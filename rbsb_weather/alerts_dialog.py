"""Settings → Weather Alerts (2.4).

Created By Shane BlackbuRn
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout,
                             QGroupBox, QHBoxLayout, QLabel, QVBoxLayout)

from . import alerts as A
from . import units

LEVEL_LABELS = {"all": "All, including advisories", "watch": "Watches and above",
                "orange": "Orange warnings and above", "red": "Red warnings only"}
LIMIT_ROWS = (("gust", "Wind gusts over"), ("rain", "Rain over"), ("heat", "Temperature above"),
              ("frost", "Temperature below"), ("snow", "Any snow"), ("thunder", "Thunderstorms"))


def to_user(key: str, v: float, s) -> float:
    if key == "gust":
        return units.convert_wind(v, s.wind_unit)
    if key == "rain":
        return units.convert_precip(v, s.precip_unit)
    if key in ("heat", "frost"):
        return units.convert_temp(v, s.temp_unit)
    return v


def from_user(key: str, v: float, s) -> float:
    """The user's units back to km/h, mm, °C."""
    if key == "gust":
        f = units.convert_wind(1.0, s.wind_unit) or 1.0
        return v / f
    if key == "rain":
        f = units.convert_precip(1.0, s.precip_unit) or 1.0
        return v / f
    if key in ("heat", "frost") and s.temp_unit == "F":
        return (v - 32) * 5 / 9
    return v


def unit_text(key: str, s) -> str:
    return {"gust": s.wind_unit, "rain": f"{s.precip_unit} in a day",
            "heat": f"°{s.temp_unit}", "frost": f"°{s.temp_unit} (frost)"}.get(key, "")


class AlertsDialog(QDialog):
    applied = pyqtSignal(dict)

    def __init__(self, settings, coverage_rows: list[tuple[str, str, str]], parent=None):
        """coverage_rows: (place, source, status) for each saved place."""
        super().__init__(parent)
        self.setWindowTitle("Weather Alerts")
        self.s = settings
        lay = QVBoxLayout(self)

        g = QGroupBox("Official warnings")
        gl = QVBoxLayout(g)
        self.official = QCheckBox("Show official weather warnings for my saved places")
        self.official.setChecked(settings.alerts_official)
        gl.addWidget(self.official)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        for c, h in enumerate(("Place", "Warnings from", "Status")):
            lbl = QLabel(f"<b>{h}</b>")
            grid.addWidget(lbl, 0, c)
        self.coverage_labels = []
        for r, (place, src, status) in enumerate(coverage_rows[:20], start=1):
            row = [QLabel(place), QLabel(src), QLabel(status)]
            for c, w in enumerate(row):
                grid.addWidget(w, r, c)
            self.coverage_labels.append(row)
        if len(coverage_rows) > 20:
            grid.addWidget(QLabel(f"… and {len(coverage_rows) - 20} more"), 21, 0)
        gl.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show from"))
        self.level = QComboBox()
        for k in A.MIN_LEVEL_CHOICES:
            self.level.addItem(LEVEL_LABELS[k], k)
        self.level.setCurrentIndex(A.MIN_LEVEL_CHOICES.index(settings.alerts_min_level))
        row.addWidget(self.level)
        row.addSpacing(16)
        row.addWidget(QLabel("Check every"))
        self.interval = QComboBox()
        for m in A.INTERVAL_CHOICES:
            self.interval.addItem(f"{m} minutes", m)
        self.interval.setCurrentIndex(A.INTERVAL_CHOICES.index(settings.alerts_interval))
        row.addWidget(self.interval)
        row.addStretch(1)
        gl.addLayout(row)
        lay.addWidget(g)

        g = QGroupBox("My own limits (from the forecast, not official)")
        gl = QVBoxLayout(g)
        self.own = QCheckBox("Alert me when the forecast goes past these limits")
        self.own.setChecked(settings.alerts_own)
        gl.addWidget(self.own)
        grid = QGridLayout()
        limits = A.limits_from_dict(settings.alerts_limits)
        self.limit_boxes: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        for r, (key, label) in enumerate(LIMIT_ROWS):
            cb = QCheckBox(label)
            cb.setChecked(limits[key].on)
            grid.addWidget(cb, r, 0)
            spin = QDoubleSpinBox()
            if key in ("snow", "thunder"):
                spin.setVisible(False)
            else:
                lo, hi = A.LIMIT_RANGES[key]
                a, b = sorted((to_user(key, lo, settings), to_user(key, hi, settings)))
                spin.setRange(a, b)
                spin.setDecimals(2 if key == "rain" and settings.precip_unit == "in" else 0)
                spin.setValue(to_user(key, limits[key].value, settings))
                grid.addWidget(spin, r, 1)
                grid.addWidget(QLabel(unit_text(key, settings)), r, 2)
            self.limit_boxes[key] = (cb, spin)
        grid.setColumnStretch(3, 1)
        gl.addLayout(grid)
        note = QLabel("These show with a grey \"MY LIMIT\" badge, so they're never mistaken for an official warning.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        gl.addWidget(note)
        lay.addWidget(g)

        g = QGroupBox("How to tell me")
        gl = QVBoxLayout(g)
        self.banner = QCheckBox("Banner in the sky and badge in Saved locations")
        self.banner.setChecked(settings.alerts_banner)
        self.notify = QCheckBox("Desktop notification when a warning is issued or changes")
        self.notify.setChecked(settings.alerts_notify)
        self.tray_dot = QCheckBox("Warning dot on the tray temperature")
        self.tray_dot.setChecked(settings.alerts_tray_dot)
        self.beep = QCheckBox("Beep for Red warnings")
        self.beep.setChecked(settings.alerts_beep_red)
        self.selected_only = QCheckBox("Only for the selected place (not all saved places)")
        self.selected_only.setChecked(settings.alerts_selected_only)
        for w in (self.banner, self.notify, self.tray_dot, self.beep, self.selected_only):
            gl.addWidget(w)
        lay.addWidget(g)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                                        | QDialogButtonBox.StandardButton.Apply)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        lay.addWidget(self.buttons)

    def values(self) -> dict:
        limits = {}
        for key, (cb, spin) in self.limit_boxes.items():
            v = A.DEFAULT_LIMITS[key].value if key in ("snow", "thunder") else from_user(key, spin.value(), self.s)
            limits[key] = {"on": cb.isChecked(), "value": round(v, 2)}
        return {"alerts_official": self.official.isChecked(), "alerts_min_level": self.level.currentData(),
                "alerts_interval": self.interval.currentData(), "alerts_own": self.own.isChecked(),
                "alerts_limits": A.limits_to_dict(A.limits_from_dict(limits)),
                "alerts_banner": self.banner.isChecked(), "alerts_notify": self.notify.isChecked(),
                "alerts_tray_dot": self.tray_dot.isChecked(), "alerts_beep_red": self.beep.isChecked(),
                "alerts_selected_only": self.selected_only.isChecked()}

    def apply(self) -> None:
        self.applied.emit(self.values())

    def _ok(self) -> None:
        self.apply()
        self.accept()
