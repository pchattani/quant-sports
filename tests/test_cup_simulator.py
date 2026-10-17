"""
Invariant tests for the cup simulator: swiss league phase, groups, fixed brackets.

Each round must be entered by exactly the right number of clubs, one club must
win, decided ties must be certain, and a drawn tie in the store must be the tie
the simulator plays.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from oddsmarkets.football.competitions.cup.config import (
    CHAMPIONS_LEAGUE,
    INTERCONTINENTAL_CUP,
    LIBERTADORES,
    SUDAMERICANA,
    CupConfig,
)
from oddsmarkets.football.competitions.cup.season_state import CupState
from oddsmarkets.football.competitions.cup.simulator import AVERAGE, CupSimulator
from oddsmarkets.football.competitions.league.season_state import LeagueMatch

from tests.test_liga_simulator import _FixedModel, _HomeAlwaysWins


def _sims(cfg: CupConfig, n: int = 2000) -> CupConfig:
    return replace(cfg, n_sims=n, sim_chunk=min(n, 1000))


def swiss_state(cfg: CupConfig, played_fraction: float = 0.5, seed: int = 3) -> CupState:
    """36 clubs, 8 fixtures each against drawn opponents, part played."""
    rng = np.random.default_rng(seed)
    teams = [f"C{k:02d}" for k in range(cfg.n_teams)]
    fixtures: list[LeagueMatch] = []
    for rnd in range(1, 9):
        order = rng.permutation(cfg.n_teams)
        for i in range(0, cfg.n_teams, 2):
            h, a = teams[order[i]], teams[order[i + 1]]
            fixtures.append(LeagueMatch(game_id=f"{rnd}-{i}", home_team=h, away_team=a, round_name=str(rnd)))
    split = int(len(fixtures) * played_fraction)
    finished = [
        LeagueMatch(game_id=m.game_id, home_team=m.home_team, away_team=m.away_team,
                    home_goals=int(rng.integers(0, 4)), away_goals=int(rng.integers(0, 3)),
                    round_name=m.round_name, status="finished")
        for m in fixtures[:split]
    ]
    return CupState(cfg=cfg, teams=teams, finished=finished, remaining=fixtures[split:])


def group_state(cfg: CupConfig, played_fraction: float = 0.5, seed: int = 4) -> CupState:
    rng = np.random.default_rng(seed)
    groups = {chr(65 + g): [f"G{chr(65 + g)}{k}" for k in range(cfg.group_size)] for g in range(cfg.n_groups)}
    teams = [t for m in groups.values() for t in m]
    fixtures: list[LeagueMatch] = []
    for g, members in groups.items():
        for i, h in enumerate(members):
            for j, a in enumerate(members):
                if i != j:
                    fixtures.append(LeagueMatch(game_id=f"{g}-{i}-{j}", home_team=h, away_team=a, round_name="1"))
    split = int(len(fixtures) * played_fraction)
    finished = [
        LeagueMatch(game_id=m.game_id, home_team=m.home_team, away_team=m.away_team,
                    home_goals=int(rng.integers(0, 4)), away_goals=int(rng.integers(0, 3)),
                    round_name=m.round_name, status="finished")
        for m in fixtures[:split]
    ]
    return CupState(cfg=cfg, teams=teams, finished=finished, remaining=fixtures[split:], groups=groups)


UCL = _sims(CHAMPIONS_LEAGUE)
LIB = _sims(LIBERTADORES)
SUD = _sims(SUDAMERICANA)
ICC = _sims(INTERCONTINENTAL_CUP)


@pytest.fixture(scope="module")
def ucl():
    state = swiss_state(UCL)
    return state, CupSimulator(_FixedModel(home_bias=0.25), state, cfg=UCL).run()


@pytest.fixture(scope="module")
def lib():
    state = group_state(LIB)
    return state, CupSimulator(_FixedModel(home_bias=0.25), state, cfg=LIB).run()


# ── swiss ────────────────────────────────────────────────────────────────────

def test_swiss_positions_and_bands(ucl) -> None:
    _, res = ucl
    matrix = np.array([res.p_position[t] for t in res.teams])
    assert matrix.shape == (36, 36)
    assert np.allclose(matrix.sum(axis=1), 1.0) and np.allclose(matrix.sum(axis=0), 1.0)
    assert sum(res.p_band["r16"].values()) == pytest.approx(8.0)
    assert sum(res.p_band["po"].values()) == pytest.approx(16.0)
    assert sum(res.p_band["out"].values()) == pytest.approx(12.0)


def test_swiss_round_entries_are_exact(ucl) -> None:
    _, res = ucl
    totals = {r: sum(res.p_reach[t][r] for t in res.teams) for r in UCL.round_keys}
    assert totals["po"] == pytest.approx(16.0)
    assert totals["r16"] == pytest.approx(16.0)
    assert totals["qf"] == pytest.approx(8.0)
    assert totals["sf"] == pytest.approx(4.0)
    assert totals["final"] == pytest.approx(2.0)
    assert sum(res.p_win.values()) == pytest.approx(1.0)
    for t in res.teams:
        r = res.p_reach[t]
        assert r["r16"] == pytest.approx(res.p_band["r16"][t] + r["po"] * 0.5, abs=0.1)
        assert r["r16"] >= r["qf"] >= r["sf"] >= r["final"] >= res.p_win[t] - 1e-9


def test_direct_qualifier_skips_the_playoff(ucl) -> None:
    _, res = ucl
    for t in res.teams:
        assert res.p_reach[t]["po"] == pytest.approx(res.p_band["po"][t])


def test_drawn_and_decided_ties_are_respected() -> None:
    state = swiss_state(UCL, played_fraction=1.0)
    table = [t for t, _ in state.standings()]
    ninth, twenty_fourth = table[8], table[23]
    # The store says 9th played 17th (not 24th), and 17th went through.
    seventeenth = table[16]
    state.known_pairs = {"po": [(twenty_fourth, table[15]), (table[22], table[9]), (table[21], table[10]),
                                (table[20], table[11]), (table[19], table[12]), (table[18], table[13]),
                                (table[17], table[14]), (seventeenth, ninth)]}
    state.playoff_results = {frozenset((ninth, seventeenth)): seventeenth}
    res = CupSimulator(_FixedModel(home_bias=0.25), state, cfg=UCL).run()
    assert res.p_reach[seventeenth]["r16"] == pytest.approx(1.0)
    assert res.p_reach[ninth]["r16"] == pytest.approx(0.0)
    assert sum(res.p_reach[t]["r16"] for t in res.teams) == pytest.approx(16.0)


# ── groups ───────────────────────────────────────────────────────────────────

def test_group_positions_and_bracket_counts(lib) -> None:
    state, res = lib
    for members in state.groups.values():
        matrix = np.array([res.p_group_position[t] for t in members])
        assert np.allclose(matrix.sum(axis=1), 1.0) and np.allclose(matrix.sum(axis=0), 1.0)
    assert sum(res.p_band["r16"].values()) == pytest.approx(16.0)
    assert sum(res.p_band["sud"].values()) == pytest.approx(8.0)
    totals = {r: sum(res.p_reach[t][r] for t in res.teams) for r in LIB.round_keys}
    assert totals == pytest.approx({"r16": 16.0, "qf": 8.0, "sf": 4.0, "final": 2.0})
    assert sum(res.p_win.values()) == pytest.approx(1.0)
    for t in res.teams:
        assert res.p_reach[t]["r16"] == pytest.approx(res.p_band["r16"][t])


def test_sudamericana_runners_up_face_an_outside_opponent() -> None:
    state = group_state(SUD)
    res = CupSimulator(_FixedModel(home_bias=0.25), state, cfg=SUD).run()
    totals = {r: sum(res.p_reach[t][r] for t in res.teams) for r in SUD.round_keys}
    assert totals["po"] == pytest.approx(8.0)            # the eight runners-up
    assert 8.0 < totals["r16"] < 16.0                     # group winners plus surviving runners-up
    # The outside sides that beat a runner-up go on in their place — and can win.
    assert 0.0 < res.p_win[AVERAGE] < 1.0
    assert res.p_reach[AVERAGE]["po"] == pytest.approx(8.0)
    assert totals["r16"] + res.p_reach[AVERAGE]["r16"] == pytest.approx(16.0)
    assert sum(res.p_win.values()) == pytest.approx(1.0)


# ── fixed ────────────────────────────────────────────────────────────────────

def test_fixed_bracket_with_an_external_champion() -> None:
    teams = ["Al-Ahli", "Auckland FC", "Mamelodi Sundowns", "Toluca", "PSG"]
    state = CupState(cfg=ICC, teams=teams)
    external = {"libertadores": {"Flamengo": 0.6, "Palmeiras": 0.4}}
    res = CupSimulator(_FixedModel(home_bias=0.2), state, cfg=ICC, external_champions=external).run()
    assert sum(res.p_win.values()) == pytest.approx(1.0)
    totals = {r: sum(res.p_reach[t][r] for t in res.p_reach) for r in ICC.round_keys}
    assert totals == pytest.approx({"r1": 2.0, "r2": 2.0, "derby": 2.0, "playoff": 2.0, "final": 2.0})
    assert res.p_reach["Flamengo"]["derby"] == pytest.approx(0.6, abs=0.05)
    assert res.p_reach["PSG"]["final"] == pytest.approx(1.0)


def test_fixed_bracket_forces_played_rounds() -> None:
    teams = ["Al-Ahli", "Auckland FC", "Mamelodi Sundowns", "Toluca", "PSG"]
    state = CupState(cfg=ICC, teams=teams, playoff_results={
        frozenset(("Al-Ahli", "Auckland FC")): "Al-Ahli",
        frozenset(("Mamelodi Sundowns", "Al-Ahli")): "Mamelodi Sundowns",
    })
    res = CupSimulator(_HomeAlwaysWins(), state, cfg=ICC, external_champions={"libertadores": {"Flamengo": 1.0}}).run()
    assert res.p_reach["Mamelodi Sundowns"]["playoff"] == pytest.approx(1.0)
    assert res.p_reach["Al-Ahli"]["playoff"] == pytest.approx(0.0)
    # Home always wins: Flamengo (home in the derby) then hosts the play-off and
    # reaches the final, which is at a neutral venue — a coin flip against PSG.
    assert res.p_reach["Flamengo"]["final"] == pytest.approx(1.0)
    assert res.p_reach["PSG"]["final"] == pytest.approx(1.0)
    assert res.p_win["PSG"] == pytest.approx(0.5, abs=0.05)



def test_fixed_cup_store_treats_every_match_as_a_tie() -> None:
    """Sofascore labels the Intercontinental rounds "Round 1"/"Round 2" with no knockout marker."""
    from oddsmarkets.football.competitions.cup.store import cup_state_from_store

    store = {"meta": {"season_id": 1}, "matches": {
        "1": {"home": "Al-Ahli", "away": "Auckland FC", "round": "r1", "status": "finished", "hs": 1, "as": 0,
              "stage": "playoff", "season_id": 1, "date": "2026-09-22T18:00:00Z"},
        "2": {"home": "Mamelodi Sundowns", "away": "Al-Ahli", "round": "Round 2", "status": "finished", "hs": 2, "as": 1,
              "stage": "league", "season_id": 1, "date": "2026-10-16T18:00:00Z"},
    }}
    state = cup_state_from_store(store, INTERCONTINENTAL_CUP)
    assert state.playoff_results == {
        frozenset(("Al-Ahli", "Auckland FC")): "Al-Ahli",
        frozenset(("Mamelodi Sundowns", "Al-Ahli")): "Mamelodi Sundowns",
    }
    assert state.games_played == 0
