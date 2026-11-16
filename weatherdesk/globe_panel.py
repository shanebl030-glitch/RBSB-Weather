"""The Earth Globe tab: the same live day/night Earth as the flat map, on a globe.

* Drag to spin it; it turns smoothly to face a location when you select one
  (in Saved Locations, or by clicking its marker).
* Saved locations, the pulsing selected marker and its card (local time,
  day/twilight/night, temperature, animated weather icon), and the Sun/Moon
  overhead points - everything the flat map has, on the visible hemisphere.
* Optional slow rotation. Stars and an atmosphere glow for depth.

It uses the same day/night image as the flat map (no extra background work).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import time
from typing import Optional

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from . import earth as E
from .clouds import CREDIT as CLOUD_CREDIT
from .earth_panel import (RECOMPOSE_S, LocationCard, Marker, PulseMarker, draw_label, info_text,
                          place_card)
from .globe import GlobeRenderer, has_numpy, project
from .sky import StarField, basis, ecef, gmst_now, hidden_by_earth, moon_orientation, sky_xy, to_view

log = logging.getLogger(__name__)

MAX_RENDER = 1300          # cap on rendered globe size (the Earth maps hold no finer detail)
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.6, 3.0, 1.25
MOON_SIZE = 0.32           # Moon radius on screen, in globe radii (not to scale, so it's visible)
MOON_MAX_PX = 360          # largest Moon drawn (logical px); rendered at device resolution
SUN_SIZE = 0.11            # Sun radius on screen, in globe radii (not to scale)
ZOOM_ANIM_MS = 180         # zoom glides between steps; the globe is re-drawn sharp at the end
DRAG_SCALE = 0.6           # render at lower resolution while dragging/turning, sharp on release
SPIN_DEG_PER_S = 8.0


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


class GlobeView(QWidget):
    location_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.renderer = GlobeRenderer()
        self.c_lat, self.c_lon = 0.0, 0.0
        self.image: Optional[QImage] = None
        self.image_time: Optional[dt.datetime] = None
        self.markers: list[Marker] = []
        self.selected: Optional[str] = None
        self.temp_unit = "C"
        self.message = "Drawing the Earth…"
        self._drag_from: Optional[QPointF] = None
        self._drag_moved = False
        self._press_key: Optional[str] = None
        self._press_pos = QPointF()
        self._low_res = False
        self.renders = 0
        self.zoom = 1.0
        self.starfield = StarField(2400 if has_numpy() else 900)
        self._phase_cache: tuple = (None, None)             # (minute, Phase)
        self._indicators: list[tuple] = []                 # off-screen Sun/Moon hints
        self.sky_drawn: dict = {}                           # what the last paint showed (for tests)
        self.setMinimumSize(300, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.pulse = PulseMarker(self)
        self.pulse.hide()
        self.card = LocationCard(self)
        self.card.hide()
        self._render_timer = QTimer(self)                 # coalesces render requests
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_now)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(700)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._anim_step)
        self.anim.finished.connect(self._anim_done)
        self._anim_from = self._anim_to = (0.0, 0.0)
        self.spin_timer = QTimer(self)
        self.spin_timer.setInterval(50)
        self.spin_timer.timeout.connect(self._spin_step)
        self._spin_last = time.monotonic()
        # Zooming glides: each frame just scales the last globe picture (instant), and the
        # globe is re-drawn at full resolution once the zoom settles - no re-render per step.
        self._zoom_target = 1.0
        self.zoom_anim = QVariantAnimation(self)
        self.zoom_anim.setDuration(ZOOM_ANIM_MS)
        self.zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.zoom_anim.valueChanged.connect(self._apply_zoom)
        self.zoom_anim.finished.connect(self._zoom_settled)
        self._moon_cache: Optional[tuple] = None          # (key, QImage)
        self._sun_cache: Optional[tuple] = None
        self.zoom_out_btn = self._tool_button("−", "Zoom out (mouse wheel or −)", self.zoom_out)
        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setStyleSheet("color: #dfe6f0; background: rgba(10,14,24,170); "
                                      "border-radius: 4px; padding: 2px 6px;")
        self.zoom_label.setToolTip("Zoom (0 resets)")
        self.zoom_in_btn = self._tool_button("+", "Zoom in (mouse wheel or +)", self.zoom_in)

    def _tool_button(self, text: str, tip: str, slot) -> QToolButton:
        b = QToolButton(self)
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRepeat(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setFixedSize(30, 28)
        b.setStyleSheet("QToolButton { color: white; font-size: 16px; font-weight: bold; "
                        "background: rgba(10,14,24,170); border: 1px solid rgba(255,255,255,60); "
                        "border-radius: 5px; } QToolButton:hover { background: rgba(40,60,100,200); }")
        b.clicked.connect(slot)
        return b

    def _place_zoom_controls(self) -> None:
        x = self.width() - 8
        for wdg in (self.zoom_in_btn, self.zoom_label, self.zoom_out_btn):
            wdg.adjustSize() if wdg is self.zoom_label else None
            x -= wdg.width()
            wdg.move(x, 8 + (28 - wdg.height()) // 2)
            x -= 4

    # ---------------------------------------------------------------- zoom
    def set_zoom(self, z: float, animate: bool = True) -> None:
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if abs(z - 1.0) < 0.02:
            z = 1.0
        if z == self._zoom_target and (self.zoom == z or self.zoom_anim.state() == QVariantAnimation.State.Running):
            return
        self._zoom_target = z
        self.zoom_label.setText(f"{round(z * 100)}%")
        self.zoom_in_btn.setEnabled(z < ZOOM_MAX)
        self.zoom_out_btn.setEnabled(z > ZOOM_MIN)
        self._place_zoom_controls()
        self.zoom_anim.stop()
        if not animate or not self.isVisible():
            self._apply_zoom(z)
            self._zoom_settled()
            return
        self.zoom_anim.setStartValue(float(self.zoom))
        self.zoom_anim.setEndValue(float(z))
        self.zoom_anim.start()

    def zooming(self) -> bool:
        return self.zoom_anim.state() == QVariantAnimation.State.Running

    def _apply_zoom(self, v) -> None:
        self.zoom = float(v)
        self._place_overlays()
        self.update()                     # paint scales the existing globe picture: cheap

    def _zoom_settled(self) -> None:
        self.zoom = self._zoom_target
        self._low_res = False
        self.request_render()             # one sharp re-draw at the final size
        self._place_overlays()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom_target * ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom_target / ZOOM_STEP)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0        # touchpads send small fractions: gentle zoom
        if steps:
            self.set_zoom(self._zoom_target * ZOOM_STEP ** steps)
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_out()
        elif k == Qt.Key.Key_0:
            self.set_zoom(1.0)
        else:
            super().keyPressEvent(e)

    # ----------------------------------------------------------- geometry
    def globe_rect(self) -> QRectF:
        d = min(self.width(), self.height()) * 0.86 * self.zoom
        return QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)

    def point_for(self, lat: float, lon: float) -> Optional[QPointF]:
        """Widget position of a place, or None if it's on the far side."""
        x, y, vis = project(lat, lon, self.c_lat, self.c_lon)
        if not vis:
            return None
        r = self.globe_rect()
        return QPointF(r.center().x() + x * r.width() / 2, r.center().y() - y * r.height() / 2)

    def marker_at(self, pos: QPointF, radius: float = 12.0) -> Optional[str]:
        best, best_d = None, radius
        for m in self.markers:
            p = self.point_for(m.lat, m.lon)
            if p is None:
                continue
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d <= best_d:
                best, best_d = m.key, d
        return best

    # -------------------------------------------------------------- state
    def set_source(self, img: Optional[QImage], when: Optional[dt.datetime], message: str = "") -> None:
        self.renderer.set_source(img)
        self.image_time = when
        if message:
            self.message = message
        if img is None:
            self.image = None
            self.update()
        else:
            self.request_render()

    def set_markers(self, markers: list[Marker], selected: Optional[str], temp_unit: str) -> None:
        changed = selected != self.selected
        self.markers, self.selected, self.temp_unit = markers, selected, temp_unit
        m = self.selected_marker()
        if changed and m is not None:
            self.turn_to(m.lat, m.lon, animate=self.isVisible())
        self.refresh_card()
        self.update()

    def selected_marker(self) -> Optional[Marker]:
        return next((m for m in self.markers if m.key == self.selected), None)

    def set_center(self, lat: float, lon: float, low_res: bool = False) -> None:
        self.c_lat = max(-85.0, min(85.0, lat))
        self.c_lon = ((lon + 180.0) % 360.0) - 180.0
        self._low_res = low_res
        self.request_render()
        self._place_overlays()

    # -------------------------------------------------------------- turning
    def turn_to(self, lat: float, lon: float, animate: bool = True) -> None:
        self.anim.stop()
        if not animate or not has_numpy():       # pure Python: jump (renders are slower)
            self.set_center(lat, lon)
            return
        dlon = ((lon - self.c_lon + 180.0) % 360.0) - 180.0          # shortest way round
        self._anim_from = (self.c_lat, self.c_lon)
        self._anim_to = (lat, self.c_lon + dlon)
        self.anim.start()

    def _anim_step(self, v) -> None:
        t = _ease(float(v))
        (a_lat, a_lon), (b_lat, b_lon) = self._anim_from, self._anim_to
        self.set_center(a_lat + (b_lat - a_lat) * t, a_lon + (b_lon - a_lon) * t, low_res=True)

    def _anim_done(self) -> None:
        self.set_center(*self._anim_to)

    def set_spin(self, on: bool) -> None:
        if on and self.isVisible():
            self._spin_last = time.monotonic()
            self.spin_timer.start()
        else:
            self.spin_timer.stop()
            if self._low_res:
                self.set_center(self.c_lat, self.c_lon)               # sharp final frame
        self._spin_wanted = on

    def _spin_step(self) -> None:
        now = time.monotonic()
        dt_ = min(0.2, now - self._spin_last)
        self._spin_last = now
        if self._drag_from is None and self.anim.state() != QVariantAnimation.State.Running:
            self.set_center(self.c_lat, self.c_lon + SPIN_DEG_PER_S * dt_, low_res=True)

    # ------------------------------------------------------------ rendering
    def request_render(self) -> None:
        self._render_timer.start(0)

    def _render_now(self) -> None:
        if not self.renderer.ready:
            return
        r = self.globe_rect()
        dpr = self.devicePixelRatioF() or 1.0
        size = int(min(MAX_RENDER, r.width() * dpr) * (DRAG_SCALE if self._low_res else 1.0))
        try:
            self.image = self.renderer.render(max(32, size), self.c_lat, self.c_lon)
            self.renders += 1
        except Exception as e:                    # never take the window down
            self.image = None
            self.message = f"The globe could not be drawn: {e}"
        self.update()

    def refresh_card(self, now: Optional[dt.datetime] = None) -> None:
        m = self.selected_marker()
        if m is None:
            self.card.hide()
            self.pulse.hide()
            return
        self.card.show_marker(m, now or dt.datetime.now(dt.timezone.utc), self.temp_unit)
        self._place_overlays()

    def _place_overlays(self) -> None:
        m = self.selected_marker()
        p = self.point_for(m.lat, m.lon) if m else None
        if p is not None and not QRectF(self.rect()).contains(p):
            p = None                           # zoomed in and it's off the edge
        if p is None:                          # nothing selected, or it's round the back
            self.card.hide()
            self.pulse.hide()
            return
        self.pulse.move(int(p.x() - self.pulse.width() / 2), int(p.y() - self.pulse.height() / 2))
        self.card.adjustSize()
        others = [q for o in self.markers if o.key != m.key and (q := self.point_for(o.lat, o.lon))]
        self.card.move(*place_card(self.card.width(), self.card.height(), p, others,
                                   self.width(), self.height()))
        self.card.show()
        self.pulse.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_zoom_controls()
        self.request_render()
        self._place_overlays()

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, "_spin_wanted", False):
            self.set_spin(True)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.spin_timer.stop()                 # no CPU while the tab isn't shown

    # ----------------------------------------------------------------- input
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # a press on a marker selects it on release - unless the mouse moves, which
        # starts a drag instead (so you can grab the globe anywhere, markers included)
        self._press_key = self.marker_at(e.position())
        self._press_pos = e.position()
        if self.globe_rect().contains(e.position()) or self._press_key:
            self.anim.stop()
            self._drag_from = e.position()
            self._drag_moved = False

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            if not self._drag_moved:
                q = e.position() - self._press_pos
                if abs(q.x()) + abs(q.y()) < 4:          # small jitter is still a click
                    return
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            d = e.position() - self._drag_from
            self._drag_from = e.position()
            k = 57.2958 / (self.globe_rect().width() / 2)              # degrees per pixel at centre
            self.set_center(self.c_lat + d.y() * k, self.c_lon - d.x() * k, low_res=True)
            self._drag_moved = True
            return
        key = self.marker_at(e.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if key else
                       (Qt.CursorShape.OpenHandCursor if self.globe_rect().contains(e.position())
                        else Qt.CursorShape.ArrowCursor))
        m = next((x for x in self.markers if x.key == key), None)
        hint = next((ind[1] for ind in self._indicators if ind[0].contains(e.position())), "")
        self.setToolTip(f"{m.name} – click to select" if m else hint or
                        ("Drag to spin · wheel to zoom" if self.globe_rect().contains(e.position()) else ""))

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            self._drag_from = None
            if self._drag_moved:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self.set_center(self.c_lat, self.c_lon)               # full-resolution frame
            elif self._press_key:
                self.location_clicked.emit(self._press_key)

    def mouseDoubleClickEvent(self, e):
        m = self.selected_marker()
        if m is not None:
            self.turn_to(m.lat, m.lon)

    # -------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.fillRect(self.rect(), QColor("#02030a"))
            r = self.globe_rect()
            c = r.center()
            rad = r.width() / 2
            t = self.image_time or dt.datetime.now(dt.timezone.utc)
            self._paint_sky(p, t, c, rad)
            p.setPen(Qt.PenStyle.NoPen)
            glow = QRadialGradient(c, rad * 1.12)
            glow.setColorAt(0.86, QColor(90, 150, 255, 0))
            glow.setColorAt(0.90, QColor(110, 170, 255, 120))
            glow.setColorAt(1.0, QColor(90, 150, 255, 0))
            p.setBrush(glow)
            p.drawEllipse(c, rad * 1.12, rad * 1.12)
            if self.image is None:
                p.setPen(QColor(200, 205, 215))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message)
                return
            p.drawImage(r, self.image)
            self._paint_sunrise_rim(p, c, rad)
            self._paint_body(p, *E.subsolar_point(t), sun=True)
            self._paint_body(p, *E.sublunar_point(t), sun=False)
            f = QFont(self.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            for m in self.markers:
                if m.key == self.selected:
                    continue
                pt = self.point_for(m.lat, m.lon)
                if pt is None:
                    continue
                p.setPen(QPen(QColor(20, 20, 20), 1.2))
                p.setBrush(QColor(255, 255, 255))
                p.drawEllipse(pt, 3.5, 3.5)
                draw_label(p, pt, m.name, self.width())
            sel = self.selected_marker()
            pt = self.point_for(sel.lat, sel.lon) if sel else None
            if pt is not None and self.card.isVisible():
                cg = self.card.geometry()
                target = QPointF(min(max(pt.x(), cg.left()), cg.right()), min(max(pt.y(), cg.top()), cg.bottom()))
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                p.drawLine(pt, target)
            self._paint_indicators(p)
        finally:
            p.end()

    # ------------------------------------------------------------ the sky
    def _moon_phase(self, t: dt.datetime):
        minute = int(t.timestamp() // 60)
        if self._phase_cache[0] != minute:
            from .moon import moon_phase
            self._phase_cache = (minute, moon_phase(t))
        return self._phase_cache[1]

    def _paint_sky(self, p: QPainter, t: dt.datetime, c: QPointF, rad: float) -> None:
        """Stars, the Sun and the Moon where they really are behind the Earth."""
        b = basis(self.c_lat, self.c_lon)
        limit = math.hypot(self.width(), self.height()) / 2 / rad + 0.1
        p.setPen(Qt.PenStyle.NoPen)
        stars = self.starfield.positions(gmst_now(t), b, limit)
        for sx, sy, size, bright in stars:
            p.setBrush(QColor(255, 255, 255, bright))
            p.drawEllipse(QPointF(c.x() + sx * rad, c.y() - sy * rad), size * 0.6, size * 0.6)
        self._indicators = []
        drawn = {"stars": len(stars)}
        view = QRectF(self.rect())
        # Sun: a limb-darkened disc with a corona, soft starburst and wide glow (a cached
        # sprite). Just behind the Earth its glow spills round the edge, like sunrise
        # seen from orbit (the bright rim is added after the globe is drawn).
        sun = ecef(*E.subsolar_point(t))
        xy = sky_xy(sun, b)
        self._sun_xy = xy
        if xy is not None:
            pt = QPointF(c.x() + xy[0] * rad, c.y() - xy[1] * rad)
            sr = max(7.0, rad * SUN_SIZE)
            sprite, core = self._sun_sprite(sr)
            half = sprite.width() / (2 * sprite.devicePixelRatio()) * (sr / core)
            if view.adjusted(-half, -half, half, half).contains(pt):
                p.drawImage(QRectF(pt.x() - half, pt.y() - half, 2 * half, 2 * half), sprite)
                drawn["sun"] = (pt.x(), pt.y(), hidden_by_earth(xy, SUN_SIZE))
        if "sun" not in drawn or not view.contains(QPointF(*drawn["sun"][:2])):
            self._add_indicator(sun, b, c, "sun")
        # Moon: NASA imagery at screen resolution, real phase, lit side towards the Sun,
        # north matching the view
        moon = ecef(*E.sublunar_point(t))
        xy = sky_xy(moon, b)
        size = max(24.0, min(float(MOON_MAX_PX), rad * MOON_SIZE * 2))
        if xy is not None:
            pt = QPointF(c.x() + xy[0] * rad, c.y() - xy[1] * rad)
            if view.adjusted(-size, -size, size, size).contains(pt) and not hidden_by_earth(xy, MOON_SIZE):
                orient = moon_orientation(moon, sun, b)
                if orient is not None:
                    ph = self._moon_phase(t)
                    img = self._moon_image(size, ph.phase_angle, orient[0])
                    if img is not None:
                        p.save()
                        p.translate(pt)
                        p.rotate(orient[1])                   # turn to the view's north (cheap)
                        p.drawImage(QRectF(-size / 2, -size / 2, size, size), img)
                        p.restore()
                        drawn["moon"] = (pt.x(), pt.y(), orient[0], orient[1], round(ph.illumination * 100))
                    else:                                  # textures missing: a plain disc
                        p.setBrush(QColor(200, 205, 215))
                        p.drawEllipse(pt, size / 2, size / 2)
                        drawn["moon"] = (pt.x(), pt.y(), None, None, None)
        if "moon" not in drawn or not view.contains(QPointF(*drawn["moon"][:2])):
            self._add_indicator(moon, b, c, "moon")
        self.sky_drawn = drawn

    def busy(self) -> bool:
        """Moving (zoom, drag, turn, spin): reuse cached Sun/Moon pictures rather than re-render."""
        return (self.zooming() or self._drag_from is not None or self.spin_timer.isActive()
                or self.anim.state() == QVariantAnimation.State.Running)

    def _moon_image(self, size: float, phase_angle: float, bright_limb: float):
        """The Moon from NASA's CGI Moon Kit at screen resolution, north up (the painter
        turns it). Cached; while the globe is moving a near-enough picture is reused."""
        dpr = self.devicePixelRatioF() or 1.0
        px = max(16, int(round(size * dpr / 8) * 8))
        limb = round(bright_limb / 2) * 2 % 360
        key = (px, round(phase_angle), limb)
        if self._moon_cache is not None:
            ckey, cimg = self._moon_cache
            if ckey == key:
                return cimg
            near = ckey[1] == key[1] and abs((ckey[2] - limb + 180) % 360 - 180) <= 8
            if self.busy() and near:
                return cimg                     # drawn scaled; sharp again once it settles
        try:
            from .moon_render import render_moon
            img = render_moon(px, phase_angle, limb, rotation=0.0)
        except Exception as e:
            log.warning("moon in globe sky: %s", e)
            return None
        self._moon_cache = (key, img)
        if self.busy():
            QTimer.singleShot(ZOOM_ANIM_MS + 60, self.update)
        return img

    def _sun_sprite(self, sr: float) -> tuple[QImage, float]:
        """A realistic Sun: limb-darkened disc, corona, soft starburst and a wide warm glow.
        Built once per size step (10%) and scaled in between, so zooming stays smooth."""
        dpr = self.devicePixelRatioF() or 1.0
        step = round(math.log(max(sr, 1.0)) / math.log(1.1))
        if self._sun_cache is not None and (self._sun_cache[0] == (step, dpr) or self.zooming()):
            return self._sun_cache[1], self._sun_cache[2]
        r = 1.1 ** step * dpr                               # core radius in device px
        glow = r * 6.0
        n = int(min(1600, 2 * glow + 4))
        glow = (n - 4) / 2
        img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        c = QPointF(n / 2, n / 2)
        g = QRadialGradient(c, glow)                        # wide scattered glow
        g.setColorAt(0.0, QColor(255, 246, 225, 170))
        g.setColorAt(0.12, QColor(255, 228, 175, 95))
        g.setColorAt(0.35, QColor(255, 200, 130, 30))
        g.setColorAt(0.7, QColor(255, 180, 110, 8))
        g.setColorAt(1.0, QColor(255, 170, 100, 0))
        p.setBrush(g)
        p.drawEllipse(c, glow, glow)
        for ang, length, width in ((0, 0.8, 0.07), (90, 0.8, 0.07), (45, 0.45, 0.05), (135, 0.45, 0.05)):
            p.save()                                        # soft starburst, like a camera sees it
            p.translate(c)
            p.rotate(ang)
            lg = QLinearGradient(QPointF(-glow * length, 0), QPointF(glow * length, 0))
            lg.setColorAt(0.0, QColor(255, 245, 225, 0))
            lg.setColorAt(0.5, QColor(255, 250, 235, 55))
            lg.setColorAt(1.0, QColor(255, 245, 225, 0))
            p.setBrush(lg)
            p.drawEllipse(QPointF(0, 0), glow * length, r * width * 2.2)
            p.restore()
        cg = QRadialGradient(c, r * 2.4)                    # corona
        cg.setColorAt(0.0, QColor(255, 255, 250, 255))
        cg.setColorAt(0.40, QColor(255, 252, 238, 235))
        cg.setColorAt(0.55, QColor(255, 236, 190, 110))
        cg.setColorAt(1.0, QColor(255, 210, 140, 0))
        p.setBrush(cg)
        p.drawEllipse(c, r * 2.4, r * 2.4)
        dg = QRadialGradient(c, r)                          # the disc, darker and warmer at the limb
        dg.setColorAt(0.0, QColor(255, 255, 253))
        dg.setColorAt(0.7, QColor(255, 251, 236))
        dg.setColorAt(1.0, QColor(255, 228, 165))
        p.setBrush(dg)
        p.drawEllipse(c, r, r)
        p.end()
        img.setDevicePixelRatio(dpr)
        self._sun_cache = ((step, dpr), img, 1.1 ** step)   # core radius in logical px
        return img, 1.1 ** step

    def _paint_sunrise_rim(self, p: QPainter, c: QPointF, rad: float) -> None:
        """When the Sun is just behind the Earth, its light blazes round that edge."""
        xy = getattr(self, "_sun_xy", None)
        if xy is None:
            return
        rr = math.hypot(*xy)
        if not 0.5 < rr < 1.6:
            return
        s = max(0.0, 1.0 - abs(rr - 1.0) / 0.6)
        if s <= 0:
            return
        ux, uy = xy[0] / rr, -xy[1] / rr
        lp = QPointF(c.x() + ux * rad, c.y() + uy * rad)
        g = QRadialGradient(lp, rad * 0.5)
        g.setColorAt(0.0, QColor(255, 240, 210, int(230 * s)))
        g.setColorAt(0.12, QColor(255, 205, 140, int(150 * s)))
        g.setColorAt(0.45, QColor(255, 150, 80, int(40 * s)))
        g.setColorAt(1.0, QColor(255, 120, 60, 0))
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(lp, rad * 0.5, rad * 0.5)
        p.restore()
        self.sky_drawn["rim"] = round(s, 2)

    def _add_indicator(self, d, b, c: QPointF, kind: str) -> None:
        """A small marker at the window edge pointing to an off-screen Sun or Moon."""
        x, y, z = to_view(d, b)
        if math.hypot(x, y) < 1e-6:
            return
        ux, uy = x / math.hypot(x, y), -y / math.hypot(x, y)
        m = 16.0
        sx = ((self.width() / 2 - m) / abs(ux)) if ux else float("inf")
        sy = ((self.height() / 2 - m) / abs(uy)) if uy else float("inf")
        s = min(sx, sy)
        pt = QPointF(self.width() / 2 + ux * s, self.height() / 2 + uy * s)
        behind = z > 0
        name = "Sun" if kind == "sun" else "Moon"
        tip = (f"The {name} is behind you, this way" if behind else
               f"The {name} is off-screen, this way")
        self._indicators.append((QRectF(pt.x() - 12, pt.y() - 12, 24, 24), tip, kind, pt, behind))

    def _paint_indicators(self, p: QPainter) -> None:
        for _rect, _tip, kind, pt, behind in self._indicators:
            p.setOpacity(0.45 if behind else 0.85)
            col = QColor(255, 214, 90) if kind == "sun" else QColor(215, 222, 240)
            g = QRadialGradient(pt, 12)
            g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 160))
            g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(pt, 12, 12)
            p.setBrush(col)
            if kind == "sun":
                p.drawEllipse(pt, 4.5, 4.5)
            else:                                     # a little crescent
                p.drawEllipse(pt, 4.5, 4.5)
                p.setBrush(QColor(2, 3, 10))
                p.drawEllipse(pt + QPointF(2.2, -1.2), 3.8, 3.8)
        p.setOpacity(1.0)

    def _paint_body(self, p: QPainter, lat: float, lon: float, sun: bool) -> None:
        pt = self.point_for(lat, lon)
        if pt is None:
            return
        rad = 7 if sun else 5
        col = QColor(255, 210, 80) if sun else QColor(210, 220, 255)
        g = QRadialGradient(pt, rad * 3)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), 150))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(pt, rad * 3, rad * 3)
        p.setBrush(col)
        p.setPen(QPen(QColor(60, 40, 0) if sun else QColor(40, 40, 60), 1))
        p.drawEllipse(pt, rad, rad)


class GlobePanel(QWidget):
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
        self.view = GlobeView()
        self.view.location_clicked.connect(self.location_clicked.emit)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.spin_box = QCheckBox("Rotate slowly")
        self.spin_box.toggled.connect(self.view.set_spin)
        if not has_numpy():
            self.spin_box.setEnabled(False)
            self.spin_box.setToolTip("Needs python3-numpy for smooth rotation")
        self.centre_btn = QPushButton("Centre on selected")
        self.centre_btn.clicked.connect(self.centre_on_selected)
        self.clouds_box = QCheckBox("Live clouds")
        self.clouds_box.setToolTip("Show near real-time satellite clouds (updated every 3 hours)")
        self.clouds_box.toggled.connect(self.clouds_toggled.emit)
        row.addWidget(self.clouds_box)
        row.addWidget(self.spin_box)
        row.addWidget(self.centre_btn)
        row.addStretch(1)
        legend = QLabel("Drag to spin  ·  wheel or +/− to zoom  ·  ☀ Sun overhead  ·  ● Moon overhead")
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

    def centre_on_selected(self) -> None:
        m = self.view.selected_marker()
        if m is not None:
            self.view.turn_to(m.lat, m.lon)

    def set_markers(self, markers, selected, temp_unit) -> None:
        self.view.set_markers(markers, selected, temp_unit)

    def retime(self) -> None:
        """Re-show times after a 12/24-hour change."""
        self.view.refresh_card()
        if self.view.image_time is not None:
            self.info.setText(info_text(self.view.image_time))

    def set_image(self, img, when, error: str = "", cloud_note: str = "") -> None:
        self.view.set_source(img, when, error)
        if when is not None:
            self.info.setText(info_text(when) + (" " + cloud_note if cloud_note else ""))
        elif error:
            self.info.setText(error)

    def needs_compose(self) -> bool:
        return time.time() - self.last_compose > RECOMPOSE_S or not self.view.renderer.ready

    def tick(self) -> None:
        self.view.refresh_card()
        if self.needs_compose():
            self.compose_requested.emit()

    def showEvent(self, e):
        super().showEvent(e)
        self.clock.start()
        self.tick()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.clock.stop()
