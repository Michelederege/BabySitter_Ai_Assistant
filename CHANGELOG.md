# Changelog

BabySitter uses version numbers like v1.2.3. The voice loop is not in yet.

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
