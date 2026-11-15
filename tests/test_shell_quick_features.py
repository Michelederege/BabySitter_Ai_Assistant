"""Drives the new spoken commands through the real window, offscreen."""

import os
import time
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def test_journal_search_and_numbers_through_the_window(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path / "data"))
    app = QApplication.instance() or QApplication([])
    from babysitter import journal
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    spoken: list[str] = []
    monkeypatch.setattr(shell, "_speak", spoken.append)

    # A day with an hour of blender already in it.
    record = journal.load_day(date.today())
    for tick in range(120):
        journal.record_sample(record, "blender.exe", datetime.now())
    journal.save_day(record)
    assert shell._run_quick("what did i do today") is True
    assert "blender" in spoken[-1]

    assert shell._run_quick("start task wiring the shell") is True
    assert "Started wiring the shell" in spoken[-1]
    assert shell._run_quick("done") is True
    assert "wiring the shell took" in spoken[-1]

    assert shell._run_quick("pause the journal") is True
    assert controller.journal_paused is True
    assert shell._run_quick("resume the journal") is True
    assert controller.journal_paused is False

    # A task left open before midnight is finished on yesterday's page.
    from datetime import timedelta

    yesterday = journal.load_day(date.today() - timedelta(days=1))
    journal.start_task(yesterday, "overnight print", datetime.now() - timedelta(hours=3))
    journal.save_day(yesterday)
    assert shell._run_quick("done") is True
    assert "overnight print took 3 hours" in spoken[-1]
    saved = journal.load_day(date.today() - timedelta(days=1))
    assert saved["tasks"][-1]["end"] != ""

    # Two files to find; the search runs on its own thread.
    prints = tmp_path / "prints"
    prints.mkdir()
    (prints / "dragon-head.stl").write_text("solid", encoding="utf-8")
    (prints / "dragon-body.stl").write_text("solid", encoding="utf-8")
    controller.settings.search_folders = [str(prints)]
    assert shell._run_quick("find all dragons") is True
    job = shell._find_job
    assert job.wait(5000)
    app.processEvents()
    assert "Found 2" in spoken[-1]
    assert len(shell._found_files) == 2

    # Numbers open from the list; a bad number is named, an old list is refused.
    assert shell._run_quick("open number 9") is True
    assert "1 to 2" in spoken[-1]
    shell._found_at = time.time() - 700
    assert shell._run_quick("open number 1") is True
    assert "from a while ago" in spoken[-1]

    # A miss is a sentence, not an error.
    assert shell._run_quick("find the blue parrot") is True
    assert "Nothing matching" in spoken[-1]

    # The sharper-matching button exists and is enabled until the download.
    assert shell.window.memory_page.sharper.isEnabled() is True

    shell.registrar.clear()
    controller.shutdown_threads()
    app.processEvents()
