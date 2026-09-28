"""HTML rendering for the hallmonitor staff pages: login, room picker, and the room view.

The room view and its charts are ported from the original single-Mac page, with one change: times
render in the viewer's time zone, which TZ_JS stores in a cookie, instead of the local time of the
machine doing the rendering.
"""

import math
from datetime import datetime, timedelta, tzinfo
from html import escape

# The page shows a 24-hour main chart plus 72-hour and 7-day views.
MAIN_HOURS = 24
LONG_VIEWS = (72, 24 * 7)
HISTORY_HOURS = LONG_VIEWS[-1]
STALE_MINUTES = 12
REFRESH_SECONDS = 120

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
.picker { margin: 0 0 18px; }
.picker select, .login input, .login button {
  font: inherit;
  color: var(--ink);
  background: var(--page);
  border: 1px solid var(--axis);
  border-radius: 8px;
  padding: 7px 10px;
}
.picker select { width: 100%; font-weight: 600; color: var(--ink-2); }
.login { display: flex; flex-wrap: wrap; gap: 10px; }
.login input { flex: 1 1 200px; }
.login button { cursor: pointer; }
.error { color: var(--ink); margin: 0 0 14px; }
.rooms { margin: 0; padding-left: 1.2em; }
.rooms li { margin: 4px 0; }
.rooms a { color: var(--series); }
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
          ". The classroom kit may be unplugged, offline, or out of Bluetooth range, so the " +
          "numbers above are not current.";
      }
    }
  }
  tick();
  setInterval(tick, 15000);
})();
"""


# Store the browser's time zone in a cookie so the server can render times for the viewer, and
# reload once when it changes. The sessionStorage guard stops a reload loop when cookies are blocked.
TZ_JS = """
(function () {
  var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!tz) { return; }
  var value = encodeURIComponent(tz);
  if (document.cookie.split("; ").indexOf("tz=" + value) >= 0) { return; }
  document.cookie = "tz=" + value + "; path=/; max-age=31536000; samesite=lax" +
    (location.protocol === "https:" ? "; secure" : "");
  try {
    if (sessionStorage.getItem("tz-reload") === value) { return; }
    sessionStorage.setItem("tz-reload", value);
  } catch (e) { return; }
  location.reload();
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


def window_points(points: list[Point], hours: float, end: datetime) -> list[Point]:
    """Return the points from the `hours` before `end`, oldest first."""
    cutoff = end - timedelta(hours=hours)
    return [p for p in points if p[0] >= cutoff]


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


def sparkline_svg(points: list[Point], label: str, tz: tzinfo, width: int = 400, height: int = 140,
                  marker: int = 4) -> str:
    """Inline SVG line chart of temperature points in degrees F.

    Single series, so no legend: the figcaption names what is plotted. 2px round-capped line, an
    end-marker with a 2px surface ring, hairline gridlines, and explicit min/max tick labels so the
    y-range is never implied.

    The viewBox is sized close to the rendered CSS width so label text does not shrink on a phone,
    and every stroke carries vector-effect="non-scaling-stroke" so the 2px line and 1px hairlines
    keep their specified weight whatever width the card ends up.

    Time ticks fall on whole hours in `tz` for spans up to two days and on midnights in `tz` beyond
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

    # Vertical hairline plus label on each whole hour (or each midnight on a long span) inside the
    # window, thinned out so labels never collide on a narrow phone screen.
    local_start, local_end = t_start.astimezone(tz), t_end.astimezone(tz)
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


def long_views_html(points: list[Point], end: datetime, tz: tzinfo) -> str:
    """Smaller charts for the longer windows, side by side under the main chart.

    A longer view only appears once the history outgrows the window before it; until then it would
    just repeat the main chart at a smaller size.
    """
    figures = []
    previous_hours = MAIN_HOURS
    for hours in LONG_VIEWS:
        window = window_points(points, hours, end)
        if span_hours(window) > previous_hours:
            caption = span_text(window).capitalize()
            figures.append(f'<figure><figcaption>{caption}</figcaption>'
                           f'{sparkline_svg(window, span_label(window), tz, 280, 100, 3)}</figure>')
        previous_hours = hours
    if not figures:
        return ""
    return '<div class="long-views">' + "".join(figures) + "</div>"


def page(title: str, body: str, refresh: bool = False, body_attrs: str = "") -> str:
    meta = f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}" />\n' if refresh else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="robots" content="noindex" />
{meta}<title>{escape(title)}</title>
<style>{PAGE_CSS}</style>
<script>{TZ_JS}</script>
</head>
<body{body_attrs}>
{body}
</body>
</html>
"""


def login_page(error: str | None, next_url: str) -> str:
    message = f'<p class="error">{escape(error)}</p>' if error else ""
    return page("hallmonitor sign in", f"""<main>
  <h1>hallmonitor: classroom temperature and humidity</h1>
  {message}
  <form class="login" method="post" action="/login">
    <input type="hidden" name="next" value="{escape(next_url)}" />
    <input type="password" name="password" placeholder="Staff password" aria-label="Staff password"
           autocomplete="current-password" required autofocus />
    <button type="submit">Sign in</button>
  </form>
</main>""")


def room_name(room: dict) -> str:
    return room["instructor"]


def picker_html(rooms: list[dict], current: int | None) -> str:
    """A drop-down of active rooms that switches the page on change, with a button for no-JS browsers."""
    options = "".join(f'<option value="{r["id"]}"{" selected" if r["id"] == current else ""}>'
                      f'{escape(room_name(r))}</option>' for r in rooms)
    return (f'<form class="picker" method="get" action="/rooms">'
            f'<select name="id" aria-label="Room" onchange="this.form.submit()">{options}</select>'
            f'<noscript><button type="submit">Show</button></noscript></form>')


def rooms_page(rooms: list[dict]) -> str:
    if rooms:
        items = "".join(f'<li><a href="/rooms/{r["id"]}">{escape(room_name(r))}</a></li>' for r in rooms)
        content = f'<ul class="rooms">{items}</ul>'
    else:
        content = '<p class="age">No kits have reported in the past day.</p>'
    return page("hallmonitor rooms", f"""<main>
  <h1>Choose an instructor</h1>
  {content}
</main>
<footer><p><a href="/logout">Sign out</a></p></footer>""", refresh=True)


def room_page(room: dict, rooms: list[dict], rows: list, tz: tzinfo) -> str:
    """The room view: current reading, charts, and the room drop-down. `rows` are oldest first."""
    title = f"{room_name(room)}: temperature and humidity"
    header = picker_html(rooms, room["id"]) if len(rooms) > 1 else f"<h1>{escape(room_name(room))}</h1>"
    footer_links = f'<a href="/api/v1/rooms/{room["id"]}/readings">JSON</a> &#183; <a href="/logout">Sign out</a>'
    if not rows:
        return page(title, f"""<main>
  {header}
  <p class="age">No readings from this kit in the past week.</p>
</main>
<footer><p>{footer_links}</p></footer>""", refresh=True)

    points = [(datetime.fromisoformat(r["ts"]), r["celsius"] * 9.0 / 5.0 + 32.0) for r in rows]
    latest = rows[-1]
    taken = points[-1][0]
    local = taken.astimezone(tz)
    main_points = window_points(points, MAIN_HOURS, taken)
    caption = span_label(main_points)
    fahrenheit = latest["celsius"] * 9.0 / 5.0 + 32.0
    battery = "&#8212;" if latest["battery"] is None else f"{latest['battery']}%"
    body = f"""<main>
  <div class="stale" id="stale" role="status" hidden>
    <span class="icon" aria-hidden="true">&#9888;</span>
    <span><strong>Stale reading.</strong> <span id="stale-detail"></span></span>
  </div>
  {header}
  <p class="hero">{fahrenheit:.1f}<span class="unit">&#176;F</span></p>
  <p class="celsius">{latest['celsius']:.1f} &#176;C</p>
  <div class="stats">
    <div class="stat">
      <span class="label">Humidity</span>
      <span class="value">{latest['humidity']:.0f}%</span>
    </div>
    <div class="stat">
      <span class="label">Sensor battery</span>
      <span class="value">{battery}</span>
    </div>
  </div>
  <figure>
    <figcaption>{caption}</figcaption>
    {sparkline_svg(main_points, caption, tz)}
  </figure>
  {long_views_html(points, taken, tz)}
  <p class="age" id="age">Updated {clock(local)}</p>
</main>
<footer>
  <p>Reading taken {datestamp(local)} &#183; page refreshes automatically &#183; {footer_links}</p>
</footer>
<script>{PAGE_JS}</script>"""
    return page(title, body, refresh=True,
                body_attrs=f' data-reading="{taken.isoformat()}" data-stale-minutes="{STALE_MINUTES}"')
