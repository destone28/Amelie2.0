# Testing Amelie

How to check that the assembled device works, from the automatic check to the
full experience with a real bottle. Each test says what to expect and what to
do if the result is not right.

One rule applies throughout: **what the software reports is not what the
hardware does.** The screen is tested by looking at it, the audio by listening
to it. An `xrandr` that reports an active mode and an `aplay` that gives no
errors prove nothing.

## The automatic check

After the installation and a reboot, log in to the board and run:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

The script only reads. It checks the system, the installation (Python
environment, voices and model with their checksums, llama.cpp, database, wine
list, firmware), the services, the application (microcontroller, the two
Modulino boards, camera, voice), the screen, the camera, the audio and the
router to the microcontroller. Each item is **OK**, **ATTENZIONE** (warning) or
**GRAVE** (serious), and each GRAVE item says what to do. The report is kept in
`/tmp/amelie-diagnostica.txt`.

Everything is fine when the summary has no GRAVE items.

## The screen

Look at the panel: it must show Amelie's waiting screen, with the wine glass on
a dark background, full screen and with no pointer.

| Symptom | Cause | Fix |
|---|---|---|
| black, but the script says 1280x720 | HDMI cable or screen power | check the HDMI cable and the screen's micro-USB cable |
| black, with the 800x480 mode | the LAFVIN panel produces no image at its native resolution | `sudo systemctl restart amelie-display` |
| small image in a corner | 1920x1080 mode | `sudo systemctl restart amelie-display` |
| the desktop appears | Amelie's session is not set | run `bash scripts/install.sh` again |
| the page does not change after an update | the kiosk opens the page only once | `sudo systemctl restart amelie-kiosk` |

A screen that turns off takes the audio with it: the board's video bridge sets
up the audio only if it sees the screen on. That is why `amelie-display` turns
off the screen's power saving.

## Touch

Touch the flag of the other language, in the top right: the text must change
immediately. If the touch does not respond, check the screen's micro-USB cable
(it carries both touch and power) and that the script reports "touch dello
schermo" (screen touch).

## Audio

Touch the flag that is **already highlighted**: nothing changes, but Amelie
announces the language aloud. It is the quickest audio test.

| Symptom | Cause | Fix |
|---|---|---|
| silence, the script says "nessuna scheda audio" (no sound card) | the sound card did not come up at boot | `sudo systemctl restart amelie-audio-guard`, then reboot |
| silence, "strada del suono verso l'HDMI chiusa" (sound path to HDMI closed) | the mixer control went back to zero | `sudo systemctl restart amelie-audio-rotta` |
| silence, everything OK in the script | speakers | check the jack between screen and speakers, the speakers' USB power and their volume |
| weak sound | volume | turn it up from the speaker in the top left |

To test the audio without the application there are `scripts/01_audio.sh` (a
full diagnosis, then a tone) and `scripts/suona.sh` (the tone only), but **with
the service stopped**:

```bash
sudo systemctl stop amelie
bash scripts/suona.sh
sudo systemctl start amelie
```

The application keeps the audio output open all the time, on purpose: the
board's audio processor takes two seconds to start, and paying that on every
sentence would make every short sentence silent. A second program that tries to
open the output finds it busy.

Every so often, at boot, the sound card does not show up: it is a race between
two system components at startup. The `amelie-audio-guard` guard notices,
restarts the audio processor and, if that is not enough, the board, only once.
It writes what it did to `/var/lib/amelie/audio-guard.log`.

## The Modulino boards

The microcontroller looks for the Modulino boards **at power-on**: a module
connected later is reported as missing until the next reboot.

- **Modulino Pixels**: at rest the light is a soft amber. If it stays off, the
  module is not seen.
- **Modulino Distance**: place a bottle. Within an instant the screen says
  "Let me have a look…". If nothing happens, the sensor is not seen.

In both cases check the Qwiic cables and their order, then switch off and on
again. The script says which modules the microcontroller sees; for more detail,
with the service stopped:

```bash
sudo systemctl stop amelie
PYTHONPATH=src ./venv/bin/python scripts/bus.py
sudo systemctl start amelie
```

`bus.py` lists what responds on the I²C bus, at which address, and the
readings of the distance sensor.

## The camera

Open the settings by holding your finger on the bottom-right corner of the
screen for three seconds, and turn on **Debug camera**. The screen shows what
the camera sees, the box that goes to the OCR, and what it reads.

Place a bottle with the label facing the screen:

- the label must be inside the box, in the center;
- the text `nitidezza` (sharpness) must be green (above the threshold);
- the lines of the label must appear in the "What it reads" column.

If the sharpness stays red, the lens is out of focus. The M12 lens is focused
by turning it in its holder: the right distance is that of the label, about
100 mm. Turn it in small steps until the sharpness is at its maximum, then lock
it (the holder has a locking ring or a set screw; failing that, a drop of
low-strength threadlocker).

You leave with "back to the story" at the bottom: a bottle left on the plate is
read immediately.

From the PC, with the service stopped, `scripts/mirino.py` shows the same view
in a larger window; the instructions are at the top of the script.

## Recognition, without a bottle

Recognition can also be tested on text typed in by hand, as if the OCR had read
it:

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

The last line is the most important one: on a text that says nothing about the
wine, the device must not make anything up.

## The automated tests

The repository has about a thousand tests. On the board:

```bash
cd ~/amelie
./venv/bin/pip install -q -r requirements-dev.txt
./venv/bin/python -m pytest -q -p no:cacheprovider tests/
```

It takes a couple of minutes. The tests that check that the story does not make
things up are in `tests/test_narrator.py`.

## The full experience

With the device assembled, switched on, and a real bottle:

1. **At rest**: the wine glass, "Every bottle has a story.", the three steps
   (**Choose**, **Place**, **Listen**), the soft amber light.
2. **Place the bottle**: the light changes and the screen says "Let me have a
   look…", then "I'm reading the label…" and "One moment…".
3. **The story**: the title at the top, the text with the sentence the voice is
   speaking highlighted, the voice.
4. **Lift the bottle as if to pour**: the story goes on to the end. Put it
   back: the story does not start over.
5. **Tap the cross at the bottom left**: the voice stops at once. Lift the
   bottle: the waiting screen comes back.

| What to look for | Why |
|---|---|
| lifted to pour, the story goes on | whoever pours has not asked for silence, and a story cut off mid-sentence stands out |
| the cross stops the voice at once | it is the only way to silence the device, and it must always work |
| the first sentence says how sure it is | "This is…" only when it is sure |
| when the same bottle is put back, the story does not start over | whoever has just poured does not want to hear it all again |
| when another bottle is placed, the new story starts | |

## Trying to break it

To be done before leaving the device in the dining room, where nobody will be
able to step in.

| Test | Expected |
|---|---|
| remove the bottle during "Let me have a look…" | the round stops and the waiting screen comes back |
| place and remove it quickly ten times | no freezes, no double readings |
| a bottle with no label, or turned around | it asks you to turn the label towards it and tries again; after three attempts it goes back to waiting (with "Add corrections" on it says "I couldn't recognise this bottle.") |
| unplug the camera and place a bottle | an error message, then back to waiting |
| in "Written on the spot" mode, `sudo systemctl stop amelie-llm`, then a bottle | it tells the story anyway, from the facts |
| reboot ten times | the audio is there every time (look at `/var/lib/amelie/audio-guard.log`) |
| cut the power during the story | it starts again cleanly |
| leave the device on and at rest for an hour | the screen stays on, the battery goes down only a little (the icon on the "Battery recharged" row of the settings) |

## Before leaving it in the dining room

- Follow "Locking it down" in [Installing the software](02-install.md).
- Reset the audio guard's reboot counter, so that after testing it again has
  its single attempt: `sudo rm -f /var/lib/amelie/riavvii-audio`.
- Turn off **Debug camera** and **Add corrections** if they are not needed.
- Reboot and check that the device reaches the waiting screen on its own,
  without a keyboard and without a network.

## Next step

[Using Amelie](05-usage.md).
