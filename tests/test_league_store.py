"""
Tests for the league store reader, the config registry, and the Sofascore event
mapping — the pieces that decide whether real data reaches the simulator intact.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from oddsmarkets.football.competitions.league.config import (
    LEAGUES,
    MLS,
    PREMIER_LEAGUE,
    Band,
    LeagueConfig,
)
from oddsmarkets.football.competitions.league.store import (
    iter_matches,
    league_state_from_store,
    training_frame,
)
from oddsmarkets.football.competitions.liga.strength import build_team_strength, elo_trajectories
from oddsmarkets.football.core import EloRatings
from oddsmarkets.football.sources import sofascore
from oddsmarkets.football.sources.teams import REGISTRIES, canonical_teams, normalize_team_name

from tests.test_liga_simulator import _FixedModel

ROOT = Path(__file__).parent.parent


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def epl_store():
    return _load_script("make_league_sample_store").build(PREMIER_LEAGUE, played_rounds=5)


@pytest.fixture(scope="module")
def mls_store():
    return _load_script("make_league_sample_store").build(MLS, played_rounds=8)


# ── config registry ──────────────────────────────────────────────────────────

def test_every_league_has_a_registry_and_consistent_bands() -> None:
    for slug, cfg in LEAGUES.items():
        assert cfg.slug == slug
        assert cfg.registry in REGISTRIES, slug
        for band in cfg.bands:
            assert 1 <= band.first <= band.last <= cfg.n_teams, (slug, band.key)
        ups = [b for b in cfg.bands if b.kind == "up"]
        downs = [b for b in cfg.bands if b.kind == "down"]
        assert ups, slug
        # Every plain league relegates; a league with a playoff (MLS, Liga MX,
        # where relegation is suspended) need not.
        if not cfg.playoff:
            assert downs, slug
        # Bands never overlap.
        spans = sorted((b.first, b.last) for b in cfg.bands)
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            assert a1 < b0, (slug, spans)


def test_band_validation_rejects_bad_ranges() -> None:
    with pytest.raises(ValueError):
        Band("x", "x", 3, 2)
    with pytest.raises(ValueError):
        LeagueConfig(slug="t", name="t", short_name="t", country="t", sofascore_id=1,
                     n_teams=10, bands=(Band("ucl", "UCL", 1, 12),))


def test_registries_have_no_alias_chains_and_are_idempotent() -> None:
    for name, reg in REGISTRIES.items():
        keys = set(reg)
        for alias, canonical in reg.items():
            # An identity entry is harmless; a chain (alias -> another alias that
            # resolves elsewhere) is not, because results would then depend on how
            # many times a name is normalised.
            assert canonical not in keys or reg[canonical] == canonical, (name, alias, canonical)
        for canonical in canonical_teams(name):
            assert normalize_team_name(canonical, name) == canonical


@pytest.mark.parametrize("raw,registry,expected", [
    ("Wolverhampton Wanderers", "premier_league", "Wolves"),
    ("Brighton & Hove Albion", "premier_league", "Brighton"),
    ("FC Bayern München", "bundesliga", "Bayern München"),
    ("Bayern Munich", "bundesliga", "Bayern München"),
    ("Borussia M'gladbach", "bundesliga", "Mönchengladbach"),
    ("St.Louis City", "mls", "St. Louis City"),
    ("Paris Saint-Germain", "ligue_1", "PSG"),
    ("Inter Milan", "serie_a", "Inter"),
    ("Athletic Bilbao", "la_liga", "Athletic Club"),
])
def test_league_aliases(raw, registry, expected) -> None:
    assert normalize_team_name(raw, registry) == expected


def test_discovery_file_matches_config_when_present() -> None:
    path = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "seasons.json"
    if not path.exists():
        pytest.skip("no seasons.json")
    leagues = json.loads(path.read_text(encoding="utf-8"))["leagues"]
    for slug, cfg in LEAGUES.items():
        entry = leagues.get(slug)
        assert entry, f"{slug} missing from seasons.json"
        assert entry["tournament_id"] == cfg.sofascore_id
        assert len(entry["seasons"]) >= 1
        assert len(entry["teams"]) == cfg.n_teams, slug
        for conf in cfg.conferences or ():
            assert len(entry["conferences"][conf]) == cfg.teams_per_conference


# ── store → state ────────────────────────────────────────────────────────────

def test_only_the_current_season_reaches_the_table(epl_store) -> None:
    state = league_state_from_store(epl_store, PREMIER_LEAGUE)
    assert len(state.teams) == 20
    n_current = sum(1 for m in epl_store["matches"].values() if m["season_id"] == 900002)
    assert len(state.finished) + len(state.remaining) == n_current
    assert state.total_league_games == 380
    assert state.games_played == sum(
        1 for m in epl_store["matches"].values()
        if m["season_id"] == 900002 and m["status"] == "finished"
    )


def test_training_frame_spans_both_seasons(epl_store) -> None:
    df = training_frame(epl_store, PREMIER_LEAGUE)
    assert len(df) == sum(1 for m in epl_store["matches"].values() if m["status"] == "finished")
    assert {"home_xg", "away_xg"} <= set(df.columns)
    assert df["match_date"].is_monotonic_increasing


def test_playoff_matches_stay_out_of_the_table(epl_store) -> None:
    store = json.loads(json.dumps(epl_store))
    first = next(iter(store["matches"]))
    store["matches"]["po"] = {
        **store["matches"][first], "stage": "playoff", "status": "finished",
        "hs": 5, "as": 0, "season_id": 900002,
    }
    state = league_state_from_store(store, PREMIER_LEAGUE)
    plain = league_state_from_store(epl_store, PREMIER_LEAGUE)
    home = store["matches"]["po"]["home"]
    assert state.records()[home].points == plain.records()[home].points
    assert state.games_played == plain.games_played


def test_standings_follow_the_tiebreak(epl_store) -> None:
    state = league_state_from_store(epl_store, PREMIER_LEAGUE)
    rows = state.standings()
    for (_, a), (_, b) in zip(rows, rows[1:]):
        assert (a.points, a.gd, a.gf) >= (b.points, b.gd, b.gf)


def test_status_strings_from_either_fetcher_are_understood() -> None:
    store = {"matches": {
        "1": {"home": "A", "away": "B", "status": "finished", "hs": 1, "as": 0, "season_id": 1},
        "2": {"home": "A", "away": "B", "status": "Ended", "hs": 1, "as": 0, "season_id": 1},
        "3": {"home": "A", "away": "B", "status": "inprogress", "hs": 1, "as": 0, "season_id": 1},
        "4": {"home": "A", "away": "B", "status": "postponed", "hs": None, "as": None, "season_id": 1},
        "5": {"home": "A", "away": "B", "status": "Not started", "hs": None, "as": None, "season_id": 1},
    }, "meta": {"season_id": 1}}
    statuses = {m.game_id: m.status for m in iter_matches(store, PREMIER_LEAGUE)}
    assert statuses == {"1": "finished", "2": "finished", "3": "live", "4": "scheduled", "5": "scheduled"}


def test_mls_conferences_and_previous_rank(mls_store) -> None:
    state = league_state_from_store(
        mls_store, MLS, previous_rank={"Inter Miami CF": 1, "St.Louis City": 30},
    )
    assert set(state.conferences) == {"Eastern", "Western"}
    assert all(len(m) == 15 for m in state.conferences.values())
    assert len(state.teams) == 30
    for conf, members in state.conferences.items():
        for t in members:
            assert state.zone_of(t) == conf
    # Previous-season ranks are normalised through the registry.
    assert state.previous_rank.get("Inter Miami") == 1
    assert state.previous_rank.get("St. Louis City") == 30
    assert len(state.standings("Eastern")) == 15


def test_state_is_duck_compatible_with_the_shared_strength_module(epl_store) -> None:
    state = league_state_from_store(epl_store, PREMIER_LEAGUE)
    model = _FixedModel(home_bias=0.2)
    rows = build_team_strength(model, state, state.teams)
    assert len(rows) == 20
    assert {r.team for r in rows} == set(state.teams)
    played = [r for r in rows if r.played > 0]
    assert played and all(r.form_results for r in played)
    ranks = sorted(r.table_rank for r in rows)
    assert ranks == list(range(1, 21))

    def factory():
        elo = EloRatings(k_league=20, home_advantage=60)
        elo.seed_from_ranking({t: i + 1 for i, t in enumerate(state.teams)}, n_teams=20)
        return elo

    hist = elo_trajectories(factory, state, state.teams)
    assert any(len(v) > 1 for v in hist.values())


# ── Sofascore event mapping ──────────────────────────────────────────────────

def _event(**over):
    base = {
        "id": 123, "startTimestamp": 1788548400, "winnerCode": 2,
        "status": {"type": "finished"}, "roundInfo": {"round": 3},
        "homeTeam": {"name": "Ipswich Town"}, "awayTeam": {"name": "Liverpool FC"},
        "homeScore": {"display": 0}, "awayScore": {"display": 2},
        "tournament": {"name": "Premier League"},
    }
    base.update(over)
    return base


def test_league_event_maps_to_a_store_record() -> None:
    gid, rec = sofascore.event_record(_event(), lambda n: normalize_team_name(n, "premier_league"), 96668)
    assert gid == "123"
    assert rec["home"] == "Ipswich" and rec["away"] == "Liverpool"
    assert rec["round"] == 3 and rec["stage"] == "league"
    assert rec["hs"] == 0 and rec["as"] == 2 and rec["status"] == "finished"
    from datetime import datetime, timezone
    expected = datetime.fromtimestamp(1788548400, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert rec["date"] == expected
    assert rec["winner"] is None and rec["season_id"] == 96668


def test_mls_playoff_event_is_tagged_by_its_tournament_label() -> None:
    """MLS playoff events carry no roundInfo; the label is the only marker."""
    ev = _event(roundInfo=None, tournament={"name": "MLS, Playoffs"},
                homeTeam={"name": "Philadelphia Union"}, awayTeam={"name": "Chicago Fire FC"},
                homeScore={"display": 2}, awayScore={"display": 2}, winnerCode=1)
    _, rec = sofascore.event_record(ev, lambda n: normalize_team_name(n, "mls"), 70158)
    assert rec["stage"] == "playoff"
    assert rec["winner"] == "Philadelphia Union"      # drawn, settled on penalties


def test_scheduled_event_has_no_score() -> None:
    ev = _event(status={"type": "notstarted"}, homeScore={}, awayScore={}, winnerCode=None)
    _, rec = sofascore.event_record(ev, str, 1)
    assert rec["hs"] is None and rec["as"] is None and rec["status"] == "notstarted"


@pytest.mark.parametrize("slug,name,expected", [
    ("quarterfinals", None, "qf"),
    (None, "Semi-finals", "sf"),
    ("conference-semifinals", None, "csf"),
    ("conference-final", None, "cf"),
    ("final", None, "final"),
    (None, "Round 12", None),
    (None, None, None),
])
def test_playoff_round_keys(slug, name, expected) -> None:
    assert sofascore.playoff_round(slug, name) == expected


# ── playoff results from the store ───────────────────────────────────────────

def _po(gid, home, away, hs, as_, winner=None):
    from oddsmarkets.football.competitions.league.season_state import LeagueMatch
    return LeagueMatch(game_id=gid, home_team=home, away_team=away, home_goals=hs, away_goals=as_,
                       stage="playoff", status="finished", winner=winner)


def test_best_of_three_is_decided_at_two_wins() -> None:
    from oddsmarkets.football.competitions.league.store import playoff_results
    one_one = [_po("1", "A", "B", 2, 0), _po("2", "B", "A", 1, 0)]
    assert playoff_results(one_one, MLS) == {}
    decided = one_one + [_po("3", "A", "B", 1, 1, winner="A")]
    assert playoff_results(decided, MLS) == {frozenset(("A", "B")): "A"}


def test_single_playoff_match_decides_outright() -> None:
    from oddsmarkets.football.competitions.league.store import playoff_results
    assert playoff_results([_po("1", "C", "D", 0, 0, winner="D")], MLS) == {frozenset(("C", "D")): "D"}
    assert playoff_results([_po("1", "C", "D", 0, 0)], MLS) == {}          # drawn, no winner recorded
    assert playoff_results([_po("1", "E", "F", 3, 1)], PREMIER_LEAGUE) == {frozenset(("E", "F")): "E"}


def test_state_carries_team_ids_and_playoff_results(mls_store) -> None:
    store = json.loads(json.dumps(mls_store))
    first = next(iter(store["matches"]))
    store["matches"][first]["home_id"] = 4242
    a, b = store["matches"][first]["home"], store["matches"][first]["away"]
    store["matches"]["po1"] = {**store["matches"][first], "stage": "playoff", "status": "finished",
                               "hs": 2, "as": 1, "season_id": 900002}
    state = league_state_from_store(store, MLS)
    assert state.team_ids[normalize_team_name(a, "mls")] == 4242
    assert state.playoff_results == {frozenset((normalize_team_name(a, "mls"), normalize_team_name(b, "mls"))): normalize_team_name(a, "mls")}
    assert state.games_played == sum(1 for m in mls_store["matches"].values()
                                     if m["season_id"] == 900002 and m["status"] == "finished")


def test_store_signature_ignores_live_scores_but_not_results(epl_store) -> None:
    from oddsmarkets.football.competitions.league.store import store_signature
    base = store_signature(epl_store)
    live = json.loads(json.dumps(epl_store))
    gid = next(g for g, m in live["matches"].items() if m["status"] != "finished")
    live["matches"][gid].update({"status": "inprogress", "hs": 1, "as": 0})
    assert store_signature(live) == base          # a live score is not a change
    done = json.loads(json.dumps(live))
    done["matches"][gid]["status"] = "finished"
    assert store_signature(done) != base          # a result is
    moved = json.loads(json.dumps(epl_store))
    moved["matches"][gid]["date"] = "2027-01-01T00:00:00Z"
    assert store_signature(moved) != base         # so is a rescheduled fixture


def test_fetcher_propagates_a_club_rename_into_stored_detail(monkeypatch) -> None:
    """A registry change renames the club in lineups and shots already stored for a match."""
    module = _load_script("fetch_sofascore_leagues")
    from oddsmarkets.football.competitions.league.config import PREMIER_LEAGUE

    def fake_events(tid, sid):
        return [{"id": 7, "startTimestamp": 1788548400, "status": {"type": "finished"}, "roundInfo": {"round": 1},
                 "homeTeam": {"name": "Wolverhampton", "id": 3, "country": {"alpha3": "ENG"}},
                 "awayTeam": {"name": "Fulham", "id": 4, "country": {"alpha3": "ENG"}},
                 "homeScore": {"display": 2}, "awayScore": {"display": 0}, "tournament": {"name": "Premier League"}}]

    monkeypatch.setattr(module.sofascore, "season_events", fake_events)
    store = {"matches": {"7": {"home": "Wolverhampton", "away": "Fulham", "status": "finished", "hs": 2, "as": 0,
                               "season_id": 1, "stage": "league"}},
             "lineups": {"7": {"p1": {"n": "A", "t": "Wolverhampton", "s": {"goals": 1}}}},
             "shots": {"7": [{"player_name": "A", "team": "Wolverhampton", "x": 90, "y": 50}]},
             "momentum": {}, "incidents": {}, "meta": {}}
    entry = {"seasons": [{"season_id": 1, "tournament_id": 17, "name": "t"}]}
    status = module.refresh_fixtures(store, PREMIER_LEAGUE, entry)
    assert status["ok"]
    assert store["matches"]["7"]["home"] == "Wolves"
    assert store["lineups"]["7"]["p1"]["t"] == "Wolves"
    assert store["shots"]["7"][0]["team"] == "Wolves"
