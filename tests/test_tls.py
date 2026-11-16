"""Secure-connection (TLS) fault handling – the 'handshake operation timed out' bug.

Uses a real HTTPS fake server with a throwaway certificate (certificate checks
stay ON) and a 'silent' server that accepts connections but never answers,
which is exactly what a stalled TLS handshake looks like to the app.
"""

from __future__ import annotations

import socket
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempEnvTestCase, qapp, wait_until
from tls_fixtures import HOST, SilentServer, TLSFakeServer, client_context, make_cert, openssl_available

from weatherdesk import net
from weatherdesk.api import ApiError, NetworkError, OpenMeteoClient

V4, V6 = socket.AF_INET, socket.AF_INET6


def ai(port, fam=V4, ip="127.0.0.1"):
    return (fam, socket.SOCK_STREAM, 6, "", (ip, port) if fam == V4 else (ip, port, 0, 0))


@unittest.skipUnless(openssl_available(), "openssl command not available")
class TLSCase(TempEnvTestCase):
    @classmethod
    def setUpClass(cls):
        cls.certdir = Path(tempfile.mkdtemp(prefix="wd-cert-"))
        cls.cert, cls.key = make_cert(cls.certdir)

    def setUp(self):
        super().setUp()
        self.tls = TLSFakeServer(self.cert, self.key).start()
        self.silent = SilentServer()
        self.addrs: list = []
        real = socket.getaddrinfo

        def fake(host, port, family=0, *a, **k):
            if host == HOST:
                res = [x for x in self.addrs if family in (0, x[0])]
                if not res:
                    raise socket.gaierror(-2, "Name or service not known")
                return res
            return real(host, port, family, *a, **k)
        self._p1 = mock.patch("socket.getaddrinfo", side_effect=fake)
        self._p1.start()
        self._p2 = mock.patch.object(net, "HANDSHAKE_TIMEOUT", 1.0)
        self._p2.start()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        self.silent.close()
        self.tls.stop()
        net.reset_health()
        super().tearDown()

    def client(self, timeout=15.0, trusted=True):
        return OpenMeteoClient(self.tls.forecast_url, self.tls.geocode_url, timeout=timeout,
                               ssl_context=client_context(self.cert) if trusted else None)


class TestHandshakeStall(TLSCase):
    def test_reported_bug_recovers_by_retrying_elsewhere(self):
        """v1.2.1: 'Could not reach the weather service (_ssl.c:983: The handshake
        operation timed out)' on every refresh. Now: one stalled attempt, then success."""
        self.addrs = [ai(self.silent.port), ai(self.tls.port)]
        c = self.client()
        t0 = time.monotonic()
        fc = c.fetch_forecast(self.place(0))
        first = time.monotonic() - t0
        self.assertEqual(len(fc.daily), 7)
        self.assertLess(first, net.HANDSHAKE_TIMEOUT + 1.0)        # not the 15 s full timeout
        self.assertGreaterEqual(first, net.HANDSHAKE_TIMEOUT * 0.9)
        self.assertEqual(self.silent.connections, 1)
        t0 = time.monotonic()
        c.fetch_forecast(self.place(0))
        c.search_locations("Auck")
        self.assertLess(time.monotonic() - t0, 0.5)                 # the bad route is now avoided
        self.assertEqual(self.silent.connections, 1)
        self.assertIn(f"127.0.0.1:{self.silent.port}", net.health_snapshot()["addresses"])

    def test_v1_2_1_behaviour_reproduced_without_the_fix(self):
        """Guard: with retries disabled the original error comes back (proves the test
        really exercises the fault)."""
        self.addrs = [ai(self.silent.port), ai(self.tls.port)]
        c = self.client()
        with mock.patch.object(NetworkError, "__init__",
                               lambda s, m, retryable=False: Exception.__init__(s, m) or
                               setattr(s, "retryable", False)):
            with self.assertRaises(NetworkError) as cm:
                c.fetch_forecast(self.place(0))
        self.assertIn("secure connection", str(cm.exception))

    def test_only_route_stalls_fails_in_bounded_time_with_clear_message(self):
        self.addrs = [ai(self.silent.port)]
        t0 = time.monotonic()
        with self.assertRaises(NetworkError) as cm:
            self.client().fetch_forecast(self.place(0))
        el = time.monotonic() - t0
        self.assertLess(el, 2 * net.HANDSHAKE_TIMEOUT + 1.0)       # exactly one retry
        self.assertEqual(self.silent.connections, 2)
        self.assertIn("secure connection to the weather service timed out", str(cm.exception))

    def test_reading_still_gets_the_full_timeout(self):
        # handshake limit 1 s, server takes 1.6 s to answer: must still succeed
        self.addrs = [ai(self.tls.port)]
        self.tls.delay = 1.6
        fc = self.client(timeout=5).fetch_forecast(self.place(0))
        self.assertEqual(len(fc.daily), 7)
        self.assertEqual(self.tls.count("/v1/forecast"), 1)

    def test_certificate_errors_are_not_retried_or_bypassed(self):
        self.addrs = [ai(self.tls.port)]
        with self.assertRaises(NetworkError) as cm:
            self.client(trusted=False).fetch_forecast(self.place(0))
        self.assertFalse(cm.exception.retryable)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(cm.exception))
        self.assertEqual(self.tls.count("/v1/forecast"), 0)
        self.assertEqual(net.health_snapshot()["addresses"], [])

    def test_server_errors_are_not_retried(self):
        self.addrs = [ai(self.tls.port)]
        self.tls.mode = "http500"
        with self.assertRaises(ApiError):
            self.client().fetch_forecast(self.place(0))
        self.assertEqual(self.tls.count("/v1/forecast"), 1)

    def test_refused_connection_not_retried(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); dead = s.getsockname()[1]; s.close()
        self.addrs = [ai(dead)]
        c = self.client()
        with mock.patch.object(c, "_get_json_once", wraps=c._get_json_once) as spy:
            with self.assertRaises(NetworkError) as cm:
                c.fetch_forecast(self.place(0))
        self.assertEqual(spy.call_count, 1)
        self.assertFalse(cm.exception.retryable)

    def test_plain_http_silent_server_also_recovers(self):
        self.addrs = [ai(self.silent.port), ai(self.server.port)]
        c = OpenMeteoClient(f"http://{HOST}:{self.server.port}/v1/forecast",
                            f"http://{HOST}:{self.server.port}/v1/search", timeout=1.0)
        # the patched resolver returns full (ip, port) pairs, so the URL's port is ignored
        fc = c.fetch_forecast(self.place(0))
        self.assertEqual(len(fc.daily), 7)


def _netns_ok() -> bool:
    import os
    import shutil
    import subprocess
    if os.geteuid() != 0 or not all(shutil.which(t) for t in ("ip", "iptables", "ethtool")):
        return False
    name = f"wdprobe{os.getpid()}"
    ok = subprocess.run(["ip", "netns", "add", name], capture_output=True).returncode == 0
    subprocess.run(["ip", "netns", "del", name], capture_output=True)
    return ok


@unittest.skipUnless(openssl_available() and _netns_ok(),
                     "needs root, ip/iptables/ethtool and network namespaces")
class TestPathMtuBlackHole(TempEnvTestCase):
    """Exactly Shane's case: ONE server address, the TCP connection works, but the
    server's full-size packets (its certificate) are silently dropped on the route,
    so the TLS handshake stalls ('_ssl.c:983: The handshake operation timed out').

    Simulated faithfully: the HTTPS server runs in its own network namespace behind
    a virtual cable (veth); packets over 1200 bytes arriving from it are dropped on
    the receive path with no ICMP 'too big' message - a path-MTU black hole."""

    @classmethod
    def setUpClass(cls):
        import os
        import subprocess
        import sys
        cls.certdir = Path(tempfile.mkdtemp(prefix="wd-cert-"))
        cls.cert, cls.key = make_cert(cls.certdir)
        n = os.getpid() % 10000
        cls.ns, cls.vc, cls.vs = f"wdmtu{n}", f"wdc{n}", f"wds{n}"
        cls.cip, cls.sip, cls.port = "10.77.0.1", "10.77.0.2", 8443
        run = lambda *a: subprocess.run(list(a), check=True, capture_output=True)
        cls.srv = None
        try:
            cls._build_network(run)
        except BaseException:
            cls.tearDownClass()                     # never leave namespaces/rules behind
            raise

    @classmethod
    def _build_network(cls, run):
        import subprocess
        import sys
        run("ip", "netns", "add", cls.ns)
        run("ip", "link", "add", cls.vc, "type", "veth", "peer", "name", cls.vs)
        run("ip", "link", "set", cls.vs, "netns", cls.ns)
        run("ip", "addr", "add", f"{cls.cip}/24", "dev", cls.vc)
        run("ip", "link", "set", cls.vc, "up")
        run("ip", "netns", "exec", cls.ns, "ip", "addr", "add", f"{cls.sip}/24", "dev", cls.vs)
        run("ip", "netns", "exec", cls.ns, "ip", "link", "set", cls.vs, "up")
        run("ip", "netns", "exec", cls.ns, "ip", "link", "set", "lo", "up")
        # make both ends send/receive real wire-size packets (a veth would otherwise pass
        # 64 KB offload "super-packets" straight through, which no real network does)
        run("ethtool", "-K", cls.vc, "gro", "off", "tso", "off", "gso", "off")
        run("ip", "netns", "exec", cls.ns, "ethtool", "-K", cls.vs, "gro", "off", "tso", "off", "gso", "off")
        cls.rule = ["INPUT", "-i", cls.vc, "-p", "tcp", "--sport", str(cls.port),
                    "-m", "length", "--length", "1200:65535", "-j", "DROP"]
        run("iptables", "-I", *cls.rule)
        cls.srv = subprocess.Popen(
            ["ip", "netns", "exec", cls.ns, sys.executable, str(Path(__file__).with_name("tls_netns_server.py")),
             cls.sip, str(cls.port), str(cls.cert), str(cls.key)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        first = cls.srv.stdout.readline().strip()
        if first != "serving":
            try:
                cls.srv.wait(5)
            except subprocess.TimeoutExpired:
                pass
            out = first + "\n" + (cls.srv.stdout.read() if cls.srv.poll() is not None else "")
            raise RuntimeError(f"namespace server failed to start: {out!r}")

    @classmethod
    def tearDownClass(cls):
        import subprocess
        if getattr(cls, "srv", None) is not None:
            cls.srv.terminate()
            try:
                cls.srv.wait(5)
            except subprocess.TimeoutExpired:
                cls.srv.kill()
            cls.srv = None
        subprocess.run(["iptables", "-D", *cls.rule], capture_output=True)
        subprocess.run(["ip", "link", "del", cls.vc], capture_output=True)
        subprocess.run(["ip", "netns", "del", cls.ns], capture_output=True)

    def setUp(self):
        super().setUp()
        real = socket.getaddrinfo
        sip, port = self.sip, self.port

        def fake(host, p, family=0, *a, **k):
            if host == HOST:
                if family not in (0, V4):
                    raise socket.gaierror(-2, "no address")
                return [ai(port, V4, sip)]                   # only ONE address, like api.open-meteo.com
            return real(host, p, family, *a, **k)
        self._p1 = mock.patch("socket.getaddrinfo", side_effect=fake)
        self._p1.start()
        self._p2 = mock.patch.object(net, "HANDSHAKE_TIMEOUT", 1.0)
        self._p2.start()

    def tearDown(self):
        self._p2.stop()
        self._p1.stop()
        net.reset_health()
        super().tearDown()

    def client(self):
        return OpenMeteoClient(f"https://{HOST}:{self.port}/v1/forecast",
                               f"https://{HOST}:{self.port}/v1/search", timeout=15,
                               ssl_context=client_context(self.cert))

    def test_without_small_packets_it_fails_like_v1_2_1(self):
        with mock.patch.object(net, "clamped", lambda a, p: False):
            with self.assertRaises(NetworkError) as cm:
                self.client().fetch_forecast(self.place(0))
        self.assertIn("secure connection to the weather service timed out", str(cm.exception))

    def test_single_address_recovers_with_small_packets(self):
        c = self.client()
        t0 = time.monotonic()
        fc = c.fetch_forecast(self.place(0))
        first = time.monotonic() - t0
        self.assertEqual(len(fc.daily), 7)
        self.assertLess(first, net.HANDSHAKE_TIMEOUT + 1.5)
        self.assertIn(f"{self.sip}:{self.port}", net.health_snapshot()["small_packets"])
        t0 = time.monotonic()
        for _ in range(3):
            c.fetch_forecast(self.place(0))
            c.search_locations("Auck")
        self.assertLess(time.monotonic() - t0, 1.0)       # no more stalls

    def test_remembered_across_restarts(self):
        import json
        health = self.tmp / "network.json"
        with mock.patch.object(net, "HEALTH_FILE", str(health)):
            self.client().fetch_forecast(self.place(0))
            saved = json.loads(health.read_text())
            self.assertEqual(saved["small_packets"][0]["address"], self.sip)
            net.reset_health()                            # "restart": memory cleared, file kept
            t0 = time.monotonic()
            self.client().fetch_forecast(self.place(0))
            self.assertLess(time.monotonic() - t0, 0.8)   # loaded from disk: no stall at all

    def test_diagnostics_confirms_packet_size_problem(self):
        from weatherdesk import diagnostics
        with mock.patch.object(diagnostics, "PROBE_TIMEOUT", 1.0):
            rep = diagnostics.run_diagnostics(self.client())
        self.assertIn("secure handshake STALLS", rep)
        self.assertIn("With small packets (MSS 1000): WORKS", rep)
        self.assertIn("Forecast download: OK", rep)       # the app itself recovered


class TestAddressOrdering(unittest.TestCase):
    def setUp(self):
        net.reset_health()

    def tearDown(self):
        net.reset_health()

    def test_bad_address_tried_last(self):
        infos = [ai(1, ip="10.0.0.1"), ai(1, ip="10.0.0.2")]
        net.mark_bad("10.0.0.1", 1, V4)
        self.assertEqual([i[4][0] for i in net.order_addresses(infos)], ["10.0.0.2", "10.0.0.1"])

    def test_ipv6_failure_puts_ipv4_first(self):
        infos = [ai(443, V6, "2001:db8::1"), ai(443, V6, "2001:db8::2"), ai(443, V4, "192.0.2.1")]
        self.assertEqual(net.order_addresses(infos)[0][0], V6)          # resolver preference
        net.mark_bad("2001:db8::1", 443, V6)
        order = net.order_addresses(infos)
        self.assertEqual(order[0][0], V4)
        self.assertEqual(order[-1][4][0], "2001:db8::1")
        self.assertTrue(net.health_snapshot()["ipv6_avoided"])

    def test_avoidance_expires(self):
        infos = [ai(1, ip="10.0.0.1"), ai(1, ip="10.0.0.2")]
        net.mark_bad("10.0.0.1", 1, V4)
        with mock.patch("time.monotonic", return_value=time.monotonic() + net.BAD_FOR_S + 1):
            self.assertEqual(net.order_addresses(infos)[0][4][0], "10.0.0.1")
            self.assertEqual(net.health_snapshot()["addresses"], [])

    def test_clamp_sets_small_segments_on_the_socket(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with mock.patch("socket.getaddrinfo", return_value=[ai(port)]):
                s1 = net.fast_create_connection(("x", port), 3)
                normal = s1.getsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG)
                s1.close()
                net.mark_bad("127.0.0.1", port, V4)
                s2 = net.fast_create_connection(("x", port), 3)
                small = s2.getsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG)
                s2.close()
            self.assertLessEqual(small, net.CLAMP_MSS)
            self.assertGreater(normal, net.CLAMP_MSS)
        finally:
            srv.close()

    def test_corrupt_health_file_ignored(self):
        tmp = Path(tempfile.mkdtemp()) / "network.json"
        tmp.write_text("{garbage")
        with mock.patch.object(net, "HEALTH_FILE", str(tmp)):
            net.reset_health()
            self.assertFalse(net.clamped("1.2.3.4", 443))
            net.mark_bad("1.2.3.4", 443, V4)               # rewrites it cleanly
            self.assertTrue(net.clamped("1.2.3.4", 443))
        import json
        self.assertEqual(json.loads(tmp.read_text())["small_packets"][0]["address"], "1.2.3.4")

    def test_only_bad_addresses_still_tried(self):
        infos = [ai(1, ip="10.0.0.1")]
        net.mark_bad("10.0.0.1", 1, V4)
        self.assertEqual(len(net.order_addresses(infos)), 1)


class TestDiagnosticsTLS(TLSCase):
    def test_healthy_reports_handshake(self):
        from weatherdesk.diagnostics import run_diagnostics
        self.addrs = [ai(self.tls.port)]
        rep = run_diagnostics(self.client())
        self.assertIn("secure handshake", rep)
        self.assertIn("Everything looks good", rep)

    def test_stall_is_explained(self):
        from weatherdesk import diagnostics
        self.addrs = [ai(self.silent.port)]
        with mock.patch.object(diagnostics, "PROBE_TIMEOUT", 1.0):
            rep = diagnostics.run_diagnostics(self.client())
        self.assertIn("secure handshake STALLS", rep)
        self.assertIn("MTU", rep)
        self.assertIn("Currently avoiding", rep)


class TestGuiRecovers(TLSCase):
    def test_window_shows_weather_not_error(self):
        qapp()
        from weatherdesk.main_window import MainWindow
        self.addrs = [ai(self.silent.port), ai(self.tls.port)]
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending, 10))
        self.assertNotIn("Couldn't update", w.message_label.text())
        self.assertRegex(w.temp_label.text(), r"°C$")
        w._quitting = True
        w.close()
        w.deleteLater()


if __name__ == "__main__":
    unittest.main()
