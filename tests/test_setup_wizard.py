"""What a GitHub visitor still has to download, and the one-file exe."""

from pathlib import Path

import pytest

from babysitter.intelligence import MAIN_MODEL, WRITING_MODEL
from babysitter.setupneed import (
    GITHUB_ZIP,
    Machine,
    commands_for,
    models_from_list_text,
    perform_pulls,
    pieces,
    portable_note,
    pull_commands,
    report,
    visitor_summary,
)


ROOT = Path(__file__).resolve().parents[1]
OLLAMA = r"C:\Users\Me\AppData\Local\Programs\Ollama\ollama.exe"


def test_github_holds_source_and_not_the_models():
    text = visitor_summary()
    by_name = {piece.name: piece for piece in pieces()}
    assert "does not hold a finished .exe" in text
    assert MAIN_MODEL in text and WRITING_MODEL in text
    assert GITHUB_ZIP.endswith("/archive/refs/heads/main.zip")
    assert by_name["program source"].on_github
    assert by_name["requirements.txt"].on_github
    assert not by_name[MAIN_MODEL].on_github
    assert not by_name[WRITING_MODEL].on_github
    assert not by_name["Ollama"].on_github
    assert not by_name["Ollama"].wizard_downloads
    assert not by_name["Python 3.12"].wizard_downloads
    assert not by_name["NVIDIA driver"].wizard_downloads
    assert by_name["Python libraries"].wizard_downloads
    assert by_name[MAIN_MODEL].wizard_downloads


def test_a_fresh_pc_is_told_what_is_missing_and_nothing_is_pulled():
    machine = Machine(False, False, None, (), False)
    text = report(machine)
    assert "Python 3.12" in text
    assert "Ollama" in text
    assert MAIN_MODEL in text
    assert WRITING_MODEL in text
    assert "NVIDIA" in text
    assert commands_for(machine) == ()
    ran: list[list[str]] = []
    lines = perform_pulls(machine, lambda command: ran.append(command) or 0, confirmed=True)
    assert ran == []
    assert lines == (
        "Ollama is not installed. Nothing was downloaded. The page is https://ollama.com/download",
    )


def test_ollama_without_models_pulls_only_the_two_known_names():
    machine = Machine(True, True, OLLAMA, (), True)
    assert commands_for(machine) == (
        (OLLAMA, "pull", MAIN_MODEL),
        (OLLAMA, "pull", WRITING_MODEL),
    )
    ran: list[list[str]] = []
    lines = perform_pulls(machine, lambda command: ran.append(list(command)) or 0, confirmed=True)
    assert ran == [
        [OLLAMA, "pull", MAIN_MODEL],
        [OLLAMA, "pull", WRITING_MODEL],
    ]
    assert lines == (f"Downloaded {MAIN_MODEL}.", f"Downloaded {WRITING_MODEL}.")
    refused = perform_pulls(machine, lambda command: ran.append(list(command)) or 0, confirmed=False)
    assert refused == ("Nothing was downloaded.",)
    assert len(ran) == 2


def test_models_already_here_are_not_downloaded_again():
    listed = models_from_list_text(
        "NAME            ID              SIZE    MODIFIED\n"
        f"{MAIN_MODEL}:latest    abc    5.4 GB    yesterday\n"
        f"{WRITING_MODEL}         def    7 GB      today\n"
    )
    machine = Machine(True, True, "ollama", listed, True)
    text = report(machine)
    assert "already downloaded" in text
    assert commands_for(machine) == ()
    lines = perform_pulls(machine, lambda command: 0, confirmed=True)
    assert lines == ("Both models are already downloaded.",)


def test_a_model_name_that_is_not_ours_is_refused():
    with pytest.raises(ValueError) as caught:
        pull_commands("ollama", (MAIN_MODEL, "evil:latest"))
    assert MAIN_MODEL in str(caught.value)
    assert "evil:latest" not in str(caught.value)


def test_a_failed_pull_does_not_start_the_next_model():
    machine = Machine(True, True, OLLAMA, (), True)
    ran: list[str] = []

    def runner(command: list[str]) -> int:
        ran.append(command[-1])
        return 1

    lines = perform_pulls(machine, runner, confirmed=True)
    assert ran == [MAIN_MODEL]
    assert lines == (f"{MAIN_MODEL} did not finish. Nothing else was downloaded.",)


def test_an_unread_model_list_downloads_nothing():
    machine = Machine(True, True, OLLAMA, None, True)
    text = report(machine)
    assert "could not be read" in text
    lines = perform_pulls(machine, lambda command: 0, confirmed=True)
    assert lines == ("Ollama's model list could not be read. Nothing was downloaded.",)


def test_the_built_program_is_one_file_you_can_move():
    spec = (ROOT / "packaging" / "babysitter.spec").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "BabySitter.iss").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build-exe.bat").read_text(encoding="utf-8")
    setup = (ROOT / "Setup.bat").read_text(encoding="utf-8")
    note = portable_note()
    assert "COLLECT" not in spec
    assert "exclude_binaries=False" in spec
    assert "a.binaries" in spec
    assert "a.datas" in spec
    assert 'Source: "..\\dist\\BabySitter.exe"' in installer
    assert "dist\\BabySitter\\*" not in installer
    assert "dist\\BabySitter.exe" in build
    assert "Desktop\\BabySitter.exe" in build
    assert "py -3.12 -m venv .venv" in setup
    assert "requirements.txt" in setup
    assert "--pull --yes" in setup
    assert "pause" in setup
    assert "desktop" in note.lower()
    assert "%LOCALAPPDATA%" in note
