"""A frameless window that resizes and moves like any normal Windows window.

From the v3 design package (babysitter-ui-v3/qt/frameless_window.py). It
resizes from every edge, moves by its title bar with Windows Snap still
working, maximizes on a title-bar double-click, remembers its size and
place, and says which size class it is in so pages can reflow.

The only change from the package: the size is kept in the BabySitter
folder, next to settings.json, not in the Windows registry.

Size classes, measured on the whole window:
    "wide"    more than 1000 px   side menu with labels
    "medium"  681 to 1000 px      side menu with icons only
    "narrow"  680 px or less      the menu becomes a bottom bar
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QAbstractButton, QLineEdit, QMainWindow, QWidget

MIN_W, MIN_H = 420, 520
GRIP = 6
WIDE_ABOVE, NARROW_AT_OR_BELOW = 1000, 680


def window_class(width: int) -> str:
    if width > WIDE_ABOVE:
        return "wide"
    if width > NARROW_AT_OR_BELOW:
        return "medium"
    return "narrow"


def content_class(width: int) -> str:
    """For a page's own width, not the window's."""
    if width > 900:
        return "roomy"
    if width > 560:
        return "single"
    return "compact"


def edges_at(pos: QPoint, w: int, h: int, grip: int = GRIP) -> Qt.Edges:
    edges = Qt.Edges()
    if pos.x() <= grip:
        edges |= Qt.LeftEdge
    elif pos.x() >= w - grip - 1:
        edges |= Qt.RightEdge
    if pos.y() <= grip:
        edges |= Qt.TopEdge
    elif pos.y() >= h - grip - 1:
        edges |= Qt.BottomEdge
    return edges


def _cursor_for(edges: Qt.Edges):
    left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
    top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
    if (left and top) or (right and bottom):
        return Qt.SizeFDiagCursor
    if (right and top) or (left and bottom):
        return Qt.SizeBDiagCursor
    if left or right:
        return Qt.SizeHorCursor
    if top or bottom:
        return Qt.SizeVerCursor
    return None


def _geometry_path():
    from babysitter.paths import data_dir

    return data_dir() / "window-geometry.bin"


class FramelessWindow(QMainWindow):
    sizeClassChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(MIN_W, MIN_H)
        self.setMouseTracking(True)
        self._title_bar: QWidget | None = None
        self._size_class: str | None = None
        if not self._restore_geometry():
            self.resize(1180, 800)
        self._apply_margins()

    def set_title_bar(self, bar: QWidget) -> None:
        """Dragging this widget moves the window; a double-click maximizes or restores."""
        self._title_bar = bar
        bar.installEventFilter(self)

    def size_class(self) -> str:
        return self._size_class or window_class(self.width())

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def save_geometry(self) -> None:
        try:
            _geometry_path().write_bytes(bytes(self.saveGeometry()))
        except OSError:
            pass

    def _restore_geometry(self) -> bool:
        try:
            raw = _geometry_path().read_bytes()
        except OSError:
            return False
        return bool(raw) and self.restoreGeometry(QByteArray(raw))

    def _apply_margins(self) -> None:
        # A thin border the window itself receives, so its edges can be
        # grabbed even where child widgets fill it. None when maximized.
        margin = 0 if self.isMaximized() else GRIP
        self.setContentsMargins(margin, margin, margin, margin)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self.isMaximized():
            cursor = _cursor_for(edges_at(event.position().toPoint(), self.width(), self.height()))
            if cursor is not None:
                self.setCursor(cursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edges = edges_at(event.position().toPoint(), self.width(), self.height())
            if edges and self.windowHandle() is not None:
                self.windowHandle().startSystemResize(edges)
                return
        super().mousePressEvent(event)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._title_bar:
            kind = event.type()
            if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and event.button() == Qt.LeftButton:
                child = obj.childAt(event.position().toPoint())
                if not isinstance(child, (QAbstractButton, QLineEdit)):
                    if kind == QEvent.MouseButtonDblClick:
                        self.toggle_maximized()
                        return True
                    if self.windowHandle() is not None:
                        self.windowHandle().startSystemMove()  # Windows Snap keeps working
                        return True
        return super().eventFilter(obj, event)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.WindowStateChange:
            self._apply_margins()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cls = window_class(self.width())
        if cls != self._size_class:
            self._size_class = cls
            self.sizeClassChanged.emit(cls)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.save_geometry()
        super().hideEvent(event)
