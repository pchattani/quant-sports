"""Player movement for the Rink (analytics/movement.py): labels from appearances, no look-ahead, payload shape."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from oddsmarkets.common import movement as MV
from oddsmarkets.nhl.analytics import movement as RM

S0, S1, S2 = 20222023, 20232024, 20242025


def _world(today=date(2025, 10, 30)):
    """Three seasons, clubs AAA / BBB / CCC; players: p1 stays, p2 traded AAA -> BBB in February, p3 gone next season,
    p4 claimed after the deadline, p5 on Arizona then Utah (a relocation, not a departure)."""
    W = RM.World.__new__(RM.World)
    W.today, W.cache, W.espn, W.draft, W.league = today, {}, {}, {}, {"AAA": "E", "BBB": "E", "CCC": "W", "UTA": "W"}
    W.people = {p: {"dob": "1995-01-01"} for p in ("p1", "p2", "p3", "p4", "p5")}
    W.names = {p: p.upper() for p in W.people}
    W.value = {s: {p: {"war": 1.0, "pos": "C", "kind": "S"} for p in W.people} for s in (S0, S1, S2)}
    W.bounds, W.app, W.games = {}, {}, {}
    rows = {S0: [], S1: [], S2: []}
    gid = 0

    def add(s, d, pid, team, toi=15.0):
        nonlocal gid
        gid += 1
        rows[s].append({"game_id": int(f"{str(s)[:4]}02{gid:04d}"), "team": team, "pid": pid, "pos": "C", "toi": toi, "kind": "S", "date": d})

    for s, y in ((S0, 2022), (S1, 2023), (S2, 2024)):
        W.bounds[s] = (date(y, 10, 10), date(y + 1, 4, 15))
        for m, d in ((10, 12), (11, 1), (12, 1), (1, 10), (2, 20), (3, 20), (4, 10)):
            yy = y if m >= 10 else y + 1
            ds = f"{yy}-{m:02d}-{d:02d}"
            add(s, ds, "p1", "AAA")
            if s == S1:
                add(s, ds, "p2", "AAA" if (m >= 10 or m == 1) else "BBB")         # last AAA game 10 Jan, BBB from 20 Feb
                add(s, ds, "p4", "AAA" if (m >= 10 or m <= 3) else "CCC")         # moved in April, after the deadline
                add(s, ds, "p5", "ARI")
            if s == S0:
                add(s, ds, "p3", "AAA")
                add(s, ds, "p5", "ARI")
            if s == S2:
                add(s, ds, "p5", "UTA")
                add(s, ds, "p2", "BBB")
        W.games[s] = pd.DataFrame([{"date": f"{y}-11-01", "home": "AAA", "away": "BBB", "hs": 3, "as": 2, "ot": False}])
    for s in rows:
        a = pd.DataFrame(rows[s])
        a["team"] = a["team"].map(RM.fr)
        W.app[s] = a.sort_values(["date", "game_id"]).reset_index(drop=True)
    W.seasons = sorted(W.app)
    return W


def test_move_before_deadline_and_relocation():
    dl = date(2024, 3, 8)
    assert RM.move_before([("2024-01-10", "AAA"), ("2024-02-20", "BBB")], "AAA", dl) == "BBB"
    assert RM.move_before([("2024-03-20", "AAA"), ("2024-04-10", "CCC")], "AAA", dl) is None           # after the deadline
    assert RM.move_before([("2024-01-10", "AAA")], "AAA", dl) is None
    assert RM.fr("ARI") == RM.fr("UTA") == RM.fr("PHX") and RM.fr("ATL") == "WPG"
    assert RM.espn_type([("2024-12-01", "trade", "AAA")], date(2024, 10, 1), date(2025, 10, 1)) == 0
    assert RM.espn_type([("2024-12-01", "release", "AAA")], date(2024, 10, 1), date(2025, 10, 1)) == 1
    assert RM.espn_type([], date(2024, 10, 1), date(2025, 10, 1)) == 2


def test_labels_from_appearances():
    W = _world()
    df = RM.panel(W, "inseason", 0.05, seasons=[S1])
    r = df.set_index("pid")
    assert r.loc["p2", "y_dl"] == 1 and r.loc["p2", "dest_dl"] == "BBB"
    assert r.loc["p4", "y_dl"] == 0                                   # moved after the deadline
    assert r.loc["p1", "y_next"] == 0 and r.loc["p2", "y_next"] == 1 and r.loc["p4", "y_next"] == 1
    assert r.loc["p5", "y_next"] == 0 and r.loc["p5", "tid"] == "UTA"      # Arizona to Utah is the same club
    df0 = RM.panel(W, "inseason", 0.05, seasons=[S0])
    assert df0.set_index("pid").loc["p3", "y_next"] == 1              # no NHL game next season


def test_features_ignore_games_after_the_snapshot():
    W = _world()
    a = RM.panel(W, "inseason", 0.05, seasons=[S1]).set_index("pid")
    W2 = _world()
    extra = W2.app[S1].iloc[-1:].copy()
    extra["date"], extra["toi"] = "2024-04-14", 60.0                     # a big late game must not move the snapshot
    W2.app[S1] = pd.concat([W2.app[S1], extra], ignore_index=True)
    b = RM.panel(W2, "inseason", 0.05, seasons=[S1]).set_index("pid")
    for c in ("share", "gp_share", "joined", "tenure", "v_prev", "team_wp"):
        assert np.allclose(a[c].astype(float).fillna(-9), b.loc[a.index, c].astype(float).fillna(-9)), c


def test_labels_unknown_until_the_next_season_is_complete():
    W = _world(today=date(2025, 1, 5))
    df = RM.panel(W, "inseason", 0.05, seasons=[S1])
    assert df["y_next"].isna().all() and df["y_dl"].notna().all()


def test_payload_shape():
    rng = np.random.default_rng(0)
    rows = []
    clubs = ["AAA", "BBB", "CCC", "DDD"]
    for s in (2022, 2023, 2024, 2025):                                  # the engine's seasons are start years
        for i in range(160):
            t = clubs[i % 4]
            rows.append({"season": s, "pid": f"{s}{i}", "tid": t, "pos": ["C", "LW", "RW", "D", "G"][i % 5], "age": 22 + i % 14,
                         "yrs": 1 + i % 10, "vnow": rng.normal(), "team_wp": 0.5 + 0.02 * (i % 4), "team_traj": 0.0, "team_turn": 0.3,
                         **{f: rng.normal() for f in RM.DL_FEATS if f not in ("age", "yrs", "team_wp", "team_traj", "team_turn")},
                         "y_next": float(rng.random() < 0.3) if s < 2024 else np.nan, "y_type": -1,
                         "y_dl": float(rng.random() < 0.1) if s < 2025 else np.nan,
                         "dest": None, "dest_dl": clubs[(i + 1) % 4] if (s < 2025 and i % 9 == 0) else None})
    df = pd.DataFrame(rows)
    res = {k: {"l2": 1.0, "test_eval": {"passed": True}} for k in ("next", "deadline", "arrivals")}
    res["type"] = {"l2": None, "test_eval": None}
    res["targets"] = {"k": 10, "test_eval": None}
    pay = MV.payload(df, RM.CFG, {}, res, "inseason", 2025, {}, "2026-10-22", {"deadline": "2027-03-05", "next": "x"})
    assert pay["player_fields"][-2:] == ["p_dl", "why"] and len(pay["players"]) == 160
    assert pay["published"]["type"] is False and pay["deadline_label"] == "traded or claimed"
    i = pay["player_fields"].index("p_next")
    for r in pay["players"]:
        parts = sum(r[i + 1 + k] for k in range(len(RM.TYPES)))
        assert abs(parts - r[i]) < 1e-2                                   # the type split adds up to the departure chance
    assert set(pay["teams"]) == set(clubs) and all(t["targets"] == [] for t in pay["teams"].values())


def test_engine_seasons_are_consecutive_start_years():
    assert RM.DEV_Y == list(range(2013, 2022)) and RM.TEST_Y == [2022, 2023, 2024]
    W = _world()
    df = RM.frame(W, "inseason", 0.05)
    assert sorted(df["season"].unique()) == [2023, 2024]                 # 2022-23 has no previous season here
