"""Moon tests: astronomy against PyEphem reference values, image rendering,
the NASA texture converter, and the Moon tab."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import PLACES, ROOT, TempEnvTestCase, qapp, wait_until

from weatherdesk import moon as M

REF = json.loads((Path(__file__).with_name("moon_reference.json")).read_text())
UTC = dt.timezone.utc
REPORT: list[str] = []


def _t(s):
    return dt.datetime.fromisoformat(s)


class TestAstronomy(unittest.TestCase):
    def test_rise_set_matches_reference(self):
        worst = {}
        for row in REF["riseset"]:
            tz = M.tz_for(row["tz"])
            d = dt.date.fromisoformat(row["date"])
            rise, sett = M.rise_set(d, row["lat"], row["lon"], tz)
            for mine, ref, key in ((rise, row["rise"], "rise"), (sett, row["set"], "set")):
                self.assertEqual(mine is None, ref is None, f"{row['place']} {d} {key}: {mine} vs {ref}")
                if mine is not None:
                    diff = abs((mine - _t(ref)).total_seconds())
                    worst[row["place"]] = max(worst.get(row["place"], 0), diff)
                    # grazing rise/set near the Arctic circle magnifies tiny position differences
                    limit = 300 if row["place"] == "Tromso" else 90
                    self.assertLess(diff, limit, f"{row['place']} {d} {key} off by {diff:.0f}s")
                    self.assertEqual(mine.date(), d)
                    self.assertIsNotNone(mine.tzinfo)
        REPORT.append("rise/set worst vs PyEphem: " + ", ".join(f"{k} {v:.0f}s" for k, v in worst.items()))

    def test_illumination_matches_reference(self):
        worst = 0.0
        for t, pct in REF["illum"]:
            worst = max(worst, abs(M.moon_phase(_t(t)).illumination * 100 - pct))
        REPORT.append(f"illumination worst diff {worst:.3f} percentage points")
        self.assertLess(worst, 0.3)

    def test_principal_phase_times(self):
        worst = 0.0
        for target, after, ref in REF["phases"]:
            mine = M.next_phase_time(_t(after), float(target))
            worst = max(worst, abs((mine - _t(ref)).total_seconds()))
        REPORT.append(f"new/quarter/full moon times worst diff {worst:.0f}s")
        self.assertLess(worst, 120)

    def test_phase_names(self):
        self.assertEqual(M.phase_name(0), "New Moon")
        self.assertEqual(M.phase_name(359), "New Moon")
        self.assertEqual(M.phase_name(45), "Waxing Crescent")
        self.assertEqual(M.phase_name(90), "First Quarter")
        self.assertEqual(M.phase_name(135), "Waxing Gibbous")
        self.assertEqual(M.phase_name(180), "Full Moon")
        self.assertEqual(M.phase_name(225), "Waning Gibbous")
        self.assertEqual(M.phase_name(270), "Last Quarter")
        self.assertEqual(M.phase_name(300), "Waning Crescent")

    def test_seven_days_name_principal_phase_only_on_its_day(self):
        tz = M.tz_for("Pacific/Auckland")
        days = M.moon_days(-36.85, 174.76, tz, dt.date(2026, 11, 15), 7)
        self.assertEqual(len(days), 7)
        names = [d.name for d in days]
        self.assertEqual(names.count("First Quarter"), 1)          # 18 Nov 00:47 NZDT
        self.assertEqual(days[3].name, "First Quarter")
        self.assertEqual(days[0].date, dt.date(2026, 11, 15))
        ill = [d.phase.illumination for d in days]
        self.assertEqual(ill, sorted(ill))                          # waxing all week

    def test_age_and_waxing(self):
        t = dt.datetime(2026, 11, 15, 0, 0, tzinfo=UTC)
        age = M.age_days(t)
        self.assertTrue(5 < age < 6.5, age)                         # new moon 9 Nov
        self.assertTrue(M.moon_phase(t).waxing)
        self.assertFalse(M.moon_phase(dt.datetime(2026, 11, 28, tzinfo=UTC)).waxing)

    def test_bright_limb_points_west_when_waxing(self):
        chi = M.moon_phase(dt.datetime(2026, 11, 15, tzinfo=UTC)).bright_limb
        self.assertTrue(200 < chi < 340, chi)                       # towards the setting sun
        chi = M.moon_phase(dt.datetime(2026, 11, 29, tzinfo=UTC)).bright_limb
        self.assertTrue(20 < chi < 160, chi)

    def test_polar_always_up_or_down(self):
        tz = M.tz_for("Europe/Oslo")
        days = M.moon_days(78.2, 15.6, tz, dt.date(2026, 11, 1), 28)    # Svalbard
        self.assertTrue(any(d.always_up or d.always_down for d in days))
        for d in days:
            if d.always_up or d.always_down:
                self.assertIsNone(d.rise)
                self.assertIsNone(d.set)

    def test_timezones(self):
        self.assertEqual(str(M.tz_for("Pacific/Auckland")), "Pacific/Auckland")
        self.assertEqual(M.tz_for("auto", 46800).utcoffset(None), dt.timedelta(hours=13))
        self.assertEqual(M.tz_for("Not/AZone", 3600).utcoffset(None), dt.timedelta(hours=1))
        self.assertIs(M.tz_for(None), dt.timezone.utc)
        with self.assertRaises(ValueError):
            M.julian_day(dt.datetime(2026, 1, 1))

    def test_upcoming_sorted_and_future(self):
        now = dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
        up = M.upcoming_phases(now, M.tz_for("Pacific/Auckland"))
        self.assertEqual({n for n, _ in up}, {"New Moon", "First Quarter", "Full Moon", "Last Quarter"})
        times = [t for _, t in up]
        self.assertEqual(times, sorted(times))
        self.assertTrue(all(t > now for t in times))

    def test_speed(self):
        t0 = time.perf_counter()
        M.moon_days(-36.85, 174.76, M.tz_for("Pacific/Auckland"), dt.date(2026, 11, 15), 7)
        el = time.perf_counter() - t0
        REPORT.append(f"7-day moon calculation: {el * 1000:.0f} ms")
        self.assertLess(el, 2.0)


class TestSkyOrientation(unittest.TestCase):
    def test_parallactic_angle_matches_reference(self):
        worst = 0.0
        for name, lat, lon, t, q_ref in REF["parallactic"]:
            q, alt, _az, _h0 = M.sky_geometry(M.julian_day(_t(t)), lat, lon)
            worst = max(worst, abs(((q - q_ref + 180) % 360) - 180))
        REPORT.append(f"parallactic angle worst vs PyEphem: {worst:.2f} deg over {len(REF['parallactic'])} samples")
        self.assertLess(worst, 2.5)

    def test_equatorial_evening_crescent_smiles(self):
        # waxing crescent low in the west after sunset near the equator: lit edge points DOWN
        for lat, lon, t in ((1.35, 103.82, dt.datetime(2026, 11, 14, 12, 30, tzinfo=UTC)),
                            (-0.18, -78.47, dt.datetime(2026, 11, 15, 0, 30, tzinfo=UTC))):
            ph = M.moon_phase(t)
            q, alt, _az, _ = M.sky_geometry(M.julian_day(t), lat, lon)
            self.assertGreater(alt, 10)
            limb_from_zenith = (ph.bright_limb - q) % 360
            self.assertLess(abs(limb_from_zenith - 180), 25, limb_from_zenith)

    def test_hemispheres_at_highest_point(self):
        t = dt.datetime(2026, 11, 15, tzinfo=UTC)
        north = M.sky_geometry(M.julian_day(M.next_transit(t, -0.13)), 51.51, -0.13)[0]
        south = M.sky_geometry(M.julian_day(M.next_transit(t, 174.76)), -36.85, 174.76)[0]
        self.assertLess(min(north, 360 - north), 1.0)          # north up from London
        self.assertLess(abs(south - 180), 1.0)                 # turned over from Auckland

    def test_sky_view_now_or_next_highest(self):
        tz = M.tz_for("Pacific/Auckland")
        up = M.sky_view(dt.datetime(2026, 11, 15, 8, 0, tzinfo=UTC), -36.85, 174.76, tz)   # 21:00 NZDT
        self.assertTrue(up.is_now and up.up)
        down = M.sky_view(dt.datetime(2026, 11, 15, 19, 0, tzinfo=UTC), -36.85, 174.76, tz)  # 08:00 NZDT
        self.assertFalse(down.is_now)
        self.assertGreater(down.when, dt.datetime(2026, 11, 15, 19, 0, tzinfo=UTC))
        self.assertTrue(down.up)
        self.assertEqual(str(down.when.tzinfo), "Pacific/Auckland")

    def test_day_view_is_that_days_transit(self):
        tz = M.tz_for("Europe/London")
        v = M.day_view(dt.date(2026, 11, 20), 51.51, -0.13, tz)
        self.assertEqual(v.when.date(), dt.date(2026, 11, 20))
        q, alt, az, _ = M.sky_geometry(M.julian_day(v.when), 51.51, -0.13)
        self.assertLess(abs(((az - 180 + 180) % 360) - 180), 1.0)   # due south at its highest


def _arr(img):
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return bytes(ptr)


class TestRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        from weatherdesk import moon_render as R
        cls.R = R

    def lit_stats(self, img):
        """(lit fraction of disc, mean x of lit pixels in -1..1, transparent corners?)"""
        n = img.width()
        b = _arr(img)
        lit = total = 0
        sx = 0.0
        for y in range(0, n, 2):
            for x in range(0, n, 2):
                p = (y * n + x) * 4
                if b[p + 3] < 250:
                    continue
                total += 1
                if b[p + 2] > 40:          # red channel (BGRA)
                    lit += 1
                    sx += (x + 0.5) / n * 2 - 1
        corner = b[3] == 0 and b[(n * n - 1) * 4 + 3] == 0
        return lit / total, (sx / lit if lit else 0.0), corner

    def test_size_transparency_and_lit_fraction(self):
        for angle in (150, 120, 90, 60, 30, 3):
            img = self.R.render_moon(200, angle, 270, False)
            self.assertEqual((img.width(), img.height()), (200, 200))
            frac, _, corners = self.lit_stats(img)
            self.assertTrue(corners)
            expected = (1 + math.cos(math.radians(angle))) / 2
            self.assertAlmostEqual(frac, expected, delta=0.09, msg=f"angle {angle}")

    def test_orientation_by_hemisphere(self):
        # waxing: bright limb towards west (chi ~270) -> lit on the right in the north,
        # on the left when viewed from the southern hemisphere.
        _, mx_n, _ = self.lit_stats(self.R.render_moon(160, 110, 270, False))
        _, mx_s, _ = self.lit_stats(self.R.render_moon(160, 110, 270, True))
        self.assertGreater(mx_n, 0.3)
        self.assertLess(mx_s, -0.3)
        _, mx_wane, _ = self.lit_stats(self.R.render_moon(160, 110, 90, False))
        self.assertLess(mx_wane, -0.3)

    def test_any_rotation_turns_the_picture_clockwise(self):
        def lit_centre(img):
            n = img.width(); b = _arr(img); sx = sy = c = 0
            for y in range(0, n, 2):
                for x in range(0, n, 2):
                    p = (y * n + x) * 4
                    if b[p + 3] > 250 and b[p + 2] > 40:
                        sx += x; sy += y; c += 1
            return sx / c / n * 2 - 1, sy / c / n * 2 - 1      # y grows downwards
        x0, y0 = lit_centre(self.R.render_moon(140, 110, 270, rotation=0))
        x90, y90 = lit_centre(self.R.render_moon(140, 110, 270, rotation=90))
        x45, y45 = lit_centre(self.R.render_moon(140, 110, 270, rotation=45))
        self.assertGreater(x0, 0.4); self.assertLess(abs(y0), 0.1)        # lit right
        self.assertGreater(y90, 0.4); self.assertLess(abs(x90), 0.1)      # lit bottom
        self.assertGreater(x45, 0.25); self.assertGreater(y45, 0.25)      # lit lower right
        self.assertEqual(self.R.render_moon(140, 110, 270, rotation=45).width(), 140)

    def test_southern_flag_equals_180_rotation(self):
        a = _arr(self.R.render_moon(100, 70, 250, True))
        b = _arr(self.R.render_moon(100, 70, 250, rotation=180))
        self.assertEqual(a, b)

    def test_new_moon_shows_only_earthshine(self):
        frac, _, _ = self.lit_stats(self.R.render_moon(160, 179.5, 270, False))
        self.assertLess(frac, 0.01)

    @unittest.skipUnless(__import__("importlib").util.find_spec("numpy"), "numpy not installed")
    def test_numpy_and_python_paths_agree(self):
        for angle, chi, south in ((62, 262, False), (4, 262, True), (150, 95, False)):
            a = _arr(self.R.render_moon(120, angle, chi, south, use_numpy=True))
            b = _arr(self.R.render_moon(120, angle, chi, south, use_numpy=False))
            self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 6)

    def test_cache_returns_same_image(self):
        a = self.R.render_moon(96, 80, 250, False)
        b = self.R.render_moon(96, 80.04, 250.2, False)
        self.assertIs(a, b)
        self.assertLessEqual(len(self.R._img_cache), self.R._IMG_CACHE_MAX)

    def test_missing_texture_raises_clear_error(self):
        with mock.patch.object(self.R, "ALBEDO_FILE", Path("/nonexistent/moon.jpg")), \
                mock.patch.dict(self.R._tex_cache, clear=True):
            with self.assertRaises(self.R.MoonTextureError):
                self.R.render_moon(77, 33, 250, False)

    def test_size_limits(self):
        self.assertEqual(self.R.render_moon(1, 90, 270).width(), 8)
        self.assertEqual(self.R.render_moon(99999, 90, 270, use_numpy=True).width(), self.R.MAX_SIZE) \
            if self.R.has_numpy() else None

    def test_meta_defaults_on_bad_json(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            bad = tmp / "m.json"
            bad.write_text("{nope")
            with mock.patch.object(self.R, "META_FILE", bad), mock.patch.object(self.R, "_meta_cache", None):
                self.assertEqual(self.R.texture_meta()["source"], "procedural")
        finally:
            shutil.rmtree(tmp)

    def test_render_speed(self):
        t0 = time.perf_counter()
        self.R.render_moon(300, 71.3, 255.5, True)
        el = time.perf_counter() - t0
        REPORT.append(f"render 300 px ({'numpy' if self.R.has_numpy() else 'pure Python'}): {el * 1000:.0f} ms")
        self.assertLess(el, 5.0)


def _have(mod):
    import importlib.util
    return importlib.util.find_spec(mod) is not None


@unittest.skipUnless(_have("numpy") and _have("tifffile"), "converter needs numpy + tifffile (build-time only)")
class TestNasaConverter(unittest.TestCase):
    def test_landmarks_land_in_the_right_place(self):
        import numpy as np
        import tifffile
        import importlib.util
        qapp()
        tmp = Path(tempfile.mkdtemp())
        try:
            W, H = 1024, 512
            lon = np.linspace(-180, 180, W, endpoint=False) + 180 / W
            lat = np.linspace(90, -90, H, endpoint=False) - 90 / H
            LON, LAT = np.meshgrid(lon, lat)

            def disk(la, lo, r):
                d = np.degrees(np.arccos(np.clip(
                    np.sin(np.radians(LAT)) * math.sin(math.radians(la)) +
                    np.cos(np.radians(LAT)) * math.cos(math.radians(la)) * np.cos(np.radians(LON - lo)), -1, 1)))
                return d < r
            col = np.full((H, W, 3), 0.6, np.float32)
            col[disk(17, 59, 9)] = 0.15
            col[disk(-43, -11, 5)] = 1.0
            col[disk(0, 120, 12)] = 0.0
            tifffile.imwrite(tmp / "c.tif", (col * 65535).astype(np.uint16), photometric="rgb")
            tifffile.imwrite(tmp / "h.tif", np.full((360, 720), 20000, np.uint16))
            spec = importlib.util.spec_from_file_location("conv", ROOT / "tools" / "make_moon_texture_nasa.py")
            conv = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(conv)
            self.assertEqual(conv.main([str(tmp / "c.tif"), str(tmp / "h.tif"), "--size", "256",
                                        "--out", str(tmp / "out")]), 0)
            from PyQt6.QtGui import QImage
            img = QImage(str(tmp / "out" / "moon_albedo.jpg"))

            def at(la, lo):
                x = math.cos(math.radians(la)) * math.sin(math.radians(lo))
                y = math.sin(math.radians(la))
                return img.pixelColor(int((x + 1) / 2 * 256), int((1 - y) / 2 * 256)).red()
            self.assertLess(at(17, 59), 60)          # Crisium-like: right of centre, north
            self.assertGreater(at(-43, -11), 230)    # Tycho-like: south, slightly west
            self.assertTrue(140 < at(20, -30) < 170)
            meta = json.loads((tmp / "out" / "moon_textures.json").read_text())
            self.assertEqual(meta["source"], "nasa-cgi-moon-kit")
            self.assertIn("NASA", meta["credit"])
        finally:
            shutil.rmtree(tmp)


class TestMoonTab(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.wins = []

    def tearDown(self):
        for w in self.wins:
            w._quitting = True
            w.close()
            w.deleteLater()
        super().tearDown()

    def make(self):
        from weatherdesk.main_window import MainWindow
        w = MainWindow(client=self.client(), enable_tray=False)
        w.show()
        self.wins.append(w)
        return w

    def test_moon_tab_shows_location_data(self):
        w = self.make()
        self.assertIn("Select a location", w.moon_panel.illum_label.text())
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        rep = w.moon_panel.report
        self.assertEqual(rep.location.name, "Auckland")
        self.assertTrue(rep.southern)
        self.assertEqual(str(rep.now.tzinfo), "Pacific/Auckland")
        self.assertEqual(w.moon_panel.name_label.text(), rep.phase.name)
        expected = M.moon_days(rep.location.latitude, rep.location.longitude, rep.now.tzinfo,
                               rep.now.date(), 1)[0]
        self.assertEqual(w.moon_panel.facts["rise"].text(),
                         expected.rise.strftime("%H:%M") if expected.rise else "no moonrise")
        self.assertEqual(len([c for c in w.moon_panel.day_cells if c["img"].image is not None]), 7)
        self.assertEqual(w.moon_panel.day_cells[0]["day"].text(), "Today")
        self.assertTrue(w.moon_panel.save_btn.isEnabled())
        self.assertEqual(rep.big.width(), 560)

    def test_fact_rows_never_overlap_and_nasa_credit_shown(self):
        w = self.make()
        w.resize(1100, 820)
        w.add_location(self.place(0))
        w.tabs.setCurrentIndex(1)
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        from PyQt6.QtTest import QTest
        QTest.qWait(100)
        f = w.moon_panel.facts
        rows = [f[k] for k in ("rise", "set", "sky", "dist", "tz")]
        for size in ((1100, 820), (800, 560), (1400, 1000)):      # incl. the smallest window allowed
            w.resize(*size)
            QTest.qWait(80)
            for a, b in zip(rows, rows[1:]):
                self.assertLess(a.geometry().bottom(), b.geometry().top(), f"rows overlap at {size}")
                self.assertGreaterEqual(a.height(), a.fontMetrics().height(), f"row squashed at {size}")
            days = w.moon_panel.day_cells
            self.assertLess(days[0]["rise"].geometry().bottom(), days[0]["set"].geometry().top())
        from weatherdesk.moon_render import texture_meta
        if texture_meta()["source"] == "nasa-cgi-moon-kit":
            self.assertIn("NASA", w.moon_panel.credit_label.text())
            self.assertIn("NASA", w.about_html())

    def test_orientation_shown_and_differs_by_location(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        rep = w.moon_panel.report
        self.assertIsNotNone(rep.view)
        self.assertEqual(len(rep.day_views), 7)
        txt = w.moon_panel.facts["sky"].text()
        # the three forms the app writes, depending on where the Moon is when the test runs
        # (1.8.1: the middle form was missing here, so the test failed whenever the Moon was
        # below the horizon at run time - a test bug, not an app bug)
        self.assertRegex(txt, r"^(Up now · \d+° high in the \w+"
                              r"|Below horizon · shown at its highest, \w{3} \d\d:\d\d"
                              r"|Below the horizon all day · shown at its highest)$")
        from weatherdesk.moon_panel import build_report
        from weatherdesk.models import Location
        t = dt.datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
        rots = {n: build_report(Location(n, la, lo, timezone=tz), tz, now=t, big_px=40, small_px=16).view.rotation
                for n, la, lo, tz in (("Auckland", -36.85, 174.76, "Pacific/Auckland"),
                                      ("Singapore", 1.35, 103.82, "Asia/Singapore"),
                                      ("London", 51.51, -0.13, "Europe/London"))}
        self.assertGreater(abs(((rots["Auckland"] - rots["Singapore"] + 180) % 360) - 180), 30)
        self.assertGreater(abs(((rots["Auckland"] - rots["London"] + 180) % 360) - 180), 30)

    def test_switching_location_recomputes(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        london = PLACES[0].copy()
        london.update(name="London", latitude=51.5072, longitude=-0.1276, country="United Kingdom",
                      admin1="England", timezone="Europe/London")
        from weatherdesk.models import Location
        w.add_location(Location.from_dict(london))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None and
                                   w.moon_panel.report.location.name == "London", 30))
        self.assertFalse(w.moon_panel.report.southern)
        self.assertEqual(str(w.moon_panel.report.now.tzinfo), "Europe/London")

    def test_no_recompute_within_ten_minutes(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        tok = w._moon_token
        w.request_moon()
        w.render()
        self.assertEqual(w._moon_token, tok)
        w.request_moon(force=True)
        self.assertEqual(w._moon_token, tok + 1)

    def test_save_high_res_image(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        out = self.tmp / "moon"            # .png added automatically
        t0 = time.monotonic()
        w.save_moon_image(str(out))
        self.assertTrue(wait_until(lambda: getattr(w, "last_moon_save", None) is not None, 120))
        REPORT.append(f"save 2048 px PNG: {time.monotonic() - t0:.1f}s")
        path, err = w.last_moon_save
        self.assertEqual(err, "")
        from PyQt6.QtGui import QImage
        img = QImage(path)
        self.assertEqual((img.width(), img.height()), (2048, 2048))
        self.assertTrue(path.endswith(".png"))
        self.assertIn("Saved moon image", w.statusBar().currentMessage())

    def test_save_failure_reported(self):
        w = self.make()
        w.add_location(self.place(0))
        self.assertTrue(wait_until(lambda: w.moon_panel.report is not None, 30))
        w.save_moon_image("/nonexistent-dir/x.png")
        self.assertTrue(wait_until(lambda: getattr(w, "last_moon_save", None) is not None, 120))
        self.assertNotEqual(w.last_moon_save[1], "")
        self.assertIn("Could not save", w.statusBar().currentMessage())

    def test_night_scene_hides_moon_below_horizon(self):
        from weatherdesk import scene as sc
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtCore import QRectF
        s = sc.WeatherScene()
        s.resize(400, 200)
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=0, moon_phase_angle=60, moon_limb=270,
                                       moon_up=False))
        img = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        with mock.patch("weatherdesk.moon_render.render_moon") as rm:
            s.paint_scene(p, QRectF(0, 0, 400, 200))
        p.end()
        self.assertFalse(rm.called)

    def test_night_scene_uses_rendered_moon(self):
        from weatherdesk import scene as sc
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtCore import QRectF
        s = sc.WeatherScene()
        s.resize(400, 200)
        s.set_conditions(sc.Conditions(sc.CLEAR, 0, daylight=0, moon_phase_angle=60, moon_limb=270,
                                       moon_rotation=121.0, moon_up=True, moon_altitude=47))
        img = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        with mock.patch("weatherdesk.moon_render.render_moon", wraps=__import__(
                "weatherdesk.moon_render", fromlist=["x"]).render_moon) as rm:
            s.paint_scene(p, QRectF(0, 0, 400, 200))
        p.end()
        self.assertTrue(rm.called)
        self.assertEqual(rm.call_args.kwargs.get("rotation"), 121.0)


def tearDownModule():
    print("\n--- moon results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
