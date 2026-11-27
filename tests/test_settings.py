import json

import pytest

from babysitter.settings import SCHEMA_VERSION, SettingsError, load_settings, save_settings


def test_fresh_settings_are_off_and_versioned(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.start_with_windows is False
    assert settings.intelligence == "medium"
    assert settings.emergency_hotkey == "Ctrl+Alt+F12"
    assert settings.power_on_hotkey == "Ctrl+Alt+F11"
    assert settings.auto_game_mode is True
    assert settings.detect_games is True
    assert settings.social_search_enabled is False
    assert (tmp_path / "settings.json").is_file()


def test_schema_ten_turns_game_detection_on_once(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 10, "auto_game_mode": False}),
        encoding="utf-8",
    )
    settings = load_settings()
    # The folder-based detection was asked to work by itself, so the one
    # migration turns both switches on. Settings can turn them back off.
    assert settings.auto_game_mode is True
    assert settings.detect_games is True
    save_settings(settings)
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "auto_game_mode": False, "detect_games": False}
        ),
        encoding="utf-8",
    )
    kept = load_settings()
    # A choice made on the current schema is kept.
    assert kept.auto_game_mode is False
    assert kept.detect_games is False


def test_version_zero_is_migrated(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 0, "intelligence": "high"}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.intelligence == "high"
    assert settings.start_with_windows is False
    assert settings.social_search_enabled is False
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["schema_version"] == SCHEMA_VERSION
    assert saved["emergency_hotkey"] == "Ctrl+Alt+F12"


def test_schema_one_turns_social_search_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 1, "intelligence": "low", "api_key": "should-not-stick"}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.intelligence == "low"
    assert settings.social_search_enabled is False
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "api_key" not in saved
    assert saved["social_search_enabled"] is False


def test_newer_settings_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 99}),
        encoding="utf-8",
    )
    with pytest.raises(SettingsError):
        load_settings()


def test_corrupt_file_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    settings = load_settings()
    assert settings.start_with_windows is False
    assert settings.notices
    assert (tmp_path / "settings.json.bak").is_file()


def test_bad_intelligence_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    save_settings_path = tmp_path / "settings.json"
    save_settings_path.write_text(
        json.dumps({"schema_version": 1, "intelligence": "ultra", "start_with_windows": True}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.intelligence == "medium"
    assert settings.start_with_windows is True
    assert settings.notices


def test_old_keyword_becomes_baby_sitter(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 4, "keyword": "hey babysitter"}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.keyword == "baby sitter"
    assert settings.keyword_listening is False


def test_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    settings = load_settings()
    settings.game_processes = ["game.exe"]
    settings.intelligence = "low"
    save_settings(settings)
    again = load_settings()
    assert again.game_processes == ["game.exe"]
    assert again.intelligence == "low"


def test_schema_seven_gains_the_listening_extras_off(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.json").write_text(
        json.dumps({"schema_version": 7, "intelligence": "low", "keep_off_game_cores": False}),
        encoding="utf-8",
    )
    settings = load_settings()
    assert settings.schema_version == SCHEMA_VERSION
    assert settings.vad_enabled is False
    assert settings.smart_turn is False
    assert settings.echo_cancel is False
    assert settings.talk_over is False
    assert settings.proactivity == 1
    assert settings.last_weekly_review == ""
    assert settings.keep_off_game_cores is False


def test_json_that_is_not_settings_is_replaced(tmp_path, monkeypatch):
    for text in ("null", "[]", "3", '"settings"'):
        path = tmp_path / "settings.json"
        path.write_text(text, encoding="utf-8")
        settings = load_settings(path)
        assert settings.intelligence == "medium"
        assert "could not be read" in settings.notices[0]
        assert (tmp_path / "settings.json.bak").read_text(encoding="utf-8") == text


def test_newer_settings_show_one_plain_sentence(tmp_path, monkeypatch):
    import babysitter.app as app
    import babysitter.startup_error as startup_error

    shown: list[str] = []
    monkeypatch.setattr(startup_error, "show_startup_failure", shown.append)

    def refuse(_args):
        raise SettingsError("These settings were saved by a newer BabySitter.")

    monkeypatch.setattr(app, "_run", refuse)
    assert app.main(["babysitter"]) == 1
    assert shown == ["These settings were saved by a newer BabySitter."]
