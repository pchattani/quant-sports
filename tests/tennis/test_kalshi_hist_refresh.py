"""The tennis Kalshi listing refreshes incrementally (common/kalshi_listing.refresh) instead of being cached for good:
a match settled after the first fetch appears, and only the newest pages are fetched again (no network here)."""
from __future__ import annotations

import json

from oddsmarkets.tennis.research import kalshi_hist as KH


def _m(i: int, day: str) -> dict:
    return {"ticker": f"KXATPMATCH-{i}-A", "event_ticker": f"KXATPMATCH-{i}", "title": "A wins",
            "open_time": f"{day}T00:00:00Z", "close_time": f"{day}T20:00:00Z", "result": "yes", "status": "finalized"}


def test_index_refresh_picks_up_new_settlements(tmp_path, monkeypatch):
    monkeypatch.setattr(KH, "CACHE", tmp_path)
    old = [_m(i, f"2026-0{1 + i // 3}-1{i % 3}") for i in range(6)]            # Jan-Feb 2026, oldest first
    (tmp_path / "index_KXATPMATCH.json").write_text(json.dumps([dict(m, _hist=False) for m in old]), encoding="utf-8")
    assert KH.index("KXATPMATCH", refresh=False) == [dict(m, _hist=False) for m in old]   # cached, no meta: served
    new = [_m(100, "2026-10-20"), _m(101, "2026-10-21")]
    live = sorted(old + new, key=lambda m: m["close_time"], reverse=True)       # Kalshi: newest first, 2 per page
    pages = [live[k:k + 2] for k in range(0, len(live), 2)]
    calls = []

    def fake_get(path, params=None, tries=8):
        calls.append((path, params.get("cursor")))
        if path == "/historical/markets":
            return {"markets": [], "cursor": ""}
        k = int(params.get("cursor") or 0)
        return {"markets": pages[k], "cursor": str(k + 1) if k + 1 < len(pages) else ""}
    monkeypatch.setattr(KH, "_get", fake_get)
    rows = KH.index("KXATPMATCH")                                               # no meta: stale, refreshed
    assert {m["ticker"] for m in rows} == {m["ticker"] for m in old + new}
    assert rows[-1]["ticker"] == "KXATPMATCH-101-A" and rows == sorted(rows, key=lambda m: m["open_time"])
    live_calls = [c for c in calls if c[0] == "/markets"]
    assert len(live_calls) == 2                       # page 0 (new), page 1 (all known and old): the walk stops
    meta = json.loads((tmp_path / "index_KXATPMATCH.meta").read_text(encoding="utf-8"))
    assert meta["complete"] == {"hist": True, "live": True}
    calls.clear()
    assert len(KH.index("KXATPMATCH")) == 8 and not calls                     # fresh: served from the cache
