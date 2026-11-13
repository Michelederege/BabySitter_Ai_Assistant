"""Turn a reply into something that can be spoken.

The screen can keep the full answer. The voice gets a short, plain sentence.
Symbols and code fences are left out so they are not read aloud.
"""

from __future__ import annotations

import re


def plain_speech(text: str) -> str:
    """Drop markdown and code fences. The words stay."""
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
