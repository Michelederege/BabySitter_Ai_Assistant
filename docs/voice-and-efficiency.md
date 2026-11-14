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

## Still to do, in this order

Priority 1 remaining: pre-made filler clips, a hard cancel of generation inside one audio block, spoken replies held to 2–3 sentences with long lists on a card, and background jobs that never run during a voice turn.

Priority 2: the follow-up window, Silero and Smart Turn, echo cancellation, and optional talk-over. Off by default.

Priority 3: personality, quick confirm with undo, memory explanations, the proactivity ladder, and the weekly review.

Priority 4 and E9: do not build now. No speech-to-speech model and no cloud realtime voice.

E1 remaining: every request using the same 16384 context waits for the video-memory guard, so a 12 GB card is not forced over the edge first.

E2 through E8: video-memory guard, faster game-mode unload, quick commands, screenshot sizing, thread limits, and the benchmark button.
