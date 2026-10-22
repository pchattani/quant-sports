"""
Market-implied ratings for The Quant Campus (round 4, October 2026; docs/research/college_edge.md).

The pro sites gained most from ratings learned from earlier games' closing lines (`basketball/models/informed.py`).
This is the college version, shared by football and basketball:

    -spread_home(g) = h [not neutral] + r_home - r_away + e      (closing spreads of games on days before D)
    total(g)        = c + t_home + t_away + e                     (closing totals, same form)

solved by weighted ridge (weight 0.5^(age / half_life days)) toward a preseason prior:

    prior_t = cm + carry (r_end_t - cm)     r_end = last season's final market rating, cm = last season's mean of the
                                            team's current conference (realignment carries the new conference's level)
    teams without a market rating last season start at cm, else at the mean of their group (FBS / FCS; D-I)

`season_path` returns, for every requested game day, the solution from lines of earlier days only, so every
prediction is walk-forward. The stacking of these ratings with each level's own model lives with the level
(`football/informed_stack.py`, `hoops/informed_stack.py`); this module is the shared ridge.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm

HOME_PRIOR = {"spread": 2.5, "total": 0.0}
EPS = 1e-4


def _solve(T: int, hi: np.ndarray, ai: np.ndarray, y: np.ndarray, w: np.ndarray, nn: np.ndarray, prior: np.ndarray,
           lam: float, kind: str, c_prior: float) -> np.ndarray:
    """[h or c, r_0..r_{T-1}] by weighted ridge (normal equations). The first column is the home term (spread) or the
    intercept (total); team effects enter +/- (spread) or +/+ (total)."""
    n = T + 1
    A = np.zeros((n, n))
    b = np.zeros(n)
    sgn = -1.0 if kind == "spread" else 1.0
    x0 = nn if kind == "spread" else np.ones(len(y))
    h1, a1 = hi + 1, ai + 1
    np.add.at(A, (0, 0), np.sum(w * x0 * x0))
    np.add.at(A, (h1, h1), w)
    np.add.at(A, (a1, a1), w)
    np.add.at(A, (h1, a1), sgn * w)
    np.add.at(A, (a1, h1), sgn * w)
    np.add.at(A, (0, h1), w * x0)
    np.add.at(A, (h1, 0), w * x0)
    np.add.at(A, (0, a1), sgn * w * x0)
    np.add.at(A, (a1, 0), sgn * w * x0)
    b[0] = np.sum(w * x0 * y)
    np.add.at(b, h1, w * y)
    np.add.at(b, a1, sgn * w * y)
    A[np.arange(1, n), np.arange(1, n)] += lam
    b[1:] += lam * prior
    k0 = 1e-2 if kind == "spread" else 1e-6
    A[0, 0] += k0
    b[0] += k0 * c_prior
    return np.linalg.solve(A, b)


def season_path(days: np.ndarray, home: Iterable[str], away: Iterable[str], neutral: np.ndarray, y: np.ndarray,
                want: Iterable[int], *, kind: str = "spread", prior: dict[str, float] | None = None,
                half_life: float = 60.0, lam: float = 1.0, teams: Iterable[str] | None = None) -> dict[int, dict]:
    """Market ratings for each day of `want` (ints, e.g. date ordinals) from the rows with day < D and a finite y.
    y is the home margin implied by the line (-spread_home) for kind "spread", the closing total for "total".
    Returns {D: {"h": home term or intercept, "r": {team: rating}, "n": lines used, "nt": {team: lines used}}}."""
    days = np.asarray(days, dtype=np.int64)
    home = np.asarray([str(t) for t in home], dtype=object)
    away = np.asarray([str(t) for t in away], dtype=object)
    neutral = np.asarray(neutral, dtype=bool)
    y = np.asarray(y, dtype=float)
    prior = dict(prior or {})
    tl = sorted(set(home.tolist()) | set(away.tolist()) | set(prior) | {str(t) for t in (teams or [])})
    ix = {t: i for i, t in enumerate(tl)}
    T = len(tl)
    hi = np.array([ix[t] for t in home], dtype=np.int64)
    ai = np.array([ix[t] for t in away], dtype=np.int64)
    pr = np.array([float(prior.get(t, 0.0)) for t in tl])
    nn = (~neutral).astype(float)
    ok = np.isfinite(y)
    c_prior = HOME_PRIOR[kind] if kind == "spread" else (float(np.nanmean(y)) if ok.any() else 0.0)
    out: dict[int, dict] = {}
    cache_n = -1
    sol = None
    order = np.argsort(days, kind="mergesort")
    sd = days[order]
    for D in sorted({int(d) for d in want}):
        k = int(np.searchsorted(sd, D, side="left"))          # rows with day < D
        m = np.zeros(len(y), dtype=bool)
        m[order[:k]] = True
        m &= ok
        n = int(m.sum())
        if n == 0:
            sol = np.concatenate([[c_prior], pr])
        elif half_life >= 1e5 and n == cache_n and sol is not None:
            pass
        else:
            w = 0.5 ** ((D - days[m]) / float(half_life))
            sol = _solve(T, hi[m], ai[m], y[m], w, nn[m], pr, lam, kind, c_prior)
        cache_n = n
        nt: dict[str, int] = defaultdict(int)
        if n:
            for t in home[m]:
                nt[t] += 1
            for t in away[m]:
                nt[t] += 1
        out[D] = {"h": float(sol[0]), "r": {t: float(sol[1 + i]) for t, i in ix.items()}, "n": n, "nt": dict(nt)}
    return out


def carry_prior(end: dict[str, float] | None, conf_last: dict[str, str | None], conf_now: dict[str, str | None],
                group_now: dict[str, str], carry: float) -> dict[str, float]:
    """This season's prior from last season's final market ratings `end` (centred on the mean of the teams that are
    in a group this season). conf_last/conf_now: {team: conference}; group_now: {team: "fbs"|"fcs"|"d1"|...}."""
    if not end:
        return {}
    by_conf: dict[str, list[float]] = defaultdict(list)
    by_group: dict[str, list[float]] = defaultdict(list)
    for t, v in end.items():
        c = conf_now.get(t) if conf_now.get(t) is not None else conf_last.get(t)
        if c is not None:
            by_conf[str(c)].append(v)
        g = group_now.get(t)
        if g is not None:
            by_group[g].append(v)
    cm = {c: float(np.mean(v)) for c, v in by_conf.items()}
    gm = {g: float(np.mean(v)) for g, v in by_group.items()}
    out = {}
    for t in set(conf_now) | set(group_now) | set(end):
        c = conf_now.get(t)
        base = cm.get(str(c)) if c is not None and str(c) in cm else gm.get(group_now.get(t, ""), float(np.mean(list(end.values()))))
        if t in end:
            out[t] = base + carry * (end[t] - base)
        else:
            out[t] = base
    return out


# ── season features, stacking and calibration (research and production share these) ─────────────────

def season_market(R: pd.DataFrame, half_life: float, lam: float, carry: float, kind: str = "spread",
                  base: str | None = None, end_prev: dict | None = None, conf_prev: dict | None = None):
    """One season's rows R (season, dayn, home, away, neutral, conf_h/a, group_h/a, fit_line, spread or ctotal, and
    `base` for residual ratings): (DataFrame mk, nl_h, nl_a on R's index; the season's final ratings, centred, or
    None when it had fewer than 30 lines; {team: conference}). `end_prev` / `conf_prev`: last season's (the prior)."""
    ycol = "spread" if kind == "spread" else "ctotal"
    conf_now = dict(zip(R["home"], R["conf_h"])) | dict(zip(R["away"], R["conf_a"]))
    grp_now = dict(zip(R["home"], R["group_h"])) | dict(zip(R["away"], R["group_a"]))
    prior = carry_prior(end_prev, conf_prev or {}, conf_now, grp_now, carry) if end_prev else {}
    L = R[R["fit_line"].astype(bool) & np.isfinite(R[ycol].astype(float))]
    y = -L["spread"].to_numpy(float) if kind == "spread" else L["ctotal"].to_numpy(float)
    if base is not None:                 # residual ratings: what the line says beyond the base prediction
        y = y - L[base].to_numpy(float)
        okb = np.isfinite(y)
        L, y = L[okb], y[okb]
    last = int(R["dayn"].max()) + 1
    want = sorted(set(R["dayn"].astype(int).tolist()) | {last})
    path = season_path(L["dayn"].to_numpy(), L["home"], L["away"], L["neutral"].to_numpy(bool), y, want,
                       kind=kind, prior=prior, half_life=half_life, lam=lam, teams=list(conf_now))
    mk = np.full(len(R), np.nan)
    nlh = np.zeros(len(R))
    nla = np.zeros(len(R))
    for j, (d, h, a, neu) in enumerate(zip(R["dayn"].astype(int), R["home"], R["away"], R["neutral"])):
        sol = path[d]
        rh, ra = sol["r"].get(h), sol["r"].get(a)
        if rh is None or ra is None:
            continue
        mk[j] = (sol["h"] * (0.0 if neu else 1.0) + rh - ra) if kind == "spread" else (sol["h"] + rh + ra)
        nlh[j] = sol["nt"].get(h, 0)
        nla[j] = sol["nt"].get(a, 0)
    out = pd.DataFrame({"mk": mk, "nl_h": nlh, "nl_a": nla}, index=R.index)
    e = path[last]["r"]
    end = None
    if len(L) >= 30:
        mu = float(np.mean([e[t] for t in conf_now if t in e]))        # centre: only differences matter
        end = {t: e[t] - mu for t in conf_now if t in e}
    return out, end, conf_now


def market_features(F: pd.DataFrame, half_life: float, lam: float, carry: float, kind: str = "spread",
                    seasons: list[int] | None = None, base: str | None = None) -> pd.DataFrame:
    """Per row: mk (h [not neutral] + r_h - r_a, or c + t_h + t_a for totals), nl_h / nl_a (lines per team before
    the day this season), from closing lines of earlier days; prior chained from the season before.
    attrs["ends"] = {season: (final ratings, conferences)} (the next season's prior)."""
    out = pd.DataFrame(index=F.index, data={"mk": np.nan, "nl_h": 0.0, "nl_a": 0.0})
    end_prev, conf_prev = None, {}
    ends = {}
    for s in sorted(F["season"].unique()):
        if seasons is not None and s not in seasons and s + 1 not in seasons:
            end_prev = None
            continue
        R = F[F["season"] == s]
        o, end, conf_now = season_market(R, half_life, lam, carry, kind, base, end_prev, conf_prev)
        out.loc[R.index, ["mk", "nl_h", "nl_a"]] = o[["mk", "nl_h", "nl_a"]].to_numpy()
        ends[int(s)] = (end, conf_now)
        end_prev, conf_prev = (end, conf_now) if end is not None else (None, {})
    out.attrs["ends"] = ends
    return out


# ── stacking and calibration ───────────────────────────────────────────────

def _ls(X, y, ridge=1e-3):
    s = X.std(axis=0)
    s[s == 0] = 1.0
    P = np.diag(ridge * len(y) * (s ** 2))
    P[0, 0] = 0.0
    return np.linalg.solve(X.T @ X + P + 1e-9 * np.eye(X.shape[1]), X.T @ y)


def probit_fit(mu: np.ndarray, y: np.ndarray, ph: np.ndarray) -> dict:
    phases = ["early", "mid", "post"]
    pidx = np.array([phases.index(p) for p in ph])

    def nll(th):
        sd = np.exp(th[1:])[pidx]
        p = np.clip(norm.cdf((mu + th[0]) / sd), EPS, 1 - EPS)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    th0 = np.array([0.0, np.log(15.0 if np.std(mu) > 8 else 11.0)] + [np.log(15.0 if np.std(mu) > 8 else 11.0)] * 2)
    r = minimize(nll, th0, method="L-BFGS-B")
    th = r.x
    for k, p in enumerate(phases):           # a phase without data keeps the mid sd
        if not (pidx == k).any():
            th[1 + k] = th[2]
    return {"c0": float(th[0]), "sd": {p: float(np.exp(th[1 + k])) for k, p in enumerate(phases)}}


def probit_apply(cal: dict, mu: np.ndarray, ph: np.ndarray) -> np.ndarray:
    sd = np.array([cal["sd"].get(p, cal["sd"]["mid"]) for p in ph])
    return norm.cdf((mu + cal["c0"]) / sd)


def walk_stack(F: pd.DataFrame, X: np.ndarray, level: str, target: str = "close", calibrate: bool = True,
               train0: int = 2013, cal_window: int | None = None) -> pd.DataFrame:
    """Walk-forward by season: coefficients for season S from seasons train0..S-1 (lined rows for "close", scope rows
    for "outcome"); probit calibration for S from the walk-forward predictions of earlier seasons (the last
    `cal_window` of them when given)."""
    t0 = train0
    seasons = sorted(F["season"].unique())
    mu = np.full(len(F), np.nan)
    p = np.full(len(F), np.nan)
    okX = np.all(np.isfinite(X), axis=1)
    coefs = {}
    for s in seasons:
        if s <= t0:
            continue
        tr = (F["season"] >= t0) & (F["season"] < s) & okX
        if target == "close":
            tr &= F["fit_line"] & np.isfinite(F["spread"])
            yt = -F["spread"].to_numpy(float)
        else:
            tr &= F["scope"]
            yt = F["y"].to_numpy(float)
        tr = tr.to_numpy(bool)
        if tr.sum() < 300:
            continue
        b = _ls(X[tr], yt[tr])
        coefs[int(s)] = b
        cur = (F["season"] == s).to_numpy(bool) & okX
        mu[cur] = X[cur] @ b
    yb = (F["y"].to_numpy(float) > 0).astype(float)
    cals = {}
    for s in seasons:
        cur = (F["season"] == s).to_numpy(bool) & np.isfinite(mu)
        if not cur.any():
            continue
        tr = (F["season"] < s).to_numpy(bool) & np.isfinite(mu) & F["scope"].to_numpy(bool)
        if cal_window:
            tr &= (F["season"] >= s - cal_window).to_numpy(bool)
        if calibrate and tr.sum() >= 300:
            cal = probit_fit(mu[tr], yb[tr], F["phase"].to_numpy()[tr])
        else:
            cal = {"c0": 0.0, "sd": {"early": float(np.nanmedian(F["sd0"])), "mid": float(np.nanmedian(F["sd0"])),
                                     "post": float(np.nanmedian(F["sd0"]))}}
        cals[int(s)] = cal
        p[cur] = probit_apply(cal, mu[cur], F["phase"].to_numpy()[cur])
    out = pd.DataFrame({"mu": mu, "p": p}, index=F.index)
    out.attrs["coefs"] = {k: [round(float(x), 4) for x in v] for k, v in coefs.items()}
    out.attrs["cals"] = cals
    return out




def _mk(F, spec, base=None, kind="spread", cache: dict | None = None):
    key = (id(F), len(F), kind, base, spec["half_life"], spec["lam"], spec["carry"])
    if cache is not None and key in cache:
        return cache[key]
    out = market_features(F, spec["half_life"], spec["lam"], spec["carry"], kind=kind, base=base)
    if cache is not None:
        cache[key] = out
    return out


def features_for(F, level, cfg, cache: dict | None = None, pre: dict | None = None):
    """Design matrix of a candidate cfg = {"mk": spec|None, "rd": spec|None, "target", "extra": [...]}.
    `pre` = {"mk": frame, "rd": frame} supplies precomputed market features (production: one season)."""
    early = None
    pre = pre or {}
    cols = {"const": np.ones(len(F)), "nn": (~F["neutral"].to_numpy(bool)).astype(float), "m0": F["m0"].to_numpy(float)}
    if cfg.get("mk"):
        M = pre["mk"] if "mk" in pre else _mk(F, cfg["mk"], cache=cache)
        early = ((M["nl_h"] < 2) | (M["nl_a"] < 2)).to_numpy(float)
        cols["mk"] = M["mk"].to_numpy(float)
    if cfg.get("rd"):
        Rd = pre["rd"] if "rd" in pre else _mk(F, cfg["rd"], base="m0", cache=cache)
        if early is None:
            early = ((Rd["nl_h"] < 2) | (Rd["nl_a"] < 2)).to_numpy(float)
        cols["rd"] = Rd["mk"].to_numpy(float)
    if early is not None and not cfg.get("no_inter"):
        for c in [k for k in ("mk", "m0", "rd") if k in cols]:
            cols[c + "_early"] = cols[c] * early
        if level == "cfb":
            fcs = F["fcs"].to_numpy(float)
            for c in [k for k in ("mk", "m0") if k in cols]:
                cols[c + "_fcs"] = cols[c] * fcs
    for c in cfg.get("extra") or []:
        if c.endswith("*early"):
            cols[c] = F[c[:-6]].to_numpy(float) * (early if early is not None else 1.0)
        else:
            cols[c] = F[c].to_numpy(float)
    names = list(cols)
    return np.column_stack([cols[c] for c in names]), names


def run_cfg(F, level, cfg, train0: int = 2013, cache: dict | None = None):
    """The walk-forward informed predictions of a candidate: DataFrame mu, p (+ attrs names, coefs, cals)."""
    X, names = features_for(F, level, cfg, cache)
    W = walk_stack(F, X, level, cfg.get("target", "close"), train0=train0, cal_window=cfg.get("cal_window"))
    W.attrs["names"] = names
    W.attrs["X"] = X
    return W


def predict_season(R: pd.DataFrame, level: str, fit: dict) -> pd.DataFrame:
    """Production: one season's rows R (as the research frame: m0, lines, conferences, phase, extras) predicted
    with a committed fit (`fitted/informed_<level>.json`: cfg, names, coefs, cal, priors). Returns mu, p, mk (the
    market-rating line: h + r_home - r_away), rd (the residual-rating term), early."""
    cfg = fit["cfg"]
    pre = {}
    for k, base in (("mk", None), ("rd", "m0")):
        if cfg.get(k):
            sp = cfg[k]
            pr = (fit.get("prior") or {}).get(k) or {}
            o, _, _ = season_market(R, sp["half_life"], sp["lam"], sp["carry"], "spread", base, pr.get("end"),
                                    pr.get("conf"))
            pre[k] = o
    X, names = features_for(R, level, cfg, pre=pre)
    if list(names) != list(fit["names"]):
        raise ValueError(f"feature names {names} differ from the fit's {fit['names']}")
    mu = X @ np.asarray(fit["coefs"], float)
    p = probit_apply(fit["cal"], mu, R["phase"].to_numpy())
    out = pd.DataFrame({"mu": mu, "p": p}, index=R.index)
    for k in pre:
        out[k] = pre[k]["mk"].to_numpy(float)
    first = pre.get("mk") if "mk" in pre else pre.get("rd")
    out["early"] = ((first["nl_h"] < 2) | (first["nl_a"] < 2)).to_numpy(bool) if first is not None else False
    return out


# ── committed fits and their validation (calibration.json) ──────────────────

FITTED_DIR = __import__("pathlib").Path(__file__).resolve().parent / "fitted"
STATUS_TEXT = {
    "promoted": "Published model: the base ratings model stacked with market-implied ratings (promoted on the sealed "
                "test seasons under the pre-registered rule).",
    "trial": "On trial: shown beside the published model, not used for it. The sealed test improved log-loss but missed "
             "the calibration-slope tolerance; a recalibrated version is being tested forward on the current season.",
    "not promoted": "Tested and not promoted: no improvement on the sealed test seasons; the base model stays.",
}


def load_fit(level: str) -> dict | None:
    import json
    try:
        return json.loads((FITTED_DIR / f"informed_{level}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def summary(level: str) -> dict | None:
    """A compact block for calibration.json: status, what the model is, dev and sealed-test numbers v the base model
    and v the market (research log: docs/research/college_edge.md)."""
    f = load_fit(level)
    if not f:
        return None
    v = f.get("validation") or {}

    def blk(r):
        if not r:
            return None
        out = {k: r.get(k) for k in ("n", "ll0", "ll1", "d_ll", "brier0", "brier1", "ece0", "ece1", "slope0", "slope1")}
        for k in ("ml_games", "mae_close_games", "open_games"):
            if r.get(k):
                out[k] = r[k]
        return out
    status = f.get("status") or ("promoted" if (v.get("verdict") or {}).get("promote") else "not promoted")
    return {"status": status, "text": STATUS_TEXT.get(status), "season": f.get("season"),
            "features": f.get("names"), "coefs": f.get("coefs"), "cal": f.get("cal"), "cfg": f.get("cfg"),
            "dev": blk(v.get("dev")), "test": blk(v.get("test")), "verdict": v.get("verdict"),
            "per_season": v.get("per_season"), "tested_cfg": v.get("cfg"), "note": f.get("note")}
