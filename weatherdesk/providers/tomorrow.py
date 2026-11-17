"""Tomorrow.io (v4 Weather Forecast API). Needs a free API key.

One request returns 120 hours hourly and 5 days daily, including sunrise/sunset
and UV. The free plan allows 25 requests an hour and 500 a day; WeatherDesk
asks at most every 10 minutes per location so it stays well inside that. The
remaining allowance comes back in the response headers and is shown in
Settings → Weather Providers.

Docs: https://docs.tomorrow.io/reference/weather-forecast

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Optional

from ..models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from . import register
from .base import (FEATURES, Provider, ProviderInfo, from_iso, kmh_from_ms, local_str, location_tz, num,
                   pct, quarter_hour, now_utc)

_CODES = {1000: 0, 1100: 1, 1101: 2, 1102: 3, 1001: 3, 2000: 45, 2100: 45,
          4000: 53, 4200: 61, 4001: 63, 4201: 65, 5001: 71, 5100: 71, 5000: 73, 5101: 75,
          6000: 56, 6200: 66, 6001: 67, 6201: 67, 7102: 77, 7000: 77, 7101: 77, 8000: 95}


def tio_code(v: Any) -> Optional[int]:
    c = num(v)
    if c is None:
        return None
    c = int(c)
    if c > 9999:                  # day/night variants: the base code plus a final 0 or 1
        c //= 10
    return _CODES.get(c)


def _first(values: dict, *names: str) -> Optional[float]:
    for n in names:
        v = num(values.get(n))
        if v is not None:
            return v
    return None


@register
class TomorrowProvider(Provider):
    info = ProviderInfo(
        id="tomorrow", name="Tomorrow.io", needs_key=True,
        website="https://www.tomorrow.io/",
        credit="Weather data by Tomorrow.io",
        coverage="Worldwide, from Tomorrow.io's own model plus its satellite and radar data.",
        forecast_days="5 days on the free plan",
        hourly="120 hours",
        limits="Free plan: 500 requests a day, 25 an hour, 3 a second (personal, non-commercial). "
               "WeatherDesk asks at most every 10 minutes per location.",
        features=frozenset(FEATURES),
        signup_url="https://app.tomorrow.io/signup",
        docs_url="https://docs.tomorrow.io/reference/weather-forecast",
        key_help="After signing in: Development → API Management.",
        min_interval_s=10 * 60,
        max_days=5,
    )

    @classmethod
    def default_base_url(cls) -> str:
        return "https://api.tomorrow.io/v4"

    def _error_reason(self, body: str) -> str:
        try:
            d = json.loads(body)
        except ValueError:
            return ""
        return str(d.get("message") or d.get("type") or "") if isinstance(d, dict) else ""

    def usage(self) -> dict:
        h = self.last_headers()
        out = {}
        day = (h.get("x-ratelimit-remaining-day"), h.get("x-ratelimit-limit-day"))
        hour = (h.get("x-ratelimit-remaining-hour"), h.get("x-ratelimit-limit-hour"))
        if day[0] is not None:
            out["today"] = f"{day[0]} of {day[1] or '?'} requests left today"
        if hour[0] is not None:
            out["hour"] = f"{hour[0]} of {hour[1] or '?'} left this hour"
        return out

    def _fetch(self, location: Location, days: int) -> Forecast:
        data = self._get_json(f"{self.base_url}/weather/forecast", {
            "location": f"{location.latitude:.4f},{location.longitude:.4f}",
            "timesteps": ["1h", "1d"], "units": "metric", "apikey": self.api_key})
        return parse_tomorrow(data, location)


def parse_tomorrow(data: Any, location: Location, now: Optional[dt.datetime] = None) -> Forecast:
    tl = data.get("timelines") if isinstance(data, dict) else None
    if not isinstance(tl, dict) or not tl.get("hourly"):
        raise ValueError("no hourly timeline")
    tz, tz_name = location_tz(location)
    now = now or now_utc()
    steps = []
    for item in tl.get("hourly") or []:
        t = from_iso(item.get("time")) if isinstance(item, dict) else None
        if t is not None and isinstance(item.get("values"), dict):
            steps.append((t, item["values"]))
    steps.sort(key=lambda s: s[0])
    if not steps:
        raise ValueError("no usable hourly steps")
    cur_i = 0
    for i, (t, _v) in enumerate(steps):
        if t <= now:
            cur_i = i
    _t, v = steps[cur_i]
    precip = [x for x in (num(v.get("rainIntensity")), num(v.get("snowIntensity")),
                          num(v.get("sleetIntensity")), num(v.get("freezingRainIntensity"))) if x is not None]
    current = CurrentWeather(
        time=quarter_hour(now, tz), temperature=num(v.get("temperature")),
        apparent_temperature=num(v.get("temperatureApparent")), humidity=pct(v.get("humidity")),
        weather_code=tio_code(v.get("weatherCode")), is_day=None,
        wind_speed=kmh_from_ms(v.get("windSpeed")), wind_direction=num(v.get("windDirection")),
        wind_gusts=kmh_from_ms(v.get("windGust")),
        pressure=_first(v, "pressureSeaLevel", "pressureSurfaceLevel"),
        cloud_cover=pct(v.get("cloudCover")), precipitation=round(sum(precip), 2) if precip else None)
    hourly = []
    for t, hv in steps[cur_i:]:
        amt = [x for x in (num(hv.get("rainIntensity")), num(hv.get("snowIntensity"))) if x is not None]
        hourly.append(HourlyPoint(local_str(t, tz), num(hv.get("temperature")),
                                  pct(hv.get("precipitationProbability")),
                                  round(sum(amt), 2) if amt else None, tio_code(hv.get("weatherCode"))))
    daily = []
    for item in tl.get("daily") or []:
        t = from_iso(item.get("time")) if isinstance(item, dict) else None
        dv = item.get("values") if isinstance(item, dict) else None
        if t is None or not isinstance(dv, dict):
            continue
        rise, sett = from_iso(dv.get("sunriseTime")), from_iso(dv.get("sunsetTime"))
        rain = [x for x in (num(dv.get("rainAccumulationSum")), num(dv.get("snowAccumulationSum")),
                            num(dv.get("sleetAccumulationLweSum")), num(dv.get("iceAccumulationSum")))
                if x is not None]
        daily.append(DailyPoint(
            date=t.astimezone(tz).date().isoformat(),
            weather_code=tio_code(dv.get("weatherCodeMax") if dv.get("weatherCodeMax") is not None
                                  else dv.get("weatherCode")),
            temp_max=_first(dv, "temperatureMax"), temp_min=_first(dv, "temperatureMin"),
            precipitation_sum=round(sum(rain), 1) if rain else None,
            precipitation_probability_max=pct(_first(dv, "precipitationProbabilityMax",
                                                     "precipitationProbabilityAvg")),
            wind_speed_max=kmh_from_ms(_first(dv, "windSpeedMax", "windSpeedAvg")),
            sunrise=local_str(rise, tz) if rise else None, sunset=local_str(sett, tz) if sett else None,
            uv_index_max=_first(dv, "uvIndexMax", "uvIndexAvg")))
    return Forecast(location=location, timezone=tz_name, current=current, hourly=hourly, daily=daily)
