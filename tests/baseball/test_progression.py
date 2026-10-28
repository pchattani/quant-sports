"""Round 6 progression on the Bullpen career files: the deep set per kind (prog.keys), each MLB season row's pr {dv, dp,
pg} aligned to it, AAA rows untouched, and mlb/progression_ref.json."""
from __future__ import annotations

from oddsmarkets.baseball.analytics import careers as CR


def _cat(kind, n, season, tg=162):
    P = {}
    for i in range(n):
        pid = f"{kind[0]}{i}"
        if kind == "hitter":
            vals = {"pa": 300 + i * 20, "g": 120, "xwoba_n": 0.28 + i * 0.005, "woba": 0.3 + i * 0.004, "k_pct": 0.3 - i * 0.005, "war": i * 0.3}
            P[pid] = {"name": f"H {i}", "team": "147", "pos": "RF" if i % 2 else "CF", "pa": vals["pa"], "values": vals,
                      "pct_role": {"xwoba_n": 5 * i} if i == 3 else {}}
        else:
            vals = {"bf": 500 + i * 10, "g": 30, "xwoba_n": 0.33 - i * 0.004, "k_pct": 0.2 + i * 0.005, "stuff_plus": 95 + i, "war": i * 0.2}
            P[pid] = {"name": f"P {i}", "team": "147", "role": "SP", "bf": vals["bf"], "values": vals}
    return {"players": P, "team_games": tg}


def test_careers_carry_the_progression(monkeypatch):
    monkeypatch.setattr(CR.an, "load_people", lambda: {})
    monkeypatch.setattr(CR.an, "load_store", lambda lvl, s: {})
    monkeypatch.setattr(CR, "movement_rows", lambda level="mlb": {})
    cats = {("mlb", 2024): {"hitters": _cat("hitter", 20, 2024), "pitchers": _cat("pitcher", 20, 2024)},
            ("mlb", 2020): {"hitters": _cat("hitter", 20, 2020, 60), "pitchers": _cat("pitcher", 20, 2020, 60)},
            ("aaa", 2024): {"hitters": _cat("hitter", 3, 2024), "pitchers": None}}
    written = {}
    CR.write_careers(lambda rel, d: written.__setitem__(rel, d), cats, {}, None, set(), lambda p: None)
    h = written["players/h3.json"]
    keys = h["prog"]["keys"]["hitter"]
    assert keys[0] == "xwoba_n" and "war" in keys
    mlb = [r for r in h["seasons"] if r["level"] == "mlb"]
    aaa = [r for r in h["seasons"] if r["level"] == "aaa"]
    assert all(len(r["pr"]["dv"]) == len(keys) for r in mlb) and all("pr" not in r for r in aaa)
    assert {r["pr"]["pg"] for r in mlb} == {"hitters_LFRF"}
    r24 = next(r for r in mlb if r["season"] == 2024)
    assert r24["pr"]["dp"][keys.index("xwoba_n")] == 15         # the site's own position percentile wins
    p = written["players/p19.json"]
    pk = p["prog"]["keys"]["pitcher"]
    pr = next(r for r in p["seasons"] if r["season"] == 2024)["pr"]
    assert pr["dp"][pk.index("k_pct")] > 90                       # a pitcher's K% points up
    assert pr["dp"][pk.index("xwoba_n")] > 90                      # and xwOBA against points down
    ref = written["mlb/progression_ref.json"]
    assert ref["seasons"]["2020"]["len"] == 60 and "sp" in ref["seasons"]["2024"]
