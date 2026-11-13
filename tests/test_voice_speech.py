from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import first_sentence, for_speech, sapi_rate
from babysitter.plugins.voice.windows_voice import speak_command


def test_speech_drops_markdown_and_code():
    raw = "Hello.\n```\nprint(1)\n```\n**Use** the `Low` setting."
    spoken = for_speech(raw)
    assert "print" not in spoken
    assert "`" not in spoken
    assert "*" not in spoken
    assert "Hello." in spoken
    assert "Use the Low setting." in spoken


def test_first_sentence_is_short():
    assert first_sentence("Berlin is the capital. The rest stays on screen.") == "Berlin is the capital."


def test_speed_slider_maps_onto_the_windows_rate():
    assert sapi_rate(100) == 0
    assert sapi_rate(80) == -4
    assert sapi_rate(130) == 6


def test_keyword_splits_the_question_off_the_wake_words():
    assert command_after_keyword("hey babysitter what time is it", "hey babysitter") == "what time is it"
    assert command_after_keyword("hey baby sitter what time is it", "hey babysitter") == "what time is it"
    assert command_after_keyword("what time is it", "hey babysitter") is None
    assert command_after_keyword("hey babysitter", "hey babysitter") == ""


def test_spoken_words_are_not_placed_on_the_command():
    command = " ".join(speak_command())
    assert "powershell" in command
    assert "Fresh start" not in command
    assert "hello" not in command
