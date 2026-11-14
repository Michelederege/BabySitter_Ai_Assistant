from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import (
    closed_lead,
    first_sentence,
    for_speech,
    interrupt_note,
    is_resume,
    lead_and_rest,
    more_answer,
    remainder_after,
    sapi_rate,
    strip_thinking,
)
from babysitter.plugins.voice.windows_voice import speak_command


def test_thinking_is_not_spoken():
    assert "secret plan" not in strip_thinking("Hello. <think>secret plan</think> The sky is blue.")
    assert strip_thinking("Hello. <think>secret plan</think> The sky is blue.").startswith("Hello.")


def test_an_interruption_keeps_only_the_words_already_spoken():
    heard = "Dancing has no single inventor."
    assert "long explanation" not in heard
    assert interrupt_note(heard) == "you were interrupted after: Dancing has no single inventor."
    assert interrupt_note("") == "you were interrupted before you spoke."
    assert is_resume("carry on")
    assert is_resume("what were you saying")
    assert not is_resume("what time is it")


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


def test_the_first_sentence_can_be_spoken_before_the_rest_arrives():
    assert closed_lead("Dancing has no single inventor") is None
    assert closed_lead("Dancing has no single inventor. It grew later.") == "Dancing has no single inventor."
    early = closed_lead(
        "People in many different places started dancing on their own, long before history was written"
    )
    assert early == "People in many different places started dancing on their own."
    assert remainder_after(early, early[:-1] + ", long before history was written.") == (
        "long before history was written."
    )


def test_a_longer_answer_keeps_the_rest_for_later():
    lead, rest = lead_and_rest("Dancing has no single inventor. It grew over thousands of years.")
    assert lead == "Dancing has no single inventor."
    assert rest == "It grew over thousands of years."
    assert more_answer("yes") == "yes"
    assert more_answer("no thanks") == "no"
    assert more_answer("who invented dancing") is None


def test_speed_slider_maps_onto_the_windows_rate():
    assert sapi_rate(100) == 0
    assert sapi_rate(80) == -4
    assert sapi_rate(130) == 6


def test_keyword_splits_the_question_off_the_wake_words():
    assert command_after_keyword("baby sitter what time is it", "baby sitter") == "what time is it"
    assert command_after_keyword("babysitter what time is it", "baby sitter") == "what time is it"
    assert command_after_keyword("what time is it", "baby sitter") is None
    assert command_after_keyword("baby sitter", "baby sitter") == ""


def test_spoken_words_are_not_placed_on_the_command():
    command = " ".join(speak_command())
    assert "powershell" in command
    assert "Fresh start" not in command
    assert "hello" not in command
