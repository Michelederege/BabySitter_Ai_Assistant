"""Linked accounts stay read-only, and one failure does not hide the rest."""

from datetime import datetime, timezone

import pytest

from babysitter.blackboard import (
    FeedError,
    MemoryFeedVault,
    blackboard_rows,
    blackboard_speech,
    events_from_ics,
    require_feed_url,
)
from babysitter.plugins.tools.google_account import GoogleError, authorization_url, read_account
from babysitter.security import require_google_url
from babysitter.settings import Settings


TOKEN = "ya29.example-token-value-ok"


def test_drive_list_is_allowed_and_changes_are_not():
    require_google_url(
        "https://www.googleapis.com/drive/v3/files?pageSize=8&fields=files(id,name,modifiedTime)"
    )
    for blocked in (
        "https://www.googleapis.com/upload/drive/v3/files",
        "https://www.googleapis.com/drive/v3/files/abc/permissions",
        "https://www.googleapis.com/drive/v3/files/abc/copy",
        "https://www.googleapis.com/drive/v3/files/abc/comments",
        "https://www.googleapis.com/drive/v3/files/abc/revisions",
    ):
        with pytest.raises(ValueError):
            require_google_url(blocked)


def test_school_sign_in_uses_the_same_read_only_scopes():
    url = authorization_url(
        "1234567890-abc.apps.googleusercontent.com",
        "statevalue",
        "challenge",
        prompt="select_account consent",
    )
    assert "drive.readonly" in url
    assert "select_account+consent" in url or "select_account%20consent" in url or "select_account consent" in url


def test_one_section_failing_keeps_the_others():
    def fetch(url, token):
        assert token == TOKEN
        if "/drive/" in url:
            raise GoogleError("Drive refused the read.")
        if "messages?q=" in url:
            return {"messages": [{"id": "msg1"}]}
        if url.endswith("msg1") or "/msg1?" in url:
            return {
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Ada <ada@example.com>"},
                        {"name": "Subject", "value": "Hello"},
                        {"name": "Date", "value": "Thu, 26 Nov 2026 09:00:00 -0500"},
                    ]
                }
            }
        if "/calendar/" in url:
            return {"items": [{"summary": "Studio", "start": {"date": "2026-11-27"}, "location": "Room 4"}]}
        raise AssertionError(url)

    rows, speeches, problems = read_account(
        TOKEN,
        mail_prefix="School mail",
        calendar_prefix="School calendar",
        drive_prefix="School Drive",
        fetch=fetch,
    )
    assert any("Hello" in row and "Ada" in row for row in rows)
    assert any("Studio" in row for row in rows)
    assert any("could not be read" in row for row in rows)
    assert any("Drive refused" in problem for problem in problems)
    blob = " ".join(rows + speeches + problems)
    assert TOKEN not in blob


def test_blackboard_feed_rejects_this_computer_and_keeps_upcoming_events():
    with pytest.raises(FeedError):
        require_feed_url("https://127.0.0.1/webapps/calendar.ics")
    with pytest.raises(FeedError):
        require_feed_url("https://calendar.local/webapps/calendar.ics")
    with pytest.raises(FeedError):
        require_feed_url("http://school.example/webapps/calendar.ics")
    kept = require_feed_url("https://learn.school.example/webapps/calendar/feed/abc.ics")
    assert kept.startswith("https://learn.school.example/")
    text = "\n".join([
        "BEGIN:VEVENT",
        "SUMMARY:Old class",
        "DTSTART:20200101T120000Z",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "SUMMARY:Critique",
        "DTSTART:20300301T180000Z",
        "END:VEVENT",
    ])
    events = events_from_ics(text, today=datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert blackboard_rows(events) == ["Blackboard · Critique · 20300301T180000Z"]
    assert "Critique" in blackboard_speech(events)
    vault = MemoryFeedVault()
    vault.save(kept)
    assert vault.load() == kept
    saved = Settings(blackboard_enabled=True).to_dict()
    assert "blackboard" not in str(saved).lower() or saved["blackboard_enabled"] is True
    assert "learn.school" not in str(saved)
    assert "ics" not in str(saved)


def test_tonight_on_blackboard_still_counts_as_upcoming():
    from datetime import timedelta

    # 11:30 PM local tonight, said two ways: as a local time and in UTC.
    tonight = datetime.now().astimezone().replace(hour=23, minute=30, second=0, microsecond=0)
    in_utc = tonight.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    local = tonight.strftime("%Y%m%dT%H%M%S")
    yesterday = (tonight - timedelta(days=1)).strftime("%Y%m%dT%H%M%S")
    text = "\n".join([
        "BEGIN:VEVENT", "SUMMARY:Gone", f"DTSTART:{yesterday}", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:Local tonight", f"DTSTART;TZID=Local:{local}", "END:VEVENT",
        "BEGIN:VEVENT", "SUMMARY:UTC tonight", f"DTSTART:{in_utc}", "END:VEVENT",
    ])
    # Asked at 10 PM, when UTC may already be on tomorrow's date.
    asked = tonight.replace(hour=22)
    names = [summary for summary, _when in events_from_ics(text, today=asked)]
    assert "Local tonight" in names and "UTC tonight" in names
    assert "Gone" not in names
