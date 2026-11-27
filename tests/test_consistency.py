"""Long run, scan D (0.29.0): what the app says matches what it does."""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_hearing_list_names_the_real_default():
    from babysitter.plugins.voice.engines import HEARING_ENGINES
    from babysitter.settings import Settings

    assert Settings().hearing_engine == "parakeet"
    assert "default" not in HEARING_ENGINES["whisper"].lower()


def test_settings_without_an_engine_get_the_default(tmp_path):
    from babysitter.settings import Settings, load_settings, save_settings

    path = tmp_path / "settings.json"
    save_settings(Settings(), path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("hearing_engine")
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_settings(path).hearing_engine == "parakeet"
    data["hearing_engine"] = "whisper"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_settings(path).hearing_engine == "whisper", "a chosen Whisper stays chosen"


def test_no_page_still_claims_there_is_no_voice_cloning():
    for path in [ROOT / "README.md", *sorted((ROOT / "src").rglob("*.py"))]:
        text = path.read_text(encoding="utf-8").lower()
        assert "no voice cloning in this project" not in text, path
        assert "voice cloning is not supported" not in text, path
        assert "will not be added" not in text or "clon" not in text, path


def test_the_readme_privacy_section_names_every_service():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for host in ("graph.microsoft.com", "api.open-meteo.com", "geocoding-api.open-meteo.com", "gmail.googleapis.com", "api.scrapecreators.com"):
        assert host in text, host


def test_a_town_is_looked_up_once_per_run(monkeypatch):
    from babysitter import weather

    monkeypatch.setattr(weather, "_found", {})
    asked = []

    class _Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(request, timeout):
        asked.append(request.full_url)
        return _Reply(json.dumps({"results": [{"name": "Leeds", "latitude": 53.8, "longitude": -1.55}]}).encode())

    assert weather.find_place("Leeds", opener) == ("Leeds", 53.8, -1.55)
    assert weather.find_place("leeds", opener) == ("Leeds", 53.8, -1.55)
    assert len(asked) == 1
