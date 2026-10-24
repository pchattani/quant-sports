"""The Rink's league block (season.json["league"]) and race log (data/race_log.json): how the race is shaping up and
each club's strengths and weaknesses, on the shared engine oddsmarkets/common/league.py.

Reads only payload dicts (season.json, teams.json, the schedule cards) plus the race log, so it runs on a deployed
copy as well as inside the build. The as-of rebuild (snapshots before the site kept a live log) calls the season
simulation with `through=<date>`: results before that date and team ratings fitted through it (no look-ahead), with
REBUILD_N simulations a date, inside REBUILD_BUDGET_S seconds a build.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Callable

from oddsmarkets.common import league as LG

logger = logging.getLogger(__name__)

METRICS = [{"key": "p_playoffs", "label": "Playoffs"}, {"key": "p_div", "label": "Division"}, {"key": "p_cup", "label": "Stanley Cup"}]
REBUILD_N = 2000
REBUILD_STEP_DAYS = 3
REBUILD_BUDGET_S = 90.0
MIN_GP = 10

# the spec's team set (docs/_design/metrics/hockey.json "teams"), read from teams.json units; chip: the dimension's
# name in a sentence ("Top-3 penalty kill")
SPEC = [
    {"id": "rating", "label": "Team rating", "dir": "higher", "fmt": "+2", "unit": "goals a game v average", "model": True, "group": "Overall"},
    {"id": "xgf_pct5", "label": "Expected-goal share (5v5)", "dir": "higher", "fmt": "pct1", "unit": "of 5v5 xG", "chip": "5v5 play", "group": "Overall"},
    {"id": "cf_pct5", "label": "Shot-attempt share (5v5)", "dir": "higher", "fmt": "pct1", "unit": "of 5v5 attempts", "chip": "puck possession", "group": "Overall"},
    {"id": "off5", "label": "5v5 offence", "dir": "higher", "fmt": "2", "unit": "xGF per 60", "chip": "5v5 offence", "group": "At 5v5"},
    {"id": "def5", "label": "5v5 defence", "dir": "lower", "fmt": "2", "unit": "xGA per 60", "chip": "5v5 defence", "group": "At 5v5"},
    {"id": "pp", "label": "Power play", "dir": "higher", "fmt": "2", "unit": "xGF per 60", "chip": "power play", "group": "Special teams"},
    {"id": "pk", "label": "Penalty kill", "dir": "lower", "fmt": "2", "unit": "xGA per 60", "chip": "penalty kill", "group": "Special teams"},
    {"id": "pp_pct", "label": "Power-play %", "dir": "higher", "fmt": "pct1", "unit": "goals per chance", "group": "Special teams"},
    {"id": "pk_pct", "label": "Penalty-kill %", "dir": "higher", "fmt": "pct1", "unit": "kills per chance", "group": "Special teams"},
    {"id": "goalie", "label": "Goaltending", "dir": "higher", "fmt": "+2", "unit": "goals saved above expected per 60", "chip": "goaltending", "group": "In net"},
    {"id": "gd_g", "label": "Goal difference", "dir": "higher", "fmt": "+2", "unit": "a game", "group": "Results"},
]
QUAD = {"x": "off5", "y": "def5", "flipY": True, "xName": "5v5 offence: expected goals for per 60", "yName": "5v5 defence: expected goals against per 60 (fewer is higher)",
        "corners": {"tl": "Defence first", "tr": "Good at both", "bl": "Work to do", "br": "Offence first"}}


def chances_of(sim_teams: dict) -> dict:
    """{metric: {team: p}} from season.json sim.teams (or the simulation's own teams dict)."""
    return {m["key"]: {t: v.get(m["key"]) for t, v in (sim_teams or {}).items() if isinstance(v, dict) and v.get(m["key"]) is not None}
            for m in METRICS}


def asof_runner(season: int, n: int = REBUILD_N) -> Callable[[str], dict | None]:
    """run_asof(day) -> {metric: {team: p}} from the season simulation with through=day (results before that date)."""
    def run(day: str) -> dict | None:
        from oddsmarkets.nhl.models import season_sim as SS
        res = SS.for_season(int(season), n=n, seed=0, through=day)
        if not res.get("ok"):
            return None
        return chances_of(res.get("teams") or {})
    return run


def _first_day(cards: list[dict]) -> str | None:
    days = sorted(str(c.get("date")) for c in cards if c.get("type") == "REG" and c.get("date"))
    return days[0] if days else None


def build(season: int, season_payload: dict, teams_payload: dict | None, cards: list[dict], race_log: dict | None,
          now: datetime, run_asof: Callable[[str], dict | None] | None = None, budget_s: float = REBUILD_BUDGET_S) -> tuple[dict | None, dict]:
    """(season.json["league"] or None, the race log to write)."""
    sp = season_payload or {}
    sim_teams = ((sp.get("sim") or {}).get("teams")) or {}
    log = dict(race_log or {}) if isinstance(race_log, dict) else {}
    rows = ((sp.get("standings") or {}).get("rows")) or []
    if not rows:
        return None, log
    teams = [str(r["team"]) for r in rows]
    by = {str(r["team"]): r for r in rows}
    info = sp.get("teams") or {}
    abbr = {t: t for t in teams}
    phase = str(sp.get("phase") or "regular")
    today = LG._day(now)
    cur = chances_of(sim_teams)
    seas = LG.race_season(log, season)
    if any(cur.values()):
        seas = LG.roll_race(seas, today, cur)
    # the as-of rebuild before live tracking began
    if run_asof is not None:
        first = _first_day(cards)
        live_from = (seas.get(LG.META) or {}).get("live_from") or today
        dates = LG.rebuild_dates(first, live_from, REBUILD_STEP_DAYS)
        seas, done = LG.backfill(seas, dates, run_asof, budget_s=budget_s, n=REBUILD_N)
        if done:
            logger.info("race log %s: rebuilt %d dates (%s .. %s)", season, len(done), done[0], done[-1])
    log[str(season)] = seas

    results = LG.norm_results([dict(c, ot=bool(c.get("ot") or c.get("so"))) for c in cards
                               if c.get("status") == "final" and c.get("type") in ("REG", "PO")])
    # our ratings (goals a game v average) for the schedule and the movers' "best win"
    tp = (teams_payload or {}).get("teams") or {}
    ratings = sp.get("ratings") or {}
    rating = {t: ((ratings.get(t) or {}).get("units") or {}).get("rating") for t in teams}
    rating = {t: (v if v is not None else by[t].get("rating")) for t, v in rating.items()}
    left = [c for c in cards if c.get("type") == "REG" and c.get("status") != "final"]
    done_reg = [c for c in cards if c.get("type") == "REG" and c.get("status") == "final"]
    sos_l = LG.schedule_strength(left, rating, teams)
    sos_p = LG.schedule_strength(done_reg, rating, teams)
    rk_l = LG.ranks({t: v["avg"] for t, v in sos_l.items()}, high_first=True)
    rk_p = LG.ranks({t: v["avg"] for t, v in sos_p.items()}, high_first=True)
    conf = {t: by[t].get("conference") or (info.get(t) or {}).get("conference") for t in teams}
    rivals = lambda t: [x for x in teams if conf.get(x) == conf.get(t)]        # noqa: E731 - the wild-card race
    metric = "p_cup" if phase == "playoffs" or (cur.get("p_playoffs") and all(v in (0, 1) for v in cur["p_playoffs"].values())) else "p_playoffs"
    mv = LG.movers(seas, metric, cur.get(metric) or {}, now, results, rivals, abbr, rating, rk_l, otl=True)

    # the games that matter: the simulation's next-game swings, else featured.py's stakes
    from oddsmarkets.common import featured as FT
    up = [{"id": c.get("game_id"), "start": c.get("start") or c.get("date"), "home": c.get("home"), "away": c.get("away"),
           "p_home": (c.get("model") or {}).get("p_home")} for c in cards if c.get("status") not in ("final",) and c.get("type") in ("REG", "PO")]
    nxt = {t: (v.get("next_game") or v.get("next") or {}) for t, v in sim_teams.items()}

    def sig(g):
        oh, oa = sim_teams.get(str(g["home"])) or {}, sim_teams.get(str(g["away"])) or {}
        return FT.stakes_points({"sig": {"playoff": [oh.get("p_playoffs"), oa.get("p_playoffs")], "title": [oh.get("p_cup"), oa.get("p_cup")]}})
    games = LG.matter_games(up, nxt, metric, now, sig=sig)

    # per-team race facts
    gp_left = {t: max(0, int(sp.get("season_games") or 82) - int(by[t].get("gp") or 0)) for t in teams}
    race = {}
    for t in teams:
        s = sim_teams.get(t) or {}
        mg, tg = (s.get("magic") or {}).get("playoffs"), (s.get("tragic") or {}).get("playoffs")
        cl, el = (s.get("clinched") or {}), (s.get("eliminated") or {})
        p = s.get("p_playoffs")
        status = "clinched" if cl.get("playoffs") else "out" if el.get("playoffs") else None
        nx = nxt.get(t) or {}
        race[t] = {k: v for k, v in {
            # shown once within reach: at most a point a game left (a magic number of 140 in October says nothing)
            "magic": mg if isinstance(mg, (int, float)) and mg <= gp_left[t] else None,
            "elim": tg if isinstance(tg, (int, float)) and tg <= gp_left[t] else None,
            "unit": "points",
            "status": status,
            "all_sims": "in" if (p is not None and p >= 0.9995 and not status) else "out" if (p is not None and p <= 0.0005 and not status) else None,
            "sos": [sos_l[t]["avg"], rk_l.get(t), sos_l[t]["n"]] if sos_l[t]["n"] else None,
            "sos_played": [sos_p[t]["avg"], rk_p.get(t), sos_p[t]["n"]] if sos_p[t]["n"] else None,
            "next": {"id": nx.get("game_id"), "date": nx.get("date"), "opp": nx.get("opp"), "home": nx.get("home"),
                     "p": LG._r(nx.get("p_win"), 3), "w": LG._r((nx.get("if_win") or {}).get(metric), 3),
                     "l": LG._r((nx.get("if_loss") or {}).get(metric), 3)} if nx.get("opp") else None,
        }.items() if v is not None}

    # strengths and weaknesses
    vals = {}
    for t in teams:
        u = ((tp.get(t) or {}).get("units")) or ((ratings.get(t) or {}).get("units")) or {}
        v = {m["id"]: u.get(m["id"]) for m in SPEC}
        if v.get("rating") is None:
            v["rating"] = rating.get(t)
        if v.get("gd_g") is None and by[t].get("gp"):
            v["gd_g"] = (by[t].get("gf", 0) - by[t].get("ga", 0)) / by[t]["gp"]
        vals[t] = v
    gp = {t: int(by[t].get("gp") or 0) for t in teams}
    prof = LG.profile(vals, SPEC, gp, MIN_GP)
    early = all(g < MIN_GP for g in gp.values())
    lk_in = {}
    for t in teams:
        u = ((tp.get(t) or {}).get("units")) or ((ratings.get(t) or {}).get("units")) or {}
        xf, xa, g = u.get("xgf_g"), u.get("xga_g"), gp[t]
        pe = LG.pythag(xf, xa, g, 2.0) if xf is not None and xa is not None else LG.pythag(by[t].get("gf"), by[t].get("ga"), g, 2.0)
        if pe is None or not g:
            continue
        lk_in[t] = {"gp": g, "actual": by[t].get("w"), "expected": pe * g, "close": LG.close_record(results, t, 1)}
    thr = max(1.5, 0.6 * math.sqrt(max(gp.values() or [0])))
    lk = LG.luck(lk_in, thr)
    ch = {t: LG.chips(t, prof, SPEC, len(teams), overall="rating", luck=lk.get(t), sos_rank=rk_l.get(t), early=gp[t] < MIN_GP) for t in teams}
    tl = LG.tiers(cur.get("p_playoffs") or {}, cur.get("p_cup") or {}, "postseason" if phase == "playoffs" else phase, len(teams))
    blk = LG.block(now=now, phase=phase, metrics=METRICS, current=cur, seas=seas, movers_=mv, games=games, race=race, prof=prof,
                   spec=SPEC, chips_=ch, luck_=lk, tiers_=tl, quad=QUAD, early=early, min_gp=MIN_GP, gp=gp, values=vals,
                   notes={"sos_unit": "goals a game: the average opponent's rating (ours), home ice included", "luck_unit": "wins",
                          "luck_basis": "wins against the wins its expected goals for and against deserved (Pythagorean, exponent 2)",
                          "close": "one-goal games, overtime and shootouts included", "metric": metric, "rebuild_n": REBUILD_N,
                          "luck_threshold": round(thr, 1)})
    return blk, log
