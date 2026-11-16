#!/usr/bin/env python3
"""Generate WeatherDesk's high-resolution moon textures (build-time tool).

Creates an orthographic view of the Moon's near side, north up, as seen from
the northern hemisphere:

  weatherdesk/assets/moon_albedo.jpg  – surface brightness (2048 x 2048)
  weatherdesk/assets/moon_height.jpg  – relief (craters/rims) for terminator shading

The major features are placed at their real selenographic coordinates: the
maria (Imbrium, Serenitatis, Tranquillitatis, Crisium, Fecunditatis,
Nectaris, Nubium, Humorum, Frigoris, Procellarum, ...), the dark crater
floors of Plato and Grimaldi, and the bright ray craters Tycho, Copernicus,
Kepler and Aristarchus. Thousands of smaller craters follow a power-law size
distribution (fewer on the younger maria). Everything is procedural and
seeded, so the output is reproducible and contains no third-party imagery.

Needs numpy and PyQt6 (to write the JPEGs). Not needed at runtime.

    python3 tools/make_moon_texture.py [size]

Created By Shane BlackbuRn
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
OUT = Path(__file__).resolve().parents[1] / "weatherdesk" / "assets"
rng = np.random.default_rng(20261115)

# ---------------------------------------------------------------- geometry
c = (np.arange(SIZE) + 0.5) / SIZE * 2 - 1
X, Y = np.meshgrid(c, -c)                    # y up
R2 = X * X + Y * Y
inside = R2 <= 1.0
Z = np.sqrt(np.clip(1 - R2, 0, 1))
LAT = np.arcsin(np.clip(Y, -1, 1))
LON = np.arctan2(X, Z)
# unit vectors on the sphere (for 3D noise and angular distances)
PX, PY, PZ = X, Y, Z


def unit(lat_deg, lon_deg):
    la, lo = math.radians(lat_deg), math.radians(lon_deg)
    return math.cos(la) * math.sin(lo), math.sin(la), math.cos(la) * math.cos(lo)


def ang_dist(lat_deg, lon_deg):
    ux, uy, uz = unit(lat_deg, lon_deg)
    return np.degrees(np.arccos(np.clip(PX * ux + PY * uy + PZ * uz, -1, 1)))


# ------------------------------------------------------------- 3D value noise
def _lattice(shape_seed):
    g = np.random.default_rng(shape_seed)
    return g.random((64, 64, 64)).astype(np.float32)


def noise3(freq, seed):
    lat = _lattice(seed)
    x = (PX + 1.3) * freq
    y = (PY + 1.7) * freq
    z = (PZ + 1.1) * freq
    xi, yi, zi = np.floor(x).astype(int), np.floor(y).astype(int), np.floor(z).astype(int)
    xf, yf, zf = x - xi, y - yi, z - zi
    u = xf * xf * (3 - 2 * xf); v = yf * yf * (3 - 2 * yf); w = zf * zf * (3 - 2 * zf)
    def L(a, b, cc):
        return lat[(xi + a) % 64, (yi + b) % 64, (zi + cc) % 64]
    x00 = L(0, 0, 0) * (1 - u) + L(1, 0, 0) * u
    x10 = L(0, 1, 0) * (1 - u) + L(1, 1, 0) * u
    x01 = L(0, 0, 1) * (1 - u) + L(1, 0, 1) * u
    x11 = L(0, 1, 1) * (1 - u) + L(1, 1, 1) * u
    y0 = x00 * (1 - v) + x10 * v
    y1 = x01 * (1 - v) + x11 * v
    return (y0 * (1 - w) + y1 * w) * 2 - 1


def fbm(base, octaves, seed):
    total = np.zeros_like(X, dtype=np.float32)
    amp, f, norm = 1.0, base, 0.0
    for o in range(octaves):
        total += amp * noise3(f, seed + o)
        norm += amp
        amp *= 0.55
        f *= 2.03
    return total / norm


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


print("noise…")
n_low = fbm(3.0, 5, 10)
n_mid = fbm(9.0, 5, 30)
n_fine = fbm(40.0, 4, 50)

# ------------------------------------------------------------------- maria
# (lat, lon, radius_deg, darkness 0..1)
MARIA = [
    (32.8, -15.6, 17.5, 1.0), (36, -25, 9, 1.0), (26, -5, 8, 0.95),          # Imbrium
    (28.0, 17.5, 10.5, 0.85),                                                 # Serenitatis
    (8.5, 31.4, 11, 0.95), (14, 25, 6, 0.95), (3, 38, 7, 0.9),                 # Tranquillitatis
    (17.0, 59.1, 8.5, 1.0),                                                   # Crisium
    (-7.8, 51.3, 10, 0.85), (-2, 55, 6, 0.85),                                # Fecunditatis
    (-15.2, 35.5, 5.8, 0.85),                                                 # Nectaris
    (-21.3, -16.6, 10.5, 0.8),                                                # Nubium
    (-24.4, -38.6, 6.5, 0.9),                                                 # Humorum
    (-10.0, -23.0, 6, 0.8),                                                   # Cognitum
    (7.5, -30.9, 8, 0.85),                                                    # Insularum
    (13.3, 3.6, 4.2, 0.85), (2.0, 1.0, 4.0, 0.75),                            # Vaporum, Sinus Medii
    (20, -55, 12, 1.0), (5, -55, 12, 0.95), (32, -52, 10, 0.95),              # Procellarum
    (-5, -45, 8, 0.9), (12, -65, 10, 0.95), (42, -58, 7, 0.9), (-15, -50, 6, 0.85),
    (25, -40, 9, 0.95), (45, -40, 6, 0.85),
    (21, 86, 5, 0.6), (-2, 85, 5, 0.6),                                       # Marginis/Smythii (limb)
]
FRIGORIS = [(56 + 3 * math.sin(lo / 9.0), lo, 4.6, 0.7) for lo in range(-45, 46, 7)]

# connecting lobes so the maria merge the way they do on the real Moon
LINKS = [(22, 5, 6, 0.9), (18, 22, 7, 0.9), (-2, 45, 6, 0.85), (-8, 40, 5, 0.85),
         (25, -32, 9, 0.95), (12, -40, 8, 0.95), (-14, -28, 6, 0.85), (-18, -32, 5, 0.85),
         (40, -10, 7, 0.9), (48, -25, 5, 0.8), (-30, -20, 5, 0.7), (5, 18, 5, 0.85)]
# domain warp (in degrees) gives irregular, coastline-like mare boundaries
warp = 7.0 * fbm(2.2, 4, 90) + 3.0 * fbm(7.0, 4, 110) + 1.0 * n_fine
field = np.full_like(X, float(len(MARIA + FRIGORIS + LINKS) * 0) + 1e-9, dtype=np.float64)
tone_w = np.zeros_like(X, dtype=np.float32)
wsum = np.full_like(X, 1e-6, dtype=np.float32)
for i, (lat_, lon_, r, dk) in enumerate(MARIA + FRIGORIS + LINKS):
    d = np.maximum(ang_dist(lat_, lon_) + warp * (0.22 + r / 45.0), 0)
    f = np.exp(-(d / r) ** 2) * dk
    field += np.exp(14.0 * f)                             # smooth maximum (log-sum-exp)
    tone_w += f * ((i * 0.618) % 1.0)
    wsum += f
tone = tone_w / wsum                                     # smooth, seam-free tone variation
field = np.log(field) / 14.0
edge_noise = 0.5 * n_low + 0.3 * n_mid + 0.2 * n_fine
field = field + 0.06 * edge_noise
# maria cover roughly a third of the near side: choose the threshold to match
t = float(np.quantile(field[inside], 1 - 0.33))
mare = smoothstep(t - 0.05, t + 0.045, field)
mare = np.clip(mare, 0, 1)

# -------------------------------------------------------------- base albedo
n_high2 = fbm(5.5, 5, 70)
high = 0.68 + 0.06 * n_low + 0.05 * n_high2 + 0.035 * n_mid + 0.025 * n_fine
n_sea = fbm(12.0, 4, 130)
sea = 0.40 + 0.08 * (tone - 0.5) + 0.05 * n_low + 0.045 * n_sea + 0.015 * n_fine
albedo = high * (1 - mare) + sea * mare
# relief map holds only crater-scale detail (large-scale slopes would tilt
# the whole lighting); fine roughness is stronger in the highlands
height = (0.012 + 0.010 * (1 - mare)) * n_fine

# dark-floored craters
for lat_, lon_, r in ((51.6, -9.4, 1.6), (-5.2, -68.6, 2.6), (-3.0, -79, 1.6)):   # Plato, Grimaldi, Riccioli
    d = ang_dist(lat_, lon_)
    albedo = albedo * (1 - 0.55 * (1 - smoothstep(r * 0.8, r * 1.1, d)))

# ------------------------------------------------------------------ craters
print("craters…")
pix_deg = 180.0 / SIZE * 1.0          # ~angular size of a pixel at disc centre


def add_crater(lat_, lon_, r_deg, depth, fresh):
    ux, uy, uz = unit(lat_, lon_)
    if uz < -0.05:
        return
    # bounding box in image space
    cx, cy = ux, uy
    rr = math.radians(r_deg) * 2.2
    x0 = int(max(0, (cx - rr + 1) / 2 * SIZE)); x1 = int(min(SIZE, (cx + rr + 1) / 2 * SIZE) + 1)
    y0 = int(max(0, (1 - (cy + rr)) / 2 * SIZE)); y1 = int(min(SIZE, (1 - (cy - rr)) / 2 * SIZE) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    sx, sy = slice(y0, y1), slice(x0, x1)
    dot = np.clip(PX[sx, sy] * ux + PY[sx, sy] * uy + PZ[sx, sy] * uz, -1, 1)
    d = np.degrees(np.arccos(dot)) / r_deg          # in crater radii
    bowl = np.where(d < 1, -(1 - d * d), 0.0)
    rim = np.exp(-((d - 1.0) / 0.18) ** 2) * 0.35
    ejecta = np.where(d > 1, np.exp(-(d - 1) * 2.2) * 0.08, 0)
    height[sx, sy] += depth * (bowl + rim + ejecta)
    if fresh > 0:
        albedo[sx, sy] += fresh * (np.exp(-((d - 1.0) / 0.3) ** 2) * 0.07
                                   + np.where(d < 1, 0.03, 0) + np.where(d > 1, np.exp(-(d - 1) * 1.4) * 0.05, 0))


# random craters: uniform on the visible hemisphere, power-law radii
N = 4200 if SIZE >= 2048 else 2200
lat_s = np.degrees(np.arcsin(rng.uniform(-1, 1, N)))
lon_s = rng.uniform(-90, 90, N)
r_s = 0.22 * (rng.pareto(1.9, N) + 1)
r_s = np.clip(r_s, 0.2, 5.0)
for la, lo, r in zip(lat_s, lon_s, r_s):
    ix = int((math.cos(math.radians(la)) * math.sin(math.radians(lo)) + 1) / 2 * (SIZE - 1))
    iy = int((1 - math.sin(math.radians(la))) / 2 * (SIZE - 1))
    on_mare = mare[iy, ix] > 0.5
    if on_mare and rng.random() < 0.75:            # maria are younger: fewer craters
        continue
    depth = 0.05 + 0.012 * r
    fresh = (rng.random() * 0.9 if rng.random() < 0.12 else 0.0) if r < 2.5 else 0.0
    add_crater(la, lo, r, depth, fresh)

# named craters
for la, lo, r, depth, fresh in ((-43.3, -11.4, 3.0, 0.16, 1.4),   # Tycho
                                (9.6, -20.1, 3.1, 0.15, 1.1),      # Copernicus
                                (8.1, -38.0, 1.1, 0.07, 1.2),      # Kepler
                                (23.7, -47.4, 1.2, 0.07, 2.2),     # Aristarchus (brightest)
                                (-9.3, -1.9, 4.9, 0.12, 0.1),      # Ptolemaeus
                                (-15.4, -2.8, 3.3, 0.11, 0.1),     # Alphonsus
                                (-18.2, -1.9, 2.0, 0.10, 0.15),    # Arzachel
                                (-11.4, 26.4, 3.3, 0.13, 0.25),    # Theophilus
                                (-58.0, -14.0, 7.0, 0.14, 0.1),    # Clavius
                                (2.8, -3.0, 0.8, 0.05, 0.6)):      # Moesting region
    add_crater(la, lo, r, depth, fresh)

# --------------------------------------------------------------- ray systems
print("rays…")
for la, lo, n_rays, length, strength, seed in ((-43.3, -11.4, 44, 70.0, 0.13, 1),   # Tycho
                                              (9.6, -20.1, 34, 26.0, 0.10, 2),      # Copernicus
                                              (8.1, -38.0, 24, 16.0, 0.09, 3),      # Kepler
                                              (23.7, -47.4, 16, 11.0, 0.08, 4),     # Aristarchus
                                              (-18.3, 41.0, 14, 10.0, 0.05, 5),     # Proclus-like
                                              (16.2, 47.6, 12, 9.0, 0.05, 6)):      # Proclus
    g = np.random.default_rng(seed)
    ux, uy, uz = unit(la, lo)
    d = ang_dist(la, lo)
    # bearing from the crater to each pixel (in the tangent plane)
    nx, ny, nz = -math.sin(math.radians(la)) * math.sin(math.radians(lo)), math.cos(math.radians(la)), \
        -math.sin(math.radians(la)) * math.cos(math.radians(lo))
    ex, ey, ez = math.cos(math.radians(lo)), 0.0, -math.sin(math.radians(lo))
    vx, vy, vz = PX - ux, PY - uy, PZ - uz
    bearing = np.arctan2(vx * ex + vy * ey + vz * ez, vx * nx + vy * ny + vz * nz)
    rays = np.zeros_like(X, dtype=np.float32)
    for k in range(n_rays):
        th = g.uniform(-math.pi, math.pi)
        w = g.uniform(0.02, 0.06)
        L = length * g.uniform(0.45, 1.0)
        diff = np.angle(np.exp(1j * (bearing - th)))
        rays = np.maximum(rays, np.exp(-(diff / w) ** 2) * np.clip(1 - d / L, 0, 1) ** 1.1
                          * g.uniform(0.5, 1.0))
    halo = np.exp(-d / (length * 0.08))
    patchy = np.clip(0.55 + 0.6 * n_mid + 0.4 * n_fine, 0, 1)
    albedo = albedo + strength * (rays * patchy + 0.9 * halo)

# ------------------------------------------------------------------- output
albedo = np.clip(albedo, 0, 1)
albedo[~inside] = 0
# store relief around mid-grey with a fixed scale (1 unit = 0.25 of range)
h = np.clip(0.5 + height * 1.0, 0, 1)
h[~inside] = 0.5


def save_gray(arr, path, quality=93):
    from PyQt6.QtGui import QImage
    data = np.ascontiguousarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    img = QImage(data.data, SIZE, SIZE, SIZE, QImage.Format.Format_Grayscale8).copy()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path), "JPG", quality):
        raise SystemExit(f"could not write {path}")
    print("wrote", path, path.stat().st_size // 1024, "KB")


save_gray(albedo, OUT / "moon_albedo.jpg")
save_gray(h, OUT / "moon_height.jpg")
