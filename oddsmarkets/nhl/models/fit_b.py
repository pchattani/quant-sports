"""
Builder B's fitting entry point: fit the play-level models in dependency order and (optionally) commit the fits
to models/fitted/ for CI (where the cache is cold).

    fit_all(seasons=None, export=True) -> {"timings": {...}, "summaries": {...}}

Order: xG (cross-fitted by season) -> stabilisation (split-half k per metric; needs xG) -> RAPM prior (the last
season's estimates, the next season's ridge centres) -> Rink value's box prior and Pythagorean exponent.
`python -m oddsmarkets.nhl.models.fit_b [season ...]` (ids 20252026 or start years 2025, as canon); with no seasons, every
completed season on disk (`_io.completed_seasons`, the current season excluded), the same set as scripts/nhl_fit.py.
"""
from __future__ import annotations

import time

from oddsmarkets.nhl.models import _io, rapm, stabilise, value, xg


def fit_all(seasons=None, export: bool = True, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    timings, summaries = {}, {}
    t = time.time()
    f = xg.fit(seasons, use_cache=use_cache)
    if export and f.get("ok"):
        _io.export_fit("xg", f)
    timings["xg"] = round(time.time() - t, 1)
    summaries["xg"] = {k: v for k, v in f.items() if k in ("ok", "seasons", "platt", "best_iter", "importance", "validation")}
    t = time.time()
    summaries["stabilise"] = stabilise.export_fits(seasons) if export else {"metrics": stabilise.table(seasons)}
    timings["stabilise"] = round(time.time() - t, 1)
    t = time.time()
    summaries["rapm_prior"] = rapm.export_fits(max(seasons)) if export and seasons else {}
    timings["rapm"] = round(time.time() - t, 1)
    t = time.time()
    summaries["value"] = value.export_fits() if export else value.box_model()
    timings["value"] = round(time.time() - t, 1)
    return {"timings": timings, "summaries": summaries}


if __name__ == "__main__":       # pragma: no cover
    import json
    import sys
    yrs = [_io.sid(a) for a in sys.argv[1:]] or None
    r = fit_all(yrs)
    print(json.dumps(r["timings"], indent=1))
