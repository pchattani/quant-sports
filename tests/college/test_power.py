"""The Campus's power rankings adapter (oddsmarkets/college/power_build.py) on a small synthetic tree: football's weekly
snapshots (a week in play folds into Now), hockey's weekly grid, basketball's every-7-days rule (one snapshot early in
the season), the parts, records, poll ranks and the players by position."""
import json
from pathlib import Path

from oddsmarkets.college import power_build as C

TEAMS = ["1", "2", "3", "4"]


def _game(i, date, home, away, hs, as_, status="post", week=None, stype="reg"):
    g = {"id": str(i), "date": date, "status": status, "stype": stype, "home": home, "away": away}
    if status == "post":
        g.update({"hs": hs, "as": as_})
    if week is not None:
        g["week"] = week
    return g


def _season(L, paths, ratings, extra=None):
    teams = {t: {"name": f"School {t} Mascots", "short": f"School {t}", "abbr": f"S{t}", "colour": "#224466", "conference": "c1", "member": True}
             for t in TEAMS}
    st = [{"team": t, "w": 3, "l": 1, "pf": 100, "pa": 80, "gf": 12, "ga": 9, "t": 1, "streak": "W2", "rank": 5 if t == "1" else None} for t in TEAMS]
    sim = {t: {"p_title": 0.2 if t == "1" else 0.0001, "p_cfp": 0.5, "p_ncaa": 0.6} for t in TEAMS}
    d = {"ok": True, "phase": "regular", "updated_at": "2026-11-13T12:00:00Z", "teams": teams,
         "conferences": {"c1": {"name": "Conference One", "short": "C1"}}, "standings": {"c1": st},
         "ratings": ratings, "rating_paths": paths, "sim": {"teams": sim}}
    d.update(extra or {})
    return d


def _players(L):
    if L == "cfb":
        P = {f"q{i}": {"name": f"QB {i}", "team": "1", "pos": "QB", "qualified_rate": i > 0, "values": {"value_pg": float(i), "pass_yds": 100 * i}}
             for i in range(5)}
    elif L in ("mch", "wch"):
        P = {f"f{i}": {"name": f"F {i}", "team": "2", "pos": "F", "qualified": True, "values": {"gar_pg": 0.1 * i, "g": i, "a": i, "pts": 2 * i}}
             for i in range(4)}
    else:
        P = {f"g{i}": {"name": f"G {i}", "team": "3", "pos": "G", "qualified": True, "values": {"r": float(i), "pts": 10.0 + i}} for i in range(4)}
    return {"ok": True, "min_floor": {"gp": 5, "mpg": 10.0}, "players": P}


def _write(root: Path, L, S, season, games):
    (root / L / str(S)).mkdir(parents=True)
    (root / L / str(S) / "season.json").write_text(json.dumps(season), encoding="utf-8")
    (root / L / str(S) / "schedule.json").write_text(json.dumps({"ok": True, "games": games}), encoding="utf-8")
    (root / L / str(S) / "players.json").write_text(json.dumps(_players(L)), encoding="utf-8")


def _cfb(root: Path, week3_done: bool):
    # week 1 on 5 Sep, week 2 on 12 Sep, week 3: a Thursday game played (17 Sep), Saturday's (19 Sep) to come or played
    games = [_game(1, "2026-09-05T20:00:00Z", "1", "2", 30, 10, week=1), _game(2, "2026-09-05T20:00:00Z", "3", "4", 7, 21, week=1),
             _game(3, "2026-09-12T20:00:00Z", "2", "1", 3, 28, week=2), _game(4, "2026-09-12T20:00:00Z", "4", "3", 14, 17, week=2),
             _game(5, "2026-09-18T00:30:00Z", "1", "3", 24, 20, week=3),
             _game(6, "2026-09-19T20:00:00Z", "2", "4", 10, 13, status="post" if week3_done else "pre", week=3)]
    stamp = "2026-09-19" if week3_done else "2026-09-17"
    paths = {t: [["2026-09-01", 1.0 * i], ["2026-09-08", 2.0 * i], ["2026-09-15", 3.0 - i], [stamp, 4.0 - i]] for i, t in enumerate(TEAMS)}
    ratings = {t: {"rating": 4.0 - i, "off": 3.0 - i, "def": 1.0} for i, t in enumerate(TEAMS)}
    _write(root, "cfb", 2026, _season("cfb", paths, ratings), games)


def _index(root: Path, levels):
    (root / "index.json").write_text(json.dumps({"updated_at": "2026-11-13T12:00:00Z",
                                                 "levels": {L: {"current_season": S, "phase": "regular"} for L, S in levels}}))


def _doc(root, L):
    return json.loads((root / "power" / f"{L}.json").read_text(encoding="utf-8"))


def test_football_week_in_play_folds_into_now(tmp_path):
    _cfb(tmp_path, week3_done=False)
    _index(tmp_path, [("cfb", 2026)])
    res = C.build(tmp_path)
    assert res["leagues"] == ["cfb"]
    d = _doc(tmp_path, "cfb")
    # 15 Sep (after week 2) folds into Now while week 3 is still being played: the move is against week 1
    assert [s["label"] for s in d["snapshots"]] == ["Pre", "Wk 1", "Now"]
    t = {x["id"]: x for x in d["teams"]}
    assert t["1"]["rating"] == 4.0 and t["1"]["path"][-1] == 1 and t["4"]["path"][-2] == 1
    assert t["1"]["move"] == 3 and t["1"]["parts"] == {"off": 3.0, "def": 1.0}
    # the school's name, the conference and the AP rank on the sub-line, two stats, the title chance only when real
    assert t["1"]["name"] == "School 1" and t["1"]["group"] == "C1 · AP No. 5" and t["1"]["record"] == "3–1"
    assert [s["label"] for s in t["1"]["stats"]] == ["Playoff", "Point diff"] and t["1"]["chance"]["label"] == "National title"
    assert "chance" not in t["2"]
    assert t["1"]["form"] == "WWW" and t["3"]["form"] == "LWL"
    g = d["players"]["groups"][0]
    assert g["key"] == "qb" and g["n"] == 4 and g["top"][0]["name"] == "QB 4" and g["top"][0]["href"] == "#/cfb/player/q4"
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "cfb"


def test_football_completed_week_keeps_its_snapshot(tmp_path):
    _cfb(tmp_path, week3_done=True)
    _index(tmp_path, [("cfb", 2026)])
    C.build(tmp_path)
    assert [s["label"] for s in _doc(tmp_path, "cfb")["snapshots"]] == ["Pre", "Wk 1", "Wk 2", "Now"]


def test_hockey_weekly_grid_and_basketball_every_seven_days(tmp_path):
    # hockey: grid entries on 1 and 8 Oct (before that day's games) and now (10 Oct); the weekend of 9-11 Oct in play
    hk_games = [_game(1, "2026-10-09T23:00:00Z", "1", "2", 3, 3), _game(2, "2026-10-11T23:00:00Z", "3", "4", 0, 0, status="pre")]
    hk_paths = {t: [["2026-10-01", 0.1 * i], ["2026-10-08", 0.2 * i], ["2026-10-10", 0.5 - 0.1 * i]] for i, t in enumerate(TEAMS)}
    hk_r = {t: {"rating": 0.5 - 0.1 * i, "off": 0.3 - 0.1 * i, "def": 0.2} for i, t in enumerate(TEAMS)}
    _write(tmp_path, "mch", 2027, _season("mch", hk_paths, hk_r), hk_games)
    # basketball: end-of-day entries 7 and 13 Nov: nothing is a week old yet, so Now alone
    bb_paths = {t: [["2026-11-07", 1.0 * i], ["2026-11-13", 2.0 * i]] for i, t in enumerate(TEAMS)}
    bb_r = {t: {"rating": 10.0 - i, "off": 105.0 - i, "def": 95.0} for i, t in enumerate(TEAMS)}
    _write(tmp_path, "mbb", 2027, _season("mbb", bb_paths, bb_r), [_game(1, "2026-11-13T23:00:00Z", "1", "2", 70, 60)])
    _index(tmp_path, [("mch", 2027), ("mbb", 2027)])
    res = C.build(tmp_path)
    assert res["leagues"] == ["mbb", "mch"]
    hk = _doc(tmp_path, "mch")
    assert [s["label"] for s in hk["snapshots"]] == ["1 Oct", "Now"]
    h1 = {x["id"]: x for x in hk["teams"]}["1"]
    assert h1["record"] == "3–1–1" and h1["group"] == "C1 · USCHO No. 5" and h1["stats"][1] == {"label": "Goal diff", "text": "+3"}
    assert h1["form"] == "T" and [p["label"] for p in hk["parts"]] == ["Attack", "Defence"]
    bb = _doc(tmp_path, "mbb")
    assert [s["label"] for s in bb["snapshots"]] == ["Now"] and bb["season_label"] == "2026–27 season"
    b1 = {x["id"]: x for x in bb["teams"]}["1"]
    # basketball's parts: offence and defence each against the national average, adding up to the rating
    assert abs(b1["parts"]["off"] + b1["parts"]["def"] - b1["rating"]) < 0.02
    assert bb["players"]["groups"][0]["key"] == "g" and bb["players"]["groups"][0]["min"] == "5+ games and 10 minutes a game"


def test_basketball_takes_the_entry_a_week_back():
    paths = {"1": [["2026-11-07", 1.0], ["2026-11-14", 2.0], ["2026-11-20", 3.0]]}
    cands, now = C.snapshot_dates("mbb", paths, [])
    # now is 20 Nov; 13 Nov is the line, so the 7 Nov entry stands for it (14 Nov is less than a week before now)
    assert [c.isoformat() for c in cands] == ["2026-11-07"] and now.isoformat() == "2026-11-20"
    assert C.value_at(paths["1"], cands[0]) == 1.0
