"""oddsmarkets/college/performers.py: the Campus standings pages' top and bottom performers."""
import json

from oddsmarkets.college import performers as PF


def _season(n):
    return {"ok": True, "teams": {str(i): {"name": f"Team {i}", "member": i < n - 1} for i in range(n)},
            "ratings": {str(i): {"rating": float(i), "off": i / 2, "def": -i / 3, "epa_off": i / 100, "epa_def": -i / 100,
                                 "sr_off": 0.4 + i / 100, "sr_def": 0.45 - i / 100, "tempo": 70} for i in range(n)}}


def test_cfb_views_spec_sets_and_qualified_rate():
    players = {}
    for i in range(8):
        players[f"q{i}"] = {"name": f"QB {i}", "team": str(i % 3), "pos": "QB", "qualified": True, "qualified_rate": i < 6,
                            "values": {"value": 10.0 * i, "value_pg": i / 2, "epa_play": i / 50, "int_rate": 0.05 - i / 200, "cmp_pct": 0.6}}
    doc = PF.build("cfb", {"ok": True, "players": players}, _season(8), 2026)
    v = {x["key"]: x for x in doc["views"]}
    assert v["qb"]["n"] == 6                                   # the spec's rate floor, not the games floor
    keys = [m["key"] for m in v["qb"]["metrics"]]
    assert keys[:2] == ["value_pg", "epa_play"] and v["qb"]["metrics"][0]["ours"]
    ir = next(m for m in v["qb"]["metrics"] if m["key"] == "int_rate")
    assert ir["dir"] == "lower" and ir["top"][0][1] == "QB 5"
    t = v["teams"]
    assert t["entity"] == "team" and t["n"] == 7                # FBS members only
    assert t["metrics"][0]["key"] == "rating" and t["metrics"][0]["top"][0][0] == "6"
    assert all(".json" not in (m.get("tip") or "") for x in doc["views"] for m in x["metrics"])


def test_hoops_positions_and_write(tmp_path):
    players = {f"p{i}": {"name": f"P {i}", "team": str(i % 4), "pos": "GFC"[i % 3], "qualified": i != 0,
                         "values": {"r": i - 5.0, "value_pg": i / 10, "value": i, "pts": 5 + i, "reb": i % 7, "ast": i % 5, "stl": 1, "blk": i % 2,
                                    "tov": 3 - i / 10, "ts": 0.5 + i / 100}} for i in range(15)}
    folder = tmp_path / "mbb" / "2026"
    folder.mkdir(parents=True)
    (folder / "players.json").write_text(json.dumps({"ok": True, "players": players}), encoding="utf-8")
    (folder / "season.json").write_text(json.dumps(_season(10)), encoding="utf-8")
    r = PF.write("mbb", tmp_path, 2026)
    assert r["ok"] and r["views"] == 5
    doc = json.loads((folder / "performers.json").read_text(encoding="utf-8"))
    v = {x["key"]: x for x in doc["views"]}
    assert list(v) == ["all", "guards", "forwards", "centers", "teams"]
    assert v["all"]["n"] == 14 and v["all"]["metrics"][0]["key"] == "r"
    assert [m["key"] for m in v["teams"]["metrics"]] == ["rating", "off", "def"]   # tempo is style
    tov = next(m for m in v["guards"]["metrics"] if m["key"] == "tov")
    assert tov["dir"] == "lower"
    assert PF.write("wbb", tmp_path, 2026)["ok"] is False
