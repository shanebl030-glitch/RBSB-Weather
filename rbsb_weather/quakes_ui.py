"""Earthquakes in the main window (2.5): checks in the background, the dots on the
Earth tabs, notifications, and Settings → Earthquakes.

Mixed into MainWindow.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QSpinBox, QSystemTrayIcon, QVBoxLayout)

from . import quakes as Q

log = logging.getLogger(__name__)


class QuakesMixin:
    def _init_quakes_ui(self, quake_client=None) -> None:
        self.quake_client = quake_client or Q.QuakeClient()
        self.quake_store = Q.QuakeStore(self.cache.dir).load()
        self._quakes_token = 0
        self._quakes_busy = False
        self._quake_click_id: Optional[str] = None
        self._quakes_dialog = None
        self.quake_notices: list[tuple[str, str]] = []           # (title, body), for tests and the log
        self.bridge.quakes_ok.connect(self._on_quakes_ok)
        for panel in (self.earth_panel, self.globe_panel):
            panel.quakes_box.setChecked(self.settings.quakes_show)
            panel.quakes_toggled.connect(self.set_quakes_shown)
            panel.quake_link.connect(lambda u: self.open_url(u))
        self.quake_timer = QTimer(self)
        self.quake_timer.timeout.connect(self.check_quakes)
        self._apply_quake_interval()
        self._show_quakes()

    def _apply_quake_interval(self) -> None:
        self.quake_timer.start(int(self.settings.quakes_interval) * 60_000)

    def _quakes_wanted(self) -> bool:
        s = self.settings
        return s.quakes_show or s.quakes_notify_near or s.quakes_notify_major

    def check_quakes(self) -> None:
        if self._quitting or self._quakes_busy or not self._quakes_wanted():
            return
        self._quakes_busy = True
        self._quakes_token += 1
        s = self.settings
        # notifications need M4.5+ near places even when the maps show only bigger ones
        min_mag = 2.5 if s.quakes_min_mag < 4.5 or (s.quakes_notify_near and s.quakes_near_mag < 4.5) else 4.5
        self.worker.quakes_update(self._quakes_token, self.quake_client, s.quakes_period, min_mag)

    def _on_quakes_ok(self, token: int, got: list, errors: dict) -> None:
        if token != self._quakes_token:
            return
        self._quakes_busy = False
        self.quake_store.update(got, errors)
        if errors:
            log.info("quakes: %s", errors)
        self._show_quakes()
        self._notify_quakes()
        self.quake_store.save()

    def shown_quakes(self, now: Optional[float] = None) -> list[Q.Quake]:
        s = self.settings
        return Q.within(self.quake_store.quakes, Q.PERIODS[s.quakes_period], s.quakes_min_mag, now)

    def _show_quakes(self) -> None:
        qs = self.shown_quakes()
        places = list(self.settings.locations)
        for view in (self.earth_panel.map, self.globe_panel.view):
            view.set_quakes(qs, places, self.settings.quakes_show)
        n = len(qs)
        tip = (f"{n} earthquake{'s' if n != 1 else ''} in the past {self.settings.quakes_period}"
               if self.quake_store.checked else "Earthquakes haven't been checked yet")
        for panel in (self.earth_panel, self.globe_panel):
            panel.quakes_box.setText(f"Earthquakes ({n})" if self.settings.quakes_show and n else "Earthquakes")
            panel.quakes_box.setStatusTip(tip)

    def _notify_quakes(self) -> None:
        s = self.settings
        st = self.quake_store
        rules = Q.NotifyRules(s.quakes_notify_near, s.quakes_near_mag, s.quakes_near_km,
                              s.quakes_notify_major, s.quakes_major_mag)
        fresh = Q.to_notify(st.quakes, list(s.locations), rules, st.notified)
        if not fresh:
            return
        st.notified += [q.id for q, _ in fresh]
        st.notified = st.notified[-500:]
        q, near = fresh[0]
        title, body = Q.notice(q, near)
        if len(fresh) > 1:
            body += f"\n(and {len(fresh) - 1} more: see the Earth tabs)"
        self.quake_notices.append((title, body))
        self._quake_click_id = q.id
        self._tray_click = "quake"
        if self.tray is not None and self.tray.isVisible():
            icon = QSystemTrayIcon.MessageIcon.Warning if q.mag >= 6 else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage(f"🌐 {title}", body, icon, 20_000)
        else:
            self.statusBar().showMessage(f"{title} — {body.splitlines()[0]}", 30_000)

    def show_quake_on_globe(self, quake_id: Optional[str] = None) -> None:
        """Open the Earth Globe turned to a quake, with its card (a notification click)."""
        qid = quake_id or self._quake_click_id
        q = next((x for x in self.quake_store.quakes if x.id == qid), None)
        self.tabs.setCurrentWidget(self.globe_panel)
        if q is None:
            return
        if not self.settings.quakes_show:
            self.set_quakes_shown(True)
        if not any(x.id == q.id for x in self.globe_panel.view.quake_layer.quakes):
            self.globe_panel.view.quake_layer.set_quakes(self.shown_quakes() + [q])
        self.globe_panel.view.turn_to(q.lat, q.lon)
        QTimer.singleShot(800, lambda: self.globe_panel.view.show_quake(q.id))

    def _on_quake_notice_clicked(self) -> None:
        self.show_normal()
        self.show_quake_on_globe()

    def set_quakes_shown(self, on: bool) -> None:
        self.settings.quakes_show = bool(on)
        for panel in (self.earth_panel, self.globe_panel):
            panel.quakes_box.blockSignals(True)
            panel.quakes_box.setChecked(self.settings.quakes_show)
            panel.quakes_box.blockSignals(False)
        self.save_settings()
        self._show_quakes()
        if on and not self.quake_store.checked:
            self.check_quakes()

    # --------------------------------------------------------------- settings
    def show_quake_settings(self) -> None:
        if self._quakes_dialog is not None:
            self._quakes_dialog.close()
            self._quakes_dialog.deleteLater()
        dlg = QuakesDialog(self.settings, self)
        dlg.applied.connect(self.apply_quake_settings)
        self._quakes_dialog = dlg
        dlg.show()
        dlg.raise_()

    def apply_quake_settings(self, values: dict) -> None:
        s = self.settings
        before = (s.quakes_period, s.quakes_min_mag, s.quakes_near_mag, s.quakes_interval)
        for k, v in values.items():
            if hasattr(s, k):
                setattr(s, k, v)
        self.save_settings()
        self.set_quakes_shown(s.quakes_show)
        if s.quakes_interval != before[3]:
            self._apply_quake_interval()
        if (s.quakes_period, s.quakes_min_mag, s.quakes_near_mag) != before[:3]:
            self.check_quakes()


from PyQt6.QtCore import pyqtSignal  # noqa: E402


class QuakesDialog(QDialog):
    applied = pyqtSignal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Earthquakes")
        lay = QVBoxLayout(self)

        g = QGroupBox("On the Earth tabs")
        gl = QGridLayout(g)
        self.show_box = QCheckBox("Show recent earthquakes")
        self.show_box.setChecked(settings.quakes_show)
        gl.addWidget(self.show_box, 0, 0, 1, 2)
        gl.addWidget(QLabel("From the past"), 1, 0)
        self.period = QComboBox()
        self.period.addItem("day", "day")
        self.period.addItem("week", "week")
        self.period.setCurrentIndex(0 if settings.quakes_period == "day" else 1)
        gl.addWidget(self.period, 1, 1)
        gl.addWidget(QLabel("Magnitude"), 2, 0)
        self.min_mag = QComboBox()
        self.min_mag.addItem("2.5 and up (many small quakes)", 2.5)
        self.min_mag.addItem("4.5 and up (fewer, bigger quakes)", 4.5)
        self.min_mag.setCurrentIndex(0 if settings.quakes_min_mag < 4.5 else 1)
        gl.addWidget(self.min_mag, 2, 1)
        legend = QLabel("Red: in the last hour (pulsing) · orange: 6 hours · yellow: a day · grey: older. "
                        "Bigger dots are bigger quakes.")
        legend.setWordWrap(True)
        legend.setStyleSheet("color: palette(placeholder-text);")
        gl.addWidget(legend, 3, 0, 1, 2)
        lay.addWidget(g)

        g = QGroupBox("Notify me")
        gl = QGridLayout(g)
        self.near = QCheckBox("Of a quake near one of my places: magnitude")
        self.near.setChecked(settings.quakes_notify_near)
        self.near_mag = QDoubleSpinBox()
        self.near_mag.setRange(2.5, 9.0)
        self.near_mag.setDecimals(1)
        self.near_mag.setSingleStep(0.5)
        self.near_mag.setValue(settings.quakes_near_mag)
        self.near_km = QSpinBox()
        self.near_km.setRange(10, 2000)
        self.near_km.setSingleStep(50)
        self.near_km.setSuffix(" km")
        self.near_km.setValue(int(settings.quakes_near_km))
        gl.addWidget(self.near, 0, 0)
        gl.addWidget(self.near_mag, 0, 1)
        gl.addWidget(QLabel("or more, within"), 0, 2)
        gl.addWidget(self.near_km, 0, 3)
        self.major = QCheckBox("Of a major quake anywhere: magnitude")
        self.major.setChecked(settings.quakes_notify_major)
        self.major_mag = QDoubleSpinBox()
        self.major_mag.setRange(5.0, 9.5)
        self.major_mag.setDecimals(1)
        self.major_mag.setSingleStep(0.5)
        self.major_mag.setValue(settings.quakes_major_mag)
        gl.addWidget(self.major, 1, 0)
        gl.addWidget(self.major_mag, 1, 1)
        gl.addWidget(QLabel("or more"), 1, 2)
        note = QLabel("Only quakes from the last 2 hours are notified, once each. Clicking the "
                      "notification turns the globe to the quake.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        gl.addWidget(note, 2, 0, 1, 4)
        lay.addWidget(g)

        row = QHBoxLayout()
        row.addWidget(QLabel("Check every"))
        self.interval = QComboBox()
        for m in Q.INTERVALS:
            self.interval.addItem(f"{m} minutes", m)
        self.interval.setCurrentIndex(Q.INTERVALS.index(settings.quakes_interval))
        row.addWidget(self.interval)
        row.addStretch(1)
        lay.addLayout(row)
        src = QLabel("From USGS (worldwide) and GeoNet (New Zealand). Not an earthquake or tsunami warning "
                     "service: follow official advice.")
        src.setWordWrap(True)
        src.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(src)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                        | QDialogButtonBox.StandardButton.Apply)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        lay.addWidget(self.buttons)

    def values(self) -> dict:
        return {"quakes_show": self.show_box.isChecked(), "quakes_period": self.period.currentData(),
                "quakes_min_mag": float(self.min_mag.currentData()), "quakes_interval": self.interval.currentData(),
                "quakes_notify_near": self.near.isChecked(), "quakes_near_mag": round(self.near_mag.value(), 1),
                "quakes_near_km": int(self.near_km.value()), "quakes_notify_major": self.major.isChecked(),
                "quakes_major_mag": round(self.major_mag.value(), 1)}

    def apply(self) -> None:
        self.applied.emit(self.values())

    def _ok(self) -> None:
        self.apply()
        self.accept()
