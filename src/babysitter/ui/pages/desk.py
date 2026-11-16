"""The rest of the tabs: schedule, memory, history, screen, health, models.

Each button does a real local action or says, in plain words, why it cannot
yet. Nothing here sends data off this PC.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.deskstore import add_item, load_list, reminder_line, remove_item
from babysitter.models import model_choice
from babysitter.ui.pinbutton import fill_pinned_list, pin_button


class _Page(QWidget):
    notice = Signal(str)
    pin_line = Signal(str)

    def __init__(self, title: str, intro: str) -> None:
        super().__init__()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 18, 22, 18)
        heading = QLabel(title)
        heading.setObjectName("title")
        text = QLabel(intro)
        text.setWordWrap(True)
        text.setObjectName("hint")
        self.root.addWidget(heading)
        self.root.addWidget(text)
        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.root.addWidget(self.body)

    def add_page_pin(self) -> None:
        row = QHBoxLayout()
        pin = pin_button()
        pin.setToolTip("Pin what is written on this page. It stays on this PC.")
        pin.clicked.connect(self._emit_body)
        row.addWidget(pin)
        row.addStretch(1)
        self.root.insertLayout(2, row)

    def _emit_body(self) -> None:
        text = self.body.toPlainText().strip()
        if text:
            self.pin_line.emit(text)


class SchedulePage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Reminders",
            "A reminder stays on this PC. When its time arrives, BabySitter says it out loud "
            "and shows a notification on this PC. That happens while BabySitter is open, "
            "including in the tray. If BabySitter is quit, it is said the next time the app "
            "is open and the time has passed. Nothing is sent. Say undo within 10 seconds to remove a new one.",
        )
        self.body.hide()
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Stretch")
        self.text.setToolTip("What to say when the time arrives.")
        self.when = QLineEdit()
        self.when.setPlaceholderText("6:00 PM, or in 20 minutes")
        self.when.setToolTip("The clock time. You can also write it in the note, as in stretch at 6:00 PM.")
        add = QPushButton("Add reminder")
        add.setObjectName("primary")
        add.setToolTip("Saves on this PC. A time makes it ring. Say undo within 10 seconds to remove it.")
        add.clicked.connect(self._add)
        self.text.returnPressed.connect(self._add)
        self.when.returnPressed.connect(self._add)
        remove = QPushButton("Remove")
        remove.setToolTip("Takes the selected reminder off the list. Nothing else is deleted.")
        remove.clicked.connect(self._remove)
        row.addWidget(self.text, 2)
        row.addWidget(self.when, 1)
        row.addWidget(add)
        row.addWidget(remove)
        self.root.insertLayout(2, row)
        self.list = QListWidget()
        self.list.setToolTip("Reminders saved on this PC. The pin puts one on the board.")
        self.root.insertWidget(3, self.list)
        self.refresh()

    def refresh(self) -> None:
        items = load_list("schedule.json")
        if not items:
            self.list.clear()
            self.list.addItem("No reminders yet.")
            return
        fill_pinned_list(
            self.list,
            [(reminder_line(item), str(item.get("id") or "")) for item in items],
            self.pin_line.emit,
        )

    def _remove(self) -> None:
        current = self.list.currentItem()
        if current is None:
            return
        item_id = str(current.data(Qt.UserRole) or "")
        if not item_id:
            return
        remove_item("schedule.json", item_id)
        self.refresh()

    def _add(self) -> None:
        text = self.text.text().strip()
        when = self.when.text().strip()
        if not text and not when:
            self.notice.emit("Type the reminder first. Nothing was saved.")
            return
        self.notice.emit(f"CONFIRM reminder: {text}\nWHEN: {when}")


class MemoryPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Memory",
            "A fact is saved when you press the button or say remember. Say undo within 10 seconds to remove it. Memory stays on this PC.",
        )
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("My name is …")
        add = QPushButton("Remember this")
        add.setObjectName("primary")
        add.clicked.connect(self._add)
        forget = QPushButton("Delete the last fact")
        forget.clicked.connect(self._forget)
        review = QPushButton("Weekly review")
        review.setToolTip("A summary from this PC. It does not load a model.")
        review.clicked.connect(lambda: self.notice.emit("WEEKLY review"))
        self.sharper = QPushButton("Sharper matching")
        self.sharper.setToolTip(
            "Downloads a small sentence model (about 90 MB) so facts match by "
            "meaning, not just the same words. It runs on the processor, on this PC."
        )
        self.sharper.clicked.connect(lambda: self.notice.emit("INSTALL embedder"))
        row.addWidget(self.text, 1)
        row.addWidget(add)
        row.addWidget(forget)
        row.addWidget(review)
        row.addWidget(self.sharper)
        self.refresh_sharper()
        self.root.insertLayout(2, row)
        self.facts = QListWidget()
        self.facts.setToolTip("Facts saved on this PC. The pin puts one on the board.")
        self.root.insertWidget(3, self.facts)
        self.body.hide()
        self.refresh()

    def refresh_sharper(self) -> None:
        from babysitter.embedder import ready as embedder_ready

        if embedder_ready():
            self.sharper.setText("Sharper matching is on")
            self.sharper.setEnabled(False)

    def refresh(self) -> None:
        items = load_list("memory.json")
        lines = [str(item.get("text") or "") for item in items]
        self.body.setPlainText("\n".join(f"• {line}" for line in lines) if lines else "Nothing is remembered yet.")
        if not lines:
            self.facts.clear()
            self.facts.addItem("Nothing is remembered yet.")
            return
        fill_pinned_list(self.facts, [(line, str(item.get("id") or "")) for item, line in zip(items, lines)], self.pin_line.emit)

    def _add(self) -> None:
        text = self.text.text().strip()
        if not text:
            self.notice.emit("Type the fact first. Nothing was saved.")
            return
        self.notice.emit(f"CONFIRM memory: {text}")

    def _forget(self) -> None:
        items = load_list("memory.json")
        if not items:
            self.notice.emit("There is no fact to delete.")
            return
        remove_item("memory.json", str(items[-1].get("id")))
        self.refresh()
        self.notice.emit("Deleted the last remembered fact. It stayed on this PC until then.")


class HistoryPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "History",
            "Conversations are saved on this PC when a reply finishes. "
            "Search them, export one as a text file, or delete them. Nothing here is uploaded.",
        )
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search saved conversations")
        self.search.returnPressed.connect(self.refresh)
        find = QPushButton("Search")
        find.clicked.connect(self.refresh)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(find)
        self.root.insertLayout(2, search_row)
        self.sessions = QListWidget()
        self.sessions.setToolTip("Saved conversations. The pin puts one on the board.")
        self.root.insertWidget(3, self.sessions)
        buttons = QHBoxLayout()
        export = QPushButton("Export")
        export.setToolTip("Writes a text file in your BabySitter folder. It is not uploaded.")
        export.clicked.connect(lambda: self.notice.emit("EXPORT session"))
        delete = QPushButton("Delete")
        delete.clicked.connect(lambda: self.notice.emit("DELETE session"))
        buttons.addWidget(export)
        buttons.addWidget(delete)
        self.root.insertLayout(4, buttons)
        wipe_row = QHBoxLayout()
        self.wipe_box = QLineEdit()
        self.wipe_box.setPlaceholderText("Type WIPE to delete every saved conversation")
        wipe = QPushButton("Wipe")
        wipe.clicked.connect(self._wipe)
        wipe_row.addWidget(self.wipe_box, 1)
        wipe_row.addWidget(wipe)
        self.root.insertLayout(5, wipe_row)
        self.refresh()

    def selected_id(self) -> str:
        item = self.sessions.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def refresh(self) -> None:
        from babysitter.sessions import search_sessions

        self.sessions.clear()
        rows = search_sessions(self.search.text())
        if not rows:
            self.body.setPlainText("No saved conversations match.")
            return
        lines = []
        pinned: list[tuple[str, str]] = []
        for row in rows:
            label = f"{row['started']}  {row['preview']}"
            lines.append(f"{row['started']} ({row['turns']} turns) {row['preview']}")
            pinned.append((label, row["id"]))
        fill_pinned_list(self.sessions, pinned, self.pin_line.emit)
        self.body.setPlainText("\n".join(lines))

    def _wipe(self) -> None:
        from babysitter.sessions import wipe_sessions

        if self.wipe_box.text().strip() != "WIPE":
            self.body.setPlainText("Type WIPE to delete every saved conversation. Nothing was deleted.")
            return
        count = wipe_sessions()
        self.wipe_box.clear()
        self.refresh()
        self.body.append(f"\nDeleted {count} saved file(s). They stayed on this PC until then.")


class ScreenPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Screen",
            "A look starts when you press the button or ask by voice. "
            "The picture stays in memory. It is not saved to disk.",
        )
        look = QPushButton("Look at this screen")
        look.setObjectName("primary")
        look.setToolTip("Takes one picture in memory. It is not saved.")
        look.clicked.connect(lambda: self.notice.emit("CONFIRM screen"))
        self.root.insertWidget(2, look)
        self.add_page_pin()


class HealthPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "PC Health",
            "The checks below only read. Suggestions are separate. "
            "BabySitter asks out loud, one at a time, and changes something only after you say yes. "
            "On Windows the read-only checks are three fixed checks. "
            "Two setup steps BabySitter cannot do for you. "
            "NVIDIA Control Panel, Manage 3D settings, Program Settings, ollama.exe, "
            "CUDA Sysmem Fallback Policy, Prefer No Sysmem Fallback. "
            "And, if Ollama was already running from its own tray icon, quit that icon and start it again "
            "after the context setting is saved. BabySitter sets that only when it starts Ollama itself.",
        )
        run = QPushButton("Read memory, startup, and RAM speed")
        run.setToolTip("Runs the fixed read-only checks. They do not change Windows.")
        run.clicked.connect(lambda: self.notice.emit("RUN health"))
        suggest = QPushButton("Suggest changes, one at a time")
        suggest.setToolTip("Speaks one idea. Say yes to do that one, or no to leave it.")
        suggest.clicked.connect(lambda: self.notice.emit("SCAN pc"))
        self.root.insertWidget(2, suggest)
        self.root.insertWidget(2, run)
        self.add_page_pin()


class ModelsPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Models",
            model_choice() + " Removing a model asks first. An uninstall does not remove Ollama's models.",
        )
        ask = QPushButton("Ask Ollama which models are installed")
        ask.setObjectName("primary")
        ask.clicked.connect(lambda: self.notice.emit("LIST models"))
        bench = QPushButton("Benchmark")
        bench.setToolTip("Times a fixed prompt three times. It does not save the words.")
        bench.clicked.connect(lambda: self.notice.emit("BENCHMARK"))
        self.root.insertWidget(2, bench)
        self.root.insertWidget(2, ask)
        self.add_page_pin()


def remember(text: str) -> None:
    add_item("memory.json", text=text)


def remind(text: str) -> None:
    add_item("schedule.json", text=text)
