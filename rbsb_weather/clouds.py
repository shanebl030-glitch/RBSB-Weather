"""Live clouds for the Earth Flat and Earth Globe tabs.

Source: Live Cloud Maps by Matt Eason (https://github.com/matteason/live-cloud-maps),
CC0 - a near real-time global cloud map built from EUMETSAT geostationary satellite
images, updated every 3 hours. Required attribution: "Contains modified EUMETSAT data."

* Downloaded in the background (never on the GUI thread) through the same connection
  code as the weather (IPv4/IPv6 racing, handshake timeout, one retry).
* Checked at most once an hour with a conditional request (If-Modified-Since /
  If-None-Match), so an unchanged map costs a few hundred bytes. After a failure it
  waits 15 minutes before trying again.
* Cached on disk; offline, the last map is used. A download that isn't a valid
  2:1 cloud map never replaces the cached one.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import email.utils
import json
import logging
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from . import __version__
from .net import build_opener, clear_last_connection, last_connection, mark_bad

log = logging.getLogger(__name__)

CLOUD_URL = "https://clouds.matteason.co.uk/images/2048x1024/clouds.jpg"
PROJECT_URL = "https://github.com/matteason/live-cloud-maps"
CREDIT = "Live clouds: contains modified EUMETSAT data, via Live Cloud Maps by Matt Eason (CC0)"
CHECK_EVERY_S = 3600          # the source updates every 3 hours; a 304 check is tiny
RETRY_AFTER_FAIL_S = 900
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 30.0
MIN_WIDTH = 256


class CloudError(Exception):
    pass


class CloudStore:
    """clouds.jpg + clouds.json (when fetched, Last-Modified, ETag, last attempt)."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.image_path = self.dir / "clouds.jpg"
        self.meta_path = self.dir / "clouds.json"

    def meta(self) -> dict:
        try:
            d = json.loads(self.meta_path.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write_meta(self, d: dict) -> None:
        from .storage import atomic_write_json
        atomic_write_json(self.meta_path, d)

    def has_image(self) -> bool:
        return self.image_path.is_file()

    def due(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        m = self.meta()
        if not self.has_image():
            return now - _num(m.get("attempted")) >= RETRY_AFTER_FAIL_S or not m.get("failed")
        if m.get("failed"):
            return now - _num(m.get("attempted")) >= RETRY_AFTER_FAIL_S
        return now - _num(m.get("checked")) >= CHECK_EVERY_S

    def image_time(self) -> Optional[dt.datetime]:
        """When the satellite map was made (Last-Modified), else when it was downloaded."""
        m = self.meta()
        lm = m.get("last_modified")
        if isinstance(lm, str):
            try:
                return email.utils.parsedate_to_datetime(lm).astimezone(dt.timezone.utc)
            except (TypeError, ValueError):
                pass
        if self.has_image() and isinstance(m.get("fetched"), (int, float)):
            return dt.datetime.fromtimestamp(m["fetched"], dt.timezone.utc)
        return None

    def save(self, data: bytes, last_modified: Optional[str], etag: Optional[str]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.image_path.with_suffix(".jpg.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.image_path)
        now = time.time()
        self._write_meta({"fetched": now, "checked": now, "attempted": now, "failed": False,
                          "last_modified": last_modified, "etag": etag, "bytes": len(data)})

    def mark_checked(self) -> None:
        m = self.meta()
        now = time.time()
        m.update(checked=now, attempted=now, failed=False)
        self._write_meta(m)

    def mark_failed(self, reason: str) -> None:
        m = self.meta()
        m.update(attempted=time.time(), failed=True, error=reason[:300])
        self._write_meta(m)

    def load(self):
        """The cached cloud map as a QImage, or None (missing or unreadable)."""
        from PyQt6.QtGui import QImage
        if not self.has_image():
            return None
        img = QImage(str(self.image_path))
        if img.isNull() or not _valid_size(img.width(), img.height()):
            log.warning("cached cloud map is unreadable; ignoring it")
            return None
        return img


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _valid_size(w: int, h: int) -> bool:
    return w >= MIN_WIDTH and h > 0 and abs(w / h - 2.0) < 0.02


def validate(data: bytes):
    """Decode a downloaded cloud map; raise CloudError unless it's a 2:1 image."""
    from PyQt6.QtGui import QImage
    img = QImage()
    if not data or not img.loadFromData(data):
        raise CloudError("the cloud map download was not a readable image")
    if not _valid_size(img.width(), img.height()):
        raise CloudError(f"the cloud map has an unexpected size ({img.width()}x{img.height()})")
    return img


def update(store: CloudStore, url: str = None, ssl_context=None, timeout: float = TIMEOUT_S,
           opener=None) -> str:
    """Check for a newer cloud map and save it. Returns "updated", "unchanged" or
    raises CloudError (the cached map, if any, is kept)."""
    url = url or CLOUD_URL
    opener = opener or build_opener(ssl_context)
    meta = store.meta() if store.has_image() else {}
    headers = {"User-Agent": f"RBSB-Weather/{__version__} (Created By Shane BlackbuRn)",
               "Accept": "image/jpeg,image/*"}
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    last_err = None
    for attempt in (1, 2):
        clear_last_connection()
        try:
            req = urllib.request.Request(url, headers=headers)
            t0 = time.monotonic()
            with opener.open(req, timeout=timeout) as resp:
                data = resp.read(MAX_BYTES + 1)
                lm, etag = resp.headers.get("Last-Modified"), resp.headers.get("ETag")
            if len(data) > MAX_BYTES:
                raise CloudError("the cloud map download was unexpectedly large")
            validate(data)
            store.save(data, lm, etag)
            log.info("cloud map updated: %d bytes in %d ms", len(data), (time.monotonic() - t0) * 1000)
            return "updated"
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            if code == 304:
                store.mark_checked()
                return "unchanged"
            last_err = CloudError(f"the cloud map server returned HTTP {code}")
            break
        except CloudError as e:
            last_err = e
            break
        except (socket.timeout, TimeoutError, ConnectionError, ssl.SSLError, urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            last_err = CloudError(f"could not download the cloud map ({reason})")
            retryable = not isinstance(reason, ssl.SSLCertVerificationError) and not (
                isinstance(reason, socket.gaierror))
            info = last_connection()
            if attempt == 1 and retryable:
                if info:
                    mark_bad(info["address"], info["port"], info["family_num"])
                log.warning("%s; retrying once", last_err)
                continue
            break
    store.mark_failed(str(last_err))
    raise last_err


# --------------------------------------------------------------- compositing
_alpha_cache: dict = {}


def cloud_alpha(img, w: int, h: int):
    """The cloud map as an Alpha8 QImage of size w x h. Thin haze and sensor noise
    are trimmed and thick cloud made opaque (numpy if available, else as-is)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage
    key = (img.cacheKey(), w, h)
    hit = _alpha_cache.get(key)
    if hit is not None:
        return hit
    g = img.convertToFormat(QImage.Format.Format_Grayscale8)
    gw, gh, bpl = g.width(), g.height(), g.bytesPerLine()
    ptr = g.constBits()
    ptr.setsize(g.sizeInBytes())
    raw = bytes(ptr)
    try:
        import numpy as np
        a = np.frombuffer(raw, np.uint8).reshape(gh, bpl)[:, :gw].astype(np.float32)
        a = np.clip((a - 18.0) * (255.0 / 200.0), 0, 255).astype(np.uint8)
        raw, bpl = a.tobytes(), gw
    except ImportError:                                 # pragma: no cover - numpy is recommended
        pass
    alpha = QImage(raw, gw, gh, bpl, QImage.Format.Format_Alpha8).copy()
    if (gw, gh) != (w, h):
        alpha = alpha.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    _alpha_cache.clear()                                # keep just the latest
    _alpha_cache[key] = alpha
    return alpha


def colour_layer(alpha, colour):
    """A W x H image of `colour` shaped by the Alpha8 mask `alpha`."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QImage, QPainter
    out = QImage(alpha.width(), alpha.height(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(colour)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(QRect(0, 0, alpha.width(), alpha.height()), alpha)
    p.end()
    return out


def note(store: CloudStore, img, error: str = "", now: Optional[dt.datetime] = None) -> str:
    """One line for the Earth tabs saying how fresh the clouds are."""
    if img is None:
        if error:
            return "Live clouds are unavailable right now, so the Earth is shown without them."
        return "Live clouds will appear once they've downloaded."
    when = store.image_time()
    if when is None:
        return "Live clouds shown."
    now = now or dt.datetime.now(dt.timezone.utc)
    local = when.astimezone()
    same_day = local.date() == now.astimezone().date()
    from .units import fmt_clock
    stamp = fmt_clock(local, day=not same_day)
    text = f"Clouds: satellite map from {stamp} (your time)"
    if (now - when).total_seconds() > 6 * 3600:
        text += " – couldn't get a newer one, showing the last" if error else " – the newest available"
    return text + "."
