"""WeatherAPI.com. Needs a free API key.

One request (forecast.json) returns current conditions, hourly data, daily values
and sunrise/sunset. The free plan returns 3 days; paid plans up to 14.

Docs: https://www.weatherapi.com/docs/

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Optional

from ..models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from . import register
from .base import (FEATURES, Provider, ProviderInfo, from_unix, local_str, location_tz, now_utc, num, pct,
                   quarter_hour)

# WeatherAPI condition code -> WMO code. Codes not listed (e.g. the dust, smoke and
# haze codes added in 2026) become None, and the condition is worked out from cloud.
_CODES = {
    1000: 0, 1003: 2, 1006: 3, 1009: 3, 1030: 45, 1063: 80, 1066: 85, 1069: 85, 1072: 56,
    1087: 95, 1114: 73, 1117: 75, 1135: 45, 1147: 48, 1150: 51, 1153: 51, 1168: 56, 1171: 57,
    1180: 61, 1183: 61, 1186: 63, 1189: 63, 1192: 65, 1195: 65, 1198: 66, 1201: 67,
    1204: 71, 1207: 73, 1210: 71, 1213: 71, 1216: 73, 1219: 73, 1222: 75, 1225: 75, 1237: 77,
    1240: 80, 1243: 81, 1246: 82, 1249: 85, 1252: 86, 1255: 85, 1258: 86, 1261: 77, 1264: 77,
    1273: 95, 1276: 95, 1279: 95, 1282: 95,
}


def wapi_code(cond: Any) -> Optional[int]:
    code = num(cond.get("code")) if isinstance(cond, dict) else num(cond)
    return None if code is None else _CODES.get(int(code))


def _clock(date: str, s: Any, tz: dt.tzinfo) -> Optional[str]:
    """'06:01 AM' on `date` -> '2026-11-17T06:01'. None for 'No sunrise' etc."""
    if not isinstance(s, str):
        return None
    try:
        t = dt.datetime.strptime(f"{date} {s.strip()}", "%Y-%m-%d %I:%M %p")
    except ValueError:
        return None
    return t.strftime("%Y-%m-%dT%H:%M")


@register
class WeatherApiProvider(Provider):
    info = ProviderInfo(
        id="weatherapi", name="WeatherAPI.com", needs_key=True,
        website="https://www.weatherapi.com/",
        credit="Weather data by WeatherAPI.com",
        coverage="Worldwide, blending ECMWF, GFS and HRRR models with observations.",
        forecast_days="3 days on the free plan; up to 14 on paid plans",
        hourly="every hour for each forecast day",
        limits="Free plan: 100,000 calls a month, commercial use allowed, no card needed. "
               "Paid plans from about US$19 a month add 14-day forecasts.",
        features=frozenset(FEATURES),
        signup_url="https://www.weatherapi.com/signup.aspx",
        docs_url="https://www.weatherapi.com/docs/",
        key_help="After signing in, the key is on your account dashboard.",
        max_days=14,
    )

    @classmethod
    def default_base_url(cls) -> str:
        return "https://api.weatherapi.com/v1"

    def _error_reason(self, body: str) -> str:
        try:
            d = json.loads(body)
        except ValueError:
            return ""
        err = d.get("error") if isinstance(d, dict) else None
        return str(err.get("message", "")) if isinstance(err, dict) else ""

    def _fetch(self, location: Location, days: int) -> Forecast:
        data = self._get_json(f"{self.base_url}/forecast.json", {
            "key": self.api_key, "q": f"{location.latitude:.4f},{location.longitude:.4f}",
            "days": days, "aqi": "no", "alerts": "no"})
        return parse_weatherapi(data, location)


def parse_weatherapi(data: Any, location: Location) -> Forecast:
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        raise ValueError("no 'current' block")
    loc = data.get("location") or {}
    tz, tz_name = location_tz(location, loc.get("tz_id"))
    c = data["current"]
    t = from_unix(loc.get("localtime_epoch")) or now_utc()      # "now" at the location, like Open-Meteo
    isd = num(c.get("is_day"))
    current = CurrentWeather(
        time=quarter_hour(t, tz),
        temperature=num(c.get("temp_c")), apparent_temperature=num(c.get("feelslike_c")),
        humidity=pct(c.get("humidity")), weather_code=wapi_code(c.get("condition")),
        is_day=None if isd is None else isd != 0,
        wind_speed=num(c.get("wind_kph")), wind_direction=num(c.get("wind_degree")),
        wind_gusts=num(c.get("gust_kph")), pressure=num(c.get("pressure_mb")),
        cloud_cover=pct(c.get("cloud")), precipitation=num(c.get("precip_mm")))
    hourly, daily = [], []
    for fd in ((data.get("forecast") or {}).get("forecastday") or []):
        if not isinstance(fd, dict) or not isinstance(fd.get("date"), str):
            continue
        day, astro = fd.get("day") or {}, fd.get("astro") or {}
        for h in fd.get("hour") or []:
            ht = from_unix(h.get("time_epoch")) if isinstance(h, dict) else None
            if ht is None:
                continue
            probs = [x for x in (pct(h.get("chance_of_rain")), pct(h.get("chance_of_snow"))) if x is not None]
            hourly.append(HourlyPoint(local_str(ht, tz), num(h.get("temp_c")), max(probs) if probs else None,
                                      num(h.get("precip_mm")), wapi_code(h.get("condition"))))
        probs = [x for x in (pct(day.get("daily_chance_of_rain")), pct(day.get("daily_chance_of_snow")))
                 if x is not None]
        daily.append(DailyPoint(
            date=fd["date"], weather_code=wapi_code(day.get("condition")),
            temp_max=num(day.get("maxtemp_c")), temp_min=num(day.get("mintemp_c")),
            precipitation_sum=num(day.get("totalprecip_mm")),
            precipitation_probability_max=max(probs) if probs else None,
            wind_speed_max=num(day.get("maxwind_kph")),
            sunrise=_clock(fd["date"], astro.get("sunrise"), tz),
            sunset=_clock(fd["date"], astro.get("sunset"), tz),
            uv_index_max=num(day.get("uv"))))
    return Forecast(location=location, timezone=tz_name, current=current, hourly=hourly, daily=daily)
