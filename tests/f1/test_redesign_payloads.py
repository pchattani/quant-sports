"""Redesign payload additions (22 Oct 2026): season.json title_history, drivers.json pct_peer floor and similar drivers."""
from oddsmarkets.f1.analytics import drivers as drv
from oddsmarkets.f1.analytics import season as ssn


def _sim(done, n, p=0.6):
    return {"n": n, "completed": list(range(1, done + 1)),
            "drivers": {"a": {"p_title": p, "exp_points": 300.0, "current_points": 250.0,
                              "points_q": {"q5": 280.0, "q25": 290.0, "q50": 300.0, "q75": 310.0, "q95": 320.0}},
                        "b": {"p_title": 1 - p, "exp_points": 290.0, "current_points": 240.0, "points_q": {}}},
            "constructors": {"t": {"p_title": 1.0, "exp_points": 600.0, "current_points": 500.0, "points_q": {}}}}


def test_title_history():
    h = ssn.title_history(None, _sim(5, 400))
    assert len(h) == 1 and h[0]["after_round"] == 5 and h[0]["drivers"]["a"]["p05"] == 280.0 and h[0]["drivers"]["a"]["points"] == 250.0
    h = ssn.title_history({"title_history": h}, _sim(5, 20000, 0.7))        # more simulations: replaces
    assert h[-1]["n_sims"] == 20000 and h[-1]["drivers"]["a"]["p_title"] == 0.7
    h = ssn.title_history({"title_history": h}, _sim(5, 400, 0.1))          # fewer: kept
    assert h[-1]["drivers"]["a"]["p_title"] == 0.7
    h = ssn.title_history({"title_history": h}, _sim(6, 20000))
    assert [x["after_round"] for x in h] == [5, 6]
    assert ssn.title_history({"title_history": h}, None) == h                # no simulation: unchanged
    stand = {"drivers": [{"driver": "a", "points": 400.0}, {"driver": "b", "points": 380.0}],
             "constructors": [{"team": "t", "points": 780.0}], "rounds_done": [1, 2, 3, 4, 5, 6, 7]}
    f = ssn.title_history({"title_history": h}, None, stand, True)
    assert f[-1]["final"] and f[-1]["drivers"]["a"]["p_title"] == 1.0 and f[-1]["drivers"]["b"]["p_title"] == 0.0
    assert ssn.title_history({"title_history": f}, None, stand, True) == f   # the final entry is added once
    assert ssn.title_history(None, None, stand, True) == []                  # never recorded: no history invented


def _cat(year, rows):
    return {"year": year, "drivers": {d: {"name": d, "team": "t", "races": r, "qualified": r >= 8,
                                          "values": {k: (x + i) for i, k in enumerate(drv.SIMILAR_W)}} for d, r, x in rows}}


def test_add_similar():
    cats = {2020: _cat(2020, [("a", 20, 0.0), ("b", 20, 1.0), ("c", 20, 2.0), ("stand_in", 1, 0.1)]),
            2021: _cat(2021, [("a", 20, 0.5), ("d", 20, 1.5), ("e", 20, 2.5)]),
            1990: _cat(1990, [("old", 16, 0.0), ("x", 16, 1.0), ("y", 16, 2.0)])}
    changed = drv.add_similar(cats, k=3)
    assert changed == [2020, 2021] and "similar_method" in cats[2020]
    sim = cats[2020]["drivers"]["a"]["similar"]
    assert sim and all(s["driver"] != "a" for s in sim)                      # own seasons excluded
    assert all(s["driver"] != "stand_in" for c in cats.values() for e in c["drivers"].values() for s in e.get("similar") or [])
    assert "similar" not in cats[2020]["drivers"]["stand_in"] and "similar" not in cats[1990]["drivers"]["old"]
    assert [s["d"] for s in sim] == sorted(s["d"] for s in sim)
