"""
Opponent-adjusted team ratings for FBS (and the FCS teams FBS teams play), walk-forward.

Three ridge models share one solver, each observation a team-game:
  points   pts(t v o)  = mu + h/2*home(t) - h/2*home(o) + off_t - def_o           (y = points, margin capped)
  EPA      epa(t v o)  = mu + ... + off_t - def_o                                    (y = offense EPA/play, weight = snaps/65)
  success  sr(t v o)   = same with success rate
`off` is scoring (EPA, success) above average, `def` is points (EPA, success) prevented, so a team's net
rating is off + def (points: the expected margin against an average FBS team on a neutral field).
Garbage time: points margins beyond `cap` count at 20% (the winner's score is pulled toward cap); EPA and success
use only snaps outside garbage time (ep.GARBAGE).

Priors (preseason): last season's final off/def regressed toward the mean of the team's NEW conference (from last
season's ratings of that conference's members): prior = conf_mean + rho * (last - conf_mean); teams without a
rating last season start at `new_mean`. Non-FBS teams: off_t = g_off + u_t with a shared FCS level g (weak prior
at last season's FCS level) and team deviations u_t shrunk hard (precision `lam_fcs`), so a once-a-year FCS
opponent is rated by its group level and little else.
Recency: observation weights 0.5 ** (age_days / half_life) relative to the rating day.

Walk-forward: for every game day D of a season the models are refitted on finished games with day < D (the
normal equations are accumulated once per season and reweighted; one 500-parameter solve per day), so a game's
pregame ratings never contain the game or anything after it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import data

VERSION = "cfb-ratings-4"


@dataclass
class Params:
    lam: float = 3.0            # prior precision in game-equivalents (points model, FBS teams)
    lam_fcs: float = 12.0       # FCS deviations
    rho: float = 0.6            # carry-over of last season's rating toward the conference mean
    half_life: float = 180.0    # days
    cap: float = 28.0           # margin cap (points model)
    new_mean: float = -8.0      # prior net rating for FBS teams without one last season
    hfa: float = 2.5            # prior mean of home-field advantage (points), estimated each fit
    sigma: float = 11.0         # score noise per team-game (points)
    lam_epa: float = 3.0        # prior precision, EPA/success models (game-equivalents at 65 snaps)
    rho_epa: float = 0.55
    w_prev2: float = 0.0        # weight of the season before last in the preseason prior (points model)
    lam_fconf: float = 2.0      # precision of the FCS conference levels (game-equivalents)
    rho_fcs: float = 0.7        # carry-over of an FCS team's deviation from its conference (per season since last seen)
    rho_fconf: float = 0.8      # carry-over of the FCS conference levels
    fcs_conf: bool = True       # FCS conference levels on (False = one shared FCS level, the earlier design)

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


DEFAULT = Params()


# ── solver ──────────────────────────────────────────────────────────────────

def _days(s: pd.Series) -> np.ndarray:
    return pd.to_datetime(s).map(lambda d: d.toordinal()).to_numpy(float)


class Model:
    """A ridge model on team-game observations with incremental normal equations.

    Parameters: [mu, hfa, g_off, g_def, off_0..off_{n-1}, def_0..def_{n-1}, coff_0..coff_{m-1}, cdef_0..cdef_{m-1}]:
    a non-FBS team's offence is g_off + coff[its FCS conference] + off_t (its own deviation), FBS teams' off_t alone.
    """

    def __init__(self, teams: list[str], fcs: np.ndarray, prior_off: np.ndarray, prior_def: np.ndarray,
                 prec_team: np.ndarray, mu0: float, hfa0: float, g0: tuple[float, float], prec_mu: float = 1e-4,
                 prec_hfa: float = 4.0, prec_g: float = 0.5, conf_idx: np.ndarray | None = None, confs: list[str] | None = None,
                 prior_coff: np.ndarray | None = None, prior_cdef: np.ndarray | None = None, prec_conf: float = 2.0):
        self.teams = list(teams)
        self.ix = {t: i for i, t in enumerate(self.teams)}
        n = len(self.teams)
        self.n = n
        self.fcs = np.asarray(fcs, bool)
        self.confs = list(confs or [])
        nc = len(self.confs)
        self.nc = nc
        self.ci = np.full(n, -1, int) if conf_idx is None else np.asarray(conf_idx, int)
        P = 4 + 2 * n + 2 * nc
        self.P = P
        self.cb = 4 + 2 * n
        self.m = np.zeros(P)
        self.lam = np.zeros(P)
        self.m[0], self.lam[0] = mu0, prec_mu
        self.m[1], self.lam[1] = hfa0, prec_hfa
        self.m[2], self.m[3] = g0
        self.lam[2] = self.lam[3] = prec_g
        self.m[4:4 + n] = prior_off
        self.m[4 + n:4 + 2 * n] = prior_def
        self.lam[4:4 + n] = prec_team
        self.lam[4 + n:4 + 2 * n] = prec_team
        if nc:
            self.m[self.cb:self.cb + nc] = np.zeros(nc) if prior_coff is None else prior_coff
            self.m[self.cb + nc:] = np.zeros(nc) if prior_cdef is None else prior_cdef
            self.lam[self.cb:] = prec_conf

    def rows(self, team: list[str], opp: list[str], home: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(index matrix k x 8, coef matrix k x 8) for y = mu + hfa*home + off_t - def_o (+ FCS and FCS-conference levels)."""
        n, nc = self.n, self.nc
        ti = np.array([self.ix[t] for t in team])
        oi = np.array([self.ix[o] for o in opp])
        k = len(ti)
        I = np.zeros((k, 8), int)
        C = np.zeros((k, 8))
        I[:, 0], C[:, 0] = 0, 1.0
        I[:, 1], C[:, 1] = 1, home
        I[:, 2], C[:, 2] = 2, self.fcs[ti].astype(float)
        I[:, 3], C[:, 3] = 3, -self.fcs[oi].astype(float)
        I[:, 4], C[:, 4] = 4 + ti, 1.0
        I[:, 5], C[:, 5] = 4 + n + oi, -1.0
        if nc:
            ct, co = self.ci[ti], self.ci[oi]
            I[:, 6], C[:, 6] = np.where(ct >= 0, self.cb + ct, 0), (ct >= 0).astype(float)
            I[:, 7], C[:, 7] = np.where(co >= 0, self.cb + nc + co, 0), -(co >= 0).astype(float)
        return I, C

    def solve(self, I, C, y, w, return_cov: bool = False):
        P = self.P
        A = np.zeros((P, P))
        b = np.zeros(P)
        if len(y):
            WC = C * w[:, None]
            np.add.at(A, (I[:, :, None], I[:, None, :]), WC[:, :, None] * C[:, None, :])
            np.add.at(b, I, WC * y[:, None])
        A[np.diag_indices(P)] += self.lam
        b += self.lam * self.m
        x = np.linalg.solve(A, b)
        if return_cov:
            return x, np.linalg.inv(A)
        return x

    def unpack(self, x: np.ndarray) -> dict:
        n, nc = self.n, self.nc
        coff = x[self.cb:self.cb + nc] if nc else np.zeros(0)
        cdef = x[self.cb + nc:] if nc else np.zeros(0)
        co = np.where(self.ci >= 0, coff[np.maximum(self.ci, 0)] if nc else 0.0, 0.0)
        cd = np.where(self.ci >= 0, cdef[np.maximum(self.ci, 0)] if nc else 0.0, 0.0)
        off = x[4:4 + n] + np.where(self.fcs, x[2] + co, 0.0)
        de = x[4 + n:4 + 2 * n] + np.where(self.fcs, x[3] + cd, 0.0)
        return {"mu": float(x[0]), "hfa": float(x[1]), "g_off": float(x[2]), "g_def": float(x[3]), "off": off, "def": de,
                "dev_off": x[4:4 + n], "dev_def": x[4 + n:4 + 2 * n],
                "c_off": dict(zip(self.confs, map(float, coff))), "c_def": dict(zip(self.confs, map(float, cdef)))}


# ── season inputs ───────────────────────────────────────────────────────────

def _capped(hs, as_, cap):
    m = hs - as_
    over = np.maximum(np.abs(m) - cap, 0.0) * 0.8
    h2 = np.where(m > 0, hs - over, hs)
    a2 = np.where(m < 0, as_ - over, as_)
    return h2, a2


def season_teams(gf: pd.DataFrame, st: dict) -> tuple[list[str], np.ndarray]:
    teams = sorted(set(gf["home"]) | set(gf["away"]))
    tm = st.get("teams") or {}
    fcs = np.array([not bool((tm.get(t) or {}).get("member")) for t in teams])
    return teams, fcs


def priors(season: int, teams: list[str], fcs: np.ndarray, st: dict, prev: dict | None, p: Params,
           kind: str = "pts", prev2: dict | None = None, mem: dict | None = None) -> dict:
    """Prior off/def per team, the FCS group level and the FCS conference levels from last season's final ratings
    (`prev`) and the memory of non-FBS teams (`mem` = {"dev": {team: (dev_off, dev_def, season)}, "conf": {cid:
    (c_off, c_def)}}; a non-FBS team often goes years between FBS opponents, so its last seen deviation is carried
    with rho_fcs per season since)."""
    n = len(teams)
    rho = p.rho if kind == "pts" else p.rho_epa
    po, pd_ = np.zeros(n), np.zeros(n)
    g0 = (0.0, 0.0)
    mu0 = 28.0 if kind == "pts" else (0.0 if kind == "epa" else 0.42)
    hfa0 = p.hfa if kind == "pts" else (0.03 if kind == "epa" else 0.01)
    new_mean = p.new_mean if kind == "pts" else 0.0
    if kind != "pts":
        new_mean = -0.06 if kind == "epa" else -0.02
    tm = st.get("teams") or {}
    mem = mem or {}
    dev_mem, conf_mem = mem.get("dev") or {}, mem.get("conf") or {}
    for i, t in enumerate(teams):
        if fcs[i] and t in dev_mem:
            do, dd, s0 = dev_mem[t]
            f = p.rho_fcs ** max(int(season) - int(s0), 1)
            po[i], pd_[i] = f * do, f * dd
    confs: list[str] = []
    cidx = np.full(n, -1, int)
    if p.fcs_conf:
        cof = [((tm.get(t) or {}).get("conference") if fcs[i] else None) for i, t in enumerate(teams)]
        confs = sorted({str(c) for c in cof if c})
        cpos = {c: j for j, c in enumerate(confs)}
        cidx = np.array([cpos.get(str(c), -1) if c else -1 for c in cof], int)
    pco = np.array([p.rho_fconf * (conf_mem.get(c) or (0.0, 0.0))[0] for c in confs])
    pcd = np.array([p.rho_fconf * (conf_mem.get(c) or (0.0, 0.0))[1] for c in confs])
    if prev:
        mu0 = prev.get("mu", mu0)
        hfa0 = 0.5 * hfa0 + 0.5 * prev.get("hfa", hfa0)
        po_prev, pd_prev = prev["off"], prev["def"]
        g0 = (prev.get("g_off", 0.0), prev.get("g_def", 0.0))
        conf = data.conf_of(st)
        by_conf: dict[str, list[str]] = {}
        for t in teams:
            if (tm.get(t) or {}).get("member") and conf.get(t) and conf.get(t) != data.INDEPENDENT:
                by_conf.setdefault(conf[t], []).append(t)
        cm_off = {c: np.mean([po_prev[t] for t in ts if t in po_prev] or [0.0]) for c, ts in by_conf.items()}
        cm_def = {c: np.mean([pd_prev[t] for t in ts if t in pd_prev] or [0.0]) for c, ts in by_conf.items()}
        allfbs_o = np.mean([po_prev[t] for t in teams if t in po_prev and (tm.get(t) or {}).get("member")] or [0.0])
        allfbs_d = np.mean([pd_prev[t] for t in teams if t in pd_prev and (tm.get(t) or {}).get("member")] or [0.0])
        for i, t in enumerate(teams):
            if fcs[i]:
                continue
            c = conf.get(t)
            co = cm_off.get(c, allfbs_o)
            cd = cm_def.get(c, allfbs_d)
            if t in po_prev:
                lo, ld = po_prev[t], pd_prev[t]
                if kind == "pts" and prev2 and p.w_prev2 and t in prev2["off"]:
                    lo = (1 - p.w_prev2) * lo + p.w_prev2 * prev2["off"][t]
                    ld = (1 - p.w_prev2) * ld + p.w_prev2 * prev2["def"][t]
                po[i] = co + rho * (lo - co)
                pd_[i] = cd + rho * (ld - cd)
            else:
                po[i] = new_mean / 2
                pd_[i] = new_mean / 2
    else:
        for i in range(n):
            if not fcs[i]:
                po[i] = pd_[i] = 0.0
        g0 = (-10.0, -10.0) if kind == "pts" else ((-0.15, -0.15) if kind == "epa" else (-0.05, -0.05))
    return {"off": po, "def": pd_, "g0": g0, "mu0": mu0, "hfa0": hfa0, "confs": confs, "cidx": cidx, "coff": pco, "cdef": pcd}


def _model(kind: str, teams, fcs, pri, p: Params) -> Model:
    kw = {"conf_idx": pri.get("cidx"), "confs": pri.get("confs"), "prior_coff": pri.get("coff"), "prior_cdef": pri.get("cdef")}
    if kind == "pts":
        prec = np.where(fcs, p.lam_fcs, p.lam)
        # observation weight 1 per team-game: prior precision in the same units
        return Model(teams, fcs, pri["off"], pri["def"], prec, pri["mu0"], pri["hfa0"], pri["g0"],
                     prec_hfa=40.0, prec_g=0.3, prec_conf=p.lam_fconf, **kw)
    prec = np.where(fcs, p.lam_epa * 4, p.lam_epa)
    return Model(teams, fcs, pri["off"], pri["def"], prec, pri["mu0"], pri["hfa0"], pri["g0"],
                 prec_hfa=400.0, prec_g=8.0, prec_conf=p.lam_fconf * 4, **kw)


# ── walk-forward over one season ────────────────────────────────────────────

@dataclass
class SeasonRun:
    season: int
    teams: list[str]
    fcs: np.ndarray
    pregame: pd.DataFrame                    # one row per game: pregame ratings of both teams
    snapshots: dict = field(default_factory=dict)   # day -> {"pts": unpack, "epa": ..., "sr": ...}
    final: dict = field(default_factory=dict)       # kind -> {"off": {t: v}, "def": {...}, "mu", "hfa", "g_off", "g_def", "se": {t: v}}


def _obs_points(fin: pd.DataFrame, cap: float):
    hs, as_ = _capped(fin["hs"].to_numpy(float), fin["as"].to_numpy(float), cap)
    home = np.where(fin["neutral"].to_numpy(bool), 0.0, 0.5)
    team = list(fin["home"]) + list(fin["away"])
    opp = list(fin["away"]) + list(fin["home"])
    y = np.concatenate([hs, as_])
    hh = np.concatenate([home, -home])
    d = np.concatenate([fin["dayn"].to_numpy(float)] * 2)
    return team, opp, hh, y, d


def _obs_eff(tgs: pd.DataFrame, fin: pd.DataFrame, col: str):
    if tgs is None or not len(tgs):
        return [], [], np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    g = tgs.merge(fin[["gid", "home", "neutral", "dayn"]], on="gid", how="inner")
    g = g[np.isfinite(g[col].to_numpy(float))]
    home = np.where(g["neutral"].to_numpy(bool), 0.0, np.where(g["team"].to_numpy() == g["home"].to_numpy(), 0.5, -0.5))
    return list(g["team"]), list(g["opp"]), home, g[col].to_numpy(float), g["dayn"].to_numpy(float), \
        (g["n"].to_numpy(float) / 65.0)


def run_season(season: int, gf: pd.DataFrame, st: dict, prev: dict | None, tgs: pd.DataFrame | None,
               p: Params = DEFAULT, kinds=("pts", "epa", "sr"), snapshots: bool = True, prev2: dict | None = None,
               mem: dict | None = None) -> SeasonRun:
    """Walk-forward ratings for one season. `prev` = last season's SeasonRun.final (or None)."""
    gf = gf.copy()
    gf["dayn"] = _days(gf["day"])
    teams, fcs = season_teams(gf, st)
    fin = gf[gf["final"]].reset_index(drop=True)
    has_eff = tgs is not None and len(tgs) > 0
    kinds = [k for k in kinds if k == "pts" or has_eff]
    models, obs = {}, {}
    for k in kinds:
        pri = priors(season, teams, fcs, st, (prev or {}).get(k), p, k, (prev2 or {}).get(k), (mem or {}).get(k))
        models[k] = _model(k, teams, fcs, pri, p)
        if k == "pts":
            t, o, h, y, d = _obs_points(fin, p.cap)
            w0 = np.ones(len(y))
        else:
            t, o, h, y, d, w0 = _obs_eff(tgs, fin, "epa" if k == "epa" else "sr")
        I, C = models[k].rows(t, o, h) if len(t) else (np.zeros((0, 8), int), np.zeros((0, 8)))
        if k == "pts":
            w0 = w0 / 1.0
        obs[k] = (I, C, y, d, w0)
    days = sorted(gf["day"].dropna().unique())
    out_rows = []
    snaps = {}
    ln2 = np.log(2.0) / max(p.half_life, 1.0)
    for day in days:
        D = date.fromisoformat(day).toordinal()
        cur = {}
        for k in kinds:
            I, C, y, d, w0 = obs[k]
            m = d < D
            w = w0[m] * np.exp(-ln2 * (D - d[m]))
            cur[k] = models[k].unpack(models[k].solve(I[m], C[m], y[m], w))
        if snapshots:
            snaps[day] = cur
        todays = gf[gf["day"] == day]
        for r in todays.itertuples(index=False):
            row = {"gid": r.gid}
            for k in kinds:
                u = cur[k]
                hi, ai = models[k].ix[r.home], models[k].ix[r.away]
                row[f"{k}_mu"] = u["mu"]
                row[f"{k}_hfa"] = u["hfa"]
                row[f"{k}_off_h"], row[f"{k}_def_h"] = u["off"][hi], u["def"][hi]
                row[f"{k}_off_a"], row[f"{k}_def_a"] = u["off"][ai], u["def"][ai]
            out_rows.append(row)
    pre = pd.DataFrame(out_rows)
    final = {}
    for k in kinds:
        I, C, y, d, w0 = obs[k]
        D = (max(d) + 1) if len(d) else 0
        w = w0 * np.exp(-ln2 * (D - d)) if len(d) else w0
        x, cov = models[k].solve(I, C, y, w, return_cov=True)
        u = models[k].unpack(x)
        n = models[k].n
        # se of the net rating off+def (x[4+i] + x[4+n+i]); residual scale from the fit
        res = (y - (C * x[I]).sum(axis=1)) if len(y) else np.zeros(0)
        s2 = float(np.average(res ** 2, weights=w)) if len(y) else (p.sigma ** 2)
        var = np.array([cov[4 + i, 4 + i] + cov[4 + n + i, 4 + n + i] + 2 * cov[4 + i, 4 + n + i] for i in range(n)])
        final[k] = {"mu": u["mu"], "hfa": u["hfa"], "g_off": u["g_off"], "g_def": u["g_def"],
                    "off": dict(zip(teams, map(float, u["off"]))), "def": dict(zip(teams, map(float, u["def"]))),
                    "dev_off": dict(zip(teams, map(float, u["dev_off"]))), "dev_def": dict(zip(teams, map(float, u["dev_def"]))),
                    "c_off": u["c_off"], "c_def": u["c_def"],
                    "se": dict(zip(teams, map(float, np.sqrt(np.maximum(var, 0) * s2)))), "resid_sd": float(np.sqrt(s2))}
    return SeasonRun(season, teams, fcs, pre, snaps, final)


def run_seasons(seasons: list[int], p: Params = DEFAULT, team_stats=None, snapshots: bool = False,
                kinds=("pts", "epa", "sr")) -> dict[int, SeasonRun]:
    """Chained walk-forward over consecutive seasons (priors from the previous season's final ratings).
    `team_stats`: {season: team_game_stats frame} (EPA/success models only where given)."""
    out: dict[int, SeasonRun] = {}
    prev = prev2 = None
    mem: dict[str, dict] = {}
    for s in sorted(seasons):
        st = data.load_store(s)
        gf = data.games_frame(s, st)
        if not len(gf):
            prev = prev2 = None
            continue
        tgs = (team_stats or {}).get(s)
        run = run_season(s, gf, st, prev, tgs, p, kinds=kinds, snapshots=snapshots, prev2=prev2, mem=mem)
        out[s] = run
        prev2, prev = prev, run.final
        for k, f in run.final.items():          # memory of non-FBS teams and FCS conference levels
            m = mem.setdefault(k, {"dev": {}, "conf": {}})
            for i, t in enumerate(run.teams):
                if run.fcs[i]:
                    m["dev"][t] = (f["dev_off"][t], f["dev_def"][t], s)
            for c in f.get("c_off") or {}:
                m["conf"][c] = (f["c_off"][c], f["c_def"][c])
    return out


def cache_key(seasons: list[int], p: Params, extra: str = "") -> str:
    ks = [data.results_key(s) for s in seasons]
    return hashlib.md5(f"{VERSION}|{seasons}|{ks}|{p.key()}|{extra}".encode()).hexdigest()[:16]
