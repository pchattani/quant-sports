"""The Gridiron's league block (season.json["league"]) and race log (data/race_log.json): how the playoff race is
shaping up and each team's strengths and weaknesses, on the shared engine oddsmarkets/common/league.py.

Reads only payload dicts (season.json, teams.json, the schedule cards) plus the race log, so it runs on a deployed copy
as well as inside the build. The as-of rebuild (snapshots before the site kept a live log) runs the season simulation
with `through=<date>`: results before that date, team ratings fitted through it and market ratings only from games
already played (no look-ahead), REBUILD_N simulations a date, at the opening game day (the preseason baseline) and
each Tuesday after a completed week, inside REBUILD_BUDGET_S seconds a build.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Callable

from oddsmarkets.common import league as LG

logger = logging.getLogger(__name__)

METRICS = [{"key": "p_playoffs", "label": "Playoffs"}, {"key": "p_div", "label": "Division"}, {"key": "p_sb", "label": "Super Bowl"}]
REBUILD_N = 2000
REBUILD_BUDGET_S = 90.0
MIN_GP = 3                    # raw EPA rates are ranked from week 3; our ratings (which carry last season) from week 1
PYTHAG_EXP = 2.37
CLOSE = 8                     # one-score games

# the spec's team sets (docs/_design/metrics/nfl.json team / team_offence / team_defence) plus the league page's
# early-down passing and pass rush; read from teams.json values. chip: the dimension's name in a sentence.
SPEC = [
    {"id": "rating", "label": "Team rating", "dir": "higher", "fmt": "+1", "unit": "points a game v average", "model": True, "group": "Overall"},
    {"id": "off_rating", "label": "Offence rating", "dir": "higher", "fmt": "+1", "unit": "points a game", "model": True, "group": "Overall"},
    {"id": "def_rating", "label": "Defence rating", "dir": "higher", "fmt": "+1", "unit": "points a game", "model": True, "group": "Overall"},
    {"id": "off_epa", "label": "Offence EPA", "dir": "higher", "fmt": "+2", "unit": "per play, opponent-adjusted", "chip": "offence", "group": "Offence"},
    {"id": "off_pass_epa", "label": "Passing EPA", "dir": "higher", "fmt": "+2", "unit": "per dropback", "chip": "passing game", "group": "Offence"},
    {"id": "off_rush_epa", "label": "Rushing EPA", "dir": "higher", "fmt": "+2", "unit": "per designed run", "chip": "running game", "group": "Offence"},
    {"id": "ed_pass_epa", "label": "Early-down passing", "dir": "higher", "fmt": "+2", "unit": "EPA per dropback, 1st and 2nd down", "chip": "early-down passing", "group": "Offence"},
    {"id": "off_success", "label": "Success rate", "dir": "higher", "fmt": "pct1", "unit": "plays gaining expected points", "group": "Offence"},
    {"id": "pressure_allowed", "label": "Pressure allowed", "dir": "lower", "fmt": "pct1", "unit": "of dropbacks", "chip": "pass protection", "group": "Offence"},
    {"id": "sack_rate_allowed", "label": "Sacks allowed", "dir": "lower", "fmt": "pct1", "unit": "per dropback", "chip": "pass protection", "group": "Offence"},
    {"id": "def_epa", "label": "Defence EPA", "dir": "lower", "fmt": "+2", "unit": "per play allowed, opponent-adjusted", "chip": "defence", "group": "Defence"},
    {"id": "def_pass_epa", "label": "Pass defence EPA", "dir": "lower", "fmt": "+2", "unit": "per dropback allowed", "chip": "pass defence", "group": "Defence"},
    {"id": "def_rush_epa", "label": "Run defence EPA", "dir": "lower", "fmt": "+2", "unit": "per designed run allowed", "chip": "run defence", "group": "Defence"},
    {"id": "ed_pass_epa_def", "label": "Early-down pass defence", "dir": "lower", "fmt": "+2", "unit": "EPA per dropback allowed, 1st and 2nd down", "group": "Defence"},
    {"id": "def_success", "label": "Success rate allowed", "dir": "lower", "fmt": "pct1", "unit": "opponent plays gaining expected points", "group": "Defence"},
    {"id": "pressure_rate_def", "label": "Pass rush (pressure)", "dir": "higher", "fmt": "pct1", "unit": "of opponent dropbacks", "chip": "pass rush", "group": "Defence"},
    {"id": "sack_rate_def", "label": "Pass rush (sacks)", "dir": "higher", "fmt": "pct1", "unit": "per opponent dropback", "chip": "pass rush", "group": "Defence"},
    {"id": "st_epa_g", "label": "Special teams", "dir": "higher", "fmt": "+1", "unit": "EPA a game", "chip": "special teams", "group": "Special teams"},
    {"id": "ed_pass_rate", "label": "Early-down pass rate", "dir": "higher", "fmt": "pct0", "unit": "of 1st- and 2nd-down plays", "style": True, "group": "Style",
     "hi": "Pass-first on early downs", "lo": "Run-first on early downs"},
    {"id": "sec_per_play_neutral", "label": "Tempo", "dir": "lower", "fmt": "1", "unit": "seconds a play, neutral situations", "style": True, "group": "Style",
     "hi": "Fastest tempo", "lo": "Slowest tempo"},
]
QUAD = {"x": "off_epa", "y": "def_epa", "flipY": True, "xName": "Offence: EPA per play (opponent-adjusted)", "yName": "Defence: EPA per play allowed (less is higher)",
        "corners": {"tl": "Defence first", "tr": "Good at both", "bl": "Work to do", "br": "Offence first"}}


def chances_of(sim_teams: dict) -> dict:
    """{metric: {team: p}} from season.json sim.teams (or the simulation's own teams dict)."""
    return {m["key"]: {t: v.get(m["key"]) for t, v in (sim_teams or {}).items() if isinstance(v, dict) and v.get(m["key"]) is not None}
            for m in METRICS}


def asof_runner(season: int, n: int = REBUILD_N) -> Callable[[str], dict | None]:
    """run_asof(day) -> {metric: {team: p}} from the season simulation with through=day (results before that date)."""
    def run(day: str) -> dict | None:
        from oddsmarkets.nfl.models import season_sim as SS
        res = SS.for_season(int(season), n=n, seed=0, through=day)
        if not res.get("ok"):
            return None
        return chances_of(res.get("teams") or {})
    return run


def _day(c: dict) -> str | None:
    return LG._day(c.get("kickoff") or c.get("date"))


def rebuild_days(cards: list[dict], live_from: str) -> list[str]:
    """The opening game day (nothing played: the preseason baseline), then each Tuesday after a week's games, before
    live tracking began."""
    days = sorted(d for d in (_day(c) for c in cards if str(c.get("gtype") or "REG") == "REG") if d)
    if not days:
        return []
    first = date.fromisoformat(days[0])
    tue = first + timedelta(days=(1 - first.weekday()) % 7 or 7)        # the first Tuesday after the opener
    return sorted(set([days[0]] + LG.rebuild_dates(tue.isoformat(), live_from, 7)) - {live_from}) if days[0] < live_from else []


def _rows(sp: dict) -> list[dict]:
    st = sp.get("standings") or []
    out = []
    for d in st if isinstance(st, list) else []:
        for r in d.get("teams") or []:
            out.append(dict(r, division=d.get("division"), conference=d.get("conference")))
    return out


def build(season: int, season_payload: dict, teams_payload: dict | None, cards: list[dict], race_log: dict | None,
          now: datetime, run_asof: Callable[[str], dict | None] | None = None, budget_s: float = REBUILD_BUDGET_S) -> tuple[dict | None, dict]:
    """(season.json["league"] or None, the race log to write)."""
    sp = season_payload or {}
    sim_teams = ((sp.get("sim") or {}).get("teams")) or {}
    log = dict(race_log or {}) if isinstance(race_log, dict) else {}
    rows = _rows(sp)
    if not rows:
        return None, log
    teams = [str(r["team"]) for r in rows]
    by = {str(r["team"]): r for r in rows}
    abbr = {t: t for t in teams}
    phase = str(sp.get("phase") or "regular")
    today = LG._day(now)
    cur = chances_of(sim_teams)
    seas = LG.race_season(log, season)
    if any(cur.values()):
        seas = LG.roll_race(seas, today, cur)
    if run_asof is not None:
        live_from = (seas.get(LG.META) or {}).get("live_from") or today
        seas, done = LG.backfill(seas, rebuild_days(cards, live_from), run_asof, budget_s=budget_s, n=REBUILD_N)
        if done:
            logger.info("race log %s: rebuilt %d dates (%s .. %s)", season, len(done), done[0], done[-1])
    log[str(season)] = seas

    results = LG.norm_results([dict(c, date=_day(c)) for c in cards if c.get("status") == "final"])
    tp = (teams_payload or {}).get("teams") or {}
    ratings = sp.get("ratings") or {}
    rating = {t: (((ratings.get(t) or {}).get("values") or {}).get("rating")) for t in teams}
    rating = {t: (v if v is not None else by[t].get("rating")) for t, v in rating.items()}
    # schedule strength: the payload's (mean team rating of the opponents, points a game), ranked (1 = hardest)
    rk_l = LG.ranks({t: by[t].get("sos_left") for t in teams if (by[t].get("games_left") or 0) > 0}, high_first=True)
    rk_p = LG.ranks({t: by[t].get("sos") for t in teams}, high_first=True)
    conf = {t: by[t].get("conference") for t in teams}
    rivals = lambda t: [x for x in teams if conf.get(x) == conf.get(t)]          # noqa: E731 - the conference race
    settled = cur.get("p_playoffs") and all(v in (0, 1) for v in cur["p_playoffs"].values())
    metric = "p_sb" if phase in ("postseason", "complete") or settled else "p_playoffs"
    mv = LG.movers(seas, metric, cur.get(metric) or {}, now, results, rivals, abbr, rating, rk_l, weekly=True)

    from oddsmarkets.common import featured as FT
    up = [{"id": c.get("game_id"), "start": c.get("kickoff"), "home": c.get("home"), "away": c.get("away"),
           "p_home": (c.get("model") or {}).get("p_home")} for c in cards if c.get("status") != "final"]
    nxt = {t: (v.get("next_game") or v.get("next") or {}) for t, v in sim_teams.items()}

    def sig(g):
        oh, oa = sim_teams.get(str(g["home"])) or {}, sim_teams.get(str(g["away"])) or {}
        return FT.stakes_points({"sig": {"playoff": [oh.get("p_playoffs"), oa.get("p_playoffs")], "title": [oh.get("p_sb"), oa.get("p_sb")]}})
    games = LG.matter_games(up, nxt, metric, now, sig=sig)

    race = {}
    for t in teams:
        s = sim_teams.get(t) or {}
        r = by[t]
        left = int(r.get("games_left") if r.get("games_left") is not None else max(0, 17 - (r.get("w") or 0) - (r.get("l") or 0) - (r.get("t") or 0)))
        mg, tg = (s.get("magic") or r.get("magic") or {}).get("playoffs"), (s.get("tragic") or r.get("tragic") or {}).get("playoffs")
        cl, el = (s.get("clinched") or r.get("clinched") or {}), (s.get("eliminated") or r.get("eliminated") or {})
        p = s.get("p_playoffs", r.get("p_playoffs"))
        status = "clinched" if cl.get("playoffs") else "out" if el.get("playoffs") else None
        nx = nxt.get(t) or {}
        race[t] = {k: v for k, v in {
            # shown once within reach: no more than the games left (a magic number of 14 in October says nothing)
            "magic": mg if isinstance(mg, (int, float)) and mg <= left else None,
            "elim": tg if isinstance(tg, (int, float)) and tg <= left else None,
            "unit": "wins",
            "status": status,
            "all_sims": "in" if (p is not None and p >= 0.9995 and not status) else "out" if (p is not None and p <= 0.0005 and not status) else None,
            "sos": [LG._r(r.get("sos_left"), 2), rk_l.get(t), left] if left and r.get("sos_left") is not None else None,
            "sos_played": [LG._r(r.get("sos"), 2), rk_p.get(t), (r.get("w") or 0) + (r.get("l") or 0) + (r.get("t") or 0)] if r.get("sos") is not None else None,
            "next": {"id": nx.get("game_id"), "week": nx.get("week"), "opp": nx.get("opp"), "home": nx.get("home"),
                     "p": LG._r(nx.get("p_win"), 3), "w": LG._r((nx.get("if_win") or {}).get(metric), 3),
                     "l": LG._r((nx.get("if_loss") or {}).get(metric), 3)} if nx.get("opp") else None,
        }.items() if v is not None}

    # strengths and weaknesses (teams.json values; season.json ratings for the model ratings when teams.json lacks them)
    vals = {}
    for t in teams:
        v0 = ((tp.get(t) or {}).get("values")) or {}
        rv = ((ratings.get(t) or {}).get("values")) or {}
        vals[t] = {m["id"]: v0.get(m["id"], rv.get(m["id"])) for m in SPEC}
    spec = [m for m in SPEC if sum(1 for t in teams if vals[t].get(m["id"]) is not None) >= 3]
    if any(m["id"] == "pressure_rate_def" for m in spec):       # pressure data: the sack rates lose their chips
        spec = [dict(m, chip=None) if m["id"] in ("sack_rate_def", "sack_rate_allowed") else m for m in spec]
    for t in teams:
        vals[t] = {m["id"]: vals[t].get(m["id"]) for m in spec}
    gp = {t: int((by[t].get("w") or 0) + (by[t].get("l") or 0) + (by[t].get("t") or 0)) for t in teams}
    prof = LG.profile(vals, spec, gp, MIN_GP)
    early = all(g < MIN_GP for g in gp.values())
    lk_in = {}
    for t in teams:
        g = gp[t]
        pe = LG.pythag(by[t].get("pf"), by[t].get("pa"), g, PYTHAG_EXP)
        if pe is None or not g:
            continue
        lk_in[t] = {"gp": g, "actual": (by[t].get("w") or 0) + 0.5 * (by[t].get("t") or 0), "expected": pe * g,
                    "close": LG.close_record(results, t, CLOSE)}
    thr = max(1.0, 0.4 * math.sqrt(max(gp.values() or [0])))
    lk = LG.luck(lk_in, thr)
    ch = {t: LG.chips(t, prof, spec, len(teams), overall="rating", luck=lk.get(t), sos_rank=rk_l.get(t), early=gp[t] < MIN_GP) for t in teams}
    tl = LG.tiers(cur.get("p_playoffs") or {}, cur.get("p_sb") or {}, phase, len(teams))
    blk = LG.block(now=now, phase=phase, metrics=METRICS, current=cur, seas=seas, movers_=mv, games=games, race=race, prof=prof,
                   spec=spec, chips_=ch, luck_=lk, tiers_=tl, quad=QUAD, early=early, min_gp=MIN_GP, gp=gp, values=vals,
                   notes={"sos_unit": "points a game: the average opponent's rating (ours)", "luck_unit": "wins",
                          "luck_basis": "wins against the wins its points for and against deserved (Pythagorean, exponent 2.37)",
                          "close": "one-score games, 8 points or fewer", "metric": metric, "rebuild_n": REBUILD_N,
                          "luck_threshold": round(thr, 1), "weekly": True})
    return blk, log
