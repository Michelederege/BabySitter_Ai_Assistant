"""Save the ScrapeCreators API key so it is not sitting in a text file.

On Windows the key is encrypted with DPAPI for the current Windows user.
Another user on the same PC cannot read it, and a copy of the file is
useless on a different PC. The key is never written into settings.json
and never written into the log.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Protocol

from babysitter.paths import scrapecreators_key_path


class KeyVault(Protocol):
    @property
    def available(self) -> bool: ...

    def has_key(self) -> bool: ...

    def save(self, raw: str) -> None: ...

    def load(self) -> str | None: ...

    def delete(self) -> None: ...


class SecretsError(Exception):
    """The key could not be saved or read. The message never includes the key."""


def normalize_key(raw: str) -> str:
    key = raw.strip()
    if not key or any(character in key for character in "\r\n\t "):
        raise SecretsError("Paste the key as one line, with no spaces.")
    if len(key) < 8 or len(key) > 200:
        raise SecretsError("That does not look like a ScrapeCreators API key.")
    return key


class MemoryVault:
    """In-memory stand-in used by tests. It does not touch the disk."""

    def __init__(self) -> None:
        self._key: str | None = None

    @property
    def available(self) -> bool:
        return True

    def has_key(self) -> bool:
        return bool(self._key)

    def save(self, raw: str) -> None:
        self._key = normalize_key(raw)

    def load(self) -> str | None:
        return self._key

    def delete(self) -> None:
        self._key = None


class DpapiKeyVault:
    """Windows DPAPI file. `available` is false on any other system."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or scrapecreators_key_path()

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def has_key(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0

    def save(self, raw: str) -> None:
        key = normalize_key(raw)
        if not self.available:
            raise SecretsError(
                "Saving the key needs Windows. On your PC it is encrypted "
                "for your Windows user only, with DPAPI."
            )
        blob = _protect(key.encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".dpapi.tmp")
        temporary.write_bytes(blob)
        temporary.replace(self.path)

    def load(self) -> str | None:
        if not self.has_key():
            return None
        if not self.available:
            raise SecretsError(
                "This computer cannot read a Windows-encrypted key."
            )
        try:
            raw = _unprotect(self.path.read_bytes())
        except OSError as exc:
            raise SecretsError(
                "Windows could not read the saved key. Delete it and save it again."
            ) from exc
        try:
            return normalize_key(raw.decode("utf-8"))
        except (UnicodeError, SecretsError) as exc:
            raise SecretsError(
                "The saved key was unreadable. Delete it and save it again."
            ) from exc

    def delete(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            raise SecretsError("The saved key could not be deleted.") from exc


def default_vault() -> DpapiKeyVault:
    return DpapiKeyVault()


def protect_blob(data: bytes, description: str) -> bytes:
    return _crypt(data, encrypt=True, description=description)


def unprotect_blob(data: bytes) -> bytes:
    return _crypt(data, encrypt=False, description="")


def _protect(data: bytes) -> bytes:
    return protect_blob(data, "BabySitter ScrapeCreators key")


def _unprotect(data: bytes) -> bytes:
    return unprotect_blob(data)


_DPAPI = None
_DPAPI_LOCK = threading.Lock()


def _dpapi():
    """The DATA_BLOB type and the three Windows calls, made once.

    They used to be made inside `_crypt` on every call. ctypes keeps every
    structure type and pointer type it is ever given, so each decrypt (the
    History page reads every saved conversation) leaked a new set: measured
    at about 100 MB over 600 local commands (27 Nov 2026).
    """
    global _DPAPI
    with _DPAPI_LOCK:
        if _DPAPI is not None:
            return _DPAPI
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        blob = ctypes.POINTER(DATA_BLOB)
        # Own function objects (WinDLL, not the shared windll), so setting their
        # types here never changes a function another part of the app uses.
        crypt32 = ctypes.WinDLL("crypt32")
        kernel32 = ctypes.WinDLL("kernel32")
        protect = crypt32.CryptProtectData
        protect.argtypes = [blob, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob]
        protect.restype = wintypes.BOOL
        unprotect = crypt32.CryptUnprotectData
        unprotect.argtypes = [blob, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob]
        unprotect.restype = wintypes.BOOL
        free = kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        _DPAPI = (DATA_BLOB, protect, unprotect, free)
        return _DPAPI


def _crypt(data: bytes, *, encrypt: bool, description: str) -> bytes:
    import ctypes

    DATA_BLOB, protect, unprotect, free = _dpapi()
    buffer = ctypes.create_string_buffer(data, len(data))
    incoming = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = DATA_BLOB()
    call, second = (protect, description) if encrypt else (unprotect, None)
    ok = call(
        ctypes.byref(incoming),
        second,
        None,
        None,
        None,
        0,
        ctypes.byref(outgoing),
    )
    if not ok:
        raise OSError("Windows DPAPI refused the key.")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        free(outgoing.pbData)
