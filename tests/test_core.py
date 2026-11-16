"""Non-GUI tests: units, codes, parsing, HTTP client error paths, settings, cache."""

from __future__ import annotations

import json
import os
import socket
import stat
import unittest

from helpers import PLACES, TempEnvTestCase

from fake_server import make_forecast
from weatherdesk import AUTHOR_CREDIT, units, weather_codes
from weatherdesk.api import (ApiError, DataError, NetworkError, OpenMeteoClient, forecast_from_dict,
                             forecast_to_dict, parse_forecast, parse_geocode)
from weatherdesk.models import Location
from weatherdesk.storage import MAX_LOCATIONS, ForecastCache, Settings, SettingsStore, atomic_write_json


class TestCredit(unittest.TestCase):
    def test_credit_spelling_exact(self):
        self.assertEqual(AUTHOR_CREDIT, "Created By Shane BlackbuRn")


class TestUnits(unittest.TestCase):
    def test_temperature(self):
        self.assertAlmostEqual(units.convert_temp(100, "F"), 212)
        self.assertAlmostEqual(units.convert_temp(-40, "F"), -40)
        self.assertEqual(units.convert_temp(21.5, "C"), 21.5)
        self.assertIsNone(units.convert_temp(None, "F"))
        with self.assertRaises(ValueError):
            units.convert_temp(1, "K")

    def test_no_negative_zero(self):
        self.assertEqual(units.fmt_temp(-0.3, "C"), "0°C")
        self.assertEqual(units.fmt_temp(-0.6, "C"), "-1°C")
        self.assertEqual(units.fmt_temp(None, "C"), "–")

    def test_wind_and_precip(self):
        self.assertAlmostEqual(units.convert_wind(36, "m/s"), 10)
        self.assertAlmostEqual(units.convert_wind(100, "mph"), 62.1371, places=3)
        self.assertAlmostEqual(units.convert_wind(100, "kn"), 53.9957, places=3)
        self.assertEqual(units.fmt_wind(18.7, "km/h"), "19 km/h")
        self.assertAlmostEqual(units.convert_precip(25.4, "in"), 1.0)
        self.assertEqual(units.fmt_precip(2.54, "in"), "0.10 in")
        self.assertEqual(units.fmt_precip(None, "mm"), "–")
        with self.assertRaises(ValueError):
            units.convert_wind(1, "furlongs")

    def test_compass(self):
        for deg, exp in [(0, "N"), (11, "N"), (12, "NNE"), (90, "E"), (225, "SW"),
                         (350, "N"), (359.9, "N"), (360, "N"), (-90, "W"), (720 + 180, "S")]:
            self.assertEqual(units.compass(deg), exp, deg)
        self.assertEqual(units.compass(None), "")


class TestWeatherCodes(unittest.TestCase):
    def test_all_known_codes_described(self):
        for c in weather_codes.all_codes():
            self.assertNotEqual(weather_codes.describe(c), "Unknown")
            self.assertTrue(weather_codes.symbol(c, True))
            self.assertTrue(weather_codes.symbol(c, False))

    def test_unknown(self):
        self.assertEqual(weather_codes.describe(42), "Unknown")
        self.assertEqual(weather_codes.describe(None), "Unknown")
        self.assertEqual(weather_codes.symbol(None), "❔")


class TestParsing(unittest.TestCase):
    loc = Location.from_dict(PLACES[0])

    def test_full_forecast(self):
        fc = parse_forecast(make_forecast(-36.8, 174.7), self.loc)
        self.assertEqual(len(fc.hourly), 7 * 24)
        self.assertEqual(len(fc.daily), 7)
        self.assertEqual(fc.current.weather_code, 2)
        self.assertTrue(fc.current.is_day)
        self.assertEqual(fc.daily[0].sunrise, "2026-11-15T06:00")

    def test_missing_current_is_error(self):
        d = make_forecast(0, 0)
        d.pop("current")
        with self.assertRaises(DataError):
            parse_forecast(d, self.loc)
        with self.assertRaises(DataError):
            parse_forecast([], self.loc)

    def test_tolerates_short_columns_nulls_nan_and_junk(self):
        d = make_forecast(0, 0)
        d["hourly"]["temperature_2m"] = d["hourly"]["temperature_2m"][:5]
        d["hourly"]["precipitation"] = "junk"
        d["daily"]["temperature_2m_max"][0] = None
        d["daily"]["uv_index_max"][1] = float("nan")
        d["daily"]["sunrise"][2] = 12345
        d["current"]["humidity"] = "x"
        d["current"]["is_day"] = 0
        fc = parse_forecast(d, self.loc)
        self.assertEqual(len(fc.hourly), 7 * 24)
        self.assertIsNone(fc.hourly[10].temperature)
        self.assertIsNone(fc.hourly[0].precipitation)
        self.assertIsNone(fc.daily[0].temp_max)
        self.assertIsNone(fc.daily[1].uv_index_max)
        self.assertIsNone(fc.daily[2].sunrise)
        self.assertFalse(fc.current.is_day)

    def test_no_hourly_or_daily(self):
        d = make_forecast(0, 0)
        d.pop("hourly"); d.pop("daily")
        fc = parse_forecast(d, self.loc)
        self.assertEqual((fc.hourly, fc.daily), ([], []))

    def test_geocode_dedupes_and_skips_invalid(self):
        res = parse_geocode({"results": [PLACES[0], PLACES[0], {"name": "x"},
                                         {"latitude": 1, "longitude": 2}, "junk", PLACES[1]]})
        self.assertEqual([r.name for r in res], ["Auckland", "Hamilton"])
        self.assertEqual(parse_geocode({}), [])
        with self.assertRaises(DataError):
            parse_geocode("nope")

    def test_cache_round_trip(self):
        fc = parse_forecast(make_forecast(-36.8, 174.7), self.loc)
        fc.fetched_at = 1234.5
        back = forecast_from_dict(json.loads(json.dumps(forecast_to_dict(fc))))
        self.assertTrue(back.from_cache)
        self.assertEqual(back.fetched_at, 1234.5)
        self.assertEqual(back.current, fc.current)
        self.assertEqual(back.daily, fc.daily)
        self.assertEqual(back.hourly, fc.hourly)
        with self.assertRaises(DataError):
            forecast_from_dict({"location": {}})

    def test_location_display(self):
        self.assertEqual(Location("Auckland", 1, 2, "New Zealand", "Auckland").display_name,
                         "Auckland, New Zealand")
        self.assertEqual(Location("Hamilton", 1, 2, "New Zealand", "Waikato").display_name,
                         "Hamilton, Waikato, New Zealand")


class TestClient(TempEnvTestCase):
    def test_search(self):
        res = self.client().search_locations("Ham")
        self.assertEqual(len(res), 2)
        self.assertEqual({r.country for r in res}, {"New Zealand", "Canada"})
        _, q = self.server.requests[-1]
        self.assertEqual(q["name"], "Ham")

    def test_short_query_makes_no_request(self):
        self.assertEqual(self.client().search_locations(" a "), [])
        self.assertEqual(self.server.count("/v1/search"), 0)

    def test_search_no_results(self):
        self.server.mode = "empty"
        self.assertEqual(self.client().search_locations("Auckland"), [])

    def test_forecast_request_parameters(self):
        fc = self.client().fetch_forecast(self.place(0))
        self.assertGreater(fc.fetched_at, 0)
        self.assertFalse(fc.from_cache)
        _, q = self.server.requests[-1]
        self.assertEqual(q["latitude"], "-36.8485")
        self.assertEqual(q["timezone"], "Pacific/Auckland")
        self.assertIn("weather_code", q["current"])
        self.assertEqual(q["forecast_days"], "7")

    def test_http_500(self):
        self.server.mode = "http500"
        with self.assertRaises(ApiError) as cm:
            self.client().fetch_forecast(self.place(0))
        self.assertIn("500", str(cm.exception))
        self.assertIn("Internal test failure", str(cm.exception))

    def test_http_400_reason(self):
        self.server.mode = "error_body"
        with self.assertRaisesRegex(ApiError, "Latitude must be in range"):
            self.client().fetch_forecast(self.place(0))

    def test_bad_json(self):
        self.server.mode = "badjson"
        with self.assertRaises(DataError):
            self.client().fetch_forecast(self.place(0))

    def test_missing_current(self):
        self.server.mode = "missing_current"
        with self.assertRaises(DataError):
            self.client().fetch_forecast(self.place(0))

    def test_timeout(self):
        self.server.delay = 2.0
        with self.assertRaises(NetworkError) as cm:
            self.client(timeout=0.4).fetch_forecast(self.place(0))
        self.assertIn("did not respond", str(cm.exception))

    def test_connection_refused(self):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        c = OpenMeteoClient(f"http://127.0.0.1:{port}/v1/forecast", f"http://127.0.0.1:{port}/s", timeout=2)
        with self.assertRaises(NetworkError):
            c.fetch_forecast(self.place(0))
        with self.assertRaises(NetworkError):
            c.search_locations("Auckland")

    def test_unresolvable_host(self):
        c = OpenMeteoClient("http://nonexistent.invalid/v1/forecast", "http://nonexistent.invalid/s", timeout=3)
        with self.assertRaises(NetworkError):
            c.fetch_forecast(self.place(0))


class TestSettings(TempEnvTestCase):
    def test_defaults_when_missing(self):
        s = SettingsStore().load()
        self.assertEqual((s.locations, s.temp_unit, s.refresh_minutes), ([], "C", 30))
        self.assertIsNone(s.selected_location())

    def test_round_trip(self):
        st = SettingsStore()
        s = Settings()
        s.add_location(self.place(0)); s.add_location(self.place(1))
        s.temp_unit, s.wind_unit, s.precip_unit, s.refresh_minutes = "F", "kn", "in", 60
        s.close_to_tray = True
        st.save(s)
        back = st.load()
        self.assertEqual(back.to_dict(), s.to_dict())
        self.assertEqual(back.selected_location(), self.place(1))

    def test_invalid_values_replaced_individually(self):
        d = Settings().to_dict()
        d.update(temp_unit="K", wind_unit=None, refresh_minutes=7, show_tray="yes",
                 selected="nope", locations=[PLACES[0], {"name": "bad"},
                                             {"name": "x", "latitude": 99, "longitude": 0}, PLACES[0]])
        s = Settings.from_dict(d)
        self.assertEqual(len(s.locations), 1)
        self.assertEqual(s.selected, s.locations[0].key)
        self.assertEqual((s.temp_unit, s.wind_unit, s.refresh_minutes, s.show_tray), ("C", "km/h", 30, True))
        self.assertEqual(Settings.from_dict("junk").to_dict(), Settings().to_dict())
        self.assertEqual(Settings.from_dict({"refresh_minutes": True}).refresh_minutes, 30)

    def test_corrupt_file_is_preserved_not_deleted(self):
        st = SettingsStore()
        st.path.parent.mkdir(parents=True)
        st.path.write_text("{ this is not json", encoding="utf-8")
        s = st.load()
        self.assertEqual(s.locations, [])
        self.assertIn("moved", st.last_error)
        backups = list(st.path.parent.glob("settings.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "{ this is not json")
        self.assertFalse(st.path.exists())

    def test_non_object_root(self):
        st = SettingsStore()
        st.path.parent.mkdir(parents=True)
        st.path.write_text("[1,2]")
        self.assertEqual(st.load().locations, [])
        self.assertIsNotNone(st.last_error)

    def test_add_remove_move(self):
        s = Settings()
        self.assertTrue(s.add_location(self.place(0)))
        self.assertFalse(s.add_location(self.place(0)))
        s.add_location(self.place(1)); s.add_location(self.place(3))
        self.assertEqual(s.selected, self.place(3).key)
        self.assertTrue(s.move_location(self.place(3).key, -2))
        self.assertEqual(s.locations[0], self.place(3))
        self.assertFalse(s.move_location(self.place(3).key, -1))
        self.assertFalse(s.move_location("missing", 1))
        self.assertTrue(s.remove_location(self.place(3).key))
        self.assertEqual(s.selected, self.place(0).key)
        self.assertFalse(s.remove_location("missing"))
        s.remove_location(self.place(0).key); s.remove_location(self.place(1).key)
        self.assertIsNone(s.selected)

    def test_location_limit(self):
        s = Settings()
        for i in range(MAX_LOCATIONS):
            s.add_location(Location(f"P{i}", i * 0.5, i * 0.5))
        with self.assertRaises(ValueError):
            s.add_location(Location("one too many", -50, -50))

    def test_atomic_write_leaves_no_temp_files(self):
        p = self.tmp / "a" / "x.json"
        for i in range(20):
            atomic_write_json(p, {"i": i})
        self.assertEqual(json.loads(p.read_text()), {"i": 19})
        self.assertEqual([f.name for f in p.parent.iterdir()], ["x.json"])

    def test_atomic_write_failure_keeps_old_file(self):
        p = self.tmp / "x.json"
        atomic_write_json(p, {"ok": 1})
        with self.assertRaises(TypeError):
            atomic_write_json(p, {"bad": object()})
        self.assertEqual(json.loads(p.read_text()), {"ok": 1})
        self.assertEqual([f.name for f in self.tmp.iterdir() if f.is_file()], ["x.json"])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_readonly_dir_raises_oserror(self):
        d = self.tmp / "ro"; d.mkdir(); d.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with self.assertRaises(OSError):
                SettingsStore(d).save(Settings())
        finally:
            d.chmod(stat.S_IRWXU)


class TestCache(TempEnvTestCase):
    def test_save_load_remove(self):
        c = ForecastCache()
        loc = self.place(0)
        self.assertIsNone(c.load(loc))
        fc = self.client().fetch_forecast(loc)
        c.save(fc)
        back = c.load(loc)
        self.assertTrue(back.from_cache)
        self.assertEqual(back.current.temperature, fc.current.temperature)
        c.remove(loc)
        self.assertIsNone(c.load(loc))
        c.remove(loc)  # removing twice is harmless

    def test_corrupt_cache_ignored(self):
        c = ForecastCache()
        loc = self.place(0)
        c.dir.mkdir(parents=True)
        c._path(loc).write_text("garbage")
        self.assertIsNone(c.load(loc))
        c._path(loc).write_text(json.dumps({"location": PLACES[0]}))
        self.assertIsNone(c.load(loc))

    def test_clean_orphans(self):
        c = ForecastCache()
        cl = self.client()
        for i in (0, 1, 3):
            c.save(cl.fetch_forecast(self.place(i)))
        self.assertEqual(c.clean_orphans([self.place(1)]), 2)
        self.assertIsNotNone(c.load(self.place(1)))
        self.assertIsNone(c.load(self.place(0)))
        self.assertEqual(ForecastCache(self.tmp / "nope").clean_orphans([]), 0)

    def test_negative_coordinates_distinct_files(self):
        c = ForecastCache()
        a, b = Location("a", -1.5, 2.0), Location("b", 1.5, 2.0)
        self.assertNotEqual(c._path(a), c._path(b))


if __name__ == "__main__":
    unittest.main()
