"""
The full edge analysis and the EDGE_RESULTS.md writer (driven by scripts/edge_backtest.py).

`analyse(df, opts)` runs: prepare -> walk-forward shrinkage -> unit-stake edge tests per sport and market (and the
raw, unshrunk model for comparison) -> breakdowns -> bankroll simulations per sport and combined, strategy
comparison and Kelly-fraction grid -> recommendation. `write_markdown(res, path)` renders it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import simulate
from .calibrate import fit_blend, logit, prepare, walk_forward_shrink
from .devig import DEFAULT_METHOD
from .kelly import SizingConfig, candidates
from .stats import holm, portfolio_metrics, unit_test

EDGE_BUCKETS = [0.0, 0.02, 0.04, 0.07, 0.12, np.inf]
LEAD_BUCKETS = [0, 1, 6, 24, 72, 168, np.inf]
LEAD_LABELS = ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", ">7d"]
FRACTIONS = [0.1, 0.2, 0.25, 0.33, 0.5]


@dataclass
class Options:
    devig: str = DEFAULT_METHOD
    sizing: SizingConfig = field(default_factory=SizingConfig)
    k_prior: float = 200.0
    min_train: int = 200
    B: int = 2000
    perm_B: int = 300
    sim_B: int = 1000
    breakdown_B: int = 500
    settle_lag_hours: float = 24.0
    initial: float = 10_000.0
    grid: bool = True
    min_bets_verdict: int = 50


# ----------------------------------------------------------------------------------------------- analysis


def _selector(cfg: SizingConfig):
    def sel(edge, r):
        pcol = "q" if cfg.use_shrunk else "model_p"
        return ((edge >= cfg.min_edge) & (r[pcol].to_numpy() >= cfg.min_prob)
                & (r["price_dec"].to_numpy() <= cfg.max_price) & ~r["warmup"].to_numpy())
    return sel


def selected(d: pd.DataFrame, cfg: SizingConfig) -> pd.Series:
    return candidates(d, cfg) & ~d["warmup"].astype(bool)


CLV_MIN_SHARE = 0.5      # CLV is the primary test only when at least this share of the bets has a same-line close
CLOSE_MOVED_MIN = 0.2    # ... and more than this share of those closes differs from the price taken


def clv_usable(u: dict) -> bool:
    """CLV is a test of the bets only when most of them have a close for the line bet and the close is not, for
    most of them, the very price taken (bets placed at the close have CLV = minus the margin by construction)."""
    n = u.get("n", 0) or 0
    return (u.get("n_clv", 0) or 0) >= CLV_MIN_SHARE * max(n, 1) and (u.get("close_differs") or 0) > CLOSE_MOVED_MIN


def clv_basis(u: dict) -> str:
    """What the CLV figure rests on, for the table: bets with a same-line close, and spreads/totals voided because
    their line moved."""
    n, k = int(u.get("n", 0) or 0), int(u.get("n_clv", 0) or 0)
    lm = int(u.get("n_line_moved", 0) or 0)
    return f"{k:,} of {n:,}" + (f"; {lm:,} line moved" if lm else "")


def no_clv_reason(u: dict) -> str:
    """Why the CLV in the table is not the test (the verdict's wording when `clv_usable` is False)."""
    n, k = int(u.get("n", 0) or 0), int(u.get("n_clv", 0) or 0)
    lm, nc = int(u.get("n_line_moved", 0) or 0), int(u.get("n_no_close", 0) or 0)
    why = []
    if lm:
        why.append(f"{lm:,} are spreads/totals whose line moved before the close, and the portfolio layer gives those "
                   f"no CLV (their closing price is for another line)")
    if nc:
        why.append(f"{nc:,} have no closing price")
    if k == 0:
        return "No CLV: no bet has a closing price for the line bet" + (f" ({'; '.join(why)})" if why else "") + "."
    clv = (f"The table's CLV ({u['clv']:+.2%})" if isinstance(u.get("clv"), float) and np.isfinite(u["clv"])
           else "The table's CLV")
    if k < CLV_MIN_SHARE * max(n, 1):
        return (f"CLV not used as the test: only {k:,} of the {n:,} bets ({k / n:.0%}) have a closing price for the "
                f"line bet" + (f"; {'; '.join(why)}" if why else "") + f". {clv} rests on those {k:,} bets only.")
    same, noprice = int(u.get("n_close_same", 0) or 0), int(u.get("n_close_noprice", 0) or 0)
    how = []
    if same:
        how.append(f"{same:,} of the {k:,} bets with a close were taken at the closing price itself, so their CLV is "
                   f"just minus the bookmaker's margin")
    if noprice:
        how.append(f"{noprice:,} of the {k:,} closes are a supplied closing probability without a closing price, so "
                   f"whether the price moved cannot be checked")
    cd = u.get("close_differs")
    pct = ("under 1%" if isinstance(cd, float) and 0 < cd < 0.005 else f"{cd:.0%}") if isinstance(cd, float) else ""
    moved = (f" (the closing price differs from the price taken for {pct} of the {k:,} bets with a close)"
             if isinstance(cd, float) and np.isfinite(cd) and same > noprice else "")
    what = ("is mostly the margin, not a test of the model" if same >= noprice
            else "cannot be read as a test of the model")
    return (f"CLV not used as the test{moved}: {'; '.join(how)}. {clv} {what}."
            + (f" {lm:,} spread/total bets get no CLV because their line moved before the close." if lm else ""))


def verdict(u: dict, p_holm: float, min_bets: int = 50) -> tuple[str, str]:
    """(code, sentence). Codes: EDGE, LIKELY, NONE, NEGATIVE, THIN."""
    n = u.get("n", 0)
    if n < min_bets:
        return "THIN", f"Too few bets ({n}) to judge."
    clv_ok = clv_usable(u)
    roi_sig = (u.get("roi_lo", -1) or -1) > 0
    holm_txt = "" if not np.isfinite(p_holm) else (" Survives the Holm multiple-testing correction."
                                                  if p_holm < 0.05 else
                                                  " Does not survive the Holm multiple-testing correction.")
    luck = " The positive ROI without CLV is treated as luck." if roi_sig else ""
    if clv_ok:
        c = f"CLV {u['clv']:+.2%} [{u['clv_lo']:+.2%}, {u['clv_hi']:+.2%}]"
        lm = int(u.get("n_line_moved", 0) or 0)
        part = (f" CLV rests on {int(u['n_clv']):,} of the {n:,} bets: {lm:,} spreads/totals get none because their "
                f"line moved before the close." if lm else "")
        r = f"ROI {u['roi']:+.2%} [{u['roi_lo']:+.2%}, {u['roi_hi']:+.2%}]"
        if u["clv_lo"] > 0 and roi_sig:
            return "EDGE", f"Edge: beats the closing line ({c}) and is profitable ({r}).{holm_txt}{part}"
        if u["clv_lo"] > 0:
            return "LIKELY", (f"Likely edge: beats the closing line ({c}); P&L not yet significant ({r}, "
                              f"{n} bets).{holm_txt}{part}")
        if u["clv_hi"] < 0:
            return "NEGATIVE", f"No edge: the bets lose to the closing line ({c}); {r}.{luck}{part}"
        return "NONE", f"No evidence of edge: CLV indistinguishable from zero ({c}); {r}.{luck}{part}"
    r = f"ROI {u['roi']:+.2%} [{u['roi_lo']:+.2%}, {u['roi_hi']:+.2%}]"
    pn = u.get("p_null_dec", np.nan)
    why = no_clv_reason(u)
    if roi_sig and np.isfinite(pn) and pn < 0.05:
        return "LIKELY", (f"Profitable against the decision-time market ({r}, market-null p={pn:.3f}), but no "
                          f"usable CLV to confirm it.{holm_txt} {why}")
    if u["roi_hi"] < 0:
        return "NEGATIVE", f"No edge: loses money ({r}). {why}"
    return "NONE", f"No evidence of edge ({r}). {why}"


def plausibility_flags(r: dict, cal: pd.DataFrame) -> list[str]:
    """Too-good-to-be-true checks: these point at price data or leakage before they point at an edge."""
    f = []
    rows = cal[cal["sport"] == r["sport"]]
    if r["market"] != "ALL":
        rows = rows[rows["market"] == r["market"]]
    for c in rows.to_dict("records"):
        tag = "" if r["market"] != "ALL" else f"{c['market']}: "
        gain = c["ll_market_dec"] - c["ll_model"]
        if c["n_test"] >= 2000 and gain > 0.005:
            f.append(f"{tag}the model beats the de-vigged decision price by {gain:.4f} nats/selection over "
                     f"{c['n_test']:,} rows, more than published models manage against liquid markets; suspect the "
                     f"recorded prices or a leak before trusting it.")
        b, se = c.get("mkt_b", np.nan), c.get("mkt_b_se", np.nan)
        spread_ok = c.get("sd_logit_fair", 0) > 0.3   # lines priced near 50/50 leave the slope unidentified
        if spread_ok and np.isfinite(b) and np.isfinite(se) and se < 0.1 and abs(b - 1) > 0.1 and abs(b - 1) > 4 * se:
            f.append(f"{tag}the de-vigged price itself is miscalibrated (outcome-on-price logit slope b={b:.2f} "
                     f"+/- {se:.2f}); real liquid markets sit near 1, so the recorded prices may not be ones that "
                     f"could have been bet (wrong line, stale or mislabelled side).")
    n = r.get("n", 0) or 0
    clv = r.get("clv", np.nan)
    if n >= 300 and isinstance(clv, float) and np.isfinite(clv) and clv > 0.04:
        f.append(f"mean CLV {clv:+.1%} over {n:,} bets is above what sharp bettors report (about +1% to +3%); "
                 f"check that the closing price is for the same line and selection as the bet (spreads/totals "
                 f"whose line moved) and that early prices are not stale quotes, before trusting it.")
    bm, cx = r.get("big_move_share", np.nan), r.get("clv_ex_big", np.nan)
    if (n >= 100 and isinstance(bm, float) and np.isfinite(bm) and bm > 0.05 and isinstance(clv, float)
            and np.isfinite(cx) and clv - cx > 0.01):
        f.append(f"{bm:.0%} of these bets are spreads/totals whose closing price is more than 25% away from the "
                 f"price taken (usually a different line, so CLV against it is meaningless); without "
                 f"them mean CLV is {cx:+.2%} instead of {clv:+.2%}.")
    roi = r.get("roi", np.nan)
    if n >= 1000 and np.isfinite(roi) and roi > 0.08:
        f.append(f"ROI {roi:+.1%} over {n:,} bets is far above what sharp bettors sustain (low single digits); "
                 f"treat as a data problem until explained.")
    return f


def _logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return float(np.mean(-(y * np.log(p) + (1 - y) * np.log(1 - p))))


def calibration_table(d: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    rows = []
    t = d[~d["warmup"] & d["outcome"].isin([0.0, 1.0])]
    for (sp, mk), g in t.groupby(["sport", "market"]):
        y = g["outcome"].to_numpy(float)
        r = {"sport": sp, "market": mk, "n_test": len(g),
             "ll_model": _logloss(g["model_p"], y), "ll_shrunk": _logloss(g["q"], y),
             "ll_market_dec": _logloss(g["fair_dec"], y),
             "ll_market_close": _logloss(g["fair_close"], y) if g["fair_close"].notna().all() else np.nan,
             "brier_model": float(np.mean((g["model_p"] - y) ** 2)),
             "brier_market_dec": float(np.mean((g["fair_dec"] - y) ** 2))}
        mc = fit_blend(logit(g["fair_dec"].to_numpy()), np.zeros(len(g)), y, k_prior=1.0)
        r["mkt_a"], r["mkt_b"], r["mkt_b_se"] = float(mc.theta[0]), float(mc.theta[1]), float(mc.se[1])
        r["sd_logit_fair"] = float(np.std(logit(g["fair_dec"].to_numpy())))
        h = hist[(hist["sport"] == sp) & (hist["segment"] == mk)]
        if len(h):
            last = h.iloc[-1]
            r.update({"a": last["a"], "b": last["b"], "c": last["c"], "se_c": last["se_c"],
                      "n_train_last": int(last["n_train"]), "c_median": float(h["c"].median())})
        rows.append(r)
    return pd.DataFrame(rows)


def inventory(raw: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sp, g in d.groupby("sport"):
        rows.append({
            "sport": sp, "rows": len(g), "events": g["event_id"].nunique(),
            "from": g["start_time"].min().strftime("%Y-%m-%d"), "to": g["start_time"].max().strftime("%Y-%m-%d"),
            "markets": ", ".join(sorted(g["market"].unique())[:8]),
            "price_src": ", ".join(sorted(g["price_src"].unique())[:6]),
            "median_lead_h": float(g["lead_h"].median()),
            "fair_recomputed": float((g["fair_dec_src"] == "recomputed").mean()),
            "fair_vig_incl": float((g["fair_dec_src"] == "vig_incl").mean()),
            "has_close": float(g["fair_close"].notna().mean()),
            "close_moved": float(((g["price_close"] - g["price_dec"]).abs() > 1e-9).mean()),
            "test_rows": int((~g["warmup"]).sum()),
            "excluded_insample": int((~g["oos"]).sum()),
            "excluded_aggregate": int((g["oos"] & ~g["executable"]).sum()),
            "test_from": (g.loc[~g["warmup"], "decision_time"].min().strftime("%Y-%m-%d")
                          if (~g["warmup"]).any() else "-"),
        })
    return pd.DataFrame(rows)


def _breakdown(rows: pd.DataFrame, by: str, B: int, min_n: int = 30, top: int = 15) -> pd.DataFrame:
    out = []
    for k, g in rows.groupby(by, observed=True):
        if len(g) < min_n:
            continue
        u = unit_test(g, None, B=B, do_perm=False, do_null=False)
        out.append({by: str(k), "n": u["n"], "clv": u.get("clv", np.nan), "clv_lo": u.get("clv_lo", np.nan),
                    "clv_hi": u.get("clv_hi", np.nan), "beat_close": u.get("beat_close", np.nan),
                    "roi": u["roi"], "roi_lo": u["roi_lo"], "roi_hi": u["roi_hi"], "avg_price": u["avg_price"]})
    t = pd.DataFrame(out)
    if len(t) > top:
        t = t.sort_values("n", ascending=False).head(top)
    return t


def analyse(df: pd.DataFrame, opts: Options, log=print) -> dict:
    cfg = opts.sizing
    res: dict = {"opts": opts}
    log(f"prepare: {len(df)} rows")
    d = prepare(df, method=opts.devig, settle_lag_hours=opts.settle_lag_hours)
    d, hist = walk_forward_shrink(d, k_prior=opts.k_prior, min_train=opts.min_train)
    d["edge_bucket"] = pd.cut(d["edge"], EDGE_BUCKETS, right=False).astype(str)
    d["lead_bucket"] = pd.cut(d["lead_h"], LEAD_BUCKETS, labels=LEAD_LABELS, right=False).astype(str)
    res["frame"] = d
    res["hist"] = hist
    res["inventory"] = inventory(df, d)
    res["calibration"] = calibration_table(d, hist)

    sel = selected(d, cfg)
    raw_cfg = replace(cfg, use_shrunk=False)
    sel_raw = selected(d, raw_cfg)
    seg_rows = []
    for sp in sorted(d["sport"].unique()):
        ds = d[d["sport"] == sp]
        segs = [("ALL", ds)] + [(mk, g) for mk, g in ds.groupby("market")]
        for mk, g in segs:
            log(f"unit tests: {sp} / {mk}")
            within = ("slate",) if mk == "ALL" else ("slate", "market")
            rows = g[sel.loc[g.index]]
            u = unit_test(rows, g, B=opts.B, perm_B=opts.perm_B, select=_selector(cfg), within=within)
            rr = g[sel_raw.loc[g.index]]
            ur = unit_test(rr, g, B=max(500, opts.B // 4), do_perm=False, do_null=False)
            w = res["calibration"]
            c_row = w[(w["sport"] == sp) & (w["market"] == mk)] if mk != "ALL" else pd.DataFrame()
            seg_rows.append({"sport": sp, "market": mk, **u,
                             "raw_n": ur.get("n", 0), "raw_clv": ur.get("clv", np.nan),
                             "raw_roi": ur.get("roi", np.nan), "raw_roi_lo": ur.get("roi_lo", np.nan),
                             "raw_roi_hi": ur.get("roi_hi", np.nan),
                             "trust_c": float(c_row["c"].iloc[0]) if len(c_row) and "c" in c_row else np.nan})
    seg = pd.DataFrame(seg_rows)
    if len(seg):
        seg["flags"] = [plausibility_flags(r, res["calibration"]) for r in seg.to_dict("records")]
        def primary(r):
            if clv_usable(r):
                return r.get("p_clv", np.nan)
            return r.get("p_null_dec", np.nan)
        seg["p_primary"] = seg.apply(primary, axis=1)
        mk_rows = seg["market"] != "ALL"
        seg["p_holm"] = np.nan
        seg.loc[mk_rows, "p_holm"] = holm(seg.loc[mk_rows, "p_primary"].tolist())
        seg.loc[~mk_rows, "p_holm"] = holm(seg.loc[~mk_rows, "p_primary"].tolist())
        v = [verdict(r, r["p_holm"], opts.min_bets_verdict) for r in seg.to_dict("records")]
        codes, texts = [], []
        for (code, txt), f in zip(v, seg["flags"]):
            if f and code in ("EDGE", "LIKELY"):
                code = "SUSPECT"
                txt = "SUSPECT, do not bet until explained. Apparent result: " + txt
            codes.append(code)
            texts.append(txt + ("" if not f else " **Data check:** " + " ".join(f)))
        for i, r in enumerate(seg.to_dict("records")):
            c = r.get("trust_c", np.nan)
            if codes[i] in ("EDGE", "LIKELY", "SUSPECT") and isinstance(c, float) and np.isfinite(c) and c < 0.1:
                texts[i] += (f" Note: the fitted model weight is c={c:.2f}, so these selections come from the "
                             f"walk-forward recalibration of the market price itself (intercept/slope, e.g. a "
                             f"favourite-longshot correction), not from the sport model.")
            hi = r.get("raw_roi_hi", np.nan)
            if (r.get("raw_n") or 0) >= 200 and isinstance(hi, float) and np.isfinite(hi) and hi < 0:
                texts[i] += (f" Taken at face value (no shrinkage) the model would have lost {r['raw_roi']:+.1%} "
                             f"over {int(r['raw_n']):,} bets.")
        recs = seg.to_dict("records")
        for i, r in enumerate(recs):   # a sport-level edge carried by a suspect market is suspect too
            if r["market"] == "ALL" and codes[i] in ("EDGE", "LIKELY"):
                bad = [x["market"] for j, x in enumerate(recs)
                       if x["sport"] == r["sport"] and x["market"] != "ALL" and codes[j] == "SUSPECT"]
                if bad:
                    codes[i] = "SUSPECT"
                    texts[i] = (f"SUSPECT: the pooled result leans on {', '.join(bad)}, which fails the "
                                f"plausibility checks. Apparent result: " + texts[i])
        seg["verdict_code"] = codes
        seg["verdict"] = texts
    res["segments"] = seg

    # breakdowns on the shrunk-policy bets
    bets = d[sel]
    res["breakdowns"] = {}
    for sp in sorted(d["sport"].unique()):
        b = bets[bets["sport"] == sp]
        if not len(b):
            continue
        bd = {by: _breakdown(b, by, opts.breakdown_B) for by in ("league", "edge_bucket", "lead_bucket", "season")}
        # every price source, including aggregates (max / avg) that are never bet
        allsrc = d[candidates(d, cfg) & ~d["warm_fit"].astype(bool) & d["oos"].astype(bool) & (d["sport"] == sp)]
        bd["price_src"] = _breakdown(allsrc, "price_src", opts.breakdown_B)
        res["breakdowns"][sp] = bd

    # bankroll simulations
    strategies = [cfg, replace(cfg, simultaneous=False), replace(cfg, kelly_fraction=0.5),
                  replace(cfg, method="flat"), replace(cfg, method="prop_edge"), replace(cfg, use_caps=False),
                  replace(cfg, use_shrunk=False)]
    labels = ["kelly", "kelly_indep", "kelly_0.5", "flat", "prop_edge", "kelly_nocaps", "kelly_raw_model"]
    res["sims"] = {}
    res["portfolio"] = []
    universes = [(sp, d[d["sport"] == sp]) for sp in sorted(d["sport"].unique())]
    if d["sport"].nunique() > 1:
        universes.append(("ALL SPORTS", d))
    for name, du in universes:
        cache: dict = {}
        for lab, sc in zip(labels, strategies):
            log(f"simulate: {name} / {sc.label()}")
            sim = simulate(du, sc, initial=opts.initial, cache=cache)
            m = portfolio_metrics(sim, B=opts.sim_B)
            m.update({"universe": name, "key": lab})
            res["portfolio"].append(m)
            res["sims"][(name, lab)] = sim
        if opts.grid:
            for fr in FRACTIONS:
                sc = replace(cfg, kelly_fraction=fr)
                sim = simulate(du, sc, initial=opts.initial, cache=cache)
                m = portfolio_metrics(sim, B=opts.sim_B)
                m.update({"universe": name, "key": f"grid_{fr:g}"})
                res["portfolio"].append(m)
    res["portfolio"] = pd.DataFrame(res["portfolio"])
    res["recommendation"] = recommend(res, opts, log)
    return res


def recommend(res: dict, opts: Options, log=print) -> dict:
    seg = res["segments"]
    if not len(seg):
        return {"bet": [], "text": "No data."}
    mk = seg[seg["market"] != "ALL"]
    confirmed = [(r["sport"], r["market"]) for r in mk[mk["verdict_code"] == "EDGE"].to_dict("records")]
    pilot = [(r["sport"], r["market"]) for r in mk[mk["verdict_code"] == "LIKELY"].to_dict("records")]
    bet = confirmed or pilot
    out = {"bet": bet, "confirmed": confirmed, "pilot": pilot}
    if not bet:
        out["text"] = ("Do not stake real money yet. No sport/market shows an edge that survives the honest tests; "
                       "paper-trade the shrunk-model selections and re-run as more out-of-sample data accrues.")
        out["fraction"] = None
        return out
    d = res["frame"]
    mask = pd.Series(False, index=d.index)
    for sp, mk in bet:
        mask |= (d["sport"] == sp) & (d["market"] == mk)
    du = d[mask]
    cache: dict = {}
    grid = []
    for fr in FRACTIONS:
        sc = replace(opts.sizing, kelly_fraction=fr)
        sim = simulate(du, sc, initial=opts.initial, cache=cache)
        m = portfolio_metrics(sim, B=opts.sim_B)
        m["fraction"] = fr
        grid.append(m)
    g = pd.DataFrame(grid)
    out["grid"] = g
    ok = g[(g.get("p_below_50", pd.Series(1.0, index=g.index)) <= 0.05)]
    pick = ok if len(ok) else g
    best = pick.sort_values("log_growth_p5", ascending=False).iloc[0] if "log_growth_p5" in pick else pick.iloc[0]
    fr = float(best["fraction"])
    if best.get("log_growth_p5", -1) <= 0:
        fr = min(fr, 0.1)
    out["fraction"] = fr
    out["metrics"] = best.to_dict()
    sc = opts.sizing
    if confirmed:
        lead = f"Bet only {', '.join(f'{a}/{b}' for a, b in confirmed)}."
        if pilot:
            lead += (f" Paper-trade (or pilot at a quarter of the stake below) "
                     f"{', '.join(f'{a}/{b}' for a, b in pilot)}, whose CLV is positive but whose P&L is not yet.")
    else:
        lead = (f"No confirmed edge: do not stake real money yet. The candidates "
                f"{', '.join(f'{a}/{b}' for a, b in pilot)} beat the closing line but their P&L is not yet "
                f"significant: paper-trade them, or pilot with a tiny bankroll. If piloted:")
    out["text"] = (f"{lead} Kelly fraction {fr:g} of the (shrunk) "
                   f"simultaneous Kelly stake, chosen as the fraction with the best 5th-percentile bootstrap log "
                   f"growth among those with P(bankroll ever below 50%) <= 5% (in-sample choice on the test "
                   f"period: treat it as an upper bound). Caps: {sc.max_bet:.0%} per bet, {sc.max_group:.0%} per "
                   f"event/team group, {sc.max_league:.0%} per league per slate, {sc.max_slate:.0%} per slate; "
                   f"drawdown throttle from {sc.dd_start:.0%} (size x{sc.dd_floor_mult:g} at {sc.dd_full:.0%}); "
                   f"minimum shrunk edge {sc.min_edge:.0%}.")
    return out


# ----------------------------------------------------------------------------------------------- rendering


def _f(x, kind="pct", nd=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "-"
    if kind == "pct":
        return f"{x * 100:+.{nd}f}%"
    if kind == "pct0":
        return f"{x * 100:.{nd}f}%"
    if kind == "p":
        return "<0.001" if x < 0.001 else f"{x:.3f}"
    if kind == "int":
        return f"{x:.2e}" if abs(x) >= 1e9 else f"{int(x):,}"
    if kind == "x":
        return f"{x:.2e}x" if abs(x) >= 1000 else f"{x:.2f}x"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def _ci(est, lo, hi):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (est, lo, hi)):
        return "-"
    return f"{est * 100:+.2f}% [{lo * 100:+.2f}, {hi * 100:+.2f}]"


def _table(header: list[str], rows: list[list[str]]) -> str:
    s = "| " + " | ".join(header) + " |\n|" + "|".join("---" for _ in header) + "|\n"
    for r in rows:
        s += "| " + " | ".join(str(x) for x in r) + " |\n"
    return s


def svg_equity(series: dict, path: Path, title: str) -> None:
    """Static log-scale equity chart (light surface, slots 1-3 of the reference categorical palette)."""
    colors = ["#2a78d6", "#eb6834", "#1baf7a"]
    W, H, L, R, T, Bm = 720, 300, 56, 120, 34, 30
    xs = [s[0] for s in series.values() if len(s[0])]
    ys = [s[1] for s in series.values() if len(s[1])]
    if not xs:
        return
    x0 = min(x.min() for x in xs)
    x1 = max(x.max() for x in xs)
    ly = [np.log10(np.clip(y, 1e-3, None)) for y in ys]
    y0 = min(min(v.min() for v in ly), 0.0)
    y1 = max(max(v.max() for v in ly), 0.0)
    if y1 - y0 < 0.05:
        y0, y1 = y0 - 0.05, y1 + 0.05

    def px(x):
        return L + (x - x0) / max(x1 - x0, 1) * (W - L - R)

    def py(v):
        return T + (y1 - v) / (y1 - y0) * (H - T - Bm)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           f'font-family="system-ui, sans-serif" font-size="11">',
           f'<rect width="{W}" height="{H}" fill="#fcfcfb"/>',
           f'<text x="{L}" y="18" fill="#0b0b0b" font-size="13" font-weight="600">{title}</text>']
    ticks = np.unique(np.round(np.linspace(y0, y1, 5), 2))
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{py(t):.1f}" y2="{py(t):.1f}" stroke="#e4e3df" '
                   f'stroke-width="1"/>')
        out.append(f'<text x="{L - 6}" y="{py(t) + 4:.1f}" text-anchor="end" fill="#52514e">{10 ** t:.2g}x</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{py(0):.1f}" y2="{py(0):.1f}" stroke="#a9a8a2" stroke-width="1"/>')
    for k, frac in enumerate((0.0, 0.5, 1.0)):
        xv = x0 + frac * (x1 - x0)
        lab = pd.Timestamp(xv, unit="s").strftime("%Y-%m")
        out.append(f'<text x="{px(xv):.1f}" y="{H - 10}" text-anchor="middle" fill="#52514e">{lab}</text>')
    for i, (name, (x, y)) in enumerate(series.items()):
        if not len(x):
            continue
        c = colors[i % len(colors)]
        v = np.log10(np.clip(y, 1e-3, None))
        step = max(1, len(x) // 800)
        pts = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in zip(x[::step], v[::step]))
        pts += f" {px(x[-1]):.1f},{py(v[-1]):.1f}"
        out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/>')
        out.append(f'<circle cx="{px(x[-1]):.1f}" cy="{py(v[-1]):.1f}" r="4" fill="{c}" stroke="#fcfcfb" '
                   f'stroke-width="2"/>')
        out.append(f'<text x="{px(x[-1]) + 8:.1f}" y="{py(v[-1]) + 4 + 12 * (i - 1) * 0:.1f}" fill="#0b0b0b">'
                   f'{name} {y[-1]:.2f}x</text>')
    # legend
    for i, name in enumerate(series):
        c = colors[i % len(colors)]
        lx = L + 10 + i * 150
        out.append(f'<rect x="{lx}" y="{T - 6}" width="12" height="3" fill="{c}"/>'
                   f'<text x="{lx + 16}" y="{T - 2}" fill="#52514e">{name}</text>')
    out.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


def write_charts(res: dict, chart_dir: Path) -> dict:
    made = {}
    for name in sorted({u for u, _ in res["sims"]}):
        series = {}
        for key, lab in (("kelly", "Kelly"), ("flat", "Flat"), ("prop_edge", "Prop-edge")):
            sim = res["sims"].get((name, key))
            if sim is None or not len(sim.ledger):
                continue
            e = sim.equity
            t = ((e["time"] - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy(float)
            series[lab] = (t, e["equity"].to_numpy(float) / sim.initial)
        if series:
            fn = chart_dir / f"equity_{name.lower().replace(' ', '_')}.svg"
            svg_equity(series, fn, f"{name}: bankroll multiple (log scale), walk-forward test period")
            made[name] = fn
    return made


def write_markdown(res: dict, reports, path: Path, charts: dict | None = None, run_info: dict | None = None,
                   synthetic: bool = False) -> str:
    opts: Options = res["opts"]
    cfg = opts.sizing
    seg: pd.DataFrame = res["segments"]
    L: list[str] = []
    A = L.append
    A("# Edge backtest results\n")
    if synthetic:
        A("> **SYNTHETIC DATA.** These numbers come from generated files with a known truth, to exercise the "
          "pipeline. They say nothing about real markets.\n")
    ri = run_info or {}
    A(f"Generated {ri.get('generated', '')} by `scripts/edge_backtest.py` from "
      f"{', '.join(ri.get('files', [])) or 'no files'}. Protocol: `docs/research/EDGE_PROTOCOL.md`. "
      f"Code: `oddsmarkets/common/edge/`.\n")

    # verdict first
    A("## Verdict\n")
    if not len(seg):
        A("No usable rows: nothing to test.\n")
    else:
        sp_rows = seg[seg["market"] == "ALL"]
        for r in sp_rows.to_dict("records"):
            A(f"- **{r['sport']}** (all markets): {r['verdict']}")
        A("")
        for r in seg[seg["market"] != "ALL"].to_dict("records"):
            A(f"- {r['sport']} / {r['market']}: {r['verdict']}")
        A("")
        rec = res["recommendation"]
        A(f"**Overall.** {overall_sentence(seg, rec)}\n")
        A(f"**Recommended portfolio settings.** {rec['text']}\n")

    A("## How to read this\n")
    A(f"- Every model is judged walk-forward. The portfolio layer does not trust `model_p` as is: each month it "
      f"refits `logit q = a + b logit(m) + c (logit(model) - logit(m))` (m = de-vigged decision price) on bets "
      f"settled before that month only, with a ridge prior worth {opts.k_prior:g} bets that the market is right "
      f"(a=0, b=1, c=0). `c` is the honest weight on the model. Months with fewer than {opts.min_train} settled "
      f"rows are warm-up: q = market, no bets. Bets need shrunk edge `q*price-1 >= {cfg.min_edge:.0%}`, "
      f"q >= {cfg.min_prob:.0%}, price <= {cfg.max_price:g}.")
    A(f"- De-vigging: `{opts.devig}` everywhere a market group is complete (all selections present); else the "
      f"file's own fair column; else 1/price with the vig left in (conservative).")
    A("- **CLV** = de-vigged closing probability x price taken - 1: the expected return if the close is the truth. "
      "It is the primary test (far less noisy than P&L). **ROI** is realised profit per unit staked "
      "(pushes and half results settled exactly). Unit-stake tests count each qualifying selection as one unit.")
    A(f"- CIs are 95% moving-block bootstrap intervals over slates in time order ({opts.B} resamples). p-values "
      "are one-sided (H0: no edge). *p(CLV)*, *p(ROI)*: bootstrap. *p(null dec)* / *p(null close)*: outcomes "
      "redrawn from the de-vigged decision / closing market, jointly per market: does the realised ROI beat what "
      "the market itself implies? *p(perm)*: model edges shuffled within slate and market, bets re-selected: "
      "does the model pick better than random picks from the same slates? *Holm* adjusts the primary p "
      f"(CLV when it is usable: a same-line close for at least {CLV_MIN_SHARE:.0%} of the bets, moved from the price "
      f"taken for more than {CLOSE_MOVED_MIN:.0%} of them; else the decision-market null) across all sport/market "
      "tests.")
    A("- A positive ROI without positive CLV is treated as luck (protocol section 1).\n")

    A("## Data\n")
    for v in reports:
        A(f"- {v.summary()}")
        for e in v.errors:
            A(f"  - ERROR: {e}")
        for w in v.warnings:
            A(f"  - warning: {w}")
        if v.extra_cols:
            A(f"  - extra columns ignored: {', '.join(map(str, v.extra_cols[:12]))}"
              + (" ..." if len(v.extra_cols) > 12 else ""))
    A("")
    inv = res.get("inventory")
    if inv is not None and len(inv):
        A("*test rows* = out-of-sample, executable rows past the shrinkage warm-up: the only rows bet and scored. "
          "Rows a sport agent marked as its tuning split (`split` = dev/train) or `quality_ok` = False, and "
          "aggregate price sources (max/avg over books, never a quotable price), are excluded from bets but used "
          "as history for the shrinkage fit.\n")
        A(_table(["sport", "rows", "events", "from", "to", "test rows (from)", "in-sample excl.", "aggregate excl.",
                  "markets", "price sources",
                  "median lead", "fair recomputed", "vig-incl fair", "has close", "close moved"],
                 [[r["sport"], _f(r["rows"], "int"), _f(r["events"], "int"), r["from"], r["to"],
                   f"{r['test_rows']:,} ({r['test_from']})", _f(r["excluded_insample"], "int"),
                   _f(r["excluded_aggregate"], "int"), r["markets"], r["price_src"],
                   f"{r['median_lead_h']:.1f}h", _f(r["fair_recomputed"], "pct0", 0), _f(r["fair_vig_incl"], "pct0", 0),
                   _f(r["has_close"], "pct0", 0), _f(r["close_moved"], "pct0", 0)] for r in inv.to_dict("records")]))

    A("## Edge tests (unit stakes, shrunk model)\n")
    if len(seg):
        A("*CLV on* = bets with a closing price for the line bet, of all bets (spreads/totals whose line moved "
          "before the close get no CLV); *close moved* = share of those closes that differ from the price taken. CLV "
          f"is the test (*CLV used*) only when it covers at least {CLV_MIN_SHARE:.0%} of the bets and more than "
          f"{CLOSE_MOVED_MIN:.0%} of those closes moved. Otherwise the CLV shown rests on a minority of the bets or, "
          "for bets taken at the closing price, is just minus the margin, and the verdict rests on the "
          "decision-market null.\n")
        A(_table(["sport", "market", "bets", "avg price", "mean CLV [95% CI]", "CLV on", "close moved", "CLV used",
                  "beat close", "ROI [95% CI]",
                  "p(CLV)", "p(ROI)", "p(null dec)", "p(null close)", "p(perm)", "Holm p", "model weight c"],
                 [[r["sport"], r["market"], _f(r["n"], "int"), _f(r.get("avg_price"), "num", 2),
                   _ci(r.get("clv"), r.get("clv_lo"), r.get("clv_hi")), clv_basis(r),
                   _f(r.get("close_differs"), "pct0", 0), "yes" if clv_usable(r) else "no",
                   _f(r.get("beat_close"), "pct0", 0),
                   _ci(r.get("roi"), r.get("roi_lo"), r.get("roi_hi")), _f(r.get("p_clv"), "p"),
                   _f(r.get("p_roi"), "p"), _f(r.get("p_null_dec"), "p"), _f(r.get("p_null_close"), "p"),
                   _f(r.get("p_perm"), "p"), _f(r.get("p_holm"), "p"), _f(r.get("trust_c"), "num", 2)]
                  for r in seg.to_dict("records")]))
        A("The raw model, unshrunk (same filters on `model_p*price-1`), for comparison:\n")
        A(_table(["sport", "market", "bets", "mean CLV", "ROI [95% CI]"],
                 [[r["sport"], r["market"], _f(r["raw_n"], "int"), _f(r.get("raw_clv"), "pct", 2),
                   _ci(r.get("raw_roi"), r.get("raw_roi_lo"), r.get("raw_roi_hi"))] for r in seg.to_dict("records")]))

    cal = res.get("calibration")
    if cal is not None and len(cal):
        A("## Model against market (test period, binary outcomes)\n")
        A("Log-loss (lower is better) of the raw model, the shrunk model and the de-vigged market at decision and "
          "close; the market's own calibration slope (outcome on logit of the de-vigged decision price: 1 = "
          "calibrated, below 1 = favourites overpriced); the last walk-forward fit (a, b, c) and the median model "
          "weight `c` over the refits.\n")
        A(_table(["sport", "market", "rows", "LL model", "LL shrunk", "LL market dec", "LL market close",
                  "Brier model", "Brier market", "market slope b (se)", "a", "b", "c (se)", "median c"],
                 [[r["sport"], r["market"], _f(r["n_test"], "int"), _f(r["ll_model"], "num", 4),
                   _f(r["ll_shrunk"], "num", 4), _f(r["ll_market_dec"], "num", 4), _f(r["ll_market_close"], "num", 4),
                   _f(r["brier_model"], "num", 4), _f(r["brier_market_dec"], "num", 4),
                   f"{_f(r.get('mkt_b'), 'num', 3)} ({_f(r.get('mkt_b_se'), 'num', 3)})", _f(r.get("a"), "num", 3),
                   _f(r.get("b"), "num", 3), f"{_f(r.get('c'), 'num', 3)} ({_f(r.get('se_c'), 'num', 3)})",
                   _f(r.get("c_median"), "num", 3)] for r in cal.to_dict("records")]))

    pf: pd.DataFrame = res["portfolio"]
    if len(pf):
        A("## Bankroll simulations\n")
        A(f"Initial bankroll {opts.initial:,.0f}; event-ordered by slate; stakes sized on equity marked at cost; "
          f"best price per selection per slate; liquidity capped at `max_stake_hint` where given. Default book: "
          f"{cfg.label()}, simultaneous Kelly per slate, caps {cfg.max_bet:.0%} bet / {cfg.max_group:.0%} group / "
          f"{cfg.max_league:.0%} league-slate / {cfg.max_slate:.0%} slate, drawdown throttle "
          f"{cfg.dd_start:.0%}-{cfg.dd_full:.0%}. Log growth CI and risk of ruin from a block bootstrap of slate "
          f"returns ({opts.sim_B} paths).\n")
        main = pf[~pf["key"].str.startswith("grid_")]
        A(_table(["universe", "strategy", "bets", "staked", "ROI", "final", "log growth [95% CI]", "max DD",
                  "DD p95", "monthly Sharpe (ann.)", "turnover", "P(<50%)", "P(loss)", "stake-wtd CLV"],
                 [[r["universe"], r["strategy"], _f(r.get("n_bets"), "int"), _f(r.get("staked"), "int"),
                   _f(r.get("roi"), "pct", 2), _f(r.get("final_mult"), "x"),
                   (f"{r['log_growth']:+.3f} [{r.get('log_growth_lo', np.nan):+.3f}, "
                    f"{r.get('log_growth_hi', np.nan):+.3f}]" if isinstance(r.get("log_growth"), float)
                    and math.isfinite(r.get("log_growth", np.nan)) else "-"),
                   _f(r.get("max_dd"), "pct0"), _f(r.get("max_dd_p95"), "pct0"),
                   _f(r.get("sharpe_month_ann"), "num", 2), _f(r.get("turnover"), "num", 1),
                   _f(r.get("p_below_50"), "pct0"), _f(r.get("p_loss"), "pct0"), _f(r.get("clv_w"), "pct", 2)]
                  for r in main.to_dict("records")]))
        grid = pf[pf["key"].str.startswith("grid_")]
        if len(grid):
            A("Kelly fraction grid (simultaneous Kelly, caps on):\n")
            A(_table(["universe", "fraction", "bets", "final", "log growth", "5th pct log growth", "max DD",
                      "P(<50%)", "P(<20%)"],
                     [[r["universe"], r["key"][5:], _f(r.get("n_bets"), "int"), _f(r.get("final_mult"), "x"),
                       _f(r.get("log_growth"), "num", 3), _f(r.get("log_growth_p5"), "num", 3),
                       _f(r.get("max_dd"), "pct0"), _f(r.get("p_below_50"), "pct0"), _f(r.get("p_below_20"), "pct0")]
                      for r in grid.to_dict("records")]))
        rec = res["recommendation"]
        if rec.get("grid") is not None:
            A("Recommended (or pilot) book, only the sport/markets named in the recommendation, fraction grid:\n")
            A(_table(["fraction", "bets", "final", "log growth", "5th pct", "max DD", "P(<50%)"],
                     [[f"{r['fraction']:g}", _f(r.get("n_bets"), "int"), _f(r.get("final_mult"), "x"),
                       _f(r.get("log_growth"), "num", 3), _f(r.get("log_growth_p5"), "num", 3),
                       _f(r.get("max_dd"), "pct0"), _f(r.get("p_below_50"), "pct0")]
                      for r in rec["grid"].to_dict("records")]))
    if charts:
        A("Equity curves (Kelly, flat and proportional-to-edge staking, log scale):\n")
        for name, fn in charts.items():
            rel = Path(fn).relative_to(path.parent).as_posix() if Path(fn).is_relative_to(path.parent) else fn
            A(f"![{name} equity]({rel})\n")

    if res.get("breakdowns"):
        A("## Breakdowns (shrunk-model bets, unit stakes)\n")
        names = {"league": "league", "price_src": "price source", "edge_bucket": "shrunk edge bucket",
                 "lead_bucket": "decision lead time", "season": "season"}
        for sp, bd in res["breakdowns"].items():
            A(f"### {sp}\n")
            for by, t in bd.items():
                if t is None or not len(t):
                    continue
                A(f"By {names[by]}:\n")
                A(_table([names[by], "bets", "mean CLV [95% CI]", "beat close", "ROI [95% CI]", "avg price"],
                         [[r[by], _f(r["n"], "int"), _ci(r["clv"], r["clv_lo"], r["clv_hi"]),
                           _f(r["beat_close"], "pct0", 0), _ci(r["roi"], r["roi_lo"], r["roi_hi"]),
                           _f(r["avg_price"], "num", 2)] for r in t.to_dict("records")]))

    A("## Experiment log\n")
    A("Every run of `scripts/edge_backtest.py` appends its settings and headline numbers to "
      "`docs/research/edge_runs.jsonl`, so the number of looks at the data stays visible (protocol rule 5). "
      f"This run: {json.dumps(ri.get('settings', {}))}\n")
    text = "\n".join(L)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def overall_sentence(seg: pd.DataFrame, rec: dict) -> str:
    mk = seg[seg["market"] != "ALL"]
    n_tests = len(mk)
    edge = mk[mk["verdict_code"] == "EDGE"]
    likely = mk[mk["verdict_code"] == "LIKELY"]
    neg = mk[mk["verdict_code"] == "NEGATIVE"]
    sus = mk[mk["verdict_code"] == "SUSPECT"]
    parts = [f"{n_tests} sport/market combinations tested."]
    if len(edge):
        parts.append("Edge (beats the close and profitable): " + ", ".join(f"{a}/{b}" for a, b in
                                                                           zip(edge["sport"], edge["market"])) + ".")
    if len(likely):
        parts.append("Likely edge, not yet confirmed by P&L: " + ", ".join(
            f"{a}/{b}" for a, b in zip(likely["sport"], likely["market"])) + ".")
    if len(sus):
        parts.append("Apparent edges that fail the plausibility checks (too good for a liquid market, or the "
                     "recorded prices are themselves miscalibrated), so they are NOT counted as edge until the data "
                     "is explained: " + ", ".join(f"{a}/{b}" for a, b in zip(sus["sport"], sus["market"])) + ".")
    if not len(edge) and not len(likely):
        parts.append("None shows an edge that survives the tests: the honest conclusion is that these models do "
                     "not yet beat the prices we could have bet.")
    if len(neg):
        parts.append("Clearly negative (losing to the close or losing money): " + ", ".join(
            f"{a}/{b}" for a, b in zip(neg["sport"], neg["market"])) + ".")
    return " ".join(parts)
