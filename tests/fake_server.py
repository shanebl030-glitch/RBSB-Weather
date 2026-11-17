"""A local stand-in for the Open-Meteo forecast and geocoding APIs.

Lets the whole test suite run deterministically with no internet access.
Behaviour is switched per test via FakeServer.mode:
  "ok" | "http500" | "badjson" | "slow" | "empty" | "error_body" | "missing_current"
"""

from __future__ import annotations

import collections
import json
import math
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLACES = [
    {"name": "Auckland", "latitude": -36.84853, "longitude": 174.76349, "country": "New Zealand",
     "admin1": "Auckland", "timezone": "Pacific/Auckland"},
    {"name": "Hamilton", "latitude": -37.78333, "longitude": 175.28333, "country": "New Zealand",
     "admin1": "Waikato", "timezone": "Pacific/Auckland"},
    {"name": "Hamilton", "latitude": 43.25011, "longitude": -79.84963, "country": "Canada",
     "admin1": "Ontario", "timezone": "America/Toronto"},
    {"name": "Wellington", "latitude": -41.28664, "longitude": 174.77557, "country": "New Zealand",
     "admin1": "Wellington", "timezone": "Pacific/Auckland"},
]


def make_forecast(lat: float, lon: float, days: int = 7) -> dict:
    base_t = 18.0 - abs(lat) / 10.0
    hours = [f"2026-11-{15 + h // 24:02d}T{h % 24:02d}:00" for h in range(days * 24)]
    temps = [round(base_t + 5 * ((h % 24) - 6) / 12.0 if 6 <= h % 24 <= 18 else base_t - 2, 1)
             for h in range(days * 24)]
    codes = [0, 1, 2, 3, 61, 80, 95]
    return {
        "latitude": lat, "longitude": lon, "timezone": "Pacific/Auckland",
        "current": {
            "time": "2026-11-15T10:15", "temperature_2m": round(base_t + 2.3, 1),
            "relative_humidity_2m": 68, "apparent_temperature": round(base_t + 1.1, 1),
            "is_day": 1, "precipitation": 0.2, "weather_code": 2, "cloud_cover": 45,
            "pressure_msl": 1016.4, "wind_speed_10m": 18.7, "wind_direction_10m": 225,
            "wind_gusts_10m": 34.2,
        },
        "hourly": {
            "time": hours, "temperature_2m": temps,
            "precipitation_probability": [(h * 7) % 80 if h % 5 else 0 for h in range(days * 24)],
            "precipitation": [0.1 * (h % 3) for h in range(days * 24)],
            "weather_code": [codes[h % len(codes)] for h in range(days * 24)],
        },
        "daily": {
            "time": [f"2026-11-{15 + d:02d}" for d in range(days)],
            "weather_code": [codes[d % len(codes)] for d in range(days)],
            "temperature_2m_max": [round(base_t + 5 - d * 0.5, 1) for d in range(days)],
            "temperature_2m_min": [round(base_t - 4 + d * 0.3, 1) for d in range(days)],
            "precipitation_sum": [round(d * 1.7, 1) for d in range(days)],
            "precipitation_probability_max": [d * 13 for d in range(days)],
            "wind_speed_10m_max": [20 + d * 3 for d in range(days)],
            "sunrise": [f"2026-11-{15 + d:02d}T06:0{d}" for d in range(days)],
            "sunset": [f"2026-11-{15 + d:02d}T20:1{d}" for d in range(days)],
            "uv_index_max": [8.5 - d * 0.4 for d in range(days)],
        },
    }


METNO_PATH = "/weatherapi/locationforecast/2.0/complete"
METNO_SYMBOLS = ["clearsky_day", "fair_night", "partlycloudy_day", "cloudy", "lightrainshowers_day",
                 "rain", "heavyrainandthunder", "fog"]


def make_metno(lat: float, lon: float, start=None, hourly_steps: int = 60, days: int = 9) -> dict:
    """A MET Norway locationforecast/2.0/complete response with the real shape: hourly
    steps (instant + next_1/6/12_hours) for `hourly_steps` hours, then 6-hourly steps."""
    import datetime as dt
    start = (start or dt.datetime.now(dt.timezone.utc)).replace(minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=days)
    times, t = [], start
    while t < end:
        times.append(t)
        t += dt.timedelta(hours=1 if len(times) < hourly_steps else 6)
    series = []
    for i, t in enumerate(times):
        base = 14.0 + 4.0 * math.sin((t.hour - 3) / 24 * 2 * math.pi)
        sym = METNO_SYMBOLS[i % len(METNO_SYMBOLS)]
        data = {"instant": {"details": {
            "air_pressure_at_sea_level": 1012.3, "air_temperature": round(base, 1),
            "cloud_area_fraction": 80.5, "relative_humidity": 75.0, "wind_from_direction": 225.0,
            "wind_speed": 5.0, "wind_speed_of_gust": 10.0, "ultraviolet_index_clear_sky": 4.0 + (i % 3)}},
            "next_6_hours": {"summary": {"symbol_code": sym},
                             "details": {"air_temperature_max": round(base + 2, 1),
                                         "air_temperature_min": round(base - 2, 1),
                                         "precipitation_amount": 1.2, "probability_of_precipitation": 40.0}},
            "next_12_hours": {"summary": {"symbol_code": sym}, "details": {"probability_of_precipitation": 50.0}}}
        if i < hourly_steps:
            data["next_1_hours"] = {"summary": {"symbol_code": sym},
                                    "details": {"precipitation_amount": 0.2, "probability_of_precipitation": 20.0}}
        series.append({"time": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "data": data})
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat, 10]},
            "properties": {"meta": {"updated_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "units": {"air_temperature": "celsius", "wind_speed": "m/s"}},
                           "timeseries": series}}


class FakeServer:
    def __init__(self):
        self.mode = "ok"
        self.metno_mode = "ok"            # ok | http500 | http429 | badjson
        self.metno_agents: collections.deque = collections.deque(maxlen=20)
        self.delay = 0.0
        # live cloud map (/images/.../clouds.jpg): body, Last-Modified, and a mode:
        # ok | http404 | garbage | huge | slow
        self.cloud_body = b""
        self.cloud_last_modified = "Sun, 15 Nov 2026 00:00:00 GMT"
        self.cloud_mode = "ok"
        self.cloud_headers: collections.deque = collections.deque(maxlen=20)
        # bounded log of recent requests + exact per-path counters (no unbounded growth)
        self.requests: collections.deque = collections.deque(maxlen=50)
        self._counts: collections.Counter = collections.Counter()
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep test output clean
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                with outer._lock:
                    outer.requests.append((u.path, q))
                    outer._counts[u.path] += 1
                    mode, delay = outer.mode, outer.delay
                if u.path.endswith("/clouds.jpg"):
                    return self._clouds()
                if u.path == METNO_PATH:
                    return self._metno(q)
                if mode == "slow" or delay:
                    time.sleep(delay or 5)
                if mode == "http500":
                    return self._send(500, {"error": True, "reason": "Internal test failure"})
                if mode == "error_body":
                    return self._send(400, {"error": True, "reason": "Latitude must be in range"})
                if mode == "badjson":
                    return self._raw(200, b"{not json")
                if u.path == "/v1/search":
                    name = q.get("name", "").lower()
                    res = [p for p in PLACES if p["name"].lower().startswith(name)]
                    return self._send(200, {"results": res} if res and mode != "empty" else {})
                if u.path == "/v1/forecast":
                    data = make_forecast(float(q["latitude"]), float(q["longitude"]),
                                         int(q.get("forecast_days", 7)))
                    if q.get("timezone") and q["timezone"] != "auto":
                        data["timezone"] = q["timezone"]       # like the real API
                    if mode == "missing_current":
                        data.pop("current")
                    return self._send(200, data)
                return self._send(404, {"error": True, "reason": "not found"})

            def _metno(self, q):
                outer.metno_agents.append(self.headers.get("User-Agent", ""))
                m = outer.metno_mode
                if m == "http500":
                    return self._raw(500, b"Internal Server Error")
                if m == "http429":
                    return self._raw(429, b"Too Many Requests")
                if m == "badjson":
                    return self._raw(200, b"{not json")
                return self._send(200, make_metno(float(q["lat"]), float(q["lon"])))

            def _clouds(self):
                outer.cloud_headers.append(dict(self.headers))
                cm = outer.cloud_mode
                if cm == "slow":
                    time.sleep(5)
                if cm == "http404":
                    return self._raw(404, b"not found")
                if cm == "garbage":
                    return self._raw(200, b"<html>not an image</html>")
                lm = outer.cloud_last_modified
                if self.headers.get("If-Modified-Since") == lm:
                    self.send_response(304)
                    self.send_header("Last-Modified", lm)
                    self.end_headers()
                    return
                body = outer.cloud_body
                size = len(body) if cm != "huge" else 9 * 1024 * 1024
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(size))
                    self.send_header("Last-Modified", lm)
                    self.end_headers()
                    if cm == "huge":
                        chunk = b"\0" * 65536
                        for _ in range(size // 65536):
                            self.wfile.write(chunk)
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _send(self, code, obj):
                self._raw(code, json.dumps(obj).encode())

            def _raw(self, code, body):
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def forecast_url(self):
        return f"http://127.0.0.1:{self.port}/v1/forecast"

    @property
    def metno_url(self):
        return f"http://127.0.0.1:{self.port}{METNO_PATH}"

    @property
    def cloud_url(self):
        return f"http://127.0.0.1:{self.port}/images/2048x1024/clouds.jpg"

    @property
    def geocode_url(self):
        return f"http://127.0.0.1:{self.port}/v1/search"

    def count(self, path: str) -> int:
        with self._lock:
            return self._counts[path]

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
