"""The natural-voice helper. It runs in its own Python, not BabySitter's.

Chatterbox needs numpy 1.x and its own torch, which would break Kokoro,
Piper, and the memory model if they shared one Python. So BabySitter
starts this file with the Python in %LOCALAPPDATA%\\BabySitter\\voiceclone\\venv
and talks to it over its standard input and output, one JSON line each way.

    in:  {"id": 1, "text": "Hello.", "voice": "C:/.../lj.wav", "exaggeration": 0.5}
    out: {"id": 1, "rate": 24000, "samples": "<base64 float32>"}   or {"id": 1, "error": "..."}

It loads only the checked files in the model folder it is given and never
downloads anything. It stops when its input closes.
"""

from __future__ import annotations

import base64
import json
import os
import sys


def main(model_dir: str) -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"  # never fetch: the files came through BabySitter's check
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    # Replies go only to the real output. Anything a library prints (the
    # watermark model announces itself) goes to the error stream instead,
    # so it can never be mistaken for a reply.
    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        import numpy as np
        import torch
        from chatterbox.tts import ChatterboxTTS

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = ChatterboxTTS.from_local(model_dir, device)
    except Exception as exc:  # the parent shows this sentence
        out.write(json.dumps({"ready": False, "error": f"The natural voice could not start ({type(exc).__name__}: {exc})."}) + "\n")
        out.flush()
        return 1
    out.write(json.dumps({"ready": True, "device": device}) + "\n")
    out.flush()
    prepared = ""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            voice = str(job.get("voice") or "")
            exaggeration = float(job.get("exaggeration", 0.5))
            key = f"{voice}|{exaggeration}"
            if voice and key != prepared:
                # The voice is worked out once from its clip, not for every sentence.
                model.prepare_conditionals(voice, exaggeration=exaggeration)
                prepared = key
            with torch.inference_mode():
                wav = model.generate(str(job.get("text") or ""), exaggeration=exaggeration, cfg_weight=float(job.get("cfg", 0.5)))
            samples = wav.squeeze().detach().cpu().numpy().astype(np.float32)
            reply = {"id": job.get("id"), "rate": int(model.sr), "samples": base64.b64encode(samples.tobytes()).decode("ascii")}
        except Exception as exc:
            reply = {"id": job.get("id") if isinstance(job, dict) else None, "error": f"{type(exc).__name__}: {exc}"[:300]}
        out.write(json.dumps(reply) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
