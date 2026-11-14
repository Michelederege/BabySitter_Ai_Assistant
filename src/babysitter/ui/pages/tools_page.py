"""The Tools tab: optional Google mail and calendar, and public social search.

Both stay off until you turn them on. Tokens and keys are typed here and
handed to the shell, which encrypts them. This page never writes them
into a file itself.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from babysitter.plugins.tools.social import LATER_RECIPES, SEARCH_ACTIONS, SearchAction


class ToolsPage(QWidget):
    enabled_changed = Signal(bool)
    save_key = Signal(str)
    delete_key = Signal()
    search_requested = Signal(str, str)
    google_enabled_changed = Signal(bool)
    save_google = Signal(str)
    delete_google = Signal()
    google_check = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)

        title = QLabel("Tools")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel(
            "Two things can leave this computer, and both are off until you turn them on. "
            "Google mail and calendar are read with your own token. BabySitter does not "
            "send mail and does not delete mail. A social search sends only the words "
            "in the box below, after you confirm, plus your key. Neither one sends "
            "files, the screen, or memory. Leave both off for confidential work."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        layout.addWidget(intro)

        google_label = QLabel("Google mail and calendar")
        google_label.setObjectName("section")
        layout.addWidget(google_label)
        self.google_enabled = QCheckBox("Turn on Google mail and calendar")
        self.google_enabled.setToolTip(
            "Off by default. While this is off, BabySitter will not contact Google."
        )
        self.google_enabled.toggled.connect(self.google_enabled_changed.emit)
        layout.addWidget(self.google_enabled)
        self.google_status = QLabel("No Google token saved.")
        self.google_status.setWordWrap(True)
        self.google_status.setObjectName("hint")
        layout.addWidget(self.google_status)
        google_row = QHBoxLayout()
        self.google_input = QLineEdit()
        self.google_input.setEchoMode(QLineEdit.Password)
        self.google_input.setPlaceholderText("Paste a read-only Gmail and Calendar token")
        self.google_input.setToolTip(
            "A token from your own Google account, with read-only mail and calendar. "
            "BabySitter encrypts it for your Windows user. It is not saved in settings.json."
        )
        self.google_save = QPushButton("Save token")
        self.google_save.setToolTip("Encrypt the token and clear this box.")
        self.google_save.clicked.connect(self._emit_google_save)
        self.google_delete = QPushButton("Delete token")
        self.google_delete.setToolTip("Remove the encrypted token from this PC.")
        self.google_delete.clicked.connect(self.delete_google.emit)
        google_row.addWidget(self.google_input, 1)
        google_row.addWidget(self.google_save)
        google_row.addWidget(self.google_delete)
        layout.addLayout(google_row)
        check_row = QHBoxLayout()
        self.mail_button = QPushButton("Check mail")
        self.mail_button.setToolTip("Reads unread subjects. Does not send or delete mail.")
        self.mail_button.clicked.connect(lambda: self.google_check.emit("mail"))
        self.calendar_button = QPushButton("Check calendar")
        self.calendar_button.setToolTip("Reads the next few events. Does not change the calendar.")
        self.calendar_button.clicked.connect(lambda: self.google_check.emit("calendar"))
        check_row.addWidget(self.mail_button)
        check_row.addWidget(self.calendar_button)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        self.enabled = QCheckBox("Turn on social search")
        self.enabled.setToolTip(
            "Off by default. While this is off, BabySitter will not contact ScrapeCreators."
        )
        self.enabled.toggled.connect(self._on_toggled)
        layout.addWidget(self.enabled)

        key_label = QLabel("ScrapeCreators API key")
        key_label.setObjectName("section")
        layout.addWidget(key_label)
        self.key_status = QLabel("No key saved.")
        self.key_status.setWordWrap(True)
        self.key_status.setObjectName("hint")
        layout.addWidget(self.key_status)
        key_row = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("Paste the key from scrapecreators.com")
        self.key_input.setToolTip(
            "Get a key at scrapecreators.com. BabySitter encrypts it for your "
            "Windows user. It is not saved in settings.json."
        )
        self.save_button = QPushButton("Save key")
        self.save_button.setToolTip("Encrypt the key and clear this box.")
        self.save_button.clicked.connect(self._emit_save)
        self.delete_button = QPushButton("Delete saved key")
        self.delete_button.setToolTip("Remove the encrypted key from this PC.")
        self.delete_button.clicked.connect(self.delete_key.emit)
        key_row.addWidget(self.key_input, 1)
        key_row.addWidget(self.save_button)
        key_row.addWidget(self.delete_button)
        layout.addLayout(key_row)

        kind_label = QLabel("What to look up")
        kind_label.setObjectName("section")
        layout.addWidget(kind_label)
        self.kind = QComboBox()
        for action in SEARCH_ACTIONS:
            self.kind.addItem(action.label, action.id)
        self.kind.setToolTip("Public posts, a public profile, comments, or a transcript.")
        self.kind.currentIndexChanged.connect(self._show_action)
        layout.addWidget(self.kind)
        self.action_note = QLabel("")
        self.action_note.setWordWrap(True)
        self.action_note.setObjectName("hint")
        layout.addWidget(self.action_note)

        self.query = QLineEdit()
        self.query.setToolTip("Only this text is sent, after you confirm.")
        self.query.returnPressed.connect(self._emit_search)
        layout.addWidget(self.query)

        self.search_button = QPushButton("Prepare search")
        self.search_button.setObjectName("primary")
        self.search_button.setToolTip(
            "Shows exactly what will be sent. Nothing leaves this PC until you confirm."
        )
        self.search_button.clicked.connect(self._emit_search)
        layout.addWidget(self.search_button)

        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Results show up here, with the public link when there is one.")
        self.results.setMinimumHeight(180)
        layout.addWidget(self.results)

        later = QLabel("Research recipes that wait for the talking assistant")
        later.setObjectName("section")
        layout.addWidget(later)
        later_body = QLabel(_later_text())
        later_body.setWordWrap(True)
        later_body.setObjectName("hint")
        later_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(later_body)
        layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._show_action()
        self._apply_enabled(False)

    def _on_toggled(self, on: bool) -> None:
        self._apply_enabled(on)
        self.enabled_changed.emit(on)

    def set_enabled(self, on: bool) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(on)
        self.enabled.blockSignals(False)
        self._apply_enabled(on)

    def set_google_enabled(self, on: bool) -> None:
        self.google_enabled.blockSignals(True)
        self.google_enabled.setChecked(on)
        self.google_enabled.blockSignals(False)

    def set_google_saved(self, saved: bool, windows_ready: bool) -> None:
        if saved:
            self.google_status.setText(
                "A token is saved, encrypted for your Windows user. "
                "The token itself is not shown again."
            )
        elif windows_ready:
            self.google_status.setText(
                "No token saved. Paste a read-only Gmail and Calendar token, then press Save token."
            )
        else:
            self.google_status.setText(
                "This computer cannot encrypt a token. On your Windows PC, "
                "BabySitter saves it with Windows DPAPI so only your user can read it."
            )
        self.google_delete.setEnabled(saved)

    def show_google(self, text: str) -> None:
        self.google_status.setText(text)

    def set_key_saved(self, saved: bool, windows_ready: bool) -> None:
        if saved:
            self.key_status.setText(
                "A key is saved, encrypted for your Windows user. "
                "The key itself is not shown again."
            )
        elif windows_ready:
            self.key_status.setText(
                "No key saved. Paste one from scrapecreators.com, then press Save key."
            )
        else:
            self.key_status.setText(
                "This computer cannot encrypt a key. On your Windows PC, "
                "BabySitter saves it with Windows DPAPI so only your user can read it."
            )
        self.delete_button.setEnabled(saved)

    def show_message(self, text: str, *, busy: bool = False) -> None:
        self.results.setPlainText(text)
        self.search_button.setEnabled(self.enabled.isChecked() and not busy)

    def _apply_enabled(self, on: bool) -> None:
        for widget in (self.kind, self.query, self.search_button):
            widget.setEnabled(on)
        if not on:
            self.results.setPlaceholderText(
                "Turn on social search before anything can be sent."
            )

    def _current(self) -> SearchAction:
        action_id = self.kind.currentData()
        for action in SEARCH_ACTIONS:
            if action.id == action_id:
                return action
        return SEARCH_ACTIONS[0]

    def _show_action(self) -> None:
        action = self._current()
        self.action_note.setText(action.note)
        self.query.setPlaceholderText(action.placeholder)
        self.query.setVisible(action.kind != "none")

    def _emit_save(self) -> None:
        self.save_key.emit(self.key_input.text())
        self.key_input.clear()

    def _emit_google_save(self) -> None:
        self.save_google.emit(self.google_input.text())
        self.google_input.clear()

    def _emit_search(self) -> None:
        if not self.enabled.isChecked():
            return
        self.search_button.setEnabled(False)
        self.results.setPlainText("Waiting for you to confirm…")
        self.search_requested.emit(self._current().id, self.query.text())


def _later_text() -> str:
    lines = [
        "These come from the social-media research skills. BabySitter does not "
        "run them on its own yet, because they need the assistant to talk and "
        "summarize. Age and gender guesses are not included.",
        "",
    ]
    for name, sentence in LATER_RECIPES:
        lines.append(f"• {name}. {sentence}")
    return "\n".join(lines)
