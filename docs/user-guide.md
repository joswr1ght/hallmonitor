# hallmonitor kit user guide

The hallmonitor kit records classroom temperature and humidity every 5 minutes and sends the
readings to a staff page, so event staff can see a room is too warm or too cold before students
complain. The kit is set up before it ships. Instructors plug it in at the start of a class and do
nothing else, whatever course they teach. The setup portal described below is only for recovery,
such as a class network whose password changed.

## What is in the kit

* The kit: a small M5Stack StickS3 with a screen and a blue button on the face. A label on it
  shows the kit ID.
* A Govee thermometer and hygrometer (an H5074). It measures the room and reports to the kit over
  Bluetooth. It runs on its own coin cell battery and carries the same kit ID label.
* A USB power supply and cable.

## Setting up in the classroom

1. Put the Govee sensor in the room where it measures the room air: away from windows, heating and
   air conditioning vents, and projectors, and within a few meters of the kit.
2. Plug the kit into USB power somewhere it will stay plugged in all week. A spot near an outlet
   that nobody needs for a laptop charger works best.
3. Check the screen. Within a few minutes it shows the room temperature, the Wi-Fi network it
   joined, and "Sent ... ago". If the screen stays dark, press the power button once.

The kit joins the strongest SANS class network it knows, which does not have to be the network for
the course in that room. Nothing on the kit names the course; the staff page lists the kit by the
instructor's name.

The kit needs USB power for the whole class. Its battery lasts about an hour and a half, enough
to move the kit or ride through a short unplug. When the battery runs out, the kit stops recording
until it is plugged in again, and the staff page shows its last reading as stale.

## What the screen shows

From top to bottom:

| Line | Meaning |
|---|---|
| Temperature and humidity | The latest reading from the Govee sensor, in °F and percent |
| Instructor name | The name the staff page lists the kit under |
| Sensor name, signal, and age | The paired Govee sensor, its Bluetooth signal strength, and how long ago the kit heard it |
| `Wi-Fi <network> <signal>` | The network the kit joined and its signal strength |
| `Sent <time> ago, <n> queued` | When the kit last sent readings, and how many readings wait to be sent |
| `Kit <ID>` and power | The kit ID on the left; on the right, `USB` or `Battery`, with the battery level |

Lines in orange need attention. See "Troubleshooting" below.

## Buttons

| Button | Action | Result |
|---|---|---|
| Blue button on the face | Hold for 3 seconds | Starts the setup portal (see below). The kit beeps and the screen shows a QR code. |
| Blue button on the face | Press while the setup portal is showing | Leaves the setup portal and restarts the kit. |
| Power button | Press once | Turns the kit on, or restarts it if it is already on. |
| Power button | Press twice quickly | Turns the kit off. |
| Power button | Hold | Puts the kit in download mode for loading new firmware. The screen goes dark and the kit stops recording. Press the power button once to restart it. |

The kit's third button does nothing.

Holding the power button by mistake is the easiest way to stop a kit. If the screen goes dark
after holding a button, press the power button once and confirm the reading returns.

## The setup portal (recovery)

Use the setup portal when the kit cannot get online, for example when the class network password
changed, or to pair a replacement Govee sensor. It needs a phone and takes a few minutes.

1. Hold the blue button on the face for 3 seconds. The kit beeps and the screen turns white with a
   QR code, a network name (`hallmon-<kit ID>`), a password, and `192.168.4.1`. The password is
   new each time.
2. Scan the QR code with a phone camera to join the kit's network. Most phones open the setup page
   on their own. If one does not, browse to `http://192.168.4.1`.
3. Make the changes the page offers:
   * **Status**: the instructor name, the sensor's latest reading, and the last upload.
   * **Wi-Fi**: the networks the kit knows, with their signal strength. To add a network or fix a
     password, choose the network (or type its name), enter the password, and tap "Test and save".
     The kit tries the password before saving it. While it tests, the phone may drop off the kit's
     network for a moment; rejoin it and the result waits on the page. To save a network that is
     out of range, tick "Save even if the kit cannot connect now".
   * **Sensor**: every Govee sensor the kit hears, strongest first. Put the sensor next to the kit
     so it tops the list, choose it, and tap "Pair this sensor".
   * **Instructor**: the name the staff page shows for the kit.
4. Tap "Restart and reconnect", or press the blue button once. The kit restarts and rejoins Wi-Fi
   with the saved networks.

Changes save as they are made. The portal closes on its own after 10 minutes without activity.

## Troubleshooting

| Screen shows | What to do |
|---|---|
| `Wi-Fi: searching` | The kit knows no network in range, or a password changed. Add the network in the setup portal. |
| `<sensor> not heard` | Move the Govee sensor closer to the kit. If its battery is flat, replace the coin cell. After replacing the sensor itself, pair the new one in the setup portal. |
| `No sensor paired` | Pair the Govee sensor in the setup portal. |
| `Waiting for the clock` | The kit is online but has not set its clock yet. It records nothing until it has. This clears on its own within a few minutes; if it does not, the network may block the kit. |
| `Upload: token rejected` | The server no longer accepts this kit. Contact Josh with the kit ID. |
| `Upload: ...` with another message | The kit cannot reach the server. Readings wait on the kit and are sent once it can. If it lasts more than an hour, contact Josh with the kit ID and the message. |
| Dark screen | Press the power button once. |

## The staff page

Event staff and instructors see every kit's readings at
`https://hallmonitor.willhackforsushi.com` with the shared staff password from Josh. The page lists
kits by instructor name, shows the latest reading and charts for the past day, 3 days, and week,
and warns when a kit has not reported for 12 minutes.
