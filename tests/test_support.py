"""2.1.1: "Buy me a coffee" link (Help menu, About box, User Guide, README).

Checks the link is the agreed PayPal payment link (Shane's public Merchant ID,
NZ$0.99, https, paypal.com only, no email address) and that every place shows it.
Opening the browser is replaced by a recorder, so the tests never launch anything.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import re
import unittest
import urllib.parse
from pathlib import Path

from helpers import ROOT, TempEnvTestCase, qapp, wait_until

from rbsb_weather import COFFEE_TEXT, COFFEE_URL


class TestCoffeeLink(unittest.TestCase):
    def test_link_is_the_agreed_paypal_link(self):
        u = urllib.parse.urlsplit(COFFEE_URL)
        self.assertEqual((u.scheme, u.hostname, u.path), ("https", "www.paypal.com", "/cgi-bin/webscr"))
        q = dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual(q["business"], "M4EDN77T6EEPJ")
        self.assertEqual(q["amount"], "0.99")
        self.assertEqual(q["currency_code"], "NZD")
        self.assertEqual(q["cmd"], "_xclick")
        self.assertIn("RBSB-Weather", q["item_name"])
        self.assertNotIn("@", COFFEE_URL, "no email address in a public link")
        self.assertEqual(COFFEE_TEXT, "If you enjoy this app, consider buying me a coffee for NZ$0.99")

    def test_in_guide_and_readme(self):
        for f in (ROOT / "rbsb_weather" / "USER_GUIDE.md", ROOT / "README.md"):
            text = f.read_text(encoding="utf-8")
            self.assertIn(COFFEE_TEXT, text, f.name)
            self.assertIn(f"({COFFEE_URL})", text, f.name)

    def test_no_personal_details_shipped(self):
        """Only the public Merchant ID may appear; never the account's email or phone."""
        for p in list((ROOT / "rbsb_weather").rglob("*.py")) + list((ROOT / "rbsb_weather").glob("*.md")) + \
                [ROOT / "README.md"]:
            text = p.read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(re.search(r"[\w.+-]+@gmail\.com", text), p)


class TestCoffeeInWindow(TempEnvTestCase):
    def setUp(self):
        super().setUp()
        qapp()
        from rbsb_weather.main_window import MainWindow
        self.w = MainWindow(enable_tray=False)
        self.opened = []
        self.w.open_url = lambda url: self.opened.append(url) or True

    def tearDown(self):
        self.w._quitting = True
        self.w.close()
        self.w.deleteLater()
        super().tearDown()

    def test_help_menu_opens_paypal(self):
        help_menu = [m.menu() for m in self.w.menuBar().actions() if m.text() == "&Help"][0]
        act = [a for a in help_menu.actions() if "Coffee" in a.text()][0]
        act.trigger()
        self.assertEqual(self.opened, [COFFEE_URL])

    def test_about_shows_text_and_clickable_link(self):
        html = self.w.about_html()
        self.assertIn(COFFEE_TEXT, html)
        self.assertIn(f"href='{COFFEE_URL}'", html)
        self.assertIn("Created By Shane BlackbuRn", html)
        # the real About box: its text label must open links in the browser
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox
        found = {}

        def inspect():
            box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
            labels = [l for l in box.findChildren(QLabel) if COFFEE_TEXT in l.text()]
            found["ok"] = bool(labels) and labels[0].openExternalLinks()
            box.close()
        QTimer.singleShot(300, inspect)
        self.w.show_about()
        self.assertTrue(found.get("ok"), "About box shows the link and opens it in the browser")

    def test_browser_not_available(self):
        self.w.open_url = lambda url: False
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication, QMessageBox
        seen = {}

        def inspect():
            box = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible())
            seen["text"] = box.text()
            box.close()
        QTimer.singleShot(300, inspect)
        self.w.buy_coffee()
        self.assertIn(COFFEE_URL, seen.get("text", ""), "the link is shown so it can be copied")


if __name__ == "__main__":
    unittest.main()
