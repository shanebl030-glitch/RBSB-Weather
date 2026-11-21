"""The Wind tab: world weather on the globe, with moving wind streaks.

Layers: 🌬 wind speed (2.2.0), 🌡 air temperature and 🌧 rain & snow (2.3.0). The
streaks always follow the wind, whichever layer is coloured in.

Reuses the Earth Globe's projection, dragging, zooming and saved-place markers
(GlobeView). The globe's picture is the Earth map, dimmed, with the wind-speed
colours over it. On top, a few thousand "particles" are carried along by the
wind and leave fading trails, so you see where the air is going and how fast.

* Hover anywhere on the globe for the wind there (speed in your units and the
  direction it comes from).
* The streaks only move while the tab is showing and animations are on, and
  they're cleared whenever the globe turns or zooms, so they never smear.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import random
import time
from typing import Optional

from PyQt6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

from . import earth as E
from . import units
from . import wind as W
from .globe import has_numpy, inverse, project
from .globe_panel import GlobeView, draw_label

try:
    import numpy as _np
except Exception:          # pragma: no cover
    _np = None

FRAME_MS = 33
PARTICLES_NUMPY = 2200
PARTICLES_PYTHON = 700
LIFE = (60, 150)                 # frames a streak lives
DEG_PER_MS_FRAME = 0.018         # degrees moved per frame per m/s of wind (at 30 frames a second)
TRAIL_FADE = 0.95                # how much of a trail survives each frame
MAP_W, MAP_H = 1440, 720         # globe picture (smooth upscale of the 1° grid)


LAYERS = (("wind", "🌬 Wind"), ("temp", "🌡 Temperature"), ("rain", "🌧 Rain && snow"))   # && shows "&"


def wind_text(u: float, v: float, wind_unit: str) -> str:
    spd, frm = W.speed_and_direction(u, v)
    return f"{units.fmt_wind(spd * 3.6, wind_unit)} from the {units.compass(frm)} ({frm:.0f}°)"


def rain_text(mm_h: float, precip_unit: str) -> str:
    if mm_h < W.RAIN_MIN:
        return "dry"
    if precip_unit == "in":
        return f"{units.convert_precip(mm_h, 'in'):.2f} in/h"
    return f"{mm_h:.1f} mm/h"


def point_text(fld: W.WindField, lat: float, lon: float, wind_unit: str, temp_unit: str,
               precip_unit: str) -> str:
    """Everything known at a point: wind, and temperature and rain when downloaded."""
    parts = [f"wind {wind_text(*fld.at(lat, lon), wind_unit)}"]
    t = fld.temp_at(lat, lon)
    if t is not None:
        parts.append(units.fmt_temp(t, temp_unit))
    r = fld.rain_at(lat, lon)
    if r is not None:
        parts.append(f"rain/snow {rain_text(r, precip_unit)}")
    return " · ".join(parts)


_coast_cache: dict = {}


def coastlines(w: int = MAP_W, h: int = MAP_H) -> Optional[QImage]:
    """Coastline outlines (white lines on transparent), traced from the Earth day map: its
    oceans are one even blue, so a coast is wherever ocean meets anything else. numpy only
    (without it the tab simply has no outlines)."""
    if (w, h) in _coast_cache:
        return _coast_cache[(w, h)]
    out = None
    if _np is not None:
        try:
            np = _np
            src = E._texture(E.DAY_FILE).scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation)
            src = src.convertToFormat(QImage.Format.Format_ARGB32)
            ptr = src.constBits()
            ptr.setsize(src.sizeInBytes())
            a = np.frombuffer(bytes(ptr), np.uint8).reshape(h, src.bytesPerLine())[:, :w * 4].reshape(h, w, 4)
            b, g, r = a[..., 0].astype(np.int16), a[..., 1].astype(np.int16), a[..., 2].astype(np.int16)
            sea = (abs(r - 30) < 28) & (abs(g - 59) < 30) & (abs(b - 117) < 40) & (b > r + 40)
            edge = np.zeros_like(sea)
            edge[:, 1:] |= sea[:, 1:] != sea[:, :-1]
            edge[1:, :] |= sea[1:, :] != sea[:-1, :]
            edge[:, 0] |= sea[:, 0] != sea[:, -1]                  # the map wraps at 180°
            thick = edge.copy()                                    # 2 px, so it survives the globe's sampling
            thick[:, 1:] |= edge[:, :-1]
            thick[1:, :] |= edge[:-1, :]
            edge = thick
            px = np.zeros((h, w, 4), np.uint8)
            px[edge] = (235, 235, 235, 235)                       # premultiplied BGRA
            out = QImage(px.tobytes(), w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        except Exception:
            out = None
    _coast_cache[(w, h)] = out
    return out


def compose_map(fld: W.WindField, layer: str = "wind") -> QImage:
    """The globe picture: the day Earth map dimmed, with the layer's colours over it."""
    out = QImage(MAP_W, MAP_H, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(QColor(10, 14, 24))
    p = QPainter(out)
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        try:
            p.setOpacity(0.75)
            p.drawImage(QRectF(0, 0, MAP_W, MAP_H), E._texture(E.DAY_FILE))
        except Exception:
            pass                                  # still useful without the map
        p.setOpacity(0.62 if layer != "rain" else 0.85)
        colours = W.layer_map(fld, layer).scaled(MAP_W, MAP_H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
        p.drawImage(0, 0, colours)
        coast = coastlines()
        if coast is not None:
            p.setOpacity(0.8)
            p.drawImage(0, 0, coast)
    finally:
        p.end()
    return out


class Particles:
    """Streak positions (lat, lon) carried along by the wind."""

    def __init__(self, n: int, seed: int = 7):
        self.n = n
        self.rng = random.Random(seed)
        if _np is not None:
            self.np_rng = _np.random.default_rng(seed)
            self.lat = _np.zeros(n)
            self.lon = _np.zeros(n)
            self.age = _np.zeros(n, _np.int64)
            self.life = _np.zeros(n, _np.int64)
        else:
            self.lat = [0.0] * n
            self.lon = [0.0] * n
            self.age = [0] * n
            self.life = [1] * n
        self.ready = False

    def _random_points(self, k: int, c_lat: float, c_lon: float):
        """`k` random points spread evenly over the half of the globe that's facing us."""
        out = []
        for _ in range(k):
            while True:
                x, y = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)
                if x * x + y * y < 0.98:
                    break
            out.append(inverse(x, y, c_lat, c_lon))
        return out

    def seed_all(self, c_lat: float, c_lon: float) -> None:
        pts = self._random_points(self.n, c_lat, c_lon)
        for i, (la, lo) in enumerate(pts):
            self.lat[i], self.lon[i] = la, lo
            self.life[i] = self.rng.randint(*LIFE)
            self.age[i] = self.rng.randint(0, self.life[i])          # staggered, so they don't all reset at once
        self.ready = True

    def step(self, fld: W.WindField, c_lat: float, c_lon: float):
        """Move every streak one frame. Returns (old lat, old lon, new lat, new lon, speed, alive)
        sequences; `alive` is False for streaks that were just reborn (no line drawn)."""
        if _np is not None:
            np = _np
            la0, lo0 = self.lat.copy(), self.lon.copy()
            u, v = fld.at_many(self.lat, self.lon)
            spd = np.hypot(u, v)
            coslat = np.maximum(np.cos(np.radians(self.lat)), 0.15)
            self.lon = (self.lon + u * DEG_PER_MS_FRAME / coslat + 180.0) % 360.0 - 180.0
            self.lat = np.clip(self.lat + v * DEG_PER_MS_FRAME, -89.5, 89.5)
            self.age += 1
            reborn = self.age >= self.life
            if reborn.any():
                k = int(reborn.sum())
                pts = self._random_points(k, c_lat, c_lon)
                self.lat[reborn] = [p[0] for p in pts]
                self.lon[reborn] = [p[1] for p in pts]
                self.age[reborn] = 0
                self.life[reborn] = self.np_rng.integers(LIFE[0], LIFE[1], k)
            return la0, lo0, self.lat, self.lon, spd, ~reborn
        old_lat, old_lon, spds, alive = list(self.lat), list(self.lon), [], []
        for i in range(self.n):
            la, lo = self.lat[i], self.lon[i]
            u, v = fld.at(la, lo)
            spds.append(math.hypot(u, v))
            coslat = max(math.cos(math.radians(la)), 0.15)
            self.lon[i] = (lo + u * DEG_PER_MS_FRAME / coslat + 180.0) % 360.0 - 180.0
            self.lat[i] = min(89.5, max(-89.5, la + v * DEG_PER_MS_FRAME))
            self.age[i] += 1
            if self.age[i] >= self.life[i]:
                (self.lat[i], self.lon[i]), = self._random_points(1, c_lat, c_lon)
                self.age[i] = 0
                self.life[i] = self.rng.randint(*LIFE)
                alive.append(False)
            else:
                alive.append(True)
        return old_lat, old_lon, self.lat, self.lon, spds, alive


class WindView(GlobeView):
    """The globe with wind colours and moving streaks."""
    hover_text = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.field: Optional[W.WindField] = None
        self.wind_unit = "km/h"
        self.temp_unit = "C"
        self.precip_unit = "mm"
        self.message = "Getting the world wind from NOAA…"
        self.particles = Particles(PARTICLES_NUMPY if has_numpy() else PARTICLES_PYTHON)
        self.trails: Optional[QImage] = None
        self._view_key = None
        self.frames = 0
        self.animate = True
        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._frame)
        self.card.hide()
        # the tab also has a row of layer buttons and the colour key: let the globe give way
        # on a short window instead of overlapping them
        self.setMinimumSize(260, 180)

    # -- no location card or Sun/Moon on this globe; markers and labels stay
    def refresh_card(self, now=None) -> None:
        self.card.hide()
        self.pulse.hide()

    def _place_overlays(self) -> None:
        self.card.hide()
        self.pulse.hide()

    def set_field(self, fld: Optional[W.WindField], img: Optional[QImage], message: str = "") -> None:
        self.field = fld
        if message:
            self.message = message
        self.set_source(img, fld.valid if fld else None, message)
        self.particles.ready = False
        self._clear_trails()
        self._update_timer()

    def set_animate(self, on: bool) -> None:
        self.animate = bool(on)
        self._update_timer()
        if not on:
            self._clear_trails()
            self.update()

    def _update_timer(self) -> None:
        if self.animate and self.field is not None and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()                         # no CPU while the tab isn't shown

    def _clear_trails(self) -> None:
        self.trails = None

    def _frame(self) -> None:
        if self.field is None or self.image is None:
            return
        r = self.globe_rect()
        key = (round(self.c_lat, 3), round(self.c_lon, 3), round(r.width(), 1), self.width(), self.height())
        if key != self._view_key or self.trails is None or self.trails.size() != self.size():
            self._view_key = key
            self.trails = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
            self.trails.fill(0)
        if not self.particles.ready:
            self.particles.seed_all(self.c_lat, self.c_lon)
        la0, lo0, la1, lo1, spd, alive = self.particles.step(self.field, self.c_lat, self.c_lon)
        p = QPainter(self.trails)
        try:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            p.fillRect(self.trails.rect(), QColor(0, 0, 0, int(255 * TRAIL_FADE)))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx, cy, rad = r.center().x(), r.center().y(), r.width() / 2
            lines = self._lines(la0, lo0, la1, lo1, alive, cx, cy, rad)
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.0))
            p.drawLines(lines)
        finally:
            p.end()
        self.frames += 1
        self.update()

    def _lines(self, la0, lo0, la1, lo1, alive, cx, cy, rad) -> list:
        if _np is not None and not isinstance(la0, list):
            np = _np
            p0, l0 = math.radians(self.c_lat), math.radians(self.c_lon)
            sp0, cp0 = math.sin(p0), math.cos(p0)

            def proj(lat, lon):
                pr, lr = np.radians(lat), np.radians(lon) - l0
                cosc = sp0 * np.sin(pr) + cp0 * np.cos(pr) * np.cos(lr)
                x = np.cos(pr) * np.sin(lr)
                y = cp0 * np.sin(pr) - sp0 * np.cos(pr) * np.cos(lr)
                return cx + x * rad, cy - y * rad, cosc > 0.05
            x0, y0, v0 = proj(la0, lo0)
            x1, y1, v1 = proj(la1, lo1)
            ok = v0 & v1 & alive & (np.abs(x1 - x0) + np.abs(y1 - y0) < rad * 0.2)
            return [QLineF(a, b, c, d) for a, b, c, d in zip(x0[ok], y0[ok], x1[ok], y1[ok])]
        out = []
        for i in range(len(la0)):
            if not alive[i]:
                continue
            xa, ya, va = project(la0[i], lo0[i], self.c_lat, self.c_lon)
            xb, yb, vb = project(la1[i], lo1[i], self.c_lat, self.c_lon)
            if va and vb:
                out.append(QLineF(cx + xa * rad, cy - ya * rad, cx + xb * rad, cy - yb * rad))
        return out

    def set_center(self, lat: float, lon: float, low_res: bool = False) -> None:
        super().set_center(lat, lon, low_res)
        self._clear_trails()                      # streaks would smear across a turning globe

    def _apply_zoom(self, v) -> None:
        super()._apply_zoom(v)
        self._clear_trails()

    # ------------------------------------------------------------ hover
    def wind_at_pos(self, pos: QPointF) -> Optional[tuple[float, float, float, float]]:
        if self.field is None:
            return None
        r = self.globe_rect()
        x = (pos.x() - r.center().x()) / (r.width() / 2)
        y = -(pos.y() - r.center().y()) / (r.height() / 2)
        ll = inverse(x, y, self.c_lat, self.c_lon)
        if ll is None:
            return None
        u, v = self.field.at(*ll)
        return ll[0], ll[1], u, v

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        if self._drag_from is not None:
            return
        w = self.wind_at_pos(e.position())
        if w is None:
            self.hover_text.emit("")
            return
        lat, lon, u, v = w
        units_ = (self.wind_unit, self.temp_unit, self.precip_unit)
        txt = (f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'} {abs(lon):.1f}°{'E' if lon >= 0 else 'W'}: "
               f"{point_text(self.field, lat, lon, *units_)}")
        self.hover_text.emit(txt)
        key = self.marker_at(e.position())
        m = next((x for x in self.markers if x.key == key), None)
        self.setToolTip(f"{m.name}: {point_text(self.field, m.lat, m.lon, *units_)}" if m else txt)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.hover_text.emit("")

    # ------------------------------------------------------------ painting
    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.fillRect(self.rect(), QColor("#02030a"))
            r = self.globe_rect()
            c = r.center()
            rad = r.width() / 2
            glow = QRadialGradient(c, rad * 1.1)
            glow.setColorAt(0.88, QColor(90, 150, 255, 0))
            glow.setColorAt(0.91, QColor(110, 170, 255, 90))
            glow.setColorAt(1.0, QColor(90, 150, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, rad * 1.1, rad * 1.1)
            if self.image is None:
                p.setPen(QColor(200, 205, 215))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
                return
            p.drawImage(r, self.image)
            if self.trails is not None and self.animate:
                p.drawImage(0, 0, self.trails)
            f = QFont(self.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            for m in self.markers:
                pt = self.point_for(m.lat, m.lon)
                if pt is None:
                    continue
                sel = m.key == self.selected
                p.setPen(QPen(QColor(20, 20, 20), 1.2))
                p.setBrush(QColor(255, 214, 90) if sel else QColor(255, 255, 255))
                p.drawEllipse(pt, 4.5 if sel else 3.5, 4.5 if sel else 3.5)
                draw_label(p, pt, m.name, self.width())
        finally:
            p.end()


class SpeedLegend(QWidget):
    """The colour key for the layer shown, labelled in the user's units."""

    TICKS = {"wind": [0, 4, 8, 12.5, 18, 27, 34], "temp": [-40, -20, 0, 10, 20, 30, 45],
             "rain": [0.1, 1, 4, 12, 35]}
    TIPS = {"wind": "Wind speed 10 m above the ground", "temp": "Air temperature 2 m above the ground",
            "rain": "Rain and snow (melted), as the forecast's average rate over the hours before"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.unit = "km/h"
        self.temp_unit = "C"
        self.precip_unit = "mm"
        self.layer = "wind"
        self.setMinimumSize(260, 30)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(self.TIPS["wind"])

    def set_unit(self, unit: str) -> None:
        self.unit = unit
        self.update()

    def set_layer(self, layer: str, temp_unit: Optional[str] = None, precip_unit: Optional[str] = None) -> None:
        self.layer = layer if layer in W.SCALES else "wind"
        self.temp_unit = temp_unit or self.temp_unit
        self.precip_unit = precip_unit or self.precip_unit
        self.setToolTip(self.TIPS[self.layer])
        self.update()

    def _label(self, x: float, last: bool) -> str:
        if self.layer == "temp":
            return units.fmt_temp(x, self.temp_unit)
        if self.layer == "rain":
            if self.precip_unit == "in":
                v = units.convert_precip(x, "in")
                return f"{v:.2f}".rstrip("0").rstrip(".") + (" in/h" if last else "")
            return f"{x:g}" + (" mm/h" if last else "")
        label = f"{units.convert_wind(x * 3.6, self.unit):.0f}" if x else "0"
        return label + (f" {self.unit}" if last else "")

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            top = 2
            h = 10
            r = QRectF(4, top, self.width() - 8, h)
            stops = W.SCALES[self.layer]
            lo, hi = stops[0][0], stops[-1][0]
            if self.layer == "rain":                     # mm/h spread out: use a square-root scale
                pos = lambda x: math.sqrt(max(0.0, x - lo) / (hi - lo))      # noqa: E731
            else:
                pos = lambda x: (x - lo) / (hi - lo)                          # noqa: E731
            g = QLinearGradient(r.left(), 0, r.right(), 0)
            for x, (cr, cg, cb) in stops:
                g.setColorAt(min(1.0, max(0.0, pos(x))), QColor(cr, cg, cb))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, 3, 3)
            f = QFont(self.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.8))
            p.setFont(f)
            p.setPen(self.palette().color(self.foregroundRole()))
            ticks = self.TICKS[self.layer]
            fm = p.fontMetrics()
            for x in ticks:
                label = self._label(x, x == ticks[-1])
                w = fm.horizontalAdvance(label)
                cx = r.left() + pos(x) * r.width()
                cx = min(max(cx - w / 2, 0), self.width() - w)
                p.drawText(QPointF(cx, top + h + fm.ascent() + 2), label)
        finally:
            p.end()


class WindPanel(QWidget):
    location_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    layer_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        self.info = QLabel("Wind 10 m above the ground, from NOAA's GFS forecast.")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        layers = QHBoxLayout()                     # 🌬 Wind · 🌡 Temperature · 🌧 Rain & snow (2.3)
        layers.setSpacing(4)
        self.layer = "wind"
        self.layer_buttons: dict[str, QPushButton] = {}
        for key, text in LAYERS:
            b = QPushButton(text)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(key == "wind")
            b.clicked.connect(lambda _=False, k=key: self.set_layer(k, user=True))
            layers.addWidget(b)
            self.layer_buttons[key] = b
        layers.addStretch(1)
        lay.addLayout(layers)
        self.view = WindView()
        self.view.location_clicked.connect(self.location_clicked.emit)
        lay.addWidget(self.view, 1)
        self.hover = QLabel(" ")
        self.hover.setStyleSheet("color: palette(placeholder-text);")
        self.view.hover_text.connect(lambda t: self.hover.setText(t or "Hover over the globe for the wind there"))
        row = QHBoxLayout()
        self.legend = SpeedLegend()
        row.addWidget(self.legend, 3)
        self.streaks_box = QCheckBox("Moving streaks")
        self.streaks_box.setChecked(True)
        self.streaks_box.setToolTip("Animated streaks that follow the wind (turn off to save CPU)")
        self.streaks_box.toggled.connect(self.view.set_animate)
        row.addWidget(self.streaks_box)
        self.centre_btn = QPushButton("Centre on selected")
        self.centre_btn.clicked.connect(self.centre_on_selected)
        row.addWidget(self.centre_btn)
        lay.addLayout(row)
        lay.addWidget(self.hover)
        self.credit = QLabel(f"{W.CREDIT} – <a href='{W.PROJECT_URL}'>ncei.noaa.gov</a>")
        self.credit.setOpenExternalLinks(True)
        self.credit.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.credit)
        self.clock = QTimer(self)
        self.clock.setInterval(5 * 60_000)
        self.clock.timeout.connect(self.refresh_requested.emit)
        self.hover.setText("Hover over the globe for the wind there")

    def centre_on_selected(self) -> None:
        m = self.view.selected_marker()
        if m is not None:
            self.view.turn_to(m.lat, m.lon)

    def set_markers(self, markers, selected, temp_unit) -> None:
        self.view.set_markers(markers, selected, temp_unit)

    def set_wind_unit(self, unit: str) -> None:
        self.view.wind_unit = unit
        self.legend.set_unit(unit)

    def set_units(self, wind_unit: str, temp_unit: str, precip_unit: str) -> None:
        self.view.wind_unit, self.view.temp_unit, self.view.precip_unit = wind_unit, temp_unit, precip_unit
        self.legend.set_unit(wind_unit)
        self.legend.set_layer(self.legend.layer, temp_unit, precip_unit)

    def _shown_layer(self) -> str:
        fld = self.view.field
        return self.layer if fld is None or self.layer in fld.layers else "wind"

    def set_layer(self, layer: str, user: bool = False) -> None:
        """Show another layer (the wind streaks stay). `user`: chosen with a button (remembered)."""
        if layer not in dict(LAYERS):
            layer = "wind"
        self.layer = layer
        shown = self._shown_layer()
        for k, b in self.layer_buttons.items():
            b.setChecked(k == shown)
        self.legend.set_layer(shown)
        fld = self.view.field
        if fld is not None:
            self.view.set_source(compose_map(fld, shown), fld.valid)
            self.info.setText(info_text(fld, layer=shown))
        if user:
            self.layer_changed.emit(layer)

    def _update_buttons(self) -> None:
        fld = self.view.field
        for k, b in self.layer_buttons.items():
            ok = fld is not None and k in fld.layers
            b.setEnabled(ok or k == "wind")
            b.setToolTip("" if ok or k == "wind" else "Not in the saved forecast yet: it comes with the next download")

    def set_field(self, fld: Optional[W.WindField], error: str = "", source: str = "") -> None:
        if fld is None:
            self.view.set_field(None, None, error or "The world wind isn't available yet.")
            self.info.setText(error or "The world wind isn't available yet.")
            self._update_buttons()
            return
        shown = self.layer if self.layer in fld.layers else "wind"
        self.view.set_field(fld, compose_map(fld, shown))
        self._update_buttons()
        for k, b in self.layer_buttons.items():
            b.setChecked(k == shown)
        self.legend.set_layer(shown)
        self.info.setText(info_text(fld, error, layer=shown))

    def retime(self) -> None:
        if self.view.field is not None:
            self.info.setText(info_text(self.view.field, layer=self._shown_layer()))

    def showEvent(self, e):
        super().showEvent(e)
        self.clock.start()
        self.refresh_requested.emit()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.clock.stop()


WHAT = {"wind": "Wind 10 m above the ground",
        "temp": "Air temperature 2 m above the ground (moving streaks: the wind)",
        "rain": "Rain and snow, as the average rate over the few hours before (moving streaks: the wind)"}


def info_text(fld: W.WindField, note: str = "", layer: str = "wind") -> str:
    local = fld.valid.astimezone()
    run = fld.run.astimezone()
    txt = (f"{WHAT.get(layer, WHAT['wind'])} for {local:%a} {units.fmt_clock(local)} (your time), "
           f"from NOAA's GFS forecast run of {run:%a} {units.fmt_clock(run)}. Updated every 3 hours.")
    if note:
        txt += f" {note}"
    return txt
