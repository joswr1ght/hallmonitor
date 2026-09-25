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
- Govee decoders are a per-model table so a replacement model is one new entry.

## Next step

Phase 1 in `docs/plan.md`: build the server API, schema, admin tool, and staff page, then add an
`--api` publish mode to `client/thermomon.py`. The firmware toolchain (Arduino core or MicroPython)
is still open.

## Conventions

- `client/thermomon.py` keeps its name until the Phase 1 changes; rename it then.
- Docs follow Josh Style.
