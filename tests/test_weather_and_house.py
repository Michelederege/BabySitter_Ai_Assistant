"""NEXT_ROUND phase 6: weather after a yes, and the house on this network only."""

import contextlib
import json

import pytest

from babysitter.home import HomeCommand, HomeError, best_match, clean_base_url, parse_house, plan, run
from babysitter.intents import match_tool, weather_intent
from babysitter.weather import WeatherError, check, forecast_url, geocode_url, require_weather_url, weather_speech


def test_weather_words_become_a_question_that_waits_for_yes():
    intent = match_tool("what's the weather in Milan tomorrow")
    assert intent.kind == "weather" and intent.query == "milan" and intent.action_id == "tomorrow"
    assert "Open-Meteo" in intent.ask
    assert weather_intent("what's the weather").query == ""  # the saved town is used
    assert weather_intent("will it rain tomorrow").action_id == "tomorrow"
    assert weather_intent("my town is Leeds").kind == "set_town"
    assert weather_intent("weather is nice") is None


def test_only_open_meteo_and_only_a_rounded_position():
    require_weather_url(geocode_url("Leeds"))
    url = forecast_url(53.80074, -1.54907)
    require_weather_url(url)
    assert "latitude=53.80" in url and "longitude=-1.55" in url
    with pytest.raises(WeatherError):
        require_weather_url("https://example.com/v1/forecast")


def test_the_forecast_is_spoken_from_the_numbers():
    payload = {
        "current": {"temperature_2m": 7.4, "weather_code": 61},
        "daily": {
            "temperature_2m_max": [9.2, 11.0],
            "temperature_2m_min": [3.6, 5.1],
            "precipitation_probability_max": [70, 5],
            "weather_code": [63, 2],
        },
    }
    assert weather_speech("Leeds", payload) == (
        "In Leeds it's 7°C and light rain right now. Today, 4 to 9°C, with a 70% chance of rain."
    )
    tomorrow = weather_speech("Leeds", payload, tomorrow=True)
    assert tomorrow == "In Leeds: Tomorrow, 5 to 11°C, partly cloudy, and rain is unlikely."


def test_check_reads_place_then_forecast():
    answers = [
        {"results": [{"name": "Leeds", "latitude": 53.8, "longitude": -1.55}]},
        {"current": {"temperature_2m": 10, "weather_code": 0}, "daily": {"temperature_2m_max": [12], "temperature_2m_min": [6]}},
    ]
    asked: list = []

    @contextlib.contextmanager
    def opener(request, timeout=0):
        asked.append(request.full_url)

        class Response:
            def read(self, _limit):
                return json.dumps(answers[len(asked) - 1]).encode()

        yield Response()

    speech = check("leeds", fahrenheit=False, opener=opener)
    assert speech.startswith("In Leeds it's 10°C and clear")
    assert asked[0].startswith("https://geocoding-api.open-meteo.com/") and asked[1].startswith("https://api.open-meteo.com/")


def test_home_assistant_must_be_on_this_network():
    assert clean_base_url("homeassistant.local:8123") == "http://homeassistant.local:8123"
    assert clean_base_url("192.168.1.20:8123/") == "http://192.168.1.20:8123"
    assert clean_base_url("https://10.0.0.5") == "https://10.0.0.5"
    for bad in ("8.8.8.8:8123", "https://example.com", "http://user:pw@192.168.1.2"):
        with pytest.raises(HomeError):
            clean_base_url(bad)


ENTITIES = [
    {"entity_id": "light.kitchen", "domain": "light", "name": "Kitchen Light", "state": "off"},
    {"entity_id": "light.desk_lamp", "domain": "light", "name": "Desk Lamp", "state": "on"},
    {"entity_id": "switch.fan_plug", "domain": "switch", "name": "Fan Plug", "state": "off"},
    {"entity_id": "media_player.speaker", "domain": "media_player", "name": "Living Room Speaker", "state": "playing"},
]


def test_spoken_switches_are_planned_never_run():
    assert parse_house("turn off the kitchen light") == ("turn_off", "kitchen light")
    assert parse_house("switch the desk lamp on") == ("turn_on", "desk lamp")
    assert parse_house("turn off the AI") is None  # BabySitter's own words are not the house
    assert parse_house("pause the music") == ("media_pause", "")
    command = plan("turn off the kitchen light", ENTITIES)
    assert command == HomeCommand("light", "turn_off", "light.kitchen", "Kitchen Light")
    assert command.ask == "Turn off Kitchen Light?"
    assert plan("next song", ENTITIES).entity_id == "media_player.speaker"
    assert plan("turn on the garage", ENTITIES) is None
    assert best_match("fan", ENTITIES)["entity_id"] == "switch.fan_plug"


def test_a_confirmed_command_posts_one_service_call():
    sent: list = []

    @contextlib.contextmanager
    def opener(request, timeout=0):
        sent.append((request.get_method(), request.full_url, request.data))

        class Response:
            status = 200

            def read(self, _limit):
                return b"[]"

        yield Response()

    speech = run(HomeCommand("light", "turn_off", "light.kitchen", "Kitchen Light"), "192.168.1.20:8123", "t" * 40, opener)
    assert speech == "Turned off Kitchen Light."
    assert sent == [("POST", "http://192.168.1.20:8123/api/services/light/turn_off", b'{"entity_id": "light.kitchen"}')]


def test_weather_and_the_house_wait_for_yes_in_the_window(tmp_path, monkeypatch):
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
        shell._offer_tool(weather_intent("what's the weather"))
        assert "Which town" in spoken[-1] and shell._pending_tool is None
        shell._offer_tool(weather_intent("my town is leeds"))
        assert controller.settings.weather_place == "Leeds"
        shell._offer_tool(weather_intent("what's the weather"))
        assert shell._pending_tool.kind == "weather" and "Leeds" in spoken[-1]
        ran: list = []
        monkeypatch.setattr(shell, "_run_weather", lambda intent: ran.append(intent.query))
        shell._answer_tool("no")
        assert ran == [] and "Nothing was sent" in spoken[-1]

        # No house is set up: a switch command is an ordinary question, not a call.
        assert shell._maybe_house("turn off the kitchen light") is False
    finally:
        shell.registrar.clear()
        controller.shutdown_threads()
        app.processEvents()
