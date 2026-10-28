"""oddsmarkets/tennis/analytics/performers.py: the Ace tour page's top and bottom performers."""
from oddsmarkets.tennis.analytics import performers as PF


def _cat(n=14):
    players = {}
    for i in range(n):
        players[str(i)] = {"name": f"P {i}", "country": "ESP" if i % 2 else "ITA", "qualified": i < 12,
                           "values": {"elo": 1500 + 10 * i, "elo_clay": 1400 + 10 * i, "elo_hard": 1450 + i, "elo_grass": 1300 + i,
                                      "hold": 0.7 + i / 100, "brk": 0.2 + i / 100, "games_won_pct": 0.45 + i / 200, "win_v_top50": i / 20},
                           "values_surface": {"clay": {"matches": i, "hold": 0.6 + i / 100, "brk": 0.3, "win_pct": i / 20, "games_won_pct": 0.5},
                                              "grass": {"matches": 1}}}
    return {"ok": True, "year": 2026, "floor": 18, "surface_floor": {"hard": 10, "clay": 8, "grass": 5}, "players": players}


def test_views_floors_and_order():
    doc = PF.build(_cat(), "atp")
    v = {x["key"]: x for x in doc["views"]}
    assert list(v) == ["all", "clay"]                     # nobody over the hard or grass floors
    assert v["all"]["n"] == 12                            # the catalogue's qualified flag
    assert v["clay"]["n"] == 6                            # 8+ clay matches: players 8..13, qualified overall or not
    m0 = v["all"]["metrics"][0]
    assert m0["key"] == "elo" and m0["label"] == "Overall Elo" and m0["ours"] and not m0.get("unit")
    assert m0["top"][0][:3] == ["11", "P 11", "ESP"] and m0["bot"][-1][1] == "P 0"
    assert v["clay"]["metrics"][0]["key"] == "elo_clay"
    # the surface's own hold, not the season's
    hold = next(m for m in v["clay"]["metrics"] if m["key"] == "hold")
    assert hold["top"][0][3] == round(0.6 + 13 / 100, 4)
    assert doc["tour"] == "atp" and doc["year"] == 2026


def test_nothing_to_show():
    assert PF.build(None, "atp") is None
    assert PF.build({"ok": False}, "wta") is None
    c = _cat()
    for p in c["players"].values():
        p["qualified"] = False
        p["values_surface"] = {}
    assert PF.build(c, "wta") is None
