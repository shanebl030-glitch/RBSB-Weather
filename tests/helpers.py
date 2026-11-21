"""Shared test fixtures. Every test gets its own temp config/cache dirs and fake server."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if not os.environ.get("XDG_RUNTIME_DIR"):
    _rt = Path(tempfile.gettempdir()) / f"rbsb_weather-test-runtime-{os.getuid()}"
    _rt.mkdir(mode=0o700, exist_ok=True)
    os.environ["XDG_RUNTIME_DIR"] = str(_rt)
# Never contact GitHub from tests: the update check (2.1) goes to a closed local port
# unless a test points it at its own fake GitHub.
os.environ["RBSB_WEATHER_UPDATE_URL"] = "http://127.0.0.1:9/releases/latest"
# Never touch the desktop's real keyring from tests: keys go to the temp config dir.
os.environ["RBSB_WEATHER_KEYRING"] = "0"
# Tests talk only to the local fake server; never route them through a proxy.
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

from fake_server import FakeServer, PLACES  # noqa: E402


_APP = None


def qapp():
    """Return the shared QApplication, kept alive for the whole test run
    (a discarded QApplication is garbage-collected and Qt then aborts)."""
    global _APP
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication(["rbsb_weather-tests"])
        app.setQuitOnLastWindowClosed(False)
    _APP = app
    return app


def wait_until(cond, timeout: float = 5.0, step_ms: int = 20) -> bool:
    from PyQt6.QtTest import QTest
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        QTest.qWait(step_ms)
    return bool(cond())


class TempEnvTestCase(unittest.TestCase):
    """Isolated directories + a running fake Open-Meteo server."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rbsb_weather-test-"))
        self._env = {k: os.environ.get(k) for k in
                     ("RBSB_WEATHER_CONFIG_DIR", "RBSB_WEATHER_CACHE_DIR", "XDG_CONFIG_HOME")}
        os.environ["RBSB_WEATHER_CONFIG_DIR"] = str(self.tmp / "config")
        os.environ["RBSB_WEATHER_CACHE_DIR"] = str(self.tmp / "cache")
        os.environ["XDG_CONFIG_HOME"] = str(self.tmp / "xdg")
        from rbsb_weather import net
        net.reset_health()                 # connection-health memory is process-wide
        self.server = FakeServer().start()
        # never reach the real cloud map service from tests
        from rbsb_weather import clouds
        self._cloud_url = clouds.CLOUD_URL
        clouds.CLOUD_URL = self.server.cloud_url

    def tearDown(self):
        from rbsb_weather import clouds
        clouds.CLOUD_URL = self._cloud_url
        self.server.stop()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, timeout: float = 3.0):
        from rbsb_weather.api import OpenMeteoClient
        return OpenMeteoClient(self.server.forecast_url, self.server.geocode_url, timeout=timeout)

    @staticmethod
    def place(i: int = 0):
        from rbsb_weather.models import Location
        return Location.from_dict(PLACES[i])
