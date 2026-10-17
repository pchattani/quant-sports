"""
Team strength: opponent-adjusted EPA per play and success rate by unit, with time decay, priors and a separate
quarterback component.

Units and models (one weighted ridge per unit and per target y in {EPA/play, success rate})
-----------------------------------------------------------------------------------------
    pass (dropbacks):  y_gtq = mu + hfa * h_g + PT_t + QB_q + PD_o + e      rows: game x offence t x passer q
    rush (designed):   y_gt  = mu + hfa * h_g + RO_t + RD_o + e             rows: game x offence t
    special teams:     s_gt  = ST_t - ST_o + e                              rows: game x team (net ST EPA, points)

h = +1/2 at home, -1/2 away, 0 at a neutral site. Offence terms are EPA/play gained above the league; defence terms
(PD, RD) are EPA/play *allowed* above the league (positive = worse defence). Rows are weighted by plays x 0.5^(age /
half-life), age in weeks before the fit date. The penalty pulls every team/QB term toward its prior:

    minimise  sum_i w_i (y_i - x_i b)^2 + sum_j lam_j (b_j - m_j)^2        (mu, hfa: lam = 1e-6, prior 0)

so lam_j is the prior's weight in plays. Defaults (half-life 30 weeks, the lam values, QB carry 0.95, new-QB prior -0.02)
were chosen by walk-forward game log-loss 2006-2025 over a grid (half-life 6-1000 weeks, lam x0.5-x2, QB lam x0.3-x3,
QB carry 0.7-1.0, new-QB prior -0.10-0); the unit carry-overs are fitted by `fit_carryover`. Posterior sd of b = s_play * sqrt(diag((X'WX + Lam)^-1)), s_play the
weighted residual sd per play.

Priors for season S (from the end-of-season fit of S-1, franchise-mapped across relocations)
    m_unit,t = c_unit * (1 + k_unit * (cont_t - mean cont)) * b_unit,t(S-1)
    m_QB,q   = c_qb * b_QB,q(last season seen, decayed c_qb per idle season); QBs never seen: QB_NEW (EPA/dropback)
cont_t is roster continuity (share of the previous season's offensive or defensive scrimmage snaps played by players
on the club's roster at the start of this season: snaps counted from the play-by-play participation, rosters from
nflverse's weekly rosters, seasons from 2017; otherwise 1 for every team, i.e. no effect; nflverse snap counts are
Pro Football Reference's and are not used). The committed k is 0 for every unit. The carry-over
coefficients c, k are fitted by `fit_carryover` (regression of end-of-season ratings on the previous season's), and
the QB book carries every QB's latest value so an injury replacement uses his own history.

Net rating (points per game against an average team on a neutral field)
    net_t = NP * (PT_t + QB_{starter(t)} - PD_t) + NR * (RO_t - RD_t) + ST_t
NP, NR = the league's mean dropbacks and designed runs per team-game in the fitted data. A starting-QB change
(injury report, depth chart, or the GAME record's listed starter) moves net_t through QB_q: `team_net(r, t, qb=...)`.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

logger = logging.getLogger(__name__)

VERSION = 1
UNITS = ("pass_team", "pass_def", "rush_off", "rush_def", "st")
DEFAULTS: dict[str, Any] = {
    "half_life_weeks": 30.0,
    "lam": {"pass_team": 500.0, "qb": 350.0, "pass_def": 450.0, "rush_off": 450.0, "rush_def": 550.0, "st": 6.0},
    "carry": {"pass_team": 0.575, "qb": 0.95, "pass_def": 0.50, "rush_off": 0.60, "rush_def": 0.505, "st": 0.45},
    "cont": {"pass_team": 0.0, "pass_def": 0.0, "rush_off": 0.0, "rush_def": 0.0, "st": 0.0},
    "qb_new": -0.02, "qb_min_db": 1.0,
    "np": 35.0, "nr": 26.0,
}


def params(over: dict | None = None) -> dict:
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    fit = D.read_json(D.c_cache() / "team_strength_params.json") or D.read_json(D.FITTED / "team_strength_params.json")
    for src in (fit or {}, over or {}):
        for k, v in (src.get("result", src) if src is fit else src).items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k].update(v)
            elif k in p:
                p[k] = v
    return p


# ── the ridge ────────────────────────────────────────────────────────────────

def spd_inv(A: np.ndarray) -> np.ndarray:
    """Inverse of a symmetric positive-definite matrix by Cholesky (scipy; numpy's inv is pathologically slow on some
    Windows BLAS builds), with a pseudo-inverse fallback."""
    import scipy.linalg as sl
    try:
        return sl.cho_solve(sl.cho_factor(A, check_finite=False), np.eye(len(A)), check_finite=False)
    except (np.linalg.LinAlgError, ValueError):
        return sl.pinvh(A)


def _ridge(cols: list[np.ndarray], vals: list[np.ndarray], y: np.ndarray, w: np.ndarray, n_par: int,
           lam: np.ndarray, prior: np.ndarray, dec: np.ndarray | None = None):
    """Sparse-ish weighted ridge toward `prior`. cols/vals: per design term, the column index and value of each row."""
    A = np.zeros((n_par, n_par))
    b = np.zeros(n_par)
    for ci, vi in zip(cols, vals):
        b += np.bincount(ci, weights=w * vi * y, minlength=n_par)
        for cj, vj in zip(cols, vals):
            np.add.at(A, (ci, cj), w * vi * vj)
    A[np.diag_indices(n_par)] += lam
    b += lam * prior
    inv = spd_inv(A)
    beta = inv @ b
    fit = np.zeros_like(y)
    for ci, vi in zip(cols, vals):
        fit += vi * beta[ci]
    res = y - fit
    # w = plays x decay, so E[w res^2] = decay x s_play^2: divide by the summed decay
    den = float((dec if dec is not None else w).sum())
    s2 = float((w * res ** 2).sum() / max(den, 1e-9)) if den > 0 else 1.0
    return beta, inv, s2


@dataclass
class Ratings:
    season: int
    through: Any
    teams: dict[str, dict] = field(default_factory=dict)
    qbs: dict[str, dict] = field(default_factory=dict)
    league: dict = field(default_factory=dict)
    starters: dict[str, str] = field(default_factory=dict)
    sr: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"season": self.season, "through": str(self.through) if self.through is not None else None,
                "teams": self.teams, "qbs": self.qbs, "league": self.league, "starters": self.starters, "sr": self.sr}


def _decay(dates: pd.Series, through: pd.Timestamp | None, hl_weeks: float) -> np.ndarray:
    if through is None or dates.isna().all():
        return np.ones(len(dates))
    age = (through - dates).dt.days.to_numpy(dtype=float) / 7.0
    age = np.where(np.isfinite(age), np.maximum(age, 0.0), 0.0)
    return 0.5 ** (age / max(hl_weeks, 1e-6))


def fit(units: pd.DataFrame, season: int, through: Any = None, prior: dict | None = None, prm: dict | None = None,
        teams: list[str] | None = None) -> Ratings:
    """
    Ratings from the unit rows of `season` dated strictly before `through` (all rows when None), pulled toward `prior`
    ({"teams": {t: {unit: value}}, "qbs": {q: value}} from `preseason_prior`; zeros when None).
    """
    p = prm or params()
    hl = float(p["half_life_weeks"])
    u = units
    if u is not None and len(u):
        u = u[u["season"] == season]
        if through is not None:
            u = u[u["date"] < pd.Timestamp(through)]
    else:
        u = pd.DataFrame(columns=["game_id", "off", "def", "qb", "pass_n", "pass_epa", "pass_sr", "rush_n", "rush_epa",
                                  "rush_sr", "st_epa", "home", "date", "week"])
    pr_t = (prior or {}).get("teams") or {}
    pr_q = (prior or {}).get("qbs") or {}
    tl = sorted(set(teams or []) | set(u["off"].astype(str)) | set(u["def"].astype(str)) | set(pr_t))
    if not tl:
        tl = sorted(D.teams_for(season))
    ti = {t: i for i, t in enumerate(tl)}
    T = len(tl)
    thr = pd.Timestamp(through) if through is not None else (u["date"].max() + pd.Timedelta(days=1) if len(u) else None)
    out = Ratings(season=season, through=through)
    lg: dict[str, Any] = {"n_games": int(u["game_id"].nunique()) if len(u) else 0}

    # ---- pass: mu, hfa, PT (T), PD (T), QB (Q)
    pu = u[u["pass_n"] > 0]
    qbl = sorted(set(pu["qb"].astype(str)) | {q for q in pr_q if q in set(pu["qb"].astype(str))})
    qi = {q: i for i, q in enumerate(qbl)}
    Q = len(qbl)
    wdec = _decay(pu["date"], thr, hl) if len(pu) else np.zeros(0)
    n = pu["pass_n"].to_numpy(float)
    w = n * wdec
    h = (pu["home"].to_numpy(float) - 0.5)
    off = pu["off"].map(ti).to_numpy(int)
    de = pu["def"].map(ti).to_numpy(int)
    qq = pu["qb"].astype(str).map(qi).to_numpy(int) if Q else np.zeros(len(pu), int)
    one = np.ones(len(pu))
    npar = 2 + 2 * T + Q
    lam = np.concatenate([[1e-6, 1e-6], np.full(T, p["lam"]["pass_team"]), np.full(T, p["lam"]["pass_def"]),
                          np.full(Q, p["lam"]["qb"])])
    prior = np.concatenate([[0.0, 0.0], [float((pr_t.get(t) or {}).get("pass_team", 0.0)) for t in tl],
                            [float((pr_t.get(t) or {}).get("pass_def", 0.0)) for t in tl],
                            [float(pr_q.get(q, p["qb_new"])) for q in qbl]])
    cols = [np.zeros(len(pu), int), np.ones(len(pu), int), 2 + off, 2 + T + de, 2 + 2 * T + qq]
    vals = [one, h, one, one, one]
    if not Q:
        cols, vals = cols[:4], vals[:4]
    res_pass = {}
    for target in ("epa", "sr"):
        if len(pu):
            y = (pu["pass_epa"] if target == "epa" else pu["pass_sr"]).to_numpy(float) / np.maximum(n, 1)
            pri = prior if target == "epa" else np.concatenate([[float(np.average(y, weights=np.maximum(w, 1e-9)))], np.zeros(npar - 1)])
            beta, inv, s2 = _ridge(cols, vals, y, w, npar, lam, pri, wdec)
            if target == "epa":
                # the intercept is free: keep the league level out of the team terms
                pass
            res_pass[target] = (beta, inv, s2)
        else:
            res_pass[target] = (prior.copy() if target == "epa" else np.zeros(npar), np.diag(1.0 / lam), 2.4)
    # ---- rush: mu, hfa, RO, RD
    ru = u.groupby(["game_id", "off", "def"], sort=False).agg(
        rush_n=("rush_n", "sum"), rush_epa=("rush_epa", "sum"), rush_sr=("rush_sr", "sum"), st_epa=("st_epa", "sum"),
        home=("home", "first"), date=("date", "first")).reset_index() if len(u) else u
    rr = ru[ru["rush_n"] > 0] if len(ru) else ru
    nr = rr["rush_n"].to_numpy(float) if len(rr) else np.zeros(0)
    wr = nr * (_decay(rr["date"], thr, hl) if len(rr) else np.zeros(0))
    off_r = rr["off"].map(ti).to_numpy(int) if len(rr) else np.zeros(0, int)
    de_r = rr["def"].map(ti).to_numpy(int) if len(rr) else np.zeros(0, int)
    one_r = np.ones(len(rr))
    nrpar = 2 + 2 * T
    lam_r = np.concatenate([[1e-6, 1e-6], np.full(T, p["lam"]["rush_off"]), np.full(T, p["lam"]["rush_def"])])
    prior_r = np.concatenate([[0.0, 0.0], [float((pr_t.get(t) or {}).get("rush_off", 0.0)) for t in tl],
                              [float((pr_t.get(t) or {}).get("rush_def", 0.0)) for t in tl]])
    cols_r = [np.zeros(len(rr), int), np.ones(len(rr), int), 2 + off_r, 2 + T + de_r]
    vals_r = [one_r, (rr["home"].to_numpy(float) - 0.5) if len(rr) else one_r, one_r, one_r]
    res_rush = {}
    for target in ("epa", "sr"):
        if len(rr):
            y = (rr["rush_epa"] if target == "epa" else rr["rush_sr"]).to_numpy(float) / np.maximum(nr, 1)
            pri = prior_r if target == "epa" else np.concatenate([[float(np.average(y, weights=np.maximum(wr, 1e-9)))], np.zeros(nrpar - 1)])
            res_rush[target] = _ridge(cols_r, vals_r, y, wr, nrpar, lam_r, pri, wr / np.maximum(nr, 1))
        else:
            res_rush[target] = (prior_r.copy() if target == "epa" else np.zeros(nrpar), np.diag(1.0 / lam_r), 1.4)
    # ---- special teams: ST_t - ST_o, one row per team-game at weight 1/2
    if len(ru):
        ws = 0.5 * _decay(ru["date"], thr, hl)
        cols_s = [ru["off"].map(ti).to_numpy(int), ru["def"].map(ti).to_numpy(int)]
        vals_s = [np.ones(len(ru)), -np.ones(len(ru))]
        prior_s = np.array([float((pr_t.get(t) or {}).get("st", 0.0)) for t in tl])
        beta_s, inv_s, s2_s = _ridge(cols_s, vals_s, ru["st_epa"].to_numpy(float), ws, T, np.full(T, p["lam"]["st"]), prior_s)
    else:
        beta_s = np.array([float((pr_t.get(t) or {}).get("st", 0.0)) for t in tl])
        inv_s, s2_s = np.diag(np.full(T, 1.0 / p["lam"]["st"])), 16.0
    # ---- league constants
    NPg = float(pu["pass_n"].sum() / max(ru["game_id"].nunique() * 2, 1)) if len(pu) else p["np"]
    NRg = float(rr["rush_n"].sum() / max(ru["game_id"].nunique() * 2, 1)) if len(rr) else p["nr"]
    if not (20 <= NPg <= 50):
        NPg = p["np"]
    if not (15 <= NRg <= 40):
        NRg = p["nr"]
    bp, ip, s2p = res_pass["epa"]
    br, ir, s2r = res_rush["epa"]
    lg.update({"np": NPg, "nr": NRg, "pass_epa": float(bp[0]), "rush_epa": float(br[0]), "hfa_pass": float(bp[1]),
               "hfa_rush": float(br[1]), "s_pass": math.sqrt(s2p), "s_rush": math.sqrt(s2r), "s_st": math.sqrt(s2_s),
               "pass_sr": float(res_pass["sr"][0][0]), "rush_sr": float(res_rush["sr"][0][0])})
    out.league = lg
    # ---- QBs: value, sd, dropbacks
    qn = pu.groupby(pu["qb"].astype(str))["pass_n"].sum().to_dict() if len(pu) else {}
    for q, k in qi.items():
        out.qbs[q] = {"val": float(bp[2 + 2 * T + k]), "se": float(math.sqrt(max(ip[2 + 2 * T + k, 2 + 2 * T + k] * s2p, 0))),
                      "n": float(qn.get(q, 0.0)), "sr": float(res_pass["sr"][0][2 + 2 * T + k])}
    # ---- starters: the last game's main passer per team
    starters = {}
    if len(pu):
        last = pu.sort_values(["date", "pass_n"]).groupby("off").tail(1)
        # the main passer of the team's latest game
        lg_games = pu.loc[pu.groupby(["game_id", "off"])["pass_n"].idxmax()].sort_values("date")
        for r in lg_games.itertuples(index=False):
            starters[str(r.off)] = str(r.qb)
        del last
    out.starters = starters
    for t, i in ti.items():
        q = starters.get(t)
        qv = out.qbs.get(q, {}).get("val") if q else None
        if qv is None:
            qv = float(pr_q.get(q, p["qb_new"])) if q else float((pr_t.get(t) or {}).get("qb_val", 0.0))
        pt = float(bp[2 + i])
        pd_ = float(bp[2 + T + i])
        ro = float(br[2 + i])
        rd = float(br[2 + T + i])
        st = float(beta_s[i])
        var_pass = (ip[2 + i, 2 + i] + ip[2 + T + i, 2 + T + i]) * s2p
        var_rush = (ir[2 + i, 2 + i] + ir[2 + T + i, 2 + T + i]) * s2r
        qse = out.qbs.get(q, {}).get("se", 0.06) if q else 0.06
        se = math.sqrt(NPg ** 2 * (var_pass + qse ** 2) + NRg ** 2 * var_rush + inv_s[i, i] * s2_s)
        rec = {"pass_team": pt, "qb": q, "qb_val": float(qv), "pass_off": pt + float(qv), "pass_def": pd_,
               "rush_off": ro, "rush_def": rd, "st": st,
               "net": NPg * (pt + qv - pd_) + NRg * (ro - rd) + st,
               "off": NPg * (pt + qv) + NRg * ro, "def": -(NPg * pd_ + NRg * rd), "se_net": se,
               "games": int(((u["off"] == t)).groupby(u["game_id"]).any().sum()) if len(u) else 0}
        out.teams[t] = rec
        bs, bsr = res_pass["sr"][0], res_rush["sr"][0]
        q_sr = out.qbs.get(q, {}).get("sr", 0.0) if q else 0.0
        out.sr[t] = {"pass_off": float(bs[2 + i] + q_sr), "pass_def": float(bs[2 + T + i]), "rush_off": float(bsr[2 + i]),
                     "rush_def": float(bsr[2 + T + i])}
    return out


def team_net(r: Ratings | dict, team: str, qb: str | None = None, prm: dict | None = None) -> float:
    """Net points per game of `team`, with `qb` (gsis id) at quarterback when given (else the current starter)."""
    rd = r.as_dict() if isinstance(r, Ratings) else r
    t = (rd.get("teams") or {}).get(team)
    if not t:
        return 0.0
    if not qb or qb == t.get("qb"):
        return float(t["net"])
    lg = rd.get("league") or {}
    NPg = float(lg.get("np", DEFAULTS["np"]))
    return float(t["net"]) + NPg * (qb_value(rd, qb, prm) - float(t["qb_val"]))


def team_units(r: Ratings | dict, team: str, qb: str | None = None, prm: dict | None = None) -> dict:
    """Unit values with the given QB substituted (pass_off = pass_team + QB)."""
    rd = r.as_dict() if isinstance(r, Ratings) else r
    t = dict((rd.get("teams") or {}).get(team) or {})
    if not t:
        return {"pass_off": 0.0, "pass_def": 0.0, "rush_off": 0.0, "rush_def": 0.0, "st": 0.0, "net": 0.0}
    if qb and qb != t.get("qb"):
        qv = qb_value(rd, qb, prm)
        t["pass_off"] = t["pass_team"] + qv
        t["qb"], t["qb_val"] = qb, qv
        t["net"] = team_net(rd, team, qb, prm)
    return t


def qb_value(rd: dict, qb: str, prm: dict | None = None) -> float:
    q = (rd.get("qbs") or {}).get(qb)
    if q is not None:
        return float(q["val"])
    book = rd.get("qb_prior") or {}
    if qb in book:
        return float(book[qb])
    return float((prm or params())["qb_new"])


# ── priors and carry-over ────────────────────────────────────────────────────

def preseason_prior(last: Ratings | dict | None, season: int, prm: dict | None = None, qb_book: dict | None = None,
                    continuity: dict | None = None) -> dict:
    """{"teams": {t: {unit: prior}}, "qbs": {q: prior}} for `season` from the previous season's end-of-season fit."""
    p = prm or params()
    c, k = p["carry"], p["cont"]
    out = {"teams": {}, "qbs": {}}
    cur = D.teams_for(season)
    if last is not None:
        ld = last.as_dict() if isinstance(last, Ratings) else last
        by_fr = {D.franchise(t): v for t, v in (ld.get("teams") or {}).items()}
        cont = continuity or {}
        mean_c = {u: float(np.mean([v.get(u, 1.0) for v in cont.values()])) if cont else 1.0 for u in ("off", "def")}
        for t in cur:
            v = by_fr.get(D.franchise(t))
            if not v:
                continue
            rec = {}
            for unit in UNITS:
                side = "def" if unit in ("pass_def", "rush_def") else "off"
                ct = (cont.get(t) or {}).get(side, mean_c[side])
                rec[unit] = float(c[unit]) * (1.0 + float(k.get(unit, 0.0)) * (ct - mean_c[side])) * float(v.get(unit, 0.0))
            out["teams"][t] = rec
    for q, v in (qb_book or {}).items():
        out["qbs"][q] = float(c["qb"]) ** max(1, season - int(v["season"])) * float(v["val"]) + \
            (1 - float(c["qb"]) ** max(1, season - int(v["season"]))) * float(p["qb_new"]) * 0.0
    return out


def update_qb_book(book: dict, r: Ratings, min_db: float = 50.0) -> dict:
    """Carry each QB's latest season value (QBs with at least `min_db` dropbacks)."""
    for q, v in r.qbs.items():
        if q and v.get("n", 0) >= min_db:
            book[q] = {"val": v["val"], "season": r.season, "n": v["n"]}
    return book


def fit_carryover(ends: dict[int, Ratings], books: dict[int, dict] | None = None) -> dict:
    """carry[unit] = OLS slope (no intercept) of a franchise's end-of-season unit value on the previous season's."""
    xs: dict[str, list] = {u: [] for u in UNITS}
    ys: dict[str, list] = {u: [] for u in UNITS}
    qx, qy = [], []
    seasons = sorted(ends)
    for s in seasons:
        a, b = ends.get(s - 1), ends.get(s)
        if not a or not b:
            continue
        af = {D.franchise(t): v for t, v in a.teams.items()}
        for t, v in b.teams.items():
            w = af.get(D.franchise(t))
            if not w or v.get("games", 0) < 8 or w.get("games", 0) < 8:
                continue
            for u in UNITS:
                xs[u].append(w[u])
                ys[u].append(v[u])
        for q, v in b.qbs.items():
            if q in a.qbs and v["n"] >= 200 and a.qbs[q]["n"] >= 200:
                qx.append(a.qbs[q]["val"])
                qy.append(v["val"])
    out = {}
    for u in UNITS:
        x, y = np.array(xs[u]), np.array(ys[u])
        if len(x) >= 40 and float(x @ x) > 0:
            out[u] = float(np.clip(x @ y / (x @ x), 0.0, 1.2))
    if len(qx) >= 30:
        x, y = np.array(qx), np.array(qy)
        out["qb"] = float(np.clip(x @ y / (x @ x), 0.0, 1.2))
    return out


def continuity(season: int) -> dict[str, dict]:
    """{team: {"off": share, "def": share}} of last season's offensive / defensive scrimmage snaps played by players
    on the club's roster at the start of this season. Snaps from the play-by-play participation (`_cdata.onfield`,
    2016 onward, so seasons from 2017), rosters from nflverse's weekly rosters (`_cdata.roster_at_start`); {} when
    either is not on disk."""
    prev = D.onfield(season - 1)
    now = D.roster_at_start(season)
    if prev is None or not len(prev) or not now:
        return {}
    a = prev.groupby(["team", "player", "side"], as_index=False)["snaps"].sum()
    a["fr"] = a["team"].map(D.franchise)
    a["stay"] = a["player"].map(now) == a["fr"]
    out = {}
    for t, g in a.groupby("fr"):
        sh = {}
        for side in ("off", "def"):
            s = g[g["side"] == side]
            tot = float(s["snaps"].sum())
            sh[side] = float(s.loc[s["stay"], "snaps"].sum() / tot) if tot else 1.0
        out[t] = sh
    cur_teams = D.teams_for(season)
    return {t: out.get(D.franchise(t), {"off": 1.0, "def": 1.0}) for t in cur_teams}


# ── season chain ─────────────────────────────────────────────────────────────

def season_chain(seasons: list[int], units_of=None, prm: dict | None = None) -> dict:
    """End-of-season fits for consecutive seasons with priors chained: {"ends": {S: Ratings}, "priors": {S: prior},
    "books": {S: qb book before S}}. units_of(season) -> unit DataFrame (default `_cdata.unit_rows`)."""
    units_of = units_of or D.unit_rows
    p = prm or params()
    ends, priors, books = {}, {}, {}
    book: dict = {}
    last = None
    for s in sorted(seasons):
        u = units_of(s)
        books[s] = dict(book)
        pr = preseason_prior(last, s, p, book, continuity(s))
        priors[s] = pr
        r = fit(u, s, None, pr, p)
        ends[s] = r
        update_qb_book(book, r)
        last = r
    return {"ends": ends, "priors": priors, "books": books}


def for_season(season: int, through: Any = None, prm: dict | None = None, first: int | None = None) -> dict:
    """Current ratings for `season` through a date (cached chain of earlier seasons); a plain dict (Ratings.as_dict)
    with "qb_prior" (the QB book) and "prior" (the preseason prior) attached."""
    p = prm or params()
    seasons = [s for s in D.pbp_seasons() if s < season]
    if first is not None:
        seasons = [s for s in seasons if s >= first]
    seasons = seasons[-6:]                                    # priors decay fast: six seasons of chain is plenty
    ch = season_chain(seasons, prm=p) if seasons else {"ends": {}, "books": {}}
    last = ch["ends"].get(season - 1)
    book = {}
    for s in sorted(ch["ends"]):
        update_qb_book(book, ch["ends"][s])
    pr = preseason_prior(last, season, p, book, continuity(season))
    u = D.unit_rows(season) if season in D.pbp_seasons() else pd.DataFrame()
    r = fit(u, season, through, pr, p, teams=sorted(D.teams_for(season)))
    out = r.as_dict()
    out["qb_prior"] = {q: v for q, v in pr["qbs"].items()}
    out["prior"] = pr
    return out


def table(rd: dict) -> list[dict]:
    """Rows sorted by net rating, for printing and payloads."""
    rows = []
    for t, v in (rd.get("teams") or {}).items():
        rows.append({"team": t, "net": round(v["net"], 2), "se": round(v["se_net"], 2), "off": round(v["off"], 2),
                     "def": round(v["def"], 2), "pass_off": round(v["pass_off"], 3), "rush_off": round(v["rush_off"], 3),
                     "pass_def": round(v["pass_def"], 3), "rush_def": round(v["rush_def"], 3), "st": round(v["st"], 2),
                     "qb": v.get("qb"), "qb_val": round(v.get("qb_val", 0.0), 3), "games": v.get("games")})
    rows.sort(key=lambda r: -r["net"])
    return rows
