#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["bleak>=3.0"]
# ///
"""Read a Govee BLE thermometer/hygrometer on macOS and publish the reading to a static web page.

The Govee H5074 and H5075 broadcast temperature and humidity in BLE advertisements, so no pairing or
GATT connection is needed and the Govee phone app can keep running at the same time.

    uv run hallclient.py scan          # one discovery cycle, print everything Govee found
    uv run hallclient.py run --once    # one scan, render the page, rsync it
    uv run hallclient.py run           # the 5-minute publish loop
    uv run hallclient.py run --api https://hallmonitor.willhackforsushi.com   # upload to the server

With --api, readings go to the hallmonitor server instead of rsync. The kit token (from the server's
add-kit command) is read from state/api-token, and readings that fail to upload wait in
state/queue.json until the next upload succeeds.
"""

import argparse
import asyncio
import json
import logging
import math
import os
import struct
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bleak import BleakScanner

# Govee squats this value in the manufacturer-specific data company ID field. On air the bytes are
# 88 EC; bleak decodes the company ID little-endian, so it surfaces as 0xEC88 (60552).
GOVEE_MFR_ID = 0xEC88

# The page shows a 4-hour main chart plus 24-hour and 7-day views, so keep a week of samples.
MAIN_HOURS = 4
LONG_VIEWS = (24, 24 * 7)
HISTORY_HOURS = LONG_VIEWS[-1]
STALE_MINUTES = 12
DEFAULT_INTERVAL = 300
# Measured on a Govee_H5074 at -45 dBm: macOS hands a persistent scanner this sensor's advertisements
# at irregular gaps, up to 93s apart. The poll loop therefore keeps one scanner running across the
# whole interval and only waits this long past it for a fresh reading before giving up on a cycle.
DEFAULT_SCAN_TIMEOUT = 90.0
DEFAULT_NAME_MATCH = "H5074"
DEFAULT_ROOM_LABEL = "Josh's teaching room"
DEFAULT_DEST = "hasborg:/home/jwright/public_html/hasborg.com/joshteachingroom/"

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"
OUT_DIR = HERE / "out"
HISTORY_PATH = STATE_DIR / "history.json"
TOKEN_PATH = STATE_DIR / "api-token"
QUEUE_PATH = STATE_DIR / "queue.json"
# The server accepts at most this many readings per request.
MAX_BATCH = 2000

log = logging.getLogger("hallclient")


@dataclass
class Reading:
    """One decoded sensor sample."""

    name: str
    celsius: float
    humidity: float
    battery: int
    rssi: int | None = None
    taken: datetime | None = None

    @property
    def fahrenheit(self) -> float:
        return self.celsius * 9.0 / 5.0 + 32.0

    def __str__(self) -> str:
        rssi = f", {self.rssi} dBm" if self.rssi is not None else ""
        return (f"{self.name}: {self.fahrenheit:.1f}F / {self.celsius:.2f}C, "
                f"{self.humidity:.1f}% RH, battery {self.battery}%{rssi}")


def decode(local_name: str, value: bytes) -> tuple[float, float, int] | None:
    """Decode Govee manufacturer data into (celsius, humidity, battery), or None if unrecognized.

    Two payload families share company ID 0xEC88, so the local name selects the decoder rather than
    guessing from the payload length.
    """
    name = local_name or ""

    # H5074 / H5051: signed hundredths of a degree C, hundredths of a percent RH, battery percent.
    if "H5074" in name or "H5051" in name:
        if len(value) < 6:
            return None
        celsius, humidity, battery = struct.unpack("<hHB", value[1:6])
        return celsius / 100.0, humidity / 100.0, battery

    # H5075 / H5072: temperature and humidity packed into one 24-bit big-endian integer, where the
    # low three decimal digits are humidity in tenths of a percent and the rest is temperature in
    # tenths of a degree C. Bit 23 flags a negative temperature.
    if "H5075" in name or "H5072" in name:
        if len(value) < 5:
            return None
        packed = int.from_bytes(value[1:4], "big")
        negative = bool(packed & 0x800000)
        packed &= 0x7FFFFF
        celsius = (packed // 1000) / 10.0
        return (-celsius if negative else celsius), (packed % 1000) / 10.0, value[4]

    return None


async def collect(timeout: float) -> list[tuple[str, bytes, int | None]]:
    """Run one discovery cycle and return (local_name, manufacturer_value, rssi) for Govee devices."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    devices = []
    for device, adv in found.values():
        value = adv.manufacturer_data.get(GOVEE_MFR_ID)
        if value is None:
            continue
        name = adv.local_name or device.name or ""
        devices.append((name, bytes(value), adv.rssi))
    return devices


class Listener:
    """One long-lived scanner that remembers the newest decoded reading from each matching device.

    bleak's CoreBluetooth backend never sets CBCentralManagerScanOptionAllowDuplicatesKey, so macOS
    coalesces repeats, but it still delivers each advertisement whose payload changed. Measured on a
    Govee_H5074 those arrive at gaps of up to 93s, which is why a scanner that only listens for a
    fixed window each cycle comes up empty now and then. Leaving the scanner running between cycles
    turns the whole interval into listening time.
    """

    def __init__(self, name_match: str) -> None:
        self.name_match = name_match
        self.latest: dict[str, Reading] = {}
        self._undecodable: set[str] = set()
        self._fresh = asyncio.Event()
        self._scanner: BleakScanner | None = None

    async def __aenter__(self) -> "Listener":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        self._scanner = BleakScanner(detection_callback=self._heard)
        await self._scanner.start()

    async def stop(self) -> None:
        if self._scanner is not None:
            await self._scanner.stop()
            self._scanner = None

    def _heard(self, device, adv) -> None:
        value = adv.manufacturer_data.get(GOVEE_MFR_ID)
        if value is None:
            return
        name = adv.local_name or device.name or ""
        if self.name_match and self.name_match not in name:
            return
        decoded = decode(name, bytes(value))
        if decoded is None:
            if name not in self._undecodable:
                self._undecodable.add(name)
                log.warning("device %r matched %r but its payload did not decode: %s",
                            name, self.name_match, bytes(value).hex())
            return
        celsius, humidity, battery = decoded
        self.latest[name] = Reading(name, celsius, humidity, battery, adv.rssi,
                                    datetime.now(timezone.utc))
        self._fresh.set()

    def newest(self) -> Reading | None:
        if not self.latest:
            return None
        if len(self.latest) > 1:
            log.warning("%d devices match %r (%s); using the most recently heard. Narrow it with "
                        "--name-match.", len(self.latest), self.name_match,
                        ", ".join(sorted(self.latest)))
        return max(self.latest.values(), key=lambda r: r.taken)

    async def wait_fresh(self, after: datetime | None, timeout: float) -> Reading | None:
        """Return the newest reading taken after `after`, waiting up to `timeout` seconds for one."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            reading = self.newest()
            if reading is not None and (after is None or reading.taken > after):
                return reading
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            self._fresh.clear()
            try:
                await asyncio.wait_for(self._fresh.wait(), remaining)
            except asyncio.TimeoutError:
                return None


# --- history ---------------------------------------------------------------------------------------

def load_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("could not read %s (%s); starting fresh", path, exc)
        return []
    return data if isinstance(data, list) else []


def prune(history: list[dict], now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=HISTORY_HOURS)
    kept = []
    for point in history:
        try:
            if datetime.fromisoformat(point["ts"]) >= cutoff:
                kept.append(point)
        except (KeyError, TypeError, ValueError):
            continue
    return kept


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file plus rename so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


# --- rendering -------------------------------------------------------------------------------------

# Colors are the dataviz reference palette: chart surface, ink, and categorical slot 1 for the single
# temperature series, with both light and dark steps chosen for their own surface.
PAGE_CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --series: #2a78d6;
  --warning: #fab219;
  --ring: rgba(11, 11, 11, 0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --series: #3987e5;
    --ring: rgba(255, 255, 255, 0.10);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 16px 40px;
  background: var(--page);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.45;
  -webkit-text-size-adjust: 100%;
}
main {
  max-width: 620px;
  margin: 0 auto;
  background: var(--surface);
  border: 1px solid var(--ring);
  border-radius: 14px;
  padding: 24px 22px 20px;
}
h1 {
  margin: 0 0 18px;
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--ink-2);
}
.hero {
  font-size: clamp(3.5rem, 17vw, 5rem);
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.02em;
  margin: 0;
}
.hero .unit { font-size: 0.36em; font-weight: 500; color: var(--ink-2); margin-left: 0.08em; }
.celsius { margin: 6px 0 0; color: var(--ink-2); font-size: 1rem; }
.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 26px;
  margin: 22px 0 0;
  padding: 18px 0 0;
  border-top: 1px solid var(--grid);
}
.stat .label {
  display: block;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}
.stat .value { display: block; font-size: 1.6rem; font-weight: 600; margin-top: 2px; }
figure { margin: 24px 0 0; }
.long-views {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-top: 18px;
}
.long-views figure { margin: 0; }
.long-views figcaption { font-size: 0.75rem; }
figcaption { font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; }
svg { display: block; width: 100%; height: auto; }
.age { margin: 18px 0 0; font-size: 0.85rem; color: var(--muted); }
.stale {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin: 0 0 18px;
  padding: 11px 13px;
  border-radius: 9px;
  border: 1px solid var(--warning);
  border-left: 4px solid var(--warning);
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  font-size: 0.88rem;
  color: var(--ink);
}
.stale[hidden] { display: none; }
.stale .icon { flex: none; font-size: 1rem; line-height: 1.3; }
footer { max-width: 620px; margin: 14px auto 0; font-size: 0.75rem; color: var(--muted); }
footer a { color: inherit; }
"""

PAGE_JS = """
(function () {
  var iso = document.body.dataset.reading;
  var limit = parseInt(document.body.dataset.staleMinutes, 10);
  var age = document.getElementById("age");
  var banner = document.getElementById("stale");
  var detail = document.getElementById("stale-detail");
  if (!iso || !age) { return; }
  function phrase(mins) {
    if (mins < 1) { return "just now"; }
    if (mins < 2) { return "1 minute ago"; }
    if (mins < 90) { return Math.round(mins) + " minutes ago"; }
    var hours = mins / 60;
    return (hours < 10 ? hours.toFixed(1) : Math.round(hours)) + " hours ago";
  }
  function tick() {
    var mins = (Date.now() - new Date(iso).getTime()) / 60000;
    if (!isFinite(mins)) { return; }
    age.textContent = "Updated " + phrase(mins);
    if (banner) {
      var stale = mins > limit;
      banner.hidden = !stale;
      if (stale && detail) {
        detail.textContent = "This reading is from " + phrase(mins) +
          ". The classroom monitor may be asleep or out of Bluetooth range, so the numbers above " +
          "are not current.";
      }
    }
  }
  tick();
  setInterval(tick, 15000);
})();
"""


def hour_label(when: datetime) -> str:
    """Format a local time as a compact hour label: 8a, 12p, 3p."""
    hour = when.hour % 12 or 12
    return f"{hour}{'a' if when.hour < 12 else 'p'}"


# strftime's "%-I" zero-padding suppression is a GNU extension, so build clock strings by hand.
def clock(when: datetime) -> str:
    """Format a local time as 3:04 PM EDT."""
    hour = when.hour % 12 or 12
    zone = when.strftime("%Z")
    return f"{hour}:{when.minute:02d} {'AM' if when.hour < 12 else 'PM'}{' ' + zone if zone else ''}"


def datestamp(when: datetime) -> str:
    """Format a local time as Saturday Jul 25, 3:04 PM EDT."""
    return f"{when.strftime('%A %b')} {when.day}, {clock(when)}"


def day_label(when: datetime) -> str:
    """Format a local time as a short weekday name: Mon, Tue."""
    return when.strftime("%a")


Point = tuple[datetime, float]


def window_points(history: list[dict], hours: float, now: datetime) -> list[Point]:
    """Return (timestamp, fahrenheit) pairs from the past `hours`, oldest first, skipping bad rows."""
    cutoff = now - timedelta(hours=hours)
    points = []
    for entry in history:
        try:
            when = datetime.fromisoformat(entry["ts"])
            if when >= cutoff:
                points.append((when, float(entry["c"]) * 9.0 / 5.0 + 32.0))
        except (KeyError, TypeError, ValueError):
            continue
    points.sort(key=lambda p: p[0])
    return points


def span_hours(points: list[Point]) -> float:
    """Hours between the first and last point, or 0 when there are fewer than two."""
    if len(points) < 2:
        return 0.0
    return (points[-1][0] - points[0][0]).total_seconds() / 3600.0


def span_text(points: list[Point]) -> str:
    """Describe the period a chart actually covers: "past 40 minutes", "past 4 hours", "past 7 days".

    Claiming "past 4 hours" while only a few minutes of history exists overstates the chart, and on
    a short span no whole-hour tick falls inside the window, so the caption carries the time scale
    on its own. Empty when there is no span to speak of.
    """
    hours = span_hours(points)
    minutes = hours * 60.0
    if minutes < 1:
        return ""
    if minutes < 90:
        return f"past {round(minutes)} minutes"
    if hours < 48:
        return f"past {round(hours)} hours"
    days = hours / 24.0
    shown = f"{round(days)}" if abs(days - round(days)) < 0.15 else f"{days:.1f}"
    return f"past {shown} days"


def span_label(points: list[Point]) -> str:
    """Caption for the main chart: "Temperature, past 4 hours"."""
    text = span_text(points)
    return f"Temperature, {text}" if text else "Temperature history"


def sparkline_svg(points: list[Point], label: str, width: int = 400, height: int = 140,
                  marker: int = 4) -> str:
    """Inline SVG line chart of temperature points in degrees F.

    Single series, so no legend: the figcaption names what is plotted. 2px round-capped line, an
    end-marker with a 2px surface ring, hairline gridlines, and explicit min/max tick labels so the
    y-range is never implied.

    The viewBox is sized close to the rendered CSS width so label text does not shrink on a phone,
    and every stroke carries vector-effect="non-scaling-stroke" so the 2px line and 1px hairlines
    keep their specified weight whatever width the card ends up.

    Time ticks fall on whole local hours for spans up to two days and on local midnights beyond
    that, labeled with the weekday, so a week view is not papered with meaningless hour marks.
    """
    left, right, top, bottom = 34, 10, 12, 24
    plot_w = width - left - right
    plot_h = height - top - bottom
    stroke = 'vector-effect="non-scaling-stroke"'

    if not points:
        return (f'<svg viewBox="0 0 {width} 52" role="img" aria-label="No history yet">'
                '<text x="0" y="30" fill="var(--muted)" font-size="13" '
                'font-family="system-ui, sans-serif">Collecting history&#8230;</text></svg>')

    temps = [value for _, value in points]
    low, high = min(temps), max(temps)
    # Keep at least a 2F window so ordinary sensor jitter does not render as dramatic swings.
    if high - low < 2.0:
        middle = (high + low) / 2.0
        low, high = middle - 1.0, middle + 1.0
    span = high - low

    t_start, t_end = points[0][0], points[-1][0]
    seconds = (t_end - t_start).total_seconds()

    def x_of(when: datetime) -> float:
        if seconds <= 0:
            # A single reading has no span to lay out; center it rather than pin it to the edge,
            # where a lone dot reads as a rendering fault.
            return left + plot_w / 2.0
        return left + plot_w * ((when - t_start).total_seconds() / seconds)

    def y_of(value: float) -> float:
        return top + plot_h * (1.0 - (value - low) / span)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="{label}, {low:.0f} to {high:.0f} degrees Fahrenheit">']

    # Horizontal hairlines at the range bounds, with the values labeled in muted ink.
    for value in (high, low):
        y = y_of(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1" {stroke} />')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" fill="var(--muted)" '
                     f'font-size="12" font-family="system-ui, sans-serif" '
                     f'style="font-variant-numeric: tabular-nums">{value:.0f}&#176;</text>')

    # Vertical hairline plus label on each whole local hour (or each local midnight on a long span)
    # inside the window, thinned out so labels never collide on a narrow phone screen.
    local_start, local_end = t_start.astimezone(), t_end.astimezone()
    by_day = seconds > 48 * 3600
    unit = timedelta(days=1) if by_day else timedelta(hours=1)
    fmt = day_label if by_day else hour_label
    tick = local_start.replace(minute=0, second=0, microsecond=0)
    if by_day:
        tick = tick.replace(hour=0)
    tick += unit
    marks = []
    while tick <= local_end:
        marks.append(tick)
        tick += unit
    # Thin the labels out so each keeps roughly its own width of clear space on a narrow screen.
    step = max(1, math.ceil(len(marks) * 34 / plot_w))
    for mark in marks[::step]:
        x = x_of(mark)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" '
                     f'stroke="var(--grid)" stroke-width="1" {stroke} />')
        parts.append(f'<text x="{x:.1f}" y="{height - 7}" text-anchor="middle" fill="var(--muted)" '
                     f'font-size="12" font-family="system-ui, sans-serif">'
                     f'{fmt(mark)}</text>')

    parts.append(f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" '
                 f'stroke="var(--axis)" stroke-width="1" {stroke} />')

    if len(points) == 1:
        cx, cy = x_of(points[0][0]), y_of(points[0][1])
    else:
        # Readings closer together than the stale threshold are one run in the series color; a
        # bridge across a longer gap is drawn in gray so a stretch of missed readings is not mistaken
        # for a measured straight line.
        gap = timedelta(minutes=STALE_MINUTES)
        runs, run = [], [points[0]]
        for prev, cur in zip(points, points[1:]):
            if cur[0] - prev[0] > gap:
                runs.append(run)
                run = []
            run.append(cur)
        runs.append(run)
        for a, b in zip(runs, runs[1:]):
            coords = f"{x_of(a[-1][0]):.1f},{y_of(a[-1][1]):.1f} {x_of(b[0][0]):.1f},{y_of(b[0][1]):.1f}"
            parts.append(f'<polyline points="{coords}" fill="none" stroke="var(--muted)" '
                         f'stroke-width="2" stroke-linecap="round" {stroke} />')
        for run in runs:
            if len(run) < 2:
                continue
            coords = " ".join(f"{x_of(when):.1f},{y_of(value):.1f}" for when, value in run)
            parts.append(f'<polyline points="{coords}" fill="none" stroke="var(--series)" '
                         f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" {stroke} />')
        cx, cy = x_of(points[-1][0]), y_of(points[-1][1])

    parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{marker}" fill="var(--series)" '
                 f'stroke="var(--surface)" stroke-width="2" {stroke} />')
    parts.append("</svg>")
    return "".join(parts)


def long_views_html(history: list[dict], now: datetime) -> str:
    """Smaller charts for the longer windows, side by side under the main chart.

    A longer view only appears once the history outgrows the window before it; until then it would
    just repeat the main chart at a smaller size.
    """
    figures = []
    previous_hours = MAIN_HOURS
    for hours in LONG_VIEWS:
        points = window_points(history, hours, now)
        if span_hours(points) > previous_hours:
            caption = span_text(points).capitalize()
            figures.append(f'<figure><figcaption>{caption}</figcaption>'
                           f'{sparkline_svg(points, span_label(points), 280, 100, 3)}</figure>')
        previous_hours = hours
    if not figures:
        return ""
    return '<div class="long-views">' + "".join(figures) + "</div>"


def render_html(reading: Reading, history: list[dict], room_label: str) -> str:
    taken = reading.taken or datetime.now(timezone.utc)
    local = taken.astimezone()
    main_points = window_points(history, MAIN_HOURS, taken)
    caption = span_label(main_points)
    # The local name already starts with "Govee_", so do not prefix it again.
    device = reading.name or "Govee sensor"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
<meta http-equiv="refresh" content="120" />
<title>{room_label} &#8212; temperature &amp; humidity</title>
<style>{PAGE_CSS}</style>
</head>
<body data-reading="{taken.isoformat()}" data-stale-minutes="{STALE_MINUTES}">
<main>
  <div class="stale" id="stale" role="status" hidden>
    <span class="icon" aria-hidden="true">&#9888;</span>
    <span><strong>Stale reading.</strong> <span id="stale-detail"></span></span>
  </div>
  <h1>{room_label}</h1>
  <p class="hero">{reading.fahrenheit:.1f}<span class="unit">&#176;F</span></p>
  <p class="celsius">{reading.celsius:.1f} &#176;C</p>
  <div class="stats">
    <div class="stat">
      <span class="label">Humidity</span>
      <span class="value">{reading.humidity:.0f}%</span>
    </div>
    <div class="stat">
      <span class="label">Sensor battery</span>
      <span class="value">{reading.battery}%</span>
    </div>
  </div>
  <figure>
    <figcaption>{caption}</figcaption>
    {sparkline_svg(main_points, caption)}
  </figure>
  {long_views_html(history, taken)}
  <p class="age" id="age">Updated {clock(local)}</p>
</main>
<footer>
  <p>{device} over Bluetooth &#183; reading taken {datestamp(local)} &#183;
  page refreshes automatically &#183; <a href="reading.json">JSON</a></p>
</footer>
<script>{PAGE_JS}</script>
</body>
</html>
"""


def render_json(reading: Reading, room_label: str) -> str:
    taken = reading.taken or datetime.now(timezone.utc)
    return json.dumps({
        "room": room_label,
        "device": reading.name,
        "ts": taken.isoformat(),
        "celsius": round(reading.celsius, 2),
        "fahrenheit": round(reading.fahrenheit, 1),
        "humidity": round(reading.humidity, 1),
        "battery": reading.battery,
        "stale_after_minutes": STALE_MINUTES,
    }, indent=2) + "\n"


# --- publish ---------------------------------------------------------------------------------------

def publish(dest: str) -> bool:
    """rsync the rendered output. Returns True on success."""
    cmd = ["rsync", "-az", "-e", "ssh", f"{OUT_DIR}/", dest]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("rsync to %s failed (exit %d): %s", dest, result.returncode,
                  result.stderr.strip() or result.stdout.strip())
        return False
    log.info("published to %s", dest)
    return True


def upload(api: str, token: str, reading: Reading) -> bool:
    """Queue the reading and POST the queue to the server. Returns True if the queue was sent.

    The queue is pruned to the same week the history keeps, so a long outage cannot grow it without
    bound. The server ignores readings it already has, so resending after a lost response is safe.
    """
    now = datetime.now(timezone.utc)
    queue = prune(load_history(QUEUE_PATH), now)
    queue.append({
        "ts": (reading.taken or now).isoformat(),
        "celsius": round(reading.celsius, 2),
        "humidity": round(reading.humidity, 1),
        "battery": reading.battery,
        "rssi": reading.rssi,
    })
    write_atomic(QUEUE_PATH, json.dumps(queue))

    batch = queue[:MAX_BATCH]
    request = urllib.request.Request(f"{api.rstrip('/')}/api/v1/readings", method="POST",
                                     data=json.dumps({"readings": batch}).encode(),
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        log.error("upload to %s failed: HTTP %d %s", api, exc.code, exc.read()[:200].decode(errors="replace"))
        return False
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("upload to %s failed (%s); %d reading(s) queued", api, exc, len(queue))
        return False

    # Rejected readings would be rejected again, so they leave the queue along with the stored ones.
    for item in result.get("rejected", []):
        log.warning("server rejected %s: %s", batch[item["index"]]["ts"], item["error"])
    write_atomic(QUEUE_PATH, json.dumps(queue[len(batch):]))
    log.info("uploaded %d reading(s) to %s (%d new)", len(batch), api, result.get("stored", 0))
    return True


async def cycle(listener: Listener, args, after: datetime | None) -> Reading | None:
    """Render and publish the newest reading heard since `after`. Returns it, or None on a miss."""
    reading = await listener.wait_fresh(after, args.scan_timeout)
    now = datetime.now(timezone.utc)
    history = prune(load_history(), now)

    if reading is None:
        log.warning("no fresh reading from a device matching %r; leaving the last reading in place",
                    args.name_match)
        return None

    log.info("%s", reading)
    history.append({
        "ts": (reading.taken or now).isoformat(),
        "c": round(reading.celsius, 2),
        "rh": round(reading.humidity, 1),
        "batt": reading.battery,
    })
    write_atomic(HISTORY_PATH, json.dumps(history))

    write_atomic(OUT_DIR / "index.html", render_html(reading, history, args.room_label))
    write_atomic(OUT_DIR / "reading.json", render_json(reading, args.room_label))

    if args.no_publish:
        log.info("rendered to %s (publishing skipped)", OUT_DIR)
    elif args.api:
        upload(args.api, args.token, reading)
    else:
        publish(args.dest)
    return reading


# --- commands --------------------------------------------------------------------------------------

BLUETOOTH_HINT = ("If Bluetooth access was never granted, or was denied, check\n"
                  "System Settings > Privacy & Security > Bluetooth for your terminal application.")


def cmd_scan(args) -> int:
    try:
        devices = asyncio.run(collect(args.scan_timeout))
    except Exception as exc:  # bleak raises backend-specific errors when Bluetooth is unavailable
        print(f"Bluetooth scan failed: {exc.__class__.__name__}: {exc}\n\n{BLUETOOTH_HINT}")
        return 1
    if not devices:
        print(f"No Govee devices heard in {args.scan_timeout:.0f}s.\n\n"
              "The sensor may be out of range, or asleep. Note that some Govee models stop\n"
              "broadcasting while a phone holds a Bluetooth connection to them, so try closing\n"
              f"the Govee app if the sensor is nearby.\n\n{BLUETOOTH_HINT}")
        return 1
    print(f"{len(devices)} Govee device(s) heard in {args.scan_timeout:.0f}s:\n")
    unknown = 0
    for name, value, rssi in sorted(devices, key=lambda d: d[0]):
        print(f"  name : {name or '(no local name)'}")
        print(f"  raw  : {value.hex()} ({len(value)} bytes under company ID {GOVEE_MFR_ID:#06x})")
        decoded = decode(name, value)
        if decoded is None:
            unknown += 1
            print("  data : unrecognized model - no decoder matched this local name\n")
            continue
        celsius, humidity, battery = decoded
        reading = Reading(name, celsius, humidity, battery, rssi)
        print(f"  temp : {reading.fahrenheit:.1f} F / {celsius:.2f} C")
        print(f"  humid: {humidity:.1f} % RH")
        print(f"  batt : {battery} %")
        print(f"  rssi : {rssi} dBm\n")
    return 1 if unknown == len(devices) else 0


async def run_loop(args) -> int:
    async with Listener(args.name_match) as listener:
        if args.once:
            return 0 if await cycle(listener, args, None) else 1
        log.info("polling every %ds, publishing to %s", args.interval, args.api or args.dest)
        after = None
        while True:
            try:
                reading = await cycle(listener, args, after)
                if reading is not None:
                    after = reading.taken
                else:
                    # A silent scanner may be a stalled CoreBluetooth session; a fresh one is cheap.
                    await listener.stop()
                    await listener.start()
            except Exception:  # keep the loop alive across transient BLE and network faults
                log.exception("cycle failed; retrying at the next interval")
            await asyncio.sleep(args.interval)


def cmd_run(args) -> int:
    if args.api:
        try:
            args.token = TOKEN_PATH.read_text().strip()
        except OSError as exc:
            print(f"--api needs the kit token in {TOKEN_PATH}: {exc}", file=sys.stderr)
            return 1
    return asyncio.run(run_loop(args))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--scan-timeout", type=float, default=DEFAULT_SCAN_TIMEOUT,
                        help="seconds to wait for a reading before giving up on a cycle "
                             f"(default {DEFAULT_SCAN_TIMEOUT:.0f})")

    scan = sub.add_parser("scan", parents=[common],
                          help="print every Govee device heard, with decoded values")
    scan.set_defaults(func=cmd_scan)

    run = sub.add_parser("run", parents=[common], help="scan, render, and publish the page")
    run.add_argument("--once", action="store_true", help="a single pass instead of the loop")
    run.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                     help=f"seconds between cycles (default {DEFAULT_INTERVAL})")
    run.add_argument("--name-match", default=DEFAULT_NAME_MATCH,
                     help=f"substring the device local name must contain (default "
                          f"{DEFAULT_NAME_MATCH!r})")
    run.add_argument("--room-label", default=DEFAULT_ROOM_LABEL,
                     help="heading shown on the page")
    run.add_argument("--dest", default=DEFAULT_DEST, help="rsync destination")
    run.add_argument("--api", metavar="URL",
                     help="upload to the hallmonitor server at URL instead of rsyncing the page")
    run.add_argument("--no-publish", action="store_true",
                     help="render locally without rsyncing")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
