"""oddsmarkets/football/analytics/power_build.py: The Quant Footballer's power rankings from a synthetic payload tree."""
from __future__ import annotations

import gzip
import json
from datetime import date, timedelta
from pathlib import Path

from oddsmarkets.football.analytics import power_build as P

L = date(2026, 11, 8)                  # the latest league game
CLUBS = {"1": "Alpha FC", "2": "Manchester City", "3": "Gamma Town", "4": "Delta City"}


def write(p: Path, obj, gz: bool = False) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False)
    if gz:
        with gzip.open(str(p) + ".gz", "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        p.write_text(text, encoding="utf-8")


def d(k: int) -> str:
    return (L - timedelta(days=k)).isoformat()


def tree(tmp: Path) -> Path:
    data = tmp / "data"
    comps = [{"slug": "lg", "name": "Test League", "short_name": "TL", "kind": "league", "ok": True, "favourite_label": "Title",
              "games_played": 40, "games_total": 120, "current_season": {"sid": 1, "season": "26/27", "era": "2026/27", "status": "current"}},
             {"slug": "cup", "name": "Test Cup", "kind": "cup", "family": "domestic", "ok": True, "current_season": {"sid": 2, "status": "current"}}]
    write(data / "competitions.json", {"competitions": comps})
    write(data / "clubs_index.json", {"fields": ["id", "name", "colour"], "rows": [[int(t), n, "#112233"] for t, n in CLUBS.items()]})
    write(data / "lg" / "teams.json", {"teams": {n: {"team_id": int(t)} for t, n in CLUBS.items()}})
    # weekly games 35, 28, 21 days back, none 14 days back (a break), then 7 back and the latest (0); Gamma's game 3 days
    # back sits between the last two snapshots: it counts at Now only
    hist = {
        "Alpha FC": [(35, 1550), (28, 1560), (21, 1570), (7, 1580), (0, 1590)],
        "Manchester City": [(35, 1540), (28, 1530), (21, 1520), (7, 1510), (0, 1500)],
        "Gamma Town": [(35, 1500), (28, 1505), (21, 1510), (7, 1515), (3, 1600)],
        "Delta City": [(35, 1490), (28, 1485), (21, 1480), (7, 1475), (0, 1470)],
    }
    write(data / "lg" / "strength.json", {"updated_at": "2026-11-13T00:00:00Z",
        "rows": [{"team": n, "strength_ppg": 1.5, "played": 10, "xg_diff": 2.0, "form_results": ["W", "W", "W", "W", "W"]} for n in CLUBS.values()],
        "elo_history": {n: [{"date": d(k), "elo": v} for k, v in h] for n, h in hist.items()}})
    stand = [{"pos": i + 1, "team": n, "played": 10, "w": 7 - i, "d": 1, "l": 2 + i, "pts": 22 - 3 * i} for i, n in enumerate(CLUBS.values())]
    write(data / "lg" / "table.json", {"standings": stand, "matches_per_team": 30, "games_played": 40, "total_games": 120})
    write(data / "lg" / "probs.json", {"teams": [{"team": n, "p_title": 0.4 if n == "Alpha FC" else 0.2} for n in CLUBS.values()]})
    fields = ["player_id", "name", "team", "tid", "role", "minutes", "gar90", "goals_90", "assists_90", "xg_90", "save_pct",
              "goals_prevented_90", "saves_90", "conceded_90"]
    rows = [[f"k{i}", f"Keeper {i}", "Alpha FC", 1, "GK", 950 + i, 0.1 * i, 0, 0, 0, 70 + i, 0.0, 3.0, 1.0] for i in range(4)]
    rows.append(["k9", "Keeper short", "Delta City", 4, "GK", 600, 0.9, 0, 0, 0, 80, 0.0, 3.0, 1.0])      # under 900 minutes
    rows += [[f"s{i}", f"Striker {i}", "Manchester City", 2, "ST", 900, 0.2 * i, 0.5, 0.1, 0.4, None, None, None, None] for i in range(4)]
    write(data / "lab" / "season" / "lg.json", {"floor": 270, "fields": fields, "rows": rows}, gz=True)       # only the .gz, as deployed
    return data


def test_league_files_snapshots_and_rows(tmp_path):
    data = tree(tmp_path)
    res = P.build(data, now="2026-11-13T00:00:00Z")
    assert res["leagues"] == ["lg"]                                  # the cup has no file
    idx = json.loads((data / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "lg"                                    # the Premier League is absent: the first league
    doc = json.loads((data / "power" / "lg.json").read_text(encoding="utf-8"))
    # seven days apart back from the latest game; the empty week 14 days back is skipped
    assert [s["date"] for s in doc["snapshots"]] == [d(35), d(28), d(21), d(7), d(0)]
    assert doc["snapshots"][-1]["label"] == "Now" and doc["step"] == "week"
    t = {r["name"]: r for r in doc["teams"]}
    # ratings against the league average (the mean now is 1540)
    assert t["Alpha FC"]["rating"] == 50.0 and t["Gamma Town"]["rating"] == 60.0
    # no look-ahead: Gamma's game three days back is in Now only, not in the snapshot seven days back
    g = t["Gamma Town"]
    assert g["rpath"][-2] == 1515 - 1540 and g["rpath"][-1] == 60.0
    assert g["rank"] == 1 and g["prev"] == 2 and g["move"] == 1
    assert t["Manchester City"]["abbr"] == "MCI" and t["Manchester City"]["short"] == "Man City"
    assert t["Alpha FC"]["href"] == "#/club/1?c=lg" and t["Alpha FC"]["colour"] == "#112233"
    assert t["Alpha FC"]["chance"] == {"label": "Title", "p": 0.4} and t["Alpha FC"]["record"] == "W7 D1 L2"
    assert t["Alpha FC"]["stats"][0] == {"label": "Table", "text": "1st, 22 pts"}


def test_players_qualify_and_totals(tmp_path):
    data = tree(tmp_path)
    P.build(data)
    doc = json.loads((data / "power" / "lg.json").read_text(encoding="utf-8"))
    groups = {g["key"]: g for g in doc["players"]["groups"]}
    gk = groups["gk"]
    assert gk["n"] == 4 and "k9" not in {p["id"] for p in gk["top"] + gk["bottom"]}         # 900 minutes for keepers
    assert "Prevented/90" not in [s["label"] for s in gk["stats"]]                            # all zeros: not covered
    st = groups["st"]
    assert st["top"][0]["id"] == "s3" and st["top"][0]["href"] == "#/player/s3?c=lg"
    labels = [s["label"] for s in st["stats"]]
    assert st["top"][0]["stats"][labels.index("Goals")] == 5                                  # 0.5 a 90 over 900 minutes


def test_club_code_matches_the_front_end():
    assert P.club_code("Arsenal") == "ARS"
    assert P.club_code("Gamma Town") == "GTO"
    assert P.club_code("West Bromwich Albion") == "WBA"
    assert P.club_code("FC Twente") == "TWE"
