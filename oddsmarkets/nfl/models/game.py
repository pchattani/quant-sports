"""
Pregame game model: expected margin and total -> win probability, spread and total distributions.

Margin (home minus away)
------------------------
    mu = s * (net_h - net_a)                              team strength (team_strength.net with each side's QB)
       + b_sr * (sr_h - sr_a)                             success-rate composite (NP (SR_PO - SR_PD) + NR (SR_RO - SR_RD))
       + (HFA + HFA_s) * [not neutral]                    home field, by season (see below)
       + b_div   * [not neutral] * [division game]        home edge in division games
       + b_rest  * (min(max(rest_h,4),14) - min(max(rest_a,4),14)) / 7
       + b_bye   * (bye_h - bye_a)                        coming off a bye week
       + b_short * (short_h - short_a)                    short week (<= 5 days)
       + b_trav  * (km_a - km_h) / 1000                   distance from home stadium to the venue
       + b_tz    * (tz_a - tz_h)                          hours between home time zone and the venue's
       + b_mr    * mr                                     market-implied line from EARLIER closing lines (below)
       + b_so_off * so_off + b_so_def * so_def            depth-chart starters out, home minus away (below)

Market ratings (feature `mr`, models/market_ratings.py): before each week, a ridge of every earlier played game's
closing line on home field + team terms (half-life 2 weeks, prior 0.8 x last season's final), with each game's
starting QBs taken out (0.77 x NP x QB value), so mr = the market's rating difference + home field + 0.77 x NP x
(QB_h - QB_a) for this game's quarterbacks. It is a market-blend input: it carries what earlier prices knew (injuries,
depth, money) that the EPA ratings miss. Added 2 Oct 2026 after the edge research (docs/research/nfl_edge.md): on
2017-2026 out of sample it cut the moneyline log-loss by 0.0063 (95% CI 0.0029-0.0098), ATS by 0.0058 and totals
by 0.0038 (total ratings: feature `mrt` = market total - base). With unfitted parameters (b_mr = 0) nothing changes.

Starters out (features `so_off`, `so_def`, models/availability.py; added 21 Oct 2026): for each side, the depth-chart
starters (as of the team's previous game; QBs and specialists excluded) who miss the game, offence (OL, receivers,
backs) and defence (DL, LB, DB) separately, home minus away. Before kickoff a starter counts by the final injury report
(Out 1, Doubtful 0.85, Questionable 0.15); from 2020, once nflverse's weekly roster carries the game-day status, the
actual inactives (and reserve moves) count 1. On 2017-2026 out of sample it lowered the moneyline log-loss by 0.0025
(95% CI 0.0007-0.0043; docs/research/nfl_edge.md). A feature enters the fit only once 256 earlier games have a
non-zero value (the reports start in 2009). Games without reports yet (more than a few days out) get 0.

HFA by season: HFA_s are one coefficient per season, ridge-penalised toward 0 (penalty LAM_HFA in game units), plus a
linear trend hfa_trend * (season - 2015) / 10, so the decline in home advantage is estimated from the data and a
season with few games leans on the trend. All coefficients are fitted by `fit_from_rows` (ridge, penalty 1 on the
feature coefficients) on walk-forward rows (ratings fitted from games strictly before each week); sigma is the
residual sd (degrees-of-freedom corrected).

Distribution: the margin is discrete with key numbers. p(m) is proportional to the Normal(mu, sigma) mass on
[m - 1/2, m + 1/2] times k(|m|), k fitted by `fit_keys` as the ratio of observed to Normal-expected frequency of each
absolute margin 0..30 on history (k(0) sets the tie rate; k(3), k(7) the key numbers), renormalised.
p_home = P(m > 0), p_tie = P(m = 0). In the playoffs a tie is impossible: p_home += p_tie / 2.

Total
-----
    total = base_s + t_off * O + b_wind * max(wind - 8, 0) * outdoor + b_cold * max(45 - temp, 0) * outdoor
            + b_dome * [dome or closed roof] + c
O = NP * (PO_h + PD_a + PO_a + PD_h) + NR * (RO_h + RD_a + RO_a + RD_h)  (EPA/play edges, pass offence with the QB)
base_s = exponentially weighted mean total of earlier games (half-life 256 games). The total is discrete: p(t) is
proportional to the Normal(total, sigma_t) mass on [t - 1/2, t + 1/2] times a total key multiplier tk(t) (37, 41, 44,
51 ... are commoner than a Normal says), tk fitted by `fit_total_keys` like the margin keys (added 21 Oct 2026; before,
a plain Normal). Team points = (total +- margin) / 2.

Market-line calibration (added 21 Oct 2026): the probability that the home side covers the MARKET spread, or that the
game goes over the MARKET total, is overconfident when read straight off the distributions: the market line already
holds most of what the model knows, and the model's disagreement with it is mostly noise (walk-forward logit slope of
the outcome on the model's cover probability about 0.2, on the over probability about 0.35). `market_cover` and
`market_over` therefore pass those two probabilities through a Platt map, logit p' = a + b logit p, with (a, b)
(`cal_ats`, `cal_tot`) fitted on the backtest's out-of-sample predictions (models/backtest.py; walk-forward there).
The margin and total distributions themselves, the win probability and every other line are unchanged.

Markets: `spread_to_p(line)` = P(home wins) for a market margin `line` ("home favoured by") through the same discrete
distribution with sigma_m (fitted sd of margin - line); `ml_to_p` de-vigs American moneylines multiplicatively.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import team_strength as TS

logger = logging.getLogger(__name__)

VERSION = 3
MARGIN_FEATURES = ("net", "sr", "hfa", "div", "rest", "bye", "short", "travel", "tz", "mr", "so_off", "so_def")
WARMUP = {"so_off": 256, "so_def": 256}       # rows with a non-zero value needed before a feature is fitted
TOTAL_FEATURES = ("off", "wind", "cold", "dome", "mrt")
LAM_HFA = 40.0
KEY_MAX = 30
DEFAULTS: dict[str, Any] = {
    "s": 0.9, "sr": 0.0, "hfa": 1.9, "hfa_trend": -0.7, "hfa_by_season": {}, "div": -0.4, "rest": 0.3, "bye": 0.5, "short": -0.3,
    "travel": 0.15, "tz": 0.2, "mr": 0.0, "so_off": 0.0, "so_def": 0.0, "sigma": 13.2, "sigma_market": 13.0,
    "t_off": 1.0, "wind": -0.35, "cold": -0.05, "dome": 1.0, "mrt": 0.0, "t_c": 0.0, "t_base": 44.0, "sigma_total": 13.3,
    "keys": None, "tkeys": None, "cal_ats": None, "cal_tot": None, "fitted": False, "n": 0,
}
_P: dict | None = None


def params(over: dict | None = None) -> dict:
    """Fitted parameters: the local cache, else the committed fit, else the defaults."""
    global _P
    if _P is None:
        p = dict(DEFAULTS)
        for path in (D.c_cache() / "game_params.json", D.FITTED / "game_params.json"):
            c = D.read_json(path)
            if c:
                p.update({k: v for k, v in (c.get("result") or c).items() if v is not None})
                break
        _P = p
    out = dict(_P)
    if over:
        out.update(over)
    return out


def set_params(p: dict | None) -> None:
    global _P
    _P = None if p is None else {**DEFAULTS, **p}


# ── features ─────────────────────────────────────────────────────────────────

def _clip_rest(x):
    return np.minimum(np.maximum(np.asarray(x, float), 4.0), 14.0)


def margin_features(df: pd.DataFrame) -> pd.DataFrame:
    """Columns of MARGIN_FEATURES from a frame with net_h, net_a and the add_context columns."""
    hfa = (~df["neutral"].astype(bool)).astype(float)
    return pd.DataFrame({
        "net": df["net_h"].to_numpy(float) - df["net_a"].to_numpy(float),
        "sr": (df["sr_h"].to_numpy(float) - df["sr_a"].to_numpy(float)) if "sr_h" in df else np.zeros(len(df)),
        "hfa": hfa.to_numpy(),
        "div": hfa.to_numpy() * df.get("div_game", pd.Series(0, index=df.index)).astype(float).to_numpy(),
        "rest": (_clip_rest(df["rest_h"]) - _clip_rest(df["rest_a"])) / 7.0,
        "bye": df["bye_h"].astype(float).to_numpy() - df["bye_a"].astype(float).to_numpy(),
        "short": df["short_h"].astype(float).to_numpy() - df["short_a"].astype(float).to_numpy(),
        "travel": (df["km_a"].to_numpy(float) - df["km_h"].to_numpy(float)) / 1000.0,
        "tz": df["tz_a"].to_numpy(float) - df["tz_h"].to_numpy(float),
        "mr": _mr_feature(df, hfa.to_numpy()),
        "so_off": pd.to_numeric(df["f_so_off"], errors="coerce").fillna(0.0).to_numpy(float) if "f_so_off" in df else np.zeros(len(df)),
        "so_def": pd.to_numeric(df["f_so_def"], errors="coerce").fillna(0.0).to_numpy(float) if "f_so_def" in df else np.zeros(len(df)),
    }, index=df.index)


def _mr_feature(df: pd.DataFrame, hfa: np.ndarray) -> np.ndarray:
    """f_mr when attached (attach_market); else (and where NaN) the market line's typical relation to the ratings,
    0.77 x net difference + 2 x home field, so an unattached frame is still priced sensibly."""
    fb = 0.77 * (df["net_h"].to_numpy(float) - df["net_a"].to_numpy(float)) + 2.0 * hfa
    if "f_mr" not in df:
        return fb
    v = pd.to_numeric(df["f_mr"], errors="coerce").to_numpy(float)
    return np.where(np.isfinite(v), v, fb)


def total_features(df: pd.DataFrame) -> pd.DataFrame:
    roof = df.get("roof", pd.Series("", index=df.index)).astype(str).str.lower()
    dome = roof.isin(["dome", "closed"]).to_numpy(float)
    outdoor = 1.0 - dome
    wind = pd.to_numeric(df.get("wind"), errors="coerce").fillna(5.0).to_numpy(float)
    temp = pd.to_numeric(df.get("temp"), errors="coerce").fillna(60.0).to_numpy(float)
    mrt = pd.to_numeric(df["t_mrt"], errors="coerce").fillna(0.0).to_numpy(float) if "t_mrt" in df else np.zeros(len(df))
    return pd.DataFrame({"off": df["off_sum"].to_numpy(float), "wind": np.maximum(wind - 8.0, 0.0) * outdoor,
                         "cold": np.maximum(45.0 - temp, 0.0) * outdoor, "dome": dome, "mrt": mrt}, index=df.index)


def mu_margin(F: pd.DataFrame, seasons: np.ndarray, p: dict, ratings_only: bool = False) -> np.ndarray:
    hs = p.get("hfa_by_season") or {}
    hfa_s = np.array([float(hs.get(str(int(s)), 0.0)) for s in seasons]) if len(seasons) else np.zeros(0)
    trend = p["hfa_trend"] * (np.asarray(seasons, float) - 2015.0) / 10.0
    mu = p["s"] * F["net"].to_numpy() + (p["hfa"] + trend + hfa_s) * F["hfa"].to_numpy()
    if not ratings_only:
        for k in ("sr", "div", "rest", "bye", "short", "travel", "tz", "mr", "so_off", "so_def"):
            mu = mu + p.get(k, 0.0) * F[k].to_numpy()
    return mu


def mu_total(F: pd.DataFrame, base: np.ndarray, p: dict) -> np.ndarray:
    mrt = p.get("mrt", 0.0) * F["mrt"].to_numpy() if "mrt" in F else 0.0
    return np.asarray(base, float) + p["t_c"] + p["t_off"] * F["off"].to_numpy() + p["wind"] * F["wind"].to_numpy() + \
        p["cold"] * F["cold"].to_numpy() + p["dome"] * F["dome"].to_numpy() + mrt


# ── distributions ────────────────────────────────────────────────────────────

SUPPORT = np.arange(-80, 81)


def keys(p: dict | None = None) -> np.ndarray:
    k = (p or params()).get("keys")
    out = np.ones(KEY_MAX + 1)
    if k:
        arr = np.asarray(k, float)[: KEY_MAX + 1]
        out[: len(arr)] = arr
    else:
        out[0] = 0.08                                 # ties are ~12x rarer than a Normal puts on [-1/2, 1/2]
    return out


def margin_pmf(mu: float | np.ndarray, sigma: float, kk: np.ndarray | None = None) -> np.ndarray:
    """P(margin = m) on SUPPORT (rows per mu when mu is an array)."""
    kk = keys() if kk is None else kk
    mu = np.atleast_1d(np.asarray(mu, float))[:, None]
    lo = ndtr((SUPPORT[None, :] - 0.5 - mu) / sigma)
    hi = ndtr((SUPPORT[None, :] + 0.5 - mu) / sigma)
    a = np.abs(SUPPORT)
    mult = np.where(a <= KEY_MAX, kk[np.minimum(a, KEY_MAX)], 1.0)
    p = (hi - lo) * mult[None, :]
    p /= p.sum(1, keepdims=True)
    return p


def win_probs(mu, sigma: float, playoff: bool | np.ndarray = False, kk=None) -> tuple[np.ndarray, np.ndarray]:
    """(p_home, p_tie) per mu."""
    P = margin_pmf(mu, sigma, kk)
    ph = P[:, SUPPORT > 0].sum(1)
    pt = P[:, SUPPORT == 0].sum(1)
    po = np.asarray(playoff, bool)
    ph = np.where(po, ph + pt / 2.0, ph)
    pt = np.where(po, 0.0, pt)
    return ph, pt


def cover_prob(mu: float, sigma: float, spread_home: float, kk=None) -> dict:
    """P(home covers / push / away covers) a home spread (negative = home favoured)."""
    P = margin_pmf(mu, sigma, kk)[0]
    adj = SUPPORT + float(spread_home)
    return {"home": float(P[adj > 0].sum()), "push": float(P[np.abs(adj) < 1e-9].sum()), "away": float(P[adj < 0].sum())}


TOT_SUPPORT = np.arange(0, 151)


def total_keys(p: dict | None = None) -> np.ndarray | None:
    """Total key multipliers on TOT_SUPPORT from the parameters (None: a plain Normal on the integers)."""
    tk = (p or params()).get("tkeys")
    if not tk:
        return None
    out = np.ones(len(TOT_SUPPORT))
    arr = np.asarray(tk, float)[: len(TOT_SUPPORT)]
    out[: len(arr)] = arr
    return out


def total_pmf(mu_t, sigma_t: float, tk: np.ndarray | None = None) -> np.ndarray:
    """P(total = t) on TOT_SUPPORT (rows per mu_t when an array): Normal mass on [t - 1/2, t + 1/2] x tk(t)."""
    mu = np.atleast_1d(np.asarray(mu_t, float))[:, None]
    P = ndtr((TOT_SUPPORT[None, :] + 0.5 - mu) / sigma_t) - ndtr((TOT_SUPPORT[None, :] - 0.5 - mu) / sigma_t)
    if tk is not None:
        P = P * np.asarray(tk, float)[None, : P.shape[1]]
    return P / P.sum(1, keepdims=True)


def total_prob(mu_t: float, sigma_t: float, line: float, tk: np.ndarray | None = None) -> dict:
    """P(over / push / under) for a total line (discrete total; tk = total key multipliers, None = plain Normal)."""
    s = TOT_SUPPORT
    P = total_pmf(mu_t, sigma_t, tk)[0]
    return {"over": float(P[s > line].sum()), "push": float(P[np.abs(s - line) < 1e-9].sum()), "under": float(P[s < line].sum())}


def fit_total_keys(mu: np.ndarray, y: np.ndarray, sigma: float, iters: int = 3) -> np.ndarray:
    """Total key multipliers tk(t): observed / expected counts of each total, iterated through the renormalisation;
    only totals with more than 5 expected games are adjusted, values clipped to [0.3, 3]."""
    tk = np.ones(len(TOT_SUPPORT))
    obs = np.bincount(np.clip(np.round(np.asarray(y, float)).astype(int), 0, len(TOT_SUPPORT) - 1),
                      minlength=len(TOT_SUPPORT)).astype(float)
    mu = np.asarray(mu, float)
    for _ in range(iters):
        exp = np.zeros(len(TOT_SUPPORT))
        for ch in np.array_split(np.arange(len(mu)), max(1, len(mu) // 3000)):
            exp += total_pmf(mu[ch], sigma, tk).sum(0)
        tk = np.clip(tk * np.where(exp > 5, obs / np.maximum(exp, 1e-9), 1.0), 0.3, 3.0)
    return tk


def platt(prob: float, ab) -> float:
    """logit p' = a + b logit p (ab None: p unchanged)."""
    if not ab or prob is None or not np.isfinite(prob):
        return prob
    q = min(max(float(prob), 1e-4), 1 - 1e-4)
    z = float(ab[0]) + float(ab[1]) * math.log(q / (1 - q))
    return 1.0 / (1.0 + math.exp(-z))


def _calibrated(d: dict, a: str, b: str, ab) -> dict:
    if not ab:
        return d
    rest = 1.0 - d["push"]
    if rest <= 0:
        return d
    pc = platt(d[a] / rest, ab)
    return {a: pc * rest, "push": d["push"], b: (1.0 - pc) * rest}


def market_cover(mu: float, sigma: float, spread_home: float, kk=None, p: dict | None = None) -> dict:
    """cover_prob at a MARKET spread with the market-line calibration (cal_ats) applied to P(home covers | no push)."""
    return _calibrated(cover_prob(mu, sigma, spread_home, kk), "home", "away", (p or params()).get("cal_ats"))


def market_over(mu_t: float, sigma_t: float, line: float, tk=None, p: dict | None = None) -> dict:
    """total_prob at a MARKET total with the total keys and the market-line calibration (cal_tot)."""
    pp = p or params()
    return _calibrated(total_prob(mu_t, sigma_t, line, total_keys(pp) if tk is None else tk), "over", "under",
                       pp.get("cal_tot"))


def spread_to_p(line: float | None, sd: float | None = None, kk=None) -> float | None:
    """P(home wins) implied by a market margin `line` (home favoured by; = -spread_home)."""
    if line is None:
        return None
    try:
        x = float(line)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    p = params()
    ph, pt = win_probs(x, float(sd or p.get("sigma_market") or p["sigma"]), False, kk)
    return float(ph[0] + pt[0] / 2.0)


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


# ── rows from ratings ────────────────────────────────────────────────────────

def side_values(rd: dict, team: str, qb: str | None) -> dict:
    u = TS.team_units(rd, team, qb)
    sr = (rd.get("sr") or {}).get(team) or {}
    lg = rd.get("league") or {}
    NPg, NRg = float(lg.get("np", TS.DEFAULTS["np"])), float(lg.get("nr", TS.DEFAULTS["nr"]))
    return {"net": float(u.get("net", 0.0)), "po": float(u.get("pass_off", 0.0)), "pd": float(u.get("pass_def", 0.0)),
            "ro": float(u.get("rush_off", 0.0)), "rd": float(u.get("rush_def", 0.0)),
            "sr": NPg * (sr.get("pass_off", 0.0) - sr.get("pass_def", 0.0)) + NRg * (sr.get("rush_off", 0.0) - sr.get("rush_def", 0.0))}


def _qbv(rd: dict, team: str, qb) -> float:
    """The QB value (EPA per dropback) a side's net rating uses: the named QB, else the team's current starter."""
    if isinstance(qb, str) and qb:
        return float(TS.qb_value(rd, qb))
    return float(((rd.get("teams") or {}).get(team) or {}).get("qb_val", 0.0))


def attach_market(df: pd.DataFrame, games: pd.DataFrame | None = None, rd: dict | None = None) -> pd.DataFrame:
    """f_mr (market-implied line with this game's QBs added back), mr_line, mr_total and t_mrt (when df has `base`)
    for the games in `df` (needs net_h, net_a, qbv_h, qbv_a, np_lg from attach_ratings). `games`: a games frame with the
    seasons' closing lines and `played` flags (default: _cdata.games_frame of df's seasons and the one before); only
    PLAYED games' lines enter. A past game's QB adjustment uses df's own qbv when df has that game, else `rd`'s values."""
    from oddsmarkets.nfl.models import market_ratings as MRm
    if df.empty:
        return df
    seasons = sorted(set(int(x) for x in df["season"]))
    G = games if games is not None else D.games_frame(range(seasons[0] - 1, seasons[-1] + 1))
    if G is None or G.empty or "line" not in G:
        return df
    G = G[G["season"].between(seasons[0] - 1, seasons[-1])]
    known = df.drop_duplicates("game_id").set_index("game_id")
    qv: dict = {}
    if {"qbv_h", "qbv_a", "np_lg"} <= set(known.columns):
        qv = (MRm.QB_S * known["np_lg"] * (known["qbv_h"] - known["qbv_a"])).to_dict()
    if rd is not None:
        npg = float((rd.get("league") or {}).get("np", TS.DEFAULTS["np"]))
        for r in G.itertuples(index=False):
            if r.game_id not in qv and bool(r.played):
                hq, aq = getattr(r, "home_qb", None), getattr(r, "away_qb", None)
                qv[r.game_id] = MRm.QB_S * npg * (_qbv(rd, r.home, hq) - _qbv(rd, r.away, aq))
    cols = ["game_id", "season", "week", "date", "home", "away", "neutral", "line", "total_line", "played"]
    extra = df.loc[~df["game_id"].isin(G["game_id"])]
    allg = pd.concat([G[cols], extra[[c for c in cols if c in extra]]], ignore_index=True)
    allg["played"] = allg["played"].fillna(False).astype(bool)
    for c in ("line", "total_line"):
        allg[c] = pd.to_numeric(allg[c], errors="coerce")
    m = MRm.ratings(allg, qadj=pd.Series(qv, dtype=float)).drop_duplicates("game_id").set_index("game_id")
    out = df.copy()
    mm = m.reindex(out["game_id"])
    qadd = MRm.QB_S * out["np_lg"].to_numpy(float) * (out["qbv_h"].to_numpy(float) - out["qbv_a"].to_numpy(float))
    out["mr_line"] = mm["mr_line"].to_numpy(float)
    out["mr_total"] = mm["mr_total"].to_numpy(float)
    out["f_mr"] = out["mr_line"].to_numpy(float) + qadd
    if "base" in out:
        out["t_mrt"] = out["mr_total"] - out["base"]
    return out


def attach_availability(df: pd.DataFrame) -> pd.DataFrame:
    """f_so_off / f_so_def (models/availability.py) for the frame's games; zeros when the inputs are missing."""
    if df.empty or "season" not in df:
        return df
    try:
        from oddsmarkets.nfl.models import availability as AV
        L = AV.load(sorted(set(int(x) for x in df["season"])))
        out = AV.attach(df, L, open_modes_zero=False)
        keep = ["f_so_off", "f_so_def"]
        drop = [c for c in out.columns if c not in df.columns and c not in keep]
        return out.drop(columns=drop)
    except Exception as exc:  # noqa: BLE001 - the feature is optional: 0 means "no news"
        logger.info("availability unavailable: %s", exc)
        return df.assign(f_so_off=0.0, f_so_def=0.0)


def attach_ratings(g: pd.DataFrame, rd: dict, use_listed_qb: bool = True, qb_override: dict | None = None) -> pd.DataFrame:
    """net_h, net_a, off_sum (and the unit edges) for games under one ratings snapshot."""
    lg = rd.get("league") or {}
    NPg, NRg = float(lg.get("np", TS.DEFAULTS["np"])), float(lg.get("nr", TS.DEFAULTS["nr"]))
    rows = []
    for r in g.itertuples(index=False):
        qh = (qb_override or {}).get(r.home) or (r.home_qb if use_listed_qb and isinstance(r.home_qb, str) and r.home_qb else None)
        qa = (qb_override or {}).get(r.away) or (r.away_qb if use_listed_qb and isinstance(r.away_qb, str) and r.away_qb else None)
        h, a = side_values(rd, r.home, qh), side_values(rd, r.away, qa)
        rows.append({"net_h": h["net"], "net_a": a["net"], "sr_h": h["sr"], "sr_a": a["sr"],
                     "off_sum": NPg * (h["po"] + a["pd"] + a["po"] + h["pd"]) + NRg * (h["ro"] + a["rd"] + a["ro"] + h["rd"]),
                     "eff_h": (NPg * (h["po"] + a["pd"]) + NRg * (h["ro"] + a["rd"])) / (NPg + NRg),
                     "eff_a": (NPg * (a["po"] + h["pd"]) + NRg * (a["ro"] + h["rd"])) / (NPg + NRg),
                     "qb_h": qh or (rd.get("starters") or {}).get(r.home), "qb_a": qa or (rd.get("starters") or {}).get(r.away),
                     "qbv_h": _qbv(rd, r.home, qh), "qbv_a": _qbv(rd, r.away, qa), "np_lg": NPg})
    out = g.copy()
    add = pd.DataFrame(rows, index=g.index)
    for c in add.columns:
        out[c] = add[c]
    return out


def walk_forward(seasons: list[int], first: int | None = None, units_of=None, games: pd.DataFrame | None = None,
                 prm_ts: dict | None = None, progress: bool = False) -> pd.DataFrame:
    """
    Walk-forward rows: for each season (chained from `first`, default the earliest of `seasons`) and each week, the
    ratings are fitted from that season's games strictly before the week (with the preseason prior from the previous
    season's end-of-season fit) and attached to the week's games. Returns one row per game (played or not) with
    margin features, total features, base (scoring level), outcomes and market lines.
    """
    units_of = units_of or D.unit_rows
    p = prm_ts or TS.params()
    seasons = sorted(seasons)
    first = first if first is not None else seasons[0]
    chain = list(range(first, seasons[-1] + 1))
    G = games if games is not None else D.games_frame(chain)
    if G.empty:
        return pd.DataFrame()
    G = D.add_context(G[G["season"].isin(chain)])
    out = []
    last = None
    book: dict = {}
    base_num, base_den = 0.0, 0.0
    decay = 0.5 ** (1 / 256.0)
    for s in chain:
        u = units_of(s)
        gs = G[G["season"] == s]
        prior = TS.preseason_prior(last, s, p, book, TS.continuity(s))
        if gs.empty:
            continue
        weeks = sorted(gs["week"].unique())
        for w in weeks:
            gw = gs[gs["week"] == w]
            thr = gw["date"].min()
            r = TS.fit(u, s, thr, prior, p, teams=sorted(set(gs["home"]) | set(gs["away"])))
            rd = r.as_dict()
            rd["qb_prior"] = prior["qbs"]
            gw = attach_ratings(gw, rd)
            base = base_num / base_den if base_den > 0 else TS.DEFAULTS["np"] * 0 + DEFAULTS["t_base"]
            gw = gw.assign(base=base, n_games_rated=r.league.get("n_games", 0))
            if s in seasons:
                out.append(gw)
            for t in gw.loc[gw["played"], "total"].to_numpy(float):
                base_num = base_num * decay + t
                base_den = base_den * decay + 1.0
        end = TS.fit(u, s, None, prior, p)
        TS.update_qb_book(book, end)
        last = end
        if progress:
            logger.info("walk_forward %s: %d games", s, len(gs))
        del u
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    df = attach_market(df, G)
    df = attach_availability(df)
    MF = margin_features(df)
    TF = total_features(df)
    for c in MF.columns:
        df["f_" + c] = MF[c]
    for c in TF.columns:
        df["t_" + c] = TF[c]
    return df


# ── fitting ──────────────────────────────────────────────────────────────────

def _mf(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({c: (rows["f_" + c].to_numpy(float) if "f_" + c in rows else np.zeros(len(rows)))
                         for c in MARGIN_FEATURES})


def _tf(rows: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({c: (rows["t_" + c].to_numpy(float) if "t_" + c in rows else np.zeros(len(rows)))
                         for c in TOTAL_FEATURES})


def fit_from_rows(rows: pd.DataFrame, min_rows: int = 200, with_keys: bool = True) -> dict:
    """Margin and total coefficients, sigmas and key-number multipliers from walk-forward rows (played games)."""
    p = dict(DEFAULTS)
    if rows is None or rows.empty:
        return p
    r = rows[rows["played"].astype(bool) & rows["margin"].notna()]
    r = r[r["n_games_rated"] > 0] if "n_games_rated" in r else r
    if len(r) < min_rows:
        return p
    F = _mf(r)
    for c, n_min in WARMUP.items():                      # too little history: the feature stays out (coefficient 0)
        if c in F and (F[c].to_numpy() != 0).sum() < n_min:
            F[c] = 0.0
    seasons = r["season"].to_numpy(int)
    us = sorted(set(seasons))
    trend = (seasons - 2015.0) / 10.0 * F["hfa"].to_numpy()
    X = np.column_stack([F[c].to_numpy() for c in MARGIN_FEATURES] + [trend] +
                        [(seasons == s) * F["hfa"].to_numpy() for s in us])
    y = r["margin"].to_numpy(float)
    k = len(MARGIN_FEATURES) + 1
    lam = np.concatenate([np.full(k, 1.0), np.full(len(us), LAM_HFA)])
    lam[0] = 1e-6
    lam[MARGIN_FEATURES.index("hfa")] = 1e-6
    beta = TS.spd_inv(X.T @ X + np.diag(lam)) @ (X.T @ y)
    res = y - X @ beta
    sigma = float(np.sqrt((res ** 2).sum() / max(len(y) - k, 1)))
    for i, c in enumerate(MARGIN_FEATURES):
        p["s" if c == "net" else c] = float(beta[i])
    p["hfa_trend"] = float(beta[len(MARGIN_FEATURES)])
    p["hfa_by_season"] = {str(s): float(beta[k + j]) for j, s in enumerate(us)}
    p["sigma"] = sigma
    mu = X @ beta
    # market sigma: sd of margin - line on games with a line
    m = r["line"].notna().to_numpy()
    if m.sum() >= 50:
        p["sigma_market"] = float(np.std(y[m] - r["line"].to_numpy(float)[m]))
    if with_keys:
        p["keys"] = fit_keys(mu, y, sigma).tolist()
    # totals
    TF = _tf(r)
    yt = r["total"].to_numpy(float) - r["base"].to_numpy(float)
    Xt = np.column_stack([TF[c].to_numpy() for c in TOTAL_FEATURES] + [np.ones(len(r))])
    lt = np.array([1.0] * len(TOTAL_FEATURES) + [1e-6])
    bt = TS.spd_inv(Xt.T @ Xt + np.diag(lt)) @ (Xt.T @ yt)
    for i, c in enumerate(TOTAL_FEATURES):
        p["t_off" if c == "off" else c] = float(bt[i])
    p["t_c"] = float(bt[-1])
    rt = yt - Xt @ bt
    p["sigma_total"] = float(np.sqrt((rt ** 2).sum() / max(len(yt) - len(TOTAL_FEATURES) - 1, 1)))
    if with_keys:
        p["tkeys"] = fit_total_keys(r["base"].to_numpy(float) + Xt @ bt, r["total"].to_numpy(float), p["sigma_total"]).tolist()
    p["n"] = int(len(r))
    p["fitted"] = True
    p["seasons"] = [int(min(us)), int(max(us))]
    return p


def fit_keys(mu: np.ndarray, y: np.ndarray, sigma: float, iters: int = 3) -> np.ndarray:
    """Key-number multipliers k(a), a = |margin| 0..KEY_MAX: observed / expected counts, iterated so the
    renormalisation inside margin_pmf is accounted for; values outside [0.02, 4] are clipped."""
    kk = np.ones(KEY_MAX + 1)
    a_obs = np.abs(np.round(y)).astype(int)
    obs = np.bincount(np.minimum(a_obs, KEY_MAX + 1), minlength=KEY_MAX + 2)[: KEY_MAX + 1].astype(float)
    for _ in range(iters):
        exp = np.zeros(KEY_MAX + 1)
        for chunk in np.array_split(np.arange(len(mu)), max(1, len(mu) // 4000)):
            P = margin_pmf(mu[chunk], sigma, kk)
            a = np.abs(SUPPORT)
            for v in range(KEY_MAX + 1):
                exp[v] += P[:, a == v].sum()
        kk = np.clip(kk * np.where(exp > 0, obs / np.maximum(exp, 1e-9), 1.0), 0.02, 4.0)
    return kk


# ── prediction ───────────────────────────────────────────────────────────────

def predict_frame(g: pd.DataFrame, rd: dict, p: dict | None = None, base: float | None = None,
                  qb_override: dict | None = None, market_games: pd.DataFrame | None = None) -> pd.DataFrame:
    """Margin / total / probabilities for a games frame (with add_context columns) under ratings `rd`.
    The market feature (only when the fitted b_mr / b_mrt are non-zero) comes from `market_games` (a games frame with
    closing lines and played flags: pass one cut at the simulation date when pricing as of a past date), else from
    the seasons' games on disk; without it margin_features falls back to the ratings."""
    p = p or params()
    g = attach_ratings(g, rd, qb_override=qb_override)
    b = np.full(len(g), float(base if base is not None else p.get("t_base", 44.0)))
    if (p.get("mr") or p.get("mrt")) and "f_mr" not in g and len(g) and "game_id" in g:
        try:
            g = attach_market(g.assign(base=b), market_games, rd)
        except Exception as exc:  # noqa: BLE001 - margin_features falls back to the ratings
            logger.info("market ratings unavailable: %s", exc)
    if (p.get("so_off") or p.get("so_def")) and "f_so_off" not in g and len(g) and "season" in g:
        g = attach_availability(g)
    MF = margin_features(g)
    TF = total_features(g)
    seasons = g["season"].to_numpy(int)
    mu = mu_margin(MF, seasons, p)
    tot = mu_total(TF, b, p)
    playoff = g["gtype"].astype(str).str.upper().ne("REG").to_numpy()
    ph, pt = win_probs(mu, p["sigma"], playoff, keys(p))
    out = g.copy()
    out["mu"], out["mu_total"] = mu, tot
    out["p_home"], out["p_tie"] = ph, pt
    out["p_away"] = 1.0 - ph - pt
    out["spread_fair"] = -mu
    out["pts_h"], out["pts_a"] = (tot + mu) / 2.0, (tot - mu) / 2.0
    out["sigma"], out["sigma_total"] = p["sigma"], p["sigma_total"]
    return out


def predict(home: str, away: str, season: int, rd: dict, ctx: dict | None = None, p: dict | None = None) -> dict:
    """One game. ctx: neutral, rest_h/rest_a, km_h/km_a, tz_h/tz_a, roof, temp, wind, div_game, home_qb, away_qb,
    gtype, base (scoring level)."""
    c = {"neutral": False, "rest_h": 7, "rest_a": 7, "km_h": 0.0, "km_a": 0.0, "tz_h": 0.0, "tz_a": 0.0, "roof": "outdoors",
         "temp": 60.0, "wind": 5.0, "div_game": 0, "home_qb": None, "away_qb": None, "gtype": "REG"}
    c.update(ctx or {})
    g = pd.DataFrame([{**c, "home": home, "away": away, "season": int(season),
                       "bye_h": c["rest_h"] >= 13, "bye_a": c["rest_a"] >= 13, "short_h": c["rest_h"] <= 5,
                       "short_a": c["rest_a"] <= 5}])
    r = predict_frame(g, rd, p, base=c.get("base"))
    row = r.iloc[0]
    pp = p or params()
    return {"margin": float(row["mu"]), "total": float(row["mu_total"]), "p_home": float(row["p_home"]),
            "p_tie": float(row["p_tie"]), "p_away": float(row["p_away"]), "spread_fair": float(row["spread_fair"]),
            "pts_h": float(row["pts_h"]), "pts_a": float(row["pts_a"]), "sigma": pp["sigma"], "sigma_total": pp["sigma_total"],
            "net_h": float(row["net_h"]), "net_a": float(row["net_a"])}


def save_params(p: dict, committed: bool = False) -> None:
    obj = {"version": VERSION, "result": p}
    D.write_json(D.c_cache() / "game_params.json", obj)
    if committed:
        D.write_json(D.FITTED / "game_params.json", obj)
    set_params(None)
