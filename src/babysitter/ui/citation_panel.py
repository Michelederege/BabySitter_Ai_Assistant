"""A small window with the citation, ready to copy, and every other style one click away."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from babysitter import citations as cites


def copy_rich(text: str) -> None:
    """Put a citation on the clipboard: rich text keeps the italics, plain text for everything else."""
    if QApplication.platformName() == "offscreen":
        # Qt's test-only screen crashes at exit holding rich clipboard data. Real Windows is fine.
        QApplication.clipboard().setText(cites.plain(text))
        return
    data = QMimeData()
    data.setText(cites.plain(text))
    data.setHtml("<br><br>".join(cites.rich(part).replace("\n", "<br>") for part in text.split("\n\n")))
    QApplication.clipboard().setMimeData(data)


class CitationPanel(QDialog):
    style_changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Citation")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(640, 360)
        self._source: cites.Source | None = None
        layout = QVBoxLayout(self)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Style"))
        self.style = QComboBox()
        self.style.setAccessibleName("Citation style")
        for key, label in cites.STYLES.items():
            self.style.addItem(label, key)
        self.style.addItem("Every style", "all")
        row.addWidget(self.style, 1)
        layout.addLayout(row)
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.setAccessibleName("Citation text")
        layout.addWidget(self.text, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.copy = QPushButton("Copy")
        self.copy.setToolTip("Copies it with the italics kept, for Word or Google Docs.")
        self.copy_plain = QPushButton("Copy as plain text")
        close = QPushButton("Close")
        buttons.addWidget(self.copy)
        buttons.addWidget(self.copy_plain)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.copy.clicked.connect(self._copy)
        self.copy_plain.clicked.connect(lambda: QApplication.clipboard().setText(cites.plain(self.clip_text())))
        close.clicked.connect(self.hide)
        self.style.activated.connect(lambda _i: self._render(str(self.style.currentData())))

    def show_source(self, source: cites.Source, style: str, note: str = "") -> str:
        """Show it, copy it, and return the text that was copied."""
        self._source = source
        index = self.style.findData(style)
        self.style.setCurrentIndex(max(0, index))
        self.title.setText(source.title or source.url)
        self.note.setText(note)
        self._render(style)
        text = self.clip_text()
        copy_rich(text)
        self.show()
        self.raise_()
        return text

    def clip_text(self) -> str:
        """What goes on the clipboard: one style is just its entry, ready to paste; every style keeps the labels."""
        if self._source is None:
            return ""
        style = str(self.style.currentData())
        return cites.every_style(self._source) if style == "all" else cites.cite(self._source, style)

    def current_text(self) -> str:
        if self._source is None:
            return ""
        style = str(self.style.currentData())
        return cites.every_style(self._source) if style == "all" else cites.block(self._source, style)

    def _render(self, style: str) -> str:
        if self._source is None:
            return ""
        text = cites.every_style(self._source) if style == "all" else cites.block(self._source, style)
        self.text.setHtml("<br><br>".join(cites.rich(part).replace("\n", "<br>") for part in text.split("\n\n")))
        self.style_changed.emit(style)
        return text

    def _copy(self) -> None:
        copy_rich(self.clip_text())
        self.note.setText("Copied.")
