"""No look-ahead in college hockey: a game listed as played but dated after the build clock never counts (14 Nov 2026: ESPN
listed the women's Beanpot game of 13 Jan 2027 as final, 1-3, and the rating path ran to 13 Jan)."""
from datetime import date, datetime, timezone

from oddsmarkets.college import power_build as C
from oddsmarkets.college.hockey import build as HB

NOW = datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc)


def test_a_future_final_is_not_yet_played():
    assert HB._not_yet({"status": "post", "date": "2027-01-13T00:30Z"}, NOW)
    assert HB._not_yet({"status": "in", "date": "2026-11-15T01:00:00Z"}, NOW)
    assert not HB._not_yet({"status": "post", "date": "2026-11-13T23:00:00Z"}, NOW)
    assert not HB._not_yet({"status": "post", "date": "2026-11-14T10:00:00Z"}, NOW)       # within the six hours' slack
    assert not HB._not_yet({"status": "pre", "date": "2027-01-13T00:30Z"}, NOW)
    assert not HB._not_yet({"status": "post", "date": "not a date"}, NOW)


def test_load_stores_keeps_a_future_final_as_scheduled(monkeypatch):
    store = {"games": [{"id": "a", "status": "post", "date": "2026-11-07T23:00:00Z", "hs": 2, "as": 1, "res": "W"},
                       {"id": "b", "status": "post", "date": "2027-01-13T00:30Z", "hs": 1, "as": 3, "res": "L",
                        "result": {"pick": "W"}}]}
    monkeypatch.setattr(HB.D, "seasons_on_disk", lambda level: [2027])
    monkeypatch.setattr(HB.D, "load_store", lambda level, s: store)
    monkeypatch.setattr(HB.chn, "enabled", lambda: True)
    out = HB.load_stores("wch", now=NOW)
    a, b = out[2027]["games"]
    assert a["status"] == "post" and a["hs"] == 2
    assert b["status"] == "pre" and "hs" not in b and "res" not in b and "result" not in b


def test_power_snapshots_stop_at_the_build_date():
    paths = {"1": [["2026-10-29", 0.1], ["2026-11-05", 0.2], ["2026-11-12", 0.3], ["2026-11-19", 0.3], ["2027-01-13", 0.3]]}
    cands, now = C.snapshot_dates("wch", paths, [], date(2026, 11, 14))
    assert now == date(2026, 11, 12) and [c.isoformat() for c in cands] == ["2026-10-29", "2026-11-05"]
