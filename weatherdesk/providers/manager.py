"""ProviderManager: the single "weather client" the app uses.

  * An ordered chain of providers: the primary, then any number of backups. Each
    update asks them in order until one answers.
  * Recovery: after the primary fails, WeatherDesk returns to it according to the
    chosen behaviour - at the next update, after 15/30/60 minutes, or only when
    the backup in use fails ("stay").
  * Providers that need a key and have none are skipped (and say so).
  * A per-provider quota guard: within its minimum interval, the last forecast
    from that provider for that location is reused instead of asking again, so
    refreshes and retries can't use up a small free allowance.
  * Status for each provider (last success, last error, last test, usage),
    saved to the cache folder so it survives restarts. Never contains keys.
  * Location search always uses Open-Meteo's geocoding (no key needed).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..api import ApiError, DataError, NetworkError, WeatherError
from ..keystore import KeyStore, redact
from ..models import Forecast, Location
from . import REGISTRY, info as provider_info
from .base import KeyMissing, Provider

log = logging.getLogger(__name__)

DEFAULT_CHAIN = ["open-meteo", "met.no"]
# recovery id -> seconds before the primary is tried again after it failed (None: stay)
RECOVERY = {"next": 0, "15": 15 * 60, "30": 30 * 60, "60": 60 * 60, "stay": None}
RECOVERY_LABELS = {
    "next": "Return to the primary at the next update",
    "15": "Try the primary again after 15 minutes",
    "30": "Try the primary again after 30 minutes",
    "60": "Try the primary again after 1 hour",
    "stay": "Stay on the backup until it fails",
}
DEFAULT_RECOVERY = "30"
BACKUP_DOWN_S = 30 * 60        # a failing backup is tried last for this long


@dataclass
class ProviderStatus:
    id: str
    last_ok: float = 0.0           # unix time of the last forecast it supplied
    last_error: str = ""
    last_error_at: float = 0.0
    test_ok: Optional[bool] = None
    test_message: str = ""
    test_at: float = 0.0
    usage: dict = field(default_factory=dict)
    plan: str = ""

    def state(self, has_key: bool, needs_key: bool) -> str:
        """"no key" | "working" | "failing" | "not used yet"."""
        if needs_key and not has_key:
            return "no key"
        last_fail = max(self.last_error_at, self.test_at if self.test_ok is False else 0.0)
        last_good = max(self.last_ok, self.test_at if self.test_ok else 0.0)
        if last_fail > last_good:
            return "failing"
        if last_good:
            return "working"
        return "not used yet"


class AllProvidersFailed(WeatherError):
    pass


def valid_chain(chain) -> list[str]:
    out: list[str] = []
    for pid in chain or []:
        if isinstance(pid, str) and pid in REGISTRY and pid not in out:
            out.append(pid)
    return out or list(DEFAULT_CHAIN)


class ProviderManager:
    def __init__(self, chain: Optional[list[str]] = None, recovery: str = DEFAULT_RECOVERY,
                 keystore: Optional[KeyStore] = None, overrides: Optional[dict[str, Provider]] = None,
                 status_file: Optional[Path] = None, timeout: float = 15.0, ssl_context=None,
                 clock: Callable[[], float] = time.time,
                 factories: Optional[dict[str, Callable[[], Provider]]] = None,
                 options: Optional[dict[str, dict]] = None):
        self._lock = threading.RLock()
        self.keystore = keystore if keystore is not None else KeyStore()
        self.timeout = timeout
        self.ssl_context = ssl_context
        self.clock = clock
        self._overrides = dict(overrides or {})
        self._factories = dict(factories or {})      # tests: build providers against a fake server
        self._instances: dict[str, Provider] = dict(self._overrides)
        self.options: dict[str, dict] = {}            # provider id -> {option: value} (not secret)
        for pid, opts in (options or {}).items():
            for name, value in (opts or {}).items():
                try:
                    self.set_option(pid, name, value, reset=False)
                except ValueError:
                    pass
        self.chain = valid_chain(chain)
        self.recovery = recovery if recovery in RECOVERY else DEFAULT_RECOVERY
        self._failed_at: dict[str, float] = {}      # provider id -> clock time of the last failure
        self._recent: dict[tuple, tuple[float, Forecast]] = {}   # (id, location key) -> (time, forecast)
        self._asked: dict[tuple, float] = {}        # (id, location key) -> time of the last request
        self.active: Optional[str] = None           # provider that supplied the last forecast
        self.active_since: float = 0.0
        self.status_file = Path(status_file) if status_file else None
        self._status: dict[str, ProviderStatus] = {}
        self._load_status()

    # ------------------------------------------------------------- configuration
    def set_chain(self, chain: list[str]) -> None:
        with self._lock:
            self.chain = valid_chain(chain)

    def set_recovery(self, mode: str) -> None:
        if mode in RECOVERY:
            self.recovery = mode

    @property
    def primary(self) -> str:
        return self.chain[0]

    def provider(self, pid: str) -> Provider:
        with self._lock:
            p = self._instances.get(pid)
            if p is None:
                if pid in self._factories:
                    p = self._factories[pid]()
                else:
                    p = REGISTRY[pid](timeout=self.timeout, ssl_context=self.ssl_context)
                self._instances[pid] = p
            if p.info.needs_key:
                p.api_key = self.keystore.get(pid)
            p.options = dict(self.options.get(pid, {}))
            return p

    def set_option(self, pid: str, name: str, value: str, reset: bool = True) -> None:
        """Set a provider option (e.g. a weather station ID); empty clears it.
        Raises ValueError if the provider has no such option or the value is invalid."""
        import re
        inf = provider_info(pid)
        spec = next((o for o in (inf.options if inf else ()) if o[0] == name), None)
        if spec is None:
            raise ValueError(f"{pid} has no option {name!r}")
        value = (value or "").strip()
        if value and not re.fullmatch(spec[3], value):
            raise ValueError(f"That doesn't look like a valid {spec[1].lower()}.")
        with self._lock:
            opts = self.options.setdefault(pid, {})
            if value:
                opts[name] = value
            else:
                opts.pop(name, None)
            if not opts:
                self.options.pop(pid, None)
        if reset:
            self._reset_provider(pid, keep_key=True)

    # --------------------------------------------------------------------- keys
    def has_key(self, pid: str) -> bool:
        return self.keystore.has(pid)

    def set_key(self, pid: str, key: str) -> None:
        self.keystore.set(pid, key)
        self._reset_provider(pid)

    def remove_key(self, pid: str) -> None:
        self.keystore.delete(pid)
        self._reset_provider(pid)

    def _reset_provider(self, pid: str, keep_key: bool = False) -> None:
        """A new key or option means a fresh start: new instance, no cached forecasts or failures."""
        with self._lock:
            if pid not in self._overrides:
                self._instances.pop(pid, None)
            elif self._instances.get(pid) is not None and not keep_key:
                self._instances[pid].api_key = None
            self._failed_at.pop(pid, None)
            for k in [k for k in self._recent if k[0] == pid]:
                del self._recent[k]
            for k in [k for k in self._asked if k[0] == pid]:
                del self._asked[k]

    # ------------------------------------------------------------------- status
    def status(self, pid: str) -> ProviderStatus:
        with self._lock:
            return copy.deepcopy(self._status.setdefault(pid, ProviderStatus(pid)))

    def state(self, pid: str) -> str:
        inf = provider_info(pid)
        if inf is None or inf.status != "integrated":
            return "planned"
        return self.status(pid).state(self.has_key(pid) if inf.needs_key else True, inf.needs_key)

    def _record(self, pid: str, **changes) -> None:
        with self._lock:
            st = self._status.setdefault(pid, ProviderStatus(pid))
            for k, v in changes.items():
                setattr(st, k, redact(v) if isinstance(v, str) else v)
            self._save_status()

    def _load_status(self) -> None:
        if not self.status_file:
            return
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for pid, d in (data.get("providers") or {}).items() if isinstance(data, dict) else []:
            if not isinstance(d, dict):
                continue
            st = ProviderStatus(str(pid))
            for k in ("last_ok", "last_error_at", "test_at"):
                if isinstance(d.get(k), (int, float)):
                    setattr(st, k, float(d[k]))
            for k in ("last_error", "test_message", "plan"):
                if isinstance(d.get(k), str):
                    setattr(st, k, redact(d[k]))
            if isinstance(d.get("test_ok"), bool):
                st.test_ok = d["test_ok"]
            if isinstance(d.get("usage"), dict):
                st.usage = {str(k): redact(str(v)) for k, v in d["usage"].items()}
            self._status[st.id] = st
        if isinstance(data, dict) and data.get("active") in REGISTRY:
            self.active = data["active"]
            self.active_since = float(data.get("active_since") or 0.0)

    def _save_status(self) -> None:
        if not self.status_file:
            return
        try:
            from ..storage import atomic_write_json
            atomic_write_json(self.status_file, {
                "providers": {pid: asdict(st) for pid, st in self._status.items()},
                "active": self.active, "active_since": self.active_since})
        except Exception as e:                  # best effort only
            log.debug("could not save provider status: %s", e)

    # --------------------------------------------------------------- forecasts
    @property
    def source_name(self) -> str:
        return REGISTRY[self.primary].info.name

    def order(self) -> list[str]:
        """The providers to ask, in order, for the next update."""
        now = self.clock()
        with self._lock:
            chain = list(self.chain)
            primary = chain[0]
            mode = RECOVERY[self.recovery]
            if mode is None:
                # "stay": keep using the backup that is working until it fails
                if self.active in chain and self.active != primary and \
                        self._failed_at.get(primary, 0) > 0 and \
                        self._failed_at.get(self.active, 0) < self.active_since:
                    chain.remove(self.active)
                    chain.insert(0, self.active)
                    return self._down_last(chain, now, skip_first=True)
                return self._down_last(chain, now)
            return self._down_last(chain, now, primary_wait=mode)

    def _down_last(self, chain: list[str], now: float, primary_wait: float = BACKUP_DOWN_S,
                   skip_first: bool = False) -> list[str]:
        def down(i, pid):
            if skip_first and i == 0:
                return False
            wait = primary_wait if pid == self.chain[0] else BACKUP_DOWN_S
            return now - self._failed_at.get(pid, -1e18) < wait
        return sorted(chain, key=lambda pid: down(chain.index(pid), pid))   # stable

    def fetch_forecast(self, location: Location, forecast_days: int = 7) -> Forecast:
        errors: list[tuple[str, WeatherError]] = []
        for pid in self.order():
            p = self.provider(pid)
            now = self.clock()
            key = (pid, location.key)
            guard = p.info.min_interval_s
            with self._lock:
                recent = self._recent.get(key)
                asked = self._asked.get(key, -1e18)
            if guard and now - asked < guard:
                if recent is not None:
                    log.info("%s: reusing the forecast from %d s ago (protects its free allowance)",
                             p.info.name, now - recent[0])
                    self._set_active(pid, now)
                    return copy.deepcopy(recent[1])
                errors.append((pid, ApiError(f"{p.info.name}: waiting {int((guard - (now - asked)) // 60) + 1} "
                                             f"min before asking again (protects its free allowance).")))
                continue
            try:
                with self._lock:
                    self._asked[key] = now
                fc = p.fetch_forecast(location, forecast_days)
            except KeyMissing as e:
                errors.append((pid, e))
                continue
            except WeatherError as e:
                msg = redact(str(e), [p.api_key])
                log.info("%s failed: %s", p.info.name, msg)
                with self._lock:
                    self._failed_at[pid] = self.clock()
                self._record(pid, last_error=msg, last_error_at=time.time(), usage=p.usage() or {})
                errors.append((pid, e))
                continue
            with self._lock:
                self._recent[key] = (now, copy.deepcopy(fc))
                self._failed_at.pop(pid, None)
            usage = p.usage()
            self._record(pid, last_ok=time.time(), usage=usage or {},
                         plan=usage.get("plan", "") if usage else "")
            if pid != self.chain[0]:
                log.warning("forecast from %s (backup) because: %s", p.info.name,
                            "; ".join(f"{REGISTRY[i].info.name}: {redact(str(e))}" for i, e in errors) or "-")
            self._set_active(pid, now)
            return fc
        raise self._combined(errors)

    def _set_active(self, pid: str, now: float) -> None:
        with self._lock:
            if self.active != pid:
                self.active, self.active_since = pid, now
                self._save_status()

    def _combined(self, errors: list[tuple[str, WeatherError]]) -> WeatherError:
        if not errors:
            return AllProvidersFailed("No weather provider is configured.")
        main_pid, main = next(((pid, e) for pid, e in errors if pid == self.chain[0]), errors[0])
        others = [REGISTRY[pid].info.name for pid, _e in errors if pid != main_pid]
        msg = str(main).rstrip(".") + "."
        if others:
            msg += f" The backup{'s' if len(others) > 1 else ''} ({', '.join(others)}) couldn't supply it either."
        msg = redact(msg)
        if isinstance(main, KeyMissing):
            return KeyMissing(msg)
        if isinstance(main, NetworkError):
            return NetworkError(msg, retryable=False)
        if isinstance(main, DataError):
            return DataError(msg)
        return ApiError(msg, status=getattr(main, "status", None))

    # -------------------------------------------------------------------- tests
    def test(self, pid: str, location: Location, key: Optional[str] = None) -> tuple[bool, str, dict]:
        """Settings → Test connection: one real request with `key` (or the saved key).
        Returns (ok, plain-English result, usage). Never includes the key."""
        cls = REGISTRY.get(pid)
        if cls is None:
            return False, "This provider isn't integrated yet.", {}
        if pid in self._factories:
            p = self._factories[pid]()
        elif pid in self._overrides:
            p = self._overrides[pid]
        else:
            p = cls(timeout=self.timeout, ssl_context=self.ssl_context)
        if cls.info.needs_key:
            p.api_key = (key or "").strip() or self.keystore.get(pid)
        p.options = dict(self.options.get(pid, {}))
        t0 = time.monotonic()
        try:
            fc, usage = p.test(location)
        except WeatherError as e:
            msg = redact(str(e), [p.api_key, key])
            self._record(pid, test_ok=False, test_message=msg, test_at=time.time())
            return False, msg, {}
        ms = round((time.monotonic() - t0) * 1000)
        hours = len(fc.hourly)
        parts = [f"answered in {ms} ms",
                 f"{len(fc.daily)} day{'s' if len(fc.daily) != 1 else ''}",
                 f"{hours} hours hourly" if hours else "no hourly data",
                 f"now {fc.current.temperature:.0f}°C at {location.name}"]
        msg = " · ".join(parts)
        self._record(pid, test_ok=True, test_message=msg, test_at=time.time(), usage=usage or {},
                     plan=(usage or {}).get("plan", ""))
        return True, msg, usage or {}

    def try_primary_now(self) -> None:
        """Forget the primary's recent failure so the next update asks it first."""
        with self._lock:
            self._failed_at.pop(self.chain[0], None)
            if self.active != self.chain[0]:
                self.active_since = 0.0

    # ---------------------------------------------------- location search & info
    def _geocoder(self):
        p = self.provider("open-meteo")
        return getattr(p, "client", p)

    def search_locations(self, query: str, count: int = 10):
        return self._geocoder().search_locations(query, count)

    @property
    def geocode_url(self) -> str:
        return self._geocoder().geocode_url

    @property
    def forecast_url(self) -> str:
        p = self.provider(self.primary)
        return getattr(getattr(p, "client", p), "forecast_url", p.base_url)

    @property
    def backup(self):
        return None            # the 1.12 single-backup interface (diagnostics uses the chain instead)
