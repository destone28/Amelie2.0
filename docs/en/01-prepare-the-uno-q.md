# Preparing the UNO Q

A new Arduino UNO Q leaves the factory with its operating system, Debian Linux,
already installed on its internal memory. Before installing Amelie it needs five
things:

- a **name**, used to reach it on the network;
- a **password** for the `arduino` user: the factory password has to be changed
  at the first setup;
- the **Wi-Fi network**;
- the **updates** of the Arduino packages;
- **network mode** switched on: it switches on SSH, the remote terminal used to
  work on the board from the computer, and makes the board answer to its name
  followed by `.local`.

This guide does them in two ways, with Arduino App Lab or from a terminal, and
ends with the board reachable over SSH as `amelie.local`.

## What you need

- the UNO Q, **on its own**: no hub, no screen, no Modulino;
- a computer with Windows, macOS or Linux;
- a USB-C **data** cable, not a charge-only one (the most common reason why the
  computer does not see the board), plugged straight into a port of the
  computer, not into a hub;
- the name and the password of the Wi-Fi network.

The UNO Q has a single USB-C port, and that port works in two ways:

- **connected to the computer** it acts as a peripheral: it takes power from the
  computer and lets itself be configured. This is the mode used in this guide;
- **connected to the hub**, as in the assembled device, it acts as a host: it
  powers the screen, the camera and the speakers, and receives power from the
  power bank through the hub. From then on it can only be reached over Wi-Fi.

The two cannot happen at the same time: while the board is in the hub, the
computer cannot see it through the cable. That is why the network is set up now.

## With Arduino App Lab

1. Download Arduino App Lab from <https://www.arduino.cc/en/software/> and
   install it. On Linux, the download page also explains how to install the
   udev rules: without them, the system does not give your user permission to
   talk to the board over USB.
2. Open App Lab and connect the UNO Q with the USB-C cable. After a few seconds
   the board appears among the devices; select it.
3. App Lab starts the first setup:
   - as the **board name**, type `amelie`: the rest of the documentation reaches
     it as `amelie.local`. If you build more than one Amelie, give each board its
     own name (`amelie2`, `amelie3`…) and use that name instead of `amelie` in
     every command;
   - choose the keyboard layout and the **Wi-Fi network**;
   - choose the **password** of the `arduino` user. Keep it: you need it for SSH
     and for the installation.
4. If App Lab offers an **update** of the board, accept it and wait until it
   finishes.
5. Check **network mode** (see "The board's terminal" below):
   `arduino-app-cli system network-mode status` must answer `enabled`.

You don't need to create or start any App Lab app: Amelie has its own firmware
and services, and the installer loads them by itself.

## The board's terminal

The commands in this guide need a terminal on the board. While the board is
connected to the computer with the USB-C cable, you open it with `adb`, the
Android tool for debugging over USB:

- on Debian and Ubuntu, install it with `sudo apt install adb`;
- on macOS and Windows, it is part of Android's "SDK Platform-Tools",
  <https://developer.android.com/tools/releases/platform-tools>.

With the board connected, on the computer:

```bash
adb devices          # the board must be listed as "device"
adb shell            # opens a terminal on the board, as the arduino user
```

Type `exit` to leave the board's terminal. On Linux, if `adb devices` does not
list the board or says "no permissions", the udev rules of step 1 are missing.

## From a terminal, without App Lab

The same steps can be done from the board's terminal (`adb shell`), in this
order. The first one sets the password; after that, only switching on network
mode asks for it: the `arduino` user is already allowed to run the others.

```bash
# The password of the arduino user. Type the new password and press Enter:
# nothing appears while you type.
sudo arduino-passwd

# The Wi-Fi network
nmcli device wifi connect "NETWORK-NAME" password "NETWORK-PASSWORD"

# The name: the board will answer as amelie.local
arduino-app-cli system set-name amelie

# The updates of the Arduino packages
arduino-app-cli system update --only-arduino --yes

# Network mode: it switches on SSH and the .local name. It asks for the
# password you have just chosen.
arduino-app-cli system network-mode enable
arduino-app-cli system network-mode status    # must answer "enabled"
```

## Checking

From the computer, with the board still connected or already unplugged:

```bash
ping -c 3 amelie.local
ssh arduino@amelie.local
```

The first time, SSH asks you to confirm the board's fingerprint: type `yes`.
Then it asks for the password of the `arduino` user. Once in, check the space and
the system:

```bash
df -h ~              # at least 4 GB must be free
cat /etc/os-release  # Debian GNU/Linux 13 (trixie)
```

If `amelie.local` does not answer:

- check that network mode is on (`arduino-app-cli system network-mode status`
  from the board's terminal);
- some networks (guest Wi-Fi, office networks) block `.local` names: use the
  board's IP address, which the board's terminal shows with `hostname -I`, for
  example `ssh arduino@192.168.1.50`;
- some Windows computers cannot resolve `.local` names: there too, use the IP
  address.

To avoid typing the password at every connection, copy your SSH key to the board
(if you don't have one, `ssh-keygen` creates it):

```bash
ssh-copy-id arduino@amelie.local
```

## If the board does not start, or you want to start over

It is almost never needed. The factory system is fine, and everything Amelie
installs lives in the `/home/arduino` folder, which has a partition of its own
with plenty of space. If, however, the board no longer starts, or you want it
back as it left the factory, Arduino explains how to rewrite the system image
with Arduino Flasher CLI: <https://docs.arduino.cc/tutorials/uno-q/update-image/>.
Rewriting the image erases everything on the board; afterwards, start again from
this page.

## Next step

[Installing the software](02-install.md).
