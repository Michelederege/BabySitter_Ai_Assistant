"""A row of buttons that wraps onto the next line instead of pushing the page wider.

v3 reflows down to a 420 px window. A fixed row of five buttons is wider
than that, so the page scrolled sideways. FlowLayout is Qt's standard flow
layout; wrap_wide_rows swaps any wide row of controls for one, in place.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QLineEdit, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            # A text box takes the whole line, so it stays usable.
            wants_line = isinstance(item.widget(), QLineEdit)
            width = rect.width() if wants_line else min(hint.width(), rect.width())
            if x > rect.x() and (x + width > rect.right() + 1 or wants_line):
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x += width + gap
            line = max(line, hint.height())
            if wants_line:
                x, y, line = rect.x(), y + line + gap, 0
        return y + line - rect.y()


def _parent_layout(layout: QLayout, root: QWidget):
    for candidate in [root.layout(), *root.findChildren(QLayout)]:
        if candidate is None:
            continue
        for index in range(candidate.count()):
            if candidate.itemAt(index).layout() is layout:
                return candidate, index
    return None, -1


def wrap_wide_rows(root: QWidget, threshold: int = 300) -> int:
    """Swap each row of controls wider than `threshold` for a wrapping one."""
    swapped = 0
    for row in list(root.findChildren(QHBoxLayout)):
        if row.minimumSize().width() <= threshold:
            continue
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        if not widgets or any(w is None for w in widgets if w is not None) or not all(
            w is None or isinstance(w, QWidget) for w in widgets
        ):
            continue
        if any(row.itemAt(i).layout() is not None for i in range(row.count())):
            continue
        parent, index = _parent_layout(row, root)
        if parent is None or not hasattr(parent, "insertWidget"):
            continue
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        flow = FlowLayout(host)
        for widget in widgets:
            if widget is not None:
                row.removeWidget(widget)
                flow.addWidget(widget)
        parent.takeAt(index)
        parent.insertWidget(index, host)
        swapped += 1
    return swapped
