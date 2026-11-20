"""Forecast playback (1.18.0): the next 24 hours in the animated sky.

The sky for a moment ahead comes from the hourly forecast (weather), that day's sunrise
and sunset (Sun), and the Moon at that moment; the wind stays as now. A change of weather
type cross-fades the clouds. The bar plays an hour a second, scrubs in 15-minute steps and
returns to now; the main window shows that hour in the sky and the card while the rest of
the window, the tray and the desktop widget stay live.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import time
import unittest

import numpy as np

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest

from fake_server import make_forecast
from weatherdesk import scene as sc
from weatherdesk import units
from weatherdesk.api import parse_forecast
from weatherdesk.models import Location
from weatherdesk.playback import PLAY_RATE, STEP_MIN, TICK_MS, PlaybackBar

REPORT: list[str] = []
LOC = Location("Auckland", -36.85, 174.76, "New Zealand", "Auckland", "Pacific/Auckland")
FRAME = 1 / sc.FPS


def forecast(fetched_ago=0.0, hourly=True):
    """The fake Open-Meteo forecast: local time 2026-11-15 10:15, hourly codes cycling
    0, 1, 2, 3, 61, 80, 95 (a change every hour), sunrise 06:0d / sunset 20:1d on day d."""
    d = make_forecast(LOC.latitude, LOC.longitude)
    if not hourly:
        d.pop("hourly")
    fc = parse_forecast(d, LOC)
    fc.fetched_at = time.time() - fetched_ago
    return fc


def frame(s, size=(640, 240)):
    img = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    s.render(p)
    p.end()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(size[1], size[0], 4)[:, :, :3].astype(np.int16).copy()


class TestSkyAtAMomentAhead(unittest.TestCase):
    def setUp(self):
        self.fc = forecast()
        self.now = time.time()

    def test_weather_comes_from_that_hours_forecast(self):
        start = sc.local_time(self.fc, self.now)
        self.assertEqual(start.strftime("%Y-%m-%d %H:%M"), "2026-11-15 10:15")
        for hours in (1, 3, 6, 9.5, 13, 20, 23.75):
            off = hours * 3600
            when = start + dt.timedelta(seconds=off)
            hp = sc.hourly_at(self.fc, when)
            self.assertIsNotNone(hp, hours)
            self.assertEqual(hp.time[:13], when.strftime("%Y-%m-%dT%H"))
            c = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=off)
            self.assertEqual((c.kind, c.intensity), sc.classify(hp.weather_code), hours)
            self.assertIsNone(c.cloud_cover)                    # not in the hourly data
        # the very next minutes still belong to this hour's forecast
        c = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=60)
        self.assertEqual(c.kind, sc.classify(sc.hourly_at(self.fc, start).weather_code)[0])

    def test_offset_zero_is_the_live_sky(self):
        a = sc.conditions_from_forecast(self.fc, now=self.now)
        b = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=0.0)
        self.assertEqual(a, b)
        self.assertEqual(a.kind, sc.classify(self.fc.current.weather_code)[0])
        self.assertEqual(a.cloud_cover, self.fc.current.cloud_cover)

    def test_day_night_and_sun_follow_the_time_ahead(self):
        rows = []
        for hours, want in ((0, "day"), (9, "day"), (10, "dusk"), (13, "night"), (19.75, "dawn"), (23, "day")):
            c = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=hours * 3600)
            got = "day" if c.daylight >= 1 else "night" if c.daylight <= 0 else (
                "dusk" if hours < 16 else "dawn")
            self.assertEqual(got, want, hours)
            rows.append(f"+{hours:g} h {got}")
        REPORT.append("sky ahead from 10:15: " + ", ".join(rows))

    def test_tomorrows_hours_use_tomorrows_sunrise_and_sunset(self):
        # day 0: sunrise 06:00, sunset 20:10; day 1: 06:01 / 20:11 (fake data)
        off = 20 * 3600                                          # Mon 06:15
        at = self.now + off
        c = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=off)
        self.assertAlmostEqual(at - c.sun_rise_ts, 14 * 60, delta=61)    # 06:01, not 06:00
        self.assertAlmostEqual(c.sun_set_ts - at, (20 * 60 + 11 - (6 * 60 + 15)) * 60, delta=61)
        today = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=3600)
        self.assertAlmostEqual(today.sun_set_ts - (self.now + 3600),
                               (20 * 60 + 10 - (11 * 60 + 15)) * 60, delta=61)

    def test_moon_is_where_it_will_be(self):
        """Regression: before 1.18 the Moon was always calculated for the real now."""
        for hours in (3, 11, 22):
            off = hours * 3600
            ahead = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=off)
            at = sc.conditions_from_forecast(self.fc, now=self.now + off)    # the same moment
            for f in ("moon_age", "moon_phase_angle", "moon_limb", "moon_rotation", "moon_up",
                      "moon_altitude", "moon_rise_ts", "moon_set_ts"):
                self.assertEqual(getattr(ahead, f), getattr(at, f), (hours, f))
        # and a moment in the past is not the real now any more
        then = time.mktime((2026, 6, 1, 12, 0, 0, 0, 0, -1))
        c = sc.conditions_from_forecast(self.fc, now=then)
        self.assertAlmostEqual(c.moon_age, sc.moon_phase(dt.datetime.fromtimestamp(then, dt.timezone.utc)))
        self.assertNotAlmostEqual(c.moon_age, sc.moon_phase(dt.datetime.now(dt.timezone.utc)), 3)

    def test_wind_stays_as_now(self):
        now = sc.conditions_from_forecast(self.fc, now=self.now)
        ahead = sc.conditions_from_forecast(self.fc, now=self.now, offset_s=7 * 3600)
        self.assertEqual((ahead.wind_kmh, ahead.wind_east), (now.wind_kmh, now.wind_east))

    def test_how_far_ahead(self):
        self.assertEqual(sc.playback_seconds(self.fc, self.now), sc.PLAYBACK_MAX_S)
        short = forecast()
        cutoff = "2026-11-15T15"                                 # forecast ends after 15:00
        short.hourly = [hp for hp in short.hourly if hp.time[:13] <= cutoff]
        secs = sc.playback_seconds(short, self.now)
        self.assertAlmostEqual(secs, (16 * 60 - (10 * 60 + 15)) * 60 - 1, delta=61)  # to 16:00
        self.assertEqual(sc.playback_seconds(forecast(hourly=False), self.now), 0.0)
        past = forecast()
        past.hourly = [hp for hp in past.hourly if hp.time[:13] < "2026-11-15T10"]
        self.assertEqual(sc.playback_seconds(past, self.now), 0.0)
        for hp in self.fc.hourly:                                 # hours without a code don't count
            hp.weather_code = None
        self.assertEqual(sc.playback_seconds(self.fc, self.now), 0.0)

    def test_old_forecast_keeps_its_clock(self):
        # the location's clock moves on with time since download (as before, at most 6 h)
        fc = forecast(fetched_ago=2 * 3600)
        self.assertEqual(sc.local_time(fc).strftime("%H:%M"), "12:15")
        c = sc.conditions_from_forecast(fc, offset_s=3600)
        self.assertEqual(c.kind, sc.classify(sc.hourly_at(fc, sc.local_time(fc) + dt.timedelta(hours=1)).weather_code)[0])


class TestCloudCrossFade(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()
        sc.AnimationClock.instance().set_enabled(True)

    def scene(self):
        s = sc.WeatherScene(seed=5)
        s.resize(640, 240)
        s.set_conditions(sc.Conditions(sc.PARTLY, 0.5))
        return s

    def test_weather_change_fades_instead_of_jumping(self):
        s = self.scene()
        before = frame(s)
        s.set_conditions(sc.Conditions(sc.OVERCAST, 1.0))
        self.assertEqual(s.cloud_fade, 0.0)
        self.assertEqual(len(s._fading), 1)
        self.assertTrue(np.array_equal(frame(s), before))           # nothing jumps at the change
        diffs, last = [], before
        for _ in range(int(sc.CLOUD_FADE_S / FRAME) + 3):
            s.advance(FRAME)
            img = frame(s)
            diffs.append(np.abs(img - last).mean())
            last = img
        self.assertEqual((s.cloud_fade, s._fading), (1.0, []))
        jump = np.abs(last - before).mean()                          # the whole change at once
        self.assertLess(max(diffs), jump * 0.25)
        REPORT.append(f"cloud cross-fade partly -> overcast: largest change in one frame {max(diffs):.2f} "
                      f"(mean pixel), vs {jump:.2f} if it jumped; done in {sc.CLOUD_FADE_S} s")

    def test_rapid_changes_never_pop(self):
        """Fast playback: the weather changes before a fade ends. Every layout fades from
        however visible it was; the layers stay bounded. (No thunder here: its lightning
        flashes suddenly by design; see test_thunder_fades_in_but_still_flashes.)"""
        s = self.scene()
        kinds = [sc.OVERCAST, sc.RAIN, sc.PARTLY, sc.SNOW, sc.CLEAR, sc.DRIZZLE, sc.FOG, sc.OVERCAST]
        last = frame(s)
        worst, most_layers = 0.0, 0
        for k in kinds:
            s.set_conditions(sc.Conditions(k, 0.7))
            for _ in range(5):                                       # 0.2 s per weather type
                s.advance(FRAME)
                img = frame(s)
                worst = max(worst, np.abs(img - last).mean())
                last = img
                most_layers = max(most_layers, len(s._fading))
                for f in s._fading:
                    self.assertLessEqual(f[2], 1.0)
                self.assertLessEqual(len(s._old_weather), 2)
        self.assertLessEqual(most_layers, 3)
        jump = self.biggest_jump(kinds)
        self.assertLess(worst, jump * 0.3)
        REPORT.append(f"{len(kinds)} weather types 0.2 s apart (rain, snow, fog, clear...): largest change "
                      f"in one frame {worst:.2f} (mean pixel) vs {jump:.2f} when the same changes jump; "
                      f"at most {most_layers} cloud layouts fading")

    def biggest_jump(self, kinds):
        """The same sequence without fading (animation off): the size of the jumps."""
        sc.AnimationClock.instance().set_enabled(False)
        try:
            s = self.scene()
            last, worst = frame(s), 0.0
            for k in kinds:
                s.set_conditions(sc.Conditions(k, 0.7))
                img = frame(s)
                worst = max(worst, np.abs(img - last).mean())
                last = img
            return worst
        finally:
            sc.AnimationClock.instance().set_enabled(True)

    def test_rain_snow_and_fog_fade_out_while_still_moving(self):
        s = self.scene()
        s.set_conditions(sc.Conditions(sc.RAIN, 0.8))
        for _ in range(30):
            s.advance(FRAME)
        drops = s._drops
        s.set_conditions(sc.Conditions(sc.PARTLY, 0.5))             # the rain stops
        self.assertEqual(len(s._old_weather), 1)
        old = s._old_weather[0]
        self.assertIs(old["_drops"], drops)
        y0 = [d[1] for d in drops[:20]]
        s.advance(FRAME)
        self.assertNotEqual([d[1] for d in old["_drops"][:20]], y0)  # still falling while fading
        self.assertLess(old["alpha"], 1.0)
        for _ in range(int(sc.CLOUD_FADE_S / FRAME) + 2):
            s.advance(FRAME)
        self.assertEqual(s._old_weather, [])

    def test_sky_tint_blends(self):
        s = self.scene()
        before = s.shown_sky_colors()[0]
        s.set_conditions(sc.Conditions(sc.THUNDER, 1.0))
        after = s.sky_colors()[0]                                    # where it's going
        self.assertEqual(s.shown_sky_colors()[0].name(), before.name())
        s.advance(sc.CLOUD_FADE_S / 2)
        mid = s.shown_sky_colors()[0]
        self.assertTrue(min(before.lightness(), after.lightness()) <= mid.lightness()
                        <= max(before.lightness(), after.lightness()))
        self.assertNotEqual(mid.name(), before.name())
        self.assertNotEqual(mid.name(), after.name())
        s.advance(sc.CLOUD_FADE_S)
        self.assertEqual(s.shown_sky_colors()[0].name(), after.name())

    def test_thunder_fades_in_but_still_flashes(self):
        s = self.scene()
        s.set_conditions(sc.Conditions(sc.THUNDER, 1.0))
        flashes = 0
        for _ in range(int(10 / FRAME)):
            s.advance(FRAME)
            flashes += s._flash == 1.0
        self.assertGreater(flashes, 0)

    def test_wind_only_change_does_not_fade(self):
        s = self.scene()
        c = sc.Conditions(sc.PARTLY, 0.5, wind_kmh=60)
        s.set_conditions(c)
        self.assertEqual((s.cloud_fade, s._fading), (1.0, []))

    def test_without_animation_the_change_is_instant(self):
        s = self.scene()
        sc.AnimationClock.instance().set_enabled(False)
        try:
            s.set_conditions(sc.Conditions(sc.OVERCAST, 1.0))
            self.assertEqual((s.cloud_fade, s._fading), (1.0, []))
            frame(s)
        finally:
            sc.AnimationClock.instance().set_enabled(True)
        # and turned off mid-fade: the next paint finishes it rather than freezing
        s.set_conditions(sc.Conditions(sc.RAIN, 0.8))
        self.assertEqual(s.cloud_fade, 0.0)
        sc.AnimationClock.instance().set_enabled(False)
        try:
            frame(s)
            self.assertEqual((s.cloud_fade, s._fading), (1.0, []))
        finally:
            sc.AnimationClock.instance().set_enabled(True)

    def test_resize_mid_fade_starts_clean(self):
        s = self.scene()
        s.show()                                     # (a hidden widget gets its resize later)
        QTest.qWait(20)
        s.set_conditions(sc.Conditions(sc.RAIN, 1.0))
        self.assertEqual(s.cloud_fade, 0.0)
        s.resize(300, 170)
        QTest.qWait(20)
        self.assertEqual((s.cloud_fade, s._fading, s._old_weather), (1.0, [], []))
        self.assertTrue(s._clouds and s._drops)
        s.hide()


class TestPlaybackBar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()

    def bar(self, secs=24 * 3600):
        b = PlaybackBar()
        b.set_range(secs, "none")
        self.got = []
        b.offset_changed.connect(self.got.append)
        return b

    def test_starts_at_now(self):
        b = self.bar()
        self.assertEqual(b.offset, 0.0)
        self.assertEqual(b.slider.maximum(), 24 * 60 // STEP_MIN)
        self.assertFalse(b.now_btn.isEnabled())
        self.assertEqual(b.play_btn.text(), "▶")

    def test_play_is_an_hour_a_second_and_stops_at_the_end(self):
        b = self.bar(3 * 3600)
        b.toggle_play()
        self.assertTrue(b.playing)
        self.assertEqual(b.play_btn.text(), "⏸")
        t0 = time.monotonic()
        self.assertTrue(wait_until(lambda: not b.playing, 10))
        took = time.monotonic() - t0
        self.assertEqual(b.offset, 3 * 3600)
        self.assertAlmostEqual(took, 3.0, delta=0.6)                  # 3 hours in about 3 seconds
        steps = [y - x for x, y in zip(self.got, self.got[1:])]
        self.assertAlmostEqual(max(steps), PLAY_RATE * TICK_MS / 1000, delta=1e-6)   # 144 s a tick
        b.toggle_play()                                               # at the end: from now again
        self.assertLess(b.offset, 600)
        b.stop()
        REPORT.append(f"play: 3 forecast hours in {took:.2f} s, {len(self.got)} steps of "
                      f"{PLAY_RATE * TICK_MS / 1000:.0f} s")

    def test_slider_scrubs_in_15_minute_steps_and_pauses_play(self):
        b = self.bar()
        b.toggle_play()
        b.slider.setValue(10)
        self.assertFalse(b.playing)
        self.assertEqual(b.offset, 10 * STEP_MIN * 60)
        self.assertTrue(b.now_btn.isEnabled())

    def test_now_and_reset(self):
        b = self.bar()
        b.slider.setValue(8)
        b.go_now()
        self.assertEqual((b.offset, self.got[-1]), (0.0, 0.0))
        b.slider.setValue(8)
        n = len(self.got)
        b.reset()
        self.assertEqual(b.offset, 0.0)
        self.assertEqual(len(self.got), n)                            # quiet
        self.assertEqual(b.slider.value(), 0)

    def test_disabled_without_hourly_data(self):
        b = self.bar()
        b.slider.setValue(4)
        b.set_range(0.0, "Weather Underground doesn't provide an hourly forecast")
        self.assertFalse(b.play_btn.isEnabled() or b.slider.isEnabled())
        self.assertEqual(b.offset, 0.0)
        self.assertIn("doesn't provide an hourly forecast", b.time_label.text())
        b.toggle_play()
        self.assertFalse(b.playing)

    def test_shorter_forecast_clamps(self):
        b = self.bar()
        b.slider.setValue(80)                                         # 20 h
        b.set_range(5 * 3600)
        self.assertEqual(b.offset, 5 * 3600)
        self.assertEqual(b.slider.maximum(), 5 * 60 // STEP_MIN)


class TestInTheApp(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        from weatherdesk.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False)
        self.w.resize(1150, 800)
        self.w.show()
        self.w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not self.w._pending))
        self.fc = self.w.forecasts[self.place(0).key]

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def live(self):
        c = self.fc.current
        return (units.fmt_temp(c.temperature, self.w.settings.temp_unit), self.w.desc_label.text())

    def test_card_and_sky_show_the_hour_while_the_rest_stays_live(self):
        w = self.w
        live_temp = w.temp_label.text()
        details = {k: v.text() for k, v in w.detail.items()}
        w.set_desktop_widget(True)
        widget_temp = w.desktop_widget.temp.text()
        self.assertEqual(w.playback.max_offset, sc.PLAYBACK_MAX_S)
        self.assertTrue(w.playback.slider.isEnabled())

        w.playback.slider.setValue(12)                                # +3 h: 13:15
        when = sc.local_time(self.fc) + dt.timedelta(hours=3)
        hp = sc.hourly_at(self.fc, when)
        self.assertEqual(w.temp_label.text(), units.fmt_temp(hp.temperature, "C"))
        from weatherdesk import weather_codes
        self.assertTrue(w.desc_label.text().startswith(weather_codes.describe(hp.weather_code)))
        self.assertIn(f"{hp.precipitation_probability:.0f}%", w.desc_label.text())
        self.assertEqual(w.message_label.text(), f"▶ Forecast for {units.fmt_clock(when, day=True)}")
        self.assertEqual(w.playback.time_label.text(), units.fmt_clock(when, day=True))
        self.assertIn("no wind", w.playback.time_label.toolTip())
        self.assertEqual(w.scene.cond.kind, sc.classify(hp.weather_code)[0])
        self.assertAlmostEqual(w.scene.clock() - time.time(), 3 * 3600, delta=2)
        # unchanged: details, the desktop widget (live sky and text)
        self.assertEqual({k: v.text() for k, v in w.detail.items()}, details)
        self.assertEqual(w.desktop_widget.temp.text(), widget_temp)
        self.assertEqual(w.desktop_widget.scene.cond.kind, sc.classify(self.fc.current.weather_code)[0])
        self.assertAlmostEqual(w.desktop_widget.scene.clock(), time.time(), delta=2)

        w.playback.now_btn.click()                                    # back to now
        self.assertEqual(w.temp_label.text(), live_temp)
        self.assertTrue(w.message_label.text().startswith("Local time at location"))
        self.assertEqual(w.scene.cond.kind, sc.classify(self.fc.current.weather_code)[0])
        self.assertIs(w.scene.clock, time.time)
        self.assertEqual(w.playback.time_label.text(), "Now")

    def test_new_location_starts_at_now(self):
        w = self.w
        w.playback.slider.setValue(20)
        w.add_location(self.place(3))
        self.assertTrue(wait_until(lambda: not w._pending))
        self.assertEqual(w.playback.offset, 0.0)
        self.assertIs(w.scene.clock, time.time)

    def test_refresh_and_unit_change_keep_the_hour_without_flicker(self):
        w = self.w
        w.playback.slider.setValue(16)                                # +4 h
        want = w.scene.cond.kind
        kinds = []
        real = w.scene.set_conditions

        def spy(cond):
            kinds.append(cond.kind)
            real(cond)
        w.scene.set_conditions = spy
        w.set_unit("temp_unit", "F")
        w.refresh_selected(force=True)
        self.assertTrue(wait_until(lambda: not w._pending))
        w._update_scene()                                             # the minute tick
        self.assertEqual(w.playback.offset, 16 * STEP_MIN * 60)
        self.assertTrue(kinds)
        self.assertEqual(set(kinds), {want})                          # never the live sky in between
        self.assertTrue(w.temp_label.text().endswith("°F"))
        self.assertTrue(w.message_label.text().startswith("▶ Forecast for"))

    def test_twelve_hour_clock(self):
        w = self.w
        w.set_unit("time_format", "12")
        w.playback.slider.setValue(20)                                # 15:15
        self.assertIn("3:15", w.playback.time_label.text())
        self.assertIn("pm", w.playback.time_label.text().lower())

    def test_provider_without_hourly_forecast(self):
        w = self.w
        self.fc.hourly = []
        w.playback.slider.setValue(8)
        w.render()
        self.assertEqual(w.playback.offset, 0.0)
        self.assertFalse(w.playback.slider.isEnabled())
        self.assertIn("doesn't provide an hourly forecast", w.playback.time_label.text())
        self.assertTrue(w.message_label.text().startswith("Local time at location"))

    def test_playing_through_the_day(self):
        """Real play for 3 s (3 forecast hours): the sky changes with the hours, nothing
        breaks, and each step is cheap."""
        w = self.w
        seen, cost = [], []
        real = w._apply_playback

        def timed(fc):
            t0 = time.perf_counter()
            real(fc)
            cost.append((time.perf_counter() - t0) * 1000)
            seen.append(w.scene.cond.kind)
        w._apply_playback = timed
        w.playback.toggle_play()
        QTest.qWait(3000)
        w.playback.stop()
        self.assertGreaterEqual(len(set(seen)), 3)                    # the weather changed
        self.assertGreater(w.playback.offset, 2 * 3600)
        median = sorted(cost)[len(cost) // 2]
        self.assertLess(median, 15.0)
        REPORT.append(f"playing in the app: {len(cost)} steps in 3 s, {len(set(seen))} weather types, "
                      f"median {median:.1f} ms per step (worst {max(cost):.1f} ms)")


def tearDownModule():
    print("\n--- playback results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
