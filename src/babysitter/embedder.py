"""A tiny embedder that stays inside this process.

It does not load a model and it does not touch the graphics card.
Saved facts are ranked on the processor so a second model is never loaded
just to remember something.
"""

from __future__ import annotations

import hashlib
import math
import re


DIMS = 64


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def embed(text: str, dims: int = DIMS) -> tuple[float, ...]:
    """A stable hashed bag of words, normalized so scores stay comparable."""
    vector = [0.0] * dims
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = digest[0] % dims
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def similarity(left: str, right: str) -> float:
    a = embed(left)
    b = embed(right)
    return sum(x * y for x, y in zip(a, b))


def rank_texts(query: str, texts: list[str], k: int = 2, floor: float = 0.2) -> list[str]:
    """The closest texts at or above the floor. Order is best first."""
    scored: list[tuple[float, str]] = []
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        score = similarity(query, cleaned)
        if score >= floor:
            scored.append((score, cleaned))
    scored.sort(key=lambda item: item[0], reverse=True)
    found: list[str] = []
    for _score, text in scored:
        if text not in found:
            found.append(text)
        if len(found) >= k:
            break
    return found
