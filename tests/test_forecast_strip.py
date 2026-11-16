"""Mini forecast in the weather scene (the "wedge"): adaptive 1-7 days in the
bottom-right corner, animated icons, correct daily data, and never overlapping
the scene's text or the Sun and Moon - in the top card and the desktop widget."""

from __future__ import annotations

import datetime as dt
import math
import time
import unittest

from helpers import PLACES, qapp, wait_until

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QFont, QImage, QPainter
from PyQt6.QtTest import QTest

from test_gui import GuiCase

from weatherdesk import forecast_strip as FS
from weatherdesk import scene as sc

REPORT: list[str] = []
TODAY = dt.date(2026, 11, 16)                 # a Monday


def make_days(n=7, rain=True):
    return [FS.Day(TODAY + dt.timedelta(days=i), [0, 2, 3, 45, 61, 65, 95][i % 7], 19 - i * 0.6, 10 + i * 0.3,
                   (i * 13.0) if rain else None, 20 + i * 3) for i in range(n)]


def font():
    qapp()
    return QFont()


def overlaps_circle(r: QRectF, c) -> bool:
    return FS._rect_circle(r, *c)


class TestDailyData(unittest.TestCase):
    def test_day_names(self):
        self.assertEqual(FS.day_name(TODAY, TODAY, True), "Today")
        self.assertEqual(FS.day_name(TODAY + dt.timedelta(days=1), TODAY, True), "Tomorrow")
        self.assertEqual(FS.day_name(TODAY + dt.timedelta(days=1), TODAY, False), "Tmrw")
        self.assertEqual(FS.day_name(TODAY + dt.timedelta(days=2), TODAY, True), "Wednesday")
        self.assertEqual(FS.day_name(TODAY + dt.timedelta(days=2), TODAY, False), "Wed")
        self.assertEqual(FS.day_name(TODAY + dt.timedelta(days=6), TODAY, True), "Sunday")

    def test_days_from_forecast_values_and_order(self):
        from fake_server import make_forecast
        from weatherdesk.api import parse_forecast
        from weatherdesk.models import Location
        loc = Location.from_dict(PLACES[0])
        fc = parse_forecast(make_forecast(loc.latitude, loc.longitude), loc)
        days = FS.days_from_forecast(fc)
        self.assertEqual(len(days), min(7, len(fc.daily)))
        for d, src in zip(days, fc.daily):
            self.assertEqual(d.date.isoformat(), src.date)
            self.assertEqual((d.code, d.temp_max, d.temp_min, d.rain, d.wind_max),
                             (src.weather_code, src.temp_max, src.temp_min,
                              src.precipitation_probability_max, src.wind_speed_max))
        self.assertEqual(days[0].date, FS.location_today(fc))
        self.assertEqual(len(FS.days_from_forecast(fc, limit=3)), 3)

    def test_past_days_skipped(self):
        from fake_server import make_forecast
        from weatherdesk.api import parse_forecast
        from weatherdesk.models import Location
        loc = Location.from_dict(PLACES[0])
        fc = parse_forecast(make_forecast(loc.latitude, loc.longitude), loc)
        d1 = dt.date.fromisoformat(fc.daily[1].date)
        fc.current.time = f"{d1.isoformat()}T09:00"       # the app has been running since yesterday
        days = FS.days_from_forecast(fc)
        self.assertEqual(days[0].date, d1)

    def test_temperature_text_and_units(self):
        self.assertEqual(FS.temp_text(19.4, "C"), "19°")
        self.assertEqual(FS.temp_text(-0.3, "C"), "0°")
        self.assertEqual(FS.temp_text(20.0, "F"), "68°")
        self.assertEqual(FS.temp_text(None, "C"), "–")

    def test_windy_only_for_dry_skies(self):
        self.assertTrue(FS.Day(TODAY, 1, 20, 10, 0, 45).windy)
        self.assertFalse(FS.Day(TODAY, 1, 20, 10, 0, 30).windy)
        self.assertFalse(FS.Day(TODAY, 63, 20, 10, 80, 60).windy)     # rain icon wins
        self.assertFalse(FS.Day(TODAY, 1, 20, 10, 0, None).windy)


class TestAdaptiveLayout(unittest.TestCase):
    def plan(self, w, h, days=None, rects=(), circles=()):
        return FS.plan(QRectF(0, 0, w, h), make_days() if days is None else days, TODAY, font(),
                       list(rects), list(circles))

    def test_size_classes(self):
        # the desktop widget's sizes and the top card at normal and wide windows
        text_small = [QRectF(16, 40, 80, 40), QRectF(16, 95, 90, 16), QRectF(16, 112, 80, 14)]
        small = self.plan(260, 130, rects=text_small)
        self.assertIsNotNone(small)
        self.assertIn(len(small.cells), (1, 2))
        medium = self.plan(340, 170, rects=[QRectF(16, 60, 90, 50), QRectF(16, 120, 100, 18)])
        self.assertTrue(3 <= len(medium.cells) <= 5, len(medium.cells))
        large = self.plan(800, 240, rects=[QRectF(16, 60, 140, 60), QRectF(16, 200, 230, 18)])
        self.assertEqual(len(large.cells), 7)
        REPORT.append(f"days shown: small {len(small.cells)}, medium {len(medium.cells)}, large {len(large.cells)}")

    def test_never_more_than_available_or_7(self):
        for n in range(1, 8):
            lay = self.plan(1200, 300, days=make_days(n))
            self.assertEqual(len(lay.cells), n)
        self.assertLessEqual(len(self.plan(3000, 400).cells), 7)
        self.assertIsNone(self.plan(400, 200, days=[]))

    def test_resize_sweep_no_overlap_no_clipping_readable(self):
        """Every size from tiny to huge: inside the scene, clear of text, readable,
        never shrinking text to cram days in, and more room never means fewer days."""
        text = lambda w, h: [QRectF(16, 12, min(w * 0.6, 260), 24), QRectF(16, 40, 110, h * 0.3),
                             QRectF(16, h - 34, min(w * 0.45, 220), 18)]
        checked = 0
        for h in (90, 110, 130, 150, 170, 200, 240, 300):
            prev = 0
            for w in range(160, 1300, 40):
                lay = self.plan(w, h, rects=text(w, h))
                scene = QRectF(0, 0, w, h)
                if lay is None:
                    self.assertEqual(prev, 0, (w, h))
                    continue
                n = len(lay.cells)
                self.assertTrue(1 <= n <= 7)
                self.assertGreaterEqual(n, prev, (w, h))           # bigger -> never fewer days
                prev = n
                self.assertTrue(scene.contains(lay.rect), (w, h))
                for t in text(w, h):
                    self.assertFalse(lay.rect.intersects(t), (w, h))
                self.assertGreaterEqual(lay.font_px, 9.5)
                self.assertGreaterEqual(lay.icon_px, 18)
                cap = FS.size_cap(w, h)
                self.assertLessEqual(n, cap)
                for a, b in zip(lay.cells, lay.cells[1:]):          # side by side, no overlap
                    self.assertLessEqual(a.rect.right(), b.rect.left() + 1e-6)
                for c in lay.cells:
                    self.assertTrue(c.rect.contains(c.icon))
                    fm = __import__("PyQt6.QtGui", fromlist=["QFontMetricsF"]).QFontMetricsF(lay.fonts[1])
                    self.assertLessEqual(fm.horizontalAdvance(c.name), c.rect.width() + 1e-6)
                checked += 1
        REPORT.append(f"resize sweep: {checked} sizes checked, no overlap or clipping")
        self.assertGreater(checked, 100)

    def test_bottom_right_position(self):
        lay = self.plan(500, 200, rects=[QRectF(16, 170, 220, 18)])
        self.assertGreater(lay.rect.left(), 250)
        self.assertGreater(lay.rect.top(), 200 * 0.35)
        self.assertGreater(lay.rect.right(), 500 * 0.9)

    def test_plan_can_still_avoid_circles_if_asked(self):
        """plan() keeps its (now unused by the scene) ability to keep clear of circles."""
        w, h = 500, 200
        pt = sc.arc_point(0.95, QRectF(0, 0, w, h), h * 0.11)
        circle = (pt.x(), pt.y(), h * 0.11 * FS.SUN_CLEARANCE)
        lay = self.plan(w, h, rects=[QRectF(16, 166, 220, 18)], circles=[circle])
        self.assertTrue(lay is None or not overlaps_circle(lay.rect, circle))

    def test_long_names_when_room(self):
        lay = self.plan(1400, 300)
        self.assertTrue(lay.long_names)
        self.assertEqual([c.name for c in lay.cells][:3], ["Today", "Tomorrow", "Wednesday"])
        lay = self.plan(500, 200, rects=[QRectF(16, 160, 200, 20)])
        if len(lay.cells) > 2:
            self.assertIn(lay.cells[1].name, ("Tomorrow", "Tmrw"))


class TestAnimatedIcons(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def frame(self, code, t, windy=False, size=48):
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        sc.paint_icon(p, QRectF(0, 0, size, size), code, True, t, windy=windy)
        p.end()
        return img

    def changed(self, a, b):
        return sum(1 for y in range(0, a.height(), 2) for x in range(0, a.width(), 2)
                   if a.pixel(x, y) != b.pixel(x, y))

    def test_every_kind_draws_and_moves(self):
        kinds = {"sunny": (0, False), "partly": (2, False), "cloudy": (3, False), "fog": (45, False),
                 "drizzle": (51, False), "rain": (61, False), "heavy rain": (65, False),
                 "thunder": (95, False), "snow": (73, False), "windy": (1, True)}
        out = []
        for name, (code, windy) in kinds.items():
            a, b = self.frame(code, 0.3, windy), self.frame(code, 0.9, windy)
            ink = sum(1 for y in range(48) for x in range(48) if (a.pixel(x, y) >> 24) & 0xFF)
            self.assertGreater(ink, 80, name)                        # something is drawn
            moved = self.changed(a, b)
            self.assertGreater(moved, 3, f"{name} should animate")
            out.append(f"{name} {moved}")
        REPORT.append("icon pixels changing between frames: " + ", ".join(out))

    def test_variants_differ(self):
        self.assertGreater(self.changed(self.frame(61, 0.4), self.frame(65, 0.4)), 5)     # heavy rain
        self.assertGreater(self.changed(self.frame(1, 0.4), self.frame(1, 0.4, windy=True)), 20)
        # thunder flashes only now and then
        flashes = [self.changed(self.frame(95, t), self.frame(95, t + 0.01)) for t in (0.1, 1.0)]
        self.assertTrue(any(f > 0 for f in flashes))


class TestInScenes(GuiCase):
    def scene_frame(self, s):
        img = QImage(s.width(), s.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)              # the rounded corners are left untouched: start from transparent
        p = QPainter(img)
        s.paint_scene(p, QRectF(0, 0, s.width(), s.height()))
        p.end()
        return img

    def test_top_card_and_widget_show_forecast_and_follow_location(self):
        w = self.make()
        w.resize(1100, 840)
        self.add(w, 0)
        QTest.qWait(100)
        self.scene_frame(w.scene)
        lay = w.scene.forecast_layout
        self.assertIsNotNone(lay)
        self.assertTrue(3 <= len(lay.cells) <= 5, len(lay.cells))
        fc = w.forecasts[self.place(0).key]
        self.assertEqual([c.day.temp_max for c in lay.cells], [d.temp_max for d in fc.daily[:len(lay.cells)]])
        self.assertEqual(lay.cells[0].name, "Today")
        # never over the card's text
        for r in w.scene._avoid_rects():
            self.assertFalse(lay.rect.intersects(r))
        # another location -> its own forecast
        self.add(w, 1)
        self.scene_frame(w.scene)
        fc2 = w.forecasts[self.place(1).key]
        self.assertEqual(w.scene.forecast_days[0].temp_max, fc2.daily[0].temp_max)
        # units follow
        w.set_unit("temp_unit", "F")
        self.assertEqual(w.scene.forecast_unit, "F")
        # desktop widget: same forecast, adapted to each size
        w.set_desktop_widget(True)
        dw = w.desktop_widget
        counts = {}
        for size in ("small", "medium", "large"):
            dw.set_size_name(size)
            QTest.qWait(30)
            self.scene_frame(dw.scene)
            lay = dw.scene.forecast_layout
            self.assertIsNotNone(lay, size)
            counts[size] = len(lay.cells)
            for r in dw.scene._avoid_rects():
                self.assertFalse(lay.rect.intersects(r), size)
            self.assertEqual(dw.scene.forecast_days[0].temp_max, fc2.daily[0].temp_max)
        REPORT.append(f"desktop widget days: {counts}")
        self.assertIn(counts["small"], (1, 2))
        self.assertTrue(3 <= counts["medium"] <= 5)
        self.assertGreaterEqual(counts["large"], counts["medium"])
        w.set_desktop_widget(False)

    def test_window_resize_adapts(self):
        w = self.make()
        self.add(w, 0)
        counts = []
        for width in (900, 1100, 1400, 1800):
            w.resize(width, 840)
            QTest.qWait(60)
            self.scene_frame(w.scene)
            lay = w.scene.forecast_layout
            counts.append(len(lay.cells) if lay else 0)
            if lay:
                self.assertTrue(QRectF(w.scene.rect()).contains(lay.rect))
                for r in w.scene._avoid_rects():
                    self.assertFalse(lay.rect.intersects(r))
        REPORT.append(f"top card days at window widths 900/1100/1400/1800: {counts}")
        self.assertEqual(counts, sorted(counts))
        self.assertEqual(counts[-1], 7)

    def test_sun_and_moon_unchanged_and_paint_cost(self):
        s = sc.WeatherScene()
        s.resize(490, 200)
        s.clock = lambda: 5000.0
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=0, sun_set_ts=10_000,
                                       moon_phase_angle=60, moon_limb=270, moon_up=True,
                                       moon_rise_ts=-5000, moon_set_ts=9000))
        self.scene_frame(s)
        no_fc = (s.sun_drawn, s.moon_drawn)
        s.set_forecast(make_days(), TODAY, "C")
        t0 = time.perf_counter()
        for i in range(20):
            s.t = i / 24
            self.scene_frame(s)
        ms = (time.perf_counter() - t0) * 1000 / 20
        self.assertEqual((s.sun_drawn, s.moon_drawn), no_fc)          # arcs untouched by the forecast
        REPORT.append(f"scene frame with forecast: {ms:.1f} ms")
        self.assertLess(ms, 40)

    def make_scene(self, prog_now, forecast=True):
        s = sc.WeatherScene()
        s.resize(490, 200)
        s.clock = lambda: prog_now
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=1.0, sun_rise_ts=0, sun_set_ts=10_000,
                                       moon_phase_angle=60, moon_limb=270, moon_up=True,
                                       moon_rise_ts=-2_000, moon_set_ts=10_500))
        if forecast:
            s.set_forecast(make_days(), TODAY, "C")
        return s

    def test_forecast_fixed_while_sun_and_moon_pass_behind(self):
        """1.11.1: the forecast stays put with the same days all day; the Sun and Moon
        follow their arcs unchanged and pass behind it."""
        rects, counts, behind = set(), set(), 0
        for i in range(0, 101, 2):
            now = i / 100 * 10_000
            with_fc, without = self.make_scene(now), self.make_scene(now, forecast=False)
            img_a, img_b = self.scene_frame(with_fc), self.scene_frame(without)
            lay = with_fc.forecast_layout
            self.assertIsNotNone(lay, i)
            rects.add(tuple(round(v, 6) for v in lay.rect.getRect()))
            counts.add(len(lay.cells))
            # Sun and Moon: identical positions, progress and timing with or without the forecast
            self.assertEqual(with_fc.sun_drawn, without.sun_drawn, i)
            self.assertEqual(with_fc.moon_drawn, without.moon_drawn, i)
            for body in (with_fc.sun_drawn, with_fc.moon_drawn):
                if body is not None and lay.rect.adjusted(-25, -25, 25, 25).contains(body[0], body[1]):
                    behind += 1
            # every pixel outside the forecast's shaded area is identical - nothing else changed
            r = lay.rect.adjusted(-lay.icon_px * 0.6, -lay.icon_px * 0.5, lay.icon_px * 0.6, lay.icon_px * 0.4)
            k = 0.62 * max(r.width(), r.height()) / r.width()       # the feathered shade's ellipse
            shade = QRectF(r.center().x() - r.width() * k - 2, r.center().y() - r.height() * k - 2,
                           2 * r.width() * k + 4, 2 * r.height() * k + 4).toAlignedRect()
            diff = 0
            for y in range(0, 200, 3):
                for x in range(0, 490, 3):
                    if not shade.contains(x, y) and img_a.pixel(x, y) != img_b.pixel(x, y):
                        diff += 1
            self.assertEqual(diff, 0, i)
        REPORT.append(f"fixed forecast over a full day: {len(rects)} position(s), days {sorted(counts)}; "
                      f"Sun/Moon behind it in {behind} frames; Sun/Moon identical with and without")
        self.assertEqual(len(rects), 1)
        self.assertEqual(len(counts), 1)
        self.assertGreater(behind, 0)

    def test_forecast_drawn_over_the_sun(self):
        """When the Sun is behind the forecast, the forecast's text is on top."""
        s = self.make_scene(0.93 * 10_000)
        img = self.scene_frame(s)
        lay = s.forecast_layout
        sun = s.sun_drawn
        self.assertTrue(lay.rect.adjusted(-30, -30, 30, 30).contains(sun[0], sun[1]))
        ref = self.make_scene(0.93 * 10_000, forecast=False)
        ref_img = self.scene_frame(ref)
        changed = sum(1 for c in lay.cells for y in range(int(c.icon.top()), int(c.icon.bottom()))
                      for x in range(int(c.icon.left()), int(c.icon.right()))
                      if img.pixel(x, y) != ref_img.pixel(x, y))
        self.assertGreater(changed, 50)

    def test_forecast_hidden_without_data(self):
        w = self.make()
        self.assertEqual(w.scene.forecast_days, [])
        self.server.mode = "http500"
        from weatherdesk.models import Location
        w.add_location(Location.from_dict(PLACES[0]))
        self.assertTrue(wait_until(lambda: not w._pending))
        self.scene_frame(w.scene)
        self.assertIsNone(w.scene.forecast_layout)


def tearDownModule():
    print("\n--- forecast strip results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
