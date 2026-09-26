# Using Amelie

Amelie tells the story of the wine you set in front of it: it reads the label
with the camera, recognizes the bottle and tells its story on the screen and
aloud, in Italian or English, without any connection.

This guide describes what the people at the table see and can do, what the
person who runs the device finds in the settings, and where to look when
something goes wrong. Phrases in quotation marks are the exact wording on the
screen (`data/lessico/frasi.json`). How the device gets from the label to the
wine is in [06-recognition.md](06-recognition.md).

## The waiting screen

When the device is ready it shows the wine glass, the name, the phrase "Every
bottle has a story." and three steps, each with its own icon:

| | Italian | English |
|---|---|---|
| 1 | **Scegli** una bottiglia | **Choose** a bottle |
| 2 | **Posa** la bottiglia su Amelie | **Place** the bottle on Amelie |
| 3 | **Ascolta** la sua storia | **Listen** to its story |

The three steps are a sign, like the text on a notice board, and that is why in
Italian they use the informal "tu"; all other text addresses the guest with the
formal "Lei".

In the top right corner are the language flags, in the top left the volume
speaker. They are the only spots that respond to touch, together with a hidden
corner that opens the settings. The rest of the screen is inert on purpose: on
a table, an accidental touch is the norm. Every button acts when you lift your
finger, and only if the finger is still over it: a touch started by mistake is
canceled by sliding away.

At power-on the logo appears first on its own, and stays until the voices are
loaded: that way the first bottle finds the voice already ready.

## A bottle, from start to finish

### Placing it

Whether there is a bottle is decided by the distance sensor, and by it alone;
the camera is there to know where the label is. As soon as you set the bottle
down the screen says "Let me have a look…", then "I'm reading the label…" while
the camera takes the picture and the OCR reads, and "One moment…" while it looks
for the wine. Meanwhile an animation shows a bottle pouring into a glass.

Place the bottle with the label facing the camera: a label turned sideways reads
poorly, or not at all.

### The story

The story screen shows:

- at the top the **title**: the name of the wine, or the *tipologia* (the wine
  type within an appellation), the appellation (*denominazione*) or the grape
  variety when recognition stops there; below it, winery and vintage, if known;
- the full **text**, with the sentence the voice is speaking highlighted; the
  text scrolls by itself to keep it in view;
- a **bar** that fills up until the end of the story;
- the **controls**, and the Cancel cross in the bottom left.

The first sentence says how sure the device is: "This is the …" when
recognition is certain, "I'd say the …" or "It should be the …" when it is a
guess. When the label can be read but there is nothing in the archive that can
be named, the device says only what is written on the bottle (for example that
it is a rosé sparkling wine, brut) and closes with "This bottle is not in my
archive; the description was generated independently, from the data and
catalogue available to me."

If there is no voice for the chosen language, the story is only read: the text
scrolls by itself at reading pace, controls and bar disappear, and at the
bottom "In this language the story is written, not spoken." appears.

### The story controls

| Control | Where | What it does |
|---|---|---|
| Restart | first circle | starts the story again from the beginning |
| Back | second circle | goes back 5 seconds |
| Pause / resume | large circle | stops the voice; touched again, it resumes from there |
| Forward | fourth circle | skips ahead 5 seconds |
| Cancel | cross in the bottom left | closes the story and returns to the waiting screen |

When the story is over, the text stays on screen for a moment and then the
waiting screen returns. In that moment the circles have nothing left to
control, and they turn off at the first touch.

**Cancel** is for someone who has already poured and wants silence without
lifting the bottle again. It also works when the story has not started yet (for
example while the model is writing). After Cancel the language stays the one
chosen, and the bottle left on the plate is not read again: the device waits
for it to be removed.

A pause does not hold the device forever: past a cap
(`TETTO_RACCONTO_S` in `src/amelie/app.py`) the story stops, the text
stays on screen with the controls off, and you leave with Cancel.

### Removing the bottle

| When you remove it | What happens |
|---|---|
| during "Let me have a look…", the reading or the request to turn the label | the round is interrupted and the waiting screen returns |
| during the story | the story continues to the end |
| on the final story screen | the waiting screen returns immediately |
| after the return to the waiting screen | nothing: the next bottle placed starts a new round |

The story continues because someone who lifts the bottle to pour has not asked
for silence: a story that dies mid-sentence is more noticeable than one that
ends. To silence the device there is Cancel.

### Putting the same bottle back

If you put it back while the story is playing, the device looks at it right
away, without stopping the voice. If the photo finds the previous label again,
or the words read are the same, the story goes on and at the end the bottle is
not read again. Two labels of the same wine, front and back, count as the same
bottle, because they tell the same story. If the new reading yields no words
the device cannot decide: it lets the story finish and reads the bottle again
afterwards.

If you put it back when the screen has already returned to waiting, it is a new
round and the story starts over from the beginning. It is also the way to hear
a bottle again.

### Swapping it for another

A different bottle placed during the story, or on the final screen, is read
immediately while the voice is still talking about the previous one. As soon as
the words read say it is a different wine, the voice stops and the story of the
new one starts, already read: no new photo is needed. The decision is made by
the text, not by the photo: the photo can quickly tell that a bottle is the
same, but a bottle put back turned around matches few points of the previous
label, and from that alone one cannot conclude that it is a different one.

### The bottle that is not recognized

Two cases lead to the same screen: the OCR finds no words, or it finds words
but no wine (in "Wine list" mode: no entry in the list). The screen shows
"Could you turn the label towards me?", the ring turns red, and after a few
moments the device tries again with a new photo: that is the moment to turn the
bottle.

After three failed readings (`TENTATIVI_MAX`) the device stops:

- with "Add corrections" on and at least one identifying word read, "I couldn't
  recognise this bottle." appears with the "Help me recognise it" button, and
  the screen stays long enough for you to reach it
  (`CONCLUSO_CON_CORREZIONE_S`);
- otherwise the waiting screen returns immediately.

In both cases the bottle left on the plate is not read again: to try again,
lift it and put it back. Without this cap any object left on the plate (a
glass, a bottle with no label) would keep camera, ring and OCR running all
evening. With corrections on, "Help me recognise it" also appears between one
attempt and the next, below the request to turn the label.

### The light ring

| Moment | Ring |
|---|---|
| waiting screen, reading, wine search | amber |
| capture with the camera stopped | white, only for the duration of the capture |
| bottle just placed, story, final screen (including "I couldn't recognise this bottle.") | green |
| "Could you turn the label towards me?", fault | red |
| Debug camera on | white |

Normally the camera is already running when the bottle arrives, and the frame
is taken from the stream without switching to white.

## Languages

The flags are in the top right on every screen, the story screen included. The
one for the language in use is full, with a gold ring; the others are dimmed.

- **You touch the other flag**: the text changes immediately and the device
  confirms it aloud with "Lingua italiana. Da adesso racconto i vini in
  italiano." or "English language. From now on I will describe the wines in
  English." Outside the story screen the sentence also appears written at the
  bottom, like a subtitle. If a story is playing, it stops and, once the
  announcement is over, starts again from the beginning in the new language:
  same wine, without putting the bottle back.
- **You touch the flag already active**: nothing changes, but the announcement
  is made anyway. It is the quickest way to test voice and speakers without a
  bottle.
- **You touch while an announcement is speaking**: the announcement is
  interrupted and the one for the language just chosen starts.

The starting language is Italian (`Configurazione.lingua` in
`src/amelie/app.py`; there is no command-line option). The device goes back to
it by itself, without announcing it, when the bottle is removed from the plate:
whoever comes next finds the house language. As long as the bottle stays on the
plate the chosen language stays: after the story ends, after Cancel, after a
fault, because the same people are still at the table.

Touching a flag just after the story has ended keeps the story screen up a few
seconds longer (`LINGUA_A_RACCONTO_FINITO_S`), so that the announcement and the
story in the new language have time to arrive.

Names of wines, wineries and vintages are not translated: they are what is
printed on the bottle. A wine list or a correction with no text in the chosen
language lets the archive speak (see the relevant sections).

## Volume

Touch the speaker in the top left: a slider opens. Drag the knob, or touch the
point on the track you want. The slider closes by itself after a few moments
without touches, and when the screen changes.

- **The icon shows the level even when the control is closed**: two waves from
  halfway up, one below halfway, none and a slash at zero. At zero the device
  tells the story anyway, silently.
- **When your hand stops** the device plays a little tap on a wine glass at the
  new level, so you can adjust it without placing a bottle. While it is telling
  a story or announcing a language there is no tap: the level can already be
  heard.
- **The scale goes from 0 to 100 and the gain is the square of the value**:
  halfway is about −12 dB, which to the ear is "half volume". 100 is the
  maximum the digital signal carries without distortion, and it does not go
  beyond that.
- **It is remembered** from one power-on to the next (`var/volume`). The
  service's `--volume` option applies only when there is no saved value.

The audio chain has no hardware volume control: the sound leaves the board over
HDMI and reaches the speakers through the screen. What is adjusted is the
signal, an instant before the output. If the service starts without voice
(`--senza-voce`) the control does not appear.

## Settings

### How to open them

Hold your finger still **on the bottom-right corner** of the screen for **three
seconds**. The sensitive area is a small square in the corner; if the finger
moves beyond a small tolerance (`ANGOLO_SCARTO` in `index.html`) the gesture
is canceled and must be repeated. It works from the screens of the cycle
(waiting, reading, story, notices). The entry point is hidden on purpose: if it
could be reached with a single tap, someone setting down a bottle would open it
by mistake.

The panel covers the screen, the list scrolls with the finger, and it closes
with the cross in the bottom left, in the same place as Cancel. It does not
stop the device: a bottle placed in the meantime is read and told underneath.
The rows, from the top:

### How it tells

| Mode | Where the text comes from | When it appears |
|---|---|---|
| "From the archive" (default) | composed from the archive data and the production specification (*disciplinare*), without a model: it does not invent and it is immediate | always |
| "Written on the spot" | the same data, but the text is written by the language model for that bottle; experimental, it can make mistakes and makes you wait | only if the service starts with `--con-modello` |
| "Wine list" | the hand-written descriptions in the wine list file, and only for the wines it contains | only if a wine list is loaded with `--carta` |

The difference between the modes is not one of style, it is the source of what
the device says. The chosen mode has the check mark, applies from the next
bottle (changing it mid-reading would interrupt the listener) and is remembered
in `var/modo`. A saved mode the device can no longer serve (the wine list
missing, the model not enabled) falls back to the archive.

In "Written on the spot" mode:

- choosing the mode starts `amelie-llm.service`, choosing another one stops it:
  even when idle the model takes up a core that the OCR needs;
- while the model is writing, "I'm writing the description…" appears in place
  of the text, with a small wine glass;
- what the model writes goes through a check; if it invents twice in a row, the
  ready-made text for that wine is used, if there is one, and otherwise the
  composition from the facts. It falls back the same way if the model does not
  respond;
- when all that is known is what is written on the label, the model never
  writes: the composition is told.

Hand corrections take precedence in all three modes.

### Add corrections

Off until you turn it on, and it stays as it is even after a reboot
(`var/correzioni_attive`). When it is on, every story shows "Correct this
bottle" below the title, or "Edit the correction" on a bottle already
corrected, and unrecognized bottles offer "Help me recognise it"; the final
screen stays up longer, to leave time to reach the button. When it is off, no
guest sees a button to correct, but corrections already saved are still
recognized. The change also applies immediately to the story on screen;
turning it off with the editor open closes the editor without saving. Apart
from the switch there is no PIN.

### Debug camera

Shows full screen what the camera sees and what it manages to read, to
fine-tune the framing:

- on the video, the **box** that goes to the OCR (nothing outside it is read),
  with the two center lines to center the label and the text `nitidezza N
  (soglia S)` ("sharpness N (threshold S)"): green above the threshold, red
  below;
- on the side, "What it reads" with the lines found (the first ten; "no line of
  text" if there are none) and "What it finds" with level, confidence, wine and
  candidates, plus sharpness and exposure. This column queries the archive, not
  the wine list or the corrections.

Turning it on **stops the cycle**: the camera can be used by only one process
at a time, so there are no stories and no readings while it is on. The ring
goes white and the exposure is searched for once, so you frame with the light
that will really be there. You leave the screen only with the "back to the story"
button at the bottom, because the debug camera covers the panel; on leaving, a
bottle left on the plate is read immediately, and that is the proof that the
framing works. It is not remembered from one startup to the next, and the row
does not appear if there is no camera.

To watch from a PC on a large screen there is also `scripts/mirino.py`, with
the same logic, to be run with the service stopped.

### Battery recharged

The power bank reports nothing: the device estimates how much energy it has
used from how long it has been on and how hard the CPU is working, against a
usable capacity declared in `CAPACITA_WH` (`src/amelie/batteria.py`). The
estimate is shown only here, as a four-bar icon; without a number, because it
is an estimate. The last bar disappears before zero, where the power bank may
shut off without warning; at zero bars the outline turns red.

Touch the row after recharging: the estimate restarts from full. At power-on
the device does this by itself if it has been off long enough to assume an
overnight charge (`RICARICATA_DOPO_S`); after a short reboot the estimate
resumes from where it was.

### Restore operation

Restarts camera, reading and voice without switching off, when "Something went
wrong. I'll try again in a moment." keeps repeating. The row shows that the
work is in progress, then a check mark, and the panel closes. What it does is
described in [When something goes wrong](#when-something-goes-wrong).

### Technical state

Opens the contents of `/stato` above the panel, to be read without a keyboard;
"close" returns to the settings. The most useful fields:

| Field | What it says |
|---|---|
| `stato` | the state of the state machine (`attesa` (waiting), `racconto` (story)…) |
| `mcu`, `protocollo`, `moduli` | whether the microcontroller responds, with which protocol, and whether it sees the ring and the distance sensor |
| `camera`, `posa` | whether the camera is there, and the exposure in use |
| `bottiglia`, `differenza`, `soglia` | whether the sensor sees a bottle, and how much the plate differs from the empty plate, compared with the threshold |
| `voce`, `volume`, `pronta` | whether the voice is loaded, the volume, whether the device has finished getting ready |
| `modo`, `racconti_generati`, `carta`, `voci_in_carta` | the storytelling mode, whether the model writes the text, the wine list file and how many entries it contains |
| `ultimo_livello`, `sicurezza` | the outcome of the last recognition |
| `transizioni` | the latest state transitions |

## Corrections

A correction teaches the device a bottle: what to say about it, or which known
wine it corresponds to. It requires "Add corrections" to be on.

### Opening the editor

- **From a story**, with "Correct this bottle" (or "Edit the correction" on a
  bottle already corrected). The voice stops. On a bottle already corrected
  the editor reopens the correction as it is. Otherwise, if the device has
  recognized a wine, a tipologia or an appellation from the archive, or a wine
  list entry, the editor opens already linked to it, with its name in the
  title; if not, with an empty title.
- **From an unrecognized bottle**, with "Help me recognise it": the editor
  opens with an empty title. The button is there only if at least one
  identifying word has been read from the label, because next time the bottle
  is found from the words and the photo together, and without words it would
  never be found again.

The photo and the reading are fixed when the editor opens: if someone swaps the
bottle in the meantime, the correction stays attached to the right one. While
the editor is open the device does not look at the plate, and a forgotten
editor closes by itself (`CORREZIONE_TETTO_S`).

### The editor

It covers the screen: the photo just taken, the **title** field, the
**description** field and an Italian keyboard drawn by the page, with the
accented letters on the keys, the apostrophe next to the comma and "?123" for
numbers and symbols (€, %, °, «»). Capitals turn on by themselves at the start
of a field and after a period; a double tap locks them; the delete key, held
down, keeps deleting. Enter in the title moves to the description.

**The title searches.** From the second letter on, in place of the description,
the bottles the device knows whose name contains the words typed appear (the
last word as the start of a word): first those already corrected, then the
wine list, then the archive, five at a time. Below each one is its source:
"corrected by hand", "wine list", "archive · wine", "archive · type", "archive ·
appellation". In the archive, the names that begin the way you typed come
first, then the shortest: the appellation before the wines of individual
producers. The last box is "None of these": with "N more" underneath it moves
to the next ones, with "I'll write the description" underneath it returns to
the description field.

- **Choose a wine from the wine list or the archive**: the bottle is **linked**
  to it. Above the fields "Linked to: …" appears, with a small cross to remove
  the link, and the description field says "Description (optional: if empty, I
  tell its own story)". Left empty, the bottle is told with the record of the
  linked wine: from the archive according to the storytelling mode, from the
  wine list with its description. Filled in, your description speaks.
- **Choose a bottle already corrected**: the current photo is added to that
  correction instead of creating a duplicate.
- **Retype the title after a choice**: the link is removed by itself.

If the bottle resembles one already corrected without having been recognized,
when the editor opens it asks "Is it one of these?" with the photos of the
candidates: touching one means "that's the one".

Without a link the description is mandatory: "Save" writes "Please write a
title" or "Please write a description" and highlights the missing field. The
device tells a correction by opening with a sentence that names it ("This is
…") and then reading the description as it is: there is no need to repeat the
name at the start.

### Saving, and the other language

"Save" shows "Saved. I will recognise it.", the editor closes and the bottle is
told immediately with the new text: that is the proof that the correction
works. The text applies to the language the screen was in when the editor was
opened.

If you wrote a description, before closing the editor asks "Would you like to
write the description in Italian too?" (or in English, if you wrote it in
Italian), and the story waits for the answer. "Yes, I'll write it" reopens the
editor on the same correction, titled "Description in Italian" (or "in
English"), with the title already written and the description that was there,
if there was one; it does not add another photo. "No, thanks", or the cross, tells the bottle as it is. Without a description (a
bottle that is only linked) the question is not asked: the record of the linked
wine already speaks every language.

If you close the editor with the cross without having saved anything, an
interrupted story is considered finished; from an unrecognized bottle the
device resumes from where it had stopped.

### How it is recognized next time

A correction is looked up before the archive, the model and the wine list, in
any storytelling mode. A bottle is the corrected one when:

- most of the saved identifying words, and at least two, are read again, and
  the image points found again on the label confirm it; or
- the image alone is very similar, even if this time the OCR misread the
  words.

Identifying words have at least four letters and are not among those found on
thousands of labels ("rosso", "doc", "brut"). The image is compared only in
the label area, so the background of the room, which is always the same, does
not make two different bottles look alike. The thresholds are in `Regola`
(`src/amelie/correzioni.py`), the reasoning in
[06-recognition.md](06-recognition.md).

Each save adds the current photo as an extra view: if a corrected bottle is not
recognized, turned around or in a different light, reopen it and choose it from
"Is it one of these?" or from the "corrected by hand" suggestions.

In a language in which the correction has no description, the bottle speaks
with the record of the linked wine; without a link it is told as if the
correction did not exist. The button stays "Edit the correction", so the
missing text can be added.

### Where they are stored, and how to delete them

Each correction is a folder in `var/correzioni/<id>/` (on the board
`/home/arduino/amelie/var/correzioni/`), where `<id>` is the date and time of
creation:

- `correzione.json`: the texts per language (`titolo`, `descrizione`), the
  link (`riferimento`) and the views (photo, lines read, words, label area);
- `vista-1.jpg`, `vista-2.jpg`…: the photos.

From the screen a correction can be edited but not deleted. To remove it:

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

A UTF-8 CSV, comma-separated, with a header row. Put fields that contain commas
in double quotes.

| Column | | Content |
|---|---|---|
| `titolo` | required | the name of the wine, as it is spoken and as it appears on screen |
| `descrizione` | required | the story in Italian, read as it is |
| `descrizione_en` | optional | the story in English; its presence adds English to the wine list |
| `titolo_en` | optional | the title in English; if missing, the Italian one is used |

A row with no title or no description is skipped. The device opens with a
sentence that names the title (for example "This is a Barolo DOCG.") and then
reads the description: start the description with the content, not with the
name.

In a language the wine list does not have, the device tells what it finds in
the archive for the same label, instead of having the English voice read
Italian.

### Where it lives

The service loads it with the `--carta` option. In
`scripts/systemd/amelie.service` (installed in `/etc/systemd/system/`) it is:

```
--carta /home/arduino/amelie/vini.csv
```

that is, `vini.csv` in the project folder on the board, the same file that sits
at the root of the repository. The repository contains an example one, in
Italian only. The wine list is read at startup: after editing it,
`sudo systemctl restart amelie.service`. To use another file, change the path
in the unit, then `sudo systemctl daemon-reload` and the restart.

If the file is missing, cannot be read or has no usable rows, the device starts
anyway: the system journal shows "carta dei vini non caricata (…): uso
l'archivio" ("wine list not loaded (…): using the archive"), the "Wine list"
mode does not appear in the settings and a saved "carta" mode falls back to the
archive. `/stato` reports the file name (`carta`) and how many entries it
loaded (`voci_in_carta`).

### What has not been read is not named

In wine list mode a bottle is recognized only by its title: no cascade and no
fallback to the archive. If no title fits, the bottle is not recognized. A
title may be said only if its words are on the glass:

- every word of the title with at least three letters must have been read,
  including those that distinguish one wine from another ("Riserva",
  "Classico", "Extra Brut"), with two exceptions:
  - the appellation marks, which are printed small on the label: DOC, DOCG,
    DOP, IGT, IGP, AOC, AOP, AVA, DOCa, VdP, QbA, and "Annata";
  - words that in the file always accompany the ones read: if the only entry
    with "Brunello" is "Brunello di Montalcino DOCG", "Montalcino" is implied.
    The words taken as implied cannot outnumber the identifying words actually
    read;
- among the titles that may be said, the one that accounts for the most words
  on the label wins, and on a tie the one that promises the fewest words that
  were not read.

A wine list gets it wrong while telling the story beautifully: its descriptions
are long and convincing, and attaching one to the wrong bottle is the worst
mistake. Hence two practical tips. Write titles with the words that are really
on the labels. And next to the specific entries keep a generic entry for the
appellation ("Champagne AOC" next to "Champagne Extra Brut"): if the
distinguishing word cannot be read, the bottle still finds a true entry instead
of remaining unrecognized. The details of the algorithm are in
[06-recognition.md](06-recognition.md).

## Diagnostics

### The scan log

Every scan, successful or not, leaves a line in `var/scansioni/giornale.jsonl`
and, next to it, the frame that was read, in `var/scansioni/<date-time>.jpg`.
Each line contains:

- when, in which language, and the `esito` (outcome): `raccontato` (told),
  `niente da leggere` (nothing to read), `letto ma non riconosciuto` (read but
  not recognized), `non in carta` (not in the wine list), `corretta a mano`
  (corrected by hand), or `chiuso da <evento>` (closed by an event) when the
  scan is interrupted (bottle removed, Cancel);
- the lines read, the sharpness, the exposure, the attempt, the capture and OCR
  times, and whether the reading was widened or done in advance during the
  story (`anticipata`);
- level and confidence of the recognition, name, winery, vintage, tipologia,
  appellation, color, candidates; in wine list mode, when the bottle is not
  found, the closest titles (`vicine`); for a correction its `id` and the
  reason;
- where the story comes from (`racconto_da`: `template` for the composition,
  `modello`, `cache`, `carta`, `correzione`) and the text spoken.

The photos of the latest scans are kept (`IMMAGINI_TENUTE`, the oldest are
discarded) and the log, beyond a certain size, rotates into
`giornale.1.jsonl`: the board's storage is flash, and an archive that grows
forever becomes a fault. If the log cannot be written the device keeps telling
stories. Dates and times, here and in the names of corrections, come from the
board's clock.

### HTTP routes

The service listens only on the board, on `127.0.0.1:8080`. From the board:

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
| `GET /pronto` | `{"pronta": true}` when the voices are loaded |
| `GET /giornale?quante=N` | the last N scans (from 1 to 200, default 20), most recent first |
| `GET /giornale/<nome>.jpg` | the frame of a scan, with the name written in its line |
| `GET /batteria` | bars, fraction, energy used, capacity, estimated hours |
| `GET /lingue` | the language in use and the available ones |
| `GET /mirino/lettura`, `GET /mirino/flusso` | with the Debug camera on: the reading as JSON and the video |

| Command | What it does |
|---|---|
| `POST /ripristina` | same as "Restore operation" |
| `POST /modo/<archivio\|generativa\|carta>` | changes the storytelling mode |
| `POST /lingua/<it\|en>` | same as touching a flag, announcement included |
| `POST /volume/<0-100>` | sets the volume |
| `POST /mirino/<1\|0>` | turns the Debug camera on or off |
| `POST /correzioni/<1\|0>` | turns "Add corrections" on or off |
| `POST /prova/<bottiglia\|via\|camera>` | fakes a bottle on the plate, or the empty plate; `camera` goes back to the real sensor |

`/prova` is for bench testing: it lets you test reading, story, voice and
screen without touching the plate. Remember to finish with `/prova/camera`,
otherwise the device keeps believing what you told it.

### What the device remembers

Everything lives in `var/`, the only project folder the service can write to.
Each file is written in a way that survives a power cut; deleting a settings
file restores the default value.

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
start, a reading does not come back within its time limit) the screen shows
"Something went wrong. I'll try again in a moment." with the ring red. The
screen times out by itself and returns to waiting; if the bottle is still on
the plate, the device reads it again, a limited number of times
(`TENTATIVI_MAX`). You do not need to do anything. If the camera stops delivering
frames with a long exposure, it restarts by itself from the starting exposure.

### Automatic recovery

Three faults in quick succession (`GUASTI_PER_RIPRISTINO` within
`FINESTRA_GUASTI_S`) mean that something has really jammed. Then the device
recovers by itself, exactly as with "Restore operation":

1. it stops the story, the announcement, the open editor and the Debug camera;
2. it waits briefly for the work in progress and, if that does not finish, lets
   it go;
3. it puts the camera back as it was at power-on: stream closed, starting
   exposure, device searched for again;
4. it closes and reopens the audio output;
5. in "Written on the spot" mode, it restarts the model;
6. it resets the attempts and returns to waiting; a bottle still on the plate
   is read again.

### Restarting the service

If the faults come back shortly after a recovery (`DOPO_RIPRISTINO_S`),
recovering was not enough: the process exits and systemd restarts it
(`Restart=always`). It is what you would get by switching off and on again,
without switching off. It happens only under systemd; launched by hand, the
service just recovers. By hand:

```bash
sudo systemctl restart amelie.service
journalctl -u amelie.service -f
```

In the system journal the steps can be recognized by the lines `ripristino (…)`
(recovery) and `riavvio del servizio: …` (service restart).

### Symptoms and remedies

| Symptom | Where to look |
|---|---|
| the bottle does not trigger anything | the distance sensor is the only thing that decides: with `mcu: false` in `/stato`, or `distanza: false` among the `moduli`, the device sees no bottle. The sensor works with infrared and may not see very pale glass |
| the voice cannot be heard | touch the flag already active: if the announcement cannot be heard, the problem is in the audio. Do not test the audio with `aplay` while the service is running: the service keeps the output open, and a second program finds it busy |
| "In this language the story is written, not spoken." | the voice for that language was not loaded: look at `voce` in `/stato` and at the system journal |
| a mode does not appear in the settings | "Written on the spot" requires `--con-modello`; "Wine list" requires a loaded wine list |
| readings fail, or the label goes outside the box | turn on the Debug camera and look at the box, the sharpness and the lines read; then at the scan log |
| the dot in the bottom right of the screen is red | the microcontroller does not respond (`mcu: false` in `/stato`), or the page has lost its connection to the service: in that case it reconnects by itself when the service responds, and if that is not enough `sudo systemctl restart amelie-kiosk.service` |
| "Something went wrong" keeps repeating | "Restore operation", then the system journal |
