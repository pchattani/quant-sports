"""The Footballer's calibration.json (oddsmarkets/football/research/site_calibration.py) and its committed copy."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.football.research import site_calibration as SC

ROOT = Path(__file__).resolve().parents[1]


def _run(n=400, seed=1):
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0.2, 0.7, n)
    pd_ = np.full(n, 0.25)
    pa = 1 - ph - pd_
    res = np.array([rng.choice(3, p=[a, b, c]) for a, b, c in zip(ph, pd_, pa)])
    seasons = np.where(np.arange(n) % 4 == 0, "2017-18", "2021-22")              # a quarter in the tuning seasons
    league = np.where(np.arange(n) % 10 == 0, "league-two", "premier-league")       # a tenth outside the site's leagues
    return pd.DataFrame({"league": league, "season": seasons, "p_h": ph, "p_d": pd_, "p_a": pa, "result": res})


def test_build_scores_test_seasons_of_site_leagues_only():
    R = _run()
    out = SC.build(R)
    keep = R[(R.season == "2021-22") & (R.league == "premier-league")]
    m = out["metrics"]["model"]
    assert m["n"] == len(keep) == out["outcomes_1x2"]["n"]
    assert abs(m["base_rate"] - float((keep.result == 0).mean())) < 1e-4
    assert abs(m["brier"] - float(np.mean((keep.p_h - (keep.result == 0)) ** 2))) < 1e-4
    assert out["span"] == "2021/22 to 2021/22" and out["leagues"] == ["premier-league"]
    assert sum(b["n"] for b in m["reliability"]) == m["n"]
    o = out["outcomes_1x2"]
    assert 0 < o["rps"] < o["brier"] and o["logloss"] > 0 and o["draw"]["n"] == m["n"]


def test_committed_file_is_readable_by_qk_calib_find():
    j = json.loads((ROOT / "oddsmarkets/football/competitions/league/data/calibration.json").read_text(encoding="utf-8"))
    m = j["metrics"]["model"]                                  # QK.calib.find: metrics.model with reliability
    assert j["ok"] and m["n"] > 10000 and m["reliability"]
    assert all({"lo", "hi", "n", "mean_p", "freq"} <= set(b) for b in m["reliability"])
    assert j["subject"] and j["span"]
