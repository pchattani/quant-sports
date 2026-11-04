from datetime import date

import pandas as pd

from oddsmarkets.powerlifting.models import ratings as R


def _row(pid, day, dots, stream="men_raw", meet=None):
    return {
        "pid": pid, "date": pd.Timestamp(day), "dots": dots, "total": 500.0, "bw": 90.0,
        "sex": "M", "eq": "raw", "tested": True, "meet_id": meet or day, "stream": stream,
    }


def test_walk_has_no_look_ahead():
    rows = pd.DataFrame([
        _row("a", "2020-01-01", 500, meet="m1"),
        _row("a", "2020-06-01", 600, meet="m2"),
        _row("b", "2020-06-01", 410, meet="m2"),
        _row("a", "2021-01-01", 450, meet="m3"),
        _row("b", "2021-01-01", 420, meet="m3"),
        _row("c", "2021-01-01", 430, meet="m3"),
        _row("d", "2021-01-01", 440, meet="m3"),
        _row("e", "2021-01-01", 400, meet="m3"),
        _row("f", "2021-01-01", 390, meet="m3"),
        _row("g", "2021-01-01", 380, meet="m3"),
        _row("h", "2021-01-01", 370, meet="m3"),
    ])
    p = R.Params(half_life=365, k0=2, m0=400, min_field=1)
    walked, books = R.walk(rows, p)
    first = walked[walked["meet_id"] == "m1"].iloc[0]
    assert first["pre"] == 400.0 and first["n"] == 0          # newcomer: the prior
    second = walked[(walked["meet_id"] == "m2") & (walked["pid"] == "a")].iloc[0]
    assert second["n"] == 1 and second["pre"] > 400            # only the first meet is in
    assert second["pre"] < 600                                 # the 600 has not been seen yet


def test_current_drops_inactive_lifters():
    rows = pd.DataFrame([
        _row("old", "2018-01-01", 500, meet=f"m{i}") for i in range(10)
    ] + [
        _row("now", "2025-06-01", 450, meet=f"n{i}") for i in range(10)
    ])
    # same meet for the batch so min_field is met
    rows.loc[rows["pid"] == "old", "meet_id"] = "oldmeet"
    rows.loc[rows["pid"] == "now", "meet_id"] = "nowmeet"
    rows.loc[rows["pid"] == "old", "date"] = pd.Timestamp("2018-01-01")
    rows.loc[rows["pid"] == "now", "date"] = pd.Timestamp("2025-06-01")
    walked, books = R.walk(rows, R.Params(half_life=365, k0=2, m0=400, min_field=8))
    cur = R.current(books["men_raw"], at=date(2025, 11, 1), min_meets=5, active_days=400)
    assert list(cur["pid"]) == ["now"]
