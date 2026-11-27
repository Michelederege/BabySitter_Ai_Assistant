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


SCHEMA_VERSION = 14

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
    auto_game_mode: bool = True
    game_mode_ask: bool = False
    # NEXT_ROUND phase 5: new mail and events said in the Windows voice while
    # the AI is off. The chat model is not loaded. Quiet hours silence them;
    # with quiet hours off, 22:00 to 07:00 is quiet for these alerts anyway.
    alerts_when_off: bool = True
    # UI v3, Memory: when off, the conversation is kept only while the window
    # is open, for follow-ups, and nothing is written to History.
    save_conversations: bool = True
    detect_games: bool = True
    game_processes: list[str] = field(default_factory=list)
    orb_x: int | None = None
    orb_y: int | None = None
    social_search_enabled: bool = False
    window_expanded: bool = False
    quit_turns_ai_off: bool = True
    keyword_listening: bool = False
    keyword: str = "baby sitter"
    followup_seconds: int = 10
    keep_off_game_cores: bool = False
    vad_enabled: bool = False
    smart_turn: bool = False
    echo_cancel: bool = False
    talk_over: bool = False
    proactivity: int = 1
    last_weekly_review: str = ""
    google_enabled: bool = False
    google_client_id: str = ""
    blackboard_enabled: bool = False
    quiet_hours: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    hide_orb_for_games: bool = False
    side_button: bool = False
    searx_enabled: bool = False
    searx_port: int = 8080
    journal_enabled: bool = True
    journal_excluded: list[str] = field(default_factory=list)
    search_folders: list[str] = field(default_factory=list)
    # The microphone's full name. Empty means Windows' default.
    microphone: str = ""
    # "whisper" (default), "moonshine", or "parakeet". One engine hears the question.
    hearing_engine: str = "moonshine"  # falls back to Whisper until its pack is downloaded
    # The memory slider, in tokens. 0 means the level's own amount.
    context_tokens: int = 0
    # Outlook / Microsoft 365, read-only. The id is the app registration's, not a secret.
    microsoft_enabled: bool = False
    microsoft_client_id: str = ""
    # Phase 6. The town is kept here; it leaves the PC only after a yes.
    weather_place: str = ""
    # Home Assistant on this network only. The token is in secrets/, encrypted.
    home_url: str = ""
    home_music_entity: str = ""
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
            "game_mode_ask": self.game_mode_ask,
            "alerts_when_off": self.alerts_when_off,
            "save_conversations": self.save_conversations,
            "detect_games": self.detect_games,
            "game_processes": list(self.game_processes),
            "orb_x": self.orb_x,
            "orb_y": self.orb_y,
            "social_search_enabled": self.social_search_enabled,
            "window_expanded": self.window_expanded,
            "quit_turns_ai_off": self.quit_turns_ai_off,
            "keyword_listening": self.keyword_listening,
            "keyword": self.keyword,
            "followup_seconds": self.followup_seconds,
            "keep_off_game_cores": self.keep_off_game_cores,
            "vad_enabled": self.vad_enabled,
            "smart_turn": self.smart_turn,
            "echo_cancel": self.echo_cancel,
            "talk_over": self.talk_over,
            "proactivity": self.proactivity,
            "last_weekly_review": self.last_weekly_review,
            "google_enabled": self.google_enabled,
            "google_client_id": self.google_client_id,
            "blackboard_enabled": self.blackboard_enabled,
            "quiet_hours": self.quiet_hours,
            "quiet_start": self.quiet_start,
            "quiet_end": self.quiet_end,
            "hide_orb_for_games": self.hide_orb_for_games,
            "side_button": self.side_button,
            "searx_enabled": self.searx_enabled,
            "searx_port": self.searx_port,
            "journal_enabled": self.journal_enabled,
            "journal_excluded": list(self.journal_excluded),
            "search_folders": list(self.search_folders),
            "microphone": self.microphone,
            "hearing_engine": self.hearing_engine,
            "context_tokens": self.context_tokens,
            "microsoft_enabled": self.microsoft_enabled,
            "microsoft_client_id": self.microsoft_client_id,
            "weather_place": self.weather_place,
            "home_url": self.home_url,
            "home_music_entity": self.home_music_entity,
        }


def _clean_games(value: object) -> list[str]:
    from babysitter.games import clean_process_name

    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value[:50]:
        if not isinstance(item, str):
            continue
        try:
            name = clean_process_name(item)
        except ValueError:
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(name)
    return cleaned


def _clean_names(value: object) -> list[str]:
    """Short plain names, like programs the journal should not write down."""
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value[:50]:
        if not isinstance(item, str):
            continue
        name = " ".join(item.split())[:120]
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            cleaned.append(name)
    return cleaned


def _clean_folders(value: object) -> list[str]:
    """Folders the file search may look in, beyond the usual three."""
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value[:20]:
        if not isinstance(item, str):
            continue
        path = item.strip()[:500]
        key = path.lower()
        if path and key not in seen:
            seen.add(key)
            cleaned.append(path)
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
    if version < 7:
        incoming.setdefault("keep_off_game_cores", False)
        incoming["schema_version"] = 7
        version = 7
    if version < 8:
        incoming.setdefault("vad_enabled", False)
        incoming.setdefault("smart_turn", False)
        incoming.setdefault("echo_cancel", False)
        incoming.setdefault("talk_over", False)
        incoming.setdefault("proactivity", 1)
        incoming.setdefault("last_weekly_review", "")
        incoming["schema_version"] = 8
        version = 8
    if version < 9:
        # Google mail and calendar stay off. The token is never in this file.
        incoming["google_enabled"] = False
        incoming["schema_version"] = 9
        version = 9
    if version < 10:
        incoming.setdefault("google_client_id", "")
        incoming.setdefault("quiet_hours", False)
        incoming.setdefault("quiet_start", "22:00")
        incoming.setdefault("quiet_end", "07:00")
        incoming.setdefault("hide_orb_for_games", False)
        incoming.setdefault("side_button", False)
        incoming.setdefault("searx_enabled", False)
        incoming.setdefault("searx_port", 8080)
        incoming["schema_version"] = 10
        version = 10
    if version < 11:
        # Game mode now notices a game by its install folder, so it no
        # longer needs a typed name. It was asked to work by itself, so
        # this one update turns the switch on. Settings can turn it off.
        incoming["detect_games"] = True
        incoming["auto_game_mode"] = True
        incoming["schema_version"] = 11
        version = 11
    if version < 12:
        # The day journal and the file search arrived together. The
        # journal starts on because it only writes program names and
        # minutes, stays on this PC, and Settings can turn it off or
        # wipe it. The search looks only in folders you chose.
        incoming.setdefault("journal_enabled", True)
        incoming.setdefault("journal_excluded", [])
        incoming.setdefault("search_folders", [])
        incoming["schema_version"] = 12
        version = 12
    if version < 13:
        # Asking before game mode is a choice. Automatic switching stays
        # on, and the Game mode button still switches by hand.
        incoming.setdefault("game_mode_ask", False)
        incoming["schema_version"] = 13
        version = 13
    if version < 14:
        # Moonshine hears a sentence in about 0.13 s on his PC; Whisper small
        # took 1.1 s for the same words. Whisper was only ever the default,
        # so the faster one takes over. Until Moonshine is downloaded, Whisper
        # still hears. Parakeet, picked by hand, stays.
        if str(incoming.get("hearing_engine") or "whisper") == "whisper":
            incoming["hearing_engine"] = "moonshine"
        incoming["schema_version"] = 14
        version = 14
    defaults = Settings().to_dict()
    for key, value in defaults.items():
        incoming.setdefault(key, value)
    incoming["schema_version"] = SCHEMA_VERSION
    return incoming


def _home_url(value: object) -> str:
    """A saved Home Assistant address is checked again: off this network, it is dropped."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        from babysitter.home import clean_base_url

        return clean_base_url(text)
    except Exception:  # noqa: BLE001
        return ""


def _client_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    from babysitter.plugins.tools.google_account import clean_client_id
    from babysitter.secrets import SecretsError

    try:
        return clean_client_id(text)
    except SecretsError:
        return ""


def _clock(value: object, default: str) -> str:
    from babysitter.quiet import parse_hhmm

    try:
        parsed = parse_hhmm(str(value or ""))
    except ValueError:
        return default
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _port(value: object) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 8080
    if number < 1 or number > 65535:
        return 8080
    return number


def _microsoft_id(value: object) -> str:
    from babysitter.plugins.tools.microsoft_account import clean_client_id
    from babysitter.secrets import SecretsError

    try:
        return clean_client_id(str(value or "")) if value else ""
    except SecretsError:
        return ""


def _context_tokens(value: object) -> int:
    from babysitter.intelligence import CONTEXT_STOPS

    try:
        tokens = int(value)
    except (TypeError, ValueError):
        return 0
    return tokens if tokens in CONTEXT_STOPS else 0


def _proactivity(value: object) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        level = 1
    return max(0, min(3, level))


def _weekly_day(value: object) -> str:
    text = str(value or "").strip()
    if len(text) != 10:
        return ""
    parts = text.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return ""
    return text


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
        auto_game_mode=bool(data.get("auto_game_mode", True)),
        game_mode_ask=bool(data.get("game_mode_ask", False)),
        alerts_when_off=bool(data.get("alerts_when_off", True)),
        save_conversations=bool(data.get("save_conversations", True)),
        detect_games=bool(data.get("detect_games", True)),
        game_processes=_clean_games(data.get("game_processes")),
        orb_x=orb_x if isinstance(orb_x, int) else None,
        orb_y=orb_y if isinstance(orb_y, int) else None,
        social_search_enabled=bool(data.get("social_search_enabled", False)),
        window_expanded=bool(data.get("window_expanded", False)),
        quit_turns_ai_off=bool(data.get("quit_turns_ai_off", True)),
        keyword_listening=bool(data.get("keyword_listening", False)),
        keyword=_clean_keyword(data.get("keyword"), notices),
        followup_seconds=_followup_seconds(data.get("followup_seconds")),
        keep_off_game_cores=bool(data.get("keep_off_game_cores", False)),
        vad_enabled=bool(data.get("vad_enabled", False)),
        smart_turn=bool(data.get("smart_turn", False)),
        echo_cancel=bool(data.get("echo_cancel", False)),
        talk_over=bool(data.get("talk_over", False)),
        proactivity=_proactivity(data.get("proactivity", 1)),
        last_weekly_review=_weekly_day(data.get("last_weekly_review", "")),
        google_enabled=bool(data.get("google_enabled", False)),
        google_client_id=_client_id(data.get("google_client_id", "")),
        blackboard_enabled=bool(data.get("blackboard_enabled", False)),
        quiet_hours=bool(data.get("quiet_hours", False)),
        quiet_start=_clock(data.get("quiet_start", "22:00"), "22:00"),
        quiet_end=_clock(data.get("quiet_end", "07:00"), "07:00"),
        hide_orb_for_games=bool(data.get("hide_orb_for_games", False)),
        side_button=bool(data.get("side_button", False)),
        searx_enabled=bool(data.get("searx_enabled", False)),
        searx_port=_port(data.get("searx_port", 8080)),
        journal_enabled=bool(data.get("journal_enabled", True)),
        journal_excluded=_clean_names(data.get("journal_excluded")),
        search_folders=_clean_folders(data.get("search_folders")),
        microphone=" ".join(str(data.get("microphone") or "").split())[:200],
        context_tokens=_context_tokens(data.get("context_tokens", 0)),
        microsoft_enabled=bool(data.get("microsoft_enabled", False)),
        microsoft_client_id=_microsoft_id(data.get("microsoft_client_id", "")),
        weather_place=" ".join(str(data.get("weather_place") or "").split())[:60],
        home_url=_home_url(data.get("home_url", "")),
        home_music_entity=str(data.get("home_music_entity") or "")[:120],
        # A missing or unknown engine means the default, Moonshine (0.27.0),
        # which itself falls back to Whisper until its pack is on this PC.
        hearing_engine=(
            str(data.get("hearing_engine"))
            if str(data.get("hearing_engine") or "") in {"whisper", "moonshine", "parakeet"}
            else "moonshine"
        ),
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
        return _start_fresh(path)
    if not isinstance(raw, dict):
        # Valid JSON that is not a settings object, such as null or a
        # list, is as unreadable as a broken file. It used to stop the
        # app from opening at all.
        return _start_fresh(path)
    try:
        original_version = int(raw.get("schema_version") or 0)
    except (TypeError, ValueError):
        original_version = 0
    settings = settings_from_dict(migrate(raw))
    if original_version != SCHEMA_VERSION or settings.notices:
        # Write the repaired file so the next launch doesn't have to fix it again.
        save_settings(settings, path)
    return settings


def _start_fresh(path: Path) -> Settings:
    """Keep the unreadable file as a copy and start with the defaults."""
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


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings.to_dict(), indent=2) + "\n"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
