"""A small pin button for any list on the tabs.

The picture is drawn here so it does not depend on an emoji font.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QWidget


def pin_icon() -> QIcon:
    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#e7b008"), 1.6))
    painter.setBrush(QColor("#e7b008"))
    painter.drawEllipse(4, 1, 10, 10)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(9, 10, 9, 16)
    painter.drawLine(6, 16, 12, 16)
    painter.end()
    return QIcon(pixmap)


def pin_button() -> QPushButton:
    button = QPushButton()
    button.setObjectName("pinIcon")
    button.setIcon(pin_icon())
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(28, 28)
    button.setToolTip("Pin this on the board. It stays on this PC.")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def fill_pinned_list(widget: QListWidget, rows: list[tuple[str, str]], on_pin) -> None:
    """Show each line with a pin. The item text stays set for selection.

    rows are (shown text, id). An empty id means the row cannot be removed by id.
    """
    widget.clear()
    for text, item_id in rows:
        shown = " ".join((text or "").split())
        if not shown:
            continue
        item = QListWidgetItem(shown)
        if item_id:
            item.setData(Qt.ItemDataRole.UserRole, item_id)
        item.setSizeHint(QSize(0, 40))
        widget.addItem(item)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(6)
        label = QLabel(shown)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        button = pin_button()
        button.clicked.connect(lambda _checked=False, line=shown: on_pin(line))
        layout.addWidget(label, 1)
        layout.addWidget(button)
        widget.setItemWidget(item, row)
