"""Automatic updates and the desktop widget's last-updated line.

The weather updates every refresh interval (30 min by default) by the wall clock,
so it catches up after the computer sleeps or the window sits in the tray, and a
failed update is retried after 5 minutes. The desktop widget shows "↻ HH:MM"."""

from __future__ import annotations

import datetime as dt
import time
import unittest

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtTest import QTest

from test_gui import GuiCase

from weatherdesk import main_window as MW

REPORT: list[str] = []


class TestAutoUpdate(GuiCase):
    def setUp(self):
        super().setUp()
        self.w = self.make()
        self.add(self.w, 0)
        self.key = self.place(0).key
        self.w.set_desktop_widget(True)
        self.dw = self.w.desktop_widget

    def tearDown(self):
        self.w.set_desktop_widget(False)
        super().tearDown()

    def fetches(self):
        return self.server.count("/v1/forecast")

    def age(self, seconds):
        """Pretend the shown weather was downloaded `seconds` ago."""
        self.w.forecasts[self.key].fetched_at = time.time() - seconds
        self.w._last_attempt[self.key] = time.time() - seconds

    def test_default_interval_is_30_minutes(self):
        self.assertEqual(self.w.settings.refresh_minutes, 30)
        self.assertEqual(self.w.refresh_timer.interval(), 30 * 60_000)
        self.assertTrue(self.w.refresh_timer.isActive())
        self.assertTrue(self.w.age_timer.isActive())
        self.assertEqual(self.w.age_timer.interval(), 60_000)

    def test_updates_when_30_minutes_old_not_before(self):
        n = self.fetches()
        self.age(28 * 60)
        self.w._check_refresh_due()
        QTest.qWait(200)
        self.assertEqual(self.fetches(), n)                      # 28 min: not yet
        self.age(30 * 60 + 5)
        self.w._check_refresh_due()
        self.assertTrue(wait_until(lambda: self.fetches() == n + 1 and self.key not in self.w._pending))
        self.assertLess(time.time() - self.w.forecasts[self.key].fetched_at, 5)
        self.w._check_refresh_due()                              # fresh again: nothing more
        QTest.qWait(200)
        self.assertEqual(self.fetches(), n + 1)

    def test_catches_up_after_sleep(self):
        """After the laptop sleeps, Qt's interval timer still has most of its 30 min to
        go (it doesn't count time asleep); the wall-clock check updates within a minute."""
        n = self.fetches()
        self.age(3 * 3600)                                       # slept for 3 hours
        self.assertGreater(self.w.refresh_timer.remainingTime(), 25 * 60_000)
        self.w.age_timer.timeout.emit()                          # the next minute tick
        self.assertTrue(wait_until(lambda: self.fetches() == n + 1 and self.key not in self.w._pending))
        self.assertGreater(self.w.refresh_timer.remainingTime(), 29 * 60_000)   # restarted from now

    def test_failed_update_retried_after_5_minutes(self):
        self.server.mode = "http500"
        self.age(31 * 60)
        n = self.fetches()
        self.w._check_refresh_due()
        self.assertTrue(wait_until(lambda: self.key not in self.w._pending and self.w.errors.get(self.key)))
        self.assertEqual(self.fetches(), n + 1)                  # (HTTP errors aren't retried at once)
        for _ in range(3):                                       # minute ticks within 5 min: no hammering
            self.w._check_refresh_due()
        QTest.qWait(200)
        self.assertEqual(self.fetches(), n + 1)
        self.assertTrue(self.dw.updated_warn)
        self.assertIn("last update failed", self.dw.updated.toolTip())
        self.server.mode = "ok"
        self.w._last_attempt[self.key] = time.time() - MW.RETRY_AFTER_FAIL_S - 1
        self.w._check_refresh_due()
        self.assertTrue(wait_until(lambda: self.key not in self.w._pending and not self.w.errors.get(self.key)))
        self.assertFalse(self.dw.updated_warn)

    def test_off_means_off(self):
        self.w.set_refresh_minutes(0)
        n = self.fetches()
        self.age(5 * 3600)
        self.w._check_refresh_due()
        QTest.qWait(200)
        self.assertEqual(self.fetches(), n)

    def test_other_intervals_follow_the_setting(self):
        self.w.set_refresh_minutes(60)
        n = self.fetches()
        self.age(45 * 60)
        self.w._check_refresh_due()
        QTest.qWait(200)
        self.assertEqual(self.fetches(), n)
        self.age(61 * 60)
        self.w._check_refresh_due()
        self.assertTrue(wait_until(lambda: self.fetches() == n + 1))


class TestWidgetUpdatedLine(GuiCase):
    def setUp(self):
        super().setUp()
        self.w = self.make()
        self.w.set_desktop_widget(True)
        self.dw = self.w.desktop_widget

    def tearDown(self):
        self.w.set_desktop_widget(False)
        super().tearDown()

    def test_shows_time_of_last_update(self):
        self.add(self.w, 0)
        fc = self.w.forecasts[self.place(0).key]
        stamp = dt.datetime.fromtimestamp(fc.fetched_at).strftime("%H:%M")
        self.assertEqual(self.dw.updated.text(), f"↻ {stamp}")
        self.assertTrue(self.dw.updated.isVisible())
        self.assertIn(f"Weather updated at {stamp}", self.dw.updated.toolTip())
        self.assertIn("updates every 30 min", self.dw.updated.toolTip())
        self.assertFalse(self.dw.updated_warn)
        # the line fits inside the widget at every size, top right, beside the place name
        for size in ("small", "medium", "large"):
            self.dw.set_size_name(size)
            QTest.qWait(30)
            g = self.dw.updated.geometry()
            self.assertTrue(self.dw.rect().contains(g), size)
            self.assertFalse(g.intersects(self.dw.place.geometry()), size)
            # top right: in the top quarter, against the right edge
            self.assertLess(g.top(), self.dw.height() * 0.25, size)
            self.assertGreater(g.right(), self.dw.width() - 30, size)
            self.assertGreaterEqual(g.width(), self.dw.updated.sizeHint().width() - 1, size)
        REPORT.append(f"widget line: '{self.dw.updated.text()}'")

    def test_updating_and_old_data(self):
        self.add(self.w, 0)
        key = self.place(0).key
        self.server.delay = 0.6
        self.w.refresh_selected(force=True)
        self.assertIn("updating…", self.dw.updated.text())
        self.assertTrue(wait_until(lambda: key not in self.w._pending))
        self.server.delay = 0
        self.assertNotIn("updating", self.dw.updated.text())
        self.w.forecasts[key].fetched_at = time.time() - 2 * 3600       # well past 2 intervals
        self.w._update_status()
        self.assertTrue(self.dw.updated_warn)
        self.assertTrue(self.dw.updated.text().endswith("(2 h ago)"))

    def test_saved_copy_and_empty(self):
        self.assertEqual(self.dw.updated.text(), "")                    # no location yet
        self.add(self.w, 0)
        self.w.forecasts[self.place(0).key].from_cache = True
        self.w._update_status()
        self.assertIn("saved copy", self.dw.updated.toolTip())
        self.assertTrue(self.dw.updated_warn)

    def test_widget_opened_later_shows_line_at_once(self):
        self.w.set_desktop_widget(False)
        self.add(self.w, 0)
        self.w.set_desktop_widget(True)
        self.assertTrue(self.w.desktop_widget.updated.text().startswith("↻ "))


def tearDownModule():
    print("\n--- refresh results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
