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


def pin_button(accessible_name: str = "Pin on board") -> QPushButton:
    button = QPushButton()
    button.setObjectName("pinIcon")
    button.setIcon(pin_icon())
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(28, 28)
    button.setAccessibleName(accessible_name)
    button.setToolTip("Pin this on the board. It stays on this PC.")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def list_width(widget: QListWidget) -> int:
    width = widget.viewport().width()
    cap = widget.maximumWidth()
    if 0 < cap < 16777215 and (width < 80 or cap < width):
        width = cap
    if width < 80:
        width = widget.width()
    return width


def fit_pinned_row(item: QListWidgetItem, label: QLabel, list_width: int) -> None:
    """Give a wrapped line enough height. A countdown no longer stops at 40 pixels."""
    width = list_width - 48
    if width < 80:
        width = 240
    rect = label.fontMetrics().boundingRect(
        0, 0, width, 2000, int(Qt.TextFlag.TextWordWrap), label.text()
    )
    item.setSizeHint(QSize(0, max(40, rect.height() + 12)))


def fill_pinned_list(widget: QListWidget, rows: list[tuple], on_pin) -> None:
    """Show each line with a pin. The item text stays set for selection.

    rows are (shown text, id) or (shown text, id, pin text).
    An empty id means the row cannot be removed by id.
    The pin text stays put while the shown text changes, such as a countdown.
    """
    widget.clear()
    for row_values in rows:
        text = row_values[0]
        item_id = row_values[1] if len(row_values) > 1 else ""
        pin_text = row_values[2] if len(row_values) > 2 else text
        shown = " ".join((text or "").split())
        pinned = " ".join((pin_text or shown).split())
        if not shown:
            continue
        item = QListWidgetItem(shown)
        item.setForeground(QColor(0, 0, 0, 0))
        if item_id:
            item.setData(Qt.ItemDataRole.UserRole, item_id)
        widget.addItem(item)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(6)
        label = QLabel(shown)
        label.setObjectName("pinnedLine")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        button = pin_button(f"Pin: {pinned[:60]}")
        button.clicked.connect(lambda _checked=False, line=pinned: on_pin(line))
        layout.addWidget(label, 1)
        layout.addWidget(button)
        widget.setItemWidget(item, row)
        fit_pinned_row(item, label, list_width(widget))
