"""The Sun and Moon arc in the weather scene: both rise just below the bottom-left,
climb to the top middle and set below the bottom-right, at their real times."""

from __future__ import annotations

import datetime as dt
import math
import time
import unittest

from helpers import qapp

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QImage, QPainter

from rbsb_weather import moon as M
from rbsb_weather import scene as sc

UTC = dt.timezone.utc
REPORT: list[str] = []
R = QRectF(0, 0, 420, 160)


class TestArcGeometry(unittest.TestCase):
    def test_path_shape(self):
        rad = 16.0
        start, top, end = sc.arc_point(0, R, rad), sc.arc_point(0.5, R, rad), sc.arc_point(1, R, rad)
        # starts and ends just below the horizon (disc fully hidden), left and right
        self.assertGreaterEqual(start.y() - rad, R.bottom())
        self.assertGreaterEqual(end.y() - rad, R.bottom())
        self.assertLess(start.x(), R.width() * 0.1)
        self.assertGreater(end.x(), R.width() * 0.9)
        # highest in the middle, with the disc fully inside the scene
        self.assertAlmostEqual(top.x(), R.center().x(), places=6)
        self.assertGreaterEqual(top.y() - rad, R.top())
        self.assertLess(top.y(), R.height() * 0.35)
        # symmetrical, left-to-right, up then down, smooth (no jumps)
        prev = None
        for i in range(201):
            p = i / 200
            a, b = sc.arc_point(p, R, rad), sc.arc_point(1 - p, R, rad)
            self.assertAlmostEqual(a.y(), b.y(), places=6)
            if prev is not None:
                self.assertGreater(a.x(), prev.x())
                self.assertLess(math.hypot(a.x() - prev.x(), a.y() - prev.y()), 6.0)
                if p <= 0.5:
                    self.assertLessEqual(a.y(), prev.y() + 1e-9)
                else:
                    self.assertGreaterEqual(a.y(), prev.y() - 1e-9)
            prev = a
        self.assertIsNone(sc.arc_point(-0.01, R, rad))          # below the horizon
        self.assertIsNone(sc.arc_point(1.01, R, rad))
        self.assertIsNone(sc.arc_point(None, R, rad))

    def test_rises_into_view_gradually(self):
        rad = 16.0
        ys = [sc.arc_point(p, R, rad).y() for p in (0.0, 0.01, 0.02, 0.04, 0.08)]
        visible = [R.bottom() - (y - rad) for y in ys]          # how much of the disc shows
        self.assertLessEqual(visible[0], 0.0)
        self.assertTrue(all(b > a for a, b in zip(visible, visible[1:])))


class TestProgressFromRealTimes(unittest.TestCase):
    def test_sun_progress_uses_real_sunrise_and_sunset(self):
        c = sc.Conditions(sun_rise_ts=1000.0, sun_set_ts=1000.0 + 14 * 3600)
        self.assertAlmostEqual(c.sun_progress_at(1000.0), 0.0)
        self.assertAlmostEqual(c.sun_progress_at(1000.0 + 7 * 3600), 0.5)
        self.assertAlmostEqual(c.sun_progress_at(1000.0 + 14 * 3600), 1.0)
        self.assertLess(c.sun_progress_at(900.0), 0)            # before sunrise: below horizon
        self.assertEqual(sc.Conditions(sun_progress=0.3).sun_progress_at(5.0), 0.3)   # fallback

    def test_moon_pass_matches_rise_set(self):
        """moon_pass (used for the arc) agrees with the Moon tab's rise/set times, which
        are checked against PyEphem elsewhere."""
        from zoneinfo import ZoneInfo
        worst = 0.0
        checked = 0
        for name, lat, lon, tzn in (("Auckland", -36.85, 174.76, "Pacific/Auckland"),
                                    ("London", 51.51, -0.13, "Europe/London"),
                                    ("Quito", -0.18, -78.47, "America/Guayaquil")):
            tz = ZoneInfo(tzn)
            for d in range(0, 20, 3):
                day = dt.date(2026, 11, 1) + dt.timedelta(days=d)
                rise, sett = M.rise_set(day, lat, lon, tz)
                if rise is None:
                    continue
                t = rise + dt.timedelta(minutes=45)
                up, prise, pset = M.moon_pass(t, lat, lon)
                self.assertTrue(up, (name, day))
                worst = max(worst, abs((prise - rise).total_seconds()))
                nxt = [s for s in (M.rise_set(day, lat, lon, tz)[1], M.rise_set(day + dt.timedelta(days=1), lat, lon, tz)[1])
                       if s is not None and s > rise]
                if nxt:
                    worst = max(worst, abs((pset - nxt[0]).total_seconds()))
                checked += 1
        REPORT.append(f"Moon arc rise/set vs Moon tab: worst {worst:.0f} s over {checked} passes")
        self.assertGreater(checked, 12)
        self.assertLess(worst, 60)

    def test_moon_pass_when_down_and_speed(self):
        # pick a moment just before a moonrise: the Moon is down
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Pacific/Auckland")
        rise, _ = M.rise_set(dt.date(2026, 11, 16), -36.85, 174.76, tz)
        up, a, b = M.moon_pass(rise - dt.timedelta(minutes=10), -36.85, 174.76)
        self.assertEqual((up, a, b), (False, None, None))
        t0 = time.perf_counter()
        for i in range(10):
            M.moon_pass(rise + dt.timedelta(hours=1 + i * 0.3), -36.85, 174.76)
        ms = (time.perf_counter() - t0) * 100
        REPORT.append(f"moon_pass: {ms:.1f} ms per call (cached in the scene between calls)")
        self.assertLess(ms, 100)


class TestSceneDrawsOnArc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def paint(self, cond, now=None):
        s = sc.WeatherScene()
        s.resize(int(R.width()), int(R.height()))
        if now is not None:
            s.clock = lambda: now
        s.set_conditions(cond)
        img = QImage(int(R.width()), int(R.height()), QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        s.paint_scene(p, R)
        p.end()
        return s

    def test_sun_glides_with_the_clock(self):
        rise, sset = 10_000.0, 10_000.0 + 12 * 3600
        c = sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=rise, sun_set_ts=sset)
        xs = []
        for hours in (0.5, 3, 6, 9, 11.5):
            s = self.paint(c, now=rise + hours * 3600)
            self.assertIsNotNone(s.sun_drawn)
            xs.append(s.sun_drawn[0])
            exp = sc.arc_point(hours / 12, R, min(R.width(), R.height()) * 0.11)
            self.assertAlmostEqual(s.sun_drawn[0], exp.x(), places=6)
            self.assertAlmostEqual(s.sun_drawn[1], exp.y(), places=6)
        self.assertEqual(xs, sorted(xs))                        # left to right through the day
        # one minute later it has moved a little (smooth, not jumping)
        a = self.paint(c, now=rise + 3 * 3600).sun_drawn
        b = self.paint(c, now=rise + 3 * 3600 + 60).sun_drawn
        self.assertGreater(b[0], a[0])
        self.assertLess(b[0] - a[0], 1.0)
        # after sunset it has gone below the horizon
        self.assertIsNone(self.paint(sc.Conditions(sc.CLEAR, 0, daylight=0.3, sun_rise_ts=rise,
                                                   sun_set_ts=sset), now=sset + 600).sun_drawn)

    def test_moon_uses_the_same_arc(self):
        c = sc.Conditions(sc.CLEAR, 0, daylight=0.0, moon_phase_angle=60, moon_limb=270, moon_up=True,
                          moon_rise_ts=0.0, moon_set_ts=10_000.0)
        for frac in (0.1, 0.5, 0.9):
            s = self.paint(c, now=frac * 10_000.0)
            self.assertIsNotNone(s.moon_drawn)
            exp = sc.arc_point(frac, R, min(R.width(), R.height()) * 0.09)
            self.assertAlmostEqual(s.moon_drawn[0], exp.x(), places=6)
            self.assertAlmostEqual(s.moon_drawn[1], exp.y(), places=6)
        self.assertIsNone(self.paint(c, now=10_500.0).moon_drawn)        # set: gone

    BOTH = dict(moon_phase_angle=60, moon_limb=270, moon_up=True)

    def scene_img(self, cond, now):
        s = sc.WeatherScene()
        s.resize(int(R.width()), int(R.height()))
        s.clock = lambda: now
        s.set_conditions(cond)
        img = QImage(int(R.width()), int(R.height()), QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        s.paint_scene(p, R)
        p.end()
        return s, img

    def test_moon_visible_in_daytime_when_above_horizon(self):
        """1.10.1: the Moon is shown by day whenever it's really up (not just at night)."""
        c = sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=0.0, sun_set_ts=40_000.0,
                          moon_rise_ts=10_000.0, moon_set_ts=50_000.0, **self.BOTH)
        s, img = self.scene_img(c, now=20_000.0)
        self.assertIsNotNone(s.moon_drawn)
        exp = sc.arc_point(0.25, R, min(R.width(), R.height()) * 0.09)
        self.assertAlmostEqual(s.moon_drawn[0], exp.x(), places=6)
        # pale but visible: the lit side brightens the blue sky
        _, sky = self.scene_img(sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=0.0, sun_set_ts=40_000.0,
                                              moon_up=False), now=20_000.0)
        x, y = int(s.moon_drawn[0]), int(s.moon_drawn[1])
        lit = img.pixelColor(x - 2, y).lightness()             # limb 270: lit on the right... either side:
        lit = max(lit, img.pixelColor(x + int(R.height() * 0.09 * 0.6), y).lightness())
        self.assertGreater(lit, sky.pixelColor(x, y).lightness() + 15)
        # the unlit side is not painted as a dark blob against the day sky
        dark_side = img.pixelColor(x - int(R.height() * 0.09 * 0.6), y)
        self.assertGreaterEqual(dark_side.lightness(), sky.pixelColor(x - int(R.height() * 0.09 * 0.6), y).lightness() - 3)

    def test_sun_and_moon_together_each_on_own_arc(self):
        c = sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=0.0, sun_set_ts=40_000.0,
                          moon_rise_ts=-20_000.0, moon_set_ts=30_000.0, **self.BOTH)
        now = 10_000.0
        s, _ = self.scene_img(c, now)
        self.assertIsNotNone(s.sun_drawn)
        self.assertIsNotNone(s.moon_drawn)
        sun_exp = sc.arc_point(10_000 / 40_000, R, min(R.width(), R.height()) * 0.11)
        moon_exp = sc.arc_point(30_000 / 50_000, R, min(R.width(), R.height()) * 0.09)
        self.assertAlmostEqual(s.sun_drawn[0], sun_exp.x(), places=6)
        self.assertAlmostEqual(s.sun_drawn[1], sun_exp.y(), places=6)
        self.assertAlmostEqual(s.moon_drawn[0], moon_exp.x(), places=6)
        self.assertAlmostEqual(s.moon_drawn[1], moon_exp.y(), places=6)
        # they move independently at their own speeds
        s2, _ = self.scene_img(c, now + 3600)
        self.assertAlmostEqual(s2.sun_drawn[2] - s.sun_drawn[2], 3600 / 40_000, places=9)
        self.assertAlmostEqual(s2.moon_drawn[2] - s.moon_drawn[2], 3600 / 50_000, places=9)

    def test_moon_disappears_below_horizon_day_and_night(self):
        for daylight in (1.0, 0.5, 0.0):
            c = sc.Conditions(sc.CLEAR, 0, daylight=daylight, sun_rise_ts=0.0, sun_set_ts=40_000.0,
                              moon_rise_ts=0.0, moon_set_ts=10_000.0, **self.BOTH)
            self.assertIsNotNone(self.scene_img(c, now=9_000.0)[0].moon_drawn, daylight)
            self.assertIsNone(self.scene_img(c, now=10_001.0)[0].moon_drawn, daylight)    # just set
            self.assertIsNone(self.scene_img(c, now=-1.0)[0].moon_drawn, daylight)        # not risen
            down = sc.Conditions(sc.CLEAR, 0, daylight=daylight, moon_phase_angle=60, moon_up=False)
            self.assertIsNone(self.scene_img(down, now=5_000.0)[0].moon_drawn, daylight)

    def test_night_moon_unchanged(self):
        c = sc.Conditions(sc.CLEAR, 0, daylight=0.0, moon_rise_ts=0.0, moon_set_ts=10_000.0, **self.BOTH)
        s, img = self.scene_img(c, now=5_000.0)
        self.assertIsNotNone(s.moon_drawn)
        self.assertIsNone(s.sun_drawn)
        # at night the dark side shows (earthshine disc), as before 1.10.1
        x, y = int(s.moon_drawn[0]), int(s.moon_drawn[1])
        self.assertGreater(img.pixelColor(x, y).alpha(), 0)

    def test_visibility_follows_astronomy_not_clock(self):
        """conditions_from_forecast takes 'up' from the Moon's real altitude: up by day
        stays up; down at night stays down."""
        from unittest import mock
        from test_scene import _fc
        from rbsb_weather import moon as M_
        for when, alt, expect_up in (("2026-11-15T12:00", 30.0, True), ("2026-11-15T23:30", -20.0, False)):
            with mock.patch.object(M_, "sky_geometry", return_value=(0.0, alt, 90.0, 0.13)):
                c = sc.conditions_from_forecast(_fc(now=when), now=time.time())
            self.assertEqual(c.moon_up, expect_up, when)
            s, _ = self.scene_img(c, now=time.time())
            self.assertEqual(s.moon_drawn is not None, expect_up, when)

    def test_forecast_conditions_give_real_times(self):
        from test_scene import _fc
        fc = _fc(now="2026-11-15T13:05")                      # sunrise 06:00, sunset 20:10
        now = time.time()
        c = sc.conditions_from_forecast(fc, now=now)
        self.assertAlmostEqual(c.sun_set_ts - c.sun_rise_ts, (20 * 60 + 10 - 6 * 60) * 60, delta=1)
        self.assertAlmostEqual(c.sun_progress_at(now), 0.5, delta=0.01)
        if c.moon_up:
            self.assertIsNotNone(c.moon_rise_ts)
            self.assertTrue(0 <= c.moon_progress_at(dt.datetime.now(UTC).timestamp()) <= 1)


def tearDownModule():
    print("\n--- arc results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
