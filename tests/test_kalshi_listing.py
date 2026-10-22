"""Incremental refresh of Kalshi's settled listings (oddsmarkets/common/kalshi_listing.py) and its use by the NFL
fetcher: new settlements appear, old pages are not fetched again. A fake API, no network."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from oddsmarkets.common import kalshi_listing as KL

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def _market(i: int, days_ago: float) -> dict:
    t = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {"ticker": f"KXGAME-{i:04d}", "event_ticker": f"KXGAME-{i:04d}", "close_time": t, "result": "yes"}


class FakeAPI:
    """Newest first, keyset cursor (the last row's ticker), like Kalshi's listings."""

    def __init__(self, rows: list[dict], per_page: int = 10):
        self.rows = rows
        self.per_page = per_page
        self.calls: list[str | None] = []

    def ordered(self) -> list[dict]:
        return sorted(self.rows, key=lambda r: (r["close_time"], r["ticker"]), reverse=True)

    def page(self, cursor: str | None) -> dict:
        self.calls.append(cursor)
        rows = self.ordered()
        start = 0 if cursor is None else next(i for i, r in enumerate(rows) if r["ticker"] == cursor) + 1
        chunk = rows[start:start + self.per_page]
        more = start + self.per_page < len(rows)
        return {"markets": chunk, "cursor": chunk[-1]["ticker"] if (chunk and more) else ""}


def _tickers(rows):
    return sorted(r["ticker"] for r in rows)


def test_first_walk_is_complete_and_a_refresh_fetches_only_the_newest_pages():
    api = FakeAPI([_market(i, 400 - i) for i in range(95)])            # 95 games, the newest 306 days ago
    rows, ok, n = KL.refresh(api.page, "markets", None, False, now=NOW)
    assert ok and n == 10 and _tickers(rows) == _tickers(api.rows)
    # nothing new: one request (the newest page is all known and long settled)
    api.calls.clear()
    assert KL.refresh(api.page, "markets", rows, ok, now=NOW)[1:] == (True, 1)
    # three new games settle: the newest page, and the next one (the first page wholly known and long settled);
    # the other eight pages are not fetched again
    api.rows += [_market(1000 + i, 0.5) for i in range(3)]
    api.calls.clear()
    rows2, ok2, n2 = KL.refresh(api.page, "markets", rows, ok, now=NOW)
    assert ok2 and n2 == 2 and api.calls[0] is None
    assert _tickers(rows2) == _tickers(api.rows)
    assert {r["ticker"] for r in rows2[:3]} == {"KXGAME-1000", "KXGAME-1001", "KXGAME-1002"}    # newest first


def test_pages_with_recent_games_are_fetched_again_and_a_late_settlement_is_found():
    api = FakeAPI([_market(i, 30 - i * 0.3) for i in range(95)])        # the newest 22 pages-worth within 14 days
    rows, ok, _ = KL.refresh(api.page, "markets", None, False, now=NOW)
    # a game that closed 10 days ago settles late: it lands on an older page, still inside the growth window
    api.rows.append(_market(5000, 10.05))
    api.calls.clear()
    rows2, ok2, n2 = KL.refresh(api.page, "markets", rows, ok, now=NOW)
    assert ok2 and "KXGAME-5000" in {r["ticker"] for r in rows2}
    assert 1 < n2 < 10                                                   # walked past the recent pages, not all


def test_an_incomplete_snapshot_is_walked_in_full_and_a_failure_marks_it_incomplete():
    api = FakeAPI([_market(i, 400 - i) for i in range(95)])
    part = api.ordered()[:20]                                            # an interrupted first fetch
    rows, ok, n = KL.refresh(api.page, "markets", part, False, now=NOW)
    assert ok and n == 10 and len(rows) == 95
    calls = {"n": 0}

    def flaky(cursor):
        calls["n"] += 1
        return api.page(cursor) if calls["n"] == 1 else None
    api.rows += [_market(2000 + i, 0.2) for i in range(12)]              # more than a page of new games
    rows2, ok2, _ = KL.refresh(flaky, "markets", rows, True, now=NOW)
    assert not ok2 and len(rows2) == 95 + 10                             # what was fetched is kept


def test_events_without_markets_count_as_old_once_known():
    ev = [{"event_ticker": f"KXEV-{i}", "markets": []} for i in range(5)]
    known = list(ev)

    def page(cursor):
        return {"events": ev, "cursor": "next"}                         # would loop forever if never stable
    rows, ok, n = KL.refresh(page, "events", known, True, now=NOW)
    assert ok and n == 1 and len(rows) == 5


def test_nfl_fetcher_settled_listing_grows_under_refresh_live(tmp_path, monkeypatch):
    from oddsmarkets.nfl.sources import kalshi_history as kh
    api = FakeAPI([_market(i, 400 - i) for i in range(25)], per_page=10)
    sent = []

    def fake_http(self, path, params):
        sent.append(dict(params))
        return api.page(params.get("cursor")), 200
    monkeypatch.setattr(kh.Fetcher, "_http", fake_http)
    params = {"series_ticker": "KXGAME", "limit": 1000}
    f = kh.Fetcher(cache=tmp_path)
    assert len(f.listing("lists", "/historical/markets", params, "markets")) == 25 and len(sent) == 3
    sent.clear()
    assert len(kh.Fetcher(cache=tmp_path).listing("lists", "/historical/markets", params, "markets")) == 25
    assert sent == []                                                    # served from the snapshot
    api.rows += [_market(900, 1.0), _market(901, 0.5)]
    # without refresh_live nothing is fetched (the old behaviour); with it the newest page is, and the new games appear
    assert len(kh.Fetcher(cache=tmp_path).listing("lists", "/historical/markets", params, "markets")) == 25
    got = kh.Fetcher(cache=tmp_path, refresh_live=True).listing("lists", "/historical/markets", params, "markets")
    # the newest page (two new games) and the next one (all known, settled long ago); the third page is not fetched
    assert len(got) == 27 and len(sent) == 2 and "cursor" not in sent[0]
    assert len(kh.Fetcher(cache=tmp_path, offline=True).listing("lists", "/historical/markets", params, "markets")) == 27
