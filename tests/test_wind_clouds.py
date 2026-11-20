"""Clouds drift with the forecast's wind (1.17.0).

Speed follows the wind speed (in scene widths, so the main window and the desktop widget
match); direction follows the way the wind blows TO, converted from the meteorological
direction it comes FROM; a refresh with new wind eases in without jumps; calm air still
drifts; strong wind is capped. Measured on the real WeatherScene by advancing its clock.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
import time
import unittest
from unittest import mock

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

import fake_server
from fake_server import make_forecast, make_metno
from weatherdesk import scene as sc
from weatherdesk.api import parse_forecast
from weatherdesk.metno import parse_metno
from weatherdesk.models import Location

REPORT: list[str] = []
FRAME = 1 / sc.FPS
MAIN = (640, 240)          # the main window's scene, typical size
WIDGET = (300, 170)        # the desktop widget's scene, medium size


def scene(size=MAIN, kind=sc.PARTLY, kmh=20.0, frm=270.0):
    """A scene with clouds (partly cloudy), sized and given a wind from `frm` degrees."""
    s = sc.WeatherScene(seed=3)
    s.resize(*size)
    s.set_conditions(cond(kind, kmh, frm))
    return s


def cond(kind=sc.PARTLY, kmh=20.0, frm=270.0):
    c = sc.Conditions(kind, 0.6, wind_kmh=kmh)
    c.wind_east = sc.wind_drift(frm)
    c.wind_sign = 1.0 if c.wind_east >= 0 else -1.0
    return c


def front(s):
    return [cl for cl in s._clouds if cl["layer"] == 2]


def run(s, seconds):
    """Advance the scene's clock in real frame steps; returns each front cloud's total
    displacement in px, unwrapped (a cloud leaving one side re-enters off-screen on the
    other: that teleport is not movement and is taken out)."""
    clouds = front(s)
    last = [cl["x"] for cl in clouds]
    total = [0.0] * len(clouds)
    w = s.width()
    for _ in range(int(round(seconds / FRAME))):
        s.advance(FRAME)
        for i, cl in enumerate(clouds):
            d = cl["x"] - last[i]
            if abs(d) > w / 2:                                    # wrapped
                d -= math.copysign(w + cl["w"] + 20, d)
            total[i] += d
            last[i] = cl["x"]
    return total


class TestWindModel(unittest.TestCase):
    """The two conversions: wind speed -> cloud speed, wind FROM -> drift TO."""

    def test_from_is_converted_to_where_the_wind_blows(self):
        # meteorological: degrees the wind comes FROM. Clouds go the opposite way.
        cases = {270: +1.0,    # westerly: from the west, blows east -> right
                 90: -1.0,     # easterly: blows west -> left
                 315: +0.795,  # north-westerly: blows south-east -> mostly right
                 225: +0.795,  # south-westerly: blows north-east -> mostly right
                 45: -0.795,   # north-easterly: blows south-west -> mostly left
                 135: -0.795}  # south-easterly: blows north-west -> mostly left
        for frm, want in cases.items():
            self.assertAlmostEqual(sc.wind_drift(frm), want, places=3, msg=frm)
        # the same direction written differently gives the same drift
        self.assertAlmostEqual(sc.wind_drift(-90), sc.wind_drift(270))
        self.assertAlmostEqual(sc.wind_drift(630), sc.wind_drift(270))

    def test_north_and_south_winds_still_drift(self):
        # a side view can't show north/south, but the sky must not freeze
        for frm in (0.0, 180.0, 360.0):
            self.assertAlmostEqual(sc.wind_drift(frm), sc.MIN_EAST_WEST, msg=frm)
        # a nearly north/south wind leans to the side it blows towards:
        # from 350 (just west of north) it blows to 170 (just east of south) -> right;
        # from 10 (just east of north) it blows to 190 (just west of south) -> left
        self.assertGreater(sc.wind_drift(350.0), sc.MIN_EAST_WEST)
        self.assertLess(sc.wind_drift(10.0), -sc.MIN_EAST_WEST)

    def test_drift_side_matches_the_true_bearing_everywhere(self):
        """Every whole degree: the drift's side is the east/west side of the bearing the
        wind blows TO (from + 180), and its size grows with how east/west that is."""
        for frm in range(360):
            to = (frm + 180) % 360
            east_of_to = math.sin(math.radians(to))
            d = sc.wind_drift(frm)
            if abs(east_of_to) > 1e-9:
                self.assertEqual(d > 0, east_of_to > 0, frm)
            self.assertGreaterEqual(abs(d), sc.MIN_EAST_WEST - 1e-12)
            self.assertLessEqual(abs(d), 1.0 + 1e-12)
            self.assertAlmostEqual(abs(d), sc.MIN_EAST_WEST + (1 - sc.MIN_EAST_WEST) * abs(east_of_to), 9)

    def test_unknown_or_bad_direction(self):
        self.assertEqual(sc.wind_drift(None), 1.0)            # as before 1.17
        self.assertEqual(sc.wind_drift(float("nan")), 1.0)

    def test_speed_rises_with_wind_and_is_bounded(self):
        prev = 0.0
        k = 0.0
        while k <= 200:
            v = sc.cloud_speed(k)
            self.assertGreater(v, prev, k) if k <= 100 else self.assertAlmostEqual(v, prev, 12)
            prev = v
            k += 0.5
        # calm still drifts; strong is capped
        self.assertAlmostEqual(1 / sc.cloud_speed(0), 150.0)
        self.assertAlmostEqual(1 / sc.cloud_speed(100), 19.0)
        self.assertAlmostEqual(1 / sc.cloud_speed(300), 19.0)
        for kmh, secs in sc.CLOUD_CROSSING_S:
            self.assertAlmostEqual(1 / sc.cloud_speed(kmh), secs, 6, kmh)
        # small real differences show: 5 km/h more is clearly faster at light winds
        self.assertGreater(sc.cloud_speed(10) / sc.cloud_speed(5), 1.3)

    def test_missing_or_bad_speed_is_calm(self):
        # not a usable number = no wind known = calm drift (the forecast cleaning already
        # drops non-finite values before they reach the scene; this is a second guard)
        for bad in (None, -4.0, float("nan"), float("-inf"), float("inf")):
            self.assertEqual(sc.cloud_speed(bad), sc.cloud_speed(0), bad)

    def test_conditions_from_real_forecast_data(self):
        """The scene uses the forecast's own wind: fake Open-Meteo 18.7 km/h from 225."""
        d = make_forecast(-36.8, 174.7)
        fc = parse_forecast(d, Location("T", -36.8, 174.7))
        self.assertEqual((fc.current.wind_speed, fc.current.wind_direction), (18.7, 225.0))
        c = sc.conditions_from_forecast(fc)
        self.assertEqual(c.wind_kmh, 18.7)
        self.assertAlmostEqual(c.wind_east, sc.wind_drift(225.0))
        self.assertGreater(c.wind_east, 0)                     # from SW blows NE -> right
        self.assertEqual(c.wind_sign, 1.0)

    def test_met_norway_from_direction_and_ms_to_kmh(self):
        """MET Norway reports wind_from_direction and m/s; WeatherDesk converts to km/h."""
        d = make_metno(-36.8, 174.7)
        d["properties"]["timeseries"][0]["data"]["instant"]["details"].update(
            wind_from_direction=90.0, wind_speed=10.0)
        fc = parse_metno(d, Location("T", -36.8, 174.7))
        c = sc.conditions_from_forecast(fc)
        self.assertAlmostEqual(c.wind_kmh, 36.0)
        self.assertEqual(c.wind_east, -1.0)                    # easterly blows west -> left

    def test_no_direction_in_forecast(self):
        d = make_forecast(-36.8, 174.7)
        d["current"]["wind_direction_10m"] = None
        d["current"]["wind_speed_10m"] = None
        c = sc.conditions_from_forecast(parse_forecast(d, Location("T", -36.8, 174.7)))
        self.assertEqual((c.wind_kmh, c.wind_east, c.wind_sign), (0.0, 1.0, 1.0))

    def test_older_conditions_with_only_wind_sign(self):
        self.assertEqual(sc.Conditions(wind_sign=-1.0).wind_east, -1.0)
        self.assertEqual(sc.Conditions().wind_east, 1.0)


class TestCloudMotion(unittest.TestCase):
    """Measured on the real scene: how far the clouds actually move."""

    @classmethod
    def setUpClass(cls):
        qapp()

    def speed_of(self, s, seconds=6.0):
        """Measured front-layer speed in scene widths per second (signed)."""
        moved = run(s, seconds)
        return sum(moved) / len(moved) / s.width() / seconds

    def test_measured_speed_and_direction_match_the_wind(self):
        rows = []
        for kmh, frm in ((0, 270), (10, 270), (20, 90), (40, 315), (80, 270), (150, 90)):
            s = scene(MAIN, kmh=kmh, frm=frm)
            got = self.speed_of(s)
            want = sc.wind_drift(frm) * sc.cloud_speed(kmh)
            self.assertAlmostEqual(got, want, delta=abs(want) * 0.01, msg=(kmh, frm))
            rows.append(f"{kmh} km/h from {frm}: {'right' if got > 0 else 'left'}, "
                        f"crosses in {1 / abs(got):.0f} s")
        REPORT.append("measured front clouds: " + "; ".join(rows))

    def test_layers_keep_their_depth(self):
        s = scene(MAIN, kmh=30)
        layers = {}
        for cl in s._clouds:
            layers.setdefault(cl["layer"], cl)
        before = {k: v["x"] for k, v in layers.items()}
        for _ in range(24):
            s.advance(FRAME)
        moved = {k: layers[k]["x"] - before[k] for k in layers}
        self.assertLess(moved[0], moved[1])
        self.assertLess(moved[1], moved[2])                    # far clouds slower than near

    def test_main_window_and_widget_sizes_look_the_same(self):
        for kmh, frm in ((5, 270), (35, 90), (90, 225)):
            a = self.speed_of(scene(MAIN, kmh=kmh, frm=frm))
            b = self.speed_of(scene(WIDGET, kmh=kmh, frm=frm))
            small = self.speed_of(scene((220, 130), kmh=kmh, frm=frm))
            self.assertAlmostEqual(a, b, delta=abs(a) * 0.01)
            self.assertAlmostEqual(a, small, delta=abs(a) * 0.01)

    def test_calm_air_still_drifts(self):
        for frm in (270, 0, 180, None):
            s = sc.WeatherScene(seed=3)
            s.resize(*MAIN)
            c = sc.Conditions(sc.PARTLY, 0.6, wind_kmh=0.0)
            c.wind_east = sc.wind_drift(frm)
            s.set_conditions(c)
            moved = run(s, 5.0)
            self.assertTrue(all(abs(m) > 2.0 for m in moved), (frm, moved))   # visibly moving
        REPORT.append(f"calm: front clouds still cross in {1 / sc.cloud_speed(0):.0f} s "
                      f"({MAIN[0] / 150:.1f} px/s in the main window), slower for north/south winds")

    def test_strong_wind_is_capped(self):
        s = scene(MAIN, kmh=250)
        v = abs(self.speed_of(s))
        self.assertAlmostEqual(1 / v, 19.0, delta=0.3)
        px_per_frame = v * MAIN[0] * FRAME
        self.assertLess(px_per_frame, 1.5)                     # small steps: smooth, not a blur
        REPORT.append(f"strong wind (>= 100 km/h): crosses in 19 s, {px_per_frame:.2f} px per frame")


class TestRefreshEasing(unittest.TestCase):
    """A refresh with new wind: no jump, a gradual change, then the new wind exactly."""

    @classmethod
    def setUpClass(cls):
        qapp()

    def test_change_of_wind_eases_without_jumps(self):
        s = scene(MAIN, kmh=10, frm=270)          # gentle, to the right
        run(s, 2.0)
        clouds_before = [id(cl) for cl in s._clouds]
        xs_before = [cl["x"] for cl in s._clouds]
        s.set_conditions(cond(sc.PARTLY, 60, 90))  # refresh: strong, to the left
        # nothing moved or was rebuilt by the refresh itself
        self.assertEqual([id(cl) for cl in s._clouds], clouds_before)
        self.assertEqual([cl["x"] for cl in s._clouds], xs_before)
        target = sc.wind_drift(90) * sc.cloud_speed(60)
        start = sc.wind_drift(270) * sc.cloud_speed(10)
        vel, steps, east, speed = [], [], [], []
        cl = front(s)[0]
        last = cl["x"]
        for _ in range(int(15 / FRAME)):
            s.advance(FRAME)
            d = cl["x"] - last
            if abs(d) < s.width() / 2:                           # not a wrap
                steps.append(d)
            last = cl["x"]
            vel.append(s.drift_east * s.drift_speed)
            east.append(s.drift_east)
            speed.append(s.drift_speed)
        # the first frame is still almost the old wind
        self.assertAlmostEqual(vel[0], start, delta=abs(start - target) * 0.02)
        # no frame changes the speed by more than a small step
        biggest = max(abs(b - a) for a, b in zip(vel, vel[1:]))
        self.assertLess(biggest, abs(target - start) * 0.02)
        # no visible jump in any cloud's position
        self.assertLess(max(abs(d) for d in steps), 2.0)
        # it turns around smoothly: slows, crosses zero once, speeds up the other way
        crossings = sum(1 for a, b in zip(vel, vel[1:]) if (a > 0) != (b > 0))
        self.assertEqual(crossings, 1)
        # every frame follows the designed easing exactly: what's left of the change after
        # t seconds is exp(-t / WIND_EASE_S), for direction and speed separately
        e0, e1 = sc.wind_drift(270), sc.wind_drift(90)
        s0, s1 = sc.cloud_speed(10), sc.cloud_speed(60)
        for i in range(len(east)):
            left = math.exp(-(i + 1) * FRAME / sc.WIND_EASE_S)
            self.assertAlmostEqual(east[i], e1 + (e0 - e1) * left, delta=1e-9)
            self.assertAlmostEqual(speed[i], s1 + (s0 - s1) * left, delta=1e-12)
        # so: 95% of the way after 3 time constants (9 s); the reversal crosses zero after
        # WIND_EASE_S * ln 2 (about 2 s); after 15 s the velocity is within 2%
        at = int(3 * sc.WIND_EASE_S / FRAME)
        self.assertLess(abs(east[at] - e1), abs(e1 - e0) * 0.051)
        self.assertLess(abs(speed[at] - s1), abs(s1 - s0) * 0.051)
        zero = next(i for i, v in enumerate(vel) if v < 0) * FRAME
        self.assertAlmostEqual(zero, sc.WIND_EASE_S * math.log(2), delta=FRAME * 1.5)
        self.assertAlmostEqual(vel[-1], target, delta=abs(target) * 0.02)
        REPORT.append(f"refresh 10 km/h W -> 60 km/h E: no rebuild, biggest per-frame speed change "
                      f"{biggest / abs(target - start) * 100:.2f}% of the total, largest cloud step "
                      f"{max(abs(d) for d in steps):.2f} px, turned round after {zero:.1f} s, "
                      f"direction and speed 95% there after {3 * sc.WIND_EASE_S:.0f} s; every frame "
                      f"matched the easing formula")

    def test_small_change_is_gradual_too(self):
        s = scene(MAIN, kmh=20, frm=270)
        s.set_conditions(cond(sc.PARTLY, 26, 250))
        first = s.drift_speed
        s.advance(FRAME)
        self.assertGreater(s.drift_speed, first)
        self.assertLess(s.drift_speed, sc.cloud_speed(26))

    def test_first_real_forecast_replaces_the_placeholder_at_once(self):
        """Regression (found while testing 1.17): the main window's sky animates with
        placeholder conditions (10 km/h) before any forecast loads, and the first real
        forecast used to ease in from that invented wind over ~10 s."""
        s = sc.WeatherScene(seed=3)
        s.resize(*MAIN)
        s.set_conditions(sc.Conditions(sc.PARTLY, 0.5))           # placeholder, no forecast
        for _ in range(48):
            s.advance(FRAME)
        real = cond(sc.PARTLY, 45, 90)
        real.from_forecast = True
        s.set_conditions(real)
        self.assertEqual((s.drift_east, s.drift_speed), (-1.0, sc.cloud_speed(45)))
        later = cond(sc.PARTLY, 10, 270)                          # the next refresh: eases
        later.from_forecast = True
        s.set_conditions(later)
        s.advance(FRAME)
        self.assertLess(s.drift_east, 0)
        self.assertGreater(s.drift_speed, sc.cloud_speed(10))

    def test_first_weather_is_shown_as_it_is(self):
        s = scene(MAIN, kmh=55, frm=90)
        self.assertEqual(s.drift_speed, sc.cloud_speed(55))
        self.assertEqual(s.drift_east, -1.0)

    def test_change_of_weather_type_still_rebuilds_clouds(self):
        # unchanged behaviour: new cloud amount -> new cloud layout; the wind stays eased
        s = scene(MAIN, kmh=10, frm=270)
        s.set_conditions(cond(sc.OVERCAST, 40, 270))
        self.assertGreater(len(s._clouds), 0)
        self.assertAlmostEqual(s.drift_speed, sc.cloud_speed(10))

    def test_rain_snow_and_fog_follow_the_eased_wind(self):
        for kind in (sc.RAIN, sc.SNOW, sc.FOG):
            s = scene(MAIN, kind=kind, kmh=30, frm=270)
            self.assertEqual(s.precip_direction(), 1.0)         # steady: exactly as before
            s.set_conditions(cond(kind, 30, 90))
            dirs = []
            for _ in range(int(12 / FRAME)):
                s.advance(FRAME)
                dirs.append(s.precip_direction())
            self.assertLess(max(abs(b - a) for a, b in zip(dirs, dirs[1:])), 0.1, kind)
            self.assertEqual(dirs[-1], -1.0, kind)


class TestNothingElseChanged(unittest.TestCase):
    """Wind only moves clouds and weather; the Sun, Moon and forecast don't care."""

    @classmethod
    def setUpClass(cls):
        qapp()

    def frame(self, kmh, frm):
        from weatherdesk.forecast_strip import Day
        s = sc.WeatherScene(seed=4)
        s.resize(*MAIN)
        c = cond(sc.PARTLY, kmh, frm)
        now = time.time()
        c.sun_rise_ts, c.sun_set_ts = now - 4 * 3600, now + 6 * 3600
        c.moon_rise_ts, c.moon_set_ts = now - 2 * 3600, now + 8 * 3600
        c.daylight = 1.0
        s.clock = lambda: now
        s.set_conditions(c)
        import datetime as dt
        today = dt.date(2026, 11, 20)
        s.set_forecast([Day(today + dt.timedelta(days=i), 2, 20.0, 12.0, 30) for i in range(5)],
                       today, "C")
        for _ in range(48):
            s.advance(FRAME)
        img = QImage(*MAIN, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        s.render(p)
        p.end()
        return s

    def test_sun_moon_and_forecast_unaffected_by_wind(self):
        a, b = self.frame(0, 270), self.frame(90, 90)
        self.assertEqual(a.sun_drawn, b.sun_drawn)
        self.assertEqual(a.moon_drawn, b.moon_drawn)
        self.assertIsNotNone(a.forecast_layout)
        self.assertEqual([c.rect for c in a.forecast_layout.cells], [c.rect for c in b.forecast_layout.cells])

    def test_cost_per_frame_unchanged(self):
        s = scene(MAIN, kind=sc.RAIN, kmh=40)
        t0 = time.perf_counter()
        for _ in range(2400):
            s.advance(FRAME)
        per = (time.perf_counter() - t0) / 2400 * 1000
        ease = time.perf_counter()
        for _ in range(2400):
            s._ease_wind(FRAME)
        ease = (time.perf_counter() - ease) / 2400 * 1000
        REPORT.append(f"cost per frame (rain scene, all particles): {per:.3f} ms; of which wind easing {ease:.4f} ms")
        self.assertLess(ease, 0.05)


class TestWindowAndWidget(TempEnvTestCase):
    """The real app: forecast wind reaches both scenes, and a refresh eases in."""

    def setUp(self):
        super().setUp()
        qapp()
        self.wins = []

    def tearDown(self):
        for w in self.wins:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def test_main_window_and_desktop_widget_share_the_wind(self):
        from weatherdesk.main_window import MainWindow
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        self.wins.append(w)
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        w.set_desktop_widget(True)
        dw = w.desktop_widget
        QTest.qWait(100)
        for s in (w.scene, dw.scene):
            self.assertEqual(s.cond.wind_kmh, 18.7)                       # the forecast's value
            self.assertAlmostEqual(s.cond.wind_east, sc.wind_drift(225))
        # both scenes animate the same relative drift
        for s in (w.scene, dw.scene):
            s.advance(FRAME)
        self.assertAlmostEqual(w.scene.drift_speed, dw.scene.drift_speed)
        self.assertAlmostEqual(w.scene.drift_east, dw.scene.drift_east)

        # a refresh brings a new wind: both scenes ease towards it together
        real = fake_server.make_forecast

        def windier(lat, lon, days=7):
            d = real(lat, lon, days)
            d["current"].update(wind_speed_10m=55.0, wind_direction_10m=80.0)
            return d
        with mock.patch.object(fake_server, "make_forecast", windier):
            w.refresh_selected(force=True)
            self.assertTrue(wait_until(lambda: not w._pending))
        for s in (w.scene, dw.scene):
            self.assertEqual(s.cond.wind_kmh, 55.0)
            self.assertLess(s.cond.wind_east, 0)                          # from E-ish: left
            self.assertGreater(s.drift_east, 0)                           # still turning
        secs = 15.0
        for _ in range(int(secs / FRAME)):
            for s in (w.scene, dw.scene):
                s.advance(FRAME)
        left = math.exp(-secs / sc.WIND_EASE_S) * 1.05             # what may still be easing in
        e0, e1 = sc.wind_drift(225), sc.wind_drift(80.0)
        s0, s1 = sc.cloud_speed(18.7), sc.cloud_speed(55.0)
        for s in (w.scene, dw.scene):
            self.assertAlmostEqual(s.drift_east, e1, delta=abs(e1 - e0) * left)
            self.assertAlmostEqual(s.drift_speed, s1, delta=abs(s1 - s0) * left)
        self.assertAlmostEqual(w.scene.drift_east, dw.scene.drift_east, delta=1e-9)


def tearDownModule():
    print("\n--- wind clouds results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
