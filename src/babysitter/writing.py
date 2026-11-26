"""The Google Doc someone is writing, as plain text for the local model.

BabySitter reads one document: the Google Doc in the front window, or the
one changed in the last two hours. The text stays in the question sent to
Ollama on this PC. A download of the file, and any format other than plain
text, is refused before the request is made.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from babysitter.plugins.tools.google_account import (
    GoogleError,
    _safe_id,
    doc_export_url,
    docs_list_url,
    http_get_text,
)

GOOGLE_DOC = "application/vnd.google-apps.document"
FRESH_MINUTES = 120

WRITING_RULES = (
    "The draft above is the document they are writing. Answer from that text. "
    "When they ask how to strengthen it, name a specific change and why it helps. "
    "When you use a fact that is not in the draft or this conversation, add a credit line "
    "in this shape: Source: Author. Title. Where it was found. Date. "
    "Use only a source that was actually given to you. "
    "If you do not have one, say you would need to look it up. "
    "Do not invent an author, a title, a date, or a link."
)

CITATION_SUMMARY = (
    "Answer from these search results. For each fact you use, add a credit line: "
    "Source: Author. Title. Where it was found. Date. "
    "Use only a source that appears in the results. Do not invent one."
)


@dataclass(frozen=True)
class DraftChoice:
    name: str
    file_id: str
    modified: datetime | None
    account: int


@dataclass(frozen=True)
class OpenDraft:
    name: str
    speech: str
    note: str
    opening: str


def title_from_window(title: str) -> str:
    """The document name in a Google Docs window title. Empty for any other window."""
    text = " ".join((title or "").split())
    lowered = text.casefold()
    mark = "google docs"
    if mark not in lowered:
        return ""
    head = text[: lowered.index(mark)]
    return head.strip(" -|–—")


def _loose(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _same_doc(file_name: str, window_name: str) -> bool:
    left = _loose(file_name)
    right = _loose(window_name)
    if len(left) < 2 or len(right) < 2:
        return False
    return left == right


def _modified(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def choices_from_listing(payload: dict, account: int) -> list[DraftChoice]:
    files = payload.get("files") if isinstance(payload, dict) else None
    found: list[DraftChoice] = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("mimeType") or "") != GOOGLE_DOC:
            continue
        name = " ".join(str(item.get("name") or "").split())[:120]
        file_id = str(item.get("id") or "")
        if not name or not _safe_id(file_id):
            continue
        found.append(DraftChoice(name, file_id, _modified(item.get("modifiedTime")), account))
    return found


def pick_draft(
    choices: list[DraftChoice],
    window_title: str,
    now: datetime,
    *,
    fresh_minutes: int = FRESH_MINUTES,
    allow_stale: bool = False,
) -> DraftChoice | None:
    """The doc in front, otherwise a doc changed recently. An old doc stays out."""
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    wanted = title_from_window(window_title)
    if wanted:
        matched = [item for item in choices if _same_doc(item.name, wanted)]
        if matched:
            return max(matched, key=lambda item: item.modified or datetime.min.replace(tzinfo=timezone.utc))
    if not choices:
        return None
    newest = max(choices, key=lambda item: item.modified or datetime.min.replace(tzinfo=timezone.utc))
    if allow_stale:
        return newest
    if newest.modified is None:
        return None
    if moment - newest.modified <= timedelta(minutes=fresh_minutes):
        return newest
    return None


def clip_draft(text: str, limit: int = 4000) -> str:
    """Keep the opening and the ending, which is where the writing is happening."""
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if limit < 400:
        limit = 400
    if len(clean) <= limit:
        return clean
    head = max(40, limit // 3)
    tail = limit - head - 5
    if tail < 40:
        return clean[:limit]
    return clean[:head].rstrip() + "\n…\n" + clean[-tail:].lstrip()


def draft_note(name: str, modified: datetime | None, text: str, limit: int = 4000) -> str:
    when = modified.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if modified else "recently"
    body = clip_draft(text, limit)
    return (
        f'Open Google Doc "{name}", changed {when}. '
        "This text is on this PC and is the draft they are writing.\n"
        f"{body}\n"
        f"{WRITING_RULES}"
    )


def opening_of(text: str, limit: int = 180) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def writing_miss(prompt: str) -> str:
    """Tell the model it does not have the paper, when the question is about the writing."""
    lowered = (prompt or "").casefold()
    marks = ("paper", "essay", "draft", "paragraph", "thesis", "citation", "my writing", "this doc")
    if any(mark in lowered for mark in marks):
        return (
            "No Google Doc is in the front window, and none was changed in the last two hours. "
            "Do not invent the draft."
        )
    return ""


def read_open_draft(
    tokens: list[str],
    window_title: str,
    *,
    fetch_json=None,
    fetch_text=None,
    now: datetime | None = None,
    limit: int = 4000,
    fresh_minutes: int = FRESH_MINUTES,
    allow_stale: bool = False,
) -> OpenDraft | None:
    """One draft note. A failed account does not hide a doc on the other account."""
    from babysitter.plugins.tools.google_account import http_get_json

    load_json = fetch_json or http_get_json
    load_text = fetch_text or http_get_text
    moment = now or datetime.now(timezone.utc)
    found: list[DraftChoice] = []
    usable = [token for token in tokens if token]
    for index, token in enumerate(usable):
        try:
            payload = load_json(docs_list_url(), token)
        except GoogleError:
            continue
        found.extend(choices_from_listing(payload, index))
    choice = pick_draft(found, window_title, moment, fresh_minutes=fresh_minutes, allow_stale=allow_stale)
    if choice is None:
        return None
    try:
        text = load_text(doc_export_url(choice.file_id), usable[choice.account])
    except GoogleError:
        speech = f"The Google Doc {choice.name} could not be read. Nothing in it was changed."
        return OpenDraft(choice.name, speech, speech, "")
    note = draft_note(choice.name, choice.modified, text, limit)
    for token in usable:
        if token and token in note:
            hidden = "The Google Doc could not be shown."
            return OpenDraft(choice.name, hidden, hidden, "")
    start = opening_of(text)
    speech = f"You're writing {choice.name}."
    if start:
        speech += f" It opens with: {start}"
    return OpenDraft(choice.name, speech, note, start)
