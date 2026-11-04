"""
Walk-forward backtest of the ratings (models/ratings.py) and the tournament simulation (models/sim.py).

Round level: each player-round's pre-event rating against the strokes gained it produced. The parameters are chosen
on TRAIN years by the mean squared error of rounds whose player had at least `min_weight` decayed rounds behind the
rating, checked on VALID, and the choice is scored once on the sealed TEST years.
Event level: for each final individual event of the TEST years with its real field and cut rule, the simulated win,
top-10 and make-cut probabilities against the outcomes (log loss), beside the base rates (1/field, 10/field,
cut count/field).
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import asdict

import numpy as np
import pandas as pd

from .. import store
from . import ratings as R
from . import sim

logger = logging.getLogger(__name__)

TRAIN = range(2005, 2020)
VALID = range(2020, 2023)
TEST = range(2023, 2026)
GRID = {"half_life": (120.0, 180.0, 270.0, 365.0, 540.0), "k0": (2.0, 4.0, 6.0, 12.0)}


def round_scores(sg: pd.DataFrame, years: range, min_weight: float = 0.0, pre: pd.DataFrame | None = None) -> dict:
    d = sg[sg["date"].dt.year.isin(list(years))]
    if pre is not None and min_weight > 0:
        d = d.merge(pre[["event", "pid", "weight"]], on=["event", "pid"])
        d = d[d["weight"] >= min_weight]
    err = d["sg"] - d["pre"]
    return {"n": int(len(d)), "mse": float((err ** 2).mean()), "sd": float(err.std()),
            "mse_zero": float((d["sg"] ** 2).mean()), "r": float(np.corrcoef(d["pre"], d["sg"])[0, 1]) if len(d) > 2 else None}


def tune(rounds: pd.DataFrame, grid: dict = GRID, min_weight: float = 10.0) -> pd.DataFrame:
    rows = []
    for hl, k0 in itertools.product(grid["half_life"], grid["k0"]):
        p = R.Params(half_life=hl, k0=k0)
        sg, pre, _ = R.walk(rounds, p)
        tr = round_scores(sg, TRAIN, min_weight, pre)
        va = round_scores(sg, VALID, min_weight, pre)
        allr = round_scores(sg, TRAIN)
        rows.append({**asdict(p), "train_mse": tr["mse"], "valid_mse": va["mse"], "train_mse_all": allr["mse"], "sd": tr["sd"]})
        logger.info("half_life %s k0 %s: train %.4f (all %.4f) valid %.4f", hl, k0, tr["mse"], allr["mse"], va["mse"])
    return pd.DataFrame(rows).sort_values(["train_mse_all", "train_mse"]).reset_index(drop=True)


def _ll(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def events_test(rounds: pd.DataFrame, pre: pd.DataFrame, sd: float, years: range = TEST, tours=("pga",), n: int = 10000) -> dict:
    """Log loss of win / top-10 / make-cut on the final individual events of `years`, model against base rates."""
    rows = []
    for t in tours:
        for y in years:
            ev = store.load_events(t, y)
            res = store.load_table(t, y, "results")
            if not len(res):
                continue
            for eid, e in ev.items():
                if e.get("status") != "final" or e.get("team"):
                    continue
                r = res[res["event"] == eid]
                r = r[r["status"].isin(["finish", "cut"])]
                if len(r) < 30:
                    continue
                f = r.merge(pre[pre["event"] == eid][["pid", "pre"]], on="pid", how="left")
                f["pre"] = f["pre"].fillna(f["pre"].min())
                nr = int(e.get("rounds") or 4)
                cr = int(e.get("cut_round") or 0)
                cc = int(e.get("cut_count") or 0) or len(f)
                out = sim.simulate(f["pre"].to_numpy(), sd, rounds=nr, cut_round=cr, cut_count=cc, n=n, seed=int(eid) % 2**31)
                won = (f["pos"] == 1).to_numpy(dtype=float)
                if won.sum() != 1:
                    continue
                top10 = ((f["pos"] <= 10) & (f["status"] == "finish")).to_numpy(dtype=float)
                made = (f["status"] == "finish").to_numpy(dtype=float)
                N = len(f)
                base_cut = made.mean()
                rows.append({"event": eid, "tour": t, "year": y, "field": N, "cut": cr > 0,
                             "win_m": _ll(out["win"], won), "win_b": _ll(np.full(N, 1 / N), won),
                             "top10_m": _ll(out["top10"], top10), "top10_b": _ll(np.full(N, min(10 / N, 1)), top10),
                             "cut_m": _ll(out["make_cut"], made) if cr else None, "cut_b": _ll(np.full(N, base_cut), made) if cr else None,
                             "fav_won": bool(won[int(np.argmax(out["win"]))])})
    d = pd.DataFrame(rows)
    if not len(d):
        return {"events": 0}
    summ = {"events": int(len(d))}
    for k in ("win", "top10", "cut"):
        m, b = d[f"{k}_m"].dropna(), d[f"{k}_b"].dropna()
        summ[k] = {"model": round(float(m.mean()), 5), "base": round(float(b.mean()), 5), "skill": round(float(1 - m.mean() / b.mean()), 4)}
    summ["favourite_won"] = round(float(d["fav_won"].mean()), 4)
    return summ
