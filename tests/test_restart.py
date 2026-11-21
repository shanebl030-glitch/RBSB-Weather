"""2.3.1: "⬆ RBSB-Weather x.y.z was installed: click to restart".

A running copy notices newer program files installed underneath it (apt replacing
the package) and offers to restart into them. Unit tests with a temporary copy of
the version file, and a real-process test: an old copy runs, its files are swapped
for a newer version exactly as an upgrade does, and the old copy restarts into it
(the new one takes over through the usual hand-over).

Created By Shane BlackbuRn
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from helpers import ROOT, TempEnvTestCase, qapp, wait_until

from rbsb_weather import __version__


def bump(path: Path, version: str) -> None:
    """Rewrite __version__ in a copy of __init__.py and move its time on (like a new install)."""
    text = re.sub(r'__version__ = ".*?"', f'__version__ = "{version}"', path.read_text())
    path.write_text(text)
    t = time.time() + 5
    os.utime(path, (t, t))


class TestInstalledCheck(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        from rbsb_weather.main_window import MainWindow
        self.w = MainWindow(enable_tray=False)
        self.w.show()
        self.init = self.tmp / "__init__.py"
        shutil.copy(ROOT / "rbsb_weather" / "__init__.py", self.init)
        self.w._install_file = self.init
        self.w._install_mtime = self.w._file_mtime(self.init)
        self.spawned = []
        self.w.spawn = lambda cmd: self.spawned.append(cmd)

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        super().tearDown()

    def test_newer_install_offers_a_restart(self):
        self.w._check_installed()
        self.assertFalse(self.w.restart_button.isVisibleTo(self.w), "nothing changed yet")
        bump(self.init, "9.0.1")
        self.w._check_installed()
        self.assertTrue(self.w.restart_button.isVisibleTo(self.w))
        self.assertEqual(self.w.restart_button.text(), "⬆ RBSB-Weather 9.0.1 was installed: click to restart")

    def test_same_or_older_or_missing_is_ignored(self):
        bump(self.init, __version__)                      # reinstalled the same version
        self.w._check_installed()
        bump(self.init, "1.0.0")                          # rolled back underneath us
        self.w._check_installed()
        self.init.unlink()                                # removed
        self.w._check_installed()
        self.assertFalse(self.w.restart_button.isVisibleTo(self.w))

    def test_unchanged_file_isnt_read_again(self):
        bump(self.init, "9.0.1")
        self.w._check_installed()
        reads = []
        real = self.w.installed_version
        self.w.installed_version = lambda p: reads.append(p) or real(p)
        for _ in range(5):
            self.w._check_installed()
        self.assertEqual(reads, [], "only the file's time is checked until it changes")

    def test_update_button_replaced_by_the_installed_version(self):
        from rbsb_weather.updates import UpdateInfo
        self.w._update_info = UpdateInfo("9.0.1", "v9.0.1", "RBSB-Weather 9.0.1", "", "")
        self.w._announce_update(self.w._update_info, popup=False)
        self.assertTrue(self.w.update_button.isVisibleTo(self.w))
        bump(self.init, "9.0.1")
        self.w._check_installed()
        self.assertFalse(self.w.update_button.isVisibleTo(self.w), "that update is now installed")
        self.assertTrue(self.w.restart_button.isVisibleTo(self.w))

    def test_click_restarts_with_the_same_python_and_module(self):
        bump(self.init, "9.0.1")
        self.w._check_installed()
        self.w.restart_button.click()
        self.assertEqual(self.spawned, [[sys.executable, "-m", "rbsb_weather"]])
        self.assertEqual(self.w.restart_button.text(), "Restarting…")
        self.assertFalse(self.w.restart_button.isEnabled())
        self.w.hide()                                      # in the tray: the new one starts hidden too
        self.assertEqual(self.w.restart_command(), [sys.executable, "-m", "rbsb_weather", "--minimized"])
        self.w._restart_not_done()                         # if the new one never took over
        self.assertTrue(self.w.restart_button.isEnabled())
        self.assertIn("was installed", self.w.restart_button.text())

    def test_failed_start_explains(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QMessageBox
        bump(self.init, "9.0.1")
        self.w._check_installed()

        def boom(cmd):
            raise OSError("no such file")
        self.w.spawn = boom
        seen = {}

        def close_box():
            box = next(x for x in QApplication.topLevelWidgets() if isinstance(x, QMessageBox) and x.isVisible())
            seen["text"] = box.text()
            box.close()
        QTimer.singleShot(300, close_box)
        self.w.restart_into_new_version()
        self.assertIn("couldn't restart by itself", seen.get("text", ""))


@unittest.skipUnless(sys.platform.startswith("linux"), "uses Linux's /proc")
class TestRealRestart(TempEnvTestCase):
    def test_old_copy_restarts_into_newly_installed_files(self):
        from rbsb_weather.instance import socket_owner_pids
        name = f"rbsb-restart-{uuid.uuid4().hex[:8]}"
        copy = Path(tempfile.mkdtemp(prefix="rbsb-installed-"))
        shutil.copytree(ROOT / "rbsb_weather", copy / "rbsb_weather", ignore=shutil.ignore_patterns("__pycache__"))
        init = copy / "rbsb_weather" / "__init__.py"
        bump(init, "2.3.1")
        # PYTHONDONTWRITEBYTECODE: like a real install (users can't write compiled files into
        # /usr/lib, and the package removes them on upgrade). Without it, Python may reuse its
        # compiled copy of the old __init__.py: the test swaps "2.3.1" for "9.0.1" (same size)
        # within the same second, and Python checks size and whole-second times (seen 3 in 8 runs)
        env = dict(os.environ, PYTHONPATH=str(copy), PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen",
                   RBSB_WEATHER_INSTANCE=name,
                   RBSB_WEATHER_INSTALL_CHECK_S="0.5", RBSB_WEATHER_RESTART_ON_INSTALL="1")
        old = subprocess.Popen([sys.executable, "-m", "rbsb_weather"], env=env, cwd=str(self.tmp),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        new_pids = []
        try:
            path = None
            end = time.monotonic() + 15
            while time.monotonic() < end and path is None:
                with open("/proc/net/unix") as f:
                    path = next((l.split()[7] for l in f if len(l.split()) >= 8 and l.split()[7].endswith("/" + name)), None)
                time.sleep(0.1)
            self.assertIsNotNone(path, "the old copy never started listening")
            bump(init, "9.0.1")                                     # "apt installs" a newer version
            try:
                rc = old.wait(30)
            except subprocess.TimeoutExpired:
                old.kill()
                rc = None
            out = old.stdout.read()
            log_text = (self.tmp / "cache" / "rbsb-weather.log").read_text(errors="replace") \
                if (self.tmp / "cache" / "rbsb-weather.log").exists() else ""
            self.assertEqual(rc, 0, "the old copy should hand over and exit cleanly\n" + out[-2500:]
                             + "\n--- log ---\n" + log_text[-2500:])
            self.assertIn("RBSB-Weather 9.0.1 has been installed", out)
            log = self.tmp / "cache" / "rbsb-weather.log"

            def new_running():
                pids = socket_owner_pids(path)
                new_pids[:] = pids
                return pids and old.pid not in pids
            self.assertTrue(wait_until(new_running, 20), "the new version didn't take over")
            # the new copy's own words: it found the old one, which handed over
            self.assertTrue(wait_until(lambda: "replacing it with 9.0.1" in log.read_text(errors="replace"), 10),
                            log.read_text(errors="replace")[-2000:])
        finally:
            for pid in new_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if old.poll() is None:
                old.kill()
            shutil.rmtree(copy, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
