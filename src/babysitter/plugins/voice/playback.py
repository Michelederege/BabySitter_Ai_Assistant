"""Shared playback so a stop can land inside one short block.

Kokoro, the filler clips, and the tests all use this. The block is 10 ms.
Stop is checked before every block, and the latest block is published so
echo cancellation can subtract it. Publishing is best-effort.
"""

from __future__ import annotations

import threading
import time


_lock = threading.Lock()
_latest = b""
_when = 0.0

# A block older than this is not "what is playing now". Before 0.28.1 the
# last block of a reply stayed forever, so echo cancellation kept
# subtracting it from the microphone and talk-over kept firing in silence.
FRESH_SECONDS = 0.3


def publish_playback(pcm: bytes) -> None:
    global _latest, _when
    with _lock:
        _latest = bytes(pcm)
        _when = time.monotonic()


def latest_playback() -> bytes:
    """The block playing now, or b"" when nothing has played in the last 0.3 s."""
    with _lock:
        if not _latest or time.monotonic() - _when > FRESH_SECONDS:
            return b""
        return _latest


def clear_playback() -> None:
    publish_playback(b"")


def preview_pcm(samples, limit: int = 1600) -> bytes:
    """A short int16 view of float samples, for the echo reference."""
    sliced = samples[:limit]
    try:
        import numpy as np

        arr = np.asarray(sliced, dtype=np.float32)
        return np.clip(arr * 32767.0, -32767.0, 32767.0).astype("<i2").tobytes()
    except ImportError:
        out = bytearray()
        for value in sliced:
            clamped = max(-1.0, min(1.0, float(value)))
            out += int(clamped * 32767).to_bytes(2, "little", signed=True)
        return bytes(out)


def play_pcm_blocks(samples, sample_rate: int, stop_event, write, block_ms: int = 10, publish=None) -> bool:
    """Play until the end. False when stop was set, including mid-buffer."""
    block = max(1, int(int(sample_rate) * block_ms / 1000))
    position = 0
    total = len(samples)
    while position < total:
        if stop_event.is_set():
            return False
        chunk = samples[position : position + block]
        if publish is not None:
            try:
                publish(preview_pcm(chunk))
            except Exception:
                pass
        write(chunk)
        position += block
    return not stop_event.is_set()
