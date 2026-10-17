"""Builder B models: config, ratings, game model, season simulation, Elo, backtest (synthetic data, no network)."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pytest
from scipy.stats import norm

from oddsmarkets.basketball.models import backtest as BT
from oddsmarkets.basketball.models import config as C
from oddsmarkets.basketball.models import elo as E
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models import season_sim as SS
from oddsmarkets.basketball.models.synthetic import make_store


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDWOOD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path / "data"))
    GM.set_params("nba", None)
    GM.set_params("wnba", None)
    yield
    GM.set_params("nba", None)
    GM.set_params("wnba", None)


@pytest.fixture(scope="module")
def nba_full():
    return make_store("nba", 2027, seed=1)


# ── config ───────────────────────────────────────────────────────────────────

def test_config_every_season_builds():
    for lg in ("nba", "wnba"):
        for s in range(1990, 2031):
            f = C.fmt(lg, s)
            assert f.n_teams >= 8 and f.games >= 22
            json.dumps(f.as_dict())
    assert C.fmt("nba", "junk").season == 2027


def test_config_known_formats():
    f = C.fmt("nba", 2027)
    assert (f.n_teams, f.games, f.playin, f.direct, f.series) == (30, 82, True, 6, (7, 7, 7, 7))
    assert f.patterns[0] == "HHAAHAH" and f.lottery_draws == 4 and f.lottery[0] == 140
    assert C.fmt("nba", 2004).n_teams == 29 and C.fmt("nba", 2005).n_teams == 30
    assert C.fmt("nba", 1999).games == 50 and C.fmt("nba", 2012).games == 66
    assert not C.fmt("nba", 2020).playin and C.fmt("nba", 2021).playin
    assert C.fmt("nba", 2002).series[0] == 5 and C.fmt("nba", 2013).patterns[-1] == C.PATTERN_232
    w = C.fmt("wnba", 2026)
    assert (w.n_teams, w.games, w.seeding, w.playoff_teams, w.series) == (15, 44, "league", 8, (3, 5, 7))
    assert w.lottery is None and w.verified
    assert C.canonical_alignment("nba", "UTAH") == ("West", "Northwest")
    assert C.norm_conf("Eastern Conference") == "East"


def test_lottery_matrix():
    M = SS.lottery_matrix(tuple(C.LOTTERY_2019), 4)
    assert np.allclose(M.sum(0), 1) and np.allclose(M.sum(1), 1)
    assert np.allclose(M[:, 0], np.array(C.LOTTERY_2019) / 1000)
    assert M[0, 5:].sum() == pytest.approx(0)            # worst team falls at most to 5th
    assert M[0, 4] > 0 and M[13, 13] > 0.9


def test_bracket_slots():
    assert SS.bracket_slots(8) == [1, 8, 4, 5, 3, 6, 2, 7]
    assert SS.bracket_slots(4) == [1, 4, 2, 3]


# ── ratings ──────────────────────────────────────────────────────────────────

def test_ratings_recover_planted(nba_full):
    st, truth = nba_full
    fit = R.fit_ratings(st["games"], league="nba", half_life_days=1e6, ridge=1.0)
    ids = list(fit["teams"])
    tn = np.array([truth["teams"][t]["net"] for t in ids])
    fn = np.array([fit["teams"][t]["net"] for t in ids])
    assert np.corrcoef(tn, fn)[0, 1] > 0.9
    assert np.sqrt(np.mean((tn - fn) ** 2)) < 2.0
    assert abs(fit["hca"] - truth["hca"]) < 1.0
    se = np.mean([v["se_net"] for v in fit["teams"].values()])
    assert 0.8 < se < 2.0
    tp = np.array([truth["teams"][t]["pace"] for t in ids])
    fp = np.array([fit["teams"][t]["pace"] for t in ids])
    assert np.sqrt(np.mean((tp - fp) ** 2)) < 1.0
    od = np.array([fit["teams"][t]["off"] - fit["league_ortg"] for t in ids])
    to = np.array([truth["teams"][t]["off"] - truth["league_ortg"] for t in ids])
    assert np.corrcoef(od, to)[0, 1] > 0.85
    assert all(v["games"] == 82 for v in fit["teams"].values())


def test_ratings_prior_and_shrinkage(nba_full):
    st, truth = nba_full
    rows = [g for g in st["games"].values()]
    early = sorted(rows, key=lambda g: g["date"])[:60]
    prior = {"teams": {t: {"off": v["off"], "def": v["def"], "net": v["net"], "pace": v["pace"], "se_net": 2.0}
                       for t, v in truth["teams"].items()}, "league_ortg": 114.0, "league_pace": 99.0}
    with_p = R.fit_ratings(early, league="nba", prior=prior, teams=list(st["teams"]))
    without = R.fit_ratings(early, league="nba", teams=list(st["teams"]))
    tn = {t: v["net"] for t, v in truth["teams"].items()}
    err_p = np.mean([(with_p["teams"][t]["net"] - tn[t]) ** 2 for t in tn])
    err_n = np.mean([(without["teams"][t]["net"] - tn[t]) ** 2 for t in tn])
    assert err_p < err_n
    # no games at all: the prior comes straight through
    none = R.fit_ratings({}, league="nba", prior=prior)
    assert none["teams"] and all(abs(none["teams"][t]["net"] - tn[t]) < 1e-9 for t in tn)


def test_rating_paths(nba_full):
    st, truth = nba_full
    paths = R.rating_paths(st["games"], league="nba")
    assert set(paths) == set(st["teams"])
    tn = np.array([truth["teams"][t]["net"] for t in paths])
    last = np.array([paths[t][-1]["net"] for t in paths])
    assert np.corrcoef(tn, last)[0, 1] > 0.85
    for p in paths.values():
        assert len(p) == 82 and p[-1]["se"] < p[0]["se"]
        assert all(math.isfinite(x["net"]) for x in p)


def test_preseason_prior():
    last = {"teams": {"a": {"off": 118, "def": 108, "net": 10.0, "pace": 101, "games": 82},
                      "b": {"off": 110, "def": 116, "net": -6.0, "pace": 97, "games": 82}},
            "league_ortg": 114.0, "league_pace": 99.0, "hca": 2.5}
    p = R.preseason_prior("nba", 2027, last=last, coef={"b": 0.6, "se": 4.0, "b_pace": 0.5}, teams=["a", "b", "c"])
    assert p["teams"]["a"]["net"] == pytest.approx(6.0)
    assert p["teams"]["b"]["net"] == pytest.approx(-3.6)
    assert p["teams"]["c"]["net"] == R.EXPANSION_NET                  # new team
    assert p["teams"]["a"]["pace"] == pytest.approx(100.0)
    q = R.preseason_prior("nba", 2027, last=last, coef={"b": 0.6, "se": 4.0}, teams=["a", "b"],
                          roster_impact={"a": -2.0, "b": 2.0}, blend=0.5)
    assert q["teams"]["a"]["net"] < p["teams"]["a"]["net"] and q["teams"]["b"]["net"] > p["teams"]["b"]["net"]
    assert q["teams"]["a"]["off"] - q["teams"]["a"]["def"] == pytest.approx(q["teams"]["a"]["net"])


def test_roster_prior_impact_follows_summer_moves():
    """Today's rosters (meta.rosters) decide where last season's players count: a star moving from a to b
    moves the roster impact with him; players without last-season minutes count at replacement."""
    imp = {"ok": True, "players": {
        "star": {"t": 6.0, "proj": {"min": 36.0, "hpm_next": 6.0}},
        "x1": {"t": 0.0, "proj": {"min": 30.0, "hpm_next": 0.0}}, "x2": {"t": 0.0, "proj": {"min": 30.0, "hpm_next": 0.0}},
        "y1": {"t": 0.0, "proj": {"min": 30.0, "hpm_next": 0.0}}, "y2": {"t": 0.0, "proj": {"min": 30.0, "hpm_next": 0.0}}}}
    before = {"meta": {"rosters": {"a": ["star", "x1"], "b": ["y1", "y2", "rookie"]}}}
    after = {"meta": {"rosters": {"a": ["x1"], "b": ["star", "y1", "y2", "rookie"]}}}
    r0 = R.roster_prior_impact("nba", 2027, store=before, impact=imp)
    r1 = R.roster_prior_impact("nba", 2027, store=after, impact=imp)
    assert r0["a"] > r0["b"] and r1["b"] > r1["a"]
    assert r1["b"] - r0["b"] == pytest.approx((6.0 - (-2.0)) * 36 / 48)     # his minutes displace replacement (-2)
    assert R.roster_prior_impact("nba", 2027, store={"meta": {}}, impact=imp) is None
    # minutes beyond five players' 240 go to the deepest players last, not pro rata
    m = R._allocate_minutes({"p1": 36, "p2": 34, "p3": 34, "p4": 34, "p5": 34, "p6": 34, "p7": 30, "p8": 20}, 240.0)
    assert m["p1"] == 36 and m["p7"] == 30 and m["p8"] == 4 and sum(m.values()) == pytest.approx(240.0)


# ── game model ───────────────────────────────────────────────────────────────

def test_game_model_recovers_context():
    rows = []
    for s in range(3):
        st, truth = make_store("nba", 2020 + s, seed=10 + s, b2b=-2.5, hca=3.0, altitude=2.0)
        prior = {"teams": {t: {**v, "se_net": 2.0} for t, v in truth["teams"].items()}, "league_ortg": 114.0, "league_pace": 99.0}
        rows += GM.walk_forward("nba", st, prior)
    p = GM.fit_from_rows(rows, "nba")
    assert p["fitted"] and p["n"] == 3690
    assert abs(p["hca"] - 3.0 * 0.99) < 0.7
    assert abs(p["b2b"] - (-2.5)) < 1.0
    assert 9.0 < p["sigma"] < 13.0
    assert abs(p["sigma_market"] - p["sigma"]) < 2.5


def test_predict_shape_and_terms(nba_full):
    st, truth = nba_full
    rt = R.fit_ratings(st["games"], league="nba")
    ctx = GM.context("nba", store=st, ratings=rt)
    a, b = list(st["teams"])[:2]
    out = GM.predict(a, b, "2027-01-15", ctx)
    for k in ("p_home", "margin", "sd", "total", "spread_fair", "detail"):
        assert k in out
    assert out["spread_fair"] == pytest.approx(-out["margin"])
    assert out["p_home"] == pytest.approx(norm.cdf(out["margin"] / out["sd"]))
    assert 180 < out["total"] < 260
    swap = GM.predict(b, a, "2027-01-15", {**ctx, "neutral": True})
    neutral = GM.predict(a, b, "2027-01-15", {**ctx, "neutral": True})
    assert neutral["detail"]["hca"] == 0 and swap["detail"]["rating"] == pytest.approx(-neutral["detail"]["rating"])
    inj = GM.predict(a, b, "2027-01-15", {**ctx, "injuries": {a: [{"impact": 6.0, "minutes": 36}]}})
    assert inj["margin"] < out["margin"] and inj["detail"]["injury"] < 0
    assert GM.spread_to_p(0.0, "nba") == pytest.approx(0.5)
    assert GM.spread_to_p(-5.5, "nba") > 0.6 > GM.spread_to_p(5.5, "nba") < 0.4
    assert GM.spread_to_p(None) is None and GM.spread_to_p("x") is None


def test_altitude_and_rest_features():
    st, _ = make_store("nba", 2027, seed=2)
    sched = GM.Schedule(st["games"], st["teams"], "nba")
    den = next(t for t, v in st["teams"].items() if v["abbr"] == "DEN")
    other = next(t for t, v in st["teams"].items() if v["abbr"] == "BOS")
    f = GM.features(den, other, date(2027, 1, 10), sched, False, "nba")
    assert f["altitude"] == 1.0 and f["hca"] == 1.0
    assert GM.features(other, den, date(2027, 1, 10), sched, False, "nba")["altitude"] == 0.0
    # a team's second night of a back-to-back
    days = sched.by_team[other]
    for (d0, _, _), (d1, host, _) in zip(days, days[1:]):
        if (d1 - d0).days == 1:
            tf = sched.team_features(other, d1, host)
            assert tf["b2b"] == 1 and tf["rest"] == 0
            break


# ── tiebreakers ──────────────────────────────────────────────────────────────

def _ranker(league, W, L, H, conf, div, CW=None, CL=None, DW=None, DL=None, PD=None, HPD=None):
    T = len(W)
    z = np.zeros(T, int)
    f = C.fmt(league, 2027 if league == "nba" else 2026)
    arr = lambda x: np.asarray(x if x is not None else z)[None]  # noqa: E731
    return SS.Ranker(f, np.asarray(conf), np.asarray(div), arr(W), arr(L), np.asarray(H, np.int16)[None],
                     arr(CW), arr(CL), arr(DW), arr(DL), np.asarray(PD if PD is not None else np.zeros(T), float)[None],
                     None if HPD is None else np.asarray(HPD, np.float32)[None], np.random.default_rng(0))


def test_two_team_tie_head_to_head():
    # teams 0 and 1 tied at 50-32; 1 won the season series 3-1
    H = np.zeros((3, 3), int)
    H[1, 0], H[0, 1] = 3, 1
    rk = _ranker("nba", [50, 50, 40], [32, 32, 42], H, [0, 0, 0], [0, 1, 1])
    assert list(rk.rank([0, 1, 2])[0]) == [1, 0, 2]


def test_two_team_tie_division_winner_then_conference_record():
    # 0 and 1 split 2-2; 0 wins its division (team 3 below it), 1 does not (team 2 leads its division)
    H = np.zeros((4, 4), int)
    H[0, 1] = H[1, 0] = 2
    W, L = [50, 50, 55, 30], [32, 32, 27, 52]
    rk = _ranker("nba", W, L, H, [0, 0, 0, 0], [0, 1, 1, 0])
    assert list(rk.rank([0, 1, 2, 3])[0]) == [2, 0, 1, 3]
    # same division, split series, neither leads it: division record decides, then conference record
    rk = _ranker("nba", [50, 50, 55], [32, 32, 27], np.array([[0, 2, 0], [2, 0, 0], [0, 0, 0]]), [0, 0, 0], [0, 0, 0],
                 DW=[8, 10, 12], DL=[8, 6, 4])
    assert list(rk.rank([0, 1, 2])[0]) == [2, 1, 0]
    rk = _ranker("nba", [50, 50], [32, 32], np.array([[0, 2], [2, 0]]), [0, 0], [0, 1], CW=[30, 33], CL=[22, 19])
    # each leads its own division, so division-winner does not separate them; conference record does
    assert list(rk.rank([0, 1])[0]) == [1, 0]


def test_three_team_tie_multi_rules_restart():
    # 0, 1, 2 tied. 2 is the only division winner (3 leads the other division) -> first. Then 0 v 1
    # restart with the two-team rules: 0 beat 1 in their series although 1 has the better record
    # among all three.
    H = np.zeros((4, 4), int)
    H[0, 1], H[1, 0] = 3, 1
    H[1, 2], H[2, 1] = 4, 0
    H[2, 0], H[0, 2] = 2, 2
    W, L = [48, 48, 48, 50], [34, 34, 34, 32]
    rk = _ranker("nba", W, L, H, [0, 0, 0, 0], [0, 0, 1, 0])
    assert list(rk.rank([0, 1, 2, 3])[0]) == [3, 2, 0, 1]
    # no division winner among them (3 leads the division): head-to-head among all three decides
    W2, L2 = [48, 48, 48, 60], [34, 34, 34, 22]
    rk = _ranker("nba", W2, L2, H, [0, 0, 0, 0], [0, 0, 0, 0])
    # h2h pct: 0: 5-3 (.625), 1: 5-3 (.625), 2: 2-6 (.25) -> {0,1} then 2; 0 v 1 restart: 0 won 3-1
    assert list(rk.rank([0, 1, 2, 3])[0]) == [3, 0, 1, 2]


def test_two_team_vectorised_matches_generic():
    rng = np.random.default_rng(5)
    S, T = 400, 6
    W = rng.integers(38, 42, (S, T))
    L = 82 - W
    H = rng.integers(0, 3, (S, T, T)).astype(np.int16)
    for s in range(S):
        np.fill_diagonal(H[s], 0)
    CW = rng.integers(20, 30, (S, T)); CL = 52 - CW
    DW = rng.integers(5, 11, (S, T)); DL = 16 - DW
    PD = rng.normal(0, 50, (S, T)).round()
    f = C.fmt("nba", 2027)
    conf, div = np.zeros(T, int), np.array([0, 0, 0, 1, 1, 1])
    rk = SS.Ranker(f, conf, div, W, L, H, CW, CL, DW, DL, PD, None, np.random.default_rng(1))
    order = rk.rank(list(range(T)))
    for s in range(S):
        o = list(order[s])
        for a, b in zip(o, o[1:]):
            assert W[s, a] >= W[s, b]
            if W[s, a] == W[s, b] and sum(W[s] == W[s, a]) == 2:
                ok = rk.resolve_one(s, [a, b])
                ok2 = rk.resolve_one(s, [b, a])
                # deterministic unless it came down to the coin
                if ok == ok2:
                    assert ok == [a, b]


def test_wnba_vs_500_tiebreak():
    # 0 and 1 tied, split head-to-head; 0 has the better record against .500+ teams (2 and 3)
    H = np.zeros((5, 5), int)
    H[0, 1] = H[1, 0] = 2
    H[0, 2], H[2, 0] = 3, 1
    H[1, 2], H[2, 1] = 1, 3
    W, L = [25, 25, 30, 23, 10], [19, 19, 14, 21, 34]
    rk = _ranker("wnba", W, L, H, [0, 0, 1, 1, 1], [0, 0, 1, 1, 1], HPD=np.zeros((5, 5)))
    assert list(rk.rank([0, 1, 2, 3, 4])[0]) == [2, 0, 1, 3, 4]


# ── series, play-in, bracket ─────────────────────────────────────────────────

def test_series_continues_from_score():
    S = 200_000
    rng = np.random.default_rng(0)
    A, B = np.zeros(S, int), np.ones(S, int)
    x = np.zeros((S, 2))
    SW = np.array([[0, 3], [0, 0]])                       # A leads 3-0 (SW[a, b] = wins of a over b)
    win, games = SS._series(A, B, 7, "HHAAHAH", x, 1.0, 0.0, 10.0, SW, rng)
    assert np.mean(win == 0) == pytest.approx(1 - 0.5 ** 4, abs=0.005)
    assert games.min() == 4 and games.max() == 7
    SW = np.array([[0, 4], [2, 0]])
    win, games = SS._series(A, B, 7, "HHAAHAH", x, 1.0, 0.0, 10.0, SW, rng)
    assert (win == 0).all() and (games == 6).all()
    # home-court pattern: a best-of-3 between equal teams with home edge h
    SW = np.zeros((2, 2), int)
    win, _ = SS._series(A, B, 3, "HAH", x, 1.0, 3.0, 10.0, SW, rng)
    pH, pA = norm.cdf(0.3), norm.cdf(-0.3)
    exact = pH * pA + pH * (1 - pA) * pH + (1 - pH) * pA * pH
    assert np.mean(win == 0) == pytest.approx(exact, abs=0.005)


def _complete_season(league="nba", season=2027, seed=4):
    st, truth = make_store(league, season, seed=seed, played_frac=1.0)
    return st, truth


def test_playin_and_bracket_on_completed_season():
    st, truth = _complete_season()
    rt = {"teams": {t: {"net": v["net"], "se_net": 0.0, "off": v["off"], "def": v["def"], "pace": v["pace"]}
                    for t, v in truth["teams"].items()}, "league_ortg": 114.0, "league_pace": 99.0}
    out = SS.simulate("nba", 2027, n=4000, seed=0, state={"store": st, "ratings": rt, "drift": 0.0})
    assert out["ok"] and out["remaining_games"] == 0 and "regular season complete: seeds fixed" in out["notes"]
    for conf in ("East", "West"):
        tm = {t: v for t, v in out["teams"].items() if v["conference"] == conf}
        by_rank = sorted(tm.items(), key=lambda kv: kv[1]["current"]["rank"])
        for i, (t, v) in enumerate(by_rank):
            if i < 6:
                assert v["p_playoffs"] == 1.0 and v["p_top6"] == 1.0 and v["p_playin"] == 0.0
                assert v["seed_dist"][i] == 1.0
            elif i < 10:
                assert v["p_playin"] == 1.0 and 0.0 < v["p_playoffs"] < 1.0
                assert v["p_lottery_pick"] is not None
            else:
                assert v["p_playoffs"] == 0.0 and v["p_title"] == 0.0
        # play-in: seeds 9 and 10 can reach the playoffs only through two wins
        s7, s8, s9, s10 = (by_rank[k][1]["p_playoffs"] for k in range(6, 10))
        assert s7 > s9 and s8 > s10
        assert sum(v["p_playoffs"] for _, v in by_rank) == pytest.approx(8.0)
        assert sum(v["p_conf"] for _, v in by_rank) == pytest.approx(1.0)
        assert by_rank[0][1]["clinched"]["top_seed"] and by_rank[-1][1]["eliminated"]["postseason"]
    tot = {k: sum(v[k] for v in out["teams"].values()) for k in ("p_title", "p_playoffs", "p_playin")}
    assert tot == pytest.approx({"p_title": 1.0, "p_playoffs": 16.0, "p_playin": 8.0})
    lp = np.array([v["p_lottery_pick"] for v in out["teams"].values()])
    assert np.allclose(lp.sum(0), 1.0)
    json.dumps(out)


def test_forced_playin_and_series_results():
    st, truth = _complete_season(seed=6)
    rt = {"teams": {t: {"net": v["net"], "se_net": 0.0, "off": v["off"], "def": v["def"], "pace": v["pace"]}
                    for t, v in truth["teams"].items()}, "league_ortg": 114.0, "league_pace": 99.0}
    pre = SS.simulate("nba", 2027, n=500, seed=0, state={"store": st, "ratings": rt, "drift": 0.0})
    east = sorted((kv for kv in pre["teams"].items() if kv[1]["conference"] == "East"), key=lambda kv: kv[1]["current"]["rank"])
    ids = [t for t, _ in east]
    s7, s8, s9, s10 = ids[6:10]
    tip = "2027-04-15T23:30Z"
    games = dict(st["games"])

    def add(gid, h, a, hs, as_, stype):
        games[gid] = {"id": gid, "date": tip, "status": "post", "stype": stype, "neutral": False, "home": h, "away": a,
                      "hs": hs, "as": as_, "periods": 4, "box": {}, "odds": None}
    add("p1", s7, s8, 90, 100, "playin")       # 8 beats 7 -> 8 is the 7th seed
    add("p2", s9, s10, 90, 100, "playin")      # 10 beats 9
    add("p3", s7, s10, 90, 100, "playin")      # 10 beats 7 -> 10 is the 8th seed
    # the 1 seed leads the 10 seed 3-0 in round one... and has already won 4
    for k in range(4):
        add(f"r{k}", ids[0], s10, 100, 90, "post")
    st2 = {**st, "games": games}
    out = SS.simulate("nba", 2027, n=2000, seed=0, state={"store": st2, "ratings": rt, "drift": 0.0})
    tm = out["teams"]
    assert tm[s8]["p_playoffs"] == 1.0 and tm[s10]["p_playoffs"] == 1.0
    assert tm[s7]["p_playoffs"] == 0.0 and tm[s9]["p_playoffs"] == 0.0
    assert tm[s10]["p_reach"]["semis"] == 0.0 and tm[ids[0]]["p_reach"]["semis"] == 1.0


def test_sim_reproduces_planted_probabilities():
    # 4-team WNBA-format league; every game played except a handful; no rating uncertainty
    st, truth = make_store("wnba", 2026, seed=7, n_teams=4, games=12, played_frac=1.0)
    games = st["games"]
    left = sorted(games, key=lambda g: games[g]["date"])[-6:]
    for g in left:
        games[g].update({"status": "pre", "hs": None, "as": None})
    rt = {"teams": {t: {"net": v["net"], "se_net": 0.0, "off": v["off"], "def": v["def"], "pace": v["pace"]}
                    for t, v in truth["teams"].items()}, "league_ortg": 104.0, "league_pace": 80.0}
    prm = {"sigma": 10.0, "hca": 2.0, "b2b": 0.0, "rest": 0.0, "travel_1000km": 0.0, "tz": 0.0, "altitude": 0.0}
    out = SS.simulate("wnba", 2026, n=60000, seed=3, state={"store": st, "ratings": rt, "params": prm, "drift": 0.0})
    sd_n = out["sigma_noise"]
    assert sd_n == pytest.approx(10.0)
    # expected wins = wins so far + sum of each remaining game's planted probability
    W0 = {t: v["current"]["w"] for t, v in out["teams"].items()}
    exp = dict(W0)
    for g in left:
        h, a = games[g]["home"], games[g]["away"]
        th, ta = truth["teams"][h], truth["teams"][a]
        pace = th["pace"] + ta["pace"] - 80.0
        mu = (th["net"] - ta["net"]) * pace / 100 + 2.0
        p = norm.cdf(mu / sd_n)
        exp[h] += p
        exp[a] += 1 - p
    for t, v in out["teams"].items():
        assert v["exp_w"] == pytest.approx(exp[t], abs=0.03)
        assert sum(v["seed_dist"]) == pytest.approx(1.0)
        assert sum(v["win_dist"]) == pytest.approx(1.0, abs=1e-3)
    assert out["bracket"]["rounds"] == ["semis", "finals"] and out["bracket"]["series"] == [5, 7]
    assert sum(v["p_title"] for v in out["teams"].values()) == pytest.approx(1.0)
    assert sum(v["p_conf"] for v in out["teams"].values()) == pytest.approx(2.0)
    # conditional odds on the next game bracket the unconditional ones (interventional, reweighted:
    # the mixture matches the unconditional odds up to the rating-draw covariance)
    for v in out["teams"].values():
        nx = v["next"]
        if nx and 0.02 < nx["p_win"] < 0.98:
            assert nx["if_win"]["p_title"] + 1e-9 >= nx["if_loss"]["p_title"] - 0.02
            mix = nx["p_win"] * nx["if_win"]["p_title"] + (1 - nx["p_win"]) * nx["if_loss"]["p_title"]
            assert mix == pytest.approx(v["p_title"], abs=0.02)


def test_next_game_leverage_is_a_few_points():
    """Opening night: one game of 82 moves a team's playoff odds by a few points, not the ~20 that raw
    conditioning gave (selection on the sampled team rating)."""
    st, truth = make_store("nba", 2027, seed=5, played_frac=0.0)
    rt = R.fit_ratings({}, league="nba", prior={"teams": {t: {**v, "se_net": 3.5} for t, v in truth["teams"].items()},
                                                "league_ortg": 114.0, "league_pace": 99.0})
    out = SS.simulate("nba", 2027, n=8000, seed=1, state={"store": st, "ratings": rt})
    diffs = []
    for v in out["teams"].values():
        nx = v["next"]
        assert nx is not None
        d = nx["if_win"]["p_playoffs"] - nx["if_loss"]["p_playoffs"]
        diffs.append(d)
        assert -0.03 < d < 0.12
    assert 0.0 < float(np.mean(diffs)) < 0.07


def test_sim_timing_and_shape_preseason():
    st, truth = make_store("nba", 2027, seed=3, played_frac=0.0)
    rt = R.fit_ratings({}, league="nba", prior={"teams": {t: {**v, "se_net": 3.0} for t, v in truth["teams"].items()},
                                                "league_ortg": 114.0, "league_pace": 99.0})
    out = SS.simulate("nba", 2027, n=20000, seed=0, state={"store": st, "ratings": rt})
    assert out["runtime_s"] < 30
    tm = out["teams"]
    assert len(tm) == 30 and out["remaining_games"] == 1230
    nets = np.array([truth["teams"][t]["net"] for t in tm])
    pt = np.array([tm[t]["p_title"] for t in tm])
    assert np.corrcoef(nets, pt)[0, 1] > 0.6
    ew = np.array([tm[t]["exp_w"] for t in tm])
    assert ew.sum() == pytest.approx(30 * 41, abs=1.0)
    assert all(v["w_p05"] <= v["exp_w"] <= v["w_p95"] for v in tm.values())
    assert all(v["magic"]["top6"] == 83 for v in tm.values())


def test_cup_tbd_games_are_filled():
    st, truth = make_store("nba", 2027, seed=8, played_frac=0.3)
    # drop two unplayed games of one team (the Cup's TBD games) and one of a conference rival
    pre = sorted((g for g in st["games"].values() if g["status"] == "pre"), key=lambda g: g["date"])
    t0 = pre[0]["home"]
    dropped = [g["id"] for g in pre if t0 in (g["home"], g["away"])][:2]
    for gid in dropped:
        del st["games"][gid]
    rt = R.fit_ratings(st["games"], league="nba")
    out = SS.simulate("nba", 2027, n=500, seed=0, state={"store": st, "ratings": rt})
    assert out["teams"][t0]["exp_w"] + out["teams"][t0]["exp_l"] == pytest.approx(82)
    assert any("filled" in n for n in out["notes"])


# ── magic numbers ────────────────────────────────────────────────────────────

def test_magic_numbers_hand_made():
    W = np.array([50, 48, 38, 47])
    Rm = np.array([2, 4, 10, 3])
    gid = np.zeros(4, int)
    out = SS.magic_numbers(W, Rm, {}, {"first": ("g", 1), "top2": ("g", 2)}, {"g": gid})
    # team 0 for first: rivals' M = 48+4-50+1=3, 38+10-50+1=-1, 47+3-50+1=1 -> largest = 3
    assert out[0]["magic"]["first"] == 3 and not out[0]["clinched"]["first"]
    # team 0 for top 2: second largest = 1
    assert out[0]["magic"]["top2"] == 1
    # team 2: its best is 48; 0 already has 50 -> eliminated from first; vs top2: 50, 48 both > 48? 48 is not > 48
    assert out[2]["eliminated"]["first"] and not out[2]["eliminated"]["top2"]
    assert out[2]["tragic"]["top2"] == 1
    W2 = np.array([60, 40, 39, 30])
    Rm2 = np.array([1, 1, 1, 1])
    o2 = SS.magic_numbers(W2, Rm2, {}, {"first": ("g", 1)}, {"g": gid})
    assert o2[0]["clinched"]["first"] and o2[0]["magic"]["first"] == 0
    assert o2[3]["eliminated"]["first"] and o2[3]["tragic"]["first"] == 0


# ── Elo ──────────────────────────────────────────────────────────────────────

def test_elo_sanity():
    stores = {}
    truths = {}
    for k, s in enumerate((2025, 2026, 2027)):
        stores[s], truths[s] = make_store("nba", s, seed=20 + k)
    h = E.history("nba", stores=stores)
    assert len(h["games"]) == 3 * 1230
    cur = h["current"]
    assert np.mean(list(cur.values())) == pytest.approx(1505, abs=5)
    nets = np.array([truths[2027]["teams"][t]["net"] for t in cur])
    assert np.corrcoef(nets, np.array(list(cur.values())))[0, 1] > 0.7
    # zero-sum updates, pregame probability uses home advantage
    g = h["games"][0]
    assert g[5] == g[6] == 1505.0 and g[7] == pytest.approx(E.expected(1505, 1505, 100), abs=1e-5)
    assert (g[8] - g[5]) == pytest.approx(-(g[9] - g[6]), abs=0.02)
    assert E.expected(1600, 1500, 0) == pytest.approx(1 - E.expected(1500, 1600, 0))
    assert E.mov_mult(10, 0) > E.mov_mult(1, 0) and E.mov_mult(10, 200) < E.mov_mult(10, 0)
    rb = E.ratings_before(h, "2026-01-01")
    assert rb and all(1200 < v < 1800 for v in rb.values())
    pr = E.predict(h, list(cur)[0], list(cur)[1])
    assert 0 < pr["p_home"] < 1
    ll = -np.mean([math.log(g[7] if (stores[g[2]]["games"][g[0]]["hs"] > stores[g[2]]["games"][g[0]]["as"]) else 1 - g[7])
                   for g in h["games"][1230:]])
    assert ll < 0.69


# ── backtest ─────────────────────────────────────────────────────────────────

def _with_playoffs(st, champion, runner_up, others):
    tip = "2027-05-20T23:30Z"
    games = st["games"]
    for k, t in enumerate(others):
        games[f"po{k}"] = {"id": f"po{k}", "date": "2027-04-25T23:30Z", "status": "post", "stype": "post", "neutral": False,
                           "home": champion, "away": t, "hs": 100, "as": 90, "periods": 4, "box": {}, "odds": None}
    games["final"] = {"id": "final", "date": tip, "status": "post", "stype": "post", "neutral": False, "home": runner_up,
                      "away": champion, "hs": 90, "as": 101, "periods": 4, "box": {}, "odds": None}
    return st


def test_backtest_runs_and_ranks_models():
    stores = {}
    for k, s in enumerate((2025, 2026, 2027)):
        st, truth = make_store("nba", s, seed=30 + k, odds_noise=0.5)
        nets = sorted(truth["teams"], key=lambda t: -truth["teams"][t]["net"])
        stores[s] = _with_playoffs(st, nets[0], nets[1], nets[2:16])
    bt = BT.backtest("nba", seasons=[2026, 2027], stores=stores, write=False, season_sims=300, checkpoints=(0.0, 0.5))
    m = bt["metrics"]
    assert set(m) >= {"model", "model_ratings_only", "elo", "market"}
    assert m["model"]["n"] == 2 * 1230 + 2 * 15
    assert m["market"]["logloss"] < m["model"]["logloss"] < 0.69
    assert m["model"]["logloss"] < m["elo"]["logloss"] + 0.02
    assert bt["margin_rmse"]["market"] < bt["margin_rmse"]["model"]
    assert bt["season_sim"]["playoffs"]["n"] == 2 * 2 * 30 and bt["season_sim"]["title"]["n"] == 120
    assert bt["season_sim"]["playoffs"]["logloss"] < 0.69
    rows = BT.summary_table(bt)
    assert any(r["model"] == "market" for r in rows)
    assert bt["params_by_season"]["2027"]["fitted"]
    json.dumps(bt, default=str)


def test_postseason_started_drops_stale_games_and_placeholders():
    st, truth = make_store("wnba", 2026, seed=9, played_frac=1.0)
    ids = list(st["teams"])
    games = st["games"]
    # a stale postponed regular-season game, a TBD placeholder playoff game and one played playoff game
    games["pp"] = {"id": "pp", "date": "2026-07-01T23:00Z", "status": "postponed", "stype": "reg", "neutral": False,
                   "home": ids[0], "away": ids[1], "hs": None, "as": None, "periods": 4, "box": {}, "odds": None}
    st["teams"]["tbd"] = {"name": "TBD", "abbr": "TBD", "location": "TBD", "conference": None, "division": None}
    games["tbd1"] = {"id": "tbd1", "date": "2026-10-10T23:00Z", "status": "pre", "stype": "post", "neutral": False,
                     "home": "tbd", "away": "tbd", "hs": None, "as": None, "periods": 4, "box": {}, "odds": None}
    rt = R.fit_ratings(games, league="wnba")
    pre = SS.simulate("wnba", 2026, n=300, seed=0, state={"store": st, "ratings": rt})
    order = sorted(pre["teams"], key=lambda t: pre["teams"][t]["current"]["rank"])
    games["po1"] = {"id": "po1", "date": "2026-09-27T23:00Z", "status": "post", "stype": "post", "neutral": False,
                    "home": order[0], "away": order[7], "hs": 80, "as": 90, "periods": 4, "box": {}, "odds": None}
    out = SS.simulate("wnba", 2026, n=300, seed=0, state={"store": st, "ratings": rt})
    assert out["remaining_games"] == 0 and "tbd" not in out["teams"]
    assert any("ignored" in n for n in out["notes"]) and "regular season complete: seeds fixed" in out["notes"]
    assert R.league_teams(st) == sorted(ids)


def test_impute_possessions_for_games_without_box():
    st, truth = make_store("nba", 2027, seed=1)
    for k, g in enumerate(st["games"].values()):
        if k % 3 == 0:
            g["box"] = {}
    rows = R.impute_poss(__import__("oddsmarkets.basketball.models._games", fromlist=["x"]).finished(st["games"], "nba"), "nba")
    assert all(r["poss"] for r in rows) and sum(1 for r in rows if r.get("poss_imputed")) == 410
    fit = R.fit_ratings(st["games"], league="nba", half_life_days=1e6, ridge=1.0)
    assert all(v["games"] == 82 for v in fit["teams"].values())
    tn = np.array([truth["teams"][t]["net"] for t in fit["teams"]])
    fn = np.array([fit["teams"][t]["net"] for t in fit["teams"]])
    assert np.corrcoef(tn, fn)[0, 1] > 0.9
