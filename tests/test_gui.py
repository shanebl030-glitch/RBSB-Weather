"""GUI workflow tests (run headless with QT_QPA_PLATFORM=offscreen)."""

from __future__ import annotations

import json
import time
import unittest

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel

from weatherdesk import AUTHOR_CREDIT
from weatherdesk.main_window import MainWindow, _age_text, _day_label, autostart_path
from weatherdesk.storage import ForecastCache, SettingsStore


class GuiCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def make(self, timeout=3.0, show=True):
        w = MainWindow(client=self.client(timeout), enable_tray=False)
        self.windows.append(w)
        if show:
            w.show()
        QTest.qWait(20)
        return w

    def add(self, w, i=0):
        w.add_location(self.place(i))
        self.assertTrue(wait_until(lambda: self.place(i).key in w.forecasts
                                   and not w.forecasts[self.place(i).key].from_cache
                                   and self.place(i).key not in w._pending))


class TestStartup(GuiCase):
    def test_empty_state(self):
        w = self.make()
        self.assertIn("Welcome", w.place_label.text())
        self.assertFalse(w.remove_btn.isEnabled())
        self.assertFalse(w.act_refresh.isEnabled())
        self.assertEqual(w.chart.point_count(), 0)
        self.assertEqual(self.server.count("/v1/forecast"), 0)

    def test_credit_visible_in_status_bar_about_and_guide(self):
        w = self.make()
        labels = [l.text() for l in w.statusBar().findChildren(QLabel)]
        self.assertIn(AUTHOR_CREDIT, labels)
        self.assertIn(AUTHOR_CREDIT, w.about_html())
        w.show_guide()
        dlg = w._guide_dialog
        from PyQt6.QtWidgets import QTextBrowser
        text = dlg.findChild(QTextBrowser).toPlainText()
        self.assertIn(AUTHOR_CREDIT, text)
        self.assertIn("Saved locations", text)
        dlg.close()

    def test_corrupt_settings_still_starts(self):
        st = SettingsStore()
        st.path.parent.mkdir(parents=True)
        st.path.write_text("\x00\xffgarbage")
        w = self.make()
        QTest.qWait(50)
        self.assertIn("moved", w.statusBar().currentMessage())
        self.assertTrue(list(st.path.parent.glob("settings.json.corrupt-*")))


class TestWorkflow(GuiCase):
    def test_search_pick_and_display(self):
        w = self.make()
        QTest.keyClicks(w.search_edit, "Ham")
        self.assertTrue(wait_until(lambda: w.results.isVisible() and w.results.count() == 2))
        # debounce: three keystrokes -> one request
        self.assertEqual(self.server.count("/v1/search"), 1)
        w.results.setCurrentRow(0)
        QTest.keyClick(w.search_edit, Qt.Key.Key_Return)
        key = self.place(1).key
        self.assertTrue(wait_until(lambda: key in w.forecasts and key not in w._pending))
        self.assertFalse(w.results.isVisible())
        self.assertEqual(w.search_edit.text(), "")
        self.assertIn("Hamilton, Waikato", w.place_label.text())
        self.assertRegex(w.temp_label.text(), r"^-?\d+°C$")
        self.assertEqual(w.desc_label.text(), "Partly cloudy")
        self.assertEqual(w.detail["wind"].text(), "19 km/h SW")
        self.assertEqual(w.detail["sunrise"].text(), "06:00")
        self.assertEqual(w.chart.point_count(), 24)
        self.assertEqual(w.day_rows[0][0].text(), "Today")
        self.assertEqual(w.day_rows[1][0].text(), "Tomorrow")
        self.assertIn("Updated", w.status_label.text())
        self.assertIn("WeatherDesk — Hamilton", w.windowTitle())
        # persisted to disk
        saved = json.loads(SettingsStore().path.read_text())
        self.assertEqual(saved["selected"], key)
        self.assertIsNotNone(ForecastCache().load(self.place(1)))
        self.assertTrue(w.remove_btn.isEnabled())

    def test_chart_starts_at_current_hour(self):
        w = self.make()
        self.add(w)
        self.assertEqual(w.chart._points[0].time, "2026-11-15T10:00")

    def test_search_no_results_and_failure_messages(self):
        w = self.make()
        self.server.mode = "empty"
        QTest.keyClicks(w.search_edit, "Zzz")
        self.assertTrue(wait_until(lambda: "No places found" in w.search_status.text()))
        self.assertFalse(w.results.isVisible())
        self.server.mode = "http500"
        QTest.keyClicks(w.search_edit, "q")
        self.assertTrue(wait_until(lambda: "Search failed" in w.search_status.text()))

    def test_clearing_search_cancels_pending_results(self):
        w = self.make()
        self.server.delay = 0.5
        QTest.keyClicks(w.search_edit, "Auck")
        QTest.qWait(500)                      # debounce fired, request in flight
        w.search_edit.clear(); w._on_search_text("")
        QTest.qWait(900)
        self.assertFalse(w.results.isVisible())

    def test_units_switch_without_refetch(self):
        w = self.make()
        self.add(w)
        n = self.server.count("/v1/forecast")
        c = w.forecasts[self.place(0).key].current
        w.set_unit("temp_unit", "F")
        self.assertEqual(w.temp_label.text(), f"{c.temperature * 9 / 5 + 32:.0f}°F")
        w.set_unit("wind_unit", "m/s")
        self.assertEqual(w.detail["wind"].text(), "5 m/s SW")
        w.set_unit("precip_unit", "in")
        self.assertEqual(w.detail["precip"].text(), "0.01 in")
        self.assertIn("°F", w.loc_list.item(0).text())
        self.assertTrue(w.unit_actions["temp_unit"]["F"].isChecked())
        self.assertEqual(self.server.count("/v1/forecast"), n)
        self.assertEqual(SettingsStore().load().temp_unit, "F")

    def test_switching_locations_uses_fresh_data_without_refetch(self):
        w = self.make()
        self.add(w, 0)
        self.add(w, 3)
        n = self.server.count("/v1/forecast")
        w.loc_list.setCurrentRow(0)
        self.assertIn("Auckland", w.place_label.text())
        QTest.qWait(100)
        self.assertEqual(self.server.count("/v1/forecast"), n)

    def test_remove_location(self):
        w = self.make()
        self.add(w, 0)
        self.add(w, 3)
        cache = ForecastCache()
        self.assertIsNotNone(cache.load(self.place(3)))
        w.remove_selected()
        self.assertIsNone(cache.load(self.place(3)))
        self.assertEqual(w.loc_list.count(), 1)
        self.assertIn("Auckland", w.place_label.text())
        w.remove_selected()
        self.assertIn("Welcome", w.place_label.text())
        self.assertEqual(SettingsStore().load().locations, [])

    def test_reorder(self):
        w = self.make()
        for i in (0, 1, 3):
            self.add(w, i)
        w._move_selected(-1)
        self.assertEqual([l.name for l in w.settings.locations], ["Auckland", "Wellington", "Hamilton"])
        self.assertEqual(w.loc_list.currentItem().data(Qt.ItemDataRole.UserRole), self.place(3).key)
        self.assertEqual([l.name for l in SettingsStore().load().locations],
                         ["Auckland", "Wellington", "Hamilton"])

    def test_duplicate_refresh_is_ignored_while_pending(self):
        w = self.make()
        self.server.delay = 0.4
        w.add_location(self.place(0))
        for _ in range(5):
            w.refresh_selected(force=True)
        self.assertTrue(wait_until(lambda: not w._pending))
        self.assertEqual(self.server.count("/v1/forecast"), 1)

    def test_restart_restores_everything_and_shows_cache_immediately(self):
        w = self.make()
        self.add(w, 0); self.add(w, 3)
        w.set_unit("temp_unit", "F")
        w._quitting = True; w.close()
        self.server.delay = 1.0            # the new window must not wait for the network
        w2 = self.make()
        self.assertEqual([l.name for l in w2.settings.locations], ["Auckland", "Wellington"])
        self.assertIn("Wellington", w2.place_label.text())
        self.assertTrue(w2.temp_label.text().endswith("°F"))
        self.assertIn("saved copy", w2.status_label.text())
        self.assertTrue(wait_until(lambda: not w2._pending, 4))
        self.assertNotIn("saved copy", w2.status_label.text())

    def test_offline_with_cache(self):
        w = self.make()
        self.add(w)
        w._quitting = True; w.close()
        self.server.mode = "http500"
        w2 = self.make()
        self.assertTrue(wait_until(lambda: not w2._pending))
        self.assertRegex(w2.temp_label.text(), r"°C$")
        self.assertIn("Couldn't update", w2.message_label.text())
        self.assertIn("saved copy", w2.status_label.text())
        self.assertIn("Offline", w2.status_label.text())
        # recovers when the network returns
        self.server.mode = "ok"
        w2.refresh_selected(force=True)
        self.assertTrue(wait_until(lambda: not w2._pending))
        self.assertNotIn("Couldn't update", w2.message_label.text())
        self.assertNotIn("Offline", w2.status_label.text())

    def test_offline_without_cache(self):
        self.server.mode = "badjson"
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: not w._pending))
        self.assertEqual(w.desc_label.text(), "No weather data yet.")
        self.assertIn("could not be read", w.message_label.text())
        self.assertEqual(w.chart.point_count(), 0)

    def test_stale_response_ignored(self):
        w = self.make()
        self.add(w)
        key = self.place(0).key
        before = w.forecasts[key]
        from weatherdesk.api import parse_forecast
        from fake_server import make_forecast
        old = parse_forecast(make_forecast(0, 0), self.place(0))
        w._on_forecast_ok(999, old)                       # unknown token
        self.assertIs(w.forecasts[key], before)
        w._on_forecast_failed(999, key, "boom")
        self.assertNotIn(key, w.errors)

    def test_response_for_removed_location_ignored(self):
        w = self.make()
        self.server.delay = 0.4
        w.add_location(self.place(0))
        w.remove_selected()
        QTest.qWait(700)
        self.assertEqual(w.forecasts, {})
        self.assertIsNone(ForecastCache().load(self.place(0)))

    def test_auto_refresh_setting(self):
        w = self.make()
        w.set_refresh_minutes(10)
        self.assertTrue(w.refresh_timer.isActive())
        self.assertEqual(w.refresh_timer.interval(), 600_000)
        w.set_refresh_minutes(0)
        self.assertFalse(w.refresh_timer.isActive())
        w.set_refresh_minutes(7)   # invalid -> ignored
        self.assertEqual(w.settings.refresh_minutes, 0)
        self.assertEqual(SettingsStore().load().refresh_minutes, 0)

    def test_autostart_toggle(self):
        w = self.make()
        w.set_autostart(True)
        self.assertIn("--minimized", autostart_path().read_text())
        self.assertTrue(w.act_autostart.isChecked())
        w.set_autostart(False)
        self.assertFalse(autostart_path().exists())

    def test_close_saves_geometry(self):
        w = self.make()
        w.resize(900, 650)
        w._quitting = True
        w.close()
        self.assertTrue(SettingsStore().load().window_geometry)

    def test_settings_save_failure_reported_not_crash(self):
        w = self.make()
        w.store.path = self.tmp / "missing-dir-file" / "x" / "settings.json"
        (self.tmp / "missing-dir-file").write_text("i am a file, not a dir")
        w.set_unit("temp_unit", "F")
        self.assertIn("Could not save settings", w.statusBar().currentMessage())


class TestHelpers(unittest.TestCase):
    def test_age_text(self):
        self.assertEqual(_age_text(10), "just now")
        self.assertEqual(_age_text(600), "10 min ago")
        self.assertEqual(_age_text(7300), "2 h ago")
        self.assertEqual(_age_text(200000), "2 days ago")
        self.assertEqual(_age_text(-5), "just now")

    def test_day_label(self):
        import datetime as dt
        t = dt.date(2026, 11, 15)
        self.assertEqual(_day_label("2026-11-15", t), "Today")
        self.assertEqual(_day_label("2026-11-16", t), "Tomorrow")
        self.assertEqual(_day_label("2026-11-17", t), "Tue 17 Nov")
        self.assertEqual(_day_label("bad", t), "bad")


if __name__ == "__main__":
    unittest.main()
