"""The Warnings tab (2.4): every warning for the selected place, in full.

Official warnings show their own wording, area and times, who issued them, and a
link to the issuer. "My own limits" alerts have a dashed edge and say they're
not official.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from . import alerts as A
from . import units

ADVICE = {"red": "Take action now", "orange": "Take action", "yellow": "Be aware",
          "watch": "Be alert: severe weather is possible", "minor": "For information",
          "limit": "From the forecast · not an official warning"}


def zone_for(loc, utc_offset: Optional[int]):
    """The place's own time zone (for showing a warning's times as the place sees them)."""
    try:
        from zoneinfo import ZoneInfo
        if loc is not None and loc.timezone and loc.timezone != "auto":
            return ZoneInfo(loc.timezone)
    except Exception:
        pass
    return dt.timezone(dt.timedelta(seconds=utc_offset or 0))


def when_text(t: Optional[float], tz) -> str:
    if t is None:
        return "–"
    d = dt.datetime.fromtimestamp(t, tz)
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}, {units.fmt_clock(d)}"


def short_until(t: Optional[float], tz, now: Optional[float] = None) -> str:
    """"until 6:00 pm" today, "until Mon 6:00 pm" another day."""
    if t is None:
        return ""
    d = dt.datetime.fromtimestamp(t, tz)
    today = dt.datetime.fromtimestamp(now if now is not None else dt.datetime.now().timestamp(), tz).date()
    return f"until {units.fmt_clock(d)}" if d.date() == today else f"until {units.fmt_clock(d, day=True)}"


def status_text(a: A.Alert, tz, now: float) -> str:
    if a.onset is not None and a.onset > now:
        d = dt.datetime.fromtimestamp(a.onset, tz)
        return f"From {units.fmt_clock(d, day=True)}"
    return "In force now"


class AlertCard(QFrame):
    def __init__(self, alert: A.Alert, tz, now: float, muted: bool, rain_mm: Optional[float],
                 precip_unit: str, site: str, parent=None):
        super().__init__(parent)
        self.alert = alert
        bg, fg = A.COLOURS.get(alert.level, A.COLOURS["minor"])
        self.setObjectName("alertCard")
        edge = "dashed #7a8aa0" if not alert.official else f"solid {bg}"
        self.setStyleSheet(f"#alertCard {{ border: 2px {edge}; border-radius: 8px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(6)

        head = QFrame()
        head.setObjectName("alertHead")
        head.setStyleSheet(f"#alertHead {{ background: {bg}; border-top-left-radius: 6px; "
                           f"border-top-right-radius: 6px; }} QLabel {{ color: {fg}; background: transparent; }}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12, 8, 12, 8)
        badge = QLabel(alert.badge)
        badge.setStyleSheet(f"border: 1px solid {fg}; border-radius: 3px; padding: 0 5px; font-weight: bold;")
        hl.addWidget(badge)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title_label = QLabel(alert.title())
        f = self.title_label.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.title_label.setFont(f)
        self.title_label.setWordWrap(True)
        titles.addWidget(self.title_label)
        titles.addWidget(QLabel(ADVICE.get(alert.level, "")))
        hl.addLayout(titles, 1)
        state = QLabel("Muted" if muted else status_text(alert, tz, now))
        fb = state.font()
        fb.setBold(True)
        state.setFont(fb)
        hl.addWidget(state, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(head)

        grid = QGridLayout()
        grid.setContentsMargins(12, 2, 12, 2)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        rows = []
        if alert.area:
            rows.append(("Area", alert.area))
        rows.append(("Valid", f"{when_text(alert.onset, tz)}  →  {when_text(alert.expires, tz)}"))
        if alert.description:
            rows.append(("Expected" if alert.official else "Details", alert.description))
        if alert.instruction:
            rows.append(("What to do", alert.instruction))
        if alert.official:
            issued = f"{alert.source}, {when_text(alert.issued, tz)}" if alert.issued else alert.source
            rows.append(("Issued by", issued))
        if rain_mm is not None and alert.hazard in ("rain", "flood"):
            rows.append(("Forecast", f"RBSB-Weather's forecast shows {units.fmt_precip(rain_mm, precip_unit)} "
                                     f"of rain over the same hours"))
        self.rows = {}
        for r, (k, v) in enumerate(rows):
            kl = QLabel(k)
            fk = kl.font()
            fk.setBold(True)
            kl.setFont(fk)
            kl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            vl = QLabel(v)
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            vl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            grid.addWidget(kl, r, 0)
            grid.addWidget(vl, r, 1)
            self.rows[k] = vl
        lay.addLayout(grid)

        btns = QHBoxLayout()
        btns.setContentsMargins(12, 2, 12, 0)
        self.open_btn = QPushButton(f"Open on {site}" if site else "Open the warning")
        self.open_btn.setVisible(bool(alert.url))
        btns.addWidget(self.open_btn)
        self.map_btn = QPushButton("Show on Earth map")
        btns.addWidget(self.map_btn)
        self.mute_btn = QPushButton("Unmute" if muted else "Mute this warning")
        self.mute_btn.setToolTip("A muted warning stays listed here, but leaves the banner, badges and "
                                 "notifications until it changes level or is reissued.")
        btns.addWidget(self.mute_btn)
        self.limits_btn = QPushButton("Change my limits…")
        self.limits_btn.setVisible(not alert.official)
        btns.addWidget(self.limits_btn)
        if not alert.official:
            self.mute_btn.setVisible(False)
        btns.addStretch(1)
        lay.addLayout(btns)


class AlertsPanel(QWidget):
    open_url = pyqtSignal(str)
    show_map = pyqtSignal()
    mute = pyqtSignal(str, bool)           # alert id, muted
    edit_limits = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 6, 4, 4)
        top = QHBoxLayout()
        self.heading = QLabel("Weather warnings")
        fh = self.heading.font()
        fh.setBold(True)
        fh.setPointSizeF(fh.pointSizeF() * 1.1)
        self.heading.setFont(fh)
        top.addWidget(self.heading, 1)
        self.checked = QLabel("")
        self.checked.setStyleSheet("color: palette(placeholder-text);")
        top.addWidget(self.checked)
        self.settings_btn = QPushButton("Settings…")
        self.settings_btn.clicked.connect(self.edit_limits.emit)
        top.addWidget(self.settings_btn)
        outer.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(self.scroll, 1)
        self.foot = QLabel("Official warnings come straight from the national weather service and are shown as "
                           "issued. Always follow official advice and Civil Defence or emergency services' "
                           "instructions.")
        self.foot.setWordWrap(True)
        self.foot.setStyleSheet("color: palette(placeholder-text);")
        outer.addWidget(self.foot)
        self.cards: list[AlertCard] = []
        self.empty_label: Optional[QLabel] = None
        self.set_data(None, [], [], 0.0, "", "")

    def set_data(self, loc, alerts: list[A.Alert], muted_ids, now: float, checked_text: str, coverage: str,
                 fc=None, precip_unit: str = "mm", min_level: str = "watch") -> None:
        tz = zone_for(loc, fc.utc_offset_seconds if fc is not None else None)
        self.heading.setText(f"Weather warnings for {loc.name}" if loc is not None else "Weather warnings")
        self.checked.setText(checked_text)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 6, 4)
        lay.setSpacing(10)
        self.cards = []
        self.empty_label = None
        muted = set(muted_ids)
        listed = [a for a in A.sort_alerts(alerts) if a.active(now)]
        cut = A.shown(listed, min_level, (), now)
        listed = [a for a in listed if a in cut]
        if not listed:
            text = ("Add a place to see its warnings." if loc is None else
                    f"No warnings for {loc.name} right now.\n\n{coverage}")
            self.empty_label = QLabel(text)
            self.empty_label.setWordWrap(True)
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            lay.addWidget(self.empty_label)
        else:
            if coverage:
                cov = QLabel(coverage)
                cov.setWordWrap(True)
                cov.setStyleSheet("color: palette(placeholder-text);")
                lay.addWidget(cov)
        site = ""
        for a in listed:
            if a.official and a.url:
                try:
                    from urllib.parse import urlsplit
                    site = urlsplit(a.url).hostname or ""
                    site = site[4:] if site.startswith("www.") else site
                except ValueError:
                    site = ""
            rain = A.rain_between(fc, a.onset or now, a.expires) if fc is not None and a.official else None
            card = AlertCard(a, tz, now, a.id in muted, rain, precip_unit, site)
            card.open_btn.clicked.connect(lambda _=False, u=a.url: self.open_url.emit(u))
            card.map_btn.clicked.connect(self.show_map.emit)
            card.mute_btn.clicked.connect(lambda _=False, i=a.id, m=a.id in muted: self.mute.emit(i, not m))
            card.limits_btn.clicked.connect(self.edit_limits.emit)
            lay.addWidget(card)
            self.cards.append(card)
        lay.addStretch(1)
        old = self.scroll.takeWidget()
        self.scroll.setWidget(body)
        if old is not None:
            old.deleteLater()
