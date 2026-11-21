"""Tests for fast connections (broken-IPv6 stall fix) and the connection test."""

from __future__ import annotations

import os
import socket
import time
import unittest
from unittest import mock

from helpers import TempEnvTestCase, qapp, wait_until

from rbsb_weather import net
from rbsb_weather.api import OpenMeteoClient
from rbsb_weather.diagnostics import run_diagnostics
from rbsb_weather.models import Location


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


def client_fd_count(server_port: int) -> int:
    return len(counted_fds(server_port))


def counted_fds(server_port: int) -> dict:
    """Open descriptors, leaving out the in-process fake server's own side of its
    connections (and its listener): those are TCP sockets whose LOCAL port is the
    server's port. The fake server closes them from its own thread a moment after the
    client hangs up, which on a busy machine can take over 2 s. That was seen 2 times
    in about 300 runs, and each time the socket closed by itself about 50 ms later,
    with no RBSB-Weather code running. RBSB-Weather's sockets (client side, a random
    local port) are all still counted, so a real leak still fails the test."""
    server_inodes = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = open(table).read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if int(f[1].rsplit(":", 1)[1], 16) == server_port:
                server_inodes.add(f[9])
    counted = {}                                    # fd number -> what it is
    for fd in os.listdir("/proc/self/fd"):
        try:
            target = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            continue                                # closed while we looked
        if target.startswith("socket:[") and target[8:-1] in server_inodes:
            continue
        counted[int(fd)] = target
    return counted


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
        port = self.server.port
        before = client_fd_count(port)
        server_before = fd_count() - before          # the fake server's own sockets
        for _ in range(30):
            net.fast_create_connection(("weather.test", 1), 5, stagger=0.02).close()
        # Only RBSB-Weather's side is counted (see client_fd_count); it must return
        # exactly to the baseline. A real leak would leave up to 30 extra here.
        deadline = time.monotonic() + 2
        while client_fd_count(port) > before and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertLessEqual(client_fd_count(port), before)
        # let the fake server finish closing its side too, so later tests start clean
        deadline = time.monotonic() + 10
        while fd_count() - client_fd_count(port) > server_before and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_leak_check_catches_a_real_leak(self):
        """The check above must still fail for a leak on RBSB-Weather's side."""
        self.addrs = [_ai(self.server.port)]
        port = self.server.port
        before = counted_fds(port)
        kept = [net.fast_create_connection(("weather.test", 1), 5) for _ in range(5)]   # "leaked"
        try:
            after = counted_fds(port)
            # Each leaked connection must be counted. (2.1.2: this used to compare the
            # process's total, which failed once in ~25 full runs when something else
            # in the test process opened 2 files at that moment; checking the leaked
            # sockets themselves is exact, and still fails if the check missed a leak.)
            mine = {k.fileno() for k in kept}
            missed = mine - set(after)
            self.assertEqual(missed, set(), f"leaked sockets not counted: {missed}")
            self.assertFalse(mine & set(before))
            self.assertGreaterEqual(len(after) - len(before), 5,
                                    f"new: {[after[f] for f in set(after) - set(before)]}")
        finally:
            for s in kept:
                s.close()

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
        from rbsb_weather.api import ApiError, NetworkError
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
        from rbsb_weather import app
        with mock.patch("rbsb_weather.diagnostics.run_diagnostics", return_value="REPORT") as m, \
                mock.patch("builtins.print") as pr:
            self.assertEqual(app.main(["--diagnose"]), 0)
        m.assert_called_once()
        pr.assert_called_with("REPORT")


class TestDiagnosticsDialog(TempEnvTestCase):
    def test_dialog_runs_and_reports(self):
        qapp()
        from PyQt6.QtTest import QTest
        from rbsb_weather.main_window import MainWindow
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
