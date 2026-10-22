#!/usr/bin/env python
"""
Walk-forward tuning of the race simulator's constants (oddsmarkets/f1/models/race_sim.py).

1. ``prep``: for every Grand Prix in the seasons asked for, the parts of the race inputs that do not depend on
   the tunable constants (``race_sim.race_components``: entry list, circuit profile and reference lap, raw
   results observations, the decomposition's pace, the actual grid and the qualifying model's grid
   distribution), computed from data strictly before the race and pickled per race under
   ``data/f1/cache/tune/<year>_<round>.pkl`` with the race's outcomes.
2. ``grid``: every configuration in a JSON list of constant overrides is simulated for every race (common
   random numbers: one seed per race), before qualifying (with and without the decomposition) and after,
   and scored (winner log-loss, binary log-loss per event). Races are processed one at a time in worker
   processes; nothing but the scores is kept.
3. ``select``: walk-forward choice: for each season Y the configuration with the lowest mean winner log-loss
   over the races of the seasons before Y (from ``--burn-in`` on) is scored on season Y; the production
   choice is the configuration that is best over every season, written to
   ``oddsmarkets/f1/models/fitted/race_params.json`` with ``--write``.

    python scripts/f1_tune.py prep --from 2012 --to 2026
    python scripts/f1_tune.py grid --configs configs.json --sims 2000 --out data/f1/cache/tune_grid.json
    python scripts/f1_tune.py select --grid data/f1/cache/tune_grid.json --first 2014 [--write]
    python scripts/f1_tune.py wintemp --grid data/f1/cache/tune_grid.json --config <id> [--write]

4. ``wintemp``: the post-qualifying win temperature table (``race_sim.WIN_TEMP_POST``): per race, T fitted on every
   earlier race of the grid's configuration (walk-forward), plus "latest" over all races.
5. ``spread``: the post-qualifying strength scale table (``race_sim.PACE_SPREAD_POST``) from a grid of fixed scales
   (configs ``{"id": "s1.3", "PACE_SPREAD_POST": {"latest": 1.3}}``, post only): per race, s minimising a weighted
   sum of the earlier races' winner log-loss (interpolated in log s between the grid's scales); the memory rule
   (``SPREAD_RULES``) is chosen on the dev seasons (``--report``) and written with ``--rule <name> --write``.

    python scripts/f1_tune.py spread --grid spread_grid.json --report
    python scripts/f1_tune.py spread --grid spread_grid.json --rule <name> --write

The refit order after any model change: ``spread`` (when the scale grid is rerun), ``grid`` with the production
configuration, ``wintemp``, then the official backtest.
"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import os
import pickle
import sys

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):   # one BLAS thread per worker process
    os.environ.setdefault(_v, "1")
import time
import warnings
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

logger = logging.getLogger("f1_tune")
TUNE = ROOT / "data" / "f1" / "cache" / "tune"
VARIANTS = ("pre", "post", "pre_results_only")
EPS = 1e-4


# ----------------------------------------------------------------------------------------------- prep

def _prep_season(year: int) -> tuple[int, int, float]:
    warnings.filterwarnings("ignore")
    from oddsmarkets.f1.models import backtest as bt
    from oddsmarkets.f1.models import race_sim as rs
    t0 = time.perf_counter()
    TUNE.mkdir(parents=True, exist_ok=True)
    n = 0
    for r, race in bt._season_races(year):
        oc = bt._outcomes(race)
        if len(oc) < 2:
            continue
        try:
            comp = rs.race_components(year, r, before_quali=True, use_a=True)
            post = rs.race_components(year, r, before_quali=False, use_a=False)
        except Exception as exc:                                      # one bad race must not stop the run
            logger.warning("%s/%s: %s", year, r, exc)
            continue
        comp["grid_actual"] = post["grid"]
        comp["quali_pace_actual"] = post.get("quali_pace")
        comp["outcomes"] = oc
        with open(TUNE / f"{year}_{r}.pkl", "wb") as fh:
            pickle.dump(comp, fh, protocol=pickle.HIGHEST_PROTOCOL)
        n += 1
        del comp, post
    gc.collect()
    return year, n, round(time.perf_counter() - t0, 1)


# ----------------------------------------------------------------------------------------------- grid

def _variant_inputs(rs, comp: dict, variant: str):
    c = dict(comp)
    if variant == "post":
        c["grid"], c["grid_dist"] = comp["grid_actual"], None
        c["quali_pace"] = comp.get("quali_pace_actual")       # absent from pickles made before October 2026
    elif variant == "pre_results_only":
        c["a"], c["grid_dist"], c["grid"] = None, None, None
    else:
        c["grid"] = None
    return rs.inputs_from_components(c)


def score_race(res_drivers: dict, oc: dict) -> dict:
    """Winner log-loss and binary log-loss sums for one race's forecast."""
    drivers = list(oc)
    N = len(drivers)
    pw = np.array([float((res_drivers.get(d) or {}).get("p_win", 1.0 / N)) for d in drivers])
    winner = next((i for i, d in enumerate(drivers) if oc[d]["win"]), None)
    out = {"ll": {}, "pw": [round(float(x), 5) for x in pw], "win": [oc[d]["win"] for d in drivers],
           "pp": [round(float((res_drivers.get(d) or {}).get("p_podium", 0.0)), 5) for d in drivers],
           "pod": [int(oc[d]["podium"]) for d in drivers]}
    s = pw.sum()
    out["wll"] = -math.log(max(pw[winner] / s if s > 0 else 0.0, EPS)) if winner is not None else None
    for e, key in (("win", "p_win"), ("podium", "p_podium"), ("points", "p_points"), ("dnf", "p_dnf")):
        p = np.clip(np.array([float((res_drivers.get(d) or {}).get(key, 0.0)) for d in drivers]), EPS, 1 - EPS)
        y = np.array([oc[d][e] for d in drivers], float)
        out["ll"][e] = [float(-np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))), int(N)]
    return out


def _grid_chunk(args: tuple) -> dict:
    files, configs, sims, variants = args
    warnings.filterwarnings("ignore")
    from oddsmarkets.f1.models import race_sim as rs
    base = {k: getattr(rs, k) for cfg in configs for k in cfg if k != "id"}
    out: dict = {}
    for f in files:
        with open(f, "rb") as fh:
            comp = pickle.load(fh)
        key = f"{comp['year']}_{comp['round']}"
        seed = 1000 * comp["year"] + comp["round"]
        for cfg in configs:
            rs.set_params(**{k: v for k, v in base.items()})
            rs.set_params(**{k: (tuple(v) if isinstance(base.get(k), tuple) else v) for k, v in cfg.items() if k != "id"})
            for v in variants:
                if v == "post" and not comp.get("grid_actual"):
                    continue
                inp = _variant_inputs(rs, comp, v)
                res = rs.simulate_race(inp, n=sims, seed=seed)
                out.setdefault(cfg["id"], {}).setdefault(v, {})[key] = score_race(res["drivers"], comp["outcomes"])
                del res, inp
        del comp
        gc.collect()
    rs.set_params(**base)
    return out


def run_grid(configs: list[dict], sims: int, seasons: list[int], workers: int, variants=VARIANTS) -> dict:
    files = sorted(p for p in TUNE.glob("*.pkl") if int(p.stem.split("_")[0]) in seasons)
    chunks = [files[i::workers * 3] for i in range(workers * 3)]
    merged: dict = {}
    with Pool(workers, maxtasksperchild=4) as pool:
        for part in pool.imap_unordered(_grid_chunk, [(c, configs, sims, variants) for c in chunks if c]):
            for cid, vv in part.items():
                for v, races in vv.items():
                    merged.setdefault(cid, {}).setdefault(v, {}).update(races)
    return merged


# ----------------------------------------------------------------------------------------------- select

def summarise(grid: dict, cid: str, variant: str, seasons: list[int] | None = None) -> dict:
    races = {k: v for k, v in (grid.get(cid, {}).get(variant) or {}).items() if seasons is None or int(k.split("_")[0]) in seasons}
    wl = [v["wll"] for v in races.values() if v.get("wll") is not None]
    ll = {}
    for e in ("win", "podium", "points", "dnf"):
        s = sum(v["ll"][e][0] for v in races.values())
        n = sum(v["ll"][e][1] for v in races.values())
        ll[e] = round(s / n, 5) if n else None
    return {"races": len(races), "winner_ll": round(float(np.mean(wl)), 4) if wl else None, "ll": ll}


def walk_forward(grid: dict, variant: str, first: int, burn_in: int) -> dict:
    """Per season Y >= first: the config best on seasons [burn_in, Y) is scored on Y."""
    seasons = sorted({int(k.split("_")[0]) for cid in grid for k in (grid[cid].get(variant) or {})})
    picks, rows = {}, []
    for y in seasons:
        if y < first:
            continue
        train = [s for s in seasons if burn_in <= s < y]
        best = min(grid, key=lambda c: summarise(grid, c, variant, train)["winner_ll"] or 9e9)
        picks[y] = best
        rows += [v for k, v in grid[best][variant].items() if int(k.split("_")[0]) == y]
    wl = [v["wll"] for v in rows if v.get("wll") is not None]
    return {"picks": picks, "winner_ll": round(float(np.mean(wl)), 4) if wl else None, "races": len(rows)}


def win_temp_table(grid: dict, cid: str, variant: str = "post", min_races: int = 20) -> dict:
    """Walk-forward win temperature: for every race, the T minimising the winner log-loss of p^T (renormalised)
    over all earlier races of the grid (1.0 until ``min_races`` are available); "latest" over every race."""
    from scipy.optimize import minimize_scalar
    races = grid[cid][variant]
    keys = sorted((k for k in races if races[k].get("wll") is not None and sum(races[k]["win"]) == 1),
                  key=lambda k: tuple(int(x) for x in k.split("_")))

    def fit(ks):
        lv = [(np.log(np.clip(np.array(races[k]["pw"], float), 1e-6, None)), races[k]["win"].index(1)) for k in ks]

        def f(t):
            return sum(-(t * v[w] - np.log(np.sum(np.exp(t * v)))) for v, w in lv)
        return round(float(minimize_scalar(f, bounds=(0.5, 3.0), method="bounded").x), 4)
    out = {k: (fit(keys[:i]) if i >= min_races else 1.0) for i, k in enumerate(keys)}
    out["latest"] = fit(keys)
    return out


# ----------------------------------------------------------------------------------------------- spread

# Memory rules for the walk-forward strength scale, pre-registered 21 Oct 2026 (round 2 of the model program): weights
# on the earlier races (``hl``: half-life in races; ``scope``: "all", "reg" = same regulation set, "season") plus K
# pseudo-races of the expanding-window mean curve (shrinkage toward the all-history fit).
SPREAD_RULES = {
    "expanding": {"scope": "all", "hl": None, "K": 0},
    **{f"hl{h}_K{k}": {"scope": "all", "hl": h, "K": k} for h in (6, 12, 24) for k in (5, 20)},
    **{f"reg_K{k}": {"scope": "reg", "hl": None, "K": k} for k in (5, 20)},
    **{f"season_K{k}": {"scope": "season", "hl": None, "K": k} for k in (5, 20)},
}
SPREAD_FINE = np.round(np.arange(0.8, 2.8001, 0.01), 2)
SPREAD_MIN_RACES = 20


def _reg_set(year: int) -> int:
    from oddsmarkets.f1.models import race_sim as rs
    starts = [y for y in rs.REG_RESET if y <= int(year)]
    return max(starts) if starts else 0


def spread_curves(grid: dict, variant: str = "post") -> tuple[list[str], np.ndarray]:
    """Races (chronological) and their winner log-loss on SPREAD_FINE, interpolated in log s from the grid's
    fixed-scale configurations (every config must carry PACE_SPREAD_POST {"latest": s})."""
    scales = {}
    for cid, vv in grid["grid"].items():
        cfg = next(c for c in grid["configs"] if c["id"] == cid)
        scales[float(cfg["PACE_SPREAD_POST"]["latest"])] = vv.get(variant) or {}
    ss = sorted(scales)
    keys = sorted(set.intersection(*[{k for k, v in scales[s].items() if v.get("wll") is not None and sum(v["win"]) == 1}
                                     for s in ss]), key=lambda k: tuple(int(x) for x in k.split("_")))
    L = np.array([[scales[s][k]["wll"] for s in ss] for k in keys])
    Lf = np.array([np.interp(np.log(SPREAD_FINE), np.log(ss), row) for row in L])
    return keys, Lf


def spread_table(keys: list[str], Lf: np.ndarray, rule: dict) -> dict:
    """Walk-forward scale per race under ``rule`` (1.0 while fewer than SPREAD_MIN_RACES earlier races), plus
    "latest" (every race, for rounds after the fit)."""
    yrs = np.array([int(k.split("_")[0]) for k in keys])
    regs = np.array([_reg_set(y) for y in yrs])

    def pick(k: int, year: int) -> float:
        if k < SPREAD_MIN_RACES:
            return 1.0
        prev = Lf[:k]
        if rule["scope"] == "season":
            w = (yrs[:k] == year).astype(float)
        elif rule["scope"] == "reg":
            w = (regs[:k] == _reg_set(year)).astype(float)
        else:
            w = np.ones(k)
        if rule.get("hl"):
            w = w * 0.5 ** ((k - 1 - np.arange(k)) / float(rule["hl"]))
        obj = w @ prev + float(rule.get("K") or 0) * prev.mean(0)
        if not np.any(obj):
            return 1.0
        return float(SPREAD_FINE[int(np.argmin(obj))])
    out = {k: pick(i, int(yrs[i])) for i, k in enumerate(keys)}
    out["latest"] = pick(len(keys), int(yrs[-1]))
    return out


def spread_score(keys: list[str], Lf: np.ndarray, tab: dict, seasons) -> float:
    """Mean interpolated winner log-loss over ``seasons`` with each race at its table scale."""
    idx = {float(s): i for i, s in enumerate(SPREAD_FINE)}
    v = [Lf[i, idx[round(tab[k], 2)]] for i, k in enumerate(keys) if int(k.split("_")[0]) in seasons]
    return float(np.mean(v)) if v else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("prep")
    p1.add_argument("--from", dest="start", type=int, default=2012)
    p1.add_argument("--to", dest="end", type=int, default=datetime.now(timezone.utc).year)
    p1.add_argument("--workers", type=int, default=8)
    p2 = sub.add_parser("grid")
    p2.add_argument("--configs", required=True)
    p2.add_argument("--sims", type=int, default=2000)
    p2.add_argument("--from", dest="start", type=int, default=2012)
    p2.add_argument("--to", dest="end", type=int, default=datetime.now(timezone.utc).year)
    p2.add_argument("--workers", type=int, default=8)
    p2.add_argument("--variants", default=",".join(VARIANTS))
    p2.add_argument("--out", required=True)
    p3 = sub.add_parser("select")
    p3.add_argument("--grid", required=True)
    p3.add_argument("--first", type=int, default=2014)
    p3.add_argument("--burn-in", type=int, default=2012)
    p3.add_argument("--write", action="store_true")
    p4 = sub.add_parser("wintemp", help="walk-forward post-qualifying win temperature table -> race_params.json")
    p4.add_argument("--grid", required=True)
    p4.add_argument("--config", required=True)
    p4.add_argument("--write", action="store_true")
    p5 = sub.add_parser("spread", help="walk-forward post-qualifying strength scale table -> race_params.json")
    p5.add_argument("--grid", required=True)
    p5.add_argument("--report", action="store_true", help="dev-season score of every memory rule")
    p5.add_argument("--dev", default="2014-2022")
    p5.add_argument("--rule", default=None)
    p5.add_argument("--write", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "prep":
        with Pool(args.workers, maxtasksperchild=1) as pool:
            for y, n, s in pool.imap_unordered(_prep_season, range(args.start, args.end + 1)):
                logger.info("prep %d: %d races (%.1f s)", y, n, s)
        return 0
    if args.cmd == "grid":
        configs = json.loads(Path(args.configs).read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        g = run_grid(configs, args.sims, list(range(args.start, args.end + 1)), args.workers, tuple(args.variants.split(",")))
        Path(args.out).write_text(json.dumps({"configs": configs, "sims": args.sims, "grid": g}), encoding="utf-8")
        logger.info("grid: %d configs in %.0f s", len(configs), time.perf_counter() - t0)
        for c in configs:
            logger.info("%s %s", c["id"], {v: summarise(g, c["id"], v)["winner_ll"] for v in VARIANTS if v in g.get(c["id"], {})})
        return 0
    d = json.loads(Path(args.grid).read_text(encoding="utf-8"))
    g, configs = d["grid"], {c["id"]: c for c in d["configs"]}
    if args.cmd == "spread":
        keys, Lf = spread_curves(d)
        a, b = (int(x) for x in args.dev.split("-"))
        dev = range(a, b + 1)
        if args.report:
            print(f"dev {a}-{b}: s = 1 everywhere {spread_score(keys, Lf, {k: 1.0 for k in keys}, dev):.4f}")
            for name, rule in SPREAD_RULES.items():
                tab = spread_table(keys, Lf, rule)
                dv = [tab[k] for k in keys if int(k.split("_")[0]) in dev]
                print(f"{name:12s} dev {spread_score(keys, Lf, tab, dev):.4f}  s mean {np.mean(dv):.2f} "
                      f"[{min(dv):.2f}, {max(dv):.2f}]")
        if args.rule:
            tab = spread_table(keys, Lf, SPREAD_RULES[args.rule])
            if args.write:
                out = ROOT / "oddsmarkets" / "f1" / "models" / "fitted" / "race_params.json"
                fitted = json.loads(out.read_text(encoding="utf-8"))
                fitted.setdefault("params", {})["PACE_SPREAD_POST"] = {k: v for k, v in tab.items()
                                                                       if k == "latest" or int(k[:4]) >= 2014}
                fitted["pace_spread_post"] = {
                    "fitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "grid": Path(args.grid).name,
                    "rule": args.rule, **SPREAD_RULES[args.rule], "sims": d.get("sims"), "races": len(keys),
                    "method": "per race, s minimising sum_j w_j LL_j(s) + K mean_j LL_j(s) over earlier races j "
                              "(winner log-loss interpolated in log s between fixed-scale simulations; 1.0 for the "
                              "first 20); rule chosen on 2014-2022; latest = all races"}
                out.write_text(json.dumps(fitted, indent=1), encoding="utf-8")
                print("wrote", out)
        return 0
    if args.cmd == "wintemp":
        tab = win_temp_table(g, args.config)
        print(json.dumps({k: v for k, v in tab.items() if k == "latest" or k.startswith("2026")}))
        if args.write:
            out = ROOT / "oddsmarkets" / "f1" / "models" / "fitted" / "race_params.json"
            fitted = json.loads(out.read_text(encoding="utf-8"))
            fitted.setdefault("params", {})["WIN_TEMP_POST"] = tab
            fitted["win_temp_post"] = {"fitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "grid": Path(args.grid).name, "config": args.config, "sims": d.get("sims"),
                                       "races": len(tab) - 1,
                                       "method": "per race, T minimising the winner log-loss of p^T over every earlier "
                                                 "race of the grid (1.0 for the first 20); latest = all races"}
            out.write_text(json.dumps(fitted, indent=1), encoding="utf-8")
            print("wrote", out)
        return 0
    report = {}
    for v in VARIANTS:
        if not any(v in g[c] for c in g):
            continue
        wf = walk_forward(g, v, args.first, args.burn_in)
        seasons = sorted({int(k.split("_")[0]) for c in g for k in (g[c].get(v) or {})})
        best = min(g, key=lambda c: summarise(g, c, v, [s for s in seasons if s >= args.burn_in])["winner_ll"] or 9e9)
        report[v] = {"walk_forward": wf, "best_overall": best, "best_summary": summarise(g, best, v)}
        print(v, json.dumps(report[v]))
    if args.write:
        best = report["post"]["best_overall"]
        cfg = {k: v for k, v in configs[best].items() if k != "id"}
        out = ROOT / "oddsmarkets" / "f1" / "models" / "fitted" / "race_params.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"fitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "config": best,
                                   "params": cfg, "selection": report}, indent=1), encoding="utf-8")
        print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
