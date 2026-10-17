"""
Fantasy layer for The Quant Rink (`data/<S>/fantasy.json`, `data/fantasy_backtest.json`, route #/fantasy). Shared spec:
docs/VALUE_SECTIONS.md section 5. Built only from our own data (game logs: gamelog.py; team strength from the same
logs; the game model's win probabilities from schedule.json); no fantasy platform's ownership, ADP, rankings or
prices (their terms do not allow our use), so "waiver targets" are defined from our own projections.

Categories: skaters G, A, +/-, PPP, SOG, HIT, BLK; goalies W, GA, SV, SO (GAA and SV% shown, scored through GA and SV).
Default points (our own, not any platform's): G 2, A 1.5, +/- 0.5, PPP 0.5, SOG 0.3, HIT 0.2, BLK 0.4; W 4, GA -1,
SV 0.2, SO 3 (an elite skater and a No. 1 goalie land near each other, as in most leagues). The page lets the reader change every weight.

Skaters (per game he plays, against a neutral opponent; history = regular-season games before the as-of date in this
season and the two before; each game weighted 0.5^(n / HL), n = his games since it):
  ice time      even-strength minutes (toi - PP - PK) and PP minutes, HL_TOI = 10 games, with 2 pseudo-games at
                his position group's mean. PP unit: rank on his club by weighted PP minutes (1-5 PP1, 6-10 PP2).
  goals         (ixG_es / 60 x es_min + ixG_pp / 60 x pp_min) x finishing x conv; ixG rates over HL_RATE = 40 games
                regressed to the position group's mean with 300 (PP: 60) pseudo-minutes; finishing = (career goals +
                FIN_PRIOR) / (career ixG + FIN_PRIOR), FIN_PRIOR = 40 expected goals (career = the logs since 2018-19);
                conv = league goals / (ixG_es + ixG_pp) (short-handed goals and the xG model's calibration).
  assists       even strength: on-ice 5v5 xGF/60 (regressed, 300 pseudo-minutes) x league 5v5 GF/xGF x his assist
                share of team-mates' 5v5 goals while on the ice ((A5 + 15 x position mean) / (on-ice GF5 - own G5 +
                15)) x es_min / 60; power play: PP assists per PP minute (regressed, 60) x pp_min.
  PPP           PP goals (the PP part of goals) + PP assists.
  +/-           (on-ice 5v5 xGF/60 - xGA/60, regressed) x es_min / 60.
  SOG, HIT, BLK per 60 of all minutes, regressed to the position mean with 200 pseudo-minutes.
  Opponents     goals, assists and PPP x the opponent's goals-against factor (its goals and xG against per game,
                recency-weighted over this and last season, regressed with 10 pseudo-games, over the league's);
                SOG x its shots-against factor; +/- uses its goals-for factor on the against side.
Goalies (per start): GA = his club's xGA per game x the opponent's xG-for factor x (1 - talent) x conv, talent =
  sum(xGA - GA) / (sum xGA + 150) over his starts (HL 80); SA = club's shots against x opponent's shots-for factor;
  SV = SA - GA; W = P(club wins) from the game model x 0.97 (the starter's share of decisions); SO = exp(-GA).
  Start probability: his share of the club's starts (HL 10 club games), the second game of a back-to-back x the
  fitted ratio for the No. 1 goalie (the rest to the others); injured players 0.
Injuries: ESPN injury status and return date (games before the return are missed; no date: as valuation.py).
Rankings: rest-of-season points (games left x availability x per game); tiers at natural gaps (a new tier where the
  drop to the next player is in the largest 10 % of drops among the top 240, at least 3 a tier); value over replacement
  by position on a standard 12-team roster (C 2, LW 2, RW 2, D 4, UTIL 1, G 2, bench 4 = 204 players, filled
  greedily by rank; replacement = the best undrafted at the position); category z-scores over the top 240 skaters
  and 48 goalies. Waiver targets: outside the season-start top 150 (our projection before the first game) and inside
  it now; drops the reverse. Breakouts: 24 or younger, inside our top 300, with ice time up 2+ minutes or PP time up 1+
  minute on last season (last five games). Buy low / sell high (6+ games, top 300): projection minus points a game so
  far >= 0.4 with goals 2+ below finishing-adjusted expected goals or on-ice 5v5 PDO <= 0.950 (sell: the mirror);
  goalies (3+ games, 30 %+ of starts): GSAx this season 4+ goals below (above) his talent x xG faced.
Backtest (`backtest`): walk-forward over the last five completed seasons at weekly checkpoints, our per-game
  projection v two naive baselines; MAE per player-game (games-weighted) and Spearman per checkpoint, next week and
  rest of season. Cached on the completed seasons' logs and VERSION: never recomputed hourly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

VERSION = 1
CATS_S = ("g", "a", "pm", "ppp", "sog", "hit", "blk")
CATS_G = ("w", "ga", "sv", "so")
DEFAULT_POINTS = {"g": 2.0, "a": 1.5, "pm": 0.5, "ppp": 0.5, "sog": 0.3, "hit": 0.2, "blk": 0.4,
                  "w": 4.0, "ga": -1.0, "sv": 0.2, "so": 3.0}
LABELS = {"g": "G", "a": "A", "pm": "+/-", "ppp": "PPP", "sog": "SOG", "hit": "HIT", "blk": "BLK", "w": "W", "ga": "GA", "sv": "SV",
          "so": "SO", "gaa": "GAA", "svp": "SV%"}
HL_TOI, HL_RATE, HL_GOALIE, HL_START, HL_TEAM = 10.0, 40.0, 80.0, 10.0, 20.0
K_IXG, K_IXG_PP, K_APP, K_ON, K_CNT, K_ASH, FIN_PRIOR, G_PRIOR, TEAM_PRIOR = 300.0, 60.0, 60.0, 300.0, 200.0, 15.0, 40.0, 150.0, 10.0
TOI_PSEUDO_GAMES = 2.0
DECISION = 0.97
ROSTER = {"C": 2, "L": 2, "R": 2, "D": 4, "UTIL": 1, "G": 2, "BN": 4}
N_TEAMS = 12
TOP_TIER_POOL = 240
TOP_N = 150
WEEKS = 4
BT_SEASONS = 5
FLAG_GP, FLAG_RANK, FLAG_PTS, FLAG_GOALS, FLAG_PDO, FLAG_GSAX = 6, 300, 0.4, 2.0, 0.05, 4.0
INJ_GAMES = {"day-to-day": 1, "out": 3, "injured reserve": 7, "long-term injured reserve": 25, "suspension": 2}


def _r(v: Any, nd: int = 2):
    v = an.fnum(v)
    return None if v is None or not math.isfinite(v) else round(v, nd)


def pos_group(p: Any) -> str:
    s = str(p or "").upper()
    return "G" if s.startswith("G") else "D" if s.startswith("D") else "F"


# ---------------------------------------------------------------------------------------------- history

def _decay(df: pd.DataFrame, key: str, hl: float) -> np.ndarray:
    """0.5^(n / hl), n = the player's (or club's) games after this one (df sorted by key, date)."""
    n = df.groupby(key, sort=False).cumcount(ascending=False).to_numpy(float)
    return np.power(0.5, n / hl)


def history(logs: dict, asof: str, season: int, back: int = 2) -> dict:
    """Regular-season rows before `asof` from `season` and the `back` seasons before it."""
    seasons = {an.season_id(an.start_year(season) - k) for k in range(back + 1)}
    out = {}
    for k in ("sk", "gk", "tg"):
        d = logs.get(k)
        if d is None or not len(d):
            out[k] = pd.DataFrame()
            continue
        m = (d["gt"] == "R") & (d["date"] < asof) & d["season"].isin(seasons)
        out[k] = d[m.to_numpy()].sort_values(["date", "game_id"]).reset_index(drop=True)
    return out


def team_strength(tg: pd.DataFrame, season: int) -> dict:
    """Per club factors over the league (recency-weighted over this and last season, TEAM_PRIOR pseudo-games):
    def_g (goals and xG against, for skaters' scoring), def_s (shots against), off_g (goals and xG for), off_x (xG for),
    off_s (shots for); plus the club's own xga_pg and sa_pg."""
    if tg is None or not len(tg):
        return {"teams": {}, "lg": {}}
    t = tg[tg["season"].isin([season, an.prev_season(season)])].copy()
    if not len(t):
        return {"teams": {}, "lg": {}}
    t = t.sort_values(["team", "date"])
    w = _decay(t, "team", HL_TEAM) * np.where(t["season"].to_numpy() == season, 1.0, 0.5)
    t["w"] = w
    for c in ("xgf", "xga", "sf", "sa"):
        t[c] = t[c].astype(float).fillna(t[c].astype(float).mean())
    lg = {c: float(np.average(t[c], weights=t["w"])) for c in ("gf", "ga", "xgf", "xga", "sf", "sa")}
    out = {}
    for team, g in t.groupby("team"):
        ww = g["w"].to_numpy()
        s = ww.sum()

        def reg(col):
            return float((np.sum(ww * g[col].to_numpy(float)) + TEAM_PRIOR * lg[col]) / (s + TEAM_PRIOR))
        ga, xga, gf, xgf, sa, sf = reg("ga"), reg("xga"), reg("gf"), reg("xgf"), reg("sa"), reg("sf")
        out[team] = {"def_g": 0.5 * (ga / lg["ga"] + xga / lg["xga"]), "def_s": sa / lg["sa"],
                     "off_g": 0.5 * (gf / lg["gf"] + xgf / lg["xgf"]), "off_x": xgf / lg["xgf"], "off_s": sf / lg["sf"],
                     "xga_pg": xga, "sa_pg": sa, "gf_pg": gf, "ga_pg": ga}
    return {"teams": out, "lg": lg}


# ---------------------------------------------------------------------------------------------- skaters

def skater_rates(sk: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per player: ice time, the regressed rates and the per-game neutral projection of every category."""
    if sk is None or not len(sk):
        return pd.DataFrame()
    d = sk.sort_values(["pid", "date", "game_id"]).reset_index(drop=True)
    num = ["toi", "toipp", "toipk", "ixg_es", "ixg_pp", "g", "a", "a5", "g5", "gf5", "xgf5", "xga5", "toi5", "app", "gpp", "sog",
           "hits", "blk", "pm", "ppp"]
    for c in num:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0.0).astype(float)
    d["toi_es"] = (d["toi"] - d["toipp"] - d["toipk"]).clip(lower=0.0)
    d["grp"] = d["pos"].map(lambda p: "D" if p == "D" else "F")
    wt = _decay(d, "pid", HL_TOI)
    wr = _decay(d, "pid", HL_RATE)
    d["wt"], d["wr"] = wt, wr
    g = d.groupby("pid", sort=False)
    last = g.tail(1).set_index("pid")
    out = pd.DataFrame(index=last.index)
    out["pos"] = last["pos"]
    out["grp"] = last["grp"]
    out["team"] = last["team"]
    out["last_date"] = last["date"]
    out["gp_all"] = g.size()
    cur = d[d["season"] == season]
    out["gp"] = cur.groupby("pid").size().reindex(out.index).fillna(0).astype(int)
    sw = g["wt"].sum()
    for c in ("toi_es", "toipp", "toi"):
        d["_x"] = d[c] * d["wt"]
        out[f"{c}_w"] = d.groupby("pid", sort=False)["_x"].sum() / sw
    # position-group means per minute (all history in d, unweighted)
    def gm(num_col: str, den_col: str) -> dict:
        s = d.groupby("grp")[[num_col, den_col]].sum()
        return {k: float(s.at[k, num_col] / max(s.at[k, den_col], 1e-9)) for k in s.index}
    mu = {"ixg_es": gm("ixg_es", "toi_es"), "ixg_pp": gm("ixg_pp", "toipp"), "app": gm("app", "toipp"), "xgf5": gm("xgf5", "toi5"),
          "xga5": gm("xga5", "toi5"), "sog": gm("sog", "toi"), "hits": gm("hits", "toi"), "blk": gm("blk", "toi")}
    tm = d.groupby("grp")[["toi_es", "toipp"]].mean()
    grp = out["grp"]
    # ice time with pseudo-games at the group mean
    for c, mc in (("toi_es_w", "toi_es"), ("toipp_w", "toipp")):
        m = grp.map(lambda x: float(tm.at[x, mc]) if x in tm.index else 0.0)
        n = out["gp_all"].clip(upper=30).astype(float)
        out[c] = (out[c] * n + TOI_PSEUDO_GAMES * m) / (n + TOI_PSEUDO_GAMES)

    def rate(num_col: str, den_col: str, key: str, k: float) -> pd.Series:
        d["_n"] = d[num_col] * d["wr"]
        d["_d"] = d[den_col] * d["wr"]
        s = d.groupby("pid", sort=False)[["_n", "_d"]].sum()
        m = grp.map(lambda x: mu[key].get(x, 0.0))
        return (s["_n"] + k * m) / (s["_d"] + k) * 60.0
    out["ixg_es60"] = rate("ixg_es", "toi_es", "ixg_es", K_IXG)
    out["ixg_pp60"] = rate("ixg_pp", "toipp", "ixg_pp", K_IXG_PP)
    out["app60"] = rate("app", "toipp", "app", K_APP)
    out["xgf60"] = rate("xgf5", "toi5", "xgf5", K_ON)
    out["xga60"] = rate("xga5", "toi5", "xga5", K_ON)
    out["sog60"] = rate("sog", "toi", "sog", K_CNT)
    out["hit60"] = rate("hits", "toi", "hits", K_CNT)
    out["blk60"] = rate("blk", "toi", "blk", K_CNT)
    car = g[["g", "ixg_es", "ixg_pp", "a5", "gf5", "g5"]].sum()
    lg_g = float(d["g"].sum())
    lg_x = float((d["ixg_es"] + d["ixg_pp"]).sum())
    conv = lg_g / lg_x if lg_x > 0 else 1.0
    out.attrs["conv"] = conv
    out["fin"] = (car["g"] + FIN_PRIOR * conv) / ((car["ixg_es"] + car["ixg_pp"]) * conv + FIN_PRIOR * conv)
    oth = (car["gf5"] - car["g5"]).clip(lower=0.0)
    sh = d.groupby("grp")[["a5", "gf5", "g5"]].sum()
    msh = {k: float(sh.at[k, "a5"] / max(sh.at[k, "gf5"] - sh.at[k, "g5"], 1e-9)) for k in sh.index}
    out["ashare"] = (car["a5"] + K_ASH * grp.map(lambda x: msh.get(x, 0.4))) / (oth + K_ASH)
    gf5, xgf5 = float(d["gf5"].sum()), float(d["xgf5"].sum())
    conv5 = gf5 / xgf5 if xgf5 > 0 else 1.0
    es, pp, tot = out["toi_es_w"], out["toipp_w"], out["toi_w"]
    out["g_es"] = out["ixg_es60"] * es / 60.0 * out["fin"] * conv
    out["g_pp"] = out["ixg_pp60"] * pp / 60.0 * out["fin"] * conv
    out["a_es"] = out["xgf60"] * conv5 * out["ashare"] * es / 60.0
    out["a_pp"] = out["app60"] * pp / 60.0
    out["pm_f"] = out["xgf60"] * conv5 * es / 60.0
    out["pm_a"] = out["xga60"] * conv5 * es / 60.0
    out["sog"] = out["sog60"] * tot / 60.0
    out["hit"] = out["hit60"] * tot / 60.0
    out["blk"] = out["blk60"] * tot / 60.0
    # PP unit: rank by weighted PP minutes among his club's skaters seen in the last 30 days of games
    recent = out[out["last_date"] >= (pd.to_datetime(out["last_date"]).max() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")]
    rk = recent.groupby("team")["toipp_w"].rank(ascending=False, method="first")
    out["pp_rank"] = rk.reindex(out.index)
    out["pp_unit"] = np.where(out["pp_rank"] <= 5, 1, np.where(out["pp_rank"] <= 10, 2, 0))
    d.drop(columns=["_x", "_n", "_d"], inplace=True, errors="ignore")
    return out


def skater_cats(r: pd.DataFrame, def_g: np.ndarray | float = 1.0, def_s: np.ndarray | float = 1.0,
                off_g: np.ndarray | float = 1.0) -> dict[str, np.ndarray]:
    """Per-game categories for the rows of skater_rates against opponent factors (scalars or arrays)."""
    g = (r["g_es"].to_numpy() + r["g_pp"].to_numpy()) * def_g
    a = (r["a_es"].to_numpy() + r["a_pp"].to_numpy()) * def_g
    ppp = (r["g_pp"].to_numpy() + r["a_pp"].to_numpy()) * def_g
    pm = r["pm_f"].to_numpy() * def_g - r["pm_a"].to_numpy() * off_g
    return {"g": g, "a": a, "pm": pm, "ppp": ppp, "sog": r["sog"].to_numpy() * def_s, "hit": r["hit"].to_numpy(),
            "blk": r["blk"].to_numpy()}


def points(cats: dict[str, Any], w: dict[str, float] | None = None) -> Any:
    w = w or DEFAULT_POINTS
    tot = 0.0
    for k, v in cats.items():
        if k in w:
            tot = tot + w[k] * v
    return tot


# ---------------------------------------------------------------------------------------------- goalies

def b2b_ratio(gk: pd.DataFrame, tg: pd.DataFrame) -> float:
    """The No. 1 goalie's start rate on the second game of a back-to-back over his start rate otherwise."""
    if gk is None or not len(gk) or tg is None or not len(tg):
        return 0.5
    t = tg[["season", "game_id", "date", "team"]].drop_duplicates().sort_values(["team", "date"]).copy()
    dts = pd.to_datetime(t["date"])
    prev = dts.groupby(t["team"]).shift(1)
    t["b2b"] = ((dts - prev).dt.days == 1).to_numpy()
    st = gk[gk["start"] == 1][["game_id", "team", "pid"]]
    t = t.merge(st, on=["game_id", "team"], how="left")
    no1 = t.groupby(["season", "team"])["pid"].agg(lambda s: s.value_counts().index[0] if s.notna().any() else None)
    t["no1"] = [no1.get((s, tm)) for s, tm in zip(t["season"], t["team"])]
    t["is1"] = (t["pid"] == t["no1"]).astype(float)
    a = t[t["b2b"]]["is1"].mean()
    b = t[~t["b2b"]]["is1"].mean()
    return float(a / b) if b and np.isfinite(a) and a > 0 else 0.5


def goalie_rates(gk: pd.DataFrame, tg: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per goalie: club (last game), start share of his club's games (HL_START club games), talent (GSAx per xG,
    regressed), appearances this season."""
    if gk is None or not len(gk):
        return pd.DataFrame()
    d = gk.sort_values(["pid", "date"]).reset_index(drop=True).copy()
    d["xga"] = pd.to_numeric(d["xga"], errors="coerce").fillna(0.0)
    d["ga_x"] = pd.to_numeric(d["ga_x"], errors="coerce").fillna(d["ga"]).astype(float)
    d["w"] = _decay(d, "pid", HL_GOALIE)
    g = d.groupby("pid", sort=False)
    last = g.tail(1).set_index("pid")
    out = pd.DataFrame(index=last.index)
    out["team"] = last["team"]
    out["last_date"] = last["date"]
    d["_gs"] = (d["xga"] - d["ga_x"]) * d["w"]
    d["_x"] = d["xga"] * d["w"]
    s = d.groupby("pid", sort=False)[["_gs", "_x"]].sum()
    out["talent"] = s["_gs"] / (s["_x"] + G_PRIOR)
    out["gp"] = d[d["season"] == season].groupby("pid").size().reindex(out.index).fillna(0).astype(int)
    out["gs"] = d[(d["season"] == season) & (d["start"] == 1)].groupby("pid").size().reindex(out.index).fillna(0).astype(int)
    # start share over each club's recent games (the goalie's current club)
    share = {}
    if tg is not None and len(tg):
        tt = tg[["game_id", "date", "team"]].drop_duplicates().sort_values(["team", "date"])
        starts = d[d["start"] == 1][["game_id", "team", "pid"]]
        for team, grp in tt.groupby("team"):
            grp = grp.tail(60)
            w = np.power(0.5, np.arange(len(grp))[::-1] / HL_START)
            st = starts[starts["team"] == team].set_index("game_id")["pid"]
            ids = [st.get(x) for x in grp["game_id"]]
            tot = w.sum()
            acc: dict[int, float] = {}
            for pid, ww in zip(ids, w):
                if pid is not None and not (isinstance(pid, float) and math.isnan(pid)):
                    acc[int(pid)] = acc.get(int(pid), 0.0) + ww
            for pid, v in acc.items():
                share[(team, pid)] = v / tot
    out["share"] = [share.get((t, int(p)), 0.0) for p, t in zip(out.index, out["team"])]
    d.drop(columns=["_gs", "_x"], inplace=True)
    return out


def goalie_game(gr: dict, team: dict, opp: dict, p_win: float, lg_conv: float) -> dict:
    ga = team.get("xga_pg", 2.9) * opp.get("off_x", 1.0) * (1.0 - float(gr.get("talent") or 0.0)) * lg_conv
    sa = team.get("sa_pg", 28.0) * opp.get("off_s", 1.0)
    return {"w": p_win * DECISION, "ga": ga, "sv": max(sa - ga, 0.0), "so": math.exp(-ga), "sa": sa}


# ---------------------------------------------------------------------------------------------- projection at a date

def project_at(logs: dict, asof: str, season: int) -> dict:
    """Everything the live page and the backtest share: skater rates, goalie rates, club factors, b2b ratio and the
    league's goalie conversion (GA / xGA)."""
    H = history(logs, asof, season)
    ts = team_strength(H["tg"], season)
    sr = skater_rates(H["sk"], season)
    gr = goalie_rates(H["gk"], H["tg"], season)
    gk = H["gk"]
    conv = float(gk["ga_x"].sum() / max(gk["xga"].sum(), 1e-9)) if len(gk) and "xga" in gk and gk["xga"].sum() > 0 else 1.0
    return {"H": H, "ts": ts, "sr": sr, "gr": gr, "b2b": b2b_ratio(H["gk"], H["tg"]), "conv_g": conv}


def _opp_arrays(ts: dict, opps: list[str]) -> tuple[float, float, float]:
    T = ts.get("teams") or {}
    if not opps:
        return 1.0, 1.0, 1.0
    dg = np.mean([(T.get(o) or {}).get("def_g", 1.0) for o in opps])
    ds = np.mean([(T.get(o) or {}).get("def_s", 1.0) for o in opps])
    og = np.mean([(T.get(o) or {}).get("off_g", 1.0) for o in opps])
    return float(dg), float(ds), float(og)


def start_probs(goalies: list[tuple[int, float]], b2b: bool, ratio: float, out_ids: set | None = None) -> dict[int, float]:
    """{pid: P(starts)} for one club game: shares renormalised, a back-to-back second game moves the No. 1's share by
    `ratio` and gives the rest to the others; injured goalies 0."""
    gl = [(p, s) for p, s in goalies if not (out_ids and p in out_ids) and s > 0]
    if not gl:
        return {}
    tot = sum(s for _, s in gl)
    sh = {p: s / tot for p, s in gl}
    if b2b and len(sh) > 1:
        no1 = max(sh, key=sh.get)
        new1 = min(sh[no1] * ratio, 1.0)
        rest = 1.0 - sh[no1]
        sh = {p: (new1 if p == no1 else (s / rest * (1.0 - new1) if rest > 0 else 0.0)) for p, s in sh.items()}
    return sh


# ---------------------------------------------------------------------------------------------- tiers, VOR, z

def tiers(values: list[float], pool: int = TOP_TIER_POOL, q: float = 0.9, min_size: int = 3) -> list[int]:
    """Tier numbers (1, 2, ...) for values sorted descending: a new tier where the drop to the next is among the largest
    10 % of drops within the top `pool`."""
    if not values:
        return []
    v = list(values)
    top = v[:pool]
    drops = [top[i] - top[i + 1] for i in range(len(top) - 1)]
    sd = sorted(drops)
    cut = float(sd[min(len(sd) - 1, int(math.floor(q * (len(sd) - 1))))]) if len(sd) >= 5 else float("inf")   # as fantasy.js
    out, t, size = [], 1, 0
    for i in range(len(v)):
        out.append(t)
        size += 1
        if i < len(v) - 1 and i < pool - 1 and size >= min_size and (v[i] - v[i + 1]) > cut and cut > 0:
            t += 1
            size = 0
    last = out[min(pool, len(out)) - 1] if out else 1
    return [x if i < pool else last + 1 for i, x in enumerate(out)]


def replacement(players: list[dict], key: str = "ros", roster: dict | None = None, n_teams: int = N_TEAMS) -> dict[str, float]:
    """Greedy draft of n_teams standard rosters by `key`; replacement = the best undrafted player at each position."""
    roster = roster or ROSTER
    slots = {p: n * n_teams for p, n in roster.items()}
    taken = set()
    for p in sorted(players, key=lambda x: -(x.get(key) or 0)):
        pos = p["pos"]
        if pos == "G":
            opts = ["G", "BN"]
        else:
            opts = [pos, "UTIL", "BN"]
        for o in opts:
            if slots.get(o, 0) > 0:
                slots[o] -= 1
                taken.add(p["id"])
                break
    out = {}
    for pos in ("C", "L", "R", "D", "G"):
        und = [p.get(key) or 0 for p in players if p["pos"] == pos and p["id"] not in taken]
        out[pos] = float(max(und)) if und else 0.0
    return out


def zscores(rows: list[dict], cats: list[str], pool: int, rate_cats: dict | None = None) -> dict[str, float]:
    """Sum of category z-scores over the top `pool` rows (by the default points) for every row."""
    if not rows:
        return {}
    ref = sorted(rows, key=lambda r: -(r.get("ros") or 0))[:pool]
    z = {r["id"]: 0.0 for r in rows}
    for c in cats:
        vals = np.array([r.get(c) or 0.0 for r in ref], float)
        mu, sd = float(vals.mean()), float(vals.std()) or 1.0
        sign = -1.0 if c == "ga" else 1.0
        for r in rows:
            z[r["id"]] += sign * ((r.get(c) or 0.0) - mu) / sd
    return z


# ---------------------------------------------------------------------------------------------- live payload

def _weeks(today: date) -> list[tuple[str, str]]:
    """Fantasy weeks Monday-Sunday: this week from today, then the next WEEKS - 1."""
    mon = today - timedelta(days=today.weekday())
    out = [(today.isoformat(), (mon + timedelta(days=6)).isoformat())]
    for k in range(1, WEEKS):
        a = mon + timedelta(days=7 * k)
        out.append((a.isoformat(), (a + timedelta(days=6)).isoformat()))
    return out


def schedule_frame(store: dict, pw: dict[int, float], today: date) -> pd.DataFrame:
    rows = []
    gs = (store or {}).get("games") or {}
    for g in (gs.values() if isinstance(gs, dict) else gs):
        gid = str(g.get("game_id") or "")
        if gid[4:6] != "02" or str(g.get("status") or "").lower() in ("final", "off", "official"):
            continue
        d = str(g.get("date") or "")[:10]
        if d < today.isoformat():
            continue
        ph = pw.get(int(gid))
        for team, opp, home in ((g.get("home"), g.get("away"), 1), (g.get("away"), g.get("home"), 0)):
            rows.append([int(gid), d, team, opp, home, None if ph is None else (ph if home else 1 - ph)])
    s = pd.DataFrame(rows, columns=["game_id", "date", "team", "opp", "home", "p_win"]).sort_values(["team", "date"])
    if len(s):
        dts = pd.to_datetime(s["date"])
        s["b2b"] = ((dts - dts.groupby(s["team"]).shift(1)).dt.days == 1).to_numpy()
    else:
        s["b2b"] = []
    return s.reset_index(drop=True)


def _inj_games(inj: dict | None, dates: list[str], today: date) -> int:
    if not inj:
        return 0
    s = str(inj.get("status") or "").lower()
    if not s or s in ("active", "probable"):
        return 0
    ret = inj.get("ret")
    if ret:
        return int(sum(1 for d in dates if today.isoformat() <= d < str(ret)[:10]))
    for k, n in INJ_GAMES.items():
        if k in s and not (k == "injured reserve" and "long" in s):
            return n
    return 0


def build_current(season: int, logs: dict, store: dict, today: date, injuries: dict[str, dict] | None, catalogue: dict | None = None,
                  backtest_summary: dict | None = None, phase: str | None = None) -> dict:
    """fantasy.json for the current season."""
    from oddsmarkets.nhl.analytics import gamelog as GL
    asof = today.isoformat()
    P = project_at(logs, asof, season)
    sr, gr, ts = P["sr"], P["gr"], P["ts"]
    T = ts.get("teams") or {}
    players = {an.sid(k): v for k, v in ((store or {}).get("players") or {}).items() if isinstance(v, dict) and v.get("team")}
    sched = schedule_frame(store, GL._pwin(season), today)
    weeks = _weeks(today)
    by_team = {t: g for t, g in sched.groupby("team")} if len(sched) else {}
    inj = injuries or {}
    pre = preseason_ranks(logs, season, store)
    # season-to-date actuals (this season's regular-season games)
    sk = logs.get("sk")
    gk = logs.get("gk")
    cur_sk = sk[(sk["season"] == season) & (sk["gt"] == "R")] if sk is not None and len(sk) else pd.DataFrame()
    cur_gk = gk[(gk["season"] == season) & (gk["gt"] == "R")] if gk is not None and len(gk) else pd.DataFrame()
    act_s = cur_sk.groupby("pid")[["g", "a", "pm", "ppp", "sog", "hits", "blk", "ixg_es", "ixg_pp", "toi"]].sum() if len(cur_sk) else pd.DataFrame()
    gp_s = cur_sk.groupby("pid").size() if len(cur_sk) else pd.Series(dtype=int)
    rec5 = cur_sk.sort_values("date").groupby("pid").tail(5).groupby("pid")[["toi", "toipp"]].mean() if len(cur_sk) else pd.DataFrame()
    prev = sk[(sk["season"] == an.prev_season(season)) & (sk["gt"] == "R")] if sk is not None and len(sk) else pd.DataFrame()
    prev_toi = prev.groupby("pid")[["toi", "toipp"]].mean() if len(prev) else pd.DataFrame()
    pdo = {}
    for pid, r in ((catalogue or {}).get("players") or {}).items():
        v = r.get("values") or {}
        if v.get("pdo") is not None and (v.get("toi5") or 0) >= 60:
            pdo[str(pid)] = (v.get("pdo"), v.get("on_sh_pct"), v.get("on_sv_pct"))
    goalie_out = set()
    for pid, p in players.items():
        if str(p.get("pos") or "").upper().startswith("G") and pid in inj:
            tgx = by_team.get(p["team"])
            if _inj_games(inj[pid], list(tgx["date"]) if tgx is not None else [], today) > 0:
                goalie_out.add(int(pid))
    rows = []
    sr_idx = set(int(x) for x in sr.index) if len(sr) else set()
    for pid, p in players.items():
        pos = str(p.get("pos") or "C").upper()[:1]
        team = p["team"]
        tg = by_team.get(team)
        dates = list(tg["date"]) if tg is not None else []
        opps = list(tg["opp"]) if tg is not None else []
        ig = _inj_games(inj.get(pid), dates, today)
        age = an.age_on(p.get("dob"), season) if p.get("dob") else None
        base = {"id": pid, "name": p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x), "team": team, "pos": pos,
                "age": age, "inj": inj.get(pid), "inj_games": ig, "left": len(dates)}
        if pos == "G":
            continue
        ipid = int(pid)
        if ipid not in sr_idx:
            continue
        r = sr.loc[[ipid]]
        rr = sr.loc[ipid]
        # every remaining game: opponent factors
        avail_dates = dates[ig:]
        avail_opps = opps[ig:]
        dg, ds, og = _opp_arrays(ts, avail_opps)
        c_ros = {k: float(v[0]) for k, v in skater_cats(r, dg, ds, og).items()}
        c_neutral = {k: float(v[0]) for k, v in skater_cats(r).items()}
        n_ros = len(avail_dates)
        wk = []
        for a, b in weeks:
            idx = [i for i, d in enumerate(avail_dates) if a <= d <= b]
            if not idx:
                wk.append([0, 0.0])
                continue
            dg2, ds2, og2 = _opp_arrays(ts, [avail_opps[i] for i in idx])
            cw = {k: float(v[0]) for k, v in skater_cats(r, dg2, ds2, og2).items()}
            wk.append([len(idx), points(cw) * len(idx)])
        rec = dict(base)
        rec.update({"kind": "S", "pp_unit": int(rr["pp_unit"]), "toi": float(rr["toi_w"]), "toi_es": float(rr["toi_es_w"]),
                    "toi_pp": float(rr["toipp_w"]), "pg": c_neutral, "pts_pg": float(points(c_ros)), "n_ros": n_ros,
                    "ros_c": {k: v * n_ros for k, v in c_ros.items()}, "ros": float(points(c_ros)) * n_ros, "weeks": wk,
                    "fin": float(rr["fin"]), "gp": int(gp_s.get(ipid, 0)) if len(gp_s) else 0})
        if len(act_s) and ipid in act_s.index:
            a = act_s.loc[ipid]
            gpn = max(int(gp_s.get(ipid, 0)), 1)
            ac = {"g": a["g"], "a": a["a"], "pm": a["pm"], "ppp": a["ppp"], "sog": a["sog"], "hit": a["hits"], "blk": a["blk"]}
            rec["act_pg"] = float(points(ac)) / gpn
            rec["luck_g"] = float(a["g"] - (a["ixg_es"] + a["ixg_pp"]) * rr["fin"] * float(sr.attrs.get("conv", 1.0)))
            rec["xg_s"] = float(a["ixg_es"] + a["ixg_pp"])
            rec["g_s"] = float(a["g"])
            rec["act"] = {k: float(v) for k, v in ac.items()}
        if len(rec5) and ipid in rec5.index:
            rec["toi5"] = float(rec5.at[ipid, "toi"])
            rec["pp5"] = float(rec5.at[ipid, "toipp"])
        if len(prev_toi) and ipid in prev_toi.index:
            rec["toi_prev"] = float(prev_toi.at[ipid, "toi"])
            rec["pp_prev"] = float(prev_toi.at[ipid, "toipp"])
        if pid in pdo:
            rec["pdo"] = pdo[pid]
        rows.append(rec)
    # goalies
    gidx = set(int(x) for x in gr.index) if len(gr) else set()
    club_goalies: dict[str, list[tuple[int, float]]] = {}
    for pid, p in players.items():
        if str(p.get("pos") or "").upper().startswith("G") and int(pid) in gidx:
            g = gr.loc[int(pid)]
            sh = float(g["share"]) if g["team"] == p["team"] else 0.0
            club_goalies.setdefault(p["team"], []).append((int(pid), sh if sh > 0 else 0.02))
    for pid, p in players.items():
        if not str(p.get("pos") or "").upper().startswith("G"):
            continue
        ipid = int(pid)
        team = p["team"]
        tg = by_team.get(team)
        if tg is None:
            continue
        g = gr.loc[ipid] if ipid in gidx else pd.Series({"talent": 0.0, "share": 0.0, "gp": 0, "gs": 0})
        dates = list(tg["date"])
        ig = _inj_games(inj.get(pid), dates, today)
        per, n_starts, wk = [], 0.0, [[0, 0.0, 0.0] for _ in weeks]
        tot = {k: 0.0 for k in CATS_G}
        sa_tot = 0.0
        for i, row in enumerate(tg.itertuples()):
            pr = start_probs(club_goalies.get(team, []), bool(row.b2b), P["b2b"], goalie_out)
            ps = 0.0 if i < ig else pr.get(ipid, 0.0)
            pw = row.p_win if row.p_win is not None and not (isinstance(row.p_win, float) and math.isnan(row.p_win)) else 0.5
            gg = goalie_game(g, T.get(team) or {}, T.get(row.opp) or {}, float(pw), P["conv_g"])
            for k in CATS_G:
                tot[k] += ps * gg[k]
            sa_tot += ps * gg["sa"]
            n_starts += ps
            for wi, (a, b) in enumerate(weeks):
                if a <= row.date <= b:
                    wk[wi][0] += 1
                    wk[wi][1] += ps
                    wk[wi][2] += ps * points(gg)
            if i < 7:
                per.append([row.date, row.opp, round(ps, 3), round(float(pw), 3), round(points(gg), 2)])
        per_start = {k: (tot[k] / n_starts if n_starts > 0 else 0.0) for k in CATS_G}
        rec = {"id": pid, "name": p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x), "team": team, "pos": "G",
               "age": an.age_on(p.get("dob"), season) if p.get("dob") else None, "inj": inj.get(pid), "inj_games": ig, "left": len(dates),
               "kind": "G", "share": float(g.get("share") or 0.0), "talent": float(g.get("talent") or 0.0), "starts": n_starts,
               "ros_c": tot, "ros": float(points(tot)), "pg": per_start, "pts_pg": float(points(per_start)), "weeks": [[w[0], round(w[1], 2), w[2]] for w in wk],
               "next": per, "gaa": tot["ga"] / n_starts if n_starts else None, "svp": tot["sv"] / sa_tot if sa_tot else None,
               "gp": int(g.get("gp") or 0), "gs": int(g.get("gs") or 0)}
        # season luck: GSAx this season v talent
        if len(cur_gk):
            m = cur_gk[cur_gk["pid"] == ipid]
            if len(m):
                xga, ga = float(pd.to_numeric(m["xga"]).fillna(0).sum()), float(pd.to_numeric(m["ga_x"]).fillna(m["ga"]).sum())
                rec["gsax_s"] = xga - ga
                rec["luck_gsax"] = (xga - ga) - rec["talent"] * xga
                rec["sv_s"] = float(m["sv"].sum()) / max(float(m["sa"].sum()), 1.0)
        rows.append(rec)
    return finish_payload(season, rows, P, pre, today, weeks, backtest_summary, phase, sched)


def finish_payload(season: int, rows: list[dict], P: dict, pre: dict, today: date, weeks: list, bt: dict | None, phase: str | None,
                   sched: pd.DataFrame) -> dict:
    rows.sort(key=lambda r: -r["ros"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    tv = tiers([r["ros"] for r in rows])
    for r, t in zip(rows, tv):
        r["tier"] = t
    rep = replacement(rows)
    for r in rows:
        r["vor"] = r["ros"] - rep.get(r["pos"], 0.0)
    sk = [r for r in rows if r["kind"] == "S"]
    gl = [r for r in rows if r["kind"] == "G"]
    zs = zscores([{"id": r["id"], "ros": r["ros"], **r["ros_c"]} for r in sk], list(CATS_S), TOP_TIER_POOL)
    zg = zscores([{"id": r["id"], "ros": r["ros"], **r["ros_c"]} for r in gl], list(CATS_G), 48)
    for r in rows:
        r["z"] = zs.get(r["id"]) if r["kind"] == "S" else zg.get(r["id"])
    # flags
    pre_rank = pre.get("ranks") or {}
    for r in rows:
        f = []
        pr = pre_rank.get(r["id"])
        r["pre_rank"] = pr
        if r["rank"] <= TOP_N and (pr is None or pr > TOP_N):
            f.append("add")
        if r["rank"] > TOP_N and pr is not None and pr <= TOP_N:
            f.append("drop")
        if r["kind"] == "S" and (r.get("gp") or 0) >= FLAG_GP and r.get("act_pg") is not None and r["rank"] <= FLAG_RANK:
            d = r["pts_pg"] - r["act_pg"]
            r["regress"] = d
            lg = r.get("luck_g") or 0.0
            pdo = (r.get("pdo") or [None])[0]
            if d >= FLAG_PTS and (lg <= -FLAG_GOALS or (pdo is not None and pdo <= 1 - FLAG_PDO)):
                f.append("buy")
            elif d <= -FLAG_PTS and (lg >= FLAG_GOALS or (pdo is not None and pdo >= 1 + FLAG_PDO)):
                f.append("sell")
        if r["kind"] == "G" and r.get("luck_gsax") is not None and (r.get("gp") or 0) >= 3 and r.get("share", 0) >= 0.3:
            if r["luck_gsax"] >= FLAG_GSAX:
                f.append("sell")
            elif r["luck_gsax"] <= -FLAG_GSAX:
                f.append("buy")
        if r["kind"] == "S" and r.get("age") is not None and r["age"] <= 24.5 and r.get("toi5") is not None and r["rank"] <= FLAG_RANK:
            up = r["toi5"] - (r.get("toi_prev") or 0.0)
            pp_up = (r.get("pp5") or 0.0) - (r.get("pp_prev") or 0.0)
            if (r.get("toi_prev") is None and r["toi5"] >= 15) or up >= 2.0 or pp_up >= 1.0:
                f.append("breakout")
                r["toi_up"] = up if r.get("toi_prev") is not None else None
                r["pp_up"] = pp_up if r.get("pp_prev") is not None else None
        r["flags"] = f
    picks = our_picks(rows, weeks)
    cols = ["id", "name", "team", "pos", "age", "kind", "rank", "tier", "pre_rank", "ros", "pts_pg", "vor", "z", "left", "inj_games", "gp",
            "toi", "toi_es", "toi_pp", "pp_unit", "share", "starts", "gaa", "svp", "flags", "inj"] + \
        [f"pg_{c}" for c in CATS_S + CATS_G] + [f"ros_{c}" for c in CATS_S + CATS_G] + ["w1", "w2", "w3", "w4", "act_pg", "regress", "luck",
                                                                                       "pdo", "toi5", "toi_prev", "pp5", "pp_prev"]
    out_rows = []
    for r in rows:
        inj = r.get("inj")
        wk = r.get("weeks") or []
        rec = [r["id"], r["name"], r["team"], r["pos"], _r(r.get("age"), 1), r["kind"], r["rank"], r["tier"], r.get("pre_rank"),
               _r(r["ros"], 1), _r(r["pts_pg"], 3), _r(r["vor"], 1), _r(r.get("z"), 2), r.get("left"), r.get("inj_games"), r.get("gp"),
               _r(r.get("toi"), 1), _r(r.get("toi_es"), 1), _r(r.get("toi_pp"), 2), r.get("pp_unit"), _r(r.get("share"), 3),
               _r(r.get("starts"), 1), _r(r.get("gaa"), 2), _r(r.get("svp"), 4), r.get("flags") or [],
               [inj.get("status"), inj.get("ret")] if inj else None]
        rec += [_r((r.get("pg") or {}).get(c), 3) for c in CATS_S + CATS_G]
        rec += [_r((r.get("ros_c") or {}).get(c), 1) for c in CATS_S + CATS_G]
        rec += [[w[0], _r(w[1], 2)] if r["kind"] == "S" else [w[0], _r(w[1], 2), _r(w[2], 2)] for w in wk[:4]] + [None] * (4 - len(wk[:4]))
        rec += [_r(r.get("act_pg"), 3), _r(r.get("regress"), 3), _r(r.get("luck_g") if r["kind"] == "S" else r.get("luck_gsax"), 2),
                [_r(x, 3) for x in r["pdo"]] if r.get("pdo") else None, _r(r.get("toi5"), 1), _r(r.get("toi_prev"), 1), _r(r.get("pp5"), 2),
                _r(r.get("pp_prev"), 2)]
        out_rows.append(rec)
    goalie_next = {r["id"]: r.get("next") for r in rows if r["kind"] == "G" and r.get("next")}
    teams = {}
    if len(sched):
        T = P["ts"].get("teams") or {}
        for team, g in sched.groupby("team"):
            ws = []
            for a, b in weeks:
                m = g[(g["date"] >= a) & (g["date"] <= b)]
                ws.append([int(len(m)), int(m["b2b"].sum()), _r(np.mean([(T.get(o) or {}).get("def_g", 1.0) for o in m["opp"]]) if len(m) else None, 3)])
            teams[team] = {"left": int(len(g)), "weeks": ws, "def_g": _r((T.get(team) or {}).get("def_g"), 3),
                           "off_g": _r((T.get(team) or {}).get("off_g"), 3)}
    return {"ok": True, "season": int(season), "updated_at": an.now(), "phase": phase, "version": VERSION, "asof": today.isoformat(),
            "points": DEFAULT_POINTS, "labels": LABELS, "cats": {"S": list(CATS_S), "G": list(CATS_G)}, "weeks": weeks,
            "roster": ROSTER, "n_teams": N_TEAMS, "replacement": {k: _r(v, 1) for k, v in rep.items()}, "top_n": TOP_N,
            "b2b_ratio": _r(P["b2b"], 3), "cols": cols, "rows": out_rows, "goalie_next": goalie_next, "teams": teams, "picks": picks,
            "backtest": bt,
            "constants": {"hl_toi": HL_TOI, "hl_rate": HL_RATE, "hl_goalie": HL_GOALIE, "hl_start": HL_START, "fin_prior": FIN_PRIOR,
                          "k_ixg": K_IXG, "k_ixg_pp": K_IXG_PP, "k_on": K_ON, "k_counts": K_CNT, "k_assist_share": K_ASH,
                          "goalie_prior_xg": G_PRIOR, "team_prior_games": TEAM_PRIOR, "decision": DECISION, "injury_games": INJ_GAMES},
            "note": "Our projections from our own data and models. No fantasy platform's ownership, ADP, rankings or prices are used "
                    "(their terms do not allow it): waiver targets are defined from our own projections."}


def our_picks(rows: list[dict], weeks: list) -> list[dict]:
    """A short list with one data-driven reason each."""
    out = []
    by = lambda f: [r for r in rows if f in (r.get("flags") or [])]
    adds = sorted(by("add"), key=lambda r: r["rank"])[:3]
    for r in adds:
        why = f"projects {r['pts_pg']:.2f} points a game, rank {r['rank']} now"
        if r.get("pre_rank"):
            why += f" (season start {r['pre_rank']})"
        if r["kind"] == "S" and r.get("toi5") is not None:
            why += f"; {r['toi5']:.1f} min a game over his last five"
            if r.get("pp_unit") == 1:
                why += ", on the first power-play unit"
        out.append({"kind": "Add", "id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "why": why})
    for r in sorted(by("buy"), key=lambda r: -(r.get("regress") or 0) if r["kind"] == "S" else (r.get("luck_gsax") or 0))[:2]:
        if r["kind"] == "S":
            why = (f"{r.get('g_s', 0):.0f} goals on {r.get('xg_s', 0):.1f} expected; projects {r['pts_pg']:.2f} points a game against "
                   f"{r.get('act_pg') or 0:.2f} so far")
        else:
            why = f"GSAx {r.get('gsax_s', 0):+.1f} this season, {r['luck_gsax']:+.1f} below his record; save talent should pull him back up"
        out.append({"kind": "Buy low", "id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "why": why})
    for r in sorted(by("sell"), key=lambda r: (r.get("regress") or 0) if r["kind"] == "S" else -(r.get("luck_gsax") or 0))[:2]:
        if r["kind"] == "S":
            why = (f"{r.get('g_s', 0):.0f} goals on {r.get('xg_s', 0):.1f} expected; projects {r['pts_pg']:.2f} points a game against "
                   f"{r.get('act_pg') or 0:.2f} so far")
        else:
            why = f"GSAx {r.get('gsax_s', 0):+.1f} this season, {r['luck_gsax']:+.1f} above his record"
        out.append({"kind": "Sell high", "id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "why": why})
    gl = [r for r in rows if r["kind"] == "G"]
    rank_g = {r["id"]: i + 1 for i, r in enumerate(sorted(gl, key=lambda r: -r["ros"]))}
    stream = sorted([r for r in gl if rank_g[r["id"]] > 24 and r.get("weeks")], key=lambda r: -(r["weeks"][0][2] if r["weeks"] else 0))[:2]
    for r in stream:
        w = r["weeks"][0]
        why = f"{w[1]:.1f} projected starts this week ({w[0]} club games), {w[2]:.1f} points"
        out.append({"kind": "Stream", "id": r["id"], "name": r["name"], "team": r["team"], "pos": "G", "why": why})
    for r in sorted(by("breakout"), key=lambda r: r["rank"])[:2]:
        parts = [f"age {r['age']:.0f}"]
        if r.get("toi_up") is not None and r["toi_up"] >= 2.0:
            parts.append(f"{r['toi5']:.1f} min a game over his last five, up {r['toi_up']:.1f} on last season")
        elif r.get("toi_prev") is None:
            parts.append(f"{r['toi5']:.1f} min a game over his last five in his first full NHL run")
        if r.get("pp_up") is not None and r["pp_up"] >= 1.0:
            parts.append(f"{r['pp5']:.1f} PP minutes a game, up {r['pp_up']:.1f}")
        parts.append(f"projects {r['pts_pg']:.2f} points a game (rank {r['rank']})")
        out.append({"kind": "Breakout", "id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "why": "; ".join(parts)})
    return out


def preseason_ranks(logs: dict, season: int, store: dict) -> dict:
    """Ranks from our projection as of the season's first game (history = earlier seasons only), cached once a season
    on the earlier seasons' logs."""
    sk = logs.get("sk")
    if sk is None or not len(sk):
        return {}
    cur = sk[(sk["season"] == season) & (sk["gt"] == "R")]
    games = (store or {}).get("games") or {}
    first = min([str(g.get("date") or "")[:10] for g in (games.values() if isinstance(games, dict) else games)
                 if str(g.get("game_id") or "")[4:6] == "02"] or [cur["date"].min() if len(cur) else "9999"])
    prev = sk[(sk["season"] < season)]
    key = hashlib.sha1(json.dumps([VERSION, DEFAULT_POINTS, season, first, len(prev), float(prev["toi"].sum()) if len(prev) else 0]).encode()).hexdigest()[:16]
    p = an.an_cache() / "fantasy" / f"preseason_{season}.json"
    c = an.read_json(p) if p.exists() else None
    if isinstance(c, dict) and c.get("key") == key:
        return c["ranks"]
    P = project_at(logs, first, season)
    sr, gr = P["sr"], P["gr"]
    n = 84 if an.start_year(season) >= 2026 else 82
    vals = []
    players = {an.sid(k): v for k, v in ((store or {}).get("players") or {}).items() if isinstance(v, dict)}
    for pid, pl in players.items():
        ip = int(pid)
        if str(pl.get("pos") or "").upper().startswith("G"):
            if len(gr) and ip in gr.index:
                g = gr.loc[ip]
                T = (P["ts"].get("teams") or {}).get(pl.get("team")) or {}
                gg = goalie_game(g, T, {}, 0.5, P["conv_g"])
                vals.append((pid, float(points(gg)) * float(g["share"]) * n))
        elif len(sr) and ip in sr.index:
            c = {k: float(v[0]) for k, v in skater_cats(sr.loc[[ip]]).items()}
            vals.append((pid, float(points(c)) * n))
    vals.sort(key=lambda x: -x[1])
    ranks = {"ranks": {pid: i + 1 for i, (pid, _) in enumerate(vals)}, "asof": first}
    try:
        an.write_json(p, {"key": key, "ranks": ranks})
    except OSError:
        pass
    return ranks


# ---------------------------------------------------------------------------------------------- backtest

def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def wmae(pred: np.ndarray, act: np.ndarray, w: np.ndarray) -> float | None:
    w = np.asarray(w, float)
    if w.sum() <= 0:
        return None
    return float(np.sum(w * np.abs(np.asarray(pred, float) - np.asarray(act, float))) / w.sum())


def _sk_points(df: pd.DataFrame) -> pd.Series:
    return (DEFAULT_POINTS["g"] * df["g"] + DEFAULT_POINTS["a"] * df["a"] + DEFAULT_POINTS["pm"] * df["pm"] + DEFAULT_POINTS["ppp"] * df["ppp"]
            + DEFAULT_POINTS["sog"] * df["sog"] + DEFAULT_POINTS["hit"] * df["hits"] + DEFAULT_POINTS["blk"] * df["blk"])


def _gk_points(df: pd.DataFrame) -> pd.Series:
    w = (df["dec"] == "W").astype(float)
    so = ((df["ga"] == 0) & (df["toi"] >= 59.0) & (df["start"] == 1)).astype(float)
    return DEFAULT_POINTS["w"] * w + DEFAULT_POINTS["ga"] * df["ga"] + DEFAULT_POINTS["sv"] * df["sv"] + DEFAULT_POINTS["so"] * so


SK_ACT = {"pts": None, "g": "g", "a": "a", "pm": "pm", "ppp": "ppp", "sog": "sog", "hit": "hits", "blk": "blk"}


def _checkpoint(logs: dict, season: int, c: str, end: str) -> dict:
    """Projections at checkpoint c and the actuals over the next week and the rest of the season, for our model and the
    two baselines (skaters per game played; goalies per club game)."""
    P = project_at(logs, c, season)
    sr, gr, ts = P["sr"], P["gr"], P["ts"]
    sk, gk, tg = logs["sk"], logs["gk"], logs["tg"]
    week_end = (date.fromisoformat(c) + timedelta(days=7)).isoformat()
    res = {}
    skR = sk[(sk["season"] == season) & (sk["gt"] == "R")]
    skP = sk[(sk["season"] == an.prev_season(season)) & (sk["gt"] == "R")]
    before = skR[skR["date"] < c]
    gkR = gk[(gk["season"] == season) & (gk["gt"] == "R")]
    gkP = gk[(gk["season"] == an.prev_season(season)) & (gk["gt"] == "R")]
    tgR = tg[(tg["season"] == season) & (tg["gt"] == "R")]
    tgP = tg[(tg["season"] == an.prev_season(season)) & (tg["gt"] == "R")]
    for hz, hi in (("week", week_end), ("ros", end)):
        win = skR[(skR["date"] >= c) & (skR["date"] < hi)].copy()
        if not len(win):
            continue
        win["pts"] = _sk_points(win)
        agg = win.groupby("pid").agg(n=("game_id", "size"), team=("team", "last"), pos=("pos", "last"),
                                     **{k: (v if v else "pts", "sum") for k, v in SK_ACT.items()})
        # our model: per game against the window's actual opponents
        opp = win.groupby("pid")["opp"].agg(list)
        ids = [p for p in agg.index if p in sr.index]
        pred = {k: np.full(len(agg), np.nan) for k in SK_ACT}
        pos_ix = {p: i for i, p in enumerate(agg.index)}
        if ids:
            R = sr.loc[ids]
            T = ts.get("teams") or {}
            dg = np.array([np.mean([(T.get(o) or {}).get("def_g", 1.0) for o in opp[p]]) for p in ids])
            ds = np.array([np.mean([(T.get(o) or {}).get("def_s", 1.0) for o in opp[p]]) for p in ids])
            og = np.array([np.mean([(T.get(o) or {}).get("off_g", 1.0) for o in opp[p]]) for p in ids])
            cats = skater_cats(R, dg, ds, og)
            ii = [pos_ix[p] for p in ids]
            for k, v in SK_ACT.items():
                pred[k][ii] = points(cats) if k == "pts" else cats[k]
        # position-group means (fallback)
        grp = agg["pos"].map(lambda p: "D" if p == "D" else "F")
        hist = pd.concat([skP, before])
        hist = hist.assign(pts=_sk_points(hist), grp=hist["pos"].map(lambda p: "D" if p == "D" else "F"))
        gmean = {k: hist.groupby("grp")[(v if v else "pts")].mean() for k, v in SK_ACT.items()}
        for k in SK_ACT:
            m = np.isnan(pred[k])
            pred[k][m] = grp[m].map(lambda g: float(gmean[k].get(g, 0.0))).to_numpy()
        # baselines
        b4 = before.assign(pts=_sk_points(before))
        std = b4.groupby("pid").agg(n=("game_id", "size"), **{k: (v if v else "pts", "mean") for k, v in SK_ACT.items()})
        p4 = skP.assign(pts=_sk_points(skP))
        lst = p4.groupby("pid").agg(n=("game_id", "size"), **{k: (v if v else "pts", "mean") for k, v in SK_ACT.items()})
        out = {}
        for k in SK_ACT:
            a_std = std[k].reindex(agg.index)
            n_std = std["n"].reindex(agg.index).fillna(0)
            a_lst = lst[k].reindex(agg.index)
            n_lst = lst["n"].reindex(agg.index).fillna(0)
            fallback = grp.map(lambda g: float(gmean[k].get(g, 0.0)))
            b1 = a_std.where(n_std >= 3, a_lst.where(n_lst >= 10, a_std)).fillna(fallback).to_numpy()
            b2 = a_lst.where(n_lst >= 10, a_std).fillna(fallback).to_numpy()
            act = (agg[k] / agg["n"]).to_numpy()
            w = agg["n"].to_numpy(float)
            mn = 2 if hz == "week" else 10
            sel = w >= mn
            out[k] = {"model": [wmae(pred[k], act, w), spearman(pred[k][sel], act[sel])],
                      "std": [wmae(b1, act, w), spearman(b1[sel], act[sel])],
                      "last": [wmae(b2, act, w), spearman(b2[sel], act[sel])], "n": int(w.sum()), "players": int(len(w))}
        res[("S", hz)] = out
        # goalies, per club game: our model v the goalie's points per club game so far / last season
        gw = gkR[(gkR["date"] >= c) & (gkR["date"] < hi)].copy()
        twin = tgR[(tgR["date"] >= c) & (tgR["date"] < hi)]
        if not len(twin):
            continue
        active = gkR[(gkR["date"] < c) & (gkR["date"] >= (date.fromisoformat(c) - timedelta(days=21)).isoformat())]
        last_team = active.sort_values("date").groupby("pid")["team"].last()
        if not len(last_team):
            continue
        gw["pts"] = _gk_points(gw)
        T = ts.get("teams") or {}
        club_goalies: dict[str, list] = {}
        for pid, team in last_team.items():
            sh = float(gr.at[pid, "share"]) if pid in gr.index and gr.at[pid, "team"] == team else 0.0
            club_goalies.setdefault(team, []).append((int(pid), max(sh, 0.02)))
        tws = twin.sort_values("date")
        prev_dates = tgR[tgR["date"] < c].groupby("team")["date"].max()
        rows_g = []
        b4g = gkR[gkR["date"] < c].assign(pts=lambda x: _gk_points(x))
        club_gp_now = tgR[tgR["date"] < c].groupby("team").size()
        lst_g = gkP.assign(pts=lambda x: _gk_points(x)).groupby("pid")["pts"].sum()
        club_gp_last = tgP.groupby("team").size()
        lst_team = gkP.groupby("pid")["team"].agg(lambda s: s.value_counts().index[0])
        for pid, team in last_team.items():
            tgames = tws[tws["team"] == team]
            if not len(tgames):
                continue
            pred_p = 0.0
            last_d = prev_dates.get(team)
            for row in tgames.itertuples():
                b2b = last_d is not None and (date.fromisoformat(row.date) - date.fromisoformat(last_d)).days == 1
                last_d = row.date
                ps = start_probs(club_goalies.get(team, []), b2b, P["b2b"]).get(int(pid), 0.0)
                pw = row.p_win if row.p_win is not None and not np.isnan(row.p_win) else 0.5
                gg = goalie_game(gr.loc[pid] if pid in gr.index else {"talent": 0.0}, T.get(team) or {}, T.get(row.opp) or {}, float(pw), P["conv_g"])
                pred_p += ps * points(gg)
            n = len(tgames)
            act = float(gw[(gw["pid"] == pid)]["pts"].sum()) / n
            s_now = float(b4g[b4g["pid"] == pid]["pts"].sum()) / max(int(club_gp_now.get(team, 0)), 1)
            l_t = lst_team.get(pid)
            s_last = float(lst_g.get(pid, np.nan)) / max(int(club_gp_last.get(l_t, 82)), 1) if l_t is not None else np.nan
            b1 = s_now if club_gp_now.get(team, 0) >= 3 else (s_last if np.isfinite(s_last) else s_now)
            b2 = s_last if np.isfinite(s_last) else s_now
            rows_g.append((pred_p / n, b1, b2, act, n))
        if rows_g:
            A = np.array(rows_g, float)
            mn = 2 if hz == "week" else 10
            sel = A[:, 4] >= mn
            res[("G", hz)] = {"pts": {"model": [wmae(A[:, 0], A[:, 3], A[:, 4]), spearman(A[sel, 0], A[sel, 3])],
                                      "std": [wmae(A[:, 1], A[:, 3], A[:, 4]), spearman(A[sel, 1], A[sel, 3])],
                                      "last": [wmae(A[:, 2], A[:, 3], A[:, 4]), spearman(A[sel, 2], A[sel, 3])],
                                      "n": int(A[:, 4].sum()), "players": int(len(A))}}
    return res


def backtest(logs: dict, seasons: list[int], step_days: int = 7) -> dict:
    """Walk-forward over `seasons` (completed) at weekly checkpoints: MAE (games-weighted) and mean Spearman across
    checkpoints, by horizon, for our projection and the two baselines; also by season and by month of the season."""
    t0 = time.perf_counter()
    acc: dict[tuple, dict] = {}
    per_season: dict[int, dict] = {}
    n_cp = 0
    for s in seasons:
        tg = logs["tg"]
        reg = tg[(tg["season"] == s) & (tg["gt"] == "R")]
        if not len(reg):
            continue
        first, last = reg["date"].min(), reg["date"].max()
        end = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        c = date.fromisoformat(first) + timedelta(days=14)
        stop = date.fromisoformat(last) - timedelta(days=6)
        while c <= stop:
            r = _checkpoint(logs, s, c.isoformat(), end)
            n_cp += 1
            for (kind, hz), cats in r.items():
                for cat, v in cats.items():
                    for who in ("model", "std", "last"):
                        a = acc.setdefault((kind, hz, cat, who), {"mae_n": 0.0, "mae_w": 0.0, "rho": [], "n": 0})
                        mae, rho = v[who]
                        if mae is not None:
                            a["mae_n"] += mae * v["n"]
                            a["mae_w"] += v["n"]
                        if rho is not None and np.isfinite(rho):
                            a["rho"].append(rho)
                        a["n"] += v["n"] if who == "model" else 0
                        if cat == "pts":
                            ps = per_season.setdefault(s, {}).setdefault((kind, hz, who), {"mae_n": 0.0, "mae_w": 0.0, "rho": []})
                            if mae is not None:
                                ps["mae_n"] += mae * v["n"]
                                ps["mae_w"] += v["n"]
                            if rho is not None and np.isfinite(rho):
                                ps["rho"].append(rho)
            c += timedelta(days=step_days)
    table = []
    for (kind, hz, cat, who), a in sorted(acc.items()):
        table.append([kind, hz, cat, who, _r(a["mae_n"] / a["mae_w"], 4) if a["mae_w"] else None,
                      _r(float(np.mean(a["rho"])), 3) if a["rho"] else None, a["n"]])
    by_season = []
    for s, d in sorted(per_season.items()):
        for (kind, hz, who), a in sorted(d.items()):
            by_season.append([s, kind, hz, who, _r(a["mae_n"] / a["mae_w"], 4) if a["mae_w"] else None,
                              _r(float(np.mean(a["rho"])), 3) if a["rho"] else None])
    return {"ok": True, "version": VERSION, "updated_at": an.now(), "seasons": seasons, "checkpoints": n_cp, "step_days": step_days,
            "cols": ["kind", "horizon", "cat", "who", "mae", "spearman", "games"], "rows": table,
            "season_cols": ["season", "kind", "horizon", "who", "mae", "spearman"], "by_season": by_season,
            "baselines": {"std": "season-to-date average per game (fewer than 3 games: last season's, 10+ games; else the position mean)",
                          "last": "last season's average per game (fewer than 10 games: season to date; else the position mean)"},
            "units": {"S": "per game played", "G": "per club game"}, "points": DEFAULT_POINTS,
            "seconds": round(time.perf_counter() - t0, 1)}


def backtest_cached(seasons: list[int], current: int | None = None, compute: bool = True) -> dict | None:
    """The backtest, cached on the completed seasons' logs (never recomputed while they are unchanged). compute=False
    (the hourly build) only reads the cache: a stale result is returned flagged "stale", none is computed."""
    from oddsmarkets.nhl.analytics import gamelog as GL
    need = sorted({an.season_id(an.start_year(s) - k) for s in seasons for k in range(3)})
    keys = []
    for s in need:
        kp = an.an_cache() / "gamelog" / f"log_{s}.key"
        keys.append([s, kp.read_text(encoding="utf-8").strip() if kp.exists() else None])
    key = hashlib.sha1(json.dumps([VERSION, DEFAULT_POINTS, seasons, keys]).encode()).hexdigest()[:16]
    p = an.an_cache() / "fantasy" / "backtest.json"
    c = an.read_json(p) if p.exists() else None
    if isinstance(c, dict) and c.get("key") == key:
        return c["result"]
    if not compute:
        if isinstance(c, dict) and c.get("result"):
            return {**c["result"], "stale": True}
        return None
    logs = GL.logs(need, current=current)
    res = backtest(logs, seasons)
    # keys after the logs were (re)built
    keys = []
    for s in need:
        kp = an.an_cache() / "gamelog" / f"log_{s}.key"
        keys.append([s, kp.read_text(encoding="utf-8").strip() if kp.exists() else None])
    key = hashlib.sha1(json.dumps([VERSION, DEFAULT_POINTS, seasons, keys]).encode()).hexdigest()[:16]
    try:
        an.write_json(p, {"key": key, "result": res})
    except OSError:
        pass
    return res


def backtest_summary(bt: dict | None) -> dict | None:
    """The headline numbers the page's card shows (points, both horizons, skaters and goalies)."""
    if not bt or not bt.get("ok"):
        return None
    out = {}
    for kind, hz, cat, who, mae, rho, n in bt["rows"]:
        if cat != "pts":
            continue
        out.setdefault(f"{kind}_{hz}", {})[who] = [mae, rho]
    return {"seasons": bt["seasons"], "checkpoints": bt["checkpoints"], "pts": out}
