"""OpenWeather (openweathermap.org). Needs a free API key.

Two ways in, picked automatically:
  * One Call API 3.0 - current, 48 hours hourly, 8 days daily, UV, sunrise/sunset.
    It's a separate "One Call" subscription on the OpenWeather account (1,000
    calls a day free; OpenWeather asks for a payment card to activate it).
  * The free key on its own - current weather plus the 5-day / 3-hour forecast.
    WeatherDesk spreads each 3-hour step across its hours for the chart and
    builds the days from the steps; there's no UV index on this plan.
If One Call answers "401" (not subscribed), WeatherDesk uses the free endpoints
and checks One Call again after a day.

Docs: https://openweathermap.org/api/one-call-3, https://openweathermap.org/forecast5

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Optional

from ..api import ApiError
from ..models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location
from . import register
from .base import (FEATURES, Provider, ProviderInfo, from_unix, kmh_from_ms, local_str, location_tz, num,
                   pct, quarter_hour, now_utc)

ONECALL_RECHECK_S = 24 * 3600


def owm_code(cid: Any) -> Optional[int]:
    """OpenWeather condition id -> WMO code (None for haze/smoke/dust: worked out from cloud)."""
    c = num(cid)
    if c is None:
        return None
    c = int(c)
    if 200 <= c < 300:
        return 95
    if 300 <= c < 400:
        return {300: 51, 301: 53, 302: 55, 310: 51, 311: 53, 312: 55, 313: 80, 314: 81, 321: 80}.get(c, 53)
    if 500 <= c < 600:
        return {500: 61, 501: 63, 502: 65, 503: 65, 504: 65, 511: 66,
                520: 80, 521: 81, 522: 82, 531: 81}.get(c, 63)
    if 600 <= c < 700:      # sleet shown as snow, as for MET Norway
        return {600: 71, 601: 73, 602: 75, 611: 73, 612: 71, 613: 85, 615: 71, 616: 73,
                620: 85, 621: 85, 622: 86}.get(c, 73)
    if c in (701, 741):
        return 45
    if c == 771:
        return 82
    if c == 781:
        return 95
    if 700 <= c < 800:
        return None
    return {800: 0, 801: 1, 802: 2, 803: 3, 804: 3}.get(c)


def _wid(block: dict) -> Optional[int]:
    w = block.get("weather")
    if isinstance(w, list) and w and isinstance(w[0], dict):
        return owm_code(w[0].get("id"))
    return None


def _precip(block: dict, period: str = "1h") -> Optional[float]:
    total, found = 0.0, False
    for k in ("rain", "snow"):
        v = block.get(k)
        if isinstance(v, dict):
            v = v.get(period)
        f = num(v)
        if f is not None:
            total += f
            found = True
    return round(total, 2) if found else None


@register
class OpenWeatherProvider(Provider):
    info = ProviderInfo(
        id="openweather", name="OpenWeather", needs_key=True,
        website="https://openweathermap.org/",
        credit="Weather data by OpenWeather (CC BY-SA 4.0)",
        coverage="Worldwide, from OpenWeather's own model blend of national weather services and "
                 "observations.",
        forecast_days="8 days with One Call 3.0; 5 days with a free key on its own",
        hourly="48 hours with One Call 3.0; 3-hourly with a free key",
        limits="Free key: 60 calls a minute, 1,000,000 a month (current weather + 5-day/3-hour "
               "forecast). One Call 3.0: first 1,000 calls a day free, then pay per call; a separate "
               "subscription that needs a payment card.",
        features=frozenset(FEATURES),
        signup_url="https://home.openweathermap.org/users/sign_up",
        docs_url="https://openweathermap.org/api/one-call-3",
        key_help="After signing in: your name → My API keys. New keys can take up to 2 hours to work.",
        min_interval_s=5 * 60,
        max_days=8,
    )

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._onecall_off_until = 0.0        # monotonic; while set, use the free endpoints
        self.plan = ""

    @classmethod
    def default_base_url(cls) -> str:
        return "https://api.openweathermap.org/data"

    def _error_reason(self, body: str) -> str:
        try:
            d = json.loads(body)
        except ValueError:
            return body.strip().splitlines()[0][:150] if body.strip() else ""
        return str(d.get("message", "")) if isinstance(d, dict) else ""

    def usage(self) -> dict:
        return {"plan": self.plan} if self.plan else {}

    def _fetch(self, location: Location, days: int) -> Forecast:
        params = {"lat": f"{location.latitude:.4f}", "lon": f"{location.longitude:.4f}",
                  "appid": self.api_key, "units": "metric"}
        if time.monotonic() >= self._onecall_off_until:
            try:
                data = self._get_json(f"{self.base_url}/3.0/onecall",
                                      dict(params, exclude="minutely,alerts"))
                self.plan = "One Call 3.0"
                return parse_onecall(data, location)
            except ApiError as e:
                if e.status != 401:
                    raise
                # not subscribed to One Call (or a bad key: the free endpoint will say)
                self._onecall_off_until = time.monotonic() + ONECALL_RECHECK_S
        cur = self._get_json(f"{self.base_url}/2.5/weather", params)
        fcst = self._get_json(f"{self.base_url}/2.5/forecast", params)
        self.plan = "Free key (current weather + 5-day/3-hour forecast)"
        return parse_free(cur, fcst, location)


# ---------------------------------------------------------------- One Call 3.0
def parse_onecall(data: Any, location: Location, now: Optional[dt.datetime] = None) -> Forecast:
    if not isinstance(data, dict) or not isinstance(data.get("current"), dict):
        raise ValueError("no 'current' block")
    tz, tz_name = location_tz(location, data.get("timezone"), num(data.get("timezone_offset")))
    c = data["current"]
    t = now or now_utc()
    rise, sett = from_unix(c.get("sunrise")), from_unix(c.get("sunset"))
    current = CurrentWeather(
        time=quarter_hour(t, tz), temperature=num(c.get("temp")),
        apparent_temperature=num(c.get("feels_like")), humidity=pct(c.get("humidity")),
        weather_code=_wid(c), is_day=(rise <= t < sett) if rise and sett else None,
        wind_speed=kmh_from_ms(c.get("wind_speed")), wind_direction=num(c.get("wind_deg")),
        wind_gusts=kmh_from_ms(c.get("wind_gust")), pressure=num(c.get("pressure")),
        cloud_cover=pct(c.get("clouds")), precipitation=_precip(c))
    hourly = []
    for h in data.get("hourly") or []:
        ht = from_unix(h.get("dt")) if isinstance(h, dict) else None
        if ht is None:
            continue
        hourly.append(HourlyPoint(local_str(ht, tz), num(h.get("temp")), pct(h.get("pop"), fraction=True),
                                  _precip(h), _wid(h)))
    daily = []
    for d in data.get("daily") or []:
        dt0 = from_unix(d.get("dt")) if isinstance(d, dict) else None
        if dt0 is None:
            continue
        temp = d.get("temp") if isinstance(d.get("temp"), dict) else {}
        r, s = from_unix(d.get("sunrise")), from_unix(d.get("sunset"))
        rain = sum(x for x in (num(d.get("rain")), num(d.get("snow"))) if x is not None) \
            if (num(d.get("rain")) is not None or num(d.get("snow")) is not None) else 0.0
        daily.append(DailyPoint(
            date=dt0.astimezone(tz).date().isoformat(), weather_code=_wid(d),
            temp_max=num(temp.get("max")), temp_min=num(temp.get("min")),
            precipitation_sum=round(rain, 1), precipitation_probability_max=pct(d.get("pop"), fraction=True),
            wind_speed_max=kmh_from_ms(d.get("wind_speed")),
            sunrise=local_str(r, tz) if r else None, sunset=local_str(s, tz) if s else None,
            uv_index_max=num(d.get("uvi"))))
    off = num(data.get("timezone_offset"))
    return Forecast(location=location, timezone=tz_name, current=current, hourly=hourly, daily=daily,
                    utc_offset_seconds=int(off) if off is not None else None)


# ------------------------------------------------------------- free endpoints
def parse_free(cur: Any, fcst: Any, location: Location) -> Forecast:
    if not isinstance(cur, dict) or not isinstance(cur.get("main"), dict):
        raise ValueError("no 'main' block in current weather")
    steps = [s for s in (fcst.get("list") if isinstance(fcst, dict) else None) or []
             if isinstance(s, dict) and from_unix(s.get("dt"))]
    city = fcst.get("city", {}) if isinstance(fcst, dict) else {}
    off = num(cur.get("timezone"))
    if off is None:
        off = num(city.get("timezone"))
    tz, tz_name = location_tz(location, None, off)
    m, w = cur["main"], cur.get("wind") or {}
    t = now_utc()
    sysb = cur.get("sys") or {}
    rise, sett = from_unix(sysb.get("sunrise")), from_unix(sysb.get("sunset"))
    current = CurrentWeather(
        time=quarter_hour(t, tz), temperature=num(m.get("temp")),
        apparent_temperature=num(m.get("feels_like")), humidity=pct(m.get("humidity")),
        weather_code=_wid(cur), is_day=(rise <= t < sett) if rise and sett else None,
        wind_speed=kmh_from_ms(w.get("speed")), wind_direction=num(w.get("deg")),
        wind_gusts=kmh_from_ms(w.get("gust")), pressure=num(m.get("pressure")),
        cloud_cover=pct((cur.get("clouds") or {}).get("all")), precipitation=_precip(cur))

    # hourly: each 3-hour step spread over its hours (temperature interpolated between steps)
    hourly = []
    for i, s in enumerate(steps):
        st = from_unix(s["dt"])
        t0 = num((s.get("main") or {}).get("temp"))
        nxt = steps[i + 1] if i + 1 < len(steps) else None
        t1 = num((nxt.get("main") or {}).get("temp")) if nxt else None
        amt = _precip(s, "3h")
        for k in range(3):
            temp = t0 if t0 is None or t1 is None else round(t0 + (t1 - t0) * k / 3, 1)
            hourly.append(HourlyPoint(local_str(st + dt.timedelta(hours=k), tz), temp,
                                      pct(s.get("pop"), fraction=True),
                                      None if amt is None else round(amt / 3, 2), _wid(s)))

    # daily: from the steps of each local day
    days: dict[str, dict] = {}
    for s in steps:
        d = from_unix(s["dt"]).astimezone(tz).date().isoformat()
        a = days.setdefault(d, {"hi": [], "lo": [], "pop": [], "rain": 0.0, "wind": [], "codes": []})
        mm = s.get("main") or {}
        a["hi"].append(num(mm.get("temp_max")) if num(mm.get("temp_max")) is not None else num(mm.get("temp")))
        a["lo"].append(num(mm.get("temp_min")) if num(mm.get("temp_min")) is not None else num(mm.get("temp")))
        a["pop"].append(pct(s.get("pop"), fraction=True))
        a["rain"] += _precip(s, "3h") or 0.0
        a["wind"].append(kmh_from_ms((s.get("wind") or {}).get("speed")))
        a["codes"].append(_wid(s))
    today = t.astimezone(tz).date().isoformat()
    daily = []
    for d, a in days.items():
        hi = [x for x in a["hi"] if x is not None]
        lo = [x for x in a["lo"] if x is not None]
        if not hi:
            continue
        if d == today:              # today's steps start now; include the current reading
            hi.append(current.temperature)
            lo.append(current.temperature)
        codes = [x for x in a["codes"] if x is not None]
        pops = [x for x in a["pop"] if x is not None]
        winds = [x for x in a["wind"] if x is not None]
        daily.append(DailyPoint(
            date=d, weather_code=max(codes) if codes else None, temp_max=max(hi), temp_min=min(lo),
            precipitation_sum=round(a["rain"], 1), precipitation_probability_max=max(pops) if pops else None,
            wind_speed_max=max(winds) if winds else None,
            sunrise=local_str(rise, tz) if d == today and rise else None,
            sunset=local_str(sett, tz) if d == today and sett else None,
            uv_index_max=None))
    fc = Forecast(location=location, timezone=tz_name, current=current, hourly=hourly, daily=daily,
                  utc_offset_seconds=int(off) if off is not None else None)
    fc.calculated = ["hourly (spread from 3-hourly steps)", "daily values (from 3-hourly steps)"]
    return fc
