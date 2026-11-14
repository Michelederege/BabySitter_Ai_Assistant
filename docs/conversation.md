# A conversation that stays in the room

People name this kind of assistant Jarvis. The useful part of that, from the film and from voice-agent work, is not a second model. It is the pace.

A modal dialog breaks the feeling that someone is in the room. A spoken yes or no, about one concrete thing, does not. BabySitter keeps the dialog for a search that leaves the PC, for deleting a saved key or token, and for quitting. A look at the screen, a reminder, and a remembered fact used to ask twice. The sentence you already said, or the button you already pressed, is the yes. Undo within 10 seconds removes a reminder, a fact, or a startup change.

The first sentence is the answer. The standing instructions say that, and they stay fixed for the whole time the AI is on, so the model does not reload. After an answer, the follow-up window is already there: you can keep talking without the wake word. Do not stack a wake word, a dialog, and “do you want to know more.”

## Which model

On this PC the card is a 12 GB RTX 4070. The processor is a Ryzen 9 7900X, and the machine has 32 GB of memory.

Low stays on `qwen3.5:9b`. A 3B or 4B model would answer faster and use less video memory, and it would drop multi-step requests: mail, calendar, and “close this, then tell me what is left.” `gemma4:12b` writes better and fills the card at 8,192 tokens, so it is Medium and High only, and only when a game is not using the card. A second model is not kept loaded.

The Q4 weights are about 5.4 GB. The 4,096-token q4 cache and the small batch add a few hundred megabytes, so a normal Low load is about 5.7 GB. That is inside 4 to 6 GB. It is not 4 GB. Moving layers into system memory is refused, because replies get slow and BabySitter would unload the model.

Dropping the context from 4,096 to 2,048 saves about 80 MB. A screenshot and a tool reply no longer fit. That trade is not worth it. These numbers are calculated for this card. They are not a live reading from the GPU.

## What does not use the model

Mail, calendar, the clock, a timer, and the PC scan do not load a model. Google stays off until you paste a read-only token. The scan speaks one suggestion. Yes does that one thing. No leaves it. Games, Windows, and security tools are never on the list to close.
