"""
Argentina on the shared infrastructure (round 6, 28 October 2026): the dead re-listed fixtures that kept the
Apertura "incomplete" (and with it the Tabla Anual, the promedios and every berth empty), champions read from a
played final, the Tabla Anual as it stands, the promedio history, the official-table check, the Copa Argentina's
place drawn from the cup's own simulation, the stakes, the Race tab's table.json, the fetcher's shared record and
standings call, and the knockout bracket note.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.football.competitions.liga import tables
from oddsmarkets.football.competitions.liga.config import APERTURA, CLAUSURA, LigaConfig
from oddsmarkets.football.competitions.liga.simulator import LigaSimulator
from oddsmarkets.football.competitions.liga.store import season_state_from_store, torneo_from_store

sys.path.insert(0, str(Path(__file__).parent))
from test_liga_simulator import _FixedModel, _make_state  # noqa: E402
from test_liga_store import _build_store  # noqa: E402

ROOT = Path(__file__).parent.parent
CFG = LigaConfig(n_sims=2_000, sim_chunk=1_000, random_seed=11)


def _complete_clausura_store() -> dict:
    return _build_store(clausura_played=10_000)


# ── dead fixtures and champions ─────────────────────────────────────────────

def test_a_relisted_postponed_fixture_no_longer_keeps_the_tournament_open() -> None:
    """The 2026 Apertura: eight fixtures postponed, replayed under new ids, the old ids "postponed" for good."""
    store = _build_store(clausura_played=20)
    played = next(m for m in store["matches"].values() if m["torneo"] == APERTURA)
    store["matches"]["dead-1"] = {**played, "status": "postponed", "hs": None, "as": None}
    torneo = torneo_from_store(store, APERTURA)
    assert torneo.league_complete
    assert all(m.game_id != "dead-1" for m in torneo.remaining)


def test_a_genuinely_postponed_fixture_still_counts_as_to_play() -> None:
    store = _build_store(clausura_played=20)
    open_one = next(g for g, m in store["matches"].items() if m["torneo"] == CLAUSURA and m["status"] != "Ended")
    store["matches"][open_one]["status"] = "postponed"
    torneo = torneo_from_store(store, CLAUSURA)
    assert any(m.game_id == open_one for m in torneo.remaining)


def test_superseded_copies_are_dropped() -> None:
    store = _build_store(clausura_played=20)
    open_one = next(g for g, m in store["matches"].items() if m["torneo"] == CLAUSURA and m["status"] != "Ended")
    store["matches"][open_one].update({"status": "canceled", "superseded_by": "x"})
    torneo = torneo_from_store(store, CLAUSURA)
    assert all(m.game_id != open_one for m in torneo.remaining + torneo.finished)


def test_a_played_final_names_the_champion_and_closes_the_zone_phase() -> None:
    store = _build_store(clausura_played=0)
    store["matches"]["fin"] = {"home": "River Plate", "away": "Belgrano", "round": "final", "status": "finished",
                               "hs": 2, "as": 3, "date": "2026-05-24T18:30:00Z", "torneo": APERTURA}
    # a stale league fixture left over in the Apertura: dead once the final is played
    store["matches"]["stale"] = {"home": "Boca Juniors", "away": "Talleres", "round": 99, "status": "notstarted",
                                 "hs": None, "as": None, "date": "2026-03-01T18:00:00Z", "torneo": APERTURA}
    torneo = torneo_from_store(store, APERTURA)
    assert torneo.champion == "Belgrano"
    assert torneo.league_complete


@pytest.mark.parametrize("extra,winner", [({"winner": "River Plate"}, "River Plate"), ({"pens": [4, 2]}, "River Plate"),
                                          ({"pens": [3, 5]}, "Belgrano")])
def test_a_final_settled_on_penalties(extra, winner) -> None:
    store = _build_store(clausura_played=0)
    store["matches"]["fin"] = {"home": "River Plate", "away": "Belgrano", "round": "final", "status": "finished",
                               "hs": 1, "as": 1, "date": "2026-05-24T18:30:00Z", "torneo": APERTURA, **extra}
    assert torneo_from_store(store, APERTURA).champion == winner


# ── the Tabla Anual as it stands ────────────────────────────────────────────

def test_the_anual_table_counts_the_clausura_so_far() -> None:
    state = _make_state(played_fraction=0.4)
    now = state.anual_now()
    base = state.anual_base()
    clausura = state.clausura.records()
    for team in state.teams:
        assert now[team].points == base[team].points + clausura[team].points
        assert now[team].played == base[team].played + clausura[team].played
    order = [t for t, _ in state.anual_standings()]
    pts = [now[t].points for t in order]
    assert pts == sorted(pts, reverse=True)


def test_anual_tiebreak_is_points_goal_difference_goals_for() -> None:
    state = _make_state(played_fraction=0.6)
    rows = state.anual_standings()
    for (t1, a), (t2, b) in zip(rows, rows[1:]):
        assert (a.points, a.gd, a.gf) >= (b.points, b.gd, b.gf), (t1, t2)


# ── promedio history and the official tables ────────────────────────────────

def _store_with_ids() -> dict:
    return {"matches": {
        "1": {"home": "Boca Juniors", "away": "River Plate", "home_id": 3202, "away_id": 3211},
        "2": {"home": "Lanús", "away": "Aldosivi", "home_id": 3218, "away_id": 36836},
    }}


def test_promedio_prior_from_sofascore_is_promedios_minus_the_anual() -> None:
    store = _store_with_ids()
    store["standings"] = {"season_id": 1, "at": "2026-10-28T00:00:00Z", "blocks": [
        {"name": "Anual 2026", "rows": [{"team": "CA Lanús", "team_id": 3218, "points": 50, "matches": 30},
                                        {"team": "Boca Juniors", "team_id": 3202, "points": 57, "matches": 30}]},
        {"name": "Promedios 2026", "rows": [{"team": "CA Lanús", "team_id": 3218, "points": 160, "matches": 103},
                                            {"team": "Boca Juniors", "team_id": 3202, "points": 200, "matches": 103}]},
    ]}
    prior, info = tables.promedio_prior(store, {}, 2026)
    assert info["source"] == "sofascore"
    assert prior == {"Lanús": (110, 73), "Boca Juniors": (143, 73)}


def test_promedio_prior_falls_back_to_past_results() -> None:
    store = _store_with_ids()
    past = {
        "77826": {"year": "2025", "matches": {
            "a": {"home": "Boca Juniors", "away": "Lanús", "home_id": 3202, "away_id": 3218, "hs": 2, "as": 0,
                  "stage": "league", "status": "finished"},
            "b": {"home": "Boca Juniors", "away": "Lanús", "home_id": 3202, "away_id": 3218, "hs": 1, "as": 1,
                  "stage": "playoff", "status": "finished"},          # playoffs never count
        }},
        "57478": {"year": "2024", "matches": {
            "c": {"home": "Lanús", "away": "Boca Juniors", "home_id": 3218, "away_id": 3202, "hs": 1, "as": 1,
                  "stage": "league", "status": "finished"},
        }},
        "47647": {"year": "2023", "matches": {                      # outside the window
            "d": {"home": "Lanús", "away": "Boca Juniors", "home_id": 3218, "away_id": 3202, "hs": 5, "as": 0,
                  "stage": "league", "status": "finished"},
        }},
    }
    prior, info = tables.promedio_prior(store, past, 2026)
    assert info["source"] == "results"
    assert prior == {"Boca Juniors": (4, 2), "Lanús": (1, 2)}
    rank = tables.previous_rank(past, store, ["Boca Juniors", "Lanús", "Gimnasia Mendoza"], 2026)
    assert rank == {"Boca Juniors": 1, "Lanús": 2, "Gimnasia Mendoza": 3}


def test_compare_with_the_official_table() -> None:
    from oddsmarkets.football.competitions.liga.season_state import TeamRecord

    a, b = TeamRecord(), TeamRecord()
    a.points, a.played, b.points, b.played = 10, 4, 7, 4
    ok = tables.compare([("X", a), ("Y", b)], {"X": {"position": 1, "points": 10, "matches": 4},
                                               "Y": {"position": 2, "points": 7, "matches": 4}})
    assert ok["same_position"] == 2 and not ok["diffs"]
    bad = tables.compare([("X", a), ("Y", b)], {"X": {"position": 2, "points": 10, "matches": 4},
                                                "Y": {"position": 1, "points": 11, "matches": 5}})
    assert bad["same_position"] == 0 and len(bad["diffs"]) == 2


def test_the_anual_2025_rebuilt_from_results_matches_sofascore() -> None:
    """The validation behind the tiebreaks: the 2025 Tabla Anual from both tournaments' zone-phase results against
    Sofascore's "Anual 2025" table, club for club (skipped without the committed stores)."""
    past_p = ROOT / "docs" / "site" / "data" / "past" / "store.json"
    arch_p = ROOT / "docs" / "site" / "data" / "archive" / "store.json"
    if not past_p.exists() or not arch_p.exists():
        pytest.skip("no past/archive stores")
    past = json.loads(past_p.read_text(encoding="utf-8"))["seasons"].get("liga-argentina") or {}
    arch = json.loads(arch_p.read_text(encoding="utf-8"))["seasons"].get("liga-argentina") or {}
    if "77826" not in arch or "70268" not in past or "77826" not in past:
        pytest.skip("2025 seasons not in the stores")
    official = {r["team_id"]: r for r in arch["77826"]["standings"] if str(r["group"]).startswith("Anual")}
    acc: dict[int, list[int]] = {}
    for sid in ("70268", "77826"):
        for m in past[sid]["matches"].values():
            if m.get("stage") != "league" or m.get("status") != "finished" or m.get("hs") is None:
                continue
            for me, gf, ga in ((m["home_id"], m["hs"], m["as"]), (m["away_id"], m["as"], m["hs"])):
                a = acc.setdefault(me, [0, 0, 0, 0])
                a[0] += 3 if gf > ga else 1 if gf == ga else 0
                a[1] += gf - ga
                a[2] += gf
                a[3] += 1
    order = sorted(acc, key=lambda k: (-acc[k][0], -acc[k][1], -acc[k][2]))
    for pos, tid in enumerate(order, start=1):
        assert official[tid]["position"] == pos and official[tid]["points"] == acc[tid][0], tid
        assert official[tid]["matches"] == acc[tid][3]


# ── the simulation: the Copa Argentina's place and the stakes ───────────────

def test_the_copa_winner_is_drawn_from_the_cup_simulation() -> None:
    state = _make_state(played_fraction=0.5)
    teams = state.teams
    outsider = teams[-1]
    dist = {outsider: 0.75, "Club Outside The League": 0.25}
    res = LigaSimulator(_FixedModel(home_bias=0.2), state, cfg=CFG, copa_dist=dist).run()
    share = res.copa_winner_share
    assert share[outsider] == pytest.approx(0.75, abs=0.04)
    assert share["(outside the league)"] == pytest.approx(0.25, abs=0.04)
    # the cup winner is in the Libertadores whenever it was drawn, wherever it finishes
    assert res.p_libertadores[outsider] >= share[outsider] - 1e-9
    # the six places are always filled
    assert sum(res.p_libertadores.values()) == pytest.approx(6.0, abs=1e-6)


def test_stakes_split_the_same_seasons_by_each_result() -> None:
    state = _make_state(played_fraction=0.5)
    # date the remaining fixtures so the stakes pick the next ones
    t0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
    from dataclasses import replace
    state.clausura.remaining = [replace(m, date=t0 + timedelta(hours=i)) for i, m in enumerate(state.clausura.remaining)]
    res = LigaSimulator(_FixedModel(home_bias=0.2), state, cfg=CFG).run()
    assert res.stakes
    s = res.stakes[0]
    assert sum(s["n"]) == CFG.n_sims
    assert set(s["bands"]) == {"libertadores", "sudamericana", "relegation", "top8"}
    for o in range(3):
        if s["title"][o] is not None:
            assert sum(s["title"][o]) == pytest.approx(1.0)          # one club tops the table in every season
            assert sum(s["bands"]["libertadores"][o]) == pytest.approx(6.0)
            assert sum(s["bands"]["relegation"][o]) == pytest.approx(2.0)


# ── the build's payloads ────────────────────────────────────────────────────

def _load_build():
    spec = importlib.util.spec_from_file_location("bsl_infra", ROOT / "scripts" / "build_site_liga.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_race_table_and_bands() -> None:
    b = _load_build()
    state = _make_state(played_fraction=0.5)
    res = LigaSimulator(_FixedModel(home_bias=0.2), state, cfg=CFG).run()
    anual = b.build_anual_json(state, res, CFG)
    assert [r["pos"] for r in anual["rows"]] == list(range(1, len(state.teams) + 1))
    assert anual["rows"][0]["pts"] >= anual["rows"][-1]["pts"] and anual["rows"][0]["played"] > 16
    table = b.build_table_json(state, res, CFG, anual)
    keys = [x["key"] for x in table["bands"]]
    assert keys == ["libertadores", "continental", "relegation"]
    assert table["bands"][0]["last"] == 3 and table["bands"][1]["last"] == 9
    assert table["matches_per_team"] == 32 and table["title_key"] == "p_anual"
    probs = b.build_probs_json(state, res, CFG)
    for t in probs["teams"]:
        bd = t["bands"]
        assert bd["continental"] == pytest.approx(bd["libertadores"] + bd["sudamericana"], abs=2e-5)
    assert b.table_places(CFG) == (3, 9)


# ── the fetcher: the shared record and the standings call ───────────────────

def _load_fetcher():
    spec = importlib.util.spec_from_file_location("fetch_liga_infra", ROOT / "scripts" / "fetch_sofascore_liga.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_fetcher_keeps_the_shared_record_with_the_shoot_out() -> None:
    f = _load_fetcher()
    ev = {"id": 9, "homeTeam": {"name": "Argentinos Juniors", "id": 3216}, "awayTeam": {"name": "Belgrano", "id": 3203},
          "homeScore": {"display": 1, "penalties": 3}, "awayScore": {"display": 1, "penalties": 4}, "winnerCode": 2,
          "status": {"type": "finished"}, "startTimestamp": 1779040800,
          "roundInfo": {"slug": "semifinals", "name": "Semifinals"},
          "tournament": {"name": "Liga Profesional, Apertura"}}
    rec = f._shared_record(ev, 87913)
    assert rec["stage"] == "playoff" and rec["winner"] == "Belgrano" and rec["pens"] == [3, 4]


def test_standings_are_fetched_at_most_every_six_hours(monkeypatch) -> None:
    from oddsmarkets.football.sources import sofascore

    f = _load_fetcher()
    calls = []
    monkeypatch.setattr(sofascore, "standings_blocks", lambda tid, sid: calls.append(sid) or [{"name": "Anual 2026", "rows": []}])
    budget = sofascore.CallBudget(2)
    store: dict = {}
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    assert f.refresh_standings(store, 87913, budget=budget, now=now)
    assert not f.refresh_standings(store, 87913, budget=budget, now=now + timedelta(hours=2))
    assert f.refresh_standings(store, 87913, budget=budget, now=now + timedelta(hours=7))
    assert calls == [87913, 87913] and budget.used == 2
    # an exhausted budget makes no call
    assert not f.refresh_standings(store, 87913, budget=budget, now=now + timedelta(hours=20))
    assert len(calls) == 2


# ── the knockout note ───────────────────────────────────────────────────────

def test_knockout_note_follows_the_rounds() -> None:
    spec = importlib.util.spec_from_file_location("bsa_note", ROOT / "scripts" / "build_site_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from oddsmarkets.football.competitions.cup.config import CUPS

    assert "all at neutral grounds" in mod.knockout_note(CUPS["copa-argentina"])
    assert "two-legged" not in mod.knockout_note(CUPS["copa-argentina"]).lower()
    assert "(two legs)" in mod.knockout_note(CUPS["copa-del-rey"])
    assert "Every tie is two-legged" not in mod.knockout_note(CUPS["fa-cup"])
