# Notes for agents

Lessons from working on this project. Read these before giving Michele
commands to run, and before opening a pull request. Plain sentences,
like the rest of the repo.

## Michele runs commands in PowerShell

Write `cd C:\BabySitter`, never `cd /d C:\BabySitter`. The `/d` flag
belongs to Command Prompt; PowerShell reads it as a path and the
command fails. More than one agent has made this exact mistake, so it
earned this file. Batch files such as `scripts\build-exe.bat` and
`Run BabySitter.bat` are still fine — those run by double-click.

The project lives at `C:\BabySitter` on Michele's PC. His Python is
started with `py -3.12`.

## Where the code lives

- Work happens on the Origin repo `michele-de-rege/Ai-assistant-Babysitter`.
  Pull requests are opened and merged there.
- The public copy is GitHub `Michelederege/BabySitter_Ai_Assistant`.
  The in-app update check points at it. Michele pushes `main` there
  from his own PC (`git push github main`); agents do not have write
  access to it.

## One branch, one pull request

Make a fresh branch off `main` for each pull request. Once a pull
request is merged, stop pushing to its branch — commits pushed to a
merged pull request's branch land nowhere, and someone has to fish
them out later. Follow-up work gets a new branch and a new pull
request, even when it continues the same feature.

## The repo's own habits still apply

CONTRIBUTING.md explains the folders, the one version number, and the
plain-sentence style. Five simulations for every feature. Tests run
with `pytest tests/ -q`, offscreen, no desktop needed.

## One place for the old chats

Product decisions from the earlier agent chats live in
`docs/agent-memory.md`. Read that file instead of opening old chats.
If a chat and that file disagree, the file is the one to follow, then
check the code.
