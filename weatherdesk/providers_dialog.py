"""Settings → Weather Providers.

Left: every provider WeatherDesk knows, with its status. Right: details for the
selected one (coverage, features, limits, last update, usage), its API key
(add / change / remove, never shown once saved) and Test connection. Bottom:
the primary provider, the backups in order, and what to do when the primary
fails.

Created By Shane BlackbuRn
"""

from __future__ import annotations

import datetime as dt
import time
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from . import providers, units
from .keystore import MASK
from .models import Location
from .providers import FEATURES
from .providers.manager import RECOVERY_LABELS

STATE_TEXT = {
    "working": ("✓", "Working", "#2e7d32"),
    "failing": ("⚠", "Not working", "#c62828"),
    "no key": ("🔑", "Needs an API key", "#8d6e00"),
    "not used yet": ("○", "Not used yet", "#555555"),
    "planned": ("…", "Planned for a later version", "#777777"),
}
FALLBACK_TEST_PLACE = Location("Auckland", -36.8485, 174.7635, "New Zealand", "Auckland", "Pacific/Auckland")


def _when(ts: float) -> str:
    if not ts:
        return "never"
    t = dt.datetime.fromtimestamp(ts)
    age = time.time() - ts
    ago = ("just now" if age < 90 else f"{int(age // 60)} min ago" if age < 3600
           else f"{int(age // 3600)} h ago" if age < 86400 else f"{int(age // 86400)} days ago")
    day = "" if t.date() == dt.date.today() else t.strftime("%a %d %b ")
    return f"{day}{units.fmt_clock(t)} ({ago})"


class ProvidersDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.manager = win.client
        self.setWindowTitle("Weather Providers")
        self.resize(980, 800)
        self._test_token = 0
        self._testing: Optional[str] = None
        self._results: dict[str, tuple[bool, str]] = {}     # provider id -> last test result shown

        root = QVBoxLayout(self)
        intro = QLabel("Choose where WeatherDesk gets its weather. If the primary provider can't be "
                       "reached, the backups are tried in order.")
        intro.setWordWrap(True)
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(230)
        self.list.currentItemChanged.connect(lambda *_: self._show_details())
        split.addWidget(self.list)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.details = QWidget()
        scroll.setWidget(self.details)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self._build_details()

        root.addWidget(self._build_order())

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel |
                                        QDialogButtonBox.StandardButton.Apply)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        root.addWidget(self.buttons)

        win.bridge.provider_test.connect(self._on_test_done)

    # ------------------------------------------------------------- building
    def _build_details(self) -> None:
        lay = QVBoxLayout(self.details)
        self.title = QLabel()
        f = self.title.font(); f.setPointSizeF(f.pointSizeF() * 1.4); f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        self.state_label = QLabel()
        self.state_label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.state_label)

        form = self.form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.f = {}
        for key, label in (("coverage", "Coverage"), ("days", "Forecast"), ("hourly", "Hourly"),
                           ("limits", "Free allowance and limits"), ("features", "Supplies"),
                           ("calculated", "Calculated by WeatherDesk"), ("last_ok", "Last successful update"),
                           ("last_error", "Last problem"), ("usage", "Usage reported"),
                           ("links", "Links"), ("reason", "Why not yet")):
            w = QLabel()
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            w.setOpenExternalLinks(True)
            self.f[key] = w
            form.addRow(f"<b>{label}:</b>", w)
        lay.addLayout(form)

        self.key_box = QGroupBox("API key")
        kl = QVBoxLayout(self.key_box)
        self.key_status = QLabel()
        self.key_status.setWordWrap(True)
        kl.addWidget(self.key_status)
        row = QHBoxLayout()
        self.btn_key = QPushButton("Add key…")
        self.btn_key.clicked.connect(self._edit_key)
        self.btn_remove = QPushButton("Remove key")
        self.btn_remove.clicked.connect(self._remove_key)
        row.addWidget(self.btn_key)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        kl.addLayout(row)
        self.key_editor = QWidget()
        el = QHBoxLayout(self.key_editor)
        el.setContentsMargins(0, 0, 0, 0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste your API key")
        self.key_edit.setClearButtonEnabled(True)
        self.key_show = QCheckBox("Show while typing")
        self.key_show.toggled.connect(lambda on: self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        self.btn_save_key = QPushButton("Save key")
        self.btn_save_key.clicked.connect(self._save_key)
        self.btn_cancel_key = QPushButton("Cancel")
        self.btn_cancel_key.clicked.connect(self._close_key_editor)
        for w in (self.key_edit, self.key_show, self.btn_save_key, self.btn_cancel_key):
            el.addWidget(w)
        el.setStretch(0, 1)
        kl.addWidget(self.key_editor)
        self.key_store_note = QLabel()
        self.key_store_note.setWordWrap(True)
        self.key_store_note.setStyleSheet("color: palette(placeholder-text);")
        kl.addWidget(self.key_store_note)
        lay.addWidget(self.key_box)

        trow = QHBoxLayout()
        self.btn_test = QPushButton("Test connection")
        self.btn_test.clicked.connect(self._test)
        trow.addWidget(self.btn_test)
        trow.addStretch(1)
        lay.addLayout(trow)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.test_result)
        lay.addStretch(1)

    def _build_order(self) -> QGroupBox:
        box = QGroupBox("Provider order")
        g = QVBoxLayout(box)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Primary provider:"))
        self.primary = QComboBox()
        self.primary.currentIndexChanged.connect(lambda *_: self._primary_changed())
        r1.addWidget(self.primary, 1)
        r1.addSpacing(16)
        r1.addWidget(QLabel("When the primary fails:"))
        self.recovery = QComboBox()
        for k, label in RECOVERY_LABELS.items():
            self.recovery.addItem(label, k)
        r1.addWidget(self.recovery, 1)
        g.addLayout(r1)

        r2 = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(QLabel("Backups (ticked ones are tried in this order):"))
        self.backups = QListWidget()
        self.backups.setMaximumHeight(108)
        self.backups.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.backups.itemChanged.connect(lambda *_: self._update_warning())
        col.addWidget(self.backups)
        r2.addLayout(col, 1)
        btns = QVBoxLayout()
        btns.addStretch(1)
        self.btn_up = QPushButton("▲ Up")
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down = QPushButton("▼ Down")
        self.btn_down.clicked.connect(lambda: self._move(1))
        btns.addWidget(self.btn_up)
        btns.addWidget(self.btn_down)
        r2.addLayout(btns)
        g.addLayout(r2)

        r3 = QHBoxLayout()
        self.supplying = QLabel()
        self.supplying.setTextFormat(Qt.TextFormat.RichText)
        r3.addWidget(self.supplying, 1)
        self.btn_primary_now = QPushButton("Use the primary now")
        self.btn_primary_now.setToolTip("Ask the primary provider first at the next update, "
                                        "even if it failed recently")
        self.btn_primary_now.clicked.connect(self._primary_now)
        r3.addWidget(self.btn_primary_now)
        g.addLayout(r3)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #b26a00;")
        g.addWidget(self.warning)
        return box

    # --------------------------------------------------------------- state
    def reload(self) -> None:
        """Fill everything from the manager (called each time the dialog opens)."""
        self.manager = self.win.client
        cur = self._current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for inf in providers.all_infos():
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, inf.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._refresh_list()
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        self.list.setCurrentRow(ids.index(cur) if cur in ids else ids.index(self.manager.primary))

        self.primary.blockSignals(True)
        self.primary.clear()
        for pid in providers.integrated_ids():
            self.primary.addItem(providers.info(pid).name, pid)
        self.primary.setCurrentIndex(self.primary.findData(self.manager.primary))
        self.primary.blockSignals(False)
        self.recovery.setCurrentIndex(self.recovery.findData(self.manager.recovery))
        self._fill_backups(self.manager.chain[1:])
        self._close_key_editor()
        self._show_details()
        self._update_supplying()

    def _current_id(self) -> Optional[str]:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _role(self, pid: str) -> str:
        chain = self.manager.chain
        if pid == chain[0]:
            return "primary"
        if pid in chain:
            return f"backup {chain.index(pid)}"
        return ""

    def _refresh_list(self) -> None:
        for i in range(self.list.count()):
            it = self.list.item(i)
            pid = it.data(Qt.ItemDataRole.UserRole)
            inf = providers.info(pid)
            sym, text, color = STATE_TEXT[self.manager.state(pid)]
            role = self._role(pid)
            supplying = " · supplying now" if pid == self.manager.active else ""
            it.setText(f"{sym}  {inf.name}" + (f"  ({role})" if role else "") + f"\n     {text}{supplying}")
            it.setToolTip(text)
            if inf.status != "integrated":
                it.setForeground(Qt.GlobalColor.gray)

    def _show_details(self) -> None:
        pid = self._current_id()
        if pid is None:
            return
        inf = providers.info(pid)
        integrated = inf.status == "integrated"
        st = self.manager.status(pid)
        state = self.manager.state(pid)
        sym, text, color = STATE_TEXT[state]
        self.title.setText(inf.name)
        role = self._role(pid)
        extra = f" · {role.capitalize()}" if role else ""
        if pid == self.manager.active:
            extra += " · <b>supplying the weather now</b>"
        self.state_label.setText(f"<span style='color:{color}'>{sym} {text}</span>{extra}")
        self.f["coverage"].setText(inf.coverage)
        self.f["days"].setText(inf.forecast_days)
        self.f["hourly"].setText(inf.hourly)
        self.f["limits"].setText(inf.limits + (" No key needed." if not inf.needs_key else ""))
        feats = [("✓ " if k in inf.features else "– ") + v for k, v in FEATURES.items()] if integrated else []
        half = (len(feats) + 1) // 2
        rows = "".join(f"<tr><td>{a}</td><td style='padding-left:18px'>{b}</td></tr>"
                       for a, b in zip(feats[:half], feats[half:] + [""]))
        self.f["features"].setText(f"<table cellspacing=0>{rows}</table>" if feats else "–")
        calc = self._calculated(pid)
        self.f["calculated"].setText(", ".join(calc) if calc else "–")
        self.f["last_ok"].setText(_when(st.last_ok) if integrated else "–")
        err = st.last_error if st.last_error_at and st.last_error_at >= st.last_ok else ""
        self.f["last_error"].setText(f"{err} ({_when(st.last_error_at)})" if err else "–")
        usage = dict(st.usage or {})
        if st.plan:
            usage.setdefault("plan", st.plan)
        self.f["usage"].setText("<br>".join(f"{v}" for v in usage.values()) if usage
                                else "This provider doesn't report usage." if integrated else "–")
        links = []
        if inf.signup_url and inf.needs_key:
            links.append(f"<a href='{inf.signup_url}'>Sign up / get a key</a>")
        links.append(f"<a href='{inf.website}'>Website</a>")
        if inf.docs_url:
            links.append(f"<a href='{inf.docs_url}'>API documentation</a>")
        self.f["links"].setText(" · ".join(links))
        self.f["reason"].setText(inf.planned_reason or "–")
        self._set_row_visible("reason", not integrated)
        for k in ("features", "calculated", "last_ok", "last_error", "usage"):
            self._set_row_visible(k, integrated)

        self.key_box.setVisible(integrated and inf.needs_key)
        if integrated and inf.needs_key:
            has = self.manager.has_key(pid)
            self.key_status.setText(f"<b>Saved</b> {MASK} (hidden; it can't be shown again)" if has
                                    else "No key saved yet. " + (inf.key_help or ""))
            self.btn_key.setText("Change key…" if has else "Add key…")
            self.btn_remove.setEnabled(has)
            self.key_store_note.setText(f"Keys are stored in {self.manager.keystore.backend}, never in "
                                        f"WeatherDesk's settings, logs or reports.")
        self.btn_test.setVisible(integrated)
        self.btn_test.setEnabled(integrated and self._testing is None)
        if pid in self._results:
            ok, msg = self._results[pid]
            self._show_result(ok, msg)
        elif st.test_at:
            self._show_result(bool(st.test_ok), f"{st.test_message} (tested {_when(st.test_at)})")
        else:
            self.test_result.setText("")
        if self._testing == pid:
            self.test_result.setText("Testing…")

    def _set_row_visible(self, key: str, on: bool) -> None:
        w = self.f[key]
        w.setVisible(on)
        lab = self.form.labelForField(w)
        if lab is not None:
            lab.setVisible(on)

    def _calculated(self, pid: str) -> list[str]:
        for fc in self.win.forecasts.values():
            if fc.provider_id == pid and not fc.from_cache:
                return list(fc.calculated)
        return []

    def _show_result(self, ok: bool, msg: str) -> None:
        color = "#2e7d32" if ok else "#c62828"
        self.test_result.setText(f"<span style='color:{color}'><b>{'✓ Connected' if ok else '⚠ Failed'}</b>"
                                 f"</span> – {msg.replace('<', '&lt;')}")

    # ---------------------------------------------------------------- keys
    def _edit_key(self) -> None:
        self.key_edit.clear()
        self.key_show.setChecked(False)
        self.key_editor.setVisible(True)
        self.key_edit.setFocus()

    def _close_key_editor(self) -> None:
        self.key_edit.clear()
        self.key_show.setChecked(False)
        self.key_editor.setVisible(False)

    def _save_key(self) -> None:
        pid = self._current_id()
        value = self.key_edit.text().strip()
        try:
            self.manager.set_key(pid, value)
        except ValueError as e:
            self._show_result(False, str(e))
            return
        except Exception as e:
            self._show_result(False, f"The key couldn't be saved ({type(e).__name__}).")
            return
        self._results.pop(pid, None)
        self._close_key_editor()
        self._show_details()
        self._refresh_list()
        self._update_warning()
        self._test()                      # check it straight away

    def _remove_key(self) -> None:
        pid = self._current_id()
        self.manager.remove_key(pid)
        self._results.pop(pid, None)
        self._show_details()
        self._refresh_list()
        self._update_warning()

    # ---------------------------------------------------------------- test
    def _test(self) -> None:
        pid = self._current_id()
        if pid is None or self._testing is not None:
            return
        typed = self.key_edit.text().strip() if self.key_editor.isVisible() else ""
        inf = providers.info(pid)
        if inf.needs_key and not typed and not self.manager.has_key(pid):
            self._show_result(False, "Add an API key first.")
            return
        self._test_token += 1
        self._testing = pid
        self.btn_test.setEnabled(False)
        self.test_result.setText("Testing…")
        loc = self.win.settings.selected_location() or FALLBACK_TEST_PLACE
        self.win.worker.test_provider(self._test_token, self.manager, pid, typed or None, loc)

    def _on_test_done(self, token: int, pid: str, ok: bool, msg: str) -> None:
        if token != self._test_token:
            return
        self._testing = None
        self._results[pid] = (ok, msg)
        self._refresh_list()
        if self._current_id() == pid:
            self._show_details()
        self.btn_test.setEnabled(True)

    # --------------------------------------------------------------- order
    def _fill_backups(self, selected: list[str]) -> None:
        primary = self.primary.currentData()
        self.backups.blockSignals(True)
        self.backups.clear()
        others = [p for p in selected if p != primary] + \
                 [p for p in providers.integrated_ids() if p not in selected and p != primary]
        for pid in others:
            it = QListWidgetItem(providers.info(pid).name)
            it.setData(Qt.ItemDataRole.UserRole, pid)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if pid in selected else Qt.CheckState.Unchecked)
            self.backups.addItem(it)
        self.backups.blockSignals(False)
        self._update_warning()

    def chosen_chain(self) -> list[str]:
        chain = [self.primary.currentData()]
        for i in range(self.backups.count()):
            it = self.backups.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                chain.append(it.data(Qt.ItemDataRole.UserRole))
        return chain

    def _primary_changed(self) -> None:
        self._fill_backups([p for p in self.chosen_backups_or_current() if p != self.primary.currentData()])

    def chosen_backups_or_current(self) -> list[str]:
        out = []
        for i in range(self.backups.count()):
            it = self.backups.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out or self.manager.chain[1:]

    def _move(self, delta: int) -> None:
        row = self.backups.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.backups.count():
            return
        it = self.backups.takeItem(row)
        self.backups.insertItem(new, it)
        self.backups.setCurrentRow(new)
        self._update_warning()

    def _update_warning(self) -> None:
        missing = [providers.info(p).name for p in self.chosen_chain()
                   if providers.info(p).needs_key and not self.manager.has_key(p)]
        notes = []
        if missing:
            notes.append(f"⚠ No API key saved for {', '.join(missing)}, so "
                         f"{'it' if len(missing) == 1 else 'they'} will be skipped until you add one.")
        if len(self.chosen_chain()) == 1:
            notes.append("⚠ No backup is ticked: if the primary fails, the weather won't update.")
        self.warning.setText("\n".join(notes))
        self.warning.setVisible(bool(notes))

    def _update_supplying(self) -> None:
        m = self.manager
        if m.active:
            since = _when(m.active_since) if m.active_since else ""
            role = "primary" if m.active == m.primary else "backup"
            self.supplying.setText(f"Currently supplying the weather: <b>{providers.info(m.active).name}</b> "
                                   f"({role}){' since ' + since if since and role == 'backup' else ''}")
        else:
            self.supplying.setText("Currently supplying the weather: – (no update yet)")
        self.btn_primary_now.setVisible(bool(m.active) and m.active != m.primary)

    def _primary_now(self) -> None:
        self.manager.try_primary_now()
        self.win.refresh_selected(force=True)
        self.btn_primary_now.setEnabled(False)

    # ------------------------------------------------------------- buttons
    def _apply(self) -> None:
        self.win.apply_provider_settings(self.chosen_chain(), self.recovery.currentData())
        self._refresh_list()
        self._show_details()
        self._update_supplying()

    def _ok(self) -> None:
        self._apply()
        self.accept()

    def refresh_status(self) -> None:
        """Called by the main window after each update so the status stays current."""
        if self.isVisible():
            self._refresh_list()
            self._show_details()
            self._update_supplying()
            self.btn_primary_now.setEnabled(True)
