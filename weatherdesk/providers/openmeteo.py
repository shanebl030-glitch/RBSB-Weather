"""Open-Meteo (built in, no key). Wraps the existing client in api.py, which also
provides location search for every provider.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from typing import Optional

from ..api import FORECAST_URL, OpenMeteoClient
from ..models import Forecast, Location
from . import register
from .base import FEATURES, Provider, ProviderInfo


@register
class OpenMeteoProvider(Provider):
    info = ProviderInfo(
        id="open-meteo", name="Open-Meteo", needs_key=False,
        website="https://open-meteo.com/",
        credit="Weather data by Open-Meteo.com (CC BY 4.0)",
        coverage="Worldwide. Blends national weather models (ECMWF, GFS, ICON, and in NZ/Australia "
                 "the ACCESS-G model) at up to 1–11 km resolution.",
        forecast_days="up to 16 days (WeatherDesk uses 7)",
        hourly="every hour, all 7 days",
        limits="Free, no key, for non-commercial use: fair use under 10,000 requests a day.",
        features=frozenset(FEATURES),
        docs_url="https://open-meteo.com/en/docs",
    )

    def __init__(self, client: Optional[OpenMeteoClient] = None, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: float = 15.0, ssl_context=None):
        super().__init__(base_url=base_url, api_key=None, timeout=timeout, ssl_context=ssl_context)
        self.client = client or OpenMeteoClient(self.base_url, timeout=timeout, ssl_context=ssl_context)

    @classmethod
    def default_base_url(cls) -> str:
        return FORECAST_URL

    def _fetch(self, location: Location, days: int) -> Forecast:
        return self.client.fetch_open_meteo(location, days)
