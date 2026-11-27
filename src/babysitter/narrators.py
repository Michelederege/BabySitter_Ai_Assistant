"""Real narrators whose recordings are free to use, for the natural voices.

Each narrator is one short clip of them reading, pinned to a SHA-256. The
voice-copying engine (Chatterbox) speaks in that narrator's voice from the
clip. Clips are fetched only after a yes and checked before each use.

- Linda Johnson, LJ Speech: a LibriVox volunteer whose recordings are in
  the public domain. The clip is read from the start of the LJ Speech
  archive, so the 2.6 GB file is not downloaded.
- Seven narrators from Hi-Fi TTS (NVIDIA), LibriVox readers, CC BY 4.0:
  credit "Hi-Fi Multi-Speaker English TTS Dataset", Bakhturina et al., 2021.
  The clips come one at a time through Hugging Face's dataset viewer.

Public domain and CC BY cover the recordings. These readers did not sign
up to have their voices copied; for use on this PC that is fine.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from babysitter.paths import data_dir

LJ_ARCHIVE = "https://data.keithito.com/data/speech/LJSpeech-1.1.tar.bz2"
HIFI_ROWS = "https://datasets-server.huggingface.co/rows?"


@dataclass(frozen=True)
class Narrator:
    id: str
    name: str
    accent: str
    licence: str
    sha256: str
    source: str  # "lj" or "hifi"
    member: str = ""  # the LJ archive member
    config: str = ""  # Hi-Fi TTS config and row
    row: int = 0


HIFI_CREDIT = "CC BY 4.0: Hi-Fi Multi-Speaker English TTS Dataset (Bakhturina et al., 2021), from LibriVox."

NARRATORS = [
    Narrator("lj", "Linda Johnson (LJ Speech)", "American", "Public domain (LibriVox).",
             "a88129cf4fcd72945a445de0bf437057846a5fa4505d62ce4e629fee99eadb05", "lj", member="LJSpeech-1.1/wavs/LJ005-0143.wav"),
    Narrator("hifi-92", "Hi-Fi narrator 92", "American", HIFI_CREDIT,
             "128dbf511befbe339dee081e97e57796bc4b1f45e3fc9e872090d2d8353d1969", "hifi", config="clean", row=100059),
    Narrator("hifi-6097", "Hi-Fi narrator 6097", "American", HIFI_CREDIT,
             "dbc845e3860e2355e1512ad5a261c0d82152c377a8f107cd186d085daab29321", "hifi", config="clean", row=39),
    Narrator("hifi-9017", "Hi-Fi narrator 9017", "American", HIFI_CREDIT,
             "5577f88c02643f3abad0213a21acb575346184461b68d436f2f1e354f73648ce", "hifi", config="clean", row=40026),
    Narrator("hifi-8051", "Hi-Fi narrator 8051", "American", HIFI_CREDIT,
             "cff18131bf69ef6ce761a15a289df235ef0486d2f86c301c5be3760a00f09bb6", "hifi", config="other", row=137569),
    Narrator("hifi-9136", "Hi-Fi narrator 9136", "American", HIFI_CREDIT,
             "4c9b5815ebdc6aa4107e3528dd34339ea58f8f347d29d3a569cd752412e3c063", "hifi", config="other", row=176874),
    Narrator("hifi-11614", "Hi-Fi narrator 11614", "American", HIFI_CREDIT,
             "3cd7233ce1a792b3ec10ef7e0ff98147c4242829852e65e3c8da924281a1522b", "hifi", config="other", row=13100),
    Narrator("hifi-11697", "Hi-Fi narrator 11697", "American", HIFI_CREDIT,
             "9e2275ef2bc5c58457c1e34703bc7b28559057761309aa4ff18f1cad62afb9d7", "hifi", config="other", row=32763),
]
BY_ID = {narrator.id: narrator for narrator in NARRATORS}


class NarratorError(Exception):
    """A narrator's clip could not be fetched or did not match."""


def clip_path(narrator: Narrator) -> Path:
    suffix = ".wav" if narrator.source == "lj" else ".flac"
    return data_dir() / "models" / "narrators" / f"{narrator.id}{suffix}"


def clip_ready(narrator: Narrator) -> bool:
    return clip_path(narrator).is_file()


def verified_clip(narrator: Narrator) -> Path:
    """The clip, after checking its hash. A clip is small, so it is hashed every time."""
    path = clip_path(narrator)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise NarratorError(f"{narrator.name} is not downloaded yet.") from exc
    if hashlib.sha256(data).hexdigest() != narrator.sha256:
        raise NarratorError(f"{narrator.name}'s clip was changed, so it was not used. Download it again.")
    return path


def _open(url: str, timeout: int = 60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "BabySitter"}), timeout=timeout)


def _lj_clip(narrator: Narrator) -> bytes:
    with _open(LJ_ARCHIVE) as response, tarfile.open(fileobj=response, mode="r|bz2") as tar:
        for member in tar:
            if member.name == narrator.member:
                handle = tar.extractfile(member)
                return handle.read() if handle is not None else b""
    raise NarratorError("The LJ Speech clip was not found in the archive.")


def _hifi_clip(narrator: Narrator) -> bytes:
    query = urllib.parse.urlencode({"dataset": "MikhailT/hifi-tts", "config": narrator.config, "split": "train",
                                    "offset": str(narrator.row), "length": "1"})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with _open(HIFI_ROWS + query) as response:
                row = json.loads(response.read().decode("utf-8"))["rows"][0]["row"]
            with _open(row["audio"][0]["src"]) as response:
                return response.read(5_000_000)
        except Exception as exc:  # the viewer limits how fast it is asked
            last = exc
            time.sleep(4 + attempt * 6)
    raise NarratorError("Hugging Face's dataset viewer did not answer. Try again in a minute.") from last


def download(narrator: Narrator) -> str:
    """Fetch one narrator's clip. The caller must have asked first."""
    data = _lj_clip(narrator) if narrator.source == "lj" else _hifi_clip(narrator)
    if hashlib.sha256(data).hexdigest() != narrator.sha256:
        raise NarratorError(f"{narrator.name}'s clip did not match the one this release expects. Nothing was kept.")
    path = clip_path(narrator)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(path)
    return f"{narrator.name} is on this PC."
