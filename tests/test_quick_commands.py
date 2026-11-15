from datetime import datetime

from babysitter.commands import clock_in, match_quick_command, timer_label
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
