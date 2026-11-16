"""The Earth tab: a live day/night world map with saved locations.

The selected location gets a pulsing marker and a card showing its local time,
whether it's day, twilight or night there (with the Sun's height), its
temperature and an animated weather icon. Clicking a marker on the map selects
that location. The map's day/night blend is recomputed in the background every
few minutes; the card's clock ticks every 15 seconds.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget)

from . import earth as E
from .clouds import CREDIT as CLOUD_CREDIT
from . import units, weather_codes
from .moon import tz_for
from .scene import WeatherIcon, _Animated

RECOMPOSE_S = 300           # refresh the day/night blend every 5 minutes
STATE_SYMBOL = {"Day": "☀", "Twilight": "◐", "Night": "☾"}


@dataclass
class Marker:
    key: str
    name: str
    lat: float
    lon: float
    tz_name: str
    utc_offset: Optional[int] = None
    temp_c: Optional[float] = None
    code: Optional[int] = None
    desc: str = ""


def local_time(m: Marker, now: dt.datetime) -> dt.datetime:
    return now.astimezone(tz_for(m.tz_name, m.utc_offset))


def place_card(cw: int, ch: int, anchor: QPointF, others: list, width: int, height: int) -> tuple[int, int]:
    """Top-left for a card next to `anchor`: tries the four corners around it and picks
    the one covering the fewest `others` (then the closest), kept inside width x height."""
    def clamp(x, y):
        return (max(4, min(x, width - cw - 4)), max(4, min(y, height - ch - 4)))
    p = anchor
    candidates = [clamp(p.x() + 16, p.y() - ch - 10), clamp(p.x() - 16 - cw, p.y() - ch - 10),
                  clamp(p.x() + 16, p.y() + 14), clamp(p.x() - 16 - cw, p.y() + 14)]

    def cost(xy):
        rect = QRectF(xy[0] - 8, xy[1] - 8, cw + 16, ch + 16)
        covers_self = QRectF(xy[0], xy[1], cw, ch).contains(p)
        return (sum(rect.contains(o) for o in others) + (10 if covers_self else 0),
                math.hypot(xy[0] + cw / 2 - p.x(), xy[1] + ch / 2 - p.y()))
    x, y = min(candidates, key=cost)
    return int(x), int(y)


def info_text(when: dt.datetime) -> str:
    slat, slon = E.subsolar_point(when)
    return (f"Day and night as of {units.fmt_clock(when.astimezone())} (your time). "
            f"The Sun is overhead at {abs(slat):.1f}°{'N' if slat >= 0 else 'S'}, "
            f"{abs(slon):.1f}°{'E' if slon >= 0 else 'W'}.")


def draw_label(p: QPainter, pt: QPointF, text: str, right_limit: float) -> None:
    """White label with a soft shadow; flips to the left of the dot near the right edge."""
    tw = p.fontMetrics().horizontalAdvance(text)
    dx = -6 - tw if pt.x() + 6 + tw > right_limit - 2 else 6
    p.setPen(QColor(0, 0, 0, 170))
    p.drawText(pt + QPointF(dx + 1, 5), text)
    p.setPen(QColor(255, 255, 255))
    p.drawText(pt + QPointF(dx, 4), text)


class PulseMarker(_Animated):
    """Small animated pulsing ring for the selected location."""

    update_every = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = QPointF(self.width() / 2, self.height() / 2)
            ph = (self.t * 0.8) % 1.0
            p.setPen(QPen(QColor(255, 220, 90, int(220 * (1 - ph))), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 4 + 12 * ph, 4 + 12 * ph)
            p.setPen(QPen(QColor(20, 20, 20), 1.5))
            p.setBrush(QColor(255, 210, 60))
            p.drawEllipse(c, 4.5, 4.5)
        finally:
            p.end()


class LocationCard(QFrame):
    """Card shown next to the selected location."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("earthCard")
        self.setStyleSheet("#earthCard { background: rgba(10, 14, 28, 215); border: 1px solid "
                           "rgba(255,255,255,70); border-radius: 8px; } QLabel { color: white; "
                           "background: transparent; }")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 7)
        lay.setSpacing(1)
        self.name = QLabel()
        f = QFont(self.font()); f.setBold(True)
        self.name.setFont(f)
        self.time = QLabel()
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.35); f.setBold(True)
        self.time.setFont(f)
        self.state = QLabel()
        row = QHBoxLayout()
        row.setSpacing(6)
        self.icon = WeatherIcon(30, phase=0.2)
        self.temp = QLabel()
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.35); f.setBold(True)
        self.temp.setFont(f)
        self.desc = QLabel()
        row.addWidget(self.icon)
        row.addWidget(self.temp)
        row.addWidget(self.desc)
        row.addStretch(1)
        for w in (self.name, self.time, self.state):
            lay.addWidget(w)
        lay.addLayout(row)

    def show_marker(self, m: Marker, now: dt.datetime, temp_unit: str) -> None:
        lt = local_time(m, now)
        elev = E.solar_elevation(now, m.lat, m.lon)
        state = E.day_state(elev)
        self.name.setText(m.name)
        self.time.setText(units.fmt_clock(lt, day=True) + (f"  {lt.strftime('%Z')}" if lt.strftime("%Z") else ""))
        self.state.setText(f"{STATE_SYMBOL[state]} {state} · sun {elev:+.0f}°")
        self.state.setToolTip("Height of the Sun above (+) or below (−) the horizon there")
        if m.temp_c is not None:
            self.temp.setText(units.fmt_temp(m.temp_c, temp_unit))
            self.icon.set_code(m.code, state == "Day")
            self.icon.show()
            self.desc.setText(m.desc)
        else:
            self.temp.setText("–")
            self.icon.set_code(None)
            self.icon.hide()
            self.desc.setText("no weather yet")
        self.adjustSize()


class EarthMap(QWidget):
    location_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: Optional[QImage] = None
        self.image_time: Optional[dt.datetime] = None
        self.markers: list[Marker] = []
        self.selected: Optional[str] = None
        self.temp_unit = "C"
        self.message = "Drawing the Earth…"
        self.setMinimumSize(360, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pulse = PulseMarker(self)
        self.pulse.hide()
        self.card = LocationCard(self)
        self.card.hide()
        self.setMouseTracking(True)

    # ------------------------------------------------------------ geometry
    def map_rect(self) -> QRectF:
        """Largest 2:1 rectangle centred in the widget."""
        w, h = self.width(), self.height()
        if w / 2 <= h:
            mw, mh = w, w / 2
        else:
            mw, mh = h * 2, h
        return QRectF((w - mw) / 2, (h - mh) / 2, mw, mh)

    def point_for(self, lat: float, lon: float) -> QPointF:
        r = self.map_rect()
        x, y = E.to_map_xy(lat, lon, r.width(), r.height())
        return QPointF(r.left() + x, r.top() + y)

    def marker_at(self, pos: QPointF, radius: float = 12.0) -> Optional[str]:
        best, best_d = None, radius
        for m in self.markers:
            p = self.point_for(m.lat, m.lon)
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d <= best_d:
                best, best_d = m.key, d
        return best

    # --------------------------------------------------------------- state
    def set_image(self, img: Optional[QImage], when: Optional[dt.datetime], message: str = "") -> None:
        self.image, self.image_time = img, when
        if message:
            self.message = message
        self.update()

    def set_markers(self, markers: list[Marker], selected: Optional[str], temp_unit: str) -> None:
        self.markers, self.selected, self.temp_unit = markers, selected, temp_unit
        self.refresh_card()
        self.update()

    def selected_marker(self) -> Optional[Marker]:
        return next((m for m in self.markers if m.key == self.selected), None)

    def refresh_card(self, now: Optional[dt.datetime] = None) -> None:
        m = self.selected_marker()
        if m is None:
            self.card.hide()
            self.pulse.hide()
            return
        now = now or dt.datetime.now(dt.timezone.utc)
        self.card.show_marker(m, now, self.temp_unit)
        self._place_overlays()
        self.card.show()
        self.pulse.show()

    def _place_overlays(self) -> None:
        m = self.selected_marker()
        if m is None:
            return
        p = self.point_for(m.lat, m.lon)
        self.pulse.move(int(p.x() - self.pulse.width() / 2), int(p.y() - self.pulse.height() / 2))
        c = self.card
        c.adjustSize()
        others = [self.point_for(o.lat, o.lon) for o in self.markers if o.key != m.key]
        c.move(*place_card(c.width(), c.height(), p, others, self.width(), self.height()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlays()

    # --------------------------------------------------------------- input
    def mousePressEvent(self, e):
        key = self.marker_at(e.position())
        if key and e.button() == Qt.MouseButton.LeftButton:
            self.location_clicked.emit(key)

    def mouseMoveEvent(self, e):
        key = self.marker_at(e.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if key else Qt.CursorShape.ArrowCursor)
        m = next((x for x in self.markers if x.key == key), None)
        self.setToolTip(f"{m.name} – click to select" if m else "")

    # ------------------------------------------------------------ painting
    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.fillRect(self.rect(), QColor("#05070d"))
            r = self.map_rect()
            if self.image is None:
                p.setPen(QColor(200, 205, 215))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message)
                return
            p.drawImage(r, self.image)
            t = self.image_time or dt.datetime.now(dt.timezone.utc)
            self._paint_body(p, *E.subsolar_point(t), sun=True)
            self._paint_body(p, *E.sublunar_point(t), sun=False)
            f = QFont(self.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            for m in self.markers:
                if m.key == self.selected:
                    continue
                pt = self.point_for(m.lat, m.lon)
                p.setPen(QPen(QColor(20, 20, 20), 1.2))
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(pt, 3.5, 3.5)
                draw_label(p, pt, m.name, r.right())
            sel = self.selected_marker()
            if sel is not None and self.card.isVisible():
                pt = self.point_for(sel.lat, sel.lon)
                cg = self.card.geometry()
                target = QPointF(min(max(pt.x(), cg.left()), cg.right()), min(max(pt.y(), cg.top()), cg.bottom()))
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                p.drawLine(pt, target)
        finally:
            p.end()

    def _paint_body(self, p: QPainter, lat: float, lon: float, sun: bool) -> None:
        pt = self.point_for(lat, lon)
        rad = 7 if sun else 5
        g = QRadialGradient(pt, rad * 3)
        col = QColor(255, 210, 80) if sun else QColor(210, 220, 255)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 150))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(pt, rad * 3, rad * 3)
        p.setBrush(col)
        p.setPen(QPen(QColor(60, 40, 0) if sun else QColor(40, 40, 60), 1))
        p.drawEllipse(pt, rad, rad)


class EarthPanel(QWidget):
    location_clicked = pyqtSignal(str)
    compose_requested = pyqtSignal()
    clouds_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.map = EarthMap()
        self.map.location_clicked.connect(self.location_clicked.emit)
        lay.addWidget(self.map, 1)
        row = QHBoxLayout()
        self.clouds_box = QCheckBox("Live clouds")
        self.clouds_box.setToolTip("Show near real-time satellite clouds (updated every 3 hours)")
        self.clouds_box.toggled.connect(self.clouds_toggled.emit)
        row.addWidget(self.clouds_box)
        row.addStretch(1)
        legend = QLabel("☀ Sun overhead  ·  ● Moon overhead")
        legend.setStyleSheet("color: palette(placeholder-text);")
        row.addWidget(legend)
        lay.addLayout(row)
        self.credit = QLabel(E.CREDIT + "\n" + CLOUD_CREDIT)
        self.credit.setWordWrap(True)
        self.credit.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.credit)
        self.clock = QTimer(self)
        self.clock.setInterval(15_000)
        self.clock.timeout.connect(self.tick)
        self.last_compose = 0.0

    def set_markers(self, markers: list[Marker], selected: Optional[str], temp_unit: str) -> None:
        self.map.set_markers(markers, selected, temp_unit)

    def retime(self) -> None:
        """Re-show times after a 12/24-hour change."""
        self.map.refresh_card()
        if self.map.image_time is not None:
            self.info.setText(info_text(self.map.image_time))

    def set_image(self, img: Optional[QImage], when: Optional[dt.datetime], error: str = "",
                  cloud_note: str = "") -> None:
        self.map.set_image(img, when, error)
        if when is not None:
            self.info.setText(info_text(when) + (" " + cloud_note if cloud_note else ""))
        elif error:
            self.info.setText(error)

    def needs_compose(self) -> bool:
        return time.time() - self.last_compose > RECOMPOSE_S or self.map.image is None

    def tick(self) -> None:
        self.map.refresh_card()
        if self.needs_compose():
            self.compose_requested.emit()

    def showEvent(self, e):
        super().showEvent(e)
        self.clock.start()
        self.tick()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.clock.stop()
