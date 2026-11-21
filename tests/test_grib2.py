"""2.2.0: the GRIB2 reader (rbsb_weather/grib2.py), checked against ecCodes' answers.

tests/data holds real NOAA GFS 10 m winds and synthetic files written by ecCodes
with every packing the reader supports (tools/make_grib2_fixtures.py). Each file
is read with numpy and with the pure-Python path, and must give ecCodes' values:
the same sample points and the same checksum of every value to 3 decimals.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import hashlib
import json
import math
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets up the import path)

from rbsb_weather import grib2

DATA = Path(__file__).resolve().parent / "data"
EXPECTED = json.loads((DATA / "grib2_expected.json").read_text())


def _digest(vals):
    clean = [None if (v is None or v != v) else round(float(v), 3) for v in vals]
    return hashlib.sha256(json.dumps(clean).encode()).hexdigest()


class Grib2Case(unittest.TestCase):
    use_numpy = True

    def setUp(self):
        self._np = grib2._np
        if not self.use_numpy:
            grib2._np = None
        elif grib2._np is None:
            self.skipTest("numpy not installed")

    def tearDown(self):
        grib2._np = self._np

    def read(self, name):
        return grib2.messages((DATA / name).read_bytes())

    def test_every_file_matches_eccodes(self):
        for name, exp in EXPECTED.items():
            with self.subTest(name):
                msgs = self.read(name)
                if name == "gfs_2p5_wind10m.grib2":       # those messages also hold other fields
                    msgs = [m for m in msgs if m.level_type == 103]
                self.assertEqual(len(msgs), len(exp))
                for m, e in zip(msgs, exp):
                    self.assertEqual((m.grid.ni, m.grid.nj, m.category, m.number, m.grid.scan),
                                     (e["ni"], e["nj"], e["category"], e["number"], e["scan"]))
                    vals = list(m.values)
                    for i, want in e["samples"].items():
                        got = vals[int(i)]
                        if want is None:
                            self.assertTrue(got is None or got != got, f"{name}[{i}] should be missing")
                        else:
                            self.assertAlmostEqual(float(got), want, places=4, msg=f"{name}[{i}]")
                    self.assertEqual(sum(1 for v in vals if v is None or v != v), e["missing"])
                    self.assertEqual(_digest(vals), e["sha256_3dp"], f"{name}: values differ from ecCodes")

    def test_real_gfs_wind(self):
        msgs = [m for m in self.read("gfs_2p5_wind10m.grib2") if m.level_type == 103 and m.level == 10]
        self.assertEqual(sorted(m.number for m in msgs), [2, 3])          # U and V
        m = msgs[0]
        self.assertEqual((m.grid.ni, m.grid.nj), (144, 73))
        self.assertEqual((m.grid.la1, m.grid.lo1, m.grid.la2), (90.0, 0.0, -90.0))
        self.assertEqual(m.forecast_hours, 120)
        self.assertEqual(m.reference_time[:4][0] > 2000, True)
        speeds = [math.hypot(u, v) for u, v in zip(msgs[0].values, msgs[1].values)]
        self.assertLess(max(speeds), 60, "10 m wind speeds are physically plausible")
        self.assertGreater(sum(speeds) / len(speeds), 2)

    def test_rows_north_to_south(self):
        # Both files were written from the same list of values. The first file says its
        # first row is the southernmost, so read north to south its rows come out reversed
        a = self.read("syn_small_south_first.grib2")[0]
        b = self.read("syn_small_csd1.grib2")[0]                  # the usual north-first order
        self.assertEqual((a.grid.scan, b.grid.scan), (0x40, 0))
        ra, rb = a.rows_north_to_south(), b.rows_north_to_south()
        self.assertEqual(len(ra), 19)
        self.assertAlmostEqual(float(ra[0][5]), float(rb[-1][5]), places=2)
        self.assertAlmostEqual(float(ra[-1][7]), float(rb[0][7]), places=2)
        self.assertAlmostEqual(float(ra[3][11]), float(rb[-4][11]), places=2)

    def test_damaged_files_raise_cleanly(self):
        good = (DATA / "syn_small_csd1.grib2").read_bytes()
        bad = {
            "empty": b"",
            "not grib": b"<html>404 Not Found</html>",
            "cut short": good[:len(good) // 2],
            "no end marker": good[:-4] + b"XXXX",
            "grib1": good[:7] + b"\x01" + good[8:],
            "bad section length": good[:16] + b"\xff\xff\xff\xff" + good[20:],
        }
        for what, buf in bad.items():
            with self.subTest(what):
                with self.assertRaises(grib2.Grib2Error):
                    grib2.messages(buf)

    def test_huge_grid_refused(self):
        buf = bytearray((DATA / "syn_small_csd1.grib2").read_bytes())
        # section 3 starts after sections 0 (16 bytes) and 1; set Ni to 4 billion
        off = 16 + int.from_bytes(buf[16:20], "big")
        if buf[off + 4] == 2:
            off += int.from_bytes(buf[off:off + 4], "big")
        self.assertEqual(buf[off + 4], 3)
        buf[off + 30:off + 34] = (0xFFFFFFF0).to_bytes(4, "big")
        with self.assertRaisesRegex(grib2.Grib2Error, "grid size"):
            grib2.messages(bytes(buf))

    def test_signed_integers_are_sign_magnitude(self):
        self.assertEqual(grib2._s(b"\x80\x05", 0, 2), -5)
        self.assertEqual(grib2._s(b"\x00\x05", 0, 2), 5)
        self.assertEqual(grib2._s(b"\x85", 0, 1), -5)


class Grib2PurePython(Grib2Case):
    use_numpy = False


class Grib2AgainstEcCodes(unittest.TestCase):
    """Only where the ecCodes Python package is installed (the build machine): read every
    field of the full original GFS sample, if present, and compare value by value."""

    def test_full_sample(self):
        try:
            import eccodes
        except Exception:
            self.skipTest("ecCodes not installed (only needed on the build machine)")
        src = Path("/tmp/pygrib_src/sampledata/gfs.t12z.pgrbf120.2p5deg.grib2")
        if not src.exists():
            self.skipTest("the full GFS sample file isn't on this machine")
        msgs = grib2.messages(src.read_bytes())
        eccodes.codes_grib_multi_support_on()
        n = 0
        with open(src, "rb") as f:
            while (h := eccodes.codes_grib_new_from_file(f)) is not None:
                ref = eccodes.codes_get_values(h)
                miss = eccodes.codes_get(h, "missingValue") if eccodes.codes_get(h, "bitmapPresent") else None
                mine = list(msgs[n].values)
                self.assertEqual(len(ref), len(mine))
                for a, b in zip(ref, mine):
                    if miss is not None and a == miss:
                        self.assertTrue(b != b, "missing in ecCodes, so NaN here")
                    else:
                        self.assertLess(abs(a - b), 1e-6)
                eccodes.codes_release(h)
                n += 1
        eccodes.codes_grib_multi_support_off()
        self.assertEqual(n, len(msgs))


if __name__ == "__main__":
    unittest.main()
