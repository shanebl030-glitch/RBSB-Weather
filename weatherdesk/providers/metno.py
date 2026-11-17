"""MET Norway (built in, no key). Wraps weatherdesk/metno.py.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from typing import Optional

from ..metno import CREDIT, FORECAST_URL, MetNoClient
from ..models import Forecast, Location
from . import register
from .base import FEATURES, Provider, ProviderInfo


@register
class MetNoProvider(Provider):
    info = ProviderInfo(
        id="met.no", name="MET Norway", needs_key=False,
        website="https://api.met.no/",
        credit=CREDIT,
        coverage="Worldwide (ECMWF outside the Nordic countries), run by the Norwegian "
                 "Meteorological Institute; the data behind yr.no.",
        forecast_days="about 9 days (WeatherDesk uses 7)",
        hourly="every hour for about 2½ days, then 6-hourly",
        limits="Free, no key: fair use (up to 20 requests a second per app); identify the app "
               "and don't request more often than needed.",
        features=frozenset(FEATURES) - {"sun"},
        docs_url="https://api.met.no/weatherapi/locationforecast/2.0/documentation",
        max_days=9,
    )

    def __init__(self, client: Optional[MetNoClient] = None, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, timeout: float = 15.0, ssl_context=None):
        super().__init__(base_url=base_url, api_key=None, timeout=timeout, ssl_context=ssl_context)
        self.client = client or MetNoClient(self.base_url, timeout=timeout, ssl_context=ssl_context)

    @classmethod
    def default_base_url(cls) -> str:
        return FORECAST_URL

    def _fetch(self, location: Location, days: int) -> Forecast:
        fc = self.client.fetch_forecast(location, days)
        fc.calculated = list(dict.fromkeys(fc.calculated + ["sunrise/sunset", "day/night", "feels like"]))
        return fc
