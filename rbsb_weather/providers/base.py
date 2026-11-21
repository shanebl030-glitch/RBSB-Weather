"""The provider interface every weather service integration implements.

A provider is a small class that:
  1. declares a ProviderInfo (name, whether it needs a key, coverage, features,
     limits, sign-up link, attribution), and
  2. implements _fetch(location, days), turning that service's response into
     RBSB-Weather's common Forecast model: WMO weather codes, °C, km/h, mm, hPa,
     %, and local times as "YYYY-MM-DDTHH:MM".

Everything else (fallback between providers, key storage, filling in values the
service doesn't supply, status and usage tracking) is shared. To add a service,
write a module in this package and decorate its class with @register.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..api import DEFAULT_TIMEOUT, ApiError, DataError, JsonHttpClient, NetworkError, WeatherError
from ..models import Forecast, Location
from ..moon import tz_for
from ..keystore import redact

# Features a provider may supply (shown as a checklist in Settings → Weather Providers)
FEATURES = {
    "current": "Current conditions",
    "hourly": "Hourly forecast",
    "daily": "Daily forecast",
    "rain_probability": "Chance of rain",
    "feels_like": "Feels-like temperature",
    "humidity": "Humidity",
    "wind": "Wind speed and direction",
    "gusts": "Wind gusts",
    "pressure": "Pressure",
    "cloud": "Cloud cover",
    "uv": "UV index",
    "sun": "Sunrise and sunset",
}


@dataclass(frozen=True)
class ProviderInfo:
    id: str                         # stable id used in settings ("open-meteo", "openweather", ...)
    name: str                       # display name
    needs_key: bool
    website: str
    credit: str                     # attribution shown in the status bar while it supplies the weather
    coverage: str                   # where it works / what it's based on
    forecast_days: str              # e.g. "16 days", "3 days (free plan), 14 days (paid)"
    hourly: str                     # e.g. "48 hours", "none"
    limits: str                     # free allowance and limits, plain English
    features: frozenset = field(default_factory=frozenset)
    signup_url: str = ""
    docs_url: str = ""
    key_help: str = ""              # where to find the key once signed up
    status: str = "integrated"      # "integrated" or "planned"
    planned_reason: str = ""
    # Quota guard: at most one request per location this often (seconds). Retries and
    # several windows can't then burn through a small free allowance.
    min_interval_s: int = 0
    max_days: int = 16              # most days the service can return
    # Non-secret settings the provider accepts, shown in Settings → Weather Providers:
    # ((name, label, help, regex the value must match), ...)
    options: tuple = ()


class KeyMissing(WeatherError):
    """The provider needs an API key and none is saved."""


class Provider(JsonHttpClient):
    """Base class. Subclasses set `info` and implement _fetch()."""
    info: ProviderInfo

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT, ssl_context=None):
        super().__init__(timeout=timeout, ssl_context=ssl_context)
        self.base_url = (base_url or self.default_base_url()).rstrip("/")
        self.api_key = api_key
        self.options: dict[str, str] = {}      # values for info.options (set by the manager)

    # ---- subclass interface -------------------------------------------------
    @classmethod
    def default_base_url(cls) -> str:          # pragma: no cover - overridden
        return ""

    def _fetch(self, location: Location, days: int) -> Forecast:     # pragma: no cover
        raise NotImplementedError

    def usage(self) -> dict:
        """Usage/limits the service reported with the last response, e.g.
        {"remaining": "487 of 500 today"}. Empty if it doesn't say."""
        return {}

    @property
    def source_name(self) -> str:             # used in messages and Forecast.source
        return self.info.name

    # ---- shared -------------------------------------------------------------
    def fetch_forecast(self, location: Location, forecast_days: int = 7) -> Forecast:
        """Fetch, convert and normalise. Errors are re-raised with any API key removed
        from the message (some services echo the key back in their error text)."""
        from .normalise import normalise
        if self.info.needs_key and not self.api_key:
            raise KeyMissing(f"{self.info.name} needs an API key (Settings → Weather Providers).")
        days = max(1, min(int(forecast_days), self.info.max_days))
        try:
            fc = self._fetch(location, days)
        except WeatherError as e:
            raise _with_message(e, self._explain(e)) from None
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, ArithmeticError,
                RecursionError, UnicodeError) as e:
            raise DataError(f"{self.info.name} sent data RBSB-Weather couldn't read "
                            f"({redact(type(e).__name__ + ': ' + str(e), [self.api_key])[:120]}).") from None
        fc.source = self.info.name
        fc.provider_id = self.info.id
        if not fc.fetched_at:
            fc.fetched_at = time.time()
        return normalise(fc, location, days)

    def _explain(self, e: WeatherError) -> str:
        """Plain-English message for common failures; never contains the key."""
        msg = str(e)
        if isinstance(e, ApiError) and e.status in (401, 403, 429):
            reason = msg.split(": ", 1)[1].strip() if ": " in msg else ""
            detail = f" ({reason.rstrip('.')})" if reason else ""
            if e.status == 429 or any(w in reason.lower() for w in ("quota", "exceed", "limit")):
                msg = f"{self.info.name}'s usage limit has been reached for now (HTTP {e.status}){detail}."
            else:
                msg = (f"{self.info.name} rejected the API key (HTTP {e.status}){detail}. Check the key in "
                       f"Settings → Weather Providers" +
                       (", and that it has access to the forecast API" if self.info.needs_key else "") + ".")
        return redact(msg, [self.api_key])

    def test(self, location: Location) -> tuple[Forecast, dict]:
        """One real forecast request (Settings → Test connection)."""
        fc = self.fetch_forecast(location, 7)
        return fc, self.usage()


def _with_message(e: WeatherError, msg: str) -> WeatherError:
    if isinstance(e, NetworkError):
        return NetworkError(msg, retryable=e.retryable)
    if isinstance(e, ApiError):
        return ApiError(msg, status=e.status)
    return type(e)(msg)


# ---- helpers for converting responses --------------------------------------------
def num(v: Any) -> Optional[float]:
    """A finite float, or None (missing, text, NaN, bool)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def kmh_from_ms(v: Any) -> Optional[float]:
    f = num(v)
    return None if f is None else round(f * 3.6, 1)


def pct(v: Any, fraction: bool = False) -> Optional[float]:
    """A percentage 0..100 (from 0..1 when fraction=True)."""
    f = num(v)
    if f is None:
        return None
    return max(0.0, min(100.0, f * 100.0 if fraction else f))


def location_tz(location: Location, name: Optional[str] = None,
                offset_s: Optional[float] = None) -> tuple[dt.tzinfo, str]:
    """The location's time zone: the provider's zone name, else the saved location's,
    else the provider's UTC offset, else the nearest hour from the longitude."""
    for n in (name, location.timezone):
        if n and n not in ("auto", "UTC", "GMT"):
            tz = tz_for(n)
            if tz is not dt.timezone.utc:
                return tz, n
    if offset_s is not None:
        return dt.timezone(dt.timedelta(seconds=int(offset_s))), "auto"
    hours = max(-12, min(14, round(location.longitude / 15.0)))
    return dt.timezone(dt.timedelta(hours=hours)), "auto"


def local_str(t: dt.datetime, tz: dt.tzinfo) -> str:
    return t.astimezone(tz).strftime("%Y-%m-%dT%H:%M")


def from_unix(ts: Any) -> Optional[dt.datetime]:
    f = num(ts)
    if f is None:
        return None
    try:
        return dt.datetime.fromtimestamp(f, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def from_iso(s: Any) -> Optional[dt.datetime]:
    """An ISO time with a zone ("...Z" or "+13:00"); None if unreadable or zone-less."""
    if not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def quarter_hour(t: dt.datetime, tz: dt.tzinfo) -> str:
    lt = t.astimezone(tz)
    return lt.replace(minute=lt.minute - lt.minute % 15).strftime("%Y-%m-%dT%H:%M")


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
