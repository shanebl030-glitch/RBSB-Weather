"""README screenshots: the sample data the tool uses is valid, and the README's
pictures all exist. Created By Shane BlackbuRn"""

import datetime as dt
import importlib.util
import re
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets the offline environment)

ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    spec = importlib.util.spec_from_file_location("make_screenshots", ROOT / "tools" / "make_screenshots.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SampleDataTest(unittest.TestCase):
    def test_every_city_parses_as_a_full_forecast_dated_today(self):
        from rbsb_weather.api import parse_forecast
        from rbsb_weather.models import Location
        from zoneinfo import ZoneInfo
        tool = load_tool()
        for name, lat, lon, country, region, tzname, *_ in tool.CITIES:
            with self.subTest(city=name):
                fc = parse_forecast(tool.sample(lat, lon), Location(name, lat, lon, country, region, tzname))
                self.assertEqual(len(fc.daily), 7)
                self.assertEqual(len(fc.hourly), 7 * 24)
                self.assertEqual(fc.daily[0].date, dt.datetime.now(ZoneInfo(tzname)).date().isoformat())
                for d in fc.daily:
                    self.assertLessEqual(d.temp_min, d.temp_max)
                    self.assertIsNotNone(d.sunrise)

    def test_the_tool_only_talks_to_this_computer(self):
        text = (ROOT / "tools" / "make_screenshots.py").read_text()
        hosts = {h.split(":")[0] for h in re.findall(r"https?://([^/\"' ]+)", text)}
        self.assertLessEqual(hosts, {"127.0.0.1", "github.com"}, hosts)   # github only in a never-fetched example


class ReadmeImagesTest(unittest.TestCase):
    def test_every_picture_in_the_readme_exists(self):
        readme = (ROOT / "README.md").read_text()
        pics = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
        self.assertGreaterEqual(len(pics), 10)
        for p in pics:
            with self.subTest(p=p):
                f = ROOT / p
                self.assertTrue(f.is_file(), p)
                self.assertGreater(f.stat().st_size, 1000)

    def test_every_screenshot_is_in_the_readme(self):
        readme = (ROOT / "README.md").read_text()
        for f in sorted((ROOT / "docs" / "media" / "screenshots").glob("*.png")):
            with self.subTest(f=f.name):
                self.assertIn(f"docs/media/screenshots/{f.name}", readme)


if __name__ == "__main__":
    unittest.main()
