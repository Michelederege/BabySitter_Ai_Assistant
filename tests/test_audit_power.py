"""Audit 2 (power, the model, game mode), 0.28.1."""

from __future__ import annotations

import logging

from babysitter.gamebudget import GameBudget
from babysitter.intelligence import MODES
from babysitter.ollama import LoadedModel, OllamaClient
from babysitter.status import GpuInfo, with_ollama_share

GIB = 1024 ** 3


def _model(vram_gib: float) -> LoadedModel:
    return LoadedModel(name="gemma4:12b", size_bytes=int(vram_gib * GIB), vram_bytes=int(vram_gib * GIB))


def test_our_share_comes_from_ollama_when_the_driver_reading_has_none():
    gpu = GpuInfo(used_mib=11000, total_mib=12282, ollama_mib=0)
    filled = with_ollama_share(gpu, [_model(8.8)])
    assert filled.ollama_mib == int(8.8 * 1024)
    assert gpu.ollama_mib == 0, "the cached reading is not changed in place"
    assert with_ollama_share(gpu, []) is gpu
    assert with_ollama_share(None, [_model(8)]) is None
    already = GpuInfo(used_mib=11000, total_mib=12282, ollama_mib=9000)
    assert with_ollama_share(already, [_model(8)]).ollama_mib == 9000


def test_a_small_game_beside_medium_changes_nothing():
    """His PC: Medium loaded (about 8.8 GB), desktop about 0.8 GB, a game using 1.5 GB."""
    ours = int(8.8 * 1024)
    used = ours + 800 + 1500
    gpu = GpuInfo(used_mib=used, total_mib=12282, ollama_mib=0)
    filled = with_ollama_share(gpu, [_model(8.8)])
    budget = GameBudget()
    for _ in range(6):  # 12 seconds of readings
        action = budget.decide(
            game="SmallGame.exe",
            state="on",
            chosen="medium",
            loaded="medium",
            gpu=(filled.total_mib, filled.used_mib, filled.ollama_mib),
            ram_free=16 * GIB,
        )
        assert action.kind == "none", action
    # Before the fix the share was 0, so the same reading meant "no room" and game mode.
    stale = GameBudget()
    kinds = {
        stale.decide(game="SmallGame.exe", state="on", chosen="medium", loaded="medium",
                     gpu=(gpu.total_mib, gpu.used_mib, gpu.ollama_mib), ram_free=16 * GIB).kind
        for _ in range(6)
    }
    assert kinds & {"game", "lower"}


def test_a_big_game_still_makes_room():
    ours = int(8.8 * 1024)
    used = ours + 800 + 6000
    gpu = with_ollama_share(GpuInfo(used_mib=min(used, 12282), total_mib=12282, ollama_mib=0), [_model(8.8)])
    budget = GameBudget()
    kinds = [
        budget.decide(game="BigGame.exe", state="on", chosen="medium", loaded="medium",
                      gpu=(gpu.total_mib, gpu.used_mib, gpu.ollama_mib), ram_free=16 * GIB).kind
        for _ in range(4)
    ]
    # Medium no longer fits, so after the settling readings it switches down or unloads.
    assert kinds[:2] == ["none", "none"] and kinds[2] in {"lower", "game"}
    assert MODES["low"].vram_mib > 0


def test_the_status_poll_is_not_logged(monkeypatch, caplog):
    client = OllamaClient()
    opened = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"models": []}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: opened.append(request.full_url) or _Response())
    with caplog.at_level(logging.INFO, logger="babysitter"):
        logger = logging.getLogger("babysitter")
        logger.addHandler(caplog.handler)
        try:
            client.running_models()
            client._request("POST", "/api/generate", {"model": "qwen3.5:9b", "keep_alive": 0})
        finally:
            logger.removeHandler(caplog.handler)
    lines = [record.getMessage() for record in caplog.records]
    assert not any("/api/ps" in line for line in lines)
    assert any("POST /api/generate model=qwen3.5:9b" in line for line in lines)
    assert len(opened) == 2
