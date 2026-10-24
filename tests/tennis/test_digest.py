"""The Ace overview's "This week in tennis" digest (oddsmarkets/tennis/analytics/site.py digest): the featured match
on the shared significance rule never a 50/50 minor match at 03:00, the race when only small events are on, and the
week's record, upset and player of the week from pre-match chances."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.tennis.analytics import site as SI

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
EVENTS = {"shanghai-2026": {"name": "Rolex Shanghai Masters", "level": "m1000", "surface": "hard", "start": "2026-10-05", "end": "2026-10-18", "status": "live"},
          "almaty-2026": {"name": "Almaty Open", "level": "250", "surface": "hard", "start": "2026-10-13", "end": "2026-10-19", "status": "live"},
          "paris-2026": {"name": "Rolex Paris Masters", "level": "m1000", "surface": "hard", "start": "2026-10-26", "end": "2026-11-01", "status": "upcoming"},
          "finals-2026": {"name": "Nitto ATP Finals", "level": "finals", "surface": "hard", "start": "2026-11-08", "end": "2026-11-15", "status": "upcoming"}}


def card(mid, event, rnd, date, p1, p2, p, status="upcoming", winner=None, sets=None):
    return {"id": mid, "event": event, "round": rnd, "date": date, "status": status, "p1": p1, "p2": p2, "winner": winner,
            "sets": sets or [], "model": {"p1": p}, "wp_now": None}


def test_featured_prefers_the_masters_match_over_a_minor_coin_flip_at_3am():
    cards = [card("almaty-R32-a-b", "almaty-2026", "R32", "2026-10-18T07:00", "a", "b", 0.50),       # 03:00 New York, 09:00 Paris
             card("shanghai-SF-c-d", "shanghai-2026", "SF", "2026-10-17T19:30", "c", "d", 0.68)]   # 15:30 New York
    dig, _ = SI.digest("atp", cards, EVENTS, None, None, NOW)
    ids = [r["id"] for r in dig["featured"]["today"]]
    assert ids == ["shanghai-SF-c-d"]
    assert "a semi-final" in dig["featured"]["today"][0]["why"]


def test_race_leads_when_only_small_events_are_on():
    """Only 250 early rounds: nothing scores enough to lead, today or this week, so the front end shows the race."""
    cards = [card("almaty-R32-a-b", "almaty-2026", "R32", "2026-10-17T18:00", "a", "b", 0.51),
             card("almaty-R16-e-f", "almaty-2026", "R16", "2026-10-18T17:00", "e", "f", 0.49)]
    dig, _ = SI.digest("atp", cards, EVENTS, None, None, NOW)
    assert dig["featured"]["today"] == [] and dig["featured"]["week"] is None


def test_tba_and_walkovers():
    """A date-only match has no known hour, so it never leads; a walkover is no match and never counts."""
    cards = [card("shanghai-F-c-d", "shanghai-2026", "F", "2026-10-18", "c", "d", 0.5),
             card("shanghai-QF-x-y", "shanghai-2026", "QF", "2026-10-15T08:00", "x", "y", 0.2, status="wo", winner="x")]
    dig, _ = SI.digest("atp", cards, EVENTS, None, None, NOW)
    assert dig["featured"]["today"] == [] and "upset" not in dig


def test_week_record_upset_player_of_the_week_and_stage():
    s20, s02 = [[6, 3, None, None], [6, 4, None, None]], [[3, 6, None, None], [4, 6, None, None]]
    cards = [card("m1", "shanghai-2026", "R32", "2026-10-11T04:00", "a", "b", 0.70, "done", "a", s20),
             card("m2", "shanghai-2026", "R16", "2026-10-13T04:00", "a", "c", 0.65, "done", "a", s20),
             card("m3", "shanghai-2026", "QF", "2026-10-15T04:00", "a", "d", 0.25, "done", "a", s20),   # a beat d at 25%
             card("m4", "shanghai-2026", "R32", "2026-10-11T06:00", "e", "f", 0.60, "done", "f", s02),
             card("m0", "shanghai-2026", "R64", "2026-10-02T04:00", "g", "h", 0.05, "done", "g", s20)]  # older than a week
    race = {"finals_qual": {"a": 0.62, "e": 0.30}, "year_end_no1": {"a": 0.8, "z": 0.2}}
    dig, log = SI.digest("atp", cards, EVENTS, race, None, NOW)
    r = dig["record"]
    assert (r["n"], r["won"], r["upsets"], r["expected"]) == (4, 2, 2, round(0.70 + 0.65 + 0.75 + 0.60, 1)) and "by" not in r
    assert dig["upset"]["id"] == "m3" and dig["upset"]["winner"] == "a" and dig["upset"]["p"] == 0.25
    assert dig["hot"]["key"] == "a" and dig["hot"]["w"] == 3 and dig["hot"]["margin"] == 6.0
    assert "movers" not in dig                       # one snapshot only: nothing a day old to compare with
    assert list(log["finals_qual"]) == ["2026-10-17"] and log["year_end_no1"]["2026-10-17"]["z"] == 0.2
    st = dig["stage"]
    assert st["now"][0]["id"] == "shanghai-2026" and st["next_big"]["id"] == "paris-2026" and st["finals"]["id"] == "finals-2026"
    later = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
    dig2, _ = SI.digest("atp", [], EVENTS, {"finals_qual": {"a": 0.90, "e": 0.10}, "year_end_no1": {"a": 0.8, "z": 0.2}}, log, later)
    assert dig2["movers"]["metric"] == "finals_qual" and dig2["movers"]["up"][0]["key"] == "a" and dig2["movers"]["down"][0]["key"] == "e"
