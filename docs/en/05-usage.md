# Using Amelie

Amelie tells the story of the wine you set in front of it: it reads the label
with the camera, recognises the bottle and tells its story on the screen and
aloud, in Italian or English, without any connection.

At the front is the screen, tilted towards the people at the table. Behind the
screen is the plate, the translucent disc the bottle stands on. The camera and
the light sit in the tower that holds the screen, facing the plate; the
distance sensor sits under the disc.

This guide describes what the people at the table see and can do, what the
person who runs the device finds in the settings, and where to look when
something goes wrong. Phrases in double quotes are the exact wording on the
screen and the exact words of the voice (`data/lessico/frasi.json` and
`src/amelie/ui/static/index.html`). How the device gets from the label to the
wine is in [06-recognition.md](06-recognition.md), how the story is composed in
[07-storytelling.md](07-storytelling.md).

## The waiting screen

At power-on the screen shows the logo on its own, the wine glass and the name,
with the wine swaying gently in the glass, and stays like that until the voices
are loaded: that way the first bottle finds the voice already ready. It
normally takes less than a minute. If the device is still not ready after
ninety seconds, "Ci vuole più del solito." appears at the bottom with "This is
taking longer than usual." underneath (see
[Symptoms and remedies](#symptoms-and-remedies)).

When the device is ready it shows the waiting screen: the wine glass, the
name, the phrase "Every bottle has a story." and three steps, each with its
own icon:

| | Italian | English |
|---|---|---|
| 1 | **Scegli** una bottiglia | **Choose** a bottle |
| 2 | **Posa** la bottiglia su Amelie | **Place** the bottle on Amelie |
| 3 | **Ascolta** la sua storia | **Listen** to its story |

The three steps are a sign, like the text on a notice board, and that is why in
Italian they use the informal *tu*; when the device speaks to the guest it uses
the formal *Lei* ("Provi a girare l'etichetta verso di me?", in English "Could
you turn the label towards me?").

In the top right corner are the language flags, in the top left the volume
speaker. They are the only spots that respond to touch, together with a hidden
corner that opens the settings ([How to open them](#how-to-open-them)). The
rest of the screen is inert on purpose: on a table, an accidental touch is the
norm. Every button acts when you lift your finger, and only if the finger is
still over it: a touch started by mistake is cancelled by sliding away. The
exception is the keys of the corrections keyboard, which type as soon as you
press them.

In the bottom right corner there is a tiny dot, normally almost invisible: it
turns red when the microcontroller does not respond or when the page has lost
its connection to the service (see
[Symptoms and remedies](#symptoms-and-remedies)).

## A bottle, from start to finish

### Placing it

Stand the bottle upright on the plate, with the label facing the screen: the
camera looks at it from the tower, and a label turned sideways reads poorly, or
not at all.

Whether there is a bottle is decided by the distance sensor, and by it alone:
it notices in an instant (three readings in agreement, about 0.15 seconds).
The camera is there to know where the label is. As soon as you set the bottle
down the light turns green and the screen says "Let me have a look…"; then,
with the light amber, "I'm reading the label…" while the camera takes the
picture and the OCR reads, and "One moment…" while it looks for the wine.
Meanwhile an animation shows a bottle pouring into a glass.

### The story

Then the story starts, on the screen and aloud, with the light green. The
screen shows:

- at the top the **title**: the name of the wine; or the *tipologia* (the wine
  type within an appellation), the appellation (*denominazione*) or the grape
  variety, when recognition stops there; or, when there is nothing in the
  archive that can be named, what was read on the glass (for example "Rosé
  sparkling wine, brut"). Below it, winery and vintage, if known. For a bottle
  corrected by hand or told from the wine list, the title is the one written
  there, with no line below;
- with "Add corrections" on, the "Correct this bottle" button below the title
  ([Corrections](#corrections));
- the full **text**, with the sentence the voice is speaking highlighted; the
  text scrolls by itself to keep it in view, and it cannot be dragged with a
  finger;
- the **controls**, four circles at the bottom centre, with a **bar** below
  them that fills up until the end of the story;
- the **cross** in the bottom left: that is Cancel.

The first sentence says what is on the plate and how sure the device is: "This
is the …" when recognition is certain, "I'd say the …" or "It should be the …"
when it is a guess. Many sentences have several equivalent forms, and the
same wine always gets the same one. When the label can be read but there is nothing
in the archive that can be named, the device says only what is written on the
bottle (for example that it is a rosé sparkling wine, brut) and closes with
"This bottle is not in my archive; the description was generated
independently, from the data and catalogue available to me."

If there is no voice for the chosen language, the story is only read: the text
scrolls by itself at reading pace, controls and bar disappear, and "In this
language the story is written, not spoken." appears at the bottom of every
screen. Italian and English both have their own voice (`VOCI` in
`src/amelie/speech.py`): this only happens with a language added to the
lexicon without a voice.

### The story controls

| Control | Where | What it does |
|---|---|---|
| Restart | first circle, the circular arrow | starts the story again from the beginning, even if it was paused |
| Back | second circle, two triangles pointing left | goes back 5 seconds |
| Pause / resume | third circle, the largest: two bars, or a triangle while paused | stops the voice; touched again, it resumes from there, repeating the last instant so as not to cut a word |
| Forward | fourth circle, two triangles pointing right | skips ahead 5 seconds, as far as the voice is already ready |
| Cancel | the cross in the bottom left | closes the story and returns to the waiting screen |

The skips are `SALTO_S` (`src/amelie/app.py`).

When the story is over, the text stays on screen for two seconds, twelve with
"Add corrections" on (`CONCLUSO_CON_CORREZIONE_S`, time to reach the button),
then the waiting screen returns. On this final screen the circles have nothing
left to control and turn off at the first touch; the cross does work, and
returns to the waiting screen at once.

**Cancel** is for someone who has already poured and wants silence without
lifting the bottle again. It also works when the story has not started yet
(for example while the model is writing). After Cancel the language stays the
one chosen, and the bottle left on the plate is not read again: the device
waits for it to be removed.

A pause does not hold the device forever: fifteen minutes after the story
started (`TETTO_RACCONTO_S` in `src/amelie/app.py`) the voice stops anyway.
The text stays on screen, the circles no longer respond, and you leave with
the cross.

### Removing the bottle

| When you remove it | What happens |
|---|---|
| during "Let me have a look…", the reading, the wine search or "Could you turn the label towards me?" | the round is interrupted and the waiting screen returns at once |
| during the story | nothing stops: the story goes on to the end (or stays paused), then the final screen and the waiting screen |
| on the final screen, including "I couldn't recognise this bottle." | the waiting screen returns at once |
| during "Something went wrong. I'll try again in a moment." | the screen runs out its six seconds, then the waiting screen returns |
| after the return to the waiting screen | the next bottle placed starts a new round |

In all these cases, when the screen returns to waiting with the plate empty,
the language goes back to the house language ([Languages](#languages)).

The story continues because someone who lifts the bottle to pour has not asked
for silence: a story that dies mid-sentence is more noticeable than one that
ends. To silence the device there is Cancel.

### Putting the same bottle back

If you put it back while the story is playing, or on the final screen, the
device looks at it right away, without stopping the voice. If the photo finds
the previous label again (at least 25 image points, `STESSA_A_OCCHIO`), or the
same words are read again (with the rule used for corrections, see
[How it is recognised next time](#how-it-is-recognised-next-time)), the story
goes on and at the end the bottle is not read again. Two labels of the same
wine, front and back, count as the same bottle, because they tell the same
story. If the new reading yields no word that identifies the bottle, the device
cannot decide: it lets the story finish and reads the bottle again afterwards.

If you put it back when the screen has already returned to waiting, it is a new
round and the story starts over from the beginning. It is also the way to hear
a bottle again.

### Swapping it for another

A different bottle placed during the story, or on the final screen, is read
immediately, while the voice is still talking about the previous one. As soon
as the words read say it is a different wine, the voice stops and the story of
the new one starts, already read: no new photo is needed. The decision is made
by the text, not by the photo: the photo can quickly tell that a bottle is the
same, but a bottle put back turned around matches few points of the previous
label, and from that alone one cannot conclude that it is a different one.

### The bottle that is not recognised

Two cases lead to the same screen: the OCR finds no words (digits and fragments
do not count), or it finds words but no wine (in "Wine list" mode: no entry in
the list). The screen shows the ↻ symbol and "Could you turn the label towards
me?", the light turns red, and after four seconds the device tries again with a
new photo: that is the moment to turn the bottle.

After three failed readings (`TENTATIVI_MAX` in `src/amelie/app.py`) the device
stops:

- with "Add corrections" on and at least one identifying word read, the ?
  symbol appears with "I couldn't recognise this bottle." and the "Help me
  recognise it" button; the screen stays for twelve seconds
  (`CONCLUSO_CON_CORREZIONE_S`), time to reach it, then the waiting screen
  returns;
- otherwise the waiting screen returns at once.

In both cases the bottle left on the plate is not read again: to try again,
lift it and put it back. Without this cap any object left on the plate (a
glass, a bottle with no label) would keep camera, light and OCR running all
evening. With corrections on, "Help me recognise it" also appears between one
attempt and the next, below the request to turn the label.

### The light

The light sits in the tower and lights the label through a translucent window.
Its colour says what the device is doing:

| Moment | Light |
|---|---|
| power-on, until the service's first command (normally the first bottle) | amber, pulsing slowly |
| waiting screen, reading, wine search | steady amber |
| capture with the camera stopped | white, only for the duration of the capture |
| bottle just placed, story, final screen (including "I couldn't recognise this bottle.") | green |
| "Could you turn the label towards me?", "Something went wrong. I'll try again in a moment." | red |
| Debug camera on | white |

The pulsing at power-on comes from the microcontroller on its own, to show
that the device is alive while the system starts. Normally the camera is
already running when the bottle arrives, and the frame is taken from the
stream without switching to white.

## Languages

The flags are in the top right on every screen of the cycle, the story screen
included; the settings, the Debug camera and the corrections editor cover the
whole screen, flags included. The flag of the language in use is full, with a
gold circle around it; the others are dimmed.

- **You touch the other flag**: the text changes immediately and the device
  confirms it aloud, in the new language: "Lingua italiana. Da adesso racconto
  i vini in italiano." or "English language. From now on I will describe the
  wines in English." Outside the story screen the sentence also appears
  written at the bottom, like a subtitle. If a story is playing it stops at
  once, and once the announcement is over it starts again from the beginning
  in the new language; the same goes for a story that has just ended: same
  wine, without putting the bottle back. On the final screen the touch keeps
  it up for up to fifteen seconds
  (`LINGUA_A_RACCONTO_FINITO_S`), time for the announcement and the story in
  the new language to arrive.
- **You touch the flag already active**: nothing changes, but the announcement
  is made anyway. It is the quickest way to test voice and speakers without a
  bottle.
- **You touch while an announcement is speaking**: the announcement is
  interrupted and the one for the language just chosen starts.

The starting language is Italian (`Configurazione.lingua` in
`src/amelie/app.py`; there is no command-line option). The device goes back to
it by itself, without announcing it, when the bottle has been removed and the
screen returns to waiting: whoever comes next finds the house language. If the
bottle is removed during the story, the language goes back home when, the story
over, the screen returns to waiting. As long as the bottle stays on the plate
the chosen language stays: after the story ends, after Cancel, after a fault,
because the same people are still at the table. Cancel and "Restore operation"
do not change the language by themselves: if the cross is touched when the
plate is already empty, the chosen language stays for the next bottle as well.

Names of wines, wineries and vintages are not translated: they are what is
printed on the bottle. A wine list or a correction with no text in the chosen
language lets the archive speak (see the relevant sections).

## Volume

Touch the speaker in the top left: a slider opens next to it. Drag the knob, or
touch the point on the track you want; the level goes from 0 to 100 in steps
of 5. The slider closes by itself after four and a half seconds without
touches, when the screen changes, or when you touch the speaker again.

- **The icon shows the level even when the slider is closed**: two waves from
  halfway up, one below halfway, none and a slash at zero. At zero the device
  tells the story anyway, silently.
- **When your hand stops** the device plays a little tap on a wine glass at the
  new level, so you can adjust it without placing a bottle. While it is telling
  a story or announcing a language there is no tap: the level can already be
  heard.
- **The gain is the square of the value**: halfway is about −12 dB, which to
  the ear sounds like half volume. 100 is the maximum the digital signal
  carries without distortion, and it does not go beyond that.
- **It is remembered** from one power-on to the next (`var/volume`). Without a
  saved value the service's `--volume` option applies, and without the option,
  100.

The audio chain has no hardware volume control: the sound leaves the board
over HDMI and reaches the speakers through the screen. What is adjusted is the
signal, an instant before the output. If the service starts without voice
(`--senza-voce`) the speaker does not appear.

## Settings

### How to open them

Hold your finger still **on the bottom-right corner** of the screen for **three
seconds**. The sensitive area is a square of about one centimetre in the
corner; nothing appears while you hold, and when the three seconds are up the
panel opens. If you lift your finger earlier, or move it by more than a few
millimetres (30 pixels, `ANGOLO_SCARTO` in `src/amelie/ui/static/index.html`),
the gesture is cancelled and must be repeated. It works from the screens of the
cycle (waiting, reading, story, notices), not over the corrections editor or
the Debug camera. The entry point is hidden on purpose: if it could be reached
with a single tap, someone setting down a bottle would open it by mistake.

The panel, titled "Settings", covers the screen; the list scrolls with the
finger, and it closes with the cross in the bottom left, in the same place as
Cancel. It does not close by itself: close it before leaving the device to the
guests. It does not stop the device: a bottle placed in the meantime is read
and told underneath, and the voice can be heard. Almost every row has a line
of explanation below its name. The rows, from the top:

### How it tells

The first section, "How it tells", chooses where the text comes from. Each
mode is a row, and the one in use has the tick.

| Mode | Where the text comes from | When it appears |
|---|---|---|
| "From the archive" (default) | composed from the archive data and the production specification (*disciplinare*), without a model: it does not invent and it is immediate | always |
| "Written on the spot" | the same data, but the text is written by the language model for that bottle; experimental, it can make mistakes and makes you wait some tens of seconds | only if the service starts with `--con-modello`, as the installed unit does |
| "Wine list" | the hand-written descriptions in the wine list file, and only for the wines it contains | only if a wine list is loaded with `--carta`, as the installed unit does ([The wine list](#the-wine-list)) |

The difference between the modes is not one of style, it is the source of what
the device says. The chosen mode applies from the next bottle (changing it
mid-reading would interrupt the listener) and is remembered in `var/modo`. A
saved mode the device cannot serve (the wine list missing, the model not
enabled) falls back to the archive.

In "Written on the spot" mode:

- choosing the mode starts `amelie-llm.service`, choosing another one stops it:
  even when idle the model takes up a core that the OCR needs;
- before each story the device waits for the model to respond, for up to 45
  seconds (just after being started, the model is still loading); while the
  model is writing, "I'm writing the description…" appears in place of the
  text, with a small wine glass;
- what the model writes goes through a check; if it invents twice in a row,
  the ready-made text for that wine is used, if there is one, and otherwise the
  composition from the facts. It falls back the same way if the model does not
  respond;
- when all that is known is what is written on the label, the model never
  writes: the composition is told.

Hand corrections take precedence in all three modes.

### Add corrections

A switch, off until you turn it on; it stays as it is even after a reboot
(`var/correzioni_attive`). When it is on:

- every story shows "Correct this bottle" below the title, or "Edit the
  correction" on a bottle already corrected;
- unrecognised bottles offer "Help me recognise it";
- the final screen of the story stays for twelve seconds instead of two, to
  leave time to reach the button.

When it is off, no guest sees a button to correct, but corrections already
saved are still recognised. The change applies at once, also to the story on
screen; if it is turned off with the editor open (from `POST /correzioni/0`),
the editor closes without saving. Apart from the hidden gesture and the switch
there is no PIN: turn it on when you want to correct, and off before leaving
the device to the guests.

### Debug camera

A switch that shows full screen what the camera sees and what it manages to
read, to fine-tune the framing:

- on the left the video, with the **box** that goes to the OCR (nothing outside
  it is read; if the device has found the bottle it is the box around it,
  otherwise the fixed one), the two centre lines to centre the label and the
  text `nitidezza N (soglia S)` (sharpness N, threshold S): all in green from
  the threshold up, in red below;
- on the right "What it reads", with the reading time and the lines found (the
  first ten, then "e altre N" (and N more); "no line of text" if there are
  none), and "What it finds", with level and confidence (green if recognition
  is certain, amber if it is doubtful, red otherwise), wine, winery and
  vintage, up to three candidates, and at the bottom sharpness and exposure
  ("nitidezza", "posa"). This column queries the archive, not the wine list or
  the corrections, and lags a few seconds behind the video: that is the time
  the OCR takes.

Turning it on **stops the cycle**: the camera can be used by only one process
at a time, so there are no stories and no readings while it is on, and a story
in progress is interrupted. The light goes white and the exposure is searched
for once, so you frame with the light that will really be there. You leave the
screen only with the "back to the story" button, in the bottom right, because
the Debug camera covers the panel; on leaving, a bottle left on the plate is
read immediately, and that is the proof that the framing works. It is not
remembered from one startup to the next, and the row does not appear if the
service started without a camera (`--senza-camera`).

To watch from a PC, on a large screen, there is also `scripts/mirino.py`, with
the same logic. It must be run with the service stopped, because the camera
can be used by only one process at a time:

```bash
sudo systemctl stop amelie.service
cd ~/amelie && PYTHONPATH=src ./venv/bin/python scripts/mirino.py --ocr --luce
```

then open `http://<board-name>.local:8090/` in the PC's browser. Ctrl-C closes
it, and `sudo systemctl start amelie.service` gets the device going again.

### Battery recharged

The power bank reports nothing: the device estimates how much energy it has
used from how long it has been on, how hard the CPU is working and how much it
speaks, against a usable capacity of 60 Wh (`CAPACITA_WH` in
`src/amelie/batteria.py`). The estimate is shown only in this row, as a
four-bar icon, without a number, because it is an estimate: four bars from 75 %
up, three from 50 %, two from 25 %, one from 8 %. The last bar disappears at
8 % and not at zero, because there the power bank may shut off without
warning; at zero bars the outline turns red and pulses.

Touch the row after recharging: the estimate restarts from full and the icon
goes back to four bars. At power-on the device does this by itself if it has
been off for at least three hours (`RICARICATA_DOPO_S`), as after an overnight
charge; after a short reboot the estimate resumes from where it was. If at
power-on the board's clock appears to have gone backwards, or forwards by more
than sixty days, the estimate stays as it was: in that case touch the row by
hand.

### Restore operation

Restarts camera, reading and voice without switching off, when "Something went
wrong. I'll try again in a moment." keeps repeating. While it works the row
dims (it takes a few seconds), then a tick appears and the panel closes onto
the waiting screen. What it does is described in
[Automatic recovery](#automatic-recovery).

### Technical state

Opens the contents of `/stato` above the panel, to be read without a keyboard:
it is a snapshot of the moment you open it. "close" returns to the settings.
The most useful fields:

| Field | What it says |
|---|---|
| `stato` | the state of the device (see below) |
| `mcu`, `protocollo`, `moduli` | whether the microcontroller responds with the Amelie firmware, which protocol version it speaks (the expected one is 2), and whether it sees the light (`anello`) and the distance sensor (`distanza`) |
| `camera`, `fotogramma_s`, `posa` | whether the service uses the camera; how many seconds have passed since the camera last delivered a frame (under a second at rest, `null` if it has never delivered one; during the story the camera is off and the number grows); the exposure in use |
| `bottiglia` | whether the distance sensor sees a bottle |
| `differenza`, `soglia` | how much the plate, as seen by the camera, differs from the empty plate, as a percentage, and the threshold beyond which the camera sees something on it |
| `voce`, `volume`, `pronta` | whether the model of the voice in use is there, the volume, whether the device has finished getting ready |
| `modo`, `racconti_generati`, `carta`, `voci_in_carta` | the storytelling mode, whether the model writes the text, the wine list file and how many entries it contains |
| `ultimo_livello`, `sicurezza` | the outcome of the last recognition: the level (`vino`, `tipologia`, `denominazione`, `vitigno`, `generico`, `nulla`: wine, type, appellation, grape, generic, nothing) and the confidence, from 0 to 100 |
| `transizioni` | the last twelve state transitions |

The states, in the order of a round: `attesa` (the waiting screen),
`assestamento` ("Let me have a look…"), `scansione` (the reading),
`riconoscimento` (the wine search), `racconto` (the story), `concluso` (the
final screen, or "I couldn't recognise this bottle."); `riposiziona` is "Could
you turn the label towards me?", `guasto` is "Something went wrong. I'll try
again in a moment.".

## Corrections

A correction teaches the device a bottle: what to say about it, or which known
wine it corresponds to. It is made from the screen, with "Add corrections" on.

### Opening the editor

- **From a story**, with "Correct this bottle" (or "Edit the correction" on a
  bottle already corrected). The button appears together with the text and
  stays on the final screen too. The voice stops. On a bottle already
  corrected the editor reopens the correction as it is. Otherwise, if the
  device has recognised a wine, a *tipologia* or an appellation from the
  archive, or a wine list entry, the editor opens already linked to it, with
  its name in the title; if not, with an empty title.
- **From an unrecognised bottle**, with "Help me recognise it", between one
  attempt and the next or on "I couldn't recognise this bottle.": the editor
  opens with an empty title. The button is there only if at least one
  identifying word has been read from the label, because next time the bottle
  is found from the words and the photo together, and without words it would
  never be found again.

The photo and the reading are fixed when the editor opens: if someone swaps the
bottle in the meantime, the correction stays attached to the right one. While
the editor is open the device does not look at the plate, and a forgotten
editor closes by itself after ten minutes (`CORREZIONE_TETTO_S`), as if the
cross had been touched.

### The editor

It covers the whole screen, flags and volume included. At the top are the
cross on the left, the name of the editor in the centre ("Correct this
bottle", "Edit the correction" or "Help me recognise it") and "Save" on the
right. Below is a line of notes, which normally says "Type the name and pick
the right wine, or write its description: next time I will recognise the
bottle.". Then come the photo just taken, the "Title" field and the
"Description" field, and at the bottom an Italian keyboard drawn by the page:

- the accented letters are on the keys (è, é, à, ò, ù, ì), the apostrophe next
  to the comma; "?123" switches to numbers and symbols (€, %, °, «», …) and
  "ABC" goes back to letters;
- the keys type as soon as you press them;
- capitals turn on by themselves at the start of a field, after a full stop
  and after a new line; a tap turns them off, a double tap locks them;
- the delete key, held down, keeps deleting;
- Enter in the title moves to the description, in the description it starts a
  new line;
- touching a field moves you there, to the point touched.

The title holds up to 120 characters, the description up to 2000.

**The title searches.** From the second letter on, in place of the description,
the bottles the device knows whose name contains the words typed appear (the
last word may be just the start of a word): first those already corrected,
then the wine list, then the archive, five at a time, up to twenty. Below each
one is its source: "corrected by hand", "wine list", "archive · wine", "archive
· type", "archive · appellation"; the archive's wines carry the winery next to
the name. In the archive, the names that begin the way you typed come first,
then the shortest: the appellation before the wines of individual producers.
The last box is "None of these": with "N more" underneath it moves to the next
ones, with "I'll write the description" underneath it returns to the
description field.

- **Choose a wine from the wine list or the archive**: the bottle is **linked**
  to it. The line of notes shows "Linked to: …" with a small cross to remove
  the link, and the description field says "Description (optional: if empty, I
  tell its own story)". Left empty, the bottle is told with the record of the
  linked wine: from the archive according to the storytelling mode, from the
  wine list with its description. Filled in, your description speaks.
- **Choose a bottle already corrected**: the photo of this reading is added to
  that correction instead of creating a duplicate; if the description is
  empty, it is filled with that correction's own.
- **Retype the title after a choice**: the link is removed by itself.

If the bottle resembles one already corrected without having been recognised,
when the editor opens the line of notes asks "Is it one of these?" and shows up
to three candidates, each with its photo and its title. Touching one means
that it is the one: title and description are filled with its own, and on
saving the photo is added to that correction. Touching it again cancels the
choice.

Without a link the description is mandatory. "Save" with a missing field
writes "Please write a title" or "Please write a description" in the line of
notes and outlines that field in red. The device tells a correction by opening
with a sentence that names it ("This is a …") and then reading the description
as it is: there is no need to repeat the name at the start.

### Saving, and the other language

"Save" writes "Saved. I will recognise it." in the line of notes, the editor
closes and the bottle is told immediately with the new text: that is the proof
that the correction works. The text applies to the language the screen was in
when the editor was opened.

If the correction has a description, before closing the editor asks, in the
language of the screen, whether you want it in the other language too: "Would
you like to write the description in Italian too?" with the screen in English,
"Vuole scrivere la descrizione anche in inglese?" with the screen in Italian.
The story waits for the answer. "Yes, I'll write it" reopens the editor on the
same correction, titled "Description in Italian" (with the screen in Italian,
"Descrizione in inglese"), with the title already written, because the name of
a wine is usually not translated, and with the description that was there, if
there was one; saving it does not add another photo. "No, thanks", or the
cross, tells the bottle as it is; the cross in the second-language editor also
tells what has already been saved. Without a description (a bottle that is
only linked) the question is not asked: the record of the linked wine already
speaks every language.

If you close the editor with the cross without having saved anything, an
interrupted story is considered finished (the final screen, then the waiting
screen; the bottle on the plate is not read again); from an unrecognised bottle
the device resumes from where it had stopped.

### How it is recognised next time

A correction is looked up before the archive, the model and the wine list, in
any storytelling mode. A bottle is the corrected one when:

- at least two of the saved identifying words, and at least six in ten, are
  read again, and the image confirms it (at least 16 points of the label found
  again); or
- the image alone is very similar (at least 30 points), even if this time the
  OCR read only one of the saved words again.

Identifying words have at least four letters, letters only, and are not among
those found on thousands of labels ("rosso", "brut", "spumante"). The image is
compared only in the label area, so the background of the room, which is
always the same, does not make two different bottles look alike. The
thresholds are in `Regola` (`src/amelie/correzioni.py`), the reasoning in
[06-recognition.md](06-recognition.md).

Each save adds the photo of that reading as an extra view: if a corrected
bottle is not recognised, turned around or in a different light, reopen it and
choose it from "Is it one of these?" or from the "corrected by hand"
suggestions.

In a language in which the correction has no description, the bottle speaks
with the record of the linked wine; without a link it is told as if the
correction did not exist. The button stays "Edit the correction", so the
missing text can be added.

### Where they are stored, and how to delete them

Each correction is a folder in `var/correzioni/<id>/` (on the board
`/home/arduino/amelie/var/correzioni/`), where `<id>` is the date and time of
creation, `YYYYMMDD-hhmmss`:

- `correzione.json`: the creation and modification dates (`creata`,
  `modificata`), the texts per language (`testi`, with `titolo` and
  `descrizione`), the link (`riferimento`) and the views (`viste`: photo,
  lines read, words, label area);
- `vista-1.jpg`, `vista-2.jpg`…: the photos.

From the screen a correction can be edited but not deleted. To remove it, on
the board:

```bash
rm -r ~/amelie/var/correzioni/<id>
sudo systemctl restart amelie.service
```

Corrections are loaded when the service starts: a hand edit to the JSON also
takes effect only after the restart. They are not in git: to keep them, copy
the folder.

## The wine list

The wine list is a hand-written file that makes the device tell the venue's
wines in the venue's own words. It is chosen from the settings as "Wine list".

### The format

A CSV file in UTF-8, with the comma as separator and a first row with the
column names. Put fields that contain commas in double quotes.

| Column | | Content |
|---|---|---|
| `titolo` | required | the name of the wine, as it is spoken and as it appears on screen |
| `descrizione` | required | the story in Italian, read as it is |
| `descrizione_en` | optional | the story in English; its presence adds English to the wine list |
| `titolo_en` | optional | the title in English; if missing, the Italian one is used |

```csv
titolo,descrizione,titolo_en,descrizione_en
"Barolo DOCG","La descrizione in italiano, letta così com'è.","Barolo DOCG","The English description."
```

A row with no title or no description is skipped; a row with an empty
`descrizione_en` has no English. The device opens with a sentence that names
the title (for example "This is a Barolo DOCG.") and then reads the
description: start the description with the content, not with the name.

In a language the wine list does not have, the device tells what it finds in
the archive for the same label, instead of having the English voice read
Italian.

Mind how the file is saved. Some spreadsheets, when saving as CSV, use the
semicolon as separator, or put the BOM mark at the start of the file: in those
cases the device does not find the `titolo` column, discards every row and
starts without a wine list. A file in another encoding (for example
Windows-1252) that contains accented letters, on the other hand, stops the
service from starting. Before using it, test it on the board with the same
code that reads it:

```bash
cd ~/amelie && PYTHONPATH=src ./venv/bin/python -c "from amelie.carta import Carta; c = Carta('/home/arduino/carta.csv'); print(len(c.voci), 'voci, lingue:', ' '.join(sorted(c.lingue)))"
```

A good file answers with the number of entries and the languages, for example
`48 voci, lingue: en it` (48 entries, languages: en it); `CartaVuota` means
a wrong separator, BOM or column names, `UnicodeDecodeError` a file that is not
in UTF-8.

### Where it lives

The service loads it with the `--carta` option. In the installed unit
(`scripts/systemd/amelie.service`, copied to `/etc/systemd/system/`) it is:

```
--carta /home/arduino/amelie/vini.csv
```

that is, `vini.csv` in the project folder on the board, the same file that
sits at the root of the repository: an example wine list of Italian
appellations and types, in Italian only. The wine list is read when the
service starts: after editing it, `sudo systemctl restart amelie.service`.

The most direct way is to rewrite `vini.csv`. It is, however, a file of the
repository: if an update changes it, `git pull` stops so as not to overwrite
yours. To keep the venue's wine list safe from updates, put it in a file of
your own, for example `/home/arduino/carta.csv`, and point to it with an
addition to the unit, which the installer does not touch:

```bash
sudo systemctl edit amelie.service
```

In the editor that opens, in the space marked at the top, write:

```ini
[Service]
ExecStart=
ExecStart=/home/arduino/amelie/venv/bin/python -m amelie.app --porta 8080 --con-modello --modello-addestrato --carta /home/arduino/carta.csv
```

Save, then `sudo systemctl restart amelie.service`. The empty `ExecStart=` line
clears the unit's command, the next one writes it again with the new file.
Editing the unit in `/etc/systemd/system/` by hand, instead, does not last: on
every run the installer puts back the one from the repository.

If the file is missing or has no usable rows, the device starts anyway: the
system journal shows the line
`carta dei vini non caricata (…): uso l'archivio` (wine list not loaded (…):
using the archive), the "Wine list" mode does not appear in the settings and a
saved `carta` mode falls back to the archive. `/stato` reports the file name
(`carta`) and how many entries it loaded (`voci_in_carta`).

### What has not been read is not named

In wine list mode a bottle is recognised only by its title: no cascade and no
fallback to the archive (corrections still apply, and come first). If no title
fits, the bottle is not recognised. A title may be said only if its words are
on the glass:

- every word of the title with at least three letters must have been read,
  including those that distinguish one wine from another ("Riserva",
  "Classico", "Extra Brut"), with two exceptions:
  - the appellation marks, which are printed small on the label: DOC, DOCG,
    DOP, IGT, IGP, AOC, AOP, AVA, DOCa, VdP, QbA, and "Annata";
  - words that in the file always accompany the ones read: if the only entry
    with "Brunello" is "Brunello di Montalcino DOCG", "Montalcino" is implied.
    The words taken as implied cannot outnumber the identifying words actually
    read;
- among the titles that may be said, the one with the most words read wins,
  and on a tie the one with the fewest words not read.

A wine list gets it wrong while telling the story beautifully: its descriptions
are long and convincing, and attaching one to the wrong bottle is the worst
mistake. Hence two practical tips. Write titles with the words that are really
on the labels. And next to the specific entries keep a generic entry for the
appellation ("Champagne AOC" next to "Champagne Extra Brut"): if the
distinguishing word cannot be read, the bottle still finds a true entry instead
of remaining unrecognised. The details of the algorithm are in
[06-recognition.md](06-recognition.md).

## Diagnostics

### The scan log

Every scan that gets as far as reading, successful or not, leaves a line in
`var/scansioni/giornale.jsonl` and, next to it, the frame that was read, in
`var/scansioni/YYYYMMDD-hhmmss-mmm.jpg` (the name is in the line's `immagine`
field); a camera or OCR fault before the reading ends up only in the system
journal. Each line contains:

- when (`quando`), in which language (`lingua`), and the outcome (`esito`):
  `raccontato` (told), `niente da leggere` (nothing to read), `letto ma non
  riconosciuto` (read but not recognised), `non in carta` (not in the wine
  list), or `chiuso da <evento>` (closed by an event) when the scan is
  interrupted before the story (`chiuso da bottiglia_assente` if the bottle was
  removed, `chiuso da annulla` after Cancel);
- the lines read (`righe`), the sharpness, the exposure, the attempt, the
  capture and OCR seconds (`scatto_s`, `ocr_s`), and whether the reading was
  widened (`allargata`) or done in advance during the story (`anticipata`);
- level and confidence of the recognition, name, winery, vintage, *tipologia*,
  appellation, colour, candidates; in wine list mode, when the bottle is not
  found, the closest titles with their similarity (`vicine`); for a correction
  its identifier (`correzione`) and the reason (`perche_correzione`);
- where the story comes from (`racconto_da`: `template` for the composition
  from the facts, `modello`, `cache` for a ready-made text, `carta`,
  `correzione`) and the text spoken (`racconto`).

When a story starts again (a language change, a saved correction) a
`raccontato` line is added with only the new story. The latest lines can be
read on the board with `tail -n 3 ~/amelie/var/scansioni/giornale.jsonl`, or
with `GET /giornale` (below).

The photos of the latest 120 scans are kept (`IMMAGINI_TENUTE` in
`src/amelie/giornale.py`; the oldest are deleted), and the log, beyond 4 MB,
rotates into `giornale.1.jsonl`, which keeps only the previous copy: the
board's storage is flash, and an archive that grows forever becomes a fault.
If the log cannot be written the device keeps telling stories. Dates and times,
here and in the names of corrections, come from the board's clock.

### HTTP routes

The service listens only on the board, on `127.0.0.1:8080`: it cannot be
reached from the network. From the board:

```bash
curl -s localhost:8080/stato | python3 -m json.tool
```

From a PC, first open a tunnel and then use `localhost:8080` the same way:

```bash
ssh -L 8080:localhost:8080 arduino@<board-name>.local
```

| Route | What it returns |
|---|---|
| `GET /stato` | the technical state, the same as in the settings |
| `GET /pronto` | `{"pronta": true}` when the voices are loaded, `false` before |
| `GET /giornale?quante=N` | the last N scans (from 1 to 200, default 20), most recent first, in the `voci` field |
| `GET /giornale/<nome>.jpg` | the frame of a scan, with the name written in its line |
| `GET /batteria` | bars, fraction, energy used, capacity, estimated hours |
| `GET /lingue` | the language in use and the available ones |
| `GET /mirino/lettura`, `GET /mirino/flusso` | with the Debug camera on: the reading as JSON and the video |

Commands are sent as POST, for example
`curl -s -X POST localhost:8080/prova/bottiglia`. They answer in JSON;
`"ok": false` means there was nothing to do, often with the reason.

| Command | What it does |
|---|---|
| `POST /annulla` | same as the story's cross |
| `POST /racconto/<azione>` | same as the story's circles: `ricomincia` (restart), `indietro` (back), `alterna` (pause and resume), `avanti` (forward); there are also `pausa` and `riprendi` |
| `POST /lingua/<it\|en>` | same as touching a flag, announcement included |
| `POST /volume/<0-100>` | sets the volume |
| `POST /modo/<archivio\|generativa\|carta>` | changes the storytelling mode |
| `POST /correzioni/<1\|0>` | turns "Add corrections" on or off |
| `POST /mirino/<1\|0>` | turns the Debug camera on or off |
| `POST /batteria/ricaricata` | same as "Battery recharged" |
| `POST /ripristina` | same as "Restore operation" |
| `POST /prova/<bottiglia\|via\|camera>` | fakes a bottle on the plate, or the empty plate; `camera` goes back to the real sensor |

`/prova` is for bench testing: it lets you test reading, story, voice and
screen without touching the plate; the camera still photographs whatever is in
front of it. Remember to finish with `/prova/camera`, otherwise the device keeps
believing what you told it; a restart of the service forgets it anyway.

The other routes (`/`, `/eventi`, `/fonts/…`, `/correzione/…`) serve the
screen's page.

### What the device remembers

Everything lives in `var/`, the only project folder the service can write to.
Settings files and corrections are written in a way that survives a power cut;
deleting a settings file restores the default value.

| File | Contents |
|---|---|
| `var/volume` | the volume |
| `var/modo` | the storytelling mode |
| `var/correzioni_attive` | the "Add corrections" switch |
| `var/batteria.json` | the battery estimate |
| `var/sfondo.npy` | the empty plate as seen by the camera, which updates itself whenever the sensor says the plate is empty |
| `var/correzioni/` | the corrections |
| `var/scansioni/` | the log and the frames |

The language and the Debug camera are not remembered: at power-on the device
tells stories, in Italian.

## When something goes wrong

### The isolated fault

When a step of the work fails (the camera gives no frame, the OCR does not
start, a reading does not come back within its time limit: 50 seconds to read,
15 to look for the wine), the screen shows the ⚠ symbol and "Something went
wrong. I'll try again in a moment.", with the light red. After six seconds the
screen returns to waiting; if the bottle is still on the plate, the device
reads it again, up to three attempts in all (`TENTATIVI_MAX`). You do not need
to do anything. If the camera stops delivering frames with a long exposure, it
restarts by itself from the starting exposure.

### Automatic recovery

Three faults within three minutes (`GUASTI_PER_RIPRISTINO` within
`FINESTRA_GUASTI_S`) mean that something has really jammed. Then the device
recovers by itself, exactly as with "Restore operation":

1. it stops the story, the announcement, the open editor and the Debug camera;
2. it waits up to five seconds for the work in progress and, if that does not
   finish, lets it go;
3. it puts the camera back as it was at power-on: stream closed, starting
   exposure, device searched for again;
4. it closes and reopens the audio output;
5. in "Written on the spot" mode, it restarts the model;
6. it resets the attempts and returns to waiting; a bottle still on the plate
   is read again.

### Restarting the service

If the faults come back within ten minutes of a recovery
(`DOPO_RIPRISTINO_S`), recovering was not enough: the process exits and
systemd restarts it after five seconds (`Restart=always` and `RestartSec=5` in
`scripts/systemd/amelie.service`); in about forty seconds the device is ready
again, voices included. It is what you would get by switching off and on
again, without switching off. It happens only under systemd; launched by hand,
the service just recovers. By hand:

```bash
sudo systemctl restart amelie.service
journalctl -u amelie.service -f
```

In the system journal the steps can be recognised by the lines `ripristino (…)`
(recovery) and `riavvio del servizio: …` (service restart).

### Symptoms and remedies

| Symptom | Where to look |
|---|---|
| at power-on the logo stays and "Ci vuole più del solito." / "This is taking longer than usual." appears | the service has not started, or has not finished getting ready: `systemctl status amelie.service` and `journalctl -u amelie.service -b`. A wine list that is not in UTF-8 stops it from starting ([The format](#the-format)) |
| the bottle does not trigger anything | if it was left on the plate after a story, after Cancel or after three attempts, the device waits for it to be removed: lift it and put it back. Otherwise the distance sensor decides, and it alone: with `mcu: false` in `/stato`, or `distanza: false` among the `moduli`, the device sees no bottle: see [The microcontroller](04-testing.md#the-microcontroller). The sensor works with infrared and may not see very pale glass |
| the voice cannot be heard | look at the volume icon (the slash means zero) and at `voce` in `/stato`: `false` means the model of that language's voice is missing, and the system journal has the line `voce … non caricata` (voice … not loaded). Then touch the flag already active: if the announcement cannot be heard, the problem is in the audio. Do not test the audio with `aplay` while the service is running: the service keeps the output open, and a second program finds it busy |
| "In this language the story is written, not spoken." | the chosen language has no voice in `VOCI` (`src/amelie/speech.py`) |
| a mode does not appear in the settings | "Written on the spot" requires `--con-modello`; "Wine list" requires a loaded wine list (if it is not loaded, the system journal says why) |
| readings fail, or the label goes outside the box | turn on the Debug camera and look at the box, the sharpness and the lines read; then at the scan log |
| the dot in the bottom right of the screen is red | the microcontroller does not respond (`mcu: false` in `/stato`: see [The microcontroller](04-testing.md#the-microcontroller)), or the page has lost its connection to the service: in that case it reconnects by itself when the service responds, and if that is not enough `sudo systemctl restart amelie-kiosk.service` |
| "Something went wrong" keeps repeating | "Restore operation", then the system journal |
