# What the chats already decided

This is the condensed record of the BabySitter agent chats through
26 November 2026. Later agents should read this file and the code.
They should not reopen those chats to recover a rule.

The code on `main` was checked while this file was written. A chat
that describes an older version is kept here only when the decision
still matches the code.

## The PC

Michele's machine is a Ryzen 9 7900X, an RTX 4070 with 12 GB of video
memory, and 32 GB of RAM. The project folder is `C:\BabySitter`.
Python is `py -3.12`. Commands he runs are PowerShell. `cd /d` is
Command Prompt and fails there. In Git Bash the folder is
`/c/BabySitter`. `/mnt/c/BabySitter` is not that shell.

The UGREEN DXP4800 Plus does not run the models. It is a low-power
CPU with 8 GB of RAM and no CUDA. It can hold copies of model files
and of `%LOCALAPPDATA%\BabySitter`. Inference, faster-whisper, and
Kokoro stay on the Windows PC. Ollama stays on `127.0.0.1:11434`.
BabySitter refuses to turn on if Ollama is listening on the network.

## Models

Only one model is loaded. Layers stay on the graphics card. Moving
them into system memory was turned down because replies get slow.

Low is `qwen3.5:9b`, 4,096 tokens of context, batch 256. The weights
are about 5.4 GB and a normal load is about 5.7 GB. That is the 4 to
6 GB goal. It is not 4 GB. A 3B or 4B model was rejected because it
drops mail, calendar, and a request with more than one step. Cutting
the context to 2,048 was rejected because a screenshot and a tool
reply no longer fit.

Medium is what the app starts on: `gemma4:12b` at 8,192 tokens, about
9.5 GB of video memory. On this PC that load is the large Task
Manager number, near 20 GB of the 32 GB. High is the same model at
16,384 tokens, and only when the card has room. Do not switch Medium
to another model unless it wins the Models-tab benchmark. `bonsai-2:27b`
was a candidate, not a change.

When BabySitter starts Ollama it sets one model, flash attention, a
q4 cache, a 5-minute keep-alive, and `OLLAMA_NO_CLOUD=1`. Those
settings do not change an Ollama that is already running from the
tray icon. Quit that copy first. Ollama older than 0.35.0 gets a
warning (CVE-2026-103663). Older than 0.17.1 also leaks memory
(CVE-2026-7482). `ollama pull` refreshes models, not the engine.

## What a reply is allowed to do

The model's words become speech and text on the screen. They do not
run a tool and they do not run a command. `shell=True` stays out of
the source.

A search that leaves the PC, and deleting a saved key or token, still
ask first. Looking at the screen, saving a reminder, and saving a
fact do not ask a second time. The sentence already said is the yes.
Undo lasts 10 seconds.

Google mail and calendar are read-only. Nothing is sent and nothing
is deleted. The token is encrypted in its own file, not in
`settings.json`. Comment links are TikTok or Reddit. A YouTube link
is not sent through the Reddit comments search.

File search names a program, a script, or a shortcut and does not
start it. A PC scan names one heavy app or one startup item. Games,
Windows, and security tools are never on the list to close. A closed
app is not reopened.

The AI starts off. Quit, and the X button, unload the model, stop the
Ollama BabySitter started, and close the microphone. There is no
"leave Ollama running" quit. Escape hides the window the same way the
X button does, and that path turns the AI off. Game mode unloads the
model and does not load it again when the game closes. Leave is what
brings the model back.

## Voice

Kokoro is the spoken voice, shown as Heart and Sarah. If it is not
on the PC, speech falls back to the Windows voice and the AI stays
off for a reminder. Vosk only notices the wake words. Whisper small
on the processor reads the question. The chat model keeps the
graphics card. Moonshine streaming hearing was researched and not
built.

A missing file inside `BabySitter.exe` must leave that feature off.
It must not close the window. The exe does not install Python
libraries into itself. That starts another copy of the window.

## How the program is opened

`Run BabySitter.bat` runs the source tree. A git pull updates that.
`dist\BabySitter.exe` is one file. A pull does not replace it.
`scripts\build-exe.bat` rebuilds it. `scripts\desktop-icon.bat` points
a shortcut at `dist\BabySitter.exe`, so that shortcut follows a
rebuild. A copy of the exe sitting on the desktop stays on the old
build until that file is replaced. Settings, memories, the journal,
and pins stay in `%LOCALAPPDATA%\BabySitter`.

`Setup.bat` makes the virtual environment and installs the libraries.
Python 3.12, the Ollama installer, and the NVIDIA driver stay manual.
After a yes, setup asks Ollama to pull `qwen3.5:9b` and `gemma4:12b`
only. Voice files and the sharper memory each wait for their own yes.

On `main` at 0.17.4, Check for an update looks at GitHub releases and
does not download an installer. Installing from inside the app is the
open pull request for 0.18.0. There is no code signing.

## Git, in one place

Work is merged on Origin `michele-de-rege/Ai-assistant-Babysitter`.
The public copy is GitHub `Michelederege/BabySitter_Ai_Assistant`.
The capital M in that GitHub name is part of the update URL. Agents
do not push the `github` remote and do not force-push. On his PC,
after a merge: `cd C:\BabySitter`, then `git pull origin main`, then
`git push github main`.

One branch, one pull request. A pull request aimed at a branch that
already merged does not land. Make a new branch off `main`.

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
| Babysitter app improvements | Review through 0.17.4, then in-app update | [#31](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/31) merged, [#32](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/32) open |
| Ai assistant | A greeting only | none |
| Summarize prior chat transcript | Empty, and it ended in an error | none |
| Summarize prior agent claims | An audit of one night. The tree has moved on | none |
| Hunt voice and power bugs | Internal hunt, no product decision | none |
| Hunt logic bugs | Internal hunt, no product decision | none |
| Hunt UI bugs | Internal hunt, no product decision | none |

One warning from those hunts is still in the code. Game detection
skips a path when any folder contains a word such as `setup` or
`directx`. A real game under `steamapps\common\TheSetup\` is missed.
Treat the rest of those hunt lists as stale until the code shows the
same bug.
