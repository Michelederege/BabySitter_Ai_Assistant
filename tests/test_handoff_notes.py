"""The private handoff notes must describe the current version.

The notes (docs/agent-memory.md, docs/build-status.md, AGENTS.md) live only on
the owner's PC; git ignores them, so they are not in the public repository.
Where they exist, this catches a version bump that forgot them; where they
don't (GitHub's test run), it skips.
"""

from pathlib import Path

import pytest

from babysitter.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def _notes(*parts: str) -> str:
    path = ROOT.joinpath(*parts)
    if not path.is_file():
        pytest.skip(f"{path.name} is a private note, not in this checkout")
    return path.read_text(encoding="utf-8")


def test_the_status_page_names_the_current_version():
    assert f"**{__version__}**" in _notes("docs", "build-status.md"), (
        f"docs/build-status.md does not mention version {__version__}. Update it with this change."
    )


def test_the_handoff_record_names_the_current_version():
    assert f"version {__version__}" in _notes("docs", "agent-memory.md"), (
        f"docs/agent-memory.md does not say it was checked at version {__version__}. Update it with this change."
    )


def test_agents_md_keeps_the_rule():
    assert "Keep the handoff notes current" in _notes("AGENTS.md")
