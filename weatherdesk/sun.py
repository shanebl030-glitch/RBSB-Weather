"""Sun and comfort calculations shared by every weather provider.

Weather services differ in what they supply. Anything WeatherDesk can work out
itself - sunrise and sunset, whether it's day or night, the "feels like"
temperature - is calculated here when a provider leaves it out.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Optional

SUN_ALT = -0.833          # sunrise/sunset: upper limb on the horizon, with refraction


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


def is_daytime(t: dt.datetime, lat: float, lon: float) -> bool:
    return _sun_elevation(t.astimezone(dt.timezone.utc), lat, lon) > SUN_ALT


def apparent_temperature(temp: Optional[float], rh: Optional[float],
                         wind_ms: Optional[float]) -> Optional[float]:
    """Australian (Steadman) apparent temperature, as used by Open-Meteo."""
    if temp is None or rh is None or wind_ms is None:
        return None
    e = rh / 100.0 * 6.105 * math.exp(17.27 * temp / (237.7 + temp))
    return round(temp + 0.33 * e - 0.70 * wind_ms - 4.0, 1)
