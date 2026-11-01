"""oddsmarkets/baseball/analytics/follow_build.py: the Bullpen's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.baseball.analytics import follow_build as B
from oddsmarkets.common import follow as FL

NOW = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)
TEAMS = {"1": ("Alpha Ants", "ANT", "Ants", "AL East", "#13294b"), "2": ("Beta Bees", "BEE", "Bees", "AL East", "#c41e3a"),
         "3": ("Gamma Goats", "GOA", "Goats", "AL East", "#005a9c"), "4": ("Delta Ducks", "DUK", "Ducks", "NL West", "#fd5a1e"),
         "5": ("Echo Eels", "EEL", "Eels", "NL West", "#003087"), "6": ("Foxtrot Foxes", "FOX", "Foxes", "NL West", "#27251f")}


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path, phase: str = "regular", champion: str | None = None) -> Path:
    data = tmp / "data"
    games, gpk = [], 1000
    # 30 days of results: team 1 wins every game, the others split; each day 1 v 2, 3 v 4, 5 v 6
    for d in range(30, 0, -1):
        t = NOW - timedelta(days=d)
        for h, a in (("1", "2"), ("3", "4"), ("5", "6")):
            gpk += 1
            hs, as_ = (5, 2) if h == "1" or d % 2 else (1, 3)
            games.append({"gpk": str(gpk), "date": t.date().isoformat(), "start": iso(t), "status": "final", "gtype": "R", "home": h, "away": a,
                          "hs": hs, "as": as_, "model": {"p_home": 0.35 if h == "1" else 0.5}})
    # a result stamped after the build clock (a later rebuild's data in the tree): never read
    games.append({"gpk": "9999", "date": (NOW + timedelta(days=1)).date().isoformat(), "start": iso(NOW + timedelta(days=1)), "status": "final",
                  "gtype": "R", "home": "2", "away": "1", "hs": 9, "as": 0, "model": {"p_home": 0.5}})
    # upcoming: two days ahead, plus a game that already started an hour ago (not "next")
    for k, dd in enumerate((1, 2, 3, 4)):
        t = NOW + timedelta(days=dd, hours=1)
        games.append({"gpk": str(5000 + k), "date": t.date().isoformat(), "start": iso(t), "status": "pre", "gtype": "R", "home": "1", "away": "3",
                      "model": {"p_home": 0.62}, "market": {"p_home": 0.6}})
    games.append({"gpk": "4999", "date": NOW.date().isoformat(), "start": iso(NOW - timedelta(hours=1)), "status": "pre", "gtype": "R", "home": "4", "away": "1",
                  "model": {"p_home": 0.5}})
    write(data / "mlb" / "2026" / "schedule.json", {"ok": True, "games": games})
    rows = {}
    for t, (nm, ab, sh, div, col) in TEAMS.items():
        w = 30 if t == "1" else 15
        rows.setdefault(div, []).append({"tid": t, "name": nm, "abbr": ab, "short": sh, "league": div[:2], "division": div, "w": w, "l": 30 - w,
                                         "pct": w / 30, "gb": 0.0 if t in ("1", "4") else 15.0, "rating": 1.2 if t == "1" else 0.0,
                                         "p_postseason": 0.97 if t == "1" else 0.3, "p_ws": 0.31 if t == "1" else 0.05})
    prof = [{"id": "rating", "label": "Team rating", "dir": "higher", "fmt": "+2", "model": True}, {"id": "woba", "label": "Lineup wOBA", "fmt": "3"},
            {"id": "k_pct", "label": "Strikeout rate", "dir": "lower", "fmt": "pct1"}, {"id": "war_sp", "label": "Rotation WAR", "fmt": "1"},
            {"id": "def_rpg", "label": "Defence", "fmt": "+2"}, {"id": "framing_runs", "label": "Framing", "fmt": "+1"}]
    lteams = {t: {"pct": {m["id"]: (95 if t == "1" else 50) - 10 * i for i, m in enumerate(prof)},
                  "vals": {"rating": 1.2 if t == "1" else 0.0, "woba": 0.350 if t == "1" else 0.310, "k_pct": 0.18 if t == "1" else 0.23,
                           "war_sp": 18.0 if t == "1" else 9.0, "def_rpg": -0.2 if t == "1" else 0.1, "framing_runs": -9.0 if t == "1" else 1.0},
                  "luck": {"a": 30.0, "x": 25.0, "d": 5.0 if t == "1" else 0.0}} for t in TEAMS}
    race = {t: {"sos": [0.2, 1 if t == "1" else 4, 120]} | ({"magic": 7} if t == "1" else {}) for t in TEAMS}
    write(data / "mlb" / "2026" / "season.json", {"ok": True, "phase": phase, "standings": rows,
                                                  "ratings": {t: {"total": 1.2 if t == "1" else 0.1 * int(t)} for t in TEAMS},
                                                  "league": {"profile": {"metrics": prof}, "teams": lteams, "race": race}})
    write(data / "mlb" / "2026" / "teams.json", {"ok": True, "teams": {t: {"name": TEAMS[t][0], "roster": [
        {"pid": f"{t}01", "name": f"Ace {TEAMS[t][2]}", "pos": "SP", "kind": "pitcher", "war": 6.5 if t == "1" else 2.0},
        {"pid": f"{t}02", "name": f"Bat {TEAMS[t][2]}", "pos": "SS", "kind": "hitter", "war": 4.0}]} for t in TEAMS}})
    write(data / "mlb" / "2025" / "season.json", {"ok": True, "standings": {"AL East": [{"tid": t, "w": 20, "l": 40} for t in TEAMS]}})
    write(data / "mlb" / "race_log.json", {"2026": {"p_postseason": {iso(NOW - timedelta(days=8))[:10]: {"1": 0.70}, iso(NOW - timedelta(days=1))[:10]: {"1": 0.97},
                                                                     iso(NOW + timedelta(days=2))[:10]: {"1": 0.10}}}})
    idx = {"ok": True, "season": 2026, "phase": phase, "levels": {"mlb": {"season": 2026, "phase": phase}},
           "teams": {t: {"name": v[0], "abbr": v[1], "short": v[2], "league": v[3][:2], "division": v[3], "colour": v[4]} for t, v in TEAMS.items()},
           "postseason": {"series": [], "teams": {}}}
    if champion:
        idx["digest"] = {"stage": {"title": {"event": "World Series", "champion": champion, "runner_up": "4", "result": [4, 2], "pre_p": 0.31, "pre_rank": 1, "pre_n": 12}}}
        idx["postseason"] = {"series": [{"round": "WS", "round_name": "World Series", "teams": [champion, "4"], "wins": [4, 2], "done": True, "winner": champion}], "teams": {}}
    write(data / "index.json", idx)
    write(data / "mlb" / "team_history.json", {"franchises": {"ANT": {"tid": "1", "first": 1969, "last": 2025, "titles": 0, "best": {"season": 2011, "w": 96, "l": 66, "pct": 0.593}}}})
    return data


def read(data: Path, tid: str) -> dict:
    return json.loads((data / "follow" / "mlb" / f"{tid}.json").read_text(encoding="utf-8"))


def test_every_club_gets_a_small_card(tmp_path):
    data = tree(tmp_path)
    out = B.build(data, "mlb", NOW)
    assert out["ids"] == sorted(TEAMS) and out["max"] <= FL.MAX_BYTES
    for t in TEAMS:
        c = read(data, t)
        assert c["k"] == f"bullpen:mlb:{t}" and c["team"]["href"] == f"#/mlb/team/{t}" and c["phase"] == "season"
        assert FL.card_bytes(c) <= FL.MAX_BYTES
    c = read(data, "1")
    assert c["now"]["record"] == "30–0" and c["now"]["standing"]["text"] == "1st in the AL East"
    assert c["now"]["rating"]["rank"] == 1 and c["now"]["rating"]["text"] == "+1.20"
    assert c["team"]["colour"] == "#13294b" and c["team"]["league"] == "MLB"
    assert [p["name"] for p in c["players"]] == ["Ace Ants", "Bat Ants"] and c["players"][0]["href"] == "#/mlb/pitcher/101"
    assert c["profile"]["strong"][0]["label"] == "Team rating" and len(c["profile"]["weak"]) == 2
    assert 3 <= len(c["facts"]) <= 5


def test_no_look_ahead_in_the_card(tmp_path):
    data = tree(tmp_path)
    B.build(data, "mlb", NOW)
    c = read(data, "1")
    # the 9-0 loss stamped after the build clock is not read: still 30 straight wins, the last a win
    assert c["now"]["form"] == "WWWWW" and c["now"]["streak"] == "W30"
    assert c["last"]["res"] == "W" and c["last"]["id"] != "9999"
    # the game that started an hour ago is not "next"; the next three are all after the clock
    assert [g["id"] for g in c["next"]] == ["5000", "5001", "5002"]
    assert all(FL._dt(g["start"]) > NOW for g in c["next"])
    assert c["next"][0]["p"] == 0.62 and c["next"][0]["mkt"] == 0.6 and c["next"][0]["opp"]["name"] == "Goats"
    # the 7-day change: 0.97 now against 0.70 a week ago, never the later 0.10
    pp = [x for x in c["chances"] if x["key"] == "p_postseason"][0]
    assert pp["p"] == 0.97 and pp["d7"] == 0.27
    # the last result's pre-game chance is the frozen one (35%): a win at that price is an upset
    assert c["last"]["p"] == 0.35 and c["last"]["upset"] is True
    texts = " ".join(f["text"] for f in c["facts"])
    assert "won 30 in a row" in texts


def test_offseason_champion_card(tmp_path):
    data = tree(tmp_path, phase="offseason", champion="1")
    B.build(data, "mlb", NOW)
    c = read(data, "1")
    assert c["phase"] == "offseason" and "form" not in c["now"] and "streak" not in c["now"] and "chances" not in c
    assert c["line"] == "Won the 2026 World Series, 4–2 over the Ducks." and c["champion"]["event"] == "World Series"
    assert c["next_note"] == "Off-season. The 2027 schedule is not out yet."
    k = [f["kind"] for f in c["facts"]]
    assert k[0] == "champion" and "franchise" in k and not set(k) & FL.LIVE_KINDS
    assert "first World Series title in franchise history, in their 58th season" in " ".join(f["text"] for f in c["facts"])
    lost = read(data, "4")
    assert lost["line"] == "Season over: out in the World Series, 2–4 to the Ants."
    # next season's schedule out: Opening Day is named
    write(data / "mlb" / "2027" / "schedule.json", {"games": [{"gtype": "R", "date": "2027-03-25"}, {"gtype": "S", "date": "2027-02-20"}]})
    B.build(data, "mlb", NOW)
    assert read(data, "5")["next_note"] == "Off-season. Opening Day 2027: Thu 25 Mar 2027."
