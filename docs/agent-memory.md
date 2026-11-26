# BabySitter, for a new developer

This is the record of the project through 26 November 2026. It was
checked against `main` at version 0.19.1. Read this file, then the
code. Do not reopen a Cursor chat to recover a rule. The requests
from those chats are copied below. A decision in the sections before
the chat log wins over an older request.

If this file and `docs/conversation.md`, `docs/voice-and-efficiency.md`,
`docs/2026-11-agent-review.md`, or the folder list in CONTRIBUTING.md
disagree, this file is the one to follow, then the code. Those other
files keep the research. CONTRIBUTING.md still describes the first
phase. They are not the current rules.

## What it does

BabySitter is a voice assistant for one Windows PC. Michele talks, it
talks, and a frog on a lily pad shows whether it is off, listening,
thinking, speaking, in a game, or waiting for a yes. It is not a chat
window. The AI starts off. A reminder still counts down and rings
while the AI is off, as long as the app is open, including in the tray.

Short requests stay on this PC and do not load a model: the clock, a
timer, a reminder, a goal, the journal, a file search, a PC scan, and
a read of mail, calendar, Drive names, school Gmail, or Blackboard.
Anything that leaves the PC waits for a yes. The model's words become
speech and text. They do not run a tool and they do not run a command.

The project folder on his PC is `C:\BabySitter`. Python is
`py -3.12`. Commands he runs are PowerShell. Work is merged on Origin
`michele-de-rege/Ai-assistant-Babysitter`. The public copy is GitHub
`Michelederege/BabySitter_Ai_Assistant`. The capital M in that GitHub
name is part of the update URL.

## Key decisions, and why

### The PC

His machine is a Ryzen 9 7900X, an RTX 4070 with 12 GB of video
memory (the driver reports about 12,282 MB), and 32 GB of RAM. In
Git Bash the folder is `/c/BabySitter`. `/mnt/c/BabySitter` is not
that shell. `cd /d` is Command Prompt. PowerShell reads `/d` as a
path and the command fails, which is why AGENTS.md exists.

The UGREEN DXP4800 Plus does not run the models. It is a low-power
CPU with 8 GB of RAM and no CUDA. It can hold copies of model files
and of `%LOCALAPPDATA%\BabySitter`. Inference, faster-whisper, and
Kokoro stay on the Windows PC. Ollama stays on `127.0.0.1:11434`.
BabySitter refuses to turn on if Ollama is listening on the network.

A five-node Raspberry Pi K3s cluster was named as a later idea. The
app does not run there. A review looked for a real job for the
cluster and did not find one that belongs in this app.

### Models

Only one model is loaded. Layers stay on the graphics card. Moving
them into system memory was turned down because replies get slow and
BabySitter would unload the model. The app starts on Medium.

Low is `qwen3.5:9b`, 4,096 tokens of context, batch 256. The Q4
weight file is 5.6 GB. A normal load is about 6.5 GB once the cache
and the CUDA runtime are counted. The goal was 4 to 6 GB. Cutting
the context to 2,048 was rejected because a screenshot and a tool
reply no longer fit, and this model's cache barely shrinks when the
context is cut. A 3B or 4B model was rejected because it drops mail,
calendar, and a request with more than one step. The older "4 to
6 GB" and "5.4 GB file, 5.7 GB load" lines were for a smaller file.

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

### What a reply is allowed to do

`shell=True` stays out of the source. A search that leaves the PC,
and deleting a saved key or token, still ask first. Looking at the
screen, saving a reminder, and saving a fact do not ask a second
time. The sentence already said is the yes. Undo lasts 10 seconds.

Google mail, calendar, and Drive file names are read-only. Nothing
is sent, nothing is deleted, and nothing is uploaded. The token is
encrypted in its own file, not in `settings.json`. A second sign-in
stores a school Google account in a different file. New mail and
events are checked about every 15 minutes, and only while the AI is
on. A Google Doc in the front window is read as plain text into the
local question. The browser name in the title is ignored, so
DuckDuckGo counts. A doc changed in the last two hours counts too.
Say "look up" to search, after a yes. A credit line uses only a
source that was returned. The file itself is not downloaded.

Blackboard is the calendar feed the school gives you, not a Google
account and not a course login. The link is encrypted and is refused
if it points at this computer or at a numeric address. Comment links
are TikTok or Reddit. A YouTube link is not sent through the Reddit
comments search. The larger public-research recipes (outlier posts,
comment themes, trends, and the rest of that list) are in the app
and still ask before they run.

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
brings the model back. Automatic game mode is on. A program running
from Steam, Epic, GOG, the Xbox app, Riot, or a folder named Games
counts. Launchers and installers do not. A game installed somewhere
unusual still needs its name in the list.

### Voice

Kokoro is the spoken voice, shown as Heart and Sarah. If it is not
on the PC, speech falls back to the Windows voice, and a reminder
can speak while the AI is off. Vosk only notices the wake words.
Whisper small on the processor reads the question, including a
keyword clip, so Hold Talk and a wake-word command share one ear.
The chat model keeps the graphics card. Moonshine streaming hearing
was researched and not built. There is no voice cloning.

A missing file inside `BabySitter.exe` must leave that feature off.
It must not close the window. The exe does not install Python
libraries into itself. That starts another copy of the window.

### How the program is opened

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

On 0.18.0 and later, **Check for an update** and **Update BabySitter**
pull `origin/main` when the git folder is on the PC, rebuild the exe
when one is in use, and restart after a confirm. On a PC with no git
folder they use a GitHub release file and check its SHA-256. Nothing
is signed. The first time onto 0.18.0 still needs one pull and one
`scripts\build-exe.bat` on the PC. After that, the window can do it.

### Git, in one place

Agents do not push the `github` remote and do not force-push. On his
PC, after a merge: `cd C:\BabySitter`, then `git pull origin main`,
then `git push github main`.

One branch, one pull request. A pull request aimed at a branch that
already merged does not land. Make a new branch off `main`. Five
simulations for every feature, not five simulations for the whole app.

## What's finished

Version 0.19.2 is the current app. The story of each version is in
CHANGELOG.md. These are in the program now:

- Power, the frog orb, the rail, Home, and the pages for Schedule,
  Journal, Files, Voice, Memory, History, Screen, Tools, PC Health,
  Models, and Settings.
- Low, Medium, and High, one model at a time, on the graphics card.
- Keyword listening, Hold Talk, Heart and Sarah, and the Windows
  voice as the fallback. Reminders speak with the Windows voice
  while the AI is off.
- Reminders with a countdown, timers, goals, pins, a day journal,
  file search, and a sharper memory that matches meaning on the
  processor after its own download.
- A PC scan that names one thing and waits for yes or no.
- Read-only Gmail, Google Calendar, Drive file names, a second
  school Google account, a Blackboard calendar feed, and the plain
  text of the Google Doc in front, including in DuckDuckGo.
- Public social and web search, off until a yes. Ad libraries stay
  refused.
- One movable `dist\BabySitter.exe`, `Setup.bat` for a GitHub visit,
  and an in-app update that fast-forwards Origin `main` or installs
  a checked GitHub release.
- Automatic game mode, with a hand switch and two Settings switches
  that turn the automatic path off.

## What's in progress

No product change is open. Pull requests 1 through 36 are merged.
The last product chat ended by asking how the unfinished ideas could
fit with what already works. That was a brainstorm. None of those
ideas were started. This file is the documentation that chat's
author asked for so another model can review the project without
the Cursor sidebar.

## Known bugs

Two leftovers from the bug hunts are still in the code. They were
checked again on 26 November 2026.

- Game detection skips a path when any folder contains a word such as
  `setup` or `directx`. The test is a substring of the whole path,
  not the file name alone. A real game under
  `steamapps\common\TheSetup\` is missed. `src/babysitter/games.py`,
  `looks_like_game_path`.
- Kokoro, Silero, and the sharper-memory download return early when a
  non-empty file is already on disk, so that file never gets the
  SHA-256 check. A new download is checked. See `_fetch` in
  `src/babysitter/plugins/voice/kokoro_voice.py`, `download_silero`
  in `silero_model.py`, and `download_embedder` in `embedder.py`.

The rest of those hunt lists were written against older trees. Treat
them as stale until the code shows the same bug.

## Next steps

These were asked for or recommended, and they are not in the app.
They are a review list, not rules. Building one of them needs a new
decision. The 26 November brainstorm asked how they could work with
the features that are already finished. It did not choose an order.

- Moonshine streaming hearing, and the Parakeet, Piper, and
  Supertonic voices that were compared and not chosen.
- Speech-to-speech, voice cloning, and a cloud realtime voice.
- A named personality, such as "be Brook". A rating can already ask
  the next session to be shorter, longer, warmer, or cooler. That is
  not a named personality.
- Code signing.
- Encrypting History and saved facts the way API keys are encrypted.
  Those files are still plain JSON.
- Hash pins on `requirements-voice.txt`. The runtime list pins
  versions. It does not pin every file's hash.
- Switching Medium to `bonsai-2:27b` after a benchmark.
- A llama-server backend, and removing PyTorch.
- Weather, Home Assistant, and music tools.
- Mail or calendar alerts while the AI is off. The 15-minute check
  runs only while the AI is on.
- A school mailbox that is Microsoft 365. School Google (Gmail) is
  a second read-only sign-in. Blackboard is the calendar feed.
- Downloading a Drive file, or reading a Word file on the PC. A
  Google Doc is plain text only.
- A smooth context slider instead of Low, Medium, and High.
- Waking the model when a watched game closes. Game mode leaves the
  model unloaded on purpose.
- Refreshing an expired Google sign-in off the window's thread. The
  inbox, "read my draft", and the 15-minute check still refresh it in
  `_token_for_google` on the window's thread, so about once an hour the
  window can pause while Google answers, up to 8 seconds per account on
  a bad connection. The jobs in `shell.py` would need the vault instead
  of the token.
- Running BabySitter on the Raspberry Pi cluster.
- Publishing the Inno Setup installer from GitHub. A tagged release
  builds the portable `BabySitter.exe` and `SHA256SUMS.txt`.

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

## Chat requests

These are Michele's requests, in the order the chats started. Spelling
in the requests is smoothed so a new reader can follow them. The
meaning is his. Times are America/New_York. A pasted command log is described instead of
copied when the log is only pip output. Cursor's own "fix the
selected merge conflicts" and "a subagent finished" lines are noted
in one sentence, because they are not product requests. Internal
hunts that an agent started on its own are listed at the end. They
did not add a product rule beyond the leftovers above.

### System performance and features

14 November 2026, 2:23 AM. [Chat](https://cursor.com/agents/bc-01a1d8f0-2ba0-759e-be12-7639f41b7a5d).
Pull requests [#1](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/1),
[#2](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/2),
and [#3](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/3),
merged. This chat set the hardware budget, Google, the scan, and the
voice rules.

> First I would like you to make a checkpoint of some kind to ensure if the code goes bad we can revert. I'd like you to go through the code optimize everything you can. Do a deep research on how you can make this run on as little gpu power as possible without destroying functionality. My goal is to lower the low setting to 4-6 gb. Then I want you to add all features planned for implementation.

> Now I would like you to ensure that we have the most effective models for our purposes. I need something that can utilize Google accounts, emails, calendar notifications. Then I'd like you to do a full analysis to ensure we have the most effective models possible. Do deep research relating to flowing conversation with ai. Then do a bug test, see how low is possible without wrecking functionality, run simulations based off my pc specs. I want to be able to have comfortable conversations not weighed down by overly uncomfortable confirmation. I also would love to have a feature that scans my pc/applications and makes suggestions on how I can optimize. Then I can use the voice control to either say yes to the individual requests or deny them.

> Are there any other features we have yet to add?

> Okay so can we implement these features?

> Does this now have a launchable desktop application I can just click?

> And is the icon the same as the Claude designed icon I sent?

> How do I implement these changes? Also the application runner is not working.

> So for one the voice is not functioning as intended and for two it can't do basic hardware scans, which was one of the goals for this project. All I did was run it from the Run BabySitter application. I'd like you to go through simulations of utilizing the voice in order to see where the errors are happening.

> Always give me the full cd command.

> Fix this code. I can already tell it's not going to function as intended. Utilize past chats to recognize exactly what is wrong.

> I'd like to know what AI model included in Cursor would be best for this project.

> C:\BabySitter is the path. Please fix this cd request.

He then pasted a Git Bash session. `cd /d C:\BabySitter` failed
because that flag is Command Prompt, and the shell was not inside
the git folder. He wrote: "this is completely failing to upgrade.
Take your time and figure out why."

### AI context and git issues

14 November 2026, 3:06 PM. [Chat](https://cursor.com/agents/bc-5e1df152-bb60-4028-80ce-1687a24d6bf6).
Pull requests [#4](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/4),
[#5](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/5),
and [#6](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/6),
merged.

> The system performance and features chat is failing to find the errors, which makes me question all the work it's completed. I would like you to verify everything and ensure that the AI has not been contaminated by context rot. Also figure out what's wrong with this code posted in this chat request.

The paste was Git Bash. `cd /mnt/c/BabySitter` does not exist in that
shell. `cd /c/BabySitter` is the folder, and the fetches failed until
he was inside it.

> Can you run 5 simulations of this program using all of the features included in order to spot areas that could be improved, putting less strain on the computer? Pay special attention to the received voice accuracy, speed of replies, accuracy within speech, and delivery of information. I also would like you to see why my RAM would be spiking to 20+ usage. I think an AI agent is still running in the background even after I close the program, which should never happen. All AI agents should be turned on and off with the program.

> It was supposed to be 5 simulations for each feature, not 5 features.

### NAS for the DXP4800 Plus

14 November 2026, 5:38 PM. [Chat](https://cursor.com/agents/bc-f9f82b5c-1176-450b-b53c-5fa7b72c1e73).
Pull request [#8](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/8),
merged.

> Would a NAS be helpful to assist in the load of this AI agent, or is it not worth the trouble? DXP4800 Plus.

> I would like to upload this to GitHub: https://github.com/Michelederege/BabySitter_Ai_Assistant. Look how we have successfully done this before.

### Agent efficiency and security

14 November 2026, 5:47 PM. [Chat](https://cursor.com/agents/bc-b25afb2b-8dd8-4732-b359-aef860334397).
Pull requests [#7](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/7),
[#9](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/9),
[#10](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/10),
[#11](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/11),
[#12](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/12),
and [#13](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/13),
merged. This chat produced the November review, the journal, file
search, sharper memory, AGENTS.md, and the v2 window.

> I would like you to do a pass over on the goals and abilities of this AI agent, do deep research on how we can improve its efficiency and usage, and whether or not we have chosen the best most efficient agents to work and complete the goals of this assistant. Also pay attention to potential security risks.

> Okay so these changes will make it more efficient, but will it impact usability?

> Okay then let's push this all out so I can test it on my own. Also can you think of any UI changes that could make this feel less cluttered? Or should I ask another agent?

> How do you think this could be improved to be the best most versatile personal assistant? Also I would like game mode to be enabled as soon as a video game is open. I'd like the ability to turn it off and on, but it should just automatically register it as a game that has been opened so game mode has switched.

> These are excellent suggestions. For suggestion 2, if I was to say pull up current tax pdf, would it pull up the latest tax pdf opened? And if I didn't remember the full name of a file, let's say it's an STL, could I just say find all STLs? Or if I said the first portion of the file and not the full name, would it pull up a full list of possible matches or would it return with an error? For suggestion 3, how can we make memory that actually remembers and also ensure that it is not a security risk or weighs down the AI? One more idea I still haven't seen but really like is some kind of way to see what I did each day, what tasks I worked on, goals I accomplished, nothing hyper specific that would be a security risk, but enough that I would know what I did and the time I spent on it.

> Okay let's get these implemented.

> I'd like you to do a once over just to make sure it's stable, not too intensive, easy to use, and secure.

> Now do one more bug test run.

> Now do an in-depth bug test top to bottom. How fast you found those bugs makes me think there's more we aren't seeing until we dig.

> Do you think it would be beneficial to run another bug run? If so do it. If not I'll start my end testing.

> Alright let's push out these changes. I would also like to build an application I can click. Build an exe I can use as a shortcut. Also give me the full commands to push these uploads.

> This is the path C:\BabySitter.

> Okay look at how successful pull requests have been made and fix these, because these don't look right at all.

> Yeah so I don't know what's with the `cd /d C:\BabySitter`, because I had to remove the `/d` in order to fix the path. You are not the first agent to do this, so I'd like you to make a note of that.

> Okay so I pushed both codes. Am I able to now use my application from the same folder? Is that the updated version?

He then pasted a PowerShell session. `pip install -r requirements-dev.txt`
failed in hash-checking mode because `colorama` was not pinned, so
PyInstaller never installed. He wrote: "I don't get it. Is this up
to date?"

> I'd like to redesign the UI. Create a prompt, not about design, just about what a UI would have to support.

> BabySitter-UI-v2.zip and Babysitter — Voice Assistant UI.html. This is the new UI. Implement it and make sure it's working.

He then pasted a checkout of `cursor/ui-v2-redesign-4397` where
`.venv\Scripts\python -m babysitter` said there was no module named
babysitter.

### Agent chat integrity

15 November 2026, 12:54 AM. [Chat](https://cursor.com/agents/bc-a2d819a6-8e7d-404a-bcb1-a4c7fed2a465).
Pull requests [#14](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/14)
through [#22](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/22),
and [#25](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/25),
merged. Listening layout, reminders, pins, the conversation after a
local answer, the desktop icon, and a glitch pass.

> Okay so I think the Agent efficiency and security chat became too rotted. Please review the fixes and implementations made in that chat and make sure they are working as intended.

> So I'd like you to go through and verify this, fix any bugs, and tell me what happened to the listening mode.

> Okay so it can't perform the most basic of requests and it's using around 8 GB of my GPU instead of the promised 5-6, so what's going on? And the voice is slow and unnatural. Also the whole thing crashed when I asked it to read out my history.

> Okay now go through every feature using simulations and ensure that they are working as intended.

> Also there is no way to manually pin anything to the pinboard. There is no reminder tab, making the reminders unviewable, and the voice still seems to lag after it gives its initial statement. I want to optimize this app. The voice sounds robotic and unnatural and the goal is for it to emulate a human talking. I also need its efficiency to go up. Also I should have the ability to override game mode manually, although it should still take effect automatically, or ask if you want to switch to game mode. The goal was 6 GB for Low. Is that even possible? I'd like you to do deep research for this and make improvements without gutting what still functions.

> Now do a deep dive into the code and look for bugs, coding errors, counterintuitive code. We are looking for every bug possible. I don't want changes to impact usability we have built so far, but the smoother, faster, and more efficient it runs the better. And do a deep dive into how we can make AI conversations more seamless and natural.

> I want to set up a schedule addition. I also would like to be able to pin things by clicking a little pin icon of some kind. Also when I say set a timer this should tell it to set a reminder. How do the reminders actually work? Does it send a notification? What does it do? Everything on the tabs list should be available to pin.

> Also reminders should go off even if the AI is off.

> If I set a reminder I'd like a timer on the reminder until it goes off to be visible. Let's update the GitHub page also.

> So I ran the exe command. Where is the exe?

> But the app cannot be moved from the actual folder. Does the app update with the git pushes, or can it be updated at all? The point is to be able to move it to the desktop.

> Okay so how can we make it so the icon becomes the one that can be updated, the BabySitter we created with the exe?

The chat then asked Cursor to fix two selected merge conflicts, and:

> So can you just retarget it and then make sure we didn't just go backwards in the app's development?

> Okay merge everything.

> Why can pull 22 not merge? I got an error.

> Okay now with all these merges, status of the application: did we lose anything? Have we gone backwards? And can we push out the newest version to my PC and GitHub?

> I set up an SSH key so now my PC is connected to git.

> I'd like you to go through this project and look for any issues or glitches.

> So are these fixed?

> So let's fix these.

> Now is the application easily updatable, like in Settings it can see if there are any new versions to use?

### Application setup and packaging

16 November 2026, 10:13 AM. [Chat](https://cursor.com/agents/bc-4c30abeb-9db7-4229-8c7f-fbb7b506488d).
Pull requests [#23](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/23)
and [#24](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/24),
merged.

> Can people use the BabySitter GitHub to download everything? What would a setup wizard need in order to download everything? I also want it easy to make an exe that someone can move to their desktop, out of their folder, without it breaking. Ensure it's easy to set up if you are just visiting my GitHub.

> What would the UI need if we had a setup wizard that could actually create a working exe?

He attached `BabySitter-UI-v2 (3).zip` and `hero_banner.py`.

> Okay now that it's merged, let's push it out to my version and GitHub.

### AI assistant

16 November 2026, 3:50 PM. [Chat](https://cursor.com/agents/bc-c1e40509-bba3-4947-9ee8-0e2a7a3b1651).
No pull request.

> Start this project.

### Plus sign location

20 November 2026, 6:37 PM. [Chat](https://cursor.com/agents/bc-2bcc157d-19ba-410a-b3b9-1e41fa9d3ae2).
Pull requests [#26](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/26)
through [#29](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/29),
merged. Broader voice commands, goals, the shared ear, and the packed
keyword libraries.

> I'd like you to go through the current application and do an in-depth bug check.

> Now I would like you to expand the voice command capabilities and create a better recognition pattern.

> I also want you to do this same thing, but I want to add a goals list of sorts. I mention "say my goals" and they get shown visibly. This can show up on the reminder tab. Go through and make sure this feels natural, and follow up with the expanded voice commands and all other bugs found when running this in simulation. Natural flow of conversation is the goal.

> Now how could we give the model its own personality?

> I'd like you to do deep research on how any of the application's processes could be improved. I also want you to take a deep look at how we can improve voice recognition and command versatility.

> Alright let's now implement everything we can.

> Now look for any improvements or "this just makes sense" fixes and push those out.

> Give me the commands to push this to my version.

> I want to update the files that are on my folder, my version of BabySitter.

> So something is clearly malfunctioning.

> I'd like you to look through the code and look for stability fixes. This seems to crash when it receives too many manual inputs at once.

### Project bug investigation

26 November 2026, 1:03 AM. [Chat](https://cursor.com/agents/bc-77feaa11-4567-4120-9786-750681b3a5ba).
Pull request [#30](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/30),
merged. A missing packed voice file must not close the window.

> This is a great project but I have been running into some very real issues. I'd like you to investigate these bugs, how they have slipped through the cracks, and look for more bugs.

### BabySitter app improvements

26 November 2026, 1:32 AM. [Chat](https://cursor.com/agents/bc-93ddf91b-e114-4ffb-8104-1b0178c37c38).
Pull requests [#31](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/31)
through [#36](https://cursor.com/codebase/michele-de-rege/Ai-assistant-Babysitter/pull/36),
merged. The 0.17.4 review, the in-app updater, this memory file's
first version, Gmail, Calendar, Drive, school Google, Blackboard,
and the Google Doc in the front window, including DuckDuckGo.

> Review my BabySitter application from top to bottom and fix what you find. Work through these areas: bugs and errors; unfinished or forgotten features; performance and efficiency; assistant conversation quality; building the exe and accessibility. The exe build is broken. Fix it so the app builds and launches reliably on Windows. Also make sure the app is easy to open and use, including keyboard navigation, readable text, and clear labels. If you spot other improvements worth making, suggest them. When you're done, give me a list of every issue you found and what you changed, anything you couldn't fix and why, and your top suggestions for what to improve next. Take into account my Pi cluster build and see if there is a potential utilization of this for this project that's meaningful.

> I want to make sure that I can update the application from within the software so I don't have to do push commands to make sure it's up to date.

> Do I need to pull this, or am I good to open the application?

> There are so many chats within this repo. I would like to condense them, without losing the valuable information within them. I fear that having so many chats confuses models and makes info hard to find. I'd also like you to note the chats disagree with each other on a few rules. Check the code so the condensed note matches what the app actually does now, so that I can go through them later and see if there are any missing implementations.

> I'd like you to then print a list of all the current capabilities of this application.

> So the main problem I see is that I cannot link this to Gmail, Google Calendar, Google Drive, my school email, Blackboard. In order for this to be a true assistant it needs to be able to view and display information reliably.

> So why is Drive blocked?

> I would like it to be able to see my Drive, a document I would be writing in at the time. This is so when I'm writing things, I can ask the AI questions relating to the paper, and it would be able to help, i.e. look things up, make suggestions, and be able to format used information into a format in order to credit where the info came from, on how to strengthen my writing.

> So the thing is that I use a browser called DuckDuckGo. How can we make this work?

> I would like you to list the current capabilities and the unimplemented ideas right now.

> I'd also like you to look for things that contradict each other, basically things that are currently in the application but cancel each other out.

> So let's brainstorm how we can make all the current application abilities work together, make the current capabilities more effective and versatile, and how we can insert the unimplemented ideas.

The unimplemented list he pasted in that last request is the next-steps
list above, plus the two known bugs.

### Actions since the 21st

26 November 2026, 2:40 PM. [Chat](https://cursor.com/agents/bc-edf77c9f-ec5d-4cfc-abaf-8363db16e574).
No pull request. He asked to delete that chat only, not the
repository.

### Claude, for a review of this project

26 November 2026, 4:22 PM. [Chat](https://cursor.com/agents/bc-7bec3376-cace-4281-9181-05cae96f9ad1).
This file.

> I have Claude Code premium. How can I add this to Cursor so I don't have to pay extra to use Opus 5.5?

> I just want to be able to use Opus in Cursor. I have Claude Code, but I cannot find the extension page. The shortcut keys didn't work.

> Honestly all I need is for Claude to be able to review this project and the chats relating to this project.

> Write a file docs/agent-memory.md that summarizes this project for a new developer: what it does, the key decisions we made and why, what's finished, what's in progress, known bugs, and next steps. And include chat history and chat requests for everything on this project.

### Internal runs

These were started by an agent, not as a new request. Their findings
are already in the decision sections and the two known bugs. One of
them, "Summarize prior chat transcript", ended in an error and added
nothing. "Summarize prior agent claims" audited one night. The tree
has moved on.

| Run | What it was |
| --- | --- |
| [Hunt voice and power bugs](https://cursor.com/agents/bc-60bbaadf-b2f3-5bf6-b59f-95890a4dad17) | Internal hunt. The SHA-256 skip is one leftover |
| [Hunt logic bugs](https://cursor.com/agents/bc-249f8053-e6f4-59e3-a641-bb8c317e8255) | Internal hunt, no product decision |
| [Hunt UI bugs](https://cursor.com/agents/bc-8e4b27cc-f394-5204-ab99-27eac5d5571b) | Internal hunt. The Escape bug in it is fixed |
| [Digest early BabySitter chats](https://cursor.com/agents/bc-5051d541-96d0-52d5-ab8b-37de0ad56164) | Read the early chats into the first memory file |
| [Digest packaging and publish chats](https://cursor.com/agents/bc-f431b325-ee00-5e77-b509-d000e7006177) | Read the packaging chats into that file |
| [Digest research and review chats](https://cursor.com/agents/bc-42b7b8ea-698b-5e5e-98de-3e1dbf81581c) | Read the review chats into that file |
| [Digest voice and bug chats](https://cursor.com/agents/bc-955f1e27-b7f5-5729-a83c-65234915fc57) | Read the voice chats into that file |
| [Digest internal bug-hunt chats](https://cursor.com/agents/bc-69b7341a-8473-5d98-b0f9-cfa9541a3dc0) | Read the hunts into that file |
| [Extract early chat decisions](https://cursor.com/agents/bc-668d2dcb-1997-57f5-8807-4fdcbae4d3b5) | A second pass on the early chats |
| [Extract voice and security decisions](https://cursor.com/agents/bc-4e088c4d-f47b-59d8-948b-daeb4dff0b09) | A second pass on voice and security |
| [Extract bug-hunt leftovers](https://cursor.com/agents/bc-8b9d18f6-1306-56de-b78f-d4f3fb118b67) | A second pass on the hunts |
| [Summarize prior agent claims](https://cursor.com/agents/bc-4dbce3fd-f1b8-5d9b-8fcf-62b9801007d6) | An audit of one night |
| [Summarize prior chat transcript](https://cursor.com/agents/bc-3d17def5-de44-5897-a0d0-fecf19af2e91) | Empty, and it ended in an error |
| [Check Cursor docs on deleting chats](https://cursor.com/agents/bc-164c784e-ccdc-5e64-bc22-4639cd918d2e) | Looked up how to delete one chat |
