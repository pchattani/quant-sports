"""Paddock analytics on synthetic stores: percentile direction, team-mate gaps, overtakes per race,
season aggregation, awards selection, dropped scores and the race payload shape (offline)."""
from __future__ import annotations

import pytest

from oddsmarkets.f1.analytics import percentiles
from oddsmarkets.f1.analytics import awards as aw
from oddsmarkets.f1.analytics import context
from oddsmarkets.f1.analytics import drivers as drv
from oddsmarkets.f1.analytics import races as rc
from oddsmarkets.f1.analytics import season as ssn

from .conftest import YEAR, number, payload_keys


# ------------------------------------------------------------------------------------------ percentiles

def test_percentile_direction_ties_and_singletons():
    vals = {"a": 1.0, "b": 2.0, "c": 3.0, "d": None}
    assert percentiles(vals) == {"a": 0, "b": 50, "c": 100}               # higher is better
    assert percentiles(vals, lower=True) == {"a": 100, "b": 50, "c": 0}   # lower is better: smallest ranks best
    assert percentiles({"a": 1.0, "b": 1.0, "c": 0.0}) == {"a": 75, "b": 75, "c": 0}
    assert percentiles({"x": 5.0}) == {"x": 50}
    assert percentiles({}) == {}


def test_catalogue_is_complete_and_defined():
    from oddsmarkets.f1.analytics.glossary import DRIVER_DEFINITIONS, TEAM_DEFINITIONS, build_glossary
    from oddsmarkets.f1.analytics.teams import METRICS as TM
    assert len(drv.METRICS) >= 70
    assert {m["group"] for m in drv.METRICS} == set(drv.GROUPS)
    assert all(DRIVER_DEFINITIONS.get(m["key"]) for m in drv.METRICS)
    assert all(TEAM_DEFINITIONS.get(m["key"]) for m in TM)
    g = build_glossary()
    assert set(g) >= {"groups", "model"}
    for grp in g["groups"]:
        for e in grp["entries"]:
            assert set(e) >= {"key", "label", "desc", "fmt", "lower", "scope"}
    keys = {t["key"] for t in g["model"]}
    for k in ("lap_time_model", "fuel_correction", "tyre_degradation", "traffic", "car_effect", "driver_effect", "random_walk",
              "elo_field", "elo_teammate", "elo_quali", "plackett_luce", "monte_carlo_race_sim", "safety_car_hazard", "pit_loss",
              "overtaking_threshold", "magic_number", "countback", "de_vig", "edge", "log_loss", "brier", "calibration", "percentile",
              "shrinkage"):
        assert k in keys


# ------------------------------------------------------------------------------------------ per-race records

def test_teammate_quali_gap_and_head_to_head(paddock_data):
    recs = drv.race_records(YEAR, 2)
    race = context.get(YEAR, 2)
    q = {r["driver"]: r for r in race.qualifying}
    # drv0 and drv1 share team0; both reached Q3 -> the gap is the Q3 difference
    assert recs["drv0"]["quali_gap_tm_ms"] == q["drv0"]["q3"] - q["drv1"]["q3"]
    assert recs["drv1"]["quali_gap_tm_ms"] == -recs["drv0"]["quali_gap_tm_ms"]
    ahead = q["drv0"]["position"] < q["drv1"]["position"]
    assert recs["drv0"]["quali_h2h"] == [1.0 if ahead else 0.0]
    pole = next(r for r in race.qualifying if r["position"] == 1)
    assert recs[pole["driver"]]["quali_gap_pole_pct"] == pytest.approx(0.0)
    # the engine failure in round 2 is a mechanical DNF, not classified
    assert recs["drv3"]["kind"] == "dnf_mech" and not recs["drv3"]["classified"]


def test_overtakes_per_race_filters_pit_and_safety_car_passes(paddock_data):
    ctx = context.get(YEAR, 1)
    passes = ctx.overtakes()
    assert [(p["by"], p["on"]) for p in passes] == [("drv1", "drv0"), ("drv1", "drv2")]
    assert ctx.penalties() == {"drv2": 1}                    # the "PENALTY SERVED" notice is not a second penalty
    assert {w["kind"] for w in ctx.neutral_windows()} == {"SC"}   # the chequered flag is not a red flag
    recs = drv.collect(YEAR)
    v = drv.season_values(recs["drv1"])
    # 2 passes in the one race with OpenF1 data -> 2.0 per race (rounds without a session do not dilute it)
    assert v["overtakes_made"] == pytest.approx(2.0)
    assert v["overtakes_suffered"] == pytest.approx(0.0)
    assert drv.season_values(recs["drv0"])["overtakes_suffered"] == pytest.approx(1.0)
    assert drv.season_values(recs["drv2"])["penalties"] == 1


def _rec(rnd, team="t", points=0.0, exp=None, pos=1, kind="finished", grid=1, **kw):
    r = {"round": rnd, "name": f"R{rnd}", "team": team, "started": kind != "dns", "kind": kind, "status": "x", "pos": pos,
         "classified": kind == "finished", "points": points, "grid": grid, "grid_raw": grid, "laps": 50, "race_laps": 50,
         "fastest_rank": None, "mates": []}
    if exp is not None:
        r["exp_points"] = exp
    r.update(kw)
    return r


def test_season_values_points_v_expected_and_reliability():
    recs = {1: _rec(1, points=25.0, exp=15.0, pos=1, grid=3, pos_gained=2),
            2: _rec(2, points=0.0, exp=8.0, pos=18, kind="dnf_mech", grid=4),
            3: _rec(3, points=18.0, exp=20.0, pos=2, grid=2, pos_gained=0),
            4: _rec(4, kind="dns", pos=20)}
    v = drv.season_values(recs)
    assert v["races"] == 3 and v["dns"] == 1
    assert v["exp_points"] == pytest.approx(43.0)
    assert v["points_v_expected"] == pytest.approx(43.0 - 43.0)
    assert v["points_lost_dnf"] == pytest.approx(8.0)
    assert v["dnf_mech"] == 1 and v["dnf_rate"] == pytest.approx(1 / 3)
    assert v["pos_gained"] == pytest.approx(1.0)
    assert v["avg_finish"] == pytest.approx(1.5)
    assert v["wins"] == 1 and v["podiums"] == 2


def test_driver_catalogue_percentiles_and_teammate_percentiles(paddock_data):
    out = drv.build(YEAR)
    ds = out["drivers"]
    assert len(ds) == 10 and len(out["metrics"]) == len(drv.METRICS)
    # drv0 is planted fastest: best average qualifying position -> field percentile 100 on a lower-is-better metric
    best = min(ds, key=lambda d: ds[d]["values"]["avg_quali"])
    assert ds[best]["pct"]["avg_quali"] == 100
    # team-mate percentiles are 0/100 within a two-car team (ties 50)
    a, b = ds["drv0"]["pct_teammate"].get("avg_quali"), ds["drv1"]["pct_teammate"].get("avg_quali")
    assert {a, b} <= {0, 50, 100} and a + b == 100
    row = ds["drv0"]["log"][0]
    assert set(row) >= {"round", "name", "grid", "pos", "status", "points", "quali_pos", "pace", "pace_rank", "pos_gained",
                        "lap1_gain", "overtakes", "pit_stops", "deg"}


# ------------------------------------------------------------------------------------------ awards

def test_awards_selection(paddock_data):
    ctx = context.get(YEAR, 2)
    res = {r["driver"]: r for r in ctx.results}
    # forecast: everyone expected their actual points except drv7, expected 0 but scored; and drv3 (DNF) expected 10
    exp = {d: {"exp_points": r["points"], "pos_dist": [0.1] * 10} for d, r in res.items()}
    lucky = next(d for d, r in res.items() if r["points"] > 0 and d not in ("drv0", "drv1"))
    exp[lucky]["exp_points"] = 0.0
    exp["drv3"]["exp_points"] = 10.0
    out = aw.race_awards(YEAR, 2, {"post": {"drivers": exp}})
    assert out["driver_of_the_day"]["driver"] == lucky
    assert out["driver_of_the_day"]["value"] == pytest.approx(res[lucky]["points"])
    assert out["team_of_weekend"]["team"] == res[lucky]["constructor"]
    assert out["unluckiest"]["driver"] == "drv3"              # engine failure while running in the points
    assert out["fastest_stop"]["driver"] == "drv0"            # lowest Jolpica pit-lane time (no stationary times)
    assert "pit lane" in out["fastest_stop"]["label"]
    back = out["best_drive_from_back"]
    if back:
        assert res[back["driver"]]["grid"] > res[back["driver"]]["position"]
    for k in aw.KEYS:
        if out[k] is not None:
            assert out[k].get("why")


def test_awards_with_openf1_session(paddock_data):
    out = aw.race_awards(YEAR, 1, {})
    assert out["fastest_stop"]["driver"] == "drv0" and out["fastest_stop"]["value"] == 2300   # OpenF1 stationary time wins
    assert out["driver_of_the_day"] is not None                                              # no forecast: positions gained
    assert out["team_of_weekend"] is None


def test_strategy_gains_are_relative_to_the_race_norm(paddock_data):
    g = aw.strategy_gains(context.get(YEAR, 2))
    assert g and sum(g.values()) == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------------------------------ standings

def test_dropped_scores_rule():
    assert ssn._counted([9, 6, 0, 4, 9, 2], [(None, 4)]) == 28
    assert ssn._counted([9, 6, 0, 4, 9, 2, 6], [(3, 2), (None, 3)]) == 15 + 19
    assert ssn._counted([1, 2, 3], None) == 6


def test_standings_countback(paddock_data):
    st = ssn.standings(YEAR)
    pts = [r["points"] for r in st["drivers"]]
    assert pts == sorted(pts, reverse=True) and st["drivers"][0]["pos"] == 1
    assert {r["team"] for r in st["constructors"]} == {f"team{j}" for j in range(5)}


# ------------------------------------------------------------------------------------------ race payload

def test_race_payload_shape_done_and_upcoming(paddock_data):
    keys = payload_keys()["race"]
    done = rc.build_race(YEAR, 1, {"pre": None, "post": None})
    assert set(done) >= keys and done["status"] == "done"
    assert done["laps"]["n"] == 20 and done["laps"]["positions"]["drv0"]
    assert done["stints"]["drv0"][0] == {"compound": "MEDIUM", "from": 1, "to": 10, "age_start": 0}
    assert {p["driver"] for p in done["pits"]} >= {"drv0"} and done["pits"][0]["stop_ms"] is not None
    assert [o["by"] for o in done["overtakes"]] == ["drv1", "drv1"]
    assert set(done["awards"]) == set(aw.KEYS)
    assert done["sessions"]["race"] == 9001 and done["telemetry"] == {"race": False, "quali": False}
    win = next(r for r in done["results"] if r["pos"] == 1)
    assert win["gap_ms"] == 0
    q = done["qualifying"]
    assert q[0]["gap_ms_to_pole"] == 0 and all("teammate_gap_ms" in r for r in q)
    up = rc.build_race(YEAR, 5, {"pre": {"drivers": {}, "teams": {}, "p_sc": 0.3, "generated_at": "x"}, "post": None})
    assert set(up) >= keys and up["status"] == "upcoming"
    assert up["results"] == [] and up["laps"]["positions"] == {} and all(v is None for v in up["awards"].values())
    assert up["forecast"]["pre_quali"]["p_sc"] == 0.3 and up["forecast"]["post_quali"] is None


def test_race_payload_without_laps_or_sessions(paddock_data):
    # the previous season has Jolpica laps but no OpenF1 session: laps come from the store, overtakes are empty
    p = rc.build_race(YEAR - 1, 2, None)
    assert p["ok"] and p["laps"]["source"] == "jolpica" and p["overtakes"] == []
    assert p["stints"]["drv0"][0]["compound"] is None


def test_final_lap_agrees_with_classification(paddock_data):
    ctx = context.get(YEAR, 1)
    res = sorted((r for r in ctx.results if r["position_text"].isdigit()), key=lambda r: r["position"])
    a, b = res[0]["driver"], res[1]["driver"]
    n = 20
    # timestamp jitter swapped the two leaders on the last lap; the payload must follow the result
    lt = {"n": n, "positions": {a: [1] * (n - 1) + [2], b: [2] * (n - 1) + [1]},
          "gaps": {a: [0.0] * (n - 1) + [0.003], b: [0.5] * (n - 1) + [0.0]}, "times": {}, "source": "openf1"}
    out = ctx._align_finish(lt)
    assert out["positions"][a][-1] == 1 and out["positions"][b][-1] == 2
    assert out["gaps"][a][-1] == 0.0
    assert out["gaps"][b][-1] == pytest.approx((res[1]["time_ms"] - res[0]["time_ms"]) / 1000.0, abs=1e-3)
    assert out["positions"][a][:-1] == [1] * (n - 1)          # earlier laps untouched
    # and the real assembled table already agrees
    lap = ctx.laps()
    last = {d: lap["positions"][d][-1] for d in (a, b)}
    assert last[a] < last[b]


def test_chequered_flag_is_not_a_red_flag(paddock_data):
    kinds = {c["message"]: c["kind"] for c in context.get(YEAR, 1).control()}
    assert kinds["CHEQUERED FLAG"] == "FLAG"


def test_expected_v_actual_percentile():
    rows = [{"driver": "a", "position": 1, "position_text": "1", "status": "Finished", "points": 25}]
    sim = {"drivers": {"a": {"pos_dist": [0.2, 0.3, 0.5], "exp_pos": 2.3, "exp_points": 15}}}
    e = rc.expected_v_actual(rows, sim)["a"]
    assert e["pctile_of_actual"] == pytest.approx(100 * (0.8 + 0.1))


def test_red_flag_test_does_not_match_the_chequered_flag() -> None:
    import re
    assert re.search(r"(?<![A-Z])RED FLAG", "CHEQUERED FLAG") is None
    assert re.search(r"(?<![A-Z])RED FLAG", "RED FLAG - RACE SUSPENDED") is not None


def _hist_store(name_rows: list[tuple[str, list[tuple[str, str, int, float]]]]) -> dict:
    """A tiny season store: rounds of (race name, [(driver, constructor, position, points)])."""
    races = {}
    for i, (name, rows) in enumerate(name_rows, 1):
        races[str(i)] = {"name": name, "results": [{"driver": d, "constructor": t, "position": p, "position_text": str(p),
                                                    "points": pts, "status": "Finished", "grid": p} for d, t, p, pts in rows]}
    return {"races": races, "drivers": {}, "constructors": {}}


def test_1958_constructors_skip_indy_and_the_fastest_lap_point(monkeypatch):
    store = _hist_store([
        ("Argentine Grand Prix", [("moss", "cooper", 1, 8.0), ("musso", "ferrari", 2, 6.0), ("fangio", "maserati", 4, 4.0)]),
        ("Belgian Grand Prix", [("brooks", "vanwall", 1, 8.0), ("hawthorn", "ferrari", 2, 7.0)]),   # 6 + fastest lap
        ("Indianapolis 500", [("bryan", "epperly", 1, 8.0), ("amick", "epperly", 2, 6.0)]),
        ("Monaco Grand Prix", [("trintignant", "cooper", 1, 8.0), ("hawthorn", "ferrari", 11, 1.0)]),  # fastest lap only
    ])
    monkeypatch.setattr(ssn.canon, "season", lambda y: store)
    st = ssn.standings(1958)
    cons = {r["team"]: r["points"] for r in st["constructors"]}
    assert "epperly" not in cons                                   # Indy-only constructor: no constructors' entry
    assert cons["ferrari"] == 12.0 and cons["maserati"] == 3.0     # position table, no fastest-lap point
    assert cons["cooper"] == 16.0 and cons["vanwall"] == 8.0
    drv = {r["driver"]: r["points"] for r in st["drivers"]}
    assert drv["bryan"] == 8.0 and drv["hawthorn"] == 8.0          # drivers keep the Indy 500 and the fastest-lap point
    prog = ssn.progression(1958)
    assert "epperly" not in prog["constructors"] and prog["constructors"]["ferrari"][-1] == 12.0


def test_championship_exclusions(monkeypatch):
    store = _hist_store([
        ("Race A", [("michael_schumacher", "ferrari", 1, 10.0), ("villeneuve", "williams", 2, 6.0), ("hakkinen", "mclaren", 3, 4.0)]),
        ("Race B", [("villeneuve", "williams", 1, 10.0), ("michael_schumacher", "ferrari", 2, 6.0), ("raikkonen", "mclaren", 3, 4.0)]),
    ])
    monkeypatch.setattr(ssn.canon, "season", lambda y: store)
    st = ssn.standings(1997)
    assert st["drivers"][0]["driver"] == "villeneuve"
    last = st["drivers"][-1]
    assert last["driver"] == "michael_schumacher" and last["points"] == 0.0 and last["points_gross"] == 16.0
    assert last["excluded"] and last["pos"] == len(st["drivers"]) and last["wins"] == 1
    st = ssn.standings(2007)
    assert st["constructors"][0]["team"] == "ferrari" and st["constructors"][-1]["team"] == "mclaren"
    assert st["constructors"][-1]["points"] == 0.0 and st["constructors"][-1]["excluded"]
    assert all(not r.get("excluded") for r in ssn.standings(2008)["constructors"])
