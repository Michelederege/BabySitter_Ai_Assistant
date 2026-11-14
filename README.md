# BabySitter

BabySitter is a voice assistant for your Windows PC. You talk, it talks, and a small light on the screen shows what it is doing. It is not a chat window.

**This build is Phase 1 only.** It is the power switch, the little floating light (the orb), and a status board. It does **not** listen to the microphone yet. Nothing is listening when you open it. The AI stays off until you turn it on.

The window icon is a placeholder: the letters **BS** on a teal circle. Your own artwork can replace it later.

## What you need

- Windows 11
- Python 3.12, only if you are running from this folder (the installed `.exe` will not need Python)
- [Ollama](https://ollama.com/download), already installed, serving `http://127.0.0.1:11434`
- An NVIDIA graphics card, and the NVIDIA driver (that driver includes `nvidia-smi`)
- The model `qwen3.5:9b` already downloaded in Ollama

Your PC (Ryzen 9 7900X, RTX 4070 12 GB, 32 GB RAM) is enough. Only one model is loaded at a time.

## Run it from this folder

Do this once:

1. Install Python 3.12 from [python.org](https://www.python.org/downloads/windows/). On the first screen, check **Add python.exe to PATH**.
2. Open this folder in File Explorer.
3. Click the address bar, type `cmd`, and press Enter. A command window opens in this folder. That window is only for setup.
4. Copy these two lines, one at a time:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

The second line can take a few minutes. It downloads the window toolkit. The versions are pinned, with a checksum on every file, so you get the exact files this project was tested with.

Then, every time you want to open BabySitter:

- Double-click **`Run BabySitter.vbs`**.

A black command window should not stay open. You should see a dark window titled BabySitter, and a small circle (the orb) near the bottom-right of the screen.

If nothing appears, double-click **`Show errors.bat`**. A window will stay open. Copy **all** of the text and send it to me.

![Home, with the AI off](docs/phase1-home.png)

The picture above was taken on a computer that does not have Ollama or an NVIDIA card, so it shows those two warnings. On your PC the red line names your Ollama version (or stays hidden if it is 0.17.1 or newer), and the video-memory card shows the RTX 4070.

![The orb, off](docs/phase1-orb.png)

## What you should see

- The window opens **compact**. Press **Expand** for the full Home screen and the tabs.
- The power mark says **Off**. Its color is grey. The orb is grey too.
- The words under it say the next click. Nothing is listening.
- Video memory, CPU, and RAM refresh every 2 seconds once the full window is open.

Colors, on the button and on the orb:

| Color | Meaning |
| --- | --- |
| Grey | Off |
| Yellow | Working (starting or stopping) |
| Green | On. Listening, Thinking, and Speaking stay green and change the motion. |
| Blue | Game |
| Red | Needs you. Read the reason. |

The window opens compact: power, Normal/Game, and one status line. **Expand** opens the tabs. Orange buttons are actions. The other colors are only for those states.

**Choose my picture** on Home copies a photo into your BabySitter folder. It is not uploaded. Leave social search off when the information is confidential.

## Try the power switch

1. Click the power mark. It turns yellow and says Working. BabySitter starts Ollama with **no** command window, then loads the model for the current level. Medium, the default, loads `gemma4:12b`. Low loads `qwen3.5:9b`. The first load can take a minute.
2. When it works, it turns green and says On.
3. Click it again. It unloads the model and stops Ollama. The message should say that nothing is listening on port **11434**, and it should tell you the video-memory numbers.
4. Press **Ctrl+Alt+F12** from anywhere, even if the window is hidden. That is the emergency stop. It turns the AI fully off. **Ctrl+Alt+F11** turns it back on. You can change both keys in Settings.
5. While the AI is on, click **Switch** under Game mode. The model unloads so a game can use the graphics card. Ollama stays running with nothing loaded. Click **Switch** again to load the model.
6. Close the window with the X. The app stays in the tray (the little BS icon by the clock). Right-click that icon, or the orb, for the same power commands. **Quit** is how you actually exit.

Start with Windows is **off** unless you check it in Settings. Even if you turn that on later, the AI still starts off.

## Intelligence: Low, Medium, High

Only one model is loaded at a time. Switching levels unloads the one that is in memory first.

- **Low** is `qwen3.5:9b` with 4,096 tokens of context. Brief replies, tools, and pictures stay. It aims for 4 to 6 GB of video memory. On this 12 GB card the Q4 weights themselves are about 5.4 GB, so a normal Low load is about 6 GB. BabySitter does not push layers into system memory to chase a smaller number.
- **Medium** is `gemma4:12b` with 8,192 tokens. This is the everyday default.
- **High** is the same writing model with 16,384 tokens. It loads only when the card has room.

If the AI is already on when you change this, click **Reload the model with this setting**. The model card tells you if the model is 100% on the GPU. If Low reports more than 6 GB, the model file is larger than the goal and the context is already as small as the pictures allow. If you start Ollama yourself, quit it from the tray so BabySitter can start it with the smaller q4 cache.

A look at the screen uses the model that is already loaded, shrunk so it fits that level. You do not get a second confirmation after you ask. `qwen3-vl:8b` is optional and is not loaded for that look.

## Your files

Everything you save goes here:

`%LOCALAPPDATA%\BabySitter\`

That is usually `C:\Users\YourName\AppData\Local\BabySitter\`.

Settings has a button that opens it. Updates and reinstalls replace the program, not this folder. The program folder and this project folder are not where your settings live.

`settings.json` has a `schema_version`. When a future update needs a new shape, BabySitter rewrites the file for you.

## Build the windowed program (no Python window)

Do this on Windows, after the steps above work:

1. Double-click `scripts\build-exe.bat`

   Or, in the same command window as before:

```bat
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m PyInstaller packaging\babysitter.spec --noconfirm
```

2. Open `dist\BabySitter\BabySitter.exe`.

That file is built with no console. Double-clicking it should show only the BabySitter window. It must not open Command Prompt or PowerShell. Ollama, `nvidia-smi`, and any later helper are started the same way: no console window.

The optional installer needs [Inno Setup 6.3 or newer](https://jrsoftware.org/isdl.php). Open `installer\BabySitter.iss` and choose Compile. You get `dist-installer\BabySitter-Setup-0.1.0.exe`, with a desktop shortcut, a Start menu entry, and an uninstaller. A silent install (for the future updater) is:

```bat
BabySitter-Setup-0.1.0.exe /SILENT
```

The installer does not delete `%LOCALAPPDATA%\BabySitter`. The uninstaller asks before it deletes that folder. A silent uninstall does not delete it. Ollama and its downloaded models are never removed.

## If something goes wrong

Send the exact text, not a summary. The best places to copy from:

- The **What just happened** box on Home
- The message under the power button
- `Show errors.bat`, if the window never opens
- The log folder, from Settings → **Open the log folder**

Logs do not contain conversations. Phase 1 has no conversations.

## Choices made in this phase

These are on purpose. Say if you want one of them changed.

- The personal folder is `%LOCALAPPDATA%\BabySitter\`, not `AIControlCenter`. The name is decided, so the folder should match it.
- **Game mode** unloads models but leaves the Ollama program running, so waking the model is faster. **Off** stops Ollama completely. If Ollama's own tray app would restart it, BabySitter asks before closing that app. Emergency stop closes it without asking, then tells you that it did.
- After a watched game closes, BabySitter **stays** in game mode. It does not load a model by surprise.
- Automatic game mode is off until you add a program name (for example `bg3.exe`) and check the box. It compares the file name only. It does not read game memory and does not draw anything inside a game.
- The app itself runs at below-normal priority so it is less likely to steal frames. Ollama stays at normal priority so a reply is not sluggish. Replies are not in this phase yet.
- Low is `qwen3.5:9b`. Medium and High are `gemma4:12b`. Only one model is loaded. A second model would have to kick the first one out.
- Mouse side buttons cannot use the same safe keyboard method (`RegisterHotKey`). Push-to-talk is Phase 2. If you want a mouse button then, it will be off whenever the AI is off, and off in game mode, so it does not get in the way of a game.
- The orb starts above other windows. You can turn that off in Settings, and you can drag the orb.

## Google mail and calendar

This is off until you turn it on. It reads your own Gmail and Calendar. It does not send mail and does not delete mail.

1. Open Tools.
2. Check **Turn on Google mail and calendar**. Until you do, nothing is sent to Google.
3. Paste a read-only token from your own Google account and press **Save token**. On your PC the token is encrypted for your Windows user, in its own file. It is not saved in settings.json and it is not written into the log.
4. Press **Check mail** or **Check calendar**, or say “check my email” or “what’s on my calendar”.

When the AI turns on, BabySitter can speak unread subjects and the next events once. Say the phrase again later to check again.

## Scan this PC

Say “scan my PC”, or open PC Health and press **Suggest changes, one at a time**. BabySitter names one heavy app or one program that starts with Windows. Say yes to do that one, or no, deny, or leave it. The next suggestion follows. Games, Windows itself, and security tools are not closed. Turning a startup item off can be undone within 10 seconds. Closing an app cannot be reopened.

The other PC Health button only reads. It does not change anything.

## Social search

The Tools tab can search public posts. It follows the same public data API as the skills in https://github.com/ScrapeCreators/social-media-research-skills (TikTok, Instagram, YouTube, Reddit, Threads, Pinterest, and public profiles on X).

1. Open Tools.
2. Check **Turn on social search**. Until you do, nothing is sent.
3. Paste an API key from https://scrapecreators.com and press **Save key**. On your PC the key is encrypted for your Windows user. It is not saved in settings.json.
4. Pick what to look up, type the words or paste a public link, and press **Prepare search**.
5. Read the box. It shows the exact words and the address. Press **Send this search** or **Don't send**.

Results list the public text and the link when ScrapeCreators returns one. Each search spends about one credit on your ScrapeCreators account. **Check credits left** asks only for the balance.

This is not the private Ollama chat. The words you type in that box go to ScrapeCreators, a separate company, and only after you press Send. BabySitter does not pull follower lists and does not guess someone's age or gender. The bigger research recipes in that GitHub project (comparing creators, reading ad libraries, and so on) need the talking assistant, which is not built yet. General web search through your own SearXNG is also still later.

## History, web search, and updates

Finished replies are saved under History. Search them, export one, delete one, or type WIPE and press Wipe. They stay on this PC.

Web search uses a SearXNG you run on this computer. Turn it on in Settings and say “search the web for …”. BabySitter only talks to `127.0.0.1`, and it still asks before the query is sent. Public social searches can be spoken the same way, one yes, then a short summary.

**Check for an update** asks GitHub if a newer release exists. It does not download, install, or sign anything. Signing needs a certificate you keep.

Quiet hours, hiding the orb while a watched game is in front, and a mouse side button for talk are in Settings and off. The side button works only while the AI is on, not in Game mode. The intelligence slider snaps to Low, Medium, and High.

## Not in this phase

The updater does not install a release by itself. Code signing is not in this build. Voice cloning, speech-to-speech, and a cloud realtime voice are not part of this project.

## Ideas I have not built

Say if you want any of these in a later phase:

- Hide the orb while a chosen game is in front. That only hides BabySitter's own window. It still would not draw on top of the game.
- Quiet hours, when the AI refuses to turn on.
- Make **High** swap to `gemma4:12b` instead of giving the main model a longer memory. Vision would be unavailable until you switch back.
- A smooth slider instead of the three buttons.
- Wake the model automatically when the game closes.

## Privacy in this phase

BabySitter does not collect usage data. There is no phone-home. With social search and Google left off, it talks only to `127.0.0.1` (this computer). Files, the screen, memory, and what you say to the assistant are never attached to a search. Leave social search off when the information is confidential. The Ollama download page is shown as text when a version is too old. Opening it is your browser, and only if you click it.

If you turn social search on, a search you confirm also goes to `api.scrapecreators.com`. Nothing else is added to that request: not your files, not a screenshot, not what the model said. The key travels with the request and is not printed in the results.

If you turn Google on, a mail or calendar check goes to `gmail.googleapis.com` and `www.googleapis.com`. The request is a read. The token travels in the header and is not printed in the result.

If Ollama is listening on the whole network instead of only this computer, BabySitter refuses to turn on and tells you. When BabySitter starts Ollama itself, it forces `127.0.0.1:11434` for that process.

Ollama older than **0.17.1** has a critical flaw, CVE-2026-7482: a malicious model file can make Ollama leak what it has in memory. BabySitter warns you and asks before turning on.

There is no voice cloning in this project, and there will not be.
