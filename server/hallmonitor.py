#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["flask>=3.0", "waitress>=3.0"]
# ///
"""hallmonitor server: the kit API, SQLite storage, and the admin commands.

    uv run hallmonitor.py add-kit --course SEC504 --instructor "Josh Wright"   # prints the token once
    uv run hallmonitor.py set-kit 1 --instructor "Another Instructor"
    uv run hallmonitor.py set-staff-password                        # prompts for the shared password
    uv run hallmonitor.py list
    uv run hallmonitor.py revoke 1
    uv run hallmonitor.py serve --port 8504
"""

import argparse
import getpass
import hashlib
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, g, jsonify, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import pages

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "state" / "hallmonitor.db"

# A 6-day class at one reading every 5 minutes is 1,728 readings, so one batch can hold a full class.
MAX_BATCH = 2000
# Readings stamped further ahead than this come from a kit with a bad clock (see H7 in docs/plan.md).
MAX_FUTURE = timedelta(minutes=10)
# The staff login and the remembered room both outlast a 6-day class.
SESSION_DAYS = 30
ROOM_COOKIE = "room"
TZ_COOKIE = "tz"
# A kit appears in the room drop-down while it has reported within this window.
ACTIVE_HOURS = 24
# Longest course or instructor name a kit can report from its setup portal.
MAX_LABEL = 40
# Readings older than this are deleted, checked at most once a day when a kit uploads.
RETENTION_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS kits     (id INTEGER PRIMARY KEY, course TEXT NOT NULL, instructor TEXT NOT NULL,
                                     sensor TEXT, token_hash TEXT UNIQUE NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS readings (kit_id INTEGER NOT NULL REFERENCES kits, ts TEXT NOT NULL,
                                     celsius REAL NOT NULL, humidity REAL NOT NULL, battery INTEGER,
                                     rssi INTEGER, PRIMARY KEY (kit_id, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # The key that signs staff session cookies. Deleting it signs every staff member out.
        conn.execute("INSERT OR IGNORE INTO settings VALUES ('secret_key', ?)", (secrets.token_hex(32),))


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def hash_token(token: str) -> str:
    # Tokens are 256 bits of randomness, so a plain SHA-256 is enough; there is nothing to brute-force.
    return hashlib.sha256(token.encode()).hexdigest()


def utc_text(when: datetime) -> str:
    """Store timestamps as fixed-width UTC text so string order is time order."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_reading(item) -> tuple[str, float, float, int | None, int | None]:
    """Validate one uploaded reading, raising ValueError with a reason if it is unusable."""
    if not isinstance(item, dict):
        raise ValueError("reading is not an object")
    when = datetime.fromisoformat(str(item.get("ts", "")).replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("ts has no time zone")
    if when > datetime.now(timezone.utc) + MAX_FUTURE:
        raise ValueError("ts is in the future")
    celsius, humidity = float(item["celsius"]), float(item["humidity"])
    if not (-40 <= celsius <= 85 and 0 <= humidity <= 100):
        raise ValueError("celsius or humidity out of range")
    battery, rssi = item.get("battery"), item.get("rssi")
    return (utc_text(when), celsius, humidity,
            None if battery is None else int(battery), None if rssi is None else int(rssi))


def fingerprint(password_hash: str) -> str:
    """Tie a staff session to the current password hash, so changing the password signs everyone out."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def parse_labels(body: dict) -> dict[str, str]:
    """Return the course, instructor, and sensor a kit reported from its setup portal, if any.

    Values that are not short non-empty strings are ignored, so a bad label never costs a batch of
    readings.
    """
    kit = body.get("kit")
    if not isinstance(kit, dict):
        return {}
    return {key: kit[key].strip() for key in ("course", "instructor", "sensor")
            if isinstance(kit.get(key), str) and 0 < len(kit[key].strip()) <= MAX_LABEL}


def create_app(db_path: Path, secure_cookies: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
                      SESSION_COOKIE_SECURE=secure_cookies, SESSION_COOKIE_SAMESITE="Lax")
    with connect(db_path) as conn:
        app.secret_key = get_setting(conn, "secret_key")

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect(db_path)
        return g.db

    @app.teardown_appcontext
    def close_db(_exc) -> None:
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    last_prune = [None]  # when old readings were last deleted, shared across requests

    def prune_readings() -> None:
        now = datetime.now(timezone.utc)
        if last_prune[0] is not None and now - last_prune[0] < timedelta(days=1):
            return
        last_prune[0] = now
        with db() as conn:
            conn.execute("DELETE FROM readings WHERE ts < ?", (utc_text(now - timedelta(days=RETENTION_DAYS)),))

    def kit_id() -> int | None:
        """Return the kit ID for the request's bearer token, or None if it is missing or revoked."""
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        row = db().execute("SELECT id FROM kits WHERE token_hash = ? AND revoked_at IS NULL",
                           (hash_token(token.strip()),)).fetchone()
        return row["id"] if row else None

    @app.post("/api/v1/readings")
    def post_readings():
        kit = kit_id()
        if kit is None:
            return jsonify(error="invalid or revoked token"), 401
        body = request.get_json(silent=True)
        items = body.get("readings") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            return jsonify(error="expected {\"readings\": [...]}"), 400
        if len(items) > MAX_BATCH:
            return jsonify(error=f"batch larger than {MAX_BATCH}"), 413
        rows, rejected = [], []
        for index, item in enumerate(items):
            try:
                rows.append((kit, *parse_reading(item)))
            except (KeyError, TypeError, ValueError) as exc:
                rejected.append({"index": index, "error": str(exc)})
        labels = parse_labels(body)
        with db() as conn:
            for key, value in labels.items():
                # The key comes from the fixed tuple in parse_labels, never from the request.
                conn.execute(f"UPDATE kits SET {key} = ? WHERE id = ?", (value, kit))
            before = conn.total_changes
            conn.executemany("INSERT OR IGNORE INTO readings VALUES (?, ?, ?, ?, ?, ?)", rows)
            stored = conn.total_changes - before
        # Duplicates are a kit resending a batch after a lost response, so they count as success.
        prune_readings()
        return jsonify(stored=stored, duplicates=len(rows) - stored, rejected=rejected)

    # --- staff pages and read API ---

    def is_staff() -> bool:
        password_hash = get_setting(db(), "staff_password")
        return password_hash is not None and session.get("staff") == fingerprint(password_hash)

    def staff_page(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not is_staff():
                return redirect("/login?" + urlencode({"next": request.full_path.rstrip("?")}))
            return view(*args, **kwargs)
        return wrapper

    def staff_api(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not is_staff():
                return jsonify(error="sign in at /login first"), 401
            return view(*args, **kwargs)
        return wrapper

    def active_rooms() -> list[dict]:
        """Kits that reported within ACTIVE_HOURS, ordered for the drop-down."""
        cutoff = utc_text(datetime.now(timezone.utc) - timedelta(hours=ACTIVE_HOURS))
        return [dict(r) for r in db().execute(
            "SELECT k.id, k.course, k.instructor, max(r.ts) AS last FROM kits k JOIN readings r ON r.kit_id = k.id "
            "WHERE k.revoked_at IS NULL AND r.ts >= ? GROUP BY k.id ORDER BY k.course, k.instructor, k.id",
            (cutoff,))]

    def get_kit(room_id: int) -> dict | None:
        row = db().execute("SELECT id, course, instructor, sensor FROM kits WHERE id = ?", (room_id,)).fetchone()
        return dict(row) if row else None

    def room_readings(room_id: int, since: datetime) -> list:
        return db().execute("SELECT ts, celsius, humidity, battery, rssi FROM readings "
                            "WHERE kit_id = ? AND ts >= ? ORDER BY ts", (room_id, utc_text(since))).fetchall()

    def viewer_tz():
        """The viewer's time zone, which the page script stores in a cookie, or UTC until it has."""
        try:
            return ZoneInfo(unquote(request.cookies.get(TZ_COOKIE, "UTC")))
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc

    @app.get("/login")
    def login_form():
        return pages.login_page(None, request.args.get("next", "/"))

    @app.post("/login")
    def login():
        next_url = request.form.get("next", "/")
        # Only follow local paths, so the login form cannot bounce a staff member to another site.
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"
        password_hash = get_setting(db(), "staff_password")
        if password_hash is None:
            return pages.login_page("No staff password is set yet. Ask the administrator.", next_url), 403
        if not check_password_hash(password_hash, request.form.get("password", "")):
            return pages.login_page("That password is not correct.", next_url), 403
        session.permanent = True
        session["staff"] = fingerprint(password_hash)
        return redirect(next_url)

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    def home():
        return redirect("/rooms")

    @app.get("/rooms")
    @staff_page
    def rooms():
        chosen = request.args.get("id", type=int) or request.cookies.get(ROOM_COOKIE, type=int)
        # A remembered kit that has gone quiet still opens, so its stale-reading banner shows.
        if chosen is not None and get_kit(chosen) is not None:
            return redirect(f"/rooms/{chosen}")
        return pages.rooms_page(active_rooms())

    @app.get("/rooms/<int:room_id>")
    @staff_page
    def room(room_id: int):
        kit = get_kit(room_id)
        if kit is None:
            return redirect("/rooms")
        rooms = active_rooms()
        # A quiet kit stays viewable by direct link, and joins the drop-down so it can be left.
        if not any(r["id"] == room_id for r in rooms):
            rooms.append(kit)
        rows = room_readings(room_id, datetime.now(timezone.utc) - timedelta(hours=pages.HISTORY_HOURS))
        response = app.make_response(pages.room_page(kit, rooms, rows, viewer_tz()))
        response.set_cookie(ROOM_COOKIE, str(room_id), max_age=365 * 86400, secure=secure_cookies,
                            httponly=True, samesite="Lax")
        return response

    @app.get("/api/v1/rooms")
    @staff_api
    def api_rooms():
        return jsonify(rooms=active_rooms())

    @app.get("/api/v1/rooms/<int:room_id>/readings")
    @staff_api
    def api_room_readings(room_id: int):
        kit = get_kit(room_id)
        if kit is None:
            return jsonify(error="no such room"), 404
        since = datetime.now(timezone.utc) - timedelta(hours=pages.HISTORY_HOURS)
        if "since" in request.args:
            try:
                since = datetime.fromisoformat(request.args["since"].replace("Z", "+00:00"))
            except ValueError:
                return jsonify(error="since must be an ISO 8601 timestamp"), 400
            if since.tzinfo is None:
                return jsonify(error="since needs a time zone"), 400
        return jsonify(room=kit, readings=[dict(r) for r in room_readings(room_id, since)])

    return app


def cmd_add_kit(args) -> int:
    token = secrets.token_urlsafe(32)
    with connect(args.db) as conn:
        cur = conn.execute("INSERT INTO kits (course, instructor, sensor, token_hash) VALUES (?, ?, ?, ?)",
                           (args.course, args.instructor, args.sensor, hash_token(token)))
    print(f"kit {cur.lastrowid}: {args.course} / {args.instructor}")
    print(f"token (shown once, store it on the kit): {token}")
    return 0


def cmd_revoke(args) -> int:
    with connect(args.db) as conn:
        cur = conn.execute("UPDATE kits SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                           (utc_text(datetime.now(timezone.utc)), args.kit_id))
    if cur.rowcount == 0:
        print(f"kit {args.kit_id} not found or already revoked", file=sys.stderr)
        return 1
    print(f"kit {args.kit_id} revoked")
    return 0


def cmd_set_kit(args) -> int:
    changes = {k: v for k, v in (("course", args.course), ("instructor", args.instructor),
                                 ("sensor", args.sensor)) if v is not None}
    if not changes:
        print("nothing to change; pass --course, --instructor, or --sensor", file=sys.stderr)
        return 1
    with connect(args.db) as conn:
        cur = conn.execute(f"UPDATE kits SET {', '.join(k + ' = ?' for k in changes)} WHERE id = ?",
                           (*changes.values(), args.kit_id))
    if cur.rowcount == 0:
        print(f"kit {args.kit_id} not found", file=sys.stderr)
        return 1
    print(f"kit {args.kit_id} updated")
    return 0


def cmd_set_staff_password(args) -> int:
    if sys.stdin.isatty():
        password = getpass.getpass("New staff password: ")
        if password != getpass.getpass("Again: "):
            print("the passwords do not match", file=sys.stderr)
            return 1
    else:
        password = sys.stdin.readline().rstrip("\n")
    if len(password) < 8:
        print("use at least 8 characters", file=sys.stderr)
        return 1
    with connect(args.db) as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('staff_password', ?)",
                     (generate_password_hash(password),))
    print("staff password set; existing staff sessions are signed out")
    return 0


def cmd_list(args) -> int:
    with connect(args.db) as conn:
        kits = conn.execute("SELECT k.*, (SELECT max(ts) FROM readings r WHERE r.kit_id = k.id) AS last "
                            "FROM kits k ORDER BY k.id").fetchall()
    for k in kits:
        state = f"revoked {k['revoked_at']}" if k["revoked_at"] else "active"
        print(f"{k['id']:>3}  {k['course']:<8} {k['instructor']:<20} sensor={k['sensor'] or '-'}  {state}  "
              f"last={k['last'] or '-'}")
    return 0


def cmd_serve(args) -> int:
    from waitress import serve

    serve(create_app(args.db, secure_cookies=not args.insecure_cookies), host=args.host, port=args.port)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite database (default {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-kit", help="add a kit and print its token")
    p.add_argument("--course", required=True, help="course number, for example SEC504")
    p.add_argument("--instructor", required=True, help="instructor name")
    p.add_argument("--sensor", help="paired Govee sensor name or Bluetooth address")
    p.set_defaults(func=cmd_add_kit)

    p = sub.add_parser("set-kit", help="change a kit's course, instructor, or sensor")
    p.add_argument("kit_id", type=int)
    p.add_argument("--course")
    p.add_argument("--instructor")
    p.add_argument("--sensor")
    p.set_defaults(func=cmd_set_kit)

    p = sub.add_parser("revoke", help="revoke a kit's token")
    p.add_argument("kit_id", type=int)
    p.set_defaults(func=cmd_revoke)

    sub.add_parser("set-staff-password", help="set the shared staff password (prompts, or reads stdin)"
                   ).set_defaults(func=cmd_set_staff_password)

    sub.add_parser("list", help="list kits").set_defaults(func=cmd_list)

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8504)
    p.add_argument("--insecure-cookies", action="store_true",
                   help="allow cookies over plain HTTP, for local testing only")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    init_db(args.db)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
