"""How BabySitter will sound, and how it hears you.

The controls save your choices. Speaking them out loud waits until a
voice engine is installed. There is no voice cloning.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from babysitter.paths import data_dir


VOICES = (
    ("American", "Heart & Sarah blend", "Kokoro", "Local"),
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


class VoicePage(QWidget):
    notice = Signal(str)

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

        self.voice = QComboBox()
        for accent, name, engine, where in VOICES:
            self.voice.addItem(f"{accent} · {name} · {engine} · {where}", name)
        self.voice.setToolTip("Pick a voice. Australian Windows voices have to be added in Windows first.")
        layout.addWidget(self.voice)

        use = QPushButton("Use this voice")
        use.setToolTip("Saves the choice on this PC. It does not download a voice by itself.")
        use.clicked.connect(self._use)
        layout.addWidget(use)

        self.speed = self._slider("Speed", 80, 130, 105)
        self.pitch = self._slider("Pitch", -6, 6, -1)
        layout.addWidget(self.speed[0])
        layout.addWidget(self.pitch[0])

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

        note = QLabel(
            "Kokoro, Windows voices, and an optional Azure voice are engines behind one slot. "
            "Voice cloning is not supported. Azure stays off: if you turn it on later, the text of every spoken reply would be sent to Microsoft."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        windows = QLabel(
            "Want the Australian Windows voices? Settings → Time & language → Speech → Add voices → English (Australia). Restart BabySitter and they can be chosen here."
        )
        windows.setWordWrap(True)
        windows.setObjectName("hint")
        layout.addWidget(windows)
        layout.addStretch(1)

    def _slider(self, label: str, low: int, high: int, value: int):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(value)
        shown = QLabel(str(value))
        slider.valueChanged.connect(lambda number, box=shown: box.setText(str(number)))
        row.addWidget(slider, 1)
        row.addWidget(shown)
        return host, slider

    def _use(self) -> None:
        payload = {
            "voice": self.voice.currentData(),
            "speed": self.speed[1].value(),
            "pitch": self.pitch[1].value(),
        }
        path = data_dir() / "voice.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        self.status.setText(
            f"Saved {payload['voice']} on this PC. Preview uses that voice. "
            "The first time, BabySitter asks before downloading Heart and Sarah."
        )
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
