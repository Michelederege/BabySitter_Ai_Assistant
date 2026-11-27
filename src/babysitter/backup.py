"""One zip of everything BabySitter remembers, for a new PC or a broken disk.

What goes in: saved facts, History, the Journal, the Board, reminders, goals,
the nickname, ratings, voice and app settings. What stays out: model files
(they download again), logs, the update cache, and the encrypted sign-ins.
Those are locked to this Windows user, so they would not open anywhere else;
on a new PC you sign in again.

History and facts are encrypted on this PC; the zip holds them readable, so
keep it somewhere private. Nothing is sent anywhere. The zip lands in the
folder you pick.
"""

from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

from babysitter.paths import data_dir
from babysitter.privatefile import is_sealed, unseal

# Folders inside the data folder that are kept.
KEPT_FOLDERS = ("journal", "sessions")
# Folders that are never copied.
SKIPPED_FOLDERS = {"models", "logs", "updates", "secrets", "voiceclone", "fillers", "startup-backup"}
# Files that are never copied, even at the top level.
SKIPPED_SUFFIXES = (".dpapi", ".tmp", ".bin", ".lock")


def backup_files(root: Path | None = None) -> list[Path]:
    """The files a backup would hold, in a fixed order."""
    base = root or data_dir()
    if not base.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(base.iterdir()):
        if path.is_file() and path.suffix.lower() in {".json", ".txt"} and not path.name.endswith(SKIPPED_SUFFIXES):
            files.append(path)
    for folder in KEPT_FOLDERS:
        sub = base / folder
        if sub.is_dir():
            for path in sorted(sub.rglob("*")):
                if path.is_file() and not path.name.endswith(SKIPPED_SUFFIXES):
                    files.append(path)
    return files


def make_backup(destination: Path, root: Path | None = None, now: datetime | None = None) -> tuple[Path, int]:
    """Write the zip into destination. Returns its path and how many files it holds."""
    base = root or data_dir()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H%M")
    target = destination / f"BabySitter memory {stamp}.zip"
    files = backup_files(base)
    temporary = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(base).as_posix()
            data = path.read_bytes()
            if is_sealed(data):
                # History and facts are encrypted for this Windows user only. The
                # backup holds them readable, so they open on a new PC.
                archive.writestr(name, unseal(data))
            else:
                archive.write(path, name)
        archive.writestr(
            "READ ME.txt",
            "BabySitter memory backup.\n\n"
            "To use it on another PC: close BabySitter there, open its data folder "
            "(Settings, Privacy and data, Open the data folder), and copy these files in.\n"
            "Sign-ins are not included. They are locked to the Windows user that made them, "
            "so sign in again on the new PC.\n",
        )
    temporary.replace(target)
    return target, len(files)
