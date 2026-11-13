"""Round 10 (13 Nov 2026): our title chances before the first ball (events.pre_events), kept on the event page once
play begins, and nothing after the start on a played match (rankings going in, the serve/return checkpoint)."""
import json
from datetime import date, timedelta

import pytest

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis.analytics import events as EV
from oddsmarkets.tennis.analytics import matches as MT


def test_pre_event_chances_use_nothing_from_the_event(ace_world):
    eid = ace_world["live_event"]
    td = an.TourData("atp", ace_world["today"])
    pres = EV.pre_events(td, 2026)
    pre = pres[eid]
    start = date.fromisoformat(td.events(2026)[eid]["start"])
    assert pre["asof"] == start.isoformat()                 # the day the event began; only matches before it enter
    assert set(pre["title"]) == set(ace_world["order"][:8])  # the eight in the draw, no one fixed through
    assert sum(pre["title"].values()) == pytest.approx(1.0, abs=2e-3)
    assert pre["n_sims"] == EV.PRE_SIMS and "qualifier" not in pre
    # the strongest player going in is our favourite
    assert max(pre["title"], key=pre["title"].get) == ace_world["order"][0]
    # the page carries it
    ms = [m for m in td.matches(2026).values() if m["event"] == eid]
    page = EV.build_event(td, eid, 2026, MT.predictions(td, ms), None, None, EV.history(td))
    assert page["pre"]["title"] == pre["title"]
    # turn every result of the event over: the chances before the first ball do not move
    path = ace_world["data"] / "atp" / "2026" / "store.json"
    st = json.loads(path.read_text(encoding="utf-8"))
    flipped = 0
    for m in st["matches"].values():
        if m["event"] == eid and m["status"] == "done":
            m["winner"] = m["p2"] if m["winner"] == m["p1"] else m["p1"]
            m["sets"] = [[b, a] + s[2:] for a, b, *s in [list(x) for x in m["sets"]]]
            flipped += 1
    assert flipped >= 4
    path.write_text(json.dumps(st), encoding="utf-8")
    for f in (ace_world["cache"] / "ace_pre_event").glob("*.json"):
        f.unlink()                                          # recomputed from the changed store, not read back
    td2 = an.TourData("atp", ace_world["today"])
    again = EV.pre_events(td2, 2026)[eid]
    assert again["title"] == pre["title"]


def test_pre_event_chances_are_cached_and_left_out_until_the_event_begins(ace_world):
    eid = ace_world["live_event"]
    td = an.TourData("atp", ace_world["today"])
    first = EV.pre_events(td, 2026)[eid]
    assert (ace_world["cache"] / "ace_pre_event" / f"atp-{an.fname(eid)}.json").exists()
    td_b = an.TourData("atp", ace_world["today"])
    assert EV.pre_events(td_b, 2026)[eid] == first          # the second build reads it back unchanged
    # before the first ball there is no pre-event block: the live simulation is the pre-event forecast
    early = an.TourData("atp", date.fromisoformat(td.events(2026)[eid]["start"]) - timedelta(days=1))
    ev = dict(early.events(2026)[eid], id=eid, status="upcoming")
    ms = [dict(m, status="upcoming", winner=None, sets=[]) for m in early.matches(2026).values() if m["event"] == eid]
    assert EV._pre_setup(early, ev, ms, 100) is None


def test_qualifiers_are_unknown_before_the_first_ball():
    d = {"size": 4, "slots": [[1, "a", 1, None], [2, "q1", None, None], [3, "b", None, None], [4, None, None, "Q"]]}
    ms = [{"round": "Q2", "p1": "q1", "p2": "x"}, {"round": "R16", "p1": "a", "p2": "q1"}]
    draw, tbd = EV.pre_event_draw(d, ms)
    assert [s[1] for s in draw["slots"]] == ["a", None, "b", None]
    assert draw["slots"][1][3] == "Q" and tbd == {"q1": "tbd:2"}


def test_a_played_match_carries_the_rankings_going_in(ace_world):
    eid = ace_world["live_event"]
    td = an.TourData("atp", ace_world["today"])
    ms = [m for m in td.matches(2026).values() if m["event"] == eid]
    page = EV.build_event(td, eid, 2026, MT.predictions(td, ms), None, None, EV.history(td))
    cards = page["draw"]["matches"]
    done = [c for c in cards.values() if c["status"] == "done"]
    up = [c for c in cards.values() if c["status"] == "upcoming"]
    rank = ace_world["rank"]
    assert done and all(c["rk"] == [rank[c["p1"]], rank[c["p2"]]] for c in done)
    assert up and all("rk" not in c for c in up)


def test_a_finished_match_without_a_prediction_never_uses_todays_fit(ace_world, monkeypatch):
    td = an.TourData("atp", ace_world["today"])
    done = next(m for m in td.matches(2026).values() if m["event"] == ace_world["live_event"] and m["status"] == "done")
    seen = []
    real = td.sr_fit
    monkeypatch.setattr(td, "sr_fit", lambda through: seen.append(through) or real(through))
    MT.build_match(td, done, None)
    assert seen and max(seen) < date.fromisoformat(done["date"][:10])
