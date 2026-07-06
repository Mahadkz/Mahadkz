#!/usr/bin/env python3
"""Generate a terminal-style animated SVG banner from live GitHub stats.

Runs in CI (see .github/workflows/banner.yml). Reads stats via the GitHub
GraphQL API using the Actions token, which can see private contributions.
Writes banner.svg into the repo. No third-party image services -> never breaks.

Design constraint: the SVG must look COMPLETE at rest (t=0). GitHub's camo
proxy and non-animating viewers snapshot the first frame, so content is always
visible; the typing/draw animation is a first-paint flourish layered on top,
never something that hides content.
"""
import json
import os
import urllib.request
from collections import Counter

USER = "Mahadkz"
TOKEN = os.environ["GH_TOKEN"]
API = "https://api.github.com/graphql"

QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    all: repositories(first: 100, ownerAffiliations: OWNER) {
      totalCount
      nodes { isFork primaryLanguage { name } }
    }
    public: repositories(privacy: PUBLIC, ownerAffiliations: OWNER) { totalCount }
    followers { totalCount }
  }
}
"""


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        out = json.load(r)
    if "errors" in out:
        raise SystemExit(f"GraphQL error: {out['errors']}")
    return out["data"]


def collect():
    u = gql(QUERY, {"login": USER})["user"]
    repos = u["all"]["nodes"]
    langs = Counter(
        r["primaryLanguage"]["name"]
        for r in repos
        if r["primaryLanguage"] and not r["isFork"]
    )
    return {
        "name": u["name"] or u["login"],
        "login": u["login"],
        "repos": u["all"]["totalCount"],
        "public": u["public"]["totalCount"],
        "followers": u["followers"]["totalCount"],
        "langs": langs.most_common(5),
    }


# --- SVG building -------------------------------------------------------------

W, H = 820, 476
PAD = 34
GREEN = "#39d353"
FG = "#c9d1d9"
MUTED = "#8b949e"
PROMPT = "#58a6ff"
BG = "#0d1117"
FONT = "'SFMono-Regular','JetBrains Mono','Fira Code',ui-monospace,Consolas,monospace"
CH = 8.4   # monospace char advance at 14px
LINE = 26


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def line(segments, x, y, begin, dur=0.5):
    """One terminal line. `segments` = list of (text, css_class).

    Rendered fully visible; a clip-path wipe reveals it left-to-right starting
    at `begin`. If the viewer ignores SMIL, the clip still shows full width
    because we animate width and also set the rect's static width to full.
    """
    text = "".join(t for t, _ in segments)
    w = len(text) * CH + 6
    cid = f"clip{abs(hash((text, begin))) % 100000}"
    tspans = ""
    for t, cls in segments:
        tspans += f'<tspan class="{cls}">{esc(t)}</tspan>'
    return f'''
  <g transform="translate({x},{y})">
    <clipPath id="{cid}"><rect x="-3" y="-14" width="{w}" height="22">
      <animate attributeName="width" values="0;{w}" dur="{dur}s" begin="{begin}s"
               fill="freeze" calcMode="linear"/>
    </rect></clipPath>
    <text clip-path="url(#{cid})">{tspans}</text>
  </g>'''


def bar(pct, x, y, w, color, begin):
    track = f'<rect x="{x}" y="{y}" width="{w}" height="7" rx="3.5" fill="#21262d"/>'
    fw = w * pct / 100
    fill = f'''<rect x="{x}" y="{y}" width="{fw:.1f}" height="7" rx="3.5" fill="{color}">
      <animate attributeName="width" values="0;{fw:.1f}" dur="0.7s" begin="{begin}s"
               fill="freeze" calcMode="spline" keyTimes="0;1" keySplines="0.2 0.7 0.2 1"/>
    </rect>'''
    return track + fill


def build(d):
    x = PAD
    y = 78
    els = []

    def prompt(cmd, begin):
        return line([(f"{d['login']} ", "prompt"), ("~ ", "muted"), ("$ ", "green"), (cmd, "fg")], x, y, begin)

    els.append(prompt("whoami", 0.0)); y += LINE
    els.append(line([(d["name"], "green")], x, y, 0.5)); y += LINE + 10

    els.append(prompt("cat profile.json", 0.9)); y += LINE + 4
    rows = [
        ("repositories", str(d["repos"]), f"{d['public']} public"),
        ("followers", str(d["followers"]), None),
        ("primary lang", d["langs"][0][0] if d["langs"] else "-", "by repo count"),
    ]
    for i, (k, v, note) in enumerate(rows):
        b = 1.4 + i * 0.22
        segs = [("  " + k.ljust(15), "muted"), (v, "value")]
        if note:
            segs.append(("   " + note, "dim"))
        els.append(line(segs, x, y, b, dur=0.35)); y += 24
    y += 16

    els.append(prompt("langs --top 5", 2.5)); y += LINE + 6
    total = sum(c for _, c in d["langs"]) or 1
    palette = ["#3178c6", "#f1e05a", "#e34c26", "#563d7c", "#3572A5", "#dea584"]
    for i, (name, count) in enumerate(d["langs"]):
        b = 3.0 + i * 0.28
        pct = 100 * count / total
        els.append(line([(name.ljust(12), "fg")], x + 2, y + 4, b, dur=0.3))
        els.append(bar(pct, x + 118, y - 3, 300, palette[i % len(palette)], b + 0.05))
        els.append(
            f'<text class="dim small" x="{x+430}" y="{y+4}" opacity="0">{pct:.0f}%'
            f'<animate attributeName="opacity" values="0;1" dur="0.3s" begin="{b+0.4}s" fill="freeze"/></text>'
        )
        y += 23
    y += 20

    # blinking cursor at the final prompt (always visible, blink is the only motion)
    cy = y
    cursor_x = x + len(f"{d['login']} ~ $ ") * CH
    els.append(line([(f"{d['login']} ", "prompt"), ("~ ", "muted"), ("$ ", "green")], x, cy, 4.5, dur=0.2))
    els.append(
        f'<rect class="cursor" x="{cursor_x:.0f}" y="{cy-12}" width="9" height="16" fill="{PROMPT}">'
        f'<animate attributeName="opacity" values="1;1;0;0" dur="1.1s" begin="4.7s" '
        f'repeatCount="indefinite" calcMode="discrete"/></rect>'
    )

    body = "\n".join(els)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" role="img" aria-label="{esc(d['name'])} - GitHub profile stats">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0.4" y2="1">
      <stop offset="0" stop-color="#161b22"/>
      <stop offset="1" stop-color="{BG}"/>
    </linearGradient>
  </defs>
  <style>
    text {{ font-family: {FONT}; font-size: 14px; dominant-baseline: alphabetic; }}
    .fg {{ fill: {FG}; }}
    .green {{ fill: {GREEN}; font-weight: 600; }}
    .value {{ fill: {FG}; font-weight: 600; }}
    .prompt {{ fill: {PROMPT}; }}
    .muted {{ fill: {MUTED}; }}
    .dim {{ fill: #6e7681; }}
    .small {{ font-size: 12px; }}
  </style>
  <rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="12" fill="url(#bg)" stroke="#30363d"/>
  <circle cx="24" cy="24" r="6" fill="#ff5f56"/>
  <circle cx="46" cy="24" r="6" fill="#ffbd2e"/>
  <circle cx="68" cy="24" r="6" fill="#27c93f"/>
  <text x="{W/2}" y="28" text-anchor="middle" class="dim small">{esc(d['login'])} - bash</text>
  <line x1="0" y1="48" x2="{W}" y2="48" stroke="#30363d"/>
{body}
</svg>'''


if __name__ == "__main__":
    data = collect()
    print("stats:", {k: v for k, v in data.items() if k != "langs"}, "langs:", data["langs"])
    svg = build(data)
    with open("banner.svg", "w") as f:
        f.write(svg)
    print(f"wrote banner.svg ({len(svg)} bytes)")
