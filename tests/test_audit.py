"""Regression tests for problems found in the 1.15.0 stability audit.

Each test names the problem it guards against (see CHANGELOG 1.15.0 / TEST_REPORT).
Everything runs locally against the fake server or in memory.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import time
import unittest
from unittest import mock

import provider_fixtures as PF
from fake_server import make_forecast, make_metno
from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from weatherdesk.api import DataError, WeatherError, _num, parse_forecast
from weatherdesk.keystore import MASK, KeyStore, RedactingFilter, remember_secret
from weatherdesk.models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from weatherdesk.providers.base import Provider, ProviderInfo
from weatherdesk.providers.manager import ProviderManager
from weatherdesk.providers.normalise import normalise

LOC = Location.from_dict(PLACES[0])


class Boom(Provider):
    """A provider whose conversion has a bug (raises something that isn't a WeatherError)."""
    info = ProviderInfo(id="open-meteo", name="Open-Meteo", needs_key=False, website="", credit="",
                        coverage="", forecast_days="", hourly="", limits="")

    def __init__(self, exc):
        super().__init__(base_url="http://127.0.0.1:9")
        self.exc = exc

    def fetch_forecast(self, location, forecast_days=7):       # skips the wrapper on purpose
        raise self.exc


# ------------------------------------------------------------- crashes and fallback
class TestNoCrashes(TempEnvTestCase):
    def test_infinity_in_json_is_dropped_not_a_crash(self):
        """Audit #1: json accepts 'Infinity'; int(inf) raised OverflowError, which escaped the
        provider and stopped the fallback chain."""
        self.assertIsNone(_num(float("inf")))
        self.assertIsNone(_num(float("-inf")))
        self.assertIsNone(_num(float("nan")))
        d = make_forecast(LOC.latitude, LOC.longitude)
        d["current"]["weather_code"] = float("inf")
        d["hourly"]["weather_code"][0] = float("-inf")
        d["daily"]["weather_code"][0] = float("inf")
        raw = json.dumps(d)                          # becomes "Infinity" in the text, as a server could send
        self.assertIn("Infinity", raw)
        fc = parse_forecast(json.loads(raw), LOC)
        self.assertIsNone(fc.hourly[0].weather_code)

    def test_unexpected_exception_still_falls_back(self):
        """Audit #2: only WeatherError was caught, so a bug in one provider skipped the backups."""
        from weatherdesk.keystore import KeyStore
        for exc in (RuntimeError("bug"), OverflowError("x"), ZeroDivisionError("y"), RecursionError()):
            m = ProviderManager(chain=["open-meteo", "met.no"],
                                keystore=KeyStore(self.tmp / "k", use_keyring=False),
                                overrides={"open-meteo": Boom(exc)},
                                factories={"met.no": PF.factories(self.server)["met.no"]})
            fc = m.fetch_forecast(LOC)
            self.assertEqual(fc.source, "MET Norway", type(exc).__name__)
            self.assertIn("couldn't use", m.status("open-meteo").last_error)
            self.assertIn(type(exc).__name__, m.status("open-meteo").last_error)

    def test_unexpected_exception_alone_is_a_clean_error(self):
        m = ProviderManager(chain=["open-meteo"], keystore=KeyStore(self.tmp / "k", use_keyring=False),
                            overrides={"open-meteo": Boom(RuntimeError("bug"))})
        with self.assertRaises(WeatherError):
            m.fetch_forecast(LOC)

    def test_connection_test_never_raises(self):
        """Audit #3: Test connection only caught WeatherError (and crashed formatting a missing
        current temperature)."""
        m = ProviderManager(chain=["open-meteo"], keystore=KeyStore(self.tmp / "k", use_keyring=False),
                            overrides={"open-meteo": Boom(KeyError("x"))})
        with mock.patch.object(Boom, "test", lambda self, loc: (_ for _ in ()).throw(KeyError("x"))):
            ok, msg, usage = m.test("open-meteo", LOC)
        self.assertFalse(ok)
        self.assertIn("KeyError", msg)

    def test_provider_wrapper_catches_arithmetic_errors(self):
        class Div(Provider):
            info = Boom.info

            def _fetch(self, location, days):
                return 1 / 0
        with self.assertRaises(DataError):
            Div(base_url="http://x").fetch_forecast(LOC)


class TestImplausibleValues(unittest.TestCase):
    """Audit #4: 'feels like' could overflow to infinity from an absurd temperature, and
    unknown condition codes reached the screen."""

    def fc(self, **cur):
        c = dict(time="2026-11-18T12:00", temperature=18.0, apparent_temperature=None, humidity=60.0,
                 weather_code=2, is_day=True, wind_speed=10.0, wind_direction=90.0, wind_gusts=20.0,
                 pressure=1013.0, cloud_cover=40.0, precipitation=0.0)
        c.update(cur)
        return Forecast(location=LOC, timezone="Pacific/Auckland", current=CurrentWeather(**c),
                        hourly=[HourlyPoint("2026-11-18T13:00", 999.0, 50, -5, 7777)],
                        daily=[DailyPoint("2026-11-18", 12345, 1e9, -1e9, -3, 50, 9999, None, None, 99)])

    def test_out_of_range_dropped(self):
        f = normalise(self.fc(pressure=50.0, wind_speed=5000.0, wind_gusts=-1.0, apparent_temperature=1e308),
                      LOC)
        c = f.current
        self.assertIsNone(c.pressure)
        self.assertIsNone(c.wind_speed)
        self.assertIsNone(c.wind_gusts)
        self.assertIsNone(c.apparent_temperature)           # can't be worked out without wind
        h, d = f.hourly[0], f.daily[0]
        self.assertIsNone(h.temperature)
        self.assertIsNone(h.precipitation)
        self.assertIsNone(h.weather_code)
        self.assertEqual((d.temp_max, d.temp_min, d.precipitation_sum, d.wind_speed_max, d.uv_index_max),
                         (None, None, None, None, None))
        self.assertIsNone(d.weather_code)

    def test_absurd_temperature_rejected(self):
        for t in (-1e308, 1e308, 150.0, -150.0):
            with self.assertRaises(DataError):
                normalise(self.fc(temperature=t), LOC)

    def test_feels_like_never_infinite(self):
        f = normalise(self.fc(temperature=-99.0, humidity=100.0, wind_speed=599.0), LOC)
        a = f.current.apparent_temperature
        self.assertTrue(a is None or math.isfinite(a))

    def test_unknown_current_code_worked_out(self):
        f = normalise(self.fc(weather_code=4242, cloud_cover=90.0), LOC)
        self.assertEqual(f.current.weather_code, 3)

    def test_metno_unknown_symbol_not_shown_as_clear(self):
        from weatherdesk.metno import parse_metno
        d = make_metno(LOC.latitude, LOC.longitude)
        for step in d["properties"]["timeseries"][:3]:
            for k in ("next_1_hours", "next_6_hours"):
                if k in step["data"]:
                    step["data"][k]["summary"]["symbol_code"] = "brandnewsymbol_day"
            step["data"]["instant"]["details"]["cloud_area_fraction"] = 95.0
        fc = parse_metno(d, LOC)
        self.assertIsNone(fc.current.weather_code)          # was 0 (clear sky) before 1.15
        # worked out from what was measured (the fixture has rain falling, so 61; else cloud → 3)
        from weatherdesk.weather_codes import KNOWN_CODES
        code = normalise(fc, LOC).current.weather_code
        self.assertIn(code, KNOWN_CODES)
        self.assertNotEqual(code, 0)


# ---------------------------------------------------------------------- providers
class TestProviderRequests(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        PF.install(self.server)
        self.keys = KeyStore(self.tmp / "keys", use_keyring=False)
        for pid, k in PF.KEYS.items():
            self.keys.set(pid, k)

    def manager(self, chain):
        return ProviderManager(chain=chain, keystore=self.keys, factories=PF.factories(self.server))

    def test_tomorrow_request_has_no_timesteps(self):
        """Audit #5: two 'timesteps' values were sent as a repeated parameter, a format the
        API doesn't document; the documented default (hourly + daily) is used instead."""
        self.manager(["tomorrow"]).fetch_forecast(LOC)
        path, q = [r for r in self.server.requests if r[0].startswith(PF.PREFIX["tomorrow"])][-1]
        self.assertNotIn("timesteps", q)
        self.assertEqual(q["units"], "metric")

    def test_openweather_free_drops_partial_last_day(self):
        """Audit #6: the 5-day/3-hour list ends part-way through a day; its high/low were shown."""
        from weatherdesk.providers.openweather import parse_free
        cur, fc = PF.owm_weather(LOC.latitude, LOC.longitude), PF.owm_forecast(LOC.latitude, LOC.longitude)
        fc["list"] = fc["list"][:-5]                      # make the last local day short
        out = parse_free(cur, fc, LOC)
        from collections import Counter
        from weatherdesk.providers.base import from_unix, location_tz
        tz, _ = location_tz(LOC)
        per_day = Counter(from_unix(s["dt"]).astimezone(tz).date().isoformat() for s in fc["list"])
        today = out.daily[0].date
        for d in out.daily:
            if d.date != today:
                self.assertGreaterEqual(per_day[d.date], 4, d.date)


# --------------------------------------------------------------------- key store
class _Counting:
    """A fake keyring that counts lookups (each one is a D-Bus call on a real desktop)."""
    def __init__(self, fail=False):
        self.store, self.gets, self.fail = {}, 0, fail

    def get_password(self, s, u):
        self.gets += 1
        if self.fail:
            raise RuntimeError("locked")
        return self.store.get((s, u))

    def set_password(self, s, u, p):
        self.store[(s, u)] = p

    def delete_password(self, s, u):
        self.store.pop((s, u), None)


class TestKeyStoreAudit(TempEnvTestCase):
    def ks(self, kr):
        k = KeyStore(self.tmp / "cfg", use_keyring=False)
        k._keyring = kr
        return k

    def test_lookups_are_cached(self):
        """Audit #7: the Weather Providers dialog asked the keyring for every provider on every
        refresh (a D-Bus call each, on the window's thread)."""
        kr = _Counting()
        ks = self.ks(kr)
        ks.set("tomorrow", "cached-key-123456")
        for _ in range(20):
            self.assertEqual(ks.get("tomorrow"), "cached-key-123456")
            self.assertIsNone(ks.get("weatherapi"))
        self.assertEqual(kr.gets, 1)                       # weatherapi once; tomorrow came from set()
        ks.delete("tomorrow")
        self.assertIsNone(ks.get("tomorrow"))
        ks.set("tomorrow", "new-key-7654321")
        self.assertEqual(ks.get("tomorrow"), "new-key-7654321")

    def test_failing_keyring_is_not_cached(self):
        kr = _Counting(fail=True)
        ks = self.ks(kr)
        self.assertIsNone(ks.get("tomorrow"))
        self.assertIsNone(ks.get("tomorrow"))
        self.assertEqual(kr.gets, 2)                       # asked again: the keyring may be unlocked later
        kr.fail = False
        kr.store[("WeatherDesk", "tomorrow")] = "after-unlock-123"
        self.assertEqual(ks.get("tomorrow"), "after-unlock-123")

    def test_no_keyring_module_uses_private_file(self):
        import builtins
        real = builtins.__import__

        def no_keyring(name, *a, **k):
            if name == "keyring" or name.startswith("keyring."):
                raise ImportError("no keyring")
            return real(name, *a, **k)
        with mock.patch("builtins.__import__", no_keyring):
            ks = KeyStore(self.tmp / "cfg2", use_keyring=True)
        self.assertIn("private file", ks.backend)
        ks.set("weatherapi", "file-only-key-1234")
        self.assertEqual(os.stat(ks.path).st_mode & 0o777, 0o600)
        self.assertEqual(KeyStore(self.tmp / "cfg2", use_keyring=False).get("weatherapi"), "file-only-key-1234")

    def test_keys_survive_reinstall_style_restart(self):
        """Keys and options live in ~/.config (not in the package): a fresh KeyStore and
        Settings load after an upgrade still find them."""
        from weatherdesk.storage import Settings, SettingsStore
        ks = KeyStore(self.tmp / "cfg3", use_keyring=False)
        ks.set("wunderground", "0123456789abcdef0123456789abcdef")
        st = SettingsStore(self.tmp / "cfg3")
        st.save(Settings(provider_chain=["wunderground", "met.no"],
                         provider_options={"wunderground": {"station_id": "IWAIUK12"}}))
        again = SettingsStore(self.tmp / "cfg3").load()
        self.assertEqual(again.provider_chain, ["wunderground", "met.no"])
        self.assertEqual(again.provider_options, {"wunderground": {"station_id": "IWAIUK12"}})
        self.assertEqual(KeyStore(self.tmp / "cfg3", use_keyring=False).get("wunderground"),
                         "0123456789abcdef0123456789abcdef")
        self.assertNotIn("0123456789abcdef", st.path.read_text())

    def test_settings_from_a_newer_version_survive_a_rollback(self):
        """Audit #11: rolling back to 1.11.1 and running it dropped the provider chain and
        Station ID (found in the real dpkg rollback test). 1.11.1 can't be changed, but from
        1.15 on, settings a newer version wrote are kept and written back unchanged."""
        import json as _json
        from weatherdesk.storage import SettingsStore
        st = SettingsStore(self.tmp / "cfg4")
        st.path.parent.mkdir(parents=True, exist_ok=True)
        st.path.write_text(_json.dumps({
            "version": 1, "temp_unit": "F", "provider_chain": ["met.no", "open-meteo"],
            "future_feature": {"enabled": True, "level": 3}, "future_list": [1, 2, 3]}))
        s = st.load()
        self.assertEqual(s.temp_unit, "F")
        s.temp_unit = "C"                                   # change something and save
        st.save(s)
        back = _json.loads(st.path.read_text())
        self.assertEqual(back["future_feature"], {"enabled": True, "level": 3})
        self.assertEqual(back["future_list"], [1, 2, 3])
        self.assertEqual(back["temp_unit"], "C")
        self.assertEqual(back["provider_chain"], ["met.no", "open-meteo"])
        # a known setting with a bad value is still replaced by its default, not kept as "extra"
        st.path.write_text(_json.dumps({"temp_unit": "kelvin"}))
        self.assertEqual(st.load().to_dict()["temp_unit"], "C")
        # a damaged file with a huge unknown value isn't carried forward
        st.path.write_text(_json.dumps({"junk": "x" * 100_000}))
        self.assertNotIn("junk", st.load().to_dict())


# --------------------------------------------------------------- leaks to the user
class TestNoKeyLeaks(TempEnvTestCase):
    def test_unexpected_worker_error_is_redacted(self):
        """Audit #8: an unexpected exception's text went to the window unredacted."""
        qapp()
        from weatherdesk.workers import Bridge, Worker
        remember_secret("WORKER-SECRET-55555")

        class Client:
            def fetch_forecast(self, loc):
                raise RuntimeError("boom with WORKER-SECRET-55555 inside")
        b = Bridge()
        got = []
        b.forecast_failed.connect(lambda tok, key, msg: got.append(msg))
        Worker(Client(), b).fetch_forecast(1, LOC)
        self.assertTrue(wait_until(lambda: got, 5))
        self.assertNotIn("WORKER-SECRET-55555", got[0])
        self.assertIn(MASK, got[0])

    def test_diagnose_mode_redacts_warnings(self):
        """Audit #9: --diagnose printed warnings without the key filter."""
        from weatherdesk import app
        remember_secret("DIAG-SECRET-424242")
        root = logging.getLogger()
        before, level = list(root.handlers), root.level
        buf = io.StringIO()
        try:
            root.handlers = []
            with mock.patch("weatherdesk.diagnostics.run_diagnostics",
                            side_effect=lambda: logging.getLogger("weatherdesk.x").warning(
                                "failed for DIAG-SECRET-424242") or "report"), \
                    mock.patch("sys.stderr", buf), mock.patch("builtins.print"):
                app.main(["--diagnose"])
            self.assertTrue(all(any(isinstance(f, RedactingFilter) for f in h.filters) for h in root.handlers))
            for h in root.handlers:
                h.flush()
            self.assertNotIn("DIAG-SECRET-424242", buf.getvalue())
        finally:
            root.handlers, root.level = before, level

    def test_provider_dialog_shows_service_text_as_text(self):
        """Audit #10: error text from a weather service was shown as rich text (it could add
        formatting or a clickable link to the dialog)."""
        qapp()
        from weatherdesk.main_window import MainWindow
        from weatherdesk.providers_dialog import ProvidersDialog
        PF.install(self.server)
        keys = KeyStore(self.tmp / "keys", use_keyring=False)
        m = ProviderManager(chain=["open-meteo", "met.no"], keystore=keys,
                            factories=PF.factories(self.server), status_file=self.tmp / "p.json")
        w = MainWindow(client=m, enable_tray=False)
        try:
            m._record("open-meteo", last_error="<a href='http://evil.example'>click</a> <b>bold</b>",
                      last_error_at=time.time())
            d = ProvidersDialog(w)
            d.reload()
            for i in range(d.list.count()):
                if d.list.item(i).data(0x0100) == "open-meteo":
                    d.list.setCurrentRow(i)
            txt = d.f["last_error"].text()
            self.assertNotIn("<a href", txt)
            self.assertIn("&lt;a href", txt)
            d._show_result(False, "<b>x</b>")
            self.assertNotIn("<b>x</b>", d.test_result.text())
            d.close()
        finally:
            w._quitting = True
            w.close()


if __name__ == "__main__":
    unittest.main()
