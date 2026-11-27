"""The rest of the tabs: schedule, memory, history, screen, health, models.

Each button does a real local action or says, in plain words, why it cannot
yet. Nothing here sends data off this PC.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from babysitter.deskstore import add_item, load_list, reminder_line, remove_item
from babysitter.models import model_choice
from babysitter.ui.pinbutton import fill_pinned_list, fit_pinned_row, list_width, pin_button


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
        self.body.setAccessibleName(f"{title} details")
        self.root.addWidget(self.body)

    def _fresh(self, key: str) -> bool:
        """Enter and the button can both fire for one press. The second is ignored."""
        now = time.monotonic()
        last = getattr(self, "_press_at", {})
        if now - last.get(key, 0.0) < 0.25:
            return False
        last[key] = now
        self._press_at = last
        return True

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
            "and shows a notification on this PC, even if the AI is off. BabySitter itself "
            "has to be open, including in the tray. If you quit BabySitter, it is said the "
            "next time the app is open and the time has passed. Nothing is sent. "
            "Say undo within 10 seconds to remove a new one. "
            "The time left counts down on this page and on Home. "
            "A goal stays here too. Say my goals, and the list is shown and read out.",
        )
        self.body.hide()
        # Goals sit in one box, so v3 can show them on the Board.
        self.goals_box = QWidget()
        goals_layout = QVBoxLayout(self.goals_box)
        goals_layout.setContentsMargins(0, 0, 0, 0)
        goals_layout.setSpacing(8)
        self.root.insertWidget(2, self.goals_box)
        goal_head = QLabel("Goals")
        goal_head.setObjectName("word")
        goals_layout.addWidget(goal_head)
        goal_row = QHBoxLayout()
        self.goal_text = QLineEdit()
        self.goal_text.setAccessibleName("Goal text")
        self.goal_text.setPlaceholderText("Finish the bracket")
        self.goal_text.setToolTip("A goal stays on this PC. It does not ring.")
        add_goal = QPushButton("Add goal")
        add_goal.setObjectName("primary")
        add_goal.setToolTip("Saves the goal on this PC and shows it in the list below.")
        add_goal.clicked.connect(self._add_goal)
        self.goal_text.returnPressed.connect(self._add_goal)
        done_goal = QPushButton("Done")
        done_goal.setAccessibleName("Mark selected goal done")
        done_goal.setToolTip("Marks the selected goal done. It stays on the list.")
        done_goal.clicked.connect(self._done_goal)
        remove_goal = QPushButton("Remove")
        remove_goal.setAccessibleName("Remove selected goal")
        remove_goal.setToolTip("Takes the selected goal off the list. Nothing else is deleted.")
        remove_goal.clicked.connect(self._remove_goal)
        goal_row.addWidget(self.goal_text, 1)
        goal_row.addWidget(add_goal)
        goal_row.addWidget(done_goal)
        goal_row.addWidget(remove_goal)
        goals_layout.addLayout(goal_row)
        self.goals = QListWidget()
        self.goals.setAccessibleName("Saved goals")
        self.goals.setMinimumHeight(72)
        self.goals.setToolTip("Goals saved on this PC. Saying my goals opens this page.")
        goals_layout.addWidget(self.goals)
        remind_head = QLabel("Reminders")
        remind_head.setObjectName("word")
        self.root.insertWidget(3, remind_head)
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setAccessibleName("Reminder text")
        self.text.setPlaceholderText("Stretch")
        self.text.setToolTip("What to say when the time arrives.")
        self.when = QLineEdit()
        self.when.setAccessibleName("Reminder time")
        self.when.setPlaceholderText("6:00 PM, or in 20 minutes")
        self.when.setToolTip("The clock time. You can also write it in the note, as in stretch at 6:00 PM.")
        add = QPushButton("Add reminder")
        add.setObjectName("primary")
        add.setToolTip("Saves on this PC. A time makes it ring. Say undo within 10 seconds to remove it.")
        add.clicked.connect(self._add)
        self.text.returnPressed.connect(self._add)
        self.when.returnPressed.connect(self._add)
        remove = QPushButton("Remove")
        remove.setAccessibleName("Remove selected reminder")
        remove.setToolTip("Takes the selected reminder off the list. Nothing else is deleted.")
        remove.clicked.connect(self._remove)
        row.addWidget(self.text, 2)
        row.addWidget(self.when, 1)
        row.addWidget(add)
        row.addWidget(remove)
        self.root.insertLayout(4, row)
        self.list = QListWidget()
        self.list.setAccessibleName("Saved reminders")
        self.list.setToolTip("Reminders saved on this PC. The pin puts one on the board.")
        self.root.insertWidget(5, self.list)
        self.refresh()

    def refresh(self) -> None:
        self._show_reminders()
        self.refresh_goals()

    def refresh_goals(self) -> None:
        from babysitter.goals import goal_rows

        items = load_list("goals.json")
        if not items:
            self.goals.clear()
            self.goals.addItem("No goals yet.")
            return
        fill_pinned_list(self.goals, goal_rows(items), self.pin_line.emit)

    def _add_goal(self) -> None:
        if not self._fresh("goal"):
            return
        text = self.goal_text.text().strip()
        if not text:
            self.notice.emit("Type the goal first. Nothing was saved.")
            return
        self.notice.emit(f"CONFIRM goal: {text}")

    def _done_goal(self) -> None:
        current = self.goals.currentItem()
        if current is None:
            return
        item_id = str(current.data(Qt.UserRole) or "")
        if not item_id:
            return
        self.notice.emit(f"GOAL done: {item_id}")

    def _remove_goal(self) -> None:
        current = self.goals.currentItem()
        if current is None:
            return
        item_id = str(current.data(Qt.UserRole) or "")
        if not item_id:
            return
        self.notice.emit(f"GOAL drop: {item_id}")

    def _show_reminders(self) -> None:
        items = load_list("schedule.json")
        if not items:
            self.list.clear()
            self.list.addItem("No reminders yet.")
            return
        fill_pinned_list(
            self.list,
            [
                (
                    reminder_line(item),
                    str(item.get("id") or ""),
                    " ".join(str(item.get("text") or "Reminder").split()) or "Reminder",
                )
                for item in items
            ],
            self.pin_line.emit,
        )

    def tick(self, items: list | None = None) -> None:
        """Refresh the time left on each row without rebuilding the pins.

        Skipped while the page is not on screen: the next tick after it is
        shown brings every row up to date within a second."""
        from PySide6.QtWidgets import QLabel

        if not self.isVisible():
            return
        if items is None:
            items = load_list("schedule.json")
        by_id = {str(item.get("id") or ""): item for item in items}
        shown = [
            str(self.list.item(row).data(Qt.ItemDataRole.UserRole) or "")
            for row in range(self.list.count())
        ]
        if [item_id for item_id in shown if item_id] != [item_id for item_id in by_id if item_id]:
            self.refresh()
            return
        for row in range(self.list.count()):
            item = self.list.item(row)
            source = by_id.get(str(item.data(Qt.ItemDataRole.UserRole) or ""))
            if source is None:
                continue
            text = reminder_line(source)
            item.setText(text)
            widget = self.list.itemWidget(item)
            if widget is None:
                continue
            label = widget.findChild(QLabel, "pinnedLine")
            if label is not None:
                label.setText(text)
                fit_pinned_row(item, label, list_width(self.list))

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
        if not self._fresh("reminder"):
            return
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
        self.text.setAccessibleName("Fact to remember")
        self.text.setPlaceholderText("My name is …")
        self.text.returnPressed.connect(self._add)
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
        self.facts.setAccessibleName("Saved facts")
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
        if not self._fresh("memory"):
            return
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
        self.search.setAccessibleName("Search saved conversations")
        self.search.setPlaceholderText("Search saved conversations")
        self.search.returnPressed.connect(self.refresh)
        find = QPushButton("Search")
        find.clicked.connect(self.refresh)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(find)
        self.root.insertLayout(2, search_row)
        self.sessions = QListWidget()
        self.sessions.setAccessibleName("Saved conversations")
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
        self.wipe_box.setAccessibleName("Confirm wipe by typing WIPE")
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
        bonsai = QPushButton("Benchmark bonsai-2:27b (timing only)")
        bonsai.setToolTip(
            "About twice this card's memory, so it runs partly in system memory and slowly. "
            "Timed only. It is never a level, and your own model loads again afterwards."
        )
        bonsai.clicked.connect(lambda: self.notice.emit("BENCHMARK bonsai-2:27b"))
        remove_row = QHBoxLayout()
        self.remove_name = QLineEdit()
        self.remove_name.setAccessibleName("Model name to remove")
        self.remove_name.setPlaceholderText("Model name to remove, such as qwen3.5:4b")
        self.remove_name.setToolTip("Type an installed Ollama model name. BabySitter asks before deleting it.")
        self.remove_name.returnPressed.connect(self._remove_model)
        self.remove_button = QPushButton("Remove model")
        self.remove_button.setObjectName("danger")
        self.remove_button.setToolTip("Asks first, then tells Ollama on this PC to delete that model.")
        self.remove_button.clicked.connect(self._remove_model)
        remove_row.addWidget(self.remove_name, 1)
        remove_row.addWidget(self.remove_button)
        self.root.insertLayout(2, remove_row)
        self.root.insertWidget(2, bonsai)
        self.root.insertWidget(2, bench)
        self.root.insertWidget(2, ask)
        self.add_page_pin()

    def _remove_model(self) -> None:
        if not self._fresh("remove_model"):
            return
        name = self.remove_name.text().strip()
        if not name:
            self.body.setPlainText("Type a model name first. Nothing was removed.")
            return
        self.notice.emit(f"REMOVE model: {name}")


def remember(text: str) -> None:
    add_item("memory.json", text=text)


def remind(text: str) -> None:
    add_item("schedule.json", text=text)
