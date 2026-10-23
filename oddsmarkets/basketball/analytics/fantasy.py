"""
Fantasy basketball layer for The Quant Hardwood (docs/VALUE_SECTIONS.md section 5; payload fantasy.json, PAYLOADS.md
"Valuation, moves and fantasy"; the walk-forward check is research/fantasy_backtest.py -> fantasy_backtest.json).

Everything here is built from our own models and ESPN's box scores, schedule and injury report. No fantasy
platform's rankings, ownership or ADP are used (their terms do not allow reuse), so "available on waivers" is a
proxy (below), and the points formats are our presets, editable on the page.

Per-game projection of player p in game g
-----------------------------------------
    E[stat] = P(play) x minutes x rate_stat x pace_factor x opponent_factor_stat
rate_stat      per-minute rates from the impact model's projections (models/impact.py `projections`: the player's
               games this season and last weighted 0.5^(k/60), shrunk to his position pool with 250 pseudo-minutes)
minutes        the team's depth chart (analytics/value.py baseline_minutes: each player's recent minutes, half-life
               12 games, capped at 0.8 of a game, five players' worth), rebuilt without the players the injury report
               rules out (value.apply_moves: their minutes go to the next players up at their position); while a
               rotation player is out, the team's shot attempts, free throws, assists, turnovers and rebounds per
               minute are kept at the healthy team's (USAGE_KEEP of the missing volume is redistributed to the active
               players in proportion to their own rates), the "usage bump"
rest           minutes and the chance of playing by the team's days of rest (0 = second night of a back-to-back, 1,
               2, 3+), fitted on the last REST_SEASONS completed seasons' box scores (rotation players, 20+ minutes a
               game): the ratio to the player's own season average
pace_factor    the opponent's pace over the league's (ratings: possessions per 48)
opponent       per category, what the opponent allows per 100 possessions over the league average, this season's games
               plus half-weighted last season's, shrunk with OPP_K team-games
P(play)        availability (valuation v2: share of team games played over two seasons, regressed) x the rest factor;
               0 while the injury report rules him out (until ESPN's return date, else the next 7 days for "Out"),
               DTD_PLAY for day-to-day on the next game
blend          the game line is then blended with the player's season-to-date per-game line, weight STD_BLEND (0.5)
               x min(1, games / STD_FULL (20)) from his third game: chosen in the walk-forward backtest
               (research/fantasy_backtest.py), where it beat both the model alone and the season-to-date average

Formats
-------
9-category: PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO; per-game z-scores over the top POOL_N players (12 teams x 13),
percentages weighted by attempts ((pct - pool pct) x attempts), turnovers negative; punting drops a category; the
page recomputes the pool and ranks for the chosen punts. Points: editable weights (presets below are ours).

Weeks, streaming, waivers, luck
-------------------------------
Weeks run Monday-Sunday (US dates). Team weeks list games, back-to-backs and light-slate games (days with at most
LIGHT_DAY games, when fewer fantasy teams can start players). Waiver targets (no ownership data): players outside
the season-start top WAIVER_LINE whose projection now ranks inside it; drop candidates the reverse. Buy-low /
sell-high: shooting luck this season in points a game = (points per shot - (expected points per shot from the shot
model + his shot-making over the two previous seasons, shrunk with 250 pseudo-shots)) x shots a game; three-point
and free-throw luck likewise against his previous seasons' percentages shrunk to the league's.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import value as VAL

logger = logging.getLogger(__name__)

VERSION = 1
STATS = ["pts", "reb", "ast", "stl", "blk", "tpm", "tpa", "fgm", "fga", "ftm", "fta", "tov"]
CATS9 = ["pts", "reb", "ast", "stl", "blk", "tpm", "fg", "ft", "tov"]
CAT_LABELS = {"pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK", "tpm": "3PM", "fg": "FG%", "ft": "FT%", "tov": "TO"}
PRESETS = {
    "standard": {"label": "Standard points (ours)", "w": {"pts": 1, "tpm": 1, "fgm": 2, "fga": -1, "ftm": 1, "fta": -1, "reb": 1, "ast": 2,
                                                         "stl": 4, "blk": 4, "tov": -2}},
    "simple": {"label": "Simple points", "w": {"pts": 1, "reb": 1.2, "ast": 1.5, "stl": 3, "blk": 3, "tov": -1}},
    "daily": {"label": "Daily-fantasy style", "w": {"pts": 1, "tpm": 0.5, "reb": 1.25, "ast": 1.5, "stl": 2, "blk": 2, "tov": -0.5,
                                                    "dd": 1.5, "td": 3}},
}
POOL_N = 156
WAIVER_LINE = 150
LIGHT_DAY = 5
REST_SEASONS = 3
OPP_K = 20.0
USAGE_KEEP = 1.0
DTD_PLAY = 0.6
OUT_DAYS = 7
WEEKS = 2
MIN_MPG = 4.0
DD_K = 5.0
SHOT_K = 250.0
LUCK_LINE = 1.0                      # points a game of shooting luck that flags buy-low / sell-high
STD_BLEND = 0.5                     # weight of the season-to-date per-game line (chosen in the backtest)
STD_FULL = 20.0                     # games of this season at which that weight is reached
TEAM_CONSERVED = ("fga", "tpa", "fta", "ast", "tov", "reb")


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)


def points(stats: dict, w: dict) -> float:
    return float(sum(float(w.get(k, 0.0)) * float(stats.get(k) or 0.0) for k in w))


# ---------------------------------------------------------------------------------------------- dates and schedule

def game_day(g: dict) -> date | None:
    from oddsmarkets.basketball.models._games import local_day
    return local_day(g)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def team_schedule(games: dict, teams: Iterable[str]) -> dict[str, list[dict]]:
    """{team: [{"id","day","opp","home","rest","status"}]} for the regular season, in date order; rest = days since the
    team's previous game minus one (0 = second night of a back-to-back; 3 = three or more, or the opener)."""
    teams = set(teams)
    by: dict[str, list[dict]] = {t: [] for t in teams}
    for gid, g in games.items():
        if g.get("stype") not in ("reg", "cup"):
            continue
        d = game_day(g)
        if d is None:
            continue
        for t, o, h in ((g.get("home"), g.get("away"), 1), (g.get("away"), g.get("home"), 0)):
            if t in by:
                by[t].append({"id": gid, "day": d, "opp": o, "home": h, "status": g.get("status")})
    for t, lst in by.items():
        lst.sort(key=lambda x: (x["day"], x["id"]))
        prev = None
        for x in lst:
            x["rest"] = 3 if prev is None else max(0, min(3, (x["day"] - prev).days - 1))
            prev = x["day"]
    return by


def slate_sizes(games: dict) -> dict[date, int]:
    n: dict[date, int] = {}
    for g in games.values():
        if g.get("stype") in ("reg", "cup"):
            d = game_day(g)
            if d is not None:
                n[d] = n.get(d, 0) + 1
    return n


# ---------------------------------------------------------------------------------------------- fitted factors

def rest_factors(frames: list[pd.DataFrame]) -> dict:
    """Minutes ratio and play probability by days of rest for rotation players (20+ minutes a game in that season),
    from completed seasons' regular-season box scores. {"min": {rest: ratio}, "play": {rest: ratio}, "n": {...}}."""
    mins: dict[int, list[float]] = {0: [], 1: [], 2: [], 3: []}
    play: dict[int, list[float]] = {0: [], 1: [], 2: [], 3: []}
    for bx in frames:
        if bx is None or bx.empty:
            continue
        b = bx.copy()
        b["day"] = pd.to_datetime(b["date"])
        tg = b.drop_duplicates(["game_id", "team"])[["game_id", "team", "day"]].sort_values(["team", "day"])
        tg["rest"] = tg.groupby("team")["day"].diff().dt.days.sub(1).clip(lower=0, upper=3).fillna(3).astype(int)
        b = b.merge(tg[["game_id", "team", "rest"]], on=["game_id", "team"], how="left")
        played = b[b["sec"] > 0]
        avg = played.groupby("player_id")["sec"].mean() / 60.0
        rot = set(avg[avg >= 20.0].index)
        p = played[played["player_id"].isin(rot)].copy()
        p["ratio"] = p["sec"] / 60.0 / p["player_id"].map(avg)
        for r, sub in p.groupby("rest"):
            mins[int(r)].append(float(sub["ratio"].mean()) if len(sub) else 1.0)
        # play share: rows of rotation players (box rows include zero-second appearances; DNPs are absent, so count
        # team games in which the player was on the team's books between his first and last game)
        first = played.groupby("player_id")["day"].min()
        last = played.groupby("player_id")["day"].max()
        team_of = played.groupby("player_id")["team"].agg(lambda s: s.mode().iloc[0])
        for pid in rot:
            t = team_of.get(pid)
            sub = tg[(tg["team"] == t) & (tg["day"] >= first[pid]) & (tg["day"] <= last[pid])]
            mine = set(played.loc[(played["player_id"] == pid) & (played["team"] == t), "game_id"])
            for r, s2 in sub.groupby("rest"):
                play[int(r)].append(float(np.mean([g in mine for g in s2["game_id"]])))
    out = {"min": {}, "play": {}}
    base_m = np.mean([x for v in mins.values() for x in v]) if any(mins.values()) else 1.0
    base_p = np.mean([x for v in play.values() for x in v]) if any(play.values()) else 1.0
    for r in range(4):
        out["min"][str(r)] = round(float(np.mean(mins[r]) / base_m), 4) if mins[r] else 1.0
        out["play"][str(r)] = round(float(np.mean(play[r]) / base_p), 4) if play[r] else 1.0
    out["n_seasons"] = len([f for f in frames if f is not None and not f.empty])
    return out


def opponent_factors(cur: pd.DataFrame | None, prev: pd.DataFrame | None, prev_weight: float = 0.5) -> dict[str, dict]:
    """{team: {stat: factor}}: what each team allows per 100 possessions against the league, shrunk with OPP_K
    team-games; FG% and FT% factors are on makes per attempt."""
    rows = []
    for bx, w in ((cur, 1.0), (prev, prev_weight)):
        if bx is None or bx.empty:
            continue
        b = bx[bx["sec"] > 0].copy()
        b["reb"] = b["oreb"] + b["dreb"]
        agg = b.groupby(["game_id", "opp"]).agg(**{s: (s, "sum") for s in STATS}, poss=("team_poss", "first")).reset_index()
        agg["w"] = w
        rows.append(agg)
    if not rows:
        return {}
    a = pd.concat(rows, ignore_index=True)
    a = a[a["poss"] > 20]
    lg = {s: float((a[s] * a["w"]).sum() / (a["poss"] * a["w"]).sum()) for s in STATS}
    lg_fg = float((a["fgm"] * a["w"]).sum() / max(1e-9, (a["fga"] * a["w"]).sum()))
    lg_ft = float((a["ftm"] * a["w"]).sum() / max(1e-9, (a["fta"] * a["w"]).sum()))
    out = {}
    for t, sub in a.groupby("opp"):
        n = float(sub["w"].sum())
        sh = n / (n + OPP_K)
        poss = float((sub["poss"] * sub["w"]).sum())
        f = {}
        for s in STATS:
            r = float((sub[s] * sub["w"]).sum()) / poss if poss else lg[s]
            f[s] = 1.0 + sh * (r / lg[s] - 1.0) if lg[s] > 0 else 1.0
        fg = float((sub["fgm"] * sub["w"]).sum() / max(1e-9, (sub["fga"] * sub["w"]).sum()))
        ft = float((sub["ftm"] * sub["w"]).sum() / max(1e-9, (sub["fta"] * sub["w"]).sum()))
        f["fg_pct"] = 1.0 + sh * (fg / lg_fg - 1.0)
        f["ft_pct"] = 1.0 + sh * (ft / lg_ft - 1.0)
        out[str(t)] = {k: round(v, 4) for k, v in f.items()}
    return out


# ---------------------------------------------------------------------------------------------- rates

def per_minute(impact: dict | None, players: dict) -> dict[str, dict]:
    """{pid: {stat: per minute}} from the impact model's projections (per-36 rates); reb = oreb + dreb."""
    out = {}
    for pid, rec in (((impact or {}).get("players")) or {}).items():
        pj = (rec or {}).get("proj") or {}
        r = pj.get("rates") or {}
        if not r:
            continue
        x = {s: float(r.get(s) or 0.0) / 36.0 for s in ("pts", "ast", "stl", "blk", "tpm", "tpa", "fgm", "fga", "ftm", "fta", "tov")}
        x["reb"] = (float(r.get("oreb") or 0.0) + float(r.get("dreb") or 0.0)) / 36.0
        out[str(pid)] = x
    return out


def pool_rates(rates: dict[str, dict], pools: dict[str, str]) -> dict[str, dict]:
    by: dict[str, list[dict]] = {}
    for pid, r in rates.items():
        by.setdefault(pools.get(pid) or "F", []).append(r)
    return {k: {s: float(np.mean([x[s] for x in v])) for s in v[0]} for k, v in by.items() if v}


def dd_rates(box: pd.DataFrame | None, half_life: float = 30.0) -> dict[str, tuple[float, float]]:
    """{pid: (double-double rate, triple-double rate)} per game played, recent games weighted, shrunk with DD_K games
    of zero."""
    if box is None or box.empty:
        return {}
    b = box[box["sec"] > 0].sort_values("date").copy()
    b["reb"] = b["oreb"] + b["dreb"]
    tens = sum((b[s] >= 10).astype(int) for s in ("pts", "reb", "ast", "stl", "blk"))
    b["dd"] = (tens >= 2).astype(float)
    b["td"] = (tens >= 3).astype(float)
    b["k"] = b.groupby("player_id").cumcount(ascending=False)
    b["w"] = 0.5 ** (b["k"] / half_life)
    g = b.groupby("player_id")
    wsum = g["w"].sum()
    dd = (b["w"] * b["dd"]).groupby(b["player_id"]).sum() / (wsum + DD_K)
    td = (b["w"] * b["td"]).groupby(b["player_id"]).sum() / (wsum + DD_K)
    return {str(k): (float(dd[k]), float(td[k])) for k in dd.index}


# ---------------------------------------------------------------------------------------------- luck

def shooting_luck(cat: dict | None, prev_cats: list[dict | None], box: pd.DataFrame | None, league_tp: float, league_ft: float) -> dict[str, dict]:
    """{pid: {"pps_luck", "tp_luck", "ft_luck", "luck" (points a game), "pps", "xpps", "skill", "fg3", "fg3_exp", "ft", "ft_exp"}}
    for this season's players (see the module docstring)."""
    if box is None or box.empty:
        return {}
    b = box[box["sec"] > 0]
    tot = b.groupby("player_id").agg(gp=("game_id", "nunique"), fga=("fga", "sum"), tpa=("tpa", "sum"), tpm=("tpm", "sum"),
                                     fta=("fta", "sum"), ftm=("ftm", "sum"))
    P = ((cat or {}).get("players")) or {}
    prev_rows = [((c or {}).get("players")) or {} for c in prev_cats]
    out = {}
    for pid, row in tot.iterrows():
        pid = str(pid)
        gp = int(row["gp"])
        if gp < 5:
            continue
        cv = (P.get(pid) or {}).get("values") or {}
        res = {}
        pps, xpps = _f(cv.get("pps")), _f(cv.get("xpps"))
        luck_pps = None
        if pps is not None and xpps is not None and row["fga"] > 0:
            # shot-making over the two previous seasons, shrunk to zero with SHOT_K pseudo-shots
            num = den = 0.0
            for pr in prev_rows:
                pv = (pr.get(pid) or {}).get("values") or {}
                a, x = _f(pv.get("pps")), _f(pv.get("xpps"))
                n = _f(pv.get("fga_total"))
                if a is not None and x is not None:
                    shots = float((pr.get(pid) or {}).get("min") or 0.0) * 0.4   # about 0.4 shots a minute when the count is missing
                    shots = n if n else shots
                    num += (a - x) * shots
                    den += shots
            skill = num / (den + SHOT_K) if den > 0 else 0.0
            luck_pps = (pps - xpps - skill) * float(row["fga"]) / gp
            res.update({"pps": pps, "xpps": xpps, "skill": skill})
        # three-point and free-throw percentages against previous seasons' (shrunk to the league's)
        prev_tp = prev_tpa = prev_ft = prev_fta = 0.0
        for pr in prev_rows:
            pv = (pr.get(pid) or {}).get("values") or {}
            g3, gft = _f(pv.get("fg3")), _f(pv.get("ft"))
            m = float((pr.get(pid) or {}).get("min") or 0.0)
            tpar = _f(pv.get("tpar"))
            if g3 is not None and m > 0:
                att = m * 0.4 * (tpar if tpar is not None else 0.35)
                prev_tp += g3 * att
                prev_tpa += att
            ftr = _f(pv.get("ftr"))
            if gft is not None and m > 0:
                att = m * 0.4 * (ftr if ftr is not None else 0.25)
                prev_ft += gft * att
                prev_fta += att
        exp3 = (prev_tp + 150.0 * league_tp) / (prev_tpa + 150.0)
        expft = (prev_ft + 100.0 * league_ft) / (prev_fta + 100.0)
        tp_luck = ((row["tpm"] / row["tpa"]) - exp3) * 3.0 * row["tpa"] / gp if row["tpa"] >= 20 else 0.0
        ft_luck = ((row["ftm"] / row["fta"]) - expft) * row["fta"] / gp if row["fta"] >= 15 else 0.0
        res.update({"fg3": row["tpm"] / row["tpa"] if row["tpa"] else None, "fg3_exp": exp3, "ft": row["ftm"] / row["fta"] if row["fta"] else None,
                    "ft_exp": expft, "tp_luck": tp_luck, "ft_luck": ft_luck, "pps_luck": luck_pps, "gp": gp})
        res["luck"] = (luck_pps if luck_pps is not None else tp_luck) + ft_luck
        out[pid] = res
    return out


# ---------------------------------------------------------------------------------------------- z-scores and ranks

def nine_cat(per_game: dict[str, dict], cats: Iterable[str] = CATS9, pool_n: int = POOL_N, iters: int = 2) -> dict[str, dict]:
    """{pid: {cat: z, "total": sum}} per-game 9-category z-scores against the top `pool_n` players (re-picked
    `iters` times by total)."""
    cats = list(cats)
    ids = list(per_game)
    if not ids:
        return {}
    X = {c: np.zeros(len(ids)) for c in CATS9}
    fga = np.array([per_game[p]["fga"] for p in ids])
    fta = np.array([per_game[p]["fta"] for p in ids])
    fgm = np.array([per_game[p]["fgm"] for p in ids])
    ftm = np.array([per_game[p]["ftm"] for p in ids])
    for c in ("pts", "reb", "ast", "stl", "blk", "tpm", "tov"):
        X[c] = np.array([per_game[p][c] for p in ids])
    pool = np.argsort(-(X["pts"] + X["reb"] + X["ast"]))[:pool_n]
    z = {}
    for _ in range(max(1, iters)):
        fg_pct = fgm[pool].sum() / max(1e-9, fga[pool].sum())
        ft_pct = ftm[pool].sum() / max(1e-9, fta[pool].sum())
        X["fg"] = fgm - fg_pct * fga
        X["ft"] = ftm - ft_pct * fta
        z = {}
        for c in CATS9:
            mu, sd = float(np.mean(X[c][pool])), float(np.std(X[c][pool])) or 1.0
            z[c] = (X[c] - mu) / sd * (-1.0 if c == "tov" else 1.0)
        total = sum(z[c] for c in cats)
        pool = np.argsort(-total)[:pool_n]
    total = sum(z[c] for c in cats)
    return {p: {**{c: float(z[c][i]) for c in CATS9}, "total": float(total[i])} for i, p in enumerate(ids)}


def tiers(values: list[float], min_size: int = 3, k: float = 1.6) -> list[int]:
    """Tier numbers for values sorted best first: a new tier starts where the gap to the next value exceeds k times
    the median gap of the list (and the current tier has at least min_size players)."""
    if not values:
        return []
    gaps = [values[i] - values[i + 1] for i in range(len(values) - 1)]
    med = float(np.median([g for g in gaps if g > 0])) if any(g > 0 for g in gaps) else 0.0
    out, t, size = [], 1, 0
    for i, v in enumerate(values):
        out.append(t)
        size += 1
        if i < len(gaps) and med > 0 and gaps[i] > k * med and size >= min_size:
            t += 1
            size = 0
    return out


def game_stats(r: dict, mins: float, pf: float, of: dict, bump: dict) -> dict:
    """Expected box line for one game: per-minute rates x minutes x pace factor x the opponent's factors, with the
    usage bump on the team-conserved stats; points follow the bumped makes at the player's own efficiency."""
    vol = mins * pf
    b = lambda s: float(bump.get(s, 1.0))  # noqa: E731
    o = lambda s: float(of.get(s, 1.0))    # noqa: E731
    g = {"fga": r.get("fga", 0.0) * vol * b("fga") * o("fga"), "tpa": r.get("tpa", 0.0) * vol * b("tpa") * o("tpa"),
         "fta": r.get("fta", 0.0) * vol * b("fta") * o("fta")}
    g["fgm"] = r.get("fgm", 0.0) * vol * b("fga") * o("fga") * o("fg_pct")
    g["tpm"] = r.get("tpm", 0.0) * vol * b("tpa") * o("tpm")
    g["ftm"] = r.get("ftm", 0.0) * vol * b("fta") * o("fta") * o("ft_pct")
    den = 2.0 * r.get("fgm", 0.0) + r.get("tpm", 0.0) + r.get("ftm", 0.0)
    shot_bump = (2.0 * r.get("fgm", 0.0) * b("fga") + r.get("tpm", 0.0) * b("tpa") + r.get("ftm", 0.0) * b("fta")) / den if den > 1e-9 else 1.0
    g["pts"] = r.get("pts", 0.0) * vol * o("pts") * shot_bump
    g["reb"] = r.get("reb", 0.0) * vol * b("reb") * o("reb")
    g["ast"] = r.get("ast", 0.0) * vol * b("ast") * o("ast")
    g["tov"] = r.get("tov", 0.0) * vol * b("tov") * o("tov")
    g["stl"] = r.get("stl", 0.0) * vol * o("stl")
    g["blk"] = r.get("blk", 0.0) * vol * o("blk")
    return g


# ---------------------------------------------------------------------------------------------- the payload

def build(ctx, cat: dict | None, prev_cat: dict | None, proj: dict[str, dict], prm: dict, valuation: dict | None,
          injuries: dict[str, list] | None, prev2_cat: dict | None = None, rest: dict | None = None,
          backtest: dict | None = None, updated_at: str | None = None) -> dict:
    """fantasy.json for the current season (see the module docstring). `proj`: value.projections; `injuries`:
    {pid: [status, detail]}; `rest`: rest_factors (cached by the build)."""
    league, season, today = ctx.league, ctx.season, ctx.today
    games = ctx.games or {}
    teams = list(ctx.teams or [])
    sched = team_schedule(games, teams)
    remaining = {t: [x for x in lst if x["status"] != "post" and x["day"] >= today] for t, lst in sched.items()}
    season_over = not any(remaining.values())
    target = season + 1 if season_over else season
    slates = slate_sizes(games)
    started = any(x["status"] == "post" for lst in sched.values() for x in lst)
    # pace and opponent factors
    rt = ((ctx.ratings or {}).get("teams")) or {}
    paces = {t: _f((rt.get(t) or {}).get("pace")) for t in teams}
    lg_pace = float(np.mean([p for p in paces.values() if p])) if any(paces.values()) else 100.0
    from oddsmarkets.basketball.models import _io
    prev_store = an.load_store(league, season - 1)
    prev_box = _io.box_frame(an.real_games(prev_store), ("reg",)) if prev_store.get("games") else None
    cur_box = ctx.box if ctx.box is not None and not ctx.box.empty else None
    opp = opponent_factors(cur_box, prev_box)
    rest = rest or {"min": {str(r): 1.0 for r in range(4)}, "play": {str(r): 1.0 for r in range(4)}}
    # rates, minutes, availability
    store_players = ctx.players or {}
    pools = {pid: str((store_players.get(pid) or {}).get("pool") or "F")[:1] for pid in proj}
    rates = per_minute(ctx.impact, store_players)
    prates = pool_rates({p: r for p, r in rates.items()}, {p: str((store_players.get(p) or {}).get("pool") or "F")[:1] for p in rates}) or {}
    lists = VAL.team_lists(proj)
    base_min = {t: VAL.baseline_minutes(ps, prm) for t, ps in lists.items()}
    inj = injuries or {}
    vrows = {}
    if valuation and valuation.get("ok"):
        vc = valuation["cols"]
        vrows = {str(r[0]): dict(zip(vc, r)) for r in valuation["rows"]}
    ddr = dd_rates(pd.concat([b for b in (prev_box, cur_box) if b is not None], ignore_index=True)
                   if (prev_box is not None or cur_box is not None) else None)
    # league percentages for luck
    lg_tp = lg_ft = None
    if cur_box is not None:
        lg_tp = float(cur_box["tpm"].sum() / max(1, cur_box["tpa"].sum()))
        lg_ft = float(cur_box["ftm"].sum() / max(1, cur_box["fta"].sum()))
    elif prev_box is not None:
        lg_tp = float(prev_box["tpm"].sum() / max(1, prev_box["tpa"].sum()))
        lg_ft = float(prev_box["ftm"].sum() / max(1, prev_box["fta"].sum()))
    luck = shooting_luck(cat, [prev_cat, prev2_cat], cur_box, lg_tp or 0.36, lg_ft or 0.78) if started and not season_over else {}
    # weeks
    if season_over:
        week_days: list[tuple[date, date]] = []
    else:
        first = min((x["day"] for lst in remaining.values() for x in lst), default=today)
        w0 = week_start(max(today, first))
        week_days = [(max(today, w0 + timedelta(days=7 * k)), w0 + timedelta(days=7 * k + 6)) for k in range(WEEKS + 2)]
    team_rows = {}
    for t in teams:
        wk = []
        for a, b in week_days:
            gl = [x for x in remaining.get(t, []) if a <= x["day"] <= b]
            light = sum(1 for x in gl if slates.get(x["day"], 0) <= LIGHT_DAY)
            b2b = sum(1 for x in gl if x["rest"] == 0)
            opp_f = float(np.mean([(opp.get(str(x["opp"])) or {}).get("pts", 1.0) * ((paces.get(x["opp"]) or lg_pace) / lg_pace) for x in gl])) if gl else None
            wk.append([len(gl), b2b, light, _r(opp_f, 3)])
        team_rows[t] = {"left": len(remaining.get(t, [])), "weeks": wk}
    full_games = VAL.season_games(league, target)
    # per player projections: per game day, the team's depth chart without the players ruled out that day
    is_out: dict[str, date] = {}
    dtd: set[str] = set()
    for pid, st in inj.items():
        s0 = str((st or [""])[0] or "").lower()
        ret = None
        mm = re.search(r"return (\d{4}-\d{2}-\d{2})", str((st or [None, None])[1] or ""))
        if mm:
            ret = date.fromisoformat(mm.group(1))
        if s0.startswith("out"):
            is_out[pid] = ret or (today + timedelta(days=OUT_DAYS))
        elif s0:
            dtd.add(pid)
    players_out = []
    per_game_avg: dict[str, dict] = {}
    # this season's per-game lines, blended into the model's (STD_BLEND x min(1, games / STD_FULL) from 3 games)
    std_pg: dict[str, tuple[dict, int]] = {}
    if cur_box is not None:
        cb = cur_box[cur_box["sec"] > 0].copy()
        cb["reb"] = cb["oreb"] + cb["dreb"]
        g_ = cb.groupby("player_id")
        n_ = g_["game_id"].nunique()
        m_ = g_[STATS].mean()
        for pid_, row_ in m_.iterrows():
            std_pg[str(pid_)] = ({k: float(row_[k]) for k in STATS}, int(n_[pid_]))
    for t, ps in lists.items():
        team_games = remaining.get(t, []) if not season_over else []
        ids = [p["id"] for p in ps]
        rate_of = {p["id"]: (rates.get(p["id"]) or prates.get(pools.get(p["id"])) or prates.get("F") or {}) for p in ps}

        def team_rate(m):
            return {s: sum(rate_of[k].get(s, 0.0) * v for k, v in m.items() if k in rate_of) for s in TEAM_CONSERVED}
        base_rate = team_rate(base_min[t])
        cache: dict[frozenset, tuple[dict, dict]] = {}

        def state(day, ps=ps, ids=ids, cache=cache, base_rate=base_rate, t=t):
            key = frozenset(k for k in ids if k in is_out and day < is_out[k])
            if key not in cache:
                if key:
                    m = VAL.apply_moves(ps, list(key), [], prm)["minutes"]
                    now = team_rate(m)
                    bump = {s: (1.0 + USAGE_KEEP * (base_rate[s] / now[s] - 1.0)) if now[s] > 1e-9 else 1.0 for s in TEAM_CONSERVED}
                else:
                    m, bump = base_min[t], {s: 1.0 for s in TEAM_CONSERVED}
                cache[key] = (m, bump)
            return key, cache[key][0], cache[key][1]
        first_game = team_games[0]["day"] if team_games else None
        for p in ps:
            pid = p["id"]
            r = rate_of.get(pid) or {}
            if not r:
                continue
            m_base = float(base_min[t].get(pid, 0.0))
            vr = vrows.get(pid) or {}
            if m_base < MIN_MPG and pid not in is_out:
                continue
            avail = float(vr.get("avail") or 0.85)
            st = inj.get(pid)
            status = str((st or [""])[0] or "")
            ret = is_out.get(pid)
            m_now = float(state(today)[1].get(pid, 0.0)) if pid not in is_out else 0.0
            dd, td = ddr.get(pid, (0.0, 0.0))
            sl, sn = std_pg.get(pid, ({}, 0))
            bw = STD_BLEND * min(1.0, sn / STD_FULL) if sn >= 3 else 0.0

            def blend(g, bw=bw, sl=sl):
                return {k: (1.0 - bw) * v + bw * sl.get(k, v) for k, v in g.items()} if bw > 0 else g
            pg = {"min": m_base, "dd": dd, "td": td, **blend(game_stats(r, m_base, 1.0, {}, {}))}
            per_game_avg[pid] = pg
            tot = {s: 0.0 for s in STATS}
            xgp = 0.0
            wk_tot = [dict({s: 0.0 for s in STATS}, g=0, xgp=0.0, dd=0.0, td=0.0) for _ in week_days]
            for x in team_games:
                key, mins_map, bump = state(x["day"])
                if pid in key:
                    continue
                pplay = avail * float(rest["play"].get(str(x["rest"]), 1.0))
                if pid in dtd and x["day"] == first_game:
                    pplay *= DTD_PLAY
                mins = float(mins_map.get(pid, 0.0)) * float(rest["min"].get(str(x["rest"]), 1.0))
                pf = (paces.get(x["opp"]) or lg_pace) / lg_pace
                g = blend(game_stats(r, mins, pf, opp.get(str(x["opp"])) or {}, bump))
                for s, v in g.items():
                    tot[s] += pplay * v
                xgp += pplay
                for k, (a, b) in enumerate(week_days):
                    if a <= x["day"] <= b:
                        wt = wk_tot[k]
                        wt["g"] += 1
                        wt["xgp"] += pplay
                        wt["dd"] += pplay * dd
                        wt["td"] += pplay * td
                        for s, v in g.items():
                            wt[s] += pplay * v
            if season_over:
                xgp = avail * full_games
                tot = {s: pg.get(s, 0.0) * xgp for s in STATS}
            tot["dd"] = xgp * dd
            tot["td"] = xgp * td
            lk = luck.get(pid) or {}
            players_out.append({"id": pid, "name": p.get("name"), "team": t, "pos": p.get("pos"), "role": p.get("role"), "age": p.get("age"),
                                "inj": status or None, "ret": str(ret) if ret else None, "mpg": m_base, "mpg_now": m_now, "avail": avail,
                                "pg": pg, "ros": tot, "xgp": xgp, "left": len(team_games) if not season_over else full_games,
                                "weeks": wk_tot, "luck": lk, "last_mpg": None, "rate": p.get("rate"), "basis": p.get("basis")})
    # last season's minutes a game (breakouts)
    PP = ((prev_cat or {}).get("players")) or {}
    for x in players_out:
        pr = PP.get(x["id"]) or {}
        if pr.get("gp"):
            x["last_mpg"] = float(pr.get("min") or 0.0) / max(1, int(pr["gp"]))
    # 9-cat values and points
    pg_map = {x["id"]: x["pg"] for x in players_out}
    z = nine_cat(pg_map)
    std = PRESETS["standard"]["w"]
    for x in players_out:
        x["z"] = z.get(x["id"]) or {}
        x["fp"] = points(x["pg"], std)
        x["fp_ros"] = points(x["ros"], std)
    ranked = sorted(players_out, key=lambda x: -(x["z"].get("total") or -99))
    for i, x in enumerate(ranked):
        x["rank9"] = i + 1
    for i, x in enumerate(sorted(players_out, key=lambda x: -x["fp"])):
        x["rankp"] = i + 1
    # season-start ranks (waiver proxy): this season's projection with last season's box only, cached by the caller
    pre = _preseason_ranks(ctx, rates, players_out, prev_box, started)
    for x in players_out:
        x["rank_pre"] = pre.get(x["id"])
    picks = our_picks(players_out, team_rows, week_days, season_over, started)
    return _payload(league, season, target, players_out, team_rows, week_days, rest, opp, picks, season_over, started, backtest,
                    lg_pace, updated_at, ctx.phase)


def _preseason_ranks(ctx, rates, players_out, prev_box, started) -> dict[str, int]:
    """Rank by 9-category value at the start of the season: before the first game, today's ranks; after it, per-game
    projections from last season's box scores (rates over last season, minutes last season's average)."""
    if not started or prev_box is None or prev_box.empty:
        return {x["id"]: x["rank9"] for x in players_out}
    b = prev_box[prev_box["sec"] > 0].copy()
    b["reb"] = b["oreb"] + b["dreb"]
    g = b.groupby("player_id")
    gp = g["game_id"].nunique()
    agg = g[[s for s in STATS]].sum()
    pg = {}
    for x in players_out:
        pid = x["id"]
        if pid in agg.index and gp.get(pid, 0) >= 10:
            pg[pid] = {s: float(agg.loc[pid, s]) / float(gp[pid]) for s in STATS}
    z = nine_cat(pg)
    order = sorted(z, key=lambda p: -z[p]["total"])
    return {p: i + 1 for i, p in enumerate(order)}


def our_picks(players: list[dict], team_rows: dict, week_days: list, season_over: bool, started: bool) -> dict[str, list]:
    """Lists with a one-line reason each: core (best 9-cat values), points (best per-game points), breakouts, buy-low,
    sell-high, waiver adds and drops, streamers for the next week, punt anchors."""
    out: dict[str, list] = {}
    rk = sorted(players, key=lambda x: x["rank9"])
    out["core"] = [[x["id"], f"No. {x['rank9']} in 9-category per game; best categories " + ", ".join(
        CAT_LABELS[c] for c, _v in sorted(((c, x["z"].get(c, 0.0)) for c in CATS9), key=lambda cv: -cv[1])[:3])] for x in rk[:10]]
    rp = sorted(players, key=lambda x: x["rankp"])
    out["points"] = [[x["id"], f"{x['fp']:.1f} standard points a game over {x['mpg']:.0f} minutes"] for x in rp[:10]]
    br = [x for x in players if x.get("age") is not None and x["age"] <= 24.5 and x.get("last_mpg") is not None and x["mpg"] - x["last_mpg"] >= 4.0
          and x["rank9"] > 40]
    br.sort(key=lambda x: (x["rank9"]))
    out["breakouts"] = [[x["id"], f"age {x['age']:.0f}: {x['last_mpg']:.0f} → {x['mpg']:.0f} projected minutes; No. {x['rank9']} now"] for x in br[:8]]
    if started and not season_over:
        lk = [x for x in players if x["luck"].get("luck") is not None and x["luck"].get("gp", 0) >= 8 and x["rank9"] <= 220]
        buy = sorted([x for x in lk if x["luck"]["luck"] <= -LUCK_LINE], key=lambda x: x["luck"]["luck"])
        sell = sorted([x for x in lk if x["luck"]["luck"] >= LUCK_LINE], key=lambda x: -x["luck"]["luck"])
        out["buy_low"] = [[x["id"], f"shooting {abs(x['luck']['luck']):.1f} points a game below what the shots and history predict"] for x in buy[:8]]
        out["sell_high"] = [[x["id"], f"shooting {x['luck']['luck']:.1f} points a game above what the shots and history predict"] for x in sell[:8]]
        adds = [x for x in players if (x.get("rank_pre") or 999) > WAIVER_LINE and x["rank9"] <= WAIVER_LINE]
        adds.sort(key=lambda x: x["rank9"])
        out["adds"] = [[x["id"], f"No. {x['rank_pre'] or '—'} at the season start, No. {x['rank9']} now"] for x in adds[:10]]
        drops = [x for x in players if (x.get("rank_pre") or 999) <= WAIVER_LINE - 30 and x["rank9"] > WAIVER_LINE + 30]
        drops.sort(key=lambda x: -(x["rank9"] - (x.get("rank_pre") or 0)))
        out["drops"] = [[x["id"], f"No. {x['rank_pre']} at the season start, No. {x['rank9']} now" + (f" ({x['inj']})" if x.get("inj") else "")]
                        for x in drops[:8]]
    if week_days and len(week_days) > 1:
        k = 0 if (week_days[0][1] - week_days[0][0]).days >= 3 else 1
        cand = [x for x in players if x["rank9"] > 100 and x["weeks"] and x["weeks"][k]["g"] >= 3]
        for x in cand:
            x["_wk"] = points(x["weeks"][k], PRESETS["standard"]["w"])
        cand.sort(key=lambda x: -x["_wk"])
        a, b = week_days[k]
        out["streamers"] = [[x["id"], f"{x['weeks'][k]['g']} games {a.strftime('%d %b')}–{b.strftime('%d %b')}, {x['_wk']:.0f} projected standard points"]
                            for x in cand[:8]]
        for x in cand:
            x.pop("_wk", None)
    # punt anchors: best players for punting FG%, FT% and TO
    for c in ("fg", "ft", "tov"):
        cats = [k for k in CATS9 if k != c]
        sc = sorted(players, key=lambda x: -sum(x["z"].get(k, 0.0) for k in cats))
        lab = CAT_LABELS[c]
        out[f"punt_{c}"] = [[x["id"], f"No. {i + 1} punting {lab} (No. {x['rank9']} in plain 9-category)"] for i, x in enumerate(sc[:6])]
    return out


COLS = ["id", "name", "team", "pos", "role", "age", "inj", "ret", "mpg", "mpg_now", "last_mpg", "avail", "left", "xgp", "rank9", "rankp",
        "rank_pre"]
PG_COLS = ["min", "pts", "reb", "ast", "stl", "blk", "tpm", "tpa", "fgm", "fga", "ftm", "fta", "tov", "dd", "td"]
TOT_COLS = ["pts", "reb", "ast", "stl", "blk", "tpm", "fgm", "fga", "ftm", "fta", "tov", "dd", "td"]
LUCK_COLS = ["luck", "pps_luck", "tp_luck", "ft_luck", "fg3", "fg3_exp"]


def _payload(league, season, target, players, team_rows, week_days, rest, opp, picks, season_over, started, backtest, lg_pace,
             updated_at, phase) -> dict:
    rows = []
    for x in sorted(players, key=lambda x: x["rank9"]):
        base = []
        for c in COLS:
            v = x.get(c)
            base.append(_r(v, 1) if c in ("age", "mpg", "mpg_now", "last_mpg", "xgp") else _r(v, 3) if c == "avail" else v)
        pg = [_r(x["pg"].get(c), 3 if c in ("dd", "td") else 2) for c in PG_COLS]
        tot = [_r(x["ros"].get(c), 1) for c in TOT_COLS]
        wk = [[w["g"], _r(w["xgp"], 2)] + [_r(w.get(c), 1) for c in TOT_COLS] for w in x["weeks"][:WEEKS]] if x["weeks"] else []
        lk = [_r(x["luck"].get(c), 3 if c in ("fg3", "fg3_exp") else 2) for c in LUCK_COLS] if x["luck"] else None
        rows.append(base + [pg, tot, wk, lk])
    weeks = [[str(a), str(b)] for a, b in week_days[:WEEKS + 2]]
    return {"ok": True, "league": league, "season": int(season), "target": int(target), "updated_at": updated_at or an.now(), "phase": phase,
            "version": VERSION, "season_over": season_over, "started": started,
            "cols": COLS + ["pg", "ros", "weeks", "luck"], "pg_cols": PG_COLS, "tot_cols": TOT_COLS, "week_cols": ["g", "xgp"] + TOT_COLS,
            "luck_cols": LUCK_COLS, "rows": rows, "weeks": weeks,
            "teams": {t: v for t, v in team_rows.items()}, "team_week_cols": ["games", "b2b", "light", "opp_pts"],
            "cats": CATS9, "cat_labels": CAT_LABELS, "presets": PRESETS, "picks": picks,
            "rest": rest, "opp": opp, "league_pace": _r(lg_pace, 2),
            "constants": {"pool_n": POOL_N, "waiver_line": WAIVER_LINE, "light_day": LIGHT_DAY, "opp_k": OPP_K, "usage_keep": USAGE_KEEP,
                          "dtd_play": DTD_PLAY, "out_days": OUT_DAYS, "luck_line": LUCK_LINE, "shot_k": SHOT_K, "rest_seasons": REST_SEASONS},
            "backtest": backtest,
            "note": "Projections from our models and ESPN's box scores, schedule and injury report. No fantasy platform's rankings, "
                    "ownership or ADP are used (their terms do not allow reuse); waiver targets use our season-start ranks as the proxy."}


def cached_rest(league: str, season: int) -> dict:
    """rest_factors over the REST_SEASONS completed seasons before `season`, cached on those stores' sizes and content
    digests (path- and mtime-independent)."""
    from oddsmarkets.basketball import store as stmod
    from oddsmarkets.basketball.models import _io
    seasons = [s for s in an.seasons_on_disk(league) if s < season][-REST_SEASONS:]
    sig = []
    for s in seasons:
        p = stmod.season_path(league, s)
        d = _io.content_digest(p)
        sig.append([s, p.stat().st_size, d] if d is not None else [s, None, None])
    path = an.cache_root() / "value" / f"fantasy_rest_{league}.json"
    c = an.read_json(path)
    if isinstance(c, dict) and c.get("key") == [VERSION, sig] and c.get("rest"):
        return c["rest"]
    frames = [_io.box_frame(an.real_games(an.load_store(league, s)), ("reg",)) for s in seasons]
    rest = rest_factors(frames)
    rest["seasons"] = seasons
    try:
        an.write_json(path, {"key": [VERSION, sig], "rest": rest})
    except OSError:
        pass
    return rest
