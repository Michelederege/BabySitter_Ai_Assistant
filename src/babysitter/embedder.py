"""Ranks saved facts against a question, on the processor.

Two ways, and the better one is used when it is on this PC:

- The hashed word match needs nothing and misses synonyms: "my car"
  does not find a fact about "the Toyota".
- The sharper memory is a small sentence model (about 90 MB, ONNX),
  downloaded only after a confirm, checked against a recorded hash, and
  run on the processor. A fact is embedded once when it is saved and the
  vector is kept beside the facts, so a question costs one small forward
  pass. It does not touch the graphics card and does not load a second
  Ollama model.

Either way, only the top two matching facts ever reach the prompt, so a
big memory never weighs on the AI.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import threading
from pathlib import Path

from babysitter.paths import data_dir
from babysitter.platform import libraries_import, missing_from_exe, running_inside_exe


DIMS = 64

EMBED_PACKAGES = ("onnxruntime==1.20.1", "numpy")

MODEL_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
VOCAB_URL = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/vocab.txt"

# Hashed-word scores and sentence-model scores live on different scales.
HASHED_FLOOR = 0.2
ONNX_FLOOR = 0.3
# Shared only through these, a fact is not about the question.
_LIGHT_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "my", "your", "i", "you", "it", "that", "this", "what",
    "do", "does", "did", "have", "has", "with", "from", "at",
}


class EmbedderError(Exception):
    """The sharper memory could not be downloaded or used."""


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def embed(text: str, dims: int = DIMS) -> tuple[float, ...]:
    """A stable hashed bag of words, normalized so scores stay comparable."""
    vector = [0.0] * dims
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = digest[0] % dims
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def similarity(left: str, right: str) -> float:
    a = embed(left)
    b = embed(right)
    return sum(x * y for x, y in zip(a, b))


def rank_texts(query: str, texts: list[str], k: int = 2, floor: float = HASHED_FLOOR) -> list[str]:
    """The closest texts at or above the floor. Order is best first."""
    engine = _shared_engine()
    if engine is not None:
        try:
            return _rank_vectors(engine, query, texts, k)
        except Exception:
            # The sharper memory failing must never break an answer.
            pass
    return _rank_hashed(query, texts, k, floor)


def _rank_hashed(query: str, texts: list[str], k: int, floor: float) -> list[str]:
    """Rank by shared words. A hash bucket can collide, so a fact with no word in common is skipped."""
    query_tokens = set(_tokens(query))
    scored: list[tuple[float, str]] = []
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        shared = query_tokens & set(_tokens(cleaned))
        if query_tokens and not shared:
            continue
        if shared and not (shared - _LIGHT_WORDS):
            continue
        score = similarity(query, cleaned)
        if score >= floor:
            scored.append((score, cleaned))
    scored.sort(key=lambda item: item[0], reverse=True)
    found: list[str] = []
    for _score, text in scored:
        if text not in found:
            found.append(text)
        if len(found) >= k:
            break
    return found


def _rank_vectors(engine, query: str, texts: list[str], k: int) -> list[str]:
    cache = VectorCache()
    wanted = engine.embed(query)
    scored: list[tuple[float, str]] = []
    kept: list[str] = []
    changed = False
    for text in texts:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        kept.append(cleaned)
        vector = cache.get(cleaned)
        if vector is None:
            vector = engine.embed(cleaned)
            cache.put(cleaned, vector)
            changed = True
        score = sum(a * b for a, b in zip(wanted, vector))
        if score >= ONNX_FLOOR:
            scored.append((score, cleaned))
    # A deleted fact must not leave its vector behind forever.
    if cache.prune(kept):
        changed = True
    if changed:
        cache.save()
    scored.sort(key=lambda item: item[0], reverse=True)
    found: list[str] = []
    for _score, text in scored:
        if text not in found:
            found.append(text)
        if len(found) >= k:
            break
    return found


# ---------------------------------------------------------------------------
# The sharper memory: a small sentence model on the processor.


def embedder_dir() -> Path:
    path = data_dir() / "models" / "embedder"
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_ready() -> bool:
    folder = embedder_dir()
    return (folder / "model.onnx").is_file() and (folder / "vocab.txt").is_file()


def packages_installed() -> bool:
    # onnxruntime opens its own DLLs. A missing one in the packaged exe is
    # an OSError, and it used to close the window.
    return libraries_import("numpy", "onnxruntime")


def ready() -> bool:
    return packages_installed() and model_ready()


def install_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", *EMBED_PACKAGES]


def download() -> str:
    """Download the sharper memory. The user must confirm before this runs."""
    from babysitter.platform import run_hidden
    from babysitter.security import keep_if_matching, require_embedder_url, require_matching_file

    for url in (MODEL_URL, VOCAB_URL):
        require_embedder_url(url)
    if not packages_installed():
        if running_inside_exe():
            raise EmbedderError(missing_from_exe("The sharper memory"))
        completed = run_hidden(install_command(), timeout=900)
        if completed.returncode not in (0, None):
            output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            raise EmbedderError(output[-1500:] or "The memory programs did not install.")
    if not packages_installed():
        raise EmbedderError(
            "The memory programs installed. Close BabySitter, open it again, "
            "and press the download once more so the model file can arrive."
        )
    folder = embedder_dir()
    for url, filename in ((MODEL_URL, "model.onnx"), (VOCAB_URL, "vocab.txt")):
        destination = folder / filename
        if keep_if_matching(url, destination):
            continue
        from urllib import request as urlrequest

        temporary = destination.with_suffix(destination.suffix + ".part")
        with urlrequest.urlopen(url, timeout=300) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
        try:
            require_matching_file(url, temporary)
        except ValueError as exc:
            temporary.unlink(missing_ok=True)
            raise EmbedderError(str(exc)) from None
        temporary.replace(destination)
    if not model_ready():
        raise EmbedderError("The download finished, but the model was not usable.")
    release()
    return (
        "The sharper memory is on this PC. Saved facts now match by meaning, "
        "still on the processor, still only the top two per question."
    )


def warm() -> None:
    """Load the model off the window's thread, so a question is not waiting on it."""
    _shared_engine()


def release() -> None:
    """Drop the loaded model. The files stay on disk."""
    global _engine, _engine_checked
    with _lock:
        _engine = None
        _engine_checked = False


_engine = None
_engine_checked = False
_lock = threading.Lock()


def _shared_engine():
    global _engine, _engine_checked
    with _lock:
        if _engine_checked:
            return _engine
        _engine_checked = True
        if not ready():
            _engine = None
            return None
        try:
            _engine = OnnxEmbedder(embedder_dir())
        except Exception:
            _engine = None
        return _engine


class OnnxEmbedder:
    """all-MiniLM-L6-v2 on the processor: WordPiece, mean pooling, unit length."""

    MAX_TOKENS = 256

    def __init__(self, folder: Path) -> None:
        import onnxruntime as ort

        from babysitter.security import require_loaded_file

        # A file that does not match is not loaded. The same-words match is used instead.
        require_loaded_file(MODEL_URL, folder / "model.onnx")
        require_loaded_file(VOCAB_URL, folder / "vocab.txt")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        try:
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        except Exception:
            pass
        self.session = ort.InferenceSession(
            str(folder / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.vocab = load_vocab(folder / "vocab.txt")

    def embed(self, text: str) -> list[float]:
        import numpy as np

        ids = wordpiece_ids(text, self.vocab, self.MAX_TOKENS)
        input_ids = np.array([ids], dtype=np.int64)
        attention = np.ones_like(input_ids)
        feeds = {"input_ids": input_ids, "attention_mask": attention}
        if any(item.name == "token_type_ids" for item in self.session.get_inputs()):
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        hidden = self.session.run(None, feeds)[0][0]
        pooled = hidden.mean(axis=0)
        norm = float(np.linalg.norm(pooled))
        if norm == 0:
            return [0.0] * len(pooled)
        return [float(value) for value in pooled / norm]


def load_vocab(path: Path) -> dict[str, int]:
    vocab: dict[str, int] = {}
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        token = line.strip()
        if token:
            vocab[token] = index
    return vocab


def _basic_tokens(text: str) -> list[str]:
    """Lowercase words and single punctuation marks, the BERT basic split."""
    pieces: list[str] = []
    word = ""
    for character in (text or "").lower():
        if character.isalnum() or character == "'":
            word += character
            continue
        if word:
            pieces.append(word)
            word = ""
        if not character.isspace():
            pieces.append(character)
    if word:
        pieces.append(word)
    return pieces


def wordpiece_ids(text: str, vocab: dict[str, int], max_tokens: int = 256) -> list[int]:
    """Greedy longest-match WordPiece, wrapped in [CLS] and [SEP]."""
    unknown = vocab.get("[UNK]", 100)
    ids: list[int] = [vocab.get("[CLS]", 101)]
    for token in _basic_tokens(text):
        if len(ids) >= max_tokens - 1:
            break
        pieces: list[int] = []
        start = 0
        while start < len(token):
            end = len(token)
            found = None
            while start < end:
                candidate = token[start:end]
                if start > 0:
                    candidate = "##" + candidate
                if candidate in vocab:
                    found = vocab[candidate]
                    break
                end -= 1
            if found is None:
                pieces = [unknown]
                break
            pieces.append(found)
            start = end
        ids.extend(pieces[: max_tokens - 1 - len(ids)])
    ids.append(vocab.get("[SEP]", 102))
    return ids


class VectorCache:
    """Vectors for saved facts, kept beside the facts. No words, no network."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "memory-vectors.json")
        self._data: dict[str, list[float]] = {}
        self._loaded = False

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, list):
                    self._data[str(key)] = [float(item) for item in value]

    def get(self, text: str) -> list[float] | None:
        self._load()
        return self._data.get(self._key(text))

    def put(self, text: str, vector: list[float]) -> None:
        self._load()
        self._data[self._key(text)] = [round(float(value), 6) for value in vector]

    def prune(self, texts: list[str]) -> bool:
        """Keep only the vectors for these texts. Returns True when any left."""
        self._load()
        wanted = {self._key(text) for text in texts}
        stale = [key for key in self._data if key not in wanted]
        for key in stale:
            del self._data[key]
        return bool(stale)

    def save(self) -> None:
        try:
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self._data) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            return
