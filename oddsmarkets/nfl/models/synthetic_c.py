"""
Synthetic NFL seasons with planted truth, for builder C's tests and for running the models before real data exists.

`league(seasons, seed)` returns {"truth": {season: {team: {...}}}, "units": DataFrame (the _cdata unit table),
"games": DataFrame (the _cdata games frame), "stores": {season: store.json-shaped dict}}.

Truth per team and season: pass_team, qb (id) with qb_val, pass_def, rush_off, rush_def, st (points per game), all in
EPA per play (positive offence = better, positive defence = more EPA allowed = worse). Ratings persist across seasons
with carry-over 0.6 plus fresh noise. Each game: dropbacks ~ Poisson(35), designed runs ~ Poisson(26); a unit's
game EPA/play = league mean + offence + defence + home edge + per-play noise / sqrt(n) (sd 1.5 pass, 1.1 rush); the
starter is replaced by the backup (qb_val - 0.15) in 8 % of games. Points = 21.5 + realised net EPA of the side + 0.6
home + N(0, 6.5), rounded at >= 0. Schedules: each team plays its division twice and 11 other teams once (a random
11-regular graph off the division), packed greedily into weeks one Sunday apart.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models._cdata import _DIVS, _finish

TEAMS = [t for v in _DIVS.values() for t in v]
DIV_OF = {t: d for d, v in _DIVS.items() for t in v}
NP, NR = 35.0, 26.0
HFA_PASS, HFA_RUSH = 0.03, 0.02


def _cross_pairs(rng: np.random.Generator, k: int = 11, tries: int = 2000) -> list[tuple[str, str]]:
    """A random k-regular simple graph on the 32 teams avoiding division pairs (configuration model with retries)."""
    for _ in range(tries):
        stubs = np.repeat(np.arange(32), k)
        rng.shuffle(stubs)
        pairs = set()
        ok = True
        left = list(stubs)
        while left:
            a = left.pop()
            for j in range(len(left)):
                b = left[j]
                ta, tb = TEAMS[a], TEAMS[b]
                if a != b and DIV_OF[ta] != DIV_OF[tb] and (min(a, b), max(a, b)) not in pairs:
                    pairs.add((min(a, b), max(a, b)))
                    left.pop(j)
                    break
            else:
                ok = False
                break
        if ok:
            return [(TEAMS[a], TEAMS[b]) for a, b in pairs]
    raise RuntimeError("could not build a schedule")


def schedule(season: int, rng: np.random.Generator) -> list[dict]:
    games = []
    for d, mem in _DIVS.items():
        for i in range(4):
            for j in range(i + 1, 4):
                games.append((mem[i], mem[j]))
                games.append((mem[j], mem[i]))
    for a, b in _cross_pairs(rng):
        games.append((a, b) if rng.random() < 0.5 else (b, a))
    order = rng.permutation(len(games))
    busy: dict[int, set] = {}
    out = []
    for k in order:
        h, a = games[k]
        w = 1
        while h in busy.get(w, set()) or a in busy.get(w, set()) or len(busy.get(w, set())) >= 30:
            w += 1
        busy.setdefault(w, set()).update((h, a))
        out.append({"home": h, "away": a, "week": w})
    base = pd.Timestamp(f"{season}-09-08")
    for g in out:
        g["date"] = base + pd.Timedelta(days=7 * (g["week"] - 1))
    out.sort(key=lambda g: (g["week"], g["home"]))
    return out


def league(seasons=(2020, 2021), seed: int = 7, sd_unit: float = 0.08, played_through_week: int | None = None) -> dict:
    rng = np.random.default_rng(seed)
    truth: dict[int, dict] = {}
    unit_rows, game_rows, stores = [], [], {}
    prev = None
    qb_counter = 0
    for s in seasons:
        T = {}
        for t in TEAMS:
            p = (prev or {}).get(t)
            def draw(key, sd):
                base = 0.6 * p[key] if p else 0.0
                return base + rng.normal(0, sd * (0.8 if p else 1.0))
            if p and rng.random() > 0.15:
                qb, qv = p["qb"], 0.8 * p["qb_val"] + rng.normal(0, 0.03)
            else:
                qb_counter += 1
                qb, qv = f"QB{qb_counter:04d}", rng.normal(0, 0.09)
            qb_counter += 1
            T[t] = {"pass_team": draw("pass_team", sd_unit * 0.6), "qb": qb, "qb_val": qv,
                    "backup": f"QB{qb_counter:04d}", "pass_def": draw("pass_def", sd_unit),
                    "rush_off": draw("rush_off", sd_unit * 0.7), "rush_def": draw("rush_def", sd_unit * 0.6),
                    "st": draw("st", 0.8)}
        truth[s] = T
        prev = T
        sched = schedule(s, rng)
        sg = {}
        for k, g in enumerate(sched):
            h, a, w = g["home"], g["away"], g["week"]
            gid = f"{s}_{w:02d}_{a}_{h}"
            played = played_through_week is None or w <= played_through_week or s != seasons[-1]
            net = {}
            qbs = {}
            for off, de, hm in ((h, a, 1.0), (a, h, 0.0)):
                to, td = T[off], T[de]
                backup = rng.random() < 0.08
                qb = to["backup"] if backup else to["qb"]
                qv = to["qb_val"] - 0.15 if backup else to["qb_val"]
                qbs[off] = qb
                n_p = int(rng.poisson(NP))
                n_r = int(rng.poisson(NR))
                hp = HFA_PASS * (hm - 0.5)
                hr = HFA_RUSH * (hm - 0.5)
                mp = 0.05 + to["pass_team"] + qv + td["pass_def"] + hp
                mr = -0.08 + to["rush_off"] + td["rush_def"] + hr
                ep = mp + rng.normal(0, 1.5 / np.sqrt(max(n_p, 1)))
                er = mr + rng.normal(0, 1.1 / np.sqrt(max(n_r, 1)))
                st = (to["st"] - td["st"]) + rng.normal(0, 2.0)
                net[off] = n_p * (ep - 0.05) + n_r * (er + 0.08) + st / 2.0
                if played:
                    unit_rows.append({"game_id": gid, "season": s, "week": w, "gtype": "REG", "date": g["date"],
                                      "off": off, "def": de, "home": hm, "qb": qb, "pass_n": float(n_p),
                                      "pass_epa": float(ep * n_p), "pass_sr": float(n_p * (0.45 + ep / 4)),
                                      "rush_n": float(n_r), "rush_epa": float(er * n_r),
                                      "rush_sr": float(n_r * (0.4 + er / 4)), "st_epa": float(st)})
            # each side's realised net EPA edge decides the score
            ph = max(0, int(round(21.5 + (net[h] - net[a]) / 2 + 0.6 + rng.normal(0, 6.5))))
            pa = max(0, int(round(21.5 + (net[a] - net[h]) / 2 - 0.6 + rng.normal(0, 6.5))))
            row = {"game_id": gid, "season": s, "week": w, "gtype": "REG", "date": g["date"].strftime("%Y-%m-%d"),
                   "kickoff": g["date"].strftime("%Y-%m-%dT17:00:00Z"), "home": h, "away": a,
                   "hs": ph if played else None, "as": pa if played else None,
                   "status": "final" if played else "scheduled", "stadium": f"{h} Stadium", "roof": "outdoors",
                   "surface": "grass", "temp": 60, "wind": 5, "home_qb": qbs[h], "away_qb": qbs[a],
                   "home_coach": f"Coach {h}", "away_coach": f"Coach {a}",
                   "lines": {}, "overtime": 0, "div_game": int(DIV_OF[h] == DIV_OF[a])}
            sg[gid] = row
        stores[s] = {"season": s, "updated_at": f"{s}-12-31T00:00:00Z",
                     "teams": {t: {"abbr": t, "name": t, "conference": DIV_OF[t][:3], "division": DIV_OF[t]} for t in TEAMS},
                     "games": sg, "meta": {"synthetic": True}}
    from oddsmarkets.nfl.models._cdata import games_from_store
    games = pd.concat([games_from_store(st, s) for s, st in stores.items()], ignore_index=True)
    units = pd.DataFrame(unit_rows)
    if not units.empty:
        units["date"] = pd.to_datetime(units["date"])
    return {"truth": truth, "units": units, "games": games, "stores": stores}


def drives(n: int = 20000, seed: int = 3, rates: dict | None = None) -> pd.DataFrame:
    """Drive rows with planted outcome rates (independent of field position)."""
    rng = np.random.default_rng(seed)
    rates = rates or {"TD": 0.22, "FG": 0.14, "PUNT": 0.40, "TO": 0.12, "DOWNS": 0.04, "MISS": 0.03, "HALF": 0.04,
                      "SAFETY": 0.005, "OPPTD": 0.005}
    keys = list(rates)
    p = np.array([rates[k] for k in keys], float)
    p /= p.sum()
    res = rng.choice(len(keys), size=n, p=p)
    start = np.clip(rng.normal(70, 12, n), 1, 99).round()
    return pd.DataFrame({"game_id": "syn", "season": 2020, "off": "AAA", "def": "BBB", "start": start,
                         "result": [keys[i] for i in res], "plays": 6, "qtr": 1})


__all__ = ["league", "drives", "schedule", "TEAMS", "DIV_OF", "_finish"]
