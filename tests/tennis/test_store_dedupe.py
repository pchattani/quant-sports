"""One row per real match in the season stores (store.dedupe, store.dedupe_seasons, tn_fetch --dedupe).

The faults these guard against (found 21 Oct 2026, docs/research/tennis_edge.md 10.4): `event_for` created a second
or third event when a record's candidates tied (two events in one city in overlapping weeks), so one match sat
under an ESPN "ch" event and the WTA's and tennis-data's tour-level events; and ESPN files a late-December event
under that year while tennis-data and the WTA file it under the next, so a match sat in two seasons' stores. The
models then rated the match twice, and the second copy's prediction already knew the result."""
from __future__ import annotations

import json

from oddsmarkets.tennis import canon, store


def _rec(src, meta, rnd, date, sets, winner="a", odds=None, year=2022):
    return {"src": src, "tour": "wta", "year": year, "event": meta, "round": rnd, "date": date, "best_of": 3,
            "winner": winner, "status": "done", "sets": sets, "odds": odds, "stats": None, "live": None,
            "duration_min": None, "a": {"rank": 10 if src == "td" else None}, "b": {"rank": 40 if src == "td" else None}}


def _meta(src, name, start, end, sid=None, level=None):
    m = {"name": name, "city": "Adelaide", "start": start, "end": end, "level": level, "surface": "hard",
         "indoor": False, "tid_hint": "adelaide", "td": None, "espn": None, "wta": None}
    if sid:
        m[src] = sid
    return m


S1 = [[6, 4, None, None], [7, 6, 7, 3]]
S1_TD = [[6, 4, None, None], [7, 6, None, None]]


def _two_week_city(tmp_data):
    """Adelaide 1 and 2 in consecutive weeks: ESPN makes two events, the WTA's and tennis-data's records tie between
    them (city and overlapping dates) and each made a new event, so week one's matches sat under three events."""
    s = store.new_store("wta", 2022)
    e1 = store.event_for(s, _meta("espn", "Adelaide International", "2022-01-02", "2022-01-09", "611"), "espn")
    e2 = store.event_for(s, _meta("espn", "Adelaide International 2", "2022-01-09", "2022-01-15", "835"), "espn")
    wk1 = [("p-a", "p-b", "R32", "2022-01-04"), ("p-c", "p-d", "R32", "2022-01-04"), ("p-a", "p-c", "R16", "2022-01-06")]
    wk2 = [("p-e", "p-f", "R32", "2022-01-11"), ("p-g", "p-h", "R32", "2022-01-11")]
    for a, b, r, d in wk1:
        store.merge_record(s, _rec("espn", {}, r, d + "T05:00", S1), e1, a, b)
    for a, b, r, d in wk2:
        store.merge_record(s, _rec("espn", {}, r, d + "T05:00", S1), e2, a, b)
    w1 = store.event_for(s, _meta("wta", "Adelaide International 1", "2022-01-03", "2022-01-09", "2014", "500"), "wta")
    t1 = store.event_for(s, _meta("td", "Adelaide International 1", "2022-01-03", "2022-01-09", "1|Adelaide", "500"), "td")
    assert len({e1, e2, w1, t1}) == 4                      # the fault: the ties made new events
    for a, b, r, d in wk1:
        store.merge_record(s, _rec("wta", {}, r, d + "T05:10", S1), w1, a, b)
        store.merge_record(s, _rec("td", {}, r, d, S1_TD, odds={"ps": [1.4, 3.0]}), t1, a, b)
    return s, (e1, e2, w1, t1)


def test_dedupe_merges_events_holding_the_same_matches(tmp_data):
    s, (e1, e2, w1, t1) = _two_week_city(tmp_data)
    assert len(s["matches"]) == 3 * 3 + 2
    out = store.dedupe(s)
    assert out == {"events": 2, "matches": 6}
    assert set(s["events"]) == {t1, e2}                    # tennis-data's event survives; week two untouched
    ev = s["events"][t1]
    assert ev["level"] == "500" and ev["_espn"] == "611" and ev["_wta"] == "2014" and ev["_td"] == "1|Adelaide"
    wk1 = [m for m in s["matches"].values() if m["event"] == t1]
    assert len(wk1) == 3
    for m in wk1:
        assert m["sources"] == ["espn", "td", "wta"] and m["odds"]["ps"] == [1.4, 3.0] and m["rank1"] == 10
        assert m["sets"][1] == [7, 6, 7, 3]                # ESPN's tiebreak points survive
        assert m["id"] == store.match_id(t1, m["round"], m["p1"], m["p2"]) and m["level"] == "500"
    assert sum(1 for m in s["matches"].values() if m["event"] == e2) == 2
    assert store.dedupe(s) == {"events": 0, "matches": 0}  # idempotent
    # the absorbed events' ids now find the survivor, so the next fetch does not split it again
    assert store.event_for(s, _meta("espn", "Adelaide International", "2022-01-02", "2022-01-09", "611"), "espn") == t1
    assert store.event_for(s, _meta("wta", "Adelaide International 1", "2022-01-03", "2022-01-09", "2014"), "wta") == t1


def test_dedupe_keeps_simultaneous_events_in_one_city_apart(tmp_data):
    """Melbourne Summer Set 1 and 2 (same city, same week, different players) share no match: never merged."""
    s = store.new_store("wta", 2022)
    a = store.event_for(s, dict(_meta("wta", "Melbourne Summer Set 1", "2022-01-04", "2022-01-09", "2058"), city="Melbourne"), "wta")
    b = store.event_for(s, dict(_meta("wta", "Melbourne Summer Set 2", "2022-01-04", "2022-01-09", "2059"), city="Melbourne"), "wta")
    for i in range(4):
        store.merge_record(s, _rec("wta", {}, "R32", "2022-01-05", S1), a, f"x{i}", f"y{i}")
        store.merge_record(s, _rec("wta", {}, "R32", "2022-01-05", S1), b, f"u{i}", f"v{i}")
    assert store.dedupe(s) == {"events": 0, "matches": 0} and len(s["events"]) == 2


def test_same_match_rules():
    m = {"p1": "a", "p2": "b", "date": "2024-09-08T07:56", "round": "Q1", "sets": [[4, 6, None, None], [6, 1, None, None]]}
    assert store.same_match(m, dict(m, round="R32", date="2024-09-08T08:05"))               # one match, two labels
    assert store.same_match(m, dict(m, p1="b", p2="a", sets=[[6, 4, None, None], [1, 6, None, None]]))  # other orientation
    assert not store.same_match(m, dict(m, round="R32", date="2024-09-09", sets=[[6, 3, None, None], [6, 3, None, None]]))
    assert not store.same_match(m, dict(m, date="2024-09-11T08:00"))                         # too far apart
    assert not store.same_match(m, dict(m, p2="c"))
    # a retirement recorded with a trailing empty set by one source
    r = dict(m, sets=[[6, 4, None, None], [0, 0, None, None]])
    assert store.same_match(r, dict(m, sets=[[6, 4, None, None]]))
    # rows without games: the same qualifying / main-draw side only (a lucky loser meets the same player twice)
    u = {"p1": "a", "p2": "b", "date": "2024-09-08", "round": "R32", "sets": []}
    assert store.same_match(u, dict(u, round="R16"))
    assert not store.same_match(u, dict(u, round="Q2"))


def test_dedupe_folds_one_match_under_two_round_labels(tmp_data):
    """Inside one event: the WTA's Q1 and ESPN's R32 for the same match (same games, ten minutes apart) are one row
    with the WTA's label; a lucky loser's qualifying and main-draw matches against the same player stay two."""
    s = store.new_store("wta", 2024)
    e = store.event_for(s, _meta("wta", "Bucharest", "2024-09-07", "2024-09-15", "9999", "250"), "wta")
    store.merge_record(s, _rec("espn", {}, "R32", "2024-09-08T08:05", S1, year=2024), e, "a", "b")
    store.merge_record(s, _rec("wta", {}, "Q1", "2024-09-08T07:56", S1, year=2024), e, "a", "b")
    store.merge_record(s, _rec("wta", {}, "Q2", "2024-09-08T10:00", [[6, 3, None, None], [6, 2, None, None]], year=2024), e, "c", "d")
    store.merge_record(s, _rec("wta", {}, "R32", "2024-09-09T10:00", [[2, 6, None, None], [6, 2, None, None], [6, 4, None, None]],
                               year=2024), e, "c", "d")
    assert len(s["matches"]) == 4
    assert store.dedupe(s) == {"events": 0, "matches": 1}
    ab = [m for m in s["matches"].values() if {m["p1"], m["p2"]} == {"a", "b"}]
    assert len(ab) == 1 and ab[0]["round"] == "Q1" and ab[0]["level"] == "q" and ab[0]["sources"] == ["espn", "wta"]
    assert len([m for m in s["matches"].values() if {m["p1"], m["p2"]} == {"c", "d"}]) == 2


def _season(year, eid_tid, start, end, rows, src):
    s = store.new_store("wta", year)
    meta = {"name": "Shenzhen Open", "city": "Shenzhen", "start": start, "end": end, "level": "250", "surface": "hard",
            "indoor": False, "tid_hint": eid_tid, src: "367"}
    e = store.event_for(s, meta, src)
    for a, b, r, d, sets in rows:
        store.merge_record(s, _rec(src, {}, r, d, sets, year=year), e, a, b)
    return s, e


def test_dedupe_seasons_moves_new_year_copies_to_the_later_season(tmp_data, tn_fetch):
    """ESPN filed Shenzhen (from 30 Dec 2018) under 2018; tennis-data and the WTA under 2019: both stores held the
    first-round matches (shenzhen-2018-R32-1371-824 and shenzhen-2019-R32-1371-824, both dated 30 Dec 2018)."""
    rows = [("1371", "824", "R32", "2018-12-30", S1), ("1", "2", "R32", "2018-12-31", S1)]
    prev, pe = _season(2018, "shenzhen", "2018-12-30", "2019-01-05", [(a, b, r, d + "T03:00", s) for a, b, r, d, s in rows], "espn")
    store.merge_record(prev, _rec("espn", {}, "R32", "2018-05-02", S1, year=2018),
                       store.event_for(prev, dict(_meta("espn", "Rabat", "2018-04-30", "2018-05-05", "1"), city="Rabat"), "espn"),
                       "x", "y")
    cur, ce = _season(2019, "shenzhen", "2018-12-30", "2019-01-05", [(a, b, r, d, S1_TD) for a, b, r, d, s in rows], "td")
    assert store.dedupe_seasons(prev, cur) == 2
    assert pe not in prev["events"] and len(prev["matches"]) == 1          # the emptied event goes, Rabat stays
    assert len(cur["matches"]) == 2
    for m in cur["matches"].values():
        assert m["event"] == ce and m["sources"] == ["espn", "td"] and m["sets"][1] == [7, 6, 7, 3]
    assert store.dedupe_seasons(prev, cur) == 0
    # the same through the fetcher's on-disk repair (no fetching), both directions
    prev2, _ = _season(2018, "shenzhen", "2018-12-30", "2019-01-05", [(a, b, r, d + "T03:00", s) for a, b, r, d, s in rows], "espn")
    cur2, _ = _season(2019, "shenzhen", "2018-12-30", "2019-01-05", [(a, b, r, d, S1_TD) for a, b, r, d, s in rows], "td")
    store.save(prev2)
    store.save(cur2)
    canon.Registry("wta").save()
    from datetime import date
    tn_fetch.repair("wta", [2018, 2019], date(2026, 10, 21))
    on_disk = {y: json.loads(store.store_path("wta", y).read_text(encoding="utf-8")) for y in (2018, 2019)}
    assert len(on_disk[2018]["matches"]) == 0 and len(on_disk[2019]["matches"]) == 2
