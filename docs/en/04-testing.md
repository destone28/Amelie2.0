# Testing Amelie

How to check that the assembled device works, from the automatic check to the
full experience with a real bottle. Each test says what to expect and what to
do if the result is not right.

One rule applies throughout: **what the software reports is not what the
hardware does.** The screen is tested by looking at it, the audio by listening
to it. An `xrandr` that reports an active video mode and an `aplay` that plays
a file without errors prove nothing.

The tests are done with the device assembled and switched on. The commands are
typed on the board, in the terminal you open from the computer with
`ssh arduino@amelie.local` (see [Installing the software](02-install.md)), in
the project folder, `~/amelie`. Those with `sudo` ask for the `arduino` user's
password.

## The automatic check

After the installation and a reboot, wait until the screen shows the waiting
screen, less than a minute after power-on: before that some services are still
starting, and the script would report them as faults. Then, on the board:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

The script only reads: it changes nothing. It prints eight sections, under
their Italian names:

1. **Sistema** (system): the Debian version, the free space, the memory, the
   temperature;
2. **Installazione** (installation): Python environment, voices and model with
   their checksums, llama.cpp, database, wine list, firmware;
3. **Servizi** (services): that the services are enabled and active, and
   Amelie's graphical session;
4. **Applicazione** (application): that it responds, the microcontroller, the
   two Modulino boards, the camera, the voice;
5. **Schermo** (screen): the video output, the 1280x720 mode, the touch;
6. **Camera**: the USB camera;
7. **Audio**: the sound card, the sound path to HDMI and the cache of the
   sentences already spoken;
8. **Router verso il microcontrollore** (router to the microcontroller): the
   `arduino-router` service, which connects Linux to the microcontroller, and
   that App Lab starts no app at power-on.

Each item is **OK**, **ATTENZIONE** (warning) or **GRAVE** (serious); lines
without a label are information. GRAVE items say what will not work and,
almost always, what to do. At the end the **Riepilogo** (summary) counts the
items of the three kinds: everything is fine when there are no GRAVE items.
The report is kept in `/tmp/amelie-diagnostica.txt` until the next reboot.

The most common items, and what to do:

| Item | What to do |
|---|---|
| "l'applicazione non risponde su 127.0.0.1:8080: …" (the application does not respond) | if you have just switched on, wait a minute and run the script again; if it stays, look at the application's journal: `journalctl -u amelie -n 50` |
| "applicazione non ancora pronta (riprova fra qualche secondo)" (application not ready yet, try again in a few seconds) | it is loading the voices: run the script again in a few seconds |
| "… non abilitato (…): rilancia scripts/install.sh", "manca …: rilancia scripts/install.sh" (not enabled, or missing: run scripts/install.sh again) | run `bash scripts/install.sh` again |
| "il router risponde ma lo sketch di Amelie non gira sul microcontrollore: …" (the router answers but the Amelie sketch is not running on the microcontroller), "sul microcontrollore gira un firmware di un'altra versione …" (the microcontroller runs a firmware of another version) | upload the sketch and the loader again: `bash scripts/firmware.sh --sempre`. See [The microcontroller](#the-microcontroller) |
| "il microcontrollore non risponde: arduino-router fermo …" (the microcontroller does not respond: arduino-router stopped) | `sudo systemctl restart arduino-router`, then run the script again |
| "nessuna traccia di un firmware caricato e verificato: …" (no trace of an uploaded and verified firmware) | `bash scripts/firmware.sh` |
| "voce non caricata: il racconto si leggera' soltanto" (voice not loaded: the story will only be read) | the voices are missing: run `bash scripts/install.sh` again |
| "la camera non ha mai dato un fotogramma all'applicazione: …", "la camera non da' fotogrammi da … s: …" (the camera has never delivered a frame to the application; the camera has delivered no frames for … s) | the application receives no images from the camera: check the camera's USB cable and its socket on the hub, then `sudo systemctl restart amelie` |
| "nessuna camera USB: controlla il cavo della camera" (no USB camera: check the camera cable) | the camera's USB cable does not reach the hub |
| "… frasi rovinate nella cache della voce: …" (… damaged sentences in the voice cache) | a power cut has left some sentences already spoken empty: the service removes them at every start, `sudo systemctl restart amelie`. See [Audio](#audio) |

For the screen, touch, audio, the microcontroller and the Modulino boards, see
the sections below.

## The screen

Look at the panel: it must show Amelie's waiting screen, with the wine glass on
a dark background, full screen and with no pointer.

| Symptom | Cause | Fix |
|---|---|---|
| black, and the script says "modalita' 1280x720" (1280x720 mode) | the HDMI cable or the screen's power | check the HDMI cable and the screen's micro-USB cable |
| black, and the script says "modalita' 800x480: il pannello vuole 1280x720 …" (the panel wants 1280x720) | the panel produces no image at its native resolution | `sudo systemctl restart amelie-display`; if that is not enough, `sudo reboot` |
| small image in a corner, and the script reports another mode, for example 1920x1080 | the screen is not at 1280x720 | `sudo systemctl restart amelie-display`; if that is not enough, `sudo reboot` |
| the desktop appears | Amelie's session is not set (the script reports it as ATTENZIONE) | run `bash scripts/install.sh` again, then `sudo reboot` |
| the page does not change after an update | the kiosk loads the page only once, at start-up | `sudo systemctl restart amelie-kiosk` |

A screen that turns off takes the audio with it: the board's video bridge sets
up the audio only if it sees the screen on. That is why `amelie-display` turns
off the screen's power saving.

## Touch

Touch the flag of the other language, in the top right: the text must change
immediately, and Amelie announces the new language aloud. If the touch does
not respond, check the screen's micro-USB cable (it carries both touch and
power) and that the script reports "touch dello schermo" (screen touch); if it
says "nessun touch riconosciuto" (no touch recognised), that cable does not
reach the hub. At the end, touch the flag of the language you started from.

## Audio

Touch the flag that is **already highlighted**, full and with the gold ring:
nothing changes, but Amelie announces the language aloud, "Lingua italiana. Da
adesso racconto i vini in italiano." (Italian language. From now on I will
describe the wines in Italian.), or "English language. From now on I will
describe the wines in English." if the language is English. It is the quickest
audio test.

| Symptom | Cause | Fix |
|---|---|---|
| silence, the script says "nessuna scheda audio" (no sound card) | the sound card did not come up at boot | `sudo systemctl restart amelie-audio-guard`, then `sudo reboot` |
| silence, the script says "strada del suono verso l'HDMI chiusa" (sound path to HDMI closed) | the mixer control was left closed | `sudo systemctl restart amelie-audio-rotta` |
| silence, everything OK in the script | the speakers | check the jack between screen and speakers, the USB cable that powers the speakers and the volume control on their cable, which must be kept at maximum (it can only be reached with the enclosure open) |
| weak sound | the volume | turn it up from the speaker in the top left; if it is already at maximum, check the volume control on the speakers' cable |
| you only hear "From now on I will describe the wines in English.", without "English language."; or a sentence is missing from a story | that sentence is saved empty in the voice cache: it happens when the device is switched off a few seconds after the sentence was heard for the first time | switch off and on, or `sudo systemctl restart amelie`: at every start the service removes the empty sentences and makes them again the first time they are needed. The script checks this in section 7 |

To test the audio without the application there are two scripts, to be run
with the screen on and **with the service stopped**: `scripts/01_audio.sh`
checks the whole chain (kernel, audio profiles, screen connected, sound card,
mixer) and at the end plays a test sound; with `--solo-diagnosi` it only
looks. `scripts/suona.sh` only plays a tone.

```bash
cd ~/amelie
sudo systemctl stop amelie
bash scripts/suona.sh
sudo systemctl start amelie
```

The application keeps the audio output open all the time, on purpose: the
board's audio processor takes about two seconds to start playing, and paying
that on every sentence would make short sentences disappear. A second program
that tries to open the output finds it busy: that is why the scripts are run
with the service stopped.

Every so often, at boot, the sound card does not show up: it is a race between
two system components. The `amelie-audio-guard` guard notices, restarts the
audio processor and, if that is not enough, the board: only once, and only in
the first ten minutes after power-on. It writes what it did to
`/var/lib/amelie/audio-guard.log`; the last lines can be read with
`tail /var/lib/amelie/audio-guard.log`.

## The microcontroller

The light and the distance sensor are driven by the UNO Q's microcontroller,
running Amelie's sketch. If the sketch is not running, the light stays off and
the device sees no bottle at all, even with the Modulino boards connected: the
Modulino Distance LED is on, because the module is powered, but nobody reads
it.

You recognise it like this:

- the script, in section 4, says "il router risponde ma lo sketch di Amelie non
  gira sul microcontrollore" (the router answers but the Amelie sketch is not
  running on the microcontroller);
- in the settings, "Technical state" shows `mcu: false` and `protocollo: null`;
- the application's journal keeps repeating "il router risponde ma lo sketch di
  Amelie non c'e'" (the router answers but the Amelie sketch is not there):
  `journalctl -u amelie -n 20`.

The most common cause is the pairing between the sketch and the loader. The
loader is the program that, when the microcontroller starts, runs the sketch
from a fixed address in memory; the loader and that address change with the
version of Arduino's core. When App Lab updates itself it brings the loader of
its own version to the microcontroller, and a sketch compiled with a different
core no longer starts: the upload succeeds, and the microcontroller stays
silent. The fix is to upload the sketch and the loader together, with the same
core, as the `arduino` user and without a password:

```bash
cd ~/amelie
bash scripts/firmware.sh --sempre
```

The script compiles the sketch if needed, uploads it together with the loader,
waits for the microcontroller to answer and says which Modulino boards it
sees: "firmware caricato, il microcontrollore risponde: Pixels visto, Distance
visto" (firmware uploaded, the microcontroller answers: Pixels seen, Distance
seen). The application notices by itself within twenty seconds, with no
restart. At the moment the microcontroller restarts, the router writes a few
"decoding packet: invalid packet, expected array" lines in its journal: this
is normal.

| `firmware.sh` message | What to do |
|---|---|
| "arduino-router e' fermo: …" (arduino-router is stopped) | `sudo systemctl restart arduino-router`, then run it again |
| "caricamento non riuscito: …" (upload failed) | run it again; if it happens again, switch off and on with the power switch and run it again |
| "firmware caricato, ma il microcontrollore non risponde" (firmware uploaded, but the microcontroller does not answer) | switch off and on with the power switch and run it again; if it persists, look at the router: `journalctl -u arduino-router -n 30` |
| "… Pixels NON visto", "… Distance NON visto" (Pixels / Distance not seen) | see [The Modulino boards](#the-modulino-boards) |

After every App Lab or system update it is worth running
`bash scripts/firmware.sh`, without `--sempre`: if the microcontroller still
answers it touches nothing. `scripts/install.sh` does it too, in step 9.

## The Modulino boards

The microcontroller looks for the Modulino boards only in the first ten
seconds after it starts: a module connected later is reported as missing until
the next power-on. To try again, switch the device off with the power switch
and on again: rebooting Linux (`sudo reboot`) is not enough, because the
microcontroller does not restart.

- **Modulino Pixels**: at rest the light is a soft amber; from power-on to the
  first bottle it pulses slowly, then it stays steady. If it stays off, the
  module is not seen.
- **Modulino Distance**: place a dark glass bottle. Within an instant the light
  turns green and the screen says "Let me have a look…", then "I'm reading the
  label…". If nothing happens, the sensor is not seen. The sensor measures with
  infrared light, which passes through clear glass: a transparent bottle may
  not be seen, which is why the test is done with dark glass.

In both cases check that the Qwiic cables are pushed fully home at both ends
(the order of the modules in the chain does not matter), then switch off and
on with the power switch. Section 4 of the script says which modules the
microcontroller sees: "Modulino Pixels visto" (Modulino Pixels seen),
"Modulino Distance visto" (Modulino Distance seen). The same can be seen on the
screen, without a computer: in the settings, "Technical state" shows `moduli`
(modules), with `anello` (the Pixels) and `distanza` (the Distance) set to
`true` when the module is seen.

For more detail, with the service stopped:

```bash
cd ~/amelie
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/bus.py
sudo systemctl start amelie
```

`bus.py` lists what responds on the I²C bus, the bus of the Qwiic cables, and
at which address: `0x36` is the Modulino Pixels, `0x29` the Modulino Distance.
If one is missing, it says so. With `--guarda` it keeps listening and prints
every change, while you connect one piece at a time (leave with Ctrl+C); with
`--sensore` it shows the distance sensor's readings for ten seconds, while you
move a hand over the disc.

## The camera

Open the settings by holding your finger still on the bottom-right corner of
the screen for three seconds, and turn on **Debug camera**. While it is on, the
device tells no stories: the screen shows what the camera sees, with the box
that goes to the OCR drawn over it, and at the side what it reads.

Place a bottle with the label facing the screen:

- the label must be inside the box, in the centre: the two thin lines mark the
  centre lines;
- the box and the text `nitidezza N (soglia 40)` (sharpness N, threshold 40)
  must be green: green means above the threshold, red below;
- at the side, under "What it reads", the lines of the label must appear, and
  under "What it finds" the level that recognition has reached and its
  confidence. The reading is updated every few seconds: the OCR takes a few
  seconds per round.

If the sharpness stays red, the lens is out of focus. The M12 lens is focused
by turning it in its holder: the right distance is that of the label, about
100 mm. Turn it in small steps until the sharpness is at its maximum, then lock
it (the holder has a locking ring or a set screw; failing that, a drop of
low-strength threadlocker).

You leave with "back to the story", at the bottom: a bottle left on the plate
is read immediately, and that is the proof that the framing works. Debug
camera does not stay on after a reboot.

To see the same view larger, on the computer: `scripts/mirino.py` runs on the
board, with the service stopped, and is viewed in the computer's browser.

```bash
cd ~/amelie
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/mirino.py --ocr
```

Open in the computer's browser the address the script prints,
`http://<indirizzo-della-board>:8090/` (the board's address), or
`http://amelie.local:8090/`. `--ocr` adds the lines read and what it finds in
the database; `--luce` turns the light white, as during the shot. Close it with
Ctrl+C; then `sudo systemctl start amelie`.

## Recognition, without a bottle

Recognition can also be tested on text typed in by hand, as if the OCR had read
it. On the board:

```bash
cd ~/amelie
PYTHONPATH=src ./venv/bin/python - <<'EOF'
from amelie.matcher import Matcher
m = Matcher()
for letto in (["BAROLO", "DENOMINAZIONE DI ORIGINE CONTROLLATA E GARANTITA", "2016"],
              ["AMARONE DELLA VALPOLICELLA", "CLASSICO"],
              ["Nebbiolo"],
              ["CONTIENE SOLFITI", "750 ml"]):
    f = m.cerca(letto)
    print(f"{f.livello.value:14} {f.sicurezza:5.0f}  "
          f"{f.nome or f.tipologia or f.denominazione or (f.vitigni[0] if f.vitigni else '-')}")
EOF
```

Expected:

```
tipologia         70  Barolo
tipologia         87  Amarone della Valpolicella Classico
vitigno           60  Nebbiolo
nulla              0  -
```

Each line gives the level at which recognition stopped (`tipologia`, the wine
type within an appellation; `vitigno`, the grape variety; `nulla`, nothing),
the confidence and what it recognised. The last one is the most important: on
a text that says nothing about the wine, the device must not make anything up.

## The automated tests

The repository has about a thousand tests. On the board:

```bash
cd ~/amelie
./venv/bin/pip install -q -r requirements-dev.txt
./venv/bin/python -m pytest -q -p no:cacheprovider tests/
```

The first command adds pytest, the program that runs the tests, to the board's
Python environment; you only need to do it once. The second runs them without
leaving pytest's cache in the repository, in a couple of minutes. At the end
pytest prints how many tests passed (`passed`) and how many were skipped
(`skipped`): some are skipped on purpose, when something that the board does
not need is missing. There must be no `failed` and no `error`. The tests that
check that the story does not make things up are in `tests/test_narrator.py`.

## The full experience

With the device assembled, switched on, and a real bottle:

1. **At rest**: the wine glass, "Every bottle has a story.", the three steps
   ("**Choose** a bottle", "**Place** the bottle on Amelie", "**Listen** to its
   story"), the soft amber light.
2. **Place the bottle**: the light turns green and the screen says "Let me
   have a look…", then "I'm reading the label…" and "One moment…".
3. **The story**: the title at the top, the text with the sentence the voice is
   speaking highlighted, the voice.
4. **Lift the bottle as if to pour**: the story goes on to the end. Put it
   back: the story does not start over.
5. **Tap the cross at the bottom left**: the voice stops at once and the
   waiting screen comes back. The bottle left on the plate is not read again:
   for a new story, lift it and put it back.

| What to look for | Why |
|---|---|
| lifted to pour, the story goes on | whoever pours has not asked for silence, and a story cut off mid-sentence stands out |
| the cross stops the voice at once | it is the only way to end a story before it finishes, since removing the bottle does not stop it, and it must always work |
| the first sentence says how sure it is | "This is…" and the other sure forms only when it is sure; when in doubt, "I'd say…", "It should be…", "This looks like…" |
| when the same bottle is put back, the story does not start over | whoever has just poured does not want to hear it all again |
| when another bottle is placed, the new story starts | the device reads it while the voice goes on, and changes story only if it really is another wine |

## Trying to break it

To be done before leaving the device in the dining room, where nobody will be
able to step in.

| Test | Expected |
|---|---|
| remove the bottle while the screen says "Let me have a look…" or "I'm reading the label…" | the round stops and the waiting screen comes back |
| place and remove it quickly ten times | no freezes, no double readings |
| a bottle with no label, or turned around | the screen asks "Could you turn the label towards me?", with the light turning red, and tries again; after three attempts it goes back to waiting, and does not read that bottle again until you remove it. With "Add corrections" on, if it has read a few words from the label, it first says "I couldn't recognise this bottle." and offers "Help me recognise it" |
| unplug the camera and place a bottle | "Something went wrong. I'll try again in a moment.", with the light turning red, then the waiting screen. Plug the camera back in and tap "Restore operation" in the settings: the next bottle is read again |
| in "Written on the spot" mode, `sudo systemctl stop amelie-llm`, then a bottle | the screen says "I'm writing the description…" for about 45 seconds, then tells the story anyway, from the archive. At the end switch the model back on with `sudo systemctl start amelie-llm` |
| reboot ten times, with `sudo reboot` or by switching off and on with the power switch | the audio is there every time (look at `/var/lib/amelie/audio-guard.log`) |
| cut the power during the story | at the next power-on it starts again cleanly, up to the waiting screen |
| leave the device on and at rest for an hour | the screen stays on, without turning off and without a screen lock; over SSH, `top` (leave with q) shows no program staying close to 100 % of a core all the time. The exception is `llama-server` in "Written on the spot" mode, which keeps almost a whole core busy even at rest |

## Before leaving it in the dining room

- Follow "Locking it down" in
  [Installing the software](02-install.md#locking-it-down).
- Reset the audio guard's reboot counter, so that after testing it again has
  its single attempt: `sudo rm -f /var/lib/amelie/riavvii-audio`.
- Turn off **Debug camera** if it is on, and **Add corrections** if it is not
  needed.
- If you saved test corrections during testing, delete them (see
  [Using Amelie](05-usage.md)).
- Charge the battery and tap **Battery recharged** in the settings: the power
  bank does not report its charge, and the device estimates it from the time
  and the work done since the recharge.
- Switch off with the power switch, switch on again and check that the device
  reaches the waiting screen on its own, without a keyboard and without a
  network.

## Next step

[Using Amelie](05-usage.md).
