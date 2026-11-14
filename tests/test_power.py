"""Power rankings: the shared shape (oddsmarkets/common/power.py) and the Gridiron's adapter on a small synthetic tree."""
import json
from pathlib import Path

import pytest

from oddsmarkets.common import power as PW


def _ents():
    # three snapshots; C climbs from 3rd to 1st, A falls, D is new at the last snapshot
    return [{"id": "A", "name": "Alpha", "rpath": [5.0, 4.0, 1.0], "form": "WLLLL", "parts": {"off": 1.0, "def": 0.0}},
            {"id": "B", "name": "Bravo", "rpath": [3.0, 3.5, 2.0], "streak": "W3", "parts": {"off": 0.5, "def": 1.5}},
            {"id": "C", "name": "Charlie", "rpath": [1.0, 2.0, 6.0], "parts": {"off": 3.0, "def": 3.0}},
            {"id": "D", "name": "Delta", "rpath": [None, None, 0.5]},
            {"id": "E", "name": "Echo", "rpath": [0.0, 0.0, None]}]


SNAPS = [{"key": "w1", "label": "Wk 1"}, {"key": "w2", "label": "Wk 2"}, {"key": "now", "label": "Now"}]


def test_teams_block_ranks_moves_and_paths():
    rows = PW.teams_block(_ents(), SNAPS, parts=[{"key": "off", "label": "Offence"}, {"key": "def", "label": "Defence"}])
    ids = [r["id"] for r in rows]
    assert ids == ["C", "B", "A", "D"]                           # E has no current rating: left out
    c, b, a, d = rows
    assert (c["rank"], c["prev"], c["move"], c["path"]) == (1, 3, 2, [3, 3, 1])
    assert (a["rank"], a["prev"], a["move"]) == (3, 1, -2)
    assert d["prev"] is None and d["move"] is None and d["path"] == [None, None, 4]
    assert c["delta"] == 4.0 and c["rating"] == 6.0
    assert c["note"].startswith("New No. 1, up from 3rd")
    assert "Down 2 places" in a["note"]
    assert "New to the rankings" in d["note"]


def test_ties_share_a_rank():
    rows = PW.teams_block([{"id": "x", "name": "X", "rpath": [1.0]}, {"id": "y", "name": "Y", "rpath": [1.0]},
                           {"id": "z", "name": "Z", "rpath": [0.0]}], [{"key": "now", "label": "Now"}])
    assert [r["rank"] for r in rows] == [1, 1, 3]


def test_group_top_bottom_and_dist():
    rows = [{"id": str(i), "name": f"P{i}", "team": "T", "v": {"m": float(i), "s": i * 2}} for i in range(1, 21)]
    g = PW.group("x", "Group", rows, {"key": "m", "label": "Metric", "fmt": "1"}, [{"key": "s", "label": "S", "fmt": "0"}],
                 n_top=5, n_bottom=3)
    assert [p["id"] for p in g["top"]] == ["20", "19", "18", "17", "16"]
    assert [p["id"] for p in g["bottom"]] == ["3", "2", "1"]          # the very bottom last
    assert g["top"][0]["pct"] == 100 and g["bottom"][-1]["pct"] == 0
    assert g["top"][0]["stats"] == [40]
    assert g["dist"][0] == 1.0 and g["dist"][-1] == 20.0 and g["n"] == 20
    low = PW.group("y", "Lower", rows, {"key": "m", "label": "Metric", "fmt": "1", "dir": "lower"}, n_top=2, n_bottom=1)
    assert [p["id"] for p in low["top"]] == ["1", "2"] and low["bottom"][-1]["id"] == "20"
    assert low["dist"][0] == 20.0 and low["dist"][-1] == 1.0       # worst to best
    assert PW.group("z", "Few", rows[:2], {"key": "m", "label": "M"}) is None


def test_group_samples_a_big_pool():
    rows = [{"id": str(i), "name": f"P{i}", "v": {"m": float(i)}} for i in range(1000)]
    g = PW.group("x", "Big", rows, {"key": "m", "label": "M", "fmt": "0"})
    assert g["sampled"] and len(g["dist"]) == PW.DIST_MAX and g["dist"][0] == 0 and g["dist"][-1] == 999


def test_write_index_and_prune(tmp_path):
    (tmp_path / "power").mkdir()
    (tmp_path / "power" / "old.json").write_text("{}")
    rows = PW.teams_block(_ents(), SNAPS)
    doc = PW.document(site="s", sport="nfl", league="lg", label="LG", season=2026, season_label="2026", updated_at="2026-11-13T00:00:00Z",
                      asof="2026-11-13", phase="season", rating={"label": "Our rating", "fmt": "+1"}, snapshots=SNAPS, teams=rows)
    res = PW.write(tmp_path, [doc], site="s", sport="nfl", updated_at=doc["updated_at"], default="lg")
    assert res["leagues"] == ["lg"] and not (tmp_path / "power" / "old.json").exists()
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "lg" and idx["leagues"][0]["file"] == "power/lg.json"
    assert idx["leagues"][0]["top"][0]["id"] == "C" and idx["leagues"][0]["snapshot"] == "Now"


def test_document_keeps_the_last_snapshots():
    snaps = [{"key": f"w{i}", "label": f"Wk {i}"} for i in range(15)]
    rows = PW.teams_block([{"id": "a", "name": "A", "rpath": [float(i) for i in range(15)]}], snaps)
    doc = PW.document(site="s", sport="x", league="l", label="L", season=1, season_label="", updated_at="", asof="", phase="season",
                      rating={}, snapshots=snaps, teams=rows)
    assert len(doc["snapshots"]) == PW.MAX_SNAPSHOTS and len(doc["teams"][0]["path"]) == PW.MAX_SNAPSHOTS
    assert doc["snapshots"][0]["key"] == "w5"


def _nfl_tree(root: Path, partial: bool):
    S = 2026
    (root / str(S)).mkdir(parents=True)
    teams = {}
    for i, a in enumerate(["AAA", "BBB", "CCC"]):
        hist = [[w, 3.0 - i + (w * (i - 1) * 0.5), 0.0, 0.0] for w in (1, 2, 3)]
        sched = [{"week": w, "gtype": "REG", "status": "final" if (w < 3 or not partial or i == 0) else "pre"} for w in (1, 2, 3)]
        teams[a] = {"name": f"Team {a}", "colour": "#123456", "values": {"rating": hist[-1][1] + (0.7 if i == 0 else 0), "off_rating": 1, "def_rating": 0},
                    "record": {"w": 2, "l": 1, "streak": "W1", "last5": ["W", "L", "W"]}, "history": hist, "schedule": sched, "sim": {"p_sb": 0.1}}
    (root / "index.json").write_text(json.dumps({"season": S, "week": 3, "phase": "regular", "teams": {a: {"division": "D"} for a in teams}}))
    (root / str(S) / "teams.json").write_text(json.dumps({"week": 3, "phase": "regular", "updated_at": "2026-11-13T00:00:00Z", "teams": teams}))
    (root / str(S) / "players.json").write_text(json.dumps({"metrics": [{"key": "composite", "label": "QB composite", "fmt": "1"}],
        "qualification": {"QB": "14 attempts"}, "players": {f"p{i}": {"name": f"Q{i}", "team": "AAA", "group": "QB", "qualified": True,
                                                                         "values": {"composite": 90 + i, "epa_db": 0.1 * i}} for i in range(5)}}))


@pytest.mark.parametrize("partial", [True, False])
def test_gridiron_adapter(tmp_path, partial):
    from oddsmarkets.nfl.analytics import power_build as G
    _nfl_tree(tmp_path, partial)
    res = G.build(tmp_path)
    assert res["leagues"] == ["nfl"]
    d = json.loads((tmp_path / "power" / "nfl.json").read_text(encoding="utf-8"))
    labels = [s["label"] for s in d["snapshots"]]
    # a week still being played folds into Now (it never stands alone); a finished week is the last snapshot, as Now
    assert labels == (["Wk 1", "Now"] if partial else ["Wk 1", "Wk 2", "Now"])
    assert d["teams"][0]["rank"] == 1 and all(len(t["path"]) == len(labels) for t in d["teams"])
    g = d["players"]["groups"][0]
    assert g["key"] == "qb" and g["top"][0]["name"] == "Q4" and g["n"] == 5
