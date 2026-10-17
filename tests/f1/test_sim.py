"""Race simulation, championship and circuit-profile tests on planted inputs (offline, no store needed)."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.f1.models import championship as ch
from oddsmarkets.f1.models import circuits as circ
from oddsmarkets.f1.models import race_sim as rs

YEAR = 2030          # no store on disk: rule-based points (25..1, no fastest-lap point)


@pytest.fixture(autouse=True)
def _no_data_checks(monkeypatch):
    monkeypatch.setattr(rs, "fastest_lap_point_in_data", lambda year: None)


def _circuit(**kw):
    c = {"laps": 40, "sprint_laps": 14, "pit_loss_s": 22.0, "sc_rate_per_lap": 0.0, "vsc_rate_per_lap": 0.0, "overtake_threshold_s": 0.9,
         "overtake_scale_s": 0.25, "typical_stops": 1.0, "p_wet": 0.0, "lap1_incident_by_grid": [0.0] * 26}
    c.update(kw)
    return c


def _inputs(n_drivers=10, pace=None, grid=True, hazard=0.0, year=YEAR, **ckw):
    ds = [f"d{i}" for i in range(n_drivers)]
    pace = pace or {}
    return rs.RaceInputs(year=year, round=1, drivers=ds, team={d: f"t{i // 2}" for i, d in enumerate(ds)},
                         pace_mu={d: float(pace.get(d, 0.0)) for d in ds}, pace_sd={d: 0.0 for d in ds},
                         grid={d: i + 1 for i, d in enumerate(ds)} if grid else None, dnf_hazard={d: hazard for d in ds},
                         circuit=_circuit(**ckw), wet=False, p_wet=0.0)


# ----------------------------------------------------------------------------------------------- race

def test_much_faster_car_wins_most_sims():
    inp = _inputs(pace={"d5": -2.0})
    res = rs.simulate_race(inp, n=3000, seed=1)
    assert res["drivers"]["d5"]["p_win"] > 0.85
    assert max(v["p_win"] for d, v in res["drivers"].items() if d != "d5") < 0.1


def test_probabilities_sum_and_one_winner_per_sim():
    inp = _inputs(n_drivers=12, pace={f"d{i}": 0.1 * i for i in range(12)}, hazard=0.004, sc_rate_per_lap=0.02)
    res = rs.simulate_race(inp, n=4000, seed=2, return_samples=True)
    d = res["drivers"]
    assert sum(v["p_win"] for v in d.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(v["p_podium"] for v in d.values()) == pytest.approx(3.0, abs=1e-9)
    pos = res["_samples"]["pos"]
    assert (np.sort(pos, axis=1) == np.arange(1, 13)).all()          # a permutation in every sim: exactly one winner
    dist = np.array([v["pos_dist"] for v in d.values()])
    assert np.allclose(dist.sum(axis=0), 1.0, atol=1e-4) and np.allclose(dist.sum(axis=1), 1.0, atol=1e-4)
    assert sum(v["exp_points"] for v in d.values()) <= res["points_total"] + 1e-9


def test_points_distribution_sums_to_race_total_without_retirements():
    inp = _inputs(n_drivers=20)
    res = rs.simulate_race(inp, n=2000, seed=3, return_samples=True)
    assert res["points_total"] == 101
    assert np.allclose(res["_samples"]["points"].sum(axis=1), 101.0)
    assert sum(v["exp_points"] for v in res["drivers"].values()) == pytest.approx(101.0)
    assert all(v["p_dnf"] == 0 for v in res["drivers"].values())


def test_fastest_lap_point_adds_one_in_seasons_that_had_it():
    inp = _inputs(n_drivers=20, year=2024)
    res = rs.simulate_race(inp, n=1000, seed=4, return_samples=True)
    assert res["points_total"] == 102
    sums = res["_samples"]["points"].sum(axis=1)
    assert set(np.round(sums).astype(int)) == {101, 102}          # no bonus when the fastest lap is set outside the top 10
    pts, pos = res["_samples"]["points"], res["_samples"]["pos"]
    bonus = (pts != np.array(rs.points_system(2024)["race"] + [0] * 10)[pos - 1])
    assert (pos[bonus] <= 10).all() and bonus.sum(axis=1).max() == 1


def test_sprint_uses_sprint_table_and_no_stops():
    inp = _inputs(n_drivers=20)
    res = rs.simulate_sprint(inp, n=1000, seed=5, return_samples=True)
    assert res["laps"] == 14 and res["points_total"] == 36
    assert np.allclose(res["_samples"]["points"].sum(axis=1), 36.0)


def test_safety_car_bunching_shrinks_gaps():
    T = np.array([[100.0, 103.0, 110.0, np.inf, 125.0]])
    running = np.array([[True, True, True, False, True]])
    b = rs.bunch(T, running)
    assert b[0, 0] == 100.0 and np.allclose(np.diff(b[0, [0, 1, 2, 4]]), rs.SC_GAP) and np.isinf(b[0, 3])
    pace = {f"d{i}": 0.3 * i for i in range(10)}
    green = rs.simulate_race(_inputs(pace=pace), n=1500, seed=6, return_samples=True)
    sc = rs.simulate_race(_inputs(pace=pace, sc_rate_per_lap=0.15), n=1500, seed=6, return_samples=True)
    assert sc["p_sc"] > 0.9 and green["p_sc"] == 0
    g_green = np.nanmax(green["_samples"]["gap_to_winner"], axis=1).mean()
    g_sc = np.nanmax(sc["_samples"]["gap_to_winner"], axis=1).mean()
    assert g_sc < 0.7 * g_green


def test_pit_loss_lowers_a_stopping_cars_position():
    base = _inputs(n_drivers=8)
    base.stops = {d: 1 for d in base.drivers}
    base.stops["d0"] = 3                                     # two extra stops for the pole sitter
    cheap = rs.simulate_race(base, n=2000, seed=7)
    base.circuit = _circuit(pit_loss_s=35.0)
    dear = rs.simulate_race(base, n=2000, seed=7)
    others = np.mean([v["exp_pos"] for d, v in cheap["drivers"].items() if d != "d0"])
    assert cheap["drivers"]["d0"]["exp_pos"] > others
    assert dear["drivers"]["d0"]["exp_pos"] > cheap["drivers"]["d0"]["exp_pos"]


def test_grid_sampled_when_no_grid():
    inp = _inputs(grid=False, pace={"d9": -1.5})
    inp.grid_strength = {d: (-2.0 if d == "d9" else 0.0) for d in inp.drivers}
    res = rs.simulate_race(inp, n=2000, seed=8)
    assert res["drivers"]["d9"]["p_win"] > 0.6


def test_wet_widens_the_distribution():
    pace = {f"d{i}": 0.15 * i for i in range(10)}
    dry = rs.simulate_race(_inputs(pace=pace), n=3000, seed=9)
    wet_inp = _inputs(pace=pace)
    wet_inp.wet = True
    wet = rs.simulate_race(wet_inp, n=3000, seed=9)
    assert wet["drivers"]["d0"]["p_win"] < dry["drivers"]["d0"]["p_win"]


def test_empty_inputs_do_not_raise():
    inp = rs.RaceInputs(year=YEAR, round=1, drivers=[], team={}, pace_mu={}, pace_sd={}, grid=None, dnf_hazard={}, circuit={})
    assert rs.simulate_race(inp, n=10)["drivers"] == {}


# ----------------------------------------------------------------------------------------------- points systems

def test_points_systems_per_season():
    assert rs.points_system(2008)["race"] == [10, 8, 6, 5, 4, 3, 2, 1] and rs.points_system(2008)["sprint"] == []
    assert rs.points_system(1998)["race"] == [10, 6, 4, 3, 2, 1]
    p15 = rs.points_system(2015)
    assert p15["race"][0] == 25 and not p15["fastest_lap"] and p15["sprint"] == []
    p21 = rs.points_system(2021)
    assert p21["sprint"] == [3, 2, 1] and p21["fastest_lap"]
    assert rs.points_system(2023)["sprint"] == [8, 7, 6, 5, 4, 3, 2, 1] and rs.points_system(2023)["fastest_lap"]
    assert not rs.points_system(2025)["fastest_lap"]


def test_fastest_lap_point_detected_from_data(monkeypatch):
    def store(fl_bonus):
        races = {}
        for k in range(1, 5):
            races[str(k)] = {"results": [{"driver": "a", "position": 1, "fastest_rank": 2, "points": 25.0},
                                         {"driver": "b", "position": 3, "fastest_rank": 1, "points": 16.0 if fl_bonus else 15.0}]}
        return {"races": races}
    monkeypatch.undo()
    monkeypatch.setattr(circ, "load_store", lambda y: store(True))
    assert rs.fastest_lap_point_in_data(2015) is True
    monkeypatch.setattr(circ, "load_store", lambda y: store(False))
    assert rs.fastest_lap_point_in_data(2022) is False


# ----------------------------------------------------------------------------------------------- championship

def _endgame(pa, pb, counts_a, counts_b, pace_b=0.0):
    state = {"driver_points": {"A": pa, "B": pb}, "team_points": {"ta": pa, "tb": pb},
             "driver_counts": {"A": counts_a + [0] * (10 - len(counts_a)), "B": counts_b + [0] * (10 - len(counts_b))},
             "team_counts": {}, "driver_team": {"A": "ta", "B": "tb"}, "completed": [1], "remaining": [(2, "race")]}
    inp = rs.RaceInputs(year=YEAR, round=2, drivers=["A", "B"], team={"A": "ta", "B": "tb"}, pace_mu={"A": 0.0, "B": pace_b},
                        pace_sd={"A": 0.1, "B": 0.1}, grid={"A": 1, "B": 2}, dnf_hazard={"A": 0.0, "B": 0.0}, circuit=_circuit(), p_wet=0.0)
    return state, [(2, "race", inp)]


def test_endgame_title_equals_closed_form_with_countback():
    # A 100, B 93, one race (25/18): B wins the race -> 118-118; countback: wins 3-3, seconds 2-2, thirds 0-1 -> B.
    state, ev = _endgame(100, 93, [3, 1, 0], [2, 2, 1])
    out = ch.simulate_championship(YEAR, n=4000, seed=10, state=state, events=ev)
    nxt = out["conditionals"]["next_round"]["contenders"]
    p_b_wins = nxt["B"]["p_win_next"]
    assert 0.05 < p_b_wins < 0.95
    assert out["drivers"]["B"]["p_title"] == pytest.approx(p_b_wins, abs=1e-12)        # closed form: P(title) = P(win race)
    assert nxt["B"]["p_title_if_win_next"] == 1.0 and nxt["B"]["p_title_if_not_win_next"] == 0.0
    assert out["drivers"]["A"]["p_title"] + out["drivers"]["B"]["p_title"] == pytest.approx(1.0)


def test_endgame_countback_against_and_out_of_reach():
    state, ev = _endgame(100, 93, [3, 1], [1, 2])          # after a B win: wins 3-2 to A -> A always champion
    out = ch.simulate_championship(YEAR, n=2000, seed=11, state=state, events=ev)
    assert out["drivers"]["A"]["p_title"] == 1.0
    state, ev = _endgame(100, 92, [0], [5])                # 117 < 118 even if B wins
    out = ch.simulate_championship(YEAR, n=2000, seed=12, state=state, events=ev)
    assert out["drivers"]["A"]["p_title"] == 1.0
    assert out["drivers"]["A"]["exp_points"] > 100


def test_countback_key_orders_ties_by_wins():
    pts = np.array([[100.0, 100.0, 99.0]])
    counts = np.zeros((1, 3, 10), int)
    counts[0, 0, 0], counts[0, 1, 0], counts[0, 2, 0] = 1, 2, 9
    pos = ch.rank_by_key(ch.countback_key(pts, counts, 10, 5))
    assert pos.tolist() == [[1, 0, 2]]


def test_magic_numbers():
    m = ch.magic_numbers({"A": 100.0, "B": 80.0, "C": 50.0}, 26)
    assert m["A"]["magic_number"] == 7 and m["A"]["can_clinch_alone"] and not m["A"]["clinched"]
    assert m["B"]["magic_number"] == 47 and not m["B"]["can_clinch_alone"]
    assert m["C"]["eliminated"] and not m["B"]["eliminated"]
    m = ch.magic_numbers({"A": 130.0, "B": 100.0}, 25)
    assert m["A"]["clinched"] and m["A"]["magic_number"] == 0


def test_max_remaining_respects_season_rules():
    rem = [(20, "sprint"), (20, "race"), (21, "race")]
    assert ch.max_remaining(2026, rem)["driver"] == 8 + 25 + 25
    assert ch.max_remaining(2024, rem)["driver"] == 8 + 26 + 26
    assert ch.max_remaining(2026, rem)["team"] == 15 + 43 + 43


# ----------------------------------------------------------------------------------------------- circuits and inputs

def test_status_kinds():
    assert circ.status_kind({"status": "Finished", "position_text": "1"}) == "finished"
    assert circ.status_kind({"status": "Retired", "position_text": "16"}) == "finished"          # classified on distance
    assert circ.status_kind({"status": "Engine", "position_text": "R"}) == "dnf_mech"
    assert circ.status_kind({"status": "Collision", "position_text": "R"}) == "dnf_incident"
    assert circ.status_kind({"status": "Retired", "position_text": "R"}) == "dnf_unknown"
    assert circ.status_kind({"status": "Did not start", "position_text": "W"}) == "dns"
    assert circ.status_kind({"status": "Disqualified", "position_text": "D"}) == "dsq"


def _rec(year, rnd, cid, pit, sc, opp, succ):
    return {"year": year, "round": rnd, "circuit": cid, "laps": 50, "starters": 20, "mech": 1, "incident": 1, "unknown": 0,
            "lap1_by_slot": {}, "starts_by_slot": {str(i): 1 for i in range(1, 21)}, "pit_loss": pit, "neutral_events": sc,
            "green_exposure": 49, "ot_opp": opp, "ot_succ": succ, "ot_delta_sum": 0.6 * opp, "ot_swaps": 0, "ot_car_laps": 0}


def test_circuit_profile_shrinks_by_sample_size():
    recs = [_rec(2020 + i % 5, 1 + i, "x", 20.0, 1, 40, 8) for i in range(40)]
    recs += [_rec(2024, 50, "slow", 30.0, 0, 30, 0)]
    recs += [_rec(2020 + i % 5, 60 + i, "busy", 30.0, 0, 60, 0) for i in range(30)]
    one = circ.circuit_profile("slow", before=(2025, 1), records=recs)
    many = circ.circuit_profile("busy", before=(2025, 1), records=recs)
    g = one["global"]["pit_loss_s"]
    assert g < one["pit_loss_s"] < many["pit_loss_s"] <= 30.0
    assert abs(one["pit_loss_s"] - g) < abs(30.0 - one["pit_loss_s"]) * 2
    assert many["overtake_difficulty"] > one["overtake_difficulty"] > 0.5
    assert many["overtake_threshold_s"] > one["overtake_threshold_s"]
    empty = circ.circuit_profile("nowhere", before=(1990, 1), records=recs)
    assert empty["pit_loss_s"] == pytest.approx(circ.PRIOR["pit_loss_s"]) and empty["laps"] == circ.PRIOR["laps"]


def test_results_only_inputs_rank_the_dominant_driver_first(monkeypatch):
    drivers = [f"d{i}" for i in range(10)]

    def race(order):
        return {"circuit": {"id": "x"}, "date": "2030-01-01", "sessions": {},
                "results": [{"driver": d, "constructor": f"t{int(d[1:]) // 2}", "position": i + 1, "position_text": str(i + 1),
                             "status": "Finished", "grid": i + 1, "laps": 50, "points": 0} for i, d in enumerate(order)],
                "qualifying": [{"driver": d, "constructor": f"t{int(d[1:]) // 2}", "position": i + 1} for i, d in enumerate(order)]}
    order = ["d7"] + [d for d in drivers if d != "d7"]
    store = {"races": {"1": race(order), "2": race(order), "3": race(order), "4": {"circuit": {"id": "x"}, "sessions": {}}}}
    monkeypatch.setattr(circ, "load_store", lambda y: store if y == YEAR else {"races": {}})
    monkeypatch.setattr(circ, "all_records", lambda refresh=False: [])
    inp = rs.race_inputs(YEAR, 4, before_quali=True, use_a=False)
    assert inp.source == "results" and set(inp.drivers) == set(drivers)
    assert min(inp.pace_mu, key=inp.pace_mu.get) == "d7"
    res = rs.simulate_race(inp, n=2000, seed=13)
    assert max(res["drivers"], key=lambda d: res["drivers"][d]["p_win"]) == "d7"
