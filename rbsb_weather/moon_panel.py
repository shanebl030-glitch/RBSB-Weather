"""The Moon tab: current phase with a high-resolution image, moonrise/moonset,
upcoming phases, and the next 7 days.

All astronomy and image rendering runs on a background thread
(build_report), so the window never stalls; the panel only displays the
finished MoonReport.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QRadialGradient
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

from . import moon as M
from . import units
from .models import Location

BIG_PX = 560          # rendered size of the main image (sharp on HiDPI at ~280 px on screen)
SMALL_PX = 180        # 7-day thumbnails (sharp at ~90 px on HiDPI)
EXPORT_PX = 2048


@dataclass
class MoonReport:
    location: Location
    tz_name: str
    now: dt.datetime
    phase: M.Phase
    age_days: float
    days: list[M.MoonDay]
    upcoming: list[tuple[str, dt.datetime]]
    southern: bool
    view: Optional[M.SkyView] = None              # orientation in this place's sky
    day_views: list = field(default_factory=list)
    big: Optional[QImage] = None
    small: list[QImage] = field(default_factory=list)
    error: str = ""


def build_report(loc: Location, tz_name: str, utc_offset: Optional[int] = None,
                 now: Optional[dt.datetime] = None, big_px: int = BIG_PX,
                 small_px: int = SMALL_PX) -> MoonReport:
    """Compute everything for the Moon tab (safe to call on a worker thread)."""
    from . import moon_render as R
    tz = M.tz_for(tz_name, utc_offset)
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    phase = M.moon_phase(now)
    days = M.moon_days(loc.latitude, loc.longitude, tz, now.date(), 7)
    rep = MoonReport(location=loc, tz_name=tz_name, now=now, phase=phase, age_days=M.age_days(now),
                     days=days, upcoming=M.upcoming_phases(now, tz), southern=loc.latitude < 0)
    # orientation exactly as in this place's sky: now if the Moon is up, otherwise at
    # its next highest point; each of the 7 days at that day's highest point
    rep.view = M.sky_view(now, loc.latitude, loc.longitude, tz)
    rep.day_views = [M.day_view(d.date, loc.latitude, loc.longitude, tz) for d in days]
    try:
        big_phase = phase if rep.view.is_now else M.moon_phase(rep.view.when)
        rep.big = R.render_moon(big_px, big_phase.phase_angle, big_phase.bright_limb,
                                rotation=rep.view.rotation)
        rep.small = []
        for d, v in zip(days, rep.day_views):
            ph = M.moon_phase(v.when)
            rep.small.append(R.render_moon(small_px, ph.phase_angle, ph.bright_limb, rotation=v.rotation))
    except R.MoonTextureError as e:
        rep.error = str(e)
    return rep


def fmt_time(t: Optional[dt.datetime]) -> str:
    return units.fmt_clock(t)


def fmt_day(d: dt.date, today: dt.date) -> str:
    if d == today:
        return "Today"
    if d == today + dt.timedelta(days=1):
        return "Tomorrow"
    return d.strftime("%a %d")


class MoonImage(QWidget):
    """Shows a moon QImage on a night-sky background, scaled crisply (HiDPI aware)."""

    def __init__(self, min_px: int, parent=None, glow: bool = True):
        super().__init__(parent)
        self.image: Optional[QImage] = None
        self.glow = glow
        self.placeholder = "Calculating…"
        self.setMinimumSize(min_px, min_px)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, img: Optional[QImage]) -> None:
        self.image = img
        self.update()

    def sizeHint(self):
        return QSize(self.minimumWidth(), self.minimumHeight())

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            r = QRectF(self.rect())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#05070d"))
            p.drawRoundedRect(r, 10, 10)
            side = min(r.width(), r.height()) * 0.88
            target = QRectF(r.center().x() - side / 2, r.center().y() - side / 2, side, side)
            if self.image is None:
                p.setPen(QColor(200, 205, 215))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.placeholder)
                return
            if self.glow:
                g = QRadialGradient(target.center(), side * 0.62)
                g.setColorAt(0.75, QColor(200, 210, 235, 40))
                g.setColorAt(1.0, QColor(200, 210, 235, 0))
                p.setBrush(g)
                p.drawEllipse(target.center(), side * 0.62, side * 0.62)
            p.drawImage(target, self.image)
        finally:
            p.end()


class MoonPanel(QWidget):
    save_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.report: Optional[MoonReport] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)

        top = QHBoxLayout()
        self.big = MoonImage(220)
        top.addWidget(self.big, 3)
        info = QVBoxLayout()
        self.name_label = QLabel("–")
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.8); f.setBold(True)
        self.name_label.setFont(f)
        info.addWidget(self.name_label)
        self.illum_label = QLabel()
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.15)
        self.illum_label.setFont(f)
        info.addWidget(self.illum_label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        self.facts: dict[str, QLabel] = {}
        for i, (key, title) in enumerate((("rise", "Moonrise today"), ("set", "Moonset today"),
                                          ("sky", "In the sky"), ("dist", "Distance"),
                                          ("tz", "Times shown in"))):
            t = QLabel(title)
            t.setStyleSheet("color: palette(placeholder-text);")
            v = QLabel("–")
            for lbl in (t, v):     # never squeeze these rows together
                lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            grid.addWidget(t, i, 0)
            grid.addWidget(v, i, 1)
            self.facts[key] = v
        f = QFont(self.font()); f.setPointSizeF(f.pointSizeF() * 1.25); f.setBold(True)
        self.facts["rise"].setFont(f)
        self.facts["set"].setFont(f)
        info.addLayout(grid)
        hdr = QLabel("Upcoming phases")
        hdr.setStyleSheet("font-weight: bold; margin-top: 8px;")
        info.addWidget(hdr)
        self.upcoming_labels = [QLabel() for _ in range(4)]
        for lbl in self.upcoming_labels:
            info.addWidget(lbl)
        info.addStretch(1)
        # every text line keeps at least its own height, so the layout can never
        # squash rows together (the window's minimum size grows instead)
        for lbl in [self.name_label, self.illum_label, hdr, *self.upcoming_labels,
                    *(l for i in range(grid.count()) if isinstance(l := grid.itemAt(i).widget(), QLabel))]:
            lbl.setMinimumHeight(lbl.fontMetrics().height() + 2)
        hdr.setMinimumHeight(hdr.fontMetrics().height() + 12)     # room for its top margin
        self.save_btn = QPushButton("Save high-resolution image…")
        self.save_btn.setToolTip(f"Save this moon as a {EXPORT_PX}×{EXPORT_PX} PNG")
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.save_btn.setEnabled(False)
        info.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignLeft)

        top.addLayout(info, 2)
        root.addLayout(top, 3)

        hdr = QLabel("Next 7 days")
        hdr.setStyleSheet("font-weight: bold;")
        root.addWidget(hdr)
        week = QFrame()
        week.setFrameShape(QFrame.Shape.StyledPanel)
        wl = QHBoxLayout(week)
        wl.setSpacing(6)
        self.day_cells: list[dict] = []
        for _ in range(7):
            cell = QVBoxLayout()
            d = {"day": QLabel(), "img": MoonImage(64, glow=False), "name": QLabel(),
                 "pct": QLabel(), "rise": QLabel(), "set": QLabel()}
            d["img"].placeholder = ""
            for k in ("day", "name", "pct", "rise", "set"):
                d[k].setAlignment(Qt.AlignmentFlag.AlignHCenter)
            d["day"].setStyleSheet("font-weight: bold;")
            d["name"].setWordWrap(True)
            sm = QFont(self.font()); sm.setPointSizeF(sm.pointSizeF() * 0.9)
            for k in ("name", "pct", "rise", "set"):
                d[k].setFont(sm)
            for k in ("day", "img", "name", "pct", "rise", "set"):
                cell.addWidget(d[k])
            wl.addLayout(cell, 1)
            self.day_cells.append(d)
        root.addWidget(week, 2)
        # short credit line; full credit in the tooltip and the About box
        self.credit_label = QLabel()
        self.credit_label.setStyleSheet("color: palette(placeholder-text);")
        try:
            from .moon_render import texture_meta
            meta = texture_meta()
            if meta.get("source") == "nasa-cgi-moon-kit":
                self.credit_label.setText("Moon imagery: NASA Scientific Visualization Studio (CGI Moon Kit)")
            self.credit_label.setToolTip(meta.get("credit", ""))
        except Exception:
            pass
        self.credit_label.setVisible(bool(self.credit_label.text()))
        root.addWidget(self.credit_label)
        self.clear("Select a location to see the Moon.")

    # ----------------------------------------------------------------
    def clear(self, message: str = "") -> None:
        self.report = None
        self.big.placeholder = message or "Calculating…"
        self.big.set_image(None)
        self.name_label.setText("Moon")
        self.illum_label.setText(message)
        for v in self.facts.values():
            v.setText("–")
        for lbl in self.upcoming_labels:
            lbl.setText("")
        for d in self.day_cells:
            for k in ("day", "name", "pct", "rise", "set"):
                d[k].setText("")
            d["img"].set_image(None)
        self.save_btn.setEnabled(False)

    def show_report(self, rep: MoonReport) -> None:
        self.report = rep
        ph = rep.phase
        self.name_label.setText(ph.name)
        self.illum_label.setText(f"{ph.illumination * 100:.0f}% illuminated  ·  "
                                 f"{rep.age_days:.1f} days old  ·  "
                                 f"{'waxing' if ph.waxing else 'waning'}")
        today = rep.days[0] if rep.days else None
        self.facts["rise"].setText(self._rise_text(today))
        self.facts["set"].setText(self._set_text(today))
        self.facts["dist"].setText(f"{ph.distance_km:,.0f} km")
        self.facts["sky"].setText(self.sky_text(rep))
        self.facts["sky"].setToolTip("The picture is turned exactly as the Moon appears in this "
                                     "place's sky (its parallactic angle), so the tilt of the "
                                     "crescent matches what you'd see looking up. When the Moon "
                                     "is below the horizon, it's shown as it will look at its "
                                     "highest point.")
        self.facts["tz"].setText(f"{rep.location.name} local time ({rep.now.strftime('%Z') or rep.tz_name})")
        for lbl, (name, when) in zip(self.upcoming_labels, rep.upcoming):
            lbl.setText(f"{name}:  {when.strftime('%a %d %b')}, {units.fmt_clock(when)}")
        self.big.placeholder = rep.error or "Calculating…"
        self.big.set_image(rep.big)
        for i, d in enumerate(self.day_cells):
            if i >= len(rep.days):
                continue
            md = rep.days[i]
            d["day"].setText(fmt_day(md.date, rep.now.date()))
            d["name"].setText(md.name)
            d["pct"].setText(f"{md.phase.illumination * 100:.0f}%")
            d["rise"].setText("↑ " + self._rise_text(md))
            d["set"].setText("↓ " + self._set_text(md))
            d["img"].set_image(rep.small[i] if i < len(rep.small) else None)
            v = rep.day_views[i] if i < len(rep.day_views) else None
            d["img"].setToolTip(f"{md.name}, {md.phase.illumination * 100:.0f}% illuminated"
                                + (f"\nShown as at its highest, {units.fmt_clock(v.when, day=True)} "
                                   f"({v.altitude:.0f}° up)" if v and v.up else ""))
        self.save_btn.setEnabled(rep.big is not None)

    @staticmethod
    def sky_text(rep: MoonReport) -> str:
        from .units import compass
        v = rep.view
        if v is None:
            return "–"
        if v.is_now:
            return f"Up now · {v.altitude:.0f}° high in the {compass(v.azimuth)}"
        if v.up:
            return f"Below horizon · shown at its highest, {units.fmt_clock(v.when, day=True)}"
        return "Below the horizon all day · shown at its highest"

    @staticmethod
    def _rise_text(md: Optional[M.MoonDay]) -> str:
        if md is None:
            return "–"
        if md.rise:
            return fmt_time(md.rise)
        return "up all day" if md.always_up else "no moonrise"

    @staticmethod
    def _set_text(md: Optional[M.MoonDay]) -> str:
        if md is None:
            return "–"
        if md.set:
            return fmt_time(md.set)
        return "down all day" if md.always_down else "no moonset"
