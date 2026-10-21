"""
Team season catalogue (`teams.json`): about 70 metrics with league percentiles and ranks, the game
log, roster with HPM, lineups (5-man, with 2- and 3-man combinations), the rotation matrix, on/off,
shot profiles for and against, injuries and the season odds against the market.

Definitions (per 100 possessions; possessions = FGA - OREB + TOV + 0.44 FTA averaged over both teams)
    ORtg = 100 pts / poss, DRtg = 100 opp pts / poss, Net = ORtg - DRtg; pace per 48 (NBA) / 40 (WNBA) minutes
    Four Factors: eFG% = (FGM + 0.5 3PM) / FGA, TOV% = TOV / poss, ORB% = ORB / (ORB + opp DRB),
                  FT rate = FTM / FGA; the same for opponents (DRB% = DRB / (DRB + opp ORB)).
    Pythagorean wins = games * PF^k / (PF^k + PA^k), k = 14 (NBA) / 13 (WNBA); luck = wins - Pythagorean wins.
    Strength of schedule = mean model net rating of the opponents played (remaining: still to play).
    Model ratings come from `models/ratings.py` (opponent- and home-adjusted, time-decayed ridge fit).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import lineups as LU
from oddsmarkets.basketball.analytics.context import SeasonContext
from oddsmarkets.basketball.analytics.players import zones_table

logger = logging.getLogger(__name__)
_m = an.metric
PYTH_K = {"nba": 14.0, "wnba": 13.0}

GROUPS = ["Ratings", "Record", "Four Factors", "Shooting", "Shot quality", "Possessions", "Clutch", "Rotation", "Context", "Projections"]

METRICS: list[dict] = [
    # Ratings
    _m("ortg", "Offensive rating", "Ratings", "1"),
    _m("drtg", "Defensive rating", "Ratings", "1", True),
    _m("net", "Net rating", "Ratings", "1"),
    _m("pace", "Pace", "Ratings", "1"),
    _m("model_off", "Model offence (adjusted)", "Ratings", "1"),
    _m("model_def", "Model defence (adjusted)", "Ratings", "1", True),
    _m("model_net", "Model net rating (adjusted)", "Ratings", "2"),
    _m("model_se", "Model net standard error", "Ratings", "2", True),
    _m("elo", "Elo", "Ratings", "int"),
    _m("net_7d_change", "Model net change over 7 days", "Ratings", "2"),
    # Record
    _m("w", "Wins", "Record", "int"),
    _m("l", "Losses", "Record", "int", True),
    _m("win_pct", "Win %", "Record", "pct"),
    _m("pyth_wins", "Pythagorean wins", "Record", "1"),
    _m("luck", "Wins above Pythagorean", "Record", "1"),
    _m("home_win_pct", "Home win %", "Record", "pct"),
    _m("away_win_pct", "Away win %", "Record", "pct"),
    _m("close_win_pct", "Win % in games within 5 points", "Record", "pct"),
    _m("mov", "Average margin", "Record", "1"),
    # Four Factors
    _m("efg", "Effective FG %", "Four Factors", "pct"),
    _m("tov_pct", "Turnover %", "Four Factors", "pct", True),
    _m("orb_pct", "Offensive rebound %", "Four Factors", "pct"),
    _m("ftr", "Free-throw rate (FTM / FGA)", "Four Factors", "3"),
    _m("opp_efg", "Opponent effective FG %", "Four Factors", "pct", True),
    _m("opp_tov_pct", "Opponent turnover %", "Four Factors", "pct"),
    _m("drb_pct", "Defensive rebound %", "Four Factors", "pct"),
    _m("opp_ftr", "Opponent free-throw rate", "Four Factors", "3", True),
    # Shooting
    _m("fg3", "3-point %", "Shooting", "pct"),
    _m("tpar", "3-point attempt rate", "Shooting", "pct"),
    _m("fg2", "2-point %", "Shooting", "pct"),
    _m("ft", "Free-throw %", "Shooting", "pct"),
    _m("ast_rate", "Assisted share of made FG", "Shooting", "pct"),
    _m("opp_fg3", "Opponent 3-point %", "Shooting", "pct", True),
    _m("opp_tpar", "Opponent 3-point attempt rate", "Shooting", "pct", True),
    _m("stl_pct", "Steal % (per opponent possession)", "Shooting", "pct"),
    _m("blk_pct", "Block % (of opponent 2s)", "Shooting", "pct"),
    # Shot quality
    _m("xpps", "Expected points per shot", "Shot quality", "3", scope="pbp"),
    _m("pox100", "Shooting luck: points over expected per 100 shots", "Shot quality", "1", scope="pbp"),
    _m("opp_xpps", "Opponent expected points per shot", "Shot quality", "3", True, "pbp"),
    _m("opp_pox100", "Opponent points over expected per 100 shots", "Shot quality", "1", True, "pbp"),
    _m("rim_freq", "Rim frequency", "Shot quality", "pct", scope="pbp"),
    _m("mid_freq", "Mid-range frequency", "Shot quality", "pct", scope="pbp"),
    _m("c3_freq", "Corner-3 frequency", "Shot quality", "pct", scope="pbp"),
    _m("opp_rim_freq", "Opponent rim frequency", "Shot quality", "pct", True, "pbp"),
    _m("opp_three_freq", "Opponent 3-point frequency", "Shot quality", "pct", True, "pbp"),
    _m("avg_dist", "Average shot distance (ft)", "Shot quality", "1", scope="pbp"),
    # Possessions
    _m("tr_share", "Transition share of possessions", "Possessions", "pct", scope="pbp"),
    _m("tr_ppp", "Points per transition possession", "Possessions", "3", scope="pbp"),
    _m("hc_ppp", "Points per half-court possession", "Possessions", "3", scope="pbp"),
    _m("ato_ppp", "Points per possession after a timeout", "Possessions", "3", scope="pbp"),
    _m("pts_paint_g", "Points in the paint per game", "Possessions", "1"),
    _m("pts_fb_g", "Fast-break points per game", "Possessions", "1"),
    _m("pts_off_tov_g", "Points off turnovers per game", "Possessions", "1"),
    # Clutch
    _m("clutch_net", "Clutch net rating", "Clutch", "1", scope="pbp"),
    _m("clutch_poss", "Clutch possessions", "Clutch", "int", scope="pbp"),
    _m("clutch_games", "Games with clutch time", "Clutch", "int", scope="pbp"),
    # Rotation
    _m("depth", "Players with 10+ minutes per game", "Rotation", "int"),
    _m("starter_min_share", "Starters' share of minutes", "Rotation", "pct"),
    _m("continuity", "Minutes by players back from last season", "Rotation", "pct"),
    _m("top_lineup_share", "Most-used lineup's share of possessions", "Rotation", "pct", scope="pbp"),
    _m("best_lineup_net", "Best lineup net (25+ poss)", "Rotation", "1", scope="pbp"),
    _m("players_used", "Players used", "Rotation", "int", True),
    # Context
    _m("sos", "Strength of schedule played", "Context", "2"),
    _m("sos_remaining", "Strength of schedule remaining", "Context", "2"),
    _m("home_net", "Net rating at home", "Context", "1"),
    _m("away_net", "Net rating away", "Context", "1"),
    _m("b2b_net", "Net rating on the 2nd night of a back-to-back", "Context", "1"),
    _m("rest_net", "Net rating with 1+ days of rest", "Context", "1"),
    _m("inj_adj_net", "Injury-adjusted model net", "Context", "2"),
    _m("lead_changes_g", "Lead changes per game", "Context", "1"),
    # Projections
    _m("exp_w", "Projected wins", "Projections", "1"),
    _m("p_playoffs", "Playoff probability", "Projections", "prob"),
    _m("p_conf", "Finals probability", "Projections", "prob"),
    _m("p_title", "Title probability", "Projections", "prob"),
    _m("p_title_market", "Title probability (market)", "Projections", "prob"),
    _m("title_edge", "Title edge (model - market)", "Projections", "prob"),
]
METRIC_KEYS = [m["key"] for m in METRICS]


def _team_frame(ctx: SeasonContext) -> pd.DataFrame:
    """One row per (game, team) for final catalogue-stype games: team box totals, opponent totals, result."""
    rows = []
    for gid, g in ctx.games.items():
        if g.get("status") != "post" or g.get("stype") != "reg" or g.get("hs") is None:
            continue
        box = g.get("box") or {}
        h, a = str(g["home"]), str(g["away"])
        for t, o, pts, opts, home in ((h, a, g["hs"], g["as"], 1), (a, h, g["as"], g["hs"], 0)):
            tb = (box.get(t) or {}).get("team") or {}
            ob = (box.get(o) or {}).get("team") or {}
            r = {"game_id": gid, "date": str(g.get("date") or "")[:10], "team": t, "opp": o, "home": home, "pts": int(pts),
                 "opp_pts": int(opts), "periods": int(g.get("periods") or 4), "neutral": bool(g.get("neutral"))}
            for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf", "pts_paint",
                      "pts_fastbreak", "pts_off_tov", "lead_changes"):
                r[k] = tb.get(k)
                r[f"o_{k}"] = ob.get(k)
            rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in df.columns:
        if c not in ("game_id", "date", "team", "opp"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # A side with no field-goal attempts is a missing box score (ESPN, NBA 2013-2018: about 330 team-games a
    # season, mostly CHI and NO): its counting stats are blanked, and possessions come from the other side, or
    # from the frame's mean pace when both are missing, so ORtg / DRtg / pace keep every game's points.
    stats = ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf", "pts_paint",
             "pts_fastbreak", "pts_off_tov", "lead_changes")
    miss_t = ~(df["fga"] > 0)
    miss_o = ~(df["o_fga"] > 0)
    for k in stats:
        df.loc[miss_t, k] = np.nan
        df.loc[miss_o, f"o_{k}"] = np.nan
    poss_t = df["fga"] - df["oreb"] + df["tov"] + 0.44 * df["fta"]
    poss_o = df["o_fga"] - df["o_oreb"] + df["o_tov"] + 0.44 * df["o_fta"]
    df["poss"] = pd.concat([poss_t, poss_o], axis=1).mean(axis=1, skipna=True)
    per = 600 if ctx.league == "wnba" else 720
    df["secs"] = 4 * per + 300 * (df["periods"] - 4).clip(lower=0)
    ok = df["poss"].notna()
    if ok.any() and (~ok).any():
        pace = float(df.loc[ok, "poss"].sum() / df.loc[ok, "secs"].sum())
        df.loc[~ok, "poss"] = pace * df.loc[~ok, "secs"]
    df["box_missing"] = miss_t
    df["win"] = (df["pts"] > df["opp_pts"]).astype(int)
    df["margin"] = df["pts"] - df["opp_pts"]
    return df.sort_values(["date", "game_id"])


def _ff(d: pd.DataFrame, pre: str = "") -> dict:
    s = {k: float(d[f"{pre}{k}"].sum()) for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "tov")}
    other = "o_" if pre == "" else ""
    o_dreb, o_oreb = float(d[f"{other}dreb"].sum()), float(d[f"{other}oreb"].sum())
    poss = float(d["poss"].sum())
    return {"efg": an.div(s["fgm"] + 0.5 * s["tpm"], s["fga"]), "tov": an.div(s["tov"], poss),
            "orb": an.div(s["oreb"], s["oreb"] + o_dreb), "ftr": an.div(s["ftm"], s["fga"]), "drb": an.div(s["dreb"], s["dreb"] + o_oreb)}


def build(ctx: SeasonContext, players_cat: dict | None = None, lineup_tables: dict | None = None, prev_box: pd.DataFrame | None = None,
          ratings_7d: dict | None = None) -> dict:
    """teams.json for one league-season (PAYLOADS.md)."""
    league, season = ctx.league, ctx.season
    df = _team_frame(ctx)
    rt = (ctx.ratings or {}).get("teams") or {}
    sim = (ctx.sim or {}).get("teams") or {}
    fut = ctx.futures or {}
    champ = ((fut.get("champion") or {}).get("probs") or {}) if isinstance(fut.get("champion"), dict) else {}
    pcat = (players_cat or {}).get("players") or {}
    sh = ctx.shots
    shot_by_team = dict(tuple(sh.groupby("team"))) if sh is not None and not sh.empty else {}
    def_by_team: dict[str, pd.DataFrame] = {}
    if sh is not None and not sh.empty:
        opp = {}
        for gid, g in ctx.games.items():
            opp[(gid, str(g.get("home")))] = str(g.get("away"))
            opp[(gid, str(g.get("away")))] = str(g.get("home"))
        dt = pd.Series([opp.get((g, t)) for g, t in zip(sh["game_id"].astype(str), sh["team"].astype(str))], index=sh.index)
        def_by_team = dict(tuple(sh.assign(def_team=dt).groupby("def_team")))
    ts = ctx.team_stints
    oo_all = {}
    tot = (ctx.pbp_totals or {}).get("teams") or {}
    b2b = _b2b(ctx)
    inj = injuries(ctx)
    sched_net = {t: (rt.get(t) or {}).get("net") for t in ctx.teams}
    remaining = {}
    for g in ctx.games.values():
        if g.get("status") == "pre" and g.get("stype") in ("reg", "cup"):
            h, a = str(g.get("home")), str(g.get("away"))
            remaining.setdefault(h, []).append(a)
            remaining.setdefault(a, []).append(h)
    pregame_p = _pregame(ctx, df)
    out_teams: dict[str, dict] = {}
    rows: dict[str, dict] = {}
    for t in ctx.teams:
        info = an.team_info(ctx.store, t)
        d = df[df["team"] == t] if not df.empty else pd.DataFrame()
        v: dict[str, Any] = {}
        r = rt.get(t) or {}
        v["model_off"], v["model_def"], v["model_net"], v["model_se"] = r.get("off"), r.get("def"), r.get("net"), r.get("se_net")
        v["elo"] = (ctx.elo_season.get("end") or {}).get(t)
        if ratings_7d and r.get("net") is not None and (ratings_7d.get(t) or {}).get("net") is not None:
            v["net_7d_change"] = r["net"] - ratings_7d[t]["net"]
        log = []
        if not d.empty:
            n = len(d)
            poss = float(d["poss"].sum())
            v["ortg"] = an.per100(d["pts"].sum(), poss)
            v["drtg"] = an.per100(d["opp_pts"].sum(), poss)
            v["net"] = v["ortg"] - v["drtg"] if v["ortg"] is not None and v["drtg"] is not None else None
            v["pace"] = an.div(poss * (2400 if league == "wnba" else 2880), d["secs"].sum())
            v["w"], v["l"] = float(d["win"].sum()), float(n - d["win"].sum())
            v["win_pct"] = v["w"] / n
            pf, pa, k = float(d["pts"].sum()), float(d["opp_pts"].sum()), PYTH_K[league]
            v["pyth_wins"] = n * pf ** k / (pf ** k + pa ** k) if pf + pa > 0 else None
            v["luck"] = v["w"] - v["pyth_wins"] if v["pyth_wins"] is not None else None
            hm, aw = d[d["home"] == 1], d[d["home"] == 0]
            v["home_win_pct"] = an.div(hm["win"].sum(), len(hm)) if len(hm) else None
            v["away_win_pct"] = an.div(aw["win"].sum(), len(aw)) if len(aw) else None
            close = d[d["margin"].abs() <= 5]
            v["close_win_pct"] = an.div(close["win"].sum(), len(close)) if len(close) else None
            v["mov"] = float(d["margin"].mean())
            db = d[d["fga"].notna() & d["o_fga"].notna()]   # box-score rates: games with both box scores
            ff, of = _ff(db, ""), _ff(db, "o_")
            v["efg"], v["tov_pct"], v["orb_pct"], v["ftr"] = ff["efg"], ff["tov"], ff["orb"], ff["ftr"]
            v["opp_efg"], v["opp_tov_pct"], v["opp_ftr"] = of["efg"], of["tov"], of["ftr"]
            v["drb_pct"] = ff["drb"]
            S = lambda c: float(db[c].sum())  # noqa: E731
            v["fg3"] = an.div(S("tpm"), S("tpa"))
            v["tpar"] = an.div(S("tpa"), S("fga"))
            v["fg2"] = an.div(S("fgm") - S("tpm"), S("fga") - S("tpa"))
            v["ft"] = an.div(S("ftm"), S("fta"))
            v["ast_rate"] = an.div(S("ast"), S("fgm"))
            v["opp_fg3"] = an.div(S("o_tpm"), S("o_tpa"))
            v["opp_tpar"] = an.div(S("o_tpa"), S("o_fga"))
            v["stl_pct"] = an.div(S("stl"), S("poss"))
            v["blk_pct"] = an.div(S("blk"), S("o_fga") - S("o_tpa"))
            for k, c in (("pts_paint_g", "pts_paint"), ("pts_fb_g", "pts_fastbreak"), ("pts_off_tov_g", "pts_off_tov"),
                         ("lead_changes_g", "lead_changes")):
                v[k] = float(d[c].mean()) if d[c].notna().any() else None
            for key, sub in (("home_net", hm), ("away_net", aw)):
                p = float(sub["poss"].sum())
                v[key] = an.per100(sub["pts"].sum() - sub["opp_pts"].sum(), p) if p > 0 else None
            bb = d[[b2b.get((t, gid), False) for gid in d["game_id"]]]
            rr = d[[not b2b.get((t, gid), False) for gid in d["game_id"]]]
            for key, sub in (("b2b_net", bb), ("rest_net", rr)):
                p = float(sub["poss"].sum())
                v[key] = an.per100(sub["pts"].sum() - sub["opp_pts"].sum(), p) if p > 0 and len(sub) >= 3 else None
            opp_nets = [sched_net.get(o) for o in d["opp"]]
            v["sos"] = an.mean(opp_nets)
            # log with the model's net rating after each game
            path = {x["game"]: x["net"] for x in ((ctx.ratings or {}).get("paths") or {}).get(t) or []}
            p_home = pregame_p.get(t) or {}
            for x in d.itertuples(index=False):
                p = float(x.poss) if x.poss == x.poss else None
                log.append({"game": x.game_id, "date": x.date, "opp": x.opp, "home": bool(x.home),
                            "res": "W" if x.win else "L", "pts": int(x.pts), "opp_pts": int(x.opp_pts),
                            "ortg": an.rnd(an.per100(x.pts, p), 1), "drtg": an.rnd(an.per100(x.opp_pts, p), 1),
                            "pace": an.rnd(an.div(p * (2400 if league == "wnba" else 2880), x.secs), 1) if p else None,
                            "net_rating_after": an.rnd(path.get(x.game_id), 2), "p_win": an.rnd(p_home.get(x.game_id), 4)})
        rem = remaining.get(t) or []
        v["sos_remaining"] = an.mean(sched_net.get(o) for o in rem) if rem else None
        # shots
        mine, theirs = shot_by_team.get(t), def_by_team.get(t)
        shot_profile = None
        if mine is not None and len(mine):
            if "xpts" in mine:
                v["xpps"] = float(mine["xpts"].mean())
                v["pox100"] = float(100 * (mine["pts"].sum() - mine["xpts"].sum()) / len(mine))
            v["rim_freq"] = float((mine["zone"] == "rim").mean())
            v["mid_freq"] = float(mine["zone"].isin(["mid", "paint"]).mean())
            v["c3_freq"] = float((mine["zone"] == "corner3").mean())
            v["avg_dist"] = float(mine["dist_ft"].mean())
            shot_profile = {"for": zones_table(mine, sh), "against": zones_table(theirs, sh) if theirs is not None else {}}
        if theirs is not None and len(theirs):
            if "xpts" in theirs:
                v["opp_xpps"] = float(theirs["xpts"].mean())
                v["opp_pox100"] = float(100 * (theirs["pts"].sum() - theirs["xpts"].sum()) / len(theirs))
            v["opp_rim_freq"] = float((theirs["zone"] == "rim").mean())
            v["opp_three_freq"] = float((theirs["value"] == 3).mean())
        # possessions and clutch from the pbp pass
        tt = tot.get(t)
        if tt:
            pz = tt.get("poss", 0.0)
            v["tr_share"] = an.div(tt.get("poss_tr", 0.0), pz)
            v["tr_ppp"] = an.div(tt.get("pts_tr", 0.0), tt.get("poss_tr", 0.0))
            v["hc_ppp"] = an.div(tt.get("pts_hc", 0.0), tt.get("poss_hc", 0.0))
            v["ato_ppp"] = an.div(tt.get("pts_ato", 0.0), tt.get("poss_ato", 0.0)) if tt.get("poss_ato", 0) >= 10 else None
            cp, cd = tt.get("c_poss", 0.0), tt.get("c_poss_d", 0.0)
            v["clutch_poss"] = 0.5 * (cp + cd)
            v["clutch_net"] = 100 * (tt.get("c_pf", 0.0) / cp - tt.get("c_pa", 0.0) / cd) if cp >= 10 and cd >= 10 else None
        cg = sum(1 for gid, s in (ctx.pbp_summaries or {}).items() if s.get("clutch_game") and t in (s.get("teams") or {}))
        if ctx.pbp_summaries:
            v["clutch_games"] = float(cg)
        # rotation
        roster, rot = [], {"games": [], "players": [], "minutes": []}
        bx = ctx.box
        if bx is not None and not bx.empty:
            tb = bx[(bx["team"] == t) & (bx["sec"] > 0)]
            if not tb.empty:
                g = tb.groupby("player_id")
                mpg = g["sec"].sum() / 60.0 / g.size()
                v["depth"] = float((mpg >= 10).sum())
                v["players_used"] = float(len(mpg))
                v["starter_min_share"] = an.div(tb[tb["starter"] == 1]["sec"].sum(), tb["sec"].sum())
                v["continuity"] = LU.continuity(bx, prev_box, t)
                rot = LU.rotation_matrix(bx, t)
                mins = g["sec"].sum() / 60.0
                for pid in mins.sort_values(ascending=False).index:
                    h = ctx.hpm.get(str(pid)) or {}
                    roster.append({"id": str(pid), "name": an.player_name(ctx.store, pid),
                                   "pos": (ctx.players.get(str(pid)) or {}).get("pos"), "min": int(round(mins[pid])), "gp": int(g.size()[pid]),
                                   "hpm": an.rnd(h.get("t"), 2), "o": an.rnd(h.get("o"), 2), "d": an.rnd(h.get("d"), 2),
                                   "mpg": an.rnd(mpg[pid], 1)})
        units = (lineup_tables or {}).get(t) or []
        if units:
            tot_poss = sum(u["poss"] for u in units) or 1.0
            v["top_lineup_share"] = units[0]["poss"] / tot_poss
            q = [u for u in units if u.get("qualified") and u.get("net") is not None]
            v["best_lineup_net"] = max((u["net"] for u in q), default=None)
        oo = LU.on_off(ts, t) if ts is not None and not ts.empty else {}
        # injuries: model net less the out players' impact
        out_players = inj.get(t) or []
        loss = sum(float(p.get("impact") or 0.0) for p in out_players if str(p.get("status", "")).lower() == "out")
        v["inj_adj_net"] = (r.get("net") - loss) if r.get("net") is not None else None
        # projections
        s = sim.get(t) or {}
        v["exp_w"], v["p_playoffs"], v["p_conf"], v["p_title"] = s.get("exp_w"), s.get("p_playoffs"), s.get("p_conf"), s.get("p_title")
        if champ.get(t) is not None:
            v["p_title_market"] = champ.get(t)
            v["title_edge"] = (s.get("p_title") - champ[t]) if s.get("p_title") is not None else None
        rows[t] = {"values": an.round_values(v, METRICS)}
        out_teams[t] = {
            "name": info["name"], "abbr": info["abbr"], "short": info["short"], "colour": info["colour"],
            "conference": info["conference"], "division": info["division"], "log": log, "roster": roster,
            "lineups": [_unit(u) for u in units[:25]],
            "pairs": [_unit(u) for u in LU.lineup_table(ts, t, 2, ctx.hpm, limit=15)] if ts is not None and not ts.empty else [],
            "trios": [_unit(u) for u in LU.lineup_table(ts, t, 3, ctx.hpm, limit=15)] if ts is not None and not ts.empty else [],
            "rotation": rot,
            "on_off": {p: {"on_net": an.rnd(o["on_net"], 2), "off_net": an.rnd(o["off_net"], 2), "diff": an.rnd(o["diff"], 2),
                           "poss_on": an.rnd(o["poss_on"], 1)} for p, o in oo.items()},
            "shot_profile": shot_profile,
            "injuries": out_players,
            "odds": _odds(s, fut, t),
            "rating_path": ((ctx.ratings or {}).get("paths") or {}).get(t) or [],
        }
    an.add_percentiles(rows, METRICS, list(rows))
    for t, r in rows.items():
        out_teams[t].update({"values": r["values"], "pct": r["pct"], "rank": r["rank"]})
    return {"ok": True, "league": league, "season": season, "updated_at": an.now(), "metrics": METRICS, "groups": GROUPS,
            "teams": out_teams, "names": _names(ctx, out_teams, pcat)}


def _names(ctx: SeasonContext, out_teams: dict, pcat: dict) -> dict[str, str]:
    """{pid: name} for every player the team pages list (lineups, rotations, rosters, injuries) who is not in the season's
    player catalogue (players.json keeps the players above its minutes floor only): without it the page shows the id."""
    ids: set[str] = set()

    def walk(o, key=None):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("id", "pid") and isinstance(v, (str, int)) and not isinstance(v, bool):
                    ids.add(str(v))
                if str(k).isdigit():                         # tables keyed by player (on_off)
                    ids.add(str(k))
                walk(v, k)
        elif isinstance(o, list):
            for v in o:
                if key == "players" and isinstance(v, (str, int)) and not isinstance(v, bool):
                    ids.add(str(v))
                walk(v, key)
    walk(out_teams)
    people = ctx.players or {}
    out = {}
    for pid in sorted(ids):
        if (pcat.get(pid) or {}).get("name"):
            continue
        nm = (people.get(pid) or {}).get("name")
        if nm:
            out[pid] = nm
    return out


def _pregame(ctx: SeasonContext, df) -> dict[str, dict[str, float]]:
    """{team: {game: pregame model P(team wins)}} for the games in the team log (ratings before the game day)."""
    from oddsmarkets.basketball.analytics.games import model_line
    out: dict[str, dict[str, float]] = {}
    if df is None or df.empty:
        return out
    for gid in df["game_id"].unique():
        g = ctx.games.get(gid)
        if not g:
            continue
        try:
            m = model_line(ctx, g, use_injuries=False)
        except Exception:  # noqa: BLE001
            m = None
        if not m or m.get("p_home") is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        out.setdefault(h, {})[gid] = m["p_home"]
        out.setdefault(a, {})[gid] = 1.0 - m["p_home"]
    return out


def _unit(u: dict) -> dict:
    return {"players": u["players"], "poss": an.rnd(u["poss"], 1), "sec": an.rnd(u.get("sec"), 0), "net": an.rnd(u.get("net"), 2),
            "ortg": an.rnd(u.get("ortg"), 2), "drtg": an.rnd(u.get("drtg"), 2), "shrunk_net": an.rnd(u.get("shrunk_net"), 2),
            "hpm_sum": an.rnd(u.get("hpm_sum"), 2), "qualified": bool(u.get("qualified"))}


def _odds(s: dict, fut: dict, t: str) -> dict:
    out = {k: an.rnd(s.get(k), 4) for k in ("p_playoffs", "p_playin", "p_top6", "p_conf", "p_title", "p_div")}
    out["exp_w"] = an.rnd(s.get("exp_w"), 2)
    mk = {}
    for key, block in (("p_title", fut.get("champion")), ("p_playoffs", fut.get("playoffs")), ("p_playin", fut.get("playin"))):
        p = ((block or {}).get("probs") or {}).get(t) if isinstance(block, dict) else None
        if p is not None:
            mk[key] = an.rnd(p, 4)
    for conf, block in ((fut.get("conference") or {}) or {}).items():
        p = ((block or {}).get("probs") or {}).get(t)
        if p is not None:
            mk["p_conf"] = an.rnd(p, 4)
    wt = (fut.get("win_totals") or {}).get(t)
    if wt:
        mk["win_total"] = {"line": wt.get("line"), "p_over": an.rnd(wt.get("p_over"), 4)}
    out["market"] = mk or None
    return out


def _b2b(ctx: SeasonContext) -> dict:
    from oddsmarkets.basketball.analytics.players import _b2b_flags
    return _b2b_flags(ctx)


def injuries(ctx: SeasonContext) -> dict[str, list[dict]]:
    """{team: [{"player","name","status","detail","impact"}]} from the team's next game (or latest game) injury list;
    impact = the player's HPM x expected minutes / game minutes (points per 100 possessions the team loses)."""
    from oddsmarkets.basketball.models import _io
    out: dict[str, list[dict]] = {}
    latest: dict[str, tuple[str, list]] = {}
    for g in ctx.games.values():
        inj = g.get("injuries") or {}
        for t, lst in inj.items():
            d = str(g.get("date") or "")
            if lst and (t not in latest or d > latest[t][0]) and g.get("status") in ("pre", "in"):
                latest[t] = (d, lst)
    gm = _io.game_minutes(ctx.league)
    for t, (_d, lst) in latest.items():
        rows = []
        for r in lst:
            pid = str(r[0])
            h = ctx.hpm.get(pid) or {}
            pj = h.get("proj") or {}
            mins = pj.get("min") or 0.0
            imp = (float(h.get("t", -2.0)) + 2.0) * float(mins) / gm if h else None
            rows.append({"player": pid, "name": an.player_name(ctx.store, pid), "status": r[1] if len(r) > 1 else None,
                         "detail": r[2] if len(r) > 2 else None, "impact": an.rnd(imp, 2), "hpm": an.rnd(h.get("t"), 2),
                         "min": an.rnd(mins, 1)})
        out[t] = rows
    return out
