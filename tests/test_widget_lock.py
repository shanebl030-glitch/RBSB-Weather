"""Desktop widget: Lock position (1.16.0).

A locked widget can't be dragged by accident; right-click and double-click still work,
the lock is saved, and an off-screen locked position is still brought back on screen.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import unittest

from helpers import TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from rbsb_weather.desktop_widget import DesktopWidget
from rbsb_weather.storage import Settings, SettingsStore


def _send(w, kind, glob: QPoint, button, buttons):
    """Send a mouse event at a fixed SCREEN position, as a real mouse would: the
    pointer stays put on screen while the widget moves under it."""
    local = w.mapFromGlobal(glob)
    ev = QMouseEvent(kind, QPointF(local), QPointF(glob), button, buttons,
                     Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(w, ev)


def drag(w, dx: int, dy: int) -> None:
    """Press, move in steps and release the left button, like a real drag."""
    L, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    start = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    _send(w, QEvent.Type.MouseButtonPress, start, L, L)
    for i in range(1, 6):
        _send(w, QEvent.Type.MouseMove, start + QPoint(dx * i // 5, dy * i // 5), none, L)
    _send(w, QEvent.Type.MouseButtonRelease, start + QPoint(dx, dy), L, none)


class TestWidgetLock(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        self.wins = []

    def tearDown(self):
        for w in self.wins:
            w._quitting = True
            w.close()
            w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def make(self):
        from rbsb_weather.main_window import MainWindow
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        self.wins.append(w)
        return w

    def widget(self, w):
        w.set_desktop_widget(True)
        dw = w.desktop_widget
        dw.move(300, 200)
        QTest.qWait(30)
        return dw

    def test_unlocked_widget_drags_as_before(self):
        w = self.make()
        dw = self.widget(w)
        self.assertFalse(dw.locked)
        before = dw.pos()
        drag(dw, 80, 40)
        self.assertEqual(dw.pos(), before + QPoint(80, 40))
        st = SettingsStore().load()
        self.assertEqual((st.widget_x, st.widget_y), (dw.x(), dw.y()))

    def test_locked_widget_does_not_move(self):
        w = self.make()
        dw = self.widget(w)
        dw.set_locked(True)
        before = dw.pos()
        drag(dw, 120, 60)
        self.assertEqual(dw.pos(), before)
        st = SettingsStore().load()
        self.assertTrue(st.widget_locked)
        self.assertEqual((st.widget_x, st.widget_y), (before.x(), before.y()))   # locked where it stood
        self.assertIn("position locked", dw.toolTip())

    def test_unlocking_lets_it_move_again(self):
        w = self.make()
        dw = self.widget(w)
        dw.set_locked(True)
        drag(dw, 50, 50)
        dw.set_locked(False)
        self.assertFalse(SettingsStore().load().widget_locked)
        self.assertIn("drag to move", dw.toolTip())
        before = dw.pos()
        drag(dw, 50, 30)
        self.assertEqual(dw.pos(), before + QPoint(50, 30))

    def test_lock_mid_drag_stops_the_drag(self):
        w = self.make()
        dw = self.widget(w)
        L, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
        start = dw.mapToGlobal(QPoint(20, 20))
        _send(dw, QEvent.Type.MouseButtonPress, start, L, L)
        _send(dw, QEvent.Type.MouseMove, start + QPoint(10, 0), none, L)
        pos = dw.pos()
        dw.set_locked(True)
        _send(dw, QEvent.Type.MouseMove, start + QPoint(90, 0), none, L)
        _send(dw, QEvent.Type.MouseButtonRelease, start + QPoint(90, 0), L, none)
        self.assertEqual(dw.pos(), pos)

    def test_menu_item_and_other_actions_still_work_when_locked(self):
        w = self.make()
        dw = self.widget(w)
        acts = {a.text(): a for a in dw.build_menu().actions()}
        self.assertIn("Lock position", acts)
        self.assertTrue(acts["Lock position"].isCheckable())
        self.assertFalse(acts["Lock position"].isChecked())
        acts["Lock position"].trigger()
        self.assertTrue(dw.locked)
        self.assertTrue(SettingsStore().load().widget_locked)
        acts = {a.text(): a for a in dw.build_menu().actions()}
        self.assertTrue(acts["Lock position"].isChecked())
        # double-click still opens the main window; size and on-top still change
        opened = []
        dw.open_requested.connect(lambda: opened.append(1))
        QTest.mouseDClick(dw, Qt.MouseButton.LeftButton)
        self.assertEqual(opened, [1])
        dw.set_size_name("large")
        self.assertEqual(dw.width(), 440)
        dw.set_on_top(True)
        self.assertTrue(dw.isVisible() and dw.locked)

    def test_lock_survives_restart_and_widget_off_on(self):
        w = self.make()
        dw = self.widget(w)
        dw.set_locked(True)
        w.set_desktop_widget(False)
        w.set_desktop_widget(True)
        self.assertTrue(w.desktop_widget.locked)
        self.assertEqual(w.desktop_widget.pos(), QPoint(300, 200))
        w._quitting = True
        w.close()
        w2 = self.make()
        w2.set_desktop_widget(True)
        dw2 = w2.desktop_widget
        self.assertTrue(dw2.locked)
        self.assertEqual(dw2.pos(), QPoint(300, 200))
        drag(dw2, 100, 100)
        self.assertEqual(dw2.pos(), QPoint(300, 200))

    def test_locked_offscreen_position_still_recovered(self):
        st = SettingsStore()
        s = Settings()
        s.desktop_widget, s.widget_locked, s.widget_x, s.widget_y = True, True, 15000, 15000
        st.save(s)
        w = self.make()
        g = QApplication.primaryScreen().availableGeometry()
        self.assertTrue(g.contains(w.desktop_widget.geometry().center()))
        self.assertTrue(w.desktop_widget.locked)

    def test_setting_default_and_validation(self):
        self.assertFalse(Settings().widget_locked)
        self.assertFalse(Settings.from_dict({}).widget_locked)                 # older settings files
        self.assertFalse(Settings.from_dict({"widget_locked": "yes"}).widget_locked)
        self.assertTrue(Settings.from_dict({"widget_locked": True}).widget_locked)
        self.assertFalse(DesktopWidget().locked)


if __name__ == "__main__":
    unittest.main()
