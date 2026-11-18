"""Background network work.

Network calls run on short-lived daemon threads so the window never freezes,
and so quitting the app is instant even if a request is stuck waiting on a
dead connection (the socket timeout still bounds every request).

Results come back to the GUI thread through Qt signals on a single long-lived
Bridge object (cross-thread emits are queued automatically by Qt). Every
request carries a token; the GUI ignores results whose token is stale, so a
slow old response can never overwrite a newer one.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from .api import OpenMeteoClient, WeatherError
from .models import Location

log = logging.getLogger(__name__)


class Bridge(QObject):
    forecast_ok = pyqtSignal(int, object)          # token, Forecast
    forecast_failed = pyqtSignal(int, str, str)    # token, location key, message
    search_ok = pyqtSignal(int, object)            # token, list[Location]
    search_failed = pyqtSignal(int, str)           # token, message
    diag_line = pyqtSignal(str)                    # connection test progress
    diag_done = pyqtSignal(str)                    # full connection test report
    moon_ok = pyqtSignal(int, object)              # token, MoonReport
    moon_saved = pyqtSignal(str, str)              # path, error ("" = ok)
    earth_ok = pyqtSignal(int, object, object, str, str)  # token, QImage|None, time, error, cloud note
    provider_test = pyqtSignal(int, str, bool, str)       # token, provider id, ok, message (no keys)


# Bridges are never destroyed while a worker thread might still emit on them.
# Emitting on a QObject that the GUI thread is destroying at that same moment is a
# use-after-free (a segfault, seen about 1 run in 6 in the window open/close stress
# test). So a window's Bridge has no Qt parent; when the window closes, its Bridge is
# "retired": signals are blocked (nothing reaches the closing window) and it's only
# deleted once its worker has no threads left.
_RETIRED: list[tuple["Bridge", "Worker"]] = []


def retire(bridge: "Bridge", worker: "Worker") -> None:
    if worker.closed:
        return
    bridge.blockSignals(True)
    worker.closed = True
    _RETIRED.append((bridge, worker))
    reap()


def reap() -> int:
    """Delete retired bridges whose threads have all finished. Returns how many remain."""
    for item in list(_RETIRED):
        b, w = item
        if w.active == 0:
            _RETIRED.remove(item)
            try:
                b.deleteLater()
            except RuntimeError:            # pragma: no cover - already gone
                pass
    return len(_RETIRED)


class Worker:
    def __init__(self, client: OpenMeteoClient, bridge: Bridge):
        reap()
        self.client = client
        self.bridge = bridge
        self.closed = False
        self._lock = threading.Lock()
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    def _spawn(self, name: str, fn: Callable[[], None]) -> None:
        def run():
            try:
                fn()
            except RuntimeError as e:
                # Bridge deleted during shutdown - nothing left to notify.
                log.debug("worker %s ended after shutdown: %s", name, e)
            except Exception:  # pragma: no cover - defensive
                log.exception("worker %s crashed", name)
            finally:
                with self._lock:
                    self._active -= 1

        with self._lock:
            self._active += 1
        t = threading.Thread(target=run, name=f"weatherdesk-{name}", daemon=True)
        try:
            t.start()
        except Exception:
            with self._lock:
                self._active -= 1
            raise

    def fetch_forecast(self, token: int, loc: Location) -> None:
        def job():
            try:
                fc = self.client.fetch_forecast(loc)
            except WeatherError as e:
                self.bridge.forecast_failed.emit(token, loc.key, str(e))
                return
            except Exception as e:
                from .keystore import redact
                log.exception("unexpected forecast failure")
                self.bridge.forecast_failed.emit(token, loc.key, redact(f"Unexpected error: {e}"))
                return
            self.bridge.forecast_ok.emit(token, fc)
        self._spawn("forecast", job)

    def test_provider(self, token: int, manager, provider_id: str, key, loc: Location) -> None:
        """Settings → Weather Providers → Test connection, off the GUI thread."""
        def job():
            from .keystore import redact
            try:
                ok, msg, _usage = manager.test(provider_id, loc, key)
            except Exception as e:                     # never let a key reach the UI or log
                log.error("provider test crashed: %s", redact(f"{type(e).__name__}: {e}", [key]))
                ok, msg = False, redact(f"Unexpected error: {e}", [key])
            self.bridge.provider_test.emit(token, provider_id, ok, msg)
        self._spawn("provider-test", job)

    def search(self, token: int, query: str) -> None:
        def job():
            try:
                res = self.client.search_locations(query)
            except WeatherError as e:
                self.bridge.search_failed.emit(token, str(e))
                return
            except Exception as e:
                log.exception("unexpected search failure")
                self.bridge.search_failed.emit(token, f"Unexpected error: {e}")
                return
            self.bridge.search_ok.emit(token, res)
        self._spawn("search", job)

    def diagnose(self) -> None:
        def job():
            from .diagnostics import run_diagnostics
            try:
                report = run_diagnostics(self.client, progress=self.bridge.diag_line.emit)
            except Exception as e:
                log.exception("connection test crashed")
                report = f"Connection test failed unexpectedly: {e}"
            self.bridge.diag_done.emit(report)
        self._spawn("diagnose", job)

    def moon_report(self, token: int, loc, tz_name: str, utc_offset=None) -> None:
        def job():
            from .moon_panel import build_report
            try:
                rep = build_report(loc, tz_name, utc_offset)
            except Exception as e:
                log.exception("moon calculation failed")
                self.bridge.moon_ok.emit(token, f"Moon calculation failed: {e}")
                return
            self.bridge.moon_ok.emit(token, rep)
        self._spawn("moon", job)

    def save_moon(self, path: str, phase_angle: float, bright_limb: float, southern: bool,
                  size: int = 2048) -> None:
        def job():
            from .moon_render import render_moon
            try:
                img = render_moon(size, phase_angle, bright_limb, southern)
                ok = img.save(path, "PNG")
                self.bridge.moon_saved.emit(path, "" if ok else "the file could not be written")
            except Exception as e:
                self.bridge.moon_saved.emit(path, str(e))
        self._spawn("moon-save", job)

    def earth_compose(self, token: int, cloud_store=None, cloud_url: str = "") -> None:
        """Draw the day/night Earth. With a cloud store, first refresh the live cloud
        map if it's due (a failure keeps the last one), then lay it over the Earth."""
        def job():
            import datetime as dt
            from . import clouds, earth
            now = dt.datetime.now(dt.timezone.utc)
            cimg, cnote = None, ""
            if cloud_store is not None:
                cerr = ""
                try:
                    if cloud_store.due():
                        clouds.update(cloud_store, cloud_url or clouds.CLOUD_URL,
                                      ssl_context=self.client.ssl_context)
                except clouds.CloudError as e:
                    cerr = str(e)
                    log.warning("live clouds: %s", e)
                except Exception as e:                    # never lose the Earth over clouds
                    cerr = str(e)
                    log.exception("live clouds failed")
                cimg = cloud_store.load()
                cnote = clouds.note(cloud_store, cimg, cerr)
            try:
                try:
                    img, err = earth.compose_day_night(now, clouds=cimg), ""
                except earth.EarthTextureError:
                    raise
                except Exception:
                    if cimg is None:
                        raise
                    log.exception("drawing clouds failed; drawing the Earth without them")
                    img, err = earth.compose_day_night(now), ""
                    cnote = "Live clouds could not be drawn, so the Earth is shown without them."
            except earth.EarthTextureError as e:          # expected, clear message, no traceback
                log.warning("%s", e)
                img, err = None, f"The Earth map could not be drawn: {e}"
            except Exception as e:
                log.exception("earth map failed")
                img, err = None, f"The Earth map could not be drawn: {e}"
            # (a RuntimeError here means the window closed meanwhile; _spawn ignores it)
            self.bridge.earth_ok.emit(token, img, now if img is not None else None, err, cnote)
        self._spawn("earth", job)
