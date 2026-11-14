"""Look up the latest GitHub release when the user asks.

This does not download or install anything, and it does not sign the
program. Signing needs a certificate that lives with the publisher.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from babysitter.security import require_update_url
from babysitter.version import __version__


RELEASE_API = "https://api.github.com/repos/alex-de-rege/Ai-assistant-Babysitter/releases/latest"


class UpdateError(Exception):
    """The release check did not finish."""


def _numbers(text: str) -> tuple[int, ...]:
    digits = []
    for part in (text or "").lstrip("vV").split("."):
        number = ""
        for character in part:
            if character.isdigit():
                number += character
            else:
                break
        if number:
            digits.append(int(number))
    return tuple(digits) or (0,)


def is_newer(remote: str, current: str = __version__) -> bool:
    left = _numbers(remote)
    right = _numbers(current)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    return left > right


def describe_release(payload: dict, current: str = __version__) -> str:
    if not isinstance(payload, dict):
        raise UpdateError("GitHub did not return a release.")
    tag = str(payload.get("tag_name") or "").strip()
    page = str(payload.get("html_url") or "")
    if not tag:
        return "No published release yet. Nothing was downloaded."
    if is_newer(tag, current):
        parsed = urllib.parse.urlsplit(page)
        owned = (parsed.hostname or "") == "github.com" and "alex-de-rege/Ai-assistant-Babysitter" in (parsed.path or "")
        where = f" The page is {page}." if parsed.scheme == "https" and owned else ""
        return (
            f"Version {tag} is published. You are on {current}. "
            "BabySitter did not download it, and it does not sign the installer."
            + where
        )
    return f"You are on {current}, and {tag} is not newer. Nothing was downloaded."


def check_latest(opener=None, current: str = __version__) -> str:
    require_update_url(RELEASE_API)
    request = urllib.request.Request(
        RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "BabySitter"},
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=8) as response:
            raw = response.read(100_000)
    except Exception as exc:
        raise UpdateError("GitHub did not answer. Nothing was downloaded.") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub sent something BabySitter could not read.") from exc
    return describe_release(payload, current)
