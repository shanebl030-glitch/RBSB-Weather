"""Unit conversion and formatting. Inputs are always metric (°C, km/h, mm, hPa)."""

from __future__ import annotations

from typing import Optional

TEMP_UNITS = ("C", "F")
WIND_UNITS = ("km/h", "m/s", "mph", "kn")
PRECIP_UNITS = ("mm", "in")
TIME_FORMATS = ("24", "12")             # 24-hour (19:30) or 12-hour (7:30 pm)

# The clock format is app-wide (every tab, the card, the widget, the tray), so it lives
# here rather than being passed to every formatter. Set from settings at start-up and
# whenever the user changes it.
_time_format = "24"


def set_time_format(fmt: str) -> None:
    global _time_format
    if fmt in TIME_FORMATS:
        _time_format = fmt


def time_format() -> str:
    return _time_format


def _clock(hour: int, minute: int, fmt: Optional[str] = None) -> str:
    if (fmt or _time_format) == "12":
        return f"{hour % 12 or 12}:{minute:02d} {'am' if hour < 12 else 'pm'}"
    return f"{hour:02d}:{minute:02d}"


def fmt_clock(t, day: bool = False, fmt: Optional[str] = None) -> str:
    """19:30 / 7:30 pm (with day=True: Mon 19:30 / Mon 7:30 pm). t: datetime or time."""
    if t is None:
        return "–"
    text = _clock(t.hour, t.minute, fmt)
    return f"{t.strftime('%a')} {text}" if day else text


def fmt_iso_clock(iso: Optional[str], fmt: Optional[str] = None) -> str:
    """The time part of an ISO local time string ("2026-11-16T19:30") as a clock."""
    if not iso or len(iso) < 16:
        return "–"
    try:
        return _clock(int(iso[11:13]), int(iso[14:16]), fmt)
    except ValueError:
        return "–"


def fmt_hour_label(iso: str, fmt: Optional[str] = None) -> str:
    """Short hour labels for the 24-hour chart: 19:00 / 7 pm."""
    if len(iso) < 16:
        return iso
    try:
        h, m = int(iso[11:13]), int(iso[14:16])
    except ValueError:
        return iso
    if (fmt or _time_format) == "12":
        return f"{h % 12 or 12}{'' if m == 0 else f':{m:02d}'} {'am' if h < 12 else 'pm'}"
    return f"{h:02d}:{m:02d}"

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def convert_temp(c: Optional[float], unit: str) -> Optional[float]:
    if c is None:
        return None
    if unit == "F":
        return c * 9.0 / 5.0 + 32.0
    if unit == "C":
        return c
    raise ValueError(f"unknown temperature unit: {unit}")


def convert_wind(kmh: Optional[float], unit: str) -> Optional[float]:
    if kmh is None:
        return None
    factors = {"km/h": 1.0, "m/s": 1 / 3.6, "mph": 0.621371, "kn": 0.539957}
    if unit not in factors:
        raise ValueError(f"unknown wind unit: {unit}")
    return kmh * factors[unit]


def convert_precip(mm: Optional[float], unit: str) -> Optional[float]:
    if mm is None:
        return None
    if unit == "in":
        return mm / 25.4
    if unit == "mm":
        return mm
    raise ValueError(f"unknown precipitation unit: {unit}")


def fmt_temp(c: Optional[float], unit: str, decimals: int = 0) -> str:
    v = convert_temp(c, unit)
    if v is None:
        return "–"
    s = f"{v:.{decimals}f}"
    if s in ("-0", "-0.0"):
        s = s[1:]
    return f"{s}°{unit}"


def fmt_wind(kmh: Optional[float], unit: str) -> str:
    v = convert_wind(kmh, unit)
    return "–" if v is None else f"{v:.0f} {unit}"


def fmt_precip(mm: Optional[float], unit: str) -> str:
    v = convert_precip(mm, unit)
    if v is None:
        return "–"
    return f"{v:.2f} in" if unit == "in" else f"{v:.1f} mm"


def compass(degrees: Optional[float]) -> str:
    if degrees is None:
        return ""
    idx = int((float(degrees) % 360) / 22.5 + 0.5) % 16
    return _COMPASS[idx]
