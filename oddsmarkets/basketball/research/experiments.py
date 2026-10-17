"""
Experiment log for the basketball edge research (scripts/bb_edge.py experiments).

Split: tuning seasons (NBA 2012-2023, WNBA 2010-2023; outcome and closing-line data only) choose features and
hyper-parameters; test seasons are the ones with ESPN open AND close prices (2024-2026 in both leagues). Every
fit is walk-forward by season (fit on seasons < s, predict s); within a season inputs use games of US days <= D-1.

Predictors of the home margin / total at the decision (the morning of game day; ESPN's open price):
  M0   production game model (ratings + home + rest / b2b / travel / tz / altitude), daily refit
  M1   M0 + availability delta (expected rotation from last game's participation x last season's player values)
  T0   ratings total;  T2 = T0 + roster O/D delta, rest, b2b, altitude, playoffs, early season
  MK   market ratings from past closing lines (half-life 10 days, ridge 1; market_ratings.py)
  C    close predictor: closing line ~ MK + M1 (or T2), fitted on earlier seasons' CLOSES only (no opens needed)
  C2   C shrunk towards the open: close ~ open + k (C - open), k fitted on earlier OPEN-era seasons (2024 trains
       2025, 2024-25 train 2026; 2024 itself uses k = 1)
Bets: EV at the predictor's probability vs the open price above a threshold; scored by CLV (closing fair
probability at the open line) and realised ROI with day-clustered bootstrap CIs.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.research import evaluate as V
from oddsmarkets.basketball.research import lines as LN
from oddsmarkets.basketball.research import market_ratings as MR
from oddsmarkets.basketball.research import markets as M

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "edge"
TUNE = {"nba": (2012, 2023), "wnba": (2010, 2023)}
TEST = (2024, 2025, 2026)
M1_FEATS = V.MARGIN_BASE + ["x_dSl"]
T2_FEATS = ["base_total", "x_tot_dS", "x_rest_sum", "x_b2b_sum", "x_alt_tot", "x_post", "x_early"]
MK_HL, MK_RIDGE = 10.0, 1.0
C_SP_FEATS = ["mk_mu", "rating", "x_dSl", "b2b", "rest", "travel_1000km", "tz", "altitude", "hca"]
C_TOT_FEATS = ["mk_tot", "base_total", "x_tot_dS", "x_b2b_sum", "x_rest_sum", "x_early", "x_post", "x_alt_tot", "lg_pace", "lg_ortg"]
THRESHOLDS = (0.0, 0.01, 0.02, 0.03, 0.05)


def table(league: str, lag: int = 1, garbage: bool = False, roster: bool = False) -> pd.DataFrame:
    p = _io.cache_root() / "edge" / f"{league}_lag{lag}{'_gb' if garbage else ''}{'_roster' if roster else ''}.parquet"
    return attach_lines(pd.read_parquet(p), league)


def attach_lines(df: pd.DataFrame, league: str) -> pd.DataFrame:
    """(Re)attach open / close columns from the line cache, so tables need no rebuild after a fetch."""
    d = df.copy()
    for s in sorted(d.season.unique()):
        ln = LN.game_lines(league, int(s))
        if not ln:
            continue
        m = d.season == s
        ids = d.loc[m, "event_id"]
        for when in ("open", "close"):
            for k in ("ml_h", "ml_a", "sp_h", "spo_h", "spo_a", "tot", "over", "under"):
                d.loc[m, f"{when}_{k}"] = ids.map(lambda g, w=when, kk=k: (((ln.get(g) or {}).get(w)) or {}).get(kk)).astype(float)
        d.loc[m, "line_src"] = ids.map(lambda g: (ln.get(g) or {}).get("src"))
    return d


def sigmas(df: pd.DataFrame, league: str) -> tuple[float, float]:
    """sd of (margin + close spread) and (total - close total) on the tuning seasons."""
    a, b = TUNE[league]
    t = df[(df.season >= a) & (df.season <= b)]
    sp = t["close_sp_h"].where(t["close_sp_h"].notna(), t["store_sp_h"])
    tt = t["close_tot"].where(t["close_tot"].notna(), t["store_tot"])
    m = sp.notna()
    mt = tt.notna()
    sig_m = float(np.sqrt(np.mean((t.margin[m] + sp[m]) ** 2))) if m.sum() > 200 else (12.55 if league == "nba" else 12.3)
    sig_t = float(np.sqrt(np.mean((t.total_pts[mt] - tt[mt]) ** 2))) if mt.sum() > 200 else (18.3 if league == "nba" else 15.5)
    return sig_m, sig_t


def _close_cols(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["cl_sp"] = d["close_sp_h"].where(d["close_sp_h"].notna(), d["store_sp_h"])
    d["cl_tot"] = d["close_tot"].where(d["close_tot"].notna(), d["store_tot"])
    return d


def build_predictions(df: pd.DataFrame, league: str, lag: int = 1) -> pd.DataFrame:
    """Walk-forward predictions for every season after the first tuning season."""
    a, _ = TUNE[league]
    seasons = sorted(s for s in df.season.unique() if s >= a)
    d = V.prep(_close_cols(df))
    w0 = V.walk_forward(d, V.MARGIN_BASE, "margin", seasons)
    w1 = V.walk_forward(d, M1_FEATS, "margin", seasons)
    t0 = V.walk_forward(d, ["base_total"], "total_pts", seasons, intercept=True)
    t2 = V.walk_forward(d, T2_FEATS, "total_pts", seasons, intercept=True)
    out = w1.drop(columns=["pred", "sigma", "coef"]).copy()
    out["mu1"], out["sd1"] = w1["pred"].to_numpy(), w1["sigma"].to_numpy()
    out["mu0"], out["sd0"] = w0["pred"].to_numpy(), w0["sigma"].to_numpy()
    out["mut0"] = t0["pred"].to_numpy()
    out["mut"], out["sdt"] = t2["pred"].to_numpy(), t2["sigma"].to_numpy()
    mk = MR.fit(_close_cols(df), half_life=MK_HL, ridge=MK_RIDGE, lag=lag).set_index("event_id")
    out["mk_mu"] = out.event_id.map(mk.mk_mu)
    out["mk_tot"] = out.event_id.map(mk.mk_tot)
    # close predictor C (feature sets chosen on the tuning seasons by RMSE against the close), walk-forward on
    # the CLOSE lines of earlier seasons:  -close spread ~ C_SP_FEATS,  close total ~ C_TOT_FEATS
    out["y_sp"] = -out["cl_sp"]
    out["c_mu"] = np.nan
    out["c_tot"] = np.nan
    have = out.dropna(subset=["mk_mu"])
    w = V.walk_forward(have, C_SP_FEATS, "y_sp", seasons, intercept=True)
    out.loc[w.index, "c_mu"] = w["pred"]
    have = out.dropna(subset=["mk_tot"])
    w = V.walk_forward(have, C_TOT_FEATS, "cl_tot", seasons, intercept=True)
    out.loc[w.index, "c_tot"] = w["pred"]
    out["c_mu"] = out["c_mu"].fillna(out["mu1"])
    out["c_tot"] = out["c_tot"].fillna(out["mut"])
    return out


def add_c2(p: pd.DataFrame) -> pd.DataFrame:
    """C2: open + k (C - open), k = slope of (close - open) on (C - open) over earlier open-era seasons (1 if none)."""
    p = p.copy()
    for col, op, cl, name in (("c_mu", "open_mu_sp", "close_mu_sp", "c2_mu"), ("c_tot", "open_mu_tot", "close_mu_tot", "c2_tot")):
        p[name] = np.nan
        p[f"k_{name}"] = np.nan
        for s in sorted(p.season.unique()):
            te = p.season == s
            tr = p[(p.season < s)].dropna(subset=[col, op, cl])
            k = 1.0
            if len(tr) > 300:
                b, _ = V.ols((tr[col] - tr[op]).to_numpy(), (tr[cl] - tr[op]).to_numpy(), const=False)
                k = float(b[0])
            p.loc[te, name] = p.loc[te, op] + k * (p.loc[te, col] - p.loc[te, op])
            p.loc[te, f"k_{name}"] = k
        p[name] = p[name].fillna(p[col])              # no open line of that kind: C itself
    return p


def move_slopes(p: pd.DataFrame) -> list[dict]:
    rows = []
    for pred, op, cl, out_col, lab in (("mu0", "open_mu_sp", "close_mu_sp", "margin", "M0 spread"),
                                       ("mu1", "open_mu_sp", "close_mu_sp", "margin", "M1 spread"),
                                       ("mk_mu", "open_mu_sp", "close_mu_sp", "margin", "MK spread"),
                                       ("c_mu", "open_mu_sp", "close_mu_sp", "margin", "C spread"),
                                       ("mut0", "open_mu_tot", "close_mu_tot", "total_pts", "T0 total"),
                                       ("mut", "open_mu_tot", "close_mu_tot", "total_pts", "T2 total"),
                                       ("mk_tot", "open_mu_tot", "close_mu_tot", "total_pts", "MK total"),
                                       ("c_tot", "open_mu_tot", "close_mu_tot", "total_pts", "C total")):
        x = p.dropna(subset=[pred, op, cl])
        if len(x) < 50:
            continue
        dis = (x[pred] - x[op]).to_numpy()
        b, se = V.ols(dis, (x[cl] - x[op]).to_numpy(), x.day.astype(str))
        bo, so = V.ols(dis, (x[out_col] - x[op]).to_numpy(), x.day.astype(str))
        rows.append({"predictor": lab, "n": len(x), "sd_disagreement": float(dis.std()), "move_slope": float(b[1]),
                     "move_se": float(se[1]), "outcome_slope": float(bo[1]), "outcome_se": float(so[1]),
                     "rmse_vs_close": float(np.sqrt(np.mean((x[pred] - x[cl]) ** 2))),
                     "open_rmse_vs_close": float(np.sqrt(np.mean((x[op] - x[cl]) ** 2)))})
    return rows


def ml_scores(p: pd.DataFrame, sig_m: float) -> list[dict]:
    """Log-loss on the outcome (home win) on games with open AND close moneylines, paired against the open."""
    x = p.dropna(subset=["open_p_ml", "close_p_ml"]).copy()
    if x.empty:
        return []
    y = (x.margin > 0).astype(float).to_numpy()
    cands = {"open (de-vigged)": x.open_p_ml.to_numpy(), "close (de-vigged)": x.close_p_ml.to_numpy(),
             "M0": norm.cdf(x.mu0 / x.sd0), "M1": norm.cdf(x.mu1 / x.sd1),
             "C (close predictor)": norm.cdf(x.c_mu / sig_m), "C2": norm.cdf(x.c2_mu / sig_m)}
    if x.elo_p.notna().all():
        cands["Elo"] = x.elo_p.to_numpy()
    out = []
    for k, v in cands.items():
        v = np.asarray(v, float)
        d = V.paired_ll_diff(v, x.open_p_ml.to_numpy(), y, x.day.astype(str))
        out.append({"forecast": k, "n": len(x), "logloss": V.logloss(v, y), "brier": V.brier(v, y),
                    "minus_open": d[0], "lo": d[1], "hi": d[2]})
    return out


def bet_tables(p: pd.DataFrame, sig_m: float, sig_t: float) -> dict[str, pd.DataFrame]:
    """Selections at the open for each edge source; returns {source: selections}."""
    p = p.copy()
    p["sig_m"] = sig_m
    p["sig_t"] = sig_t
    srcs = {"M1/T2 raw": ("mu1", "sd1", "mut", "sdt"), "M0/T0 raw": ("mu0", "sd0", "mut0", "sdt"),
            "C": ("c_mu", "sig_m", "c_tot", "sig_t"), "C2": ("c2_mu", "sig_m", "c2_tot", "sig_t")}
    out = {}
    for k, (a, b, c, d) in srcs.items():
        q = p.dropna(subset=[a])
        out[k] = M.selections(q, a, b, c, d, sig_m, sig_t)
    return out


def run_league(league: str, lag: int = 1, roster: bool = False) -> dict:
    df = table(league, lag, roster=roster)
    sig_m, sig_t = sigmas(df, league)
    pr = build_predictions(df, league, lag)
    test = pr[pr.season.isin(TEST)]
    test = test[test.open_sp_h.notna() | test.open_ml_h.notna() | test.open_tot.notna()]
    test = M.add_market_means(test, sig_m, sig_t)
    # C2 needs the open / close implied means on every open-era season
    test = add_c2(test)
    res = {"league": league, "lag": lag, "roster_prior": roster, "sig_m": sig_m, "sig_t": sig_t, "n_test_games": int(len(test)),
           "test_by_season": test.groupby("season").size().to_dict(),
           "line_src": test.line_src.value_counts().to_dict(),
           "k_c2": test.groupby("season")[["k_c2_mu", "k_c2_tot"]].first().to_dict()}
    res["move_slopes"] = move_slopes(test)
    res["ml_scores"] = ml_scores(test, sig_m)
    sels = bet_tables(test, sig_m, sig_t)
    bets = {}
    for src, s in sels.items():
        if s.empty:
            continue
        tabs = []
        for thr in THRESHOLDS:
            tabs.append(M.summarize(s, thr, by=["market"]))
            tabs.append(M.summarize(s, thr).assign(market="all"))
        bets[src] = pd.concat(tabs).to_dict("records")
    res["bets"] = bets
    # strata for C2 at thr 0.01: season, early season, playoffs
    s = sels.get("C2")
    if s is not None and not s.empty:
        s = s.copy()
        s["phase"] = np.where(s.stype == "post", "playoffs", np.where(s.gp < 20, "early (<10 games each)", "regular"))
        s["fav"] = np.where(s.price_dec < 2.0, "favourite side", "underdog side")
        res["bankroll"] = {f"{mk}_thr{thr}": bankroll(s, thr=thr, markets=None if mk == "all" else [mk])
                           for mk in ("all", "moneyline", "spread", "total") for thr in (0.02, 0.05)}
        res["strata"] = {"season": M.summarize(s, 0.01, by=["season", "market"]).to_dict("records"),
                         "fav": M.summarize(s, 0.01, by=["market", "fav"]).to_dict("records"),
                         "phase": M.summarize(s, 0.01, by=["phase", "market"]).to_dict("records"),
                         "book": M.summarize(s, 0.01, by=["price_src_book", "market"]).to_dict("records")}
    # Kalshi game-winner markets at the same decision time (C2 and raw M1 probabilities)
    try:
        res["kalshi"] = kalshi_results(test, league, sig_m)
        res["kalshi_24h"] = kalshi_results(test, league, sig_m, hours_before=24)
        res["kalshi_36h"] = kalshi_results(test, league, sig_m, hours_before=36)
    except Exception as exc:  # noqa: BLE001
        res["kalshi"] = {"error": str(exc)}
    return {"result": res, "test": test, "selections": sels}


def kalshi_results(test: pd.DataFrame, league: str, sig_m: float, hours_before: float | None = None) -> dict:
    from oddsmarkets.basketball.models import _games as G
    from oddsmarkets.basketball.research import kalshi as K
    t = test.copy()
    t["p_c2"] = norm.cdf(t["c2_mu"] / sig_m)
    t["p_c"] = norm.cdf(t["c_mu"] / sig_m)
    t["p_raw"] = norm.cdf(t["mu1"] / t["sd1"])
    abbr = {}
    for s in t.season.unique():
        st = G.load_store(league, int(s)) or {}
        abbr[int(s)] = {k: (v or {}).get("abbr") for k, v in (st.get("teams") or {}).items()}
    k = K.load(league, t, abbr, hours_before=hours_before)
    if k.empty:
        return {"n_games": 0}
    out = {"n_games": int(len(k)), "n_with_decision_quote": int(k.dec_ask_h.notna().sum()),
           "median_spread_cents_decision": float(((k.dec_ask_h - k.dec_bid_h) * 100).median()),
           "median_open_interest_decision": float(k.dec_oi.median()) if k.dec_oi.notna().any() else None}
    x = k.merge(t[["event_id", "open_p_ml", "close_p_ml", "margin"]], on="event_id", how="left").dropna(subset=["dec_ask_h"])
    y = (x.margin > 0).astype(float).to_numpy()
    mid = ((x.dec_ask_h + x.dec_bid_h) / 2).to_numpy()
    out["logloss_kalshi_mid_decision"] = V.logloss(mid, y)
    out["logloss_kalshi_mid_close"] = V.logloss(x.close_mid_h.to_numpy(), y)
    xx = x.dropna(subset=["close_p_ml"])
    out["logloss_espn_close_same_games"] = V.logloss(xx.close_p_ml.to_numpy(), (xx.margin > 0).astype(float).to_numpy())
    out["logloss_kalshi_close_same_games"] = V.logloss(xx.close_mid_h.to_numpy(), (xx.margin > 0).astype(float).to_numpy())
    tabs = {}
    for col in ("p_c2", "p_c", "p_raw"):
        sel = K.selections(k, t, col)
        if sel.empty:
            continue
        tabs[col] = pd.concat([M.summarize(sel, thr).assign(market="kalshi") for thr in THRESHOLDS]).to_dict("records")
    out["bets"] = tabs
    return out


def run_all(leagues) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    allres = {}
    for lg in leagues:
        for lag, roster in ((1, False), (2, False), (1, True)):
            p = _io.cache_root() / "edge" / f"{lg}_lag{lag}{'_roster' if roster else ''}.parquet"
            if not p.exists():
                continue
            r = run_league(lg, lag, roster)
            allres[f"{lg}_lag{lag}{'_roster' if roster else ''}"] = r["result"]
            print(json.dumps({k: v for k, v in r["result"].items() if k in ("league", "lag", "n_test_games", "sig_m", "sig_t")}), flush=True)
    (OUT / "basketball_experiments.json").write_text(json.dumps(allres, default=_js, indent=1), "utf-8")


def _js(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    return str(o)


def bankroll(sel: pd.DataFrame, thr: float = 0.02, kelly: float = 0.25, haircut: float = 0.5, cap: float = 0.02,
             markets=None) -> dict:
    """Simple sequential backtest of the selections (one side per game-market, the larger edge): bets placed at
    the decision, settled after the game, bankroll updated day by day. Edge haircut: p = fair_open +
    haircut x (model_p - fair_open); stake = kelly x Kelly fraction x bankroll, capped at `cap` of the bankroll
    per bet; flat = 1 unit a bet. Returns P&L, ROI, max drawdown for both."""
    x = sel[sel["model_ev"] > thr].copy()
    if markets:
        x = x[x.market.isin(markets)]
    x = x.sort_values("model_ev", ascending=False).drop_duplicates(["event_id", "market"]).sort_values("day")
    if x.empty:
        return {"n": 0}
    pw = x["fair_p_decision"] + haircut * (x["model_p"] - x["fair_p_decision"])
    push = x["model_push"].fillna(0)
    b = x["price_dec"] - 1
    f = ((pw * b - (1 - pw - push)) / b).clip(lower=0)
    x["f"] = f
    bank, peak, mdd = 1.0, 1.0, 0.0
    flat_cum, flat_peak, flat_mdd = 0.0, 0.0, 0.0
    staked = 0.0
    for d, g in x.groupby("day", sort=True):
        stakes = (kelly * g["f"]).clip(upper=cap) * bank
        tot = stakes.sum()
        if tot > 0.25 * bank:                            # at most a quarter of the bankroll on one day
            stakes *= 0.25 * bank / tot
        staked += stakes.sum()
        bank += float((stakes * g["profit"]).sum())
        peak = max(peak, bank)
        mdd = max(mdd, 1 - bank / peak)
        flat_cum += float(g["profit"].sum())
        flat_peak = max(flat_peak, flat_cum)
        flat_mdd = max(flat_mdd, flat_peak - flat_cum)
    roi = V.boot_ci(x["profit"].to_numpy(), x["day"].astype(str).to_numpy())
    return {"n": int(len(x)), "flat_units": flat_cum, "flat_roi": roi[0], "flat_roi_lo": roi[1], "flat_roi_hi": roi[2],
            "flat_max_drawdown_units": flat_mdd, "kelly_final_bankroll": bank, "kelly_turnover": staked,
            "kelly_roi_on_turnover": (bank - 1) / staked if staked else None, "kelly_max_drawdown": mdd,
            "mean_clv": float(x["clv"].mean())}
