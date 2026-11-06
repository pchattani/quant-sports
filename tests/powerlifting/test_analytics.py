"""Analytics and the forecast on small synthetic frames (no network, no OpenPowerlifting dump)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.powerlifting import analytics as A
from oddsmarkets.powerlifting.models import backtest as BT
from oddsmarkets.powerlifting.models import forecast as F
from oddsmarkets.powerlifting.models import ratings as R


def test_ipf_classes_from_bodyweight():
    assert A.ipf_class("M", 83.0) == "83" and A.ipf_class("M", 83.1) == "93" and A.ipf_class("M", 140) == "120+"
    assert A.ipf_class("F", 47.0) == "47" and A.ipf_class("F", 90) == "84+" and A.ipf_class("F", None) is None
    v = A.ipf_class_vec(pd.Series(["M", "F", "M"]), pd.Series([59.0, 63.5, np.nan]))
    assert v.tolist()[:2] == ["59", "69"] and pd.isna(v.iloc[2])


def _walk_rows():
    rows = []
    for m in range(6):
        day = pd.Timestamp("2021-01-01") + pd.Timedelta(days=90 * m)
        for i in range(10):
            rows.append({"pid": f"p{i}", "date": day, "dots": 300.0 + 10 * i + 5 * m, "total": 500.0 + 10 * i + 5 * m, "bw": 83.0,
                         "sex": "M", "eq": "raw", "tested": True, "meet_id": f"m{m}", "stream": "men_raw", "age": 25.0 + m / 4})
    return pd.DataFrame(rows)


def test_walk_carries_pre_meet_history_only():
    w, books = R.walk(_walk_rows(), R.Params(half_life=180, k0=0.02, m0=350, min_field=5))
    r = w[(w["pid"] == "p3") & (w["meet_id"] == "m2")].iloc[0]
    assert r["n"] == 2 and r["last_dots"] == 335.0 and r["best_dots"] == 335.0      # m1's 335, not m2's 340
    assert r["gap"] == 90 and np.isnan(w[(w["pid"] == "p3") & (w["meet_id"] == "m0")].iloc[0]["last_dots"])


def test_rating_at_matches_the_book_and_ignores_later_meets():
    rows = _walk_rows()
    p = R.Params(half_life=180, k0=0.02, m0=350, min_field=5)
    w, books = R.walk(rows, p)
    at = pd.Timestamp("2022-06-01")
    ra = R.rating_at(w, at, p).set_index("pid")
    assert abs(ra.loc["p0", "rating"] - books["men_raw"].rating("p0", at)) < 1e-9
    early = R.rating_at(w, pd.Timestamp("2021-02-01"), p).set_index("pid")
    assert early.loc["p0", "n"] == 1


def test_pre_state_uses_only_earlier_meets():
    rows = _walk_rows()
    p = R.Params(half_life=180, k0=0.02, m0=350, min_field=5)
    w, _ = R.walk(rows, p)
    ent = rows[rows["meet_id"] == "m3"][["stream", "pid", "date", "age"]].reset_index(drop=True)
    st = F.pre_state(ent, w, p, {"men_raw": 350.0})
    x = st[st["pid"] == "p0"].iloc[0]
    assert x["n"] == 3 and x["last_dots"] == 310.0 and x["gap"] == 90


def test_forecast_fits_and_beats_the_last_meet_on_improving_lifters():
    w, _ = R.walk(_walk_rows(), R.Params(half_life=180, k0=0.02, m0=350, min_field=5))
    d = w[w["n"] > 0]
    m = F.Model(variant="full").fit(d, w[w["n"] == 0])
    e_full = BT.errors(d["dots"], m.mu(d))["rmse"]
    e_last = BT.errors(d["dots"], d["last_dots"])["rmse"]
    assert e_full < e_last                     # everyone improves 5 a meet: the intercept learns it


def test_podium_simulation_hands_out_three_places_per_flight():
    g = np.array([0] * 6 + [1] * 4)
    mu = np.array([600, 590, 580, 400, 390, 380, 500, 300, 299, 298], dtype=float)
    sd = np.full(10, 15.0)
    pp, pw = F.simulate_podium(g, mu, sd, np.zeros(10), sims=400)
    assert abs(pp[:6].sum() - 3) < 1e-9 and abs(pw[:6].sum() - 1) < 1e-9
    assert pp[0] > 0.95 and pp[5] < 0.05 and pw[6] > 0.99


def test_paired_interval_says_better_only_when_clear():
    rng = np.random.default_rng(1)
    base = rng.normal(0, 1, 4000) ** 2 + 0.5
    new = base - 0.2
    x = BT.paired(base, new, np.arange(4000) // 4)
    assert x["better"] and x["lo"] > 0
    y = BT.paired(base, base + rng.normal(0, 0.01, 4000), np.arange(4000) // 4)
    assert not y["better"]


def test_percentiles_turn_lower_is_better_and_keep_styles():
    df = pd.DataFrame({"stream": ["men_raw"] * 20, "cls": ["83"] * 20, "bomb": np.arange(20, dtype=float), "sh_s": np.arange(20, dtype=float),
                       "dots": np.arange(20, dtype=float)})
    p = A.percentiles(df, ids=["bomb", "sh_s", "dots"])
    assert p["bomb"].iloc[0] > p["bomb"].iloc[-1]          # fewer bomb-outs rank higher
    assert p["sh_s"].iloc[-1] > p["sh_s"].iloc[0] and p["dots"].iloc[-1] == 100


def test_iron_registers_its_follow_cards_at_boot():
    from pathlib import Path
    core = (Path(__file__).resolve().parents[2] / "docs" / "iron" / "assets" / "app" / "core.js").read_text(encoding="utf-8")
    assert "QK.FOLLOW_CARDS.iron = ['lifter']" in core
