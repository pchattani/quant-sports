"""The Hardwood's league block (<L>/<S>/season.json["league_block"]) and race log (data/<L>/race_log.json): how the race is
shaping up and each team's strengths and weaknesses, on the shared engine oddsmarkets/common/league.py. NBA and WNBA.

Reads only payload dicts (season.json, teams.json, the schedule cards) plus the race log, so it runs on a deployed
copy as well as inside the build. The as-of rebuild (snapshots before the site kept a live log) calls the season
simulation with `through=<the day before>` (the basketball simulation counts `through` as the last day played, so the
snapshot for day D holds the results before D) and team ratings fitted through that day (no look-ahead), with
REBUILD_N simulations a date, inside REBUILD_BUDGET_S seconds a build. A finished season (the WNBA in its offseason)
rebuilds from its first regular-season day to its last, so its page shows how the race unfolded.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Callable

from oddsmarkets.common import league as LG

logger = logging.getLogger(__name__)

REBUILD_N = 2000
REBUILD_STEP_DAYS = {"nba": 2, "wnba": 4}
REBUILD_BUDGET_S = 90.0
MIN_GP = 10
PYTH_EXP = {"nba": 14.0, "wnba": 13.0}
TITLE = {"nba": "NBA title", "wnba": "WNBA title"}


def metrics(league: str) -> list[dict]:
    return [{"key": "p_playoffs", "label": "Playoffs"}, {"key": "p_div", "label": "Division"},
            {"key": "p_title", "label": TITLE.get(league, "Title")}]


# the spec's team set (docs/_design/metrics/basketball.json nba_teams / wnba_teams), read from teams.json values;
# chip: the dimension's name in a sentence ("Top-3 defence")
SPEC = [
    {"id": "model_net", "label": "Adjusted net rating", "dir": "higher", "fmt": "+1", "unit": "points per 100 v average", "model": True, "group": "Our ratings"},
    {"id": "model_off", "label": "Adjusted offence", "dir": "higher", "fmt": "1", "unit": "points per 100", "model": True, "chip": "offence", "group": "Our ratings"},
    {"id": "model_def", "label": "Adjusted defence", "dir": "lower", "fmt": "1", "unit": "points allowed per 100", "model": True, "chip": "defence", "group": "Our ratings"},
    {"id": "pace", "label": "Pace", "dir": "higher", "fmt": "1", "unit": "possessions a game", "style": True, "chip": "pace",
     "hi": "Fastest pace", "lo": "Slowest pace", "group": "Style"},
    {"id": "tpar", "label": "3-point attempt rate", "dir": "higher", "fmt": "pct1", "unit": "of shots from three", "style": True,
     "hi": "Most threes", "lo": "Fewest threes", "group": "Style"},
    {"id": "efg", "label": "Effective FG", "dir": "higher", "fmt": "pct1", "unit": "shooting", "chip": "shooting", "group": "Four factors"},
    {"id": "opp_efg", "label": "Opponent effective FG", "dir": "lower", "fmt": "pct1", "unit": "allowed", "chip": "shooting defence", "group": "Four factors"},
    {"id": "tov_pct", "label": "Turnover rate", "dir": "lower", "fmt": "pct1", "unit": "of possessions", "chip": "ball security", "group": "Four factors"},
    {"id": "opp_tov_pct", "label": "Forced turnover rate", "dir": "higher", "fmt": "pct1", "unit": "of opponent possessions", "chip": "forcing turnovers", "group": "Four factors"},
    {"id": "orb_pct", "label": "Offensive rebound rate", "dir": "higher", "fmt": "pct1", "unit": "of misses", "chip": "offensive rebounding", "group": "Four factors"},
    {"id": "drb_pct", "label": "Defensive rebound rate", "dir": "higher", "fmt": "pct1", "unit": "of opponent misses", "chip": "defensive rebounding", "group": "Four factors"},
    {"id": "ftr", "label": "Free-throw rate", "dir": "higher", "fmt": "3", "unit": "FTA per FGA", "chip": "getting to the line", "group": "Four factors"},
    {"id": "fg3", "label": "3-point %", "dir": "higher", "fmt": "pct1", "unit": "made", "chip": "3-point shooting", "group": "Shooting"},
    {"id": "opp_fg3", "label": "Opponent 3-point %", "dir": "lower", "fmt": "pct1", "unit": "allowed", "chip": "3-point defence", "group": "Shooting"},
    {"id": "mov", "label": "Average margin", "dir": "higher", "fmt": "+1", "unit": "points a game", "group": "Results"},
]
QUAD = {"x": "model_off", "y": "model_def", "flipY": True, "xName": "Adjusted offence: points per 100 possessions",
        "yName": "Adjusted defence: points allowed per 100 (fewer is higher)",
        "corners": {"tl": "Defence first", "tr": "Good at both", "bl": "Work to do", "br": "Offence first"}}


def chances_of(sim_teams: dict, league: str) -> dict:
    """{metric: {team: p}} from season.json sim.teams (or the simulation's own teams dict); a metric no team has
    (the WNBA's division) is left out."""
    out = {}
    for m in metrics(league):
        cur = {str(t): v.get(m["key"]) for t, v in (sim_teams or {}).items() if isinstance(v, dict) and v.get(m["key"]) is not None}
        if cur:
            out[m["key"]] = cur
    return out


def asof_runner(league: str, season: int, n: int = REBUILD_N, ctx=None) -> Callable[[str], dict | None]:
    """run_asof(day) -> {metric: {team: p}} from the season simulation with through = the day before (results before
    `day`). With the build's SeasonContext the ratings are ctx.ratings_before(day): fitted on the games strictly before
    that day from the season's preseason prior, the same walk-forward fit behind the published pre-game chances; without
    one the simulation fits its own (slower: ratings.for_season)."""
    def run(day: str) -> dict | None:
        from oddsmarkets.basketball.models import season_sim as SS
        d = date.fromisoformat(day)
        prev = (d - timedelta(days=1)).isoformat()
        if ctx is not None:
            res = SS.simulate(league, int(season), n=n, seed=0, state={"store": ctx.member_store, "through": prev,
                                                                       "ratings": ctx.ratings_before(d)})
        else:
            res = SS.for_season(league, int(season), n=n, seed=0, through=prev)
        if res.get("ok") is False or not res.get("teams"):
            return None
        return chances_of(res.get("teams") or {}, league)
    return run


def up_games(cards: list[dict]) -> bool:
    """Any game still to play (a postseason in progress)."""
    return any(c.get("status") != "post" and c.get("stype") in ("reg", "post", "playin") for c in cards)


def _days(cards: list[dict]) -> tuple[str | None, str | None]:
    """(first, last) regular-season game day (UTC date of the start)."""
    ds = sorted(str(c.get("date"))[:10] for c in cards if c.get("stype") == "reg" and c.get("date"))
    return (ds[0], ds[-1]) if ds else (None, None)


def build(league: str, season: int, season_payload: dict, teams_payload: dict | None, cards: list[dict], race_log: dict | None,
          now: datetime, run_asof: Callable[[str], dict | None] | None = None, budget_s: float = REBUILD_BUDGET_S) -> tuple[dict | None, dict]:
    """(season.json["league_block"] or None, the race log to write)."""
    sp = season_payload or {}
    sim_teams = ((sp.get("sim") or {}).get("teams")) or {}
    log = dict(race_log or {}) if isinstance(race_log, dict) else {}
    st = sp.get("standings") or {}
    rows = [dict(r, conf=c) for c, rs in st.items() if isinstance(rs, list) for r in rs if r and r.get("team") is not None]
    if not rows:
        return None, log
    teams = [str(r["team"]) for r in rows]
    by = {str(r["team"]): r for r in rows}
    info = sp.get("teams") or {}
    abbr = {t: str((info.get(t) or {}).get("abbr") or t) for t in teams}
    phase = str(sp.get("phase") or "regular")
    fmt = sp.get("format") or {}
    today = LG._day(now)
    cur = chances_of(sim_teams, league)
    first, last = _days(cards)
    done_reg = all(c.get("status") == "post" for c in cards if c.get("stype") == "reg") and bool(first)
    seas = LG.race_season(log, season)
    # a season that is over (no game left to play): today's snapshot would be a flat line of 0s and 1s, so the log takes
    # none; the page shows the race as it unfolded (rebuilt through the day after the regular season's last day). A
    # postseason in progress keeps taking live snapshots (the title race).
    take_live = bool(cur) and (not done_reg or up_games(cards))
    if take_live:
        seas = LG.roll_race(seas, today, cur)
    if run_asof is not None and first:
        meta = seas.get(LG.META) or {}
        live_from = meta.get("live_from") or today
        if done_reg and not meta.get("live_from") and not up_games(cards):
            live_from = (date.fromisoformat(last) + timedelta(days=2)).isoformat()   # through the last day's results
        dates = LG.rebuild_dates(first, live_from, REBUILD_STEP_DAYS.get(league, 3),
                                 also=[(date.fromisoformat(last) + timedelta(days=1)).isoformat()] if done_reg else None)
        seas, done = LG.backfill(seas, dates, run_asof, budget_s=budget_s, n=REBUILD_N)
        if done:
            logger.info("race log %s %s: rebuilt %d dates (%s .. %s)", league, season, len(done), done[0], done[-1])
    log[str(season)] = seas

    results = LG.norm_results([{"date": c.get("date"), "home": c.get("home"), "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"),
                                "ot": (c.get("period") or 0) > 4} for c in cards
                               if c.get("status") == "post" and c.get("stype") in ("reg", "post", "playin")])
    reg_results = LG.norm_results([{"date": c.get("date"), "home": c.get("home"), "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"),
                                    "ot": (c.get("period") or 0) > 4} for c in cards if c.get("status") == "post" and c.get("stype") == "reg"])
    tp = (teams_payload or {}).get("teams") or {}
    R = sp.get("ratings") or {}
    rating = {t: (R.get(t) or {}).get("net") for t in teams}
    sd = sp.get("schedule_difficulty") or {}
    if sd:
        sos_l = {t: {"avg": (sd.get(t) or {}).get("remaining"), "n": (sd.get(t) or {}).get("n_remaining") or 0} for t in teams}
        sos_p = {t: {"avg": (sd.get(t) or {}).get("played"), "n": (sd.get(t) or {}).get("n_played") or 0} for t in teams}
    else:
        left = [c for c in cards if c.get("stype") == "reg" and c.get("status") != "post"]
        played = [c for c in cards if c.get("stype") == "reg" and c.get("status") == "post"]
        sos_l, sos_p = LG.schedule_strength(left, rating, teams), LG.schedule_strength(played, rating, teams)
    rk_l = LG.ranks({t: v["avg"] for t, v in sos_l.items() if v["n"]}, high_first=True)
    rk_p = LG.ranks({t: v["avg"] for t, v in sos_p.items() if v["n"]}, high_first=True)
    league_wide = fmt.get("seeding") == "league"
    conf = {t: by[t].get("conf") for t in teams}
    rivals = (lambda t: teams) if league_wide else (lambda t: [x for x in teams if conf.get(x) == conf.get(t)])
    pick = (cur.get("p_playoffs") or {})
    settled = bool(pick) and all(v in (0, 1, 0.0, 1.0) for v in pick.values())
    metric = "p_title" if phase == "playoffs" or settled else "p_playoffs"
    if done_reg and settled and phase != "playoffs" or (done_reg and settled and not up_games(cards)):
        metric = "p_playoffs"                      # a finished season: the race the page shows is the regular season's
    mv = None
    if not (done_reg and settled):
        mv = LG.movers(seas, metric, cur.get(metric) or {}, now, results, rivals, abbr, rating, rk_l)

    from oddsmarkets.common import featured as FT
    up = [{"id": c.get("id"), "start": c.get("date"), "home": c.get("home"), "away": c.get("away"), "p_home": (c.get("model") or {}).get("p_home")}
          for c in cards if c.get("status") != "post" and c.get("stype") in ("reg", "post", "playin")]
    nxt = {str(t): (v.get("next") or v.get("next_game") or {}) for t, v in sim_teams.items()}

    def sig(g):
        oh, oa = sim_teams.get(str(g["home"])) or {}, sim_teams.get(str(g["away"])) or {}
        return FT.stakes_points({"sig": {"playoff": [oh.get("p_playoffs"), oa.get("p_playoffs")], "title": [oh.get("p_title"), oa.get("p_title")]}})
    games = LG.matter_games(up, nxt, metric, now, sig=sig)

    n_games = int(fmt.get("games") or 82)
    race = {}
    for t in teams:
        s = sim_teams.get(t) or {}
        r = by[t]
        left_n = max(0, n_games - int(r.get("w") or 0) - int(r.get("l") or 0))
        mg_d, tg_d = s.get("magic") or {}, s.get("tragic") or {}
        key = next((k for k in ("postseason", "playoffs", "top6") if k in mg_d or k in tg_d), "postseason")
        mg, tg = mg_d.get(key), tg_d.get(key)
        cl, el = s.get("clinched") or {}, s.get("eliminated") or {}
        p = s.get("p_playoffs")
        status = "clinched" if cl.get(key) else "out" if el.get(key) else None
        nx = nxt.get(t) or {}
        race[t] = {k: v for k, v in {
            # shown once within reach: at most half the games left (a magic number of 80 in October says nothing)
            "magic": mg if isinstance(mg, (int, float)) and 0 < mg <= left_n / 2 else None,
            "elim": tg if isinstance(tg, (int, float)) and 0 < tg <= left_n / 2 and not status else None,
            "unit": "wins",
            "status": status,
            "all_sims": "in" if (p is not None and p >= 0.9995 and not status) else "out" if (p is not None and p <= 0.0005 and not status) else None,
            "sos": [LG._r(sos_l[t]["avg"], 2), rk_l.get(t), sos_l[t]["n"]] if sos_l[t]["n"] else None,
            "sos_played": [LG._r(sos_p[t]["avg"], 2), rk_p.get(t), sos_p[t]["n"]] if sos_p[t]["n"] else None,
            "next": {"id": nx.get("game") or nx.get("game_id"), "date": nx.get("date"), "opp": nx.get("opp"), "home": nx.get("home"),
                     "p": LG._r(nx.get("p_win"), 3), "w": LG._r((nx.get("if_win") or {}).get(metric), 3),
                     "l": LG._r((nx.get("if_loss") or {}).get(metric), 3)} if nx.get("opp") else None,
        }.items() if v is not None}

    vals, gp = {}, {}
    for t in teams:
        v = ((tp.get(t) or {}).get("values")) or {}
        rr = R.get(t) or {}
        row = {m["id"]: v.get(m["id"]) for m in SPEC}
        for k, rk in (("model_net", "net"), ("model_off", "off"), ("model_def", "def"), ("pace", "pace")):
            if row.get(k) is None and rr.get(rk) is not None:
                row[k] = rr.get(rk)
        vals[t] = row
        gp[t] = int(by[t].get("w") or 0) + int(by[t].get("l") or 0)
    prof = LG.profile(vals, SPEC, gp, MIN_GP)
    early = all(g < MIN_GP for g in gp.values())
    exp = PYTH_EXP.get(league, 14.0)
    lk_in = {}
    for t in teams:
        g = gp[t]
        # the regular season's results only (the record and the Pythagorean record are both regular-season numbers)
        me = LG.team_window(reg_results, t, "0000-00-00")
        pf = sum(x["gf"] for x in me["games"])
        pa = sum(x["ga"] for x in me["games"])
        pe = LG.pythag(pf, pa, g, exp) if me["games"] else None
        if pe is None or not g:
            continue
        lk_in[t] = {"gp": g, "actual": by[t].get("w"), "expected": pe * g, "close": LG.close_record(reg_results, t, 3)}
    thr = max(1.5, 0.45 * math.sqrt(max(gp.values() or [0])))
    lk = LG.luck(lk_in, thr)
    ch = {t: LG.chips(t, prof, SPEC, len(teams), overall="model_net", luck=lk.get(t), sos_rank=rk_l.get(t) if not done_reg else None,
                      early=gp[t] < MIN_GP) for t in teams}
    tier_phase = "complete" if done_reg and settled and any((cur.get("p_title") or {}).get(t, 0) >= 0.9999 for t in teams) else \
        ("postseason" if settled else phase)
    tl = LG.tiers(cur.get("p_playoffs") or {}, cur.get("p_title") or {}, tier_phase, len(teams))
    ms = [m for m in metrics(league) if m["key"] in cur]
    blk = LG.block(now=now, phase=phase, metrics=ms, current=cur, seas=seas, movers_=mv, games=games, race=race, prof=prof,
                   spec=SPEC, chips_=ch, luck_=lk, tiers_=tl, quad=QUAD, early=early, min_gp=MIN_GP, gp=gp, values=vals,
                   notes={"sos_unit": "points per 100: the average opponent's net rating (ours)", "luck_unit": "wins",
                          "luck_basis": f"wins against the Pythagorean wins from points scored and allowed, exponent {exp:g}",
                          "close": "games decided by 3 points or fewer, or in overtime", "metric": metric, "rebuild_n": REBUILD_N,
                          "luck_threshold": round(thr, 1), "season_over": bool(done_reg)})
    return blk, log
