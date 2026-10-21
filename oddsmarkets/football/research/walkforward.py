"""
Walk-forward football match model on football-data.co.uk history.

Decision times (explicit, UTC)
    football-data's "pre-closing" prices (PSH.., MaxH.., P>2.5, PAHH ..) are collected on
    Friday afternoon for Friday-Monday games and on Tuesday for Tuesday-Thursday games.
    The decision for a match is therefore taken at 12:00 UTC on that Friday (or Tuesday);
    `snapshot_time`. Every model refit for a decision uses only matches that kicked off
    at least 2.5 h before it. Closing prices are used only to judge.

Models
    A spec (`Spec`) selects the training rows and their weights:
        goals rows       (production: Dixon-Coles on goals)
        shots rows       a per-side expected-goals proxy from shots and shots on target
        market rows      the goal rates implied by each past match's *closing* prices
    plus the time decay, ridge, training window, a prior for teams new to the league
    (promoted), and the production Elo blend where a league's dc_weight < 1.

All fits are per league, refitted at every decision time (about twice a week), with a
warm start from the previous fit.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, asdict
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from oddsmarkets.football.research import fastdc
from oddsmarkets.common.edge import devig as _dv

TUNE_LAST_SEASON = 2018     # seasons starting <= 2018 are for tuning; >= 2019 are the test
SETTLE_H = 2.5              # a match counts as finished this long after kickoff


# ── data preparation ─────────────────────────────────────────────────────────

def season_year(s: str) -> int:
    return int(str(s)[:4])


def snapshot_time(kick: pd.Series) -> pd.Series:
    """12:00 UTC on the Friday (Fri-Mon games) or Tuesday (Tue-Thu games) before kickoff."""
    k = kick.dt.tz_convert("UTC")
    wd = k.dt.weekday  # Mon 0 .. Sun 6
    back = np.select([wd == 4, wd == 5, wd == 6, wd == 0, wd == 1, wd == 2, wd == 3], [0, 1, 2, 3, 0, 1, 2])
    day = k.dt.normalize() - pd.to_timedelta(back, unit="D")
    t = day + pd.Timedelta(hours=12)
    late = t > k - pd.Timedelta(hours=1)
    return t.where(~late, k - pd.Timedelta(hours=3))


def devig(odds: np.ndarray) -> np.ndarray:
    """Proportional de-vig along the last axis; NaN where any price is missing or <= 1."""
    return _dv.multiplicative_rows(odds, strict=True)          # common/edge/devig.py


# Market-implied goal rates of a match from its closing 1X2 (and O/U 2.5 when present).
_GRID = None


def _grid():
    global _GRID
    if _GRID is None:
        lh, la = np.meshgrid(np.arange(0.15, 4.5, 0.02), np.arange(0.1, 4.0, 0.02), indexing="ij")
        lh, la = lh.ravel(), la.ravel()
        M = fastdc.score_matrix(lh, la, -0.05, max_goals=12)
        p = fastdc.outcome_probs(M)
        po = fastdc.over_prob(M)
        _GRID = (lh, la, p, po)
    return _GRID


def implied_rates(p1x2: np.ndarray, pover: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lh, la, p, po = _grid()
    out_h = np.full(len(p1x2), np.nan)
    out_a = np.full(len(p1x2), np.nan)
    ok = np.isfinite(p1x2).all(axis=1)
    has_o = ok & np.isfinite(pover)
    # With the total: match home, away and over. Without: home and away only, using the
    # draw to pin the total (weaker).
    t3 = cKDTree(np.column_stack([p[:, 0], p[:, 2], po]))
    t2 = cKDTree(np.column_stack([p[:, 0], p[:, 2], p[:, 1] * 2]))
    if has_o.any():
        _, idx = t3.query(np.column_stack([p1x2[has_o, 0], p1x2[has_o, 2], pover[has_o]]))
        out_h[has_o], out_a[has_o] = lh[idx], la[idx]
    only = ok & ~has_o
    if only.any():
        _, idx = t2.query(np.column_stack([p1x2[only, 0], p1x2[only, 2], p1x2[only, 1] * 2]))
        out_h[only], out_a[only] = lh[idx], la[idx]
    return out_h, out_a


def prepare(df: pd.DataFrame, shots_coef: tuple[float, float] | None = None, mkt_source: str = "pinnacle") -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(subset=["hg", "ag"]).reset_index(drop=True)
    df["sy"] = df["season"].map(season_year)
    df["snap"] = snapshot_time(df["start_time"])
    fo = devig(df[["ps_h", "ps_d", "ps_a"]].to_numpy())
    fc = devig(df[["psc_h", "psc_d", "psc_a"]].to_numpy())
    for k, c in enumerate("hda"):
        df[f"fo_{c}"], df[f"fc_{c}"] = fo[:, k], fc[:, k]
    po = devig(df[["pin_o25", "pin_u25"]].to_numpy())[:, 0]
    pc = devig(df[["pc_o25", "pc_u25"]].to_numpy())[:, 0]
    df["fair_open_o25"], df["fair_close_o25"] = po, pc
    # Closing O/U where present, else the max-price O/U de-vigged (a rougher total).
    pmaxc = devig(df[["maxc_o25", "maxc_u25"]].to_numpy())[:, 0]
    pmax = devig(df[["max_o25", "max_u25"]].to_numpy())[:, 0]
    pover = np.where(np.isfinite(pc), pc, np.where(np.isfinite(pmaxc), pmaxc, pmax))
    if mkt_source == "production":
        # what the build uses: Pinnacle close, else Betfair exchange close, else market average
        from oddsmarkets.football.sources.market_rates import closing_probs
        fc, pover = closing_probs(df)
    elif mkt_source == "avg":
        fc = devig(df[["avgc_h", "avgc_d", "avgc_a"]].to_numpy())
        pover = devig(df[["avgc_o25", "avgc_u25"]].to_numpy())[:, 0]
    df["mkt_h"], df["mkt_a"] = implied_rates(fc, pover)
    if shots_coef is not None:
        a, b = shots_coef
        df["sx_h"] = a * df["hst"] + b * (df["hs"] - df["hst"])
        df["sx_a"] = a * df["ast"] + b * (df["as_"] - df["ast"])
    else:
        df["sx_h"] = np.nan
        df["sx_a"] = np.nan
    df["result"] = np.select([df.hg > df.ag, df.hg == df.ag], [0, 1], 2)
    return df


def fit_shots_coef(df: pd.DataFrame) -> tuple[float, float]:
    """Goals ~ Poisson(a*SOT + b*off-target shots), fitted on tuning seasons only."""
    d = df[(df["sy"] <= TUNE_LAST_SEASON)].dropna(subset=["hs", "hst", "as_", "ast"])
    g = np.concatenate([d.hg, d.ag])
    sot = np.concatenate([d.hst, d.ast])
    off = np.concatenate([d.hs - d.hst, d.as_ - d.ast])
    ok = (sot >= 0) & (off >= 0)
    g, sot, off = g[ok], sot[ok], off[ok]
    a, b = 0.3, 0.03
    for _ in range(50):  # IRLS for an identity-link Poisson without intercept
        mu = np.maximum(a * sot + b * off, 1e-3)
        X = np.column_stack([sot, off])
        W = 1 / mu
        beta = np.linalg.solve(X.T @ (X * W[:, None]), X.T @ (W * g))
        a, b = float(max(beta[0], 1e-3)), float(max(beta[1], 0.0))
    return a, b


# ── model spec and the per-league walk-forward ───────────────────────────────

@dataclass
class Spec:
    name: str = "production"
    xi: float = 0.0035
    ridge: float = 1.0
    window_days: int = 730
    w_goals: float = 1.0
    w_shots: float = 0.0
    w_mkt: float = 0.0
    promo_att: float = 0.0       # ridge prior mean for teams with no league match in the window
    promo_def: float = 0.0
    dc_weight: float = 1.0
    elo_ha: float = 50.0
    elo_k: float = 30.0
    fit_rho: bool = True
    max_goals: int = 10
    # Oct 2026 additions (defaults keep the 2 Oct behaviour):
    xi_mkt: float | None = None  # own daily decay for the market rows (None: xi)
    xi_shots: float | None = None  # own daily decay for the shots rows (None: xi)
    ah: bool = True              # compute the Asian-handicap columns (off for fast tuning runs)
    elo_out: bool = False        # also return the production Elo's H/D/A (p_elo_*) for stacking


class Elo:
    """Production Elo: win/draw/loss only, seeded each season from the previous table."""

    def __init__(self, k: float, ha: float):
        self.k, self.ha, self.r = k, ha, {}

    def p_home(self, h, a):
        dr = self.r.get(h, 1500.0) - self.r.get(a, 1500.0) + self.ha
        return 1.0 / (1.0 + 10 ** (-dr / 400.0))

    def update(self, h, a, s):
        e = self.p_home(h, a)
        rh, ra = self.r.get(h, 1500.0), self.r.get(a, 1500.0)
        self.r[h] = rh + self.k * (s - e)
        self.r[a] = ra + self.k * ((1 - s) - (1 - e))


_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _days(t: pd.Series) -> np.ndarray:
    """Days since the epoch, whatever the datetime unit (ns or us after a parquet round trip)."""
    return ((t - _EPOCH) / pd.Timedelta(days=1)).to_numpy(float)


def _season_table_order(d: pd.DataFrame) -> list[str]:
    pts = {}
    for h, a, hg, ag in zip(d.home, d.away, d.hg, d.ag):
        pts.setdefault(h, [0, 0]); pts.setdefault(a, [0, 0])
        if hg > ag: pts[h][0] += 3
        elif hg < ag: pts[a][0] += 3
        else: pts[h][0] += 1; pts[a][0] += 1
        pts[h][1] += hg - ag; pts[a][1] += ag - hg
    return sorted(pts, key=lambda t: (-pts[t][0], -pts[t][1]))


def run_league(L: pd.DataFrame, spec: Spec, first_season: int | None = None, last_season: int = 9999) -> pd.DataFrame:
    """Walk-forward predictions for every match of one league (from first_season on)."""
    L = L.sort_values("start_time").reset_index(drop=True)
    teams = sorted(set(L.home) | set(L.away))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = L.home.map(idx).to_numpy()
    ai = L.away.map(idx).to_numpy()
    kick = L.start_time.to_numpy()
    kick_s = _days(L.start_time)
    snap_s = _days(L.snap)
    hg, ag = L.hg.to_numpy(float), L.ag.to_numpy(float)
    sxh, sxa = L.sx_h.to_numpy(float), L.sx_a.to_numpy(float)
    mh, ma = L.mkt_h.to_numpy(float), L.mkt_a.to_numpy(float)
    sy = L.sy.to_numpy()
    first_season = first_season if first_season is not None else int(sy.min()) + 1

    # Elo state per season (production: seeded from last season's table, replays from there)
    use_elo = spec.dc_weight < 1.0
    elo_cache: dict[int, tuple[Elo, int]] = {}

    def elo_for(season: int, upto_day: float) -> Elo:
        prev = L[sy == season - 1]
        n_t = len(set(L.home[sy == season]) | set(L.away[sy == season])) or 20
        if season not in elo_cache:
            e = Elo(spec.elo_k, spec.elo_ha)
            order = _season_table_order(prev) if len(prev) else []
            for rank, t in enumerate(order, 1):
                e.r[t] = 1500.0 + (n_t - rank) * 15.0
            for t in set(L.home[sy == season]) | set(L.away[sy == season]):
                if t not in e.r:
                    e.r[t] = 1500.0  # promoted clubs: rank n_teams
            elo_cache[season] = (e, 0)
            # replay the previous season's matches (production replays its training frame)
            for h, a, x, y in zip(prev.home, prev.away, prev.hg, prev.ag):
                e.update(h, a, 1.0 if x > y else 0.5 if x == y else 0.0)
            ptr_rows = np.flatnonzero(sy == season)
            elo_cache[season] = (e, 0)
            elo_cache[(season, "rows")] = ptr_rows  # type: ignore[index]
        e, ptr = elo_cache[season]
        rows = elo_cache[(season, "rows")]  # type: ignore[index]
        while ptr < len(rows) and kick_s[rows[ptr]] + SETTLE_H / 24 < upto_day:
            r = rows[ptr]
            e.update(L.home.iat[r], L.away.iat[r], 1.0 if hg[r] > ag[r] else 0.5 if hg[r] == ag[r] else 0.0)
            ptr += 1
        elo_cache[season] = (e, ptr)
        return e

    out = []
    x_prev = None
    groups = pd.Series(np.arange(len(L))).groupby(snap_s).apply(list)
    for snap_day, rows in groups.items():
        rows = np.array(rows)
        rows = rows[(sy[rows] >= first_season) & (sy[rows] <= last_season)]
        if len(rows) == 0:
            continue
        tr = (kick_s + SETTLE_H / 24 < snap_day) & (kick_s >= snap_day - spec.window_days)
        if tr.sum() < 60:
            continue
        age = snap_day - kick_s[tr]
        w = np.exp(-spec.xi * age)
        data = fastdc.FitData(
            hi=hi[tr], ai=ai[tr], hg=hg[tr], ag=ag[tr], wg=w * spec.w_goals,
        )
        rh_parts = []
        if spec.w_shots > 0 or spec.w_mkt > 0:
            # Rate rows: combine shots proxy and market rates as separate rows.
            H, A, W, RH, RA = [], [], [], [], []
            if spec.w_shots > 0:
                ws = w if spec.xi_shots is None else np.exp(-spec.xi_shots * age)
                H.append(hi[tr]); A.append(ai[tr]); W.append(ws * spec.w_shots); RH.append(sxh[tr]); RA.append(sxa[tr])
            if spec.w_mkt > 0:
                wm = w if spec.xi_mkt is None else np.exp(-spec.xi_mkt * age)
                H.append(hi[tr]); A.append(ai[tr]); W.append(wm * spec.w_mkt); RH.append(mh[tr]); RA.append(ma[tr])
            k = len(H)
            data = fastdc.FitData(
                hi=np.concatenate([hi[tr]] + H), ai=np.concatenate([ai[tr]] + A),
                hg=np.concatenate([hg[tr]] + [np.full(tr.sum(), np.nan)] * k),
                ag=np.concatenate([ag[tr]] + [np.full(tr.sum(), np.nan)] * k),
                wg=np.concatenate([w * spec.w_goals] + [np.zeros(tr.sum())] * k),
                rh=np.concatenate([np.full(tr.sum(), np.nan)] + RH),
                ra=np.concatenate([np.full(tr.sum(), np.nan)] + RA),
                wr=np.concatenate([np.zeros(tr.sum())] + W),
            )
        present = np.zeros(n, bool)
        present[hi[tr]] = True
        present[ai[tr]] = True
        ap = np.where(present, 0.0, spec.promo_att)
        dp = np.where(present, 0.0, spec.promo_def)
        x = fastdc.fit(data, n, spec.ridge, att_prior=ap, def_prior=dp, x0=x_prev, fit_rho=spec.fit_rho)
        # Teams without data: reset to their prior (the warm start must not carry stale values)
        x[:n] = np.where(present, x[:n], ap)
        x[n:2 * n] = np.where(present, x[n:2 * n], dp)
        x[n] = 0.0 if not present[0] else x[n]
        x_prev = x
        att, dfn, home, rho = x[:n], x[n:2 * n], x[2 * n], x[2 * n + 1]
        lh = np.exp(att[hi[rows]] + dfn[ai[rows]] + home)
        la = np.exp(att[ai[rows]] + dfn[hi[rows]])
        M = fastdc.score_matrix(lh, la, rho, spec.max_goals)
        p = fastdc.outcome_probs(M)
        if use_elo or spec.elo_out:
            draw_rate = float((hg[tr] == ag[tr]).mean())
            e = elo_for(int(sy[rows[0]]), snap_day)
            pe = np.array([e.p_home(L.home.iat[r], L.away.iat[r]) for r in rows])
            p_elo = np.column_stack([pe, (1 - pe) * draw_rate, (1 - pe) * (1 - draw_rate)])
        if use_elo:
            # production EnsembleModel: linear H/D/A blend with Elo, Elo draws split by the
            # empirical draw rate; matrix blended with an Elo Poisson matrix.
            trg = tr
            draw_rate = float((hg[trg] == ag[trg]).mean())
            lam_scale = float(hg[trg].mean() + ag[trg].mean())
            season = int(sy[rows[0]])
            e = elo_for(season, snap_day)
            pe = np.array([e.p_home(L.home.iat[r], L.away.iat[r]) for r in rows])
            pel = np.column_stack([pe, (1 - pe) * draw_rate, (1 - pe) * (1 - draw_rate)])
            dw = spec.dc_weight
            p = dw * p + (1 - dw) * pel
            p = p / p.sum(1, keepdims=True)
            Me = fastdc.score_matrix(np.maximum(pe * lam_scale, 0.3), np.maximum((1 - pe) * lam_scale, 0.3), 0.0, spec.max_goals)
            M = dw * M + (1 - dw) * Me
        res = pd.DataFrame({
            "row": L.index[rows].to_numpy(), "p_h": p[:, 0], "p_d": p[:, 1], "p_a": p[:, 2],
            "p_o25": fastdc.over_prob(M), "lam_h": lh, "lam_a": la, "rho": rho, "home_adv": home,
            "n_train": int(tr.sum()),
        })
        if spec.elo_out:
            res["p_elo_h"], res["p_elo_d"], res["p_elo_a"] = p_elo[:, 0], p_elo[:, 1], p_elo[:, 2]
        # Asian handicap: P(win) and P(push) on each half of the snapshot and closing lines.
        for tag, col in ((("o", "ah_line"), ("c", "ahc_line")) if spec.ah else ()):
            line = L[col].to_numpy(float)[rows]
            ok = np.isfinite(line)
            for half, sh in (("lo", -0.25), ("hi", 0.25)):
                q = np.round(np.nan_to_num(line) * 4) % 2 == 1
                l2 = np.where(q, np.nan_to_num(line) + sh, np.nan_to_num(line))
                G = M.shape[1]
                i, j = np.indices((G, G))
                m = (i - j)[None] + l2[:, None, None]
                res[f"ah{tag}_{half}_w"] = np.where(ok, (M * (m > 0)).sum((1, 2)), np.nan)
                res[f"ah{tag}_{half}_p"] = np.where(ok, (M * (m == 0)).sum((1, 2)), np.nan)
        out.append(res)
    if not out:
        return pd.DataFrame()
    R = pd.concat(out, ignore_index=True)
    R = R.merge(L, left_on="row", right_index=True, how="left").drop(columns=["row"])
    R["spec"] = spec.name
    return R


def _run_one(args):
    L, spec, first, last = args
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    return run_league(L, spec, first, last)


def run(df: pd.DataFrame, spec: Spec, leagues: list[str] | None = None, *, first_season: int | None = None,
        last_season: int = 9999, workers: int = 6, spec_by_league: dict[str, Spec] | None = None) -> pd.DataFrame:
    """Run a spec over many leagues in parallel (one process per league)."""
    from concurrent.futures import ProcessPoolExecutor
    leagues = leagues or sorted(df.league.unique())
    jobs = []
    for lg in leagues:
        L = df[df.league == lg]
        s = (spec_by_league or {}).get(lg, spec)
        jobs.append((L, s, first_season, last_season))
    if workers <= 1:
        parts = [_run_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_run_one, jobs))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
