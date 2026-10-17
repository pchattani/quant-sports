"""
Tests for reading a Sofascore store into simulator inputs.

The store is the only data source for the Liga dashboard, and the build must work
offline against a committed copy — that is what makes CI viable at all, since
Sofascore blocks datacenter IPs. So these exercise the full store -> SeasonState ->
simulator path with no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from oddsmarkets.football.competitions.liga.config import (
    APERTURA,
    CLAUSURA,
    FALLBACK_ZONES_2026,
    LigaConfig,
    ZONE_A,
    ZONE_B,
    ZONES,
)
from oddsmarkets.football.competitions.liga.store import (
    empirical_calibration,
    load_store,
    save_store,
    season_state_from_store,
    store_age_hours,
    team_xg_map,
    torneo_from_store,
    training_frame,
    zones_from_store,
)

CFG = LigaConfig(n_sims=500, sim_chunk=500)
BASE = datetime(2026, 7, 23, tzinfo=timezone.utc)


def _build_store(clausura_played: int = 20, with_xg: bool = True) -> dict:
    """A store shaped exactly like the Liga fetcher writes."""
    zones = {z: list(FALLBACK_ZONES_2026[z]) for z in ZONES}
    store = {
        "matches": {}, "lineups": {}, "shots": {},
        "momentum": {}, "incidents": {},
        "zones": {APERTURA: zones, CLAUSURA: zones},
        "meta": {"updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }

    gid = 0
    # A complete Apertura: one round-robin per zone.
    for zone in ZONES:
        members = zones[zone]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                gid += 1
                store["matches"][str(gid)] = {
                    "home": members[i], "away": members[j],
                    "round": (i + j) % 14 + 1, "status": "Ended",
                    "hs": (i + j) % 4, "as": (i * j) % 3,
                    "date": (BASE - timedelta(days=200 - gid % 150)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "torneo": APERTURA, "zone": zone,
                }

    # A Clausura part-played.
    clausura_ids = []
    for zone in ZONES:
        members = zones[zone]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                gid += 1
                clausura_ids.append(str(gid))
                store["matches"][str(gid)] = {
                    "home": members[i], "away": members[j],
                    "round": (i + j) % 14 + 1, "status": "Not started",
                    "hs": None, "as": None,
                    "date": (BASE + timedelta(days=gid % 120)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "torneo": CLAUSURA, "zone": zone,
                }
    for k, mid in enumerate(clausura_ids[:clausura_played]):
        store["matches"][mid].update({"status": "Ended", "hs": k % 3, "as": (k + 1) % 3})

    if with_xg:
        for mid in list(store["matches"])[:40]:
            meta = store["matches"][mid]
            store["lineups"][mid] = {
                "p1": {"n": "Player One", "t": meta["home"], "s": {"expectedGoals": 0.7}},
                "p2": {"n": "Player Two", "t": meta["home"], "s": {"expectedGoals": 0.4}},
                "p3": {"n": "Player Three", "t": meta["away"], "s": {"expectedGoals": 0.5}},
            }
    return store


def test_load_missing_store_returns_empty(tmp_path) -> None:
    """An absent store must degrade, not raise — CI depends on this."""
    store = load_store(tmp_path / "nope.json")
    assert store["matches"] == {}
    assert store["lineups"] == {}


def test_load_corrupt_store_returns_empty(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_store(path)["matches"] == {}


def test_save_and_reload_roundtrip(tmp_path) -> None:
    path = tmp_path / "store.json"
    save_store(_build_store(), path)
    reloaded = load_store(path)
    assert len(reloaded["matches"]) > 400
    assert store_age_hours(reloaded) < 1.0


def test_zones_read_from_store() -> None:
    zones = zones_from_store(_build_store(), CLAUSURA, CFG)
    assert len(zones[ZONE_A]) == CFG.teams_per_zone
    assert len(zones[ZONE_B]) == CFG.teams_per_zone


def test_zones_fall_back_when_store_is_wrong_size(caplog) -> None:
    store = _build_store()
    store["zones"][CLAUSURA] = {ZONE_A: ["Boca Juniors"], ZONE_B: []}
    with caplog.at_level("WARNING"):
        zones = zones_from_store(store, CLAUSURA, CFG)
    assert len(zones[ZONE_A]) == CFG.teams_per_zone
    assert any("wrong size" in r.message for r in caplog.records)


def test_finished_and_remaining_are_split() -> None:
    torneo = torneo_from_store(_build_store(clausura_played=20), CLAUSURA, CFG)
    assert torneo.games_played == 20
    assert len(torneo.remaining) == torneo.total_league_games - 20
    assert not torneo.league_complete


def test_completed_torneo_has_no_remaining() -> None:
    torneo = torneo_from_store(_build_store(), APERTURA, CFG)
    assert torneo.league_complete
    assert torneo.remaining == []


def test_standings_order_and_points() -> None:
    torneo = torneo_from_store(_build_store(clausura_played=40), CLAUSURA, CFG)
    table = torneo.standings(ZONE_A)
    assert len(table) == CFG.teams_per_zone
    points = [rec.points for _, rec in table]
    assert points == sorted(points, reverse=True)
    for _, rec in table:
        assert rec.points == rec.won * 3 + rec.drawn
        assert rec.played == rec.won + rec.drawn + rec.lost


def test_xg_is_keyed_by_match_not_team_pair() -> None:
    """
    The World Cup keys xG by frozenset({home, away}), which collapses repeat meetings.
    In a league the same clubs meet several times, so keys must be per match.
    """
    xg = team_xg_map(_build_store())
    assert len(xg) == 40
    for home_xg, away_xg in xg.values():
        assert home_xg == pytest.approx(1.1)
        assert away_xg == pytest.approx(0.5)


def test_training_frame_shape_and_xg_columns() -> None:
    df = training_frame(_build_store(clausura_played=20))
    assert len(df) == 210 + 20
    assert {"home_team", "away_team", "home_goals", "away_goals", "match_date"} <= set(df.columns)
    assert df["match_date"].is_monotonic_increasing
    # Partial xG coverage is expected and fine — the fit mixes likelihoods per row.
    assert df["home_xg"].notna().sum() == 40
    assert df["home_xg"].isna().sum() > 0


def test_training_frame_empty_store_is_safe() -> None:
    df = training_frame({"matches": {}, "lineups": {}})
    assert len(df) == 0


def test_empirical_calibration_reflects_the_data() -> None:
    df = training_frame(_build_store(clausura_played=40))
    cal = empirical_calibration(df)
    assert 0.0 <= cal["draw_rate"] <= 1.0
    assert cal["lam_scale"] == pytest.approx(2.0 * cal["mean_goals"])
    # Defaults must be returned rather than dividing by zero on an empty frame.
    fallback = empirical_calibration(training_frame({"matches": {}}))
    assert fallback["draw_rate"] == 0.25
    assert fallback["lam_scale"] == 2.6


def test_season_state_and_promedios() -> None:
    store = _build_store(clausura_played=30)
    prior = {t: (60, 45) for t in FALLBACK_ZONES_2026[ZONE_A]}
    state = season_state_from_store(
        store, CFG, promedios_prior=prior, apertura_champion="Belgrano"
    )
    assert len(state.teams) == CFG.n_teams
    assert state.apertura.champion == "Belgrano"
    assert state.live_torneo().key == CLAUSURA

    # The Apertura is complete, so it contributes to the Tabla Anual base.
    base = state.anual_base()
    assert sum(r.played for r in base.values()) == 210 * 2

    promedios = state.promedio_now()
    assert len(promedios) == CFG.n_teams
    assert all(p >= 0 for p in promedios.values())
    # A club with no prior history is scored on this season alone, not penalised.
    newcomer = FALLBACK_ZONES_2026[ZONE_B][0]
    assert promedios[newcomer] > 0


def test_end_to_end_offline_simulation() -> None:
    """
    The critical integration check: store on disk -> state -> simulator, no network.
    This is the same path CI takes when Sofascore is unreachable.
    """
    from oddsmarkets.football.competitions.liga.simulator import LigaSimulator
    from tests.test_liga_simulator import _FixedModel

    store = _build_store(clausura_played=30)
    state = season_state_from_store(store, CFG, apertura_champion="Belgrano")
    res = LigaSimulator(_FixedModel(home_bias=0.2), state, cfg=CFG).run()

    assert sum(res.p_relegation_any.values()) == pytest.approx(2.0, abs=1e-6)
    assert sum(res.p_title.values()) == pytest.approx(1.0, abs=1e-6)
    assert res.p_libertadores["Belgrano"] == pytest.approx(1.0)


def test_unknown_status_counts_as_scheduled() -> None:
    store = _build_store(clausura_played=0)
    first = next(iter(store["matches"]))
    store["matches"][first]["status"] = "Postponed"
    torneo = torneo_from_store(store, APERTURA, CFG)
    assert all(m.game_id != first for m in torneo.finished)
