"""Single-instance hand-over tests using real WeatherDesk processes.

Each scenario runs real app processes (headless) with their own config
directories and a private instance name (WEATHERDESK_INSTANCE), so running
these tests never touches a WeatherDesk you have open. No locations are
saved, so no network requests are made.
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

from helpers import ROOT, TempEnvTestCase

from weatherdesk import __version__
from weatherdesk.instance import compare_versions, decide, parse_version, socket_owner_pids


class TestVersionLogic(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(compare_versions("1.1.1", "1.1.0"), 1)
        self.assertEqual(compare_versions("1.1.0", "1.1.1"), -1)
        self.assertEqual(compare_versions("1.10.0", "1.9.9"), 1)      # numeric, not text
        self.assertEqual(compare_versions("1.1", "1.1.0"), 0)
        self.assertEqual(compare_versions("junk", "1.0.0"), 0)
        self.assertIsNone(parse_version(""))

    def test_decide(self):
        self.assertEqual(decide(b"show 1.2.0\n", "1.1.1"), "yield")
        self.assertEqual(decide(b"show 1.1.1\n", "1.1.1"), "ok")
        self.assertEqual(decide(b"show 1.0.0\n", "1.1.1"), "newer 1.1.1")
        self.assertEqual(decide(b"show", "1.1.1"), "ok")        # pre-1.1.1 style request
        self.assertEqual(decide(b"\xff\xfe", "1.1.1"), "ok")


def _make_copy(dest: Path, version: str, legacy: bool = False) -> Path:
    """Copy the package with a different version (and optionally the pre-1.1.1
    behaviour of never answering the version question)."""
    pkg = dest / "weatherdesk"
    shutil.copytree(ROOT / "weatherdesk", pkg, ignore=shutil.ignore_patterns("__pycache__"))
    init = pkg / "__init__.py"
    init.write_text(re.sub(r'__version__ = ".*?"', f'__version__ = "{version}"', init.read_text()))
    if legacy:
        app = pkg / "app.py"
        src = app.read_text()
        assert "conn.write((reply" in src
        app.write_text(src.replace("conn.write((reply", "(lambda *_: None)((reply"))
    return dest


class InstanceCase(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.name = f"weatherdesk-test-{uuid.uuid4().hex[:8]}"
        self.procs: list[subprocess.Popen] = []
        self.copies = Path(tempfile.mkdtemp(prefix="wd-copies-"))

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
                try:
                    p.wait(5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(5)
        shutil.rmtree(self.copies, ignore_errors=True)
        super().tearDown()

    def launch(self, pythonpath: Path = ROOT) -> subprocess.Popen:
        env = dict(os.environ)
        env.update(PYTHONPATH=str(pythonpath), QT_QPA_PLATFORM="offscreen",
                   WEATHERDESK_INSTANCE=self.name)
        p = subprocess.Popen([sys.executable, "-X", "faulthandler", "-m", "weatherdesk"], env=env, cwd=str(self.tmp),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.procs.append(p)
        return p

    def wait_listening(self, timeout=10.0) -> str:
        """Wait until some process owns the instance socket; return its path."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with open("/proc/net/unix") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 8 and parts[7].endswith("/" + self.name):
                        return parts[7]
            time.sleep(0.05)
        self.fail("instance never started listening")

    def owner(self, path) -> list[int]:
        return socket_owner_pids(path)


class TestHandOver(InstanceCase):
    def test_busy_current_copy_is_never_closed(self):
        """Regression: a same-version copy that is slow to answer must not be
        mistaken for a legacy copy and closed."""
        first = self.launch()
        path = self.wait_listening()
        os.kill(first.pid, signal.SIGSTOP)          # simulate a busy/unresponsive copy
        try:
            second = self.launch()
            time.sleep(2.5)                          # it's still retrying
            self.assertIsNone(second.poll())
        finally:
            os.kill(first.pid, signal.SIGCONT)       # becomes responsive again
        out, _ = second.communicate(timeout=20)
        self.assertEqual(second.returncode, 0, out)
        self.assertIn("already running", out)
        self.assertIsNone(first.poll(), "the busy copy must not have been closed")
        self.assertEqual(self.owner(path), [first.pid])

    def test_abandoned_requests_while_busy_are_harmless(self):
        """Regression (1.8.1): launches that gave up while this copy was busy leave closed
        sockets with requests in them. Answering those could crash the running copy (a
        socket deleted inside its own signal), and a stale "newer version" request could
        make it quit for a launch that had already moved on. Now they're ignored."""
        import socket as so
        first = self.launch()
        path = self.wait_listening()
        os.kill(first.pid, signal.SIGSTOP)
        try:
            for i in range(25):
                s = so.socket(so.AF_UNIX, so.SOCK_STREAM)
                s.connect(path.lstrip("@") if not path.startswith("@") else "\0" + path[1:])
                ver = "99.0.0" if i % 2 else __version__
                s.sendall(f"show {ver}\n".encode())
                s.close()                                  # gave up without waiting
        finally:
            os.kill(first.pid, signal.SIGCONT)
        time.sleep(2.0)
        self.assertIsNone(first.poll(), "the running copy must survive abandoned requests")
        second = self.launch()                             # a normal launch still works
        out, _ = second.communicate(timeout=20)
        self.assertEqual(second.returncode, 0, out)
        self.assertIn("already running", out)
        self.assertIsNone(first.poll())
        first.send_signal(signal.SIGTERM)
        out1, _ = first.communicate(timeout=15)
        self.assertEqual(first.returncode, 0, out1)
        self.assertNotIn("Fatal Python error", out1)
        self.assertIn("ignoring a launch request", out1)

    def test_same_version_brings_existing_to_front(self):
        first = self.launch()
        path = self.wait_listening()
        second = self.launch()
        out, _ = second.communicate(timeout=15)
        self.assertEqual(second.returncode, 0)
        self.assertIn("already running", out)
        self.assertIsNone(first.poll(), "the running copy must stay open")
        self.assertEqual(self.owner(path), [first.pid])

    def test_newer_version_replaces_older_running_copy(self):
        old = self.launch(_make_copy(self.copies / "old", "1.1.0.9"))   # older, has hand-over
        path = self.wait_listening()
        new = self.launch()
        rc = old.wait(15)
        self.assertEqual(rc, 0, "old copy should quit cleanly (exit 0). Output:\n" + old.stdout.read()[-3000:])
        time.sleep(0.5)
        path = self.wait_listening()
        self.assertEqual(self.owner(path), [new.pid])
        self.assertIsNone(new.poll())
        # settings saved by the old copy on its clean exit
        self.assertTrue((self.tmp / "config" / "settings.json").exists())

    def test_older_launch_leaves_newer_running(self):
        newer = self.launch(_make_copy(self.copies / "newer", "9.0.0"))
        path = self.wait_listening()
        older = self.launch()
        out, _ = older.communicate(timeout=15)
        self.assertEqual(older.returncode, 0)
        self.assertIn("newer WeatherDesk (9.0.0)", out)
        self.assertIsNone(newer.poll())
        self.assertEqual(self.owner(path), [newer.pid])

    def test_legacy_copy_that_cannot_answer_is_replaced(self):
        legacy = self.launch(_make_copy(self.copies / "legacy", "1.1.0", legacy=True))
        self.wait_listening()
        t0 = time.monotonic()
        new = self.launch()
        self.assertEqual(legacy.wait(15), 0, "legacy copy should save and exit on SIGTERM")
        path = self.wait_listening()
        time.sleep(0.5)
        self.assertEqual(self.owner(path), [new.pid])
        self.assertIsNone(new.poll())
        self.assertLess(time.monotonic() - t0, 10)

    def test_unrelated_processes_never_signalled(self):
        # A process that merely *looks* like WeatherDesk but doesn't own the
        # socket must be left alone.
        decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "weatherdesk"])
        try:
            legacy = self.launch(_make_copy(self.copies / "legacy", "1.0.0", legacy=True))
            self.wait_listening()
            self.launch()
            self.assertEqual(legacy.wait(15), 0)
            self.assertIsNone(decoy.poll(), "decoy process must not be touched")
        finally:
            decoy.kill()
            decoy.wait()

    def test_stale_socket_after_crash(self):
        crashed = self.launch()
        self.wait_listening()
        crashed.kill()                      # no clean shutdown -> stale socket file
        crashed.wait(5)
        new = self.launch()
        path = self.wait_listening()
        time.sleep(1.0)
        self.assertIsNone(new.poll())
        self.assertEqual(self.owner(path), [new.pid])


if __name__ == "__main__":
    unittest.main()
