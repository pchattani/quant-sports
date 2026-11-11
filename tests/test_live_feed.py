"""scripts/live_feed.py: the live-score feed. Parsers keep the sites' ids, a game only shows a score once it has
started, a board's cadence follows its games, a silent board is retried without losing what it had, and the kit and
the sites read the feed through QK.live."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_feed", ROOT / "scripts" / "live_feed.py")
lf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lf)


def espn_event(eid, state, hs, as_, name="STATUS_IN_PROGRESS", period=2, clock="5:32", home="LAR", away="WSH",
               season=2026, stype=2, week=10, date="2026-11-11T20:00Z"):
    return {"id": eid, "date": date, "season": {"year": season, "type": stype}, "week": {"number": week},
            "competitions": [{"status": {"period": period, "displayClock": clock,
                                         "type": {"state": state, "name": name, "shortDetail": "x"}},
                              "competitors": [{"homeAway": "home", "score": str(hs), "team": {"abbreviation": home}},
                                              {"homeAway": "away", "score": str(as_), "team": {"abbreviation": away}}]}]}


def test_espn_states_and_scores():
    g = lf.parse_espn({"events": [espn_event("1", "in", 50, 48), espn_event("2", "pre", 0, 0, "STATUS_SCHEDULED"),
                                  espn_event("3", "post", 80, 76, "STATUS_FINAL"),
                                  espn_event("4", "post", 0, 0, "STATUS_POSTPONED")]})
    assert (g["1"]["s"], g["1"]["hs"], g["1"]["as"], g["1"]["p"], g["1"]["c"]) == ("live", 50, 48, 2, "5:32")
    assert (g["2"]["s"], g["2"]["hs"], g["2"]["as"], g["2"]["p"]) == ("pre", None, None, None)   # no 0-0 before the start
    assert (g["3"]["s"], g["3"]["hs"], g["3"]["p"], g["3"]["c"]) == ("final", 80, None, None)
    assert g["4"]["s"] == "off"


def test_nfl_ids_are_nflverse_ids():
    g = lf.parse_espn_nfl({"events": [espn_event("9", "in", 7, 3), espn_event("10", "pre", 0, 0, "STATUS_SCHEDULED",
                                                                             home="KC", away="BUF", stype=3, week=5)]})
    assert set(g) == {"2026_10_WAS_LA", "2026_22_BUF_KC"}        # ESPN's LAR / WSH; the Super Bowl is week 22


def test_nhl_and_mlb():
    nhl = lf.parse_nhl({"games": [
        {"id": 2026020293, "gameState": "LIVE", "homeTeam": {"score": 2}, "awayTeam": {"score": 1},
         "periodDescriptor": {"number": 2, "periodType": "REG"}, "clock": {"timeRemaining": "07:10", "inIntermission": False}},
        {"id": 2026020294, "gameState": "OFF", "homeTeam": {"score": 3}, "awayTeam": {"score": 4},
         "periodDescriptor": {"number": 4, "periodType": "OT"}},
        {"id": 2026020295, "gameState": "FUT", "homeTeam": {}, "awayTeam": {}}]})
    assert (nhl["2026020293"]["s"], nhl["2026020293"]["p"], nhl["2026020293"]["c"]) == ("live", 2, "07:10")
    assert (nhl["2026020294"]["s"], nhl["2026020294"]["d"], nhl["2026020294"]["as"]) == ("final", "Final/OT", 4)
    assert nhl["2026020295"]["s"] == "pre" and nhl["2026020295"]["hs"] is None
    mlb = lf.parse_mlb({"dates": [{"games": [
        {"gamePk": 7, "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
         "teams": {"home": {"score": 1}, "away": {"score": 0}}, "linescore": {"currentInning": 6, "inningState": "Bottom"}},
        {"gamePk": 8, "status": {"abstractGameState": "Final", "detailedState": "Postponed"}, "teams": {}}]}]})
    assert (mlb["7"]["s"], mlb["7"]["p"], mlb["7"]["c"], mlb["7"]["hs"]) == ("live", 6, "Bot", 1)
    assert mlb["8"]["s"] == "off"


def test_cadence_follows_the_games():
    now = 1_800_000_000
    iso = lambda dt: __import__("datetime").datetime.fromtimestamp(now + dt, __import__("datetime").timezone.utc).isoformat()
    assert lf.cadence({"a": {"s": "live"}}, now) == 30
    assert lf.cadence({"a": {"s": "pre", "st": iso(600)}}, now) == 60
    assert lf.cadence({"a": {"s": "pre", "st": iso(-1200)}}, now) == 60          # late start: still watched closely
    assert lf.cadence({"a": {"s": "pre", "st": iso(2 * 3600)}}, now) == 600
    assert lf.cadence({"a": {"s": "pre", "st": iso(1500)}}, now) == 600           # read again just as the 15 minutes begin
    assert lf.cadence({"a": {"s": "pre", "st": iso(86400)}}, now) == 1800
    assert lf.cadence({"a": {"s": "final"}}, now) == 1800
    assert lf.cadence({"a": {"s": "pre", "st": iso(-9 * 3600)}}, now) == 1800     # a stale row is not a game about to start


def test_tick_merges_keeps_and_retries():
    now = 1_800_000_000
    answers = {"nba": {"1": {"s": "live", "hs": 10, "as": 8, "p": 1, "c": "9:00", "d": None, "st": None, "_h": "X"}}}
    state: dict = {}
    doc = lf.tick(state, now, reader=lambda k: answers.get(k, {}))
    assert doc["sports"]["basketball"]["g"]["1"]["hs"] == 10 and "_h" not in doc["sports"]["basketball"]["g"]["1"]
    assert set(doc["sports"]) == {"basketball", "nfl", "college", "hockey", "baseball", "rugby", "football", "tennis"}
    assert state["boards"]["nba"]["next"] == now + 30 and state["boards"]["nfl"]["next"] == now + 1800
    assert state["boards"]["tennis-atp"]["next"] == now + 1800
    fp = lf.fingerprint(doc)
    # the source goes silent: the game is kept as last seen, the board retried sooner each time, nothing raised
    doc2 = lf.tick(state, now + 30, reader=lambda k: None if k == "nba" else {})
    assert doc2["sports"]["basketball"]["g"]["1"]["hs"] == 10 and lf.fingerprint(doc2) == fp
    assert state["boards"]["nba"]["fails"] == 1
    # the board answers again without the game (it has moved off the day's board): a game left "live" for over
    # 15 minutes is dropped, never shown live for ever
    doc3 = lf.tick(state, now + 2000, reader=lambda k: {})
    assert "1" not in doc3["sports"]["basketball"]["g"]
    # a final stays for KEEP_H hours
    answers["nba"] = {"2": {"s": "final", "hs": 99, "as": 90, "p": None, "c": None, "d": "Final", "st": None}}
    lf.tick(state, now + 4000, reader=lambda k: answers.get(k, {}))
    doc4 = lf.tick(state, now + 4000 + 3600, reader=lambda k: {})
    assert doc4["sports"]["basketball"]["g"]["2"]["hs"] == 99
    doc5 = lf.tick(state, now + 4000 + (lf.KEEP_H + 1) * 3600, reader=lambda k: {})
    assert "2" not in doc5["sports"]["basketball"]["g"]
    json.dumps(doc5)


def test_the_kit_and_the_sites_read_the_feed():
    kit = (ROOT / "docs" / "_design" / "quant.js").read_text(encoding="utf-8")
    assert "QK.live = (function" in kit and "the-quant-live/live.json" in kit
    home = (ROOT / "docs" / "home" / "assets" / "home.js").read_text(encoding="utf-8")
    assert "QK.live.onChange(applyFeed); QK.live.start();" in home
    for rel, sport in (("rink/assets/js/core.js", "hockey"), ("gridiron/assets/app/core.js", "nfl"),
                       ("hardwood/assets/js/core.js", "basketball"), ("bullpen/assets/js/core.js", "baseball"),
                       ("campus/assets/js/cc-core.js", "college"), ("scrum/assets/js/sc-core.js", "rugby"),
                       ("site/assets/app/core.js", "football"), ("ace/assets/js/core.js", "tennis")):
        t = (ROOT / "docs" / rel).read_text(encoding="utf-8")
        assert "QK.live.watch(" in t and f"'{sport}'" in t and "QK.live.attach(" in t, rel
    # every sport the sites watch is a sport the feed writes
    assert {s for s, *_ in lf.BOARDS.values()} == {"hockey", "nfl", "basketball", "baseball", "college", "rugby", "football", "tennis"}


def soccer_event(eid, home, away, date, state="in", hs=1, as_=0, name="STATUS_FIRST_HALF"):
    return {"id": eid, "date": date, "competitions": [{"status": {"period": 1, "displayClock": "34'",
            "type": {"state": state, "name": name, "shortDetail": "34'"}},
            "competitors": [{"homeAway": "home", "score": str(hs), "team": {"displayName": home, "shortDisplayName": home, "abbreviation": "H"}},
                            {"homeAway": "away", "score": str(as_), "team": {"displayName": away, "shortDisplayName": away, "abbreviation": "A"}}]}]}


def test_football_names_match_only_when_clear():
    assert lf.name_sim("Köln", ["FC Cologne", "Cologne", "Köln"]) == 1.0
    assert lf.name_sim("Inter", ["Internazionale", "Inter Milan"]) >= 0.85
    assert lf.name_sim("Sporting KC", ["Sporting Kansas City"]) >= 0.6
    assert lf.name_sim("Rennes", ["Brighton & Hove Albion"]) < 0.6
    start = 1_800_000_000
    iso = __import__("datetime").datetime.fromtimestamp(start, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    ev = lf.parse_soccer_events({"events": [soccer_event("e1", "Internazionale", "Como", iso), soccer_event("e2", "Brighton & Hove Albion", "Brentford", iso),
                                            soccer_event("e3", "Como Women", "Inter Women", iso)]})
    assert lf.match_fixture(["1", start, "Inter", "Como"], ev)["_id"] == "e1"
    assert lf.match_fixture(["2", start, "Rennes", "Lille"], ev) is None                    # not on the board: left out
    assert lf.match_fixture(["3", start + 3600, "Inter", "Como"], ev) is None               # another kickoff: not this match
    # two candidates as good as each other: no guess
    twin = lf.parse_soccer_events({"events": [soccer_event("a", "Nacional", "Real Potosi", iso), soccer_event("b", "Nacional", "Real Potosi", iso)]})
    assert lf.match_fixture(["4", start, "Nacional", "Real Potosí"], twin) is None


def test_football_board_is_read_only_around_a_kickoff():
    now = 1_800_000_000
    iso = lambda s: __import__("datetime").datetime.fromtimestamp(s, __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hub = {"days": {"d": [{"id": 11, "date": iso(now - 1800), "home": "Inter", "away": "Como", "status": "live"},
                          {"id": 12, "date": iso(now + 8 * 3600), "home": "Rennes", "away": "Lille", "status": "scheduled"},
                          {"id": 13, "date": iso(now - 1800), "home": "Sport Boys", "away": "Universidad Técnica de Cajamarca", "status": "scheduled"},
                          {"id": 14, "date": iso(now + 3600), "home": "A", "away": "B", "status": "postponed"}]}}
    calls = []

    def getter(url, params=None):
        calls.append(url)
        if url == lf.HUB_URL:
            return hub
        return {"events": [soccer_event("e1", "Internazionale", "Como", iso(now - 1800), hs=2, as_=1)]}

    lf._SOCCER.clear()
    out = lf.read_soccer(now, getter)
    assert (out["11"]["s"], out["11"]["hs"], out["11"]["as"], out["11"]["c"]) == ("live", 2, 1, "34'")
    assert out["12"]["s"] == "pre" and out["12"]["st"] and "14" not in out
    assert out["13"]["s"] == "pre" and out["13"]["st"] is None        # started, not on ESPN's board: not polled for
    assert lf._SOCCER["map"] == {"11": "e1"}
    # nothing near a kickoff: the fixtures come from the cached hub and ESPN is not called at all
    calls.clear()
    lf._SOCCER["fx"] = [f for f in lf._SOCCER["fx"] if f[0] == "12"]
    assert set(lf.read_soccer(now + 60, getter)) == {"12"} and calls == []
    lf._SOCCER.clear()


def tennis_comp(a, b, sa, sb, name="STATUS_IN_PROGRESS", winner=None, date="2026-11-11T17:05Z"):
    cp = lambda pid, order, sc: {"id": pid, "order": order, "winner": winner == pid, "linescores": [{"value": v, **({"tiebreak": t} if t is not None else {})} for v, t in sc]}
    return {"date": date, "status": {"type": {"name": name, "completed": name == "STATUS_FINAL"}}, "competitors": [cp(a, 1, sa), cp(b, 2, sb)]}


def test_tennis_sets_are_written_from_p1s_side():
    c = tennis_comp("2989", "8710", [(7, 7), (4, None), (2, None)], [(6, 5), (6, None), (3, None)])
    e = lf.tennis_entry(c, "8710")                                    # the Ace's p1 is ESPN's second player
    assert e["s"] == "live" and e["sets"] == [[6, 7, 5, 7], [6, 4, None, None]]
    assert e["live"] == {"set": 3, "games": [3, 2], "points": None, "server": None} and (e["hs"], e["as"], e["c"]) == (1, 1, "3-2")
    f = lf.tennis_entry(tennis_comp("2989", "8710", [(7, 7), (4, None), (3, None)], [(6, 5), (6, None), (6, None)], "STATUS_FINAL", "8710"), "8710")
    assert (f["s"], f["d"], f["w"], f["hs"], f["as"]) == ("final", "done", "8710", 2, 1) and f["live"] is None
    assert lf.tennis_entry(tennis_comp("1", "2", [], [], "STATUS_SCHEDULED"), "1")["sets"] == []
    idx = {"tours": {"atp": {"live": [{"id": "x-2026-R16-2989-8710", "p1": "8710", "p2": "2989", "date": "2026-11-11T17:05", "status": "live"}],
                             "today": [{"id": "done-1", "p1": "1", "p2": "2", "date": "2026-11-11T12:00", "status": "done"}], "upcoming": []}}}
    board = {"events": [{"groupings": [{"grouping": {"slug": "mens-singles"}, "competitions": [c]},
                                       {"grouping": {"slug": "mens-doubles"}, "competitions": [tennis_comp("8710", "2989", [(1, None)], [(0, None)])]}]}]}
    lf._TENNIS.clear()
    now = int(__import__("datetime").datetime(2026, 11, 11, 18, 0, tzinfo=__import__("datetime").timezone.utc).timestamp())
    out = lf.read_tennis("atp", now, lambda url, params=None: idx if url == lf.ACE_URL else board)
    assert set(out) == {"x-2026-R16-2989-8710"} and out["x-2026-R16-2989-8710"]["live"]["games"] == [3, 2]
    lf._TENNIS.clear()


def test_the_live_repo_never_fails_a_run():
    if not (ROOT / "live_repo").exists():      # the public build repo carries the feed scripts, not the live repo's files
        return
    wf = (ROOT / "live_repo" / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8")
    assert "core.setFailed" not in wf and "cancel-in-progress: false" in wf and "createWorkflowDispatch" in wf
    assert wf.count("continue-on-error: true") == 3 and "scripts/live_chances.py" in wf      # the models never stop the feed
    wd = (ROOT / "live_repo" / ".github" / "workflows" / "watchdog.yml").read_text(encoding="utf-8")
    assert "core.setFailed" not in wd and "live.yml" in wd
