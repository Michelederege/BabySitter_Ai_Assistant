"""The frog-pond picture across the top of the Assistant panel.

The picture fills the width and is cropped to keep the frog in view.
Off is grey and dark. On keeps the colour, with a warm glow at the
top right. The frog, the state word, and the hint sit on the picture.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

PANEL = QColor("#2a3350")
# How grey the photo is, then how bright. Off is grey and dark.
LOOK = {
    "off": (0.85, 0.60),
    "needs": (0.50, 0.70),
    "working": (0.10, 0.92),
    "on": (0.10, 0.92),
    "game": (0.10, 0.92),
}
TINT = 0.32
# Keep this point of the photo in view. The frog sits left of centre.
FOCUS = (0.30, 0.55)

# App state -> the picture look, then the frog strip.
PICTURE = {
    "off": "off",
    "starting": "working",
    "on": "on",
    "listening": "on",
    "thinking": "on",
    "speaking": "on",
    "game": "game",
    "error": "needs",
}
FROG = {
    "off": "off",
    "starting": "working",
    "on": "on",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
    "game": "game",
    "error": "needs",
}


def picture_key(phase: str) -> str:
    return PICTURE.get(phase, "on")


def frog_key(phase: str) -> str:
    return FROG.get(phase, "on")


class FrogSprite(QWidget):
    """The same frog strips as the orb, drawn on the picture."""

    def __init__(self, sprites_dir: Path, size: int = 78, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("heroFrog")
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._px = 168
        self._strips: dict[str, tuple[QPixmap, int]] = {}
        self._state = "off"
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._load(Path(sprites_dir))

    def _load(self, folder: Path) -> None:
        meta_path = folder / "sprites.json"
        if not meta_path.is_file():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._px = int(meta["frameSize"])
        for state, info in meta["states"].items():
            pixmap = QPixmap(str(folder / info["file"]))
            if pixmap.isNull():
                continue
            self._strips[state] = (pixmap, int(info["frames"]))
        if self._strips:
            self._timer.start(int(1000 / int(meta["fps"])))

    def set_state(self, state: str) -> None:
        if state in self._strips and state != self._state:
            self._state = state
            self._frame = 0
            self.update()

    def set_reduced_motion(self, on: bool) -> None:
        if on:
            self._timer.stop()
            self._frame = 0
            self.update()
        elif self._strips and not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        frames = self._strips[self._state][1]
        self._frame = (self._frame + 1) % frames
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        strip = self._strips.get(self._state)
        if strip is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pixmap, _frames = strip
        source = QRectF(self._frame * self._px, 0, self._px, self._px)
        painter.drawPixmap(self.rect(), pixmap, source.toRect())


class HeroBanner(QWidget):
    """A wide cropped photo with the frog and the state drawn on it."""

    def __init__(self, image_path, sprites_dir, radius: int = 8, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("heroBanner")
        self._radius = radius
        self._key = "off"
        self._cache: dict = {}
        self._old = None
        self._fade = 1.0
        self._focus = FOCUS
        blank = QImage(8, 8, QImage.Format.Format_RGB32)
        blank.fill(PANEL)
        self._img = blank
        self._gray = blank
        self.set_image(image_path)
        self.set_compact(False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self.frog = FrogSprite(sprites_dir, 78, self)
        self.word = QLabel("Off", self)
        self.word.setStyleSheet("color:#ffffff; font:700 20px 'Inter'; background:transparent;")
        self.hint = QLabel("The AI is off. Nothing is listening.", self)
        self.hint.setStyleSheet("color:#e8ecf4; font:12px 'Inter'; background:transparent;")
        self.hint.setWordWrap(True)
        for label in (self.word, self.hint):
            shadow = QGraphicsDropShadowEffect(label)
            shadow.setBlurRadius(10)
            shadow.setOffset(0, 1)
            shadow.setColor(QColor(0, 0, 0, 160))
            label.setGraphicsEffect(shadow)
        words = QVBoxLayout()
        words.setSpacing(1)
        words.setContentsMargins(0, 0, 0, 0)
        words.addStretch(1)
        words.addWidget(self.word)
        words.addWidget(self.hint)
        words.addStretch(1)
        self._overlay = QWidget(self)
        self._overlay.setObjectName("heroOverlay")
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(self._overlay)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self.frog)
        row.addLayout(words, 1)
        self._corner = None

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(600)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.valueChanged.connect(self._on_fade)

    def set_image(self, path, focus=FOCUS) -> bool:
        """Use another picture. A file that will not open leaves the current one."""
        image = QImage(str(path))
        if image.isNull():
            return False
        self._img = image.convertToFormat(QImage.Format.Format_RGB32)
        self._gray = self._img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
            QImage.Format.Format_RGB32
        )
        self._focus = focus
        self._cache.clear()
        self._old = None
        self.update()
        return True

    def set_state(self, key: str, word: str, hint: str) -> None:
        """key is off, working, on, game, or needs. The frog follows unless set_frog says otherwise."""
        key = key if key in LOOK else "on"
        self.word.setText(word)
        self.hint.setText(hint)
        self.frog.set_state(key)
        if key != self._key:
            self._old = self._background()
            self._key = key
            self._anim.stop()
            self._anim.start()
        self.update()

    def set_frog(self, frog_state: str) -> None:
        self.frog.set_state(frog_state)

    def show_phase(self, phase: str, word: str, hint: str) -> None:
        """One app state. Listening keeps the On picture and changes the frog."""
        self.set_state(picture_key(phase), word, hint)
        self.set_frog(frog_key(phase))

    def set_corner_widget(self, widget) -> None:
        """A button in the top-right corner, over the picture."""
        self._corner = widget
        widget.setParent(self)
        widget.show()
        self._place()

    def set_compact(self, compact: bool) -> None:
        """Half screen is a little taller, so the frog still has room."""
        self.setFixedHeight(170 if compact else 150)

    def set_reduced_motion(self, on: bool) -> None:
        self.frog.set_reduced_motion(on)
        self._anim.setDuration(0 if on else 600)

    def _on_fade(self, value) -> None:
        self._fade = float(value)
        if self._fade >= 1.0:
            self._old = None
        self.update()

    def _background(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        width, height = max(1, self.width()), max(1, self.height())
        key = (width, height, round(dpr, 2), self._key)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        pixel_w, pixel_h = int(width * dpr), int(height * dpr)
        gray_amount, bright = LOOK[self._key]

        def cover(src: QImage) -> QImage:
            scaled = src.scaled(
                pixel_w,
                pixel_h,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = int((scaled.width() - pixel_w) * self._focus[0])
            y = int((scaled.height() - pixel_h) * self._focus[1])
            x = max(0, min(x, max(0, scaled.width() - pixel_w)))
            y = max(0, min(y, max(0, scaled.height() - pixel_h)))
            return scaled.copy(x, y, pixel_w, pixel_h)

        color, gray = cover(self._img), cover(self._gray)
        out = QImage(pixel_w, pixel_h, QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(PANEL)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawImage(0, 0, color)
        painter.setOpacity(1 - (1 - gray_amount) * (1 - TINT))
        painter.drawImage(0, 0, gray)
        painter.setOpacity(1)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.fillRect(out.rect(), QColor(241, 248, 255))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.fillRect(out.rect(), QColor(0, 0, 15))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setOpacity(1 - bright)
        painter.fillRect(out.rect(), Qt.GlobalColor.black)
        painter.setOpacity(1)
        glow = QRadialGradient(QPointF(0, 0), 1.0)
        glow.setColorAt(0.0, QColor(247, 176, 98, 166))
        glow.setColorAt(0.7, QColor(247, 176, 98, 0))
        brush = QBrush(glow)
        brush.setTransform(
            QTransform()
            .translate(pixel_w * 0.82, pixel_h * 0.10)
            .scale(pixel_w * 0.60, pixel_h * 0.80)
        )
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
        painter.fillRect(out.rect(), brush)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        fade = QLinearGradient(0, 0, 0, pixel_h)
        fade.setColorAt(0.0, QColor(32, 40, 64, 51))
        fade.setColorAt(0.4, QColor(32, 40, 64, 0))
        fade.setColorAt(1.0, QColor(42, 51, 80, 242))
        painter.fillRect(out.rect(), fade)
        painter.end()

        pixmap = QPixmap.fromImage(out)
        pixmap.setDevicePixelRatio(dpr)
        if len(self._cache) > 12:
            self._cache.clear()
        self._cache[key] = pixmap
        return pixmap

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), PANEL)
        radius, width, height = self._radius, self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height + radius), radius, radius)
        painter.setClipPath(path)
        if self._old is not None and self._fade < 1.0:
            painter.drawPixmap(0, 0, self._old)
            painter.setOpacity(self._fade)
        painter.drawPixmap(0, 0, self._background())
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        self._overlay.setGeometry(14, self.height() - 10 - 78, max(0, self.width() - 28), 78)
        if self._corner is not None:
            self._corner.adjustSize()
            self._corner.move(self.width() - self._corner.width() - 10, 10)
