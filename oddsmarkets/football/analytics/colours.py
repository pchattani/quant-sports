"""
Club kit colours for the Broadcast heroes, game-card stripes and title-race bars (docs/_design/MIGRATION_V4.md,
"Football"): `colour` (the main colour) and `alt` (the second, for clashes) per club id, as "#rrggbb".

Three sources, in this order of precedence, merged into one committed table, data/club_colours.json
({tid: [colour, alt, source]}), which the build (PC or CI) reads:

  1. "sofascore": the `teamColors` (primary, secondary, text) Sofascore puts on every team object of the answers the
     fetchers already receive (event lists, standings, squads). oddsmarkets/football/sources/sofascore.py keeps them
     as they arrive, with no extra call, in data/sofascore_colours.json ({tid: [primary, secondary, text]}).
     Sofascore's placeholder (its own brand blue on both, for a team nobody has coloured) counts as unknown.
  2. "override": a small hand-checked table (OVERRIDES below) for top clubs whose crest read is wrong (Barcelona and
     Real Madrid gold, Newcastle teal, ...): the clubs' well-known primary and secondary colours. It beats the crest
     and stands in until Sofascore's colours for the club arrive.
  3. "crest": the dominant non-white colours of the club crests in docs/site/assets/crests/ (Sofascore's team
     images, fetched by scripts/fetch_crests.py), derived on the PC into data/crest_colours.json ({tid: [colour,
     alt]}); the crests themselves are never published by the public build (docs/HOSTING_MIGRATION.md, D6).

These are facts about club colours; no crest or image is shipped. A club in none of the three, or a national team,
gets nothing, and the kit falls back to cobalt v slate. A pale kit (Real Madrid's white) is the kit's job
(QK.color.block outlines or darkens it).

Rebuild the merged table (the fetchers do it when new Sofascore colours arrive; fetch_crests.py re-derives the crest
layer first):

    python -m oddsmarkets.football.analytics.colours            # re-derive the crest layer, then rebuild
    python -m oddsmarkets.football.analytics.colours --merge    # rebuild only
"""
from __future__ import annotations

import colorsys
import json
import math
import re
import sys
from pathlib import Path

DATA = Path(__file__).parent / "data"
TABLE = DATA / "club_colours.json"                  # the merged table the build reads: {tid: [colour, alt, source]}
CREST_TABLE = DATA / "crest_colours.json"           # derived from the crests: {tid: [colour, alt]}
SOFASCORE_TABLE = DATA / "sofascore_colours.json"   # Sofascore teamColors: {tid: [primary, secondary, text]}
SOURCES = ("sofascore", "override", "crest")

# Sofascore's teamColors for a team it has not coloured: its own brand blue (older answers: its old green) on both.
SOFASCORE_PLACEHOLDERS = {("#374df5", "#374df5"), ("#52b030", "#52b030")}

# Hand-checked primary and secondary colours of top clubs whose crest read is wrong or missing (the clubs' home kits
# and club identities, checked 23 Oct 2026). Sofascore's own colours, once kept, win over these.
OVERRIDES: dict[str, tuple[str, str | None]] = {
    # Premier League
    "40": ("#670e36", "#95bfe5"),       # Aston Villa: claret and sky blue (crest read light blue)
    "39": ("#241f20", "#ffffff"),       # Newcastle: black and white (crest read teal)
    "17": ("#6cabdd", "#1c2c5b"),       # Manchester City: sky blue and navy (crest read navy and gold)
    "7": ("#1b458f", "#c4122e"),        # Crystal Palace: blue and red (crest read pale blue and pink)
    "11": ("#59cbe8", "#ffffff"),       # Coventry: sky blue and white (crest read brown)
    "32": ("#0044a9", "#ffffff"),       # Ipswich: blue and white (crest read pink second)
    # LaLiga
    "2817": ("#004d98", "#a50044"),     # Barcelona: blaugrana blue and garnet (crest read gold)
    "2829": ("#ffffff", "#00529f"),     # Real Madrid: white, club blue second (crest read gold)
    "2824": ("#0067b1", "#ffffff"),     # Real Sociedad: blue and white (crest read orange)
    "2821": ("#8ac3ee", "#e5254e"),     # Celta Vigo: sky blue and red (crest read red first)
    "2832": ("#0057a8", "#ffffff"),     # Deportivo La Coruna: blue and white (crest read magenta)
    "2859": ("#005999", "#ffffff"),     # Getafe: blue and white (crest read green)
    "2846": ("#05642c", "#ffffff"),     # Elche: green and white (crest read red)
    "2814": ("#007fc8", "#ffffff"),     # Espanyol: blue and white (crest read red first)
    "2819": ("#ffe114", "#005187"),     # Villarreal: yellow and navy (crest read navy first)
    # Serie A
    "2699": ("#87d8f7", "#0c2340"),     # Lazio: sky blue, navy second (crest read pale gold)
    "2689": ("#f5d300", "#d6001c"),     # Lecce: yellow and red (crest read navy and bronze)
    # Bundesliga
    "2681": ("#e32221", "#000000"),     # Leverkusen: red and black (crest read maroon and olive)
    "2538": ("#e2001a", "#000000"),     # Freiburg: red and black (crest read black)
    # Ligue 1
    "1649": ("#14387f", "#da0812"),     # Lyon: blue and red (crest read orange second)
    "1661": ("#c8102e", "#000000"),     # Nice: red and black (crest read black and bronze)
    # Eredivisie
    "2953": ("#d2122e", "#ffffff"),     # Ajax: red and white (no crest colour)
    "2960": ("#e30613", "#ffffff"),     # Sparta Rotterdam: red and white (crest read black)
    # Primeira Liga
    "3006": ("#e20e17", "#ffffff"),     # Benfica: red and white (crest read orange and green)
    "3002": ("#00428c", "#ffffff"),     # Porto: blue and white (crest read grey-blue and bronze)
    "3036": ("#00843d", "#ffffff"),     # Rio Ave: green and white (crest read black)
    # Belgian Pro League
    "2901": ("#d71920", "#ffffff"),     # Standard Liege: red and white (crest read orange)
    "5044": ("#e2001a", "#ffe600"),     # Mechelen: red and yellow (crest read orange)
    # Brasileirao, Liga Profesional
    "1957": ("#000000", "#ffffff"),     # Corinthians: black and white (crest read red first)
    "3205": ("#002b5c", "#ffffff"),     # Gimnasia LP: navy and white (crest read teal)
    # MLS
    "243211": ("#80000a", "#000000"),   # Atlanta United: red and black (crest read dull gold)
    "337602": ("#f7b5cd", "#231f20"),   # Inter Miami: pink and black (no crest colour)
    "2505": ("#c8102e", "#0a174a"),     # Chicago Fire: red and navy (crest read pale blue)
    # Saudi Pro League
    "23400": ("#fcd116", "#0c2d6b"),    # Al-Nassr: yellow and blue (crest read navy first)
    # Liga MX
    "1938": ("#cd1719", "#0d2c6c"),     # Guadalajara: red, blue second (crest read navy and gold)
    "1940": ("#fdb913", "#002f6c"),     # Tigres: yellow and blue (crest read navy first)
    # HNL
    "2039": ("#0057b8", "#ffffff"),     # Rijeka: blue and white (crest read teal and beige)
}
HEX = re.compile(r"^#[0-9a-f]{6}$")
CRESTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "site" / "assets" / "crests"

# A pixel counts when it is opaque; white, off-white and light greys (the crest's background and outlines) do not.
_ALPHA_MIN = 200
_SIDE = 64              # crests are downscaled to at most 64 x 64 before counting
_MIN_SHARE = 0.06       # a colour must cover 6% of the crest's coloured pixels to count
_ALT_MIN_SHARE = 0.04   # the second colour 4%
_WHITE_ALT_SHARE = 0.2  # white is the alternate only when it covers a fifth of the crest and nothing else qualifies


def _hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, int(round(v)))):02x}" for v in rgb)


def _lum(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a, b) -> float:
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _whiteish(rgb) -> bool:
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    return l >= 0.86 or (l >= 0.75 and s < 0.15)


def _apart(a, b) -> bool:
    """Two colours a viewer tells apart (the kit's blockPair rule: 1.4:1 lightness, or 50 degrees of hue)."""
    if _contrast(a, b) >= 1.4:
        return True
    ha, la, sa = colorsys.rgb_to_hls(*(v / 255 for v in a))
    hb, lb, sb = colorsys.rgb_to_hls(*(v / 255 for v in b))
    if sa < 0.1 or sb < 0.1:
        return False
    d = abs(ha - hb) * 360
    return min(d, 360 - d) >= 50


def _second(a, b) -> bool:
    """b can stand in for a on a clash: another hue (50 degrees, both coloured), or black against a colour (3:1);
    a lighter shade of the same blue is not a second colour."""
    ha, la, sa = colorsys.rgb_to_hls(*(v / 255 for v in a))
    hb, lb, sb = colorsys.rgb_to_hls(*(v / 255 for v in b))
    if sa >= 0.18 and sb >= 0.18 and la >= 0.13 and lb >= 0.13:
        d = abs(ha - hb) * 360
        return min(d, 360 - d) >= 50
    return _contrast(a, b) >= 3


def _weight(rgb) -> float:
    """How much a colour says about the kit: greys and silvers (outlines, metal), pale tints and bronze rims count
    for less than true colours."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    if l < 0.13:
        return 0.7                      # black: a kit colour (Juventus, Newcastle) but also every outline
    if s < 0.18:
        return 0.3                      # grey, silver
    if l > 0.7 and s < 0.6:
        return 0.4                      # pale tints: cream, beige, a shield's light shading
    if 25 <= h * 360 <= 50 and s < 0.55 and 0.3 <= l <= 0.65:
        return 0.5                      # bronze and dull gold: a rim more often than a kit
    if s < 0.35:
        return 0.5                      # muted tones: shading, a banner, a background tint
    if 35 <= h * 360 <= 65:
        return 0.6                      # gold and yellow: crowns, stars and lettering as often as a kit
    return 1.0


def _bin(rgb) -> tuple:
    """A pixel's colour family: black, grey by lightness, else 20-degree hue by lightness band."""
    h, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb))
    if l < 0.13:
        return ("k",)
    if s < 0.18:
        return ("g", min(int(l * 4), 3))
    return ("c", int(h * 18) % 18, 0 if l < 0.35 else 1 if l < 0.6 else 2)


def derive(png: Path) -> tuple[str | None, str | None]:
    """(colour, alt) of one crest: the strongest non-white colour family, then the strongest one told apart from it.
    Pixels near the crest's centre (the shield, where the club colours sit) count more than its rim, and greys,
    silvers, pale tints and bronze count less than true colours (_weight)."""
    from PIL import Image  # local tool only: the build reads the committed table

    im = Image.open(png).convert("RGBA")
    im.thumbnail((_SIDE, _SIDE))
    w, h = im.size
    cx, cy, rad = (w - 1) / 2, (h - 1) / 2, max(w, h) / 2
    n_px = n_white = 0
    fam: dict[tuple, list[float]] = {}
    pixels = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    for i, p in enumerate(pixels):
        if p[3] < _ALPHA_MIN:
            continue
        n_px += 1
        rgb = p[:3]
        if _whiteish(rgb):
            n_white += 1
            continue
        x, y = i % w, i // w
        wt = math.exp(-1.2 * (((x - cx) / rad) ** 2 + ((y - cy) / rad) ** 2))
        f = fam.setdefault(_bin(rgb), [0.0, 0.0, 0.0, 0.0])
        f[0] += wt
        f[1] += rgb[0] * wt
        f[2] += rgb[1] * wt
        f[3] += rgb[2] * wt
    n_col = n_px - n_white
    if not n_px or n_col < 0.05 * n_px:
        return None, None
    groups = sorted(([f[0], (f[1] / f[0], f[2] / f[0], f[3] / f[0])] for f in fam.values() if f[0] > 0),
                    key=lambda g: -g[0])
    # neighbouring families a viewer would not tell apart join the bigger one (one red shaded across two bins)
    merged: list[list] = []
    for g in groups:
        for m in merged:
            if not _apart(m[1], g[1]) and _contrast(m[1], g[1]) < 1.3:
                tot = m[0] + g[0]
                m[1] = tuple((m[1][k] * m[0] + g[1][k] * g[0]) / tot for k in range(3))
                m[0] = tot
                break
        else:
            merged.append(list(g))
    total = sum(m[0] for m in merged)
    ranked = sorted(merged, key=lambda m: -m[0] * _weight(m[1]))
    main = [m for m in ranked if m[0] >= _MIN_SHARE * total]
    if not main:
        return None, None
    if _weight(main[0][1]) <= 0.3:
        return None, None               # a grey or silver crest says nothing about the kit: the kit's fallback
    colour = main[0][1]
    alt = next((m[1] for m in ranked if m is not main[0] and m[0] >= _ALT_MIN_SHARE * total and _second(colour, m[1])
                and _weight(m[1]) > 0.3), None)
    if alt is None and n_white >= _WHITE_ALT_SHARE * n_px:
        alt = (255, 255, 255)
    return _hex(colour), (_hex(alt) if alt else None)


def _write_rows(table: Path, rows: dict[str, list]) -> None:
    """One club per line, sorted by id (a small diff when one club changes)."""
    table.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(f'"{k}":{json.dumps(v)}' for k, v in sorted(rows.items(), key=lambda kv: (len(kv[0]), kv[0])))
    table.write_text("{\n" + body + "\n}\n" if rows else "{}\n", encoding="utf-8")


def _read(table: Path) -> dict[str, list]:
    try:
        rows = json.loads(table.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def _norm(v) -> str | None:
    v = str(v or "").strip().lower()
    if re.match(r"^#[0-9a-f]{3}$", v):
        v = "#" + "".join(c * 2 for c in v[1:])
    return v if HEX.match(v) else None


def _three(row) -> list:
    return [_norm(v) for v in (list(row or []) + [None, None, None])[:3]]


def sofascore_pair(row) -> tuple[str | None, str | None]:
    """(colour, alt) from a kept Sofascore teamColors row [primary, secondary, text]: the placeholder is unknown; the
    secondary is the alternate when it differs from the primary, else the text colour when that does."""
    primary, secondary, text = _three(row)
    if not primary or (primary, secondary) in SOFASCORE_PLACEHOLDERS:
        return None, None
    alt = secondary if secondary and secondary != primary else text if text and text != primary else None
    return primary, alt


def merge(sofascore: dict[str, list], overrides: dict[str, tuple], crest: dict[str, list]) -> dict[str, list]:
    """{tid: [colour, alt, source]}: Sofascore first, then a hand-checked override, then the crest."""
    out: dict[str, list] = {}
    for tid, row in crest.items():
        colour, alt = (_three(row) + [None])[:2]
        if colour:
            out[str(tid)] = [colour, alt, "crest"]
    for tid, (colour, alt) in overrides.items():
        if _norm(colour):
            out[str(tid)] = [_norm(colour), _norm(alt), "override"]
    for tid, row in sofascore.items():
        colour, alt = sofascore_pair(row)
        if colour:
            out[str(tid)] = [colour, alt, "sofascore"]
    return out


def rebuild(table: Path = TABLE, sofascore: Path = SOFASCORE_TABLE, crest: Path = CREST_TABLE,
            overrides: dict[str, tuple] | None = None) -> dict[str, list]:
    """Merge the three sources into the committed table the build reads, and return it."""
    rows = merge(_read(sofascore), OVERRIDES if overrides is None else overrides, _read(crest))
    _write_rows(table, rows)
    _CACHE.pop(table, None)
    return rows


def keep_sofascore(seen: dict[str, list], sofascore: Path = SOFASCORE_TABLE) -> int:
    """Fold the teamColors seen in a run ({tid: [primary, secondary, text]}) into the kept Sofascore map; returns the
    number of clubs added or changed (the newest answer wins)."""
    kept = _read(sofascore)
    changed = 0
    for tid, row in seen.items():
        row = _three(row)
        if not str(tid).isdigit() or not row[0] or kept.get(str(tid)) == row:
            continue
        kept[str(tid)] = row
        changed += 1
    if changed:
        _write_rows(sofascore, kept)
    return changed


def refresh(crests_dir: Path = CRESTS_DIR, table: Path = CREST_TABLE) -> dict[str, list]:
    """Re-derive every crest's colours and write the crest layer ({tid: [colour, alt]}, sorted by id)."""
    out: dict[str, list] = {}
    for png in sorted(crests_dir.glob("*.png"), key=lambda p: (len(p.stem), p.stem)):
        if not png.stem.isdigit():
            continue
        try:
            colour, alt = derive(png)
        except Exception:  # noqa: BLE001  a broken image: no colours, the kit falls back
            continue
        if colour:
            out[png.stem] = [colour, alt]
    _write_rows(table, out)
    return out


_CACHE: dict[Path, dict[str, list]] = {}


def load(table: Path = TABLE) -> dict[str, list]:
    """The committed table ({tid: [colour, alt, source]}); empty when it is missing."""
    if table not in _CACHE:
        _CACHE[table] = _read(table)
    return _CACHE[table]


def club(tid, table: Path = TABLE) -> dict[str, str]:
    """{"colour": ..., "alt": ...} for a club id (only the keys that are known)."""
    row = load(table).get(str(tid)) or [None, None]
    return {k: v for k, v in zip(("colour", "alt"), row) if v}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--merge" not in sys.argv:
        crest_rows = refresh(Path(args[0]) if args else CRESTS_DIR)
        print(f"crests: {len(crest_rows)} clubs with a colour -> {CREST_TABLE}")
    rows = rebuild()
    by = {k: sum(1 for v in rows.values() if v[2] == k) for k in SOURCES}
    print(f"{len(rows)} clubs with a colour ({by}) -> {TABLE}")
