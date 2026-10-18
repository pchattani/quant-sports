"""Plausible dates of birth (analytics.plausible_dob, age_at, TourData.spans / dob_from, scripts/tn_bio.py --clean):
ESPN reuses old athlete ids, so some dates belong to a different, younger player and gave negative ages."""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

from oddsmarkets.tennis import analytics as an

ROOT = Path(__file__).resolve().parents[2]


def test_plausible_dob_rules():
    today = date(2026, 10, 18)
    assert an.plausible_dob("1998-12-22", "2021-06-01", today, "2016-09-28") == "1998-12-22"
    assert an.plausible_dob("2004-06-11", "2003-02-19", today) is None          # unborn at his typical match
    assert an.plausible_dob("1999-12-20", "2009-04-22", today) is None          # aged 9 at the median match
    assert an.plausible_dob("2000-04-24", "2017-02-20", today, "2007-02-12") is None   # aged 6 at the run's start
    assert an.plausible_dob("1930-01-01", None, today) is None                  # before DOB_MIN_YEAR
    assert an.plausible_dob("2027-01-01", None, today) is None                  # in the future
    assert an.plausible_dob("not a date", None, today) is None
    assert an.plausible_dob("1990-01-01", None, today) == "1990-01-01"          # no matches: only the date checks


def test_age_at_bounds_and_since():
    assert round(an.age_at("2000-01-01", date(2026, 1, 1)), 1) == 26.0
    assert an.age_at("2000-01-01", date(2005, 1, 1)) is None                    # under AGE_MIN
    assert an.age_at("1940-01-01", date(2026, 1, 1)) is None                    # over AGE_MAX
    assert an.age_at("1998-12-22", date(2000, 6, 1), since="2016-09-28") is None
    assert an.age_at(None, date(2026, 1, 1)) is None


def _rewrite(world, fn):
    for y in (2025, 2026):
        p = world["data"] / "atp" / str(y) / "store.json"
        s = json.loads(p.read_text(encoding="utf-8"))
        fn(y, s)
        p.write_text(json.dumps(s), encoding="utf-8")


def test_tourdata_drops_impossible_dates_and_ages(ace_world):
    a, b, c = ace_world["pids"][:3]

    def edit(y, s):
        s["players"][a]["dob"] = "2020-01-01"        # a store date that makes him 5 at his matches
        s["players"][b]["dob"] = None
        s["players"][c]["dob"] = None
    _rewrite(ace_world, edit)
    (ace_world["data"] / "atp" / "bio.json").write_text(json.dumps({
        "_meta": {}, b: {"dob": "1999-05-05", "espn": b, "checked": "2026-10-01"},
        c: {"dob": "2016-01-01", "espn": c, "checked": "2026-10-01"}}), encoding="utf-8")
    td = an.TourData("atp", ace_world["today"])
    assert td.players[a]["dob"] is None and td.age(a, td.today) is None
    assert td.players[b]["dob"] == "1999-05-05" and 26 < td.age(b, td.today) < 28
    assert td.players[c]["dob"] is None
    first, typical, last, start = td.spans[b]
    assert first <= start <= typical <= last
    ages = [td.age(p, td.season_end(y)) for y in td.years for p in ace_world["pids"]]
    assert all(x is None or an.AGE_MIN <= x <= an.AGE_MAX for x in ages)


def test_spans_take_the_latest_run(ace_world):
    a = ace_world["pids"][0]

    def edit(y, s):
        if y == 2025:                                  # an older namesake: one match 20 years before (bad date too)
            m = dict(next(iter(s["matches"].values())), id="old", date="2005-03-01", p1=a)
            s["matches"]["old"] = m
            m2 = dict(m, id="stray", date="2050-01-02T23:00")    # outside the store's year: the event start counts
            s["matches"]["stray"] = m2
    _rewrite(ace_world, edit)
    td = an.TourData("atp", ace_world["today"])
    first, typical, last, start = td.spans[a]
    assert last < "2027" and start >= "2025" and typical >= "2025"
    assert first >= "2024"                             # the 2005 date is outside 2025's store year +-1: event start


def test_tn_bio_clean_nulls_rejected_dates(ace_world):
    a, b = ace_world["pids"][:2]

    def edit(y, s):
        s["players"][a]["dob"] = None
        s["players"][b]["dob"] = None
    _rewrite(ace_world, edit)
    path = ace_world["data"] / "atp" / "bio.json"
    path.write_text(json.dumps({"_meta": {}, a: {"dob": "2019-01-01", "espn": a, "checked": "2026-10-01"},
                                b: {"dob": "1995-01-01", "espn": b, "checked": "2026-10-01"}}), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("tn_bio_mod", ROOT / "scripts" / "tn_bio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    td = an.TourData("atp", ace_world["today"])
    bio = json.loads(path.read_text(encoding="utf-8"))
    out = mod.clean(td, bio, ace_world["today"])
    assert [r[0] for r in out] == [a]
    assert bio[a]["dob"] is None and bio[a]["rejected"] == "2019-01-01" and bio[b]["dob"] == "1995-01-01"
