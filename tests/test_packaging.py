"""Package tests: build the .deb and source archive from a copy of the project and check
what's inside, then run the packaged app's own self-check from the unpacked tree.

These don't install anything (installing needs root and changes the machine); the real
dpkg install/upgrade test is recorded in TEST_REPORT.md.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET = "-".join(["SHOULD", "NOT", "SHIP"])     # built at run time so this file doesn't contain it
HAVE_DPKG = shutil.which("dpkg-deb") is not None


@unittest.skipUnless(HAVE_DPKG, "dpkg-deb is not installed")
class TestPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="wd-pkg-"))
        work = cls.tmp / "src"
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "dist", "test-results.log", ".git")
        shutil.copytree(ROOT, work, ignore=ignore)
        # a stray secret in the working copy must never reach the source archive
        (work / "keys.json").write_text('{"tomorrow": "%s"}' % SECRET)
        (work / "rbsb_weather" / "test.key").write_text(SECRET)
        (work / ".env").write_text("KEY=" + SECRET)
        out = subprocess.run(["bash", "build_deb.sh"], cwd=work, capture_output=True, text=True, timeout=300)
        if out.returncode:
            raise AssertionError(f"build failed:\n{out.stdout}\n{out.stderr}")
        init = (ROOT / "rbsb_weather" / "__init__.py").read_text()
        cls.version = re.search(r'__version__ = "(.+?)"', init).group(1)
        cls.dist = work / "dist"
        cls.deb = cls.dist / f"rbsb-weather_{cls.version}_all.deb"
        cls.src = cls.dist / f"rbsb-weather-{cls.version}-source.tar.gz"
        cls.unpacked = cls.tmp / "root"
        subprocess.run(["dpkg-deb", "-R", str(cls.deb), str(cls.unpacked)], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def field(self, name):
        m = re.search(rf"^{name}: (.+)$", (self.unpacked / "DEBIAN" / "control").read_text(), re.M)
        return m.group(1) if m else None

    def test_control_fields(self):
        self.assertEqual(self.field("Package"), "rbsb-weather")
        self.assertEqual(self.field("Version"), self.version)
        self.assertEqual(self.field("Architecture"), "all")
        self.assertEqual(self.field("Depends"), "python3 (>= 3.10), python3-pyqt6")
        rec = self.field("Recommends")
        for r in ("python3-keyring", "python3-numpy", "fonts-noto-color-emoji"):
            self.assertIn(r, rec)
        self.assertIn("Created By Shane BlackbuRn", self.field("Description"))
        # 2.0.0 rename: installing rbsb-weather cleanly replaces the old weatherdesk package
        self.assertEqual(self.field("Replaces"), "weatherdesk")
        self.assertEqual(self.field("Conflicts"), "weatherdesk")

    def test_every_module_and_asset_is_packaged(self):
        lib = self.unpacked / "usr/lib/rbsb-weather/rbsb_weather"
        for src in (ROOT / "rbsb_weather").rglob("*"):
            if "__pycache__" in src.parts or src.is_dir():
                continue
            rel = src.relative_to(ROOT / "rbsb_weather")
            self.assertTrue((lib / rel).is_file(), f"missing from the package: {rel}")
            self.assertEqual((lib / rel).read_bytes(), src.read_bytes(), rel)

    def test_launcher_desktop_icon_docs(self):
        u = self.unpacked / "usr"
        launcher = u / "bin/rbsb-weather"
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn("PYTHONPATH=/usr/lib/rbsb-weather", launcher.read_text())
        self.assertIn("-m rbsb_weather", launcher.read_text())
        old = u / "bin/weatherdesk"                  # the old command still works
        self.assertTrue(old.is_symlink())
        self.assertEqual(os.readlink(old), "rbsb-weather")
        desk = (u / "share/applications/rbsb-weather.desktop").read_text()
        self.assertIn("Exec=rbsb-weather\n", desk)
        self.assertIn("Icon=rbsb-weather", desk)
        self.assertIn("Name=RBSB-Weather", desk)
        self.assertIn("weatherdesk;", desk)             # still found by searching the old name
        self.assertTrue((u / "share/icons/hicolor/scalable/apps/rbsb-weather.svg").is_file())
        for d in ("README.md", "changelog.gz", "copyright"):
            self.assertTrue((u / "share/doc/rbsb-weather" / d).is_file(), d)

    def test_no_caches_or_secrets_in_package(self):
        for p in self.unpacked.rglob("*"):
            self.assertNotIn("__pycache__", p.parts, p)
            self.assertFalse(p.name.endswith((".pyc", ".key")) or p.name in ("keys.json", ".env"), p)

    def test_maintainer_scripts(self):
        prerm = self.unpacked / "DEBIAN/prerm"
        self.assertTrue(os.access(prerm, os.X_OK))
        self.assertIn("__pycache__", prerm.read_text())
        # nothing in the package touches ~/.config, so settings and keys survive upgrades/removal
        for s in (self.unpacked / "DEBIAN").iterdir():
            self.assertNotIn(".config", s.read_text(errors="replace"), s.name)

    def test_source_archive_clean_and_complete(self):
        with tarfile.open(self.src) as t:
            names = t.getnames()
            top = f"rbsb-weather-{self.version}"
            for must in ("rbsb_weather/__init__.py", "rbsb_weather/providers/manager.py", "tests/test_audit.py", "tests/test_migrate.py", "rbsb_weather/migrate.py",
                         "build_deb.sh", "run_tests.sh", "README.md", "CHANGELOG.md", "TEST_REPORT.md",
                         "TRANSCRIPT.md"):
                self.assertIn(f"{top}/{must}", names)
            for n in names:
                self.assertFalse(n.endswith(("keys.json", ".key", ".pyc", ".env")) or "__pycache__" in n
                                 or "/dist/" in n, n)
            for m in t.getmembers():
                if m.isfile():
                    self.assertNotIn(SECRET.encode(), t.extractfile(m).read(), m.name)

    def test_checksums_match(self):
        out = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=self.dist, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_packaged_app_runs_its_self_check(self):
        """Run the packaged copy (not the source tree) far enough to print its version."""
        env = dict(os.environ, PYTHONPATH=str(self.unpacked / "usr/lib/rbsb-weather"), QT_QPA_PLATFORM="offscreen")
        out = subprocess.run([sys.executable, "-c", "import rbsb_weather, rbsb_weather.app, rbsb_weather.main_window,"
                              " rbsb_weather.providers.manager; print(rbsb_weather.__version__, rbsb_weather.__file__)"],
                             env=env, capture_output=True, text=True, timeout=60, cwd=self.tmp)
        self.assertEqual(out.returncode, 0, out.stderr)
        ver, path = out.stdout.split()
        self.assertEqual(ver, self.version)
        self.assertTrue(path.startswith(str(self.unpacked)), path)


if __name__ == "__main__":
    unittest.main()
