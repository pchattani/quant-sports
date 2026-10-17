"""
Synthetic season stores in the contract's store.json GAME shape, with planted truth.

Used by the tests (and handy for front-end work before real stores exist). A team has a
planted offence `off`, defence `def` (points allowed above average per 100; lower = better)
and pace deviation. Each game draws

    poss  = league_pace + pace_h + pace_a + N(0, 3)
    pts_h = (L + off_h + def_a + hca/2 + b2b_h + alt) * poss / 100 + N(0, sd_pts)
    pts_a = (L + off_a + def_h - hca/2 + b2b_a)       * poss / 100 + N(0, sd_pts)

(hca per 100 on the margin; b2b in points per game for a team on the second night of a
back-to-back), resolves a level score with overtime, and writes team box totals whose
possession estimate FGA - OREB + TOV + 0.44 FTA reproduces `poss`.

NBA schedules follow the real 82-game shape (4 games against each division rival, 3 or 4
against the other ten conference teams, 2 against each team in the other conference);
other leagues use repeated round robins.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np

from oddsmarkets.basketball.models.config import NBA_DIVISIONS, WNBA_CONFERENCES


def _nba_schedule(teams: list[dict], rng) -> list[tuple[int, int]]:
    """List of (home, away) index pairs with the NBA 82-game shape."""
    pairs = []
    T = len(teams)
    for i in range(T):
        for j in range(i + 1, T):
            a, b = teams[i], teams[j]
            if a["conference"] != b["conference"]:
                n = 2
            elif a["division"] == b["division"]:
                n = 4
            else:
                n = 3 if (b["slot"] - a["slot"]) % 5 in (1, 4) else 4
            for k in range(n):
                pairs.append((i, j) if k % 2 == 0 else (j, i))
    return pairs


def _rr_schedule(T: int, games: int, rng) -> list[tuple[int, int]]:
    teams = list(range(T)) + ([None] if T % 2 else [])
    n = len(teams)
    count = np.zeros(T, int)
    pairs = []
    flip = 0
    while count.min() < games:
        arr = teams[:]
        for _ in range(n - 1):
            for k in range(n // 2):
                a, b = arr[k], arr[n - 1 - k]
                if a is None or b is None or count[a] >= games or count[b] >= games:
                    continue
                pairs.append((a, b) if flip % 2 == 0 else (b, a))
                count[a] += 1
                count[b] += 1
            arr = [arr[0]] + [arr[-1]] + arr[1:-1]
        flip += 1
        if flip > 20:
            break
    return pairs


def _dates(pairs, T, start: date, days: int, rng) -> list[date]:
    busy: dict[int, set] = {i: set() for i in range(T)}
    out = []
    order = rng.permutation(len(pairs))
    when = [None] * len(pairs)
    for k in order:
        h, a = pairs[k]
        d0 = int(rng.integers(0, days))
        for off in range(days * 2):
            d = (d0 + off) % days
            if d not in busy[h] and d not in busy[a]:
                busy[h].add(d)
                busy[a].add(d)
                when[k] = d
                break
        else:
            when[k] = d0
    for k in range(len(pairs)):
        out.append(start + timedelta(days=int(when[k])))
    return out


def make_store(league: str = "nba", season: int = 2027, seed: int = 0, played_frac: float = 1.0,
               net_sd: float | None = None, hca: float = 3.0, b2b: float = -2.0, altitude: float = 0.0,
               sd_pts: float | None = None, n_teams: int | None = None, games: int | None = None,
               start: date | None = None, odds_noise: float = 1.0, truth_override: dict | None = None) -> tuple[dict, dict]:
    """
    (store, truth). `played_frac` of the schedule (by date) is final; the rest is status "pre".
    truth = {"teams": {tid: {"off","def","net","pace"}}, "hca", "b2b", "league_ortg", "league_pace", "sd_pts"}.
    """
    rng = np.random.default_rng(seed)
    lg = "wnba" if str(league).lower() == "wnba" else "nba"
    L, P = (104.0, 80.0) if lg == "wnba" else (114.0, 99.0)
    sd_pts = sd_pts if sd_pts is not None else (7.0 if lg == "wnba" else 8.0)
    net_sd = net_sd if net_sd is not None else (6.0 if lg == "wnba" else 5.0)
    table = WNBA_CONFERENCES if lg == "wnba" else NBA_DIVISIONS
    teams = []
    for conf, divs in table.items():
        for div, abbrs in divs.items():
            for slot, ab in enumerate(abbrs):
                teams.append({"abbr": ab, "conference": conf, "division": div, "slot": slot})
    if n_teams:
        teams = teams[:n_teams]
    T = len(teams)
    ids = [str(100 + i) for i in range(T)]
    netv = rng.normal(0, net_sd, T)
    netv -= netv.mean()
    split = rng.uniform(0.3, 0.7, T)
    off = netv * split
    dfn = -(netv - off)
    pace = rng.normal(0, 2.0, T)
    pace -= pace.mean()
    truth = {"teams": {ids[i]: {"off": L + off[i], "def": L + dfn[i], "net": float(netv[i]), "pace": P + pace[i]} for i in range(T)},
             "hca": hca, "b2b": b2b, "altitude": altitude, "league_ortg": L, "league_pace": P, "sd_pts": sd_pts}
    if truth_override:
        for t, v in truth_override.get("teams", {}).items():
            truth["teams"][t].update(v)
        off = np.array([truth["teams"][t]["off"] - L for t in ids])
        dfn = np.array([truth["teams"][t]["def"] - L for t in ids])
    if lg == "nba" and T == 30 and not games:
        pairs = _nba_schedule(teams, rng)
        days = 170
    else:
        pairs = _rr_schedule(T, games or (44 if lg == "wnba" else 82), rng)
        days = 120 if lg == "wnba" else 170
    start = start or (date(season - 1, 10, 21) if lg == "nba" else date(season, 5, 16))
    dts = _dates(pairs, T, start, days, rng)
    order = sorted(range(len(pairs)), key=lambda k: (dts[k], k))
    cut = start + timedelta(days=int(round(days * played_frac)))
    last_day = {i: None for i in range(T)}
    store_games = {}
    alt_idx = {i for i, t in enumerate(teams) if t["abbr"] in ("DEN", "UTAH")}
    for n_, k in enumerate(order):
        h, a = pairs[k]
        d = dts[k]
        gid = f"9{season}{n_:05d}"
        b2b_h = b2b if last_day[h] is not None and (d - last_day[h]).days == 1 else 0.0
        b2b_a = b2b if last_day[a] is not None and (d - last_day[a]).days == 1 else 0.0
        last_day[h], last_day[a] = d, d
        tip = datetime(d.year, d.month, d.day, 23, 30, tzinfo=timezone.utc)
        g = {"id": gid, "date": tip.strftime("%Y-%m-%dT%H:%MZ"), "status": "pre", "stype": "reg", "neutral": False,
             "home": ids[h], "away": ids[a], "hs": None, "as": None, "periods": 4, "line": {"home": [], "away": []},
             "box": {}, "odds": None, "injuries": {}, "venue": None, "attendance": None, "series": None, "has_pbp": False}
        poss = P + pace[h] + pace[a] + rng.normal(0, 3.0)
        alt = altitude if h in alt_idx else 0.0
        eh = (L + off[h] + dfn[a] + hca / 2) * poss / 100 + b2b_h + alt
        ea = (L + off[a] + dfn[h] - hca / 2) * poss / 100 + b2b_a
        mu = eh - ea
        g["odds"] = {"provider": "synthetic", "spread_home": float(np.round(2 * (-mu + rng.normal(0, odds_noise))) / 2),
                     "total": float(np.round(2 * (eh + ea)) / 2), "ml_home": None, "ml_away": None}
        if d < cut:
            ph = eh + rng.normal(0, sd_pts)
            pa = ea + rng.normal(0, sd_pts)
            hs, as_ = int(round(ph)), int(round(pa))
            periods = 4
            while hs == as_:
                periods += 1
                hs += int(rng.integers(5, 16))
                as_ += int(rng.integers(5, 16))
            g.update({"status": "post", "hs": hs, "as": as_, "periods": periods})
            box = {}
            for tid, pts in ((ids[h], hs), (ids[a], as_)):
                fta, tov, oreb = 22, 13, 10
                p_ot = poss * (1 + 0.125 * (periods - 4) * (48 / (40 if lg == "wnba" else 48)))
                fga = int(round(p_ot - tov + oreb - 0.44 * fta))
                box[tid] = {"players": [], "dnp": [], "team": {"fgm": int(fga * 0.47), "fga": fga, "tpm": 12, "tpa": 35,
                                                                 "ftm": 17, "fta": fta, "oreb": oreb, "dreb": 33, "ast": 25,
                                                                 "stl": 7, "blk": 5, "tov": tov, "team_tov": 0, "pf": 19,
                                                                 "pts_paint": 48, "pts_fastbreak": 14, "pts_off_tov": 16,
                                                                 "largest_lead": 10, "lead_changes": 5}}
            g["box"] = box
        store_games[gid] = g
    store = {"league": lg, "season": int(season), "updated_at": "2026-10-01T00:00:00Z",
             "teams": {ids[i]: {"name": f"Team {teams[i]['abbr']}", "abbr": teams[i]["abbr"], "location": teams[i]["abbr"],
                                "colour": "#336699", "alt_colour": "#ffffff", "conference": teams[i]["conference"],
                                "division": teams[i]["division"]} for i in range(T)},
             "players": {}, "games": store_games,
             "meta": {"fetched": {}, "complete_through": str(cut - timedelta(days=1))}}
    return store, truth
