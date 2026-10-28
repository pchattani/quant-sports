"""
data/mlb/award_history.json: the award winners against our pre-vote calls (round 9, Standings > Races).

Past seasons come from the committed walk-forward calls (models/fitted/award_calls_mlb.json, scripts/mlb_award_calls.py:
each season's award model fitted only on the earlier seasons' verified winners, scoring that season's full regular-season
lines). The current season adds our call from its awards.json once its regular season is over (the winners are announced
in November: until then the entry has no winner).

{"ok", "updated_at", "method", "source", "labels": {key: label},
 "seasons": {S: {key: {winner: {pid, name, p, rank} | null, pick: {pid, name, p}, top: [[pid, name, p]], n}}},
 "summary": {n, top_pick_won, winner_in_top3, mean_p_winner, by_award: {mvp|cy|roy: {n, top_pick_won}}}}
"""
from __future__ import annotations

import json
from pathlib import Path

from oddsmarkets.baseball import analytics as an

CALLS = Path(__file__).resolve().parent.parent / "models" / "fitted" / "award_calls_mlb.json"
LABELS = {"al_mvp": "AL MVP", "nl_mvp": "NL MVP", "al_cy": "AL Cy Young", "nl_cy": "NL Cy Young", "al_roy": "AL Rookie of the Year",
          "nl_roy": "NL Rookie of the Year"}


def build(current: int | None = None, current_awards: dict | None = None, regular_over: bool = False) -> dict | None:
    try:
        calls = json.loads(CALLS.read_text(encoding="utf-8")) if CALLS.exists() else None
    except (OSError, ValueError):
        calls = None
    if not calls:
        return None
    seasons = dict(calls.get("seasons") or {})
    if current and regular_over and str(current) not in seasons and isinstance(current_awards, dict):
        cur = {}
        for key, rec in ((current_awards.get("awards") or {}).items()):
            rows = (rec or {}).get("rows") or []
            if not rows:
                model = (rec or {}).get("model") or {}
                rows = [{"pid": k, "p": v} for k, v in sorted(model.items(), key=lambda kv: -kv[1])]
            if not rows:
                continue
            top = [[str(r.get("pid")), r.get("name"), round(float(r.get("p") or 0), 4)] for r in rows[:5]]
            cur[key] = {"winner": None, "pick": {"pid": top[0][0], "name": top[0][1], "p": top[0][2]}, "top": top, "n": len(rows)}
        if cur:
            seasons[str(current)] = cur
    n = hit = top3 = 0
    ps: list[float] = []
    by: dict[str, dict] = {}
    for s, recs in seasons.items():
        for key, r in recs.items():
            w = r.get("winner")
            if not w:
                continue
            n += 1
            won = w.get("rank") == 1
            hit += int(won)
            top3 += int((w.get("rank") or 99) <= 3)
            ps.append(float(w.get("p") or 0))
            b = by.setdefault(key.split("_", 1)[1], {"n": 0, "top_pick_won": 0})
            b["n"] += 1
            b["top_pick_won"] += int(won)
    return {"ok": True, "updated_at": an.now(), "method": calls.get("method"), "source": calls.get("source"), "labels": LABELS,
            "seasons": seasons,
            "summary": {"n": n, "top_pick_won": hit, "winner_in_top3": top3, "mean_p_winner": round(sum(ps) / len(ps), 3) if ps else None,
                        "by_award": by}}
