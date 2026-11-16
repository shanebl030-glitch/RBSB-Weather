"""Live cloud tests: download, conditional re-checks, caching, bad downloads,
compositing over day and night, and the Live clouds switch in both Earth tabs."""

from __future__ import annotations

import datetime as dt
import json
import socket
import time
import unittest

from helpers import PLACES, TempEnvTestCase, qapp, wait_until

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest

from weatherdesk import clouds as C
from weatherdesk import earth as E

UTC = dt.timezone.utc
REPORT: list[str] = []
# cloud block: longitude 0..30 E, latitude 0..20 N (test spot: 15E, 10N)
SPOT = (10.0, 15.0)
DAY_T = dt.datetime(2026, 11, 15, 10, 45, tzinfo=UTC)     # Sun nearly overhead at 15E
NIGHT_T = dt.datetime(2026, 11, 15, 22, 45, tzinfo=UTC)


def cloud_jpeg(w=512, h=256, block=True, haze=0) -> bytes:
    qapp()
    img = QImage(w, h, QImage.Format.Format_Grayscale8)
    img.fill(QColor(haze, haze, haze))
    if block:
        p = QPainter(img)
        x0, x1 = int((0 + 180) / 360 * w), int((30 + 180) / 360 * w)
        y0, y1 = int((90 - 20) / 180 * h), int((90 - 0) / 180 * h)
        p.fillRect(QRect(x0, y0, x1 - x0, y1 - y0), QColor(255, 255, 255))
        p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPG", 92)
    buf.close()
    return bytes(ba)


def pixel_at(img: QImage, lat: float, lon: float) -> QColor:
    x, y = E.to_map_xy(lat, lon, img.width(), img.height())
    return img.pixelColor(int(x), int(y))


class TestDownload(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        self.store = C.CloudStore(self.tmp / "cache")
        self.server.cloud_body = cloud_jpeg()

    def test_download_then_not_modified_then_new(self):
        self.assertTrue(self.store.due())
        t = time.perf_counter()
        self.assertEqual(C.update(self.store, self.server.cloud_url), "updated")
        REPORT.append(f"cloud map download + check (local): {(time.perf_counter() - t) * 1000:.0f} ms")
        self.assertTrue(self.store.image_path.is_file())
        m = self.store.meta()
        self.assertEqual(m["last_modified"], self.server.cloud_last_modified)
        self.assertEqual(self.store.image_time(), dt.datetime(2026, 11, 15, 0, 0, tzinfo=UTC))
        self.assertFalse(self.store.due())
        self.assertIsNotNone(self.store.load())
        before = self.store.image_path.stat().st_mtime_ns
        # unchanged on the server: a conditional request, nothing re-downloaded
        self.assertEqual(C.update(self.store, self.server.cloud_url), "unchanged")
        self.assertEqual(self.server.cloud_headers[-1].get("If-Modified-Since"), self.server.cloud_last_modified)
        self.assertEqual(self.store.image_path.stat().st_mtime_ns, before)
        # a newer map
        self.server.cloud_last_modified = "Sun, 15 Nov 2026 03:00:00 GMT"
        self.assertEqual(C.update(self.store, self.server.cloud_url), "updated")
        self.assertEqual(self.store.image_time().hour, 3)
        self.assertIn("WeatherDesk/", self.server.cloud_headers[-1].get("User-Agent", ""))

    def test_due_schedule(self):
        C.update(self.store, self.server.cloud_url)
        now = time.time()
        self.assertFalse(self.store.due(now + C.CHECK_EVERY_S - 5))
        self.assertTrue(self.store.due(now + C.CHECK_EVERY_S + 5))

    def test_bad_downloads_keep_the_cached_map(self):
        C.update(self.store, self.server.cloud_url)
        good = self.store.image_path.read_bytes()
        self.server.cloud_last_modified = "Sun, 15 Nov 2026 06:00:00 GMT"
        for mode, words in (("garbage", "not a readable image"), ("http404", "HTTP 404"),
                            ("huge", "unexpectedly large")):
            self.server.cloud_mode = mode
            t = time.perf_counter()
            with self.assertRaises(C.CloudError) as cm:
                C.update(self.store, self.server.cloud_url)
            self.assertIn(words, str(cm.exception))
            self.assertLess(time.perf_counter() - t, 5)
            self.assertEqual(self.store.image_path.read_bytes(), good, mode)
            self.assertIsNotNone(self.store.load())
        # after a failure, wait 15 minutes before trying again
        now = time.time()
        self.assertFalse(self.store.due(now + 60))
        self.assertTrue(self.store.due(now + C.RETRY_AFTER_FAIL_S + 5))
        self.assertEqual(self.store.image_time().hour, 0)    # still the cached map's time

    def test_wrong_shape_rejected(self):
        self.server.cloud_body = cloud_jpeg(400, 400)
        with self.assertRaises(C.CloudError) as cm:
            C.update(self.store, self.server.cloud_url)
        self.assertIn("unexpected size", str(cm.exception))
        self.assertFalse(self.store.image_path.exists())

    def test_unreachable_fails_quickly_and_retries_once(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                            # nothing listening
        t = time.perf_counter()
        with self.assertRaises(C.CloudError):
            C.update(self.store, f"http://127.0.0.1:{port}/clouds.jpg", timeout=2)
        self.assertLess(time.perf_counter() - t, 5)
        self.assertTrue(self.store.meta().get("failed"))

    def test_timeout_bounded(self):
        self.server.cloud_mode = "slow"
        t = time.perf_counter()
        with self.assertRaises(C.CloudError):
            C.update(self.store, self.server.cloud_url, timeout=0.5)
        took = time.perf_counter() - t
        REPORT.append(f"stalled cloud server: gave up after {took:.1f} s (timeout 0.5 s, one retry)")
        self.assertLess(took, 3)

    def test_corrupt_cache_and_meta_ignored(self):
        self.store.dir.mkdir(parents=True, exist_ok=True)
        self.store.image_path.write_bytes(b"\xff\xd8 broken")
        self.store.meta_path.write_text("{oops")
        self.assertIsNone(self.store.load())
        self.assertEqual(self.store.meta(), {})
        self.assertTrue(self.store.due())
        self.assertEqual(C.update(self.store, self.server.cloud_url), "updated")
        self.assertIsNotNone(self.store.load())


class TestCompositing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qapp()
        img = QImage()
        img.loadFromData(cloud_jpeg())
        cls.clouds = img

    def test_alpha_curve(self):
        img = QImage()
        img.loadFromData(cloud_jpeg(haze=12))
        a = C.cloud_alpha(img, 512, 256)
        self.assertEqual(a.format(), QImage.Format.Format_Alpha8)
        self.assertLess(a.pixelColor(20, 20).alpha(), 3)            # thin haze trimmed
        x, y = E.to_map_xy(10, 15, 512, 256)
        self.assertGreater(a.pixelColor(int(x), int(y)).alpha(), 250)   # thick cloud opaque

    def test_clouds_white_by_day(self):
        t = time.perf_counter()
        with_c = E.compose_day_night(DAY_T, clouds=self.clouds)
        took = (time.perf_counter() - t) * 1000
        REPORT.append(f"day/night + clouds composite 2576x1288: {took:.0f} ms")
        without = E.compose_day_night(DAY_T)
        a, b = pixel_at(with_c, *SPOT), pixel_at(without, *SPOT)
        self.assertGreater(a.lightness(), 220)
        self.assertGreater(a.lightness(), b.lightness() + 40)
        # outside the cloud the map is unchanged
        self.assertEqual(pixel_at(with_c, -30, 60).rgb(), pixel_at(without, -30, 60).rgb())

    def test_clouds_hide_city_lights_at_night(self):
        lagos = (6.5, 3.4)                         # bright city lights, inside the cloud block
        with_c = E.compose_day_night(NIGHT_T, clouds=self.clouds)
        without = E.compose_day_night(NIGHT_T)

        def contrast(img):                         # brightest light minus darkest ground nearby
            x, y = E.to_map_xy(*lagos, img.width(), img.height())
            v = [img.pixelColor(int(x) + i, int(y) + j).lightness()
                 for i in range(-20, 20) for j in range(-15, 15)]
            return max(v) - min(v)
        a, b = contrast(with_c), contrast(without)
        REPORT.append(f"city-light contrast at Lagos at night: {b} clear -> {a} under cloud")
        self.assertGreater(b, 60)
        self.assertLess(a, b * 0.25)
        self.assertGreater(pixel_at(with_c, *SPOT).lightness(), 0)    # faint cloud still visible

    def test_note(self):
        store = C.CloudStore("/nonexistent/weatherdesk-test")
        self.assertIn("unavailable", C.note(store, None, "HTTP 404"))
        self.assertIn("once they've downloaded", C.note(store, None, ""))


class TestEarthTabsClouds(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        self.app = qapp()
        self.server.cloud_body = cloud_jpeg()
        from weatherdesk.main_window import MainWindow
        self.w = MainWindow(client=self.client(), enable_tray=False)
        self.w.resize(1100, 820)
        self.w.show()
        from weatherdesk.models import Location
        self.w.add_location(Location.from_dict(PLACES[0]))
        self.assertTrue(wait_until(lambda: not self.w._pending))

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        QTest.qWait(30)
        super().tearDown()

    def open_flat(self):
        self.w.tabs.setCurrentWidget(self.w.earth_panel)
        self.assertTrue(wait_until(lambda: self.w.earth_panel.map.image is not None, 20))

    def test_clouds_on_by_default_and_shown(self):
        self.assertTrue(self.w.earth_panel.clouds_box.isChecked())
        self.assertTrue(self.w.globe_panel.clouds_box.isChecked())
        self.open_flat()
        self.assertIn("Clouds: satellite map from", self.w.earth_panel.info.text())
        self.assertEqual(self.server.count("/images/2048x1024/clouds.jpg"), 1)
        self.assertTrue(self.w.cloud_store.image_path.is_file())
        self.assertIn("EUMETSAT", self.w.earth_panel.credit.text())
        self.assertIn("EUMETSAT", self.w.globe_panel.credit.text())
        self.assertIn("matteason/live-cloud-maps", self.w.about_html())

    def test_not_downloaded_again_within_the_hour(self):
        self.open_flat()
        for _ in range(3):
            self.w.request_earth()
            tok = self.w._earth_token
            self.assertTrue(wait_until(lambda: self.w.earth_panel.info.text().startswith("Day and night")
                                       and self.w._earth_token == tok, 10))
            QTest.qWait(300)
        self.assertEqual(self.server.count("/images/2048x1024/clouds.jpg"), 1)

    def test_switch_shared_saved_and_redraws(self):
        self.open_flat()
        img_on = self.w.earth_panel.map.image
        self.w.tabs.setCurrentWidget(self.w.globe_panel)
        tok = self.w._earth_token
        self.w.globe_panel.clouds_box.setChecked(False)
        self.assertFalse(self.w.earth_panel.clouds_box.isChecked())       # both tabs follow
        self.assertFalse(self.w.settings.earth_clouds)
        saved = json.loads(self.w.store.path.read_text())
        self.assertIs(saved["earth_clouds"], False)
        self.assertTrue(wait_until(lambda: self.w._earth_token > tok and
                                   "Clouds" not in self.w.globe_panel.info.text() and
                                   self.w.earth_panel.map.image is not img_on, 10))
        self.assertNotIn("Clouds", self.w.earth_panel.info.text())
        n = self.server.count("/images/2048x1024/clouds.jpg")
        self.w.globe_panel.clouds_box.setChecked(True)
        self.assertTrue(wait_until(lambda: "Clouds: satellite map" in self.w.globe_panel.info.text(), 10))
        self.assertEqual(self.server.count("/images/2048x1024/clouds.jpg"), n)   # cached, no download

    def test_offline_without_cache_still_draws_earth(self):
        self.server.cloud_mode = "http404"
        self.open_flat()
        self.assertIn("Live clouds are unavailable", self.w.earth_panel.info.text())
        self.assertIsNotNone(self.w.earth_panel.map.image)

    def test_close_during_slow_cloud_download(self):
        self.server.cloud_mode = "slow"
        self.w.tabs.setCurrentWidget(self.w.earth_panel)
        QTest.qWait(200)                                   # download in flight
        t = time.perf_counter()
        self.w._quitting = True
        self.w.close()
        took = time.perf_counter() - t
        REPORT.append(f"window closed during a stalled cloud download in {took * 1000:.0f} ms")
        self.assertLess(took, 1.0)
        QTest.qWait(50)

    def test_setting_validation(self):
        from weatherdesk.storage import Settings
        self.assertTrue(Settings.from_dict({"earth_clouds": "yes"}).earth_clouds)
        self.assertFalse(Settings.from_dict({"earth_clouds": False}).earth_clouds)


def tearDownModule():
    print("\n--- clouds results ---")
    for line in REPORT:
        print("  " + line)


if __name__ == "__main__":
    unittest.main()
