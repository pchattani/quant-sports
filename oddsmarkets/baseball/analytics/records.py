"""
data/<L>/<S>/chases.json: on pace for history (round 9). The season's leaders in the counting stats that have famous
single-season records (home runs, stolen bases, hits, walks, doubles; strikeouts, wins, saves), set against the top 15
American and National League seasons since 1901 (season_records.json, from the Lahman Baseball Database, CC BY-SA 3.0,
scripts/mlb_season_records.py). While the regular season runs a leader's total is projected to 162 team games at the
same rate ("on pace for"); once it is over the total is final. MLB only.

{"ok", "season", "final": bool, "team_games", "source", "stats": {key: {label, kind, record: [name, year, value],
 list_min, leaders: [{pid, name, team, value, pace, rank (where the pace would rank since 1901, null when outside the
 top 15), behind (the record minus the pace)}]}}}
"""
from __future__ import annotations

import json
from pathlib import Path

from oddsmarkets.baseball import analytics as an

RECORDS = Path(__file__).with_name("season_records.json")
SCHEDULE = 162
LEADERS = 3


def build(season: int, hit: dict | None, pit: dict | None, phase: str | None) -> dict | None:
    try:
        rec = json.loads(RECORDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tg = max((hit or {}).get("team_games") or 0, (pit or {}).get("team_games") or 0)
    if not tg:
        return None
    final = str(phase or "") not in ("regular", "preseason") or tg >= SCHEDULE
    scale = 1.0 if final else SCHEDULE / tg
    out = {}
    for key, spec in (rec.get("stats") or {}).items():
        cat = (hit if spec.get("kind") == "hitter" else pit) or {}
        rows = []
        for pid, r in (cat.get("players") or {}).items():
            v = an.fnum((r.get("values") or {}).get(key))
            if v is not None and v > 0:
                rows.append((v, pid, r))
        rows.sort(key=lambda x: -x[0])
        top = spec.get("top") or []
        if not rows or not top:
            continue
        vals = [t[2] for t in top]
        leaders = []
        for v, pid, r in rows[:LEADERS]:
            pace = round(v * scale, 1)
            rank = 1 + sum(1 for x in vals if x > pace) if pace >= vals[-1] else None
            leaders.append({"pid": str(pid), "name": r.get("name"), "team": r.get("team"), "value": int(round(v)), "pace": pace,
                            "rank": rank, "behind": round(vals[0] - pace, 1)})
        out[key] = {"label": spec.get("label"), "kind": spec.get("kind"), "record": top[0], "list_min": vals[-1], "top": top[:5], "leaders": leaders}
    if not out:
        return None
    return {"ok": True, "season": season, "updated_at": an.now(), "final": final, "team_games": tg, "source": rec.get("source"), "stats": out}
