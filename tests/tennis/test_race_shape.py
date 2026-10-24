"""The race page's "how the race is shaping up" fields (round 5, 24 Oct 2026): season_sim.race_extras (bounds, the
certain clinch lines, what is at stake) and race.py's week results and player profiles."""
from __future__ import annotations

from datetime import date

import numpy as np

from oddsmarkets.tennis.analytics import race as RC
from oddsmarkets.tennis.models import season_sim as SS


def _state(race_pts, events, tour="wta", slam_winners=(), strengths=None):
    pids = list(race_pts)
    s = np.array(strengths if strengths is not None else [0.0] * len(pids))
    return {"tour": tour, "players": pids, "rank_pts": {}, "race_pts": race_pts, "drops": {}, "use_snapshot": False,
            "events": events, "logit": lambda a, b: SS._field_logit(s[:, None] - s[None, :], 0, len(pids)),
            "slam_winners": list(slam_winners), "finals": None, "as_of": "2026-10-20"}


def _ev(eid, start, entry, level="250", draw=4, pts=None):
    return {"id": eid, "level": level, "draw_size": draw, "accept": 1.0, "surface": "hard", "best_of": 3, "start": start,
            "entry": entry, "points": pts or {"W": 250, "F": 165, "SF": 100, "R4": 0}}


def test_bounds_and_certain_status():
    # ten players; one 250 left (winner 250): p0-p6 are far clear, p7 and p8 fight for eighth, p9 cannot reach it
    race = {f"p{i}": 3000 - 200 * i for i in range(7)}
    race.update({"p7": 1000, "p8": 900, "p9": 500})
    r = SS.simulate_season(_state(race, [_ev("x-2026", "2026-10-22", {p: 1.0 for p in race})]), n=400)
    assert r["left"]["future_max"] == 250
    assert r["bounds"]["p0"] == [3000, 3250] and r["bounds"]["p9"] == [500, 750]
    assert all(r["status"].get(f"p{i}") == "in" for i in range(7))
    assert "p7" not in r["status"] and "p8" not in r["status"]      # still alive: 900 + 250 > 1000
    assert r["status"]["p9"] == "out"                                # 750 < eight sure totals


def test_atp_slam_champion_takes_eighth_so_eighth_is_not_safe():
    race = {f"p{i}": 3000 - 100 * i for i in range(10)}
    st = _state(race, [], tour="atp", slam_winners=["p9"])
    r = SS.simulate_season(st, n=200)
    # nothing left to play: p0-p6 are certain, p7 sits eighth but the Slam champion p9 (ranked 10th) takes the place
    assert all(r["status"].get(f"p{i}") == "in" for i in range(7))
    assert r["status"].get("p7") != "in"
    assert r["finals_qual"].get("p9") == 1.0 and "p7" not in r["finals_qual"]


def test_stakes_condition_on_the_result_in_the_same_simulations():
    # p7 and p8 tied for the last place, one event left that both enter: whoever goes further qualifies
    race = {f"p{i}": 5000 - 100 * i for i in range(7)}
    race.update({"p7": 1000, "p8": 1000, "p9": 10})
    st = _state(race, [_ev("x-2026", "2026-10-22", {"p7": 1.0, "p8": 1.0, "p9": 1.0, "p6": 1.0})])
    r = SS.simulate_season(st, n=4000, seed=1)
    rows = [s for s in r["stakes"] if s["metric"] == "finals_qual" and s["pid"] == "p7"]
    assert rows, r["stakes"]
    s = rows[0]
    assert s["event"] == "x-2026" and not s["in_progress"] and s["p_enter"] == 1.0
    assert s["if_win"] > s["p"] > s["if_lose"]
    assert s["if_title"] == 1.0
    lv = {x[0]: x[2] for x in s["levels"]}
    assert lv[250.0] == 1.0
    # the levels' shares add up to one (all simulations where the player plays it)
    assert abs(sum(x[1] for x in s["levels"]) - 1.0) < 0.02


def test_week_results_and_profiles():
    class TD:
        current = 2026

        def matches(self, y):
            return {
                "a": {"event": "x-2026", "level": "500", "round": "R32", "date": "2026-10-20", "status": "done", "p1": "1", "p2": "2", "winner": "1"},
                "b": {"event": "x-2026", "level": "500", "round": "R16", "date": "2026-10-22", "status": "done", "p1": "1", "p2": "3", "winner": "3"},
                "c": {"event": "x-2026", "level": "500", "round": "QF", "date": "2026-10-24", "status": "upcoming", "p1": "3", "p2": "4", "winner": None},
                "d": {"event": "old-2026", "level": "500", "round": "F", "date": "2026-10-01", "status": "done", "p1": "5", "p2": "6", "winner": "5"},
                "e": {"event": "y-2026", "level": "250", "round": "F", "date": "2026-10-21", "status": "done", "p1": "5", "p2": "6", "winner": "5"},
                "f": {"event": "q-2026", "level": "250", "round": "Q2", "date": "2026-10-21", "status": "done", "p1": "7", "p2": "8", "winner": "7"},
            }
    w = RC.week_results(TD(), date(2026, 10, 23), ["1", "2", "3", "5", "7"])
    assert w["1"] == [["x-2026", "R16", "L"]]
    assert w["2"] == [["x-2026", "R32", "L"]]
    assert w["3"] == [["x-2026", "QF", "A"]]
    assert w["5"] == [["y-2026", "F", "W"]]                  # last week's final is outside the seven days
    assert "7" not in w                                      # qualifying is not tour level
    nx = RC.next_match(TD(), "4", "x-2026")
    assert nx["opp"] == "3" and nx["round"] == "QF"
    cat = {"year": 2026, "floor": 18, "players": {"1": {"qualified": True, "values": {"elo": 2000.0, "matches": 30}, "pct": {"elo": 97}}}}
    pr = RC.profiles(cat, ["1", "9"])
    assert list(pr["rows"]) == ["1"] and pr["keys"][-1] == "qualified"
    row = dict(zip(pr["keys"], pr["rows"]["1"]))
    assert row["p:elo"] == 97 and row["v:elo"] == 2000.0 and row["qualified"] == 1 and row["p:hold"] is None
    assert RC.profile_ids([[1, "9", 100], [150, "8", 1]], [("1", 10)], top_rank=100) == ["1", "9"]
