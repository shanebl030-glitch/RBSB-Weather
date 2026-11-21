"""12/24-hour clock option: the formatters, the setting, and every place a clock
time appears (status bar, details, chart, Moon tab, Earth tabs, desktop widget)."""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import unittest

from helpers import PLACES, qapp, wait_until

from PyQt6.QtTest import QTest

from test_gui import GuiCase

from rbsb_weather import units
from rbsb_weather.storage import Settings

H12 = re.compile(r"\b(1[0-2]|[1-9]):[0-5]\d (am|pm)\b")
H24 = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")


class TestFormatters(unittest.TestCase):
    def tearDown(self):
        units.set_time_format("24")

    def test_clock_both_ways(self):
        cases = [((0, 5), "00:05", "12:05 am"), ((9, 30), "09:30", "9:30 am"), ((12, 0), "12:00", "12:00 pm"),
                 ((13, 7), "13:07", "1:07 pm"), ((23, 59), "23:59", "11:59 pm")]
        for (h, m), f24, f12 in cases:
            t = dt.datetime(2026, 11, 16, h, m)
            self.assertEqual(units.fmt_clock(t, fmt="24"), f24)
            self.assertEqual(units.fmt_clock(t, fmt="12"), f12)
            iso = t.strftime("%Y-%m-%dT%H:%M")
            self.assertEqual(units.fmt_iso_clock(iso, fmt="24"), f24)
            self.assertEqual(units.fmt_iso_clock(iso, fmt="12"), f12)
        t = dt.datetime(2026, 11, 16, 19, 30)
        self.assertEqual(units.fmt_clock(t, day=True, fmt="12"), "Mon 7:30 pm")
        self.assertEqual(units.fmt_clock(t, day=True, fmt="24"), "Mon 19:30")
        self.assertEqual(units.fmt_clock(dt.time(6, 1), fmt="12"), "6:01 am")
        self.assertEqual(units.fmt_clock(None), "–")
        self.assertEqual(units.fmt_iso_clock(None), "–")
        self.assertEqual(units.fmt_iso_clock("2026-11-16"), "–")
        self.assertEqual(units.fmt_iso_clock("2026-11-16Tab:cd"), "–")

    def test_chart_labels(self):
        self.assertEqual(units.fmt_hour_label("2026-11-16T00:00", "12"), "12 am")
        self.assertEqual(units.fmt_hour_label("2026-11-16T12:00", "12"), "12 pm")
        self.assertEqual(units.fmt_hour_label("2026-11-16T19:00", "12"), "7 pm")
        self.assertEqual(units.fmt_hour_label("2026-11-16T19:30", "12"), "7:30 pm")
        self.assertEqual(units.fmt_hour_label("2026-11-16T19:00", "24"), "19:00")

    def test_global_switch_and_bad_values(self):
        units.set_time_format("12")
        self.assertEqual(units.fmt_clock(dt.time(15, 0)), "3:00 pm")
        units.set_time_format("bogus")                     # ignored
        self.assertEqual(units.time_format(), "12")
        units.set_time_format("24")
        self.assertEqual(units.fmt_clock(dt.time(15, 0)), "15:00")

    def test_setting_saved_and_validated(self):
        self.assertEqual(Settings().time_format, "24")      # default unchanged for existing users
        self.assertEqual(Settings.from_dict({"time_format": "12"}).time_format, "12")
        self.assertEqual(Settings.from_dict({"time_format": 12}).time_format, "24")
        self.assertEqual(Settings.from_dict({"time_format": "13"}).time_format, "24")
        self.assertEqual(Settings.from_dict(Settings(time_format="12").to_dict()).time_format, "12")


class TestTimeFormatInApp(GuiCase):
    def tearDown(self):
        units.set_time_format("24")
        super().tearDown()

    def test_switching_updates_every_view(self):
        w = self.make()
        self.add(w, 0)
        w.set_desktop_widget(True)
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        w.tabs.setCurrentWidget(w.earth_panel)
        self.assertTrue(wait_until(lambda: w.earth_panel.map.image is not None, 20))
        n = self.server.count("/v1/forecast")

        def texts():
            moon = [l.text() for l in w.moon_panel.findChildren(type(w.status_label))]
            return {"status": w.status_label.text(), "sunrise": w.detail["sunrise"].text(),
                    "hero": w.message_label.text(),
                    "card": w.earth_panel.map.card.time.text(), "info": w.earth_panel.info.text(),
                    "widget": w.desktop_widget.updated.text(), "moon": " | ".join(moon)}
        before = texts()
        self.assertRegex(before["sunrise"], r"^\d\d:\d\d$")
        self.assertIsNone(H12.search(" ".join(before.values())))
        w.unit_actions["time_format"]["12"].trigger()
        after = texts()
        self.assertEqual(w.settings.time_format, "12")
        self.assertEqual(json.loads(w.store.path.read_text())["time_format"], "12")
        self.assertRegex(after["sunrise"], r"^(1[0-2]|[1-9]):\d\d (am|pm)$")
        self.assertRegex(after["hero"], r"^Local time at location: (1[0-2]|[1-9]):\d\d (am|pm)$")
        self.assertRegex(after["status"], r"Updated (1[0-2]|[1-9]):\d\d (am|pm)")
        self.assertRegex(after["card"], r"^\w{3} (1[0-2]|[1-9]):\d\d (am|pm)")
        self.assertRegex(after["info"], r"as of (1[0-2]|[1-9]):\d\d (am|pm)")
        self.assertRegex(after["widget"], r"^↻ (1[0-2]|[1-9]):\d\d (am|pm)")
        self.assertRegex(after["moon"], r"(1[0-2]|[1-9]):\d\d (am|pm)")
        bare = [m.group(0) for m in re.finditer(r"\b\d{1,2}:\d\d\b(?! (am|pm))", after["moon"])]
        self.assertEqual(bare, [], "every Moon tab time should be 12-hour")
        self.assertEqual(self.server.count("/v1/forecast"), n)          # no re-download
        self.assertTrue(w.unit_actions["time_format"]["12"].isChecked())
        # the 24-hour chart's hour labels follow too
        from unittest import mock
        from rbsb_weather import widgets
        seen = []
        real = units.fmt_hour_label
        with mock.patch.object(widgets.units, "fmt_hour_label", side_effect=lambda iso: seen.append(real(iso)) or seen[-1]):
            w.chart.grab()                   # paints even though another tab is showing
        self.assertTrue(seen and all(re.search(r"(am|pm)$", x) for x in seen), seen[:5])
        # back to 24-hour
        w.unit_actions["time_format"]["24"].trigger()
        again = texts()
        self.assertRegex(again["sunrise"], r"^\d\d:\d\d$")
        self.assertIsNone(H12.search(" ".join(again.values())))
        w.set_desktop_widget(False)

    def test_choice_remembered_after_restart(self):
        w = self.make()
        self.add(w, 0)
        w.set_unit("time_format", "12")
        w._quitting = True
        w.close()
        units.set_time_format("24")                         # as in a fresh process
        w2 = self.make()
        self.assertEqual(w2.settings.time_format, "12")
        self.assertEqual(units.time_format(), "12")
        self.assertTrue(w2.unit_actions["time_format"]["12"].isChecked())
        self.assertTrue(wait_until(lambda: self.place(0).key in w2.forecasts))
        self.assertRegex(w2.detail["sunrise"].text(), r"(am|pm)$")


if __name__ == "__main__":
    unittest.main()
