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
    from oddsmarkets.football.competitions.liga.store import store_path
    path = store_path()
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


# ── overdue fixtures held again under another id (liga.store.mark_superseded) ──

def _fx(home, away, date, status="notstarted", rnd=None, stage="league", sid=1, hs=None, as_=None):
    return {"home": home, "away": away, "date": date, "status": status, "round": rnd, "stage": stage, "season_id": sid,
            "hs": hs, "as": as_}


def test_overdue_relisted_fixtures_are_closed_and_others_flagged(tmp_path) -> None:
    """Sofascore keeps a re-listed match's old id as "notstarted": it is closed against the copy (same sides, or the
    sides swapped within a day), a second leg is never taken for it, and a lone overdue fixture is left to the
    pages ("result not reported"). Loading the store applies it; the file is not rewritten."""
    from datetime import datetime, timezone

    from oddsmarkets.football.competitions.liga import store as L

    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    store = {"matches": {
        "old1": _fx("A", "B", "2026-10-01T12:00:00Z"),                                       # friendly entered twice
        "new1": _fx("A", "B", "2026-10-01T14:00:00Z", "finished", hs=0, as_=6),
        "old2": _fx("C", "D", "2026-09-11T14:00:00Z", rnd="r1", stage="qualifying"),          # sides swapped
        "new2": _fx("D", "C", "2026-09-11T14:00:00Z", "finished", rnd="r1", stage="qualifying", hs=0, as_=4),
        "leg2": _fx("D", "C", "2026-10-03T12:00:00Z", "finished", rnd="r1", stage="qualifying", hs=0, as_=1),
        "old3": _fx("E", "F", "2026-09-23T13:00:00Z", rnd="2", stage="qualifying"),          # postponed, re-listed
        "new3": _fx("E", "F", "2026-10-24T17:00:00Z", rnd="2", stage="qualifying"),
        "lone": _fx("G", "H", "2026-10-17T12:00:00Z", rnd="r32", stage="playoff"),           # no copy anywhere
        "soon": _fx("I", "J", "2026-10-18T10:00:00Z"),                                       # two hours ago: not overdue
        "far": _fx("K", "L", "2026-09-01T12:00:00Z"),                                        # a pair met again weeks later
        "far2": _fx("K", "L", "2026-10-01T12:00:00Z", "finished", hs=1, as_=0),
    }}
    out = dict(L.mark_superseded(store, now))
    assert out == {"old1": "new1", "old2": "new2", "old3": "new3"}
    m = store["matches"]
    assert m["old1"]["status"] == "canceled" and m["old1"]["status_was"] == "notstarted"
    assert L.overdue(m["lone"], now) and not L.overdue(m["soon"], now) and not L.overdue(m["new3"], now)
    assert m["far"]["status"] == "notstarted"                         # no round, 30 days apart: not the same match
    assert L.mark_superseded(store, now) == []                        # idempotent
    path = tmp_path / "store.json"
    raw = {"matches": {"old1": _fx("A", "B", "2026-10-01T12:00:00Z"), "new1": _fx("A", "B", "2026-10-01T14:00:00Z", "finished", hs=0, as_=6)},
           "meta": {}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    s = L.load_store(path)
    assert s["matches"]["old1"]["superseded_by"] == "new1"
    assert json.loads(path.read_text(encoding="utf-8")) == raw


def test_superseded_and_overdue_fixtures_in_the_payloads() -> None:
    """fixtures.json drops the old copy and calls a lone overdue fixture postponed with result_missing; the league and
    cup readers skip the old copy, so it is never simulated twice."""
    import scripts.build_site_all as b
    from oddsmarkets.football.competitions.cup import store as cup_store

    store = {"matches": {
        "old": dict(_fx("A", "B", "2020-10-01T12:00:00Z"), status="canceled", superseded_by="new"),
        "new": _fx("A", "B", "2020-10-01T14:00:00Z", "finished", hs=1, as_=0),
        "lone": _fx("C", "D", "2020-10-02T12:00:00Z"),
        "next": _fx("E", "F", "2099-10-02T12:00:00Z"),
    }, "lineups": {}}
    rows = {r["id"]: r for r in b.build_fixtures_json(store, lambda n: n, None, lambda raw: True, {})["matches"]}
    assert "old" not in rows and rows["new"]["status"] == "finished"
    assert rows["lone"]["status"] == "postponed" and rows["lone"]["result_missing"] is True
    assert rows["next"]["status"] == "scheduled" and "result_missing" not in rows["next"]
    assert [m.game_id for m, _ in cup_store.iter_matches(store)] == ["new", "lone", "next"]


def test_cancelled_fixture_is_cancelled_and_void_matches_carry_no_score() -> None:
    """Sofascore's "canceled" event (with a placeholder 0-0) used to show as postponed with a 0-0 score: "canceled" is
    also in _POSTPONED, which the payload checked first (accuracy audit, 22 Oct 2026: Rayo Vallecano v Athletic Club)."""
    import scripts.build_site_all as b

    store = {"matches": {
        "c": _fx("A", "B", "2026-10-10T12:00:00Z", "canceled", hs=0, as_=0),
        "p": _fx("C", "D", "2099-12-12T15:00:00Z", "postponed"),
        "f": _fx("E", "F", "2026-10-11T12:00:00Z", "finished", hs=2, as_=1),
    }, "lineups": {}}
    rows = {r["id"]: r for r in b.build_fixtures_json(store, lambda n: n, None, lambda raw: True, {})["matches"]}
    assert rows["c"]["status"] == "cancelled" and rows["c"]["hs"] is None and rows["c"]["as"] is None
    assert rows["p"]["status"] == "postponed" and rows["p"]["hs"] is None
    assert (rows["f"]["status"], rows["f"]["hs"], rows["f"]["as"]) == ("finished", 2, 1)


def test_positions_fall_back_to_the_squads_and_other_stores() -> None:
    """A store that saw a player only in line-ups without a position (UEFA qualifiers) takes it from the current
    squads, then other stores' metadata; the store's own knowledge always wins (accuracy audit, 22 Oct 2026)."""
    import scripts.build_site_all as b
    from oddsmarkets.football.analytics import players as P

    squads = {"teams": {"1": {"players": [{"id": 7, "pos": "D"}, {"id": 8, "pos": "F"}]}}}
    other = {"players": {"9": {"pos": "G"}, "7": {"pos": "M"}}}
    fb = b.fallback_positions(squads, [other])
    assert fb == {"7": "D", "8": "F", "9": "G"}           # squads first
    store = {"players": {"8": {"pos": "M"}}, "lineups": {"g1": {
        "7": {"n": "Seven", "s": {}}, "8": {"n": "Eight", "s": {}}, "9": {"n": "Nine", "p": "F", "s": {}}, "10": {"n": "Ten", "s": {}}}}}
    try:
        assert P.positions_from_store(store) == {"8": "M", "9": "F"}
        P.set_fallback_positions(fb)
        assert P.positions_from_store(store) == {"7": "D", "8": "M", "9": "F"}
    finally:
        P.set_fallback_positions({})


def _cup(slug_rounds):
    from types import SimpleNamespace
    return SimpleNamespace(kind="knockout", rounds=slug_rounds)


def _km(home, away, date, rnd, stage="playoff", hs=None, as_=None, status=None, sid=1, **kw):
    st = status or ("finished" if hs is not None else "notstarted")
    return {"home": home, "away": away, "date": date, "round": rnd, "stage": stage, "hs": hs, "as": as_, "status": st,
            "season_id": sid, **kw}


def test_national_cup_rounds_go_on_the_bracket() -> None:
    """Sofascore's "Round 2", "Round 3" of a national cup were "qualifying" (never simulated): the EFL Cup ran from its
    first round alone, so West Ham, out in the third round, were 21% to win it (accuracy audit, 22 Oct 2026)."""
    from oddsmarkets.football.competitions.cup import store as cs

    cfg = _cup((("r1", 1), ("r2", 1), ("r3", 1), ("r4", 1), ("qf", 1), ("sf", 2), ("final", 1)))
    store = {"matches": {
        "1": _km("West Ham", "Portsmouth", "2026-08-08T18:00:00Z", "r1", hs=3, as_=1),
        "2": _km("Southampton", "West Ham", "2026-08-25T18:00:00Z", 2, stage="qualifying", hs=1, as_=4),
        "3": _km("West Ham", "Fulham", "2026-09-15T18:00:00Z", 3, stage="qualifying", hs=2, as_=3),
        "4": _km("Fulham", "Everton", "2026-10-28T19:00:00Z", 4, stage="qualifying"),
    }}
    assert cs.normalize_knockout_rounds(store, cfg) == 3
    assert [(m["stage"], m["round"]) for m in store["matches"].values()] == [
        ("playoff", "r1"), ("playoff", "r2"), ("playoff", "r3"), ("playoff", "r4")]
    results, pairs = cs.tie_results(list(cs.iter_matches(store)))
    assert results[frozenset(("West Ham", "Fulham"))] == "Fulham"
    assert cs.normalize_knockout_rounds(store, cfg) == 0                       # idempotent
    assert cs.normalize_knockout_rounds(store, _cup((("r1", 1),)).__class__(kind="groups", rounds=())) == 0


def test_qualifying_rounds_are_not_the_first_round_proper() -> None:
    """The FA Cup's first qualifying round (September) and its first round proper (November) both read "r1": a club in
    two first-round ties, "reach" 2.0. The earlier ties are qualifying, and so is a numbered round before the first
    round proper."""
    from oddsmarkets.football.competitions.cup import store as cs

    cfg = _cup((("r1", 1), ("r2", 1), ("r3", 1), ("final", 1)))
    store = {"matches": {
        "q1": _km("Desborough", "Rushden", "2026-09-05T14:00:00Z", "r1", hs=0, as_=3),
        "q1b": _km("Alpha", "Beta", "2026-09-05T14:00:00Z", "r1", hs=1, as_=0),
        "q2": _km("Rushden", "Peterborough Sports", "2026-09-19T14:00:00Z", 2, stage="qualifying", hs=3, as_=1),
        "p1": _km("Burton", "Rushden", "2026-11-07T15:00:00Z", "r1"),
        "p1b": _km("Gamma", "Delta", "2026-11-07T15:00:00Z", "r1"),
    }}
    cs.normalize_knockout_rounds(store, cfg)
    stage = {g: (m["stage"], m["round"]) for g, m in store["matches"].items()}
    assert stage["q1"][0] == stage["q1b"][0] == stage["q2"][0] == "qualifying"
    assert stage["p1"] == stage["p1b"] == ("playoff", "r1")


def test_a_bracket_that_skips_a_real_round_keeps_only_the_rounds_after_it() -> None:
    """The Copa do Brasil has five early rounds and the configured bracket three: the third round's winners are not
    the round of 16's clubs, so the early rounds stay off the bracket."""
    from oddsmarkets.football.competitions.cup import store as cs

    cfg = _cup((("r1", 1), ("r2", 1), ("r16", 2), ("qf", 2)))
    ms = {"a": _km("A", "B", "2026-02-18T22:00:00Z", "r1", hs=1, as_=0),
          "b": _km("A", "C", "2026-03-04T22:00:00Z", 2, stage="qualifying", hs=2, as_=0)}
    for i in range(8):
        ms[f"r16_{i}"] = _km(f"T{2 * i}", f"T{2 * i + 1}", "2026-08-01T22:00:00Z", "r16")
    store = {"matches": ms}
    cs.normalize_knockout_rounds(store, cfg)
    assert store["matches"]["a"]["stage"] == store["matches"]["b"]["stage"] == "qualifying"
    assert all(store["matches"][f"r16_{i}"]["stage"] == "playoff" for i in range(8))


def test_postponed_and_cancelled_copies_are_not_legs() -> None:
    """A postponed copy of a fixture played under another id kept the tie open (Everton 1-0 Wolves simulated again, its
    pair read Everton v Everton); a cancelled tie made its clubs reach the round twice (CONCACAF 2026)."""
    from oddsmarkets.football.competitions.cup import store as cs

    store = {"matches": {
        "pp": _km("Everton", "Wolves", "2026-09-09T18:45:00Z", "r3", status="postponed"),
        "ok": _km("Everton", "Wolves", "2026-09-16T18:45:00Z", "r3", hs=1, as_=0),
        "cx": _km("Forge", "San Miguelito", "2026-02-03T00:00:00Z", "r1", status="canceled"),
        "l1": _km("San Miguelito", "LA Galaxy", "2026-02-20T00:00:00Z", "r1", hs=1, as_=1),
        "l2": _km("LA Galaxy", "San Miguelito", "2026-02-26T00:00:00Z", "r1", hs=0, as_=0, agg_winner="LA Galaxy"),
        "two1": _km("X", "Y", "2026-02-20T00:00:00Z", "r1", hs=1, as_=0),
        "two2": _km("Y", "X", "2026-02-27T00:00:00Z", "r1", status="postponed"),
    }}
    results, pairs = cs.tie_results(list(cs.iter_matches(store)))
    assert results[frozenset(("Everton", "Wolves"))] == "Everton" and ("Everton", "Wolves") in pairs["r3"]
    assert results[frozenset(("LA Galaxy", "San Miguelito"))] == "LA Galaxy"
    assert not any("Forge" in p for p in pairs["r1"])
    assert frozenset(("X", "Y")) not in results                 # a postponed second leg still keeps the tie open


def test_top_flight_membership_is_the_league_s_clubs_not_the_country() -> None:
    """team_league comes from the country code, so every English club counted as Premier League and the FA Cup showed
    Burton Albion 15% to win before the top flight entered (accuracy audit, 22 Oct 2026)."""
    from types import SimpleNamespace

    import scripts.build_site_all as b

    dom = SimpleNamespace(family="domestic")
    early = SimpleNamespace(teams=["Burton Albion", "Bury FC"], team_league={"Burton Albion": "premier-league", "Bury FC": "premier-league"})
    later = SimpleNamespace(teams=["Burton Albion", "Arsenal"], team_league={"Burton Albion": "premier-league", "Arsenal": "premier-league"})
    top = {"premier-league": {"Arsenal", "Chelsea"}}
    assert b.cup_field_partial(dom, early, top) is True
    assert b.cup_field_partial(dom, later, top) is False
    assert b.cup_field_partial(dom, early) is False                       # the country-only reading this replaces
    assert b.cup_field_partial(dom, early, {"premier-league": set()}) is False   # clubs unknown: the country reading


def test_a_rate_never_passes_100_percent() -> None:
    """Line-ups with wonTackle but no totalTackle summed to a season tackle success of 266.7% (Robert, FC København,
    Conference League; 71 players over 100%, accuracy audit 22 Oct 2026)."""
    from oddsmarkets.football.analytics.players import aggregate_players, paired_stats

    assert paired_stats({"wonTackle": 3}) == {"wonTackle": 3, "totalTackle": 3}
    whole = {"wonTackle": 1, "totalTackle": 2}
    assert paired_stats(whole) is whole
    store = {"matches": {"1": {"home": "A", "away": "B", "hs": 0, "as": 0, "date": "2026-10-01T18:00:00Z"},
                         "2": {"home": "A", "away": "B", "hs": 0, "as": 0, "date": "2026-10-08T18:00:00Z"}},
             "lineups": {"1": {"7": {"n": "Seven", "t": "A", "p": "M", "s": {"minutesPlayed": 90, "wonTackle": 5}}},
                         "2": {"7": {"n": "Seven", "t": "A", "p": "M", "s": {"minutesPlayed": 90, "wonTackle": 1, "totalTackle": 3}}}},
             "players": {}, "incidents": {}}
    row = aggregate_players(store, registry="none")[0]
    assert (row["tackles"], row["tackles_won"], row["tackle_pct"]) == (8, 6, 75.0)
