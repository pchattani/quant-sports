"""The Hardwood's power rankings adapter (oddsmarkets/basketball/analytics/power_build.py) on a small synthetic tree."""
import json
from datetime import date, timedelta
from pathlib import Path

from oddsmarkets.basketball.analytics import power_build as P

TIDS = ["1", "2", "3", "4"]


def _league(root: Path, L: str, S: int, phase: str, start: date, n_days: int, late: str | None = None):
    d = root / L / str(S)
    d.mkdir(parents=True)
    paths, games = {t: [] for t in TIDS}, []
    for k in range(n_days):
        day = start + timedelta(days=k)
        for a, b in (("1", "2"), ("3", "4")):
            if late == a and k < 3:
                continue                      # team `late` (and its opponent) start three days later
            hw = (k + int(a)) % 3 != 0
            gid = f"{L}{k}{a}"
            games.append({"id": gid, "date": f"{day.isoformat()}T23:30:00Z", "status": "post", "stype": "reg", "home": a, "away": b,
                          "hs": 100 if hw else 90, "as": 90 if hw else 100})
            for t, sign in ((a, 1 if hw else -1), (b, -1 if hw else 1)):
                last = paths[t][-1]["net"] if paths[t] else 0.0
                bias = {"1": 3.0, "2": 1.0, "3": -1.0, "4": -3.0}[t] * 0.1
                paths[t].append({"date": day.isoformat(), "game": gid, "net": round(last + sign * 0.5 + bias, 3), "se": 3.0})
    teams = {t: {"name": f"Team {t}", "abbr": f"T{t}", "short": f"T{t}s", "colour": "#224466", "conference": "East" if t in "12" else "West"} for t in TIDS}
    standings = {"East": [{"team": t, "w": 5, "l": 3, "pd": 20 - 10 * int(t), "streak": "W1"} for t in "12"],
                 "West": [{"team": t, "w": 3, "l": 5, "pd": 20 - 10 * int(t), "streak": "L1"} for t in "34"]}
    sim = {t: {"p_title": 0.4 - 0.1 * int(t), "p_playoffs": 0.9, "exp_w": 50.4} for t in TIDS} if phase == "regular" else None
    post = {"series": [{"teams": ["1", "3"], "rnum": 1, "round": "Semi-finals", "rkey": "semis", "winner": "1"},
                       {"teams": ["1", "2"], "rnum": 2, "round": "Finals", "rkey": "finals", "winner": "2"}]} if phase == "offseason" else None
    (d / "season.json").write_text(json.dumps({"updated_at": "2026-11-14T01:00:00Z", "phase": phase, "teams": teams, "standings": standings,
                                               "rating_paths": paths, "sim": {"teams": sim} if sim else None, "postseason": post}))
    (d / "schedule.json").write_text(json.dumps({"games": games}))
    pl = {}
    for j in range(12):
        role = "GWB"[j % 3]
        pl[f"p{L}{j}"] = {"name": f"Player {j}", "team": TIDS[j % 4], "role": role, "qualified": j != 0,
                          "values": {"hpm": j - 5.0, "pts_g": 10 + j, "ast_g": 2.0, "reb_g": 4.0, "ts": 0.58, "tpm_g": 1.5, "stl_g": 1.0, "blk_g": 0.5}}
    (d / "players.json").write_text(json.dumps({"min_floor": 94, "players": pl}))
    (d / "performers.json").write_text(json.dumps({"views": [{"key": "all", "min": "94 minutes so far"}]}))
    return {"name": L.upper(), "current_season": S, "phase": phase, "teams": teams}


def _tree(root: Path):
    ix = {"updated_at": "2026-11-14T01:00:00Z", "leagues": {
        "nba": _league(root, "nba", 2027, "regular", date(2026, 10, 20), 24, late="3"),
        "wnba": _league(root, "wnba", 2026, "offseason", date(2026, 8, 1), 70)}}
    (root / "index.json").write_text(json.dumps(ix))


def test_snapshots_every_seven_days_back_from_the_last_game(tmp_path):
    _tree(tmp_path)
    res = P.build(tmp_path)
    assert res["leagues"] == ["nba", "wnba"]
    d = json.loads((tmp_path / "power" / "nba.json").read_text(encoding="utf-8"))
    # last game 12 Nov; 22 Oct goes (teams 3 and 4 had not played yet), so 29 Oct, 5 Nov and now
    assert [s["date"] for s in d["snapshots"]] == ["2026-10-29", "2026-11-05", "2026-11-12"]
    assert [s["label"] for s in d["snapshots"]] == ["29 Oct", "5 Nov", "Now"]
    one = d["teams"][0]
    assert one["id"] == "1" and one["href"] == "#/nba/team/1" and one["record"] == "5–3"
    assert all(len(t["path"]) == 3 for t in d["teams"])
    # the snapshot value is the team's last path entry dated that day or earlier (the rating after that day's games)
    sj = json.loads((tmp_path / "nba" / "2027" / "season.json").read_text(encoding="utf-8"))
    want = [e["net"] for e in sj["rating_paths"]["1"] if e["date"] <= "2026-11-05"][-1]
    assert abs(one["rpath"][1] - want) < 0.01 and one["rating"] == sj["rating_paths"]["1"][-1]["net"]
    assert one["chance"]["label"] == "NBA title" and [s["label"] for s in one["stats"]] == ["Point diff", "Proj. wins", "Playoffs"]
    assert d["parts"] == [] and len(one["form"]) == 5
    g = {x["key"]: x for x in d["players"]["groups"]}
    assert set(g) == {"guards", "wings", "bigs"} and g["guards"]["n"] == 3        # p0 (a guard) is not qualified
    assert g["bigs"]["top"][0]["href"] == "#/nba/player/pnba11" and g["bigs"]["top"][0]["team"] == "T4"
    assert g["bigs"]["min"] == "94 minutes so far"
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "nba" and [x["league"] for x in idx["leagues"]] == ["nba", "wnba"]


def test_offseason_reads_final(tmp_path):
    _tree(tmp_path)
    P.build(tmp_path)
    d = json.loads((tmp_path / "power" / "wnba.json").read_text(encoding="utf-8"))
    assert d["phase"] == "offseason" and d["season_label"] == "2026 season"
    assert len(d["snapshots"]) == 10 and d["snapshots"][-1]["label"] == "Final" and d["snapshots"][-1]["date"] == "2026-10-09"
    assert all("chance" not in t for t in d["teams"])
    by = {t["id"]: t for t in d["teams"]}
    assert {s["label"]: s["text"] for s in by["2"]["stats"]}["Playoffs"] == "Champions"
    assert {s["label"]: s["text"] for s in by["3"]["stats"]}["Playoffs"] == "Semi-finals"
    assert {s["label"]: s["text"] for s in by["4"]["stats"]}["Playoffs"] == "Missed"
    assert "Won the 2026 WNBA title" in by["2"]["note"]
