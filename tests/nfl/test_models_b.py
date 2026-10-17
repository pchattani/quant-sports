"""Builder B play-level models on synthetic seasons with planted truth (no network, no real data), plus
hand-worked checks of the 4th-down / two-point calculator and schema checks on the recorded pbp slice."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nfl.models import _io, synthetic_b as S

SEASONS = (2021, 2022, 2023, 2024)
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    raw = tmp_path_factory.mktemp("gridiron_raw")
    keys = ("GRIDIRON_RAW", "GRIDIRON_CACHE", "GRIDIRON_NO_SOURCES", "GRIDIRON_THREADS")
    old = {k: os.environ.get(k) for k in keys}
    os.environ["GRIDIRON_RAW"] = str(raw)
    os.environ["GRIDIRON_CACHE"] = str(raw / "cache")
    os.environ["GRIDIRON_NO_SOURCES"] = "1"
    os.environ["GRIDIRON_THREADS"] = "4"
    old_fitted = _io.FITTED
    _io.FITTED = raw / "fitted"
    rng_league = __import__("random").Random(5)
    truth = {}
    for i, y in enumerate(SEASONS):
        league = S.make_league(rng_league, 8, y)
        pbp, t = S.write_season(raw, y, seed=i, rounds=4, teams=league)
        truth[y] = (pbp, t)
    from oddsmarkets.nfl.models import ep, fourth_down, kicking, wp
    fits = {"ep": ep.fit(list(SEASONS)), "wp": wp.fit(list(SEASONS)), "kick": kicking.fit(list(SEASONS)),
            "fourth": fourth_down.fit(list(SEASONS))}
    yield {"raw": raw, "truth": truth, "fits": fits}
    _io.FITTED = old_fitted
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _spearman(a, b) -> float:
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


# ============================================================================ EP

def test_next_score_labels_hand_built():
    from oddsmarkets.nfl.models import ep
    rows = [  # game G, half 1: A drives, punts; B kicks a FG; A plays on and the half ends scoreless after
        ("G", 1, 1, "A", "B", 1, "run", 0, None, None, 0),
        ("G", 2, 1, "A", "B", 4, "punt", 0, None, None, 0),
        ("G", 3, 2, "B", "A", 1, "pass", 0, None, None, 0),
        ("G", 4, 2, "B", "A", 4, "field_goal", 0, None, "made", 0),
        ("G", 5, 2, "A", "B", 1, "pass", 0, None, None, 0),
        # half 2: B scores a TD after A's turnover; then A is tackled for a safety
        ("G", 6, 3, "A", "B", 1, "pass", 0, None, None, 0),
        ("G", 7, 3, "B", "A", 1, "run", 1, "B", None, 0),
        ("G", 8, 3, "B", "A", None, "extra_point", 0, None, None, 0),
        ("G", 9, 4, "A", "B", 2, "run", 0, None, None, 1),
        ("G", 10, 4, "B", "A", 1, "run", 0, None, None, 0),
    ]
    d = pd.DataFrame(rows, columns=["game_id", "play_id", "qtr", "posteam", "defteam", "down", "play_type", "touchdown",
                                    "td_team", "field_goal_result", "safety"])
    d = ep.next_score(d)
    want = ["opp_fg", "opp_fg", "fg", "fg", "none", "opp_td", "td", "safety", "opp_safety", "none"]
    got = [ep.CLASSES[int(c)] for c in d["ns_class"]]
    # play 8 (the try) is not a model play; its label (the next event after it is A's safety: B's points) is "safety"
    assert got == want


def test_ep_probabilities_calibration_and_monotone(env):
    from oddsmarkets.nfl.models import ep
    f = env["fits"]["ep"]
    v = f["validation"]["all"]
    assert v["n"] > 20000
    for c, x in v["ours"]["classes"].items():
        assert abs(x["mean_pred"] - x["obs"]) < 0.04, c
    assert v["ours"]["ep_calibration"]["mae_weighted"] < 0.5
    # EP falls as the ball moves away from the goal line (1st and 10, mid first half, tied)
    yl = np.arange(10, 95, 5, dtype=float)
    st = pd.DataFrame({"down": 1.0, "ydstogo": np.minimum(10.0, yl), "goal_to_go": (yl <= 10).astype(float), "yardline_100": yl,
                       "half_seconds_remaining": 1200.0, "half": 1.0, "score_differential": 0.0,
                       "posteam_timeouts_remaining": 3.0, "defteam_timeouts_remaining": 3.0, "home": 1.0, "roof_code": 0.0,
                       "era": 2023.0})
    P = ep.predict_proba(f, st)
    assert np.allclose(P.sum(axis=1), 1.0, atol=1e-6)
    e = ep.ep_from_proba(P)
    assert _spearman(yl, e) < -0.95
    assert e[0] > 3.0 and e[-1] < 1.0


def test_epa_ours_scoring_play_is_points_minus_ep(env):
    from oddsmarkets.nfl.models import ep
    o = ep.for_season(2024)
    d = _io.plays(2024).merge(o[["game_id", "play_id", "ep_ours", "epa_ours"]], on=["game_id", "play_id"])
    td = d[(d["touchdown"] == 1) & (d["td_team"] == d["posteam"]) & d["epa_ours"].notna()]
    assert len(td) > 50
    assert np.allclose(td["epa_ours"], 7.0 - td["ep_ours"], atol=1e-4)
    assert abs(o["epa_ours"].mean()) < 0.3


# ============================================================================ WP

def test_wp_monotone_spread_and_calibration(env):
    from oddsmarkets.nfl.models import wp
    f = env["fits"]["wp"]
    v = f["validation"]["all"]
    assert v["ours"]["logloss"] < 0.55
    assert v["ours"]["calibration"]["ece"] < 0.08       # 448 synthetic games: game-clustered labels
    sd = np.arange(-21, 22, 3, dtype=float)
    st = pd.DataFrame({"score_differential": sd, "game_seconds_remaining": 900.0, "half_seconds_remaining": 900.0, "qtr": 4.0,
                       "down": 1.0, "ydstogo": 10.0, "yardline_100": 60.0, "posteam_timeouts_remaining": 3.0,
                       "defteam_timeouts_remaining": 3.0, "home": 1.0, "pos_spread": 0.0, "receive_2h_ko": 0.0, "season": 2023.0})
    p = wp.state_wp(f, wp.features(st))
    assert np.all(np.diff(p) >= -1e-9) and p[-1] - p[0] > 0.7
    st2 = st.assign(pos_spread=7.0, game_seconds_remaining=3500.0, half_seconds_remaining=1700.0, qtr=1.0)
    st3 = st.assign(pos_spread=-7.0, game_seconds_remaining=3500.0, half_seconds_remaining=1700.0, qtr=1.0)
    assert np.all(wp.state_wp(f, wp.features(st2)) >= wp.state_wp(f, wp.features(st3)))
    over = st.assign(game_seconds_remaining=0.0)
    q = wp.state_wp(f, wp.features(over))
    assert np.all(q[sd > 0] == 1.0) and np.all(q[sd < 0] == 0.0)


def test_receive_2h_ko_on_recorded_pbp():
    from oddsmarkets.nfl.models import wp
    d = _io.prepare(_io.read_parquet(FIX / "pbp_2025_slice.parquet", _io.PBP_COLUMNS))
    g = d[d["game_id"] == "2025_13_JAX_TEN"].copy()
    r = wp.receive_2h_ko(g)
    h1 = (g["qtr"] <= 2).to_numpy()
    # TEN (home) kicked off to open the game, so JAX's first-half plays have 0 and TEN's 1
    jax = (g["posteam"] == "JAX").to_numpy()
    ten = (g["posteam"] == "TEN").to_numpy()
    assert np.all(r[h1 & ten] == 1.0) and np.all(r[h1 & jax] == 0.0)
    assert np.all(r[~h1] == 0.0)


# ============================================================================ 4th down and 2-pt calculator (hand-worked)

def _toy_wp(states: pd.DataFrame) -> np.ndarray:
    return np.clip(0.5 + 0.02 * states["score_differential"].to_numpy(float)
                   + 0.004 * (50.0 - states["yardline_100"].to_numpy(float)), 0, 1)


def _base(yl, togo, sd=0.0):
    return pd.DataFrame({"yardline_100": [float(yl)], "ydstogo": [float(togo)], "score_differential": [float(sd)],
                         "game_seconds_remaining": [1800.0], "half_seconds_remaining": [1800.0], "half": [2.0],
                         "posteam_timeouts_remaining": [3.0], "defteam_timeouts_remaining": [3.0], "home": [1.0],
                         "pos_spread": [0.0], "receive_2h_ko": [0.0], "season": [2023.0]})


GAINS = {"succ_excess": [[0.0] * 5] * 7, "fail_short": [[-1.0] * 5] * 7}


def test_fourth_down_calculator_hand_worked():
    from oddsmarkets.nfl.models import fourth_down as F
    # 4th and 2 at the opponent's 40, tied: go = .6 * .548 + .4 * .544; FG (57 yd) = .5 * .66 + .5 * .512; punt to the 15 = .64
    ev = F.evaluate(_base(40, 2), _toy_wp, np.array([0.6]), np.array([0.5]), GAINS, np.full((1, 5), 85.0), np.zeros(1), 75.0, 1.0)
    assert ev["wp_go"][0] == pytest.approx(0.6 * 0.548 + 0.4 * 0.544, abs=1e-9)
    assert ev["wp_fg"][0] == pytest.approx(0.5 * 0.66 + 0.5 * 0.512, abs=1e-9)
    assert ev["wp_punt"][0] == pytest.approx(0.64, abs=1e-9)
    assert ev["rec"][0] == "punt"
    assert ev["go_gain"][0] == pytest.approx(0.5464 - 0.64, abs=1e-9)
    # 4th and goal at the 2: a conversion is a touchdown (+6 + P(PAT) = 7), the opponent receiving at its 25
    ev = F.evaluate(_base(2, 2), _toy_wp, np.array([0.5]), np.array([0.9]), GAINS, np.full((1, 5), 85.0), np.zeros(1), 75.0, 1.0)
    assert ev["wp_go"][0] == pytest.approx(0.5 * 0.74 + 0.5 * 0.696, abs=1e-9)
    assert ev["wp_fg"][0] == pytest.approx(0.9 * 0.66 + 0.1 * 0.62, abs=1e-9)
    assert ev["rec"][0] == "go"
    # 4th and 10 at our own 1 with a big loss: tackled in our end zone is a safety (-2, then we kick from the 40)
    g2 = {"succ_excess": [[0.0] * 5] * 7, "fail_short": [[-12.0] * 5] * 7}
    ev = F.evaluate(_base(99, 10), _toy_wp, np.array([0.0]), np.array([0.0]), g2, np.full((1, 5), 60.0), np.zeros(1), 75.0, 1.0)
    # the opponent at its 40 (yardline_100 60) leading by 2: its WP .5 + .04 - .04 = .5
    assert ev["wp_go"][0] == pytest.approx(0.5, abs=1e-9)
    assert np.isnan(ev["wp_fg"][0])                       # a 116-yard field goal is not an option


def test_two_point_calculator_hand_worked():
    from oddsmarkets.nfl.models import fourth_down as F
    e = F.evaluate_two_point(_base(15, 0, sd=-1.0), _toy_wp, 0.94, 0.5, 75.0)
    assert e["wp_kick"][0] == pytest.approx(0.94 * 0.60 + 0.06 * 0.58, abs=1e-9)
    assert e["wp_two"][0] == pytest.approx(0.5 * 0.62 + 0.5 * 0.58, abs=1e-9)
    assert e["two_gain"][0] == pytest.approx(0.60 - 0.5988, abs=1e-9)
    assert e["rec"][0] == "either"            # 0.12 WP points: inside the toss-up band
    e = F.evaluate_two_point(_base(15, 0, sd=-1.0), _toy_wp, 0.94, 0.6, 75.0)
    assert e["rec"][0] == "two"               # .6 * .62 + .4 * .58 = .604 against .5988


def test_fourth_down_conversion_monotone_and_calibrated(env):
    from oddsmarkets.nfl.models import fourth_down as F
    f = env["fits"]["fourth"]
    X = pd.DataFrame({"ydstogo": np.arange(1, 16, dtype=float), "yardline_100": 50.0, "goal_to_go": 0.0, "is4": 1.0,
                      "off_r": 0.0, "def_r": 0.0, "era": 2023.0, "indoor": 0.0})
    p = F.conv_prob(f, X)
    assert np.all(np.diff(p) <= 1e-9) and p[0] - p[-1] > 0.25
    hi = F.conv_prob(f, X.assign(off_r=0.15))
    assert np.all(hi >= p - 1e-9)
    cal = f["calibration_4th"]
    assert cal["ece"] < 0.08
    assert cal["logloss"] <= cal["logloss_base_rate"] + 0.01


def test_fourth_down_grades_recover_planted_aggressiveness(env):
    from oddsmarkets.nfl.models import fourth_down as F
    fits = {"fourth": env["fits"]["fourth"], "wp": env["fits"]["wp"], "kick": env["fits"]["kick"]}
    r = F.grade_season(2024, fits=fits)
    assert r["ok"]
    dec = r["decisions"]
    assert set(dec["choice"]) <= {"go", "punt", "fg"} and (dec["wp_lost"] >= 0).all()
    assert (dec.loc[dec["choice"] == dec["rec"], "wp_lost"] == 0).all()
    planted = {v["coach"]: v["aggr"] for v in env["truth"][2024][1]["teams"].values()}
    c = r["coaches"]
    assert _spearman(c["go_oe_per100"], c["coach"].map(planted)) > 0.6
    assert "tries" in r and set(r["tries"]["rec"]) <= {"kick", "two", "either"}


# ============================================================================ kicking

def test_kicking_distance_altitude_and_kicker_effects(env):
    from oddsmarkets.nfl.models import kicking
    f = env["fits"]["kick"]
    fg = f["fg"]
    p = kicking.fg_prob(fg, [25.0, 40.0, 50.0, 58.0], 2023)
    assert np.all(np.diff(p) < 0) and p[0] > 0.9
    hi = kicking.fg_prob(fg, [50.0], 2023, altitude=[5280.0])[0]
    assert hi > kicking.fg_prob(fg, [50.0], 2023)[0]
    planted = {}
    for y, (_d, t) in env["truth"].items():
        for v in t["teams"].values():
            planted[v["k"]] = v["k_skill"]
    eff = fg["kickers"]
    ks = [k for k in eff if k in planted and eff[k][1] >= 30]
    assert len(ks) >= 20
    assert np.corrcoef([eff[k][0] for k in ks], [planted[k] for k in ks])[0, 1] > 0.4
    pun = f["punt"]
    oy, _ = kicking.punt_outcomes(pun, [80.0])
    assert 55 < np.median(oy) < 70       # ~41 net from our 20: the receiver near its 39-ish (yardline_100 61)


# ============================================================================ completion / YAC / RYOE

def test_completion_recovers_qb_skill_and_pressure(env):
    from oddsmarkets.nfl.models import completion
    f = completion.fit(list(SEASONS))
    assert {t["name"] for t in f["tiers"]} >= {"base", "part", "ftn", "ftn_part"}
    t = completion.season_rows(2023)
    pt = completion.passer_table(t)
    planted = {v["qb"]: v["qb_skill"] for v in env["truth"][2023][1]["teams"].values()}
    pt = pt[pt["passer"].isin(planted)]
    assert _spearman(pt["cpoe"], pt["passer"].map(planted)) > 0.6
    # pressure lowers cp (the participation tier sees it)
    x = t[t["season"] == 2023].head(500)
    a = _io.predict_tiers(f, x.assign(p_pressure=0.0, qb_hit=0.0, f_oop=0.0), completion.TIERS)
    b = _io.predict_tiers(f, x.assign(p_pressure=1.0, qb_hit=0.0, f_oop=0.0), completion.TIERS)
    assert np.mean(a - b) > 0.04
    v = f["validation"]
    assert v["ours"]["logloss"] < v["nflverse_cp"]["logloss"]      # the synthetic nflverse cp is a crude stand-in


def test_ryoe_recovers_rusher_skill_and_box(env):
    from oddsmarkets.nfl.models import ryoe
    f = ryoe.fit(list(SEASONS))
    t = ryoe.season_rows(2023)
    rt = ryoe.rusher_table(t)
    planted = {}
    for v in env["truth"][2023][1]["teams"].values():
        planted.update(dict(zip(v["rbs"], v["rb_skill"])))
    rt = rt[rt["rusher"].isin(planted) & (rt["att"] >= 60)]
    assert _spearman(rt["ryoe_per_att"], rt["rusher"].map(planted)) > 0.6
    x = t.head(400)
    lo = _io.predict_tiers(f, x.assign(p_box=6.0, f_box=6.0), ryoe.TIERS)
    hi = _io.predict_tiers(f, x.assign(p_box=8.0, f_box=8.0), ryoe.TIERS)
    assert np.all(hi <= lo + 1e-9) and np.mean(lo - hi) > 0.8
    assert f["validation"]["ngs"]["corr"] > 0.5


def test_yac_recovers_receiver_skill(env):
    from oddsmarkets.nfl.models import yac
    yac.fit(list(SEASONS))
    t = yac.season_rows(2022)
    rt = yac.receiver_table(t)
    planted = {}
    for v in env["truth"][2022][1]["teams"].values():
        planted.update(dict(zip(v["wrs"], v["wr_yac"])))
    rt = rt[rt["receiver"].isin(planted) & (rt["rec"] >= 40)]
    assert _spearman(rt["yacoe"], rt["receiver"].map(planted)) > 0.6


# ============================================================================ player value, pressure, QB, stabilisation

def test_player_value_raw_sums_and_adjusted_ranking(env):
    from oddsmarkets.nfl.models import player_value as PV
    d = _io.plays(2024)
    p = PV.play_rows(d)
    raw = PV.raw_attribution(p)
    by = raw.groupby("role")["raw_epa"].sum()
    assert by["passer"] == pytest.approx(p.loc[p["passer"].notna(), "epa"].sum(), abs=1e-6)
    assert by["rusher"] == pytest.approx(p.loc[p["rusher"].notna() & p["passer"].isna(), "epa"].sum(), abs=1e-6)
    rc = raw[raw["role"] == "receiver"]
    assert np.allclose(rc["air_epa"] + rc["yac_epa"], rc["raw_epa"], atol=1e-6)
    r = PV.season_value(2024, d)
    pl = r["players"]
    qbs = pl[pl["role"] == "passer"]
    planted = {v["qb"]: v["qb_skill"] for v in env["truth"][2024][1]["teams"].values()}
    qbs = qbs[qbs["player"].isin(planted)]
    assert _spearman(qbs["adj_per_play"], qbs["player"].map(planted)) > 0.5
    assert "rapm" not in r or len(r["rapm"]) > 0       # 2024 has (synthetic) participation
    assert len(r["defense"]) == 8


def test_pressure_tables(env):
    from oddsmarkets.nfl.models import pressure
    t = pressure.season_tables(2023)
    off = t["team_offense"]
    assert len(off) == 8 and off["sack_rate"].between(0.0, 0.3).all()
    assert abs((off["sacks"] - off["x_sacks"]).sum()) < 1e-6      # expected sacks sum to the league's sacks
    assert (t["qbs"]["pressure_rate"] > 0.15).all()


def test_stabilise_recovers_beta_binomial_k():
    from oddsmarkets.nfl.models import stabilise
    rng = np.random.default_rng(3)
    a, b = 6.0, 54.0                            # true rate ~ Beta(6, 54): k = a + b = 60
    rows = []
    for e in range(300):
        p = rng.beta(a, b)
        n = 600
        rows.append(pd.DataFrame({"entity": f"e{e}", "t": np.arange(n), "v": (rng.random(n) < p).astype(float)}))
    ev = pd.concat(rows, ignore_index=True)
    k = stabilise.fit_k(stabilise.split_half_curve(ev))
    assert 40 < k < 90


def test_qb_composite_shrinks_and_ranks(env):
    from oddsmarkets.nfl.models import completion, qb
    completion.fit(list(SEASONS))
    h = qb.history(list(SEASONS))
    c = qb.composite(h, 2024, {"w": qb.DEFAULT_W})
    assert len(c) >= 8
    for comp in qb.COMPONENTS:
        lg = c["league_" + comp].iloc[0]
        raw_dev = (c[comp] - lg).abs()
        post_dev = (c["post_" + comp] - lg).abs()
        assert (post_dev <= raw_dev + 1e-9).mean() > 0.7, comp
    planted = {v["qb"]: v["qb_skill"] for v in env["truth"][2024][1]["teams"].values()}
    c = c[c["qb"].isin(planted)]
    assert _spearman(c["composite"], c["qb"].map(planted)) > 0.5


# ============================================================================ IO: fitted fallback, schema on the recorded slice

def test_fitted_export_and_cold_cache_fallback(env, tmp_path, monkeypatch):
    from oddsmarkets.nfl.models import ep
    f = env["fits"]["ep"]
    _io.export_fit("ep", f)
    monkeypatch.setenv("GRIDIRON_CACHE", str(tmp_path / "cold"))
    g = _io.get_fit("ep", ep.MODEL_VERSION)
    assert g is not None and g["models"]["main"] == f["models"]["main"]
    d = _io.read_parquet(Path(os.environ["GRIDIRON_RAW"]) / "raw" / "pbp" / "play_by_play_2024.parquet")
    d = _io.prepare(d).head(300)
    m = ep.is_model_play(d)
    assert np.allclose(ep.predict(g, d[m]), ep.predict(f, d[m]))


def test_prepare_and_joins_on_recorded_slice():
    d = _io.prepare(_io.read_parquet(FIX / "pbp_2025_slice.parquet", _io.PBP_COLUMNS))
    d = _io.attach_participation(d, _io.read_parquet(FIX / "participation_2025_slice.parquet"))
    d = _io.attach_ftn(d, _io.read_parquet(FIX / "ftn_2025_slice.parquet"))
    g = d[d["game_id"] == "2025_13_JAX_TEN"]
    assert g["p_box"].notna().sum() > 100 and g["f_box"].notna().sum() > 100
    assert set(g["p_pressure"].dropna().unique()) <= {0.0, 1.0}
    assert g["pos_spread"].notna().all()
    assert d["td_team"].dtype == object and d["roof_code"].notna().any()
