"""The Bullpen's league block (season.json["league"]) and race log (data/<level>/race_log.json): how the races are
shaping up and each club's strengths and weaknesses, on the shared engine oddsmarkets/common/league.py (the Rink's
oddsmarkets/nhl/analytics/race.py is the reference).

Reads only payload dicts (season.json, teams.json, the schedule cards) plus the race log, so it runs on a deployed copy
as well as inside the build.

The race history. The site began keeping a daily log of our chances on 24 Oct 2026, in the World Series. The dates
before that are rebuilt (`asof_runner`) without look-ahead:
  * regular season, every REBUILD_STEP_DAYS from the end of the first week to the day after the last regular-season
    game: season_sim.regular_season(store, through=<date>) with REBUILD_N simulations. Its team ratings are the run
    differential of the games before that date, regressed to average (season_sim.team_ratings): the ratings model,
    not the full game model (probable pitchers, lineups) the live site uses, and no preseason projection, so the
    rebuilt April chances are flatter than the ones we published then;
  * postseason, every POST_STEP_DAYS from the first postseason day: season_sim.postseason on a copy of the store in
    which every postseason game on or after that date is unplayed (the regular-season ratings decide the games).
Triple-A has no season simulation (its playoff format is not modelled), so its block carries the strengths and
weaknesses, the luck and the shape of the league, with no chances and no race history.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Callable

from oddsmarkets.common import league as LG

logger = logging.getLogger(__name__)

METRICS = [{"key": "p_postseason", "label": "Postseason"}, {"key": "p_div", "label": "Division"}, {"key": "p_ws", "label": "World Series"}]
REBUILD_N = 2000
REBUILD_STEP_DAYS = 7
POST_STEP_DAYS = 2
REBUILD_BUDGET_S = 90.0
MIN_GP = 20
POST_GTYPES = ("F", "D", "L", "W")

# the spec's team set (docs/_design/metrics/baseball.json "teams") from teams.json values, plus the rotation, bullpen and
# lineup dimensions; chip: the dimension's name in a sentence ("Bullpen is the weak spot")
SPEC = [
    {"id": "rating", "label": "Team rating", "dir": "higher", "fmt": "+2", "unit": "runs a game v average", "model": True, "group": "Overall"},
    {"id": "baseruns_pct", "label": "BaseRuns win%", "dir": "higher", "fmt": "3", "unit": "the record the play deserved", "group": "Overall"},
    {"id": "off_rpg", "label": "Offence", "dir": "higher", "fmt": "+2", "unit": "runs a game, park-adjusted", "chip": "lineup", "group": "Lineup"},
    {"id": "woba", "label": "Lineup wOBA", "dir": "higher", "fmt": "3", "unit": "home park included", "group": "Lineup"},
    {"id": "k_pct", "label": "Strikeout rate", "dir": "lower", "fmt": "pct1", "unit": "of plate appearances", "group": "Lineup"},
    {"id": "barrel_pct", "label": "Barrel rate", "dir": "higher", "fmt": "pct1", "unit": "of batted balls", "chip": "power", "group": "Lineup"},
    {"id": "war_sp", "label": "Rotation WAR", "dir": "higher", "fmt": "1", "unit": "the starters", "chip": "rotation", "group": "Pitching"},
    {"id": "war_rp", "label": "Bullpen WAR", "dir": "higher", "fmt": "1", "unit": "the relievers", "chip": "bullpen", "group": "Pitching"},
    {"id": "pit_rpg", "label": "Pitching", "dir": "higher", "fmt": "+2", "unit": "runs a game saved", "group": "Pitching"},
    {"id": "stuff_plus", "label": "Staff Stuff+", "dir": "higher", "fmt": "0", "unit": "100 = average", "group": "Pitching"},
    {"id": "def_rpg", "label": "Defence", "dir": "higher", "fmt": "+2", "unit": "runs a game, fielding and framing", "chip": "defence", "group": "Defence"},
    {"id": "framing_runs", "label": "Framing", "dir": "higher", "fmt": "+1", "unit": "runs from the catchers", "group": "Defence"},
]
QUAD = {"x": "off_rpg", "y": "prev_rpg", "flipY": False, "xFmt": "2",
        "xName": "Run scoring: runs a game above average", "yName": "Run prevention: runs a game saved (pitching and defence)",
        "sub": "Up and right is better; dashed: the league average", "corners": {"tl": "Run prevention first", "tr": "Good at both", "bl": "Work to do", "br": "Run scoring first"}}


# ───────────────────────────────────────────────────────────── inputs from the payloads
def standings_rows(sp: dict) -> list[dict]:
    """season.json standings ({division: [row]} or [row]) as a flat list of rows with a string tid."""
    st = (sp or {}).get("standings") or {}
    out = []
    if isinstance(st, dict):
        for div, rows in st.items():
            for r in rows if isinstance(rows, list) else []:
                if isinstance(r, dict) and r.get("tid") is not None:
                    out.append(dict(r, tid=str(r["tid"]), division=r.get("division") or div))
    elif isinstance(st, list):
        out = [dict(r, tid=str(r.get("tid"))) for r in st if isinstance(r, dict) and r.get("tid") is not None]
    return out


def _div_flag(r: dict) -> float | None:
    if r.get("div_winner") is True or str(r.get("clinched") or "") in ("y", "z"):
        return 1.0
    if r.get("div_winner") is False:
        return 0.0
    return None


def current_chances(sp: dict, rows: list[dict], phase: str) -> dict:
    """{metric: {tid: p}} from the standings rows, the simulation and the postseason block."""
    sim = ((sp.get("sim") or {}).get("teams")) or ((sp.get("regular") or {}).get("teams")) or {}
    pt = ((sp.get("postseason") or {}).get("teams")) or {}
    done = phase in ("postseason", "complete")
    out: dict = {m["key"]: {} for m in METRICS}
    for r in rows:
        t = r["tid"]
        s = sim.get(t) if isinstance(sim.get(t), dict) else {}
        pp = r.get("p_postseason", s.get("p_postseason"))
        if pp is not None:
            out["p_postseason"][t] = pp
        pd_ = r.get("p_division", s.get("p_division"))
        if pd_ is None and done:
            pd_ = _div_flag(r)
        if pd_ is not None:
            out["p_div"][t] = pd_
        ws = (pt.get(t) or {}).get("p_ws", r.get("p_ws", s.get("p_ws")))
        if ws is None and done and pp == 0:
            ws = 0.0
        if ws is not None:
            out["p_ws"][t] = ws
    return {m: v for m, v in out.items() if v}


def _cut_postseason(store: dict, day: str) -> dict:
    """A copy of the store in which every postseason game on or after `day` is unplayed."""
    gs = {}
    for k, g in (store.get("games") or {}).items():
        if str(g.get("gtype") or "R") in POST_GTYPES and str(g.get("date"))[:10] >= day:
            g = dict(g, hs=None, status="Scheduled")
            g["as"] = None
        gs[k] = g
    return dict(store, games=gs)


def asof_runner(level: str, season: int, n: int = REBUILD_N, store: dict | None = None) -> Callable[[str], dict | None]:
    """run_asof(day) -> {metric: {tid: p}}: the regular season as of `day` (results before it), or the postseason
    from `day` on (the bracket as it stood that morning). MLB only."""
    from oddsmarkets.baseball.models import _dio
    from oddsmarkets.baseball.models import season_sim as SS
    st = store if store is not None else _dio.load_store(level, season)
    post_days = sorted(str(g.get("date"))[:10] for g in (st.get("games") or {}).values() if str(g.get("gtype") or "R") in POST_GTYPES)
    first_post = post_days[0] if post_days else None
    final = SS.standings(st) if first_post else None

    def run(day: str) -> dict | None:
        if first_post and day >= first_post:
            res = SS.postseason(_cut_postseason(st, day), n=n, seed=0)
            if not res.get("available", True) or not res.get("teams"):
                return None
            ft = final["teams"]
            ws = {t: float((res["teams"].get(t) or {}).get("p_ws") or 0.0) for t in ft}
            return {"p_postseason": {t: 1.0 if t in res["teams"] else 0.0 for t in ft},
                    "p_div": {t: 1.0 if v.get("div_winner") else 0.0 for t, v in ft.items()}, "p_ws": ws}
        res = SS.regular_season(st, n=n, seed=0, through=day)
        tm = res.get("teams") or {}
        if not tm:
            return None
        return {"p_postseason": {t: float(v["p_postseason"]) for t, v in tm.items()},
                "p_div": {t: float(v["p_division"]) for t, v in tm.items()}, "p_ws": {t: float(v["p_ws"]) for t, v in tm.items()}}
    return run


def rebuild_schedule(cards: list[dict], live_from: str) -> list[str]:
    """The dates to rebuild: weekly from the end of the first week of the regular season to the day after its last
    game, then every POST_STEP_DAYS through the postseason, all before live tracking began."""
    reg = sorted(str(c.get("date"))[:10] for c in cards if str(c.get("gtype") or "R") == "R" and c.get("status") == "final" and c.get("date"))
    post = sorted(str(c.get("date"))[:10] for c in cards if str(c.get("gtype") or "") in POST_GTYPES and c.get("date"))
    if not reg:
        return []
    first = (date.fromisoformat(reg[0]) + timedelta(days=REBUILD_STEP_DAYS)).isoformat()
    after = (date.fromisoformat(reg[-1]) + timedelta(days=1)).isoformat()
    end = min(live_from, post[0]) if post else live_from
    ds = LG.rebuild_dates(first, end, REBUILD_STEP_DAYS, also=[after])
    if post:
        ds += LG.rebuild_dates(post[0], live_from, POST_STEP_DAYS)
    return sorted(set(ds))


# ───────────────────────────────────────────────────────────── the block
def build(level: str, season: int, season_payload: dict, teams_payload: dict | None, cards: list[dict], race_log: dict | None,
          now: datetime, run_asof: Callable[[str], dict | None] | None = None, budget_s: float = REBUILD_BUDGET_S) -> tuple[dict | None, dict]:
    """(season.json["league"] or None, the race log to write)."""
    sp = season_payload or {}
    log = dict(race_log or {}) if isinstance(race_log, dict) else {}
    rows = standings_rows(sp)
    if not rows:
        return None, log
    teams = [r["tid"] for r in rows]
    by = {r["tid"]: r for r in rows}
    abbr = {t: str(by[t].get("abbr") or t) for t in teams}
    phase = str(sp.get("phase") or "regular")
    done = phase in ("postseason", "complete")
    today = LG._day(now)
    # Triple-A has no season simulation: its rows carry placeholder zeros, never chances
    cur = current_chances(sp, rows, phase) if level == "mlb" else {}
    seas = LG.race_season(log, season)
    if cur:
        seas = LG.roll_race(seas, today, cur)
    if run_asof is not None:
        live_from = (seas.get(LG.META) or {}).get("live_from") or today
        dates = rebuild_schedule(cards, live_from)
        seas, got = LG.backfill(seas, dates, run_asof, budget_s=budget_s, n=REBUILD_N)
        if got:
            logger.info("race log %s %s: rebuilt %d dates (%s .. %s)", level, season, len(got), got[0], got[-1])
    if any(m != LG.META for m in seas):
        log[str(season)] = seas
    metrics = [m for m in METRICS if cur.get(m["key"])] if cur else []

    games = [c for c in cards if c.get("status") != "cancelled"]
    results = LG.norm_results([c for c in games if c.get("status") == "final"])
    reg_done = [c for c in games if str(c.get("gtype") or "R") == "R" and c.get("status") == "final"]
    reg_left = [c for c in games if str(c.get("gtype") or "R") == "R" and c.get("status") != "final"]
    rating = {t: by[t].get("rating") for t in teams}
    sos_l = LG.schedule_strength(reg_left, rating, teams)
    sos_p = LG.schedule_strength(reg_done, rating, teams)
    rk_l = LG.ranks({t: v["avg"] for t, v in sos_l.items()}, high_first=True)
    rk_p = LG.ranks({t: v["avg"] for t, v in sos_p.items()}, high_first=True)
    lg_of = {t: by[t].get("league") for t in teams}
    rivals = lambda t: [x for x in teams if lg_of.get(x) == lg_of.get(t)]        # noqa: E731 - the wild-card races
    metric = "p_ws" if done else "p_postseason"
    mv = LG.movers(seas, metric, cur.get(metric) or {}, now, results, rivals, abbr, rating, rk_l) if cur else None

    # the games that matter: each club's next game carries the simulation's if_win / if_loss (no game id in the
    # payload: the next scheduled game involving the club, the series' next game in the postseason)
    up = sorted([c for c in games if c.get("status") not in ("final",) and c.get("home") and c.get("away")],
                key=lambda c: (str(c.get("start") or c.get("date")), str(c.get("gpk"))))
    first_up: dict = {}
    for s in ((sp.get("postseason") or {}).get("series") or []):
        nx = s.get("next") or {}
        if not s.get("done") and nx.get("gpk"):
            for t in s.get("teams") or []:
                first_up.setdefault(str(t), str(nx["gpk"]))
    for c in up:
        for t in (str(c["home"]), str(c["away"])):
            first_up.setdefault(t, str(c.get("gpk")))
    sim = ((sp.get("sim") or {}).get("teams")) or {}
    nxt = {}
    for t in teams:
        x = by[t].get("next") or ((sim.get(t) or {}).get("next") if isinstance(sim.get(t), dict) else None)
        if isinstance(x, dict) and x.get("if_win") and t in first_up:
            nxt[t] = dict(x, game_id=str(x.get("gpk") or first_up[t]))
    upc = [{"id": str(c.get("gpk")), "start": c.get("start") or c.get("date"), "home": str(c["home"]), "away": str(c["away"]),
            "p_home": (c.get("model") or {}).get("p_home")} for c in up]
    from oddsmarkets.common import featured as FT

    def sig(g):
        a, b = by.get(g["home"]) or {}, by.get(g["away"]) or {}
        return FT.stakes_points({"sig": {"playoff": [a.get("p_postseason"), b.get("p_postseason")], "title": [a.get("p_ws"), b.get("p_ws")]}})
    mg = LG.matter_games(upc, nxt, metric, now, sig=sig) if cur else []

    race = {}
    for t in teams:
        r, s = by[t], sim.get(t) if isinstance(sim.get(t), dict) else {}
        m = r.get("magic") if isinstance(r.get("magic"), dict) else (s.get("magic") or {})
        left = sos_l[t]["n"]
        pp = (cur.get("p_postseason") or {}).get(t)
        status = "clinched" if pp is not None and done and pp >= 0.9999 else "out" if pp is not None and done and pp <= 0.0001 else None
        nx = nxt.get(t) or {}
        opp = None
        if nx:
            g = next((c for c in up if str(c.get("gpk")) == nx["game_id"]), None)
            if g:
                opp = {"id": nx["game_id"], "date": str(g.get("date"))[:10], "opp": str(g["away"]) if str(g["home"]) == t else str(g["home"]),
                       "home": str(g["home"]) == t, "p": LG._r(nx.get("p_win"), 3), "w": LG._r((nx.get("if_win") or {}).get(metric), 3),
                       "l": LG._r((nx.get("if_loss") or {}).get(metric), 3)}
        dm = m.get("division_magic")
        race[t] = {k: v for k, v in {
            # the division magic number (wins plus division-rival losses), once within reach
            "magic": dm if isinstance(dm, (int, float)) and 0 < dm <= left and not done else None,
            "unit": "wins",
            "status": status,
            "all_sims": None if done else ("in" if pp is not None and pp >= 0.9995 else "out" if pp is not None and pp <= 0.0005 else None),
            "sos": [sos_l[t]["avg"], rk_l.get(t), left] if left else None,
            "sos_played": [sos_p[t]["avg"], rk_p.get(t), sos_p[t]["n"]] if sos_p[t]["n"] else None,
            "next": opp,
        }.items() if v is not None}

    # strengths and weaknesses
    tp = ((teams_payload or {}).get("teams")) or {}
    vals, gp = {}, {}
    for t in teams:
        v0 = ((tp.get(t) or {}).get("values")) or {}
        v = {m["id"]: v0.get(m["id"]) for m in SPEC}
        if v.get("rating") is None:
            v["rating"] = by[t].get("rating")
        for k, rk in (("off_rpg", "off"), ("def_rpg", "def"), ("pit_rpg", "pit")):
            if v.get(k) is None:
                v[k] = by[t].get(rk)
        if v.get("pit_rpg") is not None and v.get("def_rpg") is not None:
            v["prev_rpg"] = round(v["pit_rpg"] + v["def_rpg"], 3)
        vals[t] = v
        gp[t] = int((by[t].get("w") or 0) + (by[t].get("l") or 0))
    # a metric is ranked only with three or more clubs carrying it and some spread (all-equal values would make every
    # club "Best")
    spec = [m for m in SPEC if len({vals[t].get(m["id"]) for t in teams if vals[t].get(m["id"]) is not None}) >= 3]
    prof = LG.profile(vals, spec, gp, MIN_GP)
    early = all(g < MIN_GP for g in gp.values())
    lk_in = {}
    reg_results = LG.norm_results(reg_done)
    for t in teams:
        v0 = ((tp.get(t) or {}).get("values")) or {}
        xw = v0.get("baseruns_w")
        if xw is None:
            xw = by[t].get("pythag_w", v0.get("pythag_w"))
        if xw is None or not gp[t]:
            continue
        lk_in[t] = {"gp": gp[t], "actual": by[t].get("w"), "expected": xw,
                    "close": LG.close_record(reg_results, t, 1)}
    thr = max(1.5, 0.4 * math.sqrt(max(gp.values() or [0])))
    lk = LG.luck(lk_in, thr)
    ch = {t: LG.chips(t, prof, spec, len(teams), overall="rating", luck=lk.get(t), sos_rank=rk_l.get(t) if sos_l[t]["n"] else None,
                      early=gp[t] < MIN_GP) for t in teams}
    tl = LG.tiers(cur.get("p_postseason") or {}, cur.get("p_ws") or {}, phase, len(teams)) if cur else []
    basis = "BaseRuns" if any(((tp.get(t) or {}).get("values") or {}).get("baseruns_w") is not None for t in teams) else "Pythagorean"
    blk = LG.block(now=now, phase=phase, metrics=metrics, current=cur, seas=seas, movers_=mv, games=mg, race=race, prof=prof,
                   spec=[{k: v for k, v in m.items()} for m in spec], chips_=ch, luck_=lk, tiers_=tl, quad=QUAD, early=early, min_gp=MIN_GP,
                   gp=gp, values=vals,
                   notes={"sos_unit": "runs a game: the average opponent's rating (ours)", "luck_unit": "wins",
                          "luck_basis": ("wins against BaseRuns wins: the record the hits, walks and outs deserved" if basis == "BaseRuns"
                                         else "wins against Pythagorean wins from runs scored and allowed (exponent 1.83)"),
                          "close": "one-run regular-season games", "metric": metric, "rebuild_n": REBUILD_N,
                          "rebuild": "Rebuilt dates: the regular season from run-differential ratings (results before each date, regressed to "
                                     "average; not the full game model, no preseason projection), the postseason with the bracket as it stood",
                          "luck_threshold": round(thr, 1)})
    if not cur:
        blk["notes"]["no_sim"] = "No season simulation at this level: no chances or race history."
    return blk, log
