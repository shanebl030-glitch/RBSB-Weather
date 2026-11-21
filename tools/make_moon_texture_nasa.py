#!/usr/bin/env python3
"""Build RBSB-Weather's moon textures from NASA's CGI Moon Kit (build-time tool).

Source data (public domain, NASA's Scientific Visualization Studio):
    https://svs.gsfc.nasa.gov/4720
  * colour map  : lroc_color_16bit_srgb_4k.tif  (or _8k / _16k; equirectangular,
                  centred on 0° longitude, sRGB)
  * height map  : ldem_16_uint.tif  (16 px/degree, unsigned 16-bit, half-metres)

Output (replaces the generated textures; the app picks them up automatically):
    rbsb_weather/assets/moon_albedo.jpg   near-side colour, orthographic, north up
    rbsb_weather/assets/moon_height.jpg   crater-scale relief (large slopes removed)
    rbsb_weather/assets/moon_textures.json

Usage:
    python3 tools/make_moon_texture_nasa.py COLOUR.tif HEIGHT.tif [--size 2048] [--exaggeration 3]

Needs numpy, tifffile and imagecodecs (pip). Not needed at runtime.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "rbsb_weather" / "assets"
MOON_RADIUS_M = 1737400.0
CREDIT = ("Moon imagery: NASA's Scientific Visualization Studio, CGI Moon Kit "
          "(LRO LROC WAC and LOLA data)")


def load(path: str) -> np.ndarray:
    import tifffile
    arr = tifffile.imread(path)
    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)           # planar -> interleaved
    return arr


def to_unit_float(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.uint16:
        return arr.astype(np.float32) / 65535.0
    if arr.dtype == np.uint8:
        return arr.astype(np.float32) / 255.0
    a = arr.astype(np.float32)
    return np.clip(a, 0, 1)


def ortho_grid(size: int):
    c = (np.arange(size, dtype=np.float64) + 0.5) / size * 2 - 1
    X, Y = np.meshgrid(c, -c)                     # y up
    R2 = X * X + Y * Y
    inside = R2 <= 1.0
    Z = np.sqrt(np.clip(1 - R2, 0, 1))
    lat = np.degrees(np.arcsin(np.clip(Y, -1, 1)))
    lon = np.degrees(np.arctan2(X, Z))            # east (positive) to the right, as in photos
    return lat, lon, inside


def sample(eq: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Bilinear sample of an equirectangular map (lon -180..180 centred on 0, lat 90..-90)."""
    h, w = eq.shape[:2]
    u = (lon + 180.0) / 360.0 * w - 0.5
    v = (90.0 - lat) / 180.0 * h - 0.5
    u0 = np.floor(u).astype(int); v0 = np.floor(v).astype(int)
    fu = (u - u0)[..., None] if eq.ndim == 3 else (u - u0)
    fv = (v - v0)[..., None] if eq.ndim == 3 else (v - v0)
    u0 %= w; u1 = (u0 + 1) % w
    v0 = np.clip(v0, 0, h - 1); v1 = np.clip(v0 + 1, 0, h - 1)
    a, b, c, d = eq[v0, u0], eq[v0, u1], eq[v1, u0], eq[v1, u1]
    return (a * (1 - fu) + b * fu) * (1 - fv) + (c * (1 - fu) + d * fu) * fv


def box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Fast separable box blur (applied 3x ~ Gaussian)."""
    out = a.astype(np.float64)
    for _ in range(3):
        for axis in (0, 1):
            pad = [(0, 0), (0, 0)]
            pad[axis] = (r + 1, r)
            p = np.pad(out, pad, mode="edge")
            cs = np.cumsum(p, axis=axis)
            hi = np.take(cs, np.arange(2 * r + 1, cs.shape[axis]), axis=axis)
            lo = np.take(cs, np.arange(0, cs.shape[axis] - 2 * r - 1), axis=axis)
            out = (hi - lo) / (2 * r + 1)
    return out


def save_jpeg(arr: np.ndarray, path: Path, quality: int = 92) -> None:
    from PyQt6.QtGui import QImage
    data = np.ascontiguousarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8))
    hh, ww = data.shape[:2]
    if data.ndim == 3:
        img = QImage(data.data, ww, hh, ww * 3, QImage.Format.Format_RGB888).copy()
    else:
        img = QImage(data.data, ww, hh, ww, QImage.Format.Format_Grayscale8).copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path), "JPG", quality):
        raise SystemExit(f"could not write {path}")
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("colour")
    ap.add_argument("height")
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--exaggeration", type=float, default=3.0,
                    help="relief exaggeration so craters read clearly at small sizes")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    out = Path(a.out)

    lat, lon, inside = ortho_grid(a.size)

    print("colour map…")
    col = to_unit_float(load(a.colour))
    if col.ndim == 2:
        col = np.repeat(col[..., None], 3, axis=2)
    col = col[..., :3]
    albedo = sample(col, lat, lon)
    albedo[~inside] = 0

    print("height map…")
    dem = load(a.height).astype(np.float64)
    if dem.ndim == 3:
        dem = dem[..., 0]
    metres = dem * 0.5 if load_is_uint(a.height) else dem * 1000.0   # uint: half-metres, float: km
    hgt = sample(metres, lat, lon)
    # keep crater-scale relief only: large slopes would tilt the whole lighting
    blur_r = max(2, a.size // 170)
    hp = hgt - box_blur(hgt, blur_r)
    hp[~inside] = 0
    span = float(np.percentile(np.abs(hp[inside]), 99.5)) or 1.0
    c = 0.45 / span                                 # metres -> stored units around 0.5
    stored = np.clip(0.5 + hp * c, 0, 1)
    stored[~inside] = 0.5
    # renderer: slope = k * grad, k = bump * size/2 ; physical slope = dh/dx.
    # grad(stored) per pixel = c * dh/dx * (2R/size)  =>  bump = exaggeration / (c * R)
    bump = a.exaggeration / (c * MOON_RADIUS_M)

    save_jpeg(albedo, out / "moon_albedo.jpg", 93)
    save_jpeg(stored, out / "moon_height.jpg", 95)
    meta = {"source": "nasa-cgi-moon-kit", "bump": round(bump, 6), "tint": [1.0, 1.0, 1.0],
            "credit": CREDIT, "inputs": [Path(a.colour).name, Path(a.height).name],
            "size": a.size, "relief_span_m": round(span, 1), "exaggeration": a.exaggeration}
    (out / "moon_textures.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("wrote", out / "moon_textures.json", meta)
    return 0


def load_is_uint(path: str) -> bool:
    import tifffile
    with tifffile.TiffFile(path) as t:
        return t.pages[0].dtype.kind == "u"


if __name__ == "__main__":
    sys.exit(main())
