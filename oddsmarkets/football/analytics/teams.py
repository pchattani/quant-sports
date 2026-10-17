"""
Per-team match statistics and season aggregates from the store's team-stat sheets.

A match with the full detail carries Sofascore's whole-match team statistics;
one fetched in the older format carries only what the lineups imply (xG as the
sum of its players' xG). Rows are emitted for both, with the missing columns
null, so the season means are over whatever is known.
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.football.sources.teams import normalize_team_name

# Team-stat keys (Sofascore) -> row columns. Ratio stats carry a `<key>_total`
# alongside, from which the success rate is derived below.
STAT_COLUMNS = {
    "ballPossession": "poss", "expectedGoals": "xg", "expectedGoalsOnTarget": "xgot",
    "totalShotsOnGoal": "shots", "shotsOnGoal": "sot", "shotsOffGoal": "shots_off",
    "blockedScoringAttempt": "shots_blocked", "totalShotsInsideBox": "shots_in",
    "totalShotsOutsideBox": "shots_out", "bigChanceCreated": "big_chances",
    "bigChanceScored": "big_chances_scored", "bigChanceMissed": "big_chances_missed",
    "cornerKicks": "corners", "offsides": "offsides", "fouls": "fouls", "yellowCards": "yellow",
    "redCards": "red", "passes": "passes", "accuratePasses": "passes_acc",
    "touchesInOppBox": "box_touches", "finalThirdEntries": "final_third",
    "accurateLongBalls": "long_balls", "accurateCross": "crosses", "accurateThroughBall": "through_balls",
    "totalTackle": "tackles", "wonTacklePercent": "tackles_won", "interceptionWon": "interceptions",
    "ballRecovery": "recoveries", "totalClearance": "clearances", "errorsLeadToShot": "errors",
    "duelWonPercent": "duel_pct", "groundDuelsPercentage": "ground_won", "aerialDuelsPercentage": "aerial_won",
    "dribblesPercentage": "dribbles", "dispossessed": "dispossessed",
    "goalkeeperSaves": "saves", "goalsPrevented": "goals_prevented", "diveSaves": "big_saves",
    "kilometersCovered": "km", "numberOfSprints": "sprints", "avgRating": "rating",
    "freeKicks": "free_kicks", "throwIns": "throw_ins", "goalKicks": "goal_kicks",
}
TOTAL_COLUMNS = {
    "accurateLongBalls": "long_balls_att", "accurateCross": "crosses_att",
    "wonTacklePercent": "tackles_att", "groundDuelsPercentage": "ground_total",
    "aerialDuelsPercentage": "aerial_total", "dribblesPercentage": "dribbles_att",
}

# Season aggregates shown on team pages; `lower` marks where less is better.
TEAM_METRICS: list[dict[str, Any]] = [
    {"key": "xg", "label": "xG per match", "fmt": "2"},
    {"key": "xga", "label": "xG against per match", "fmt": "2", "lower": True},
    {"key": "xg_diff", "label": "xG difference per match", "fmt": "2"},
    {"key": "gf", "label": "Goals per match", "fmt": "2"},
    {"key": "ga", "label": "Goals against per match", "fmt": "2", "lower": True},
    {"key": "shots", "label": "Shots per match", "fmt": "1"},
    {"key": "shots_ag", "label": "Shots faced per match", "fmt": "1", "lower": True},
    {"key": "sot", "label": "Shots on target per match", "fmt": "1"},
    {"key": "xg_per_shot", "label": "xG per shot", "fmt": "2"},
    {"key": "poss", "label": "Possession", "fmt": "pct"},
    {"key": "pass_pct", "label": "Pass completion", "fmt": "pct"},
    {"key": "passes", "label": "Passes per match", "fmt": "int"},
    {"key": "box_touches", "label": "Touches in the box per match", "fmt": "1"},
    {"key": "final_third", "label": "Final-third entries per match", "fmt": "1"},
    {"key": "big_chances", "label": "Big chances per match", "fmt": "2"},
    {"key": "corners", "label": "Corners per match", "fmt": "1"},
    {"key": "tackles", "label": "Tackles per match", "fmt": "1"},
    {"key": "interceptions", "label": "Interceptions per match", "fmt": "1"},
    {"key": "recoveries", "label": "Recoveries per match", "fmt": "1"},
    {"key": "clearances", "label": "Clearances per match", "fmt": "1"},
    {"key": "aerial_pct", "label": "Aerial duels won", "fmt": "pct"},
    {"key": "ground_pct", "label": "Ground duels won", "fmt": "pct"},
    {"key": "fouls", "label": "Fouls per match", "fmt": "1", "lower": True},
    {"key": "km", "label": "Distance covered (km)", "fmt": "1"},
    {"key": "sprints", "label": "Sprints per match", "fmt": "int"},
    {"key": "rating", "label": "Average rating", "fmt": "2"},
    {"key": "conv", "label": "Shot conversion", "fmt": "pct"},
    {"key": "save_pct", "label": "Save %", "fmt": "pct"},
]

_MEAN_KEYS = (
    "xg", "xga", "gf", "ga", "shots", "shots_ag", "sot", "sot_ag", "poss", "passes", "passes_acc",
    "box_touches", "final_third", "big_chances", "corners", "tackles", "interceptions", "recoveries",
    "clearances", "fouls", "km", "sprints", "rating", "long_balls", "long_balls_att", "crosses",
    "crosses_att", "aerial_won", "aerial_total", "ground_won", "ground_total", "saves", "goals_prevented",
    "yellow", "red", "xgot", "xgot_ag", "dribbles", "dribbles_att", "errors", "offsides",
)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def team_match_stats(store: dict[str, Any], registry="liga_argentina", xg_by_match: dict | None = None) -> dict[str, list[dict]]:
    """Team -> match rows (newest first) with the team's numbers and its opponent's shooting."""
    matches = store.get("matches") or {}
    sheets = store.get("team_stats") or {}
    lineups = store.get("lineups") or {}
    out: dict[str, list[dict]] = {}
    for gid in set(sheets) | set(lineups):
        meta = matches.get(str(gid)) or {}
        if meta.get("status") != "finished" or meta.get("hs") is None:
            continue
        home = normalize_team_name(str(meta.get("home", "")), registry)
        away = normalize_team_name(str(meta.get("away", "")), registry)
        if not home or not away:
            continue
        sheet = sheets.get(str(gid)) or {}
        fallback = (xg_by_match or {}).get(str(gid))
        sides = {"home": {}, "away": {}}
        for side in ("home", "away"):
            raw = sheet.get(side) or {}
            row: dict[str, Any] = {}
            for key, col in STAT_COLUMNS.items():
                if raw.get(key) is not None:
                    row[col] = raw[key]
            for key, col in TOTAL_COLUMNS.items():
                if raw.get(key + "_total") is not None:
                    row[col] = raw[key + "_total"]
            if row.get("xg") is None and fallback:
                row["xg"] = fallback[0 if side == "home" else 1]
            sides[side] = row
        for side, team, opp_side in (("home", home, "away"), ("away", away, "home")):
            mine, theirs = sides[side], sides[opp_side]
            gf, ga = (meta["hs"], meta["as"]) if side == "home" else (meta["as"], meta["hs"])
            row = {
                "gid": str(gid), "date": meta.get("date"), "round": meta.get("round"), "stage": meta.get("stage"),
                "opp": away if side == "home" else home, "ha": "H" if side == "home" else "A",
                "gf": gf, "ga": ga, "res": "W" if gf > ga else "D" if gf == ga else "L",
                **mine,
                "xga": theirs.get("xg"), "xgot_ag": theirs.get("xgot"),
                "shots_ag": theirs.get("shots"), "sot_ag": theirs.get("sot"),
            }
            row["has_sheet"] = bool(sheet)
            out.setdefault(team, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return out


def season_team_stats(by_team: dict[str, list[dict]]) -> dict[str, dict]:
    """Per-team means over the matches with a stat sheet, plus derived rates."""
    out: dict[str, dict] = {}
    for team, rows in by_team.items():
        sums: dict[str, float] = {}
        counts: dict[str, int] = {}
        for r in rows:
            for k in _MEAN_KEYS:
                v = _num(r.get(k))
                if v is None:
                    continue
                sums[k] = sums.get(k, 0.0) + v
                counts[k] = counts.get(k, 0) + 1
        agg: dict[str, Any] = {"matches": len(rows), "with_sheet": sum(1 for r in rows if r.get("has_sheet"))}
        for k in _MEAN_KEYS:
            agg[k] = round(sums[k] / counts[k], 3) if counts.get(k) else None
        agg["xg_diff"] = round(agg["xg"] - agg["xga"], 3) if agg.get("xg") is not None and agg.get("xga") is not None else None
        shots_n = sums.get("shots") or 0.0
        agg["xg_per_shot"] = round(sums["xg"] / shots_n, 3) if shots_n and counts.get("xg") else None
        agg["conv"] = round(100.0 * sums.get("gf", 0.0) / shots_n, 1) if shots_n else None
        agg["pass_pct"] = round(100.0 * sums["passes_acc"] / sums["passes"], 1) if sums.get("passes") else None
        agg["aerial_pct"] = round(100.0 * sums["aerial_won"] / sums["aerial_total"], 1) if sums.get("aerial_total") else None
        agg["ground_pct"] = round(100.0 * sums["ground_won"] / sums["ground_total"], 1) if sums.get("ground_total") else None
        sot_ag = sums.get("sot_ag") or 0.0
        agg["save_pct"] = round(100.0 * (sot_ag - sums.get("ga", 0.0)) / sot_ag, 1) if sot_ag and counts.get("sot_ag") else None
        # Totals a table wants alongside the means.
        agg["xg_total"] = round(sums.get("xg", 0.0), 2)
        agg["xga_total"] = round(sums.get("xga", 0.0), 2)
        agg["gf_total"] = int(sums.get("gf", 0))
        agg["ga_total"] = int(sums.get("ga", 0))
        out[team] = agg
    # Percentiles within the competition for the catalogue metrics.
    for m in TEAM_METRICS:
        vals = sorted(v for v in (agg.get(m["key"]) for agg in out.values()) if v is not None)
        if len(vals) < 3:
            continue
        for agg in out.values():
            v = agg.get(m["key"])
            if v is None:
                continue
            below = sum(1 for x in vals if x < v)
            ties = sum(1 for x in vals if x == v)
            rank = (below + 0.5 * ties) / len(vals)
            if m.get("lower"):
                rank = 1.0 - rank
            agg.setdefault("pct", {})[m["key"]] = int(round(100 * rank))
    return out
