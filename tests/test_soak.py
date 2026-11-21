"""Soak test: keep the whole window busy for a while and watch for leaks.

Cycles every tab, spins and zooms the globe, refreshes, switches units, and turns the
desktop widget on and off, sampling memory, threads and open files throughout. Then
measures CPU while the window sits idle on the Forecast tab and on the rotating globe.

Length: WD_SOAK_SECONDS (default 60). The release check ran it for 600 s; see TEST_REPORT.md.
Offscreen Qt only - a real display, GPU and compositor can behave differently.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import gc
import os
import resource
import threading
import time
import unittest

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtTest import QTest

from rbsb_weather.main_window import MainWindow

SECONDS = float(os.environ.get("WD_SOAK_SECONDS", "60"))


def rss_kb() -> int:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def cpu_s() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


class TestSoak(TempEnvTestCase):
    def test_soak(self):
        qapp()
        w = MainWindow(client=self.client(), enable_tray=False)
        w.resize(1100, 760)
        w.show()
        for i in range(3):
            w.add_location(self.place(i))
        self.assertTrue(wait_until(lambda: not w._pending, 10))
        base_threads, base_fds = threading.active_count(), len(os.listdir("/proc/self/fd"))
        samples = []
        start = time.monotonic()
        step = 0
        try:
            while time.monotonic() - start < SECONDS:
                step += 1
                w.tabs.setCurrentIndex(step % w.tabs.count())
                QTest.qWait(150)
                if w.tabs.currentWidget() is w.globe_panel:
                    for _ in range(3):
                        w.globe_panel.view.zoom_in()
                        QTest.qWait(60)
                    for _ in range(3):
                        w.globe_panel.view.zoom_out()
                        QTest.qWait(60)
                if step % 5 == 0:
                    w.loc_list.setCurrentRow(step % 3)
                    w.refresh_selected(force=True)
                if step % 7 == 0:
                    w.set_desktop_widget(not w.settings.desktop_widget)
                if step % 11 == 0:
                    w.settings.temp_unit = "F" if w.settings.temp_unit == "C" else "C"
                    w.render()
                if step % 10 == 0:
                    gc.collect()
                    samples.append((time.monotonic() - start, rss_kb()))
            wait_until(lambda: not w._pending, 10)
            w.set_desktop_widget(False)
            QTest.qWait(300)
            gc.collect()
            QTest.qWait(300)
            threads, fds = threading.active_count(), len(os.listdir("/proc/self/fd"))

            # idle CPU: Forecast tab, then the globe (which keeps rotating)
            idle = {}
            for name, idx in (("forecast", 0), ("globe", w.tabs.indexOf(w.globe_panel))):
                w.tabs.setCurrentIndex(idx)
                QTest.qWait(1500)
                c0, t0 = cpu_s(), time.monotonic()
                QTest.qWait(8000)
                idle[name] = 100 * (cpu_s() - c0) / (time.monotonic() - t0)
        finally:
            w._quitting = True
            w.close()
            w.deleteLater()
            QTest.qWait(50)

        third = [r for t, r in samples if t >= SECONDS / 3]
        early, late = (third[0], samples[-1][1]) if third else (samples[0][1], samples[-1][1])
        print("\n--- soak results ---")
        print(f"  soak {SECONDS:.0f} s, {step} steps: RSS {samples[0][1] // 1024} MB at start, "
              f"{early // 1024} MB at 1/3, {late // 1024} MB at end (peak {max(r for _, r in samples) // 1024} MB)")
        print(f"  soak threads {threads} (base {base_threads}), fds {fds} (base {base_fds})")
        print(f"  idle CPU: forecast tab {idle['forecast']:.1f}%, rotating globe {idle['globe']:.1f}% of one core")
        # after the first third (caches warm), memory must level off, not keep climbing
        self.assertLess(late - early, 40 * 1024, "memory kept growing during the soak")
        self.assertLessEqual(threads, base_threads + 2)
        self.assertLessEqual(fds, base_fds + 4)
        self.assertLess(idle["forecast"], 25.0)


if __name__ == "__main__":
    unittest.main()
