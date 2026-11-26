# What the chats already decided

This is the condensed record of the BabySitter agent chats through
26 November 2026. It was checked against `main` at version 0.18.0.
Later agents should read this file and the code. They should not
reopen those chats to recover a rule.

If this file and `docs/conversation.md`, `docs/voice-and-efficiency.md`,
`docs/2026-11-agent-review.md`, or the folder list in CONTRIBUTING.md
disagree, this file is the one to follow, then the code. Those other
files keep the research. They are not the current rules.

## The PC

Michele's machine is a Ryzen 9 7900X, an RTX 4070 with 12 GB of video
memory (the driver reports about 12,282 MB), and 32 GB of RAM. The
project folder is `C:\BabySitter`. Python is `py -3.12`. Commands he
runs are PowerShell. `cd /d` is Command Prompt and fails there. In
Git Bash the folder is `/c/BabySitter`. `/mnt/c/BabySitter` is not
that shell.

The UGREEN DXP4800 Plus does not run the models. It is a low-power
CPU with 8 GB of RAM and no CUDA. It can hold copies of model files
and of `%LOCALAPPDATA%\BabySitter`. Inference, faster-whisper, and
Kokoro stay on the Windows PC. Ollama stays on `127.0.0.1:11434`.
BabySitter refuses to turn on if Ollama is listening on the network.

A five-node Raspberry Pi K3s cluster was named as a later idea. The
app does not run there.

## Models

Only one model is loaded. Layers stay on the graphics card. Moving
them into system memory was turned down because replies get slow.
The app starts on Medium.

Low is `qwen3.5:9b`, 4,096 tokens of context, batch 256. The Q4
weight file is 5.6 GB. A normal load is about 6.5 GB once the cache
and the CUDA runtime are counted. The older "4 to 6 GB" and "5.4 GB
file, 5.7 GB load" lines were for a smaller file. Cutting the context
to 2,048 was rejected because a screenshot and a tool reply no longer
fit, and this model's cache barely shrinks when the context is cut.
A 3B or 4B model was rejected because it drops mail, calendar, and a
request with more than one step.

Medium is `gemma4:12b` at 8,192 tokens. The card should have about
9,500 MB free before that load. On this PC the large Task Manager
number, near 20 GB of the 32 GB, is that load plus everything else
already in memory. High is the same model at 16,384 tokens, and only
when the card has about 11,000 MB free. Do not switch Medium to
another model unless it wins the Models-tab benchmark. `bonsai-2:27b`
was a candidate, not a change.

When BabySitter starts Ollama it sets one model, flash attention, a
q4_0 cache, a 5-minute keep-alive, and `OLLAMA_NO_CLOUD=1`. Those
settings do not change an Ollama that is already running from the
tray icon. Quit that copy first, or the q4 cache never applies.
Ollama older than 0.35.0 gets a warning (CVE-2026-103663). Older than
0.17.1 also leaks memory (CVE-2026-7482). `ollama pull` refreshes
models, not the engine. Preload sends an empty message list, so the
model loads without writing a token.

## What a reply is allowed to do

The model's words become speech and text on the screen. They do not
run a tool and they do not run a command. `shell=True` stays out of
the source.

A search that leaves the PC, and deleting a saved key or token, still
ask first. Looking at the screen, saving a reminder, and saving a
fact do not ask a second time. The sentence already said is the yes.
Undo lasts 10 seconds.

Google mail, calendar, and Drive file names are read-only. Nothing
is sent, nothing is deleted, and nothing is uploaded. The token is
encrypted in its own file, not in `settings.json`. A second sign-in
stores a school Google account in a different file. New mail and
events are checked about every 15 minutes, and only while the AI is
on. The list on Tools shows the messages, events, and file names.
Blackboard is the calendar feed the school gives you, not a Google
account. Comment links are TikTok or Reddit. A YouTube link is not
sent through the Reddit comments search. The larger public-research recipes (outlier posts, comment
themes, trends, and the rest of that list) are in the app and still
ask before they run.

File search names a program, a script, or a shortcut and does not
start it. A PC scan names one heavy app or one startup item. Games,
Windows, and security tools are never on the list to close. A closed
app is not reopened.

The AI starts off. Quit, the X button, and Escape unload the model,
stop the Ollama BabySitter started, and close the microphone. If
Ollama's own tray app is still running, BabySitter asks before
closing it. "Leave it running" leaves that tray app. The model is
already unloaded. Emergency stop closes the tray app without asking.
Game mode unloads the model, leaves the Ollama process running, and
does not load the model again when the game closes. Leave is what
brings the model back.

## Voice

Kokoro is the spoken voice, shown as Heart and Sarah. If it is not
on the PC, speech falls back to the Windows voice, and a reminder
can speak while the AI is off. Vosk only notices the wake words.
Whisper small on the processor reads the question. The chat model
keeps the graphics card. Moonshine streaming hearing was researched
and not built.

A missing file inside `BabySitter.exe` must leave that feature off.
It must not close the window. The exe does not install Python
libraries into itself. That starts another copy of the window.

## How the program is opened

`Run BabySitter.bat` runs the source tree. A git pull updates that.
`dist\BabySitter.exe` is one file. A pull does not replace it.
`scripts\build-exe.bat` rebuilds it. `scripts\desktop-icon.bat` points
a shortcut at `dist\BabySitter.exe`, so that shortcut follows a
rebuild. A copy of the exe sitting on the desktop stays on the old
build until that file is replaced. From 0.18.0, Settings can do that
replacement after you confirm. Settings, memories, the journal, and
pins stay in `%LOCALAPPDATA%\BabySitter`.

`Setup.bat` makes the virtual environment and installs the libraries.
Python 3.12, the Ollama installer, and the NVIDIA driver stay manual.
After a yes, setup asks Ollama to pull `qwen3.5:9b` and `gemma4:12b`
only. Voice files and the sharper memory each wait for their own yes,
and each new download is checked against a recorded SHA-256. A file
that is already on disk is kept without that check.

On 0.18.0, **Check for an update** and **Update BabySitter** pull
`origin/main` when the git folder is on the PC, rebuild the exe when
one is in use, and restart after a confirm. On a PC with no git
folder they use a GitHub release file and check its SHA-256. Nothing
is signed. The first time onto 0.18.0 still needs one pull and one
`scripts\build-exe.bat` on the PC. After that, the window can do it.

## Git, in one place

Work is merged on Origin `michele-de-rege/Ai-assistant-Babysitter`.
The public copy is GitHub `Michelederege/BabySitter_Ai_Assistant`.
The capital M in that GitHub name is part of the update URL. Agents
do not push the `github` remote and do not force-push. On his PC,
after a merge: `cd C:\BabySitter`, then `git pull origin main`, then
`git push github main`.

One branch, one pull request. A pull request aimed at a branch that
already merged does not land. Make a new branch off `main`. Five
simulations for every feature, not five simulations for the whole app.

## Where the chats disagreed

Each line is a claim that showed up in a chat or in an older doc, and
what the code does now.

- Low was described as a 5.4 GB file and a 5.7 GB load, inside 4 to
  6 GB, with batch 128. The code uses a 5.6 GB file, about 6.5 GB,
  context 4,096, and batch 256.
- `docs/voice-and-efficiency.md` once set Low's context to 16,384 and
  the cache to q8. The code keeps Low at 4,096 and the cache at q4_0.
- The November review said preload asks the model to write "ready",
  and that memory match is only a hashed bag of words. Preload sends
  an empty message list. The hashed match is the fallback. Sharper
  matching downloads an ONNX model and runs it on the processor.
- Several chats said Check for an update never downloads. That was
  true through 0.17.4. Version 0.18.0 installs after a confirm.
- One hunt said Escape only hides the window and leaves the model
  loaded. Escape now takes the same path as the X button and turns
  the AI off.
- One hunt said a YouTube link is sent to the Reddit comments search.
  Comment links are only `tiktok.com` and `reddit.com`.
- Early packaging chats said `BabySitter.exe` has to stay beside a
  folder of DLLs. The built app is one file, `dist\BabySitter.exe`.
- One chat said Quit must never offer to leave Ollama running. The
  model is always unloaded. If Ollama's tray app is open, the window
  still asks, and Leave it running is one of the buttons.
- A 20-of-32 GB memory line in an early chat was a test fixture, not
  a reading from this PC.

## Not built yet

These were asked for or recommended, and they are not in the app.
They are a review list, not rules. Building one of them needs a new
decision.

- Moonshine streaming hearing, and the Parakeet, Piper, and
  Supertonic voices that were compared and not chosen.
- Speech-to-speech, voice cloning, and a cloud realtime voice.
- Code signing.
- Encrypting History and saved facts the way API keys are encrypted.
  Those files are still plain JSON.
- Hash pins on `requirements-voice.txt`. The runtime list pins
  versions. It does not pin every file's hash.
- A named personality, such as "be Brook".
- Switching Medium to `bonsai-2:27b` after a benchmark.
- A llama-server backend, and removing PyTorch.
- Weather, Home Assistant, and music tools.
- Mail or calendar alerts while the AI is off. The 15-minute check
  runs only while the AI is on.
- A school mailbox that is Microsoft 365. School Google (Gmail) is
  a second read-only sign-in. Blackboard is the calendar feed the
  school gives you, not a course login.
- Running BabySitter on the Raspberry Pi cluster.
- Publishing the Inno Setup installer from GitHub. A tagged release
  builds the portable `BabySitter.exe` and `SHA256SUMS.txt`.

Two leftovers from the bug hunts are still in the code:

- Game detection skips a path when any folder contains a word such as
  `setup` or `directx`. A real game under `steamapps\common\TheSetup\`
  is missed. `src/babysitter/games.py`, `looks_like_game_path`.
- Kokoro, Silero, and the sharper-memory download skip the SHA-256
  check when a non-empty file is already on disk.

The rest of those hunt lists were written against older trees. Treat
them as stale until the code shows the same bug.

## Chats this file replaces

The text above is the part worth keeping. The chats themselves can
be archived in Cursor. Archiving does not delete the pull requests
they already merged.

| Chat | What it was | Pull request |
| --- | --- | --- |
| System performance and features | Hardware, Low budget, Google, scan, voice rules | [#1](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/1) merged |
| Ai context and git issues | Off means off, five simulations per feature, Git Bash path | [#4](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/4) merged |
| Agent efficiency and security | Security pass, journal, file search, sharper memory | [#9](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/9) merged |
| Nas for dxp4800 plus | NAS does not run models; public update URL | [#8](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/8) merged |
| Agent chat integrity | Listening layout, reminders, pins, exe vs source | [#14](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/14) merged |
| Application setup and packaging | One-file exe, Setup.bat, desktop copy | [#23](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/23) merged |
| Plus sign location | Broader voice commands, goals, exe crash | [#26](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/26) merged |
| Project bug investigation | Packed voice files must not close the window | [#30](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/30) merged |
| Babysitter app improvements | Review through 0.17.4, then in-app update | [#31](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/31) merged, [#32](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/32) merged |
| Ai assistant | A greeting only | none |
| Summarize prior chat transcript | Empty, and it ended in an error | none |
| Summarize prior agent claims | An audit of one night. The tree has moved on | none |
| Hunt voice and power bugs | Internal hunt. Two leftovers are listed above | none |
| Hunt logic bugs | Internal hunt, no product decision | none |
| Hunt UI bugs | Internal hunt. The Escape bug in it is fixed | none |
