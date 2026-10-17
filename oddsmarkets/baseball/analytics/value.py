"""
Player value, the best at each position, and every club's strengths and needs (MLB, Triple-A and NPB).
docs/VALUE_SECTIONS.md sections 1-2; the trade simulator's payloads are analytics/trade.py.

The currency is WAR: Bullpen WAR for MLB and Triple-A (models/war.py: batting from regressed xwOBA+, baserunning,
catch-probability fielding, framing, positional adjustment, replacement; pitchers RA9-based, relievers by leverage),
WAR-lite for NPB (npb/models.season_war: batting, base stealing, positional adjustment, replacement; FIP-based
pitching; no fielding). Nothing here re-estimates a player's value: it allocates, ranks, projects and compares.

Positions. MLB and Triple-A: games at each position from the pitch table's fielder_2..9 at every plate appearance
(the share of the team's defensive plate appearances a player was at the position, as models/war.defensive_games;
a game batted without fielding is a DH game), cached per season. NPB: box-score starts by position (2005 on). A
player's WAR is split across the positions he played in proportion to his games there. Pitchers are SP or RP by
role; a swingman's WAR is split by an estimate of his batters faced as a starter (22 a start) and in relief (4.3 a
game) for MLB, by role for NPB (the stat pages carry no starts).

Rates: WAR per 600 plate appearances for hitters, per 700 batters faced for pitchers (about a starter's season).

Projection (next season, `fit_projection`): a Marcel-style weighted rate of the last three seasons (hitters 5/4/3,
pitchers 3/2/1), regressed to the league's rate with k plate appearances or batters faced of league average, plus an
age adjustment (a quadratic in age fitted on consecutive seasons' rate changes, weighted by the harmonic mean of the
two samples; MLB ages, used for every level). k is chosen walk-forward (seasons before the target only); the
validation against "last season's rate" is in the payload's `projection` block.

Team strengths and needs (`team_needs`): every position's team value (WAR) graded against the level's other clubs
(percentile -> A >= 80, B >= 60, C >= 40, D >= 20, else F); the top three and bottom three; for each weakness the
best candidates on other clubs ranked by projected gain at the position over a full season (wins), with age and
feasibility hints only where the data support them (the other club missed the postseason or is out of contention;
it has another player at the position worth at least three quarters as much). No salaries, contracts or
availability: no legitimate free source exists for MLB or NPB salaries, and free agents are not identified by our
data, which the payload says.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from typing import Any

import numpy as np

from oddsmarkets.baseball import analytics as an

log = logging.getLogger(__name__)
VERSION = "value-2"
HIT_POS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH")
PIT_POS = ("SP", "RP")
POSITIONS = HIT_POS + PIT_POS
POS_ADJ = {"C": 12.5, "1B": -12.5, "2B": 2.5, "3B": 2.5, "SS": 7.5, "LF": -7.5, "CF": 2.5, "RF": -7.5, "DH": -17.5}
POS_NUM = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
RATE_PA = 600.0
RATE_BF = 700.0
GRADES = ((80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "F"))
LABEL = ("Model suggestions based on on-field value; not considering salary, contracts, fit or availability "
         "(no legitimate free source of MLB or NPB salaries exists, and our data do not identify free agents).")
SCHEDULE = {"mlb": 162, "aaa": 150, "npb": 143}
CURRENCY = {"mlb": "Bullpen WAR", "aaa": "Bullpen WAR", "npb": "WAR-lite"}


def grade(pct: float | None) -> str | None:
    if pct is None:
        return None
    for cut, g in GRADES:
        if pct >= cut:
            return g
    return "F"


def pct_rank(values: list[float], v: float, lower: bool = False) -> float | None:
    """Percentile (0-100) of v in values, ties at the midpoint."""
    if not values or v is None:
        return None
    a = sorted(values)
    lo = sum(1 for x in a if x < v)
    eq = sum(1 for x in a if x == v)
    p = 100.0 * (lo + eq / 2.0) / len(a)
    return 100.0 - p if lower else p


# ── player rows ─────────────────────────────────────────────────────────────

def _split_sp(g, gs) -> float:
    """Share of a pitcher's work as a starter, estimated from games and starts (22 BF a start, 4.3 a relief game)."""
    g, gs = g or 0, gs or 0
    if g <= 0:
        return 0.0
    a = 22.0 * gs
    b = 4.3 * max(g - gs, 0)
    return a / (a + b) if a + b > 0 else 0.0


def rows_mlb(hit: dict | None, pit: dict | None, posgames: dict[str, dict] | None) -> list[dict]:
    """Value rows from the season's catalogues (hitters.json, pitchers.json) and position games."""
    out = []
    posgames = posgames or {}
    for pid, r in ((hit or {}).get("players") or {}).items():
        v = r.get("values") or {}
        if v.get("war") is None:
            continue
        pa = r.get("pa") or v.get("pa") or 0
        pg = {k: float(x) for k, x in (posgames.get(pid) or {}).items() if x and k in HIT_POS}
        if not pg and r.get("pos") in HIT_POS:
            pg = {r["pos"]: float(v.get("g") or 1)}
        comps = [("Batting", v.get("batting_runs")), ("Baserunning", v.get("bsr")), ("Fielding", v.get("fielding_runs")),
                 ("Framing", v.get("framing_runs")), ("Positional", v.get("pos_runs")), ("Replacement", v.get("repl_runs"))]
        out.append({"pid": pid, "name": r.get("name"), "team": r.get("team"), "kind": "H", "pos": _primary(pg) or r.get("pos"),
                    "pos_g": pg, "g": v.get("g"), "n": pa, "war": v.get("war"), "rate": _rate(v.get("war"), pa, RATE_PA),
                    "pos_runs": v.get("pos_runs") or 0.0, "comps": [[k, an.rnd(x, 1)] for k, x in comps if x is not None],
                    "stat": {"wOBA": v.get("woba"), "xwOBA+": v.get("xwoba_plus"), "OPS": v.get("ops")}, "age": r.get("age")})
    for pid, r in ((pit or {}).get("players") or {}).items():
        v = r.get("values") or {}
        if v.get("war") is None:
            continue
        bf = r.get("bf") or v.get("bf") or 0
        sp = _split_sp(v.get("g"), v.get("gs"))
        role = "SP" if sp >= 0.5 else "RP"
        out.append({"pid": pid, "name": r.get("name"), "team": r.get("team"), "kind": "P", "pos": role,
                    "pos_g": {"SP": sp, "RP": 1 - sp} if v.get("g") else {role: 1.0}, "g": v.get("g"), "gs": v.get("gs"), "n": bf,
                    "ip": v.get("ip"), "war": v.get("war"), "rate": _rate(v.get("war"), bf, RATE_BF),
                    "comps": [["RA9", an.rnd(v.get("ra9"), 2)], ["FIP", an.rnd(v.get("fip"), 2)], ["xWAR", an.rnd(v.get("war_x"), 1)],
                              ["IP", an.rnd(v.get("ip"), 1)]],
                    "stat": {"RA9": v.get("ra9"), "FIP": v.get("fip"), "K%": v.get("k_pct")}, "age": r.get("age")})
    return out


def rows_npb(players: dict | None, positions: dict[str, dict] | None, ages: dict[str, float] | None = None) -> list[dict]:
    rpw = float(((players or {}).get("war_meta") or {}).get("rpw") or 8.3)
    """Value rows from npb/<S>/players.json (a traded player's clubs summed; his club is the one with more PA / BF)."""
    out = []
    positions = positions or {}
    ages = ages or {}
    if not players or not players.get("ok"):
        return out
    agg: dict[str, dict] = {}
    for r in players.get("bat") or []:
        if r.get("pitcher") or r.get("war") is None:
            continue
        a = agg.setdefault(r["pid"], {"pid": r["pid"], "name": r.get("name"), "team": r.get("team"), "_n": -1, "pa": 0, "g": 0, "war": 0.0,
                                      "bat_runs": 0.0, "br_runs": 0.0, "pos_runs": 0.0, "pos": r.get("pos"), "wrc_plus": r.get("wrc_plus"),
                                      "woba": r.get("woba"), "ops": r.get("ops")})
        for k in ("pa", "g", "war", "bat_runs", "br_runs", "pos_runs"):
            a[k] += r.get(k) or 0
        if (r.get("pa") or 0) > a["_n"]:
            a["_n"], a["team"] = r.get("pa") or 0, r.get("team")
    for pid, a in agg.items():
        pg = {k: float(x) for k, x in (positions.get(pid) or {}).items() if k in HIT_POS and x}
        if not pg and a.get("pos") in HIT_POS:
            pg = {a["pos"]: float(a["g"] or 1)}
        rep = a["war"] - (a["bat_runs"] + a["br_runs"] + a["pos_runs"]) / rpw
        comps = [["Batting", an.rnd(a["bat_runs"], 1)], ["Base stealing", an.rnd(a["br_runs"], 1)], ["Positional", an.rnd(a["pos_runs"], 1)],
                 ["Replacement (wins)", an.rnd(rep, 1)]]
        out.append({"pid": pid, "name": a["name"], "team": a["team"], "kind": "H", "pos": _primary(pg) or a.get("pos"), "pos_g": pg,
                    "g": a["g"], "n": a["pa"], "war": round(a["war"], 2), "rate": _rate(a["war"], a["pa"], RATE_PA), "pos_runs": a["pos_runs"],
                    "comps": comps, "stat": {"wRC+": a.get("wrc_plus"), "wOBA": a.get("woba"), "OPS": a.get("ops")}, "age": ages.get(pid)})
    aggp: dict[str, dict] = {}
    for r in players.get("pit") or []:
        if r.get("war") is None:
            continue
        a = aggp.setdefault(r["pid"], {"pid": r["pid"], "name": r.get("name"), "team": r.get("team"), "_n": -1, "bf": 0, "g": 0, "outs": 0,
                                       "war": 0.0, "role": r.get("role"), "fip": r.get("fip"), "era": r.get("era"), "fip_minus": r.get("fip_minus")})
        for k in ("bf", "g", "outs", "war"):
            a[k] += r.get(k) or 0
        if (r.get("bf") or 0) > a["_n"]:
            a["_n"], a["team"], a["role"] = r.get("bf") or 0, r.get("team"), r.get("role")
    for pid, a in aggp.items():
        role = "SP" if (a["g"] and a["outs"] / max(a["g"], 1) >= 12) else "RP"
        ip = a["outs"] / 3.0
        out.append({"pid": pid, "name": a["name"], "team": a["team"], "kind": "P", "pos": role, "pos_g": {role: 1.0}, "g": a["g"],
                    "n": a["bf"], "ip": round(ip, 1), "war": round(a["war"], 2), "rate": _rate(a["war"], a["bf"], RATE_BF),
                    "comps": [["FIP", an.rnd(a.get("fip"), 2)], ["FIP-", a.get("fip_minus")], ["ERA", an.rnd(a.get("era"), 2)], ["IP", round(ip, 1)]],
                    "stat": {"FIP": a.get("fip"), "ERA": a.get("era"), "FIP-": a.get("fip_minus")}, "age": ages.get(pid)})
    return out


def _rate(war, n, unit) -> float | None:
    if war is None or not n:
        return None
    return float(war) / float(n) * unit


def _primary(pg: dict) -> str | None:
    if not pg:
        return None
    return max(pg.items(), key=lambda kv: kv[1])[0]


def eligible(row: dict, min_share: float = 0.2, min_games: float = 15) -> list[str]:
    """Positions a player can be listed at: his primary, and any he played in at least min_games or min_share of his
    games (hitters); a pitcher's role, and the other role when at least min_share of his work."""
    pg = row.get("pos_g") or {}
    tot = sum(pg.values()) or 1.0
    if row["kind"] == "P":
        return sorted([p for p, x in pg.items() if x >= min_share or p == row.get("pos")], key=lambda p: -pg.get(p, 0))
    return sorted([p for p, x in pg.items() if p == row.get("pos") or x >= min_games or x / tot >= min_share], key=lambda p: -pg.get(p, 0))


# ── history and projections ─────────────────────────────────────────────────

def history_table(rows_by_season: dict[int, list[dict]]) -> dict[str, dict[int, dict]]:
    """{pid: {season: {"war", "n", "pos_runs", "kind", "age"}}} (hitters and pitchers apart: pid "H:" / "P:" keys)."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for s, rows in rows_by_season.items():
        for r in rows:
            out[r["kind"] + ":" + r["pid"]][s] = {"war": r.get("war"), "n": r.get("n") or 0, "pos_runs": r.get("pos_runs") or 0.0,
                                                  "age": r.get("age"), "role": r.get("pos")}
    return out


WEIGHTS = {"H": (5.0, 4.0, 3.0), "P": (3.0, 2.0, 1.0)}
K_GRID = {"H": (300.0, 600.0, 1000.0, 1500.0, 2500.0, 4000.0, 6000.0), "P": (300.0, 600.0, 1000.0, 1500.0, 2500.0, 4000.0, 6000.0)}
UNIT = {"H": RATE_PA, "P": RATE_BF}
MIN_TARGET_N = {"H": 200, "P": 150}


def _marcel(h: dict[int, dict], target: int, kind: str, k: float, m: float, hpt: float = 0.0) -> tuple[float | None, float]:
    """Weighted, regressed WAR rate per unit for `target` from the three seasons before it; (rate, weighted n).
    The target of the regression is the league rate m scaled by nw / (nw + hpt): a player with little playing time is
    pulled toward replacement level rather than toward the average regular (hpt = 0: plain Marcel)."""
    w = WEIGHTS[kind]
    num = den = 0.0
    for i, wt in enumerate(w):
        x = h.get(target - 1 - i)
        if not x or x.get("war") is None or not x.get("n"):
            continue
        num += wt * float(x["war"])
        den += wt * float(x["n"])
    if den <= 0:
        return None, 0.0
    u = UNIT[kind]
    mt = m * den / (den + hpt) if hpt > 0 else m
    return (num + k * mt / u) / (den + k) * u, den


def aging_curve(hist: dict[str, dict[int, dict]], kind: str) -> list[float]:
    """Quadratic in age of the change in WAR rate between consecutive seasons (weighted by the harmonic mean
    sample); [c0, c1, c2] for delta = c0 + c1 (age - 28) + c2 (age - 28)^2. Zeros without ages."""
    X, y, w = [], [], []
    for key, h in hist.items():
        if not key.startswith(kind + ":"):
            continue
        for s, x in h.items():
            z = h.get(s + 1)
            if not z or x.get("age") is None or (x.get("n") or 0) < 150 or (z.get("n") or 0) < 150:
                continue
            r1 = x["war"] / x["n"] * UNIT[kind]
            r2 = z["war"] / z["n"] * UNIT[kind]
            a = float(x["age"]) - 28.0
            X.append([1.0, a, a * a])
            y.append(r2 - r1)
            w.append(2 * x["n"] * z["n"] / (x["n"] + z["n"]))
    if len(y) < 100:
        return [0.0, 0.0, 0.0]
    X, y, w = np.array(X), np.array(y), np.array(w)
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    # the regression to the mean is already in the Marcel step: centre the curve so its weighted mean is the
    # observed mean change of players near 27-29 (the curve's job is the slope with age)
    return [float(c) for c in coef]


def age_delta(curve: list[float], age) -> float:
    if age is None or not curve:
        return 0.0
    a = min(max(float(age) - 28.0, -8.0), 12.0)
    return curve[0] + curve[1] * a + curve[2] * a * a - (curve[0])


H_GRID = (0.0, 500.0, 2000.0, 6000.0)


def _league_rate(hist: dict, kind: str, upto: int) -> float:
    num = den = 0.0
    for key, h in hist.items():
        if key.startswith(kind + ":"):
            for s, x in h.items():
                if s < upto and x.get("war") is not None and x.get("n"):
                    num += x["war"]
                    den += x["n"]
    return num / den * UNIT[kind] if den else 0.0


def _target_arrays(hist: dict, kind: str, T: int) -> dict | None:
    """Players with MIN_TARGET_N in season T and any of the three before: weighted sums, the actual rate, weights."""
    w3 = WEIGHTS[kind]
    unit = UNIT[kind]
    num, den, y, wt, last = [], [], [], [], []
    for key, h in hist.items():
        if not key.startswith(kind + ":"):
            continue
        t = h.get(T)
        if not t or (t.get("n") or 0) < MIN_TARGET_N[kind] or t.get("war") is None:
            continue
        a = d = 0.0
        for i, ww in enumerate(w3):
            x = h.get(T - 1 - i)
            if x and x.get("war") is not None and x.get("n"):
                a += ww * float(x["war"])
                d += ww * float(x["n"])
        if d <= 0:
            continue
        lx = h.get(T - 1)
        num.append(a)
        den.append(d)
        y.append(float(t["war"]) / float(t["n"]) * unit)
        wt.append(float(t["n"]))
        last.append(float(lx["war"]) / float(lx["n"]) * unit if lx and lx.get("n") and lx.get("war") is not None else np.nan)
    if not y:
        return None
    return {"num": np.array(num), "den": np.array(den), "y": np.array(y), "w": np.array(wt), "last": np.array(last)}


def _sse(A: dict, k: float, hpt: float, m: float, unit: float) -> float:
    mt = m * A["den"] / (A["den"] + hpt) if hpt > 0 else np.full(len(A["den"]), m)
    pred = (A["num"] + k * mt / unit) / (A["den"] + k) * unit
    return float((A["w"] * (pred - A["y"]) ** 2).sum())


def fit_projection(hist: dict[str, dict[int, dict]], seasons: list[int], kind: str) -> dict:
    """Walk-forward choice of (k, hpt) for one kind, and the validation: for each target season T with at least two
    earlier targets, (k, hpt) minimise the weighted squared error over the targets before T; the projection for T is then
    scored on T (players with >= MIN_TARGET_N), against last season's rate and against the league rate."""
    ss = sorted(seasons)
    unit = UNIT[kind]
    arrays = {T: _target_arrays(hist, kind, T) for T in ss}
    lrate = {T: _league_rate(hist, kind, T) for T in ss}
    chosen: dict[int, list] = {}
    val = {"proj": 0.0, "last": 0.0, "league": 0.0, "w": 0.0, "targets": []}
    for T in ss:
        prior = [P for P in ss if P < T and arrays.get(P) is not None]
        if len(prior) < 2:
            continue
        best, bp = None, (K_GRID[kind][3], 0.0)
        for k in K_GRID[kind]:
            for hpt in H_GRID:
                tot = sum(_sse(arrays[P], k, hpt, lrate[P], unit) for P in prior)
                if best is None or tot < best:
                    best, bp = tot, (k, hpt)
        chosen[T] = list(bp)
        A = arrays.get(T)
        if A is None:
            continue
        m = lrate[T]
        val["proj"] += _sse(A, bp[0], bp[1], m, unit)
        lastp = np.where(np.isnan(A["last"]), m, A["last"])
        val["last"] += float((A["w"] * (lastp - A["y"]) ** 2).sum())
        val["league"] += float((A["w"] * (m - A["y"]) ** 2).sum())
        val["w"] += float(A["w"].sum())
        val["targets"].append(T)
    fin = chosen[max(chosen)] if chosen else [K_GRID[kind][3], 0.0]
    out = {"k": {T: v[0] for T, v in chosen.items()}, "h": {T: v[1] for T, v in chosen.items()}, "k_final": fin[0], "h_final": fin[1]}
    if val["w"] > 0:
        out["validation"] = {"targets": val["targets"], "rmse": {"projection": math.sqrt(val["proj"] / val["w"]),
                                                                 "last_season": math.sqrt(val["last"] / val["w"]),
                                                                 "league_rate": math.sqrt(val["league"] / val["w"])},
                             "unit": f"WAR per {int(unit)} {'PA' if kind == 'H' else 'BF'}", "min_n": MIN_TARGET_N[kind]}
    return out


def project(hist: dict[str, dict[int, dict]], next_season: int, kind: str, k: float, curve: list[float], hpt: float = 0.0) -> dict[str, dict]:
    """{pid: {"rate": projected WAR per unit, "n_w": weighted sample, "age"}} for next_season."""
    unit = UNIT[kind]
    num = den = 0.0
    for key, h in hist.items():
        if key.startswith(kind + ":"):
            for s, x in h.items():
                if s < next_season and x.get("war") is not None and x.get("n"):
                    num += x["war"]
                    den += x["n"]
    m = num / den * unit if den else 0.0
    out = {}
    for key, h in hist.items():
        if not key.startswith(kind + ":"):
            continue
        r, nw = _marcel(h, next_season, kind, k, m, hpt)
        if r is None:
            continue
        last = h.get(next_season - 1) or {}
        age = last.get("age")
        out[key.split(":", 1)[1]] = {"rate": r + age_delta(curve, age), "n_w": nw, "age": (age + 1) if age is not None else None}
    return out


def marcel_time(h: dict[int, dict], s: int, kind: str, level: str) -> float:
    """Marcel's playing time for next season: 0.5 n(S) + 0.1 n(S-1) + a base (hitters 200 PA, pitchers 60 BF;
    NPB's shorter season scaled)."""
    a = (h.get(s) or {}).get("n") or 0
    b = (h.get(s - 1) or {}).get("n") or 0
    base = 200.0 if kind == "H" else 60.0
    return (0.5 * a + 0.1 * b + base) * SCHEDULE.get(level, 162) / 162.0


# ── the value payload ───────────────────────────────────────────────────────

FIELDS = ["pid", "name", "team", "kind", "pos", "elig", "age", "g", "n", "war", "rate", "pct", "war_prev", "proj", "why"]


def floors(level: str, team_games: int) -> dict:
    """Leaderboard and percentile floors: 2.1 PA and 1.25 BF per team game (the catalogues' reference rules)."""
    tg = max(team_games or 0, 20)
    return {"H": max(50, int(round(2.1 * tg))), "P": max(40, int(round(1.25 * tg)))}


def why(r: dict) -> str:
    c = [x for x in (r.get("comps") or []) if x[1] is not None]
    if r["kind"] == "H":
        parts = sorted([x for x in c if x[0] not in ("Replacement", "Replacement (wins)")], key=lambda x: -abs(x[1]))[:3]
        return ", ".join(f"{k.lower()} {v:+.1f}" for k, v in parts) + " runs"
    return ", ".join(f"{k} {v}" for k, v in c if v is not None)


def value_payload(level: str, season: int, rows: list[dict], prev: list[dict] | None, proj: dict | None, team_games: int,
                  phase: str | None, proj_meta: dict | None = None) -> dict:
    """<L>/<S>/value.json: the leaderboard and the best at each position."""
    fl = floors(level, team_games)
    prev_by = {(r["kind"], r["pid"]): r for r in (prev or [])}
    pool = {k: [r["war"] for r in rows if r["kind"] == k and (r.get("n") or 0) >= fl[k] and r.get("war") is not None] for k in ("H", "P")}
    out_rows = []
    for r in rows:
        if (r.get("n") or 0) < 10:
            continue
        p = prev_by.get((r["kind"], r["pid"]))
        pj = ((proj or {}).get(r["kind"]) or {}).get(r["pid"])
        pct = pct_rank(pool[r["kind"]], r["war"]) if (r.get("n") or 0) >= fl[r["kind"]] else None
        out_rows.append([r["pid"], r.get("name"), r.get("team"), r["kind"], r.get("pos"), eligible(r), an.rnd(r.get("age"), 1), r.get("g"),
                         r.get("n"), an.rnd(r.get("war"), 1), an.rnd(r.get("rate"), 2), an.rnd(pct, 0),
                         an.rnd(p.get("war"), 1) if p else None, an.rnd(pj.get("war"), 1) if pj else None, why(r)])
    best = {}
    for pos in POSITIONS:
        cand = []
        for r in rows:
            if r.get("war") is None or (r.get("n") or 0) < fl[r["kind"]] * (0.5 if r["kind"] == "H" else 0.5):
                continue
            if r["kind"] == "H" and pos in HIT_POS and r.get("pos") == pos:
                cand.append(r)
            elif r["kind"] == "P" and pos in PIT_POS and r.get("pos") == pos:
                cand.append(r)
        vals = [r["war"] for r in cand]
        cand.sort(key=lambda r: -r["war"])
        best[pos] = [[r["pid"], r.get("name"), r.get("team"), an.rnd(r["war"], 1), an.rnd(r.get("rate"), 2), an.rnd(pct_rank(vals, r["war"]), 0),
                      r.get("n"), an.rnd(r.get("age"), 1), why(r), _stat_line(r)] for r in cand[:10]]
    return {"ok": True, "level": level, "season": season, "updated_at": an.now(), "phase": phase, "currency": CURRENCY.get(level),
            "units": {"H": "WAR per 600 PA", "P": "WAR per 700 BF"}, "floors": fl, "fields": FIELDS, "rows": out_rows,
            "best": best, "positions": list(POSITIONS), "projection": proj_meta,
            "notes": [f"Value is {CURRENCY.get(level)}; the rate is per 600 plate appearances (hitters) or 700 batters faced (pitchers).",
                      "Best at each position: players whose primary position it is (most games there; pitchers by role), with at least "
                      "half the leaderboard floor.",
                      "Next season: a Marcel-style projection of the WAR rate (three seasons, regressed, aged) times Marcel's playing time."]}


def _stat_line(r: dict) -> str:
    st = r.get("stat") or {}
    parts = []
    for k, v in st.items():
        if v is None:
            continue
        if k in ("wOBA", "xwOBA+", "OPS", "K%"):
            parts.append(f"{k} {v:.3f}".replace("0.", ".") if k != "K%" else f"K% {100 * v:.1f}")
        elif k in ("RA9", "FIP", "ERA"):
            parts.append(f"{k} {v:.2f}")
        else:
            parts.append(f"{k} {v}")
    return " · ".join(parts[:3])


# ── team strengths and needs ────────────────────────────────────────────────

def position_values(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{team: {pos: {"war": WAR at the position, "players": [[pid, share of his games there, WAR there]]}}}."""
    out: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"war": 0.0, "players": []}))
    for r in rows:
        if r.get("war") is None or not r.get("team"):
            continue
        pg = r.get("pos_g") or {}
        tot = sum(pg.values())
        if tot <= 0:
            continue
        for pos, gm in pg.items():
            if pos not in POSITIONS or gm <= 0:
                continue
            w = r["war"] * gm / tot
            cell = out[r["team"]][pos]
            cell["war"] += w
            cell["players"].append([r["pid"], gm / tot, w, gm])
    return out


def value_ft(row: dict, pos: str, proj_rate: float | None, slot: dict, rpw: float) -> float | None:
    """Projected wins over a full season in `pos` (hitters: a lineup slot of slot["pa"] PA, the positional
    adjustment swapped for the new position's; pitchers: slot["sp"] or slot["rp"] batters faced)."""
    if proj_rate is None:
        return None
    if row["kind"] == "H":
        if pos not in HIT_POS:
            return None
        # the positional adjustment inside his rate, per 600 PA, from where he played (a full season of 650 PA at a
        # position carries POS_ADJ runs): from his position shares, not pos_runs / PA, which a player with many games
        # and few plate appearances (defensive replacements, pinch runners) would blow up
        pg = {k: v for k, v in (row.get("pos_g") or {}).items() if k in POS_ADJ and v}
        tot = sum(pg.values())
        mix = sum(POS_ADJ[k] * v for k, v in pg.items()) / tot if tot else POS_ADJ.get(row.get("pos"), 0.0)
        off_def = proj_rate - mix * (RATE_PA / 650.0) / rpw
        return off_def * slot["pa"] / RATE_PA + POS_ADJ.get(pos, 0.0) / rpw * (slot["pa"] / 650.0)
    if pos not in PIT_POS:
        return None
    return proj_rate * slot["sp" if pos == "SP" else "rp"] / RATE_BF


ROT, PEN = 5, 7                                  # rotation and bullpen slots a club's pitchers are compared in


def slot_value(row: dict, pos: str, proj_rate: float | None, slot: dict, rpw: float) -> float | None:
    """Projected wins over a full season in one slot: a lineup position (value_ft), one rotation spot (a fifth of
    the starters' batters faced) or one bullpen spot (a seventh of the relievers')."""
    v = value_ft(row, pos, proj_rate, slot, rpw)
    if v is None or pos not in PIT_POS:
        return v
    return v / (ROT if pos == "SP" else PEN)


def team_needs(level: str, season: int, rows: list[dict], proj: dict, teams: dict[str, dict], contention: dict[str, dict],
               slot: dict, rpw: float, n_cands: int = 5, no_dh: set | None = None, no_dh_note: str | None = None,
               dh_next: bool = False) -> dict[str, dict]:
    """{tid: <L>/<S>/value/<tid>.json payload}. teams: {tid: {name, abbr, league, division}};
    contention: {tid: {"out": bool, "why": text}}; no_dh: clubs whose league played without the DH this season (NPB's
    Central League to 2026): their DH is neither graded nor counted among the league's DH values."""
    no_dh = set(no_dh or ())
    pv = position_values(rows)
    tids = sorted(teams)
    vals = {pos: [pv.get(t, {}).get(pos, {}).get("war", 0.0) for t in tids if not (pos == "DH" and t in no_dh)] for pos in POSITIONS}
    by_pid = {(r["kind"], r["pid"]): r for r in rows}

    def prate(r):
        p = (proj.get(r["kind"]) or {}).get(r["pid"])
        if p and p.get("rate") is not None:
            return p["rate"]
        return r.get("rate")

    def elig_at(r, pos):
        return pos in eligible(r) or (r["kind"] == "H" and pos == "DH")
    min_n = {"H": 100, "P": 80}
    # every player's projected full-season value at each position he can play, and each club's best there
    vft: dict[tuple, float] = {}
    club_best: dict[tuple, list] = defaultdict(list)
    for r in rows:
        if r.get("war") is None or not r.get("team"):
            continue
        for pos in (HIT_POS if r["kind"] == "H" else PIT_POS):
            if not elig_at(r, pos):
                continue
            v = slot_value(r, pos, prate(r), slot, rpw)
            if v is None:
                continue
            vft[(r["kind"], r["pid"], pos)] = v
            if pos != "DH" or "DH" in eligible(r):
                club_best[(r["team"], pos)].append((v, r["pid"]))
    for k in club_best:
        club_best[k].sort(reverse=True)
    out = {}
    for t in tids:
        grades = []
        for pos in POSITIONS:
            cell = pv.get(t, {}).get(pos, {"war": 0.0, "players": []})
            if pos == "DH" and t in no_dh:
                grades.append({"pos": pos, "war": an.rnd(cell["war"], 1), "pct": None, "grade": None, "players": [], "rank": None,
                               "of": None, "incumbent_ft": None, "ungraded": True,
                               "evidence": no_dh_note or "no designated hitter in this league this season"})
                continue
            pc = pct_rank(vals[pos], cell["war"])
            kind = "P" if pos in PIT_POS else "H"
            # hitters: the players with the most games there; pitchers: the most WAR in the role
            top = sorted(cell["players"], key=lambda x: -(x[2] if kind == "P" else x[3]))[:3]
            names = []
            for pid, sh, w, gm in top:
                rr = by_pid.get((kind, pid)) or {}
                names.append([pid, rr.get("name"), an.rnd(sh, 2), an.rnd(w, 1), an.rnd(gm, 1)])
            # the incumbent: for a lineup position the player with the most games there; for the rotation and the
            # bullpen the club's fifth-best starter / seventh-best reliever by projection (the one a newcomer replaces)
            if kind == "H":
                inc = vft.get((kind, top[0][0], pos)) if top else None
            else:
                own = sorted((v for (v, pid) in club_best.get((t, pos), []) if (by_pid.get(("P", pid)) or {}).get("n", 0) >= min_n["P"]), reverse=True)
                k_slot = ROT if pos == "SP" else PEN
                inc = own[k_slot - 1] if len(own) >= k_slot else 0.0
            grades.append({"pos": pos, "war": an.rnd(cell["war"], 1), "pct": an.rnd(pc, 0), "grade": grade(pc), "players": names,
                           "rank": 1 + sum(1 for x in vals[pos] if x > cell["war"]), "of": len(vals[pos]), "incumbent_ft": an.rnd(inc, 1),
                           "evidence": _evidence(pos, names, by_pid)})
        graded = [g for g in grades if not g.get("ungraded")]
        ordered = sorted(graded, key=lambda g: (-(g["pct"] or 0), -(g["war"] or 0)))
        strengths = ordered[:3]
        weak = sorted(graded, key=lambda g: ((g["pct"] if g["pct"] is not None else 50), g["war"] or 0))[:3]
        improve = {}
        targets = list(weak)
        if dh_next and t in no_dh:                   # a league adopting the DH next season: every club needs one
            targets.append({"pos": "DH", "incumbent_ft": 0.0})
        for gr in targets:
            pos = gr["pos"]
            kind = "P" if pos in PIT_POS else "H"
            inc_ft = gr.get("incumbent_ft") or 0.0
            cands = []
            for r in rows:
                if r.get("team") in (None, t) or r["kind"] != kind or (r.get("n") or 0) < min_n[kind]:
                    continue
                v = vft.get((kind, r["pid"], pos))
                if v is None:
                    continue
                gain = v - inc_ft
                if gain <= 0.3:
                    continue
                hints = []
                c = contention.get(r["team"]) or {}
                if c.get("out"):
                    hints.append(c.get("why") or "his club is out of contention")
                # surplus: another player of his club at the position worth at least three quarters as much
                mate = next((x for x in club_best.get((r["team"], pos), []) if x[1] != r["pid"]), None)
                if mate is not None and v > 0 and mate[0] >= 0.75 * v and mate[0] > (1.0 if kind == "H" else 0.5):
                    hints.append(f"his club has another {pos} projected at {mate[0]:.1f} wins" if kind == "H" else
                                 f"his club has another {'starter' if pos == 'SP' else 'reliever'} projected at {mate[0]:.1f} wins a slot")
                cands.append({"pid": r["pid"], "name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"), "age": an.rnd(r.get("age"), 1),
                              "war": an.rnd(r.get("war"), 1), "proj_ft": an.rnd(v, 1), "gain": an.rnd(gain, 1), "hints": hints,
                              "n": r.get("n")})
            cands.sort(key=lambda x: (-x["gain"], x["pid"]))
            improve[pos] = cands[:n_cands]
        out[t] = {"ok": True, "level": level, "season": season, "tid": t, "team": teams[t], "updated_at": an.now(), "grades": grades,
                  "strengths": [g["pos"] for g in strengths], "weaknesses": [g["pos"] for g in weak] + (["DH"] if dh_next and t in no_dh else []),
                  "improve": improve,
                  "label": LABEL, "free_agents": "Not identified by our data (no transaction or contract feed is used).",
                  "units": {"war": CURRENCY.get(level), "gain": "wins over a full season at the position (one rotation or bullpen slot for pitchers)"}}
    return out


def _evidence(pos: str, names: list, by_pid: dict) -> str:
    if not names:
        return "no player recorded at the position"
    pid, nm, sh, w, gm = names[0]
    r = by_pid.get(("P" if pos in PIT_POS else "H", pid)) or {}
    line = _stat_line(r)
    lead = f"{nm}: {w:+.1f} WAR there" + (f" ({int(round(100 * sh))}% of his games)" if pos in HIT_POS and sh is not None else "")
    return lead + (f"; {line}" if line else "")
