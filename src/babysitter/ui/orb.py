"""The floating frog orb.

A frameless, see-through widget that plays the frog sprite strips from
the assets folder. A plain click opens the window; a drag only moves it
and never opens anything. Right-click (or the Menu key, or Shift+F10)
asks for the orb menu. The colored ring in the drawing is the state
color, and a short caption sits in a dark pill under the frog, never
over it. The frog never draws inside a game: the shell hides the whole
orb while a watched game is in front.
"""

from __future__ import annotations

import json
import sys

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from babysitter.paths import asset_path
from babysitter.ui.theme import CAPTIONS, ORB_SPRITES, STATE_COLORS

FROG_SIZE = 84
MAX_CAPTION = 42


def _animations_wanted() -> bool:
    """Follow the Windows "Show animations" setting. Elsewhere, animate."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        value = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(value), 0
        )
        return bool(value.value)
    except Exception:
        return True


def _load_sprites() -> tuple[dict, int, int]:
    """Read the sprite strips. Returns ({state: (pixmap, frames)}, frame_px, fps)."""
    folder = asset_path("orb")
    meta_path = folder / "sprites.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        frame_px = int(meta["frameSize"])
        fps = int(meta["fps"])
        strips: dict[str, tuple[QPixmap, int]] = {}
        for state, info in meta["states"].items():
            pixmap = QPixmap(str(folder / str(info["file"])))
            if pixmap.isNull():
                return {}, 0, 0
            strips[state] = (pixmap, int(info["frames"]))
        return strips, frame_px, fps
    except Exception:
        return {}, 0, 0


class Orb(QWidget):
    clicked = Signal()
    menu_requested = Signal(object)
    moved = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.state = "off"
        self._detail = "The AI is off."
        self._caption = CAPTIONS["off"]
        self._press = None
        self._origin = None
        self._moved = False
        self._frame = 0
        self._strips, self._frame_px, self._fps = _load_sprites()
        self.setWindowTitle("BabySitter")
        self.setFixedSize(200, FROG_SIZE + 34)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background: transparent;")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.OpenHandCursor)
        self._caption_font = QFont("Inter", 9, QFont.DemiBold)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        if self._strips and _animations_wanted():
            self._timer.start(int(1000 / max(1, self._fps)))
        self._update_accessible()

    # ---------- public API (same as the old orb) ----------
    def set_always_on_top(self, enabled: bool) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.NoDropShadowWindowHint
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        position = self.pos()
        self.setWindowFlags(flags)
        self.move(position)
        self.show()

    def set_state(self, state: str, detail: str) -> None:
        state = state if state in STATE_COLORS else "error"
        if state != self.state:
            self._frame = 0
        self.state = state
        self._detail = detail
        clean = " ".join(str(detail or "").split())
        if clean and len(clean) <= MAX_CAPTION:
            self._caption = clean.rstrip(".")
        else:
            self._caption = CAPTIONS.get(state, "Needs you")
        self.setToolTip(detail)
        self._update_accessible()
        self.update()

    # ---------- internals ----------
    def _update_accessible(self) -> None:
        from babysitter.ui.theme import STATE_WORDS

        self.setAccessibleName(f"BabySitter: {STATE_WORDS.get(self.state, 'Needs you')}. {self._caption}")

    def _tick(self) -> None:
        strip = self._strips.get(ORB_SPRITES.get(self.state, "needs"))
        if strip is None:
            return
        self._frame = (self._frame + 1) % strip[1]
        self.update()

    def _frog_rect(self) -> QRect:
        return QRect((self.width() - FROG_SIZE) // 2, 0, FROG_SIZE, FROG_SIZE)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        sprite = self._strips.get(ORB_SPRITES.get(self.state, "needs"))
        if sprite is not None:
            pixmap, frames = sprite
            frame = self._frame % max(1, frames)
            src = QRect(frame * self._frame_px, 0, self._frame_px, self._frame_px)
            painter.drawPixmap(self._frog_rect(), pixmap, src)
        else:
            # No sprites on disk: fall back to the plain colored light.
            color = QColor(STATE_COLORS[self.state])
            glow = QColor(color)
            glow.setAlpha(80)
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(self._frog_rect())
            painter.setBrush(color)
            painter.drawEllipse(self._frog_rect().adjusted(10, 10, -10, -10))
        # Caption pill under the frog, never over it.
        painter.setFont(self._caption_font)
        metrics = QFontMetrics(self._caption_font)
        text = metrics.elidedText(self._caption, Qt.ElideRight, self.width() - 24)
        width = metrics.horizontalAdvance(text) + 20
        height = metrics.height() + 6
        pill = QRect((self.width() - width) // 2, FROG_SIZE + 4, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(14, 18, 30, 214))
        painter.drawRoundedRect(pill, height / 2, height / 2)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill, Qt.AlignCenter, text)
        painter.end()

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
        if not self._moved and delta.manhattanLength() >= QApplication.startDragDistance():
            self._moved = True
            self.setCursor(Qt.ClosedHandCursor)
        if self._moved:
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if not self._moved:
                self.clicked.emit()
            else:
                self.moved.emit(self.x(), self.y())
        self._press = None
        self._moved = False
        self.setCursor(Qt.OpenHandCursor)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        elif event.key() == Qt.Key_Menu or (
            event.key() == Qt.Key_F10 and event.modifiers() & Qt.ShiftModifier
        ):
            self.menu_requested.emit(self.mapToGlobal(self._frog_rect().center()))
        else:
            super().keyPressEvent(event)
