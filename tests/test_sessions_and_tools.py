"""Saved chats, spoken tools, quiet hours, and the other local additions."""

from datetime import datetime

import pytest

from babysitter.games import should_hide_orb
from babysitter.intents import match_tool
from babysitter.plugins.tools.google_account import (
    authorization_url,
    code_from_redirect,
    fresh_lines,
    pkce_pair,
)
from babysitter.quiet import in_quiet_hours
from babysitter.searx import SearxError, search_url
from babysitter.security import require_searx_url
from babysitter.sessions import append_turn, begin_session, export_text, search_sessions, wipe_sessions
from babysitter.settings import SCHEMA_VERSION, load_settings
from babysitter.sidebutton import side_button_down, xbutton_action
from babysitter.updates import describe_release, is_newer


def test_a_conversation_can_be_searched_and_wiped(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    session_id = begin_session()
    append_turn(session_id, "The cat is called Moth", "I'll remember that name.")
    found = search_sessions("moth")
    assert found and found[0]["id"] == session_id
    path = export_text(session_id)
    assert "Moth" in path.read_text(encoding="utf-8")
    assert wipe_sessions() >= 1
    assert search_sessions("moth") == []


def test_quiet_hours_wrap_past_midnight():
    late = datetime(2026, 11, 14, 23, 0)
    morning = datetime(2026, 11, 14, 6, 0)
    midday = datetime(2026, 11, 14, 12, 0)
    assert in_quiet_hours(True, "22:00", "07:00", late) is True
    assert in_quiet_hours(True, "22:00", "07:00", morning) is True
    assert in_quiet_hours(True, "22:00", "07:00", midday) is False
    assert in_quiet_hours(False, "22:00", "07:00", late) is False


def test_spoken_tools_wait_for_a_yes_and_refuse_ad_libraries():
    web = match_tool("search the web for local bakeries")
    assert web is not None and web.kind == "web" and "bakeries" in web.query
    social = match_tool("search reddit for pasta")
    assert social is not None and social.action_id == "reddit"
    refused = match_tool("check the ad library")
    assert refused is not None and refused.kind == "refuse"
    assert match_tool("what time is it") is None


def test_searx_stays_on_this_computer():
    url = search_url(8080, "bakeries")
    assert url.startswith("http://127.0.0.1:8080/search?")
    require_searx_url(url)
    with pytest.raises(ValueError):
        require_searx_url("https://example.com/search?q=bakeries")
    with pytest.raises(SearxError):
        search_url(0, "bakeries")


def test_update_check_compares_versions_and_does_not_download():
    assert is_newer("v0.14.0", "0.13.0") is True
    assert is_newer("0.13.0", "0.13.0") is False
    speech = describe_release({"tag_name": "v9.0.0", "html_url": "https://github.com/alex-de-rege/Ai-assistant-Babysitter/releases/tag/v9.0.0"}, "0.13.0")
    assert "did not download" in speech
    assert "sign" in speech


def test_side_buttons_are_the_only_mouse_events_that_count():
    assert xbutton_action(0x020B, 1 << 16) == "down"
    assert xbutton_action(0x020C, 2 << 16) == "up"
    assert xbutton_action(0x0201, 0) is None
    assert side_button_down({0x05: True, 0x06: False}) is True
    assert side_button_down({}) is False


def test_the_orb_hides_only_for_a_watched_game_in_front():
    assert should_hide_orb(True, "bg3.exe", ["bg3.exe"]) is True
    assert should_hide_orb(False, "bg3.exe", ["bg3.exe"]) is False
    assert should_hide_orb(True, "chrome.exe", ["bg3.exe"]) is False


def test_google_sign_in_uses_read_only_scopes_and_hides_the_code():
    verifier, challenge = pkce_pair()
    url = authorization_url("client-id-1234567890.apps.googleusercontent.com", "state-value", challenge)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "gmail.readonly" in url and "calendar.readonly" in url
    assert "code_challenge=" in url
    assert verifier not in url
    code = code_from_redirect("/babysitter?code=abc123&state=state-value", "state-value")
    assert code == "abc123"
    with pytest.raises(Exception):
        code_from_redirect("/babysitter?code=abc123&state=other", "state-value")
    speech, seen = fresh_lines(["m1", "m2"], ["Hello", "Notes"], {"m1"})
    assert speech == "New from Google: Notes."
    assert seen == {"m1", "m2"}


def test_schema_nine_gains_the_new_switches_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        '{"schema_version": 9, "intelligence": "low", "google_enabled": false}',
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.quiet_hours is False
    assert settings.hide_orb_for_games is False
    assert settings.side_button is False
    assert settings.searx_enabled is False
    assert settings.google_client_id == ""
