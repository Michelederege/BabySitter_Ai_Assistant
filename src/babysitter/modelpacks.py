"""Model packs for the extra voices and hearing engines.

A pack is everything one engine needs: one archive, or a list of files,
each pinned to a SHA-256. Nothing is downloaded until you confirm on the
Voice tab. After a download, every file's hash is written beside it, and
the pack is checked against those hashes before every load (by size and
change time, then by hash if either changed), the same as Kokoro.

Archives are unpacked only after their hash matches, and an entry that
would land outside the pack folder, or is a link, is refused.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from babysitter.paths import data_dir, write_text_safely

SHERPA_ASR = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
SHERPA_TTS = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
SUPERTONIC = "https://huggingface.co/Supertone/supertonic-3/resolve/724fb5abbf5502583fb520898d45929e62f02c0b/"
# Chatterbox, the voice-copying engine (MIT licence), pinned to one revision.
CHATTERBOX = "https://huggingface.co/ResembleAI/chatterbox/resolve/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18/"


@dataclass(frozen=True)
class Pack:
    id: str
    label: str
    kind: str  # "hearing" or "voice"
    size_mb: int
    archive: tuple[str, str] | None = None  # (url, sha256) of a .tar.bz2
    files: tuple[tuple[str, str], ...] = ()  # (path under base, sha256)
    note: str = ""
    base: str = SUPERTONIC


PACKS: dict[str, Pack] = {
    "moonshine": Pack(
        "moonshine", "Moonshine (fast hearing)", "hearing", 111,
        archive=(SHERPA_ASR + "sherpa-onnx-moonshine-base-en-quantized-2026-02-27.tar.bz2",
                 "43232c1d13013d37317163baec3135bd771a186a4356f28c889bab453bb0e891"),
        note="Hears a question in a fraction of Whisper's time, on the processor.",
    ),
    "parakeet": Pack(
        "parakeet", "Parakeet (accurate hearing)", "hearing", 482,
        archive=(SHERPA_ASR + "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
                 "6fc4426b54aa549a0019b8a75b8dea59164e71790a37ac56a045ad57f915f714"),
        note="NVIDIA's English model. More accurate than Moonshine and a little slower, on the processor.",
    ),
    "piper-hfc": Pack(
        "piper-hfc", "Piper: HFC female (American)", "voice", 67,
        archive=(SHERPA_TTS + "vits-piper-en_US-hfc_female-medium.tar.bz2",
                 "3fffdceb0c65bd9415a085d09c3cb88cc82f9d74a6ca453f8ce7fc5eaee81ff8"),
    ),
    "piper-jenny": Pack(
        "piper-jenny", "Piper: Jenny (British)", "voice", 67,
        archive=(SHERPA_TTS + "vits-piper-en_GB-jenny_dioco-medium.tar.bz2",
                 "a0888024569bafbefc05a4b48ddf8419d8dbbf3205f4af37cf7c6f1a87cc20c5"),
    ),
    "chatterbox": Pack(
        "chatterbox", "Natural voices (Chatterbox)", "voice", 3200,
        files=(
            ("ve.safetensors", "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c"),
            ("t3_cfg.safetensors", "914cb1696f47527fe8852ca8f1fe1fa63cb34f76f9c715e84e067b744dd0da81"),
            ("s3gen.safetensors", "2b78103c654207393955e4900aac14a12de8ef25f4b09424f1ef91941f161d4e"),
            ("tokenizer.json", "d71e3a44eabb1784df9a68e9f95b251ecbf1a7af6a9f50835856b2ca9d8c14a5"),
            ("conds.pt", "6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e"),
        ),
        note="Copies a narrator's voice from a short clip. It runs on the graphics card while the AI is on Low.",
        base=CHATTERBOX,
    ),
    "supertonic": Pack(
        "supertonic", "Supertonic", "voice", 401,
        files=(
            ("onnx/duration_predictor.onnx", "c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db"),
            ("onnx/text_encoder.onnx", "c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff"),
            ("onnx/vector_estimator.onnx", "883ac868ea0275ef0e991524dc64f16b3c0376efd7c320af6b53f5b780d7c61c"),
            ("onnx/vocoder.onnx", "085de76dd8e8d5836d6ca66826601f615939218f90e519f70ee8a36ed2a4c4ba"),
            ("onnx/tts.json", "42078d3aef1cd43ab43021f3c54f47d2d75ceb4e75f627f118890128b06a0d09"),
            ("onnx/unicode_indexer.json", "9bf7346e43883a81f8645c81224f786d43c5b57f3641f6e7671a7d6c493cb24f"),
            ("voice_styles/F1.json", "bbdec6ee00231c2c742ad05483df5334cab3b52fda3ba38e6a07059c4563dbc2"),
            ("voice_styles/F2.json", "7c722c6a72707b1a77f035d67f0d1351ba187738e06f7683e8c72b1df3477fc6"),
            ("voice_styles/F3.json", "12f6ef2573baa2defa1128069cb59f203e3ab67c92af77b42df8a0e3a2f7c6ab"),
            ("voice_styles/F4.json", "c2fa764c1225a76dfc3e2c73e8aa4f70d9ee48793860eb34c295fff01c2e032b"),
            ("voice_styles/F5.json", "45966e73316415626cf41a7d1c6f3b4c70dbc1ba2bee5c1978ef0ce33244fc8d"),
            ("voice_styles/M1.json", "e35604687f5d23694b8e91593a93eec0e4eca6c0b02bb8ed69139ab2ea6b0a5b"),
            ("voice_styles/M2.json", "b76cbf62bac707c710cf0ae5aba5e31eea1a6339a9734bfae33ab98499534a50"),
            ("voice_styles/M3.json", "ea1ac35ccb91b0d7ecad533a2fbd0eec10c91513d8951e3b25fbba99954e159b"),
            ("voice_styles/M4.json", "ca8eefad4fcd989c9379032ff3e50738adc547eeb5e221b82593a6d7b3bac303"),
            ("voice_styles/M5.json", "dd22b92740314321f8ae11c5e87f8dd60d060f15dd3a632b5adf77f471f77af2"),
        ),
    ),
}

# Every Piper voice pack, from the voice catalog, each pinned to its SHA-256.
def _add_piper_packs() -> None:
    from babysitter.voice_catalog import piper_packs

    for pack_id, label, url, sha in piper_packs():
        if pack_id not in PACKS:
            PACKS[pack_id] = Pack(pack_id, label, "voice", 80 if "voices)" in label else 67, archive=(url, sha))


_add_piper_packs()

MANIFEST = "pack-manifest.json"


class PackError(Exception):
    """A model pack could not be downloaded or did not match."""


def pack_dir(pack_id: str) -> Path:
    return data_dir() / "models" / "packs" / pack_id


def ready(pack_id: str) -> bool:
    return (pack_dir(pack_id) / MANIFEST).is_file()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fetch(url: str, expected: str, dest: Path, opener=urllib.request.urlopen) -> None:
    if not url.startswith(("https://github.com/k2-fsa/sherpa-onnx/releases/download/", SUPERTONIC, CHATTERBOX)):
        raise PackError("That model address is not allowed.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with opener(url, timeout=180) as response, part.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                handle.write(chunk)
    except PackError:
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise PackError("The download did not finish. Nothing was kept.") from exc
    if _sha256(part) != expected:
        part.unlink(missing_ok=True)
        raise PackError("That download did not match the file this release expects. Nothing was kept.")
    part.replace(dest)


def _safe_extract(archive: Path, folder: Path) -> None:
    root = folder.resolve()
    with tarfile.open(archive, "r:bz2") as bundle:
        members = bundle.getmembers()
        for member in members:
            target = (root / member.name).resolve()
            if member.issym() or member.islnk() or not str(target).startswith(str(root)):
                raise PackError("The model download contained an unsafe path. Nothing was kept.")
        # Python's own "data" filter is a second guard: no links, devices, or odd permissions.
        bundle.extractall(root, members=members, filter="data")


def _write_manifest(folder: Path) -> None:
    entries = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name not in {MANIFEST, MANIFEST + ".tmp"}:
            stat = path.stat()
            entries[path.relative_to(folder).as_posix()] = [_sha256(path), stat.st_size, stat.st_mtime_ns]
    # Whole or not at all: a torn list made a 3.2 GB pack look "not downloaded".
    write_text_safely(folder / MANIFEST, json.dumps(entries, indent=1))


def download(pack_id: str, opener=urllib.request.urlopen) -> str:
    """Download one pack. The caller must have asked first."""
    pack = PACKS[pack_id]
    folder = pack_dir(pack_id)
    staging = folder.with_name(pack_id + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        if pack.archive:
            url, expected = pack.archive
            archive = staging / "download.tar.bz2"
            _fetch(url, expected, archive, opener)
            _safe_extract(archive, staging)
            archive.unlink()
        for rel, expected in pack.files:
            _fetch(pack.base + rel, expected, staging / rel, opener)
        _write_manifest(staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(folder, ignore_errors=True)
    staging.replace(folder)
    return f"{pack.label} is on this PC."


def verify(pack_id: str) -> Path:
    """The pack folder, after checking every file against its hash. Raises PackError."""
    folder = pack_dir(pack_id)
    manifest = folder / MANIFEST
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PackError(f"{PACKS[pack_id].label} is not downloaded yet.") from exc
    changed = False
    for rel, (sha, size, mtime) in entries.items():
        path = folder / rel
        try:
            stat = path.stat()
        except OSError:
            raise PackError(f"A {PACKS[pack_id].label} file is missing. Download it again.") from None
        if [stat.st_size, stat.st_mtime_ns] == [size, mtime]:
            continue
        if _sha256(path) != sha:
            raise PackError(f"A {PACKS[pack_id].label} file was changed, so it was not loaded. Download it again.")
        entries[rel] = [sha, stat.st_size, stat.st_mtime_ns]
        changed = True
    if changed:
        write_text_safely(manifest, json.dumps(entries, indent=1))
    return folder


def find(folder: Path, pattern: str) -> Path:
    """The one file in a pack matching a pattern, wherever the archive put it."""
    found = sorted(folder.rglob(pattern))
    if not found:
        raise PackError(f"The model pack is missing {pattern}. Download it again.")
    return found[0]
