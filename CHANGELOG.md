# Changelog

BabySitter uses version numbers like v1.2.3.

## 0.22.0 — Use only what a question needs

**The paper goes with a question only when it matters.** With Google on, every question used to fetch the doc you changed in the last two hours and send its text along, even "what time is it". On Low, that crowded out the question, and every question waited on Google first. Now the doc goes with a question only when a Google Docs window is in front, or the question is about the writing: the paper, the essay, a paragraph, a citation, a rewrite. Any other question never reaches Google at all. "What am I writing" still finds a doc you changed in the last two hours.

**On asks about an Ollama that is already running.** When Ollama's own tray app started it, BabySitter's settings are not on it: the this-PC-only address, the smaller memory cache, and cloud models off. On now asks whether to restart it under BabySitter so they apply, or use it as it is without them. The answer is kept until BabySitter closes. Leave it running, in the quit dialog, now says the same.

**A folder named Games is not a game by itself.** Steam, Epic, GOG, the Xbox app, and Riot folders still count, and so does any name in your list. A game kept in a plain Games folder needs its name added in Settings. Settings shows example paths and how each one is read.

## 0.21.1 — A voice that sounds like a person

**Pauses where a person would take them.** Every sentence used to end with the same short gap, whether it was a full stop, a question, or a sentence cut in half. Now a full stop gets a real pause, a question a little longer, a comma a short breath, and a long sentence runs on where it had to be split. A long sentence is split at a comma where it can be, not in the middle of a phrase.

**Words, not symbols.** The voice hears "3.7 gigabytes", "12 percent", "for example", "8 to 10", and "about 9" instead of reading "GB", "%", "e.g.", "8-10", and "~9" letter by letter. A link is "the link on the screen", and emoji are left out. The screen still shows the text as written.

**A warmer EDITH-style blend.** It now mixes in Heart, Kokoro's most natural voice: Nova 45%, Heart 30%, and Kore 25%. It stays calm and crisp, and sounds less like a machine.

## 0.21.0 — A real PC scan, a faster update, and an EDITH-style voice

**"Scan my PC" says what is using it, and what looks wrong.** It names your five heaviest apps by memory, with Chrome's many processes counted as one Chrome, and the Health page lists each one's processor share. It also flags warning signs, each with its reason: a program with a Windows name running outside Windows' folders, a one-letter disguise of one such as svch0st, a program running from Temp, Downloads, the Recycle Bin, or the Public folder, a program whose file was deleted while it runs, and a startup entry that runs hidden PowerShell or a script from AppData. Windows Defender's own recent detections are read too. These are warning signs, not a virus scan, and nothing is closed or deleted because of one. The offers to close a heavy app or a startup item still follow, and still wait for a yes. The scan reads on its own thread and takes about three seconds.

**Update BabySitter is faster, and the old copy closes.** The rebuild reuses PyInstaller's earlier work instead of starting from an empty folder, so a small update no longer analyses every library again. An update now closes this copy even when turning the AI off reports a problem. The helper waits up to a minute for the old copy, and if it is still running, closes it before opening the new one. Each step is written to the log with how long it took.

**An EDITH-style voice.** The Voice tab has a new Kokoro blend: Nova's clear diction over Kore's lower, steadier tone, calm and crisp. It is a mix of Kokoro's stock voices, not a copy of anyone's. The short "One moment" lines now play in the voice you chose, instead of always in Heart and Sarah.

**A name to answer to.** Say "be EDITH", or "be Brook", or "call yourself" and a name. It is saved on this PC and used the next time the AI turns on. EDITH speaks calmly and precisely, with a dry wit. Any other name keeps the usual manner. Say "be yourself" to go back. A persona changes only how the assistant speaks: it cannot send mail, change a calendar, press play, flip a switch, or invent a source.

## 0.20.0 — Make room for a game

**Game mode follows the graphics card, not the game's name.** While a game runs, BabySitter reads the card every two seconds and works out how much the game leaves for the AI. Its own model does not count against it. If your level still fits, nothing changes. If Medium no longer fits but Low does, it switches to Low by itself. If not even Low fits, or system memory is nearly full, it switches to game mode and unloads the model. A reading has to hold for about six seconds first, so a loading screen does not flip levels, and the level only goes down while the game runs.

**Your level comes back when the game closes.** About ten seconds after the game closes, the level you picked loads again. Game mode that was switched on for the game is left by itself. Game mode you chose with the button stays until you press Leave.

**Nothing switches in the middle of an answer.** A change waits until the reply is written and spoken. That includes the two-minute return to game mode after "Load the brain?".

**On with a game already open loads the level that fits.** Turning the AI on while a heavy game runs loads Low instead of failing, or starts in game mode when nothing fits.

**Leave stays left.** After a "Load the brain?" visit, pressing Game mode and then Leave could bring game mode back two minutes later. Pressing Game mode or Leave now cancels that timer.

Settings calls the switch **Make room for a game by itself**. **Ask me before unloading the model for a game** still asks before game mode. Switching down to Low does not ask. Your saved level is never changed by a game.

## 0.19.2 — Bug fixes from a review of the code

**The Google Doc in front is read again.** The request asked Drive for the file's details instead of its text, so the AI never saw the draft. It now asks for the plain text.

**Nothing goes online by itself.** Loading speech recognition asked the Hugging Face Hub for the model's file list every time the AI turned on, even with the model already on this PC. Only the confirmed download goes online now.

**Reminders ring at the right hour across a clock change.** A reminder for another day used today's offset from UTC, so the night before daylight saving time began or ended, "tomorrow at 9" rang at 8 or 10.

**Tonight's Blackboard events stay on the list.** The feed compared each event with today's date in UTC, which in the evening is already tomorrow. Events later today now show until they are over.

**The PC scan leaves BabySitter and every game alone.** From the source folder BabySitter runs as pythonw.exe, and closing that name by voice closed BabySitter too. It is now skipped, and so is its own Start with Windows entry. Every game running from a store folder is left alone, not only the first one noticed.

**More program kinds are listed, never opened.** File search now also refuses Control Panel applets, ClickOnce installs, consoles, compiled help, and the other kinds Windows would run, and a name that ends in a dot.

**The window does not freeze for the PC check.** The Health page's check runs on its own thread.

**A failed update reopens BabySitter.** If the new BabySitter.exe could not be copied into place, the window closed and nothing came back. The old version now opens again and says the update did not finish. A failed pull also puts the project folder back on the branch it was on.

**Smaller fixes.** A settings file holding valid JSON that is not settings, such as `null`, is kept as a copy and replaced, instead of stopping BabySitter from opening. Settings from a newer BabySitter show one plain sentence. Each reply no longer leaves a thread behind. The keyword model download gives up on a stalled connection instead of waiting forever. The tests pass on a Windows desktop and no longer open a message box.

## 0.19.1 — Read the Google Doc you are writing

A question to the AI can include the Google Doc in the front window, in DuckDuckGo or any other browser, or the one you changed in the last two hours. The browser name in the window title is ignored. BabySitter reads that doc as plain text and keeps it on this PC. Say “what am I writing” to hear the title and the opening. Say “look up …” or “find a source for …” to search, after a yes. A credit line uses only a source that was actually returned. An invented author, title, date, or link is against the instruction. Downloading the file, and any format other than plain text, stays refused.

## 0.19.0 — Read Gmail, Calendar, Drive, school Google, and Blackboard

Tools can show unread mail, upcoming events, and Drive file names in one list. Sign in with Google asks for read-only mail, calendar, and Drive. Sign in school Google stores a second account separately, so a school Gmail account does not replace the personal one. A failed read of one of those does not hide the others. An expired sign-in says to sign in again instead of quietly reusing a dead token.

Blackboard has no single sign-in BabySitter can use at every school. Paste the external calendar link from Blackboard's calendar. BabySitter reads that feed and lists what is coming up. The link is encrypted on this PC and is not written into settings.json. A link that points at this computer, or at a numeric address, is refused.

You still create one Google desktop client id, once, and add the redirect `http://127.0.0.1:8765/babysitter`. Google does not let BabySitter sign in without that. Say "check my drive", "check my school email", or "what's on blackboard".

## 0.18.0 — Update BabySitter from inside the window

Settings now starts with **Check for an update** and **Update BabySitter** (and Home accepts “check for updates” or “update babysitter” even while the AI is off). When your BabySitter git folder is on this PC — whether you launched `Run BabySitter.vbs`, `dist\BabySitter.exe`, or a `BabySitter.exe` copied to the desktop — BabySitter checks `origin/main` directly without needing a `git push` to GitHub. After you confirm **Update and restart**, it fast-forwards `main`, updates `.venv` libraries if `requirements.txt` changed, rebuilds `BabySitter.exe` into a staging folder when running from the exe (or when `dist\BabySitter.exe` exists), closes the AI and single-instance lock cleanly, swaps the exe once the old process exits, and reopens on the new version.

On a PC without a git folder, **Update BabySitter** checks GitHub Releases, verifies the release asset's SHA-256 fingerprint before touching disk, and installs after confirmation. Tagged `v*` pushes now also have a Windows release workflow that builds `BabySitter.exe` and `SHA256SUMS.txt`. Personal settings, memories, notes, and encrypted keys in `%LOCALAPPDATA%\BabySitter` are never touched by an update.

## 0.17.4 — Reliable Windows exe build, warmer replies, and keyboard access

Opening BabySitter on Windows was failing inside `Shell.show` because `QApplication`, `QDialog`, `QFileDialog`, and `QMenu` had been dropped from `shell.py`'s imports. Those imports are back, and any startup failure inside the app now writes `%LOCALAPPDATA%\BabySitter\logs\startup-error.txt` before showing the error box. `scripts\build-exe.bat` now checks that `babysitter.ui.shell` imports cleanly, closes a tray-resident `BabySitter.exe` before rebuilding so Windows unlocks `dist\BabySitter.exe`, checks `PyInstaller`'s exit code and output file before reporting success, packs every `babysitter` submodule plus `numpy`, and leaves `pytest` and dev tools out of the exe.

Typing a normal question on Home and pressing Enter or **Run it** now sends the line instead of stopping on “Waiting.” Saying “remember the cat is called Moth” saves the fact without the word “remember”, and saying “remind me at 6 pm to stretch” saves “stretch” with the clock time instead of repeating the time twice. Saying “undo” within 10 seconds of setting a timer now cancels the timer and removes its row from `schedule.json` so it cannot ring later. Store-folder games noticed automatically now also hide the orb when **Hide the orb while a watched game is in front** is on, and PC scans leave them alone too.

Settings now includes the **Programs left out of the journal** list, Models has a **Remove model** control that asks before deleting a model from Ollama, Voice loads your saved voice, speed, and pitch (including pitch 0) on startup and blocks cloud voices that stay off, and Tools describes the spoken research recipes that already work. Local replies vary their phrasing naturally, conversation memory keeps local file, scan, Google, and review turns in context, text hints have higher contrast, and keyboard shortcuts (`Ctrl+L`, `F11`, `Ctrl+PageUp`, `Ctrl+PageDown`, `Esc`, and `Tab` focus rings) work across the window.

## 0.17.3 — The packaged voice no longer closes the window

Previewing Heart and Sarah in the built exe opened Kokoro, and Kokoro asked for `config.json` in the temp folder. That file was never packed, so the error box came up and the window stopped. Keyword listening did the same thing when Vosk's libraries were unpacked at the top of the temp folder instead of in the vosk folder. A missing file or DLL now leaves that feature off. The hearing programs and the sharper memory had the same hole, and they take the same path.

The build installs those programs first, then packs the files they open by path: Kokoro's config, espeak's data and library, PortAudio in its own folder, and Vosk's libraries in the vosk folder. The exe does not try to pip-install into itself. That was starting another copy of BabySitter.

## 0.17.2 — The window stays open when the keyword libraries are packed wrong

Turning the AI on was opening Vosk even when keyword listening was off. In the built exe, Vosk asked Windows for a temp folder that had not been unpacked. Windows could not find it, and BabySitter closed with an error. Keyword listening is the only path that opens Vosk now. A missing folder leaves that feature off, and the window stays up. The build also packs the Vosk and microphone libraries into the exe.

A burst of clicks or typed lines no longer starts a second voice or a second transcription over the one already running. The newest request waits, and the thread that is already going is kept until it finishes. Stopping keyword listening waits once, then leaves the microphone thread to exit. Enter on a reminder or a goal does not save the same line twice.

## 0.17.1 — A dead microphone comes back, and an hour and a half counts

An overflow on the microphone no longer throws the sound away. When the keyword stream dies, listening starts again only after the old thread has let go. If it dies three times in a row, keyword listening turns off and says so, instead of opening the microphone forever.

“An hour and a half”, “two and a half hours”, and “half a minute” are real lengths. When the keyword ear and Whisper both hear a command and they disagree, the longer line wins, so a short hint does not replace “remind me to stretch”. A clip that Whisper turns into “thanks for watching” or a lone “you” is treated as silence.

## 0.17.0 — The same ear for a keyword and for Hold Talk

A keyword command keeps its audio and, when speech recognition is downloaded, Whisper reads that clip. Vosk still notices the wake words. The reading carries a short hint of the command verbs. A second, slower reading runs only when the first line is not already a command and the model doubts it. A weak line that is not a command is repeated back, and nothing is sent. “Set a time for twenty minutes” and “rewind me” still land on the timer and the reminder. “Fine my tax pdf” finds the file.

Stopping the voice no longer closes the microphone. If the keyword stream goes quiet because it died, listening starts again. A list file that cannot be read is moved aside, so the next save does not erase it. The Voice page says how long the last line took to become text.

## 0.16.0 — More of what you say is understood

The heard line is matched as a pattern, not only as one exact sentence.

A clock can be “six thirty five”, “half past six”, or “quarter to seven”. “At 12”, with no am or pm, is noon. “At 12 am” is still midnight. “In 10 seconds” and “in ten seconds” keep the seconds, so a short reminder rings when you asked, and the note keeps the task (“to stretch”) instead of the time words. “Set a timer for twenty minutes” and “set a timer for half an hour” count.

These stay on this PC: “what’s the date”, “what’s my next reminder”, “cancel the reminder”, “say that again”, “stop talking”, “pin that”, “how did my day go”, “any unread mail”, “where is my tax pdf”, and “open the second one”. “Where is Paris” still goes to the model. “Make a note that …” is a memory. “Don’t forget to …” is a reminder.

A goal is not a reminder. It does not ring. “My goal is to finish the bracket”, then “say my goals”, puts the list on the Reminders page and reads it out. “Add another to call Mom”, “the second one is done”, and “drop the second goal” stay with that list while the talk is open. “Done” finishes the goal just talked about. Once that talk ends, “done” finishes a journal task again. “Find my goals” reads the list. “Where is my tax pdf” is still a file search.

“Comment themes” on a YouTube link is no longer sent to Reddit. Comments are read only for a TikTok or Reddit link. Anything else is refused, and nothing is sent.

## Also in 0.15.0 — Tomorrow rings, and a reminder row can wrap

“Tomorrow at 6” is 6:00 on the next day, not later today. With no am or pm, that is 6:00 AM. “Remind me tomorrow,” with no hour, is 9:00 AM tomorrow. “Set a timer,” with no length, is 5 minutes. A long reminder line grows past one row, so the countdown is not cut off.

## Also in 0.15.0 — The home picture fills the panel

The frog-pond picture on Home fills the assistant panel, cropped so the frog stays in view. Off is grey and dark. On keeps the colour, with a warm corner. The frog, the state word, and the hint sit on the picture, and **Choose my picture** sits in the top corner. Half screen makes the picture a little taller. A picture that will not open leaves the current one in place.

## Also in 0.15.0 — One exe you can move, and a setup for a GitHub visit

The built program is one file, `dist\BabySitter.exe`. Copy it to the desktop or any other folder. The pictures are inside the file, and settings stay in `%LOCALAPPDATA%\BabySitter`, so the file does not need the folder it was built in. `scripts\build-exe.bat` can copy it to the desktop after the build. Start with Windows remembers the path. Move the file first, then turn that switch off and on again.

Someone who downloads the GitHub ZIP does not get Ollama, the models, or that exe. There is still no release file on the page. Double-click `Setup.bat`. It makes the Python folder and downloads the pinned libraries. It then says what is still missing. Python 3.12, the Ollama installer, and the NVIDIA driver are installed by you. After a yes, the same setup asks Ollama to pull `qwen3.5:9b` and `gemma4:12b`. It will not pull any other name.

## Also in 0.15.0 — The v2 interface: the frog orb, the rail, and two new pages

**The frog orb.** The floating light is now a cartoon pond frog on a lily pad, with the BS pacifier in its mouth, drawn from animation strips that ship with the program. Each state has its own animation: asleep when Off, a firefly while Working, breathing and blinking when On, perked ears while Listening, a croaking throat pouch while Speaking, dozing in blue moonlight in Game, and hopping with a red ring when it Needs you. A short caption sits in a dark pill under the frog, never over it. A plain click opens the window, a drag only moves it, right-click opens the menu, and the animations stop when Windows' "Show animations" is off.

**The window.** A frameless window with its own title bar: Half screen snaps to the left half so a game fits beside it, Full screen fills the desk, the dash hides the window while the orb stays, and the X turns the AI off the way it always did. The pages moved into a rail on the left, in three groups — Today (Home, Schedule, Journal, Files), Assistant (Voice, Memory, History, Screen, Tools), and This PC (PC Health, Models, Settings). The top bar holds the state pill (clicking it is the power switch), the latest status line, Emergency stop, and the privacy word, which changes to "Online only when you approve" while an outside tool is on. Warnings now show in one place under the top bar, on every page.

**Home, rearranged.** The controls strip is first: Power, Intelligence, Game mode, and the Keyword. Then the assistant — the frog-pond picture, what you said, the spoken sentence under SAID, and the detail under ON SCREEN — beside the pinboard, which now holds up to twelve cards with Open and Unpin on each. This PC and What just happened close the page. In Half screen, and whenever the window is too narrow for one row, the four controls fold into two columns and the cards stack into one column, assistant first, so Listen for a keyword stays on screen. The state pill shows Listening, Thinking, and Speaking while the microphone or the voice is busy, the same words as the frog.

**Two new pages.** Journal got its own page: the switch, Say my day and Say yesterday, pause and resume, starting and finishing tasks by button, today's minutes per program, and the wipe. Files got its own page too: type a few words, press Find, and the same search runs that "find my tax pdf" runs by voice — one match opens, several make a numbered list, and programs are listed but never started.

**A desktop icon for the built app.** `scripts\desktop-icon.bat` puts a BabySitter icon on the desktop. It opens the one file, `dist\BabySitter.exe`. After a git pull, building again updates the program that icon opens. A copied file stays as it was until you copy it again. Reminders and settings stay in the personal folder.

**A countdown on each reminder.** Home shows the next reminder and the time left, in large type. Each row on the Reminders page shows the same countdown, and it ticks every second until the reminder rings. The README, which is the GitHub page, describes that.

**A reminder still rings when the AI is off.** Turning the AI off unloads the voice. A due reminder now says itself with the Windows voice, and still shows the notification, without turning the AI on or asking to download a voice. BabySitter has to be open, including in the tray.

**Reminders you can add, and a pin on every list.** The Reminders page has a note and a time. "6:00 PM" or "in 20 minutes" is saved as the clock, so the reminder rings. "Set a timer for 20 minutes" saves that same kind of reminder, due 20 minutes from now. When the time arrives, BabySitter says it and shows a notification on this PC. That happens while BabySitter is open, including in the tray. If BabySitter is quit, it is said the next time the app is open and the time has passed. Nothing is sent. Each row on Reminders, Memory, History, Journal, Files, and Settings has a pin, and Screen, Health, Models, Tools, and Voice can pin what they are showing.

**A conversation that keeps going.** A follow-up can be one word, such as why or where. The next question still knows the answer that stayed on the screen, and it knows a local answer such as the clock, a reminder, or the journal. A saved fact that only shares a word like "is" is no longer offered. A name such as "Dr. Smith" is not split into its own sentence. A reply stops at 512 new tokens so one turn cannot run on.

**Notes, reminders, and the voice.** The pinboard has a title and a note, so a card can be pinned without waiting for a reply. The rail page is called Reminders, and each row shows the clock time and whether it has already been said. The Game mode button switches by hand. Settings can ask before a game switches on its own. The voice keeps one playback stream open and trims the long silence Kokoro puts on each sentence, and the rest of a reply is rendered while the first sentence is still playing. Low stays on qwen3.5:9b. The Q4 file is 5.6 GB, and a normal load is about 6.5 GB once the cache and CUDA are counted. Cutting the context does not bring it under 6 GB, and layers are not moved into system memory.

**Reminders ring.** "Set a reminder at one thirty to go to bed" is saved on this PC and spoken when that time arrives. It is not sent to the model. "Read out my history" reads the last few saved lines here too, in a short piece, so a long reply cannot knock the voice over. Medium still says, up front, that it uses about 8 to 10 GB. Low is the voice model, about 6.5 GB.

**The look.** Inter for everything you read, JetBrains Mono for keys and paths, Space Grotesk for the name, and the amber BS pacifier as the program's icon everywhere. Orange is only ever something you can click; green, blue, yellow, and red only ever mean state. Nothing else changed underneath: the same settings, the same confirmations, the same rule that nothing listens, loads, or sends until you act.

## Also in 0.15.0 — A day journal, a file search, and a memory that matches meaning

**The day journal.** While the AI is on, the name of the front program is written down about twice a minute, with the minutes spent — only the program's name. No window titles, no keys, no screenshots, nothing sent anywhere. "What did I do today" and "what did I do yesterday" speak the day: "Today you spent 2 hours in blender, 45 minutes in bg3." Say "start task modeling the bracket" and later "done" to put a named block of time in the day too. Days are plain JSON files in your BabySitter folder, kept for 90 days. Settings can turn the journal off, exclude programs, or wipe every day file; "pause the journal" stops the writing until you resume it or restart.

**The file search.** "Pull up my current tax pdf" opens the tax PDF you opened last — "current" and "latest" use Windows' own Recent list, falling back to the newest change. "Find all stls" lists every STL. A partial name never errors: one match opens, several are listed with numbers so "open number 2" opens that one, and only a file the search just listed can be opened — for 10 minutes, then the list goes stale on purpose. A program or a script (`.exe`, `.bat`, `.ps1`, a shortcut, and the rest) is listed but never started; documents open, programs only show their place. It looks in Documents, Downloads, and Desktop, plus any folder you add in Settings, scanned on demand on its own thread (never indexed in the background, never freezing the window), and no file name leaves this PC.

**The sharper memory.** A new button on the Memory tab downloads a small sentence model (all-MiniLM-L6-v2, about 90 MB, checked against a recorded SHA-256) so saved facts match by meaning: "what's my pet called" now finds "My dog is called Biscuit." It runs on the processor, never the graphics card, and each fact is embedded once and cached, so a question costs one small forward pass. The saved facts are embedded right after the download finishes, and the model warms in the background when the AI turns on, so no question waits for either. Without the download, the old same-words match keeps working, and a fact that shares no word with the question is left out even when the short hash happens to line up. Either way only the top two matching facts reach a question, so a big memory never slows the AI.

## 0.15.0 — Game mode switches by itself, plus the November review

Opening a game now switches to game mode without you typing its name first. A program running from a folder where game stores install — Steam's `steamapps`, Epic Games, GOG, the Xbox app, Riot Games, or a folder simply named `Games` — counts as a game. Launchers, anti-cheat helpers, and installers in those folders do not. Only the file name and the folder it runs from are read; nothing reads a game's memory. This one update turns automatic game mode on, since it was asked to work by itself. Two switches in Settings turn it off: one for the folder detection, one for automatic game mode entirely. A game installed somewhere unusual still needs its name in the list, and **Switch** under Game mode still works by hand. Waking the model during a game still keeps the AI on until that game closes.

## Also in 0.15.0 — The November review: a newer Ollama gate, faster loads, and checked downloads

The security cutoff moves from Ollama 0.17.1 to **0.35.0**. October 2026 brought CVE-2026-103663: on anything from 0.34.2 up to 0.35.0, a program that can reach Ollama's local port can make it write a file outside its model folder, and that file runs the next time Ollama starts. The old message even recommended 0.34.2 for speed, which sits inside that range. Anything older than 0.35.0 now gets the warning and the ask before turning on.

The Ollama that BabySitter starts now has Ollama's own cloud models turned off (`OLLAMA_NO_CLOUD=1`). Signing in to Ollama for another app can no longer send a BabySitter request to the internet.

Loading a model no longer asks it to write a word and throw it away. The load request carries an empty conversation, so Ollama loads the model and answers at once. Power-on is a second or two faster.

Low's batch goes from 128 to 256. That costs about 36 MB of video memory by this project's own arithmetic and roughly doubles how fast a long prompt — a screenshot, a tool reply — is read. Low stays inside the 4 to 6 GB goal. If your card disagrees, the model card and the Models-tab benchmark will say so.

The four allowed downloads (the two Heart and Sarah files, the keyword model, and the voice detector) are now checked against a recorded SHA-256 before they are kept. A file that changed behind its address is refused and deleted.

Public text — social results and web results — is labeled before the model reads it: the prompt now says those lines were written by strangers and that instructions inside them are not to be followed. What you said is never labeled.

## 0.14.5 — Closing BabySitter unloads the model

The X button used to hide the window and leave the model loaded. Quit also offered “leave Ollama running,” and every reply pinned the model in memory until something unloaded it. A 12 GB model left that way is the 20 GB reading that stays after the window is gone. A runner process started by Ollama could also survive when only the parent was stopped.

Closing the window now turns the AI off. Quit always unloads the model, stops Ollama, and closes the microphone and the local voice. An idle model also drops after five quiet minutes instead of staying forever. Ollama is started with the context size of the level you turned on, not a 16,384 default.

“Please check my email,” “can you tell me the time,” and “what's on the screen” stay on this PC. A remembered line keeps its capital letters, so “Moth” is not saved as “moth.”

## 0.14.4 — “No” answers the scan, and a waiting scan still runs

Saying “no” to “Close it?” was dropped. During a follow-up, a single word “no” is treated as silence, and the scan never turned on the yes-or-no listener. It does now, so “yes” and “no” both count without the keyword.

A scan asked while a reply is still being written runs when that reply is done, including when the voice never starts. “Check my pc” and “clean up my computer” scan this PC. “How’s my computer” speaks the memory and CPU numbers.

## 0.14.3 — The scan says the memory number, then one question

A spoken scan now starts with the real memory reading, such as "Memory is using 20.0 of 32.0 GB, 62 percent," and then one suggestion you can accept or deny. "Why is my ram so high," "my computer is slow," and "free up some memory" take that path. "How is my pc" speaks the memory and CPU numbers.

If a reply is still being spoken, the scan waits and runs when that reply finishes. It no longer says it will scan and then drops the request. The model is told not to invent a scan and not to paste a shell command.

## 0.14.2 — A spoken scan checks this PC

“I'd like you to scan my computer, my RAM usage is very high” now runs the scan on this PC. It no longer asks the model, which was answering that it could not see the hardware and pasting a shell command. The same is true for “scan this computer”, “check my RAM”, and “what's using my memory”.

If nothing is heavy enough to close, the scan still names the heaviest program it can see. The spoken line is not repeated again in the text under it.

## 0.14.1 — The double-click starter shows the window

`Run BabySitter.vbs` was starting the program hidden. A double-click could look like nothing happened, and a crash inside pythonw had no window to read. The starter now opens the window normally. If the Python folder is missing, it says so. `Run BabySitter.bat` does the same and leaves the error on screen. A failed import is also written to `startup-error.txt` in the BabySitter log folder.

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
