"""Draw the placeholder BS icon. Replace assets/icon.png and icon.ico with your design later.

Run from the repo root, after PySide6 is installed:

    python assets/make_icon.py
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets"


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    margin = size * 0.06
    rect = painter.viewport().adjusted(int(margin), int(margin), int(-margin), int(-margin))
    path = QPainterPath()
    radius = size * 0.22
    path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), radius, radius)
    painter.fillPath(path, QColor("#10141c"))
    orb = size * 0.62
    ox = (size - orb) / 2
    oy = size * 0.16
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#123f3a"))
    painter.drawEllipse(int(ox), int(oy), int(orb), int(orb))
    painter.setBrush(QColor("#2dd4bf"))
    painter.drawEllipse(int(ox + orb * 0.18), int(oy + orb * 0.18), int(orb * 0.64), int(orb * 0.64))
    painter.setPen(QColor("#06211e"))
    font = QFont("DejaVu Sans")
    font.setBold(True)
    font.setPixelSize(int(size * 0.28))
    painter.setFont(font)
    painter.drawText(image.rect().adjusted(0, int(size * 0.08), 0, 0), Qt.AlignCenter, "BS")
    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(images: list[QImage], path: Path) -> None:
    """A modern .ico that stores PNG frames. Windows 11 accepts this."""
    blobs = [png_bytes(image) for image in images]
    count = len(blobs)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    offset = 6 + 16 * count
    chunks = b""
    for image, blob in zip(images, blobs):
        width = 0 if image.width() >= 256 else image.width()
        height = 0 if image.height() >= 256 else image.height()
        entries += struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        chunks += blob
    path.write_bytes(header + entries + chunks)


def main() -> None:
    QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(size) for size in sizes]
    images[-1].save(str(OUT / "icon.png"), "PNG")
    write_ico(images, OUT / "icon.ico")
    print(f"Wrote {OUT / 'icon.png'} and {OUT / 'icon.ico'}")


if __name__ == "__main__":
    main()
