"""Settings and forecast cache, stored as JSON under the XDG directories.

* Settings: ~/.config/weatherdesk/settings.json
* Cache:    ~/.cache/weatherdesk/<lat>_<lon>.json

All writes are atomic (temp file in the same directory + fsync + os.replace),
so a crash or power loss can never leave a half-written file. A corrupt
settings file is moved aside to settings.json.corrupt-<timestamp> rather than
deleted, and defaults are used.

The environment variables WEATHERDESK_CONFIG_DIR and WEATHERDESK_CACHE_DIR
override the locations (used by the test suite).
"""

from __future__ import annotations

import json
import re
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import APP_ID
from .api import Forecast, forecast_from_dict, forecast_to_dict, WeatherError
from .models import Location
from .units import PRECIP_UNITS, TEMP_UNITS, TIME_FORMATS, WIND_UNITS

log = logging.getLogger(__name__)

MAX_LOCATIONS = 50
REFRESH_CHOICES = (0, 10, 15, 30, 60, 120)   # minutes; 0 = off
WIDGET_SIZES = {"small": (260, 130), "medium": (340, 170), "large": (440, 220)}
WEATHER_SOURCES = ("open-meteo", "met.no")   # preferred forecast source; the other is the automatic backup


def config_dir() -> Path:
    env = os.environ.get("WEATHERDESK_CONFIG_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / APP_ID


def cache_dir() -> Path:
    env = os.environ.get("WEATHERDESK_CACHE_DIR")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(Path.home(), ".cache")
    return Path(base) / APP_ID


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


@dataclass
class Settings:
    locations: list[Location] = field(default_factory=list)
    selected: Optional[str] = None            # Location.key
    temp_unit: str = "C"
    wind_unit: str = "km/h"
    precip_unit: str = "mm"
    time_format: str = "24"                   # "24" (19:30) or "12" (7:30 pm)
    refresh_minutes: int = 30
    show_tray: bool = True
    close_to_tray: bool = False
    window_geometry: str = ""                 # hex-encoded QByteArray
    animations: bool = True                   # animated weather scene and icons
    desktop_widget: bool = False              # floating desktop weather widget
    widget_x: Optional[int] = None
    widget_y: Optional[int] = None
    widget_size: str = "medium"               # small | medium | large
    widget_on_top: bool = False
    earth_clouds: bool = True                 # live clouds on the Earth tabs
    weather_source: str = "open-meteo"        # 1.12 setting; kept in step with provider_chain[0]
    # Weather Providers (1.13): primary first, then backups in order; and when to go back
    # to the primary after it failed (see providers/manager.py RECOVERY)
    provider_chain: list = field(default_factory=lambda: ["open-meteo", "met.no"])
    provider_recovery: str = "30"

    # ---------------------------------------------------------- helpers
    def selected_location(self) -> Optional[Location]:
        for loc in self.locations:
            if loc.key == self.selected:
                return loc
        return self.locations[0] if self.locations else None

    def add_location(self, loc: Location) -> bool:
        """Add a location (no duplicates). Returns True if newly added."""
        if any(l.key == loc.key for l in self.locations):
            self.selected = loc.key
            return False
        if len(self.locations) >= MAX_LOCATIONS:
            raise ValueError(f"You can save at most {MAX_LOCATIONS} locations.")
        self.locations.append(loc)
        self.selected = loc.key
        return True

    def remove_location(self, key: str) -> bool:
        before = len(self.locations)
        self.locations = [l for l in self.locations if l.key != key]
        if self.selected == key:
            self.selected = self.locations[0].key if self.locations else None
        return len(self.locations) != before

    def move_location(self, key: str, delta: int) -> bool:
        idx = next((i for i, l in enumerate(self.locations) if l.key == key), None)
        if idx is None:
            return False
        new = idx + delta
        if not 0 <= new < len(self.locations):
            return False
        self.locations.insert(new, self.locations.pop(idx))
        return True

    # ---------------------------------------------------- (de)serialise
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "locations": [l.to_dict() for l in self.locations],
            "selected": self.selected,
            "temp_unit": self.temp_unit,
            "wind_unit": self.wind_unit,
            "precip_unit": self.precip_unit,
            "time_format": self.time_format,
            "refresh_minutes": self.refresh_minutes,
            "show_tray": self.show_tray,
            "close_to_tray": self.close_to_tray,
            "window_geometry": self.window_geometry,
            "animations": self.animations,
            "desktop_widget": self.desktop_widget,
            "widget_x": self.widget_x,
            "widget_y": self.widget_y,
            "widget_size": self.widget_size,
            "widget_on_top": self.widget_on_top,
            "earth_clouds": self.earth_clouds,
            "weather_source": self.weather_source,
            "provider_chain": list(self.provider_chain),
            "provider_recovery": self.provider_recovery,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        """Build settings, silently replacing any invalid individual value with its default."""
        s = cls()
        if not isinstance(d, dict):
            return s
        locs = []
        for item in d.get("locations") or []:
            try:
                loc = Location.from_dict(item)
                if -90 <= loc.latitude <= 90 and -180 <= loc.longitude <= 180 and \
                        all(l.key != loc.key for l in locs):
                    locs.append(loc)
            except (KeyError, TypeError, ValueError):
                log.warning("Skipping invalid saved location: %r", item)
        s.locations = locs[:MAX_LOCATIONS]
        sel = d.get("selected")
        s.selected = sel if isinstance(sel, str) and any(l.key == sel for l in locs) else \
            (locs[0].key if locs else None)
        if d.get("temp_unit") in TEMP_UNITS:
            s.temp_unit = d["temp_unit"]
        if d.get("wind_unit") in WIND_UNITS:
            s.wind_unit = d["wind_unit"]
        if d.get("precip_unit") in PRECIP_UNITS:
            s.precip_unit = d["precip_unit"]
        if d.get("time_format") in TIME_FORMATS:
            s.time_format = d["time_format"]
        if d.get("refresh_minutes") in REFRESH_CHOICES and not isinstance(d.get("refresh_minutes"), bool):
            s.refresh_minutes = d["refresh_minutes"]
        for k in ("show_tray", "close_to_tray", "animations", "desktop_widget", "widget_on_top", "earth_clouds"):
            if isinstance(d.get(k), bool):
                setattr(s, k, d[k])
        for k in ("widget_x", "widget_y"):
            v = d.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and -20000 < v < 20000:
                setattr(s, k, v)
        if d.get("weather_source") in WEATHER_SOURCES:
            s.weather_source = d["weather_source"]
            if d["weather_source"] == "met.no":          # 1.12 "MET Norway (Open-Meteo as backup)"
                s.provider_chain = ["met.no", "open-meteo"]
        chain = d.get("provider_chain")
        if isinstance(chain, list):
            ids = []
            for x in chain:
                if isinstance(x, str) and re.fullmatch(r"[a-z0-9.\-]{1,40}", x) and x not in ids:
                    ids.append(x)
            if ids:
                s.provider_chain = ids[:10]
        if d.get("provider_recovery") in ("next", "15", "30", "60", "stay"):
            s.provider_recovery = d["provider_recovery"]
        if d.get("widget_size") in WIDGET_SIZES:
            s.widget_size = d["widget_size"]
        if isinstance(d.get("window_geometry"), str):
            s.window_geometry = d["window_geometry"]
        return s


class SettingsStore:
    def __init__(self, directory: Optional[Path] = None):
        self.path = (directory or config_dir()) / "settings.json"
        self.last_error: Optional[str] = None

    def load(self) -> Settings:
        self.last_error = None
        if not self.path.exists():
            return Settings()
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("settings root is not an object")
            return Settings.from_dict(data)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            backup = self.path.with_name(f"settings.json.corrupt-{int(time.time())}")
            try:
                os.replace(self.path, backup)
                self.last_error = (f"Your settings file could not be read and was moved to "
                                   f"{backup.name}. Defaults are being used.")
            except OSError:
                self.last_error = "Your settings file could not be read. Defaults are being used."
            log.warning("Settings load failed (%s); %s", e, self.last_error)
            return Settings()

    def save(self, settings: Settings) -> None:
        atomic_write_json(self.path, settings.to_dict())


class ForecastCache:
    """One JSON file per location holding the last successful forecast."""

    def __init__(self, directory: Optional[Path] = None):
        self.dir = directory or cache_dir()

    def _path(self, loc: Location) -> Path:
        safe = loc.key.replace(",", "_").replace("-", "m")
        return self.dir / f"{safe}.json"

    def save(self, fc: Forecast) -> None:
        try:
            atomic_write_json(self._path(fc.location), forecast_to_dict(fc))
        except OSError as e:
            log.warning("Could not write forecast cache: %s", e)

    def load(self, loc: Location) -> Optional[Forecast]:
        p = self._path(loc)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                fc = forecast_from_dict(json.load(f))
            # Keep the user's saved location metadata (name may have been edited).
            fc.location = loc
            return fc
        except (OSError, ValueError, UnicodeDecodeError, WeatherError) as e:
            log.warning("Ignoring unreadable cache %s: %s", p, e)
            return None

    def remove(self, loc: Location) -> None:
        try:
            self._path(loc).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning("Could not remove cache file: %s", e)

    def clean_orphans(self, keep: list[Location]) -> int:
        """Delete cache files for locations no longer saved. Returns count removed."""
        if not self.dir.exists():
            return 0
        wanted = {self._path(l).name for l in keep}
        removed = 0
        for p in self.dir.glob("*.json"):
            if p.name not in wanted:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        # stale temp files from an interrupted write
        for p in self.dir.glob(".*.tmp"):
            try:
                if time.time() - p.stat().st_mtime > 3600:
                    p.unlink()
            except OSError:
                pass
        return removed
