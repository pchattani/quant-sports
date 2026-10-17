#!/usr/bin/env python
"""
Fit the models CI cannot fit itself and export them to oddsmarkets/nhl/models/fitted/ (committed by hand).

CI holds only the current season's raw data and derived tables (plus the Actions cache of data/nhl), so every model
that trains on earlier seasons reads its committed fit when the cache is cold (`_io.get_fit`: the cached fit when its
version matches, else models/fitted/):

  builder B   xg, shooting, goalies, onice, rapm (multi-season priors), value, lines, stabilise: models/fit_b.fit_all
              when present, else each module's export_fits(seasons)
  builder C   models/fit_c.fit_all(committed=True, last=through): team-strength carry-over, the walk-forward game fit,
              award models, the season-simulation spread scan and the backtest (docs/rink/data/calibration.json)

Every step is isolated; a failing or missing one is reported and the rest run. Each fit holds one season of events at
a time inside the model code. Run locally after a backfill, at the start of a season, or when a model version moves.

    python scripts/nhl_fit.py                              # everything, through the latest completed season
    python scripts/nhl_fit.py --only b --through 20252026
    python scripts/nhl_fit.py --models xg rapm             # builder B's modules one by one (any C name runs fit_c)
Seasons: --through defaults to the last completed season (canon.current_season), as fit_b and fit_c default to.
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

from oddsmarkets.nhl import analytics as an  # noqa: E402

logger = logging.getLogger("nhl_fit")
B_ORDER = ("xg", "shooting", "goalies", "onice", "rapm", "value", "lines", "stabilise")
C_ORDER = ("team_strength", "game", "live", "season_sim", "awards", "backtest")


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


def export(name: str, seasons: list[int]) -> dict:
    try:
        mod = importlib.import_module(f"oddsmarkets.nhl.models.{name}")
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "skipped": True, "error": f"module not importable: {exc}"}
    f = getattr(mod, "export_fits", None)
    if f is not None:
        def call():
            try:
                return f(seasons)
            except TypeError:
                return f(seasons[-1] if seasons else None)
        return _run(name, call)
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
    ap.add_argument("--through", type=int, default=None, help="fit on seasons through this one (id or start year; default: every completed season)")
    ap.add_argument("--first", type=int, default=an.PBP_FIRST, help="first season (default 20092010)")
    ap.add_argument("--raw", default=None, help="raw root (default RINK_RAW or data/nhl)")
    ap.add_argument("--cache", default=None, help="cache root (default RINK_CACHE or data/nhl/cache)")
    args = ap.parse_args(argv)
    if args.raw:
        an.set_raw_root(args.raw)
    if args.cache:
        an.set_cache_root(args.cache)
    on = [s for s in an.seasons_on_disk() if an.events_path(s).exists()]
    if not on:
        logger.error("no derived events under %s", an.raw_root())
        return 1
    from oddsmarkets.nhl import canon
    through = canon.norm_season(args.through) if args.through else an.prev_season(an.current_season())
    seasons = [s for s in on if args.first <= s <= through]
    logger.info("fitting on %d seasons (%s..%s)", len(seasons), seasons[0] if seasons else None, seasons[-1] if seasons else None)
    report: dict[str, dict] = {}
    b_models = [m for m in B_ORDER if not args.models or m in args.models]
    if "b" in args.only and (not args.models or any(m in B_ORDER for m in args.models)):
        fb = None
        try:
            fb = importlib.import_module("oddsmarkets.nhl.models.fit_b")
        except Exception:                                        # noqa: BLE001
            fb = None
        if fb is not None and getattr(fb, "fit_all", None) is not None and not args.models:
            report["fit_b"] = _run("fit_b", lambda: fb.fit_all(seasons, export=True))
        else:
            for m in b_models:
                report[m] = export(m, seasons)
    if "c" in args.only and (not args.models or any(m in C_ORDER for m in args.models)):
        from oddsmarkets.nhl.models import fit_c
        report["fit_c"] = _run("fit_c", lambda: fit_c.fit_all(committed=True, last=through))
    print(json.dumps(an.clean(report), indent=1, default=str))
    return 0 if all(v.get("ok") for v in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
