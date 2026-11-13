import pytest

from babysitter.intelligence import MAIN_MODEL, MODES, WRITING_MODEL
from babysitter.ollama import (
    OllamaClient,
    classify_ollama_process,
    gpu_placement_label,
    models_from_ps,
    parse_ollama_version,
    version_is_older,
)
from babysitter.security import bind_is_private, bind_is_public, require_local_host
from babysitter.startupcheck import version_message
from babysitter.status import parse_compute_apps_csv, parse_gpu_memory_csv


def test_only_this_computer():
    require_local_host("127.0.0.1")
    with pytest.raises(ValueError):
        OllamaClient(host="10.0.0.8")
    with pytest.raises(ValueError):
        require_local_host("0.0.0.0")


def test_public_bind_is_not_private():
    assert bind_is_private(["127.0.0.1"])
    assert bind_is_public(["0.0.0.0"])
    assert not bind_is_private(["0.0.0.0"])


def test_version_parsing_and_the_security_cutoff():
    assert parse_ollama_version("ollama version is 0.17.1\n") == (0, 17, 1)
    assert parse_ollama_version("ollama version is 0.17.0") == (0, 17, 0)
    assert version_is_older((0, 17, 0), (0, 17, 1))
    assert not version_is_older((0, 17, 1), (0, 17, 1))
    assert not version_is_older((0, 18, 0), (0, 17, 1))
    _found, older, message = version_message((0, 6, 2), "", None)
    assert older
    assert "CVE-2026-7482" in message
    found, older, message = version_message(None, "", "Ollama is not installed, or it is not on the PATH.")
    assert not found
    assert not older
    assert "not installed" in message


def test_process_names():
    assert classify_ollama_process("ollama.exe") == "server"
    assert classify_ollama_process("Ollama") == "server"
    assert classify_ollama_process("ollama app.exe") == "tray"
    assert classify_ollama_process("chrome.exe") is None


def test_model_is_fully_on_the_gpu_only_when_vram_matches():
    assert gpu_placement_label(1000, 1000) == "100% on the GPU"
    assert gpu_placement_label(1000, 990) == "100% on the GPU"
    assert "system memory" in gpu_placement_label(1000, 0)
    assert "50% on the GPU" == gpu_placement_label(1000, 500)
    models = models_from_ps(
        {"models": [{"name": "qwen3.5:9b", "size": 1000, "size_vram": 1000}]}
    )
    assert models[0].gpu_label == "100% on the GPU"


def test_nvidia_csv():
    gpu, error = parse_gpu_memory_csv("4812, 12282\n")
    assert error is None
    assert gpu is not None
    assert gpu.used_mib == 4812
    assert gpu.total_mib == 12282
    assert parse_compute_apps_csv("123, C:\\Program Files\\Ollama\\ollama.exe, 6100\n") == 6100
    assert parse_compute_apps_csv("55, chrome.exe, 200\n") == 0
    empty, problem = parse_gpu_memory_csv("")
    assert empty is None
    assert problem


def test_intelligence_keeps_one_model():
    assert {mode.model for mode in MODES.values()} == {MAIN_MODEL}
    assert MODES["low"].num_ctx < MODES["medium"].num_ctx < MODES["high"].num_ctx
    assert WRITING_MODEL != MAIN_MODEL
