"""Long run, scan A (0.29.0): nothing opens that you did not ask for.

"Find …" used to catch everyday questions, and a single match opened at
once, so a question could pop a document open. Now a question with no
file behind it goes to the model, and a single loose match is listed, not
opened.
"""

from __future__ import annotations

import pytest

from babysitter.commands import match_quick_command
from babysitter.filefind import FoundFile, names_it, search_reply, sounds_like_a_question


def _file(name: str) -> FoundFile:
    return FoundFile(name, "C:/Users/me/Documents/" + name, 0.0)


@pytest.mark.parametrize("question", [
    "find me a recipe for pancakes",
    "find the capital of australia",
    "find a good movie to watch",
    "find the derivative of x squared",
    "find directions to the mall",
    "find time for a walk",
    "find the answer to question three",
])
def test_questions_are_questions(question):
    quick = match_quick_command(question)
    assert quick is not None and quick.kind == "find"  # still searched first, in case a file matches
    assert sounds_like_a_question(quick.detail)


@pytest.mark.parametrize("request_", ["find my essay", "find the history paper", "find the blue parrot", "find all dragons", "look for my notes"])
def test_file_requests_stay_file_requests(request_):
    assert not sounds_like_a_question(match_quick_command(request_).detail)


def test_a_loose_single_match_is_listed_not_opened():
    speech, detail, best = search_reply("my keys", [_file("keyset-backup.zip")], ["Documents"])
    assert best is None and "Say open it" in speech and "keyset-backup.zip" in detail


def test_a_clear_single_match_still_opens():
    speech, _detail, best = search_reply("my history essay", [_file("History Essay.docx")], ["Documents"])
    assert best is not None and speech.startswith("Opening History Essay.docx")
    assert names_it("all dragons", _file("dragon-head.stl"))


def test_a_question_that_happens_to_match_is_not_opened():
    _speech, _detail, best = search_reply("the capital of australia", [_file("capital of australia.pdf")], ["Documents"])
    assert best is None


@pytest.mark.parametrize("phrase", ["open it", "open that", "open that one"])
def test_open_it_means_the_file_just_found(phrase):
    quick = match_quick_command(phrase)
    assert quick is not None and quick.kind == "open_number" and quick.seconds == 1


def test_a_search_with_nothing_found_hands_a_question_to_the_model(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    shell = Shell(Controller())
    try:
        sent = []
        monkeypatch.setattr(shell, "_send_heard", lambda: sent.append((shell._pending_line, shell._skip_quick_once)))
        shell._finish_find("find the capital of australia", "the capital of australia", [], {})
        assert sent == [("find the capital of australia", True)]
        spoken = []
        monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append(text))
        shell._finish_find("find the blue parrot", "the blue parrot", [], {})
        assert "Nothing matching" in spoken[-1] and len(sent) == 1
    finally:
        shell.window.close()
