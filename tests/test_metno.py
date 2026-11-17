"""MET Norway as a second weather source, the automatic backup, the escalating
retries, and the quicker retry after a failed update (1.12.0).

Everything runs against the local fake server; nothing touches the internet.
Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from helpers import TempEnvTestCase, qapp, wait_until
from fake_server import METNO_PATH, make_metno

from weatherdesk import net
from weatherdesk.api import ApiError, NetworkError, OpenMeteoClient, default_client
from weatherdesk.metno import (MetNoClient, SOURCE_NAME, SUN_ALT, apparent_temperature, parse_metno,
                               sun_rise_set, wmo_code)
from weatherdesk.models import Location
from weatherdesk import earth

AKL = ZoneInfo("Pacific/Auckland")
WAIUKU = Location("Waiuku", -37.2486, 174.7300, "New Zealand", "Auckland", "Pacific/Auckland")


def dead_url(path="/v1/forecast") -> str:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return f"http://127.0.0.1:{port}{path}"


class TestSymbols(unittest.TestCase):
    def test_mapping(self):
        cases = {
            "clearsky_day": 0, "clearsky_night": 0, "fair_polartwilight": 1, "partlycloudy_day": 2,
            "cloudy": 3, "fog": 45,
            "lightrain": 61, "rain": 63, "heavyrain": 65,
            "lightrainshowers_day": 80, "rainshowers_night": 81, "heavyrainshowers_day": 82,
            "lightsnow": 71, "snow": 73, "heavysnow": 75, "lightsnowshowers_day": 85, "heavysnowshowers_day": 86,
            "lightsleet": 71, "sleetshowers_day": 85,
            "rainandthunder": 95, "heavyrainshowersandthunder_day": 95,
            "lightssleetshowersandthunder_day": 95,       # MET's own spelling
        }
        for sym, code in cases.items():
            self.assertEqual(wmo_code(sym), code, sym)
        for bad in (None, "", 7, "unknownthing"):
            self.assertIsNone(wmo_code(bad))

    def test_every_mapped_code_is_known_to_the_app(self):
        from weatherdesk import weather_codes
        bases = ["clearsky", "fair", "partlycloudy", "cloudy", "fog"]
        for kind in ("rain", "sleet", "snow"):
            for lvl in ("light", "", "heavy"):
                for sh in ("", "showers"):
                    for th in ("", "andthunder"):
                        bases.append(f"{lvl}{kind}{sh}{th}")
        for b in bases:
            self.assertIn(wmo_code(b), weather_codes.all_codes(), b)


class TestSun(unittest.TestCase):
    def test_sunrise_sunset_waiuku(self):
        rise, sett = sun_rise_set(dt.date(2026, 11, 17), WAIUKU.latitude, WAIUKU.longitude, AKL)
        # published times for Auckland on 17 Nov are about 05:59 and 20:08; Waiuku is a
        # little further west and south, so a couple of minutes later
        self.assertEqual((rise.hour, rise.tzinfo), (6, AKL))
        self.assertLess(abs((rise - rise.replace(hour=6, minute=0, second=0)).total_seconds()), 8 * 60)
        self.assertLess(abs((sett - sett.replace(hour=20, minute=10, second=0)).total_seconds()), 8 * 60)
        for t in (rise, sett):        # the sun really is on the horizon then
            self.assertAlmostEqual(earth.solar_elevation(t.astimezone(dt.timezone.utc),
                                                         WAIUKU.latitude, WAIUKU.longitude), SUN_ALT, delta=0.05)

    def test_polar_day_and_night(self):
        tz = ZoneInfo("Arctic/Longyearbyen")
        self.assertEqual(sun_rise_set(dt.date(2026, 6, 21), 78.2, 15.6, tz), (None, None))
        self.assertEqual(sun_rise_set(dt.date(2026, 12, 21), 78.2, 15.6, tz), (None, None))


class TestParse(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 17, 3, 20, tzinfo=dt.timezone.utc)      # 16:20 NZDT
        self.start = dt.datetime(2026, 11, 17, 2, 0, tzinfo=dt.timezone.utc)     # MET's first step
        self.data = make_metno(WAIUKU.latitude, WAIUKU.longitude, start=self.start)
        self.fc = parse_metno(self.data, WAIUKU, 7, now=self.now)

    def test_current(self):
        c, fc = self.fc.current, self.fc
        self.assertEqual(fc.source, SOURCE_NAME)
        self.assertEqual(c.time, "2026-11-17T16:15")                 # local, on the quarter hour
        step = self.data["properties"]["timeseries"][1]               # 03:00Z, the latest before now
        det = step["data"]["instant"]["details"]
        self.assertEqual(c.temperature, det["air_temperature"])
        self.assertEqual(c.wind_speed, 18.0)                         # 5 m/s -> km/h
        self.assertEqual(c.wind_gusts, 36.0)
        self.assertEqual(c.weather_code, wmo_code(step["data"]["next_1_hours"]["summary"]["symbol_code"]))
        self.assertTrue(c.is_day)
        self.assertEqual(c.apparent_temperature, apparent_temperature(det["air_temperature"], 75.0, 5.0))
        self.assertEqual((fc.timezone, fc.utc_offset_seconds), ("Pacific/Auckland", 13 * 3600))

    def test_hourly_is_local_and_consecutive(self):
        h = self.fc.hourly
        self.assertGreaterEqual(len(h), 48)
        self.assertEqual(h[0].time, "2026-11-17T16:00")
        for a, b in zip(h, h[1:]):
            ta, tb = dt.datetime.fromisoformat(a.time), dt.datetime.fromisoformat(b.time)
            self.assertEqual(tb - ta, dt.timedelta(hours=1))

    def test_daily(self):
        d = self.fc.daily
        self.assertEqual([x.date for x in d], [f"2026-11-{17 + i}" for i in range(7)])
        for x in d:
            self.assertLessEqual(x.temp_min, x.temp_max)
            self.assertTrue(x.sunrise.startswith(x.date) and x.sunset.startswith(x.date))
            self.assertIsNotNone(x.weather_code)
            self.assertIsNotNone(x.precipitation_probability_max)
            self.assertGreater(x.precipitation_sum, 0)
        # day 2 is entirely hourly: 24 x 0.2 mm, no double counting from 6-hour blocks
        self.assertAlmostEqual(d[1].precipitation_sum, 4.8, places=1)
        # a 6-hourly day uses the 6-hour blocks' max/min too (each block is its instant +/- 2)
        day5 = [s["data"]["instant"]["details"]["air_temperature"] for s in self.data["properties"]["timeseries"]
                if dt.datetime.fromisoformat(s["time"].replace("Z", "+00:00")).astimezone(AKL).date().isoformat()
                == d[5].date]
        self.assertEqual(d[5].temp_max, max(day5) + 2)
        self.assertEqual(d[5].temp_min, min(day5) - 2)

    def test_window_shows_parsed_forecast(self):
        """The forecast is the same model the rest of the app uses (cache round trip)."""
        from weatherdesk.api import forecast_from_dict, forecast_to_dict
        back = forecast_from_dict(json.loads(json.dumps(forecast_to_dict(self.fc))))
        self.assertEqual(back.source, SOURCE_NAME)
        self.assertEqual(back.daily, self.fc.daily)
        old = forecast_to_dict(self.fc); old.pop("source")                 # caches from 1.11
        self.assertEqual(forecast_from_dict(old).source, "Open-Meteo")

    def test_bad_responses(self):
        from weatherdesk.api import DataError
        for bad in (None, [], {}, {"properties": {}}, {"properties": {"timeseries": []}},
                    {"properties": {"timeseries": [{"time": "x", "data": {}}]}}):
            with self.assertRaises(DataError):
                parse_metno(bad, WAIUKU)

    def test_auto_timezone_uses_longitude(self):
        loc = Location("Somewhere", -37.25, 174.73, timezone="auto")
        fc = parse_metno(self.data, loc, now=self.now)
        self.assertEqual(fc.utc_offset_seconds, 12 * 3600)


class TestClientAndBackup(TempEnvTestCase):
    def metno(self, timeout=3.0):
        return MetNoClient(self.server.metno_url, timeout=timeout)

    def test_metno_request_follows_terms(self):
        fc = self.metno().fetch_forecast(WAIUKU)
        self.assertEqual(fc.source, SOURCE_NAME)
        self.assertGreater(fc.fetched_at, time.time() - 5)
        path, q = [r for r in self.server.requests if r[0] == METNO_PATH][-1]
        self.assertEqual((q["lat"], q["lon"]), ("-37.2486", "174.7300"))     # at most 4 decimals
        ua = self.server.metno_agents[-1]
        self.assertIn("WeatherDesk/", ua)
        self.assertIn("github.com/shanebl030-glitch/WeatherDesk", ua)

    def test_backup_used_when_open_meteo_unreachable(self):
        c = OpenMeteoClient(dead_url(), self.server.geocode_url, timeout=2, backup=self.metno())
        fc = c.fetch_forecast(WAIUKU)
        self.assertEqual(fc.source, SOURCE_NAME)
        self.assertEqual(len(fc.daily), 7)
        # the next refresh goes straight to the backup instead of waiting on the dead route
        with mock.patch.object(c, "fetch_open_meteo", wraps=c.fetch_open_meteo) as spy:
            c.fetch_forecast(WAIUKU)
            self.assertEqual(spy.call_count, 0)
        # ...until the main source's time-out is over
        c._down_until["primary"] = time.monotonic() - 1
        c.forecast_url = self.server.forecast_url
        self.assertEqual(c.fetch_forecast(WAIUKU).source, "Open-Meteo")

    def test_backup_used_on_server_error(self):
        self.server.mode = "http500"
        c = OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=2,
                            backup=self.metno())
        self.assertEqual(c.fetch_forecast(WAIUKU).source, SOURCE_NAME)

    def test_open_meteo_used_when_working(self):
        c = OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=2,
                            backup=self.metno())
        self.assertEqual(c.fetch_forecast(WAIUKU).source, "Open-Meteo")
        self.assertEqual(self.server.count(METNO_PATH), 0)

    def test_prefer_met_norway(self):
        c = OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=2,
                            backup=self.metno(), prefer_backup=True)
        self.assertEqual(c.fetch_forecast(WAIUKU).source, SOURCE_NAME)
        self.assertEqual(self.server.count("/v1/forecast"), 0)
        self.server.metno_mode = "http429"                 # MET busy: Open-Meteo steps in
        self.assertEqual(c.fetch_forecast(WAIUKU).source, "Open-Meteo")

    def test_both_down_gives_one_clear_error(self):
        self.server.metno_mode = "http500"
        c = OpenMeteoClient(dead_url(), self.server.geocode_url, timeout=2, backup=self.metno())
        with self.assertRaises(NetworkError) as cm:
            c.fetch_forecast(WAIUKU)
        self.assertIn("Could not reach the weather service", str(cm.exception))
        self.assertIn("other weather source (MET Norway) couldn't be reached either", str(cm.exception))
        # both are now marked as failing: both are still tried, and Open-Meteo's fault is reported
        with self.assertRaises(NetworkError) as cm:
            c.fetch_forecast(WAIUKU)
        self.assertTrue(str(cm.exception).startswith("Could not reach the weather service"))
        self.assertIn("(MET Norway)", str(cm.exception))
        self.assertFalse(cm.exception.retryable)

    def test_bad_data_from_backup_not_hidden(self):
        """A garbled reply isn't a network fault: the error is reported, not retried forever."""
        self.server.metno_mode = "badjson"
        c = OpenMeteoClient(dead_url(), self.server.geocode_url, timeout=2, backup=self.metno())
        from weatherdesk.api import DataError
        with self.assertRaises(DataError):
            c.fetch_forecast(WAIUKU)

    def test_default_client(self):
        c = default_client()
        self.assertIsInstance(c.backup, MetNoClient)
        self.assertFalse(c.prefer_backup)
        self.assertTrue(default_client("met.no").prefer_backup)

    def test_diagnostics_reports_both_sources(self):
        from weatherdesk import diagnostics
        c = OpenMeteoClient(dead_url(), self.server.geocode_url, timeout=2, backup=self.metno())
        with mock.patch.object(diagnostics, "PROBE_TIMEOUT", 1.0):
            rep = diagnostics.run_diagnostics(c)
        self.assertIn("Forecast download: FAILED", rep)
        self.assertIn("Backup forecast (MET Norway): OK", rep)
        self.assertIn("keeps updating from it automatically", rep)


class TestSmallerPackets(unittest.TestCase):
    def tearDown(self):
        net.reset_health()

    def test_second_stall_steps_down_to_minimum(self):
        net.reset_health()
        self.assertIsNone(net.clamp_mss("10.9.9.9", 443))
        net.mark_bad("10.9.9.9", 443, socket.AF_INET)
        self.assertEqual(net.clamp_mss("10.9.9.9", 443), net.CLAMP_MSS)
        net.mark_bad("10.9.9.9", 443, socket.AF_INET)
        self.assertEqual(net.clamp_mss("10.9.9.9", 443), net.CLAMP_MSS_MIN)
        self.assertTrue(net.clamped("10.9.9.9", 443))

    def test_minimum_size_applied_to_socket(self):
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        info = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))
        try:
            net.reset_health()
            net.mark_bad("127.0.0.1", port, socket.AF_INET)
            net.mark_bad("127.0.0.1", port, socket.AF_INET)
            with mock.patch("socket.getaddrinfo", return_value=[info]):
                s = net.fast_create_connection(("x", port), 3)
                mss = s.getsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG)
                s.close()
            self.assertLessEqual(mss, net.CLAMP_MSS_MIN)
        finally:
            srv.close()

    def test_health_file_keeps_size_and_reads_old_format(self):
        tmp = Path(tempfile.mkdtemp()) / "network.json"
        until = time.time() + 3600
        tmp.write_text(json.dumps({"small_packets": [
            {"address": "1.1.1.1", "port": 443, "until": until},                  # 1.11 format
            {"address": "2.2.2.2", "port": 443, "until": until, "mss": 536},
            {"address": "3.3.3.3", "port": 443, "until": until, "mss": 40}]}))   # nonsense: ignored
        with mock.patch.object(net, "HEALTH_FILE", str(tmp)):
            net.reset_health()
            self.assertEqual(net.clamp_mss("1.1.1.1", 443), net.CLAMP_MSS)
            self.assertEqual(net.clamp_mss("2.2.2.2", 443), 536)
            self.assertIsNone(net.clamp_mss("3.3.3.3", 443))
            net.mark_bad("1.1.1.1", 443, socket.AF_INET)
            saved = {i["address"]: i["mss"] for i in json.loads(tmp.read_text())["small_packets"]}
        self.assertEqual(saved, {"1.1.1.1": 536, "2.2.2.2": 536})

    def test_handshake_limit_is_per_thread_and_restored(self):
        with net.handshake_limit(9.0):
            self.assertEqual(net._tls.handshake, 9.0)
            import threading
            seen = []
            t = threading.Thread(target=lambda: seen.append(getattr(net._tls, "handshake", None)))
            t.start(); t.join()
            self.assertEqual(seen, [None])
        self.assertIsNone(net._tls.handshake)


class TestWindow(TempEnvTestCase):
    """Quicker retries after a failure, the calmer message, and the source menu."""

    def setUp(self):
        super().setUp()
        self.app = qapp()
        from weatherdesk.main_window import MainWindow
        self.MW = MainWindow
        self.windows = []

    def tearDown(self):
        from PyQt6.QtTest import QTest
        for w in self.windows:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        net.reset_health()
        super().tearDown()

    def make(self, backup=True):
        c = OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=2,
                            backup=MetNoClient(self.server.metno_url, timeout=2) if backup else None)
        w = self.MW(client=c, enable_tray=False)
        self.windows.append(w)
        w.show()
        return w

    def add(self, w, i=0):
        w.add_location(self.place(i))
        k = self.place(i).key
        self.assertTrue(wait_until(lambda: k in w.forecasts and k not in w._pending))
        return k

    def test_retries_quickly_then_backs_off(self):
        from weatherdesk import main_window as MWm
        w = self.make(backup=False)
        k = self.add(w)
        self.server.mode = "http500"
        delays = []
        for _ in range(5):
            w.refresh_selected(force=True)
            self.assertTrue(wait_until(lambda: k not in w._pending))
            self.assertTrue(w.retry_timer.isActive())
            delays.append(w.retry_timer.interval() // 1000)
        self.assertEqual(delays, [30, 60, 120, 300, 300])
        self.assertEqual(w._retry_delay(k), MWm.RETRY_AFTER_FAIL_S)
        # the retry timer firing really retries, and success resets the back-off
        self.server.mode = "ok"
        n = self.server.count("/v1/forecast")
        w.retry_timer.timeout.emit()
        self.assertTrue(wait_until(lambda: self.server.count("/v1/forecast") == n + 1 and k not in w._pending))
        self.assertNotIn(k, w.errors)
        self.assertNotIn(k, w._fail_count)
        self.assertEqual(w._retry_delay(k), 30)

    def test_no_retry_timer_when_auto_refresh_off(self):
        w = self.make(backup=False)
        k = self.add(w)
        w.set_refresh_minutes(0)
        self.server.mode = "http500"
        w.refresh_selected(force=True)
        self.assertTrue(wait_until(lambda: k not in w._pending))
        self.assertFalse(w.retry_timer.isActive())

    def test_recent_data_gets_a_calm_message(self):
        w = self.make(backup=False)
        k = self.add(w)
        self.server.mode = "http500"
        w.refresh_selected(force=True)
        self.assertTrue(wait_until(lambda: k not in w._pending))
        txt = w.message_label.text()
        self.assertIn("Couldn't update", txt)
        self.assertIn("Showing weather from just now; retrying automatically.", txt)
        self.assertNotIn("bold", w.message_label.styleSheet())
        w.forecasts[k].fetched_at = time.time() - 4 * 3600            # old data: the strong warning
        w.render()
        self.assertIn("4 h ago", w.message_label.text())
        self.assertIn("bold", w.message_label.styleSheet())

    def test_open_meteo_failing_still_updates_from_met_norway(self):
        """The reported problem: Open-Meteo can't be reached, the weather keeps updating."""
        w = self.make()
        self.server.mode = "http500"
        k = self.add(w)
        self.assertEqual(w.forecasts[k].source, SOURCE_NAME)
        self.assertNotIn(k, w.errors)
        self.assertNotIn("Couldn't update", w.message_label.text())
        self.assertIn("MET Norway", w.status_label.text())
        self.assertNotIn("Open-Meteo.com", w.status_label.text())

    def test_source_menu(self):
        w = self.make()
        k = self.add(w)
        self.assertEqual(w.forecasts[k].source, "Open-Meteo")
        self.assertTrue(w.source_actions["open-meteo"].isChecked())
        w.source_actions["met.no"].trigger()
        self.assertTrue(w.client.prefer_backup)
        self.assertTrue(wait_until(lambda: k not in w._pending and w.forecasts[k].source == SOURCE_NAME))
        self.assertEqual(w.store.load().weather_source, "met.no")
        w.set_weather_source("open-meteo")
        self.assertTrue(wait_until(lambda: k not in w._pending and w.forecasts[k].source == "Open-Meteo"))
        w.set_weather_source("nonsense")
        self.assertEqual(w.settings.weather_source, "open-meteo")

    def test_about_credits_both_sources(self):
        w = self.make()
        html = w.about_html()
        self.assertIn("open-meteo.com", html)
        self.assertIn("MET Norway", html)

    def test_settings_value_validated(self):
        from weatherdesk.storage import Settings
        self.assertEqual(Settings.from_dict({"weather_source": "met.no"}).weather_source, "met.no")
        self.assertEqual(Settings.from_dict({"weather_source": "bogus"}).weather_source, "open-meteo")
        self.assertEqual(Settings().to_dict()["weather_source"], "open-meteo")


if __name__ == "__main__":
    unittest.main()
