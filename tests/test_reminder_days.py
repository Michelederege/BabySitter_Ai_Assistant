"""0.31.0: reminders understand weekdays, dates and the part of the day.

Before, "remind me on Friday at 3 pm" was saved for tomorrow at 3, "December 3"
was dropped, and "set an alarm for 6:30 am tomorrow" rang at 9.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from babysitter.commands import match_quick_command, spoken_when, when_from

ZONE = datetime.now().astimezone().tzinfo
# Friday 27 November 2026, 3:55 in the afternoon.
NOW = datetime(2026, 11, 27, 15, 55, tzinfo=ZONE)


@pytest.mark.parametrize("words, day, hour, minute", [
    ("on Friday at 3 pm", (12, 4), 15, 0),          # today's 3 pm has gone: next Friday
    ("on Friday at 5 pm", (11, 27), 17, 0),         # still ahead today
    ("next Friday at 5 pm", (12, 4), 17, 0),
    ("next tuesday at 4 pm", (12, 1), 16, 0),
    ("on monday", (11, 30), 9, 0),
    ("on December 3 at 10 am", (12, 3), 10, 0),
    ("on the 3rd of december", (12, 3), 9, 0),
    ("on december twenty fifth at 8 am", (12, 25), 8, 0),
    ("on january 2nd at 9 am", (1, 2), 9, 0),        # next year
    ("6:30 am tomorrow", (11, 28), 6, 30),
    ("tomorrow morning at 8", (11, 28), 8, 0),
    ("this evening at 7", (11, 27), 19, 0),
    ("the day after tomorrow at noon", (11, 29), 12, 0),
])
def test_days_and_dates(words, day, hour, minute):
    moment = when_from(words, NOW)
    assert moment is not None, words
    assert (moment.month, moment.day, moment.hour, moment.minute) == (*day, hour, minute), words


def test_a_weekday_inside_the_note_stays_words():
    said = match_quick_command("can you remind me the bins are Thursday")
    assert said is not None and said.detail == "the bins are Thursday" and not said.when


def test_the_day_leaves_the_note():
    said = match_quick_command("remind me on Friday at 3 pm to go to the dentist")
    assert said is not None and said.when and "Friday" not in said.detail
    evening = match_quick_command("remind me this evening at 7 to cook")
    assert evening is not None and "evening" not in evening.detail


def test_an_alarm_with_tomorrow_after_the_time():
    said = match_quick_command("set an alarm for 6:30 am tomorrow")
    moment = datetime.fromisoformat(said.when)
    assert (moment.hour, moment.minute) == (6, 30)


def test_spoken_days():
    assert spoken_when(datetime(2026, 11, 30, 9, 0, tzinfo=ZONE), NOW) == "9:00 AM on Monday"
    assert spoken_when(datetime(2026, 12, 25, 8, 0, tzinfo=ZONE), NOW) == "8:00 AM on Friday, December 25"


# ---------- audit 2 regressions ----------

@pytest.mark.parametrize("words, day, hour", [
    ("in 2 days at 9", (11, 29), 9),          # was today at 9
    ("in 3 days", (11, 30), 9),               # was not understood
    ("in a week", (12, 4), 9),
    ("in 2 weeks at 10 am", (12, 11), 10),
    ("next friday at 3", (12, 4), 15),        # was 3 AM
    ("tomorrow at 3", (11, 28), 15),
    ("the day after tomorrow at 4", (11, 29), 16),
    ("tomorrow at 6", (11, 28), 6),           # 6 to 11 stays the morning
    ("on monday at 9", (11, 30), 9),
    ("tonight at 2", (11, 28), 2),            # was 2 PM tomorrow
    ("tonight at 11", (11, 27), 23),
    ("on february 29 at 9", (2, 29), 9),      # next leap year, not today
])
def test_more_days(words, day, hour):
    moment = when_from(words, NOW)
    assert moment is not None, words
    assert (moment.month, moment.day, moment.hour) == (*day, hour), words


def test_a_date_that_doesnt_exist_isnt_today():
    assert when_from("on november 31st", NOW) is None
    assert when_from("on february 30th", NOW) is None


@pytest.mark.parametrize("line, kind", [
    ("can you remember the name of that movie with the robot", None),
    ("do you remember what we said", None),
    ("can you remember the cat is called Moth", "remember"),
    ("can you remember that my locker is 12", "remember"),
    ("how much vram do I need for 4k", None),
    ("whats my vram", "vram"),
    ("how much vram is free", "vram"),
    ("reference this in my essay", None),
    ("reference this page in apa", "cite"),
])
def test_questions_that_looked_like_commands(line, kind):
    said = match_quick_command(line)
    assert (said.kind if said else None) == kind, line
