"""Earthquakes drawn on the Earth tabs (2.5): a dot per quake, sized by magnitude and
coloured by age, with pulsing rings for the last hour; hover for details, click for a
card with a link to the quake's page.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import quakes as Q
from .scene import AnimationClock, _Animated


class QuakeLayer(_Animated):
    """Transparent overlay over a map or globe. `project(lat, lon)` gives a widget
    point, or None when the place is out of sight (the far side of the globe)."""

    update_every = 2

    def __init__(self, parent: QWidget, project: Callable[[float, float], Optional[QPointF]]):
        super().__init__(parent)
        self.project = project
        self.quakes: list[Q.Quake] = []
        self.selected: Optional[str] = None
        self.enabled = True
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.drawn: list[tuple] = []            # (quake id, point) of the last paint, for hit tests and tests
        self.pulsing = 0
        self._sync_clock()

    def set_quakes(self, quakes: list[Q.Quake], selected: Optional[str] = None) -> None:
        # biggest last, so they're drawn on top of the small ones
        self.quakes = sorted(quakes, key=lambda q: q.mag)
        self.selected = selected
        self._sync_clock()
        self.update()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.setVisible(self.enabled)
        self._sync_clock()

    def _sync_clock(self) -> None:
        """Only quakes in the last hour pulse; with none, the overlay needs no animation."""
        now = time.time()
        self.pulsing = sum(1 for q in self.quakes if q.age(now) < Q.PULSE_S) if self.enabled else 0
        clock = AnimationClock.instance()
        if self.pulsing or self.selected:
            clock.register(self)
        else:
            clock.unregister(self)

    def quake_at(self, pos: QPointF, slack: float = 5.0) -> Optional[Q.Quake]:
        if not self.enabled:
            return None
        best, best_d = None, None
        for q in self.quakes:
            p = self.project(q.lat, q.lon)
            if p is None:
                continue
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d <= Q.radius(q.mag) + slack and (best_d is None or d < best_d):
                best, best_d = q, d
        return best

    def paintEvent(self, _e):
        if not self.enabled or not self.quakes:
            self.drawn = []
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            now = time.time()
            drawn = []
            for q in self.quakes:
                pt = self.project(q.lat, q.lon)
                if pt is None:
                    continue
                drawn.append((q.id, pt))
                col = QColor(Q.colour(q, now))
                r = Q.radius(q.mag)
                age = q.age(now)
                if age < Q.PULSE_S or q.id == self.selected:
                    # two rings expanding out of the dot; faster and wider for bigger quakes
                    for k in (0.0, 0.5):
                        ph = (self.t * 0.7 + k) % 1.0
                        ring = QColor(col)
                        ring.setAlpha(int(230 * (1 - ph)))
                        p.setPen(QPen(ring, 2.0))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        rr = r + (10 + r * 1.6) * ph
                        p.drawEllipse(pt, rr, rr)
                fill = QColor(col)
                fill.setAlpha(215 if age < 86400 else 150)
                p.setPen(QPen(QColor(20, 20, 20, 200), 1.0))
                p.setBrush(fill)
                p.drawEllipse(pt, r, r)
                if q.id == self.selected:
                    p.setPen(QPen(QColor(255, 255, 255), 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(pt, r + 3, r + 3)
            self.drawn = drawn
        finally:
            p.end()


class QuakeCard(QFrame):
    """The card shown for a clicked quake."""

    link_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("quakeCard")
        self.setStyleSheet("#quakeCard { background: rgba(10, 14, 28, 225); border: 1px solid "
                           "rgba(255,120,90,170); border-radius: 8px; } QLabel { color: white; "
                           "background: transparent; } a { color: #9cc7ff; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        self.title = QLabel()
        f = self.title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.1)
        self.title.setFont(f)
        self.lines = QLabel()
        self.lines.setWordWrap(True)
        self.lines.setMaximumWidth(300)
        self.link = QLabel()
        self.link.setTextFormat(Qt.TextFormat.RichText)
        self.link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.link.linkActivated.connect(self.link_clicked.emit)
        for w in (self.title, self.lines, self.link):
            lay.addWidget(w)
        self.quake: Optional[Q.Quake] = None

    def show_quake(self, q: Q.Quake, places: list, now: Optional[float] = None) -> None:
        self.quake = q
        self.title.setText(f"M{q.mag:.1f} earthquake")
        rows = []
        if q.place:
            rows.append(q.place)
        if q.depth_km is not None:
            rows.append(f"{q.depth_km:.0f} km deep")
        rows.append(Q.ago(q.age(now)).capitalize())
        near = Q.nearest(q, places)
        if near is not None:
            rows.append(f"{near[1]:.0f} km from {near[0].name}")
        if q.tsunami and q.mag >= 6.5:
            rows.append("Large quake under the sea: check official tsunami advice")
        self.lines.setText("\n".join(rows))
        site = "GeoNet" if q.source == "GeoNet" else "USGS"
        self.link.setText(f"<a style='color:#9cc7ff;' href='{q.url}'>Details on {site} ›</a>" if q.url
                          else f"From {site}")
        self.adjustSize()


class QuakeHost:
    """Mixed into EarthMap and GlobeView: their quake overlay, card and mouse handling.
    The host has point_for(lat, lon), a `card` (the place card) and emits quake_link(url)."""

    def _init_quakes(self) -> None:
        self.quake_layer = QuakeLayer(self, self.point_for)
        self.quake_layer.setGeometry(self.rect())
        self.quake_card = QuakeCard(self)
        self.quake_card.hide()
        self.quake_card.link_clicked.connect(self.quake_link.emit)
        self.quake_places: list = []
        for w in (getattr(self, "pulse", None), getattr(self, "card", None), self.quake_card):
            if w is not None:
                w.raise_()

    def set_quakes(self, quakes: list, places: list, enabled: bool = True) -> None:
        self.quake_places = list(places)
        sel = self.quake_card.quake.id if self.quake_card.isVisible() and self.quake_card.quake else None
        if sel and not any(q.id == sel for q in quakes):
            sel = None
            self.quake_card.hide()
        self.quake_layer.set_quakes(quakes, sel)
        self.quake_layer.set_enabled(enabled)
        if not enabled:
            self.quake_card.hide()
        elif sel:
            q = next(q for q in quakes if q.id == sel)
            self.quake_card.show_quake(q, self.quake_places)
            self._place_quake_card()

    def show_quake(self, quake_id: str) -> bool:
        q = next((x for x in self.quake_layer.quakes if x.id == quake_id), None)
        if q is None:
            return False
        self.quake_card.show_quake(q, self.quake_places)
        self.quake_card.show()
        self.quake_card.raise_()
        self.quake_layer.selected = q.id
        self.quake_layer._sync_clock()
        self._place_quake_card()
        self.quake_layer.update()
        return True

    def hide_quake(self) -> None:
        self.quake_card.hide()
        if self.quake_layer.selected:
            self.quake_layer.selected = None
            self.quake_layer._sync_clock()
            self.quake_layer.update()

    def _place_quake_card(self) -> None:
        q = self.quake_card.quake
        if q is None or not self.quake_card.isVisible():
            return
        p = self.point_for(q.lat, q.lon)
        c = self.quake_card
        c.adjustSize()
        if p is None:                                 # turned out of sight: park in the corner
            c.move(8, 8)
            return
        from PyQt6.QtCore import QRect
        w, h = c.width(), c.height()
        place = getattr(self, "card", None)
        busy = place.geometry() if place is not None and place.isVisible() else QRect()

        def clamp(x, y):
            return (int(max(4, min(x, self.width() - w - 4))), int(max(4, min(y, self.height() - h - 4))))
        # beside the quake, then below or above it: the first spot clear of the place card
        spots = [clamp(p.x() + 16, p.y() - h / 2), clamp(p.x() - 16 - w, p.y() - h / 2),
                 clamp(p.x() - w / 2, p.y() + 16), clamp(p.x() - w / 2, p.y() - 16 - h)]
        for x, y in spots:
            r = QRect(x, y, w, h)
            if not r.intersects(busy) and not r.contains(int(p.x()), int(p.y())):
                c.move(x, y)
                return
        c.move(*spots[0])

    def _quakes_resized(self) -> None:
        self.quake_layer.setGeometry(self.rect())
        self._place_quake_card()

    def _quake_tip(self, pos: QPointF) -> str:
        q = self.quake_layer.quake_at(pos)
        return Q.describe(q) + " – click for details" if q else ""

    def _quake_click(self, pos: QPointF) -> bool:
        """A click: show the card of the quake under the mouse (True), or hide the card."""
        q = self.quake_layer.quake_at(pos)
        if q is None:
            self.hide_quake()
            return False
        self.show_quake(q.id)
        return True
