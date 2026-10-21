"""Player value, strengths and needs, and the trade simulator's inputs (docs/VALUE_SECTIONS.md): replacement
levels and sample floors, position grading, candidate ranking, the season simulation's shift / record options and
the importance-sampled sensitivity curves, the contracts gate. Synthetic data only (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy.special import ndtr

from oddsmarkets.nfl.analytics import contracts as CT
from oddsmarkets.nfl.analytics import value as VL
from oddsmarkets.nfl.models import season_sim as SS
from oddsmarkets.nfl.models import synthetic_c as SC
from oddsmarkets.nfl.models import team_strength as TS


# ── a synthetic catalogue ────────────────────────────────────────────────────

def _player(group, team, games=10, q=True, pos=None, **values):
    return {"name": f"{group}-{team}-{len(values)}", "team": team, "pos": pos or group, "group": group, "age": 26.0, "games": games,
            "qualified": q, "values": values}


def _catalogue():
    P = {}
    # ten WRs: receiver rates 0.00 .. 0.18 per target, 80 targets each; one small-sample WR far above (not qualified)
    for i in range(10):
        P[f"wr{i}"] = _player("WR", "T%d" % (i % 4), value=0.02 * i * 80)
    P["wrsmall"] = _player("WR", "T0", games=2, q=False, value=3.0)
    # defenders: splash EPA per game 0.5 .. 2.4 over 10 games
    for i in range(6):
        P[f"cb{i}"] = _player("DEF", "T%d" % (i % 4), pos="CB", def_value=10 * (0.5 + 0.38 * i), sacks=0, pd=3 + i, ints=i % 2)
    # kickers
    for i in range(6):
        P[f"k{i}"] = _player("K", "T%d" % (i % 4), fga=20, pts_oe=-3.0 + 1.5 * i, fg_oe=-1 + 0.5 * i, fg_50=i, fg_pct=0.8)
    return {"ok": True, "team_games": 10, "players": P}


def _pv():
    rows = [{"player": f"wr{i}", "role": "receiver", "adj_per_play": 0.02 * i, "adj_plays": 80} for i in range(10)]
    rows.append({"player": "wrsmall", "role": "receiver", "adj_per_play": 0.5, "adj_plays": 6})
    return {"players": rows}


def test_replacement_level_and_sample_floors():
    recs, repl = VL.player_records(2025, _catalogue(), _pv(), None, {})
    # the replacement rate is the 20th percentile of the qualified-volume rates; the 6-target WR does not set it
    exp = float(np.quantile([0.02 * i for i in range(10)], VL.REPL_Q))
    assert repl["WR"]["receiver"] == pytest.approx(exp, abs=1e-4)
    assert recs["wr9"]["gvar"] == pytest.approx((0.18 - exp) * 80, abs=1e-3)
    assert recs["wr0"]["gvar"] < 0 < recs["wr9"]["gvar"]
    assert recs["wr9"]["gvar_pg"] == pytest.approx(recs["wr9"]["gvar"] / 10)
    # defenders: shrunk per game toward the position mean, then replacement; values rise with the raw rate
    d = [recs[f"cb{i}"]["gvar"] for i in range(6)]
    assert d == sorted(d) and recs["cb0"]["pos"] == "CB"
    # kickers: points over expected shrunk per attempt (k = 60) less the 20th percentile
    sh = [(-3.0 + 1.5 * i) / (20 + VL.K_K) for i in range(6)]
    assert repl["K"]["per_fga"] == pytest.approx(float(np.quantile(sh, VL.REPL_Q)), abs=1e-4)


def test_value_payload_best_lists_only_qualified():
    recs, repl = VL.player_records(2025, _catalogue(), _pv(), None, {})
    v = VL.value_payload(2025, recs, repl, {"wr9": 0.5}, "regular", 10, False)
    assert v["ok"] and v["cols"][0] == "pid"
    assert "wrsmall" not in v["best"]["WR"] and v["best"]["WR"][0] == "wr9"
    rows = {r[0]: dict(zip(v["cols"], r)) for r in v["rows"]}
    assert rows["wrsmall"]["pct"] is None and rows["wr9"]["pct"] == 100
    assert rows["wr9"]["trend"] == pytest.approx(rows["wr9"]["gv"] / 10 - 0.5, abs=0.01)


def test_def_position_tiers():
    assert VL.def_position("x", "DE", {"ngs": "INTERIOR_LINE"}, {"pff": "ED"}) == "DL"       # the weekly roster first
    assert VL.def_position("x", "OLB", {}, {"pff": "ED"}) == "EDGE"
    assert VL.def_position("x", "OLB", {}, {}) == "LB"
    assert VL.def_position("x", "SAF", {}, {}) == "S"
    assert VL.def_position("x", "DT", {}, {}, "EDGE") == "EDGE"                               # the depth chart before the list


def test_starters_model_grading_and_displacement():
    recs = {p: {"pid": p, "pos": "WR", "team": "A", "gvar_pg": v, "status": "ACT"} for p, v in (("a1", 2.0), ("a2", 1.0), ("a3", 0.5), ("a4", -0.4))}
    recs.update({p: {"pid": p, "pos": "WR", "team": "B", "gvar_pg": v, "status": "ACT"} for p, v in (("b1", 1.5), ("b2", 0.2))})
    recs["inj"] = {"pid": "inj", "pos": "WR", "team": "A", "gvar_pg": 5.0, "status": "RES"}
    members = VL.team_members(recs, True)
    assert "inj" not in members["A"]["WR"]                                    # injured reserve is out
    tpv = VL.team_pos_values(recs, ["A", "B"], members, {}, 35.0)
    assert tpv["A"]["WR"] == pytest.approx(3.5) and tpv["B"]["WR"] == pytest.approx(1.7)   # B: two players, the third slot is replacement (0)
    # b1 to A displaces a3 (0.5); A's gain 1.0. B loses b1, nobody behind: 1.5
    assert VL.gain_for("A", recs["b1"], recs, members, {}, {}, 35.0) == pytest.approx(1.0)
    assert VL.loss_for("B", recs["b1"], recs, members, {}, {}, 35.0) == pytest.approx(1.5)
    # a below-replacement player adds nothing; the grade letters follow the percentile cuts
    assert VL.gain_for("B", recs["a4"], recs, members, {}, {}, 35.0) == 0.0
    assert [VL.grade(x) for x in (95, 80, 79, 40, 20, 19, None)] == ["A", "A", "B", "C", "D", "F", None]
    # QB: the model QB term; only a better QB starts, and only the starter's departure costs
    qbs = {"q1": 0.10, "q2": -0.02, "q3": 0.20}
    assert VL.gain_for("A", {"pid": "q3", "pos": "QB"}, recs, members, {"A": 0.10}, qbs, 35.0) == pytest.approx(3.5)
    assert VL.gain_for("A", {"pid": "q2", "pos": "QB"}, recs, members, {"A": 0.10}, qbs, 35.0) == 0.0
    assert VL.loss_for("A", {"pid": "q1", "pos": "QB"}, recs, members, {"A": 0.10}, qbs, 35.0, {"A": -0.02}, {"A": "q1"}) == pytest.approx(4.2)
    assert VL.loss_for("A", {"pid": "q2", "pos": "QB"}, recs, members, {"A": 0.10}, qbs, 35.0, {"A": -0.02}, {"A": "q1"}) == 0.0


def test_candidates_ranked_with_hints():
    recs = {}
    for t, vals in (("A", (0.1, 0.1, 0.0)), ("B", (2.5, 0.2, 0.1)), ("C", (1.0, 0.9, 0.8)), ("D", (0.6, 0.5, 0.4))):
        for i, v in enumerate(vals):
            recs[f"{t}{i}"] = {"pid": f"{t}{i}", "name": f"{t}{i}", "pos": "CB", "team": t, "gvar_pg": v, "status": "ACT", "age": 25.0, "q": True}
    members = VL.team_members(recs, True)
    teams = ["A", "B", "C", "D"]
    tpv = VL.team_pos_values(recs, teams, members, {}, 35.0)
    pos_pct = {p: {t: 0 if (t == "A" and p == "CB") else 80 for t in teams} for p in VL.SLOTS}
    sens = {"ok": True, "grid": [-4.0, 0.0, 4.0], "teams": {"A": {"mean_wins": [4.0, 6.0, 8.0], "p_playoffs": [0.1, 0.2, 0.3]}}}
    sim_t = {"B": {"p_playoffs": 0.05}, "C": {"p_playoffs": 0.6}, "D": {"p_playoffs": 0.5}}
    n = VL.needs_payload(2026, "A", recs, {"values": {}, "pct": {}}, tpv, pos_pct, {}, {}, {}, {}, {}, 35.0, members, sens, sim_t,
                         {"A": 10}, 1.0, {}, {}, [], {}, False, 2026)
    cb = next(w for w in n["improve"] if w["key"] == "CB")
    names = [c["name"] for c in cb["candidates"]]
    assert names[0] == "B0"                                             # the biggest gain first
    assert [c["gain_pg"] for c in cb["candidates"]] == sorted([c["gain_pg"] for c in cb["candidates"]], reverse=True)
    top = cb["candidates"][0]
    assert any("5% to make the playoffs" in h for h in top["hints"])     # the seller is out of contention
    assert top["d_wins"] == pytest.approx(0.5 * top["gain_pg"], abs=0.01) and top["gain_rest"] == pytest.approx(10 * top["gain_pg"], abs=0.05)
    assert "salary cap" in n["label"] and n["contracts"]["enabled"] is False and "OverTheCap" in n["contracts"]["note"]


# ── season simulation: shift, record, sensitivity ───────────────────────────

@pytest.fixture(scope="module")
def league():
    L = SC.league((2024, 2025), seed=3, played_through_week=8)
    u = L["units"]
    ch = TS.season_chain([2024], units_of=lambda s: u[u["season"] == s])
    r = TS.fit(u, 2025, None, TS.preseason_prior(ch["ends"][2024], 2025)).as_dict()
    return {"games": L["games"], "ratings": r}


def test_prepared_state_reproduces_simulate(league):
    a = SS.simulate(2025, n=1500, seed=4, state=league)
    prep = SS.prepare(2025, league)
    b = SS.simulate(2025, n=1500, seed=4, state={**league, "prepared": prep})
    assert all(a["teams"][t]["p_playoffs"] == b["teams"][t]["p_playoffs"] for t in a["teams"])


def test_shift_moves_only_the_team_and_record_is_complete(league):
    prep = SS.prepare(2025, league)
    t = sorted(prep["S0"]["teams"])[0]
    base = SS.simulate(2025, n=3000, seed=2, state={**league, "prepared": prep})
    up = SS.simulate(2025, n=3000, seed=2, state={**league, "prepared": prep, "shift": {t: 5.0}, "record": t})
    assert up["teams"][t]["p_playoffs"] > base["teams"][t]["p_playoffs"] and up["teams"][t]["exp_w"] > base["teams"][t]["exp_w"]
    rec = up["_record"]
    assert all(len(rec[k]) == 3000 for k in ("z", "playoffs", "div", "bye", "conf", "sb", "wins", "pick"))
    assert rec["playoffs"].mean() == pytest.approx(up["teams"][t]["p_playoffs"])
    assert rec["pick"].mean() == pytest.approx(up["teams"][t]["draft"]["exp_pick"], abs=1e-9)


def test_importance_weights_recover_a_planted_curve():
    # outcome = 1{true strength z + shift > 1}: under N(shift, se^2) the probability is Phi((shift - 1) / se)
    rng = np.random.default_rng(0)
    se, k = 2.0, SS.SENS_PROPOSAL
    z = rng.normal(0, k * se, 40000)
    one = (z > 1.0).astype(float)
    rec = {"z": z, "se": se, "se_draw": k * se, **{f: one for f in ("playoffs", "div", "bye", "conf", "sb")}, "wins": z, "pick": z}
    raw = SS.curve_from_record(rec, (-4.0, 0.0, 4.0))
    for i, dx in enumerate((-4.0, 0.0, 4.0)):
        assert raw["p_playoffs"][i] == pytest.approx(float(ndtr((dx - 1.0) / se)), abs=0.02)
        assert raw["mean_wins"][i] == pytest.approx(dx, abs=0.1)
    assert min(raw["ess"]) > 4000


def test_anchor_is_monotone_exact_at_zero_and_bounded():
    g = list(SS.SENS_GRID)
    noisy = {k: [0.5 + 0.03 * x + (0.02 if i % 2 else -0.02) for i, x in enumerate(g)] for k in SS.SENS_KEYS}
    noisy["ess"] = [500.0] * len(g)
    a = SS.anchor_curve(noisy, {"p_playoffs": 0.37, "p_sb": 0.0, "mean_wins": 8.25, "mean_pick": 14.0})
    i0 = g.index(0.0)
    assert a["p_playoffs"][i0] == pytest.approx(0.37) and a["mean_wins"][i0] == pytest.approx(8.25)
    for k in SS.SENS_KEYS:
        assert all(b >= c - 1e-9 for b, c in zip(a[k][1:], a[k][:-1])), k
    assert all(0.0 <= x <= 1.0 for x in a["p_playoffs"])
    assert a["p_sb"][i0] == 0.0


def test_sensitivity_matches_direct_shifted_runs(league):
    prep = SS.prepare(2025, league)
    teams = sorted(prep["S0"]["teams"])[:2]
    base = SS.simulate(2025, n=4000, seed=0, state={**league, "prepared": prep})
    bl = {t: {"p_playoffs": base["teams"][t]["p_playoffs"], "mean_wins": base["teams"][t]["exp_w"]} for t in teams}
    sens = SS.sensitivity(2025, n=1500, state={**league, "prepared": prep}, teams=teams, baseline=bl)
    assert sens["ok"] and sens["grid"] == list(SS.SENS_GRID)
    for t in teams:
        d = SS.simulate(2025, n=4000, seed=0, state={**league, "prepared": prep, "shift": {t: 4.0}})["teams"][t]
        c = sens["teams"][t]
        assert VL.interp(c["p_playoffs"], sens["grid"], 4.0) == pytest.approx(d["p_playoffs"], abs=0.08)
        assert VL.interp(c["mean_wins"], sens["grid"], 4.0) == pytest.approx(d["exp_w"], abs=0.35)


# ── contracts ────────────────────────────────────────────────────────────────

def _contracts():
    return pd.DataFrame([
        {"gsis_id": "00-1", "team": "Chiefs", "is_active": True, "year_signed": 2024, "years": 3, "apy": 10.0,
         "season_history": [{"year": "2026", "team": "Chiefs", "cap_number": 12.0, "cap_percent": 0.04},
                            {"year": "Total", "team": "Total", "cap_number": 30.0, "cap_percent": None}]},
        {"gsis_id": "00-2", "team": "Bills", "is_active": True, "year_signed": 2026, "years": 4, "apy": 5.0,
         "season_history": [{"year": "2026", "team": "Bills", "cap_number": 3.0, "cap_percent": 0.01}]},
        {"gsis_id": "00-3", "team": "Bills", "is_active": False, "year_signed": 2020, "years": 2, "apy": 1.0,
         "season_history": [{"year": "2026", "team": "Bills", "cap_number": 9.0, "cap_percent": 0.03}]},
    ])


def test_contracts_table_and_gate(monkeypatch):
    monkeypatch.delenv("GRIDIRON_CONTRACTS", raising=False)
    CT.set_enabled(None)
    assert CT.enabled() is False and CT.table(2026) == {}           # off by default: OverTheCap's terms
    tab = CT.table(2026, _contracts())
    assert set(tab) == {"00-1", "00-2"}                             # inactive contracts are left out
    assert tab["00-1"] == {**tab["00-1"], "cap_hit": 12.0, "team": "KC", "end": 2026, "years_left": 1, "contract_year": True}
    assert tab["00-2"]["end"] == 2029 and tab["00-2"]["contract_year"] is False
    assert CT.team_totals(tab) == {"KC": 12.0, "BUF": 3.0}
    assert CT.team_totals(tab, {"00-1": "BUF"}) == {"BUF": 15.0}
    assert CT.season_cap({f"p{i}": {"cap_hit": 3.0, "cap_pct": 0.01} for i in range(25)}) == pytest.approx(300.0)
    monkeypatch.setenv("GRIDIRON_CONTRACTS", "1")
    assert CT.enabled() is True
    assert CT.season_cap(tab) is None                               # too few rows to read the cap from


def test_valuation_person_name_fallback(monkeypatch):
    """A rostered player with no snap in the panel is named from the crosswalk, never published as his gsis id."""
    from oddsmarkets.nfl.analytics import people, valuation
    monkeypatch.setattr(people, "_PEOPLE", {"00-0035264": {"name": "Jarrett Stidham"}})
    assert valuation._person_name("00-0035264") == "Jarrett Stidham"
    assert valuation._person_name("00-0000000") is None
