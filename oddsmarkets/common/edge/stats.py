"""
Statistics: unit-stake edge tests, portfolio metrics, block bootstrap, permutation and market-null tests.

Unit-stake tests treat every row that passes the bet filters as a 1-unit bet. They answer "does this
selection rule have an edge?", free of sizing choices:

    mean CLV                 fair_close * price - 1; the expected return if the closing price is the truth
    % beating the close      price taken > closing price
    ROI                      mean profit per unit (pushes / half results settled exactly)
    CIs                      moving-block bootstrap over slates in time order (keeps within-slate and
                             short-range dependence), percentile intervals
    p (bootstrap)            one-sided H0: mean <= 0, from the recentred bootstrap distribution
    p (market null)          outcomes re-drawn from the de-vigged market (decision or close) jointly per
                             exclusive group: is the realised ROI more than the market itself implies?
    p (permutation)          model edges shuffled within slate (and segment), bets re-selected by the same
                             filter: does the model's ranking pick better bets than random picks from the same
                             slates? (selection skill; under the null, ROI is what the slate offers at random)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calibrate import to_seconds
from .devig import market_family


def _slate_order(slate: pd.Series, t: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Integer slate code ordered by first decision time; returns (codes per row, n_slates)."""
    first = pd.Series(to_seconds(t), index=slate.index).groupby(slate).min().sort_values(kind="stable")
    order = {k: i for i, k in enumerate(first.index)}
    return slate.map(order).to_numpy(np.int64), len(order)


def block_bootstrap_idx(n: int, B: int, block: int | None = None, seed: int = 7) -> np.ndarray:
    """B x n matrix of slate indices from a moving-block bootstrap (blocks of `block` consecutive slates)."""
    if n == 0:
        return np.zeros((B, 0), dtype=np.int64)
    L = block or max(1, int(round(n ** (1 / 3))))
    L = min(L, n)
    nb = int(np.ceil(n / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - L + 1, size=(B, nb))
    idx = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(B, -1)[:, :n]
    return idx


def ratio_bootstrap(x: np.ndarray, w: np.ndarray, codes: np.ndarray, n_slates: int, B: int = 2000,
                    seed: int = 7, block: int | None = None) -> dict:
    """
    Bootstrap of sum(w*x)/sum(w) with slates as the resampling unit (moving blocks in time order).
    Returns estimate, CI, se and the one-sided p-value for H0: mean <= 0.
    """
    ok = np.isfinite(x) & np.isfinite(w)
    x, w, codes = x[ok], w[ok], codes[ok]
    if len(x) == 0 or w.sum() <= 0:
        return {"est": np.nan, "lo": np.nan, "hi": np.nan, "se": np.nan, "p": np.nan, "n": 0}
    sx = np.bincount(codes, weights=w * x, minlength=n_slates)
    sw = np.bincount(codes, weights=w, minlength=n_slates)
    est = sx.sum() / sw.sum()
    idx = block_bootstrap_idx(n_slates, B, block, seed)
    bx = sx[idx].sum(axis=1)
    bw = sw[idx].sum(axis=1)
    bs = np.where(bw > 0, bx / np.where(bw > 0, bw, 1), np.nan)
    bs = bs[np.isfinite(bs)]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    p = (1 + np.sum(bs - est >= est)) / (len(bs) + 1)
    return {"est": float(est), "lo": float(lo), "hi": float(hi), "se": float(np.std(bs, ddof=1)), "p": float(p),
            "n": int(ok.sum())}


def market_null_p(bets: pd.DataFrame, full: pd.DataFrame, fair_col: str, B: int = 1000, seed: int = 11
                  ) -> dict:
    """
    p-value of the realised unit ROI under H0: outcomes follow the de-vigged market `fair_col`.
    Selections of one exclusive group are drawn jointly (one winner per group, or none of the listed ones for
    an incomplete group). Rows with fractional outcomes (pushes, half results) keep their realised profit.
    """
    b = bets[np.isfinite(bets[fair_col])]
    if not len(b):
        return {"p": np.nan, "null_mean": np.nan}
    f = full[np.isfinite(full[fair_col])]
    # cumulative probability bounds of each selection within its exclusive group
    f = f.sort_values(["excl_key", "selection"])
    pr = f[fair_col].to_numpy(float)
    grp = f["excl_key"].to_numpy()
    tot = pd.Series(pr).groupby(grp).transform("sum").to_numpy()
    pr_n = np.where(tot > 1.0, pr / tot, pr)
    cum_hi = pd.Series(pr_n).groupby(grp).cumsum().to_numpy()
    cum_lo = cum_hi - pr_n
    bounds = pd.DataFrame({"lo": cum_lo, "hi": cum_hi}, index=f.index)
    b = b.join(bounds, how="left")
    b_lo = b["lo"].fillna(0.0).to_numpy()
    b_hi = b["hi"].fillna(b[fair_col]).to_numpy()
    gcodes = pd.factorize(b["outcome_key"] if "outcome_key" in b else b["excl_key"])[0]
    G = gcodes.max() + 1
    o = b["price_dec"].to_numpy(float)
    frac = ~b["outcome"].isin([0.0, 1.0]).to_numpy()
    fixed = b["profit_unit"].to_numpy(float)
    obs = float(np.mean(fixed))
    rng = np.random.default_rng(seed)
    sims = np.empty(B)
    for k in range(B):
        u = rng.random(G)[gcodes]
        win = (u >= b_lo) & (u < b_hi)
        prof = np.where(win, o - 1.0, -1.0)
        prof = np.where(frac, fixed, prof)
        sims[k] = prof.mean()
    return {"p": float((1 + np.sum(sims >= obs)) / (B + 1)), "null_mean": float(sims.mean()),
            "null_sd": float(sims.std(ddof=1))}


def permutation_p(rows: pd.DataFrame, select, stat_col: str = "profit_unit", within=("slate",), B: int = 400,
                  seed: int = 3) -> dict:
    """
    Shuffle the model's probability-derived edge among rows of the same slate (and `within` keys), re-apply
    the selection rule `select(edge_array, rows) -> bool mask`, and compare mean `stat_col` of the selected
    rows to the observed selection. One-sided p: P(perm >= observed).
    """
    r = rows[np.isfinite(rows[stat_col])]
    if not len(r):
        return {"p": np.nan}
    edge = r["edge"].to_numpy(float)
    stat = r[stat_col].to_numpy(float)
    m0 = select(edge, r)
    if not m0.any():
        return {"p": np.nan}
    obs = stat[m0].mean()
    key = r[list(within)].astype(str).agg("|".join, axis=1) if len(within) > 1 else r[within[0]].astype(str)
    codes = pd.factorize(key)[0]
    rng = np.random.default_rng(seed)
    sims = []
    order0 = np.argsort(codes, kind="stable")
    sc = codes[order0]
    for _ in range(B):
        rnd = rng.random(len(r))
        perm = np.lexsort((rnd, codes))  # rows sorted by group, random within group
        pe = np.empty_like(edge)
        pe[order0] = edge[perm]          # position j of group-sorted order receives a random edge of that group
        m = select(pe, r)
        if m.any():
            sims.append(stat[m].mean())
    sims = np.asarray(sims)
    del sc
    if not len(sims):
        return {"p": np.nan}
    return {"p": float((1 + np.sum(sims >= obs)) / (len(sims) + 1)), "null_mean": float(sims.mean()),
            "obs": float(obs)}


def holm(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.flatnonzero(np.isfinite(p))
    if not len(ok):
        return out.tolist()
    order = ok[np.argsort(p[ok])]
    m = len(order)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        out[i] = running
    return out.tolist()


# ------------------------------------------------------------------------------------------- unit-stake test


def unit_test(rows: pd.DataFrame, full: pd.DataFrame | None = None, B: int = 2000, perm_B: int = 300,
              select=None, within=("slate",), do_perm: bool = True, do_null: bool = True, seed: int = 7) -> dict:
    """All unit-stake edge statistics for a set of selected bets `rows` (subset of `full`)."""
    out = {"n": len(rows)}
    if not len(rows):
        return out
    codes, ns = _slate_order(rows["slate"], rows["decision_time"])
    one = np.ones(len(rows))
    roi = ratio_bootstrap(rows["profit_unit"].to_numpy(float), one, codes, ns, B, seed)
    out.update({"roi": roi["est"], "roi_lo": roi["lo"], "roi_hi": roi["hi"], "p_roi": roi["p"]})
    has_close = rows["clv"].notna()
    out["n_clv"] = int(has_close.sum())
    moved = (rows["price_close"].notna() & (np.abs(rows["price_close"] - rows["price_dec"]) > 1e-9))
    out["close_differs"] = float(moved[has_close].mean()) if has_close.any() else np.nan
    # what the CLV rests on: bets whose spread/total line moved before the close get no CLV (calibrate.prepare); of
    # those with a close, how many were taken at the closing price itself (CLV = minus the margin) or have only a
    # supplied closing probability (no closing price, so movement cannot be checked)
    lm = rows["line_moved"].fillna(False).astype(bool) if "line_moved" in rows else pd.Series(False, index=rows.index)
    out["n_line_moved"] = int(lm.sum())
    out["n_no_close"] = int((~has_close & ~lm).sum())
    out["n_close_same"] = int((has_close & rows["price_close"].notna() & ~moved).sum())
    out["n_close_noprice"] = int((has_close & rows["price_close"].isna()).sum())
    if has_close.any():
        clv = ratio_bootstrap(rows["clv"].to_numpy(float), one, codes, ns, B, seed + 1)
        out.update({"clv": clv["est"], "clv_lo": clv["lo"], "clv_hi": clv["hi"], "p_clv": clv["p"]})
        bc = rows["beat_close"].dropna()
        out["beat_close"] = float(bc.mean()) if len(bc) else np.nan
        # price jumps open->close of more than 25% in log terms: on a spread/total usually a different line
        jump = np.abs(np.log(rows["price_close"] / rows.get("price_gross", rows["price_dec"]))) > 0.25
        fam = rows["market"].map(market_family)
        jump = jump & has_close & fam.isin(["spread", "total"])
        out["big_move_share"] = float(jump[has_close].mean())
        rest = rows.loc[has_close & ~jump, "clv"]
        out["clv_ex_big"] = float(rest.mean()) if len(rest) else np.nan
    pu = rows["profit_unit"].to_numpy(float)
    out["sharpe_bet"] = float(pu.mean() / pu.std(ddof=1)) if len(pu) > 1 and pu.std() > 0 else np.nan
    out["avg_price"] = float(rows["price_dec"].mean())
    out["avg_edge"] = float(rows["edge"].mean()) if "edge" in rows else np.nan
    out["avg_edge_raw"] = float(rows["edge_raw"].mean())
    out["hit"] = float((rows["outcome"] >= 0.75).mean())
    m = rows.groupby(rows["decision_time"].dt.strftime("%Y-%m"))["profit_unit"].sum()
    out["months"] = len(m)
    out["pos_months"] = float((m > 0).mean()) if len(m) else np.nan
    if do_null and full is not None:
        nd = market_null_p(rows, full, "fair_dec", B=min(B, 1000), seed=seed + 2)
        out["p_null_dec"] = nd["p"]
        out["null_dec_mean"] = nd.get("null_mean", np.nan)
        if has_close.any():
            nc = market_null_p(rows[has_close], full, "fair_close", B=min(B, 1000), seed=seed + 3)
            out["p_null_close"] = nc["p"]
    if do_perm and full is not None and select is not None:
        pool = full[full["slate"].isin(rows["slate"].unique())]
        for k in within:
            pool = pool[pool[k].isin(rows[k].unique())]
        pp = permutation_p(pool, select, "profit_unit", within=within, B=perm_B, seed=seed + 4)
        out["p_perm"] = pp["p"]
        if has_close.any():
            pc = permutation_p(pool[pool["clv"].notna()], select, "clv", within=within, B=perm_B, seed=seed + 5)
            out["p_perm_clv"] = pc["p"]
    return out


# ------------------------------------------------------------------------------------------- portfolio metrics


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return np.nan
    peak = np.maximum.accumulate(equity)
    return float(np.max(1.0 - equity / peak))


def portfolio_metrics(sim, B: int = 1000, ruin_levels=(0.5, 0.2), seed: int = 5) -> dict:
    led, eq, sl = sim.ledger, sim.equity, sim.slates
    out = {"strategy": sim.cfg.label(), "n_bets": len(led)}
    if not len(led):
        return out
    staked = led["stake"].sum()
    profit = led["profit"].sum()
    out["staked"] = float(staked)
    out["profit"] = float(profit)
    out["roi"] = float(profit / staked) if staked > 0 else np.nan
    out["final_mult"] = sim.final / sim.initial
    out["log_growth"] = float(np.log(max(sim.final, 1e-12) / sim.initial))
    e = eq["equity"].to_numpy(float)
    out["max_dd"] = max_drawdown(e)
    mean_eq = float(np.mean(e))
    out["turnover"] = float(staked / mean_eq) if mean_eq > 0 else np.nan
    span_y = max((led["decision_time"].max() - led["decision_time"].min()).total_seconds() / (365.25 * 86400), 1e-9)
    out["years"] = span_y
    out["cagr_log"] = out["log_growth"] / span_y
    out["avg_stake_frac"] = float(led["frac"].mean())
    w = led["stake"].to_numpy()
    if led["clv"].notna().any():
        m = led["clv"].notna().to_numpy()
        out["clv_w"] = float(np.average(led["clv"].to_numpy()[m], weights=w[m]))
        bc = led["beat_close"].dropna()
        out["beat_close"] = float(bc.mean()) if len(bc) else np.nan
    r = led["profit_unit"].to_numpy(float)
    out["sharpe_bet"] = float(r.mean() / r.std(ddof=1)) if len(r) > 1 and r.std() > 0 else np.nan
    # monthly: equity at month ends
    s = eq.set_index("time")["equity"]
    me = s.resample("ME").last().ffill()
    me = pd.concat([pd.Series([sim.initial], index=[me.index[0] - pd.offsets.MonthEnd(1)]), me])
    mr = me.pct_change().dropna()
    out["months"] = len(mr)
    if len(mr) > 1 and mr.std() > 0:
        out["sharpe_month_ann"] = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12))
        out["pos_months"] = float((mr > 0).mean())
    # bootstrap of slate log-returns: CI on log growth and risk of ruin
    if len(sl) and "logret" in sl:
        lr = sl["logret"].to_numpy(float)
        n = len(lr)
        idx = block_bootstrap_idx(n, B, seed=seed)
        paths = np.cumsum(lr[idx], axis=1)
        tot = paths[:, -1]
        out["log_growth_lo"], out["log_growth_hi"] = (float(x) for x in np.percentile(tot, [2.5, 97.5]))
        out["log_growth_p5"] = float(np.percentile(tot, 5))
        mins = np.minimum(paths.min(axis=1), 0.0)
        for lv in ruin_levels:
            out[f"p_below_{int(lv * 100)}"] = float(np.mean(mins <= np.log(lv)))
        dd = 1.0 - np.exp(paths - np.maximum.accumulate(np.maximum(paths, 0.0), axis=1))
        out["max_dd_p95"] = float(np.percentile(dd.max(axis=1), 95))
        out["p_loss"] = float(np.mean(tot < 0))
    return out
