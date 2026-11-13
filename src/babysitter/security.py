"""Small rules about who BabySitter is allowed to talk to.

Ollama stays on this computer (127.0.0.1). Social search, if you turn it
on, may also talk to api.scrapecreators.com. Nothing else.
"""

from __future__ import annotations

import urllib.parse

LOCAL_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
SCRAPECREATORS_HOST = "api.scrapecreators.com"
KEYWORD_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
LOCAL_BINDINGS = {"127.0.0.1", "::1", "localhost"}
# 0.0.0.0 and :: mean "every network interface", which is not private.
PUBLIC_BINDINGS = {"0.0.0.0", "::", ""}


def require_local_host(host: str) -> None:
    if host != LOCAL_HOST:
        raise ValueError(
            "BabySitter only talks to Ollama on this computer (127.0.0.1)."
        )


def bind_is_private(addresses: list[str]) -> bool:
    """True when every listener is loopback, not the whole network."""
    if not addresses:
        return False
    return all(address in LOCAL_BINDINGS for address in addresses)


def bind_is_public(addresses: list[str]) -> bool:
    return any(address in PUBLIC_BINDINGS for address in addresses)


def require_keyword_model_url(url: str) -> None:
    """The keyword model has one allowed address, and only after you confirm."""
    if url != KEYWORD_MODEL_URL:
        raise ValueError("That model download is not allowed.")


def require_scrapecreators_url(url: str) -> None:
    """Reject any social-search address that is not the ScrapeCreators API."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != SCRAPECREATORS_HOST:
        raise ValueError("Social search only talks to api.scrapecreators.com.")
    if parsed.username or parsed.password:
        raise ValueError("That address is not allowed.")
