"""
The league/cup fetcher: an out-of-season competition's fixture list is left
alone for a day at a time (nothing within a week either side of today,
refreshed within the last day, no match live); a fixture refresh stamps the
store; and a knockout cup never has a "league" match — a round outside the
competition's bracket is a qualifying round.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

fetcher = importlib.import_module("fetch_sofascore_leagues")
from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _store(dates: list[str], refreshed: datetime | None, status: str = "finished") -> dict:
    matches = {str(i): {"home": "A", "away": "B", "date": d + "T19:00:00Z", "status": status, "hs": 1, "as": 0}
               for i, d in enumerate(dates)}
    meta = {"league": "x"}
    if refreshed is not None:
        meta["fixtures_refreshed_at"] = refreshed.strftime(STAMP)
    return {"matches": matches, "meta": meta}


def test_out_of_season_and_refreshed_today_is_dormant() -> None:
    assert fetcher.is_dormant(_store(["2026-06-11", "2026-07-19"], NOW - timedelta(hours=3)), NOW)


def test_a_fixture_within_a_week_keeps_it_active() -> None:
    assert not fetcher.is_dormant(_store(["2026-06-11", "2026-10-03"], NOW - timedelta(hours=3), status="notstarted"), NOW)
    assert not fetcher.is_dormant(_store(["2026-09-23"], NOW - timedelta(hours=3)), NOW)      # played six days ago


def test_stale_refresh_or_no_stamp_or_live_match_is_never_dormant() -> None:
    assert not fetcher.is_dormant(_store(["2026-06-11"], NOW - timedelta(hours=30)), NOW)     # refreshed too long ago
    assert not fetcher.is_dormant(_store(["2026-06-11"], None), NOW)                          # never stamped
    assert not fetcher.is_dormant(_store(["2026-06-11"], NOW - timedelta(hours=1), status="live"), NOW)
    assert not fetcher.is_dormant({"matches": {}, "meta": {"fixtures_refreshed_at": NOW.strftime(STAMP)}}, NOW)
    assert not fetcher.is_dormant(_store(["2026-06-11"], NOW - timedelta(hours=1)) | {"meta": {"fixtures_refreshed_at": "yesterday"}}, NOW)


def _event(gid: int, home: str, away: str, round_info: dict, label: str = "FA Cup") -> dict:
    return {"id": gid, "homeTeam": {"name": home, "country": {"alpha3": "ENG"}}, "awayTeam": {"name": away, "country": {"alpha3": "ENG"}},
            "status": {"type": "notstarted"}, "homeScore": {}, "awayScore": {}, "roundInfo": round_info,
            "tournament": {"name": label}, "startTimestamp": 1791000000}


def test_refresh_fixtures_stamps_the_store_and_reads_a_knockout_cup(monkeypatch) -> None:
    cfg = CUPS["fa-cup"]
    events = [
        _event(5, "Arsenal FC", "Wrexham", {"round": 3, "slug": "3rd-round"}),
        _event(6, "Chelsea", "Barnet", {"round": 1, "slug": "extra-preliminary-round", "name": "Extra Preliminary Round"}),
        _event(7, "Everton", "Hull", {"round": 7}),                                           # a bare numeric round
    ]
    monkeypatch.setattr(fetcher.sofascore, "season_events", lambda tid, sid: events)
    monkeypatch.setattr(fetcher, "normalize_cup_name", lambda name, alpha3=None: name.replace(" FC", ""))
    store = fetcher.sofascore.new_store()
    status = fetcher.refresh_fixtures(store, cfg, {"seasons": [{"season_id": 1, "name": "2026/27"}]})
    assert status["ok"] and status["matches_seen"] == 3
    m = store["matches"]
    assert m["5"]["home"] == "Arsenal" and (m["5"]["stage"], m["5"]["round"]) == ("playoff", "r3")
    assert m["6"]["stage"] == "qualifying" and m["7"]["stage"] == "qualifying"          # not in the bracket, never "league"
    stamp = store["meta"]["fixtures_refreshed_at"]
    assert (datetime.now(timezone.utc) - datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)).total_seconds() < 60
    assert store["meta"]["season_id"] == 1


def test_an_unchanged_store_is_saved_once_a_day_so_dormancy_persists() -> None:
    """Without the daily save the refresh stamp never reaches disk and dormancy lapses after a day."""
    assert fetcher.needs_heartbeat(None, NOW)                                                  # never stamped
    assert fetcher.needs_heartbeat("garbage", NOW)
    assert not fetcher.needs_heartbeat((NOW - timedelta(hours=3)).strftime(STAMP), NOW)
    assert fetcher.needs_heartbeat((NOW - timedelta(hours=fetcher.HEARTBEAT_HOURS)).strftime(STAMP), NOW)
    assert fetcher.HEARTBEAT_HOURS < fetcher.DORMANT_REFRESH_HOURS                              # saved before dormancy lapses
