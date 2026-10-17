"""
Stabilisation: the sample at which each NHL metric becomes signal (split-half reliability 0.7).

Every metric is a ratio of sums over units of one entity (player, goalie): value = sum(a) / sum(b), with a sample
size sum(den) in the metric's own denominator — events (shots, unblocked attempts faced, faceoffs) or time on ice
in seconds (per-60 rates and on-ice shares, whose units are player-games). For each sample size n on the grid:
take every entity with at least 2n of denominator in the season (in game order), keep its first 2n, deal its
units alternately into two halves, compute the half values and correlate them across entities (r_n, needs
MIN_ENTITIES). Under the Spearman-Brown model the reliability of an n-sample mean is

    r(n) = n / (n + k),   n_0.7 = k * 0.7 / 0.3,

k fitted by weighted least squares on (n, r_n) per season, pooled over seasons as an entity-weighted geometric
mean (one season in memory at a time). k is the shrinkage constant the other models use: regressed =
(sum + k * prior) / (n + k) (`shrink_k`). Time-denominated k are in seconds (builder D shows minutes).

Metrics (name: entity, units, value):
  finishing     shooter, unblocked attempts (manned net), goals - xG per attempt
  shot_quality  shooter, unblocked attempts, xG per attempt
  sh_pct        shooter, shots on goal, goals per shot
  gsax100 / gsax60  goalie, unblocked attempts faced, (xG - goals) per attempt
  g_sv_pct      goalie, unblocked attempts faced, saves / shots on goal
  g_hd_sv_pct   goalie, unblocked attempts faced, high-danger saves / high-danger shots on goal
  fo_pct        faceoff taker, faceoffs, wins per faceoff
  p60, g60, p1_60, hits60, blocks60, pen_taken60, pen_drawn60   skater, all-situations TOI
  p60_5v5, ixg60, icf60, ipp, cf60, ca60, xgf60, xga60, cf_pct, xgf_pct, gf_pct   skater, 5v5 TOI
  pp_p60        skater, power-play TOI
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io

MODEL_VERSION = "nhlstab-1"
TARGET = 0.7
MIN_ENTITIES = 20
MIN = 60.0
GRID_EVENTS = [25, 50, 75, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000, 3000]
GRID_TIME = [m * MIN for m in (20, 40, 60, 100, 150, 200, 300, 400, 500, 600, 800)]
DEFAULT_K = {"finishing": 1500.0, "shot_quality": 60.0, "sh_pct": 375.0, "gsax100": 1200.0, "gsax60": 1200.0,
             "g_sv_pct": 2000.0, "g_hd_sv_pct": 1500.0, "fo_pct": 140.0,
             "p60": 400 * MIN, "g60": 600 * MIN, "p1_60": 400 * MIN, "hits60": 150 * MIN, "blocks60": 200 * MIN,
             "pen_taken60": 600 * MIN, "pen_drawn60": 600 * MIN, "p60_5v5": 500 * MIN, "ixg60": 250 * MIN,
             "icf60": 150 * MIN, "ipp": 400 * MIN, "cf60": 400 * MIN, "ca60": 400 * MIN, "xgf60": 500 * MIN,
             "xga60": 500 * MIN, "cf_pct": 400 * MIN, "xgf_pct": 500 * MIN, "gf_pct": 1500 * MIN, "pp_p60": 300 * MIN}
TIME_METRICS = {"p60": ("toi", ["g", "a1", "a2"], None), "g60": ("toi", ["g"], None), "p1_60": ("toi", ["g", "a1"], None),
                "hits60": ("toi", ["hits"], None), "blocks60": ("toi", ["blocks"], None),
                "pen_taken60": ("toi", ["pen_taken"], None), "pen_drawn60": ("toi", ["pen_drawn"], None),
                "p60_5v5": ("toi5", ["g5", "a1_5", "a2_5"], None), "ixg60": ("toi5", ["ixg5"], None),
                "icf60": ("toi5", ["icf5"], None), "ipp": ("toi5", ["g5", "a1_5", "a2_5"], ["gf5_on"]),
                "cf60": ("toi5", ["cf5"], None), "ca60": ("toi5", ["ca5"], None), "xgf60": ("toi5", ["xgf5"], None),
                "xga60": ("toi5", ["xga5"], None), "cf_pct": ("toi5", ["cf5"], ["cf5", "ca5"]),
                "xgf_pct": ("toi5", ["xgf5"], ["xgf5", "xga5"]), "gf_pct": ("toi5", ["gf5_on"], ["gf5_on", "ga5_on"]),
                "pp_p60": ("toipp", ["gpp", "a1pp", "a2pp"], None)}
LABELS = {"finishing": "Goals above xG per unblocked attempt", "shot_quality": "xG per unblocked attempt",
          "sh_pct": "Shooting %", "gsax100": "GSAx per unblocked attempt faced", "gsax60": "GSAx (per attempt faced)",
          "g_sv_pct": "Save %", "g_hd_sv_pct": "High-danger save %", "fo_pct": "Faceoff %"}


def _frame(entity, t, a, b, den) -> pd.DataFrame:
    return pd.DataFrame({"entity": np.asarray(entity, float), "t": np.asarray(t, float), "a": np.asarray(a, float),
                         "b": np.asarray(b, float), "den": np.asarray(den, float)})


def unit_tables(season: int, sh: pd.DataFrame | None = None, ev: pd.DataFrame | None = None,
                pg: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """metric -> [entity, t, a, b, den] for one season (t = order within the season)."""
    from oddsmarkets.nhl.models import _stints, xg
    from oddsmarkets.nhl.models.goalies import faced
    season = _io.sid(season)
    out: dict[str, pd.DataFrame] = {}
    sh = xg.shot_table(season) if sh is None else sh
    if len(sh) and sh["xg"].notna().any():
        t = sh["game_id"].to_numpy(float) * 1e4 + sh["idx"].to_numpy(float)
        man = (sh["empty_net"].to_numpy(float) == 0) & sh["shooter"].notna().to_numpy() & np.isfinite(sh["xg"].to_numpy(float))
        s = sh[man]
        ts = t[man]
        one = np.ones(len(s))
        out["finishing"] = _frame(s["shooter"], ts, s["goal"] - s["xg"], one, one)
        out["shot_quality"] = _frame(s["shooter"], ts, s["xg"], one, one)
        sog = s["type"].isin(["goal", "shot-on-goal"]).to_numpy()
        out["sh_pct"] = _frame(s["shooter"][sog], ts[sog], s["goal"][sog], one[sog], one[sog])
        f = faced(sh)
        if len(f):
            tf = f["game_id"].to_numpy(float) * 1e4 + f["idx"].to_numpy(float)
            o = np.ones(len(f))
            out["gsax100"] = _frame(f["g"], tf, f["xg"] - f["goal"], o, o)
            out["gsax60"] = out["gsax100"]
            fs = f["type"].isin(["goal", "shot-on-goal"]).to_numpy(float)
            out["g_sv_pct"] = _frame(f["g"], tf, fs * (1 - f["goal"].to_numpy(float)), fs, o)
            hd = (f["xg"].to_numpy(float) >= xg.DANGER[1]).astype(float)
            out["g_hd_sv_pct"] = _frame(f["g"], tf, hd * fs * (1 - f["goal"].to_numpy(float)), hd * fs, o)
    ev = _io.events(season) if ev is None else ev
    fo = ev[(ev["type"] == "faceoff") & ev["winner"].notna() & ev["loser"].notna()]
    if len(fo):
        tf = fo["game_id"].to_numpy(float) * 1e4 + fo["idx"].to_numpy(float)
        o = np.ones(len(fo))
        out["fo_pct"] = pd.concat([_frame(fo["winner"], tf, o, o, o), _frame(fo["loser"], tf, 0 * o, o, o)], ignore_index=True)
    pg = _stints.player_games_cached(season) if pg is None else pg
    if pg is not None and len(pg):
        t = pg["game_id"].to_numpy(float)
        for m, (den, num, dnm) in TIME_METRICS.items():
            d = pg[den].to_numpy(float)
            a = pg[num].to_numpy(float).sum(axis=1)
            b = pg[dnm].to_numpy(float).sum(axis=1) if dnm else d
            keep = d > 0
            out[m] = _frame(pg["player"][keep], t[keep], a[keep], b[keep], d[keep])
    return out


def split_half_curve(u: pd.DataFrame, grid: list[float], min_entities: int = MIN_ENTITIES) -> list[list[float]]:
    d = u.dropna()
    if not len(d):
        return []
    d = d.sort_values(["entity", "t"], kind="mergesort").reset_index(drop=True)
    cum = d.groupby("entity")["den"].cumsum().to_numpy()
    prev = cum - d["den"].to_numpy()
    tot = d.groupby("entity")["den"].transform("sum").to_numpy()
    out = []
    for n in grid:
        m = (tot >= 2 * n) & (prev < 2 * n)
        ents = np.unique(d["entity"].to_numpy()[m])
        if len(ents) < min_entities:
            break
        s = d[m]
        half = s.groupby("entity").cumcount().to_numpy() % 2
        h = s.assign(h=half).groupby(["entity", "h"])[["a", "b"]].sum()
        v = (h["a"] / h["b"].where(h["b"] > 0)).unstack()
        if v.shape[1] < 2:
            break
        r = _io.pearson(v[0], v[1])
        if r is not None:
            out.append([float(n), float(r), int(v.dropna().shape[0])])
    return out


def fit_k(curve: list[list[float]]) -> float | None:
    pts = [(n, r, w) for n, r, w in curve if 0.02 < r < 0.995]
    if not pts:
        return None
    ks = np.logspace(-0.5, 7.5, 800)
    n = np.array([p[0] for p in pts])
    r = np.array([p[1] for p in pts])
    w = np.array([p[2] for p in pts], float)
    err = ((r[None, :] - n[None, :] / (n[None, :] + ks[:, None])) ** 2 * w[None, :]).sum(axis=1)
    return float(ks[int(np.argmin(err))])


def season_stability(season: int, **kw) -> dict:
    tabs = unit_tables(season, **kw)
    out = {}
    for m, u in tabs.items():
        grid = GRID_TIME if m in TIME_METRICS else GRID_EVENTS
        curve = split_half_curve(u, grid)
        out[m] = {"curve": curve, "k": fit_k(curve), "entities": int(max([c[2] for c in curve], default=0))}
    return out


def combine(per: dict[str, dict]) -> dict:
    res = {}
    names = sorted({m for r in per.values() for m in r})
    for m in names:
        ks, ws = [], []
        for _s, r in per.items():
            x = r.get(m)
            if x and x.get("k"):
                ks.append(x["k"])
                ws.append(max(x.get("entities", 1), 1))
        if not ks:
            continue
        k = float(np.exp(np.average(np.log(ks), weights=ws)))
        unit = "seconds" if m in TIME_METRICS else "events"
        res[m] = {"k": round(k, 1), "n70": round(k * TARGET / (1 - TARGET), 1), "unit": unit,
                  "label": LABELS.get(m, m), "seasons": len(ks)}
    return res


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import xg
    season = _io.sid(season)
    f = xg.current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), MODEL_VERSION, f.get("key"), f.get("platt"))
    return _io.cached("stabilise", str(season), key, lambda: season_stability(season), use_cache)


def table(seasons=None) -> dict:
    seasons = _io.season_range(seasons)
    return combine({str(s): for_season(s) for s in seasons})


_K: dict = {}


def shrink_k(metric: str) -> float:
    """The fitted k (models/fitted/stabilise.json) or the default."""
    if "fit" not in _K:
        f = _io.read_fit("stabilise")
        _K["fit"] = f if isinstance(f, dict) and f.get("version") == MODEL_VERSION else {}
    m = (_K["fit"].get("metrics") or {}).get(metric)
    return float(m["k"]) if m and m.get("k") else float(DEFAULT_K.get(metric, 200.0))


def point(metric: str) -> float:
    return shrink_k(metric) * TARGET / (1 - TARGET)


def export_fits(seasons=None) -> dict:
    out = {"version": MODEL_VERSION, "target": TARGET, "metrics": table(seasons)}
    _io.write_fit("stabilise", out)
    _K.clear()
    return out
