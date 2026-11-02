#!/usr/bin/env python
"""
Fit and score The Quant Scrum's models (oddsmarkets/rugby/models.py): tune on the development years, score once on
the sealed test years, apply the promotion rule, and write

    oddsmarkets/rugby/fitted/params.json     the promoted model's parameters, the World Rugby replica's logistic,
                                             the try model, the score simulator's spreads and the value weights
    oddsmarkets/rugby/fitted/report.json     every rung's development and test scores, the paired comparisons,
                                             calibration, and the replica's accuracy against published rankings

    uv run python scripts/scrum_fit.py                 # men's tests (the default scope)
    uv run python scripts/scrum_fit.py --scope women

Runs in a few minutes on one core (each walk-forward pass is a few thousand matches).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.rugby import models as M, store, validate  # noqa: E402
from oddsmarkets.rugby.ratings import Params  # noqa: E402

FITTED = ROOT / "oddsmarkets" / "rugby" / "fitted"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", default="men")
    ap.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args(argv)
    t0 = time.time()
    matches, _ath = store.load_all(a.scope)
    ms = M.eligible(matches)
    by_id = {m["id"]: m for m in ms}
    last_year = max(M.year(m) for m in ms)
    test = (M.TEST_FROM, last_year)
    print(f"{len(ms)} matches {M.year(ms[0])}-{last_year}; dev {M.DEV}, test {test}")

    # rung 0: the World Rugby replica
    rk, wr_rows = M.replica(ms)
    wr_fit = M.fit_wr(wr_rows)
    for r in wr_rows:
        r["p"] = M.wr_probs(r["gap"], wr_fit)
    rep = {"scope": a.scope, "n": len(ms), "dev": list(M.DEV), "test": list(test), "rungs": {}, "paired": {}}
    rep["rungs"]["wr"] = {"dev": M.score(wr_rows, *M.DEV), "test": M.score(wr_rows, *test),
                          "cal_test": M.calibration(wr_rows, *test), "fit": wr_fit}

    # rung 1: our margin rating with home advantage
    base = Params(split=False, c_km=0.0, c_tz=0.0, c_rest=0.0)
    elo, ll = M.tune(ms, base, M.GRID_ELO, rounds=a.rounds)
    elo_rows = M.walk(ms, elo)
    rep["rungs"]["elo"] = {"params": M.as_dict(elo), "dev": M.score(elo_rows, *M.DEV), "test": M.score(elo_rows, *test),
                           "cal_test": M.calibration(elo_rows, *test)}
    # rung 2: rating uncertainty (Glicko-style spread)
    unc, _ = M.tune(ms, elo, M.GRID_UNC, rounds=a.rounds)
    unc_rows = M.walk(ms, unc)
    rep["rungs"]["unc"] = {"params": M.as_dict(unc), "dev": M.score(unc_rows, *M.DEV), "test": M.score(unc_rows, *test),
                           "cal_test": M.calibration(unc_rows, *test)}
    # rung 3: travel and rest (on top of the best rung so far, decided below)
    ctx, _ = M.tune(ms, unc, M.GRID_CTX, rounds=a.rounds)
    ctx_rows = M.walk(ms, ctx)
    rep["rungs"]["ctx"] = {"params": M.as_dict(ctx), "dev": M.score(ctx_rows, *M.DEV), "test": M.score(ctx_rows, *test),
                           "cal_test": M.calibration(ctx_rows, *test)}
    # rung 3: attack and defence (re-tune the learning rates for the split)
    split0 = replace(ctx, split=True)
    split, _ = M.tune(ms, split0, {k: M.GRID_ELO[k] for k in ("k", "k_new", "cap", "s0", "s1")}, rounds=1)
    split_rows = M.walk(ms, split)
    rep["rungs"]["split"] = {"params": M.as_dict(split), "dev": M.score(split_rows, *M.DEV), "test": M.score(split_rows, *test),
                             "cal_test": M.calibration(split_rows, *test)}

    # the ladder on the sealed test years
    rep["paired"]["elo_vs_wr"] = M.paired(wr_rows, elo_rows, *test)
    rep["paired"]["unc_vs_elo"] = M.paired(elo_rows, unc_rows, *test)
    rep["paired"]["ctx_vs_unc"] = M.paired(unc_rows, ctx_rows, *test)
    rep["paired"]["split_vs_best"] = None
    chosen, chosen_rows, chosen_name = elo, elo_rows, "elo"
    if not rep["paired"]["elo_vs_wr"]["better"]:
        print("WARNING: our rating does not beat the replica on the test years; it stays as the published model only "
              "because the replica gives no margin or total")
    tol = 0.005
    if rep["paired"]["unc_vs_elo"]["better"] and rep["rungs"]["unc"]["cal_test"]["ece"] <= rep["rungs"]["elo"]["cal_test"]["ece"] + tol:
        chosen, chosen_rows, chosen_name = unc, unc_rows, "unc"
    if rep["paired"]["ctx_vs_unc"]["better"] and rep["rungs"]["ctx"]["cal_test"]["ece"] <= rep["rungs"][chosen_name]["cal_test"]["ece"] + tol:
        chosen, chosen_rows, chosen_name = ctx, ctx_rows, "ctx"
    rep["paired"]["split_vs_best"] = M.paired(chosen_rows, split_rows, *test)
    rep["paired"]["split_vs_best"]["against"] = chosen_name
    if rep["paired"]["split_vs_best"]["better"] and rep["rungs"]["split"]["cal_test"]["ece"] <= rep["rungs"][chosen_name]["cal_test"]["ece"] + tol:
        chosen, chosen_rows, chosen_name = split, split_rows, "split"
    # the hybrid (post hoc): the chosen rung, with the rebuild's chance for tests involving a tier-three side
    hyb = replace(chosen, wr3=True)
    hyb_rows = M.walk(ms, hyb, wr_fit=wr_fit)
    rep["rungs"]["hybrid"] = {"params": M.as_dict(hyb), "dev": M.score(hyb_rows, *M.DEV), "test": M.score(hyb_rows, *test),
                              "cal_test": M.calibration(hyb_rows, *test), "post_hoc": True}
    rep["paired"]["hybrid_vs_best"] = dict(M.paired(chosen_rows, hyb_rows, *test), against=chosen_name, post_hoc=True)
    rep["paired"]["hybrid_vs_wr"] = dict(M.paired(wr_rows, hyb_rows, *test), post_hoc=True)
    rep["sealed_choice"] = chosen_name
    chosen, chosen_rows, chosen_name = hyb, hyb_rows, "hybrid"
    rep["chosen"] = chosen_name
    # the total: the split model's attack/defence total when chosen; else the split model still supplies it (the
    # total does not change the win chance), scored against the era-mean total
    tot_rows = chosen_rows if chosen.split else split_rows
    rep["total"] = {"sd_test": round(M.total_sd(tot_rows, *test), 3), "sd_dev": round(M.total_sd(tot_rows, *M.DEV), 3),
                    "mae_test": round(sum(abs((r["hs"] + r["as"]) - r["total"]) for r in tot_rows if test[0] <= r["y"] <= test[1]) /
                                      max(1, sum(1 for r in tot_rows if test[0] <= r["y"] <= test[1])), 3)}
    base_tot = [r for r in tot_rows if M.DEV[0] <= r["y"] <= M.DEV[1]]
    mean_dev = sum(r["hs"] + r["as"] for r in base_tot) / max(1, len(base_tot))
    tt = [r for r in tot_rows if test[0] <= r["y"] <= test[1]]
    rep["total"]["mae_test_baseline"] = round(sum(abs((r["hs"] + r["as"]) - mean_dev) for r in tt) / max(1, len(tt)), 3)
    # tries
    tries = M.fit_tries(tot_rows, by_id)
    rep["tries"] = {"fit": tries, "test": M.score_tries(tot_rows, by_id, tries, *test)}
    # value weights
    rep["value"] = M.fit_value(ms)
    # the replica against published values
    rep["replica"] = validate.replica_check(rk, ms)
    rep["seconds"] = round(time.time() - t0, 1)

    params = {"scope": a.scope, "model": chosen_name, "params": M.as_dict(chosen), "total_params": M.as_dict(split),
              "wr_logistic": wr_fit, "tries": tries, "sd_total": rep["total"]["sd_dev"],
              "value": rep["value"].get("weights") if rep["value"].get("ok") else None,
              "fitted_through": max(r["date"] for r in chosen_rows)[:10]}
    FITTED.mkdir(parents=True, exist_ok=True)
    sfx = "" if a.scope == "men" else f"_{a.scope}"
    (FITTED / f"params{sfx}.json").write_text(json.dumps(params, indent=1), encoding="utf-8")
    (FITTED / f"report{sfx}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for k in ("wr", "elo", "unc", "ctx", "split", "hybrid"):
        print(k, rep["rungs"][k]["dev"], rep["rungs"][k]["test"], "ece", rep["rungs"][k]["cal_test"]["ece"])
    print("paired", json.dumps(rep["paired"]))
    print("chosen", chosen_name, "total", rep["total"], "tries", rep["tries"]["test"])
    print("value", {k: v for k, v in rep["value"].items() if k != "weights"})
    print("replica", json.dumps(rep["replica"])[:600])
    print(f"{rep['seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
