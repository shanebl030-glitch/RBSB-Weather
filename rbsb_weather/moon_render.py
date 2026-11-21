"""High-resolution moon images lit for any phase.

Uses the bundled 2048 px near-side textures (assets/moon_albedo.jpg and
assets/moon_height.jpg, made by tools/make_moon_texture.py) and lights them
per pixel:

* Lommel–Seeliger reflectance (the real Moon's photometry, which is why a
  full moon looks evenly bright, not shaded like a ball), blended with a
  little Lambert so the terminator softens naturally;
* crater relief from the height map, so craters cast light and shadow along
  the terminator;
* faint, slightly blue earthshine on the night side (strongest at crescent);
* the sun direction from the real phase angle and bright-limb position
  angle, so the crescent tilt matches the sky;
* the view rotated 180° for the southern hemisphere, which is how the Moon
  looks from New Zealand.

numpy is used when it's installed (fast); otherwise a pure-Python path
produces the same image, just more slowly. Results are cached.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QTransform

ASSETS = Path(__file__).with_name("assets")
ALBEDO_FILE = ASSETS / "moon_albedo.jpg"
HEIGHT_FILE = ASSETS / "moon_height.jpg"
META_FILE = ASSETS / "moon_textures.json"     # describes which textures are installed
MAX_SIZE = 2048

try:                     # optional speed-up
    import numpy as _np
except Exception:        # pragma: no cover - depends on the system
    _np = None

_lock = threading.Lock()
_tex_cache: dict[int, tuple[bytes, bytes, int]] = {}
_img_cache: "OrderedDict[tuple, QImage]" = OrderedDict()
_IMG_CACHE_MAX = 40


class MoonTextureError(RuntimeError):
    pass


_meta_cache: Optional[dict] = None
DEFAULT_META = {"source": "procedural", "bump": 0.16, "tint": [1.0, 0.97, 0.92],
                "credit": ""}


def texture_meta() -> dict:
    """Which textures are installed: generated ('procedural') or NASA's CGI Moon Kit,
    plus how strongly to apply the relief and any colour tint."""
    global _meta_cache
    if _meta_cache is None:
        meta = dict(DEFAULT_META)
        try:
            import json
            with open(META_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                meta.update({k: data[k] for k in DEFAULT_META if k in data})
        except (OSError, ValueError):
            pass
        _meta_cache = meta
    return _meta_cache


def _textures(size: int) -> tuple[bytes, int, bytes, int]:
    """RGB albedo and grayscale height bytes scaled to `size` (cached)."""
    with _lock:
        hit = _tex_cache.get(size)
        if hit:
            return hit
    out = []
    for f, fmt in ((ALBEDO_FILE, QImage.Format.Format_RGB888),
                   (HEIGHT_FILE, QImage.Format.Format_Grayscale8)):
        img = QImage(str(f))
        if img.isNull():
            raise MoonTextureError(f"moon texture missing or unreadable: {f}")
        img = img.convertToFormat(fmt)
        if img.width() != size:
            img = img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        bpl = img.bytesPerLine()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        out.append((bytes(ptr), bpl))
    res = (out[0][0], out[0][1], out[1][0], out[1][1])
    with _lock:
        if len(_tex_cache) > 6:
            _tex_cache.pop(next(iter(_tex_cache)))
        _tex_cache[size] = res
    return res


def sun_vector(phase_angle: float, bright_limb: float) -> tuple[float, float, float]:
    """Unit vector to the Sun in image space (x right, y up, z towards viewer),
    for a north-up view with celestial east on the left."""
    i = math.radians(phase_angle)
    chi = math.radians(bright_limb)
    dx, dy = -math.sin(chi), math.cos(chi)
    return (math.sin(i) * dx, math.sin(i) * dy, math.cos(i))


def _params(phase_angle: float):
    illum = (1 + math.cos(math.radians(phase_angle))) / 2
    earth = 0.055 * (1 - illum) ** 1.5           # earthshine fades as the Moon fills
    exposure = 1.12 + 0.3 * (1 - illum)          # like a photo: a full moon needs less
    return illum, earth, exposure


GAMMA = 1 / 1.12


def _render_numpy(size, alb_b, abpl, hgt_b, bpl, s, earth, EXPOSURE, BUMP, tint):
    np = _np
    alb = (np.frombuffer(alb_b, np.uint8).reshape(size, abpl)[:, :size * 3]
           .reshape(size, size, 3).astype(np.float32) / 255)
    hgt = np.frombuffer(hgt_b, np.uint8).reshape(size, bpl)[:, :size].astype(np.float32) / 255
    c = (np.arange(size, dtype=np.float32) + 0.5) / size * 2 - 1
    X, Y = np.meshgrid(c, -c)
    r2 = X * X + Y * Y
    Z = np.sqrt(np.clip(1 - r2, 0, 1))
    gy, gx = np.gradient(hgt)
    gy = -gy                           # image rows go down; y goes up
    k = BUMP * size / 2 * Z           # slope per radius; fades out towards the limb
    nx, ny, nz = X - k * gx, Y - k * gy, Z
    inv = 1 / np.sqrt(nx * nx + ny * ny + nz * nz + 1e-12)
    nx, ny, nz = nx * inv, ny * inv, nz * inv
    mu0 = nx * s[0] + ny * s[1] + nz * s[2]
    mu = np.maximum(nz, 0.05)             # emission angle from the *bumped* normal, so
    lit = np.clip(mu0, 0, None)           # relief vanishes at full moon, as it does in reality
    shade = 0.88 * (2 * lit / (lit + mu)) + 0.12 * lit
    sh = np.clip(shade * EXPOSURE, 0, 1.6)
    r = np.clip(alb[..., 0] * (sh * tint[0] + earth * 0.85), 0, 1) ** GAMMA
    g = np.clip(alb[..., 1] * (sh * tint[1] + earth * 0.92), 0, 1) ** GAMMA
    b = np.clip(alb[..., 2] * (sh * tint[2] + earth * 1.05), 0, 1) ** GAMMA
    a = np.clip((1 - np.sqrt(r2)) * size / 2 + 0.5, 0, 1)    # anti-aliased limb
    out = np.empty((size, size, 4), np.uint8)               # BGRA (premultiplied)
    out[..., 0] = (b * a * 255).astype(np.uint8)
    out[..., 1] = (g * a * 255).astype(np.uint8)
    out[..., 2] = (r * a * 255).astype(np.uint8)
    out[..., 3] = (a * 255).astype(np.uint8)
    return out.tobytes()


def _render_python(size, alb_b, abpl, hgt_b, bpl, s, earth, EXPOSURE, BUMP, tint):
    out = bytearray(size * size * 4)
    sx, sy, sz = s
    kk = BUMP * size / 2
    half = size / 2
    for j in range(size):
        y = 1 - (j + 0.5) / size * 2
        row = j * bpl
        arow = j * abpl
        up = max(j - 1, 0) * bpl
        dn = min(j + 1, size - 1) * bpl
        o = j * size * 4
        yy = y * y
        lim = 1 + 2.0 / size
        if yy > lim * lim:
            continue
        xr = math.sqrt(max(0.0, lim * lim - yy))
        i0 = max(0, int((1 - xr) / 2 * size) - 1)
        i1 = min(size, int((1 + xr) / 2 * size) + 2)
        for i in range(i0, i1):
            x = (i + 0.5) / size * 2 - 1
            r2 = x * x + yy
            rr = math.sqrt(r2)
            a = (1 - rr) * half + 0.5          # anti-aliased limb (includes the
            if a <= 0:                          # half-covered pixels just outside r=1)
                continue
            if a > 1:
                a = 1.0
            z = math.sqrt(1 - r2) if r2 < 1 else 0.0
            gx = (hgt_b[row + min(i + 1, size - 1)] - hgt_b[row + max(i - 1, 0)]) / 510.0
            gy = (hgt_b[up + i] - hgt_b[dn + i]) / 510.0
            k = kk * z
            nx, ny, nz = x - k * gx, y - k * gy, z
            inv = 1 / math.sqrt(nx * nx + ny * ny + nz * nz + 1e-12)
            mu0 = (nx * sx + ny * sy + nz * sz) * inv
            ai = arow + i * 3
            ar, ag, ab = alb_b[ai] / 255.0, alb_b[ai + 1] / 255.0, alb_b[ai + 2] / 255.0
            if mu0 > 0:
                mu = nz * inv
                if mu < 0.05:
                    mu = 0.05
                shade = (0.88 * (2 * mu0 / (mu0 + mu)) + 0.12 * mu0) * EXPOSURE
                if shade > 1.6:
                    shade = 1.6
            else:
                shade = 0.0
            r = min(1.0, ar * (shade * tint[0] + earth * 0.85)) ** GAMMA
            g = min(1.0, ag * (shade * tint[1] + earth * 0.92)) ** GAMMA
            b = min(1.0, ab * (shade * tint[2] + earth * 1.05)) ** GAMMA
            p = o + i * 4
            out[p] = int(b * a * 255)
            out[p + 1] = int(g * a * 255)
            out[p + 2] = int(r * a * 255)
            out[p + 3] = int(a * 255)
    return bytes(out)


def render_moon(size: int, phase_angle: float, bright_limb: float, southern: bool = False,
                use_numpy: Optional[bool] = None, rotation: Optional[float] = None) -> QImage:
    """A size x size image of the Moon at the given phase (transparent outside the disc).

    rotation: degrees to turn the north-up view clockwise (the parallactic angle from
    moon.sky_view), so the picture matches the observer's sky. If omitted, a simple
    hemisphere view is used: north up, or turned 180 degrees when `southern`."""
    size = int(max(8, min(MAX_SIZE, size)))
    rot = (180.0 if southern else 0.0) if rotation is None else float(rotation) % 360
    rot = round(rot) % 360                                    # 1 degree steps (cache-friendly)
    key = (size, round(phase_angle, 1), round(bright_limb) % 360, rot,
           use_numpy if use_numpy is not None else _np is not None)
    with _lock:
        hit = _img_cache.get(key)
        if hit is not None:
            _img_cache.move_to_end(key)
            return hit
    alb, abpl, hgt, bpl = _textures(size)
    s = sun_vector(phase_angle, bright_limb)
    _illum, earth, exposure = _params(phase_angle)
    meta = texture_meta()
    numpy_ok = _np is not None if use_numpy is None else (use_numpy and _np is not None)
    data = (_render_numpy if numpy_ok else _render_python)(
        size, alb, abpl, hgt, bpl, s, earth, exposure, float(meta["bump"]), tuple(meta["tint"]))
    img = QImage(data, size, size, size * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
    if rot % 90 == 0:
        if rot:
            img = img.transformed(QTransform().rotate(rot))             # exact, lossless
    else:
        big = img.transformed(QTransform().rotate(rot), Qt.TransformationMode.SmoothTransformation)
        ox, oy = (big.width() - size) // 2, (big.height() - size) // 2   # re-centre the disc
        img = big.copy(ox, oy, size, size)
    with _lock:
        _img_cache[key] = img
        while len(_img_cache) > _IMG_CACHE_MAX:
            _img_cache.popitem(last=False)
    return img


def has_numpy() -> bool:
    return _np is not None
