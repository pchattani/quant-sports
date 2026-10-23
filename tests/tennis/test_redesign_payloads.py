"""Redesign payload additions (22 Oct 2026): race.json history, the career files' peer block and similar players."""
from oddsmarkets.tennis.analytics import players as PL
from oddsmarkets.tennis.analytics import race as RC


def _sim(as_of, n=1000, fq=None):
    return {"ok": True, "as_of": as_of, "n_sims": n, "finals_qual": fq or {"a": 0.9, "b": 0.4, "c": 0.0001},
            "year_end_no1": {"a": 0.7, "b": 0.3}}


def test_race_history_rolls_forward():
    h = RC.history(None, _sim("2026-10-20"))
    assert len(h) == 1 and h[0]["finals_qual"] == {"a": 0.9, "b": 0.4}          # below HISTORY_MIN_P dropped
    h = RC.history({"history": h}, _sim("2026-10-21"))
    h = RC.history({"history": h}, _sim("2026-10-21", n=5000))               # same date: replaced
    assert [x["as_of"] for x in h] == ["2026-10-20", "2026-10-21"] and h[-1]["n_sims"] == 5000
    assert RC.history({"history": h}, {"ok": False}) == h                     # a failed simulation keeps the series
    assert [x["as_of"] for x in RC.history({"history": h}, _sim("2027-01-05"))] == ["2027-01-05"]   # new season


def test_similar_players_recipe():
    feats = {"a": {"x": 0.0, "y": 0.0}, "b": {"x": 0.1, "y": 0.0}, "c": {"x": 5.0, "y": 5.0}, "d": {"x": 0.0, "y": None}}
    out = PL.similar_players(feats, {"x": 0.8, "y": 0.4}, k=2)
    assert out["a"][0][0] in ("b", "d") and out["c"][-1][0] in ("a", "b", "d")
    assert all(row[1] >= 0 for rows in out.values() for row in rows)
    assert "a" not in [r[0] for r in out["a"]]


def _cat():
    def row(m, q, elo, surf):
        return {"name": f"P{elo}", "matches": m, "qualified": q,
                "values": {"elo": elo, "elo_clay": elo - 50, "elo_grass": elo - 80, "elo_hard": elo, "hold": 0.8, "brk": 0.2 + elo / 1e4,
                           "games_won_pct": 0.5 + elo / 1e5, "tb_per_set": 0.1, "win_pct": 0.5},
                "pct": {"elo": 50, "hold": 50}, "rank_metric": {"elo": 3},
                "values_surface": {"clay": {"matches": surf, "hold": 0.8, "brk": 0.25, "games_won_pct": 0.5, "elo_surface": elo - 50, "elo": elo}},
                "pct_surface": {"clay": {"hold": 40, "elo_surface": 70, "elo": 60}}}
    P = {f"p{i}": row(30, True, 1500 + 10 * i, 10) for i in range(8)}
    P["low"] = row(5, False, 1600, 2)
    return {"year": 2026, "floor": 18, "surface_floor": {"hard": 10, "clay": 8, "grass": 5}, "players": P}


def test_peer_blocks():
    blocks = PL.peer_blocks(_cat(), "atp")
    b = blocks["p3"]
    g = b["groups"]["all"]
    assert g["group"] == "atp_all" and g["in_pool"] and g["pool"] == 8 and g["headline"][0] == "elo"
    assert g["pct"] == {"elo": 50, "hold": 50} and g["rank"] == {"elo": 3}
    c = b["groups"]["clay"]
    assert c["group"] == "atp_clay" and c["pct"]["elo_clay"] == 70 and c["pct"]["elo"] == 60 and c["values"]["elo_clay"] == 1480
    assert len(b["similar"]) == 5 and "p3" not in [s["id"] for s in b["similar"]] and len(b["similar_surface"]["clay"]) == 5
    low = blocks["low"]
    assert not low["groups"]["all"]["in_pool"] and low["groups"]["all"]["pct"] == {} and low["similar"] == []
    assert "low" not in [s["id"] for s in b["similar"]]
