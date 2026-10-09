# Installing the software

All of Amelie's software is installed with one script, `scripts/install.sh`,
which runs on the UNO Q. This guide explains how to launch it, what it does
step by step, where it puts things and how to update the device.

You need a board prepared as in
[Preparing the UNO Q](01-prepare-the-uno-q.md): with the name `amelie`, the
`arduino` user's password chosen at the first setup, the Wi-Fi network and
network mode switched on. On a new board network mode is off, and with it SSH
and the name `amelie.local`: that guide explains how to switch it on. If you
gave the board a different name, use it instead of `amelie` in every command.

You work in two places:

- **on the computer**, in a terminal (PowerShell on Windows, the Terminal app
  on macOS and Linux);
- **on the board**, in the terminal you open from the computer with
  `ssh arduino@amelie.local`. SSH is the remote terminal: what you type there
  runs on the board. You leave it with `exit`.

Unless stated otherwise, the commands in this guide are typed on the board.
Those that start with `sudo` act as administrator: `sudo` asks for the
`arduino` user's password (nothing appears while you type it) and remembers it
for a quarter of an hour.

## Where the board sits while you install

The installation only needs the network. The board can be:

- **on the bench, connected to the hub**, with the hub powered by the power
  bank or by a USB-C power supply, even without screen and camera: this is the
  recommended set-up;
- **already mounted** in the device;
- **connected to the computer** with the USB-C cable, as at the end of
  [Preparing the UNO Q](01-prepare-the-uno-q.md). It works, but the board takes
  its power from the computer, and in step 6 compiling llama.cpp keeps all four
  cores at full load for about twenty minutes: use a port that supplies at
  least 1.5 A. If the board restarts on its own during the compilation, the
  power is not enough: put it on the bench with the hub and run the
  installation again.

The Modulino boards are not needed for the installation: the firmware is
uploaded to the microcontroller even without them.

## Running the installation

1. From the computer, log in to the board:

   ```bash
   ssh arduino@amelie.local
   ```

2. Optional, but useful: open a `tmux` session. tmux keeps the terminal on the
   board alive even when the connection with the computer drops, and the
   installation carries on.

   ```bash
   sudo apt update
   sudo apt install tmux
   tmux
   ```

   If the connection drops, log in again with `ssh arduino@amelie.local` and
   get back into the session with `tmux attach`.

3. Download the project **into the `~/amelie` folder**. `~` is the home folder
   of the `arduino` user, that is `/home/arduino`: the system services look for
   the project in `/home/arduino/amelie`, and the script stops if it finds it
   elsewhere.

   ```bash
   git clone https://github.com/destone28/Amelie2.0 ~/amelie
   ```

   If the board answers that the `git` command does not exist, install it with
   `sudo apt install git` and try again.

4. Run the installer:

   ```bash
   cd ~/amelie
   bash scripts/install.sh
   ```

The script prints a heading for each step, with its Italian name, from
`==> [1/12] Controlli` to `==> [12/12] Console silenziosa`, and a few lines
underneath on what it has done. At the end of step 1 it asks for the `arduino`
user's password, only once: it is for `sudo`, and the script keeps it valid
until the end. Then it works on its own.

Compiling llama.cpp, in step 6, takes about twenty minutes on its own. The
rest of the time depends mostly on the network: the system and Python
packages, the two voices and the 380 MB language model are downloaded.

If the connection drops halfway without `tmux`, the installation stops: log in
again and run the same command. Each step skips what is already done.

At the end the script prints "Installazione completata." (installation
complete) and reminds you of three commands: the reboot, the state of the
services and the testing.

### Two optional variables

They go in front of the command, on the same line:

| Variable | What it is for |
|---|---|
| `AMELIE_FUSO=Europe/Rome` | sets the board's time zone, which is UTC from the factory; the times in the scan log follow the time zone. It can also be set later, with `sudo timedatectl set-timezone Europe/Rome` |
| `AMELIE_URL_MODELLO=…` | downloads the language model from a different address, for example from your own copy. The file must be the same: if its SHA-256 sum is not the expected one, the installation stops |

For example: `AMELIE_FUSO=Europe/Rome bash scripts/install.sh`.

### If the installation stops

When a step fails, the script stops and prints `ERRORE:` (error) followed by
the reason, in Italian. Running it again is always safe: it starts again,
skipping what is already done.

| Message | What to do |
|---|---|
| "va eseguito come utente arduino, non come …" (it must be run as the arduino user, not as …) | log in as `arduino` (`ssh arduino@amelie.local`) and run the script without `sudo` in front |
| "il repository deve stare in /home/arduino/amelie (e' in …)" (the repository must be in /home/arduino/amelie; it is in …) | clone the repository into `~/amelie`, as in point 3 |
| "la board non e' in rete" (the board is not on the network) | the board cannot reach the internet: check the Wi-Fi ([Preparing the UNO Q](01-prepare-the-uno-q.md)) |
| "servono almeno 4 GB liberi in /home/arduino (ce ne sono …)" (at least 4 GB free are needed; there are …) | free some space in the home folder; `df -h ~` tells you how much there is |
| "serve la password di arduino per sudo" (the arduino password is needed for sudo) | the password was mistyped three times: run the script again and type it carefully |
| "la voce … non corrisponde alla somma attesa", "modello non scaricato da …", "il modello non corrisponde alla somma attesa" (a voice or the model does not match the expected sum, or the model was not downloaded) | a download was interrupted or a different file arrived: run the script again. With `AMELIE_URL_MODELLO`, check the address |
| "remoteocd non trovato …", "loader o configurazione OpenOCD del core non trovati …", "caricamento non riuscito: …" (upload tool, loader or OpenOCD configuration not found; upload failed) | the firmware was not uploaded to the microcontroller: run the script again; if it happens again, remove and restore power to the board and run it again |
| "arduino-router e' fermo: …" (arduino-router is stopped) | the service that connects Linux to the microcontroller is stopped: `sudo systemctl restart arduino-router`, then run the script again |

If the command that stops is a system one (`apt-get`, `pip`, `cmake`, `git`,
`curl`), the message is its own, and the cause is almost always the network:
run the script again. Step 1 also warns, without stopping, if the system is not
Debian 13 (trixie), the only tested configuration.

### The reboot

```bash
sudo reboot
```

The SSH connection closes. At power-on the board's start-up messages may appear
on the screen for about ten seconds; then the screen takes on the colour of the
brand, Amelie's logo appears (the wine glass and the name) while the device
loads the voices, and in less than a minute the waiting screen. If after a
minute and a half "This is taking longer than usual." appears at the bottom,
the device is not ready: follow [Testing Amelie](04-testing.md).

If the board is on the bench without a screen, log in again after a minute and
check that the application is ready:

```bash
systemctl status amelie        # must say "active (running)"; leave with q
curl -s localhost:8080/pronto  # must answer {"pronta":true}
```

## What it does, step by step

The script prints the steps numbered from 1 to 12, under their Italian names
(shown here in parentheses).

**1. Checks** (*Controlli*). It verifies that it is running as the `arduino`
user, in the `/home/arduino/amelie` folder, with network access and at least
4 GB free in the home folder, and stops if anything is missing. It warns,
without stopping, if the system is not Debian 13 (trixie), the tested
configuration. Then it asks for the password for `sudo`.

**2. System packages** (*Pacchetti di sistema*). Python with `venv`, the tools
to compile and download (`build-essential`, `cmake`, `git`, `curl`), Chromium
for the screen, `unclutter` to hide the pointer, `x11-xserver-utils` for the
video mode, the camera and audio tools (`v4l-utils`, `alsa-utils`) and the
EB Garamond font.

**3. Sound card at boot** (*Scheda audio all'avvio*). On this board the sound
card sometimes fails to come up: the audio processor (ADSP) can start before
`qcom_pd_mapper`, the kernel module it turns to at start-up, is ready. A line
in `/etc/modprobe.d/amelie-audio-race.conf` makes that module load before the
audio processor's driver; the cases that remain are recovered by the
`amelie-audio-guard` service (below).

**4. Python environment** (*Ambiente Python*). A virtual environment, that is a
folder with its own Python and its own packages, separate from the system's,
in `~/amelie/venv`. It holds the exact versions in
[`requirements.txt`](../../requirements.txt), the ones tested on the UNO Q:
OpenCV, ONNX Runtime, RapidOCR, RapidFuzz, FastAPI, Uvicorn, Piper.

**5. OCR engine** (*Motore OCR*). OCR is the recognition of text in images.
RapidOCR downloads its networks the first time it is used, into the virtual
environment; the application's service runs in a sandbox where that folder is
read-only, so the script downloads them here, once.

**6. llama.cpp.** The engine that runs the language model of the "Written on
the spot" mode. It is downloaded at the tested commit, and `llama-server` is
compiled, optimised for this processor. This is the long step, about twenty
minutes; if `llama-server` is already compiled at that commit, it is skipped.

**7. Voices and language model** (*Voci e modello linguistico*). The two voices
of Piper, the speech synthesis engine (`it_IT-serena-medium` and
`en_US-ljspeech-medium`), from Hugging Face at a fixed revision, and the
fine-tuned language model (380 MB) from this repository's release. Each file is
checked against its SHA-256 sum in
[`scripts/modelli.sha256`](../../scripts/modelli.sha256): a missing or
different file is downloaded again, and if a voice or the model still does not
match after the download, the installation stops.

**8. Wine database** (*Database dei vini*). `data/build_db.py` builds
`data/amelie.db` from the open data in `data/sources/`, in a few minutes. It
rebuilds it when it is missing or when the sources in `data/` or the code are
newer, for example after a `git pull` that changes them; otherwise it prints
"gia' aggiornato" (already up to date). The sources and their licences are in
[Attributions and licences](08-attributions.md).

**9. Microcontroller firmware** (*Firmware del microcontrollore*). It runs
`scripts/firmware.sh`. With `arduino-cli` it installs the `arduino:zephyr` core
(Arduino's support for the UNO Q's microcontroller) and the
`Arduino_RouterBridge` library at the tested versions, compiles the
`firmware/amelie_mcu` sketch and uploads it to the STM32U585 from the board
itself, without a password, **together with the core's loader**: the sketch
only starts if the loader on the microcontroller is the same version as the
core it was compiled with. It tells App Lab not to start any app at power-on:
an App Lab app would replace Amelie's firmware. Then it waits for the
microcontroller to answer and prints which Modulino boards it sees, for example
"firmware caricato, il microcontrollore risponde: Pixels visto, Distance visto"
(firmware uploaded, the microcontroller answers: Pixels seen, Distance seen).
If the sketch and the versions have not changed and the microcontroller
already answers, it uploads nothing and says so. If the microcontroller does
not answer after the upload, the installation carries on and reminds you at
the end: see [The microcontroller](04-testing.md#the-microcontroller). The
firmware is described in
[`firmware/amelie_mcu/README.en.md`](../../firmware/amelie_mcu/README.en.md).

**10. Services** (*Servizi*). It copies the service scripts to
`/usr/local/bin/` and the units to `/etc/systemd/system/`, installs the
permission with which the application switches the language model on and off,
and enables the services in the table below. If the application is already
running, as during an update, it restarts it and reloads the page on the
screen, and prints "applicazione riavviata" (application restarted).

**11. Graphical session** (*Sessione grafica*). Automatic login for the
`arduino` user and, instead of the XFCE desktop, Amelie's session: a window
manager and nothing else. Only the device appears on the screen.

**12. Quiet console** (*Console silenziosa*). No system messages on the screen
at boot, no Magic SysRq (the kernel's emergency commands, such as "reboot" or
"remount everything read-only": the kernel console is on a debug serial line
that stays unconnected in the assembled device, and noise on that line can be
read as a command), and no console switching from the keyboard. With
`AMELIE_FUSO`, this is also where it sets the time zone.

## Where things are

| Path | What is there |
|---|---|
| `~/amelie/src/amelie/` | the application |
| `~/amelie/venv/` | the Python environment |
| `~/amelie/models/` | the voices and the language model |
| `~/amelie/llama.cpp/` | llama.cpp, compiled |
| `~/amelie/data/amelie.db` | the wine database |
| `~/amelie/vini.csv` | the wine list |
| `~/amelie/var/` | what the device remembers: volume, mode, corrections, battery estimate, scan log; in `var/firmware/` the compiled firmware |
| `~/.cache/amelie/voce/` | the sentences the voice has already synthesised |
| `/etc/systemd/system/amelie*.service` | the services |
| `/usr/local/bin/amelie-*.sh` | the scripts of the services and of the graphical session |
| `/etc/polkit-1/rules.d/50-amelie-llm.rules` | the permission with which the application switches `amelie-llm` on and off |
| `/etc/lightdm/lightdm.conf.d/50-amelie-autologin.conf`, `/etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf`, `/usr/share/xsessions/amelie.desktop` | automatic login and Amelie's graphical session |
| `/etc/modprobe.d/amelie-audio-race.conf` | the order of the audio modules (step 3) |
| `/etc/systemd/system.conf.d/50-amelie-silenzio.conf`, `/etc/sysctl.d/99-amelie-silenzio.conf`, `/etc/X11/xorg.conf.d/10-amelie-kiosk.conf` | the quiet console (step 12) |
| `/var/lib/amelie/` | the audio guard's log (`audio-guard.log`) and its reboot counter (`riavvii-audio`) |

## The services

A service is a program that systemd, the Linux service manager, starts at
power-on and keeps running. Amelie's are:

| Service | What it does |
|---|---|
| `amelie` | the application: camera, OCR, recognition, storytelling, voice, and the web page on port 8080, which only answers requests from the board itself (`localhost`) |
| `amelie-kiosk` | Chromium full screen: it starts from the screen with the logo and moves to the application's page when the device is ready |
| `amelie-display` | sets the screen to 1280 × 720 (at its native resolution, 800 × 480, the panel stays black) and keeps it from turning off: with the screen off, the audio is lost too |
| `amelie-audio-guard` | at boot, checks that the sound card exists; if it is missing, it restarts the audio processor and, if that is not enough, the board: only once, and only in the first ten minutes after power-on |
| `amelie-audio-rotta` | opens the sound path to HDMI (a mixer control that is closed again at every boot) |
| `amelie-sipario` | tints the console in the brand colour and removes the text, until the graphics start |
| `amelie-scrivania` | turns off what the XFCE desktop starts on its own and does not belong on the device (App Lab, the screen lock, the network and Bluetooth icons), in case the desktop comes back |
| `amelie-llm` | the language model (`llama-server`); it is **not** enabled at boot: the application switches it on and off, only in "Written on the spot" mode |

Useful commands, on the board:

```bash
systemctl status 'amelie*'                 # the state of all of them (leave with q)
journalctl -u amelie -f                    # the application's journal, live (leave with Ctrl+C)
sudo systemctl restart amelie              # restart the application
sudo systemctl restart amelie-kiosk        # reload the page on the screen
curl -s localhost:8080/stato | python3 -m json.tool    # the technical state
```

The system journal is the log in which systemd collects the services'
messages; `journalctl` reads it. The technical state is the same one that opens
on the screen from the settings, "Technical state" (see
[Using Amelie](05-usage.md)).

## The service starts in "From the archive" mode

The application starts with the language model installed and selectable
(`--con-modello --modello-addestrato`) and with the wine list next to the code
(`--carta /home/arduino/amelie/vini.csv`), but a freshly installed device tells
its stories **from the archive**: it composes the story from the facts in the
database, without a model. The mode is changed from the settings on the
screen, under "How it tells", and the device remembers it in `var/modo`. See
[Using Amelie](05-usage.md).

## Updating

On the board:

```bash
cd ~/amelie
git pull
bash scripts/install.sh
```

`git pull` downloads the changes from the repository. The installer redoes
only what has changed: the database if the sources or the code have changed,
the firmware if the sketch or the versions of the core and the library have
changed, or if the microcontroller does not answer. If the application is
running, step 10 restarts it and reloads the page on the screen. Changes to
the other services, to the graphical session and to the console take effect
from the next reboot: when in doubt, `sudo reboot`. The settings and the
corrections in `var/` are kept.

After an App Lab or system update (`arduino-app-cli system update`), run the
firmware script as well:

```bash
cd ~/amelie
bash scripts/firmware.sh
```

When App Lab updates itself it can bring the loader of its own version to the
microcontroller, and Amelie's sketch only starts with a loader of the same
version as the core it was compiled with. If the microcontroller still
answers, the script says so and touches nothing; otherwise it uploads the
sketch and the loader together.

### From a PC, without going through git

If you change the code on a PC, you can try it on the board with
`scripts/rilascio.sh`, which runs **on the PC**, from the repository folder
(`<indirizzo-della-board>` stands for the board's address):

```bash
bash scripts/rilascio.sh                                         # to the board arduino@amelie.local
bash scripts/rilascio.sh --host arduino@<indirizzo-della-board>  # to another board
```

It copies to the board the code, the page, the lexicon, the database and the
tests (the first time, it keeps a copy of the board's database,
`data/amelie.db.prima-del-rilascio`), runs the tests on the board and restarts
the application and the kiosk. It does not touch the voices, the language
model or the firmware. You need:

- a board already installed with `scripts/install.sh`;
- SSH access with a key (`ssh-copy-id`, see
  [Preparing the UNO Q](01-prepare-the-uno-q.md)): the script connects many
  times, and without a key it would ask for the password at every connection;
- the database built on the PC: `PYTHONPATH=src python3 data/build_db.py`;
- for the tests, pytest in the board's Python environment (see
  [The automated tests](04-testing.md#the-automated-tests)).

The final restart uses `sudo` over SSH, without a terminal from which to ask
for the password: if `sudo` on the board asks for the password, that step
fails and the application keeps running the code it had. In that case, on the
board: `sudo systemctl restart amelie` and then
`sudo systemctl restart amelie-kiosk`.

The files copied this way show up in the board's clone as local changes, and
the next `git pull` may refuse to overwrite them: on the board,
`cd ~/amelie && git checkout -- .` brings them back to the repository's
version.

## Back to the desktop

To use the board with a screen, keyboard and mouse like a small computer, with
the XFCE desktop:

```bash
sudo rm /etc/lightdm/lightdm.conf.d/60-amelie-sessione.conf
sudo systemctl disable --now amelie-kiosk
sudo systemctl restart lightdm
```

The first command removes Amelie's session; the second turns off the
full-screen Chromium, which would otherwise cover the desktop, also on later
reboots; the third restarts the graphics. The application keeps running.

To go back to Amelie's session: `cd ~/amelie && bash scripts/install.sh`,
which puts the session back and enables the kiosk again, then `sudo reboot`.

## Locking it down

The device sits on a table, where anyone can get their hands on it. Before
leaving it in the dining room, on the board:

**Passwordless sudo.** A new UNO Q asks for the password for `sudo`. If, while
working on the board, you enabled passwordless `sudo`, remove it: here the file
is called `010_arduino-nopasswd`; use the name of the file you created in
`/etc/sudoers.d/`. Then check:

```bash
sudo rm -f /etc/sudoers.d/010_arduino-nopasswd
sudo -k
sudo -n true 2>/dev/null && echo "sudo senza password ancora attivo" || echo "ok"
```

`sudo -k` makes `sudo` forget the password you have just typed, and
`sudo -n true` tries to use it without asking for one. The last line must print
`ok`; the other message, "sudo senza password ancora attivo", means
"passwordless sudo still active".

**The audio packages.** Hold the packages the audio depends on, so that an
update cannot replace the board's audio profiles:

```bash
sudo apt-mark hold alsa-ucm-conf "linux-image-$(uname -r)"
```

To release them, `sudo apt-mark unhold` with the same names.

**SSH.** Leave it on only with key access. First copy your key from the
computer (`ssh-copy-id arduino@amelie.local`, see
[Preparing the UNO Q](01-prepare-the-uno-q.md)) and check that
`ssh arduino@amelie.local` logs you in without asking for the password: without
a working key, once passwords are off, you can no longer get in over SSH. Then,
on the board:

```bash
echo 'PasswordAuthentication no' | sudo tee /etc/ssh/sshd_config.d/00-amelie.conf
sudo systemctl restart ssh
sudo sshd -T | grep -i '^passwordauthentication'
```

The last command must answer `passwordauthentication no`. Alternatively, you
can turn SSH off altogether with `sudo systemctl disable --now ssh`. After a
reboot, from the computer, `ssh arduino@amelie.local` must fail; if it still
answers, switch network mode off with
`arduino-app-cli system network-mode disable`, which asks for the `arduino`
password. To turn SSH back on you then have to open the device and connect the
board to the computer with the USB-C cable (`adb shell`, see
[Preparing the UNO Q](01-prepare-the-uno-q.md)).

The `amelie` and `amelie-llm` services already run confined by systemd
(`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`): the application
cannot rewrite its own code or the system. The most effective measure is still
a physical one: the hub and the board are inside the closed enclosure, and the
only socket that can be reached from outside is the charging one, which leads
to the power bank and not to the board.

## Next step

[Assembling Amelie](03-assembly.md).
