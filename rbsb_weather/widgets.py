"""Custom painted widgets: the 24-hour chart and the tray icon renderer."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import units, weather_codes
from .models import HourlyPoint

TEMP_COLOR = QColor("#e8743b")
RAIN_COLOR = QColor(74, 144, 217, 150)


class HourlyChart(QWidget):
    """Temperature line with precipitation-probability bars for the next 24 hours."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: list[HourlyPoint] = []
        self._unit = "C"
        self._alert_span: Optional[tuple] = None    # (first index, last index, colour, label) (2.4)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    empty_text = "No hourly data"      # shown when there are no points (the window may set a reason)

    def set_data(self, points: list[HourlyPoint], temp_unit: str) -> None:
        self._points = list(points)
        self._unit = temp_unit
        self.setToolTip("" if not points else
                        "Line: temperature  ·  Blue bars: chance of precipitation")
        self.update()

    def point_count(self) -> int:
        return len(self._points)

    def set_alert_span(self, span: Optional[tuple]) -> None:
        """Shade the hours a warning is in force: (first, last point index, colour, label) or None."""
        self._alert_span = span
        self.update()

    def alert_span(self) -> Optional[tuple]:
        return self._alert_span

    def paintEvent(self, _event):
        p = QPainter(self)
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text = pal.color(pal.ColorRole.WindowText)
        faint = QColor(text)
        faint.setAlpha(110)

        pts = self._points
        if not pts:
            p.setPen(faint)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return

        temps = [units.convert_temp(x.temperature, self._unit) for x in pts]
        valid = [t for t in temps if t is not None]
        if not valid:
            p.setPen(faint)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            return

        left, right, top, bottom = 12.0, 12.0, 26.0, 40.0
        w = max(1.0, self.width() - left - right)
        h = max(1.0, self.height() - top - bottom)
        n = len(pts)
        step = w / n
        lo, hi = min(valid), max(valid)
        if hi - lo < 4:
            mid = (hi + lo) / 2
            lo, hi = mid - 2, mid + 2

        def y_for(t: float) -> float:
            return top + h * 0.15 + (h * 0.6) * (1 - (t - lo) / (hi - lo))

        base_y = top + h

        # hours a warning is in force (2.4): a tinted band with a dashed end, and its name
        if self._alert_span is not None:
            a, b, colour, label = self._alert_span
            a, b = max(0, a), min(n - 1, b)
            if a <= b:
                c = QColor(colour)
                band = QColor(c)
                band.setAlpha(40)
                x0, x1 = left + a * step, left + (b + 1) * step
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(band)
                p.drawRect(QRectF(x0, top - 20, x1 - x0, base_y - top + 20))
                p.setPen(QPen(c.darker(115), 1.5, Qt.PenStyle.DashLine))
                if b < n - 1:
                    p.drawLine(QPointF(x1, top - 20), QPointF(x1, base_y))
                if a > 0:
                    p.drawLine(QPointF(x0, top - 20), QPointF(x0, base_y))
                f = QFont(self.font())
                f.setPointSizeF(max(7.0, f.pointSizeF() * 0.8))
                f.setBold(True)
                p.setFont(f)
                lab = QColor(colour).darker(170) if QColor(colour).lightness() > 120 else QColor(colour)
                p.setPen(lab)
                p.drawText(QRectF(x0 + 4, top - 20, max(10.0, x1 - x0 - 8), 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, int(max(10.0, x1 - x0 - 8))))
                p.setFont(self.font())

        # precipitation probability bars
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(RAIN_COLOR)
        for i, pt in enumerate(pts):
            prob = pt.precipitation_probability or 0
            if prob <= 0:
                continue
            bh = h * 0.45 * min(prob, 100) / 100.0
            x = left + i * step + step * 0.2
            p.drawRoundedRect(QRectF(x, base_y - bh, step * 0.6, bh), 2, 2)

        # temperature line
        path = QPainterPath()
        started = False
        for i, t in enumerate(temps):
            if t is None:
                started = False
                continue
            pt = QPointF(left + i * step + step / 2, y_for(t))
            if not started:
                path.moveTo(pt)
                started = True
            else:
                path.lineTo(pt)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(TEMP_COLOR, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)

        # labels every N hours so they never overlap
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        p.setFont(font)
        fm = p.fontMetrics()
        widest = max(fm.horizontalAdvance("00:00"), fm.horizontalAdvance("12 pm"))
        label_every = max(1, int((widest + 10) // step) + 1)
        for i, (pt, t) in enumerate(zip(pts, temps)):
            if i % label_every:
                continue
            cx = left + i * step + step / 2
            if t is not None:
                y = y_for(t)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(TEMP_COLOR)
                p.drawEllipse(QPointF(cx, y), 3, 3)
                p.setPen(text)
                lbl = f"{t:.0f}°"
                p.drawText(QRectF(cx - 30, y - 22, 60, 18), Qt.AlignmentFlag.AlignCenter, lbl)
            hour = units.fmt_hour_label(pt.time)
            p.setPen(faint)
            p.drawText(QRectF(cx - 30, base_y + 4, 60, 16), Qt.AlignmentFlag.AlignCenter, hour)
            prob = pt.precipitation_probability
            if prob:
                p.setPen(RAIN_COLOR.darker(130))
                p.drawText(QRectF(cx - 30, base_y + 19, 60, 16), Qt.AlignmentFlag.AlignCenter,
                           f"{prob:.0f}%")


def render_tray_icon(temp_c: Optional[float], unit: str, code: Optional[int] = None,
                     size: int = 64, alert_colour: Optional[str] = None) -> QIcon:
    """Draw the current temperature as an icon (works on any panel theme)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor("#2f6fb3")
        if code is not None and code >= 95:
            bg = QColor("#7a3fb0")
        elif code is not None and code >= 51:
            bg = QColor("#3b6e8f")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
        v = units.convert_temp(temp_c, unit)
        txt = "–" if v is None else f"{v:.0f}°"
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * (0.48 if len(txt) <= 3 else 0.38)))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, txt)
        if alert_colour:                    # a warning is in force (2.4): a dot in the corner
            r = size * 0.17
            p.setPen(QPen(QColor("#20242b"), size * 0.05))
            p.setBrush(QColor(alert_colour))
            p.drawEllipse(QPointF(size - r - 1.5, r + 1.5), r, r)
    finally:
        p.end()
    return QIcon(pix)


def app_icon() -> QIcon:
    """Application icon: themed icon if installed, else a painted sun/cloud."""
    themed = QIcon.fromTheme("rbsb-weather")
    if not themed.isNull():
        return themed
    size = 128
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#2f6fb3"))
        p.drawRoundedRect(QRectF(4, 4, 120, 120), 26, 26)
        p.setBrush(QColor("#ffc83d"))
        p.drawEllipse(QPointF(50, 50), 24, 24)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(58, 82), 20, 20)
        p.drawEllipse(QPointF(80, 72), 24, 24)
        p.drawEllipse(QPointF(100, 86), 16, 16)
        p.drawRoundedRect(QRectF(40, 82, 76, 20), 10, 10)
    finally:
        p.end()
    return QIcon(pix)


# Re-export for convenience
describe = weather_codes.describe
