"""Player layer: game score, the team constraint, replacement level, inferred transfers, units and fantasy."""
import numpy as np
import pytest

from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import players as PL
from oddsmarkets.college.hoops import ratings as R

from .hoops_synth import make_level


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("CAMPUS_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("CAMPUS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CAMPUS_DATA", str(tmp_path / "data"))
    D._CACHE.clear()
    return tmp_path


def test_game_score_formula():
    # sec pts fgm fga tpm tpa ftm fta oreb dreb ast stl blk tov pf
    x = np.array([[1800, 20, 8, 15, 2, 5, 2, 4, 2, 5, 3, 1, 1, 2, 3]], float)
    expect = 20 + 0.4 * 8 - 0.7 * 15 - 0.4 * 2 + 0.7 * 2 + 0.3 * 5 + 1 + 0.7 * 3 + 0.7 * 1 - 0.4 * 3 - 2
    assert PL.gmsc(x)[0] == pytest.approx(expect)


def test_team_constraint_and_moves(roots):
    make_level("mbb", seasons=(2025, 2026))
    tab = D.season_table("mbb", 2026)
    e = R.end_ratings(tab, "mbb")
    ratings = {t: {"rating": v["net"], "tempo": v["tempo"]} for t, v in e["teams"].items()}
    sp = PL.season_players("mbb", 2026, ratings)
    rows = sp["rows"]
    assert len(rows) == 640 and sp["params"]["repl"] < 0
    # five-man sum on the floor = team rating
    br = PL.box_rows("mbb", 2026)
    by = {}
    for p, r in rows.items():
        by.setdefault(r["team"], []).append(r)
    for t, rs in list(by.items())[:5]:
        tm = sum(r["min"] for r in rs)
        five = sum(r["r"] * r["min"] / (tm / 5) for r in rs)
        assert five == pytest.approx(ratings[t]["rating"], abs=1e-6)
    assert all(r["pos"] in ("G", "F", "C") for r in rows.values())
    # rate fields: on-floor denominators from the game's two team totals
    r0 = max(rows.values(), key=lambda r: r["min"])
    rt = r0["rates"]
    t = r0["tot"]
    assert rt["pts100"] > 0 and 0 < rt["trb_pct"] < 1 and 0 <= rt["stl_pct"] < 0.2 and 0 <= rt["ast_pct"] < 1
    assert rt["efg"] == pytest.approx((t["fgm"] + 0.5 * t["tpm"]) / t["fga"])
    lo, hi = sorted((rt["orb_pct"], rt["drb_pct"]))
    assert lo - 1e-12 <= rt["trb_pct"] <= hi + 1e-12          # the mediant of the two rebound rates
    ln = PL.per_game_line(r0)
    assert set(PL.RATE_KEYS) <= set(ln)
    qual = {p for p, r in rows.items() if r["min"] >= 150}
    role, thr = PL.classify_roles(rows, qual)
    assert set(role) == set(rows) and set(role.values()) <= {"G", "W", "B"}
    assert all(role[p] == "G" for p, r in rows.items() if r["pos"] == "G")
    # a move: the same id on a different team the next season
    prev = {"p1": {**next(iter(rows.values())), "team": "100", "value": 50.0, "pctl": 95.0, "name": "X"}}
    mv = PL.inferred_moves(prev, {"p1": "101"}, None, {})
    assert mv[0]["from"] == "100" and mv[0]["to"] == "101" and mv[0]["value_after"] is None and mv[0]["grade"] == "A"
    rv = PL.returning_value(prev, {"p1": "101"}, ["100", "101"])
    assert rv["101"]["ret"] == 50.0 and rv["100"]["lost"] == 50.0 and rv["100"]["prev"] == 50.0
    us = PL.units("mbb", rows, {})
    assert {u["key"] for u in next(iter(us.values()))} >= {"G", "F", "C"}
    bt = PL.fantasy_backtest(br)
    assert bt["n"] > 1000 and bt["mae"] > 0 and bt["mae_naive"] > 0


def test_nine_cat_ranks():
    rng = np.random.default_rng(0)
    lines = {}
    for k in range(60):
        L = {c: float(rng.uniform(0, 10)) for c in ("pts", "reb", "ast", "stl", "blk", "tpm", "tov")}
        L.update({"fga": 10.0, "fgm": float(rng.uniform(3, 6)), "fta": 4.0, "ftm": float(rng.uniform(2, 4))})
        L["fp"] = L["pts"] + L["reb"]
        lines[str(k)] = L
    lines["star"] = {"pts": 30, "reb": 12, "ast": 9, "stl": 3, "blk": 3, "tpm": 4, "tov": 0.5, "fga": 18, "fgm": 11, "fta": 8,
                     "ftm": 7.5, "fp": 60}
    out = PL.nine_cat(lines)
    assert out["star"]["rank"] == 1


def test_returning_value_splits_own_and_incoming():
    prev = {"a": {"team": "1", "value": 50.0, "min": 900.0}, "b": {"team": "2", "value": 30.0, "min": 800.0},
            "c": {"team": "1", "value": 20.0, "min": 400.0}}
    cur = {"a": "1", "b": "1"}                                      # c gone, b transferred 2 -> 1
    rv = PL.returning_value(prev, cur, ["1", "2"])
    assert rv["1"]["ret"] == 80.0 and rv["1"]["ret_same"] == 50.0 and rv["1"]["ret_in"] == 30.0 and rv["1"]["n_in"] == 1
    assert rv["1"]["prev"] == 70.0 and rv["1"]["lost"] == 20.0 and rv["2"]["lost"] == 30.0


def test_non_member_rows_dropped(roots):
    info = make_level("mbb", seasons=(2026,), current=2027)
    st = D.load("mbb", 2026)
    br = PL.box_rows("mbb", 2026, st)
    members = {t for t, v in st["teams"].items() if v.get("member")}
    ratings = {t: {"rating": 0.0, "tempo": 68.0} for t in members}
    res = PL.season_players("mbb", 2026, ratings, br, st)
    assert res["rows"] and all(r["team"] in members for r in res["rows"].values())
