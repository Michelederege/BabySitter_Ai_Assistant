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

Priority 1 remaining: pre-made filler clips instead of speaking the line live, cancel inside one audio block, and background jobs that never run during a voice turn.

Priority 2: Silero and Smart Turn, echo cancellation, and optional talk-over. Off by default. The follow-up window itself is in.

Priority 3 remaining: personality ratings, the proactivity ladder, and the weekly review. Quick confirm with undo is in for timers only. “Why did you say that” shows the recent conversation, not saved facts.

Priority 4 and E9: do not build now. No speech-to-speech model and no cloud realtime voice.

E1 remaining: gemma on Medium stays at 8,192 because a 12 GB card was already full there. High is 16,384 only when the guard allows it. Not every request uses 16,384.

E2 through E8 remaining: NVML instead of nvidia-smi, an in-process embedder, and pre-rendered filler clips. The core-avoidance setting exists and stays off until frame times are compared. Do not build a llama-server backend or remove PyTorch in this pass.
