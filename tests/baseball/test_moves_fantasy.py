"""Transactions, valuation v2, trade ratings and the fantasy layer (analytics/moves.py, valuation.py, trade_ratings.py,
fantasy.py, mlbapi.py; sources/statsapi.py's transactions and stat lines). No network: the Stats API client is offline
under the tests (conftest) and the API's answers are planted."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.analytics import fantasy as F
from oddsmarkets.baseball.analytics import fantasy_build as FB
from oddsmarkets.baseball.analytics import mlbapi
from oddsmarkets.baseball.analytics import moves as M
from oddsmarkets.baseball.analytics import trade_ratings as TRR
from oddsmarkets.baseball.analytics import valuation as VA
from oddsmarkets.baseball.analytics import value as V
from oddsmarkets.baseball.sources import statsapi


def tx(id_, d, code, pid, f, t, x, pn=None, fn=None, tn=None):
    return {"id": id_, "d": d, "e": d, "r": None, "c": code, "p": pid, "pn": pn or (f"P{pid}" if pid else None), "f": f, "fn": fn, "t": t,
            "tn": tn, "x": x}


# ── the Stats API source ────────────────────────────────────────────────────

class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        return self.answers.pop(0) if self.answers else None


def test_transactions_raw_compacts_and_drops_duplicates():
    rec = {"id": 7, "person": {"id": 11, "fullName": "A B"}, "fromTeam": {"id": 1, "name": "X"}, "toTeam": {"id": 2, "name": "Y"},
           "date": "2026-07-30", "effectiveDate": "2026-07-30", "typeCode": "TR", "description": "X traded A B to Y for cash."}
    c = FakeClient([{"transactions": [rec, dict(rec)]}])
    out = statsapi.transactions_raw(c, "2026-07-01", "2026-07-31")
    assert len(out) == 1 and out[0]["p"] == "11" and out[0]["f"] == "1" and out[0]["t"] == "2" and out[0]["c"] == "TR"


def test_stat_lines_sum_club_rows_and_prefer_the_combined_row():
    def split(pid, team, n_teams, pa, hr):
        return {"player": {"id": pid}, "team": {"id": team} if team else None, "numTeams": n_teams, "stat": {"plateAppearances": pa, "homeRuns": hr}}
    page = {"stats": [{"totalSplits": 4, "splits": [split(1, 10, 1, 100, 3), split(1, 11, 1, 50, 2), split(2, 10, 1, 80, 1),
                                                    split(3, None, 2, 300, 9)]}]}
    out = statsapi.stat_lines(FakeClient([page]), "hitting", season=2025)
    assert out["1"]["pa"] == 150 and out["1"]["hr"] == 5 and out["1"]["team"] is None
    assert out["2"]["team"] == "10" and out["3"]["pa"] == 300 and out["3"]["teams"] == 2


def test_mlbapi_offline_reads_the_cache_only(bullpen_roots):
    assert mlbapi.client() is None                                    # BULLPEN_OFFLINE is set by conftest
    assert mlbapi.tx_month("mlb", 2026, 7, None) is None
    from oddsmarkets.baseball import analytics as an
    an.write_json(mlbapi.tx_path("mlb", 2026, 7), {"fetched_at": "2026-08-20T00:00:00Z", "rows": [tx(1, "2026-07-02", "SC", "5", None, "1", "x")]})
    rows = mlbapi.transactions("mlb", date(2026, 7, 1), date(2026, 7, 31))
    assert len(rows) == 1 and rows[0]["p"] == "5"


def test_season_weeks_cover_the_season_from_mondays():
    store = {"games": {"1": {"gtype": "R", "date": "2026-03-26"}, "2": {"gtype": "R", "date": "2026-09-27"}}}
    w = mlbapi.season_weeks(2026, store)
    assert w[0][0].weekday() == 0 and w[0][0] <= date(2026, 3, 26) and w[-1][1] >= date(2026, 9, 27)


# ── parsing ─────────────────────────────────────────────────────────────────

def test_parse_injured_list_moves():
    p = M.parse(tx(1, "2026-05-02", "SC", "9", None, "1", "Club placed RHP X on the 15-day injured list retroactive to April 29, 2026. Right elbow inflammation."))
    assert p["kind"] == "il_place" and p["il"] == 15 and p["start"] == "2026-04-29" and p["part"] == "elbow"
    q = M.parse(tx(2, "2016-05-02", "SC", "9", None, "1", "Club placed LHP X on the 10-day disabled list. Left hamstring strain."))
    assert q["kind"] == "il_place" and q["il"] == 10 and q["part"] == "hamstring"
    a = M.parse(tx(3, "2026-06-01", "SC", "9", None, "1", "Club activated RHP X from the 15-day injured list."))
    assert a["kind"] == "il_activate"
    t = M.parse(tx(4, "2026-06-01", "SC", "9", None, "1", "Club transferred RHP X from the 15-day injured list to the 60-day injured list."))
    assert t["kind"] == "il_transfer" and t["il_to"] == 60
    assert M.parse(tx(5, "2026-06-01", "SFA", "9", None, "1", "Club signed free agent RHP X to a minor league contract."))["kind"] == "signing_minor"
    assert M.parse(tx(6, "2026-06-01", "ASG", "9", None, "1", "Club sent RHP X on a rehab assignment to Y."))["kind"] == "rehab"


def test_trades_group_pieces_and_give_extras_to_the_right_club():
    x = "Alpha traded RHP A to Beta for cash."
    rows = [tx(10, "2026-07-30", "TR", "1", "100", "200", x, tn="Beta", fn="Alpha"),
            tx(10, "2026-07-30", "TR", None, "200", "100", x, tn="Alpha", fn="Beta")]
    T = M.trades(M.parse_all(rows))
    assert len(T) == 1 and T[0]["pieces"][0]["to"] == "200" and T[0]["extras"] == {"100": ["cash"]}


def test_one_way_trades_of_a_three_club_deal_merge():
    rows = [tx(21, "2025-12-19", "TR", "1", "A", "B", "A traded X to B."), tx(22, "2025-12-19", "TR", "2", "B", "C", "B traded Y to C."),
            tx(23, "2025-12-19", "TR", "3", "C", "A", "C traded Z to A."), tx(90, "2025-12-19", "TR", "4", "D", "E", "D traded W to E.")]
    T = M.trades(M.parse_all(rows))
    merged = [t for t in T if t.get("merged")]
    assert len(T) == 2 and len(merged) == 1 and sorted(merged[0]["teams"]) == ["A", "B", "C"] and len(merged[0]["pieces"]) == 3


def test_il_stints_days_and_duplicates():
    rows = [tx(1, "2026-05-01", "SC", "9", None, "1", "C placed X on the 10-day injured list. Left oblique strain."),
            tx(2, "2026-05-02", "SC", "9", None, "1", "C placed X on the 10-day injured list. Left oblique strain."),
            tx(3, "2026-05-20", "SC", "9", None, "1", "C activated X from the 10-day injured list."),
            tx(4, "2026-09-01", "SC", "9", None, "1", "C placed X on the 60-day injured list. Right shoulder surgery.")]
    st = M.il_stints(M.parse_all(rows))
    assert len(st["9"]) == 2 and st["9"][0]["end"] == "2026-05-20" and st["9"][1]["end"] is None
    days = M.il_days(st, {2026: (date(2026, 3, 26), date(2026, 9, 27))})
    assert days["9"][2026]["days"] == 20 + 27 and days["9"][2026]["stints"] == 2
    assert "9" in M.on_il(st, date(2026, 9, 10)) and "9" not in M.on_il(st, date(2026, 6, 1))


def test_feed_rows_keep_mlb_moves_only():
    rows = M.parse_all([tx(1, "2026-06-01", "OPT", "9", "1", "500", "C optioned X to Y."),
                        tx(2, "2026-06-01", "SFA", "8", None, "1", "C signed free agent X to a minor league contract."),
                        tx(3, "2026-06-01", "ASG", "7", "600", "601", "X assigned to Y.")])
    fr = M.feed_rows(rows, "2026-01-01", "2026-12-31", {"1"})
    assert [r[1] for r in fr] == ["option"]
    assert M.ledger_counts(fr, ["1"])["1"]["option"] == 1


# ── valuation ───────────────────────────────────────────────────────────────

def _splits():
    rows = []
    for i, d in enumerate(["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01"]):
        rows.append({"pid": "9", "kind": "H", "tid": "A" if i < 2 else "B", "date": d, "n": 100, "ws": 30.0 if i < 2 else 40.0, "wd": 90.0})
    rows.append({"pid": "8", "kind": "H", "tid": "A", "date": "2026-05-01", "n": 400, "ws": 120.0, "wd": 360.0})
    return VA.Splits({2026: pd.DataFrame(rows)})


def test_war_part_splits_add_up_and_follow_the_woba():
    sp = _splits()
    tot = sp.part("H", "9", 2026)
    a = VA.war_part(4.0, "H", tot, sp.part("H", "9", 2026, "A"))
    b = VA.war_part(4.0, "H", tot, sp.part("H", "9", 2026, "B"))
    assert a + b == pytest.approx(4.0) and b > a                       # the better half with B earns more
    assert sp.clubs("H", "9", 2026) == {"A": 200.0, "B": 200.0}


def test_naive_path_ages_and_discounting():
    curve = [0.0, -0.1, 0.0]                                          # a tenth of a win per 600 PA lost a year after 28
    p = VA.naive_path(3.0, 600.0, 30.0, "H", curve, 3)
    assert p[0] == pytest.approx(3.0) and p[1] < p[0] and p[2] < p[1]
    assert VA.discounted([1.0, 1.0]) == pytest.approx(1.0 + VA.DISCOUNT)


def test_band_and_il_expectation():
    bfit = {"H": {"1": {str(b): [-1.0, 2.0, 100] for b in range(5)}}}
    assert VA.band(bfit, "H", "1", 3.0) == (2.0, 5.0)
    e, p = VA.il_expect({"coef": [20.0, 0.5, 0.0, 0.0], "logit": [0.0, 0.0, 0.0, 0.0]}, 40.0, 0.0, 28.0)
    assert e == pytest.approx(40.0) and p == pytest.approx(0.5)


def test_scarcity_line_is_the_median_starter():
    rows = [{"pid": str(i), "kind": "H", "pos": "SS", "pos_g": {"SS": 140.0}, "n": 500, "war": 1.0, "rate": i / 10.0} for i in range(40)]
    lines = VA.scarcity(rows, {}, {"pa": 650.0, "sp": 4000.0, "rp": 2200.0}, 10.0)
    vals = sorted((V.slot_value(r, "SS", r["rate"], {"pa": 650.0, "sp": 4000.0, "rp": 2200.0}, 10.0) for r in rows), reverse=True)
    assert lines["SS"]["line"] == pytest.approx(round(vals[14], 2)) and lines["SS"]["n"] == 40


def test_poisson_fit_recovers_a_planted_log_link():
    rng = np.random.default_rng(3)
    X = np.c_[np.ones(4000), np.zeros((4000, 3)), rng.normal(size=4000)]
    y = rng.poisson(np.exp(-1.0 + 0.6 * X[:, 4]))
    b = VA.poisson_fit(X, y.astype(float), ridge=1e-3)
    assert b[0] == pytest.approx(-1.0, abs=0.08) and b[4] == pytest.approx(0.6, abs=0.06)


def test_prospect_rows_pick_the_highest_level_with_a_sample():
    def line(pa, h, age):
        return {"pa": pa, "ab": pa - 10, "h": h, "d": 5, "t": 0, "hr": 3, "bb": 8, "hbp": 1, "sf": 1, "age": age}
    lines = {2025: {"aaa": {"H": {"x": line(30, 9, 22), **{f"a{i}": line(300, 70 + i, 26) for i in range(25)}}, "P": {}},
                    "aa": {"H": {"x": line(400, 120, 22), **{f"b{i}": line(300, 70 + i, 24) for i in range(25)}}, "P": {}}}}
    pr = VA.prospect_rows(lines)
    assert pr[(2025, "H", "x")]["level"] == "aa" and pr[(2025, "H", "x")]["age_rel"] < 0 and pr[(2025, "H", "x")]["z"] > 0


# ── trade ratings ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("net,g", [(2.5, "A"), (2.0, "A"), (1.0, "B"), (0.0, "C"), (-1.0, "D"), (-3.0, "F"), (None, None)])
def test_trade_grades(net, g):
    assert TRR.grade(net) == g


def test_timing_in_season_and_between_seasons():
    b = {2026: (date(2026, 3, 26), date(2026, 9, 27))}
    assert TRR.timing("2026-07-30", b) == (2026, True)
    assert TRR.timing("2026-11-20", b) == (2027, False)
    assert TRR.timing("2026-01-10", b) == (2026, False)


def _world():
    hist = {"H:9": {2023: {"war": 3.0, "n": 600, "age": 27}, 2024: {"war": 3.0, "n": 600, "age": 28}, 2025: {"war": 3.0, "n": 600, "age": 29},
                    2026: {"war": 4.0, "n": 400, "age": 30}},
            "H:8": {2025: {"war": 1.0, "n": 600, "age": 26}, 2026: {"war": 2.0, "n": 400, "age": 27}}}
    hfit = {"H": {str(b): {"slope": [1.0] * 5, "n": [100] * 5} for b in range(4)}}
    store = {"games": {str(i): {"gtype": "R", "date": f"2026-0{4 + i // 30}-{1 + i % 28:02d}", "home": "A", "away": "B"} for i in range(150)}}
    W = TRR.World(hist, {"H": [1500.0, 0.0]}, {"H": [0.0, 0.0, 0.0]}, hfit, _splits(), {2026: store}, {2026: (date(2026, 3, 26), date(2026, 9, 27))},
                  {"9": {"debut": 2019, "birth": "1996-01-01"}, "8": {"debut": 2025, "birth": "1999-01-01"}}, {})
    W.retention = {"by": {"6+|off": [0.9, 0.5, 0.4, 0.3, 0.2], "0-2|off": [0.9, 0.8, 0.7, 0.6, 0.5]}}
    W.base = {"21-22": {"value": 0.2, "e2": 0.05, "n": 50}}
    return W


def test_value_at_between_seasons_weights_later_seasons_by_retention():
    W = _world()
    v = TRR.value_at(W, "9", "2026-11-20", "B")
    assert v["type"] == "mlb" and v["service"] == "6+" and v["rest"] == 0.0 and len(v["path"]) == 5
    expect = sum((VA.DISCOUNT ** t) * v["path"][t] * v["ret"][t] for t in range(5))
    assert v["value"] == pytest.approx(expect) and v["ret"][:2] == [0.9, 0.5]
    u = TRR.value_at(W, "8", "2026-11-20", "B")
    assert u["service"] == "0-2" and u["ret"][1] == 0.8


def test_value_at_falls_back_to_the_base_rate():
    W = _world()
    W.extra = {"77": {"dob": "2004-06-01"}}
    v = TRR.value_at(W, "77", "2026-11-20", "B")
    assert v["type"] == "base" and v["value"] == pytest.approx(0.2)


def test_realised_counts_only_the_new_club_after_the_date():
    W = _world()
    r = TRR.realised(W, "9", "2026-06-15", "B")
    tot = W.splits.part("H", "9", 2026)
    assert r["total"] == pytest.approx(VA.war_part(4.0, "H", tot, W.splits.part("H", "9", 2026, "B", "2026-06-15")))
    assert TRR.realised(W, "9", "2026-06-15", "C")["total"] == 0.0


def test_rate_nets_and_winner():
    W = _world()
    t = {"id": 1, "date": "2026-11-20", "teams": ["A", "B"], "pieces": [{"pid": "9", "name": "N", "from": "A", "to": "B"}], "extras": {"A": ["cash"]}}
    r = TRR.rate(W, t)
    a, b = r["clubs"]["A"], r["clubs"]["B"]
    assert b["net"] == pytest.approx(-a["net"]) and b["net"] > 0.75 and r["winner"] == "B" and a["extras"] == ["cash"]


# ── fantasy ─────────────────────────────────────────────────────────────────

R9 = [0.22, 0.09, 0.01, 0.15, 0.045, 0.004, 0.035, 0.22, 0.226]


def test_hitter_line_arithmetic():
    lg = {"sfsh": 0.01}
    ln = F.hitter_line(R9, 600.0, lg, {}, 0.1, 0.8, 0.0, 3.0)
    h = 600 * (0.15 + 0.045 + 0.004 + 0.035)
    ab = 600 * (1 - 0.09 - 0.01 - 0.01)
    assert ln["h"] == pytest.approx(h) and ln["ab"] == pytest.approx(ab) and ln["avg"] == pytest.approx(h / ab)
    assert ln["sb"] == pytest.approx(600 * (0.15 + 0.09 + 0.01) * 0.1 * 0.8) and ln["hr"] == pytest.approx(21.0)


def test_pitcher_line_baseruns_and_ratios():
    lg = {"e": 0.01, "br_mult": 1.0, "er_r": 0.9, "era": 4.2}
    ln = F.pitcher_line(R9, 700.0, 30.0, 30.0, lg, {}, 0.55, 0.0, 0.0, 40.0, 60.0)
    assert ln["ip"] == pytest.approx(ln["outs"] / 3) and ln["era"] == pytest.approx(9 * ln["er"] / ln["ip"])
    assert ln["whip"] == pytest.approx((ln["h"] + ln["bb"]) / ln["ip"]) and 2.0 < ln["era"] < 7.0 and ln["w"] > 0 and ln["sv"] == 0.0
    assert F.baseruns(0, 0, 0, 0, 27) == 0.0


def test_zvalues_order_and_volume_weighted_avg():
    lines = {}
    for i in range(30):
        lines[str(i)] = {"r": 50 + i, "hr": 10 + i / 2, "rbi": 50 + i, "sb": 5, "h": 150, "ab": 550, "avg": 150 / 550}
    lines["hi_avg"] = {"r": 65, "hr": 17, "rbi": 65, "sb": 5, "h": 180, "ab": 550, "avg": 180 / 550}
    z, st = F.zvalues(lines, "H", 20)
    assert z["29"]["total"] > z["0"]["total"] and z["hi_avg"]["z"]["avg"] > z["15"]["z"]["avg"]


def test_replacement_fills_scarce_slots_first():
    vals = {f"c{i}": 1.0 - i * 0.1 for i in range(14)}
    vals.update({f"o{i}": 5.0 - i * 0.01 for i in range(200)})
    elig = {p: (["C", "UT"] if p.startswith("c") else ["OF", "UT"]) for p in vals}
    lvl, taken = F.replacement(vals, elig)
    assert lvl["C"] == pytest.approx(vals["c12"]) and len([p for p in taken if p.startswith("c")]) >= 12


def test_dollars_budget_and_tiers():
    var = {str(i): 30 - i for i in range(40)}
    usd = F.dollars(var, 20, 0.5)
    top = sorted(var, key=lambda p: -var[p])[:20]
    assert sum(usd[p] for p in top) == pytest.approx(F.TEAMS * F.BUDGET * 0.5)
    t = F.tiers([10, 9.8, 9.7, 5, 4.9, 1, 0.9], 3)
    assert t == [1, 1, 1, 2, 2, 3, 3]


def test_points_and_eligibility():
    assert F.points({"hr": 2, "r": 2, "rbi": 3, "so": 4}, "H") == pytest.approx(2 * 4 + 2 + 3 - 4)
    assert F.eligible_slots(["SS", "LF"], "H") == ["SS", "OF", "MI", "UT"]


def test_sb_rates_regress_to_the_speed_prior():
    lines = {2025: {"hitting": {"x": {"pa": 20, "h": 5, "d": 0, "t": 0, "hr": 0, "bb": 2, "hbp": 0, "sb": 4, "cs": 0}}}}
    leagues = {2025: {"att": 0.08, "succ": 0.78}}
    fast, _ = F.sb_rates("x", [2025], lines, leagues, 30.0, {"att": 0.08, "succ": 0.78})
    slow, _ = F.sb_rates("x", [2025], lines, leagues, 25.0, {"att": 0.08, "succ": 0.78})
    none, succ = F.sb_rates("nobody", [2025], lines, leagues, None, {"att": 0.08, "succ": 0.78})
    assert fast > slow and none == pytest.approx(0.08) and succ == pytest.approx(0.78)


def test_current_teams_follow_the_latest_move():
    parsed = M.parse_all([tx(1, "2026-07-30", "TR", "9", "A", "B", "A traded X to B for Y."),
                          tx(2, "2026-11-05", "DFA", "8", None, None, "X elected free agency."),
                          tx(3, "2026-12-01", "SFA", "8", None, "C", "C signed free agent X.")])
    assert FB.current_teams(parsed, "2026-01-01") == {"9": "B", "8": "C"}
