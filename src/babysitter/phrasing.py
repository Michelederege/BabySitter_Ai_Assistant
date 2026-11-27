"""Warm, natural spoken phrasings that vary without repeating back-to-back.

Local quick commands do not ask the language model, so without variation
they sound like a speaking clock reading the same fixed line every time.
PhraseBook rotates through plain, conversational variants per category so
replies feel human while keeping the facts exact.
"""

from __future__ import annotations

from datetime import datetime


class PhraseBook:
    """Picks the next natural phrasing for each kind of local reply."""

    def __init__(self) -> None:
        self._turns: dict[str, int] = {}

    def _pick(self, key: str, choices: tuple[str, ...]) -> str:
        index = self._turns.get(key, 0)
        self._turns[key] = index + 1
        return choices[index % len(choices)]

    def time_reply(self, now: datetime) -> str:
        weekday = now.strftime("%A")
        month_day = now.strftime("%B %d").replace(" 0", " ")
        clock = now.strftime("%I:%M %p").lstrip("0")
        return self._pick(
            "time",
            (
                f"It's {clock} on {weekday}, {month_day}.",
                f"It's {weekday}, {month_day}, {clock}.",
                f"Right now, it's {clock} — {weekday}, {month_day}.",
            ),
        )

    def vram_reply(self, used_mib: int, total_mib: int) -> str:
        return self._pick(
            "vram",
            (
                f"Video memory is using {used_mib:,} of {total_mib:,} megabytes right now.",
                f"Your graphics card has {used_mib:,} of {total_mib:,} megabytes in use.",
                f"Right now, {used_mib:,} out of {total_mib:,} megabytes of video memory are in use.",
            ),
        )

    def vram_missing_reply(self) -> str:
        return self._pick(
            "vram_missing",
            (
                "I can't see the video memory from here right now.",
                "I couldn't get a video memory reading from the graphics driver.",
            ),
        )

    def memory_saved_reply(self, text: str = "") -> str:
        snippet = " ".join((text or "").split())
        short = f"“{snippet}”" if 0 < len(snippet) <= 48 else "that"
        return self._pick(
            "memory_saved",
            (
                f"Got it — I'll remember {short}. Say undo in the next 10 seconds if you want me to drop it.",
                f"Saved {short} on this PC. Say undo within 10 seconds to remove it.",
                f"Noted, I've tucked {short} away here. Say undo in the next 10 seconds to take it back.",
            ),
        )

    @staticmethod
    def ring_line(note: str) -> str:
        """What is said when a reminder rings. It used to be "Reminder. to call mom"."""
        clean = " ".join((note or "").split()).rstrip(".")
        lowered = clean.lower()
        if lowered in {"", "reminder"}:
            return "Here's your reminder."
        if lowered == "alarm":
            return "It's time. This is your alarm."
        if lowered == "wake up":
            return "Time to wake up."
        if lowered.startswith("to "):
            return f"Time to {clean[3:].strip()}."
        return f"Reminder: {clean}."

    def reminder_saved_reply(self, when_text: str, note: str = "") -> str:
        clean = " ".join((note or "").split())
        # The note often already starts with "to" ("remind me at 5 to call mom"),
        # which said "remind you to to call mom". The default labels (an alarm,
        # a wake-up) are not a subject at all.
        if clean.lower().startswith("to "):
            clean = clean[3:].strip()
        subject = f" to {clean}" if clean and clean.lower() not in {"reminder", "timer", "alarm", "wake up"} else ""
        return self._pick(
            "reminder_saved",
            (
                f"All set — I'll remind you{subject} at {when_text}, even if the AI is off. Say undo in the next 10 seconds to cancel it.",
                f"Reminder set for {when_text}{subject}. I'll say it here and show a notification, even with the AI off. Say undo within 10 seconds to remove it.",
                f"Got it, {when_text}{subject}. It stays on this PC and still rings if the AI is off. Say undo in the next 10 seconds to drop it.",
            ),
        )

    def timer_saved_reply(self, label: str, note: str = "") -> str:
        clean = " ".join((note or "").split())
        for_part = f" for {clean}" if clean and clean.lower() != "timer" else ""
        return self._pick(
            "timer_saved",
            (
                f"Timer set for {label}{for_part}. I'll let you know when it's up, even if the AI is off. Say undo in the next 10 seconds to cancel it.",
                f"Starting {label}{for_part} now. Say undo within 10 seconds if you want to cancel it.",
                f"Got a {label} timer going{for_part}. It'll ring right here while BabySitter is open. Say undo in the next 10 seconds to stop it.",
            ),
        )

    def untimed_reminder_reply(self) -> str:
        return self._pick(
            "untimed_reminder",
            (
                "Saved the reminder, though there's no time on it yet so it won't ring. You can add a time on the Reminders page, or say undo in the next 10 seconds.",
                "I've put that on your Reminders list without a clock time. Add a time on the Reminders page if you want it to ring, or say undo within 10 seconds.",
            ),
        )

    def thanks_reply(self) -> str:
        return self._pick(
            "thanks",
            (
                "You're welcome.",
                "Anytime.",
                "Happy to help.",
                "Of course.",
                "No problem.",
                "Glad I could help.",
            ),
        )

    def bye_reply(self, night: bool = False) -> str:
        if night:
            return self._pick("night", ("Good night.", "Sleep well.", "Night. Talk tomorrow."))
        return self._pick(
            "bye",
            (
                "Talk soon.",
                "Okay. I'm here when you need me.",
                "Bye for now.",
                "Sounds good. Just say the word if you need anything.",
            ),
        )

    def fresh_start_reply(self) -> str:
        return self._pick(
            "fresh",
            (
                "Fresh start. What's next?",
                "Clean slate. What's on your mind?",
                "Okay, new topic. Go ahead.",
            ),
        )

    def hush_reply(self) -> str:
        return self._pick(
            "hush",
            (
                "All quiet.",
                "Got it, staying quiet.",
                "Quiet now.",
            ),
        )

    def repeat_missing_reply(self) -> str:
        return self._pick(
            "repeat_missing",
            (
                "I haven't said anything yet in this session.",
                "There's nothing to repeat yet — ask me something first.",
            ),
        )

    def undo_note_reply(self) -> str:
        return self._pick(
            "undo_note",
            (
                "Removed that for you.",
                "Took that right off the list.",
                "Done — removed that.",
            ),
        )

    def undo_empty_reply(self) -> str:
        return self._pick(
            "undo_empty",
            (
                "Nothing recent to undo.",
                "There isn't a recent change left to undo.",
            ),
        )
