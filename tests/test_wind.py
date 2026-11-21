"""2.2.0: the Wind tab. World wind data (rbsb_weather/wind.py) and the globe (wind_panel.py).

A local fake NOAA answers like NOMADS (the grib filter) and like NOAA's GFS
copy on Amazon (an .idx index plus byte-range requests), serving the real
GFS 10 m wind from tests/data. Nothing here contacts NOAA.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import http.server
import math
import resource
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

from helpers import TempEnvTestCase, qapp, wait_until

from rbsb_weather import wind as W

DATA = Path(__file__).resolve().parent / "data"
GFS = (DATA / "gfs_2p5_wind10m.grib2").read_bytes()
LAYERS = (DATA / "gfs_2p5_layers.grib2").read_bytes()      # wind, 2 m temperature, precipitation rate (2.3)
UTC = dt.timezone.utc


class FakeNOAA:
    def __init__(self):
        self.nomads_ok = True
        self.missing_runs: set[str] = set()       # "YYYYMMDD/HH" that aren't published yet
        self.requests: list[str] = []
        self.ranges: list[str] = []
        self.payload = LAYERS                     # what NOMADS returns: wind, temperature, rain (2.3)
        filler = b"GRIB" + b"\x00" * 300            # something before our fields in the "full file"
        self.full = filler + LAYERS + b"GRIB-OTHER-FIELD" * 20
        self.wind_at = len(filler)
        # where each field's message starts inside LAYERS (one field per message)
        from rbsb_weather import grib2 as _g
        self.offsets = []
        pos = 0
        while pos < len(LAYERS):
            self.offsets.append(pos)
            pos += int.from_bytes(LAYERS[pos + 8:pos + 16], "big")
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, extra=None):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append(self.path)
                u = urllib.parse.urlsplit(self.path)
                if u.path.startswith("/nomads"):
                    q = dict(urllib.parse.parse_qsl(u.query))
                    day_hour = q["dir"].split("gfs.")[1].split("/atmos")[0]
                    if not outer.nomads_ok:
                        return self.send(503, b"<html>busy</html>")
                    if day_hour in outer.missing_runs:
                        return self.send(404, b"<html>no such file</html>")
                    return self.send(200, outer.payload)
                if u.path.startswith("/aws/"):
                    day_hour = u.path.split("gfs.")[1].split("/atmos")[0]
                    if day_hour in outer.missing_runs:
                        return self.send(404, b"NoSuchKey")
                    if u.path.endswith(".idx"):
                        o = [outer.wind_at + x for x in outer.offsets]   # file order: TMP, UGRD, VGRD, PRATE
                        names = ["TMP:2 m above ground", "UGRD:10 m above ground", "VGRD:10 m above ground",
                                 "PRATE:surface:0-6 hour ave"]
                        lines = ["1:0:d=2026112100:PRMSL:mean sea level:6 hour fcst:"]
                        lines += [f"{k + 2}:{off}:d=2026112100:{nm}:6 hour fcst:" for k, (off, nm) in enumerate(zip(o, names))]
                        lines.append(f"6:{outer.wind_at + len(LAYERS)}:d=2026112100:APCP:surface:0-6 hour acc fcst:")
                        return self.send(200, ("\n".join(lines) + "\n").encode())
                    rng = self.headers.get("Range", "")
                    outer.ranges.append(rng)
                    a, b = rng.split("=")[1].split("-")
                    a, b = int(a), (int(b) if b else len(outer.full) - 1)
                    return self.send(206, outer.full[a:b + 1])
                self.send(404, b"")

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.client = W.WindClient(base + "/nomads", base + "/aws", timeout=5)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ====================================================================== data
class TestRunsAndUrls(unittest.TestCase):
    def test_newest_published_run_and_closest_hour(self):
        now = dt.datetime(2026, 11, 21, 9, 40, tzinfo=UTC)          # 06Z isn't out until ~10Z
        runs = W.runs_to_try(now)
        self.assertEqual(runs[0], (dt.datetime(2026, 11, 21, 0, tzinfo=UTC), 9))     # 9h40 -> +9 h
        self.assertEqual(runs[1], (dt.datetime(2026, 11, 20, 18, tzinfo=UTC), 15))
        later = W.runs_to_try(dt.datetime(2026, 11, 21, 10, 10, tzinfo=UTC))
        self.assertEqual(later[0], (dt.datetime(2026, 11, 21, 6, tzinfo=UTC), 3))
        # local times are converted to UTC first
        nz = dt.timezone(dt.timedelta(hours=13))
        self.assertEqual(W.runs_to_try(dt.datetime(2026, 11, 21, 22, 40, tzinfo=nz))[0], runs[0])

    def test_urls(self):
        run = dt.datetime(2026, 11, 21, 6, tzinfo=UTC)
        u = urllib.parse.urlsplit(W.nomads_url(run, 9))
        q = dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual((u.scheme, u.netloc), ("https", "nomads.ncep.noaa.gov"))
        self.assertEqual(q["dir"], "/gfs.20261121/06/atmos")
        self.assertEqual(q["file"], "gfs.t06z.pgrb2.1p00.f009")
        for k in ("var_UGRD", "var_VGRD", "var_TMP", "var_PRATE", "lev_10_m_above_ground",
                  "lev_2_m_above_ground", "lev_surface"):
            self.assertEqual(q[k], "on", k)
        data, idx = W.aws_urls(run, 9)
        self.assertEqual(data, "https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.20261121/06/atmos/gfs.t06z.pgrb2.1p00.f009")
        self.assertEqual(idx, data + ".idx")

    def test_index_byte_ranges(self):
        idx = ("1:0:d=x:PRMSL:mean sea level:anl:\n2:500:d=x:UGRD:10 m above ground:anl:\n"
               "3:900:d=x:VGRD:10 m above ground:anl:\n4:1400:d=x:UGRD:20 m above ground:anl:\n")
        self.assertEqual(W.byte_ranges_from_index(idx), [(500, 899), (900, 1399)])
        full = ("1:0:d=x:PRMSL:mean sea level:6 hour fcst:\n2:500:d=x:TMP:surface:6 hour fcst:\n"
                "3:800:d=x:TMP:2 m above ground:6 hour fcst:\n4:1100:d=x:UGRD:10 m above ground:6 hour fcst:\n"
                "5:1500:d=x:VGRD:10 m above ground:6 hour fcst:\n6:1900:d=x:PRATE:surface:0-6 hour ave fcst:\n"
                "7:2300:d=x:APCP:surface:0-6 hour acc fcst:\n")
        self.assertEqual(W.byte_ranges_from_index(full), [(800, 1099), (1100, 1499), (1500, 1899), (1900, 2299)],
                         "2.3: 2 m temperature and precipitation rate too, but not surface TMP or APCP")
        shared = "1:0:d=x:A:b:c:\n2.1:300:d=x:UGRD:10 m above ground:c:\n2.2:300:d=x:VGRD:10 m above ground:c:\n"
        self.assertEqual(W.byte_ranges_from_index(shared), [(300, None)])   # one message, to the end
        with self.assertRaises(W.WindError):
            W.byte_ranges_from_index("1:0:d=x:TMP:2 m above ground:anl:\n")

    def test_direction_convention(self):
        self.assertEqual(W.speed_and_direction(0, -5), (5.0, 0.0))          # blowing south = from the north
        spd, frm = W.speed_and_direction(5, 0)                             # blowing east = from the west
        self.assertAlmostEqual(frm, 270.0)
        self.assertAlmostEqual(W.speed_and_direction(-3, -4)[1], 36.87, places=2)   # from the NE


class TestField(unittest.TestCase):
    def setUp(self):
        self.fld = W.field_from_grib(GFS)

    def test_real_gfs_field(self):
        f = self.fld
        self.assertEqual((f.ni, f.nj, f.lat0, f.lon0, f.dlat, f.dlon), (144, 73, 90.0, 0.0, 2.5, 2.5))
        self.assertEqual(f.fhour, 120)
        # at a grid point, at() is the grid value; in between, it's between its neighbours
        u, v = f.at(-35.0, 175.0)
        self.assertAlmostEqual(u, float(f.u[50][70]), places=4)
        self.assertAlmostEqual(v, float(f.v[50][70]), places=4)
        um, _ = f.at(-36.25, 176.25)
        corners = [float(f.u[j][i]) for j in (50, 51) for i in (70, 71)]
        self.assertGreaterEqual(um, min(corners) - 1e-6)
        self.assertLessEqual(um, max(corners) + 1e-6)
        # longitude wraps: 360° = 0°, -180° = 180°
        self.assertEqual(f.at(10, 0), f.at(10, 360))
        self.assertEqual(f.at(10, -180), f.at(10, 180))
        self.assertEqual(f.at(-90, 10), f.at(-95, 10))                   # clamped at the poles

    def test_vectorised_matches_single(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        lats = np.array([-36.85, 0.0, 51.5, -89.0, 89.9, 12.3])
        lons = np.array([174.76, -179.99, -0.12, 33.0, -100.0, 359.0])
        us, vs = self.fld.at_many(lats, lons)
        for la, lo, a, b in zip(lats, lons, us, vs):
            u, v = self.fld.at(float(la), float(lo))
            self.assertAlmostEqual(float(a), u, places=4)
            self.assertAlmostEqual(float(b), v, places=4)

    def test_pure_python_field(self):
        from rbsb_weather import grib2
        saved = (W._np, grib2._np)
        W._np = grib2._np = None
        try:
            f = W.field_from_grib(GFS)
        finally:
            W._np, grib2._np = saved
        self.assertIsInstance(f.u, list)
        for la, lo in ((-36.85, 174.76), (51.5, -0.12), (0, 0)):
            a, b = f.at(la, lo), self.fld.at(la, lo)
            self.assertAlmostEqual(a[0], b[0], places=4)
            self.assertAlmostEqual(a[1], b[1], places=4)

    def test_not_wind_or_damaged(self):
        with self.assertRaises(Exception):
            W.field_from_grib(b"<html>404</html>")
        other = (DATA / "syn_small_simple.grib2").read_bytes()             # category 2 no. 2, but not at 10 m? it is U at 10 m
        with self.assertRaises(W.WindError):                                 # ...yet there's no V
            W.field_from_grib(other)

    def test_colours(self):
        self.assertEqual(W.colour_for(-1), W.SPEED_COLOURS[0][1])
        self.assertEqual(W.colour_for(1000), W.SPEED_COLOURS[-1][1])
        self.assertEqual(W.colour_for(1.0), tuple(round((a + b) / 2) for a, b in
                                                 zip(W.SPEED_COLOURS[0][1], W.SPEED_COLOURS[1][1])))


class TestLayers(unittest.TestCase):
    """2.3.0: temperature and rain from the real GFS sample."""

    def setUp(self):
        self.fld = W.field_from_grib(LAYERS)

    def test_layers_present_and_in_the_right_units(self):
        f = self.fld
        self.assertEqual(f.layers, ["wind", "temp", "rain"])
        import json
        exp = {(e["category"], e["number"]): e for e in json.loads((DATA / "grib2_expected.json").read_text())["gfs_2p5_layers.grib2"]}
        # ecCodes' value of the first grid point (north pole row, 0°E), converted
        self.assertAlmostEqual(float(f.temp[0][0]), exp[(0, 0)]["samples"]["0"] - 273.15, places=3)
        self.assertAlmostEqual(float(f.rain[0][0]), exp[(1, 7)]["samples"]["0"] * 3600, places=3)
        temps = [float(x) for row in f.temp for x in row]
        self.assertGreater(min(temps), -60)
        self.assertLess(max(temps), 60)
        rains = [float(x) for row in f.rain for x in row]
        self.assertGreaterEqual(min(rains), 0)
        self.assertLess(max(rains), 100, "mm/h")
        self.assertGreater(sum(1 for r in rains if r < W.RAIN_MIN) / len(rains), 0.3, "most of the world is dry")
        # temperature at a grid point is the grid value; rain never negative
        self.assertAlmostEqual(f.temp_at(-35.0, 175.0), float(f.temp[50][70]), places=4)
        self.assertGreaterEqual(f.rain_at(10, 10), 0)
        # the wind is the same as in the wind-only file
        w = W.field_from_grib(GFS)
        self.assertEqual(f.at(-36.85, 174.76), w.at(-36.85, 174.76))

    def test_wind_only_file(self):
        f = W.field_from_grib(GFS)
        self.assertEqual(f.layers, ["wind"])
        self.assertIsNone(f.temp_at(0, 0))
        self.assertIsNone(f.rain_at(0, 0))

    def test_pure_python_layers(self):
        from rbsb_weather import grib2
        saved = (W._np, grib2._np)
        W._np = grib2._np = None
        try:
            f = W.field_from_grib(LAYERS)
        finally:
            W._np, grib2._np = saved
        for la, lo in ((-36.85, 174.76), (51.5, -0.12), (5, 100)):
            self.assertAlmostEqual(f.temp_at(la, lo), self.fld.temp_at(la, lo), places=3)
            self.assertAlmostEqual(f.rain_at(la, lo), self.fld.rain_at(la, lo), places=4)

    def test_colour_maps(self):
        from helpers import qapp
        qapp()
        for layer in ("wind", "temp", "rain"):
            img = W.layer_map(self.fld, layer)
            self.assertEqual((img.width(), img.height()), (144, 73))
        rain = W.layer_map(self.fld, "rain")
        alphas = [rain.pixelColor(i, j).alpha() for j in range(0, 73, 4) for i in range(0, 144, 4)]
        self.assertIn(0, alphas, "dry areas are see-through")
        self.assertTrue(any(a > 0 for a in alphas), "rainy areas are coloured")
        self.assertEqual(W.rain_alpha(0.0), 0)
        self.assertEqual(W.rain_alpha(5.0), 255)
        cold, hot = W._lerp_colour(W.TEMP_COLOURS, -30), W._lerp_colour(W.TEMP_COLOURS, 35)
        self.assertGreater(cold[2], cold[0], "cold is blue")
        self.assertGreater(hot[0], hot[2], "hot is red")
        # a layer the field doesn't have falls back to wind
        wind_only = W.field_from_grib(GFS)
        self.assertEqual(W.layer_map(wind_only, "temp").pixel(10, 10), W.layer_map(wind_only, "wind").pixel(10, 10))

    def test_point_text_in_units(self):
        from rbsb_weather.wind_panel import point_text, rain_text
        t = point_text(self.fld, -36.85, 174.76, "kn", "F", "in")
        self.assertIn(" kn from the ", t)
        self.assertIn("°F", t)
        self.assertIn("rain/snow", t)
        self.assertEqual(rain_text(0.0, "mm"), "dry")
        self.assertEqual(rain_text(2.54, "in"), "0.10 in/h")
        self.assertEqual(rain_text(1.25, "mm"), "1.2 mm/h")
        only = point_text(W.field_from_grib(GFS), 0, 0, "km/h", "C", "mm")
        self.assertNotIn("°C", only, "wind only: no temperature shown")
        self.assertNotIn("rain", only)


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.noaa = FakeNOAA()
        self.now = dt.datetime(2026, 11, 21, 9, 40, tzinfo=UTC)

    def tearDown(self):
        self.noaa.stop()

    def test_from_nomads(self):
        data, run, fh, src = self.noaa.client.fetch(self.now)
        self.assertEqual((run.hour, fh, src), (0, 9, "NOAA NOMADS"))
        self.assertEqual(data, LAYERS)

    def test_newest_run_not_out_yet(self):
        self.noaa.missing_runs.add("20261121/00")
        data, run, fh, src = self.noaa.client.fetch(self.now)
        self.assertEqual((run, fh), (dt.datetime(2026, 11, 20, 18, tzinfo=UTC), 15))   # same time, older run

    def test_nomads_down_uses_aws_byte_ranges(self):
        self.noaa.nomads_ok = False
        data, run, fh, src = self.noaa.client.fetch(self.now)
        self.assertEqual(src, "NOAA on AWS")
        self.assertEqual(data, LAYERS, "exactly the four fields, cut out by byte range")
        self.assertEqual(len(self.noaa.ranges), 4)
        fld = W.field_from_grib(data, run)
        self.assertEqual((fld.ni, fld.layers), (144, ["wind", "temp", "rain"]))

    def test_nothing_reachable(self):
        c = W.WindClient("http://127.0.0.1:9/nomads", "http://127.0.0.1:9/aws", timeout=2)
        with self.assertRaisesRegex(W.WindError, "couldn't be downloaded from NOAA"):
            c.fetch(self.now)


class TestStore(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.noaa = FakeNOAA()
        self.store = W.WindStore(self.tmp / "wind")

    def tearDown(self):
        self.noaa.stop()
        super().tearDown()

    def test_download_save_reuse_and_refresh(self):
        now = dt.datetime.now(UTC)
        fld, note = W.update(self.store, self.noaa.client, now)
        self.assertIsNotNone(fld)
        self.assertEqual(note, "")
        n = len(self.noaa.requests)
        self.assertFalse(self.store.due(now))
        fld2, _ = W.update(self.store, self.noaa.client, now)          # not due: the saved one, no network
        self.assertEqual(len(self.noaa.requests), n)
        self.assertEqual((fld2.ni, fld2.run), (fld.ni, fld.run))
        self.assertTrue(self.store.due(now + dt.timedelta(hours=3)))     # 3 hours on: the next forecast hour

    def test_failure_keeps_the_saved_map_and_waits(self):
        now = dt.datetime.now(UTC)
        W.update(self.store, self.noaa.client, now)
        self.noaa.nomads_ok = False
        self.noaa.missing_runs.update({f"{(now - dt.timedelta(hours=h)):%Y%m%d}/{h2:02d}"
                                       for h in range(0, 30) for h2 in (0, 6, 12, 18)})
        later = now + dt.timedelta(hours=4)
        fld, note = W.update(self.store, self.noaa.client, later)
        self.assertIsNotNone(fld, "the saved map is still shown")
        self.assertIn("saved one", note)
        self.assertFalse(self.store.due(later), "not retried straight away after a failure")

    def test_nothing_saved_and_offline(self):
        c = W.WindClient("http://127.0.0.1:9/nomads", "http://127.0.0.1:9/aws", timeout=2)
        with self.assertRaises(W.WindError):
            W.update(self.store, c)

    def test_damaged_download_never_replaces_the_saved_map(self):
        now = dt.datetime.now(UTC)
        W.update(self.store, self.noaa.client, now)
        good = self.store.data_path.read_bytes()

        class Bad(W.WindClient):
            def fetch(self, now=None, cancelled=None):
                return b"GRIB\x00\x00\x00\x02" + b"\x00" * 30, now, 0, "bad"
        W.update(self.store, Bad(), now + dt.timedelta(hours=4))
        self.assertEqual(self.store.data_path.read_bytes(), good)

    def test_saved_wind_only_map_is_upgraded_once(self):
        """A map saved by 2.2.0 has only the wind: it's shown, and the layers fetched once."""
        now = dt.datetime.now(UTC)
        run, fh = W.runs_to_try(now)[0]
        self.store.save(GFS, run, fh, "2.2.0")
        m = self.store.meta()
        m.pop("layers")
        from rbsb_weather.storage import atomic_write_json
        atomic_write_json(self.store.meta_path, m)
        self.assertEqual(self.store.load().layers, ["wind"])
        self.assertTrue(self.store.due(now), "fetch once for the new layers")
        fld, _ = W.update(self.store, self.noaa.client, now)
        self.assertEqual(fld.layers, ["wind", "temp", "rain"])
        self.assertFalse(self.store.due(now))

    def test_damaged_saved_file(self):
        self.store.dir.mkdir(parents=True)
        self.store.data_path.write_bytes(b"rubbish")
        self.store.meta_path.write_text('{"run": "2026-11-21T00:00:00+00:00", "fhour": 9}')
        self.assertIsNone(self.store.load())


# ====================================================================== the tab
class TestWindTab(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        self.noaa = FakeNOAA()
        from rbsb_weather.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False, wind_client=self.noaa.client)
        self.w.resize(1000, 760)
        self.w.show()
        self.panel = self.w.wind_panel
        self.view = self.panel.view

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        from PyQt6.QtTest import QTest
        QTest.qWait(30)
        self.noaa.stop()
        super().tearDown()

    def show_tab(self):
        self.w.tabs.setCurrentWidget(self.panel)
        self.assertTrue(wait_until(lambda: self.view.image is not None, 15), self.panel.info.text())

    def test_tab_downloads_only_when_shown(self):
        texts = [self.w.tabs.tabText(i) for i in range(self.w.tabs.count())]
        self.assertIn("🌬 Wind", texts)
        from PyQt6.QtTest import QTest
        QTest.qWait(300)
        self.assertEqual(self.noaa.requests, [], "nothing is downloaded until the tab is opened")
        self.show_tab()
        self.assertEqual(len(self.noaa.requests), 1)
        self.assertIn("NOAA's GFS", self.panel.info.text())
        self.assertTrue((self.tmp / "cache" / "wind" / "gfs_wind10m.grib2").exists())

    def test_streaks_move_only_while_shown_and_on(self):
        from PyQt6.QtTest import QTest
        self.show_tab()
        self.assertTrue(wait_until(lambda: self.view.frames > 10, 5))
        self.w.tabs.setCurrentIndex(0)
        QTest.qWait(100)
        n = self.view.frames
        QTest.qWait(500)
        self.assertEqual(self.view.frames, n, "no frames while another tab is shown")
        self.w.tabs.setCurrentWidget(self.panel)
        self.assertTrue(wait_until(lambda: self.view.frames > n + 5, 5))
        self.panel.streaks_box.setChecked(False)
        QTest.qWait(100)
        n = self.view.frames
        QTest.qWait(400)
        self.assertEqual(self.view.frames, n, "streaks off: no frames")
        self.panel.streaks_box.setChecked(True)
        self.w.set_animations(False)
        QTest.qWait(100)
        n = self.view.frames
        QTest.qWait(400)
        self.assertEqual(self.view.frames, n, "View → Animations off: no frames")

    def test_hover_readout_in_the_users_units(self):
        from PyQt6.QtCore import QPointF
        self.show_tab()
        self.w.set_unit("wind_unit", "kn")
        self.assertEqual(self.panel.legend.unit, "kn")
        r = self.view.globe_rect()
        lat, lon, u, v = self.view.wind_at_pos(r.center())
        self.assertAlmostEqual(lat, self.view.c_lat, places=3)
        seen = []
        self.view.hover_text.connect(seen.append)
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtCore import QEvent, Qt
        ev = QMouseEvent(QEvent.Type.MouseMove, r.center(), r.center(), Qt.MouseButton.NoButton,
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        self.view.mouseMoveEvent(ev)
        self.assertTrue(seen and " kn from the " in seen[-1], seen)
        self.assertIsNone(self.view.wind_at_pos(QPointF(2, 2)), "outside the globe: nothing")

    def test_turning_clears_the_streaks(self):
        self.show_tab()
        self.assertTrue(wait_until(lambda: self.view.trails is not None, 5))
        self.view.set_center(10, 20)
        self.assertIsNone(self.view.trails)

    def test_offline_with_nothing_saved(self):
        self.w._wind_client = W.WindClient("http://127.0.0.1:9/nomads", "http://127.0.0.1:9/aws", timeout=2)
        self.w.tabs.setCurrentWidget(self.panel)
        self.assertTrue(wait_until(lambda: "couldn't be downloaded" in self.panel.info.text(), 20),
                        self.panel.info.text())
        self.assertIsNone(self.view.image)

    def test_saved_map_shown_at_once_offline(self):
        W.update(W.WindStore(self.tmp / "cache" / "wind"), self.noaa.client)
        self.noaa.stop()
        self.w._wind_client = W.WindClient("http://127.0.0.1:9/nomads", "http://127.0.0.1:9/aws", timeout=2)
        self.w.tabs.setCurrentWidget(self.panel)
        self.assertIsNotNone(self.view.field, "the saved map is loaded straight away, before any download")
        self.assertTrue(wait_until(lambda: self.view.image is not None, 1.0), "and drawn on the next repaint")
        self.noaa = FakeNOAA()                      # so tearDown has something to stop

    def test_layer_buttons_and_remembered_layer(self):
        self.show_tab()
        p = self.panel
        self.assertEqual([b.text() for b in p.layer_buttons.values()],
                         ["🌬 Wind", "🌡 Temperature", "🌧 Rain && snow"])     # shows "Rain & snow"
        self.assertTrue(all(b.isEnabled() for b in p.layer_buttons.values()))
        wind_img = self.view.image
        p.layer_buttons["temp"].click()
        self.assertTrue(wait_until(lambda: self.view.image is not wind_img, 3))
        self.assertEqual(self.w.settings.wind_layer, "temp")
        self.assertEqual(p.legend.layer, "temp")
        self.assertIn("Air temperature", p.info.text())
        self.assertTrue(self.view.timer.isActive(), "the wind streaks keep moving on other layers")
        from rbsb_weather.storage import SettingsStore
        self.assertEqual(SettingsStore().load().wind_layer, "temp", "remembered")
        self.w.set_unit("temp_unit", "F")
        self.assertEqual(p.legend.temp_unit, "F")
        self.assertEqual(self.view.temp_unit, "F")
        p.layer_buttons["rain"].click()
        self.assertEqual(p.legend.layer, "rain")

    def test_buttons_disabled_without_the_layers(self):
        self.show_tab()
        self.panel.set_layer("rain", user=True)
        self.panel.set_field(W.field_from_grib(GFS))          # an old wind-only map
        self.assertFalse(self.panel.layer_buttons["rain"].isEnabled())
        self.assertTrue(self.panel.layer_buttons["wind"].isChecked(), "falls back to wind")
        self.assertEqual(self.panel.layer, "rain", "the choice is kept for when the layers arrive")
        self.panel.set_field(W.field_from_grib(LAYERS))
        self.assertTrue(self.panel.layer_buttons["rain"].isChecked())

    def test_frame_cost(self):
        """One streak frame must stay well inside the 33 ms frame budget."""
        from PyQt6.QtTest import QTest
        self.show_tab()
        QTest.qWait(500)
        t0, f0 = time.process_time(), self.view.frames
        QTest.qWait(2000)
        frames = self.view.frames - f0
        per = (time.process_time() - t0) / max(1, frames) * 1000
        print(f"\n  wind streaks: {frames / 2:.0f} frames/s, {per:.1f} ms of CPU per frame "
              f"({self.view.particles.n} streaks)")
        self.assertGreater(frames, 20)
        self.assertLess(per, 25)


class TestParticlesPurePython(unittest.TestCase):
    def test_step_without_numpy(self):
        from rbsb_weather import grib2, wind_panel
        saved = (W._np, grib2._np, wind_panel._np)
        W._np = grib2._np = wind_panel._np = None
        try:
            fld = W.field_from_grib(GFS)
            ps = wind_panel.Particles(200)
            ps.seed_all(-30.0, 150.0)
            la0 = list(ps.lat)
            for _ in range(5):
                out = ps.step(fld, -30.0, 150.0)
            moved = sum(1 for a, b in zip(la0, ps.lat) if a != b)
            self.assertGreater(moved, 150)
            self.assertEqual(len(out[0]), 200)
        finally:
            W._np, grib2._np, wind_panel._np = saved


if __name__ == "__main__":
    unittest.main()
