"""2.1.2: the desktop widget shows the weather provider in small text under the place.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import copy
import unittest

from PyQt6.QtTest import QTest

from helpers import TempEnvTestCase, qapp, wait_until


class TestWidgetSource(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        from rbsb_weather.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False)
        self.w.show()
        self.w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: self.w.forecasts, 10))
        self.w.set_desktop_widget(True)
        self.dw = self.w.desktop_widget
        QTest.qWait(100)

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def fc(self):
        return copy.copy(next(iter(self.w.forecasts.values())))

    def test_primary_provider_shown_under_the_place(self):
        self.assertEqual(self.dw.source.text(), "Open-Meteo")
        self.assertTrue(self.dw.source.isVisibleTo(self.dw))
        self.assertEqual(self.dw.source.toolTip(), "Weather from Open-Meteo")
        # under the place, and smaller than it
        self.assertGreater(self.dw.source.y(), self.dw.place.y())
        self.assertLess(self.dw.source.font().pointSizeF(), self.dw.place.font().pointSizeF())
        self.assertIn(self.dw.source, self.dw.scene.avoid_widgets, "the mini forecast keeps clear of it")

    def test_backup_and_saved_copy(self):
        fc = self.fc()
        fc.provider_id, fc.source = "met.no", "MET Norway"
        self.w._update_widget(fc)
        self.assertEqual(self.dw.source.text(), "MET Norway (backup)")
        fc = self.fc()
        fc.from_cache = True
        self.w._update_widget(fc)
        self.assertEqual(self.dw.source.text(), "Open-Meteo · saved copy")

    def test_cleared_with_no_location(self):
        self.w._update_widget(None)
        self.assertEqual(self.dw.source.text(), "")
        self.assertFalse(self.dw.source.isVisibleTo(self.dw))

    def test_fits_every_size(self):
        self.dw.set_source("Weather Underground (backup)")
        for size in ("small", "medium", "large"):
            self.dw.set_size_name(size)
            QTest.qWait(150)
            src, temp = self.dw.source.geometry(), self.dw.temp.geometry()
            self.assertLessEqual(src.right(), self.dw.updated.geometry().left() + 2
                                 if self.dw.updated.isVisible() else self.dw.width(), size)
            self.assertLessEqual(src.bottom(), temp.top() + 2, f"{size}: overlaps the temperature")


if __name__ == "__main__":
    unittest.main()
