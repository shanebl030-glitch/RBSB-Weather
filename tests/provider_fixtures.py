"""Fake responses for each keyed weather provider, in the shape their API
documentation gives, served by the local FakeServer. Nothing touches the internet.

  install(server)            -> registers the routes; server.provider_mode[pid] picks a
                                behaviour ("ok", "http500", "http429", "unknown_codes",
                                "badjson", "no_onecall" for OpenWeather, "bad_shape")
  factories(server)          -> {provider id: callable} for ProviderManager(factories=...)
  KEYS                       -> the valid key for each provider on the fake server

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import math
from zoneinfo import ZoneInfo

AKL = ZoneInfo("Pacific/Auckland")
KEYS = {"openweather": "owm-test-key-0123456789abcdef", "weatherapi": "wapi-test-key-0123456789",
        "visualcrossing": "VCTESTKEY0123456789ABCDEF", "tomorrow": "tio-test-key-0123456789abcd"}
PREFIX = {"openweather": "/owm/data", "weatherapi": "/wapi/v1", "visualcrossing": "/vc/timeline",
          "tomorrow": "/tio/v4"}


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)


def _temp(t: dt.datetime) -> float:
    lt = t.astimezone(AKL)
    return round(15.0 + 5.0 * math.sin((lt.hour - 9) / 24 * 2 * math.pi), 1)


def _sun(day: dt.date):
    rise = dt.datetime.combine(day, dt.time(6, 1), AKL)
    sett = dt.datetime.combine(day, dt.time(20, 9), AKL)
    return rise, sett


def _days(n: int):
    today = _now().astimezone(AKL).date()
    return [today + dt.timedelta(days=i) for i in range(n)]


# --------------------------------------------------------------- OpenWeather
def owm_onecall(lat, lon, unknown=False) -> dict:
    now = _now()
    rise, sett = _sun(now.astimezone(AKL).date())
    cid = 721 if unknown else 804
    hourly = []
    start = now.replace(minute=0)
    for i in range(48):
        t = start + dt.timedelta(hours=i)
        h = {"dt": int(t.timestamp()), "temp": _temp(t), "feels_like": _temp(t) - 1, "pressure": 1014,
             "humidity": 70, "uvi": 2.0, "clouds": 75, "wind_speed": 5.0, "wind_deg": 220, "wind_gust": 9.0,
             "weather": [{"id": [800, 802, 500, 501][i % 4], "main": "x", "description": "x", "icon": "01d"}],
             "pop": 0.35}
        if i % 4 >= 2:
            h["rain"] = {"1h": 0.6}
        hourly.append(h)
    daily = []
    for i, d in enumerate(_days(8)):
        r, s = _sun(d)
        noon = dt.datetime.combine(d, dt.time(12, 0), AKL)
        day = {"dt": int(noon.timestamp()), "sunrise": int(r.timestamp()), "sunset": int(s.timestamp()),
               "temp": {"day": 18, "min": 11.0 + i * 0.1, "max": 20.0 - i * 0.2, "night": 12, "eve": 16, "morn": 13},
               "humidity": 65, "wind_speed": 6.0, "wind_deg": 210, "clouds": 50, "uvi": 9.1 - i * 0.3,
               "pop": 0.4, "weather": [{"id": [501, 800, 211, 601][i % 4]}]}
        if i % 2 == 0:
            day["rain"] = 3.2
        daily.append(day)
    return {"lat": lat, "lon": lon, "timezone": "Pacific/Auckland", "timezone_offset": 46800,
            "current": {"dt": int(now.timestamp()), "sunrise": int(rise.timestamp()),
                        "sunset": int(sett.timestamp()), "temp": 16.2, "feels_like": 15.9, "pressure": 1014,
                        "humidity": 72, "uvi": 3.1, "clouds": 90, "wind_speed": 4.6, "wind_deg": 230,
                        "wind_gust": 8.2, "weather": [{"id": cid, "main": "Clouds", "description": "x"}]},
            "hourly": hourly, "daily": daily}


def owm_weather(lat, lon) -> dict:
    now = _now()
    rise, sett = _sun(now.astimezone(AKL).date())
    return {"coord": {"lat": lat, "lon": lon}, "weather": [{"id": 803, "main": "Clouds"}],
            "main": {"temp": 16.4, "feels_like": 16.0, "pressure": 1013, "humidity": 71},
            "wind": {"speed": 4.1, "deg": 240, "gust": 7.5}, "clouds": {"all": 75},
            "dt": int(now.timestamp()), "sys": {"sunrise": int(rise.timestamp()), "sunset": int(sett.timestamp())},
            "timezone": 46800, "name": "Auckland", "cod": 200}


def owm_forecast(lat, lon) -> dict:
    now = _now()
    first = now.replace(minute=0) + dt.timedelta(hours=3 - now.hour % 3)
    steps = []
    for i in range(40):
        t = first + dt.timedelta(hours=3 * i)
        s = {"dt": int(t.timestamp()), "main": {"temp": _temp(t), "temp_min": _temp(t) - 0.5,
                                               "temp_max": _temp(t) + 0.5, "humidity": 70},
             "weather": [{"id": [800, 801, 500, 802][i % 4]}], "clouds": {"all": 40},
             "wind": {"speed": 5.0, "deg": 200, "gust": 8.0}, "pop": [0, 0.1, 0.62, 0.3][i % 4],
             "dt_txt": t.strftime("%Y-%m-%d %H:%M:%S")}
        if i % 4 == 2:
            s["rain"] = {"3h": 1.5}
        steps.append(s)
    return {"cod": "200", "cnt": 40, "list": steps,
            "city": {"name": "Auckland", "timezone": 46800, "sunrise": 0, "sunset": 0}}


# -------------------------------------------------------------- WeatherAPI.com
def wapi_forecast(lat, lon, days=3, unknown=False) -> dict:
    now = _now()
    fdays = []
    for i, d in enumerate(_days(min(days, 3))):          # the free plan returns 3 days
        hours = []
        for h in range(24):
            t = dt.datetime.combine(d, dt.time(h, 0), AKL)
            hours.append({"time_epoch": int(t.timestamp()), "time": t.strftime("%Y-%m-%d %H:%M"),
                          "temp_c": _temp(t), "condition": {"text": "x", "code": [1000, 1003, 1183, 1189][h % 4]},
                          "chance_of_rain": (h * 5) % 90, "chance_of_snow": 0, "precip_mm": 0.2 if h % 4 >= 2 else 0})
        fdays.append({"date": d.isoformat(), "date_epoch": int(dt.datetime.combine(d, dt.time(), dt.timezone.utc).timestamp()),
                      "day": {"maxtemp_c": 20.1 - i, "mintemp_c": 10.4 + i, "totalprecip_mm": 2.4,
                              "maxwind_kph": 24.5, "daily_chance_of_rain": 70, "daily_chance_of_snow": 0,
                              "uv": 8.0, "condition": {"text": "x", "code": [1189, 1000, 1276][i % 3]}},
                      "astro": {"sunrise": "06:01 AM", "sunset": "08:09 PM" if i else "No sunset"},
                      "hour": hours})
    return {"location": {"name": "Auckland", "tz_id": "Pacific/Auckland",
                         "localtime_epoch": int(now.timestamp())},
            "current": {"last_updated_epoch": int(now.timestamp()) - 600, "temp_c": 16.0, "is_day": 1,
                        "condition": {"text": "Haze" if unknown else "Overcast", "code": 1999 if unknown else 1009},
                        "wind_kph": 15.1, "wind_degree": 230, "pressure_mb": 1015.0, "precip_mm": 0.0,
                        "humidity": 77, "cloud": 100, "feelslike_c": 15.2, "uv": 3.0, "gust_kph": 22.0},
            "forecast": {"forecastday": fdays}}


# ------------------------------------------------------------- Visual Crossing
def vc_timeline(lat, lon) -> dict:
    now = _now()
    days = []
    for i, d in enumerate(_days(15)):
        r, s = _sun(d)
        hours = []
        for h in range(24):
            t = dt.datetime.combine(d, dt.time(h, 0), AKL)
            hours.append({"datetime": f"{h:02d}:00:00", "datetimeEpoch": int(t.timestamp()), "temp": _temp(t),
                          "precip": 0.3 if h % 3 == 0 else 0.0, "precipprob": 40.0, "snow": 0.0,
                          "windspeed": 14.0, "winddir": 220.0, "cloudcover": 60.0, "uvindex": 3,
                          "icon": ["clear-day", "partly-cloudy-day", "rain", "showers-day"][h % 4],
                          "conditions": "x"})
        days.append({"datetime": d.isoformat(), "datetimeEpoch": int(dt.datetime.combine(d, dt.time(), AKL).timestamp()),
                     "tempmax": 21.0 - i * 0.1, "tempmin": 11.0, "precip": 4.2, "precipprob": 80.0, "snow": 0.0,
                     "windspeed": 25.2, "winddir": 210.0, "pressure": 1012.0, "cloudcover": 55.0, "uvindex": 9,
                     "sunrise": "06:01:22", "sunriseEpoch": int(r.timestamp()), "sunset": "20:09:40",
                     "sunsetEpoch": int(s.timestamp()), "icon": ["rain", "clear-day", "thunder-rain"][i % 3],
                     "conditions": "x", "hours": hours})
    r, s = _sun(now.astimezone(AKL).date())
    return {"queryCost": 1, "latitude": lat, "longitude": lon, "resolvedAddress": f"{lat},{lon}",
            "timezone": "Pacific/Auckland", "tzoffset": 13.0, "days": days,
            "currentConditions": {"datetime": now.astimezone(AKL).strftime("%H:%M:%S"),
                                  "datetimeEpoch": int(now.timestamp()) - 1800, "temp": 16.8, "feelslike": 16.8,
                                  "humidity": 74.0, "precip": 0.0, "precipprob": 0.0, "snow": 0.0,
                                  "windgust": 25.9, "windspeed": 14.8, "winddir": 225.0, "pressure": 1015.0,
                                  "cloudcover": 88.0, "uvindex": 2, "conditions": "Partially cloudy",
                                  "icon": "partly-cloudy-day", "sunrise": "06:01:22",
                                  "sunriseEpoch": int(r.timestamp()), "sunset": "20:09:40",
                                  "sunsetEpoch": int(s.timestamp())}}


# ------------------------------------------------------------------ Tomorrow.io
def tio_forecast(lat, lon) -> dict:
    now = _now()
    start = now.replace(minute=0)
    hourly = []
    for i in range(120):
        t = start + dt.timedelta(hours=i)
        hourly.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "values": {
            "temperature": _temp(t), "temperatureApparent": _temp(t) - 0.8, "humidity": 69,
            "windSpeed": 4.5, "windDirection": 215, "windGust": 8.8, "pressureSeaLevel": 1016.2,
            "pressureSurfaceLevel": 1013.0, "precipitationProbability": [0, 5, 45, 80][i % 4],
            "rainIntensity": 0.8 if i % 4 == 3 else 0, "snowIntensity": 0, "cloudCover": 64,
            "uvIndex": 3, "weatherCode": [1000, 1101, 4200, 4001][i % 4]}})
    daily = []
    for i, d in enumerate(_days(6)):
        r, s = _sun(d)
        t = dt.datetime.combine(d, dt.time(6, 0), AKL).astimezone(dt.timezone.utc)
        daily.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "values": {
            "temperatureMax": 21.5 - i * 0.3, "temperatureMin": 10.5, "precipitationProbabilityMax": 75,
            "rainAccumulationSum": 3.9, "snowAccumulationSum": 0, "windSpeedMax": 9.0,
            "windDirectionAvg": 220, "uvIndexMax": 9, "humidityAvg": 70,
            "sunriseTime": r.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sunsetTime": s.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "weatherCodeMax": [4001, 1000, 8000, 5100, 1101, 10000][i]}})
    return {"timelines": {"minutely": [], "hourly": hourly, "daily": daily},
            "location": {"lat": lat, "lon": lon}}


# ----------------------------------------------------------------- serving
def _j(code, obj, hdrs=None):
    return code, json.dumps(obj).encode(), hdrs or {}


def install(server) -> None:
    server.provider_mode = {pid: "ok" for pid in KEYS}
    server.provider_calls = {pid: 0 for pid in KEYS}

    def common(pid, key_ok, err401, err429):
        server.provider_calls[pid] += 1
        mode = server.provider_mode[pid]
        if mode == "http500":
            return 500, b"Internal Server Error", {}
        if not key_ok:
            return err401
        if mode == "http429":
            return err429
        if mode == "badjson":
            return 200, b"{nope", {}
        if mode == "bad_shape":
            return _j(200, {"unexpected": True})
        return None

    def owm(path, q, h):
        bad = (401, json.dumps({"cod": 401, "message": "Invalid API key. Please see "
                                "https://openweathermap.org/faq#error401 for more info."}).encode(), {})
        r = common("openweather", q.get("appid") == KEYS["openweather"], bad,
                   _j(429, {"cod": 429, "message": "Your account is temporary blocked due to exceeding of "
                                                    "requests limitation of your subscription type."}))
        if r:
            return r
        lat, lon = float(q["lat"]), float(q["lon"])
        if path.endswith("/3.0/onecall"):
            if server.provider_mode["openweather"] == "no_onecall":
                return _j(401, {"cod": 401, "message": "Please note that using One Call 3.0 requires a "
                                "separate subscription to the One Call by Call plan."})
            return _j(200, owm_onecall(lat, lon, server.provider_mode["openweather"] == "unknown_codes"))
        if path.endswith("/2.5/weather"):
            return _j(200, owm_weather(lat, lon))
        if path.endswith("/2.5/forecast"):
            return _j(200, owm_forecast(lat, lon))
        return _j(404, {"cod": 404, "message": "not found"})

    def wapi(path, q, h):
        r = common("weatherapi", q.get("key") == KEYS["weatherapi"],
                   _j(401, {"error": {"code": 2006, "message": "API key is invalid."}}),
                   _j(403, {"error": {"code": 2007, "message": "API key has exceeded calls per month quota."}}))
        if r:
            return r
        lat, lon = (float(x) for x in q["q"].split(","))
        return _j(200, wapi_forecast(lat, lon, int(q.get("days", 3)),
                                     server.provider_mode["weatherapi"] == "unknown_codes"))

    def vc(path, q, h):
        key = q.get("key", "")
        r = common("visualcrossing", key == KEYS["visualcrossing"],
                   (401, f"No account found with API key '{key}'".encode(), {}),
                   (429, b"Maximum daily cost exceeded", {}))
        if r:
            return r
        lat, lon = (float(x) for x in path.rsplit("/", 1)[1].split(","))
        return _j(200, vc_timeline(lat, lon))

    def tio(path, q, h):
        limits = {"X-RateLimit-Limit-Day": "500", "X-RateLimit-Remaining-Day": "487",
                  "X-RateLimit-Limit-Hour": "25", "X-RateLimit-Remaining-Hour": "24"}
        r = common("tomorrow", q.get("apikey") == KEYS["tomorrow"],
                   _j(401, {"code": 401001, "type": "Invalid Key",
                            "message": "The method requires authentication but it was not presented or is invalid."}),
                   _j(429, {"code": 429001, "type": "Too Many Calls",
                            "message": "The request limit for this resource has been reached for the current "
                                       "rate limit window."}, dict(limits, **{"X-RateLimit-Remaining-Hour": "0"})))
        if r:
            return r
        lat, lon = (float(x) for x in q["location"].split(","))
        return _j(200, tio_forecast(lat, lon), limits)

    server.routes.update({PREFIX["openweather"]: owm, PREFIX["weatherapi"]: wapi,
                          PREFIX["visualcrossing"]: vc, PREFIX["tomorrow"]: tio})


def base_url(server, pid: str) -> str:
    return f"http://127.0.0.1:{server.port}{PREFIX[pid]}"


def factories(server, timeout: float = 3.0) -> dict:
    """Providers pointed at the fake server (Open-Meteo and MET Norway too)."""
    from weatherdesk.api import OpenMeteoClient
    from weatherdesk.metno import MetNoClient
    from weatherdesk.providers import REGISTRY
    from weatherdesk.providers.metno import MetNoProvider
    from weatherdesk.providers.openmeteo import OpenMeteoProvider
    out = {
        "open-meteo": lambda: OpenMeteoProvider(client=OpenMeteoClient(server.forecast_url, server.geocode_url,
                                                                       timeout=timeout)),
        "met.no": lambda: MetNoProvider(client=MetNoClient(server.metno_url, timeout=timeout)),
    }
    for pid in KEYS:
        out[pid] = (lambda pid=pid: REGISTRY[pid](base_url=base_url(server, pid), timeout=timeout))
    return out
