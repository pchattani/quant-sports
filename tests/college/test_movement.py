"""
Who moves next on The Quant Campus (oddsmarkets/college/movement.py): labels from box scores, no look-ahead in the
features, the season-intercept model on a planted rule, the gate on the current season, and the payloads.

Offline: synthetic basketball stores (12 teams of 8, seasons 2012-2021) with planted moves: a player leaves the data
after four seasons; a bench player (little playing time) transfers with probability 0.5; everyone else stays.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pytest

from oddsmarkets.college import movement as MV
from oddsmarkets.college import packing
from oddsmarkets.college import store as ST

TEAMS = [str(100 + k) for k in range(12)]
CUR = 2021


def _world(seed: int = 4):
    """{season: {pid: (team, years, bench)}}: who plays where each season under the planted rule."""
    rng = np.random.default_rng(seed)
    nid = [1000]

    def new(team):
        nid[0] += 1
        return str(nid[0])

    seasons = {}
    rosters = {t: [(new(t), int(rng.integers(0, 4))) for _ in range(8)] for t in TEAMS}
    for s in range(2010, CUR + 1):
        cur = {}
        for t, lst in rosters.items():
            for k, (p, yrs) in enumerate(lst):
                cur[p] = (t, yrs, k >= 5)                     # the last three of each team play little
        seasons[s] = cur
        nxt = {t: [] for t in TEAMS}
        for p, (t, yrs, bench) in cur.items():
            if yrs >= 3:
                continue                                       # four seasons: leaves the data
            if bench and rng.random() < 0.5:
                dest = TEAMS[(TEAMS.index(t) + 1 + int(rng.integers(0, 11))) % 12]
                nxt[dest].append((p, yrs + 1))
            else:
                nxt[t].append((p, yrs + 1))
        for t in TEAMS:
            regulars = [x for x in nxt[t]][:5]
            rest = [x for x in nxt[t]][5:]
            while len(regulars) + len(rest) < 8:
                rest.append((new(t), 0))
            nxt[t] = regulars + rest
        rosters = nxt
    return seasons


def _write_stores(world, played=lambda s: True):
    for s, cur in world.items():
        st = ST.new_store("mbb", s)
        st["teams"] = {t: {"name": f"Team {t}", "short": f"T{t}", "conference": "1" if int(t) < 106 else "2", "member": True}
                       for t in TEAMS}
        by_team = {t: [p for p, v in cur.items() if v[0] == t] for t in TEAMS}
        st["rosters"] = by_team
        st["players"] = {p: {"name": f"P{p}", "pos": "G" if int(p) % 2 else "F", "class": "SR" if v[1] >= 3 else "FR"}
                         for p, v in cur.items()}
        if played(s):
            d0 = date(s - 1, 11, 10)
            gid = 0
            for w in range(14):
                for k in range(6):
                    h, a = TEAMS[(2 * k + w) % 12], TEAMS[(2 * k + 1 + w) % 12]
                    if h == a:
                        continue
                    gid += 1
                    box = {}
                    for t in (h, a):
                        rows = []
                        for j, p in enumerate(by_team[t]):
                            bench = cur[p][2]
                            sec = (8 if bench else 34) * 60
                            pts = 3 if bench else 12 + (int(p) % 5)
                            rows.append([p, not bench, sec, pts, pts // 2, pts, 0, 1, 0, 0, 1, 2, 1, 0, 0, 1, 1])
                        box[t] = {"players": rows, "team": {"fga": 60, "fta": 15, "tov": 10}}
                    st["games"][f"{s}{gid:04d}"] = {"id": f"{s}{gid:04d}", "date": (d0 + timedelta(days=3 * w)).isoformat() + "T23:00:00Z",
                                                    "status": "post", "home": h, "away": a, "hs": 70 + int(h) % 7,
                                                    "as": 68 + int(a) % 5, "box": box}
        ST.save(st)


@pytest.fixture
def stores(tmp_path, monkeypatch):
    for k, d in (("CAMPUS_STORES", "stores"), ("CAMPUS_RAW", "raw"), ("CAMPUS_CACHE", "cache"), ("CAMPUS_DATA", "data")):
        monkeypatch.setenv(k, str(tmp_path / d))
    monkeypatch.setattr(MV, "FIRST_ROSTER_SEASON", 2012)
    monkeypatch.setattr(MV, "MIN_PANEL", 10)
    world = _world()
    _write_stores(world)
    return tmp_path, world


def test_labels_come_from_next_seasons_box_scores_and_features_from_this_season(stores) -> None:
    tmp, world = stores
    infos = {s: MV.season_info("mbb", s) for s in range(2011, CUR + 1)}
    P = MV.build_panel("mbb", 2016, infos, labels=True)
    assert P is not None and len(P) == len(world[2016])
    nxt = world[2017]
    for i, p in enumerate(P.pid):
        if p not in nxt:
            assert P.y[i] == 1 and P.typ[i] == 0 and P.dest[i] is None          # left the data
        elif nxt[p][0] != P.tid[i]:
            assert P.y[i] == 1 and P.typ[i] == 1 and P.dest[i] == nxt[p][0]      # inferred transfer
        else:
            assert P.y[i] == 0
    # The next season's data never enters the features.
    infos2 = dict(infos)
    infos2[2017] = {**infos[2017], "box": {}, "margin": {}}
    P2 = MV.build_panel("mbb", 2016, infos2, labels=False)
    assert P2.pid == P.pid and np.allclose(P2.X, P.X)
    # An incomplete next season is not labelled.
    infos3 = dict(infos)
    infos3[2017] = {**infos[2017], "n_box_games": infos[2016]["n_box_games"] // 3}
    assert MV.build_panel("mbb", 2016, infos3, labels=True) is None


def test_the_model_learns_the_planted_rule(stores) -> None:
    res = MV.build_movement("mbb", CUR)
    assert res["meta"]["ok"], res["meta"]
    rows = res["players"]
    world = _world()
    senior = [r["p"] for r in rows if world[CUR][r["id"]][1] >= 3]
    young_starter = [r["p"] for r in rows if world[CUR][r["id"]][1] < 3 and not world[CUR][r["id"]][2]]
    bench = [r["p_transfer"] for r in rows if world[CUR][r["id"]][1] < 3 and world[CUR][r["id"]][2]]
    young_starter_tr = [r["p_transfer"] for r in rows if world[CUR][r["id"]][1] < 3 and not world[CUR][r["id"]][2]]
    assert np.mean(senior) > np.mean(young_starter) + 0.3
    assert np.mean(bench) > np.mean(young_starter_tr) + 0.15
    for r in rows:
        assert 0 <= r["p_transfer"] <= r["p"] <= 1 and abs(r["p"] - r["p_transfer"] - r["p_gone"]) < 0.002
    t = res["teams"][TEAMS[0]]
    assert set(t["expected_out"]) == set(MV.POS_GROUPS["mbb"]) and t["targets"] is not None
    assert all(x["team"] != TEAMS[0] for x in t["targets"])
    assert [x["p_join"] for x in t["targets"]] == sorted((x["p_join"] for x in t["targets"]), reverse=True)


def test_the_current_season_waits_for_box_scores_and_the_writer_adds_team_blocks(tmp_path, monkeypatch) -> None:
    for k, d in (("CAMPUS_STORES", "stores"), ("CAMPUS_RAW", "raw"), ("CAMPUS_CACHE", "cache"), ("CAMPUS_DATA", "data")):
        monkeypatch.setenv(k, str(tmp_path / d))
    monkeypatch.setattr(MV, "FIRST_ROSTER_SEASON", 2012)
    monkeypatch.setattr(MV, "MIN_PANEL", 10)
    world = _world()
    _write_stores(world, played=lambda s: s < CUR)
    res = MV.build_movement("mbb", CUR)
    assert res["meta"]["ok"] is False and "box scores" in res["meta"]["reason"]
    _write_stores(world)
    data = tmp_path / "data"
    (data / "mbb" / str(CUR) / "teams").mkdir(parents=True)
    for t in TEAMS:
        (data / "mbb" / str(CUR) / "teams" / f"{t}.json").write_text(json.dumps({"ok": True, "id": t}), encoding="utf-8")
    out = MV.write_movement("mbb", data, CUR)
    assert out["published"] and out["team_pages"] == len(TEAMS)
    doc = json.loads((data / "mbb" / str(CUR) / "movement.json").read_text(encoding="utf-8"))
    assert doc["ok"] and doc["meta"]["inferred"] and "not the official transfer portal" in doc["meta"]["method"]
    players = packing.unpack(doc["players"])
    assert len(players) == len(world[CUR]) and set(players[0]) <= set(MV.P_COLS)
    page = json.loads((data / "mbb" / str(CUR) / "teams" / f"{TEAMS[3]}.json").read_text(encoding="utf-8"))
    assert page["id"] == TEAMS[3] and page["movement"]["next_season"] == CUR + 1


def test_football_positions_are_inferred_the_same_way_every_season() -> None:
    assert MV._pos_cfb({"pass": 2000, "rush": 300}) == "QB"
    assert MV._pos_cfb({"rush": 800, "rec": 100}) == "RB"
    assert MV._pos_cfb({"rec": 600}) == "WR"
    assert MV._pos_cfb({"tkl": 40, "pd": 8, "defp": 60}) == "DB"
    assert MV._pos_cfb({"tkl": 30, "sacks": 6, "tfl": 9, "defp": 70}) == "DL"
    assert MV._pos_cfb({"tkl": 80, "tfl": 3, "defp": 90}) == "LB"
    assert MV._pos_cfb({"kick": 12}) == "K"
    assert MV._ordinal(91) == "91st" and MV._ordinal(12) == "12th" and MV._ordinal(23) == "23rd"
