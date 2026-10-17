"""
fourth_downs.json (per season), coaches.json and referees.json (site-wide, every season on disk).

Fourth downs: every fourth down of the season (regular season and playoffs) with the situation, the choice (go /
punt / FG), our recommendation and win probability by option, and the WP lost against the best option. The
coach table grades decisions: go rate, go rate when the model says go, WP lost, decisions matching the
recommendation, and go rate over expected (GOE): the team's go rate against a league logistic model of going for it
on distance, field position, score, time and win probability fitted on the same season (so GOE measures
aggressiveness relative to the league, not optimality).

Referees: per referee and season, accepted penalties and yards per game, home share of penalties, the most common
calls and the home team's record in their games.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num

logger = logging.getLogger(__name__)
FD_COLS = ["game_id", "week", "gtype", "qtr", "clock", "team", "opp", "coach", "dist", "yl100", "score_diff", "wp", "choice", "rec",
           "wp_go", "wp_punt", "wp_fg", "p_convert", "wp_lost", "go_exp", "result", "play_id", "grade"]


def _fourths(ctx: SeasonContext) -> pd.DataFrame:
    P = ctx.plays()
    if not len(P) or "play_type" not in P:
        return P.iloc[0:0]
    D = P[(num(P, "down") == 4) & P["play_type"].isin(["pass", "run", "punt", "field_goal"])].copy()
    D["choice"] = D["play_type"].map({"pass": "go", "run": "go", "punt": "punt", "field_goal": "fg"})
    # fakes: a punt or FG formation that ends as a pass / run counts as go (nflverse records the actual play)
    D["go"] = (D["choice"] == "go").astype(float)
    return D


def go_model(D: pd.DataFrame) -> pd.Series:
    """League P(go) by logistic regression on distance, field position, score, seconds left and WP (season fit)."""
    if len(D) < 200:
        return pd.Series(np.nan, index=D.index)
    dist = num(D, "ydstogo").clip(1, 20)
    yl = num(D, "yardline_100")
    sd = num(D, "score_differential").clip(-28, 28)
    gs = num(D, "game_seconds_remaining")
    wp = num(D, "wp")
    X = np.column_stack([np.ones(len(D)), np.log(dist), yl / 100, (yl / 100) ** 2, sd / 14, gs / 3600, wp, (sd < 0) * (gs < 900)])
    ok = ~np.isnan(X).any(axis=1)
    y = D["go"].to_numpy(float)
    w = np.zeros(X.shape[1])
    Xo, yo = X[ok], y[ok]
    for _ in range(40):
        p = 1 / (1 + np.exp(-(Xo @ w)))
        W = p * (1 - p) + 1e-9
        H = Xo.T @ (Xo * W[:, None]) + np.eye(X.shape[1]) * 1e-2
        step = np.linalg.solve(H, Xo.T @ (yo - p) - 1e-2 * w)
        w = w + step
        if np.abs(step).max() < 1e-7:
            break
    out = np.full(len(D), np.nan)
    out[ok] = 1 / (1 + np.exp(-(Xo @ w)))
    return pd.Series(out, index=D.index)


def build(ctx: SeasonContext) -> dict | None:
    D = _fourths(ctx)
    if not len(D):
        return {"ok": False, "reason": f"no play-by-play for {ctx.season}", "season": ctx.season}
    D["go_exp"] = go_model(D)
    gtype = {gid: g.get("gtype") for gid, g in ctx.games.items()}
    coach = {}
    for gid, g in ctx.games.items():
        coach[(gid, g.get("home"))] = g.get("home_coach")
        coach[(gid, g.get("away"))] = g.get("away_coach")
    if "home_coach" in D:
        hc = np.where(D["posteam"] == D["home_team"], D["home_coach"], D["away_coach"])
    else:
        hc = [coach.get((gid, t)) for gid, t in zip(D["game_id"], D["posteam"])]
    D["coach"] = hc
    D["opp"] = D["defteam"]
    rows = []
    from oddsmarkets.nfl.analytics.games import grade
    for r in D.sort_values(["game_id", "play_id"]).to_dict("records"):
        res = an.sid(r.get("field_goal_result")) if r["choice"] == "fg" else (
            "converted" if an.inum(r.get("fourth_down_converted")) == 1 else ("failed" if an.inum(r.get("fourth_down_failed")) == 1 else r["choice"]))
        rows.append([r["game_id"], an.inum(r.get("week")), gtype.get(r["game_id"]), an.inum(r.get("qtr")), r.get("time"), r.get("posteam"),
                     r.get("opp"), r.get("coach"), an.inum(r.get("ydstogo")), an.inum(r.get("yardline_100")), an.inum(r.get("score_differential")),
                     an.rnd(r.get("wp"), 4), r["choice"], r.get("fd_rec"), an.rnd(r.get("fd_wp_go"), 4), an.rnd(r.get("fd_wp_punt"), 4),
                     an.rnd(r.get("fd_wp_fg"), 4), an.rnd(r.get("fd_p_convert"), 4), an.rnd(r.get("fd_wp_lost"), 4), an.rnd(r.get("go_exp"), 4),
                     res, an.fnum(r.get("play_id")), grade(r.get("fd_wp_lost"))])
    has_rec = "fd_rec" in D and D["fd_rec"].notna().any()
    # coach table (team-coach pairs; regular season and playoffs; end-of-half and garbage-time excluded from rates)
    hs = num(D, "half_seconds_remaining")
    wp = num(D, "wp")
    core = D[(hs > 120) & wp.between(0.05, 0.95)]
    table = []
    for (c, t), d in core.groupby([core["coach"].fillna("?"), core["posteam"]]):
        rec_go = d["fd_rec"].astype(str).str.lower().str.startswith("go") if has_rec else pd.Series(False, index=d.index)
        row = {"coach": c, "team": t, "n": int(len(d)), "go": int(d["go"].sum()), "go_rate": an.rnd(d["go"].mean(), 4),
               "go_exp": an.rnd(d["go_exp"].mean(), 4), "goe": an.rnd(d["go"].mean() - d["go_exp"].mean(), 4) if d["go_exp"].notna().any() else None,
               "n_rec_go": int(rec_go.sum()) if has_rec else None,
               "go_when_rec_go": an.rnd(d.loc[rec_go, "go"].mean(), 4) if has_rec and rec_go.any() else None,
               "agree": an.rnd((d["fd_rec"].astype(str).str.lower().str[:2] == d["choice"].str[:2]).mean(), 4) if has_rec else None,
               "wp_lost": an.rnd(num(d, "fd_wp_lost").fillna(0).sum(), 4) if has_rec else None,
               "wp_lost_per": an.rnd(num(d, "fd_wp_lost").fillna(0).mean(), 5) if has_rec else None}
        table.append(row)
    table.sort(key=lambda r: -(r["goe"] if r["goe"] is not None else r["go_rate"] or 0))
    league = {"n": int(len(core)), "go_rate": an.rnd(core["go"].mean(), 4) if len(core) else None,
              "go_rate_rec": an.rnd(core.loc[core["fd_rec"].astype(str).str.lower().str.startswith("go"), "go"].mean(), 4) if has_rec else None}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "cols": FD_COLS, "rows": rows, "coaches": table, "league": league,
            "model": "fourth_down" if has_rec else None,
            "model_note": None if has_rec else "the fourth-down model did not score this season: recommendations and WP by option "
                                               "are null; go rate over expected (league behaviour) is shown.",
            "model_errors": {k: v for k, v in ctx.model_errors.items() if k in ("fourth_down", "wp", "ep", "play_scores")}}


def coaches(fd_by_season: dict[int, dict | None], games_by_season: dict[int, dict] | None = None) -> dict:
    """coaches.json: decision grades by coach and season (from each season's fourth_downs.json), plus a career row."""
    by: dict[str, dict] = {}
    for s, fd in sorted(fd_by_season.items()):
        for r in (fd or {}).get("coaches") or []:
            c = r.get("coach")
            if not c or c == "?":
                continue
            e = by.setdefault(c, {"name": c, "seasons": [], "teams": []})
            e["seasons"].append({"season": s, **{k: r.get(k) for k in ("team", "n", "go", "go_rate", "go_exp", "goe", "n_rec_go",
                                                                      "go_when_rec_go", "agree", "wp_lost", "wp_lost_per")}})
            if r.get("team") not in e["teams"]:
                e["teams"].append(r.get("team"))
    for c, e in by.items():
        n = sum(x["n"] or 0 for x in e["seasons"])
        go = sum(x["go"] or 0 for x in e["seasons"])
        ge = sum((x["go_exp"] or 0) * (x["n"] or 0) for x in e["seasons"] if x["go_exp"] is not None)
        nge = sum(x["n"] or 0 for x in e["seasons"] if x["go_exp"] is not None)
        wl = [x["wp_lost"] for x in e["seasons"] if x["wp_lost"] is not None]
        e["career"] = {"n": n, "go_rate": an.rnd(go / n, 4) if n else None, "goe": an.rnd(go / n - ge / nge, 4) if n and nge else None,
                       "wp_lost": an.rnd(sum(wl), 4) if wl else None, "first": e["seasons"][0]["season"], "last": e["seasons"][-1]["season"]}
    latest = max(fd_by_season) if fd_by_season else None
    current = sorted([{"name": c, **{k: x.get(k) for k in ("team", "n", "go_rate", "goe", "go_when_rec_go", "agree", "wp_lost")}}
                      for c, e in by.items() for x in e["seasons"] if x["season"] == latest],
                     key=lambda r: -(r["goe"] if r["goe"] is not None else 0))
    # head-coach records from the stores
    if games_by_season:
        for s, games in games_by_season.items():
            for g in games.values():
                if g.get("status") != "final" or g.get("hs") is None:
                    continue
                for side, opp in (("home", "away"), ("away", "home")):
                    c = g.get(f"{side}_coach")
                    if c in by:
                        pf, pa = (g["hs"], g["as"]) if side == "home" else (g["as"], g["hs"])
                        rec = by[c].setdefault("record", {"w": 0, "l": 0, "t": 0, "post_w": 0, "post_l": 0})
                        if g.get("gtype") == "REG":
                            rec["w" if pf > pa else ("l" if pf < pa else "t")] += 1
                        else:
                            rec["post_w" if pf > pa else "post_l"] += 1
    return {"ok": True, "updated_at": an.now(), "season": latest, "current": current, "coaches": by,
            "notes": "GOE = go rate minus a league logistic model's expected go rate (same season, same situations): aggressiveness "
                     "relative to the league. WP lost is against our fourth-down recommendation (seasons it scores)."}


def referees_season(ctx: SeasonContext) -> dict | None:
    """Per referee: games, accepted penalties and yards per game, home share, top calls, home record."""
    P = ctx.pbp()
    refs: dict[str, dict] = {}
    for gid, g in ctx.games.items():
        r = g.get("referee")
        if r and g.get("status") == "final":
            e = refs.setdefault(r, {"games": [], "home_w": 0, "home_l": 0, "home_t": 0})
            e["games"].append(gid)
            if g.get("hs") is not None:
                d = int(g["hs"]) - int(g["as"])
                e["home_w" if d > 0 else ("home_l" if d < 0 else "home_t")] += 1
    if not refs:
        return {"ok": False, "reason": "no referee assignments in the store", "season": ctx.season}
    pen = P[flag(P, "penalty").fillna(0) == 1] if len(P) and "penalty" in P else P.iloc[0:0]
    if len(pen) and "penalty_team" in pen:
        pen = pen[pen["penalty_team"].notna()]
    rows = []
    lg_ppg = (len(pen) / max(1, P["game_id"].nunique())) if len(P) else None
    for r, e in refs.items():
        gids = set(e["games"])
        p = pen[pen["game_id"].isin(gids)] if len(pen) else pen
        n = len(gids)
        home = (p["penalty_team"] == p["home_team"]).sum() if len(p) and "home_team" in p else 0
        top = p["penalty_type"].value_counts().head(5) if len(p) and "penalty_type" in p else pd.Series(dtype=int)
        rows.append({"referee": r, "games": n, "penalties_pg": an.rnd(len(p) / n, 2) if n and len(P) else None,
                     "yards_pg": an.rnd(num(p, "penalty_yards").sum() / n, 1) if n and len(P) else None,
                     "home_share": an.rnd(home / len(p), 3) if len(p) else None,
                     "vs_league": an.rnd(len(p) / n - lg_ppg, 2) if n and lg_ppg is not None and len(P) else None,
                     "top_calls": [[k, int(v)] for k, v in top.items()],
                     "home_record": [e["home_w"], e["home_l"], e["home_t"]]})
    rows.sort(key=lambda x: -(x["penalties_pg"] or 0))
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "league_penalties_pg": an.rnd(lg_ppg, 2), "referees": rows}


def referees(by_season: dict[int, dict | None]) -> dict:
    out: dict[str, dict] = {}
    for s, blk in sorted(by_season.items()):
        for r in (blk or {}).get("referees") or []:
            e = out.setdefault(r["referee"], {"name": r["referee"], "seasons": []})
            e["seasons"].append({"season": s, **{k: v for k, v in r.items() if k != "referee"}})
    for e in out.values():
        g = sum(x["games"] for x in e["seasons"])
        pen = sum((x["penalties_pg"] or 0) * x["games"] for x in e["seasons"] if x["penalties_pg"] is not None)
        ng = sum(x["games"] for x in e["seasons"] if x["penalties_pg"] is not None)
        e["career"] = {"games": g, "penalties_pg": an.rnd(pen / ng, 2) if ng else None}
    latest = max(by_season) if by_season else None
    return {"ok": True, "updated_at": an.now(), "season": latest,
            "current": ((by_season.get(latest) or {}).get("referees") if latest else None) or [],
            "league": {str(s): (b or {}).get("league_penalties_pg") for s, b in by_season.items()}, "referees": out}
