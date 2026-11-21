"""Earthquakes (2.5): recent quakes on the Earth tabs, and a notification when one is
near a saved place (or a major one anywhere).

* Worldwide: the USGS earthquake feeds (public domain), magnitude 2.5 or 4.5 and up,
  for the past day or week, updated every minute at the source.
* New Zealand: GeoNet (CC BY 3.0 NZ), quakes likely to have been felt (MMI 3+).
  GeoNet is preferred for NZ quakes: when both report the same quake, GeoNet's is kept.

Nothing about the user is sent: the same feeds are downloaded whoever asks, and the
distances to saved places are worked out on this computer.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Iterable, Optional

from . import __version__
from .net import build_opener

log = logging.getLogger(__name__)

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson"
GEONET_URL = "https://api.geonet.org.nz/quake?MMI=3"
GEONET_ACCEPT = "application/vnd.geo+json;version=2"
TIMEOUT_S = 20.0
MAX_BYTES = 6 * 1024 * 1024
CREDIT = "Earthquakes: USGS (public domain) and GeoNet (CC BY 3.0 NZ)"
SOURCE_PAGES = {"GeoNet": "https://www.geonet.org.nz/earthquake/{id}",
                "USGS": ""}                                    # USGS gives each quake's page itself

PERIODS = {"day": 86400, "week": 7 * 86400}
MIN_MAGS = (2.5, 4.5)
INTERVALS = (5, 10, 30)
PULSE_S = 3600                    # quakes in the last hour pulse
NOTIFY_WITHIN_S = 2 * 3600        # only recent quakes notify (not old ones seen on first start)


class QuakeError(Exception):
    """A quake feed couldn't be read. Message is user-friendly."""


@dataclass
class Quake:
    id: str
    source: str                   # "USGS" | "GeoNet"
    time: float                   # unix time of the quake
    lat: float
    lon: float
    depth_km: Optional[float]
    mag: float
    place: str = ""
    url: str = ""
    mmi: Optional[float] = None   # GeoNet: shaking at the nearest locality; USGS: estimated max
    tsunami: bool = False         # USGS: "large event in an oceanic region" (not a warning)
    alert: str = ""               # USGS PAGER impact level: green | yellow | orange | red

    def age(self, now: Optional[float] = None) -> float:
        return (time.time() if now is None else now) - self.time

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Quake":
        if not isinstance(d, dict):
            raise TypeError("not a quake")

        def num(v, default=None):
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else default
        lat, lon, mag, t = num(d.get("lat")), num(d.get("lon")), num(d.get("mag")), num(d.get("time"))
        if None in (lat, lon, mag, t) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("bad quake")
        return cls(id=str(d["id"])[:120], source=str(d.get("source", ""))[:20], time=t, lat=lat, lon=lon,
                   depth_km=num(d.get("depth_km")), mag=mag, place=str(d.get("place", ""))[:200],
                   url=_safe_url(str(d.get("url", ""))), mmi=num(d.get("mmi")), tsunami=bool(d.get("tsunami")),
                   alert=str(d.get("alert", ""))[:10] if d.get("alert") in ("green", "yellow", "orange", "red") else "")


def _safe_url(u: str) -> str:
    u = (u or "").strip()
    return u[:400] if u.startswith(("https://", "http://")) else ""


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def km_between(a1: float, o1: float, a2: float, o2: float) -> float:
    p1, p2 = math.radians(a1), math.radians(a2)
    dp, dl = p2 - p1, math.radians(o2 - o1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


# ==================================================================== parsing
def parse_usgs(data) -> list[Quake]:
    """A USGS summary GeoJSON feed. Coordinates are [lon, lat, depth km]; time is ms."""
    out = []
    feats = data.get("features") if isinstance(data, dict) else None
    for f in feats if isinstance(feats, list) else []:
        try:
            p, g = f["properties"], f["geometry"]["coordinates"]
            if p.get("type", "earthquake") != "earthquake" or p.get("status") == "deleted":
                continue                                    # quarry blasts, explosions, ...
            lon, lat = float(g[0]), float(g[1])
            depth = _num(g[2]) if len(g) > 2 else None
            mag, ms = _num(p.get("mag")), _num(p.get("time"))
            if mag is None or ms is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            alert = p.get("alert") if p.get("alert") in ("green", "yellow", "orange", "red") else ""
            out.append(Quake(id=f"usgs:{f.get('id') or p.get('code')}"[:120], source="USGS", time=ms / 1000.0,
                             lat=lat, lon=lon, depth_km=depth, mag=round(mag, 1),
                             place=str(p.get("place") or "")[:200], url=_safe_url(str(p.get("url") or "")),
                             mmi=_num(p.get("mmi")), tsunami=p.get("tsunami") == 1, alert=alert))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def parse_geonet(data) -> list[Quake]:
    """GeoNet /quake GeoJSON (version 2). Coordinates [lon, lat]; time ISO 8601."""
    out = []
    feats = data.get("features") if isinstance(data, dict) else None
    for f in feats if isinstance(feats, list) else []:
        try:
            p, g = f["properties"], f["geometry"]["coordinates"]
            if str(p.get("quality", "")).lower() == "deleted":
                continue
            lon, lat = float(g[0]), float(g[1])
            if lon > 180:
                lon -= 360
            mag = _num(p.get("magnitude"))
            t = dt.datetime.fromisoformat(str(p["time"]).replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            if mag is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            pid = str(p.get("publicID") or "")[:60]
            out.append(Quake(id=f"geonet:{pid}", source="GeoNet", time=t.timestamp(), lat=lat, lon=lon,
                             depth_km=_num(p.get("depth")), mag=round(mag, 1),
                             place=str(p.get("locality") or "")[:200],
                             url=SOURCE_PAGES["GeoNet"].format(id=pid) if pid else "",
                             mmi=_num(p.get("mmi") if "mmi" in p else p.get("MMI"))))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def merge(usgs: list[Quake], geonet: list[Quake]) -> list[Quake]:
    """Both lists, newest first, with USGS copies of GeoNet quakes removed (same quake:
    within 2 minutes and 100 km)."""
    keep = list(geonet)
    for q in usgs:
        if any(abs(q.time - g.time) < 120 and km_between(q.lat, q.lon, g.lat, g.lon) < 100 for g in geonet):
            continue
        keep.append(q)
    return sorted(keep, key=lambda q: q.time, reverse=True)


def within(quakes: Iterable[Quake], period_s: float, min_mag: float, now: Optional[float] = None) -> list[Quake]:
    now = time.time() if now is None else now
    return [q for q in quakes if 0 <= now - q.time <= period_s + 300 and q.mag >= min_mag - 1e-9]


# ===================================================================== look
def colour(q: Quake, now: Optional[float] = None) -> str:
    """By age: red under an hour, orange under 6 hours, yellow under a day, then pale."""
    a = q.age(now)
    return "#ff3b30" if a < 3600 else "#ff9500" if a < 6 * 3600 else "#ffd60a" if a < 86400 else "#c7c9d1"


def radius(mag: float) -> float:
    return max(2.5, min(14.0, 2.5 + (mag - 2.5) * 1.8))


def ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 2 * 86400:
        h = s // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    return f"{s // 86400} days ago"


def describe(q: Quake, now: Optional[float] = None) -> str:
    """One line: "M5.4 · 20 km north-east of Seddon · 12 km deep · 3 min ago (GeoNet)"."""
    parts = [f"M{q.mag:.1f}"]
    if q.place:
        parts.append(q.place)
    if q.depth_km is not None:
        parts.append(f"{q.depth_km:.0f} km deep")
    parts.append(ago(q.age(now)))
    return " · ".join(parts) + f" ({q.source})"


def nearest(q: Quake, places: Iterable) -> Optional[tuple]:
    """(place, km) of the nearest saved place (anything with .latitude/.longitude/.name)."""
    best = None
    for loc in places:
        d = km_between(q.lat, q.lon, loc.latitude, loc.longitude)
        if best is None or d < best[1]:
            best = (loc, d)
    return best


# ============================================================ notifications
@dataclass
class NotifyRules:
    near: bool = True
    near_mag: float = 4.5
    near_km: float = 300.0
    major: bool = True
    major_mag: float = 7.0


def to_notify(quakes: Iterable[Quake], places: list, rules: NotifyRules, notified: Iterable[str],
              now: Optional[float] = None) -> list[tuple[Quake, Optional[tuple]]]:
    """Recent quakes that pass the rules and haven't been notified: [(quake, (place, km) or None)]."""
    now = time.time() if now is None else now
    done = set(notified)
    out = []
    for q in quakes:
        if q.id in done or q.age(now) > NOTIFY_WITHIN_S or q.age(now) < -300:
            continue
        near = nearest(q, places)
        if rules.near and near is not None and q.mag >= rules.near_mag and near[1] <= rules.near_km:
            out.append((q, near))
        elif rules.major and q.mag >= rules.major_mag:
            out.append((q, near))
    return sorted(out, key=lambda x: -x[0].mag)


def notice(q: Quake, near: Optional[tuple], now: Optional[float] = None) -> tuple[str, str]:
    """Notification title and body."""
    if near is not None and near[1] < 1000:
        title = f"M{q.mag:.1f} earthquake {near[1]:.0f} km from {near[0].name}"
    else:
        title = f"M{q.mag:.1f} earthquake" + (f": {q.place}" if q.place else "")
    body = describe(q, now)
    if q.tsunami and q.mag >= 6.5:
        body += ("\nA large quake under the sea. If you're near the coast, check your official "
                 "tsunami advice (in New Zealand: Civil Defence, civildefence.govt.nz).")
    return title, body


# =================================================================== client
class QuakeClient:
    def __init__(self, timeout: float = TIMEOUT_S, ssl_context=None, usgs_url: Optional[str] = None,
                 geonet_url: Optional[str] = None):
        env = os.environ.get
        self.usgs_url = usgs_url or env("RBSB_WEATHER_QUAKES_USGS") or USGS_URL
        self.geonet_url = geonet_url or env("RBSB_WEATHER_QUAKES_GEONET") or GEONET_URL
        self.timeout = timeout
        self._opener = build_opener(ssl_context)
        self.user_agent = (f"RBSB-Weather/{__version__} (github.com/shanebl030-glitch/RBSB-Weather; "
                           f"Created By Shane BlackbuRn)")

    def _get_json(self, url: str, accept: str):
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": accept})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                data = resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            raise QuakeError(f"HTTP {code}") from None
        except Exception as e:
            raise QuakeError(f"couldn't connect ({getattr(e, 'reason', e)})") from None
        if len(data) > MAX_BYTES:
            raise QuakeError("the reply was unexpectedly large")
        try:
            return json.loads(data)
        except ValueError:
            raise QuakeError("the reply couldn't be read") from None

    def fetch(self, period: str = "day", min_mag: float = 2.5, nz: bool = True) -> tuple[list[Quake], dict]:
        """Recent quakes (merged, newest first) and {source: error}. A failing source
        returns nothing for that source; the caller keeps what it had."""
        feed = f"{'2.5' if min_mag < 4.5 else '4.5'}_{'week' if period == 'week' else 'day'}"
        errors, usgs, geonet = {}, [], []
        try:
            usgs = parse_usgs(self._get_json(self.usgs_url.format(feed=feed), "application/geo+json, application/json"))
        except QuakeError as e:
            errors["USGS"] = str(e)
        if nz:
            try:
                geonet = parse_geonet(self._get_json(self.geonet_url, GEONET_ACCEPT))
            except QuakeError as e:
                errors["GeoNet"] = str(e)
        return merge(usgs, geonet), errors


# ==================================================================== store
class QuakeStore:
    """quakes.json in the cache folder: the last quakes (shown offline) and which
    have been notified (so a restart doesn't repeat them)."""

    def __init__(self, directory):
        from pathlib import Path
        self.path = Path(directory) / "quakes.json"
        self.quakes: list[Quake] = []
        self.notified: list[str] = []
        self.checked = 0.0
        self.errors: dict = {}

    def load(self) -> "QuakeStore":
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            return self
        if not isinstance(d, dict):
            return self
        qs = []
        for x in (d.get("quakes") or [])[:2000]:
            try:
                qs.append(Quake.from_dict(x))
            except (KeyError, TypeError, ValueError):
                continue
        self.quakes = qs
        n = d.get("notified")
        if isinstance(n, list):
            self.notified = [str(x)[:120] for x in n if isinstance(x, str)][-500:]
        c = d.get("checked")
        self.checked = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else 0.0
        return self

    def save(self) -> None:
        from .storage import atomic_write_json
        try:
            atomic_write_json(self.path, {"version": 1, "checked": self.checked,
                                          "quakes": [q.to_dict() for q in self.quakes[:2000]],
                                          "notified": self.notified[-500:]})
        except OSError as e:
            log.warning("quakes: couldn't save %s: %s", self.path, e)

    def update(self, fresh: list[Quake], errors: dict, now: Optional[float] = None) -> None:
        """Take the new list. If a source failed, keep its quakes from before."""
        now = time.time() if now is None else now
        lists = {}
        for src in ("USGS", "GeoNet"):
            pool = self.quakes if src in errors else fresh
            lists[src] = [q for q in pool if q.source == src]
        merged = merge(lists["USGS"], lists["GeoNet"])          # also drops USGS copies of kept GeoNet quakes
        self.quakes = [q for q in merged if now - q.time <= PERIODS["week"] + 3600]
        self.errors = dict(errors)
        self.checked = now
