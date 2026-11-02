"""
Competition rules for The Quant Scrum: tables with bonus points, tiebreakers, and Monte Carlo simulators for the
Six Nations, The Rugby Championship, the Nations Championship and the 2027 Rugby World Cup.

Rules (verified 2 Nov 2026 against the competitions' Wikipedia articles, which cite the organisers):
  Table points   4 a win, 2 a draw; a try bonus point for 4+ tries; a losing bonus point for losing by 7 or fewer.
                 Six Nations: 3 more for a Grand Slam (five wins). Before 2017 the Six Nations had no bonus points
                 (2 a win, 1 a draw); The Rugby Championship has had bonus points since its start (Tri Nations too).
  Six Nations    tied on points: points difference, then tries scored, then shared. Triple Crown: a Home Nation
                 (England, Ireland, Scotland, Wales) beating the other three. Wooden spoon: last place.
  Rugby World Cup pools: head to head between two tied teams, then points difference, try difference, points scored,
                 tries scored (then the world ranking: our replica). 2027: six pools of four; the top two and the
                 four best third-placed teams reach a round of 16 (the third-place permutation table below);
                 thirds are ranked on table points, then points difference, try difference, points, tries.
  Nations Championship (new in 2026): two conferences of six (the Six Nations sides; the Rugby Championship sides
                 with Fiji and Japan); each side plays the six in the other conference once (three home, three away)
                 over the July and November windows; standard bonus points; then a finals weekend at Twickenham
                 (27-29 Nov 2026) where each place meets its equal: N1 v S1 the final, N2 v S2 third place, and so on.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

HOME_NATIONS = ("England", "Ireland", "Scotland", "Wales")

# 2027 Rugby World Cup (Australia, 1 Oct - 13 Nov 2027): pools from the draw of 3 Dec 2025
RWC27_POOLS = {
    "A": ["New Zealand", "Australia", "Chile", "Hong Kong"],
    "B": ["South Africa", "Italy", "Georgia", "Romania"],
    "C": ["Argentina", "Fiji", "Spain", "Canada"],
    "D": ["Ireland", "Scotland", "Uruguay", "Portugal"],
    "E": ["France", "Japan", "United States", "Samoa"],
    "F": ["England", "Wales", "Tonga", "Zimbabwe"],
}
RWC27_HOST = "Australia"
# opponents of A1, B1, C1, D1 for each set of four qualifying third-placed pools
RWC27_THIRDS = {
    "ABCD": "CDAB", "ABCE": "CEAB", "ABCF": "CFAB", "ABDE": "EDAB", "ABDF": "FDAB", "ABEF": "EFAB",
    "ACDE": "CDAE", "ACDF": "CDAF", "ACEF": "CEAF", "ADEF": "EDAF", "BCDE": "CDEB", "BCDF": "CDFB",
    "BCEF": "CEFB", "BDEF": "EDFB", "CDEF": "CDEF",
}
# round of 16 (match number: pairing). "3:A" = the third-placed team drawn against A1 by the table above
RWC27_R16 = {1: ("2C", "2F"), 2: ("1A", "3:A"), 3: ("1E", "2D"), 4: ("1B", "3:B"), 5: ("1C", "3:C"), 6: ("1D", "3:D"),
             7: ("2A", "2E"), 8: ("1F", "2B")}
RWC27_QF = {1: (2, 4), 2: (1, 3), 3: (5, 6), 4: (7, 8)}
RWC27_SF = {1: (1, 2), 2: (3, 4)}

# 2027 Six Nations fixtures (announced 9 March 2026): (date, home, away)
SIX27 = [
    ("2027-02-05", "Ireland", "England"), ("2027-02-06", "Scotland", "Italy"), ("2027-02-06", "France", "Wales"),
    ("2027-02-13", "Italy", "Ireland"), ("2027-02-13", "Scotland", "Wales"), ("2027-02-14", "England", "France"),
    ("2027-02-20", "Wales", "Ireland"), ("2027-02-20", "England", "Italy"), ("2027-02-21", "France", "Scotland"),
    ("2027-03-05", "Scotland", "Ireland"), ("2027-03-06", "Italy", "France"), ("2027-03-06", "Wales", "England"),
    ("2027-03-13", "Italy", "Wales"), ("2027-03-13", "England", "Scotland"), ("2027-03-13", "Ireland", "France"),
]
NC_NORTH = ["England", "France", "Ireland", "Italy", "Scotland", "Wales"]
NC_SOUTH = ["Argentina", "Australia", "Fiji", "Japan", "New Zealand", "South Africa"]


# ── tables ────────────────────────────────────────────────────────────────────────────────────────────────

def match_points(pf: int, pa: int, tf: int | None, bonus: bool = True) -> tuple[int, int, int]:
    """(table points, try bonus, losing bonus) for one side."""
    if not bonus:
        return (2 if pf > pa else (1 if pf == pa else 0)), 0, 0
    base = 4 if pf > pa else (2 if pf == pa else 0)
    tb = 1 if (tf is not None and tf >= 4) else 0
    lb = 1 if (pf < pa and pa - pf <= 7) else 0
    return base + tb + lb, tb, lb


def empty_row(team: str) -> dict:
    return {"team": team, "p": 0, "w": 0, "d": 0, "l": 0, "pf": 0, "pa": 0, "tf": 0, "ta": 0, "tb": 0, "lb": 0, "gs": 0, "pts": 0}


def table(results: list[dict], teams: list[str] | None = None, bonus: bool = True, grand_slam: bool = False,
          tiebreak: str = "six") -> list[dict]:
    """results: [{home, away, hs, as, ht (home tries), at}] with team names. Returns ranked rows."""
    rows = {t: empty_row(t) for t in teams or []}
    for r in results:
        for side, opp, pf, pa, tf, ta in ((r["home"], r["away"], r["hs"], r["as"], r.get("ht"), r.get("at")),
                                          (r["away"], r["home"], r["as"], r["hs"], r.get("at"), r.get("ht"))):
            x = rows.setdefault(side, empty_row(side))
            pts, tb, lb = match_points(pf, pa, tf, bonus)
            x["p"] += 1
            x["w"] += pf > pa
            x["d"] += pf == pa
            x["l"] += pf < pa
            x["pf"] += pf
            x["pa"] += pa
            x["tf"] += tf or 0
            x["ta"] += ta or 0
            x["tb"] += tb
            x["lb"] += lb
            x["pts"] += pts
    if grand_slam:
        n = max((x["p"] for x in rows.values()), default=0)
        for x in rows.values():
            if n == 5 and x["w"] == 5:
                x["gs"] = 3
                x["pts"] += 3
    return rank(list(rows.values()), results, tiebreak)


def _h2h(a: str, b: str, results: list[dict]) -> int:
    """+1 if a beat b in their meeting(s) on aggregate of wins, -1 if b did, 0 otherwise."""
    s = 0
    for r in results:
        if {r["home"], r["away"]} == {a, b}:
            pa = r["hs"] if r["home"] == a else r["as"]
            pb = r["as"] if r["home"] == a else r["hs"]
            s += (pa > pb) - (pa < pb)
    return (s > 0) - (s < 0)


def rank(rows: list[dict], results: list[dict], tiebreak: str = "six", fallback: dict | None = None) -> list[dict]:
    fb = fallback or {}

    def key(x):
        pd = x["pf"] - x["pa"]
        if tiebreak == "rwc":
            return (-x["pts"], -pd, -(x["tf"] - x["ta"]), -x["pf"], -x["tf"], -fb.get(x["team"], 0.0))
        return (-x["pts"], -pd, -x["tf"], -fb.get(x["team"], 0.0))
    rows = sorted(rows, key=key)
    if tiebreak == "rwc":
        # head to head first between exactly two teams level on points
        i = 0
        while i < len(rows) - 1:
            j = i
            while j + 1 < len(rows) and rows[j + 1]["pts"] == rows[i]["pts"]:
                j += 1
            if j == i + 1 and _h2h(rows[j]["team"], rows[i]["team"], results) > 0:
                rows[i], rows[j] = rows[j], rows[i]
            i = j + 1
    for i, x in enumerate(rows):
        x["pos"] = i + 1
        x["pd"] = x["pf"] - x["pa"]
    return rows


# ── score model for simulations ──────────────────────────────────────────────────────────────────────────

class ScoreSim:
    """Draws a final score and try counts for a match from our expected points.

    The margin is normal with our spread (ratings.wdl), the total normal with sd `sd_total`; each side's tries,
    given its points, are binomial on the number of five-point blocks with a mean `t0 + t1 * points` (fitted on
    the development years: models.fit_tries). This keeps the bonus points consistent with the score."""

    def __init__(self, s0: float, s1: float, sd_total: float = 13.0, t0: float = 0.0, t1: float = 0.125,
                 rng: random.Random | None = None):
        self.s0, self.s1, self.sd_total, self.t0, self.t1 = s0, s1, sd_total, t0, t1
        self.rng = rng or random.Random(7)

    def tries(self, pts: int) -> int:
        n = pts // 5
        if n <= 0:
            return 0
        mean = max(0.0, min(float(n), self.t0 + self.t1 * pts))
        q = mean / n
        return sum(1 for _ in range(n) if self.rng.random() < q)

    def draw(self, exp_h: float, exp_a: float) -> tuple[int, int, int, int]:
        m = exp_h - exp_a
        sd = self.s0 + self.s1 * abs(m)
        mg = self.rng.gauss(m, sd)
        tot = max(abs(mg) + 3.0, self.rng.gauss(exp_h + exp_a, self.sd_total))
        h = max(0, int(round((tot + mg) / 2)))
        a = max(0, int(round((tot - mg) / 2)))
        if h == 1:
            h = 0
        if a == 1:
            a = 0
        if h == a and abs(mg) >= 0.5:                 # rounding made a draw the margin did not
            if mg > 0:
                h += 1 if h + 1 != 1 else 3
            else:
                a += 1 if a + 1 != 1 else 3
        return h, a, self.tries(h), self.tries(a)


# ── simulators ───────────────────────────────────────────────────────────────────────────────────────────

def _expect(model, home: str, away: str, ids: dict, date: str, neutral: bool) -> tuple[float, float]:
    # a side the data has never seen (a qualifier with no test in the feed) plays on its tier's prior rating
    m = {"home": {"id": ids.get(home, "new:" + home), "name": home}, "away": {"id": ids.get(away, "new:" + away), "name": away}, "date": date,
         "neutral": neutral, "venue": {}}
    e = model.expect(m)
    return e["exp_h"], e["exp_a"]


def simulate_league(model, sim: ScoreSim, teams: list[str], ids: dict, played: list[dict], remaining: list[tuple],
                    n: int = 20000, grand_slam: bool = False, bonus: bool = True, tiebreak: str = "six",
                    triple_crown: bool = False, fallback: dict | None = None) -> dict:
    """played: result dicts; remaining: (date, home, away[, neutral]). Returns per-team chances and positions."""
    exps = [(d, h, a, _expect(model, h, a, ids, d, bool(rest[0]) if rest else False)) for d, h, a, *rest in remaining]
    pos = {t: [0] * len(teams) for t in teams}
    pts_sum = defaultdict(float)
    gs = defaultdict(int)
    tc = defaultdict(int)
    for _ in range(n):
        res = list(played)
        for d, h, a, (eh, ea) in exps:
            hs, as_, ht, at = sim.draw(eh, ea)
            res.append({"home": h, "away": a, "hs": hs, "as": as_, "ht": ht, "at": at})
        tab = table(res, teams, bonus=bonus, grand_slam=grand_slam, tiebreak=tiebreak)
        for x in tab:
            pos[x["team"]][x["pos"] - 1] += 1
            pts_sum[x["team"]] += x["pts"]
            if x["w"] == len(teams) - 1:
                gs[x["team"]] += 1
        if triple_crown:
            for t in HOME_NATIONS:
                if t not in teams:
                    continue
                if all(any(((r["home"] == t and r["away"] == o and r["hs"] > r["as"]) or
                            (r["away"] == t and r["home"] == o and r["as"] > r["hs"])) for r in res)
                       for o in HOME_NATIONS if o != t and o in teams):
                    tc[t] += 1
    out = []
    for t in teams:
        row = {"team": t, "title": pos[t][0] / n, "pos": [round(c / n, 4) for c in pos[t]],
               "last": pos[t][-1] / n, "xpts": round(pts_sum[t] / n, 2), "slam": gs[t] / n}
        if triple_crown and t in HOME_NATIONS:
            row["triple_crown"] = tc[t] / n
        out.append(row)
    out.sort(key=lambda r: (-r["title"], -r["xpts"]))
    return {"n": n, "teams": out}


def _ko(model, sim: ScoreSim, a: str, b: str, ids: dict, date: str, host: str | None) -> str:
    """A knockout tie: the winner (a level score goes to extra time and then a coin flip weighted by strength)."""
    neutral = host not in (a, b)
    home, away = (a, b) if (neutral or a == host) else (b, a)
    eh, ea = _expect(model, home, away, ids, date, neutral)
    hs, as_, _, _ = sim.draw(eh, ea)
    if hs == as_:
        p = 1.0 / (1.0 + math.exp(-(eh - ea) / 6.0))
        return home if sim.rng.random() < p else away
    return home if hs > as_ else away


def simulate_rwc27(model, sim: ScoreSim, ids: dict, played: list[dict], fallback: dict, n: int = 20000,
                   fixtures: list[tuple] | None = None) -> dict:
    """The 2027 Rugby World Cup: pools, the four best thirds, round of 16 to the final."""
    pools = RWC27_POOLS
    fx = fixtures or [(None, p, i, j) for p, ts in pools.items() for i in range(4) for j in range(i + 1, 4)]
    pre = []
    for d, p, i, j in fx:
        a, b = pools[p][i], pools[p][j]
        home, away = (b, a) if b == RWC27_HOST else (a, b)
        neutral = RWC27_HOST not in (home, away)
        pre.append((p, home, away, _expect(model, home, away, ids, d or "2027-10-08", neutral)))
    stages = ("qf", "sf", "final", "champion")
    cnt = {t: defaultdict(int) for ts in pools.values() for t in ts}
    for _ in range(n):
        res = {p: [r for r in played if r["home"] in ts and r["away"] in ts] for p, ts in pools.items()}
        done = {(r["home"], r["away"]) for ps in res.values() for r in ps}
        for p, h, a, (eh, ea) in pre:
            if (h, a) in done or (a, h) in done:
                continue
            hs, as_, ht, at = sim.draw(eh, ea)
            res[p].append({"home": h, "away": a, "hs": hs, "as": as_, "ht": ht, "at": at})
        tabs = {p: rank(table(res[p], pools[p], tiebreak="rwc"), res[p], "rwc", fallback) for p in pools}
        seat = {}
        thirds = []
        for p, tab in tabs.items():
            seat["1" + p], seat["2" + p] = tab[0]["team"], tab[1]["team"]
            thirds.append((p, tab[2]))
            for x in tab:
                cnt[x["team"]]["pool_" + str(x["pos"])] += 1
        thirds.sort(key=lambda z: (-z[1]["pts"], -z[1]["pd"], -(z[1]["tf"] - z[1]["ta"]), -z[1]["pf"], -z[1]["tf"],
                                   -fallback.get(z[1]["team"], 0)))
        q = "".join(sorted(p for p, _ in thirds[:4]))
        perm = RWC27_THIRDS[q]
        third_of = {"A": "3" + perm[0], "B": "3" + perm[1], "C": "3" + perm[2], "D": "3" + perm[3]}
        for p, x in thirds[:4]:
            seat["3" + p] = x["team"]
        r16 = {}
        for k, (x, y) in RWC27_R16.items():
            ya = seat[third_of[y[2]]] if y.startswith("3:") else seat[y]
            xa = seat[x]
            cnt[xa]["r16"] += 1
            cnt[ya]["r16"] += 1
            r16[k] = _ko(model, sim, xa, ya, ids, "2027-10-23", RWC27_HOST)
        qf = {}
        for k, (x, y) in RWC27_QF.items():
            cnt[r16[x]]["qf"] += 1
            cnt[r16[y]]["qf"] += 1
            qf[k] = _ko(model, sim, r16[x], r16[y], ids, "2027-10-30", RWC27_HOST)
        sf = {}
        for k, (x, y) in RWC27_SF.items():
            cnt[qf[x]]["sf"] += 1
            cnt[qf[y]]["sf"] += 1
            sf[k] = _ko(model, sim, qf[x], qf[y], ids, "2027-11-05", RWC27_HOST)
        cnt[sf[1]]["final"] += 1
        cnt[sf[2]]["final"] += 1
        cnt[_ko(model, sim, sf[1], sf[2], ids, "2027-11-13", RWC27_HOST)]["champion"] += 1
    out = []
    for p, ts in pools.items():
        for t in ts:
            c = cnt[t]
            out.append({"team": t, "pool": p, "win_pool": c["pool_1"] / n, "r16": c["r16"] / n,
                        "qf": c["qf"] / n, "sf": c["sf"] / n, "final": c["final"] / n, "champion": c["champion"] / n})
    out.sort(key=lambda r: -r["champion"])
    return {"n": n, "teams": out, "stages": list(stages)}


def simulate_nc(model, sim: ScoreSim, ids: dict, played: list[dict], remaining: list[tuple], n: int = 20000,
                final_date: str = "2026-11-28", final_host: str = "England") -> dict:
    """The Nations Championship: both conference tables after six rounds, then the finals weekend (each place meets
    its equal at Twickenham, England's home)."""
    exps = [(h, a, _expect(model, h, a, ids, d, False)) for d, h, a, *_ in remaining]
    cnt = {t: defaultdict(int) for t in NC_NORTH + NC_SOUTH}
    for _ in range(n):
        res = list(played)
        for h, a, (eh, ea) in exps:
            hs, as_, ht, at = sim.draw(eh, ea)
            res.append({"home": h, "away": a, "hs": hs, "as": as_, "ht": ht, "at": at})
        north = table([r for r in res if r["home"] in NC_NORTH or r["away"] in NC_NORTH], None)
        tn = [x for x in rank([x for x in north if x["team"] in NC_NORTH], res) if x["team"] in NC_NORTH]
        ts = [x for x in rank([x for x in north if x["team"] in NC_SOUTH], res) if x["team"] in NC_SOUTH]
        for i, (x, y) in enumerate(zip(tn, ts)):
            cnt[x["team"]]["conf_" + str(i + 1)] += 1
            cnt[y["team"]]["conf_" + str(i + 1)] += 1
            w = _ko(model, sim, x["team"], y["team"], ids, final_date, final_host)
            place = 2 * i + (1 if w == x["team"] else 2)
            cnt[x["team"]]["place_" + str(place)] += 1
            other = 2 * i + (2 if w == x["team"] else 1)
            cnt[y["team"]]["place_" + str(other)] += 1
            if i == 0:
                cnt[w]["champion"] += 1
                cnt[x["team"]]["final"] += 1
                cnt[y["team"]]["final"] += 1
    out = []
    for t in NC_NORTH + NC_SOUTH:
        c = cnt[t]
        out.append({"team": t, "conf": "North" if t in NC_NORTH else "South", "top_conf": c["conf_1"] / n,
                    "final": c["final"] / n, "champion": c["champion"] / n,
                    "conf_pos": [round(c["conf_" + str(i)] / n, 4) for i in range(1, 7)],
                    "place": [round(c["place_" + str(i)] / n, 4) for i in range(1, 13)]})
    out.sort(key=lambda r: -r["champion"])
    return {"n": n, "teams": out}
