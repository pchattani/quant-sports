"""Builder C models on synthetic seasons with planted truth (no network, no real data):
RE24 (simulator truth and a hand-computed matrix), linear weights, win expectancy, xwOBA+ (spray and park
matter, calibration, the predictive test), catch probability (planted range recovered), framing and
umpires (planted catcher / umpire effects recovered, scorecards), park factors (planted parks recovered),
WAR (totals and components), steals, the Retrosheet path and history, stabilisation, ABS summaries."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.models import (_c, catchprob, framing, history, parks, re24, stabilise, synthetic_c, umpire,
                                         war, xwoba)


@pytest.fixture(scope="module")
def season():
    df, store, truth = synthetic_c.synth_season(n_games=700, seed=3)
    return df, store, truth


@pytest.fixture(scope="module")
def pitches(season):
    return _c.prepare_pitches(season[0].copy())


@pytest.fixture(scope="module")
def xw(pitches, season):
    return xwoba.score_season(pitches, season[1])


# ============================================================================ RE24

def test_re24_matches_simulator_truth(season):
    df, store, truth = season
    res = re24.statcast_season("mlb", 2025, pitches=df, with_wpa=False)
    tp = truth["pa"][truth["pa"]["complete"]]
    tm = tp.groupby(["outs", "bases"])["runs_to_end"].mean().unstack().reindex(index=range(3), columns=range(8))
    assert np.nanmax(np.abs(tm.to_numpy() - res["re"]["re"])) < 1e-9
    assert res["re"]["n"].sum() == len(tp)


def _hand_pitch_table():
    """Two innings and a half of one game, one pitch per PA (see test for the hand-computed matrix)."""
    rows = []
    ab = [0]

    def pa(inning, half, outs, bases, bat_score, fld_score, runs, event):
        ab[0] += 1
        on = {1: 101 if bases & 1 else None, 2: 102 if bases & 2 else None, 3: 103 if bases & 4 else None}
        rows.append({"game_pk": 1, "game_type": "R", "game_date": "2025-04-01", "at_bat_number": ab[0], "pitch_number": 1,
                     "inning": inning, "inning_topbot": "Top" if half == 0 else "Bot", "outs_when_up": outs,
                     "on_1b": on[1], "on_2b": on[2], "on_3b": on[3], "bat_score": bat_score, "fld_score": fld_score,
                     "post_bat_score": bat_score + runs, "events": event, "description": "hit_into_play",
                     "home_team": "H", "away_team": "A", "batter": 1, "pitcher": 2, "stand": "R", "p_throws": "R",
                     "balls": 0, "strikes": 0, "woba_value": 0.0, "woba_denom": 1.0})
    # top 1: single, two-run homer, K, out, out (2 runs)
    pa(1, 0, 0, 0, 0, 0, 0, "single"); pa(1, 0, 0, 1, 0, 0, 2, "home_run"); pa(1, 0, 0, 0, 2, 0, 0, "strikeout")
    pa(1, 0, 1, 0, 2, 0, 0, "field_out"); pa(1, 0, 2, 0, 2, 0, 0, "field_out")
    # bottom 1: walk, K, RBI double, out, out (1 run)
    pa(1, 1, 0, 0, 0, 2, 0, "walk"); pa(1, 1, 0, 1, 0, 2, 0, "strikeout"); pa(1, 1, 1, 1, 0, 2, 1, "double")
    pa(1, 1, 1, 2, 1, 2, 0, "field_out"); pa(1, 1, 2, 2, 1, 2, 0, "field_out")
    # top 2: three strikeouts
    pa(2, 0, 0, 0, 2, 1, 0, "strikeout"); pa(2, 0, 1, 0, 2, 1, 0, "strikeout"); pa(2, 0, 2, 0, 2, 1, 0, "strikeout")
    # bottom 2: the game stops (rain) after a single: an incomplete half-inning, excluded
    pa(2, 1, 0, 0, 1, 2, 0, "single")
    return pd.DataFrame(rows)


def test_re24_hand_computed_matrix():
    res = re24.statcast_season("mlb", 2025, pitches=_hand_pitch_table(), with_wpa=False, count=False)
    re, n = res["re"]["re"], res["re"]["n"]
    # by hand: (0,empty) {2,0,1,0} -> 0.75; (0,1B) {2,1} -> 1.5; (1,1B) {1}; (1,2B) {0}; outs-only states 0
    assert re[0, 0] == pytest.approx(0.75)
    assert re[0, 1] == pytest.approx(1.5)
    assert re[1, 1] == pytest.approx(1.0)
    assert re[1, 2] == pytest.approx(0.0)
    assert re[1, 0] == pytest.approx(0.0) and re[2, 0] == pytest.approx(0.0)
    assert n.sum() == 13            # the rain-shortened bottom of the 2nd is excluded
    # RE24 of the two-run homer: RE(0, empty) - RE(0, 1B) + 2
    pa = res["pa"]
    hr = pa[pa["events"] == "home_run"].iloc[0]
    assert hr["re24"] == pytest.approx(0.75 - 1.5 + 2)


def test_linear_weights_and_woba_scale(season):
    res = re24.statcast_season("mlb", 2025, pitches=season[0], with_wpa=False)
    lw = res["lw"]["lw"]
    assert lw["HR"] > lw["2B"] > lw["1B"] > lw["BB"] > 0 > lw["OUT"]
    assert lw["K"] < 0
    w = res["lw"]["woba_w"]
    assert w["HR"] > w["2B"] > w["1B"] > w["BB"] > 0
    assert 8 < res["lw"]["rpw"] < 13
    sv = res["counts"]["strike_value"]
    assert sv["3-2"] > sv["0-0"] > 0          # a full-count call is worth the most


def test_win_expectancy_structure_and_calibration(season):
    res = re24.statcast_season("mlb", 2025, pitches=season[0], with_wpa=True, count=False)
    wet = res["we"]
    we = lambda i, h, o, b, d: float(re24.we_lookup(wet, [i], [h], [o], [b], [d])[0])
    assert 0.4 < we(1, 0, 0, 0, 0) < 0.6
    assert we(9, 1, 2, 7, 0) > we(9, 1, 2, 0, 0) > 0.5          # tied, home batting in the 9th
    assert we(9, 0, 2, 0, 3) > we(9, 0, 2, 0, 1) > we(9, 0, 2, 0, -1)
    cal = re24.we_calibration(res["pa"])
    assert cal["brier"] < 0.2
    for p, y, n in cal["bins"]:
        if n > 1000:
            assert abs(p - y) < 0.08
    assert res["pa"]["li"].mean() == pytest.approx(1.0)


# ============================================================================ xwOBA+

def test_xwoba_spray_and_park_matter(pitches, season):
    b = xwoba.batted_balls(pitches)
    ab = xwoba.ablation(b, season[1], rounds=100)
    assert ab["launch+spray"]["logloss"] < ab["launch"]["logloss"] - 0.05          # planted: direction matters
    assert ab["launch+fence+park"]["logloss"] < ab["launch"]["logloss"] - 0.01     # the fence it heads for
    assert ab["full"]["logloss"] < ab["launch"]["logloss"]


def test_xwoba_calibrated_and_park_neutral(xw):
    pa = xw["pa"]
    bip = xw["bip"]
    assert bip["xwoba"].mean() == pytest.approx(bip["woba_value"].mean(), abs=1e-6)
    assert pa["xwoba"].sum() / pa["denom"].sum() == pytest.approx(pa["woba"].sum() / pa["denom"].sum(), abs=1e-6)
    g = bip.groupby("home_team")[["xwoba", "xwoba_n"]].mean()
    assert g.loc["T00", "xwoba"] > g.loc["T00", "xwoba_n"] + 0.01      # short fences inflate contact
    eff = g["xwoba"] - g["xwoba_n"]
    assert eff["T00"] > eff["T01"] + 0.01                                # short fences v the biggest park
    assert g.loc["T02", "xwoba"] > g.loc["T02", "xwoba_n"] + 0.01      # altitude
    t = xwoba.player_table(pa, "batter", min_pa=200)
    assert len(t) > 50 and t["xwoba"].between(0.15, 0.6).all()


def test_xwoba_predictive_test_runs(season):
    df = season[0]
    res = xwoba.predictive_test("mlb", [2025], min_pa=100, min_pa_next=100, rounds=80,
                                pitch_loader=lambda s: _c.prepare_pitches(df.copy()))
    w = res["within"]["2025"]
    assert w["n"] > 40
    for k in ("woba", "savant_xwoba", "xwoba"):
        assert w[k]["r"] is not None and w[k]["rmse"] > 0
    # with planted talent and no luck in the expectation, xwOBA+ predicts the next half at least as well as wOBA
    assert w["xwoba"]["r"] > w["woba"]["r"] - 0.05


# ============================================================================ fielding

def test_catchprob_recovers_planted_range(pitches, season):
    truth = season[2]
    b = catchprob.score(pitches)
    assert b["p_out"].mean() == pytest.approx(b["out"].mean(), abs=1e-3)
    ft = catchprob.fielder_table(b)
    ft["truth"] = ft["pid"].map(truth["fielder"])
    pos = {str(v): int(k) for r in truth["positions"].values() for k, v in r.items()}
    ft["tpos"] = ft["pid"].map(pos)
    of, inf = ft[ft["tpos"] >= 7], ft[ft["tpos"] <= 6]
    assert np.corrcoef(of["oaa"], of["truth"])[0, 1] > 0.7
    assert np.corrcoef(inf["oaa"], inf["truth"])[0, 1] > 0.6
    assert np.corrcoef(ft["runs"], ft["oaa"])[0, 1] > 0.9
    assert set(b["direction"].unique()) <= {"back", "in", "toward_1b", "toward_3b"}


# ============================================================================ framing and umpires

@pytest.fixture(scope="module")
def frame(pitches, season):
    return framing.season_fit("mlb", 2025, pitches=pitches, store=season[1])


def test_framing_recovers_catchers(frame, season):
    truth = season[2]
    t = frame["table"].copy()
    t["truth"] = t["pid"].map(truth["catcher"])
    assert np.corrcoef(t["effect"], t["truth"])[0, 1] > 0.9
    assert np.corrcoef(t["runs"], t["truth"])[0, 1] > 0.9
    best = max(truth["catcher"], key=truth["catcher"].get)
    worst = min(truth["catcher"], key=truth["catcher"].get)
    assert t.iloc[0]["pid"] == best and t.iloc[-1]["pid"] == worst
    u = pd.Series(frame["model"]["effects"]["ump"])
    assert np.corrcoef(u, pd.Series(truth["umpire"]).reindex(u.index))[0, 1] > 0.8


def test_umpire_tables_and_scorecards(frame, pitches, season):
    rs = re24.statcast_season("mlb", 2025, pitches=pitches, with_wpa=False)
    r = umpire.season_tables(frame["called"], frame["model"], rs["re"]["re"], rs["counts"])
    u, sc, d = r["umpires"], r["scorecards"], r["called"]
    assert u["accuracy"].between(0.7, 1).all() and u["consistency"].between(0.7, 1).all()
    assert int(u["missed"].sum()) == int((d["correct"] == 0).sum()) == int(sc["missed"].sum())
    truth = pd.Series(season[2]["umpire"])
    assert np.corrcoef(u["zone_per100"], truth.reindex(u["pid"]).to_numpy())[0, 1] > 0.8
    assert np.allclose(sc["home_favour"], sc["home_gain"] - sc["away_gain"])
    assert (sc["total_impact"] >= sc[["home_gain", "away_gain"]].abs().max(axis=1) - 1e-9).all()
    one = umpire.missed_calls(d, int(sc.iloc[0]["game_pk"]))
    assert len(one) == int(sc.iloc[0]["missed"])


def test_abs_store_summary():
    store = {"games": {"1": {"home": "10", "away": "20", "abs": {"home": {"used": 2, "overturned": 1},
                                                                  "away": {"used": 1, "overturned": 0}}},
                       "2": {"home": "20", "away": "10", "abs": {"home": {"used": 2, "overturned": 2},
                                                                  "away": {"used": 0, "overturned": 0}}}}}
    p = pd.DataFrame({"description": ["ball"], "events": [None]})
    out = umpire.abs_analytics(p, store, np.zeros((3, 8)), {"rv": {}})
    assert out["ok"] and out["source"] == "store"
    assert out["used"] == 5 and out["won"] == 3 and out["overturn_rate"] == pytest.approx(0.6)


# ============================================================================ parks

def test_park_factors_recover_planted_parks(xw, pitches, season):
    pa = re24.prepare_pa(_c.pa_table(pitches))
    agg = parks.season_aggregates(xw["bip"], pa, season[1])
    res = parks.combine([agg], season[1])
    hr = {k: v["factors"]["HR"] for k, v in res.items()}
    assert hr["T00"] > 1.05 and hr["T01"] < 0.95 and hr["T02"] > 1.1
    assert set(res["T00"]["by_hand"]) == {"L", "R"}
    w = parks.weather_effects(agg["weather"])
    assert w["carry_ft"]["per_10F"] > 3 and w["carry_ft"]["per_mph_out"] > 1.5      # planted 7 ft and 3 ft
    assert parks.parse_wind("12 mph, Out To CF") == 12 and parks.parse_wind("10 mph, In From LF") == -7
    assert parks.parse_wind("8 mph, L To R") == 0


# ============================================================================ WAR

def test_war_sums_and_components(season, xw, frame):
    df, store, truth = season
    res = war.season_war(df, store, season=2025, xw=xw, framing_t=frame["table"])
    b, p, k = res["batters"], res["pitchers"], res["constants"]
    tgt = k["target_total"]
    assert tgt == pytest.approx(1000 * res["team_games"] / 4860)
    assert b["war"].sum() == pytest.approx(0.57 * tgt, rel=1e-9)
    assert p["war_ra9"].sum() == pytest.approx(0.43 * tgt, rel=1e-9)
    assert p["war_x"].sum() == pytest.approx(0.43 * tgt, rel=1e-9)
    comp = b["batting"] + b["baserunning"] + b["fielding"] + b["framing"] + b["pos_runs"] + b["league_adj"]
    assert comp.sum() == pytest.approx(0.0, abs=1e-6)
    assert np.allclose(b["rar"], comp + b["replacement"])
    # planted speed shows up in baserunning; catchers carry framing; positions have the right sign
    sp = pd.Series(truth["speed"]).reindex(b.index)
    assert np.corrcoef(b["baserunning"], sp)[0, 1] > 0.4
    cat = [c for cs in truth["catchers"].values() for c in cs]
    assert (b.loc[b.index.isin(cat), "framing"].abs() > 0).all()
    assert (b.loc[b.index.isin(cat), "pos_runs"] > 0).all()


def test_steals_detected_exactly(pitches, season):
    st = war.statcast_steals(pitches)
    sb = sum(1 for x in season[2]["steals"] if x[2] == 1)
    cs = sum(1 for x in season[2]["steals"] if x[2] == 0)
    vc = st["kind"].value_counts()
    assert vc.get("sb", 0) == sb and vc.get("cs", 0) == cs


# ============================================================================ Retrosheet path and history

def test_retro_path_and_history(season):
    df = season[0]
    rt = synthetic_c.retro_from_pitches(df)
    res = re24.retro_season(2025, rt)
    st = re24.statcast_season("mlb", 2025, pitches=df, with_wpa=False, count=False)
    assert np.abs(res["re"]["re"] - st["re"]["re"]).max() < 0.05
    hw = war.historical_season(2025, rt, people={})
    tgt = hw["constants"]["target_total"]
    assert hw["batters"]["war"].sum() == pytest.approx(0.57 * tgt) and hw["pitchers"]["war_ra9"].sum() == pytest.approx(0.43 * tgt)
    lines = history.retro_lines(2025, rt, people={})
    car = history.careers(lines["batters"], lines["pitchers"])
    cb = car["batters"]
    assert cb["pa"].sum() == (rt["pa"]).sum()
    assert cb["war"].sum() == pytest.approx(0.57 * tgt)
    assert (cb["wraa"] * cb["pa"]).sum() != 0 and cb["wrc_plus"].between(0, 300).all()
    lb = history.leaderboards(car, 5)
    assert len(lb["bat_war"]["rows"]) == 5 and "pit_ra9_minus" in lb


def test_retro_steal_parsing():
    df = pd.DataFrame({"event_tx": ["SB2", "K+SB3", "CS2(26)", "CS2(2E6)", "POCS3(15)", "S8.1-3"],
                       "run1_pre": ["a", None, "c", "d", None, "f"], "run2_pre": [None, "b", None, None, "e", None],
                       "run3_pre": [None] * 6})
    st = re24.retro_running(df)
    got = sorted(map(tuple, st[["runner", "kind"]].to_numpy().tolist()))
    assert got == [("a", "sb"), ("b", "sb"), ("c", "cs"), ("e", "cs")]


# ============================================================================ stabilisation

def test_stabilise_recovers_spearman_brown_k():
    rng = np.random.default_rng(0)
    n_players, n_events = 400, 1400
    p = np.clip(rng.normal(0.25, 0.03, n_players), 0.01, 0.99)
    rows = rng.random((n_players, n_events)) < p[:, None]
    ev = pd.DataFrame({"batter": np.repeat(np.arange(n_players).astype(str), n_events),
                       "t": np.tile(np.arange(n_events), n_players), "k_rate": rows.ravel().astype(float)})
    curve = stabilise.split_half_curve(ev, "batter", "k_rate")
    k = stabilise.fit_k(curve)
    k_true = 0.25 * 0.75 / 0.03 ** 2
    assert k == pytest.approx(k_true, rel=0.3)


def test_stabilise_season_table(pitches, xw):
    res = stabilise.season_stability(pitches, xw["bip"], metrics=["k_rate", "ev", "pull_rate", "xwoba"])
    t = stabilise.combine({"2025": res})
    assert t["ev"]["n70"] < t["k_rate"]["n70"]          # exit velocity stabilises faster than K% here
    assert all(v["n70"] > 0 for v in t.values())


def test_abs_from_play_text():
    base = {"game_pk": 1, "inning_topbot": "Top", "home_team": "H", "away_team": "A", "outs_when_up": 1, "on_1b": np.nan,
            "on_2b": np.nan, "on_3b": np.nan, "fielder_2": 30, "pitcher": 20, "player_name": "Arm, Joe"}
    rows = [
        {**base, "batter": 10, "balls": 1, "strikes": 2, "description": "called_strike", "events": "strikeout",
         "des": "Al Bat challenged (pitch result), call on the field was confirmed: Al Bat called out on strikes."},
        {**base, "batter": 11, "balls": 3, "strikes": 2, "description": "ball", "events": "walk",
         "des": "Cy Catcher challenged (pitch result), call on the field was confirmed: Bo Hit walks."},
        {**base, "batter": 12, "balls": 3, "strikes": 2, "description": "called_strike", "events": "strikeout",
         "des": "Cy Catcher challenged (pitch result), call on the field was overturned: Di Hit called out on strikes."},
        {**base, "batter": 13, "balls": 0, "strikes": 0, "description": "hit_into_play", "events": "single",
         "des": "Mgr challenged (play at 1st), call on the field was overturned: Ed Hit singles."},
    ]
    p = pd.DataFrame(rows)
    re = np.array([[0.5 - 0.2 * o + 0.35 * bin(b).count("1") for b in range(8)] for o in range(3)])
    out = umpire.abs_analytics(p, {"games": {}}, re, {"rv": {}})
    assert out["ok"] and out["source"] == "des" and out["n"] == 3
    assert out["by_role"]["batter"]["n"] == 1 and out["by_role"]["catcher"]["n"] == 2
    assert out["overturn_rate"] == pytest.approx(1 / 3)
    assert out["replay"]["n"] == 1
    # the overturned full-count call turned a walk into a strikeout for the fielding side: value > 0
    assert out["value_per_overturn"] > 0


def test_xwoba_classes_follow_woba_value():
    p = pd.DataFrame({"events": ["field_error", "fielders_choice", "field_out", "single", "sac_bunt"],
                      "description": ["hit_into_play"] * 5, "woba_value": [0.9, 0.9, 0.0, 0.9, 0.0],
                      "woba_denom": [1, 1, 1, 1, 0]})
    b = xwoba.batted_balls(p)
    assert b["cls"].tolist() == [1, 1, 0, 1]
    assert xwoba.class_weights(b)[1] == pytest.approx(0.88)       # default kept below five examples


def test_stabilise_game_parity_split_ignores_shared_game_effects():
    """A shock shared by the events of one game (pitcher, park, umpire) lands in both halves of an event-parity
    split and inflates r_n (k too small); the game-parity split (stab-4) keeps it out and recovers the talent k."""
    rng = np.random.default_rng(1)
    n_players, n_games, per_game = 300, 120, 4
    talent = rng.normal(0.25, 0.03, n_players)
    shock = rng.normal(0.0, 0.08, (n_players, n_games))                 # one game's shared effect
    p = np.clip(talent[:, None, None] + shock[:, :, None], 0.01, 0.99)
    ev_ = rng.random((n_players, n_games, per_game)) < p
    ev = pd.DataFrame({"batter": np.repeat(np.arange(n_players).astype(str), n_games * per_game),
                       "g": np.tile(np.repeat(np.arange(n_games), per_game), n_players),
                       "t": np.tile(np.arange(n_games * per_game), n_players), "k_rate": ev_.ravel().astype(float)})
    k_game = stabilise.fit_k(stabilise.split_half_curve(ev, "batter", "k_rate"))
    k_event = stabilise.fit_k(stabilise.split_half_curve(ev, "batter", "k_rate", by="event"))
    k_true = 0.25 * 0.75 / 0.03 ** 2
    assert k_event < 0.8 * k_game                                       # the event split understates k
    assert k_game > 0.8 * k_true
