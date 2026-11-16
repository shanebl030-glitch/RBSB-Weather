"""Open-Meteo client (forecast + geocoding) using only the Python standard library.

No API key or account is needed. Base URLs are configurable so the test suite
can point the client at a local server and never touch the internet.
"""

from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from . import __version__
from .net import build_opener, clear_last_connection, last_connection, mark_bad
from .models import CurrentWeather, DailyPoint, Forecast, HourlyPoint, Location

log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

DEFAULT_TIMEOUT = 15.0
MAX_RESPONSE_BYTES = 5 * 1024 * 1024   # guard against runaway responses

CURRENT_FIELDS = [
    "temperature_2m", "relative_humidity_2m", "apparent_temperature", "is_day",
    "precipitation", "weather_code", "cloud_cover", "pressure_msl",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
]
HOURLY_FIELDS = ["temperature_2m", "precipitation_probability", "precipitation", "weather_code"]
DAILY_FIELDS = [
    "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
    "precipitation_probability_max", "wind_speed_10m_max", "sunrise", "sunset", "uv_index_max",
]


class WeatherError(Exception):
    """Base class for all errors raised by the client. Message is user-friendly."""


class NetworkError(WeatherError):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable      # a stall/timeout/reset: worth one retry elsewhere


class ApiError(WeatherError):
    pass


class DataError(WeatherError):
    pass


class OpenMeteoClient:
    def __init__(self, forecast_url: str = FORECAST_URL, geocode_url: str = GEOCODE_URL,
                 timeout: float = DEFAULT_TIMEOUT, ssl_context=None):
        self.forecast_url = forecast_url
        self.geocode_url = geocode_url
        self.timeout = timeout
        self.user_agent = f"WeatherDesk/{__version__} (Created By Shane BlackbuRn)"
        # Races IPv6/IPv4 so a broken IPv6 route can't stall every request.
        self.ssl_context = ssl_context
        self._opener = build_opener(ssl_context)

    # ------------------------------------------------------------------ HTTP
    def _get_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET with one automatic retry after a stall/timeout/reset. The address
        that failed (and IPv6 as a whole, if that's what failed) is avoided, so
        the retry - and the next few minutes of requests - go another way."""
        for attempt in (1, 2):
            clear_last_connection()
            try:
                return self._get_json_once(url, params)
            except NetworkError as e:
                info = last_connection()
                if attempt == 1 and e.retryable:
                    if info:
                        mark_bad(info["address"], info["port"], info["family_num"])
                    log.warning("request failed (%s)%s; retrying once", e,
                                f" via {info['family']} {info['address']}" if info else "")
                    continue
                raise
        raise AssertionError("unreachable")      # pragma: no cover

    def _get_json_once(self, url: str, params: dict[str, Any]) -> Any:
        full = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(full, headers={"User-Agent": self.user_agent,
                                                    "Accept": "application/json"})
        t0 = time.monotonic()
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as e:
            reason = ""
            try:
                body = json.loads(e.read(65536).decode("utf-8", "replace"))
                reason = body.get("reason", "") if isinstance(body, dict) else ""
            except Exception:
                pass
            finally:
                e.close()
            raise ApiError(f"Weather service returned HTTP {e.code}"
                           + (f": {reason}" if reason else "")) from None
        except (socket.timeout, TimeoutError):
            raise NetworkError("The weather service did not respond in time.", retryable=True) from None
        except urllib.error.URLError as e:
            r = e.reason
            if isinstance(r, (socket.timeout, TimeoutError)) and "handshake" in str(r).lower():
                raise NetworkError("The secure connection to the weather service timed out "
                                   "(the network may be blocking or slowing it).", retryable=True) from None
            if isinstance(r, (socket.timeout, TimeoutError)):
                raise NetworkError("The weather service did not respond in time.", retryable=True) from None
            if isinstance(r, (ssl.SSLError, ConnectionResetError, ConnectionAbortedError)):
                raise NetworkError(f"The secure connection to the weather service failed ({r}).",
                                   retryable=not isinstance(r, ssl.SSLCertVerificationError)) from None
            raise NetworkError(f"Could not reach the weather service ({r}).") from None
        except (ConnectionResetError, ConnectionAbortedError, ssl.SSLError) as e:
            raise NetworkError(f"The connection to the weather service was interrupted ({e}).",
                               retryable=not isinstance(e, ssl.SSLCertVerificationError)) from None
        except (ConnectionError, OSError) as e:
            raise NetworkError(f"Network error: {e}") from None

        log.info("GET %s: %d bytes in %d ms", urllib.parse.urlsplit(url).netloc + urllib.parse.urlsplit(url).path,
                 len(raw), (time.monotonic() - t0) * 1000)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DataError("Response from the weather service was unexpectedly large.")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise DataError("The weather service sent data that could not be read.") from None
        if isinstance(data, dict) and data.get("error"):
            raise ApiError(f"Weather service error: {data.get('reason', 'unknown')}")
        return data

    # ------------------------------------------------------------ Geocoding
    def search_locations(self, query: str, count: int = 10) -> list[Location]:
        query = (query or "").strip()
        if len(query) < 2:
            return []
        data = self._get_json(self.geocode_url, {
            "name": query, "count": max(1, min(int(count), 20)),
            "language": "en", "format": "json",
        })
        return parse_geocode(data)

    # ------------------------------------------------------------- Forecast
    def fetch_forecast(self, location: Location, forecast_days: int = 7) -> Forecast:
        data = self._get_json(self.forecast_url, {
            "latitude": f"{location.latitude:.4f}",
            "longitude": f"{location.longitude:.4f}",
            "current": ",".join(CURRENT_FIELDS),
            "hourly": ",".join(HOURLY_FIELDS),
            "daily": ",".join(DAILY_FIELDS),
            "timezone": location.timezone or "auto",
            "forecast_days": max(1, min(int(forecast_days), 16)),
        })
        fc = parse_forecast(data, location)
        fc.fetched_at = time.time()
        return fc


# ---------------------------------------------------------------- Parsing
def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(f)


def _col(block: dict, key: str, n: int) -> list:
    col = block.get(key)
    if not isinstance(col, list):
        return [None] * n
    return (col + [None] * n)[:n]


def parse_geocode(data: Any) -> list[Location]:
    if not isinstance(data, dict):
        raise DataError("Unexpected location search response.")
    out: list[Location] = []
    seen: set[str] = set()
    for r in data.get("results") or []:
        if not isinstance(r, dict):
            continue
        lat, lon = _num(r.get("latitude")), _num(r.get("longitude"))
        name = r.get("name")
        if lat is None or lon is None or not name:
            continue
        loc = Location(name=str(name), latitude=lat, longitude=lon,
                       country=str(r.get("country") or ""), admin1=str(r.get("admin1") or ""),
                       timezone=str(r.get("timezone") or "auto"))
        if loc.key in seen:
            continue
        seen.add(loc.key)
        out.append(loc)
    return out


def parse_forecast(data: Any, location: Location) -> Forecast:
    if not isinstance(data, dict):
        raise DataError("Unexpected forecast response.")
    cur = data.get("current")
    if not isinstance(cur, dict) or _num(cur.get("temperature_2m")) is None:
        raise DataError("Forecast response is missing current conditions.")

    current = CurrentWeather(
        time=str(cur.get("time", "")),
        temperature=_num(cur.get("temperature_2m")),
        apparent_temperature=_num(cur.get("apparent_temperature")),
        humidity=_num(cur.get("relative_humidity_2m")),
        weather_code=_int(cur.get("weather_code")) or 0,
        is_day=_int(cur.get("is_day")) != 0,   # missing/invalid -> treat as day
        wind_speed=_num(cur.get("wind_speed_10m")),
        wind_direction=_num(cur.get("wind_direction_10m")),
        wind_gusts=_num(cur.get("wind_gusts_10m")),
        pressure=_num(cur.get("pressure_msl")),
        cloud_cover=_num(cur.get("cloud_cover")),
        precipitation=_num(cur.get("precipitation")),
    )

    hourly: list[HourlyPoint] = []
    h = data.get("hourly")
    if isinstance(h, dict) and isinstance(h.get("time"), list):
        n = len(h["time"])
        t, temp, pp, pr, wc = (h["time"], _col(h, "temperature_2m", n),
                               _col(h, "precipitation_probability", n),
                               _col(h, "precipitation", n), _col(h, "weather_code", n))
        for i in range(n):
            hourly.append(HourlyPoint(str(t[i]), _num(temp[i]), _num(pp[i]), _num(pr[i]), _int(wc[i])))

    daily: list[DailyPoint] = []
    d = data.get("daily")
    if isinstance(d, dict) and isinstance(d.get("time"), list):
        n = len(d["time"])
        cols = {k: _col(d, k, n) for k in DAILY_FIELDS}
        for i in range(n):
            daily.append(DailyPoint(
                date=str(d["time"][i]),
                weather_code=_int(cols["weather_code"][i]),
                temp_max=_num(cols["temperature_2m_max"][i]),
                temp_min=_num(cols["temperature_2m_min"][i]),
                precipitation_sum=_num(cols["precipitation_sum"][i]),
                precipitation_probability_max=_num(cols["precipitation_probability_max"][i]),
                wind_speed_max=_num(cols["wind_speed_10m_max"][i]),
                sunrise=cols["sunrise"][i] if isinstance(cols["sunrise"][i], str) else None,
                sunset=cols["sunset"][i] if isinstance(cols["sunset"][i], str) else None,
                uv_index_max=_num(cols["uv_index_max"][i]),
            ))

    off = data.get("utc_offset_seconds")
    return Forecast(location=location, timezone=str(data.get("timezone") or location.timezone),
                    current=current, hourly=hourly, daily=daily,
                    utc_offset_seconds=int(off) if isinstance(off, (int, float)) and not isinstance(off, bool) else None)


# ------------------------------------------------------ Cache (de)serialise
def forecast_to_dict(fc: Forecast) -> dict:
    from dataclasses import asdict
    d = asdict(fc)
    d.pop("from_cache", None)
    return d


def forecast_from_dict(d: dict) -> Forecast:
    try:
        return Forecast(
            location=Location.from_dict(d["location"]),
            timezone=str(d.get("timezone", "auto")),
            current=CurrentWeather(**d["current"]),
            hourly=[HourlyPoint(**x) for x in d.get("hourly", [])],
            daily=[DailyPoint(**x) for x in d.get("daily", [])],
            fetched_at=float(d.get("fetched_at", 0.0)),
            utc_offset_seconds=d.get("utc_offset_seconds"),
            from_cache=True,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise DataError(f"Cached forecast is invalid: {e}") from None
