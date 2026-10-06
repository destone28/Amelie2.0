# Microcontroller firmware

*[Versione italiana](README.md)*

The Arduino UNO Q has two processors: a Qualcomm QRB2210 running Debian Linux,
which runs the Amelie application, and an **STM32U585** microcontroller, which
runs an Arduino sketch (a program for a microcontroller) on top of Zephyr, a
real-time operating system. `amelie_mcu.ino` is Amelie's sketch: it runs on
the microcontroller, not on Linux.

The UNO Q's **Qwiic** connector is wired to the microcontroller. Qwiic is a
four-wire connector (3.3 V, ground, SDA, SCL) that daisy-chains small modules
on the **I²C** bus: a two-line serial bus, data (SDA) and clock (SCL), on which
each device answers at its own 7-bit address. On the microcontroller that bus
is I²C4, which the sketch calls `Wire1`. That is why Amelie's two modules, the
light and the distance sensor, are visible only to the microcontroller, and
Linux reaches them through the link described below.

## The link with Linux

Linux and the microcontroller talk through the **Arduino router**,
`arduino-router`: a Linux service that receives the programs' requests on the
socket `/run/arduino-router.sock` and passes them to the microcontroller over
an internal serial line, and the other way round. The messages follow the
**MessagePack-RPC** protocol. An **RPC** (remote procedure call) is calling by
name a function that runs on another processor, with its parameters and its
result; **MessagePack** is the compact binary format the data travels in.

On the microcontroller side the sketch uses the **Arduino_RouterBridge**
library: its `Bridge` object registers the functions that Linux can call
(`Bridge.provide()`) and sends notifications (`Bridge.notify()`). On the Linux
side they are called by the `amelie.bridge` module (`src/amelie/bridge.py`).

## The two modules

| module | address | where it is and what it is for |
|---|---|---|
| **Modulino Pixels** | `0x36` | the device's light, which the code calls the "ring" (*anello*): eight LEDs on the optical panel in the tower, next to the camera, which light the label through the translucent plate. It goes white during the capture burst |
| **Modulino Distance** | `0x29` | the VL53L4CD distance sensor, under the disc the bottle stands on: it senses that the bottle has arrived. It is a time-of-flight (ToF) sensor: it measures how long infrared light takes to come back, and the sketch calls it `tof` |

Both addresses are the factory defaults: **there is nothing to reprogram
before assembly.**

The addresses are written in their 7-bit form. The Modulino Pixels datasheet
also gives `0x6C`, the "Modulino" address: it is the same `0x36` written on
eight bits, that is, shifted one place to the left to make room for the read or
write bit. Anyone writing their own sketch with the `Arduino_Modulino` library
must pass it `0x36`: with `0x6C` it fails **silently**, because `begin()` with
an explicit address returns `true` without querying the bus.

## When the modules are looked for

The modules are looked for **only when the microcontroller starts up**: that
is why they must be connected with the board switched off. The ring is looked
for straight away; the sensor as soon as the link with Linux is ready (see
[At power-up](#at-power-up)). The search ends when both have been found or when
ten seconds have passed since the microcontroller started up
(`ATTESA_MODULI_MS`), after at least one attempt for each: at power-up the link
with Linux comes later, and the sensor gets a single attempt.

A module counts as present only after a real answer: the ring after a
successful write, the sensor after returning its identity code (`0xEBAA`) and
completing its start-up. A module connected later, or a sensor that stops
responding, shows up as absent until the next power-up or the next firmware
upload, which restarts the microcontroller.

## The libraries

The **core** is the package that lets `arduino-cli`, Arduino's command-line
tool, compile for a board: for the UNO Q it is `arduino:zephyr`. On the UNO Q
`arduino-cli` is already installed; on another computer it is installed as
explained at <https://arduino.github.io/arduino-cli/latest/installation/>. The
sketch includes only one external library, **Arduino_RouterBridge**; `Wire`,
the I²C bus library, and the Zephyr headers are part of the core.

The fixed versions, the same ones that `scripts/install.sh` installs, are the
`arduino:zephyr` 0.52.0 core and `Arduino_RouterBridge` 0.4.3:

```bash
arduino-cli core update-index
arduino-cli core install arduino:zephyr@0.52.0
arduino-cli lib install Arduino_RouterBridge@0.4.3
```

`arduino-cli` installs by itself the libraries that Arduino_RouterBridge
depends on: Arduino_RPClite and, in turn, MsgPack with ArxContainer,
ArxTypeTraits and DebugLog. Their versions are not fixed: `arduino-cli` picks
them.

The sketch does not use the `Arduino_Modulino` library: every I²C transaction,
to the ring and to the sensor, is written by hand in the sketch, with a bounded
wait. The reason is in the comment at the top of `amelie_mcu.ino`: without
`Modulino.begin()` the library uses a null pointer; `begin()` with an explicit
address and `write()` return `true` even when the module does not respond; the
sensor driver can retry a transfer forever.

## Uploading it to the microcontroller

### From the board, with `install.sh`

`scripts/install.sh`, in step 9, installs the core and the library at the
fixed versions, compiles the sketch on the board and uploads it to the
microcontroller with `remoteocd`. `remoteocd` is the core's tool that uploads
the firmware through OpenOCD (Open On-Chip Debugger), a free program that
writes a microcontroller's memory through its debug port. Run on the board
with no address and no serial number, `remoteocd` works locally, with the
board's own OpenOCD, and **does not ask for a password**.

The script uploads the firmware again only when the sketch or the core and
library versions change: it keeps a fingerprint of them in
`var/firmware/.caricato`. It then tells App Lab, Arduino's environment for
creating and running apps on the UNO Q, not to start any app at power-up: an
App Lab app would replace this firmware on the microcontroller.

To upload the firmware again by hand from the board, for example to restart the
search for the modules, the script's own commands are enough, as the `arduino`
user:

```bash
cd ~/amelie
arduino-cli compile -b arduino:zephyr:unoq --output-dir var/firmware firmware/amelie_mcu
OCD=$(find ~/.arduino15/packages/arduino/tools/remoteocd -name remoteocd -type f | sort -V | tail -1)
CFG=$(find ~/.arduino15/packages/arduino/hardware/zephyr/0.52.0/variants -name flash_sketch.cfg | head -1)
"$OCD" upload -f "$CFG" var/firmware/amelie_mcu.ino.elf-zsk.bin
```

`arduino:zephyr:unoq` is the board's full name for `arduino-cli` (the FQBN,
fully qualified board name).

### From another computer, over the network

On a computer on the same network as the board, with the core and the library
installed as above:

```bash
arduino-cli board list      # shows the board and its network address
arduino-cli compile -b arduino:zephyr:unoq --upload -p <board-address> firmware/amelie_mcu
```

This way `remoteocd` connects to the board over SSH, the encrypted remote
terminal, to run OpenOCD there, and asks for the **password of the `arduino`
user**. The command must therefore be run from an interactive terminal: from a
non-interactive script the upload fails with *"user input not supported in
non interactive mode"*. To upload without a password, use `install.sh` or the
commands in the previous section, on the board.

### Compiling it without the board

With the core and the library installed as above, the sketch compiles on any
computer, without the board and without the modules:

```bash
arduino-cli compile -b arduino:zephyr:unoq firmware/amelie_mcu
```

Uploading it needs the board.

## The methods exposed to Linux

| method | parameters | returns |
|---|---|---|
| `set_anello` | r, g, b (0-255), brightness (0-100) | `true`; the colour is applied at the next pass of `loop()`, if the ring is present |
| `distanza` | — | the last measurement in millimetres, or `-1` if the last measurement is not valid or the sensor is not present |
| `moduli` | — | which modules it sees, as a sum of bits: **1** the ring, **2** the sensor (from 0 to 3) |
| `versione` | — | the **protocol** version: `2` |

There is also one **notification**, that is, a message the microcontroller
sends on its own initiative, without waiting for an answer:
`bottiglia(presente, mm)`, sent when `presente` changes, at most ten times per
second. `presente` is true with a valid measurement below 10 cm. The
application on Linux does not use it: it queries `distanza` and decides by
itself whether the bottle is there, with hysteresis, that is, with two separate
thresholds for arriving and for leaving and with several readings in a row
before changing its mind, so that a measurement wavering near a threshold
triggers nothing (the `Presenza` class in `amelie.bridge`).

`versione` does not say which build is running: it says **what the answers
mean**, and it changes only when a meaning changes, not when the code changes.
That is why `Ponte.moduli()` asks for the version first and, if it is not the
expected one (`PROTOCOLLO_ATTESO` in `amelie.bridge`), answers "I see nothing"
and writes that to the log: a Linux side and a microcontroller speaking two
different protocols would read the same bits with two different meanings, and
"I don't know" is better than an inverted answer for whoever is assembling the
device.

Three methods are for diagnostics, and `scripts/bus.py` uses them:

| method | parameters | returns |
|---|---|---|
| `scansiona` | block 0-3 | a 32-bit mask: bit *i* is 1 if address block × 32 + *i* responds. Four calls cover all the 7-bit addresses; the reserved ones, below `0x08` and above `0x77`, are not tried |
| `stato_tof` | — | where the sensor start-up stopped: `0` succeeded, `-1` never attempted, from `1` to `6` the step that failed (the list is in the sketch) |
| `registro_tof` | 0-5 | a raw sensor register (the list is in the sketch); `-1` if the sensor does not respond to the read, `-2` if the sensor is not present, `-3` if the number is outside 0-5 |

## At power-up

An Arduino sketch has two fixed functions: `setup()`, run once at start-up, and
`loop()`, repeated forever.

The microcontroller is ready in a few milliseconds. The link with Linux comes
when `arduino-router` starts, about forty seconds after power-up, and until
then `Bridge.begin()` waits and `setup()` does not finish. In the meantime the
ring **breathes in amber**, to show that the device is on: the sketch switches
it on before it starts waiting, and a separate thread makes it breathe during
the wait. The breathing stops at the first `set_anello` from Linux; from then
on the colour is decided by the application.

As the very first step, at every start-up, the firmware frees the I²C bus with
`i2c_recover_bus()`. A module reset in the middle of a byte can stay convinced
that it is transmitting and hold SDA low: then no transaction can start, not
even to the ring, and the device looks as if it had no firmware. The recovery
manoeuvre clocks the bus until the module releases the line, then sends a
STOP. Without it, the only way out would be to cut the power to everything:
uploading the firmware again restarts the microcontroller, not the module
holding the line down.

## Three ways to fail silently, and how they are avoided

**A module that does not respond must not stop `setup()`.** If `setup()` does
not finish, Linux never sees the methods: the router accepts the connection and
every call answers *"method not available"*, the same symptom as missing
firmware. That is why every I²C transaction in the sketch has a bounded wait,
the modules are **searched for** instead of being assumed present, and a module
counts as present only after a write or a read that succeeded.
`Bridge.provide()` is reached as soon as the link is ready, and no module can
prevent it.

**A handler does not call the bridge.** A handler is the function that the
sketch registers with `Bridge.provide()` and that Linux calls by name. Calling
`Bridge.call()` or `Monitor.print()` (printing messages to Linux) inside a
handler stalls the channel. The sketch's handlers write to a variable that
`loop()` then applies, or at most read the bus under a lock, a Zephyr mutex:
they run on a library thread, not inside `loop()`, and two threads on the same
bus would mix up the answers.

**A `.ino` is not a `.cpp`.** Arduino generates the prototypes of all functions
and inserts them right before the first function definition in the file: a type
declared after that point does not exist yet when the prototype names it, and
the compiler gives a `has not been declared` error on a line that is *below*
the declaration and looks correct. That is why in the sketch all types and
variables are at the top, and the functions come after.

## Power

The eight LEDs are powered from the Qwiic cable, 28 AWG, at 3.3 V. Outside the
burst the brightness stays between **22 and 30** out of 100 (22 for amber, 30
for green and red), and goes up to **90, in white**, only for the capture burst
and with "Debug camera" on: seconds, not a flash. Do not leave the ring at
maximum "to see if it works": if the 3.3 V supply sags, I²C drops out too, and
it looks like a module fault.
