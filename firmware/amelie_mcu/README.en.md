# Microcontroller firmware

`amelie_mcu.ino` runs on the UNO Q's **STM32U585**, not on the Linux side. The
Qwiic connector is wired to the MCU's I²C4, which in the sketch is called
`Wire1`: the LED ring and the distance sensor are visible only to the
microcontroller, and Linux talks to them through Arduino's router
(`arduino-router`), using the Bridge library.

## The two modules

| module | address | what it is for |
|---|---|---|
| **Modulino Pixels** | `0x36` | the ring under the bottle; goes white during the capture burst |
| **Modulino Distance** | `0x29` | senses that the bottle has arrived |

Both addresses are the factory defaults: **there is nothing to
reprogram before assembly.**

`0x36` is the **hardware** address. The datasheet calls `0x6C` the
"Modulino" address (it is the same `0x36` written on eight bits): passing it to
the `Arduino_Modulino` library fails **silently**, because `begin()` returns
`true` anyway.

The modules are detected **when the microcontroller powers up**: they must be
connected with the board switched off. A module connected later, or a sensor
that stops responding, shows up as absent until the next power-up or the next
firmware upload.

## The libraries

The tested versions are the `arduino:zephyr` 0.52.0 core,
`Arduino_RouterBridge` 0.4.3 and `Arduino_Modulino` 0.9.0:

```bash
arduino-cli core install arduino:zephyr@0.52.0          # ~1.2 GB, only once
arduino-cli lib install Arduino_RouterBridge@0.4.3 Arduino_Modulino@0.9.0
```

To compile the sketch only `Arduino_RouterBridge` is needed: `Arduino_Modulino`
is not included, because every I²C transaction is written by hand in the sketch
(the reason is in the comment at the top of `amelie_mcu.ino`). It is installed
for its examples, which are handy for testing a module on its own.

## Uploading it

`scripts/install.sh` compiles and uploads it. By hand:

```bash
arduino-cli board list      # gives the board's network address, e.g. <board-address>
arduino-cli compile -b arduino:zephyr:unoq --upload -p <board-address> firmware/amelie_mcu
```

The upload asks for the **password of the `arduino` user**, so it must be run
from an interactive terminal: from a non-interactive script it fails with
*"user input not supported in non interactive mode"*.

There is no way around this. The upload goes through `remoteocd`, which opens
an SSH connection to the board and runs OpenOCD there, and that program accepts
**only the password**: an SSH key that is already set up does not help, and an
empty `--upload-field password=` is rejected. Compiling, on the other hand,
asks for nothing.

It is uploaded with `arduino-cli`, not from App Lab.

## Compiling it without the board

With the core and the libraries installed as above:

```bash
arduino-cli compile -b arduino:zephyr:unoq firmware/amelie_mcu
```

This is how you find out that the firmware compiles before you have the
Modulino modules in hand. Uploading, on the other hand, does need the board.

## The methods exposed to Linux

| method | parameters | returns |
|---|---|---|
| `set_anello` | r, g, b (0-255), brightness (0-100) | `true` |
| `distanza` | — | millimeters, or `-1` if the measurement is not valid |
| `moduli` | — | sum of bits: **1** ring, **2** sensor |
| `versione` | — | the **protocol** version: currently `2` |

And one notification: `bottiglia(presente, mm)`, sent at every change and no
more than ten times per second. `presente` means a valid measurement below
10 cm; the real decision, with its hysteresis, is made by Linux in
`amelie.bridge`.

`versione` does not say which build is running, it says **what the answers
mean**: it goes up when a meaning changes, not when the code changes. That is
why `Ponte.moduli()` asks for the version first, and if it is not the expected
one (`PROTOCOLLO_ATTESO` in `amelie.bridge`) it answers "I see nothing" and
writes that to the log: a Linux side and an MCU speaking two different
protocols would read the same bits with two different meanings, and "I don't
know" is better than an inverted answer for someone holding the cables.

Three methods are for diagnostics, and `scripts/bus.py` uses them:

| method | parameters | returns |
|---|---|---|
| `scansiona` | block 0-3 | the bits of the addresses that respond, 32 per block |
| `stato_tof` | — | where the sensor startup stopped: `0` succeeded, `-1` never attempted, otherwise the step |
| `registro_tof` | 0-5 | a raw sensor register (see the sketch); `-1` if it does not respond, `-2` if the sensor is not there |

## At power-up

The microcontroller is ready in milliseconds, Linux in about forty
seconds. In the meantime the ring **breathes in amber**, to show that the
device is alive; it stops at the first `set_anello` from Linux, and from then
on the color is decided by the application.

First of all the firmware unlocks the I²C bus (`i2c_recover_bus()`): a module
reset in the middle of a byte can hold SDA low, and then no transaction can
start anymore, not even to the ring. Uploading the firmware again is not
enough, because that resets the microcontroller and not the module holding the
line down.

## Three ways to fail silently, and how they are avoided

**A module that does not respond must not stop `setup()`.** If `setup()` does
not finish, Linux never sees the methods: the router accepts the connection and
every call says *"method not available"*, the same symptom as missing
firmware. That is why every I²C transaction in the sketch has a bounded wait,
the modules are **searched for** instead of being assumed present, and a module
counts as present only after a write or a read that succeeded.
`Bridge.provide()` is reached as soon as the bridge is ready, and no module can
prevent it.

**A handler does not call the bridge.** Calling `Bridge.call()` or
`Monitor.print()` inside a handler registered with `provide()` stalls the
channel. The sketch's handlers write to a variable that `loop()` then applies,
or at most read the bus under a lock: the handlers run on a library thread, not
in `loop()`, and two threads on the same bus mix up the answers.

**A `.ino` is not a `.cpp`.** Arduino generates the prototypes of all functions
and inserts them right before the first function definition in the file: a type
declared after that point does not exist yet when the prototype names it, and
you get a `has not been declared` on a line that is *below* the declaration and
looks correct. That is why in the sketch all types and variables are at the
top, and the functions come after.

## Power

Eight LEDs on a 28 AWG Qwiic cable. Outside the burst the ring stays between
**22 and 30** brightness — 22 while waiting, 30 in the states that ask for
something — and goes up to **90 in white** for the duration of the burst:
seconds, not a flash. Do not leave it on at maximum "to see if it works": if
the 3.3 V rail sags, I²C drops out too, and it looks like a module fault.
