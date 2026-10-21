"""College basketball models on synthetic stores: ratings recover known strengths, the walk-forward never peeks,
the game model, the actual field and the selection proxy, bracket mechanics and the season simulation."""
import numpy as np
import pytest

from oddsmarkets.college import store as ST
from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import model as M
from oddsmarkets.college.hoops import ncaa as N
from oddsmarkets.college.hoops import ratings as R
from oddsmarkets.college.hoops import sim as SM
from oddsmarkets.college.hoops import tourney as TT

from .hoops_synth import make_level, make_season


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("CAMPUS_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("CAMPUS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CAMPUS_DATA", str(tmp_path / "data"))
    D._CACHE.clear()
    return tmp_path


@pytest.fixture
def level(roots):
    info = make_level("mbb", seasons=(2025, 2026), current=2027)
    return info


def test_possessions_box_and_scoreboard():
    g = {"home": "1", "away": "2", "hs": 70, "as": 65,
         "box": {"1": {"team": {"fga": 60, "oreb": 10, "tov": 12, "fta": 20, "fgm": 26, "tpm": 4, "ftm": 14}},
                 "2": {"team": {"fga": 58, "oreb": 8, "tov": 14, "fta": 22, "fgm": 24, "tpm": 5, "ftm": 12}}},
         "team_stats": {"1": {"fga": 60, "fta": 20}, "2": {"fga": 58, "fta": 22}}}
    assert D.box_poss(g) == pytest.approx(((60 - 10 + 12 + 9.5) + (58 - 8 + 14 + 0.475 * 22)) / 2)
    assert D.scoreboard_x(g) == pytest.approx((60 + 9.5 + 58 + 0.475 * 22) / 2)
    assert D.box_poss({"box": {}}) is None
    partial = {**g, "hs": 100}                       # an older partial box: its points do not add up to the score
    assert D.box_poss(partial) is None and not D.box_ok(partial, rel=0.1) and D.box_ok(g)


def test_neutral_inference_without_flags():
    games = {}
    for k in range(6):
        games[str(k)] = {"id": str(k), "stype": "reg", "home": "A", "away": "B", "neutral": False, "venue": {"name": "Home A"}}
    games["x"] = {"id": "x", "stype": "reg", "home": "A", "away": "C", "neutral": False, "venue": {"name": "Somewhere"}}
    games["t"] = {"id": "t", "stype": "ncaa", "home": "Q", "away": "R", "neutral": False, "venue": None}
    nm = D.neutral_map({"games": games})
    assert nm["x"] is True and nm["0"] is False and nm["t"] is True


def test_ratings_recover_strengths(level):
    tab = D.season_table("mbb", 2026)
    assert tab["teams"][-1] == D.ND1 and tab["T"] == 81
    e = R.end_ratings(tab, "mbb")
    st = level["strengths"]
    # the strengths dict was regressed after 2026 was written: compare ranks against the 2026 order loosely
    nets = [e["teams"][t]["net"] for t in sorted(st)]
    assert np.std(nets) > 3
    assert e["teams"][D.ND1]["net"] < np.mean(nets) - 10        # the pooled non-D-I team is far below
    f = R.fit(tab, None, R.empty_prior(tab, "mbb"), want_se=True)
    assert np.all(f["se"][:-1] > 0) and abs(np.mean(f["net"][tab["member"]])) < 1e-6


def test_walk_forward_does_not_peek(level):
    tab = D.season_table("mbb", 2026)
    pr = R.empty_prior(tab, "mbb")
    w1 = R.walk(tab, pr)
    G = tab["g"]
    mid = int(np.median(G["day"]))
    k = int(np.where(G["day"] == mid)[0][0])
    tab2 = {**tab, "g": {kk: v.copy() for kk, v in G.items()}}
    later = tab2["g"]["day"] >= mid
    tab2["g"]["hs"][later] = tab2["g"]["hs"][later] + 40              # rewrite every result from that day on
    w2 = R.walk(tab2, pr)
    assert w1["net_h"][k] == pytest.approx(w2["net_h"][k])
    assert w1["net_a"][k] == pytest.approx(w2["net_a"][k])
    after = np.where(G["day"] > mid)[0]
    assert not np.allclose(w1["net_h"][after], w2["net_h"][after])


def test_level_state_and_game_model(level):
    st8 = M.level_state("mbb", [2025, 2026, 2027], use_cache=False, log=False)
    assert st8["params"][2025]["n"] == 0 and st8["params"][2026]["n"] > 0     # 2026 parameters come from 2025 only
    pr = st8["preds"][2026]
    m = np.isfinite(pr["mu"])
    y = st8["feats"][2026]["margin"][m] > 0
    assert np.mean((pr["p"][m] > 0.5) == y) > 0.65
    f = M.current_fit(st8, 2027)                                              # preseason: the prior only
    assert f["n"] == 0 and np.all(np.isfinite(f["net"]))
    p = M.predict_one(f, 0, 1, False, st8["params"]["latest"], se=f["se"])
    assert 0 < p["p_home"] < 1 and p["spread_fair"] == pytest.approx(-p["margin"])


def test_actual_field_and_selection(level):
    st = D.load("mbb", 2026)
    af = TT.actual_field("mbb", 2026, st)
    assert af["field"] == 68 and len(af["first_four"]) == 4 and af["n_auto"] == 8 and af["n_at_large"] == 60
    assert sum(1 for v in af["teams"].values() if v["reached"] == "Champion") == 1
    assert len(af["regions"]) == 4
    st8 = M.level_state("mbb", [2025, 2026], use_cache=False, log=False)
    pre = {s: N.pretourney(st8, s) for s in (2025, 2026)}
    rows = N.selection_rows(st8, pre)
    assert all(r["has_seed"] for r in rows.values())
    lo = N.selection_loso(rows)
    assert lo["n_seasons"] == 2 and 0.5 < lo["at_large_acc"] <= 1 and lo["seed_mae"] < 3


def test_build_field_shapes():
    rng = np.random.default_rng(0)
    n = 120
    ids = np.arange(n)
    auto = np.zeros(n, bool)
    auto[rng.choice(n, 32, replace=False)] = True
    sel = rng.normal(size=n)
    sd = rng.normal(size=n)
    f = TT.build_field(ids, auto, sel, sd, 68, 4)
    assert len(f["field"]) == 68 and len(f["entries"]) == 64
    assert sorted(len(e) for e in f["entries"]).count(2) == 4
    assert all(1 <= v <= 16 for v in f["seed"].values())
    regs = TT.regions_from_entries(f["entries"])
    assert all(len(r) == 16 for r in regs)
    pos, ff = TT.bracket_arrays(regs)
    assert len(ff) == 4 and (pos >= 0).sum() == 60
    f65 = TT.build_field(ids, auto, sel, sd, 65, 1)
    assert sum(1 for e in f65["entries"] if len(e) == 2) == 1
    f64 = TT.build_field(ids, auto, sel, sd, 64, 0)
    assert all(len(e) == 1 for e in f64["entries"])


def test_sim_bracket_probabilities():
    rng = np.random.default_rng(1)
    T = 70
    strength = np.broadcast_to(np.linspace(30, -10, T), (3000, T)).copy()
    entries = [[k] for k in range(60)] + [[60, 61], [62, 63], [64, 65], [66, 67]]
    regs = TT.regions_from_entries(entries)
    pos, ff = TT.bracket_arrays(regs)
    res = TT.sim_bracket(pos, ff, strength, np.full(T, 68.0), 68.0, {"s": 1.0, "s0": 10.0, "hca": 3.0}, rng)
    reach = res["reach"] / 3000
    assert reach[:, 6].sum() == pytest.approx(1.0)
    assert reach[:, 1].sum() == pytest.approx(32.0)
    assert reach[0, 0] == 1.0 and reach[0, 6] > reach[30, 6]
    assert reach[60, 0] + reach[61, 0] == pytest.approx(1.0)


def test_conference_bracket_order():
    assert SM._bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert sorted(SM._bracket_order(16)) == list(range(1, 17))


def test_season_sim_preseason(level):
    st8 = M.level_state("mbb", [2025, 2026, 2027], use_cache=False, log=False)
    pre = {s: N.pretourney(st8, s) for s in (2025, 2026)}
    rows = N.selection_rows(st8, pre)
    selm = N.fit_on(rows, list(rows))
    f = M.current_fit(st8, 2027)
    r = SM.simulate(st8, 2027, f, n=400, sel_model=selm)
    assert r["p_ncaa"].sum() == pytest.approx(68.0)
    assert r["p_auto"].sum() == pytest.approx(8.0)
    assert r["reach"][:, 6].sum() == pytest.approx(1.0)
    best = int(np.argmax(f["net"][:-1]))
    assert r["p_ncaa"][best] > 0.8
    tb = N.tourney_backtest(st8, pre, n=500)
    assert tb["summary"]["n_seasons"] == 2 and tb["summary"]["game_ll"] > 0


def test_clean_odds_drops_price_in_line_fields():
    bad = D.clean_odds("mbb", {"spread_home": -110.0, "total": -110.0, "ml_home": -110, "ml_away": -110,
                               "has_close_block": True, "provider": "ESPN BET"})
    assert bad["spread"] is None and bad["total"] is None and bad["ml_home"] is None
    ok = D.clean_odds("mbb", {"spread_home": -4.5, "total": 141.5, "ml_home": -190, "ml_away": 160, "has_close_block": True})
    assert ok["spread"] == -4.5 and ok["total"] == 141.5 and ok["ml_home"] == -190 and ok["close_block"]
    assert D.clean_odds("wbb", {"spread_home": 3.0, "total": 40.0})["total"] is None
    assert D.clean_odds("mbb", None)["spread"] is None
