"""The sky behind the Earth Globe: where the real Sun, Moon and stars appear.

The globe is seen from a point in space above (c_lat, c_lon). Things far away -
the Sun, Moon and stars - are drawn with a perspective (gnomonic) projection
from there, as if the camera could see about RHO degrees around the Earth's edge:

    screen offset = (x, y) / (-z) / tan(RHO)        in globe radii

where (x, y, z) is the object's direction in the view frame (x east, y north,
z towards the camera). Only things beyond the Earth (z < 0) can be seen; the
Earth itself hides anything that lands inside its disc. As the globe turns,
the Sun slides across the background and sets behind the Earth exactly when
the place facing you goes into night.

The Moon is drawn with its real phase, its bright side facing the Sun's
direction on screen, and celestial north turned to match the view.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import random
from typing import Optional

try:
    import numpy as _np
except ImportError:                       # pragma: no cover
    _np = None

RHO = 40.0                                # the Earth's angular radius as seen by the camera (wide view)
TAN_RHO = math.tan(math.radians(RHO))
_R = math.radians
_D = math.degrees

Vec = tuple[float, float, float]


def ecef(lat: float, lon: float) -> Vec:
    """Unit vector (Earth-fixed) towards latitude/longitude."""
    p, l = _R(lat), _R(lon)
    return (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))


def basis(c_lat: float, c_lon: float) -> tuple[Vec, Vec, Vec]:
    """(east, north, up) unit vectors for a view centred on c_lat, c_lon."""
    p, l = _R(c_lat), _R(c_lon)
    e = (-math.sin(l), math.cos(l), 0.0)
    n = (-math.sin(p) * math.cos(l), -math.sin(p) * math.sin(l), math.cos(p))
    u = (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))
    return e, n, u


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Vec) -> Vec:
    k = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / k, a[1] / k, a[2] / k)


def to_view(d: Vec, b) -> Vec:
    e, n, u = b
    return (_dot(d, e), _dot(d, n), _dot(d, u))


def sky_xy(d: Vec, b) -> Optional[tuple[float, float]]:
    """Screen offset (globe radii; x right, y up) of a far-away object in Earth-fixed
    direction d, or None if it's behind the camera."""
    x, y, z = to_view(d, b)
    if z > -1e-3:
        return None
    k = -1.0 / (z * TAN_RHO)
    return (x * k, y * k)


def hidden_by_earth(xy: tuple[float, float], radius: float = 0.0) -> bool:
    """True if a disc of `radius` (globe radii) at xy is completely behind the globe."""
    return math.hypot(*xy) + radius < 1.0


def _screen_angle(frm: tuple[float, float], to: tuple[float, float]) -> float:
    """Clockwise angle from up (degrees) of the direction frm -> to."""
    return _D(math.atan2(to[0] - frm[0], to[1] - frm[1])) % 360


def moon_orientation(moon: Vec, sun: Vec, b) -> Optional[tuple[float, float]]:
    """(bright_limb, rotation) for moon_render.render_moon so the Moon on screen has its
    lit side towards the Sun and its north matching the view. None if not visible."""
    m = _norm(moon)
    here = sky_xy(m, b)
    if here is None:
        return None
    eps = 0.01

    def towards(target: Vec) -> Optional[float]:
        t = _dot(target, m)
        tang = (target[0] - t * m[0], target[1] - t * m[1], target[2] - t * m[2])
        if _dot(tang, tang) < 1e-12:
            return None
        tang = _norm(tang)
        q = sky_xy(_norm((m[0] + eps * tang[0], m[1] + eps * tang[1], m[2] + eps * tang[2])), b)
        return None if q is None else _screen_angle(here, q)

    north = towards((0.0, 0.0, 1.0))
    sun_dir = towards(_norm(sun))
    north = 0.0 if north is None else north
    sun_dir = north if sun_dir is None else sun_dir
    bright_limb = (north - sun_dir) % 360
    return bright_limb, north


# ------------------------------------------------------------------ stars
class StarField:
    """Stars fixed in space (right ascension / declination), turning with sidereal time,
    so they wheel past as the globe spins - like the Sun and Moon."""

    def __init__(self, n: int = 2400, seed: int = 7):
        rng = random.Random(seed)
        self.stars = []                                    # (ra deg, dec deg, size, brightness)
        for _ in range(n):
            ra = rng.uniform(0, 360)
            dec = _D(math.asin(rng.uniform(-1, 1)))         # uniform over the sphere
            mag = rng.random() ** 3                         # mostly faint, a few bright
            self.stars.append((ra, dec, 0.5 + 1.4 * mag, int(70 + 185 * mag)))
        if _np is not None:
            a = _np.array([[s[0], s[1]] for s in self.stars], dtype=_np.float64)
            self._ra, self._dec = _np.radians(a[:, 0]), _np.radians(a[:, 1])
            self._size = _np.array([s[2] for s in self.stars])
            self._bright = _np.array([s[3] for s in self.stars])

    def positions(self, gmst_deg: float, b, limit: float) -> list[tuple[float, float, float, int]]:
        """[(x, y, size, brightness)] in globe radii for stars beyond the Earth and within
        `limit` radii of the centre (stars inside the globe disc are left out)."""
        e, n, u = b
        g = _R(gmst_deg)
        if _np is not None:
            np = _np
            lon = self._ra - g
            cd = np.cos(self._dec)
            d = np.stack([cd * np.cos(lon), cd * np.sin(lon), np.sin(self._dec)], axis=1)
            x, y, z = d @ np.array(e), d @ np.array(n), d @ np.array(u)
            ok = z < -1e-3
            k = np.where(ok, -1.0 / (np.where(ok, z, -1.0) * TAN_RHO), 0.0)
            sx, sy = x * k, y * k
            r = np.hypot(sx, sy)
            ok &= (r > 1.0) & (r < limit)
            idx = np.nonzero(ok)[0]
            return [(float(sx[i]), float(sy[i]), float(self._size[i]), int(self._bright[i])) for i in idx]
        out = []
        for ra, dec, size, bright in self.stars:
            lon = _R(ra) - g
            cd = math.cos(_R(dec))
            d = (cd * math.cos(lon), cd * math.sin(lon), math.sin(_R(dec)))
            xy = sky_xy(d, b)
            if xy is not None and 1.0 < math.hypot(*xy) < limit:
                out.append((xy[0], xy[1], size, bright))
        return out


def gmst_now(t: dt.datetime) -> float:
    from .moon import gmst, julian_day
    return gmst(julian_day(t))
