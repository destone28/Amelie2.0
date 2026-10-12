# Amelie 2.0

Put a bottle of wine down and Amelie tells you its story. A camera reads the label, the Arduino UNO Q recognises the wine and a voice describes it: where it comes from, the grapes, how it looks and tastes, what to pair it with. Everything happens on the device, in Italian or English, without an internet connection.

![Amelie 2.0, showing the waiting screen](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/amelie.jpg)

Amelie is a table-top device for a wine bar, a restaurant or a wine cellar at home. It runs on a battery for a whole evening, has a single power switch and charges through a USB-C socket on the back. This article explains how to build one from scratch: the parts to buy, the 3D-printed enclosure, the wiring, the software setup on a factory-new UNO Q, and how to use it.

[Italiano: README.it.md](https://github.com/destone28/Amelie2.0/blob/main/README.it.md)

## What Amelie does

A guest places a bottle on the round plate behind the screen, with the label turned towards the screen: the camera looks at the label from the back of the tower that holds the screen. A distance sensor under the plate notices the bottle, and the camera takes pictures of the label, lit by the white and yellow light next to it, which is always on. The camera adjusts its exposure by itself while the device waits, so the bottle finds the right light already set. The UNO Q reads the text on the label, looks it up in a database of Italian wines and tells the story out loud, while the text scrolls on the 5" touchscreen with the sentence being spoken highlighted.

![The plate side: the disc, the light window and the camera](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/piatto-camera-luce.jpg)

*The plate side: the disc the bottle stands on and, in the tower, the light window and the camera. Bottom right, the charging socket.*

Amelie always says how sure it is. When it recognises the exact wine, it starts with "This is the…"; when it can only recognise the appellation, the wine type or the grape variety, it says so and describes that. It never names something it has not read on the label. Every sentence of the description comes from facts in the database and from the official production specification of the appellation: nothing is invented.

Guests can pause, rewind or skip the story, stop it with the cross, change language with a flag and adjust the volume. Lifting the bottle to pour does not interrupt the story, and putting it back does not start it over. Putting down a different bottle starts the new story straight away.

The person running the venue has a hidden settings panel. From there they choose where the stories come from:

- **From the archive** (default): composed from the facts in the database. It is instant and never invents.
- **Wine list**: your own descriptions, from a CSV file with one row per wine.
- **Written on the spot** (experimental): a small language model running on the UNO Q writes the text. It is slower, and what it writes is checked against the facts before it is spoken.

When Amelie does not recognise a bottle, the staff can teach it from the touchscreen, by picking the right wine or writing a description. The next time, that bottle is recognised by its picture and its words.

## How it works

The Arduino UNO Q has two processors, and Amelie uses both.

- **The Linux side** (Qualcomm QRB2210, running Debian) runs the application, written in Python: camera capture, OCR (optical character recognition), the search in the database, the composition of the story, speech synthesis, and the web page shown full screen on the display.
- **The microcontroller side** (STM32U585, running Zephyr) runs a small Arduino sketch. It drives the two Modulino boards on the Qwiic connector, the light and the distance sensor, and talks to Linux through the Arduino Router Bridge.

The main pieces of software:

- **OCR**: RapidOCR with the PP-OCRv6 networks on ONNX Runtime. It reads the label from a crop of the camera frame.
- **Recognition**: a cascade that goes from the most specific match to the most general one (wine, wine type, appellation, grape variety). Every match gets a confidence score: above one threshold it is told as certain, above a lower one as a guess, and the score can never be higher than the words read on the label allow. See [docs/en/06-recognition.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/06-recognition.md).
- **The database**: about 19,000 Italian wines and all 532 Italian wine appellations (DOCG, DOC and IGT), with their wine types, grape varieties and the official descriptions of colour, nose and palate. It is built on the board from open data included in this repository.
- **The story**: sentences composed from a bilingual lexicon, filled in only with facts, then checked word by word before being spoken. See [docs/en/07-storytelling.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/07-storytelling.md).
- **The voice**: Piper, with one voice per language, running offline.
- **The screen**: a local web page shown by Chromium in kiosk mode, served by FastAPI.

## What you need

These are the parts used to build Amelie 2.0. The links point to the products used for this build, on the Arduino Store and on Amazon Italy; the same products are sold on the other Amazon stores under the same names.

Electronics:

- 1 × [Arduino UNO Q, 4 GB](https://store.arduino.cc/products/uno-q-4gb)
- 1 × [Arduino Modulino Pixels](https://store.arduino.cc/products/modulino-pixels): the light
- 1 × [Arduino Modulino Distance](https://store.arduino.cc/products/modulino-distance): it senses the bottle
- 2 × Qwiic cables: each Modulino comes with one
- 1 × [UGREEN Revodok 105 USB-C hub](https://www.amazon.it/dp/B0BR3M8XHK): 5-in-1, with HDMI, a USB-C PD 100 W input, three USB-A ports and a built-in USB-C cable
- 1 × [LAFVIN 5" IPS capacitive touchscreen, HDMI, 800 × 480](https://www.amazon.it/dp/B0BWJ8YP7S)
- 1 × [Innomaker 1080P USB 2.0 UVC camera](https://www.amazon.it/dp/B0CNCSFQC1) (U20CAM-1080P): 32 × 32 mm board with four M2 holes and an M12 lens, with its USB cable
- 1 × [GOEDCH mini USB speakers](https://www.amazon.it/dp/B0DKXML9X6): a pair of small stereo speakers, about 46 × 46 × 28 mm each, powered over USB, with a 3.5 mm audio jack and an inline volume control
- 1 × [Charmast 26,800 mAh slim power bank](https://www.amazon.it/dp/B073FJ9X2J): its box includes a USB-A to micro-USB cable, used for the touchscreen
- 1 × [YINGAYOU USB-A to USB-C cable with an on/off switch, 0.3 m](https://www.amazon.it/dp/B0FD9JVC9B): the USB-C plug is at 90°
- 1 × [Thsucords USB-C extension, male to female, 0.1 m, 90°](https://www.amazon.it/dp/B0C8JBSXNJ): sold in pairs, one is enough; its female end becomes the charging socket on the back
- 1 × HDMI cable, male to male, as short as possible: the hub and the display are a few centimetres apart

Printed parts and hardware:

- the 11 printed parts in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl), described in the next section
- PLA filament for nine parts and translucent PETG for the two parts that diffuse the light
- 18 × countersunk wood screws, 4 × 16 mm
- 16 × countersunk M2 screws: 8 × M2 × 5 mm, 6 × M2 × 6 mm, 2 × M2 × 8 mm
- 4 × adhesive rubber feet, 3 mm thick

Tools:

- a 3D printer
- screwdrivers for the screws above
- a computer (Windows, macOS or Linux) with [Arduino App Lab](https://www.arduino.cc/en/software/), for the first setup of the UNO Q
- a USB-C data cable (not a charge-only cable), for the first setup
- a USB-C charger, to charge the power bank through the socket on the back

You don't need to solder anything.

## Print the parts

The enclosure is made of 11 parts. The STL files are in [hardware/stl](https://github.com/destone28/Amelie2.0/tree/main/hardware/stl).

- **Base**: the shell. It holds the tower, the plate the bottle stands on and the charging socket.
- **Piastra**: the removable bottom. It carries the power bank, the hub, the UNO Q, the speakers and the switch.
- **Torre**: the tower, a 30° wedge that holds the display at the front and the optics at the back.
- **Frontale**: the frame around the display.
- **PannelloOttico**: the optical panel inside the tower, with the seats for the camera and the Modulino Pixels.
- **CerchioLuce**: the translucent disc the bottle stands on; the Modulino Distance is screwed underneath it.
- **PlaccaLuce**: the translucent plate that closes the light window at the back of the tower and diffuses the light.
- **VassoioLuce**: the bridge over the power bank, under the disc.
- **FermoHub**, **FermoSwitch**, **FermoUno**: the clamps that hold down the hub, the switch and the UNO Q.

Print CerchioLuce and PlaccaLuce in translucent PETG and everything else in PLA. The Base is printed upside down, with its top on the build plate. The material and the printing notes of every part are in [docs/en/03-assembly.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/03-assembly.md).

![All the printed parts](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/parti.png)

![Two units built from the same files](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/due-esemplari.jpg)

*Two units built from the same printing files, with some parts in different colours.*

## Wiring

Everything plugs in; nothing is soldered.

![Wiring diagram](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/wiring.png)

- **Power**: the power bank feeds the hub through the cable with the switch, and the hub powers the UNO Q through its built-in USB-C cable. The UNO Q works as a USB host and receives power through the same port.
- **Charging**: the USB-C socket on the back is the extension that reaches the power bank's USB-C input. You charge Amelie without opening it.
- **Video and sound**: HDMI from the hub to the display. The sound travels over HDMI and comes out of the display's 3.5 mm jack, into the speakers.
- **USB**: the camera, the touchscreen (micro-USB, for touch and power) and the speakers' power plug go into the three USB-A ports of the hub.
- **Qwiic**: the UNO Q's Qwiic connector goes to one Modulino, and the second Qwiic cable chains the other one; the order doesn't matter. Connect them before switching on: the microcontroller looks for them at start-up.

## Prepare the UNO Q

A factory-new UNO Q needs a name, a password, a Wi-Fi connection, the latest Arduino updates and network mode switched on. The simplest way is Arduino App Lab. The full procedure, including how to do everything from a terminal without App Lab, is in [docs/en/01-prepare-the-uno-q.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/01-prepare-the-uno-q.md).

**Connect the board.** Install [Arduino App Lab](https://www.arduino.cc/en/software/) on your computer and open it. Connect the UNO Q, on its own, to the computer with the USB-C data cable. App Lab finds the board and starts the first setup.

**Name, Wi-Fi and password.** Call the board `amelie`: the rest of this guide reaches it as `amelie.local`. If you build more than one Amelie, give each board its own name (`amelie2`, `amelie3`…). Connect it to your Wi-Fi network. Then choose a password for the `arduino` user: the factory password has to be changed at the first setup. Keep the new one: you need it for SSH and for the installation.

**Update.** Accept the updates App Lab offers and wait until they finish.

**Network mode.** Network mode switches on SSH, the remote terminal used in the next steps, and makes the board answer as `amelie.local`. Check it from the board's terminal, the one you open with `adb shell` (see the full guide), with `arduino-app-cli system network-mode status`. If it says `disabled`, switch it on with `arduino-app-cli system network-mode enable`, which asks for the password you have just chosen.

**Check that you can reach it.** From a terminal on your computer:

```bash
ssh arduino@amelie.local
```

The first time, SSH asks you to confirm the board's fingerprint (type `yes`), then the password of the `arduino` user.

## Install the software

The installation runs on the UNO Q itself. Connected over SSH, clone the repository into the home folder and start the installer:

```bash
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

The installer asks once for the password of the `arduino` user, then works on its own for about an hour, most of which is spent compiling llama.cpp. It prints twelve numbered steps:

- system packages (Chromium, Python, build tools)
- a fix for the audio card at start-up
- the Python environment, with the exact versions listed in `requirements.txt`
- the OCR networks
- llama.cpp, the engine of the experimental language model
- the two voices and the language model, checked against their SHA-256 checksums
- the wine database, built from the open data in `data/sources`
- the microcontroller firmware, compiled and uploaded from the board itself
- the system services, the full-screen session and a quiet start-up screen

When it ends, restart the board:

```bash
sudo reboot
```

You can run the installer again whenever you want: it skips what is already done. To update Amelie later, run `cd ~/amelie && git pull && bash scripts/install.sh` on the board.

Every step is explained in [docs/en/02-install.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/02-install.md).

## Assemble

The enclosure closes in a fixed order, because the screws that hold the tower to the base are driven from inside the base, and can only be reached while the bottom is open. The full guide, with the position of every component and every screw, is in [docs/en/03-assembly.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/03-assembly.md).

**Focus the camera first.** The M12 lens leaves the factory focused far away, and the label is about 100 mm from it. Connect the camera to a computer like a webcam and turn the lens until the small print of a label 10 cm away is sharp.

**Phase A, the bottom (Piastra).** The two speakers go into the front corners, membrane facing down. The power bank goes upside down in the middle, ports towards the back. The hub goes into the cradle on the right, its built-in cable towards the back and its HDMI port towards the front, held by the FermoHub clip. The UNO Q sits on four pins between the speakers, USB-C towards the back, held by the FermoUno bridge. The switch lies in the rear bay with its lever through the bottom, closed by the FermoSwitch cover. Then connect the switch cable (power bank Output 3 to the hub's USB-C PD port), the hub cable to the UNO Q, the speakers' USB plug, the first Qwiic cable and the charging extension, and put the VassoioLuce bridge over the power bank.

**Phase B, the tower (Torre).** The translucent PlaccaLuce closes the light window at the back of the tower. The camera, rotated by 90°, and the Modulino Pixels are screwed to the optical panel, which is then screwed inside the tower. The display goes into the ramp with its HDMI, touch and audio cables connected, and the Frontale frame closes it.

**Phase C, the shell (Base).** The Modulino Distance is screwed under the translucent disc (CerchioLuce), which locks into the Base with a sixth of a turn. The charging socket fits into the back wall. The tower is screwed to the Base from inside.

**Phase D, closing.** Connect HDMI, touch, camera and the Qwiic chain, switch on and check the screen, the voice and the bottle detection, then screw the bottom to the Base and stick on the feet.

![Exploded view of Amelie 2.0](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/esploso.png)

<img src="https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/piastra.jpg" alt="The assembled Piastra" width="480">

*The assembled Piastra, seen from above: the two speakers and the UNO Q towards the front, the power bank in the middle, the hub next to it and the cables.*

## First power-on

![The switch in the window in the bottom](https://raw.githubusercontent.com/destone28/Amelie2.0/main/docs/images/foto/interruttore.jpg)

*The switch is operated from underneath, through the window in the bottom.*

Switch Amelie on. The screen shows the Amelie logo while the voices load, then the home screen: a wine glass, "Every bottle has a story." and three steps, **Choose** a bottle, **Place** the bottle on Amelie, **Listen** to its story.

Check the three things that can go wrong when mounting the hardware:

- **Sound**: tap the flag that is already highlighted, at the top right. Amelie announces the language out loud. If you can't hear it, check the jack between the display and the speakers, the speakers' USB power and their volume control.
- **Modules**: while Amelie waits, the light is on, white and yellow; it turns red only for a fault, or while waiting when the battery is almost flat. Place a bottle: the screen must say "Let me have a look…". If the light stays off, or nothing happens when you place the bottle, a Modulino is not seen: check the Qwiic cables, then switch off and on again.
- **Camera**: hold a finger on the bottom-right corner of the screen for three seconds to open the settings, and switch on **Debug camera**. The screen shows the frame that goes to the OCR, with the label in the middle, and the text that was read.

For a complete check, connected over SSH:

```bash
cd ~/amelie && bash scripts/00_diagnostica.sh
```

Every test, and what to do when one fails, is in [docs/en/04-testing.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/04-testing.md).

## Using Amelie

For guests there is nothing to learn. Place the bottle on the plate with the label turned towards the screen, and listen. The controls under the text start over, go back, pause or skip ahead. The cross at the bottom left stops the story. The flags at the top right change the language, and the speaker at the top left changes the volume. When the story is over and the bottle is taken away, Amelie goes back to its home language, ready for the next table.

For the staff, the settings open by holding a finger on the bottom-right corner of the screen for three seconds. They contain:

- **How it tells**: the source of the stories (From the archive, Wine list, Written on the spot).
- **Add corrections**: shows "Correct this bottle" on every story, and "Help me recognise it" on the bottles Amelie does not know. A correction can point to the right wine in the archive, or carry a description written by you, in one language or both.
- **Debug camera**: what the camera sees and reads, to adjust the framing.
- **Battery recharged**: shows the battery estimate; tap it after recharging, so that the estimate starts from full again.
- **Restore operation**: restarts the camera, the reading and the voice without switching off, when "Something went wrong" keeps coming back.
- **Technical state**: microcontroller, modules, camera, voice and mode at a glance.

Everything is described in [docs/en/05-usage.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/05-usage.md).

## Your own wine list

The wine list is a CSV file, `vini.csv`, in the project folder on the board. It has a header row and one row per wine:

```csv
titolo,descrizione,titolo_en,descrizione_en
"Barolo DOCG","The Italian description, read as it is.","Barolo DOCG","The English description."
```

`titolo` (title) and `descrizione` (description) are required; the two English columns are optional. The repository includes an example list of Italian appellations and wine types, in Italian only. After editing the file, restart the application with `sudo systemctl restart amelie`, then choose **Wine list** in the settings. When a wine is not in the list, Amelie tells its story from the archive.

## When something goes wrong

- **The screen stays black**: check the HDMI cable and the display's micro-USB cable. The display is driven at 1280 × 720, a mode it scales down to its 800 × 480 panel; `systemctl status amelie-display` says which mode was set.
- **No sound**: see the checks in "First power-on". The sound needs the display to be awake, and Amelie keeps it on at all times.
- **Bottles are never noticed and the light stays off**: Amelie's sketch is not running on the microcontroller, usually after an App Lab update. On the board run `bash ~/amelie/scripts/firmware.sh --sempre`, which uploads the sketch and the loader together.
- **The light is on, but bottles are not noticed**: the distance sensor is not seen. Check the Qwiic chain and switch the device off and on.
- **The language announcement lacks "English language", or a sentence is missing from a story**: switching off right after a new sentence left it empty in the voice cache. Switch off and on: at start-up the service removes the empty sentences and makes them again.
- **Labels are read badly**: switch on Debug camera and check that the label is in the middle of the frame and sharp.
- **Anything else**: try "Restore operation" in the settings. The application log is shown by `journalctl -u amelie`.

## Documentation

The complete documentation is in English in [docs/en](https://github.com/destone28/Amelie2.0/tree/main/docs/en) and in Italian in [docs/it](https://github.com/destone28/Amelie2.0/tree/main/docs/it):

- [01 Prepare the UNO Q](https://github.com/destone28/Amelie2.0/blob/main/docs/en/01-prepare-the-uno-q.md)
- [02 Install the software](https://github.com/destone28/Amelie2.0/blob/main/docs/en/02-install.md)
- [03 Assemble](https://github.com/destone28/Amelie2.0/blob/main/docs/en/03-assembly.md)
- [04 Test](https://github.com/destone28/Amelie2.0/blob/main/docs/en/04-testing.md)
- [05 Use](https://github.com/destone28/Amelie2.0/blob/main/docs/en/05-usage.md)
- [06 How a label is recognised](https://github.com/destone28/Amelie2.0/blob/main/docs/en/06-recognition.md)
- [07 How the story is told](https://github.com/destone28/Amelie2.0/blob/main/docs/en/07-storytelling.md)
- [08 Attributions and licences](https://github.com/destone28/Amelie2.0/blob/main/docs/en/08-attributions.md)

The microcontroller sketch is documented in [firmware/amelie_mcu/README.en.md](https://github.com/destone28/Amelie2.0/blob/main/firmware/amelie_mcu/README.en.md).

## Credits and licences

Created by Emilio Destratis ([destratis.it](https://destratis.it)) in collaboration with Arduino.

- The code is released under the MIT License ([LICENSE](https://github.com/destone28/Amelie2.0/blob/main/LICENSE)).
- Documentation, images, diagrams and 3D files are released under the Creative Commons Attribution 4.0 International licence ([LICENSE-DOCS.md](https://github.com/destone28/Amelie2.0/blob/main/LICENSE-DOCS.md)).

The wine database is built from open data and is distributed under the Open Database License 1.0. The sources are:

- Candiago et al., "Quality wines in Italy and France: PDO specifications" (figshare, CC BY 4.0);
- de Azambuja, Morais and Filipe, "X-Wines: A Wine Dataset for Recommender Systems and Machine Learning", Big Data and Cognitive Computing 2023;
- the EU register of geographical indications and the single documents, © European Union (CC BY 4.0).

The voices, the OCR networks, the language model and the font have their own licences. All of them are listed in [docs/en/08-attributions.md](https://github.com/destone28/Amelie2.0/blob/main/docs/en/08-attributions.md).
