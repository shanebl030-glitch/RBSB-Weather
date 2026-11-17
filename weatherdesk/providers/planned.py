"""Providers researched but not yet integrated. They appear in Settings → Weather
Providers with the reason, and can't be selected until a tested integration
exists. To integrate one, add a module like tomorrow.py and remove its entry here.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from . import plan
from .base import ProviderInfo

plan(ProviderInfo(
    id="accuweather", name="AccuWeather", needs_key=True,
    website="https://developer.accuweather.com/",
    credit="Weather data by AccuWeather",
    coverage="Worldwide.",
    forecast_days="5 days (Starter/Standard), 10–15 days on higher plans",
    hourly="12 hours (Starter/Standard), 72–120 hours on higher plans",
    limits="Free access ended in 2025: a 14-day trial (500 calls a day), then paid plans from "
           "US$2 a month for 15,000 calls (personal use).",
    status="planned",
    planned_reason="Paid-only after a 14-day trial, and every location first needs a separate "
                   "'location key' lookup, so each update costs several calls. Planned for a later "
                   "version if you'd like it.",
    signup_url="https://developer.accuweather.com/",
    docs_url="https://developer.accuweather.com/documentation/overview",
))

plan(ProviderInfo(
    id="weatherbit", name="Weatherbit", needs_key=True,
    website="https://www.weatherbit.io/",
    credit="Weather data by Weatherbit.io",
    coverage="Worldwide.",
    forecast_days="7 days on the free plan; 16 on paid plans",
    hourly="paid plans only",
    limits="Free plan: 50 requests a day, non-commercial use only (CC BY-NC 4.0); paid plans "
           "from 25,000 a day.",
    status="planned",
    planned_reason="The free plan's 50 requests a day is less than one update every 30 minutes "
                   "needs (current + forecast = 2 requests), and has no hourly data. Planned for a "
                   "later version, mainly useful with a paid key.",
    signup_url="https://www.weatherbit.io/account/create",
    docs_url="https://www.weatherbit.io/api",
))
