"""Kalshi opening quotes for the edge files (oddsmarkets/common/edge/opens.py)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.common.edge import opens as O
from oddsmarkets.common.fees import kalshi_cost


def _c(rows):
    return pd.DataFrame(rows, columns=["ticker", "ts", "bid", "ask", "vol"])


def test_parse_both_field_formats():
    old = [{"end_period_ts": 100, "yes_bid": {"close": "0.40"}, "yes_ask": {"close": "0.45"}, "volume": "3"}]
    new = [{"end_period_ts": 200, "yes_bid": {"close_dollars": "0.41"}, "yes_ask": {"close_dollars": "0.44"},
            "volume_fp": "5.00"}]
    compact = [{"end_period_ts": 300, "yes_bid": {"close": 0.42}, "yes_ask": {"close": 0.43}, "volume": None}]
    out = O.parse_candles(old, "A") + O.parse_candles(new, "A") + O.parse_candles(compact, "A")
    assert [(t, b, a) for _, t, b, a, _ in out] == [(100, 0.40, 0.45), (200, 0.41, 0.44), (300, 0.42, 0.43)]
    assert out[1][4] == 5.0 and out[2][4] == 0.0


def test_first_liquid_needs_every_selection_and_respects_the_cutoff():
    H = 3600
    c = _c([("H", 0, 0.01, 0.99, 0), ("A", 0, 0.01, 0.99, 0),      # listing seed: not liquid
            ("H", H, 0.50, 0.55, 1),                                 # home liquid, away not yet
            ("A", 2 * H, 0.44, 0.48, 1),                             # both liquid from 2h (home carried forward)
            ("H", 5 * H, 0.60, 0.62, 1), ("A", 5 * H, 0.37, 0.39, 1)])
    Q = O.EventQuotes(c, ["H", "A"])
    t, q = Q.first_at_or_after(0, 10 * H)
    assert t == 2 * H and q == {"H": (0.50, 0.55), "A": (0.44, 0.48)}
    t, q = Q.first_at_or_after(3 * H, 10 * H)       # the model's cutoff is after the listing
    assert t == 5 * H
    t, _ = Q.last_at_or_before(4 * H)
    assert t == 2 * H
    assert Q.first_at_or_after(6 * H, 10 * H) is None or Q.first_at_or_after(6 * H, 10 * H)[0] >= 6 * H


def test_stale_quotes_are_not_carried_forever():
    H = 3600
    c = _c([("H", 0, 0.50, 0.55, 1), ("A", 7 * H, 0.44, 0.48, 1)])
    Q = O.EventQuotes(c, ["H", "A"])
    assert Q.first_at_or_after(0, 10 * H) is None      # H's quote is 7 h old when A first quotes


def test_two_way_prices_and_single_market():
    q = {"H": (0.50, 0.55), "A": (0.44, 0.48)}
    px = O.two_way(q, "H", "A")
    assert px["home"][0] == pytest.approx(min(0.55, 1 - 0.44))
    assert px["away"][0] == pytest.approx(min(0.48, 1 - 0.50))
    assert px["home"][1] + px["away"][1] == pytest.approx(1.0)
    one = O.two_way({"Y": (0.30, 0.34)}, "Y", None, home_is_yes=False)   # the YES contract is the away side
    assert one["home"][0] == pytest.approx(1 - 0.30) and one["away"][0] == pytest.approx(0.34)
    assert one["home"][1] == pytest.approx(0.68)


def test_three_way_and_fee():
    q = {"h": (0.40, 0.42), "d": (0.27, 0.29), "a": (0.30, 0.32)}
    px = O.three_way(q, {"home": "h", "draw": "d", "away": "a"})
    assert sum(f for _, f in px.values()) == pytest.approx(1.0)
    assert px["home"][0] == 0.42
    assert O.dec(0.42) == pytest.approx(1 / float(kalshi_cost(0.42)))
    assert np.isnan(O.dec(1.0)) and np.isnan(O.dec(0.0))


def test_merge_into_is_idempotent(tmp_path):
    p = tmp_path / "x.parquet"
    base = pd.DataFrame({"event_id": ["e1", "e1"], "price_src": ["espn_open", "espn_open"], "model_p": [0.4, 0.6],
                         "season": [2025, 2025]})
    base.to_parquet(p, index=False)
    new = pd.DataFrame({"event_id": ["e1"], "price_src": [O.PRICE_SRC], "model_p": [0.4], "season": [2025],
                        "listing_ts": [pd.Timestamp("2025-01-01", tz="UTC")]})
    assert O.merge_into(p, new) == (0, 1)
    assert O.merge_into(p, new) == (1, 1)
    d = pd.read_parquet(p)
    assert len(d) == 3 and (d.price_src == O.PRICE_SRC).sum() == 1 and d.season.dtype == base.season.dtype
    assert O.merge_into(p, pd.DataFrame()) == (1, 0)
    assert len(pd.read_parquet(p)) == 2


def test_candles_from_dir_reads_requested_files(tmp_path):
    (tmp_path / "T1.json").write_text(json.dumps([{"end_period_ts": 1, "yes_bid": {"close": "0.1"},
                                                    "yes_ask": {"close": "0.2"}}]))
    (tmp_path / "EV.json").write_text(json.dumps({"T2": [{"end_period_ts": 2, "yes_bid": {"close": 0.3},
                                                         "yes_ask": {"close": 0.4}}]}))
    assert set(O.candles_from_dir(tmp_path)["ticker"]) == {"T1", "T2"}
    assert list(O.candles_from_dir(tmp_path, ["T1"])["ticker"]) == ["T1"]


def test_capture_reference_reads_tomorrow_for_daily_leagues():
    from datetime import datetime, timezone

    from oddsmarkets.fund.capture import reference as R

    calls = []

    class Client:
        def get(self, url):
            calls.append(url)
            ev = {"id": "1" if "dates" not in url else "2", "date": "2026-10-23T23:00Z",
                  "status": {"type": {"state": "pre"}},
                  "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": "H"}},
                                                    {"homeAway": "away", "team": {"abbreviation": "A"}}],
                                    "odds": [{"provider": {"name": "DraftKings"},
                                              "moneyline": {"home": {"close": {"odds": "-120"}, "open": {"odds": "-110"}},
                                                            "away": {"close": {"odds": "+100"}, "open": {"odds": "-110"}}}}]}]}
            return {"events": [ev, ev]}
    now = lambda: datetime(2026, 10, 22, 13, 0, tzinfo=timezone.utc)  # noqa: E731
    rows, err = R.fetch_reference(Client(), now, leagues=["basketball/nba", "football/nfl"])
    assert err == 0
    assert calls == [f"{R.SITE}/basketball/nba/scoreboard", f"{R.SITE}/basketball/nba/scoreboard?dates=20261023",
                     f"{R.SITE}/football/nfl/scoreboard"]
    ids = sorted(r["underlying_id"] for r in rows)
    assert ids == ["sport:espn:nba:1", "sport:espn:nba:2", "sport:espn:nfl:1"]     # duplicates within a poll dropped
