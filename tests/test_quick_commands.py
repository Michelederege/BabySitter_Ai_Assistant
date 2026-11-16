from datetime import datetime

from babysitter.commands import clock_in, match_quick_command, spoken_when, timer_label, when_from
from babysitter.pictures import benchmark_warning, format_benchmark, image_tokens, room_for_model, scaled_size
from babysitter.plugins.voice.speech import spell_codes, voice_and_rest


def test_short_requests_do_not_need_the_model():
    assert match_quick_command("what time is it").kind == "time"
    assert match_quick_command("what's my vram").kind == "vram"
    assert match_quick_command("look at my screen").kind == "screen"
    assert match_quick_command("read the small text").kind == "screen_text"
    assert match_quick_command("why did you say that").kind == "why"
    assert match_quick_command("weekly review").kind == "weekly"
    assert match_quick_command("rate that shorter").detail == "shorter"
    assert match_quick_command("how is my pc").kind == "health"
    assert match_quick_command("undo").kind == "undo"
    timer = match_quick_command("set a timer for 20 minutes")
    assert timer.kind == "timer"
    assert timer.seconds == 20 * 60
    assert timer_label(20 * 60) == "20 minutes"
    assert match_quick_command("who invented dancing") is None


def test_a_clock_reminder_is_saved_here_and_history_is_not_sent_to_the_model():
    bedtime = match_quick_command("can you set a reminder at one thirty to go to bed")
    assert bedtime is not None and bedtime.kind == "remind"
    assert bedtime.detail == "to go to bed"
    assert bedtime.when
    moment = datetime.fromisoformat(bedtime.when)
    assert (moment.hour, moment.minute) in {(1, 30), (13, 30)}
    plain = match_quick_command("remind me to call Mom")
    assert plain is not None and plain.detail == "to call Mom" and plain.when == ""
    fixed = datetime(2026, 11, 15, 1, 28, tzinfo=datetime.now().astimezone().tzinfo)
    upcoming = clock_in("at one thirty", fixed)
    assert upcoming is not None
    assert upcoming.hour == 1 and upcoming.minute == 30
    assert upcoming > fixed
    history = match_quick_command("read out my history")
    assert history is not None and history.kind == "history"
    assert match_quick_command("set a timer for 30 seconds").kind == "timer"
    oven = match_quick_command("set a timer for 20 minutes to check the oven")
    assert oven is not None and oven.kind == "timer" and oven.detail == "check the oven"
    named = match_quick_command("set a timer to call Mom at 6 pm")
    assert named is not None and named.kind == "remind" and "Mom" in named.detail and named.when
    from babysitter.commands import reminder_fields

    zone = datetime.now().astimezone().tzinfo
    morning = datetime(2026, 11, 16, 10, 0, tzinfo=zone)
    note, due = reminder_fields("stretch", "6:00 PM", morning)
    assert note == "stretch" and due
    assert datetime.fromisoformat(due).hour in {6, 18}
    later = when_from("tomorrow at 6", morning)
    assert later is not None and spoken_when(later, morning) == "6:00 AM tomorrow"
    assert later is not None and later.date().day == 17 and later.hour == 6
    evening = when_from("tomorrow at 6 pm", morning)
    assert evening is not None and evening.date().day == 17 and evening.hour == 18
    named_day = when_from("at 6:00 PM tomorrow", morning)
    assert named_day is not None and named_day.date().day == 17 and named_day.hour == 18
    bare_day = when_from("tomorrow", morning)
    assert bare_day is not None and bare_day.date().day == 17 and bare_day.hour == 9
    tomorrow = match_quick_command("remind me tomorrow")
    assert tomorrow is not None and tomorrow.kind == "remind" and tomorrow.detail == "Reminder"
    assert datetime.fromisoformat(tomorrow.when).hour == 9
    bare = match_quick_command("set a timer")
    assert bare is not None and bare.kind == "remind" and bare.detail == "Timer"
    wait = datetime.fromisoformat(bare.when) - datetime.now().astimezone()
    assert 4 * 60 <= wait.total_seconds() <= 5 * 60 + 2


def test_a_reminder_counts_down_until_it_rings():
    from datetime import timedelta

    from babysitter.deskstore import next_reminder_line, remaining_clock, reminder_line

    now = datetime(2026, 11, 16, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    due = (now + timedelta(seconds=90)).isoformat()
    assert remaining_clock(due, now) == "1:30"
    assert reminder_line({"text": "stretch", "due": due}, now).endswith("— 1:30")
    hour = (now + timedelta(hours=1, seconds=1)).isoformat()
    assert remaining_clock(hour, now) == "1:00:01"
    assert next_reminder_line([{"text": "stretch", "due": due}], now) == "stretch — 1:30"
    assert next_reminder_line([], now) == "No reminder is counting down."
    said = reminder_line({"text": "stretch", "due": due, "fired": "yes"}, now)
    assert "already said" in said and "1:30" not in said.split("—")[-1]


def test_the_voice_keeps_the_rest_and_trims_the_padding():
    from babysitter.deskstore import reminder_line
    from babysitter.plugins.voice.kokoro_voice import trim_edges
    from babysitter.plugins.voice.speech import rest_after_lead

    assert rest_after_lead("It is 1:30.", "It is 1:30. Then go to bed.") == "Then go to bed."
    assert rest_after_lead("It is 1:30.", "It is 1:30.") == ""
    samples = [0.0] * 24000
    samples[8000] = 0.5
    samples[9000] = 0.5
    trimmed = trim_edges(samples, 24000)
    assert len(trimmed) < len(samples)
    assert max(trimmed) == 0.5
    line = reminder_line({"text": "go to bed", "due": "2026-11-15T13:30", "fired": "yes"})
    assert "go to bed" in line and "already said" in line


def test_a_long_sentence_is_split_before_the_voice_reads_it():
    from babysitter.plugins.voice.speech import speech_chunks

    chunks = speech_chunks(" ".join(["word"] * 200), limit=80)
    assert chunks
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_a_picture_is_shrunk_and_a_full_card_is_refused():
    assert scaled_size(2560, 1440) == (1280, 720)
    assert scaled_size(800, 600) == (800, 600)
    assert room_for_model(None, "gemma4:12b") is None
    assert room_for_model(12000, "qwen3.5:9b") is None
    assert room_for_model(7000, "qwen3.5:9b", 4096) is None
    assert "not enough video memory" in room_for_model(5000, "qwen3.5:9b", 4096)
    assert "not enough video memory" in room_for_model(4000, "gemma4:12b")


def test_long_lists_and_codes_stay_readable():
    listed = "Here are the steps.\n- one\n- two\n- three\n- four"
    spoken, rest = voice_and_rest(listed)
    assert spoken.startswith("Here are the steps")
    assert rest == ""
    assert spell_codes("See KB5034441 and 0x80070005.") == "See K B 5 0 3 4 4 4 1 and 0 x 8 0 0 7 0 0 0 5."
    assert "3:15" in spell_codes("It is 3:15.")


def test_benchmark_keeps_times_only():
    text = format_benchmark([900, 1100, 1000])
    assert "900 ms" in text
    assert "ready" not in text.lower()
    detailed = format_benchmark([{"load_ms": 0, "prompt_tps": 2100, "gen_tps": 62}])
    assert "62" in detailed
    assert "ready" not in detailed.lower()
    assert benchmark_warning(40, 70)
    assert benchmark_warning(68, 70) is None
    assert image_tokens(1280, 720) == 900
