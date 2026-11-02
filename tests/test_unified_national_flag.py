"""oddsmarkets/football/analytics/unified.py: a club that once met a national team in a friendly stays a club.

Qatar v Fiorentina (2022), Qatar v Lazio (2022) and Mexico v Valencia (2024) sit in the international friendlies, and
every side of an international-scope match used to be flagged a national team: clubs_index.json called Fiorentina a
national team, and Home's search labelled it "National team · ITA"."""
from __future__ import annotations

from pathlib import Path

from oddsmarkets.football.analytics import unified as U


def _m(home, away, hid, aid, date):
    return {"home": home, "away": away, "home_id": hid, "away_id": aid, "date": date, "status": "finished", "hs": 1, "as": 1}


def test_a_friendly_against_a_national_team_does_not_make_a_club_national():
    u = U.Unified(Path("."), {})
    club, intl = {"scope": "club", "kind": "league"}, {"scope": "international", "kind": "international"}
    for k in range(3):
        u._club_match("serie-a", club, "1", f"s{k}", _m("Fiorentina", "Lazio", 2693, 2699, f"2026-09-0{k + 1}T18:00:00Z"), False)
    u._club_match("friendlies", intl, "2", "f1", _m("Qatar", "Fiorentina", 4777, 2693, "2022-08-03T16:00:00Z"), False)
    u._club_match("world-cup", intl, "3", "w1", _m("Qatar", "Ecuador", 4777, 4757, "2022-11-20T16:00:00Z"), False)
    assert u.clubs["2693"]["national"] is False and u.clubs["2699"]["national"] is False
    assert u.clubs["4777"]["national"] is True and u.clubs["4757"]["national"] is True
