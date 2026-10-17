"""
Per-match detail for match pages: lineups with each player's line, the team-stat
sheet, shots, momentum, incidents and ratings.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.football.analytics.players import LOG_KEYS, positions_from_store, short_num
from oddsmarkets.football.sources.teams import normalize_team_name

# Columns kept on a lineup entry (a subset of the match-log columns).
LINEUP_KEYS = (
    "min", "rt", "g", "a", "xg", "xa", "sh", "sot", "kp", "bc", "pa", "pt", "tch", "dw", "dl",
    "tk", "tw", "int", "clr", "rec", "aw", "al", "drw", "dra", "fl", "fld", "sv", "gp", "km", "spr", "ts",
    "xgot", "crs", "crst", "lb", "lbt", "pc", "dis", "pl", "blk", "svib",
)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def match_details(store: dict[str, Any], limit_ratings: int = 30, registry="liga_argentina") -> dict[str, dict]:
    """Per-match momentum, incidents, shots, lineups, team stats and ratings, keyed by game_id."""
    out: dict[str, dict] = {}
    matches = store.get("matches") or {}
    sheets = store.get("team_stats") or {}
    extras_all = store.get("lineup_extras") or {}
    positions = positions_from_store(store)
    for gid, players in (store.get("lineups") or {}).items():
        meta = matches.get(str(gid), {})
        home = normalize_team_name(str(meta.get("home", "")), registry)
        away = normalize_team_name(str(meta.get("away", "")), registry)
        ratings = []
        lineups: dict[str, list[dict]] = {"home": [], "away": []}
        xg = {"home": 0.0, "away": 0.0}
        if isinstance(players, dict):
            for pid, p in players.items():
                if not isinstance(p, dict):
                    continue
                s = p.get("s") or {}
                team = normalize_team_name(str(p.get("t", "")), registry)
                side = "home" if team == home else "away"
                xg[side] += _f(s.get("expectedGoals"))
                entry: dict[str, Any] = {
                    "id": str(pid), "n": p.get("n", ""), "pos": p.get("p") or positions.get(str(pid)),
                    "no": p.get("no"), "start": not p.get("sub"), "cap": bool(p.get("cap")),
                }
                for stat, short in LOG_KEYS.items():
                    if short in LINEUP_KEYS and s.get(stat) is not None:
                        entry[short] = short_num(s[stat])
                lineups[side].append(entry)
                if s.get("minutesPlayed") and s.get("rating"):
                    ratings.append({
                        "id": str(pid), "name": p.get("n", ""), "team": team,
                        "rating": float(s["rating"]), "goals": int(_f(s.get("goals"))),
                        "xg": round(_f(s.get("expectedGoals")), 2), "minutes": int(_f(s.get("minutesPlayed"))),
                    })
        for side in lineups:
            # Starters first, goalkeeper on top, then by line; within a line the
            # source's order is kept (Sofascore lists each line right to left), which
            # is what lets the page draw the formation. Substitutes by minutes.
            lineups[side].sort(key=lambda e: (not e["start"], {"G": 0, "D": 1, "M": 2, "F": 3}.get(e.get("pos") or "", 4),
                                              0.0 if e["start"] else -_f(e.get("min"))))
        ratings.sort(key=lambda r: -r["rating"])
        incidents = []
        for inc in (store.get("incidents") or {}).get(str(gid), []) or []:
            if not isinstance(inc, dict):
                continue
            rec = dict(inc)
            if rec.get("is_home") is None:
                rec["is_home"] = normalize_team_name(str(rec.get("team", "")), registry) == home
            for k in ("country", "tournament", "season", "week", "game_id"):
                rec.pop(k, None)
            incidents.append(rec)
        incidents.sort(key=lambda i: (_f(i.get("time")), _f(i.get("added_time"))))
        sheet = sheets.get(str(gid)) or {}
        extras = extras_all.get(str(gid)) or {}
        out[str(gid)] = {
            "id": str(gid), "home": home, "away": away, "hs": meta.get("hs"), "as": meta.get("as"),
            "round": meta.get("round"), "stage": meta.get("stage"), "torneo": meta.get("torneo"),
            "date": meta.get("date"), "status": meta.get("status"), "group": meta.get("group"),
            "xg": [round(xg["home"], 2), round(xg["away"], 2)] if players else None,
            "momentum": (store.get("momentum") or {}).get(str(gid), []),
            "incidents": incidents,
            "shots": (store.get("shots") or {}).get(str(gid), []),
            "ratings": ratings[:limit_ratings],
            "lineups": lineups,
            "formation": extras.get("formation") or {},
            "missing": extras.get("missing") or {},
            "team_stats": sheet if sheet else None,
        }
    return out
