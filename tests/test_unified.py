"""
The unified registries (people by Sofascore player id, clubs by Sofascore team
id), the season dimension, current squads and the fetcher helpers behind them —
on small synthetic stores, offline.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from oddsmarkets.football.analytics import unified as U  # noqa: E402

TODAY = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _m(gid, home, away, hid, aid, hs, as_, date, sid, stage="league", rnd=1, status="finished", **kw):
    return gid, {"home": home, "away": away, "home_id": hid, "away_id": aid, "hs": hs, "as": as_, "date": date,
                 "season_id": sid, "stage": stage, "round": rnd, "status": status, **kw}


def _lineup(team, pid, name, mins=90, goals=0, rating=7.0, sub=False):
    return {pid: {"n": name, "t": team, "p": "M", "sub": sub,
                  "s": {"minutesPlayed": mins, "goals": goals, "goalAssist": 0, "rating": rating, "expectedGoals": 0.1}}}


def _store(matches, lineups, current, players=None):
    return {"matches": dict(matches), "lineups": lineups, "players": players or {}, "incidents": {},
            "meta": {"season_id": current, "season_name": "x"}}


@pytest.fixture()
def world(tmp_path):
    """A league with two seasons, a continental cup and a national team, sharing players and clubs."""
    league = _store(
        [_m("1", "Boca Juniors", "River Plate", 3202, 3211, 2, 1, "2026-03-01T20:00:00Z", 200),
         _m("2", "River Plate", "Boca Juniors", 3211, 3202, 0, 0, "2026-09-01T20:00:00Z", 300),
         _m("3", "Boca Juniors", "River Plate", 3202, 3211, None, None, "2026-12-01T20:00:00Z", 300, status="notstarted")],
        {"1": {**_lineup("Boca Juniors", "82474", "Ander Herrera", goals=1), **_lineup("River Plate", "9", "River Nine")},
         "2": {**_lineup("Boca Juniors", "77", "Boca Seven"), **_lineup("River Plate", "9", "River Nine")}},
        current=300, players={"82474": {"n": "Ander Herrera", "c": "ESP", "dob": 619056000, "pos": "M"}})
    cup = _store(
        [_m("10", "Boca", "Flamengo", 3202, 5981, 1, 1, "2026-05-29T00:30:00Z", 500, stage="playoff", rnd="final",
            winner="Boca")],
        {"10": {**_lineup("Boca", "82474", "Ander Herrera", mins=45), **_lineup("Flamengo", "5", "Fla Five")}},
        current=500)
    intl = _store(
        [_m("20", "Spain", "Italy", 4698, 4707, 1, 0, "2026-06-10T18:00:00Z", 700, rnd="final")],
        {"20": {**_lineup("Spain", "82474", "Ander Herrera", mins=20), **_lineup("Italy", "8", "Italy Eight")}},
        current=700)
    seasons = {"premier-league": {"tournament_id": 17, "seasons": [{"season_id": 300, "name": "PL 26/27", "year": "26/27"},
                                                                 {"season_id": 200, "name": "PL 25/26", "year": "25/26"}]},
               "libertadores": {"tournament_id": 384, "seasons": [{"season_id": 500, "name": "Libertadores 2026", "year": "2026"}]},
               "euro": {"tournament_id": 1, "seasons": [{"season_id": 700, "name": "EURO 2026", "year": "2026"}]}}
    archive = {"seasons": {"premier-league": {"100": {"name": "PL 24/25", "year": "24/25", "standings": [
        {"group": "PL 24/25", "team": "River Plate FC", "position": 1, "points": 80, "matches": 38},
        {"group": "PL 24/25", "team": "Boca Juniors", "position": 2, "points": 70, "matches": 38}],
        "top_players": {"goals": [{"id": 9, "name": "River Nine", "team": "River Plate FC", "value": 20}]}}}},
        "players": {}, "season_lists": {}}
    squads = {"teams": {"3202": {"name": "Boca Juniors", "fetched_at": "2026-10-01T00:00:00Z",
                                 "players": [{"id": "77", "n": "Boca Seven", "pos": "D", "dob": 900000000, "c": "ARG"}]}},
              "people": {"82474": {"team_id": 2814, "team": "Real Zaragoza", "fetched_at": "2026-10-02T01:00:00Z"}},
              "pending": []}
    u = U.Unified(tmp_path, seasons, archive=archive, squads=squads, today=TODAY)
    u.add_store("premier-league", league)
    u.add_store("libertadores", cup)
    u.add_store("euro", intl)
    counts = u.finish()
    return tmp_path, u, counts


def _j(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── people ───────────────────────────────────────────────────────────────────

def test_one_person_across_club_cup_and_national_team(world) -> None:
    d, u, _ = world
    p = _j(d / "people" / "82474.json")
    assert p["name"] == "Ander Herrera" and p["nat"] == "ESP" and p["dob"] == "1989-08-14"
    scopes = {s["scope"] for s in p["seasons"]}
    assert scopes == {"club", "international"}
    assert {s["comp"] for s in p["seasons"]} == {"premier-league", "libertadores", "euro"}
    kinds = {s["comp"]: s["kind"] for s in p["seasons"]}
    assert kinds == {"premier-league": "league", "libertadores": "continental_club", "euro": "international"}
    assert len(p["apps"]) == 3 and p["apps_fields"][2] == "comp"
    assert [a[0] for a in p["apps"]] == sorted((a[0] for a in p["apps"]), reverse=True)
    # tid of every appearance names a team in the lookup; the result is from his side.
    assert all(str(a[4]) in p["teams"] for a in p["apps"])
    euro = next(a for a in p["apps"] if a[2] == "euro")
    assert euro[8] == "W 1-0" and p["teams"]["4698"]["national"] is True
    assert p["national_team"]["tid"] == 4698
    idx = _j(d / "people_index.json")
    ids = [r[0] for r in idx["rows"]]
    assert len(ids) == len(set(ids))
    row = dict(zip(idx["fields"], next(r for r in idx["rows"] if r[0] == "82474")))
    assert row["nt_tid"] == 4698 and row["nt"] == "Spain"


def test_a_player_who_left_is_not_in_the_squad_and_his_new_club_comes_from_his_profile(world) -> None:
    d, u, _ = world
    boca = _j(d / "clubs" / "3202.json")
    assert boca["squad"]["source"] == "roster"
    assert [p["id"] for p in boca["squad"]["players"]] == ["77"]
    p = _j(d / "people" / "82474.json")
    assert p["current_club"]["tid"] == 2814 and p["current_club"]["source"] == "profile"


def test_current_club_rules() -> None:
    u = U.Unified(Path("."), {}, squads={"teams": {"1": {"fetched_at": "2026-09-01T00:00:00Z", "players": [{"id": "p"}]},
                                                   "2": {"fetched_at": "2026-09-01T00:00:00Z", "players": []}}}, today=TODAY)
    roster, rostered = u._roster_index()
    app = lambda d, tid: [d, "g", "premier-league", "1", tid, 9, "X", 1, None, 1, 90, 0, 0, 0, 0, 7, 0, 0, 0, 0]  # noqa: E731
    # Listed by a roster: that club.
    assert u.current_club("p", [app("2026-08-01", 1)], roster, rostered)["source"] == "roster"
    # A later appearance for another club beats an older roster.
    assert u.current_club("p", [app("2026-09-20", 3)], roster, rostered) == {"tid": 3, "source": "appearances", "as_of": "2026-09-20"}
    # Last seen at a club whose roster does not list him: no current club.
    assert u.current_club("q", [app("2026-08-01", 2)], roster, rostered) is None
    # Last seen at a club with no roster: that club, from appearances.
    assert u.current_club("q", [app("2026-08-01", 5)], roster, rostered)["tid"] == 5
    # National-team appearances never make a club.
    intl = [["2026-09-01", "g", "euro", "1", 4698, 1, "X", 1, None, 1, 90, 0, 0, 0, 0, 7, 0, 0, 0, 0]]
    assert u.current_club("r", intl, roster, rostered) is None


# ── clubs ────────────────────────────────────────────────────────────────────

def test_one_club_across_competitions_and_names(world) -> None:
    d, _, _ = world
    boca = _j(d / "clubs" / "3202.json")
    assert boca["names"]["premier-league"] == "Boca Juniors" and boca["names"]["libertadores"] == "Boca"
    assert {s["comp"] for s in boca["seasons"]} >= {"premier-league", "libertadores"}
    lib = next(s for s in boca["seasons"] if s["comp"] == "libertadores")
    assert lib["stage"] == "winner" and lib["kind"] == "continental_club"
    ids = [m["id"] for m in boca["matches"]]
    assert len(ids) == len(set(ids)) and "3" in ids
    idx = _j(d / "clubs_index.json")
    tids = [r[0] for r in idx["rows"]]
    assert len(tids) == len(set(tids)) and 3202 in tids
    spain = _j(d / "clubs" / "4698.json")
    assert spain["national"] is True and spain["squad"]["source"] == "appearances"
    assert [p["id"] for p in spain["squad"]["players"]] == ["82474"]


def test_squad_without_roster_lists_only_players_whose_latest_club_it_is(world) -> None:
    d, _, _ = world
    river = _j(d / "clubs" / "3211.json")
    assert river["squad"]["source"] == "appearances"
    assert [p["id"] for p in river["squad"]["players"]] == ["9"]


# ── seasons ──────────────────────────────────────────────────────────────────

def test_season_manifest_and_past_season_payloads(world) -> None:
    d, u, _ = world
    man = _j(d / "premier-league" / "seasons.json")
    assert [r["source"] for r in man["seasons"]] == ["live", "store", "archive"]
    assert man["seasons"][0]["path"] == "" and man["current"] == 300
    past = _j(d / "premier-league" / "s" / "200" / "season.json")
    assert past["standings_source"] == "computed" and past["standings"][0]["team"] == "Boca Juniors"
    assert past["standings"][0]["tid"] == 3202 and past["fixtures"][0]["id"] == "1"
    arch = _j(d / "premier-league" / "s" / "100" / "season.json")
    assert arch["standings_source"] == "official"
    # "River Plate FC" in the archive is River Plate (3211) in the store.
    assert arch["standings"][0]["tid"] == 3211 and "group" not in arch["standings"][0]
    assert arch["leaders"]["goals"][0]["tid"] == 3211
    assert man["seasons"][2]["champion"] == {"team": "River Plate FC", "tid": 3211}
    f = u.competition_fields()
    assert f["premier-league"]["current_season"]["sid"] == 300 and f["premier-league"]["kind_u"] == "league"
    assert f["euro"]["current_season"]["status"] == "last_edition" and f["euro"]["winner"]["tid"] == 4698
    assert f["libertadores"]["scope"] == "club"


def test_cup_champion_only_from_a_final() -> None:
    table = [{"pos": 1, "team": "A", "tid": 1}]
    assert U.champion_of([], table, "continental_club") is None
    assert U.champion_of([], table, "league") == {"team": "A", "tid": 1}
    final = {"round": "final", "home": "A", "away": "B", "home_id": 1, "away_id": 2, "hs": 1, "as": 1, "status": "finished",
             "winner": "B", "date": "2026-05-01"}
    assert U.champion_of([final], table, "continental_club") == {"team": "B", "tid": 2}


@pytest.mark.parametrize("name,year,want", [
    ("Premier League 26/27", "26/27", ("26/27", "2026/27")),
    ("MLS 2026", "2026", ("2026", "2026")),
    ("Liga MX, Clausura 2026", "25/26", ("Clausura 2026", "2026")),
    ("World Cup Qualification, AFC 2025", "23-25", ("2025", "2025")),
])
def test_season_labels(name, year, want) -> None:
    assert U.season_label(name, year) == want


def test_argentina_seasons_are_the_halves_of_the_year(tmp_path) -> None:
    st = _store([_m("1", "Boca Juniors", "River Plate", 3202, 3211, 1, 0, "2026-03-01T20:00:00Z", 87913, torneo="apertura"),
                 _m("2", "Boca Juniors", "River Plate", 3202, 3211, None, None, "2026-11-01T20:00:00Z", 87913,
                    status="notstarted", torneo="clausura")],
                {"1": _lineup("Boca Juniors", "82474", "Ander Herrera")}, current=None)
    u = U.Unified(tmp_path, {}, today=TODAY)
    u.add_store("liga-argentina", st, current_key="2026-clausura")
    man = _j(tmp_path / "liga-argentina" / "seasons.json")
    assert [(r["sid"], r["season"], r["source"]) for r in man["seasons"]] == [
        ("2026-clausura", "Clausura 2026", "live"), ("2026-apertura", "Apertura 2026", "store")]
    assert (tmp_path / "liga-argentina" / "s" / "2026-apertura" / "season.json").exists()


def test_name_index_matches_archive_spellings() -> None:
    idx = U.NameIndex()
    for name, tid in (("Liverpool", 44), ("Brighton", 30), ("Manchester United", 35), ("Manchester City", 17)):
        idx.add(name, tid)
    assert idx("Liverpool FC") == 44 and idx("Brighton & Hove Albion") == 30
    assert idx("Manchester United FC") == 35 and idx("Manchester") is None     # ambiguous: no guess
    idx.add_fallback("Real Zaragoza", 2814)
    assert idx("Real Zaragoza") == 2814 and idx("Zaragoza") is None           # the fallback is exact only


# ── the squads fetcher ───────────────────────────────────────────────────────

def test_squad_rotation_and_departures() -> None:
    sq = importlib.import_module("fetch_sofascore_squads")
    assert sq.in_transfer_window(datetime(2026, 8, 1).date()) and not sq.in_transfer_window(datetime(2026, 10, 2).date())
    clubs = {"1": {"priority": 1}, "2": {"priority": 0}, "3": {"priority": 0}, "4": {"priority": 0}, "5": {"priority": 1}}
    store = {"teams": {"3": {"fetched_at": "2026-09-01T00:00:00Z"}, "4": {"fetched_at": "2026-10-01T12:00:00Z"}},
             "failed": {"5": {"at": "2026-09-30T00:00:00Z", "status": 404}}}
    # The followed leagues first (never fetched, then stale), then the cups; "4" is fresh and
    # "5" had no squad page two days ago, so it waits (it used to block the queue for ten days).
    assert sq.due_clubs(clubs, store, TODAY) == ["2", "3", "1"]
    store["failed"]["5"]["at"] = "2026-09-01T00:00:00Z"
    assert sq.due_clubs(clubs, store, TODAY) == ["2", "3", "1", "5"]
    assert sq.departures([{"id": "a"}, {"id": "b"}], [{"id": "b"}], {"c": "2026-09-01"}) == ["a", "c"]


def test_team_players_parses_the_squad(monkeypatch) -> None:
    from oddsmarkets.football.sources import sofascore as s
    payload = {"players": [{"player": {"id": 77, "name": "Boca Seven", "shortName": "B. Seven", "position": "D",
                                       "jerseyNumber": "4", "dateOfBirthTimestamp": 900000000, "country": {"alpha3": "ARG"},
                                       "proposedMarketValueRaw": {"value": 4500000, "currency": "EUR"}}},
                           {"player": {"id": 77, "name": "dup"}},
                           {"player": {"id": 78, "name": "Peso Eight", "proposedMarketValueRaw": {"value": 900000, "currency": "USD"}}}]}
    monkeypatch.setattr(s, "get_json", lambda path, quiet=False, timeout=20: payload if path == "/team/3202/players" else None)
    monkeypatch.setattr(s, "DETAIL_PAUSE_S", 0)
    rows = s.team_players(3202, s.CallBudget(1))
    assert rows == [{"id": "77", "n": "Boca Seven", "sn": "B. Seven", "pos": "D", "no": "4", "dob": 900000000, "c": "ARG", "mv": 4500000},
                    {"id": "78", "n": "Peso Eight", "mv": 900000, "mvc": "USD"}]
    assert s.team_players(1) is None


# ── the past-results backfill ────────────────────────────────────────────────

def test_past_seasons_queue_newest_first_and_resume(monkeypatch) -> None:
    h = importlib.import_module("fetch_sofascore_history")
    from oddsmarkets.football.sources import sofascore as s
    archive = {"season_lists": {"17": [{"season_id": 3, "name": "PL 26/27", "year": "26/27"}, {"season_id": 2, "name": "PL 25/26", "year": "25/26"},
                                       {"season_id": 1, "name": "PL 24/25", "year": "24/25"}, {"season_id": 0, "name": "PL 23/24", "year": "23/24"}],
                                "7": [{"season_id": 9, "name": "UCL 26/27", "year": "26/27"}, {"season_id": 8, "name": "UCL 25/26", "year": "25/26"},
                                      {"season_id": 6, "name": "UCL 24/25", "year": "24/25"}]},
               "seasons": {}}
    cfg = {"premier-league": {"tournament_id": 17, "seasons": [{"season_id": 3}, {"season_id": 2}]},
           "champions-league": {"tournament_id": 7, "seasons": [{"season_id": 9}, {"season_id": 8}]}}
    past = {"seasons": {"premier-league": {"99": {"complete": True}}}}
    q = h.past_queue(archive, past, cfg)
    assert [(slug, s_["season_id"]) for slug, _, s_ in q] == [("premier-league", 1), ("champions-league", 6), ("premier-league", 0)]
    assert "99" not in past["seasons"]["premier-league"]      # a season of another tournament is dropped
    pages = {0: {"events": [{"id": 1}], "hasNextPage": True}, 1: {"events": [{"id": 2}], "hasNextPage": False}}
    monkeypatch.setattr(s, "get_json", lambda path, quiet=False, timeout=20: pages.get(int(path.rsplit("/", 1)[1])))
    monkeypatch.setattr(s, "PAGE_PAUSE_S", 0)
    ev, done, nxt = s.past_season_events(17, 1, s.CallBudget(1))
    assert [e["id"] for e in ev] == [1] and not done and nxt == 1
    ev, done, nxt = s.past_season_events(17, 1, s.CallBudget(5), start_page=nxt)
    assert [e["id"] for e in ev] == [2] and done


# ── the Ballon d'Or is gone ──────────────────────────────────────────────────

def test_no_ballon_dor_anywhere_in_the_backend() -> None:
    assert importlib.util.find_spec("oddsmarkets.football.analytics.ballon_dor") is None
    assert importlib.util.find_spec("oddsmarkets.football.sources.polymarket") is None
    assert not (ROOT / "scripts" / "fit_ballon_dor.py").exists()
    for f in ("build_site_global.py", "build_site_all.py", "fetch_sofascore_history.py"):
        text = (ROOT / "scripts" / f).read_text(encoding="utf-8").lower()
        assert "ballon" not in text, f
    wf = (ROOT / ".github" / "workflows" / "update_site.yml").read_text(encoding="utf-8").lower()
    assert "ballon" not in wf


def test_results_keep_the_shootout_apart() -> None:
    m = {"home": "France", "away": "England", "hs": 2, "as": 2, "status": "finished", "winner": "England", "pens": [2, 4]}
    assert U.result_string(m, True) == "D 2-2, lost 2-4 pens"
    assert U.result_string(m, False) == "D 2-2, won 4-2 pens"
    assert U.result_string({**m, "pens": None}, True) == "D 2-2, lost on pens"
    assert U.result_string({"hs": 4, "as": 6, "status": "finished"}, True) == "L 4-6"


def test_finished_editions_are_not_live_and_rows_say_who_is_current(world) -> None:
    d, _, _ = world
    p = _j(d / "people" / "82474.json")
    euro = next(s for s in p["seasons"] if s["comp"] == "euro")
    assert euro["source"] == "store"                 # the Euro of the fixture is over: a last edition, not live
    lib = next(s for s in p["seasons"] if s["comp"] == "libertadores")
    assert lib["current"] is False                   # he has left Boca
    assert euro["current"] is True                   # still Spain's
    league = next(s for s in p["seasons"] if s["comp"] == "premier-league")
    assert set(league) >= {"apps", "min", "g", "a"}


def test_play_off_paths_crown_no_one() -> None:
    f = lambda h, a, d: {"round": "final", "home": h, "away": a, "hs": 1, "as": 0, "status": "finished", "date": d}  # noqa: E731
    assert U.champion_of([f("Poland", "Wales", "2024-03-26"), f("Georgia", "Greece", "2024-03-26")], [], "international") is None
    two_legs = [f("A", "B", "2026-02-01"), {**f("B", "A", "2026-02-08"), "agg_winner": "A", "hs": 1, "as": 1}]
    assert U.champion_of(two_legs, [], "super_cup")["team"] == "A"


def test_no_team_profile_means_no_current_club() -> None:
    u = U.Unified(Path("."), {}, squads={"teams": {}, "people": {"21521": {"team_id": 241802, "team": "No team",
                                                                          "fetched_at": "2026-10-02T05:00:00Z"}}}, today=TODAY)
    app = ["2026-05-01", "g", "liga-argentina", "x", 3202, 1, "X", 1, None, 1, 90, 0, 0, 0, 0, 7, 0, 0, 0, 0]
    assert u.current_club("21521", [app], {}, set()) is None


def test_qualifiers_have_no_winner(tmp_path) -> None:
    st = _store([_m("1", "DR Congo", "Nigeria", 1, 2, 1, 1, "2025-11-16T18:00:00Z", 9, stage="playoff", rnd="final", winner="DR Congo")],
                {}, current=9)
    u = U.Unified(tmp_path, {}, today=TODAY)
    u.add_store("wc-qual-caf", st)
    assert "winner" not in _j(tmp_path / "wc-qual-caf" / "seasons.json")


# ── what a fan reads (audit of 2 October 2026) ───────────────────────────────

@pytest.mark.parametrize("name,year,want", [
    ("UEFA Super Cup 2026", "26/27", ("2026", "2026/27")),                    # the name, not the year, labels a one-off
    ("Euro Cup 2020", "2021", ("2020", "2021")),
    ("Super Cup 22/23", "23/24", ("22/23", "2023/24")),
    ("World Cup Qualification, CONMEBOL 2025", "2026", ("2026", "2026")),   # qualifiers: the tournament they lead to
    ("Africa Cup of Nations 2015, Qualification", "2014", ("2015", "2014")),
])
def test_season_label_reads_like_the_name(name, year, want) -> None:
    assert U.season_label(name, year) == want


def test_a_league_relegation_play_off_crowns_no_one() -> None:
    table = [{"pos": 1, "team": "Bayern", "tid": 1}]
    po = [{"round": "final", "stage": "other", "home": "Paderborn", "away": "Wolfsburg", "home_id": 3, "away_id": 4, "hs": 2, "as": 1,
           "status": "finished", "date": "2026-05-25"}]
    assert U.champion_of(po, table, "league") == {"team": "Bayern", "tid": 1}
    liguilla = [{**po[0], "stage": "playoff", "home": "Cruz Azul", "away": "Pumas", "home_id": 5, "away_id": 6}]
    assert U.champion_of(liguilla, table, "league", title_by_playoff=True)["team"] == "Cruz Azul"
    play_in = [{**po[0], "stage": "qualifying", "home": "LAFC", "away": "America"}]
    assert U.champion_of(play_in, [], "continental_club") is None
    split = [{"pos": 1, "team": "Gent", "tid": 9, "group": "Pro League, Regular Season"},
             {"pos": 1, "team": "Club Brugge", "tid": 8, "group": "Pro League, Championship Round"}]
    assert U.champion_of([], split, "league")["team"] == "Club Brugge"


def test_national_cup_rounds_are_rounds_not_qualifiers() -> None:
    assert U._round_key({"stage": "qualifying", "round": 3}, "domestic_cup") == ("r3", 2.3)
    assert U._round_key({"stage": "qualifying", "round": "2"}, "continental_club")[0] == "q2"
    assert U._round_key({"stage": "qualifying", "round": 300}, "domestic_cup")[0] == "prelim"
    assert U._round_key({"stage": "playoff", "round": "qf"}, "domestic_cup") == ("qf", 6)


def test_official_table_takes_the_record_only_when_the_results_cover_it() -> None:
    official = [{"pos": 1, "team": "Arsenal", "tid": 42, "played": 2, "pts": 4}, {"pos": 2, "team": "Chelsea", "tid": 38, "played": 2, "pts": 1}]
    full = [{"team": "Arsenal", "tid": 42, "played": 2, "w": 1, "d": 1, "l": 0, "gf": 3, "ga": 1, "gd": 2},
            {"team": "Chelsea", "tid": 38, "played": 2, "w": 0, "d": 1, "l": 1, "gf": 1, "ga": 3, "gd": -2}]
    assert U.merge_records(official, full)[0]["w"] == 1
    partial = [dict(full[0], played=1), full[1]]
    assert "w" not in U.merge_records(official, partial)[0]


def test_a_postponed_copy_of_a_played_fixture_is_dropped() -> None:
    ms = dict([_m("1", "A", "B", 1, 2, 2, 1, "2026-03-01", 5), _m("2", "A", "B", 1, 2, None, None, "2026-02-01", 5, status="postponed"),
               _m("3", "C", "D", 3, 4, None, None, "2026-02-01", 5, status="postponed")])
    assert sorted(U._drop_stale(ms)) == ["1", "3"]


def test_registry_spelling_beats_a_shared_word() -> None:
    idx = U.NameIndex()
    idx.add("PSG", 1644)
    idx.add("Paris FC", 6070)
    idx.registry = U.competitions()["ligue-1"]["registry"]
    # The registry knows "Paris Saint-Germain" is PSG; the loose word match would have said Paris FC.
    assert idx("Paris Saint-Germain") == 1644


def test_world_cup_qualifying_is_named_for_its_world_cup() -> None:
    assert U.fan_label("wc-qual-afc", "2025") == "2026"
    assert U.fan_label("wc-qual-uefa", "2022") == "2022"
    assert U.fan_label("euro-qualifiers", "2023") == "2023"


# ── the season model, coverage, year by year (17 October 2026) ─────────────────

def test_frames_and_edition_season_keys() -> None:
    assert U.frame_of("premier-league") == "split" and U.frame_of("brasileirao") == "calendar"
    assert U.frame_of("world-cup") == "international" and U.frame_of("liga-argentina") == "calendar"
    assert U.frame_era("split", "2026-08-02") == "2026/27" and U.frame_era("split", "2026-05-24") == "2025/26"
    assert U.frame_era("calendar", "2026-11-30") == "2026"
    # A super cup named for a year opens the season of its date, whatever Sofascore's year says.
    assert U.edition_era("johan-cruijff-schaal", "2025/26", ["2026-08-02"]) == "2026/27"
    # The Supercopa named "2027" is played in January 2027: 2026/27; an archive edition without dates takes the learned shift.
    assert U.edition_era("supercopa-espana", "2027", ["2027-01-07", "2027-01-11"]) == "2026/27"
    assert U.edition_era("supercopa-espana", "2024", [], shift=-1) == "2023/24"
    assert U.edition_era("community-shield", "2022", []) == "2022/23"
    assert U.edition_era("club-world-cup", "2023/24", []) == "2023"
    # International football falls in the player's own frame; June and July close the split season.
    assert U.frame_era("split", "2026-07-19", U.INTL_SPLIT_START_MONTH) == "2025/26"
    assert U.frame_era("split", "2026-09-05", U.INTL_SPLIT_START_MONTH) == "2026/27"
    assert U.person_frame(["libertadores", "brasileirao"]) == "calendar" and U.person_frame(["champions-league"]) == "split"
    assert U.person_frame([], ["25/26", "2024"]) == "split" and U.person_frame([]) == "calendar"


def _coverage_world(tmp_path, archive_minutes=None):
    """A split-season league whose last season has line-ups for one match of two, and a June international."""
    league = _store(
        [_m("1", "Home", "Away", 1, 2, 1, 0, "2025-09-01T15:00:00Z", 10),
         _m("2", "Away", "Home", 2, 1, 0, 0, "2026-03-01T15:00:00Z", 10),
         _m("3", "Home", "Away", 1, 2, 2, 2, "2026-09-01T15:00:00Z", 20)],
        {"2": _lineup("Home", "7", "Seven"), "3": _lineup("Home", "7", "Seven", goals=1)}, current=20,
        players={"7": {"n": "Seven", "pos": "M", "dob": 900000000}})
    league["detail_missing"] = {}
    intl = _store([_m("30", "Norway", "Italy", 50, 51, 3, 0, "2026-06-20T18:00:00Z", 70, stage="league")],
                  {"30": _lineup("Norway", "7", "Seven", mins=80, goals=2)}, current=70)
    seasons = {"premier-league": {"tournament_id": 17, "seasons": [{"season_id": 20, "name": "PL 26/27", "year": "26/27"},
                                                                 {"season_id": 10, "name": "PL 25/26", "year": "25/26"}]},
               "world-cup": {"tournament_id": 16, "seasons": [{"season_id": 70, "name": "World Cup 2026", "year": "2026"}]}}
    archive = {"seasons": {}, "season_lists": {}, "players": {}}
    if archive_minutes:
        archive["players"]["7"] = {"seasons": [{"tid": 17, "tname": "Premier League", "sid": 10, "sname": "Premier League 25/26",
                                                "year": "25/26", "team": "Home",
                                                "stats": {"appearances": 2, "minutesPlayed": archive_minutes, "goals": 3}}]}
    squads = {"teams": {"1": {"name": "Home", "fetched_at": "2026-10-01T00:00:00Z",
                              "players": [{"id": "7", "n": "Seven", "pos": "M", "mv": 12000000, "until": 1877472000}]}}}
    u = U.Unified(tmp_path, seasons, archive=archive, squads=squads, today=TODAY)
    u.add_store("premier-league", league)
    u.add_store("world-cup", intl)
    u.finish()
    return _j(tmp_path / "people" / "7.json"), u


def test_partial_seasons_are_flagged_and_years_add_up(tmp_path) -> None:
    p, u = _coverage_world(tmp_path)
    assert p["frame"] == "split" and p["mv"] == 12000000 and p["until"] == "2029-06-30"
    last = next(s for s in p["seasons"] if s["comp"] == "premier-league" and s["sid"] == 10)
    assert last["coverage"] == "partial" and last["cov"] == [1, 2] and last["gap"] == "backfill" and last["min"] == 90
    now = next(s for s in p["seasons"] if s["sid"] == 20)
    assert now["coverage"] == "full"
    wc = next(s for s in p["seasons"] if s["comp"] == "world-cup")
    assert wc["era"] == "2025/26"                    # a June World Cup closes his 2025/26
    years = {y["era"]: y for y in p["years"]}
    assert set(years) == {"2026/27", "2025/26"}
    assert years["2025/26"]["min"] == 170 and years["2025/26"]["intl"]["min"] == 80 and years["2025/26"]["coverage"] == "partial"
    for y in p["years"]:                            # the competitions add up to the season
        assert y["min"] == sum(s["min"] for s in p["seasons"] if s["era"] == y["era"])
    idx = _j(tmp_path / "people_index.json")
    row = dict(zip(idx["fields"], next(r for r in idx["rows"] if r[0] == "7")))
    assert row["season"] == "2026/27" and row["min"] == 90 and row["mv"] == 12000000
    man = _j(tmp_path / "premier-league" / "seasons.json")
    cov = {r["sid"]: r["coverage"] for r in man["seasons"]}
    assert cov == {20: "full", 10: "partial"}
    club = _j(tmp_path / "clubs" / "1.json")
    assert next(s for s in club["seasons"] if s["sid"] == 10)["coverage"] == "partial"
    assert {y["era"] for y in club["years"]} == {"2026/27", "2025/26"}
    assert club["squad"]["players"][0]["mv"] == 12000000


def test_season_totals_replace_a_partial_line_up_record(tmp_path) -> None:
    p, _ = _coverage_world(tmp_path, archive_minutes=170)
    last = next(s for s in p["seasons"] if s["comp"] == "premier-league" and s["sid"] == 10)
    assert last["coverage"] == "totals" and last["min"] == 170 and last["g"] == 3 and last["lineups"] == {"apps": 1, "min": 90}
    assert "archive" not in p                       # never also an archive row for the same edition
    y = next(y for y in p["years"] if y["era"] == "2025/26")
    assert y["min"] == 250 and y["coverage"] == "full"


def test_unavailable_line_ups_are_told_apart(tmp_path) -> None:
    league = _store([_m("1", "Home", "Away", 1, 2, 1, 0, "2025-09-01T15:00:00Z", 10),
                     _m("2", "Away", "Home", 2, 1, 0, 0, "2026-03-01T15:00:00Z", 10)],
                    {"2": _lineup("Home", "7", "Seven")}, current=10)
    league["detail_missing"] = {"1": {"at": "2026-10-01T00:00:00Z", "n": 3, "why": "no-lineups", "final": True}}
    u = U.Unified(tmp_path, {}, today=TODAY)
    u.add_store("premier-league", league)
    u.finish()
    row = _j(tmp_path / "people" / "7.json")["seasons"][0]
    assert row["coverage"] == "partial" and row["gap"] == "unavailable"
    assert _j(tmp_path / "premier-league" / "seasons.json")["seasons"][0]["unavailable"] == 1


def test_minutes_floor_rises_with_games_played() -> None:
    from oddsmarkets.football.analytics.players import minutes_floor

    assert minutes_floor([{"minutes": 630}]) == 190                # seven rounds in: 30% of 630
    assert minutes_floor([{"minutes": 2700}]) == 810               # thirty rounds in
    assert minutes_floor([{"minutes": 3420}]) == 1030              # a full 38-round season
    assert minutes_floor([{"minutes": 120}]) == 90                 # never under 90
    assert minutes_floor([], games=10) == 270


def test_global_pool_keeps_the_season_under_way() -> None:
    import build_site_global as G

    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    pl = {"slug": "premier-league", "_fixtures": [{"date": "2026-08-21"}, {"date": "2027-05-30"}, {"date": "2026-12-26"}]}
    br = {"slug": "brasileirao", "_fixtures": [{"date": "2026-01-28"}, {"date": "2026-12-02"}, {"date": "2026-07-01"}]}
    cdf = {"slug": "coupe-de-france", "_fixtures": [{"date": "2025-11-14"}, {"date": "2026-05-22"}, {"date": "2026-02-01"}]}
    euq = {"slug": "euro-qualifiers", "_fixtures": [{"date": "2024-03-26", "status": "finished"}]}
    nl = {"slug": "nations-league", "_fixtures": [{"date": "2026-10-13", "status": "finished"}]}
    assert [G.in_current_window(c, now) for c in (pl, br, cdf, euq, nl)] == [True, True, False, False, True]


def test_old_detail_gets_no_match_page() -> None:
    from scripts.build_site_all import has_match_page

    now = datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert has_match_page("1", "2025-08-16", {"1"}, now)                 # the live edition: always
    assert has_match_page("2", "2025-10-20", set(), now)                 # inside the year
    assert not has_match_page("3", "2025-08-16", set(), now)             # a backfilled match from last August


# ── careers the fetcher's old row cap cut short ──────────────────────────────

def test_fetcher_keeps_whole_seasons_and_relists_lists_the_old_cap_cut() -> None:
    h = importlib.import_module("fetch_sofascore_history")
    assert [h.season_end_year(y) for y in ("23/24", "2023/2024", "2024", "26/27", None)] == [2024, 2024, 2024, 2027, 0]
    # Mbappe's list, Sofascore order: per tournament, newest first.
    listed = [{"tid": 8, "sid": 1, "year": "25/26"}, {"tid": 8, "sid": 2, "year": "24/25"},
              {"tid": 7, "sid": 3, "year": "25/26"}, {"tid": 7, "sid": 4, "year": "24/25"}, {"tid": 7, "sid": 5, "year": "23/24"},
              {"tid": 7, "sid": 6, "year": "22/23"}, {"tid": 34, "sid": 7, "year": "23/24"}, {"tid": 34, "sid": 8, "year": "22/23"},
              {"tid": 1, "sid": 9, "year": "2024"}, {"tid": 999, "sid": 10, "year": "25/26"}]
    allowed = {8, 7, 34, 1}
    keep = h.select_career(listed, allowed, years=3)
    assert {s["sid"] for s in keep} == {1, 2, 3, 4, 5, 7, 9}      # 2023/24 whole: CL, Ligue 1 and EURO 2024
    assert [h.season_end_year(s["year"]) for s in keep] == sorted((h.season_end_year(s["year"]) for s in keep), reverse=True)
    old = {"season_list": [{"tid": 7, "sid": i, "year": "25/26"} for i in range(12)], "complete": True}
    assert h.needs_relist(old)
    assert not h.needs_relist({**old, "list_rule": h.LIST_RULE})
    assert not h.needs_relist({"season_list": old["season_list"][:11]})
    assert not h.needs_relist({"season_list": None})


def _career_world(tmp_path, n_listed):
    """A Ligue 1 club (PSG in the stores) and a player whose archive career the old cap may have cut."""
    league = _store([_m("1", "PSG", "Lyon", 1644, 1649, 2, 0, "2026-09-01T15:00:00Z", 20)],
                    {"1": _lineup("PSG", "7", "Seven")}, current=20, players={"7": {"n": "Seven", "pos": "F", "dob": 900000000}})
    seasons = {"ligue-1": {"tournament_id": 34, "seasons": [{"season_id": 20, "name": "Ligue 1 26/27", "year": "26/27"}]},
               "champions-league": {"tournament_id": 7, "seasons": []}}
    listed = [{"tid": 34, "tname": "Ligue 1", "sid": 100 + i, "sname": f"Ligue 1 {25 - i:02d}/{26 - i:02d}", "year": f"{25 - i:02d}/{26 - i:02d}"}
              for i in range(n_listed)]
    arch_seasons = [{**s, "team": "Paris Saint-Germain", "stats": {"appearances": 30, "minutesPlayed": 2500, "goals": 20}} for s in listed]
    archive = {"seasons": {}, "season_lists": {}, "players": {"7": {"season_list": listed, "seasons": arch_seasons, "complete": True}}}
    u = U.Unified(tmp_path, seasons, archive=archive, today=TODAY)
    u.add_store("ligue-1", league)
    u.finish()
    return _j(tmp_path / "people" / "7.json")


def test_a_career_cut_by_the_old_cap_reads_partial_from_where_it_stops(tmp_path) -> None:
    p = _career_world(tmp_path, 12)
    cut = p["career_gap"]["through"]
    assert cut == "2014/15"                                       # the oldest season the cut list reached
    years = {y["era"]: y for y in p["years"]}
    assert years["2014/15"]["coverage"] == "partial" and years["2014/15"]["gap"] == "career"
    assert years["2015/16"]["coverage"] == "full" and "gap" not in years["2015/16"]
    assert years["2026/27"]["coverage"] == "full"
    # "Paris Saint-Germain" in the archive is PSG (1644) in the stores, through the Ligue 1 registry.
    assert {r.get("tid") for r in p["archive"]} == {1644}


def test_a_short_or_relisted_career_has_no_gap(tmp_path) -> None:
    p = _career_world(tmp_path, 5)
    assert "career_gap" not in p and all(y["coverage"] == "full" for y in p["years"])
