"""
The fantasy projection model, its walk-forward backtest and the payloads (the method is described in fantasy.py).
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import fantasy as F
from oddsmarkets.nfl.analytics.fantasy import FORMATS, POS4, REG_WEEKS, PREV_W, points

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------------- rosters, injuries

OUT_STATUS = {"RES", "PUP", "SUS", "NWT", "EXE", "RET", "CUT", "DEV", "TRD", "TRC", "NON", "UFA", "RSN", "RSR"}


def rosters(season: int) -> pd.DataFrame:
    """Weekly rosters: [pid, team, pos, status, week, name]."""
    from oddsmarkets.nfl.analytics.context import load_release
    df = load_release("weekly_rosters", season, ["gsis_id", "team", "position", "status", "week", "full_name", "game_type"])
    if df is None or not len(df):
        return pd.DataFrame(columns=["pid", "team", "pos", "status", "week", "name"])
    df = df[df["gsis_id"].notna()]
    if "game_type" in df:
        df = df[df["game_type"].isin(["REG"]) | df["game_type"].isna()]
    out = pd.DataFrame({"pid": df["gsis_id"].astype(str), "team": [F._canon(t, season) for t in df["team"]],
                        "pos": df["position"].astype(str).replace({"FB": "RB", "HB": "RB"}), "status": df["status"].astype(str),
                        "week": pd.to_numeric(df["week"], errors="coerce").fillna(0).astype(int), "name": df["full_name"].astype(str)})
    return out.reset_index(drop=True)


def injuries(season: int) -> pd.DataFrame:
    """Injury reports: [pid, week, status (Out / Doubtful / Questionable / None), injury]."""
    from oddsmarkets.nfl.analytics.context import load_release
    df = load_release("injuries", season, ["gsis_id", "week", "report_status", "season_type", "report_primary_injury", "position"])
    if df is None or not len(df):
        return pd.DataFrame(columns=["pid", "week", "status", "injury"])
    if "season_type" in df:
        df = df[df["season_type"] == "REG"]

    def clean(s):
        return s.astype(str).where(~s.astype(str).isin(["nan", "None", "<NA>"]), None)
    return pd.DataFrame({"pid": df["gsis_id"].astype(str), "week": pd.to_numeric(df["week"], errors="coerce").fillna(0).astype(int),
                         "status": clean(df["report_status"]), "injury": clean(df["report_primary_injury"]),
                         "pos": df["position"].astype(str) if "position" in df else None}).reset_index(drop=True)


def avail_of(status: Any, P: dict) -> float:
    s = str(status or "")
    if s == "Out":
        return 0.0
    if s == "Doubtful":
        return float(P["P_D"])
    if s == "Questionable":
        return float(P["P_Q"])
    return 1.0


# ---------------------------------------------------------------------------------------------- usage and efficiency

def _div(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / np.where(b > 0, b, 1.0), 0.0)


SHARE_COLS = {"s_tgt": ("tgt", "team_tgt"), "s_car": ("car", "team_car"), "s_xrt": ("xrec_td", "team_xrec_td"),
              "s_xut": ("xrush_td", "team_xrush_td"), "s_att": ("att", "team_att"), "s_rz": ("rz_tgt", "team_rz_tgt"),
              "s_air": ("air", "team_air"), "s_rzc": ("rz_car", "team_rz_car")}
EFF_SUMS = ["tgt", "rec", "rec_yds", "xrec", "xrec_yds", "car", "rush_yds", "xrush_yds", "att", "pass_yds", "pass_td", "ints",
            "rec_td", "rush_td", "xrec_td", "xrush_td", "fp_ppr", "fp_half", "fp_std", "xfp_ppr", "fl", "rz_tgt", "rz_car", "gl_car", "air"]


def shares(H: pd.DataFrame, w: int, hl: float) -> pd.DataFrame:
    """Per player over the games in H: recency-weighted shares (weights 0.5^((w - 1 - week) / hl)), games, sums of the
    stat columns (EFF_SUMS as n_<col>), last team, last three games' shares."""
    if not len(H):
        return pd.DataFrame(columns=["pid", "wt", "games"])
    H = H.copy()
    for k, (a, b) in SHARE_COLS.items():
        H[k] = _div(H[a], H[b])
    H["wt"] = 0.5 ** ((w - 1 - H["week"]) / hl)
    for k in SHARE_COLS:
        H["w_" + k] = H["wt"] * H[k]
    g = H.groupby("pid")
    out = g[["wt"] + ["w_" + k for k in SHARE_COLS]].sum()
    for k in SHARE_COLS:
        out[k] = out["w_" + k] / out["wt"]
    out["games"] = g.size()
    out["last_week"] = g["week"].max()
    srt = H.sort_values("week")
    last = srt.groupby("pid").tail(1).set_index("pid")
    out["team_last"] = last["team"]
    out["name"] = last["name"]
    out["pos_last"] = last["pos"]
    for c in EFF_SUMS:
        out["n_" + c] = g[c].sum()
    g3 = srt.groupby("pid").tail(3).groupby("pid")
    for k in ("s_tgt", "s_car", "s_rz"):
        out[k + "3"] = g3[k].mean()
    keep = ["wt", "games", "last_week", "team_last", "name", "pos_last"] + list(SHARE_COLS) + ["s_tgt3", "s_car3", "s_rz3"] + ["n_" + c for c in EFF_SUMS]
    return out[keep].reset_index()


def prepare(S: int, w: int, pw_cur: pd.DataFrame, pw_prev: pd.DataFrame, tw_cur: pd.DataFrame, P: dict) -> dict:
    """Everything a week's projections need from the games before week w."""
    H = pw_cur[pw_cur["week"] < w] if len(pw_cur) else pw_cur
    cur = shares(H, w, float(P["HL"]))
    prev = shares(pw_prev, REG_WEEKS + 1, 1e9) if len(pw_prev) else pd.DataFrame(columns=["pid", "wt", "games"])
    base = cur.merge(prev, on="pid", how="outer", suffixes=("", "_p"))
    for c in ("name", "pos_last", "team_last"):
        if c + "_p" in base:
            base[c] = base[c].fillna(base[c + "_p"])
    dflt = {}
    if len(prev):
        reg = prev[prev["games"] >= 4]
        for pos in POS4:
            m = reg[reg["pos_last"] == pos]
            dflt[pos] = {k: float(m[k].quantile(0.25)) if len(m) else 0.0 for k in SHARE_COLS}
    pg = float(P["PRIOR_G"])
    for k in SHARE_COLS:
        wc = base["wt"].fillna(0.0).to_numpy(float)
        xc = base[k].fillna(0.0).to_numpy(float)
        has_p = (base["games_p"].fillna(0) >= 3).to_numpy() if "games_p" in base else np.zeros(len(base), bool)
        xp = base[k + "_p"].fillna(0.0).to_numpy(float) if k + "_p" in base else np.zeros(len(base))
        prior_w = np.where(has_p, pg, 0.0)
        den = wc + prior_w
        base[k + "_hat"] = np.where(den > 0, (wc * xc + prior_w * xp) / np.where(den > 0, den, 1.0), np.nan)

    def tot(c):
        a = base["n_" + c].fillna(0.0) if "n_" + c in base else 0.0
        b = base["n_" + c + "_p"].fillna(0.0) if "n_" + c + "_p" in base else 0.0
        return (a + PREV_W * b).to_numpy(float) if hasattr(a + PREV_W * b, "to_numpy") else np.zeros(len(base))
    T = {c: tot(c) for c in EFF_SUMS}
    xcr = np.where(T["tgt"] > 0, _div(T["xrec"], T["tgt"]), 0.64)
    xypt = np.where(T["tgt"] > 0, _div(T["xrec_yds"], T["tgt"]), 7.0)
    base["catch"] = (T["rec"] + P["K_CATCH"] * xcr) / (T["tgt"] + P["K_CATCH"])
    base["ypt"] = (T["rec_yds"] + P["K_YPT"] * xypt) / (T["tgt"] + P["K_YPT"])
    xypc = np.where(T["car"] > 0, _div(T["xrush_yds"], T["car"]), 4.3)
    base["ypc"] = (T["rush_yds"] + P["K_YPC"] * xypc) / (T["car"] + P["K_YPC"])
    lg = pd.concat([H, pw_prev]) if len(pw_prev) else H
    lq = lg[lg["att"] > 0] if len(lg) else lg
    lg_ypa = float(lq["pass_yds"].sum() / max(lq["att"].sum(), 1)) if len(lq) else 6.8
    lg_int = float(lq["ints"].sum() / max(lq["att"].sum(), 1)) if len(lq) else 0.023
    base["ypa"] = (T["pass_yds"] + P["K_YPA"] * lg_ypa) / (T["att"] + P["K_YPA"])
    base["int_rate"] = (T["ints"] + P["K_INT"] * lg_int) / (T["att"] + P["K_INT"])
    return {"base": base, "dflt": dflt, "team": team_volume(w, pw_cur, pw_prev, tw_cur, P), "opp": opp_factors(w, pw_cur, pw_prev, P),
            "lg_ypa": lg_ypa, "lg_int": lg_int, "S": S, "w": w}


def _team_rows(pw: pd.DataFrame) -> pd.DataFrame:
    cols = ["team_tgt", "team_car", "team_att", "team_xrec_td", "team_xrush_td"]
    if not len(pw):
        return pd.DataFrame(columns=["team", "week"] + cols)
    return pw.groupby(["team", "week"])[cols].first().reset_index()


def team_volume(w: int, pw_cur, pw_prev, tw_cur, P: dict) -> pd.DataFrame:
    """Per team: recency-weighted targets, carries and pass attempts per game (last season as a prior worth
    TEAM_PRIOR_G games), the passing share of expected TDs, and the average expected margin in those games."""
    cols = ["team_tgt", "team_car", "team_att", "team_xrec_td", "team_xrush_td"]
    cur = _team_rows(pw_cur[pw_cur["week"] < w] if len(pw_cur) else pw_cur)
    prev = _team_rows(pw_prev)
    if len(cur):
        cur = cur.assign(wt=0.5 ** ((w - 1 - cur["week"]) / float(P["TEAM_HL"])))
        if len(tw_cur):
            mg = tw_cur[["team", "week"]].copy()
            mg["mg"] = pd.to_numeric(tw_cur["imp"], errors="coerce") - pd.to_numeric(tw_cur["oimp"], errors="coerce")
            cur = cur.merge(mg, on=["team", "week"], how="left")
        else:
            cur["mg"] = 0.0
        cur["mg"] = cur["mg"].fillna(0.0)
        for c in cols + ["mg"]:
            cur["w_" + c] = cur["wt"] * cur[c]
        a = cur.groupby("team")[["wt"] + ["w_" + c for c in cols + ["mg"]]].sum()
    else:
        a = pd.DataFrame(columns=["wt"] + ["w_" + c for c in cols + ["mg"]])
    p = prev.groupby("team")[cols].mean() if len(prev) else pd.DataFrame(columns=cols)
    lg = prev[cols].mean() if len(prev) else pd.Series({"team_tgt": 33.0, "team_car": 26.0, "team_att": 34.0, "team_xrec_td": 1.4,
                                                        "team_xrush_td": 0.9})
    rows = []
    pg = float(P["TEAM_PRIOR_G"])
    for t in sorted(set(a.index) | set(p.index)):
        r = {"team": t}
        wt = float(a.loc[t, "wt"]) if t in a.index else 0.0
        for c in cols:
            pr = float(p.loc[t, c]) if t in p.index and pd.notna(p.loc[t, c]) else float(lg[c])
            r[c] = ((float(a.loc[t, "w_" + c]) if t in a.index else 0.0) + pg * pr) / (wt + pg)
        r["mg_avg"] = (float(a.loc[t, "w_mg"]) / wt) if wt > 0 else 0.0
        tt = r["team_xrec_td"] + r["team_xrush_td"]
        r["f_rec"] = r["team_xrec_td"] / tt if tt > 0 else 0.6
        rows.append(r)
    if not rows:
        return pd.DataFrame(columns=cols + ["mg_avg", "f_rec"])
    return pd.DataFrame(rows).set_index("team")


def opp_factors(w: int, pw_cur, pw_prev, P: dict) -> dict[tuple, float]:
    """{(defence, pos): PPR points allowed to the position per game / league average}: recency-weighted, last season
    (half weight, half the league) as a prior worth K_OPP games."""
    def per_game(pw):
        if not len(pw):
            return pd.DataFrame(columns=["opp", "pos", "week", "fpa"])
        x = pw[pw["pos"].isin(POS4)]
        return x.groupby(["opp", "pos", "week"])["fp_ppr"].sum().rename("fpa").reset_index()
    cur = per_game(pw_cur[pw_cur["week"] < w] if len(pw_cur) else pw_cur)
    prev = per_game(pw_prev)
    lg = {}
    for pos in POS4:
        both = pd.concat([cur[cur["pos"] == pos], prev[prev["pos"] == pos]])
        lg[pos] = float(both["fpa"].mean()) if len(both) else 1.0
    pmean = prev.groupby(["opp", "pos"])["fpa"].mean() if len(prev) else pd.Series(dtype=float)
    if len(cur):
        cur = cur.assign(wt=0.5 ** ((w - 1 - cur["week"]) / float(P["HL"])))
        cur["wf"] = cur["wt"] * cur["fpa"]
        ca = cur.groupby(["opp", "pos"])[["wt", "wf"]].sum()
    else:
        ca = pd.DataFrame(columns=["wt", "wf"])
    out = {}
    k = float(P["K_OPP"])
    for key in set(ca.index) | set(pmean.index):
        d, pos = key
        if pos not in lg or lg[pos] <= 0:
            continue
        prior = 0.5 * float(pmean.get(key, lg[pos])) + 0.5 * lg[pos]
        wt = float(ca.loc[key, "wt"]) if key in ca.index else 0.0
        wf = float(ca.loc[key, "wf"]) if key in ca.index else 0.0
        out[key] = ((wf + k * prior) / (wt + k)) / lg[pos]
    return out


# ---------------------------------------------------------------------------------------------- one week's projections

def _redistribute(df: pd.DataFrame, share: str, grp: tuple, cap: float) -> pd.Series:
    """The share each available player takes: missing team-mates' usage (their share x (1 - availability)) shared out
    in proportion, then each team's total capped at `cap`. Returned per row, before his own availability."""
    out = df[share].fillna(0.0).astype(float).copy()
    m = df["pos"].isin(grp)
    if not m.any():
        return out
    s = df.loc[m, share].fillna(0.0).astype(float)
    a = df.loc[m, "avail"].astype(float)
    t = df.loc[m, "team"]
    have = (s * a).groupby(t).sum()
    vac = (s * (1.0 - a)).groupby(t).sum()
    scale = (1.0 + vac / have.where(have > 0)).fillna(1.0)
    new = s * t.map(scale)
    tot = (new * a).groupby(t).sum()
    lim = (cap / tot.where(tot > 0)).clip(upper=1.0).fillna(1.0)
    out.loc[m] = new * t.map(lim)
    return out


def project(prep: dict, ctx: dict, P: dict) -> pd.DataFrame:
    """Projected stat lines and points for one week. ctx = {"players": roster frame [pid, team, pos, name],
    "games": {team: {"opp", "imp", "oimp"}}, "avail": {pid: availability}, "qb": {team: starting QB pid}}.
    Teams without a game (byes) get no rows."""
    base, tv, of = prep["base"], prep["team"], prep["opp"]
    g = ctx["games"]
    pl = ctx["players"]
    pl = pl[pl["pos"].isin(POS4) & pl["team"].isin(list(g))]
    if not len(pl):
        return pd.DataFrame()
    bcols = [c for c in base.columns if c not in ("name",)]
    df = pl.merge(base[bcols], on="pid", how="left")
    for k in SHARE_COLS:
        d = df["pos"].map(lambda p, k=k: (prep["dflt"].get(p) or {}).get(k, 0.0)).astype(float)
        df[k + "_hat"] = df[k + "_hat"].astype(float).fillna(d)
    for c, d in (("catch", 0.64), ("ypt", 7.0), ("ypc", 4.3)):
        df[c] = df[c].astype(float).fillna(d)
    df["ypa"] = df["ypa"].astype(float).fillna(prep["lg_ypa"])
    df["int_rate"] = df["int_rate"].astype(float).fillna(prep["lg_int"])
    av = ctx.get("avail") or {}
    df["avail"] = df["pid"].map(lambda p: av.get(p, 1.0)).astype(float)
    qb = ctx.get("qb") or {}
    is_qb = (df["pos"] == "QB").to_numpy()
    start = np.array([qb.get(t) == p for t, p in zip(df["team"], df["pid"])], bool)
    s_att = df["s_att_hat"].fillna(0.0).to_numpy(float)
    s_att = np.where(is_qb & start, np.maximum(s_att, 0.95), 0.0)
    df["s_att_hat"] = s_att
    for k in ("s_car_hat", "s_xut_hat"):
        df[k] = np.where(is_qb & ~start, df[k].to_numpy(float) * 0.1, df[k].to_numpy(float))
    df["tgt_a"] = _redistribute(df, "s_tgt_hat", ("RB", "WR", "TE"), P["TGT_CAP"])
    df["xrt_a"] = _redistribute(df, "s_xrt_hat", ("RB", "WR", "TE"), P["TGT_CAP"])
    df["car_a"] = _redistribute(df, "s_car_hat", ("RB",), P["CAR_CAP"])
    df["xut_a"] = _redistribute(df, "s_xut_hat", ("RB",), P["CAR_CAP"])
    df["opp"] = df["team"].map(lambda t: g[t]["opp"])
    imp = df["team"].map(lambda t: g[t].get("imp")).astype(float).fillna(22.0)
    oimp = df["team"].map(lambda t: g[t].get("oimp")).astype(float).fillna(22.0)

    def tcol(c, d):
        return df["team"].map(lambda t: float(tv.loc[t, c]) if t in tv.index else d).astype(float)
    dev = (imp - oimp) - tcol("mg_avg", 0.0)
    team_tgt = (tcol("team_tgt", 33.0) + P["B_PASS"] * dev).clip(lower=15)
    team_att = (tcol("team_att", 34.0) + P["B_PASS"] * dev).clip(lower=15)
    team_car = (tcol("team_car", 26.0) + P["B_RUSH"] * dev).clip(lower=12)
    f_rec = tcol("f_rec", 0.6)
    td_g = np.maximum(P["TD_A"] + P["TD_B"] * imp, 0.3)
    opp_f = np.array([of.get((o, p), 1.0) for o, p in zip(df["opp"], df["pos"])], float)
    fac = opp_f ** float(P["ALPHA"])
    out = pd.DataFrame({"pid": df["pid"], "name": df["name"], "team": df["team"], "pos": df["pos"], "opp": df["opp"], "imp": imp,
                        "oimp": oimp, "avail": df["avail"], "opp_f": opp_f})
    tg = df["tgt_a"] * team_tgt
    car = df["car_a"] * team_car
    att = df["s_att_hat"] * team_att
    out["tgt"] = tg
    out["rec"] = tg * df["catch"]
    out["rec_yds"] = tg * df["ypt"] * fac
    out["rec_td"] = td_g * f_rec * df["xrt_a"] * fac
    out["car"] = car
    out["rush_yds"] = car * df["ypc"] * fac
    out["rush_td"] = td_g * (1.0 - f_rec) * df["xut_a"] * fac
    out["att"] = att
    out["pass_yds"] = att * df["ypa"] * fac
    out["pass_td"] = td_g * f_rec * df["s_att_hat"] * fac
    out["ints"] = att * df["int_rate"]
    out["fl"] = (out["rec"] + out["car"]) * P["FL_RATE"]
    for c in ("tgt", "rec", "rec_yds", "rec_td", "car", "rush_yds", "rush_td", "att", "pass_yds", "pass_td", "ints", "fl"):
        out[c] = out[c].astype(float).fillna(0.0).clip(lower=0.0) * out["avail"]
    for f in FORMATS:
        out[f] = points(out, f)
    out["starter_qb"] = is_qb & start
    for c in ("s_tgt_hat", "s_car_hat", "s_rz_hat", "s_air_hat", "s_xrt_hat", "s_xut_hat", "s_rzc_hat"):
        out[c] = df[c].astype(float).fillna(0.0).values
    return out.reset_index(drop=True)


def project_k_dst(ctx: dict, tw_cur: pd.DataFrame, tw_prev: pd.DataFrame, w: int, P: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kickers by team (implied points, the team's kicking history as a tilt) and D/ST (expected points-allowed score
    from the opponent's implied points; sacks and takeaways half from the defence's rate, half from the opponent
    offence's rate allowed, each shrunk toward the league; TDs, safeties and blocks at the league rate scaled by
    takeaways)."""
    games = ctx["games"]
    H = tw_cur[(tw_cur["week"] < w) & tw_cur["final"].astype(bool)] if len(tw_cur) else tw_cur
    Hp = tw_prev[tw_prev["final"].astype(bool)] if len(tw_prev) else tw_prev
    both = pd.concat([H, Hp]) if len(Hp) else H

    def rate(col, k=6.0, wp=0.5):
        if not len(both) or col not in both:
            return {}, 0.0
        lgm = float(pd.to_numeric(both[col], errors="coerce").mean())
        c = H.groupby("team")[col].agg(["sum", "count"]) if len(H) else pd.DataFrame(columns=["sum", "count"])
        p = Hp.groupby("team")[col].agg(["sum", "count"]) if len(Hp) else pd.DataFrame(columns=["sum", "count"])
        out = {}
        for t in set(c.index) | set(p.index):
            s = (float(c.loc[t, "sum"]) if t in c.index else 0.0) + wp * (float(p.loc[t, "sum"]) if t in p.index else 0.0)
            n = (float(c.loc[t, "count"]) if t in c.index else 0.0) + wp * (float(p.loc[t, "count"]) if t in p.index else 0.0)
            out[t] = (s + k * lgm) / (n + k)
        return out, lgm
    sk, lg_sk = rate("def_sacks")
    skd, _ = rate("sacked")
    ta, lg_ta = rate("takeaways")
    tad, _ = rate("gave")
    kp, lg_k = rate("k_pts", k=8.0)
    if len(both):
        oth = float(((both["def_tds"] + both["special_teams_tds"]) * 6 + both["def_safeties"] * 2 + both["blk"] * 2).mean())
    else:
        oth = 1.4
    k_rows, d_rows = [], []
    for t, gm in games.items():
        o = gm["opp"]
        imp = gm.get("imp")
        oimp = gm.get("oimp")
        imp = 22.0 if imp is None or (isinstance(imp, float) and math.isnan(imp)) else float(imp)
        oimp = 22.0 if oimp is None or (isinstance(oimp, float) and math.isnan(oimp)) else float(oimp)
        k_model = P["K_A"] + P["K_B"] * imp
        tilt = (kp.get(t, lg_k) / lg_k) if lg_k > 0 else 1.0
        k_rows.append({"team": t, "opp": o, "imp": imp, "proj": k_model * (0.75 + 0.25 * tilt)})
        sacks = 0.5 * sk.get(t, lg_sk) + 0.5 * skd.get(o, lg_sk)
        take = 0.5 * ta.get(t, lg_ta) + 0.5 * tad.get(o, lg_ta)
        pa = F.dst_pa_expected(oimp, float(P["DST_SD"]))
        other = oth * (take / lg_ta if lg_ta > 0 else 1.0)
        d_rows.append({"team": t, "opp": o, "oimp": oimp, "sacks": sacks, "take": take, "pa_pts": pa, "proj": sacks + 2.0 * take + pa + other})
    return pd.DataFrame(k_rows), pd.DataFrame(d_rows)


def week_games(tw: pd.DataFrame, w: int) -> dict[str, dict]:
    x = tw[tw["week"] == w] if len(tw) else tw
    return {r["team"]: {"opp": r["opp"], "imp": an.fnum(r.get("imp")), "oimp": an.fnum(r.get("oimp")), "game_id": r.get("game_id"),
                        "kickoff": r.get("kickoff"), "home": bool(r.get("home"))} for r in x.to_dict("records")}


def starting_qbs(pw_cur: pd.DataFrame, pw_prev: pd.DataFrame, w: int, roster_w: pd.DataFrame, avail: dict[str, float]) -> dict[str, str]:
    """{team: QB pid}: the passer with the team's most attempts in its latest game before week w, if available and on
    the roster; else the available roster QB with the most attempts this season and (half) last."""
    out: dict[str, str] = {}
    H = pw_cur[(pw_cur["week"] < w) & (pw_cur["att"] > 0)] if len(pw_cur) else pw_cur
    on: dict[str, list] = {}
    for r in roster_w[roster_w["pos"] == "QB"].to_dict("records"):
        on.setdefault(r["team"], []).append(r["pid"])
    att: dict[str, float] = {}
    for fr, wt in ((H, 1.0), (pw_prev[pw_prev["att"] > 0] if len(pw_prev) else pw_prev, 0.5)):
        if len(fr):
            for pid, a in fr.groupby("pid")["att"].sum().items():
                att[pid] = att.get(pid, 0.0) + wt * float(a)
    if len(H):
        lw = H.groupby("team")["week"].max()
        last = H[H["week"] == H["team"].map(lw)].sort_values("att").groupby("team").tail(1)
        for r in last.to_dict("records"):
            if r["pid"] in on.get(r["team"], []) and avail.get(r["pid"], 1.0) >= 0.5:
                out[r["team"]] = r["pid"]
    for t, ids in on.items():
        if t in out:
            continue
        ok = [p for p in ids if avail.get(p, 1.0) >= 0.5]
        if ok:
            out[t] = max(ok, key=lambda p: att.get(p, 0.0))
    return out


def week_context(roster: pd.DataFrame, inj: pd.DataFrame, w: int, tw: pd.DataFrame, P: dict) -> dict:
    """The roster of week w (the latest week on file when w is not yet published), availability from multi-week
    statuses (injured reserve, PUP, suspension, ...) and the injury report."""
    rw = roster[roster["week"] == w] if len(roster) else roster
    if not len(rw) and len(roster):
        rw = roster[roster["week"] == roster["week"].max()]
    rw = rw.drop_duplicates("pid", keep="last")
    avail: dict[str, float] = {}
    for p, s in zip(rw["pid"], rw["status"]):
        if s in OUT_STATUS:
            avail[p] = 0.0
    iw = inj[inj["week"] == w] if len(inj) else inj
    rep = {}
    for p, s, i in zip(iw["pid"], iw["status"], iw["injury"]):
        if isinstance(s, str) and s in ("Out", "Doubtful", "Questionable"):
            i = i if isinstance(i, str) else None
            avail[p] = min(avail.get(p, 1.0), avail_of(s, P))
            rep[p] = [s, i]
    players = rw[~rw["status"].isin({"CUT", "RET", "DEV", "TRD", "TRC", "UFA"})][["pid", "team", "pos", "name", "status"]]
    return {"players": players, "avail": avail, "games": week_games(tw, w), "inj": rep, "status": dict(zip(rw["pid"], rw["status"]))}


# ---------------------------------------------------------------------------------------------- the backtest

POOL_N = {"QB": 32, "RB": 64, "WR": 96, "TE": 32}


class SeasonData:
    """A season's frames, rosters and injuries plus last season's frames (loaded once)."""

    def __init__(self, S: int, fresh: bool = False):
        self.S = S
        # fresh: rebuild the season's frames now (the current season: the game model's implied points move)
        self.pw, self.tw = F.frames(S, F.season_games(S) if fresh else None)
        self.pwp, self.twp = F.frames(S - 1)
        self.ro = rosters(S)
        self.inj = injuries(S)

    def weeks(self) -> list[int]:
        if not len(self.tw):
            return []
        fin = self.tw[self.tw["final"].astype(bool)]
        return sorted(int(w) for w in fin["week"].unique() if int(w) <= REG_WEEKS)


def baselines(sd: SeasonData, w: int) -> pd.DataFrame:
    """Per player: season-to-date points per game (weeks before w) and last season's points per game, all formats."""
    H = sd.pw[sd.pw["week"] < w]
    cur = H.groupby("pid")[["fp_ppr", "fp_half", "fp_std"]].mean().add_prefix("std_") if len(H) else pd.DataFrame()
    cur["g_cur"] = H.groupby("pid").size() if len(H) else 0
    prev = sd.pwp.groupby("pid")[["fp_ppr", "fp_half", "fp_std"]].mean().add_prefix("last_") if len(sd.pwp) else pd.DataFrame()
    prev["g_last"] = sd.pwp.groupby("pid").size() if len(sd.pwp) else 0
    out = cur.join(prev, how="outer")
    for f in FORMATS:
        # week 1 (no games yet): season-to-date falls back to last season
        out["std_fp_" + f] = out["std_fp_" + f].fillna(out["last_fp_" + f]) if "std_fp_" + f in out else out["last_fp_" + f]
    return out


def backtest_week(sd: SeasonData, w: int, P: dict) -> pd.DataFrame:
    prep = prepare(sd.S, w, sd.pw, sd.pwp, sd.tw, P)
    ctx = week_context(sd.ro, sd.inj, w, sd.tw, P)
    ctx["qb"] = starting_qbs(sd.pw, sd.pwp, w, ctx["players"], ctx["avail"])
    pr = project(prep, ctx, P)
    if not len(pr):
        return pr
    b = baselines(sd, w)
    pr = pr.merge(b, left_on="pid", right_index=True, how="left")
    act = sd.pw[sd.pw["week"] == w].drop_duplicates("pid").set_index("pid")
    for f in FORMATS:
        pr["act_" + f] = pr["pid"].map(act["fp_" + f]).fillna(0.0)
    pr["played"] = pr["pid"].isin(act.index)
    # the fantasy-relevant pool, method-independent: top N at the position by either baseline
    keep = np.zeros(len(pr), bool)
    for pos, n in POOL_N.items():
        m = (pr["pos"] == pos).to_numpy()
        for col in ("std_fp_ppr", "last_fp_ppr"):
            if col in pr:
                r = pr.loc[m, col].rank(ascending=False, method="first")
                keep[np.where(m)[0][(r <= n).to_numpy()]] = True
    pr["pool"] = keep
    pr["S"], pr["w"] = sd.S, w
    return pr


def backtest_k_dst(sd: SeasonData, w: int, P: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    ctx = {"games": week_games(sd.tw, w)}
    k, d = project_k_dst(ctx, sd.tw, sd.twp, w, P)
    x = sd.tw[sd.tw["week"] == w].set_index("team")
    for fr, col in ((k, "k_pts"), (d, "dst_pts")):
        if len(fr):
            fr["act"] = fr["team"].map(x[col]) if col in x else np.nan
            prior = sd.tw[(sd.tw["week"] < w)].groupby("team")[col].mean() if len(sd.tw) else pd.Series(dtype=float)
            last = sd.twp.groupby("team")[col].mean() if len(sd.twp) else pd.Series(dtype=float)
            fr["std"] = fr["team"].map(prior).fillna(fr["team"].map(last))
            fr["last"] = fr["team"].map(last)
            fr["S"], fr["w"] = sd.S, w
    return k, d


def run_backtest(seasons: list[int], P: dict, with_kd: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows, ks, ds = [], [], []
    for S in seasons:
        sd = SeasonData(S)
        for w in sd.weeks():
            pr = backtest_week(sd, w, P)
            if len(pr):
                rows.append(pr[pr["pool"]])
            if with_kd:
                k, d = backtest_k_dst(sd, w, P)
                ks.append(k)
                ds.append(d)
    cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()   # noqa: E731
    return cat(rows), cat(ks), cat(ds)


def _spearman(a, b) -> float | None:
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    if len(a) < 5 or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def metrics(bt: pd.DataFrame, fmt: str = "ppr") -> dict:
    """MAE and mean weekly Spearman rank correlation of the model and the two baselines, by position and overall,
    for every pooled player and for those who played."""
    out = {}
    if not len(bt):
        return out
    for pos in list(POS4) + ["ALL"]:
        x = bt if pos == "ALL" else bt[bt["pos"] == pos]
        x = x.dropna(subset=["std_fp_" + fmt])
        r = {"n": int(len(x))}
        for name, col in (("model", fmt), ("season_to_date", "std_fp_" + fmt), ("last_season", "last_fp_" + fmt)):
            y = x.dropna(subset=[col])
            r[name] = {"mae": round(float((y[col] - y["act_" + fmt]).abs().mean()), 3) if len(y) else None,
                       "mae_played": round(float((y.loc[y["played"], col] - y.loc[y["played"], "act_" + fmt]).abs().mean()), 3) if y["played"].any() else None,
                       "rho": None, "n": int(len(y))}
            if pos != "ALL":
                rs = [_spearman(g[col], g["act_" + fmt]) for _, g in y.groupby(["S", "w"])]
                rs = [v for v in rs if v is not None]
                r[name]["rho"] = round(float(np.mean(rs)), 3) if rs else None
                yp = y[y["played"]]
                rp = [_spearman(g[col], g["act_" + fmt]) for _, g in yp.groupby(["S", "w"])]
                rp = [v for v in rp if v is not None]
                r[name]["rho_played"] = round(float(np.mean(rp)), 3) if rp else None
        out[pos] = r
    return out


def metrics_kd(fr: pd.DataFrame) -> dict:
    x = fr.dropna(subset=["act", "std"])
    if not len(x):
        return {}
    out = {"n": int(len(x))}
    for name, col in (("model", "proj"), ("season_to_date", "std"), ("last_season", "last")):
        y = x.dropna(subset=[col])
        rs = [_spearman(g[col], g["act"]) for _, g in y.groupby(["S", "w"])]
        rs = [v for v in rs if v is not None]
        out[name] = {"mae": round(float((y[col] - y["act"]).abs().mean()), 3), "rho": round(float(np.mean(rs)), 3) if rs else None}
    return out


# ---------------------------------------------------------------------------------------------- fitting

def fit_simple(seasons: list[int]) -> dict:
    """Low-dimensional constants by regression on the given seasons: team TDs and kicker points on implied points,
    the spread of points allowed around the opponent's implied points, script slopes of team targets and carries on
    the expected margin (within team-season), the rate players listed questionable / doubtful played, fumbles lost
    per touch."""
    tws, pws, injs = [], [], []
    for S in seasons:
        pw, tw = F.frames(S)
        tws.append(tw.assign(S=S))
        pws.append(pw.assign(S=S))
        injs.append(injuries(S).assign(S=S))
    tw = pd.concat(tws, ignore_index=True)
    pw = pd.concat(pws, ignore_index=True)
    inj = pd.concat(injs, ignore_index=True)
    out = {}
    x = tw.dropna(subset=["imp", "off_td"])
    x = x[x["final"].astype(bool)]
    b, a = np.polyfit(x["imp"].astype(float), x["off_td"].astype(float), 1)
    out["TD_A"], out["TD_B"] = round(float(a), 4), round(float(b), 5)
    y = x.dropna(subset=["k_pts"])
    b, a = np.polyfit(y["imp"].astype(float), y["k_pts"].astype(float), 1)
    out["K_A"], out["K_B"] = round(float(a), 4), round(float(b), 5)
    out["DST_SD"] = round(float((pd.to_numeric(x["pa"], errors="coerce") - x["oimp"].astype(float)).std()), 3)
    tm = pw.groupby(["S", "team", "week"])[["team_tgt", "team_car"]].first().reset_index()
    tm = tm.merge(tw[["S", "team", "week", "imp", "oimp"]], on=["S", "team", "week"], how="inner").dropna(subset=["imp", "oimp"])
    tm["mg"] = tm["imp"].astype(float) - tm["oimp"].astype(float)
    for col, key in (("team_tgt", "B_PASS"), ("team_car", "B_RUSH")):
        d = tm.groupby(["S", "team"])[[col, "mg"]].transform(lambda s: s - s.mean())
        out[key] = round(float(np.polyfit(d["mg"], d[col], 1)[0]), 4)
    played = set(zip(pw["S"], pw["pid"], pw["week"]))
    byes = set(zip(tw["S"], tw["team"], tw["week"]))
    for st, key in (("Questionable", "P_Q"), ("Doubtful", "P_D")):
        # skill players only: linemen and most defenders have no weekly stat row even when they play
        z = inj[(inj["status"] == st) & inj["pos"].isin(["QB", "RB", "WR", "TE", "FB"])]
        if len(z):
            out[key] = round(float(np.mean([(s, p, w) in played for s, p, w in zip(z["S"], z["pid"], z["week"])])), 4)
    sk = pw[pw["pos"].isin(POS4)]
    out["FL_RATE"] = round(float(sk["fl"].sum() / max((sk["rec"] + sk["car"]).sum(), 1)), 5)
    del byes
    return out


def fit_sd(bt: pd.DataFrame, fmt: str = "ppr") -> dict:
    """{pos: [c0, c1]}: SD of the actual around the projection = sqrt(pi / 2) x (c0 + c1 x projection), from a
    regression of absolute errors on the projection (players who played)."""
    out = {}
    for pos in POS4:
        x = bt[(bt["pos"] == pos) & bt["played"]]
        if len(x) < 50:
            out[pos] = [3.0, 0.4]
            continue
        b, a = np.polyfit(x[fmt].astype(float), (x[fmt] - x["act_" + fmt]).abs().astype(float), 1)
        k = math.sqrt(math.pi / 2)
        out[pos] = [round(float(max(a, 0.5) * k), 3), round(float(max(b, 0.05) * k), 4)]
    return out


GRID = {"HL": (3.0, 6.0), "ALPHA": (0.3, 0.7), "PRIOR_G": (2.0, 4.0)}


def tune(P0: dict, seasons: list[int]) -> tuple[dict, list]:
    """Grid over GRID on the tuning seasons by PPR MAE of the pool."""
    import itertools
    best, log = None, []
    for hl, al, pg in itertools.product(GRID["HL"], GRID["ALPHA"], GRID["PRIOR_G"]):
        P = dict(P0, HL=hl, ALPHA=al, PRIOR_G=pg)
        bt, _, _ = run_backtest(seasons, P, with_kd=False)
        mae = float((bt["ppr"] - bt["act_ppr"]).abs().mean())
        log.append([hl, al, pg, round(mae, 4)])
        logger.info("tune HL %s ALPHA %s PRIOR_G %s: MAE %.4f", hl, al, pg, mae)
        if best is None or mae < best[0]:
            best = (mae, P)
    return best[1], log


def fitted_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "models" / "fitted" / "fantasy.json"


def load_params() -> dict:
    P = dict(F.PARAMS)
    fit = an.read_json(fitted_path()) or {}
    for k, v in (fit.get("params") or {}).items():
        if k in P:
            P[k] = v
    P["SD"] = fit.get("sd") or {pos: [3.0, 0.4] for pos in POS4}
    return P


def fit_all(tune_seasons: tuple[int, int] = F.TUNE, eval_last: int = 2025) -> dict:
    """Constants and the grid on the tuning seasons, the SD model on their residuals, then the walk-forward backtest on
    EVAL_FIRST..eval_last with those fixed; writes models/fitted/fantasy.json and returns it. The live model's
    regression constants are then refitted on every completed season (the grid choice is kept)."""
    ts = list(range(tune_seasons[0], tune_seasons[1] + 1))
    P0 = dict(F.PARAMS)
    P0.update(fit_simple(ts))
    P, grid_log = tune(P0, ts)
    bt_t, _, _ = run_backtest(ts, P, with_kd=False)
    sd = fit_sd(bt_t)
    ev = list(range(F.EVAL_FIRST, eval_last + 1))
    bt, k, d = run_backtest(ev, P)
    res = {"version": F.VERSION, "fitted_at": an.now(), "tune_seasons": ts, "eval_seasons": ev, "grid": grid_log,
           "params_tuned": {k_: P[k_] for k_ in F.PARAMS}, "sd": sd}
    live = dict(P)
    live.update(fit_simple(list(range(tune_seasons[0], eval_last + 1))))
    res["params"] = {k_: live[k_] for k_ in F.PARAMS}
    res["backtest"] = summarise(bt, k, d, ev)
    an.write_json(fitted_path(), res)
    return res


def refresh_backtest() -> dict:
    """Re-run the evaluation backtest with the stored tuned parameters (no re-tuning) and rewrite its summary."""
    res = an.read_json(fitted_path()) or {}
    P = dict(F.PARAMS)
    P.update(res.get("params_tuned") or {})
    ev = res.get("eval_seasons") or list(range(F.EVAL_FIRST, 2026))
    bt, k, d = run_backtest(ev, P)
    res["backtest"] = summarise(bt, k, d, ev)
    # coverage of the floor-ceiling band (players who played)
    x = bt[bt["played"]]
    if len(x):
        Pm = dict(P, SD=res.get("sd") or {})
        inside = [band(p, pos, Pm)[0] <= a <= band(p, pos, Pm)[1] for p, pos, a in zip(x["ppr"], x["pos"], x["act_ppr"])]
        res["backtest"]["band_coverage"] = round(float(np.mean(inside)), 3)
    an.write_json(fitted_path(), res)
    return res


def summarise(bt: pd.DataFrame, k: pd.DataFrame, d: pd.DataFrame, seasons: list[int]) -> dict:
    out = {"seasons": seasons, "formats": {f: metrics(bt, f) for f in FORMATS}, "k": metrics_kd(k), "dst": metrics_kd(d),
           "by_season": {}, "n_weeks": int(bt.groupby(["S", "w"]).ngroups) if len(bt) else 0}
    for S, x in bt.groupby("S"):
        m = metrics(x, "ppr")
        out["by_season"][str(int(S))] = {pos: {"model": m[pos]["model"]["mae"], "season_to_date": m[pos]["season_to_date"]["mae"],
                                               "last_season": m[pos]["last_season"]["mae"], "rho": m[pos]["model"]["rho"],
                                               "rho_std": m[pos]["season_to_date"]["rho"]} for pos in m}
    # calibration of the band: share of actuals inside the 10th-90th percentile band (players who played)
    return out


# ---------------------------------------------------------------------------------------------- the payload

WAIVER_N = {"QB": 14, "RB": 30, "WR": 40, "TE": 12}
START_N = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}
COLS = ["pid", "name", "team", "pos", "status", "inj", "opp", "home", "imp", "opp_f",
        "ppr", "half", "std", "floor", "ceil", "tgt", "rec", "rec_yds", "rec_td", "car", "rush_yds", "rush_td", "att", "pass_yds", "pass_td", "ints",
        "ros_ppr", "ros_half", "ros_std", "ros_g", "next4", "sos", "sos4",
        "g", "pts_ppr", "pts_half", "pts_std", "xfp", "td", "xtd", "rec_yds_s", "xrec_yds_s", "rush_yds_s", "xrush_yds_s",
        "tgt_sh", "tgt_sh3", "car_sh", "car_sh3", "rz_sh", "rz_sh3", "air_sh", "ppg_last"]


def _r(x, nd=2):
    return an.rnd(x, nd)


def band(proj: float, pos: str, P: dict) -> tuple[float, float]:
    c0, c1 = (P.get("SD") or {}).get(pos) or [3.0, 0.4]
    sd = c0 + c1 * max(proj, 0.0)
    return max(0.0, proj - 1.2816 * sd), proj + 1.2816 * sd


def card_qbs(games: dict[str, dict], w: int) -> dict[str, str]:
    """{team: QB id} from the game cards of week w (our depth-chart QB for the game)."""
    out = {}
    for g in games.values():
        if g.get("week") != w:
            continue
        q = g.get("qbs") or {}
        for side in ("home", "away"):
            pid = (q.get(side) or {}).get("id")
            if pid and g.get(side):
                out[g[side]] = pid
    return out


def build(S: int, w_now: int, P: dict | None = None, fitted: dict | None = None) -> dict:
    """fantasy.json for the current season at week w_now (the next week to be played)."""
    P = P or load_params()
    fitted = fitted if fitted is not None else (an.read_json(fitted_path()) or {})
    sd = SeasonData(S, fresh=True)
    games = F.season_games(S)
    last_wk = max([int(w) for w in sd.tw["week"].unique()] + [w_now]) if len(sd.tw) else w_now
    last_wk = min(last_wk, REG_WEEKS)
    prep = prepare(S, w_now, sd.pw, sd.pwp, sd.tw, P)
    ctx = week_context(sd.ro, sd.inj, w_now, sd.tw, P)
    qb = starting_qbs(sd.pw, sd.pwp, w_now, ctx["players"], ctx["avail"])
    for t, pid in card_qbs(games, w_now).items():
        if ctx["avail"].get(pid, 1.0) >= 0.5:
            qb[t] = pid
    ctx["qb"] = qb
    nxt = project(prep, ctx, P)
    # the rest of the season: the same usage, each week's opponent and game script; this week's injury report only
    qb_later = starting_qbs(sd.pw, sd.pwp, w_now, ctx["players"], {p: (0.0 if ctx["status"].get(p) in OUT_STATUS else 1.0) for p in ctx["avail"]})
    ros_frames = []
    k_rows, d_rows = [], []
    for wk in range(w_now, last_wk + 1):
        g = week_games(sd.tw, wk)
        if not g:
            continue
        if wk == w_now:
            pr = nxt
            c = dict(ctx)
        else:
            av = {}
            for p, s in ctx["status"].items():
                if s in OUT_STATUS:
                    av[p] = 0.0 if (s != "RES" or wk < w_now + 4) else 0.5
            for p, (st, _inj) in ctx["inj"].items():
                if st == "Out" and p not in av:
                    av[p] = 0.85
            c = {"players": ctx["players"], "avail": av, "games": g, "qb": qb_later}
            pr = project(prep, c, P)
        if len(pr):
            ros_frames.append(pr.assign(week=wk))
        kk, dd = project_k_dst({"games": g}, sd.tw, sd.twp, w_now, P)
        k_rows.append(kk.assign(week=wk))
        d_rows.append(dd.assign(week=wk))
    ros = pd.concat(ros_frames, ignore_index=True) if ros_frames else pd.DataFrame()
    agg = ros.groupby("pid").agg(ros_ppr=("ppr", "sum"), ros_half=("half", "sum"), ros_std=("std", "sum"), ros_g=("avail", "sum"),
                                 sos=("opp_f", "mean")) if len(ros) else pd.DataFrame()
    n4 = ros[ros["week"] < w_now + 4] if len(ros) else ros
    sos4 = n4.groupby("pid")["opp_f"].mean() if len(n4) else pd.Series(dtype=float)
    weekly = {pid: [[int(w), o, _r(p, 1)] for w, o, p in zip(x["week"], x["opp"], x["ppr"])] for pid, x in n4.groupby("pid")} if len(n4) else {}
    base = prep["base"].set_index("pid")
    rows = []
    for r in nxt.to_dict("records"):
        pid = r["pid"]
        b = base.loc[pid] if pid in base.index else None
        a = agg.loc[pid] if len(agg) and pid in agg.index else None
        if b is not None and isinstance(b, pd.DataFrame):
            b = b.iloc[0]
        g_cur = float(b["games"]) if b is not None and pd.notna(b.get("games")) else 0.0
        fl, ce = band(r["ppr"], r["pos"], P)
        num = (lambda k: float(b[k]) if b is not None and k in b and pd.notna(b[k]) else 0.0)
        ros_ppr = float(a["ros_ppr"]) if a is not None else 0.0
        if ros_ppr < 3.0 and num("n_fp_ppr") <= 0:
            continue
        inj = ctx["inj"].get(pid)
        rows.append({"pid": pid, "name": r["name"], "team": r["team"], "pos": r["pos"], "status": ctx["status"].get(pid),
                     "inj": inj[0] if inj else None, "opp": r["opp"], "home": (week_games(sd.tw, w_now).get(r["team"]) or {}).get("home"),
                     "imp": _r(r["imp"], 1), "opp_f": _r(r["opp_f"], 2), "ppr": _r(r["ppr"], 1), "half": _r(r["half"], 1), "std": _r(r["std"], 1),
                     "floor": _r(fl, 1), "ceil": _r(ce, 1), "tgt": _r(r["tgt"], 1), "rec": _r(r["rec"], 1), "rec_yds": _r(r["rec_yds"], 0),
                     "rec_td": _r(r["rec_td"], 2), "car": _r(r["car"], 1), "rush_yds": _r(r["rush_yds"], 0), "rush_td": _r(r["rush_td"], 2),
                     "att": _r(r["att"], 1), "pass_yds": _r(r["pass_yds"], 0), "pass_td": _r(r["pass_td"], 2), "ints": _r(r["ints"], 2),
                     "ros_ppr": _r(ros_ppr, 1), "ros_half": _r(a["ros_half"] if a is not None else 0.0, 1),
                     "ros_std": _r(a["ros_std"] if a is not None else 0.0, 1), "ros_g": _r(a["ros_g"] if a is not None else 0.0, 1),
                     "next4": weekly.get(pid), "sos": _r(a["sos"] if a is not None else None, 2), "sos4": _r(sos4.get(pid), 2),
                     "g": int(g_cur), "pts_ppr": _r(num("n_fp_ppr"), 1), "pts_half": _r(num("n_fp_half"), 1), "pts_std": _r(num("n_fp_std"), 1),
                     "xfp": _r(num("n_xfp_ppr"), 1) if r["pos"] != "QB" else None, "td": _r(num("n_rec_td") + num("n_rush_td") + num("n_pass_td") * (1 if r["pos"] == "QB" else 0), 0),
                     "xtd": _r(num("n_xrec_td") + num("n_xrush_td"), 1), "rec_yds_s": _r(num("n_rec_yds"), 0), "xrec_yds_s": _r(num("n_xrec_yds"), 0),
                     "rush_yds_s": _r(num("n_rush_yds"), 0), "xrush_yds_s": _r(num("n_xrush_yds"), 0),
                     "tgt_sh": _r(num("s_tgt"), 3), "tgt_sh3": _r(num("s_tgt3"), 3), "car_sh": _r(num("s_car"), 3), "car_sh3": _r(num("s_car3"), 3),
                     "rz_sh": _r(num("s_rz"), 3), "rz_sh3": _r(num("s_rz3"), 3), "air_sh": _r(num("s_air"), 3),
                     "ppg_last": _r(num("n_fp_ppr_p") / num("games_p") if num("games_p") else None, 1)})
    rows.sort(key=lambda x: -(x["ros_ppr"] or 0))
    K = pd.concat(k_rows, ignore_index=True) if k_rows else pd.DataFrame()
    D = pd.concat(d_rows, ignore_index=True) if d_rows else pd.DataFrame()

    def team_tab(fr):
        out = {}
        for t, x in fr.groupby("team"):
            x = x.sort_values("week")
            out[t] = {"weeks": [[int(w), o, _r(p, 1)] for w, o, p in zip(x["week"], x["opp"], x["proj"])][:4],
                      "ros": _r(x["proj"].sum(), 1), "next": _r(x["proj"].iloc[0], 1) if int(x["week"].iloc[0]) == w_now else None}
        return out
    sos_tab = {}
    if len(ros):
        for (t, pos), x in ros.groupby(["team", "pos"]):
            sos_tab.setdefault(t, {})[pos] = [_r(x["opp_f"].mean(), 3), _r(x[x["week"] < w_now + 4]["opp_f"].mean(), 3)]
    payload = {"ok": True, "season": S, "week": w_now, "last_week": last_wk, "updated_at": an.now(), "version": F.VERSION,
               "cols": COLS, "rows": [[x.get(c) for c in COLS] for x in rows],
               "k": team_tab(K) if len(K) else {}, "dst": team_tab(D) if len(D) else {}, "sos": sos_tab,
               "picks": picks(rows, team_tab(K) if len(K) else {}, team_tab(D) if len(D) else {}, w_now),
               "waiver_n": WAIVER_N, "start_n": START_N, "sd": P.get("SD"),
               "params": {k: P[k] for k in F.PARAMS},
               "backtest": (fitted or {}).get("backtest"), "tune_seasons": (fitted or {}).get("tune_seasons"),
               "scoring": {"pass_yd": 0.04, "pass_td": 4, "int": -2, "rush_rec_yd": 0.1, "td": 6, "fumble_lost": -2, "two_pt": 2,
                           "reception": REC_PTS_PUB, "k": "FG 0-39 3, 40-49 4, 50+ 5, XP 1, missed FG/XP -1",
                           "dst": "sack 1, INT 2, fumble recovery 2, safety 2, TD 6, block 2; points allowed 0: 10, 1-6: 7, 7-13: 4, "
                                  "14-20: 1, 21-27: 0, 28-34: -1, 35+: -4"},
               "notes": {"left_out": "Snap counts are not used: nflverse's come from Pro Football Reference, whose terms forbid "
                                     "building websites or tools on its data. Routes run have no public in-season source. "
                                     "Fantasy-platform ADP, ownership and salaries are not used (platform terms restrict reuse).",
                         "waiver": "We have no league ownership data: 'likely available' means outside the top "
                                   + ", ".join(f"{n} {p}" for p, n in WAIVER_N.items()) + " in points so far (PPR).",
                         "injuries": "Injury report statuses as nflverse publishes them (the NFL's); out = 0, doubtful and "
                                     "questionable at the rate such players have played."},
               "credits": [an.NFLVERSE_CREDIT]}
    return payload


REC_PTS_PUB = {"ppr": 1.0, "half": 0.5, "std": 0.0}


def _pct(x):
    return f"{100 * x:.0f}%"


def _n(v: float, word: str) -> str:
    """'1 TD', '3 TDs': a whole count with its noun in the right number."""
    k = int(round(v or 0))
    return f"{k} {word}" + ("" if k == 1 else "s")


def picks(rows: list[dict], K: dict, D: dict, w: int) -> dict:
    """Our suggested picks with reasons (PPR): start (projected well above where his season so far ranks him), waiver
    targets (likely available: outside the top scorers at the position; ranked by rest-of-season points per game with
    rising usage counting), buy-low (usage worth more points than he has scored), sell-high (scoring on touchdowns the
    usage does not support), breakouts (usage rising over the last three games), streamers (D/ST and K for the week)."""
    out = {"start": [], "waiver": [], "buy_low": [], "sell_high": [], "breakout": [], "dst": [], "k": []}
    by_pos: dict[str, list] = {}
    for r in rows:
        by_pos.setdefault(r["pos"], []).append(r)
    for pos, xs in by_pos.items():
        played = [x for x in xs if (x.get("g") or 0) > 0]
        szn = sorted(played, key=lambda x: -((x["pts_ppr"] or 0) / max(x["g"] or 1, 1)))
        rank_s = {x["pid"]: i + 1 for i, x in enumerate(szn)}
        wk = sorted([x for x in xs if (x.get("ppr") or 0) > 0], key=lambda x: -(x["ppr"] or 0))
        rank_w = {x["pid"]: i + 1 for i, x in enumerate(wk)}
        tot = sorted(played, key=lambda x: -(x["pts_ppr"] or 0))
        rank_t = {x["pid"]: i + 1 for i, x in enumerate(tot)}
        n = START_N.get(pos, 24)
        for x in xs:
            rw, rs = rank_w.get(x["pid"]), rank_s.get(x["pid"])
            why = []
            if x.get("opp_f") and x["opp_f"] >= 1.08:
                why.append(f"{x['opp']} allow {100 * (x['opp_f'] - 1):.0f}% more PPR points to {pos}s than average")
            if x.get("imp") and x["imp"] >= 25:
                why.append(f"team implied for {x['imp']:.1f} points")
            if rw and rw <= n and rs and rs - rw >= max(6, n // 3) and not x.get("inj"):
                out["start"].append({"pid": x["pid"], "pos": pos, "score": rs - rw,
                                     "why": f"projected {x['ppr']:.1f} ({pos}{rw} this week) against {pos}{rs} on points per game so far"
                                            + ("; " + "; ".join(why) if why else "")})
            # waivers
            # a waiver target must be able to play: not on a reserve list and not ruled out (or doubtful) this week
            if (rank_t.get(x["pid"], 999) > WAIVER_N.get(pos, 30) and x["status"] not in OUT_STATUS
                    and x.get("inj") not in ("Out", "Doubtful", "IR") and (x.get("ros_g") or 0) >= 3):
                ros_pg = (x["ros_ppr"] or 0) / max(x["ros_g"] or 1, 1)
                trend = 0.0
                rs_ = []
                if pos in ("WR", "TE", "RB") and x.get("tgt_sh3") is not None and x.get("tgt_sh") is not None and x["tgt_sh3"] - x["tgt_sh"] >= 0.04:
                    trend += 1.5
                    rs_.append(f"target share {_pct(x['tgt_sh3'])} over the last three games (season {_pct(x['tgt_sh'])})")
                if pos == "RB" and x.get("car_sh3") is not None and x.get("car_sh") is not None and x["car_sh3"] - x["car_sh"] >= 0.08:
                    trend += 1.5
                    rs_.append(f"carry share {_pct(x['car_sh3'])} over the last three (season {_pct(x['car_sh'])})")
                if x.get("sos") and x["sos"] >= 1.05:
                    rs_.append("soft remaining schedule")
                out["waiver"].append({"pid": x["pid"], "pos": pos, "score": ros_pg + trend,
                                      "why": f"{ros_pg:.1f} PPR points a game projected for the rest of the season"
                                             + ("; " + "; ".join(rs_) if rs_ else "")})
            g = x.get("g") or 0
            if g >= 3 and x.get("xfp") is not None:
                diff = ((x["pts_ppr"] or 0) - x["xfp"]) / g
                tdd = (x.get("td") or 0) - (x.get("xtd") or 0)
                if pos != "QB" and x["xfp"] / g >= {"RB": 9, "WR": 9, "TE": 7}.get(pos, 9) and diff <= -2.0:
                    out["buy_low"].append({"pid": x["pid"], "pos": pos, "score": -diff,
                                           "why": f"usage worth {x['xfp'] / g:.1f} PPR points a game, scoring {(x['pts_ppr'] or 0) / g:.1f}"
                                                  + (f"; {_n(x['td'], 'TD')} on {x['xtd']:.1f} expected" if tdd <= -1 else "")})
                if pos != "QB" and diff >= 2.5 and tdd >= 1.5:
                    out["sell_high"].append({"pid": x["pid"], "pos": pos, "score": diff,
                                             "why": f"{_n(x['td'], 'TD')} on {x['xtd']:.1f} expected; scoring {(x['pts_ppr'] or 0) / g:.1f} a game on "
                                                    f"usage worth {x['xfp'] / g:.1f}"})
            if g >= 4 and pos in ("WR", "TE", "RB") and (x.get("ros_ppr") or 0) > 0:
                d_t = (x.get("tgt_sh3") or 0) - (x.get("tgt_sh") or 0)
                d_c = (x.get("car_sh3") or 0) - (x.get("car_sh") or 0)
                if d_t >= 0.05 or (pos == "RB" and d_c >= 0.10):
                    out["breakout"].append({"pid": x["pid"], "pos": pos, "score": d_t + 0.5 * d_c,
                                            "why": (f"target share up to {_pct(x['tgt_sh3'])} (season {_pct(x['tgt_sh'])})" if d_t >= 0.05 else
                                                    f"carry share up to {_pct(x['car_sh3'])} (season {_pct(x['car_sh'])})")})
    for key in ("start", "waiver", "buy_low", "sell_high", "breakout"):
        out[key] = sorted(out[key], key=lambda z: -z["score"])[:12]
        for z in out[key]:
            z["score"] = _r(z["score"], 2)
    for key, tab in (("dst", D), ("k", K)):
        xs = sorted(((t, v) for t, v in tab.items() if v.get("next") is not None), key=lambda tv: -(tv[1]["next"] or 0))[:8]
        for t, v in xs:
            wk = (v.get("weeks") or [[None, None, None]])[0]
            out[key].append({"team": t, "proj": v["next"], "opp": wk[1],
                             "why": f"projected {v['next']:.1f} against {wk[1]}; next four weeks " + ", ".join(f"{o} {p:.1f}" for _, o, p in v["weeks"])})
    return out


def current_backtest(S: int, w_now: int, P: dict) -> dict | None:
    """The walk-forward check of this season so far (weeks before w_now)."""
    if w_now <= 1:
        return None
    sd = SeasonData(S)
    rows = []
    for w in [x for x in sd.weeks() if x < w_now]:
        pr = backtest_week(sd, w, P)
        if len(pr):
            rows.append(pr[pr["pool"]])
    if not rows:
        return None
    bt = pd.concat(rows, ignore_index=True)
    return {"weeks": sorted(int(x) for x in bt["w"].unique()), "ppr": metrics(bt, "ppr")}
