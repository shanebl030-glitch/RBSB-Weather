"""Earth tab tests: sun position, day/night compositing, map geometry, and the
location card (local time, day/twilight/night, temperature, animated icon)."""

from __future__ import annotations

import datetime as dt
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest

from rbsb_weather import earth as E

REF = json.loads(Path(__file__).with_name("earth_reference.json").read_text())
UTC = dt.timezone.utc
REPORT: list[str] = []
LONDON = dict(name="London", latitude=51.5072, longitude=-0.1276, country="United Kingdom",
              admin1="England", timezone="Europe/London")
NEW_YORK = dict(name="New York", latitude=40.7128, longitude=-74.006, country="United States",
                admin1="New York", timezone="America/New_York")


def _t(s):
    return dt.datetime.fromisoformat(s)


class TestSunGeometry(unittest.TestCase):
    def test_subsolar_point_matches_reference(self):
        wl = wo = 0.0
        for t, lat_ref, lon_ref in REF["subsolar"]:
            lat, lon = E.subsolar_point(_t(t))
            wl = max(wl, abs(lat - lat_ref))
            wo = max(wo, abs(((lon - lon_ref + 180) % 360) - 180))
        REPORT.append(f"subsolar point worst vs PyEphem: lat {wl * 60:.2f}', lon {wo * 60:.2f}'")
        self.assertLess(wl, 0.05)
        self.assertLess(wo, 0.05)

    def test_sun_elevation_matches_reference(self):
        worst = 0.0
        for name, lat, lon, t, alt in REF["sun_alt"]:
            worst = max(worst, abs(E.solar_elevation(_t(t), lat, lon) - alt))
        REPORT.append(f"sun elevation worst vs PyEphem: {worst:.3f} deg over {len(REF['sun_alt'])} samples")
        self.assertLess(worst, 0.1)

    def test_equinox_and_solstices(self):
        self.assertAlmostEqual(E.subsolar_point(dt.datetime(2026, 3, 20, 14, 46, tzinfo=UTC))[0], 0.0, delta=0.05)
        self.assertAlmostEqual(E.subsolar_point(dt.datetime(2026, 6, 21, 8, 24, tzinfo=UTC))[0], 23.44, delta=0.05)
        self.assertAlmostEqual(E.subsolar_point(dt.datetime(2026, 12, 21, 20, 50, tzinfo=UTC))[0], -23.44, delta=0.05)
        # around 12:00 UTC the Sun is overhead near Greenwich (within the equation of time)
        self.assertLess(abs(E.subsolar_point(dt.datetime(2026, 11, 15, 12, 0, tzinfo=UTC))[1]), 5)

    def test_day_states(self):
        self.assertEqual(E.day_state(30), "Day")
        self.assertEqual(E.day_state(-0.5), "Day")          # Sun's edge still above the horizon
        self.assertEqual(E.day_state(-3), "Twilight")
        self.assertEqual(E.day_state(-12), "Night")
        noon = dt.datetime(2026, 11, 15, 0, 15, tzinfo=UTC)   # 13:15 NZDT
        self.assertEqual(E.day_state(E.solar_elevation(noon, -36.85, 174.76)), "Day")
        self.assertEqual(E.day_state(E.solar_elevation(noon, 51.51, -0.13)), "Night")

    def test_map_projection(self):
        x, y = E.to_map_xy(-36.85, 174.76, 3600, 1800)
        self.assertAlmostEqual(x, 3547.6, delta=0.1)
        self.assertAlmostEqual(y, 1268.5, delta=0.1)
        lat, lon = E.from_map_xy(x, y, 3600, 1800)
        self.assertAlmostEqual(lat, -36.85, places=6)
        self.assertAlmostEqual(lon, 174.76, places=6)
        self.assertAlmostEqual(E.to_map_xy(0, 190, 360, 180)[0], E.to_map_xy(0, -170, 360, 180)[0])


class TestCompositing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_masks_day_at_subsolar_night_at_antipode(self):
        t = dt.datetime(2026, 11, 15, 0, 15, tzinfo=UTC)
        day, shade = E.masks(t, 360, 180)
        lat, lon = E.subsolar_point(t)
        at = lambda la, lo: day[int(E.to_map_xy(la, lo, 360, 180)[1]) * 360 + int(E.to_map_xy(la, lo, 360, 180)[0]) % 360]
        self.assertEqual(at(lat, lon), 255)
        self.assertEqual(at(-lat, lon + 180), 0)
        self.assertEqual(len(day), 360 * 180)
        self.assertEqual(len(shade), 360 * 180)
        self.assertTrue(any(0 < v < 255 for v in day))             # a soft twilight band exists

    def test_composite_uses_day_and_night_maps(self):
        t = dt.datetime(2026, 11, 15, 0, 15, tzinfo=UTC)
        t0 = time.perf_counter()
        img = E.compose_day_night(t)
        el = time.perf_counter() - t0
        REPORT.append(f"day/night composite {img.width()}x{img.height()}: {el * 1000:.0f} ms")
        self.assertLess(el, 3.0)
        day = QImage(str(E.DAY_FILE)).convertToFormat(QImage.Format.Format_ARGB32)
        night = QImage(str(E.NIGHT_FILE)).convertToFormat(QImage.Format.Format_ARGB32)
        self.assertEqual(img.size(), day.size())
        W, H = img.width(), img.height()
        lat, lon = E.subsolar_point(t)
        for (la, lo), ref in (((lat, lon), day), ((-lat, lon + 180), night), ((-20, -60), night)):
            x, y = (int(v) for v in E.to_map_xy(la, lo, W, H))
            a, b = img.pixelColor(x, y), ref.pixelColor(x, y)
            self.assertLess(abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()), 30,
                            f"pixel at {la:.0f},{lo:.0f}")

    def test_missing_texture_raises(self):
        with mock.patch.object(E, "DAY_FILE", Path("/nonexistent/day.jpg")), mock.patch.dict(E._tex, clear=True):
            with self.assertRaises(E.EarthTextureError):
                E.compose_day_night(dt.datetime.now(UTC))


class TestEarthTab(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        from rbsb_weather.main_window import MainWindow
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
        from rbsb_weather.models import Location
        self.w.add_location(Location.from_dict(d))
        self.assertTrue(wait_until(lambda: not self.w._pending))

    def open_tab(self):
        self.w.tabs.setCurrentWidget(self.w.earth_panel)
        self.assertTrue(wait_until(lambda: self.w.earth_panel.map.image is not None, 20))
        QTest.qWait(50)

    def test_map_drawn_with_markers_and_card(self):
        self.add(LONDON)
        self.add(PLACES[0])
        self.open_tab()
        m = self.w.earth_panel.map
        self.assertEqual([x.name for x in m.markers], ["London", "Auckland"])
        self.assertTrue(m.card.isVisible())
        self.assertEqual(m.card.name.text(), "Auckland")
        self.assertRegex(m.card.time.text(), r"^\w{3} \d\d:\d\d +NZ(DT|ST)$")
        self.assertRegex(m.card.state.text(), r"^(☀ Day|◐ Twilight|☾ Night) · sun [+-]\d+°$")
        self.assertRegex(m.card.temp.text(), r"°C$")
        self.assertEqual(m.card.icon.code, self.w.forecasts[self.place(0).key].current.weather_code)
        self.assertTrue(m.pulse.isVisible())
        self.assertIn("The Sun is overhead", self.w.earth_panel.info.text())
        self.assertTrue(self.w.earth_panel.clock.isActive())

    def test_selecting_in_saved_locations_moves_the_card(self):
        self.add(LONDON)
        self.add(PLACES[0])
        self.open_tab()
        m = self.w.earth_panel.map
        self.w.loc_list.setCurrentRow(0)                 # London
        self.assertEqual(m.card.name.text(), "London")
        self.assertRegex(m.card.time.text(), r"(GMT|BST)$")
        p = m.point_for(51.5072, -0.1276)
        self.assertLess(abs(m.pulse.geometry().center().x() - p.x()), 2)
        self.assertLess(abs(m.pulse.geometry().center().y() - p.y()), 2)

    def test_clicking_a_marker_selects_that_location(self):
        self.add(LONDON)
        self.add(NEW_YORK)
        self.open_tab()
        m = self.w.earth_panel.map
        p = m.point_for(51.5072, -0.1276)
        QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=p.toPoint())
        self.assertEqual(self.w.settings.selected_location().name, "London")
        self.assertEqual(self.w.loc_list.currentItem().text().split()[-2], "London")
        self.assertEqual(m.card.name.text(), "London")
        QTest.mouseClick(m, Qt.MouseButton.LeftButton, pos=QPointF(5, 5).toPoint())   # empty spot
        self.assertEqual(self.w.settings.selected_location().name, "London")

    def test_day_twilight_night_at_fixed_times(self):
        self.add(LONDON)
        self.open_tab()
        card, m = self.w.earth_panel.map.card, self.w.earth_panel.map
        for when, state, clock in ((dt.datetime(2026, 11, 15, 12, 0, tzinfo=UTC), "☀ Day", "Sun 12:00"),
                                   (dt.datetime(2026, 11, 15, 16, 45, tzinfo=UTC), "◐ Twilight", "Sun 16:45"),
                                   (dt.datetime(2026, 11, 15, 23, 0, tzinfo=UTC), "☾ Night", "Sun 23:00")):
            m.refresh_card(when)
            self.assertTrue(card.state.text().startswith(state), card.state.text())
            self.assertTrue(card.time.text().startswith(clock), card.time.text())

    def test_units_and_missing_weather(self):
        self.add(PLACES[0])
        self.open_tab()
        card = self.w.earth_panel.map.card
        self.w.set_unit("temp_unit", "F")
        self.assertTrue(card.temp.text().endswith("°F"))
        self.server.mode = "http500"
        from rbsb_weather.models import Location
        self.w.add_location(Location.from_dict(LONDON))
        self.assertTrue(wait_until(lambda: not self.w._pending))
        self.assertEqual(card.name.text(), "London")
        self.assertEqual(card.temp.text(), "–")
        self.assertEqual(card.desc.text(), "no weather yet")
        self.assertFalse(card.icon.isVisible())

    def test_card_avoids_other_markers_and_stays_inside(self):
        self.add(dict(PLACES[0]))
        self.add(dict(name="Wellington", latitude=-41.29, longitude=174.78, country="New Zealand",
                      admin1="Wellington", timezone="Pacific/Auckland"))
        self.add(dict(name="Sydney", latitude=-33.87, longitude=151.21, country="Australia",
                      admin1="New South Wales", timezone="Australia/Sydney"))
        self.w.loc_list.setCurrentRow(0)                 # Auckland
        self.open_tab()
        m = self.w.earth_panel.map
        for size in ((1100, 820), (800, 560)):
            self.w.resize(*size)
            QTest.qWait(60)
            g = m.card.geometry()
            self.assertTrue(m.rect().contains(g), f"card outside map at {size}")
            for name, la, lo in (("Wellington", -41.29, 174.78), ("Sydney", -33.87, 151.21)):
                self.assertFalse(g.contains(m.point_for(la, lo).toPoint()), f"card covers {name} at {size}")

    def test_recompose_only_when_stale_and_clock_stops_when_hidden(self):
        self.add(PLACES[0])
        self.open_tab()
        tok = self.w._earth_token
        self.w.earth_panel.tick()
        self.assertEqual(self.w._earth_token, tok)                      # fresh: no redraw
        self.w.earth_panel.last_compose -= 301
        self.w.earth_panel.tick()
        self.assertEqual(self.w._earth_token, tok + 1)                  # stale: redrawn
        self.w.tabs.setCurrentIndex(0)
        QTest.qWait(30)
        self.assertFalse(self.w.earth_panel.clock.isActive())

    def test_texture_error_shown(self):
        self.add(PLACES[0])
        with mock.patch.object(E, "NIGHT_FILE", Path("/nonexistent/night.jpg")), mock.patch.dict(E._tex, clear=True):
            self.w.tabs.setCurrentWidget(self.w.earth_panel)
            self.assertTrue(wait_until(lambda: "could not be drawn" in self.w.earth_panel.info.text(), 10))
        self.assertIn("could not be drawn", self.w.earth_panel.map.message)

    def test_labels_near_right_edge_drawn_inside(self):
        # Auckland sits at the far right of the map; its label must flip to the left
        self.add(LONDON)
        self.add(PLACES[0])
        self.w.loc_list.setCurrentRow(0)                 # London selected -> Auckland is a plain label
        self.open_tab()
        m = self.w.earth_panel.map
        img = m.grab().toImage()
        r = m.map_rect()
        p = m.point_for(-36.85, 174.76)
        tw = m.fontMetrics().horizontalAdvance("Auckland")
        # some white label pixels must exist to the LEFT of the dot, within the label width
        y0 = int(p.y()) - 6
        found = any(img.pixelColor(x, y).lightness() > 230
                    for x in range(int(p.x() - tw - 6), int(p.x() - 6)) for y in range(y0, y0 + 10))
        self.assertTrue(found)
        self.assertLessEqual(p.x(), r.right())

    def test_credits(self):
        self.assertIn("Solar System Scope (CC BY 4.0)", self.w.earth_panel.credit.text())
        self.assertIn("solarsystemscope.com/textures", self.w.about_html())


def tearDownModule():
    print("\n--- earth results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
