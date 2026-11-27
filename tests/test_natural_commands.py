"""0.27.2: everyday wordings reach the same commands, and ordinary questions still reach the model."""

from datetime import datetime

from babysitter.commands import match_quick_command
from babysitter.pcscan import suggestion_answer
from babysitter.plugins.voice.speech import followup_phrase, more_answer


def _kind(text: str):
    found = match_quick_command(text)
    return None if found is None else found.kind


def test_polite_and_filler_words_around_a_request():
    for said in (
        "could you please tell me the time",
        "can you just tell me the time real quick",
        "um what time is it",
        "so what time is it right now",
        "hey there what's the time",
        "would you mind telling me the time",
        "I'd like you to check my email",
        "do me a favor and check my email",
        "go ahead and check my calendar for me",
        "could you check my email if you can",
        "alright, what's on my calendar?",
    ):
        assert _kind(said) in {"time", "mail", "calendar"}, said
    assert _kind("I need you to be quiet") == "hush"


def test_everyday_wordings_for_each_command():
    expected = {
        "do you have the time": "time",
        "what date is it": "time",
        "shut up": "hush",
        "shh": "hush",
        "hold on": "hush",
        "stop": "hush",
        "pardon": "repeat",
        "sorry what": "repeat",
        "what was that": "repeat",
        "i didn't catch that": "repeat",
        "huh": "repeat",
        "any reminders": "next_reminder",
        "when's the timer done": "next_reminder",
        "forget the reminder": "cancel_reminder",
        "never mind the timer": "cancel_timer",
        "turn off the timer": "cancel_timer",
        "scratch that": "undo",
        "take that back": "undo",
        "do i have any new emails": "mail",
        "anything in my inbox": "mail",
        "any appointments today": "calendar",
        "what's happening today": "calendar",
        "is my computer okay": "health",
        "what can you see": "screen",
        "where were we": "history",
        "save that": "pin",
        "what have you learned about me": "memories",
        "tell me what you remember": "memories",
    }
    for said, kind in expected.items():
        assert _kind(said) == kind, (said, _kind(said))


def test_thanks_goodbye_and_a_fresh_start_need_no_model():
    for said in ("thanks", "thank you so much", "cheers", "much appreciated", "thanks, that was helpful", "great job"):
        assert _kind(said) in {"thanks", None}, said
    assert _kind("thank you so much") == "thanks"
    assert _kind("great job") == "thanks"
    assert _kind("bye") == "bye"
    assert match_quick_command("good night").detail == "night"
    assert match_quick_command("talk to you later").detail == ""
    assert _kind("that's all for now") == "bye"
    for said in ("new topic", "let's start over", "change the subject", "new conversation"):
        assert _kind(said) == "fresh_start", said


def test_reminders_notes_and_names_said_naturally():
    found = match_quick_command("wake me up at 7 am")
    assert found.kind == "remind" and found.when
    found = match_quick_command("ping me in 5 mins to check the oven")
    assert found.kind == "remind" and "check the oven" in found.detail
    when = datetime.fromisoformat(found.when)
    assert 4 * 60 <= (when - datetime.now().astimezone()).total_seconds() <= 5 * 60 + 5
    assert match_quick_command("set a timer for 10 mins").seconds == 600
    assert match_quick_command("set a timer for a couple of minutes").seconds == 120
    assert match_quick_command("remember that my sister is called Anna").detail == "my sister is called Anna"
    assert match_quick_command("keep in mind that I'm allergic to nuts").detail == "I'm allergic to nuts"
    assert match_quick_command("note to self buy milk").detail == "buy milk"
    assert match_quick_command("my name is alex").detail == "My name is Alex"
    assert _kind("my name is not important") is None  # not a name
    assert match_quick_command("remind me to call Min").detail == "to call Min"  # a name, not "minutes"


def test_ordinary_questions_still_go_to_the_model():
    for said in (
        "what time does the store close",
        "what's the date of the next full moon",
        "how do I stop my dog barking",
        "can you explain how timers work in javascript",
        "what was that movie with the shark",
        "thanks to whom was the war won",
        "say goodbye to my friend in french",
        "what is this word in spanish",
        "tell me about the history of rome",
        "is the moon bigger than pluto",
        "could you write me a poem about the sea",
        "why do people say goodnight",
        "how many minutes are in a day",
        "what happens if I stop eating sugar",
    ):
        assert _kind(said) is None, (said, _kind(said))


def test_yes_and_no_are_natural_and_long_sentences_are_new_questions():
    for said in ("sure thing", "go for it", "yes please", "absolutely", "sounds good", "why not", "yea"):
        assert more_answer(said) == "yes", said
    for said in ("not now", "maybe later", "i'm good", "nah", "don't bother", "forget it"):
        assert more_answer(said) == "no", said
    # A new question that only starts with a yes word is not a yes.
    assert more_answer("yeah but what about the weather tomorrow") is None
    assert more_answer("please set a timer for five minutes") is None
    assert more_answer("no wait what about the second one then") is None
    assert suggestion_answer("go for it") == "yes"
    assert suggestion_answer("not now") == "no"
    assert suggestion_answer("no I think it is fine because I use it every day") is None
    assert followup_phrase("nothing else") == ""
    assert followup_phrase("i'm good") == ""
    assert followup_phrase("no") is None  # a bare no still answers a scan suggestion


def test_false_matches_from_the_sweep_stay_questions():
    for said in (
        "can you remind me what photosynthesis is",
        "remember when we talked about dogs",
        "note that down is a funny phrase",
        "wake me up inside lyrics",
        "ping me the details",
    ):
        assert _kind(said) is None, (said, _kind(said))
    assert match_quick_command("remind me when I get home to call mom").kind == "remind"


def test_wake_me_up_means_the_morning():
    found = match_quick_command("wake me up at 7")
    assert found.detail == "Wake up"
    assert datetime.fromisoformat(found.when).hour == 7
    assert datetime.fromisoformat(match_quick_command("wake me up at 7 pm").when).hour == 19


def test_thanks_goodbye_and_new_topic_are_answered_here(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    from babysitter.controller import Controller
    from babysitter.ui.shell import Shell

    controller = Controller()
    shell = Shell(controller)
    try:
        spoken: list = []
        monkeypatch.setattr(shell, "_speak", lambda text, **kw: spoken.append(text))
        turned_on: list = []
        monkeypatch.setattr(controller, "turn_on", lambda *a, **k: turned_on.append(1))
        for said in ("thank you so much", "good night", "new topic"):
            shell._pending_line = said
            shell._send_heard()
        assert spoken[0] in {"You're welcome.", "Anytime.", "Happy to help.", "Of course.", "No problem.", "Glad I could help."}
        assert spoken[1] in {"Good night.", "Sleep well.", "Night. Talk tomorrow."}
        assert "start" in spoken[2].lower() or "slate" in spoken[2].lower() or "topic" in spoken[2].lower()
        assert turned_on == []  # the model was never loaded for any of them
        assert shell._history == [] and shell._session_id == ""
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
