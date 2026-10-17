"""
awards.json: the award races (`models/awards.py`: conditional-logit weights fitted on past winners,
projected to season end with the season simulation's win distributions) beside the prediction
markets, with the features behind each candidate and the eligibility flag (NBA 65-game rule).

Keys follow the markets: mvp, roy, dpoy, sixth (the model's "6moy"), mip, clutch (NBA only).
Also `career_awards`: {pid: [[season, award]]} for the winners the stores can resolve.
"""
from __future__ import annotations

import logging

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics.context import SeasonContext
from oddsmarkets.basketball.models import _io

logger = logging.getLogger(__name__)
MODEL_KEY = {"mvp": "mvp", "roy": "roy", "dpoy": "dpoy", "sixth": "6moy", "mip": "mip", "clutch": "clutch"}
LABELS = {"mvp": "Most Valuable Player", "roy": "Rookie of the Year", "dpoy": "Defensive Player of the Year",
          "sixth": "Sixth Man of the Year", "mip": "Most Improved Player", "clutch": "Clutch Player of the Year"}


def build(ctx: SeasonContext) -> dict:
    from oddsmarkets.basketball.models import awards as AWM
    sim = (ctx.sim or {}).get("teams") or {}
    team_wins = {t: {k: v.get(k) for k in ("exp_w", "w_p05", "w_p95")} for t, v in sim.items()} or None
    res = AWM.for_season(ctx.league, ctx.season, team_wins=team_wins)
    if not res.get("ok"):
        return {"ok": False, "reason": res.get("reason") or "award races unavailable", "league": ctx.league, "season": ctx.season}
    fut = ctx.futures or {}
    out = {"ok": True, "league": ctx.league, "season": ctx.season, "updated_at": an.now(), "labels": {}, "keys": []}
    for key, mk in MODEL_KEY.items():
        if key == "clutch" and ctx.league != "nba":
            continue
        if key == "sixth" and ctx.league == "wnba":
            out["labels"][key] = "Sixth Player of the Year"
        else:
            out["labels"][key] = LABELS[key]
        race = (res.get("races") or {}).get(mk) or {}
        feats = (res.get("features") or {}).get(mk) or {}
        market = fut.get(key) if isinstance(fut.get(key), dict) else None
        out["keys"].append(key)
        out[key] = {
            "model": {pid: an.rnd(v.get("p"), 4) for pid, v in race.items() if (v.get("p") or 0) > 0 or pid in feats},
            "p_top3": {pid: an.rnd(v.get("p_top3"), 4) for pid, v in race.items() if (v.get("p_top3") or 0) > 0},
            "market": _io.clean(market, 4) if market else None,
            "features": {pid: _io.clean(f, 3) for pid, f in feats.items()},
            "eligible": {pid: bool(v.get("can_qualify", True)) for pid, v in race.items()},
            "fit": {k: (res.get("models") or {}).get(mk, {}).get(k) for k in ("features", "weights", "n_seasons", "fitted", "top1")},
        }
        w = winner(ctx.league, mk, ctx.season, ctx.players)
        if w:
            out[key]["winner"] = w
    return out


def winner(league: str, award: str, season: int, players: dict) -> dict | None:
    """The announced winner(s) of a finished race ({"names": [...], "ids": [...]}, ids resolved by folded
    name among the season's players; a name the store cannot resolve keeps a null id), or None."""
    from oddsmarkets.basketball.models import award_winners as AW
    names = AW.winner_names(league, award, season) or []
    if not names:
        return None
    by: dict[str, str] = {}
    for pid, r in (players or {}).items():
        by.setdefault(_io.fold_name((r or {}).get("name") or ""), pid)
    return {"names": list(names), "ids": [by.get(_io.fold_name(n)) for n in names]}


def award_probs(payload: dict | None) -> dict[str, dict[str, float]]:
    """{award: {pid: p}} from an awards.json payload (for the player files)."""
    if not payload or not payload.get("ok"):
        return {}
    return {k: (payload.get(k) or {}).get("model") or {} for k in payload.get("keys") or []}


def career_awards(league: str, seasons: list[int], catalogues: dict[int, dict]) -> dict[str, list[list]]:
    """{pid: [[season, award]]} from the hand-entered winners resolved by name in each season's catalogue."""
    from oddsmarkets.basketball.models import award_winners as AW
    out: dict[str, list[list]] = {}
    for s in seasons:
        cat = catalogues.get(s) or {}
        by = {}
        for pid, r in (cat.get("players") or {}).items():
            by.setdefault(_io.fold_name(r.get("name") or ""), pid)
        for key, mk in MODEL_KEY.items():
            for name in AW.winner_names(league, mk, s) or []:
                pid = by.get(_io.fold_name(name))
                if pid:
                    out.setdefault(pid, []).append([s, key])
    return out
