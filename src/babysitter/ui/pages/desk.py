"""The rest of the tabs: schedule, memory, history, screen, health, models.

Each button does a real local action or says, in plain words, why it cannot
yet. Nothing here sends data off this PC.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.deskstore import add_item, load_list, remove_item


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
            "Reminders stay on this PC. A reminder is saved only after you confirm it from Home or from the button here.",
        )
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("Stretch at 6:00 PM")
        add = QPushButton("Add reminder")
        add.setObjectName("primary")
        add.setToolTip("Asks before it saves. Nothing is sent off this PC.")
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
            "A fact is saved only after you agree. You can delete each one. Memory stays on this PC.",
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
            "Past sessions will be listed here as readable transcripts. Nothing is saved until the voice loop is keeping sessions. Home is not the transcript.",
        )
        self.body.setPlainText(
            "No sessions yet. When a conversation is saved, you will be able to search it, export it, or delete it. "
            "Wipe will ask you to type WIPE."
        )


class ScreenPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Screen",
            "A look starts only when you press the button. The picture stays in memory. It is not saved to disk, and it is not sent unless you confirm that exact picture.",
        )
        look = QPushButton("Look at this screen")
        look.setObjectName("primary")
        look.setToolTip("Asks first. Does not save a file.")
        look.clicked.connect(lambda: self.notice.emit("CONFIRM screen"))
        self.root.insertWidget(2, look)


class HealthPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "PC Health",
            "Read only. BabySitter will not change the PC. There is no Fix button. "
            "On Windows these are three fixed checks. "
            "Two setup steps BabySitter cannot do for you. "
            "NVIDIA Control Panel, Manage 3D settings, Program Settings, ollama.exe, "
            "CUDA Sysmem Fallback Policy, Prefer No Sysmem Fallback. "
            "And, if Ollama was already running from its own tray icon, quit that icon and start it again "
            "after the context setting is saved. BabySitter sets that only when it starts Ollama itself.",
        )
        run = QPushButton("Read memory, startup, and RAM speed")
        run.setToolTip("Runs the fixed read-only checks. They do not change Windows.")
        run.clicked.connect(lambda: self.notice.emit("RUN health"))
        self.root.insertWidget(2, run)


class ModelsPage(_Page):
    def __init__(self) -> None:
        super().__init__(
            "Models",
            "Only one model is loaded at a time. Low keeps qwen3.5:9b near 6 GB. "
            "It answers and can look at the screen. gemma4:12b is for longer writing. qwen3-vl:8b is optional. "
            "Removing a model asks first. An uninstall does not remove Ollama's models.",
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
