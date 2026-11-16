"""Globe sky and zoom tests: the Sun, Moon and stars behind the Earth Globe
(positions, hiding behind the Earth, the Moon's lit side and phase), the
off-screen hints, and zooming with the wheel, buttons and keys."""

from __future__ import annotations

import datetime as dt
import math
import time
import unittest
from unittest import mock

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from weatherdesk import earth as E
from weatherdesk import globe as G
from weatherdesk import sky as S

REPORT: list[str] = []
UTC = dt.timezone.utc
T = dt.datetime(2026, 11, 15, 1, 20, tzinfo=UTC)


def antipode(lat, lon):
    return -lat, lon + 180.0


def lit_screen_angle(bright_limb, rotation):
    """Clockwise-from-up direction of the Moon's lit side after render_moon's rotation."""
    return (rotation - bright_limb) % 360


def angdiff(a, b):
    return abs((a - b + 180) % 360 - 180)


class TestSkyGeometry(unittest.TestCase):
    def test_projection_basics(self):
        b = S.basis(10, 20)
        self.assertEqual(S.sky_xy(S.ecef(10, 20), b), None)                 # behind the camera
        x, y = S.sky_xy(S.ecef(*antipode(10, 20)), b)                       # straight behind the Earth
        self.assertAlmostEqual(x, 0, places=9)
        self.assertAlmostEqual(y, 0, places=9)
        self.assertTrue(S.hidden_by_earth((x, y), 0.05))
        # an object RHO degrees from straight-behind sits exactly on the Earth's edge
        b0 = S.basis(0, 0)
        for theta in (10.0, S.RHO, 55.0):
            x, y = S.sky_xy(S.ecef(0, 180 - theta), b0)       # behind, displaced towards the east
            self.assertAlmostEqual(math.hypot(x, y), math.tan(math.radians(theta)) / S.TAN_RHO, places=9)
        x, _ = S.sky_xy(S.ecef(0, 180 - 30), b0)
        self.assertGreater(x, 0)                              # east is on the right, as on the globe
        _, y = S.sky_xy(S.ecef(30, 180), b0)                  # towards the north pole, behind
        self.assertGreater(y, 0)

    def test_sun_sets_behind_earth_with_the_terminator(self):
        """The Sun touches the globe's edge when the place in the middle of the view has
        the Sun RHO degrees from its nadir - consistent with day and night on the globe."""
        slat, slon = E.subsolar_point(T)
        sun = S.ecef(slat, slon)
        for c in ((0, slon + 180), (40, slon + 150), (-30, slon - 140)):
            elev = E.solar_elevation(T, *c)
            xy = S.sky_xy(sun, S.basis(*c))
            theta = 90 + elev                                  # angle from straight behind
            if xy is None:
                self.assertGreaterEqual(elev, -0.01)           # day side facing us: Sun behind camera
                continue
            r = math.hypot(*xy)
            self.assertAlmostEqual(r, math.tan(math.radians(theta)) / S.TAN_RHO, places=6)
            self.assertEqual(r < 1, theta < S.RHO)

    def test_moon_lit_side_faces_the_sun_on_screen(self):
        worst = 0.0
        for mlat, mlon, slat, slon, clat, clon in ((5, 170, -15, 150, 0, -10), (-20, -100, 18, -60, 30, 90),
                                                    (40, 0, -10, 40, -50, 200), (0, 90, 0, 140, 60, -80)):
            m, s = S.ecef(mlat, mlon), S.ecef(slat, slon)
            b = S.basis(clat, clon)
            o = S.moon_orientation(m, s, b)
            self.assertIsNotNone(o)
            mxy = S.sky_xy(m, b)
            sxy = S.sky_xy(s, b)
            if sxy is None:
                continue
            want = S._screen_angle(mxy, sxy)                   # straight line in this projection
            worst = max(worst, angdiff(lit_screen_angle(*o), want))
        REPORT.append(f"Moon lit side vs direction to the Sun on screen: worst {worst:.2f} deg")
        self.assertLess(worst, 1.0)

    def test_rendered_moon_bright_towards_sun(self):
        qapp()
        from weatherdesk.moon_render import render_moon
        m, s = S.ecef(5, 170), S.ecef(-15, 120)               # Sun lower-left of the Moon
        b = S.basis(0, -10)
        bl, rot = S.moon_orientation(m, s, b)
        img = render_moon(96, 90.0, bl, rotation=rot)
        ang = math.radians(S._screen_angle(S.sky_xy(m, b), S.sky_xy(s, b)))
        ux, uy = math.sin(ang), -math.cos(ang)                 # screen direction (y down)
        def lum(k):
            c = img.pixelColor(int(48 + ux * 30 * k), int(48 + uy * 30 * k))
            return c.lightness()
        self.assertGreater(lum(1), lum(-1) + 40)

    def test_stars_turn_with_sidereal_time_and_paths_agree(self):
        b = S.basis(20, 30)
        f = S.StarField(600, seed=3)
        a = f.positions(100.0, b, 3.0)
        c = f.positions(130.0, b, 3.0)
        self.assertTrue(a and c)
        self.assertNotEqual(a[:5], c[:5])
        self.assertTrue(all(1.0 < math.hypot(x, y) < 3.0 for x, y, *_ in a))
        if S._np is not None:
            with mock.patch.object(S, "_np", None):
                py = S.StarField(600, seed=3).positions(100.0, b, 3.0)
            self.assertEqual(len(py), len(a))
            self.assertLess(max(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(sorted(py), sorted(a))), 1e-9)


class TestGlobeSkyAndZoom(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        from weatherdesk.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False)
        self.w.resize(1100, 820)
        self.w.show()
        from weatherdesk.models import Location
        for d in (PLACES[0], dict(name="London", latitude=51.5072, longitude=-0.1276, country="United Kingdom",
                                  admin1="England", timezone="Europe/London")):
            self.w.add_location(Location.from_dict(d))
            self.assertTrue(wait_until(lambda: not self.w._pending))
        self.w.tabs.setCurrentWidget(self.w.globe_panel)
        self.v = self.w.globe_panel.view
        self.assertTrue(wait_until(lambda: self.v.image is not None, 20))
        self.assertTrue(wait_until(lambda: self.v.anim.state().name == "Stopped", 5))

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def paint(self):
        return self.v.grab().toImage()

    def test_sun_drawn_where_expected_and_hidden_on_day_side(self):
        t = self.v.image_time
        slat, slon = E.subsolar_point(t)
        self.v.set_center(-slat * 0.3, slon + 180 - 52)        # night side, Sun just off the edge
        img = self.paint()
        self.assertIn("sun", self.v.sky_drawn)
        sx, sy, hidden = self.v.sky_drawn["sun"]
        r = self.v.globe_rect()
        xy = S.sky_xy(S.ecef(slat, slon), S.basis(self.v.c_lat, self.v.c_lon))
        self.assertAlmostEqual(sx, r.center().x() + xy[0] * r.width() / 2, places=3)
        self.assertFalse(hidden)
        self.assertGreater(img.pixelColor(int(sx), int(sy)).lightness(), 240)       # bright disc
        self.assertGreater(math.hypot(sx - r.center().x(), sy - r.center().y()), r.width() / 2)
        # facing the sunlit side: the Sun is behind us -> not drawn, a hint at the edge instead
        self.v.set_center(slat, slon + 25)
        self.paint()
        self.assertNotIn("sun", self.v.sky_drawn)
        tips = [i[1] for i in self.v._indicators]
        self.assertIn("The Sun is behind you, this way", tips)

    def test_moon_drawn_with_real_phase(self):
        t = self.v.image_time
        mlat, mlon = E.sublunar_point(t)
        self.v.set_center(-mlat * 0.5, mlon + 180 - 50)
        self.paint()
        self.assertIn("moon", self.v.sky_drawn)
        from weatherdesk.moon import moon_phase
        self.assertEqual(self.v.sky_drawn["moon"][4], round(moon_phase(t).illumination * 100))
        # straight behind the Earth: hidden
        self.v.set_center(*antipode(mlat, mlon))
        self.paint()
        self.assertNotIn("moon", self.v.sky_drawn)

    def test_sky_moves_as_the_globe_spins(self):
        slat, slon = E.subsolar_point(self.v.image_time)
        self.v.set_center(0, slon + 180 - 50)
        self.paint()
        a = self.v.sky_drawn.get("sun")
        self.v.set_center(0, slon + 180 - 45)
        self.paint()
        b = self.v.sky_drawn.get("sun")
        self.assertTrue(a and b)
        self.assertGreater(b[0], a[0])          # turning the view east brings the Sun in from the left
        t0 = time.perf_counter()
        for i in range(10):
            self.v.set_center(0, slon + 180 - 50 + i)
            self.v.repaint()
        ms = (time.perf_counter() - t0) * 100
        REPORT.append(f"globe paint with stars, Sun and Moon: {ms:.0f} ms")
        self.assertLess(ms, 250)

    def wheel(self, notches):
        pos = QPointF(self.v.width() / 2, self.v.height() / 2)
        ev = QWheelEvent(pos, self.v.mapToGlobal(pos), QPoint(0, 0), QPoint(0, int(120 * notches)),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(self.v, ev)

    def settle(self):
        self.assertTrue(wait_until(lambda: not self.v.zooming(), 3))

    def test_zoom_wheel_buttons_keys_and_limits(self):
        d0 = self.v.globe_rect().width()
        self.wheel(1)
        self.assertAlmostEqual(self.v._zoom_target, 1.25)
        self.assertEqual(self.v.zoom_label.text(), "125%")
        self.settle()
        self.assertAlmostEqual(self.v.zoom, 1.25)
        self.assertAlmostEqual(self.v.globe_rect().width(), d0 * 1.25, places=3)
        self.v.zoom_out_btn.click()
        self.settle()
        self.assertEqual(self.v.zoom, 1.0)
        self.v.zoom_in_btn.click()
        QTest.keyClick(self.v, Qt.Key.Key_Plus)              # a second step while gliding
        self.settle()
        self.assertAlmostEqual(self.v.zoom, 1.5625)
        QTest.keyClick(self.v, Qt.Key.Key_0)
        self.settle()
        self.assertEqual(self.v.zoom, 1.0)
        QTest.keyClick(self.v, Qt.Key.Key_Minus)
        self.settle()
        self.assertAlmostEqual(self.v.zoom, 0.8)
        for _ in range(20):
            self.wheel(1)
        self.settle()
        self.assertEqual(self.v.zoom, G_ZOOM_MAX())
        self.assertFalse(self.v.zoom_in_btn.isEnabled())
        self.wheel(-40)
        self.settle()
        self.assertEqual(self.v.zoom, G_ZOOM_MIN())
        self.assertFalse(self.v.zoom_out_btn.isEnabled())
        self.wheel(0.25)                                      # touchpad: a small fraction of a step
        self.settle()
        self.assertAlmostEqual(self.v.zoom, G_ZOOM_MIN() * 1.25 ** 0.25, places=6)

    def test_zoom_glides_without_rerendering_each_frame(self):
        """The fix for choppy zooming: frames during the glide only scale the existing
        globe picture; one sharp render happens when the zoom settles."""
        slat, slon = E.subsolar_point(self.v.image_time)
        self.v.set_center(-slat * 0.3, slon + 180 - 50)      # Sun and sky in view
        QTest.qWait(100)
        before = self.v.renders
        at_end = []
        self.v.zoom_anim.finished.connect(lambda: at_end.append(self.v.renders - before))
        self.v.zoom_in()
        frames, worst = 0, 0.0
        sprites = set()
        while self.v.zooming():
            t0 = time.perf_counter()
            self.v.repaint()
            sprites.add(id(self.v._sun_cache[1]) if self.v._sun_cache else None)
            worst = max(worst, (time.perf_counter() - t0) * 1000)
            frames += 1
            QTest.qWait(10)
        QTest.qWait(150)
        during = at_end[0]
        after = self.v.renders - before
        REPORT.append(f"zoom glide: {frames} frames, worst frame {worst:.0f} ms, globe re-renders "
                      f"during {during}, after {after}")
        self.assertGreaterEqual(frames, 5)
        self.assertEqual(during, 0)
        self.assertEqual(after, 1)
        self.assertLess(worst, 40)
        self.assertEqual(len(sprites), 1)                    # Sun picture not rebuilt mid-glide
        self.assertIn("sun", self.v.sky_drawn)

    def test_moon_high_res_cached_and_reused_while_moving(self):
        t = self.v.image_time
        mlat, mlon = E.sublunar_point(t)
        self.v.set_center(-mlat * 0.5, mlon + 180 - 50)
        self.paint()
        key, img = self.v._moon_cache
        from weatherdesk.globe_panel import MOON_SIZE
        rad = self.v.globe_rect().width() / 2
        size = rad * MOON_SIZE * 2
        self.assertEqual(img.width(), key[0])
        self.assertAlmostEqual(key[0], size * self.v.devicePixelRatioF(), delta=8)   # screen resolution
        self.assertGreaterEqual(size, rad * 0.32 * 2 * 0.99)      # 2x the 1.7.0 size (0.16 radii)
        from weatherdesk import moon_render
        calls = []
        real = moon_render.render_moon

        def spy(*a, **k):
            calls.append(self.v.zooming())
            return real(*a, **k)
        with mock.patch.object(moon_render, "render_moon", side_effect=spy):
            self.v.zoom_in()                     # while gliding: reuse, no re-render
            while self.v.zooming():
                self.v.repaint()
                QTest.qWait(10)
            QTest.qWait(100)
            self.paint()                         # settled: one sharp re-render at the new size
        self.assertNotIn(True, calls)
        self.assertEqual(len(calls), 1)
        self.assertGreater(self.v._moon_cache[0][0], key[0])

    def test_zoomed_render_is_capped_and_memory_bounded(self):
        from weatherdesk.globe_panel import MAX_RENDER
        self.v.set_zoom(3.0, animate=False)
        self.assertTrue(wait_until(lambda: not self.v._low_res and self.v.image is not None, 3))
        QTest.qWait(50)
        self.assertLessEqual(self.v.image.width(), MAX_RENDER)
        for z in (0.6, 0.8, 1.0, 1.5, 2.0, 3.0):
            self.v.set_zoom(z, animate=False)
            self.v._render_now()
        if G.has_numpy():
            self.assertLessEqual(len(self.v.renderer._grid_cache), 3)

    def test_zoom_hides_card_when_its_place_is_off_screen(self):
        self.w.loc_list.setCurrentRow(0)                      # Auckland
        self.assertTrue(wait_until(lambda: self.v.anim.state().name == "Stopped", 5))
        self.assertTrue(self.v.card.isVisible())
        self.v.set_zoom(3.0, animate=False)
        self.v.set_center(-36.85 + 25, 174.76)                # Auckland now well below the window
        self.assertFalse(self.v.card.isVisible())
        self.v.set_center(-36.85, 174.76)
        self.assertTrue(self.v.card.isVisible())
        # markers still clickable when zoomed
        p = self.v.point_for(-36.85, 174.76)
        self.w.loc_list.setCurrentRow(1)
        self.assertTrue(wait_until(lambda: self.v.anim.state().name == "Stopped", 5))
        self.v.set_center(-36.85, 174.76)
        p = self.v.point_for(-36.85, 174.76)
        QTest.mouseClick(self.v, Qt.MouseButton.LeftButton, pos=p.toPoint())
        self.assertEqual(self.w.settings.selected_location().name, "Auckland")


def G_ZOOM_MAX():
    from weatherdesk.globe_panel import ZOOM_MAX
    return ZOOM_MAX


def G_ZOOM_MIN():
    from weatherdesk.globe_panel import ZOOM_MIN
    return ZOOM_MIN


def tearDownModule():
    print("\n--- sky results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
