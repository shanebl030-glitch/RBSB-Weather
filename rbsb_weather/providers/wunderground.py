"""Weather Underground (The Weather Company), with a personal weather station
(PWS) owner's API key.

What a PWS key gives (The Weather Company's "APIs for PWS contributors"):
  * the Daily Forecast (5 Day) - today plus 5 days, with day and night parts:
    condition, chance of rain, humidity, wind, UV, cloud cover, sunrise/sunset;
  * current observations from personal weather stations;
  * Location Services "near", which finds the stations closest to a place.
There's no hourly forecast on a PWS key, so the 24-hour chart stays empty while
Weather Underground supplies the weather (or a backup supplies it).

Current conditions come from your own station if you enter its ID in Settings →
Weather Providers, otherwise from the nearest station that's reporting. Stations
don't report a weather condition, so the current condition comes from the
forecast for this part of the day (shown under "Calculated by RBSB-Weather").

Docs: https://www.wunderground.com/member/api-keys and
https://docs.google.com/document/d/1eKCnKXI9xnoMGRRzOL1xPCBihNV2rOet08qpE_gArAY

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Any, Optional

from ..api import DataError
from ..models import CurrentWeather, DailyPoint, Forecast, Location
from . import register
from .base import FEATURES, Provider, ProviderInfo, from_iso, local_str, location_tz, now_utc, num, pct, quarter_hour

STATIONS_FOR_S = 24 * 3600     # nearby-station list is kept this long per location
STATION_MAX_AGE_S = 2 * 3600   # a station whose last report is older than this is skipped
NEARBY_TRIES = 3

# The Weather Company icon codes -> WMO codes (None: worked out from cloud and rain)
_ICONS = {
    0: 95, 1: 95, 2: 95, 3: 95, 4: 95, 5: 71, 6: 71, 7: 71, 8: 56, 9: 53, 10: 67, 11: 81, 12: 63,
    13: 71, 14: 85, 15: 73, 16: 73, 17: 96, 18: 71, 19: None, 20: 45, 21: None, 22: None, 23: None,
    24: None, 25: None, 26: 3, 27: 3, 28: 3, 29: 2, 30: 2, 31: 0, 32: 0, 33: 1, 34: 1, 35: 96, 36: 0,
    37: 95, 38: 95, 39: 80, 40: 65, 41: 85, 42: 75, 43: 75, 44: None, 45: 80, 46: 85, 47: 95,
}


def icon_code(v: Any) -> Optional[int]:
    c = num(v)
    return None if c is None else _ICONS.get(int(c))


def _at(arr: Any, i: int):
    return arr[i] if isinstance(arr, list) and 0 <= i < len(arr) else None


@register
class WundergroundProvider(Provider):
    info = ProviderInfo(
        id="wunderground", name="Weather Underground", needs_key=True,
        website="https://www.wunderground.com/",
        credit="Weather data by Weather Underground / The Weather Company",
        coverage="Worldwide forecast from The Weather Company; current conditions from your own or "
                 "the nearest personal weather station (PWS).",
        forecast_days="5 days plus today",
        hourly="none with a PWS key (the 24-hour chart stays empty)",
        limits="Free API key for people who upload data from their own weather station "
               "(personal, non-commercial use). The Weather Company limits PWS keys to about "
               "1,500 calls a day and 30 a minute; each update uses 2.",
        features=frozenset(FEATURES) - {"hourly", "feels_like", "cloud"},
        signup_url="https://www.wunderground.com/member/api-keys",
        docs_url="https://docs.google.com/document/d/1eKCnKXI9xnoMGRRzOL1xPCBihNV2rOet08qpE_gArAY",
        key_help="Sign in at wunderground.com → My Profile → API Keys (available to members who send "
                 "data from a personal weather station).",
        min_interval_s=5 * 60,
        max_days=6,
        options=(("station_id", "Station ID",
                  "Optional: your weather station's ID (e.g. IWAIUK12) for current conditions. "
                  "Leave empty to use the nearest station that's reporting.",
                  r"[A-Za-z0-9]{3,24}"),),
    )

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._stations: dict[str, tuple[float, list[str]]] = {}   # location key -> (time, station ids)
        self.station_used = ""

    @classmethod
    def default_base_url(cls) -> str:
        return "https://api.weather.com"

    def _error_reason(self, body: str) -> str:
        try:
            d = json.loads(body)
        except ValueError:
            return body.strip().splitlines()[0][:150] if body.strip() else ""
        errs = d.get("errors") if isinstance(d, dict) else None
        if isinstance(errs, list) and errs and isinstance(errs[0], dict):
            e = errs[0].get("error") or {}
            return str(e.get("message", ""))
        return ""

    def usage(self) -> dict:
        return {"station": f"current conditions from station {self.station_used}"} if self.station_used else {}

    # ------------------------------------------------------------------------
    def _fetch(self, location: Location, days: int) -> Forecast:
        geo = f"{location.latitude:.4f},{location.longitude:.4f}"
        fc_data = self._get_json(f"{self.base_url}/v3/wx/forecast/daily/5day", {
            "geocode": geo, "format": "json", "units": "m", "language": "en-US", "apiKey": self.api_key})
        obs, station = self._observation(location, geo)
        self.station_used = station
        return parse_wunderground(fc_data, obs, location)

    def _observation(self, location: Location, geo: str) -> tuple[dict, str]:
        own = self.options.get("station_id", "")
        candidates = [own] if own else self._nearby(location, geo)
        problems = []
        for sid in candidates[:NEARBY_TRIES] if not own else candidates:
            try:
                data = self._get_json(f"{self.base_url}/v2/pws/observations/current", {
                    "stationId": sid, "format": "json", "units": "m", "numericPrecision": "decimal",
                    "apiKey": self.api_key})
            except DataError:
                problems.append(f"{sid}: not reporting")      # HTTP 204: station offline
                continue
            ob = _at((data or {}).get("observations") if isinstance(data, dict) else None, 0)
            if not isinstance(ob, dict) or not isinstance(ob.get("metric"), dict):
                problems.append(f"{sid}: no data")
                continue
            age = time.time() - (num(ob.get("epoch")) or 0)
            if age > STATION_MAX_AGE_S:
                problems.append(f"{sid}: last report {int(age // 3600)} h ago")
                continue
            return ob, sid
        if own:
            raise DataError(f"Your weather station {own} isn't reporting current conditions "
                            f"({'; '.join(problems) or 'no data'}).")
        raise DataError("No nearby weather station is reporting current conditions"
                        + (f" ({'; '.join(problems)})." if problems else "."))

    def _nearby(self, location: Location, geo: str) -> list[str]:
        cached = self._stations.get(location.key)
        if cached and time.time() - cached[0] < STATIONS_FOR_S:
            return cached[1]
        data = self._get_json(f"{self.base_url}/v3/location/near", {
            "geocode": geo, "product": "pws", "format": "json", "apiKey": self.api_key})
        loc = data.get("location") if isinstance(data, dict) else None
        ids = loc.get("stationId") if isinstance(loc, dict) else None
        qc = loc.get("qcStatus") if isinstance(loc, dict) else None
        out = [s for i, s in enumerate(ids or []) if isinstance(s, str) and s
               and (num(_at(qc, i)) is None or num(_at(qc, i)) >= 0)]
        if not out:
            raise DataError("Weather Underground found no personal weather stations near this location.")
        self._stations[location.key] = (time.time(), out)
        return out


def parse_wunderground(fcd: Any, ob: dict, location: Location, now: Optional[dt.datetime] = None) -> Forecast:
    if not isinstance(fcd, dict) or not isinstance(fcd.get("validTimeLocal"), list):
        raise ValueError("no daily forecast arrays")
    tz, tz_name = location_tz(location)
    now = now or now_utc()
    parts = _at(fcd.get("daypart"), 0) or {}
    m = ob.get("metric") or {}

    # this part of the day: day part of today's forecast, else tonight's
    today_day = _at(parts.get("iconCode"), 0)
    cur_part = 0 if today_day is not None else 1
    calc = ["current condition (from the forecast for this part of the day)"]
    current = CurrentWeather(
        time=quarter_hour(now, tz), temperature=num(m.get("temp")),
        apparent_temperature=None,                         # calculated like every other provider
        humidity=pct(ob.get("humidity")),
        weather_code=icon_code(_at(parts.get("iconCode"), cur_part)),
        is_day=None, wind_speed=num(m.get("windSpeed")), wind_direction=num(ob.get("winddir")),
        wind_gusts=num(m.get("windGust")), pressure=num(m.get("pressure")),
        cloud_cover=pct(_at(parts.get("cloudCover"), cur_part)),
        precipitation=num(m.get("precipRate")))
    if current.cloud_cover is not None:
        calc.append("cloud cover (from the forecast)")
    # The forecast's condition covers the whole day or night; the station knows whether
    # it's actually raining now. Wet forecast but a dry station: show the cloud instead.
    # Dry forecast but rain at the station: show rain.
    rate = current.precipitation
    wet = current.weather_code is not None and current.weather_code >= 51 and current.weather_code != 45
    if rate is not None:
        from .normalise import code_from
        if wet and rate <= 0.05:
            current.weather_code = code_from(current.cloud_cover, None)
            calc[0] = "current condition (forecast for this part of the day, no rain at the station now)"
        elif not wet and rate > 0.05:
            current.weather_code = code_from(None, rate)
            calc[0] = "current condition (rain measured at the station now)"

    daily = []
    for i, vt in enumerate(fcd.get("validTimeLocal") or []):
        t = from_iso(vt)
        if t is None:
            continue
        date = t.date().isoformat()                         # already local to the location
        d_i, n_i = 2 * i, 2 * i + 1
        code = icon_code(_at(parts.get("iconCode"), d_i))
        if code is None:
            code = icon_code(_at(parts.get("iconCode"), n_i))
        chances = [x for x in (pct(_at(parts.get("precipChance"), d_i)),
                               pct(_at(parts.get("precipChance"), n_i))) if x is not None]
        winds = [x for x in (num(_at(parts.get("windSpeed"), d_i)), num(_at(parts.get("windSpeed"), n_i)))
                 if x is not None]
        rise, sett = from_iso(_at(fcd.get("sunriseTimeLocal"), i)), from_iso(_at(fcd.get("sunsetTimeLocal"), i))
        hi = num(_at(fcd.get("calendarDayTemperatureMax"), i))
        lo = num(_at(fcd.get("calendarDayTemperatureMin"), i))
        if hi is None:
            hi = num(_at(fcd.get("temperatureMax"), i))
        if lo is None:
            lo = num(_at(fcd.get("temperatureMin"), i))
        daily.append(DailyPoint(
            date=date, weather_code=code, temp_max=hi, temp_min=lo,
            precipitation_sum=num(_at(fcd.get("qpf"), i)),
            precipitation_probability_max=max(chances) if chances else None,
            wind_speed_max=max(winds) if winds else None,
            sunrise=local_str(rise, tz) if rise else None, sunset=local_str(sett, tz) if sett else None,
            uv_index_max=num(_at(parts.get("uvIndex"), d_i))))
    if daily and current.temperature is not None:
        # today's calendar-day range should include what the station measures now
        d0 = daily[0]
        if d0.temp_max is not None and current.temperature > d0.temp_max:
            d0.temp_max = current.temperature
        if d0.temp_min is not None and current.temperature < d0.temp_min:
            d0.temp_min = current.temperature
    fc = Forecast(location=location, timezone=tz_name, current=current, hourly=[], daily=daily)
    fc.calculated = calc
    return fc

