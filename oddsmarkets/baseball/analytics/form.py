"""
data/<L>/<S>/form.json: who is hot and who is cold (round 9). The current season's player blocks carry each hitter's rolling
xwOBA+ over the last 100 plate appearances (careers.current_blocks "rolling": [[date, xwOBA+, wOBA]]) and each pitcher's
rolling Pitching+ over the last 500 pitches ("pitching_rolling": [[date, pitches, Stuff+, Location+, Pitching+, rolling
Pitching+]]). Form is the latest rolling value against the player's own season figure from the catalogue (hitters with
250+ PA, pitchers with 1,500+ pitches' worth of season: starters 300+ batters faced, relievers 150+), so a player is hot
against their own standard, not the league's. The rolling windows are what the contact or the pitches deserved, which
settle faster than results.

{"ok", "level", "season", "asof", "hitters": {"hot": [ROW], "cold": [ROW]}, "pitchers": {"hot": [...], "cold": [...]},
 ROW = {pid, name, team, pos, season, recent, delta, n, last (date), spark: [recent values, oldest first]}}
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an

TOP = 8
MIN_PA = 250
MIN_BF_SP, MIN_BF_RP = 300, 150


def _spark(rows: list, i: int, n: int = 12) -> list:
    return [an.rnd(r[i], 3) for r in rows[-n:] if isinstance(r, list) and len(r) > i and r[i] is not None]


def build(level: str, season: int, blocks: dict | None, hit: dict | None, pit: dict | None) -> dict | None:
    if not blocks:
        return None
    H = (hit or {}).get("players") or {}
    P = (pit or {}).get("players") or {}
    hrows, prows, last = [], [], ""
    for pid, b in blocks.items():
        pid = str(pid)
        roll = (b or {}).get("rolling")
        h = H.get(pid)
        if roll and h and (h.get("pa") or 0) >= MIN_PA:
            sv = an.fnum((h.get("values") or {}).get("xwoba_plus"))
            rv = an.fnum(roll[-1][1]) if len(roll[-1]) > 1 else None
            if sv is not None and rv is not None:
                last = max(last, str(roll[-1][0]))
                hrows.append({"pid": pid, "name": h.get("name"), "team": h.get("team"), "pos": h.get("pos"), "season": an.rnd(sv, 3),
                              "recent": an.rnd(rv, 3), "delta": an.rnd(rv - sv, 3), "n": h.get("pa"), "last": str(roll[-1][0]), "spark": _spark(roll, 1)})
        pr = (b or {}).get("pitching_rolling")
        p = P.get(pid)
        if pr and p:
            bf = (p.get("values") or {}).get("bf") or 0
            floor = MIN_BF_RP if str(p.get("role") or p.get("pos") or "").upper() == "RP" else MIN_BF_SP
            sv = an.fnum((p.get("values") or {}).get("pitching_plus"))
            rv = an.fnum(pr[-1][5]) if len(pr[-1]) > 5 else None
            if bf >= floor and sv is not None and rv is not None:
                last = max(last, str(pr[-1][0]))
                prows.append({"pid": pid, "name": p.get("name"), "team": p.get("team"), "pos": p.get("role") or p.get("pos"), "season": an.rnd(sv, 1),
                              "recent": an.rnd(rv, 1), "delta": an.rnd(rv - sv, 1), "n": bf, "last": str(pr[-1][0]), "spark": _spark(pr, 5)})
    if not hrows and not prows:
        return None

    def ends(rows: list) -> dict:
        rows = sorted(rows, key=lambda r: -(r["delta"] or 0))
        return {"hot": rows[:TOP], "cold": list(reversed(rows[-TOP:])) if len(rows) > TOP else []}
    return {"ok": True, "level": level, "season": season, "updated_at": an.now(), "asof": last or None,
            "rules": {"hitters": "rolling xwOBA+ over the last 100 plate appearances against the season's, 250+ PA",
                      "pitchers": "rolling Pitching+ over the last 500 pitches against the season's, starters 300+ batters faced, relievers 150+"},
            "hitters": ends(hrows), "pitchers": ends(prows)}
