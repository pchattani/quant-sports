"""College football models on a synthetic world (oddsmarkets/college/football/synthetic.py): EP/EPA, ratings
(walk-forward, no peeking), game blend, Elo, committee proxy, season sim and CFP formats. No network."""
import numpy as np
import pandas as pd
import pytest

from oddsmarkets.college.football import (
    backtest,
    committee,
    data,
    ep,
    game,
    ratings,
    sim,
    synthetic,
)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("cfbworld")
    with pytest.MonkeyPatch.context() as mp:
        for k in ("CAMPUS_STORES", "CAMPUS_RAW", "CAMPUS_CACHE", "CAMPUS_DATA"):
            mp.setenv(k, str(root / k.lower()))
        data.clear_memo()
        w = synthetic.make_world(root, seasons=(2022, 2023, 2024))
        yield w
        data.clear_memo()


@pytest.fixture(scope="module")
def pipe(world):
    return backtest.pipeline(2024, p=ratings.Params(lam=3, lam_fcs=2, rho=0.8, half_life=2000, cap=40), use_cache=False)


# ── EP ──────────────────────────────────────────────────────────────────────

def test_score_events_flag_and_side():
    tp = np.array([68, 59, 36, 20, 24, 24, 52])
    flag = np.array([1, 1, 1, 1, 0, 1, 1])
    text = np.array(["run 3 yds TOUCHDOWN", "34 yd FG GOOD", "pass intercepted, return TOUCHDOWN", "SAFETY",
                     "pass complete for 30 yds TOUCHDOWN nullified by penalty", "pass complete to X for a TD (Y KICK)",
                     "punt 40 yds, returns for 80 yds for a TD"])
    val, side = ep._score_events(tp, flag, text)
    assert list(val) == [7, 3, 7, 2, 0, 7, 7]
    assert list(side) == ["off", "off", "def", "def", "", "off", "def"]


def test_ep_monotone_in_field_position(world):
    f = ep.fit(2024, use_cache=False)
    assert f["W"] is not None and f["validation"]["n"] > 0
    assert f["validation"]["logloss"] < f["validation"]["logloss_base"] + 0.05
    states = pd.DataFrame({"yte": [90, 60, 30, 5], "down": 1, "distance": 10, "half_sec": 1500, "half": 1})
    e = ep.predict_proba(f["W"], states) @ ep.VALUES
    assert e[0] < e[1] < e[2] < e[3]


def test_epa_signs(world):
    f = ep.fit(2024)
    pl = ep.season_epa(2023, f)
    tds = pl[(pl["pts"] == 7) & pl["model_play"]]
    assert len(tds) and (tds["epa"] > 0).mean() > 0.95
    inc = pl[(pl["type_id"] == 3) & pl["model_play"]]
    assert inc["epa"].mean() < 0
    assert set(pl.loc[pl["scrim"], "success"].dropna().unique()) <= {0.0, 1.0}
    g = ep.team_game_stats(pl)
    assert {"gid", "team", "opp", "epa", "sr", "n"} <= set(g.columns) and (g["n"] > 0).all()


# ── ratings / no peeking ────────────────────────────────────────────────────

def test_ratings_recover_strength(world, pipe):
    fin = pipe["final"][2023]["pts"]
    s = world["strength"]
    fbs = world["fbs"]
    est = np.array([fin["off"][t] + fin["def"][t] for t in fbs])
    tru = np.array([s[t] for t in fbs])
    assert np.corrcoef(est, tru)[0, 1] > 0.8
    fcs = world["fcs"]
    assert np.mean([fin["off"][t] + fin["def"][t] for t in fcs]) < np.mean(est) - 10


def test_walk_forward_no_peeking(world):
    st = data.load_store(2023)
    gf = data.games_frame(2023, st)
    run1 = ratings.run_season(2023, gf, st, None, None, ratings.DEFAULT, kinds=("pts",))
    day = sorted(gf["day"].unique())[5]
    # change every result on or after `day`: pregame ratings of games on `day` must not move
    gf2 = gf.copy()
    m = gf2["day"] >= day
    gf2.loc[m, "hs"] = gf2.loc[m, "hs"] + 30
    run2 = ratings.run_season(2023, gf2, st, None, None, ratings.DEFAULT, kinds=("pts",))
    ids = gf.loc[gf["day"] == day, "gid"]
    a = run1.pregame.set_index("gid").loc[ids]
    b = run2.pregame.set_index("gid").loc[ids]
    assert np.allclose(a[["pts_off_h", "pts_def_a"]].to_numpy(), b[["pts_off_h", "pts_def_a"]].to_numpy())
    later = gf.loc[gf["day"] > day, "gid"]
    assert not np.allclose(run1.pregame.set_index("gid").loc[later, "pts_off_h"], run2.pregame.set_index("gid").loc[later, "pts_off_h"])


def test_blend_fitted_on_earlier_seasons_only(pipe):
    b23 = pipe["blends"][2023]
    assert b23["seasons"] == [2022]
    assert pipe["blends"][2022]["seasons"] == []        # first season: defaults
    P = pipe["preds"]
    assert P["p_home"].between(0, 1).all()


def test_calibration_payload(pipe):
    cal = backtest.calibration(pipe)
    assert cal["ok"] and cal["n_games"] > 0
    vs = cal["summary"]["vs_close"]
    assert vs["n"] > 0 and 0 <= vs["ats_hit"] <= 1 and vs["ats_se"] > 0
    assert vs["mae_close"] < vs["mae_model"] + 5
    assert cal["by_spread"] and cal["calibration"]
    assert {r["season"] for r in cal["per_season"]} == {2022, 2023, 2024}


def test_devig_and_predict():
    assert abs(data.devig(-150, 130) - 0.5798) < 0.01
    r = {"pts": {"off": {"a": 5, "b": -5}, "def": {"a": 5, "b": -5}, "mu": 28, "hfa": 2.5}}
    out = game.predict("a", "b", "2026-10-24", {"ratings": r, "blend": game.DEFAULT_BLEND, "neutral": True})
    assert out["margin"] == pytest.approx(20.0) and out["p_home"] > 0.85 and out["spread_fair"] == pytest.approx(-20.0)


# ── committee, sim, formats ─────────────────────────────────────────────────

def test_cfp_formats():
    assert sim.cfp_format(2010)["teams"] == 2
    assert sim.cfp_format(2019)["teams"] == 4
    f24, f25, f26 = sim.cfp_format(2024), sim.cfp_format(2025), sim.cfp_format(2026)
    assert f24["teams"] == 12 and f24["seeding"] == "champions_top4" and f24["verified"]
    assert f25["seeding"] == "straight" and f25["verified"]
    assert not f26["verified"] and "assumed" in f26["note"]
    tab = sim.format_table(list(range(2014, 2027)))
    assert [r["from"] for r in tab] == [2014, 2024, 2025, 2026]


def test_committee_fit(world, pipe):
    tabs = committee.ranking_tables(pipe, [2022, 2023])
    assert tabs and all(t["ranked"] for t in tabs)
    m = committee.fit(tabs)
    assert m["n_pairs"] > 0
    e = committee.evaluate([t for t in tabs if t["final"]][0], m)
    assert e["spearman"] > 0.3 and 0 <= e["top12"] <= 1


def test_season_sim_mass(world, pipe):
    comm = committee.fit_and_validate(pipe, use_cache=False)
    r = sim.simulate(2024, pipe, comm, n=2000)
    T = r["teams"]
    assert abs(sum(v["p_title"] for v in T.values()) - 1) < 1e-6
    assert abs(sum(v["p_cfp"] for v in T.values()) - 12) < 1e-6        # 2024 rules: 12 teams
    assert abs(sum(v["p_bye"] for v in T.values()) - 4) < 1e-6
    for c, rows in r["conf"].items():
        assert abs(sum(x["p_win"] for x in rows) - 1) < 1e-6
        assert abs(sum(x["p_appear"] for x in rows) - 2) < 1e-6
    best = max(T, key=lambda t: world["strength"][t])
    assert T[best]["p_title"] > 1 / 24


def test_sim_backtest_runs(world, pipe):
    comm = committee.fit_and_validate(pipe)
    bt = sim.backtest(pipe, comm, seasons=[2022, 2023], n=500)
    assert bt["n_seasons"] >= 1 and 0 <= bt["field_hit_rate"] <= 1


# ── honesty guards added 21 Oct 2026 ────────────────────────────────────────

def test_ep_never_scores_a_season_with_its_own_model(world):
    f = ep.fit(2024)
    rows = f["validation"]["per_season"]
    assert rows and not any(r["in_sample"] for r in rows)
    for r in rows:
        if r["season"] > ep.EARLY_END and r["scheme"] == "walk-forward" and r["train"][1] < r["season"]:
            assert r["train"][1] < r["season"]


def test_fcs_memory_and_conference_levels():
    p = ratings.Params(rho_fcs=0.5, rho_fconf=1.0)
    st = {"teams": {"a": {"member": True, "conference": "1"}, "b": {"member": True, "conference": "1"},
                    "x": {"member": False, "conference": "48"}, "y": {"member": False, "conference": "48"}}}
    teams = ["a", "b", "x", "y"]
    fcs = np.array([False, False, True, True])
    mem = {"dev": {"x": (4.0, 2.0, 2020)}, "conf": {"48": (-3.0, -1.0)}}
    pri = ratings.priors(2022, teams, fcs, st, None, p, "pts", None, mem)
    assert pri["off"][2] == pytest.approx(4.0 * 0.5 ** 2) and pri["off"][3] == 0.0       # carried over two seasons
    assert pri["confs"] == ["48"] and list(pri["cidx"]) == [-1, -1, 0, 0] and pri["coff"][0] == pytest.approx(-3.0)
    m = ratings._model("pts", teams, fcs, pri, p)
    u = m.unpack(m.m)                                                                        # the prior itself
    assert u["off"][2] == pytest.approx(pri["g0"][0] - 3.0 + 1.0) and u["c_off"]["48"] == pytest.approx(-3.0)


def test_title_game_placeholders_follow_their_headline():
    st = {"teams": {str(i): {"member": True, "conference": c} for i, c in enumerate(["1"] * 3 + ["5"] * 3 + ["8"] * 6)},
          "conferences": {"1": {"name": "Atlantic Coast Conference", "short": "ACC"},
                          "5": {"name": "Big Ten Conference", "short": "Big Ten"},
                          "8": {"name": "Southeastern Conference", "short": "SEC"}},
          "games": {"g1": {"stype": "conf", "home": "-1", "away": "-2", "note": "Big Ten Championship"},
                    "g2": {"stype": "conf", "home": "-1", "away": "-2", "note": "ACC Championship"}}}
    gf = pd.DataFrame(columns=["gid", "home", "away", "stype", "h_member", "a_member", "final"])
    out = sim.ccg_conferences(st, gf)
    assert set(out) == {"1", "5"}                     # not the largest conference (8) by default


def test_unreliable_lines_are_dropped(world, monkeypatch):
    monkeypatch.setattr(data, "UNRELIABLE_LINES", {2023: "test"})
    gf = data.games_frame(2023)
    assert gf["spread_home"].isna().all() and gf["ml_home"].isna().all()
    assert data.games_frame(2022)["spread_home"].notna().any()
