"""Tests for fast connections (broken-IPv6 stall fix) and the connection test."""

from __future__ import annotations

import os
import socket
import time
import unittest
from unittest import mock

from helpers import TempEnvTestCase, qapp, wait_until

from weatherdesk import net
from weatherdesk.api import OpenMeteoClient
from weatherdesk.diagnostics import run_diagnostics
from weatherdesk.models import Location


class BlackHole:
    """A local address that never answers a connection attempt (like broken IPv6).

    A listener whose accept queue is already full: the kernel silently drops
    further connection attempts, so connect() hangs until its timeout.
    """

    def __init__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(0)
        self.port = self.srv.getsockname()[1]
        self.fill = []
        for _ in range(4):
            c = socket.socket()
            c.setblocking(False)
            c.connect_ex(("127.0.0.1", self.port))
            self.fill.append(c)
        time.sleep(0.15)

    def close(self):
        for c in self.fill:
            c.close()
        self.srv.close()


def _closed_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _ai(port):
    return (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))


def fd_count():
    return len(os.listdir("/proc/self/fd"))


class NetCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.bh = BlackHole()
        self._real_gai = socket.getaddrinfo
        self.addrs: list = []

        def fake(host, port, *a, **k):
            if host == "weather.test":
                return list(self.addrs)
            return self._real_gai(host, port, *a, **k)
        self._patch = mock.patch("socket.getaddrinfo", side_effect=fake)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.bh.close()
        super().tearDown()

    def make_client(self, timeout=15.0):
        p = self.server.port
        return OpenMeteoClient(f"http://weather.test:{p}/v1/forecast",
                               f"http://weather.test:{p}/v1/search", timeout=timeout)


class TestFastConnect(NetCase):
    def test_dead_first_address_does_not_stall(self):
        self.addrs = [_ai(self.bh.port), _ai(self.server.port)]
        st = {}
        t = time.monotonic()
        s = net.fast_create_connection(("weather.test", 1), 15, stats=st)
        elapsed = time.monotonic() - t
        s.close()
        self.assertLess(elapsed, 1.0)
        self.assertEqual(st["attempts"], 2)
        self.assertEqual(st["family"], "IPv4")
        self.assertGreaterEqual(st["connect_ms"], 200)   # waited one stagger interval

    def test_refused_first_address_moves_on_immediately(self):
        self.addrs = [_ai(_closed_port()), _ai(self.server.port)]
        t = time.monotonic()
        net.fast_create_connection(("weather.test", 1), 15).close()
        self.assertLess(time.monotonic() - t, 0.15)

    def test_healthy_first_address_single_attempt(self):
        self.addrs = [_ai(self.server.port), _ai(self.bh.port)]
        st = {}
        net.fast_create_connection(("weather.test", 1), 15, stats=st).close()
        self.assertEqual(st["attempts"], 1)
        self.assertLess(st["connect_ms"], 150)

    def test_all_refused_raises_quickly(self):
        self.addrs = [_ai(_closed_port()), _ai(_closed_port())]
        t = time.monotonic()
        with self.assertRaises(OSError):
            net.fast_create_connection(("weather.test", 1), 15)
        self.assertLess(time.monotonic() - t, 0.5)

    def test_all_dead_times_out_on_time(self):
        self.addrs = [_ai(self.bh.port), _ai(self.bh.port)]
        t = time.monotonic()
        with self.assertRaises(socket.timeout):
            net.fast_create_connection(("weather.test", 1), 1.0)
        self.assertAlmostEqual(time.monotonic() - t, 1.0, delta=0.4)

    def test_no_addresses(self):
        self.addrs = []
        with self.assertRaises(OSError):
            net.fast_create_connection(("weather.test", 1), 2)

    def test_connected_socket_is_blocking_with_timeout(self):
        self.addrs = [_ai(self.server.port)]
        s = net.fast_create_connection(("weather.test", 1), 7)
        self.assertEqual(s.gettimeout(), 7.0)
        s.close()

    def test_no_socket_leak_over_many_raced_connects(self):
        self.addrs = [_ai(self.bh.port), _ai(self.server.port)]
        net.fast_create_connection(("weather.test", 1), 5).close()
        time.sleep(0.3)
        before = fd_count()
        for _ in range(30):
            net.fast_create_connection(("weather.test", 1), 5, stagger=0.02).close()
        # The in-process fake server may briefly hold its side of the last
        # connection; it must still return exactly to the baseline (a real
        # leak would leave up to 30 extra descriptors here).
        deadline = time.monotonic() + 2
        while fd_count() > before and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertLessEqual(fd_count(), before)

    def test_interleave(self):
        A, B = socket.AF_INET6, socket.AF_INET
        infos = [(A, 0, 0, "", "a1"), (A, 0, 0, "", "a2"), (B, 0, 0, "", "b1"), (B, 0, 0, "", "b2")]
        self.assertEqual([i[4] for i in net._interleave(infos)], ["a1", "b1", "a2", "b2"])
        self.assertEqual(net._interleave([]), [])


class TestClientUsesFastConnect(NetCase):
    def test_fast_connect_used(self):
        # Regression: http.client sets _create_connection in __init__, which
        # silently shadowed a class-level override in the first attempt.
        c = net.FastHTTPSConnection("example.invalid")
        self.assertIs(c._create_connection, net.fast_create_connection)
        c = net.FastHTTPConnection("example.invalid")
        self.assertIs(c._create_connection, net.fast_create_connection)

    def test_forecast_and_search_fast_with_dead_first_address(self):
        """The reported bug: v1.0.0 took the full 15 s timeout per request here."""
        self.addrs = [_ai(self.bh.port), _ai(self.server.port)]
        c = self.make_client(timeout=15)
        t = time.monotonic()
        fc = c.fetch_forecast(self.place(0))
        res = c.search_locations("Auck")
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertEqual(res[0].name, "Auckland")
        self.assertEqual(len(fc.daily), 7)

    def test_error_paths_still_mapped(self):
        from weatherdesk.api import ApiError, NetworkError
        self.addrs = [_ai(_closed_port())]
        with self.assertRaises(NetworkError):
            self.make_client().fetch_forecast(self.place(0))
        self.addrs = [_ai(self.bh.port)]
        with self.assertRaises(NetworkError):
            self.make_client(timeout=0.6).fetch_forecast(self.place(0))
        self.addrs = [_ai(self.server.port)]
        self.server.mode = "http500"
        with self.assertRaises(ApiError):
            self.make_client().fetch_forecast(self.place(0))


class TestDiagnostics(TempEnvTestCase):
    def test_report_ok(self):
        lines = []
        rep = run_diagnostics(self.client(), progress=lines.append)
        self.assertIn("Created By Shane BlackbuRn", rep)
        self.assertIn("[127.0.0.1]", rep)
        self.assertIn("IPv4: OK", rep)
        self.assertIn("Location search: OK", rep)
        self.assertIn("Forecast download: OK", rep)
        self.assertIn("Everything looks good", rep)
        self.assertEqual("\n".join(lines), rep)

    def test_report_failure(self):
        self.server.mode = "http500"
        rep = run_diagnostics(self.client())
        self.assertIn("Forecast download: FAILED", rep)
        self.assertIn("could not be reached", rep)

    def test_report_slow(self):
        self.server.delay = 1.6
        rep = run_diagnostics(self.client(timeout=5))
        self.assertIn("← slow", rep)
        self.assertIn("responded slowly", rep)

    def test_cli_diagnose_flag(self):
        from weatherdesk import app
        with mock.patch("weatherdesk.diagnostics.run_diagnostics", return_value="REPORT") as m, \
                mock.patch("builtins.print") as pr:
            self.assertEqual(app.main(["--diagnose"]), 0)
        m.assert_called_once()
        pr.assert_called_with("REPORT")


class TestDiagnosticsDialog(TempEnvTestCase):
    def test_dialog_runs_and_reports(self):
        qapp()
        from PyQt6.QtTest import QTest
        from weatherdesk.main_window import MainWindow
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        w.show_connection_test()
        w._start_diag()                       # second start while running is ignored
        self.assertTrue(wait_until(lambda: not w._diag_running, 15))
        self.assertIn("Summary", w.diag_text.toPlainText())
        self.assertIn("Forecast – Open-Meteo (primary): OK", w.diag_text.toPlainText())   # 1.13: per provider
        self.assertTrue(w.diag_run_btn.isEnabled())
        self.assertEqual(self.server.count("/v1/forecast"), 1)
        w._diag_dialog.close()
        QTest.qWait(50)
        self.assertIsNone(w._diag_dialog)
        w._quitting = True
        w.close()
        w.deleteLater()


if __name__ == "__main__":
    unittest.main()
