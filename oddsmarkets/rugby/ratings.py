"""
Our team ratings and the match model (docs/scrum/MODELS.md).

The rating is in points: each team carries an attack rating `att` (points it scores above the era's average side)
and a defence rating `dfn` (points it stops). Before a match:

    expected home points = mu/2 + att_h - dfn_a + H/2 + travel/2 + rest/2
    expected away points = mu/2 + att_a - dfn_h - H/2 - travel/2 - rest/2
    expected margin m    = home - away;   expected total = home + away

    H       home advantage in points (0 at a neutral venue)
    travel  c_km * (log1p(km_away/1000) - log1p(km_home/1000)) + c_tz * (zones_away - zones_home)
    rest    c_rest * (min(rest_h, 28) - min(rest_a, 28)) / 7          (days since each side's last test)
    alt     c_alt * [home venue 1,000 m or higher and the away side not from altitude]  (nations.altitude_edge)

Win, draw and loss chances come from a normal margin with a spread that widens with the mismatch,
sd = s0 + s1*|m|; a draw is a final margin inside +-0.5. After the match each side's ratings move by the
error, capped at `cap` points, times a learning rate that is higher for a team's first tests:

    att_h += k_h * e_h,  dfn_a -= k_a * e_h        e_h = clip(home points - expected home points)
    (and the same for the away side's points)

Between calendar years every rating shrinks toward its tier's mean by `revert`. A team new to the data starts on
its tier's prior. `split=False` is the single-rating version (only the margin is learned; the total is the era
mean). Every parameter is chosen on the development years only (models.py); the sealed test years are scored once.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import nations

TIER_PRIOR = {1: 8.0, 2: -6.0, 3: -22.0}      # a new side's margin rating against an average test side
SQRT2 = math.sqrt(2.0)
AWAY_FROM_HOME_KM = 1500.0


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / SQRT2))


@dataclass
class Params:
    H: float = 4.5            # home advantage, points
    k: float = 0.12           # learning rate (per point of error)
    k_new: float = 0.30       # learning rate for a team's first `n_new` tests
    n_new: int = 8
    cap: float = 30.0         # error cap, points
    revert: float = 0.15      # shrink toward the tier mean between years
    c_km: float = 0.0         # travel: points per log-thousand-km of extra travel
    c_tz: float = 0.0         # travel: points per extra time zone
    c_rest: float = 0.0       # rest: points per extra week
    c_alt: float = 0.0        # altitude: points for a home side at a venue 1,000 m up against a side from lower down
    s0: float = 11.5          # margin spread at a level match
    s1: float = 0.12          # extra spread per point of expected margin
    s_tier: float = 0.0       # extra spread per tier step of the weaker side (tests between lesser sides swing more)
    wr3: bool = False         # tests with a tier-three side: the chance from our World Rugby rebuild (models.py, "hybrid")
    s_n: float = 0.0          # rating uncertainty: widens the spread for sides with few tests rated (0 = off)
    kal: bool = False         # Kalman learning rates: each side carries a rating variance v; a result moves side i by
                              # v_i / (v_h + v_a + sd^2) of the error (sd = the match's base spread), so a test between
                              # two unproven sides moves both less than a test against an established side
    v0: float = 225.0         # a new side's rating variance (points^2)
    q: float = 25.0           # variance added to every side at the turn of a year (form drifts)
    mclip: float = 0.0        # blow-out shrink: the final margin is clipped to +-mclip before the error (0 = off)
    anchor: float = 0.0       # 0..1: the between-years shrink (and a new side's start) aims at the World Rugby
                              # replica's points mapped onto our scale instead of the tier mean (0 = tier mean)
    b_map: float = 1.2        # the map: points of margin rating per World Rugby point, through (78, the tier-one prior)
    mu0: float = 42.0         # the era's average total, learned slowly
    k_mu: float = 0.01
    split: bool = True        # attack and defence (True) or one margin rating (False)
    tiers: dict = field(default_factory=lambda: dict(TIER_PRIOR))


def spread(m: float, p: Params, n_h: int = 99, n_a: int = 99, tier: int = 1, v_h: float | None = None,
           v_a: float | None = None) -> float:
    """The margin's spread: s0 + s1 |m|, widened (in quadrature) by how unsure the two ratings still are, s_n^2 for
    each side scaled by 1 / (tests rated + 1) (the Glicko idea: a side with few tests has a wide rating)."""
    base = p.s0 + p.s1 * abs(m) + p.s_tier * (tier - 1)
    if p.kal and v_h is not None:
        return math.sqrt(base * base + v_h + v_a)
    if p.s_n <= 0:
        return base
    return math.sqrt(base * base + p.s_n * p.s_n * (1.0 / (n_h + 1) + 1.0 / (n_a + 1)))


def wdl(m: float, p: Params, n_h: int = 99, n_a: int = 99, tier: int = 1, v_h: float | None = None,
        v_a: float | None = None) -> tuple[float, float, float]:
    sd = spread(m, p, n_h, n_a, tier, v_h, v_a)
    pw = 1.0 - ncdf((0.5 - m) / sd)
    pl = ncdf((-0.5 - m) / sd)
    pd = max(0.0, 1.0 - pw - pl)
    return pw, pd, pl


class Model:
    def __init__(self, p: Params | None = None):
        self.p = p or Params()
        self.att: dict[str, float] = {}
        self.dfn: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.v: dict[str, float] = {}
        self.last: dict[str, str] = {}
        self.name: dict[str, str] = {}
        self.mu = self.p.mu0
        self.year: int | None = None
        # the World Rugby rebuild run alongside, for the hybrid (Params.wr3): its logistic {a, b, draw} is set by the
        # caller (fitted on the development years)
        self.wr = None
        self.wr_fit: dict | None = None
        from .rankings import REPLICA_FROM
        self.wr_from = REPLICA_FROM
        if self.p.wr3 or self.p.anchor > 0:
            from . import rankings
            self.wr = rankings.Ranker(default=lambda t, d: {1: 78.0, 2: 66.0, 3: 52.0}[nations.tier(self.name.get(t, ""))])

    # state -------------------------------------------------------------------------------------------------
    def _target(self, tid: str, name: str, when: str = "") -> float:
        """Where a side's rating is shrunk to: its tier's prior, or (anchor > 0) a blend with the World Rugby replica's
        points (results to date only) mapped onto our scale."""
        prior = self.p.tiers.get(nations.tier(name), -22.0)
        if self.p.anchor > 0 and self.wr is not None and not nations.invitational(name):
            pts = self.wr.get(tid, when)
            mapped = self.p.tiers.get(1, 8.0) + self.p.b_map * (pts - 78.0)
            return prior + self.p.anchor * (mapped - prior)
        return prior

    def _ensure(self, tid: str, name: str, when: str = "") -> None:
        if tid not in self.att:
            self.name[tid] = name
            prior = self._target(tid, name, when)
            self.att[tid] = prior / 2.0
            self.dfn[tid] = prior / 2.0
            self.n[tid] = 0
            self.v[tid] = self.p.v0
        self.name[tid] = name

    def rating(self, tid: str) -> float:
        """The margin rating: expected margin against an average test side at a neutral venue."""
        return self.att.get(tid, 0.0) + self.dfn.get(tid, 0.0)

    def new_year(self, year: int) -> None:
        if self.year is not None and year > self.year and self.p.revert > 0:
            for t in list(self.att):
                prior = self._target(t, self.name.get(t, ""), f"{year}-01-01") / 2.0
                self.att[t] = prior + (self.att[t] - prior) * (1 - self.p.revert)
                self.dfn[t] = prior + (self.dfn[t] - prior) * (1 - self.p.revert)
        if self.year is not None and year > self.year and self.p.kal:
            for t in self.v:
                self.v[t] = min(self.p.v0, self.v[t] + self.p.q)
        self.year = year

    # features ----------------------------------------------------------------------------------------------
    def context(self, m: dict) -> dict:
        where = nations.venue_point(m)
        kh, zh = nations.travel(m["home"]["name"], where)
        ka, za = nations.travel(m["away"]["name"], where)
        day = str(m.get("date") or "")[:10]

        def rest(tid):
            l = self.last.get(tid)
            if not l:
                return 28.0
            from datetime import date
            try:
                return float((date.fromisoformat(day) - date.fromisoformat(l)).days)
            except ValueError:
                return 28.0
        # a "home" match played far from home (Fiji's 2026 home tests in Britain, Japan v Ireland in Newcastle, NSW)
        # carries no home advantage: the feed's flag says home, the venue says otherwise
        neutral = bool(m.get("neutral")) or kh > AWAY_FROM_HOME_KM
        return {"neutral": neutral, "km_h": kh, "km_a": ka, "tz_h": zh, "tz_a": za,
                "rest_h": rest(m["home"]["id"]), "rest_a": rest(m["away"]["id"]),
                "alt": 0 if neutral else nations.altitude_edge(m)}

    def expect(self, m: dict, ctx: dict | None = None) -> dict:
        p = self.p
        h, a = m["home"], m["away"]
        self._ensure(h["id"], h["name"], str(m.get("date") or ""))
        self._ensure(a["id"], a["name"], str(m.get("date") or ""))
        ctx = ctx or self.context(m)
        edge = 0.0 if ctx["neutral"] else p.H
        edge += p.c_km * (math.log1p(ctx["km_a"] / 1000.0) - math.log1p(ctx["km_h"] / 1000.0))
        edge += p.c_tz * (ctx["tz_a"] - ctx["tz_h"])
        edge += p.c_rest * (min(ctx["rest_h"], 28.0) - min(ctx["rest_a"], 28.0)) / 7.0
        if p.c_alt:
            edge += p.c_alt * ctx.get("alt", 0)
        if p.split:
            eh = self.mu / 2 + self.att[h["id"]] - self.dfn[a["id"]] + edge / 2
            ea = self.mu / 2 + self.att[a["id"]] - self.dfn[h["id"]] - edge / 2
        else:
            mg = self.rating(h["id"]) - self.rating(a["id"]) + edge
            eh, ea = self.mu / 2 + mg / 2, self.mu / 2 - mg / 2
        eh, ea = max(eh, 3.0), max(ea, 3.0)
        mg = eh - ea
        nh, na = self.n.get(h["id"], 0), self.n.get(a["id"], 0)
        tier = max(nations.tier(h["name"]), nations.tier(a["name"]))     # the weaker side's tier (1 to 3)
        vh, va = (self.v.get(h["id"], p.v0), self.v.get(a["id"], p.v0)) if p.kal else (None, None)
        pw, pd, pl = wdl(mg, p, nh, na, tier, vh, va)
        if p.wr3 and tier >= 3 and self.wr is not None and self.wr_fit:
            from . import rankings
            ra, rb = self.wr.get(h["id"], m.get("date") or ""), self.wr.get(a["id"], m.get("date") or "")
            bonus = rankings.HOME_BONUS if (not ctx["neutral"] and str(m.get("date") or "")[:10] < rankings.HOME_BONUS_ENDS) else 0.0
            z = self.wr_fit["a"] + self.wr_fit["b"] * (ra + bonus - rb)
            q = 1.0 / (1.0 + math.exp(-z))
            pd = self.wr_fit["draw"]
            pw, pl = (1 - pd) * q, (1 - pd) * (1 - q)
        return {"exp_h": eh, "exp_a": ea, "margin": mg, "total": eh + ea, "p_home": pw, "p_draw": pd, "p_away": pl,
                "sd": spread(mg, p, nh, na, tier, vh, va), "base_sd": p.s0 + p.s1 * abs(mg) + p.s_tier * (tier - 1),
                "edge": edge, "ctx": ctx}

    def update(self, m: dict, e: dict | None = None) -> dict:
        p = self.p
        e = e or self.expect(m)
        h, a = m["home"]["id"], m["away"]["id"]
        hs, as_ = float(m["hs"]), float(m["as"])

        if p.mclip > 0:                 # blow-out shrink: a 117-3 counts as a win by mclip
            mg_ = max(-p.mclip, min(p.mclip, hs - as_))
            if mg_ != hs - as_:
                tot_ = hs + as_
                hs, as_ = (tot_ + mg_) / 2.0, (tot_ - mg_) / 2.0
        if p.kal:
            vh, va = self.v.get(h, p.v0), self.v.get(a, p.v0)
            den = vh + va + e.get("base_sd", p.s0) ** 2
            kal = {h: vh / den, a: va / den}
            self.v[h], self.v[a] = vh * (1 - kal[h]), va * (1 - kal[a])

        def kk(t):
            if p.kal:
                return kal[t]
            return p.k_new if self.n.get(t, 0) < p.n_new else p.k

        def clip(x):
            return max(-p.cap, min(p.cap, x))
        if p.split:
            eh, ea = clip(hs - e["exp_h"]), clip(as_ - e["exp_a"])
            self.att[h] += kk(h) * eh
            self.dfn[a] -= kk(a) * eh
            self.att[a] += kk(a) * ea
            self.dfn[h] -= kk(h) * ea
        else:
            err = clip((hs - as_) - e["margin"])
            self.att[h] += kk(h) * err / 2
            self.dfn[h] += kk(h) * err / 2
            self.att[a] -= kk(a) * err / 2
            self.dfn[a] -= kk(a) * err / 2
        self.mu += p.k_mu * ((float(m["hs"]) + float(m["as"])) - e["total"])
        if self.wr is not None and not nations.invitational(m["home"]["name"]) and not nations.invitational(m["away"]["name"])                 and str(m.get("date") or "")[:4] >= str(self.wr_from):
            self.wr.update(h, a, int(m["hs"]), int(m["as"]), m.get("date") or "", neutral=bool(m.get("neutral")),
                           world_cup=m.get("comp") in ("rwc", "wrwc"))
        for t in (h, a):
            self.n[t] = self.n.get(t, 0) + 1
            self.last[t] = str(m.get("date") or "")[:10]
        return e


def outcome(m: dict) -> int:
    """0 home win, 1 draw, 2 away win."""
    return 0 if m["hs"] > m["as"] else (1 if m["hs"] == m["as"] else 2)


def logloss(probs: tuple, y: int) -> float:
    return -math.log(max(1e-12, probs[y]))


def brier(probs: tuple, y: int) -> float:
    return sum((probs[i] - (1.0 if i == y else 0.0)) ** 2 for i in range(3))
