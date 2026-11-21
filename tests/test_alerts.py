"""Weather warnings (2.4): parsing each service's format, matching warnings to places,
levels, own limits, the store and notifications. Created By Shane BlackbuRn"""

from __future__ import annotations

import datetime as dt
import json
import time
import unittest
import xml.etree.ElementTree as ET

from helpers import TempEnvTestCase
import alert_fixtures as AF

from rbsb_weather import alerts as A
from rbsb_weather.models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location

AUCKLAND = Location("Auckland", -36.84853, 174.76349, "New Zealand", "Auckland", "Pacific/Auckland")
WELLINGTON = Location("Wellington", -41.28664, 174.77557, "New Zealand", "Wellington", "Pacific/Auckland")
CHRISTCHURCH = Location("Christchurch", -43.53333, 172.63333, "New Zealand", "Canterbury", "Pacific/Auckland")
LONDON = Location("London", 51.50853, -0.12574, "United Kingdom", "England", "Europe/London")
PARIS = Location("Paris", 48.85341, 2.3488, "France", "Île-de-France", "Europe/Paris")
NEW_YORK = Location("New York", 40.71427, -74.00597, "United States", "New York", "America/New_York")
OSLO = Location("Oslo", 59.91273, 10.74609, "Norway", "Oslo", "Europe/Oslo")
TOKYO = Location("Tokyo", 35.6895, 139.69171, "Japan", "Tokyo", "Asia/Tokyo")


class GeometryTest(unittest.TestCase):
    def test_point_in_polygon(self):
        ring = A.parse_cap_polygon("-36.30,174.40 -36.30,175.60 -37.30,175.60 -37.30,174.40 -36.30,174.40")
        self.assertTrue(A.point_in_ring(-36.85, 174.76, ring))
        self.assertFalse(A.point_in_ring(-41.29, 174.78, ring))

    def test_ring_across_the_antimeridian(self):
        ring = A.parse_cap_polygon("-43,176 -43,-176 -45,-176 -45,176 -43,176")   # Chatham Islands box
        self.assertTrue(A.point_in_ring(-44.0, -176.5, ring))
        self.assertTrue(A.point_in_ring(-44.0, 179.0, ring))
        self.assertFalse(A.point_in_ring(-44.0, 170.0, ring))

    def test_bad_polygons_are_ignored(self):
        self.assertEqual(A.parse_cap_polygon("1,2 3"), [])
        self.assertEqual(A.parse_cap_polygon("95,0 1,1 2,2"), [])
        self.assertEqual(A.covers([], 0, 0), None)

    def test_circle(self):
        self.assertTrue(A.in_circle(-36.85, 174.76, "-36.9,174.8 20"))
        self.assertFalse(A.in_circle(-41.3, 174.8, "-36.9,174.8 20"))

    def test_geojson_with_a_hole(self):
        g = {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                                                [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
        self.assertTrue(A.geojson_contains(g, 2, 2))
        self.assertFalse(A.geojson_contains(g, 5, 5))
        self.assertIsNone(A.geojson_contains(None, 5, 5))


class LevelTest(unittest.TestCase):
    def test_metservice_colour_beats_its_lower_severity(self):
        # MetService's CAP severity sits a step below the colour it issues
        self.assertEqual(A.level_from("Moderate", "rain", "Orange", "Heavy Rain Warning - Orange",
                                      trust_severity=False), "orange")
        self.assertEqual(A.level_from("Minor", "wind", "Yellow", "Strong Wind Watch", trust_severity=False), "watch")
        self.assertEqual(A.level_from("Severe", "rain", "Red", "", trust_severity=False), "red")

    def test_cap_severity(self):
        self.assertEqual(A.level_from("Extreme", "Tornado Warning"), "red")
        self.assertEqual(A.level_from("Severe", "Flood Warning"), "orange")
        self.assertEqual(A.level_from("Moderate", "Winter Storm Watch"), "watch")
        self.assertEqual(A.level_from("Minor", "Special Weather Statement"), "minor")
        self.assertEqual(A.level_from("", "Some Warning"), "yellow")

    def test_meteoalarm_awareness_level(self):
        self.assertEqual(A.level_from("Moderate", "Rain", "3; orange; Severe"), "orange")

    def test_title(self):
        a = A.Alert("x", "MetService", "orange", "Heavy Rain Warning")
        self.assertEqual(a.title(), "Orange Heavy Rain Warning")
        self.assertEqual(A.Alert("y", "s", "watch", "Strong Wind Watch").title(), "Strong Wind Watch")


class ParseTest(unittest.TestCase):
    def test_metservice_cap(self):
        root = ET.fromstring(AF.fill("cap_rain_auckland.xml", "http://x"))
        a, areas = A.cap_alert(root, "MetService", "http://x/cap", "ColourCode", trust_severity=False)
        self.assertEqual(a.level, "orange")
        self.assertEqual(a.event, "Heavy Rain Warning")          # "- Orange" goes: the level shows it
        self.assertEqual(a.hazard, "rain")
        self.assertIn("100 to 140 mm", a.description)
        self.assertTrue(a.instruction.startswith("Streams"))
        self.assertEqual(a.area, "Auckland, including the Hauraki Gulf islands")
        self.assertTrue(A.covers(areas, AUCKLAND.latitude, AUCKLAND.longitude))
        self.assertFalse(A.covers(areas, WELLINGTON.latitude, WELLINGTON.longitude))
        self.assertTrue(a.in_force())

    def test_tests_and_cancellations_are_dropped(self):
        self.assertIsNone(A.cap_alert(ET.fromstring(AF.fill("cap_test.xml", "")), "MetService"))
        cancelled = AF.fill("cap_rain_auckland.xml", "").replace(b"<msgType>Update</msgType>",
                                                                  b"<msgType>Cancel</msgType>")
        self.assertIsNone(A.cap_alert(ET.fromstring(cancelled), "MetService"))

    def test_nws(self):
        al = A.parse_nws(json.loads(AF.fill("nws_point.json", "")))
        self.assertEqual(len(al), 1)                             # the Test message is dropped
        a = al[0]
        self.assertEqual((a.level, a.event, a.hazard), ("watch", "Winter Storm Watch", "snow"))
        self.assertIn("6 to 10 inches", a.description)
        self.assertTrue(a.url.startswith("https://api.weather.gov/alerts/"))

    def test_metno(self):
        al = A.parse_metno(json.loads(AF.fill("metno_current.json", "")), OSLO.latitude, OSLO.longitude)
        self.assertEqual(len(al), 1)                             # Troms is far from Oslo
        self.assertEqual((al[0].level, al[0].event, al[0].hazard), ("orange", "Wind", "wind"))
        self.assertIn("Trees may fall", al[0].description)

    def test_doctype_and_entities_are_refused(self):
        with self.assertRaises(A.AlertError):
            A._xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')

    def test_garbage_never_crashes(self):
        for bad in ({}, [], {"features": "x"}, {"features": [None, 1, {"properties": None}]}):
            self.assertEqual(A.parse_nws(bad), [])
            self.assertEqual(A.parse_metno(bad, 0, 0), [])

    def test_alert_round_trip_and_bad_values(self):
        a = A.Alert("id1", "MetService", "red", "Heavy Rain Warning", onset=1.0, expires=2.0,
                    url="javascript:alert(1)")
        self.assertEqual(a.url, "javascript:alert(1)")
        b = A.Alert.from_dict(a.to_dict())
        self.assertEqual(b.url, "")                               # only web links survive
        self.assertEqual(b.level, "red")
        self.assertEqual(A.Alert.from_dict({"id": "z", "level": "purple"}).level, "minor")


class CoverageTest(unittest.TestCase):
    def test_sources(self):
        self.assertEqual(A.source_for(AUCKLAND), "metservice")
        self.assertEqual(A.source_for(NEW_YORK), "nws")
        self.assertEqual(A.source_for(OSLO), "metno")
        self.assertEqual(A.source_for(LONDON), "meteoalarm")
        self.assertEqual(A.source_for(PARIS), "meteoalarm")
        self.assertIsNone(A.source_for(TOKYO))
        self.assertEqual(A.coverage_text(TOKYO), "Not covered yet")
        # a place saved without a country, in New Zealand
        self.assertEqual(A.source_for(Location("Somewhere", -40.0, 175.0)), "metservice")


class ClientTest(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        base = f"http://127.0.0.1:{self.server.port}"
        self.urls = AF.install(self.server, base)
        self.client = A.AlertClient(metservice_url=self.urls["metservice"], nws_url=self.urls["nws"],
                                    metno_url=self.urls["metno"], meteoalarm_url=self.urls["meteoalarm"],
                                    timeout=5)

    def test_every_source_matched_to_the_right_places(self):
        locs = [AUCKLAND, WELLINGTON, CHRISTCHURCH, LONDON, NEW_YORK, OSLO, TOKYO]
        got, errors = self.client.fetch_all(locs)
        self.assertEqual(errors, {})
        self.assertEqual([a.title() for a in got[AUCKLAND.key]], ["Orange Heavy Rain Warning"])
        self.assertEqual([a.title() for a in got[WELLINGTON.key]], ["Strong Wind Watch"])
        self.assertEqual(got[CHRISTCHURCH.key], [])
        self.assertEqual([(a.level, a.source) for a in got[LONDON.key]], [("yellow", "MeteoAlarm")])
        self.assertEqual([a.event for a in got[NEW_YORK.key]], ["Winter Storm Watch"])
        self.assertEqual([a.level for a in got[OSLO.key]], ["orange"])
        self.assertNotIn(TOKYO.key, got)
        # NWS and MET Norway require an identifying User-Agent
        self.assertTrue(all("RBSB-Weather/" in ua and "github.com" in ua for ua in self.server.alert_agents))

    def test_cap_documents_are_fetched_once(self):
        self.client.fetch_all([AUCKLAND])
        self.client.fetch_all([AUCKLAND])
        hits = {k.rsplit("/", 1)[-1]: v for k, v in self.server.alert_hits.items()}
        self.assertEqual(hits["rss"], 2)
        self.assertEqual(hits["rain-auckland.xml"], 1)

    def test_one_source_failing_keeps_the_others(self):
        self.server.alert_mode["metservice"] = "http500"
        self.server.alert_mode["nws"] = "garbage"
        got, errors = self.client.fetch_all([AUCKLAND, LONDON, NEW_YORK])
        self.assertIn("metservice", errors)
        self.assertIn("nws", errors)
        self.assertNotIn(AUCKLAND.key, got)          # unknown: keep the warnings already shown
        self.assertNotIn(NEW_YORK.key, got)
        self.assertEqual(len(got[LONDON.key]), 1)

    def test_garbage_xml_is_a_clean_error(self):
        self.server.alert_mode["metservice"] = "garbage"
        got, errors = self.client.fetch_all([AUCKLAND])
        self.assertIn("couldn't be read", errors["metservice"])

    def test_country_without_a_feed(self):
        got, errors = self.client.fetch_all([PARIS])
        self.assertIn("France", errors.get("meteoalarm", ""))

    def test_no_warnings(self):
        for k in self.server.alert_mode:
            self.server.alert_mode[k] = "none"
        got, errors = self.client.fetch_all([AUCKLAND, LONDON, NEW_YORK, OSLO])
        self.assertEqual(errors, {})
        self.assertTrue(all(v == [] for v in got.values()))
        self.assertEqual(len(got), 4)


def _fc(loc=AUCKLAND, rain=(64, 38, 0.4, 0, 0, 0, 0), tmin=(12, 13, 12, 11, 10, -2, 9),
        tmax=(16, 17, 19, 21, 22, 20, 18), codes=(65, 63, 3, 0, 1, 95, 2), gusts=(72, 95, 40, 30, 30, 50, 40),
        off=13 * 3600):
    tz = dt.timezone(dt.timedelta(seconds=off))
    today = dt.datetime.now(tz).date()
    daily = [DailyPoint((today + dt.timedelta(days=i)).isoformat(), codes[i], tmax[i], tmin[i], rain[i], 50, 30,
                        None, None, 3) for i in range(7)]
    start = dt.datetime.combine(today, dt.time())
    hourly = [HourlyPoint((start + dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M"), 14, 80, 2.0, 63)
              for h in range(48)]
    cur = CurrentWeather("", 14, 12, 90, 65, True, 30, 45, 70, 1000, 100, 2)
    return Forecast(loc, "Pacific/Auckland", cur, hourly, daily, fetched_at=time.time(),
                    utc_offset_seconds=off, daily_gusts=list(gusts))


class OwnLimitsTest(unittest.TestCase):
    def test_defaults(self):
        al = A.own_alerts(_fc(), A.limits_from_dict(None))
        titles = [a.event for a in al]
        self.assertIn("My limit: wind gusts over 90 km/h", titles)
        self.assertIn("My limit: rain over 50.0 mm in a day", titles)
        self.assertIn("My limit: temperature below 0°C", titles)
        self.assertIn("My limit: thunderstorms", titles)
        self.assertNotIn("My limit: snow", titles)                    # off by default
        self.assertTrue(all(not a.official and a.level == "limit" for a in al))
        gust = next(a for a in al if a.hazard == "wind")
        self.assertIn("Tomorrow", gust.headline)
        self.assertIn("not an official warning", gust.description)

    def test_values_in_the_users_units_and_later_days(self):
        lim = A.limits_from_dict({"rain": {"on": True, "value": 30}, "gust": {"on": False, "value": 90}})
        al = A.own_alerts(_fc(), lim, wind_unit="mph", temp_unit="F", precip_unit="in")
        rain = next(a for a in al if a.hazard == "rain")
        self.assertIn("1.18 in", rain.event)
        self.assertIn("Also: Tomorrow", rain.headline)
        self.assertFalse(any(a.hazard == "wind" for a in al))

    def test_limits_are_validated(self):
        lim = A.limits_from_dict({"gust": {"on": "yes", "value": 10_000}, "rain": {"value": True}, "x": 1})
        self.assertTrue(lim["gust"].on)
        self.assertEqual(lim["gust"].value, 250)
        self.assertEqual(lim["rain"].value, 50)
        self.assertEqual(A.limits_to_dict(lim)["gust"], {"on": True, "value": 250})

    def test_gusts_missing_uses_todays_current_gust_only(self):
        fc = _fc(gusts=())
        fc.current.wind_gusts = 100
        lim = A.limits_from_dict({k: {"on": k == "gust"} for k in A.DEFAULT_LIMITS})
        al = A.own_alerts(fc, lim)
        self.assertEqual(len(al), 1)
        self.assertIn("today", al[0].headline)

    def test_rain_between(self):
        fc = _fc()
        start = dt.datetime.fromisoformat(fc.hourly[0].time).replace(
            tzinfo=dt.timezone(dt.timedelta(seconds=fc.utc_offset_seconds))).timestamp()
        self.assertEqual(A.rain_between(fc, start, start + 10 * 3600), 20.0)
        self.assertIsNone(A.rain_between(fc, None, start))


class ShownAndNotifyTest(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.al = [A.Alert("r", "s", "red", "Red one", expires=now + 3600),
                   A.Alert("o", "s", "orange", "Orange one", expires=now + 3600),
                   A.Alert("w", "s", "watch", "Some Watch", expires=now + 3600),
                   A.Alert("m", "s", "minor", "Statement", expires=now + 3600),
                   A.Alert("old", "s", "red", "Expired", expires=now - 10),
                   A.Alert("lim", "My limits", "limit", "My limit", official=False, expires=now + 3600)]

    def test_levels(self):
        ids = lambda lvl: [a.id for a in A.shown(self.al, lvl)]
        self.assertEqual(ids("all"), ["r", "o", "w", "m", "lim"])
        self.assertEqual(ids("watch"), ["r", "o", "w", "lim"])
        self.assertEqual(ids("orange"), ["r", "o", "lim"])
        self.assertEqual(ids("red"), ["r", "lim"])
        self.assertEqual([a.id for a in A.shown(self.al, "all", muted=["o"])], ["r", "w", "m", "lim"])
        self.assertEqual(A.worst(A.shown(self.al, "watch")).id, "r")

    def test_notify_once_then_again_when_upgraded(self):
        notified = {}
        first = A.to_notify(self.al, notified, "watch")
        self.assertEqual([a.id for a in first], ["r", "o", "w", "lim"])
        for a in first:
            notified[a.id] = a.signature()
        self.assertEqual(A.to_notify(self.al, notified, "watch"), [])
        self.al[1].level = "red"                                  # orange upgraded to red
        self.assertEqual([a.id for a in A.to_notify(self.al, notified, "watch")], ["o"])
        notified["o"] = self.al[1].signature()
        self.al[2].issued = time.time()                           # the watch reissued (e.g. extended)
        self.assertEqual([a.id for a in A.to_notify(self.al, notified, "watch")], ["w"])
        notified["w"] = self.al[2].signature()
        self.al[2].expires += 60                                  # same issue: no new notification
        self.assertEqual(A.to_notify(self.al, notified, "watch"), [])


class StoreTest(TempEnvTestCase):
    def test_round_trip_and_clean_up(self):
        st = A.AlertStore(self.tmp)
        now = time.time()
        st.update({"k1": [A.Alert("a", "MetService", "orange", "Rain", expires=now + 600)],
                   "k2": [A.Alert("b", "MetService", "red", "Wind", expires=now - 5)]}, ["k1", "k2"])
        st.notified = {"a": "sig", "gone": "sig"}
        st.update({}, ["k1", "k2"])
        self.assertEqual(st.notified, {"a": "sig"})              # expired/vanished ones forgotten
        st.save()
        st2 = A.AlertStore(self.tmp).load()
        self.assertEqual([a.id for a in st2.alerts["k1"]], ["a"])
        self.assertEqual(st2.alerts["k2"], [])                   # expired: not reloaded
        st2.update({}, ["k1"])
        self.assertNotIn("k2", st2.alerts)                       # place removed

    def test_damaged_file(self):
        (self.tmp / "alerts.json").write_text("{not json")
        self.assertEqual(A.AlertStore(self.tmp).load().alerts, {})
        (self.tmp / "alerts.json").write_text(json.dumps({"alerts": {"k": [{"no": "id"}, 5]}, "checked": "x"}))
        st = A.AlertStore(self.tmp).load()
        self.assertEqual(st.alerts["k"], [])
        self.assertEqual(st.checked, 0.0)


if __name__ == "__main__":
    unittest.main()


class SettingsAndCacheTest(unittest.TestCase):
    def test_bad_alert_settings_fall_back(self):
        from rbsb_weather.storage import Settings
        s = Settings.from_dict({"alerts_official": "yes", "alerts_min_level": "purple", "alerts_interval": 7,
                                "alerts_limits": {"rain": {"on": True, "value": -5}}, "alerts_muted": "x",
                                "alerts_beep_red": True})
        self.assertTrue(s.alerts_official)
        self.assertEqual((s.alerts_min_level, s.alerts_interval), ("watch", 15))
        self.assertEqual(s.alerts_limits["rain"], {"on": True, "value": 1.0})     # clamped to the range
        self.assertEqual(s.alerts_muted, [])
        self.assertTrue(s.alerts_beep_red)
        self.assertEqual(Settings.from_dict(s.to_dict()), s)

    def test_gusts_cached_and_older_caches_still_load(self):
        from rbsb_weather.api import forecast_from_dict, forecast_to_dict
        fc = _fc()
        d = forecast_to_dict(fc)
        self.assertEqual(forecast_from_dict(d).daily_gusts, [72.0, 95.0, 40.0, 30.0, 30.0, 50.0, 40.0])
        d.pop("daily_gusts")                                     # a cache written before 2.4
        self.assertEqual(forecast_from_dict(d).daily_gusts, [])
        # what an older version reads: every DailyPoint field it knows, nothing new inside them
        self.assertEqual(set(d["daily"][0]), {"date", "weather_code", "temp_max", "temp_min", "precipitation_sum",
                                              "precipitation_probability_max", "wind_speed_max", "sunrise",
                                              "sunset", "uv_index_max"})

    def test_open_meteo_daily_gusts_parsed(self):
        from rbsb_weather.api import DAILY_FIELDS, parse_forecast
        self.assertIn("wind_gusts_10m_max", DAILY_FIELDS)
        data = {"current": {"time": "2026-11-22T10:00", "temperature_2m": 14},
                "daily": {"time": ["2026-11-22", "2026-11-23"], "wind_gusts_10m_max": [72.5, None]}}
        self.assertEqual(parse_forecast(data, AUCKLAND).daily_gusts, [72.5, None])
        data["daily"].pop("wind_gusts_10m_max")
        self.assertEqual(parse_forecast(data, AUCKLAND).daily_gusts, [])
