"""Goals you say out loud. The list stays on this PC, on the Reminders page.

A goal is not a reminder. It does not ring. Saying the list shows the page.
A short follow-up, such as "done with that", only counts while that talk is
still open.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from babysitter.commands import QuickCommand, strip_lead

_LIST = {
    "say my goals",
    "say my goal",
    "what are my goals",
    "what are my goal",
    "whats my goals",
    "what's my goals",
    "whats my goal",
    "what's my goal",
    "what is my goal",
    "what is my goals",
    "read my goals",
    "read my goal",
    "read out my goals",
    "read me my goals",
    "show my goals",
    "show me my goals",
    "tell me my goals",
    "my goals",
    "list my goals",
    "find my goals",
    "find my goal",
    "pull up my goals",
    "pull up my goal",
    "look for my goals",
    "look for my goal",
    "locate my goals",
    "locate my goal",
    "open my goals",
    "open my goal",
    "where is my goal",
    "where is my goals",
    "where are my goals",
    "remind me of my goals",
    "remind me of my goal",
    "remind me my goals",
    "remind me about my goals",
    "remind me about my goal",
}

_ADD = (
    "add a goal to",
    "add a goal",
    "add goal to",
    "add goal",
    "my goal is to",
    "my goal is",
    "new goal",
    "set a goal to",
    "set a goal of",
    "set a goal",
    "set goal to",
    "set goal",
)

_ACT = (
    "i finished my goal",
    "i finished the goal",
    "done with the goal",
    "done with my goal",
    "finished the goal",
    "finished my goal",
    "complete the goal",
    "complete my goal",
    "complete goal",
    "mark the goal",
    "mark my goal",
    "drop the goal",
    "drop my goal",
    "remove the goal",
    "remove my goal",
    "delete the goal",
    "delete my goal",
)

_DROP_WORDS = {"drop", "remove", "delete"}

_FOLLOW_DONE = {
    "done",
    "done with that",
    "that's done",
    "thats done",
    "finished it",
    "i finished it",
    "i finished that",
    "mark it done",
    "that one is done",
    "that is done",
}

_FOLLOW_DROP = {
    "drop it",
    "drop that",
    "remove it",
    "delete it",
    "never mind that",
    "never mind that goal",
}

_LAST = {"", "last", "that", "it", "that one", "this one"}

_INDEX = (
    r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
)

_ORDINALS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

_NUMBER = (
    r"(?:the\s+|number\s+|goal\s+)*"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
)


def clean_goal(detail: str) -> str:
    """The goal itself, without a leading to, for, or of."""
    text = " ".join((detail or "").split()).strip(" .,")
    lowered = text.lower()
    for lead in ("to ", "for ", "of "):
        if lowered.startswith(lead):
            text = text[len(lead):].strip()
            lowered = text.lower()
    return text.strip(" .,")


def _phrase(text: str) -> tuple[str, str]:
    original = strip_lead(text)
    words = re.findall(r"[a-z0-9']+", original.lower())
    return " ".join(words), original


def match_goal(text: str) -> QuickCommand | None:
    """A full goal sentence. Short follow-ups are handled separately."""
    phrase, original = _phrase(text)
    if not phrase:
        return None
    if phrase in _LIST:
        return QuickCommand("goals")
    for label in _ADD:
        if phrase == label:
            return QuickCommand("goal_add", detail="")
        if phrase.startswith(label + " "):
            return QuickCommand("goal_add", detail=clean_goal(_tail(original, label)))
    for label in _ACT:
        if phrase != label and not phrase.startswith(label + " "):
            continue
        detail = clean_goal(_tail(original, label)) if phrase.startswith(label + " ") else ""
        kind = "goal_drop" if label.split()[0] in _DROP_WORDS else "goal_done"
        return QuickCommand(kind, detail=detail)
    numbered = re.fullmatch(
        r"(done with|i finished|finish|finished|complete|drop|remove|delete|mark) "
        r"(?:the |my )?goal(?: (?:number )?(.+))?",
        phrase,
    )
    if numbered:
        kind = "goal_drop" if numbered.group(1) in _DROP_WORDS else "goal_done"
        return QuickCommand(kind, detail=_goal_target(numbered.group(2) or ""))
    placed = re.fullmatch(
        rf"(done with|i finished|finish|finished|complete|drop|remove|delete|mark) "
        rf"(?:the |my )?({_INDEX}) goal(?: (?:as )?done)?",
        phrase,
    )
    if placed:
        kind = "goal_drop" if placed.group(1) in _DROP_WORDS else "goal_done"
        return QuickCommand(kind, detail=placed.group(2))
    return None


def goal_followup(text: str, items: list[dict], last_id: str = "") -> QuickCommand | None:
    """A short line while a goal talk is still open. None for anything else."""
    phrase, original = _phrase(text)
    if not phrase:
        return None
    if phrase in {"say them again", "read them again", "say that list again"}:
        return QuickCommand("goals")
    if phrase in _FOLLOW_DONE:
        return QuickCommand("goal_done", detail="last")
    if phrase in _FOLLOW_DROP:
        return QuickCommand("goal_drop", detail="last")
    added = re.fullmatch(r"(?:add another|another goal|another one)(?: to)?(?: (.+))?", phrase)
    if added:
        detail = ""
        if added.group(1):
            detail = clean_goal(
                _tail(original, "add another")
                or _tail(original, "another goal")
                or _tail(original, "another one")
            )
        return QuickCommand("goal_add", detail=detail)
    pointed = re.fullmatch(
        rf"(?:(done with|finish|finished|complete|drop|remove|delete|mark)\s+)?"
        rf"{_NUMBER}(?:\s+one|\s+goal)?(?:\s+(?:is\s+)?done)?",
        phrase,
    )
    if pointed is None:
        return None
    token = pointed.group(2)
    if _as_number(token) is None:
        return None
    verb = pointed.group(1) or ""
    if verb in _DROP_WORDS:
        return QuickCommand("goal_drop", detail=token)
    if verb or phrase.endswith("done"):
        return QuickCommand("goal_done", detail=token)
    return QuickCommand("goal_show", detail=token)


def open_goals(items: list[dict]) -> list[dict]:
    return [item for item in items if str(item.get("done") or "") != "yes" and str(item.get("text") or "").strip()]


def goal_line(item: dict) -> str:
    text = " ".join(str(item.get("text") or "").split()) or "Goal"
    if str(item.get("done") or "") == "yes":
        return f"Done. {text}"
    return text


def goal_rows(items: list[dict]) -> list[tuple[str, str, str]]:
    """The lines on the Reminders page: number, id, and the words a pin keeps."""
    rows = []
    number = 0
    for item in items:
        text = " ".join(str(item.get("text") or "").split()) or "Goal"
        item_id = str(item.get("id") or "")
        if str(item.get("done") or "") == "yes":
            rows.append((f"Done. {text}", item_id, text))
            continue
        number += 1
        rows.append((f"{number}. {text}", item_id, text))
    return rows


def goals_speech(items: list[dict]) -> str:
    """What to say when someone asks for the list."""
    pending = open_goals(items)
    finished = [item for item in items if str(item.get("done") or "") == "yes"]
    if not pending and not finished:
        return "You don't have a goal yet. Say add a goal, and what it is."
    if not pending:
        return "Every goal is done."
    names = [" ".join(str(item.get("text") or "Goal").split()) for item in pending]
    if len(names) == 1:
        return f"Your goal is {names[0]}."
    if len(names) == 2:
        return f"Your goals are {names[0]} and {names[1]}."
    numbered = ". ".join(f"{number}. {name}" for number, name in enumerate(names, start=1))
    return f"You have {len(names)} goals. {numbered}."


def goals_detail(items: list[dict]) -> str:
    """The same list, one goal on each line, for the screen."""
    if not items:
        return "No goals yet."
    return "\n".join(row[0] for row in goal_rows(items))


@dataclass
class GoalTurn:
    route: str
    speech: str
    detail: str
    items: list[dict] = field(default_factory=list)
    last_id: str = ""
    added_id: str = ""
    goals_open: bool = False


def apply_spoken(items: list[dict], command: QuickCommand, last_id: str = "") -> GoalTurn:
    """Apply one goal command to a copy of the list. Nothing is written to disk."""
    stored = [dict(item) for item in items]
    kind = command.kind
    added_id = ""
    if kind == "goals":
        speech = goals_speech(stored)
        pending = open_goals(stored)
        last_id = pending[0]["id"] if len(pending) == 1 else ""
    elif kind == "goal_show":
        found, speech = _resolve(command.detail, stored, last_id)
        if found is not None:
            name = " ".join(str(found.get("text") or "Goal").split())
            speech = f"That one is {name}."
            last_id = str(found.get("id") or "")
    elif kind == "goal_add":
        detail = clean_goal(command.detail)
        if not detail:
            speech = "Say the goal after add a goal. Nothing was saved."
        elif any(str(item.get("text") or "").strip().lower() == detail.lower() for item in open_goals(stored)):
            speech = f"That's already a goal. {detail}."
            found, _reason = _resolve(detail, stored, "")
            if found is not None:
                last_id = str(found.get("id") or "")
        else:
            added_id = uuid.uuid4().hex[:10]
            stored.append({"id": added_id, "text": detail, "done": ""})
            last_id = added_id
            speech = (
                f"Added the goal, {detail}. It is on the Reminders page. "
                "Say undo in the next 10 seconds to remove it."
            )
    elif kind in {"goal_done", "goal_drop"}:
        found, speech = _resolve(command.detail, stored, last_id, include_done=True)
        if found is not None:
            name = " ".join(str(found.get("text") or "Goal").split())
            last_id = str(found.get("id") or "")
            if kind == "goal_drop":
                stored = [item for item in stored if item.get("id") != found.get("id")]
                speech = f"Dropped {name}."
                last_id = ""
            elif str(found.get("done") or "") == "yes":
                speech = f"{name} is already done."
            else:
                found["done"] = "yes"
                speech = f"{name} is done. It stays on the Reminders page."
    else:
        speech = goals_speech(stored)
    return GoalTurn(kind, speech, goals_detail(stored), stored, last_id, added_id, True)


def conversation(lines: list[str]) -> list[GoalTurn]:
    """One spoken exchange after another, the way the window decides.

    A short follow-up only applies while the goal talk is still open.
    Another command, including the other local ones, closes that talk.
    """
    from babysitter.commands import match_quick_command
    from babysitter.intents import match_tool
    from babysitter.plugins.voice.speech import followup_phrase

    items: list[dict] = []
    last_id = ""
    talking = False
    said = ""
    turns: list[GoalTurn] = []
    for line in lines:
        if followup_phrase(line) == "":
            talking = False
            last_id = ""
            turns.append(GoalTurn("stop", "Okay. I'm here when you need me.", goals_detail(items), items, "", "", False))
            continue
        command = goal_followup(line, items, last_id) if talking else None
        if command is None:
            command = match_goal(line)
        if command is not None:
            turn = apply_spoken(items, command, last_id)
            items = turn.items
            last_id = turn.last_id
            talking = True
            said = turn.speech
            turns.append(turn)
            continue
        quick = match_quick_command(line)
        if quick is not None and quick.kind == "repeat":
            speech = said or "I have not said anything yet."
            turns.append(GoalTurn("repeat", speech, goals_detail(items), items, last_id, "", talking))
            continue
        if quick is not None and quick.kind == "hush":
            turns.append(GoalTurn("hush", "Okay.", goals_detail(items), items, last_id, "", talking))
            continue
        talking = False
        last_id = ""
        if quick is not None:
            turns.append(GoalTurn(quick.kind, "", goals_detail(items), items, "", "", False))
            continue
        route = "tool" if match_tool(line) is not None else "model"
        turns.append(GoalTurn(route, "", goals_detail(items), items, "", "", False))
    return turns


def _goal_target(detail: str) -> str:
    """The goal a done or drop sentence points at.

    "done" on its own means the one just talked about. "get the shipment done"
    keeps the last word, because that word is part of the goal.
    """
    text = clean_goal(detail)
    lowered = text.lower()
    if lowered in {"done", "as done", "complete", "completed"}:
        return ""
    trimmed = re.sub(r"\s+(?:as\s+)?done$", "", lowered).strip()
    if trimmed and trimmed != lowered and _as_number(trimmed) is not None:
        return trimmed
    return text


def _resolve(
    detail: str,
    items: list[dict],
    last_id: str,
    include_done: bool = False,
) -> tuple[dict | None, str]:
    pending = open_goals(items)
    text = " ".join((detail or "").split())
    lowered = text.lower()
    if lowered in _LAST:
        if last_id:
            pool = items if include_done else pending
            found = next((item for item in pool if str(item.get("id") or "") == last_id), None)
            if found is not None:
                return found, ""
        if len(pending) == 1:
            return pending[0], ""
        if not pending:
            return None, "You don't have an open goal."
        return None, _which(pending)
    number = _as_number(lowered)
    if number is not None:
        if not pending:
            return None, "You don't have an open goal."
        if number < 1 or number > len(pending):
            if len(pending) == 1:
                name = " ".join(str(pending[0].get("text") or "Goal").split())
                return None, f"There is one goal, {name}."
            return None, f"The list goes from 1 to {len(pending)}."
        return pending[number - 1], ""
    words = [
        word
        for word in re.findall(r"[a-z0-9']+", lowered)
        if word not in {"the", "a", "my", "goal", "number", "to", "as"}
    ]
    if words and set(words) <= {"done", "complete", "completed"}:
        words = []
    if not words:
        if len(pending) == 1:
            return pending[0], ""
        return None, _which(pending) if pending else "You don't have an open goal."
    hits = _named(pending, words)
    if len(hits) == 1:
        return hits[0], ""
    if not hits and include_done:
        finished = [item for item in items if str(item.get("done") or "") == "yes"]
        hits = _named(finished, words)
        if len(hits) == 1:
            return hits[0], ""
    if not hits:
        return None, "I don't see that goal."
    return None, _which(hits)


def _named(items: list[dict], words: list[str]) -> list[dict]:
    hits = []
    for item in items:
        name = str(item.get("text") or "").lower()
        if all(word in name for word in words):
            hits.append(item)
    return hits


def _which(items: list[dict]) -> str:
    names = [f"{number}. {' '.join(str(item.get('text') or 'Goal').split())}" for number, item in enumerate(items, start=1)]
    return "Which one? " + " ".join(names)


def _as_number(text: str) -> int | None:
    token = " ".join(text.lower().split())
    token = re.sub(r"^(?:the|goal|number)\s+", "", token)
    token = re.sub(r"^(?:the|goal|number)\s+", "", token)
    token = re.sub(r"\s+(?:one|goal)$", "", token)
    if token.isdigit():
        return int(token)
    return _ORDINALS.get(token)


def _tail(original: str, label: str) -> str:
    words = re.findall(r"[A-Za-z0-9']+", original)
    lowered = [word.lower() for word in words]
    label_words = label.lower().split()
    for start in range(len(lowered) - len(label_words) + 1):
        if lowered[start: start + len(label_words)] == label_words:
            return " ".join(words[start + len(label_words):])
    return ""
