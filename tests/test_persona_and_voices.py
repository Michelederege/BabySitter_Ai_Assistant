"""Personas, voice blends, and filler clips per voice."""

from babysitter.commands import match_quick_command


def test_persona_phrases_and_requests_that_are_not_names():
    assert match_quick_command("be edith").kind == "persona"
    assert match_quick_command("be edith").detail == "edith"
    assert match_quick_command("call yourself brook").detail == "brook"
    assert match_quick_command("be yourself").detail == ""
    for request in ("be quiet", "be honest", "be more concise", "be right back"):
        found = match_quick_command(request)
        assert found is None or found.kind != "persona", request


def test_a_persona_is_saved_survives_and_gives_no_powers(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter import personality

    assert personality.persona_clause() == ""
    assert personality.save_persona("edith") == "EDITH"
    clause = personality.session_clause()
    assert clause.startswith("Your name is EDITH.")
    assert "cannot send mail" in clause and "invent a source" in clause
    assert personality.save_persona("brook") == "Brook"
    assert "Your name is Brook." in personality.persona_clause()
    personality.clear_persona()
    assert personality.persona_clause() == ""


def test_the_edith_style_blend_is_a_mix_of_stock_voices():
    from babysitter.plugins.voice import kokoro_voice

    first, second, a, b = kokoro_voice.BLENDS["EDITH-style blend"]
    assert (first, second) == ("af_nova", "af_kore") and abs(a + b - 1.0) < 1e-9
    assert kokoro_voice.BLEND == kokoro_voice.BLENDS["Heart & Sarah blend"]


def test_each_voice_keeps_its_own_filler_clips(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    from babysitter.plugins.voice.fillers import filler_dir, library

    assert library("Heart & Sarah blend")._folder() == filler_dir()
    edith = library("EDITH-style blend")._folder()
    assert edith != filler_dir() and edith.parent == filler_dir()
    rendered: list[str] = []

    def render(text):
        rendered.append(text)
        return b"\x00\x01" * 200, 24000

    assert library("EDITH-style blend").prepare(render, lambda: False) == "ready"
    assert library("EDITH-style blend").clip(0) is not None
    assert library("Heart & Sarah blend").clip(0) is None
