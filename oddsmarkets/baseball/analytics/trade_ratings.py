"""
Trade ratings (docs/VALUE_SECTIONS.md section 4; MODELS.md section 27): every MLB trade valued for each club at the time
it was made and against what has happened since.

The pieces. A trade's players (analytics/moves.trades); cash, players to be named later, bonus pool money and picks are
listed but not valued (the transactions do not price them).

Value at the time, for the club that receives the player, in Bullpen WAR, from data before the trade date only:
  * a major leaguer (MLB plate appearances or batters faced in the three seasons before): his rate is value.py's Marcel
    projection from the seasons before the trade's season, with the season to date folded in as one more season (its WAR
    estimated from his wOBA, or wOBA allowed, before the date: `valuation.proxy_fit`, fitted on full seasons before the
    trade's season). The rest of the season: that rate times his playing-time pace over the club's games left. Later
    seasons: valuation.py's calibrated path (aged, attrition and regression included). Each later season is weighted by
    the chance he is still with the club (`retention_fit`, below) and discounted 8% a year; five seasons in all
    (the rest of the season and four more for an in-season trade).
  * a minor leaguer (or a player with little MLB time): valuation.prospect_fit's expected MLB WAR over four seasons
    (discounted) from his latest complete minor-league season before the trade (level, age for the level, performance,
    sample).
  * anyone else (no minor-league line in the two seasons before: an amateur signee, a player hurt all season): the
    average, over the trades of 2015-2022, of what players of his age band with no MLB record at the time went on to
    produce in the majors in the four seasons after (`base_rates`).
Retention: of traded players who played in the majors in a later season, the share who did so mainly for the club that
acquired them, by years of MLB service at the trade (from the debut year: 0-2, 3-5, 6+), by whether the trade was made in
season or between seasons, and by seasons after the trade. It stands in for contracts and club control, which no
legitimate free source gives.

Realised value for the club: what the player has produced for it since the trade: the season's WAR split by plate
appearances (batters faced) with the club after the date, moved by how his wOBA (allowed) there compared with his season's
(`valuation.war_part`), plus each later season's WAR with the club, through the latest season on disk.

Per club: value in, value out, net; a grade from the net expected value (A +2 wins or more, B +0.75, C within 0.75, D -0.75,
F -2 or worse) and the same for the realised net to date; the winner is the club with the larger net when it is at least
0.75 wins. Ledgers: every club's trades of the last twelve months summed. Validation (`validate`): for the trades of
2016-2024 the expectation over the rest of the season and the next season against what was realised over the same span,
next to the naive forecast "last season's WAR" over the same playing time.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import valuation as VA
from oddsmarkets.baseball.analytics import value as V

log = logging.getLogger(__name__)
VERSION = "trade-ratings-1"
GRADE_CUTS = ((2.0, "A"), (0.75, "B"), (-0.75, "C"), (-2.0, "D"))
SERVICE = ((0, 3, "0-2"), (3, 6, "3-5"), (6, 99, "6+"))
PROSPECT_AGES = ((0, 21, "20 or younger"), (21, 23, "21-22"), (23, 25, "23-24"), (25, 27, "25-26"), (27, 99, "27 or older"))


def grade(net: float | None) -> str | None:
    if net is None:
        return None
    for cut, g in GRADE_CUTS:
        if net >= cut:
            return g
    return "F"


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def timing(d: str, bounds: dict[int, tuple[date, date]]) -> tuple[int, bool]:
    """(the season the value starts in, in season?): a trade during a regular season starts in it; one after it, in the
    next; one before it (January to March), in it."""
    x = _d(d)
    lo, hi = bounds.get(x.year) or (date(x.year, 3, 28), date(x.year, 9, 30))
    if lo <= x <= hi:
        return x.year, True
    return (x.year + 1, False) if x > hi else (x.year, False)


def club_games(store: dict, club: str) -> list[str]:
    return sorted(str(g["date"])[:10] for g in (store.get("games") or {}).values()
                  if g.get("gtype") == "R" and club in (g.get("home"), g.get("away")) and g.get("date"))


def frac_left(store: dict, club: str, d: str) -> float:
    """Share of the club's regular-season games on or after the date."""
    gs = club_games(store, club)
    if not gs:
        return 0.0
    return sum(1 for g in gs if g >= d) / len(gs)


def service_band(pid: str, season: int, people: dict) -> str | None:
    deb = (people.get(pid) or {}).get("debut")
    if not deb:
        return None
    yrs = season - int(deb)
    for lo, hi, lab in SERVICE:
        if lo <= yrs < hi:
            return lab
    return "6+"


def age_at(pid: str, d: str, people: dict, extra: dict) -> float | None:
    dob = (people.get(pid) or {}).get("birth") or (extra.get(pid) or {}).get("dob")
    if not dob:
        return None
    try:
        b = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return None
    return round((_d(d) - b).days / 365.25, 1)


def prospect_band(age: float | None) -> str:
    a = age if age is not None else 23.0
    for lo, hi, lab in PROSPECT_AGES:
        if lo <= a < hi:
            return lab
    return PROSPECT_AGES[-1][2]


class World:
    """Everything a valuation at a date needs: value rows' history, the projection's k and aging, the horizon and band
    fits, the club splits, the in-season proxy, retention, Triple-A and base-rate fits, stores, people."""

    def __init__(self, hist: dict, ks: dict, curves: dict, hfit: dict, splits: VA.Splits, stores: dict[int, dict],
                 bounds: dict[int, tuple[date, date]], people: dict, extra_people: dict, prows: dict | None = None,
                 pfit: dict | None = None, rpw: float = 10.0):
        self.hist, self.ks, self.curves, self.hfit, self.splits = hist, ks, curves, hfit, splits
        self.stores, self.bounds, self.people, self.extra = stores, bounds, people, extra_people
        self.rpw = rpw
        self.last = max(s for s in stores) if stores else date.today().year
        self.proxy: dict[tuple, list[float]] = {}
        self.retention: dict = {}
        self.base: dict = {}
        self.prows = prows or {}
        self.pfit = pfit or {}

    def proxy_coef(self, kind: str, season: int) -> list[float]:
        key = (kind, season)
        if key not in self.proxy:
            self.proxy[key] = VA.proxy_fit(self.hist, self.splits, kind, [s for s in self.stores if s < season and s not in VA.EXCLUDE])
        return self.proxy[key]

    def lg_rate(self, kind: str, upto: int) -> float:
        return V._league_rate(self.hist, kind, upto)

    def kinds_of(self, pid: str) -> list[str]:
        return [k for k in ("H", "P") if (k + ":" + pid) in self.hist]


def value_at(W: World, pid: str, d: str, club: str, horizon: int = VA.HORIZON) -> dict:
    """The expected value of a player for `club` from the date on (see the module notes): {"type", "kind", "rest",
    "path", "ret", "value", "e2" (the rest of this season and the next, undiscounted, retention-weighted), "age",
    "service"}."""
    S, inseason = timing(d, W.bounds)
    service = service_band(pid, S, W.people)
    age = age_at(pid, d, W.people, W.extra)
    out: dict[str, Any] = {"type": None, "kind": None, "rest": 0.0, "path": [], "value": 0.0, "e2": 0.0, "age": age, "service": service}
    kinds = W.kinds_of(pid)
    best = None
    for kind in kinds:
        h = W.hist.get(kind + ":" + pid) or {}
        recent = [s for s in h if S - 3 <= s <= S - 1 and (h[s].get("n") or 0) > 0]
        part = W.splits.part(kind, pid, S, None, None, (_d(d) - timedelta(days=1)).isoformat()) if inseason else (0.0, 0.0, 0.0)
        if not recent and part[0] < 30:
            continue
        kh = W.ks.get(kind) or [1500.0, 0.0]
        kh = kh if isinstance(kh, (list, tuple)) else [float(kh), 0.0]
        m = W.lg_rate(kind, S)
        h2 = {s: x for s, x in h.items() if s < S}
        f_left = 0.0
        if inseason and part[0] > 0:
            lgw = (W.splits.lg.get(S) or {}).get("woba") or 0.315
            h2[S] = {"war": VA.proxy_war(kind, part, lgw, W.proxy_coef(kind, S)), "n": part[0]}
        if inseason:
            f_left = frac_left(W.stores.get(S) or {}, club, d)
            rate_now, _ = V._marcel(h2, S + 1, kind, kh[0], m, kh[1])
            if rate_now is None:
                continue
            pace = part[0] / max(1.0 - f_left, 0.15) if part[0] > 0 else 0.0
            pt_prev = V.marcel_time(h2, S - 1, kind, "mlb") if (S - 1) in h2 else 0.0
            full = 0.5 * pace + 0.5 * pt_prev if pt_prev > 0 else pace
            rest = rate_now * f_left * full / V.UNIT[kind]
            h3 = dict(h2)
            if S in h3:
                h3[S] = {"war": h3[S]["war"], "n": min(full, 800.0)}
            pt_next = V.marcel_time(h3, S, kind, "mlb") if S in h3 else V.marcel_time(h2, S - 1, kind, "mlb")
            age_s = (age - 0.5) if age is not None else None          # baseball age: the season's age
            rate1 = rate_now + V.age_delta(W.curves.get(kind) or [0, 0, 0], age_s)
            path = VA.expected_path(rate1, pt_next, (age_s + 1) if age_s is not None else None, kind, W.curves, W.hfit, horizon - 1)
        else:
            rate0, _ = V._marcel(h2, S, kind, kh[0], m, kh[1])
            if rate0 is None:
                continue
            last = max(s for s in h2) if h2 else S - 1
            age_prev = (h2.get(last) or {}).get("age")
            rate1 = rate0 + V.age_delta(W.curves.get(kind) or [0, 0, 0], age_prev)
            pt = V.marcel_time(h2, last, kind, "mlb") if last == S - 1 else V.marcel_time(h2, last, kind, "mlb") * 0.5
            rest = 0.0
            path = VA.expected_path(rate1, pt, (age_prev + 1) if age_prev is not None else age, kind, W.curves, W.hfit, horizon)
        ret = retention_path(W, service, inseason, len(path))
        val = rest + sum((VA.DISCOUNT ** (t + (1 if inseason else 0))) * path[t] * ret[t] for t in range(len(path)))
        e2 = rest + (path[0] * ret[0] if path else 0.0)
        # the naive forecast for the validation: his last season's WAR rate (50+ PA / BF) over the same playing time,
        # with the same calibration of next season
        prev = [s for s in sorted(h2) if s < S and (h2[s].get("n") or 0) >= 50 and h2[s].get("war") is not None]
        naive = None
        if prev:
            lr = float(h2[prev[-1]]["war"]) / float(h2[prev[-1]]["n"])
            sl = (((W.hfit.get(kind) or {}).get(str(VA.age_band(age))) or {}).get("slope") or [1.0])[0] or 1.0
            pt1 = pt_next if inseason else pt
            naive = lr * ((f_left * full if inseason else 0.0) + ret[0] * pt1 * sl)
        cand = {"type": "mlb", "kind": kind, "rest": rest, "path": path, "ret": ret, "value": val, "e2": e2, "f_left": f_left,
                "naive": naive}
        if best is None:
            best = cand
        else:                                                 # a two-way player: both kinds add up
            best = {"type": "mlb", "kind": "H+P", "rest": best["rest"] + rest, "path": [a + b for a, b in zip(best["path"], path)],
                    "ret": ret, "value": best["value"] + val, "e2": best["e2"] + e2, "f_left": f_left,
                    "naive": (best.get("naive") or 0.0) + (naive or 0.0) if (best.get("naive") is not None or naive is not None) else None}
    if best is not None:
        out.update(best)
        return out
    # a prospect: the minor-league model on his latest complete minor-league season before the date
    for s0 in (S - 1, S - 2):
        cands = [(k, W.prows.get((s0, k, pid))) for k in ("H", "P")]
        cands = [(k, r) for k, r in cands if r]
        if not cands:
            continue
        kind, r = max(cands, key=lambda kr: kr[1]["n"])
        pv = VA.prospect_value(W.pfit, kind, r)
        if pv is not None:
            early = float(((W.pfit.get(kind) or {}).get("early_share")) or 0.25)
            out.update(type="prospect", kind=kind, value=pv, e2=pv * early, level=r["level"], line_season=s0, z=round(r["z"], 2),
                       line_n=r["n"])
            return out
    b = W.base.get(prospect_band(age)) or {}
    out.update(type="base", value=b.get("value") or 0.0, e2=b.get("e2") or 0.0, band=prospect_band(age))
    return out


def retention_path(W: World, service: str | None, inseason: bool, n: int) -> list[float]:
    key = f"{service or 'none'}|{'in' if inseason else 'off'}"
    p = (W.retention.get("by") or {}).get(key) or (W.retention.get("by") or {}).get(f"{service or 'none'}|any") or []
    out = []
    for t in range(n):
        v = p[t] if t < len(p) and p[t] is not None else (out[-1] if out else 0.9)
        out.append(float(v))
    return out


# ── realised ────────────────────────────────────────────────────────────────

def realised(W: World, pid: str, d: str, club: str) -> dict:
    """WAR produced for `club` since the date, by season: {"total", "by": {season: WAR}, "n": PA or BF}."""
    S, inseason = timing(d, W.bounds)
    by: dict[int, float] = {}
    n_tot = 0.0
    for kind in W.kinds_of(pid):
        h = W.hist.get(kind + ":" + pid) or {}
        for s in range(S, W.last + 1):
            x = h.get(s)
            if not x or x.get("war") is None:
                continue
            tot = W.splits.part(kind, pid, s)
            lo = d if (s == S and inseason) else None
            part = W.splits.part(kind, pid, s, club, lo, None)
            if part[0] <= 0:
                continue
            w = VA.war_part(x["war"], kind, tot, part, W.rpw)
            by[s] = by.get(s, 0.0) + w
            n_tot += part[0]
    return {"total": float(sum(by.values())), "by": {s: round(v, 2) for s, v in by.items()}, "n": n_tot}


# ── fits on history ─────────────────────────────────────────────────────────

def retention_fit(W: World, trades: list[dict], upto: int) -> dict:
    """{"by": {"<service>|<in|off>": [share with the acquiring club, t = 0..4]}, "n": {...}}: among traded players who
    played in the majors in a season after the trade, the share whose PA (BF) that season were mostly with the club that
    acquired them."""
    acc: dict[tuple, list] = defaultdict(lambda: [0, 0])
    for t in trades:
        S, inseason = timing(t["date"], W.bounds)
        if S > upto:
            continue
        for p in t["pieces"]:
            kinds = W.kinds_of(p["pid"])
            if not kinds:
                continue
            sv = service_band(p["pid"], S, W.people) or "none"
            for k in range(5):
                T = S + k + (1 if inseason else 0)
                if T > W.last or T in VA.EXCLUDE:
                    continue
                tot, mine = 0.0, 0.0
                for kind in kinds:
                    cl = W.splits.clubs(kind, p["pid"], T)
                    tot += sum(cl.values())
                    mine += cl.get(p["to"], 0.0)
                if tot <= 0:
                    continue
                for key in (f"{sv}|{'in' if inseason else 'off'}", f"{sv}|any"):
                    c = acc[(key, k)]
                    c[0] += int(mine >= 0.5 * tot)
                    c[1] += 1
    by: dict[str, list] = {}
    ns: dict[str, list] = {}
    for (key, k), (a, n) in acc.items():
        by.setdefault(key, [None] * 5)[k] = round(a / n, 3) if n >= 15 else None
        ns.setdefault(key, [0] * 5)[k] = n
    return {"by": by, "n": ns}


def base_rates(W: World, trades: list[dict], first: int = 2015, last: int = 2022) -> dict:
    """{age band: {"value": mean discounted MLB WAR over the four seasons from the trade's season, "e2": the first two
    seasons' mean, "n"}} over traded players with no MLB record before the trade (any club; a player who never reached
    the majors counts as 0)."""
    acc: dict[str, list] = defaultdict(list)
    for t in trades:
        S, inseason = timing(t["date"], W.bounds)
        if not (first <= S <= last) or S + 3 > W.last:
            continue
        for p in t["pieces"]:
            pid = p["pid"]
            kinds = ("H", "P")
            before = sum((W.hist.get(k + ":" + pid) or {}).get(s, {}).get("n") or 0 for k in kinds for s in range(S - 3, S + (0 if not inseason else 1)))
            deb = (W.people.get(pid) or {}).get("debut")
            if before > 0 or (deb and int(deb) < S):
                continue
            path = []
            for k in range(4):
                T = S + k
                w = 0.0
                for kind in kinds:
                    x = (W.hist.get(kind + ":" + pid) or {}).get(T)
                    if x and x.get("war") is not None:
                        w += float(x["war"])
                path.append(w)
            age = age_at(pid, t["date"], W.people, W.extra)
            acc[prospect_band(age)].append((VA.discounted(path), path[0] + path[1]))
    out = {}
    for band, lst in acc.items():
        a = np.array(lst)
        out[band] = {"value": round(float(a[:, 0].mean()), 3), "e2": round(float(a[:, 1].mean()), 3), "n": len(lst),
                     "share_positive": round(float((a[:, 0] > 0.5).mean()), 3)}
    return out


# ── rating trades ───────────────────────────────────────────────────────────

def rate(W: World, t: dict, with_realised: bool = True) -> dict:
    """One trade: per club the pieces in and out with their values, the totals, net, grades; the winner."""
    pieces = []
    for p in t["pieces"]:
        v = value_at(W, p["pid"], t["date"], p["to"])
        r = realised(W, p["pid"], t["date"], p["to"]) if with_realised else {"total": 0.0, "by": {}, "n": 0.0}
        pieces.append({**p, "v": v, "r": r})
    clubs = {}
    for c in t["teams"]:
        vin = sum(x["v"]["value"] for x in pieces if x["to"] == c)
        vout = sum(x["v"]["value"] for x in pieces if x["from"] == c)
        rin = sum(x["r"]["total"] for x in pieces if x["to"] == c)
        rout = sum(x["r"]["total"] for x in pieces if x["from"] == c)
        e2in = sum(x["v"]["e2"] for x in pieces if x["to"] == c)
        e2out = sum(x["v"]["e2"] for x in pieces if x["from"] == c)
        clubs[c] = {"in": vin, "out": vout, "net": vin - vout, "r_in": rin, "r_out": rout, "r_net": rin - rout, "e2_net": e2in - e2out,
                    "grade": grade(vin - vout), "r_grade": grade(rin - rout), "extras": (t.get("extras") or {}).get(c) or []}
    nets = sorted(((v["net"], c) for c, v in clubs.items()), reverse=True)
    rn = sorted(((v["r_net"], c) for c, v in clubs.items()), reverse=True)
    winner = nets[0][1] if nets and nets[0][0] >= 0.75 else None
    r_winner = rn[0][1] if rn and rn[0][0] >= 0.75 else None
    return {"id": t["id"], "date": t["date"], "teams": t["teams"], "pieces": pieces, "clubs": clubs, "winner": winner, "r_winner": r_winner}


def validate(W: World, trades: list[dict], first: int = 2016, last: int = 2024) -> dict:
    """The expectation over the rest of the trade's season and the next one (retention-weighted, undiscounted) against
    the WAR realised for the acquiring club over the same span; the naive forecast is last season's WAR rate (the
    player's last season with a sample) over the same playing time. Pieces with an MLB projection; and the clubs' nets."""
    xs, ys, zs = [], [], []
    net_e, net_r, net_z = [], [], []
    for t in trades:
        S, inseason = timing(t["date"], W.bounds)
        if not (first <= S <= last) or S + 1 > W.last:
            continue
        side: dict[str, list] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for p in t["pieces"]:
            v = value_at(W, p["pid"], t["date"], p["to"])
            r = realised(W, p["pid"], t["date"], p["to"])
            span = [s for s in r["by"] if s <= S + (1 if inseason else 0)]
            rr = sum(r["by"][s] for s in span)
            if v["type"] == "mlb" and v.get("naive") is not None:
                naive = v["naive"]
                xs.append(v["e2"])
                ys.append(rr)
                zs.append(naive)
            else:
                naive = v["e2"]
            for c, sg in ((p["to"], 1.0), (p["from"], -1.0)):
                side[c][0] += sg * v["e2"]
                side[c][1] += sg * rr
                side[c][2] += sg * naive
        if t["pieces"]:
            c = t["teams"][0]
            net_e.append(side[c][0])
            net_r.append(side[c][1])
            net_z.append(side[c][2])
    out = {"span": f"{first}-{last}", "pieces": _scores(xs, ys, zs), "nets": _scores(net_e, net_r, net_z)}
    return out


def _scores(x, y, z) -> dict:
    x, y, z = np.array(x, dtype=float), np.array(y, dtype=float), np.array(z, dtype=float)
    if len(x) < 10:
        return {"n": int(len(x))}
    def r(a, b):
        return round(float(np.corrcoef(a, b)[0, 1]), 3) if np.std(a) > 0 and np.std(b) > 0 else None
    slope = float((x * y).sum() / max((x * x).sum(), 1e-9))
    return {"n": int(len(x)), "r_model": r(x, y), "r_naive": r(z, y), "mae_model": round(float(np.abs(x - y).mean()), 3),
            "mae_naive": round(float(np.abs(z - y).mean()), 3), "slope": round(slope, 3), "mean_expected": round(float(x.mean()), 3),
            "mean_realised": round(float(y.mean()), 3), "spearman_model": _sp(x, y), "spearman_naive": _sp(z, y)}


def _sp(a, b):
    s = VA._spearman(a, b)
    return round(s, 3) if s is not None else None
