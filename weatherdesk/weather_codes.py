"""WMO weather interpretation codes (as used by Open-Meteo)."""

from __future__ import annotations

# code: (description, day symbol, night symbol)
_CODES: dict[int, tuple[str, str, str]] = {
    0: ("Clear sky", "☀️", "🌙"),
    1: ("Mainly clear", "🌤️", "🌙"),
    2: ("Partly cloudy", "⛅", "☁️"),
    3: ("Overcast", "☁️", "☁️"),
    45: ("Fog", "🌫️", "🌫️"),
    48: ("Depositing rime fog", "🌫️", "🌫️"),
    51: ("Light drizzle", "🌦️", "🌧️"),
    53: ("Drizzle", "🌦️", "🌧️"),
    55: ("Dense drizzle", "🌧️", "🌧️"),
    56: ("Light freezing drizzle", "🌧️", "🌧️"),
    57: ("Freezing drizzle", "🌧️", "🌧️"),
    61: ("Light rain", "🌦️", "🌧️"),
    63: ("Rain", "🌧️", "🌧️"),
    65: ("Heavy rain", "🌧️", "🌧️"),
    66: ("Light freezing rain", "🌧️", "🌧️"),
    67: ("Freezing rain", "🌧️", "🌧️"),
    71: ("Light snow", "🌨️", "🌨️"),
    73: ("Snow", "🌨️", "🌨️"),
    75: ("Heavy snow", "❄️", "❄️"),
    77: ("Snow grains", "🌨️", "🌨️"),
    80: ("Light showers", "🌦️", "🌧️"),
    81: ("Showers", "🌧️", "🌧️"),
    82: ("Violent showers", "⛈️", "⛈️"),
    85: ("Light snow showers", "🌨️", "🌨️"),
    86: ("Snow showers", "❄️", "❄️"),
    95: ("Thunderstorm", "⛈️", "⛈️"),
    96: ("Thunderstorm with hail", "⛈️", "⛈️"),
    99: ("Severe thunderstorm with hail", "⛈️", "⛈️"),
}

UNKNOWN = ("Unknown", "❔", "❔")


def describe(code: int | None) -> str:
    if code is None:
        return UNKNOWN[0]
    return _CODES.get(int(code), UNKNOWN)[0]


def symbol(code: int | None, is_day: bool = True) -> str:
    if code is None:
        return UNKNOWN[1]
    entry = _CODES.get(int(code), UNKNOWN)
    return entry[1] if is_day else entry[2]


def all_codes() -> list[int]:
    return sorted(_CODES)
