"""Google reads, PC suggestions, and the model floor for this PC."""

import json
from datetime import datetime, timezone

import pytest

from babysitter.commands import match_quick_command
from babysitter.models import model_choice
from babysitter.pcscan import (
    DictStartup,
    Suggestion,
    apply_startup,
    close_named,
    scan,
    suggestion_answer,
)
from babysitter.plugins.tools.google_account import (
    GMAIL_LIST_URL,
    GoogleError,
    GoogleReader,
    MemoryGoogleVault,
    http_get_json,
    normalize_google_token,
)
from babysitter.security import require_google_url
from babysitter.settings import SCHEMA_VERSION, Settings, load_settings, save_settings
from babysitter.vram import simulate_ryzen_4070


TOKEN = "ya29.a0AfH6SM-test-token-value"


def test_low_stays_at_4096_on_a_4070():
    report = simulate_ryzen_4070()
    assert report["card_mib"] == 12282
    assert report["working_mib"] > 6144
    assert report["working_mib"] <= 7168
    assert report["fits_4_to_6"] is False
    assert report["within_voice_budget"] is True
    assert report["savings_mib"] < 200
    assert report["context_2048_mib"] > 5000
    assert report["shrinking_context_keeps_features"] is False
    choice = model_choice()
    assert "qwen3.5:9b" in choice
    assert "gemma4:12b" in choice
    assert "4,096" in choice


def test_scan_skips_the_system_and_games():
    megabyte = 1024 * 1024
    result = scan(
        [
            ("chrome.exe", 2400 * megabyte, 10),
            ("ollama.exe", 5000 * megabyte, 11),
            ("explorer.exe", 900 * megabyte, 12),
            ("notepad.exe", 20 * megabyte, 13),
            ("bg3.exe", 8000 * megabyte, 14),
        ],
        [("Discord", "discord.exe"), ("SecurityHealth", "sec.exe")],
        games=["bg3.exe"],
    )
    names = [item.name for item in result.suggestions]
    assert result.left_games is True
    assert "chrome.exe" in names
    assert "bg3.exe" not in names
    assert all("ollama" not in name.lower() for name in names)
    assert all("explorer" not in name.lower() for name in names)
    assert any(item.kind == "startup" and item.name == "Discord" for item in result.suggestions)
    assert "SecurityHealth" not in names


def test_close_refuses_a_protected_or_changed_app():
    assert "left it" in close_named("ollama.exe", pids=lambda _name: [1], terminate=lambda _pid: None).lower()
    assert "already closed" in close_named("chrome.exe", pids=lambda _name: [], terminate=lambda _pid: None).lower()
    closed = []
    speech = close_named("chrome.exe", pids=lambda _name: [4, 5], terminate=closed.append)
    assert closed == [4, 5]
    assert speech == "Closed 2 chrome.exe processes."


def test_startup_can_be_turned_off_and_put_back():
    store = DictStartup({"Discord": "discord.exe"})
    item = Suggestion(kind="startup", speech="Turn it off?", name="Discord", command="discord.exe")
    speech, previous = apply_startup(item, store)
    assert previous == "discord.exe"
    assert "Discord" not in store.items
    assert "undo" in speech.lower()
    store.restore("Discord", previous)
    assert store.items["Discord"] == "discord.exe"
    protected = Suggestion(kind="startup", speech="", name="SecurityHealth")
    speech, previous = apply_startup(protected, DictStartup({"SecurityHealth": "x"}))
    assert previous is None
    assert "stays" in speech


def test_deny_answers_a_suggestion():
    assert suggestion_answer("deny") == "no"
    assert suggestion_answer("leave it") == "no"
    assert suggestion_answer("yes") == "yes"
    assert suggestion_answer("tell me more") is None
    assert suggestion_answer("what time is it") is None


def test_quick_commands_for_scan_mail_and_memory():
    assert match_quick_command("scan my pc").kind == "scan"
    assert match_quick_command("optimize my computer").kind == "scan"
    assert match_quick_command("check my email").kind == "mail"
    assert match_quick_command("what's on my calendar").kind == "calendar"
    remembered = match_quick_command("remember the cat is called Moth")
    assert remembered.kind == "remember"
    assert "Moth" in remembered.detail
    assert match_quick_command("remind me to call mom").kind == "remind"


def test_google_token_and_addresses():
    assert normalize_google_token("  " + TOKEN + " ") == TOKEN
    with pytest.raises(Exception):
        normalize_google_token("short")
    with pytest.raises(Exception):
        normalize_google_token(TOKEN + " tail")
    require_google_url(GMAIL_LIST_URL)
    with pytest.raises(ValueError):
        require_google_url("http://gmail.googleapis.com/gmail/v1/users/me/messages")
    with pytest.raises(ValueError):
        require_google_url("https://maps.googleapis.com/maps/api/x")
    with pytest.raises(ValueError):
        require_google_url("https://www.googleapis.com/drive/v3/files")


def test_unread_and_calendar_use_only_the_read_urls():
    seen = []

    def fetch(url, token):
        assert token == TOKEN
        assert TOKEN not in url
        require_google_url(url)
        seen.append(url)
        if "messages?q=" in url:
            return {"messages": [{"id": "abc123"}, {"id": "def456"}, {"id": "ghi789"}, {"id": "jkl000"}]}
        if "abc123" in url:
            return {"payload": {"headers": [{"name": "Subject", "value": "Hello"}]}}
        if "def456" in url:
            return {"payload": {"headers": [{"name": "Subject", "value": "Notes"}]}}
        if "ghi789" in url:
            return {"payload": {"headers": [{"name": "Subject", "value": "Ship"}]}}
        if "calendar" in url:
            assert "timeMin=" in url
            return {"items": [{"summary": "Standup", "start": {"dateTime": "2026-11-14T15:00:00Z"}}]}
        raise AssertionError(url)

    reader = GoogleReader(TOKEN, fetch, now=datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc))
    mail = reader.unread()
    calendar = reader.upcoming()
    assert "Hello" in mail and "1 more unread" in mail
    assert "Standup" in calendar
    assert all(url.startswith("https://gmail.googleapis.com/") or url.startswith("https://www.googleapis.com/calendar/") for url in seen)


def test_a_failed_google_read_does_not_repeat_the_token():
    def opener(request, timeout=8):
        raise RuntimeError("failed " + request.get_header("Authorization"))

    with pytest.raises(GoogleError) as caught:
        http_get_json(GMAIL_LIST_URL, TOKEN, opener=opener)
    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None


def test_google_stays_out_of_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 8, "intelligence": "low", "google_enabled": True}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.google_enabled is False
    assert "token" not in settings.to_dict()
    settings.google_enabled = True
    save_settings(settings)
    again = load_settings()
    assert again.google_enabled is True
    raw = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert TOKEN not in raw
    vault = MemoryGoogleVault()
    vault.save(TOKEN)
    assert vault.load() == TOKEN
    assert TOKEN not in Settings(google_enabled=True).to_dict()
