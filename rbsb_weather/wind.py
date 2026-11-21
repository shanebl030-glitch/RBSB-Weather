"""World wind for the Wind tab (2.2.0): NOAA GFS 10 m wind on a 1 degree grid.

NOAA's Global Forecast System (GFS) runs four times a day (00, 06, 12 and 18
UTC) and is published free of charge, with no key; it's public domain. Only the
two fields the tab needs are downloaded (the wind's east-west "U" and
north-south "V" parts, 10 m above the ground), about 200 KB:

1. NOMADS, NOAA's "grib filter" service, which cuts those two fields out of
   the run's file for us;
2. if that fails, NOAA's copy of GFS on Amazon (the NOAA Open Data
   Dissemination programme): the run's index file says where the two fields
   are, and just those bytes are fetched.

The newest run is normally out about 4 hours after its start time; if it isn't
there yet, the one before is used. The forecast hour closest to now is shown
(GFS has one every 3 hours), so what you see is never more than 90 minutes from
the current time.

Everything is kept in ~/.cache/rbsb-weather/wind/ so the tab works offline,
and is fetched again only when a newer forecast time is due (every 3 hours).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__, grib2
from .net import build_opener

try:
    import numpy as _np
except Exception:          # pragma: no cover - depends on the system
    _np = None

log = logging.getLogger(__name__)

NOMADS_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_1p00.pl"
AWS_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
CREDIT = "Wind: NOAA Global Forecast System (GFS), public domain"
PROJECT_URL = "https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast"

PUBLISH_DELAY_H = 4            # a run is normally downloadable about this long after it starts
MAX_FHOUR = 384
REFRESH_S = 3 * 3600
RETRY_S = 20 * 60              # after a failed download
TIMEOUT_S = 30.0
MAX_BYTES = 4 * 1024 * 1024
_UTC = dt.timezone.utc


class WindError(Exception):
    """A plain-English reason the wind couldn't be fetched or read."""


# ------------------------------------------------------------------- the wind field
@dataclass
class WindField:
    """10 m wind (m/s) on a regular grid: rows from north to south, columns from lon0 east."""
    nj: int
    ni: int
    lat0: float                  # latitude of the first (northernmost) row
    lon0: float                  # longitude of the first column
    dlat: float
    dlon: float
    u: object                    # (nj, ni) numpy array, or list of lists
    v: object
    run: dt.datetime             # model run (UTC)
    valid: dt.datetime           # time the wind is for (UTC)

    @property
    def fhour(self) -> int:
        return int(round((self.valid - self.run).total_seconds() / 3600))

    def _locate(self, lat: float, lon: float):
        fy = (self.lat0 - lat) / self.dlat
        fx = ((lon - self.lon0) % 360.0) / self.dlon
        fy = min(max(fy, 0.0), self.nj - 1.000001)
        j = int(fy)
        i = int(fx) % self.ni
        return j, i, fy - j, fx - int(fx)

    def at(self, lat: float, lon: float) -> tuple[float, float]:
        """(u, v) in m/s at a point, interpolated between the four nearest grid points."""
        j, i, ty, tx = self._locate(lat, lon)
        i2 = (i + 1) % self.ni
        out = []
        for a in (self.u, self.v):
            r0, r1 = a[j], a[j + 1]
            top = r0[i] * (1 - tx) + r0[i2] * tx
            bot = r1[i] * (1 - tx) + r1[i2] * tx
            out.append(float(top * (1 - ty) + bot * ty))
        return out[0], out[1]

    def at_many(self, lat, lon):
        """Vectorised at() for numpy arrays of positions."""
        np = _np
        fy = np.clip((self.lat0 - lat) / self.dlat, 0.0, self.nj - 1.000001)
        fx = ((lon - self.lon0) % 360.0) / self.dlon
        j = fy.astype(np.int64)
        i = fx.astype(np.int64) % self.ni
        ty, tx = fy - j, fx - np.floor(fx)
        i2 = (i + 1) % self.ni
        res = []
        for a in (self.u, self.v):
            top = a[j, i] * (1 - tx) + a[j, i2] * tx
            bot = a[j + 1, i] * (1 - tx) + a[j + 1, i2] * tx
            res.append(top * (1 - ty) + bot * ty)
        return res[0], res[1]


def speed_and_direction(u: float, v: float) -> tuple[float, float]:
    """Speed (m/s) and the direction the wind comes FROM (degrees, 0 = north), as
    forecasts give it: U is towards the east, V towards the north."""
    return math.hypot(u, v), (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


def field_from_grib(buf: bytes, run: Optional[dt.datetime] = None) -> WindField:
    msgs = grib2.messages(buf)
    u = next((m for m in msgs if (m.discipline, m.category, m.number, m.level_type) == (0, 2, 2, 103)
              and abs(m.level - 10) < 0.01), None)
    v = next((m for m in msgs if (m.discipline, m.category, m.number, m.level_type) == (0, 2, 3, 103)
              and abs(m.level - 10) < 0.01), None)
    if u is None or v is None:
        raise WindError("The wind file doesn't contain the 10 m wind.")
    g = u.grid
    if (g.ni, g.nj) != (v.grid.ni, v.grid.nj):
        raise WindError("The two wind fields use different grids.")
    if g.ni < 4 or g.nj < 3 or g.di <= 0 or g.dj <= 0:
        raise WindError("The wind grid is too small to use.")
    ru, rv = u.rows_north_to_south(), v.rows_north_to_south()
    if _np is not None and not isinstance(ru, list):
        ru = _np.nan_to_num(_np.asarray(ru, _np.float32))
        rv = _np.nan_to_num(_np.asarray(rv, _np.float32))
    else:
        ru = [[0.0 if x is None else x for x in row] for row in ru]
        rv = [[0.0 if x is None else x for x in row] for row in rv]
    lat0 = max(g.la1, g.la2)
    west = g.lo1 if not g.scan & 0x80 else g.lo2
    y, mo, d, h, mi, s = u.reference_time
    ref = run or dt.datetime(y, mo, d, h, mi, s, tzinfo=_UTC)
    valid = ref + dt.timedelta(hours=u.forecast_hours or 0)
    return WindField(g.nj, g.ni, lat0, west % 360.0, g.dj, g.di, ru, rv, ref, valid)


# ------------------------------------------------------------------- which run
def runs_to_try(now: dt.datetime, count: int = 3) -> list[tuple[dt.datetime, int]]:
    """(run, forecast hour) pairs to try, newest first, each giving the forecast closest
    to `now` that the run has."""
    now = now.astimezone(_UTC)
    newest = now - dt.timedelta(hours=PUBLISH_DELAY_H)
    run = newest.replace(hour=newest.hour // 6 * 6, minute=0, second=0, microsecond=0)
    out = []
    for k in range(count):
        r = run - dt.timedelta(hours=6 * k)
        hours = (now - r).total_seconds() / 3600
        f = int(round(hours / 3.0)) * 3
        out.append((r, max(0, min(MAX_FHOUR, f))))
    return out


def nomads_url(run: dt.datetime, fhour: int) -> str:
    q = {"dir": f"/gfs.{run:%Y%m%d}/{run:%H}/atmos", "file": f"gfs.t{run:%H}z.pgrb2.1p00.f{fhour:03d}",
         "var_UGRD": "on", "var_VGRD": "on", "lev_10_m_above_ground": "on"}
    return f"{NOMADS_URL}?{urllib.parse.urlencode(q)}"


def aws_urls(run: dt.datetime, fhour: int) -> tuple[str, str]:
    path = f"{AWS_URL}/gfs.{run:%Y%m%d}/{run:%H}/atmos/gfs.t{run:%H}z.pgrb2.1p00.f{fhour:03d}"
    return path, path + ".idx"


def byte_ranges_from_index(idx: str) -> list[tuple[int, Optional[int]]]:
    """Byte ranges of the 10 m U and V wind in a GFS .idx index file ("n:offset:d=…:VAR:level:…").
    Messages holding several fields share one offset; each range ends where the next
    offset starts (None = to the end of the file)."""
    rows = []
    for line in idx.splitlines():
        parts = line.split(":")
        if len(parts) >= 5 and parts[1].isdigit():
            rows.append((int(parts[1]), parts[3], parts[4]))
    offsets = sorted({r[0] for r in rows})
    wanted = sorted({off for off, var, lev in rows if var in ("UGRD", "VGRD") and lev == "10 m above ground"})
    if len(wanted) == 0:
        raise WindError("The GFS index doesn't list the 10 m wind.")
    out = []
    for off in wanted:
        later = [o for o in offsets if o > off]
        out.append((off, later[0] - 1 if later else None))
    return out


# ------------------------------------------------------------------- download
class WindClient:
    def __init__(self, nomads_base: Optional[str] = None, aws_base: Optional[str] = None,
                 timeout: float = TIMEOUT_S, ssl_context=None):
        self.nomads_base = nomads_base or os.environ.get("RBSB_WEATHER_WIND_NOMADS") or NOMADS_URL
        self.aws_base = aws_base or os.environ.get("RBSB_WEATHER_WIND_AWS") or AWS_URL
        self.timeout = timeout
        self._opener = build_opener(ssl_context)
        self.user_agent = f"RBSB-Weather/{__version__} (Created By Shane BlackbuRn)"

    def _get(self, url: str, headers: Optional[dict] = None, limit: int = MAX_BYTES) -> bytes:
        h = {"User-Agent": self.user_agent}
        h.update(headers or {})
        try:
            with self._opener.open(urllib.request.Request(url, headers=h), timeout=self.timeout) as resp:
                data = resp.read(limit + 1)
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            raise WindError(f"HTTP {code}") from None
        except Exception as e:
            reason = getattr(e, "reason", e)
            raise WindError(f"couldn't connect ({reason})") from None
        if len(data) > limit:
            raise WindError("the download was unexpectedly large")
        return data

    def fetch(self, now: Optional[dt.datetime] = None,
              cancelled: Optional[Callable[[], bool]] = None) -> tuple[bytes, dt.datetime, int, str]:
        """GRIB2 bytes of the newest available run's forecast closest to `now`.
        Returns (data, run, forecast hour, source)."""
        now = now or dt.datetime.now(_UTC)
        problems = []
        for run, fh in runs_to_try(now):
            for source in ("NOAA NOMADS", "NOAA on AWS"):
                if cancelled and cancelled():
                    raise WindError("cancelled")
                try:
                    data = self._fetch_nomads(run, fh) if source == "NOAA NOMADS" else self._fetch_aws(run, fh)
                    if not grib2.is_grib2(data):
                        raise WindError("the reply wasn't wind data")
                    log.info("wind: GFS %s run, +%d h, from %s (%d bytes)",
                             run.strftime("%Y-%m-%d %HZ"), fh, source, len(data))
                    return data, run, fh, source
                except WindError as e:
                    problems.append(f"{source} {run:%HZ %d %b} +{fh} h: {e}")
                    log.info("wind: %s", problems[-1])
        raise WindError("The world wind map couldn't be downloaded from NOAA ("
                        + "; ".join(problems[:2]) + ").")

    def _fetch_nomads(self, run: dt.datetime, fh: int) -> bytes:
        url = nomads_url(run, fh).replace(NOMADS_URL, self.nomads_base, 1)
        return self._get(url)

    def _fetch_aws(self, run: dt.datetime, fh: int) -> bytes:
        data_url, idx_url = aws_urls(run, fh)
        data_url, idx_url = (u.replace(AWS_URL, self.aws_base, 1) for u in (data_url, idx_url))
        idx = self._get(idx_url, limit=512 * 1024).decode("utf-8", "replace")
        parts = []
        for start, end in byte_ranges_from_index(idx):
            rng = f"bytes={start}-" + ("" if end is None else str(end))
            parts.append(self._get(data_url, {"Range": rng}))
        return b"".join(parts)


# ------------------------------------------------------------------- cache
class WindStore:
    """wind/gfs_wind10m.grib2 + wind/wind.json (run, forecast hour, when fetched, source)."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.data_path = self.dir / "gfs_wind10m.grib2"
        self.meta_path = self.dir / "wind.json"

    def meta(self) -> dict:
        try:
            d = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data: bytes, run: dt.datetime, fh: int, source: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".wind-", suffix=".tmp", dir=str(self.dir))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, self.data_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        from .storage import atomic_write_json
        atomic_write_json(self.meta_path, {"run": run.isoformat(), "fhour": fh, "fetched": time.time(),
                                           "source": source})

    def note_failure(self) -> None:
        from .storage import atomic_write_json
        m = self.meta()
        m["failed"] = time.time()
        try:
            atomic_write_json(self.meta_path, m)
        except OSError:
            pass

    def load(self) -> Optional[WindField]:
        m = self.meta()
        try:
            run = dt.datetime.fromisoformat(m["run"])
            return field_from_grib(self.data_path.read_bytes(), run)
        except (KeyError, ValueError, OSError, grib2.Grib2Error, WindError) as e:
            if self.data_path.exists():
                log.warning("saved wind map unusable: %s", e)
            return None

    def due(self, now: Optional[dt.datetime] = None) -> bool:
        """Should a new download be tried? When the forecast hour closest to now differs
        from the saved one (every 3 hours), but not within RETRY_S of a failure."""
        now = now or dt.datetime.now(_UTC)
        m = self.meta()
        failed = m.get("failed")
        if isinstance(failed, (int, float)) and 0 <= time.time() - failed < RETRY_S:
            return False
        try:
            run = dt.datetime.fromisoformat(m["run"])
            valid = run + dt.timedelta(hours=int(m["fhour"]))
        except (KeyError, ValueError, TypeError):
            return True
        if not self.data_path.exists():
            return True
        return abs((now - valid).total_seconds()) > 90 * 60 + 60


def update(store: WindStore, client: Optional[WindClient] = None, now: Optional[dt.datetime] = None,
           cancelled=None) -> tuple[Optional[WindField], str]:
    """Download if due. Returns (field to show, note): the new or saved field (None if
    there's none yet), and a note when a newer one couldn't be fetched. Raises WindError
    only when there's nothing at all to show."""
    if store.due(now):
        client = client or WindClient()
        try:
            data, run, fh, source = client.fetch(now, cancelled)
            fld = field_from_grib(data, run)        # validate before replacing the saved one
            store.save(data, run, fh, source)
            return fld, ""
        except (WindError, grib2.Grib2Error) as e:
            store.note_failure()
            saved = store.load()
            if saved is None:
                raise WindError(str(e)) from None
            log.info("wind: keeping the saved map (%s)", e)
            return saved, "A newer forecast couldn't be downloaded, so the saved one is shown."
    return store.load(), ""


# ------------------------------------------------------------------- colours
# Wind speed (m/s) -> colour, from calm blue through green and yellow to red and purple
SPEED_COLOURS = [
    (0.0, (52, 64, 158)), (2.0, (46, 106, 196)), (4.0, (38, 152, 196)), (6.0, (52, 170, 112)),
    (8.0, (92, 184, 64)), (10.0, (170, 196, 56)), (12.5, (222, 182, 54)), (15.0, (226, 128, 48)),
    (18.0, (206, 74, 64)), (22.0, (176, 46, 104)), (27.0, (150, 52, 168)), (34.0, (226, 176, 236)),
]


def colour_for(speed: float) -> tuple[int, int, int]:
    if speed <= SPEED_COLOURS[0][0]:
        return SPEED_COLOURS[0][1]
    for (s0, c0), (s1, c1) in zip(SPEED_COLOURS, SPEED_COLOURS[1:]):
        if speed <= s1:
            t = (speed - s0) / (s1 - s0)
            return tuple(int(round(a + (b - a) * t)) for a, b in zip(c0, c1))
    return SPEED_COLOURS[-1][1]


def speed_map(fld: WindField):
    """A QImage (equirectangular, west edge at -180°, north at the top) of wind speed colours,
    one pixel per grid point; the caller scales it smoothly."""
    from PyQt6.QtGui import QImage
    ni, nj = fld.ni, fld.nj
    shift = int(round(((-180.0 - fld.lon0) % 360.0) / fld.dlon)) % ni     # column of 180° W
    if _np is not None and not isinstance(fld.u, list):
        np = _np
        spd = np.sqrt(fld.u.astype(np.float32) ** 2 + fld.v.astype(np.float32) ** 2)
        spd = np.roll(spd, -shift, axis=1)
        xs = np.array([s for s, _ in SPEED_COLOURS], np.float32)
        out = np.empty((nj, ni, 4), np.uint8)
        for ch, k in ((2, 0), (1, 1), (0, 2)):                              # BGRA
            out[..., ch] = np.interp(spd, xs, np.array([c[k] for _, c in SPEED_COLOURS], np.float32)).astype(np.uint8)
        out[..., 3] = 255
        return QImage(out.tobytes(), ni, nj, ni * 4, QImage.Format.Format_ARGB32).copy()
    img = QImage(ni, nj, QImage.Format.Format_ARGB32)
    for j in range(nj):
        ru, rv = fld.u[j], fld.v[j]
        for i in range(ni):
            k = (i + shift) % ni
            r, g, b = colour_for(math.hypot(ru[k], rv[k]))
            img.setPixel(i, j, 0xFF000000 | (r << 16) | (g << 8) | b)
    return img
