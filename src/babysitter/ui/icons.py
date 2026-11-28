"""Line icons for the v3 window, drawn in code.

The design uses thin outline icons (a mic for Talk, a pin for Board, a
calendar for Today ...). Drawing them here keeps them sharp at any scale,
needs no image files in the exe, and costs one small pixmap per icon per
colour, cached.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap

MUTED = "#a3aec5"
TEXT = "#e8ecf4"
INK = "#2a1606"


def _draw(name: str, p: QPainter, s: float) -> None:
    """Each icon on a 24-unit grid, scaled to s."""
    k = s / 24.0

    def pt(x, y):
        return QPointF(x * k, y * k)

    def rect(x, y, w, h):
        return QRectF(x * k, y * k, w * k, h * k)

    path = QPainterPath()
    if name == "mic":
        p.drawRoundedRect(rect(9, 3, 6, 11), 3 * k, 3 * k)
        path.moveTo(pt(5.5, 11))
        path.cubicTo(pt(5.5, 15.5), pt(8.5, 17.5), pt(12, 17.5))
        path.cubicTo(pt(15.5, 17.5), pt(18.5, 15.5), pt(18.5, 11))
        p.drawPath(path)
        p.drawLine(pt(12, 17.5), pt(12, 21))
    elif name == "pin":
        path.moveTo(pt(9, 3))
        path.lineTo(pt(15, 3))
        path.moveTo(pt(10, 3))
        path.lineTo(pt(10, 9))
        path.lineTo(pt(7, 13))
        path.lineTo(pt(17, 13))
        path.lineTo(pt(14, 9))
        path.lineTo(pt(14, 3))
        p.drawPath(path)
        p.drawLine(pt(12, 13), pt(12, 21))
    elif name == "calendar":
        p.drawRoundedRect(rect(4, 5, 16, 15), 2 * k, 2 * k)
        p.drawLine(pt(4, 10), pt(20, 10))
        p.drawLine(pt(8, 3), pt(8, 7))
        p.drawLine(pt(16, 3), pt(16, 7))
    elif name == "pencil":
        path.moveTo(pt(15.5, 4.5))
        path.lineTo(pt(19.5, 8.5))
        path.lineTo(pt(9, 19))
        path.lineTo(pt(4.5, 19.5))
        path.lineTo(pt(5, 15))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(pt(13.5, 6.5), pt(17.5, 10.5))
    elif name == "book":
        path.moveTo(pt(6, 4))
        path.lineTo(pt(18, 4))
        path.lineTo(pt(18, 20))
        path.lineTo(pt(7.5, 20))
        path.cubicTo(pt(6.5, 20), pt(6, 19.3), pt(6, 18.5))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(pt(6, 17), pt(18, 17))
    elif name == "sliders":
        for y, x in ((7, 15), (12, 8), (17, 13)):
            p.drawLine(pt(4, y), pt(20, y))
            p.drawLine(pt(x, y - 2.5), pt(x, y + 2.5))
    elif name == "stop":
        p.setBrush(p.pen().color())
        p.drawRoundedRect(rect(7, 7, 10, 10), 1.5 * k, 1.5 * k)
    elif name == "lock":
        p.drawRoundedRect(rect(5.5, 11, 13, 9), 2 * k, 2 * k)
        path.moveTo(pt(8.5, 11))
        path.lineTo(pt(8.5, 8))
        path.cubicTo(pt(8.5, 3.5), pt(15.5, 3.5), pt(15.5, 8))
        path.lineTo(pt(15.5, 11))
        p.drawPath(path)
    elif name == "bell":
        path.moveTo(pt(6, 16.5))
        path.lineTo(pt(6, 11))
        path.cubicTo(pt(6, 7), pt(8.7, 4.5), pt(12, 4.5))
        path.cubicTo(pt(15.3, 4.5), pt(18, 7), pt(18, 11))
        path.lineTo(pt(18, 16.5))
        path.lineTo(pt(19.5, 18))
        path.lineTo(pt(4.5, 18))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(pt(10.5, 20.5), pt(13.5, 20.5))
    elif name == "minimize":
        p.drawLine(pt(6, 12), pt(18, 12))
    elif name == "maximize":
        p.drawRect(rect(6.5, 6.5, 11, 11))
    elif name == "restore":
        p.drawRect(rect(6, 9, 9, 9))
        path.moveTo(pt(9, 9))
        path.lineTo(pt(9, 6))
        path.lineTo(pt(18, 6))
        path.lineTo(pt(18, 15))
        path.lineTo(pt(15, 15))
        p.drawPath(path)
    elif name == "close":
        p.drawLine(pt(6.5, 6.5), pt(17.5, 17.5))
        p.drawLine(pt(17.5, 6.5), pt(6.5, 17.5))
    elif name == "chevron_down":
        path.moveTo(pt(7, 10))
        path.lineTo(pt(12, 15))
        path.lineTo(pt(17, 10))
        p.drawPath(path)
    elif name == "chevron_up":
        path.moveTo(pt(7, 14))
        path.lineTo(pt(12, 9))
        path.lineTo(pt(17, 14))
        p.drawPath(path)
    elif name == "copy":
        p.drawRoundedRect(rect(8.5, 8.5, 11, 11), 2 * k, 2 * k)
        path.moveTo(pt(5.5, 15.5))
        path.lineTo(pt(4.5, 15.5))
        path.lineTo(pt(4.5, 4.5))
        path.lineTo(pt(15.5, 4.5))
        path.lineTo(pt(15.5, 5.5))
        p.drawPath(path)
    elif name == "refresh":
        p.drawArc(rect(5, 5, 14, 14), 100 * 16, 290 * 16)
        path.moveTo(pt(5, 4))
        path.lineTo(pt(5.5, 9))
        path.lineTo(pt(10, 8))
        p.drawPath(path)
    elif name == "arrow_right":
        p.drawLine(pt(5, 12), pt(19, 12))
        path.moveTo(pt(13, 6))
        path.lineTo(pt(19, 12))
        path.lineTo(pt(13, 18))
        p.drawPath(path)
    elif name == "plus":
        p.drawLine(pt(12, 5), pt(12, 19))
        p.drawLine(pt(5, 12), pt(19, 12))
    elif name == "image":
        p.drawRoundedRect(rect(4, 5, 16, 14), 2 * k, 2 * k)
        p.drawEllipse(rect(8, 8, 3, 3))
        path.moveTo(pt(4.5, 17))
        path.lineTo(pt(10, 12.5))
        path.lineTo(pt(13.5, 15.5))
        path.lineTo(pt(16, 13.5))
        path.lineTo(pt(19.5, 16.5))
        p.drawPath(path)


NAMES = (
    "mic", "pin", "calendar", "pencil", "book", "sliders", "stop", "lock", "bell", "minimize", "maximize",
    "restore", "close", "chevron_down", "chevron_up", "copy", "refresh", "arrow_right", "plus", "image",
)


@lru_cache(maxsize=128)
def pixmap(name: str, color: str = MUTED, size: int = 20, width: float = 1.7) -> QPixmap:
    """One icon, drawn at the screen's pixel ratio so it stays crisp."""
    app = QGuiApplication.instance()
    ratio = 1.0
    if app is not None:
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
    pix = QPixmap(int(size * ratio), int(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(width * size / 20.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _draw(name, painter, float(size))
    painter.end()
    return pix


def icon(name: str, color: str = MUTED, active: str | None = None, size: int = 20) -> QIcon:
    """An icon with a brighter version for hover, checked and active states."""
    result = QIcon()
    result.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    bright = pixmap(name, active or TEXT, size)
    result.addPixmap(bright, QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(bright, QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(bright, QIcon.Mode.Active, QIcon.State.On)
    return result
