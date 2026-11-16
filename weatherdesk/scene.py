"""Animated, realistic weather scenes and icons (pure QPainter, no image files).

* WeatherScene  – a sky scene: time-of-day sky colours, the sun moving along
  its daily arc, a moon in its real phase with twinkling stars, layered
  volumetric clouds drifting with the wind, rain (slanted by wind, with
  splashes), drizzle, swaying snow, drifting fog and lightning.
* WeatherIcon   – small animated icon for forecast rows.
* AnimationClock – one shared ~30 fps timer. It only runs while at least one
  scene/icon is actually visible (not hidden, not minimised) and animation is
  enabled, so a hidden or tray-minimised app uses no CPU on animation.

All randomness uses seeded generators so frames are reproducible in tests.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import math
import random
import time
import weakref
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QLineF, QObject, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QRadialGradient)
from PyQt6.QtWidgets import QSizePolicy, QWidget

FPS = 24          # weather moves slowly; 24 fps looks smooth and saves ~20% CPU vs 30

# ----------------------------------------------------------------- classify
CLEAR, PARTLY, OVERCAST, FOG, DRIZZLE, RAIN, SNOW, THUNDER = (
    "clear", "partly", "overcast", "fog", "drizzle", "rain", "snow", "thunder")

_CODE_MAP: dict[int, tuple[str, float]] = {
    0: (CLEAR, 0.0), 1: (PARTLY, 0.25), 2: (PARTLY, 0.55), 3: (OVERCAST, 1.0),
    45: (FOG, 0.7), 48: (FOG, 0.9),
    51: (DRIZZLE, 0.3), 53: (DRIZZLE, 0.55), 55: (DRIZZLE, 0.85), 56: (DRIZZLE, 0.4), 57: (DRIZZLE, 0.7),
    61: (RAIN, 0.35), 63: (RAIN, 0.6), 65: (RAIN, 1.0), 66: (RAIN, 0.4), 67: (RAIN, 0.8),
    80: (RAIN, 0.4), 81: (RAIN, 0.7), 82: (RAIN, 1.0),
    71: (SNOW, 0.3), 73: (SNOW, 0.6), 75: (SNOW, 1.0), 77: (SNOW, 0.3), 85: (SNOW, 0.5), 86: (SNOW, 0.9),
    95: (THUNDER, 0.7), 96: (THUNDER, 0.85), 99: (THUNDER, 1.0),
}


def classify(code: Optional[int]) -> tuple[str, float]:
    """WMO weather code -> (kind, intensity 0..1). Unknown codes look partly cloudy."""
    if code is None:
        return PARTLY, 0.4
    return _CODE_MAP.get(int(code), (PARTLY, 0.4))


def moon_phase(when: dt.datetime) -> float:
    """Moon age as a fraction 0..1 (0 = new, 0.5 = full). Accurate to ~a day."""
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    days = (when - ref).total_seconds() / 86400.0
    return (days / 29.530588853) % 1.0


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(_lerp(c1.red(), c2.red(), t)), int(_lerp(c1.green(), c2.green(), t)),
                  int(_lerp(c1.blue(), c2.blue(), t)), int(_lerp(c1.alpha(), c2.alpha(), t)))


# ------------------------------------------------------------- conditions
@dataclass
class Conditions:
    kind: str = PARTLY
    intensity: float = 0.4
    daylight: float = 1.0          # 0 night .. 1 full day
    twilight: float = 0.0          # 0..1 strength of dawn/dusk glow
    sun_progress: float = 0.5      # 0 at sunrise .. 1 at sunset
    wind_kmh: float = 10.0
    wind_sign: float = 1.0         # +1 drift right, -1 drift left
    cloud_cover: Optional[float] = None
    moon_age: float = 0.5
    southern: bool = False         # southern hemisphere: moon appears mirrored
    moon_phase_angle: Optional[float] = None   # from moon.py (0 full .. 180 new)
    moon_limb: float = 270.0                    # bright-limb position angle
    moon_rotation: Optional[float] = None       # parallactic angle for this place (None: hemisphere)
    moon_up: bool = True                        # above the horizon right now
    moon_altitude: float = 45.0
    moon_progress: Optional[float] = None       # 0 at moonrise .. 1 at moonset (None: unknown)
    # Real rise/set moments (epoch seconds). When known, the scene works out the Sun's
    # and Moon's place on their arc continuously from the clock, so they glide.
    sun_rise_ts: Optional[float] = None
    sun_set_ts: Optional[float] = None
    moon_rise_ts: Optional[float] = None
    moon_set_ts: Optional[float] = None

    def sun_progress_at(self, now: float) -> float:
        if self.sun_rise_ts is not None and self.sun_set_ts is not None and self.sun_set_ts > self.sun_rise_ts:
            return (now - self.sun_rise_ts) / (self.sun_set_ts - self.sun_rise_ts)
        return self.sun_progress

    def moon_progress_at(self, now: float) -> Optional[float]:
        if self.moon_rise_ts is not None and self.moon_set_ts is not None and self.moon_set_ts > self.moon_rise_ts:
            return (now - self.moon_rise_ts) / (self.moon_set_ts - self.moon_rise_ts)
        if self.moon_progress is not None:
            return self.moon_progress
        if not self.moon_up:
            return None
        # rise/set unknown (e.g. polar regions): place it by altitude, past the top
        return 0.5 + 0.5 * (1 - max(0.0, min(90.0, self.moon_altitude)) / 90.0)

    @property
    def cloud_amount(self) -> float:
        base = {CLEAR: 0.0, PARTLY: 0.25 + 0.4 * self.intensity, OVERCAST: 1.0, FOG: 0.55,
                DRIZZLE: 0.85, RAIN: 0.9, SNOW: 0.85, THUNDER: 1.0}[self.kind]
        if self.kind == CLEAR and self.cloud_cover:
            base = min(0.25, self.cloud_cover / 300.0)
        return base

    @property
    def darkness(self) -> float:
        """How grey/heavy the clouds are."""
        return {CLEAR: 0.0, PARTLY: 0.05, OVERCAST: 0.3, FOG: 0.1, DRIZZLE: 0.35,
                RAIN: 0.35 + 0.25 * self.intensity, SNOW: 0.2,
                THUNDER: 0.65 + 0.2 * self.intensity}[self.kind]


_pass_cache: dict = {}


def _moon_pass_cached(now_utc: dt.datetime, lat: float, lon: float):
    """Moonrise/moonset of the Moon's current pass, reused while still inside it."""
    from . import moon as _moon
    key = (round(lat, 3), round(lon, 3))
    hit = _pass_cache.get(key)
    if hit is not None and hit[0] is not None and hit[1] is not None and hit[0] <= now_utc <= hit[1]:
        return hit
    _up, rise, sett = _moon.moon_pass(now_utc, lat, lon)
    if len(_pass_cache) > 64:
        _pass_cache.clear()
    _pass_cache[key] = (rise, sett)
    return rise, sett


DAY_MOON_FADE = 0.3       # the daytime Moon is drawn at 70% strength, washed out by the sky


def arc_point(progress: float, r: QRectF, rad: float) -> Optional[QPointF]:
    """Where the Sun or Moon sits on its arc across the scene.

    progress 0 = rising: just below the horizon at the bottom-left.
    progress 0.5 = highest: top middle. progress 1 = setting: just below the
    bottom-right. Outside 0..1 it's below the horizon (None)."""
    if progress is None or not 0.0 <= progress <= 1.0:
        return None
    w, h = r.width(), r.height()
    x0, x1 = r.left() + w * 0.05, r.right() - w * 0.05
    horizon = r.bottom() + rad * 1.05            # fully hidden at the very start and end
    apex = r.top() + max(rad * 1.35, h * 0.2)
    x = x0 + (x1 - x0) * progress
    y = horizon - (horizon - apex) * math.sin(math.pi * progress)
    return QPointF(x, y)


def conditions_from_forecast(fc, now: Optional[float] = None) -> Conditions:
    """Build scene conditions from a Forecast, advancing the location's clock
    by the time elapsed since download so the sun keeps moving."""
    c = fc.current
    kind, intensity = classify(c.weather_code)
    cond = Conditions(kind=kind, intensity=intensity, wind_kmh=c.wind_speed or 0.0,
                      cloud_cover=c.cloud_cover)
    if c.wind_direction is not None:
        s = -math.sin(math.radians(c.wind_direction))   # direction wind comes FROM
        cond.wind_sign = 1.0 if s >= 0 else -1.0
    now = time.time() if now is None else now

    local_now = None
    try:
        local_now = dt.datetime.fromisoformat(c.time)
        if fc.fetched_at:
            local_now += dt.timedelta(seconds=max(0.0, min(now - fc.fetched_at, 6 * 3600)))
    except (ValueError, TypeError):
        pass
    today = fc.daily[0] if fc.daily else None
    try:
        rise = dt.datetime.fromisoformat(today.sunrise) if today and today.sunrise else None
        sset = dt.datetime.fromisoformat(today.sunset) if today and today.sunset else None
    except ValueError:
        rise = sset = None

    if local_now and rise and sset and sset > rise:
        # compare by time of day so a long-running app keeps looking right
        m = local_now.hour * 60 + local_now.minute + local_now.second / 60
        r = rise.hour * 60 + rise.minute
        s_ = sset.hour * 60 + sset.minute
        tw = 40.0
        if r + tw <= m <= s_ - tw:
            cond.daylight = 1.0
        elif m < r - tw or m > s_ + tw:
            cond.daylight = 0.0
        else:
            edge = r if abs(m - r) < abs(m - s_) else s_
            cond.daylight = max(0.0, min(1.0, 0.5 + (m - edge) / (2 * tw) * (1 if edge == r else -1)))
            cond.twilight = 1.0 - abs(m - edge) / tw
        cond.sun_progress = max(-0.2, min(1.2, (m - r) / max(1.0, s_ - r)))
        cond.sun_rise_ts = now - (m - r) * 60.0
        cond.sun_set_ts = now + (s_ - m) * 60.0
    else:
        cond.daylight = 1.0 if c.is_day else 0.0
        cond.sun_progress = 0.35
    cond.moon_age = moon_phase(dt.datetime.now(dt.timezone.utc))
    try:
        from . import moon as _moon
        now_utc = dt.datetime.now(dt.timezone.utc)
        ph = _moon.moon_phase(now_utc)
        cond.moon_phase_angle, cond.moon_limb = ph.phase_angle, ph.bright_limb
        loc = fc.location
        q, alt, _az, h0 = _moon.sky_geometry(_moon.julian_day(now_utc), loc.latitude, loc.longitude)
        cond.moon_rotation, cond.moon_up, cond.moon_altitude = q, alt > h0, alt
        if cond.moon_up:
            rise, sett = _moon_pass_cached(now_utc, loc.latitude, loc.longitude)
            if rise is not None and sett is not None:
                cond.moon_rise_ts, cond.moon_set_ts = rise.timestamp(), sett.timestamp()
                cond.moon_progress = cond.moon_progress_at(now_utc.timestamp())
    except Exception:          # pragma: no cover - fall back to the drawn moon
        pass
    cond.southern = fc.location.latitude < 0
    return cond


# --------------------------------------------------------- animation clock
class AnimationClock(QObject):
    """Shared timer driving every registered animated widget."""

    _instance: Optional["AnimationClock"] = None

    def __init__(self):
        super().__init__()
        self._targets: "weakref.WeakSet[QWidget]" = weakref.WeakSet()
        self.enabled = True
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / FPS))
        self.timer.timeout.connect(self._tick)
        self._last = time.monotonic()
        self.ticks = 0

    @classmethod
    def instance(cls) -> "AnimationClock":
        if cls._instance is None:
            cls._instance = AnimationClock()
        return cls._instance

    def register(self, w: QWidget) -> None:
        self._targets.add(w)
        self.reevaluate()

    def unregister(self, w: QWidget) -> None:
        self._targets.discard(w)
        self.reevaluate()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self.reevaluate()

    @staticmethod
    def _showing(w: QWidget) -> bool:
        try:
            win = w.window()
            return w.isVisible() and not win.isMinimized()
        except RuntimeError:          # C++ object already deleted
            return False

    def visible_targets(self) -> list:
        return [w for w in list(self._targets) if self._showing(w)]

    def reevaluate(self) -> None:
        want = self.enabled and bool(self.visible_targets())
        if want and not self.timer.isActive():
            self._last = time.monotonic()
            self.timer.start()
        elif not want and self.timer.isActive():
            self.timer.stop()

    def _tick(self) -> None:
        now = time.monotonic()
        dt_ = min(0.1, now - self._last)       # clamp after stalls/suspend
        self._last = now
        targets = self.visible_targets()
        if not targets or not self.enabled:
            self.timer.stop()
            return
        self.ticks += 1
        for w in targets:
            try:
                w.advance(dt_)                  # time always advances...
                if self.ticks % w.update_every == 0:
                    w.update()                  # ...but small widgets repaint less often
            except RuntimeError:
                pass


class _Animated(QWidget):
    """Base: registers with the clock and pauses when hidden."""

    update_every = 1            # repaint every Nth clock tick

    def __init__(self, parent=None):
        super().__init__(parent)
        self.t = 0.0
        AnimationClock.instance().register(self)

    def advance(self, dt_: float) -> None:
        self.t += dt_

    def showEvent(self, e):
        super().showEvent(e)
        AnimationClock.instance().reevaluate()

    def hideEvent(self, e):
        super().hideEvent(e)
        QTimer.singleShot(0, AnimationClock.instance().reevaluate)

    def changeEvent(self, e):
        super().changeEvent(e)
        AnimationClock.instance().reevaluate()


# ----------------------------------------------------------- cloud sprites
_SPRITE_CACHE: dict[tuple, QPixmap] = {}
_SPRITE_CACHE_MAX = 96


def cloud_sprite(w: int, h: int, darkness: float, seed: int) -> QPixmap:
    """A soft, volumetric cloud: overlapping lit puffs with shaded undersides."""
    dk = round(darkness * 20) / 20
    key = (w, h, dk, seed)
    pix = _SPRITE_CACHE.get(key)
    if pix is not None:
        return pix
    rng = random.Random(seed)
    pix = QPixmap(max(1, w), max(1, h))
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lit = _mix(QColor(255, 255, 255), QColor(150, 158, 170), dk)
        body = _mix(QColor(236, 240, 246), QColor(105, 113, 126), dk)
        shade = _mix(QColor(190, 198, 212), QColor(62, 68, 80), dk)
        p.setPen(Qt.PenStyle.NoPen)
        base_y = h * 0.72
        puffs = []
        n = rng.randint(6, 9)
        for i in range(n):
            fx = (i + 0.5) / n
            r = h * (0.22 + 0.22 * math.sin(math.pi * fx)) * rng.uniform(0.85, 1.15)
            cx = w * (0.12 + 0.76 * fx) + rng.uniform(-w * 0.03, w * 0.03)
            cy = base_y - r * rng.uniform(0.35, 0.75)
            r = min(r, cy - 1, cx - 1, w - cx - 1)          # stay inside the sprite (no flat edges)
            puffs.append((cx, cy, max(2.0, r)))
        # flat-ish base
        puffs.append((w * 0.5, base_y - h * 0.08, w * 0.38))
        for cx, cy, r in sorted(puffs, key=lambda x: x[2]):
            g = QRadialGradient(QPointF(cx - r * 0.25, cy - r * 0.35), r * 1.25)
            g.setColorAt(0.0, lit)
            g.setColorAt(0.55, body)
            edge = QColor(body)
            edge.setAlpha(0)
            g.setColorAt(1.0, edge)
            p.setBrush(g)
            if (cx, cy, r) == puffs[-1]:
                p.drawEllipse(QRectF(cx - r, cy - h * 0.16, 2 * r, h * 0.32))
            else:
                p.drawEllipse(QPointF(cx, cy), r, r)
        # shaded underside
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        sg = QLinearGradient(0, h * 0.35, 0, h)
        s0 = QColor(shade); s0.setAlpha(0)
        s1 = QColor(shade); s1.setAlpha(200)
        sg.setColorAt(0, s0)
        sg.setColorAt(1, s1)
        p.fillRect(QRectF(0, 0, w, h), sg)
    finally:
        p.end()
    if len(_SPRITE_CACHE) >= _SPRITE_CACHE_MAX:
        _SPRITE_CACHE.pop(next(iter(_SPRITE_CACHE)))
    _SPRITE_CACHE[key] = pix
    return pix


# -------------------------------------------------------------- the scene
class WeatherScene(_Animated):
    """Full animated sky scene."""

    def __init__(self, parent=None, seed: int = 7, scrim: bool = True, rounded: float = 10.0):
        super().__init__(parent)
        self.cond = Conditions()
        self.clock = time.time             # wall clock for the Sun/Moon arc (tests can replace it)
        self.sun_drawn = None              # (x, y, progress) of the last painted Sun, for tests
        self.moon_drawn = None
        # mini forecast in the bottom-right corner (see forecast_strip.py)
        self.forecast_days: list = []
        self.forecast_today = None
        self.forecast_unit = "C"
        self.avoid_widgets: list = []      # text on the scene the forecast must keep clear of
        self.forecast_layout = None        # what the last paint showed (for tests)
        self.scrim = scrim                 # darken left side so overlaid text stays readable
        self.rounded = rounded
        self._rng = random.Random(seed)
        self._seed = seed
        self._size = (0, 0)
        self._clouds: list[dict] = []
        self._drops: list[list[float]] = []
        self._splashes: list[list[float]] = []
        self._flakes: list[list[float]] = []
        self._stars: list[tuple[float, float, float, float]] = []
        self._fog: list[list[float]] = []
        self._flash = 0.0
        self._bolt: Optional[list[QPointF]] = None
        self._next_strike = 3.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 110)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, rounded <= 0)

    # ---------------------------------------------------------- state
    def set_forecast(self, days: list, today, temp_unit: str) -> None:
        """Days for the mini forecast (forecast_strip.Day), today's date at the location,
        and the temperature unit. An empty list hides it."""
        self.forecast_days, self.forecast_today, self.forecast_unit = list(days), today, temp_unit
        self.update()

    def _avoid_rects(self) -> list:
        """Where text actually is on the scene (a label's text, not its whole width)."""
        from PyQt6.QtGui import QFontMetricsF
        out = []
        for wdg in self.avoid_widgets:
            try:
                if not wdg.isVisible() or not wdg.text():
                    continue
                g = QRectF(wdg.geometry())
                if wdg.parentWidget() is not self:
                    g.moveTopLeft(QPointF(wdg.mapTo(self, wdg.rect().topLeft())))
                if wdg.alignment() & Qt.AlignmentFlag.AlignRight:
                    out.append(g)
                    continue
                fm = QFontMetricsF(wdg.font())
                flags = int(Qt.TextFlag.TextWordWrap.value) if wdg.wordWrap() else 0
                br = fm.boundingRect(QRectF(0, 0, g.width(), 10000), flags, wdg.text())
                out.append(QRectF(g.left(), g.top(), min(g.width(), br.width() + 2), g.height()))
            except RuntimeError:             # label already deleted
                continue
        return out

    def _paint_forecast(self, p: QPainter, r: QRectF) -> None:
        self.forecast_layout = None
        if not self.forecast_days:
            return
        from . import forecast_strip as FS
        # Fixed in the bottom-right corner (1.11.1): the Sun and Moon simply pass behind it
        # as they rise and set - it's painted after them, over its soft translucent shade.
        lay = FS.plan(r, self.forecast_days, self.forecast_today, self.font(),
                      self._avoid_rects(), (), self.forecast_unit)
        self.forecast_layout = lay
        if lay is not None:
            FS.paint(p, lay, self.t, self.forecast_unit)

    def set_conditions(self, cond: Conditions) -> None:
        changed = (cond.kind, round(cond.intensity, 2), round(cond.darkness, 2)) != \
                  (self.cond.kind, round(self.cond.intensity, 2), round(self.cond.darkness, 2))
        self.cond = cond
        if changed or not self._clouds:
            self._rebuild()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rebuild()

    def _rebuild(self) -> None:
        """(Re)create particles for the current size and weather."""
        w, h = max(1, self.width()), max(1, self.height())
        self._size = (w, h)
        rng = random.Random(self._seed)
        c = self.cond
        area = (w * h) / (600 * 220)

        self._stars = [(rng.random() * w, rng.random() * h * 0.75, rng.uniform(0.6, 1.6),
                        rng.uniform(0, math.tau)) for _ in range(int(70 * area) + 10)]

        amount = c.cloud_amount
        self._clouds = []
        layers = [(0.55, 0.35, 0.6), (0.8, 0.6, 0.85), (1.0, 1.0, 1.0)]   # scale, speed, opacity
        n_per_layer = 0 if amount <= 0.01 else max(1, int(round(1 + amount * 4 * max(1.0, w / 500))))
        for li, (scale, speed, opacity) in enumerate(layers):
            if amount < 0.3 and li == 0:
                continue
            for i in range(n_per_layer):
                cw = int(w * rng.uniform(0.32, 0.5) * scale * (0.8 + amount * 0.5))
                ch = int(cw * rng.uniform(0.42, 0.55))
                x = (i + rng.random() * 0.6) / n_per_layer * (w + cw) - cw * 0.5
                ytop = -ch * 0.25 if amount > 0.8 else h * 0.02
                y = rng.uniform(ytop, h * (0.18 + 0.25 * (1 - amount)) + ch * 0.0) - ch * 0.15 * li
                self._clouds.append(dict(x=x, y=y, w=cw, h=ch, layer=li, speed=speed,
                                         opacity=opacity * (0.75 + 0.25 * amount),
                                         seed=self._seed * 100 + li * 10 + i))

        if amount >= 0.8:
            # a second, lower deck so heavy cloud covers most of the sky
            n_deck = max(3, int(3 * max(1.0, w / 400)))
            for i in range(n_deck):
                cw = int(w * rng.uniform(0.45, 0.65))
                ch = int(cw * rng.uniform(0.38, 0.48))
                x = (i + rng.random() * 0.5) / n_deck * (w + cw) - cw * 0.5
                y = rng.uniform(h * 0.12, h * 0.32)
                self._clouds.append(dict(x=x, y=y, w=cw, h=ch, layer=-1, speed=0.25,
                                         opacity=0.55 + 0.3 * c.darkness,
                                         seed=self._seed * 100 + 90 + i))

        self._drops, self._splashes, self._flakes, self._fog = [], [], [], []
        if c.kind in (RAIN, THUNDER, DRIZZLE):
            heavy = c.kind != DRIZZLE
            n = int((60 + 200 * c.intensity) * area) if heavy else int((90 + 140 * c.intensity) * area)
            for _ in range(n):
                self._drops.append([rng.random() * w, rng.random() * h,
                                    rng.uniform(0.75, 1.0), rng.random()])
        if c.kind == SNOW:
            for _ in range(int((40 + 160 * c.intensity) * area)):
                self._flakes.append([rng.random() * w, rng.random() * h, rng.uniform(1.0, 3.2),
                                     rng.uniform(0, math.tau), rng.uniform(0.6, 1.2)])
        if c.kind == FOG or (c.kind in (DRIZZLE,) and c.intensity > 0.6):
            for i in range(5):
                self._fog.append([rng.random() * w, h * (0.3 + 0.14 * i), rng.uniform(8, 18),
                                  rng.uniform(0.25, 0.5)])

    # ---------------------------------------------------------- motion
    def advance(self, dt_: float) -> None:
        super().advance(dt_)
        w, h = self._size
        if w <= 1:
            return
        c = self.cond
        wind = 8 + min(c.wind_kmh, 80) * 0.9          # px/s at front layer
        sign = c.wind_sign
        for cl in self._clouds:
            cl["x"] += sign * wind * cl["speed"] * dt_
            if sign > 0 and cl["x"] > w + 10:
                cl["x"] = -cl["w"] - 10
            elif sign < 0 and cl["x"] < -cl["w"] - 10:
                cl["x"] = w + 10

        slant = sign * min(0.45, 0.06 + c.wind_kmh / 120)
        if self._drops:
            heavy = c.kind != DRIZZLE
            fall = h * (2.6 if heavy else 1.3)
            for d in self._drops:
                d[1] += fall * d[2] * dt_
                d[0] += fall * d[2] * slant * dt_
                if d[1] > h:
                    if heavy and d[3] < 0.5 and len(self._splashes) < 60:
                        self._splashes.append([d[0], h - self._rng.uniform(2, 14), 0.0])
                    d[1] -= h + 20
                    d[0] = self._rng.random() * w
                    d[3] = self._rng.random()
                if d[0] > w + 20:
                    d[0] -= w + 40
                elif d[0] < -20:
                    d[0] += w + 40
            for s in self._splashes:
                s[2] += dt_
            self._splashes = [s for s in self._splashes if s[2] < 0.25]

        for f in self._flakes:
            f[1] += (14 + 22 * f[2]) * f[4] * dt_
            f[3] += dt_ * 1.4
            f[0] += (math.sin(f[3]) * 14 + sign * wind * 0.4) * dt_
            if f[1] > h + 4:
                f[1] = -4
                f[0] = self._rng.random() * w
            if f[0] > w + 6:
                f[0] = -6
            elif f[0] < -6:
                f[0] = w + 6

        for fg in self._fog:
            fg[0] += sign * fg[2] * dt_
            if fg[0] > w * 1.5:
                fg[0] = -w * 0.5
            elif fg[0] < -w * 0.5:
                fg[0] = w * 1.5

        if c.kind == THUNDER:
            self._flash = max(0.0, self._flash - dt_ * 2.6)
            self._next_strike -= dt_
            if self._next_strike <= 0:
                self._strike()
                self._next_strike = self._rng.uniform(2.5, 7.0) / (0.6 + 0.6 * c.intensity)

    def _strike(self) -> None:
        w, h = self._size
        x = self._rng.uniform(w * 0.35, w * 0.9)
        y = 0.0
        pts = [QPointF(x, y)]
        while y < h * self._rng.uniform(0.55, 0.85):
            y += self._rng.uniform(8, 20)
            x += self._rng.uniform(-14, 14)
            pts.append(QPointF(x, y))
        self._bolt = pts
        self._flash = 1.0

    # ---------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            self.paint_scene(p, QRectF(self.rect()))
        finally:
            p.end()

    def sky_colors(self) -> tuple[QColor, QColor]:
        c = self.cond
        day_top, day_bot = QColor("#2f7fd6"), QColor("#9fd2f6")
        nit_top, nit_bot = QColor("#0a1430"), QColor("#24365c")
        tw_top, tw_bot = QColor("#40548f"), QColor("#f2a15c")
        top = _mix(nit_top, day_top, c.daylight)
        bot = _mix(nit_bot, day_bot, c.daylight)
        if c.twilight > 0:
            top = _mix(top, tw_top, c.twilight * 0.7)
            bot = _mix(bot, tw_bot, c.twilight * 0.85)
        grey = min(1.0, c.cloud_amount * 0.75 + c.darkness * 0.35) if c.cloud_amount > 0.5 else 0.0
        g_top = _mix(QColor("#1b2129"), QColor("#7c8998"), c.daylight)
        g_bot = _mix(QColor("#39424f"), QColor("#bac4cd"), c.daylight)
        if c.kind == THUNDER:
            g_top, g_bot = _mix(QColor("#14181e"), QColor("#2c333c"), c.daylight), \
                _mix(QColor("#2a3038"), QColor("#5b6570"), c.daylight)
        if c.kind == FOG:
            g_top, g_bot = _mix(QColor("#2a3038"), QColor("#a9b2ba"), c.daylight), \
                _mix(QColor("#3c434c"), QColor("#d3d8dc"), c.daylight)
            grey = 0.85
        return _mix(top, g_top, grey), _mix(bot, g_bot, grey)

    def paint_scene(self, p: QPainter, r: QRectF) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.cond
        w, h = r.width(), r.height()
        p.save()
        if self.rounded > 0:
            clip = QPainterPath()
            clip.addRoundedRect(r, self.rounded, self.rounded)
            p.setClipPath(clip)

        top, bot = self.sky_colors()
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, top)
        g.setColorAt(1, bot)
        p.fillRect(r, g)

        amount = c.cloud_amount
        # stars
        if c.daylight < 0.6 and amount < 0.95:
            vis = (1 - c.daylight / 0.6) * (1 - amount * 0.8)
            p.setPen(Qt.PenStyle.NoPen)
            for sx, sy, sz, ph in self._stars:
                a = vis * (0.55 + 0.45 * math.sin(self.t * 1.7 + ph))
                p.setBrush(QColor(255, 255, 240, int(220 * max(0.0, a))))
                p.drawEllipse(QPointF(r.left() + sx, r.top() + sy), sz * 0.6, sz * 0.6)

        # sun or moon
        if amount < 0.97:
            veil = 1 - max(0.0, amount - 0.4) / 0.6 if amount > 0.4 else 1.0
            if c.daylight > 0.05:
                self._paint_sun(p, r, veil * min(1.0, c.daylight * 1.5))
            # The Moon is shown whenever it's really above the horizon - by day too (it
            # often is). In daylight it's paler, like the real daytime Moon.
            self._paint_moon(p, r, veil * (1.0 - DAY_MOON_FADE * c.daylight))
        else:
            self.sun_drawn = self.moon_drawn = None

        # clouds back -> front, flash brightens them
        for cl in sorted(self._clouds, key=lambda d: d["layer"]):
            dk = c.darkness * (0.75 + 0.12 * cl["layer"])
            if c.daylight < 0.5:
                dk = min(1.0, dk + 0.5 * (1 - c.daylight * 2))
            spr = cloud_sprite(cl["w"], cl["h"], dk, cl["seed"])
            p.setOpacity(cl["opacity"] * (0.9 if c.daylight > 0.2 else 0.8))
            p.drawPixmap(QPointF(r.left() + cl["x"], r.top() + cl["y"]), spr)
        p.setOpacity(1.0)

        # fog bands
        if self._fog:
            p.setPen(Qt.PenStyle.NoPen)
            fog_col = _mix(QColor(70, 78, 88), QColor(235, 238, 240), c.daylight)
            for fx, fy, _sp, alpha in self._fog:
                rg = QRadialGradient(QPointF(r.left() + fx, r.top() + fy), w * 0.55)
                c0 = QColor(fog_col); c0.setAlpha(int(255 * alpha * c.intensity))
                c1 = QColor(fog_col); c1.setAlpha(0)
                rg.setColorAt(0, c0)
                rg.setColorAt(1, c1)
                p.setBrush(rg)
                p.drawEllipse(QPointF(r.left() + fx, r.top() + fy), w * 0.55, h * 0.16)

        # precipitation
        if self._drops:
            heavy = c.kind != DRIZZLE
            slant = c.wind_sign * min(0.45, 0.06 + c.wind_kmh / 120)
            length = h * (0.075 if heavy else 0.035)
            base = _mix(QColor(150, 170, 200), QColor(205, 222, 245), c.daylight)
            for depth_band, alpha in ((0.85, 110), (1.0, 170)):
                col = QColor(base)
                col.setAlpha(alpha if heavy else int(alpha * 0.7))
                p.setPen(QPen(col, 1.4 if depth_band == 1.0 else 1.0, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap))
                ox, oy = r.left(), r.top()
                lines = [QLineF(ox + x, oy + y, ox + x - slant * length * spd, oy + y - length * spd)
                         for x, y, spd, _ in self._drops if (spd > 0.88) == (depth_band == 1.0)]
                if lines:
                    # Fast-moving 1px streaks look identical without antialiasing,
                    # and this halves the frame cost in heavy rain.
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                    p.drawLines(lines)          # one batched call instead of one per drop
                    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._splashes:
                p.setBrush(Qt.BrushStyle.NoBrush)
                for sx, sy, age in self._splashes:
                    k = age / 0.25
                    col = QColor(base); col.setAlpha(int(150 * (1 - k)))
                    p.setPen(QPen(col, 1.0))
                    rw = 2 + 7 * k
                    p.drawArc(QRectF(r.left() + sx - rw, r.top() + sy - rw * 0.35, 2 * rw, rw * 0.7),
                              0, 180 * 16)
        if self._flakes:
            p.setPen(Qt.PenStyle.NoPen)
            for x, y, sz, _ph, _sp in self._flakes:
                p.setBrush(QColor(255, 255, 255, int(150 + 30 * sz)))
                p.drawEllipse(QPointF(r.left() + x, r.top() + y), sz, sz)

        # lightning
        if c.kind == THUNDER and self._flash > 0:
            if self._bolt and self._flash > 0.45:
                path = QPainterPath(self._bolt[0] + r.topLeft())
                for pt in self._bolt[1:]:
                    path.lineTo(pt + r.topLeft())
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(QColor(180, 200, 255, 90), 7, cap=Qt.PenCapStyle.RoundCap,
                              join=Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
                p.setPen(QPen(QColor(255, 255, 255, 240), 2, cap=Qt.PenCapStyle.RoundCap,
                              join=Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
            flicker = self._flash * (0.6 + 0.4 * abs(math.sin(self._flash * 25)))
            p.fillRect(r, QColor(235, 240, 255, int(120 * flicker)))

        # readability scrim behind overlaid text
        if self.scrim:
            sg = QLinearGradient(r.left(), 0, r.left() + w * 0.7, 0)
            sg.setColorAt(0, QColor(0, 0, 0, 105))
            sg.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(r, sg)
        self._paint_forecast(p, r)
        p.restore()

    def _paint_sun(self, p: QPainter, r: QRectF, alpha: float) -> None:
        c = self.cond
        if alpha <= 0.01:
            return
        w, h = r.width(), r.height()
        rad = min(w, h) * 0.11
        prog = c.sun_progress_at(self.clock())
        pt = arc_point(prog, r, rad)
        self.sun_drawn = None
        if pt is None:
            return                                   # below the horizon
        cx, cy = pt.x(), pt.y()
        self.sun_drawn = (cx, cy, prog)
        warm = max(c.twilight, 1 - math.sin(math.pi * prog) * 1.6)
        core = _mix(QColor(255, 248, 215), QColor(255, 190, 110), max(0.0, min(1.0, warm)))
        p.save()
        p.setOpacity(alpha)
        glow = QRadialGradient(QPointF(cx, cy), rad * 4.2)
        g0 = QColor(core); g0.setAlpha(150)
        g1 = QColor(core); g1.setAlpha(0)
        glow.setColorAt(0, g0)
        glow.setColorAt(0.35, QColor(core.red(), core.green(), core.blue(), 55))
        glow.setColorAt(1, g1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), rad * 4.2, rad * 4.2)
        # slowly rotating soft rays
        p.translate(cx, cy)
        p.rotate(self.t * 6)
        ray = QColor(core); ray.setAlpha(40)
        p.setBrush(ray)
        for i in range(12):
            p.rotate(30)
            pth = QPainterPath()
            pth.moveTo(-rad * 0.18, 0)
            pth.lineTo(0, -rad * (2.4 + 0.25 * math.sin(self.t * 2 + i)))
            pth.lineTo(rad * 0.18, 0)
            p.drawPath(pth)
        p.resetTransform()
        disc = QRadialGradient(QPointF(cx - rad * 0.3, cy - rad * 0.3), rad * 1.3)
        disc.setColorAt(0, QColor(255, 255, 245))
        disc.setColorAt(1, core)
        p.setBrush(disc)
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.restore()

    def _paint_moon(self, p: QPainter, r: QRectF, alpha: float) -> None:
        self.moon_drawn = None
        if alpha <= 0.01 or not self.cond.moon_up:
            return                                   # only drawn when it's really in the sky
        w, h = r.width(), r.height()
        rad = min(w, h) * 0.09
        # the same arc as the Sun: rises bottom-left, highest mid-sky, sets bottom-right
        prog = self.cond.moon_progress_at(self.clock())
        pt = arc_point(prog, r, rad)
        if pt is None:
            return
        cx, cy = pt.x(), pt.y()
        self.moon_drawn = (cx, cy, prog)
        day = max(0.0, min(1.0, self.cond.daylight))
        p.save()
        p.setOpacity(alpha)
        glow = QRadialGradient(QPointF(cx, cy), rad * 3)
        glow.setColorAt(0, QColor(220, 230, 255, int(70 * (1 - day))))   # no night glow by day
        glow.setColorAt(1, QColor(220, 230, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), rad * 3, rad * 3)
        if self.cond.moon_phase_angle is not None:
            # the same high-resolution, correctly lit moon as the Moon tab
            try:
                from .moon_render import render_moon
                dpr = self.devicePixelRatioF() if self.isVisible() else 1.0
                px = max(16, int(round(rad * 2 * dpr / 8)) * 8)       # bucketed for the cache
                img = render_moon(px, self.cond.moon_phase_angle, self.cond.moon_limb,
                                  self.cond.southern, rotation=self.cond.moon_rotation)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                target = QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad)
                # Night: drawn as is (dark side with earthshine). Day: the unlit part
                # can't be seen against a bright sky, so it's blended with "screen"
                # (dark adds nothing, the lit part brightens the blue) - cross-faded
                # through twilight so nothing jumps.
                if day < 1.0:
                    p.setOpacity(alpha * (1 - day))
                    p.drawImage(target, img)
                if day > 0.0:
                    p.setOpacity(alpha * day)
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                    p.drawImage(target, img)
                p.restore()
                return
            except Exception:
                pass                                                   # fall back to drawn moon
        p.setBrush(QColor(238, 238, 226))
        p.drawEllipse(QPointF(cx, cy), rad, rad)
        # a few soft maria
        p.setBrush(QColor(200, 200, 190, 120))
        p.drawEllipse(QPointF(cx - rad * 0.3, cy - rad * 0.2), rad * 0.28, rad * 0.22)
        p.drawEllipse(QPointF(cx + rad * 0.25, cy + rad * 0.25), rad * 0.2, rad * 0.16)
        # phase: earthshine-dark disc, then the lit part = half disc +/- terminator ellipse
        age = self.cond.moon_age
        illum = (1 - math.cos(age * math.tau)) / 2          # 0 new .. 1 full
        if illum < 0.985:
            waxing = age < 0.5
            lit_right = waxing != self.cond.southern        # mirrored south of the equator
            disc = QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad)
            half = QPainterPath()
            half.moveTo(cx, cy - rad)
            half.arcTo(disc, 90, -180 if lit_right else 180)
            half.closeSubpath()
            tw = rad * abs(1 - 2 * illum)
            ell = QPainterPath()
            ell.addEllipse(QPointF(cx, cy), tw, rad)
            lit = half.united(ell) if illum >= 0.5 else half.subtracted(ell)
            # repaint the whole disc dim, then the lit part bright
            p.setBrush(_mix(self.sky_colors()[0], QColor(70, 72, 80), 0.35))
            p.drawEllipse(QPointF(cx, cy), rad * 1.01, rad * 1.01)
            p.setBrush(QColor(238, 238, 226))
            p.drawPath(lit)
            p.setBrush(QColor(200, 200, 190, 110))
            mar = QPainterPath()
            mar.addEllipse(QPointF(cx - rad * 0.3, cy - rad * 0.2), rad * 0.28, rad * 0.22)
            mar.addEllipse(QPointF(cx + rad * 0.25, cy + rad * 0.25), rad * 0.2, rad * 0.16)
            p.drawPath(mar.intersected(lit))
        p.restore()


# ------------------------------------------------------------ small icons
def _draw_cloud(p: QPainter, cx: float, cy: float, s: float, dark: float = 0.0) -> None:
    top = _mix(QColor(255, 255, 255), QColor(140, 148, 160), dark)
    bot = _mix(QColor(200, 208, 220), QColor(90, 96, 108), dark)
    g = QLinearGradient(0, cy - s * 0.5, 0, cy + s * 0.35)
    g.setColorAt(0, top)
    g.setColorAt(1, bot)
    path = QPainterPath()
    path.addEllipse(QPointF(cx - s * 0.32, cy), s * 0.3, s * 0.26)
    path.addEllipse(QPointF(cx + s * 0.02, cy - s * 0.18), s * 0.36, s * 0.34)
    path.addEllipse(QPointF(cx + s * 0.36, cy + s * 0.02), s * 0.26, s * 0.24)
    path.addRoundedRect(QRectF(cx - s * 0.6, cy - s * 0.02, s * 1.2, s * 0.3), s * 0.15, s * 0.15)
    path.setFillRule(Qt.FillRule.WindingFill)
    p.setPen(QPen(QColor(0, 0, 0, 35), max(0.6, s * 0.02)))
    p.setBrush(g)
    p.drawPath(path.simplified())


def _draw_sun(p: QPainter, cx: float, cy: float, rad: float, t: float) -> None:
    p.save()
    p.translate(cx, cy)
    p.rotate(t * 30)
    p.setPen(QPen(QColor(255, 186, 40), max(1.0, rad * 0.18), cap=Qt.PenCapStyle.RoundCap))
    for _ in range(8):
        p.rotate(45)
        p.drawLine(QPointF(0, -rad * 1.35), QPointF(0, -rad * (1.75 + 0.12 * math.sin(t * 4))))
    p.restore()
    g = QRadialGradient(QPointF(cx - rad * 0.3, cy - rad * 0.3), rad * 1.4)
    g.setColorAt(0, QColor(255, 240, 150))
    g.setColorAt(1, QColor(255, 176, 30))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), rad, rad)


def _draw_moon(p: QPainter, cx: float, cy: float, rad: float, bg: QColor) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(240, 236, 210))
    p.drawEllipse(QPointF(cx, cy), rad, rad)
    p.setBrush(bg)
    p.drawEllipse(QPointF(cx + rad * 0.45, cy - rad * 0.25), rad * 0.85, rad * 0.85)


def _draw_wind(p: QPainter, rect: QRectF, t: float) -> None:
    """Three gusts sweeping across, each fading in and out (the windy icon)."""
    s = min(rect.width(), rect.height())
    p.save()
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i, (y, length) in enumerate(((0.70, 0.62), (0.82, 0.78), (0.93, 0.5))):
        ph = (t * 0.55 + i * 0.33) % 1.0
        x0 = rect.left() + rect.width() * (-0.35 + 0.75 * ph)
        a = int(230 * math.sin(math.pi * ph))
        p.setPen(QPen(QColor(235, 242, 252, a), max(1.0, s * 0.055), cap=Qt.PenCapStyle.RoundCap))
        yy = rect.top() + rect.height() * y
        path = QPainterPath(QPointF(x0, yy))
        L = rect.width() * length
        path.cubicTo(QPointF(x0 + L * 0.35, yy - s * 0.05), QPointF(x0 + L * 0.65, yy + s * 0.05),
                     QPointF(x0 + L, yy - s * 0.02))
        path.arcTo(QRectF(x0 + L - s * 0.07, yy - s * 0.16, s * 0.14, s * 0.14), 270, 250)
        p.drawPath(path)
    p.restore()


def paint_icon(p: QPainter, rect: QRectF, code: Optional[int], is_day: bool, t: float,
               bg: Optional[QColor] = None, windy: bool = False) -> None:
    """Animated icon for any weather code, drawn in `rect` at animation time t.
    windy=True adds sweeping gusts below a slightly smaller sky icon."""
    if windy:
        inner = QRectF(rect.left(), rect.top(), rect.width() * 0.86, rect.height() * 0.74)
        paint_icon(p, inner, code, is_day, t, bg)
        p.save()
        p.setClipRect(rect)
        _draw_wind(p, rect, t)
        p.restore()
        return
    kind, inten = classify(code)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    bg = bg or QColor(0, 0, 0, 0)
    p.save()
    p.setClipRect(rect)
    if kind == CLEAR:
        if is_day:
            _draw_sun(p, cx, cy, s * 0.22, t)
        else:
            _draw_moon(p, cx, cy, s * 0.3, bg)
    elif kind == PARTLY:
        if is_day:
            _draw_sun(p, cx - s * 0.14, cy - s * 0.14, s * 0.17, t)
        else:
            _draw_moon(p, cx - s * 0.14, cy - s * 0.16, s * 0.2, bg)
        _draw_cloud(p, cx + s * 0.06 + math.sin(t * 0.8) * s * 0.03, cy + s * 0.12, s * 0.62)
    elif kind == OVERCAST:
        _draw_cloud(p, cx - s * 0.12 + math.sin(t * 0.6) * s * 0.02, cy - s * 0.1, s * 0.5, 0.25)
        _draw_cloud(p, cx + s * 0.05 + math.sin(t * 0.8 + 1) * s * 0.03, cy + s * 0.08, s * 0.66, 0.1)
    elif kind == FOG:
        _draw_cloud(p, cx, cy - s * 0.12, s * 0.6, 0.15)
        p.setPen(QPen(QColor(170, 178, 190), max(1.0, s * 0.05), cap=Qt.PenCapStyle.RoundCap))
        for i in range(3):
            off = math.sin(t * 1.2 + i) * s * 0.08
            y = cy + s * (0.16 + 0.1 * i)
            p.drawLine(QPointF(cx - s * 0.32 + off, y), QPointF(cx + s * 0.32 + off, y))
    else:
        dark = {DRIZZLE: 0.15, RAIN: 0.3, SNOW: 0.1, THUNDER: 0.55}[kind]
        _draw_cloud(p, cx, cy - s * 0.14, s * 0.66, dark)
        top, bottom = cy + s * 0.08, rect.bottom()
        if kind in (RAIN, DRIZZLE, THUNDER):
            heavy = kind != DRIZZLE and inten >= 0.8          # heavy rain: more, faster drops
            n = (5 if heavy else 3) if kind != DRIZZLE else 4
            pen = QPen(QColor(70, 140, 230), max(1.0, s * (0.05 if kind != DRIZZLE else 0.035)),
                       cap=Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            speed = (2.1 if heavy else 1.6) if kind != DRIZZLE else 1.0
            for i in range(n):
                ph = ((t * speed + i / n) % 1.0)
                x = cx + (i - (n - 1) / 2) * s * (0.18 if n <= 4 else 0.12) - ph * s * 0.06
                y = top + ph * (bottom - top)
                L = s * (0.12 if kind != DRIZZLE else 0.06)
                p.drawLine(QPointF(x, y), QPointF(x + s * 0.03, y - L))
        if kind == SNOW:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(130, 170, 220))
            for i in range(3):
                ph = ((t * 0.6 + i / 3) % 1.0)
                x = cx + (i - 1) * s * 0.2 + math.sin(t * 2 + i) * s * 0.04
                y = top + ph * (bottom - top)
                p.drawEllipse(QPointF(x, y), s * 0.045, s * 0.045)
        if kind == THUNDER and (t % 2.2) < 0.45:
            path = QPainterPath()
            path.moveTo(cx + s * 0.02, cy - s * 0.02)
            path.lineTo(cx - s * 0.1, cy + s * 0.2)
            path.lineTo(cx + s * 0.0, cy + s * 0.2)
            path.lineTo(cx - s * 0.08, cy + s * 0.42)
            path.lineTo(cx + s * 0.14, cy + s * 0.12)
            path.lineTo(cx + s * 0.03, cy + s * 0.12)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 210, 40))
            p.drawPath(path)
    p.restore()


class WeatherIcon(_Animated):
    """Small animated weather icon (forecast rows). Repaints at half the clock
    rate (12 fps): plenty for a 30 px icon and saves ~half its CPU."""

    update_every = 2

    def __init__(self, size: int = 34, parent=None, phase: float = 0.0):
        super().__init__(parent)
        self.code: Optional[int] = None
        self.is_day = True
        self.t = phase                     # stagger so rows don't move in lock-step
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_code(self, code: Optional[int], is_day: bool = True) -> None:
        self.code, self.is_day = code, is_day
        self.setToolTip("")
        self.update()

    def paintEvent(self, _e):
        if self.code is None:
            return
        p = QPainter(self)
        try:
            paint_icon(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), self.code, self.is_day, self.t,
                       self.palette().color(self.backgroundRole()))
        finally:
            p.end()
