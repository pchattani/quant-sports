"""Synthetic Quant Rink inputs for builder D's tests: a season store and builder A-shaped derived events / stints.

`make_season(data, raw, season, n_teams=6, rounds=2, seed=0, today=None)` writes
  <data>/<season>/store.json              teams, games (final before `today`, scheduled after), players, standings None
  <raw>/derived/<season>/events.parquet   builder A's column names (event_id, period, sec, type, team, is_home, x, y, zone,
                                          shot_type, shooter, goalie, assist1, assist2, player1, player2, pen_min, sit,
                                          score_home, score_away, home_s1..6, home_g, away_s1..6, away_g)
  <raw>/derived/<season>/stints.parquet   game_id, period, start, end, dur, home_s1..6, home_g, away_s1..6, away_g
Each team: 12 forwards (4 lines), 6 defencemen (3 pairs), 2 goalies; 40-second stints; every 9th stint a power play.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TEAMS = ["BOS", "TOR", "MTL", "NYR", "EDM", "VAN"]
DIV = {"BOS": ("Eastern", "Atlantic"), "TOR": ("Eastern", "Atlantic"), "MTL": ("Eastern", "Atlantic"), "NYR": ("Eastern", "Metropolitan"),
       "EDM": ("Western", "Pacific"), "VAN": ("Western", "Pacific")}


def roster(i: int) -> dict:
    base = 8470000 + i * 100
    f = [base + k for k in range(12)]
    d = [base + 20 + k for k in range(6)]
    g = [base + 40, base + 41]
    return {"F": f, "D": d, "G": g}


def make_season(data: Path, raw: Path, season: int = 20252026, n_teams: int = 6, rounds: int = 2, seed: int = 0,
                today: date | None = None, start: date | None = None) -> dict:
    rng = np.random.default_rng(seed)
    teams = TEAMS[:n_teams]
    rosters = {t: roster(i) for i, t in enumerate(teams)}
    y = season // 10000
    d0 = start or date(y, 10, 8)
    today = today or date(y + 1, 6, 30)
    games = {}
    ev_rows, st_rows = [], []
    n = 0
    talent = {t: rng.normal(0, 0.25) for t in teams}
    for r in range(rounds):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j or (r % 2 == 0 and i > j) or (r % 2 == 1 and i < j):
                    continue
                n += 1
                gid = int(f"{y}02{n:04d}")
                gd = d0 + timedelta(days=n)
                final = gd < today
                g = {"game_id": gid, "season": season, "date": gd.isoformat(), "start": f"{gd.isoformat()}T23:00:00Z", "type": 2,
                     "home": h, "away": a, "hs": None, "as": None, "status": "final" if final else "scheduled", "period": None,
                     "ot": None, "so": None, "venue": f"{h} Arena", "lines": {"src": "synthetic", "ml": [-130, 110],
                                                                              "puck_line": {"home": -1.5, "price": [160, -190]},
                                                                              "total": {"line": 6.0, "over": -110, "under": -110},
                                                                              "open": None, "close": None, "books": []},
                     "goalies": {"home": {"starter": rosters[h]["G"][n % 2], "used": [], "decision": None},
                                 "away": {"starter": rosters[a]["G"][n % 2], "used": [], "decision": None}}, "attendance": 18000}
                if final:
                    hs, as_ = _game(rng, gid, h, a, rosters, talent, ev_rows, st_rows, g)
                    if hs == as_:
                        if rng.random() < 0.5:
                            hs += 1
                        else:
                            as_ += 1
                        g["ot"] = True
                        g["so"] = False
                    else:
                        g["ot"] = g["so"] = False
                    g.update(hs=hs, **{"as": as_}, period=3 if not g["ot"] else 4)
                games[str(gid)] = g
    players = {}
    for t in teams:
        for k, p in enumerate(rosters[t]["F"]):
            players[str(p)] = {"name": f"{t} Forward {k + 1}", "first": t, "last": f"F{k + 1}", "pos": "CLR"[k % 3], "shoots": "L",
                               "dob": f"{1995 + k % 8}-03-0{1 + k % 9}", "team": t, "number": k + 10}
        for k, p in enumerate(rosters[t]["D"]):
            players[str(p)] = {"name": f"{t} Defence {k + 1}", "pos": "D", "shoots": "R", "dob": "1996-05-05", "team": t}
        for k, p in enumerate(rosters[t]["G"]):
            players[str(p)] = {"name": f"{t} Goalie {k + 1}", "pos": "G", "shoots": "L", "dob": "1994-01-01", "team": t}
    store = {"season": season, "updated_at": "2026-10-01T00:00:00Z",
             "teams": {t: {"abbr": t, "name": f"{t} Club", "conference": DIV[t][0], "division": DIV[t][1], "colour": "#123456"} for t in teams},
             "games": games, "standings": None, "players": players, "meta": {}}
    sd = Path(data) / str(season)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "store.json").write_text(json.dumps(store), encoding="utf-8")
    dd = Path(raw) / "derived" / str(season)
    dd.mkdir(parents=True, exist_ok=True)
    ev = pd.DataFrame(ev_rows)
    stn = pd.DataFrame(st_rows)
    for c in [f"home_s{i}" for i in range(1, 7)] + [f"away_s{i}" for i in range(1, 7)] + ["home_g", "away_g", "shooter", "goalie",
                                                                                          "assist1", "assist2", "player1", "player2"]:
        if c in ev:
            ev[c] = pd.array(ev[c].tolist(), dtype="Int64")
        if c in stn:
            stn[c] = pd.array(stn[c].tolist(), dtype="Int64")
    ev.to_parquet(dd / "events.parquet", index=False)
    stn.to_parquet(dd / "stints.parquet", index=False)
    return store


def _game(rng, gid, h, a, rosters, talent, ev_rows, st_rows, g) -> tuple[int, int]:
    score = {h: 0, a: 0}
    eid = 0
    gh = g["goalies"]["home"]["starter"]
    ga = g["goalies"]["away"]["starter"]
    k = 0
    for period in (1, 2, 3):
        t = 0
        while t < 1200:
            dur = min(40, 1200 - t)
            fl = k % 4
            dp = k % 3
            pp_side = None
            if k % 9 == 8:
                pp_side = "home" if rng.random() < 0.5 else "away"
            hs_ = rosters[h]["F"][fl * 3:fl * 3 + 3] + rosters[h]["D"][dp * 2:dp * 2 + 2]
            as_ = rosters[a]["F"][fl * 3:fl * 3 + 3] + rosters[a]["D"][dp * 2:dp * 2 + 2]
            if pp_side == "home":
                as_ = as_[:4]
            elif pp_side == "away":
                hs_ = hs_[:4]
            sec0 = (period - 1) * 1200 + t
            st = {"game_id": gid, "period": period, "start": sec0, "end": sec0 + dur, "dur": dur, "home_g": gh, "away_g": ga}
            for i in range(6):
                st[f"home_s{i + 1}"] = hs_[i] if i < len(hs_) else None
                st[f"away_s{i + 1}"] = as_[i] if i < len(as_) else None
            st_rows.append(st)
            sit_h, sit_a = len(hs_), len(as_)
            sit = f"1{sit_a}{sit_h}1"
            # faceoff at the stint start
            win_home = rng.random() < 0.5
            zone = rng.choice(["O", "D", "N"])
            eid += 1
            ev_rows.append(_ev(gid, eid, period, sec0, "faceoff", h if win_home else a, win_home, 0.0 if zone == "N" else (69.0 if zone == "O" else -69.0),
                               22.0, zone, None, None, None, None, hs_[0] if win_home else as_[0], as_[0] if win_home else hs_[0], sit,
                               score[h], score[a], hs_, as_, gh, ga))
            for side, team, opp, mine, theirs, gopp in (("home", h, a, hs_, as_, ga), ("away", a, h, as_, hs_, gh)):
                lam = 1.0 * np.exp(talent[team] - talent[opp]) * (1.6 if len(mine) > len(theirs) else (0.5 if len(mine) < len(theirs) else 1.0))
                for _ in range(rng.poisson(lam)):
                    tt = sec0 + int(rng.integers(1, max(2, dur)))
                    x = float(rng.uniform(30, 88))
                    yy = float(rng.uniform(-30, 30))
                    dist = np.hypot(89 - x, yy)
                    p_goal = 1 / (1 + np.exp(-(-1.2 - 0.06 * dist)))
                    u = rng.random()
                    shooter = mine[int(rng.integers(0, len(mine)))]
                    eid += 1
                    if u < 0.25:
                        ev_rows.append(_ev(gid, eid, period, tt, "blocked-shot", team, side == "home", x, yy, "O", "wrist", shooter, None,
                                           None, shooter, theirs[int(rng.integers(0, len(theirs)))], sit, score[h], score[a], hs_, as_, gh, ga))
                    elif u < 0.45:
                        ev_rows.append(_ev(gid, eid, period, tt, "missed-shot", team, side == "home", x, yy, "O", "slap", shooter, gopp,
                                           None, shooter, None, sit, score[h], score[a], hs_, as_, gh, ga))
                    elif rng.random() < p_goal * 1.4:
                        others = [p for p in mine if p != shooter]
                        a1 = others[0] if others else None
                        a2 = others[1] if len(others) > 1 else None
                        ev_rows.append(_ev(gid, eid, period, tt, "goal", team, side == "home", x, yy, "O", str(rng.choice(["wrist", "snap", "slap", "backhand"])), shooter, gopp,
                                           a1, shooter, None, sit, score[h], score[a], hs_, as_, gh, ga, assist2=a2))
                        score[team] += 1
                    else:
                        ev_rows.append(_ev(gid, eid, period, tt, "shot-on-goal", team, side == "home", x, yy, "O", str(rng.choice(["wrist", "snap", "slap", "backhand"])), shooter, gopp,
                                           None, shooter, None, sit, score[h], score[a], hs_, as_, gh, ga))
                if rng.random() < 0.4:
                    eid += 1
                    ev_rows.append(_ev(gid, eid, period, sec0 + 5, "hit", team, side == "home", 10.0, 40.0, "N", None, None, None, None,
                                       mine[0], theirs[0], sit, score[h], score[a], hs_, as_, gh, ga))
                if rng.random() < 0.2:
                    eid += 1
                    ev_rows.append(_ev(gid, eid, period, sec0 + 7, "giveaway", team, side == "home", -40.0, 0.0, "D", None, None, None, None,
                                       mine[1], None, sit, score[h], score[a], hs_, as_, gh, ga))
            if pp_side:
                pen_team = a if pp_side == "home" else h
                pen_by = (as_ if pp_side == "home" else hs_)[0]
                drawn = (hs_ if pp_side == "home" else as_)[0]
                eid += 1
                ev_rows.append(_ev(gid, eid, period, sec0, "penalty", pen_team, pen_team == h, 0.0, 0.0, "N", None, None, None, None,
                                   pen_by, drawn, f"1551", score[h], score[a], hs_, as_, gh, ga, pen_min=2))
            t += dur
            k += 1
    return score[h], score[a]


def _ev(gid, eid, period, sec, typ, team, is_home, x, y, zone, shot_type, shooter, goalie, a1, p1, p2, sit, sh, sa, hs_, as_, gh, ga,
        assist2=None, pen_min=None) -> dict:
    r = {"game_id": gid, "season": int(str(gid)[:4]) * 10001 + 1, "event_id": eid, "sort": eid, "period": period, "sec": float(sec),
         "type": typ, "team": team, "is_home": bool(is_home), "x": x, "y": y, "zone": zone, "shot_type": shot_type, "shooter": shooter,
         "goalie": goalie, "assist1": a1, "assist2": assist2, "player1": p1, "player2": p2, "pen_min": pen_min, "sit": sit,
         "score_home": sh, "score_away": sa, "home_g": gh, "away_g": ga}
    for i in range(6):
        r[f"home_s{i + 1}"] = hs_[i] if i < len(hs_) else None
        r[f"away_s{i + 1}"] = as_[i] if i < len(as_) else None
    return r
