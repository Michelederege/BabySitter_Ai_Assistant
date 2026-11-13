# Contributing

This file is for anyone changing BabySitter later, including future-you. It is written in plain language.

There is one version number. It lives in `src/babysitter/version.py`. The installer copies it. A test fails if the two copies drift apart.

## What each folder is

```
src/babysitter/
  version.py          the only version number
  app.py              starts the program, one window only
  controller.py       the window asks this object to turn the AI on or off
  power.py            Off, On, Game mode, and the checks that follow
  ollama.py           talks only to 127.0.0.1:11434, and starts Ollama with no console
  status.py           video memory, CPU, RAM, loaded models
  settings.py         settings.json, including schema_version and migrations
  hotkeys.py          Ctrl+Alt+F12 and the turn-on key
  winhotkey.py        the Windows call that reserves those keys
  games.py            "is this program name running?"
  audio.py            the microphone hook. Phase 1 does not open the mic
  platform.py         no console windows, low priority, Start with Windows
  security.py         localhost, plus the optional ScrapeCreators host
  secrets.py          Windows DPAPI for the social-search key
  startupcheck.py     Ollama version, and the 0.17.1 warning
  paths.py            %LOCALAPPDATA%\BabySitter
  plugins/voice/      empty socket for voice engines (Phase 2)
  plugins/tools/      social search (off by default). Other actions are still later
  ui/                 the window, the orb, the tray
assets/               the BS icon. Replace icon.png and icon.ico with a new design
installer/            Inno Setup script
packaging/            PyInstaller script (windowed, no console)
tests/                automated checks
```

Personal files never go in these folders. They go in `%LOCALAPPDATA%\BabySitter\`.

## How a setting survives an update

`settings.json` starts with `"schema_version"`. `settings.py` has a `migrate` function. When you add a field:

1. Give it a default.
2. If old files need more than "fill in the blank", bump `SCHEMA_VERSION` and teach `migrate` how to rewrite the old shape.
3. Add a test that loads an old file and checks the new file.

Missing fields are filled from the defaults. A file from a newer app is refused, so an old program does not destroy new settings.

## How to add a voice engine later

Do not wire a new voice into the window by hand. Add a file under `src/babysitter/plugins/voice/` that has the methods in `base.py`: list voices, speak, and stop. The rest of the app should call those methods and should not care which engine it is. Do not add voice cloning.

## How to add a tool later

Add a file under `src/babysitter/plugins/tools/` with `describe` and `run`. `describe` is one sentence a person can read before they say yes. Nothing should call `run` until they have said yes. Do not pass the model's words to a command prompt. `shell=True` is not allowed anywhere. A test checks the source for it.

## Power rules that should stay true

- The program opens with the AI off.
- Off unloads models, stops Ollama, releases the microphone hook, and disables future assistant hotkeys. Emergency stop and the turn-on key stay.
- On starts Ollama hidden, waits for port 11434, and loads one model.
- Game mode unloads models and does not stop Ollama.
- Only `127.0.0.1` is contacted in this phase.
- Subprocesses are a list of arguments, with the Windows "no console" flag, never a shell string.

## Tests

From this folder, after the setup in the README:

```bat
.venv\Scripts\python -m pytest
```

The tests cover the power switch, the wipe-sized confirmations that exist so far (port closed, video memory, tray app), settings migrations, hotkeys, game-name matching, and the "no shell, localhost only" rules. They do not need a GPU. One test builds the window without showing it on a desktop.

## Publishing later

GitHub releases, the updater, and code signing are not built yet. When they are, the release steps will be:

1. Change `src/babysitter/version.py`.
2. Write what changed, in plain language, in `CHANGELOG.md`.
3. Make the installer version match (the test checks).
4. Tag `v1.2.3` and push the tag.

Do not tag a release from this phase. 0.1.0 is the power switch only.
