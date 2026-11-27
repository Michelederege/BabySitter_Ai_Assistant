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
SILERO_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
)
EMBEDDER_MODEL_URLS = (
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx",
    "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/vocab.txt",
)
LOCAL_BINDINGS = {"127.0.0.1", "::1", "localhost"}
# 0.0.0.0 and :: mean "every network interface", which is not private.
PUBLIC_BINDINGS = {"0.0.0.0", "::", ""}

# The exact bytes behind each allowed download, as SHA-256. A release asset
# behind a fixed address can still be replaced; a changed file is refused.
DOWNLOAD_SHA256 = {
    KEYWORD_MODEL_URL: "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
    KOKORO_MODEL_URLS[0]: "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a",
    KOKORO_MODEL_URLS[1]: "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    SILERO_MODEL_URL: "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f",
    EMBEDDER_MODEL_URLS[0]: "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    EMBEDDER_MODEL_URLS[1]: "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
}


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
    allowed = "https://api.github.com/repos/Michelederege/BabySitter_Ai_Assistant/releases/latest"
    if url != allowed:
        raise ValueError("That update address is not allowed.")


RELEASE_DOWNLOAD_PREFIX = (
    "https://github.com/Michelederege/BabySitter_Ai_Assistant/releases/download/"
)


def require_release_asset_url(url: str) -> None:
    """Only release files published on the BabySitter GitHub page, over https."""
    parsed = urllib.parse.urlsplit(url or "")
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host != "github.com"
        or parsed.username
        or parsed.password
        or not (url or "").startswith(RELEASE_DOWNLOAD_PREFIX)
    ):
        raise ValueError("That release download address is not allowed.")


def normalize_sha256(value: str) -> str:
    text = (value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:].strip()
    if len(text) != 64 or not all(ch in "0123456789abcdef" for ch in text):
        return ""
    return text


def require_sha256_file(expected_sha256: str, path) -> None:
    """Refuse a release file whose SHA-256 does not match its published digest."""
    import hashlib

    expected = normalize_sha256(expected_sha256)
    if not expected:
        raise ValueError("That release file did not come with a SHA-256 fingerprint.")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(
            "That download did not match the SHA-256 fingerprint for this release. Nothing was kept."
        )


def require_silero_url(url: str) -> None:
    """The voice detector has one allowed file, and only after a confirm."""
    if url != SILERO_MODEL_URL:
        raise ValueError("That voice-detector download is not allowed.")


def require_embedder_url(url: str) -> None:
    """The sharper memory has two allowed files, and only after a confirm."""
    if url not in EMBEDDER_MODEL_URLS:
        raise ValueError("That memory download is not allowed.")


def require_matching_bytes(url: str, raw: bytes) -> None:
    """Refuse a download whose SHA-256 is not the recorded one."""
    import hashlib

    expected = DOWNLOAD_SHA256.get(url)
    if not expected:
        raise ValueError("That download is not allowed.")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(
            "That download did not match the file this release expects. Nothing was kept."
        )


def require_matching_file(url: str, path) -> None:
    """Refuse a downloaded file whose SHA-256 is not the recorded one."""
    import hashlib

    expected = DOWNLOAD_SHA256.get(url)
    if not expected:
        raise ValueError("That download is not allowed.")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(
            "That download did not match the file this release expects. Nothing was kept."
        )


def keep_if_matching(url: str, path) -> bool:
    """True when a file already on disk has the recorded SHA-256.

    A file that is there but does not match is deleted, so the caller
    downloads a fresh copy. A file someone copied in by hand, or one an
    earlier version saved without a check, gets the same check as a new
    download.
    """
    from pathlib import Path

    path = Path(path)
    if not path.is_file():
        return False
    try:
        require_matching_file(url, path)
    except ValueError:
        path.unlink(missing_ok=True)
        return False
    return True


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
    """Read-only Gmail, Calendar, and Drive. No other Google host, and no http."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("That Google address is not allowed.")
    query = urllib.parse.parse_qs(parsed.query)
    if any(item.lower() == "media" for item in query.get("alt", [])):
        raise ValueError("Drive files are not downloaded. A Google Doc is read as plain text.")
    if path.rstrip("/").endswith("/export"):
        mime = (query.get("mimeType") or [""])[0].lower()
        if mime != "text/plain":
            raise ValueError("A Google Doc is read as plain text.")
    if host == "gmail.googleapis.com" and path.startswith("/gmail/v1/"):
        return
    if host == "www.googleapis.com" and path.startswith("/calendar/v3/"):
        return
    if host == "www.googleapis.com" and _drive_read_path(path):
        return
    raise ValueError(
        "Google mail, calendar, and Drive only use the read-only addresses."
    )


def _drive_read_path(path: str) -> bool:
    """List files. No upload, no permission change, no copy."""
    if path != "/drive/v3/files" and not path.startswith("/drive/v3/files/"):
        return False
    lowered = path.lower()
    blocked = ("upload", "/permissions", "/copy", "/comments", "/revisions")
    return not any(piece in lowered for piece in blocked)


def require_scrapecreators_url(url: str) -> None:
    """Reject any social-search address that is not the ScrapeCreators API."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host != SCRAPECREATORS_HOST:
        raise ValueError("Social search only talks to api.scrapecreators.com.")
    if parsed.username or parsed.password:
        raise ValueError("That address is not allowed.")
