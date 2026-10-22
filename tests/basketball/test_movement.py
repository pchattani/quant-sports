"""Hardwood player movement (analytics/movement.py): labels from synthetic box-score listings, no look-ahead in the
season-start features, and the payload's shape."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

import pytest

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import movement as HM

TEAMS = ["1", "2", "3", "4", "5", "6"]


def _season_dates(s: int) -> list[date]:
    lo = date(s - 1, 11, 1)
    return [lo + timedelta(days=3 * k) for k in range(50)]          # 1 Nov to mid-April, every third day


def _write_league(root, seasons, plan):
    """plan(s, d, roster) -> roster after date d: {tid: [pids]}; every team plays every listed date."""
    rng = random.Random(4)
    roster = {t: [f"{t}{i:02d}" for i in range(9)] for t in TEAMS}
    players = {}
    for s in seasons:
        games = {}
        dates = _season_dates(s)
        for k, d in enumerate(dates):
            roster = plan(s, d, roster)
            for j in range(0, len(TEAMS), 2):
                h, a = TEAMS[j], TEAMS[j + 1] if k % 2 == 0 else TEAMS[(j + 3) % len(TEAMS)]
                if h == a:
                    a = TEAMS[(j + 1) % len(TEAMS)]
                box = {t: {"players": [[p, 1, rng.randint(300, 2000)] + [0] * 15 for p in roster[t][:8]],
                           "dnp": [[p, "COACH'S DECISION"] for p in roster[t][8:]]} for t in (h, a)}
                gid = f"{s}{k:03d}{j}"
                games[gid] = {"id": gid, "date": d.isoformat() + "T00:00Z", "status": "post", "stype": "reg", "home": h, "away": a,
                              "hs": 100 + rng.randint(0, 20), "as": 100 + rng.randint(0, 20), "box": box}
            for t, ps in roster.items():
                for p in ps:
                    players.setdefault(p, {"name": f"Player {p}", "pool": "GFC"[int(p[-1]) % 3]})
        st = {"league": "nba", "season": s, "updated_at": None, "teams": {t: {"name": f"Team {t}", "conference": "East" if int(t) < 4 else "West"}
                                                                       for t in TEAMS},
              "players": players, "games": games, "meta": {"fetched": {}, "complete_through": None}}
        d = root / "nba" / str(s)
        d.mkdir(parents=True, exist_ok=True)
        (d / "store.json").write_text(json.dumps(st), encoding="utf-8")


def _move(roster, pid, to):
    roster = {t: [p for p in ps if p != pid] for t, ps in roster.items()}
    roster[to] = roster[to] + [pid]
    return roster


def _on(roster, pid, t):
    return pid in roster.get(t, [])


def _plan(s, d, roster):
    if s == 2008 and d >= date(2008, 1, 9) and _on(roster, "100", "1"):          # a deadline move, 1 -> 2
        roster = _move(roster, "100", "2")
    if s == 2009 and _on(roster, "201", "2"):                                   # an offseason move: 2 -> 3 for 2009
        roster = _move(roster, "201", "3")
    if s == 2010 and d >= date(2009, 12, 1):                                    # waived by 3, not listed again this season
        roster = {t: [p for p in ps if p != "302"] for t, ps in roster.items()}
    if s == 2011 and not any("302" in ps for ps in roster.values()):            # signs with 4 next season
        roster = dict(roster)
        roster["4"] = roster["4"] + ["302"]
    return roster


@pytest.fixture
def league(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path))
    monkeypatch.setenv("HARDWOOD_CACHE", str(tmp_path / "cache"))
    an.set_data_root(tmp_path)
    _write_league(tmp_path, list(range(2003, 2013)), _plan)
    yield tmp_path
    an.set_data_root(None)


def test_direct_move_rules():
    seq = [("2008-01-01", "1", 600, "reg"), ("2008-01-07", "1", 0, "reg"), ("2008-01-13", "2", 900, "reg")]
    assert HM.direct_move(seq, "1", "2007-11-01")[0] == "2"
    assert HM.direct_move(seq, "1", "2007-11-01", until=date(2008, 1, 10))[0] is None    # first listed there too late
    gap = [("2008-01-01", "1", 600, "reg"), ("2008-03-01", "2", 900, "reg")]
    assert HM.direct_move(gap, "1", "2007-11-01")[0] is None                                # a long gap: not a direct move


def test_labels_from_listings(league):
    W = HM.World("nba", date(2012, 6, 1))
    df = HM.panel(W, "inseason", 0.0)
    row = lambda s, pid: df[(df["season"] == s) & (df["pid"] == pid)].iloc[0]
    r = row(2008, "100")
    assert r["tid"] == "1" and r["y_dl"] == 1.0 and r["dest_dl"] == "2"
    assert r["y_next"] == 1.0 and r["y_type"] == HM.TYPES.index("trade")
    r = row(2008, "201")
    assert r["y_next"] == 1.0 and r["y_type"] == HM.TYPES.index("other") and r["dest"] == "3" and r["y_dl"] == 0.0
    r = row(2010, "302")
    assert r["tid"] == "3" and r["y_next"] == 1.0 and r["y_type"] == HM.TYPES.index("release") and r["dest"] == "4"
    stay = row(2009, "500")
    assert stay["y_next"] == 0.0 and stay["y_type"] == -1 and stay["tenure"] >= 1


def test_season_start_features_do_not_look_ahead(league):
    W = HM.World("nba", date(2012, 6, 1))
    a = HM.panel(W, "inseason", 0.0)
    # rewrite the 2010 season after its opening window: features of 2010 rows must not change, labels may
    p = league / "nba" / "2010" / "store.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    for g in st["games"].values():
        if g["date"][:10] > "2009-11-20":
            for b in g["box"].values():
                for r in b["players"]:
                    r[2] = 1
    p.write_text(json.dumps(st), encoding="utf-8")
    an.set_data_root(league)
    b = HM.panel(HM.World("nba", date(2012, 6, 1)), "inseason", 0.0)
    feats = [f for f in HM.config("nba", "inseason").feats if f not in ("team_turn",)]
    x = a[a["season"] == 2010].sort_values("pid")[feats].reset_index(drop=True)
    y = b[b["season"] == 2010].sort_values("pid")[feats].reset_index(drop=True)
    assert x.equals(y)


def test_payload_shape(league, monkeypatch):
    monkeypatch.setitem(HM.SPLITS, "nba", {"dev": [2008, 2009], "test": [2010, 2011]})
    pay = HM.build("nba", date(2011, 11, 3))
    assert pay and pay["ok"] and pay["phase"] == "inseason" and pay["version"] == HM.VERSION
    for k in ("published", "reasons", "base_rates", "recent_rates", "player_fields", "players", "team_fields", "teams", "validation",
              "horizons", "types", "type_labels", "notes", "deadline_label", "roster_source"):
        assert k in pay
    assert pay["deadline_label"] == "traded or claimed"
    assert all(len(r) == len(pay["player_fields"]) for r in pay["players"])
    assert set(pay["teams"]) <= set(TEAMS)
    json.dumps(pay, allow_nan=False)                                                        # strict JSON as is
    for k, ok in pay["published"].items():
        if not ok and k in ("next", "deadline"):
            col = pay["player_fields"].index("p_next" if k == "next" else "p_dl")
            assert all(r[col] is None for r in pay["players"])
