# Amelie 2.0

Put a bottle of wine down and Amelie tells you its story. A camera reads the label, the Arduino UNO Q recognizes the wine and a voice describes it: where it comes from, the grapes, how it looks and tastes, what to pair it with. Everything happens on the device, in Italian or English, without an internet connection.

![Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/insieme.png)

Amelie is a table-top device for a wine bar, a restaurant or a wine cellar at home. It runs on a battery for a whole evening, has a single power switch and charges through a USB-C socket on the back. This article explains how to build one from scratch: the parts to buy, the 3D-printed enclosure, the wiring, the software setup on a factory-new UNO Q and how to use it.

[Italiano: README.it.md](https://github.com/destone28/Amelie2.0/blob/main/README.it.md)

## What Amelie does

A guest places a bottle on the round plate behind the screen, with the label turned towards the screen: the camera looks at it from the back of the screen's tower. A distance sensor under the plate notices the bottle, the light next to the camera changes color and the camera takes pictures of the label. The UNO Q reads the text on the label, looks it up in a database of Italian wines and tells the story out loud while the text scrolls on the 5" touchscreen, with the sentence being spoken highlighted.

Amelie always says how sure it is. When it recognizes the exact wine, it starts with "This is the…"; when it can only recognize the appellation, the wine type or the grape, it says so and describes that. It never names something it has not read on the label. Every sentence of the description comes from facts in the database and from the official production specification of the appellation. Nothing is invented.

Guests can pause, rewind or skip the story, stop it with the cross, change language with a flag, and adjust the volume. Lifting the bottle to pour does not interrupt the story, and putting it back does not start it over. Putting down a different bottle starts the new story straight away.

The person running the venue has a hidden settings panel. From there they can choose where the stories come from:

- **From the archive** (default): composed from the database facts. It is instant and never invents.
- **Wine list**: your own descriptions, from a CSV file with one row per wine.
- **Written on the spot** (experimental): a small language model running on the UNO Q writes the text. It is slower and checked against the facts before it is spoken.

When Amelie does not recognize a bottle, staff can teach it from the touchscreen by picking the right wine or writing a description. The next time, that bottle is recognized by its picture and its words.

## How it works

The Arduino UNO Q has two brains, and Amelie uses both.

- **The Linux side** (Qualcomm QRB2210, Debian) runs the application in Python: camera capture, OCR, the search in the database, the composition of the story, speech synthesis, and the web page shown full screen on the display.
- **The microcontroller side** (STM32U585, Zephyr) runs a small Arduino sketch. It drives the two Modulino boards on the Qwiic connector, the light and the distance sensor. It talks to Linux through the Arduino Router Bridge.

The main pieces of software:

- **OCR**: RapidOCR with PP-OCRv6 networks on ONNX Runtime. It reads the label from a crop of the camera frame.
- **Recognition**: a cascade that goes from the most specific match to the most general (wine, wine type, appellation, grape variety). Each step has its own confidence threshold, and a guess is only told as certain when the words on the label support it. See [docs/en/06-recognition.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/06-recognition.md).
- **The database**: about 19,000 Italian wines and all 532 Italian wine appellations (DOCG, DOC, IGT), with their wine types, grapes and the official color, nose and palate descriptions. It is built on the board from open data included in this repository.
- **The story**: sentences composed from a bilingual lexicon, filled only with facts, then checked word by word before being spoken. See [docs/en/07-storytelling.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/07-storytelling.md).
- **The voice**: Piper, with one voice per language, running offline.
- **The screen**: a local web page in Chromium kiosk mode, served by FastAPI.

## What you need

Electronics:

- 1 × Arduino UNO Q, 4 GB
- 1 × Arduino Modulino Pixels
- 1 × Arduino Modulino Distance
- 2 × Qwiic cables
- 1 × UGREEN Revodok 105 USB-C hub (5-in-1: HDMI, USB-C PD 100 W input, three USB-A ports, built-in USB-C cable)
- 1 × LAFVIN 5" HDMI IPS capacitive touchscreen, 800 × 480
- 1 × InnoMaker U20CAM-1080P USB camera with M12 lens
- 1 × pair of small USB-powered stereo speakers (46 × 46 × 28 mm each), with a 3.5 mm audio jack
- 1 × Charmast 26,800 mAh slim power bank
- 1 × USB-A to USB-C cable with an inline on/off switch, about 32 cm, with 90° plugs at both ends
- 1 × USB-C panel-mount extension, female to male, for the charging socket
- 1 × short HDMI cable, from the hub to the display
- 1 × USB-A to micro-USB cable, for the touchscreen

Printed parts and hardware:

- the 11 printed parts in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl), described in the next section
- 18 × countersunk wood screws, 4 × 16 mm
- 16 × countersunk M2 screws: 8 × M2 × 5, 6 × M2 × 6, 2 × M2 × 8
- 4 adhesive rubber feet

Tools:

- a 3D printer; a translucent filament is needed for the light parts
- screwdrivers for the screws above
- a computer with Arduino App Lab, for the first setup of the UNO Q
- a USB-C data cable, for the first setup

You don't need to solder anything.

## Print the parts

The enclosure is made of 11 parts. The STL files are in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl).

- **Base**: the shell. It holds the tower, the plate the bottle stands on and the charging socket.
- **Piastra**: the removable bottom. It carries the power bank, the hub, the UNO Q, the speakers and the switch.
- **Torre**: the tower, a 30° wedge that holds the display at the front and the optics at the back.
- **Frontale**: the frame around the display.
- **PannelloOttico**: the optical panel inside the tower, with the seats for the camera and the Modulino.
- **VassoioLuce**, **CerchioLuce**, **PlaccaLuce**: the parts that carry and diffuse the light. CerchioLuce is the translucent disc the bottle stands on.
- **FermoHub**, **FermoSwitch**, **FermoUno**: the clamps that hold down the hub, the switch and the UNO Q.

![All the printed parts](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/parti.png)

## Wiring

Everything plugs in; nothing is soldered.

![Wiring diagram](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/wiring.png)

- **Power**: the power bank feeds the hub through the switch cable, and the hub powers the UNO Q through its built-in USB-C cable. The UNO Q works as a USB host with power pass-through.
- **Charging**: the USB-C socket on the back is an extension that reaches the power bank's USB-C input. You charge Amelie without opening it.
- **Video and sound**: HDMI from the hub to the display. The sound travels over HDMI and comes out of the display's 3.5 mm jack, into the speakers.
- **USB**: the camera, the touchscreen (micro-USB, for touch and power) and the speakers' power go to the three USB-A ports of the hub.
- **Qwiic**: the UNO Q's Qwiic connector goes to one Modulino, and a second Qwiic cable chains the other one. The order doesn't matter. Connect them before switching on: the microcontroller looks for them at power-up.

## Prepare the UNO Q

A new UNO Q needs a name, a password, a Wi-Fi connection and the latest system updates. The simplest way is Arduino App Lab. The full procedure, including how to do it from a terminal without App Lab, is in [docs/en/01-prepare-the-uno-q.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/01-prepare-the-uno-q.md).

**Connect the board.** Install Arduino App Lab on your computer from the Arduino website and open it. Connect the UNO Q to the computer with a USB-C data cable. App Lab finds the board and starts the first setup.

**Name, password and Wi-Fi.** Call the board `amelie`: the rest of this guide reaches it as `amelie.local`. Choose a password for the `arduino` user and connect the board to your Wi-Fi network.

**Update.** Accept the updates App Lab offers and wait for the board to restart.

**Check that you can reach it.** From a terminal on your computer:

```bash
ssh arduino@amelie.local
```

## Install the software

The installation runs on the UNO Q itself. Connected over SSH, clone the repository into the home folder and start the installer:

```bash
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

It asks for the password of the `arduino` user once, then works on its own for about an hour, most of which is spent compiling llama.cpp. It shows twelve numbered steps:

- system packages (Chromium, Python, build tools)
- a fix for the audio card at boot
- the Python environment, with the exact versions in `requirements.txt`
- the OCR networks
- llama.cpp, the engine of the experimental language model
- the two voices and the language model, checked against their SHA-256 checksums
- the wine database, built from the open data in `data/sources`
- the microcontroller firmware, compiled and uploaded from the board itself
- the system services, the kiosk session and a quiet boot screen

When it ends, restart the board:

```bash
sudo reboot
```

You can run the installer again whenever you want. It skips what is already done. To update Amelie later, run `cd ~/amelie && git pull && bash scripts/install.sh`.

Every step is explained in [docs/en/02-install.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/02-install.md).

## Assemble

The enclosure closes in a fixed order, because the screws that hold the tower to the base are driven from inside the base, and can only be reached while the bottom is open. The full guide, with the position of every component and every screw, is in [docs/en/03-assembly.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/03-assembly.md).

**Focus the camera first.** The M12 lens leaves the factory focused far away, and the label is about 100 mm from it. Connect the camera to a computer like a webcam and turn the lens until the small print of a label 10 cm away is sharp.

**Phase A, the bottom plate (Piastra).** The two speakers go into the front corners, membrane down. The power bank goes upside down in the middle, ports towards the back. The hub goes in the cradle on the right, its built-in cable towards the back and the HDMI port towards the front, held by the FermoHub clip. The UNO Q sits on four pins between the speakers, USB-C towards the back, held by the FermoUno bridge. The switch lies in the rear bay, lever through the bottom, closed by the FermoSwitch. Then connect the switch cable (power bank Output 3 to the hub's USB-C PD port), the hub cable to the UNO Q, the speakers' USB, the first Qwiic cable and the charging extension, and put the VassoioLuce bridge over the power bank.

**Phase B, the tower (Torre).** The translucent PlaccaLuce closes the light window at the back of the tower. The camera, rotated 90°, and the Modulino Pixels are screwed to the optical panel, which is then screwed inside the tower. The screen goes into the ramp with its HDMI, touch and audio cables connected, and the Frontale frame closes it.

**Phase C, the shell (Base).** The Modulino Distance is screwed under the translucent disc (CerchioLuce), which locks into the Base with a sixth of a turn. The charging socket clips into the back wall. The tower is screwed to the Base from inside.

**Phase D, closing.** Connect HDMI, touch, camera and the Qwiic chain, switch on and check screen, voice and bottle detection, then screw the bottom plate to the Base and stick on the feet.

![Exploded view of Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/esploso.png)

## First power-on

Switch Amelie on. The screen shows the Amelie logo while the voices load, then the home screen: a wine glass, "Every bottle has a story." and three steps, **Choose** a bottle, **Place** the bottle on Amelie, **Listen** to its story.

Check the three things that can go wrong when mounting the hardware:

- **Sound**: tap the flag that is already highlighted, top right. Amelie announces the language out loud. If you can't hear it, check the jack between the display and the speakers, and the speakers' USB power.
- **Modules**: the light is amber while Amelie waits. Place a bottle: the screen must say "Let me have a look…" and the light must change color. If the light stays off, or nothing happens when you place the bottle, a Modulino isn't seen: check the Qwiic cables, then switch off and on again.
- **Camera**: hold your finger on the bottom-right corner of the screen for three seconds to open the settings, and turn on **Debug camera**. The video shows the frame that goes to the OCR, with the label centered in it and the text that was read.

For a complete check from SSH:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Every test and what to do when it fails are in [docs/en/04-testing.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/04-testing.md).

## Using Amelie

For guests there is nothing to learn. Place the bottle on the plate with the label turned towards the screen, and listen. The controls under the text start over, go back, pause or skip ahead. The cross at the bottom left stops the story. The flags at the top right change language, and the speaker at the top left changes the volume. When the bottle is lifted, Amelie goes back to its home language, ready for the next table.

For staff, the settings open by holding a finger on the bottom-right corner of the screen for three seconds. They contain:

- **How it tells**: the source of the stories (From the archive, Wine list, Written on the spot).
- **Add corrections**: shows "Correct this bottle" on every story, and "Help me recognise it" on the bottles Amelie doesn't know. A correction can point to the right wine in the archive, or carry a description written by you, in one or both languages.
- **Debug camera**: what the camera sees and reads, to adjust the framing.
- **Battery recharged**: shows the battery estimate; tap it after recharging, so the estimate starts from full again.
- **Restore operation**: restarts the camera, the reading and the voice without switching off, if "Something went wrong" keeps coming back.
- **Technical state**: microcontroller, modules, camera, voice and mode at a glance.

Everything is described in [docs/en/05-usage.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/05-usage.md).

## Your own wine list

The wine list is a CSV file, `vini.csv`, in the project folder on the board. It has a header row and one row per wine:

```csv
titolo,descrizione,titolo_en,descrizione_en
"Barolo DOCG","The Italian description, read as it is.","Barolo DOCG","The English description."
```

`titolo` and `descrizione` are required; the two English columns are optional. The repository includes an example list of Italian appellations and wine types, in Italian only. After editing the file, restart the application with `sudo systemctl restart amelie`, then choose **Wine list** in the settings. When a wine is not in the list, Amelie tells its story from the archive.

## When something goes wrong

- **The screen stays black**: check the HDMI cable and the display's micro-USB cable. The display is driven at 1280 × 720, a mode it scales to its 800 × 480 panel; `systemctl status amelie-display` says which mode was set.
- **No sound**: see the checks in "First power-on". Sound needs the display to be awake: Amelie keeps it on at all times.
- **Bottles are never noticed**: the distance sensor isn't seen. Check the Qwiic chain and switch the device off and on.
- **Labels are read badly**: turn on Debug camera and check that the label is centered and sharp.
- **Anything else**: try "Restore operation" in the settings. The application log is at `journalctl -u amelie`.

## Documentation

The complete documentation is in English in [docs/en](https://github.com/destone28/Amelie2.0/tree/main/docs/en) and in Italian in [docs/it](https://github.com/destone28/Amelie2.0/tree/main/docs/it):

- [01 Prepare the UNO Q](https://github.com/destone28/Amelie2.0/blob/main/docs/en/01-prepare-the-uno-q.md)
- [02 Install the software](https://github.com/destone28/Amelie2.0/blob/main/docs/en/02-install.md)
- [03 Assemble](https://github.com/destone28/Amelie2.0/blob/main/docs/en/03-assembly.md)
- [04 Test](https://github.com/destone28/Amelie2.0/blob/main/docs/en/04-testing.md)
- [05 Use](https://github.com/destone28/Amelie2.0/blob/main/docs/en/05-usage.md)
- [06 How a label is recognized](https://github.com/destone28/Amelie2.0/blob/main/docs/en/06-recognition.md)
- [07 How the story is told](https://github.com/destone28/Amelie2.0/blob/main/docs/en/07-storytelling.md)
- [08 Credits and licenses](https://github.com/destone28/Amelie2.0/blob/main/docs/en/08-attributions.md)

The microcontroller sketch is documented in [firmware/amelie_mcu/README.en.md](https://github.com/destone28/Amelie2.0/blob/main/firmware/amelie_mcu/README.en.md).

## Credits and licenses

Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

- The code is released under the GNU General Public License v3.0 or later ([LICENSE](https://github.com/destone28/Amelie2.0/blob/main/LICENSE)).
- Documentation, images, diagrams and 3D files are released under Creative Commons Attribution 4.0 ([LICENSE-DOCS.md](https://github.com/destone28/Amelie2.0/blob/main/LICENSE-DOCS.md)).

The wine database is built from open data and is distributed under the Open Database License 1.0. The sources are:

- Candiago et al., "Quality wines in Italy and France: PDO specifications" (figshare, CC BY 4.0);
- de Azambuja, Morais and Filipe, "X-Wines: A Wine Dataset for Recommender Systems and Machine Learning", Big Data and Cognitive Computing 2023;
- the EU register of geographical indications and the single documents, © European Union (CC BY 4.0).

The voices, the OCR networks, the language model and the font have their own licenses. All of them are listed in [docs/en/08-attributions.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/08-attributions.md).
