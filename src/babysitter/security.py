"""Small rules about who BabySitter is allowed to talk to.

Ollama stays on this computer (127.0.0.1). Social search, if you turn it
on, may also talk to api.scrapecreators.com. Google mail and calendar, if
you turn them on, may talk to gmail.googleapis.com and www.googleapis.com.
Nothing else.
"""

from __future__ import annotations

import urllib.parse

LOCAL_HOST = "127.0.0.1"
OLLAMA_PORT = 11434
SCRAPECREATORS_HOST = "api.scrapecreators.com"
KEYWORD_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
KOKORO_MODEL_URLS = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin",
)
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


def require_kokoro_model_url(url: str) -> None:
    """Heart and Sarah has two allowed files, and only after you confirm."""
    if url not in KOKORO_MODEL_URLS:
        raise ValueError("That voice download is not allowed.")


def require_keyword_model_url(url: str) -> None:
    """The keyword model has one allowed address, and only after you confirm."""
    if url != KEYWORD_MODEL_URL:
        raise ValueError("That model download is not allowed.")


def require_google_url(url: str) -> None:
    """Read-only Gmail and Calendar. No other Google host, and no http."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("That Google address is not allowed.")
    if host == "gmail.googleapis.com" and path.startswith("/gmail/v1/"):
        return
    if host == "www.googleapis.com" and path.startswith("/calendar/v3/"):
        return
    raise ValueError(
        "Google mail and calendar only use the read-only Gmail and Calendar addresses."
    )


def require_scrapecreators_url(url: str) -> None:
    """Reject any social-search address that is not the ScrapeCreators API."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != SCRAPECREATORS_HOST:
        raise ValueError("Social search only talks to api.scrapecreators.com.")
    if parsed.username or parsed.password:
        raise ValueError("That address is not allowed.")
