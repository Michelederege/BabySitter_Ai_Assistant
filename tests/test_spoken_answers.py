"""Long run, scan H (0.29.0): local answers read as sentences, not screen labels."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from babysitter.deskstore import _spoken_length, next_reminder_speech
from babysitter.phrasing import PhraseBook

NOW = datetime(2026, 11, 27, 12, 0).astimezone()


def _due(**delta) -> str:
    return (NOW + timedelta(**delta)).isoformat()


@pytest.mark.parametrize("seconds, said", [
    (29, "29 seconds"), (89, "1 minute 29 seconds"), (600, "10 minutes"),
    (3599, "1 hour"), (7199, "2 hours"), (7260, "2 hours 1 minute"), (90000, "about 1 day"),
])
def test_lengths_are_said_like_a_person(seconds, said):
    assert _spoken_length(seconds) == said


def test_the_next_reminder_is_a_sentence():
    assert next_reminder_speech([{"text": "Timer", "due": _due(seconds=89)}], NOW) == "1 minute 29 seconds left on the timer."
    assert next_reminder_speech([{"text": "Alarm", "due": _due(hours=7, minutes=3)}], NOW) == "Your alarm goes off in 7 hours 3 minutes."
    assert next_reminder_speech([{"text": "to call mom", "due": _due(minutes=45)}], NOW) == "In 45 minutes: call mom."
    two = [{"text": "drink water", "due": _due(seconds=7199)}, {"text": "Alarm", "due": _due(hours=20)}]
    assert next_reminder_speech(two, NOW) == "In 2 hours: drink water. One more after that."
    assert next_reminder_speech([], NOW) == "Nothing is counting down."
    for items in ([{"text": "Timer", "due": _due(seconds=89)}], two):
        assert "—" not in next_reminder_speech(items, NOW)


@pytest.mark.parametrize("fact, said", [
    ("my favourite colour is green", "your favourite colour is green"),
    ("I'm allergic to nuts", "You're allergic to nuts"),
    ("Anna is my sister", "Anna is your sister"),
    ("I like Imagine Dragons", "You like Imagine Dragons"),
])
def test_saved_facts_are_said_back_to_you(fact, said):
    assert PhraseBook.said_back(fact) == said
