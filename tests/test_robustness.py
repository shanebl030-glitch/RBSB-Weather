"""Audit (1.15.0): robustness of every provider's conversion against damaged data.

Real services occasionally send partial, null, mistyped or extreme values. For
every provider this mutates a realistic response thousands of ways (deleting
keys, nulls, wrong types, NaN/inf, huge and negative numbers, empty lists) and
checks the only outcomes are:
  * a valid, normalised forecast the whole app can draw, or
  * a WeatherError with a plain-English message (the manager then falls back).
Anything else (an unexpected exception type) would stop the fallback chain and
is a bug.

These are local, simulated responses - they prove the code's defences, not
compatibility with the live services (see TEST_REPORT.md).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import copy
import math
import random
import unittest

import provider_fixtures as PF
from fake_server import make_forecast, make_metno
from helpers import PLACES

from rbsb_weather.api import WeatherError, parse_forecast
from rbsb_weather.metno import parse_metno
from rbsb_weather.models import Location
from rbsb_weather.providers.base import Provider, ProviderInfo
from rbsb_weather.providers.openweather import parse_free, parse_onecall
from rbsb_weather.providers.tomorrow import parse_tomorrow
from rbsb_weather.providers.visualcrossing import parse_visualcrossing
from rbsb_weather.providers.weatherapi import parse_weatherapi
from rbsb_weather.providers.wunderground import parse_wunderground

REPORT: list[str] = []
LOC = Location.from_dict(PLACES[0])
LAT, LON = LOC.latitude, LOC.longitude
WEIRD = [None, "", "abc", float("nan"), float("inf"), -float("inf"), 1e308, -1e308, -1, 0, True,
         [], {}, [None], {"x": 1}, 10 ** 30, "12.5", -999.0]


def _paths(obj, prefix=()):
    """Every (path) to a value in a JSON-like structure (lists sampled)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(prefix + (k,))
            out += _paths(v, prefix + (k,))
    elif isinstance(obj, list):
        for i in sorted({0, 1, len(obj) // 2, len(obj) - 1} & set(range(len(obj)))):
            out.append(prefix + (i,))
            out += _paths(obj[i], prefix + (i,))
    return out


def _set(obj, path, value, delete=False):
    for p in path[:-1]:
        obj = obj[p]
    if delete:
        if isinstance(obj, dict):
            obj.pop(path[-1], None)
        else:
            del obj[path[-1]]
    else:
        obj[path[-1]] = value


class _Harness(Provider):
    """Runs a parser through the same wrapper and normaliser as a real provider."""
    info = ProviderInfo(id="harness", name="Harness", needs_key=False, website="", credit="",
                        coverage="", forecast_days="", hourly="", limits="")

    def __init__(self, parse):
        super().__init__(base_url="http://127.0.0.1:9")
        self._parse = parse

    def _fetch(self, location, days):
        return self._parse()


def check_forecast(tc, fc):
    """What the app relies on after normalise()."""
    c = fc.current
    tc.assertTrue(isinstance(c.temperature, float) and math.isfinite(c.temperature))
    tc.assertIsInstance(c.is_day, bool)
    for v in (c.humidity, c.cloud_cover):
        tc.assertTrue(v is None or 0 <= v <= 100, v)
    tc.assertTrue(c.wind_direction is None or 0 <= c.wind_direction < 360)
    for v in (c.apparent_temperature, c.wind_speed, c.wind_gusts, c.pressure, c.precipitation):
        tc.assertTrue(v is None or (isinstance(v, float) and math.isfinite(v)), v)
    tc.assertTrue(c.weather_code is None or isinstance(c.weather_code, int))
    for h in fc.hourly:
        tc.assertIsInstance(h.time, str)
        tc.assertTrue(h.temperature is None or math.isfinite(h.temperature))
        tc.assertTrue(h.precipitation_probability is None or 0 <= h.precipitation_probability <= 100)
        tc.assertTrue(h.weather_code is None or isinstance(h.weather_code, int))
    for d in fc.daily:
        tc.assertIsInstance(d.date, str)
        if d.temp_max is not None and d.temp_min is not None:
            tc.assertLessEqual(d.temp_min, d.temp_max)
        tc.assertTrue(d.precipitation_probability_max is None or 0 <= d.precipitation_probability_max <= 100)
        tc.assertTrue(d.weather_code is None or isinstance(d.weather_code, int))


class TestDamagedResponses(unittest.TestCase):
    CASES = {
        "Open-Meteo": (lambda: make_forecast(LAT, LON), lambda d: parse_forecast(d, LOC)),
        "MET Norway": (lambda: make_metno(LAT, LON), lambda d: parse_metno(d, LOC)),
        "OpenWeather One Call": (lambda: PF.owm_onecall(LAT, LON), lambda d: parse_onecall(d, LOC)),
        "OpenWeather free": (lambda: {"cur": PF.owm_weather(LAT, LON), "fc": PF.owm_forecast(LAT, LON)},
                             lambda d: parse_free(d["cur"], d["fc"], LOC)),
        "WeatherAPI.com": (lambda: PF.wapi_forecast(LAT, LON), lambda d: parse_weatherapi(d, LOC)),
        "Visual Crossing": (lambda: PF.vc_timeline(LAT, LON), lambda d: parse_visualcrossing(d, LOC)),
        "Tomorrow.io": (lambda: PF.tio_forecast(LAT, LON), lambda d: parse_tomorrow(d, LOC)),
        "Weather Underground": (lambda: {"fc": PF.wu_5day(LAT, LON), "ob": PF.wu_obs("IWAIUK12")["observations"][0]},
                                lambda d: parse_wunderground(d["fc"], d["ob"], LOC)),
    }

    def run_case(self, name, make, parse, n=300, seed=1):
        rng = random.Random(seed)
        base = make()
        paths = _paths(base)
        ok = err = 0
        for i in range(n):
            data = copy.deepcopy(base)
            for _ in range(rng.choice((1, 1, 2, 3))):
                p = rng.choice(paths)
                try:
                    if rng.random() < 0.3:
                        _set(data, p, None, delete=True)
                    else:
                        _set(data, p, rng.choice(WEIRD))
                except (KeyError, IndexError, TypeError):
                    pass                         # an earlier mutation removed the parent
            h = _Harness(lambda: parse(data))
            try:
                fc = h.fetch_forecast(LOC, 7)
            except WeatherError as e:
                self.assertTrue(str(e), name)    # a message for the user
                err += 1
                continue
            except Exception as e:               # anything else would break the fallback chain
                self.fail(f"{name}: mutation {i} raised {type(e).__name__}: {e}")
            check_forecast(self, fc)
            ok += 1
        REPORT.append(f"{name}: {n} damaged responses -> {ok} usable forecasts, {err} clean errors, 0 crashes")

    def test_every_provider_survives_damaged_data(self):
        for name, (make, parse) in self.CASES.items():
            with self.subTest(provider=name):
                self.run_case(name, make, parse)

    def test_undamaged_fixtures_still_parse(self):
        for name, (make, parse) in self.CASES.items():
            with self.subTest(provider=name):
                check_forecast(self, _Harness(lambda: parse(make())).fetch_forecast(LOC, 7))

    def test_not_json_shapes(self):
        for name, (_make, parse) in self.CASES.items():
            for junk in (None, [], "", 42, {"unexpected": True}):
                with self.subTest(provider=name, junk=repr(junk)):
                    data = junk if name not in ("OpenWeather free", "Weather Underground") else \
                        {"cur": junk, "fc": junk, "ob": junk if isinstance(junk, dict) else {}}
                    with self.assertRaises(WeatherError):
                        _Harness(lambda: parse(data)).fetch_forecast(LOC, 7)


def tearDownModule():
    print("\n--- robustness results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
