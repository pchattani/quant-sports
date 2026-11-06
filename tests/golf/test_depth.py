"""The depth round (6 Nov 2026): analytics.py and depth.py on small synthetic frames, the partial-round filter, the
season-statistics parser and the points-share table."""
import numpy as np
import pandas as pd

from oddsmarkets.golf import analytics as A
from oddsmarkets.golf import depth as DP
from oddsmarkets.golf.sources import espn


def _rounds():
    rows = []
    rng = np.random.default_rng(3)
    for e in range(6):
        for r in (1, 2, 3, 4):
            for i in range(30):
                skill = (i - 15) / 10.0
                st = int(round(70 - skill + rng.normal(0, 2.5)))
                out = st // 2
                rows.append({"tour": "pga", "event": f"e{e}", "pid": f"p{i}", "round": r, "date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=7 * e + r),
                             "strokes": float(st), "field_par": 70.0, "sg": 70.0 - st, "pre": skill, "out": float(out), "in": float(st - out),
                             "tee_time": f"2025-01-0{1 + r % 2}T{10 + i % 8}:00Z", "holes": 18})
    df = pd.DataFrame(rows)
    # the walk's own field par: the mean of strokes plus the rating brought in (models/ratings.py)
    df["field_par"] = (df["strokes"] + df["pre"]).groupby([df["event"], df["round"]]).transform("mean")
    df["sg"] = df["field_par"] - df["strokes"]
    return df


def test_nines_add_up_to_the_round():
    df = _rounds()
    rf = A.round_frame(df.drop(columns=["out", "in", "tee_time", "holes"]), df[["event", "pid", "round", "out", "in", "tee_time", "holes"]])
    # each nine is against the field's nine (half the rating each), so the two nines add up to the round
    assert np.allclose(rf["sg_f"] + rf["sg_b"], rf["sg"])
    assert rf["wave"].isin(["am", "pm", ""]).all()
    assert (rf.loc[rf["round"] > 2, "wave"] == "").all()


def test_shrinkage_pulls_small_samples_to_the_mean():
    m = pd.Series([3.0, 3.0])
    n = pd.Series([1, 200])
    s = A._shrink(m, n, 12, prior=0.0)
    assert s.iloc[0] < 0.3 and s.iloc[1] > 2.8


def test_player_metrics_rank_skill():
    df = _rounds()
    rf = A.round_frame(df.drop(columns=["out", "in", "tee_time", "holes"]), df[["event", "pid", "round", "out", "in", "tee_time", "holes"]])
    pm = A.player_metrics(rf, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None)
    assert pm.loc["p29", "sg"] > pm.loc["p0", "sg"]
    assert 0 <= pm["great"].min() and pm["great"].max() <= 1
    pm["q"] = True
    pc = A.percentiles(pm, pm["q"], ["sg", "sd"])
    assert pc.loc["p29", "sg"] > 90 and pc.loc["p0", "sg"] < 10


def test_percentiles_flip_lower_is_better():
    df = pd.DataFrame({"sd": np.arange(20, dtype=float)}, index=[f"p{i}" for i in range(20)])
    pc = A.percentiles(df, pd.Series(True, index=df.index), ["sd"])
    assert pc.loc["p0", "sd"] > pc.loc["p19", "sd"]


def test_parse_stats_drops_unrecorded_striking():
    raw = {"splits": {"categories": [{"stats": [{"name": "roundsPlayed", "value": 80}, {"name": "yardsPerDrive", "value": 0},
                                                {"name": "greensInRegPct", "value": 68.5}, {"name": "scoringAverage", "value": 70.1}]}]}}
    s = espn.parse_stats(raw)
    assert s["rounds"] == 80 and s["gir"] == 68.5 and "dist" not in s
    assert espn.parse_stats({"error": {"code": 404}}) == {}


def test_points_share_falls_with_position():
    assert DP._share(1) == 1.0
    assert DP._share(2) == 0.64
    assert 0.2 < DP._share(9.5) < 0.215
    assert DP._share(61) == 0.0
    assert all(DP._share(p) >= DP._share(p + 1) for p in range(1, 60))


def test_age_from_a_date_of_birth():
    from datetime import date
    assert DP._age("1996-06-21", date(2026, 6, 21)) == 30.0
    assert DP._age(None, date(2026, 1, 1)) is None
