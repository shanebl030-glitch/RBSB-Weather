"""Weather warnings in the main window (2.4): the sky banner, Saved-locations badges,
the Warnings tab, the chart's shaded hours, the 7-day tags, the tray dot, the desktop
widget's warning line, notifications and Settings → Weather Alerts.

Mixed into MainWindow; kept here so main_window.py stays readable.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import html
import logging
import time
from typing import Optional

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QApplication, QPushButton, QStyledItemDelegate, QSystemTrayIcon

from . import alerts as A
from . import units
from .alerts_panel import AlertsPanel, short_until, zone_for

log = logging.getLogger(__name__)

BADGE_ROLE = Qt.ItemDataRole.UserRole + 1          # (badge text, background, text colour) or None


class AlertBadgeDelegate(QStyledItemDelegate):
    """Saved locations: a small coloured pill at the right of a place with a warning."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        badge = index.data(BADGE_ROLE)
        if not badge:
            return
        text, bg, fg = badge
        painter.save()
        try:
            f = QFont(option.font)
            f.setBold(True)
            f.setPointSizeF(max(6.5, f.pointSizeF() * 0.75))
            painter.setFont(f)
            fm = painter.fontMetrics()
            w = fm.horizontalAdvance(text) + 10
            h = fm.height() + 2
            r = option.rect
            box = QRectF(r.right() - w - 4, r.center().y() - h / 2, w, h)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QColor(fg))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        finally:
            painter.restore()


class AlertsMixin:
    # ------------------------------------------------------------- set up
    def _build_alerts_ui(self, scene_layout) -> None:
        """Called from _build_ui: the banner (top of the sky) and the Warnings tab."""
        self.alert_banner = QPushButton()
        self.alert_banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alert_banner.setToolTip("Click for the full warning")
        self.alert_banner.clicked.connect(self.show_alerts_tab)
        self.alert_banner.setVisible(False)
        scene_layout.insertWidget(0, self.alert_banner)
        self.scene.avoid_widgets = list(self.scene.avoid_widgets) + [self.alert_banner]
        self.alerts_panel = AlertsPanel()
        self.alerts_panel.open_url.connect(lambda u: self.open_url(u))
        self.alerts_panel.show_map.connect(lambda: self.tabs.setCurrentWidget(self.earth_panel))
        self.alerts_panel.mute.connect(self.set_alert_muted)
        self.alerts_panel.edit_limits.connect(self.show_alerts_settings)
        self.tabs.insertTab(1, self.alerts_panel, "Warnings")
        self.loc_list.setItemDelegate(AlertBadgeDelegate(self.loc_list))

    def _init_alerts(self, alert_client=None) -> None:
        """Called from __init__ once the window exists."""
        self.alert_client = alert_client or A.AlertClient()
        self.alert_store = A.AlertStore(self.cache.dir).load()
        self._alerts_token = 0
        self._alerts_busy = False
        self._alerts_again = False
        self._alerts_dialog = None
        self._alert_click_key: Optional[str] = None
        self.notifications_sent: list[tuple[str, str]] = []      # (title, body), for tests and the log
        self.beep = QApplication.beep                              # replaced in tests
        self.bridge.alerts_ok.connect(self._on_alerts_ok)
        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self.check_alerts)
        self._apply_alert_interval()

    def _apply_alert_interval(self) -> None:
        self.alert_timer.start(int(self.settings.alerts_interval) * 60_000)

    # -------------------------------------------------------------- checks
    def check_alerts(self) -> None:
        """Ask each official source for the saved places' warnings (in the background)."""
        if self._quitting or not self.settings.alerts_official:
            return
        if self._alerts_busy:
            self._alerts_again = True             # e.g. a place was added mid-check
            return
        locs = [l for l in self.settings.locations if A.source_for(l)]
        if not locs:
            return
        self._alerts_busy = True
        self._alerts_token += 1
        self.worker.alerts_update(self._alerts_token, self.alert_client, list(locs))

    def _on_alerts_ok(self, token: int, got: dict, errors: dict) -> None:
        if token != self._alerts_token:
            return
        self._alerts_busy = False
        st = self.alert_store
        st.update(got, [l.key for l in self.settings.locations])
        st.errors = dict(errors)
        st.checked = time.time()
        if errors:
            log.info("alerts: some sources couldn't be read: %s", errors)
        self._alerts_changed(notify=True)
        if self._alerts_again:
            self._alerts_again = False
            self.check_alerts()

    def _alerts_changed(self, notify: bool) -> None:
        self.render()
        self._refresh_alert_badges()
        if notify:
            self._notify_alerts()
        self.alert_store.save()

    # ------------------------------------------------------------- queries
    def alerts_for(self, key: str, now: Optional[float] = None) -> list[A.Alert]:
        """Every active alert for a place: official (if on) and own limits (if on)."""
        s = self.settings
        out = list(self.alert_store.alerts.get(key, [])) if s.alerts_official else []
        fc = self.forecasts.get(key)
        if s.alerts_own and fc is not None:
            out += A.own_alerts(fc, A.limits_from_dict(s.alerts_limits), s.wind_unit, s.temp_unit,
                                s.precip_unit, now)
        return [a for a in out if a.active(now)]

    def shown_alerts(self, key: str, now: Optional[float] = None) -> list[A.Alert]:
        return A.shown(self.alerts_for(key, now), self.settings.alerts_min_level, self.settings.alerts_muted, now)

    def _coverage_text(self, loc) -> str:
        s = self.settings
        if loc is None:
            return ""
        if not s.alerts_official:
            return "Official warnings are turned off (Settings → Weather Alerts)."
        sid = A.source_for(loc)
        if sid is None:
            where = loc.country or loc.name
            return (f"There's no official warning source for {where} in RBSB-Weather yet. "
                    f"Your own limits still work.")
        name = A.SOURCE_NAMES[sid]
        err = self.alert_store.errors.get(sid)
        if err:
            return f"{name} couldn't be read at the last check ({err}). Showing the warnings from before."
        return f"Official warnings here come from {name}."

    def _checked_text(self) -> str:
        st = self.alert_store
        every = f"every {self.settings.alerts_interval} minutes"
        if not self.settings.alerts_official:
            return ""
        if not st.checked:
            return f"Not checked yet · {every}"
        return f"Checked {units.fmt_clock(dt.datetime.fromtimestamp(st.checked))} · {every}"

    # --------------------------------------------------------------- render
    def _render_alerts(self, loc, fc) -> None:
        """Called at the end of render(): everything that shows the selected place's warnings."""
        s = self.settings
        now = time.time()
        shown = self.shown_alerts(loc.key, now) if loc is not None else []
        worst = shown[0] if shown else None
        tz = zone_for(loc, fc.utc_offset_seconds if fc is not None else None)
        # banner
        if worst is not None and s.alerts_banner:
            bg, fg = A.COLOURS[worst.level]
            parts = [f"⚠  {worst.title()}"]
            until = short_until(worst.expires, tz, now)
            if until:
                parts.append(until)
            parts.append(worst.source if worst.official else "not official")
            more = len(shown) - 1
            text = "  ·  ".join(parts) + (f"   (+{more} more)" if more > 0 else "") + "   ›"
            self.alert_banner.setText(text)
            self.alert_banner.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; border: none; border-radius: 6px; "
                f"padding: 5px 10px; font-weight: bold; text-align: left; }}")
            self.alert_banner.setVisible(True)
        else:
            self.alert_banner.setVisible(False)
        # the Warnings tab
        idx = self.tabs.indexOf(self.alerts_panel)
        n = len(shown)
        self.tabs.setTabText(idx, f"⚠ Warnings ({n})" if n else "Warnings")
        self.alerts_panel.set_data(loc, self.alerts_for(loc.key, now) if loc is not None else [],
                                   s.alerts_muted, now, self._checked_text(), self._coverage_text(loc), fc,
                                   s.precip_unit, s.alerts_min_level)
        # chart: the hours a warning is in force
        span = None
        if worst is not None and fc is not None and self.chart.point_count():
            span = self._chart_span(shown, fc)
        self.chart.set_alert_span(span)
        # 7-day tags
        if fc is not None:
            for r, labels in enumerate(self.day_rows):
                if r >= len(fc.daily):
                    continue
                desc = labels[2].text()
                if "<span" in desc:
                    continue                                 # already tagged
                a = self._worst_on_day(shown, fc.daily[r].date, tz)
                if a is not None:
                    desc = html.escape(desc)
                    bg, fg = A.COLOURS[a.level]
                    tag = {"limit": "MY LIMIT", "watch": "WATCH"}.get(a.level, f"{a.badge} WARNING"
                                                                    if a.level != "minor" else "ADVISORY")
                    desc += (f"&nbsp;&nbsp;<span style=\"background:{bg}; color:{fg}; font-weight:bold;\">"
                             f"&nbsp;{tag}&nbsp;</span>")
                labels[2].setText(desc)
        # desktop widget (the tray's dot is drawn by _update_tray)
        dw = self.desktop_widget
        if dw is not None:
            if worst is not None and s.alerts_banner:
                bg, fg = A.COLOURS[worst.level]
                until = short_until(worst.expires, tz, now)
                dw.set_alert(f"⚠ {worst.title()}", bg, fg,
                             (f"{worst.title()} {until}. " if until else "") + "Click for the full warning")
            else:
                dw.set_alert("")

    def _chart_span(self, shown: list[A.Alert], fc) -> Optional[tuple]:
        pts = self.chart._points
        tz = zone_for(fc.location, fc.utc_offset_seconds)
        times = []
        for p in pts:
            try:
                t = dt.datetime.fromisoformat(p.time)
            except ValueError:
                return None
            times.append((t if t.tzinfo else t.replace(tzinfo=tz)).timestamp())
        for a in shown:
            first = last = None
            for i, ts in enumerate(times):
                if (a.onset is None or ts + 3600 > a.onset) and (a.expires is None or ts < a.expires):
                    first = i if first is None else first
                    last = i
            if first is not None:
                label = f"{a.title()} in force" if a.official else a.title()
                return first, last, A.COLOURS[a.level][0], label
        return None

    @staticmethod
    def _worst_on_day(shown: list[A.Alert], date: str, tz) -> Optional[A.Alert]:
        try:
            d = dt.date.fromisoformat(date[:10])
        except ValueError:
            return None
        start = dt.datetime.combine(d, dt.time(), tz).timestamp()
        end = start + 86400
        for a in shown:
            if (a.onset is None or a.onset < end) and (a.expires is None or a.expires > start):
                return a
        return None

    def _refresh_alert_badges(self) -> None:
        s = self.settings
        for i in range(self.loc_list.count()):
            it = self.loc_list.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            badge = None
            if s.alerts_banner:
                worst = next(iter(self.shown_alerts(key)), None)
                if worst is not None:
                    bg, fg = A.COLOURS[worst.level]
                    badge = (worst.badge, bg, fg)
            if it.data(BADGE_ROLE) != badge:
                it.setData(BADGE_ROLE, badge)

    def tray_alert_colour(self, key: Optional[str]) -> Optional[str]:
        if key is None or not self.settings.alerts_tray_dot:
            return None
        now = time.time()
        for a in self.shown_alerts(key, now):
            if a.in_force(now) or (a.onset or 0) - now < 24 * 3600:
                return A.COLOURS[a.level][0]
        return None

    # ---------------------------------------------------------- notifications
    def _notify_alerts(self) -> None:
        s = self.settings
        st = self.alert_store
        sel = s.selected_location()
        locs = [sel] if s.alerts_selected_only and sel else list(s.locations)
        fresh = []
        for loc in locs:
            for a in A.to_notify(self.alerts_for(loc.key), st.notified, s.alerts_min_level, s.alerts_muted):
                fresh.append((loc, a))
        if not fresh:
            return
        for _, a in fresh:
            st.notified[a.id] = a.signature()
        st.save()
        if not s.alerts_notify:
            return
        fresh.sort(key=lambda x: x[1].rank)
        loc, a = fresh[0]
        if len(fresh) == 1:
            title = f"⚠ {a.title()}: {loc.name}"
            body = (a.headline if a.headline and a.headline != a.event else a.description) or a.area
            body = (body[:220] + "…") if len(body) > 220 else body
            if a.official:
                body += f" ({a.source})"
        else:
            title = f"⚠ {len(fresh)} weather warnings"
            body = "\n".join(f"{x.title()}: {l.name}" for l, x in fresh[:5])
            if len(fresh) > 5:
                body += f"\n… and {len(fresh) - 5} more"
        self.notifications_sent.append((title, body))
        self._alert_click_key = loc.key
        self._tray_click = "alerts"
        red = any(x.level == "red" for _, x in fresh)
        if self.tray is not None and self.tray.isVisible():
            icon = (QSystemTrayIcon.MessageIcon.Critical if red else QSystemTrayIcon.MessageIcon.Warning)
            self.tray.showMessage(title, body, icon, 60_000 if red else 15_000)
        else:
            self.statusBar().showMessage(f"{title} — {body.splitlines()[0]}", 30_000)
        if red and s.alerts_beep_red:
            self.beep()

    def show_alerts_tab(self, key: Optional[str] = None) -> None:
        if key and key != self.settings.selected:
            self.select_location(key)
        self.tabs.setCurrentWidget(self.alerts_panel)

    def _on_alert_notice_clicked(self) -> None:
        self.show_normal()
        self.show_alerts_tab(self._alert_click_key)

    # -------------------------------------------------------------- actions
    def set_alert_muted(self, alert_id: str, muted: bool) -> None:
        m = [x for x in self.settings.alerts_muted if x != alert_id]
        if muted:
            m.append(alert_id)
        self.settings.alerts_muted = m[-200:]
        self.save_settings()
        self._alerts_changed(notify=False)

    def coverage_rows(self) -> list[tuple[str, str, str]]:
        st = self.alert_store
        rows = []
        for loc in self.settings.locations:
            sid = A.source_for(loc)
            if sid is None:
                rows.append((loc.name, "None available", "Not covered yet"))
                continue
            if not self.settings.alerts_official:
                status = "Off"
            elif st.errors.get(sid):
                status = "Couldn't be read"
            elif st.checked:
                status = "Working"
            else:
                status = "Not checked yet"
            rows.append((loc.name, A.SOURCE_NAMES[sid], status))
        return rows

    def show_alerts_settings(self) -> None:
        from .alerts_dialog import AlertsDialog
        if self._alerts_dialog is not None:
            self._alerts_dialog.close()
            self._alerts_dialog.deleteLater()
        dlg = AlertsDialog(self.settings, self.coverage_rows(), self)
        dlg.applied.connect(self.apply_alert_settings)
        self._alerts_dialog = dlg
        dlg.show()
        dlg.raise_()

    def apply_alert_settings(self, values: dict) -> None:
        s = self.settings
        was_on, old_interval = s.alerts_official, s.alerts_interval
        for k, v in values.items():
            if hasattr(s, k):
                setattr(s, k, v)
        self.save_settings()
        if s.alerts_interval != old_interval:
            self._apply_alert_interval()
        self._alerts_changed(notify=True)
        if s.alerts_official and not was_on:
            self.check_alerts()
