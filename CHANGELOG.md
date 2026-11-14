# Changelog

BabySitter uses version numbers like v1.2.3. The voice loop is not in yet.

## 0.14.3 — The scan says the memory number, then one question

A spoken scan now starts with the real memory reading, such as "Memory is using 20.0 of 32.0 GB, 62 percent," and then one suggestion you can accept or deny. "Why is my ram so high," "my computer is slow," and "free up some memory" take that path. "How is my pc" speaks the memory and CPU numbers.

If a reply is still being spoken, the scan waits and runs when that reply finishes. It no longer says it will scan and then drops the request. The model is told not to invent a scan and not to paste a shell command.

## 0.14.2 — A spoken scan checks this PC

“I'd like you to scan my computer, my RAM usage is very high” now runs the scan on this PC. It no longer asks the model, which was answering that it could not see the hardware and pasting a shell command. The same is true for “scan this computer”, “check my RAM”, and “what's using my memory”.

If nothing is heavy enough to close, the scan still names the heaviest program it can see. The spoken line is not repeated again in the text under it.

## 0.14.0 — Saved chats, spoken tools, and a few switches that were waiting

Conversations are saved on this PC when a reply finishes. History can search them, export one as a text file, delete one, or wipe them after you type WIPE.

Say “search the web for …” to use a SearXNG you run on this computer. Say “search reddit for …” (or TikTok, YouTube, Instagram, Threads, Pinterest) and BabySitter asks once, then can summarize the public results. Ad libraries are refused. There is no ad-library source here.

Google sign-in uses your own OAuth client id and a page on 127.0.0.1. The token can be refreshed. Mail and calendar stay read-only. While the AI is on, new mail and events can be spoken about every 15 minutes. A pasted token still works.

Quiet hours, hiding the orb while a watched game is in front, and a side mouse button for talk are in Settings and off. The side button does nothing while the AI is off or in Game mode. The intelligence slider snaps to Low, Medium, and High. Check for an update asks GitHub and does not download or install. Silero can be downloaded after a confirm, and stays off until the detector setting is on.

Speech-to-speech, a cloud realtime voice, voice cloning, and signing the installer are not in this build. Signing needs your certificate.

## 0.13.0 — A conversation, your Google account, and one suggestion at a time

Low stays on `qwen3.5:9b`. A 3B or 4B model would be smaller and would miss tools, mail, and calendar. `gemma4:12b` stays for longer writing when the card is free. Only one model is loaded. Cutting the context from 4,096 to 2,048 saves about 80 MB and clips a screenshot and a tool reply, so Low stays at 4,096. That is a calculation for this 12 GB card, not a live measurement.

The standing instructions now start with the answer and do not ask you to confirm a chat. A yes or a no is for one change on this PC, or for something that leaves it. Looking at the screen no longer asks a second time after you already asked. A reminder or a remembered fact is saved, and you can say undo within 10 seconds.

Google mail and calendar are off until you turn them on under Tools and paste a read-only token from your own account. The token is encrypted on Windows, in its own file, and is not stored in settings.json. BabySitter only reads. It does not send mail and does not delete mail. When the AI turns on, it can speak unread mail and the next events once.

Say scan my PC, or press Suggest changes. BabySitter names one heavy app or one startup item. Say yes to do that one, or no to leave it. Games, Windows, and security tools are not closed. A startup item can be put back with undo within 10 seconds. Closing an app cannot be undone.

## 0.12.0 — Low fits in 4 to 6 GB, and the remaining local features

The code from 0.11.0 is tagged `checkpoint-0.11.0`. Check that tag out if this build misbehaves.

Low still uses `qwen3.5:9b`, so voice, tools, and pictures stay. The context is 4,096 tokens and the batch is 128. That is the room a short talk and a shrunk screenshot need. When BabySitter starts Ollama, the cache is q4 and flash attention stays on. The weights of a 9B Q4 model are about 5.4 GB, so Low lands around 6 GB rather than 4 GB. Layers are not moved into system memory, because that makes replies slow and BabySitter would unload the model. Medium stays at 8,192. High stays at 16,384 and still loads only when the card has room.

Video memory is read from the NVIDIA driver library when it is present. `nvidia-smi` is the fallback. Those reads pause during a voice turn. A benchmark, a PC check, filler rendering, and the weekly review wait too. Game-name checks still run.

"One moment", "Still working", and "Give me a second" play from clips rendered ahead of time, not from the live voice. Stopping speech is checked every 10 ms, and the Windows voice stops between short pieces. Silero is used when `silero_vad.onnx` is already in the BabySitter folder. Otherwise a loud-versus-quiet check on the processor does the job. Smart Turn, echo subtraction, and talking over a reply are in Settings and are off. Saved facts that match the question can ride along with it, still on this PC. You can rate a reply. The rating applies the next time the AI turns on. Proactivity runs from 0 to 3, and the default is 1. A weekly review is written from local notes and does not load a model.

Speech-to-speech and a cloud realtime voice are still not built.

## 0.11.0 — Keep the model on the graphics card

Low now gives qwen3.5:9b a 16,384-token conversation. That extra room is small on this model. Medium stays at 8,192 because the writing model already fills a 12 GB card. High still asks for 16,384 and loads only when the card has room. If the model spills into system memory, BabySitter unloads it and says so. A short context is reported instead of being ignored. Holding talk while the AI is off starts the load while you are still speaking. In Game mode, saying yes loads the model and unloads it again two minutes after the answer. Speech recognition stays loaded while the AI is on, on four processor threads. Heart and Sarah is capped the same way and stops spinning while it waits. The benchmark records speeds, not words, and warns if a later run is much slower.

## 0.10.0 — Faster everyday answers, still on this PC

Short requests such as the time, video memory, a timer, and “why did you say that” are answered without the language model. A timer starts immediately and can be cancelled by saying undo within 10 seconds. In Game mode those short requests still work. Anything else asks before loading the model. If a reply takes more than a second and a half, and Heart and Sarah is already downloaded, BabySitter says “One moment” while it keeps working. Stopping an answer also stops the request to Ollama. A screenshot is shrunk and shown to the model that is already loaded. It is not saved. Long lists and code stay on the screen. The follow-up window can be 5 to 20 seconds. A benchmark on the Models tab times a fixed prompt three times and keeps only the times.

## 0.9.0 — A conversation, not a new question every time

BabySitter keeps the last few things you said and answers in two or three sentences. The rest stays on screen. Say tell me more to hear it. After an answer, if keyword listening is on, you can keep talking for 10 seconds without saying baby sitter. Say that's all to stop. The tone is warmer, and it is allowed to disagree.

## 0.8.0 — Measure the wait, and stop cleanly

Voice turns record timings only, on the Voice tab under Responsiveness and in Export diagnostics. The clock stays on the newest message so the standing instructions can be reused. Hidden thinking is removed before anything is spoken. Holding the talk button while BabySitter is speaking stops the voice and the answer. Say “carry on” to hear the rest of what was cut off. If a second and a half passes with no sound, the screen says it is still working.

## 0.7.2 — Shorter wait before the first word

The question is sent after a shorter pause. The first words are spoken once about a dozen words are ready, instead of waiting for a long sentence. On Low, the hidden thinking step is skipped. Heart and Sarah loads when the AI turns on, so the first answer is not also waiting for the voice.

## 0.7.1 — Start speaking sooner

The first sentence is spoken as soon as it is written. BabySitter no longer waits for the whole answer before it starts talking. The rest still follows only if you say yes.

## 0.7.0 — Ask before reading the rest

A reply is spoken as one sentence. If there is more, BabySitter asks “Do you want to know more?” Say yes and it reads the rest. Say no and it stops. The full answer stays on screen either way.

## 0.6.0 — Baby sitter, the clock, and Heart and Sarah

The keyword is “baby sitter”. Every question now includes the clock on this PC, so the model can answer the time. That time stays on this computer with the question. Replies use Heart and Sarah when that voice is downloaded. Until then, BabySitter says so instead of pretending the Windows voice is the one you picked.

## 0.5.1 — Keyword and command in one sentence

“Hey babysitter what time is it” is one command. The words after the keyword are what gets sent. You do not have to pause and wait for a second listen.

## 0.5.0 — Say a keyword instead of holding a button

Keyword listening is off until you turn it on. While it is on, and the AI is on, the microphone stays open for the keyword (hey babysitter, unless you change it). The sound is checked on this PC. It is not saved and it is not sent. The orb shows when it is listening. Hold to talk is still there as a backup. Game mode and Off close the microphone.

## 0.4.0 — The Windows voice, and a download for hearing

Replies can be spoken with the Windows voice already on your PC. Kokoro is not installed yet, so a Kokoro name uses that Windows voice instead. Holding Talk does not open the microphone until you click Download speech recognition on the Voice tab. That download stays on this PC and runs on the processor, not the graphics card.

## 0.3.1 — Warning line stays one line

The note that Ollama is already running no longer stretches into a tall empty box. The compact window opens short. Expand still opens the full Home screen.

## 0.3.0 — The slate window

The window now follows the slate-and-orange design: top tabs, a pin rail, Home with power, intelligence, game mode, emergency stop, this PC, a hero picture, a pinboard, and what just happened.

- Orange is for actions. Green, blue, yellow, and red are for state. The words are Off, Working, On, Game, and Needs you.
- Compact shows the power row. Expand opens the tabs. The app remembers which one you used.
- Low loads qwen3.5:9b. Medium and High load gemma4:12b. Only one model is loaded at a time.
- Hold to talk, typed commands, reminders, memory, pins, a screen look, and the model list do something and tell you what happened. A reminder is saved only after you confirm.
- Voice choices can be saved. Speaking them waits until a voice engine is installed. There is no voice cloning.
- Choose my picture copies a photo into your BabySitter folder. It is not uploaded.

Speech-to-text, Kokoro, speaker recognition, session refresh, and the updater are not running yet.

## 0.2.1 — Privacy line

Home now says when BabySitter is private to this computer. Social search stays the only optional path off the PC, and the Tools tab says it never includes files, the screen, memory, or what you say to the assistant. There is still no usage data and no phone-home.

## 0.2.0 — Social search

Optional public social search on the Tools tab. It uses the ScrapeCreators API, the same data layer as the skills at https://github.com/ScrapeCreators/social-media-research-skills

- Off until you check "Turn on social search".
- You confirm every search. The window shows the exact words and the address before anything is sent.
- The API key is encrypted with Windows DPAPI. It is not stored in settings.json and it is not written in the log.
- Searches cover public posts, public profiles, public comments, and one public video transcript. Follower lists and age or gender guesses are not included.
- The longer research recipes (outlier posts, ad libraries, and the rest) wait until the assistant can talk.

## 0.1.0 — Phase 1

The power switch, the floating orb, and the status board. The microphone is not opened.

- The app always opens with the AI off.
- One power button in the window, on the orb's right-click menu, and in the tray.
- Off unloads every model, stops Ollama, closes the microphone hook, and turns off future assistant hotkeys. The emergency key and the turn-on key stay active.
- On starts Ollama with no console window, waits until 127.0.0.1:11434 answers, and loads qwen3.5:9b.
- Game mode unloads models and leaves Ollama running with nothing loaded, so a game can use the graphics card.
- Optional automatic game mode, off by default, based only on the program's file name.
- Emergency stop is Ctrl+Alt+F12. Turn on is Ctrl+Alt+F11. Both can be changed in Settings.
- Warns if Ollama is older than 0.17.1 (CVE-2026-7482).
- Notices when Ollama's own tray app is running, and can close it.
- Home shows video memory, loaded models, CPU, and RAM, refreshed every 2 seconds.
- Low / Medium / High changes how much conversation the one loaded model can hold. Only one model is loaded at a time.
- Start with Windows is off unless you turn it on.
- Settings live in `%LOCALAPPDATA%\BabySitter\`, not in the install folder.
- The app lowers its own CPU priority so it is less likely to steal frames from a game.

## Later

Voice, memory, the pinboard, reminders, history, and the updater are not built yet. Social search is the one tool that is in.
