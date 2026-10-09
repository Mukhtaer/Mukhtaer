#!/usr/bin/env python3
"""Render the profile terminal as dark and light SVGs, with live GitHub activity."""

import base64
import json
import os
import random
import sys
import textwrap
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com/graphql"
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      nodes { languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name color } } } }
    }
  }
}
"""

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

# Rosé Pine (dark) and Rosé Pine Dawn (light).
THEMES = {
    "dark": {"text": "#E0DEF4", "soft": "#908CAA", "muted": "#6E6A86", "prompt": "#C4A7E7", "accent": "#9CCFD8",
             "panel": "#191724", "chrome": "#1F1D2E", "border": "#2A2739", "track": "#26233A",
             "levels": ["#26233A", "#4C425E", "#6E5F86", "#9983B6", "#C4A7E7"],
             "groups": {"web": "#9CCFD8", "mobile": "#C4A7E7", "backend": "#EBBCBA", "data": "#F6C177", "delivery": "#EB6F92"}},
    "light": {"text": "#575279", "soft": "#797593", "muted": "#9893A5", "prompt": "#907AA9", "accent": "#286983",
              "panel": "#FAF4ED", "chrome": "#FFFAF3", "border": "#DFDAD9", "track": "#F2E9E1",
              "levels": ["#F2E9E1", "#DACFD9", "#C5B7CB", "#AB99BA", "#907AA9"],
              "groups": {"web": "#56949F", "mobile": "#907AA9", "backend": "#D7827E", "data": "#EA9D34", "delivery": "#B4637A"}},
}

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT = "'Geist Mono', 'SF Mono', ui-monospace, Menlo, Consolas, monospace"
WIDTH, SIZE, LINE_HEIGHT, PAD, CHAR = 820, 15, 28, 48, 9.0
TOP, GAP = 108, 14
CELL, CELL_GAP = 10, 3

STACK = {
    "web": ["next.js", "react", "typescript", "tailwind"],
    "mobile": ["flutter", "dart", "firebase"],
    "backend": ["laravel", "php", "python", "livewire", "rest"],
    "data": ["mysql", "postgresql"],
    "delivery": ["docker", "github-actions", "linux", "nginx"],
}
CHIP_SIZE, CHIP_HEIGHT, CHIP_GAP = 13, 24, 8

QUOTES = [
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Simple things should be simple, complex things should be possible.", "Alan Kay"),
    ("Good programmers write code that humans can understand.", "Martin Fowler"),
    ("If it hurts, do it more often.", "Martin Fowler"),
    ("The best code is no code at all.", "Jeff Atwood"),
    ("Programs must be written for people to read.", "Harold Abelson"),
    ("Code never lies, comments sometimes do.", "Ron Jeffries"),
    ("Fix the cause, not the symptom.", "Steve Maguire"),
    ("Walking on water and developing software from a specification are easy if both are frozen.", "Edward V. Berard"),
]
QUOTE_WIDTH = 72


def fetch(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    request = urllib.request.Request(API, body, {"Authorization": f"bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["user"]


def current_streak(days, today):
    counts = [d["contributionCount"] for d in days if date.fromisoformat(d["date"]) <= today]
    if counts and counts[-1] == 0:
        counts.pop()
    streak = 0
    for count in reversed(counts):
        if count == 0:
            break
        streak += 1
    return streak


def longest_streak(days):
    best = run = 0
    for day in days:
        run = run + 1 if day["contributionCount"] else 0
        best = max(best, run)
    return best


def top_languages(repositories, limit=8):
    sizes, colors = Counter(), {}
    for repo in repositories:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            sizes[name] += edge["size"]
            colors[name] = edge["node"]["color"]
    top = sizes.most_common(limit)
    total = sum(size for _, size in top)
    return [(name, colors[name], size / total) for name, size in top] if total else []


def quote_of_the_day(today):
    return random.Random(today.toordinal()).choice(QUOTES)


def summarize(user, today):
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    return {
        "total": calendar["totalContributions"],
        "current": current_streak(days, today),
        "longest": longest_streak(days),
        "weeks": [[LEVELS[d["contributionLevel"]] for d in week["contributionDays"]] for week in calendar["weeks"]],
        "languages": top_languages(user["repositories"]["nodes"]),
        "quote": quote_of_the_day(today),
    }


def font_faces():
    faces = []
    for weight in (400, 600):
        data = base64.b64encode((FONT_DIR / f"geist-mono-{weight}.woff2").read_bytes()).decode()
        faces.append(f"@font-face {{ font-family: 'Geist Mono'; font-weight: {weight}; src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
    return "\n    ".join(faces)


def fade_in(begin, duration=0.2):
    return f'<animate attributeName="opacity" from="0" to="1" begin="{begin:.2f}s" dur="{duration}s" fill="freeze"/>'


class Terminal:
    def __init__(self, theme):
        self.t = theme
        self.defs, self.parts = [], []
        self.y, self.clock = TOP, 0.3

    def command(self, text):
        text = f"$ {text}"
        clip_id = f"c{len(self.defs)}"
        duration = 0.02 * len(text)
        widths = ";".join(str(i * CHAR) for i in range(len(text))) + f";{len(text) * CHAR + SIZE}"
        self.defs.append(
            f'<clipPath id="{clip_id}"><rect x="{PAD}" y="{self.y - SIZE}" height="{SIZE * 1.6}" width="0">'
            f'<animate attributeName="width" begin="{self.clock:.2f}s" dur="{duration:.2f}s" fill="freeze" calcMode="discrete" values="{widths}"/>'
            f"</rect></clipPath>"
        )
        self.parts.append(
            f'<text x="{PAD}" y="{self.y}" clip-path="url(#{clip_id})"><tspan fill="{self.t["prompt"]}">$</tspan>'
            f'<tspan fill="{self.t["text"]}" font-weight="600">{escape(text[1:])}</tspan></text>'
        )
        self.clock += duration + 0.1
        self.y += LINE_HEIGHT

    def output(self, *spans):
        content = "".join(
            f'<tspan fill="{self.t[color]}" font-weight="{600 if strong else 400}">{escape(text)}</tspan>'
            for color, text, *strong in spans
        )
        self.parts.append(f'<text x="{PAD}" y="{self.y}" opacity="0" xml:space="preserve">{content}{fade_in(self.clock)}</text>')
        self.clock += 0.05
        self.y += LINE_HEIGHT

    def gap(self):
        self.y += GAP

    def heatmap(self, weeks):
        top = self.y - SIZE + 4
        for col, week in enumerate(weeks):
            x = PAD + col * (CELL + CELL_GAP)
            cells = "".join(
                f'<rect x="{x}" y="{top + row * (CELL + CELL_GAP)}" width="{CELL}" height="{CELL}" rx="2.5" fill="{self.t["levels"][level]}"/>'
                for row, level in enumerate(week)
            )
            self.parts.append(f'<g opacity="0">{cells}{fade_in(self.clock + col * 0.008, 0.15)}</g>')
        self.clock += len(weeks) * 0.008 + 0.1
        self.y += 7 * (CELL + CELL_GAP) + 16

    def languages(self, languages):
        width, top, clip_id = WIDTH - 2 * PAD, self.y - 12, f"c{len(self.defs)}"
        self.defs.append(
            f'<clipPath id="{clip_id}"><rect x="{PAD}" y="{top}" height="8" rx="4" width="0">'
            f'<animate attributeName="width" from="0" to="{width}" begin="{self.clock:.2f}s" dur="0.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines=".2 .7 .2 1"/>'
            f"</rect></clipPath>"
        )
        x, segments = PAD, []
        for _, color, share in languages:
            segments.append(f'<rect x="{x:.1f}" y="{top}" width="{width * share:.1f}" height="8" fill="{color or self.t["muted"]}"/>')
            x += width * share
        self.parts.append(f'<g clip-path="url(#{clip_id})">{"".join(segments)}</g>')

        rows = (len(languages) + 1) // 2
        for i, (name, color, share) in enumerate(languages):
            col, row = divmod(i, rows)
            x, y = PAD + col * 330, self.y + 26 + row * LINE_HEIGHT
            self.parts.append(
                f'<g opacity="0">{fade_in(self.clock + 0.2 + i * 0.04)}'
                f'<circle cx="{x + 5}" cy="{y - 5}" r="5" fill="{color or self.t["muted"]}"/>'
                f'<text x="{x + 20}" y="{y}" xml:space="preserve"><tspan fill="{self.t["soft"]}">{escape(name)}</tspan>'
                f'<tspan fill="{self.t["muted"]}">  {share:.2%}</tspan></text></g>'
            )
        self.clock += 0.7
        self.y += 26 + rows * LINE_HEIGHT

    def stack(self, groups):
        small = CHIP_SIZE * 0.6
        legend_width = sum(18 + len(name) * small + 18 for name in groups) - 18
        x, y = WIDTH - PAD - legend_width, self.y - LINE_HEIGHT
        for name in groups:
            self.parts.append(
                f'<g opacity="0">{fade_in(self.clock)}<circle cx="{x + 4:.1f}" cy="{y - 4.5}" r="3.5" fill="{self.t["groups"][name]}"/>'
                f'<text x="{x + 14:.1f}" y="{y}" fill="{self.t["muted"]}" style="font-size:{CHIP_SIZE}px">{name}</text></g>'
            )
            x += 18 + len(name) * small + 18

        x, top = PAD, self.y - SIZE
        for i, (group, tool) in enumerate((g, t) for g, tools in groups.items() for t in tools):
            width = 34 + len(tool) * small
            if x + width > WIDTH - PAD:
                x, top = PAD, top + CHIP_HEIGHT + CHIP_GAP
            self.parts.append(
                f'<g opacity="0">{fade_in(self.clock + i * 0.02, 0.15)}'
                f'<rect x="{x:.1f}" y="{top}" width="{width:.1f}" height="{CHIP_HEIGHT}" rx="{CHIP_HEIGHT / 2}" fill="{self.t["track"]}" stroke="{self.t["border"]}"/>'
                f'<circle cx="{x + 13:.1f}" cy="{top + CHIP_HEIGHT / 2}" r="3.5" fill="{self.t["groups"][group]}"/>'
                f'<text x="{x + 23:.1f}" y="{top + CHIP_HEIGHT / 2 + CHIP_SIZE * 0.35:.1f}" fill="{self.t["soft"]}" style="font-size:{CHIP_SIZE}px">{escape(tool)}</text></g>'
            )
            x += width + CHIP_GAP
        self.clock += 0.5
        self.y = top + CHIP_HEIGHT + SIZE + 10

    def checks(self, labels):
        x = PAD
        for label in labels:
            self.clock += 0.15
            self.parts.append(
                f'<text x="{x}" y="{self.y}" opacity="0"><tspan fill="{self.t["accent"]}">✓</tspan>'
                f'<tspan fill="{self.t["soft"]}"> {label}</tspan>{fade_in(self.clock, 0.15)}</text>'
            )
            x += (len(label) + 5) * CHAR
        self.clock += 0.1
        self.y += LINE_HEIGHT

    def prompt(self):
        self.parts.append(
            f'<g opacity="0">{fade_in(self.clock, 0.1)}<text x="{PAD}" y="{self.y}" fill="{self.t["prompt"]}">$</text>'
            f'<rect class="cursor" x="{PAD + 2 * CHAR}" y="{self.y - SIZE + 2}" width="{CHAR}" height="{SIZE * 1.15}" rx="1" fill="{self.t["prompt"]}"/></g>'
        )

    def svg(self, synced):
        t, height = self.t, round(self.y + 40)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Mukhtar Sani, software engineer. Terminal with stack and GitHub activity.">
  <title>Mukhtar Sani, software engineer</title>
  <style>
    {font_faces()}
    text {{ font-family: {FONT}; font-size: {SIZE}px; }}
    .cursor {{ animation: blink 1s steps(1) infinite; }}
    @keyframes blink {{ 0%, 49% {{ opacity: 1; }} 50%, 100% {{ opacity: 0; }} }}
  </style>
  <defs>{"".join(self.defs)}</defs>
  <rect x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="14" fill="{t["panel"]}" stroke="{t["border"]}"/>
  <path d="M.5 14.5 a14 14 0 0 1 14 -14 h{WIDTH - 29} a14 14 0 0 1 14 14 v33 h-{WIDTH - 1} z" fill="{t["chrome"]}"/>
  <line x1=".5" y1="48" x2="{WIDTH - .5}" y2="48" stroke="{t["border"]}"/>
  <circle cx="26" cy="24" r="5.5" fill="{t["border"]}"/><circle cx="46" cy="24" r="5.5" fill="{t["border"]}"/><circle cx="66" cy="24" r="5.5" fill="{t["border"]}"/>
  <text x="{WIDTH / 2}" y="28.5" fill="{t["muted"]}" text-anchor="middle" style="font-size:12px">mukhtar@dev: ~</text>
  <text x="{WIDTH - 24}" y="28.5" fill="{t["muted"]}" text-anchor="end" style="font-size:11px">synced {synced}</text>
  {chr(10).join("  " + part for part in self.parts)}
</svg>
"""


def render(stats, theme, synced):
    term = Terminal(theme)
    term.command("whoami")
    term.output(("text", "mukhtar sani · software engineer"))
    term.gap()
    term.command("cat about.txt")
    term.output(("soft", "I build software end to end: web and mobile apps,"))
    term.output(("soft", "the APIs behind them, and the pipelines that ship them."))
    term.gap()
    term.command("ls ~/stack")
    term.stack(STACK)
    term.gap()
    term.command("git activity")
    term.heatmap(stats["weeks"])
    term.output(
        ("text", f"{stats['total']:,}", True), ("muted", " contributions   "),
        ("text", f"{stats['current']}d", True), ("muted", " streak   "),
        ("text", f"{stats['longest']}d", True), ("muted", " best"),
    )
    term.gap()
    term.command("git languages")
    term.languages(stats["languages"])
    term.gap()
    term.command("make deploy")
    term.checks(["lint", "test", "build", "ship"])
    term.gap()
    text, author = stats["quote"]
    term.command("fortune")
    for line in textwrap.wrap(f'"{text}"', QUOTE_WIDTH):
        term.output(("text", line))
    term.output(("muted", f"  {author}"))
    term.gap()
    term.prompt()
    return term.svg(synced)


def main():
    login, out_dir = sys.argv[1], Path(sys.argv[2])
    now = datetime.now(timezone.utc)
    stats = summarize(fetch(login, os.environ["GITHUB_TOKEN"]), now.date())
    synced = f"{now.day} {now:%b %Y}"
    for mode, theme in THEMES.items():
        (out_dir / f"terminal-{mode}.svg").write_text(render(stats, theme, synced), encoding="utf-8")


if __name__ == "__main__":
    main()
