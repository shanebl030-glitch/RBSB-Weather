"""Moon astronomy computed locally: phase, illumination, moonrise/moonset.

No web service is involved, so moon data works offline. Positions use the
main periodic terms of Meeus, "Astronomical Algorithms" (2nd ed.), ch. 47
(about 10" for the Moon) and ch. 25 (Sun). Rise/set times are where the
Moon's centre reaches the standard altitude h0 = 0.7275·π − 0.5667°
(Meeus ch. 15, π = horizontal parallax), which accounts for parallax and
refraction. Times are typically within about a minute of published almanacs
(checked against PyEphem in the test suite).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Optional

SYNODIC_MONTH = 29.530588853
DELTA_T_S = 69.2            # TT - UT (s), adequate for 2020s-2030s

# Meeus Table 47.A: D, M, M', F, Σl (1e-6 deg), Σr (1e-3 km)
_LR = [
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111), (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925), (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138), (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586), (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321), (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661), (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208), (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379), (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650), (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003), (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884), (0, 1, 2, 0, -2120, 5751),
    (0, 2, 0, 0, -2069, 0), (2, -2, -1, 0, 2048, -4950), (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0), (4, -1, -1, 0, 1215, -3958), (0, 0, 2, 2, -1110, 0),
    (3, 0, -1, 0, -892, 3258), (2, 1, 1, 0, -810, 2616), (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117), (2, 2, -1, 0, -700, 2354), (2, 1, -2, 0, 691, 0),
    (2, -1, 0, -2, 596, 0), (4, 0, 1, 0, 549, -1423), (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571), (1, 0, -2, 0, -487, -1739), (2, 1, 0, -2, -399, 0),
    (0, 0, 2, -2, -381, -4421), (1, 1, 1, 0, 351, 0), (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0), (2, -1, 2, 0, 327, 0), (0, 2, 1, 0, -323, 1165),
    (1, 1, -1, 0, 299, 0), (2, 0, 3, 0, 294, 0), (2, 0, -1, -2, 0, 8752),
]
# Meeus Table 47.B: D, M, M', F, Σb (1e-6 deg)
_B = [
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693), (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271), (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266), (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463), (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870), (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794),
    (0, 0, 0, 3, -1749), (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335), (0, 0, 3, 1, 1107),
    (4, 0, 0, -1, 1021), (4, 0, -1, 1, 833), (0, 0, 1, -3, 777), (4, 0, -2, 1, 671),
    (2, 0, 0, -3, 607), (2, 0, 2, -1, 596), (2, -1, 1, -1, 491), (2, 0, -2, 1, -451),
    (0, 0, 3, -1, 439), (2, 0, 2, 1, 422), (2, 0, -3, -1, 421), (2, 1, -1, 1, -366),
    (2, 1, 0, 1, -351), (4, 0, 0, 1, 331), (2, -1, 1, 1, 315), (2, -2, 0, -1, 302),
    (0, 0, 1, 3, -283), (2, 1, 1, -1, -229), (1, 1, 0, -1, 223), (1, 1, 0, 1, 223),
]

_R = math.radians
_D = math.degrees


def _sin(d: float) -> float:
    return math.sin(_R(d))


def _cos(d: float) -> float:
    return math.cos(_R(d))


def julian_day(t: dt.datetime) -> float:
    """Julian Day for an aware datetime (converted to UTC)."""
    if t.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    t = t.astimezone(dt.timezone.utc)
    return 2440587.5 + t.timestamp() / 86400.0


@dataclass
class Position:
    ra: float          # degrees
    dec: float         # degrees
    lon: float         # ecliptic longitude, degrees
    lat: float         # ecliptic latitude, degrees
    dist_km: float


def _obliquity(T: float) -> float:
    return 23.439291 - 0.0130042 * T - 1.64e-7 * T * T


def _ecl_to_eq(lon: float, lat: float, eps: float) -> tuple[float, float]:
    ra = _D(math.atan2(_sin(lon) * _cos(eps) - math.tan(_R(lat)) * _sin(eps), _cos(lon))) % 360
    dec = _D(math.asin(_sin(lat) * _cos(eps) + _cos(lat) * _sin(eps) * _sin(lon)))
    return ra, dec


def moon_position(jd_ut: float) -> Position:
    T = (jd_ut + DELTA_T_S / 86400 - 2451545.0) / 36525.0
    Lp = 218.3164477 + 481267.88123421 * T - 0.0015786 * T * T + T ** 3 / 538841 - T ** 4 / 65194000
    D = 297.8501921 + 445267.1114034 * T - 0.0018819 * T * T + T ** 3 / 545868 - T ** 4 / 113065000
    M = 357.5291092 + 35999.0502909 * T - 0.0001536 * T * T + T ** 3 / 24490000
    Mp = 134.9633964 + 477198.8675055 * T + 0.0087414 * T * T + T ** 3 / 69699 - T ** 4 / 14712000
    F = 93.2720950 + 483202.0175233 * T - 0.0036539 * T * T - T ** 3 / 3526000 + T ** 4 / 863310000
    A1 = 119.75 + 131.849 * T
    A2 = 53.09 + 479264.290 * T
    A3 = 313.45 + 481266.484 * T
    E = 1 - 0.002516 * T - 0.0000074 * T * T
    sl = sr = sb = 0.0
    for d, m, mp, f, cl, cr in _LR:
        arg = d * D + m * M + mp * Mp + f * F
        e = E ** abs(m)
        sl += cl * e * _sin(arg)
        sr += cr * e * _cos(arg)
    for d, m, mp, f, cb in _B:
        sb += cb * (E ** abs(m)) * _sin(d * D + m * M + mp * Mp + f * F)
    sl += 3958 * _sin(A1) + 1962 * _sin(Lp - F) + 318 * _sin(A2)
    sb += (-2235 * _sin(Lp) + 382 * _sin(A3) + 175 * _sin(A1 - F) + 175 * _sin(A1 + F)
           + 127 * _sin(Lp - Mp) - 115 * _sin(Lp + Mp))
    # nutation in longitude (main terms)
    om = 125.04452 - 1934.136261 * T
    dpsi = (-17.20 * _sin(om) - 1.32 * _sin(2 * (280.4665 + 36000.7698 * T))
            - 0.23 * _sin(2 * Lp) + 0.21 * _sin(2 * om)) / 3600
    lon = (Lp + sl / 1e6 + dpsi) % 360
    lat = sb / 1e6
    dist = 385000.56 + sr / 1000
    eps = _obliquity(T) + 9.20 / 3600 * _cos(om)
    ra, dec = _ecl_to_eq(lon, lat, eps)
    return Position(ra, dec, lon, lat, dist)


def sun_position(jd_ut: float) -> Position:
    T = (jd_ut + DELTA_T_S / 86400 - 2451545.0) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
    e = 0.016708634 - 0.000042037 * T
    C = ((1.914602 - 0.004817 * T - 0.000014 * T * T) * _sin(M)
         + (0.019993 - 0.000101 * T) * _sin(2 * M) + 0.000289 * _sin(3 * M))
    v = M + C
    R = 1.000001018 * (1 - e * e) / (1 + e * _cos(v))
    om = 125.04 - 1934.136 * T
    lon = (L0 + C - 0.00569 - 0.00478 * _sin(om)) % 360
    eps = _obliquity(T) + 0.00256 * _cos(om)
    ra, dec = _ecl_to_eq(lon, 0.0, eps)
    return Position(ra, dec, lon, 0.0, R * 149597870.7)


def gmst(jd_ut: float) -> float:
    T = (jd_ut - 2451545.0) / 36525.0
    return (280.46061837 + 360.98564736629 * (jd_ut - 2451545.0)
            + 0.000387933 * T * T - T ** 3 / 38710000) % 360


def moon_altitude(jd_ut: float, lat: float, lon: float) -> tuple[float, float]:
    """Geocentric altitude of the Moon's centre and the rise/set standard altitude h0."""
    p = moon_position(jd_ut)
    H = gmst(jd_ut) + lon - p.ra
    alt = _D(math.asin(_sin(lat) * _sin(p.dec) + _cos(lat) * _cos(p.dec) * _cos(H)))
    parallax = _D(math.asin(6378.14 / p.dist_km))
    return alt, 0.7275 * parallax - 0.5667


# ------------------------------------------------------------------ phase
@dataclass
class Phase:
    illumination: float      # 0..1 illuminated fraction
    phase_angle: float       # degrees, 0 = full, 180 = new
    elongation: float        # moon - sun ecliptic longitude, 0..360 (0 new, 180 full)
    waxing: bool
    bright_limb: float       # position angle of the bright limb (deg, from north through east)
    age_days: float          # approximate days since new moon
    distance_km: float

    @property
    def name(self) -> str:
        return phase_name(self.elongation)


def phase_name(elong: float) -> str:
    e = elong % 360
    w = 6.0                  # ~half a day either side of the exact instant
    if e < w or e > 360 - w:
        return "New Moon"
    if abs(e - 90) < w:
        return "First Quarter"
    if abs(e - 180) < w:
        return "Full Moon"
    if abs(e - 270) < w:
        return "Last Quarter"
    if e < 90:
        return "Waxing Crescent"
    if e < 180:
        return "Waxing Gibbous"
    if e < 270:
        return "Waning Gibbous"
    return "Waning Crescent"


def moon_phase(t: dt.datetime) -> Phase:
    jd = julian_day(t)
    m, s = moon_position(jd), sun_position(jd)
    elong = (m.lon - s.lon) % 360
    cos_psi = _cos(m.lat) * _cos(m.lon - s.lon)
    psi = math.acos(max(-1.0, min(1.0, cos_psi)))
    i = math.atan2(s.dist_km * math.sin(psi), m.dist_km - s.dist_km * math.cos(psi))
    k = (1 + math.cos(i)) / 2
    chi = _D(math.atan2(_cos(s.dec) * _sin(s.ra - m.ra),
                        _sin(s.dec) * _cos(m.dec) - _cos(s.dec) * _sin(m.dec) * _cos(s.ra - m.ra))) % 360
    return Phase(illumination=k, phase_angle=_D(i), elongation=elong, waxing=elong < 180,
                 bright_limb=chi, age_days=elong / 360 * SYNODIC_MONTH, distance_km=m.dist_km)


def _elong(jd: float) -> float:
    return (moon_position(jd).lon - sun_position(jd).lon) % 360


SYNODIC_RATE = 360.0 / SYNODIC_MONTH        # mean change in elongation, degrees per day


def next_phase_time(after: dt.datetime, target: float) -> dt.datetime:
    """Next instant (UTC-aware) when elongation equals target (0, 90, 180, 270).

    Newton's method on the elongation (about 6 position calculations instead of a
    half-day scan with bisection, ~75), accurate to well under a second."""
    jd0 = julian_day(after)

    def f(jd):  # signed angular distance to target in (-180, 180]
        return ((_elong(jd) - target + 180) % 360) - 180

    jd = jd0 + ((-f(jd0)) % 360) / SYNODIC_RATE          # first estimate: next crossing
    for _ in range(12):
        d = f(jd)
        jd -= d / SYNODIC_RATE
        if abs(d) < 1e-6:                                   # ~0.01 s of time
            break
    if jd < jd0 - 1e-6:                                     # landed on the previous one
        return next_phase_time(_from_jd(jd0 + 1.0), target)
    return _from_jd(jd)


def _from_jd(jd: float) -> dt.datetime:
    return dt.datetime.fromtimestamp((jd - 2440587.5) * 86400.0, dt.timezone.utc)


def age_days(t: dt.datetime) -> float:
    """Days since the most recent new moon."""
    prev = next_phase_time(t - dt.timedelta(days=SYNODIC_MONTH + 1), 0.0)
    while True:
        nxt = next_phase_time(prev + dt.timedelta(days=1), 0.0)
        if nxt > t:
            break
        prev = nxt
    return (t - prev).total_seconds() / 86400


# -------------------------------------------------------------- rise / set
def rise_set(day: dt.date, lat: float, lon: float, tz: dt.tzinfo) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
    """Moonrise and moonset during the local calendar `day` (None if it doesn't happen)."""
    start = dt.datetime.combine(day, dt.time(0, 0), tz)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0), tz)
    jd_a, jd_b = julian_day(start), julian_day(end)

    def g(jd):
        alt, h0 = moon_altitude(jd, lat, lon)
        return alt - h0

    rise = sett = None
    step = 30 / 1440                                   # altitude changes smoothly; refine below
    jd, v = jd_a, g(jd_a)
    while jd < jd_b - 1e-9:
        nxt = min(jd + step, jd_b)
        nv = g(nxt)
        if (v < 0 <= nv) or (v >= 0 > nv):
            # secant/regula-falsi refinement (a handful of calls instead of 30 bisections)
            a, b, fa, fb = jd, nxt, v, nv
            for _ in range(8):
                c = b - fb * (b - a) / (fb - fa) if fb != fa else (a + b) / 2
                fc = g(c)
                if abs(fc) < 1e-5 or abs(b - a) < 1e-6:
                    a = b = c
                    break
                if (fa < 0) == (fc < 0):
                    a, fa = c, fc
                else:
                    b, fb = c, fc
            when = _from_jd((a + b) / 2).astimezone(tz)
            if v < 0 <= nv and rise is None:
                rise = when
            elif v >= 0 > nv and sett is None:
                sett = when
        jd, v = nxt, nv
    return rise, sett


def _refine(g, a: float, b: float, fa: float, fb: float) -> float:
    """Where g crosses zero between a and b (secant / regula falsi)."""
    for _ in range(10):
        c = b - fb * (b - a) / (fb - fa) if fb != fa else (a + b) / 2
        fc = g(c)
        if abs(fc) < 1e-5 or abs(b - a) < 1e-6:
            return c
        if (fa < 0) == (fc < 0):
            a, fa = c, fc
        else:
            b, fb = c, fc
    return (a + b) / 2


def moon_pass(t: dt.datetime, lat: float, lon: float,
              span_hours: float = 30.0) -> tuple[bool, Optional[dt.datetime], Optional[dt.datetime]]:
    """(up, rise, set) for the Moon's current trip across the sky at time t:
    the moonrise that started it and the moonset that will end it (UTC).
    rise/set are None when not found within `span_hours` (polar always-up)."""
    def g(jd):
        alt, h0 = moon_altitude(jd, lat, lon)
        return alt - h0
    jd0 = julian_day(t)
    v0 = g(jd0)
    if v0 < 0:
        return False, None, None
    step = 20 / 1440
    n = int(span_hours * 60 / 20)
    rise = sett = None
    a, fa = jd0, v0                               # backwards to the rise
    for _ in range(n):
        b = a - step
        fb = g(b)
        if fb < 0:
            rise = _from_jd(_refine(g, b, a, fb, fa))
            break
        a, fa = b, fb
    a, fa = jd0, v0                               # forwards to the set
    for _ in range(n):
        b = a + step
        fb = g(b)
        if fb < 0:
            sett = _from_jd(_refine(g, a, b, fa, fb))
            break
        a, fa = b, fb
    return True, rise, sett


# ------------------------------------------------------------- daily view
@dataclass
class MoonDay:
    date: dt.date
    phase: Phase              # at local noon
    name: str                 # principal phase name if its exact instant falls on this day
    rise: Optional[dt.datetime]
    set: Optional[dt.datetime]
    always_up: bool = False
    always_down: bool = False


PRINCIPAL = ((0.0, "New Moon"), (90.0, "First Quarter"), (180.0, "Full Moon"), (270.0, "Last Quarter"))


def tz_for(name: Optional[str], utc_offset_s: Optional[int] = None) -> dt.tzinfo:
    """Timezone from an IANA name (e.g. Pacific/Auckland), else a fixed offset, else UTC."""
    if name and name not in ("auto", "GMT", "UTC"):
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            pass
    if utc_offset_s is not None:
        return dt.timezone(dt.timedelta(seconds=int(utc_offset_s)))
    return dt.timezone.utc


def moon_days(lat: float, lon: float, tz: dt.tzinfo, first: dt.date, days: int = 7) -> list[MoonDay]:
    out = []
    start = dt.datetime.combine(first, dt.time(0, 0), tz)
    events = []
    t = start - dt.timedelta(days=1)
    for target, name in PRINCIPAL:
        e = next_phase_time(t, target)
        while e < start + dt.timedelta(days=days + 1):
            events.append((e.astimezone(tz), name))
            e = next_phase_time(e + dt.timedelta(days=2), target)
    for i in range(days):
        d = first + dt.timedelta(days=i)
        noon = dt.datetime.combine(d, dt.time(12, 0), tz)
        ph = moon_phase(noon)
        name = next((n for e, n in events if e.date() == d), ph.name)
        if name in ("New Moon", "First Quarter", "Full Moon", "Last Quarter") and \
                not any(e.date() == d and n == name for e, n in events):
            # a principal name only on the actual day of the event
            name = ("Waxing Crescent" if ph.elongation < 90 else "Waxing Gibbous" if ph.elongation < 180
                    else "Waning Gibbous" if ph.elongation < 270 else "Waning Crescent")
        r, s = rise_set(d, lat, lon, tz)
        md = MoonDay(d, ph, name, r, s)
        if r is None and s is None:
            alt, h0 = moon_altitude(julian_day(noon), lat, lon)
            md.always_up, md.always_down = alt > h0, alt <= h0
        out.append(md)
    return out


def upcoming_phases(after: dt.datetime, tz: dt.tzinfo) -> list[tuple[str, dt.datetime]]:
    """The next New, First Quarter, Full and Last Quarter moons, soonest first."""
    res = [(name, next_phase_time(after, target).astimezone(tz)) for target, name in PRINCIPAL]
    return sorted(res, key=lambda x: x[1])


# ------------------------------------------------------- view in the sky
@dataclass
class SkyView:
    """How the Moon is oriented in a given place's sky.

    rotation: degrees to turn a north-up picture CLOCKWISE so that "up" in the
    picture is straight up in the observer's sky (towards the zenith). This is
    the parallactic angle q (Meeus ch. 14): 0 when the Moon is due south of the
    zenith (typical from the northern hemisphere), ~180 from the southern
    hemisphere, and in between (the tropical "smiling" crescent) elsewhere.
    """
    when: dt.datetime
    rotation: float
    altitude: float          # degrees (geocentric, centre of the Moon)
    azimuth: float           # degrees from north through east
    up: bool                 # above the horizon at `when`
    is_now: bool             # True: orientation right now; False: at its next highest point


def _hour_angle(jd: float, lon: float, ra: float) -> float:
    return ((gmst(jd) + lon - ra + 180) % 360) - 180          # -180..180, 0 = on the meridian


def sky_geometry(jd_ut: float, lat: float, lon: float) -> tuple[float, float, float, float]:
    """(parallactic angle q, altitude, azimuth, standard altitude h0) for the Moon."""
    p = moon_position(jd_ut)
    H = _hour_angle(jd_ut, lon, p.ra)
    q = _D(math.atan2(_sin(H), math.tan(_R(lat)) * _cos(p.dec) - _sin(p.dec) * _cos(H)))
    alt = _D(math.asin(_sin(lat) * _sin(p.dec) + _cos(lat) * _cos(p.dec) * _cos(H)))
    az = (_D(math.atan2(_sin(H), _cos(H) * _sin(lat) - math.tan(_R(p.dec)) * _cos(lat))) + 180) % 360
    h0 = 0.7275 * _D(math.asin(6378.14 / p.dist_km)) - 0.5667
    return q % 360, alt, az, h0


LUNAR_DAY_RATE = 360.0 / 1.0350501     # degrees of hour angle per day (mean lunar day 24h 50m)


def next_transit(after: dt.datetime, lon: float) -> dt.datetime:
    """Next upper culmination (Moon on the local meridian, at its highest).

    Newton's method on the hour angle: about 5 position calculations instead of
    a 10-minute scan (~180), which keeps the background work light."""
    jd0 = julian_day(after)
    H0 = _hour_angle(jd0, lon, moon_position(jd0).ra)
    jd = jd0 + ((-H0) % 360) / LUNAR_DAY_RATE           # first estimate: the next crossing
    for _ in range(8):
        H = _hour_angle(jd, lon, moon_position(jd).ra)
        jd -= H / LUNAR_DAY_RATE
        if abs(H) < 1e-4:                                 # ~0.4 s of time
            break
    if jd < jd0 - 1e-6:                                   # converged onto the previous transit
        return next_transit(_from_jd(jd0 + 0.05), lon)
    return _from_jd(jd)


def _next_transit_scan(after: dt.datetime, lon: float) -> dt.datetime:   # reference (tests only)
    """Next upper culmination (Moon on the local meridian, at its highest)."""
    jd0 = julian_day(after)
    step = 10 / 1440
    a = jd0
    fa = _hour_angle(a, lon, moon_position(a).ra)
    for _ in range(int(1.2 / step)):                          # always within ~24.9 h
        b = a + step
        fb = _hour_angle(b, lon, moon_position(b).ra)
        if fa < 0 <= fb and fb - fa < 90:
            for _ in range(30):
                c = (a + b) / 2
                fc = _hour_angle(c, lon, moon_position(c).ra)
                if fc < 0:
                    a, fa = c, fc
                else:
                    b = c
            return _from_jd((a + b) / 2)
        a, fa = b, fb
    raise RuntimeError("transit search failed")              # pragma: no cover


def sky_view(t: dt.datetime, lat: float, lon: float, tz: Optional[dt.tzinfo] = None) -> SkyView:
    """Orientation now if the Moon is up; otherwise as it will look at its next highest point."""
    tz = tz or t.tzinfo or dt.timezone.utc
    q, alt, az, h0 = sky_geometry(julian_day(t), lat, lon)
    if alt > h0:
        return SkyView(t.astimezone(tz), q, alt, az, True, True)
    tr = next_transit(t, lon)
    q, alt, az, h0 = sky_geometry(julian_day(tr), lat, lon)
    return SkyView(tr.astimezone(tz), q, alt, az, alt > h0, False)


def day_view(day: dt.date, lat: float, lon: float, tz: dt.tzinfo) -> SkyView:
    """Orientation at the Moon's highest point during (or nearest after the start of) a local day."""
    start = dt.datetime.combine(day, dt.time(0, 0), tz)
    tr = next_transit(start, lon).astimezone(tz)
    q, alt, az, h0 = sky_geometry(julian_day(tr), lat, lon)
    return SkyView(tr, q, alt, az, alt > h0, False)
