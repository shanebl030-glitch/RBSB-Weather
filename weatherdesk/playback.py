"""Forecast playback bar (1.18): play, scrub and return to now.

A slim bar under the weather scene: ▶ plays the coming hours in the animated sky (an hour
per second), the slider picks any moment up to 24 hours ahead in 15-minute steps, and Now
returns to the live weather. It only reports the chosen offset; the main window turns
that into the sky and the card's text.

Created By Shane BlackbuRn
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QStyle, QToolButton, QWidget

PLAY_RATE = 3600.0          # forecast seconds per real second while playing: an hour a second
TICK_MS = 40                # 25 updates a second while playing
STEP_MIN = 15               # slider step, minutes


class PlaybackBar(QWidget):
    offset_changed = pyqtSignal(float)          # seconds ahead of now (0 = live)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.offset = 0.0
        self.max_offset = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.play_btn = QToolButton()
        self.play_btn.setAutoRaise(True)
        self.play_btn.clicked.connect(self.toggle_play)
        self.play_btn.setToolTip("Play the coming hours in the sky (an hour a second)")
        lay.addWidget(self.play_btn)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(4)                       # an hour
        self.slider.setToolTip("Drag to see the sky at any time in the next 24 hours")
        self.slider.valueChanged.connect(self._slid)
        lay.addWidget(self.slider, 1)
        self.time_label = QLabel()
        self.time_label.setMinimumWidth(150)
        lay.addWidget(self.time_label)
        self.now_btn = QToolButton()
        self.now_btn.setText("Now")
        self.now_btn.setAutoRaise(True)
        self.now_btn.setToolTip("Back to the weather now")
        self.now_btn.clicked.connect(self.go_now)
        lay.addWidget(self.now_btn)
        self.set_range(0.0)

    # ------------------------------------------------------------ state
    @property
    def playing(self) -> bool:
        return self.timer.isActive()

    def set_range(self, max_seconds: float, unavailable: str = "") -> None:
        """How far ahead the forecast allows; 0 disables the bar, showing `unavailable`."""
        self.max_offset = max(0.0, float(max_seconds))
        steps = int(self.max_offset // (STEP_MIN * 60))
        self.slider.blockSignals(True)
        self.slider.setRange(0, steps)
        self.slider.blockSignals(False)
        usable = steps > 0
        for w in (self.play_btn, self.slider):
            w.setEnabled(usable)
        if not usable:
            self.stop()
            self.time_label.setText(unavailable or "No hourly forecast")
            self.time_label.setToolTip(unavailable)
        if self.offset > self.max_offset:
            self._set(self.max_offset)
        self._refresh_buttons()

    WIND_NOTE = ("The hourly forecast has no wind, so the clouds keep the wind of now; "
                 "everything else in the sky is the forecast for this time.")

    def set_time_text(self, text: str) -> None:
        if self.max_offset > 0:
            self.time_label.setText(text)
            self.time_label.setToolTip("" if self.offset <= 0 else self.WIND_NOTE)

    # ---------------------------------------------------------- actions
    def toggle_play(self) -> None:
        if self.playing:
            self.stop()
            return
        if self.max_offset <= 0:
            return
        if self.offset >= self.max_offset - 1:          # at the end: play again from now
            self._set(0.0)
        self.timer.start()
        self._refresh_buttons()

    def stop(self) -> None:
        self.timer.stop()
        self._refresh_buttons()

    def go_now(self) -> None:
        self.stop()
        self._set(0.0)

    def reset(self) -> None:
        """Back to now without announcing it (the caller redraws anyway)."""
        self.blockSignals(True)
        try:
            self.go_now()
        finally:
            self.blockSignals(False)

    def _tick(self) -> None:
        nxt = self.offset + PLAY_RATE * TICK_MS / 1000.0
        if nxt >= self.max_offset:
            self._set(self.max_offset)
            self.stop()
        else:
            self._set(nxt)

    def _slid(self, value: int) -> None:
        if self.playing:
            self.stop()                                  # the user took over
        self._set(min(self.max_offset, value * STEP_MIN * 60.0), from_slider=True)

    def _set(self, offset: float, from_slider: bool = False) -> None:
        offset = max(0.0, min(self.max_offset, offset))
        if not from_slider:
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(offset / (STEP_MIN * 60))))
            self.slider.blockSignals(False)
        changed = offset != self.offset
        self.offset = offset
        self._refresh_buttons()
        if changed:
            self.offset_changed.emit(offset)

    def _refresh_buttons(self) -> None:
        # the desktop theme's own play/pause icons: a text "⏸" isn't in every font
        icon = (QStyle.StandardPixmap.SP_MediaPause if self.playing
                else QStyle.StandardPixmap.SP_MediaPlay)
        self.play_btn.setIcon(self.style().standardIcon(icon))
        self.play_btn.setToolTip("Pause" if self.playing else
                                 "Play the coming hours in the sky (an hour a second)")
        self.now_btn.setEnabled(self.offset > 0 or self.playing)
