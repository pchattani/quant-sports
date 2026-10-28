"""
The layer above the competitions: the pooled scale and the archive readers, on
synthetic inputs, since the real ones need Sofascore.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from oddsmarkets.football.analytics.archive import career, season_row, season_tables
from oddsmarkets.football.analytics.pool import adjust_players, build_pool, club_params, dc_score_matrix, outcome_probs


class _Pooled:
    """A stand-in for a fitted pooled Dixon-Coles model: params only."""

    def __init__(self, params):
        self.params_ = params


def _pooled():
    params = {"rho": -0.05, "home_adv": 0.25}
    clubs = {"premier-league": {"Strong": (0.4, -0.3), "Mid": (0.0, 0.0), "Weak": (-0.3, 0.3)},
             "saudi-pro-league": {"Al-X": (-0.2, 0.4), "Al-Y": (-0.4, 0.5)},
             "champions-league": {"Outsider": (0.1, 0.1)}}
    for prefix, members in clubs.items():
        for club, (att, dfn) in members.items():
            params[f"attack_{prefix}:{club}"] = att
            params[f"defense_{prefix}:{club}"] = dfn
    return _Pooled(params)


# ── the pool ─────────────────────────────────────────────────────────────────

def test_score_matrix_matches_the_model_and_sums_to_one() -> None:
    from oddsmarkets.football.core import DixonColesModel

    dc = DixonColesModel()
    dc.params_ = {"attack_A": 0.3, "defense_A": -0.2, "attack_B": -0.1, "defense_B": 0.1, "home_adv": 0.2, "rho": -0.08}
    ref = dc.predict_match("A", "B", neutral=False)
    m = dc_score_matrix(0.3, -0.2, -0.1, 0.1, -0.08, home_adv=0.2)
    h, d, a = outcome_probs(m)
    assert abs(m.sum() - 1.0) < 1e-9
    assert h == pytest.approx(ref.home_win, abs=1e-9) and d == pytest.approx(ref.draw, abs=1e-9) and a == pytest.approx(ref.away_win, abs=1e-9)


def test_pool_ranks_clubs_and_derives_league_factors() -> None:
    pooled = _pooled()
    assert set(club_params(pooled)) == {("premier-league", "Strong"), ("premier-league", "Mid"), ("premier-league", "Weak"),
                                        ("saudi-pro-league", "Al-X"), ("saudi-pro-league", "Al-Y"), ("champions-league", "Outsider")}
    pool = build_pool(pooled, {"premier-league": "Premier League", "saudi-pro-league": "Saudi Pro League"}, {"champions-league": "UCL"},
                      connections={"premier-league": 40, "saudi-pro-league": 3})
    clubs = pool["clubs"]
    assert [c["team"] for c in clubs[:2]] == ["Strong", "Outsider"] or clubs[0]["team"] == "Strong"
    assert clubs[0]["rank"] == 1 and clubs[-1]["team"] == "Al-Y"
    assert all(0.3 <= c["strength"] <= 3.0 for c in clubs)
    assert clubs[0]["block"] == "Europe" and pool["leagues"]["saudi-pro-league"]["block"] == "Asia"
    # The cup-only club is in the table but not in any league's aggregate.
    assert any(c["team"] == "Outsider" and not c["in_league"] for c in clubs)
    # rated = in a followed league or with table games; rank_rated ranks those only (the cup-only Outsider is unrated)
    out = next(c for c in clubs if c["team"] == "Outsider")
    assert out["rated"] is False and out["rank_rated"] is None
    rated = [c for c in clubs if c["rated"]]
    assert [c["rank_rated"] for c in rated] == list(range(1, len(rated) + 1)) and pool["model"]["n_rated"] == len(rated)
    leagues = pool["leagues"]
    assert leagues["premier-league"]["rank"] == 1 and leagues["saudi-pro-league"]["rank"] == 2
    # Weaker defences in the Saudi league: its scoring factor is below one, the Premier League's above.
    assert leagues["saudi-pro-league"]["factor_att"] < 1.0 < leagues["premier-league"]["factor_att"]
    assert leagues["saudi-pro-league"]["connection"] == 3
    players = [{"comp": "saudi-pro-league", "goals_90": 1.0, "xa_90": 0.5}, {"comp": "premier-league", "goals_90": 1.0}]
    adjust_players(players, {s: L["factor_att"] for s, L in leagues.items()})
    assert players[0]["goals_90_adj"] < 1.0 < players[1]["goals_90_adj"]
    assert players[0]["xa_90_adj"] == pytest.approx(0.5 * leagues["saudi-pro-league"]["factor_att"], abs=1e-3)


# ── the archive ──────────────────────────────────────────────────────────────

def _archive():
    return {"players": {"12994": {
        "details": {"name": "Lionel Messi", "position": "F", "country": "ARG", "team": "Inter Miami"},
        "seasons": [
            {"tid": 242, "tname": "MLS", "sid": 2, "sname": "MLS 2025", "year": "2025", "team": "Inter Miami",
             "stats": {"appearances": 28, "minutesPlayed": 2400, "goals": 29, "assists": 19, "expectedGoals": 22.5, "rating": 8.3, "keyPasses": 80}},
            {"tid": 242, "tname": "MLS", "sid": 1, "sname": "MLS 2024", "year": "2024", "team": "Inter Miami",
             "stats": {"appearances": 19, "minutesPlayed": 1500, "goals": 20, "assists": 16, "rating": 8.4}},
            {"tid": 16, "tname": "World Cup", "sid": 3, "sname": "World Cup 2026", "year": "2026", "team": "Argentina",
             "stats": {"appearances": 7, "minutesPlayed": 600, "goals": 3, "assists": 4, "rating": 7.9}},
        ], "complete": True}},
        "seasons": {"premier-league": {"10": {"name": "Premier League 24/25", "year": "24/25", "tournament_id": 17,
                                              "standings": [{"team": "Liverpool", "position": 1, "points": 84}],
                                              "top_players": {"goals": [{"id": 1, "name": "Mohamed Salah", "team": "Liverpool", "value": 29}]}},
                                       "9": {"name": "Premier League 23/24", "year": "23/24", "tournament_id": 17, "standings": [], "top_players": {}}}},
        "season_lists": {}, "meta": {}}


def test_career_orders_seasons_and_derives_rates() -> None:
    c = career(_archive(), "12994")
    assert [s["season"] for s in c["seasons"]] == ["MLS 2024", "MLS 2025", "World Cup 2026"]
    s25 = c["seasons"][1]
    assert s25["goals"] == 29 and s25["ga_90"] == pytest.approx(48 / (2400 / 90), abs=1e-3) and s25["key_passes_90"] == pytest.approx(3.0)
    assert c["totals"]["goals"] == 52 and c["totals"]["apps"] == 54
    assert c["totals"]["rating"] == pytest.approx((8.3 * 2400 + 8.4 * 1500 + 7.9 * 600) / 4500, abs=0.01)
    assert career(_archive(), "nope") is None


def test_season_tables_are_newest_first_with_leaders() -> None:
    tables = season_tables(_archive(), "premier-league")
    assert [t["year"] for t in tables] == ["24/25", "23/24"]
    assert tables[0]["standings"][0]["team"] == "Liverpool"
    assert tables[0]["leaders"]["goals"][0]["name"] == "Mohamed Salah"


def test_season_row_handles_missing_stats() -> None:
    row = season_row({"tid": 1, "tname": "X", "year": "20/21", "stats": {}})
    assert "goals" not in row and "ga_90" not in row and row["year"] == "20/21"


# ── the pool guard (round 9) ─────────────────────────────────────────────────

def test_a_run_without_a_pooled_fit_keeps_the_last_good_pool(tmp_path) -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from build_site_global import build_global

    good = {"model": {"rho": -0.05}, "leagues": {"premier-league": {}}, "clubs": [{"team": "A"}], "updated_at": "2026-10-27T00:00:00Z"}
    (tmp_path / "pool.json").write_text(json.dumps(good), encoding="utf-8")
    assert build_global(tmp_path, [], None, None) is None
    assert json.loads((tmp_path / "pool.json").read_text(encoding="utf-8")) == good
    # a first build (nothing to keep) still writes the stub, so the page reads "no pooled fit"
    fresh = tmp_path / "fresh"
    build_global(fresh, [], None, None)
    assert json.loads((fresh / "pool.json").read_text(encoding="utf-8"))["model"] is None


def test_champions_reference_is_written_slim(tmp_path, monkeypatch) -> None:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import build_site_global as g
    ref = tmp_path / "ref.json"
    ref.write_text(json.dumps({"source": "Wikidata", "licence": "CC0 1.0", "fetched_at": "x", "competitions": {
        "premier-league": {"qid": "Q9448", "label": "Premier League", "editions": [{"season": "1992-93 FA Premier League", "year": 1992, "winner": "Manchester United F.C.", "winner_qid": "Q18656"}]},
        "empty": {"editions": []}}}), encoding="utf-8")
    monkeypatch.setattr(g, "CHAMPIONS_REF", ref)
    assert g.write_champions(tmp_path) == 1
    out = json.loads((tmp_path / "champions.json").read_text(encoding="utf-8"))
    assert out["licence"] == "CC0 1.0"
    assert out["competitions"]["premier-league"]["editions"] == [["1992-93 FA Premier League", 1992, "Manchester United F.C."]]
