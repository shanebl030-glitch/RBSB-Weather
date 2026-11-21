#!/usr/bin/env python3
"""Take the README screenshots (docs/media/screenshots/*.png) from the real app.

    QT_QPA_PLATFORM=offscreen python3 tools/make_screenshots.py

The app runs exactly as usual, in a throw-away profile, but its weather comes
from a small local server that sends believable sample forecasts in
Open-Meteo's format, dated today, for Auckland, London, Tokyo and New York (the
weather services can't be reached from the build machine). The sky, Sun, Moon
and day/night are the real ones for the moment the screenshots are taken. The
Wind tab uses real NOAA GFS sample data from tests/data. Nothing is sent
anywhere.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import http.server
import json
import math
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "media" / "screenshots"
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="rbsb-shots-"))
os.environ.update(RBSB_WEATHER_CONFIG_DIR=str(TMP / "config"), RBSB_WEATHER_CACHE_DIR=str(TMP / "cache"),
                  RBSB_WEATHER_KEYRING="0", RBSB_WEATHER_UPDATE_URL="http://127.0.0.1:9/none",
                  RBSB_WEATHER_WIND_NOMADS="http://127.0.0.1:9/none", RBSB_WEATHER_WIND_AWS="http://127.0.0.1:9/none",
                  QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
os.environ.pop("XDG_RUNTIME_DIR", None)

# name, lat, lon, country, region, timezone, base temperature, daily range, weather now, later today, next days
CITIES = [
    ("Auckland", -36.84853, 174.76349, "New Zealand", "Auckland", "Pacific/Auckland", 15.5, 7, 2, (2, 80, 80, 3),
     [2, 80, 3, 1, 0, 61, 2]),
    ("London", 51.50853, -0.12574, "United Kingdom", "England", "Europe/London", 6.0, 5, 1, (1, 2, 3, 3),
     [3, 61, 63, 3, 2, 1, 61]),
    ("Tokyo", 35.6895, 139.69171, "Japan", "Tokyo", "Asia/Tokyo", 11.0, 6, 63, (61, 3, 2, 1),
     [63, 3, 1, 0, 2, 80, 3]),
    ("New York", 40.71427, -74.00597, "United States", "New York", "America/New_York", -3.0, 5, 73, (71, 3, 3, 2),
     [73, 3, 2, 0, 1, 71, 3]),
]


def sample(lat: float, lon: float) -> dict:
    """A believable Open-Meteo forecast for one of CITIES, dated today in its time zone."""
    from rbsb_weather import sun
    c = min(CITIES, key=lambda x: (x[1] - lat) ** 2 + (x[2] - lon) ** 2)
    name, _, _, _, _, tzname, base, rng, code_now, later, days = c
    tz = ZoneInfo(tzname)
    now = dt.datetime.now(tz)
    day0 = now.date()
    hours, temps, pops, prs, codes = [], [], [], [], []
    for h in range(7 * 24):
        t = dt.datetime.combine(day0, dt.time()) + dt.timedelta(hours=h)
        d, hr = h // 24, t.hour
        temp = base - d * 0.4 + rng * math.sin((hr - 9) / 24 * 2 * math.pi) + 1.5 * math.sin(d * 1.3)
        if d == 0:
            k = 0 if t.hour <= now.hour else min(3, (t.hour - now.hour) // 3)
            code = code_now if k == 0 else later[k]
        else:
            dc = days[d % 7]
            code = dc if 9 <= hr <= 18 else (dc if dc in (0, 1, 2, 3) else 3)
        wet = code >= 51
        hours.append(t.strftime("%Y-%m-%dT%H:%M"))
        temps.append(round(temp, 1))
        pops.append(min(90, 40 + 9 * (hr % 5)) if wet else (15 if code == 3 else 0))
        prs.append(round(0.1 + 0.2 * (hr % 3), 1) if wet else 0.0)
        codes.append(code)
    daily = {k: [] for k in ("time", "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                              "precipitation_probability_max", "wind_speed_10m_max", "sunrise", "sunset", "uv_index_max")}
    for d in range(7):
        date = day0 + dt.timedelta(days=d)
        block = slice(d * 24, d * 24 + 24)
        rise, sset = sun.sun_rise_set(date, lat, lon, tz)
        daily["time"].append(date.isoformat())
        daily["weather_code"].append(max(codes[block]))          # Open-Meteo: the most severe of the day
        daily["temperature_2m_max"].append(max(temps[block]))
        daily["temperature_2m_min"].append(min(temps[block]))
        daily["precipitation_sum"].append(round(sum(prs[block]), 1))
        daily["precipitation_probability_max"].append(max(pops[block]))
        daily["wind_speed_10m_max"].append(18 + (d * 7) % 20)
        daily["sunrise"].append(rise.strftime("%Y-%m-%dT%H:%M") if rise else None)
        daily["sunset"].append(sset.strftime("%Y-%m-%dT%H:%M") if sset else None)
        daily["uv_index_max"].append(round(max(1.0, 7.5 - abs(lat) / 12 - d * 0.3), 1))
    i = now.hour
    return {"latitude": lat, "longitude": lon, "timezone": tzname,
            "utc_offset_seconds": int(now.utcoffset().total_seconds()),
            "current": {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": temps[i],
                        "relative_humidity_2m": 88 if codes[i] >= 51 else 64,
                        "apparent_temperature": round(temps[i] - 2.2, 1), "is_day": int(sun.is_daytime(now, lat, lon)),
                        "precipitation": prs[i], "weather_code": code_now,
                        "cloud_cover": {0: 4, 1: 20, 2: 48}.get(code_now, 92), "pressure_msl": 1013.6,
                        "wind_speed_10m": 21.0, "wind_direction_10m": 225, "wind_gusts_10m": 38.0},
            "hourly": {"time": hours, "temperature_2m": temps, "precipitation_probability": pops,
                       "precipitation": prs, "weather_code": codes},
            "daily": daily}


class Server:
    def __init__(self):
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/alerts-"):
                    return self._alerts()
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                body = json.dumps(sample(float(q.get("latitude", 0)), float(q.get("longitude", 0)))).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _alerts(self):
                """Sample warnings (2.4) from tests/data/alerts, timed around now."""
                name = {"rss": "metservice_rss.xml", "rain-auckland.xml": "cap_rain_auckland.xml",
                        "wind-wellington.xml": "cap_wind_wellington.xml", "test.xml": "cap_test.xml",
                        "united-kingdom": "meteoalarm_uk.xml",
                        "alerts-nws": "nws_point.json"}.get(urllib.parse.urlsplit(self.path).path.rsplit("/", 1)[-1])
                if name is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
                body = (ROOT / "tests" / "data" / "alerts" / name).read_text().replace(
                    "{BASE}", f"http://127.0.0.1:{self.server.server_address[1]}/alerts-metservice").replace(
                    "{ONSET}", (now - dt.timedelta(hours=1)).isoformat()).replace(
                    "{EXPIRES}", (now + dt.timedelta(hours=32)).isoformat()).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/forecast"


def main() -> int:
    from PyQt6.QtCore import QPoint, QRect, Qt
    from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    app = QApplication(["rbsb-weather"])
    app.setDesktopFileName("rbsb-weather")
    from rbsb_weather import wind
    from rbsb_weather.api import OpenMeteoClient
    from rbsb_weather.main_window import MainWindow
    from rbsb_weather.models import Location
    OUT.mkdir(parents=True, exist_ok=True)
    srv = Server()
    store = wind.WindStore(TMP / "cache" / "wind")
    # the sample file is a 120-hour GFS forecast; dated so that it is valid about now
    run = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=120)
    store.save((ROOT / "tests" / "data" / "gfs_2p5_layers.grib2").read_bytes(), run, 120, "sample")

    def wait(ms):
        QTest.qWait(ms)

    from rbsb_weather import alerts as A
    base = srv.url.rsplit("/v1/", 1)[0]
    ac = A.AlertClient(metservice_url=f"{base}/alerts-metservice/cap/rss", nws_url=f"{base}/alerts-nws",
                       metno_url=f"{base}/alerts-metno", meteoalarm_url=base + "/alerts-meteoalarm/{slug}")
    w = MainWindow(client=OpenMeteoClient(forecast_url=srv.url, geocode_url=srv.url), enable_tray=False,
                   alert_client=ac)
    w.set_earth_clouds(False)                           # the Earth tabs stay offline
    # warnings (2.4) have their own screenshots at the end; the others are taken without them
    w.apply_alert_settings({"alerts_official": False, "alerts_own": False})
    w.resize(1240, 860)
    w.show()
    keys = {}
    for name, lat, lon, country, region, tzname, *_ in CITIES:
        loc = Location(name, lat, lon, country, region, tzname)
        w.add_location(loc)
        keys[name] = loc.key
    end = time.time() + 20
    while time.time() < end and len(w.forecasts) < len(CITIES):
        wait(200)

    def select(name):
        for i in range(w.loc_list.count()):
            if w.loc_list.item(i).data(Qt.ItemDataRole.UserRole) == keys[name] or name in w.loc_list.item(i).text():
                w.loc_list.setCurrentRow(i)
                break
        wait(1500)

    def shot(widget, name, settle=1200):
        wait(settle)
        widget.grab().save(str(OUT / name))
        print("saved", name)

    taken = []
    for city, fname in (("Auckland", "01-forecast-auckland.png"), ("London", "02-night-london.png"),
                        ("Tokyo", "03-rain-tokyo.png"), ("New York", "04-snow-new-york.png")):
        select(city)
        w.tabs.setCurrentIndex(0)
        shot(w, fname, 2500)
        taken.append(fname)

    select("Auckland")                                  # forecast playback, a few hours ahead
    bar = w.playback
    if hasattr(bar, "slider"):
        bar.slider.setValue(min(bar.slider.maximum(), bar.slider.minimum() + 5 * 4))
        shot(w, "05-playback.png", 2500)
        bar.go_now() if hasattr(bar, "go_now") else None

    for tab, fname in ((w.moon_scroll, "06-moon.png"), (w.earth_panel, "07-earth-flat.png"),
                       (w.globe_panel, "08-earth-globe.png")):
        w.tabs.setCurrentWidget(tab)
        shot(w, fname, 3500)

    w.tabs.setCurrentWidget(w.wind_panel)
    wait(800)
    v = w.wind_panel.view
    v.set_zoom(1.3, animate=False)
    v.set_center(-30, 160)
    for layer, fname in (("wind", "09-wind.png"), ("temp", "10-temperature.png"), ("rain", "11-rain.png")):
        w.wind_panel.layer_buttons[layer].click()
        shot(w, fname, 3500)

    w.tabs.setCurrentIndex(0)
    w.set_desktop_widget(True)
    dw = w.desktop_widget
    for size in ("medium",):
        dw.set_size_name(size)
        wait(2500)
        img = QImage(dw.width() + 60, dw.height() + 60, QImage.Format.Format_ARGB32_Premultiplied)
        p = QPainter(img)
        g = QLinearGradient(0, 0, img.width(), img.height())
        g.setColorAt(0, QColor(46, 62, 92))
        g.setColorAt(1, QColor(22, 28, 44))
        p.fillRect(img.rect(), g)
        dw.render(p, QPoint(30, 30))
        p.end()
        img.save(str(OUT / "12-desktop-widget.png"))
        print("saved 12-desktop-widget.png")
    w.set_desktop_widget(False)

    w.show_providers()
    wait(1500)
    dlg = w._providers_dialog
    if dlg is not None:
        shot(dlg, "13-weather-providers.png", 800)
        dlg.close()

    from rbsb_weather.updates import UpdateInfo
    from rbsb_weather import __version__
    major, minor, patch = (int(x) for x in __version__.split("."))
    nxt = f"{major}.{minor}.{patch + 1}"
    info = UpdateInfo(nxt, f"v{nxt}", f"RBSB-Weather {nxt}",
                      "## What's new\n\n- A sample of the release notes that appear here.\n"
                      "- The update is downloaded, checked against its checksum and opened in your package installer.",
                      "https://github.com/shanebl030-glitch/RBSB-Weather/releases", "", f"rbsb-weather_{nxt}_all.deb",
                      "https://github.com/x.deb", 2_400_000, "https://github.com/s")
    w._update_info = info
    w._announce_update(info, popup=False)
    dlg = w._open_update_dialog()
    dlg.show_available(info)
    shot(dlg, "14-update-available.png", 800)
    dlg.close()
    w.update_button.setVisible(False)

    # ---- weather warnings (2.4), with sample warnings
    w.apply_alert_settings({"alerts_official": True, "alerts_own": True})
    end = time.time() + 15
    while time.time() < end and (not w.alert_store.checked or w._alerts_busy):
        wait(200)
    select("Auckland")
    w.tabs.setCurrentIndex(0)
    shot(w, "15-warning-banner.png", 2500)
    w.tabs.setCurrentWidget(w.alerts_panel)
    shot(w, "16-warnings-tab.png", 1500)
    w.show_alerts_settings()
    shot(w._alerts_dialog, "17-weather-alerts-settings.png", 1200)
    w._alerts_dialog.close()
    w.set_desktop_widget(True)
    dw = w.desktop_widget
    wait(2500)
    img = QImage(dw.width() + 60, dw.height() + 60, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    g = QLinearGradient(0, 0, img.width(), img.height())
    g.setColorAt(0, QColor(46, 62, 92))
    g.setColorAt(1, QColor(22, 28, 44))
    p.fillRect(img.rect(), g)
    dw.render(p, QPoint(30, 30))
    p.end()
    img.save(str(OUT / "18-widget-warning.png"))
    print("saved 18-widget-warning.png")
    w.set_desktop_widget(False)
    w._quitting = True
    w.close()
    srv.httpd.shutdown()
    print("screenshots in", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
