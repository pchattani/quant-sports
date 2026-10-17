"""Builder B (The Quant Rink models) on synthetic seasons with planted effects (models/synthetic_b.py).

One league (fixed talents) is simulated over three consecutive seasons — 2018-19 and 2019-20 with the hand-tracking
arena bias planted in BOS's rink, 2020-21 without — and written in builder A's layout under temporary roots; the
committed-fit directory is redirected to a temporary folder. No network.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nhl.models import _io, synthetic_b as S

SEASONS = (20182019, 20192020, 20202021)
N_GAMES = 180


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("rinkb")
    env = {"RINK_RAW": str(base / "raw"), "RINK_DATA": str(base / "data"), "RINK_CACHE": str(base / "raw" / "cache")}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    old_fitted = _io.FITTED
    _io.FITTED = base / "fitted"
    from oddsmarkets.nhl.models import stabilise
    stabilise._K.clear()
    sims = S.build(base / "raw", base / "data", seasons=SEASONS, n_games=N_GAMES, seed=11)
    from oddsmarkets.nhl.models import xg
    fit = xg.fit(list(SEASONS), use_cache=False)
    yield {"base": base, "sims": sims, "truth": sims[SEASONS[0]]["truth"], "xg": fit}
    _io.FITTED = old_fitted
    stabilise._K.clear()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _frame(obj: dict) -> pd.DataFrame:
    return pd.DataFrame(obj["rows"], columns=obj["cols"])


# ----------------------------------------------------------------------------- events

def test_events_canonical(world):
    ev = _io.events(SEASONS[1])
    assert len(ev) and list(ev.columns) == _io.EVENT_COLS
    assert ev.groupby("game_id")["idx"].apply(lambda s: s.nunique() == len(s)).all()
    g = ev[(ev["type"] == "goal") & (ev["shootout"] == 0)]
    first = g.groupby("game_id").head(1)
    assert ((first["score_h"] + first["score_a"]) == 0).all()          # score *before* the goal
    assert ev.loc[ev["period"] == 5, "shootout"].eq(1).all()
    assert set(ev["sk_h"].dropna().unique()) <= {0, 3, 4, 5, 6}
    gm = _io.back_to_back(_io.games(SEASONS[1], ev))
    assert {"b2b_home", "b2b_away"} <= set(gm.columns) and gm["b2b_home"].isin([0, 1]).all()


# ----------------------------------------------------------------------------- xG

def test_xg_calibrated_and_discriminating(world):
    v = world["xg"]["validation"]
    o = v["overall"]
    assert o["log_loss"] < o["log_loss_base"] - 0.015
    assert o["auc"] > 0.70
    assert abs(o["xg"] - o["goals"]) / o["goals"] < 0.03
    assert v["calibration"]["ece"] < 0.01
    for s in map(str, SEASONS):
        b = v["by_season"][s]
        assert abs(b["xg"] - b["goals"]) / b["goals"] < 0.10
    # empty-net shots are scored by their own logistic, not the trees
    en = v["by_strength"]["empty_net"]
    assert en["n"] > 20 and abs(en["xg"] - en["goals"]) / en["goals"] < 0.35


def test_xg_planted_shape(world):
    from oddsmarkets.nhl.models import xg
    sh = xg.shot_table(SEASONS[2])
    assert len(sh) and sh["xg"].between(0, 1).all()
    near = sh[(sh["distance"] < 25) & (sh["empty_net"] == 0)]
    far = sh[(sh["distance"] > 45) & (sh["empty_net"] == 0)]
    assert near["xg"].mean() > 2.5 * far["xg"].mean()
    m = sh["empty_net"] == 0
    reb = sh[m & (sh["rebound"] == 1)]
    non = sh[m & (sh["rebound"] == 0) & (sh["distance"] < 20)]
    assert reb["xg"].mean() > non["xg"].mean()                         # planted +1.1 logit for rebounds
    assert set(sh["danger"]) <= {"low", "medium", "high"}


def test_arena_adjustment_removes_planted_bias(world):
    from oddsmarkets.nhl.models import xg
    a = world["xg"]["arena"]
    for s in SEASONS[:2]:
        bos = a[str(s)]["arenas"]["BOS"]
        assert bos["ratio_before"] < 0.86                               # BOS scorer records shots ~22% closer
        assert 0.95 < bos["ratio_after"] < 1.05
        assert a[str(s)]["applied"]
        assert a[str(s)]["mean_abs_log_ratio_after"] < 0.5 * a[str(s)]["mean_abs_log_ratio_before"]
    post = a[str(SEASONS[2])]
    # the third season has no planted bias; it is adjusted only when it precedes the tracking cut-off (2023-24)
    from oddsmarkets.nhl.models import _io
    assert post["applied"] == (SEASONS[2] < _io.TRACKING_FIRST) and 0.92 < post["arenas"]["BOS"]["ratio_before"] < 1.08
    assert _io.TRACKING_FIRST == 20232024
    # unit level: quantile matching maps a shrunk sample back onto the reference distribution
    rng = np.random.default_rng(0)
    ref = rng.gamma(2.0, 15.0, 4000) + 4
    adj = xg._qmap(ref * 0.8, np.quantile(ref * 0.8, xg.ARENA_Q), np.quantile(ref, xg.ARENA_Q))
    assert abs(np.median(adj) / np.median(ref) - 1) < 0.02


def test_xg_moneypuck_benchmark_matches_shots(world):
    """The benchmark joins on game, period, second and shooter; a fake MoneyPuck file built from our own shots
    (xGoal = ours with noise) must match them all and report both models."""
    from oddsmarkets.nhl.models import xg
    s = SEASONS[2]
    sh = xg.shot_table(s)
    rng = np.random.default_rng(1)
    mp = pd.DataFrame({"season": s // 10000, "game_id": sh["game_id"] % 1_000_000, "period": sh["period"],
                       "time": np.round(sh["sec"]).astype(int), "shooterPlayerId": sh["shooter"],
                       "xGoal": np.clip(sh["xg"] * np.exp(rng.normal(0, 0.2, len(sh))), 0.001, 0.99),
                       "goal": sh["goal"], "event": np.where(sh["goal"] == 1, "GOAL", "SHOT"), "teamCode": sh["team"]})
    d = Path(os.environ["RINK_RAW"]) / "moneypuck"
    d.mkdir(parents=True, exist_ok=True)
    mp.to_parquet(d / f"shots_{s}.parquet", index=False)
    b = xg.benchmark_moneypuck(s, sh)
    assert b["ok"] and b["n_matched"] > 0.9 * len(sh)
    assert b["label_agreement"] == 1.0
    assert b["ours"]["log_loss"] <= b["moneypuck"]["log_loss"] + 1e-9
    assert b["team_season"]["r_ours_mp"] > 0.8


def test_score_events_aligns_with_any_frame(world):
    from oddsmarkets.nhl.models import xg
    ev = _io.events(SEASONS[2])
    x = xg.score_events(ev[["game_id", "idx", "type"]].assign(game_id=ev["game_id"].astype(str)))
    fen = ev["type"].isin(_io.UNBLOCKED).to_numpy() & (ev["shootout"].to_numpy() == 0)
    assert np.isfinite(x[fen]).mean() > 0.95 and not np.isfinite(x[~ev["type"].isin(_io.UNBLOCKED).to_numpy()]).any()
    out = xg.for_season(SEASONS[2])
    assert out["ok"] and {"game_id", "idx", "xg"} <= set(out["shots"].columns)


# ----------------------------------------------------------------------------- shooting and goalies

def test_shooting_recovers_planted_finishing(world):
    from oddsmarkets.nhl.models import shooting, xg
    sh = pd.concat([xg.shot_table(s) for s in SEASONS], ignore_index=True)
    t = shooting.table(sh, k=400.0, k_sh=300.0)
    t = t[t["attempts"] >= 150]
    true = t["player_id"].map(world["truth"]["finish"])
    assert _io.pearson(t["talent"], true) > 0.3
    # shrinkage: |gax_shrunk| <= |gax| and the same sign
    assert (t["gax_shrunk"].abs() <= t["gax"].abs() + 1e-9).all()
    assert (np.sign(t["gax_shrunk"]) == np.sign(t["gax"])).all()
    r = shooting.for_season(SEASONS[1])
    assert r["ok"] and _frame(r["players"])["gax"].notna().all()


def test_gsax_components_sum_and_recover_skill(world):
    from oddsmarkets.nhl.models import goalies, xg
    sh = pd.concat([xg.shot_table(s) for s in SEASONS], ignore_index=True)
    t = goalies.table(sh, k=1200.0)
    bands = t[[f"gsax_{b}" for b in goalies.BANDS]].sum(axis=1)
    types = t[[f"gsax_{ty}" for ty in goalies.TYPES]].sum(axis=1)
    assert np.allclose(bands, t["gsax"], atol=1e-6) and np.allclose(types, t["gsax"], atol=1e-6)
    f = goalies.faced(sh)
    assert np.isclose(t["gsax"].sum(), float(f["xg"].sum()) - float(f["goal"].sum()), atol=1e-2)
    assert np.isclose(t["fa"].sum(), len(f))
    true = t["player_id"].map(world["truth"]["save"])
    assert _io.pearson(t["gsax100"], true) > 0.6
    r = goalies.for_season(SEASONS[0])
    g = _frame(r["goalies"])
    assert r["ok"] and g["gsax60"].notna().all() and (g["toi"] > 0).all()


# ----------------------------------------------------------------------------- stints, on-ice, RAPM

def test_stints_attribute_every_attempt(world):
    from oddsmarkets.nhl.models import _stints
    st = _stints.build(SEASONS[1])
    ev = _io.events(SEASONS[1])
    att = ev[ev["type"].isin(_io.ATTEMPTS) & (ev["shootout"] == 0)]
    assert st.attrs["unattributed"] == 0
    assert np.isclose(st[["h_cf", "a_cf"]].to_numpy().sum(), len(att))
    goals = ((ev["type"] == "goal") & (ev["shootout"] == 0)).sum()
    assert np.isclose(st[["h_gf", "a_gf"]].to_numpy().sum(), goals)
    assert set(st["zs_h"]) <= {"O", "D", "N", "F"} and (st["zs_h"] != "F").mean() > 0.1
    assert {"5v5", "pp_h", "pp_a"} <= set(st["strength"])
    # adjusted counts preserve the league total roughly (weights centred on 1)
    assert 0.9 < st[["h_cf_adj", "a_cf_adj"]].to_numpy().sum() / len(att) < 1.1


def test_onice_rates(world):
    from oddsmarkets.nhl.models import onice
    r = onice.for_season(SEASONS[1])
    p = _frame(r["players"])
    assert r["ok"] and len(p) > 100
    reg = p[p["toi"] > 300]
    assert reg["cf_pct"].between(0.3, 0.7).all() and reg["xgf_pct_adj"].between(0.3, 0.7).all()
    # relative values centre on zero (TOI-weighted)
    assert abs(np.average(reg["xgf_pct_rel"], weights=reg["toi"])) < 0.02
    t = _frame(r["teams"])
    five = t[t["role"] == "5v5"]
    assert np.isclose(np.average(five["cf_pct"], weights=five["toi"]), 0.5, atol=0.01)
    pp = t[t["role"] == "pp"]
    assert (pp["xgf60"].mean() > 1.5 * five["xgf60"].mean())


def test_rapm_recovers_planted_effects(world):
    from oddsmarkets.nhl.models import _stints, rapm
    st = _stints.for_season(SEASONS[2])
    tr = world["truth"]
    for target, lo in (("xg", 0.45), ("cf", 0.55)):
        r = rapm.fit(st, target)
        df = pd.DataFrame([{"p": int(p), **v} for p, v in r["players"].items()])
        assert _io.pearson(df["o"], df["p"].map(tr["off"])) > lo
        assert _io.pearson(df["d"], df["p"].map(tr["def"])) > lo - 0.05
        assert (df["se_o"] > 0).all() and r["ridge"] in rapm.RIDGE_GRID
    r = rapm.fit(st, "xg")
    c, se = r["controls"], r["controls_se"]
    assert c["zs_O"] > 3 * se["zs_O"]                                  # planted offensive-zone start boost
    assert c["lead_m2"] > c["lead_p2"]                                 # trailing sides attack more
    assert c["home"] > 0


def test_rapm_multiseason_prior(world):
    from oddsmarkets.nhl.models import rapm
    res = rapm.chain(SEASONS[2])
    assert res["ok"]
    pl = res["xg"]["players"]
    assert np.mean([abs(v["prior_o"]) > 0 for v in pl.values()]) > 0.8   # centred on last season x carry
    out = rapm.for_season(SEASONS[2])
    df = _frame(out["players"])
    tr = world["truth"]
    assert _io.pearson(df["off"], df["player_id"].map(tr["off"])) > 0.5
    assert {"off", "def", "net", "off_se", "gf", "ga", "cf", "ca"} <= set(df.columns)
    ex = rapm.export_fits()
    assert ex["ok"] and (_io.FITTED / "rapm_prior.json").exists()


# ----------------------------------------------------------------------------- value and lines

def test_rink_value(world):
    from oddsmarkets.nhl.models import value
    v = value.for_season(SEASONS[2])
    assert v["ok"], v.get("reason")
    env = v["environment"]
    assert 4.0 < env["goals_per_win"] < 9.0 and 0.05 < env["goals_per_minor"] < 0.4
    sk = _frame(v["skaters"])
    comp = sk[["ev_off", "ev_def", "pp", "pk", "shooting", "pen"]].sum(axis=1)
    assert np.allclose(comp, sk["gaa"], atol=1e-3)
    assert np.allclose(sk["war"] * env["goals_per_win"], sk["gar"], atol=1e-3)
    reg = sk[sk["toi5"] > 400]
    tr = world["truth"]
    true = reg["player_id"].map(lambda p: tr["off"].get(p, 0.0) + tr["def"].get(p, 0.0))
    assert _io.pearson(reg["off"] + reg["def"], true) > 0.45
    g = _frame(v["goalies"])
    assert len(g) and np.isfinite(g["war"]).all()


def test_lines(world):
    from oddsmarkets.nhl.models import lines
    r = lines.for_season(SEASONS[1])
    assert r["ok"] and r["forwards"] and r["pairs"]
    assert all(len(u["players"]) == 3 for u in r["forwards"]) and all(len(u["players"]) == 2 for u in r["pairs"])
    for u in r["forwards"][:30]:
        lo, hi = sorted([u["xgf_pct"], u["team_xgf_pct"]])
        assert lo - 1e-6 <= u["xgf_pct_shrunk"] <= hi + 1e-6               # shrunk towards the team's share
    top = max(r["forwards"], key=lambda u: u["toi"])
    assert top["toi"] > 100


# ----------------------------------------------------------------------------- stabilisation

def test_split_half_recovers_known_k():
    """Bernoulli events with talent sd: the theoretical k = p(1-p) / var(talent)."""
    from oddsmarkets.nhl.models import stabilise
    rng = np.random.default_rng(3)
    n_ent, n_ev = 300, 1200
    p = np.clip(0.5 + rng.normal(0, 0.05, n_ent), 0.05, 0.95)
    ent = np.repeat(np.arange(n_ent), n_ev)
    v = (rng.random(n_ent * n_ev) < p[ent]).astype(float)
    u = pd.DataFrame({"entity": ent.astype(float), "t": np.tile(np.arange(n_ev), n_ent).astype(float), "a": v, "b": 1.0,
                      "den": 1.0})
    curve = stabilise.split_half_curve(u, stabilise.GRID_EVENTS)
    k = stabilise.fit_k(curve)
    k_true = 0.25 / 0.05 ** 2
    assert 0.7 * k_true < k < 1.4 * k_true
    assert abs(stabilise.point("fo_pct") - stabilise.shrink_k("fo_pct") * 0.7 / 0.3) < 1e-9


def test_stabilise_season_and_export(world):
    from oddsmarkets.nhl.models import stabilise
    r = stabilise.season_stability(SEASONS[1])
    assert r["finishing"]["k"] and r["shot_quality"]["k"] and r["cf_pct"]["k"]
    assert all(c[0] > 0 for c in r["cf60"]["curve"])
    ex = stabilise.export_fits(list(SEASONS))
    assert ex["metrics"]["shot_quality"]["unit"] == "events" and ex["metrics"]["cf_pct"]["unit"] == "seconds"
    assert stabilise.shrink_k("cf_pct") == ex["metrics"]["cf_pct"]["k"]


# ----------------------------------------------------------------------------- committed-fit fallback

def test_export_and_fitted_fallback(world, monkeypatch, tmp_path):
    from oddsmarkets.nhl.models import xg
    _io.export_fit("xg", world["xg"])
    assert (_io.FITTED / "xg.json").exists() and (_io.FITTED / "xg_main.txt.gz").exists()
    monkeypatch.setenv("RINK_CACHE", str(tmp_path / "cold"))             # CI: an empty cache
    f = xg.current_fit()
    assert f is not None and f["models"]["main"] and f["version"] == xg.MODEL_VERSION
    t, _ = xg.attempts(_io.events(SEASONS[2]), SEASONS[2])
    p = xg.predict_raw(f, t)
    assert np.isfinite(p).all() and abs(p.mean() - t["goal"].mean()) < 0.01
