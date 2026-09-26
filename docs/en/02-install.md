# Installing the software

All of Amelie's software is installed with one script, `scripts/install.sh`,
which runs on the UNO Q. This guide explains how to launch it, what it does
step by step, where it puts things and how to update the device.

First you need a board prepared as in
[Preparing the UNO Q](01-prepare-the-uno-q.md): with a name, a password, the
network, and reachable over SSH.

## Where the board sits while you install

The installation only needs the network. The board can be:

- **on the bench, connected to the hub** with its power supply or the power
  bank, even without screen and camera: this is the recommended way;
- **already mounted** in the device;
- **connected to the computer** with the USB-C cable. It works, but compiling
  llama.cpp keeps all four cores at full load for about twenty minutes: use a
  computer port that supplies at least 1.5 A, or a powered hub.

The Modulino boards are not needed for the installation: the firmware is
uploaded to the microcontroller even without them.

## Running the installation

Log in to the board and clone the repository **into `/home/arduino/amelie`**:
the system services look for the project there.

```bash
ssh arduino@amelie.local
git clone https://github.com/destone28/Amelie2.0 ~/amelie
cd ~/amelie
bash scripts/install.sh
```

The script asks once for the `arduino` user's password (for `sudo`) and then
works on its own. It takes about an hour, almost all of it spent compiling
llama.cpp and downloading the Python packages. If the SSH connection drops
halfway, run the same command again: each step skips what is already done. To
avoid depending on the connection, run it inside `tmux` (`sudo apt install
tmux`, then `tmux`; if the connection drops, get back in with `tmux attach`).

Two optional variables:

| Variable | What it is for |
|---|---|
| `AMELIE_FUSO=Europe/Rome` | sets the time zone; the board starts out in UTC, and the times in the scan log follow the time zone |
| `AMELIE_URL_MODELLO=…` | downloads the language model from a different address |

For example: `AMELIE_FUSO=Europe/Rome bash scripts/install.sh`.

At the end:

```bash
sudo reboot
```

After the reboot the screen shows the logo, then the waiting screen. If the
board is still on the bench without a screen, the service starts anyway: you
can see it with `systemctl status amelie`.

## What it does, step by step

The script prints the steps numbered from 1 to 12, under their Italian names
(shown here in parentheses).

**1. Checks** (*Controlli*). It verifies that it is running as the `arduino`
user, in the right folder, with network access and at least 4 GB free. It
warns if the system is not Debian 13, the tested configuration.

**2. System packages** (*Pacchetti di sistema*). Python with `venv`, the
build tools (`build-essential`, `cmake`), Chromium for the screen, `unclutter`
to hide the pointer, the camera and audio tools (`v4l-utils`, `alsa-utils`) and
the EB Garamond font.

**3. Sound card at boot** (*Scheda audio all'avvio*). On this board the sound
card sometimes fails to come up: the audio processor (ADSP) starts before the
service that waits for it is ready. A line in
`/etc/modprobe.d/amelie-audio-race.conf` makes the right module load first; the
rest is done by the `amelie-audio-guard` service (below).

**4. Python environment** (*Ambiente Python*). A virtual environment in
`~/amelie/venv` with the exact versions in
[`requirements.txt`](../../requirements.txt), the ones tested on the UNO Q:
OpenCV, ONNX Runtime, RapidOCR, RapidFuzz, FastAPI, Uvicorn, Piper.

**5. OCR engine** (*Motore OCR*). RapidOCR downloads its networks the first
time it is used. The service runs in a sandbox that cannot write to the virtual
environment, so the script loads them here, once.

**6. llama.cpp.** The engine that runs the language model of the "Written on
the spot" mode. It is downloaded at the tested commit, and `llama-server` is
compiled, optimized for this processor. This is the long step, and on the
second run it is skipped.

**7. Voices and language model** (*Voci e modello linguistico*). The two
Piper voices (`it_IT-serena-medium` and `en_US-ljspeech-medium`) from Hugging
Face, at a fixed revision, and the fine-tuned language model (380 MB) from this
repository's release. Each file is checked against its SHA-256 sum in
[`scripts/modelli.sha256`](../../scripts/modelli.sha256): a file that differs
stops the installation.

**8. Wine database** (*Database dei vini*). `data/build_db.py` builds
`data/amelie.db` from the open data in `data/sources/`, in a few minutes. It is
rebuilt automatically when the sources or the code change (after a `git pull`).
The sources and their licenses are in
[Attributions and licenses](08-attributions.md).

**9. Microcontroller firmware** (*Firmware del microcontrollore*). It
installs the `arduino:zephyr` core and the `Arduino_RouterBridge` library at
the tested versions, compiles the `firmware/amelie_mcu` sketch and uploads it
to the STM32U585 from the board itself, without a password. Then it tells App
Lab not to start any app at power-on: an App Lab app would replace Amelie's
firmware. The firmware is described in
[`firmware/amelie_mcu/README.en.md`](../../firmware/amelie_mcu/README.en.md).

**10. Services** (*Servizi*). It installs and enables the system services
(table below).

**11. Graphical session** (*Sessione grafica*). Automatic login for the
`arduino` user and, instead of the XFCE desktop, Amelie's session: a window
manager and nothing else. Only the device appears on the screen.

**12. Quiet console** (*Console silenziosa*). No system messages on the
screen at boot, no Magic SysRq (the kernel console is on a debug serial line
that stays unconnected in the assembled device, and noise on that line can be
read as a command), and no console switching from the keyboard.

## Where things are

| Path | What is there |
|---|---|
| `~/amelie/src/amelie/` | the application |
| `~/amelie/venv/` | the Python environment |
| `~/amelie/models/` | the voices and the language model |
| `~/amelie/llama.cpp/` | llama.cpp, compiled |
| `~/amelie/data/amelie.db` | the wine database |
| `~/amelie/vini.csv` | the wine list |
| `~/amelie/var/` | what the device remembers: volume, mode, corrections, scan log |
| `/etc/systemd/system/amelie*.service` | the services |
| `/usr/local/bin/amelie-*.sh` | the service scripts |
| `/var/lib/amelie/` | the audio guard's log |

## The services

| Service | What it does |
|---|---|
| `amelie` | the application: camera, OCR, recognition, storytelling, voice, the web page on port 8080 |
| `amelie-kiosk` | Chromium full screen on the application's page |
| `amelie-display` | sets the screen to 1280 × 720 and keeps it from turning off: with the screen off, the audio is lost too |
| `amelie-audio-guard` | at boot, checks that the sound card exists; if it is missing, restarts the audio processor and, at most once, the board |
| `amelie-audio-rotta` | opens the sound path to HDMI (a mixer control that is closed again at every boot) |
| `amelie-sipario` | tints the console in the brand color and removes the text, until the graphics start |
| `amelie-scrivania` | turns off what the desktop would start on its own, if you put the desktop back |
| `amelie-llm` | the language model; it is **not** enabled: the application turns it on only in "Written on the spot" mode |

Useful commands:

```bash
systemctl status 'amelie*'                 # the state of all of them
journalctl -u amelie -f                    # the application's log, live
sudo systemctl restart amelie              # restart the application
sudo systemctl restart amelie-kiosk        # reload the page on the screen
curl -s localhost:8080/stato | python3 -m json.tool
```

## The service starts in "archive" mode

The application starts with the language model installed and selectable
(`--con-modello --modello-addestrato`) and with the wine list next to the code
(`--carta /home/arduino/amelie/vini.csv`), but a freshly installed device tells
its stories **from the archive**. The mode is changed from the settings on the
screen, and it is remembered in `var/modo`. See [Using Amelie](05-usage.md).

## Updating

On the board:

```bash
cd ~/amelie
git pull
bash scripts/install.sh
```

The installer redoes only what has changed: the database if the sources or the
code changed, the firmware if the sketch changed. At the end it restarts the
application and reloads the page on the screen. The settings and the
corrections in `var/` are kept.

If you change the code on a PC, you can bring it to the board without going
through git, with `scripts/rilascio.sh`; the script explains how at the top.

## Back to the desktop

To work on the board with a screen, keyboard and mouse, like a small computer:

```bash
sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
sudo systemctl restart lightdm
```

To put Amelie's session back, just run `bash scripts/install.sh` again.

## Locking it down

The device sits on a table, where anyone can get their hands on it. Before
leaving it in the dining room:

```bash
# If it exists, remove passwordless sudo: 'sudo -n true' must then fail.
# ("sudo senza password ancora attivo" = passwordless sudo still active)
sudo rm -f /etc/sudoers.d/010_arduino-nopasswd
sudo -n true && echo "sudo senza password ancora attivo" || echo "ok"

# Hold the packages the audio depends on: an automatic update
# could replace the board's audio profiles.
sudo apt-mark hold alsa-ucm-conf "linux-image-$(uname -r)"

# SSH with a key only (after copying yours with ssh-copy-id), or turned off.
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
# or: sudo systemctl disable --now ssh
```

The `amelie` and `amelie-llm` services already run confined
(`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`): the application
cannot rewrite its own code or the system. The most effective measure is still
a physical one: the hub's free USB ports are inside the enclosure.

## Next step

[Assembling the device](03-assembly.md).
