"""oddsmarkets/football/analytics/follow_build.py: The Quant Footballer's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.football.analytics import follow_build as B

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
# six league clubs (tids 1-6), a cup-only club (7), a club that met a national team in a friendly (6), a national team (90)
CLUBS = {"1": "Alpha FC", "2": "Beta United", "3": "Gamma Town", "4": "Delta City", "5": "Echo Rovers", "6": "Foxtrot"}


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def tree(tmp: Path) -> Path:
    d = tmp / "data"
    comps = [
        {"slug": "lg", "name": "Test League", "short_name": "TL", "kind": "league", "scope": "club", "ok": True, "favourite_label": "Title",
         "current_season": {"sid": 100, "season": "26/27", "status": "current"}},
        {"slug": "cup", "name": "Test Cup", "short_name": "Cup", "kind": "cup", "scope": "club", "family": "domestic", "ok": True,
         "current_season": {"sid": 200, "status": "current"}},
        {"slug": "shield", "name": "Test Shield", "kind": "cup", "scope": "club", "family": "super", "ok": True,
         "current_season": {"sid": 300, "status": "last_edition"}},
        {"slug": "nl", "name": "Nations Test", "short_name": "NT", "kind": "cup", "scope": "international", "family": "international", "ok": True,
         "current_season": {"sid": 400, "status": "current"}},
        {"slug": "friendlies", "name": "Friendlies", "kind": "cup", "scope": "international", "family": "international", "ok": True,
         "current_season": {"sid": 500, "status": "current"}},
    ]
    write(d / "competitions.json", {"competitions": comps})
    rows = [[int(t), nm, "TST", 1 if t == "6" else 0, "lg", ["lg", "cup"], "#112233", "#ffffff"] for t, nm in CLUBS.items()]
    rows += [[7, "Lower Ltd", "TST", 0, None, ["cup"], None, None], [90, "Testland", "TST", 1, None, ["nl", "friendlies"], None, None]]
    write(d / "clubs_index.json", {"fields": ["id", "name", "country", "national", "home", "comps", "colour", "alt"], "rows": rows})
    write(d / "lg" / "teams.json", {"teams": {nm: {"team_id": int(t)} for t, nm in CLUBS.items()}})
    write(d / "cup" / "teams.json", {"teams": {**{nm: {"team_id": int(t)} for t, nm in CLUBS.items()}, "Lower Ltd": {"team_id": 7}}})
    write(d / "nl" / "teams.json", {"teams": {"Testland": {"team_id": 90}}})
    # the table: club 1 top on 21 points, club 2 second
    stand = [{"pos": i + 1, "team": CLUBS[t], "played": 8, "w": 7 - i, "d": 0, "l": 1 + i, "pts": 21 - 3 * i} for i, t in enumerate(CLUBS)]
    fixtures = []
    for k in range(4):                       # club 1 wins four at home, club 2 loses four away
        fixtures.append({"home": "Alpha FC", "away": CLUBS[str(2 + k)], "hg": 2, "ag": 0, "date": (NOW - timedelta(days=30 - k)).date().isoformat(), "done": True, "stage": "league"})
    for k in range(4):
        fixtures.append({"home": CLUBS[str(3 + k % 4)] if 3 + k % 4 <= 6 else "Gamma Town", "away": "Beta United", "hg": 1, "ag": 0,
                         "date": (NOW - timedelta(days=20 - k)).date().isoformat(), "done": True, "stage": "league"})
    fixtures.append({"home": "Gamma Town", "away": "Alpha FC", "hg": 0, "ag": 5, "date": (NOW + timedelta(days=2)).date().isoformat(), "done": True, "stage": "league"})
    write(d / "lg" / "table.json", {"bands": [{"key": "ucl", "label": "Europe", "kind": "up"}, {"key": "rel", "label": "Relegation", "kind": "down"}],
                                    "standings": stand, "fixtures": fixtures, "matches_per_team": 30})
    write(d / "lg" / "probs.json", {"teams": [{"team": CLUBS[t], "p_title": 0.6 if t == "1" else 0.08, "bands": {"ucl": 0.95 if t == "1" else 0.4, "rel": 0.0 if t == "1" else 0.2}} for t in CLUBS]})
    write(d / "lg" / "strength.json", {"rows": [{"team": CLUBS[t], "sos_remaining": 1.2 + 0.05 * int(t), "played": 8} for t in CLUBS]})
    metrics = [{"key": "xg", "label": "xG per match", "fmt": "2"}, {"key": "xga", "label": "xG against per match", "fmt": "2", "lower": True},
               {"key": "xg_diff", "label": "xG difference per match", "fmt": "2"}, {"key": "shots", "label": "Shots per match", "fmt": "1"},
               {"key": "poss", "label": "Possession", "fmt": "pct"}, {"key": "fouls", "label": "Fouls per match", "fmt": "1", "lower": True}]
    write(d / "lg" / "team_stats.json", {"metrics": metrics, "teams": {CLUBS[t]: {"season": {"matches": 8, "xg": 2.0 - 0.2 * int(t), "xga": 0.5 + 0.1 * int(t),
                                         "xg_diff": 1.5 - 0.3 * int(t), "shots": 10 + int(t), "poss": 60 - int(t), "fouls": 9}} for t in CLUBS}})
    snaps = [{"ts": iso(NOW - timedelta(days=8)), "title": {"Alpha FC": 0.40}, "relegation": {"Beta United": 0.05}},
             {"ts": iso(NOW - timedelta(days=1)), "title": {"Alpha FC": 0.60}, "relegation": {"Beta United": 0.2}},
             {"ts": iso(NOW + timedelta(days=1)), "title": {"Alpha FC": 0.01}}]          # a later run: never read
    write(d / "lg" / "history.json", {"snapshots": snaps})
    write(d / "cup" / "bracket.json", {"p_cup": {"Alpha FC": 0.3, "Beta United": 0.25, "Lower Ltd": 0.0}})
    write(d / "pool.json", {"clubs": [{"team_id": int(t), "team": CLUBS[t], "comp": "lg", "strength": 2.0 - 0.1 * int(t), "rank": int(t)} for t in CLUBS]
                                     + [{"team": "Lower Ltd", "comp": "cup", "strength": 0.5, "rank": 40}]})
    write(d / "nations.json", {"teams": [{"team": "Testland", "strength": 1.9, "rank": 3}, {"team": "Otherland", "strength": 1.0, "rank": 9}]})
    write(d / "forecast_log.json", {"m-last": [0.3, 0.3, 0.4, iso(NOW - timedelta(days=2)), "lg"]})
    write(d / "value" / "players.json", {"fields": ["id", "name", "role", "league"], "rows": [["p1", "Ace Alpha", "ST", "lg"], ["p2", "Bee Alpha", "CM", "lg"], ["p3", "Cee Beta", "CB", "lg"]]})
    write(d / "value" / "season.json", {"fields": ["id", "scope", "tid", "gar"], "rows": [["p1", "club", 1, 6.0], ["p2", "club", 1, 2.0], ["p3", "club", 2, 4.0]]})

    def club(t, name, seasons, matches, national=False, years=None):
        write(d / "clubs" / f"{t}.json", {"id": int(t), "name": name, "national": national, "home": "lg" if t in CLUBS else None, "colour": "#112233",
                                          "seasons": seasons, "matches": matches, "years": years or []})
    for t, nm in CLUBS.items():
        ms = []
        if t == "1":
            # five wins, the last one at 40% (an upset); a later "finished" match after the clock is never read
            for k in range(5):
                ms.append({"id": f"m{k}", "comp": "lg", "date": iso(NOW - timedelta(days=12 - 2 * k)), "home": 1, "opp_tid": 3, "opp": "Gamma Town",
                           "status": "finished", "gf": 2, "ga": 0, "res": "W 2-0", "stage": "league"})
            ms.append({"id": "m-last", "comp": "lg", "date": iso(NOW - timedelta(days=2)), "home": 0, "opp_tid": 2, "opp": "Beta United",
                       "status": "finished", "gf": 1, "ga": 0, "res": "W 1-0", "stage": "league"})
            ms.append({"id": "m-future", "comp": "lg", "date": iso(NOW + timedelta(days=2)), "home": 0, "opp_tid": 3, "opp": "Gamma Town",
                       "status": "finished", "gf": 0, "ga": 5, "res": "L 0-5", "stage": "league"})
            ms.append({"id": "m-started", "comp": "lg", "date": iso(NOW - timedelta(hours=1)), "home": 1, "opp_tid": 4, "opp": "Delta City",
                       "status": "scheduled", "model": {"h": 0.5, "d": 0.3, "a": 0.2}})
            for k, (dd, comp, opp) in enumerate(((3, "lg", "4"), (6, "cup", "5"), (9, "lg", "2"), (12, "lg", "6"))):
                ms.append({"id": f"n{k}", "comp": comp, "date": iso(NOW + timedelta(days=dd, hours=6)), "home": 1, "opp_tid": int(opp), "opp": CLUBS[opp],
                           "status": "scheduled", "stage": "league" if comp == "lg" else "playoff", "model": {"h": 0.62, "d": 0.22, "a": 0.16}})
        seasons = [{"comp": "lg", "kind": "league", "sid": 100, "w": 7, "d": 0, "l": 1, "pos": 1, "pts": 21}, {"comp": "cup", "kind": "domestic_cup", "sid": 200}]
        if t == "6":
            ms.append({"id": "fr", "comp": "friendlies", "date": "2022-08-03T16:00:00Z", "home": 0, "opp_tid": 90, "opp": "Testland", "status": "finished",
                       "gf": 1, "ga": 1, "res": "D 1-1"})
            seasons.append({"comp": "friendlies", "kind": "international", "scope": "international", "sid": 1})
        club(t, nm, seasons, ms, national=(t == "6"), years=[{"era": "2026/27", "won": ["shield"]}] if t == "1" else None)
    club("7", "Lower Ltd", [{"comp": "cup", "kind": "domestic_cup", "sid": 200}],
         [{"id": "c1", "comp": "cup", "date": iso(NOW - timedelta(days=10)), "home": 1, "opp_tid": 5, "opp": "Echo Rovers", "status": "finished",
           "gf": 0, "ga": 1, "res": "L 0-1", "through": 0, "stage": "playoff"}])
    club("90", "Testland", [{"comp": "nl", "kind": "international", "sid": 400}],
         [{"id": "i1", "comp": "nl", "date": iso(NOW + timedelta(days=14)), "home": 1, "opp_tid": 91, "opp": "Otherland", "status": "scheduled",
           "model": {"h": 0.6, "d": 0.25, "a": 0.15}}], national=True)
    club("99", "Old Club", [{"comp": "lg", "kind": "league", "sid": 50}], [])          # no current season: no card
    return d


def card(d: Path, t: str) -> dict:
    return json.loads((d / "follow" / "club" / f"{t}.json").read_text(encoding="utf-8"))


def test_a_small_card_for_every_side_with_a_current_season(tmp_path):
    d = tree(tmp_path)
    out = B.build(d, NOW)
    assert out["ids"] == sorted(list(CLUBS) + ["7", "90"]) and out["max"] <= FL.MAX_BYTES
    for t in out["ids"]:
        c = card(d, t)
        assert c["k"] == f"site:club:{t}" and c["team"]["href"] == f"#/club/{t}" and FL.card_bytes(c) <= FL.MAX_BYTES
    c = card(d, "1")
    assert c["team"]["league"] == "Test League" and c["now"]["record"] == "W7 D0 L1"
    assert c["now"]["standing"]["text"] == "1st in Test League, 21 pts"
    assert c["now"]["rating"] == {"value": 1.9, "text": "1.90", "rank": 1, "of": 7, "label": "Our rating"}
    assert [p["name"] for p in c["players"]] == ["Ace Alpha", "Bee Alpha"] and c["players"][0]["href"] == "#/player/p1"
    assert c["profile"]["strong"][0]["pct"] >= 90 and len(c["profile"]["weak"]) == 2
    assert "fouls" not in {r["id"] for r in c["profile"]["strong"] + c["profile"]["weak"]}       # style metrics stay out
    assert c["champion"]["event"] == "Test Shield"
    assert 3 <= len(c["facts"]) <= 5
    texts = " ".join(f["text"] for f in c["facts"])
    assert "The Alpha" not in texts and " against the " not in texts
    # the headline chance is the title (last), with the cup's chance beside it
    cup = [x for x in c["chances"] if x["key"] == "p_cup_cup"]
    assert c["chances"][-1]["key"] == "p_title" and cup and cup[0]["label"] == "Cup title" and cup[0]["p"] == 0.3
    # a national cup still in its early rounds (the league clubs not in the draw): no chance to win it is shown
    write(d / "cup" / "bracket.json", {"p_cup": {"Alpha FC": 0.1, "Lower Ltd": 0.6}})
    B.build(d, NOW)
    assert not [x for x in card(d, "1")["chances"] if x["key"] == "p_cup_cup"]


def test_no_look_ahead(tmp_path):
    d = tree(tmp_path)
    B.build(d, NOW)
    c = card(d, "1")
    # the 0-5 loss stamped after the clock is not read; the last result is the 1-0 win we gave 40%: an upset
    assert c["now"]["form"] == "WWWWW" and c["now"]["streak"] == "W6"
    assert c["last"]["id"] == "m-last" and c["last"]["p"] == 0.4 and c["last"]["upset"] is True
    # the match that kicked off an hour ago is not "next"; our side's chance, the draw beside it
    assert [g["id"] for g in c["next"]] == ["n0", "n1", "n2"] and all(FL._dt(g["start"]) > NOW for g in c["next"])
    assert c["next"][0]["p"] == 0.62 and c["next"][0]["p_draw"] == 0.22 and c["next"][0]["href"] == "#/match/lg/n0"
    # the 7-day change: 0.60 now against 0.40 a week ago, never the later run's 0.01
    t = [x for x in c["chances"] if x["key"] == "p_title"][0]
    assert t["p"] == 0.6 and t["d7"] == 0.2
    # the home record ignores the result dated after the clock
    split = [f for f in c["facts"] if f["kind"] == "split"]
    assert not split or "W4 D0 L0" in split[0]["text"]


def test_national_teams_cups_and_the_friendly_flag(tmp_path):
    d = tree(tmp_path)
    B.build(d, NOW)
    nt = card(d, "90")
    assert nt["team"]["league"] == "National team" and nt["now"]["rating"]["rank"] == 3 and nt["now"]["rating"]["of"] == 2
    assert nt["next"][0]["opp"]["name"] == "Otherland"
    six = card(d, "6")                                     # flagged national by a 2022 friendly: still a league club
    assert six["team"]["league"] == "Test League" and "standing" in six["now"]
    low = card(d, "7")
    assert low["line"] == "Out of the Test Cup." and low["now"]["rating"]["rank"] == 40   # the pool row found by name
    assert low["next_note"] == "No fixtures scheduled yet."
    # a club with no current season has no card
    assert not (d / "follow" / "club" / "99.json").exists()


def test_a_second_title_keeps_its_own_series_and_shows_as_won(tmp_path):
    """Argentina: probs p_title is the Clausura, the daily race log's "title" is the Tabla Anual (table.json
    hist_keys). The Clausura's weekly change never reads the Tabla Anual's history, and a finished Tabla Anual with a
    certain leader is a title won (Boca, 10 Nov 2026: Clausura 24% read against the Tabla Anual's 71% as -47)."""
    d = tree(tmp_path)
    cj = json.loads((d / "competitions.json").read_text(encoding="utf-8"))
    cj["competitions"][0]["kind"] = "liga"                  # Argentina's kind: its table is not the Clausura's title
    write(d / "competitions.json", cj)
    tb = json.loads((d / "lg" / "table.json").read_text(encoding="utf-8"))
    tb.update({"hist_keys": {"title": "anual", "band": "ucl", "relegation": "relegation"}, "title_key": "p_anual",
               "title_label": "Top of the Tabla Anual", "label": "Tabla Anual", "season": "2026", "games_played": 24, "total_games": 24})
    write(d / "lg" / "table.json", tb)
    pr = json.loads((d / "lg" / "probs.json").read_text(encoding="utf-8"))
    for r in pr["teams"]:
        r["p_title"] = 0.24 if r["team"] == "Alpha FC" else 0.1
        r["p_anual"] = 1.0 if r["team"] == "Alpha FC" else 0.0
    write(d / "lg" / "probs.json", pr)
    daily = [{"d": (NOW - timedelta(days=8)).date().isoformat(), "ts": iso(NOW - timedelta(days=8)), "title": {"Alpha FC": 0.71}},
             {"d": (NOW - timedelta(days=1)).date().isoformat(), "ts": iso(NOW - timedelta(days=1)), "title": {"Alpha FC": 1.0}}]
    snaps = [{"ts": iso(NOW - timedelta(hours=5)), "title": {"Alpha FC": 0.23}, "anual": {"Alpha FC": 1.0}}]
    write(d / "lg" / "history.json", {"daily": daily, "snapshots": snaps})
    (d / "clubs" / "1.json").write_text((d / "clubs" / "1.json").read_text(encoding="utf-8").replace('"won": ["shield"]', '"won": []'),
                                        encoding="utf-8")
    B.build(d, NOW)
    c = card(d, "1")
    title = next(x for x in c["chances"] if x["key"] == "p_title")
    assert title["p"] == 0.24 and title.get("d7") is None           # no Clausura point a week back: no change, never -0.47
    assert not [x for x in c["chances"] if x["key"] == "p_anual"]  # decided: shown as won, not as a 100% chance
    assert c["champion"]["event"] == "Tabla Anual" and c["champion"]["season"] == "2026"
    # still open: the Tabla Anual row carries its own weekly change
    tb["games_played"] = 20
    write(d / "lg" / "table.json", tb)
    for r in pr["teams"]:
        r["p_anual"] = 0.9 if r["team"] == "Alpha FC" else 0.02
    write(d / "lg" / "probs.json", pr)
    B.build(d, NOW)
    c = card(d, "1")
    an = next(x for x in c["chances"] if x["key"] == "p_anual")
    assert an["label"] == "Top of the Tabla Anual" and an["p"] == 0.9 and abs(an.get("d7", 9) - (1.0 - 0.71)) < 1e-6
    assert c.get("champion") is None


def test_a_clinched_league_title_is_a_title_won(tmp_path):
    """First place certain by arithmetic (more points than any other side can still reach) is a title won; a
    simulated 100% alone is not. MLS: the overall table of a finished regular season is the Supporters' Shield."""
    assert B.clinched_first([{"pos": 1, "team": "A", "pts": 80, "played": 34}, {"pos": 2, "team": "B", "pts": 67, "played": 34}], 38, False)["team"] == "A"
    assert B.clinched_first([{"pos": 1, "team": "A", "pts": 80, "played": 34}, {"pos": 2, "team": "B", "pts": 69, "played": 33}], 38, False) is None
    assert B.clinched_first([{"pos": 1, "team": "A", "pts": 70, "played": 38}, {"pos": 2, "team": "B", "pts": 70, "played": 38}], 38, True)["team"] == "A"
    d = tree(tmp_path)
    tb = json.loads((d / "lg" / "table.json").read_text(encoding="utf-8"))
    tb["matches_per_team"] = 10                              # Alpha 21 pts with 2 left; Beta can reach 18 + 6 = 24: open
    write(d / "lg" / "table.json", tb)
    (d / "clubs" / "1.json").write_text((d / "clubs" / "1.json").read_text(encoding="utf-8").replace('"won": ["shield"]', '"won": []'),
                                        encoding="utf-8")
    B.build(d, NOW)
    assert card(d, "1").get("champion") is None
    tb["matches_per_team"] = 9                               # Beta's best is now 18 + 3 = 21, not above 21... still open
    write(d / "lg" / "table.json", tb)
    B.build(d, NOW)
    assert card(d, "1").get("champion") is None
    tb["matches_per_team"] = 8                               # nothing left for anyone: Alpha 21 > Beta 18
    write(d / "lg" / "table.json", tb)
    B.build(d, NOW)
    c = card(d, "1")
    assert c["champion"]["event"] == "Test League" and c["champion"]["season"] == "26/27"
    assert not [x for x in c["chances"] if x["key"] == "p_title"]
    assert card(d, "2").get("champion") is None
