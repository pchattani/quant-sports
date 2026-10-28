"""Copy The Quant design kit (docs/_design) into a site's assets, the way base.css is copied today.

    from design_kit import copy_kit
    copy_kit(DOCS / "rink")          # -> docs/rink/assets/qk/{tokens.css, quant.css, quant.js, quant-charts.js, plotly-ec.js,
                                     #    league.js, progression.js}
                                     #    and docs/rink/assets/qk/metrics/hockey.json

Every site build calls this once, so all sites ship the same kit version. The style guide
(docs/_design/index.html, guide.js) is not copied.

The site's metrics spec (docs/_design/metrics/<sport>.json, the machine-readable form of docs/METRICS_SPEC.md:
headline metrics, peer groups, minimums, year-to-year reliability) is copied to assets/qk/metrics/<sport>.json so
the front end can read it in the browser (fetch("assets/qk/metrics/hockey.json")). Only the site's own sport is
copied; the home page gets none.

Beside it goes assets/qk/metrics/<sport>.labels.json (a few KB, `labels()`): every metric's display name, unit,
direction, set, order, style flag and one-line explanation per entity, each peer group's headline ids in order, and
the `our_models` registry (which metrics come from our own models). Labs, leaderboards and tables read labels through
`QK.spec` (quant.js) so they match the spec without loading the full file.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1] / "docs" / "_design"
METRICS = DESIGN / "metrics"
# plotly-ec.js is optional on a page (window.Plotly on ECharts for views still written against Plotly) but is
# copied everywhere so any site can load it without its own copy.
# league.js (QKL) draws the season payload's "league" block on the US sports' standings and team pages
# (oddsmarkets/common/league.py); a page that does not load it is unaffected.
# progression.js (QKC.progression, QK.progressionGrid, QK.compareProgression ...: round 6) draws a player's career season by
# season against the peers (oddsmarkets/common/progression.py); a page that does not load it is unaffected.
KIT_FILES = ["tokens.css", "quant.css", "quant.js", "quant-charts.js", "plotly-ec.js", "league.js", "progression.js"]
# site folder (docs/<folder>) -> the sport of its metrics file (docs/_design/metrics/<sport>.json)
SITE_SPORT = {
    "site": "football",
    "paddock": "f1",
    "hardwood": "basketball",
    "ace": "tennis",
    "bullpen": "baseball",
    "gridiron": "nfl",
    "rink": "hockey",
    "campus": "college",
}


def metrics_files(site_dir: Path) -> list[Path]:
    """The metrics spec file(s) a site ships: its own sport's, or none (home, unknown folders)."""
    sport = SITE_SPORT.get(Path(site_dir).name)
    if sport is None:
        return []
    src = METRICS / f"{sport}.json"
    return [src] if src.exists() else []


def copy_kit(site_dir: Path, sub: str = "assets/qk") -> Path:
    dst = Path(site_dir) / sub
    dst.mkdir(parents=True, exist_ok=True)
    for f in KIT_FILES:
        shutil.copyfile(DESIGN / f, dst / f)
    mfiles = metrics_files(site_dir)
    if mfiles:
        (dst / "metrics").mkdir(exist_ok=True)
        for src in mfiles:
            shutil.copyfile(src, dst / "metrics" / src.name)
            text = json.dumps(labels(json.loads(src.read_text(encoding="utf-8"))), ensure_ascii=False, separators=(",", ":"))
            (dst / "metrics" / f"{src.stem}.labels.json").write_text(text + "\n", encoding="utf-8")
    return dst


def labels(spec: dict) -> dict:
    """The compact labels file from a sport's metrics spec: {"sport", "generated", "ours": {"models": {key: {name,
    about}}, "metrics": {id: model key}}, "m": {entity: {id: [display, unit, direction, set ("h"/"s"), order, style
    (0/1), explanation]}}, "groups": [{"id", "display", "entity", "headline": [ids in order], "field"?, "codes"?,
    "min"?: {"field", "value", "unit"}}]} (field/codes: the payload field and codes of the peer group; min: the spec's
    minimum sample). A metric id that
    appears in several groups of one entity keeps the first headline entry (else the first entry)."""
    m: dict = {}
    groups = []
    for g in spec.get("groups") or []:
        ent = g.get("entity") or "player"
        tab = m.setdefault(ent, {})
        heads = []
        for x in g.get("metrics") or []:
            mid = x.get("id")
            if not mid:
                continue
            head = x.get("set") == "headline"
            if head:
                heads.append((x.get("order") or 99, mid))
            row = [x.get("display") or mid, x.get("unit") or "", x.get("direction") or "higher", "h" if head else "s",
                   x.get("order") or 99, 1 if x.get("style") else 0, x.get("explanation") or ""]
            if mid not in tab or (head and tab[mid][3] != "h"):
                tab[mid] = row
        groups.append({"id": g.get("id"), "display": g.get("display") or g.get("id"), "entity": ent,
                       "headline": [i for _o, i in sorted(heads, key=lambda t: t[0])]})
        for k in ("league", "tour", "surface"):
            if g.get(k):
                groups[-1][k] = g[k]
        # the peer group itself, for the Labs' "Compare within: Position" (QK.within): the payload field and codes
        # that place a row in the group, and the spec's minimum sample
        if g.get("position_field") and g.get("position_codes"):
            groups[-1]["field"] = g["position_field"]
            groups[-1]["codes"] = list(g["position_codes"])
        mn = g.get("minimum") or {}
        if mn.get("field") and mn.get("value") is not None:
            groups[-1]["min"] = {"field": mn["field"], "value": mn["value"], "unit": mn.get("unit") or ""}
    ours = spec.get("our_models") or {}
    return {"sport": spec.get("sport"), "generated": spec.get("generated"),
            "ours": {"models": ours.get("models") or {}, "metrics": ours.get("metrics") or {}}, "m": m, "groups": groups}


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        print(copy_kit(Path(d)))
