"""
Pregame goal model: expected goals -> regulation score distribution (bivariate Poisson, late-game empty-net chain)
-> overtime and shootout -> win, regulation win, P(OT), puck line, totals.

Means (one Poisson log-linear model per side, fitted walk-forward by `fit_from_rows`)
---------------------------------------------------------------------------------
    log mu_h = b0 + b_xg log Gxg_h + b_g log Gg_h + home * 1[not neutral] + 1/2 s . f
    log mu_a = b0 + b_xg log Gxg_a + b_g log Gg_a                         - 1/2 s . f
Gxg = team_strength.expected_goals (5v5 xG, special teams, finishing, the *opposing starter's* goaltending);
Gg = team_strength.goals_model (goals-only ratings, a second opinion); f = schedule features home minus away
(back-to-back, rest days capped at 3, travel km / 1000, |time-zone change|), s their coefficients. mu is a team's
regulation goals before the empty-net chain below.

Regulation distribution
-----------------------
Minutes 0-57: bivariate Poisson, X = U + W, Y = V + W with U ~ P(mu_h' - l3), V ~ P(mu_a' - l3), W ~ P(l3),
mu' = mu * 57/60 and l3 = theta * min(mu_h', mu_a') (theta >= 0 adds correlation and ties).
Minutes 57-60: a Markov chain on the score in 10-second steps (at most one goal per step). Rates per minute are
mu/60, except: tied -> both x tie_k (teams play for the overtime point); trailing by one with <= pull1 minutes left,
or by two with <= pull2 minutes left -> the trailing side's goalie is pulled: its rate x k_pull and the leader adds
r_en per minute (empty-net goals). Scores are tracked 0..12 (mass above is held at 12).

Overtime (tied after regulation)
--------------------------------
Regular season: 5 minutes (3-on-3 from 2015-16, 4-on-4 before); P(goal) = 1 - exp(-5 k_ot (mu_h + mu_a) / 60),
k_ot by era; the scorer is home with probability mu_h / (mu_h + mu_a); otherwise a shootout won by the home side
with probability so_home. Playoffs: sudden-death 5-on-5 until a goal, home with probability mu_h / (mu_h + mu_a).
The NHL credits the shootout winner with one goal, so final score = regulation score + 1 for the winner of any game
past regulation (totals and puck lines are settled on that score: an overtime game never covers -1.5).

Outputs: p_home (any manner), p_reg_home / p_reg_away, p_ot (regulation tie), p_ot_home (wins in OT or SO), p_so,
puck line P(home -1.5) = P(final margin >= 2), P(away -1.5), totals pmf of the final score, exp goals.
Market helpers: `ml_to_p` (multiplicative de-vig of American moneylines), `ou_to_p`, `pl_to_p`.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import gammaln

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import team_strength as TS

logger = logging.getLogger(__name__)

VERSION = 1
NMAX = 12
T_LATE = 3.0
STEP_S = 10.0
SCHED = TS.SCHED_FEATURES
DEFAULTS: dict[str, Any] = {
    "b0": 0.0, "b_xg": 1.0, "b_g": 0.0, "home": 0.045,
    "s": {"b2b": -0.06, "rest": 0.01, "travel": -0.01, "tz": -0.01},
    "theta": 0.08, "tie_k": 0.85, "k_pull": 2.2, "r_en": 0.22, "pull1": 2.0, "pull2": 3.0,
    "k_ot": {"3v3": 1.85, "4v4": 1.2}, "so_home": 0.5,
    "fitted": False, "n": 0,
}
_P: dict | None = None


def params(over: dict | None = None) -> dict:
    global _P
    if _P is None:
        p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
        for path in (D.c_cache() / "game_params.json", D.FITTED / "game_params.json"):
            c = D.read_json(path)
            if c:
                for k, v in (c.get("result") or c).items():
                    if v is None:
                        continue
                    if isinstance(v, dict) and isinstance(p.get(k), dict):
                        p[k].update(v)
                    else:
                        p[k] = v
                break
        _P = p
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in _P.items()}
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def set_params(p: dict | None) -> None:
    global _P
    _P = None if p is None else {**{k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}, **p}


def ot_era(season: int | None) -> str:
    return "4v4" if season is not None and D.start_year(season) <= 2014 else "3v3"


# ── distributions ────────────────────────────────────────────────────────────

_K = np.arange(NMAX + 1)


def _pois(lam: np.ndarray) -> np.ndarray:
    """(G, NMAX+1) Poisson pmf with the upper tail folded into NMAX."""
    lam = np.maximum(np.asarray(lam, float), 1e-9)[:, None]
    lp = _K[None, :] * np.log(lam) - lam - gammaln(_K + 1)[None, :]
    P = np.exp(lp)
    P[:, -1] += np.maximum(1.0 - P.sum(1), 0.0)
    return P


def bivariate(mu_h, mu_a, theta: float) -> np.ndarray:
    """(G, N, N) bivariate Poisson pmf P[x, y], l3 = theta * min(mu_h, mu_a)."""
    mu_h = np.atleast_1d(np.asarray(mu_h, float))
    mu_a = np.atleast_1d(np.asarray(mu_a, float))
    l3 = np.clip(theta, 0.0, 0.9) * np.minimum(mu_h, mu_a)
    U, V, W = _pois(mu_h - l3), _pois(mu_a - l3), _pois(l3)
    N = NMAX + 1
    P = np.zeros((len(mu_h), N, N))
    for w in range(N):
        pw = W[:, w]
        if not np.any(pw > 1e-12):
            continue
        n = N - w
        P[:, w:, w:] += pw[:, None, None] * U[:, :n, None] * V[:, None, :n]
    P /= P.sum((1, 2), keepdims=True)
    return P


_DIFF = _K[:, None] - _K[None, :]


def late_chain(P: np.ndarray, mu_h, mu_a, p: dict, minutes: float = T_LATE, step_s: float = STEP_S) -> np.ndarray:
    """Run the last `minutes` of regulation on a score pmf P (G, N, N) (see module doc)."""
    mu_h = np.atleast_1d(np.asarray(mu_h, float))[:, None, None] / 60.0
    mu_a = np.atleast_1d(np.asarray(mu_a, float))[:, None, None] / 60.0
    steps = int(round(minutes * 60 / step_s))
    dt = step_s / 60.0
    tie = (_DIFF == 0)[None]
    for k in range(steps):
        left = minutes - k * dt                       # minutes remaining at the start of the step
        pulled_h = (((_DIFF == -1) & (left <= p["pull1"])) | ((_DIFF == -2) & (left <= p["pull2"])))[None]
        pulled_a = (((_DIFF == 1) & (left <= p["pull1"])) | ((_DIFF == 2) & (left <= p["pull2"])))[None]
        rh = np.where(tie, mu_h * p["tie_k"], mu_h)
        ra = np.where(tie, mu_a * p["tie_k"], mu_a)
        rh = np.where(pulled_h, mu_h * p["k_pull"], np.where(pulled_a, rh + p["r_en"], rh))
        ra = np.where(pulled_a, mu_a * p["k_pull"], np.where(pulled_h, ra + p["r_en"], ra))
        ph = np.clip(rh * dt, 0, 0.45)
        pa = np.clip(ra * dt, 0, 0.45)
        stay = P * (1.0 - ph - pa)
        gh = P * ph
        ga = P * pa
        new = stay
        new[:, 1:, :] += gh[:, :-1, :]
        new[:, -1, :] += gh[:, -1, :]
        new[:, :, 1:] += ga[:, :, :-1]
        new[:, :, -1] += ga[:, :, -1]
        P = new
    return P


def regulation(mu_h, mu_a, p: dict) -> np.ndarray:
    f = (60.0 - T_LATE) / 60.0
    P = bivariate(np.asarray(mu_h) * f, np.asarray(mu_a) * f, p["theta"])
    return late_chain(P, mu_h, mu_a, p)


def outcome_probs(mu_h, mu_a, p: dict | None = None, playoff=False, season: int | None = None, full: bool = False) -> dict:
    """Vectorised game probabilities (arrays over games). full=True adds "reg" (G,N,N) and "final_total" (G, 2N)."""
    p = p or params()
    mu_h = np.atleast_1d(np.asarray(mu_h, float))
    mu_a = np.atleast_1d(np.asarray(mu_a, float))
    R = regulation(mu_h, mu_a, p)
    G = len(mu_h)
    up = np.triu(np.ones((NMAX + 1, NMAX + 1)), 1).astype(bool)      # x < y
    p_reg_a = R[:, up].sum(1)
    p_reg_h = R[:, up.T].sum(1)
    diag = np.einsum("gii->gi", R)
    p_ot = diag.sum(1)
    share = mu_h / np.maximum(mu_h + mu_a, 1e-9)
    po = np.broadcast_to(np.asarray(playoff, bool), (G,))
    k_ot = p["k_ot"][ot_era(season)] if isinstance(p.get("k_ot"), dict) else float(p["k_ot"])
    p_dec = 1.0 - np.exp(-5.0 * k_ot * (mu_h + mu_a) / 60.0)
    h_ot = np.where(po, share, p_dec * share + (1 - p_dec) * p["so_home"])
    p_ot_home = p_ot * h_ot
    p_so = np.where(po, 0.0, p_ot * (1 - p_dec))
    # final margin >= 2 only in regulation
    d = _DIFF[None]
    pl_h = (R * (d >= 2)).sum((1, 2))
    pl_a = (R * (d <= -2)).sum((1, 2))
    out = {"p_home": p_reg_h + p_ot_home, "p_reg_home": p_reg_h, "p_reg_away": p_reg_a, "p_ot": p_ot,
           "p_ot_home": p_ot_home, "p_so": p_so, "pl_home": pl_h, "pl_away": pl_a,
           "exp_h": (R.sum(2) * _K[None]).sum(1) + p_ot_home, "exp_a": (R.sum(1) * _K[None]).sum(1) + (p_ot - p_ot_home)}
    tot = np.zeros((G, 2 * NMAX + 2))
    s = (_K[:, None] + _K[None, :])
    for t in range(2 * NMAX + 1):
        m = (s == t)
        nt = (R * (m & (_DIFF != 0))[None]).sum((1, 2))
        tie_t = (R * (m & (_DIFF == 0))[None]).sum((1, 2))
        tot[:, t] += nt
        tot[:, t + 1] += tie_t
    out["total_pmf"] = tot
    out["exp_total"] = (tot * np.arange(tot.shape[1])[None]).sum(1)
    if full:
        out["reg"] = R
    return out


def total_over(total_pmf: np.ndarray, line: float) -> np.ndarray:
    k = np.arange(total_pmf.shape[-1])
    return (total_pmf * (k > line)).sum(-1)


def total_push(total_pmf: np.ndarray, line: float) -> np.ndarray:
    k = np.arange(total_pmf.shape[-1])
    return (total_pmf * (np.abs(k - line) < 1e-9)).sum(-1)


def fair_total(total_pmf: np.ndarray) -> np.ndarray:
    """The half-goal line nearest an even over / under."""
    lines = np.arange(0.5, total_pmf.shape[-1] - 1, 1.0)
    ov = np.stack([total_over(total_pmf, l) for l in lines], -1)
    return lines[np.argmin(np.abs(ov - 0.5), -1)]


# ── market helpers ───────────────────────────────────────────────────────────

def american_to_p(ml) -> float | None:
    try:
        x = float(ml)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x == 0 or -100 < x < 100:
        return None
    return 100.0 / (x + 100.0) if x > 0 else -x / (-x + 100.0)


def ml_to_p(ml_home, ml_away) -> float | None:
    a, b = american_to_p(ml_home), american_to_p(ml_away)
    if a is None or b is None:
        return None
    return a / (a + b)


def two_way(price_a, price_b) -> float | None:
    """De-vigged probability of side a from two American prices."""
    return ml_to_p(price_a, price_b)


# ── means ────────────────────────────────────────────────────────────────────

def means(F: pd.DataFrame, p: dict) -> tuple[np.ndarray, np.ndarray]:
    """mu_h, mu_a from the feature frame (lx_h, lx_a, lg_h, lg_a, home, sched features)."""
    s = p.get("s") or {}
    sf = sum(float(s.get(k, 0.0)) * F[k].to_numpy(float) for k in SCHED) if len(F) else np.zeros(0)
    base_h = p["b0"] + p["b_xg"] * F["lx_h"].to_numpy(float) + p["b_g"] * F["lg_h"].to_numpy(float)
    base_a = p["b0"] + p["b_xg"] * F["lx_a"].to_numpy(float) + p["b_g"] * F["lg_a"].to_numpy(float)
    hm = p["home"] * F["hfa"].to_numpy(float)
    return np.exp(base_h + hm + 0.5 * sf), np.exp(base_a - 0.5 * sf)


def features(g: pd.DataFrame, rd: dict, goalies: dict | None = None) -> pd.DataFrame:
    """lx_h, lx_a (log xG-composed goals), lg_h, lg_a (log goals-model goals), hfa (1 unless neutral), schedule features. Starters from
    the games' goalie_h / goalie_a columns (else the team's usual starter); `goalies` {team: id} overrides."""
    rows = []
    gl = goalies or {}
    for r in g.itertuples(index=False):
        qh = gl.get(r.home) or (getattr(r, "goalie_h", None) if isinstance(getattr(r, "goalie_h", None), str) else None)
        qa = gl.get(r.away) or (getattr(r, "goalie_a", None) if isinstance(getattr(r, "goalie_a", None), str) else None)
        xh, xa = TS.expected_goals(rd, r.home, r.away, qh, qa)
        gh, ga = TS.goals_model(rd, r.home, r.away)
        rows.append((math.log(max(xh, 0.05)), math.log(max(xa, 0.05)), math.log(max(gh, 0.05)), math.log(max(ga, 0.05))))
    a = np.array(rows, float).reshape(-1, 4)
    F = pd.DataFrame({"lx_h": a[:, 0], "lx_a": a[:, 1], "lg_h": a[:, 2], "lg_a": a[:, 3]}, index=g.index)
    F["hfa"] = (~g["neutral"].astype(bool)).astype(float).to_numpy() if "neutral" in g else 1.0
    if "rest_h" in g:
        S = TS.schedule_features(g)
        for k in SCHED:
            F[k] = S[k].to_numpy()
    else:
        for k in SCHED:
            F[k] = 0.0
    return F


# ── walk-forward rows ────────────────────────────────────────────────────────

def walk_forward(seasons: list[int], games: pd.DataFrame | None = None, tg_of=None, prm_ts: dict | None = None,
                 refit_days: int = 7, first: int | None = None, progress: bool = False) -> pd.DataFrame:
    """
    One row per game of `seasons` (played or not) with features from ratings fitted only on games before the game's
    refit block (blocks of `refit_days` days; the preseason prior chained from `first`, default the season before
    the earliest), plus outcomes (reg_h, reg_a, ot, so, hs, as_) and closing-line fields. Bounded memory: one
    season's team-game table at a time.
    """
    tg_of = tg_of or D.team_games
    p = prm_ts or TS.params()
    seasons = sorted(int(s) for s in seasons)
    first = first if first is not None else D.prev_season(seasons[0])
    chain = []
    s = first
    while s <= seasons[-1]:
        chain.append(s)
        s = D.next_season(s)
    G = games if games is not None else D.games_frame(chain)
    if G.empty:
        return pd.DataFrame()
    G = D.add_context(G[G["season"].isin(chain)])
    out, last, book = [], None, {}
    for s in chain:
        tg = tg_of(s)
        gs = G[G["season"] == s]
        teams = sorted(set(gs["home"]) | set(gs["away"])) or None
        prior = TS.preseason_prior(last, s, p, book, teams)
        if s in seasons and not gs.empty:
            d0 = gs["date"].min()
            blk = ((gs["date"] - d0).dt.days // max(refit_days, 1)).to_numpy()
            for b in np.unique(blk):
                gb = gs[blk == b]
                thr = gb["date"].min()
                r = TS.fit(tg, s, thr, prior, p, teams=teams)
                rd = r.as_dict()
                rd["goalie_prior"] = prior["goalies"]
                F = features(gb, rd)
                F["n_rated"] = r.league.get("n_games", 0)
                F["net_h"] = [rd["teams"].get(t, {}).get("net", 0.0) for t in gb["home"]]
                F["net_a"] = [rd["teams"].get(t, {}).get("net", 0.0) for t in gb["away"]]
                F["xev_h"] = [rd["teams"].get(t, {}).get("ev_off", 0.0) - rd["teams"].get(t, {}).get("ev_def", 0.0) for t in gb["home"]]
                F["xev_a"] = [rd["teams"].get(t, {}).get("ev_off", 0.0) - rd["teams"].get(t, {}).get("ev_def", 0.0) for t in gb["away"]]
                out.append(pd.concat([gb.reset_index(drop=True), F.reset_index(drop=True)], axis=1))
        if not gs.empty or len(tg):
            end = TS.fit(tg, s, None, prior, p, teams=teams)
            TS.update_goalie_book(book, end)
            last = end
        if progress:
            logger.info("walk_forward %s: %d games", s, len(gs))
        del tg
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


# ── fitting ──────────────────────────────────────────────────────────────────

def _glm_poisson(X: np.ndarray, y: np.ndarray, lam: np.ndarray, iters: int = 40) -> np.ndarray:
    b = np.zeros(X.shape[1])
    b[0] = math.log(max(y.mean(), 1e-3))
    for _ in range(iters):
        eta = np.clip(X @ b, -5, 5)
        m = np.exp(eta)
        H = X.T @ (X * m[:, None]) + np.diag(lam)
        g = X.T @ (y - m) - lam * b
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-7:
            break
    return b


def _played_rows(rows: pd.DataFrame) -> pd.DataFrame:
    r = rows[rows["played"].astype(bool) & rows["reg_h"].notna() & rows["reg_a"].notna()]
    if "n_rated" in r:
        r = r[r["n_rated"] > 0]
    return r


def fit_means(rows: pd.DataFrame, p: dict | None = None, use_goals: bool = True) -> dict:
    """b0, b_xg, b_g, home, s from regulation goals of played walk-forward rows (Poisson GLM, small ridge on all but
    the intercept)."""
    p = dict(p or params())
    r = _played_rows(rows)
    if len(r) < 200:
        return p
    S = TS.schedule_features(r) if "rest_h" in r else pd.DataFrame({k: np.zeros(len(r)) for k in SCHED}, index=r.index)
    n = len(r)
    one = np.ones(2 * n)
    lx = np.concatenate([r["lx_h"].to_numpy(float), r["lx_a"].to_numpy(float)])
    lg = np.concatenate([r["lg_h"].to_numpy(float), r["lg_a"].to_numpy(float)])
    hm = np.concatenate([r["hfa"].to_numpy(float), np.zeros(n)])
    cols = [one, lx] + ([lg] if use_goals else []) + [hm]
    for k in SCHED:
        v = S[k].to_numpy(float)
        cols.append(np.concatenate([0.5 * v, -0.5 * v]))
    X = np.column_stack(cols)
    y = np.concatenate([r["reg_h"].to_numpy(float), r["reg_a"].to_numpy(float)])
    lam = np.full(X.shape[1], 2.0)
    lam[0] = 1e-6
    b = _glm_poisson(X, y, lam)
    i = 0
    p["b0"] = float(b[i]); i += 1
    p["b_xg"] = float(b[i]); i += 1
    if use_goals:
        p["b_g"] = float(b[i]); i += 1
    else:
        p["b_g"] = 0.0
    p["home"] = float(b[i]); i += 1
    p["s"] = {k: float(b[i + j]) for j, k in enumerate(SCHED)}
    return p


def _reg_loglik(r: pd.DataFrame, p: dict, mu_h, mu_a) -> float:
    R = regulation(mu_h, mu_a, p)
    h = np.minimum(r["reg_h"].to_numpy(int), NMAX)
    a = np.minimum(r["reg_a"].to_numpy(int), NMAX)
    return float(np.log(np.maximum(R[np.arange(len(h)), h, a], 1e-12)).sum())


def fit_shape(rows: pd.DataFrame, p: dict | None = None, max_games: int = 6000, seed: int = 0, rounds: int = 2) -> dict:
    """theta, tie_k, r_en, k_pull by coordinate-wise grid maximum likelihood of the regulation score; then b0 re-
    centred so the mean regulation total (with the late chain) matches the observed one."""
    p = dict(p or params())
    r = _played_rows(rows)
    if len(r) < 300:
        return p
    if len(r) > max_games:
        r = r.sample(max_games, random_state=seed)
    F = r
    grids = {"theta": [0.0, 0.04, 0.08, 0.12, 0.18, 0.25], "tie_k": [0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1],
             "r_en": [0.06, 0.09, 0.12, 0.17, 0.22, 0.28, 0.35], "k_pull": [1.5, 2.0, 2.5, 3.0, 3.5]}
    for _ in range(rounds):
        mu_h, mu_a = means(F, p)
        for k, grid in grids.items():
            best = None
            for v in grid:
                q = dict(p, **{k: v})
                ll = _reg_loglik(r, q, mu_h, mu_a)
                if best is None or ll > best[1]:
                    best = (v, ll)
            p[k] = best[0]
        # re-centre the level: observed regulation goals v the chain's expectation
        R = regulation(mu_h, mu_a, p)
        e = float(((R.sum(2) * _K).sum(1) + (R.sum(1) * _K).sum(1)).mean())
        o = float((r["reg_h"] + r["reg_a"]).mean())
        p["b0"] = float(p["b0"] + math.log(max(o, 1e-3) / max(e, 1e-3)))
    p["loglik_reg"] = _reg_loglik(r, p, *means(F, p)) / len(r)
    return p


def recenter(rows: pd.DataFrame, p: dict, max_games: int = 4000, seed: int = 0) -> dict:
    """b0 shifted so the mean regulation total under the full process (late chain included) matches the rows'."""
    p = dict(p)
    r = _played_rows(rows)
    if len(r) < 100:
        return p
    if len(r) > max_games:
        r = r.sample(max_games, random_state=seed)
    R = regulation(*means(r, p), p)
    e = float(((R.sum(2) * _K).sum(1) + (R.sum(1) * _K).sum(1)).mean())
    o = float((r["reg_h"] + r["reg_a"]).mean())
    p["b0"] = float(p["b0"] + math.log(max(o, 1e-3) / max(e, 1e-3)))
    return p


def fit_ot(rows: pd.DataFrame, p: dict | None = None) -> dict:
    """k_ot per era from the share of regular-season overtimes decided before a shootout; so_home from shootouts
    (shrunk to 0.5 with 300 pseudo-games)."""
    p = dict(p or params())
    r = _played_rows(rows)
    r = r[(r["gtype"] == "REG") & r["ot"].astype(bool)]
    if len(r) < 50:
        return p
    mu_h, mu_a = means(r, p)
    kk = dict(p["k_ot"]) if isinstance(p.get("k_ot"), dict) else {"3v3": 1.85, "4v4": 1.2}
    era = np.array([ot_era(s) for s in r["season"]])
    dec = ~r["so"].astype(bool).to_numpy()
    for e in ("3v3", "4v4"):
        m = era == e
        if m.sum() < 40:
            continue
        lam = (mu_h[m] + mu_a[m]) * 5.0 / 60.0
        target = dec[m].mean()
        lo, hi = 0.05, 8.0
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if (1 - np.exp(-mid * lam)).mean() < target:
                lo = mid
            else:
                hi = mid
        kk[e] = float(0.5 * (lo + hi))
    p["k_ot"] = kk
    so = r[r["so"].astype(bool)]
    if len(so):
        hw = float((so["hs"] > so["as_"]).sum())
        p["so_home"] = float((hw + 150.0) / (len(so) + 300.0))
    return p


def fit_from_rows(rows: pd.DataFrame, use_goals: bool = True) -> dict:
    p = fit_means(rows, params(), use_goals)
    p = fit_shape(rows, p)
    p = fit_ot(rows, p)
    r = _played_rows(rows)
    p["n"] = int(len(r))
    p["fitted"] = len(r) >= 300
    if len(r):
        p["seasons"] = [int(r["season"].min()), int(r["season"].max())]
    return p


def save_params(p: dict, committed: bool = False) -> None:
    obj = {"version": VERSION, "result": p}
    D.write_json(D.c_cache() / "game_params.json", obj)
    if committed:
        D.write_json(D.FITTED / "game_params.json", obj)
    set_params(None)


# ── prediction ───────────────────────────────────────────────────────────────

def predict_frame(g: pd.DataFrame, rd: dict, p: dict | None = None, goalies: dict | None = None) -> pd.DataFrame:
    """Model columns for a games frame (with add_context columns): mu_h, mu_a, p_home, p_reg_home, p_reg_away, p_ot,
    p_ot_home, p_so, pl_home (home -1.5), pl_away (away -1.5), exp_total, fair_total, p_over (at the game's
    total_line when it has one)."""
    p = p or params()
    if g.empty:
        return g.copy()
    F = features(g, rd, goalies)
    mu_h, mu_a = means(F, p)
    po = (g["gtype"].astype(str) == "PO").to_numpy() if "gtype" in g else False
    season = int(g["season"].iloc[0]) if "season" in g else None
    o = outcome_probs(mu_h, mu_a, p, po, season)
    out = g.copy()
    out["mu_h"], out["mu_a"] = mu_h, mu_a
    for k in ("p_home", "p_reg_home", "p_reg_away", "p_ot", "p_ot_home", "p_so", "pl_home", "pl_away", "exp_total"):
        out[k] = o[k]
    out["fair_total"] = fair_total(o["total_pmf"])
    if "total_line" in g:
        tl = g["total_line"].to_numpy(float)
        out["p_over"] = [float(total_over(o["total_pmf"][i], tl[i])) if np.isfinite(tl[i]) else np.nan for i in range(len(g))]
    out["_total_pmf"] = list(o["total_pmf"])
    return out


def predict(home: str, away: str, season: int, rd: dict, ctx: dict | None = None, p: dict | None = None) -> dict:
    """One game: ctx keys neutral, playoff, goalie_h, goalie_a, rest_h/rest_a, b2b_h/b2b_a, km_h/km_a, tz_h/tz_a,
    total_line, pl_home. Returns probabilities, means, the totals pmf and the 6x6 score matrix (final scores)."""
    c = {"neutral": False, "playoff": False, "goalie_h": None, "goalie_a": None, "rest_h": 1.0, "rest_a": 1.0,
         "b2b_h": 0.0, "b2b_a": 0.0, "km_h": 0.0, "km_a": 0.0, "tz_h": 0.0, "tz_a": 0.0}
    c.update(ctx or {})
    g = pd.DataFrame([{"home": home, "away": away, "season": int(season), "gtype": "PO" if c["playoff"] else "REG",
                       "neutral": bool(c["neutral"]), "goalie_h": c["goalie_h"], "goalie_a": c["goalie_a"],
                       **{k: float(c[k]) for k in ("rest_h", "rest_a", "b2b_h", "b2b_a", "km_h", "km_a", "tz_h", "tz_a")}}])
    pp = p or params()
    F = features(g, rd)
    mu_h, mu_a = means(F, pp)
    o = outcome_probs(mu_h, mu_a, pp, bool(c["playoff"]), int(season), full=True)
    R = o["reg"][0]
    fin = R.copy()
    di = np.einsum("ii->i", R).copy()
    np.fill_diagonal(fin, 0.0)
    h_ot = float(o["p_ot_home"][0] / max(o["p_ot"][0], 1e-12))
    for k in range(NMAX):
        fin[k + 1, k] += di[k] * h_ot
        fin[k, k + 1] += di[k] * (1 - h_ot)
    res = {k: float(v[0]) for k, v in o.items() if k not in ("total_pmf", "reg")}
    res.update({"mu_h": float(mu_h[0]), "mu_a": float(mu_a[0]), "total_pmf": [round(float(x), 6) for x in o["total_pmf"][0]],
                "fair_total": float(fair_total(o["total_pmf"])[0]),
                "score_matrix": [[round(float(fin[i, j]), 5) for j in range(7)] for i in range(7)]})
    if c.get("total_line") is not None:
        res["p_over"] = float(total_over(o["total_pmf"][0], float(c["total_line"])))
    return res


def simulate_scores(mu_h, mu_a, rng: np.random.Generator, p: dict | None = None, playoff=False, season: int | None = None,
                    steps: int = 6) -> dict:
    """Sampled games (vectorised over any array shape of means): regulation by the same process as the analytic
    distribution (late chain with `steps` sub-steps over the last three minutes), then OT / SO. Returns hs, as_
    (final, shootout winner +1), reg_h, reg_a, ot, so, home_win."""
    p = p or params()
    mu_h = np.asarray(mu_h, float)
    mu_a = np.asarray(mu_a, float)
    f = (60.0 - T_LATE) / 60.0
    l3 = np.clip(p["theta"], 0, 0.9) * np.minimum(mu_h, mu_a) * f
    w = rng.poisson(l3)
    h = rng.poisson(np.maximum(mu_h * f - l3, 0)) + w
    a = rng.poisson(np.maximum(mu_a * f - l3, 0)) + w
    dt = T_LATE / steps
    for k in range(steps):
        left = T_LATE - k * dt
        d = h - a
        pull_h = ((d == -1) & (left <= p["pull1"])) | ((d == -2) & (left <= p["pull2"]))
        pull_a = ((d == 1) & (left <= p["pull1"])) | ((d == 2) & (left <= p["pull2"]))
        tie = d == 0
        rh = np.where(tie, mu_h * p["tie_k"], mu_h) / 60.0
        ra = np.where(tie, mu_a * p["tie_k"], mu_a) / 60.0
        rh2 = np.where(pull_h, mu_h / 60.0 * p["k_pull"], np.where(pull_a, rh + p["r_en"], rh))
        ra2 = np.where(pull_a, mu_a / 60.0 * p["k_pull"], np.where(pull_h, ra + p["r_en"], ra))
        h = h + rng.poisson(rh2 * dt)
        a = a + rng.poisson(ra2 * dt)
    reg_h, reg_a = h.copy(), a.copy()
    tied = h == a
    po = np.broadcast_to(np.asarray(playoff, bool), h.shape)
    share = mu_h / np.maximum(mu_h + mu_a, 1e-9)
    k_ot = p["k_ot"][ot_era(season)] if isinstance(p.get("k_ot"), dict) else float(p["k_ot"])
    p_dec = np.where(po, 1.0, 1.0 - np.exp(-5.0 * k_ot * (mu_h + mu_a) / 60.0))
    u = rng.random(h.shape)
    dec = u < p_dec
    hw_ot = np.where(dec, rng.random(h.shape) < share, rng.random(h.shape) < p["so_home"])
    so = tied & ~dec
    h = h + (tied & hw_ot)
    a = a + (tied & ~hw_ot)
    return {"hs": h, "as_": a, "reg_h": reg_h, "reg_a": reg_a, "ot": tied, "so": so, "home_win": h > a}
