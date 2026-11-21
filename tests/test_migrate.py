"""2.0.0: WeatherDesk -> RBSB-Weather rename. Data carry-over and hand-over tests.

* unit tests of rbsb_weather/migrate.py with temporary folders and a fake keyring
* the real app started with a WeatherDesk profile in a temporary HOME (no test
  folder overrides, so the startup path that users get is the one exercised)
* a real WeatherDesk 1.18.0 process (taken from git history) handing over to
  RBSB-Weather through its old single-instance socket

Created By Shane BlackbuRn
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from helpers import ROOT, TempEnvTestCase

from rbsb_weather import migrate
from rbsb_weather.instance import is_rbsb_weather, socket_owner_pids
from rbsb_weather.storage import AUTOSTART_ENTRY

LEGACY_VERSION_REF = "v1.18.0"        # last WeatherDesk release, for the real hand-over test


class FakeKeyring:
    def __init__(self, data=None, fail_on=()):
        self.data = dict(data or {})
        self.fail_on = set(fail_on)

    def get_password(self, service, user):
        if user in self.fail_on:
            raise RuntimeError("locked")
        return self.data.get((service, user))

    def set_password(self, service, user, value):
        self.data[(service, user)] = value


def _legacy_profile(home: Path) -> dict:
    """A WeatherDesk 1.x profile like a real user's (°F, 12-hour, keys in keys.json)."""
    cfg, cache = home / ".config" / "weatherdesk", home / ".cache" / "weatherdesk"
    cfg.mkdir(parents=True, mode=0o700)
    os.chmod(cfg, 0o700)
    cache.mkdir(parents=True)
    settings = {"version": 1, "locations": [], "temp_unit": "F", "time_format": "12",
                "refresh_minutes": 60, "future_setting_from_1_16": {"x": 1}}
    (cfg / "settings.json").write_text(json.dumps(settings))
    keys = cfg / "keys.json"
    keys.write_text(json.dumps({"note": "WeatherDesk API keys. Keep private.",
                                "keys": {"tomorrow": "fake-tomorrow-key-123"}}))
    os.chmod(keys, 0o600)
    (cache / "m36.8500_174.7600.json").write_text('{"fake": "forecast"}')
    (cache / "providers.json").write_text("{}")
    (cache / "weatherdesk.log").write_text("old log\n")
    auto = home / ".config" / "autostart"
    auto.mkdir(parents=True)
    (auto / "weatherdesk.desktop").write_text("[Desktop Entry]\nExec=weatherdesk --minimized\n")
    return settings


class MigrateCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="rbsb-migrate-"))
        self.settings = _legacy_profile(self.home)
        self.kw = dict(
            old_config=self.home / ".config/weatherdesk", new_config=self.home / ".config/rbsb-weather",
            old_cache=self.home / ".cache/weatherdesk", new_cache=self.home / ".cache/rbsb-weather",
            old_autostart=self.home / ".config/autostart/weatherdesk.desktop",
            new_autostart=self.home / ".config/autostart/rbsb-weather.desktop",
            autostart_entry=AUTOSTART_ENTRY)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)


class TestMigrate(MigrateCase):
    def test_everything_carried_over_and_originals_kept(self):
        notes = migrate.migrate(**self.kw)
        self.assertEqual(notes, ["settings and saved locations", "saved forecasts", "Start at login"])
        new_cfg, new_cache = self.kw["new_config"], self.kw["new_cache"]
        self.assertEqual(json.loads((new_cfg / "settings.json").read_text()), self.settings)
        self.assertEqual(json.loads((new_cfg / "keys.json").read_text())["keys"],
                         {"tomorrow": "fake-tomorrow-key-123"})
        self.assertEqual(stat.S_IMODE((new_cfg / "keys.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(new_cfg.stat().st_mode), 0o700)
        self.assertTrue((new_cache / "m36.8500_174.7600.json").exists())
        self.assertFalse((new_cache / "weatherdesk.log").exists(), "old logs are not copied")
        # originals untouched (only the login entry is renamed, never deleted)
        self.assertTrue((self.kw["old_config"] / "settings.json").exists())
        self.assertTrue((self.kw["old_config"] / "keys.json").exists())
        self.assertTrue((self.kw["old_cache"] / "weatherdesk.log").exists())
        self.assertFalse(self.kw["old_autostart"].exists())
        self.assertTrue(self.kw["old_autostart"].with_name("weatherdesk.desktop.migrated").exists())
        self.assertIn("Exec=rbsb-weather --minimized", self.kw["new_autostart"].read_text())
        self.assertTrue((new_cfg / migrate.MARKER).exists())
        self.assertEqual(list(new_cfg.parent.glob(".rbsb-weather.migrating-*")), [])

    def test_runs_only_once(self):
        migrate.migrate(**self.kw)
        (self.kw["new_config"] / "settings.json").write_text('{"temp_unit": "C"}')   # user changes it
        (self.kw["old_config"] / "settings.json").write_text('{"temp_unit": "F", "changed": 1}')
        self.assertEqual(migrate.migrate(**self.kw), [])
        self.assertEqual(json.loads((self.kw["new_config"] / "settings.json").read_text()), {"temp_unit": "C"})

    def test_never_overwrites_existing_rbsb_data(self):
        self.kw["new_config"].mkdir(parents=True)
        (self.kw["new_config"] / "settings.json").write_text('{"temp_unit": "C"}')
        notes = migrate.migrate(**self.kw)
        self.assertNotIn("settings and saved locations", notes)
        self.assertEqual(json.loads((self.kw["new_config"] / "settings.json").read_text()), {"temp_unit": "C"})
        self.assertFalse((self.kw["new_config"] / "keys.json").exists())

    def test_cache_holding_only_the_new_log_is_still_filled(self):
        """The app opens its log in the cache folder before migrating."""
        self.kw["new_cache"].mkdir(parents=True)
        (self.kw["new_cache"] / "rbsb-weather.log").write_text("new log\n")
        notes = migrate.migrate(**self.kw)
        self.assertIn("saved forecasts", notes)
        self.assertEqual((self.kw["new_cache"] / "rbsb-weather.log").read_text(), "new log\n")
        self.assertTrue((self.kw["new_cache"] / "providers.json").exists())

    def test_nothing_to_do_for_a_new_user(self):
        shutil.rmtree(self.home / ".config")
        shutil.rmtree(self.home / ".cache")
        self.assertEqual(migrate.migrate(**self.kw), [])
        self.assertFalse(self.kw["new_config"].exists())

    def test_existing_new_autostart_kept_and_old_one_disabled(self):
        self.kw["new_autostart"].write_text("[Desktop Entry]\nExec=rbsb-weather --minimized\nX-Mine=1\n")
        migrate.migrate(**self.kw)
        self.assertIn("X-Mine=1", self.kw["new_autostart"].read_text())
        self.assertFalse(self.kw["old_autostart"].exists())

    def test_keyring_keys_copied_and_old_entries_kept(self):
        kr = FakeKeyring({("WeatherDesk", "wunderground"): "wu-key-1", ("WeatherDesk", "tomorrow"): "t-key",
                          ("RBSB-Weather", "tomorrow"): "already-new"})
        notes = migrate.migrate(**self.kw, keyring_mod=kr,
                                provider_ids=["open-meteo", "wunderground", "tomorrow"])
        self.assertIn("1 API key in the keyring", notes)
        self.assertEqual(kr.data[("RBSB-Weather", "wunderground")], "wu-key-1")
        self.assertEqual(kr.data[("RBSB-Weather", "tomorrow")], "already-new", "never overwritten")
        self.assertEqual(kr.data[("WeatherDesk", "wunderground")], "wu-key-1", "old entry kept")

    def test_locked_keyring_never_stops_the_migration(self):
        kr = FakeKeyring({("WeatherDesk", "openweather"): "k1"}, fail_on={"wunderground"})
        notes = migrate.migrate(**self.kw, keyring_mod=kr, provider_ids=["wunderground", "openweather"])
        self.assertIn("settings and saved locations", notes)
        self.assertEqual(kr.data[("RBSB-Weather", "openweather")], "k1")

    def test_failed_copy_retries_next_start(self):
        orig = migrate.copy_folder
        calls = []

        def boom(old, new):
            calls.append(old)
            raise OSError("disk full")
        migrate.copy_folder = boom
        try:
            self.assertEqual(migrate.migrate(**{**self.kw, "old_autostart": self.home / "none"}), [])
        finally:
            migrate.copy_folder = orig
        self.assertFalse((self.kw["new_config"] / migrate.MARKER).exists())
        self.assertIn("settings and saved locations", migrate.migrate(**self.kw))

    def test_interrupted_copy_leaves_no_half_folder(self):
        orig = shutil.copy2

        def flaky(src, dst, *a, **k):
            if src.endswith("keys.json"):
                raise OSError("I/O error")
            return orig(src, dst, *a, **k)
        shutil.copy2 = flaky
        try:
            with self.assertRaises(OSError):
                migrate.copy_folder(self.kw["old_config"], self.kw["new_config"])
        finally:
            shutil.copy2 = orig
        self.assertFalse(self.kw["new_config"].exists())
        self.assertEqual(list(self.kw["new_config"].parent.glob(".rbsb-weather.migrating-*")), [])
        self.assertTrue(migrate.copy_folder(self.kw["old_config"], self.kw["new_config"]))


class TestRunGuards(unittest.TestCase):
    def test_skipped_with_test_folder_overrides_or_switch(self):
        env = {k: os.environ.get(k) for k in ("RBSB_WEATHER_CONFIG_DIR", "RBSB_WEATHER_MIGRATE")}
        try:
            os.environ["RBSB_WEATHER_CONFIG_DIR"] = "/nonexistent"
            self.assertEqual(migrate.run(), [])
            os.environ.pop("RBSB_WEATHER_CONFIG_DIR")
            os.environ["RBSB_WEATHER_MIGRATE"] = "0"
            self.assertEqual(migrate.run(), [])
        finally:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_legacy_socket_name(self):
        env = {k: os.environ.get(k) for k in ("RBSB_WEATHER_INSTANCE", "RBSB_WEATHER_LEGACY_INSTANCE")}
        try:
            os.environ.pop("RBSB_WEATHER_INSTANCE", None)
            os.environ.pop("RBSB_WEATHER_LEGACY_INSTANCE", None)
            self.assertEqual(migrate.legacy_server_name(), f"weatherdesk-{os.getuid()}")
            os.environ["RBSB_WEATHER_INSTANCE"] = "test-x"      # tests never reach a real WeatherDesk
            self.assertIsNone(migrate.legacy_server_name())
            os.environ["RBSB_WEATHER_LEGACY_INSTANCE"] = "fake-legacy"
            self.assertEqual(migrate.legacy_server_name(), "fake-legacy")
        finally:
            for k, v in env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_process_check_recognises_both_names(self):
        procs = []
        try:
            for args in (["rbsb_weather"], ["weatherdesk"], ["/usr/bin/rbsb-weather"], ["something_else"]):
                procs.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *args]))
            time.sleep(0.3)
            self.assertEqual([is_rbsb_weather(p.pid) for p in procs], [True, True, True, False])
        finally:
            for p in procs:
                p.kill()
                p.wait()


def _app_env(home: Path, instance: str, **extra) -> dict:
    env = dict(os.environ)
    for k in ("RBSB_WEATHER_CONFIG_DIR", "RBSB_WEATHER_CACHE_DIR", "RBSB_WEATHER_LEGACY_INSTANCE"):
        env.pop(k, None)
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               QT_QPA_PLATFORM="offscreen", RBSB_WEATHER_INSTANCE=instance, RBSB_WEATHER_KEYRING="0",
               WEATHERDESK_INSTANCE=instance + "-legacy", WEATHERDESK_KEYRING="0")
    env.update(extra)
    return env


def _wait_socket(name: str, timeout=15.0) -> str:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with open("/proc/net/unix") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 8 and parts[7].endswith("/" + name):
                    return parts[7]
        time.sleep(0.05)
    raise AssertionError(f"nothing listened on {name}")


class TestRealApp(unittest.TestCase):
    """Real app processes in a temporary HOME."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="rbsb-home-"))
        self.name = f"rbsb-mig-{uuid.uuid4().hex[:8]}"
        self.procs: list[subprocess.Popen] = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(5)
        shutil.rmtree(self.home, ignore_errors=True)

    def launch(self, module="rbsb_weather", pythonpath=ROOT, **extra):
        p = subprocess.Popen([sys.executable, "-X", "faulthandler", "-m", module],
                             env=_app_env(self.home, self.name, PYTHONPATH=str(pythonpath), **extra),
                             cwd=str(self.home), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        return p

    def test_first_start_carries_over_a_weatherdesk_profile(self):
        settings = _legacy_profile(self.home)
        app = self.launch()
        _wait_socket(self.name)
        time.sleep(0.5)
        app.send_signal(signal.SIGTERM)
        out, _ = app.communicate(timeout=20)
        self.assertEqual(app.returncode, 0, out[-3000:])
        self.assertIn("carried over from WeatherDesk", out)
        new = json.loads((self.home / ".config/rbsb-weather/settings.json").read_text())
        self.assertEqual(new["temp_unit"], "F")
        self.assertEqual(new["time_format"], "12")
        self.assertEqual(new["future_setting_from_1_16"], settings["future_setting_from_1_16"])
        self.assertEqual(stat.S_IMODE((self.home / ".config/rbsb-weather/keys.json").stat().st_mode), 0o600)
        self.assertTrue((self.home / ".config/autostart/rbsb-weather.desktop").exists())
        self.assertTrue((self.home / ".cache/rbsb-weather/rbsb-weather.log").exists())
        self.assertTrue((self.home / ".config/weatherdesk/settings.json").exists(), "old data kept")
        # second start: nothing more to carry over
        app2 = self.launch()
        _wait_socket(self.name)
        time.sleep(0.3)
        app2.send_signal(signal.SIGTERM)
        out2, _ = app2.communicate(timeout=20)
        self.assertNotIn("carried over", out2)

    def _legacy_tree(self) -> Path:
        dest = self.home / "legacy-src"
        dest.mkdir()
        try:
            arch = subprocess.run(["git", "-C", str(ROOT), "archive", LEGACY_VERSION_REF, "weatherdesk"],
                                  capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            self.skipTest("git not available")
        if arch.returncode != 0:
            self.skipTest(f"WeatherDesk {LEGACY_VERSION_REF} not in git history (source archive?)")
        subprocess.run(["tar", "-x", "-C", str(dest)], input=arch.stdout, check=True)
        return dest

    def test_running_weatherdesk_hands_over_and_its_settings_come_along(self):
        legacy_src = self._legacy_tree()
        _legacy_profile(self.home)
        legacy_name = self.name + "-legacy"
        old = self.launch(module="weatherdesk", pythonpath=legacy_src)
        lpath = _wait_socket(legacy_name)
        self.assertEqual(socket_owner_pids(lpath), [old.pid])
        new = self.launch(RBSB_WEATHER_LEGACY_INSTANCE=legacy_name)
        rc = old.wait(20)
        out_old = old.stdout.read()
        old.stdout.close()
        self.assertEqual(rc, 0, "WeatherDesk should save and quit cleanly:\n" + out_old[-3000:])
        path = _wait_socket(self.name)
        time.sleep(0.5)
        self.assertEqual(socket_owner_pids(path), [new.pid])
        self.assertIsNone(new.poll())
        new.send_signal(signal.SIGTERM)
        out, _ = new.communicate(timeout=20)
        self.assertEqual(new.returncode, 0, out[-3000:])
        self.assertIn("Replacing the WeatherDesk that was running", out)
        self.assertIn("carried over from WeatherDesk", out)
        new_settings = json.loads((self.home / ".config/rbsb-weather/settings.json").read_text())
        self.assertEqual(new_settings["temp_unit"], "F")


if __name__ == "__main__":
    unittest.main()
