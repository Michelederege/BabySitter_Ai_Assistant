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


# A dot after one of these is not the end of a sentence. "Dr. Smith is here."
_ABBREV = {"mr", "mrs", "ms", "dr", "st", "jr", "sr", "vs", "etc", "prof", "inc", "ltd"}


def _at_sentence_end(spoken: str, index: int) -> bool:
    """True when this mark ends a sentence, not an abbreviation."""
    if spoken[index] not in ".!?":
        return False
    if index + 1 < len(spoken) and spoken[index + 1] != " ":
        return False
    if spoken[index] != ".":
        return True
    start = index
    while start > 0 and spoken[start - 1].isalpha():
        start -= 1
    return spoken[start:index].lower() not in _ABBREV


def first_sentence(text: str) -> str:
    spoken = plain_speech(text)
    if not spoken:
        return ""
    for index in range(len(spoken)):
        if _at_sentence_end(spoken, index):
            return spoken[: index + 1]
    if spoken[-1] not in ".!?":
        return spoken + "."
    return spoken


def remembered_reply(reply: str, limit: int = 900) -> str:
    """What the next turn should still know. The voice keeps the short version."""
    text = strip_thinking(reply or "")
    text = re.sub(r"```", " ", text)
    text = re.sub(r"[*_#>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(".,;:")
    return (cut or text[:limit]).rstrip() + "."


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


def rest_after_lead(lead: str, spoken: str) -> str:
    """The sentences still waiting after the opening line was already sent to the voice."""
    bare = lead[:-1].rstrip() if (lead or "")[-1:] in ".!?" else (lead or "")
    if bare and (spoken or "").startswith(bare):
        return spoken[len(bare) :].lstrip(" \t,.;:!?")
    return ""


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


_ONE_WORD_FOLLOWUP = {"why", "how", "when", "where", "who"}


def sentences(text: str) -> list[str]:
    spoken = plain_speech(text)
    if not spoken:
        return []
    found: list[str] = []
    start = 0
    for index, _char in enumerate(spoken):
        if _at_sentence_end(spoken, index) or (spoken[index] in ".!?" and index + 1 == len(spoken)):
            piece = spoken[start : index + 1].strip()
            if piece:
                found.append(piece)
            start = index + 1
    tail = spoken[start:].strip()
    if tail:
        found.append(tail)
    return found


def unread_detail(spoken: str, reply: str) -> str:
    """The part of a reply that was not already shown as the spoken line.

    The window has one line for what was said and another for the rest.
    The rest must not start by repeating that spoken line.
    """
    raw = strip_thinking(reply or "").strip()
    lead = plain_speech(spoken)
    if not raw or not lead:
        return raw
    body, fences = _split_fences(raw)
    body_plain = plain_speech(body)
    if body_plain.startswith(lead):
        body_rest = body_plain[len(lead) :].strip()
    else:
        body_rest = remainder_after(lead, body)
    parts = [part for part in (body_rest, *fences) if part]
    return "\n\n".join(parts).strip()


def _split_fences(text: str) -> tuple[str, list[str]]:
    fences = re.findall(r"```.*?```", text or "", flags=re.DOTALL)
    body = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    return body, [fence.strip() for fence in fences if fence.strip()]


def voice_and_rest(text: str) -> tuple[str, str]:
    """Two or three sentences to say, and the rest for the screen.

    Code and lists longer than three items stay on the screen. The voice
    says one line about them.
    """
    parts = sentences(text)
    if not parts:
        return "", ""
    if _belongs_on_a_card(text):
        return spell_codes(parts[0]), ""
    spoken = " ".join(parts[:3])
    rest = " ".join(parts[3:]).strip()
    return spell_codes(spoken), rest


def spell_codes(text: str) -> str:
    """Read error codes and KB numbers one character at a time."""

    def spell(match) -> str:
        return " ".join(match.group(0))

    spoken = re.sub(r"\bKB\d+\b", spell, text or "", flags=re.IGNORECASE)
    return re.sub(r"\b0x[0-9A-Fa-f]+\b", spell, spoken)


def _belongs_on_a_card(text: str) -> bool:
    if "```" in (text or ""):
        return True
    bullets = 0
    for line in (text or "").splitlines():
        if re.match(r"\s*(?:[-*]|\d+[.)])\s+\S", line):
            bullets += 1
    return bullets > 3


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
    if len(words) == 1 and words[0] in _ONE_WORD_FOLLOWUP:
        return words[0]
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
    for index, _char in enumerate(spoken):
        if _at_sentence_end(spoken, index) or (spoken[index] in ".!?" and index + 1 == len(spoken)):
            sentences.append(spoken[start : index + 1].strip())
            start = index + 1
    tail = spoken[start:].strip()
    if tail:
        sentences.append(tail)
    chunks: list[str] = []
    current = ""
    bounded: list[str] = []
    for sentence in sentences:
        if len(sentence) <= limit:
            bounded.append(sentence)
            continue
        words = sentence.split()
        piece = ""
        for word in words:
            if piece and len(piece) + 1 + len(word) > limit:
                bounded.append(piece)
                piece = word
            else:
                piece = f"{piece} {word}".strip()
        if piece:
            bounded.append(piece)
    for sentence in bounded:
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
