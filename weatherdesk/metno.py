"""MET Norway (yr.no) forecast client – a second, independent weather source.

Free, no API key or account. Global coverage (ECMWF-based outside the Nordics),
run by the Norwegian Meteorological Institute on its own servers, so it's a
different network route from Open-Meteo. Data: CC BY 4.0, "Data from MET Norway".

Terms of service (https://api.met.no/doc/TermsOfService): identify the app in
the User-Agent, use at most 4 decimals in coordinates, don't hammer the API.
WeatherDesk asks at most every few minutes, so that's well within limits.

The response is converted into the same Forecast model Open-Meteo produces:
  - times converted from UTC to the location's local time ("YYYY-MM-DDTHH:MM");
  - m/s -> km/h; MET symbol codes -> WMO weather codes;
  - "feels like" from the same formula Open-Meteo uses (Australian apparent temperature);
  - daily values aggregated per local day; sunrise/sunset and day/night calculated
    here (MET's forecast doesn't include them, and that saves a second request).
Differences from Open-Meteo: today's high/low only cover the rest of today, and the
UV index is the clear-sky value.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import time
from typing import Any, Optional

from .api import DataError, JsonHttpClient, _num, DEFAULT_TIMEOUT
from .models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from .moon import tz_for

FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
SOURCE_NAME = "MET Norway"
CREDIT = "Weather data by MET Norway (CC BY 4.0)"
SUN_ALT = -0.833          # sunrise/sunset: upper limb on the horizon, with refraction


class MetNoClient(JsonHttpClient):
    source_name = SOURCE_NAME

    def __init__(self, forecast_url: str = FORECAST_URL, timeout: float = DEFAULT_TIMEOUT,
                 ssl_context=None):
        super().__init__(timeout=timeout, ssl_context=ssl_context)
        self.forecast_url = forecast_url
        # MET asks for an identifying User-Agent with a way to reach the developer.
        self.user_agent += " github.com/shanebl030-glitch/WeatherDesk"

    def fetch_forecast(self, location: Location, forecast_days: int = 7,
                       now: Optional[dt.datetime] = None) -> Forecast:
        data = self._get_json(self.forecast_url, {
            "lat": f"{location.latitude:.4f}",
            "lon": f"{location.longitude:.4f}",
        })
        fc = parse_metno(data, location, max(1, min(int(forecast_days), 9)), now=now)
        fc.fetched_at = time.time()
        return fc


# ----------------------------------------------------------- symbol codes
def wmo_code(symbol: Optional[str]) -> Optional[int]:
    """MET symbol code (e.g. "lightrainshowers_day") -> WMO code (e.g. 80)."""
    if not isinstance(symbol, str) or not symbol:
        return None
    base = symbol.split("_")[0]
    fixed = {"clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45}
    if base in fixed:
        return fixed[base]
    level = 0 if base.startswith("light") else 2 if base.startswith("heavy") else 1
    if "thunder" in base:
        return 95
    showers = "showers" in base
    if "snow" in base or "sleet" in base:     # sleet shown as snow (the closest WMO kind)
        return (85, 85, 86)[level] if showers else (71, 73, 75)[level]
    if "rain" in base:
        return (80, 81, 82)[level] if showers else (61, 63, 65)[level]
    return None


# -------------------------------------------------------------- the sun
def _sun_elevation(t: dt.datetime, lat: float, lon: float) -> float:
    from .earth import solar_elevation
    return solar_elevation(t, lat, lon)


def sun_rise_set(day: dt.date, lat: float, lon: float, tz: dt.tzinfo
                 ) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """Sunrise and sunset on the local calendar day (None in polar day/night)."""
    start = dt.datetime.combine(day, dt.time(0, 0), tz).astimezone(dt.timezone.utc)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), tz).astimezone(dt.timezone.utc)

    def g(t):
        return _sun_elevation(t, lat, lon) - SUN_ALT

    rise = sett = None
    step = dt.timedelta(minutes=20)
    t, v = start, g(start)
    while t < end and (rise is None or sett is None):
        n = min(t + step, end)
        nv = g(n)
        if (v < 0 <= nv) or (v >= 0 > nv):
            a, b, fa = t, n, v
            for _ in range(14):               # bisection to well under a minute
                m = a + (b - a) / 2
                fm = g(m)
                if (fa < 0) == (fm < 0):
                    a, fa = m, fm
                else:
                    b = m
            when = (a + (b - a) / 2).astimezone(tz)
            if v < 0 <= nv and rise is None:
                rise = when
            elif v >= 0 > nv and sett is None:
                sett = when
        t, v = n, nv
    return rise, sett


# ------------------------------------------------------------- parsing
def _local(t: dt.datetime, tz: dt.tzinfo) -> str:
    return t.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def _parse_time(s: Any) -> Optional[dt.datetime]:
    if not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def apparent_temperature(temp: Optional[float], rh: Optional[float],
                         wind_ms: Optional[float]) -> Optional[float]:
    """Australian (Steadman) apparent temperature, as used by Open-Meteo."""
    if temp is None or rh is None or wind_ms is None:
        return None
    e = rh / 100.0 * 6.105 * math.exp(17.27 * temp / (237.7 + temp))
    return round(temp + 0.33 * e - 0.70 * wind_ms - 4.0, 1)


def _kmh(ms: Optional[float]) -> Optional[float]:
    return None if ms is None else round(ms * 3.6, 1)


def _tz_for_location(location: Location) -> tuple[dt.tzinfo, str]:
    if location.timezone and location.timezone not in ("auto", ""):
        return tz_for(location.timezone), location.timezone
    # no zone name saved: nearest whole hour from the longitude
    hours = max(-12, min(14, round(location.longitude / 15.0)))
    return dt.timezone(dt.timedelta(hours=hours)), "auto"


def parse_metno(data: Any, location: Location, days: int = 7,
                now: Optional[dt.datetime] = None) -> Forecast:
    if not isinstance(data, dict):
        raise DataError("Unexpected forecast response from MET Norway.")
    props = data.get("properties")
    series = props.get("timeseries") if isinstance(props, dict) else None
    if not isinstance(series, list) or not series:
        raise DataError("MET Norway's forecast response has no data.")

    steps = []          # (utc time, instant details, next_1_hours, next_6_hours)
    for item in series:
        if not isinstance(item, dict):
            continue
        t = _parse_time(item.get("time"))
        d = item.get("data")
        if t is None or not isinstance(d, dict):
            continue
        inst = (d.get("instant") or {}).get("details") or {}
        if not isinstance(inst, dict) or _num(inst.get("air_temperature")) is None:
            continue
        n1 = d.get("next_1_hours") if isinstance(d.get("next_1_hours"), dict) else None
        n6 = d.get("next_6_hours") if isinstance(d.get("next_6_hours"), dict) else None
        steps.append((t, inst, n1, n6))
    if not steps:
        raise DataError("MET Norway's forecast response is missing temperatures.")
    steps.sort(key=lambda s: s[0])

    tz, tz_name = _tz_for_location(location)
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    lat, lon = location.latitude, location.longitude

    # ---- current: the latest step at or before now (else the first one)
    cur_i = 0
    for i, s in enumerate(steps):
        if s[0] <= now:
            cur_i = i
    t0, inst, n1, n6 = steps[cur_i]
    summary = (n1 or n6 or {}).get("summary") or {}
    temp = _num(inst.get("air_temperature"))
    rh = _num(inst.get("relative_humidity"))
    wind = _num(inst.get("wind_speed"))
    local_now = now.astimezone(tz)
    current = CurrentWeather(
        time=local_now.replace(minute=local_now.minute - local_now.minute % 15).strftime("%Y-%m-%dT%H:%M"),
        temperature=temp,
        apparent_temperature=apparent_temperature(temp, rh, wind),
        humidity=rh,
        weather_code=wmo_code(summary.get("symbol_code")) or 0,
        is_day=_sun_elevation(now, lat, lon) > SUN_ALT,
        wind_speed=_kmh(wind),
        wind_direction=_num(inst.get("wind_from_direction")),
        wind_gusts=_kmh(_num(inst.get("wind_speed_of_gust"))),
        pressure=_num(inst.get("air_pressure_at_sea_level")),
        cloud_cover=_num(inst.get("cloud_area_fraction")),
        precipitation=_num(((n1 or {}).get("details") or {}).get("precipitation_amount")),
    )

    # ---- hourly: the steps that are one hour apart (about the first 2.5 days)
    hourly: list[HourlyPoint] = []
    for t, inst, n1, _n6 in steps[cur_i:]:
        if n1 is None:
            break
        det = n1.get("details") or {}
        hourly.append(HourlyPoint(
            time=_local(t, tz), temperature=_num(inst.get("air_temperature")),
            precipitation_probability=_num(det.get("probability_of_precipitation")),
            precipitation=_num(det.get("precipitation_amount")),
            weather_code=wmo_code((n1.get("summary") or {}).get("symbol_code"))))

    # ---- daily: aggregate every step from now on by its local date
    first_day = local_now.date()
    want = [first_day + dt.timedelta(days=i) for i in range(days)]
    agg: dict[dt.date, dict] = {d: {"temps": [], "codes": [], "pp": [], "wind": [], "uv": [],
                                    "rain": 0.0, "has_rain": False} for d in want}
    later = steps[cur_i:]
    for i, (t, inst, n1, n6) in enumerate(later):
        day = t.astimezone(tz).date()
        a = agg.get(day)
        if a is None:
            continue
        gap_h = ((later[i + 1][0] - t).total_seconds() / 3600) if i + 1 < len(later) else 6.0
        block = n1 if (gap_h <= 1.01 and n1) else (n6 or n1)
        a["temps"].append(_num(inst.get("air_temperature")))
        a["wind"].append(_num(inst.get("wind_speed")))
        a["uv"].append(_num(inst.get("ultraviolet_index_clear_sky")))
        if n6 and gap_h > 1.01:
            det6 = n6.get("details") or {}
            a["temps"] += [_num(det6.get("air_temperature_max")), _num(det6.get("air_temperature_min"))]
        if block:
            det = block.get("details") or {}
            a["codes"].append(wmo_code((block.get("summary") or {}).get("symbol_code")))
            a["pp"].append(_num(det.get("probability_of_precipitation")))
            amt = _num(det.get("precipitation_amount"))
            if amt is not None:
                a["rain"] += amt
                a["has_rain"] = True

    daily: list[DailyPoint] = []
    for day in want:
        a = agg[day]
        temps = [x for x in a["temps"] if x is not None]
        if not temps:
            break                                    # past the end of MET's forecast
        rise, sett = sun_rise_set(day, lat, lon, tz)
        codes = [c for c in a["codes"] if c is not None]
        pps = [x for x in a["pp"] if x is not None]
        winds = [x for x in a["wind"] if x is not None]
        uvs = [x for x in a["uv"] if x is not None]
        daily.append(DailyPoint(
            date=day.isoformat(),
            weather_code=max(codes) if codes else None,     # the day's most significant weather
            temp_max=max(temps), temp_min=min(temps),
            precipitation_sum=round(a["rain"], 1) if a["has_rain"] else None,
            precipitation_probability_max=max(pps) if pps else None,
            wind_speed_max=_kmh(max(winds)) if winds else None,
            sunrise=rise.strftime("%Y-%m-%dT%H:%M") if rise else None,
            sunset=sett.strftime("%Y-%m-%dT%H:%M") if sett else None,
            uv_index_max=max(uvs) if uvs else None,
        ))

    off = now.astimezone(tz).utcoffset()
    return Forecast(location=location, timezone=tz_name, current=current, hourly=hourly,
                    daily=daily, utc_offset_seconds=int(off.total_seconds()) if off is not None else None,
                    source=SOURCE_NAME)
