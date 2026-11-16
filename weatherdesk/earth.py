"""Earth day/night calculations and map compositing.

* subsolar_point / sublunar_point – where the Sun / Moon are directly overhead
* solar_elevation / day_state     – day, twilight or night at a place
* compose_day_night               – blends the day and night Earth maps along the
                                    real terminator, with a soft twilight band

Compositing is done with Qt (no numpy needed): the day/night weight is
computed on a small grid in Python, scaled smoothly to the map size, and used
as an alpha mask - fast enough for a background thread every few minutes.

Earth maps: Solar System Scope (CC BY 4.0), based on NASA imagery.
Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Optional

from .moon import gmst, julian_day, moon_position, sun_position

ASSETS = Path(__file__).with_name("assets")
DAY_FILE = ASSETS / "earth_day.jpg"
NIGHT_FILE = ASSETS / "earth_night.jpg"
CREDIT = "Earth maps: Solar System Scope (CC BY 4.0), based on NASA imagery"
SOURCE_URL = "https://www.solarsystemscope.com/textures/"

# Twilight limits (solar elevation, degrees)
SUNRISE_ALT = -0.833       # Sun's upper edge on the horizon, with refraction
CIVIL_TWILIGHT = -6.0
NIGHT_LIGHTS_FULL = -9.0   # city lights fully visible below this
DAY_FULL = 4.0             # full daylight colours above this

_R = math.radians
_D = math.degrees


class EarthTextureError(RuntimeError):
    pass


def _norm_lon(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


def subsolar_point(t: dt.datetime) -> tuple[float, float]:
    """(latitude, longitude) where the Sun is overhead at time t."""
    jd = julian_day(t)
    s = sun_position(jd)
    return s.dec, _norm_lon(s.ra - gmst(jd))


def sublunar_point(t: dt.datetime) -> tuple[float, float]:
    """(latitude, longitude) where the Moon is overhead (geocentric) at time t."""
    jd = julian_day(t)
    m = moon_position(jd)
    return m.dec, _norm_lon(m.ra - gmst(jd))


def elevation_from(sub_lat: float, sub_lon: float, lat: float, lon: float) -> float:
    """Elevation (degrees) of a body overhead at (sub_lat, sub_lon), seen from (lat, lon)."""
    s = (math.sin(_R(lat)) * math.sin(_R(sub_lat))
         + math.cos(_R(lat)) * math.cos(_R(sub_lat)) * math.cos(_R(lon - sub_lon)))
    return _D(math.asin(max(-1.0, min(1.0, s))))


def solar_elevation(t: dt.datetime, lat: float, lon: float) -> float:
    return elevation_from(*subsolar_point(t), lat, lon)


def day_state(elevation: float) -> str:
    if elevation > SUNRISE_ALT:
        return "Day"
    if elevation > CIVIL_TWILIGHT:
        return "Twilight"
    return "Night"


def _smoothstep(e0: float, e1: float, x: float) -> float:
    t = (x - e0) / (e1 - e0)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def day_weight(elev: float) -> float:
    """0 = night map, 1 = day map; a smooth band through twilight."""
    return _smoothstep(NIGHT_LIGHTS_FULL, DAY_FULL, elev)


def masks(t: dt.datetime, w: int = 512, h: int = 256) -> tuple[bytes, bytes]:
    """(day alpha, dusk shade alpha) as w*h byte grids for time t (equirectangular,
    longitude -180..180 left to right, latitude 90..-90 top to bottom)."""
    slat, slon = subsolar_point(t)
    sd, cd = math.sin(_R(slat)), math.cos(_R(slat))
    cols = [math.cos(_R(-180.0 + (i + 0.5) * 360.0 / w - slon)) for i in range(w)]
    day = bytearray(w * h)
    shade = bytearray(w * h)
    asin, deg = math.asin, _D
    for j in range(h):
        lat = 90.0 - (j + 0.5) * 180.0 / h
        a = math.sin(_R(lat)) * sd
        b = math.cos(_R(lat)) * cd
        row = j * w
        for i in range(w):
            s = a + b * cols[i]
            e = deg(asin(-1.0 if s < -1 else 1.0 if s > 1 else s))
            day[row + i] = int(255 * day_weight(e) + 0.5)
            # gentle darkening of the day side towards the terminator (low sun)
            shade[row + i] = int(255 * 0.45 * (1 - _smoothstep(0.0, 25.0, e)) * _smoothstep(-6.0, 0.0, e) + 0.5)
    return bytes(day), bytes(shade)


_tex: dict[str, object] = {}


def _texture(path: Path):
    from PyQt6.QtGui import QImage
    img = _tex.get(str(path))
    if img is None:
        img = QImage(str(path))
        if img.isNull():
            raise EarthTextureError(f"Earth map missing or unreadable: {path}")
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        _tex[str(path)] = img
    return img


CLOUD_DAY = (246, 248, 252)      # sunlit cloud tops
CLOUD_NIGHT_DIM = 0.88           # how much cloud hides city lights at night
CLOUD_NIGHT_GLOW = 0.16          # faint (moonlit) cloud visible on the night side


def compose_day_night(t: dt.datetime, mask_w: int = 512, clouds=None):
    """The Earth map at time t: night lights where it's dark, daylight where it's
    day, blended through twilight. With `clouds` (a 2:1 greyscale cloud map
    QImage), white cloud is laid over the day side and dims city lights on the
    night side. Returns a QImage at the textures' size."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter

    day = _texture(DAY_FILE)
    night = _texture(NIGHT_FILE)
    if day.size() != night.size():
        night = night.scaled(day.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    W, H = day.width(), day.height()
    mw, mh = mask_w, mask_w // 2
    dmask, smask = masks(t, mw, mh)

    if clouds is not None:
        from .clouds import cloud_alpha, colour_layer
        ca = cloud_alpha(clouds, W, H)
        day = day.copy()
        p = QPainter(day)
        p.drawImage(0, 0, colour_layer(ca, QColor(*CLOUD_DAY)))
        p.end()
        night = night.copy()
        p = QPainter(night)
        p.setOpacity(CLOUD_NIGHT_DIM)
        p.drawImage(0, 0, colour_layer(ca, QColor(6, 8, 14)))
        p.setOpacity(CLOUD_NIGHT_GLOW)
        p.drawImage(0, 0, colour_layer(ca, QColor(120, 130, 150)))
        p.end()

    def alpha_img(data: bytes):
        a = QImage(data, mw, mh, mw, QImage.Format.Format_Alpha8).copy()
        return a.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)

    layer = day.copy()
    p = QPainter(layer)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(QRect(0, 0, W, H), alpha_img(dmask))
    p.end()

    shade = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    shade.fill(QColor(8, 10, 30))
    p = QPainter(shade)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(QRect(0, 0, W, H), alpha_img(smask))
    p.end()

    out = night.copy()
    p = QPainter(out)
    p.drawImage(0, 0, layer)
    p.drawImage(0, 0, shade)
    p.end()
    return out


def to_map_xy(lat: float, lon: float, w: float, h: float) -> tuple[float, float]:
    """Equirectangular projection: map pixel for a latitude/longitude."""
    return (_norm_lon(lon) + 180.0) / 360.0 * w, (90.0 - lat) / 180.0 * h


def from_map_xy(x: float, y: float, w: float, h: float) -> tuple[float, float]:
    return 90.0 - y / h * 180.0, x / w * 360.0 - 180.0
