"""oddsmarkets/nhl/analytics/performers.py: the Rink league page's top and bottom performers."""
from oddsmarkets.nhl.analytics import performers as PF


def _sk(n, group, q=True, base=0.0, pre=""):
    return {f"{pre}{group}{i}": {"name": f"{pre}{group} {i}", "team": "TOR" if i % 2 else "MTL", "group": group, "qualified": q,
                            "values": {"gar": base + i / 10, "gar_60": base + i / 100, "p": i, "g": i // 2, "p60": i / 5,
                                       "ixg60_all": i / 7, "adj_xgf_pct": 0.4 + i / 100, "adj_xga60": 3 - i / 10,
                                       "rapm_def": i / 9, "toi_gp": 15 + i}} for i in range(n)}


def test_views_qualified_only_and_spec_sets():
    players = {**_sk(12, "F"), **_sk(8, "D"), **_sk(3, "F", q=False, base=99, pre="u")}
    goalies = {"players": {f"G{i}": {"name": f"G {i}", "team": "TOR", "qualified": i < 6, "values": {"gsax": i - 2.5, "sv_pct": 0.9 + i / 1000}} for i in range(9)}}
    doc = PF.build({"players": players, "team_games": 9, "updated_at": "2026-10-28T00:00:00Z"}, goalies, "20262027")
    v = {x["key"]: x for x in doc["views"]}
    assert list(v) == ["all", "forwards", "defence", "goalies"]
    assert v["all"]["n"] == 20 and v["forwards"]["n"] == 12 and v["defence"]["n"] == 8 and v["goalies"]["n"] == 6
    # unqualified players never reach a board, even with the best numbers
    assert not any(r[3] > 50 for m in v["all"]["metrics"] for r in m["top"])
    # our value model first; ice time (usage) gets no board; lower-is-better ranks the smallest first
    assert v["all"]["metrics"][0]["key"] == "gar_60" and v["all"]["metrics"][0]["ours"]
    assert "toi_gp" not in [m["key"] for x in doc["views"] for m in x["metrics"]]
    xga = next(m for m in v["defence"]["metrics"] if m["key"] == "adj_xga60")
    assert xga["dir"] == "lower" and xga["top"][0][3] == min(3 - i / 10 for i in range(8))
    g = next(m for m in v["goalies"]["metrics"] if m["key"] == "gsax")
    assert g["top"][0][1] == "G 5" and g["bot"][-1][1] == "G 0" and g["top"][0][4] == 100
    assert doc["season"] == 20262027 and doc["team_games"] == 9


def test_empty_catalogues():
    assert PF.build(None, None, 20262027) is None
    assert PF.build({"players": _sk(5, "F", q=False)}, {"players": {}}, 20262027) is None
