"""A voice that sounds like a person: what the model is told, and what is trimmed."""

from babysitter.ollama import chat_messages, clock_matters, sampling_for, system_prompt
from babysitter.plugins.voice.speech import speakable, trim_closing_offer


def test_the_clock_goes_only_with_questions_about_time():
    assert clock_matters("what time is it")
    assert clock_matters("remind me tomorrow at 6")
    assert clock_matters("how long until friday")
    assert not clock_matters("what's a good name for a cat")
    assert not clock_matters("how does a fridge work")
    line = chat_messages("how does a fridge work")[-1]["content"]
    assert line == "how does a fridge work"
    timed = chat_messages("what day is it")[-1]["content"]
    assert timed.startswith("what day is it") and "Clock on this PC" in timed


def test_the_instructions_are_for_the_ear():
    prompt = system_prompt(name="Kari")
    assert "spoken aloud by a voice" in prompt
    assert "Write numbers as digits" in prompt  # spelled-out numbers came back wrong
    assert "Most replies end without a question" in prompt
    assert "octopus" not in prompt.lower()  # an example it once copied word for word


def test_each_model_gets_its_own_sampling():
    assert sampling_for("qwen3.5:9b")["top_k"] == 20
    assert sampling_for("gemma4:12b") == {"temperature": 1.0, "top_p": 0.95, "top_k": 64}


def test_closing_offers_are_trimmed_real_questions_kept():
    assert trim_closing_offer("Jane Austen wrote it. Want to hear about her other books?") == "Jane Austen wrote it."
    assert trim_closing_offer("It's 12. Would you like another practice problem?") == "It's 12."
    assert trim_closing_offer("Fifteen percent of 80 is 12. Shall we try another, or take a break?") == "Fifteen percent of 80 is 12."
    kept = "Which town do you mean, Paris in France or Paris in Texas?"
    assert trim_closing_offer(kept) == kept
    assert trim_closing_offer("Want some?") == "Want some?"  # nothing before it: left alone
    assert trim_closing_offer("Mochi is cute. Does your cat have any markings?") == "Mochi is cute. Does your cat have any markings?"


def test_symbols_are_said_as_words():
    assert speakable("It boils at 212°F.") == "It boils at 212 degrees."
    assert "percent" in speakable("about 70% likely")


def test_units_and_symbols_are_said_the_way_people_say_them():
    assert speakable("It is 384,000 km away.") == "It is 384,000 kilometres away."
    assert speakable("Open 24/7.") == "Open around the clock."
    assert speakable("2 + 2 = 4") == "2 plus 2 equals 4"
    assert speakable("Well... maybe.") == "Well, maybe."
    assert speakable("Takes 15 mins.") == "Takes 15 minutes."


def test_the_natural_voice_has_more_feeling_on_an_exclamation():
    from babysitter.plugins.voice.clone_voice import liveliness

    assert liveliness("That's brilliant!") > liveliness("It is twelve.") > liveliness(" ".join(["word"] * 30) + ".")
    assert 0.3 <= liveliness("Really?") <= 0.8


def test_everyday_wordings_reach_the_same_commands():
    from babysitter.commands import match_quick_command
    from babysitter.intents import match_tool

    expected = {
        "do you know what time it is": "time",
        "time please": "time",
        "whats the date today": "time",
        "start a 3 minute timer": "timer",
        "put a timer on for 15 minutes": "timer",
        "stop the timer": "undo",
        "how much time is left": "next_reminder",
        "what do you remember about me": "memories",
        "read my emails": "mail",
        "whats my schedule": "calendar",
    }
    for said, kind in expected.items():
        assert match_quick_command(said).kind == kind, said
    assert match_quick_command("set a 20 second timer").seconds == 20
    assert match_quick_command("set a 5 minute timer for the pasta").detail == "the pasta"
    for said in ("whats the weather", "do i need an umbrella", "how cold is it outside"):
        assert match_tool(said).kind == "weather", said
    assert match_tool("I'm in trouble") is None  # not a town
