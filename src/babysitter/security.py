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


def require_searx_url(url: str) -> None:
    """SearXNG stays on this computer. No other host, and only the search path."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or (parsed.hostname or "").lower() != "127.0.0.1":
        raise ValueError("Web search only talks to SearXNG on this computer (127.0.0.1).")
    if parsed.path != "/search" or parsed.username or parsed.password:
        raise ValueError("That search address is not allowed.")


def require_update_url(url: str) -> None:
    """One GitHub releases address, and only after the user asks."""
    allowed = "https://api.github.com/repos/michele-de-rege/Ai-assistant-Babysitter/releases/latest"
    if url != allowed:
        raise ValueError("That update address is not allowed.")


def require_silero_url(url: str) -> None:
    """The voice detector has one allowed file, and only after a confirm."""
    allowed = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
    if url != allowed:
        raise ValueError("That voice-detector download is not allowed.")


def require_google_oauth_url(url: str) -> None:
    """Sign-in and token refresh. Not Gmail, and not a place that sends mail."""
    allowed = {
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
    }
    parsed = urllib.parse.urlsplit(url)
    base = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
    if parsed.scheme != "https" or base not in allowed or parsed.username or parsed.password:
        raise ValueError("That Google sign-in address is not allowed.")


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
