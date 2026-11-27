"""Requests no command matched, turned into one of BabySitter's own commands, after a yes.

"Put dentist on Friday at 3" matches nothing, so before 0.31 it went to the
model as a question and nothing happened. Now the model may rewrite it into
one command sentence from a short fixed list. That sentence goes through the
same parser as anything you say, and only these kinds are kept: a reminder
with a time, a timer, a fact to remember, a goal, a journal task. Nothing is
done until you say yes, and the question you hear is built from the parsed
command, not from the model's words.
"""

from __future__ import annotations

import re
from datetime import datetime

from babysitter.commands import QuickCommand, match_quick_command, spoken_when, strip_lead, timer_label

# The only kinds the model can lead to. Opening files or apps, power, mail and
# anything that sends words off this PC are left out on purpose.
ALLOWED = {"remind", "timer", "remember", "goal_add", "task_start"}

SCHEMA = {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
}

_ACTION_START = re.compile(
    r"^(?:put|add|schedule|book|set|make|create|remind|note|write|jot|save|keep|log|track|start|begin|"
    r"wake|alert|ping|nudge|tell me|let me know|don't let me forget|dont let me forget|i need to|i have to|"
    r"i've got|ive got|i have got|i gotta|i got|i should|i must|i want to remember|my [\w']+(?: \w+)? is|block|plan|give me)\b"
)
_TIME_WORD = re.compile(
    r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight|tomorrow|tonight|today|morning|afternoon|evening|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|next week|minutes?|hours?|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)\b"
)
_QUESTION = re.compile(r"^(?:what|why|how|who|where|which|is|are|was|were|do|does|did|can i|could i|should i|tell me about|explain)\b")


def looks_like_action(text: str) -> bool:
    """Worth one quick try: it starts like an instruction, or names a time without asking something."""
    phrase = " ".join(re.findall(r"[a-z0-9:'']+", strip_lead(text or "").lower()))
    if not phrase or len(phrase.split()) > 30:
        return False
    if _QUESTION.match(phrase):
        return False
    if _ACTION_START.match(phrase):
        return True
    return bool(_TIME_WORD.search(phrase)) and bool(
        re.search(r"\b(?:appointment|meeting|class|practice|game|exam|test|call|dentist|doctor|party|deadline|due|shift|pickup|pick up)\b", phrase)
    )


def system_prompt(now: datetime) -> str:
    today = now.strftime("%A, %B %d, %Y, %I:%M %p").replace(" 0", " ")
    return (
        "You turn one spoken request into exactly one command for a desktop assistant, or nothing.\n"
        f"Right now it is {today}.\n"
        "The only commands, written exactly in these shapes:\n"
        "remind me on <weekday or Month day> at <h:mm am/pm> to <thing>\n"
        "remind me tomorrow at <h:mm am/pm> to <thing>\n"
        "remind me at <h:mm am/pm> to <thing>\n"
        "remind me in <number> minutes to <thing>\n"
        "set a timer for <number> minutes\n"
        "remember that <fact>\n"
        "add a goal to <goal>\n"
        "start a task called <name>\n"
        "Rules:\n"
        "- Always write am or pm. With no am or pm, pick the one a person most likely means: "
        "an appointment or practice at 3 is 3 pm, waking up at 6:30 is 6:30 am.\n"
        "- A day with no time at all is 9:00 am.\n"
        "- <thing> is short, in the person's own words, without 'I have' or 'put': "
        "'go to the dentist', 'doctor's appointment', 'soccer practice'. Waking up is 'wake up'.\n"
        "- A note, fact or something to keep is 'remember that <fact>'.\n"
        "- Never add details they did not say.\n"
        "- A question, a chat, maths, writing, or anything else is an empty command.\n"
        "Examples:\n"
        "put dentist on Friday at 3 -> remind me on Friday at 3:00 pm to go to the dentist\n"
        "make a note that the gate code is 4412 -> remember that the gate code is 4412\n"
        "block out 4 pm for studying -> remind me at 4:00 pm to study\n"
        "what's the capital of France -> (empty)\n"
        'Answer only JSON: {"command": "..."}'
    )


def _content_words(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "that", "this", "remind", "call", "called", "about", "set", "timer",
            "minutes", "goal", "task", "start", "add", "remember", "tomorrow"}
    return {word for word in re.findall(r"[a-z]{3,}", (text or "").lower()) if word not in stop}


def _shares_a_word(kept: set[str], said: set[str]) -> bool:
    """Loosely, so "study" and "studying", "run" and "running" are the same word."""
    for a in kept:
        for b in said:
            n = min(len(a), len(b), 5)
            if a[:n] == b[:n]:
                return True
    return False


def accept(heard: str, command: str) -> QuickCommand | None:
    """The model's sentence, parsed by the ordinary parser. None unless it is a kept kind and fits what was said."""
    command = " ".join(str(command or "").split())
    if not command or len(command) > 200:
        return None
    parsed = match_quick_command(command)
    if parsed is None or parsed.kind not in ALLOWED:
        return None
    if parsed.kind == "remind" and not parsed.when:
        return None  # a reminder that never rings is not worth a question
    if parsed.kind in {"remind", "timer"} and not _TIME_WORD.search(strip_lead(heard or "").lower()):
        return None  # "schedule my haircut" names no time: the model would be making one up
    if parsed.kind == "remind":
        parsed = _wake_in_the_morning(heard, parsed)
    if parsed.kind == "timer" and parsed.seconds <= 0:
        return None
    if parsed.kind != "timer":
        # The note must come from what was said, so the model cannot make one up.
        said = _content_words(heard)
        kept = _content_words(parsed.detail)
        if kept and not _shares_a_word(kept, said):
            return None
    return parsed


def _wake_in_the_morning(heard: str, parsed: QuickCommand) -> QuickCommand:
    """'Wake me at half past six' is the morning, whatever am or pm the model wrote."""
    from dataclasses import replace
    from datetime import timedelta

    lowered = (heard or "").lower()
    if not re.search(r"\bwake\b|\bget up\b", lowered) or re.search(r"\b(?:pm|p\.m|evening|tonight|afternoon)\b", lowered):
        return parsed
    moment = datetime.fromisoformat(parsed.when)
    if moment.hour < 12:
        return parsed
    morning = moment - timedelta(hours=12)
    if morning <= datetime.now().astimezone():
        morning += timedelta(days=1)
    return replace(parsed, when=morning.isoformat(timespec="seconds"))


def confirm_line(parsed: QuickCommand, now: datetime | None = None) -> str:
    """The question you hear, built from the parsed command."""
    detail = " ".join((parsed.detail or "").split()).strip(" .")
    if parsed.kind == "remind":
        moment = datetime.fromisoformat(parsed.when)
        thing = re.sub(r"^(?:to|about)\s+", "", detail, flags=re.IGNORECASE) or "your reminder"
        return f"Set a reminder for {spoken_when(moment, now)}: {thing}?"
    if parsed.kind == "timer":
        return f"Start a timer for {timer_label(parsed.seconds)}?"
    if parsed.kind == "remember":
        return f"Remember that {detail}?"
    if parsed.kind == "goal_add":
        return f"Add the goal: {detail}?"
    if parsed.kind == "task_start":
        name = re.sub(r"^called\s+", "", detail, flags=re.IGNORECASE)
        return f"Start the task {name} in your journal?"
    return ""


def suggest(client, model: str, heard: str, num_ctx: int, *, num_batch=None, keep_alive=None, now: datetime | None = None):
    """(command sentence, parsed command), or None. Any failure is None, and the line goes to chat as before."""
    now = now or datetime.now().astimezone()
    try:
        kwargs = {"num_batch": num_batch}
        if keep_alive is not None:
            kwargs["keep_alive"] = keep_alive
        answer = client.ask_json(model, system_prompt(now), strip_lead(heard) or heard, num_ctx, SCHEMA, timeout=20, **kwargs)
    except Exception:
        return None
    command = str(answer.get("command") or "")
    parsed = accept(heard, command)
    if parsed is None:
        return None
    return command, parsed
