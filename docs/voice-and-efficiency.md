# Voice and efficiency additions

This is the November 2026 research, kept so the build order stays fixed.
Priority 1 comes before the calendar and before Priorities 2–4.
Items marked "do not build now" stay unbuilt.

## Already started in 0.8.0

- Responsiveness timings only, on the Voice tab and in Export diagnostics
- Standing instructions stay the same for the session; the clock is on the newest message
- Voice turns send think: false, and thinking text is stripped before speech
- The first speakable piece still starts at the first sentence, or a comma after about 8 words
- Kokoro plays raw audio in short blocks, and the next piece is built while one plays
- Holding talk while it speaks stops playback, drops the late answer, and keeps only the words already spoken
- "Carry on" or "what were you saying?" reads the cut-off rest
- If 1.5 seconds pass with no sound, the screen shows a short waiting line
- When BabySitter itself starts Ollama, it sets the private host, one model, flash attention, q8 cache, and a 5-minute keep-alive for when BabySitter is not running. While the AI is on, requests still use keep-alive forever.

## Added in 0.10.0

- Time, video memory, PC health, screen look, “why did you say that”, and timers run without the model
- A timer starts immediately. Say undo within 10 seconds to cancel it
- Game mode answers those short requests. Anything else asks before loading the model
- A short spoken “One moment” when Heart and Sarah is already on this PC
- Stopping an answer closes the Ollama request
- A screenshot is shrunk to a 1280 long edge and sent to the model already loaded. It is not saved
- Lists longer than three items, and code, stay on the screen. KB numbers and hex codes are spelled out
- Follow-up listening is a setting from 5 to 20 seconds
- The model is not loaded when the card does not have room. If the free amount cannot be read, the load is allowed
- The Models tab can time a fixed prompt three times
- Hearing uses four processor threads. BabySitter starts with a small thread limit

## Added in 0.11.0

- Low uses a 16,384-token context. Medium stays at 8,192. High stays at 16,384 and is refused when the card is full
- Every request at one level sends the same context size
- After a load, a model that spilled more than 0.5 GB out of video memory is unloaded
- A loaded context shorter than the one asked for is shown as Needs you
- Ollama older than 0.34.2 gets a speed note. The security cutoff stays 0.17.1
- A slow first start says Ollama may be upgrading its storage
- Hold to talk while Off starts loading during the question
- A model loaded from Game mode unloads again two minutes after the answer
- Prompt-token counts and generation speed are kept with the other timings. No words
- The benchmark compares generation speed with the first saved run
- Charts skip nvidia-smi while the window is hidden. Game detection still runs
- Speech recognition is loaded once. Kokoro uses four threads and does not spin-wait
- Off drops the speech model and the voice from memory
- “Read the small text” sends the screenshot at full size and says it takes a few seconds
- A setting, off by default, can keep BabySitter on logical processors 12–23 on a 24-thread CPU

## Still to do, in this order

Priority 1, Priority 2, and Priority 3 from the November list are in 0.12.0, with the limits below.

- Filler lines play from clips made while no voice turn is open. If Heart and Sarah is not downloaded, the line stays on screen and is not spoken live.
- Stop is checked every 10 ms of Kokoro audio, and between short Windows-voice pieces.
- A benchmark, the PC-health read, filler rendering, and the weekly review do not run during a voice turn. Game-name checks still run.
- Silero runs only when `models/silero/silero_vad.onnx` is already on this PC. Otherwise the processor energy check is used. Smart Turn, echo subtraction, and talk-over are off until Settings enables them. Talk-over does nothing unless echo subtraction is also on.
- Personality ratings apply the next time the AI turns on, so the standing instructions stay fixed during a session.
- Proactivity defaults to 1. The weekly review is local text. It does not load a model.
- “Why did you say that” shows the recent conversation and any saved fact the on-PC embedder matched.

Priority 4 and E9: do not build now. No speech-to-speech model and no cloud realtime voice.

E1: Low is 4,096 so the 9B model stays near 6 GB. Medium stays at 8,192. High is 16,384 only when the guard allows it. Every request at one level sends that level's context and batch.

E2 through E8: video memory is read through NVML when the driver library is present, with nvidia-smi as the fallback. Facts are ranked by an in-process embedder, not a second model. Filler clips are pre-rendered. The core-avoidance setting still exists and stays off until frame times are compared. There is no llama-server backend, and PyTorch is not removed.
