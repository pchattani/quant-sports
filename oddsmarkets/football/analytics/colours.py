"""
Club kit colours for the Broadcast heroes, game-card stripes and title-race bars (docs/_design/MIGRATION_V4.md,
"Football"): `colour` (the main colour) and `alt` (the second, for clashes) per club id, as "#rrggbb".

Source: the dominant non-white colours of the club crests in docs/site/assets/crests/ (Sofascore's team images,
fetched by scripts/fetch_crests.py; the stores keep no `teamColors`). No fetch: the crests are already on the PC.
The crests themselves are never published by the public build (docs/HOSTING_MIGRATION.md, D6), so the colours are
derived on the PC and committed as a small table, data/club_colours.json, which the build (PC or CI) reads. A club
with no crest, a national team, or a crest with no usable colour gets nothing, and the kit falls back to cobalt v
slate.

Refresh after new crests land (fetch_crests.py does it at the end of a run):

    python -m oddsmarkets.football.analytics.colours
"""
from __future__ import annotations

import colorsys
import json
import math
import re
import sys
from pathlib import Path

TABLE = Path(__file__).parent / "data" / "club_colours.json"
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


def refresh(crests_dir: Path = CRESTS_DIR, table: Path = TABLE) -> dict[str, list]:
    """Re-derive every crest's colours and write the table ({tid: [colour, alt]}, sorted by id)."""
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
    table.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(f'"{k}":{json.dumps(v)}' for k, v in out.items())
    table.write_text("{\n" + body + "\n}\n", encoding="utf-8")
    return out


_CACHE: dict[Path, dict[str, list]] = {}


def load(table: Path = TABLE) -> dict[str, list]:
    """The committed table ({tid: [colour, alt]}); empty when it is missing."""
    if table not in _CACHE:
        try:
            _CACHE[table] = json.loads(table.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE[table] = {}
    return _CACHE[table]


def club(tid, table: Path = TABLE) -> dict[str, str]:
    """{"colour": ..., "alt": ...} for a club id (only the keys that are known)."""
    row = load(table).get(str(tid)) or [None, None]
    return {k: v for k, v in zip(("colour", "alt"), row) if v}


if __name__ == "__main__":
    rows = refresh(Path(sys.argv[1]) if len(sys.argv) > 1 else CRESTS_DIR)
    n_alt = sum(1 for v in rows.values() if v[1])
    print(f"{len(rows)} clubs with a colour ({n_alt} with an alternate) -> {TABLE}")
