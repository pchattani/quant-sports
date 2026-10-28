"""
The Ace's tour page (rankings): top and bottom performers, data/<T>/performers.json, from the season's catalogue
(data/<T>/players.json; oddsmarkets/common/performers.py writes the shape, the kit's QKL.leaders draws it).

    build(cat, tour) -> the document, or None when nobody qualifies

Tennis has no positions, so the views are the spec's groups (docs/_design/metrics/tennis.json): all surfaces
(<tour>_all: our Elo first, then hold, break and the tour-wide numbers) and each surface (<tour>_hard, _clay,
_grass: the surface Elo first, then that surface's hold, break and win rates). Qualified players only: the
catalogue's `qualified` flag for all surfaces (tour-level main-draw matches over the season's floor) and, on a
surface, the catalogue's `surface_floor` matches on it (values_surface is written from half the floor, so the
floor is checked here). A player's row carries the country as its team (the mark beside the name). Season to date:
no look-ahead.
"""
from __future__ import annotations

from oddsmarkets.common import performers as P

SURFACES = (("hard", "Hard"), ("clay", "Clay"), ("grass", "Grass"))
# QKL.fmtVal codes
FMT = {"elo": "0", "elo_hard": "0", "elo_clay": "0", "elo_grass": "0", "games_won_pct": "pct1", "hold": "pct1", "brk": "pct1",
       "win_v_top50": "pct0", "win_pct": "pct1", "dominance": "2", "ace_pct": "pct1"}
ELO_KEYS = ("elo", "elo_hard", "elo_clay", "elo_grass")


def _num(x):
    return P.num(x)


def _metrics(spec: dict, gid: str) -> list[dict]:
    """The group's headline set; an Elo needs no unit beside it, and the overall one reads "Overall Elo" (the page
    lower-cases a label's first letter mid-sentence: "on overall Elo")."""
    ms = P.spec_metrics(spec, gid, fmt=FMT)
    for m in ms:
        if m["key"] in ELO_KEYS:
            m["unit"] = ""
            if m["key"] == "elo":
                m["label"] = "Overall Elo"
    return ms


def build(cat: dict | None, tour: str) -> dict | None:
    if not cat or cat.get("ok") is False:
        return None
    spec = P.load_spec("tennis")
    players = cat.get("players") or {}
    sfloor = cat.get("surface_floor") or {}
    floor = cat.get("floor")
    rows_all, rows_s = [], {s: [] for s, _ in SURFACES}
    for pid, p in players.items():
        if not isinstance(p, dict):
            continue
        base = p.get("values") or {}
        row = {"id": str(pid), "name": p.get("name") or "", "team": p.get("country") or ""}
        if p.get("qualified"):
            rows_all.append({**row, "v": base})
        for s, _lbl in SURFACES:
            vs = (p.get("values_surface") or {}).get(s) or {}
            fl = sfloor.get(s)
            if fl is None or (_num(vs.get("matches")) or 0) < fl:
                continue
            # the surface's own numbers, with the Elo ratings (overall and by surface) from the season row
            rows_s[s].append({**row, "v": {**{k: base.get(k) for k in ELO_KEYS}, **vs}})
    t = str(tour).lower()
    peer = "players"
    views = [P.view("all", "All surfaces", rows_all, _metrics(spec, f"{t}_all"), peer=peer,
                    min_text=f"{floor} tour-level main-draw matches this season" if floor else "the season's match floor")]
    for s, lbl in SURFACES:
        fl = sfloor.get(s)
        views.append(P.view(s, lbl, rows_s[s], _metrics(spec, f"{t}_{s}"), peer=f"players on {s}",
                            min_text=f"{fl} tour-level matches on {s} this season" if fl else ""))
    doc = P.document(views, tour=t, year=cat.get("year"), updated_at=cat.get("updated_at"))
    return doc if doc["views"] else None
