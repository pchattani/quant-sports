"""
Stabilisation: the sample at which each NFL metric becomes signal (split-half reliability 0.7).

For a metric measured on events of a unit (dropback, aimed pass, target, carry, field goal, team play),
for each sample size n in GRID: take every player (or team) with at least 2n events in the season (in
game and play order), split the first 2n into odd and even halves and correlate the half means across
players (r_n, needs MIN_PLAYERS). Under the Spearman-Brown model the reliability of an n-event mean is

    r(n) = n / (n + k),   k = n (1 - r) / r,   n_0.7 = k * 0.7 / 0.3.

k is fitted by least squares on (n, r_n) over the grid (weighted by players) per season, then pooled over
seasons as a players-weighted geometric mean; one season in memory at a time. k is the shrinkage constant
the other models use: regressed = (sum + k * prior) / (n + k) (`shrink_k`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "nflstab-1"
GRID = [10, 20, 30, 40, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500]
MIN_PLAYERS = 20
TARGET = 0.7
DEFAULT_K = {"qb_epa_db": 300.0, "cpoe": 350.0, "sack_rate": 120.0, "int_rate": 900.0, "twp_rate": 400.0,
             "ryoe_att": 250.0, "rush_success": 300.0, "croe": 150.0, "yacoe": 120.0, "epa_target": 150.0,
             "team_off_epa": 400.0, "team_def_epa": 900.0, "fgoe": 120.0}
# metric -> (entity, description)
METRICS = {
    "qb_epa_db": ("passer", "EPA per dropback"),
    "cpoe": ("passer", "CPOE (ours), per aimed pass"),
    "sack_rate": ("passer", "Sack rate per dropback"),
    "int_rate": ("passer", "Interception rate per attempt"),
    "twp_rate": ("passer", "Turnover-worthy (interception-worthy, FTN) rate per attempt"),
    "ryoe_att": ("rusher", "Rushing yards over expected per carry (ours)"),
    "rush_success": ("rusher", "Rushing success rate (EPA > 0)"),
    "croe": ("receiver", "Catch rate over expected per target"),
    "yacoe": ("receiver", "YAC over expected per reception"),
    "epa_target": ("receiver", "EPA per target"),
    "team_off_epa": ("team", "Offensive EPA per play"),
    "team_def_epa": ("team", "Defensive EPA per play allowed"),
    "fgoe": ("kicker", "Field goals over expected per attempt"),
}


def event_tables(season: int, d: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """metric -> frame [entity, t, value] for one season (t = order within the season)."""
    from oddsmarkets.nfl.models import completion, kicking, ryoe, yac
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return {}
    d = d.sort_values(["game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    wk = pd.to_numeric(d["week"], errors="coerce").fillna(0).to_numpy()
    order = np.lexsort((pd.to_numeric(d["play_id"], errors="coerce").fillna(0).to_numpy(), d["game_id"].astype(str).to_numpy(), wk))
    rank = np.empty(len(d), int)
    rank[order] = np.arange(len(d))
    d["t"] = rank
    out: dict[str, pd.DataFrame] = {}
    db = (pd.to_numeric(d["qb_dropback"], errors="coerce").fillna(0) == 1) & d["passer_player_id"].notna()
    x = d[db]
    out["qb_epa_db"] = pd.DataFrame({"entity": x["passer_player_id"].astype(str), "t": x["t"], "v": pd.to_numeric(x["epa"], errors="coerce")})
    out["sack_rate"] = pd.DataFrame({"entity": x["passer_player_id"].astype(str), "t": x["t"], "v": pd.to_numeric(x["sack"], errors="coerce").fillna(0)})
    pa = x[(pd.to_numeric(x["pass_attempt"], errors="coerce").fillna(0) == 1) & (pd.to_numeric(x["sack"], errors="coerce").fillna(0) == 0)]
    out["int_rate"] = pd.DataFrame({"entity": pa["passer_player_id"].astype(str), "t": pa["t"], "v": pd.to_numeric(pa["interception"], errors="coerce").fillna(0)})
    if "f_int_worthy" in pa and pa["f_int_worthy"].notna().any():
        q = pa[pa["f_int_worthy"].notna()]
        out["twp_rate"] = pd.DataFrame({"entity": q["passer_player_id"].astype(str), "t": q["t"], "v": q["f_int_worthy"].astype(float)})
    tmap = d.set_index(["game_id", "play_id"])["t"]
    try:
        c = completion.season_rows(season, d)
        if len(c) and c["cp_ours"].notna().any():
            tt = tmap.reindex(pd.MultiIndex.from_frame(c[["game_id", "play_id"]])).to_numpy()
            out["cpoe"] = pd.DataFrame({"entity": c["passer"].astype(str), "t": tt, "v": c["y"] - c["cp_ours"]})
            r = c[c["receiver"].notna()]
            tr = tmap.reindex(pd.MultiIndex.from_frame(r[["game_id", "play_id"]])).to_numpy()
            out["croe"] = pd.DataFrame({"entity": r["receiver"].astype(str), "t": tr, "v": r["y"] - r["cp_ours"]})
    except Exception:  # noqa: BLE001 - a model without a fit
        pass
    try:
        y = yac.season_rows(season, d)
        if len(y) and y["xyac"].notna().any():
            ty = tmap.reindex(pd.MultiIndex.from_frame(y[["game_id", "play_id"]])).to_numpy()
            out["yacoe"] = pd.DataFrame({"entity": y["receiver"].astype(str), "t": ty, "v": y["yac"] - y["xyac"]})
    except Exception:  # noqa: BLE001
        pass
    try:
        r = ryoe.season_rows(season, d)
        if len(r) and r["xry"].notna().any():
            tr = tmap.reindex(pd.MultiIndex.from_frame(r[["game_id", "play_id"]])).to_numpy()
            out["ryoe_att"] = pd.DataFrame({"entity": r["rusher"].astype(str), "t": tr, "v": r["yards"] - r["xry"]})
            out["rush_success"] = pd.DataFrame({"entity": r["rusher"].astype(str), "t": tr, "v": r["success"]})
    except Exception:  # noqa: BLE001
        pass
    tg = d[d["receiver_player_id"].notna() & (pd.to_numeric(d["pass_attempt"], errors="coerce").fillna(0) == 1)]
    out["epa_target"] = pd.DataFrame({"entity": tg["receiver_player_id"].astype(str), "t": tg["t"], "v": pd.to_numeric(tg["epa"], errors="coerce")})
    sc = d[d["play_type"].astype(str).isin(["pass", "run"]) & d["posteam"].notna()]
    out["team_off_epa"] = pd.DataFrame({"entity": sc["posteam"].astype(str), "t": sc["t"], "v": pd.to_numeric(sc["epa"], errors="coerce")})
    out["team_def_epa"] = pd.DataFrame({"entity": sc["defteam"].astype(str), "t": sc["t"], "v": pd.to_numeric(sc["epa"], errors="coerce")})
    kf = kicking.current_fit()
    if kf and kf.get("ok"):
        fg = d[(d["play_type"].astype(str) == "field_goal") & d["kicker_player_id"].notna()]
        a = kicking.fg_attempts(fg)
        if len(a):
            p = kicking.fg_prob(kf["fg"], a["distance"], a["season"], a["wind"], a["temp"], a["indoor"], a["altitude"])
            ok = d["play_type"].astype(str).eq("field_goal") & d["field_goal_result"].astype(str).isin(["made", "missed", "blocked"]) \
                & pd.to_numeric(d["kick_distance"], errors="coerce").notna() & d["kicker_player_id"].notna()
            out["fgoe"] = pd.DataFrame({"entity": a["kicker"].astype(str).to_numpy(), "t": d.loc[ok, "t"].to_numpy()[:len(a)],
                                        "v": a["made"].to_numpy() - p})
    return out


def split_half_curve(ev: pd.DataFrame, grid=GRID, min_players: int = MIN_PLAYERS) -> list[list[float]]:
    d = ev.dropna()
    if not len(d):
        return []
    d = d.sort_values(["entity", "t"], kind="mergesort")
    d["rank"] = d.groupby("entity").cumcount()
    cnt = d.groupby("entity").size()
    out = []
    for n in grid:
        ok = cnt[cnt >= 2 * n].index
        if len(ok) < min_players:
            break
        s = d[d["entity"].isin(ok) & (d["rank"] < 2 * n)]
        h = s.groupby(["entity", s["rank"] % 2])["v"].mean().unstack()
        r = _io.pearson(h[0], h[1])
        if r is not None:
            out.append([float(n), float(r), int(len(ok))])
    return out


def fit_k(curve: list[list[float]]) -> float | None:
    pts = [(n, r, w) for n, r, w in curve if 0.02 < r < 0.995]
    if not pts:
        return None
    ks = np.logspace(-0.5, 4.5, 500)
    n = np.array([p[0] for p in pts])
    r = np.array([p[1] for p in pts])
    w = np.array([p[2] for p in pts], float)
    err = ((r[None, :] - n[None, :] / (n[None, :] + ks[:, None])) ** 2 * w[None, :]).sum(axis=1)
    return float(ks[int(np.argmin(err))])


def season_stability(season: int, d: pd.DataFrame | None = None) -> dict:
    tabs = event_tables(season, d)
    out = {}
    for m, ev in tabs.items():
        curve = split_half_curve(ev)
        k = fit_k(curve)
        out[m] = {"curve": curve, "k": k, "players": int(max([c[2] for c in curve], default=0))}
    return out


def combine(per: dict[str, dict]) -> dict:
    res = {}
    for m, (ent, desc) in METRICS.items():
        ks, ws = [], []
        for _s, r in per.items():
            x = r.get(m)
            if x and x.get("k"):
                ks.append(x["k"])
                ws.append(max(x.get("players", 1), 1))
        if not ks:
            continue
        k = float(np.exp(np.average(np.log(ks), weights=ws)))
        res[m] = {"k": round(k, 1), "n70": round(k * TARGET / (1 - TARGET), 1), "entity": ent, "label": desc, "seasons": len(ks)}
    return res


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nfl.models import completion, kicking, ryoe, yac
    fits = [(m.current_fit() or {}).get("key") for m in (completion, kicking, ryoe, yac)]
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, fits)
    return _io.cached("stabilise", str(int(season)), key, lambda: season_stability(season), use_cache)


def table(seasons=None) -> dict:
    seasons = _io.season_range(seasons)
    return combine({str(s): for_season(s) for s in seasons})


def shrink_k(metric: str) -> float:
    f = _io.read_fit("stabilise") or {}
    m = (f.get("metrics") or {}).get(metric)
    return float(m["k"]) if m and m.get("k") else DEFAULT_K.get(metric, 200.0)


def point(metric: str) -> float:
    return shrink_k(metric) * TARGET / (1 - TARGET)


def export_fits(seasons=None) -> dict:
    out = {"version": MODEL_VERSION, "target": TARGET, "metrics": table(seasons)}
    _io.write_fit("stabilise", out)
    return out
