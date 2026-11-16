"""Earth Globe tests: orthographic projection, the numpy and pure-Python renderers,
and the Earth Globe tab (markers, card, selection turning, dragging, slow rotation,
one shared day/night image with the flat map)."""

from __future__ import annotations

import math
import random
import time
import unittest
from unittest import mock

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest

from weatherdesk import globe as G

REPORT: list[str] = []
LONDON = dict(name="London", latitude=51.5072, longitude=-0.1276, country="United Kingdom",
              admin1="England", timezone="Europe/London")
NEW_YORK = dict(name="New York", latitude=40.7128, longitude=-74.006, country="United States",
                admin1="New York", timezone="America/New_York")


def source_image():
    """A 360x180 equirectangular test map: red = longitude, green = latitude."""
    qapp()
    img = QImage(360, 180, QImage.Format.Format_RGB32)
    for y in range(180):
        for x in range(360):
            img.setPixelColor(x, y, QColor(int(x * 255 / 359), int(y * 255 / 179), 90))
    return img


class TestProjection(unittest.TestCase):
    def test_centre_and_far_side(self):
        x, y, vis = G.project(51.5, -0.1, 51.5, -0.1)
        self.assertAlmostEqual(x, 0, places=9)
        self.assertAlmostEqual(y, 0, places=9)
        self.assertTrue(vis)
        self.assertFalse(G.project(-51.5, 179.9, 51.5, -0.1)[2])        # antipode hidden
        x, y, vis = G.project(0, 90, 0, 0)                               # on the limb, east
        self.assertAlmostEqual(x, 1, places=9)
        _, y, _ = G.project(90, 0, 0, 0)                                 # north pole at top
        self.assertAlmostEqual(y, 1, places=9)

    def test_round_trip(self):
        rng = random.Random(1)
        worst = 0.0
        for _ in range(3000):
            c_lat, c_lon = rng.uniform(-85, 85), rng.uniform(-180, 180)
            lat, lon = rng.uniform(-89, 89), rng.uniform(-180, 180)
            x, y, vis = G.project(lat, lon, c_lat, c_lon)
            if not vis or math.hypot(x, y) > 0.999:
                continue
            la, lo = G.inverse(x, y, c_lat, c_lon)
            worst = max(worst, abs(la - lat), abs(((lo - lon + 180) % 360) - 180) * math.cos(math.radians(lat)))
        REPORT.append(f"projection round trip worst error: {worst:.2e} deg")
        self.assertLess(worst, 1e-6)
        self.assertIsNone(G.inverse(0.8, 0.8, 0, 0))                     # outside the disc


class TestRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = source_image()

    def render(self, size, c_lat, c_lon, use_numpy):
        r = G.GlobeRenderer()
        self.assertFalse(r.ready)
        r.set_source(self.src)
        self.assertTrue(r.ready)
        return r.render(size, c_lat, c_lon, use_numpy=use_numpy)

    def check_basic(self, use_numpy):
        img = self.render(200, 20, 40, use_numpy)
        self.assertEqual((img.width(), img.height()), (200, 200))
        self.assertEqual(img.pixelColor(2, 2).alpha(), 0)                # outside the disc: transparent
        self.assertEqual(img.pixelColor(197, 197).alpha(), 0)
        c = img.pixelColor(100, 100)                                     # centre = source pixel at (20N, 40E)
        self.assertEqual(c.alpha(), 255)
        exp = self.src.pixelColor(int((40 + 180) / 360 * 360), int((90 - 20) / 180 * 180))
        self.assertLess(abs(c.red() - exp.red()), 6)
        self.assertLess(abs(c.green() - exp.green()), 6)
        # limb darkening: the edge is darker than the middle for the same blue channel
        self.assertLess(img.pixelColor(100, 3).blue() + 0, c.blue() + 1)

    def test_python_renderer(self):
        self.check_basic(False)

    @unittest.skipUnless(G.has_numpy(), "numpy not installed")
    def test_numpy_renderer(self):
        self.check_basic(True)

    @unittest.skipUnless(G.has_numpy(), "numpy not installed")
    def test_numpy_and_python_agree(self):
        worst = 0
        for c in ((0, 0), (51.5, -0.1), (-36.8, 174.7), (80, 120)):
            a = self.render(240, *c, use_numpy=True)
            b = self.render(240, *c, use_numpy=False)
            for y in range(0, 240, 3):
                for x in range(0, 240, 3):
                    pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
                    worst = max(worst, abs(pa.red() - pb.red()), abs(pa.green() - pb.green()),
                                abs(pa.alpha() - pb.alpha()))
        REPORT.append(f"numpy vs pure-Python worst channel difference: {worst}")
        self.assertLessEqual(worst, 2)

    def test_python_path_capped_then_scaled(self):
        img = self.render(G.PY_MAX_SIZE + 200, 0, 0, False)
        self.assertEqual(img.width(), G.PY_MAX_SIZE + 200)

    def test_performance(self):
        r = G.GlobeRenderer()
        r.set_source(self.src)
        t = time.perf_counter()
        r.render(240, 10, 10, use_numpy=False)
        py = (time.perf_counter() - t) * 1000
        REPORT.append(f"pure-Python 240 px render: {py:.0f} ms")
        self.assertLess(py, 1500)
        if G.has_numpy():
            r.render(600, 0, 0, use_numpy=True)            # build the grid cache
            t = time.perf_counter()
            for i in range(5):
                r.render(600, 10, i * 3, use_numpy=True)
            npt = (time.perf_counter() - t) * 1000 / 5
            REPORT.append(f"numpy 600 px render: {npt:.0f} ms per frame")
            self.assertLess(npt, 400)


class TestGlobeTab(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        from weatherdesk.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False)
        self.w.resize(1100, 820)
        self.w.show()

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def add(self, d):
        from weatherdesk.models import Location
        self.w.add_location(Location.from_dict(d))
        self.assertTrue(wait_until(lambda: not self.w._pending))

    def open_tab(self):
        self.w.tabs.setCurrentWidget(self.w.globe_panel)
        self.assertTrue(wait_until(lambda: self.w.globe_panel.view.image is not None, 20))
        self.assertTrue(wait_until(lambda: self.w.globe_panel.view.anim.state().name == "Stopped", 5))
        QTest.qWait(50)

    @property
    def v(self):
        return self.w.globe_panel.view

    def test_tab_names(self):
        names = [self.w.tabs.tabText(i) for i in range(self.w.tabs.count())]
        self.assertIn("🗺 Earth Flat", names)
        self.assertIn("🌐 Earth Globe", names)
        self.assertNotIn("🌍 Earth", names)

    def test_globe_faces_selected_with_card(self):
        self.add(LONDON)
        self.add(PLACES[0])                               # Auckland, selected
        self.open_tab()
        self.assertAlmostEqual(self.v.c_lat, -36.85, delta=0.5)
        self.assertAlmostEqual(self.v.c_lon, 174.76, delta=0.5)
        self.assertTrue(self.v.card.isVisible())
        self.assertEqual(self.v.card.name.text(), "Auckland")
        self.assertRegex(self.v.card.state.text(), r"^(☀ Day|◐ Twilight|☾ Night) · sun [+-]\d+°$")
        self.assertTrue(self.v.pulse.isVisible())
        c = self.v.globe_rect().center()
        self.assertLess(abs(self.v.pulse.geometry().center().x() - c.x()), 2)
        self.assertIsNone(self.v.point_for(51.5072, -0.1276))           # London is round the back
        self.assertIn("The Sun is overhead", self.w.globe_panel.info.text())

    def test_selecting_turns_the_globe(self):
        self.add(LONDON)
        self.add(PLACES[0])
        self.open_tab()
        self.w.loc_list.setCurrentRow(0)                  # London
        self.assertEqual(self.v.card.name.text(), "London")
        # wait for the turn to finish (the last eased frames are already within 0.01 deg,
        # so position alone isn't enough - 1.8.1 fix for a rare timing failure in this test)
        self.assertTrue(wait_until(lambda: self.v.anim.state().name == "Stopped", 5))
        self.assertAlmostEqual(self.v.c_lat, 51.5072, delta=0.01)
        self.assertAlmostEqual(self.v.c_lon, -0.1276, delta=0.01)
        self.assertTrue(self.v.card.isVisible())
        self.assertIsNone(self.v.point_for(-36.85, 174.76))             # Auckland now hidden
        self.assertFalse(self.v._low_res)                               # sharp final frame

    def test_clicking_a_marker_selects(self):
        self.add(LONDON)
        self.add(NEW_YORK)                                # New York selected, London visible
        self.open_tab()
        p = self.v.point_for(51.5072, -0.1276)
        self.assertIsNotNone(p)
        # grabbing the London marker and dragging spins the globe without selecting London
        QTest.mousePress(self.v, Qt.MouseButton.LeftButton, pos=p.toPoint())
        for i in range(1, 6):
            QTest.mouseMove(self.v, (p + QPointF(i * 10, 0)).toPoint())
        QTest.mouseRelease(self.v, Qt.MouseButton.LeftButton, pos=(p + QPointF(50, 0)).toPoint())
        self.assertEqual(self.w.settings.selected_location().name, "New York")
        self.v.set_center(51.5072, -0.1276)
        p = self.v.point_for(51.5072, -0.1276)
        QTest.mouseClick(self.v, Qt.MouseButton.LeftButton, pos=p.toPoint())
        self.assertEqual(self.w.settings.selected_location().name, "London")
        self.assertEqual(self.v.card.name.text(), "London")

    def test_drag_rotates_and_far_side_card_hides(self):
        self.add(PLACES[0])
        self.open_tab()
        lon0 = self.v.c_lon
        c = self.v.globe_rect().center().toPoint()
        QTest.mousePress(self.v, Qt.MouseButton.LeftButton, pos=c)
        for i in range(1, 11):
            QTest.mouseMove(self.v, c + QPointF(i * 20, 0).toPoint())
        QTest.mouseRelease(self.v, Qt.MouseButton.LeftButton, pos=c + QPointF(200, 0).toPoint())
        moved = ((lon0 - self.v.c_lon + 180) % 360) - 180
        REPORT.append(f"200 px drag turned the globe {moved:.0f} deg")
        self.assertGreater(moved, 20)                     # dragging right turns the globe east-to-west
        self.assertFalse(self.v._low_res)
        self.v.set_center(-self.v.c_lat, self.v.c_lon + 180)            # face the other side
        self.assertFalse(self.v.card.isVisible())
        self.assertFalse(self.v.pulse.isVisible())
        self.assertEqual(self.w.settings.selected_location().name, "Auckland")   # drag doesn't select

    def test_one_shared_compose(self):
        self.add(PLACES[0])
        calls = []
        orig = self.w.worker.earth_compose
        with mock.patch.object(self.w.worker, "earth_compose", side_effect=lambda t, *a: (calls.append(t), orig(t, *a))):
            self.w.tabs.setCurrentWidget(self.w.earth_panel)
            self.assertTrue(wait_until(lambda: self.w.earth_panel.map.image is not None, 20))
            self.w.tabs.setCurrentWidget(self.w.globe_panel)
            self.assertTrue(wait_until(lambda: self.v.image is not None, 20))
        self.assertEqual(len(calls), 1, "both tabs should share one day/night image")
        img = self.w.earth_panel.map.image
        self.assertEqual((self.v.renderer._w, self.v.renderer._h), (img.width(), img.height()))
        self.assertEqual(self.w.globe_panel.last_compose, self.w.earth_panel.last_compose)

    def test_spin_runs_only_while_visible(self):
        self.add(PLACES[0])
        self.open_tab()
        if not G.has_numpy():
            self.assertFalse(self.w.globe_panel.spin_box.isEnabled())
            return
        lon0 = self.v.c_lon
        self.w.globe_panel.spin_box.setChecked(True)
        self.assertTrue(self.v.spin_timer.isActive())
        QTest.qWait(600)
        self.assertNotAlmostEqual(self.v.c_lon, lon0, delta=1)
        self.w.tabs.setCurrentIndex(0)
        QTest.qWait(30)
        self.assertFalse(self.v.spin_timer.isActive())
        self.assertFalse(self.w.globe_panel.clock.isActive())
        self.w.tabs.setCurrentWidget(self.w.globe_panel)
        QTest.qWait(30)
        self.assertTrue(self.v.spin_timer.isActive())                   # resumes when shown again
        self.w.globe_panel.spin_box.setChecked(False)
        self.assertFalse(self.v.spin_timer.isActive())
        self.assertFalse(self.v._low_res)

    def test_centre_button_and_python_fallback(self):
        self.add(PLACES[0])
        self.open_tab()
        self.v.set_center(0, 0)
        self.w.globe_panel.centre_btn.click()
        self.assertTrue(wait_until(lambda: abs(self.v.c_lon - 174.76) < 0.5, 5))
        with mock.patch.object(G, "has_numpy", return_value=False), \
                mock.patch("weatherdesk.globe_panel.has_numpy", return_value=False):
            self.v.turn_to(10, 20)                         # no numpy: jumps straight there
            self.assertEqual((self.v.c_lat, self.v.c_lon), (10, 20))

    def test_texture_error_shown(self):
        from pathlib import Path
        from weatherdesk import earth as E
        self.add(PLACES[0])
        with mock.patch.object(E, "NIGHT_FILE", Path("/nonexistent/night.jpg")), mock.patch.dict(E._tex, clear=True):
            self.w.tabs.setCurrentWidget(self.w.globe_panel)
            self.assertTrue(wait_until(lambda: "could not be drawn" in self.w.globe_panel.info.text(), 10))
        self.assertIsNone(self.v.image)
        self.v.repaint()                                   # paints the message without crashing

    def test_credit(self):
        self.assertIn("Solar System Scope (CC BY 4.0)", self.w.globe_panel.credit.text())


def tearDownModule():
    print("\n--- globe results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
