"""Download the Silero voice detector after a confirm.

The file stays in the BabySitter folder. It is not loaded until the
voice-detector setting is on, and it never uses the graphics card.
"""

from __future__ import annotations

import urllib.request

from babysitter.paths import data_dir
from babysitter.security import keep_if_matching, require_matching_bytes, require_silero_url


SILERO_URL = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"


class SileroError(Exception):
    """The voice detector could not be saved."""


def silero_path():
    return data_dir() / "models" / "silero" / "silero_vad.onnx"


def download_silero(opener=None) -> str:
    require_silero_url(SILERO_URL)
    destination = silero_path()
    if keep_if_matching(SILERO_URL, destination):
        return "The sharper voice detector is already on this PC. Turn it on in Settings."
    destination.parent.mkdir(parents=True, exist_ok=True)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(SILERO_URL, timeout=60) as response:
            raw = response.read(5_000_000)
    except Exception as exc:
        raise SileroError("The voice detector did not download. Nothing was changed.") from exc
    if len(raw) < 1000:
        raise SileroError("That download was empty. Nothing was saved.")
    try:
        require_matching_bytes(SILERO_URL, raw)
    except ValueError as exc:
        raise SileroError(str(exc)) from None
    temporary = destination.with_suffix(".onnx.tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)
    return "The sharper voice detector is on this PC. Turn it on in Settings."
