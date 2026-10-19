"""
Bullpen projections: component projections for hitters and pitchers, each skill regressed at its own rate.

Data
----
Per season and level, the pitch table becomes a plate-appearance table (`_dio.plate_appearances`, built
month by month and cached as Parquet) and then per-player count aggregates (cached): PA/BF and the nine
outcome classes overall and by opposing hand, balls in play, ground balls, the sum and count of Savant's
expected wOBA on contact (or builder C's xwOBA+ when its module provides per-PA values), the PA-max bat
speed, games, starts and pitch counts per start. Sprint speed comes from the Savant leaderboard (builder
A's cache, read through builder C's loader) when present.

Components and stabilisation (k, in the component's own denominator)
---------------------------------------------------------------------
    hitters   K/PA 60, BB/PA 120, HBP/PA 240, GB/BIP 70, xwOBAcon 50 BIP, HR/BIP 300 BIP (walk-forward 2016-2026),
              hits/(BIP-HR) 820, XBH/(BIP-HR) 600, 3B/XBH 100, bat speed 50 swings
    pitchers  K/BF 70, BB/BF 170, HBP/BF 640, GB/BIP 70, xwOBAcon 300 BIP, HR/BIP 1000,
              hits/(BIP-HR) 2000, XBH/(BIP-HR) 1000, 3B/XBH 300
Builder C's `stabilise.py` values replace these when it exports them (`stabilise.K` or `POINTS`).

Estimator for one component with recent seasons i (most recent first), counts x_i out of n_i:

    weighted  X = sum_i w_i x_i,   N = sum_i w_i n_i      (hitters w = 1, .8, .6; pitchers 1, .67, .33 - Marcel 5/4/3, 3/2/1)
    talent    r = (X + k m) / (N + k)                     (m = the shrinkage target)
    next      logit r' = logit r + aging(age)             (rate components; linear ones add the delta)
    range     sd^2 = r(1-r)/(N + k) + r(1-r)/n_proj        (talent + binomial noise over the projected n)
              p10 / p90 = r' -/+ 1.2816 sd

The league environment: the projection's own (the same seasons, weights and level as the players' counts; a
rest-of-season projection's target season contributes only its counts to date); attrs["env_game"] is the
season's environment for the game model (`game_env`). The shrinkage target m is its league rate (position players';
pitchers batting are shrunk to the pitchers' batting rates; pitchers' targets move by role, starters against
relievers, `role_offsets`), except for slow components whose target comes from fast ones (a weighted
least-squares fit of the empirical logit across player seasons, centred so its sample-weighted mean is the
league rate):
    hitter HR/BIP  ~ xwOBAcon, GB/BIP (+ bat speed)     hitter hits/(BIP-HR) ~ xwOBAcon, GB/BIP (+ sprint speed)
    hitter XBH     ~ xwOBAcon                           pitcher K/BF ~ stuff (builder B, else fastball velocity)
    pitcher HR/BIP ~ xwOBAcon, GB/BIP                   pitcher hits/(BIP-HR) ~ GB/BIP
The HR/BIP priors enter at weight 0.4 (PRIOR_WEIGHT: the prior is fitted on the same batted balls as the rate).
The game model moves each projection from its event mix (attrs["env"]) into attrs["env_game"].

Aging (delta method): for players seen in consecutive seasons (both with n >= 100), the change in each
component (logit for rates) weighted by the harmonic mean of the two samples, averaged by age, then a
weighted quadratic in age is fitted (ages 19-41). Used for next-season projections only; rest-of-season
projections use no aging; hitters' HR/BIP and pitchers' HR/BIP and walks are not aged (NO_AGING).

Triple-A translations: for players with both AAA and MLB samples in the same season (n >= 50 each), the
mean logit (or linear) difference MLB - AAA per component, weighted by the harmonic mean sample. AAA counts
enter a projection translated to MLB-equivalent rates and with weight 0.6. Defaults apply without data.

Event rates for the game model: K, BB, HBP from the components; balls in play split into HR, then
hits (1B / 2B / 3B via XBH and 3B shares) and outs (GO / AO by the ground-ball share of outs, which
follows GB/BIP); platoon rates by opposing hand are the overall rates times the individual's observed
split ratio shrunk to the league platoon ratio with k = 600 PA (BF) per hand.

Evaluation: for each season Y with history, our projection from seasons < Y against the season's actual
rates (players with >= 200 PA / BF), weighted RMSE, against a Marcel-like baseline (5/4/3 or 3/2/1
weights, 1200 PA of league average, no components, Marcel's wOBA age factor).
"""
from __future__ import annotations

import logging
import math
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio
from oddsmarkets.baseball.models._dio import E, EVENTS, NE
from oddsmarkets.baseball.models import _io as _pio

logger = logging.getLogger(__name__)

VERSION = 1
W_HIT = (1.0, 0.8, 0.6)
W_PIT = (1.0, 0.67, 0.33)
AAA_WEIGHT = 0.6
PLATOON_K = 600.0
WOBA_DEFAULT = {"BB": 0.69, "HBP": 0.72, "1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03}

STAB = {
    "hitter": {"K": 60, "BB": 120, "HBP": 240, "GB": 70, "XWCON": 50, "HRBIP": 300, "HITS": 820, "XBH": 600, "TRIP": 100,
               "BATSPD": 50},
    "pitcher": {"K": 70, "BB": 170, "HBP": 640, "GB": 70, "XWCON": 300, "HRBIP": 1000, "HITS": 2000, "XBH": 1000,
                "TRIP": 300},
}
# component: (numerator, denominator, kind)
COMPONENTS = {
    "K": ("K", "PA", "rate"), "BB": ("BB", "PA", "rate"), "HBP": ("HBP", "PA", "rate"),
    "GB": ("GBALL", "BIP", "rate"), "XWCON": ("XW_SUM", "XW_N", "linear"), "HRBIP": ("HR", "BIP", "rate"),
    "HITS": ("NHHITS", "NHBIP", "rate"), "XBH": ("XBH", "NHBIP", "rate"), "TRIP": ("3B", "XBH", "rate"),
    "BATSPD": ("BS_SUM", "BS_N", "linear"),
}
LINEAR_SD = {"XWCON": 0.42, "BATSPD": 4.0}
# default aging (logit / linear deltas per year as a quadratic a + b (age-27) + c (age-27)^2)
AGING_DEFAULT = {
    "hitter": {"K": (0.02, 0.006, 0.0), "BB": (0.02, -0.002, 0.0), "HBP": (0.0, 0.0, 0.0), "GB": (0.0, 0.003, 0.0),
               "XWCON": (-0.002, -0.0012, -0.00008), "HRBIP": (-0.01, -0.012, -0.0006), "HITS": (-0.01, -0.004, 0.0),
               "XBH": (-0.01, -0.006, 0.0), "TRIP": (-0.05, -0.01, 0.0), "BATSPD": (-0.1, -0.08, -0.004)},
    "pitcher": {"K": (-0.01, -0.006, -0.0005), "BB": (0.0, -0.003, 0.0004), "HBP": (0.0, 0.0, 0.0), "GB": (0.0, 0.0, 0.0),
                "XWCON": (0.001, 0.0005, 0.0), "HRBIP": (0.01, 0.003, 0.0), "HITS": (0.0, 0.0, 0.0), "XBH": (0.0, 0.0, 0.0),
                "TRIP": (0.0, 0.0, 0.0)},
}
# default AAA -> MLB (logit / linear) translations
TRANSLATE_DEFAULT = {
    "hitter": {"K": 0.22, "BB": -0.18, "HBP": -0.05, "GB": 0.02, "XWCON": -0.030, "HRBIP": -0.25, "HITS": -0.08,
               "XBH": -0.10, "TRIP": -0.1, "BATSPD": 0.0},
    "pitcher": {"K": -0.22, "BB": 0.15, "HBP": 0.05, "GB": -0.02, "XWCON": 0.030, "HRBIP": 0.25, "HITS": 0.08,
                "XBH": 0.10, "TRIP": 0.1},
}
PRIOR_MODELS = {
    "hitter": {"HRBIP": ["XWCON", "GB", "BATSPD"], "HITS": ["XWCON", "GB", "SPRINT"], "XBH": ["XWCON", "SPRINT"]},
    "pitcher": {"K": ["STUFF"], "HRBIP": ["XWCON", "GB"], "HITS": ["GB"]},
}
# How far the prior model moves a component's target from the league rate (1 = the fitted prediction). The prior
# is fitted on the same batted balls as the rate it shrinks (a barrel lifts both xwOBAcon and HR/BIP), so taken at
# full strength it counts that evidence twice: hitters' HR/BIP projections trailed the Marcel baseline by 12.5%.
# The weight that best combines the two, estimated walk-forward (each season from the earlier ones) on 2017-2026
# with k = 300, is 0.33-0.49 (0.39 pooled); 0.4 is used, for pitchers too (their HR/BIP prior from contact
# quality and ground balls has the same double count).
PRIOR_WEIGHT = {"hitter": {"HRBIP": 0.4}, "pitcher": {"HRBIP": 0.4}}
# Components with no next-season aging. The delta method's curves come from players who survived into the next
# season, and on 2016-2026 (walk-forward against Marcel, which ages neither) the HR/BIP curve cost hitters about
# 1% and pitchers' HR/BIP projections carried a +0.004 bias (pooled -1.0% against Marcel with it, +4.1% without);
# the pitchers' walk curve likewise (-1.6% with it, +0.3% without).
NO_AGING = {"hitter": {"HRBIP"}, "pitcher": {"HRBIP", "BB"}}


STAB_C = {"hitter": {"K": "k_rate", "BB": "bb_rate", "HBP": "hbp_rate"},
          "pitcher": {"K": "p_k_rate", "BB": "p_bb_rate", "HBP": "p_hbp_rate"}}


def stab(role: str, level: str = "mlb") -> dict:
    """Regression constants k: builder C's fitted split-half values (stabilise.shrink_k) where its committed fit
    has the metric, else ours (STAB)."""
    out = dict(STAB[role])
    mod = _dio.sibling("stabilise")
    if mod is not None:
        try:
            fitted = mod._fitted(level) or {}
        except Exception:  # noqa: BLE001
            fitted = {}
        for comp, metric in STAB_C[role].items():
            m = fitted.get(metric)
            if isinstance(m, dict) and isinstance(m.get("k"), (int, float)) and m["k"] > 0:
                out[comp] = float(m["k"])
    return out


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-5, 1 - 1e-5)
    return np.log(p / (1 - p))


def _sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


# ── season PA tables and aggregates ─────────────────────────────────────────

def _cache(name: str):
    return _dio.cache_root() / "proj" / name


def pa_table(level: str, season: int, use_cache: bool = True) -> pd.DataFrame:
    """Plate appearances of one season (built month by month; cached Parquet keyed on the pitch file's mtime)."""
    src = _dio.pitch_path(level, season)
    if not src.exists():
        return pd.DataFrame()
    stamp = _pio.stamp(src)
    p = _cache(f"pa_{level}_{season}_{stamp}.parquet")
    if use_cache and p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:  # noqa: BLE001
            pass
    parts = []
    for _, df in _dio.iter_months(level, season):
        if len(df):
            parts.append(_dio.plate_appearances(df))
        del df
    pa = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(pa):
        pa = pa.drop(columns=["umpire"], errors="ignore")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            for old in p.parent.glob(f"pa_{level}_{season}_*.parquet"):
                old.unlink(missing_ok=True)
            pa.to_parquet(p, index=False)
        except Exception as exc:  # noqa: BLE001
            logger.info("cache write failed: %s", exc)
    return pa


def _counts(pa: pd.DataFrame, who: str, hand_col: str, self_col: str) -> pd.DataFrame:
    ev = pa["ev"].to_numpy()
    d = pd.DataFrame({"pid": pa[who].to_numpy(), "hand": pa[hand_col].to_numpy()})
    d["SELF_L"] = (pa[self_col].astype(str).to_numpy() == "L").astype(np.int32)
    for e, i in E.items():
        d[e] = (ev == i).astype(np.int32)
    bip = np.isin(ev, [E["1B"], E["2B"], E["3B"], E["HR"], E["GO"], E["AO"]])
    d["PA"] = 1
    d["BIP"] = bip.astype(np.int32)
    xw = pa["xwoba"].to_numpy(dtype=float)
    okx = bip & np.isfinite(xw)
    d["XW_SUM"] = np.where(okx, xw, 0.0)
    d["XW_N"] = okx.astype(np.int32)
    la = pa["launch_angle"].to_numpy(dtype=float)
    gball = bip & (ev != E["HR"]) & ((ev == E["GO"]) | (np.isfinite(la) & (la < 10)))
    d["GBALL"] = gball.astype(np.int32)
    bs = pa["bat_speed"].to_numpy(dtype=float)
    okb = np.isfinite(bs) & (bs > 40)
    d["BS_SUM"] = np.where(okb, bs, 0.0)
    d["BS_N"] = okb.astype(np.int32)
    d["WOBA_SUM"] = pa["woba_value"].fillna(0).to_numpy(dtype=float)
    d["WOBA_DEN"] = pa["woba_denom"].fillna(0).to_numpy(dtype=float)
    cols = list(E) + ["PA", "BIP", "XW_SUM", "XW_N", "GBALL", "BS_SUM", "BS_N", "WOBA_SUM", "WOBA_DEN", "SELF_L"]
    tot = d.groupby("pid")[cols].sum()
    by = d.groupby(["pid", "hand"])[list(E) + ["PA"]].sum().unstack("hand", fill_value=0)
    for h in ("L", "R"):
        for c in list(E) + ["PA"]:
            tot[f"{c}_{h}"] = by[(c, h)] if (c, h) in by.columns else 0
    return tot.fillna(0)


def _starts(pa: pd.DataFrame) -> pd.DataFrame:
    """Per pitcher: games, starts, pitches per start (mean / sd over the season), pitches per BF."""
    g = pa.groupby(["game_pk", "top", "pitcher"], sort=False).agg(pitches=("pitches", "sum"), bf=("ev", "size"),
                                                                    first_ab=("ab", "min")).reset_index()
    first = g.loc[g.groupby(["game_pk", "top"])["first_ab"].idxmin()]
    first = first.assign(start=1)[["game_pk", "top", "pitcher", "start"]]
    g = g.merge(first, on=["game_pk", "top", "pitcher"], how="left").fillna({"start": 0})
    agg = g.groupby("pitcher").agg(G=("game_pk", "size"), GS=("start", "sum"), PITCHES=("pitches", "sum"),
                                   BF_ALL=("bf", "sum"))
    st = g[g["start"] == 1].groupby("pitcher")["pitches"].agg(["mean", "std", "size"])
    agg["PC_MEAN"] = st["mean"]
    agg["PC_SD"] = st["std"]
    agg.index.name = "pid"
    return agg


def season_aggregates(level: str, season: int, use_cache: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(hitters, pitchers) count tables for one season (index pid)."""
    src = _dio.pitch_path(level, season)
    if not src.exists():
        return pd.DataFrame(), pd.DataFrame()
    stamp = _pio.stamp(src)
    ph, pp = _cache(f"agg_h_{level}_{season}_{stamp}.parquet"), _cache(f"agg_p_{level}_{season}_{stamp}.parquet")
    if use_cache and ph.exists() and pp.exists():
        try:
            return pd.read_parquet(ph), pd.read_parquet(pp)
        except Exception:  # noqa: BLE001
            pass
    pa = pa_table(level, season, use_cache)
    if not len(pa):
        return pd.DataFrame(), pd.DataFrame()
    pa = pa[pa["game_type"].isin(["R"])] if (pa["game_type"] == "R").any() else pa
    h, p = aggregates_from_pa(pa)
    try:
        for f in ph.parent.glob(f"agg_*_{level}_{season}_*.parquet"):
            f.unlink(missing_ok=True)
        ph.parent.mkdir(parents=True, exist_ok=True)
        h.to_parquet(ph)
        p.to_parquet(pp)
    except Exception as exc:  # noqa: BLE001
        logger.info("cache write failed: %s", exc)
    return h, p


def aggregates_from_pa(pa: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    h = _counts(pa, "batter", "p_throws", "stand")
    p = _counts(pa, "pitcher", "stand", "p_throws")
    p = p.join(_starts(pa), how="left")
    # velocity proxy for stuff when builder B's model is absent: filled by the caller if available
    for t in (h, p):
        t["NHBIP"] = t["BIP"] - t["HR"]
        t["NHHITS"] = t["1B"] + t["2B"] + t["3B"]
        t["XBH"] = t["2B"] + t["3B"]
    h["GP"] = pa.groupby("batter")["game_pk"].nunique()
    return h, p


def league_table(h: pd.DataFrame) -> np.ndarray:
    """Overall PA outcome rates from a hitter aggregate table."""
    if h is None or not len(h):
        from oddsmarkets.baseball.models.game_sim import LEAGUE_DEFAULT
        return LEAGUE_DEFAULT.copy()
    v = np.array([h[e].sum() for e in EVENTS], float)
    return v / v.sum()


def league_split_from(h: pd.DataFrame) -> dict[str, np.ndarray]:
    """League rates by (batter hand, pitcher hand) from hitter counts by pitcher hand + batter handedness map."""
    from oddsmarkets.baseball.models.game_sim import league_split
    return league_split(league_table(h))


def woba_weights(season: int) -> dict:
    mod = _dio.sibling("re24")
    for fn in ("woba_weights", "linear_weights"):
        f = getattr(mod, fn, None) if mod else None
        if f:
            try:
                w = f(season)
                if isinstance(w, dict) and all(k in w for k in ("BB", "1B", "HR")):
                    return {k: float(w[k]) for k in WOBA_DEFAULT if k in w} | {k: v for k, v in WOBA_DEFAULT.items() if k not in w}
                if isinstance(w, dict) and "single" in w:
                    m = {"BB": "walk", "HBP": "hbp", "1B": "single", "2B": "double", "3B": "triple", "HR": "home_run"}
                    return {k: float(w.get(v, WOBA_DEFAULT[k])) for k, v in m.items()}
            except Exception:  # noqa: BLE001
                pass
    return dict(WOBA_DEFAULT)


_WSAV: dict = {}


def woba_scale_savant(level: str, season: int) -> tuple[np.ndarray, np.ndarray] | None:
    """(value, denominator) per outcome class: the mean Savant woba_value / woba_denom of each class in the
    season's plate appearances, so a projected wOBA = sum r_e v_e / sum r_e d_e sits on Savant's scale
    (intentional walks carry no denominator; errors are outs). None without data."""
    key = (level, season)
    if key in _WSAV:
        return _WSAV[key]
    pa = pa_table(level, season)
    res = None
    if len(pa):
        g = pa.groupby("ev").agg(v=("woba_value", "mean"), d=("woba_denom", "mean")).reindex(range(NE))
        if g["v"].notna().all():
            res = (g["v"].fillna(0).to_numpy(float), g["d"].fillna(1).to_numpy(float))
    _WSAV[key] = res
    return res


def sprint_speed(season: int) -> pd.Series:
    """pid -> sprint speed (ft/s) from the Savant leaderboard when cached, else empty."""
    try:
        from oddsmarkets.baseball.models import _c
        df = _c.leaderboard("sprint_speed", season)
    except Exception:  # noqa: BLE001
        df = None
    if df is None or not len(df):
        return pd.Series(dtype=float)
    idc = next((c for c in ("player_id", "pid", "batter", "mlbam_id") if c in df.columns), None)
    vc = next((c for c in ("sprint_speed", "hp_to_1b_sprint_speed") if c in df.columns), None)
    if not idc or not vc:
        return pd.Series(dtype=float)
    return pd.Series(pd.to_numeric(df[vc], errors="coerce").to_numpy(), index=df[idc].astype(str)).dropna()


def stuff_scores(level: str, season: int) -> pd.Series:
    """pid -> builder B's pitcher stuff (100 = average) when available; empty otherwise."""
    for name in ("pitching", "stuff"):
        mod = _dio.sibling(name)
        if not mod:
            continue
        for fn in ("pitcher_scores", "pitcher_table", "for_season"):
            f = getattr(mod, fn, None)
            if not f:
                continue
            try:
                res = f(level, season)
            except Exception:  # noqa: BLE001
                continue
            df = None
            if isinstance(res, pd.DataFrame):
                df = res
            elif isinstance(res, dict):
                for key in ("pitchers", "pitcher", "rows"):
                    if isinstance(res.get(key), (list, dict)):
                        v = res[key]
                        df = pd.DataFrame(v if isinstance(v, list) else [dict(pid=k, **x) for k, x in v.items()
                                                                       if isinstance(x, dict)])
                        break
            if df is None or not len(df):
                continue
            idc = next((c for c in ("pid", "pitcher", "player_id") if c in df.columns), None)
            vc = next((c for c in ("stuff_plus", "stuff", "stuff100", "pitching_plus") if c in df.columns), None)
            if idc and vc:
                s = pd.Series(pd.to_numeric(df[vc], errors="coerce").to_numpy(), index=df[idc].astype(str)).dropna()
                if len(s):
                    return s
    return pd.Series(dtype=float)


def velocity(level: str, season: int) -> pd.Series:
    """pid -> mean fastball velocity (FF/SI) from the pitch table (stuff fallback)."""
    p = _cache(f"velo_{level}_{season}.parquet")
    src = _dio.pitch_path(level, season)
    if not src.exists():
        return pd.Series(dtype=float)
    if p.exists() and p.stat().st_mtime >= src.stat().st_mtime:
        try:
            return pd.read_parquet(p)["velo"]
        except Exception:  # noqa: BLE001
            pass
    try:
        df = _dio.read_pitches(level, season, ["pitcher", "pitch_type", "release_speed"])
        df = df[df["pitch_type"].astype(str).isin(["FF", "SI", "FA"])]
        s = df.groupby(df["pitcher"].astype("Int64").astype(str))["release_speed"].mean().astype(float)
        p.parent.mkdir(parents=True, exist_ok=True)
        s.rename("velo").to_frame().to_parquet(p)
        return s
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)


# ── ages ─────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=2)
def _births(level: str = "mlb") -> dict:
    out = {}
    for pid, v in (_dio.people() or {}).items():
        b = (v or {}).get("birth") or (v or {}).get("dob")
        if b:
            out[str(pid)] = str(b)[:10]
    for s in _dio.store_seasons(level)[-4:]:
        for pid, v in (_dio.load_store(level, s).get("players") or {}).items():
            if (v or {}).get("dob"):
                out[str(pid)] = str(v["dob"])[:10]
    return out


def age_on(pid: str, season: int, births: dict | None = None) -> float | None:
    """Age on 1 July of the season."""
    b = (births if births is not None else _births()).get(str(pid))
    if not b:
        return None
    try:
        y, m, d = (int(x) for x in b.split("-")[:3])
    except ValueError:
        return None
    return season - y + ((7 - m) * 30.4 + (1 - d)) / 365.25


# ── aging and translations ──────────────────────────────────────────────────

def _rate(df: pd.DataFrame, comp: str) -> tuple[np.ndarray, np.ndarray]:
    num, den, _ = COMPONENTS[comp]
    if num not in df.columns or den not in df.columns:
        return np.full(len(df), np.nan), np.zeros(len(df))
    n = df[den].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = df[num].to_numpy(dtype=float) / n
    return r, n


def _transform(comp: str, r):
    return _logit(r) if COMPONENTS[comp][2] == "rate" else np.asarray(r, float)


def _inverse(comp: str, x):
    return _sig(x) if COMPONENTS[comp][2] == "rate" else np.asarray(x, float)


def fit_aging(level: str, seasons: Iterable[int], role: str, births: dict | None = None, min_n: float = 100) -> dict:
    """{comp: (a, b, c)} quadratic delta per year in age-27 (delta method); defaults where data are thin."""
    births = births if births is not None else _births(level)
    seasons = sorted(seasons)
    rows = {c: [] for c in STAB[role]}
    prev = None
    for s in seasons:
        h, p = season_aggregates(level, s)
        cur = h if role == "hitter" else p
        if prev is not None and len(cur) and prev[0] == s - 1:
            a, b = prev[1], cur
            common = a.index.intersection(b.index)
            if len(common):
                A, B = a.loc[common], b.loc[common]
                ages = np.array([age_on(pid, s - 1, births) or np.nan for pid in common])
                for c in rows:
                    ra, na = _rate(A, c)
                    rb, nb = _rate(B, c)
                    ok = (na >= min_n * (0.3 if c in ("TRIP",) else 1)) & (nb >= min_n * (0.3 if c in ("TRIP",) else 1)) & \
                        np.isfinite(ra) & np.isfinite(rb) & np.isfinite(ages)
                    if c in ("XWCON", "BATSPD"):
                        ok &= (na >= 50) & (nb >= 50)
                    if ok.any():
                        d = _transform(c, rb[ok]) - _transform(c, ra[ok])
                        w = 2 * na[ok] * nb[ok] / (na[ok] + nb[ok])
                        rows[c].append(np.c_[ages[ok], d, w])
        prev = (s, cur) if len(cur) else None
    out = {}
    for c, parts in rows.items():
        dflt = AGING_DEFAULT[role].get(c, (0, 0, 0))
        if not parts:
            out[c] = {"coef": dflt, "n": 0, "source": "default"}
            continue
        X = np.vstack(parts)
        X = X[(X[:, 0] >= 19) & (X[:, 0] <= 41)]
        if len(X) < 60:
            out[c] = {"coef": dflt, "n": int(len(X)), "source": "default"}
            continue
        z = X[:, 0] - 27
        A = np.c_[np.ones_like(z), z, z ** 2]
        w = X[:, 2]
        # ridge towards the default curve (n-weighted) to keep sparse ages sane
        lam = np.diag([50.0, 500.0, 5000.0]) * w.mean()
        coef = np.linalg.solve(A.T @ (A * w[:, None]) + lam, A.T @ (w * X[:, 1]) + lam @ np.array(dflt))
        out[c] = {"coef": tuple(float(x) for x in coef), "n": int(len(X)), "source": "fitted"}
    return out


def aging_delta(aging: dict, comp: str, age: float | None) -> float:
    if age is None or not np.isfinite(age):
        return 0.0
    a, b, c = (aging.get(comp) or {}).get("coef", (0, 0, 0))
    z = min(max(age, 19.0), 41.0) - 27.0
    return float(a + b * z + c * z * z)


def fit_translation(seasons: Iterable[int], role: str, min_n: float = 50) -> dict:
    """AAA -> MLB deltas per component from players with both samples in a season."""
    acc = {c: [] for c in STAB[role]}
    for s in seasons:
        mh, mp = season_aggregates("mlb", s)
        ah, ap = season_aggregates("aaa", s)
        M, A = (mh, ah) if role == "hitter" else (mp, ap)
        if not len(M) or not len(A):
            continue
        common = M.index.intersection(A.index)
        for c in acc:
            rm, nm = _rate(M.loc[common], c)
            ra, na = _rate(A.loc[common], c)
            ok = (nm >= min_n) & (na >= min_n) & np.isfinite(rm) & np.isfinite(ra)
            if ok.any():
                d = _transform(c, rm[ok]) - _transform(c, ra[ok])
                w = 2 * nm[ok] * na[ok] / (nm[ok] + na[ok])
                acc[c].append(np.c_[d, w])
    out = {}
    for c, parts in acc.items():
        dflt = TRANSLATE_DEFAULT[role].get(c, 0.0)
        if not parts:
            out[c] = {"delta": dflt, "n": 0, "source": "default"}
            continue
        X = np.vstack(parts)
        if len(X) < 25:
            out[c] = {"delta": dflt, "n": int(len(X)), "source": "default"}
            continue
        # n-weighted mean, shrunk to the default with 25 players' weight
        w = X[:, 1]
        k = 25 * w.mean()
        d = float((np.sum(w * X[:, 0]) + k * dflt) / (w.sum() + k))
        out[c] = {"delta": d, "n": int(len(X)), "source": "fitted"}
    return out


# ── projection ───────────────────────────────────────────────────────────────

COUNT_COLS = list(E) + ["PA", "BIP", "XW_SUM", "XW_N", "GBALL", "BS_SUM", "BS_N", "NHBIP", "NHHITS", "XBH", "WOBA_SUM",
                        "WOBA_DEN", "SELF_L"] + [f"{e}_{h}" for e in list(E) + ["PA"] for h in ("L", "R")]


def _translate_counts(df: pd.DataFrame, role: str, trans: dict) -> pd.DataFrame:
    """AAA counts -> MLB-equivalent counts (rates moved by the translation, denominators kept)."""
    out = df.copy()
    for c, (num, den, kind) in COMPONENTS.items():
        if c not in trans or num not in out.columns or den not in out.columns:
            continue
        n = out[den].to_numpy(dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = out[num].to_numpy(dtype=float) / n
        ok = n > 0
        r2 = np.where(ok, _inverse(c, _transform(c, np.where(ok, r, 0.5)) + trans[c]["delta"]), 0.0)
        out[num] = np.where(ok, r2 * n, 0.0)
    for e in EVENTS:              # keep hand splits proportional to the translated totals
        for h in ("L", "R"):
            col = f"{e}_{h}"
            if col in out.columns and e in df.columns:
                with np.errstate(invalid="ignore", divide="ignore"):
                    f = np.where(df[e] > 0, out[e] / df[e], 1.0)
                out[col] = df[col] * f
    return out


ENV_K = 5000.0          # plate appearances: the shrinkage of the season-to-date ratio in `game_env`


def game_env(level: str, target: int, kind: str = "ros", part: dict[int, pd.DataFrame] | None = None,
             k: float = ENV_K, dates: tuple[str, str] | None = None) -> np.ndarray | None:
    """
    The league event mix for the games of season `target`. The previous full season's mix, each outcome's rate
    multiplied by (this season's rate to date / the previous season's rate over the same calendar days) ^
    (n / (n + k)), n the plate appearances to date: comparing the same stretch of the calendar cancels the cold
    April, and the ratio moves the level within weeks of a change in the ball or the rules. `dates` (first, last
    day of the counts to date) give the calendar window; without them the previous season's first n plate
    appearances stand in; when the previous season has under half as many plate appearances in the window (the
    2020 season began on 23 July) the previous season's mix is used unchanged.
    Judged on a linear-weights proxy over 2016-2026, the error in each season's rest-of-season run level fell
    from 0.17 (the previous season plus the season to date, pooled) to 0.05 runs per 38 PA with k = 3,000-5,000.
    Next-season projections and seasons with no counts to date: the previous full season (or the season itself
    once it is complete and no partial counts are given).
    """
    def mix(c):
        v = np.array([float(c.get(e, 0.0)) for e in EVENTS])
        return v / v.sum() if v.sum() > 0 else None
    if kind != "next" and not (part and target in part) and _dio.pitch_path(level, target).exists():
        return mix(season_env(level, target))
    prev = season_env(level, target - 1)
    base = mix(prev) if len(prev) else None
    if base is None or kind == "next" or not (part and target in part):
        return base
    to = part[target]
    if to is None or not len(to):
        return base
    tv = np.array([float(to[e].sum()) for e in EVENTS])
    n = tv.sum()
    if n <= 0:
        return base
    days = league_days(level, target - 1)
    if not days:
        return base
    keys = sorted(days)
    if dates is not None and dates[0] and dates[1]:
        lo, hi = str(dates[0])[5:10], str(dates[1])[5:10]
        ps = np.sum([days[k] for k in keys if lo <= k <= hi] or [np.zeros(NE)], axis=0).astype(float)
    else:
        ps, acc = np.zeros(NE), 0.0
        for day in keys:                     # the previous season's first n plate appearances, whole days
            if acc >= n:                     # (`day`, not `k`: k is the shrinkage constant)
                break
            ps = ps + np.asarray(days[day], float)
            acc = ps.sum()
    if ps.sum() < 0.5 * n:
        return base
    f = ((tv / n) / np.maximum(ps / ps.sum(), 1e-9)) ** (n / (n + k))
    v = base * np.where(np.isfinite(f) & (f > 0), f, 1.0)
    return v / v.sum()


_DAYS: dict = {}


def league_days(level: str, season: int) -> dict[str, np.ndarray]:
    """{"MM-DD": event counts} of a season's regular-season plate appearances: from the PA table, else the committed
    models/fitted/league_days_<level>.json (CI holds only the current season's pitch table)."""
    key = (level, season)
    if key in _DAYS:
        return _DAYS[key]
    out: dict[str, np.ndarray] = {}
    pa = pa_table(level, season)
    if len(pa):
        pa = pa[pa["game_type"] == "R"] if (pa["game_type"] == "R").any() else pa
        g = pd.DataFrame({"d": pa["game_date"].astype(str).str[5:10].to_numpy(), "ev": pa["ev"].to_numpy()})
        g = g[g["ev"] >= 0]
        tab = pd.crosstab(g["d"], g["ev"]).reindex(columns=range(NE), fill_value=0)
        out = {str(d): row.to_numpy(float) for d, row in tab.iterrows()}
    else:
        p = _dio.fitted_dir() / f"league_days_{level}.json"
        if p.exists():
            try:
                import json
                out = {k: np.asarray(v, float) for k, v in (json.loads(p.read_text()).get(str(season)) or {}).items()}
            except Exception:  # noqa: BLE001
                out = {}
    _DAYS[key] = out
    return out


def export_league_days(level: str, seasons: list[int]) -> dict:
    """Write models/fitted/league_days_<level>.json for `seasons` (game_env's calendar comparison in CI)."""
    import json
    res = {str(s): {k: [int(x) for x in v] for k, v in league_days(level, s).items()} for s in seasons}
    res = {s: v for s, v in res.items() if v}
    p = _dio.fitted_dir() / f"league_days_{level}.json"
    p.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
    return {"ok": bool(res), "path": str(p), "seasons": sorted(res)}


def season_env(level: str, s: int, partial: dict[int, pd.DataFrame] | None = None) -> pd.Series:
    """League count totals of one season (every plate appearance; the counts to date when `partial` has it)."""
    if partial and s in partial:
        f = partial[s]
    else:
        f, _ = season_aggregates(level, s)
    if f is None or not len(f):
        return pd.Series(dtype=float)
    return f[[c for c in COUNT_COLS if c in f.columns]].astype(float).sum()


def _stack(level: str, seasons: list[int], role: str, weights: tuple, trans: dict | None,
           partial: dict[int, pd.DataFrame] | None = None) -> tuple[pd.DataFrame, dict]:
    """Weighted count totals over recent seasons (MLB + translated AAA). Returns (totals, per-season raw)."""
    tot = None
    raw = {}
    for i, s in enumerate(seasons):
        w = weights[i] if i < len(weights) else 0.0
        if w <= 0:
            continue
        frames = []
        if partial and s in partial:
            frames.append((partial[s], 1.0))
        else:
            h, p = season_aggregates(level, s)
            cur = h if role == "hitter" else p
            if len(cur):
                frames.append((cur, 1.0))
                raw[s] = cur
            if level == "mlb" and trans is not None:
                ah, ap = season_aggregates("aaa", s)
                acur = ah if role == "hitter" else ap
                if len(acur):
                    frames.append((_translate_counts(acur, role, trans), AAA_WEIGHT))
        for f, fw in frames:
            cols = [c for c in COUNT_COLS if c in f.columns]
            part = f[cols].astype(float) * (w * fw)
            tot = part if tot is None else tot.add(part, fill_value=0.0)
    return (tot if tot is not None else pd.DataFrame(columns=COUNT_COLS)), raw


def _wls(X: np.ndarray, y: np.ndarray, w: np.ndarray, ridge: float = 1.0) -> np.ndarray:
    A = np.c_[np.ones(len(X)), X]
    lam = np.eye(A.shape[1]) * ridge
    lam[0, 0] = 0
    return np.linalg.solve(A.T @ (A * w[:, None]) + lam, A.T @ (w * y))


def project_from_totals(tot: pd.DataFrame, role: str, league: dict, extras: dict[str, pd.Series] | None = None,
                        aging: dict | None = None, ages: dict | None = None, n_proj: float | None = None,
                        k: dict | None = None, targets: dict[str, np.ndarray] | None = None,
                        offsets: dict[str, np.ndarray] | None = None) -> pd.DataFrame:
    """
    Component projections from weighted totals. league: {comp: league rate}. extras: {"SPRINT", "STUFF"} series.
    targets: {comp: per-player shrinkage target, NaN where the league / prior-model target applies} (pitchers
    batting are shrunk to the pitchers' batting rates, not the position players'). offsets: {comp: per-player
    shift of the target on the component's scale (logit for rates)} (pitchers' starter / reliever role).
    Returns one row per player: <comp> (projected talent), <comp>_n (weighted sample), <comp>_p10/_p90,
    rates_L / rates_R (9-vector event rates by opposing hand), PA (weighted sample), age.
    """
    k = k or stab(role)
    out = pd.DataFrame(index=tot.index)
    extras = extras or {}
    reg = {}
    order = ["K", "BB", "HBP", "GB", "XWCON", "BATSPD", "HRBIP", "HITS", "XBH", "TRIP"]
    for c in order:
        if c not in k:
            continue
        num, den, kind = COMPONENTS[c]
        if den not in tot.columns or num not in tot.columns:
            continue
        X = tot[num].to_numpy(dtype=float)
        N = tot[den].to_numpy(dtype=float)
        m = np.full(len(tot), float(league.get(c, np.nan)))
        if not np.isfinite(m).all():
            with np.errstate(invalid="ignore", divide="ignore"):
                lm = X.sum() / N.sum() if N.sum() > 0 else np.nan
            m = np.where(np.isfinite(m), m, lm)
        preds = [p for p in PRIOR_MODELS[role].get(c, [])]
        feats = []
        for pname in preds:
            if pname in reg:
                # a component with no data this window (bat speed before bat tracking, 2023) is all NaN: leave it
                # out rather than turn every player's prior into NaN
                v = np.asarray(reg[pname], float)
                if np.isfinite(v).sum() >= 20:
                    feats.append(np.where(np.isfinite(v), v, np.nanmean(v)))
            elif pname in extras and len(extras[pname]):
                v = extras[pname].reindex(tot.index).to_numpy(dtype=float)
                if np.isfinite(v).sum() >= 20:
                    feats.append(np.where(np.isfinite(v), v, np.nanmean(v)))
        if feats and N.sum() > 0:
            F = np.column_stack(feats)
            F = (F - F.mean(0)) / np.where(F.std(0) > 0, F.std(0), 1.0)
            with np.errstate(invalid="ignore", divide="ignore"):
                raw = X / N
            ok = (N >= max(30.0, 0.5 * k[c])) & np.isfinite(raw)
            if ok.sum() >= 30:
                # the empirical logit (x + 0.5) / (n + 1): the logit of a raw rate sends a player with no home runs
                # to logit(1e-4) = -9.2, and those few points steepened the fit (2 October 2026: hitters' HR/BIP
                # trailed the Marcel baseline by 12.5% with the old fit, and matched it with no prior at all)
                y = (_logit((X[ok] + 0.5) / (N[ok] + 1.0)) if kind == "rate" else raw[ok])
                beta = _wls(F[ok], y, N[ok] / (N[ok] + k[c]), ridge=5.0)
                pred = np.c_[np.ones(len(F)), F] @ beta
                pred = PRIOR_WEIGHT.get(role, {}).get(c, 1.0) * pred      # deviations scaled; centred below
                # center the prior so its sample-weighted mean over every player is the league rate (in rate
                # space): the target stays unbiased for the population the league rate describes
                pred = pred + _center_shift(pred, N, float(m[0]), kind,
                                            None if targets is None or c not in targets else np.isfinite(targets[c]))
                m = _inverse(c, pred)
        if offsets is not None and c in offsets:
            off = np.nan_to_num(np.asarray(offsets[c], float))
            m = _inverse(c, _transform(c, m) + off) if kind == "rate" else m + off
        if targets is not None and c in targets:
            ov = np.asarray(targets[c], float)
            m = np.where(np.isfinite(ov), ov, m)
        r = (X + k[c] * m) / (N + k[c])
        reg[c] = _transform(c, r) if kind == "rate" else r
        out[c + "_talent"] = r
        out[c + "_n"] = N
        # next-season aging
        if aging is not None and ages is not None and c not in NO_AGING.get(role, ()):
            d = np.array([aging_delta(aging, c, ages.get(pid)) for pid in tot.index])
            r_next = _inverse(c, _transform(c, r) + d) if kind == "rate" else r + d
        else:
            r_next = r
        out[c] = r_next
        if kind == "rate":
            var_t = r_next * (1 - r_next) / (N + k[c])
            nproj = n_proj if n_proj else None
            var = var_t + (r_next * (1 - r_next) / _proj_den(c, nproj, r_next, out) if nproj else 0)
        else:
            sdl = LINEAR_SD.get(c, 1.0)
            var = sdl ** 2 / (N + k[c]) + ((sdl ** 2 / _proj_den(c, n_proj, None, out)) if n_proj else 0)
        sd = np.sqrt(var)
        out[c + "_p10"] = r_next - 1.2816 * sd
        out[c + "_p90"] = r_next + 1.2816 * sd
    out["PA"] = tot["PA"].to_numpy(dtype=float) if "PA" in tot.columns else 0
    return out


def _center_shift(pred: np.ndarray, N: np.ndarray, target: float, kind: str, skip: np.ndarray | None = None) -> float:
    """The shift d (on the component's scale) with sum N_i T^-1(pred_i + d) / sum N_i = target."""
    use = (N > 0) & np.isfinite(pred)
    if skip is not None:
        use &= ~np.asarray(skip, bool)
    if not use.any() or not np.isfinite(target):
        return 0.0
    p, w = pred[use], N[use] / N[use].sum()
    if kind != "rate":
        return float(target - np.sum(w * p))
    d = float(_logit(target) - np.sum(w * p))
    for _ in range(30):
        s = _sig(p + d)
        f = float(np.sum(w * s)) - target
        g = float(np.sum(w * s * (1 - s)))
        if g <= 0:
            break
        step = f / g
        d -= step
        if abs(step) < 1e-10:
            break
    return d


def _proj_den(c: str, n_proj: float | None, r, out) -> float:
    """Projected denominator for component c given projected PA."""
    if not n_proj:
        return np.inf
    if c in ("K", "BB", "HBP"):
        return n_proj
    bip_share = 0.68
    if c in ("GB", "XWCON", "HRBIP"):
        return n_proj * bip_share
    if c in ("HITS", "XBH"):
        return n_proj * bip_share * 0.95
    if c == "TRIP":
        return max(n_proj * bip_share * 0.95 * 0.075, 1.0)
    if c == "BATSPD":
        return n_proj * 0.75
    return n_proj


def event_rates(row: pd.Series | dict, league_gb_out_ratio: float = 1.0) -> np.ndarray:
    """9-vector of PA outcome rates from projected components."""
    g = lambda c, d: float(row.get(c, d)) if row.get(c) is not None and np.isfinite(row.get(c, np.nan)) else d  # noqa: E731
    k, bb, hbp = g("K", 0.224), g("BB", 0.083), g("HBP", 0.011)
    bip = max(1.0 - k - bb - hbp, 0.2)
    hr = g("HRBIP", 0.046)
    hits = g("HITS", 0.30)
    xbh = g("XBH", 0.067)
    trip = g("TRIP", 0.075)
    gb = g("GB", 0.43)
    single = max(hits - xbh, 0.05)
    outs = max(1.0 - hits, 0.3)
    # ground-ball share of outs follows the ground-ball rate (ground balls become outs more often)
    go_share = min(max(gb * 1.12 * league_gb_out_ratio, 0.15), 0.85)
    v = np.array([k, bb, hbp,
                  bip * (1 - hr) * single,
                  bip * (1 - hr) * xbh * (1 - trip),
                  bip * (1 - hr) * xbh * trip,
                  bip * hr,
                  bip * (1 - hr) * outs * go_share,
                  bip * (1 - hr) * outs * (1 - go_share)])
    v = np.clip(v, 1e-5, None)
    return v / v.sum()


def own_hand(tot_row: pd.Series | dict, role: str) -> str:
    """'L' / 'R' (and 'S' for hitters seen batting from both sides, each >= 15 %)."""
    n = float(tot_row.get("PA", 0.0) or 0.0)
    l = float(tot_row.get("SELF_L", 0.0) or 0.0)
    if n <= 0:
        return "R"
    f = l / n
    if role == "hitter" and 0.15 <= f <= 0.85:
        return "S"
    return "L" if f > 0.5 else "R"


def platoon_rates(rates: np.ndarray, tot_row: pd.Series, league: dict | None, role: str, hand: str | None = None) -> dict:
    """
    {"L": arr, "R": arr} by opposing hand. The target ratio (rate v hand / overall rate) is the league platoon
    ratio for the player's own hand and his mix of opponents; the observed ratio is shrunk to it with
    PLATOON_K PA (BF) per hand.
    """
    from oddsmarkets.baseball.models.game_sim import _bat_hand, league_split
    split = league if isinstance(league, dict) and "LL" in (league or {}) else league_split()
    own = hand or own_hand(tot_row, role)
    base_counts = np.array([float(tot_row.get(e, 0.0)) for e in EVENTS])
    n_all = max(base_counts.sum(), 1.0)
    shares, lrow = {}, {}
    for h in ("L", "R"):
        shares[h] = float(tot_row.get(f"PA_{h}", 0.0)) / n_all if n_all > 1 else (0.3 if h == "L" else 0.7)
        if role == "hitter":
            bh = _bat_hand(own, h)
            lrow[h] = split[bh + h]
        else:
            th = "L" if own == "L" else "R"
            lrow[h] = split[h + th]
    if shares["L"] + shares["R"] <= 0:
        shares = {"L": 0.3, "R": 0.7}
    expected = shares["L"] * lrow["L"] + shares["R"] * lrow["R"]
    overall = base_counts / n_all if base_counts.sum() > 0 else rates
    out = {}
    for h in ("L", "R"):
        target = lrow[h] / np.maximum(expected, 1e-9)
        cnt = np.array([float(tot_row.get(f"{e}_{h}", 0.0)) for e in EVENTS])
        nh = cnt.sum()
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = (cnt + PLATOON_K * overall * target) / (nh + PLATOON_K) / np.maximum(overall, 1e-9)
        ratio = np.where(np.isfinite(ratio) & (overall > 0), ratio, target)
        q = rates * ratio
        out[h] = q / q.sum()
    return out


def league_components(tot_league: pd.DataFrame | None, h_counts: pd.DataFrame) -> dict:
    """League value of every component from a season's hitter counts."""
    t = h_counts.sum(numeric_only=True) if len(h_counts) else pd.Series(dtype=float)
    out = {}
    for c, (num, den, kind) in COMPONENTS.items():
        if num in t and den in t and t[den] > 0:
            out[c] = float(t[num] / t[den])
    return out


def project(level: str, target: int, kind: str = "next", through: Any = None, role: str = "hitter",
            history: int = 3, partial: pd.DataFrame | None = None, n_proj: float | None = None,
            use_aging: bool = True, aging: dict | None = None, trans: dict | None = None,
            births: dict | None = None, extras_season: int | None = None,
            partial_pitchers: pd.DataFrame | None = None, partial_dates: tuple[str, str] | None = None) -> pd.DataFrame:
    """
    Projections for `role` ("hitter" | "pitcher"). `extras_season` picks the season whose sprint speed / stuff
    scores inform the shrinkage targets (default the most recent season with data; the backtest passes the
    previous season so nothing from the future leaks in).
    kind "next": season `target` from seasons target-1 .. target-history (aging applied).
    kind "ros":  rest of season `target` from the season to date (`partial` counts, or the season's own
                 aggregates) plus target-1 .. target-history+1 (no aging).
    """
    w = W_HIT if role == "hitter" else W_PIT
    if kind == "next":
        seasons = [target - i for i in range(1, history + 1)]
        part = None
    else:
        seasons = [target - i for i in range(0, history)]
        # the target season contributes only the counts passed in (never its own full-season file: that would
        # leak the rest of the season into a rest-of-season projection); `partial=None` means "season to date"
        # is the whole file, which only build_context uses after the season
        part = {target: partial} if partial is not None else None
    seasons_avail = [s for s in seasons if _dio.pitch_path(level, s).exists() or (part and s in part)]
    if not seasons_avail:
        return pd.DataFrame()
    if trans is None and level == "mlb":
        trans = {c: v for c, v in fit_translation([s for s in seasons_avail if s >= 2023], role).items()}
    # The projection's own league environment: the same seasons, weights and level as the players' counts (MLB
    # only; a rest-of-season projection's target season contributes only its counts to date). The shrinkage
    # targets are its rates, so a league-average player projects to exactly its event mix (attrs["env"]); the game
    # model moves every projection from it to the season's environment (attrs["env_game"], `game_env`). (Until 2
    # October 2026 the target was "the most recent full season on disk", which in the walk-forward backtest was the
    # whole target season, and the game model's league reference was the season-to-date table: a mismatch that
    # inflated home runs.)
    tot, raw = _stack(level, seasons, role, w, trans if level == "mlb" else None, part)
    if not len(tot):
        return pd.DataFrame()
    env_tot, _ = _stack(level, seasons, role, w, None, part)
    if not len(env_tot):
        env_tot = tot
    pb = pd.Index([])
    if role == "hitter":
        pb = pitcher_batters(level, seasons, part, partial_pitchers, env_tot)
    pos = env_tot.drop(index=pb, errors="ignore")
    league = league_components(None, pos if len(pos) else env_tot)
    go_ratio = gb_out_ratio(env_tot)
    targets = None
    pb_league = None
    if len(pb) and float(env_tot.loc[env_tot.index.intersection(pb), "PA"].sum()) >= 300:
        pb_league = league_components(None, env_tot.loc[env_tot.index.intersection(pb)])
        is_pb = tot.index.isin(pb)
        targets = {c: np.where(is_pb, v, np.nan) for c, v in pb_league.items() if c in COMPONENTS}
    extras = {}
    s0 = extras_season if extras_season is not None else seasons_avail[0]
    if role == "hitter":
        ss = sprint_speed(s0)
        if len(ss):
            extras["SPRINT"] = ss
    else:
        st = stuff_scores(level, s0)
        extras["STUFF"] = st if len(st) else velocity(level, s0)
    births = births if births is not None else _births(level)
    ages = {pid: age_on(pid, target if kind == "next" else target, births) for pid in tot.index}
    if kind == "next" and use_aging:
        if aging is None:
            aging = fit_aging(level, sorted(set(range(min(seasons_avail) - 3, max(seasons_avail) + 1))), role, births)
        ages_prev = {pid: (a - 1 if a is not None else None) for pid, a in ages.items()}
    else:
        aging, ages_prev = None, None
    offsets = None
    if role == "pitcher":
        offsets = role_offsets(level, seasons, part, env_tot, tot.index)
    out = project_from_totals(tot, role, league, extras, aging, ages_prev, n_proj=n_proj, targets=targets,
                              offsets=offsets)
    out["age"] = pd.Series(ages)
    rates = []
    rl, rr = [], []
    for pid, row in out.iterrows():
        r = event_rates(row, go_ratio)
        rates.append(r)
        pr = platoon_rates(r, tot.loc[pid], None, role)
        rl.append(pr["L"])
        rr.append(pr["R"])
    out["rates"] = rates
    out["hand"] = [own_hand(tot.loc[pid], role) for pid in out.index]
    out["rates_L"] = rl
    out["rates_R"] = rr
    sav = next((x for x in (woba_scale_savant(level, s) for s in seasons_avail) if x is not None), None)
    if sav is not None:
        wv, wd = sav
    else:
        ww = woba_weights(target)
        wv = np.array([0, ww["BB"], ww["HBP"], ww["1B"], ww["2B"], ww["3B"], ww["HR"], 0, 0])
        wd = np.ones(NE)
    out["wOBA"] = [float(np.dot(r, wv) / max(np.dot(r, wd), 1e-6)) for r in rates]
    out["ISO"] = [float((r[4] + 2 * r[5] + 3 * r[6]) / max(1 - r[1] - r[2] - 0.006, 0.5)) for r in rates]
    out["BABIP"] = [float((r[3] + r[4] + r[5]) / max(r[3] + r[4] + r[5] + r[7] + r[8], 1e-6)) for r in rates]
    if role == "pitcher":
        for s in seasons_avail:
            _, p = season_aggregates(level, s)
            if len(p) and "PC_MEAN" in p.columns:
                out["pc_mean_last"] = p["PC_MEAN"].reindex(out.index)
                out["gs_last"] = p["GS"].reindex(out.index)
                out["g_last"] = p["G"].reindex(out.index)
                break
    out.index.name = "pid"
    env = np.array([float(env_tot[e].sum()) for e in EVENTS])
    out.attrs["env"] = (env / env.sum()) if env.sum() > 0 else None
    out.attrs["env_game"] = game_env(level, target, kind, part, dates=partial_dates)
    out.attrs["go_ratio"] = go_ratio
    out.attrs["pitcher_batters"] = [str(x) for x in pb]
    out.attrs["pb_rates"] = event_rates(pb_league, go_ratio) if pb_league else None
    return out


def gb_out_ratio(counts: pd.DataFrame) -> float:
    """Calibration of `event_rates`' ground-out share (GB x 1.12 x ratio) so a league-average player reproduces
    the league's ground outs / (ground + air outs)."""
    if counts is None or not len(counts) or not all(c in counts.columns for c in ("GO", "AO", "GBALL", "BIP")):
        return 1.0
    go, ao, gb, bip = (float(counts[c].sum()) for c in ("GO", "AO", "GBALL", "BIP"))
    if go + ao <= 0 or gb <= 0 or bip <= 0:
        return 1.0
    return float(np.clip((go / (go + ao)) / (1.12 * gb / bip), 0.5, 1.5))


def start_share(level: str, seasons: list[int], part: dict | None) -> pd.Series:
    """pid -> games started / games pitched over the projection's seasons (the season to date from `part`)."""
    g = pd.Series(dtype=float)
    gs = pd.Series(dtype=float)
    for s in seasons:
        if part and s in part:
            p = part[s]
        else:
            _, p = season_aggregates(level, s)
        if p is None or not len(p) or "G" not in p.columns or "GS" not in p.columns:
            continue
        g = g.add(p["G"].astype(float).fillna(0.0), fill_value=0.0)
        gs = gs.add(p["GS"].astype(float).fillna(0.0), fill_value=0.0)
    if not len(g):
        return pd.Series(dtype=float)
    return (gs.reindex(g.index).fillna(0.0) / g.where(g > 0)).dropna()


def role_offsets(level: str, seasons: list[int], part: dict | None, env_tot: pd.DataFrame,
                 index: pd.Index) -> dict[str, np.ndarray] | None:
    """
    Pitchers' shrinkage targets by role. Relievers as a group strike out and walk more batters and allow fewer
    home runs per ball in play than starters (2025: BB 9.3% v 7.8%, HR/BIP 4.3% v 4.7%), and they are the
    pitchers with the smallest samples, so shrinking every pitcher to the all-pitcher mean overstated the home
    runs relievers allow. The target moves by share x T(m_SP) + (1 - share) x T(m_RP) - T(m_all), share =
    games started / games (T = logit for rates); pitchers with no games on record keep the overall target.
    """
    sh = start_share(level, seasons, part)
    if not len(sh):
        return None
    ids = env_tot.index.intersection(sh.index)
    sp, rp = ids[sh.reindex(ids) >= 0.5], ids[sh.reindex(ids) < 0.5]
    if not len(sp) or not len(rp) or env_tot.loc[sp, "PA"].sum() < 2000 or env_tot.loc[rp, "PA"].sum() < 2000:
        return None
    m_all = league_components(None, env_tot)
    m_sp = league_components(None, env_tot.loc[sp])
    m_rp = league_components(None, env_tot.loc[rp])
    share = sh.reindex(index).to_numpy(dtype=float)
    out = {}
    for c in ("K", "BB", "HBP", "GB", "XWCON", "HRBIP", "HITS", "XBH", "TRIP"):
        if c not in m_all or c not in m_sp or c not in m_rp:
            continue
        t = lambda v: float(_transform(c, v))  # noqa: E731
        out[c] = np.where(np.isfinite(share), share * t(m_sp[c]) + (1 - share) * t(m_rp[c]) - t(m_all[c]), 0.0)
    return out


def pitcher_batters(level: str, seasons: list[int], part: dict | None, partial_pitchers: pd.DataFrame | None,
                    htot: pd.DataFrame) -> pd.Index:
    """Hitters who are pitchers: batters faced at least twice their plate appearances (and 50+) over the
    projection's seasons (two-way players stay hitters). Before the universal DH (2022) pitchers batted in NL
    parks and hit far below every other batter; shrinking them to the position players' rates overstated them."""
    bf = pd.Series(dtype=float)
    pa = pd.Series(dtype=float)
    for s in seasons:
        if part and s in part:
            if partial_pitchers is not None and len(partial_pitchers):
                bf = bf.add(partial_pitchers["PA"].astype(float), fill_value=0.0)
            pa = pa.add(part[s]["PA"].astype(float), fill_value=0.0) if len(part[s]) else pa
            continue
        h, p = season_aggregates(level, s)
        if len(p):
            bf = bf.add(p["PA"].astype(float), fill_value=0.0)
        if len(h):
            pa = pa.add(h["PA"].astype(float), fill_value=0.0)
    if not len(bf):
        return pd.Index([])
    ids = htot.index.intersection(bf.index)
    pa_ = pa.reindex(ids).fillna(0.0)
    bf_ = bf.reindex(ids).fillna(0.0)
    return ids[(bf_ >= 50) & (bf_ >= 2 * pa_)]


# ── evaluation against a Marcel-like baseline ───────────────────────────────

def marcel(level: str, target: int, role: str, comps=("K", "BB", "HRBIP", "HITS"), births: dict | None = None) -> pd.DataFrame:
    """Marcel-like baseline: 5/4/3 (3/2/1) weights, 1200 PA/BF of league average, no components."""
    w = (5.0, 4.0, 3.0) if role == "hitter" else (3.0, 2.0, 1.0)
    seasons = [target - 1, target - 2, target - 3]
    tot, _ = _stack(level, seasons, role, w, None)
    if not len(tot):
        return pd.DataFrame()
    h, _ = season_aggregates(level, target - 1)
    league = league_components(None, h)
    out = pd.DataFrame(index=tot.index)
    pa = tot["PA"].to_numpy(dtype=float)
    reg_pa = 1200.0
    for c in comps:
        num, den, kind = COMPONENTS[c]
        X, N = tot[num].to_numpy(dtype=float), tot[den].to_numpy(dtype=float)
        frac = np.where(pa > 0, N / np.maximum(pa, 1), 0.68)
        kk = reg_pa * (np.nanmedian(frac) if c not in ("K", "BB", "HBP") else 1.0)
        out[c] = (X + kk * league.get(c, 0)) / (N + kk)
    ww = woba_weights(target)
    num = tot["WOBA_SUM"].to_numpy(dtype=float)
    den = tot["WOBA_DEN"].to_numpy(dtype=float)
    lw = (h["WOBA_SUM"].sum() / h["WOBA_DEN"].sum()) if len(h) and h["WOBA_DEN"].sum() > 0 else 0.315
    wo = (num + reg_pa * lw) / (den + reg_pa)
    births = births if births is not None else _births(level)
    if role == "hitter":
        ages = np.array([age_on(pid, target, births) or 29.0 for pid in tot.index])
        wo = wo * np.where(ages > 29, 1 - (ages - 29) * 0.003, 1 + (29 - ages) * 0.006)
    out["wOBA"] = wo
    return out


def actuals(level: str, season: int, role: str) -> pd.DataFrame:
    h, p = season_aggregates(level, season)
    t = h if role == "hitter" else p
    if not len(t):
        return pd.DataFrame()
    out = pd.DataFrame(index=t.index)
    for c in ("K", "BB", "HRBIP", "HITS", "XWCON"):
        r, n = _rate(t, c)
        out[c] = r
        out[c + "_n"] = n
    out["wOBA"] = t["WOBA_SUM"] / t["WOBA_DEN"].replace(0, np.nan)
    out["PA"] = t["PA"]
    out["wOBA_n"] = t["WOBA_DEN"]
    return out


def evaluate(level: str = "mlb", seasons: Iterable[int] | None = None, min_n: int = 200) -> dict:
    """Weighted RMSE of next-season projections v the Marcel-like baseline, per component, role and season."""
    avail = _dio.pitch_seasons(level)
    seasons = [s for s in (seasons or avail) if s - 1 in avail]
    births = _births(level)
    res = {"seasons": {}, "pooled": {}}
    pooled: dict = {}
    for role in ("hitter", "pitcher"):
        aging = fit_aging(level, [s for s in avail if s < (min(seasons) if seasons else 0)] or avail[:-1], role, births) \
            if seasons else None
        for s in seasons:
            # aging fitted strictly on seasons before the target (walk-forward)
            ag = fit_aging(level, [x for x in avail if x < s], role, births)
            ours = project(level, s, "next", role=role, aging=ag, births=births)
            base = marcel(level, s, role, births=births)
            act = actuals(level, s, role)
            if not len(ours) or not len(base) or not len(act):
                continue
            ids = act.index[(act["PA"] >= min_n)].intersection(ours.index).intersection(base.index)
            row = {"n": int(len(ids))}
            for c in ("K", "BB", "HRBIP", "HITS", "wOBA"):
                a = act.loc[ids, c].to_numpy(dtype=float)
                w = act.loc[ids, c + "_n" if c != "wOBA" else "wOBA_n"].to_numpy(dtype=float)
                o = ours.loc[ids, c].to_numpy(dtype=float)
                b = base.loc[ids, c].to_numpy(dtype=float)
                ok = np.isfinite(a) & np.isfinite(o) & np.isfinite(b) & (w > 0)
                if ok.sum() < 10:
                    continue
                ro = float(np.sqrt(np.average((o[ok] - a[ok]) ** 2, weights=w[ok])))
                rb = float(np.sqrt(np.average((b[ok] - a[ok]) ** 2, weights=w[ok])))
                row[c] = {"ours": round(ro, 5), "marcel": round(rb, 5), "gain_pct": round(100 * (1 - ro / rb), 2)}
                pz = pooled.setdefault((role, c), [0.0, 0.0, 0.0])
                pz[0] += float(np.sum(w[ok] * (o[ok] - a[ok]) ** 2))
                pz[1] += float(np.sum(w[ok] * (b[ok] - a[ok]) ** 2))
                pz[2] += float(np.sum(w[ok]))
            res["seasons"].setdefault(role, {})[str(s)] = row
    for (role, c), (so, sb, sw) in pooled.items():
        ro, rb = math.sqrt(so / sw), math.sqrt(sb / sw)
        res["pooled"].setdefault(role, {})[c] = {"ours": round(ro, 5), "marcel": round(rb, 5),
                                                 "gain_pct": round(100 * (1 - ro / rb), 2)}
    return res


# ── payloads ─────────────────────────────────────────────────────────────────

def for_season(level: str, season: int, kind: str = "next", n_proj_h: float = 600, n_proj_p: float = 700,
               min_n: float = 50) -> dict:
    """
    {"hitters": {pid: {...}}, "pitchers": {pid: {...}}, "kind", "season", "version"} for the site and the game
    model. Components with p10/p90, wOBA, ISO, BABIP, event rates by opposing hand, age.
    """
    out: dict[str, Any] = {"season": season, "level": level, "kind": kind, "version": VERSION}
    for role, npj, key in (("hitter", n_proj_h, "hitters"), ("pitcher", n_proj_p, "pitchers")):
        try:
            df = project(level, season, kind, role=role, n_proj=npj)
        except Exception as exc:  # noqa: BLE001
            logger.info("projection %s %s failed: %s", role, season, exc)
            df = pd.DataFrame()
        rows = {}
        if len(df):
            df = df[df["PA"] >= min_n]
            for pid, r in df.iterrows():
                d = {"age": None if r.get("age") is None or not np.isfinite(r.get("age") or np.nan) else round(float(r["age"]), 1),
                     "n": round(float(r["PA"]), 1), "wOBA": round(float(r["wOBA"]), 4), "ISO": round(float(r["ISO"]), 4),
                     "BABIP": round(float(r["BABIP"]), 4),
                     "rates": {"all": [round(float(x), 5) for x in r["rates"]],
                               "L": [round(float(x), 5) for x in r["rates_L"]],
                               "R": [round(float(x), 5) for x in r["rates_R"]]}}
                comps = {}
                for c in STAB[role]:
                    if c in r and np.isfinite(r[c]):
                        comps[c] = {"proj": round(float(r[c]), 5), "p10": round(float(r[c + "_p10"]), 5),
                                    "p90": round(float(r[c + "_p90"]), 5), "n": round(float(r[c + "_n"]), 1)}
                d["components"] = comps
                if role == "pitcher":
                    for c in ("pc_mean_last", "gs_last", "g_last"):
                        if c in r and r[c] is not None and np.isfinite(r[c]):
                            d[c] = round(float(r[c]), 2)
                rows[str(pid)] = d
        out[key] = rows
    return out
