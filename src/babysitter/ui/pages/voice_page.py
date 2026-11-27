"""How BabySitter will sound, and how it hears you.

The controls save your choices. Speaking them out loud waits until a
voice engine is installed. The only copied voices are the narrators, who
released their recordings, and your own, recorded here after a consent
question (`ownvoice.py`).
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from babysitter.paths import data_dir
from babysitter.ui.pinbutton import pin_button


VOICES = (
    ("American", "Heart & Sarah blend", "Kokoro", "Local"),
    ("American", "EDITH-style blend", "Kokoro", "Local"),

    ("American", "af_heart", "Kokoro", "Local"),
    ("American", "am_michael", "Kokoro", "Local"),
    ("American", "Microsoft Zira", "Windows", "Local"),
    ("British", "bf_emma", "Kokoro", "Local"),
    ("British", "bm_george", "Kokoro", "Local"),
    ("British", "Microsoft Hazel", "Windows", "Local"),
    ("Australian", "Microsoft Catherine", "Windows", "Not installed"),
    ("Australian", "Microsoft James", "Windows", "Not installed"),
    ("Australian", "en-AU-NatashaNeural", "Azure", "Cloud, off"),
)


def _all_voices():
    """The blends and Windows voices above, plus every voice in the catalog."""
    from babysitter.voice_catalog import catalog

    engines = {"kokoro": "Kokoro", "piper": "Piper", "supertonic": "Supertonic", "natural": "Natural, real narrator"}
    listed = {name for _accent, name, _engine, _where in VOICES}
    extra = [
        (voice.accent, voice.name, "Natural, your voice" if voice.speaker == "own" else engines[voice.engine], "Local")
        for voice in catalog()
        if voice.name not in listed
    ]
    natural = [row for row in extra if row[2].startswith("Natural")]
    others = [row for row in extra if not row[2].startswith("Natural")]
    # The real narrators first after the default, since they sound the most human.
    return list(VOICES[:2]) + natural + others[:28] + list(VOICES[2:]) + others[28:]


ALL_VOICES = _all_voices()


class VoicePage(QWidget):
    notice = Signal(str)
    # A voice whose model pack is not on this PC yet: the pack id.
    pack_needed = Signal(str)
    voice_saved = Signal(str)
    pin_line = Signal(str)
    record_own = Signal()
    delete_own = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        title = QLabel("Voice")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("How I sound, and how I hear you. Nothing here is sent off this PC unless you turn on a cloud voice later.")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        layout.addWidget(intro)

        preview = QPushButton('Preview “Fresh start, I kept the important bits.”')
        preview.setObjectName("primary")
        preview.setToolTip("Plays the line when a local voice engine is installed.")
        preview.clicked.connect(self._preview)
        layout.addWidget(preview)

        self.voice_search = QLineEdit()
        self.voice_search.setAccessibleName("Find a voice")
        self.voice_search.setPlaceholderText(f"Find a voice: {len(ALL_VOICES)} to choose from. Try British, Piper, or a name")
        self.voice_search.textChanged.connect(self._filter_voices)
        layout.addWidget(self.voice_search)
        self.voice = QComboBox()
        self.voice.setAccessibleName("Voice selection")
        self.voice.setMaxVisibleItems(18)
        for accent, name, engine, where in ALL_VOICES:
            self.voice.addItem(f"{accent} · {name} · {engine} · {where}", name)
        self.voice.setToolTip("Pick a voice. Australian Windows voices have to be added in Windows first.")
        layout.addWidget(self.voice)

        use = QPushButton("Use this voice")
        use.setToolTip("Saves the choice on this PC. It does not download a voice by itself.")
        use.clicked.connect(self._use)
        voice_row = QHBoxLayout()
        voice_row.addWidget(use)
        voice_pin = pin_button()
        voice_pin.setToolTip("Pin the voice you picked. It stays on this PC.")
        voice_pin.clicked.connect(self._pin_voice)
        voice_row.addWidget(voice_pin)
        voice_row.addStretch(1)
        layout.addLayout(voice_row)

        own_row = QHBoxLayout()
        record = QPushButton("Record my voice…")
        record.setToolTip(
            "Read a short passage for about 15 seconds. BabySitter copies how you sound. "
            "The recording stays on this PC. It asks first."
        )
        record.clicked.connect(self.record_own.emit)
        own_row.addWidget(record)
        forget = QPushButton("Delete my voice")
        forget.setToolTip("Deletes your voice recording from this PC.")
        forget.clicked.connect(self.delete_own.emit)
        own_row.addWidget(forget)
        own_row.addStretch(1)
        layout.addLayout(own_row)

        self.speed = self._slider("Speed", 80, 130, 105)
        self.pitch = self._slider("Pitch", -6, 6, -1)
        self.followup = self._slider("Follow-up seconds", 5, 20, 10)
        layout.addWidget(self.speed[0])
        layout.addWidget(self.pitch[0])
        layout.addWidget(self.followup[0])
        self.speed[1].sliderReleased.connect(self._save_sliders)
        self.pitch[1].sliderReleased.connect(self._save_sliders)
        self.followup[1].sliderReleased.connect(
            lambda: self.notice.emit(f"FOLLOWUP {self.followup[1].value()}")
        )
        self.proactivity = self._slider("Proactivity", 0, 3, 1)
        self.proactivity[1].setToolTip(
            "0 answers and stops. 1 offers the rest. 2 can mention a saved fact. 3 can offer the weekly review."
        )
        layout.addWidget(self.proactivity[0])
        self.proactivity[1].sliderReleased.connect(
            lambda: self.notice.emit(f"PROACTIVITY {self.proactivity[1].value()}")
        )

        ratings = QHBoxLayout()
        for label in ("shorter", "longer", "warmer", "cooler", "just right"):
            button = QPushButton(label)
            button.setToolTip("Saved on this PC. It applies the next time the AI turns on.")
            button.clicked.connect(lambda _checked=False, name=label: self.notice.emit(f"RATE {name}"))
            ratings.addWidget(button)
        layout.addLayout(ratings)

        self.status = QLabel(self._saved_line())
        self.status.setWordWrap(True)
        self.status.setObjectName("hint")
        layout.addWidget(self.status)
        download = QPushButton("Download speech recognition")
        download.setObjectName("primary")
        download.setToolTip(
            "Downloads the hearing programs and the small speech model onto this PC. Nothing you say is sent out."
        )
        download.clicked.connect(lambda: self.notice.emit("INSTALL hearing"))
        layout.addWidget(download)
        silero = QPushButton("Download the sharper voice detector")
        silero.setToolTip(
            "Downloads Silero onto this PC after you confirm. It stays off until you turn the detector on in Settings."
        )
        silero.clicked.connect(lambda: self.notice.emit("INSTALL silero"))
        layout.addWidget(silero)

        note = QLabel(
            "Kokoro, Windows voices, and an optional Azure voice are engines behind one slot. "
            "The natural voices copy a narrator, or your own voice if you record it here; nobody else's. Azure stays off: if you turn it on later, the text of every spoken reply would be sent to Microsoft."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        windows = QLabel(
            "Want the Australian Windows voices? Settings → Time & language → Speech → Add voices → English (Australia). Restart BabySitter and they can be chosen here."
        )
        windows.setWordWrap(True)
        windows.setObjectName("hint")
        layout.addWidget(windows)
        speed_title = QLabel("Responsiveness")
        speed_title.setObjectName("section")
        layout.addWidget(speed_title)
        self.responsiveness = QLabel("No voice turns measured yet. Only timings are kept. No words are stored.")
        self.responsiveness.setWordWrap(True)
        self.responsiveness.setObjectName("hint")
        layout.addWidget(self.responsiveness)
        export = QPushButton("Export diagnostics")
        export.setToolTip("Saves the timings on this PC. It does not include what you said.")
        export.clicked.connect(lambda: self.notice.emit("EXPORT timings"))
        layout.addWidget(export)
        layout.addStretch(1)
        self.load_saved()

    def set_responsiveness(self, text: str) -> None:
        self.responsiveness.setText(text)

    def _slider(self, label: str, low: int, high: int, value: int):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Horizontal)
        slider.setAccessibleName(label)
        slider.setRange(low, high)
        slider.setValue(value)
        shown = QLabel(str(value))
        slider.valueChanged.connect(lambda number, box=shown: box.setText(str(number)))
        row.addWidget(slider, 1)
        row.addWidget(shown)
        return host, slider

    def _pin_voice(self) -> None:
        text = self.voice.currentText().strip()
        if text:
            self.pin_line.emit(text)

    def load_saved(self) -> None:
        """Sync the dropdown and sliders with voice.json when it exists."""
        path = data_dir() / "voice.json"
        if not path.is_file():
            return
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(saved, dict):
            return
        voice_name = str(saved.get("voice") or "")
        if voice_name:
            index = self.voice.findData(voice_name)
            if index >= 0:
                self.voice.setCurrentIndex(index)
        if saved.get("speed") is not None:
            try:
                self.speed[1].setValue(int(saved["speed"]))
            except (TypeError, ValueError):
                pass
        if saved.get("pitch") is not None:
            try:
                self.pitch[1].setValue(int(saved["pitch"]))
            except (TypeError, ValueError):
                pass

    def _filter_voices(self, text: str) -> None:
        """Show only the voices whose line has every word typed."""
        words = text.lower().split()
        view = self.voice.view()
        first = -1
        for index in range(self.voice.count()):
            shown = all(word in self.voice.itemText(index).lower() for word in words)
            view.setRowHidden(index, not shown)
            if shown and first < 0:
                first = index
        if first >= 0 and view.isRowHidden(self.voice.currentIndex()):
            self.voice.setCurrentIndex(first)

    def _selected_is_cloud_off(self) -> bool:
        return "Cloud, off" in self.voice.currentText()

    def _save_sliders(self) -> None:
        if self._selected_is_cloud_off():
            return
        path = data_dir() / "voice.json"
        voice_name = self.voice.currentData()
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and existing.get("voice"):
                    voice_name = existing["voice"]
            except (OSError, json.JSONDecodeError):
                pass
        payload = {
            "voice": voice_name,
            "speed": self.speed[1].value(),
            "pitch": self.pitch[1].value(),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.status.setText(
            f"Saved {payload['voice']} (speed {payload['speed']}, pitch {payload['pitch']}) on this PC."
        )
        self.notice.emit(self.status.text())

    def _use(self) -> None:
        if self._selected_is_cloud_off():
            choice = self.voice.currentData() or "That voice"
            self.status.setText(
                f"{choice} is a cloud voice and stays off so your words stay on this PC. "
                "Choose a local Kokoro or Windows voice."
            )
            self.notice.emit(self.status.text())
            return
        payload = {
            "voice": self.voice.currentData(),
            "speed": self.speed[1].value(),
            "pitch": self.pitch[1].value(),
        }
        path = data_dir() / "voice.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.status.setText(
            f"Saved {payload['voice']} on this PC. Preview uses that voice. "
            "The first time, BabySitter asks before downloading it."
        )
        from babysitter.plugins.voice.engines import EXTRA_VOICES, is_natural, voice_ready

        name = str(payload["voice"] or "")
        self.voice_saved.emit(name)
        if name in EXTRA_VOICES and not voice_ready(name):
            if EXTRA_VOICES[name][1] == "own":
                self.pack_needed.emit("own")
            else:
                self.pack_needed.emit("natural" if is_natural(name) else EXTRA_VOICES[name][0])
        self.notice.emit(self.status.text())

    def _preview(self) -> None:
        self.notice.emit("PREVIEW voice")

    def _saved_line(self) -> str:
        path = data_dir() / "voice.json"
        if not path.is_file():
            return "No voice saved yet. The suggested start is Heart and Sarah, speed 1.05, pitch −1."
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "The saved voice file could not be read. Choose the voice again."
        return f"Saved voice: {saved.get('voice', 'unknown')}."
