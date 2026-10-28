"""Paddock round 9 (28 Oct 2026): the Scouting Room's lab.json carries each driver-season's age."""
from oddsmarkets.f1.analytics import season as ssn


def test_season_age_is_taken_on_1_july():
    assert ssn.season_age("1998-02-15", 2026) == 28
    assert ssn.season_age("2006-08-25", 2026) == 19          # birthday after 1 July: still 19 on the day
    assert ssn.season_age("2000-07-01", 2026) == 26          # born on the day: the birthday counts
    assert ssn.season_age(None, 2026) is None and ssn.season_age("not a date", 2026) is None


def test_lab_payload_carries_age():
    cat = {"metrics": [], "drivers": {"a": {"name": "A", "team": "t", "races": 3, "values": {}},
                                      "b": {"name": "B", "team": "t", "races": 2, "values": {}}}}
    lab = ssn.lab_payload({2025: cat, 2026: cat}, 2026, dobs={"a": "2000-01-01"})
    i = lab["fields"].index("age")
    assert lab["fields"][:6] == ["driver", "name", "team", "year", "races", "age"]
    ages = {(r[0], r[3]): r[i] for r in lab["rows"]}
    assert ages[("a", 2026)] == 26 and ages[("a", 2025)] == 25 and ages[("b", 2026)] is None
    assert all(len(r) == len(lab["fields"]) for r in lab["rows"])
