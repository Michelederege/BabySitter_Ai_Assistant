"""The big power button and the status cards."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton, QVBoxLayout

from babysitter.ui.theme import STATE_COLORS, STATE_WORDS


class PowerButton(QPushButton):
    def __init__(self) -> None:
        super().__init__()
        self.state = "off"
        self._phase = 0
        self.setFixedSize(188, 188)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("AI power")
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(50)

    def set_state(self, state: str) -> None:
        self.state = state if state in STATE_COLORS else "error"
        self.update()

    def _tick(self) -> None:
        if self.state == "starting":
            self._phase = (self._phase + 1) % 30
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(STATE_COLORS[self.state])
        rect = self.rect().adjusted(10, 10, -10, -10)
        painter.setPen(Qt.NoPen)
        glow = QColor(color)
        if self.state == "starting":
            glow.setAlpha(50 + int(18 * abs(self._phase - 15)))
        else:
            glow.setAlpha(60)
        painter.setBrush(glow)
        painter.drawEllipse(rect.adjusted(-6, -6, 6, 6))
        painter.setBrush(color)
        painter.drawEllipse(rect)
        dark_text = self.state in {"starting", "on"}
        painter.setPen(QColor("#1a1404") if dark_text else QColor("#f7fafc"))
        font = QFont(painter.font())
        font.setPixelSize(32)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, STATE_WORDS[self.state])


class Card(QFrame):
    def __init__(self, title: str, tooltip: str) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setToolTip(tooltip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        self.title = QLabel(title)
        self.title.setObjectName("section")
        self.body = QLabel("Checking…")
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setToolTip(tooltip)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addWidget(self.bar)

    def set_text(self, text: str, percent: int | None = None) -> None:
        self.body.setText(text)
        if percent is None:
            self.bar.hide()
        else:
            self.bar.show()
            self.bar.setValue(max(0, min(100, percent)))
