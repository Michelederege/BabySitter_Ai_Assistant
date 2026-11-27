"""Audit 4 (commands, settings, accounts, files, updates), 0.28.1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from babysitter import inbox
from babysitter.paths import write_text_safely


def test_a_save_that_fails_halfway_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "voice.json"
    write_text_safely(target, '{"voice": "Kokoro: Bella"}\n')

    def broken(self, text, encoding=None):
        raise OSError("the disk went away mid-save")

    monkeypatch.setattr(Path, "write_text", broken)
    with pytest.raises(OSError):
        write_text_safely(target, '{"voice": "Kokoro: Adam"')
    monkeypatch.undo()
    assert json.loads(target.read_text(encoding="utf-8")) == {"voice": "Kokoro: Bella"}


def test_the_pack_list_never_lists_its_own_temporary_file(tmp_path, monkeypatch):
    from babysitter import modelpacks

    (tmp_path / "model.onnx").write_bytes(b"weights")
    (tmp_path / (modelpacks.MANIFEST + ".tmp")).write_text("half a list", encoding="utf-8")
    modelpacks._write_manifest(tmp_path)
    entries = json.loads((tmp_path / modelpacks.MANIFEST).read_text(encoding="utf-8"))
    assert list(entries) == ["model.onnx"]


def _account(name, reader=None, indexer=None, token="tok-" + "x" * 8):
    return inbox.Account(name=name, mail="", calendar="", drive="", token=lambda: token, reader=reader, indexer=indexer)


def test_an_odd_outlook_reply_is_one_line_and_the_rest_still_show():
    def outlook_breaks(_token):
        raise KeyError("value")  # Graph answered without the expected field

    def school_works(_token):
        return ["School · 2 unread"], ["Unread school mail: 2."], []

    result = inbox.gather([_account("Outlook", outlook_breaks), _account("School Google", school_works)])
    assert "School · 2 unread" in result.rows
    assert "Outlook · could not be read" in result.rows
    assert any(line.startswith("Outlook:") for line in result.problems)


def test_a_failing_index_reports_nothing_new_for_that_account_only():
    def reader(_token):
        return ["Outlook · 1 unread"], [], []

    def broken_index(_token):
        raise TypeError("odd reply")

    result = inbox.gather([_account("Outlook", reader, broken_index)], want_fresh=True)
    assert result.rows == ["Outlook · 1 unread"] and result.fresh_ids == []


def test_a_calendar_file_that_cannot_be_parsed_is_one_line(monkeypatch):
    monkeypatch.setattr(inbox, "events_from_ics", lambda text: (_ for _ in ()).throw(ValueError("bad date")))
    result = inbox.gather([], feed=lambda: "https://example.blackboard.com/feed.ics", fetch_ics=lambda url: "BEGIN:VCALENDAR")
    assert "Blackboard · could not be read" in result.rows
    assert result.problems == ["Blackboard: the calendar could not be read."]


def test_a_saved_link_that_cannot_be_opened_is_one_line():
    def vault():
        raise OSError("DPAPI could not unprotect")

    result = inbox.gather([], feed=vault)
    assert result.problems == ["Blackboard: the saved link could not be opened."]
