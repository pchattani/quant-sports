"""Data-accuracy fixes found by the 22 October 2026 audit of the live Ace payloads (docs/ACCURACY_AUDIT.md):
walkover finals in titles, ESPN's stand-in midnight times, superseded scheduled matches, tour events losing their
tid to a Challenger / 125, exhibition entries, and the season simulation's calendar drift. No network."""
from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis import store as st


def _m(eid, rnd, p1, p2, status="done", winner=None, date_="2026-10-20", sources=("espn",), level="250", surface="hard"):
    return {"id": st.match_id(eid, rnd, p1, p2), "event": eid, "round": rnd, "p1": p1, "p2": p2, "status": status,
            "winner": winner if winner is not None else (p1 if status != "upcoming" else None), "date": date_,
            "sets": [] if status in ("upcoming", "wo") else [[6, 4, None, None], [6, 4, None, None]],
            "level": level, "surface": surface, "indoor": False, "best_of": 3, "sources": list(sources)}


def _ev(tid, year, level="250", start="2026-10-17", end="2026-10-25"):
    return {"tid": tid, "name": tid, "year": year, "start": start, "end": end, "level": level, "surface": "hard",
            "indoor": False, "draw_size": 32, "best_of": 3, "status": "live", "champion": None, "draw": None}


def _store(events, matches, year=2026, tour="atp"):
    s = st.new_store(tour, year)
    s["events"] = events
    s["matches"] = {m["id"]: m for m in matches}
    return s


# ── titles and finals count walkover finals ─────────────────────────────────────────────────────────

def test_titles_finals_count_a_walkover_final(tmp_path, monkeypatch):
    from oddsmarkets.tennis.analytics import players as PL
    monkeypatch.setenv("ACE_DATA", str(tmp_path / "ace"))
    monkeypatch.setenv("ACE_CACHE", str(tmp_path / "cache"))
    ms = [_m("dubai-2026", "F", "A", "B", status="wo", date_="2026-02-28", level="500"),     # A wins by walkover
          _m("dubai-2026", "SF", "A", "C", date_="2026-02-27", level="500"),
          _m("doha-2026", "F", "B", "A", date_="2026-02-21", surface="hard"),                  # A loses a played final
          _m("doha-2026", "Q1", "A", "Z", date_="2026-02-14", level="q")]
    s = _store({"dubai-2026": _ev("dubai", 2026, "500"), "doha-2026": _ev("doha", 2026)}, ms)
    p = tmp_path / "ace" / "atp" / "2026" / "store.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(s), encoding="utf-8")
    td = an.TourData("atp", date(2026, 10, 22))
    tf = PL.titles_finals(td, 2026)
    assert tf["A"]["all"] == [1, 2] and tf["B"]["all"] == [1, 2] and "C" not in tf
    # the season summary (careers) takes them; without them it counts only the played final
    E = [{"won": False, "round": "F", "surface": "hard"}, {"won": True, "round": "SF", "surface": "hard"}]
    assert PL.season_summary(E)["titles"] == 0 and PL.season_summary(E)["finals"] == 1
    row = PL.season_summary(E, tuple(tf["A"]["all"]))
    assert row["titles"] == 1 and row["finals"] == 2 and row["w"] == 1 and row["l"] == 1
    v, nn = {}, {}
    PL._apply_titles(v, nn, tf["A"]["all"])
    assert v == {"titles": 1, "finals": 2, "final_win_pct": 0.5} and nn["finals"] == 2


# ── ESPN times ───────────────────────────────────────────────────────────────────────────────────────

def test_espn_time_not_valid_keeps_the_date_only():
    from oddsmarkets.tennis.sources import espn
    raw = json.load(gzip.open(Path(__file__).parent / "fixtures" / "espn_atp_20260925.json.gz", "rt", encoding="utf-8"))
    timed = espn.parse_scoreboard(raw, "atp")
    assert timed and all(r["date"] is None or len(r["date"]) == 16 for r in timed)
    for ev in raw["events"]:
        for g in ev.get("groupings") or []:
            for c in g.get("competitions") or []:
                c["timeValid"] = False
    plain = espn.parse_scoreboard(raw, "atp")
    assert plain and all(r["date"] is None or len(r["date"]) == 10 for r in plain)
    assert {r["date"] for r in plain} <= {r["date"][:10] if r["date"] else None for r in timed}


def test_merge_replaces_the_stand_in_midnight():
    old = {"id": "m", "date": "2026-10-22T04:00", "status": "upcoming", "sources": ["espn"], "p1": "a", "p2": "b"}
    # ESPN now has the start time
    new = dict(old, date="2026-10-22T11:40")
    assert st._merge_match(old, new)["date"] == "2026-10-22T11:40"
    # ESPN says the time is not known (timeValid false): the stand-in midnight goes
    assert st._merge_match(old, dict(old, date="2026-10-22"))["date"] == "2026-10-22"
    # ... but a real time is not cleared, nor a stand-in on another day
    real = dict(old, date="2026-10-22T09:10")
    assert st._merge_match(real, dict(old, date="2026-10-22"))["date"] == "2026-10-22T09:10"
    assert st._merge_match(old, dict(old, date="2026-10-23"))["date"] == "2026-10-22T04:00"
    # the WTA's time stamps do not override a stored time; a fold of two stored rows keeps the first
    assert st._merge_match(real, dict(old, date="2026-10-22T07:45", sources=["wta"]))["date"] == "2026-10-22T09:10"
    assert st._merge_match(real, dict(old, date="2026-10-22T07:45", sources=["espn", "td"]))["date"] == "2026-10-22T09:10"
    # a timestamp still beats a plain date, and a 1900 date is still refused
    assert st._merge_match(dict(old, date="2026-10-22", sources=["td"]), real)["date"] == "2026-10-22T09:10"
    assert st._merge_match(dict(old, date="2007-01-15", sources=["td"]), dict(old, date="1900-01-03T05:00"))["date"] == "2007-01-15"


# ── superseded scheduled matches, exhibition rows, tids ─────────────────────────────────────────────

def test_superseded_scheduled_matches_are_dropped():
    e = "brussels-2026"
    ms = [_m(e, "R32", "A", "B", status="upcoming", date_="2026-10-19"),     # A met C instead: provisional pairing
          _m(e, "R32", "A", "C", date_="2026-10-20"),
          _m(e, "R16", "D", "E", date_="2026-10-21"),
          _m(e, "R32", "D", "F", status="upcoming", date_="2026-10-19"),     # D has already played the next round
          _m(e, "QF", "A", "D", status="upcoming", date_="2026-10-23"),      # the real next match: kept
          _m(e, "R32", "G", "H", status="upcoming", date_="2026-10-23"),     # nobody has moved past it: kept
          _m(e, "RR", "A", "G", status="upcoming")]                          # round robin: never judged
    s = _store({e: _ev("brussels", 2026)}, ms)
    assert st.drop_superseded(s) == 2
    left = {(m["round"], m["p1"], m["p2"]) for m in s["matches"].values()}
    assert ("R32", "A", "B") not in left and ("R32", "D", "F") not in left
    assert {("QF", "A", "D"), ("R32", "G", "H"), ("RR", "A", "G"), ("R32", "A", "C")} <= left


def test_finalize_drops_exhibition_rows_and_wta_skips_them():
    from oddsmarkets.tennis.sources import wta
    e = "rovereto-2026"
    s = _store({e: _ev("rovereto", 2026, "ch")}, [_m(e, "R32", "x:ivan", "x:silviu", status="upcoming"),
                                                   _m(e, "R32", "P", "Q")], tour="wta")
    s["players"] = {"x:ivan": {"name": "Ivan", "wta": "EXW0000015"}, "x:silviu": {"name": "Silviu", "wta": "EXW0000016"},
                    "P": {"name": "P", "wta": "1"}, "Q": {"name": "Q", "wta": "2"}}
    st.finalize_events(s, date(2026, 10, 22))
    assert [m["p1"] for m in s["matches"].values()] == ["P"]
    row = {"PlayerIDA": "EXW0000015", "PlayerNameFirstA": "Ivan", "PlayerNameLastA": "Tratter"}
    assert wta._side(row, "A") is None
    assert wta._side(dict(row, PlayerIDA="320301"), "A")["wta"] == "320301"


def test_tour_event_takes_the_plain_tid_back():
    evs = {"madrid-2026": _ev("madrid", 2026, "ch", "2026-04-05", "2026-04-12"),
           "madrid-2-2026": _ev("madrid-2", 2026, "m1000", "2026-04-20", "2026-05-03"),
           "lyon-2-2026": _ev("lyon-2", 2026, "250"),
           "adelaide-2026": _ev("adelaide", 2026, "250", "2026-01-05", "2026-01-11"),
           "adelaide-2-2026": _ev("adelaide-2", 2026, "250", "2026-01-12", "2026-01-18")}
    ms = [_m("madrid-2-2026", "F", "A", "B", level="m1000"), _m("madrid-2026", "F", "C", "D", level="ch"),
          _m("lyon-2-2026", "R32", "E", "F")]
    s = _store(evs, ms)
    assert st.prefer_tour_tids(s) == 2
    assert s["events"]["madrid-2026"]["level"] == "m1000" and s["events"]["madrid-3-2026"]["level"] == "ch"
    assert "lyon-2026" in s["events"] and "lyon-2-2026" not in s["events"]
    assert "adelaide-2-2026" in s["events"]                    # two tour events in one city: both kept as they are
    ids = set(s["matches"])
    assert st.match_id("madrid-2026", "F", "A", "B") in ids and st.match_id("madrid-3-2026", "F", "C", "D") in ids
    assert st.match_id("lyon-2026", "R32", "E", "F") in ids
    assert all(m["event"] in s["events"] for m in s["matches"].values())
    assert st.prefer_tour_tids(s) == 0                          # idempotent


# ── the season simulation's calendar ─────────────────────────────────────────────────────────────────

def test_calendar_drift_whole_weeks():
    from oddsmarkets.tennis.models import season_sim as S
    prev = {f"{t}-2025": {"tid": t, "level": "250", "start": s} for t, s in
            (("beijing", "2025-09-24"), ("tokyo", "2025-09-24"), ("shanghai", "2025-08-31"), ("almaty", "2025-10-11"),
             ("brussels", "2025-10-11"), ("basel", "2025-10-18"))}
    cur = {f"{t}-2026": {"tid": t, "level": "250", "start": s} for t, s in
           (("beijing", "2026-09-30"), ("tokyo", "2026-09-30"), ("shanghai", "2026-10-05"), ("almaty", "2026-10-17"),
            ("brussels", "2026-10-16"))}
    assert S.calendar_drift(cur, prev, date(2026, 10, 22)) == 7          # outlier (Shanghai) ignored by the median
    assert S.calendar_drift({}, prev, date(2026, 10, 22)) == 0
    far = {k: dict(v, start="2026-12-30") for k, v in cur.items()}
    assert S.calendar_drift(far, prev, date(2026, 12, 31)) == 14         # capped at two weeks


def test_unlisted_events_follow_the_drift_and_past_ones_are_dropped():
    """2026 runs a week behind 2025 + 364: Basel / Vienna (not listed yet) go to the week after Almaty and before
    Paris, not into Paris's week; Stockholm, whose week is under way without it, is not simulated."""
    import numpy as np
    from oddsmarkets.tennis.models import season_sim as S

    def ev(tid, year, start, end, level="250", status="done"):
        return {"tid": tid, "year": year, "start": start, "end": end, "level": level, "draw_size": 32, "status": status,
                "surface": "hard", "best_of": 3, "draw": None}
    prev = {"events": {f"{t}-2025": ev(t, 2025, s0, e0, lv) for t, s0, e0, lv in (
        ("beijing", "2025-09-24", "2025-10-01", "500"), ("tokyo", "2025-09-24", "2025-09-30", "500"),
        ("almaty", "2025-10-11", "2025-10-19", "250"), ("stockholm", "2025-10-11", "2025-10-19", "250"),
        ("basel", "2025-10-18", "2025-10-26", "500"), ("vienna", "2025-10-18", "2025-10-26", "500"),
        ("paris", "2025-10-25", "2025-11-02", "m1000"))}, "matches": {}}
    cur = {"events": {f"{t}-2026": ev(t, 2026, s0, e0, lv) for t, s0, e0, lv in (
        ("beijing", "2026-09-30", "2026-10-07", "500"), ("tokyo", "2026-09-30", "2026-10-06", "500"))},
           "matches": {}, "rankings": {"date": "2026-10-19", "rows": [[i + 1, f"p{i}", 5000 - 100 * i] for i in range(8)]}}
    cur["events"]["almaty-2026"] = ev("almaty", 2026, "2026-10-17", "2026-10-25", "250", "live")

    def prob(pids, surface, bo):
        return np.full((len(pids), len(pids)), 0.5)
    state = S.build_state("atp", "2026-10-22", stores={2026: cur, 2025: prev}, prob=prob, n=50)
    starts = {e["id"]: e["start"] for e in state["events"]}
    assert "stockholm-2026" not in starts
    assert starts["basel-2026"] == starts["vienna-2026"] == "2026-10-24"
    assert starts["paris-2026"] == "2026-10-31"
    assert S._week(date.fromisoformat(starts["basel-2026"])) != S._week(date.fromisoformat(starts["paris-2026"]))
