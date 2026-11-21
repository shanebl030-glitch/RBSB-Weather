"""Earthquakes in the window (2.5): dots on Earth Flat and Earth Globe, pulsing, hover
and click, the Earthquakes box, notifications (once, across restarts), a notice click
turning the globe, settings, failures. Created By Shane BlackbuRn"""

from __future__ import annotations

import time
import unittest

from helpers import TempEnvTestCase, qapp, wait_until
import quake_fixtures as QF

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest

from rbsb_weather import quakes as Q
from rbsb_weather.main_window import MainWindow
from rbsb_weather.models import Location
from rbsb_weather.scene import AnimationClock

WELLINGTON = Location("Wellington", -41.28664, 174.77557, "New Zealand", "Wellington", "Pacific/Auckland")
LONDON = Location("London", 51.50853, -0.12574, "United Kingdom", "England", "Europe/London")


class QuakeGuiCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.windows = []
        self.usgs_url, self.geonet_url = QF.install(self.server)
        from rbsb_weather import clouds
        clouds.CLOUD_URL = "http://127.0.0.1:9/clouds.jpg"

    def tearDown(self):
        for w in self.windows:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def make(self, places=(WELLINGTON,), settings=None):
        from rbsb_weather.api import OpenMeteoClient
        from rbsb_weather.storage import SettingsStore
        st = SettingsStore()
        s = st.load()
        for p in places:
            s.add_location(p)
        s.alerts_official = False
        s.alerts_own = False
        s.earth_clouds = False
        for k, v in (settings or {}).items():
            setattr(s, k, v)
        st.save(s)
        w = MainWindow(client=OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=3),
                       enable_tray=False,
                       quake_client=Q.QuakeClient(usgs_url=self.usgs_url, geonet_url=self.geonet_url, timeout=5))
        w.open_url = lambda u: self.opened.append(u) or True
        self.opened = []
        self.windows.append(w)
        w.resize(1100, 800)
        w.show()
        if w._quakes_wanted():
            self.assertTrue(wait_until(lambda: w.quake_store.checked > 0 and not w._quakes_busy, 10))
        QTest.qWait(50)
        return w


class DisplayTest(QuakeGuiCase):
    def test_dots_on_both_earth_tabs(self):
        w = self.make()
        flat = w.earth_panel.map
        self.assertEqual(len(flat.quake_layer.quakes), 5)                 # past day, M2.5+
        self.assertEqual(w.earth_panel.quakes_box.text(), "Earthquakes (5)")
        w.tabs.setCurrentWidget(w.earth_panel)
        self.assertTrue(wait_until(lambda: flat.image is not None, 20))
        QTest.qWait(200)
        flat.quake_layer.repaint()
        self.assertEqual(len(flat.quake_layer.drawn), 5)                  # every quake is on the flat map
        # two quakes in the last hour pulse, so the overlay is animated
        self.assertEqual(flat.quake_layer.pulsing, 2)
        self.assertIn(flat.quake_layer, AnimationClock.instance().visible_targets())
        # hover and click the Japan quake
        jp = next(q for q in flat.quake_layer.quakes if q.mag == 7.3)
        pt = flat.point_for(jp.lat, jp.lon)
        self.assertIn("M7.3", flat._quake_tip(pt))
        QTest.mouseClick(flat, Qt.MouseButton.LeftButton, pos=QPoint(int(pt.x()), int(pt.y())))
        self.assertTrue(flat.quake_card.isVisible())
        self.assertEqual(flat.quake_card.title.text(), "M7.3 earthquake")
        self.assertIn("km from Wellington", flat.quake_card.lines.text())
        self.assertIn("tsunami advice", flat.quake_card.lines.text())
        flat.quake_card.link.linkActivated.emit(jp.url)
        self.assertEqual(self.opened, [jp.url])
        # a click on empty sea hides it
        QTest.mouseClick(flat, Qt.MouseButton.LeftButton, pos=QPoint(int(flat.map_rect().left() + 5),
                                                                     int(flat.map_rect().bottom() - 5)))
        self.assertFalse(flat.quake_card.isVisible())

    def test_globe_hides_the_far_side(self):
        w = self.make()
        g = w.globe_panel.view
        w.tabs.setCurrentWidget(w.globe_panel)
        self.assertTrue(wait_until(lambda: g.image is not None, 20))
        g.set_center(-40, 175)                                  # facing New Zealand
        QTest.qWait(100)
        g.quake_layer.repaint()
        ids = {i for i, _ in g.quake_layer.drawn}
        self.assertIn("geonet:2026p881001", ids)                # Seddon: in view
        self.assertNotIn("usgs:ci4012", ids)                    # California: round the back
        self.assertIsNone(g.quake_layer.quake_at(QPointF(5, 5)))

    def test_box_and_settings(self):
        w = self.make()
        w.globe_panel.quakes_box.setChecked(False)
        self.assertFalse(w.settings.quakes_show)
        self.assertFalse(w.earth_panel.quakes_box.isChecked())           # both tabs follow
        self.assertFalse(w.earth_panel.map.quake_layer.isVisibleTo(w.earth_panel.map))
        w.earth_panel.quakes_box.setChecked(True)
        self.assertTrue(w.globe_panel.view.quake_layer.isVisibleTo(w.globe_panel.view))
        w.show_quake_settings()
        dlg = w._quakes_dialog
        dlg.period.setCurrentIndex(1)                       # past week
        dlg.min_mag.setCurrentIndex(1)                      # 4.5+
        dlg.interval.setCurrentIndex(2)
        dlg._ok()
        self.assertEqual((w.settings.quakes_period, w.settings.quakes_min_mag), ("week", 4.5))
        self.assertEqual(w.quake_timer.interval(), 30 * 60_000)
        self.assertTrue(wait_until(lambda: "/usgs/2.5_week" in self.server.quake_hits["usgs"]
                                   or "/usgs/4.5_week" in self.server.quake_hits["usgs"], 10))
        self.assertTrue(wait_until(lambda: [q.mag for q in w.earth_panel.map.quake_layer.quakes] == [4.8, 5.3, 7.3], 10))
        from rbsb_weather.storage import SettingsStore
        self.assertEqual(SettingsStore().load().quakes_period, "week")

    def test_everything_off_means_no_downloads(self):
        w = self.make(settings={"quakes_show": False, "quakes_notify_near": False, "quakes_notify_major": False})
        w.check_quakes()
        QTest.qWait(300)
        self.assertEqual(self.server.quake_hits["usgs"], [])


class NotifyTest(QuakeGuiCase):
    def test_notified_once_even_after_a_restart(self):
        w = self.make((WELLINGTON, LONDON))
        self.assertEqual(len(w.quake_notices), 1)
        title, body = w.quake_notices[0]
        self.assertEqual(title, "M7.3 earthquake: 90 km E of Ishinomaki, Japan")
        self.assertIn("and 1 more", body)
        w.check_quakes()
        self.assertTrue(wait_until(lambda: not w._quakes_busy, 10))
        QTest.qWait(50)
        self.assertEqual(len(w.quake_notices), 1)
        w2 = self.make((WELLINGTON, LONDON))
        self.assertEqual(w2.quake_notices, [])

    def test_notice_click_turns_the_globe_to_the_quake(self):
        w = self.make(settings={"quakes_notify_major": False})
        self.assertRegex(w.quake_notices[0][0], r"M5\.3 earthquake \d+ km from Wellington")
        w._tray_click = "quake"
        w._on_tray_message_clicked()
        self.assertIs(w.tabs.currentWidget(), w.globe_panel)
        g = w.globe_panel.view
        self.assertTrue(wait_until(lambda: g.quake_card.isVisible(), 5))
        self.assertEqual(g.quake_card.quake.id, "geonet:2026p881001")
        self.assertAlmostEqual(g.c_lat, -41.7, delta=0.5)

    def test_failing_feed_keeps_the_dots(self):
        w = self.make()
        n = len(w.earth_panel.map.quake_layer.quakes)
        self.server.quake_mode["usgs"] = "http500"
        self.server.quake_mode["geonet"] = "http500"
        w.check_quakes()
        self.assertTrue(wait_until(lambda: not w._quakes_busy and w.quake_store.errors, 10))
        self.assertEqual(len(w.earth_panel.map.quake_layer.quakes), n)


if __name__ == "__main__":
    unittest.main()


class LayoutTest(unittest.TestCase):
    def test_earth_tabs_dont_widen_the_window(self):
        """The Earthquakes box must not push the window's minimum width up (the legend wraps)."""
        qapp()
        from rbsb_weather.earth_panel import EarthPanel
        from rbsb_weather.globe_panel import GlobePanel
        for cls in (EarthPanel, GlobePanel):
            with self.subTest(cls=cls.__name__):
                self.assertLess(cls().minimumSizeHint().width(), 700)
