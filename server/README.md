# server

The hallmonitor server: an API that accepts readings from kits, stores them in SQLite, and renders
the staff page with a room drop-down. It also includes a command-line admin tool for issuing and
revoking kit tokens and labeling each kit with its course and instructor.

Working and deployed: the kit upload endpoint, the staff page, the read endpoints, and the admin
commands. See "Server and API" and Phase 1 in [../docs/plan.md](../docs/plan.md).

`hallmonitor.py` is a `uv` script holding the API and the admin commands, and `pages.py` beside it
renders the staff pages. The usage examples at the top of `hallmonitor.py` cover the admin
commands. The database defaults to `server/state/hallmonitor.db` and is created on first use.

Event staff and instructors sign in with one shared staff password, set with
`set-staff-password`. Changing the password signs everyone out. After signing in, staff pick a room
from the drop-down, and a cookie remembers the last room viewed. The drop-down lists kits that
reported in the past 24 hours, labeled by course and instructor; a quiet kit stays viewable by its
direct link. Times render in the viewer's time zone, which the page reports in a cookie.

A kit can change its own label by including it with an upload, which is how the setup portal will
report a new course or instructor:

```json
{"kit": {"course": "SEC504", "instructor": "Josh Wright"}, "readings": [...]}
```

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/readings` | kit token | Batch upload of readings |
| `GET /api/v1/config` | kit token | The Wi-Fi list kits merge into their own |
| `GET /rooms`, `GET /rooms/<id>` | staff | Room picker and room page |
| `GET /api/v1/rooms` | staff | Kits that reported in the past 24 hours, as JSON |
| `GET /api/v1/rooms/<id>/readings?since=` | staff | A kit's readings as JSON (default: the past 7 days) |

The server keeps readings for 90 days. Once a day, when a kit uploads, it deletes anything older.

For local testing over plain HTTP, add `--insecure-cookies` to `serve`; without it, browsers only
send the login cookie over HTTPS.

```
uv run hallmonitor.py serve --port 8504
```

A kit uploads readings with its token:

```
curl -X POST https://hallmonitor.willhackforsushi.com/api/v1/readings \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"readings": [{"ts": "2026-09-24T12:00:00Z", "celsius": 21.5, "humidity": 44.2,
                     "battery": 90, "rssi": -60}]}'
```

The response reports how many readings were stored, how many were duplicates of earlier uploads,
and which were rejected and why. Duplicates are expected when a kit resends a batch after a lost
response, and they count as success.

The Wi-Fi list that kits fetch is stored on the server with `set-networks`. After changing
`firmware/networks.json`, load it on the server so kits pick up the change:

```
ssh hasborg 'cd hallmonitor && ~/.local/bin/uv run --script hallmonitor.py set-networks' < ../firmware/networks.json
```

## Deployment on hasborg

The service runs as `jwright` from `/home/jwright/hallmonitor`, and the database lives in
`/home/jwright/hallmonitor/state/`. The files in `deploy/` are the systemd unit and the port 80
virtual host; certbot generated the matching `-le-ssl.conf` and the HTTPS redirect.

To deploy a new version, copy the script and restart the service:

```
rsync -a hallmonitor.py pages.py hasborg:hallmonitor/
ssh hasborg 'sudo systemctl restart hallmonitor'
```

The unit starts the script with `uv run --offline`, so it only uses packages already in the `uv`
cache. After adding or changing a dependency, run the script once online before restarting, for
example `ssh hasborg 'cd hallmonitor && ~/.local/bin/uv run --script hallmonitor.py list'`.

Run admin commands on the server the same way:

```
ssh hasborg 'cd hallmonitor && ~/.local/bin/uv run --script hallmonitor.py list'
```

A cron job for `jwright` backs up the database every night at 3:17 AM (server time, US Eastern)
with SQLite's online backup, which is safe while the server runs. It keeps the newest 7 copies in
`state/backups/` and logs to `state/backups/backup.log`. The copies are on the same disk as the
database, so they protect against corruption and mistakes but not against losing the server.
