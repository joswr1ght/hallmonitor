# hallmonitor plan

Status, 2026-09-24: Phase 1 is built and deployed at `https://hallmonitor.willhackforsushi.com`. The
firmware for milestones 1 to 3 is written and compiles but has not run on hardware. Prices are rough estimates and should be checked before committing to a
bill of materials.

## Goal

Today the project (then named thermomon) is one Mac, one Govee H5074, and one static page rsynced to
hasborg over SSH. It records only while the Mac is open and awake, so lunch breaks and nights leave
gaps in the history.

The expanded system should let any instructor drop a small, inexpensive kit into a classroom on day
one and forget about it for the 5-6 day run of the class. Event staff should open one page, pick a
room from a drop-down, and see the current temperature, humidity, and trend for that room.

## Deliverables

The finished project has four parts:

1. **Kit firmware.** Firmware for the M5StickC Plus2 that reads the paired Govee sensor over
   Bluetooth Low Energy (BLE), uploads readings to the server, and shows temperature, humidity, and
   status information on the LCD (see "What the screen shows").
2. **API server.** The server that accepts readings from kits, stores them, and serves them to the
   web interface (see "Server and API"). Built and deployed.
3. **Web interface.** A staff login on the server, a drop-down of classrooms, and charts of each
   room's readings over 24-hour, 72-hour, and 7-day windows. Built and deployed.
4. **Setup portal.** A press-and-hold on the kit starts a Wi-Fi network for configuring the kit from
   a phone: choosing the Govee sensor from a list sorted by signal strength, adding Wi-Fi networks,
   and updating the saved entry for a network whose password changed (see F1).

## Requirements

The requirements below come from the initial discussion:

* **Price:** the per-instructor kit should cost as little as possible.
* **Unattended recording:** the kit should record every 5 minutes for the full class, including
  lunch and overnight, without a laptop.
* **Central API:** kits send readings to an API on a server Josh runs. Each instructor gets a
  credential Josh issues and can revoke. The server stores readings and renders the staff page.
* **Headless setup:** an instructor should be able to set up the kit, tie it to a classroom, and
  confirm it is reading the right sensor without a keyboard or monitor.
* **Venue Wi-Fi:** the kit should join the strongest network from a known list of SSID and
  pre-shared key (PSK) pairs, including WPA3 networks, with multiple class networks per venue.

The rest of this document proposes an architecture that meets these requirements, compares hardware
options, and lists the open questions that need answers before building.

## Proposed architecture

```
 classroom                                   hasborg (existing Apache + certbot)
 ┌─────────────────────────────┐             ┌─────────────────────────────────────┐
 │ sensor ──BLE adv──▶ kit     │   HTTPS     │ Apache ──▶ API app (Python)         │
 │                    │ buffer │ ──POST────▶ │              │                      │
 │                    │ (queue)│  bearer     │              ▼                      │
 │                    ▼        │  token      │           SQLite (WAL)              │
 │               small LCD     │             │              │                      │
 │  (status, SSID, last send)  │             │              ▼                      │
 └─────────────────────────────┘             │  /rooms  staff page + drop-down     │
                                             └─────────────────────────────────────┘
```

Two design choices carry most of the weight here.

First, the kit should be as dumb as possible. It reads the sensor, queues the reading locally, and
sends it when it can. All rendering, history, and room naming moves to the server. That keeps the
firmware small and means a page change never requires touching a kit in the field.

Second, the kit should store and forward. Venue Wi-Fi drops, and the kit should keep a few days of
readings locally (1,728 readings per 6-day class is a few tens of kilobytes) and upload them in a
batch on reconnect. With that in place, a Wi-Fi outage becomes a delayed chart instead of a gap.

## Hardware options

Three families of hardware fit the problem. Each is described below with an estimated kit cost
that includes the Govee sensor (about $15) where one is used.

**Option A: Raspberry Pi Zero 2 W**

This is the closest match to the current code. BlueZ on Linux is a supported bleak backend, so the
existing scanner and decoder in `client/hallclient.py` run with little change. NetworkManager
handles WPA2 and WPA3 profiles.

* Board about $15, microSD about $8, USB power supply about $8, case about $6. Kit total about $52.
* An add-on 240x240 LCD with a 5-way joystick and three buttons (for example the Waveshare 1.3"
  LCD HAT) adds about $15, for a kit total near $67.
* Boot takes 30-60 seconds.
* SD cards can corrupt when power is pulled without a shutdown, which is how instructors will turn
  it off on the last day. A read-only root filesystem with a small writable data partition reduces
  that risk but adds setup work to the image.
* The Wi-Fi radio is 2.4 GHz only.
* WPA3-SAE support on the Zero 2 W's Broadcom radio depends on the firmware and OS release and
  should be tested on real venue networks before committing.

**Option B: ESP32 board with a built-in screen and buttons**

Small ESP32 devices such as the M5StickC Plus2 (1.14" LCD, three buttons, about $20) or LilyGO
T-Display-S3 (1.9" LCD, two buttons, about $20) have BLE, Wi-Fi, and a display on one board.

* Kit total about $43 with a Govee sensor and USB power supply.
* Boots in about a second. No SD card, no filesystem to corrupt; a power pull is harmless.
* ESP-IDF and the Arduino core support WPA3-SAE, and the Arduino `WiFiMulti` class already
  implements "scan, then join the strongest network from this list."
* The code becomes firmware (Arduino C++ or MicroPython) instead of a Python script. The Govee
  decoder is about 30 lines and ports easily; the rest is new code.
* Firmware updates across a fleet need over-the-air (OTA) update support, or instructors return
  kits to Josh for reflashing.
* Most boards are 2.4 GHz only. The ESP32-C5 adds 5 GHz Wi-Fi, but boards with a screen are newer
  and less common.

**Option C: ESP32 with a wired sensor instead of a Govee**

The same ESP32 board, with a Sensirion SHT40 temperature and humidity sensor on a short cable (for
example the M5Stack ENV IV unit, about $8, which plugs into the M5StickC Grove port).

* Kit total about $36, or about $20 without a screen.
* The "is this the right Govee?" problem disappears, because there is no Bluetooth pairing at all.
* The sensor should sit on a cable 10-20 cm away from the board, since the ESP32 warms itself and
  would bias a sensor mounted on the board.
* The sensor has to be near a power outlet, unlike a battery-powered Govee that can sit anywhere
  in the room.
* Instructors who already own a Govee get no reuse from it.

Here is the comparison in one table:

| | A: Pi Zero 2 W | B: ESP32 + screen + Govee | C: ESP32 + wired sensor |
|---|---|---|---|
| Estimated kit cost | $52, $67 with LCD | $43 | $36 |
| Reuses current Python code | Mostly | Decoder logic only | No |
| Survives power pulls | With a read-only image | Yes | Yes |
| Boot time | 30-60 s | ~1 s | ~1 s |
| Sensor identity problem | Yes | Yes | No |
| Strongest-network roaming | Custom script | Built in (`WiFiMulti`) | Built in |
| Fleet updates | `apt`/`git pull` over SSH or a pull script | OTA firmware | OTA firmware |

**Recommendation**

Option B is the best fit for a kit that other instructors use. It is the cheapest option that keeps
the Govee sensor, it tolerates the "unplug it on Friday" shutdown, and the screen solves most of the
headless setup problem. Option A is faster to prototype because the current code runs on it, so it
is a reasonable way to validate the server before the firmware exists, but the Mac already serves
that purpose (see the phased plan below). Option C was set aside in favor of the Govee sensor (see
H5).

## Server and API

The expected load is small. At one reading every 5 minutes, 50 simultaneous classrooms produce
10 requests per minute and about 86,000 rows per week. SQLite in write-ahead logging (WAL) mode
handles that with no tuning. The API can run as a small Python app (for example Flask or FastAPI,
declared as `uv` inline dependencies) behind the Apache and certbot setup already on hasborg.

**Endpoints**

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/readings` | kit token | Batch upload of queued readings, plus the kit's course, instructor, and sensor when they change |
| `GET /api/v1/config` | kit token | Wi-Fi list for this kit (not built yet) |
| `GET /api/v1/rooms` | staff | Kits that reported in the past 24 hours, for the drop-down |
| `GET /api/v1/rooms/{id}/readings?since=` | staff | Readings for charts and a future Slack bot |
| `GET /rooms` and `/rooms/{id}` | staff | The rendered staff page |

A command-line admin tool on the server issues and revokes kit tokens and sets each kit's course
and instructor. That avoids building an admin web interface.

**Schema**

```sql
CREATE TABLE kits     (id INTEGER PRIMARY KEY, course TEXT NOT NULL, instructor TEXT NOT NULL,
                       sensor TEXT, token_hash TEXT UNIQUE NOT NULL, revoked_at TEXT);
CREATE TABLE readings (kit_id INTEGER NOT NULL REFERENCES kits, ts TEXT NOT NULL,
                       celsius REAL NOT NULL, humidity REAL NOT NULL, battery INTEGER,
                       rssi INTEGER, PRIMARY KEY (kit_id, ts)) WITHOUT ROWID;
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

A kit is labeled by course and instructor (for example "SEC504 · Josh Wright"), not by event or
room. An earlier design tied kits to per-event deployments with room names and dates, but that
would require setup for every event an instructor teaches. Instead, the staff drop-down lists every
kit that reported in the past 24 hours, and staff find a classroom by course and instructor, which
the event schedule already lists. The `(kit_id, ts)` primary key makes batch uploads idempotent, so
a kit that resends a batch after a lost response does not create duplicates. The `settings` table
holds the staff password hash and the key that signs session cookies.

Timestamps are stored in UTC and rendered in the viewer's time zone, which a small script on the
page reports to the server in a cookie. Staff read the page at the venue, so the viewer's time zone
is the classroom's time zone without any per-event setup.

**JWT or opaque token**

The request was for a JSON Web Token (JWT) per instructor. JWTs are useful when the server that
checks the token cannot look anything up, but this server owns the database anyway. An opaque random
token, stored as a hash in `devices.token_hash`, is simpler to issue, revocable by setting one
column, and carries no signing key to protect. A JWT is still workable, but revoking one requires
a database check on every request, which removes the reason to use a JWT.

The recommendation is one opaque token per kit rather than per instructor. An instructor with two
kits (or a kit that is lost) can then have one token revoked without affecting the other.

**Staff page access**

The readings themselves are not sensitive, but room names and event schedules might be. Options
range from fully public (as today, with `noindex`), to a shared staff passcode per event, to
per-person logins.

Decided (2026-09-24): one shared staff password for now, which can move to per-event passcodes or
per-person logins later. Instructors and event staff see all rooms. The last room viewed is kept in
a cookie, so an instructor who opens the page sees their own room without choosing it each time.

**Hosting on hasborg**

hasborg runs Ubuntu 24.04 and Apache 2.4 with the prefork module (for PHP), and no proxy or Web
Server Gateway Interface (WSGI) module is enabled today. The server is one `uv` script,
`server/hallmonitor.py`, that runs the Flask app under the waitress WSGI server on `127.0.0.1`. A
systemd service keeps it running, and Apache forwards requests to it with `mod_proxy` and
`mod_proxy_http`. Running the app in its own process, instead of inside Apache with `mod_wsgi`,
keeps it apart from the PHP sites that share the server and lets it restart without reloading
Apache.

Deployed 2026-09-24 at `https://hallmonitor.willhackforsushi.com`, with the upload endpoint only.
The service runs `uv run --offline`, so a reboot does not depend on reaching the Python Package
Index (PyPI). The deployment steps are in `server/README.md`.

## Setup without a keyboard or monitor

Setup splits into three problems: getting credentials onto the kit, tying the kit to a room, and
confirming the kit is reading the right sensor. The simplest approach moves as much as possible off
the device.

**Credentials and Wi-Fi list**

Josh flashes each kit with its device token and the current venue Wi-Fi list before handing it to
an instructor. The list is the 47 SANS class networks (one per course, such as `SEC504`), kept in
`firmware/networks.json`, which is gitignored because it holds the passwords. The kit then fetches an updated Wi-Fi list from `GET /api/v1/config` each time it is
online, so a new venue network added on the server reaches every kit on its next connection. The
baked-in list only has to get the kit online once.

For a new venue that no kit has seen, a fallback is needed. Two candidates are the instructor's
phone hotspot (a fixed SSID and PSK in every kit's list) or a captive-portal setup mode, where the
kit becomes its own access point and serves a page for entering an SSID and PSK. The hotspot
fallback is far less code.

**Course and instructor label**

Josh sets each kit's course and instructor name when provisioning it (`add-kit --course SEC504
--instructor "Josh Wright"`). When a kit changes hands, the new instructor updates the label in the
setup portal (F1), and the kit sends the new label with its next upload. Josh can also change it on
the server with `set-kit`. No per-event room assignment is needed.

**Sensor identity**

At a conference the kit may hear several Govee sensors through walls. The current script handles
this with `--name-match Govee_H5074_C0A6`, and the kit can do the same thing: bind the sensor to
the kit once, when the kit is assembled, by storing the sensor's Bluetooth address in the device
record. The sensor and kit then travel together as a pair.

The screen confirms the binding in the room. It should show the current reading and the sensor's
short name, so the instructor can compare against the sensor (the H5075 has its own LCD; the H5074
does not, so the Govee phone app serves that role). If a sensor is lost and replaced on site, the
instructor rebinds the kit through the setup portal (F1).

**What the screen shows**

The screen is mainly a status display, not a setup menu:

* Current temperature and humidity
* The course and instructor label
* Sensor short name and signal strength
* Connected SSID and Wi-Fi signal strength
* Time since the last successful upload, and the number of queued readings
* The device ID, so the instructor can tell Josh which kit has a problem

These lines answer nearly every "is it working?" question without a laptop.

## Wi-Fi selection

The kit holds a list of SSID and PSK pairs. On boot, and whenever the connection drops, it scans,
filters the scan results to known SSIDs, and joins the one with the strongest signal. Roaming
between access points on the same SSID is left to the Wi-Fi stack. Joining another class's network
is acceptable, since the kit only needs outbound HTTPS.

On an ESP32 this is `WiFiMulti`, which already works this way. On a Pi, NetworkManager chooses among
known networks by configured priority and recent use, not by signal strength, so a small script
calling `nmcli device wifi list` would need to pick the network and bring up that profile.

Josh confirmed (2026-09-24) that the SANS class networks use WPA2 and offer both 2.4 GHz and 5 GHz.
That removes two earlier risks: a 2.4 GHz-only ESP32 can see every class network, and WPA3 support
on the board no longer matters. Two venue risks remain to test:

* Networks that require a captive portal click-through. A headless kit cannot pass one.
* Outbound port restrictions. HTTPS on TCP 443 is far more likely to be open than SSH on TCP 2232,
  so moving to the API also removes the current network dependency.

A test at one venue with the prototype kit will show whether either risk is real.

## Issues to work out

Each issue has an ID, a status (open, leaning, or decided), and the current thinking. Hardware comes
first because the board choice constrains the firmware, setup, and Wi-Fi design.

### Hardware

**H1: Board (decided: M5StickC Plus2)**

The board needs to support the setup portal (F1) as well as normal reporting. That sets these
hardware requirements:

* An ESP32 with BLE and 2.4 GHz Wi-Fi that can run an access point and a station at the same time,
  so the portal can test new credentials before saving them. Every ESP32 variant below does this.
* A screen large enough to show a QR code and readable text together. A QR code for a Wi-Fi join
  string needs 25-29 modules per side; at 4 pixels per module that is about 100-116 pixels, so a
  screen at least 135 pixels wide fits the code with a line or two of text beside or below it.
* At least one button for the long press, and preferably two or three for status pages and sensor
  rebinding (H2).
* USB-C power, and enough flash for firmware with over-the-air (OTA) update support (4 MB minimum,
  8 MB comfortable).
* A connector for a wired sensor is useful for future expansion but not required, since the kit
  uses a Govee sensor (H5).

These boards meet some or all of the requirements. Prices were checked on 2026-09-24:

| Board | Chip | Screen | Buttons | Wired sensor port | Price | Notes |
|---|---|---|---|---|---|---|
| M5StickC Plus2 | ESP32-PICO-V3-02, 8 MB flash, 2 MB PSRAM | 1.14", 135x240 | 3 + power | Grove | $19.95 | Enclosed case, 200 mAh battery, RTC, buzzer |
| LilyGO T-Display-S3 | ESP32-S3, 16 MB flash, 8 MB PSRAM | 1.9", 170x320 | 2 + boot/reset | STEMMA QT | $15-23 | Larger screen; bare board, case sold separately |
| M5Stack AtomS3R | ESP32-S3, 8 MB flash, 8 MB PSRAM | 0.85", 128x128 | 1 | Grove | about $15-20 | Too small to show a QR code and text at once |

The M5StickC Plus2 fits best. Its 135-pixel width is enough for a QR code plus text, it arrives in
a case, and its RTC helps with H7. The T-Display-S3 is the fallback: a roomier screen and more
memory for about the same price, but it needs a 3D-printed or purchased case, and its two buttons
leave less room for status pages. The AtomS3R's screen is too small for the portal screen.

Boards with richer input (the M5Stack Cardputer with a keyboard, or the LilyGO T-Embed and M5Stack
Dial with rotary encoders) are no longer needed, since the phone handles text entry through the
portal.

**H2: On-device input (decided: three buttons, no D-pad)**

All setup choices, including Wi-Fi credentials and sensor selection, happen on a phone through the
setup portal (F1). A phone is a far better keyboard and list picker than any D-pad on a 1.14"
screen. That leaves the buttons with three jobs: a long press to start the portal, a short press to
cancel it, and a press to cycle through status screens.

**H3: Who sets up and pairs kits (decided: Josh preconfigures, portal allows changes)**

Josh flashes each kit, loads its device token and the current Wi-Fi list, binds it to one Govee
sensor by Bluetooth address, labels both with the kit ID, and hands the pair to the instructor. The
instructor only plugs it in, so a normal deployment has no pairing or token entry in the field.

When the sensor does need to change (a lost or dead sensor, or a newer model), the instructor
rebinds it through the setup portal (F1) instead of the buttons. The phone gives a readable list
of sensors with their live readings, which is far easier to choose from than a list paged through
on a 1.14" screen.

**H4: Wi-Fi credential maintenance (decided: setup portal, see F1)**

SANS sometimes changes network passwords or adds networks, so a kit's Wi-Fi list will go out of
date. Reflashing over USB works, but it requires the kit to come back to Josh or the instructor to
have a toolchain installed. Several lighter options exist, and they combine well:

1. Server-pushed list. The kit fetches the current Wi-Fi list from `GET /api/v1/config` whenever
   it is online. Josh edits the list once on the server and every kit picks it up. This covers
   changes announced before the kit reaches the venue, but not a kit that cannot get online at all.
2. Phone-hotspot fallback. Every kit's list includes one fixed SSID and PSK (per instructor, or one
   shared setup network). When no known network works, the instructor turns on a hotspot with that
   name, the kit connects, pulls the new list from the server, and moves to the venue network.
3. On-device setup portal. Holding a button puts the kit into access point mode, and the screen
   shows the network name (and optionally a QR code to join it). The instructor connects with a
   phone, and a small web page served by the kit accepts an SSID and PSK. Libraries such as
   WiFiManager for the Arduino core implement this pattern.
4. Browser-based USB setup. Tools such as ESP Web Tools and the Improv Wi-Fi protocol let a Chrome
   or Edge page flash firmware or send Wi-Fi credentials over USB, with no toolchain installed.
   This is the "set it up again over USB" path, reduced to opening a web page.

The decision is 3 (the setup portal) as a feature goal, specified as F1 below, with 1 as the normal
path when Josh knows about a change ahead of time, and 4 for reflashing. Option 2 is a small
addition if the portal proves awkward in practice.

**H5: Govee or wired sensor (decided: Govee over BLE)**

A wired SHT40 on the Grove port would cost less and remove pairing, but the Govee sensor wins on
two points. First, it is independent of the ESP32: it runs on its own battery, can sit anywhere in
the room within Bluetooth range, and does not pick up heat from the board. Second, it is
replaceable: if Govee discontinues the H5074, a newer model can take its place without changing
the kit hardware.

The replaceability point puts one requirement on the firmware. The decoder should be a table of
supported models (matched by the advertised name prefix), so adding a model means adding one
decoder entry and releasing an OTA update. Before adopting a new Govee model, a `hallclient.py scan`
should confirm it broadcasts its readings unencrypted in BLE advertisements, as the H5074 and H5075
do; a model that requires a connection or the Govee cloud would not work with this design.

The Grove port stays unused for now, and the wired sensor is out of scope.

**H6: Power and placement (open)**

The StickC's battery lasts hours, not days, so the kit needs USB power for the whole class. The
kit needs a USB power supply and a cable long enough to reach an outlet from wherever it sits, and
it should be somewhere it will not be unplugged for a laptop charger. The Govee should stay within
reliable Bluetooth range of the kit; the current measurements at a few meters are the only data
so far.

**H7: Timestamps before time sync (leaning: no readings without a valid clock)**

Readings queued before the kit's first network time sync need a trustworthy timestamp. The StickC
has an RTC, which keeps time while its battery holds charge. The firmware as written takes no
readings until the clock is valid. It sets the clock from NTP, or from the server's HTTP `Date`
header when a venue blocks NTP, restores it from the RTC at boot, and copies each sync back to the
RTC. A kit that boots with a flat RTC battery and no network records nothing until it gets online,
which the prototype should show is rare.

**H8: Bluetooth and Wi-Fi on one radio (open)**

The ESP32 shares one radio between BLE scanning and Wi-Fi. That usually works, but the H5074's
irregular advertising gaps (up to 93 seconds, measured in the README) leave little margin. The
prototype should log how many advertisements it hears per 5-minute cycle while Wi-Fi is active.

**H9: Enclosure and labeling (open)**

A label with the kit ID, the paired sensor's short name, and a QR code linking to the room page
helps both the instructor and event staff. The StickC's own case may be enough, with a
wall-mount or adhesive option if kits end up taped to walls.

With H1 to H5 decided, the kit is an M5StickC Plus2, a Govee sensor, and a USB power supply, and
the remaining hardware items (H6 to H9) are details the prototype will settle.

## Feature goals

### F1: On-device setup portal

An instructor at a venue with a new or changed Wi-Fi network should be able to fix the kit with a
phone in under two minutes, with no laptop and no call to Josh.

**Flow**

1. The instructor presses and holds the main button for 3 seconds. The kit beeps and stops
   uploading.
2. The kit starts its own Wi-Fi access point named `hallmon-<kit ID>`, protected by a random
   8-character password generated for this session.
3. The screen shows a QR code that joins the network, plus the network name, the password, and the
   setup URL (`http://192.168.4.1`) as text.
4. The instructor scans the QR code. Phones detect the kit's captive portal and open the setup page
   automatically; the URL on screen covers phones that do not.
5. The page lists the networks the kit can see, sorted by signal strength, with the known ones
   marked. The instructor picks one and enters the password.
6. The kit tries the new credentials while the portal stays up and reports success or failure on
   the page and on the screen.
7. On success, the kit saves the network, reports the change to the server on its next upload
   (so Josh can add it to the server-side list for other kits), and returns to normal operation.

The portal shuts itself off after 10 minutes without activity, and a short press of the main
button cancels it.

**Security**

Physical access to the kit is the authentication: the portal password appears only on the kit's
screen and changes each session. The page accepts new credentials but never displays saved
passwords or the device token. These choices keep someone in the next room from reconfiguring a
kit they cannot touch.

**Scope for the first version**

The portal has four pages:

* Wi-Fi: add a network, as described in the flow above; update the saved password for a network
  already in the list when the venue changes it; and remove a network.
* Sensor: choose which Govee sensor the kit reports, from a list sorted by signal strength (see
  below).
* Label: the course number and instructor name shown on the staff page.
* Status: kit ID, paired sensor, last upload, and queued readings.

**Keeping the Wi-Fi list current**

A kit's Wi-Fi list has two sources: the list Josh maintains on the server (H4, option 1) and the
changes an instructor makes in the portal. The two can disagree about the same network, for
example when an instructor updates a password in the portal before Josh updates the server. The
leaning is that each entry carries the time it last changed, the newer entry wins on the kit, and
the kit reports portal changes to the server with its next upload so Josh can fold them into the
server list for every kit.

Decided (2026-09-24): once a kit is deployed, the instructor's changes are the source of truth for
that kit. A network the instructor added or edited in the portal is marked on the kit, and a list
from provisioning or the server never overrides it. Networks the instructor has not touched still
follow the server list. The kit also reports its course, instructor, and sensor with every upload,
so the server's record follows the kit.

**Sensor selection**

During normal operation the kit already hears every Govee advertisement in range; it just ignores
the ones that do not match its bound sensor. The firmware should keep a small table of every Govee
device heard in the last 15 minutes (address, model, signal strength, and latest reading). The
sensor page then lists those devices immediately, without starting a new scan, which matters
because the H5074 can go 93 seconds between advertisements.

Each row shows the sensor's short name (for example `H5074_C0A6`), its signal strength, and its
current temperature and humidity, sorted strongest first. At a conference with sensors in
neighboring rooms, two cues identify the right one: placing the sensor next to the kit puts it at
the top of the list, and the live reading can be compared against the Govee app or the sensor's
own display. After the instructor selects a sensor, the kit's screen shows that sensor's name and
reading as confirmation, and the change is reported to the server with the next upload so the
device record stays current.

**Implementation notes**

Libraries such as WiFiManager for the Arduino core provide the captive portal, DNS redirect, and
network scan, and can be customized with additional pages. The ESP32 shares one radio between BLE
and Wi-Fi (H8), so the prototype should test whether BLE scanning can continue at a reduced duty
cycle while the portal runs, to keep the sensor list's readings fresh. If it cannot, the
15-minute table from normal operation is still enough to pick a sensor.

## Phased plan

Each phase produces something usable on its own.

**Phase 1: server API, Mac as the first client**

Build the API, the SQLite schema, the admin tool, and the staff page with the room drop-down. Add
an `--api` publish mode to the Mac client (now `client/hallclient.py`) that POSTs readings with a
kit token instead of rsyncing HTML. This validates the whole server side with no new hardware, and
Josh's class switches over immediately. The lunch and overnight gap remains, but the page and data
path are the new ones.

Done 2026-09-24, except moving Josh's class onto `--api` mode. Remaining steps:

1. Verify the Govee connection end to end. With the H5074 nearby, run
   `uv run hallclient.py scan` from `client/` and confirm `Govee_H5074_C0A6` appears with a decoded
   reading. Then run `uv run hallclient.py run --once --api https://hallmonitor.willhackforsushi.com
   --name-match Govee_H5074_C0A6` and confirm the reading appears on the SEC504 · Josh Wright page.
   The first attempt on 2026-09-24 heard no Govee devices because the sensor was not nearby.
2. Open the staff page on a phone and confirm times render in the local time zone.
3. Run the client with `--api` for a full class.

**Phase 2: prototype kit**

Buy one M5StickC Plus2 and pair it with the existing H5074. Write firmware that reads the Govee
over BLE, queues readings, joins the strongest known network, and uploads batches.
Run it alongside the Mac for one full class and compare the two data sets.

Decided (2026-09-24): the firmware uses the Arduino framework built with PlatformIO, with
M5Unified for the screen, buttons, and RTC, NimBLE-Arduino for BLE, and ArduinoJson. The work
splits into milestones that can each be tested on the board:

1. Screen and buttons.
2. BLE scan with the H5074 decoded on screen, compared against the Mac client.
3. Wi-Fi, clock, queue, and HTTPS uploads to the server.
4. `provision.py`, which runs `add-kit` on the server over SSH, flashes the firmware, and sends the
   kit its settings over USB serial. One firmware build then serves every kit.
5. The setup portal (F1).
6. Over-the-air (OTA) updates, before Phase 3.

Milestones 1 to 4 are written. The firmware compiles and `provision.py` passed a test against a
simulated kit on a pseudo-terminal, but both still need to run on the board.

**Phase 3: pilot with two or three instructors**

Assemble and flash kits for a few instructors, write a one-page setup card, and collect feedback on
setup friction, venue Wi-Fi failures, and what staff want from the page. Add OTA updates before this
phase, since fixes will be needed.

**Phase 4: broader rollout**

Kit assembly instructions, a bill of materials, and optional additions such as Slack alerts when a
room crosses a temperature threshold (the `reading.json` groundwork already anticipates a bot).

## Open questions

These need answers from Josh before or during Phase 1:

1. Who assembles and flashes kits: Josh, shipping them preconfigured, or instructors, from written
   instructions? Preconfigured kits make every other setup problem easier. (Answered: Josh
   preconfigures. See H3 under "Issues to work out.")
2. Is the target a Govee kit, a wired-sensor kit, or both? (Answered: Govee. See H5.)
3. Should the staff page be public, protected by a shared passcode per event, or something else?
   (Answered: one shared staff password for now. See "Staff page access.")
4. Do SANS venue networks ever require a captive portal? (Answered in part: class networks use WPA2
   on both 2.4 GHz and 5 GHz.)
5. Is a per-kit cost ceiling in mind (for example, under $40)?
6. How long should readings be kept after a class ends? (Answered: 90 days. The server deletes
   older readings once a day.)
7. Should instructors see only their own rooms, or all rooms at the event? (Answered: all rooms.)
8. Should the setup portal's Wi-Fi network be open or password protected? (Answered: WPA2 with a
   random password shown on the kit's screen, as in F1.)
9. Should the staff login be rate limited? (Answered: not for now.)

The answers to questions 1 and 2 decide most of the hardware and setup design, so they should be
settled first.
