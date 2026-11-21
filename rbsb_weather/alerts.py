"""Weather warnings (2.4): official warnings from national weather services, and the
user's own limits worked out from the forecast.

Official warnings come straight from the service that issues them, matched to each
saved place by the warning's own area:

* New Zealand — MetService's public CAP feed (CC BY 4.0).
* United States — the National Weather Service (api.weather.gov), asked by point.
* Norway — MET Norway's MetAlerts, asked by point.
* Most of Europe — MeteoAlarm's per-country feeds (warnings that carry an area
  polygon; warnings described only by a region code are left out).

Elsewhere there's no official source here yet; the user's own limits still work.

Warnings are shown as issued: RBSB-Weather doesn't change their wording or level.
"My own limits" alerts are clearly marked as not official.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import logging
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional

from . import __version__
from .models import Forecast, Location
from .net import build_opener

log = logging.getLogger(__name__)

METSERVICE_URL = "https://alerts.metservice.com/cap/rss"
NWS_URL = "https://api.weather.gov/alerts/active"
METNO_URL = "https://api.met.no/weatherapi/metalerts/2.0/current.json"
METEOALARM_URL = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{slug}"
TIMEOUT_S = 20.0
MAX_FEED_BYTES = 8 * 1024 * 1024
MAX_CAP_BYTES = 1024 * 1024
MAX_CAP_DOCS = 60                    # per feed and check: a runaway feed can't make us fetch hundreds

# Levels, most severe first. "watch" is a yellow-level watch; "minor" an advisory/statement.
LEVELS = ("red", "orange", "yellow", "watch", "minor")
RANK = {"red": 0, "orange": 1, "yellow": 2, "watch": 2, "minor": 3, "limit": 4}
BADGE = {"red": "RED", "orange": "ORANGE", "yellow": "YELLOW", "watch": "WATCH",
         "minor": "ADVISORY", "limit": "MY LIMIT"}
# background, text (text contrast ≥ 4.5:1 on each)
COLOURS = {"red": ("#b91c1c", "#ffffff"), "orange": ("#f28c28", "#1f1300"),
           "yellow": ("#facc15", "#2a2100"), "watch": ("#facc15", "#2a2100"),
           "minor": ("#dbe4f0", "#1c2c44"), "limit": ("#e6ebf2", "#1c2c44")}
MIN_LEVEL_CHOICES = ("all", "watch", "orange", "red")   # Settings → "Show from"
INTERVAL_CHOICES = (15, 30, 60)

_UTC = dt.timezone.utc


CREDIT = ("Weather warnings from MetService (CC BY 4.0), the US National Weather Service (public domain), "
          "MET Norway (CC BY 4.0) and MeteoAlarm (EUMETNET and national weather services; "
          "UK © Crown copyright, Met Office)")


class AlertError(Exception):
    """A warning source couldn't be read. Message is user-friendly."""


# ======================================================================= model
@dataclass
class Alert:
    id: str
    source: str                      # "MetService", "US National Weather Service", "My limits", ...
    level: str                       # red | orange | yellow | watch | minor | limit
    event: str                       # "Heavy Rain Warning"
    headline: str = ""
    description: str = ""
    instruction: str = ""
    area: str = ""
    onset: Optional[float] = None    # unix time
    expires: Optional[float] = None
    issued: Optional[float] = None
    url: str = ""
    official: bool = True
    hazard: str = "other"            # rain | wind | snow | thunder | heat | cold | flood | fog | fire | other

    @property
    def badge(self) -> str:
        return BADGE.get(self.level, "ALERT")

    @property
    def rank(self) -> int:
        return RANK.get(self.level, 5)

    def title(self) -> str:
        """"Orange Heavy Rain Warning", "Strong Wind Watch", "My limit: rain over 50 mm"."""
        if not self.official:
            return self.event
        ev = self.event.strip()
        if self.level in ("red", "orange", "yellow") and not ev.lower().startswith(self.level):
            return f"{self.level.capitalize()} {ev}"
        return ev

    def active(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self.expires is None or self.expires > now

    def in_force(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self.active(now) and (self.onset is None or self.onset <= now)

    def signature(self) -> str:
        """Changes when the warning is upgraded or reissued (for notifications). A reissue —
        including an extension — carries a new issue time, so the expiry itself isn't used."""
        return f"{self.level}|{int(self.issued or self.expires or 0)}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Alert":
        def num(v):
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        if not isinstance(d, dict):
            raise TypeError("not an alert")
        level = d.get("level") if d.get("level") in RANK else "minor"
        return cls(id=str(d["id"])[:300], source=str(d.get("source", ""))[:80], level=level,
                   event=str(d.get("event", ""))[:200], headline=str(d.get("headline", ""))[:500],
                   description=str(d.get("description", ""))[:6000],
                   instruction=str(d.get("instruction", ""))[:4000], area=str(d.get("area", ""))[:1000],
                   onset=num(d.get("onset")), expires=num(d.get("expires")), issued=num(d.get("issued")),
                   url=_safe_url(str(d.get("url", ""))), official=bool(d.get("official", True)),
                   hazard=str(d.get("hazard", "other"))[:20])


def sort_alerts(alerts: Iterable[Alert]) -> list[Alert]:
    return sorted(alerts, key=lambda a: (a.rank, a.onset or 0, a.title()))


def shown(alerts: Iterable[Alert], min_level: str, muted: Iterable[str] = (),
          now: Optional[float] = None) -> list[Alert]:
    """The alerts to show for a place: active, at or above the chosen level, not muted.
    Own-limit alerts are always shown (the user turned each one on)."""
    cut = {"all": 3, "watch": 2, "orange": 1, "red": 0}.get(min_level, 2)
    muted = set(muted)
    return sort_alerts(a for a in alerts if a.active(now) and a.id not in muted
                       and (not a.official or a.rank <= cut))


def worst(alerts: Iterable[Alert]) -> Optional[Alert]:
    al = sort_alerts(alerts)
    return al[0] if al else None


# ====================================================================== helpers
_HAZARDS = (("thunder", "thunder"), ("lightning", "thunder"), ("tornado", "wind"), ("hurricane", "wind"),
            ("cyclone", "wind"), ("snow", "snow"), ("winter", "snow"), ("blizzard", "snow"), ("ice", "snow"), ("frost", "cold"),
            ("freez", "cold"), ("cold", "cold"), ("chill", "cold"), ("heat", "heat"), ("high temperature", "heat"),
            ("flood", "flood"), ("rain", "rain"), ("wind", "wind"), ("gale", "wind"), ("storm", "wind"),
            ("fog", "fog"), ("fire", "fire"), ("swell", "wind"), ("surf", "wind"))


def hazard_of(*texts: str) -> str:
    t = " ".join(x for x in texts if x).lower()
    for word, hz in _HAZARDS:
        if word in t:
            return hz
    return "other"


def _safe_url(u: str) -> str:
    u = (u or "").strip()
    return u[:500] if u.startswith(("https://", "http://")) else ""


def parse_time(s: Optional[str]) -> Optional[float]:
    """ISO 8601 (with offset or Z) or RFC 822 → unix time; None if missing or invalid."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=_UTC)
        return t.timestamp()
    except ValueError:
        pass
    try:
        t = email.utils.parsedate_to_datetime(s)
        if t.tzinfo is None:
            t = t.replace(tzinfo=_UTC)
        return t.timestamp()
    except (TypeError, ValueError, IndexError):
        return None


def _clean(text: Optional[str], limit: int = 6000) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]{0,200}>", " ", str(text))             # stray HTML tags
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()[:limit]


# ---------------------------------------------------------------- geometry
def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray casting; ring is [(lat, lon), ...]. Handles rings across the antimeridian."""
    if len(ring) < 3:
        return False
    lons = [p[1] for p in ring]
    if max(lons) - min(lons) > 180:                 # crosses ±180°: shift to 0..360
        ring = [(a, b + 360 if b < 0 else b) for a, b in ring]
        if lon < 0:
            lon += 360
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x = xi + (lat - yi) * (xj - xi) / (yj - yi)
            if lon < x:
                inside = not inside
        j = i
    return inside


def parse_cap_polygon(text: str) -> list[tuple[float, float]]:
    """CAP polygon "lat,lon lat,lon ..." → [(lat, lon), ...] ([] if invalid)."""
    out = []
    for pair in (text or "").split():
        try:
            a, b = pair.split(",")[:2]
            la, lo = float(a), float(b)
        except ValueError:
            return []
        if not (-90 <= la <= 90 and -180 <= lo <= 180):
            return []
        out.append((la, lo))
        if len(out) > 20000:
            return []
    return out


def in_circle(lat: float, lon: float, text: str) -> bool:
    """CAP circle "lat,lon radius_km"."""
    try:
        centre, radius = text.split()
        la, lo = (float(x) for x in centre.split(",")[:2])
        r = float(radius)
    except ValueError:
        return False
    return _km(lat, lon, la, lo) <= r


def _km(a1, o1, a2, o2) -> float:
    p1, p2 = math.radians(a1), math.radians(a2)
    dp, dl = p2 - p1, math.radians(o2 - o1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def geojson_contains(geom, lat: float, lon: float) -> Optional[bool]:
    """True/False for a Polygon/MultiPolygon; None when there's no usable geometry."""
    if not isinstance(geom, dict):
        return None
    kind, coords = geom.get("type"), geom.get("coordinates")
    polys = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else None
    if not isinstance(polys, list):
        return None
    try:
        for poly in polys:
            rings = [[(float(p[1]), float(p[0])) for p in ring] for ring in poly]
            if rings and point_in_ring(lat, lon, rings[0]) and \
                    not any(point_in_ring(lat, lon, hole) for hole in rings[1:]):
                return True
    except (TypeError, ValueError, IndexError):
        return None
    return False


# ==================================================================== CAP XML
def _xml(data: bytes) -> ET.Element:
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise AlertError("the warning feed contained something unexpected, so it was ignored")
    try:
        return ET.fromstring(data)
    except ET.ParseError as e:
        raise AlertError(f"the warning feed couldn't be read ({e})") from None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el: ET.Element, name: str) -> Optional[ET.Element]:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _text(el: Optional[ET.Element], name: str) -> str:
    c = _child(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def _params(info: ET.Element) -> dict:
    out = {}
    for p in _children(info, "parameter"):
        k, v = _text(p, "valueName"), _text(p, "value")
        if k:
            out[k.lower()] = v
    return out


def _colour_level(*texts: str) -> Optional[str]:
    for t in texts:
        t = (t or "").lower()
        for lvl in ("red", "orange", "yellow"):
            if re.search(rf"\b{lvl}\b", t):
                return lvl
    return None


def level_from(severity: str, event: str = "", colour: str = "", headline: str = "",
               certainty: str = "", trust_severity: bool = True) -> str:
    """The display level. A service's own colour comes first; then CAP severity."""
    ev = f"{event} {headline}".lower()
    lvl = _colour_level(colour)
    if lvl is None and not trust_severity:
        lvl = _colour_level(headline, event)
    if lvl is None:
        lvl = {"extreme": "red", "severe": "orange", "moderate": "yellow",
               "minor": "minor"}.get((severity or "").strip().lower())
    if lvl is None:
        lvl = _colour_level(headline, event) or "minor"
    if "watch" in ev and lvl in ("yellow", "minor"):
        return "watch"
    if lvl == "minor" and "warning" in ev:
        return "yellow"
    return lvl


def _pick_info(alert: ET.Element) -> Optional[ET.Element]:
    infos = _children(alert, "info")
    if not infos:
        return None
    for info in infos:
        lang = _text(info, "language").lower()
        if not lang or lang.startswith("en"):
            return info
    return infos[0]


def cap_alert(root: ET.Element, source: str, url: str = "", colour_param: str = "",
              trust_severity: bool = True, feed_id: str = "") -> Optional[tuple[Alert, list]]:
    """One CAP <alert> → (Alert, areas). areas: list of ("polygon", ring) / ("circle", text).
    None for tests, exercises, cancellations and anything that isn't a public alert."""
    if _local(root.tag) != "alert":
        return None
    status = _text(root, "status").lower()
    msg_type = _text(root, "msgType").lower()
    if status and status != "actual" or msg_type == "cancel":
        return None
    info = _pick_info(root)
    if info is None:
        return None
    params = _params(info)
    event = _text(info, "event")
    headline = _text(info, "headline")
    colour = params.get(colour_param.lower(), "") if colour_param else ""
    if not colour:
        colour = params.get("awareness_level", "") or params.get("colourcode", "") or params.get("colorcode", "")
    level = level_from(_text(info, "severity"), event, colour, headline, trust_severity=trust_severity)
    areas, descs = [], []
    for area in _children(info, "area"):
        d = _text(area, "areaDesc")
        if d:
            descs.append(d)
        for p in _children(area, "polygon"):
            ring = parse_cap_polygon(p.text or "")
            if ring:
                areas.append(("polygon", ring))
        for c in _children(area, "circle"):
            if c.text:
                areas.append(("circle", c.text.strip()))
    title = headline if headline and len(headline) < 90 else event
    # MetService headlines read "Heavy Rain Warning - Orange": the colour is shown by the level
    title = re.sub(r"\s*[-–]\s*(red|orange|yellow)\s*$", "", title, flags=re.I) or event
    alert = Alert(
        id=(feed_id or _text(root, "identifier") or url or headline)[:300],
        source=source, level=level, event=_clean(title, 200) or "Weather warning",
        headline=_clean(headline, 500), description=_clean(_text(info, "description")),
        instruction=_clean(_text(info, "instruction"), 4000), area=_clean("; ".join(descs), 1000),
        onset=parse_time(_text(info, "onset") or _text(info, "effective")),
        expires=parse_time(_text(info, "expires")), issued=parse_time(_text(root, "sent")),
        url=_safe_url(_text(info, "web") or url), official=True,
        hazard=hazard_of(event, headline, params.get("awareness_type", "")))
    return alert, areas


def covers(areas: list, lat: float, lon: float) -> Optional[bool]:
    """Does any area include the point? None when the warning has no polygon or circle."""
    if not areas:
        return None
    for kind, a in areas:
        if kind == "polygon" and point_in_ring(lat, lon, a):
            return True
        if kind == "circle" and in_circle(lat, lon, a):
            return True
    return False


def feed_entries(root: ET.Element) -> list[dict]:
    """RSS <item>s or Atom <entry>s: {"id", "link", "updated", "el"}."""
    out = []
    items = list(root.iter())
    for el in items:
        name = _local(el.tag)
        if name not in ("item", "entry"):
            continue
        link = ""
        for l in _children(el, "link"):
            href = l.get("href") or (l.text or "").strip()
            typ = (l.get("type") or "").lower()
            if href and (not link or "cap" in typ or "xml" in typ):
                link = href
        guid = _text(el, "guid") or _text(el, "id")
        if not link and guid.startswith("http"):
            link = guid
        out.append({"id": guid or link, "link": _safe_url(link),
                    "updated": _text(el, "updated") or _text(el, "pubDate") or _text(el, "published"),
                    "el": el})
    return out


def inline_cap(entry: ET.Element, source: str, feed_id: str) -> Optional[tuple[Alert, list]]:
    """MeteoAlarm-style Atom entries carry the CAP fields (cap:event, cap:polygon, ...) inline."""
    def t(name):
        for c in entry.iter():
            if _local(c.tag) == name and c.text:
                return c.text.strip()
        return ""
    if not t("event") and not t("severity"):
        return None
    status, msg_type = t("status").lower(), t("message_type").lower() or t("msgType").lower()
    if status and status != "actual" or msg_type == "cancel":
        return None
    areas = []
    for c in entry.iter():
        if _local(c.tag) == "polygon" and c.text:
            ring = parse_cap_polygon(c.text)
            if ring:
                areas.append(("polygon", ring))
        elif _local(c.tag) == "circle" and c.text:
            areas.append(("circle", c.text.strip()))
    title = _text(entry, "title")
    event = t("event")
    level = level_from(t("severity"), event, "", title, trust_severity=True)
    link = ""
    for l in _children(entry, "link"):
        if l.get("href"):
            link = link or l.get("href")
    alert = Alert(id=(t("identifier") or feed_id)[:300] + (f"#{feed_id}" if t("identifier") and feed_id else ""),
                  source=source, level=level, event=_clean(event or title, 200),
                  headline=_clean(title, 500), description=_clean(t("description") or _text(entry, "summary")),
                  instruction=_clean(t("instruction"), 4000), area=_clean(t("areaDesc"), 1000),
                  onset=parse_time(t("onset") or t("effective")), expires=parse_time(t("expires")),
                  issued=parse_time(t("sent") or _text(entry, "updated")), url=_safe_url(link), official=True,
                  hazard=hazard_of(event, title))
    return alert, areas


# ================================================================== sources
NZ_NAMES = {"new zealand", "aotearoa", "nz"}
US_NAMES = {"united states", "united states of america", "usa", "us", "puerto rico", "guam",
            "u.s. virgin islands", "american samoa", "northern mariana islands"}
NO_NAMES = {"norway", "norge", "svalbard and jan mayen", "svalbard"}
# MeteoAlarm feeds by country (slugs as in feeds.meteoalarm.org; several tried where unsure)
METEOALARM = {
    "austria": ["austria"], "belgium": ["belgium"], "bosnia and herzegovina": ["bosnia-herzegovina", "bosnia-and-herzegovina"],
    "bulgaria": ["bulgaria"], "croatia": ["croatia"], "cyprus": ["cyprus"],
    "czechia": ["czechia", "czech-republic"], "czech republic": ["czechia", "czech-republic"],
    "denmark": ["denmark"], "estonia": ["estonia"], "finland": ["finland"], "france": ["france"],
    "germany": ["germany"], "greece": ["greece"], "hungary": ["hungary"], "iceland": ["iceland"],
    "ireland": ["ireland"], "israel": ["israel"], "italy": ["italy"], "latvia": ["latvia"],
    "lithuania": ["lithuania"], "luxembourg": ["luxembourg"], "malta": ["malta"],
    "moldova": ["moldova", "republic-of-moldova"], "montenegro": ["montenegro"],
    "netherlands": ["netherlands"], "the netherlands": ["netherlands"],
    "north macedonia": ["republic-of-north-macedonia", "north-macedonia"],
    "poland": ["poland"], "portugal": ["portugal"], "romania": ["romania"], "serbia": ["serbia"],
    "slovakia": ["slovakia"], "slovenia": ["slovenia"], "spain": ["spain"], "sweden": ["sweden"],
    "switzerland": ["switzerland"], "united kingdom": ["united-kingdom"], "uk": ["united-kingdom"],
    "ukraine": ["ukraine"], "andorra": ["andorra"],
}


def _in_box(loc: Location, la0, la1, lo0, lo1) -> bool:
    return la0 <= loc.latitude <= la1 and lo0 <= loc.longitude <= lo1


def source_for(loc: Location) -> Optional[str]:
    """Which official source covers a place: "metservice" | "nws" | "metno" | "meteoalarm" | None."""
    c = (loc.country or "").strip().lower()
    if c in NZ_NAMES or (not c and (_in_box(loc, -48, -33, 165, 180) or _in_box(loc, -45, -43, -177, -175))):
        return "metservice"
    if c in US_NAMES:
        return "nws"
    if c in NO_NAMES:
        return "metno"
    if c in METEOALARM:
        return "meteoalarm"
    return None


SOURCE_NAMES = {"metservice": "MetService", "nws": "US National Weather Service",
                "metno": "MET Norway", "meteoalarm": "MeteoAlarm"}
SOURCE_SITES = {"metservice": "https://www.metservice.com/warnings/home", "nws": "https://www.weather.gov/",
                "metno": "https://www.met.no/en", "meteoalarm": "https://meteoalarm.org/"}


def coverage_text(loc: Location) -> str:
    sid = source_for(loc)
    if sid is None:
        return "Not covered yet"
    return SOURCE_NAMES[sid]


class AlertClient:
    """Downloads official warnings. Each source is tried on its own: one failing doesn't
    stop the others."""

    def __init__(self, timeout: float = TIMEOUT_S, ssl_context=None,
                 metservice_url: Optional[str] = None, nws_url: Optional[str] = None,
                 metno_url: Optional[str] = None, meteoalarm_url: Optional[str] = None):
        env = os.environ.get
        self.metservice_url = metservice_url or env("RBSB_WEATHER_ALERTS_METSERVICE") or METSERVICE_URL
        self.nws_url = nws_url or env("RBSB_WEATHER_ALERTS_NWS") or NWS_URL
        self.metno_url = metno_url or env("RBSB_WEATHER_ALERTS_METNO") or METNO_URL
        self.meteoalarm_url = meteoalarm_url or env("RBSB_WEATHER_ALERTS_METEOALARM") or METEOALARM_URL
        self.timeout = timeout
        self._opener = build_opener(ssl_context)
        # NWS and MET Norway ask for a User-Agent that identifies the app and a contact
        self.user_agent = (f"RBSB-Weather/{__version__} (github.com/shanebl030-glitch/RBSB-Weather; "
                           f"Created By Shane BlackbuRn)")
        self._cap_cache: dict[str, tuple[str, Optional[tuple]]] = {}    # url -> (feed "updated", parsed)
        self._ma_slug: dict[str, str] = {}                               # country -> slug that worked

    # ---------------------------------------------------------------- http
    def _get(self, url: str, accept: str = "*/*", limit: int = MAX_FEED_BYTES) -> bytes:
        if not url.startswith(("https://", "http://")):
            raise AlertError("bad address")
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": accept})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                data = resp.read(limit + 1)
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            raise AlertError(f"HTTP {code}") from None
        except Exception as e:
            raise AlertError(f"couldn't connect ({getattr(e, 'reason', e)})") from None
        if len(data) > limit:
            raise AlertError("the reply was unexpectedly large")
        return data

    # ------------------------------------------------------------- sources
    def fetch_all(self, locations: list[Location],
                  cancelled: Optional[Callable[[], bool]] = None) -> tuple[dict, dict]:
        """Official warnings for every place. Returns ({key: [Alert]}, {source id: error})
        — a place whose source failed is missing from the first dict (keep its old warnings)."""
        by_source: dict[str, list[Location]] = {}
        for loc in locations:
            sid = source_for(loc)
            if sid:
                by_source.setdefault(sid, []).append(loc)
        out: dict[str, list[Alert]] = {}
        errors: dict[str, str] = {}
        for sid, locs in by_source.items():
            if cancelled and cancelled():
                break
            try:
                if sid == "metservice":
                    out.update(self._metservice(locs))
                elif sid == "nws":
                    out.update(self._nws(locs, errors))
                elif sid == "metno":
                    out.update(self._metno(locs, errors))
                elif sid == "meteoalarm":
                    out.update(self._meteoalarm(locs, errors))
            except AlertError as e:
                errors[sid] = str(e)
                log.info("alerts: %s: %s", sid, e)
            except Exception as e:                   # a damaged reply must never crash a check
                errors[sid] = f"unexpected problem ({e.__class__.__name__})"
                log.exception("alerts: %s crashed", sid)
        return out, errors

    def _cap_feed(self, url: str, source: str, colour_param: str = "", trust_severity: bool = True) -> list:
        """A feed of CAP documents (RSS or Atom): [(Alert, areas)]. CAP documents are fetched
        once and reused until the feed says they changed."""
        root = _xml(self._get(url, "application/rss+xml, application/atom+xml, application/xml"))
        got, seen = [], set()
        for e in feed_entries(root)[:MAX_CAP_DOCS * 3]:
            inl = inline_cap(e["el"], source, e["id"])
            if inl is not None:
                got.append(inl)
                continue
            link = e["link"]
            if not link or link in seen:
                continue
            seen.add(link)
            if len(seen) > MAX_CAP_DOCS:
                break
            cached = self._cap_cache.get(link)
            if cached is not None and cached[0] == e["updated"]:
                parsed = cached[1]
            else:
                try:
                    doc = _xml(self._get(link, "application/cap+xml, application/xml", MAX_CAP_BYTES))
                    parsed = cap_alert(doc, source, link, colour_param, trust_severity,
                                       feed_id=e["id"] if not doc.findtext("{*}identifier") else "")
                except AlertError as err:
                    log.info("alerts: %s: %s", link, err)
                    continue
                self._cap_cache[link] = (e["updated"], parsed)
            if parsed is not None:
                got.append(parsed)
        live = {e["link"] for e in feed_entries(root)}
        for k in [k for k in self._cap_cache if k not in live]:
            del self._cap_cache[k]                    # gone from the feed: no longer current
        return got

    @staticmethod
    def _match(parsed: list, locs: list[Location]) -> dict:
        out = {loc.key: [] for loc in locs}
        for alert, areas in parsed:
            for loc in locs:
                if covers(areas, loc.latitude, loc.longitude):
                    out[loc.key].append(alert)
        return out

    def _metservice(self, locs: list[Location]) -> dict:
        # MetService's CAP severity sits a step below the colour it issues, so its
        # ColourCode parameter decides the level.
        parsed = self._cap_feed(self.metservice_url, "MetService", colour_param="ColourCode",
                                trust_severity=False)
        return self._match(parsed, locs)

    def _meteoalarm(self, locs: list[Location], errors: dict) -> dict:
        out = {}
        by_country: dict[str, list[Location]] = {}
        for loc in locs:
            by_country.setdefault(loc.country.strip().lower(), []).append(loc)
        for country, cl in by_country.items():
            slugs = METEOALARM.get(country, [])
            if country in self._ma_slug:
                slugs = [self._ma_slug[country]]
            last = None
            for slug in slugs:
                try:
                    parsed = self._cap_feed(self.meteoalarm_url.format(slug=slug), "MeteoAlarm")
                except AlertError as e:
                    last = e
                    continue
                self._ma_slug[country] = slug
                out.update(self._match(parsed, cl))
                last = None
                break
            if last is not None:
                errors["meteoalarm"] = f"{country.title()}: {last}"
        return out

    def _nws(self, locs: list[Location], errors: dict) -> dict:
        out = {}
        for loc in locs:
            url = f"{self.nws_url}?point={loc.latitude:.4f},{loc.longitude:.4f}"
            try:
                data = json.loads(self._get(url, "application/geo+json"))
            except (AlertError, ValueError) as e:
                errors["nws"] = str(e)
                continue
            out[loc.key] = parse_nws(data)
        return out

    def _metno(self, locs: list[Location], errors: dict) -> dict:
        out = {}
        for loc in locs:
            url = f"{self.metno_url}?lat={loc.latitude:.4f}&lon={loc.longitude:.4f}&lang=en"
            try:
                data = json.loads(self._get(url, "application/json"))
            except (AlertError, ValueError) as e:
                errors["metno"] = str(e)
                continue
            out[loc.key] = parse_metno(data, loc.latitude, loc.longitude)
        return out


def parse_nws(data) -> list[Alert]:
    """api.weather.gov /alerts/active?point= GeoJSON (the service already matched the point)."""
    out = []
    feats = data.get("features") if isinstance(data, dict) else None
    for f in feats if isinstance(feats, list) else []:
        p = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(p, dict):
            continue
        if str(p.get("status", "Actual")).lower() != "actual" or str(p.get("messageType", "")).lower() == "cancel":
            continue
        event = str(p.get("event") or "")
        headline = str(p.get("headline") or "")
        level = level_from(str(p.get("severity") or ""), event, "", headline)
        out.append(Alert(
            id=str(p.get("id") or f.get("id") or headline)[:300], source="US National Weather Service",
            level=level, event=_clean(event, 200) or "Weather alert", headline=_clean(headline, 500),
            description=_clean(p.get("description")), instruction=_clean(p.get("instruction"), 4000),
            area=_clean(p.get("areaDesc"), 1000),
            onset=parse_time(p.get("onset") or p.get("effective")),
            expires=parse_time(p.get("ends") or p.get("expires")), issued=parse_time(p.get("sent")),
            url=_safe_url(str(p.get("@id") or f.get("id") or "")), official=True, hazard=hazard_of(event)))
    return out


def parse_metno(data, lat: float, lon: float) -> list[Alert]:
    """MET Norway MetAlerts current.json (GeoJSON). Asked by point; the polygon is checked too."""
    out = []
    feats = data.get("features") if isinstance(data, dict) else None
    for f in feats if isinstance(feats, list) else []:
        if not isinstance(f, dict) or not isinstance(f.get("properties"), dict):
            continue
        p = f["properties"]
        if str(p.get("status", "Actual")).lower() != "actual":
            continue
        if geojson_contains(f.get("geometry"), lat, lon) is False:
            continue
        when = (f.get("when") or {}).get("interval") or [None, None]
        colour = str(p.get("riskMatrixColor") or p.get("awareness_level") or "")
        title = str(p.get("title") or "")
        event = str(p.get("eventAwarenessName") or p.get("event") or "")
        name = event.capitalize() if event else "Weather warning"
        level = level_from(str(p.get("severity") or ""), name, colour, title)
        out.append(Alert(
            id=str(p.get("id") or title)[:300], source="MET Norway", level=level,
            event=_clean(name, 200), headline=_clean(title, 500),
            description=_clean(" ".join(str(p.get(k) or "") for k in ("description", "consequences"))),
            instruction=_clean(p.get("instruction") or p.get("awarenessResponse"), 4000),
            area=_clean(p.get("area"), 1000),
            onset=parse_time(when[0] if len(when) > 0 else None),
            expires=parse_time(when[1] if len(when) > 1 else None),
            issued=parse_time((data.get("lastChange") if isinstance(data, dict) else None)),
            url=_safe_url(str(p.get("web") or "")), official=True,
            hazard=hazard_of(event, str(p.get("awareness_type") or ""), title)))
    return out


# ================================================================ own limits
@dataclass
class Limit:
    on: bool
    value: float


DEFAULT_LIMITS = {"gust": Limit(True, 90.0), "rain": Limit(True, 50.0), "heat": Limit(False, 30.0),
                  "frost": Limit(True, 0.0), "snow": Limit(False, 0.0), "thunder": Limit(True, 0.0)}
LIMIT_RANGES = {"gust": (20, 250), "rain": (1, 500), "heat": (-20, 60), "frost": (-60, 20),
                "snow": (0, 0), "thunder": (0, 0)}


def limits_from_dict(d) -> dict[str, Limit]:
    out = {k: Limit(v.on, v.value) for k, v in DEFAULT_LIMITS.items()}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if k in out and isinstance(v, dict):
            on = v.get("on")
            val = v.get("value")
            if isinstance(on, bool):
                out[k].on = on
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                lo, hi = LIMIT_RANGES[k]
                out[k].value = float(min(hi, max(lo, val)))
    return out


def limits_to_dict(limits: dict[str, Limit]) -> dict:
    return {k: {"on": v.on, "value": v.value} for k, v in limits.items()}


SNOW_CODES = {71, 73, 75, 77, 85, 86}
THUNDER_CODES = {95, 96, 99}


def own_alerts(fc: Forecast, limits: dict[str, Limit], wind_unit: str = "km/h", temp_unit: str = "C",
               precip_unit: str = "mm", now: Optional[float] = None) -> list[Alert]:
    """The user's own limits, checked against the forecast (one alert per limit: the first
    day it's passed, with any later days listed). Values are in base units (km/h, °C, mm)."""
    from . import units
    now = time.time() if now is None else now
    off = fc.utc_offset_seconds or 0
    tz = dt.timezone(dt.timedelta(seconds=off))
    today = dt.datetime.fromtimestamp(now, tz).date()
    gusts = list(getattr(fc, "daily_gusts", []) or [])
    days = []
    for i, d in enumerate(fc.daily):
        try:
            date = dt.date.fromisoformat(d.date[:10])
        except ValueError:
            continue
        if date < today:
            continue
        g = gusts[i] if i < len(gusts) else None
        if g is None and date == today and fc.current is not None:
            g = fc.current.wind_gusts
        days.append((date, d, g))

    def fmt_temp(v):
        return units.fmt_temp(v, temp_unit)

    rules = (
        ("gust", "wind", lambda d, g, v: g is not None and g > v,
         lambda v: f"My limit: wind gusts over {units.fmt_wind(v, wind_unit)}",
         lambda d, g: f"gusts to {units.fmt_wind(g, wind_unit)}"),
        ("rain", "rain", lambda d, g, v: d.precipitation_sum is not None and d.precipitation_sum > v,
         lambda v: f"My limit: rain over {units.fmt_precip(v, precip_unit)} in a day",
         lambda d, g: f"{units.fmt_precip(d.precipitation_sum, precip_unit)} of rain"),
        ("heat", "heat", lambda d, g, v: d.temp_max is not None and d.temp_max > v,
         lambda v: f"My limit: temperature above {fmt_temp(v)}",
         lambda d, g: f"a high of {fmt_temp(d.temp_max)}"),
        ("frost", "cold", lambda d, g, v: d.temp_min is not None and d.temp_min < v,
         lambda v: f"My limit: temperature below {fmt_temp(v)}",
         lambda d, g: f"a low of {fmt_temp(d.temp_min)}"),
        ("snow", "snow", lambda d, g, v: d.weather_code in SNOW_CODES,
         lambda v: "My limit: snow", lambda d, g: "snow"),
        ("thunder", "thunder", lambda d, g, v: d.weather_code in THUNDER_CODES,
         lambda v: "My limit: thunderstorms", lambda d, g: "thunderstorms"),
    )
    out = []
    for key, hazard, test, title, what in rules:
        lim = limits.get(key)
        if lim is None or not lim.on:
            continue
        hits = [(date, d, g) for date, d, g in days if test(d, g, lim.value)]
        if not hits:
            continue
        date, d, g = hits[0]
        start = dt.datetime.combine(date, dt.time(), tz)
        names = [_day_name(x[0], today) for x in hits]
        desc = f"The forecast shows {what(d, g)} {_day_name(date, today).lower() if date == today else 'on ' + _day_name(date, today)}."
        if len(hits) > 1:
            desc += f" Also: {', '.join(names[1:])}."
        out.append(Alert(
            id=f"limit:{key}:{fc.location.key}:{date.isoformat()}", source="My limits", level="limit",
            event=title(lim.value), headline=desc, description=desc +
            " This comes from RBSB-Weather's forecast and your own limit; it is not an official warning.",
            area=fc.location.display_name, onset=start.timestamp(),
            expires=(start + dt.timedelta(days=1)).timestamp(), issued=None,
            official=False, hazard=hazard))
    return out


def _day_name(date: dt.date, today: dt.date) -> str:
    if date == today:
        return "Today"
    if date == today + dt.timedelta(days=1):
        return "Tomorrow"
    return date.strftime("%a %d %b").replace(" 0", " ")


def rain_between(fc: Forecast, start: Optional[float], end: Optional[float]) -> Optional[float]:
    """Total forecast rain (mm) in [start, end), from the hourly forecast; None if it can't be worked out."""
    if fc is None or not fc.hourly or start is None or end is None:
        return None
    tz = dt.timezone(dt.timedelta(seconds=fc.utc_offset_seconds or 0))
    total, n = 0.0, 0
    for h in fc.hourly:
        try:
            t = dt.datetime.fromisoformat(h.time)
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=tz)
        ts = t.timestamp()
        if start <= ts < end and h.precipitation is not None:
            total += h.precipitation
            n += 1
    return round(total, 1) if n else None


# ===================================================================== store
class AlertStore:
    """alerts.json in the cache folder: the last warnings per place, when each source was
    last read, and which warnings have already been notified (so a restart doesn't repeat them)."""

    def __init__(self, directory):
        from pathlib import Path
        self.path = Path(directory) / "alerts.json"
        self.alerts: dict[str, list[Alert]] = {}
        self.notified: dict[str, str] = {}              # alert id -> signature
        self.checked: float = 0.0
        self.errors: dict[str, str] = {}

    def load(self) -> "AlertStore":
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            return self
        if not isinstance(d, dict):
            return self
        now = time.time()
        for key, lst in (d.get("alerts") or {}).items():
            if isinstance(lst, list):
                good = []
                for x in lst[:100]:
                    try:
                        a = Alert.from_dict(x)
                    except (KeyError, TypeError, ValueError):
                        continue
                    if a.official and a.active(now):
                        good.append(a)
                self.alerts[str(key)] = good
        n = d.get("notified")
        if isinstance(n, dict):
            self.notified = {str(k): str(v) for k, v in list(n.items())[-500:]}
        c = d.get("checked")
        self.checked = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else 0.0
        return self

    def save(self) -> None:
        from .storage import atomic_write_json
        try:
            atomic_write_json(self.path, {
                "version": 1, "checked": self.checked,
                "alerts": {k: [a.to_dict() for a in v if a.official] for k, v in self.alerts.items()},
                "notified": dict(list(self.notified.items())[-500:])})
        except OSError as e:
            log.warning("alerts: couldn't save %s: %s", self.path, e)

    def update(self, fresh: dict[str, list[Alert]], keys: Iterable[str]) -> None:
        """Replace the warnings of the places that were read; drop places no longer saved."""
        keys = set(keys)
        for k, v in fresh.items():
            if k in keys:
                self.alerts[k] = v
        for k in [k for k in self.alerts if k not in keys]:
            del self.alerts[k]
        now = time.time()
        live = {a.id for v in self.alerts.values() for a in v if a.active(now)}
        self.notified = {k: v for k, v in self.notified.items() if k in live or k.startswith("limit:")}


def to_notify(alerts: Iterable[Alert], notified: dict[str, str], min_level: str,
              muted: Iterable[str] = ()) -> list[Alert]:
    """Alerts that are new, upgraded or changed since last notified (watches and advisories
    only if the user asked to see them; own limits once per day they first appear)."""
    out = []
    for a in shown(alerts, min_level, muted):
        if a.level in ("minor",):
            continue
        if notified.get(a.id) != a.signature():
            out.append(a)
    return out
