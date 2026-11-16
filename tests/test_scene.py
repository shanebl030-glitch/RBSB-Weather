"""Animated scene, icons, animation clock and desktop widget tests."""

from __future__ import annotations

import datetime as dt
import gc
import statistics
import time
import unittest

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from fake_server import make_forecast
from weatherdesk import scene as sc
from weatherdesk.api import parse_forecast
from weatherdesk.models import Location
from weatherdesk.storage import Settings, SettingsStore
from weatherdesk.weather_codes import all_codes

REPORT: list[str] = []


def _fc(code=2, now="2026-11-15T10:15", rise="2026-11-15T06:00", sset="2026-11-15T20:10",
        lat=-36.8, wind_dir=225, is_day=1, fetched_at=0.0):
    d = make_forecast(lat, 174.7)
    d["current"].update(weather_code=code, time=now, wind_direction_10m=wind_dir, is_day=is_day)
    d["daily"]["sunrise"][0] = rise
    d["daily"]["sunset"][0] = sset
    fc = parse_forecast(d, Location("T", lat, 174.7))
    fc.fetched_at = fetched_at
    return fc


def _render(scene: sc.WeatherScene, w=640, h=240) -> tuple[QImage, float]:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    t0 = time.perf_counter()
    scene.paint_scene(p, QRectF(0, 0, w, h))
    ms = (time.perf_counter() - t0) * 1000
    p.end()
    return img, ms


def _distinct_colours(img: QImage, step=23) -> int:
    seen = set()
    for x in range(0, img.width(), step):
        for y in range(0, img.height(), step):
            seen.add(img.pixel(x, y))
    return len(seen)


class TestClassifyAndMoon(unittest.TestCase):
    def test_every_known_code_classified(self):
        for code in all_codes():
            kind, inten = sc.classify(code)
            self.assertIn(kind, (sc.CLEAR, sc.PARTLY, sc.OVERCAST, sc.FOG, sc.DRIZZLE,
                                 sc.RAIN, sc.SNOW, sc.THUNDER), code)
            self.assertTrue(0 <= inten <= 1)
        self.assertEqual(sc.classify(None)[0], sc.PARTLY)
        self.assertEqual(sc.classify(42)[0], sc.PARTLY)
        self.assertEqual(sc.classify(65), (sc.RAIN, 1.0))
        self.assertEqual(sc.classify(95)[0], sc.THUNDER)

    def test_moon_phase_known_dates(self):
        utc = dt.timezone.utc
        self.assertAlmostEqual(sc.moon_phase(dt.datetime(2000, 1, 6, 18, 14, tzinfo=utc)), 0.0, delta=0.01)
        # full moon 25 Jan 2024 17:54 UTC; new moon 11 Jan 2024 11:57 UTC
        self.assertAlmostEqual(sc.moon_phase(dt.datetime(2024, 1, 25, 17, 54, tzinfo=utc)), 0.5, delta=0.03)
        new = sc.moon_phase(dt.datetime(2024, 1, 11, 11, 57, tzinfo=utc))
        self.assertTrue(new < 0.03 or new > 0.97, new)
        self.assertTrue(0 <= sc.moon_phase(dt.datetime(2026, 11, 15)) < 1)   # naive accepted


class TestConditions(unittest.TestCase):
    def test_day_night_twilight(self):
        self.assertEqual(sc.conditions_from_forecast(_fc(now="2026-11-15T13:00")).daylight, 1.0)
        night = sc.conditions_from_forecast(_fc(now="2026-11-15T23:30"))
        self.assertEqual(night.daylight, 0.0)
        self.assertEqual(night.twilight, 0.0)
        dusk = sc.conditions_from_forecast(_fc(now="2026-11-15T20:10"))
        self.assertAlmostEqual(dusk.twilight, 1.0, delta=0.01)
        self.assertAlmostEqual(dusk.daylight, 0.5, delta=0.01)
        dawn = sc.conditions_from_forecast(_fc(now="2026-11-15T05:50"))
        self.assertGreater(dawn.twilight, 0.6)
        self.assertLess(dawn.daylight, 0.5)

    def test_sun_progress(self):
        self.assertAlmostEqual(sc.conditions_from_forecast(_fc(now="2026-11-15T06:00")).sun_progress, 0.0)
        mid = sc.conditions_from_forecast(_fc(now="2026-11-15T13:05")).sun_progress
        self.assertAlmostEqual(mid, 0.5, delta=0.01)

    def test_clock_advances_since_download(self):
        fc = _fc(now="2026-11-15T19:00", fetched_at=1000.0)
        later = sc.conditions_from_forecast(fc, now=1000.0 + 3 * 3600)   # 22:00 -> night
        self.assertEqual(later.daylight, 0.0)
        self.assertEqual(sc.conditions_from_forecast(fc, now=1000.0).daylight, 1.0)

    def test_fallback_without_sun_times_uses_is_day(self):
        fc = _fc(is_day=0)
        fc.daily = []
        self.assertEqual(sc.conditions_from_forecast(fc).daylight, 0.0)
        fc = _fc(is_day=1, now="garbage")
        self.assertEqual(sc.conditions_from_forecast(fc).daylight, 1.0)

    def test_wind_direction_and_hemisphere(self):
        self.assertEqual(sc.conditions_from_forecast(_fc(wind_dir=270)).wind_sign, 1.0)   # from W -> right
        self.assertEqual(sc.conditions_from_forecast(_fc(wind_dir=90)).wind_sign, -1.0)   # from E -> left
        self.assertTrue(sc.conditions_from_forecast(_fc(lat=-36.8)).southern)
        self.assertFalse(sc.conditions_from_forecast(_fc(lat=51.5)).southern)

    def test_cloud_amount_ordering(self):
        amt = lambda code: sc.Conditions(*sc.classify(code)).cloud_amount
        self.assertEqual(amt(0), 0.0)
        self.assertLess(amt(1), amt(2))
        self.assertLess(amt(2), amt(3))
        self.assertGreater(sc.Conditions(*sc.classify(99)).darkness, sc.Conditions(*sc.classify(61)).darkness)


class TestSceneRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_all_codes_all_times_render(self):
        times = {"day": dict(daylight=1.0), "dusk": dict(daylight=0.5, twilight=1.0, sun_progress=0.97),
                 "night": dict(daylight=0.0)}
        worst = 0.0
        for code in all_codes() + [None, 42]:
            for name, kw in times.items():
                s = sc.WeatherScene(seed=5)
                s.resize(640, 240)
                s.set_conditions(sc.Conditions(*sc.classify(code), wind_kmh=30, **kw))
                for _ in range(20):
                    s.advance(1 / 30)
                img, ms = _render(s)
                worst = max(worst, ms)
                self.assertGreater(_distinct_colours(img), 3, f"blank scene for {code} {name}")
                s.deleteLater()
        REPORT.append(f"all {len(all_codes()) + 2} codes x 3 times rendered; worst single frame "
                      f"{worst:.1f} ms (includes one-off cloud sprite generation)")

    def test_day_and_night_skies_differ(self):
        s = sc.WeatherScene()
        s.resize(300, 150)
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=1))
        day_top, _ = s.sky_colors()
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=0))
        night_top, _ = s.sky_colors()
        self.assertGreater(day_top.lightness(), night_top.lightness() + 60)
        s.set_conditions(sc.Conditions(sc.THUNDER, 1, daylight=1))
        storm_top, _ = s.sky_colors()
        self.assertLess(storm_top.saturation(), day_top.saturation())

    def test_steady_state_performance(self):
        results = []
        for code in (0, 3, 45, 55, 65, 75, 99):
            s = sc.WeatherScene(seed=3)
            s.resize(640, 240)
            s.set_conditions(sc.Conditions(*sc.classify(code), daylight=0.0 if code == 65 else 1.0,
                                           wind_kmh=30))
            _render(s)                                  # warm sprite cache
            times = []
            for _ in range(40):
                s.advance(1 / 30)
                times.append(_render(s)[1])
            med = statistics.median(times)
            results.append((code, med))
            # 30 fps needs < 33 ms; demand far less so it stays light on CPU.
            self.assertLess(med, 15.0, f"code {code} median {med:.1f} ms")
        REPORT.append("paint 640x240 median ms: " + ", ".join(f"{c}={m:.1f}" for c, m in results))

    def test_degenerate_sizes(self):
        for w, h in ((1, 1), (5, 3), (2000, 900)):
            s = sc.WeatherScene()
            s.resize(w, h)
            s.set_conditions(sc.Conditions(sc.THUNDER, 1.0))
            for _ in range(10):
                s.advance(0.05)
            _render(s, max(1, w), max(1, h))

    def test_particles_bounded_over_long_run(self):
        for code in (65, 75, 99, 55, 45):
            s = sc.WeatherScene(seed=9)
            s.resize(500, 200)
            s.set_conditions(sc.Conditions(*sc.classify(code), wind_kmh=60))
            counts = (len(s._drops), len(s._flakes), len(s._clouds), len(s._fog))
            for _ in range(6000):               # 10 simulated minutes
                s.advance(0.1)
            self.assertEqual(counts, (len(s._drops), len(s._flakes), len(s._clouds), len(s._fog)))
            self.assertLessEqual(len(s._splashes), 60)
            for d in s._drops:
                self.assertTrue(-60 <= d[0] <= 560 and -40 <= d[1] <= 220, d)
            for f in s._flakes:
                self.assertTrue(-10 <= f[0] <= 510 and -10 <= f[1] <= 210, f)
            for cl in s._clouds:
                self.assertTrue(-cl["w"] - 40 <= cl["x"] <= 540, cl["x"])

    def test_lightning_only_in_storms(self):
        s = sc.WeatherScene(seed=4)
        s.resize(400, 200)
        s.set_conditions(sc.Conditions(sc.THUNDER, 1.0))
        flashes = 0
        for _ in range(600):                   # 20 s
            before = s._flash
            s.advance(1 / 30)
            if s._flash > before:
                flashes += 1
        self.assertGreaterEqual(flashes, 2)
        self.assertIsNotNone(s._bolt)
        s.set_conditions(sc.Conditions(sc.RAIN, 1.0))
        s._flash = 0
        for _ in range(600):
            s.advance(1 / 30)
        self.assertEqual(s._flash, 0)

    def test_rain_slants_with_wind(self):
        for sign in (1.0, -1.0):
            s = sc.WeatherScene(seed=2)
            s.resize(400, 200)
            s.set_conditions(sc.Conditions(sc.RAIN, 0.5, wind_kmh=40, wind_sign=sign))
            xs = [d[0] for d in s._drops]
            s.advance(0.02)
            moved = statistics.mean(d[0] - x for d, x in zip(s._drops, xs) if abs(d[0] - x) < 50)
            self.assertEqual(moved > 0, sign > 0)

    def test_sprite_cache_bounded(self):
        for i in range(200):
            sc.cloud_sprite(50 + i % 7, 30, (i % 10) / 10, i)
        self.assertLessEqual(len(sc._SPRITE_CACHE), sc._SPRITE_CACHE_MAX)

    def test_icons_render_every_code(self):
        img = QImage(48, 48, QImage.Format.Format_ARGB32_Premultiplied)
        for code in all_codes() + [None]:
            for day in (True, False):
                for t in (0.0, 0.3, 1.1, 2.05):
                    img.fill(0)
                    p = QPainter(img)
                    sc.paint_icon(p, QRectF(0, 0, 48, 48), code, day, t, QColor("white"))
                    p.end()
                    self.assertGreater(_distinct_colours(img, 5), 1, (code, day, t))


class TestAnimationClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_runs_only_when_visible_and_enabled(self):
        clock = sc.AnimationClock.instance()
        clock.set_enabled(True)
        s = sc.WeatherScene()
        s.resize(300, 150)
        s.set_conditions(sc.Conditions(sc.RAIN, 0.5))
        QTest.qWait(50)
        s.show()
        QTest.qWait(30)
        self.assertTrue(clock.timer.isActive())
        t0, ticks0 = s.t, clock.ticks
        QTest.qWait(1000)
        frames = clock.ticks - ticks0
        REPORT.append(f"animation clock: {frames} frames in 1 s (target {sc.FPS})")
        self.assertGreater(frames, 15)
        self.assertGreater(s.t, t0 + 0.5)
        s.hide()
        self.assertTrue(wait_until(lambda: not clock.timer.isActive(), 1))
        t_hidden = s.t
        QTest.qWait(200)
        self.assertEqual(s.t, t_hidden, "hidden scene must not animate")
        s.show()
        self.assertTrue(wait_until(lambda: clock.timer.isActive(), 1))
        clock.set_enabled(False)
        self.assertFalse(clock.timer.isActive())
        t_off = s.t
        QTest.qWait(200)
        self.assertEqual(s.t, t_off)
        clock.set_enabled(True)
        self.assertTrue(clock.timer.isActive())
        s.close()
        s.deleteLater()
        QTest.qWait(50)

    def test_icons_repaint_at_half_rate_but_keep_time(self):
        self.assertEqual(sc.WeatherIcon.update_every, 2)
        self.assertEqual(sc.WeatherScene.update_every, 1)
        clock = sc.AnimationClock.instance()
        clock.set_enabled(True)
        icon = sc.WeatherIcon(30)
        icon.set_code(61)
        icon.show()
        t0 = icon.t
        QTest.qWait(600)
        self.assertGreater(icon.t - t0, 0.4)          # time advances at full rate
        icon.close()
        icon.deleteLater()

    def test_deleted_widget_does_not_crash_clock(self):
        clock = sc.AnimationClock.instance()
        clock.set_enabled(True)
        for _ in range(20):
            s = sc.WeatherScene()
            s.show()
            QTest.qWait(5)
            s.deleteLater()
        QTest.qWait(200)
        gc.collect()
        self.assertTrue(wait_until(lambda: not clock.timer.isActive() or clock.visible_targets(), 1))


class TestDesktopWidgetAndToggles(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.wins = []

    def tearDown(self):
        for w in self.wins:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        sc.AnimationClock.instance().set_enabled(True)
        super().tearDown()

    def make(self):
        from weatherdesk.main_window import MainWindow
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        self.wins.append(w)
        return w

    def test_hero_scene_and_icons_follow_forecast(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        self.assertEqual(w.scene.cond.kind, sc.PARTLY)          # fake current code 2
        self.assertEqual(w.day_icons[0].code, 0)
        self.assertEqual(w.day_icons[6].code, 95)
        self.assertEqual(w.day_icons[3].toolTip(), "Overcast")
        w.remove_selected()
        self.assertIsNone(w.day_icons[0].code)

    def test_widget_toggle_shows_weather_and_persists(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        w.set_desktop_widget(True)
        dw = w.desktop_widget
        self.assertTrue(dw.isVisible())
        self.assertEqual(dw.temp.text(), w.temp_label.text())
        self.assertEqual(dw.place.text(), "Auckland")
        self.assertTrue(dw.hilo.text().startswith("H "))
        self.assertTrue(SettingsStore().load().desktop_widget)
        w.set_unit("temp_unit", "F")
        self.assertTrue(dw.temp.text().endswith("°F"))
        dw.move(123, 87)
        dw.moved.emit(123, 87)
        dw.set_size_name("large")
        self.assertEqual(dw.size().width(), 440)
        dw.set_on_top(True)
        self.assertTrue(dw.isVisible())
        st = SettingsStore().load()
        self.assertEqual((st.widget_x, st.widget_y, st.widget_size, st.widget_on_top), (123, 87, "large", True))
        dw.hide_requested.emit()
        self.assertIsNone(w.desktop_widget)
        self.assertFalse(w.act_widget.isChecked())
        self.assertFalse(SettingsStore().load().desktop_widget)

    def test_widget_restored_on_restart_and_closed_with_app(self):
        w = self.make()
        w.set_desktop_widget(True)
        w.desktop_widget.move(200, 150)
        w._quitting = True
        w.close()
        self.assertIsNone(w.desktop_widget)
        w2 = self.make()
        self.assertIsNotNone(w2.desktop_widget)
        self.assertEqual((w2.desktop_widget.x(), w2.desktop_widget.y()), (200, 150))
        self.assertIn("Add a location", w2.desktop_widget.cond.text())

    def test_offscreen_position_recovered(self):
        st = SettingsStore()
        s = Settings()
        s.desktop_widget, s.widget_x, s.widget_y = True, 15000, 15000
        st.save(s)
        w = self.make()
        g = QApplication.primaryScreen().availableGeometry()
        self.assertTrue(g.contains(w.desktop_widget.geometry().center()))

    def test_widget_menu(self):
        w = self.make()
        w.set_desktop_widget(True)
        texts = [a.text() for a in w.desktop_widget.build_menu().actions()]
        for t in ("Open WeatherDesk", "Refresh", "Size", "Keep on top of windows", "Hide widget"):
            self.assertIn(t, texts)

    def test_animation_toggle_persists(self):
        w = self.make()
        w.set_animations(False)
        self.assertFalse(sc.AnimationClock.instance().timer.isActive())
        self.assertFalse(SettingsStore().load().animations)
        w._quitting = True
        w.close()
        w2 = self.make()
        self.assertFalse(w2.act_anim.isChecked())
        self.assertFalse(sc.AnimationClock.instance().enabled)
        w2.set_animations(True)
        self.assertTrue(wait_until(lambda: sc.AnimationClock.instance().timer.isActive(), 1))

    def test_invalid_widget_settings_replaced(self):
        d = Settings().to_dict()
        d.update(widget_x="a", widget_y=True, widget_size="huge", animations="yes", widget_on_top=1)
        s = Settings.from_dict(d)
        self.assertEqual((s.widget_x, s.widget_y, s.widget_size, s.animations, s.widget_on_top),
                         (None, None, "medium", True, False))

    def test_widget_toggle_no_leak(self):
        w = self.make()
        w.set_desktop_widget(True)
        w.set_desktop_widget(False)
        QTest.qWait(50)
        gc.collect()
        base = len(QApplication.topLevelWidgets())
        for _ in range(20):
            w.set_desktop_widget(True)
            w.set_desktop_widget(False)
        QTest.qWait(100)
        gc.collect()
        after = len(QApplication.topLevelWidgets())
        REPORT.append(f"desktop widget on/off x20: top-level widgets {after} (base {base})")
        self.assertLessEqual(after, base)


def tearDownModule():
    print("\n--- scene results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
