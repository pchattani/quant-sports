"""Market-implied ratings (oddsmarkets/college/informed.py): the ridge, the walk-forward cut, the prior, the stack."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.college import informed as INF


def _games(n_days=20, teams=8, seed=0):
    rng = np.random.default_rng(seed)
    r = {f"t{i}": float(v) for i, v in enumerate(rng.normal(0, 7, teams))}
    rows = []
    for d in range(n_days):
        order = rng.permutation(teams)
        for k in range(0, teams, 2):
            h, a = f"t{order[k]}", f"t{order[k + 1]}"
            neu = bool(rng.random() < 0.2)
            line = (0.0 if neu else 3.0) + r[h] - r[a]
            rows.append((1000 + d, h, a, neu, line))
    df = pd.DataFrame(rows, columns=["day", "home", "away", "neutral", "line"])
    return df, r


def test_season_path_recovers_ratings_and_home_term():
    df, r = _games()
    last = int(df["day"].max()) + 1
    p = INF.season_path(df["day"], df["home"], df["away"], df["neutral"], df["line"], [last], half_life=1e6, lam=1e-6)
    sol = p[last]
    assert abs(sol["h"] - 3.0) < 1e-3
    est = np.array([sol["r"][t] for t in sorted(r)])
    true = np.array([r[t] for t in sorted(r)])
    assert np.allclose(est - est.mean(), true - true.mean(), atol=1e-3)
    assert sol["n"] == len(df)


def test_season_path_uses_only_earlier_days():
    df, _ = _games(n_days=5)
    d2 = 1002
    p = INF.season_path(df["day"], df["home"], df["away"], df["neutral"], df["line"], [1000, d2])
    assert p[1000]["n"] == 0                                    # nothing before the first day: the prior
    assert p[d2]["n"] == int((df["day"] < d2).sum())
    # changing a line on day d2 or later cannot move the ratings for day d2
    df2 = df.copy()
    df2.loc[df2["day"] >= d2, "line"] += 30.0
    q = INF.season_path(df2["day"], df2["home"], df2["away"], df2["neutral"], df2["line"], [d2])
    assert all(abs(q[d2]["r"][t] - p[d2]["r"][t]) < 1e-12 for t in p[d2]["r"])


def test_ridge_pulls_toward_prior():
    df, _ = _games(n_days=2)
    last = 1002
    prior = {t: 50.0 for t in set(df["home"]) | set(df["away"])}
    strong = INF.season_path(df["day"], df["home"], df["away"], df["neutral"], df["line"], [last], prior=prior, lam=1e6)
    assert all(abs(v - 50.0) < 1e-2 for v in strong[last]["r"].values())


def test_totals_kind():
    rng = np.random.default_rng(1)
    t = {f"t{i}": float(v) for i, v in enumerate(rng.normal(0, 3, 6))}
    rows = [(1000 + d, h, a, False, 140 + t[h] + t[a]) for d in range(30) for h in t for a in t if h < a]
    df = pd.DataFrame(rows, columns=["day", "home", "away", "neutral", "tot"])
    p = INF.season_path(df["day"], df["home"], df["away"], df["neutral"], df["tot"], [1031], kind="total", half_life=1e6,
                        lam=1e-6)[1031]
    pred = p["h"] + p["r"]["t0"] + p["r"]["t1"]
    assert abs(pred - (140 + t["t0"] + t["t1"])) < 1e-3


def test_carry_prior_regresses_to_new_conference():
    end = {"a": 10.0, "b": -10.0, "c": 4.0, "d": 0.0}
    conf_last = {"a": "1", "b": "1", "c": "2", "d": "2"}
    conf_now = {"a": "2", "b": "1", "c": "2", "d": "2", "new": "1"}
    pr = INF.carry_prior(end, conf_last, conf_now, {k: "fbs" for k in conf_now}, carry=0.5)
    cm2 = np.mean([10.0, 4.0, 0.0])           # conference 2 as constituted now (a moved in)
    assert abs(pr["a"] - (cm2 + 0.5 * (10.0 - cm2))) < 1e-9
    assert abs(pr["new"] - (-10.0)) < 1e-9    # a team without a rating starts at its conference's mean


def test_walk_stack_is_walk_forward():
    rng = np.random.default_rng(2)
    n = 3000
    F = pd.DataFrame({"season": np.repeat([2013, 2014, 2015], n // 3), "dayn": np.arange(n),
                      "spread": rng.normal(0, 7, n), "fit_line": True, "scope": True, "sd0": 12.0,
                      "phase": "mid"})
    F["y"] = -F["spread"] + rng.normal(0, 11, n)
    X = np.column_stack([np.ones(n), -F["spread"].to_numpy()])
    W = INF.walk_stack(F, X, "mbb", train0=2013)
    assert W.loc[F["season"] == 2013, "mu"].isna().all()       # the first season has nothing earlier to learn from
    assert W.loc[F["season"] == 2014, "mu"].notna().all()
    assert abs(W.attrs["coefs"][2014][1] - 1.0) < 5e-3            # a light ridge
    # season 2015's coefficients do not change when 2015's own targets change
    F2 = F.copy()
    F2.loc[F2["season"] == 2015, "spread"] *= 3
    W2 = INF.walk_stack(F2, X, "mbb", train0=2013)
    assert W2.attrs["coefs"][2015] == W.attrs["coefs"][2015]


def test_hoops_trial_line_is_walk_forward(tmp_path, monkeypatch):
    from oddsmarkets.college.hoops import data as D
    from oddsmarkets.college.hoops import market_informed as HMI
    from oddsmarkets.college.hoops import model as M

    from .hoops_synth import make_level
    for k, d in (("CAMPUS_STORES", "stores"), ("CAMPUS_RAW", "raw"), ("CAMPUS_CACHE", "cache"), ("CAMPUS_DATA", "data")):
        monkeypatch.setenv(k, str(tmp_path / d))
    D._CACHE.clear()
    make_level("mbb", seasons=(2025, 2026))
    st8 = M.level_state("mbb", use_cache=False, log=False)
    spec = {"half_life": 60.0, "lam": 0.25, "carry": 0.7}
    fit = {"version": 1, "level": "mbb", "season": 2026, "status": "trial",
           "cfg": {"mk": spec, "rd": {"half_life": 60.0, "lam": 4.0, "carry": 0.5}, "target": "close", "no_inter": True},
           "names": ["const", "nn", "m0", "mk", "rd"], "coefs": [0.0, 0.0, 0.5, 0.5, 0.3],
           "cal": {"c0": 0.0, "sd": {"early": 11.0, "mid": 11.0, "post": 11.0}}, "prior": {}}
    monkeypatch.setattr(INF, "load_fit", lambda lv: fit if lv == "mbb" else None)
    a = HMI.predict(st8, "mbb", 2026, M.current_fit(st8, 2026))
    assert len(a) > 100 and all(0.0 < v["p_home"] < 1.0 for v in a.values())
    assert all(v["status"] == "trial" for v in a.values())
    G = st8["tabs"][2026]["g"]
    last = int(np.max(G["day"]))
    G["spread"] = np.where(G["day"] == last, G["spread"] + 20.0, G["spread"])     # rewrite the last day's lines
    b = HMI.predict(st8, "mbb", 2026, M.current_fit(st8, 2026))
    early = [str(g) for g, d in zip(G["gid"], G["day"]) if d < last]
    assert early and all(abs(a[g]["p_home"] - b[g]["p_home"]) < 1e-12 for g in early if g in a)
    assert HMI.predict(st8, "mbb", 2025, None) == {}                              # no fit for that season


def test_weather_windows_cover_dates_in_14_day_calls():
    from datetime import date

    from oddsmarkets.college.sources import weather as WX
    ds = [date(2025, 9, 6), date(2025, 9, 13), date(2025, 9, 27), date(2025, 10, 4), date(2025, 11, 29)]
    w = WX.windows(ds)
    assert w == [(date(2025, 9, 6), date(2025, 9, 13)), (date(2025, 9, 27), date(2025, 10, 4)),
                 (date(2025, 11, 29), date(2025, 11, 29))]
    assert all((b - a).days < 14 for a, b in w)
