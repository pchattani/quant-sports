"""Builder B pitch models on synthetic seasons with planted truth (no network, no real data)."""
from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.models import _io, synthetic as S


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    raw = tmp_path_factory.mktemp("bullpen_raw")
    old = {k: os.environ.get(k) for k in ("BULLPEN_RAW", "BULLPEN_CACHE")}
    os.environ["BULLPEN_RAW"] = str(raw)
    os.environ["BULLPEN_CACHE"] = str(raw / "cache")
    truth = {}
    for i, y in enumerate((2023, 2024, 2025)):
        df, t = S.write_season(raw, seed=10 + i, n_games=220, season_year=y)
        truth[y] = (df, t)
    # a season without bat tracking
    S.write_season(raw, level="aaa", seed=99, n_games=20, season_year=2019, bat_tracking=False)
    yield {"raw": raw, "truth": truth}
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _sorted_truth(env, y):
    df, t = env["truth"][y]
    return _io.sort_pitches(df.copy()), t


# ----------------------------------------------------------------------------- physics

def test_physics_reproduces_planted_movement_and_vaa(env):
    from oddsmarkets.baseball.models import physics
    df, _ = _sorted_truth(env, 2024)
    raw = df[[c for c in df.columns if not c.startswith("_")]].copy()
    out = physics.add_physics(raw.copy())
    assert np.max(np.abs(out["pfx_x_calc"] - df["pfx_x"])) * 12 < 1e-3
    assert np.max(np.abs(out["pfx_z_calc"] - df["pfx_z"])) * 12 < 1e-3
    assert np.max(np.abs(out["vaa"] - df["_vaa"])) < 1e-3
    assert np.max(np.abs(out["x_dp"] - df["_x_dp"])) < 1e-4
    v = physics.validate(raw)
    for k in ("pfx_x", "pfx_z", "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in", "release_x", "release_z"):
        assert v[k]["mae_in"] < 0.01, k


def test_physics_against_numerical_integration():
    """Integrate the flight numerically from the release point and measure the movement geometrically."""
    from oddsmarkets.baseball.models import physics
    tr = S.trajectory_one(95.0, -0.6, 1.35, -2.0, 6.0, 6.5, 0.3, 2.8)
    df = pd.DataFrame([{**{k: tr[k] for k in ("vx0", "vy0", "vz0", "ax", "ay", "az")}, "plate_x": 0.3, "plate_z": 2.8,
                        "release_pos_x": -2.0, "release_pos_y": 54.0, "release_pos_z": 6.0, "p_throws": "R", "stand": "R"}])
    out = physics.add_physics(df)
    t9 = physics.trajectory(df)
    x, y, z = (float(a[0]) for a in physics.position(t9, t9["t_rel"]))
    vx, vy, vz = (float(a[0]) for a in physics.velocity(t9, t9["t_rel"]))
    assert abs(x + 2.0) < 1e-6 and abs(y - 54.0) < 1e-6 and abs(z - 6.0) < 1e-6
    x_line = x + vx / vy * (_io.Y_FRONT - y)
    z_line = z + vz / vy * (_io.Y_FRONT - y)
    dt, t = 1e-5, 0.0
    while y > _io.Y_FRONT:
        x += vx * dt + 0.5 * tr["ax"] * dt * dt; y += vy * dt + 0.5 * tr["ay"] * dt * dt; z += vz * dt + 0.5 * tr["az"] * dt * dt
        vx += tr["ax"] * dt; vy += tr["ay"] * dt; vz += tr["az"] * dt
        t += dt
    assert abs(x - 0.3) < 2e-3 and abs(z - 2.8) < 2e-3
    assert abs(math.degrees(math.atan2(vz, -vy)) - float(out["vaa"][0])) < 0.01
    assert abs(t - float(out["t_plate"][0])) < 1e-4
    ivb = 0.5 * _io.G_FT * t * t - (z_line - z)
    assert abs(float(out["pfx_z_calc"][0]) - ivb) * 12 < 0.02 and abs(ivb - 1.35) * 12 < 0.02
    assert abs(float(out["pfx_x_calc"][0]) - (x - x_line)) * 12 < 0.02 and abs((x - x_line) + 0.6) * 12 < 0.02
    assert abs(float(out["brk_z_grav"][0]) - (z_line - z)) * 12 < 0.02


def test_movement_axis_convention_and_ssw(env):
    from oddsmarkets.baseball.models import physics, prep
    a = physics.movement_axis(np.array([-0.7, 0.7]), np.array([1.3, 1.3]))
    assert 200 < a[0] < 215 and 145 < a[1] < 160          # RHP / LHP riding fastballs
    df, t = _sorted_truth(env, 2024)
    e = prep.enrich(df[[c for c in df.columns if not c.startswith("_")]])
    ssw_p = {p for p, v in t["pitchers"].items() if v["ssw"]}
    m = e["pitch_type"].isin(["SI", "CH", "FS"])
    on = e[m & e["pitcher"].isin(ssw_p)]["ssw"].mean()
    off = e[m & ~e["pitcher"].isin(ssw_p)]["ssw"].mean()
    assert on > 0.6 and off < 0.2
    assert e.loc[m & e["pitcher"].isin(ssw_p), "axis_dev"].abs().mean() > 20


def test_release_consistency(env):
    from oddsmarkets.baseball.models import physics, prep
    df, _ = _sorted_truth(env, 2024)
    e = prep.enrich(df[[c for c in df.columns if not c.startswith("_")]])
    rc = physics.release_consistency(e)
    # planted release noise: sd 0.12 ft side, 0.10 ft height
    assert abs(rc["sd_side_in"].median() - 1.44) < 0.3
    assert abs(rc["sd_height_in"].median() - 1.2) < 0.3


# ----------------------------------------------------------------------------- stuff

def test_stuff_recovers_planted_stuff_and_scales_to_100(env):
    from oddsmarkets.baseball.models import prep, stuff
    m = stuff.model_for("mlb", 2025)
    assert m["ok"] and m["seasons"] == [2023, 2024]
    json.dumps(m)
    # scaling season (2024) averages 100
    e24 = prep.prepared("mlb", 2024)
    sc24 = stuff.score(e24[stuff.usable(e24)], m)
    assert abs(sc24["stuff"].mean() - 100) < 1e-3
    # out of sample 2025: stuff tracks the planted latent within each family
    df, _ = _sorted_truth(env, 2025)
    e = prep.prepared("mlb", 2025)
    u = stuff.usable(e).to_numpy()
    sc = stuff.score(e[u], m)
    lat = df["_stuff"].to_numpy()[u]
    for fam in ("fastball", "breaking"):
        f = (sc["family"] == fam).to_numpy()
        assert np.corrcoef(sc["stuff"].to_numpy()[f], lat[f])[0, 1] > 0.6, fam
    imp = m["importance"]["fastball"]["whiff"]
    assert max(imp, key=imp.get) in ("release_speed", "ivb", "vaa_adj", "release_extension")
    v = stuff.validate(e, m)
    w = v["families"]["fastball"]["whiff"]
    assert w["logloss"] < w["logloss_const"]
    r = stuff.for_season("mlb", 2025)
    assert r["ok"] and r["pitchers"]
    json.dumps(r)


# ----------------------------------------------------------------------------- location

def test_location_surface_and_scaling(env):
    from oddsmarkets.baseball.models import location, prep
    m = location.model_for("mlb", 2025)
    assert m["ok"]
    g = location.grid(m, "fastball", 0, 0, 0)
    rv = np.array(g["rv"])
    xi, zi = list(g["x"]).index(0.0), int(np.argmin(np.abs(np.array(g["z"]) - 0.5)))
    heart = rv[zi, xi]
    # low-away edge and well outside (a ball): both better for the pitcher than the heart in 0-0 ...
    edge = rv[int(np.argmin(np.abs(np.array(g["z"]) - 0.0))), int(np.argmin(np.abs(np.array(g["x"]) - 0.75)))]
    assert heart > edge
    # ... but in 3-0 a pitch far outside is worse for the pitcher than one in the zone
    g30 = np.array(location.grid(m, "fastball", 0, 3, 0)["rv"])
    assert g30[0, 0] > g30[zi, xi]
    e = prep.prepared("mlb", 2024)
    sc = location.score(e[location.usable(e)], m)
    assert abs(sc["location"].mean() - 100) < 1e-3
    # pitchers with planted sharper command score better
    _, t = env["truth"][2024]
    per = sc.groupby("pitcher")["location"].mean()
    cmd = pd.Series({p: v["command"] for p, v in t["pitchers"].items()})
    j = pd.concat([per, cmd], axis=1, join="inner")
    assert np.corrcoef(j.iloc[:, 0], -j.iloc[:, 1])[0, 1] > 0.3


# ----------------------------------------------------------------------------- pitching

def test_pitching_combines_and_scales(env):
    from oddsmarkets.baseball.models import location, pitching, stuff
    r = pitching.for_season("mlb", 2025)
    assert r["ok"]
    m = pitching.model_for("mlb", 2025)
    sc24 = pitching.season_scores("mlb", 2024, models=(stuff.model_for("mlb", 2025), location.model_for("mlb", 2025), m))
    assert {"stuff", "location", "pitching"} <= set(sc24.columns)
    assert abs(sc24["pitching"].mean() - 100) < 1e-3     # 2024 is the 2025 model's scaling season
    assert set(m["importance"]) >= {"stuff_xrv", "loc_rel"}
    k = next(iter(r["rolling"]))
    assert len(r["rolling"][k][0]) == 6
    json.dumps(r)


# ----------------------------------------------------------------------------- swing decisions

def test_swing_recovers_aggression_discipline_and_sums(env):
    from oddsmarkets.baseball.models import prep, swing
    m = swing.model_for("mlb", 2025)
    e = prep.prepared("mlb", 2025)
    dec, h = swing.season_table(e, m)
    # swings more likely in the zone
    assert dec.loc[dec["in_zone"] == 1, "p_sw"].mean() > dec.loc[dec["in_zone"] == 0, "p_sw"].mean() + 0.2
    _, t = env["truth"][2025]
    tb = pd.DataFrame.from_dict(t["batters"], orient="index")
    j = h.join(tb[["aggr", "disc"]], how="inner")
    assert np.corrcoef(j["aggression"], j["aggr"])[0, 1] > 0.5
    assert np.corrcoef(j["dv_c"], j["disc"])[0, 1] > 0.3
    # decision value bookkeeping
    assert np.allclose(h["dv"], h["dv_zone"] + h["dv_chase"], atol=1e-6)
    assert abs(h["dv"].sum() - dec["dv"].astype(float).sum()) < 1e-3
    assert abs(h["dv_c"].sum()) < 1e-3
    # dv per pitch is the chosen value minus its expectation
    i = dec.index[0]
    r = dec.loc[i]
    exp = r.p_sw * r.rv_sw + (1 - r.p_sw) * r.rv_tk
    assert abs(r.dv - ((r.rv_sw if r.swing else r.rv_tk) - exp)) < 1e-5
    out = swing.for_season("mlb", 2025)
    assert out["ok"] and out["leaders"]["dv_c"]
    json.dumps(out)


# ----------------------------------------------------------------------------- tunneling

def test_tunneling_effect_on_whiff(env):
    from oddsmarkets.baseball.models import tunneling
    r = tunneling.for_season("mlb", 2025)
    assert r["ok"]
    b = r["whiff"]["logit"]["tunnel_z"]
    assert b["b"] > 0 and b["b"] / b["se"] > 5
    d = r["whiff"]["deciles"]["whiff"]
    assert d[-1] > d[0]
    json.dumps(r)


# ----------------------------------------------------------------------------- bat tracking

def test_battrack_adjusted_bat_speed_and_absence(env):
    from oddsmarkets.baseball.models import battrack
    r = battrack.for_season("mlb", 2025)
    assert r["ok"]
    _, t = env["truth"][2025]
    h = pd.DataFrame.from_dict(r["hitters"], orient="index")
    h.index = h.index.astype(int)
    tb = pd.DataFrame.from_dict(t["batters"], orient="index")
    j = h.join(tb[["bat_speed", "attack"]].rename(columns={"bat_speed": "true_bs"}), how="inner")
    j = j[j["n"] >= 100]
    assert np.corrcoef(j["bat_speed_adj"], j["true_bs"])[0, 1] > 0.85
    # squared-up falls with swing-path mismatch (planted)
    bands = r["info"]["mismatch_bands"]
    first, last = list(bands.values())[0]["sq"], list(bands.values())[-2]["sq"]
    assert first > last
    none = battrack.for_season("aaa", 2019)
    assert none["ok"] is False
    json.dumps(r)


# ----------------------------------------------------------------------------- fatigue

def test_fatigue_within_game_and_tto(env):
    from oddsmarkets.baseball.models import fatigue
    r = fatigue.for_season("mlb", 2025)
    assert r["ok"]
    _, t = env["truth"][2025]
    lw = r["league"]["within"]["velo"]["slope_per100"]
    planted = np.mean([v["fatigue"] for v in t["pitchers"].values()])
    assert abs(lw + planted) < 0.4
    p = pd.DataFrame.from_dict(r["pitchers"], orient="index")
    p.index = p.index.astype(int)
    f = pd.Series({k: v["fatigue"] for k, v in t["pitchers"].items()})
    j = p[["velo_per100", "n_fb"]].join(f.rename("f"), how="inner").dropna()
    j = j[j["n_fb"] >= 300]
    assert np.corrcoef(j["velo_per100"], -j["f"])[0, 1] > 0.5
    assert r["league"]["tto"]["penalty"] > 0
    json.dumps(r)


def test_physics_for_season_and_booster_roundtrip(env):
    from oddsmarkets.baseball.models import physics, stuff, prep
    r = physics.for_season("mlb", 2025)
    assert r["ok"] and r["validation"]["pfx_z"]["mae_in"] < 0.01
    json.dumps(r)
    m = json.loads(json.dumps(stuff.model_for("mlb", 2025)))
    e = prep.prepared("mlb", 2025).head(500)
    a = stuff.score(e[stuff.usable(e)], m)["stuff"].to_numpy()
    _io._BOOSTERS.clear()
    b = stuff.score(e[stuff.usable(e)], m)["stuff"].to_numpy()
    assert np.allclose(a, b)


def test_load_pitches_missing_columns(env):
    df = _io.load_pitches("mlb", 2024, ["pitch_type", "not_a_column"])
    assert list(df.columns) == ["pitch_type", "not_a_column"] and df["not_a_column"].isna().all()
    assert _io.load_pitches("mlb", 1999, ["pitch_type"]).empty
