"""Visual Crossing Weather (Timeline API). Needs a free API key.

One request returns current conditions, hourly data and 15 days. A forecast
counts as a single "record" however many days and hours it contains, so the free
1,000 records a day go a long way.

Docs: https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/

Created By Shane BlackbuRn
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from . import register
from .base import (FEATURES, Provider, ProviderInfo, from_unix, local_str, location_tz, now_utc, num, pct,
                   quarter_hour)


def vc_code(icon: Any, precip: Any = None, snow: Any = None) -> Optional[int]:
    """Visual Crossing icon (icons2 set) -> WMO code; rain/snow amounts set the intensity.
    `precip` is mm for the period (an hour, or a whole day)."""
    if not isinstance(icon, str):
        return None
    p = num(precip) or 0.0
    s = num(snow) or 0.0
    lvl = 0 if p < 2.5 else 1 if p < 10 else 2
    if icon.startswith("thunder"):
        return 95
    if icon.startswith("snow-showers"):
        return 86 if s >= 5 else 85
    if icon == "snow":
        return 75 if s >= 5 else 73 if s >= 1 else 71
    if icon.startswith("showers"):
        return (80, 81, 82)[lvl]
    if icon == "rain":
        return (61, 63, 65)[lvl]
    if icon == "fog":
        return 45
    if icon.startswith("clear"):
        return 0
    if icon.startswith("partly-cloudy"):
        return 2
    if icon == "cloudy":
        return 3
    return None          # "wind" and anything new: worked out from cloud and rain


def _hm(date: str, s: Any) -> Optional[str]:
    if not isinstance(s, str) or len(s) < 5:
        return None
    return f"{date}T{s[:5]}"


@register
class VisualCrossingProvider(Provider):
    info = ProviderInfo(
        id="visualcrossing", name="Visual Crossing", needs_key=True,
        website="https://www.visualcrossing.com/",
        credit="Weather data by Visual Crossing Weather",
        coverage="Worldwide, combining several national weather models with station observations.",
        forecast_days="15 days (RBSB-Weather uses 7)",
        hourly="every hour, all 15 days",
        limits="Free plan: 1,000 records a day (one forecast = 1 record), commercial use allowed. "
               "Pay-as-you-go and subscriptions above that.",
        features=frozenset(FEATURES),
        signup_url="https://www.visualcrossing.com/sign-up",
        docs_url="https://www.visualcrossing.com/resources/documentation/weather-api/timeline-weather-api/",
        key_help="After signing in: Account → Your details → Key.",
        min_interval_s=5 * 60,
        max_days=15,
    )

    @classmethod
    def default_base_url(cls) -> str:
        return "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"

    def _error_reason(self, body: str) -> str:
        # plain text, e.g. "No account found with API key '…'" (the key is removed later)
        return body.strip().splitlines()[0][:150] if body.strip() else ""

    def usage(self) -> dict:
        cost = getattr(self._local, "cost", None)
        return {"cost": f"this update cost {int(cost)} record(s) of the daily allowance"} \
            if cost is not None else {}

    def _fetch(self, location: Location, days: int) -> Forecast:
        data = self._get_json(f"{self.base_url}/{location.latitude:.4f},{location.longitude:.4f}", {
            "unitGroup": "metric", "include": "current,hours,days", "iconSet": "icons2",
            "contentType": "json", "key": self.api_key})
        self._local.cost = num(data.get("queryCost")) if isinstance(data, dict) else None
        return parse_visualcrossing(data, location)


def parse_visualcrossing(data: Any, location: Location) -> Forecast:
    if not isinstance(data, dict) or not isinstance(data.get("currentConditions"), dict):
        raise ValueError("no 'currentConditions' block")
    off_h = num(data.get("tzoffset"))
    tz, tz_name = location_tz(location, data.get("timezone"), None if off_h is None else off_h * 3600)
    c = data["currentConditions"]
    t = now_utc()          # the observation can be up to an hour old; the clock should be "now"
    rise, sett = from_unix(c.get("sunriseEpoch")), from_unix(c.get("sunsetEpoch"))
    current = CurrentWeather(
        time=quarter_hour(t, tz),
        temperature=num(c.get("temp")), apparent_temperature=num(c.get("feelslike")),
        humidity=pct(c.get("humidity")), weather_code=vc_code(c.get("icon"), c.get("precip"), c.get("snow")),
        is_day=(rise <= t < sett) if rise and sett else None,
        wind_speed=num(c.get("windspeed")), wind_direction=num(c.get("winddir")),
        wind_gusts=num(c.get("windgust")), pressure=num(c.get("pressure")),
        cloud_cover=pct(c.get("cloudcover")), precipitation=num(c.get("precip")))
    hourly, daily = [], []
    for d in data.get("days") or []:
        if not isinstance(d, dict) or not isinstance(d.get("datetime"), str):
            continue
        date = d["datetime"]
        for h in d.get("hours") or []:
            ht = from_unix(h.get("datetimeEpoch")) if isinstance(h, dict) else None
            if ht is None:
                continue
            hourly.append(HourlyPoint(local_str(ht, tz), num(h.get("temp")), pct(h.get("precipprob")),
                                      num(h.get("precip")), vc_code(h.get("icon"), h.get("precip"), h.get("snow"))))
        dr, ds = from_unix(d.get("sunriseEpoch")), from_unix(d.get("sunsetEpoch"))
        daily.append(DailyPoint(
            date=date, weather_code=vc_code(d.get("icon"), d.get("precip"), d.get("snow")),
            temp_max=num(d.get("tempmax")), temp_min=num(d.get("tempmin")),
            precipitation_sum=num(d.get("precip")), precipitation_probability_max=pct(d.get("precipprob")),
            wind_speed_max=num(d.get("windspeed")),
            sunrise=local_str(dr, tz) if dr else _hm(date, d.get("sunrise")),
            sunset=local_str(ds, tz) if ds else _hm(date, d.get("sunset")),
            uv_index_max=num(d.get("uvindex"))))
    return Forecast(location=location, timezone=tz_name, current=current, hourly=hourly, daily=daily,
                    utc_offset_seconds=None if off_h is None else int(off_h * 3600))
