"""Earthquake fixtures (2.5): USGS summary GeoJSON and GeoNet /quake GeoJSON (version 2),
written to their documented formats (not captured from the live services). Times are
relative to now. Created By Shane BlackbuRn"""

from __future__ import annotations

import datetime as dt
import json
import time


def usgs(now: float = None) -> dict:
    now = time.time() if now is None else now
    ms = lambda ago_s: int((now - ago_s) * 1000)          # noqa: E731
    feats = [
        # Seddon, Marlborough: reported by GeoNet too (the USGS copy is dropped)
        ("us7000a1", 5.4, 174.08, -41.72, 12.0, "25 km SE of Blenheim, New Zealand", 600, 0, ""),
        ("us7000a2", 7.3, 142.9, 38.2, 30.0, "90 km E of Ishinomaki, Japan", 1500, 1, "yellow"),
        ("ak0251", 2.9, -150.1, 61.3, 40.0, "20 km N of Anchorage, Alaska", 4 * 3600, 0, ""),
        ("ci4012", 3.1, -117.5, 34.0, 8.0, "5 km W of Ontario, CA", 20 * 3600, 0, ""),
        ("us7000old", 4.8, 120.0, -8.0, 50.0, "Bali Sea", 3 * 86400, 0, ""),
    ]
    features = [{"type": "Feature", "id": fid,
                 "properties": {"mag": mag, "place": place, "time": ms(ago), "updated": ms(ago - 60),
                                "url": f"https://earthquake.usgs.gov/earthquakes/eventpage/{fid}",
                                "felt": None, "cdi": None, "mmi": None, "alert": alert or None,
                                "status": "reviewed", "tsunami": tsu, "sig": 100, "net": "us", "code": fid,
                                "type": "earthquake", "title": f"M {mag} - {place}"},
                 "geometry": {"type": "Point", "coordinates": [lon, lat, depth]}}
                for fid, mag, lon, lat, depth, place, ago, tsu, alert in feats]
    features.append({"type": "Feature", "id": "blast1",
                     "properties": {"mag": 2.6, "time": ms(100), "type": "quarry blast", "place": "quarry"},
                     "geometry": {"type": "Point", "coordinates": [-118, 35, 0]}})
    features.append({"type": "Feature", "id": "bad", "properties": {"mag": None, "time": None},
                     "geometry": {"type": "Point", "coordinates": [0, 0]}})
    return {"type": "FeatureCollection", "metadata": {"title": "USGS Magnitude 2.5+ Earthquakes, Past Day"},
            "features": features}


def geonet(now: float = None) -> dict:
    now = time.time() if now is None else now
    iso = lambda ago_s: dt.datetime.fromtimestamp(now - ago_s, dt.timezone.utc).strftime(  # noqa: E731
        "%Y-%m-%dT%H:%M:%S.%fZ")
    rows = [
        ("2026p881001", 5.3, 174.05, -41.70, 11.0, "20 km south-east of Seddon", 5, 620, "best"),
        ("2026p880950", 3.4, 176.25, -38.70, 5.0, "15 km north of Taupō", 3, 3 * 3600, "preliminary"),
        ("2026p870000", 4.1, 178.3, -37.6, 25.0, "30 km east of Te Araroa", 3, 2 * 86400, "best"),
        ("2026p880999", 3.0, 172.6, -43.5, 8.0, "deleted one", 3, 1000, "deleted"),
    ]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
         "properties": {"publicID": pid, "time": iso(ago), "depth": depth, "magnitude": mag, "mmi": mmi,
                        "locality": loc, "quality": q}}
        for pid, mag, lon, lat, depth, loc, mmi, ago, q in rows]}


def install(server):
    """Routes /usgs/<feed> and /geonet. server.quake_mode[source] = ok | http500 | garbage | empty."""
    server.quake_mode = {"usgs": "ok", "geonet": "ok"}
    server.quake_hits = {"usgs": [], "geonet": []}

    def usgs_h(path, q, headers):
        server.quake_hits["usgs"].append(path)
        m = server.quake_mode["usgs"]
        if m == "http500":
            return 500, b"error", {}
        if m == "garbage":
            return 200, b"<html>nope", {}
        data = usgs() if m == "ok" else {"type": "FeatureCollection", "features": []}
        return 200, json.dumps(data).encode(), {"Content-Type": "application/geo+json"}

    def geonet_h(path, q, headers):
        server.quake_hits["geonet"].append(headers.get("Accept", ""))
        m = server.quake_mode["geonet"]
        if m == "http500":
            return 500, b"error", {}
        if m == "garbage":
            return 200, b"{{{", {}
        data = geonet() if m == "ok" else {"type": "FeatureCollection", "features": []}
        return 200, json.dumps(data).encode(), {"Content-Type": "application/vnd.geo+json"}

    server.routes["/usgs/"] = usgs_h
    server.routes["/geonet"] = geonet_h
    base = f"http://127.0.0.1:{server.port}"
    return base + "/usgs/{feed}", base + "/geonet"
