"""History and saved facts, encrypted on disk with Windows' own protection (DPAPI).

The same protection as the Google token: only this Windows user, on this PC,
can read the files. BabySitter reads them back the same way, so search,
export, and the backup still work. A wipe still deletes the files.

An encrypted file starts with MAGIC, then the DPAPI blob. A file without it
is plain text from an older version: it is read as it is and encrypted the
next time it is saved, or by seal_existing() when BabySitter opens. On a
system without DPAPI (tests on Linux), files stay plain text.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAGIC = b"BSDPAPI1\n"
_DESCRIPTION = "BabySitter history and facts"


def encryption_available() -> bool:
    return sys.platform == "win32"


def is_sealed(data: bytes) -> bool:
    return data.startswith(MAGIC)


def seal(text: str) -> bytes:
    raw = text.encode("utf-8")
    if not encryption_available():
        return raw
    from babysitter.secrets import protect_blob

    return MAGIC + protect_blob(raw, _DESCRIPTION)


def unseal(data: bytes) -> str:
    """The text in a file's bytes, sealed or not. Raises UnicodeError or OSError when unreadable."""
    if is_sealed(data):
        from babysitter.secrets import unprotect_blob

        try:
            return unprotect_blob(data[len(MAGIC):]).decode("utf-8")
        except UnicodeError:
            raise
        except Exception as exc:  # noqa: BLE001 - DPAPI refuses another user's file
            raise OSError("This file was encrypted by another Windows user or PC.") from exc
    return data.decode("utf-8")


def read_private(path: Path) -> str:
    return unseal(Path(path).read_bytes())


def write_private(path: Path, text: str) -> None:
    """Write through a temporary file, so a crash never leaves half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(seal(text))
    temporary.replace(path)


def seal_existing(paths) -> int:
    """Encrypt plain files left by an older version. Returns how many were sealed."""
    if not encryption_available():
        return 0
    count = 0
    for path in paths:
        path = Path(path)
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not data or is_sealed(data):
            continue
        try:
            write_private(path, data.decode("utf-8"))
        except (OSError, UnicodeError):
            continue
        count += 1
    return count
