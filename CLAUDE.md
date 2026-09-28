# hallmonitor

Centralized classroom environment monitoring for SANS event staff. Formerly thermomon, a single-Mac
monitor (still in `client/`). The plan, decisions, and open issues live in `docs/plan.md`; read it
before starting work and update it when a decision changes.

## Decisions so far

- Kit: M5StickS3 (the M5StickC Plus2 order arrived as a StickS3; the firmware builds for both)
  plus a Govee BLE sensor (H5074 today) and a USB power supply. No wired sensor.
- Josh preconfigures and pairs each kit. Instructors change Wi-Fi networks and the paired sensor
  through the on-device setup portal (F1): hold the main button, the screen shows a QR code, the
  `hallmon-<kit ID>` network, its password, and `http://192.168.4.1`.
- Venue Wi-Fi is WPA2 on 2.4 and 5 GHz, so a 2.4 GHz ESP32 is fine.
- Server: Python API behind the existing Apache on hasborg hosted at hallmonitor.willhackforsushi.com
    - SQLite in WAL mode, one opaque bearer
    - token per kit (stored hashed), command-line admin tool
    - Flask under waitress on 127.0.0.1, run by systemd, reached through Apache `mod_proxy`
- Readings are kept 90 days. No login rate limiting for now.
- Staff page: one shared staff password; everyone sees all rooms; last room viewed kept in a cookie.
- Kits are labeled by instructor only (no course, events, or deployments), set at provisioning and
  changeable from the setup portal. A kit works in any class with no setup; the portal is for
  recovery. Charts: 24-hour main, 72-hour and 7-day below, in the viewer's time zone.
- Setup portal network is WPA2 with a random per-session password on the LCD.
- Once deployed, an instructor's portal edits are the source of truth for their kit; server or
  provisioning lists never override instructor-edited networks.
- Firmware: Arduino framework with PlatformIO (`uv tool install platformio`), M5Unified,
  NimBLE-Arduino, ArduinoJson. Kits are provisioned over USB serial.
- Govee decoders are a per-model table so a replacement model is one new entry.

## Next step

Phase 1 in `docs/plan.md` is built, deployed, and verified. Phase 2 (prototype kit) is in progress
on an M5StickS3 (kit 1 since production was reset on 2026-09-28): it is provisioned and uploading
readings. The setup portal starts on the board, but its pages are not yet tested, and OTA is not
started. A battery run-down test and the week-on-battery goal are in H6 of `docs/plan.md`. User
documentation lives in `docs/user-guide.md`.

## Conventions

- Docs follow Josh Style.
