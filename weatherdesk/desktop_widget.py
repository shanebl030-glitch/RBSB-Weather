"""Floating desktop weather widget: an animated scene with the temperature.

Frameless and draggable. By default it sits below normal windows like a
desktop gadget ("Keep on top" is optional). "Lock position" stops it being
dragged by accident (1.16). Right-click for options,
double-click to open the main window. Its position is remembered; if the
saved spot is no longer on any screen (e.g. a monitor was unplugged), it
moves back onto the primary screen.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QFont, QGuiApplication
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from . import APP_NAME, AUTHOR_CREDIT
from .scene import WeatherScene
from .storage import WIDGET_SIZES


class DesktopWidget(QWidget):
    open_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    hide_requested = pyqtSignal()
    size_changed = pyqtSignal(str)
    on_top_changed = pyqtSignal(bool)
    locked_changed = pyqtSignal(bool)
    moved = pyqtSignal(int, int)

    def __init__(self, size: str = "medium", on_top: bool = False, locked: bool = False):
        super().__init__(None)
        self.size_name = size if size in WIDGET_SIZES else "medium"
        self.on_top = on_top
        self.locked = bool(locked)
        self._drag_from: Optional[QPoint] = None
        self._drag_moved = False
        self.setWindowTitle(f"{APP_NAME} widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._apply_flags()
        self._apply_tooltip()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scene = WeatherScene(self, seed=11, scrim=True, rounded=16)
        self.scene.setMinimumSize(10, 10)
        outer.addWidget(self.scene)
        lay = QVBoxLayout(self.scene)
        lay.setContentsMargins(16, 10, 14, 12)
        self.place = QLabel()
        self.temp = QLabel()
        self.cond = QLabel()
        self.hilo = QLabel()
        self.updated = QLabel()                 # "↻ 19:30" - when the weather was last updated
        self.updated.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top = QHBoxLayout()                     # place on the left, last update top right
        top.addWidget(self.place)
        top.addStretch(1)
        top.addWidget(self.updated)
        lay.addLayout(top)
        lay.addStretch(1)
        lay.addWidget(self.temp)
        lay.addWidget(self.cond)
        lay.addWidget(self.hilo)
        for lbl in (self.place, self.temp, self.cond, self.hilo, self.updated):
            if lbl is not self.updated:
                lbl.setStyleSheet("color: white; background: transparent;")
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.scene.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # the mini forecast (bottom right) keeps clear of this text
        self.scene.avoid_widgets = [self.place, self.temp, self.cond, self.hilo, self.updated]
        self._apply_size()
        self.set_empty()

    # -------------------------------------------------------------- content
    def set_updated(self, text: str, tooltip: str = "", warn: bool = False) -> None:
        """The last-updated line, e.g. "↻ 19:30"; amber when the data is getting old."""
        self.updated.setText(text)
        self.updated.setToolTip(tooltip)
        # a soft dark pill keeps it readable over bright clouds or a sunny sky
        self.updated.setStyleSheet("background: rgba(0,0,0,85); border-radius: 6px; padding: 1px 6px; color: "
                                   + ("#ffd27a;" if warn else "rgba(255,255,255,235);"))
        self.updated.setVisible(bool(text))
        self.updated_warn = warn

    def set_empty(self) -> None:
        self.set_updated("")
        self.scene.set_forecast([], None, "C")
        self.place.setText(APP_NAME)
        self.temp.setText("–")
        self.cond.setText("Add a location in WeatherDesk")
        self.hilo.setText("")

    def set_weather(self, place: str, temp: str, cond: str, hilo: str, conditions) -> None:
        self.place.setText(place)
        self.temp.setText(temp)
        self.cond.setText(cond)
        self.hilo.setText(hilo)
        self.scene.set_conditions(conditions)

    # --------------------------------------------------------------- layout
    def _apply_flags(self) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        flags |= (Qt.WindowType.WindowStaysOnTopHint if self.on_top
                  else Qt.WindowType.WindowStaysOnBottomHint)
        self.setWindowFlags(flags)

    def _apply_size(self) -> None:
        w, h = WIDGET_SIZES[self.size_name]
        self.setFixedSize(w, h)
        base = h / 170.0
        for lbl, pts, bold in ((self.place, 10.5, True), (self.temp, 30, True),
                               (self.cond, 11, False), (self.hilo, 9.5, False),
                               (self.updated, 8.5, False)):
            f = QFont(self.font())
            f.setPointSizeF(max(7.5, pts * base) if lbl is self.updated else pts * base)
            f.setBold(bold)
            lbl.setFont(f)

    def set_size_name(self, name: str) -> None:
        if name in WIDGET_SIZES and name != self.size_name:
            self.size_name = name
            self._apply_size()
            self.size_changed.emit(name)

    def set_on_top(self, on: bool) -> None:
        if bool(on) == self.on_top:
            return
        self.on_top = bool(on)
        was_visible = self.isVisible()
        pos = self.pos()
        self._apply_flags()           # changing flags hides the window
        if was_visible:
            self.move(pos)
            self.show()
        self.on_top_changed.emit(self.on_top)

    def set_locked(self, on: bool) -> None:
        """Lock (or unlock) the widget where it is: no dragging while locked."""
        if bool(on) == self.locked:
            return
        self.locked = bool(on)
        self._drag_from = None                 # a drag in progress ends here
        self._apply_tooltip()
        self.locked_changed.emit(self.locked)

    def _apply_tooltip(self) -> None:
        how = ("position locked (right-click → Lock position to move it)" if self.locked
               else "drag to move")
        self.setToolTip(f"{APP_NAME} – {how}, right-click for options, "
                        f"double-click to open.\n{AUTHOR_CREDIT}")

    def place_at(self, x: Optional[int], y: Optional[int]) -> None:
        """Move to a saved position, or a sensible default if it's off-screen."""
        if x is not None and y is not None:
            pt = QPoint(x + self.width() // 2, y + self.height() // 2)
            if QGuiApplication.screenAt(pt) is not None:
                self.move(x, y)
                return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.move(40, 40)
            return
        g = screen.availableGeometry()
        self.move(g.right() - self.width() - 30, g.top() + 50)

    # ---------------------------------------------------------------- mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self.locked:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_from is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_from)
            self._drag_moved = True
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None and self._drag_moved:
            self.moved.emit(self.x(), self.y())
        self._drag_from = None

    def mouseDoubleClickEvent(self, e):
        self.open_requested.emit()

    def contextMenuEvent(self, e):
        self.build_menu().exec(e.globalPos())

    def build_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Open WeatherDesk", self.open_requested.emit)
        m.addAction("Refresh", self.refresh_requested.emit)
        sub = m.addMenu("Size")
        grp = QActionGroup(m)
        for name in WIDGET_SIZES:
            a = QAction(name.capitalize(), m, checkable=True, checked=(name == self.size_name))
            a.triggered.connect(lambda _=False, n=name: self.set_size_name(n))
            grp.addAction(a)
            sub.addAction(a)
        top = QAction("Keep on top of windows", m, checkable=True, checked=self.on_top)
        top.triggered.connect(self.set_on_top)
        m.addAction(top)
        lock = QAction("Lock position", m, checkable=True, checked=self.locked)
        lock.triggered.connect(self.set_locked)
        m.addAction(lock)
        m.addSeparator()
        m.addAction("Hide widget", self.hide_requested.emit)
        return m
