"""Orthographic globe: projection maths and rendering from the day/night map.

The globe is drawn by inverse-projecting every pixel of the disc to a
latitude/longitude and sampling the equirectangular day/night composite
(earth.compose_day_night), so the globe always shows exactly the same
day/night state as the flat map. A gentle limb darkening gives depth; the
atmosphere glow and stars are painted by the widget.

numpy is used when installed (a few tens of ms per frame, smooth dragging);
otherwise a pure-Python path renders a smaller globe that is scaled up.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
from typing import Optional

try:
    import numpy as _np
except Exception:          # pragma: no cover - depends on the system
    _np = None

_R = math.radians
_D = math.degrees

LIMB = 0.25                # limb darkening strength (0 = flat disc)
PY_MAX_SIZE = 320          # pure-Python path renders at most this size, then scales up


def has_numpy() -> bool:
    return _np is not None


def project(lat: float, lon: float, c_lat: float, c_lon: float) -> tuple[float, float, bool]:
    """Orthographic projection of (lat, lon) for a globe centred on (c_lat, c_lon).
    Returns (x, y, visible) with x right, y up, both in -1..1 on the disc."""
    p, l, p0, l0 = _R(lat), _R(lon), _R(c_lat), _R(c_lon)
    cos_c = math.sin(p0) * math.sin(p) + math.cos(p0) * math.cos(p) * math.cos(l - l0)
    x = math.cos(p) * math.sin(l - l0)
    y = math.cos(p0) * math.sin(p) - math.sin(p0) * math.cos(p) * math.cos(l - l0)
    return x, y, cos_c > 0


def inverse(x: float, y: float, c_lat: float, c_lon: float) -> Optional[tuple[float, float]]:
    """Latitude/longitude under disc point (x, y) (y up), or None outside the disc."""
    rho = math.hypot(x, y)
    if rho > 1:
        return None
    if rho < 1e-12:
        return c_lat, c_lon
    c = math.asin(rho)
    p0, l0 = _R(c_lat), _R(c_lon)
    lat = math.asin(math.cos(c) * math.sin(p0) + y * math.sin(c) * math.cos(p0) / rho)
    lon = l0 + math.atan2(x * math.sin(c), rho * math.cos(c) * math.cos(p0) - y * math.sin(c) * math.sin(p0))
    return _D(lat), ((_D(lon) + 180) % 360) - 180


def _source_bytes(src):
    """(bytes, width, height, bytes_per_line) of an ARGB32 QImage."""
    from PyQt6.QtGui import QImage
    if src.format() != QImage.Format.Format_ARGB32_Premultiplied:
        src = src.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    ptr = src.constBits()
    ptr.setsize(src.sizeInBytes())
    return bytes(ptr), src.width(), src.height(), src.bytesPerLine()


class GlobeRenderer:
    """Keeps the current day/night map ready for fast repeated globe renders."""

    def __init__(self):
        self._src = None              # numpy array (H, W, 4) or raw bytes
        self._raw = b""
        self._w = self._h = self._bpl = 0
        self._grid_cache: dict[int, tuple] = {}

    def set_source(self, img) -> None:
        if img is None:
            self._src = None
            return
        data, w, h, bpl = _source_bytes(img)
        self._w, self._h, self._bpl = w, h, bpl
        self._raw = data                                  # used by the pure-Python path
        if _np is not None:
            self._src = _np.frombuffer(data, _np.uint8).reshape(h, bpl)[:, :w * 4].reshape(h, w, 4)
        else:
            self._src = data

    @property
    def ready(self) -> bool:
        return self._src is not None

    # ------------------------------------------------------------- render
    def render(self, size: int, c_lat: float, c_lon: float, use_numpy: Optional[bool] = None):
        """QImage (size x size, transparent outside the disc) of the globe."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QImage
        size = max(16, int(size))
        if self._src is None:
            raise RuntimeError("no Earth map yet")
        np_ok = (_np is not None) if use_numpy is None else (use_numpy and _np is not None)
        if np_ok:
            data = self._render_numpy(size, c_lat, c_lon)
            return QImage(data, size, size, size * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        small = min(size, PY_MAX_SIZE)
        data = self._render_python(small, c_lat, c_lon)
        img = QImage(data, small, small, small * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        if small != size:
            img = img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        return img

    def _grid(self, size: int):
        g = self._grid_cache.get(size)
        if g is None:
            np = _np
            c = (np.arange(size, dtype=np.float64) + 0.5) / size * 2 - 1
            X, Y = np.meshgrid(c, -c)
            rho = np.minimum(np.sqrt(X * X + Y * Y), 1.0 + 4.0 / size)
            cc = np.arcsin(np.clip(rho, 0, 1))
            alpha = np.clip((1 - rho) * size / 2 + 0.5, 0, 1)        # anti-aliased edge
            shade = 1 - LIMB * (1 - np.sqrt(np.clip(1 - rho * rho, 0, 1)))
            rho = np.minimum(rho, 1.0)                               # project edge pixels onto the rim
            rho_s = np.where(rho < 1e-12, 1.0, rho)
            f32 = np.float32
            # float32 halves the memory; at most 3 sizes are kept (about 30 MB at 1300 px)
            g = (X.astype(f32), Y.astype(f32), rho.astype(f32), rho_s.astype(f32),
                 np.sin(cc).astype(f32), np.cos(cc).astype(f32), (alpha * 255).astype(np.uint8),
                 (shade * alpha).astype(f32))
            if len(self._grid_cache) >= 3:
                self._grid_cache.pop(next(iter(self._grid_cache)))
            self._grid_cache[size] = g
        return g

    def _render_numpy(self, size, c_lat, c_lon) -> bytes:
        np = _np
        X, Y, rho, rho_s, sinc, cosc, alpha8, k = self._grid(size)
        p0, l0 = _R(c_lat), _R(c_lon)
        lat = np.arcsin(np.clip(cosc * math.sin(p0) + Y * sinc * math.cos(p0) / rho_s, -1, 1))
        lon = l0 + np.arctan2(X * sinc, rho_s * cosc * math.cos(p0) - Y * sinc * math.sin(p0))
        u = ((np.degrees(lon) + 180.0) % 360.0) / 360.0 * self._w
        v = (90.0 - np.degrees(lat)) / 180.0 * self._h
        ui = np.clip(u.astype(np.int64), 0, self._w - 1)
        vi = np.clip(v.astype(np.int64), 0, self._h - 1)
        px = self._src[vi, ui].astype(np.float32)                    # BGRA
        # alpha already covers the half-covered edge pixels just outside rho = 1
        # (their position is projected as if on the rim), matching the pure-Python path
        out = np.empty((size, size, 4), np.uint8)
        out[..., :3] = np.clip(px[..., :3] * k[..., None], 0, 255).astype(np.uint8)
        out[..., 3] = alpha8
        return out.tobytes()

    def _render_python(self, size, c_lat, c_lon) -> bytes:
        out = bytearray(size * size * 4)
        src, W, H, bpl = self._raw, self._w, self._h, self._bpl
        p0, l0 = _R(c_lat), _R(c_lon)
        sp0, cp0 = math.sin(p0), math.cos(p0)
        asin, atan2, sqrt, deg = math.asin, math.atan2, math.sqrt, _D
        half = size / 2
        for j in range(size):
            y = 1 - (j + 0.5) / size * 2
            for i in range(size):
                x = (i + 0.5) / size * 2 - 1
                r2 = x * x + y * y
                rho = sqrt(r2)
                a = (1 - rho) * half + 0.5
                if a <= 0:
                    continue
                if a > 1:
                    a = 1.0
                if rho > 1:
                    rho = 1.0
                if rho < 1e-12:
                    lat, lon = c_lat, c_lon
                    z = 1.0
                else:
                    sc = rho
                    cc = sqrt(max(0.0, 1 - rho * rho))
                    z = cc
                    s = cc * sp0 + y * sc * cp0 / rho
                    lat = deg(asin(-1.0 if s < -1 else 1.0 if s > 1 else s))
                    lon = deg(l0 + atan2(x * sc, rho * cc * cp0 - y * sc * sp0))
                ui = int(((lon + 180.0) % 360.0) / 360.0 * W)
                vi = int((90.0 - lat) / 180.0 * H)
                ui = W - 1 if ui >= W else ui
                vi = H - 1 if vi >= H else (0 if vi < 0 else vi)
                k = (1 - LIMB * (1 - z)) * a
                sp = vi * bpl + ui * 4
                p = (j * size + i) * 4
                out[p] = int(src[sp] * k)
                out[p + 1] = int(src[sp + 1] * k)
                out[p + 2] = int(src[sp + 2] * k)
                out[p + 3] = int(255 * a)
        return bytes(out)
