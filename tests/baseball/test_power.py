"""The Bullpen's power rankings adapter (oddsmarkets/baseball/analytics/power_build.py) on a small synthetic tree: the
run-differential rating, snapshots every 7 days back from the last complete date, no look-ahead, the off-season's
"Final" and postseason notes, and the players by position on WAR."""
import json
from datetime import date, timedelta
from pathlib import Path

from oddsmarkets.baseball.analytics import power_build as B

S = 2026
D0 = date(2026, 8, 1)


def _log(results):
    """[(day offset, runs for, runs against)] -> game-log rows; None runs = a game not finished yet."""
    out = []
    for i, (k, rf, ra) in enumerate(results):
        res = "W" if rf is not None and rf > ra else "L" if rf is not None else "scheduled"
        out.append([str(1000 + i), (D0 + timedelta(days=k)).isoformat(), "R", "999", 1, rf, ra, res, 0.5, None])
    return out


def _tree(root: Path, phase="regular", pending=False):
    (root / "mlb" / str(S)).mkdir(parents=True)
    # 30 days of games; AAA wins big early then fades, BBB steady, CCC loses; DDD's 10-0 loss on day 21 is the check
    logs = {
        "101": [(k, 6, 2) if k < 15 else (k, 2, 4) for k in range(30)],
        "102": [(k, 4, 3) for k in range(30)],
        "103": [(k, 2, 5) for k in range(30)],
        "104": [(k, 4, 4 if k != 21 else 14) if k != 21 else (k, 0, 10) for k in range(30)],
    }
    if pending:                  # day 30 under way for one club: day 29 is the last complete date
        logs["102"].append((30, None, None))
        logs["101"].append((30, 3, 1))
    teams, rows = {}, []
    for i, (t, res) in enumerate(logs.items()):
        teams[t] = {"name": f"Club {t}", "abbr": f"C{t[-1]}", "short": f"C{t}", "colour": "#123456", "division": "AL East",
                    "values": {"rating": 0.5 - i * 0.3}, "log": _log(res)}
        rows.append({"tid": t, "name": f"Club {t}", "division": "AL East", "w": 20 - i, "l": 10 + i, "streak": "W3",
                     "p_ws": 0.1, "p_postseason": 0.5})
    (root / "index.json").write_text(json.dumps({"season": S, "levels": {"mlb": {"season": S, "phase": phase}},
                                                 "teams": {t: {"name": v["name"], "colour": "#123456"} for t, v in teams.items()}}))
    (root / "mlb" / str(S) / "teams.json").write_text(json.dumps({"updated_at": "2026-11-13T00:00:00Z", "teams": teams}))
    post = {"teams": {"101": {"reached": "WS", "champion": True}, "102": {"reached": "DS", "champion": False}}}
    (root / "mlb" / str(S) / "season.json").write_text(json.dumps({"phase": phase, "standings": {"AL East": rows}, "postseason": post}))
    hit = {"ok": True, "team_games": 162, "players": {
        f"h{i}": {"name": f"Hitter {i}", "team": "101", "team_abbr": "C1", "pos": "SS", "pa": 150 + 30 * i,
                  "values": {"war": float(i), "hr": i, "ops": 0.7, "sb": i, "oaa": 1.0}} for i in range(6)}}
    pit = {"ok": True, "team_games": 162, "players": {
        f"p{i}": {"name": f"Pitcher {i}", "team": "102", "team_abbr": "C2", "role": "SP", "bf": 400,
                  "values": {"war": 2.0 - i, "ip": 150.0, "ra9": 4.0, "fip": 4.1, "k_pct": 0.25, "stuff_plus": 101}} for i in range(4)}}
    (root / "mlb" / str(S) / "hitters.json").write_text(json.dumps(hit))
    (root / "mlb" / str(S) / "pitchers.json").write_text(json.dumps(pit))


def _doc(root):
    return json.loads((root / "power" / "mlb.json").read_text(encoding="utf-8"))


def test_in_season_snapshots_rating_and_no_look_ahead(tmp_path):
    _tree(tmp_path)
    res = B.build(tmp_path)
    assert res["leagues"] == ["mlb"]
    d = _doc(tmp_path)
    last = D0 + timedelta(days=29)
    # every 7 days back from the last complete date, while games had been played; the last snapshot is now
    want = [last - timedelta(days=7 * k) for k in (4, 3, 2, 1)]
    assert [s["date"] for s in d["snapshots"][:-1]] == [x.isoformat() for x in want]
    assert d["snapshots"][-1]["label"] == "Now" and d["phase"] == "season"
    t = {x["id"]: x for x in d["teams"]}
    # the rating: run differential a game regressed with RATING_G0 games of prior; the parts add up to it
    assert abs(t["102"]["rating"] - round(30 / (30 + B.RATING_G0), 3)) < 1e-3
    assert abs(t["102"]["parts"]["off"] + t["102"]["parts"]["def"] - t["102"]["rating"]) < 2e-3
    # no look-ahead: DDD's 0-10 on day 21 is not in the snapshot dated day 15 (7 days before day 22's snapshot)
    k = [s["date"] for s in d["snapshots"]].index((D0 + timedelta(days=22)).isoformat())
    assert t["104"]["rpath"][k - 1] == 0.0 and t["104"]["rpath"][k] < 0
    assert t["101"]["chance"]["label"] == "World Series"


def test_a_date_with_a_game_under_way_is_not_complete(tmp_path):
    _tree(tmp_path, pending=True)
    B.build(tmp_path)
    d = _doc(tmp_path)
    # day 30 has a game still to finish, so the snapshots count back from day 29; now still adds AAA's day-30 win
    assert d["snapshots"][-2]["date"] == (D0 + timedelta(days=22)).isoformat()
    a = {x["id"]: x for x in d["teams"]}["101"]
    gs = B.reg_games(json.loads((tmp_path / "mlb" / str(S) / "teams.json").read_text())["teams"]["101"]["log"])
    assert len(gs) == 31 and abs(a["rating"] - round(sum(g[1] - g[2] for g in gs) / (31 + B.RATING_G0), 3)) < 1e-3


def test_offseason_reads_final_with_postseason_notes(tmp_path):
    _tree(tmp_path, phase="offseason")
    B.build(tmp_path)
    d = _doc(tmp_path)
    assert d["phase"] == "offseason" and d["snapshots"][-1]["label"] == "Final"
    t = {x["id"]: x for x in d["teams"]}
    assert t["101"]["note"].startswith("World Series champions")
    assert t["102"]["note"].startswith("Lost in the Division Series")
    assert t["103"]["note"].startswith("Missed the postseason")
    assert all("this week" not in x["note"] for x in d["teams"]) and "chance" not in t["101"]


def test_players_on_war_with_the_qualifying_rule(tmp_path):
    _tree(tmp_path)
    B.build(tmp_path)
    g = {x["key"]: x for x in _doc(tmp_path)["players"]["groups"]}
    # 200 PA over a full season: h0 (150 PA) and h1 (180 PA) are out
    assert g["ss"]["n"] == 4 and g["ss"]["top"][0]["name"] == "Hitter 5" and g["ss"]["metric"]["key"] == "war"
    assert g["ss"]["top"][0]["href"] == "#/mlb/hitter/h5" and g["sp"]["top"][0]["href"] == "#/mlb/pitcher/p0"
    assert [s["label"] for s in g["sp"]["stats"]] == ["IP", "RA9", "FIP", "K%", "Stuff+"]


def test_with_post_keeps_the_result_first():
    assert B.with_post("Won 5 straight; best run scoring in the league.", "World Series champions") == "World Series champions; won 5 straight."
    assert B.with_post("No. 1 for 3 weeks running.", "Lost in the LCS") == "Lost in the LCS; No. 1 for 3 weeks running."
    assert B.with_post("", "Missed the postseason") == "Missed the postseason."
