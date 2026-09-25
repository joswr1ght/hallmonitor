# firmware

Firmware for the hallmonitor kit: an M5StickC Plus2 paired with a Govee sensor. The kit reads the
sensor over Bluetooth Low Energy (BLE), queues a reading every 5 minutes, joins the strongest known
Wi-Fi network, and uploads batches to the server. The screen shows the current reading and the
kit's status.

Status: milestones 1 to 4 (screen, BLE decoding, uploads, and `provision.py`) are written. The
firmware compiles and `provision.py` passed a test against a simulated kit, but neither has run on
hardware yet. The setup portal and over-the-air (OTA) updates are not started. See Phase 2 in
[../docs/plan.md](../docs/plan.md).

## Toolchain

The firmware uses the Arduino framework, built with PlatformIO. Install PlatformIO once with `uv`:

```sh
uv tool install platformio
```

Build, flash over USB-C, and open the serial console from this directory:

```sh
pio run                     # build only
pio run -t upload           # build and flash the connected kit
pio device monitor          # serial console at 115200 baud
```

The first build downloads the ESP32 toolchain and takes a few minutes. The libraries are M5Unified
(screen, buttons, power, and RTC), NimBLE-Arduino (BLE scanning), and ArduinoJson.

## Source layout

| File | Purpose |
|---|---|
| `src/main.cpp` | Setup and the main loop |
| `src/config.*` | Settings stored in flash, and the serial provisioning commands |
| `src/govee.*` | Continuous BLE scan and the Govee decoder table, ported from `client/hallclient.py` |
| `src/reporter.*` | Wi-Fi, the clock, the readings queue, and HTTPS uploads |
| `src/display.*` | The status screen |
| `src/certs.h` | The Let's Encrypt root certificates the kit trusts |

## Provisioning a kit

`provision.py` sets up a kit in one command. With the kit plugged in over USB-C and turned on:

```sh
uv run provision.py --course SEC504 --instructor "Josh Wright"
```

The script finds the kit on USB, flashes the firmware, creates the kit on the server with
`add-kit` over SSH, and sends the kit its ID, token, label, and every network in `networks.json`.
It then lists the Govee sensors the kit hears, strongest first, and asks which one to pair; pass
`--sensor Govee_H5074_C0A6` to skip the question. Last, it reboots the kit and prints the kit ID to
write on the kit and its sensor. The token goes from the server to the kit without being saved or
shown anywhere else.

After `networks.json` changes, `--update` resends the list to a kit that is already provisioned,
without flashing or touching the server. `--update` also accepts `--course`, `--instructor`, and
`--sensor` to change the label or the paired sensor. `--port` picks the serial port when more than
one is plugged in, and `--no-flash` skips flashing a kit that already runs the current firmware.

Provisioning a kit that already has settings creates a new kit on the server. Revoke the old kit
with the server's `revoke` command if nothing else uses it.

## Serial commands

A new kit has no settings. With the kit on USB, `pio device monitor` accepts one command per line,
and each command answers with one line of JSON:

| Command | Purpose |
|---|---|
| `show` | Print the settings, without the token or network passwords |
| `sensors` | List the Govee sensors heard in the past 15 minutes, strongest first |
| `config {json}` | Set any of `kit_id`, `server`, `token`, `course`, `instructor`, `sensor`, and `networks` |
| `reboot` | Restart the kit, which it needs to pick up new Wi-Fi networks |

`provision.py` uses these commands. To provision a kit by hand instead, create it on the server,
then paste one `config` line with the token
that `add-kit` printed, and reboot:

```
config {"kit_id": 1, "server": "https://hallmonitor.willhackforsushi.com", "token": "...", "course": "SEC504", "instructor": "Josh Wright", "sensor": "Govee_H5074_C0A6", "networks": [{"ssid": "SANS", "psk": "..."}]}
reboot
```

The SANS class networks (47 SSID and password pairs) live in `networks.json` in this directory.
The file is gitignored, since it holds Wi-Fi passwords, so it exists only on Josh's Mac. Because
`config` changes only the keys it is given, the whole list can go to a kit as its own line. This
prints that line for pasting into `pio device monitor`:

```sh
echo "config $(jq -c '{networks: .}' networks.json)"
```

The `networks` list replaces the networks that came from provisioning and keeps any network an
instructor added or edited in the setup portal. Once a kit is deployed, the instructor's changes
are the source of truth for that kit.

## Behavior notes

* **Clock.** Readings wait until the clock is valid. The kit sets its clock from NTP, or from the
  server's HTTP `Date` header when a venue blocks NTP, and copies it to the RTC so the time
  survives a power pull while the RTC battery lasts.
* **Queue.** Up to a week of readings wait in RAM while the kit is offline. A power pull loses
  readings that were not yet sent.
* **Certificates.** The kit trusts ISRG Root X1 and X2. If Let's Encrypt moves the server to a root
  outside those two, uploads fail until the kit is reflashed with new roots.
