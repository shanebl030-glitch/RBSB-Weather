"""Weather Provider Manager (1.13): every integration, the common data format,
fallback and recovery, API key security, and Settings → Weather Providers.

All providers are served by the local fake server in the shape their API docs
give (provider_fixtures.py). Nothing touches the internet or the real keyring.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import logging
import os
import stat
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import TempEnvTestCase, qapp, wait_until
import provider_fixtures as PF

from rbsb_weather import providers, weather_codes
from rbsb_weather.api import ApiError, DataError, NetworkError, WeatherError
from rbsb_weather.keystore import MASK, KeyStore, RedactingFilter, redact, remember_secret
from rbsb_weather.models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from rbsb_weather.providers import REGISTRY
from rbsb_weather.providers.base import KeyMissing
from rbsb_weather.providers.manager import ProviderManager, valid_chain
from rbsb_weather.providers.normalise import code_from, normalise

KEYED = list(PF.KEYS)
ALL = ["open-meteo", "met.no"] + KEYED


class ProviderCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        PF.install(self.server)
        self.keys = KeyStore(self.tmp / "keys", use_keyring=False)
        for pid, k in PF.KEYS.items():
            self.keys.set(pid, k)
        self.clock_t = 1_000_000.0

    def clock(self):
        return self.clock_t

    def manager(self, chain, recovery="30", **kw):
        return ProviderManager(chain=chain, recovery=recovery, keystore=self.keys,
                               factories=PF.factories(self.server), clock=self.clock, **kw)

    def loc(self, i=0):
        return self.place(i)


# ------------------------------------------------------------------- registry
class TestRegistry(unittest.TestCase):
    def test_providers_listed(self):
        self.assertEqual(providers.integrated_ids(), ALL)
        self.assertEqual([i.id for i in providers.all_infos()], ALL + ["accuweather", "weatherbit"])
        for pid in ("accuweather", "weatherbit"):
            inf = providers.info(pid)
            self.assertEqual(inf.status, "planned")
            self.assertTrue(inf.planned_reason)
            self.assertNotIn(pid, REGISTRY)

    def test_info_complete(self):
        for inf in providers.all_infos():
            for f in ("name", "website", "credit", "coverage", "forecast_days", "hourly", "limits"):
                self.assertTrue(getattr(inf, f), f"{inf.id}.{f}")
            if inf.status == "integrated":
                self.assertTrue(inf.features <= set(providers.FEATURES), inf.id)
                if inf.needs_key:
                    self.assertTrue(inf.signup_url and inf.key_help, inf.id)

    def test_valid_chain(self):
        self.assertEqual(valid_chain(["tomorrow", "x", "tomorrow", "met.no"]), ["tomorrow", "met.no"])
        self.assertEqual(valid_chain(["accuweather"]), ["open-meteo", "met.no"])    # planned: not usable
        self.assertEqual(valid_chain(None), ["open-meteo", "met.no"])

    def test_every_mapped_code_is_known_to_the_app(self):
        from rbsb_weather.providers import openweather, tomorrow, visualcrossing, weatherapi
        known = set(weather_codes.all_codes())
        codes = [openweather.owm_code(c) for c in range(200, 805)]
        codes += list(weatherapi._CODES.values()) + list(tomorrow._CODES.values())
        codes += [visualcrossing.vc_code(i, p, s) for i in ("snow", "snow-showers-day", "rain", "showers-night",
                                                             "thunder-rain", "fog", "clear-night", "cloudy",
                                                             "partly-cloudy-day") for p in (0, 5, 20) for s in (0, 6)]
        for c in codes:
            self.assertTrue(c is None or c in known, c)


# -------------------------------------------------------------- integrations
class TestIntegrations(ProviderCase):
    def fetch(self, pid):
        return self.manager([pid]).fetch_forecast(self.loc())

    def check_common(self, fc, pid, min_days, min_hours):
        """What every provider must give the app."""
        c = fc.current
        self.assertEqual((fc.provider_id, fc.source), (pid, providers.info(pid).name))
        self.assertGreater(fc.fetched_at, time.time() - 60)       # drives "Updated…" and auto refresh
        self.assertIsNotNone(c.temperature)
        self.assertIsInstance(c.is_day, bool)
        self.assertIn(c.weather_code, weather_codes.all_codes())
        for v in (c.humidity, c.cloud_cover):
            self.assertTrue(v is None or 0 <= v <= 100)
        self.assertTrue(c.wind_direction is None or 0 <= c.wind_direction < 360)
        now_local = dt.datetime.now(dt.timezone.utc).astimezone(PF.AKL).replace(tzinfo=None)
        self.assertLess(abs((dt.datetime.fromisoformat(c.time) - now_local).total_seconds()), 20 * 60)
        self.assertGreaterEqual(len(fc.daily), min_days)
        self.assertLessEqual(len(fc.daily), 7)
        self.assertEqual(fc.daily[0].date, now_local.date().isoformat())
        for d in fc.daily:
            self.assertLessEqual(d.temp_min, d.temp_max)
            self.assertTrue(d.sunrise.startswith(d.date) and d.sunset.startswith(d.date), d)
            self.assertTrue(d.precipitation_probability_max is None or 0 <= d.precipitation_probability_max <= 100)
        self.assertGreaterEqual(len(fc.hourly), min_hours)
        times = [h.time for h in fc.hourly]
        self.assertEqual(times, sorted(times))
        self.assertEqual(fc.utc_offset_seconds, 13 * 3600)

    def test_openweather_one_call(self):
        fc = self.fetch("openweather")
        self.check_common(fc, "openweather", 7, 48)
        c = fc.current
        self.assertEqual((c.temperature, c.apparent_temperature, c.humidity), (16.2, 15.9, 72.0))
        self.assertEqual((c.wind_speed, c.wind_gusts, c.wind_direction), (16.6, 29.5, 230.0))   # m/s -> km/h
        self.assertEqual(c.weather_code, 3)                     # 804 overcast
        d0 = fc.daily[0]
        self.assertEqual((d0.temp_max, d0.temp_min, d0.precipitation_probability_max, d0.uv_index_max),
                         (20.0, 11.0, 40.0, 9.1))
        self.assertEqual((d0.sunrise[11:], d0.sunset[11:]), ("06:01", "20:09"))
        self.assertEqual(fc.daily[1].precipitation_sum, 0.0)     # no "rain" key = none
        self.assertEqual(fc.hourly[0].precipitation_probability, 35.0)   # 0..1 -> %
        self.assertEqual(fc.calculated, [])

    def test_openweather_free_key_falls_back_and_remembers(self):
        self.server.provider_mode["openweather"] = "no_onecall"
        m = self.manager(["openweather"])
        fc = m.fetch_forecast(self.loc())
        self.check_common(fc, "openweather", 5, 100)
        self.assertEqual(self.server.provider_calls["openweather"], 3)       # onecall, weather, forecast
        self.assertIn("Free key", m.provider("openweather").usage()["plan"])
        self.assertIsNone(fc.daily[1].uv_index_max)                          # not on the free plan: "–"
        self.assertIn("hourly (spread from 3-hourly steps)", fc.calculated)
        self.assertIn("sunrise/sunset", fc.calculated)                       # days after today
        hrs = [dt.datetime.fromisoformat(h.time) for h in fc.hourly[:6]]
        self.assertTrue(all(b - a == dt.timedelta(hours=1) for a, b in zip(hrs, hrs[1:])))
        m._recent.clear(); m._asked.clear()
        m.fetch_forecast(self.loc())
        self.assertEqual(self.server.provider_calls["openweather"], 5)       # One Call not asked again

    def test_weatherapi(self):
        fc = self.fetch("weatherapi")
        self.check_common(fc, "weatherapi", 3, 24)
        self.assertEqual(len(fc.daily), 3)                                   # free plan: 3 days, shown as 3
        c = fc.current
        self.assertEqual((c.temperature, c.wind_speed, c.weather_code, c.pressure), (16.0, 15.1, 3, 1015.0))
        self.assertEqual(fc.daily[0].weather_code, 63)                       # 1189 moderate rain
        self.assertEqual(fc.daily[2].weather_code, 95)                       # 1276 rain with thunder
        self.assertEqual(fc.daily[1].sunset, f"{fc.daily[1].date}T20:09")
        self.assertIn("sunrise/sunset", fc.calculated)                       # "No sunset" on day 1 -> calculated

    def test_visualcrossing(self):
        fc = self.fetch("visualcrossing")
        self.check_common(fc, "visualcrossing", 7, 24 * 7)
        self.assertEqual(len(fc.daily), 7)                                   # 15 offered, 7 used
        c = fc.current
        self.assertEqual((c.temperature, c.wind_speed, c.weather_code), (16.8, 14.8, 2))   # km/h already
        self.assertEqual([d.weather_code for d in fc.daily[:3]], [63, 0, 95])   # rain 4.2 mm -> moderate
        self.assertEqual(fc.daily[0].uv_index_max, 9.0)
        m = self.manager(["visualcrossing"])
        m.fetch_forecast(self.loc())
        self.assertIn("1 record", m.status("visualcrossing").usage["cost"])

    def test_tomorrow(self):
        m = self.manager(["tomorrow"])
        fc = m.fetch_forecast(self.loc())
        self.check_common(fc, "tomorrow", 5, 100)
        self.assertEqual(len(fc.daily), 5)
        c = fc.current
        self.assertEqual((c.wind_speed, c.pressure), (16.2, 1016.2))
        self.assertEqual([d.weather_code for d in fc.daily], [63, 0, 95, 71, 2])
        self.assertIn("day/night", fc.calculated)
        u = m.provider("tomorrow").usage()
        self.assertEqual(u["today"], "487 of 500 requests left today")
        self.assertEqual(m.status("tomorrow").usage, u)

    def test_wunderground_nearest_station(self):
        m = self.manager(["wunderground"])
        fc = m.fetch_forecast(self.loc())
        self.check_common(fc, "wunderground", 6, 0)
        self.assertEqual(len(fc.daily), 6)                       # today + 5
        self.assertEqual(fc.hourly, [])                          # none on a PWS key
        c = fc.current
        self.assertEqual((c.temperature, c.wind_speed, c.wind_gusts, c.wind_direction, c.humidity),
                         (17.4, 13.0, 22.3, 235.0, 68.0))
        self.assertEqual(c.pressure, 1015.92)
        # today's day part says rain (icon 12), but the station measures none right now:
        # the cloud cover (80 %) is shown instead
        self.assertEqual(c.weather_code, 3)
        self.assertIsNotNone(c.apparent_temperature)             # calculated, like the other providers
        self.assertEqual([d.weather_code for d in fc.daily], [63, 0, 95, 3, 2, 85])
        d0 = fc.daily[0]
        self.assertEqual((d0.temp_max, d0.temp_min, d0.precipitation_probability_max, d0.precipitation_sum,
                          d0.uv_index_max, d0.wind_speed_max), (21.0, 11.0, 60.0, 5.1, 9.0, 20.0))
        self.assertEqual((d0.sunrise[11:], d0.sunset[11:]), ("06:01", "20:09"))
        self.assertIn("current condition (forecast for this part of the day, no rain at the station now)",
                      fc.calculated)
        # qcStatus -1, offline (204) and 5-hour-old stations are skipped
        self.assertEqual(m.provider("wunderground").station_used, "IAUCKL456")
        self.assertIn("IAUCKL456", m.status("wunderground").usage["station"])
        near = sum(1 for r in self.server.wu_requests if r.endswith("/location/near"))
        m._recent.clear(); m._asked.clear()
        m.fetch_forecast(self.loc())
        self.assertEqual(sum(1 for r in self.server.wu_requests if r.endswith("/location/near")), near)  # cached

    def test_wunderground_rain_at_station(self):
        from rbsb_weather.providers import wunderground as WU
        ob = PF.wu_obs("IX")["observations"][0]
        ob["metric"]["precipRate"] = 4.2
        fcd = PF.wu_5day(0, 0)
        fcd["daypart"][0]["iconCode"][0] = 32                         # forecast: sunny
        fc = WU.parse_wunderground(fcd, ob, self.loc())
        self.assertEqual(fc.current.weather_code, 63)                  # but 4.2 mm/h is falling
        ob["metric"]["precipRate"] = None                              # unknown: keep the forecast's
        fcd["daypart"][0]["iconCode"][0] = 12
        self.assertEqual(WU.parse_wunderground(fcd, ob, self.loc()).current.weather_code, 63)

    def test_wunderground_own_station(self):
        m = self.manager(["wunderground", "met.no"])
        m.set_option("wunderground", "station_id", "IMYSTATION7")
        fc = m.fetch_forecast(self.loc())
        self.assertEqual((fc.provider_id, m.provider("wunderground").station_used), ("wunderground", "IMYSTATION7"))
        self.assertFalse(any(r.endswith("/location/near") for r in self.server.wu_requests))
        m.set_option("wunderground", "station_id", "IOFFLINE1")       # own station offline: backup
        fc = m.fetch_forecast(self.loc())
        self.assertEqual(fc.provider_id, "met.no")
        self.assertIn("Your weather station IOFFLINE1 isn't reporting", m.status("wunderground").last_error)
        for bad in ("has space", "ab", "x" * 30, "../x"):
            with self.assertRaises(ValueError):
                m.set_option("wunderground", "station_id", bad)
        with self.assertRaises(ValueError):
            m.set_option("tomorrow", "station_id", "IWAIUK12")         # not an option there
        m.set_option("wunderground", "station_id", "")
        self.assertNotIn("wunderground", m.options)

    def test_wunderground_afternoon_and_no_stations(self):
        self.server.provider_mode["wunderground"] = "afternoon"         # today's day part is null
        fc = self.manager(["wunderground"]).fetch_forecast(self.loc())
        self.assertEqual(fc.current.weather_code, 2)                    # tonight showers, dry station, 60 % cloud
        self.assertEqual((fc.daily[0].weather_code, fc.daily[0].temp_max), (81, 21.0))
        self.server.provider_mode["wunderground"] = "all_offline"
        with self.assertRaises(DataError) as cm:
            self.manager(["wunderground"]).fetch_forecast(self.loc())
        self.assertIn("No nearby weather station is reporting", str(cm.exception))

    def test_unknown_condition_codes_are_worked_out_not_guessed(self):
        for pid in ("openweather", "weatherapi"):
            self.server.provider_mode[pid] = "unknown_codes"
            fc = self.fetch(pid)
            self.assertEqual(fc.current.weather_code, code_from(fc.current.cloud_cover, fc.current.precipitation))
            self.assertIn("current condition (from cloud and rain)", fc.calculated)

    def test_scene_and_widget_work_for_every_provider(self):
        from rbsb_weather import forecast_strip
        from rbsb_weather.scene import conditions_from_forecast
        for pid in ALL:
            fc = self.fetch(pid)
            cond = conditions_from_forecast(fc)
            self.assertIsNotNone(cond.kind, pid)
            days = forecast_strip.days_from_forecast(fc)
            self.assertGreaterEqual(len(days), 3, pid)
            self.assertIsNotNone(forecast_strip.location_today(fc), pid)


class TestErrors(ProviderCase):
    def test_bad_key_is_explained_and_never_echoed(self):
        for pid in KEYED:
            secret = f"WRONG-{pid}-SECRET-1234567890"
            self.keys.set(pid, secret)
            m = self.manager([pid])
            with self.assertRaises(ApiError) as cm:
                m.fetch_forecast(self.loc())
            msg = str(cm.exception)
            self.assertIn("rejected the API key", msg, pid)
            self.assertNotIn(secret, msg, pid)
            self.assertNotIn(secret, m.status(pid).last_error, pid)
        # Visual Crossing really does put the key in its error text: it's removed
        self.keys.set("visualcrossing", "VC-ECHOED-KEY-123456")
        m = self.manager(["visualcrossing"])
        with self.assertRaises(ApiError):
            m.fetch_forecast(self.loc())
        self.assertNotIn("VC-ECHOED-KEY-123456", m.status("visualcrossing").last_error)

    def test_usage_limit(self):
        for pid in KEYED:
            self.server.provider_mode[pid] = "http429"
        for pid in ("openweather", "visualcrossing", "tomorrow"):
            with self.assertRaises(ApiError) as cm:
                self.manager([pid]).fetch_forecast(self.loc())
            self.assertIn("usage limit has been reached", str(cm.exception))
        with self.assertRaises(ApiError) as cm:                    # WeatherAPI says so with a 403
            self.manager(["weatherapi"]).fetch_forecast(self.loc())
        self.assertIn("usage limit has been reached for now (HTTP 403) (API key has exceeded calls per month "
                      "quota)", str(cm.exception))

    def test_garbled_or_unexpected_data(self):
        for pid in KEYED:
            for mode in ("badjson", "bad_shape"):
                self.server.provider_mode[pid] = mode
                with self.assertRaises(DataError, msg=f"{pid} {mode}"):
                    self.manager([pid]).fetch_forecast(self.loc())

    def test_no_key_is_skipped(self):
        self.keys.delete("tomorrow")
        m = self.manager(["tomorrow", "met.no"])
        self.assertEqual(m.fetch_forecast(self.loc()).provider_id, "met.no")
        self.assertEqual(m.state("tomorrow"), "no key")
        self.assertEqual(self.server.provider_calls["tomorrow"], 0)
        with self.assertRaises(KeyMissing):
            self.manager(["tomorrow"]).fetch_forecast(self.loc())


# ----------------------------------------------------------------- manager
class TestFallbackAndRecovery(ProviderCase):
    def test_backups_tried_in_order(self):
        self.server.provider_mode["tomorrow"] = "http500"
        self.server.provider_mode["weatherapi"] = "http500"
        m = self.manager(["tomorrow", "weatherapi", "visualcrossing", "met.no"])
        fc = m.fetch_forecast(self.loc())
        self.assertEqual(fc.provider_id, "visualcrossing")
        self.assertEqual(m.active, "visualcrossing")
        self.assertEqual(m.state("tomorrow"), "failing")
        self.assertEqual(m.state("visualcrossing"), "working")
        self.assertEqual(len(self.server.metno_agents), 0)            # never needed

    def test_all_fail_one_clear_message(self):
        for pid in KEYED:
            self.server.provider_mode[pid] = "http500"
        self.server.metno_mode = "http500"
        m = self.manager(["tomorrow", "weatherapi", "met.no"])
        with self.assertRaises(WeatherError) as cm:
            m.fetch_forecast(self.loc())
        msg = str(cm.exception)
        self.assertTrue(msg.startswith("Weather service returned HTTP 500"), msg)
        self.assertIn("The backups (WeatherAPI.com, MET Norway) couldn't supply it either.", msg)

    def recovery_run(self, mode):
        self.server.provider_mode["tomorrow"] = "http500"
        m = self.manager(["tomorrow", "met.no"], recovery=mode)
        loc = self.loc()
        self.assertEqual(m.fetch_forecast(loc).provider_id, "met.no")
        self.server.provider_mode["tomorrow"] = "ok"          # the primary is back
        out = []
        for minutes in (1, 16, 31, 61):
            self.clock_t = 1_000_000.0 + minutes * 60
            m._asked.clear(); m._recent.clear()
            out.append(m.fetch_forecast(loc).provider_id)
        return m, out

    def test_recovery_next_update(self):
        _m, out = self.recovery_run("next")
        self.assertEqual(out, ["tomorrow"] * 4)

    def test_recovery_after_30_minutes(self):
        _m, out = self.recovery_run("30")
        self.assertEqual(out, ["met.no", "met.no", "tomorrow", "tomorrow"])

    def test_recovery_after_15_and_60(self):
        self.assertEqual(self.recovery_run("15")[1], ["met.no", "tomorrow", "tomorrow", "tomorrow"])
        self.setUp_again()
        self.assertEqual(self.recovery_run("60")[1], ["met.no", "met.no", "met.no", "tomorrow"])

    def setUp_again(self):
        self.server.provider_calls = {pid: 0 for pid in KEYED}
        self.clock_t = 1_000_000.0

    def test_recovery_stay_until_backup_fails(self):
        m, out = self.recovery_run("stay")
        self.assertEqual(out, ["met.no"] * 4)
        self.server.metno_mode = "http500"                    # the backup fails: back to the primary
        self.clock_t += 60
        m._asked.clear(); m._recent.clear()
        self.assertEqual(m.fetch_forecast(self.loc()).provider_id, "tomorrow")

    def test_use_primary_now(self):
        m, _ = self.recovery_run("stay")
        m.try_primary_now()
        m._asked.clear(); m._recent.clear()
        self.assertEqual(m.fetch_forecast(self.loc()).provider_id, "tomorrow")

    def test_quota_guard_reuses_recent_forecast(self):
        m = self.manager(["tomorrow", "met.no"])
        a = m.fetch_forecast(self.loc())
        self.clock_t += 5 * 60                                 # within Tomorrow.io's 10 minutes
        b = m.fetch_forecast(self.loc())
        self.assertEqual(self.server.provider_calls["tomorrow"], 1)
        self.assertEqual((b.provider_id, b.fetched_at), ("tomorrow", a.fetched_at))
        self.assertIsNot(a, b)
        self.clock_t += 6 * 60
        m.fetch_forecast(self.loc())
        self.assertEqual(self.server.provider_calls["tomorrow"], 2)
        m.fetch_forecast(self.loc(3))                          # another location: its own allowance
        self.assertEqual(self.server.provider_calls["tomorrow"], 3)

    def test_quota_guard_after_failure_uses_backup(self):
        self.server.provider_mode["tomorrow"] = "http429"
        m = self.manager(["tomorrow", "met.no"], recovery="next")
        self.assertEqual(m.fetch_forecast(self.loc()).provider_id, "met.no")
        self.server.provider_mode["tomorrow"] = "ok"
        self.clock_t += 30                                     # quick retry: don't ask Tomorrow.io yet
        self.assertEqual(m.fetch_forecast(self.loc()).provider_id, "met.no")
        self.assertEqual(self.server.provider_calls["tomorrow"], 1)

    def test_new_key_resets_provider(self):
        self.server.provider_mode["openweather"] = "no_onecall"
        m = self.manager(["openweather"])
        m.fetch_forecast(self.loc())
        self.assertGreater(m.provider("openweather")._onecall_off_until, 0)
        m.set_key("openweather", PF.KEYS["openweather"])
        self.assertEqual(m.provider("openweather")._onecall_off_until, 0)   # fresh instance

    def test_status_saved_without_keys(self):
        f = self.tmp / "providers.json"
        for pid in KEYED:
            self.keys.set(pid, f"WRONG-KEY-{pid}-abcdef123456")
        m = self.manager(KEYED + ["met.no"], status_file=f)
        m.fetch_forecast(self.loc())
        text = f.read_text()
        for pid in KEYED:
            self.assertNotIn(f"WRONG-KEY-{pid}", text)
            self.assertNotIn(PF.KEYS[pid], text)
        m2 = self.manager(["met.no"], status_file=f)            # restart
        self.assertEqual(m2.state("visualcrossing"), "failing")
        self.assertEqual(m2.active, "met.no")
        self.assertGreater(m2.status("met.no").last_ok, 0)

    def test_test_connection(self):
        m = self.manager(["met.no"])
        ok, msg, usage = m.test("tomorrow", self.loc())
        self.assertTrue(ok, msg)
        self.assertIn("5 days", msg)
        self.assertIn("120 hours hourly", msg)
        self.assertIn("left today", usage["today"])
        ok, msg, _ = m.test("weatherapi", self.loc(), key="typed-but-wrong-key-999")
        self.assertFalse(ok)
        self.assertNotIn("typed-but-wrong-key-999", msg)
        self.assertEqual(m.status("weatherapi").test_ok, False)
        ok, msg, _ = m.test("accuweather", self.loc())
        self.assertFalse(ok)
        self.assertIn("isn't integrated", msg)

    def test_location_search_always_open_meteo(self):
        m = self.manager(["tomorrow"])
        self.assertEqual([p.name for p in m.search_locations("Ham")], ["Hamilton", "Hamilton"])


# --------------------------------------------------------------- normaliser
class TestNormalise(unittest.TestCase):
    def fc(self, **cur):
        c = dict(time="2026-11-17T10:15", temperature=16.0, apparent_temperature=None, humidity=70.0,
                 weather_code=None, is_day=None, wind_speed=18.0, wind_direction=370.0, wind_gusts=-1.0,
                 pressure=float("nan"), cloud_cover=130.0, precipitation=None)
        c.update(cur)
        return Forecast(location=Location("Auckland", -36.85, 174.76, timezone="Pacific/Auckland"),
                        timezone="Pacific/Auckland", current=CurrentWeather(**c),
                        hourly=[HourlyPoint(f"2026-11-18T{h:02d}:00", 14.0, 30.0 + h, 0.1, [61, 3][h % 2])
                                for h in range(24)],
                        daily=[DailyPoint(f"2026-11-{17 + i}", None, 10.0, 20.0, None, None, None, None, None, -2)
                               for i in range(9)],
                        source="X", provider_id="x")

    def test_fills_and_cleans(self):
        loc = Location("Auckland", -36.85, 174.76, timezone="Pacific/Auckland")
        fc = normalise(self.fc(), loc, 7)
        c = fc.current
        self.assertEqual((c.cloud_cover, c.wind_direction, c.wind_gusts, c.pressure), (100.0, 10.0, None, None))
        self.assertTrue(c.is_day)                                      # 10:15 in November
        self.assertIsNotNone(c.apparent_temperature)
        self.assertEqual(c.weather_code, 3)                            # 100 % cloud
        self.assertEqual(len(fc.daily), 7)
        d = fc.daily[0]
        self.assertEqual((d.temp_min, d.temp_max), (10.0, 20.0))       # swapped back
        self.assertIsNone(d.uv_index_max)                              # negative: dropped
        self.assertTrue(d.sunrise.startswith("2026-11-17T05:") or d.sunrise.startswith("2026-11-17T06:"))
        self.assertEqual(fc.daily[1].weather_code, 61)                 # from that day's hours
        self.assertEqual(fc.daily[1].precipitation_probability_max, 53.0)
        self.assertIsNone(fc.daily[0].precipitation_probability_max)   # no hours that day: stays "–"
        self.assertEqual(fc.utc_offset_seconds, 13 * 3600)
        for what in ("day/night", "feels like", "sunrise/sunset", "current condition (from cloud and rain)",
                     "daily condition (from hourly)", "daily chance of rain (from hourly)"):
            self.assertIn(what, fc.calculated)

    def test_unknown_stays_unknown(self):
        loc = Location("Auckland", -36.85, 174.76, timezone="Pacific/Auckland")
        fc = normalise(self.fc(cloud_cover=None, humidity=None), loc)
        self.assertIsNone(fc.current.weather_code)
        self.assertIsNone(fc.current.apparent_temperature)
        self.assertEqual(weather_codes.describe(fc.current.weather_code), "Unknown")

    def test_no_temperature_is_an_error(self):
        with self.assertRaises(DataError):
            normalise(self.fc(temperature=None), Location("A", 0, 0))

    def test_code_from(self):
        self.assertEqual([code_from(c, None) for c in (0, 20, 50, 90)], [0, 1, 2, 3])
        self.assertEqual([code_from(None, p) for p in (0.5, 4, 9)], [61, 63, 65])
        self.assertIsNone(code_from(None, None))


# -------------------------------------------------------------------- keys
class TestKeyStore(TempEnvTestCase):
    def test_private_file(self):
        ks = KeyStore(self.tmp / "cfg", use_keyring=False)
        ks.set("tomorrow", "  abc123def456  ")
        self.assertEqual(ks.get("tomorrow"), "abc123def456")
        self.assertEqual(stat.S_IMODE(os.stat(ks.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(ks.dir).st_mode), 0o700)
        self.assertIn("private file", ks.backend)
        ks.set("weatherapi", "zzz999yyy888")
        ks.delete("tomorrow")
        self.assertIsNone(ks.get("tomorrow"))
        self.assertEqual(ks.get("weatherapi"), "zzz999yyy888")
        ks.delete("weatherapi")
        self.assertFalse(ks.path.exists())

    def test_rejects_non_keys(self):
        ks = KeyStore(self.tmp, use_keyring=False)
        for bad in ("", "   ", "has space", "x" * 600):
            with self.assertRaises(ValueError):
                ks.set("tomorrow", bad)

    def test_loosened_permissions_are_tightened(self):
        ks = KeyStore(self.tmp, use_keyring=False)
        ks.set("tomorrow", "abc123def456")
        os.chmod(ks.path, 0o644)
        self.assertEqual(KeyStore(self.tmp, use_keyring=False).get("tomorrow"), "abc123def456")
        self.assertEqual(stat.S_IMODE(os.stat(ks.path).st_mode), 0o600)

    @unittest.skipUnless(importlib.util.find_spec("keyring"), "python3-keyring not installed "
                         "(it's a Recommends of the package; the private-file path is tested regardless)")
    def test_system_keyring_used_when_available(self):
        import keyring
        from keyring.backend import KeyringBackend

        class Memory(KeyringBackend):
            priority = 5
            store: dict = {}

            def get_password(self, s, u):
                return self.store.get((s, u))

            def set_password(self, s, u, p):
                self.store[(s, u)] = p

            def delete_password(self, s, u):
                self.store.pop((s, u), None)

        old = keyring.get_keyring()
        keyring.set_keyring(Memory())
        try:
            ks = KeyStore(self.tmp, use_keyring=True)
            self.assertIn("system keyring", ks.backend)
            ks.set("tomorrow", "kr-secret-123456")
            self.assertEqual(Memory.store[("RBSB-Weather", "tomorrow")], "kr-secret-123456")
            self.assertFalse(ks.path.exists())                  # nothing on disk
            self.assertEqual(ks.get("tomorrow"), "kr-secret-123456")
            ks.delete("tomorrow")
            self.assertIsNone(ks.get("tomorrow"))
        finally:
            keyring.set_keyring(old)

    @unittest.skipUnless(importlib.util.find_spec("keyring"), "python3-keyring not installed")
    def test_insecure_keyring_not_used(self):
        import keyring
        from keyring.backends import fail
        old = keyring.get_keyring()
        keyring.set_keyring(fail.Keyring())
        try:
            self.assertIn("private file", KeyStore(self.tmp, use_keyring=True).backend)
        finally:
            keyring.set_keyring(old)

    def test_keys_never_in_settings_or_cache(self):
        from rbsb_weather.storage import Settings, SettingsStore
        ks = KeyStore(self.tmp / "cfg", use_keyring=False)
        ks.set("tomorrow", "SETTINGS-LEAK-CHECK-123")
        store = SettingsStore(self.tmp / "cfg")
        store.save(Settings(provider_chain=["tomorrow", "met.no"]))
        self.assertNotIn("SETTINGS-LEAK-CHECK-123", store.path.read_text())

    def test_gitignore_refuses_key_files(self):
        text = (Path(__file__).resolve().parents[1] / ".gitignore").read_text()
        for pat in ("keys.json", "*.key", ".env"):
            self.assertIn(pat, text)


class TestRedaction(unittest.TestCase):
    def test_redact(self):
        remember_secret("SAVEDKEY-abcdef")
        self.assertEqual(redact("bad key SAVEDKEY-abcdef here"), f"bad key {MASK} here")
        self.assertEqual(redact("GET /x?appid=zzz&units=metric&key=Q1&apikey=Q2&token=Q3"),
                         f"GET /x?appid={MASK}&units=metric&key={MASK}&apikey={MASK}&token={MASK}")
        self.assertEqual(redact("one-off", ["one-off-but-short"]), "one-off")
        self.assertEqual(redact("x TYPED123 y", ["TYPED123"]), f"x {MASK} y")

    def test_log_filter(self):
        remember_secret("LOGGED-SECRET-999")
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.addFilter(RedactingFilter())
        lg = logging.getLogger("rbsb_weather.test.redact")
        lg.addHandler(h)
        lg.propagate = False
        try:
            lg.warning("failed with %s at https://h/x?appid=%s", "LOGGED-SECRET-999", "abc")
            try:
                raise ValueError("boom LOGGED-SECRET-999")
            except ValueError:
                lg.exception("crash")
        finally:
            lg.removeHandler(h)
        out = buf.getvalue()
        self.assertNotIn("LOGGED-SECRET-999", out)
        self.assertNotIn("appid=abc", out)
        self.assertIn(MASK, out)
        self.assertIn("ValueError", out)

    def test_app_installs_filter(self):
        from rbsb_weather import app
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            with mock.patch("rbsb_weather.storage.cache_dir", side_effect=OSError):
                root.handlers = []
                app._setup_logging(False)
            self.assertTrue(all(any(isinstance(f, RedactingFilter) for f in h.filters) for h in root.handlers))
        finally:
            root.handlers = before


class TestSettingsMigration(unittest.TestCase):
    def test_from_1_12(self):
        from rbsb_weather.storage import Settings
        self.assertEqual(Settings.from_dict({"weather_source": "met.no"}).provider_chain, ["met.no", "open-meteo"])
        self.assertEqual(Settings.from_dict({}).provider_chain, ["open-meteo", "met.no"])
        s = Settings.from_dict({"provider_chain": ["tomorrow", "../evil", 5, "tomorrow", "met.no"],
                                "provider_recovery": "stay"})
        self.assertEqual((s.provider_chain, s.provider_recovery), (["tomorrow", "met.no"], "stay"))
        self.assertEqual(Settings.from_dict({"provider_recovery": "never"}).provider_recovery, "30")
        o = Settings.from_dict({"provider_options": {"wunderground": {"station_id": "IWAIUK12", "n": 5},
                                                      "BAD ID": {"x": "y"}, "tomorrow": "nope"}})
        self.assertEqual(o.provider_options, {"wunderground": {"station_id": "IWAIUK12"}})
        m = ProviderManager(chain=["open-meteo"], options=o.provider_options | {"wunderground2": {"a": "b"}},
                            keystore=KeyStore(Path("/nonexistent-wd"), use_keyring=False))
        self.assertEqual(m.options, {"wunderground": {"station_id": "IWAIUK12"}})   # unknown ids ignored
        d = Settings(provider_chain=["weatherapi", "open-meteo"]).to_dict()
        self.assertEqual(d["provider_chain"], ["weatherapi", "open-meteo"])


class TestDiagnostics(ProviderCase):
    def test_report_lists_chain_without_keys(self):
        from rbsb_weather import diagnostics
        self.server.provider_mode["tomorrow"] = "http500"
        self.keys.delete("weatherapi")
        m = self.manager(["tomorrow", "weatherapi", "visualcrossing"])
        with mock.patch.object(diagnostics, "PROBE_TIMEOUT", 1.0):
            rep = diagnostics.run_diagnostics(m)
        self.assertIn("Forecast – Tomorrow.io (primary, key saved (not shown)): FAILED", rep)
        self.assertIn("Forecast – WeatherAPI.com (backup 1): skipped – no API key saved", rep)
        self.assertIn("Forecast – Visual Crossing (backup 2, key saved (not shown)): OK", rep)
        self.assertIn("but Visual Crossing works", rep)
        for k in PF.KEYS.values():
            self.assertNotIn(k, rep)


# ------------------------------------------------------------------- window
class WindowCase(ProviderCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.windows = []

    def tearDown(self):
        from PyQt6.QtTest import QTest
        for w in self.windows:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def make(self, chain, recovery="30"):
        from rbsb_weather.main_window import MainWindow
        m = ProviderManager(chain=chain, recovery=recovery, keystore=self.keys,
                            factories=PF.factories(self.server), status_file=self.tmp / "providers.json")
        w = MainWindow(client=m, enable_tray=False)
        self.windows.append(w)
        w.show()
        return w

    def add(self, w, i=0):
        w.add_location(self.place(i))
        k = self.place(i).key
        self.assertTrue(wait_until(lambda: k in w.forecasts and k not in w._pending))
        return k

    def all_text(self, widget) -> str:
        from PyQt6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QListWidget
        parts = []
        for cls in (QLabel, QLineEdit, QAbstractButton):
            for x in widget.findChildren(cls):
                parts.append(x.text())
                parts.append(x.toolTip())
        for x in widget.findChildren(QListWidget):
            parts += [x.item(i).text() for i in range(x.count())]
        for x in widget.findChildren(QComboBox):
            parts += [x.itemText(i) for i in range(x.count())]
        return "\n".join(parts)


class TestWindowProviders(WindowCase):
    def test_every_provider_drives_the_whole_window(self):
        for pid in ALL:
            w = self.make([pid])
            k = self.add(w)
            fc = w.forecasts[k]
            self.assertEqual(fc.provider_id, pid)
            self.assertRegex(w.temp_label.text(), r"°C$")
            self.assertNotIn("Unknown", w.desc_label.text())
            self.assertIn(providers.info(pid).credit, w.status_label.text())
            self.assertIn("Updated", w.status_label.text())
            self.assertIn("just now", w.status_label.text())
            if pid == "wunderground":      # no hourly forecast on a PWS key: says so instead
                self.assertEqual(w.chart.point_count(), 0)
                self.assertEqual(w.chart.empty_text, "Weather Underground doesn't provide an hourly forecast")
            else:
                self.assertGreater(w.chart.point_count(), 0, pid)
            self.assertTrue(w.day_rows[0][0].text())
            self.assertNotEqual(w.detail["sunrise"].text(), "–", pid)
            w.set_desktop_widget(True)
            self.assertRegex(w.desktop_widget.temp.text(), r"°")
            w.set_desktop_widget(False)

    def test_backup_shown_in_status(self):
        self.server.provider_mode["tomorrow"] = "http500"
        w = self.make(["tomorrow", "met.no"])
        k = self.add(w)
        self.assertEqual(w.forecasts[k].provider_id, "met.no")
        self.assertNotIn(k, w.errors)
        self.assertIn("from MET Norway (backup)", w.status_label.text())
        self.assertIn("MET Norway (CC BY 4.0)", w.status_label.text())

    def test_missing_fields_show_dash(self):
        self.server.provider_mode["openweather"] = "no_onecall"     # free key: no UV index
        w = self.make(["openweather"])
        self.add(w)
        self.assertEqual(w.detail["uv"].text(), "–")


class TestProvidersDialog(WindowCase):
    def open(self, w):
        w.show_providers()
        d = w._providers_dialog
        self.assertTrue(wait_until(lambda: d.isVisible()))
        return d

    def select(self, d, pid):
        from PyQt6.QtCore import Qt
        for i in range(d.list.count()):
            if d.list.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                d.list.setCurrentRow(i)
                return
        self.fail(pid)

    def test_lists_everything_with_status(self):
        self.keys.delete("openweather")
        w = self.make(["open-meteo", "met.no"])
        self.add(w)
        d = self.open(w)
        self.assertEqual(d.list.count(), 9)
        texts = [d.list.item(i).text() for i in range(d.list.count())]
        self.assertIn("(primary)", texts[0])
        self.assertIn("supplying now", texts[0])
        self.assertIn("Needs an API key", texts[2])
        self.assertIn("Planned", texts[7])
        self.assertEqual([d.primary.itemData(i) for i in range(d.primary.count())], ALL)   # no planned ones
        self.select(d, "accuweather")
        self.assertFalse(d.key_box.isVisible())
        self.assertFalse(d.btn_test.isVisible())
        self.assertIn("Paid-only", d.f["reason"].text())
        self.select(d, "tomorrow")
        self.assertIn("500 requests a day", d.f["limits"].text())
        self.assertIn("✓ UV index", d.f["features"].text())
        self.assertIn("Currently supplying the weather: <b>Open-Meteo</b>", d.supplying.text())

    def test_every_row_shows_both_lines(self):
        """1.13.0 on Shane's desktop: one row kept a one-line height and showed
        "MET Norway (backup 1)…" with its status cut off."""
        from PyQt6.QtGui import QFontMetrics
        w = self.make(["open-meteo", "met.no"])
        self.add(w)
        d = self.open(w)
        two_lines = 2 * QFontMetrics(d.list.font()).lineSpacing()
        for _ in range(2):                                   # before and after a status change
            for i in range(d.list.count()):
                self.assertGreaterEqual(d.list.visualItemRect(d.list.item(i)).height(), two_lines,
                                        d.list.item(i).text())
            d.manager.set_key("tomorrow", PF.KEYS["tomorrow"])
            d._refresh_list()

    def test_add_change_remove_key_never_shown(self):
        self.keys.delete("weatherapi")
        w = self.make(["open-meteo"])
        d = self.open(w)
        self.select(d, "weatherapi")
        self.assertIn("No key saved", d.key_status.text())
        d.btn_key.click()
        self.assertTrue(d.key_editor.isVisible())
        from PyQt6.QtWidgets import QLineEdit
        self.assertEqual(d.key_edit.echoMode(), QLineEdit.EchoMode.Password)
        d.key_edit.setText(PF.KEYS["weatherapi"])
        d.btn_save_key.click()
        self.assertEqual(self.keys.get("weatherapi"), PF.KEYS["weatherapi"])
        self.assertEqual(d.key_edit.text(), "")                              # cleared at once
        self.assertFalse(d.key_editor.isVisible())
        self.assertIn(MASK, d.key_status.text())
        self.assertEqual(d.btn_key.text(), "Change key…")
        self.assertTrue(wait_until(lambda: d._testing is None and "Connected" in d.test_result.text(), 10))
        self.assertIn("3 days", d.test_result.text())
        self.assertNotIn(PF.KEYS["weatherapi"], self.all_text(d))
        d.btn_key.click()
        self.assertEqual(d.key_edit.text(), "")                              # never pre-filled
        d.btn_cancel_key.click()
        d.btn_remove.click()
        self.assertIsNone(self.keys.get("weatherapi"))
        self.assertIn("No key saved", d.key_status.text())

    def test_bad_key_test_result(self):
        w = self.make(["open-meteo"])
        d = self.open(w)
        self.select(d, "visualcrossing")
        d.btn_key.click()
        d.key_edit.setText("TYPED-WRONG-VC-KEY-42")
        d.btn_test.click()                                                    # tests the typed key
        self.assertTrue(wait_until(lambda: d._testing is None and "Failed" in d.test_result.text(), 10))
        self.assertIn("rejected the API key", d.test_result.text())
        self.assertNotIn("TYPED-WRONG-VC-KEY-42", d.test_result.text())
        self.assertEqual(self.keys.get("visualcrossing"), PF.KEYS["visualcrossing"])   # not saved

    def test_order_and_recovery_saved(self):
        w = self.make(["open-meteo", "met.no"])
        k = self.add(w)
        d = self.open(w)
        d.primary.setCurrentIndex(d.primary.findData("tomorrow"))
        from PyQt6.QtCore import Qt
        for i in range(d.backups.count()):
            it = d.backups.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in
                             ("visualcrossing", "open-meteo") else Qt.CheckState.Unchecked)
        d.recovery.setCurrentIndex(d.recovery.findData("stay"))
        self.assertEqual(d.chosen_chain()[0], "tomorrow")
        d.buttons.button(d.buttons.StandardButton.Ok).click()
        self.assertEqual(w.client.chain[0], "tomorrow")
        self.assertEqual(set(w.client.chain[1:]), {"visualcrossing", "open-meteo"})
        saved = w.store.load()
        self.assertEqual((saved.provider_chain, saved.provider_recovery), (w.client.chain, "stay"))
        self.assertTrue(wait_until(lambda: k not in w._pending and w.forecasts[k].provider_id == "tomorrow"))

    def test_warnings(self):
        self.keys.delete("tomorrow")
        w = self.make(["open-meteo"])
        d = self.open(w)
        d.primary.setCurrentIndex(d.primary.findData("tomorrow"))
        from PyQt6.QtCore import Qt
        for i in range(d.backups.count()):
            d.backups.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.assertIn("No API key saved for Tomorrow.io", d.warning.text())
        self.assertIn("No backup is ticked", d.warning.text())

    def test_currently_supplying_and_primary_now(self):
        self.server.provider_mode["tomorrow"] = "http500"
        w = self.make(["tomorrow", "met.no"])
        k = self.add(w)
        d = self.open(w)
        self.assertIn("<b>MET Norway</b> (backup)", d.supplying.text())
        self.assertTrue(d.btn_primary_now.isVisible())
        self.server.provider_mode["tomorrow"] = "ok"
        w.client._asked.clear()
        d.btn_primary_now.click()
        self.assertTrue(wait_until(lambda: k not in w._pending and w.forecasts[k].provider_id == "tomorrow"))
        self.assertTrue(wait_until(lambda: "<b>Tomorrow.io</b> (primary)" in d.supplying.text()))

    def test_station_id_option(self):
        w = self.make(["open-meteo"])
        d = self.open(w)
        self.select(d, "tomorrow")
        self.assertFalse(d.opt_box.isVisible())
        self.select(d, "wunderground")
        self.assertTrue(d.opt_box.isVisible())
        self.assertIn("none with a PWS key", d.f["hourly"].text())
        edit = d.opt_widgets["station_id"]
        edit.setText("bad id!")
        d._save_option("wunderground", "station_id", edit)
        self.assertIn("valid station id", d.test_result.text())
        edit.setText("IWAIUK12")
        d._save_option("wunderground", "station_id", edit)
        self.assertEqual(w.store.load().provider_options, {"wunderground": {"station_id": "IWAIUK12"}})
        self.assertEqual(w.client.options["wunderground"]["station_id"], "IWAIUK12")
        self.select(d, "tomorrow"); self.select(d, "wunderground")
        self.assertEqual(d.opt_widgets["station_id"].text(), "IWAIUK12")       # shown again (not secret)

    def test_menu(self):
        w = self.make(["open-meteo"])
        self.assertEqual(w.act_providers.text(), "Weather &Providers…")
        w.act_providers.trigger()
        self.assertTrue(wait_until(lambda: w._providers_dialog.isVisible()))


if __name__ == "__main__":
    unittest.main()
