"""Where BabySitter keeps your files.

On your Windows PC everything lives in %LOCALAPPDATA%\\BabySitter\\.
Nothing you save is stored in the install folder, so an update can replace
the program without touching your settings.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "BabySitter"


def data_dir() -> Path:
    """Folder for settings, logs, and (later) memory and the pinboard."""
    override = os.environ.get("BABYSITTER_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if not root:
            root = str(Path.home() / "AppData" / "Local")
        path = Path(root) / APP_DIR_NAME
    else:
        # Used when a developer runs the app on a non-Windows machine.
        path = Path.home() / ".local" / "share" / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return data_dir() / "settings.json"


def secrets_dir() -> Path:
    path = data_dir() / "secrets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def scrapecreators_key_path() -> Path:
    """Encrypted ScrapeCreators key. Not settings.json, and not plain text."""
    return secrets_dir() / "scrapecreators.dpapi"


def google_token_path() -> Path:
    """Encrypted Google token. A different file from the ScrapeCreators key."""
    return secrets_dir() / "google.dpapi"


def ollama_log_path() -> Path:
    return logs_dir() / "ollama-serve.log"


def project_root() -> Path:
    """Repo root when running from source. Install folder when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # This file is src/babysitter/paths.py
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    """Icon and other files shipped with the program."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return base / "assets" / name
    return project_root() / "assets" / name
