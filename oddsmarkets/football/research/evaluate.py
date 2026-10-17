"""
Scoring of walk-forward predictions against the market (EDGE_PROTOCOL.md section 1).

Everything here takes the frame produced by `walkforward.run` (one row per match with
p_h/p_d/p_a, p_o25, AH half-line probabilities, and the football-data price columns).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.common.edge import devig as _dv

EPS = 1e-12


def logloss3(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(p[np.arange(len(y)), y], EPS, 1))


def brier3(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    Y = np.zeros_like(p)
    Y[np.arange(len(y)), y] = 1
    return ((p - Y) ** 2).sum(1)


def logloss2(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -(y * np.log(np.clip(p, EPS, 1)) + (1 - y) * np.log(np.clip(1 - p, EPS, 1)))


def boot_ci(x: np.ndarray, groups: np.ndarray | None = None, n: int = 2000, seed: int = 7,
            stat=np.mean) -> tuple[float, float, float]:
    """Mean and 95% bootstrap CI; resamples whole groups (matches) when given."""
    x = np.asarray(x, float)
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    if groups is None:
        bs = [stat(x[rng.integers(0, len(x), len(x))]) for _ in range(n)]
    else:
        codes, inv = np.unique(groups, return_inverse=True)
        sums = np.bincount(inv, x)
        cnts = np.bincount(inv)
        k = len(codes)
        bs = []
        for _ in range(n):
            s = rng.integers(0, k, k)
            bs.append(sums[s].sum() / cnts[s].sum())
    return float(stat(x)), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def model_probs(R: pd.DataFrame) -> np.ndarray:
    return R[["p_h", "p_d", "p_a"]].to_numpy(float)


def fair(R: pd.DataFrame, which: str) -> np.ndarray:
    return R[[f"{which}_h", f"{which}_d", f"{which}_a"]].to_numpy(float)


def accuracy_table(R: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Log-loss and Brier: model v Pinnacle snapshot v Pinnacle close, on common matches."""
    rows = []
    groups = [("all", R)] if by is None else list(R.groupby(by))
    for key, g in groups:
        P = model_probs(g)
        fo, fc = fair(g, "fo"), fair(g, "fc")
        y = g["result"].to_numpy(int)
        ok = np.isfinite(P).all(1) & np.isfinite(fc).all(1)
        has_open = ok & np.isfinite(fo).all(1)
        rec = {by or "set": key, "n": int(ok.sum()), "n_open": int(has_open.sum())}
        rec["ll_model"] = logloss3(P[ok], y[ok]).mean()
        rec["ll_close"] = logloss3(fc[ok], y[ok]).mean()
        rec["ll_model_o"] = logloss3(P[has_open], y[has_open]).mean() if has_open.any() else np.nan
        rec["ll_open"] = logloss3(fo[has_open], y[has_open]).mean() if has_open.any() else np.nan
        d = logloss3(P[has_open], y[has_open]) - logloss3(fo[has_open], y[has_open])
        m, lo, hi = boot_ci(d) if has_open.any() else (np.nan,) * 3
        rec["d_ll_vs_open"], rec["d_lo"], rec["d_hi"] = m, lo, hi
        d2 = logloss3(P[ok], y[ok]) - logloss3(fc[ok], y[ok])
        m2, lo2, hi2 = boot_ci(d2)
        rec["d_ll_vs_close"], rec["dc_lo"], rec["dc_hi"] = m2, lo2, hi2
        rec["brier_model"] = brier3(P[ok], y[ok]).mean()
        rec["brier_close"] = brier3(fc[ok], y[ok]).mean()
        # totals
        po = g["p_o25"].to_numpy(float)
        yo = ((g.hg + g.ag) > 2.5).to_numpy(float)
        fco = g["fair_close_o25"].to_numpy(float)
        foo = g["fair_open_o25"].to_numpy(float)
        okt = np.isfinite(fco) & np.isfinite(foo) & np.isfinite(po)
        rec["n_ou"] = int(okt.sum())
        if okt.any():
            rec["ll_ou_model"] = logloss2(po[okt], yo[okt]).mean()
            rec["ll_ou_open"] = logloss2(foo[okt], yo[okt]).mean()
            rec["ll_ou_close"] = logloss2(fco[okt], yo[okt]).mean()
        rows.append(rec)
    return pd.DataFrame(rows)


# ── bets ─────────────────────────────────────────────────────────────────────

def selections(R: pd.DataFrame, markets=("1x2", "ou25", "ah")) -> pd.DataFrame:
    """
    One row per selection per match with: model probability-equivalent, snapshot price
    (Pinnacle and market max), closing fair probability, outcome (fractional for AH).
    For AH the comparison uses the effective probability that makes EV zero at a price.
    """
    out = []
    base = R[["league", "season", "sy", "start_time", "snap", "home", "away", "hg", "ag"]].copy()
    base["event_id"] = (R["league"] + "|" + R["start_time"].dt.strftime("%Y%m%d%H%M") + "|" + R["home"] + "|" + R["away"]).to_numpy()
    if "1x2" in markets:
        fo, fc = fair(R, "fo"), fair(R, "fc")
        P = model_probs(R)
        y = R["result"].to_numpy(int)
        for k, (sel, c) in enumerate((("home", "h"), ("draw", "d"), ("away", "a"))):
            b = base.copy()
            b["market"], b["selection"], b["line"] = "1x2", sel, np.nan
            b["model_p"] = P[:, k]
            b["price_pin"] = R[f"ps_{c}"].to_numpy(float)
            b["price_max"] = R[f"max_{c}"].to_numpy(float)
            b["price_close"] = R[f"psc_{c}"].to_numpy(float)
            b["price_maxc"] = R[f"maxc_{c}"].to_numpy(float)
            b["fair_open"] = fo[:, k]
            b["fair_close"] = fc[:, k]
            b["outcome"] = (y == k).astype(float)
            out.append(b)
    if "ou25" in markets:
        po = R["p_o25"].to_numpy(float)
        tot = (R.hg + R.ag).to_numpy(float)
        for sel, p, pin, mx, pc, fo_, fc_, win in (
            ("over", po, "pin_o25", "max_o25", "pc_o25", R["fair_open_o25"], R["fair_close_o25"], tot > 2.5),
            ("under", 1 - po, "pin_u25", "max_u25", "pc_u25", 1 - R["fair_open_o25"], 1 - R["fair_close_o25"], tot < 2.5),
        ):
            b = base.copy()
            b["market"], b["selection"], b["line"] = "total", sel, 2.5
            b["model_p"] = p
            b["price_pin"] = R[pin].to_numpy(float)
            b["price_max"] = R[mx].to_numpy(float)
            b["price_close"] = R[pc].to_numpy(float)
            b["price_maxc"] = R["maxc_" + mx.split("_")[1]].to_numpy(float)
            b["fair_open"] = np.asarray(fo_, float)
            b["fair_close"] = np.asarray(fc_, float)
            b["outcome"] = win.astype(float)
            out.append(b)
    if "ah" in markets:
        # Only where the snapshot and closing lines agree (otherwise "closing fair p" of the
        # snapshot bet is not defined by the data).
        same = np.isclose(R["ah_line"].to_numpy(float), R["ahc_line"].to_numpy(float))
        gd = (R.hg - R.ag).to_numpy(float)
        line = R["ah_line"].to_numpy(float)
        for sel, ph, pa_, mh, pch in (("home", "pah_h", "pah_a", "maxah_h", "pcah_h"), ("away", "pah_a", "pah_h", "maxah_a", "pcah_a")):
            home = sel == "home"
            wlo, plo = R["aho_lo_w"].to_numpy(float), R["aho_lo_p"].to_numpy(float)
            whi, phi = R["aho_hi_w"].to_numpy(float), R["aho_hi_p"].to_numpy(float)
            if not home:
                wlo, whi = 1 - wlo - plo, 1 - whi - phi
            # effective p: the p for which a bet at price d has EV p_eff*d - 1 (no pushes)
            # EV(d) = 0.5*sum_halves[w*(d-1) - (1-w-p)]; set p_eff = 0.5*sum(w + ... ) / ... :
            # we keep the pieces and compute EV at any price instead.
            b = base.copy()
            b["market"], b["selection"] = "spread", sel
            b["line"] = line if home else -line
            b["_w"] = 0.5 * (wlo + whi)
            b["_l"] = 0.5 * ((1 - wlo - plo) + (1 - whi - phi))
            b["model_p"] = b["_w"] / (b["_w"] + b["_l"])
            b["price_pin"] = np.where(same, R[ph].to_numpy(float), np.nan)
            b["price_max"] = np.where(same, R[mh].to_numpy(float), np.nan)
            b["price_close"] = np.where(same, R[pch].to_numpy(float), np.nan)
            b["price_maxc"] = np.where(same, R["maxc" + mh[3:]].to_numpy(float), np.nan)
            o_open = devig(R[[ph, pa_]].to_numpy(float))[:, 0]
            o_close = devig(R[[pch, "pcah_a" if home else "pcah_h"]].to_numpy(float))[:, 0]
            b["fair_open"] = np.where(same, o_open, np.nan)
            b["fair_close"] = np.where(same, o_close, np.nan)
            w, p = _ah_outcome(gd, line, home)
            b["outcome"] = w + 0.5 * p   # fraction of stake-weight won; pushes count half (protocol: 0.5)
            b["_win"], b["_push"] = w, p
            out.append(b)
    S = pd.concat(out, ignore_index=True)
    return S


def devig(o):
    return _dv.multiplicative_rows(o, strict=False)          # common/edge/devig.py


def _ah_outcome(gd, line, home):
    q = np.round(np.nan_to_num(line) * 4) % 2 == 1
    w = np.zeros(len(gd))
    p = np.zeros(len(gd))
    for sh in (-0.25, 0.25):
        l2 = np.where(q, line + sh, line)
        m = gd + l2 if home else -(gd + l2)
        w += 0.5 * (m > 0)
        p += 0.5 * (m == 0)
    return w, p


def settle_return(S: pd.DataFrame, price: np.ndarray) -> np.ndarray:
    """Return per unit stake at `price`."""
    if "_win" in S.columns:
        w = S["_win"].to_numpy(float)
        p = S["_push"].to_numpy(float)
        isah = S["market"].to_numpy() == "spread"
        ah = w * (price - 1) - (1 - w - p)
        other = S["outcome"].to_numpy(float) * price - 1
        return np.where(isah, ah, other)
    return S["outcome"].to_numpy(float) * price - 1


def model_ev(S: pd.DataFrame, price: np.ndarray) -> np.ndarray:
    if "_w" in S.columns:
        isah = S["market"].to_numpy() == "spread"
        ah = S["_w"].to_numpy(float) * (price - 1) - S["_l"].to_numpy(float)
        return np.where(isah, ah, S["model_p"].to_numpy(float) * price - 1)
    return S["model_p"].to_numpy(float) * price - 1


def clv(S: pd.DataFrame, price: np.ndarray) -> np.ndarray:
    """Expected return of the bet at the de-vigged closing probability (AH: no-push basis)."""
    return S["fair_close"].to_numpy(float) * price - 1


def bet_table(S: pd.DataFrame, price_col: str = "price_pin", thresholds=(0.0, 0.02, 0.05, 0.10),
              by: list[str] | None = None, min_n: int = 30) -> pd.DataFrame:
    """Flat 1-unit bets wherever model EV at the decision price exceeds a threshold."""
    rows = []
    price = S[price_col].to_numpy(float)
    ok = np.isfinite(price) & (price > 1) & np.isfinite(S["fair_close"].to_numpy(float)) & np.isfinite(S["model_p"].to_numpy(float))
    ev = model_ev(S, price)
    c = clv(S, price)
    r = settle_return(S, price)
    keys = by or []
    G = [((), S.index)] if not keys else list(S.groupby(keys).groups.items())
    for key, ix in G:
        m_ix = np.zeros(len(S), bool)
        m_ix[S.index.get_indexer(ix)] = True
        for t in thresholds:
            sel = ok & m_ix & (ev > t)
            if sel.sum() < min_n:
                continue
            ev_id = S["event_id"].to_numpy()[sel]
            cm, clo, chi = boot_ci(c[sel], ev_id)
            rm, rlo, rhi = boot_ci(r[sel], ev_id)
            rec = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
            rec.update({"price": price_col, "thr": t, "n_bets": int(sel.sum()), "mean_ev_model": float(ev[sel].mean()),
                        "clv": cm, "clv_lo": clo, "clv_hi": chi, "roi": rm, "roi_lo": rlo, "roi_hi": rhi,
                        "avg_price": float(price[sel].mean())})
            rows.append(rec)
    return pd.DataFrame(rows)
