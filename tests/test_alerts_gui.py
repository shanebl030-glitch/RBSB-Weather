"""Weather warnings in the window (2.4): banner, badges, Warnings tab, chart and 7-day
tags, desktop widget, tray dot, notifications, muting, settings. Offline: every
warning service is the fake server. Created By Shane BlackbuRn"""

from __future__ import annotations

import time
import unittest

from helpers import TempEnvTestCase, qapp, wait_until
import alert_fixtures as AF

from PyQt6.QtTest import QTest

from rbsb_weather import alerts as A
from rbsb_weather.alerts_ui import BADGE_ROLE
from rbsb_weather.main_window import MainWindow
from rbsb_weather.models import Location

AUCKLAND = Location("Auckland", -36.84853, 174.76349, "New Zealand", "Auckland", "Pacific/Auckland")
WELLINGTON = Location("Wellington", -41.28664, 174.77557, "New Zealand", "Wellington", "Pacific/Auckland")
LONDON = Location("London", 51.50853, -0.12574, "United Kingdom", "England", "Europe/London")
TOKYO = Location("Tokyo", 35.6895, 139.69171, "Japan", "Tokyo", "Asia/Tokyo")
NO_LIMITS = {k: {"on": False, "value": v.value} for k, v in A.DEFAULT_LIMITS.items()}


class AlertGuiCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.windows = []
        base = f"http://127.0.0.1:{self.server.port}"
        self.urls = AF.install(self.server, base)
        # forecasts dated today (the default fake forecast has fixed dates), so warnings and
        # own limits line up with the chart and the 7-day list
        import importlib.util, json
        from helpers import ROOT
        spec = importlib.util.spec_from_file_location("make_screenshots", ROOT / "tools" / "make_screenshots.py")
        shots = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shots)
        self.server.routes["/v1/forecast"] = lambda path, q, h: (
            200, json.dumps(shots.sample(float(q["latitude"]), float(q["longitude"]))).encode(),
            {"Content-Type": "application/json"})

    def tearDown(self):
        for w in self.windows:
            w._quitting = True
            if w.desktop_widget is not None:
                w.set_desktop_widget(False)
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def alert_client(self):
        u = self.urls
        return A.AlertClient(metservice_url=u["metservice"], nws_url=u["nws"], metno_url=u["metno"],
                             meteoalarm_url=u["meteoalarm"], timeout=5)

    def make(self, places=(AUCKLAND,), own_limits=False, settings=None):
        from rbsb_weather.api import OpenMeteoClient
        from rbsb_weather.storage import SettingsStore
        st = SettingsStore()
        s = st.load()
        for p in places:
            s.add_location(p)
        s.selected = places[0].key if places else None
        s.alerts_own = own_limits
        for k, v in (settings or {}).items():
            setattr(s, k, v)
        st.save(s)
        w = MainWindow(client=OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=3),
                       enable_tray=False, alert_client=self.alert_client())
        w.open_url = lambda u: self.opened.append(u) or True
        self.opened = []
        w.beep = lambda: self.beeps.append(1)
        self.beeps = []
        self.windows.append(w)
        w.show()
        if any(A.source_for(p) for p in places):
            self.assertTrue(wait_until(lambda: w.alert_store.checked > 0 and not w._alerts_busy, 10))
        self.assertTrue(wait_until(lambda: all(p.key in w.forecasts and not w.forecasts[p.key].from_cache
                                               for p in places[:1]), 10))
        QTest.qWait(50)
        return w

    def item(self, w, key):
        from PyQt6.QtCore import Qt
        for i in range(w.loc_list.count()):
            if w.loc_list.item(i).data(Qt.ItemDataRole.UserRole) == key:
                return w.loc_list.item(i)


class BannerAndTabTest(AlertGuiCase):
    def test_orange_warning_everywhere_it_should_be(self):
        w = self.make((AUCKLAND, WELLINGTON, TOKYO))
        # the banner at the top of the sky
        self.assertTrue(w.alert_banner.isVisible())
        self.assertIn("Orange Heavy Rain Warning", w.alert_banner.text())
        self.assertIn("MetService", w.alert_banner.text())
        self.assertIn("#f28c28", w.alert_banner.styleSheet())
        # badges in Saved locations: Auckland orange, Wellington watch, Tokyo none
        self.assertEqual(self.item(w, AUCKLAND.key).data(BADGE_ROLE)[0], "ORANGE")
        self.assertEqual(self.item(w, WELLINGTON.key).data(BADGE_ROLE)[0], "WATCH")
        self.assertIsNone(self.item(w, TOKYO.key).data(BADGE_ROLE))
        # the Warnings tab
        idx = w.tabs.indexOf(w.alerts_panel)
        self.assertEqual(idx, 1)
        self.assertEqual(w.tabs.tabText(idx), "⚠ Warnings (1)")
        card = w.alerts_panel.cards[0]
        self.assertEqual(card.title_label.text(), "Orange Heavy Rain Warning")
        self.assertIn("100 to 140 mm", card.rows["Expected"].text())
        self.assertIn("Streams and rivers", card.rows["What to do"].text())
        self.assertIn("MetService", card.rows["Issued by"].text())
        self.assertRegex(card.rows["Forecast"].text(), r"forecast shows \d+\.\d mm of rain over the same hours")
        self.assertIn("MetService", w.alerts_panel.foot.text() + w._coverage_text(AUCKLAND))
        # clicking the banner opens the tab; Open on metservice.com goes to the issuer
        w.tabs.setCurrentIndex(0)
        w.alert_banner.click()
        self.assertIs(w.tabs.currentWidget(), w.alerts_panel)
        self.assertEqual(card.open_btn.text(), "Open on metservice.com")
        card.open_btn.click()
        self.assertEqual(self.opened, ["https://www.metservice.com/warnings/home"])
        card.map_btn.click()
        self.assertIs(w.tabs.currentWidget(), w.earth_panel)
        # the chart shades the warning hours; Today and Tomorrow are tagged
        span = w.chart.alert_span()
        self.assertIsNotNone(span)
        self.assertEqual(span[0], 0)
        self.assertIn("Heavy Rain Warning in force", span[3])
        self.assertIn("ORANGE WARNING", w.day_rows[0][2].text())
        # the desktop widget's warning line and the tray dot
        w.set_desktop_widget(True)
        self.assertIn("Orange Heavy Rain Warning", w.desktop_widget.alert_text())
        self.assertEqual(w.tray_alert_colour(AUCKLAND.key), "#f28c28")

    def test_place_without_a_source(self):
        w = self.make((TOKYO,))
        self.assertFalse(w.alert_banner.isVisible())
        self.assertEqual(w.tabs.tabText(w.tabs.indexOf(w.alerts_panel)), "Warnings")
        self.assertIn("No warnings for Tokyo", w.alerts_panel.empty_label.text())
        self.assertIn("no official warning source for Japan", w.alerts_panel.empty_label.text())

    def test_switching_places(self):
        w = self.make((AUCKLAND, LONDON))
        w.select_location(LONDON.key)
        self.assertTrue(wait_until(lambda: LONDON.key in w.forecasts, 10))
        self.assertIn("Yellow Rain", w.alert_banner.text())
        self.assertIn("MeteoAlarm", w.alert_banner.text())


class NotifyTest(AlertGuiCase):
    def test_notified_once_and_not_again_after_a_restart(self):
        w = self.make((AUCKLAND, WELLINGTON))
        self.assertEqual(len(w.notifications_sent), 1)
        title, body = w.notifications_sent[0]
        self.assertEqual(title, "⚠ 2 weather warnings")
        self.assertIn("Orange Heavy Rain Warning: Auckland", body)
        self.assertIn("Strong Wind Watch: Wellington", body)
        w.check_alerts()
        self.assertTrue(wait_until(lambda: not w._alerts_busy, 10))
        QTest.qWait(50)
        self.assertEqual(len(w.notifications_sent), 1)
        # a new window (a restart) remembers what was already notified
        w2 = self.make((AUCKLAND, WELLINGTON))
        self.assertEqual(w2.notifications_sent, [])

    def test_upgrade_to_red_notifies_and_beeps(self):
        w = self.make((AUCKLAND,), settings={"alerts_beep_red": True})
        self.assertEqual(len(w.notifications_sent), 1)
        self.assertEqual(self.beeps, [])
        path = AF.DATA / "cap_rain_auckland.xml"
        orig = path.read_text()
        try:
            path.write_text(orig.replace("<value>Orange</value>", "<value>Red</value>")
                            .replace("09:30:00+13:00", "10:30:00+13:00"))
            self.server.alert_mode["metservice"] = "ok"
            w.alert_client._cap_cache.clear()
            w.check_alerts()
            self.assertTrue(wait_until(lambda: len(w.notifications_sent) == 2, 10))
        finally:
            path.write_text(orig)
        self.assertIn("Red Heavy Rain Warning", w.notifications_sent[1][0])
        self.assertEqual(self.beeps, [1])
        self.assertIn("#b91c1c", w.alert_banner.styleSheet())

    def test_selected_only_and_notifications_off(self):
        w = self.make((AUCKLAND, WELLINGTON), settings={"alerts_selected_only": True})
        self.assertEqual(w.notifications_sent[0][0], "⚠ Orange Heavy Rain Warning: Auckland")
        w2 = self.make((LONDON,), settings={"alerts_notify": False})
        self.assertEqual(w2.notifications_sent, [])
        self.assertTrue(w2.alert_banner.isVisible())


class SettingsTest(AlertGuiCase):
    def test_mute_and_unmute(self):
        w = self.make((AUCKLAND,))
        a_id = w.alerts_panel.cards[0].alert.id
        w.alerts_panel.cards[0].mute_btn.click()
        self.assertIn(a_id, w.settings.alerts_muted)
        self.assertFalse(w.alert_banner.isVisible())
        self.assertIsNone(self.item(w, AUCKLAND.key).data(BADGE_ROLE))
        self.assertEqual(w.tabs.tabText(w.tabs.indexOf(w.alerts_panel)), "Warnings")
        # still listed, marked muted, with Unmute
        self.assertEqual(w.alerts_panel.cards[0].mute_btn.text(), "Unmute")
        w.alerts_panel.cards[0].mute_btn.click()
        self.assertTrue(w.alert_banner.isVisible())

    def test_level_filter_and_official_off(self):
        w = self.make((AUCKLAND, WELLINGTON))
        w.apply_alert_settings({"alerts_min_level": "red"})
        self.assertFalse(w.alert_banner.isVisible())
        self.assertIsNone(self.item(w, WELLINGTON.key).data(BADGE_ROLE))
        w.apply_alert_settings({"alerts_min_level": "orange"})
        self.assertTrue(w.alert_banner.isVisible())
        self.assertIsNone(self.item(w, WELLINGTON.key).data(BADGE_ROLE))
        w.apply_alert_settings({"alerts_official": False})
        self.assertFalse(w.alert_banner.isVisible())
        self.assertIn("turned off", w._coverage_text(AUCKLAND))
        n = self.server.alert_hits.get("/alerts-metservice/cap/rss", 0)
        w.check_alerts()
        QTest.qWait(200)
        self.assertEqual(self.server.alert_hits.get("/alerts-metservice/cap/rss", 0), n)   # no requests
        w.apply_alert_settings({"alerts_official": True})
        self.assertTrue(wait_until(lambda: w.alert_banner.isVisible(), 10))

    def test_banner_option_off_hides_banner_badges_and_widget_line(self):
        w = self.make((AUCKLAND,), settings={"alerts_banner": False})
        self.assertFalse(w.alert_banner.isVisible())
        self.assertIsNone(self.item(w, AUCKLAND.key).data(BADGE_ROLE))
        self.assertEqual(w.tabs.tabText(w.tabs.indexOf(w.alerts_panel)), "⚠ Warnings (1)")

    def test_settings_saved_and_the_dialog(self):
        w = self.make((AUCKLAND, TOKYO), settings={"wind_unit": "mph"})
        w.show_alerts_settings()
        dlg = w._alerts_dialog
        rows = [[l.text() for l in r] for r in dlg.coverage_labels]
        self.assertEqual(rows[0], ["Auckland", "MetService", "Working"])
        self.assertEqual(rows[1], ["Tokyo", "None available", "Not covered yet"])
        cb, spin = dlg.limit_boxes["gust"]
        self.assertAlmostEqual(spin.value(), 56, delta=0.6)            # 90 km/h shown in mph
        spin.setValue(50)
        dlg.interval.setCurrentIndex(2)
        dlg._ok()
        self.assertAlmostEqual(w.settings.alerts_limits["gust"]["value"], 80.47, delta=0.05)
        self.assertEqual(w.settings.alerts_interval, 60)
        self.assertEqual(w.alert_timer.interval(), 60 * 60_000)
        from rbsb_weather.storage import SettingsStore
        saved = SettingsStore().load()
        self.assertEqual(saved.alerts_interval, 60)
        self.assertAlmostEqual(saved.alerts_limits["gust"]["value"], 80.47, delta=0.05)


class OwnLimitsGuiTest(AlertGuiCase):
    def test_own_limit_shows_and_notifies(self):
        lim = dict(NO_LIMITS)
        lim["heat"] = {"on": True, "value": -50.0}           # any forecast passes this
        w = self.make((TOKYO,), own_limits=True, settings={"alerts_limits": lim})
        self.assertTrue(w.alert_banner.isVisible())
        self.assertIn("My limit: temperature above", w.alert_banner.text())
        self.assertIn("not official", w.alert_banner.text())
        self.assertEqual(self.item(w, TOKYO.key).data(BADGE_ROLE)[0], "MY LIMIT")
        card = w.alerts_panel.cards[0]
        self.assertFalse(card.limits_btn.isHidden())
        self.assertTrue(card.mute_btn.isHidden())              # own limits are changed, not muted
        self.assertFalse(card.alert.official)
        self.assertTrue(any("My limit" in t for t, _ in w.notifications_sent))

    def test_failed_source_keeps_the_last_warnings(self):
        w = self.make((AUCKLAND,))
        self.server.alert_mode["metservice"] = "http500"
        w.check_alerts()
        self.assertTrue(wait_until(lambda: "metservice" in w.alert_store.errors, 10))
        self.assertTrue(w.alert_banner.isVisible())
        self.assertIn("couldn't be read", w._coverage_text(AUCKLAND))
        w.show_alerts_settings()
        self.assertEqual(w._alerts_dialog.coverage_labels[0][2].text(), "Couldn't be read")

    def test_expired_warning_goes(self):
        self.server.alert_expires_h = 0.0005                  # about two seconds
        w = self.make((AUCKLAND,))
        QTest.qWait(2500)
        w.render()
        w._refresh_alert_badges()
        self.assertFalse(w.alert_banner.isVisible())
        self.assertIsNone(self.item(w, AUCKLAND.key).data(BADGE_ROLE))


if __name__ == "__main__":
    unittest.main()
