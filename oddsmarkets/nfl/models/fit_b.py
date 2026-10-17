"""
Builder B's fitting entry point: fit every play-level model in dependency order and (optionally) commit
the fits to models/fitted/ for CI.

    fit_all(seasons, export=True) -> {"timings": {...}, "summaries": {...}}

Order: EP -> WP -> kicking (FG, PAT, punts) -> fourth down (conversion, go propensity) -> completion ->
YAC -> RYOE -> stabilisation (needs the residual models) -> QB composite (needs CPOE and stabilisation).
Completed seasons only should be passed for fitting; the current season is predicted by the production
fits through each module's for_season.
"""
from __future__ import annotations

import time

from oddsmarkets.nfl.models import _io, completion, ep, fourth_down, kicking, qb, ryoe, stabilise, wp, yac

STEPS = [("ep", ep), ("wp", wp), ("kicking", kicking), ("fourth_down", fourth_down), ("completion", completion),
         ("yac", yac), ("ryoe", ryoe)]


def fit_all(seasons=None, export: bool = True, only: list[str] | None = None, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    timings, summaries = {}, {}
    for name, mod in STEPS:
        if only and name not in only:
            continue
        t = time.time()
        f = mod.fit(seasons, use_cache=use_cache)
        if export:
            _io.export_fit(name, f)
        timings[name] = round(time.time() - t, 1)
        summaries[name] = {k: v for k, v in f.items() if k not in ("models", "folds")}
    if not only or "stabilise" in only:
        t = time.time()
        summaries["stabilise"] = stabilise.export_fits(seasons) if export else {"metrics": stabilise.table(seasons)}
        timings["stabilise"] = round(time.time() - t, 1)
    if not only or "qb" in only:
        t = time.time()
        f = qb.fit(seasons)
        if export:
            _io.write_fit("qb", f)
        summaries["qb"] = f
        timings["qb"] = round(time.time() - t, 1)
    return {"timings": timings, "summaries": summaries}


if __name__ == "__main__":       # pragma: no cover
    import json
    import sys
    yrs = [int(a) for a in sys.argv[1:]] or None
    r = fit_all(yrs)
    print(json.dumps(r["timings"], indent=1))
