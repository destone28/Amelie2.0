# Assembling Amelie

Amelie's enclosure is made of 11 printed parts, held together by only two types
of screw. This guide says what to print, where each component goes and in which
order the device is closed. The electrical connections are in the
[wiring diagram](../images/wiring.png).

The order is not arbitrary. The four screws that hold the tower to the base are
driven **from inside the base**, and can only be reached while the bottom is
open. That is why the bottom (the Piastra, on the bench) and the tower are
assembled first, then the shell is closed, and the Piastra is screwed to the
base last.

![Two assembled units of Amelie](../images/foto/due-esemplari.jpg)

*Two units built from the same printing files, with some parts in different colours.*

## The parts to print

The files are in [`hardware/stl/`](../../hardware/stl/).

![The 11 printed parts](../images/parti.png)

| Part | What it is | Material |
|---|---|---|
| `Base.stl` | the shell: the top with the hole for the disc and the seat of the tower, the walls, the charging socket at the back | PLA |
| `Piastra.stl` | the removable bottom: seats for the power bank, hub, UNO Q, speakers and switch, with the speaker grilles and the window for the switch lever | PLA |
| `Torre.stl` | the tower, a 30° wedge that holds the screen at the front and the optics at the back | PLA |
| `Frontale.stl` | the frame around the screen, flush with the ramp | PLA |
| `PannelloOttico.stl` | the panel inside the tower: camera and Modulino Pixels | PLA |
| `CerchioLuce.stl` | the disc the bottle stands on; the Modulino Distance is mounted underneath | **translucent PETG** |
| `PlaccaLuce.stl` | the small plate that closes the light window at the back of the tower and diffuses the light | **translucent PETG** |
| `VassoioLuce.stl` | the bridge over the power bank, under the disc: it closes the bottom of the light chamber | PLA |
| `FermoHub.stl` | the clip that holds the hub in its cradle | PLA |
| `FermoSwitch.stl` | the cover that closes the switch in its seat | PLA |
| `FermoUno.stl` | the bridge that holds the UNO Q on its pins | PLA |

The Base is printed **upside down**, with the top on the build plate. For all
parts 15-20 % infill is enough; the wood screws cut their own thread in the
plastic, so do not enlarge the pilot holes.

## Screws

Two types of screw in the whole device, both countersunk.

| Screw | How many | Where |
|---|---|---|
| wood screw 4 × 16 mm | 4 | Frontale → Torre |
| | 2 | PannelloOttico → Torre |
| | 4 | Torre → Base |
| | 6 | Piastra → Base |
| | 2 | FermoUno → Piastra |
| M2 × 5 mm | 4 | camera → PannelloOttico |
| | 2 | Modulino Distance → CerchioLuce |
| | 2 | PlaccaLuce → Torre, from inside |
| M2 × 6 mm | 4 | screen → Torre, through its tabs |
| | 2 | Modulino Pixels → PannelloOttico |
| M2 × 8 mm | 2 | FermoSwitch → Piastra |

That is 18 wood screws 4 × 16 and 16 M2 screws. You also need 4 adhesive
rubber feet (3 mm) and, optionally, a few cable ties. Give the last two turns of
every screw by hand: in plastic a power driver strips the thread.

## Before assembling: the camera

The camera's M12 lens leaves the factory focused far away. The label is about
100 mm from it: focus it now, with the camera connected to a computer (it is an
ordinary USB webcam) and a label 10 cm away, turning the lens in its holder
until the small print is sharp. The fine adjustment is done on the assembled
device, with **Debug camera** ([Testing](04-testing.md)).

![Exploded view: from the bottom, the Piastra with its clamps, the Base with the disc, the tower with its frame, the optical panel and the small light plate](../images/esploso.png)

## Phase A: the Piastra

Work on the bench, with the Piastra lying flat and the inside facing up. The
front of the device, the side of the screen, is the side of the two speakers.

1. **The speakers.** The two speakers go into the cages in the two front
   corners, membrane facing down, on the grilles.
2. **The power bank.** It goes into the enclosure in the middle, **upside
   down** and with the ports towards the back: that way the Output 3 port ends
   up on the right, near the hub, and the USB-C In-Out port faces the charging
   socket.
3. **The hub.** It goes into the cradle on the right, with the row of ports
   facing the power bank, the built-in USB-C cable towards the **back** and the
   HDMI port towards the **front**. The FermoHub clips over it, no screws.
4. **The UNO Q.** It goes between the two speakers, on the four pins, with the
   USB-C socket towards the back and the Qwiic connector towards the front. The
   FermoUno straddles the Qwiic side and is fixed with two 4 × 16 screws.

   <img src="../images/foto/uno-q.jpg" alt="The UNO Q on the Piastra" width="480">

   *The UNO Q held by the FermoUno: the Qwiic cable at the top, the USB-C cable at the bottom.*
5. **The switch.** The body of the switch on the power cable lies flat in its
   seat in the rear bay, with the lever in the window of the bottom: it is
   operated from underneath the device. The FermoSwitch closes it with two
   M2 × 8 screws.

   ![The switch lever in the window in the bottom](../images/foto/interruttore.jpg)

   *The finished device seen from underneath: the switch lever in its window, next to a foot.*
6. **The cables.**
   - the switch cable: its USB-A plug into the power bank's **Output 3** port,
     its 90° USB-C plug into the hub's **USB-C PD** port;
   - the hub's built-in cable: it leaves from the back side, turns, runs resting
     on top of the hub and comes down to the UNO Q's USB-C;
   - the speakers: their USB plug into a USB-A port of the hub; the audio jack
     is connected to the screen in phase B. Turn the volume control on their
     cable all the way up: once the enclosure is closed you can no longer reach
     it, and the volume is set from the screen;
   - a Qwiic cable in the UNO Q's connector, along the front wall: it will go
     to the first of the two Modulino boards;
   - the charging extension: its 90° male plug into the power bank's **USB-C
     In-Out** port; the female end is fixed in phase C.
7. **The VassoioLuce.** It stands on its four legs, bridging over the power
   bank.

<img src="../images/foto/piastra.jpg" alt="The assembled Piastra seen from above" width="480">

*The assembled Piastra, seen from above: the two speakers and the UNO Q towards the front, the power bank in the middle, the hub next to it and the cables.*

## Phase B: the tower

Assemble the tower upside down or on its side: you work through the open belly.

1. **The PlaccaLuce.** It goes into the window at the back of the tower, from
   inside, with two M2 × 5 screws. It is where the light towards the bottle
   comes out.
2. **The PannelloOttico.** Modules first:
   - the camera, **rotated 90°**, on its frame, with four M2 × 5 screws; the
     lens holder fits into the notch in the panel;
   - the Modulino Pixels on its four pads, with two M2 × 6 screws and the two
     centring pins in the other two holes, LEDs towards the window;
   - a Qwiic cable in the Pixels, and the camera's USB cable.

   Then the panel goes into the tower and is fixed with two 4 × 16 screws.

   <img src="../images/foto/torre-interno.jpg" alt="Inside the tower" width="480">

   *Inside the tower, lying on its side: the camera and the Modulino Pixels on the PannelloOttico, each with its cable; behind them, the back of the screen.*
3. **The screen.** It goes into the pocket of the ramp, glass facing out and
   connectors at the bottom, fixed through its four tabs with four M2 × 6
   screws. Connect the HDMI cable, the USB-A to micro-USB cable of the touch
   (the one in the power bank's box) and the speakers' audio jack now: you won't
   reach them later.
4. **The Frontale.** It closes the ramp around the screen and is fixed from
   inside the tower with four 4 × 16 screws.

## Phase C: the shell

Turn the Base upside down, with the top on the bench and the open bottom facing
up.

1. **The CerchioLuce.** Screw the Modulino Distance under the disc with two
   M2 × 5 screws, the sensor towards the disc's window. Connect the Qwiic
   cable. The disc goes into its hole from the top and locks with a sixth of a
   turn: three tabs slide under the ledge. It comes out the same way.

   <img src="../images/foto/disco-sensore.jpg" alt="The CerchioLuce seen from below, with the Modulino Distance" width="480">

   *The CerchioLuce seen from below, in its hole: the Modulino Distance in the middle, with its Qwiic cable, and the three tabs under the ledge.*
2. **The charging socket.** The female end of the extension goes into its seat
   in the back wall of the Base, with the opening facing outwards.
3. **The tower.** It sits in its seat on the top of the Base; the cables of the
   screen, camera and Pixels go down through the opening. Fix it with four
   4 × 16 screws **from inside the Base, upwards**.

## Phase D: closing

1. **The connections between the Piastra and the rest.**
   - HDMI: the screen's cable into the hub's HDMI port;
   - USB: the screen's touch and the camera into the two free USB-A ports of
     the hub;
   - Qwiic: the UNO Q, the Modulino Distance and the Modulino Pixels in a
     chain; the order doesn't matter.

   <img src="../images/foto/prima-di-chiudere.jpg" alt="Before closing: the open Base above the Piastra" width="480">

   *Before closing: the Base upside down, with the disc, the sensor and the back of the screen, above the Piastra with all the connections made.*
2. **Test before closing.** Switch on with the switch underneath and check the
   waiting screen, the voice (tap the active flag), and that placing a bottle on
   the disc makes the screen say "Let me have a look…". The Modulino boards are
   looked for at power-on: if one is missing, switch off, check the cable and
   switch on again.
3. **The Piastra.** Lower it into the Base, with the cables tucked into their
   bays, and fix it with six 4 × 16 screws from the bottom.
4. **The feet.** The four adhesive feet in their seats under the Piastra.

![The bottom of two units](../images/foto/fondo.jpg)

*The bottom of two units: the four feet, the speaker grilles and the switch window.*

## Charging

The device charges from the USB-C socket at the back with an ordinary USB-C
charger, also while it is on. After charging, tap **Battery recharged** in the
settings, so the estimate starts from full again ([Using Amelie](05-usage.md)).

![The charging socket in the back wall](../images/foto/piatto-camera-luce.jpg)

*The plate side: the camera and the light window face the disc, and the charging socket is low in the back wall.*

## Next step

[Testing Amelie](04-testing.md).
