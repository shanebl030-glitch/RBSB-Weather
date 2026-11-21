"""Weather warning fixtures (2.4) served by the fake server.

The files in tests/data/alerts are written to each service's documented format
(MetService CAP 1.2 with its ColourCode parameter, MeteoAlarm's Atom feed with
inline CAP fields, api.weather.gov GeoJSON, MET Norway MetAlerts GeoJSON). They
were not captured from the live services, which can't be reached from the
build machine. Times are filled in relative to now.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "alerts"
PREFIX = {"metservice": "/alerts-metservice", "nws": "/alerts-nws", "metno": "/alerts-metno",
          "meteoalarm": "/alerts-meteoalarm"}


def fill(name: str, base: str, onset_h: float = -1, expires_h: float = 30) -> bytes:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    text = (DATA / name).read_text(encoding="utf-8")
    text = text.replace("{BASE}", base + PREFIX["metservice"])
    text = text.replace("{ONSET}", (now + dt.timedelta(hours=onset_h)).isoformat())
    text = text.replace("{EXPIRES}", (now + dt.timedelta(hours=expires_h)).isoformat())
    return text.encode()


def install(server, base: str):
    """Register the warning routes. server.alert_mode[source] = ok | none | http500 | garbage;
    server.alert_hits counts requests per path."""
    server.alert_mode = {k: "ok" for k in PREFIX}
    server.alert_hits = {}
    server.alert_agents = []
    server.alert_expires_h = 30

    def handler(source):
        def h(path, q, headers):
            server.alert_hits[path] = server.alert_hits.get(path, 0) + 1
            server.alert_agents.append(headers.get("User-Agent", ""))
            mode = server.alert_mode[source]
            if mode == "http500":
                return 500, b"error", {}
            if mode == "garbage":
                return 200, b"<<<not xml or json", {}
            exp = server.alert_expires_h
            if source == "metservice":
                if path.endswith("/cap/rss"):
                    if mode == "none":
                        return 200, fill("metservice_rss.xml", base).split(b"<item>")[0] + b"</channel></rss>", {}
                    return 200, fill("metservice_rss.xml", base), {"Content-Type": "application/rss+xml"}
                name = {"rain-auckland.xml": "cap_rain_auckland.xml", "wind-wellington.xml": "cap_wind_wellington.xml",
                        "test.xml": "cap_test.xml"}.get(path.rsplit("/", 1)[-1])
                if name:
                    return 200, fill(name, base, expires_h=exp), {"Content-Type": "application/cap+xml"}
                return 404, b"not found", {}
            if source == "meteoalarm":
                if not path.endswith("/united-kingdom"):
                    return 404, b"not found", {}
                if mode == "none":
                    return 200, b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>', {}
                return 200, fill("meteoalarm_uk.xml", base, expires_h=exp), {}
            if source == "nws":
                if mode == "none":
                    return 200, b'{"type": "FeatureCollection", "features": []}', {}
                return 200, fill("nws_point.json", base, expires_h=exp), {"Content-Type": "application/geo+json"}
            if source == "metno":
                if mode == "none":
                    return 200, b'{"type": "FeatureCollection", "features": []}', {}
                return 200, fill("metno_current.json", base, expires_h=exp), {}
            return 404, b"", {}
        return h

    for src, pre in PREFIX.items():
        server.routes[pre] = handler(src)
    return {"metservice": base + PREFIX["metservice"] + "/cap/rss",
            "nws": base + PREFIX["nws"],
            "metno": base + PREFIX["metno"],
            "meteoalarm": base + PREFIX["meteoalarm"] + "/{slug}"}


def use_server(base: str):
    """Point the app's warning sources (environment) at the fake server."""
    import os
    urls = {"metservice": base + PREFIX["metservice"] + "/cap/rss", "nws": base + PREFIX["nws"],
            "metno": base + PREFIX["metno"], "meteoalarm": base + PREFIX["meteoalarm"] + "/{slug}"}
    for k, v in urls.items():
        os.environ[f"RBSB_WEATHER_ALERTS_{k.upper()}"] = v
    return urls
