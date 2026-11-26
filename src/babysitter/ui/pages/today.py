"""The Journal and Files pages. Both are local only.

The journal writes program names and minutes, nothing else. File search
looks only in the chosen folders, on demand, and never starts a program.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.ui.pinbutton import fill_pinned_list, pin_button


class JournalPage(QWidget):
    notice = Signal(str)
    pin_line = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)
        title = QLabel("Journal")
        title.setObjectName("title")
        root.addWidget(title)
        intro = QLabel(
            "Keeps program names and minutes only, for 90 days. "
            "No window titles, no screenshots, no typing. It stays in your BabySitter folder."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)

        self.enabled = QCheckBox("Keep the day journal")
        self.enabled.setToolTip(
            "On by default. Turning it off stops the writing at once. The files already "
            "written stay until you wipe them."
        )
        root.addWidget(self.enabled)

        say_row = QHBoxLayout()
        say = QPushButton("Say my day")
        say.setObjectName("primary")
        say.setToolTip("Speaks today's summary. The same as asking what did I do today.")
        say.clicked.connect(lambda: self.notice.emit("JOURNAL today"))
        yesterday = QPushButton("Say yesterday")
        yesterday.setToolTip("Speaks yesterday's summary.")
        yesterday.clicked.connect(lambda: self.notice.emit("JOURNAL yesterday"))
        self.pause = QPushButton("Pause the journal")
        self.pause.setCheckable(True)
        self.pause.setToolTip("Stops writing until you resume. The old days stay.")
        self.pause.toggled.connect(self._pause_toggled)
        say_row.addWidget(say)
        say_row.addWidget(yesterday)
        say_row.addWidget(self.pause)
        say_row.addStretch(1)
        root.addLayout(say_row)

        task_label = QLabel("TASKS")
        task_label.setObjectName("section")
        root.addWidget(task_label)
        task_row = QHBoxLayout()
        self.task_name = QLineEdit()
        self.task_name.setAccessibleName("Task name")
        self.task_name.setPlaceholderText("wiring the shelf")
        self.task_name.setToolTip("A few words naming what you are working on.")
        start = QPushButton("Start task")
        start.setToolTip("The same as saying start task and the name.")
        start.clicked.connect(self._start_task)
        self.task_name.returnPressed.connect(self._start_task)
        done = QPushButton("Done")
        done.setToolTip("Closes the open task and says how long it took.")
        done.clicked.connect(lambda: self.notice.emit("TASK done"))
        task_row.addWidget(self.task_name, 1)
        task_row.addWidget(start)
        task_row.addWidget(done)
        root.addLayout(task_row)

        today_row = QHBoxLayout()
        today_label = QLabel("TODAY SO FAR")
        today_label.setObjectName("section")
        today_pin = pin_button()
        today_pin.setToolTip("Pin today's journal. It stays on this PC.")
        today_pin.clicked.connect(self._pin_today)
        today_row.addWidget(today_label)
        today_row.addStretch(1)
        today_row.addWidget(today_pin)
        root.addLayout(today_row)
        self.lines = QListWidget()
        self.lines.setAccessibleName("Today's journal entries")
        self.lines.setToolTip("Each line of today's journal. The pin puts that line on the board.")
        root.addWidget(self.lines, 1)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setToolTip("Program names and minutes from today's journal file.")
        self.body.hide()
        root.addWidget(self.body)

        wipe_row = QHBoxLayout()
        self.wipe = QPushButton("Wipe the journal")
        self.wipe.setToolTip("Deletes every journal day file. There is no undo.")
        self.wipe.clicked.connect(lambda: self.notice.emit("WIPE journal"))
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-reads today's journal file.")
        refresh.clicked.connect(self.refresh)
        wipe_row.addWidget(refresh)
        wipe_row.addStretch(1)
        wipe_row.addWidget(self.wipe)
        root.addLayout(wipe_row)

    def _start_task(self) -> None:
        name = self.task_name.text().strip()
        if not name:
            self.body.setPlainText("Type a task name first. Nothing was started.")
            fill_pinned_list(self.lines, [("Type a task name first. Nothing was started.", "")], self.pin_line.emit)
            return
        self.task_name.clear()
        self.notice.emit(f"TASK start {name}")

    def _pause_toggled(self, paused: bool) -> None:
        self.pause.setText("Resume the journal" if paused else "Pause the journal")
        self.notice.emit("JOURNAL pause" if paused else "JOURNAL resume")

    def set_paused(self, paused: bool) -> None:
        self.pause.blockSignals(True)
        self.pause.setChecked(paused)
        self.pause.setText("Resume the journal" if paused else "Pause the journal")
        self.pause.blockSignals(False)

    def refresh(self) -> None:
        from babysitter.journal import day_detail, load_day

        try:
            record = load_day(date.today())
            detail = day_detail(record)
        except Exception:
            detail = "Today's journal file could not be read."
        text = detail or "Nothing is in the journal for today yet."
        self.body.setPlainText(text)
        rows = [line.strip() for line in text.splitlines() if line.strip()]
        fill_pinned_list(self.lines, [(line, "") for line in rows], self.pin_line.emit)

    def _pin_today(self) -> None:
        text = self.body.toPlainText().strip()
        if text:
            self.pin_line.emit(text)

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh()
        super().showEvent(event)


class FilesPage(QWidget):
    notice = Signal(str)
    pin_line = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)
        title = QLabel("Files")
        title.setObjectName("title")
        root.addWidget(title)
        intro = QLabel(
            "Find a file by a few words of its name, the same as saying find my tax pdf. "
            "Nothing is indexed in the background and no file name leaves this PC. "
            "Programs and scripts are listed but never started."
        )
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        root.addWidget(intro)

        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setAccessibleName("File name search")
        self.query.setPlaceholderText("tax pdf, dragon stl, resume…")
        self.query.setToolTip("A few words from the file name. Current or latest picks the one opened most recently.")
        self.query.returnPressed.connect(self._find)
        find = QPushButton("Find")
        find.setObjectName("primary")
        find.setToolTip("Looks through the folders below. One match opens; several make a numbered list.")
        find.clicked.connect(self._find)
        row.addWidget(self.query, 1)
        row.addWidget(find)
        root.addLayout(row)

        self.folders_line = QLabel("Searching Documents, Downloads, and Desktop.")
        self.folders_line.setWordWrap(True)
        self.folders_line.setObjectName("hint")
        root.addWidget(self.folders_line)

        self.matches = QListWidget()
        self.matches.setAccessibleName("Matching files")
        self.matches.setToolTip("Files that matched. The pin puts one on the board. A program is never started.")
        root.addWidget(self.matches, 1)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setPlaceholderText(
            "Matches show up here. One match opens by itself. Several make a numbered "
            "list that is good for 10 minutes — say open 2, or type open number 2 on Home."
        )
        self.body.hide()
        root.addWidget(self.body)

        note = QLabel("Add or remove folders under Settings › File search folders.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        root.addWidget(note)

    def _find(self) -> None:
        wanted = self.query.text().strip()
        if not wanted:
            self._show_lines("Type a few words of the file name first. Nothing was searched.")
            return
        self.notice.emit(f"FIND {wanted}")

    def set_folders(self, folders: list[str]) -> None:
        if not folders:
            self.folders_line.setText("No folders are set.")
            return
        self.folders_line.setText("Searching " + ", ".join(folders) + ".")

    def set_results(self, speech: str, detail: str) -> None:
        text = speech if not detail else f"{speech}\n\n{detail}"
        self._show_lines(text)

    def set_busy_line(self, text: str) -> None:
        self._show_lines(text)

    def _show_lines(self, text: str) -> None:
        self.body.setPlainText(text)
        rows = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not rows:
            self.matches.clear()
            return
        fill_pinned_list(self.matches, [(line, "") for line in rows], self.pin_line.emit)
