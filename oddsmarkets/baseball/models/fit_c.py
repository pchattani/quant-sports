"""
Builder C's committed fits in one call (for scripts/mlb_fit.py): each module's `export_fits` writes to
models/fitted/. One season of pitches is loaded at a time inside each step; a failing step is recorded
and the rest continue.

    re24_<level>.json, re24_retro.json   RE matrices, linear and wOBA weights, count values, WE table
    xwoba_<level>.txt.gz + .json          LightGBM multiclass model, features, rake, class weights
    catchprob_<level>.txt.gz + .json      LightGBM catch model, start-position tables
    framing_<level>.json                  called-strike surface, count/family/hands coefficients
    parks_<level>.json                    multi-year park factors, dimension and weather effects
    stabilise_<level>.json                split-half k and n_0.7 per metric
    war_constants.json                    WAR constants
"""
from __future__ import annotations

import time
import traceback


def export_fits(level: str = "mlb", season: int | None = None, retro: bool = True) -> dict:
    from oddsmarkets.baseball.models import catchprob, framing, parks, re24, stabilise, war, xwoba
    steps = [("re24", lambda: re24.export_fits(level, retro=retro)),
             ("xwoba", lambda: xwoba.export_fits(level, season)),
             ("catchprob", lambda: catchprob.export_fits(level, season)),
             ("framing", lambda: framing.export_fits(level, season)),
             ("parks", lambda: parks.export_fits(level, season)),
             ("stabilise", lambda: stabilise.export_fits(level)),
             ("war", lambda: war.export_fits(level))]
    out = {}
    for name, f in steps:
        t = time.time()
        try:
            r = f()
            out[name] = {"ok": bool(r.get("ok", True)) if isinstance(r, dict) else True, "s": round(time.time() - t, 1)}
        except Exception as exc:  # noqa: BLE001 - isolated steps
            out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=3)}
    return out
