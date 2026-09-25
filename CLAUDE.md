# hallmonitor

Centralized classroom environment monitoring for SANS event staff. Formerly thermomon, a single-Mac
monitor (still in `client/`). The plan, decisions, and open issues live in `docs/plan.md`; read it
before starting work and update it when a decision changes.

## Decisions so far

- Kit: M5StickC Plus2 plus a Govee BLE sensor (H5074 today) and a USB power supply. No wired sensor.
- Josh preconfigures and pairs each kit. Instructors change Wi-Fi networks and the paired sensor
  through the on-device setup portal (F1): hold the main button, the screen shows a QR code, the
  `hallmon-<kit ID>` network, its password, and `http://192.168.4.1`.
- Venue Wi-Fi is WPA2 on 2.4 and 5 GHz, so a 2.4 GHz ESP32 is fine.
- Server: Python API behind the existing Apache on hasborg hosted at hallmonitor.willhackforsushi.com
    - SQLite in WAL mode, one opaque bearer
    - token per kit (stored hashed), command-line admin tool
    - Flask under waitress on 127.0.0.1, run by systemd, reached through Apache `mod_proxy`
- Staff page: one shared staff password; everyone sees all rooms; last room viewed kept in a cookie.
- Kits are labeled by course and instructor (no events or deployments), set at provisioning and
  changeable from the setup portal. Charts: 24-hour main, 72-hour and 7-day below, in the viewer's
  time zone.
- Setup portal network is WPA2 with a random per-session password on the LCD.
- Once deployed, an instructor's portal edits are the source of truth for their kit; server or
  provisioning lists never override instructor-edited networks.
- Firmware: Arduino framework with PlatformIO (`uv tool install platformio`), M5Unified,
  NimBLE-Arduino, ArduinoJson. Kits are provisioned over USB serial.
- Govee decoders are a per-model table so a replacement model is one new entry.

## Next step

Phase 1 in `docs/plan.md` is built and deployed; what remains is running Josh's class on
`client/hallclient.py run --api`, starting with the Govee verification steps listed under Phase 1. Phase 2 (prototype kit) is in progress: firmware milestones 1 to 3 compile but have not run on
the M5StickC Plus2 yet; `provision.py`, the setup portal, and OTA are not started.

## Conventions

- Docs follow Josh Style.
