"""
Regression tests for three bugs that would only have surfaced against real data.

Each of these was invisible against the synthetic sample store, because the generator
happened to supply what the real fetcher does not. That is the dangerous shape of bug:
everything passes locally and breaks the moment live data arrives.
"""
from __future__ import annotations

import copy
import gc
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from oddsmarkets.football.competitions.liga.config import APERTURA, CLAUSURA, ZONES
from oddsmarkets.football.competitions.liga.store import (
    _derive_zone,
    iter_matches,
    torneo_from_store,
)
from oddsmarkets.football.sources.teams import normalize_team_name

ROOT = Path(__file__).parent.parent


def _load_fetcher():
    spec = importlib.util.spec_from_file_location(
        "fetch_liga", ROOT / "scripts" / "fetch_sofascore_liga.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_liga"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def real_shaped_store():
    """
    The sample store with every per-match zone stripped.

    This is what a real fetch produces: `store["zones"]` holds squad membership, but
    no individual match carries a zone.
    """
    path = ROOT / "docs" / "liga" / "data" / "liga_store.json"
    if not path.exists():
        pytest.skip("no sample store; run scripts/make_liga_sample_store.py")
    store = json.loads(path.read_text(encoding="utf-8"))
    stripped = copy.deepcopy(store)
    for match in stripped["matches"].values():
        match["zone"] = None
    return stripped


# ── bug 1: fixtures filtered by zone came back empty ─────────────────────────

def test_zone_is_derived_when_the_store_has_none(real_shaped_store) -> None:
    """
    build_site_liga filters fixtures on `match.zone`, so a store without per-match
    zones produced an empty Zonas fixture table and an empty Team-view fixture list.
    It would have looked like a Sofascore outage rather than a join bug.
    """
    assert not any(m["zone"] for m in real_shaped_store["matches"].values())

    torneo = torneo_from_store(real_shaped_store, CLAUSURA)
    fixtures = torneo.finished + torneo.remaining
    zoned = [m for m in fixtures if m.zone]

    assert zoned, "no fixture recovered a zone"
    assert len(zoned) > 0.8 * len(fixtures)
    for zone in ZONES:
        assert any(m.zone == zone for m in fixtures), zone


def test_interzone_fixtures_have_no_zone_and_that_is_correct(real_shaped_store) -> None:
    """
    A fixture between clubs in different zones belongs to neither. That must read as
    a real category, not as a derivation failure.
    """
    torneo = torneo_from_store(real_shaped_store, CLAUSURA)
    zones = torneo.zones
    for m in torneo.finished + torneo.remaining:
        home_zone = next((z for z, t in zones.items() if m.home_team in t), None)
        away_zone = next((z for z, t in zones.items() if m.away_team in t), None)
        if home_zone and home_zone == away_zone:
            assert m.zone == home_zone, m.game_id
        else:
            assert m.zone is None, m.game_id


def test_derive_zone_directly() -> None:
    zones = {"A": ["Boca Juniors", "Talleres"], "B": ["River Plate", "Racing Club"]}
    assert _derive_zone(zones, "Boca Juniors", "Talleres") == "A"
    assert _derive_zone(zones, "River Plate", "Racing Club") == "B"
    assert _derive_zone(zones, "Boca Juniors", "River Plate") is None   # interzone
    assert _derive_zone(zones, "Boca Juniors", "Unknown Club") is None
    assert _derive_zone(None, "Boca Juniors", "Talleres") is None


def test_an_explicit_zone_is_not_overwritten() -> None:
    """Derivation fills a gap; it must not override what the store already asserts."""
    store = {
        "matches": {
            "1": {"home": "Boca Juniors", "away": "River Plate", "zone": "A",
                  "torneo": CLAUSURA, "status": "Ended", "hs": 1, "as": 0},
        },
        "zones": {CLAUSURA: {"A": ["Boca Juniors"], "B": ["River Plate"]}},
    }
    zones = {"A": ["Boca Juniors"], "B": ["River Plate"]}
    match = next(iter(iter_matches(store, CLAUSURA, zones=zones)))
    assert match.zone == "A"


# ── bug 2: playoff rounds were never labelled ────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("round-of-16", "r16"), ("Round of 16", "r16"), ("octavos", "r16"), ("1/8", "r16"),
    ("quarterfinals", "qf"), ("Quarter-finals", "qf"), ("1/4", "qf"), ("cuartos", "qf"),
    ("semifinals", "sf"), ("Semi-finals", "sf"), ("1/2", "sf"),
    ("final", "final"), ("Final", "final"),
])
def test_playoff_slugs_map_to_round_keys(raw, expected) -> None:
    assert _load_fetcher().playoff_round(raw) == expected


@pytest.mark.parametrize("raw", ["12", "Round 12", "Fecha 3", None, ""])
def test_league_rounds_are_not_mistaken_for_playoffs(raw) -> None:
    """
    The costly direction of this bug. A league round misread as a playoff would drop
    real results out of the standings.
    """
    assert _load_fetcher().playoff_round(raw) is None


def test_labelled_playoff_matches_leave_the_league_standings() -> None:
    """
    The actual consequence: `is_playoff` gates what counts toward the zone table.
    Before the fix the fetcher only ever wrote numeric rounds, so a playoff match
    was scored as a league result.
    """
    zones = {"A": ["Boca Juniors", "Talleres"], "B": ["River Plate", "Racing Club"]}
    base = {
        "zones": {CLAUSURA: zones},
        "matches": {
            "1": {"home": "Boca Juniors", "away": "Talleres", "round": 3,
                  "torneo": CLAUSURA, "status": "Ended", "hs": 2, "as": 0},
            "2": {"home": "Boca Juniors", "away": "River Plate", "round": "final",
                  "torneo": CLAUSURA, "status": "Ended", "hs": 3, "as": 1},
        },
    }
    torneo = torneo_from_store(base, CLAUSURA)
    records = torneo.records()

    # The league win counts; the final does not.
    assert records["Boca Juniors"].played == 1
    assert records["Boca Juniors"].points == 3
    assert torneo.games_played == 1
    # But the final is still captured as a playoff result.
    assert "final:0" in torneo.playoff_results
    assert torneo.playoff_results["final:0"] == "Boca Juniors"


def test_a_numeric_round_still_counts_toward_the_table() -> None:
    store = {
        "zones": {CLAUSURA: {"A": ["Boca Juniors", "Talleres"], "B": []}},
        "matches": {
            "1": {"home": "Boca Juniors", "away": "Talleres", "round": 7,
                  "torneo": CLAUSURA, "status": "Ended", "hs": 1, "as": 1},
        },
    }
    torneo = torneo_from_store(store, CLAUSURA)
    assert torneo.games_played == 1
    assert torneo.records()["Boca Juniors"].points == 1
    assert torneo.playoff_results == {}


# ── bug 3: the fold cache was keyed on object identity ───────────────────────

def test_ad_hoc_registries_do_not_contaminate_each_other() -> None:
    """
    The cache was keyed on `id(aliases)`. The public signature accepts a temporary
    dict, and CPython reuses addresses after collection — so one call could be served
    another registry's table. A wrong join is worse than a missing one, because it is
    silent.
    """
    for i in range(300):
        registry = {f"Alias{i}": f"Canon{i}"}
        assert normalize_team_name(f"Alias{i}", registry) == f"Canon{i}"
        del registry
        gc.collect()


def test_named_registries_still_resolve() -> None:
    assert normalize_team_name("Türkiye") == "Turkey"
    assert normalize_team_name("CA Velez Sarsfield", "liga_argentina") == "Vélez Sarsfield"
    assert normalize_team_name("Unknown FC", "liga_argentina") == "Unknown FC"


def test_two_registries_with_the_same_key_stay_separate() -> None:
    """Distinct mappings sharing an alias must not bleed into one another."""
    a = {"Racing": "Racing Club"}
    b = {"Racing": "Racing Santander"}
    assert normalize_team_name("Racing", a) == "Racing Club"
    assert normalize_team_name("Racing", b) == "Racing Santander"
    assert normalize_team_name("Racing", a) == "Racing Club"


# ── bug 4: one season id now serves both tournaments ─────────────────────────
#
# From 2026 Sofascore stopped giving Apertura and Clausura their own season ids and
# serves both under "Primera LPF 2026". None of this could surface earlier: the
# sandbox could not reach Sofascore, so the fetcher had never run against the real
# season layout at all.

def _load_discovery():
    spec = importlib.util.spec_from_file_location(
        "discover_liga", ROOT / "scripts" / "discover_sofascore_liga.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["discover_liga"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("label,expected", [
    # The two tournaments are not labelled consistently, so only the tournament
    # word can be matched — not the whole string.
    ("Liga Profesional de Fútbol, Apertura", APERTURA),
    ("Liga Profesional, Clausura", CLAUSURA),
    ("Primera LPF 2026, Clausura, Group A", CLAUSURA),
])
def test_a_match_reports_its_own_tournament(label, expected) -> None:
    assert _load_fetcher().torneo_of_label(label) == expected


@pytest.mark.parametrize("label", ["Primera LPF 2026", "Liga Profesional 2024", "", None])
def test_an_unreadable_tournament_label_is_not_guessed(label) -> None:
    assert _load_fetcher().torneo_of_label(label) is None


def test_a_shared_season_id_is_fetched_once(monkeypatch) -> None:
    """
    Both tournaments under one id must produce one fetch, not one per tournament.

    Fetching per tournament pulls every match twice and stamps them all with
    whichever pass ran last, silently merging two tournaments into one table.
    """
    module = _load_fetcher()
    calls: list[tuple[int, tuple[str, ...]]] = []

    def fake_fetch(season_id, torneos):
        calls.append((season_id, torneos))
        return pd.DataFrame([{
            "game_id": 1, "home_team": "Boca Juniors", "away_team": "River Plate",
            "status": "Not started", "week": 1, "start_timestamp": 1769112000,
            "_torneo": APERTURA, "_season_id": season_id, "_ko_round": None,
        }])

    monkeypatch.setattr(module, "load_seasons", lambda: [
        {"year": 2026, APERTURA: 87913, CLAUSURA: 87913},
    ])
    monkeypatch.setattr(module, "load_zones", lambda year: {})
    monkeypatch.setattr(module, "fetch_season_matches", fake_fetch)

    store = {"matches": {}, "lineups": {}, "zones": {}}
    module.update_store(store)

    assert len(calls) == 1
    assert calls[0][0] == 87913
    assert sorted(calls[0][1]) == [APERTURA, CLAUSURA]


def test_separate_season_ids_are_still_fetched_separately(monkeypatch) -> None:
    """The pre-2026 layout, one id per tournament, must keep working."""
    module = _load_fetcher()
    calls: list[tuple[int, tuple[str, ...]]] = []

    def fake_fetch(season_id, torneos):
        calls.append((season_id, torneos))
        return None

    monkeypatch.setattr(module, "load_seasons", lambda: [
        {"year": 2025, APERTURA: 70268, CLAUSURA: 77826},
    ])
    monkeypatch.setattr(module, "load_zones", lambda year: {})
    monkeypatch.setattr(module, "fetch_season_matches", fake_fetch)

    module.update_store({"matches": {}, "lineups": {}, "zones": {}})

    assert sorted(calls) == [(70268, (APERTURA,)), (77826, (CLAUSURA,))]


def test_zone_membership_is_attributed_per_tournament(monkeypatch) -> None:
    """
    One standings payload carries both tournaments' zones. Keying on the zone letter
    alone lets whichever block comes last overwrite the other, which silently gives
    one tournament the other's zones.
    """
    module = _load_discovery()
    payload = {"standings": [
        {"name": "Primera LPF 2026, Clausura, Group A",
         "rows": [{"team": {"name": "Boca Juniors"}}]},
        {"name": "Apertura, Group A", "rows": [{"team": {"name": "River Plate"}}]},
        {"name": "Primera LPF 2026, Clausura, Group B",
         "rows": [{"team": {"name": "CA Talleres"}}]},
        {"name": "Apertura, Group B", "rows": [{"team": {"name": "Racing Club"}}]},
        # Aggregate tables carry no zone and must be ignored.
        {"name": "Anual 2026", "rows": [{"team": {"name": "Aldosivi"}}]},
        {"name": "Promedios 2026", "rows": [{"team": {"name": "Aldosivi"}}]},
    ]}
    monkeypatch.setattr(module, "_get", lambda path: payload)

    zones = module.discover_zones(155, 87913)

    assert zones[CLAUSURA] == {"A": ["Boca Juniors"], "B": ["Talleres"]}
    assert zones[APERTURA] == {"A": ["River Plate"], "B": ["Racing Club"]}


def test_a_single_tournament_season_keeps_its_own_zones(monkeypatch) -> None:
    """Pre-2026 standings label the zone only, so the season's tournament is used."""
    module = _load_discovery()
    payload = {"standings": [
        {"name": "Zona A", "rows": [{"team": {"name": "Boca Juniors"}}]},
        {"name": "Zona B", "rows": [{"team": {"name": "River Plate"}}]},
    ]}
    monkeypatch.setattr(module, "_get", lambda path: payload)

    zones = module.discover_zones(155, 77826, default_torneo=CLAUSURA)

    assert list(zones) == [CLAUSURA]
    assert zones[CLAUSURA] == {"A": ["Boca Juniors"], "B": ["River Plate"]}
