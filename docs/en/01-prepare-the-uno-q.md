# Preparing the UNO Q

An Arduino UNO Q fresh out of the box already has its operating system,
Debian, on its internal storage. Before you install Amelie it needs four
things: a name, a password, the Wi-Fi network and the latest updates. This
guide sets them up in two ways, with Arduino App Lab or from the terminal, and
ends with the board reachable over SSH as `amelie.local`.

## What you need

- the UNO Q **on its own**: no hub, no screen, no Modulino boards;
- a computer running Windows, macOS or Linux;
- a USB-C **data** cable, not a charge-only one (it is the most common reason
  the computer does not see the board), plugged into a port on the computer,
  not into a hub;
- the name and password of the Wi-Fi network.

The UNO Q has a single USB-C port, and that port works in two ways:

- **connected to the computer** it acts as a peripheral: it draws power from
  the computer and lets itself be configured. This is the mode used in this
  guide;
- **connected to the hub**, as in the assembled device, it acts as a host: it
  powers the screen, camera and speakers, and receives power from the power
  bank through the hub. From then on it can be reached only over Wi-Fi.

The two do not go together: when the board is in the hub, the computer cannot
see it over the cable. That is why the network is set up now.

## With Arduino App Lab

1. Download Arduino App Lab from <https://www.arduino.cc/en/software/> and
   install it. On Linux, also follow the udev rules instructions on the
   download page: without them, the system does not give your user permission
   to talk to the board.
2. Open App Lab and connect the UNO Q with the USB-C cable. After a few seconds
   the board appears among the devices; select it.
3. App Lab starts the first-time setup. When it asks for the **board name**,
   type `amelie`: the rest of the documentation reaches it as `amelie.local`.
   Choose the keyboard layout, the **Wi-Fi** network and a **password** for the
   `arduino` user. Keep it handy: you need it for SSH and for the
   installation.
4. If App Lab offers a board **update**, accept it and wait for it to finish:
   the board reboots by itself.

There is no need to create or start any App Lab app: Amelie has its own
firmware and its own service, and the installer loads it by itself.

## From the terminal, without App Lab

You need `adb`, the Android tool for debugging over USB (on Debian and Ubuntu
`sudo apt install adb`; on macOS and Windows it is in Android's
"platform-tools" package). With the board connected to the computer:

```bash
adb devices          # the board must show up as "device"
adb shell            # a shell on the board, as the arduino user
```

From the board's shell:

```bash
# The Wi-Fi network
sudo nmcli device wifi connect "NETWORK-NAME" password "NETWORK-PASSWORD"

# The name: the board will answer as amelie.local
sudo arduino-app-cli system set-name amelie

# The password of the arduino user
passwd

# Updates to the system and the Arduino packages
sudo arduino-app-cli system update --yes

# SSH access
sudo systemctl enable --now ssh

sudo reboot
```

## Checking

From the computer, with the board still connected or already unplugged:

```bash
ping -c 3 amelie.local
ssh arduino@amelie.local
```

The first time, SSH asks you to confirm the board's fingerprint, then the
password. Once in, check disk space and system:

```bash
df -h /home          # you need at least 4 GB free
cat /etc/os-release  # Debian GNU/Linux 13 (trixie)
```

If `amelie.local` does not respond, your computer does not resolve `.local`
names (this happens on some corporate networks and on Windows without Bonjour):
use the IP address, which you can read in the board's shell with
`hostname -I`.

To avoid typing the password every time, copy your SSH key to the board:

```bash
ssh-copy-id arduino@amelie.local
```

## If the board does not boot, or you want to start from scratch

You almost never need this. The factory system is fine, and everything Amelie
installs goes in `/home/arduino`, where there is plenty of space. If, however,
the board no longer boots, or you want to bring it back to how it left the
factory, Arduino explains how to rewrite the system image with Arduino Flasher
CLI: <https://docs.arduino.cc/tutorials/uno-q/update-image/>. Rewriting the
image erases everything on the board; afterwards, start again from this page.

## Next step

[Installing the software](02-install.md).
