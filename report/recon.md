# Reconnaissance

## Stack

* Server: Python 3.11+ `uv` script (`server/hallmonitor.py`), Flask 3 under waitress, SQLite in
  Write-Ahead Logging (WAL) mode through the standard `sqlite3` module with parameterized queries.
  HTML is built with f-strings in `server/pages.py` and escaped with `html.escape`.
* Deployment: waitress on 127.0.0.1:8504, run by systemd as `jwright`, behind Apache `mod_proxy`
  (`server/deploy/`). Certbot's HTTPS virtual host is not in the repository.
* Kit firmware: ESP32 Arduino (PlatformIO), M5Unified, NimBLE-Arduino, ArduinoJson. The kit runs a
  setup portal (`firmware/src/portal.cpp`) on a WPA2 soft access point with a per-session random
  password shown on the LCD.
* Admin tooling: `firmware/provision.py` (USB serial and SSH), `client/hallclient.py` (legacy Mac
  client with an API upload mode).

## Entry points

| Method and path | Auth | Handler |
|---|---|---|
| `POST /api/v1/readings` | kit bearer token | `post_readings` (`server/hallmonitor.py:169`) |
| `GET /api/v1/config` | kit bearer token | `get_config` (`server/hallmonitor.py:198`) |
| `GET /login`, `POST /login` | none | `login_form`, `login` (`server/hallmonitor.py:250`) |
| `GET /logout` | none | `logout` |
| `GET /rooms`, `GET /rooms/<id>` | staff session | `rooms`, `room` |
| `GET /api/v1/rooms`, `GET /api/v1/rooms/<id>/readings` | staff session | `api_rooms`, `api_room_readings` |
| Kit portal `GET /`, `POST /wifi`, `/wifi/remove`, `/sensor`, `/label`, `/scan`, `/done` | WPA2 PSK on the LCD | `firmware/src/portal.cpp` |

## Auth model

* Kits: 256-bit bearer token from `secrets.token_urlsafe(32)`, stored as SHA-256, checked on each
  request; revocation sets `revoked_at`.
* Staff: one shared password (Werkzeug `generate_password_hash`, scrypt). A correct password sets a
  Flask signed-cookie session holding a 16-hex-character fingerprint of the password hash. The
  signing key is 32 random bytes stored in the `settings` table. Sessions are permanent for 30
  days. All staff see all rooms, so there is no tenant boundary.
* Portal: physical access to the kit's screen is the authentication (docs/plan.md, "Security").

## Untrusted input

* Kit uploads: readings (validated in `parse_reading`) and labels (`parse_labels`, strings of 1 to
  40 characters), rendered escaped on the staff pages.
* Staff pages: `next` (login), `id` (room), `since` (readings API), `room` and `tz` cookies.
* Portal: form fields, Wi-Fi scan SSIDs, and Bluetooth Low Energy (BLE) advertisement names, all
  passed through the portal's `html()` escaper.

## External integrations

No outbound HTTP from the server. Kits reach the server over HTTPS pinned to the ISRG roots
(`firmware/src/certs.h`), plus a plain HTTP request for the `Date` header when NTP fails.

## Configuration and secrets

`.gitignore` excludes `state/` (database) and `firmware/networks.json` (venue Wi-Fi passwords). No
secrets are committed. The session signing key and password hash live in the SQLite database.

## Live target

* Production: `https://hallmonitor.willhackforsushi.com` (docs/plan.md, CLAUDE.md). No requests
  were sent to production during this audit.
* Validation target: a local copy of the current server code, started as below. Every validation
  script reads `BASE` (default `http://127.0.0.1:18504`) and `STAFF_PASSWORD` (default
  `testpass123`).

```bash
cd server
echo 'testpass123' | uv run --script hallmonitor.py --db /tmp/hm/t.db set-staff-password
uv run --script hallmonitor.py --db /tmp/hm/t.db add-kit --course SEC504 --instructor Tester
uv run --script hallmonitor.py --db /tmp/hm/t.db serve --port 18504 --insecure-cookies
```

## Candidates falsified

* Stored XSS through kit labels: a label of `<img src=x onerror=alert(1)>` renders as `&lt;img`
  on `/rooms/1`; `pages.py` escapes every label and the SVG labels are server-generated.
* SQL injection: every query is parameterized; the two f-string `UPDATE` statements take column
  names from fixed tuples (`server/hallmonitor.py:188`, `:372`).
* `tz` cookie path traversal: `ZoneInfo` rejects non-normalized keys, and `America` or
  `../../etc/passwd` fall back to UTC (HTTP 200).
* Kit token guessing and timing: 256-bit tokens compared by SHA-256 lookup.
* Portal XSS through SSIDs, sensor names, and notices: all pass through `html()`.
* Provisioning command injection: `provision.py` builds the SSH command with `shlex.join`.
* Kit clock spoofing through the plain HTTP `Date` fallback: an attacker on the venue network can
  set the kit's clock, but the kit's NTP traffic is equally unauthenticated, so the fallback adds
  no new capability.
