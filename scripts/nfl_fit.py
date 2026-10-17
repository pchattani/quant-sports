#!/usr/bin/env python
"""
Fit the models CI cannot fit itself and export them to oddsmarkets/nfl/models/fitted/ (committed by hand).

CI holds only the current season's play-by-play (plus the Actions cache of data/nfl/raw), so every model that trains on
earlier seasons reads its committed fit when the cache is cold (`_io.get_fit`: the cached fit when its version
matches, else models/fitted/):

  builder B   ep, wp, kicking, completion, yac, ryoe, fourth_down (needs the wp and kicking fits), qb, stabilise
              (each module's export_fits(seasons): LightGBM boosters as <name>_<key>.txt.gz, the rest as <name>.json)
  builder C   fit_c.fit_all(committed=True): team_strength_params.json (carry-over), the walk-forward game fit
              (game_params.json, the canonical one), drive_model.json, awards_fit.json, season_sim_params.json, then the
              backtest (which merges game_model / season_sim into calibration.json)

Every step is isolated; a failing or missing one is reported and the rest run. Each fit holds one season of plays at a
time inside the model code. Run locally after a backfill, at the start of a season, or when a model version moves.

    python scripts/nfl_fit.py                          # everything, through the latest completed season
    python scripts/nfl_fit.py --only b --through 2025
    python scripts/nfl_fit.py --only c
    python scripts/nfl_fit.py --models ep wp fourth_down
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oddsmarkets.nfl import analytics as an  # noqa: E402

logger = logging.getLogger("nfl_fit")
B_ORDER = ("ep", "wp", "kicking", "completion", "yac", "ryoe", "pressure", "player_value", "fourth_down", "qb", "stabilise")
C_ORDER = ("fit_c",)                    # builder C's exporters: team strength, game, drive, awards, season sim, backtest


def _run(name: str, fn) -> dict:
    t = time.time()
    try:
        r = fn()
        logger.info("%s: done in %.0f s", name, time.time() - t)
        return {"ok": True, "s": round(time.time() - t, 1), "result": _summary(r)}
    except Exception as exc:  # noqa: BLE001 - isolated steps
        logger.error("%s failed: %s\n%s", name, exc, traceback.format_exc())
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "s": round(time.time() - t, 1)}


def _summary(r):
    if isinstance(r, dict):
        return {k: (v if isinstance(v, (int, float, str, bool)) or v is None else type(v).__name__) for k, v in list(r.items())[:30]}
    return None if r is None else str(r)[:200]


def export(name: str, seasons: list[int] | None) -> dict:
    try:
        mod = importlib.import_module(f"oddsmarkets.nfl.models.{name}")
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "skipped": True, "error": f"module not importable: {exc}"}
    if name == "fit_c":
        last = max(seasons) if seasons else None
        return _run(name, lambda: mod.fit_all(last=last, committed=True))
    f = getattr(mod, "export_fits", None)
    if f is not None:
        return _run(name, lambda: f(seasons))
    for fn in ("fit_and_save", "export"):
        g = getattr(mod, fn, None)
        if g is not None:
            return _run(name, lambda: g(seasons))
    fp, sp = getattr(mod, "fit_params", None), getattr(mod, "save_params", None)
    if fp is not None and sp is not None:
        return _run(name, lambda: sp(fp(seasons), committed=True))
    return {"ok": True, "skipped": True, "note": "no export function (nothing to commit)"}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=("b", "c"), default=["b", "c"])
    ap.add_argument("--models", nargs="+", default=None, help="only these model modules")
    ap.add_argument("--through", type=int, default=None, help="fit on seasons through this one (default: every completed season)")
    ap.add_argument("--first", type=int, default=an.FIRST_SEASON, help="first season (default 1999)")
    ap.add_argument("--raw", default=None, help="raw root (default GRIDIRON_RAW or data/nfl)")
    ap.add_argument("--cache", default=None, help="cache root (default GRIDIRON_CACHE or data/nfl/cache)")
    args = ap.parse_args(argv)
    if args.raw:
        an.set_raw_root(args.raw)
    if args.cache:
        an.set_cache_root(args.cache)
    on = an.pbp_seasons()
    if not on:
        logger.error("no play-by-play under %s", an.raw_root())
        return 1
    through = args.through or (an.current_season() - 1)
    seasons = [s for s in on if args.first <= s <= through]
    logger.info("fitting on %d seasons (%s..%s)", len(seasons), seasons[0] if seasons else None, seasons[-1] if seasons else None)
    order = ([m for m in B_ORDER] if "b" in args.only else []) + ([m for m in C_ORDER] if "c" in args.only else [])
    if args.models:
        order = [m for m in order if m in args.models] + [m for m in args.models if m not in order]
    report = {m: export(m, seasons) for m in order}
    print(json.dumps(an.clean(report), indent=1, default=str))
    return 0 if all(v.get("ok") for v in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
