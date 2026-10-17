"""
Run and win expectancy: RE24, linear weights, wOBA weights, count values, win expectancy, WPA and
leverage, per season. Statcast seasons from the pitch table, 1908 onward from Retrosheet PAs (no event files
before 1908).

Run expectancy
--------------
A plate appearance (PA) starts in base-out state s = (outs o in 0..2, bases b as a bitmask
1 = first, 2 = second, 4 = third). For every PA in a *complete* half-inning

    R_to_end = (half-inning final batting score) - (batting score at the PA's first pitch)

and RE(o, b) = mean R_to_end over those PAs. A half-inning is complete unless it is a bottom half
of the ninth or later (walk-offs end those early) or the last half-inning of a game that is not a
top half of the ninth or later (rain-shortened or suspended games). This is the standard
(Tango) convention. The empirical distribution P(R_to_end = k | o, b), estimated separately for
top and bottom halves (home and away batting), drives the win-expectancy model.

PA run value (RE24): RV = RE(end) - RE(start) + runs scored during the PA, where end = the next PA's
start state in the same half-inning, or three outs (RE = 0) when the half-inning ends.

Linear weights and wOBA
-----------------------
lw_c = mean RV over PAs ending in class c (BB, IBB, HBP, 1B, 2B, 3B, HR, ROE, K, OUT);
lw_out = mean RV over all outs (K and outs in play). wOBA weights are lw_c - lw_out scaled by
s = lgOBP / (sum_c (lw_c - lw_out) n_c / wOBA denominator) so league wOBA equals league OBP
(FanGraphs' convention). Runs per win RPW = 9 * (runs per inning) * 1.5 + 3 (FanGraphs' formula).

Count values
------------
RV(b-s) = mean final PA run value over PAs that passed through count b-s; the value of a called
strike at a count is RV(next count after a strike) - RV(next count after a ball), with RV(strikeout)
and RV(walk) for the terminal transitions. Framing and umpire scorecards use these.

Win expectancy (Markov model)
-----------------------------
WE(inning i, half h, outs o, bases b, home lead d) = P(home wins). Inside a half-inning the rest of
it scores k runs with P_h(k | o, b) (top: the away team's distribution, bottom: the home team's);
between half-innings the game moves on deterministically:

    after top of i with lead d':    i >= 9 and d' > 0  -> 1 (home wins without batting)
                                    else                -> bottom of i at (0 outs, empty), lead d'
    after bottom of i with lead d': i >= 9: d' > 0 -> 1, d' < 0 -> 0, tied -> top of i+1
                                    i < 9:  -> top of i+1
    in the bottom of the ninth or later any run that puts the home team ahead ends the game, which
    the formula handles exactly (all k with d + k > 0 map to 1).

Extra innings start each half at (0 outs, runner on second) from 2020 in the regular season (the
automatic runner; postseason games start empty). Every extra inning is then identical, so the
value X of a tied extra inning solves X = sum_k P_top(k) [S_bot(>k) + P_bot(k) X], in closed form.
Leads are clipped to +/- D_MAX = 30. The model's calibration against actual results is reported
(`we_calibration`).

Leverage index: LI(state) = sum over one-PA transitions (o, b) -> (o', b', runs) with empirical
probabilities of |WE(next) - WE(now)|, divided by the mean of that quantity over all PAs of the
season (so the average PA has LI = 1). WPA of a PA is WE after minus WE before for the batting
team (the pitcher gets the negative).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "re24-1"
K_MAX = 14                 # runs-to-end distribution support 0..K_MAX (the tail is folded into K_MAX)
D_MAX = 30                 # home lead clipped to +/- D_MAX inside the DP
INNING_TABLE = 10          # WE tables published for innings 1..9 and "10+"
D_TABLE = 15               # published lead range +/- D_TABLE
AUTO_RUNNER_FROM = 2020
PRIOR_STATE_PAS = 50       # pseudo-PAs pulling sparse top/bottom run distributions toward the pooled one
CLASSES = ["BB", "IBB", "HBP", "1B", "2B", "3B", "HR", "ROE", "K", "OUT"]
RPW_FORMULA = "9 * runs_per_inning * 1.5 + 3"


# ============================================================================ PA tables

def _complete_halves(pa: pd.DataFrame) -> pd.Series:
    """bool per hkey: the half-inning counts for run expectancy."""
    h = pa.groupby("hkey", sort=False).agg(game=("game_pk", "first"), inning=("inning", "first"), half=("half", "first"))
    order = h.reset_index().sort_values(["game", "inning", "half"])
    last = order.groupby("game")["hkey"].transform("last") == order["hkey"]
    late_bot = (order["half"] == 1) & (order["inning"] >= 9)
    late_top = (order["half"] == 0) & (order["inning"] >= 9)
    ok = ~late_bot & (~last | late_top)
    return pd.Series(ok.to_numpy(), index=order["hkey"].to_numpy())


def prepare_pa(pa: pd.DataFrame) -> pd.DataFrame:
    """Add runs_pa, runs_to_end, complete, end_outs, end_bases, last_in_half to a PA table
    (from `_c.pa_table` or `retro_pa`). Rows must be in game order."""
    pa = pa.copy()
    if "runs_pa" not in pa:
        pa["runs_pa"] = (pa["post_bat_score"].astype(float) - pa["bat_score"].astype(float)).fillna(0.0)
    g = pa.groupby("hkey", sort=False)
    if "runs_to_end" not in pa:
        if "bat_score" in pa and pa["bat_score"].notna().all():
            final = g["post_bat_score"].transform("max").astype(float)
            pa["runs_to_end"] = final - pa["bat_score"].astype(float)
        else:
            pa["runs_to_end"] = g["runs_pa"].transform(lambda s: s[::-1].cumsum()[::-1])
    comp = _complete_halves(pa)
    pa["complete"] = pa["hkey"].map(comp).fillna(False).astype(bool)
    nxt_h = pa["hkey"].shift(-1)
    pa["last_in_half"] = (nxt_h != pa["hkey"]).to_numpy()
    if "outs_post" in pa and pa["outs_post"].notna().any():
        pa["end_outs"] = pa["outs_post"].fillna(3).clip(upper=3).astype(int)
        pa["end_bases"] = pa["bases_post"].fillna(0).astype(int)
    else:
        pa["end_outs"] = np.where(pa["last_in_half"], 3, pa["outs_when_up"].shift(-1).fillna(3)).astype(int)
        pa["end_bases"] = np.where(pa["last_in_half"], 0, pa["bases"].shift(-1).fillna(0)).astype(int)
    pa["outs_when_up"] = pa["outs_when_up"].astype(int).clip(0, 2)
    pa["bases"] = pa["bases"].astype(int)
    return pa


RETRO_NUM = {2: "OUT", 3: "K", 14: "BB", 15: "IBB", 16: "HBP", 17: "CI", 18: "ROE", 19: "OUT", 20: "1B", 21: "2B",
             22: "3B", 23: "HR"}
RETRO_STR = {"single": "1B", "s": "1B", "1b": "1B", "double": "2B", "d": "2B", "2b": "2B", "triple": "3B", "t": "3B",
             "3b": "3B", "home_run": "HR", "hr": "HR", "h": "HR", "homerun": "HR", "walk": "BB", "bb": "BB", "w": "BB",
             "intent_walk": "IBB", "ibb": "IBB", "iw": "IBB", "intentional_walk": "IBB", "hit_by_pitch": "HBP",
             "hbp": "HBP", "hp": "HBP", "strikeout": "K", "k": "K", "so": "K", "error": "ROE", "e": "ROE", "roe": "ROE",
             "field_error": "ROE", "interference": "CI", "ci": "CI", "int": "CI", "catcher_interf": "CI", "c": "CI", "out": "OUT",
             "generic_out": "OUT", "fielders_choice": "OUT", "fc": "OUT", "field_out": "OUT", "sac_fly": "OUT",
             "sac_bunt": "OUT", "sf": "OUT", "sh": "OUT", "gdp": "OUT", "double_play": "OUT"}


def retro_class(event_cd: pd.Series) -> np.ndarray:
    out = []
    for v in event_cd.tolist():
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append("")
            continue
        try:
            out.append(RETRO_NUM.get(int(v), ""))
            continue
        except (TypeError, ValueError):
            pass
        out.append(RETRO_STR.get(str(v).strip().lower(), "OUT" if "out" in str(v).lower() else ""))
    return np.array(out, dtype=object)


def retro_pa(df: pd.DataFrame, gtypes: tuple[str, ...] | None = ("R",)) -> pd.DataFrame:
    """Builder A's Retrosheet event table (every PA and running event, game order by seq) as the PA table
    `prepare_pa` expects: one row per plate appearance with runs_to_end counted over *all* events of the
    half-inning (so runs on steals, wild pitches and balks count), the PA's own post state and runs, and
    the scores before the PA."""
    if df is None or not len(df):
        return pd.DataFrame()
    d = df.copy()
    for c in d.columns:
        if isinstance(d[c].dtype, pd.CategoricalDtype):
            d[c] = d[c].astype(object)
    if gtypes is not None and "gtype" in d:
        d = d[d["gtype"].astype(str).isin(gtypes)]
    sort = [c for c in ("game_id", "seq") if c in d]
    d = d.sort_values(sort, kind="mergesort") if sort else d
    d["half"] = pd.to_numeric(d["half"], errors="coerce").fillna(0).astype(int)
    gcode = pd.factorize(d["game_id"].astype(str))[0].astype(np.int64)
    d["game_pk"] = gcode
    d["hkey"] = gcode * 100 + d["inning"].astype(int) * 2 + d["half"]
    runs = d["runs_on_play"].fillna(0).astype(float)
    d["runs_to_end"] = runs[::-1].groupby(d["hkey"][::-1]).cumsum()[::-1]
    home_bat = d["half"] == 1
    hs = d["home_score_pre"].astype(float) if "home_score_pre" in d else pd.Series(np.nan, index=d.index)
    as_ = d["away_score_pre"].astype(float) if "away_score_pre" in d else pd.Series(np.nan, index=d.index)
    d["bat_score"] = np.where(home_bat, hs, as_)
    d["fld_score"] = np.where(home_bat, as_, hs)
    g = d.groupby("game_pk", sort=False)
    d["home_final"] = (hs + np.where(home_bat, runs, 0)).groupby(d["game_pk"]).transform("max")
    d["away_final"] = (as_ + np.where(home_bat, 0, runs)).groupby(d["game_pk"]).transform("max")
    pa = d[d["pa"].astype(bool)].copy() if "pa" in d else d
    pa["outs_when_up"] = pa["outs_pre"].astype(int)
    pa["bases"] = pa["bases_pre"].fillna(0).astype(int)
    pa["runs_pa"] = pa["runs_on_play"].fillna(0).astype(float)
    pa["post_bat_score"] = pa["bat_score"] + pa["runs_pa"]
    pa["cls"] = retro_class(pa["event_cd"])
    if "sf" in pa:
        pa["events"] = np.where(pa["sf"].astype(bool), "sac_fly", np.where(pa.get("sh", False).astype(bool), "sac_bunt", ""))
    pa["inning_topbot"] = np.where(pa["half"] == 0, "Top", "Bot")
    return pa.reset_index(drop=True)


def retro_running(df: pd.DataFrame) -> pd.DataFrame:
    """Stolen-base and caught-stealing events per runner from the Retrosheet event table:
    columns season, runner (retro id), kind ('sb'|'cs'), base (target base 2, 3 or 4)."""
    if df is None or not len(df) or "event_tx" not in df:
        return pd.DataFrame(columns=["runner", "kind", "base"])
    tx = df["event_tx"].astype(str)
    rows = []
    for col_pre, base in (("run1_pre", 2), ("run2_pre", 3), ("run3_pre", 4)):
        tag = {2: "2", 3: "3", 4: "H"}[base]
        sb = tx.str.contains(rf"(?:^|[;+])SB{tag}", regex=True)
        cs = tx.str.contains(rf"(?:^|[;+])(?:PO)?CS{tag}(?!\([^)]*E)", regex=True)
        for kind, m in (("sb", sb), ("cs", cs)):
            sub = df.loc[m & df[col_pre].notna(), col_pre].astype(str)
            rows.append(pd.DataFrame({"runner": sub.to_numpy(), "kind": kind, "base": base}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["runner", "kind", "base"])


# ============================================================================ run expectancy

def re_matrix(pa: pd.DataFrame) -> dict:
    """RE(o, b) (3 x 8), counts, and the run distributions (pooled, top, bottom; 3 x 8 x K_MAX+1)."""
    c = pa[pa["complete"]]
    o = c["outs_when_up"].to_numpy(int); b = c["bases"].to_numpy(int)
    r = np.clip(c["runs_to_end"].to_numpy(float), 0, None)
    rk = np.clip(np.round(r).astype(int), 0, K_MAX)
    half = c["half"].to_numpy(int)
    re = np.zeros((3, 8)); n = np.zeros((3, 8), int)
    dist = np.zeros((3, 3, 8, K_MAX + 1))      # [pooled, top, bottom]
    np.add.at(n, (o, b), 1)
    sums = np.zeros((3, 8)); np.add.at(sums, (o, b), r)
    re = np.where(n > 0, sums / np.maximum(n, 1), np.nan)
    np.add.at(dist[0], (o, b, rk), 1)
    np.add.at(dist[1], (o[half == 0], b[half == 0], rk[half == 0]), 1)
    np.add.at(dist[2], (o[half == 1], b[half == 1], rk[half == 1]), 1)
    # empty cells: fall back to a geometric-ish default anchored on the overall start distribution
    pooled = dist[0].sum(axis=(0, 1)) + 1e-9
    for oo in range(3):
        for bb in range(8):
            if dist[0, oo, bb].sum() == 0:
                dist[0, oo, bb] = pooled
    probs = dist[0] / dist[0].sum(axis=2, keepdims=True)
    side = []
    for k in (1, 2):
        cnt = dist[k]
        tot = cnt.sum(axis=2, keepdims=True)
        side.append((cnt + PRIOR_STATE_PAS * probs) / (tot + PRIOR_STATE_PAS))
    re = np.where(np.isnan(re), (probs * np.arange(K_MAX + 1)).sum(axis=2), re)
    return {"re": re, "n": n, "dist": probs, "dist_top": side[0], "dist_bot": side[1],
            "runs_per_inning": float(re[0, 0])}


def re_lookup(re: np.ndarray, outs, bases) -> np.ndarray:
    o = np.asarray(outs, int); b = np.asarray(bases, int)
    val = np.zeros(len(o))
    ok = o < 3
    val[ok] = re[np.clip(o[ok], 0, 2), np.clip(b[ok], 0, 7)]
    return val


def pa_values(pa: pd.DataFrame, re: np.ndarray) -> pd.DataFrame:
    pa = pa.copy()
    pa["re_start"] = re_lookup(re, pa["outs_when_up"], pa["bases"])
    pa["re_end"] = re_lookup(re, pa["end_outs"], pa["end_bases"])
    pa["re24"] = pa["re_end"] - pa["re_start"] + pa["runs_pa"]
    return pa


def linear_weights(pa: pd.DataFrame, re_info: dict | None = None) -> dict:
    """Linear weights per class, wOBA weights/scale, league rates and runs per win from a valued PA table."""
    v = pa[pa["cls"].isin(CLASSES)]
    lw = v.groupby("cls")["re24"].mean().to_dict()
    n = v["cls"].value_counts().to_dict()
    outs = v[v["cls"].isin(["K", "OUT"])]
    lw_out = float(outs["re24"].mean()) if len(outs) else -0.27
    rel = {k: float(lw.get(k, 0.0) - lw_out) for k in CLASSES}
    for k in ("K", "OUT"):
        rel[k] = 0.0
    # wOBA denominator: AB + uBB + SF + HBP = PA - IBB - SH - CI
    ev = v["events"].astype(str) if "events" in v else pd.Series("", index=v.index)
    sh = int(ev.isin(["sac_bunt", "sac_bunt_double_play"]).sum())
    sf = int(ev.isin(["sac_fly", "sac_fly_double_play"]).sum())
    pa_n = len(v)
    denom = pa_n - n.get("IBB", 0) - sh
    hits = sum(n.get(k, 0) for k in ("1B", "2B", "3B", "HR"))
    on = hits + n.get("BB", 0) + n.get("IBB", 0) + n.get("HBP", 0)
    obp = on / max(pa_n - sh, 1)
    raw = sum(rel[k] * n.get(k, 0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR", "ROE")) / max(denom, 1)
    scale = obp / raw if raw > 0 else 1.2
    w = {k: rel[k] * scale for k in ("BB", "HBP", "1B", "2B", "3B", "HR", "ROE")}
    runs = float(pa["runs_pa"].sum())
    halves = pa["hkey"].nunique()
    rpi = runs / max(halves, 1)
    rpo = runs / max(float(v["cls"].map(lambda c: 1 if c in ("K", "OUT") else 0).sum()) + 0.0, 1.0)
    out = {"lw": {k: float(lw.get(k, float("nan"))) for k in CLASSES}, "lw_out": lw_out, "lw_rel": rel,
           "woba_w": w, "woba_scale": float(scale), "lg_woba": float(obp), "lg_obp": float(obp),
           "runs_per_pa": runs / max(pa_n, 1), "runs_per_inning": rpi, "runs_per_out": rpo,
           "rpw": 9 * rpi * 1.5 + 3, "n": {k: int(n.get(k, 0)) for k in CLASSES}, "pa": pa_n, "sf": sf, "sh": sh}
    return out


def woba_from_counts(counts: dict, w: dict) -> float:
    """wOBA from class counts with weights `w` (denominator PA - IBB - SH supplied as counts['den'])."""
    num = sum(w.get(k, 0.0) * counts.get(k, 0) for k in ("BB", "HBP", "1B", "2B", "3B", "HR"))
    return num / max(counts.get("den", 0), 1)


def count_values(pitches: pd.DataFrame, pa: pd.DataFrame) -> dict:
    """Run value by count and the value of a strike over a ball at each count (see module doc)."""
    key = pa.set_index(["game_pk", "at_bat_number"])["re24"]
    p = pitches[["game_pk", "at_bat_number", "balls", "strikes"]].copy()
    p["rv"] = key.reindex(pd.MultiIndex.from_frame(p[["game_pk", "at_bat_number"]])).to_numpy()
    p = p[p["rv"].notna() & p["balls"].between(0, 3) & p["strikes"].between(0, 2)]
    p = p.drop_duplicates(["game_pk", "at_bat_number", "balls", "strikes"])
    rv = p.groupby(["balls", "strikes"])["rv"].mean()
    k_val = float(pa.loc[pa["cls"] == "K", "re24"].mean()) if (pa["cls"] == "K").any() else -0.28
    bb_val = float(pa.loc[pa["cls"] == "BB", "re24"].mean()) if (pa["cls"] == "BB").any() else 0.32
    table, sv = {}, {}
    for b in range(4):
        for s in range(3):
            table[f"{b}-{s}"] = float(rv.get((b, s), np.nan))
    for b in range(4):
        for s in range(3):
            after_s = k_val if s == 2 else table[f"{b}-{s + 1}"]
            after_b = bb_val if b == 3 else table[f"{b + 1}-{s}"]
            sv[f"{b}-{s}"] = float(after_b - after_s)     # runs saved for the fielding side by a strike instead of a ball
    return {"rv": table, "strike_value": sv, "k": k_val, "bb": bb_val,
            "mean_strike_value": float(np.nanmean(list(sv.values())))}


# ============================================================================ win expectancy

def _cum_gt(p: np.ndarray) -> np.ndarray:
    """S[k] = P(R > k)."""
    return 1.0 - np.cumsum(p)


def win_expectancy(rei: dict, auto_runner: bool = True) -> dict:
    """WE tables from the top/bottom run distributions (see module doc).
    Returns {"we": array [inning 1..INNING_TABLE][half][outs][bases][lead -D_MAX..D_MAX], "x_extra", ...}."""
    Pt, Pb = rei["dist_top"], rei["dist_bot"]
    K = K_MAX + 1
    D = np.arange(-D_MAX, D_MAX + 1)
    nd = len(D)
    st_extra = (0, 2) if auto_runner else (0, 0)
    pt_x, pb_x = Pt[st_extra], Pb[st_extra]
    # tied extra inning value
    S_b = _cum_gt(pb_x)
    X = float(np.sum(pt_x * S_b) / max(1 - np.sum(pt_x * pb_x), 1e-12))

    def clipd(d):
        return np.clip(d, -D_MAX, D_MAX) + D_MAX

    IM = INNING_TABLE
    # top_start[i][d], bot_start[i][d]: value at the start of a half with lead d (index by d + D_MAX)
    top_start = np.zeros((IM + 2, nd)); bot_start = np.zeros((IM + 2, nd))
    after_top = np.zeros((IM + 2, nd)); after_bot = np.zeros((IM + 2, nd))
    # extra innings (i >= 10 in the table): a non-tied lead cannot occur at the top of an extra inning except via
    # clipping; give them the regulation-style formula with the extra start state
    for i in range(IM + 1, 0, -1):
        ii = min(i, IM)
        p_top = Pt[st_extra] if (ii >= 10) else Pt[0, 0]
        p_bot = Pb[st_extra] if (ii >= 10) else Pb[0, 0]
        # after bottom of i with lead d'
        if ii >= 9:
            nxt = np.where(D > 0, 1.0, np.where(D < 0, 0.0, X if ii >= 9 else 0.5))
            # tied after the bottom of 9+ -> top of the next (extra) inning, value X
            after_bot[i] = nxt
        else:
            after_bot[i] = top_start[i + 1]
        # bottom start of i with lead d: sum_k p_bot[k] * after_bot(d + k), walk-off exact
        vals = np.zeros(nd)
        for k in range(K):
            vals += p_bot[k] * after_bot[i][clipd(D + k)]
        bot_start[i] = vals
        # after top of i with lead d'
        after_top[i] = np.where((D > 0) & (ii >= 9), 1.0, bot_start[i])
        vals = np.zeros(nd)
        for k in range(K):
            vals += p_top[k] * after_top[i][clipd(D - k)]
        top_start[i] = vals
    # in-state table
    we = np.zeros((IM, 2, 3, 8, nd))
    for i in range(1, IM + 1):
        for o in range(3):
            for b in range(8):
                pt, pb = Pt[o, b], Pb[o, b]
                vt = np.zeros(nd); vb = np.zeros(nd)
                for k in range(K):
                    vt += pt[k] * after_top[i][clipd(D - k)]
                    vb += pb[k] * after_bot[i][clipd(D + k)]
                we[i - 1, 0, o, b] = vt
                we[i - 1, 1, o, b] = vb
    return {"we": we, "after_top": after_top[1:IM + 1], "after_bot": after_bot[1:IM + 1], "x_extra": X,
            "home_start": float(top_start[1][D_MAX]), "auto_runner": auto_runner}


def we_lookup(wet: dict, inning, half, outs, bases, lead) -> np.ndarray:
    """P(home wins) for arrays of states; outs == 3 means the half-inning just ended."""
    we = wet["we"]
    i = np.clip(np.asarray(inning, int), 1, INNING_TABLE) - 1
    h = np.asarray(half, int)
    o = np.asarray(outs, int)
    b = np.clip(np.asarray(bases, int), 0, 7)
    d = np.clip(np.asarray(lead, int), -D_MAX, D_MAX) + D_MAX
    out = np.empty(len(i))
    mid = o < 3
    out[mid] = we[i[mid], h[mid], o[mid], b[mid], d[mid]]
    end = ~mid
    out[end] = np.where(h[end] == 0, wet["after_top"][i[end], d[end]], wet["after_bot"][i[end], d[end]])
    return out


def _transitions(pa: pd.DataFrame) -> dict:
    """Empirical one-PA transitions per start state: {(o, b): (end_outs, end_bases, runs, prob)}."""
    t = pa[pa["cls"].isin(CLASSES)]
    g = t.groupby(["outs_when_up", "bases", "end_outs", "end_bases", t["runs_pa"].clip(0, 4).round().astype(int)]).size()
    out = {}
    for (o, b, eo, eb, r), cnt in g.items():
        out.setdefault((int(o), int(b)), []).append((int(eo), int(eb), int(r), float(cnt)))
    for k, lst in out.items():
        tot = sum(x[3] for x in lst)
        out[k] = [(eo, eb, r, c / tot) for eo, eb, r, c in lst]
    return out


def leverage_table(wet: dict, pa: pd.DataFrame) -> np.ndarray:
    """Raw expected |ΔWE| per state [inning][half][outs][bases][lead]; normalise with `li_norm`."""
    tr = _transitions(pa)
    nd = 2 * D_MAX + 1
    D = np.arange(-D_MAX, D_MAX + 1)
    raw = np.zeros((INNING_TABLE, 2, 3, 8, nd))
    for i in range(1, INNING_TABLE + 1):
        for h in (0, 1):
            for o in range(3):
                for b in range(8):
                    now = wet["we"][i - 1, h, o, b]
                    acc = np.zeros(nd)
                    for eo, eb, r, p in tr.get((o, b), []):
                        lead2 = D - r if h == 0 else D + r
                        nxt = we_lookup(wet, np.full(nd, i), np.full(nd, h), np.full(nd, min(eo, 3)), np.full(nd, eb), lead2)
                        if h == 1 and i >= 9:
                            nxt = np.where(lead2 > 0, 1.0, nxt)
                        acc += p * np.abs(nxt - now)
                    raw[i - 1, h, o, b] = acc
    return raw


def add_wpa(pa: pd.DataFrame, wet: dict, li_raw: np.ndarray | None = None) -> pd.DataFrame:
    """WE before/after, WPA (batting side) and LI per PA. Lead = home score - away score at the PA's first pitch."""
    pa = pa.copy()
    home_bat = pa["half"].to_numpy() == 1
    bat = pa["bat_score"].astype(float).to_numpy(); fld = pa["fld_score"].astype(float).to_numpy()
    lead = np.where(home_bat, bat - fld, fld - bat)
    pa["lead"] = lead
    before = we_lookup(wet, pa["inning"], pa["half"], pa["outs_when_up"], pa["bases"], lead)
    runs = pa["runs_pa"].to_numpy(float)
    lead_after = lead + np.where(home_bat, runs, -runs)
    after = we_lookup(wet, pa["inning"], pa["half"], np.minimum(pa["end_outs"], 3), pa["end_bases"], lead_after)
    # walk-offs and game ends: the last PA of a game gets the actual result
    last_game = (pa["game_pk"].shift(-1) != pa["game_pk"]).to_numpy()
    if last_game.any():
        fin = pa.groupby("game_pk", sort=False).apply(_final_home_win, include_groups=False)
        res = pa["game_pk"].map(fin).to_numpy(float)
        after = np.where(last_game & np.isfinite(res), res, after)
    walk = home_bat & (pa["inning"].to_numpy() >= 9) & (lead_after > 0)
    after = np.where(walk, 1.0, after)
    pa["we_before"] = before
    pa["we_after"] = after
    pa["wpa"] = np.where(home_bat, after - before, before - after)
    if li_raw is not None:
        i = np.clip(pa["inning"].to_numpy(int), 1, INNING_TABLE) - 1
        raw = li_raw[i, pa["half"].to_numpy(int), pa["outs_when_up"].to_numpy(int), pa["bases"].to_numpy(int),
                     np.clip(lead.astype(int), -D_MAX, D_MAX) + D_MAX]
        pa["li"] = raw / max(float(np.mean(raw)), 1e-9)
    return pa


def _final_home_win(g: pd.DataFrame) -> float:
    home = g.loc[g["half"] == 1, "post_bat_score"].max() if (g["half"] == 1).any() else 0.0
    away = g.loc[g["half"] == 0, "post_bat_score"].max() if (g["half"] == 0).any() else 0.0
    if "home_final" in g:
        home, away = g["home_final"].iloc[0], g["away_final"].iloc[0]
    if pd.isna(home) or pd.isna(away) or home == away:
        return float("nan")
    return float(home > away)


def we_calibration(pa: pd.DataFrame, bins: int = 10) -> dict:
    """Calibration of we_before against the actual result of each game (one row per PA)."""
    fin = pa.groupby("game_pk", sort=False).apply(_final_home_win, include_groups=False)
    y = pa["game_pk"].map(fin).to_numpy(float)
    p = pa["we_before"].to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    if not len(y):
        return {"n": 0}
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for k in range(bins):
        m = idx == k
        if m.any():
            rows.append([float(p[m].mean()), float(y[m].mean()), int(m.sum())])
    brier = float(np.mean((p - y) ** 2))
    ll = float(-np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1))))
    return {"n": int(len(y)), "brier": brier, "logloss": ll, "bins": rows}


# ============================================================================ season drivers

def season_tables(pa: pd.DataFrame, season: int | None = None, regular: bool = True, with_wpa: bool = True) -> dict:
    """All run/win tables for one season's prepared PA table. Returns
    {"pa" (valued, with WPA/LI), "re" (re_matrix dict), "lw", "we" (win_expectancy dict), "li_raw"}."""
    pa = prepare_pa(pa)
    rei = re_matrix(pa)
    pa = pa_values(pa, rei["re"])
    lw = linear_weights(pa, rei)
    out = {"re": rei, "lw": lw}
    if with_wpa:
        auto = bool(regular and (season is None or season >= AUTO_RUNNER_FROM))
        wet = win_expectancy(rei, auto_runner=auto)
        li_raw = leverage_table(wet, pa)
        pa = add_wpa(pa, wet, li_raw)
        out.update(we=wet, li_raw=li_raw)
    out["pa"] = pa
    return out


def statcast_season(level: str, season: int, pitches: pd.DataFrame | None = None, with_wpa: bool = True,
                    count: bool = True) -> dict | None:
    """Season tables from the pitch table (loaded when not given), plus count values."""
    cols = ["game_date", "home_team", "away_team", "inning", "inning_topbot", "batter", "pitcher", "stand", "p_throws",
            "outs_when_up", "bat_score", "fld_score", "post_bat_score", "on_1b", "on_2b", "on_3b", "events",
            "description", "balls", "strikes", "woba_value", "woba_denom", "home_win_exp", "delta_home_win_exp"]
    if pitches is None:
        pitches = _c.load_pitches(level, season, cols)
        if pitches is None or not len(pitches):
            return None
    else:
        pitches = _c.prepare_pitches(pitches.copy(), game_types=("R",))
    pa = _c.pa_table(pitches)
    res = season_tables(pa, season=season, regular=True, with_wpa=with_wpa)
    if count:
        res["counts"] = count_values(pitches, res["pa"])
    return res


def retro_season(season: int, df: pd.DataFrame | None = None, with_wpa: bool = False) -> dict | None:
    """Season tables from the Retrosheet event table (regular season)."""
    df = _c.load_pa(season) if df is None else df
    if df is None or not len(df):
        return None
    pa = retro_pa(df)
    if not len(pa):
        return None
    return season_tables(pa, season=season, regular=True, with_wpa=with_wpa)


def summary(res: dict) -> dict:
    """JSON-ready season summary: RE matrix, counts, linear and wOBA weights, count values, WE extras."""
    rei = res["re"]
    out = {"version": MODEL_VERSION, "re": _c.clean(rei["re"].tolist(), 3), "n": rei["n"].tolist(),
           "runs_per_inning": round(rei["runs_per_inning"], 4), "lw": _c.clean(res["lw"], 4)}
    if "counts" in res:
        out["counts"] = _c.clean(res["counts"], 4)
    if "we" in res:
        out["we_home_start"] = round(res["we"]["home_start"], 4)
        out["we_x_extra"] = round(res["we"]["x_extra"], 4)
        if "we_before" in res["pa"]:
            out["we_calibration"] = _c.clean(we_calibration(res["pa"]), 4)
    return out


def we_payload(wet: dict) -> dict:
    """Compact WE table for the site: innings 1..10+, half, outs, bases, lead -D_TABLE..D_TABLE (3 dp)."""
    lo, hi = D_MAX - D_TABLE, D_MAX + D_TABLE + 1
    return {"leads": list(range(-D_TABLE, D_TABLE + 1)), "we": np.round(wet["we"][..., lo:hi], 3).tolist(),
            "after_top": np.round(wet["after_top"][:, lo:hi], 3).tolist(),
            "after_bot": np.round(wet["after_bot"][:, lo:hi], 3).tolist(), "auto_runner": wet["auto_runner"]}


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """Cached JSON summary for a Statcast season (RE matrix, weights, count values, WE table summary)."""
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        res = statcast_season(level, season)
        if res is None:
            return {"ok": False, "reason": "empty pitch table"}
        out = summary(res)
        out["we_table"] = we_payload(res["we"])
        out["ok"] = True
        return out
    return _c.cached("re24", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def weights(level: str, season: int) -> dict | None:
    """Linear/wOBA weights and count values for a season: cache, else the committed fit, else None."""
    r = for_season(level, season) if _c.pitch_path(level, season).exists() else None
    if isinstance(r, dict) and r.get("ok"):
        return r
    fit = _c.read_fit(f"re24_{level}") or {}
    return (fit.get("seasons") or {}).get(str(season))


def woba_weights(season: int, level: str = "mlb") -> dict | None:
    """{"BB","HBP","1B","2B","3B","HR","scale","lg_woba"} for a season: the Statcast-era cache/fit, else the
    Retrosheet fit, else None."""
    w = None
    try:
        w = weights(level, season)
    except Exception:
        w = None
    lw = (w or {}).get("lw")
    if not lw:
        fit = _c.read_fit("re24_retro") or {}
        lw = ((fit.get("seasons") or {}).get(str(season)) or {}).get("lw")
    if not lw or not lw.get("woba_w"):
        return None
    out = {k: float(v) for k, v in lw["woba_w"].items() if v is not None}
    out.update(scale=float(lw.get("woba_scale") or 1.2), lg_woba=float(lw.get("lg_woba") or 0.315))
    return out


def export_fits(level: str = "mlb", seasons: list[int] | None = None, retro: bool = True) -> dict:
    """Write models/fitted/re24_<level>.json (per-season summaries, Statcast era) and, with `retro`,
    re24_retro.json (per-season RE matrix and linear weights from Retrosheet PAs, one season at a time)."""
    seasons = seasons or _c.pitch_seasons(level)
    out = {"version": MODEL_VERSION, "level": level, "seasons": {}}
    latest_we = None
    for s in seasons:
        r = for_season(level, s)
        if isinstance(r, dict) and r.get("ok"):
            we = r.pop("we_table", None)
            out["seasons"][str(s)] = r
            latest_we = we or latest_we
    if latest_we:
        out["we_table"] = latest_we
    _c.write_fit(f"re24_{level}", out)
    if retro:
        rr = {"version": MODEL_VERSION, "seasons": {}}
        for s in _c.retro_seasons():
            res = retro_season(s)
            if res is not None:
                rr["seasons"][str(s)] = summary(res)
        if rr["seasons"]:
            _c.write_fit("re24_retro", rr)
    return out
