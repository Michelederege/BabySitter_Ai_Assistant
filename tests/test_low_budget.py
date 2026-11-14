"""The Ryzen 9 7900X and RTX 4070, simulated. No graphics card is required."""

import array
import threading
from datetime import date

from babysitter.commands import match_quick_command
from babysitter.embedder import rank_texts
from babysitter.personality import clause_from_counts, record
from babysitter.pictures import fit_screenshot, room_for_model
from babysitter.plugins.voice.fillers import FillerLibrary, PHRASES
from babysitter.plugins.voice.playback import play_pcm_blocks
from babysitter.plugins.voice.turntaking import (
    barge_in,
    finished_by_silence,
    is_speech,
    open_vad,
    prepare_chunk,
    residual_pcm,
)
from babysitter.proactivity import nudge, offer_weekly, weekly_review
from babysitter.settings import Settings
from babysitter.status import StatusCollector, gpu_from_pairs, probes_paused
from babysitter.turngate import TurnGate, run_if_idle
from babysitter.vram import (
    DESKTOP_RESERVE_MIB,
    LOW_CEILING_MIB,
    LOW_FLOOR_MIB,
    RTX_4070_TOTAL_MIB,
    kv_mib,
    low_estimate_mib,
    low_load_note,
    need_mib,
)


def _pcm(value: int, count: int = 800) -> bytes:
    return array.array("h", [value] * count).tobytes()


def test_low_lands_in_four_to_six_gigabytes_on_a_4070():
    # 12 GB card, 24-thread Ryzen, 32 GB of RAM. The scarce piece is video memory.
    assert RTX_4070_TOTAL_MIB == 12282
    assert Settings().keep_off_game_cores is False
    estimate = low_estimate_mib()
    assert LOW_FLOOR_MIB <= estimate <= LOW_CEILING_MIB
    assert need_mib("qwen3.5:9b", 4096) == estimate
    assert kv_mib(16384, "q8_0") > kv_mib(4096, "q4_0") * 3

    free = RTX_4070_TOTAL_MIB - DESKTOP_RESERVE_MIB
    assert room_for_model(free, "qwen3.5:9b", 4096) is None
    used = DESKTOP_RESERVE_MIB + estimate
    assert used < RTX_4070_TOTAL_MIB
    # A game holding about 8 GB leaves Low no room, and Medium no room either.
    assert room_for_model(RTX_4070_TOTAL_MIB - 8192, "qwen3.5:9b", 4096)
    assert room_for_model(RTX_4070_TOTAL_MIB - 8192, "gemma4:12b", 8192)
    # Medium still fits beside the desktop. High still asks for more, and the guard can refuse it.
    assert room_for_model(free, "gemma4:12b", 8192) is None
    assert need_mib("gemma4:12b", 16384) == 11000


def test_nvml_reading_is_used_and_a_voice_turn_skips_the_next_probe():
    gpu, error = gpu_from_pairs([(4812, 12282)])
    assert error is None
    assert gpu is not None
    assert gpu.total_mib == 12282
    assert probes_paused(False, True)
    assert not probes_paused(False, False)

    class QuietOllama:
        def port_open(self):
            return False

    collector = StatusCollector(QuietOllama())
    calls = {"n": 0}

    def reader():
        calls["n"] += 1
        return [(3200, 12282)]

    collector.nvml_reader = reader
    first = collector.snapshot()
    assert calls["n"] == 1
    assert first.gpu is not None and first.gpu.used_mib == 3200
    collector.defer_probes = True
    second = collector.snapshot()
    assert calls["n"] == 1
    assert second.gpu is not None and second.gpu.used_mib == 3200


def test_a_heavy_low_load_is_reported_and_a_fitting_one_is_named():
    over = low_load_note("qwen3.5:9b", 7 * 1024 * 1024 * 1024, 4096)
    assert over is not None and "above the 6 GB goal" in over
    inside = low_load_note("qwen3.5:9b", 5 * 1024 * 1024 * 1024, 4096)
    assert inside is not None and "4 to 6 GB" in inside
    assert low_load_note("qwen3.5:9b", 1000, 4096) is None
    assert low_load_note("gemma4:12b", 9 * 1024 * 1024 * 1024, 8192) is None


def test_background_work_waits_and_a_stop_lands_inside_a_block():
    gate = TurnGate()
    ran: list[int] = []
    assert run_if_idle(gate, lambda: ran.append(1))
    gate.enter()
    assert run_if_idle(gate, lambda: ran.append(2)) is False
    gate.leave()
    assert ran == [1]

    stop = threading.Event()
    seen: list[int] = []

    def write(chunk) -> None:
        seen.append(len(chunk))
        stop.set()

    assert play_pcm_blocks([0.0] * 1000, 16000, stop, write, block_ms=10) is False
    assert len(seen) == 1


def test_fillers_are_prepared_only_while_idle():
    folder_holder = {}

    def render(text: str):
        assert text in PHRASES
        return (_pcm(1000, 16), 16000)

    library = FillerLibrary(folder=None)

    class Folder(FillerLibrary):
        def __init__(self, path):
            super().__init__(path)

    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        library = Folder(Path(raw))
        assert library.prepare(render, lambda: True) == "skipped"
        assert library.prepare(render, lambda: False) == "ready"
        assert library.ready()
        assert library.prepare(render, lambda: False) == "cached"
        assert library.clip(0) is not None
        folder_holder["ok"] = True
    assert folder_holder["ok"]


def test_echo_smart_turn_and_silero_stay_optional():
    mic = _pcm(4000)
    same = residual_pcm(mic, mic)
    assert not is_speech(same)
    heard, applied = prepare_chunk(mic, True, mic)
    assert applied and not is_speech(heard)
    untouched, applied = prepare_chunk(mic, False, mic)
    assert untouched == mic and applied is False
    tripped, hot = barge_in(2000, True, True, 2)
    assert tripped and hot == 3
    assert barge_in(2000, False, True, 2) == (False, 0)
    assert finished_by_silence(1, 3, False, False) is False
    assert finished_by_silence(4, 2, True, False) is True
    assert open_vad(False) is None
    assert open_vad(True, None).id == "energy"


def test_facts_ratings_and_the_weekly_review_stay_on_this_pc(tmp_path, monkeypatch):
    monkeypatch.setenv("BABYSITTER_DATA_DIR", str(tmp_path))
    assert rank_texts("the cat sat", ["dogs play", "the cat sat on the mat"], k=1) == ["the cat sat on the mat"]
    assert clause_from_counts({"shorter": 0, "longer": 0, "warmer": 0, "cooler": 0, "just right": 0}) == ""
    record("shorter")
    record("shorter")
    assert "shorter" in clause_from_counts({"shorter": 2, "longer": 0, "warmer": 0, "cooler": 0, "just right": 0})
    assert offer_weekly(3, "", date(2026, 11, 14), False)
    assert offer_weekly(3, "2026-11-14", date(2026, 11, 14), False) is False
    assert offer_weekly(1, "", date(2026, 11, 14), False) is False
    text = weekly_review(["The cat is called Moth"], ["what time is it"])
    assert "No model" in text
    assert "Moth" in text
    line = nudge(2, True, "The cat is called Moth", False)
    assert "Say yes" in line and "Moth" in line
    assert match_quick_command("weekly review").kind == "weekly"


def test_a_screenshot_on_low_stays_inside_the_short_context():
    width, height = fit_screenshot(2560, 1440, edge=896, num_ctx=4096)
    assert max(width, height) <= 896
    sharp, tall = fit_screenshot(2560, 1440, edge=1280, num_ctx=4096)
    assert max(sharp, tall) <= 1280
