"""
A voided or awarded match must never reach a model. Sofascore shows it with a
negative "score"; the parser turns that into no score, the season readers do
not count it as finished, and the Dixon-Coles fit refuses a training frame
that would make its likelihood non-finite instead of returning its starting
point (every team average, one line for every fixture). Discovery also refuses
a tournament from another sport.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.league.season_state import LeagueMatch as Match  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402
from oddsmarkets.sports.world_cup.models.dixon_coles import DixonColesModel  # noqa: E402


def _event(hs, as_):
    return {"id": 1, "homeTeam": {"name": "Angers"}, "awayTeam": {"name": "Nice"}, "status": {"type": "finished"},
            "homeScore": {"display": hs}, "awayScore": {"display": as_}, "roundInfo": {"round": 3}, "tournament": {"name": "Ligue 1"},
            "startTimestamp": 1788548400}


def test_a_negative_display_score_is_no_score() -> None:
    _, r = sofascore.event_record(_event(-2, -4), lambda n: n, 5)
    assert r["hs"] is None and r["as"] is None and r["status"] == "finished"
    _, r = sofascore.event_record(_event(2, 1), lambda n: n, 5)
    assert (r["hs"], r["as"]) == (2, 1)
    assert sofascore._score("3") == 3 and sofascore._score(None) is None and sofascore._score(-1) is None


def test_a_match_without_a_real_scoreline_is_not_finished() -> None:
    kw = dict(game_id="1", home_team="A", away_team="B", status="finished")
    assert Match(home_goals=1, away_goals=0, **kw).is_finished
    assert not Match(home_goals=None, away_goals=None, **kw).is_finished
    assert not Match(home_goals=-2, away_goals=-4, **kw).is_finished


def _frame(n=60, seed=1):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(8)]
    rows = []
    for k in range(n):
        h, a = rng.choice(teams, 2, replace=False)
        rows.append({"game_id": str(k), "home_team": h, "away_team": a, "home_goals": int(rng.poisson(1.4)), "away_goals": int(rng.poisson(1.1)),
                     "match_date": pd.Timestamp("2026-08-01", tz="UTC") + pd.Timedelta(days=k), "weight": 1.0})
    return pd.DataFrame(rows)


def test_the_fit_drops_negative_scores_and_still_fits() -> None:
    df = _frame()
    df.loc[3, ["home_goals", "away_goals"]] = [-2, -4]
    m = DixonColesModel(xi=0.002, ridge=1.0)
    m.fit(df)
    attacks = [v for k, v in m.params_.items() if k.startswith("attack_")]
    assert max(abs(v) for v in attacks) > 0.01                  # a real fit, not the starting point


def test_the_fit_refuses_a_non_finite_likelihood_rather_than_returning_zeros() -> None:
    df = _frame()
    df["home_xg"] = np.nan
    df["away_xg"] = np.nan
    df.loc[5, ["home_xg", "away_xg"]] = [-3.0, 0.5]              # a negative "xG" makes the likelihood non-finite
    with pytest.raises(ValueError):
        DixonColesModel(xi=0.002, ridge=1.0).fit(df)


def test_search_skips_other_sports_and_womens_editions(monkeypatch) -> None:
    payload = {"results": [
        {"type": "uniqueTournament", "entity": {"id": 2310, "name": "Billie Jean King Cup", "category": {"name": "Billie Jean King Cup", "sport": {"slug": "tennis"}}}},
        {"type": "uniqueTournament", "entity": {"id": 26768, "name": "Copa do Brasil, Feminino", "category": {"name": "Brazil", "sport": {"slug": "football"}}}},
        {"type": "uniqueTournament", "entity": {"id": 16600, "name": "Copa do Brasil", "category": {"name": "Brazil", "sport": {"slug": "volleyball"}}}},
        {"type": "uniqueTournament", "entity": {"id": 373, "name": "Copa Betano do Brasil", "category": {"name": "Brazil", "sport": {"slug": "football"}}}},
    ]}
    monkeypatch.setattr(sofascore, "get_json", lambda path, **kw: payload)
    assert sofascore.search_tournament("Copa do Brasil", "Brazil")["id"] == 373
    assert sofascore.search_tournament("King Cup", "Saudi Arabia") is None
