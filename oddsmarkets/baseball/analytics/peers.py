"""Small per-season files for the player page, so it needs no 4-7 MB catalogue.

peers.json (`data/<L>/<S>/peers.json`): the distribution ("Among peers") values of every peer group, the same groups and
floors as the page's sets (docs/_design/metrics/baseball.json): hitters by position (C, 1B, 2B, 3B, SS, CF, LF/RF, DH,
and ALL = every hitter), pitchers by role (SP, RP); a player counts once he reaches the group's minimum prorated by the
season's team games (200 PA; 300 BF starters, 120 BF relievers). Shape:

    {"ok", "level", "season", "team_games", "metrics": {"hitter": [...], "pitcher": [...]},
     "groups": {set: {"kind", "n", "floor": {"field", "value", "unit"}, <metric>: [sorted values], ...}}}

so `groups[set][metric]` is the sorted list the distribution chart draws (players without the metric are left out).

league_types.json (`data/<L>/<S>/league_types.json`): pitchers.json `league_types` alone ({pitch type: {n, usage, whiff,
csw, xwoba, stuff, velo, ivb, hb, spin, vaa}}, about 2 KB), the league average per pitch type for the movement chart.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.baseball import analytics as an

# the page's "Among peers" metrics (docs/bullpen/assets/js/bp-player.js DIST) plus each set's headline rates
DIST = {"hitter": ["xwoba_n", "war_600", "barrel_pct", "k_pct", "chase_pct", "woba", "hard_pct", "bb_pct", "bat_speed",
                   "sprint_speed", "iso"],
        "pitcher": ["xwoba_n", "stuff_plus", "k_bb_pct", "csw_pct", "xfip", "pitching_plus", "fb_velo", "k_pct", "bb_pct",
                    "gb_pct", "whiff_pct"]}
POS_SET = {"C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS", "CF": "CF", "LF": "LF/RF", "RF": "LF/RF", "OF": "LF/RF",
           "LF/RF": "LF/RF", "DH": "DH", "TWP": "DH"}
FLOORS = {"hitter": ("pa", 200.0, "PA"), "SP": ("bf", 300.0, "BF"), "RP": ("bf", 120.0, "BF")}


def set_of(kind: str, row: dict) -> str:
    """The page's set key for a catalogue row (bp-ui.js U.setFor): pitchers by role, hitters by position, else ALL."""
    if kind == "pitcher":
        return "RP" if str(row.get("role") or "").upper() == "RP" else "SP"
    return POS_SET.get(str(row.get("pos") or "").upper(), "ALL")


def floor_of(kind: str, set_key: str, team_games: Any) -> tuple[str, int, str]:
    field, full, unit = FLOORS["hitter" if kind == "hitter" else set_key]
    tg = an.fnum(team_games)
    tg = min(162.0, tg) if tg and tg > 0 else 162.0
    return field, max(1, int(round(full * tg / 162.0))), unit


def _sample(row: dict, field: str) -> float | None:
    for src in (row.get("n") or {}, row.get("values") or {}, row):
        v = an.fnum(src.get(field)) if isinstance(src, dict) else None
        if v is not None:
            return v
    return None


def build(hit: dict | None, pit: dict | None, level: str, season: int) -> dict:
    groups: dict[str, dict] = {}
    tg = (hit or {}).get("team_games") or (pit or {}).get("team_games")
    for kind, cat in (("hitter", hit), ("pitcher", pit)):
        rows = ((cat or {}).get("players")) or {}
        members: dict[str, list[dict]] = {}
        for r in rows.values():
            sk = set_of(kind, r)
            field, need, _ = floor_of(kind, sk, (cat or {}).get("team_games") or tg)
            if (_sample(r, field) or 0) < need:
                continue
            members.setdefault(sk, []).append(r)
            if kind == "hitter" and sk != "ALL":
                members.setdefault("ALL", []).append(r)
        for sk, mem in members.items():
            field, need, unit = floor_of(kind, sk, (cat or {}).get("team_games") or tg)
            g: dict[str, Any] = {"kind": kind, "n": len(mem), "floor": {"field": field, "value": need, "unit": unit}}
            for k in DIST[kind]:
                vals = sorted(an.rnd(v, 4) for v in (an.fnum((r.get("values") or {}).get(k)) for r in mem) if v is not None)
                if vals:
                    g[k] = vals
            groups[sk] = g
    return {"ok": bool(groups), "level": level, "season": int(season), "team_games": tg, "metrics": dict(DIST), "groups": groups,
            "updated_at": an.now()}


def league_types(pit: dict | None, level: str, season: int) -> dict:
    lt = (pit or {}).get("league_types") or {}
    return {"ok": bool(lt), "level": level, "season": int(season), "league_types": lt, "updated_at": an.now()}


def own_types(league: dict | None, arsenal: dict | None) -> dict | None:
    """league_types restricted to the pitch types in a pitcher's arsenal (for his player file's current block)."""
    if not league or not arsenal:
        return None
    out = {t: league[t] for t in arsenal if t != "all" and t in league}
    return out or None
