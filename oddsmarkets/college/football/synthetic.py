"""
A small synthetic college football world for the tests (no network): two or more seasons of stores and plays in
the CONTRACT.md shapes, written under the CAMPUS_STORES / CAMPUS_RAW roots.

`make_world(root, seasons=(2023, 2024), current_unplayed=0.3)` writes stores and plays for 3 conferences of 8 FBS
teams plus 4 FCS teams, a 10-game regular season, conference title games, a 4-team (2014-2023) or 12-team
playoff in completed seasons, AP / CFP rankings, closing lines and box scores. The last season leaves
`current_unplayed` of its regular season unplayed (status "pre"). Team strengths are fixed and known
(`world["strength"]`) so tests can check the ratings recover them.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from oddsmarkets.college import store

CONFS = {"1": "ACC", "4": "Big 12", "8": "SEC"}


def _names(rng, n):
    first = ["Alex", "Blake", "Carter", "Drew", "Evan", "Finn", "Gage", "Hunter", "Ian", "Jace", "Kyle", "Luke"]
    last = ["Adams", "Brown", "Clark", "Davis", "Evans", "Foster", "Green", "Hill", "Irwin", "Jones", "King", "Lewis",
            "Moore", "Nash", "Owens", "Price", "Reed", "Scott", "Turner", "Vance", "Wells", "Young"]
    return [f"{first[rng.integers(len(first))]} {last[rng.integers(len(last))]}{i}" for i in range(n)]


def make_world(root: Path, seasons=(2023, 2024), current_unplayed: float = 0.3, seed: int = 11) -> dict:
    root = Path(root)
    os.environ["CAMPUS_STORES"] = str(root / "stores")
    os.environ["CAMPUS_RAW"] = str(root / "raw")
    os.environ["CAMPUS_CACHE"] = str(root / "cache")
    os.environ["CAMPUS_DATA"] = str(root / "data")
    rng = np.random.default_rng(seed)
    fbs = [str(100 + i) for i in range(24)]
    fcs = [str(900 + i) for i in range(4)]
    conf_of = {t: list(CONFS)[i // 8] for i, t in enumerate(fbs)}
    strength = {t: float(rng.normal(0, 10)) for t in fbs}
    strength.update({t: float(rng.normal(-25, 5)) for t in fcs})
    roster = {}
    pid = 5000
    for t in fbs + fcs:
        nm = _names(rng, 6)
        roster[t] = []
        for k, pos in enumerate(["QB", "RB", "WR", "TE", "LB", "PK"]):
            roster[t].append((str(pid), nm[k], pos, str(k + 1)))
            pid += 1
    world = {"fbs": fbs, "fcs": fcs, "strength": strength, "conf_of": conf_of, "seasons": list(seasons)}
    for si, S in enumerate(seasons):
        last = si == len(seasons) - 1
        st = store.new_store("cfb", S)
        st["conferences"] = {c: {"name": f"{n} Conference", "short": n, "abbr": n.lower(), "fbs": True, "divisions": {}}
                             for c, n in CONFS.items()}
        for t in fbs + fcs:
            st["teams"][t] = {"name": f"Team {t}", "short": f"T{t}", "abbr": f"T{t}", "location": f"Team {t}", "nickname": "X",
                              "colour": "#123456", "alt_colour": "#ffffff", "conference": conf_of.get(t), "member": t in fbs,
                              "division": None, "venue": None}
        for t, ps in roster.items():
            st["rosters"][t] = [p[0] for p in ps]
            for p, nm, pos, j in ps:
                st["players"][p] = {"name": nm, "short": None, "pos": pos, "jersey": j, "class": "JR", "height_in": 72,
                                    "weight_lb": 200, "hometown": None, "teams": [t]}
        start = date(S, 8, 30)
        cal = [[2, w, f"Week {w}", (start + timedelta(days=7 * (w - 1) - 3)).isoformat(),
                (start + timedelta(days=7 * w - 3)).isoformat()] for w in range(1, 13)]
        cal.append([3, 1, "Bowls", (start + timedelta(days=7 * 12 - 3)).isoformat(), date(S + 1, 1, 20).isoformat()])
        st["meta"]["calendar"] = cal
        plays = store.new_plays(S)
        plays["types"] = {"5": "Rush", "24": "Pass Reception", "3": "Pass Incompletion", "52": "Punt", "59": "Field Goal Good",
                          "68": "Rushing Touchdown", "53": "Kickoff"}
        gid = S * 10000
        games = []
        # schedule: each week FBS teams paired at random (conference games weeks 4-10), FCS games week 1
        for w in range(1, 11):
            ts = list(fbs)
            rng.shuffle(ts)
            if w == 1:
                for k, f in enumerate(fcs):
                    games.append((w, ts[k], f, False))
                ts = ts[len(fcs):]
            if 4 <= w <= 10:
                pairs = []
                for c in CONFS:
                    cm = [t for t in ts if conf_of[t] == c]
                    pairs += [(cm[i], cm[i + 1], True) for i in range(0, len(cm) - 1, 2)]
            else:
                pairs = [(ts[i], ts[i + 1], False) for i in range(0, len(ts) - 1, 2)]
            for h, a, cg in pairs:
                games.append((w, h, a, cg))
        n_reg = len(games)
        cut = int(n_reg * (1 - current_unplayed)) if last else n_reg
        rows = []
        for k, (w, h, a, cg) in enumerate(games):
            day = start + timedelta(days=7 * (w - 1))
            played = k < cut
            rows.append(_game(st, plays, rng, str(gid + k), day, w, h, a, cg, played, strength, roster, "reg"))
        gid += len(games)
        if not last:
            # conference championships: top two by conference wins
            wins = {t: 0 for t in fbs}
            for g in st["games"].values():
                if g["status"] == "post" and g["conf_game"]:
                    wins[g["home"] if g["hs"] > g["as"] else g["away"]] += 1
            champs = []
            for c in CONFS:
                cm = sorted([t for t in fbs if conf_of[t] == c], key=lambda t: (-wins[t], -strength[t]))
                g = _game(st, plays, rng, str(gid), start + timedelta(days=7 * 11), 12, cm[0], cm[1], True, True, strength,
                          roster, "conf", neutral=True)
                gid += 1
                champs.append(g["home"] if g["hs"] > g["as"] else g["away"])
            # rankings by strength + wins (CFP top 25 weeks 9..12, AP weekly)
            allw = {t: 0 for t in fbs}
            for g in st["games"].values():
                if g["status"] == "post" and g["home"] in allw and g["away"] in allw:
                    allw[g["home"] if g["hs"] > g["as"] else g["away"]] += 1
            order = sorted(fbs, key=lambda t: -(strength[t] + 3 * allw[t] + 5 * (t in champs)))
            st["rankings"]["cfp"] = {str(w): [[i + 1, t, None, 0] for i, t in enumerate(order[:20])] for w in (9, 10, 11, 12)}
            st["rankings"]["ap"] = {str(w): [[i + 1, t, 1500 - 10 * i, 0] for i, t in enumerate(order[:20])] for w in range(2, 13)}
            field = order[:4]
            sf1 = _game(st, plays, rng, str(gid), start + timedelta(days=7 * 15), None, field[0], field[3], False, True,
                        strength, roster, "cfp", neutral=True, rnd="Semifinal", seeds=(1, 4))
            sf2 = _game(st, plays, rng, str(gid + 1), start + timedelta(days=7 * 15), None, field[1], field[2], False, True,
                        strength, roster, "cfp", neutral=True, rnd="Semifinal", seeds=(2, 3))
            f1 = sf1["home"] if sf1["hs"] > sf1["as"] else sf1["away"]
            f2 = sf2["home"] if sf2["hs"] > sf2["as"] else sf2["away"]
            _game(st, plays, rng, str(gid + 2), start + timedelta(days=7 * 17), None, f1, f2, False, True, strength, roster,
                  "cfp", neutral=True, rnd="National Championship")
            gid += 3
        else:
            st["rankings"]["ap"] = {str(w): [[i + 1, t, 1500 - 10 * i, 0] for i, t in enumerate(sorted(fbs, key=lambda t: -strength[t])[:20])]
                                    for w in range(2, 6)}
            for c in CONFS:
                st["games"][f"ph{c}"] = {"id": f"ph{c}", "date": f"{S}-12-05T20:00:00Z", "status": "pre", "stype": "conf",
                                         "round": "Championship", "region": None, "note": None, "week": 12, "neutral": True,
                                         "conf_game": True, "home": "-1", "away": "-2", "hs": None, "as": None, "periods": 0,
                                         "line": {"home": [], "away": []}, "ranks": {"home": None, "away": None}, "seeds": None,
                                         "team_stats": {}, "box": {}, "odds": None, "predictor": None, "venue": None,
                                         "attendance": None, "has_pbp": False, "summary": False}
        store.save(st)
        store.save_plays(plays)
    return world


def _game(st, plays, rng, gid, day, week, h, a, cg, played, strength, roster, stype, neutral=False, rnd=None, seeds=None):
    true = strength[h] - strength[a] + (0 if neutral else 2.5)
    o = {"provider": "Book", "spread_home": round(-(true + rng.normal(0, 2)) * 2) / 2, "total": 52.5,
         "ml_home": None, "ml_away": None, "open_spread_home": None, "open_total": None, "n_books": 1, "source": "core",
         "has_close_block": True}
    p = 1 / (1 + np.exp(-true / 7.0))
    o["ml_home"] = int(-100 * p / (1 - p)) if p > 0.5 else int(100 * (1 - p) / p)
    o["ml_away"] = int(-100 * (1 - p) / p) if p < 0.5 else int(100 * p / (1 - p))
    g = {"id": gid, "date": f"{day.isoformat()}T19:00:00Z", "status": "post" if played else "pre", "stype": stype,
         "round": rnd, "region": None, "note": None, "week": week, "neutral": neutral, "conf_game": cg, "home": h, "away": a,
         "hs": None, "as": None, "periods": 4 if played else 0, "line": {"home": [], "away": []},
         "ranks": {"home": None, "away": None}, "seeds": ({"home": seeds[0], "away": seeds[1]} if seeds else None),
         "team_stats": {}, "box": {}, "odds": o, "predictor": None, "venue": None, "attendance": None,
         "has_pbp": played, "summary": played}
    if played:
        rows, hs, as_ = _plays(rng, h, a, true, roster)
        if hs == as_:
            hs += 3
        g["hs"], g["as"] = hs, as_
        plays["games"][gid] = {"drives": [], "plays": rows}
        g["box"] = {t: _box(rng, t, roster, pts) for t, pts in ((h, hs), (a, as_))}
    st["games"][gid] = g
    return g


def _plays(rng, h, a, true, roster):
    """A plausible play sequence: alternating drives of rushes and passes ending in TD, FG or punt."""
    rows = []
    seq = 0
    score = {h: 0, a: 0}
    off = h
    for period in (1, 2, 3, 4):
        clock = 900
        while clock > 60:
            de = a if off == h else h
            edge = (true if off == h else -true) / 20.0
            yte = 75
            down, dist = 1, 10
            qb, rb, wr = roster[off][0], roster[off][1], roster[off][2]
            while True:
                seq += 1
                clock = max(clock - 30, 0)
                if rng.random() < 0.5:
                    gain = int(rng.normal(4.5 + 3 * edge, 4))
                    tp, text = 5, f"({clock // 60:02d}:{clock % 60:02d}) Shotgun #{rb[3]} {rb[1][0]}.{rb[1].split()[1]} rush middle for {gain} yards"
                else:
                    if rng.random() < 0.62 + 0.05 * edge:
                        gain = int(rng.normal(11 + 3 * edge, 7))
                        tp = 24
                        text = (f"({clock // 60:02d}:{clock % 60:02d}) Shotgun #{qb[3]} {qb[1][0]}.{qb[1].split()[1]} pass complete short right "
                                f"to #{wr[3]} {wr[1][0]}.{wr[1].split()[1]} caught at X, for {gain} yards")
                    else:
                        gain, tp = 0, 3
                        text = (f"({clock // 60:02d}:{clock % 60:02d}) Shotgun #{qb[3]} {qb[1][0]}.{qb[1].split()[1]} pass incomplete short right "
                                f"to #{wr[3]} {wr[1][0]}.{wr[1].split()[1]}")
                gain = min(gain, yte)
                scoring = 0
                end = yte - gain
                if end <= 0:
                    tp = 68 if tp == 5 else 67
                    scoring = 1
                    text += " TOUCHDOWN"
                rows.append([seq, 0, period, clock, off, de, tp, down, dist, yte, gain, None, None, max(end, 0), scoring,
                             score[h], score[a], 0, 0, None, text])
                if scoring:
                    score[off] += 7
                    break
                yte = end
                if gain >= dist:
                    down, dist = 1, min(10, yte)
                else:
                    down, dist = down + 1, dist - gain
                if down == 4:
                    seq += 1
                    if yte <= 35:
                        good = rng.random() < 0.8
                        rows.append([seq, 0, period, clock, off, de, 59 if good else 60, 4, dist, yte, 0, None, None, yte,
                                     int(good), score[h], score[a], 0, 0, None, "field goal attempt GOOD" if good else "field goal attempt NO GOOD"])
                        if good:
                            score[off] += 3
                    else:
                        rows.append([seq, 0, period, clock, off, de, 52, 4, dist, yte, 0, None, None, yte, 0, score[h], score[a],
                                     0, 0, None, "punt 40 yards"])
                    break
                if clock <= 60:
                    break
            off = de
    return rows, score[h], score[a]


def _box(rng, t, roster, pts):
    qb, rb, wr, te, lb, k = roster[t]
    return {"team": {"first_downs": 20, "total_yards": int(300 + 3 * pts), "pass_yards": 200, "rush_yards": 120, "rush_att": 35,
                     "pass_att": 30, "pass_cmp": 19, "turnovers": int(rng.integers(0, 3)), "fumbles_lost": 0, "ints_thrown": 0,
                     "penalties": 5, "penalty_yards": 40, "third_conv": 5, "third_att": 12, "fourth_conv": 1, "fourth_att": 2,
                     "possession_s": 1800},
            "players": {
                "passing": {"cols": ["cmp", "att", "passing_yards", "yards_per_pass_attempt", "passing_touchdowns", "interceptions", "adj_qbr"],
                            "rows": [[qb[0], 19, 30, int(150 + 4 * pts), 7.0, pts // 14, int(rng.integers(0, 2)), 60.0]]},
                "rushing": {"cols": ["rushing_attempts", "rushing_yards", "yards_per_rush_attempt", "rushing_touchdowns", "long_rushing"],
                            "rows": [[rb[0], 20, int(60 + 2 * pts), 4.5, pts // 21, 20]]},
                "receiving": {"cols": ["receptions", "receiving_yards", "yards_per_reception", "receiving_touchdowns", "long_reception"],
                              "rows": [[wr[0], 7, int(80 + 2 * pts), 12.0, pts // 21, 30], [te[0], 3, 30, 10.0, 0, 15]]},
                "fumbles": {"cols": ["fumbles", "fumbles_lost", "fumbles_recovered"], "rows": []},
                "defensive": {"cols": ["total_tackles", "solo_tackles", "sacks", "tackles_for_loss", "passes_defended", "hurries", "defensive_touchdowns"],
                              "rows": [[lb[0], 8, 5, float(rng.integers(0, 2)), 1.0, 1, 0, 0]]},
                "interceptions": {"cols": ["interceptions", "interception_yards", "interception_touchdowns"], "rows": []},
                "kicking": {"cols": ["fgm", "fga", "field_goal_pct", "long_field_goal_made", "xpm", "xpa", "total_kicking_points"],
                            "rows": [[k[0], 1, 1, 100, 40, pts // 7, pts // 7, 3 + pts // 7]]},
                "punting": {"cols": ["punts", "punt_yards", "gross_avg_punt_yards", "touchbacks", "punts_inside20", "long_punt"], "rows": []}}}
