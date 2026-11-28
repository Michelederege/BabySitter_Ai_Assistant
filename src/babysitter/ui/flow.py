"""A row of buttons that wraps onto the next line instead of pushing the page wider.

v3 reflows down to a 420 px window. A fixed row of five buttons is wider
than that, so the page scrolled sideways. FlowLayout is Qt's standard flow
layout; wrap_wide_rows swaps any wide row of controls for one, in place.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLayout, QLineEdit, QSizePolicy, QWidget


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
        owner = row.parentWidget()
        if owner is not None and owner.property("noWrap"):
            continue  # a row laid out on purpose, like the talk bar
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
        host.setObjectName("flowHost")
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


def fit_list(widget, max_rows: int = 10) -> None:
    """A list as tall as its rows (up to max_rows), so a short list leaves no empty box."""
    widget.setWordWrap(True)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rows = widget.count()
    if rows == 0:
        widget.setFixedHeight(0)
        widget.hide()
        return
    widget.show()
    shown = min(rows, max_rows)
    height = sum(max(widget.sizeHintForRow(i), 20) for i in range(shown))
    frame = widget.frameWidth() * 2
    widget.setFixedHeight(height + frame + 6)


class WrapGrid(QWidget):
    """Cards in as many columns as fit, never a fixed two columns."""

    def __init__(self, min_column: int = 360) -> None:
        super().__init__()
        self._min = min_column
        self._items: list[QWidget] = []
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(14)

    def clear(self) -> None:
        for item in self._items:
            self._grid.removeWidget(item)
            item.deleteLater()
        self._items = []
        self._columns = 0

    def add(self, widget: QWidget) -> None:
        self._items.append(widget)
        self._columns = 0
        self._reflow()

    def _reflow(self) -> None:
        columns = max(1, min(len(self._items) or 1, self.width() // self._min if self.width() > 0 else 1))
        if columns == self._columns:
            return
        self._columns = columns
        for item in self._items:
            self._grid.removeWidget(item)
        for index, item in enumerate(self._items):
            self._grid.addWidget(item, index // columns, index % columns, Qt.AlignTop)
        for column in range(4):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow()
