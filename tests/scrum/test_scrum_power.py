"""oddsmarkets/rugby/power_build.py: The Quant Scrum's power rankings from a synthetic payload tree.
(Named test_scrum_power.py, not test_power.py: tests/scrum is not a package, so the name would clash with
tests/test_power.py.)"""
from __future__ import annotations

import json
from pathlib import Path

from oddsmarkets.rugby import power_build as P


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def tree(tmp: Path) -> Path:
    data = tmp / "data"
    teams = {"1": {"name": "Alpha", "abbr": "ALP", "colour": "#112233", "tier": 1},
             "2": {"name": "Bravo", "abbr": "BRA", "colour": "#445566", "tier": 1},
             "3": {"name": "Charlie", "abbr": "CHA", "colour": "#778899", "tier": 2},
             "4": {"name": "Delta", "abbr": "DEL", "tier": 3}}
    write(data / "index.json", {"updated_at": "2026-11-14T02:00:00Z", "scopes": {"men": {"ok": True, "teams": teams}, "women": {"ok": False}}})
    # month-end ratings (the rating after the side's last test that month); Alpha overtakes Bravo in November (Now);
    # nobody plays in September; Delta is provisional (no rank)
    r = [{"id": "1", "rank": 1, "rating": 12.0, "tier": 1, "form": "WWLWW", "rec12": [8, 0, 2], "wr": 90.1, "wr_rank": 2, "d365": 1.5,
          "hist": [["2026-07", 5.0], ["2026-08", 6.0], ["2026-10", 8.0], ["2026-11", 12.0]]},
         {"id": "2", "rank": 2, "rating": 10.0, "tier": 1, "form": "WLLWL", "rec12": [6, 1, 3], "wr": 91.0, "wr_rank": 1,
          "hist": [["2026-07", 9.0], ["2026-08", 9.5], ["2026-10", 10.0]]},
         {"id": "3", "rank": 3, "rating": -4.0, "tier": 2, "hist": [["2025-11", -3.0], ["2026-08", -4.0]]},
         {"id": "4", "rank": None, "prov": 1, "rating": -50.0, "hist": [["2026-11", -50.0]]}]
    write(data / "men" / "ratings.json", {"asof": "2026-11-14", "teams": r})
    write(data / "men" / "comps" / "nc.json", {"fixtures": [{"date": "2026-11-21"}], "sim": {"teams": [{"team": "Alpha", "champion": 0.6}, {"team": "Bravo", "champion": 0.4}]}})
    cols = ["id", "n", "team", "pos", "grp", "gp", "min", "q", "last", "val80", "tk", "car", "tkpct", "pc"]
    rows = [[f"p{i}", f"Prop {i}", "1", "P", "front_row", 5, 300, 1, "2026-11-07", 0.5 * i, 10, 8, 0.9, 0.5] for i in range(4)]
    rows.append(["old", "Retired Prop", "2", "P", "front_row", 9, 700, 1, "2024-12-01", 3.0, 10, 8, 0.9, 0.5])    # no test for 13 months
    rows.append(["few", "Cameo Prop", "2", "H", "front_row", 1, 60, 0, "2026-11-07", 4.0, 10, 8, 0.9, 0.5])       # not qualified
    write(data / "men" / "players.json", {"from": "2024-11-14", "min_q": 160, "cols": cols, "rows": rows})
    return data


def test_monthly_snapshots_no_look_ahead_and_rows(tmp_path):
    data = tree(tmp_path)
    res = P.build(data)
    assert res["leagues"] == ["men"]                                   # women not built: no file
    doc = json.loads((data / "power" / "men.json").read_text(encoding="utf-8"))
    keys = [s["key"] for s in doc["snapshots"]]
    # ten calendar months back from the latest month with a test (November), which is Now
    assert keys[0] == "2026-02" and keys[-2] == "2026-10" and keys[-1] == "now" and len(keys) == 10
    assert doc["step"] == "month" and doc["snapshots"][-2]["date"] == "2026-10-31"
    t = {x["id"]: x for x in doc["teams"]}
    assert "4" not in t                                                # provisional sides are not ranked
    a, b = t["1"], t["2"]
    # September has no test: its value is August's; October's is the side's own October entry, never November's
    i_sep, i_oct = keys.index("2026-09"), keys.index("2026-10")
    assert a["rpath"][i_sep] == 6.0 and a["rpath"][i_oct] == 8.0 and a["rpath"][-1] == 12.0
    assert a["rank"] == 1 and a["prev"] == 2 and a["move"] == 1 and b["move"] == -1
    assert t["3"]["rpath"][0] == -3.0                                  # carried from its last test (Nov 2025)
    assert a["chance"] == {"label": "Nations Championship", "p": 0.6}
    assert a["href"] == "#/men/team/1" and a["group"] == "Tier 1" and a["record"] == "W8 D0 L2"
    assert a["stats"][0] == {"label": "World Rugby", "text": "2nd, 90.10 pts"}


def test_players_qualified_and_recent(tmp_path):
    data = tree(tmp_path)
    P.build(data)
    doc = json.loads((data / "power" / "men.json").read_text(encoding="utf-8"))
    g = doc["players"]["groups"][0]
    assert g["key"] == "front_row" and g["n"] == 4
    ids = {p["id"] for p in g["top"] + g["bottom"]}
    assert "old" not in ids and "few" not in ids
    assert g["top"][0]["id"] == "p3" and g["top"][0]["href"] == "#/men/player/p3" and g["top"][0]["team"] == "ALP"
    assert g["top"][0]["sub"] == "Prop"
