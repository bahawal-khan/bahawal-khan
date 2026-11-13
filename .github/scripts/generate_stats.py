#!/usr/bin/env python3
"""
Generates two static SVG cards for a GitHub profile README:

  profile-stats/heatmap.svg  - GitHub-style GREEN contribution heatmap (last 53 weeks)
  profile-stats/streak.svg   - total contributions / current streak / longest streak

Why static SVG files committed to the repo?
  - They render everywhere (desktop browser, GitHub mobile app) because they are
    served from raw.githubusercontent.com, not from a third-party server that can
    go down or get paused.
  - No dependencies: Python standard library only.

Usage (GitHub Actions):  GITHUB_TOKEN=... USERNAME=... python generate_stats.py
Local preview (no token): python generate_stats.py --demo
"""
import json
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

OUT_DIR = os.environ.get("OUT_DIR", "profile-stats")
FONT = "'Segoe UI', -apple-system, BlinkMacSystemFont, Helvetica, Arial, sans-serif"

# GitHub's own dark-mode greens (level 0 = no contributions ... 4 = most)
LEVEL_COLORS = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]
LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

BG = "#0d1117"
BORDER = "#30363d"
TEXT_MUTED = "#8b949e"
TEXT_DIM = "#6e7681"
GREEN = "#39d353"
GREEN_DARK = "#26a641"


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def gql(token, query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_days(token, login):
    """Returns {date: (count, level)} for every year the account has activity."""
    years = gql(
        token,
        "query($l:String!){user(login:$l){contributionsCollection{contributionYears}}}",
        {"l": login},
    )["user"]["contributionsCollection"]["contributionYears"]

    q = """
    query($l:String!,$from:DateTime!,$to:DateTime!){
      user(login:$l){
        contributionsCollection(from:$from,to:$to){
          contributionCalendar{
            weeks{ contributionDays{ date contributionCount contributionLevel } }
          }
        }
      }
    }"""
    now = datetime.now(timezone.utc)
    days = {}
    for y in sorted(years):
        start = datetime(y, 1, 1, tzinfo=timezone.utc)
        end = min(datetime(y, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        data = gql(
            token,
            q,
            {"l": login, "from": start.isoformat(), "to": end.isoformat()},
        )
        weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        for w in weeks:
            for d in w["contributionDays"]:
                days[date.fromisoformat(d["date"])] = (
                    d["contributionCount"],
                    LEVELS.get(d["contributionLevel"], 0),
                )
    return days


def demo_days():
    """Synthetic data so the cards can be previewed without a token."""
    rnd = random.Random(7)
    today = date.today()
    days = {}
    for i in range(500):
        d = today - timedelta(days=i)
        r = rnd.random()
        if i < 9:  # a live current streak
            count = rnd.randint(1, 12)
        elif r < 0.35:
            count = 0
        else:
            count = rnd.randint(1, 18)
        level = 0 if count == 0 else 1 if count < 3 else 2 if count < 7 else 3 if count < 12 else 4
        days[d] = (count, level)
    return days


# --------------------------------------------------------------------------- #
# Streaks
# --------------------------------------------------------------------------- #
def fmt(d):
    return f"{d:%b} {d.day}"


def fmt_full(d):
    return f"{d:%b} {d.day}, {d.year}"


def compute_streaks(days):
    ordered = sorted(days)
    last = ordered[-1]

    # longest streak
    best_len, best_start, best_end = 0, None, None
    run_len, run_start = 0, None
    prev = None
    for d in ordered:
        if days[d][0] > 0:
            if prev is not None and (d - prev).days == 1 and run_len > 0:
                run_len += 1
            else:
                run_len, run_start = 1, d
            if run_len > best_len:
                best_len, best_start, best_end = run_len, run_start, d
        else:
            run_len = 0
        prev = d

    # current streak: still alive if today has no commits yet but yesterday did
    cur_len, cur_start, cur_end = 0, None, None
    d = last if days[last][0] > 0 else last - timedelta(days=1)
    while d in days and days[d][0] > 0:
        cur_end = cur_end or d
        cur_start = d
        cur_len += 1
        d -= timedelta(days=1)

    total = sum(c for c, _ in days.values())
    first_active = next((d for d in ordered if days[d][0] > 0), ordered[0])
    return {
        "total": total,
        "since": first_active,
        "last": last,
        "cur": (cur_len, cur_start, cur_end),
        "best": (best_len, best_start, best_end),
    }


# --------------------------------------------------------------------------- #
# SVG: heatmap
# --------------------------------------------------------------------------- #
def render_heatmap(days, login):
    CELL, GAP = 12, 3
    PITCH = CELL + GAP
    WEEKS = 53
    X0, Y0 = 44, 84            # grid origin
    W = X0 + WEEKS * PITCH + 22
    H = Y0 + 7 * PITCH + 52

    last = max(days)
    last_sunday_index = (last.weekday() + 1) % 7          # Sun=0 ... Sat=6
    start = last - timedelta(days=last_sunday_index + (WEEKS - 1) * 7)

    window_total = 0
    cells, month_labels = [], []
    prev_month = None
    for w in range(WEEKS):
        for dow in range(7):
            d = start + timedelta(days=w * 7 + dow)
            if d > last:
                continue
            count, level = days.get(d, (0, 0))
            window_total += count
            x, y = X0 + w * PITCH, Y0 + dow * PITCH
            tip = f"{count} contribution{'s' if count != 1 else ''} on {fmt_full(d)}"
            cells.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2.5" '
                f'fill="{LEVEL_COLORS[level]}"><title>{tip}</title></rect>'
            )
        first_of_col = start + timedelta(days=w * 7)
        if first_of_col.month != prev_month and (w == 0 or first_of_col.day <= 7):
            # skip a label squeezed against the previous one
            if not month_labels or X0 + w * PITCH - month_labels[-1][0] >= 38:
                month_labels.append((X0 + w * PITCH, f"{first_of_col:%b}"))
        prev_month = first_of_col.month

    months = "".join(
        f'<text x="{x}" y="{Y0 - 10}" font-size="12" fill="{TEXT_MUTED}">{m}</text>'
        for x, m in month_labels
    )
    weekdays = "".join(
        f'<text x="{X0 - 10}" y="{Y0 + i * PITCH + 10}" font-size="11" fill="{TEXT_DIM}" '
        f'text-anchor="end">{name}</text>'
        for i, name in ((1, "Mon"), (3, "Wed"), (5, "Fri"))
    )

    # legend
    lx = W - 22 - (5 * PITCH) - 78
    ly = Y0 + 7 * PITCH + 18
    legend = (
        f'<text x="{lx}" y="{ly + 10}" font-size="11" fill="{TEXT_MUTED}">Less</text>'
        + "".join(
            f'<rect x="{lx + 32 + i * PITCH}" y="{ly}" width="{CELL}" height="{CELL}" rx="2.5" fill="{c}"/>'
            for i, c in enumerate(LEVEL_COLORS)
        )
        + f'<text x="{lx + 32 + 5 * PITCH + 4}" y="{ly + 10}" font-size="11" fill="{TEXT_MUTED}">More</text>'
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{escape(login)} contribution heatmap">
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <g font-family="{FONT}">
    <text x="{X0 - 22}" y="32" font-size="17" font-weight="600" fill="{GREEN}">{window_total:,} contributions in the last year</text>
    <text x="{X0 - 22}" y="50" font-size="12" fill="{TEXT_MUTED}">@{escape(login)} &#183; updated {fmt_full(last)}</text>
    {months}
    {weekdays}
    {''.join(cells)}
    {legend}
  </g>
</svg>
"""


# --------------------------------------------------------------------------- #
# SVG: streak card
# --------------------------------------------------------------------------- #
def render_streak(s, login):
    W, H = 560, 176
    cur_len, cur_start, cur_end = s["cur"]
    best_len, best_start, best_end = s["best"]

    def span(a, b):
        if not a:
            return "No streak yet"
        return fmt(a) if a == b else f"{fmt(a)} - {fmt(b)}"

    flame = (
        "M0,-15 C5,-8 10,-3 10,4 C10,10 5,14 0,14 C-5,14 -10,10 -10,4 "
        "C-10,-1 -6,-4 -4,-9 C-3,-6 -2,-5 0,-4 C1,-9 0,-12 0,-15 Z"
    )
    cx, cy, r = 280, 78, 40
    circ = 2 * 3.14159265 * r
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{escape(login)} contribution streak">
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{BG}" stroke="{BORDER}"/>
  <g font-family="{FONT}" text-anchor="middle">
    <line x1="195" y1="26" x2="195" y2="150" stroke="{BORDER}"/>
    <line x1="365" y1="26" x2="365" y2="150" stroke="{BORDER}"/>

    <text x="98" y="78" font-size="34" font-weight="700" fill="{GREEN}">{s['total']:,}</text>
    <text x="98" y="104" font-size="14" fill="{GREEN_DARK}">Total Contributions</text>
    <text x="98" y="124" font-size="11" fill="{TEXT_DIM}">{fmt_full(s['since'])} - Present</text>

    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#161b22" stroke-width="6"/>
    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{GREEN}" stroke-width="6" stroke-linecap="round"
            stroke-dasharray="{circ * 0.80:.1f} {circ:.1f}" transform="rotate(-90 {cx} {cy})"/>
    <g transform="translate({cx} {cy - r - 2}) scale(0.62)">
      <rect x="-14" y="-12" width="28" height="30" fill="{BG}"/>
      <path d="{flame}" fill="{GREEN}"/>
    </g>
    <text x="{cx}" y="{cy + 12}" font-size="32" font-weight="700" fill="#e6edf3">{cur_len}</text>
    <text x="{cx}" y="140" font-size="14" font-weight="600" fill="{GREEN}">Current Streak</text>
    <text x="{cx}" y="158" font-size="11" fill="{TEXT_DIM}">{span(cur_start, cur_end)}</text>

    <text x="462" y="78" font-size="34" font-weight="700" fill="{GREEN}">{best_len}</text>
    <text x="462" y="104" font-size="14" fill="{GREEN_DARK}">Longest Streak</text>
    <text x="462" y="124" font-size="11" fill="{TEXT_DIM}">{span(best_start, best_end)}</text>
  </g>
</svg>
"""


# --------------------------------------------------------------------------- #
def main():
    demo = "--demo" in sys.argv
    login = os.environ.get("USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "octocat"
    if demo:
        days = demo_days()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("GITHUB_TOKEN is missing")
        days = fetch_days(token, login)
    if not days:
        sys.exit("No contribution data returned - not overwriting existing cards")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "heatmap.svg"), "w", encoding="utf-8") as f:
        f.write(render_heatmap(days, login))
    with open(os.path.join(OUT_DIR, "streak.svg"), "w", encoding="utf-8") as f:
        f.write(render_streak(compute_streaks(days), login))
    print(f"wrote {OUT_DIR}/heatmap.svg and {OUT_DIR}/streak.svg for @{login}")


if __name__ == "__main__":
    main()
