"""The value section and the trade simulator (analytics/value.py, analytics/trade.py): position grading, candidate
ranking, sample floors, projections, the depth-chart allocation the page mirrors, sensitivity curves from the season
simulation and their interpolation. No network."""
from __future__ import annotations

import pytest

from oddsmarkets.baseball.analytics import trade as TR
from oddsmarkets.baseball.analytics import value as V
from oddsmarkets.baseball.models import synthetic_d as SD

SLOT = {"pa": 650.0, "sp": 4000.0, "rp": 2200.0}


def H(pid, team, pos, war, pa=600, pos_g=None, pos_runs=0.0, age=27.0):
    return {"pid": pid, "name": "P" + pid, "team": team, "kind": "H", "pos": pos, "pos_g": pos_g or {pos: 140.0}, "g": 140, "n": pa,
            "war": war, "rate": war / pa * 600, "pos_runs": pos_runs, "comps": [["Batting", 10.0]], "stat": {}, "age": age}


def P(pid, team, role, war, bf=700, age=28.0):
    return {"pid": pid, "name": "P" + pid, "team": team, "kind": "P", "pos": role, "pos_g": {role: 1.0}, "g": 30, "n": bf, "ip": bf / 4.3,
            "war": war, "rate": war / bf * 700, "comps": [], "stat": {}, "age": age}


def league(n_teams=4):
    """Four clubs; club 'A' is weak at SS and strong at C; 'D' has two good shortstops (surplus) and is out of contention."""
    rows = []
    for i, t in enumerate("ABCD"[:n_teams]):
        for pos in V.HIT_POS:
            war = 2.0 + 0.5 * i
            if t == "A" and pos == "SS":
                war = -0.5
            if t == "A" and pos == "C":
                war = 6.0
            rows.append(H(f"{t}{pos}", t, pos, war))
        for k in range(5):
            rows.append(P(f"{t}SP{k}", t, "SP", 2.0 + 0.3 * i))
        for k in range(7):
            rows.append(P(f"{t}RP{k}", t, "RP", 0.5 + 0.1 * i, bf=280))
    rows.append(H("D_SS2", "D", "SS", 3.4, pa=500))
    return rows


# ── grading ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pct,g", [(100, "A"), (80, "A"), (79.9, "B"), (60, "B"), (45, "C"), (20, "D"), (19, "F"), (0, "F"), (None, None)])
def test_grade_cuts(pct, g):
    assert V.grade(pct) == g


def test_pct_rank_ties_and_direction():
    assert V.pct_rank([1, 2, 3, 4], 4) == pytest.approx(87.5)
    assert V.pct_rank([1, 2, 2, 4], 2) == pytest.approx(50.0)
    assert V.pct_rank([1, 2, 3, 4], 1, lower=True) == pytest.approx(87.5)


def test_position_values_split_war_by_games():
    r = H("x", "A", "SS", 4.0, pos_g={"SS": 90.0, "2B": 30.0})
    pv = V.position_values([r])
    assert pv["A"]["SS"]["war"] == pytest.approx(3.0) and pv["A"]["2B"]["war"] == pytest.approx(1.0)


def test_team_needs_grades_strengths_weaknesses_and_candidates():
    rows = league()
    teams = {t: {"name": t, "abbr": t} for t in "ABCD"}
    out = V.team_needs("mlb", 2026, rows, {}, teams, {"D": {"out": True, "why": "his club missed the postseason"}}, SLOT, 10.0)
    a = out["A"]
    g = {x["pos"]: x for x in a["grades"]}
    assert g["SS"]["grade"] == "F" and g["SS"]["rank"] == 4 and g["C"]["grade"] == "A" and g["C"]["rank"] == 1
    assert "SS" in a["weaknesses"] and "C" in a["strengths"]
    cands = a["improve"]["SS"]
    assert cands, "a weak shortstop should have candidates"
    assert [c["gain"] for c in cands] == sorted([c["gain"] for c in cands], reverse=True)          # ranked by gain
    assert all(c["team"] != "A" for c in cands)                                                    # never his own club
    top = cands[0]
    assert top["team"] == "D" and "his club missed the postseason" in top["hints"]
    assert any("another SS" in h for h in top["hints"])                                            # D has a second shortstop
    assert a["label"].startswith("Model suggestions") and "salar" in a["label"]
    # pitchers are compared slot for slot: a starter's gain is over the club's fifth starter
    assert all(abs(c["proj_ft"]) < 5 for p in ("SP", "RP") for c in a["improve"].get(p, []))


def test_team_needs_sample_floor_and_no_dh():
    rows = league()
    rows.append(H("tiny", "B", "SS", 3.0, pa=40))                    # a hot 40 PA: never a candidate
    teams = {t: {"name": t} for t in "ABCD"}
    out = V.team_needs("npb", 2026, rows, {}, teams, {}, SLOT, 8.3, no_dh={"A", "B"}, no_dh_note="no DH", dh_next=True)
    assert all(c["pid"] != "tiny" for c in out["A"]["improve"]["SS"])
    gA = {x["pos"]: x for x in out["A"]["grades"]}
    assert gA["DH"]["grade"] is None and gA["DH"]["ungraded"] and gA["DH"]["evidence"] == "no DH"
    gC = {x["pos"]: x for x in out["C"]["grades"]}
    assert gC["DH"]["of"] == 2                                         # graded among the clubs that used the DH
    assert "DH" in out["A"]["weaknesses"] and out["A"]["improve"]["DH"]  # adopting the DH next season: a need


def test_value_payload_floors_and_best():
    rows = league()
    rows.append(H("small", "B", "LF", 1.0, pa=60))
    d = V.value_payload("mlb", 2026, rows, None, None, 160, "offseason")
    F = {f: i for i, f in enumerate(d["fields"])}
    by = {r[F["pid"]]: r for r in d["rows"]}
    assert d["floors"]["H"] == 336 and by["small"][F["pct"]] is None and by["ASS"][F["pct"]] is not None
    assert [x[0] for x in d["best"]["C"]][0] == "AC"                  # the best catcher first
    assert all(x[0] != "small" for x in d["best"]["LF"])               # under half the floor


def test_value_payload_ranks_starters_and_relievers_apart():
    """Pitchers' WAR percentiles are within the role (starters with starters, relievers with relievers), each with the
    spec's floor (300 / 120 BF x team games / 162): a reliever is never ranked against starters' innings."""
    rows = [P("s1", "A", "SP", 5.0, bf=800), P("s2", "B", "SP", 1.0, bf=700), P("r1", "A", "RP", 1.5, bf=280),
            P("r2", "B", "RP", 0.2, bf=250), P("rsmall", "C", "RP", 0.1, bf=100)]
    d = V.value_payload("mlb", 2026, rows, None, None, 162, "offseason")
    assert d["floors"]["SP"] == 300 and d["floors"]["RP"] == 120 and V.floors("mlb", 81)["RP"] == 60
    F = {f: i for i, f in enumerate(d["fields"])}
    by = {r[F["pid"]]: r for r in d["rows"]}
    assert by["r1"][F["pct"]] == 75 and by["r2"][F["pct"]] == 25      # top and bottom of the two qualified relievers
    assert by["s1"][F["pct"]] == 75 and by["s2"][F["pct"]] == 25
    assert by["rsmall"][F["pct"]] is None                              # under the relievers' 120 BF


# ── projections ─────────────────────────────────────────────────────────────

def test_marcel_weights_and_regression():
    h = {2024: {"war": 6.0, "n": 600}, 2025: {"war": 3.0, "n": 600}}
    r, nw = V._marcel(h, 2026, "H", 0.0, 2.0)
    assert nw == pytest.approx(5 * 600 + 4 * 600)
    assert r == pytest.approx((5 * 3.0 + 4 * 6.0) / (9 * 600) * 600)
    r2, _ = V._marcel(h, 2026, "H", 1e9, 2.0)
    assert r2 == pytest.approx(2.0, abs=1e-3)                          # infinite regression: the league rate


def test_fit_projection_beats_last_season_on_noisy_talent():
    import numpy as np
    rng = np.random.default_rng(5)
    hist = {}
    for i in range(300):
        talent = rng.normal(2.0, 1.5)
        h = {}
        for s in range(2015, 2027):
            n = 600
            h[s] = {"war": float(rng.normal(talent, 1.6)) * n / 600, "n": n}
        hist["H:" + str(i)] = h
    f = V.fit_projection(hist, list(range(2015, 2027)), "H")
    v = f["validation"]["rmse"]
    assert v["projection"] < v["last_season"] and v["projection"] < v["league_rate"]
    assert f["k_final"] in V.K_GRID["H"]


def test_age_delta_zero_at_28():
    assert V.age_delta([0.1, -0.05, -0.002], 28) == pytest.approx(0.0)
    assert V.age_delta([0.1, -0.05, -0.002], 34) < 0 < V.age_delta([0.1, -0.05, -0.002], 24)
    assert V.age_delta([0.1, -0.05, -0.002], None) == 0.0


# ── the depth-chart allocation and the trade delta ──────────────────────────

def test_allocate_caps_availability_and_replacement():
    roster = [{"pid": "c1", "ft": {"C": 4.0, "DH": 1.0}}, {"pid": "c2", "ft": {"C": 1.0}}, {"pid": "ss", "ft": {"SS": 3.0, "2B": 2.5}}]
    al = TR.allocate(roster)
    assert al["share"]["c1"]["C"] == pytest.approx(0.8) and al["share"]["c2"]["C"] == pytest.approx(0.2)
    assert al["share"]["ss"]["SS"] == pytest.approx(0.95) and "2B" in al["share"]["ss"]     # his last 5% go to 2B
    assert al["repl"]["2B"] == pytest.approx(0.95) and al["repl"]["CF"] == pytest.approx(1.0)
    assert al["share"]["c1"]["DH"] == pytest.approx(0.2)                                  # what is left of him
    assert al["wins"] == pytest.approx(0.8 * 4 + 0.2 * 1 + 0.95 * 3 + 0.05 * 2.5 + 0.2 * 1.0)
    assert "DH" not in (TR.allocate(roster, dh=False)["share"].get("c1") or {})


def test_allocate_rotation_and_bullpen():
    roster = [{"pid": f"s{i}", "ft": {"SP": 10.0 - i, "RP": 3.0}} for i in range(7)]
    al = TR.allocate(roster)
    sp = {p: v.get("SP", 0) for p, v in al["share"].items()}
    assert sum(sp.values()) == pytest.approx(1.0) and sp["s0"] == pytest.approx(0.2) and sp.get("s5", 0) == 0
    assert sum(v.get("RP", 0) for v in al["share"].values()) == pytest.approx(1.0)


def test_trade_delta_noop_and_displacement():
    a = [{"pid": "a1", "ft": {"SS": 1.0}}, {"pid": "a2", "ft": {"CF": 2.0}}]
    assert TR.trade_delta(a, set(), [])["delta"] == pytest.approx(0.0)
    star = {"pid": "x", "ft": {"SS": 5.0}}
    d = TR.trade_delta(a, {"a2"}, [star])
    # the star takes 95% of short; the old shortstop keeps the last 5%; centre field is left to replacement level
    assert d["delta"] == pytest.approx((0.95 * 5.0 + 0.05 * 1.0) - (0.95 * 1.0 + 0.95 * 2.0), abs=1e-6)
    assert d["displaced"][0][0] == "a1" and d["displaced"][0][1] == pytest.approx(0.90)


# ── sensitivity curves and their interpolation ──────────────────────────────

def test_interp():
    c = {"exp_w": [70, 80, 90], "p_post": [0.1, 0.5, 0.9]}
    assert TR.interp(c, 80, "p_post") == pytest.approx(0.5)
    assert TR.interp(c, 85, "p_post") == pytest.approx(0.7)
    assert TR.interp(c, 60, "p_post") == pytest.approx(0.1) and TR.interp(c, 99, "p_post") == pytest.approx(0.9)
    assert TR.interp({"exp_w": [90, 70, 80], "p_post": [0.9, 0.1, 0.5]}, 75, "p_post") == pytest.approx(0.3)   # unsorted input
    assert TR.interp({}, 80, "p_post") is None


@pytest.mark.parametrize("played", [1.0, 0.4])
def test_mlb_curves_from_the_season_simulation(monkeypatch, played):
    monkeypatch.setattr(TR, "SHIFT_WINS", (-6.0, 0.0, 6.0))
    st, r = SD.quick_store(seed=4, games_per_pair=2, played_frac=played)
    out = TR.mlb_curves(st, 2027, n=300, carry={"carry": 0.5, "sd": 0.1})
    assert out["horizon"] == ("next" if played == 1.0 else "rest")
    assert len(out["curves"]) == 30
    for t, c in out["curves"].items():
        assert c["exp_w"] == sorted(c["exp_w"])
        assert c["p_post"][0] <= c["p_post"][-1] + 0.02 and c["p_title"][0] <= c["p_title"][-1] + 0.02
        assert TR.interp(c, out["base"][t]["exp_w"], "p_post") == pytest.approx(out["base"][t]["p_post"], abs=1e-6)
    # a better club gains more wins from a shift of the same size? at least every curve moves the right way
    assert sum(c["exp_w"][-1] - c["exp_w"][0] for c in out["curves"].values()) > 0


# ── NPB rows and the build's write rule ─────────────────────────────────────

def test_rows_npb_sums_a_traded_player_and_reads_positions():
    players = {"ok": True, "war_meta": {"rpw": 8.0},
               "bat": [{"pid": "n1", "name": "A", "team": "91001", "pa": 300, "g": 70, "war": 1.0, "bat_runs": 5.0, "br_runs": 0.5, "pos_runs": 1.0,
                        "pos": "SS", "pos_g": {"SS": 60}},
                       {"pid": "n1", "name": "A", "team": "91002", "pa": 200, "g": 50, "war": 0.5, "bat_runs": 2.0, "br_runs": 0.0, "pos_runs": 0.5,
                        "pos": "SS", "pos_g": {"SS": 40, "2B": 5}},
                       {"pid": "n9", "name": "P", "team": "91001", "pa": 3, "pitcher": True, "war": 0.0}],
               "pit": [{"pid": "n2", "name": "B", "team": "91003", "bf": 600, "g": 25, "outs": 450, "war": 3.0, "fip": 3.0, "role": "SP"},
                       {"pid": "n3", "name": "C", "team": "91003", "bf": 250, "g": 55, "outs": 180, "war": 1.0, "fip": 2.5, "role": "RP"}]}
    from oddsmarkets.baseball.npb import valuebuild as VBN
    rows = V.rows_npb(players, VBN.positions_of(players), {"n1": 28.0})
    a = next(r for r in rows if r["pid"] == "n1")
    assert a["team"] == "91001" and a["n"] == 500 and a["war"] == pytest.approx(1.5) and a["age"] == 28.0
    assert a["pos_g"] == {"SS": 100.0, "2B": 5.0} and a["pos"] == "SS"
    assert not any(r["pid"] == "n9" for r in rows)                     # pitchers batting are not hitters
    roles = {r["pid"]: r["pos"] for r in rows if r["kind"] == "P"}
    assert roles == {"n2": "SP", "n3": "RP"}


def test_write_if_changed(tmp_path):
    from oddsmarkets.baseball.analytics import value_build as VB

    class B:
        data = tmp_path
        n = 0

        def write(self, rel, payload):
            B.n += 1
            import json
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload), encoding="utf-8")
    b = B()
    assert VB.write_if_changed(b, "x/v.json", {"ok": True, "updated_at": "1", "a": 1.5})
    assert not VB.write_if_changed(b, "x/v.json", {"ok": True, "updated_at": "2", "a": 1.5})   # only the stamp moved
    assert VB.write_if_changed(b, "x/v.json", {"ok": True, "updated_at": "3", "a": 2.0})
    assert B.n == 2


def test_value_ft_positional_swap_and_small_samples():
    ss = H("ss", "A", "SS", 3.0, pa=600, pos_g={"SS": 150.0})
    at_ss = V.value_ft(ss, "SS", 3.0, SLOT, 10.0)
    at_1b = V.value_ft(ss, "1B", 3.0, SLOT, 10.0)
    assert at_ss - at_1b == pytest.approx((7.5 + 12.5) / 10.0)                    # SS +7.5 against 1B -12.5 runs
    # a defensive replacement with 6 PA in 40 games: the positional part comes from his shares, not runs per PA
    sub = H("sub", "A", "LF", 0.0, pa=6, pos_g={"LF": 40.0}, pos_runs=-1.85)
    assert abs(V.value_ft(sub, "LF", 1.0, SLOT, 8.3) - 1.0 * SLOT["pa"] / 600) < 0.05


def test_allocate_respects_availability():
    roster = [{"pid": "reg", "ft": {"SS": 2.0}, "avail": 1.0}, {"pid": "callup", "ft": {"SS": 3.0}, "avail": 0.3},
              {"pid": "sp1", "ft": {"SP": 10.0}, "avail_sp": 0.5}]
    al = TR.allocate(roster)
    assert al["share"]["callup"]["SS"] == pytest.approx(0.3) and al["share"]["reg"]["SS"] == pytest.approx(0.7)
    assert al["share"]["sp1"]["SP"] == pytest.approx(0.1)                          # half of a fifth of the starts


def test_forty_man_rows_take_the_roster_feeds_name():
    """A 40-man player with no game this season is named from the roster feed (not shown as his MLBAM id)."""
    from types import SimpleNamespace
    from oddsmarkets.baseball.analytics import teams as TM
    ctx = SimpleNamespace(store={"meta": {"rosters": {"109": {"40man": ["691009"], "injured": [], "names": {"691009": "Rookie Arm"},
                                                             "pos": {"691009": "P"}}}}},
                          players={}, name=lambda pid: str(pid))
    rows = TM.roster(ctx, "109", {}, {})
    assert rows == [{"pid": "691009", "name": "Rookie Arm", "pos": "P", "kind": "40man", "injured": None}]
