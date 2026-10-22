"""Gridiron player movement (analytics/movement.py): labels from synthetic weekly rosters, bye weeks, camp lists,
no look-ahead in the features, the payload's shape."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from oddsmarkets.common import movement as MV
from oddsmarkets.nfl.analytics import movement as NM


def _rows(season, team, pid, weeks, status="ACT", pos="WR"):
    return [{"season": season, "team": team, "week": w, "status": status, "gsis_id": pid, "game_type": "REG", "position": pos,
             "full_name": pid, "birth_date": "1996-01-01", "years_exp": 4, "entry_year": season - 4, "draft_number": 40}
            for w in weeks]


def _world(rosters: dict[int, list[dict]]) -> NM.World:
    W = object.__new__(NM.World)
    W.today = date(2026, 10, 22)
    W.rosters = {s: pd.DataFrame(r) for s, r in rosters.items()}
    W.stats, W.values, W.cache, W.names = {}, {}, {}, {}
    games = []
    for s in rosters:
        for wk in range(1, 18):
            games.append({"season": s, "game_type": "REG", "week": wk, "gameday": f"{s}-{9 + (wk + 7) // 5:02d}-{1 + (7 * wk) % 27:02d}",
                          "home_team": "KC", "away_team": "BUF", "home_score": 20, "away_score": 17})
    W.sched = pd.DataFrame(games)
    W.seasons = sorted(rosters)
    return W


def test_labels_trade_release_offseason_and_bye_week():
    r24 = []
    r24 += _rows(2024, "KC", "stay", range(1, 18))
    r24 += _rows(2024, "KC", "traded", range(1, 8)) + _rows(2024, "BUF", "traded", range(8, 18))      # moved straight on
    r24 += _rows(2024, "KC", "cut", range(1, 10))                                                     # gone in season
    r24 += _rows(2024, "KC", "fa", range(1, 18))                                                      # gone in the offseason
    r24 += _rows(2024, "BUF", "bye", [1, 2, 3, 4, 5] + list(range(7, 18)))                           # his team on a bye in week 6
    r24 += _rows(2024, "BUF", "x", [1, 2, 3, 4, 5] + list(range(7, 18)))                             # the whole team
    r25 = _rows(2025, "KC", "stay", range(1, 18)) + _rows(2025, "BUF", "traded", range(1, 18)) + _rows(2025, "NYJ", "fa", range(1, 18)) \
        + _rows(2025, "BUF", "bye", range(1, 18)) + _rows(2025, "BUF", "x", range(1, 18))
    W = _world({2023: _rows(2023, "KC", "stay", range(1, 18)), 2024: r24, 2025: r25})
    W.deadline_week = lambda s: 9
    df = NM.panel(W, 6, [2024]).set_index("pid")
    assert set(df.index) == {"stay", "traded", "cut", "fa", "bye", "x"}            # the bye-week team's list is week 5's
    assert df.loc["traded", "y_dl"] == 1 and df.loc["traded", "dest_dl"] == "BUF"
    assert df.loc["cut", "y_dl"] == 0 and df.loc["stay", "y_dl"] == 0
    assert df.loc["stay", "y_next"] == 0 and df.loc["bye", "y_next"] == 0
    assert df.loc["traded", "y_type"] == 0 and df.loc["cut", "y_type"] == 1 and df.loc["fa", "y_type"] == 2
    assert df.loc["fa", "dest"] == "NYJ"
    assert df.loc["stay", "tenure"] == 1                                             # with KC at the end of 2023


def test_camp_list_week_is_skipped():
    camp = []
    for i in range(90):
        camp += _rows(2025, "KC", f"p{i}", [1])
    camp += _rows(2025, "KC", "kept", [2])
    for i in range(50):
        camp += _rows(2025, "KC", f"q{i}", [2])
    W = _world({2025: camp})
    wk1 = NM._week1(W, 2025)
    assert "kept" in wk1 and "p0" not in wk1


def test_no_unsettled_labels_and_payload_shape():
    rng = np.random.default_rng(0)
    rows = []
    for s in range(2010, 2021):
        for t in ("A", "B", "C", "D"):
            for i in range(40):
                x = rng.normal()
                rows.append({"season": s, "pid": f"{s}{t}{i}", "tid": t, "pos": ["QB", "WR", "CB", "OL"][i % 4], "age": 25 + i % 10,
                             "yrs": i % 10, "vnow": max(0.0, x * 5), "team_wp": 0.3 + 0.1 * "ABCD".index(t), "team_traj": 0.0,
                             "team_turn": 0.4, "x": x, "y_next": float(rng.random() < 1 / (1 + np.exp(-x))) if s < 2020 else np.nan,
                             "y_type": int(rng.integers(0, 3)), "y_dl": float(rng.random() < 0.05) if s < 2020 else np.nan,
                             "dest": None, "dest_dl": None})
    df = pd.DataFrame(rows)
    df.loc[df["y_next"] != 1, "y_type"] = -1
    mv = (df["y_next"] == 1) & (df["season"] < 2020)
    df.loc[mv, "dest"] = df.loc[mv, "tid"].map({"A": "B", "B": "C", "C": "D", "D": "A"})
    cfg = MV.Config(level="t", version="t", feats=["x", "age"], quad=[], dl_feats=["x"], type_feats=["x"], arr_feats=["need", "team_wp"],
                    types=NM.TYPES, type_label=NM.TYPE_LABEL, dev=[2015, 2016], test=[2017, 2018, 2019], slots=NM.SLOTS,
                    inseason_gap=0, team_horizon="next")
    res = MV.research(df, cfg, {}, "inseason")
    pay = MV.payload(df, cfg, {}, res, "inseason", 2020, {}, "2026-10-22", {"deadline": "2026-11-03"})
    assert len(pay["players"]) == 160 and len(pay["player_fields"]) == len(pay["players"][0])
    assert pay["team_horizon"] == "next" and set(pay["teams"]) == {"A", "B", "C", "D"}
    assert set(pay["published"]) == {"next", "deadline", "type", "arrivals", "targets"}
    if pay["published"]["next"]:
        i = pay["player_fields"].index
        for r in pay["players"]:
            assert abs(sum(r[i("p_" + t)] for t in NM.TYPES) - r[i("p_next")]) < 0.01
