"""Stress / leak tests: repeated refreshes (1/10/25/50), stalled sockets, window cycles.

Measured after each batch: Python threads, worker count, open file descriptors,
QObjects owned by the window, and resident memory. Results are printed so they
can be copied into the test report.
"""

from __future__ import annotations

import gc
import os
import threading
import time
import unittest

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QObject
from PyQt6.QtTest import QTest

from weatherdesk.main_window import MainWindow

REPORT: list[str] = []


def fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def rss_kb() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


class StressCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()

    def snapshot(self, w):
        gc.collect()
        QTest.qWait(50)
        return dict(threads=threading.active_count(), workers=w.worker.active, fds=fd_count(),
                    qobjects=len(w.findChildren(QObject)), rss=rss_kb())


class TestRepeatedRefresh(StressCase):
    def test_refresh_batches(self):
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        # warm-up so lazily-created Qt objects are not counted as leaks
        for _ in range(3):
            w.refresh_selected(force=True)
            self.assertTrue(wait_until(lambda: not w._pending))
        base = self.snapshot(w)
        done = 0
        for batch in (1, 10, 25, 50):
            for _ in range(batch):
                w.refresh_selected(force=True)
                self.assertTrue(wait_until(lambda: not w._pending, 5))
                done += 1
            self.assertTrue(wait_until(lambda: w.worker.active == 0 and
                                       threading.active_count() <= base["threads"], 5))
            s = self.snapshot(w)
            REPORT.append(f"refresh x{batch:<3} threads {s['threads']} (base {base['threads']}), "
                          f"workers {s['workers']}, fds {s['fds']} (base {base['fds']}), "
                          f"qobjects {s['qobjects']} (base {base['qobjects']}), "
                          f"rss {s['rss'] - base['rss']:+d} KB")
            self.assertEqual(s["workers"], 0)
            self.assertLessEqual(s["threads"], base["threads"])
            self.assertLessEqual(s["fds"], base["fds"] + 2)
            self.assertEqual(s["qobjects"], base["qobjects"])
        self.assertEqual(w.errors, {})
        self.assertGreaterEqual(self.server.count("/v1/forecast"), done)
        # memory growth across 86 refreshes must stay small (no per-refresh leak)
        self.assertLess(self.snapshot(w)["rss"] - base["rss"], 2000)
        w._quitting = True
        w.close()
        w.deleteLater()

    def test_repeated_unit_switch_and_render(self):
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        base = self.snapshot(w)
        for i in range(200):
            w.set_unit("temp_unit", "F" if i % 2 else "C")
            if i % 20 == 0:
                QTest.qWait(1)
        s = self.snapshot(w)
        REPORT.append(f"render x200    qobjects {s['qobjects']} (base {base['qobjects']}), "
                      f"rss {s['rss'] - base['rss']:+d} KB")
        self.assertEqual(s["qobjects"], base["qobjects"])
        w._quitting = True
        w.close()
        w.deleteLater()


class TestStalledNetwork(StressCase):
    def test_ui_stays_responsive_and_request_times_out(self):
        self.server.delay = 3.0
        w = MainWindow(client=self.client(timeout=1.0), enable_tray=False)
        w.show()
        w.add_location(self.place(0))
        # event loop keeps running while the request is stalled
        t0 = time.monotonic()
        ticks = 0
        while time.monotonic() - t0 < 0.5:
            QTest.qWait(10)
            ticks += 1
        self.assertGreater(ticks, 20, "event loop blocked by network call")
        self.assertIn("Loading", w.desc_label.text())
        self.assertTrue(wait_until(lambda: not w._pending, 4))
        self.assertIn("did not respond", w.message_label.text())
        self.assertTrue(wait_until(lambda: w.worker.active == 0, 3))
        REPORT.append(f"stalled socket: timed out cleanly, UI ticks during stall = {ticks}")
        w._quitting = True
        w.close()
        w.deleteLater()

    def test_close_while_request_in_flight(self):
        self.server.delay = 1.5
        w = MainWindow(client=self.client(timeout=3.0), enable_tray=False)
        w.show()
        w.add_location(self.place(0))
        QTest.qWait(100)
        self.assertTrue(w._pending)
        t0 = time.monotonic()
        w._quitting = True
        w.close()
        w.deleteLater()
        QTest.qWait(50)
        self.assertLess(time.monotonic() - t0, 0.5, "closing must not wait for the network")
        # the orphaned request finishes (or fails) without crashing the process
        QTest.qWait(2000)
        REPORT.append("close during in-flight request: closed instantly, no crash")


class TestWindowCycles(StressCase):
    def test_create_destroy_cycles(self):
        base_threads = threading.active_count()
        base_fds = fd_count()
        for _ in range(10):
            w = MainWindow(client=self.client(), enable_tray=False)
            w.show()
            if not w.settings.locations:
                w.add_location(self.place(0))
            self.assertTrue(wait_until(lambda: not w._pending))
            w._quitting = True
            w.close()
            w.deleteLater()
            QTest.qWait(20)
        gc.collect()
        self.assertTrue(wait_until(lambda: threading.active_count() <= base_threads, 3))
        REPORT.append(f"window cycles x10: threads {threading.active_count()} (base {base_threads}), "
                      f"fds {fd_count()} (base {base_fds})")
        self.assertLessEqual(fd_count(), base_fds + 3)


class TestCloseRace(StressCase):
    def test_close_while_results_arrive(self):
        """Regression for a rare segfault (about 1 run in 6 of the window-cycle test):
        a worker thread emitting its result at the very moment the closing window's
        Bridge was being destroyed. Here, 40 windows are closed while their forecast
        and Earth results are landing, at slightly different moments each time."""
        import random
        from weatherdesk import workers
        rng = random.Random(5)
        for i in range(40):
            w = MainWindow(client=self.client(), enable_tray=False)
            w.show()
            if not w.settings.locations:
                w.add_location(self.place(0))
                self.assertTrue(wait_until(lambda: not w._pending))
            self.server.delay = rng.uniform(0.0, 0.03)
            w.refresh_selected(force=True)
            w.request_earth()
            QTest.qWait(rng.randint(0, 30))
            w._quitting = True
            w.close()
            w.deleteLater()
            QTest.qWait(rng.randint(0, 5))
        self.server.delay = 0
        self.assertTrue(wait_until(lambda: workers.reap() == 0, 10))
        REPORT.append("close while results arrive x40: no crash; all retired bridges released")

    def test_emit_flood_during_window_destruction(self):
        """Deterministic version of the race: a worker thread emits non-stop through the
        window's Bridge while the window is closed and destroyed. With the Bridge owned
        by the window (before 1.8.1) this crashes the process; now the Bridge outlives
        the window until the thread is done."""
        import threading
        from weatherdesk import workers
        for i in range(15):
            w = MainWindow(client=self.client(), enable_tray=False)
            w.show()
            QTest.qWait(10)
            stop = threading.Event()
            bridge, worker = w.bridge, w.worker

            def flood():
                try:
                    while not stop.is_set():
                        bridge.diag_line.emit("x")
                except RuntimeError:
                    pass                          # wrapper noticed the object was deleted
                finally:
                    with worker._lock:
                        worker._active -= 1
            with worker._lock:
                worker._active += 1
            t = threading.Thread(target=flood, daemon=True)
            t.start()
            w._quitting = True
            w.close()
            w.deleteLater()
            QTest.qWait(15)                       # window destroyed while the thread emits
            stop.set()
            t.join(2)
            QTest.qWait(5)
        self.assertTrue(wait_until(lambda: workers.reap() == 0, 5))
        REPORT.append("emit flood during window destruction x15: no crash")


def tearDownModule():
    print("\n--- stress results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
