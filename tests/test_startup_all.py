"""Startup updates every saved location (1.16.0).

The selected location updates at once; the others follow one at a time (STARTUP_STAGGER_MS
apart), a location updated in the last couple of minutes is skipped, and when the network
isn't up yet (as at boot) a failed location is retried on the usual steps, then left.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import time
import unittest
from unittest import mock

from helpers import wait_until

from PyQt6.QtTest import QTest

from test_gui import GuiCase

from weatherdesk import main_window as MW
from weatherdesk.main_window import MainWindow
from weatherdesk.storage import Settings, SettingsStore

REPORT: list[str] = []


class StartupCase(GuiCase):
    N = 4

    def save_locations(self, n=None, startup_update_all=True):
        """A previous session: n saved locations with cached forecasts; the last is selected."""
        w = self.make()
        for i in range(n or self.N):
            self.add(w, i)
        w.set_startup_update_all(startup_update_all)
        w._quitting = True
        w.close()
        self.windows.remove(w)
        w.deleteLater()
        QTest.qWait(30)
        return [self.place(i).key for i in range(n or self.N)]

    def restart(self):
        """Start WeatherDesk again, recording every forecast request it makes."""
        w = MainWindow(client=self.client(), enable_tray=False)
        self.windows.append(w)
        self.calls: list[tuple[float, str]] = []
        real = w.worker.fetch_forecast

        def record(token, loc):
            self.calls.append((time.monotonic(), loc.key))
            real(token, loc)
        w.worker.fetch_forecast = record
        w.show()
        return w

    def keys_called(self):
        return [k for _, k in self.calls]


class TestStartupUpdatesAll(StartupCase):
    def test_every_location_updates_selected_first_then_one_at_a_time(self):
        keys = self.save_locations()
        selected = keys[-1]
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0):
            t0 = time.monotonic()
            w = self.restart()
            self.assertTrue(all(w.forecasts[k].from_cache for k in keys))
            self.assertTrue(wait_until(lambda: len(self.calls) >= self.N and not w._pending, 15))
            took = time.monotonic() - t0
        QTest.qWait(500)
        self.assertEqual(self.keys_called()[0], selected)                    # the one you see, first
        self.assertEqual(sorted(self.keys_called()), sorted(keys))           # each exactly once
        self.assertEqual(self.keys_called()[1:], [k for k in keys if k != selected])   # saved order
        for k in keys:
            self.assertFalse(w.forecasts[k].from_cache, k)                   # fresh, not the saved copy
            self.assertLess(time.time() - w.forecasts[k].fetched_at, 20)
        gaps = [b[0] - a[0] for a, b in zip(self.calls[1:], self.calls[2:])]
        first = self.calls[1][0] - self.calls[0][0]
        self.assertGreaterEqual(first, MW.STARTUP_STAGGER_MS / 1000 - 0.1)
        for g in gaps:
            self.assertGreaterEqual(g, MW.STARTUP_STAGGER_MS / 1000 - 0.1)
        self.assertFalse(w._startup_due or w._startup_tries)
        REPORT.append(f"startup with {self.N} saved locations: all {len(self.calls)} updated in {took:.1f} s; "
                      f"selected first, others {min([first] + gaps):.2f}-{max([first] + gaps):.2f} s apart")

    def test_location_list_and_markers_show_new_weather(self):
        keys = self.save_locations(2)
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 150):
            w = self.restart()
            self.assertTrue(wait_until(lambda: len(self.calls) == 2 and not w._pending, 10))
        other = keys[0]
        self.assertFalse(w.forecasts[other].from_cache)
        # the window still shows the selected place; nothing else was switched
        self.assertEqual(w.settings.selected, keys[-1])

    def test_quick_restart_skips_locations_just_updated(self):
        keys = self.save_locations(3)                 # all fetched seconds ago
        w = self.restart()
        QTest.qWait(MW.STARTUP_STAGGER_MS * 3)
        self.assertEqual(self.keys_called(), [keys[-1]])   # only the selected (as before 1.16)
        self.assertFalse(w._startup_due)

    def test_setting_off_updates_only_the_selected(self):
        keys = self.save_locations(3, startup_update_all=False)
        self.assertFalse(SettingsStore().load().startup_update_all)
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0):
            w = self.restart()
            self.assertFalse(w.act_startup_all.isChecked())
            QTest.qWait(MW.STARTUP_STAGGER_MS * 3)
        self.assertEqual(self.keys_called(), [keys[-1]])

    def test_turning_off_mid_round_stops_it(self):
        keys = self.save_locations()
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 400):
            w = self.restart()
            self.assertTrue(wait_until(lambda: len(self.calls) == 2, 5))
            w.act_startup_all.trigger()                                   # menu: untick
            self.assertFalse(w.settings.startup_update_all)
            QTest.qWait(1500)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(SettingsStore().load().startup_update_all)

    def test_location_removed_before_its_turn_is_skipped(self):
        keys = self.save_locations()
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 300):
            w = self.restart()
            self.assertTrue(wait_until(lambda: w._startup_due, 5))             # the round has begun
            self.assertIn(keys[2], w._startup_due)
            w.settings.remove_location(keys[2])
            self.assertTrue(wait_until(lambda: not w._startup_due and not w._pending, 6))
            QTest.qWait(400)
        self.assertNotIn(keys[2], self.keys_called())
        self.assertEqual(sorted(self.keys_called()), sorted(k for k in keys if k != keys[2]))

    def test_closing_during_the_round_stops_it_cleanly(self):
        self.save_locations()
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 300):
            w = self.restart()
            self.assertTrue(wait_until(lambda: len(self.calls) == 2, 5))
            w._quitting = True
            w.close()
            n = len(self.calls)
            QTest.qWait(1200)
        self.assertEqual(len(self.calls), n)
        self.assertFalse(w.startup_timer.isActive())


class TestBootWithoutNetwork(StartupCase):
    """At boot the network often comes up after WeatherDesk starts."""

    def test_failed_locations_are_retried_and_recover(self):
        keys = self.save_locations()
        others = [k for k in keys if k != keys[-1]]
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 100), \
                mock.patch.object(MW, "RETRY_STEPS_S", (0.4, 0.4, 0.4, 0.4)):
            self.server.mode = "http500"                                   # network not up yet
            w = self.restart()
            self.assertTrue(wait_until(lambda: all(self.keys_called().count(k) >= 2 for k in others), 10))
            self.assertTrue(all(w.forecasts[k].from_cache for k in others))   # saved copies still shown
            self.server.mode = "ok"                                         # network comes up
            self.assertTrue(wait_until(lambda: all(not w.forecasts[k].from_cache for k in keys), 10))
        self.assertFalse(any(w.errors.get(k) for k in others))
        self.assertFalse(w._startup_due or w._startup_tries)
        REPORT.append("boot without network: others retried, all updated once the network was up")

    def test_gives_up_after_the_usual_retries(self):
        keys = self.save_locations(3)
        others = [k for k in keys if k != keys[-1]]
        with mock.patch.object(MW, "STARTUP_FRESH_S", 0), mock.patch.object(MW, "STARTUP_STAGGER_MS", 100), \
                mock.patch.object(MW, "RETRY_STEPS_S", (0.2, 0.2, 0.2, 0.2)):
            self.server.mode = "http500"
            w = self.restart()
            self.assertTrue(wait_until(lambda: w._startup_tries, 5))           # the round has begun
            self.assertTrue(wait_until(lambda: not w._startup_tries and not w._pending, 15))
            QTest.qWait(1000)                                                  # and nothing after it
        for k in others:
            self.assertEqual(self.keys_called().count(k), 1 + 4, k)       # first try + 4 retries
            self.assertTrue(w.forecasts[k].from_cache)                     # saved copy kept on screen
        REPORT.append("network never up: each other location tried 5 times, then left (saved copy shown)")


class TestSetting(unittest.TestCase):
    def test_default_on_and_validated(self):
        self.assertTrue(Settings().startup_update_all)
        self.assertTrue(Settings.from_dict({}).startup_update_all)            # older settings files
        self.assertTrue(Settings.from_dict({"startup_update_all": "no"}).startup_update_all)
        self.assertFalse(Settings.from_dict({"startup_update_all": False}).startup_update_all)
        self.assertIs(Settings.from_dict({"startup_update_all": False}).to_dict()["startup_update_all"], False)


def tearDownModule():
    print("\n--- startup results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
