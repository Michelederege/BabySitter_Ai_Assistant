"""Settings saved as one JSON file, with a version number.

schema_version lets a future update reshape the file without you doing
anything. If a value is missing, the default is filled in. If the file
is unreadable, it is renamed and a fresh one is started.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from babysitter.hotkeys import HotkeyError, canonical_hotkey
from babysitter.intelligence import MODES
from babysitter.paths import settings_path


SCHEMA_VERSION = 6

DEFAULT_EMERGENCY = "Ctrl+Alt+F12"
DEFAULT_POWER_ON = "Ctrl+Alt+F11"


class SettingsError(Exception):
    """The settings file is from a newer app, or could not be repaired."""


@dataclass
class Settings:
    schema_version: int = SCHEMA_VERSION
    intelligence: str = "medium"
    start_with_windows: bool = False
    orb_always_on_top: bool = True
    emergency_hotkey: str = DEFAULT_EMERGENCY
    power_on_hotkey: str = DEFAULT_POWER_ON
    auto_game_mode: bool = False
    game_processes: list[str] = field(default_factory=list)
    orb_x: int | None = None
    orb_y: int | None = None
    social_search_enabled: bool = False
    window_expanded: bool = False
    quit_turns_ai_off: bool = True
    keyword_listening: bool = False
    keyword: str = "baby sitter"
    followup_seconds: int = 10
    notices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "intelligence": self.intelligence,
            "start_with_windows": self.start_with_windows,
            "orb_always_on_top": self.orb_always_on_top,
            "emergency_hotkey": self.emergency_hotkey,
            "power_on_hotkey": self.power_on_hotkey,
            "auto_game_mode": self.auto_game_mode,
            "game_processes": list(self.game_processes),
            "orb_x": self.orb_x,
            "orb_y": self.orb_y,
            "social_search_enabled": self.social_search_enabled,
            "window_expanded": self.window_expanded,
            "quit_turns_ai_off": self.quit_turns_ai_off,
            "keyword_listening": self.keyword_listening,
            "keyword": self.keyword,
            "followup_seconds": self.followup_seconds,
        }


def _clean_games(value: object) -> list[str]:
    from babysitter.games import clean_process_name

    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value[:50]:
        if not isinstance(item, str):
            continue
        try:
            name = clean_process_name(item)
        except ValueError:
            continue
        if name.lower() not in {existing.lower() for existing in cleaned}:
            cleaned.append(name)
    return cleaned


def migrate(data: dict) -> dict:
    """Bring an older settings file up to the current schema."""
    incoming = dict(data)
    try:
        version = int(incoming.get("schema_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version > SCHEMA_VERSION:
        raise SettingsError(
            "These settings were saved by a newer BabySitter. "
            "Update the app before opening them."
        )
    if version < 1:
        # First published shape. Older files (or empty ones) land here.
        incoming["schema_version"] = 1
        version = 1
    if version < 2:
        # Social search arrived later. It stays off, and the API key is
        # never stored in this file.
        incoming["social_search_enabled"] = False
        incoming["schema_version"] = 2
        version = 2
    if version < 3:
        incoming.setdefault("window_expanded", False)
        incoming.setdefault("quit_turns_ai_off", True)
        incoming["schema_version"] = 3
        version = 3
    if version < 4:
        incoming.setdefault("keyword_listening", False)
        incoming.setdefault("keyword", "hey babysitter")
        incoming["schema_version"] = 4
        version = 4
    if version < 5:
        current = str(incoming.get("keyword") or "").strip().lower()
        if current in {"", "hey babysitter", "babysitter"}:
            incoming["keyword"] = "baby sitter"
        incoming["schema_version"] = 5
        version = 5
    if version < 6:
        incoming.setdefault("followup_seconds", 10)
        incoming["schema_version"] = 6
        version = 6
    defaults = Settings().to_dict()
    for key, value in defaults.items():
        incoming.setdefault(key, value)
    incoming["schema_version"] = SCHEMA_VERSION
    return incoming


def _followup_seconds(value: object) -> int:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = 10
    return max(5, min(20, seconds))


def _clean_keyword(value: object, notices: list[str]) -> str:
    from babysitter.plugins.voice.keyword import DEFAULT_KEYWORD, KeywordError, clean_keyword

    try:
        return clean_keyword(str(value or DEFAULT_KEYWORD))
    except KeywordError as exc:
        notices.append(f"{exc} Using baby sitter.")
        return DEFAULT_KEYWORD


def settings_from_dict(data: dict) -> Settings:
    notices: list[str] = []
    intelligence = data.get("intelligence", "medium")
    if intelligence not in MODES:
        notices.append(
            f"Saved intelligence '{intelligence}' is not Low, Medium, or High. "
            "Using Medium."
        )
        intelligence = "medium"
    emergency = str(data.get("emergency_hotkey") or DEFAULT_EMERGENCY)
    power_on = str(data.get("power_on_hotkey") or DEFAULT_POWER_ON)
    try:
        emergency = canonical_hotkey(emergency)
        power_on = canonical_hotkey(power_on)
        if emergency.lower() == power_on.lower():
            raise HotkeyError("The on key and the emergency key were the same.")
    except HotkeyError as exc:
        notices.append(f"{exc} Using the default keys.")
        emergency = DEFAULT_EMERGENCY
        power_on = DEFAULT_POWER_ON
    orb_x = data.get("orb_x")
    orb_y = data.get("orb_y")
    return Settings(
        schema_version=SCHEMA_VERSION,
        intelligence=intelligence,
        start_with_windows=bool(data.get("start_with_windows", False)),
        orb_always_on_top=bool(data.get("orb_always_on_top", True)),
        emergency_hotkey=emergency,
        power_on_hotkey=power_on,
        auto_game_mode=bool(data.get("auto_game_mode", False)),
        game_processes=_clean_games(data.get("game_processes")),
        orb_x=orb_x if isinstance(orb_x, int) else None,
        orb_y=orb_y if isinstance(orb_y, int) else None,
        social_search_enabled=bool(data.get("social_search_enabled", False)),
        window_expanded=bool(data.get("window_expanded", False)),
        quit_turns_ai_off=bool(data.get("quit_turns_ai_off", True)),
        keyword_listening=bool(data.get("keyword_listening", False)),
        keyword=_clean_keyword(data.get("keyword"), notices),
        followup_seconds=_followup_seconds(data.get("followup_seconds")),
        notices=notices,
    )


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings, path)
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        backup = path.with_name("settings.json.bak")
        try:
            path.replace(backup)
        except OSError:
            backup = path
        settings = Settings()
        settings.notices.append(
            "The settings file could not be read. A copy was kept as "
            f"{backup.name}, and a fresh settings file was started. "
            "Start with Windows is off."
        )
        save_settings(settings, path)
        return settings
    if not isinstance(raw, dict):
        raise SettingsError("The settings file was not a settings object.")
    try:
        original_version = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError):
        original_version = 0
    settings = settings_from_dict(migrate(raw))
    if original_version != SCHEMA_VERSION or settings.notices:
        # Write the repaired file so the next launch doesn't have to fix it again.
        save_settings(settings, path)
    return settings


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_dict(), indent=2) + "\n"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
