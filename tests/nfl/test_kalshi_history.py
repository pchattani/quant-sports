"""Offline tests for oddsmarkets/nfl/sources/kalshi_history.py on a recorded fixture (no network).

Fixture tests/nfl/fixtures/kalshi_history_slice.json (recorded 2 Oct 2026): market payloads as the listings return
them (historical and live schemas) and a few raw candles of each schema.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from oddsmarkets.nfl.sources import kalshi_history as kh

from .conftest import fixture_path, load_fixture_json


@pytest.fixture(scope="module")
def fx():
    return load_fixture_json("kalshi_history_slice.json")


@pytest.fixture(scope="module")
def gi():
    sched = pd.read_parquet(fixture_path("schedules_slice.parquet"))
    g = sched[sched.season >= 2024].copy()
    ko = pd.to_datetime(g.gameday + " " + g.gametime.fillna("13:00"))
    g["kickoff_utc"] = ko.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return kh.GameIndex(g)


def _row(fx, gi, ticker):
    m = next(x for x in fx["markets"] if x["ticker"] == ticker)
    return kh.market_row(m, gi)


def test_live_game_market_maps_to_nflverse(fx, gi):
    r = _row(fx, gi, "KXNFLGAME-26SEP27LARDEN-DEN")
    assert r["kind"] == "game" and r["season"] == 2026
    assert r["game_id"] == "2026_03_LA_DEN" and r["team"] == "DEN"
    assert (r["away_team"], r["home_team"]) == ("LA", "DEN")
    assert r["kickoff_utc"] == datetime(2026, 9, 28, 0, 20, tzinfo=timezone.utc)  # 20:20 ET
    assert r["kickoff_source"] == "nflverse"
    assert r["result"] in ("yes", "no") and r["settlement_value"] in (0.0, 1.0)


def test_historical_game_market_old_la_code(fx, gi):
    r = _row(fx, gi, "KXNFLGAME-26JAN25LASEA-SEA")
    assert r["source"] == "historical" and r["season"] == 2025
    assert r["game_id"].startswith("2025_") and r["game_type"] == "CON"  # NFC Championship (Kalshi rules text says "divisional round")
    # Kalshi expected expiration is kickoff + 3 h
    assert r["kickoff_utc"] == r["expected_expiration_time"] - kh.KICKOFF_FROM_EXPIRY


def test_spread_total_semantics(fx, gi):
    s = _row(fx, gi, fx["spread_ticker"])
    assert s["kind"] == "spread" and s["team"] in (s["away_team"], s["home_team"])
    assert s["line"] == s["floor_strike"] and "wins by more than" in s["strike_note"]
    t = _row(fx, gi, fx["total_ticker"])
    assert t["kind"] == "total" and t["team"] is None and t["line"] == t["floor_strike"]
    assert t["game_id"] == s["game_id"] is not None


def test_win_total_ladders_both_formats(fx, gi):
    old = _row(fx, gi, "KXNFLWINS-ARI-25B-T9")        # "Over 9.5 wins", series per team
    assert old["kind"] == "wins" and old["team"] == "ARI" and old["season"] == 2025 and old["line"] == 9.5
    new = _row(fx, gi, fx["wins_new_ticker"])          # "N+ wins", event KXNFLWINS-27<TEAM>
    n = int(new["yes_sub_title"].split("+")[0])
    assert new["season"] == 2026 and new["line"] == n - 0.5 and new["team"] is not None


def test_futures_season_from_expiry_not_suffix(fx, gi):
    div = _row(fx, gi, fx["division_ticker"])          # KXNFLAFCEAST-25-* is the 2025 season
    assert div["kind"] == "division" and div["season"] == 2025
    po = _row(fx, gi, fx["playoff_ticker"])            # KXNFLPLAYOFF-26-* is the 2025 season too
    assert po["kind"] == "playoff" and po["season"] == 2025
    conf = _row(fx, gi, fx["conference_ticker"])     # KXNFLAFCCHAMP-25-DEN: the 2025 AFC title game
    assert conf["kind"] == "conference" and conf["season"] == 2025 and conf["game_id"] == "2025_21_NE_DEN"
    sb = _row(fx, gi, "KXSB-26-SEA")
    assert sb["kind"] == "champion" and sb["season"] == 2025 and sb["game_type"] == "SB"


def test_parse_candles_both_schemas(fx):
    live = kh.parse_candles("L", fx["candles_live"])
    hist = kh.parse_candles("H", fx["candles_historical"] + fx["candles_historical"][:1])  # duplicate dropped
    assert len(hist) == len(fx["candles_historical"])
    for rows in (live, hist):
        assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)
        for r in rows:
            assert set(kh.CANDLE_COLUMNS) == set(r)
            for c in ("yes_bid_close", "yes_ask_close", "price_close", "price_mean"):
                assert r[c] is None or 0.0 <= r[c] <= 1.0
            assert r["volume"] is not None and r["volume"] >= 0
    assert any(r["price_close"] is not None for r in live)
    assert any(r["yes_ask_close"] is not None for r in hist)


def test_chunks_respect_cap_and_grid():
    a = datetime(2025, 2, 12, 15, tzinfo=timezone.utc)
    b = datetime(2026, 2, 9, 3, tzinfo=timezone.utc)
    cs = kh.chunks(a, b)
    assert cs[0][1] <= a.timestamp() and cs[-1][2] >= b.timestamp() - 3600
    for _, s, e in cs:
        assert (e - s) / 3600 + 1 <= 5000
    for (_, _, e1), (_, s2, _) in zip(cs, cs[1:]):
        assert s2 == e1 + 3600


def test_fetcher_serves_cache_offline(tmp_path, fx):
    f = kh.Fetcher(cache=tmp_path, offline=True)
    path, params = "/historical/markets/X/candlesticks", {"start_ts": 1, "end_ts": 2, "period_interval": 60}
    p = f.key_path("candles", path, params)
    p.parent.mkdir(parents=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump({"body": {"candlesticks": fx["candles_historical"]}}, fh)
    assert f.get("candles", path, params)["candlesticks"] == fx["candles_historical"]
    assert f.requests == 0 and f.hits == 1
    with pytest.raises(kh.Offline):
        f.get("candles", path, {**params, "end_ts": 3})


def test_game_event_code_splits():
    d, splits = kh.parse_game_event("KXNFLGAME-26JAN25LASEA")
    assert d.date().isoformat() == "2026-01-25" and ("LA", "SEA") in splits
    assert ("JAX", "NO") in kh.parse_game_event("KXNFLGAME-25AUG17JACNO")[1]
    assert ("NYG", "NE") in kh.parse_game_event("KXNFLGAME-25DEC01NYGNE")[1]
