"""Turn a reply into something that can be spoken.

The screen can keep the full answer. The voice gets a short, plain sentence.
Symbols and code fences are left out so they are not read aloud.
"""

from __future__ import annotations

import re


def strip_thinking(text: str) -> str:
    """Drop hidden thinking before anything is spoken or shown."""
    cleaned = re.sub(r"<think>.*?</think>", " ", text or "", flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<think>.*", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned


def plain_speech(text: str) -> str:
    """Drop markdown, code fences, and thinking. The words stay."""
    text = strip_thinking(text)
    kept: list[str] = []
    skipping_code = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            skipping_code = not skipping_code
            continue
        if skipping_code:
            continue
        cleaned = re.sub(r"[*_#`>|]+", "", line)
        cleaned = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", cleaned)
        cleaned = cleaned.strip()
        if cleaned:
            kept.append(cleaned)
    spoken = " ".join(kept)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken


def for_speech(text: str) -> str:
    """A short piece for one spoken line."""
    return plain_speech(text)[:400]


def first_sentence(text: str) -> str:
    spoken = plain_speech(text)
    if not spoken:
        return ""
    for mark in (". ", "? ", "! "):
        index = spoken.find(mark)
        if index != -1:
            return spoken[: index + 1]
    if spoken[-1] not in ".!?":
        return spoken + "."
    return spoken


def closed_lead(text: str) -> str | None:
    """A piece that is ready to say. None while the opening is still unfinished."""
    lead, rest = lead_and_rest(text)
    if lead and rest:
        return lead
    spoken = plain_speech(text)
    cut = spoken.rfind(",")
    if cut < 1 or cut >= len(spoken) - 1:
        return None
    chunk = spoken[:cut].strip()
    if len(chunk.split()) < 8:
        return None
    if chunk[-1] not in ".!?":
        chunk += "."
    return chunk


def lead_and_rest(text: str) -> tuple[str, str]:
    """The first sentence, then everything else that can be read later."""
    spoken = plain_speech(text)
    lead = first_sentence(spoken)
    if not lead:
        return "", ""
    return lead, spoken[len(lead) :].strip()


_YES = {"yes", "yeah", "yep", "yup", "sure", "please", "ok", "okay"}
_NO = {"no", "nope", "nah"}
_YES_PHRASES = {"tell me more", "read it", "read the rest", "go ahead", "go on"}
_NO_PHRASES = {"no thanks", "no thank you", "thats enough", "that's enough", "stop"}


def remainder_after(spoken_lead: str, reply: str) -> str:
    """The words still unread after the part that was already spoken."""
    plain = plain_speech(reply)
    lead = (spoken_lead or "").strip()
    if lead:
        bare = lead[:-1].rstrip() if lead[-1] in ".!?" else lead
        if bare and plain.startswith(bare):
            return plain[len(bare) :].lstrip(" \t.,!?;:").strip()
    return lead_and_rest(reply)[1]


_RESUME = {"carry on", "what were you saying", "keep going", "continue", "go on"}


def is_resume(text: str) -> bool:
    """True when the user wants the cut-off answer to continue."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    return " ".join(words) in _RESUME


def interrupt_note(heard: str) -> str:
    """What the model is told after a cut-off. Only the words already spoken."""
    spoken = (heard or "").strip()
    if not spoken:
        return "you were interrupted before you spoke."
    return f"you were interrupted after: {spoken}"


def more_answer(text: str) -> str | None:
    """Yes or no to “do you want to know more?” Anything else is a new question."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return None
    phrase = " ".join(words)
    if phrase in _NO_PHRASES or words[0] in _NO:
        return "no"
    if phrase in _YES_PHRASES or words[0] in _YES:
        return "yes"
    return None


def sentences(text: str) -> list[str]:
    spoken = plain_speech(text)
    if not spoken:
        return []
    found: list[str] = []
    start = 0
    for index, char in enumerate(spoken):
        if char in ".!?" and (index + 1 == len(spoken) or spoken[index + 1] == " "):
            piece = spoken[start : index + 1].strip()
            if piece:
                found.append(piece)
            start = index + 1
    tail = spoken[start:].strip()
    if tail:
        found.append(tail)
    return found


def voice_and_rest(text: str) -> tuple[str, str]:
    """Two or three sentences to say, and the rest for the screen."""
    parts = sentences(text)
    if not parts:
        return "", ""
    return " ".join(parts[:3]), " ".join(parts[3:]).strip()


def followup_phrase(text: str) -> str | None:
    """A hands-free follow-up. Empty means they are done. None means ignore it."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if not words:
        return None
    phrase = " ".join(words)
    if phrase in {"thanks thats all", "thanks that's all", "thats all", "that's all", "never mind", "nevermind"}:
        return ""
    if phrase in {"tell me more", "read the rest"} or is_resume(text) or more_answer(text) == "yes":
        return phrase
    if len(words) < 2:
        return None
    return phrase


def speech_chunks(text: str, limit: int = 400) -> list[str]:
    """Break a long reading into sentence-sized pieces the voice can say."""
    spoken = plain_speech(text)
    if not spoken:
        return []
    sentences: list[str] = []
    start = 0
    for index, char in enumerate(spoken):
        if char in ".!?" and (index + 1 == len(spoken) or spoken[index + 1] == " "):
            sentences.append(spoken[start : index + 1].strip())
            start = index + 1
    tail = spoken[start:].strip()
    if tail:
        sentences.append(tail)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def sapi_rate(speed_percent: int) -> int:
    """Map the speed slider (80–130) onto the Windows voice rate (−10 to 10)."""
    try:
        speed = int(speed_percent)
    except (TypeError, ValueError):
        speed = 100
    return max(-10, min(10, round((speed - 100) / 5)))
