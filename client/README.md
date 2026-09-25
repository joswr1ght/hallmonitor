# thermomon

> This is the original single-classroom client, copied unchanged from the thermomon project. Phase 1
> of [the plan](../docs/plan.md) adds an API publish mode so it reports to the hallmonitor server.

Reads a Govee Bluetooth thermometer/hygrometer from macOS and publishes the reading to
<https://www.hasborg.com/joshteachingroom> so SANS event staff can check classroom temperature and
humidity without interrupting class.

The sensor broadcasts its readings in BLE advertisements, so thermomon never pairs or connects. The
Govee Home app on the phone keeps working at the same time.

## Requirements

- macOS with Bluetooth, and `uv` (dependencies are declared inline in `thermomon.py`)
- The `hasborg` SSH alias in `~/.ssh/config` (already present: 107.170.28.205:2232)

### Bluetooth permission

The first run prompts for Bluetooth access. If it was previously denied, bleak raises
`BleakBluetoothNotAvailableError` and the permission has to be restored by hand in **System Settings
→ Privacy & Security → Bluetooth**, for whichever terminal application is running the script.

## Usage

Confirm the sensor is heard and decodes correctly:

```sh
uv run thermomon.py scan
```

This prints every nearby Govee device with its local name, raw manufacturer bytes, and decoded
values. Compare against the Govee app to confirm. If the device reports as an H5075 rather than an
H5074, pass `--name-match H5075` to `run`.

Render and publish one reading:

```sh
uv run thermomon.py run --once
```

Run the publish loop while teaching:

```sh
caffeinate -i uv run thermomon.py run
```

`caffeinate -i` keeps idle sleep from stopping the BLE scan. Closing the lid still suspends the Mac
and therefore the scan; the page shows a stale-reading banner after 12 minutes so staff can tell the
difference between "the room is fine" and "the monitor is asleep."

Useful flags on `run`:

| Flag | Default | Purpose |
|---|---|---|
| `--interval` | `300` | seconds between readings |
| `--scan-timeout` | `90` | seconds to wait past the interval for a fresh reading before giving up on a cycle; see the note on advertising interval below |
| `--name-match` | `H5074` | substring the device local name must contain |
| `--room-label` | `Josh's teaching room` | heading on the page |
| `--dest` | the hasborg docroot | rsync destination |
| `--no-publish` | off | render into `out/` without rsyncing |

Pin to one specific sensor when other Govee devices are in range — likely at a conference — by
passing the full local name, for example `--name-match Govee_H5074_C0A6`.

## How it works

```
BleakScanner.discover(20s)
  └─ decode manufacturer data under company ID 0xEC88
       └─ append state/history.json (pruned to 7 days)
            └─ render out/index.html + out/reading.json
                 └─ rsync -az -e ssh ──▶ hasborg:public_html/hasborg.com/joshteachingroom/
```

`state/history.json` on this Mac is the source of truth for the sparkline, so history survives a
restart without reading anything back from the server. The published page is static: no server-side
code, no external CSS, JS, fonts, or chart library.

`out/reading.json` carries the same reading in machine-readable form. A Slack bot could consume it
later without scraping HTML.

### Payload decoding

Both supported models put their readings in BLE manufacturer-specific data under company ID
`0xEC88` (on air the bytes are `88 EC`; bleak decodes company IDs little-endian).

- **H5074 / H5051** — `value[1:6]` unpacks as little-endian `<hHB`: signed hundredths of a degree
  Celsius, hundredths of a percent RH, battery percent.
- **H5075 / H5072** — `value[1:4]` is a 24-bit big-endian integer whose low three decimal digits are
  humidity in tenths of a percent and whose remaining digits are temperature in tenths of a degree
  Celsius. Bit 23 flags a negative temperature. Battery is `value[4]`.

### Advertising interval — why the scanner never stops

This sensor is heard far less often than its Bluetooth signal strength suggests. Measured over four
minutes with the unit a few metres from the Mac at −45 dBm, one scanner left running received:

```
t+ 16.7s   -46 dBm  00f5071e156402
t+109.4s   -53 dBm  00f00717156402
t+165.7s   -45 dBm  00ef070f156402
t+187.9s   -45 dBm  00f3070e156402
t+212.1s   -44 dBm  00eb070b156402
t+240.2s   -44 dBm  00ea0711156402
```

The gaps are irregular, from 17 seconds up to 93. An earlier version of the poller built a fresh
scanner each cycle and listened for a fixed 90-second window, which lost the race against that
93-second gap often enough to leave "no device heard" warnings in the log even with the sensor in
the same room.

The poller now keeps one scanner running for the whole life of the process and remembers the newest
reading it hears. Each cycle publishes whatever arrived since the last one, so the entire 300-second
interval counts as listening time and a miss needs the sensor to go silent for the interval plus
`--scan-timeout`. If a cycle still comes up empty the scanner is torn down and rebuilt before the
next one, in case the CoreBluetooth session itself stalled. If a venue puts the sensor farther away,
raise `--scan-timeout` before assuming the sensor is broken.

bleak's CoreBluetooth backend calls `scanForPeripheralsWithServices_options_(uuids, None)`, so
`CBCentralManagerScanOptionAllowDuplicatesKey` is never set and macOS coalesces repeated
advertisements. The measurement above shows that it still delivers each advertisement whose payload
changed, which is all a temperature monitor needs.

## Server setup

Done once, already complete:

```sh
ssh hasborg 'mkdir -p /home/jwright/public_html/hasborg.com/joshteachingroom'
ssh hasborg 'sudo certbot --apache -d hasborg.com -d www.hasborg.com --redirect \
    --non-interactive --agree-tos -m jwright@hasborg.com'
```

Note that `https://www.hasborg.com/` at the root still returns 403 — that docroot is empty and
thermomon does not change it.

## Before a conference

From the venue wifi, confirm the one network dependency works:

```sh
ssh hasborg true
```

Outbound TCP 2232 is all thermomon needs. If the venue blocks it, tether the Mac to an iPhone
hotspot for the publish step.
