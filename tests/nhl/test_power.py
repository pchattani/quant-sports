"""The Rink's power rankings adapter (oddsmarkets/nhl/analytics/power_build.py) on a small synthetic tree."""
import json
from pathlib import Path

from oddsmarkets.nhl.analytics import power_build as P

S = 20262027
CLUBS = ["AAA", "BBB", "CCC", "DDD"]


def _tree(root: Path, last_game: str, phase: str = "regular"):
    (root / str(S)).mkdir(parents=True)
    teams, rows = {}, []
    for i, a in enumerate(CLUBS):
        sched = []
        for k, d in enumerate(["2026-10-01", "2026-10-08", "2026-10-15", last_game]):
            res = "W" if (k + i) % 2 == 0 else ("OTL" if i == 3 else "L")
            sched.append({"game_id": f"{i}{k}", "date": d, "opp": CLUBS[(i + 1) % 4], "status": "final", "result": res,
                          "gf": 3 if res == "W" else 2, "ga": 2 if res == "W" else 3})
        sched.append({"game_id": f"{i}9", "date": "2026-12-01", "opp": "AAA", "status": "pre"})
        gf, ga = 3.2 - 0.2 * i, 2.8 + 0.1 * i
        teams[a] = {"name": f"City {a}s", "units": {"rating": round(gf - ga, 3), "model": {"gf_g": gf, "ga_g": ga}},
                    "schedule": sched, "sim": {"p_cup": 0.3 - 0.05 * i, "p_playoffs": 0.9 - 0.2 * i}}
        rows.append({"team": a, "w": 2, "l": 1, "otl": 1, "pts": 5, "gf": 10, "ga": 9 + i, "streak": "W1"})
    (root / "index.json").write_text(json.dumps({"season": S, "phase": phase,
                                                 "teams": {a: {"name": f"City {a}s", "colour": "#123456", "division": "Atlantic"} for a in CLUBS}}))
    (root / str(S) / "teams.json").write_text(json.dumps({"updated_at": "2026-10-20T12:00:00Z", "phase": phase, "teams": teams}))
    (root / str(S) / "season.json").write_text(json.dumps({"phase": phase, "standings": {"rows": rows}}))
    # Mondays: DDD best, then it slides; the 19 Oct point is the latest
    weeks = ["2026-10-05", "2026-10-12", "2026-10-19"]
    hist = {"AAA": [0.1, 0.2, 0.3], "BBB": [0.0, 0.0, 0.1], "CCC": [-0.1, -0.2, 0.0], "DDD": [0.5, 0.4, 0.2]}
    ranks = {a: [sorted(hist, key=lambda x: -hist[x][k]).index(a) + 1 for k in range(3)] for a in hist}
    (root / str(S) / "rating_history.json").write_text(json.dumps({"ok": True, "season": S, "weeks": weeks, "teams": hist, "ranks": ranks}))
    sk = {}
    for j in range(16):
        pos = ["C", "L", "R", "D"][j % 4]
        sk[f"p{j}"] = {"name": f"Skater {j}", "team": CLUBS[j % 4], "pos": pos, "qualified": j != 11,
                       "values": {"gar_60": 0.05 * j, "gar": j / 2, "p": j, "g": j // 2, "p60": 1.0 + j / 10, "fo_pct": 0.5}}
    (root / str(S) / "skaters.json").write_text(json.dumps({"players": sk}))
    gk = {f"g{j}": {"name": f"Goalie {j}", "team": CLUBS[j], "pos": "G", "qualified": True, "values": {"gsax": 2.0 * j - 3, "sv_pct": 0.9}}
          for j in range(4)}
    (root / str(S) / "goalies.json").write_text(json.dumps({"players": gk}))


def _doc(root: Path):
    return json.loads((root / "power" / "nhl.json").read_text(encoding="utf-8"))


def test_monday_points_and_the_week_in_play(tmp_path):
    # latest game Thu 22 Oct: the 19 Oct Monday's games end 18 Oct, under a week before 22 Oct, so it folds into now
    _tree(tmp_path, "2026-10-22")
    res = P.build(tmp_path)
    assert res["leagues"] == ["nhl"]
    d = _doc(tmp_path)
    assert [s["label"] for s in d["snapshots"]] == ["5 Oct", "12 Oct", "Now"]
    assert d["snapshots"][-1]["date"] == "2026-10-22"
    top = d["teams"][0]
    assert top["id"] == "AAA" and top["rank"] == 1 and top["prev"] == 2        # now 0.4: AAA leads, DDD (0.4 on 12 Oct) falls
    assert all(len(t["path"]) == 3 for t in d["teams"])
    # the parts are our goals for and against about the league's mean, and they add up to the rating
    for t in d["teams"]:
        assert abs(t["parts"]["off"] + t["parts"]["def"] - t["rating"]) < 0.002
    assert top["chance"]["label"] == "Stanley Cup" and top["record"] == "2–1–1"
    assert top["form"] == "WLWL" and [s["label"] for s in top["stats"]] == ["Points", "Goal diff", "Playoffs"]
    assert d["notes"] and d["rating"]["fmt"] == "+2"
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "nhl" and idx["leagues"][0]["top"][0]["id"] == "AAA"


def test_a_full_week_after_the_monday_keeps_it(tmp_path):
    # latest game Sun 25 Oct: the 19 Oct point's games end 18 Oct, a full week before, so it stays a snapshot
    _tree(tmp_path, "2026-10-25")
    P.build(tmp_path)
    assert [s["label"] for s in _doc(tmp_path)["snapshots"]] == ["5 Oct", "12 Oct", "19 Oct", "Now"]


def test_players_by_position_and_offseason(tmp_path):
    _tree(tmp_path, "2026-10-25", phase="offseason")
    P.build(tmp_path)
    d = _doc(tmp_path)
    assert d["phase"] == "offseason" and d["snapshots"][-1]["label"] == "Final"
    assert all("chance" not in t for t in d["teams"])
    g = {x["key"]: x for x in d["players"]["groups"]}
    assert set(g) == {"c", "w", "d", "g"}
    assert g["w"]["n"] == 8 and g["w"]["top"][0]["sub"] in ("LW", "RW")      # left and right wings together
    assert g["d"]["n"] == 3                                                   # p11 (a D) is not qualified
    assert g["c"]["top"][0]["href"] == "#/player/p12" and g["c"]["metric"]["key"] == "gar_60"
    assert g["g"]["top"][0]["name"] == "Goalie 3" and g["g"]["metric"]["key"] == "gsax"
