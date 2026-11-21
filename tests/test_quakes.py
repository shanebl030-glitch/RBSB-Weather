"""Earthquakes (2.5): parsing USGS and GeoNet, merging, filters, notifications, the store
and the client. Created By Shane BlackbuRn"""

from __future__ import annotations

import json
import time
import unittest

from helpers import TempEnvTestCase
import quake_fixtures as QF

from rbsb_weather import quakes as Q
from rbsb_weather.models import Location

WELLINGTON = Location("Wellington", -41.28664, 174.77557, "New Zealand", "Wellington", "Pacific/Auckland")
AUCKLAND = Location("Auckland", -36.84853, 174.76349, "New Zealand", "Auckland", "Pacific/Auckland")
TOKYO = Location("Tokyo", 35.6895, 139.69171, "Japan", "Tokyo", "Asia/Tokyo")
LONDON = Location("London", 51.50853, -0.12574, "United Kingdom", "England", "Europe/London")


class ParseTest(unittest.TestCase):
    def test_usgs(self):
        qs = Q.parse_usgs(QF.usgs())
        self.assertEqual(len(qs), 5)                     # the quarry blast and the broken one are dropped
        jp = next(q for q in qs if q.mag == 7.3)
        self.assertEqual((jp.lat, jp.lon, jp.depth_km), (38.2, 142.9, 30.0))   # [lon, lat, depth] read right
        self.assertTrue(jp.tsunami)
        self.assertEqual(jp.alert, "yellow")
        self.assertTrue(jp.url.startswith("https://earthquake.usgs.gov/"))
        self.assertAlmostEqual(jp.age(), 1500, delta=5)

    def test_geonet(self):
        qs = Q.parse_geonet(QF.geonet())
        self.assertEqual(len(qs), 3)                     # "deleted" quality dropped
        s = qs[0]
        self.assertEqual((s.source, s.mag, s.place, s.mmi), ("GeoNet", 5.3, "20 km south-east of Seddon", 5))
        self.assertEqual(s.url, "https://www.geonet.org.nz/earthquake/2026p881001")
        self.assertAlmostEqual(s.age(), 620, delta=5)

    def test_merge_prefers_geonet_for_the_same_quake(self):
        qs = Q.merge(Q.parse_usgs(QF.usgs()), Q.parse_geonet(QF.geonet()))
        seddon = [q for q in qs if abs(q.lat + 41.7) < 0.1]
        self.assertEqual([q.source for q in seddon], ["GeoNet"])
        self.assertEqual(len(qs), 7)
        self.assertEqual(qs, sorted(qs, key=lambda q: -q.time))

    def test_garbage(self):
        for bad in (None, [], {"features": 5}, {"features": [None, {}, {"properties": {}, "geometry": {}}]}):
            self.assertEqual(Q.parse_usgs(bad), [])
            self.assertEqual(Q.parse_geonet(bad), [])
        d = QF.usgs()
        d["features"][0]["geometry"]["coordinates"] = [500, 100, 1]
        self.assertEqual(len(Q.parse_usgs(d)), 4)

    def test_round_trip(self):
        q = Q.parse_usgs(QF.usgs())[1]
        self.assertEqual(Q.Quake.from_dict(q.to_dict()), q)
        with self.assertRaises(ValueError):
            Q.Quake.from_dict({"id": "x", "lat": 99, "lon": 0, "mag": 3, "time": 1})
        self.assertEqual(Q.Quake.from_dict(dict(q.to_dict(), url="file:///etc/passwd")).url, "")


class LookTest(unittest.TestCase):
    def test_colour_radius_and_text(self):
        now = time.time()
        q = Q.Quake("a", "USGS", now - 600, 0, 0, 12.0, 5.4, "Somewhere")
        self.assertEqual(Q.colour(q, now), "#ff3b30")
        q.time = now - 3 * 3600
        self.assertEqual(Q.colour(q, now), "#ff9500")
        q.time = now - 10 * 3600
        self.assertEqual(Q.colour(q, now), "#ffd60a")
        q.time = now - 3 * 86400
        self.assertEqual(Q.colour(q, now), "#c7c9d1")
        self.assertLess(Q.radius(2.5), Q.radius(5.0))
        self.assertEqual(Q.radius(9.5), 14.0)
        self.assertEqual(Q.describe(q, now), "M5.4 · Somewhere · 12 km deep · 3 days ago (USGS)")
        self.assertEqual(Q.ago(30), "just now")
        self.assertEqual(Q.ago(3600 * 5), "5 hours ago")

    def test_within(self):
        qs = Q.merge(Q.parse_usgs(QF.usgs()), Q.parse_geonet(QF.geonet()))
        self.assertEqual(len(Q.within(qs, Q.PERIODS["day"], 2.5)), 5)
        self.assertEqual(len(Q.within(qs, Q.PERIODS["week"], 2.5)), 7)
        self.assertEqual([q.mag for q in Q.within(qs, Q.PERIODS["day"], 4.5)], [5.3, 7.3])


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.qs = Q.merge(Q.parse_usgs(QF.usgs()), Q.parse_geonet(QF.geonet()))

    def test_near_a_place_and_major_anywhere(self):
        got = Q.to_notify(self.qs, [WELLINGTON, LONDON], Q.NotifyRules(), [])
        self.assertEqual([q.mag for q, _ in got], [7.3, 5.3])          # Japan (major), Seddon (near)
        q, near = got[1]
        self.assertEqual(near[0].name, "Wellington")
        title, body = Q.notice(q, near)
        self.assertRegex(title, r"^M5\.3 earthquake \d+ km from Wellington$")
        self.assertIn("20 km south-east of Seddon", body)
        jt, jb = Q.notice(*got[0])
        self.assertIn("tsunami advice", jb)
        self.assertEqual(jt, "M7.3 earthquake: 90 km E of Ishinomaki, Japan")

    def test_rules(self):
        ids = lambda rules, places=(WELLINGTON,): [q.mag for q, _ in Q.to_notify(self.qs, list(places), rules, [])]  # noqa: E731
        self.assertEqual(ids(Q.NotifyRules(major=False)), [5.3])
        self.assertEqual(ids(Q.NotifyRules(near=False)), [7.3])
        self.assertEqual(ids(Q.NotifyRules(near_mag=5.5, major=False)), [])
        self.assertEqual(ids(Q.NotifyRules(near_km=20, major=False)), [])
        self.assertEqual(ids(Q.NotifyRules(near_mag=3.0, major=False)), [5.3])   # Taupō is too far, Alaska older
        # Tokyo is ~330 km from the Japan quake: notified as "near", with the distance
        got = Q.to_notify(self.qs, [TOKYO], Q.NotifyRules(near_km=400), [])
        self.assertIn("from Tokyo", Q.notice(*got[0])[0])

    def test_once_and_only_recent(self):
        first = Q.to_notify(self.qs, [WELLINGTON], Q.NotifyRules(), [])
        self.assertEqual(Q.to_notify(self.qs, [WELLINGTON], Q.NotifyRules(), [q.id for q, _ in first]), [])
        later = time.time() + 3 * 3600                                       # everything older than 2 hours
        self.assertEqual(Q.to_notify(self.qs, [WELLINGTON], Q.NotifyRules(), [], now=later), [])


class ClientAndStoreTest(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.usgs_url, self.geonet_url = QF.install(self.server)
        self.client = Q.QuakeClient(usgs_url=self.usgs_url, geonet_url=self.geonet_url, timeout=5)

    def test_fetch(self):
        qs, errors = self.client.fetch("day", 2.5)
        self.assertEqual(errors, {})
        self.assertEqual(len(qs), 7)
        self.assertEqual(self.server.quake_hits["usgs"], ["/usgs/2.5_day"])
        self.assertEqual(self.server.quake_hits["geonet"], [Q.GEONET_ACCEPT])     # GeoNet's versioned Accept
        self.client.fetch("week", 4.5)
        self.assertEqual(self.server.quake_hits["usgs"][-1], "/usgs/4.5_week")

    def test_one_source_failing(self):
        self.server.quake_mode["geonet"] = "http500"
        qs, errors = self.client.fetch()
        self.assertEqual(list(errors), ["GeoNet"])
        self.assertEqual(len(qs), 5)
        self.server.quake_mode["usgs"] = "garbage"
        qs, errors = self.client.fetch()
        self.assertEqual(set(errors), {"GeoNet", "USGS"})
        self.assertEqual(qs, [])

    def test_store_keeps_a_failed_sources_quakes(self):
        st = Q.QuakeStore(self.tmp)
        qs, _ = self.client.fetch()
        st.update(qs, {})
        st.notified = ["geonet:2026p881001"]
        st.save()
        st2 = Q.QuakeStore(self.tmp).load()
        self.assertEqual(len(st2.quakes), 7)
        self.assertEqual(st2.notified, ["geonet:2026p881001"])
        self.server.quake_mode["geonet"] = "http500"
        qs, errors = self.client.fetch()
        st2.update(qs, errors)
        self.assertEqual(sum(q.source == "GeoNet" for q in st2.quakes), 3)    # kept from before
        self.assertEqual(len(st2.quakes), 7)
        # quakes older than a week drop out
        st2.update(qs, {}, now=time.time() + 9 * 86400)
        self.assertEqual(st2.quakes, [])

    def test_damaged_store(self):
        (self.tmp / "quakes.json").write_text("{nope")
        self.assertEqual(Q.QuakeStore(self.tmp).load().quakes, [])
        (self.tmp / "quakes.json").write_text(json.dumps({"quakes": [5, {"id": "x"}], "notified": "x"}))
        st = Q.QuakeStore(self.tmp).load()
        self.assertEqual((st.quakes, st.notified), ([], []))


class SettingsTest(unittest.TestCase):
    def test_validated(self):
        from rbsb_weather.storage import Settings
        s = Settings.from_dict({"quakes_period": "year", "quakes_min_mag": 3, "quakes_interval": 1,
                                "quakes_near_mag": 1, "quakes_near_km": 99999, "quakes_major_mag": True,
                                "quakes_show": False})
        self.assertEqual((s.quakes_period, s.quakes_min_mag, s.quakes_interval), ("day", 2.5, 5))
        self.assertEqual((s.quakes_near_mag, s.quakes_near_km, s.quakes_major_mag), (2.5, 2000, 7.0))
        self.assertFalse(s.quakes_show)
        self.assertEqual(Settings.from_dict(s.to_dict()), s)


if __name__ == "__main__":
    unittest.main()
