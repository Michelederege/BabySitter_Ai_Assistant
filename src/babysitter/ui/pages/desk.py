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

from babysitter.deskstore import add_item, load_list, remove_item
from babysitter.models import model_choice


class _Page(QWidget):
    notice = Signal(str)

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


class SchedulePage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Schedule",
            "Reminders stay on this PC. Adding one saves it, and you can say undo within 10 seconds.",
        )
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Stretch at 6:00 PM")
        add = QPushButton("Add reminder")
        add.setObjectName("primary")
        add.setToolTip("Saves on this PC. Say undo within 10 seconds to remove it.")
        add.clicked.connect(self._add)
        row.addWidget(self.text, 1)
        row.addWidget(add)
        self.root.insertLayout(2, row)
        self.refresh()

    def refresh(self) -> None:
        items = load_list("schedule.json")
        if not items:
            self.body.setPlainText("No reminders yet.")
            return
        self.body.setPlainText("\n".join(f"• {item.get('text', '')}" for item in items))

    def _add(self) -> None:
        text = self.text.text().strip()
        if not text:
            self.notice.emit("Type the reminder first. Nothing was saved.")
            return
        self.notice.emit(f"CONFIRM reminder: {text}")


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
        row.addWidget(self.text, 1)
        row.addWidget(add)
        row.addWidget(forget)
        row.addWidget(review)
        self.root.insertLayout(2, row)
        self.refresh()

    def refresh(self) -> None:
        items = load_list("memory.json")
        if not items:
            self.body.setPlainText("Nothing is remembered yet.")
            return
        self.body.setPlainText("\n".join(f"• {item.get('text', '')}" for item in items))

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
        for row in rows:
            label = f"{row['started']}  {row['preview']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.sessions.addItem(item)
            lines.append(f"{row['started']} ({row['turns']} turns) {row['preview']}")
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


def remember(text: str) -> None:
    add_item("memory.json", text=text)


def remind(text: str) -> None:
    add_item("schedule.json", text=text)
