"""The handoff notes must describe the current version.

Alex moves between agents, and the next one picks up only from these
two files. AGENTS.md makes updating them part of every change; this test
catches a version bump that forgot them.
"""

from pathlib import Path

from babysitter.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_the_status_page_names_the_current_version():
    text = (ROOT / "docs" / "build-status.md").read_text(encoding="utf-8")
    assert f"**{__version__}**" in text, (
        f"docs/build-status.md does not mention version {__version__}. "
        "Update it with this change (AGENTS.md: keep the handoff notes current)."
    )


def test_the_handoff_record_names_the_current_version():
    text = (ROOT / "docs" / "agent-memory.md").read_text(encoding="utf-8")
    assert f"version {__version__}" in text, (
        f"docs/agent-memory.md does not say it was checked at version {__version__}. "
        "Update it with this change (AGENTS.md: keep the handoff notes current)."
    )


def test_agents_md_keeps_the_rule():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep the handoff notes current" in text
