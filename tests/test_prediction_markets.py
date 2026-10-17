"""
Prediction-market prices without a key: club names match across spellings,
Polymarket and Kalshi match lines land on the right fixture and side, thin or
one-sided quotes are skipped, and title markets map onto the table. All offline.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oddsmarkets.football.core.markets import build_outright_markets  # noqa: E402
from oddsmarkets.football.sources import prediction_markets as pm  # noqa: E402

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
FIXTURES = [
    {"id": 1, "home": "Arsenal", "away": "Leeds", "date": "2026-10-10T11:30:00Z", "status": "scheduled"},
    {"id": 2, "home": "Brighton", "away": "Manchester United", "date": "2026-10-10T14:00:00Z", "status": "scheduled"},
    {"id": 3, "home": "Leeds", "away": "Arsenal", "date": "2027-03-01T15:00:00Z", "status": "scheduled"},     # the return fixture, months away
    {"id": 4, "home": "Chelsea", "away": "Fulham", "date": "2026-09-20T14:00:00Z", "status": "finished"},
]


def _poly_line(label, bid, ask, last=None):
    return {"sportsMarketType": "moneyline", "groupItemTitle": label, "bestBid": bid, "bestAsk": ask, "lastTradePrice": last}


def _fake(monkeypatch, poly_events, kalshi_events, kalshi_title=None, poly_search=None):
    def get(url, params=None):
        if url.endswith("/sports"):
            return [{"sport": "epl", "series": "10188"}]
        if url.endswith("/events") and "gamma" in url:
            return poly_events if not params.get("offset") else []
        if url.endswith("/public-search"):
            return poly_search or {}
        if "kalshi" in url:
            return {"events": kalshi_title if params.get("series_ticker") == "KXPREMIERLEAGUE" else kalshi_events}
        return None
    monkeypatch.setattr(pm, "_get", get)
    monkeypatch.setattr(pm, "_sports_cache", None)


def test_names_match_across_spellings_and_refuse_to_guess() -> None:
    assert pm.name_score("Leeds United FC", "Leeds") > 0.9
    assert pm.name_score("Brighton & Hove Albion FC", "Brighton") > 0.9
    assert pm.name_score("Atlético Madrid", "Atletico de Madrid") > 0.9
    assert pm.best_match("Manchester United FC", ["Manchester United", "Manchester City"]) == "Manchester United"
    assert pm.best_match("Manchester", ["Manchester United", "Manchester City"]) is None       # ambiguous
    assert pm.best_match("Real Oviedo", ["Arsenal", "Leeds"]) is None


def test_match_lines_from_both_markets_land_on_the_right_fixture_and_side(monkeypatch) -> None:
    poly = [
        {"title": "Arsenal FC vs. Leeds United FC", "startTime": "2026-10-10T11:30:00Z", "markets": [
            _poly_line("Arsenal FC", 0.71, 0.72), _poly_line("Draw (Arsenal FC vs. Leeds United FC)", 0.18, 0.19), _poly_line("Leeds United FC", 0.10, 0.11)]},
        {"title": "Arsenal FC vs. Leeds United FC - Total Corners", "markets": []},                  # a side market: ignored
        {"title": "Brighton & Hove Albion FC vs. Manchester United FC", "startTime": "2026-10-10T14:00:00Z", "markets": [
            _poly_line("Brighton & Hove Albion FC", 0.40, 0.70), _poly_line("Draw", 0.25, 0.26), _poly_line("Manchester United FC", 0.30, 0.31)]},   # spread too wide, no trade
    ]
    kalshi = [{"title": "Arsenal vs Leeds United", "markets": [
        {"yes_sub_title": "Leeds United", "yes_bid_dollars": "0.11", "yes_ask_dollars": "0.12", "occurrence_datetime": "2026-10-10T11:30:00Z"},
        {"yes_sub_title": "Arsenal", "yes_bid_dollars": "0.72", "yes_ask_dollars": "0.73"},
        {"yes_sub_title": "Tie", "yes_bid_dollars": "0.17", "yes_ask_dollars": "0.18"}]}]
    _fake(monkeypatch, poly, kalshi)
    rows = pm.match_rows("premier-league", FIXTURES, now=NOW)
    assert [r["match_id"] for r in rows] == ["1"]                     # Brighton skipped; the March return fixture not confused
    books = rows[0]["books"]
    assert set(books) == {"polymarket", "kalshi"}
    assert books["polymarket"]["home"] == pytest.approx(1 / 0.715, rel=1e-3)
    assert books["kalshi"]["away"] == pytest.approx(1 / 0.115, rel=1e-3) and books["kalshi"]["draw"] == pytest.approx(1 / 0.175, rel=1e-3)


def test_a_one_sided_or_stale_quote_is_not_a_price(monkeypatch) -> None:
    poly = [{"title": "Arsenal FC vs. Leeds United FC", "startTime": "2026-10-10T11:30:00Z", "markets": [
        _poly_line("Arsenal FC", None, 0.72, 0.70), _poly_line("Draw", 0.18, 0.19), _poly_line("Leeds United FC", 0.10, 0.11)]}]
    _fake(monkeypatch, poly, [])
    assert pm.match_rows("premier-league", FIXTURES, now=NOW) == []      # no bid on the home side: the match is skipped
    assert pm._mid(None, None, 0.84) is None                            # a last trade alone is never used


def test_title_market_maps_onto_the_table_and_pools_sources(monkeypatch) -> None:
    kt = [{"title": "English Premier League Champion", "markets": [
        {"yes_sub_title": "Arsenal", "yes_bid_dollars": "0.60", "yes_ask_dollars": "0.62"},
        {"yes_sub_title": "Man City", "yes_bid_dollars": "0.19", "yes_ask_dollars": "0.20"},
        {"yes_sub_title": "Liverpool", "yes_bid_dollars": "0.07", "yes_ask_dollars": "0.08"},
        {"yes_sub_title": "Chelsea", "yes_bid_dollars": "0.04", "yes_ask_dollars": "0.05"},
        {"yes_sub_title": "Wrexham", "yes_bid_dollars": "0.01", "yes_ask_dollars": "0.02"}]}]      # not in the league
    ps = {"events": [{"slug": "epl-2027-champion-20260701", "markets": [
        {"groupItemTitle": "Arsenal", "bestBid": 0.58, "bestAsk": 0.60}, {"groupItemTitle": "Manchester City", "bestBid": 0.20, "bestAsk": 0.21}]}]}
    _fake(monkeypatch, [], [], kalshi_title=kt, poly_search=ps)
    table = ["Arsenal", "Manchester City", "Liverpool", "Chelsea", "Leeds", "Fulham"]
    prices = pm.title_prices("premier-league", "Premier League", table)
    assert set(prices) == {"Arsenal", "Manchester City", "Liverpool", "Chelsea"}
    assert 1 / prices["Arsenal"] == pytest.approx((0.61 + 0.59) / 2, abs=1e-3)       # the two markets pooled
    out = build_outright_markets(prices, {"Arsenal": 0.6, "Manchester City": 0.2, "Liverpool": 0.1, "Chelsea": 0.05, "Leeds": 0.03, "Fulham": 0.02})
    assert out["available"] and len(out["teams"]) == 4


def test_competitions_without_a_market_cost_nothing(monkeypatch) -> None:
    monkeypatch.setattr(pm, "_get", lambda *a, **k: pytest.fail("no call expected"))
    assert pm.match_rows("kings-cup", FIXTURES, now=NOW) == []
    assert pm.title_prices("kings-cup", "King's Cup", ["A"]) == {}


def test_city_names_resolve_through_the_alias_table() -> None:
    teams = ["PSV", "AZ", "Twente", "NEC", "Ajax"]
    assert [pm.best_match(n, teams) for n in ("Eindhoven", "Alkmaar", "Enschede", "Nijmegen", "Ajax")] == teams


def test_a_thin_title_market_is_not_published(monkeypatch) -> None:
    kt = [{"title": "Champion", "markets": [{"yes_sub_title": "Arsenal", "yes_bid_dollars": "0.60", "yes_ask_dollars": "0.62"}]}]
    _fake(monkeypatch, [], [], kalshi_title=kt)
    assert pm.title_prices("premier-league", "Premier League", ["Arsenal", "Chelsea", "Liverpool", "Leeds"]) == {}
