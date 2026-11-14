"""Small dark dialogs. Each one says exactly what the choice will do."""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QPlainTextEdit,
)

from babysitter.hotkeys import HotkeyError, canonical_hotkey
from babysitter.ui.theme import DIALOG_QSS


def _box(parent, title: str) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setStyleSheet(DIALOG_QSS)
    dialog.setMinimumWidth(460)
    return dialog


def ask_yes_no(parent, title: str, body: str, yes: str, no: str) -> bool:
    dialog = _box(parent, title)
    layout = QVBoxLayout(dialog)
    label = QLabel(body)
    label.setWordWrap(True)
    layout.addWidget(label)
    row = QHBoxLayout()
    yes_button = QPushButton(yes)
    yes_button.setObjectName("primary")
    no_button = QPushButton(no)
    yes_button.setToolTip(yes)
    no_button.setToolTip(no)
    yes_button.clicked.connect(dialog.accept)
    no_button.clicked.connect(dialog.reject)
    row.addWidget(no_button)
    row.addWidget(yes_button)
    layout.addLayout(row)
    return dialog.exec() == QDialog.Accepted


def show_copyable(parent, title: str, body: str) -> None:
    dialog = _box(parent, title)
    layout = QVBoxLayout(dialog)
    text = QPlainTextEdit(body)
    text.setReadOnly(True)
    text.setMinimumHeight(160)
    layout.addWidget(text)
    row = QHBoxLayout()
    copy = QPushButton("Copy this text")
    copy.setToolTip("Copies the message so you can paste it when you ask for help.")
    close = QPushButton("Close")
    close.setObjectName("primary")

    def copy_text() -> None:
        QGuiApplication.clipboard().setText(body)

    copy.clicked.connect(copy_text)
    close.clicked.connect(dialog.accept)
    row.addWidget(copy)
    row.addWidget(close)
    layout.addLayout(row)
    dialog.exec()


class HotkeyCapture(QDialog):
    """Waits for you to press a key combination."""

    def __init__(self, parent, purpose: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose a key")
        self.setStyleSheet(DIALOG_QSS)
        self.setModal(True)
        self.chosen = ""
        layout = QVBoxLayout(self)
        label = QLabel(
            f"Press the keys for {purpose}. Use Ctrl, Alt, Shift, or the Windows key "
            "plus one more key. Esc cancels."
        )
        label.setWordWrap(True)
        self.feedback = QLabel("Waiting for a key…")
        self.feedback.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(self.feedback)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key_Escape:
            self.reject()
            return
        if key in {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta}:
            self.feedback.setText("Keep holding that, then press the main key.")
            return
        name = _qt_key_name(key)
        if name is None:
            self.feedback.setText("That key isn't supported. Try a letter, a number, or F1–F24.")
            return
        parts: list[str] = []
        modifiers = event.modifiers()
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.MetaModifier:
            parts.append("Win")
        parts.append(name)
        try:
            self.chosen = canonical_hotkey("+".join(parts))
        except HotkeyError as exc:
            self.feedback.setText(str(exc))
            return
        self.accept()


def _qt_key_name(key: int) -> str | None:
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"F{key - Qt.Key_F1 + 1}"
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    return None


class ProcessPicker(QDialog):
    """Lists programs that are running so a game can be added by name."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a game")
        self.setStyleSheet(DIALOG_QSS)
        self.setMinimumSize(460, 480)
        self.chosen = ""
        layout = QVBoxLayout(self)
        help_label = QLabel(
            "Pick the game's program. If you don't see it, start the game, "
            "close this list, and open it again. Choose the game itself, not Steam."
        )
        help_label.setWordWrap(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter, or type a name like game.exe")
        self.search.setToolTip("Filters the list. You can also type a program name and press Add.")
        self.list = QListWidget()
        self.list.setToolTip("Programs running right now, largest memory users first.")
        layout.addWidget(help_label)
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Add this program")
        add.setObjectName("primary")
        add.setToolTip("Saves the selected program name. BabySitter only compares the name.")
        cancel = QPushButton("Cancel")
        add.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(add)
        layout.addLayout(row)
        self._rows = _running_programs()
        self.search.textChanged.connect(self._refill)
        self.list.itemDoubleClicked.connect(lambda _item: self._accept())
        self._refill()

    def _refill(self) -> None:
        query = self.search.text().strip().lower()
        self.list.clear()
        for name, _rss in self._rows:
            if query and query not in name.lower():
                continue
            self.list.addItem(name)

    def _accept(self) -> None:
        typed = self.search.text().strip()
        current = self.list.currentItem()
        if current and (not typed or typed.lower() in current.text().lower()):
            self.chosen = current.text()
        elif typed:
            self.chosen = typed
        else:
            return
        self.accept()


def _running_programs() -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = proc.info.get("name")
            memory = proc.info.get("memory_info")
        except (psutil.Error, OSError):
            continue
        if not name or memory is None:
            continue
        seen[str(name)] = max(seen.get(str(name), 0), int(memory.rss))
    return sorted(seen.items(), key=lambda item: item[1], reverse=True)
