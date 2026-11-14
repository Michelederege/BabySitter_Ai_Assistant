"""Search through a SearXNG the user runs on this PC.

The address is always 127.0.0.1. BabySitter does not pick a public
search site of its own. The query still leaves this PC if that
SearXNG is set up to ask other sites, so the caller waits for a yes.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from babysitter.security import require_searx_url


class SearxError(Exception):
    """The local search did not answer. The message never includes a key."""


def search_url(port: int, query: str) -> str:
    number = int(port)
    if number < 1 or number > 65535:
        raise SearxError("That SearXNG port is not allowed.")
    text = (query or "").strip()
    if not text:
        raise SearxError("Type what to search for. Nothing was sent.")
    url = "http://127.0.0.1:" + str(number) + "/search?" + urllib.parse.urlencode(
        {"q": text, "format": "json"}
    )
    require_searx_url(url)
    return url


def parse_results(payload: dict) -> str:
    rows = payload.get("results") if isinstance(payload, dict) else None
    lines: list[str] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Result")[:140]
        link = str(item.get("url") or "")
        lines.append(f"{title} — {link}" if link else title)
        if len(lines) == 5:
            break
    if not lines:
        return "No results from SearXNG."
    return "\n".join(lines)


def search(port: int, query: str, opener=None) -> str:
    url = search_url(port, query)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(url, timeout=8) as response:
            raw = response.read(200_000)
    except Exception as exc:
        raise SearxError("SearXNG did not answer. Is it running on this PC?") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SearxError("SearXNG sent something BabySitter could not read.") from exc
    if not isinstance(payload, dict):
        raise SearxError("SearXNG sent something BabySitter could not read.")
    return parse_results(payload)
