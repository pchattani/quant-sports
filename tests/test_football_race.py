"""The league Race tab's payload fields: the simulator's stakes split, the set-piece profile and the daily race
history (oddsmarkets/football/analytics/race.py)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np

from oddsmarkets.football.analytics import race
from oddsmarkets.football.competitions.league.config import MLS, PREMIER_LEAGUE, with_sims
from oddsmarkets.football.competitions.league.simulator import LeagueSimulator

from tests.test_league_simulator import make_state
from tests.test_liga_simulator import _FixedModel

EPL = with_sims(PREMIER_LEAGUE, 4_000)
T0 = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


def dated_state(cfg, played_fraction=0.8):
    """A league with the remaining fixtures dated a round a week, from T0."""
    st = make_state(cfg, played_fraction=played_fraction)
    rounds = sorted({int(m.round_name) for m in st.remaining})
    first = {r: i for i, r in enumerate(rounds)}
    st.remaining = [replace(m, date=T0 + timedelta(days=7 * first[int(m.round_name)])) for m in st.remaining]
    return st


def test_stakes_split_every_simulation_by_the_next_fixtures():
    st = dated_state(EPL)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), st, cfg=EPL, seed=11).run()
    assert res.stakes, "dated fixtures within the week give stakes"
    first_round = [m for m in st.remaining if m.date == T0]
    assert len(res.stakes) == min(len(first_round), 12)
    for s in res.stakes:
        assert sum(s["n"]) == res.n_sims
        # each result's title chances add to one over the clubs
        for o in range(3):
            if s["title"][o] is not None:
                assert abs(sum(s["title"][o]) - 1.0) < 1e-9
        # the conditional chances average back to the unconditional one
        i = res.teams.index(s["home"])
        mix = sum(s["n"][o] * s["title"][o][i] for o in range(3) if s["title"][o] is not None) / res.n_sims
        assert abs(mix - res.p_title[s["home"]]) < 1e-9
        assert set(s["bands"]) == {b.key for b in EPL.bands}


def test_winning_helps_a_contender():
    st = dated_state(EPL, played_fraction=0.6)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), st, cfg=EPL, seed=5).run()
    best = max(res.stakes, key=lambda s: max(res.p_title[s["home"]], res.p_title[s["away"]]))
    i = res.teams.index(best["home"])
    win, loss = best["title"][0][i], best["title"][2][i]
    assert win >= loss


def test_no_stakes_without_dates_or_for_conference_formats():
    st = make_state(EPL, played_fraction=0.8)                 # undated
    assert LeagueSimulator(_FixedModel(), st, cfg=EPL).run().stakes == []
    mls = with_sims(MLS, 500)
    st2 = make_state(mls, played_fraction=0.8)
    st2.remaining = [replace(m, date=T0) for m in st2.remaining]
    assert LeagueSimulator(_FixedModel(), st2, cfg=mls).run().stakes == []


def test_stakes_do_not_change_the_simulation():
    st = dated_state(EPL)
    a = LeagueSimulator(_FixedModel(0.2), st, cfg=EPL, seed=9).run()
    b = LeagueSimulator(_FixedModel(0.2), st, cfg=EPL, seed=9, stake_max=0).run()
    assert b.stakes == []
    assert a.p_title == b.p_title and a.p_position == b.p_position


def test_stakes_payload_is_compact_and_ranked_by_noise_free_moves():
    st = dated_state(EPL, played_fraction=0.6)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), st, cfg=EPL, seed=3).run()
    out = race.stakes_payload(res, EPL)
    assert len(out) == len(res.stakes)
    for s in out:
        assert abs(sum(s["p"]) - 1) < 0.01
        assert s["swing"] >= 0
        for m in s["m"]:
            assert m["key"] in {"title"} | {b.key for b in EPL.bands}
            assert 0 < len(m["teams"]) <= race.STAKE_TEAMS
            for v in m["teams"].values():
                assert len(v) == 3
                lo = min(x for x in v if x is not None)
                hi = max(x for x in v if x is not None)
                assert hi - lo >= race.STAKE_MIN_MOVE - 1e-9


def _store():
    m = {}
    shots = {}
    teams = ["A", "B", "C", "D", "E"]
    gid = 0
    for i, h in enumerate(teams):
        for j, a in enumerate(teams):
            if i == j:
                continue
            gid += 1
            m[str(gid)] = {"home": h, "away": a, "status": "finished", "stage": "league", "hs": 1, "as": 0}
            shots[str(gid)] = [
                {"is_home": True, "xg": 0.3, "situation": "corner"},
                {"is_home": True, "xg": 0.5, "situation": "assisted"},
                {"is_home": False, "xg": 0.2 * (j + 1), "situation": "fast-break"},
                {"is_home": False, "xg": 0.79, "situation": "penalty"},
            ]
    return {"matches": m, "shots": shots}


def test_set_pieces_per_match_and_percentiles():
    out = race.set_pieces(_store())
    t = out["teams"]
    assert set(t) == {"A", "B", "C", "D", "E"}
    a = t["A"]
    assert a["matches"] == 8
    # A hosts four matches (0.3 set-piece xG each), never takes a set piece away
    assert abs(a["sp_xg"] - 0.3 * 4 / 8) < 1e-3
    # penalties are neither set pieces nor open play
    assert a["sp_share"] is not None and 0 < a["sp_share"] < 1
    assert all(0 <= v <= 100 for r in t.values() for v in r["pct"].values())


def test_set_pieces_skip_unfinished_and_small_leagues():
    s = _store()
    for v in s["matches"].values():
        v["status"] = "notstarted"
    assert race.set_pieces(s) == {}


def test_roll_daily_keeps_one_snapshot_a_day_and_resets_each_season():
    snaps = [
        {"ts": "2026-10-20T08:00:00Z", "title": {"A": 0.5, "B": 0.5}, "relegation": {"C": 0.9}},
        {"ts": "2026-10-20T20:00:00Z", "title": {"A": 0.6, "B": 0.4}, "relegation": {"C": 0.8}},
        {"ts": "2026-10-21T09:00:00Z", "title": {"A": 0.7, "B": 0.3, "Z": 0.0001}, "band": {"A": 1.0}, "band_key": "ucl"},
        {"ts": "2026-10-19T09:00:00Z", "title": {"Old": 1.0}},          # last season's club: skipped
    ]
    d = race.roll_daily(None, snaps, "S1", ["A", "B", "C", "Z"])
    assert [e["d"] for e in d["days"]] == ["2026-10-20", "2026-10-21"]
    assert d["days"][0]["title"] == {"A": 0.6, "B": 0.4}
    assert "Z" not in d["days"][1]["title"]                            # under DAILY_MIN
    assert d["days"][1]["band_key"] == "ucl"
    # carried forward when the hourly snapshots have rolled off
    d2 = race.roll_daily(d, [{"ts": "2026-10-22T09:00:00Z", "title": {"A": 0.8, "B": 0.2}}], "S1", ["A", "B", "C"])
    assert [e["d"] for e in d2["days"]] == ["2026-10-20", "2026-10-21", "2026-10-22"]
    # a new season starts afresh
    d3 = race.roll_daily(d2, [{"ts": "2027-08-10T09:00:00Z", "title": {"A": 0.3}}], "S2", ["A"])
    assert [e["d"] for e in d3["days"]] == ["2027-08-10"]
    assert np.isclose(d3["days"][0]["title"]["A"], 0.3)
