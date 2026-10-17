"""
Synthetic MLB-shaped seasons for builder D's tests and dry runs (no network, no real data).

`make_world` plants every player's true PA outcome rates (a 9-vector over EVENTS), handedness, and a
team structure (two leagues x three divisions of `per_div` teams). `season_rows` plays games plate
appearance by plate appearance with the default base-out tables of game_sim and writes one Savant-shaped
row per PA (the PA's last pitch: the contract's column names), plus a store dict with games, results,
probables, lineups and closing moneylines (the true home-win probability from a quick simulation, plus
noise, de-vigged at 4.5 %). Truth goes back alongside for the tests.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import game_sim as G
from oddsmarkets.baseball.models._dio import E, EVENTS, NE

EV_NAME = {"K": "strikeout", "BB": "walk", "HBP": "hit_by_pitch", "1B": "single", "2B": "double", "3B": "triple",
           "HR": "home_run", "GO": "field_out", "AO": "field_out"}
XW = {"1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03, "GO": 0.05, "AO": 0.12}


def _talent(rng, base: np.ndarray, sd: np.ndarray) -> np.ndarray:
    v = base * np.exp(rng.normal(0, sd))
    return v / v.sum()


def make_world(n_leagues: int = 2, divisions: int = 3, per_div: int = 5, seed: int = 0, talent_sd: float = 1.0) -> dict:
    rng = np.random.default_rng(seed)
    base = G.LEAGUE_DEFAULT
    hsd = talent_sd * np.array([0.25, 0.30, 0.4, 0.10, 0.15, 0.4, 0.35, 0.08, 0.08])
    psd = talent_sd * np.array([0.22, 0.25, 0.4, 0.06, 0.08, 0.3, 0.20, 0.08, 0.08])
    teams, players = {}, {}
    pid = 600000
    tid = 100
    for lg in range(n_leagues):
        for dv in range(divisions):
            for k in range(per_div):
                tid += 1
                t = {"name": f"Team {tid}", "abbr": f"T{tid}", "short": f"T{tid}", "league": ["AL", "NL"][lg % 2],
                     "division": f"{['AL', 'NL'][lg % 2]} {['East', 'Central', 'West'][dv % 3]}", "venue": str(tid),
                     "hitters": [], "starters": [], "relievers": []}
                for i in range(10):
                    pid += 1
                    bats = rng.choice(["R", "L", "S"], p=[0.55, 0.35, 0.10])
                    players[str(pid)] = {"name": f"Hitter {pid}", "bats": str(bats), "throws": "R", "pos": "OF",
                                         "dob": f"{1990 + int(rng.integers(0, 12))}-0{1 + int(rng.integers(0, 9))}-15",
                                         "true": _talent(rng, base, hsd), "team": str(tid)}
                    t["hitters"].append(str(pid))
                for role, cnt in (("starters", 5), ("relievers", 7)):
                    for i in range(cnt):
                        pid += 1
                        th = rng.choice(["R", "L"], p=[0.72, 0.28])
                        players[str(pid)] = {"name": f"Pitcher {pid}", "bats": "R", "throws": str(th), "pos": "P",
                                             "dob": f"{1990 + int(rng.integers(0, 12))}-0{1 + int(rng.integers(0, 9))}-15",
                                             "true": _talent(rng, base, psd), "team": str(tid)}
                        t[role].append(str(pid))
                teams[str(tid)] = t
    return {"teams": teams, "players": players, "seed": seed}


def _pa_probs(world: dict, b: str, p: str, home_bat: bool, league: dict) -> np.ndarray:
    pb, pp = world["players"][b], world["players"][p]
    th = pp["throws"]
    bh = G._bat_hand(pb["bats"], th)
    lt = league[bh + th]
    # true rates are hand-neutral; platoon enters through the league table ratio
    rb = pb["true"] * lt / G.LEAGUE_DEFAULT
    rp = pp["true"]
    q = G.odds_ratio(rb, rp, G.LEAGUE_DEFAULT, G.HFA if home_bat else 1.0 / G.HFA)
    return q


def play_game(world: dict, home: str, away: str, rng, gpk: int, date: str, league: dict, trans, starters: dict,
              auto_runner: bool = True, gtype: str = "R") -> tuple[list[dict], dict]:
    """One game PA by PA. Returns (rows, game record)."""
    T = world["teams"]
    lineups = {t: T[t]["hitters"][:9] for t in (home, away)}
    sp = {t: starters[t] for t in (home, away)}
    pitcher = dict(sp)
    bf = {home: 0, away: 0}
    rel_i = {home: 0, away: 0}
    score = {home: 0, away: 0}
    bidx = {home: 0, away: 0}
    rows = []
    ab = 0
    inn = 1
    while True:
        for top in (True, False):
            bat, fld = (away, home) if top else (home, away)
            if not top and inn >= 9 and score[home] > score[away]:
                break
            outs, bases = 0, 0
            if auto_runner and inn >= 10:
                bases = 2
            on = [None, None, None]
            if bases & 2:
                on[1] = lineups[bat][(bidx[bat] - 1) % 9]
            while outs < 3:
                # pitching change: starter out after ~24 batters, relievers every ~5
                if pitcher[fld] == sp[fld] and bf[fld] >= 23 + int(rng.integers(0, 5)):
                    pitcher[fld] = T[fld]["relievers"][rel_i[fld] % 7]
                    rel_i[fld] += 1
                    bf[fld] = 0
                elif pitcher[fld] != sp[fld] and bf[fld] >= 5:
                    pitcher[fld] = T[fld]["relievers"][rel_i[fld] % 7]
                    rel_i[fld] += 1
                    bf[fld] = 0
                b = lineups[bat][bidx[bat] % 9]
                p = pitcher[fld]
                q = _pa_probs(world, b, p, not top, league)
                ev = int(rng.choice(NE, p=q))
                cum = trans.cum[ev, bases, outs]
                k = int(np.searchsorted(cum, rng.random()))
                k = min(k, cum.shape[0] - 1)
                nb, runs, dout = int(trans.nb[ev, bases, outs, k]), int(trans.runs[ev, bases, outs, k]), int(trans.douts[ev, bases, outs, k])
                walk_off = (not top) and inn >= 9 and score[home] + runs > score[away]
                if walk_off and EVENTS[ev] != "HR":
                    runs = score[away] + 1 - score[home]
                ab += 1
                e = EVENTS[ev]
                pb = world["players"][b]
                stand = G._bat_hand(pb["bats"], world["players"][p]["throws"])
                xw = np.nan
                if e in XW:
                    xw = float(np.clip(XW[e] * 0.55 + 0.45 * (np.dot(pb["true"][3:7], [0.88, 1.25, 1.58, 2.03]) /
                                                             max(pb["true"][3:].sum(), 1e-6) * 1.0) + rng.normal(0, 0.15), 0, 2.1))
                rows.append({
                    "game_pk": gpk, "game_date": date, "game_type": gtype, "at_bat_number": ab, "pitch_number": 1,
                    "pitcher": int(p), "batter": int(b), "stand": stand, "p_throws": world["players"][p]["throws"],
                    "home_team": T[home]["abbr"], "away_team": T[away]["abbr"], "inning": inn,
                    "inning_topbot": "Top" if top else "Bot", "outs_when_up": outs, "balls": 0, "strikes": 0,
                    "on_1b": float(on[0]) if on[0] else np.nan, "on_2b": float(on[1]) if on[1] else np.nan,
                    "on_3b": float(on[2]) if on[2] else np.nan, "events": EV_NAME[e],
                    "bb_type": "ground_ball" if e == "GO" else ("fly_ball" if e in ("AO", "HR", "2B", "3B") else
                                                               ("line_drive" if e == "1B" else None)),
                    "launch_speed": float(rng.normal(88, 10)) if e in XW else np.nan,
                    "launch_angle": (-5.0 if e == "GO" else 25.0) if e in XW else np.nan,
                    "estimated_woba_using_speedangle": xw,
                    "woba_value": {"BB": 0.69, "HBP": 0.72, "1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03}.get(e, 0.0),
                    "woba_denom": 1.0, "babip_value": 1.0 if e in ("1B", "2B", "3B") else 0.0, "iso_value": 0.0,
                    "bat_score": score[bat], "post_bat_score": score[bat] + runs, "fld_score": score[fld],
                    "bat_speed": float(rng.normal(71, 3)) if e != "BB" else np.nan,
                    "n_thruorder_pitcher": 1 + bf[fld] // 9, "pitcher_days_since_prev_game": np.nan, "umpire": None,
                    "delta_run_exp": 0.0, "release_speed": float(rng.normal(93, 2)), "description": "hit_into_play",
                    "type": "X", "hc_x": np.nan, "hc_y": np.nan, "pitch_type": "FF",
                })
                bf[fld] += 1
                bidx[bat] += 1
                score[bat] += runs
                outs += dout
                bases = nb
                ids = [None, None, None]
                for i in range(3):
                    if bases & (1 << i):
                        ids[i] = b if i == 0 else (on[i - 1] or b)
                on = ids
                if walk_off:
                    break
            if (not top) and inn >= 9 and score[home] > score[away]:
                break
            if top and inn >= 9 and score[home] > score[away]:
                break
        if inn >= 9 and score[home] != score[away]:
            break
        inn += 1
        if inn > 25:
            score[home] += 1
            break
    g = {"gpk": str(gpk), "date": date, "gtype": gtype, "series": None, "home": home, "away": away, "hs": score[home],
         "as": score[away], "status": "final", "venue": T[home]["venue"], "weather": {"temp": 72, "wind": "5 mph, L To R",
                                                                                      "cond": "Clear"},
         "umpire_hp": None, "probables": {"home": sp[home], "away": sp[away]}, "lineups": {home: lineups[home], away: lineups[away]},
         "innings": inn, "lines": None, "abs": None, "has_statcast": True}
    return rows, g


def schedule(world: dict, n_games: int, seed: int) -> list[tuple[str, str]]:
    rng = np.random.default_rng(seed)
    tids = list(world["teams"])
    out = []
    for _ in range(n_games):
        h, a = rng.choice(len(tids), 2, replace=False)
        out.append((tids[h], tids[a]))
    return out


def season_rows(world: dict, season: int, n_days: int = 60, seed: int = 0, lines: bool = True,
                start: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Every team plays once a day (random pairings) for `n_days` days."""
    rng = np.random.default_rng(seed + season)
    league = G.league_split()
    trans = G.default_transitions()
    T = world["teams"]
    tids = list(T)
    d0 = dt.date.fromisoformat(start or f"{season}-04-01")
    rows, games = [], {}
    rot = {t: 0 for t in tids}
    gpk = season * 100000
    for day in range(n_days):
        date = (d0 + dt.timedelta(days=day)).isoformat()
        perm = rng.permutation(tids)
        for i in range(0, len(perm) - 1, 2):
            h, a = str(perm[i]), str(perm[i + 1])
            gpk += 1
            starters = {t: T[t]["starters"][rot[t] % 5] for t in (h, a)}
            for t in (h, a):
                rot[t] += 1
            r, g = play_game(world, h, a, rng, gpk, date, league, trans, starters, auto_runner=season >= 2020)
            rows += r
            if lines:
                p = true_home_p(world, h, a, starters, n=600, seed=gpk)
                pn = float(np.clip(p + rng.normal(0, 0.02), 0.05, 0.95))
                vig = 1.045
                g["lines"] = {"close": {"ml": [_american(pn * vig), _american((1 - pn) * vig)]}, "ml": None}
                g["_true_p"] = p
            games[str(gpk)] = g
    df = pd.DataFrame(rows)
    store = {"level": "mlb", "season": season, "teams": {t: {k: v for k, v in T[t].items() if k not in ("hitters", "starters", "relievers")}
                                                         for t in tids},
             "players": {p: {k: v for k, v in x.items() if k not in ("true", "team")} for p, x in world["players"].items()},
             "games": games, "venues": {T[t]["venue"]: {"name": f"Park {t}", "roof": "open"} for t in tids}, "meta": {}}
    return df, store


def _american(p: float) -> int:
    p = min(max(p, 0.02), 0.98)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def true_side(world: dict, team: str, starter: str) -> dict:
    T = world["teams"][team]
    P = world["players"]
    lg = G.LEAGUE_DEFAULT
    league = G.league_split()

    def hitter(pid):
        x = P[pid]
        rates = {}
        for th in ("L", "R"):
            bh = G._bat_hand(x["bats"], th)
            rates[th] = x["true"] * league[bh + th] / lg
            rates[th] /= rates[th].sum()
        return {"pid": pid, "bats": x["bats"], "rates": rates}

    def pitcher(pid):
        x = P[pid]
        rates = {}
        for bh in ("L", "R"):
            rates[bh] = x["true"]
        return {"pid": pid, "throws": x["throws"], "rates": rates, "pc_mean": 95.0, "pc_sd": 10.0, "ppa": 1.0}

    rel = [P[r]["true"] for r in T["relievers"]]
    mix = np.mean(rel, axis=0)
    share_l = float(np.mean([P[r]["throws"] == "L" for r in T["relievers"]]))
    return {"lineup": [hitter(h) for h in T["hitters"][:9]], "starter": pitcher(starter),
            "bullpen": {"hi": {"rates": {"L": mix, "R": mix}, "share_L": share_l},
                        "mid": {"rates": {"L": mix, "R": mix}, "share_L": share_l}}}


def true_home_p(world: dict, home: str, away: str, starters: dict, n: int = 2000, seed: int = 0) -> float:
    spec = {"home": true_side(world, home, starters[home]), "away": true_side(world, away, starters[away]),
            "league": G.league_split(), "auto_runner": True}
    return G.simulate(spec, n=n, seed=seed)["p_home"]


def write_season(root, world: dict, season: int, **kw) -> tuple[pd.DataFrame, dict]:
    """Write <root>/statcast/mlb/<season>.parquet and return (rows, store)."""
    from pathlib import Path
    df, store = season_rows(world, season, **kw)
    p = Path(root) / "statcast" / "mlb" / f"{season}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df, store


def quick_store(season: int = 2027, seed: int = 0, games_per_pair: int = 6, played_frac: float = 1.0,
                rating_sd: float = 0.25, postseason: dict | None = None) -> tuple[dict, dict]:
    """
    A results-only store (no PA rows) for season-simulation tests: 30 teams in two leagues x three
    divisions, every pair in a league meeting `games_per_pair` times (home and away alternating), results
    drawn from planted logit ratings with home field 0.16. The first `played_frac` of the schedule (by date)
    is final, the rest scheduled. Returns (store, ratings).
    """
    rng = np.random.default_rng(seed)
    teams = {}
    r = {}
    tid = 100
    for lg in ("AL", "NL"):
        for dv in ("East", "Central", "West"):
            for k in range(5):
                tid += 1
                teams[str(tid)] = {"name": f"Team {tid}", "abbr": f"T{tid}", "short": f"T{tid}", "league": lg,
                                   "division": f"{lg} {dv}", "venue": str(tid)}
                r[str(tid)] = float(rng.normal(0, rating_sd))
    ids = list(teams)
    sched = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if teams[a]["league"] != teams[b]["league"]:
                continue
            for k in range(games_per_pair):
                h, w = (a, b) if k % 2 == 0 else (b, a)
                sched.append((h, w))
    rng.shuffle(sched)
    d0 = dt.date(season, 3, 28)
    games = {}
    n_play = int(round(len(sched) * played_frac))
    per_day = max(1, len(sched) // 180)
    for k, (h, a) in enumerate(sched):
        gpk = str(season * 1000000 + k)
        date = (d0 + dt.timedelta(days=k // per_day)).isoformat()
        g = {"gpk": gpk, "date": date, "gtype": "R", "series": None, "home": h, "away": a, "hs": None, "as": None,
             "status": "scheduled", "venue": teams[h]["venue"]}
        if k < n_play:
            p = 1 / (1 + np.exp(-(r[h] - r[a] + 0.16)))
            hw = rng.random() < p
            g.update({"hs": int(5 if hw else 3), "as": int(3 if hw else 5), "status": "final"})
        games[gpk] = g
    store = {"level": "mlb", "season": season, "teams": teams, "games": games, "players": {}, "venues": {}, "meta": {}}
    return store, r
