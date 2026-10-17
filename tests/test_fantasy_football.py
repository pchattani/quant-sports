"""
The fantasy layer (oddsmarkets/football/analytics/fantasy.py), offline: scoring from match
lines, bonus by rating, Poisson expectations, fixture scaling, gameweeks, prices, the squad optimiser.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from oddsmarkets.football.analytics import fantasy as FA
from oddsmarkets.football.analytics import value as V


def _rows(lines: list[dict]) -> V.Rows:
    n = len(lines)
    F = np.zeros((n, V.NFF))
    for i, line in enumerate(lines):
        for k, v in line.get("f", {}).items():
            F[i, V.FANTASY_KEYS.index(k)] = v
    z = np.zeros(n, dtype=np.int64)
    return V.Rows(pid=np.arange(n), match=z, side=z, day=z + 740000, comp=z, sid=z, tid=z + 1, start=z + 1,
                  mins=np.array([float(x["min"]) for x in lines]), letter=np.array([FA.POS.index(x["pos"]) for x in lines]), role=z - 1,
                  rating=np.array([x.get("rt", 6.5) for x in lines]), X=np.zeros((n, V.NF)), comps=["premier-league"], comp_scope=["club"],
                  sids=["1"], current={}, m_day=np.array([740000]), m_comp=np.array([0]), m_tid=np.array([[1, 2]]),
                  m_npxg=np.array([[1.2, 0.8]]), m_goals=np.array([[2, 0]]), m_gid=np.array([1]), F=F)


def test_scoring_follows_the_fpl_rules() -> None:
    R = _rows([
        {"pos": "D", "min": 90, "f": {"g": 1, "gc": 0, "cbit": 11, "cbirt": 15}, "rt": 8.5},   # goal 6, clean sheet 4, DC 2, minutes 2, bonus 3
        {"pos": "F", "min": 70, "f": {"g": 2, "a": 1, "yc": 1}, "rt": 8.0},                     # 8 + 3 - 1 + 2 + bonus 2
        {"pos": "G", "min": 90, "f": {"sv": 7, "gc": 3}, "rt": 7.0},                            # saves 2, conceded -1, minutes 2, bonus 1
        {"pos": "M", "min": 30, "f": {"og": 1, "pm": 1, "rc": 1}, "rt": 5.0},                   # 1 - 2 - 2 - 3
        {"pos": "M", "min": 75, "f": {"gc": 0, "cbirt": 12}, "rt": 6.0},                        # 2 + clean sheet 1 + DC 2
    ])
    pos = FA.fantasy_positions(R, {})
    bonus = FA.bonus_points(R)
    assert bonus.tolist() == [3, 2, 1, 0, 0]
    assert FA.actual_points(R, pos, bonus).tolist() == [17, 14, 4, -6, 5]
    # People's letters win over the line's.
    assert FA.fantasy_positions(R, {"0": {"pos": "F"}})[0] == FA.POS.index("F")


def test_bonus_ties_share_the_higher_award() -> None:
    R = _rows([{"pos": "M", "min": 90, "rt": 8.0}, {"pos": "M", "min": 90, "rt": 8.0}, {"pos": "M", "min": 90, "rt": 7.0},
               {"pos": "M", "min": 90, "rt": 6.0}])
    assert FA.bonus_points(R).tolist() == [3, 3, 1, 0]


def test_poisson_expectations_match_simulation() -> None:
    rng = np.random.default_rng(0)
    for mu in (0.4, 1.3, 3.0):
        x = rng.poisson(mu, 200_000)
        assert FA._pois_floor_half(np.array([mu]))[0] == pytest.approx(np.floor(x / 2).mean(), abs=0.01)
        assert FA._pois_floor_third(np.array([mu]))[0] == pytest.approx(np.floor(x / 3).mean(), abs=0.01)


def test_projection_moves_with_the_fixture() -> None:
    letters = np.array(["F", "D"])
    rates = {k: np.array([0.5, 0.05]) for k in ("g", "a")}
    rates.update({k: np.zeros(2) for k in ("sv", "yc", "rc", "og", "pm", "bonus", "dc")})
    args = (np.array([85.0, 90]), np.array([0.9, 0.95]), np.array([0.95, 0.98]))
    easy = FA.total(FA.project_points(letters, rates, *args, np.array([2.2, 2.2]), np.array([0.6, 0.6]), np.array([1.4, 1.4]), np.array([1.4, 1.4])))
    hard = FA.total(FA.project_points(letters, rates, *args, np.array([0.8, 0.8]), np.array([2.2, 2.2]), np.array([1.4, 1.4]), np.array([1.4, 1.4])))
    assert np.all(easy > hard)


def _fx(d, r=None, h="A", a="B"):
    return {"date": d + "T15:00:00Z", "round": r, "home": h, "away": a, "hs": None, "status": "scheduled", "stage": "league",
            "model": {"lh": 1.3, "la": 1.1}}


def test_gameweeks_by_round_with_a_rescheduled_match_and_by_week_without_rounds() -> None:
    fixtures = [_fx("2026-10-17", 7), _fx("2026-10-18", 7), _fx("2026-10-24", 8), _fx("2026-10-25", 8), _fx("2026-10-24", 3, "C", "D"),
                _fx("2026-10-10", 6)]
    gws = FA.gameweeks(fixtures, date(2026, 10, 16))
    # The past fixture is dropped; round 3's rescheduled match joins the gameweek it falls in.
    assert [g["gw"] for g in gws] == [1, 2] and len(gws[0]["fixtures"]) == 2 and len(gws[1]["fixtures"]) == 3
    assert gws[0]["label"].startswith("Round 7")
    weeks = FA.gameweeks([_fx("2026-10-17"), _fx("2026-10-18"), _fx("2026-10-21")], date(2026, 10, 16))
    assert len(weeks) == 2 and weeks[0]["label"].startswith("Week of")


def test_prices_stay_in_range_and_follow_the_score() -> None:
    letters = np.array(["G"] * 5 + ["F"] * 5)
    score = np.array([1, 2, 3, 4, 5, 1, 2, 3, 4, 5], dtype=float)
    p = FA.price_proxy(letters, score)
    assert np.all(np.diff(p[:5]) >= 0) and np.all(np.diff(p[5:]) >= 0)
    assert 4.0 <= p[:5].min() and p[:5].max() <= 6.0 and p[5:].max() <= 14.5


def test_the_squad_optimiser_respects_every_rule() -> None:
    rng = np.random.default_rng(3)
    letters = list(rng.choice(FA.POS, 120, p=[0.12, 0.33, 0.35, 0.2]))
    clubs = [int(c) for c in rng.integers(1, 21, 120)]
    prices = np.round(rng.uniform(4.0, 12.0, 120), 1)
    h5 = prices * rng.uniform(1.5, 2.5, 120)
    sq = FA.optimise_squad(letters, clubs, prices, h5, h5 / 5)
    assert sq is not None and len(sq["squad"]) == 15 and len(sq["xi"]) == 11 and sq["captain"] in sq["xi"]
    chosen = sq["squad"]
    assert prices[chosen].sum() <= FA.BUDGET + 1e-6
    for p, k in FA.SQUAD.items():
        assert sum(1 for i in chosen if letters[i] == p) == k
    assert max(np.bincount(np.array(clubs)[chosen])) <= FA.PER_CLUB
    xi = sq["xi"]
    assert set(xi) <= set(chosen)
    assert sum(1 for i in xi if letters[i] == "G") == 1 and sum(1 for i in xi if letters[i] == "D") >= 3
    greedy = FA.greedy_squad(letters, clubs, prices, h5)
    assert len(greedy) == 15 and prices[greedy].sum() <= FA.BUDGET + 1e-6
