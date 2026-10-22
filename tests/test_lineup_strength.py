"""
The line-up term (oddsmarkets/football/analytics/lineup_strength.py; docs/MODELS.md 2.6), the pre-match
line-up fetch (sofascore.parse_prematch, fetch_sofascore_leagues.prematch_queue) and the build's use of it
(build_fixtures_json, build_match_markets). Offline: synthetic stores.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.football.analytics import lineup_strength as LS
from oddsmarkets.football.analytics import value as V
from oddsmarkets.football.core.markets import build_match_markets
from oddsmarkets.football.sources import sofascore

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LETTERS = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F"]


def _lineup(team: str, pids: list[int], rating: float | dict = 7.0, xg: float | dict = 0.1) -> dict:
    out = {}
    for pid, letter in zip(pids, LETTERS):
        r = rating.get(pid, 7.0) if isinstance(rating, dict) else rating
        x = xg.get(pid, 0.1) if isinstance(xg, dict) else xg
        out[str(pid)] = {"n": f"P{pid}", "t": team, "p": letter, "s": {"minutesPlayed": 90, "rating": r, "expectedGoals": x}}
    return out


def _store(n_matches: int = 12, star_out_last: bool = True) -> tuple[dict, list[int]]:
    """Club A (ids 100-110, 105 a star) plays club B (200-210) every week; in the last match A's star is replaced by 111."""
    a = list(range(100, 111))
    b = list(range(200, 211))
    matches, lineups = {}, {}
    d0 = date(2026, 1, 3)
    for k in range(n_matches):
        gid = str(1000 + k)
        day = d0 + timedelta(days=7 * k)
        matches[gid] = {"home": "A", "away": "B", "hs": 2, "as": 1, "date": f"{day.isoformat()}T15:00:00Z", "season_id": 1,
                        "home_id": 1, "away_id": 2, "status": "finished"}
        xi_a = a if not (star_out_last and k == n_matches - 1) else [p if p != 105 else 111 for p in a]
        lineups[gid] = {**_lineup("A", xi_a, rating={105: 8.5, 111: 6.2}, xg={105: 0.8, 111: 0.05}), **_lineup("B", b)}
    return {"matches": matches, "lineups": lineups, "meta": {"season_id": 1}}, a


def _rows(store: dict) -> V.Rows:
    col = V.ValueCollector()
    col.add_store("premier-league", store)
    return col.finish()


def test_weaker_xi_than_usual_has_a_negative_delta_and_the_usual_xi_a_zero_one() -> None:
    store, a = _store()
    R = _rows(store)
    w = LS.ValueWeights(beta=V.default_beta(), scale=1.0, rating_w=0.14)
    idx = LS.PlayerIndex(R, w)
    xis = LS.TeamXIs.from_rows(R)
    last = max(store["matches"], key=lambda g: store["matches"][g]["date"])
    day = date.fromisoformat(store["matches"][last]["date"][:10]).toordinal()
    xi_today = xis.by_match[(R.m_gid.tolist().index(int(last)), 0)]
    s = LS.xi_strength(idx, xis, 1, day, xi_today, n=10)
    assert s is not None and s.delta < -0.1
    assert [r["pid"] for r in s.absent] == [105] and s.absent[0]["share"] == 1.0
    # The usual XI against itself: no news.
    usual = [(p, V.LETTERS.index(l)) for p, l in zip(a, LETTERS)]
    s0 = LS.xi_strength(idx, xis, 1, day, usual, n=10)
    assert abs(s0.delta) < 1e-9
    # Too little history, or not eleven starters: no term.
    first = min(store["matches"], key=lambda g: store["matches"][g]["date"])
    d_first = date.fromisoformat(store["matches"][first]["date"][:10]).toordinal()
    assert LS.xi_strength(idx, xis, 1, d_first + 7, usual, n=10) is None
    assert LS.xi_strength(idx, xis, 1, day, usual[:10], n=10) is None


def test_player_values_use_only_earlier_days() -> None:
    store, _a = _store()
    R = _rows(store)
    idx = LS.PlayerIndex(R, LS.ValueWeights(beta=V.default_beta(), scale=1.0, rating_w=0.14))
    first_day = int(R.day.min())
    assert idx.minutes(105, first_day) == 0.0                     # nothing before the first match
    assert idx.minutes(105, first_day + 1) == 90.0                # the first match counts from the next day
    # An unknown player sits at his letter's mean, the same as anyone without minutes.
    assert idx.value(999, first_day + 30, 3) == pytest.approx(idx.value(998, first_day + 30, 3))


def test_xis_without_substitute_flags_are_not_usual_xis() -> None:
    store, _a = _store()
    g = sorted(store["lineups"])[0]
    extra = _lineup("A", list(range(300, 311)))
    store["lineups"][g].update(extra)                              # 22 "starters" for A
    xis = LS.TeamXIs.from_rows(_rows(store))
    assert all(len(x) == 11 for t in xis.by_team.values() for _d, _m, x in t)


def test_tilt_moves_the_goal_difference_by_about_c_d_and_barely_the_total() -> None:
    from oddsmarkets.football.research import fastdc
    lh, la = np.array([1.5]), np.array([1.1])
    h2, a2 = LS.tilt(lh, la, np.array([0.2]), 1.0)
    assert (h2 - a2)[0] - (lh - la)[0] == pytest.approx(0.2, abs=0.01)
    assert (h2 + a2)[0] == pytest.approx(2.6, abs=0.05)          # the total moves only to second order
    # The matrix form equals refitting the rates for independent Poisson sides.
    M = fastdc.score_matrix(lh, la, 0.0, 12)[0]
    Mt = LS.tilt_matrix(M, 1.5, 1.1, 0.2, 1.0)
    ref = fastdc.score_matrix(h2, a2, 0.0, 12)[0]
    assert np.abs(Mt - ref).max() < 1e-6
    assert LS.tilt_matrix(M, 1.5, 1.1, 0.0, 1.0) is M


def test_parse_prematch_keeps_the_eleven_starters_the_confirmed_flag_and_the_missing() -> None:
    def side(base):
        players = [{"player": {"id": base + i, "name": f"N{i}", "position": l}, "position": l, "shirtNumber": i + 1, "substitute": False}
                   for i, l in enumerate(LETTERS)]
        players += [{"player": {"id": base + 50, "name": "Sub"}, "substitute": True}]
        return {"players": players, "formation": "4-3-3",
                "missingPlayers": [{"player": {"id": base + 90, "name": "Hurt"}, "type": "missing", "reason": 1}]}
    rec = sofascore.parse_prematch({"confirmed": True, "home": side(100), "away": side(200)}, {"home": "A", "away": "B"})
    assert rec["confirmed"] and rec["home"]["team"] == "A" and rec["home"]["f"] == "4-3-3"
    assert len(rec["home"]["xi"]) == 11 and rec["home"]["xi"][0] == [100, "N0", "G", "1"]
    assert rec["away"]["missing"][0][1] == "Hurt"
    short = side(100)
    short["players"] = short["players"][:10]
    assert sofascore.parse_prematch({"confirmed": True, "home": short, "away": side(200)}, {}) is None


def test_prematch_queue_asks_only_for_matches_about_to_start_until_confirmed() -> None:
    import fetch_sofascore_leagues as F
    now = datetime(2026, 10, 24, 13, 0, tzinfo=timezone.utc)

    def m(minutes, status="notstarted"):
        return {"date": (now + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": status}
    store = {"matches": {"1": m(60), "2": m(200), "3": m(30, "inprogress"), "4": m(90), "5": m(-30), "6": m(45)},
             "prematch": {"4": {"confirmed": True}, "6": {"confirmed": False}}}
    assert [g for g, _m in F.prematch_queue(store, now)] == ["6", "1"]


def test_build_applies_the_term_only_to_posted_fixtures_and_markets_compare_the_line_after_it() -> None:
    import build_site_all as B

    class P:
        def __init__(self):
            from oddsmarkets.football.research import fastdc
            M = fastdc.score_matrix(np.array([1.4]), np.array([1.1]), -0.05, 8)[0]
            i, j = np.indices(M.shape)
            self.score_matrix, self.lambda_home, self.lambda_away = M, 1.4, 1.1
            self.home_win, self.draw, self.away_win = float(M[i > j].sum()), float(M[i == j].sum()), float(M[i < j].sum())

    class Model:
        def predict(self, h, a, neutral=False):
            return P()

    store = {"matches": {
        "1": {"home": "A", "away": "B", "date": "2026-10-24T14:00:00Z", "status": "notstarted", "season_id": 1},
        "2": {"home": "C", "away": "D", "date": "2026-10-24T14:00:00Z", "status": "notstarted", "season_id": 1}}}
    term = {"applied": True, "d": -0.3, "c": 0.75, "home": {"delta": -0.3}, "away": {"delta": 0.0}}
    fx = B.build_fixtures_json(store, lambda s: s, Model(), lambda m: True, {}, lineup_terms={"1": term})
    rows = {r["id"]: r for r in fx["matches"]}
    a, b = rows["1"], rows["2"]
    assert a["model"]["lineups"] and a["xi"] is term and a["model"]["h"] < a["model_pre"]["h"]
    assert "xi" not in b and "model_pre" not in b and not b["model"].get("lineups")
    assert b["model"]["h"] == pytest.approx(a["model_pre"]["h"])
    adj = B.lineup_lines(fx["matches"])
    assert set(adj) == {"1"}
    mk = build_match_markets([{"match_id": "1", "home": "A", "away": "B", "books": {"kalshi": {"home": 2.0, "draw": 3.5, "away": 4.0}}},
                              {"match_id": "2", "home": "C", "away": "D", "books": {"kalshi": {"home": 2.0, "draw": 3.5, "away": 4.0}}}],
                             Model(), adjust=adj)
    by = {f["match_id"]: f for f in mk["fixtures"]}
    assert by["1"]["lineups"] and by["1"]["model"]["home"] == pytest.approx(a["model"]["h"], abs=1e-4)
    assert "lineups" not in by["2"]
    # A term that could not be applied (no history) shows the XIs and leaves the line alone.
    fx2 = B.build_fixtures_json(store, lambda s: s, Model(), lambda m: True, {},
                                lineup_terms={"1": {"applied": False, "d": None, "c": 0.75, "home": {}, "away": {}}})
    r = {x["id"]: x for x in fx2["matches"]}["1"]
    assert r["xi"]["applied"] is False and "model_pre" not in r and r["model"]["h"] == pytest.approx(b["model"]["h"])


def test_live_terms_cost_nothing_without_posted_line_ups() -> None:
    store, _a = _store()
    assert LS.live_terms({"premier-league": store}) == {}
    store["prematch"] = {"1000": {"confirmed": True, "home": {}, "away": {}}}     # an old, finished match
    assert LS.live_terms({"premier-league": store}) == {}


def test_live_terms_price_a_posted_weaker_xi() -> None:
    store, a = _store(n_matches=12, star_out_last=False)
    ko = datetime(2026, 3, 30, 15, 0, tzinfo=timezone.utc)
    store["matches"]["2000"] = {"home": "A", "away": "B", "date": ko.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "notstarted",
                                "season_id": 1, "home_id": 1, "away_id": 2}
    xi_a = [[p if p != 105 else 111, "x", l, ""] for p, l in zip(a, LETTERS)]
    xi_b = [[p, "y", l, ""] for p, l in zip(range(200, 211), LETTERS)]
    store["prematch"] = {"2000": {"confirmed": True, "at": "2026-03-30T14:01:00Z", "home": {"xi": xi_a}, "away": {"xi": xi_b}}}
    out = LS.live_terms({"premier-league": store}, now=ko - timedelta(minutes=50))
    t = out["premier-league"]["2000"]
    assert t["applied"] and t["d"] < 0 and t["home"]["delta"] < 0 and abs(t["away"]["delta"]) < 1e-6
    assert [o["id"] for o in t["home"]["out"]] == [105]


def test_rho_is_held_at_the_club_value_only_when_a_frame_cannot_identify_it() -> None:
    import pandas as pd

    import build_site_all as B
    from oddsmarkets.football.competitions.league import fitting
    n = B.MIN_GOALS_ROWS_FOR_RHO
    all_xg = pd.DataFrame({"home_xg": np.ones(n + 50), "away_xg": np.ones(n + 50)})
    assert B.rho_hold(all_xg) == fitting.club_rho()
    goals = all_xg.copy()
    goals.loc[: n - 1, "home_xg"] = np.nan
    assert B.rho_hold(goals) is None
    assert B.rho_hold(pd.DataFrame({"home_goals": [1] * (n - 1)})) == fitting.club_rho()
    assert B.rho_hold(None) == fitting.club_rho()


def test_tier_prior_puts_weak_cup_only_clubs_below_league_clubs_and_unseen_ones_at_their_tier() -> None:
    import pandas as pd

    from oddsmarkets.football.competitions.league import fitting
    from oddsmarkets.football.core import DixonColesModel
    rng = np.random.default_rng(4)
    lg = [f"premier-league:T{i}" for i in range(8)]
    low = [f"fa-cup:L{i}" for i in range(8)]
    d0 = pd.Timestamp("2026-01-01", tz="UTC")
    rows = []
    for k in range(300):                         # league clubs among themselves
        h, a = rng.choice(lg, 2, replace=False)
        rows.append((h, a, rng.poisson(1.4), rng.poisson(1.1)))
    for k in range(120):                         # lower clubs thrash each other ...
        h, a = rng.choice(low, 2, replace=False)
        rows.append((h, a, rng.poisson(2.5), rng.poisson(0.4)))
    for k in range(60):                          # ... and lose to league clubs in the cup
        rows.append((rng.choice(lg), rng.choice(low), rng.poisson(3.0), rng.poisson(0.3)))
    df = pd.DataFrame(rows, columns=["home_team", "away_team", "home_goals", "away_goals"]).assign(match_date=d0, weight=1.0)
    plain = DixonColesModel(xi=0.0, ridge=1.0, analytic_grad=True, fixed_rho=-0.05)
    plain.fit(df, as_of=d0)
    tier = DixonColesModel(xi=0.0, ridge=1.0, analytic_grad=True, fixed_rho=-0.05, prior_group=fitting.pooled_tier)
    tier.fit(df, as_of=d0)

    def strength(m, team):
        return m.team_params(team)[0] - m.team_params(team)[1]
    lg_mean = np.mean([strength(tier, t) for t in lg])
    assert np.mean([strength(tier, t) for t in low]) < lg_mean
    assert np.mean([strength(tier, t) for t in low]) < np.mean([strength(plain, t) for t in low])
    assert strength(tier, "fa-cup:Never Seen") < lg_mean            # an unseen lower club: its tier, below the league
    assert plain.team_params("fa-cup:Never Seen") == (0.0, 0.0)
    assert fitting.pooled_tier("premier-league:Arsenal") is None and fitting.pooled_tier("champions-league:Celtic") == "continental"
