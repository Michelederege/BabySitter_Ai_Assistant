"""The small floating light.

Click it to open Home. Drag it to move it. Right-click for the same
power commands as the tray icon. The color is the assistant's state.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel, QVBoxLayout, QWidget

from babysitter.ui.theme import CAPTIONS, STATE_COLORS


class Orb(QWidget):
    clicked = Signal()
    menu_requested = Signal(object)
    moved = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.state = "off"
        self._detail = "The AI is off."
        self._press = None
        self._origin = None
        self._moved = False
        self._caption_generation = 0
        self.setWindowTitle("BabySitter")
        self.setFixedSize(200, 168)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 92, 8, 8)
        self.caption = QLabel(CAPTIONS["off"])
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.caption.setStyleSheet(
            "background: rgba(12, 14, 18, 220); color: #f4f7fb; "
            "border-radius: 10px; padding: 4px 8px; font-size: 13px;"
        )
        layout.addWidget(self.caption)
        self._effect = QGraphicsOpacityEffect(self.caption)
        self._effect.setOpacity(1.0)
        self.caption.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(700)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        self.setToolTip(self._detail)

    def set_always_on_top(self, enabled: bool) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        position = self.pos()
        self.setWindowFlags(flags)
        self.move(position)
        self.show()

    def set_state(self, state: str, detail: str) -> None:
        self.state = state if state in STATE_COLORS else "error"
        self._detail = detail
        self.caption.setText(CAPTIONS.get(self.state, "Needs attention"))
        self.setToolTip(detail)
        self._effect.setOpacity(1.0)
        self._fade.stop()
        self.update()
        self._caption_generation += 1
        generation = self._caption_generation
        if self.state != "error":
            self._fade.setStartValue(1.0)
            self._fade.setEndValue(0.0)
            # Show the word, then let it fade. The color stays.
            QTimer.singleShot(5000, lambda gen=generation: self._start_fade(gen))

    def _start_fade(self, generation: int) -> None:
        if generation != self._caption_generation or self.state == "error":
            return
        self._fade.start()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(STATE_COLORS[self.state])
        painter.setPen(Qt.NoPen)
        glow = QColor(color)
        glow.setAlpha(80)
        painter.setBrush(glow)
        painter.drawEllipse(54, 8, 92, 92)
        painter.setBrush(color)
        painter.drawEllipse(64, 18, 72, 72)
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawEllipse(82, 30, 18, 12)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.frameGeometry().topLeft()
            self._moved = False
        elif event.button() == Qt.RightButton:
            self.menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        delta = event.globalPosition().toPoint() - self._press
        if delta.manhattanLength() > 6:
            self._moved = True
        self.move(self._origin + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if not self._moved:
                self.clicked.emit()
            else:
                self.moved.emit(self.x(), self.y())
        self._press = None
