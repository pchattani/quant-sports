"""
Selections, prices and CLV for the edge research.

`selections(df, mu, sd, mu_t, sd_t, sig_m, sig_t)` turns a game table (with open / close line columns and model
means) into one row per selection at the OPEN decision: moneyline home / away, spread home / away (at the open
line), total over / under (at the open total). For each: model P(win, push, loss), the open decimal price, the
de-vigged open probability, the closing fair P(win, push, loss) AT THE OPEN LINE (the close's implied mean
re-evaluated at the open line, so a line move counts), CLV = expected profit per unit at the closing fair
probabilities, and the realised profit.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from oddsmarkets.basketball.research import evaluate as V
from oddsmarkets.basketball.research.lines import am_to_dec, devig2


def _f(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def _implied(p_home_nopush, line, sd, kind):
    return V.implied_mean(p_home_nopush, line, sd, kind) if p_home_nopush is not None else None


def market_means(r: pd.Series, when: str, sig_m: float, sig_t: float) -> dict:
    """Implied margin mean (spread market), implied total mean, fair ML P(home) for one game at open / close."""
    out = {"mu_sp": None, "mu_tot": None, "p_ml": None}
    sp, so_h, so_a = _f(r.get(f"{when}_sp_h")), _f(r.get(f"{when}_spo_h")), _f(r.get(f"{when}_spo_a"))
    if sp is not None:
        fv = devig2(so_h, so_a) if so_h is not None and so_a is not None else (0.5, 0.5)
        if fv:
            out["mu_sp"] = _implied(fv[0], sp, sig_m, "spread")
    tl, ov, un = _f(r.get(f"{when}_tot")), _f(r.get(f"{when}_over")), _f(r.get(f"{when}_under"))
    if tl is not None:
        fv = devig2(ov, un) if ov is not None and un is not None else (0.5, 0.5)
        if fv:
            out["mu_tot"] = _implied(fv[0], tl, sig_t, "total")
    ml = devig2(_f(r.get(f"{when}_ml_h")), _f(r.get(f"{when}_ml_a")))
    if ml:
        out["p_ml"] = ml[0]
    return out


def add_market_means(df: pd.DataFrame, sig_m: float, sig_t: float) -> pd.DataFrame:
    d = df.copy()
    for when in ("open", "close"):
        mm = [market_means(r, when, sig_m, sig_t) for _, r in d.iterrows()]
        d[f"{when}_mu_sp"] = [m["mu_sp"] for m in mm]
        d[f"{when}_mu_tot"] = [m["mu_tot"] for m in mm]
        d[f"{when}_p_ml"] = [m["p_ml"] for m in mm]
    return d


def _ml_probs(mu, sd):
    w, _, l_ = V.margin_probs(mu, sd, 0.0)
    return w, l_


def selections(d: pd.DataFrame, mu_col: str, sd_col: str, mut_col: str | None, sdt_col: str | None,
               sig_m: float, sig_t: float, price_src: str = "open") -> pd.DataFrame:
    """One row per selection at the `price_src` decision ("open"); requires add_market_means columns."""
    rows = []
    for _, r in d.iterrows():
        base = {"event_id": r["event_id"], "league": r["league"], "season": int(r["season"]), "start_time": r["start_time"],
                "decision_time": r["decision_time"], "day": r["day"], "stype": r["stype"], "gp": int(r["gp_h"] + r["gp_a"]),
                "price_src_book": r.get("line_src")}
        mu, sd = _f(r.get(mu_col)), _f(r.get(sd_col))
        # moneyline
        mh, ma = _f(r.get(f"{price_src}_ml_h")), _f(r.get(f"{price_src}_ml_a"))
        fo = devig2(mh, ma)
        if fo and mu is not None:
            pw, pl = _ml_probs(mu, sd)
            pc = _f(r.get("close_p_ml"))
            y = 1.0 if r["margin"] > 0 else 0.0
            ch, ca = _f(r.get("close_ml_h")), _f(r.get("close_ml_a"))
            for side, a, pm, fop, fcp, out, cpr in (("home", mh, pw, fo[0], pc, y, ch), ("away", ma, pl, fo[1], None if pc is None else 1 - pc, 1 - y, ca)):
                dec = am_to_dec(a)
                rows.append({**base, "market": "moneyline", "selection": side, "line": None, "model_p": float(pm),
                             "price_close": am_to_dec(cpr) if cpr is not None else None,
                             "model_push": 0.0, "price_dec": dec, "fair_p_decision": fop, "fair_p_close": fcp,
                             "close_push": 0.0 if fcp is not None else None, "outcome": out})
        # spread at the open line
        sp = _f(r.get(f"{price_src}_sp_h"))
        so_h, so_a = _f(r.get(f"{price_src}_spo_h")), _f(r.get(f"{price_src}_spo_a"))
        if sp is not None and so_h is not None and so_a is not None and mu is not None:
            fo = devig2(so_h, so_a)
            if fo:
                w, e, l_ = V.margin_probs(mu, sd, sp)
                cm = _f(r.get("close_mu_sp"))
                if cm is not None:
                    cw, ce, cl = V.margin_probs(cm, sig_m, sp)
                else:
                    cw = ce = cl = None
                mg = r["margin"] + sp
                oh = 1.0 if mg > 0 else (0.5 if mg == 0 else 0.0)
                cph, cpa = _f(r.get("close_spo_h")), _f(r.get("close_spo_a"))
                for side, a, pw_, pl_, fop, cwin, closs, out, ln, cpr in (
                        ("home", so_h, w, l_, fo[0], cw, cl, oh, sp, cph), ("away", so_a, l_, w, fo[1], cl, cw, 1 - oh, -sp, cpa)):
                    rows.append({**base, "market": "spread", "selection": side, "line": ln, "model_p": float(pw_),
                                 "price_close": am_to_dec(cpr) if cpr is not None else None,
                                 "line_close": None if _f(r.get("close_sp_h")) is None else (_f(r.get("close_sp_h")) if side == "home" else -_f(r.get("close_sp_h"))),
                                 "model_push": float(e), "price_dec": am_to_dec(a), "fair_p_decision": fop,
                                 "fair_p_close": None if cwin is None else float(cwin / (cwin + closs)),
                                 "close_push": None if cwin is None else float(ce), "outcome": out})
        # total at the open line
        tl = _f(r.get(f"{price_src}_tot"))
        ov, un = _f(r.get(f"{price_src}_over")), _f(r.get(f"{price_src}_under"))
        mut = _f(r.get(mut_col)) if mut_col else None
        sdt = _f(r.get(sdt_col)) if sdt_col else None
        if tl is not None and ov is not None and un is not None and mut is not None:
            fo = devig2(ov, un)
            if fo:
                o, e, u = V.total_probs(mut, sdt, tl)
                cm = _f(r.get("close_mu_tot"))
                if cm is not None:
                    co, ce, cu = V.total_probs(cm, sig_t, tl)
                else:
                    co = ce = cu = None
                tp = r["total_pts"]
                oo = 1.0 if tp > tl else (0.5 if tp == tl else 0.0)
                cpo, cpu = _f(r.get("close_over")), _f(r.get("close_under"))
                for side, a, pw_, pl_, fop, cwin, closs, out, cpr in (("over", ov, o, u, fo[0], co, cu, oo, cpo),
                                                                      ("under", un, u, o, fo[1], cu, co, 1 - oo, cpu)):
                    rows.append({**base, "market": "total", "selection": side, "line": tl, "model_p": float(pw_),
                                 "price_close": am_to_dec(cpr) if cpr is not None else None, "line_close": _f(r.get("close_tot")),
                                 "model_push": float(e), "price_dec": am_to_dec(a), "fair_p_decision": fop,
                                 "fair_p_close": None if cwin is None else float(cwin / (cwin + closs)),
                                 "close_push": None if cwin is None else float(ce), "outcome": out})
    s = pd.DataFrame(rows)
    if s.empty:
        return s
    pw = s["model_p"].astype(float)
    pp = s["model_push"].astype(float)
    s["model_ev"] = pw * (s["price_dec"] - 1) - (1 - pw - pp)
    fc = s["fair_p_close"].astype(float)
    cp = s["close_push"].astype(float).fillna(0.0)
    s["clv"] = fc * (1 - cp) * (s["price_dec"] - 1) - (1 - fc) * (1 - cp)
    same_line = (s["market"] == "moneyline") | (s.get("line_close").astype(float) == s["line"].astype(float)) if "line_close" in s else (s["market"] == "moneyline")
    s["price_clv"] = np.where(same_line, s["price_dec"] / s["price_close"].astype(float) - 1, np.nan)
    s["profit"] = np.where(s["outcome"] == 1.0, s["price_dec"] - 1, np.where(s["outcome"] == 0.5, 0.0, -1.0))
    s.loc[s["outcome"] == 0.5, "profit"] = 0.0
    return s


def summarize(s: pd.DataFrame, thr: float = 0.0, by: list[str] | None = None, edge_col: str = "model_ev") -> pd.DataFrame:
    """Bets = selections with edge > thr (one side per game-market at most: the larger edge). Mean CLV, ROI with
    day-clustered 95 % CIs; n bets; mean edge."""
    if s.empty:
        return pd.DataFrame()
    x = s[s[edge_col] > thr].copy()
    x = x.sort_values(edge_col, ascending=False).drop_duplicates(["event_id", "market"])
    groups = by or []
    out = []
    for key, g in (x.groupby(groups) if groups else [((), x)]):
        gc = g.dropna(subset=["clv"])
        clv = V.boot_ci(gc["clv"].to_numpy(), gc["day"].astype(str).to_numpy()) if len(gc) else (np.nan,) * 3
        roi = V.boot_ci(g["profit"].to_numpy(), g["day"].astype(str).to_numpy()) if len(g) else (np.nan,) * 3
        rec = dict(zip(groups, key if isinstance(key, tuple) else (key,))) if groups else {}
        pc = g["price_clv"].dropna() if "price_clv" in g else pd.Series(dtype=float)
        rec.update({"thr": thr, "n": len(g), "edge": g[edge_col].mean(), "clv": clv[0], "clv_lo": clv[1], "clv_hi": clv[2],
                    "price_clv": float(pc.mean()) if len(pc) else np.nan, "n_price_clv": int(len(pc)),
                    "beat_close": float((gc["fair_p_close"] > 1 / gc["price_dec"]).mean()) if len(gc) else np.nan,
                    "roi": roi[0], "roi_lo": roi[1], "roi_hi": roi[2]})
        out.append(rec)
    return pd.DataFrame(out)
