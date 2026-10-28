"""oddsmarkets/basketball/analytics/performers.py: the Hardwood standings page's top and bottom performers."""
from oddsmarkets.basketball.analytics import performers as PF


def _cat(roles=True):
    P = {}
    for i in range(30):
        role = "GWB"[i % 3]
        P[str(i)] = {"name": f"P{i}", "team": str(1 + i % 5), "qualified": i < 24, "role": role if roles else None,
                     "values": {"hpm": i / 3 - 4, "hpm_o": i / 4, "hpm_d": -i / 5, "pts_g": 30 - i, "reb_g": i / 2, "ast_g": 3,
                                "ts": 0.5 + i / 100, "pts100": i, "ts_add": i / 10, "pox100": 1, "ast_pct": 0.2, "ast_tov": 2,
                                "fta100": 5, "stl_pct": 0.02, "drb_pct": 0.2, "orb_pct": 0.1, "blk_pct": 0.03}}
        if not roles:
            del P[str(i)]["role"]
    return {"ok": True, "players": P, "min_floor": 120, "updated_at": "2026-10-28T00:00:00Z"}


def test_views_roles_and_qualified():
    doc = PF.build(_cat(), "nba", "2027")
    v = {x["key"]: x for x in doc["views"]}
    assert list(v) == ["all", "guards", "wings", "bigs"]
    assert v["all"]["n"] == 24 and v["guards"]["n"] == v["wings"]["n"] == v["bigs"]["n"] == 8
    hpm = v["all"]["metrics"][0]
    assert hpm["key"] == "hpm" and hpm["ours"] and hpm["top"][0][1] == "P23"     # unqualified P24-29 never rank
    assert [m["key"] for m in v["bigs"]["metrics"]][:3] == ["hpm", "hpm_o", "hpm_d"]
    assert "blk_pct" in [m["key"] for m in v["bigs"]["metrics"]] and "blk_pct" not in [m["key"] for m in v["guards"]["metrics"]]
    pts = next(m for m in v["all"]["metrics"] if m["key"] == "pts_g")
    assert pts["top"][0][3] == 30 and pts["bot"][-1][3] == 7
    assert doc["league"] == "nba" and doc["season"] == 2027 and "120 minutes" in v["all"]["min"]


def test_catalogue_without_roles_and_empty():
    doc = PF.build(_cat(roles=False), "wnba", 2025)
    assert [x["key"] for x in doc["views"]] == ["all"]
    assert PF.build({"ok": False}, "nba", 2027) is None
    assert PF.build({"ok": True, "players": {}}, "nba", 2027) is None
