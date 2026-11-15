"""Five simulations each for the journal, the file search, and the memory."""

import json
from datetime import date, datetime, timedelta

from babysitter import journal
from babysitter.commands import match_quick_command
from babysitter.embedder import (
    VectorCache,
    rank_texts,
    wordpiece_ids,
)
from babysitter.filefind import (
    NEVER_OPEN,
    FoundFile,
    default_folders,
    match_files,
    open_found,
    parse_query,
    scan_folders,
    search_reply,
)
from babysitter.security import DOWNLOAD_SHA256, EMBEDDER_MODEL_URLS, require_embedder_url
from babysitter.settings import migrate, settings_from_dict


NOON = datetime(2026, 11, 14, 12, 0)


# ---------------------------------------------------------------------------
# The day journal.


def test_a_day_collects_minutes_per_program(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    record = journal.load_day(NOON.date())
    for tick in range(6):
        journal.record_sample(record, "Blender.exe", NOON + timedelta(seconds=30 * tick))
    for tick in range(2):
        journal.record_sample(record, "bg3.exe", NOON + timedelta(minutes=3, seconds=30 * tick))
    journal.save_day(record)
    loaded = journal.load_day(NOON.date())
    assert loaded["apps"]["blender"]["seconds"] == 180
    assert loaded["apps"]["bg3"]["seconds"] == 60
    speech = journal.day_speech(loaded)
    assert "3 minutes in blender" in speech
    assert "1 minute in bg3" in speech


def test_excluded_and_odd_names_are_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    record = journal.load_day(NOON.date())
    assert journal.record_sample(record, "private.exe", NOON, excluded=["private.exe"]) is False
    assert journal.record_sample(record, "Private.EXE", NOON, excluded=["private"]) is False
    assert journal.record_sample(record, "", NOON) is False
    assert journal.record_sample(record, "x" * 200, NOON) is False
    assert record["apps"] == {}
    assert "Nothing is in the journal" in journal.day_speech(record)


def test_tasks_open_and_close_with_their_time(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    record = journal.load_day(NOON.date())
    assert journal.finish_task(record, NOON).startswith("No task is open")
    spoken = journal.start_task(record, "modeling the bracket", NOON)
    assert "Started modeling the bracket" in spoken
    # Starting another task closes the first one.
    second = journal.start_task(record, "slicing", NOON + timedelta(minutes=45))
    assert "modeling the bracket took 45 minutes" in second
    done = journal.finish_task(record, NOON + timedelta(hours=2))
    assert "slicing took 1 hour 15 minutes" in done
    detail = journal.day_detail(record)
    assert "modeling the bracket" in detail
    assert "Nothing left this PC" in detail


def test_old_days_are_pruned_and_a_wipe_removes_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    today = date(2026, 11, 14)
    for days_ago in (0, 30, 91, 200):
        day = today - timedelta(days=days_ago)
        record = journal.load_day(day)
        journal.record_sample(record, "blender.exe", datetime.combine(day, NOON.time()))
        journal.save_day(record)
    assert journal.prune(today) == 2
    kept = sorted(path.stem for path in journal.journal_dir().glob("*.json"))
    assert kept == ["2026-10-15", "2026-11-14"]
    assert journal.wipe() == 2
    assert list(journal.journal_dir().glob("*.json")) == []


def test_a_damaged_day_file_is_cleaned_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    bad = {
        "date": "2026-03-03",
        "apps": {"blender": "junk", "odd.exe": {"seconds": "9zz"}, "cura": {"seconds": 90}},
        "tasks": ["junk", {"noname": 1}, {"name": "real", "start": "", "end": ""}],
    }
    journal.day_path(date(2026, 3, 3)).write_text(json.dumps(bad), encoding="utf-8")
    clean = journal.load_day(date(2026, 3, 3))
    assert list(clean["apps"]) == ["cura"]
    assert [task["name"] for task in clean["tasks"]] == ["real"]
    # The exact write that used to crash the sampler on such a file.
    assert journal.record_sample(clean, "blender.exe", datetime(2026, 3, 3, 10, 0)) is True


def test_journal_phrases_are_quick_commands():
    assert match_quick_command("what did I do today").kind == "journal_today"
    assert match_quick_command("what did i do yesterday").kind == "journal_yesterday"
    started = match_quick_command("start task modeling the bracket")
    assert started.kind == "task_start"
    assert started.detail == "modeling the bracket"
    assert match_quick_command("done").kind == "task_done"
    assert match_quick_command("pause the journal").kind == "journal_pause"
    assert match_quick_command("resume the journal").kind == "journal_resume"
    assert match_quick_command("what did i do wrong") is None


# ---------------------------------------------------------------------------
# The file search.


def _entry(name: str, modified: float) -> FoundFile:
    return FoundFile(name, f"C:\\Users\\me\\Documents\\{name}", modified)


def test_the_default_folders_include_the_onedrive_homes(tmp_path):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    (home / "OneDrive" / "Documents").mkdir(parents=True)
    (home / "Documents" / "tax.pdf").write_text("x", encoding="utf-8")
    (home / "OneDrive" / "Documents" / "cloudtax.pdf").write_text("x", encoding="utf-8")
    names = {found.name for found in scan_folders(default_folders(home))}
    assert names == {"tax.pdf", "cloudtax.pdf"}


def test_spoken_requests_become_words_and_kinds():
    words, kinds = parse_query("pull up my current tax pdf")
    assert words == ["tax"]
    assert kinds == {".pdf"}
    words, kinds = parse_query("find all stls")
    assert words == []
    assert kinds == {".stl"}
    words, kinds = parse_query("the dragon file")
    assert words == ["dragon"]
    assert kinds == set()


def test_current_means_the_one_opened_last():
    entries = [
        _entry("tax-2024.pdf", 100.0),
        _entry("tax-2025.pdf", 50.0),
        _entry("holiday.pdf", 999.0),
    ]
    opened = {"tax-2025.pdf": 500.0}
    matches = match_files("current tax pdf", entries, opened)
    assert [found.name for found in matches] == ["tax-2025.pdf", "tax-2024.pdf"]
    speech, _detail, best = search_reply("current tax pdf", matches[:1], default_folders())
    assert best is not None and best.name == "tax-2025.pdf"
    assert "Opening tax-2025.pdf" in speech


def test_a_partial_name_lists_matches_instead_of_an_error():
    entries = [
        _entry("dragon-head.stl", 300.0),
        _entry("dragon-body.stl", 200.0),
        _entry("Dragon notes.txt", 100.0),
        _entry("boat.stl", 50.0),
    ]
    matches = match_files("find all dragons", entries)
    assert [found.name for found in matches] == [
        "dragon-head.stl",
        "dragon-body.stl",
        "Dragon notes.txt",
    ]
    speech, detail, best = search_reply("all dragons", matches, default_folders())
    assert best is None
    assert "Found 3" in speech and "open number 1 to 3" in speech
    assert "1. dragon-head.stl" in detail
    stls = match_files("find all stls", entries)
    assert [found.name for found in stls] == ["dragon-head.stl", "dragon-body.stl", "boat.stl"]


def test_a_miss_names_the_folders_and_never_errors():
    speech, detail, best = search_reply("blue parrot", [], ["C:\\Users\\me\\Documents"])
    assert best is None
    assert "Nothing matching blue parrot" in speech
    assert "Documents" in speech
    assert "C:\\Users\\me\\Documents" in detail
    assert match_files("", [_entry("a.txt", 1.0)]) == []


def test_the_scan_stays_shallow_and_skips_hidden_folders(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "dragon.stl").write_text("solid", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret.txt").write_text("no", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("no", encoding="utf-8")
    deep = tmp_path
    for level in range(8):
        deep = deep / f"level{level}"
    deep.mkdir(parents=True)
    (deep / "toodeep.txt").write_text("no", encoding="utf-8")
    names = {found.name for found in scan_folders([str(tmp_path), str(tmp_path / "missing")])}
    assert names == {"dragon.stl"}


def test_a_program_is_listed_but_never_started():
    for name in ("setup.exe", "patch.bat", "fix.ps1", "Shortcut.LNK", "tool.vbs", "run.py"):
        spoken = open_found(_entry(name, 1.0))
        assert "was not started" in spoken, name
    # The dangerous kinds stay dangerous even if someone edits one out.
    assert {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".lnk", ".msi", ".scr"} <= NEVER_OPEN
    # A document is allowed; off Windows that is a polite no-op.
    assert "not started" not in open_found(_entry("taxes.pdf", 1.0))


def test_find_phrases_are_quick_commands_but_questions_are_not():
    found = match_quick_command("pull up my current tax pdf")
    assert found.kind == "find"
    assert found.detail == "my current tax pdf"
    assert match_quick_command("find all stls").detail == "all stls"
    opened = match_quick_command("open number 3")
    assert opened.kind == "open_number" and opened.seconds == 3
    assert match_quick_command("open number 99").seconds == 99
    assert match_quick_command("find out about the weather") is None
    assert match_quick_command("look for news about space") is None


# ---------------------------------------------------------------------------
# The sharper memory.


def test_the_download_is_pinned_and_other_urls_are_refused():
    for url in EMBEDDER_MODEL_URLS:
        require_embedder_url(url)
        assert len(DOWNLOAD_SHA256[url]) == 64
    try:
        require_embedder_url("https://huggingface.co/evil/model.onnx")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("A strange URL was accepted.")


def test_wordpiece_splits_like_bert():
    vocab = {
        "[CLS]": 0, "[SEP]": 1, "[UNK]": 2,
        "my": 3, "print": 4, "##er": 5, "is": 6, "a": 7, "bamboo": 8,
    }
    ids = wordpiece_ids("My printer is a Bamboo!", vocab)
    # printer = print + ##er, and ! is not in the vocab so it is unknown.
    assert ids == [0, 3, 4, 5, 6, 7, 8, 2, 1]


def test_without_the_model_the_hashed_match_still_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    facts = ["I have a Prusa printer.", "My dog is called Biscuit.", ""]
    found = rank_texts("what printer do I have", facts)
    assert found == ["I have a Prusa printer."]
    dog = ["My dog is called Biscuit.", "The wifi name is North."]
    assert rank_texts("what is my dog called", dog) == ["My dog is called Biscuit."]
    assert rank_texts("completely unrelated question", ["something else entirely"]) == []


def test_fact_vectors_are_cached_beside_the_facts(tmp_path):
    cache = VectorCache(tmp_path / "memory-vectors.json")
    assert cache.get("My printer is a Prusa.") is None
    cache.put("My printer is a Prusa.", [0.25, -0.5])
    cache.save()
    again = VectorCache(tmp_path / "memory-vectors.json")
    assert again.get("My printer is a Prusa.") == [0.25, -0.5]
    # The file holds hashes and numbers, never the words themselves.
    raw = (tmp_path / "memory-vectors.json").read_text(encoding="utf-8")
    assert "Prusa" not in raw


def test_the_onnx_path_ranks_by_meaning_with_a_fake_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))

    class FakeEngine:
        def embed(self, text: str) -> list[float]:
            # A toy meaning space: pets on one axis, printers on the other.
            pets = 1.0 if any(word in text.lower() for word in ("dog", "biscuit", "pet")) else 0.0
            printers = 1.0 if any(word in text.lower() for word in ("printer", "prusa")) else 0.0
            norm = (pets * pets + printers * printers) ** 0.5 or 1.0
            return [pets / norm, printers / norm]

    monkeypatch.setattr("babysitter.embedder._shared_engine", lambda: FakeEngine())
    facts = ["My printer is a Prusa.", "My dog is called Biscuit."]
    assert rank_texts("what is my pet's name", facts) == ["My dog is called Biscuit."]
    cache = VectorCache()
    assert cache.get("My dog is called Biscuit.") is not None
    # A deleted fact's vector is swept out on the next question.
    rank_texts("anything", ["My printer is a Prusa."])
    swept = VectorCache()
    assert swept.get("My dog is called Biscuit.") is None
    assert swept.get("My printer is a Prusa.") is not None


# ---------------------------------------------------------------------------
# Settings carry the new switches.


def test_an_eleventh_schema_file_gains_the_new_fields():
    upgraded = migrate({"schema_version": 11, "intelligence": "low"})
    assert upgraded["schema_version"] == 13
    assert upgraded["journal_enabled"] is True
    assert upgraded["game_mode_ask"] is False
    assert upgraded["journal_excluded"] == []
    assert upgraded["search_folders"] == []
    settings = settings_from_dict(upgraded)
    assert settings.journal_enabled is True
    assert settings.intelligence == "low"


def test_folder_and_name_lists_are_cleaned_not_trusted():
    settings = settings_from_dict(
        migrate(
            {
                "schema_version": 12,
                "journal_excluded": ["Private.exe", "private.exe", 7, ""],
                "search_folders": ["C:\\Prints", "c:\\prints", 3, ""],
            }
        )
    )
    assert settings.journal_excluded == ["Private.exe"]
    assert settings.search_folders == ["C:\\Prints"]
