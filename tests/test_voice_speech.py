from babysitter.plugins.voice.keyword import command_after_keyword
from babysitter.plugins.voice.speech import (
    closed_lead,
    first_sentence,
    followup_phrase,
    for_speech,
    interrupt_note,
    is_resume,
    lead_and_rest,
    more_answer,
    remainder_after,
    sapi_rate,
    strip_thinking,
    voice_and_rest,
)
from babysitter.plugins.voice.windows_voice import speak_command


def test_a_reply_speaks_two_or_three_sentences():
    spoken, rest = voice_and_rest("One. Two. Three. Four is the extra part.")
    assert spoken == "One. Two. Three."
    assert rest == "Four is the extra part."
    assert followup_phrase("what about france") == "what about france"
    assert followup_phrase("yes") == "yes"
    assert followup_phrase("thanks that's all") == ""
    assert followup_phrase("hi") is None
    assert followup_phrase("why") == "why"


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
    assert first_sentence("Dr. Smith is here. He left.") == "Dr. Smith is here."


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


def test_a_reminder_speaks_without_the_ai():
    from babysitter.plugins.voice.speech import alert_voice

    kokoro = {"engine": "kokoro", "name": "blend", "speed": 105}
    fallen_back = alert_voice(kokoro, kokoro_ready=False, windows_ok=True)
    assert fallen_back is not None and fallen_back["engine"] == "windows"
    assert alert_voice(kokoro, kokoro_ready=True, windows_ok=False)["engine"] == "kokoro"
    assert alert_voice(kokoro, kokoro_ready=False, windows_ok=False) is None


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


def test_the_voice_hears_words_a_person_would_say():
    from babysitter.plugins.voice.speech import speakable

    said = speakable("Chrome uses 3.7 GB, about 12% of memory, e.g. tabs & videos. See https://x.y/z 🙂")
    assert "3.7 gigabytes" in said and "12 percent" in said
    assert "for example, tabs and videos" in said
    assert "the link on the screen" in said and "🙂" not in said
    assert speakable("It needs 8-10 GB, ~9 most days.") == "It needs 8 to 10 gigabytes, about 9 most days."
    assert speakable("Plain words stay the same.") == "Plain words stay the same."


def test_pauses_follow_the_punctuation():
    from babysitter.plugins.voice.speech import pause_ms

    assert pause_ms("Is it on?") > pause_ms("It is on.") > pause_ms("First,") > pause_ms("and then the")


def test_a_long_sentence_breaks_at_a_comma_not_mid_phrase():
    from babysitter.plugins.voice.speech import speech_chunks

    sentence = (
        "The scan found five heavy apps running right now on this computer, "
        "and the heaviest one by far is the DuckDuckGo browser with its many helper windows open."
    )
    pieces = speech_chunks(sentence, limit=90)
    assert pieces[0].endswith("computer,")
    assert " ".join(pieces) == sentence
