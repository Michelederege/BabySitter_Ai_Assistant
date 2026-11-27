"""NEXT_ROUND phase 4: History and facts encrypted on disk with DPAPI."""

import json
import sys
import zipfile

import pytest

from babysitter.privatefile import MAGIC, is_sealed

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")


@windows_only
def test_facts_are_encrypted_and_still_read_back(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.deskstore import add_item, load_list, save_list

    add_item("memory.json", text="my locker code is 4471")
    raw = (tmp_path / "memory.json").read_bytes()
    assert raw.startswith(MAGIC)
    assert b"4471" not in raw
    assert load_list("memory.json")[0]["text"] == "my locker code is 4471"
    # Other lists (the Board, reminders) stay plain: they are not History or facts.
    save_list("pins.json", [{"id": "a", "title": "x"}])
    assert json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))[0]["title"] == "x"


@windows_only
def test_history_is_encrypted_searchable_and_exported(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter import sessions

    session = sessions.begin_session()
    sessions.append_turn(session, "what is the capital of peru", "Lima.")
    raw = (tmp_path / "sessions" / f"{session}.json").read_bytes()
    assert is_sealed(raw) and b"peru" not in raw
    assert [row["id"] for row in sessions.search_sessions("peru")] == [session]
    assert "Lima." in sessions.export_text(session).read_text(encoding="utf-8")
    assert sessions.wipe_sessions() >= 1
    assert sessions.list_sessions() == []


@windows_only
def test_plain_files_from_an_older_version_are_sealed_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter import sessions
    from babysitter.deskstore import load_list

    (tmp_path / "memory.json").write_text('[{"id": "1", "text": "likes tea"}]', encoding="utf-8")
    folder = tmp_path / "sessions"
    folder.mkdir()
    (folder / "abcdef123456.json").write_text(
        json.dumps({"id": "abcdef123456", "started": "2026-11-01T10:00", "turns": [{"user": "hi", "assistant": "hello"}]}),
        encoding="utf-8",
    )
    assert load_list("memory.json")[0]["text"] == "likes tea"  # plain is still read
    assert sessions.seal_old_files() == 2
    assert sessions.seal_old_files() == 0
    assert is_sealed((tmp_path / "memory.json").read_bytes())
    assert sessions.load_session("abcdef123456")["turns"][0]["assistant"] == "hello"

    from babysitter.backup import make_backup

    target, _count = make_backup(tmp_path / "out")
    archive = zipfile.ZipFile(target)
    assert json.loads(archive.read("memory.json"))[0]["text"] == "likes tea"  # readable on a new PC


def _docx(paragraphs):
    import io

    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_a_word_file_becomes_plain_text(tmp_path):
    from babysitter.filetext import FileTextError, plain_text, read_file_text

    path = tmp_path / "essay.docx"
    path.write_bytes(_docx(["Title", "First point.", "Second point."]))
    assert read_file_text(path) == "Title\nFirst point.\nSecond point."
    assert plain_text(b"a\r\nb", "notes.txt") == "a\nb"
    assert len(plain_text(b"x" * 100_000, "big.txt")) == 80_000  # the Google Doc cap
    with pytest.raises(FileTextError):
        plain_text(b"%PDF", "paper.pdf")
    with pytest.raises(FileTextError):
        plain_text(b"not a zip", "broken.docx")


def test_drive_reads_one_file_as_text_and_nothing_else():
    from babysitter.plugins.tools.google_account import GoogleError, drive_file_text, drive_media_url, drive_search_url
    from babysitter.security import require_google_url

    require_google_url(drive_media_url("1AbCdEfGhIjKlMn"))
    for bad in (
        "https://www.googleapis.com/drive/v3/files?alt=media",
        "https://www.googleapis.com/drive/v3/files/1AbCdEfGhIjKlMn?alt=media&uploadType=media",
        "https://www.googleapis.com/upload/drive/v3/files/1AbCdEfGhIjKlMn?alt=media",
    ):
        with pytest.raises(ValueError):
            require_google_url(bad)
    require_google_url(drive_search_url("history essay"))
    assert "name+contains+%27it%5C%27s%27" in drive_search_url("it's")

    word = {"id": "1AbCdEfGhIjKlMn", "name": "Essay", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    asked: list = []
    text = drive_file_text(word, "tok", get_bytes=lambda url, token: asked.append(url) or _docx(["Hello."]))
    assert text == "Hello." and asked[0].endswith("?alt=media")
    doc = {"id": "1AbCdEfGhIjKlMn", "name": "Notes", "mimeType": "application/vnd.google-apps.document"}
    assert drive_file_text(doc, "tok", get_text=lambda url, token: "Doc words") == "Doc words"
    with pytest.raises(GoogleError):
        drive_file_text({"id": "1AbCdEfGhIjKlMn", "name": "song.mp3", "mimeType": "audio/mpeg"}, "tok")


def test_reading_commands():
    from babysitter.commands import match_quick_command

    assert match_quick_command("summarize number 2").kind == "summarize_number"
    assert match_quick_command("what's in the second one").seconds == 2
    quick = match_quick_command("read my drive file history essay")
    assert quick.kind == "drive_text" and quick.detail == "history essay"
    assert match_quick_command("open number 3").kind == "open_number"
