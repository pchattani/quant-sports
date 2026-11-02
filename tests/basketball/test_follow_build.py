"""oddsmarkets/basketball/analytics/follow_build.py: the Hardwood's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.basketball.analytics import follow_build as B
from oddsmarkets.common import follow as FL

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
TEAMS = {"1": ("Alpha Ants", "ANT", "Ants", "East", "#13294b"), "2": ("Beta Bees", "BEE", "Bees", "East", "#c41e3a"),
         "3": ("Gamma Goats", "GOA", "Goats", "East", "#005a9c"), "4": ("Delta Ducks", "DUK", "Ducks", "West", "#fd5a1e"),
         "5": ("Echo Eels", "EEL", "Eels", "West", "#003087"), "6": ("Foxtrot Foxes", "FOX", "Foxes", "West", "#27251f")}


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path, finals: str | None = None) -> Path:
    """A WNBA-like league. finals: None (a regular season), "live" (the Finals at 3-3, Game 7 to come), "done" (team 1
    won Game 7)."""
    data = tmp / "data"
    L, S = "wnba", 2026
    games, gid = [], 1000
    for d in range(40, 10, -1):
        t = NOW - timedelta(days=d)
        for h, a in (("1", "2"), ("3", "4"), ("5", "6")):
            gid += 1
            hs, as_ = (90, 80) if h == "1" or d % 2 else (70, 75)
            games.append({"id": str(gid), "season": S, "date": iso(t), "status": "post", "stype": "reg", "home": h, "away": a, "hs": hs, "as": as_,
                          "model": {"p_home": 0.35 if h == "1" else 0.5}})
    # a result stamped after the build clock: never read
    games.append({"id": "9999", "season": S, "date": iso(NOW + timedelta(days=1)), "status": "post", "stype": "reg", "home": "2", "away": "1", "hs": 99, "as": 50,
                  "model": {"p_home": 0.5}})
    series = []
    phase = "regular"
    if finals:
        phase = "playoffs"
        fg = []
        for k in range(6):
            gid += 1
            t = NOW - timedelta(days=9 - k)
            h, a = ("1", "4") if k % 2 == 0 else ("4", "1")
            win1 = k < 3
            hs, as_ = (80, 70) if (h == "1") == win1 else (70, 80)
            fg.append({"id": str(gid), "season": S, "date": iso(t), "status": "post", "stype": "post", "home": h, "away": a, "hs": hs, "as": as_,
                       "model": {"p_home": 0.5}, "series": {"round": "WNBA Finals"}})
        g7 = {"id": "7777", "season": S, "date": iso(NOW - timedelta(hours=20)) if finals == "done" else iso(NOW + timedelta(hours=8)),
              "status": "post" if finals == "done" else "pre", "stype": "post", "home": "1", "away": "4", "hs": 81 if finals == "done" else None,
              "as": 77 if finals == "done" else None, "model": {"p_home": 0.55}, "market": {"p_home": 0.52}, "series": {"round": "WNBA Finals"}}
        games += fg + [g7]
        series = [{"teams": ["1", "4"], "stype": "post", "wins": {"1": 3, "4": 3}, "round": "WNBA Finals", "rkey": "finals", "rnum": 2, "best_of": 7, "winner": None,
                   "summary": "Series tied 3-3"},
                  {"teams": ["2", "3"], "stype": "post", "wins": {"2": 0, "3": 3}, "round": "Semi-finals", "rnum": 1, "best_of": 5, "winner": "3", "summary": "GOA wins series 3-0"},
                  {"teams": ["3", "1"], "stype": "post", "wins": {"3": 1, "1": 3}, "round": "Semi-finals", "rnum": 1, "best_of": 5, "winner": "1", "summary": "ANT wins series 3-1"}]
    else:
        for k, dd in enumerate((1, 2, 3, 4)):
            games.append({"id": str(5000 + k), "season": S, "date": iso(NOW + timedelta(days=dd)), "status": "pre", "stype": "reg", "home": "1", "away": "3",
                          "model": {"p_home": 0.62}, "market": {"p_home": 0.6}})
    write(data / L / str(S) / "schedule.json", {"ok": True, "games": games})
    st = {}
    for t, (nm, ab, sh, conf, col) in TEAMS.items():
        w = 28 if t == "1" else 14
        st.setdefault(conf, []).append({"team": t, "w": w, "l": 30 - w, "pct": w / 30, "gb": 0.0 if t in ("1", "4") else 14.0, "home": [w // 2, 15 - w // 2],
                                        "away": [w - w // 2, 15 - (w - w // 2)], "streak": "W3", "seed": int(t)})
    prof = [{"id": "model_net", "label": "Adjusted net rating", "dir": "higher", "fmt": "+1", "model": True},
            {"id": "model_off", "label": "Adjusted offence", "fmt": "1", "model": True}, {"id": "model_def", "label": "Adjusted defence", "dir": "lower", "fmt": "1", "model": True},
            {"id": "pace", "label": "Pace", "fmt": "1", "style": True}, {"id": "efg", "label": "Effective FG", "fmt": "pct1"}, {"id": "tov_pct", "label": "Turnover rate", "dir": "lower", "fmt": "pct1"}]
    lteams = {t: {"pct": {m["id"]: (95 if t == "1" else 40) - 8 * i for i, m in enumerate(prof)},
                  "vals": {"model_net": 9.0 if t == "1" else float(t) - 4, "model_off": 110.0 if t == "1" else 100.0 + int(t), "model_def": 95.0 if t == "1" else 100.0 + int(t),
                           "pace": 80.0, "efg": 0.55 if t == "1" else 0.48 + 0.002 * int(t), "tov_pct": 0.12 if t == "1" else 0.14 + 0.001 * int(t)},
                  "luck": {"a": 28, "x": 24, "d": 4.0 if t == "1" else 0.0}} for t in TEAMS}
    sim = {t: {"p_playoffs": 0.97 if t == "1" else 0.4, "p_title": 0.45 if t == "1" else 0.1, "exp_w": 30.0, "exp_l": 14.0} for t in TEAMS}
    write(data / L / str(S) / "season.json", {"ok": True, "phase": phase, "teams": {t: {"name": v[0], "abbr": v[1], "short": v[2], "conference": v[3], "colour": v[4]} for t, v in TEAMS.items()},
                                              "standings": st, "sim": {"teams": sim}, "ratings": {t: {"net": 9.0 if t == "1" else float(t) - 4, "off": 110.0, "def": 101.0} for t in TEAMS},
                                              "power": [[t, 9.0 if t == "1" else float(t) - 4, 0] for t in sorted(TEAMS, key=lambda x: -(9.0 if x == "1" else float(x) - 4))],
                                              "postseason": {"series": series}, "format": {"series": [5, 7]},
                                              "league_block": {"profile": {"metrics": prof, "min_gp": 10}, "teams": lteams, "race": {}}})
    write(data / L / str(S) / "teams.json", {"ok": True, "teams": {t: {"name": TEAMS[t][0], "roster": [
        {"id": f"{t}01", "name": f"Star {TEAMS[t][2]}", "pos": "G", "hpm": 6.0 if t == "1" else 1.0, "mpg": 33, "gp": 30, "min": 990},
        {"id": f"{t}02", "name": f"Big {TEAMS[t][2]}", "pos": "C", "hpm": 2.0, "mpg": 28, "gp": 30, "min": 840}]} for t in TEAMS}})
    cols = ["id", "name", "team", "pos", "war", "q"]
    write(data / L / str(S) / "value.json", {"ok": True, "cols": cols, "rows": [[f"{t}01", f"Star {TEAMS[t][2]}", t, "G", 7.0 if t == "1" else 2.0, 1] for t in TEAMS]})
    write(data / L / str(S - 1) / "teams.json", {"ok": True, "teams": {t: {"log": [{"date": f"2025-06-{d:02d}", "res": "W" if d % 3 else "L"} for d in range(1, 31)]} for t in TEAMS}})
    write(data / L / "race_log.json", {str(S): {"p_title": {(NOW - timedelta(days=8)).date().isoformat(): {"1": 0.20}, (NOW - timedelta(days=1)).date().isoformat(): {"1": 0.45},
                                                            (NOW + timedelta(days=2)).date().isoformat(): {"1": 0.99}}, "_meta": {"live_from": "2026-01-01"}}})
    write(data / L / "history.json", {"first_season": 1997, "champions": [[2010, "4"], [2020, "4"]]})
    for s in (2023, 2024, 2025):
        write(data / L / str(s) / "season.json", {"teams": {t: {} for t in TEAMS if t != "1" or s >= 2025}})
    idx = {"ok": True, "leagues": {L: {"name": "WNBA", "current_season": S, "seasons": [2023, 2024, 2025, 2026], "phase": phase,
                                       "teams": {t: {"name": v[0], "abbr": v[1], "short": v[2], "conference": v[3], "colour": v[4]} for t, v in TEAMS.items()},
                                       "champions": [[2010, "4"], [2020, "4"]]}}}
    write(data / "index.json", idx)
    return data


def cards(data: Path) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "follow" / "wnba").glob("*.json")}


def test_a_card_for_every_team_under_the_ceiling(tmp_path):
    data = tree(tmp_path)
    s = B.build(data, "wnba", NOW)
    assert s["n"] == len(TEAMS) and sorted(s["ids"]) == sorted(TEAMS)
    assert s["max"] <= FL.MAX_BYTES
    c = cards(data)["1"]
    assert c["k"] == "hardwood:wnba:1" and c["team"]["href"] == "#/wnba/team/1" and c["phase"] == "season"
    assert c["now"]["rating"]["rank"] == 1 and c["now"]["standing"]["text"].startswith("1st in the East")
    assert [x["key"] for x in c["chances"]] == ["p_playoffs", "p_title"] and abs(c["chances"][-1]["d7"] - 0.25) < 1e-9
    assert len(c["next"]) == 3 and c["next"][0]["p"] == 0.62 and c["next"][0]["mkt"] == 0.6
    assert c["players"][0]["metric"] == "WAR" and c["players"][0]["name"] == "Star Ants"
    kinds = {f["kind"] for f in c["facts"]}
    assert 3 <= len(c["facts"]) <= 5 and len(kinds) == len(c["facts"])
    assert {"pctl", "player_rank"} & kinds


def test_no_look_ahead(tmp_path):
    data = tree(tmp_path)
    B.build(data, "wnba", NOW)
    c = cards(data)["1"]
    # the 99-50 loss dated tomorrow is not the last result, and the race-log point after now is not the chance move
    assert c["last"]["id"] != "9999" and c["last"]["res"] == "W"
    assert c["chances"][-1]["d7"] == 0.25


def test_long_shot_headline_is_the_playoffs(tmp_path):
    data = tree(tmp_path)
    sj = data / "wnba" / "2026" / "season.json"
    d = json.loads(sj.read_text())
    d["sim"]["teams"]["2"]["p_title"] = 0.01
    sj.write_text(json.dumps(d))
    B.build(data, "wnba", NOW)
    assert [x["key"] for x in cards(data)["2"]["chances"]] == ["p_title", "p_playoffs"]


def test_finals_in_progress(tmp_path):
    data = tree(tmp_path, finals="live")
    B.build(data, "wnba", NOW)
    c = cards(data)
    assert c["1"]["phase"] == "postseason" and "level 3–3 with the Ducks" in c["1"]["line"]
    assert [x["key"] for x in c["1"]["chances"]] == ["p_title"]
    assert c["1"]["next"][0]["comp"] == "WNBA Finals · Game 7"
    assert c["2"]["line"].startswith("Out in the Semi-finals, 0–3 to the Goats")


def test_decided_finals_is_the_champion_state(tmp_path):
    data = tree(tmp_path, finals="done")
    B.build(data, "wnba", NOW)
    c = cards(data)
    ch = c["1"]
    assert ch["phase"] == "offseason" and ch["champion"]["event"] == "WNBA" and ch["champion"]["season"] == 2026
    assert ch["line"] == "Won the 2026 WNBA Finals, 4–3 over the Ducks."
    assert "form" not in ch["now"] and "chances" not in ch and ch["next_note"].startswith("Off-season")
    facts = {f["kind"]: f["text"] for f in ch["facts"]}
    assert facts["champion"].startswith("2026 WNBA champions, 4–3 over the Ducks")
    assert facts["franchise"] == "The first WNBA title in franchise history, in their 2nd season."
    ru = c["4"]
    assert ru["phase"] == "offseason" and "champion" not in ru and ru["line"] == "Season over: out in the WNBA Finals, 3–4 to the Ants."
    # a team that had won before gets "since", never "first"
    assert not any(f["kind"] == "franchise" and "first" in f["text"] for f in ru["facts"])
