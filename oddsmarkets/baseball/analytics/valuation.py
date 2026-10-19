"""
Valuation v2 (docs/VALUE_SECTIONS.md section 4; MODELS.md section 26): a player's value as projected wins over the next
five seasons, discounted, with an uncertainty band, his availability, the scarcity of his position, and for Triple-A
players the prospect context. analytics/trades.py uses the same machinery to value every trade at the time it was made.

The currency is Bullpen WAR (models/war.py). Nothing here re-estimates a season's WAR: it projects, splits and
calibrates it.

1. Season by season. Next season's rate is value.py's Marcel-style projection (three seasons, regressed, aged). Season t
   (t = 1..5) ages it by the MLB aging curve, times Marcel's playing time: the "naive" path. Each horizon is calibrated
   on history (`horizon_fit`): the slope of actual WAR in season B+t on the naive projection made after season B (through
   the origin; players with 50+ PA or BF in B; a player who did not play counts as 0 WAR), by kind and age band, so
   attrition, injuries and the regression the naive path misses are in the expectation.
2. Value = sum over t of 0.92^(t-1) x E[WAR_t] (a win next year is worth 8% less than one now). WAR is already above
   replacement, so this is the surplus over a freely available player; salaries are not known (no legitimate free
   source), so it is not net of pay.
3. Uncertainty (`band_fit`): the 10th and 90th percentiles of actual minus expected WAR, by kind and band of the
   expectation, for next season and for the next three seasons together, fitted walk-forward (each base season's band
   from earlier bases) and checked for coverage.
4. Availability (`il_fit`): injured-list days per season from the transactions (analytics/moves.py); next season's days
   from the last two seasons' days and age (least squares, walk-forward against the league mean), and the chance of 30 or
   more days (logistic). Whether the expected days improve Marcel's playing time is tested walk-forward (`pt_fit`); they
   enter the projection only if they do.
5. Scarcity (`scarcity`): at each position the projected full-season value (value.value_ft) of the 15th-best regular
   whose primary position it is (the median starter of 30 clubs); a player's "wins over the median starter" at his
   position, and each position's starter line against the mean of the lines.
6. Prospects (`prospect_fit`): a minor leaguer's expected MLB WAR over the four seasons after a minor-league season
   (discounted), from the Stats API stat lines of every level (Triple-A, Double-A, High-A, Single-A; 2015 on): his
   level, his age against the level's mean, his performance against the level's (OPS for hitters, strikeouts minus
   walks per batter faced for pitchers, as a z-score shrunk by the sample) and the sample; a log-link regression on the
   2015-2022 cohorts (a player who never reached the majors counts as 0), checked out of sample on 2021-22 after fitting
   on the cohorts to 2019. It sees stat lines only, not scouting grades.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import value as V

log = logging.getLogger(__name__)
VERSION = "valuation-1"
DISCOUNT = 0.92
HORIZON = 5
WOBA_SCALE = 1.24
AGE_BANDS = ((0, 26), (26, 30), (30, 33), (33, 99))
EXCLUDE = (2020,)                     # the 60-game season: neither a base nor a target of the horizon fits


def age_band(age) -> int:
    a = float(age) if age is not None else 28.0
    for i, (lo, hi) in enumerate(AGE_BANDS):
        if lo <= a < hi:
            return i
    return len(AGE_BANDS) - 1


# ── splits by club and date (the plate-appearance table) ────────────────────

def stint_table(level: str, season: int, store: dict | None = None) -> pd.DataFrame | None:
    """Per player, club and date: plate appearances (batters faced), the sum of wOBA values and of their denominators.
    Columns pid, kind ("H" batting, "P" pitching), tid, date, n, ws, wd. Cached on the pitch table's mtime."""
    from oddsmarkets.baseball.models import projections as PJ
    src = an.pitch_path(level, season)
    cdir = an.cache_root() / "value"
    if not src.exists():
        olds = sorted(cdir.glob(f"stints_{level}_{season}_*.parquet"))
        return pd.read_parquet(olds[-1]) if olds else None
    from oddsmarkets.baseball.models import _io as _pio
    cp = cdir / f"stints_{level}_{season}_{_pio.stamp(src)}.parquet"
    if cp.exists():
        try:
            return pd.read_parquet(cp)
        except Exception:                                   # noqa: BLE001
            pass
    pa = PJ.pa_table(level, season)
    if pa is None or not len(pa):
        return None
    pa = pa[pa["game_type"].astype(str) == "R"]
    st = store if store is not None else an.load_store(level, season)
    ab = an.abbr_to_tid(st or {})
    home = pa["home_team"].astype(str).str.upper().map(ab)
    away = pa["away_team"].astype(str).str.upper().map(ab)
    top = pa["top"].astype(bool)
    bat_t = np.where(top, away, home)
    fld_t = np.where(top, home, away)
    base = pd.DataFrame({"date": pa["game_date"].astype(str).str[:10], "ws": pa["woba_value"].astype(float).fillna(0.0),
                         "wd": pa["woba_denom"].astype(float).fillna(0.0)})
    hb = base.assign(pid=pa["batter"].astype(str), tid=bat_t, kind="H")
    pb = base.assign(pid=pa["pitcher"].astype(str), tid=fld_t, kind="P")
    out = pd.concat([hb, pb], ignore_index=True)
    out["tid"] = out["tid"].astype(object).where(out["tid"].notna(), None)
    out = out.dropna(subset=["tid"])
    out["n"] = 1
    g = out.groupby(["pid", "kind", "tid", "date"], as_index=False).agg(n=("n", "sum"), ws=("ws", "sum"), wd=("wd", "sum"))
    g["tid"] = g["tid"].astype(str)
    cdir.mkdir(parents=True, exist_ok=True)
    for old in cdir.glob(f"stints_{level}_{season}_*.parquet"):
        old.unlink(missing_ok=True)
    g.to_parquet(cp, index=False)
    return g


class Splits:
    """A player's plate appearances (batters faced) by club and date, season by season, for splitting a season's WAR."""

    def __init__(self, tables: dict[int, pd.DataFrame | None]):
        self.by: dict[int, dict[tuple, tuple]] = {}
        self.lg: dict[int, dict[str, float]] = {}
        for s, df in tables.items():
            if df is None or not len(df):
                continue
            d: dict[tuple, tuple] = {}
            df = df.sort_values(["kind", "pid", "date"])
            for (kind, pid), grp in df.groupby(["kind", "pid"], sort=False):
                d[(kind, str(pid))] = (grp["tid"].to_numpy(dtype=object), grp["date"].to_numpy(dtype=object),
                                       grp["n"].to_numpy(dtype=float), grp["ws"].to_numpy(dtype=float), grp["wd"].to_numpy(dtype=float))
            self.by[s] = d
            hh = df[df["kind"] == "H"]
            self.lg[s] = {"woba": float(hh["ws"].sum() / max(hh["wd"].sum(), 1.0))}

    def part(self, kind: str, pid: str, season: int, club: str | None = None, lo: str | None = None, hi: str | None = None) -> tuple[float, float, float]:
        """(n, wOBA sum, wOBA denominator) for the player in the season, optionally with one club and dates lo..hi."""
        x = (self.by.get(season) or {}).get((kind, str(pid)))
        if x is None:
            return 0.0, 0.0, 0.0
        tid, dts, n, ws, wd = x
        m = np.ones(len(n), dtype=bool)
        if club is not None:
            m &= tid == str(club)
        if lo is not None:
            m &= dts >= lo
        if hi is not None:
            m &= dts <= hi
        return float(n[m].sum()), float(ws[m].sum()), float(wd[m].sum())

    def clubs(self, kind: str, pid: str, season: int) -> dict[str, float]:
        x = (self.by.get(season) or {}).get((kind, str(pid)))
        if x is None:
            return {}
        out: dict[str, float] = defaultdict(float)
        for t, n in zip(x[0], x[2]):
            out[str(t)] += float(n)
        return dict(out)


def war_part(war: float | None, kind: str, tot: tuple, part: tuple, rpw: float = 10.0) -> float:
    """The share of a season's WAR earned in a part of it: pro rata by plate appearances (batters faced), moved by how
    much better or worse his wOBA (allowed) was in the part than over the season, in runs (wOBA scale 1.24) over runs
    per win. The parts of a season add up to the season."""
    if war is None or tot[0] <= 0 or part[0] <= 0:
        return 0.0
    share = part[0] / tot[0]
    w_season = tot[1] / tot[2] if tot[2] > 0 else 0.0
    w_part = part[1] / part[2] if part[2] > 0 else w_season
    runs = (w_part - w_season) * part[2] / WOBA_SCALE
    return float(war) * share + (runs if kind == "H" else -runs) / rpw


# ── the in-season proxy: WAR rate from wOBA to date ─────────────────────────

def proxy_fit(hist: dict, splits: Splits, kind: str, seasons: Iterable[int]) -> list[float]:
    """[a, b] of WAR rate = a + b x (wOBA - league wOBA) / scale x unit (sign flipped for pitchers), least squares
    weighted by the sample over full seasons (n >= 200 / 150); used for a season's part before a trade date."""
    X, y, w = [], [], []
    unit = V.UNIT[kind]
    for key, h in hist.items():
        if not key.startswith(kind + ":"):
            continue
        pid = key.split(":", 1)[1]
        for s in seasons:
            x = h.get(s)
            if not x or x.get("war") is None or (x.get("n") or 0) < V.MIN_TARGET_N[kind] or s not in splits.lg:
                continue
            n, ws, wd = splits.part(kind, pid, s)
            if wd <= 0:
                continue
            r = (ws / wd - splits.lg[s]["woba"]) / WOBA_SCALE * unit * (1 if kind == "H" else -1)
            X.append([1.0, r])
            y.append(float(x["war"]) / float(x["n"]) * unit)
            w.append(float(x["n"]))
    if len(y) < 50:
        return [0.0, 0.1]
    X, y, w = np.array(X), np.array(y), np.sqrt(np.array(w))
    coef, *_ = np.linalg.lstsq(X * w[:, None], y * w, rcond=None)
    return [float(c) for c in coef]


def proxy_war(kind: str, part: tuple, lg_woba: float, coef: list[float]) -> float:
    """WAR proxy for a part of a season from its wOBA (allowed)."""
    n, ws, wd = part
    if n <= 0 or wd <= 0:
        return 0.0
    unit = V.UNIT[kind]
    r = (ws / wd - lg_woba) / WOBA_SCALE * unit * (1 if kind == "H" else -1)
    return (coef[0] + coef[1] * r) * n / unit


# ── the season-by-season path ───────────────────────────────────────────────

def naive_path(rate1: float | None, pt: float, age1, kind: str, curve: list[float], horizon: int = HORIZON) -> list[float]:
    """[WAR_1 .. WAR_h] before calibration: the rate aged year by year (value.age_delta) times the playing time."""
    if rate1 is None:
        return [0.0] * horizon
    out, r = [], float(rate1)
    for t in range(horizon):
        if t:
            r += V.age_delta(curve, (float(age1) + t - 1) if age1 is not None else None)
        out.append(r * pt / V.UNIT[kind])
    return out


def _base_proj(hist: dict, base: int, ks: dict, curves: dict, level: str, pt_adj: dict | None = None) -> dict:
    """{kind: {pid: {"rate", "pt", "age"}}} for season base+1 from seasons <= base (value.project + Marcel's time)."""
    out = {}
    for kind in ("H", "P"):
        kh = ks.get(kind) or [1500.0, 0.0]
        kh = kh if isinstance(kh, (list, tuple)) else [float(kh), 0.0]
        pr = V.project(hist, base + 1, kind, kh[0], curves.get(kind) or [0, 0, 0], kh[1])
        d = {}
        for pid, p in pr.items():
            h = hist.get(kind + ":" + pid) or {}
            if base not in h:
                continue
            pt = V.marcel_time(h, base, kind, level)
            if pt_adj:
                pt = max(pt * (pt_adj.get((kind, pid)) or 1.0), 0.0)
            d[pid] = {"rate": p["rate"], "pt": pt, "age": p.get("age"), "n": h[base].get("n") or 0}
        out[kind] = d
    return out


def horizon_fit(hist: dict, seasons: list[int], ks: dict, curves: dict, level: str, horizon: int = HORIZON, min_n: int = 50,
                upto: int | None = None) -> dict:
    """{kind: {band: [slope_1 .. slope_h]}} (with "n" per cell) from bases B whose B+t is a completed season <= upto."""
    last = upto if upto is not None else max(seasons)
    acc = {(k, b, t): [0.0, 0.0, 0] for k in ("H", "P") for b in range(len(AGE_BANDS)) for t in range(horizon)}
    for B in seasons:
        if B in EXCLUDE or B - 2 < min(seasons) or B >= last:
            continue
        bp = _base_proj(hist, B, ks, curves, level)
        for kind, d in bp.items():
            for pid, p in d.items():
                if p["n"] < min_n:
                    continue
                path = naive_path(p["rate"], p["pt"], p["age"], kind, curves.get(kind) or [0, 0, 0], horizon)
                h = hist.get(kind + ":" + pid) or {}
                band = age_band(p["age"])
                for t in range(horizon):
                    T = B + 1 + t
                    if T > last or T in EXCLUDE:
                        continue
                    a = float((h.get(T) or {}).get("war") or 0.0)
                    c = acc[(kind, band, t)]
                    c[0] += a * path[t]
                    c[1] += path[t] * path[t]
                    c[2] += 1
    out: dict[str, dict] = {}
    for (kind, band, t), (xy, xx, n) in acc.items():
        cell = out.setdefault(kind, {}).setdefault(str(band), {"slope": [None] * horizon, "n": [0] * horizon})
        cell["slope"][t] = round(xy / xx, 4) if xx > 0 and n >= 30 else None
        cell["n"][t] = n
    # a missing cell borrows the nearest shorter horizon of its band, then the kind's pooled value
    for kind, bands in out.items():
        for band, cell in bands.items():
            for t in range(horizon):
                if cell["slope"][t] is None:
                    prev = next((cell["slope"][j] for j in range(t - 1, -1, -1) if cell["slope"][j] is not None), None)
                    cell["slope"][t] = prev if prev is not None else 0.8 ** (t + 1)
    return out


def expected_path(rate1, pt, age1, kind: str, curves: dict, hfit: dict, horizon: int = HORIZON) -> list[float]:
    naive = naive_path(rate1, pt, age1, kind, curves.get(kind) or [0, 0, 0], horizon)
    sl = ((hfit.get(kind) or {}).get(str(age_band(age1))) or {}).get("slope") or [1.0] * horizon
    return [naive[t] * (sl[t] if sl[t] is not None else 1.0) for t in range(horizon)]


def discounted(path: list[float], weights: list[float] | None = None) -> float:
    w = weights or [1.0] * len(path)
    return float(sum((DISCOUNT ** t) * path[t] * w[t] for t in range(len(path))))


# ── uncertainty ─────────────────────────────────────────────────────────────

E_BANDS = (-99.0, 0.5, 1.5, 3.0, 5.0)


def _ebin(e: float) -> int:
    i = 0
    for j, lo in enumerate(E_BANDS):
        if e >= lo:
            i = j
    return i


def band_fit(hist: dict, seasons: list[int], ks: dict, curves: dict, hfit: dict, level: str, min_n: int = 50) -> dict:
    """{kind: {"1": {bin: [q10, q90, n]}, "3": {...}}, "coverage": {...}}: residual quantiles of next season's WAR and of
    the next three seasons' (actual - expected), by bin of the expectation; coverage of the 80% band out of sample
    (each base's quantiles from earlier bases)."""
    last = max(seasons)
    res: dict[tuple, list] = defaultdict(list)            # (kind, horizon, bin) -> [(base, residual)]
    for B in seasons:
        if B in EXCLUDE or B - 2 < min(seasons) or B >= last:
            continue
        bp = _base_proj(hist, B, ks, curves, level)
        for kind, d in bp.items():
            for pid, p in d.items():
                if p["n"] < min_n:
                    continue
                ep = expected_path(p["rate"], p["pt"], p["age"], kind, curves, hfit, 3)
                h = hist.get(kind + ":" + pid) or {}
                if B + 1 <= last and B + 1 not in EXCLUDE:
                    a1 = float((h.get(B + 1) or {}).get("war") or 0.0)
                    res[(kind, "1", _ebin(ep[0]))].append((B, a1 - ep[0]))
                if B + 3 <= last and not any(T in EXCLUDE for T in (B + 1, B + 2, B + 3)):
                    a3 = sum(float((h.get(B + 1 + t) or {}).get("war") or 0.0) for t in range(3))
                    res[(kind, "3", _ebin(sum(ep)))].append((B, a3 - sum(ep)))
    out: dict[str, Any] = {}
    cover: dict[str, list] = defaultdict(lambda: [0, 0])
    for (kind, hz, b), lst in res.items():
        r = np.array([x[1] for x in lst])
        cell = out.setdefault(kind, {}).setdefault(hz, {})
        cell[str(b)] = [round(float(np.quantile(r, 0.1)), 2), round(float(np.quantile(r, 0.9)), 2), int(len(r))] if len(r) >= 20 else None
        bases = sorted({x[0] for x in lst})
        for B in bases:                               # out of sample: the quantiles of earlier bases
            prior = np.array([x[1] for x in lst if x[0] < B])
            cur = [x[1] for x in lst if x[0] == B]
            if len(prior) < 40:
                continue
            q10, q90 = np.quantile(prior, 0.1), np.quantile(prior, 0.9)
            c = cover[f"{kind}{hz}"]
            c[0] += sum(1 for v in cur if q10 <= v <= q90)
            c[1] += len(cur)
    out["coverage"] = {k: {"inside": v[0], "n": v[1], "rate": round(v[0] / v[1], 3) if v[1] else None} for k, v in cover.items()}
    # empty bins borrow their neighbour
    for kind in ("H", "P"):
        for hz in ("1", "3"):
            cell = (out.get(kind) or {}).get(hz) or {}
            for b in range(len(E_BANDS)):
                if cell.get(str(b)) is None:
                    nb = next((cell.get(str(j)) for j in sorted(range(len(E_BANDS)), key=lambda j: abs(j - b)) if cell.get(str(j))), None)
                    cell[str(b)] = nb
            out.setdefault(kind, {})[hz] = cell
    return out


def band(bfit: dict, kind: str, hz: str, e: float) -> tuple[float | None, float | None]:
    q = (((bfit.get(kind) or {}).get(hz) or {}).get(str(_ebin(e))))
    if not q:
        return None, None
    return e + q[0], e + q[1]


# ── availability ────────────────────────────────────────────────────────────

def il_table(days: dict[str, dict[int, dict]]) -> dict[str, dict[int, int]]:
    return {pid: {s: int(v.get("days") or 0) for s, v in d.items()} for pid, d in days.items()}


def _il_rows(hist: dict, il: dict, seasons: list[int], kind: str, min_n: int = 50):
    """(base season, pid, [1, days_S, days_S-1, age-28], days_S+1, n_S+1, marcel pt) for players with n_S >= min_n."""
    out = []
    for key, h in hist.items():
        if not key.startswith(kind + ":"):
            continue
        pid = key.split(":", 1)[1]
        d = il.get(pid) or {}
        for s, x in h.items():
            if s + 1 not in seasons or s in EXCLUDE or s + 1 in EXCLUDE or (x.get("n") or 0) < min_n:
                continue
            age = x.get("age")
            feats = [1.0, float(d.get(s, 0)), float(d.get(s - 1, 0)), (float(age) - 28.0) if age is not None else 0.0]
            nxt = h.get(s + 1) or {}
            out.append((s, pid, feats, float(d.get(s + 1, 0)), float(nxt.get("n") or 0.0), V.marcel_time(h, s, kind, "mlb")))
    return out


def _logit_fit(X: np.ndarray, y: np.ndarray, iters: int = 25, ridge: float = 1e-3) -> np.ndarray:
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(X @ b)))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        g = X.T @ (y - p) - ridge * b
        step = np.linalg.solve(H, g)
        b += step
        if np.max(np.abs(step)) < 1e-7:
            break
    return b


def il_fit(hist: dict, il: dict, seasons: list[int], first_tx: int = 2015) -> dict:
    """{kind: {"coef" (days), "logit" (30+ days), "mean", "validation": {...}, "pt": {...}}}. Walk-forward: for each
    target season the coefficients come from earlier targets; MAE of the days against the earlier seasons' mean, and the
    playing-time test (Marcel's time, and Marcel's time scaled by (1 - (expected days - mean) / 186), against next
    season's PA or BF)."""
    out = {}
    ss = [s for s in seasons if s >= first_tx]
    for kind in ("H", "P"):
        rows = [r for r in _il_rows(hist, il, ss, kind) if r[0] - 1 >= first_tx]
        if len(rows) < 200:
            out[kind] = None
            continue
        bases = sorted({r[0] for r in rows})
        val = {"mae_model": 0.0, "mae_mean": 0.0, "n": 0, "brier_model": 0.0, "brier_rate": 0.0,
               "pt_rmse_marcel": 0.0, "pt_rmse_il": 0.0, "pt_n": 0}
        for B in bases:
            tr = [r for r in rows if r[0] < B]
            te = [r for r in rows if r[0] == B]
            if len(tr) < 200 or not te:
                continue
            X = np.array([r[2] for r in tr])
            y = np.array([r[3] for r in tr])
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            lb = _logit_fit(X / np.array([1, 60, 60, 10]), (y >= 30).astype(float))
            mu, rate30 = float(y.mean()), float((y >= 30).mean())
            Xt = np.array([r[2] for r in te])
            yt = np.array([r[3] for r in te])
            pred = np.clip(Xt @ coef, 0, 186)
            p30 = 1 / (1 + np.exp(-((Xt / np.array([1, 60, 60, 10])) @ lb)))
            val["mae_model"] += float(np.abs(pred - yt).sum())
            val["mae_mean"] += float(np.abs(mu - yt).sum())
            val["brier_model"] += float(((p30 - (yt >= 30)) ** 2).sum())
            val["brier_rate"] += float(((rate30 - (yt >= 30)) ** 2).sum())
            val["n"] += len(te)
            nt = np.array([r[4] for r in te])
            pt = np.array([r[5] for r in te])
            ok = nt > 0
            adj = pt * np.clip(1 - (pred - mu) / 186.0, 0.3, 1.3)
            val["pt_rmse_marcel"] += float(((pt - nt)[ok] ** 2).sum())
            val["pt_rmse_il"] += float(((adj - nt)[ok] ** 2).sum())
            val["pt_n"] += int(ok.sum())
        X = np.array([r[2] for r in rows])
        y = np.array([r[3] for r in rows])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        lb = _logit_fit(X / np.array([1, 60, 60, 10]), (y >= 30).astype(float))
        n = max(val["n"], 1)
        pn = max(val["pt_n"], 1)
        v = {"mae_model": round(val["mae_model"] / n, 2), "mae_mean": round(val["mae_mean"] / n, 2),
             "brier_model": round(val["brier_model"] / n, 4), "brier_rate": round(val["brier_rate"] / n, 4), "n": val["n"],
             "pt_rmse_marcel": round(math.sqrt(val["pt_rmse_marcel"] / pn), 1), "pt_rmse_il": round(math.sqrt(val["pt_rmse_il"] / pn), 1),
             "pt_n": val["pt_n"]}
        v["pt_helps"] = v["pt_rmse_il"] < v["pt_rmse_marcel"]
        out[kind] = {"coef": [round(float(c), 4) for c in coef], "logit": [round(float(c), 4) for c in lb], "mean": round(float(y.mean()), 2),
                     "rate30": round(float((y >= 30).mean()), 4), "features": ["1", "days last season", "days the season before", "age - 28"],
                     "validation": v}
    return out


def il_expect(fit: dict | None, d1: float, d2: float, age) -> tuple[float | None, float | None]:
    """(expected injured-list days next season, chance of 30 or more)."""
    if not fit:
        return None, None
    x = np.array([1.0, d1, d2, (float(age) - 28.0) if age is not None else 0.0])
    e = float(np.clip(x @ np.array(fit["coef"]), 0, 186))
    p = float(1 / (1 + np.exp(-((x / np.array([1, 60, 60, 10])) @ np.array(fit["logit"])))))
    return e, p


# ── scarcity ────────────────────────────────────────────────────────────────

def scarcity(rows: list[dict], proj: dict, slot: dict, rpw: float, rank: int = 15) -> dict:
    """{pos: {"line": the projected full-season value of the rank-th best regular whose primary position it is,
    "n": players, "delta": the mean line minus this line (positive: scarce)}} (DH and the pitchers' roles included; a
    rotation slot is a fifth of the starters' work, a bullpen slot a seventh)."""
    vals: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("war") is None or (r.get("n") or 0) < (100 if r["kind"] == "H" else 80):
            continue
        p = (proj.get(r["kind"]) or {}).get(r["pid"]) or {}
        rate = p.get("rate") if p.get("rate") is not None else r.get("rate")
        pos = r.get("pos")
        if pos not in V.POSITIONS:
            continue
        v = V.slot_value(r, pos, rate, slot, rpw)
        if v is not None:
            vals[pos].append(v)
    lines = {}
    for pos, lst in vals.items():
        lst.sort(reverse=True)
        k = min(rank, len(lst)) - 1
        if pos == "SP":
            k = min(rank * 5, len(lst)) - 1          # 30 clubs x 5 rotation slots: the median of 150
        elif pos == "RP":
            k = min(rank * 7, len(lst)) - 1
        if k >= 0:
            lines[pos] = {"line": round(lst[k], 2), "n": len(lst)}
    hit = [v["line"] for p, v in lines.items() if p in V.HIT_POS and p != "DH"]
    m = float(np.mean(hit)) if hit else 0.0
    for p, v in lines.items():
        if p in V.HIT_POS:
            v["delta"] = round(m - v["line"], 2)
    return lines


def _spearman(a, b) -> float | None:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 5 or np.std(a) == 0 or np.std(b) == 0:
        return None
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


# ── a player's valuation ────────────────────────────────────────────────────

def player_valuation(kind: str, pid: str, proj: dict, hist: dict, curves: dict, hfit: dict, bfit: dict, il: dict, ilfit: dict,
                     season: int, use_il_pt: dict) -> dict | None:
    """Next season's expectation and band, three seasons' with band, the five-season value, injured-list history and
    expectation, for one player (proj: value_build.proj_for's {"rate", "war", "age"} for next season)."""
    p = proj.get(pid)
    h = hist.get(kind + ":" + pid) or {}
    if not p or p.get("rate") is None:
        return None
    pt = V.marcel_time(h, season, kind, "mlb") if season in h else 0.0
    d = il.get(pid) or {}
    d1, d2 = float(d.get(season, 0)), float(d.get(season - 1, 0))
    e_il, p30 = il_expect((ilfit or {}).get(kind), d1, d2, p.get("age"))
    f = (ilfit or {}).get(kind) or {}
    if use_il_pt.get(kind) and e_il is not None:
        pt *= min(max(1 - (e_il - f.get("mean", 0.0)) / 186.0, 0.3), 1.3)
    path = expected_path(p["rate"], pt, p.get("age"), kind, curves, hfit)
    lo1, hi1 = band(bfit, kind, "1", path[0])
    s3 = sum(path[:3])
    lo3, hi3 = band(bfit, kind, "3", s3)
    return {"e1": path[0], "lo1": lo1, "hi1": hi1, "e3": s3, "lo3": lo3, "hi3": hi3, "value": discounted(path), "path": path,
            "il_days": [int(d.get(season - 2, 0)), int(d2), int(d1)], "il_exp": e_il, "il_p30": p30, "pt": pt}


# ── prospects from minor-league stat lines (any level) ──────────────────────

MINORS = ("aaa", "aa", "hia", "a")
MINOR_NAME = {"aaa": "Triple-A", "aa": "Double-A", "hia": "High-A", "a": "Single-A"}


def minor_lines(seasons: Iterable[int]) -> dict[int, dict[str, dict[str, dict]]]:
    """{season: {level: {"H": {pid: line}, "P": {pid: line}}}} from the cached Stats API lines (analytics/mlbapi.py)."""
    from oddsmarkets.baseball.analytics import mlbapi
    out: dict[int, dict] = {}
    for s in seasons:
        for lv in MINORS:
            h = mlbapi.season_lines(lv, s, "hitting")
            p = mlbapi.season_lines(lv, s, "pitching")
            if h or p:
                out.setdefault(s, {})[lv] = {"H": h or {}, "P": p or {}}
    return out


def _perf(kind: str, x: dict) -> tuple[float, float]:
    """(performance, sample): hitters OPS over PA, pitchers (K - BB) / BF over BF."""
    if kind == "H":
        pa, ab = float(x.get("pa") or 0), float(x.get("ab") or 0)
        if pa <= 0 or ab <= 0:
            return float("nan"), 0.0
        h, d, t, hr = (float(x.get(k) or 0) for k in ("h", "d", "t", "hr"))
        bb, hbp, sf = (float(x.get(k) or 0) for k in ("bb", "hbp", "sf"))
        obp = (h + bb + hbp) / max(ab + bb + hbp + sf, 1.0)
        slg = (h + d + 2 * t + 3 * hr) / ab
        return obp + slg, pa
    bf = float(x.get("bf") or 0)
    if bf <= 0:
        return float("nan"), 0.0
    return (float(x.get("so") or 0) - float(x.get("bb") or 0)) / bf, bf


def prospect_rows(lines: dict, min_n: float = 100.0) -> dict[tuple, dict]:
    """{(season, kind, pid): {"level", "age", "age_rel", "z", "n", "perf"}} at each player's highest level of the season
    with min_n (else his largest sample); z is the performance's z-score within the level and season (players with min_n),
    age_rel his age minus the level's sample-weighted mean age."""
    out: dict[tuple, dict] = {}
    for s, levels in lines.items():
        stats: dict[tuple, tuple] = {}
        for lv, kinds in levels.items():
            for kind, rows in kinds.items():
                vals, ages = [], []
                for pid, x in rows.items():
                    v, n = _perf(kind, x)
                    if n >= min_n and math.isfinite(v):
                        vals.append(v)
                        if x.get("age"):
                            ages.append((float(x["age"]), n))
                if len(vals) >= 20:
                    mage = sum(a * n for a, n in ages) / max(sum(n for _, n in ages), 1.0) if ages else 24.0
                    stats[(lv, kind)] = (float(np.mean(vals)), float(np.std(vals)) or 1.0, mage)
        best: dict[tuple, tuple] = {}
        for lv in MINORS:                                   # highest level first
            for kind, rows in (levels.get(lv) or {}).items():
                for pid, x in rows.items():
                    v, n = _perf(kind, x)
                    if n <= 0 or (lv, kind) not in stats:
                        continue
                    key = (kind, pid)
                    cur = best.get(key)
                    if cur is None or (cur[2] < min_n and n > cur[2]):
                        best[key] = (lv, x, n, v)
        for (kind, pid), (lv, x, n, v) in best.items():
            mu, sd, mage = stats[(lv, kind)]
            age = float(x["age"]) if x.get("age") else None
            out[(s, kind, pid)] = {"level": lv, "age": age, "age_rel": (age - mage) if age is not None else 0.0,
                                   "z": ((v - mu) / sd) if math.isfinite(v) else 0.0, "n": n, "perf": v}
    return out


def _pfeats(r: dict, k: float = 150.0) -> list[float]:
    """The prospect model's features; the performance z is shrunk by the sample (n / (n + 150))."""
    lv = r["level"]
    z = max(min(r["z"], 4.0), -4.0) * r["n"] / (r["n"] + k)
    ar = max(min(r["age_rel"], 6.0), -6.0)
    hi = 1.0 if lv in ("aaa", "aa") else 0.0
    return [float(lv == "aaa"), float(lv == "aa"), float(lv == "hia"), float(lv == "a"), ar, ar * ar, ar * hi, z, z * hi,
            math.log(max(r["n"], 30.0) / 300.0)]


def poisson_fit(X: np.ndarray, y: np.ndarray, ridge: float = 1.0, iters: int = 60) -> np.ndarray:
    """Log-link (Poisson pseudo-likelihood) regression of a non-negative outcome, ridge-penalised, by Newton steps."""
    b = np.zeros(X.shape[1])
    b[:4] = math.log(max(float(y.mean()), 1e-3))
    for _ in range(iters):
        mu = np.exp(np.clip(X @ b, -20, 5))
        g = X.T @ (y - mu) - ridge * b
        H = X.T @ (X * mu[:, None]) + ridge * np.eye(X.shape[1])
        st = np.linalg.solve(H, g)
        b += st
        if np.abs(st).max() < 1e-8:
            break
    return b


PFEATS = ["Triple-A", "Double-A", "High-A", "Single-A", "age minus the level mean", "its square", "age at Double-A or Triple-A",
          "performance z (shrunk)", "z at Double-A or Triple-A", "log(sample / 300)"]


def prospect_fit(prows: dict, hist: dict, people: dict, last: int, first: int = 2015, horizon: int = 4) -> dict:
    """{kind: {"coef", "scale", "features", "n", "validation"}}: expected MLB WAR over the four seasons after a minor-league
    season (discounted 8% a year; 0 for a player who never played in the majors): a log-link regression of the outcome's
    positive part (poisson_fit) times the ratio of the outcome's mean to its positive part's mean ("scale"), on the cohorts
    whose four seasons are complete. Players with more than 130 PA / 100 BF in the majors through the season, or a debut three or
    more seasons before it, are not prospects and are left out. Out of sample: fitted on cohorts to 2019, scored on 2021-22
    against the mean of each level."""
    data: dict[str, list] = {"H": [], "P": []}
    for (s, kind, pid), r in prows.items():
        if s < first or s + horizon > last:
            continue
        if _established(hist, kind, pid, s, people):
            continue
        y, y2 = 0.0, 0.0
        for t in range(1, horizon + 1):
            T = s + t
            w = sum(float(((hist.get(k + ":" + pid) or {}).get(T) or {}).get("war") or 0.0) for k in ("H", "P"))
            y += (DISCOUNT ** (t - 1)) * w
            if t <= 2:
                y2 += w
        data[kind].append((s, _pfeats(r), y, r["level"], y2))
    out = {}
    for kind, rows in data.items():
        if len(rows) < 200:
            out[kind] = None
            continue
        X = np.array([r[1] for r in rows])
        y = np.array([r[2] for r in rows])
        coef = poisson_fit(X, np.maximum(y, 0.0))
        scale = float(y.mean() / max(np.maximum(y, 0.0).mean(), 1e-6))
        val = None
        tr = [r for r in rows if r[0] <= 2019]
        te = [r for r in rows if r[0] >= 2021]
        if len(tr) >= 200 and len(te) >= 50:
            ytr = np.array([r[2] for r in tr])
            ct = poisson_fit(np.array([r[1] for r in tr]), np.maximum(ytr, 0.0))
            sc = float(ytr.mean() / max(np.maximum(ytr, 0.0).mean(), 1e-6))
            pt = np.exp(np.array([r[1] for r in te]) @ ct) * sc
            yt = np.array([r[2] for r in te])
            lvmean = {lv: float(np.mean([r[2] for r in tr if r[3] == lv] or [0.0])) for lv in MINORS}
            base = np.array([lvmean[r[3]] for r in te])
            top = np.argsort(-pt)[: max(len(pt) // 20, 10)]
            val = {"cohorts": sorted({r[0] for r in te}), "n": len(te), "mae_model": round(float(np.abs(pt - yt).mean()), 3),
                   "mae_level_mean": round(float(np.abs(base - yt).mean()), 3), "spearman_model": _r3(_spearman(pt, yt)),
                   "spearman_level_mean": _r3(_spearman(base, yt)), "top5pct_mean_actual": round(float(yt[top].mean()), 3),
                   "all_mean_actual": round(float(yt.mean()), 3), "top5pct_mean_pred": round(float(pt[top].mean()), 3)}
        early = float(np.mean([r[4] for r in rows])) / max(float(y.mean()), 1e-6)
        out[kind] = {"coef": [round(float(c), 5) for c in coef], "scale": round(scale, 4), "early_share": round(min(max(early, 0.0), 1.0), 3),
                     "features": PFEATS, "n": len(rows),
                     "validation": val, "mean": round(float(y.mean()), 3), "share_1war": round(float((y >= 1.0).mean()), 3)}
    return out


def _r3(x):
    return round(x, 3) if x is not None else None


def _established(hist: dict, kind: str, pid: str, s: int, people: dict) -> bool:
    n = sum(float(x.get("n") or 0) for ss, x in (hist.get(kind + ":" + pid) or {}).items() if ss <= s)
    if n > (130 if kind == "H" else 100):
        return True
    deb = (people.get(pid) or {}).get("debut")
    return bool(deb) and int(deb) <= s - 3


def prospect_value(fit: dict | None, kind: str, r: dict | None) -> float | None:
    f = (fit or {}).get(kind)
    if not f or not r:
        return None
    return float(math.exp(min(float(np.array(_pfeats(r)) @ np.array(f["coef"])), 5.0)) * float(f.get("scale") or 1.0))
