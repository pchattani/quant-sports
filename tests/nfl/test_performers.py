"""oddsmarkets/nfl/analytics/performers.py: the Gridiron standings page's top and bottom performers."""
from oddsmarkets.nfl.analytics import performers as PF


def _value(rows):
    cols = ["pid", "name", "team", "pos", "gvar", "gvar_pg", "q"]
    return {"ok": True, "cols": cols, "rows": [[r.get(c) for c in cols] for r in rows]}


def test_views_positions_and_qualified():
    players, vrows = {}, []
    for i in range(8):
        pid = f"qb{i}"
        players[pid] = {"name": f"QB {i}", "team": "KC", "group": "QB", "games": 6, "qualified": i < 6,
                        "values": {"composite": 90 + i, "epa_db": i / 20 - 0.1, "cpoe": i - 3.0, "sack_rate": 0.1 - i / 100, "adot": 7 + i}}
        vrows.append({"pid": pid, "name": f"QB {i}", "team": "KC", "pos": "QB", "gvar": 10.0 * i, "gvar_pg": 1.5 * i, "q": 1})
    for i in range(7):
        pid = f"de{i}"
        players[pid] = {"name": f"DE {i}", "team": "BUF", "group": "DEF", "pos": "DE", "games": 4, "qualified": True,
                        "values": {"pressures_pg": i / 2, "tackles": 4 * i, "tfl": i, "pd": 0, "ints": 0, "ff": i % 2}}
        vrows.append({"pid": pid, "name": f"DE {i}", "team": "BUF", "pos": "EDGE", "gvar": i, "gvar_pg": i / 4, "q": 1})
    doc = PF.build({"ok": True, "players": players, "team_games": 6}, _value(vrows), 2026)
    v = {x["key"]: x for x in doc["views"]}
    assert list(v)[:1] == ["all"] and v["all"]["metrics"][0]["key"] == "gvar_pg" and v["all"]["n"] == 15
    qb = v["qb"]
    assert qb["n"] == 6                                         # the two unqualified quarterbacks are left out
    keys = [m["key"] for m in qb["metrics"]]
    assert keys[0] == "composite" and "epa_db" in keys and "cpoe" in keys and "adot" not in keys   # ours first, style out
    sack = next(m for m in qb["metrics"] if m["key"] == "sack_rate")
    assert sack["dir"] == "lower" and sack["top"][0][1] == "QB 5"
    edge = v["edge"]
    assert edge["peer"] == "outside pass rushers" and edge["label"] == "Pass rushers" and edge["min"].startswith("half the team")
    tk = next(m for m in edge["metrics"] if m["key"] == "tackles_pg")
    assert tk["top"][0][3] == 6.0 and tk["top"][0][1] == "DE 6"     # 24 tackles over 4 games
    assert "dl" not in v                                          # nobody there: no view


def test_nothing_qualified():
    assert PF.build({"ok": True, "players": {}}, {"ok": False}, 2026) is None
