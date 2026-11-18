"""Make every provider's Forecast safe and complete enough for the whole app.

Runs after each provider's conversion. It never invents weather: values the
service doesn't supply stay None (shown as "–") unless WeatherDesk can calculate
them exactly from other data. Calculated values are listed in Forecast.calculated.

  - sunrise/sunset: calculated from the location and date (astronomy) when missing;
  - day/night: from the Sun's elevation, when missing;
  - "feels like": from temperature, humidity and wind, when missing;
  - an unknown condition code: worked out from cloud cover and rain, when present;
  - a day's condition / rain chance: from that day's hourly values, when missing;
  - out-of-range percentages clamped, non-numbers dropped, days sorted and limited.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Optional

from ..api import DataError
from ..models import Forecast, Location
from ..moon import tz_for
from ..sun import apparent_temperature, is_daytime, sun_rise_set


def _fin(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# Physically possible ranges (1.15 audit). A value outside them is a broken response,
# not weather: it's dropped (shown as "–") rather than drawn, and can't overflow a
# calculation such as "feels like".
TEMP_C = (-100.0, 70.0)
WIND_KMH = (0.0, 600.0)
PRESSURE_HPA = (800.0, 1100.0)
PRECIP_MM = (0.0, 1000.0)
UV = (0.0, 25.0)


def _rng(v, bounds) -> Optional[float]:
    f = _fin(v)
    return f if f is not None and bounds[0] <= f <= bounds[1] else None


def _code(v) -> Optional[int]:
    """A WMO code the app knows how to show, else None (then worked out where possible)."""
    from ..weather_codes import KNOWN_CODES
    f = _fin(v)
    if f is None or f != int(f):
        return None
    return int(f) if int(f) in KNOWN_CODES else None


def _pct(v) -> Optional[float]:
    f = _fin(v)
    return None if f is None else max(0.0, min(100.0, f))


def code_from(cloud: Optional[float], precip: Optional[float]) -> Optional[int]:
    """A WMO code from cloud cover (%) and precipitation (mm/h), for providers whose
    condition code is unknown. None if neither is known."""
    if precip is not None and precip > 0.05:
        return 61 if precip < 2.5 else 63 if precip < 7.6 else 65
    if cloud is None:
        return None
    return 0 if cloud < 12 else 1 if cloud < 38 else 2 if cloud < 75 else 3


def _tz(fc: Forecast) -> dt.tzinfo:
    return tz_for(fc.timezone, fc.utc_offset_seconds)


def normalise(fc: Forecast, location: Location, days: int = 7) -> Forecast:
    if fc.current is None or _rng(fc.current.temperature, TEMP_C) is None:
        raise DataError(f"{fc.source} didn't supply a current temperature.")
    calc: list[str] = list(fc.calculated or [])

    def note(what: str) -> None:
        if what not in calc:
            calc.append(what)

    tz = _tz(fc)
    lat, lon = location.latitude, location.longitude
    c = fc.current
    for name, bounds in (("temperature", TEMP_C), ("apparent_temperature", TEMP_C),
                         ("wind_speed", WIND_KMH), ("wind_gusts", WIND_KMH), ("pressure", PRESSURE_HPA),
                         ("precipitation", PRECIP_MM)):
        setattr(c, name, _rng(getattr(c, name), bounds))
    c.humidity = _pct(c.humidity)
    c.cloud_cover = _pct(c.cloud_cover)
    wd = _fin(c.wind_direction)
    c.wind_direction = None if wd is None else wd % 360.0
    for name in ("wind_speed", "wind_gusts", "precipitation"):
        v = getattr(c, name)
        if v is not None and v < 0:
            setattr(c, name, None)

    try:
        cur_t = dt.datetime.fromisoformat(c.time).replace(tzinfo=tz)
    except (TypeError, ValueError):
        cur_t = dt.datetime.now(tz)
        c.time = cur_t.strftime("%Y-%m-%dT%H:%M")
    if c.is_day is None:
        c.is_day = is_daytime(cur_t, lat, lon)
        note("day/night")
    if c.apparent_temperature is None and c.humidity is not None and c.wind_speed is not None:
        c.apparent_temperature = _rng(apparent_temperature(c.temperature, c.humidity, c.wind_speed / 3.6),
                                      TEMP_C)
        if c.apparent_temperature is not None:
            note("feels like")
    c.weather_code = _code(c.weather_code)
    if not isinstance(c.is_day, bool) and c.is_day is not None:
        c.is_day = bool(c.is_day)
    if c.weather_code is None:
        c.weather_code = code_from(c.cloud_cover, c.precipitation)
        if c.weather_code is not None:
            note("current condition (from cloud and rain)")

    # ---- hourly
    hourly = []
    seen = set()
    for h in sorted(fc.hourly or [], key=lambda x: x.time):
        if not isinstance(h.time, str) or h.time in seen:
            continue
        seen.add(h.time)
        h.temperature = _rng(h.temperature, TEMP_C)
        h.precipitation = _rng(h.precipitation, PRECIP_MM)
        h.precipitation_probability = _pct(h.precipitation_probability)
        h.weather_code = _code(h.weather_code)
        hourly.append(h)
    fc.hourly = hourly

    # ---- daily
    by_date = {}
    for d in sorted(fc.daily or [], key=lambda x: x.date):
        if isinstance(d.date, str) and d.date not in by_date:
            by_date[d.date] = d
    daily = list(by_date.values())[:max(1, int(days))]
    for d in daily:
        d.temp_max, d.temp_min = _rng(d.temp_max, TEMP_C), _rng(d.temp_min, TEMP_C)
        d.weather_code = _code(d.weather_code)
        if d.temp_max is not None and d.temp_min is not None and d.temp_min > d.temp_max:
            d.temp_max, d.temp_min = d.temp_min, d.temp_max
        d.precipitation_sum = _rng(d.precipitation_sum, PRECIP_MM)
        d.precipitation_probability_max = _pct(d.precipitation_probability_max)
        d.wind_speed_max = _rng(d.wind_speed_max, WIND_KMH)
        d.uv_index_max = _rng(d.uv_index_max, UV)
        day_hours = [h for h in hourly if h.time[:10] == d.date]
        if d.weather_code is None:
            codes = [h.weather_code for h in day_hours if h.weather_code is not None]
            if codes:
                d.weather_code = max(codes)
                note("daily condition (from hourly)")
        if d.precipitation_probability_max is None:
            pps = [h.precipitation_probability for h in day_hours if h.precipitation_probability is not None]
            if len(pps) >= 12:
                d.precipitation_probability_max = max(pps)
                note("daily chance of rain (from hourly)")
        if not d.sunrise or not d.sunset:
            try:
                rise, sett = sun_rise_set(dt.date.fromisoformat(d.date), lat, lon, tz)
            except ValueError:
                rise = sett = None
            if not d.sunrise and rise:
                d.sunrise = rise.strftime("%Y-%m-%dT%H:%M")
            if not d.sunset and sett:
                d.sunset = sett.strftime("%Y-%m-%dT%H:%M")
            if rise or sett:
                note("sunrise/sunset")
    fc.daily = daily
    if fc.utc_offset_seconds is None:
        off = cur_t.utcoffset()
        fc.utc_offset_seconds = int(off.total_seconds()) if off is not None else None
    fc.calculated = calc
    return fc
