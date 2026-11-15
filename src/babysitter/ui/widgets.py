"""The big power button and the status cards."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from babysitter.ui.theme import STATE_COLORS


class PowerButton(QPushButton):
    def __init__(self) -> None:
        super().__init__()
        self.state = "off"
        self._phase = 0
        self.setFixedSize(64, 64)
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
        dark_text = self.state in {"starting", "on", "listening", "thinking", "speaking"}
        ink = QColor("#1a1404") if dark_text else QColor("#f7fafc")
        painter.setBrush(ink)
        stem = rect.adjusted(rect.width() // 2 - 2, 6, -(rect.width() // 2 - 2), -(rect.height() // 2) + 4)
        painter.drawRoundedRect(stem, 2, 2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(ink, max(3, rect.width() // 12), Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(rect.adjusted(6, 6, -6, -6), 50 * 16, 280 * 16)


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


class Sparkline(QWidget):
    """Orange line of the last two minutes. One point is added every refresh."""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[float] = []
        self.setMinimumHeight(42)
        self.setMinimumWidth(120)

    def push(self, value: float) -> None:
        self.values.append(value)
        del self.values[:-60]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if len(self.values) < 2:
            return
        width = max(1, self.width() - 4)
        height = max(1, self.height() - 4)
        low = min(self.values)
        high = max(self.values)
        span = high - low or 1
        painter.setPen(QPen(QColor("#f5a54a"), 2))
        previous = None
        for index, value in enumerate(self.values):
            x = 2 + width * index / (len(self.values) - 1)
            y = 2 + height * (1 - (value - low) / span)
            if previous is not None:
                painter.drawLine(previous[0], previous[1], x, y)
            previous = (x, y)


class BarChart(QWidget):
    """Orange bars for the video-memory samples kept on screen."""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[float] = []
        self.setMinimumHeight(92)

    def set_values(self, values: list[float]) -> None:
        self.values = list(values[-40:])
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.values:
            return
        high = max(self.values) or 1
        count = len(self.values)
        gap = 2
        bar_width = max(2, (self.width() - gap * count) / count)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#f5a54a"))
        for index, value in enumerate(self.values):
            height = max(2, self.height() * (value / high))
            painter.drawRoundedRect(
                int(index * (bar_width + gap)),
                int(self.height() - height),
                int(bar_width),
                int(height),
                2,
                2,
            )
