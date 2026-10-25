"""Team-page top performers (oddsmarkets/college/top_performers.py)."""
import json

from oddsmarkets.college import top_performers as T


def _cat(level="cfb"):
    key = "value_pg" if level == "cfb" else "r"
    P = {}
    for i in range(10):
        P[f"q{i}"] = {"name": f"QB{i}", "team": "A" if i < 2 else "B", "pos": "QB", "gp": 6, "qualified": True,
                      "values": {key: 10 - i, "value": 50 - i, "value_pg": 10 - i}, "pct_pos": {key: 100 - 10 * i}}
    P["w0"] = {"name": "WR0", "team": "A", "pos": "WR", "gp": 6, "qualified": True, "values": {key: 2, "value": 5, "value_pg": 2}}
    P["x"] = {"name": "Short", "team": "A", "pos": "QB", "gp": 1, "qualified": False, "values": {key: 99, "value": 99, "value_pg": 99}}
    mets = [{"key": "value"}, {"key": "value_pg"}] + ([{"key": "r"}] if level != "cfb" else [])
    return {"ok": True, "metrics": mets, "players": P}


def test_ranks_within_position_and_only_qualified():
    out = T.compute("cfb", _cat())
    a = out["A"]
    assert [r["id"] for r in a["overall"]][:2] == ["q0", "q1"]           # the unqualified 99 is left out
    qb = [r for r in a["by_pos"] if r["pos"] == "QB"][0]
    assert qb["rank"] == 1 and qb["n"] == 10 and qb["pct"] == 100
    wr = [r for r in a["by_pos"] if r["pos"] == "WR"][0]
    assert wr["rank"] == 1 and wr["n"] == 1
    assert a["ours"] and a["pool"] == "FBS"
    assert out["B"]["by_pos"][0]["rank"] == 3                            # q2 is third of ten


def test_hoops_uses_the_box_rating():
    out = T.compute("mbb", _cat("mbb"))
    assert out["A"]["by_pos"][0]["key"] == "r" and out["A"]["pool"] == "Division I"


def test_write_top_adds_the_field(tmp_path):
    base = tmp_path / "cfb" / "2026"
    (base / "teams").mkdir(parents=True)
    (base / "players.json").write_text(json.dumps(_cat()), encoding="utf-8")
    (base / "teams" / "A.json").write_text(json.dumps({"ok": True, "id": "A"}), encoding="utf-8")
    assert T.write_top("cfb", tmp_path, 2026)["team_pages"] == 1
    d = json.loads((base / "teams" / "A.json").read_text(encoding="utf-8"))
    assert d["id"] == "A" and d["top_performers"]["overall"]
