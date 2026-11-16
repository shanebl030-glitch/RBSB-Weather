"""The mini forecast inside the weather scene (the "wedge"): 1-7 days in its
bottom-right corner, each with an animated icon, day name, high/low and rain chance.

* How many days fit is worked out from the scene's real size (small: 1-2,
  medium: 3-5, large: up to 7) - never squeezed: a day is only shown if it fits
  at a readable size.
* It never overlaps the text on the scene (place, temperature, description,
  local time, ...). It stays fixed in the bottom-right corner; the Sun and Moon
  pass behind it as they set (1.11.1 - before, it stepped aside for them).
  plan() can still keep clear of circles if given any, but the scene passes none.
* Drawn by the scene itself with the same animation clock as the sky, so it's
  as smooth as the Sun and Moon and costs no extra timers or widgets.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QRadialGradient

from . import units

MAX_DAYS = 7
WINDY_KMH = 40.0                  # daily max wind at or above this shows the windy icon
MARGIN = 0.035                    # of the scene's smaller side
GAP_TEXT = 14.0                   # px kept clear of the scene's text
SUN_CLEARANCE = 1.6               # Sun disc radius multiplier kept clear (disc + inner rays)
MOON_CLEARANCE = 1.3
LONG_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SHORT_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Day:
    date: dt.date
    code: Optional[int]
    temp_max: Optional[float]          # °C
    temp_min: Optional[float]          # °C
    rain: Optional[float]              # % chance, None if not available
    wind_max: Optional[float] = None   # km/h

    @property
    def windy(self) -> bool:
        from .scene import CLEAR, OVERCAST, PARTLY, classify
        return (self.wind_max is not None and self.wind_max >= WINDY_KMH
                and classify(self.code)[0] in (CLEAR, PARTLY, OVERCAST))


def days_from_forecast(fc, limit: int = MAX_DAYS) -> list[Day]:
    """Today onwards (at the location), from the forecast's daily data."""
    today = location_today(fc)
    out = []
    for d in fc.daily:
        try:
            date = dt.date.fromisoformat(d.date)
        except (TypeError, ValueError):
            continue
        if today is not None and date < today:
            continue
        out.append(Day(date, d.weather_code, d.temp_max, d.temp_min,
                       d.precipitation_probability_max, d.wind_speed_max))
        if len(out) >= limit:
            break
    return out


def location_today(fc) -> Optional[dt.date]:
    try:
        return dt.datetime.fromisoformat(fc.current.time).date()
    except (AttributeError, TypeError, ValueError):
        return None


def day_name(date: dt.date, today: Optional[dt.date], long: bool) -> str:
    if today is not None:
        if date == today:
            return "Today"
        if date == today + dt.timedelta(days=1):
            return "Tomorrow" if long else "Tmrw"
    return (LONG_NAMES if long else SHORT_NAMES)[date.weekday()]


def temp_text(c: Optional[float], unit: str) -> str:
    v = units.convert_temp(c, unit)
    if v is None:
        return "–"
    s = f"{v:.0f}"
    return (s[1:] if s == "-0" else s) + "°"


# ---------------------------------------------------------------- layout
@dataclass
class Cell:
    day: Day
    name: str
    rect: QRectF
    icon: QRectF
    name_y: float
    temp_y: float
    rain_y: float


@dataclass
class Layout:
    cells: list[Cell]
    rect: QRectF
    font_px: float
    small_px: float
    icon_px: float
    long_names: bool
    cap: int                            # most days this size of scene may show
    fonts: tuple = field(default=(), repr=False)


def size_cap(w: float, h: float) -> int:
    """Small scenes show at most 2 days, medium 5, large 7 (readability first)."""
    side = min(w, h)
    if side < 150 or w < 280:
        return 2
    if side < 200 or w < 420:
        return 5
    return MAX_DAYS


def _fonts(base: QFont, h: float):
    font_px = max(9.5, min(13.0, h * 0.066))
    f = QFont(base)
    f.setPixelSize(round(font_px))
    fb = QFont(f)
    fb.setBold(True)
    fs = QFont(base)
    fs.setPixelSize(round(max(9.0, font_px * 0.88)))
    return f, fb, fs, font_px, fs.pixelSize()


def _rect_circle(r: QRectF, cx: float, cy: float, rad: float) -> bool:
    nx = min(max(cx, r.left()), r.right())
    ny = min(max(cy, r.top()), r.bottom())
    return math.hypot(cx - nx, cy - ny) < rad


def plan(scene: QRectF, days: list[Day], today: Optional[dt.date], base_font: QFont,
         avoid_rects: list[QRectF] = (), avoid_circles: list[tuple[float, float, float]] = (),
         temp_unit: str = "C") -> Optional[Layout]:
    """Where the forecast goes, or None if not even one day fits readably."""
    if not days or scene.width() < 120 or scene.height() < 80:
        return None
    w, h = scene.width(), scene.height()
    f, fb, fs, font_px, small_px = _fonts(base_font, h)
    fm, fmb, fms = QFontMetricsF(f), QFontMetricsF(fb), QFontMetricsF(fs)
    icon = max(18.0, min(40.0, h * 0.18))
    pad = max(2.0, h * 0.012)
    cell_h = fmb.height() + pad + icon + pad + fm.height() + fms.height() + pad
    margin = max(6.0, min(w, h) * MARGIN)
    bottom = scene.bottom() - margin
    top = bottom - cell_h
    if top < scene.top() + margin:
        return None
    # sized from the real values shown (so a typical "19° 10°" isn't given room for "-88° -88°")
    temps_w = max(fmb.horizontalAdvance(temp_text(d.temp_max, temp_unit))
                  + fm.horizontalAdvance(" " + temp_text(d.temp_min, temp_unit)) for d in days[:MAX_DAYS])
    rain_w = max((fms.horizontalAdvance(f"{d.rain:.0f}%") for d in days[:MAX_DAYS] if d.rain is not None),
                 default=0.0) + small_px * 0.9
    cap = size_cap(w, h)
    # left edge: right of any scene text in the forecast's band, and in the right-hand part
    x_min = scene.left() + w * 0.3
    band = QRectF(scene.left(), top - 4, w, cell_h + 8)
    for t in avoid_rects:
        if t.intersects(band):
            x_min = max(x_min, t.right() + GAP_TEXT)
    x_max = scene.right() - margin
    best = None
    for long in (True, False):
        names = [day_name(d.date, today, long) for d in days[:cap]]
        name_w = max(fmb.horizontalAdvance(n) for n in names)
        cell_w = max(icon * 1.2, name_w, temps_w, rain_w) + max(6.0, font_px * 0.7)
        n_fit = min(cap, len(days), int((x_max - x_min) // cell_w))
        for n in range(n_fit, 0, -1):
            width = n * cell_w
            # rightmost spot first; otherwise just left of whichever Sun/Moon is in the way
            spots = [x_max] + sorted((cx - r - 3.0 for cx, _cy, r in avoid_circles), reverse=True)
            placed = None
            for right in spots:
                right = min(right, x_max)
                strip = QRectF(right - width, top, width, cell_h)
                if strip.left() < x_min:
                    continue
                if any(_rect_circle(strip, cx, cy, r) for cx, cy, r in avoid_circles):
                    continue
                if any(strip.intersects(t) for t in avoid_rects):
                    continue
                placed = strip
                break
            if placed is not None:
                if best is None or n > len(best[1]):
                    best = (long, names[:n], placed, cell_w)
                break
        if best is not None and len(best[1]) >= min(cap, len(days)):
            break                                    # long names already fit everything
    if best is None:
        return None
    long, names, strip, cell_w = best
    cells = []
    for i, (d, name) in enumerate(zip(days, names)):
        x = strip.left() + i * cell_w
        cell = QRectF(x, top, cell_w, cell_h)
        name_y = top + fmb.ascent()
        icon_r = QRectF(x + (cell_w - icon) / 2, top + fmb.height() + pad, icon, icon)
        temp_y = icon_r.bottom() + pad + fm.ascent()
        rain_y = icon_r.bottom() + pad + fm.height() + fms.ascent()
        cells.append(Cell(d, name, cell, icon_r, name_y, temp_y, rain_y))
    return Layout(cells, strip, font_px, small_px, icon, long, cap, (f, fb, fs))


# ---------------------------------------------------------------- painting
def paint(p: QPainter, lay: Layout, t: float, temp_unit: str) -> None:
    from .scene import paint_icon
    f, fb, fs = lay.fonts
    p.save()
    # a soft shade under the corner keeps white text readable on a bright sky
    # (feathered, so it blends into the scene rather than looking like a panel)
    r = lay.rect.adjusted(-lay.icon_px * 0.6, -lay.icon_px * 0.5, lay.icon_px * 0.6, lay.icon_px * 0.4)
    g = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.62)
    g.setColorAt(0.0, QColor(0, 10, 30, 95))
    g.setColorAt(0.7, QColor(0, 10, 30, 55))
    g.setColorAt(1.0, QColor(0, 10, 30, 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.save()
    p.translate(r.center())
    p.scale(1.0, r.height() / max(1.0, r.width()))
    rad = max(r.width(), r.height()) * 0.62
    p.drawEllipse(QPointF(0, 0), rad, rad)
    p.restore()

    def text(x, y, s, font, color, align_center=True):
        p.setFont(font)
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(s)
        tx = x - tw / 2 if align_center else x
        p.setPen(QColor(0, 0, 0, 170))
        p.drawText(QPointF(tx + 1, y + 1), s)
        p.setPen(color)
        p.drawText(QPointF(tx, y), s)
        return tw

    for i, c in enumerate(lay.cells):
        cx = c.rect.center().x()
        text(cx, c.name_y, c.name, fb, QColor(255, 255, 255))
        # each day's icon has its own phase so they don't move in lockstep
        paint_icon(p, c.icon, c.day.code, True, t + i * 0.37, windy=c.day.windy)
        hi, lo = temp_text(c.day.temp_max, temp_unit), temp_text(c.day.temp_min, temp_unit)
        fmb, fm = QFontMetricsF(fb), QFontMetricsF(f)
        total = fmb.horizontalAdvance(hi) + fm.horizontalAdvance(" " + lo)
        x0 = cx - total / 2
        w1 = text(x0, c.temp_y, hi, fb, QColor(255, 255, 255), align_center=False)
        text(x0 + w1, c.temp_y, " " + lo, f, QColor(232, 238, 248, 225), align_center=False)
        if c.day.rain is not None:
            pct = f"{c.day.rain:.0f}%"
            fms = QFontMetricsF(fs)
            dw = lay.small_px * 0.55
            total = dw + 3 + fms.horizontalAdvance(pct)
            x0 = cx - total / 2
            _drop(p, QPointF(x0 + dw / 2, c.rain_y - fms.ascent() * 0.42), dw)
            col = QColor(195, 225, 255) if c.day.rain >= 20 else QColor(225, 232, 242, 220)
            text(x0 + dw + 3, c.rain_y, pct, fs, col, align_center=False)
    p.restore()


def _drop(p: QPainter, c: QPointF, w: float) -> None:
    path = QPainterPath()
    path.moveTo(c.x(), c.y() - w * 0.95)
    path.cubicTo(c.x() + w * 0.6, c.y() - w * 0.1, c.x() + w * 0.55, c.y() + w * 0.55, c.x(), c.y() + w * 0.55)
    path.cubicTo(c.x() - w * 0.55, c.y() + w * 0.55, c.x() - w * 0.6, c.y() - w * 0.1, c.x(), c.y() - w * 0.95)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(120, 180, 255))
    p.drawPath(path)
