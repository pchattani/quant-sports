"""
Per-player season aggregates, percentiles against positional peers, and match logs.

The metric catalogue (`METRICS`) is emitted with the payload so the front-end's
leaderboards, percentile sliders and match-log columns are data-driven: adding a
metric here adds it everywhere.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from oddsmarkets.football.sources.teams import normalize_team_name

# Sofascore credits a penalty with this much xG; non-penalty xG subtracts it.
PEN_XG = 0.79

POSITION_LABELS = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward"}

# Per-match stats summed across a player's matches (rating and top speed are not sums).
SUM_KEYS = (
    "minutesPlayed", "goals", "goalAssist", "expectedGoals", "expectedAssists",
    "expectedGoalsOnTarget", "totalShots", "onTargetScoringAttempt", "shotOffTarget",
    "blockedScoringAttempt", "hitWoodwork", "bigChanceCreated", "bigChanceMissed",
    "keyPass", "penaltyWon", "penaltyConceded", "penaltyMiss", "totalOffside",
    "accuratePass", "totalPass", "accurateOwnHalfPasses", "totalOwnHalfPasses",
    "accurateOppositionHalfPasses", "totalOppositionHalfPasses",
    "accurateLongBalls", "totalLongBalls", "accurateCross", "totalCross",
    "totalContest", "wonContest", "ballCarriesCount", "progressiveBallCarriesCount",
    "totalBallCarriesDistance", "totalProgressiveBallCarriesDistance",
    "totalProgression", "touches", "unsuccessfulTouch", "dispossessed", "possessionLostCtrl",
    "duelWon", "duelLost", "aerialWon", "aerialLost", "challengeLost",
    "totalTackle", "wonTackle", "interceptionWon", "totalClearance", "clearanceOffLine",
    "outfielderBlock", "ballRecovery", "fouls", "wasFouled", "errorLeadToAShot",
    "errorLeadToAGoal", "ownGoals",
    "saves", "savedShotsFromInsideTheBox", "goalsPrevented", "keeperSaveValue",
    "totalKeeperSweeper", "accurateKeeperSweeper", "goodHighClaim", "punches",
    "kilometersCovered", "metersCoveredRunningKm", "metersCoveredHighSpeedRunningKm",
    "metersCoveredSprintingKm", "numberOfSprints",
)

# Totals that also get a per-90 rate (`<key>_90`).
PER90 = (
    "goals", "npg", "assists", "xg", "npxg", "xa", "xgot", "shots", "sot", "key_passes",
    "big_chances", "passes", "opp_half_passes", "long_balls", "crosses", "dribbles",
    "carries", "prog_carries", "carry_dist", "touches", "dispossessed", "poss_lost",
    "tackles", "interceptions", "clearances", "blocks", "recoveries", "aerials_won",
    "duels_won", "fouls", "fouled", "km", "sprints", "hsr_km",
    "saves", "goals_prevented", "conceded", "sweeper", "high_claims",
)

# The catalogue. `scope`: out (outfield), gk, all. `fmt`: int, 1, 2, pct. `pct`
# says whether the metric is one of the percentile sliders; `lower` marks
# metrics where less is better.
METRICS: list[dict[str, Any]] = [
    # scoring
    {"key": "goals", "label": "Goals", "group": "Scoring", "fmt": "int", "scope": "out"},
    {"key": "goals_90", "label": "Goals /90", "group": "Scoring", "fmt": "2", "scope": "out", "pct": True},
    {"key": "npg", "label": "Non-penalty goals", "group": "Scoring", "fmt": "int", "scope": "out"},
    {"key": "npg_90", "label": "npG /90", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "xg", "label": "xG", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "xg_90", "label": "xG /90", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "npxg", "label": "Non-penalty xG", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "npxg_90", "label": "npxG /90", "group": "Scoring", "fmt": "2", "scope": "out", "pct": True},
    {"key": "xgot", "label": "xGOT", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "xgot_90", "label": "xGOT /90", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "g_minus_xg", "label": "Goals − xG", "group": "Scoring", "fmt": "2", "scope": "out", "pct": True},
    {"key": "shots", "label": "Shots", "group": "Scoring", "fmt": "int", "scope": "out"},
    {"key": "shots_90", "label": "Shots /90", "group": "Scoring", "fmt": "2", "scope": "out", "pct": True},
    {"key": "sot", "label": "Shots on target", "group": "Scoring", "fmt": "int", "scope": "out"},
    {"key": "sot_90", "label": "SoT /90", "group": "Scoring", "fmt": "2", "scope": "out"},
    {"key": "sot_pct", "label": "Shots on target %", "group": "Scoring", "fmt": "pct", "scope": "out", "pct": True},
    {"key": "xg_per_shot", "label": "xG per shot", "group": "Scoring", "fmt": "2", "scope": "out", "pct": True},
    {"key": "big_chances_missed", "label": "Big chances missed", "group": "Scoring", "fmt": "int", "scope": "out"},
    {"key": "pens", "label": "Penalty goals", "group": "Scoring", "fmt": "int", "scope": "out"},
    # creating
    {"key": "assists", "label": "Assists", "group": "Creating", "fmt": "int", "scope": "out"},
    {"key": "assists_90", "label": "Assists /90", "group": "Creating", "fmt": "2", "scope": "out"},
    {"key": "xa", "label": "xA", "group": "Creating", "fmt": "2", "scope": "out"},
    {"key": "xa_90", "label": "xA /90", "group": "Creating", "fmt": "2", "scope": "out", "pct": True},
    {"key": "key_passes", "label": "Key passes", "group": "Creating", "fmt": "int", "scope": "out"},
    {"key": "key_passes_90", "label": "Key passes /90", "group": "Creating", "fmt": "2", "scope": "out", "pct": True},
    {"key": "big_chances", "label": "Big chances created", "group": "Creating", "fmt": "int", "scope": "out"},
    {"key": "big_chances_90", "label": "Big chances /90", "group": "Creating", "fmt": "2", "scope": "out", "pct": True},
    # passing
    {"key": "passes", "label": "Passes", "group": "Passing", "fmt": "int", "scope": "all"},
    {"key": "passes_90", "label": "Passes /90", "group": "Passing", "fmt": "1", "scope": "all", "pct": True},
    {"key": "pass_pct", "label": "Pass completion", "group": "Passing", "fmt": "pct", "scope": "all", "pct": True},
    {"key": "opp_half_passes_90", "label": "Opp.-half passes /90", "group": "Passing", "fmt": "1", "scope": "out", "pct": True},
    {"key": "long_balls_90", "label": "Long balls /90", "group": "Passing", "fmt": "2", "scope": "all", "pct": True},
    {"key": "long_ball_pct", "label": "Long-ball accuracy", "group": "Passing", "fmt": "pct", "scope": "all", "pct": True},
    {"key": "crosses_90", "label": "Crosses /90", "group": "Passing", "fmt": "2", "scope": "out", "pct": True},
    {"key": "cross_pct", "label": "Cross accuracy", "group": "Passing", "fmt": "pct", "scope": "out"},
    # carrying
    {"key": "touches", "label": "Touches", "group": "Carrying", "fmt": "int", "scope": "all"},
    {"key": "touches_90", "label": "Touches /90", "group": "Carrying", "fmt": "1", "scope": "out", "pct": True},
    {"key": "dribbles", "label": "Dribbles completed", "group": "Carrying", "fmt": "int", "scope": "out"},
    {"key": "dribbles_90", "label": "Dribbles /90", "group": "Carrying", "fmt": "2", "scope": "out", "pct": True},
    {"key": "dribble_pct", "label": "Dribble success", "group": "Carrying", "fmt": "pct", "scope": "out", "pct": True},
    {"key": "carries_90", "label": "Carries /90", "group": "Carrying", "fmt": "1", "scope": "out"},
    {"key": "prog_carries_90", "label": "Progressive carries /90", "group": "Carrying", "fmt": "2", "scope": "out", "pct": True},
    {"key": "carry_dist_90", "label": "Carry distance /90 (m)", "group": "Carrying", "fmt": "int", "scope": "out"},
    {"key": "dispossessed_90", "label": "Dispossessed /90", "group": "Carrying", "fmt": "2", "scope": "out", "pct": True, "lower": True},
    {"key": "poss_lost_90", "label": "Possession lost /90", "group": "Carrying", "fmt": "1", "scope": "out", "pct": True, "lower": True},
    # defending
    {"key": "tackles", "label": "Tackles", "group": "Defending", "fmt": "int", "scope": "out"},
    {"key": "tackles_90", "label": "Tackles /90", "group": "Defending", "fmt": "2", "scope": "out", "pct": True},
    {"key": "tackle_pct", "label": "Tackle success", "group": "Defending", "fmt": "pct", "scope": "out", "pct": True},
    {"key": "interceptions", "label": "Interceptions", "group": "Defending", "fmt": "int", "scope": "out"},
    {"key": "interceptions_90", "label": "Interceptions /90", "group": "Defending", "fmt": "2", "scope": "out", "pct": True},
    {"key": "clearances_90", "label": "Clearances /90", "group": "Defending", "fmt": "2", "scope": "out", "pct": True},
    {"key": "blocks_90", "label": "Blocks /90", "group": "Defending", "fmt": "2", "scope": "out", "pct": True},
    {"key": "recoveries", "label": "Recoveries", "group": "Defending", "fmt": "int", "scope": "out"},
    {"key": "recoveries_90", "label": "Recoveries /90", "group": "Defending", "fmt": "2", "scope": "out", "pct": True},
    {"key": "errors", "label": "Errors leading to a shot", "group": "Defending", "fmt": "int", "scope": "all", "lower": True},
    # duels
    {"key": "duels_won", "label": "Duels won", "group": "Duels", "fmt": "int", "scope": "out"},
    {"key": "duels_won_90", "label": "Duels won /90", "group": "Duels", "fmt": "2", "scope": "out", "pct": True},
    {"key": "duel_pct", "label": "Duel success", "group": "Duels", "fmt": "pct", "scope": "out", "pct": True},
    {"key": "aerials_won_90", "label": "Aerials won /90", "group": "Duels", "fmt": "2", "scope": "out", "pct": True},
    {"key": "aerial_pct", "label": "Aerial success", "group": "Duels", "fmt": "pct", "scope": "out", "pct": True},
    {"key": "fouls_90", "label": "Fouls /90", "group": "Duels", "fmt": "2", "scope": "out", "pct": True, "lower": True},
    {"key": "fouled_90", "label": "Fouled /90", "group": "Duels", "fmt": "2", "scope": "out", "pct": True},
    # goalkeeping
    {"key": "saves", "label": "Saves", "group": "Goalkeeping", "fmt": "int", "scope": "gk"},
    {"key": "saves_90", "label": "Saves /90", "group": "Goalkeeping", "fmt": "2", "scope": "gk", "pct": True},
    {"key": "save_pct", "label": "Save %", "group": "Goalkeeping", "fmt": "pct", "scope": "gk", "pct": True},
    {"key": "goals_prevented", "label": "Goals prevented", "group": "Goalkeeping", "fmt": "2", "scope": "gk"},
    {"key": "goals_prevented_90", "label": "Goals prevented /90", "group": "Goalkeeping", "fmt": "2", "scope": "gk", "pct": True},
    {"key": "conceded", "label": "Goals conceded", "group": "Goalkeeping", "fmt": "int", "scope": "gk", "lower": True},
    {"key": "conceded_90", "label": "Conceded /90", "group": "Goalkeeping", "fmt": "2", "scope": "gk", "pct": True, "lower": True},
    {"key": "saves_in_box", "label": "Saves from inside the box", "group": "Goalkeeping", "fmt": "int", "scope": "gk"},
    {"key": "sweeper_90", "label": "Sweeper actions /90", "group": "Goalkeeping", "fmt": "2", "scope": "gk", "pct": True},
    {"key": "high_claims_90", "label": "High claims /90", "group": "Goalkeeping", "fmt": "2", "scope": "gk", "pct": True},
    {"key": "punches", "label": "Punches", "group": "Goalkeeping", "fmt": "int", "scope": "gk"},
    # physical
    {"key": "km", "label": "Distance (km)", "group": "Physical", "fmt": "1", "scope": "all"},
    {"key": "km_90", "label": "Distance /90 (km)", "group": "Physical", "fmt": "2", "scope": "out", "pct": True},
    {"key": "hsr_km_90", "label": "High-speed running /90 (km)", "group": "Physical", "fmt": "2", "scope": "out", "pct": True},
    {"key": "sprints", "label": "Sprints", "group": "Physical", "fmt": "int", "scope": "all"},
    {"key": "sprints_90", "label": "Sprints /90", "group": "Physical", "fmt": "1", "scope": "out", "pct": True},
    {"key": "top_speed", "label": "Top speed (km/h)", "group": "Physical", "fmt": "1", "scope": "all", "pct": True},
    # discipline and rating
    # Derived: combinations and ratios that separate style from volume.
    {"key": "npxg_xa_90", "label": "npxG + xA /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "ga_90", "label": "Goals + assists /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "finishing", "label": "Finishing (npG − npxG per shot)", "group": "Advanced", "fmt": "3", "scope": "out", "pct": True},
    {"key": "placement", "label": "Shot placement (xGOT − xG per shot)", "group": "Advanced", "fmt": "3", "scope": "out", "pct": True},
    {"key": "xa_per_kp", "label": "xA per key pass", "group": "Advanced", "fmt": "3", "scope": "out", "pct": True},
    {"key": "shot_creation_90", "label": "Shots + key passes /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "prog_actions_90", "label": "Progressive carries + dribbles /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "def_actions_90", "label": "Defensive actions /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "padj_tkl_int_90", "label": "PAdj tackles + interceptions /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "ball_wins_90", "label": "Ball wins /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "duels_90", "label": "Duels contested /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "aerials_90", "label": "Aerials contested /90", "group": "Advanced", "fmt": "2", "scope": "out", "pct": True},
    {"key": "loss_per_100", "label": "Possession lost per 100 touches", "group": "Advanced", "fmt": "1", "scope": "out", "pct": True, "lower": True},
    {"key": "rating", "label": "Rating", "group": "Rating", "fmt": "2", "scope": "all", "pct": True},
    {"key": "yellow", "label": "Yellow cards", "group": "Discipline", "fmt": "int", "scope": "all", "lower": True},
    {"key": "red", "label": "Red cards", "group": "Discipline", "fmt": "int", "scope": "all", "lower": True},
    {"key": "minutes", "label": "Minutes", "group": "Playing time", "fmt": "int", "scope": "all"},
    {"key": "matches", "label": "Appearances", "group": "Playing time", "fmt": "int", "scope": "all"},
    {"key": "starts", "label": "Starts", "group": "Playing time", "fmt": "int", "scope": "all"},
]

# Every entry carries its definition, so the payloads that emit the catalogue
# (players_live.json and the like) can explain each metric in place. The
# glossary module imports nothing from here at import time, so this is not a cycle.
from oddsmarkets.football.analytics.glossary import PLAYER_DEFINITIONS  # noqa: E402

for _m in METRICS:
    _m["desc"] = PLAYER_DEFINITIONS.get(_m["key"], "")
del _m

# Short keys for match-log rows and lineup entries (Sofascore stat -> column).
LOG_KEYS = {
    "minutesPlayed": "min", "goals": "g", "goalAssist": "a", "expectedGoals": "xg",
    "expectedAssists": "xa", "expectedGoalsOnTarget": "xgot", "totalShots": "sh",
    "onTargetScoringAttempt": "sot", "keyPass": "kp", "bigChanceCreated": "bc",
    "accuratePass": "pa", "totalPass": "pt", "touches": "tch", "duelWon": "dw", "duelLost": "dl",
    "wonTackle": "tw", "totalTackle": "tk", "interceptionWon": "int", "totalClearance": "clr",
    "ballRecovery": "rec", "aerialWon": "aw", "aerialLost": "al", "wonContest": "drw",
    "totalContest": "dra", "accurateCross": "crs", "totalCross": "crst", "accurateLongBalls": "lb",
    "totalLongBalls": "lbt", "progressiveBallCarriesCount": "pc", "ballCarriesCount": "car",
    "dispossessed": "dis", "possessionLostCtrl": "pl", "fouls": "fl", "wasFouled": "fld",
    "outfielderBlock": "blk", "saves": "sv", "goalsPrevented": "gp", "savedShotsFromInsideTheBox": "svib",
    "totalKeeperSweeper": "swp", "goodHighClaim": "hc", "punches": "pun", "kilometersCovered": "km",
    "numberOfSprints": "spr", "topSpeed": "ts", "rating": "rt",
}


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def short_num(v):
    """A stat as a compact JSON number: ints stay ints, floats keep three decimals."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return int(f) if f == int(f) else round(f, 3)


def _rate(num: float, den: float, digits: int = 1) -> float | None:
    return round(100.0 * num / den, digits) if den > 0 else None


def _age(dob_ts, now: datetime | None = None) -> int | None:
    if dob_ts is None:
        return None
    try:
        born = datetime.fromtimestamp(float(dob_ts), tz=timezone.utc)
    except (ValueError, OSError, OverflowError, TypeError):
        return None
    now = now or datetime.now(timezone.utc)
    return int((now - born).days // 365.25)


def tally_incidents(incs, out: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Add one match's incidents to `out`: cards and penalty goals per player id (or name when the id is missing)."""
    if not isinstance(incs, list):
        return out
    for inc in incs:
        if not isinstance(inc, dict):
            continue
        key = str(inc.get("player_id") or inc.get("player_name") or "")
        if not key:
            continue
        kind = str(inc.get("incident_type") or "").lower()
        cls = str(inc.get("incident_class") or "").lower()
        tally = out.setdefault(key, {"yellow": 0, "red": 0, "pens": 0, "own_goals": 0})
        if kind == "card":
            if "red" in cls:
                tally["red"] += 1
            else:
                tally["yellow"] += 1
        elif kind == "goal":
            if cls == "penalty":
                tally["pens"] += 1
            elif "own" in cls:
                tally["own_goals"] += 1
    return out


def player_incidents(store: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Cards and penalty goals per player, keyed by player id (or name when the id is missing)."""
    out: dict[str, dict[str, int]] = {}
    for incs in (store.get("incidents") or {}).values():
        tally_incidents(incs, out)
    return out


# Success-rate pairs (numerator, denominator). Some line-ups (an older Sofascore format, many UEFA qualifiers) carry
# the numerator without the denominator, e.g. wonTackle without totalTackle: summed as they are, the season's rate went
# past 100% (Conference League tackle success up to 600%, 71 players, 22 Oct 2026). An action won is an action tried,
# so a match's denominator is taken as at least its numerator.
RATE_PAIRS = (
    ("wonTackle", "totalTackle"), ("accuratePass", "totalPass"), ("accurateOwnHalfPasses", "totalOwnHalfPasses"),
    ("accurateOppositionHalfPasses", "totalOppositionHalfPasses"), ("accurateLongBalls", "totalLongBalls"),
    ("accurateCross", "totalCross"), ("wonContest", "totalContest"), ("accurateKeeperSweeper", "totalKeeperSweeper"),
    ("onTargetScoringAttempt", "totalShots"),
)


def paired_stats(s: dict[str, Any]) -> dict[str, Any]:
    """A match's statistics with every rate's denominator at least its numerator (RATE_PAIRS); `s` itself if whole."""
    out = s
    for num, den in RATE_PAIRS:
        n = _f(s.get(num))
        if n > _f(s.get(den)):
            if out is s:
                out = dict(s)
            out[den] = n
    return out


# Positions known outside a competition's own store (the current squads, other competitions' player metadata).
# A UEFA qualifier or a light-detail store often has line-ups without positions and no metadata for clubs
# outside the followed leagues; without a fallback those players had no position, so no positional peers
# (22 Oct 2026: 738 of 1,953 Conference League players). Set once per build by set_fallback_positions().
_FALLBACK_POSITIONS: dict[str, str] = {}
POSITION_LETTERS = ("G", "D", "M", "F")


def set_fallback_positions(positions: dict[str, str] | None) -> None:
    """Install the build-wide position map used when a store knows nothing of a player's position."""
    _FALLBACK_POSITIONS.clear()
    for pid, pos in (positions or {}).items():
        if pos in POSITION_LETTERS:
            _FALLBACK_POSITIONS[str(pid)] = pos


def positions_from_store(store: dict[str, Any]) -> dict[str, str]:
    """Each player's position letter: the store's metadata, else the most common per-match position, else the
    build-wide fallback (set_fallback_positions)."""
    out: dict[str, str] = {}
    meta = store.get("players") or {}
    votes: dict[str, dict[str, int]] = {}
    seen: set[str] = set()
    for players in (store.get("lineups") or {}).values():
        if not isinstance(players, dict):
            continue
        for pid, p in players.items():
            seen.add(str(pid))
            pos = p.get("p") if isinstance(p, dict) else None
            if pos:
                v = votes.setdefault(str(pid), {})
                v[pos] = v.get(pos, 0) + 1
    for pid, v in votes.items():
        out[pid] = max(v.items(), key=lambda kv: kv[1])[0]
    for pid, m in meta.items():
        if isinstance(m, dict) and m.get("pos"):
            out[str(pid)] = str(m["pos"])
    if _FALLBACK_POSITIONS:
        for pid in seen:
            if pid not in out and pid in _FALLBACK_POSITIONS:
                out[pid] = _FALLBACK_POSITIONS[pid]
    return out


def aggregate_players(store: dict[str, Any], registry="liga_argentina") -> list[dict]:
    """
    Per-player season totals, rates and per-90s from the per-match store.

    Keyed by Sofascore player id rather than name, so two players sharing a name are
    not merged. The club recorded is whichever the player last appeared for —
    mid-season transfers are common, and attributing a whole season to a stale
    club would misstate both the player and the team totals.
    """
    matches = store.get("matches") or {}
    meta_all = store.get("players") or {}
    positions = positions_from_store(store)
    incidents = player_incidents(store)
    acc: dict[str, dict] = {}

    def entry(pid: str, p: dict) -> dict:
        a = acc.get(pid)
        if a is None:
            a = acc[pid] = {
                "player_id": pid, "name": p.get("n", ""), "team": "", "matches": 0, "starts": 0,
                "_rat_w": 0.0, "_rat_min": 0.0, "top_speed": 0.0, "_conceded": 0.0, "_last": "", "_padj": 0.0,
                "shirt": None, **{k: 0.0 for k in SUM_KEYS},
            }
        return a

    # Sort by date so "last club" really is the latest appearance.
    order = sorted(
        ((gid, players) for gid, players in (store.get("lineups") or {}).items() if isinstance(players, dict)),
        key=lambda kv: str((matches.get(str(kv[0])) or {}).get("date") or ""),
    )
    sheets = store.get("team_stats") or {}
    for gid, players in order:
        meta = matches.get(str(gid)) or {}
        home = normalize_team_name(str(meta.get("home", "")), registry)
        hs, as_ = meta.get("hs"), meta.get("as")
        sheet = sheets.get(str(gid)) or {}
        for pid, p in players.items():
            if not isinstance(p, dict):
                continue
            s = paired_stats(p.get("s") or {})
            mins = _f(s.get("minutesPlayed"))
            a = entry(str(pid), p)
            a["name"] = p.get("n", a["name"])
            team = normalize_team_name(str(p.get("t", "")), registry)
            if team:
                a["team"] = team
            if p.get("no"):
                a["shirt"] = str(p["no"])
            if mins > 0:
                a["matches"] += 1
                if not p.get("sub"):
                    a["starts"] += 1
            for k in SUM_KEYS:
                a[k] += _f(s.get(k))
            # Possession-adjusted tackles + interceptions: a side that has the ball
            # less has more chances to defend, so each action is scaled by
            # 50 / opponent possession (clamped to 25-75%). Matches without a
            # team sheet count unadjusted.
            own = (sheet.get("home" if team == home else "away") or {}).get("ballPossession") if sheet else None
            opp = 100.0 - min(max(_f(own), 25.0), 75.0) if own is not None else 50.0
            a["_padj"] += (_f(s.get("totalTackle")) + _f(s.get("interceptionWon"))) * 50.0 / opp
            if s.get("rating") is not None and mins > 0:
                a["_rat_w"] += _f(s["rating"]) * mins
                a["_rat_min"] += mins
            if s.get("topSpeed"):
                a["top_speed"] = max(a["top_speed"], _f(s["topSpeed"]))
            # A goalkeeper's goals conceded: the opponent's goals, pro-rated by
            # minutes when they did not play the whole match.
            if (p.get("p") or positions.get(str(pid))) == "G" and mins > 0 and hs is not None and as_ is not None:
                against = as_ if team == home else hs
                a["_conceded"] += _f(against) * min(mins, 90.0) / 90.0

    now = datetime.now(timezone.utc)
    out = []
    for pid, a in acc.items():
        meta = meta_all.get(pid) if isinstance(meta_all.get(pid), dict) else {}
        inc = incidents.get(pid) or incidents.get(a["name"]) or {}
        out.append(finalize_player(pid, a, meta, positions.get(pid), inc, now))

    out.sort(key=lambda r: (-r["goals"], -r["xg"]))
    return out


def finalize_player(pid: str, a: dict[str, Any], meta: dict | None, pos: str | None, inc: dict | None,
                    now: datetime | None = None) -> dict[str, Any]:
    """
    One player's line from his accumulated match stats (`a`: SUM_KEYS plus matches,
    starts, the rating weights, top speed, goals conceded and the possession-adjusted
    defending, as aggregate_players builds them), his store metadata, position letter
    and incident tally. Shared with the consolidated per-person lines (people_lines.py).
    """
    meta = meta or {}
    inc = inc or {}
    now = now or datetime.now(timezone.utc)
    mins = a["minutesPlayed"]
    p90 = max(mins, 1.0) / 90.0
    pens = int(inc.get("pens", 0))
    # non-penalty xG leaves out every penalty taken: scored (incidents) and missed or saved (penaltyMiss); before 23 Oct
    # 2026 a missed penalty's 0.79 stayed in npxg (value.py already removed both)
    goals = int(a["goals"])
    is_gk = pos == "G" if pos else bool(a["saves"] > 0 or a["keeperSaveValue"] > 0 or a["savedShotsFromInsideTheBox"] > 0)
    shots = int(a["totalShots"])
    rec: dict[str, Any] = {
        "player_id": pid, "name": a["name"], "team": a["team"],
        "short_name": meta.get("sn"), "position": pos, "is_gk": is_gk,
        "age": _age(meta.get("dob"), now), "country": meta.get("c"), "height": meta.get("h"),
        "shirt": a["shirt"] or meta.get("no"),
        "matches": a["matches"], "starts": a["starts"], "minutes": int(mins),
        "goals": goals, "assists": int(a["goalAssist"]),
        "pens": pens, "npg": goals - pens,
        "xg": round(a["expectedGoals"], 2), "npxg": round(max(a["expectedGoals"] - PEN_XG * (pens + int(a.get("penaltyMiss") or 0)), 0.0), 2),
        "xa": round(a["expectedAssists"], 2), "xgot": round(a["expectedGoalsOnTarget"], 2),
        "g_minus_xg": round(goals - a["expectedGoals"], 2),
        "shots": shots, "sot": int(a["onTargetScoringAttempt"]),
        "shots_blocked": int(a["blockedScoringAttempt"]), "woodwork": int(a["hitWoodwork"]),
        "sot_pct": _rate(a["onTargetScoringAttempt"], shots),
        "xg_per_shot": round(a["expectedGoals"] / shots, 3) if shots else None,
        "key_passes": int(a["keyPass"]), "big_chances": int(a["bigChanceCreated"]),
        "big_chances_missed": int(a["bigChanceMissed"]),
        "passes": int(a["totalPass"]), "passes_acc": int(a["accuratePass"]),
        "pass_pct": round(100 * a["accuratePass"] / max(a["totalPass"], 1), 1),
        "opp_half_passes": int(a["accurateOppositionHalfPasses"]),
        "long_balls": int(a["accurateLongBalls"]), "long_balls_att": int(a["totalLongBalls"]),
        "long_ball_pct": _rate(a["accurateLongBalls"], a["totalLongBalls"]),
        "crosses": int(a["accurateCross"]), "crosses_att": int(a["totalCross"]),
        "cross_pct": _rate(a["accurateCross"], a["totalCross"]),
        "dribbles": int(a["wonContest"]), "dribbles_att": int(a["totalContest"]),
        "dribble_pct": _rate(a["wonContest"], a["totalContest"]),
        "carries": int(a["ballCarriesCount"]), "prog_carries": int(a["progressiveBallCarriesCount"]),
        "carry_dist": int(a["totalBallCarriesDistance"]),
        "touches": int(a["touches"]), "dispossessed": int(a["dispossessed"]),
        "poss_lost": int(a["possessionLostCtrl"]),
        "tackles": int(a["totalTackle"]), "tackles_won": int(a["wonTackle"]),
        "tackle_pct": _rate(a["wonTackle"], a["totalTackle"]),
        "interceptions": int(a["interceptionWon"]), "clearances": int(a["totalClearance"]),
        "blocks": int(a["outfielderBlock"]), "recoveries": int(a["ballRecovery"]),
        "duels_won": int(a["duelWon"]), "duels_lost": int(a["duelLost"]),
        "duel_pct": _rate(a["duelWon"], a["duelWon"] + a["duelLost"]),
        "aerials_won": int(a["aerialWon"]), "aerials_lost": int(a["aerialLost"]),
        "aerial_pct": _rate(a["aerialWon"], a["aerialWon"] + a["aerialLost"]),
        "fouls": int(a["fouls"]), "fouled": int(a["wasFouled"]),
        "errors": int(a["errorLeadToAShot"] + a["errorLeadToAGoal"]), "offsides": int(a["totalOffside"]),
        "saves": int(a["saves"]), "saves_in_box": int(a["savedShotsFromInsideTheBox"]),
        "goals_prevented": round(a["goalsPrevented"], 2),
        "conceded": int(round(a["_conceded"])),
        "save_pct": _rate(a["saves"], a["saves"] + a["_conceded"]) if is_gk else None,
        "sweeper": int(a["totalKeeperSweeper"]), "high_claims": int(a["goodHighClaim"]),
        "punches": int(a["punches"]),
        "km": round(a["kilometersCovered"], 1),
        "hsr_km": round(a["metersCoveredHighSpeedRunningKm"] + a["metersCoveredSprintingKm"], 2),
        "sprints": int(a["numberOfSprints"]), "top_speed": round(a["top_speed"], 1),
        "rating": round(a["_rat_w"] / a["_rat_min"], 2) if a["_rat_min"] > 0 else None,
        "yellow": int(inc.get("yellow", 0)), "red": int(inc.get("red", 0)),
        "own_goals": int(a["ownGoals"]),
    }
    # Per-90 rates: what makes a rotation player comparable to an ever-present,
    # and what the leaderboards and percentiles sort on.
    for m in PER90:
        v = rec.get(m)
        rec[f"{m}_90"] = round(float(v) / p90, 3) if v is not None else None
    # Derived metrics (the "Advanced" group of the catalogue).
    np_shots = max(shots - pens - int(a["penaltyMiss"]), 0)
    rec["npxg_xa_90"] = round((rec["npxg"] + rec["xa"]) / p90, 3)
    rec["ga_90"] = round((goals + rec["assists"]) / p90, 3)
    rec["finishing"] = round((rec["npg"] - rec["npxg"]) / np_shots, 3) if np_shots >= 1 else None
    rec["placement"] = round((a["expectedGoalsOnTarget"] - a["expectedGoals"]) / shots, 3) if shots else None
    rec["xa_per_kp"] = round(rec["xa"] / rec["key_passes"], 3) if rec["key_passes"] else None
    rec["shot_creation_90"] = round((shots + rec["key_passes"]) / p90, 3)
    rec["prog_actions_90"] = round((rec["prog_carries"] + rec["dribbles"]) / p90, 3)
    rec["def_actions_90"] = round((rec["tackles"] + rec["interceptions"] + rec["blocks"] + rec["clearances"]) / p90, 3)
    rec["padj_tkl_int_90"] = round(a["_padj"] / p90, 3)
    rec["ball_wins_90"] = round((rec["tackles_won"] + rec["interceptions"] + rec["recoveries"]) / p90, 3)
    rec["duels_90"] = round((rec["duels_won"] + rec["duels_lost"]) / p90, 3)
    rec["aerials_90"] = round((rec["aerials_won"] + rec["aerials_lost"]) / p90, 3)
    rec["loss_per_100"] = round(100.0 * rec["poss_lost"] / rec["touches"], 1) if rec["touches"] else None
    return rec


# Minutes a player needs before he is ranked (percentiles, leaderboards): this share of the
# minutes his competition's season has offered so far, so the bar rises with the games played
# (about 190 minutes seven rounds in, about 1,030 at the end of a 38-round league) and a
# league thirty rounds in is not ranked on the same 270 minutes as one seven rounds in.
FLOOR_SHARE = 0.3
FLOOR_MIN = 90


def minutes_floor(players: list[dict], games: float | None = None) -> int:
    """
    The ranking floor: FLOOR_SHARE of the season's minutes so far (`games` x 90; by
    default the most minutes any player has, an ever-present's), at least FLOOR_MIN,
    rounded to ten minutes.
    """
    if games is None:
        top = max((p.get("minutes", 0) or 0 for p in players), default=0)
    else:
        top = float(games) * 90.0
    return int(max(FLOOR_MIN, round(FLOOR_SHARE * top / 10.0) * 10))


def add_percentiles(players: list[dict], floor: int | None = None) -> int:
    """
    Percentile of each slider metric against positional peers in the same
    competition (goalkeepers against goalkeepers, defenders against defenders,
    and so on), among players over the minutes floor. Writes `pct` (metric ->
    0-100), `pool` and `qualified` onto each row; returns the floor used.
    """
    floor = minutes_floor(players) if floor is None else floor
    pools: dict[str, list[dict]] = {}
    for p in players:
        p["qualified"] = p.get("minutes", 0) >= floor
        if p["qualified"]:
            pools.setdefault(_pool_of(p), []).append(p)
    slider = [m for m in METRICS if m.get("pct")]
    sorted_values: dict[tuple[str, str], list[float]] = {}
    for pool_key, members in pools.items():
        for m in slider:
            vals = sorted(float(q[m["key"]]) for q in members if q.get(m["key"]) is not None)
            sorted_values[(pool_key, m["key"])] = vals
    for p in players:
        if not p["qualified"]:
            p["pct"] = None
            p["pool"] = None
            continue
        pool_key = _pool_of(p)
        p["pool"] = {"key": pool_key, "label": POSITION_LABELS.get(pool_key, "Outfield"), "n": len(pools[pool_key])}
        pct: dict[str, int] = {}
        for m in slider:
            if m["scope"] == "gk" and pool_key != "G":
                continue
            if m["scope"] == "out" and pool_key == "G":
                continue
            v = p.get(m["key"])
            vals = sorted_values.get((pool_key, m["key"])) or []
            if v is None or len(vals) < 3:
                continue
            below = _bisect_left(vals, float(v))
            above = len(vals) - _bisect_right(vals, float(v))
            ties = len(vals) - below - above
            rank = (below + 0.5 * ties) / len(vals)
            if m.get("lower"):
                rank = 1.0 - rank
            pct[m["key"]] = int(round(100 * rank))
        p["pct"] = pct
    return floor


def _pool_of(p: dict) -> str:
    pos = p.get("position")
    if p.get("is_gk"):
        return "G"
    return pos if pos in ("D", "M", "F") else "out"


def _bisect_left(vals: list[float], x: float) -> int:
    lo, hi = 0, len(vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if vals[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _bisect_right(vals: list[float], x: float) -> int:
    lo, hi = 0, len(vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if x < vals[mid]:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _shots_by_match_player(store: dict[str, Any]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for gid, shots in (store.get("shots") or {}).items():
        if not isinstance(shots, list):
            continue
        for s in shots:
            if not isinstance(s, dict):
                continue
            key = str(s.get("player_id") or s.get("player_name") or "")
            if not key:
                continue
            out.setdefault((str(gid), key), []).append({
                "x": s.get("x"), "y": s.get("y"), "xg": s.get("xg"), "xgot": s.get("xgot"),
                "type": s.get("shot_type"), "body": s.get("body_part"), "situation": s.get("situation"),
                "time": s.get("time"),
            })
    return out


def player_match_logs(store: dict[str, Any], registry="liga_argentina") -> dict[str, dict]:
    """
    Every player's match-by-match line: minutes, rating, the short-keyed stats,
    and their shots in that match. Keyed by player id; rows newest first.
    """
    matches = store.get("matches") or {}
    shots = _shots_by_match_player(store)
    positions = positions_from_store(store)
    out: dict[str, dict] = {}
    for gid, players in (store.get("lineups") or {}).items():
        if not isinstance(players, dict):
            continue
        meta = matches.get(str(gid)) or {}
        home = normalize_team_name(str(meta.get("home", "")), registry)
        away = normalize_team_name(str(meta.get("away", "")), registry)
        hs, as_ = meta.get("hs"), meta.get("as")
        for pid, p in players.items():
            if not isinstance(p, dict):
                continue
            s = p.get("s") or {}
            mins = _f(s.get("minutesPlayed"))
            if mins <= 0:
                continue
            team = normalize_team_name(str(p.get("t", "")), registry)
            is_home = team == home
            opp = away if is_home else home
            gf, ga = (hs, as_) if is_home else (as_, hs)
            res = None
            if gf is not None and ga is not None:
                res = "W" if gf > ga else "D" if gf == ga else "L"
            row: dict[str, Any] = {
                "gid": str(gid), "date": meta.get("date"), "round": meta.get("round"), "stage": meta.get("stage"),
                "team": team, "opp": opp, "ha": "H" if is_home else "A", "gf": gf, "ga": ga, "res": res,
                "pos": p.get("p"), "start": not p.get("sub"),
            }
            for stat, short in LOG_KEYS.items():
                if s.get(stat) is not None:
                    row[short] = short_num(s[stat])
            sh = shots.get((str(gid), str(pid))) or shots.get((str(gid), str(p.get("n", ""))))
            if sh:
                row["shots"] = sh
            entry = out.setdefault(str(pid), {"name": p.get("n", ""), "team": team, "pos": positions.get(str(pid)), "matches": []})
            entry["name"] = p.get("n", entry["name"])
            entry["matches"].append(row)
    for entry in out.values():
        entry["matches"].sort(key=lambda r: str(r.get("date") or ""), reverse=True)
        # The club is the one of the latest appearance.
        entry["team"] = entry["matches"][0]["team"]
    return out
