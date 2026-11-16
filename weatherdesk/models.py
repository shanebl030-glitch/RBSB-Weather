"""Plain data classes used throughout WeatherDesk.

All values are stored in metric base units (°C, km/h, mm, hPa) exactly as
returned by Open-Meteo. Conversion to the user's chosen units happens only at
display time (see units.py), so switching units never needs a re-download.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin1: str = ""          # state / region
    timezone: str = "auto"

    @property
    def key(self) -> str:
        """Stable identifier used for de-duplication and cache file names."""
        return f"{self.latitude:.4f},{self.longitude:.4f}"

    @property
    def display_name(self) -> str:
        parts = [self.name]
        if self.admin1 and self.admin1 != self.name:
            parts.append(self.admin1)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        return cls(
            name=str(d["name"]),
            latitude=float(d["latitude"]),
            longitude=float(d["longitude"]),
            country=str(d.get("country", "") or ""),
            admin1=str(d.get("admin1", "") or ""),
            timezone=str(d.get("timezone", "auto") or "auto"),
        )


@dataclass
class CurrentWeather:
    time: str
    temperature: float
    apparent_temperature: Optional[float]
    humidity: Optional[float]
    weather_code: int
    is_day: bool
    wind_speed: Optional[float]
    wind_direction: Optional[float]
    wind_gusts: Optional[float]
    pressure: Optional[float]
    cloud_cover: Optional[float]
    precipitation: Optional[float]


@dataclass
class HourlyPoint:
    time: str
    temperature: Optional[float]
    precipitation_probability: Optional[float]
    precipitation: Optional[float]
    weather_code: Optional[int]


@dataclass
class DailyPoint:
    date: str
    weather_code: Optional[int]
    temp_max: Optional[float]
    temp_min: Optional[float]
    precipitation_sum: Optional[float]
    precipitation_probability_max: Optional[float]
    wind_speed_max: Optional[float]
    sunrise: Optional[str]
    sunset: Optional[str]
    uv_index_max: Optional[float]


@dataclass
class Forecast:
    location: Location
    timezone: str
    current: CurrentWeather
    hourly: list[HourlyPoint] = field(default_factory=list)
    daily: list[DailyPoint] = field(default_factory=list)
    fetched_at: float = 0.0      # unix time when downloaded
    utc_offset_seconds: Optional[int] = None
    from_cache: bool = False
