"""
Fantasy football for The Quant Footballer: our own FPL-style points, projections per
fixture, rankings, picks and an optimised squad, for every followed league.

Scoring (FPL's 2025/26 rules as published, applied by us to Sofascore's match data):
minutes 1 (1-59) or 2 (60+); goals 10 (goalkeeper), 6 (defender), 5 (midfielder), 4
(forward); assists 3; a clean sheet (60+ minutes, nothing conceded while on the pitch)
4 for goalkeepers and defenders, 1 for midfielders; -1 per two goals conceded on the
pitch (goalkeepers and defenders); 1 per three saves; yellow -1, red -3 (a second yellow
counts as the red only); own goal -2; penalty missed -2; defensive contribution 2
(defenders: 10+ clearances, blocks, interceptions and tackles; midfielders and forwards:
12+ including recoveries); bonus 3/2/1 to the three best Sofascore match ratings in the
match (our stand-in for FPL's bonus point system). Penalty saves are not scored (the
incidents do not separate a save from a miss). Positions are Sofascore's G/D/M/F.

Projection per player and fixture (`project`): expected minutes and the chances of
playing at all and of 60+ from his recent share of his club's league minutes; per-90
rates of goals, assists (both a blend of the expected and the actual, recency-weighted
and shrunk to the position), saves, cards, bonus and the defensive-contribution hit
rate; the fixture from the match model's expected goals (`lh`, `la` in fixtures.json):
attacking rates scaled by the team's expected goals in the fixture against its average
over its remaining fixtures, the clean sheet by exp(-expected goals against), goals
conceded and saves from Poisson expectations.

Backtest (`backtest`): walk-forward over every league round with line-ups, projections
built only from matches before the round (the fixture's expected goals from a
walk-forward team-strength proxy, since past fixtures keep no model line), scored
against the points computed from the actual match stats, against three naive baselines
(season-to-date points per club match, the last five club matches, the last 365 days).

Prices are our own proxy (official FPL prices and ownership are not used: the Premier
League's terms forbid reproducing its material or building a database from it): each
player's expected points above replacement next season from the value model
(transfers.value_v2's first year), ranked within the league and position and mapped
onto FPL-like price ranges. The suggested squad is the integer programme FPL managers
solve: 15 players (2/5/5/3), at most 3 a club, a 100.0 budget, the best XI in a legal
formation plus a captain, solved with scipy's HiGHS MILP.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np

from oddsmarkets.football.analytics import value as V

logger = logging.getLogger(__name__)

POS = ("G", "D", "M", "F")
POS_LABEL = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward"}
GOAL_PTS = {"G": 10.0, "D": 6.0, "M": 5.0, "F": 4.0}
CS_PTS = {"G": 4.0, "D": 4.0, "M": 1.0, "F": 0.0}
ASSIST_PTS = 3.0
DC_THRESHOLD = {"D": ("cbit", 10.0), "M": ("cbirt", 12.0), "F": ("cbirt", 12.0)}
DC_PTS = 2.0
BONUS = (3.0, 2.0, 1.0)
SCORING = {
    "minutes": "1 for 1-59 minutes, 2 for 60+", "goal": GOAL_PTS, "assist": ASSIST_PTS, "clean_sheet": CS_PTS,
    "goals_conceded": "-1 per 2 conceded on the pitch (G, D)", "saves": "1 per 3 saves", "yellow": -1, "red": -3,
    "own_goal": -2, "penalty_missed": -2,
    "defensive_contribution": "2 for 10+ clearances, blocks, interceptions and tackles (D); 12+ including recoveries (M, F)",
    "bonus": "3, 2, 1 to the three best Sofascore ratings in the match (stand-in for FPL's bonus points)",
    "not_scored": "penalty saves (the incidents do not tell a save from a miss)",
}
PRICE_RANGE = {"G": (4.0, 6.0), "D": (4.0, 7.5), "M": (4.5, 13.0), "F": (4.5, 14.5)}
PRICE_POWER = 1.6
BUDGET = 100.0
SQUAD = {"G": 2, "D": 5, "M": 5, "F": 3}
XI_MIN = {"G": 1, "D": 3, "M": 2, "F": 1}
XI_MAX = {"G": 1, "D": 5, "M": 5, "F": 3}
PER_CLUB = 3
BENCH_WEIGHT = 0.1
HORIZON = 5                      # gameweeks the squad and the "next 5" columns cover
FDR_GWS = 6
TAU_RATES = 180.0                # days: recency weighting of per-90 rates
TAU_MIN = 60.0                   # days: recency weighting of minutes
SPAN = 365
PRIOR_90S = {"g": 6.0, "a": 6.0, "sv": 4.0, "yc": 8.0, "rc": 20.0, "og": 30.0, "pm": 30.0, "bonus": 6.0}
DC_PRIOR_APPS = 4.0
MIN_PRIOR = (3.0, 30.0, 0.25, 0.45)      # pseudo-matches, minutes, p60, p1 for a player new to his club
PRIOR_SPAN = 120                         # days: the player's own record at the club that the minutes shrink toward
MIN_PRIOR_WEIGHT = 1.0                   # recency-weighted matches the player's own 12-month record at the club is worth
BIG = 1 << 22


def _r(x, n=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, n) if math.isfinite(f) else None


# ── actual points ────────────────────────────────────────────────────────────

def fantasy_positions(R: V.Rows, people: dict[str, dict]) -> np.ndarray:
    """Per line, the player's fantasy position index into POS: his Sofascore letter, else the line's."""
    out = np.full(len(R), 2, dtype=np.int64)
    cache: dict[int, int] = {}
    for i, (pid, let) in enumerate(zip(R.pid.tolist(), R.letter.tolist())):
        p = cache.get(pid)
        if p is None:
            letter = (people.get(str(pid)) or {}).get("pos")
            p = POS.index(letter) if letter in POS else -1
            cache[pid] = p
        out[i] = p if p >= 0 else (let if let >= 0 else 2)
    return out


def bonus_points(R: V.Rows) -> np.ndarray:
    """3/2/1 to the three best ratings in each match (ties share the higher award)."""
    out = np.zeros(len(R))
    if not len(R):
        return out
    rt = np.where(np.isfinite(R.rating), R.rating, -1.0)
    order = np.lexsort((-rt, R.match))
    m = R.match[order]
    starts = np.r_[0, np.flatnonzero(np.diff(m)) + 1]
    ends = np.r_[starts[1:], m.size]
    for a, b in zip(starts.tolist(), ends.tolist()):
        prev, award_i = None, -1
        for k in range(a, min(b, a + 6)):
            r = rt[order[k]]
            if r <= 0:
                break
            if r != prev:
                award_i = k - a
                prev = r
            if award_i >= 3:
                break
            out[order[k]] = BONUS[award_i]
    return out


def _k(name: str) -> int:
    return V.FANTASY_KEYS.index(name)


def points_components(R: V.Rows, pos: np.ndarray, bonus: np.ndarray) -> dict[str, np.ndarray]:
    """Per line, each scoring component of the actual points."""
    F = R.F if R.F is not None else np.zeros((len(R), V.NFF))
    mins = R.mins
    played = mins > 0
    p60 = mins >= 60
    letter = np.array(POS)[pos]
    gp = np.array([GOAL_PTS[x] for x in POS])[pos]
    csp = np.array([CS_PTS[x] for x in POS])[pos]
    gk_def = (pos == 0) | (pos == 1)
    gc = F[:, _k("gc")]
    dc = np.zeros(len(R))
    for p, (col, thr) in DC_THRESHOLD.items():
        sel = letter == p
        dc[sel] = np.where(F[sel, _k(col)] >= thr, DC_PTS, 0.0)
    return {
        "app": played * 1.0 + p60 * 1.0,
        "goals": F[:, _k("g")] * gp,
        "assists": F[:, _k("a")] * ASSIST_PTS,
        "cs": np.where(p60 & (gc < 0.5), csp, 0.0),
        "gc": np.where(gk_def, -np.floor(gc / 2.0 + 1e-9), 0.0),
        "saves": np.floor(F[:, _k("sv")] / 3.0 + 1e-9),
        "cards": -F[:, _k("yc")] - 3.0 * F[:, _k("rc")],
        "og_pm": -2.0 * F[:, _k("og")] - 2.0 * F[:, _k("pm")],
        "dc": dc,
        "bonus": bonus,
    }


def actual_points(R: V.Rows, pos: np.ndarray, bonus: np.ndarray) -> np.ndarray:
    return sum(points_components(R, pos, bonus).values())


def _pois_floor_half(mu: np.ndarray) -> np.ndarray:
    """E[floor(X / 2)] for X ~ Poisson(mu)."""
    mu = np.maximum(np.asarray(mu, dtype=float), 0.0)
    return np.maximum(mu / 2.0 - 0.25 * (1.0 - np.exp(-2.0 * mu)), 0.0)


def _pois_floor_third(mu: np.ndarray) -> np.ndarray:
    """E[floor(X / 3)] for X ~ Poisson(mu), by summation (mu is small)."""
    mu = np.maximum(np.asarray(mu, dtype=float), 0.0)
    k = np.arange(0, 40)
    logp = -mu[..., None] + k * np.log(np.maximum(mu[..., None], 1e-12)) - np.array([math.lgamma(x + 1) for x in k])
    return (np.exp(logp) * np.floor(k / 3.0)).sum(axis=-1)


def underlying_points(R: V.Rows, pos: np.ndarray, bonus: np.ndarray) -> np.ndarray:
    """
    Per line, the points the underlying numbers were worth: goals and assists at xG and xA,
    the clean sheet and goals conceded at the opponent's expected goals while he was on (the
    side's xG against x his share of the match); minutes, saves, cards, bonus and defensive
    contributions as they happened. Actual minus underlying is luck (finishing, conversion).
    """
    comp = points_components(R, pos, bonus)
    F = R.F if R.F is not None else np.zeros((len(R), V.NFF))
    opp_xg = R.m_npxg[R.match, 1 - R.side] if len(R) else np.zeros(0)
    share = np.minimum(R.mins, 90.0) / 90.0
    mu = opp_xg * share
    gp = np.array([GOAL_PTS[x] for x in POS])[pos]
    csp = np.array([CS_PTS[x] for x in POS])[pos]
    gk_def = (pos == 0) | (pos == 1)
    out = comp["app"] + comp["saves"] + comp["cards"] + comp["og_pm"] + comp["dc"] + comp["bonus"]
    out = out + F[:, _k("xg")] * gp + F[:, _k("xa")] * ASSIST_PTS
    out = out + np.where(R.mins >= 60, csp * np.exp(-mu), 0.0) - np.where(gk_def, _pois_floor_half(mu), 0.0)
    return out


# ── rates at a cutoff, vectorised over players ───────────────────────────────

class RateIndex:
    """Recency-weighted sums of each player's club lines before any cutoff day, and the minutes model."""

    COLS = ("m90", "g", "xg", "a", "xa", "sv", "yc", "rc", "og", "pm", "bonus", "apps60", "dc_hit", "pts")

    def __init__(self, R: V.Rows, pos: np.ndarray, bonus: np.ndarray, pts: np.ndarray, league_comps: set[int]) -> None:
        club = V._club_rows(R)
        rows = np.flatnonzero(club)
        order = rows[np.lexsort((R.day[rows], R.pid[rows]))]
        self.rows = order
        self.pid = R.pid[order]
        self.day = R.day[order]
        self.tid = R.tid[order]
        self.D0 = int(R.day.max()) if len(R) else 0
        u, inv = np.unique(self.pid, return_inverse=True)
        self.pids = u
        self.pidx = {int(p): i for i, p in enumerate(u.tolist())}
        self.keys = inv.astype(np.int64) * BIG + (self.day - (self.D0 - BIG // 2))
        F = R.F[order] if R.F is not None else np.zeros((order.size, V.NFF))
        mins = R.mins[order]
        # xG-based rates only from matches that have xG (older-format matches carry none).
        has_xg = (R.m_npxg[R.match[order]].sum(axis=1) > 0) if order.size else np.zeros(0, dtype=bool)
        letter = np.array(POS)[pos[order]] if order.size else np.zeros(0, dtype="<U1")
        dc_hit = np.zeros(order.size)
        for p, (col, thr) in DC_THRESHOLD.items():
            sel = letter == p
            dc_hit[sel] = (F[sel, _k(col)] >= thr) & (mins[sel] >= 60)
        cols = {
            "m90": mins / 90.0, "g": F[:, _k("g")], "a": F[:, _k("a")], "sv": F[:, _k("sv")], "yc": F[:, _k("yc")],
            "rc": F[:, _k("rc")], "og": F[:, _k("og")], "pm": F[:, _k("pm")], "bonus": bonus[order], "apps60": (mins >= 60) * 1.0,
            "dc_hit": dc_hit, "pts": pts[order],
            "xg": np.where(has_xg, F[:, _k("xg")], 0.0), "xa": np.where(has_xg, F[:, _k("xa")], 0.0),
            "m90x": np.where(has_xg, mins / 90.0, 0.0),
        }
        self.ew = np.exp((self.day - self.D0) / TAU_RATES)
        self.C = {k: np.r_[0.0, np.cumsum(v * self.ew)] for k, v in cols.items()}
        self.Cn = {k: np.r_[0.0, np.cumsum(v)] for k, v in cols.items()}      # unweighted, for the baselines
        # Minutes: league lines per (player, club), against the club's league matches.
        is_lg = np.array([c in league_comps for c in R.comp[order].tolist()], dtype=bool) if order.size else np.zeros(0, dtype=bool)
        lg = np.flatnonzero(is_lg)
        pt = self.pid[lg].astype(np.int64) * (1 << 24) + np.maximum(self.tid[lg], 0)
        o2 = np.lexsort((self.day[lg], pt))
        lg = lg[o2]
        pt = pt[o2]
        upt, inv2 = np.unique(pt, return_inverse=True)
        self.pt_index = {int(k): i for i, k in enumerate(upt.tolist())}
        self.pt_keys = inv2.astype(np.int64) * BIG + (self.day[lg] - (self.D0 - BIG // 2))
        self.pt_day = self.day[lg]
        mw = np.exp((self.day[lg] - self.D0) / TAU_MIN)
        self.pt_mw = mw
        lm = mins[lg]
        self.CM = {"min": np.r_[0.0, np.cumsum(lm * mw)], "p60": np.r_[0.0, np.cumsum((lm >= 60) * mw)],
                   "p1": np.r_[0.0, np.cumsum((lm > 0) * mw)]}
        self.CMp = {"min": np.r_[0.0, np.cumsum(lm)], "p60": np.r_[0.0, np.cumsum((lm >= 60) * 1.0)], "p1": np.r_[0.0, np.cumsum((lm > 0) * 1.0)]}
        # Each club's league match days.
        mm = [i for i, c in enumerate(R.m_comp.tolist()) if c in league_comps]
        cd: dict[int, list[int]] = {}
        for mi in mm:
            for s in (0, 1):
                cd.setdefault(int(R.m_tid[mi, s]), []).append(int(R.m_day[mi]))
        cl = sorted(cd)
        self.cidx = {c: i for i, c in enumerate(cl)}
        ck, cdays = [], []
        for i, c in enumerate(cl):
            ds = np.sort(np.array(cd[c]))
            ck.append(i * BIG + (ds - (self.D0 - BIG // 2)))
            cdays.append(ds)
        self.c_keys = np.concatenate(ck) if ck else np.zeros(0, dtype=np.int64)
        cdays_all = np.concatenate(cdays) if cdays else np.zeros(0)
        self.c_cum = np.r_[0.0, np.cumsum(np.exp((cdays_all - self.D0) / TAU_MIN))]
        self.c_cnt = np.arange(cdays_all.size + 1, dtype=float)
        # Position means of each rate (all club lines, unweighted), for shrinkage.
        self.pos_mean: dict[str, dict[str, float]] = {}
        letters_all = letter
        for p in POS:
            sel = letters_all == p
            m90 = cols["m90"][sel].sum()
            m90x = cols["m90x"][sel].sum()
            apps60 = cols["apps60"][sel].sum()
            self.pos_mean[p] = {k: (cols[k][sel].sum() / (m90x if k in ("xg", "xa") else m90)) if (m90x if k in ("xg", "xa") else m90) > 0 else 0.0
                                for k in ("g", "xg", "a", "xa", "sv", "yc", "rc", "og", "pm", "bonus")}
            self.pos_mean[p]["dc"] = (cols["dc_hit"][sel].sum() / apps60) if apps60 > 0 else 0.0
        all_m90 = cols["m90x"].sum()
        self.g_per_xg = float(cols["g"][cols["m90x"] > 0].sum() / max(cols["xg"].sum(), 1e-9)) if all_m90 > 0 else 1.0
        self.a_per_xa = float(cols["a"][cols["m90x"] > 0].sum() / max(cols["xa"].sum(), 1e-9)) if all_m90 > 0 else 1.0

    def _range(self, pidx: np.ndarray, D: int, span: int = SPAN) -> tuple[np.ndarray, np.ndarray]:
        base = pidx.astype(np.int64) * BIG - (self.D0 - BIG // 2)
        i = np.searchsorted(self.keys, base + (D - span), "left")
        j = np.searchsorted(self.keys, base + D, "left")
        return i, j

    def weighted(self, pidx: np.ndarray, D: int, span: int = SPAN) -> dict[str, np.ndarray]:
        i, j = self._range(pidx, D, span)
        scale = math.exp((self.D0 - D) / TAU_RATES)
        return {k: (c[j] - c[i]) * scale for k, c in self.C.items()}

    def plain(self, pidx: np.ndarray, D0: int, D1: int) -> dict[str, np.ndarray]:
        base = pidx.astype(np.int64) * BIG - (self.D0 - BIG // 2)
        i = np.searchsorted(self.keys, base + D0, "left")
        j = np.searchsorted(self.keys, base + D1, "left")
        return {k: (c[j] - c[i]) for k, c in self.Cn.items()}

    def last_club(self, pidx: np.ndarray, D: int) -> np.ndarray:
        """The club of each player's latest club line before D (-1 when none in the span)."""
        i, j = self._range(pidx, D)
        out = np.full(pidx.size, -1, dtype=np.int64)
        ok = j > i
        out[ok] = self.tid[j[ok] - 1]
        return out

    def club_matches(self, tids: np.ndarray, d0: np.ndarray, D: int, weighted: bool = True) -> np.ndarray:
        """Count (recency-weighted, or plain) of each club's league matches on days d0 <= day < D."""
        ci = np.array([self.cidx.get(int(t), -1) for t in tids.tolist()], dtype=np.int64)
        base = np.maximum(ci, 0) * BIG - (self.D0 - BIG // 2)
        i = np.searchsorted(self.c_keys, base + d0, "left")
        j = np.searchsorted(self.c_keys, base + D, "left")
        out = (self.c_cum[j] - self.c_cum[i]) * math.exp((self.D0 - D) / TAU_MIN) if weighted else (self.c_cnt[j] - self.c_cnt[i])
        return np.where(ci >= 0, out, 0.0)

    def minutes(self, pids: np.ndarray, tids: np.ndarray, D: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(expected minutes, p60, p1, weighted club matches) at club `tids` before D, shrunk for newcomers."""
        n = pids.size
        k = np.array([self.pt_index.get(int(p) * (1 << 24) + max(int(t), 0), -1) for p, t in zip(pids.tolist(), tids.tolist())],
                     dtype=np.int64)
        base = np.maximum(k, 0) * BIG - (self.D0 - BIG // 2)
        i = np.searchsorted(self.pt_keys, base + (D - SPAN), "left")
        j = np.searchsorted(self.pt_keys, base + D, "left")
        has = (k >= 0) & (j > i)
        first = np.where(has, self.pt_day[np.minimum(i, self.pt_day.size - 1)] if self.pt_day.size else 0, D)
        scale = math.exp((self.D0 - D) / TAU_MIN)
        sm = np.where(has, (self.CM["min"][j] - self.CM["min"][i]) * scale, 0.0)
        s60 = np.where(has, (self.CM["p60"][j] - self.CM["p60"][i]) * scale, 0.0)
        s1 = np.where(has, (self.CM["p1"][j] - self.CM["p1"][i]) * scale, 0.0)
        nm = np.where(has, self.club_matches(tids, first, D), 0.0)
        nm = np.maximum(nm, np.where(has, s1, 0.0))
        k0, m0, p60_0, p1_0 = MIN_PRIOR
        # The prior: his own unweighted record at the club over the last PRIOR_SPAN days (itself shrunk to a newcomer's
        # bench role), so a regular early in a season is not dragged toward the bench by thin recent weights.
        ip = np.searchsorted(self.pt_keys, base + (D - PRIOR_SPAN), "left")
        hp = (k >= 0) & (j > ip)
        pm = np.where(hp, self.CMp["min"][j] - self.CMp["min"][ip], 0.0)
        p6 = np.where(hp, self.CMp["p60"][j] - self.CMp["p60"][ip], 0.0)
        pa = np.where(hp, self.CMp["p1"][j] - self.CMp["p1"][ip], 0.0)
        npl = np.maximum(np.where(has, self.club_matches(tids, np.maximum(first, D - PRIOR_SPAN), D, weighted=False), 0.0), pa)
        m0 = (pm + k0 * m0) / (npl + k0)
        p60_0 = (p6 + k0 * p60_0) / (npl + k0)
        p1_0 = (pa + k0 * p1_0) / (npl + k0)
        kw = MIN_PRIOR_WEIGHT
        e_min = (sm + kw * m0) / (nm + kw)
        p60 = (s60 + kw * p60_0) / (nm + kw)
        p1 = (s1 + kw * p1_0) / (nm + kw)
        del n
        return e_min, np.clip(p60, 0, 1), np.clip(np.maximum(p1, p60), 0, 1), nm

    def rates(self, pidx: np.ndarray, letters: np.ndarray, D: int) -> dict[str, np.ndarray]:
        """Per-90 rates shrunk to the position (goals and assists blend the expected and the actual)."""
        w = self.weighted(pidx, D)
        out: dict[str, np.ndarray] = {}
        mean = {k: np.array([self.pos_mean[p][k] for p in letters.tolist()]) for k in ("g", "xg", "a", "xa", "sv", "yc", "rc", "og", "pm", "bonus", "dc")}
        m90, m90x = w["m90"], w["m90x"]
        for k in ("sv", "yc", "rc", "og", "pm", "bonus"):
            out[k] = (w[k] + PRIOR_90S[k] * mean[k]) / (m90 + PRIOR_90S[k])
        xg = (w["xg"] * self.g_per_xg + PRIOR_90S["g"] * mean["xg"] * self.g_per_xg) / (m90x + PRIOR_90S["g"])
        g = (w["g"] + PRIOR_90S["g"] * mean["g"]) / (m90 + PRIOR_90S["g"])
        out["g"] = np.where(m90x > 0, 0.7 * xg + 0.3 * g, g)
        xa = (w["xa"] * self.a_per_xa + PRIOR_90S["a"] * mean["xa"] * self.a_per_xa) / (m90x + PRIOR_90S["a"])
        a = (w["a"] + PRIOR_90S["a"] * mean["a"]) / (m90 + PRIOR_90S["a"])
        out["a"] = np.where(m90x > 0, 0.7 * xa + 0.3 * a, a)
        out["dc"] = (w["dc_hit"] + DC_PRIOR_APPS * mean["dc"]) / (w["apps60"] + DC_PRIOR_APPS)
        out["m90"] = m90
        return out


# ── projections ──────────────────────────────────────────────────────────────

def project_points(letters: np.ndarray, rates: dict[str, np.ndarray], e_min: np.ndarray, p60: np.ndarray, p1: np.ndarray,
                   lam_for: np.ndarray, lam_against: np.ndarray, lam_for_mean: np.ndarray, lam_against_mean: np.ndarray) -> dict[str, np.ndarray]:
    """Expected points of each player in one fixture, by component."""
    m = np.minimum(e_min, 95.0) / 90.0
    s_att = np.clip(lam_for / np.maximum(lam_for_mean, 0.1), 0.3, 3.0)
    s_def = np.clip(lam_against / np.maximum(lam_against_mean, 0.1), 0.3, 3.0)
    gp = np.array([GOAL_PTS[x] for x in letters.tolist()])
    csp = np.array([CS_PTS[x] for x in letters.tolist()])
    gk_def = np.isin(letters, ("G", "D"))
    is_gk = letters == "G"
    cs_prob = np.exp(-lam_against)
    on_share = np.where(p60 > 0, np.clip(e_min / np.maximum(p1, 0.05) / 90.0, 0, 1), 0.0)
    # Bonus follows the attack for midfielders and forwards, the clean sheet for the back line.
    bonus_scale = np.where(gk_def, 0.5 + 0.5 * cs_prob / np.maximum(np.exp(-lam_against_mean), 0.05), 0.5 + 0.5 * s_att)
    out = {
        "app": p1 + p60,
        "goals": rates["g"] * s_att * m * gp,
        "assists": rates["a"] * s_att * m * ASSIST_PTS,
        "cs": p60 * cs_prob * csp,
        "gc": -np.where(gk_def, p1 * _pois_floor_half(lam_against * on_share), 0.0),
        "saves": np.where(is_gk, p1 * _pois_floor_third(rates["sv"] * s_def * np.where(p1 > 0, m / np.maximum(p1, 0.05), 0.0)), 0.0),
        "cards": -(rates["yc"] + 3.0 * rates["rc"]) * m,
        "og_pm": -2.0 * (rates["og"] + rates["pm"]) * m,
        "dc": np.where(is_gk, 0.0, DC_PTS * rates["dc"] * p60),
        "bonus": rates["bonus"] * m * bonus_scale,
    }
    return out


def total(comp: dict[str, np.ndarray]) -> np.ndarray:
    return sum(comp.values())


# ── gameweeks ────────────────────────────────────────────────────────────────

def _day(s: str | None) -> int | None:
    try:
        return date.fromisoformat(str(s)[:10]).toordinal()
    except (TypeError, ValueError):
        return None


def gameweeks(fixtures: list[dict], today: date, n: int | None = None) -> list[dict]:
    """
    Upcoming fixtures grouped into gameweeks: by round where the league numbers them (a fixture
    more than four days from its round's median date is a rescheduled one and joins the gameweek
    whose dates it falls in), else by week (Monday to Sunday). [{gw, label, start, end, fixtures}].
    """
    t0 = today.toordinal()
    up = [f for f in fixtures if f.get("hs") is None and str(f.get("status") or "") not in ("finished", "canceled", "cancelled")
          and (_day(f.get("date")) or 0) >= t0 and (f.get("model") or {}).get("lh") is not None and f.get("stage", "league") == "league"]
    if not up:
        return []
    rounds = [f.get("round") for f in up]
    groups: dict[Any, list[dict]] = {}
    if sum(1 for r in rounds if r is not None) >= 0.8 * len(up):
        for f in up:
            groups.setdefault(("r", f.get("round")), []).append(f)
        med = {k: float(np.median([_day(f["date"]) for f in v])) for k, v in groups.items()}
        moved = []
        for k, v in list(groups.items()):
            keep = [f for f in v if abs(_day(f["date"]) - med[k]) <= 4]
            moved += [f for f in v if abs(_day(f["date"]) - med[k]) > 4]
            groups[k] = keep
        groups = {k: v for k, v in groups.items() if v}
        # A round of a few rescheduled matches inside a full round's dates joins that round (a double gameweek).
        typical = float(np.median([len(v) for v in groups.values()]))
        for k in sorted(groups, key=lambda k_: len(groups[k_])):
            v = groups[k]
            if not (len(v) < 0.5 * typical or (len(v) == 1 and typical >= 2)):
                continue
            for k2, v2 in groups.items():
                if k2 == k or len(v2) <= len(v):
                    continue
                a, b = min(_day(f["date"]) for f in v2), max(_day(f["date"]) for f in v2)
                if all(a - 1 <= _day(f["date"]) <= b + 1 for f in v):
                    v2.extend(v)
                    groups[k] = []
                    break
        groups = {k: v for k, v in groups.items() if v}
        spans = {k: (min(_day(f["date"]) for f in v), max(_day(f["date"]) for f in v)) for k, v in groups.items()}
        for f in moved:
            d = _day(f["date"])
            host = next((k for k, (a, b) in sorted(spans.items(), key=lambda kv: kv[1][0]) if a - 1 <= d <= b + 1), None)
            if host is None:
                host = ("w", date.fromordinal(d).isocalendar()[:2])
                spans[host] = (d, d)
            groups.setdefault(host, []).append(f)
    else:
        for f in up:
            groups.setdefault(("w", date.fromordinal(_day(f["date"])).isocalendar()[:2]), []).append(f)
    out = []
    for k, v in groups.items():
        days = [_day(f["date"]) for f in v]
        out.append({"key": k, "start": min(days), "end": max(days), "fixtures": sorted(v, key=lambda f: f["date"])})
    out.sort(key=lambda g: g["start"])
    for i, g in enumerate(out):
        g["gw"] = i + 1
        rk = g["key"]
        g["label"] = (f"Round {rk[1]}" if rk[0] == "r" else "Week of " + date.fromordinal(g["start"]).strftime("%d %b")) + \
            " · " + date.fromordinal(g["start"]).strftime("%d %b") + ("" if g["start"] == g["end"] else "-" + date.fromordinal(g["end"]).strftime("%d %b"))
        del g["key"]
    return out[:n] if n else out


# ── prices ───────────────────────────────────────────────────────────────────

def price_proxy(letters: np.ndarray, score: np.ndarray) -> np.ndarray:
    """
    Our price, by position within the league: the player's value score (expected points above
    replacement next season) ranked among the league's players at his position, mapped onto
    FPL-like ranges as lo + (hi - lo) x q^1.6, to 0.1.
    """
    out = np.zeros(letters.size)
    for p in POS:
        sel = np.flatnonzero(letters == p)
        if not sel.size:
            continue
        s = score[sel]
        q = (np.argsort(np.argsort(s)) + 0.5) / sel.size
        lo, hi = PRICE_RANGE[p]
        out[sel] = np.round(lo + (hi - lo) * q ** PRICE_POWER, 1)
    return out


# ── the squad ────────────────────────────────────────────────────────────────

def optimise_squad(letters: list[str], clubs: list[int], prices: np.ndarray, horizon_pts: np.ndarray, next_pts: np.ndarray,
                   budget: float = BUDGET) -> dict | None:
    """
    The FPL problem as an integer programme (scipy's HiGHS): 15 players (2/5/5/3), at most three a
    club, within the budget, maximising the starting XI's points over the horizon plus a tenth of
    the bench's, plus the captain's next-gameweek points again. None when infeasible or no solver.
    """
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
    except ImportError:
        return None
    n = len(letters)
    if n < 15:
        return None
    # x (squad), s (starter), c (captain): 3n binaries.
    obj = np.concatenate([BENCH_WEIGHT * horizon_pts, (1 - BENCH_WEIGHT) * horizon_pts, next_pts])
    rows, lo, hi = [], [], []

    def add(coef_x=None, coef_s=None, coef_c=None, l=-np.inf, h=np.inf):
        r = np.zeros(3 * n)
        if coef_x is not None:
            r[:n] = coef_x
        if coef_s is not None:
            r[n:2 * n] = coef_s
        if coef_c is not None:
            r[2 * n:] = coef_c
        rows.append(r)
        lo.append(l)
        hi.append(h)

    L = np.array(letters)
    add(coef_x=np.ones(n), l=15, h=15)
    add(coef_s=np.ones(n), l=11, h=11)
    add(coef_c=np.ones(n), l=1, h=1)
    add(coef_x=prices, h=budget)
    for p in POS:
        ind = (L == p).astype(float)
        add(coef_x=ind, l=SQUAD[p], h=SQUAD[p])
        add(coef_s=ind, l=XI_MIN[p], h=XI_MAX[p])
    for c in set(clubs):
        ind = np.array([1.0 if x == c else 0.0 for x in clubs])
        add(coef_x=ind, h=PER_CLUB)
    A = np.array(rows)
    # s <= x and c <= s, as rows of their own.
    link = np.zeros((2 * n, 3 * n))
    for i in range(n):
        link[i, n + i] = 1.0
        link[i, i] = -1.0
        link[n + i, 2 * n + i] = 1.0
        link[n + i, n + i] = -1.0
    cons = [LinearConstraint(A, np.array(lo), np.array(hi)), LinearConstraint(link, -np.inf, 0.0)]
    try:
        res = milp(c=-obj, constraints=cons, integrality=np.ones(3 * n), bounds=Bounds(0, 1),
                   options={"time_limit": 20.0, "mip_rel_gap": 1e-4})
    except Exception as exc:  # noqa: BLE001
        logger.warning("fantasy: squad solver failed: %s", exc)
        return None
    if res.x is None:
        return None
    x = res.x[:n] > 0.5
    s = res.x[n:2 * n] > 0.5
    c = res.x[2 * n:] > 0.5
    return {"squad": np.flatnonzero(x).tolist(), "xi": np.flatnonzero(s).tolist(), "captain": int(np.flatnonzero(c)[0]) if c.any() else None,
            "cost": float(prices[x].sum()), "objective": float(-res.fun), "status": int(res.status)}


def greedy_squad(letters: list[str], clubs: list[int], prices: np.ndarray, horizon_pts: np.ndarray, budget: float = BUDGET) -> list[int]:
    """A fallback without a solver: best points per price first, within every constraint."""
    need = dict(SQUAD)
    per_club: dict[int, int] = {}
    cheapest = {p: sorted(prices[np.array(letters) == p])[:SQUAD[p]] for p in POS}
    left = budget
    out: list[int] = []
    for i in np.argsort(-(horizon_pts / np.maximum(prices - 3.5, 0.5))).tolist():
        p = letters[i]
        if need[p] == 0 or per_club.get(clubs[i], 0) >= PER_CLUB:
            continue
        reserve = sum(sum(cheapest[q][:need[q] - (1 if q == p else 0)]) for q in POS)
        if prices[i] + reserve > left + 1e-9:
            continue
        out.append(i)
        need[p] -= 1
        per_club[clubs[i]] = per_club.get(clubs[i], 0) + 1
        left -= prices[i]
        if not any(need.values()):
            break
    return out


# ── the walk-forward backtest ────────────────────────────────────────────────

def league_rounds(R: V.Rows, ci: int) -> list[tuple[int, list[int]]]:
    """A league's matches grouped into rounds: consecutive match days, a new round after a gap of 2+ days."""
    ms = np.flatnonzero(R.m_comp == ci)
    if not ms.size:
        return []
    ms = ms[np.argsort(R.m_day[ms], kind="stable")]
    out: list[tuple[int, list[int]]] = []
    cur: list[int] = []
    last = None
    for mi in ms.tolist():
        d = int(R.m_day[mi])
        if last is not None and d - last >= 2 and cur:
            out.append((int(R.m_day[cur[0]]), cur))
            cur = []
        cur.append(mi)
        last = d
    if cur:
        out.append((int(R.m_day[cur[0]]), cur))
    return out


def proxy_lambdas(R: V.Rows, ci: int, D: int, teams: np.ndarray) -> tuple[dict[int, float], dict[int, float], float, float]:
    """
    Walk-forward team strengths for the backtest (past fixtures keep no model line): each team's
    recency-weighted non-penalty xG for and against per league match before D, shrunk by five
    matches to the league average, as attack and defence multipliers; the league's mean home and
    away goals. Expected goals = mean goals x attack x the opponent's defence.
    """
    ms = np.flatnonzero((R.m_comp == ci) & (R.m_day < D) & (R.m_day >= D - SPAN))
    if ms.size < 10:
        return {}, {}, 1.45, 1.15
    w = np.exp((R.m_day[ms] - D) / 120.0)
    xg = R.m_npxg[ms]
    g = R.m_goals[ms]
    mu_h, mu_a = float(np.average(g[:, 0], weights=w)), float(np.average(g[:, 1], weights=w))
    avg = float(np.average(xg.mean(axis=1), weights=w)) or 1.0
    att: dict[int, float] = {}
    dfn: dict[int, float] = {}
    for t in set(teams.tolist()):
        f_ = np.concatenate([xg[R.m_tid[ms, 0] == t, 0], xg[R.m_tid[ms, 1] == t, 1]])
        a_ = np.concatenate([xg[R.m_tid[ms, 0] == t, 1], xg[R.m_tid[ms, 1] == t, 0]])
        ww = np.concatenate([w[R.m_tid[ms, 0] == t], w[R.m_tid[ms, 1] == t]])
        k = 5.0
        att[t] = ((f_ * ww).sum() + k * avg) / (ww.sum() + k) / avg
        dfn[t] = ((a_ * ww).sum() + k * avg) / (ww.sum() + k) / avg
    return att, dfn, mu_h, mu_a


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 10 or np.all(a == a[0]) or np.all(b == b[0]):
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def backtest(R: V.Rows, RI: RateIndex, pos_row: np.ndarray, pts: np.ndarray, leagues: list[str], min_history_days: int = 28) -> dict:
    """
    Walk-forward: for every round of every league with line-ups, project each player of the
    round's clubs (his latest club line before the round) from earlier matches only, and score
    the projection against the points his line-ups earned in the round (0 when he did not play).
    Baselines from the same earlier matches: points per club league match this season, over
    his club's last five league matches, and over the last 365 days.
    """
    t0 = datetime.now(timezone.utc)
    pid_letter: dict[int, str] = {}
    for p, l in zip(R.pid.tolist(), pos_row.tolist()):
        pid_letter[p] = POS[l]
    all_pidx = np.arange(RI.pids.size)
    all_letters = np.array([pid_letter.get(int(p), "M") for p in RI.pids.tolist()])
    # League lines per player for the baselines: (day, points, season key), in date order.
    res = {"model": [], "std": [], "last5": [], "y365": [], "actual": [], "pos": [], "league": [], "round_ids": []}
    per_round_rho = {"model": [], "std": [], "last5": [], "y365": []}
    top_pts = {"model": [], "std": [], "last5": [], "y365": []}
    n_rounds = 0
    raw_sum = act_sum = 0.0
    collected = []                     # (first day, league, arrays) per round, calibrated afterwards in date order
    for slug in leagues:
        if slug not in R.comps:
            continue
        ci = R.comps.index(slug)
        lg_rows = np.flatnonzero(R.comp == ci)
        by_pid: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        if lg_rows.size:
            o = lg_rows[np.lexsort((R.day[lg_rows], R.pid[lg_rows]))]
            pids_o = R.pid[o]
            starts = np.r_[0, np.flatnonzero(np.diff(pids_o)) + 1]
            ends = np.r_[starts[1:], o.size]
            for a, b in zip(starts.tolist(), ends.tolist()):
                rr = o[a:b]
                by_pid[int(pids_o[a])] = (R.day[rr], pts[rr], R.sid[rr], R.match[rr])
        club_days: dict[int, np.ndarray] = {}
        lm = np.flatnonzero(R.m_comp == ci)
        for s in (0, 1):
            for t in set(R.m_tid[lm, s].tolist()):
                pass
        cd: dict[int, list[int]] = {}
        for mi in lm.tolist():
            for s in (0, 1):
                cd.setdefault(int(R.m_tid[mi, s]), []).append(int(R.m_day[mi]))
        club_days = {t: np.sort(np.array(v)) for t, v in cd.items()}
        rounds = league_rounds(R, ci)
        first_day = int(R.m_day[lm].min()) if lm.size else 0
        for D, mlist in rounds:
            if D - first_day < min_history_days or len(mlist) < 3:
                continue
            teams = R.m_tid[mlist].ravel()
            att, dfn, mu_h, mu_a = proxy_lambdas(R, ci, D, teams)
            if not att:
                continue
            last = RI.last_club(all_pidx, D)
            cand = np.flatnonzero(np.isin(last, teams))
            if cand.size < 20:
                continue
            tids = last[cand]
            letters = all_letters[cand]
            rates = RI.rates(cand, letters, D)
            e_min, p60, p1, _ = RI.minutes(RI.pids[cand], tids, D)
            # Each candidate's fixture(s) in the round.
            lam_f = np.zeros(cand.size)
            lam_a = np.zeros(cand.size)
            proj = np.zeros(cand.size)
            mean_f = np.array([att.get(int(t), 1.0) * (mu_h + mu_a) / 2 for t in tids.tolist()])
            mean_a = np.array([dfn.get(int(t), 1.0) * (mu_h + mu_a) / 2 for t in tids.tolist()])
            for mi in mlist:
                h, a = int(R.m_tid[mi, 0]), int(R.m_tid[mi, 1])
                lh = mu_h * att.get(h, 1.0) * dfn.get(a, 1.0)
                la = mu_a * att.get(a, 1.0) * dfn.get(h, 1.0)
                for team, lf, lag in ((h, lh, la), (a, la, lh)):
                    sel = tids == team
                    if not sel.any():
                        continue
                    lam_f[sel] = lf
                    lam_a[sel] = lag
                    comp = project_points(letters[sel], {k: v[sel] for k, v in rates.items()}, e_min[sel], p60[sel], p1[sel],
                                          lam_f[sel], lam_a[sel], mean_f[sel], mean_a[sel])
                    proj[sel] += total(comp)
            mset = set(int(m) for m in mlist)
            actual = np.zeros(cand.size)
            std = np.zeros(cand.size)
            l5 = np.zeros(cand.size)
            y365 = np.zeros(cand.size)
            for k, p in enumerate(RI.pids[cand].tolist()):
                rec = by_pid.get(int(p))
                cdays = club_days.get(int(tids[k]))
                if rec is not None:
                    days, pp, sids, mts = rec
                    j = int(np.searchsorted(days, D, "left"))
                    j2 = int(np.searchsorted(days, D + 7, "left"))
                    actual[k] = sum(pp[x] for x in range(j, j2) if int(mts[x]) in mset)
                    if j > 0 and cdays is not None:
                        cur_sid = sids[j - 1]
                        i_s = j - 1
                        while i_s > 0 and sids[i_s - 1] == cur_sid:
                            i_s -= 1
                        n_s = int(np.searchsorted(cdays, D) - np.searchsorted(cdays, days[i_s]))
                        std[k] = pp[i_s:j].sum() / max(n_s, 1)
                        last5_days = cdays[max(int(np.searchsorted(cdays, D)) - 5, 0):int(np.searchsorted(cdays, D))]
                        if last5_days.size:
                            lo = int(np.searchsorted(days, last5_days[0], "left"))
                            l5[k] = pp[lo:j].sum() / last5_days.size
                        i_y = int(np.searchsorted(days, D - SPAN, "left"))
                        if i_y < j:
                            n_y = int(np.searchsorted(cdays, D) - np.searchsorted(cdays, max(days[i_y], D - SPAN)))
                            y365[k] = pp[i_y:j].sum() / max(n_y, 1)
            n_rounds += 1
            collected.append((D, slug, proj, std, l5, y365, actual, letters))
    # One scale factor for the projection's level, walk-forward: each round is scaled by the ratio of
    # actual to projected points over every earlier round (any league), from the 20th round on.
    collected.sort(key=lambda c: c[0])
    for k, (D, slug, proj, std, l5, y365, actual, letters) in enumerate(collected):
        cal = (act_sum / raw_sum) if (k >= 20 and raw_sum > 0) else 1.0
        raw_sum += float(proj.sum())
        act_sum += float(actual.sum())
        proj = proj * cal
        for name, arr in (("model", proj), ("std", std), ("last5", l5), ("y365", y365)):
            res[name].append(arr)
            rho = _spearman(arr, actual)
            if rho is not None:
                per_round_rho[name].append(rho)
            top = np.argsort(-arr)[:20]
            top_pts[name].append(float(actual[top].mean()))
        res["actual"].append(actual)
        res["pos"].append(letters)
        res["league"].append(np.array([slug] * actual.size))
    if not res["actual"]:
        return {"ok": False, "reason": "no rounds with enough history"}
    A = np.concatenate(res["actual"])
    P = np.concatenate(res["pos"])
    Lg = np.concatenate(res["league"])
    out: dict[str, Any] = {"ok": True, "rounds": n_rounds, "player_rounds": int(A.size), "mean_actual": _r(A.mean(), 3), "methods": {}}
    labels = {"model": "Our projection", "std": "Season-to-date points per club match", "last5": "Last five club matches",
              "y365": "Last 365 days per club match"}
    for name in ("model", "std", "last5", "y365"):
        Pm = np.concatenate(res[name])
        bias = float(Pm.mean() - A.mean())
        out["methods"][name] = {
            "label": labels[name], "mae": _r(np.abs(Pm - A).mean(), 3), "rmse": _r(math.sqrt(float(((Pm - A) ** 2).mean())), 3),
            "bias": _r(bias, 3), "spearman_round_mean": _r(float(np.mean(per_round_rho[name])), 3) if per_round_rho[name] else None,
            "top20_actual_mean": _r(float(np.mean(top_pts[name])), 3),
            "by_position": {p: {"mae": _r(np.abs(Pm[P == p] - A[P == p]).mean(), 3), "n": int((P == p).sum())} for p in POS if (P == p).any()},
            "big5_mae": _r(np.abs(Pm[np.isin(Lg, V.BIG_FIVE)] - A[np.isin(Lg, V.BIG_FIVE)]).mean(), 3) if np.isin(Lg, V.BIG_FIVE).any() else None,
        }
    out["calibration"] = _r(min(max(act_sum / raw_sum, 0.75), 1.25), 4) if raw_sum > 0 else 1.0
    out["calibration_note"] = ("the live projections are multiplied by this ratio of actual to projected points over every backtest "
                               "round; in the backtest each round used only the earlier rounds' ratio")
    out["runtime_s"] = round((datetime.now(timezone.utc) - t0).total_seconds(), 1)
    return out


# ── the build ────────────────────────────────────────────────────────────────

def _tiers(values: np.ndarray, max_tiers: int = 6) -> np.ndarray:
    """Tiers down a sorted list: a new tier where the drop to the next player is over twice the typical drop."""
    out = np.ones(values.size, dtype=int)
    if values.size < 3:
        return out
    order = np.argsort(-values)
    v = values[order]
    drops = -np.diff(v)
    typical = float(np.median(drops[:40])) if drops.size else 0.0
    tier = 1
    for i in range(1, v.size):
        if tier < max_tiers and drops[i - 1] > max(2.0 * typical, 0.15):
            tier += 1
        out[order[i]] = tier
    return out


def build_fantasy(R: V.Rows, *, people: dict[str, dict], club_of: dict[str, dict | None], entries: list[dict],
                  value_score: dict[int, float], out_dir, today: date, comps: dict[str, dict], run_backtest: bool = True) -> dict:
    """data/fantasy/: meta.json (scoring, method, backtest) and <league>.json per followed league."""
    import json
    from pathlib import Path

    t0 = datetime.now(timezone.utc)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pos_row = fantasy_positions(R, people)
    bonus = bonus_points(R)
    pts = actual_points(R, pos_row, bonus)
    xpts = underlying_points(R, pos_row, bonus)
    league_ci = {i for i, c in enumerate(R.comps) if (comps.get(c) or {}).get("kind") == "league"}
    RI = RateIndex(R, pos_row, bonus, pts, league_ci)
    D = today.toordinal() + 1
    lg_slugs = [e["slug"] for e in entries if (comps.get(e.get("slug") or "") or {}).get("kind") == "league" and e.get("ok")]
    bt = backtest(R, RI, pos_row, pts, lg_slugs) if run_backtest else {"ok": False, "reason": "skipped"}
    cal = float(bt.get("calibration") or 1.0)
    leagues = [e for e in entries if (comps.get(e.get("slug") or "") or {}).get("kind") == "league" and e.get("ok")]
    written = []
    summary = []
    for e in leagues:
        slug = e["slug"]
        teams = {name: int(info["team_id"]) for name, info in (e.get("_teams") or {}).items() if isinstance(info, dict) and info.get("team_id")}
        tid_name = {t: n for n, t in teams.items()}
        gws = gameweeks(e.get("_fixtures") or [], today)
        if not gws or len(teams) < 4:
            continue
        # Players: the league clubs' current players (unified current club), with a club line in 12 months.
        cand = []
        for pid, cc in club_of.items():
            if cc and cc.get("tid") is not None and int(cc["tid"]) in tid_name:
                try:
                    p = int(pid)
                except ValueError:
                    continue
                if p in RI.pidx:
                    cand.append((p, int(cc["tid"])))
        if len(cand) < 40:
            continue
        pids = np.array([p for p, _ in cand])
        tids = np.array([t for _, t in cand])
        pidx = np.array([RI.pidx[p] for p in pids.tolist()])
        letters = np.array([(people.get(str(p)) or {}).get("pos") if (people.get(str(p)) or {}).get("pos") in POS else
                            POS[int(np.bincount(pos_row[R.pid == p], minlength=4).argmax())] if (R.pid == p).any() else "M" for p in pids.tolist()])
        rates = RI.rates(pidx, letters, D)
        e_min, p60, p1, nm = RI.minutes(pids, tids, D)
        # Fixture expected goals per team and gameweek, and each team's mean over its remaining fixtures.
        lam: dict[tuple[int, int], list[tuple[float, float, str, bool]]] = {}
        allf: dict[int, list[tuple[float, float]]] = {}
        for g in gws:
            for f in g["fixtures"]:
                h, a = teams.get(f.get("home")), teams.get(f.get("away"))
                if h is None or a is None:
                    continue
                lh, la = float(f["model"]["lh"]), float(f["model"]["la"])
                lam.setdefault((h, g["gw"]), []).append((lh, la, f.get("away"), True))
                lam.setdefault((a, g["gw"]), []).append((la, lh, f.get("home"), False))
                allf.setdefault(h, []).append((lh, la))
                allf.setdefault(a, []).append((la, lh))
        mean_f = np.array([np.mean([x[0] for x in allf.get(int(t), [(1.3, 1.3)])]) for t in tids.tolist()])
        mean_a = np.array([np.mean([x[1] for x in allf.get(int(t), [(1.3, 1.3)])]) for t in tids.tolist()])
        n_gw = len(gws)
        P = np.zeros((pids.size, n_gw))
        next_comp = None
        for gi, g in enumerate(gws):
            for k_fix in range(2):
                lf = np.array([(lam.get((int(t), g["gw"])) or [])[k_fix][0] if len(lam.get((int(t), g["gw"])) or []) > k_fix else np.nan for t in tids.tolist()])
                if np.all(np.isnan(lf)):
                    continue
                la = np.array([(lam.get((int(t), g["gw"])) or [])[k_fix][1] if len(lam.get((int(t), g["gw"])) or []) > k_fix else np.nan for t in tids.tolist()])
                ok = np.isfinite(lf)
                comp = project_points(letters, rates, e_min, p60, p1, np.where(ok, lf, 1.0), np.where(ok, la, 1.0), mean_f, mean_a)
                comp = {k_: v_ * cal for k_, v_ in comp.items()}
                tot = np.where(ok, total(comp), 0.0)
                P[:, gi] += tot
                if gi == 0:
                    c0 = {k: np.where(ok, v, 0.0) for k, v in comp.items()}
                    next_comp = c0 if next_comp is None else {k: next_comp[k] + c0[k] for k in c0}
        h5 = P[:, :HORIZON].sum(axis=1)
        ros = P.sum(axis=1)
        nxt = P[:, 0]
        score = np.array([value_score.get(int(p), 0.0) for p in pids.tolist()])
        price = price_proxy(letters, score)
        # This season in the league, and the last five club league matches: actual against underlying.
        ci = R.comps.index(slug) if slug in R.comps else -1
        cur_sid = R.current.get(slug)
        sid_i = R.sids.index(cur_sid) if cur_sid in R.sids else -1
        rows_l = np.flatnonzero((R.comp == ci) & (R.sid == sid_i)) if ci >= 0 else np.zeros(0, dtype=int)
        pid_set = {int(p): i for i, p in enumerate(pids.tolist())}
        season = np.zeros((pids.size, 4))           # points, minutes, appearances, underlying points
        for r in rows_l.tolist():
            i = pid_set.get(int(R.pid[r]))
            if i is not None:
                season[i] += (pts[r], R.mins[r], 1.0, xpts[r])
        lg_rows = np.flatnonzero(R.comp == ci) if ci >= 0 else np.zeros(0, dtype=int)
        form = np.zeros((pids.size, 3))             # last five club league matches: points, underlying, appearances
        club_m: dict[int, list[tuple[int, int]]] = {}
        for mi in np.flatnonzero(R.m_comp == ci).tolist() if ci >= 0 else []:
            for s in (0, 1):
                club_m.setdefault(int(R.m_tid[mi, s]), []).append((int(R.m_day[mi]), mi))
        last5 = {t: {mi for _, mi in sorted(v)[-5:]} for t, v in club_m.items()}
        for r in lg_rows.tolist():
            i = pid_set.get(int(R.pid[r]))
            if i is not None and int(R.match[r]) in last5.get(int(tids[i]), ()):
                form[i] += (pts[r], xpts[r], 1.0)
        tiers = np.zeros(pids.size, dtype=int)
        for p in POS:
            sel = np.flatnonzero(letters == p)
            if sel.size:
                tiers[sel] = _tiers(h5[sel])
        fields = ["id", "name", "pos", "tid", "club", "price", "next", "h5", "ros", "tier", "e_min", "p60", "p_goal", "p_ga", "cs",
                  "season_pts", "season_min", "season_apps", "season_xpts", "form_pts", "form_xpts", "form_apps", "value", "next_parts"]
        rows = []
        order = np.argsort(-h5)
        parts_keys = ["app", "goals", "assists", "cs", "gc", "saves", "cards", "og_pm", "dc", "bonus"]
        g_exp = (next_comp["goals"] / np.array([GOAL_PTS[x] for x in letters.tolist()])) if next_comp else np.zeros(pids.size)
        a_exp = (next_comp["assists"] / ASSIST_PTS) if next_comp else np.zeros(pids.size)
        for i in order.tolist():
            pid = int(pids[i])
            ident = people.get(str(pid)) or {}
            cs_p = (next_comp["cs"][i] / CS_PTS[letters[i]]) if (next_comp and CS_PTS[letters[i]] > 0) else None
            rows.append([str(pid), ident.get("name"), letters[i], int(tids[i]), tid_name.get(int(tids[i])), _r(price[i], 1), _r(nxt[i]),
                         _r(h5[i]), _r(ros[i], 1), int(tiers[i]), _r(e_min[i], 0), _r(p60[i]), _r(1 - math.exp(-g_exp[i])),
                         _r(1 - math.exp(-(g_exp[i] + a_exp[i]))), _r(cs_p), _r(season[i, 0], 0), int(season[i, 1]), int(season[i, 2]),
                         _r(season[i, 3], 1), _r(form[i, 0], 0), _r(form[i, 1], 1), int(form[i, 2]), _r(score[i], 2),
                         [_r(next_comp[k][i]) for k in parts_keys] if next_comp else None])
        # Fixture difficulty: each club's next gameweeks with its expected goals for and against.
        allv = [x for v in lam.values() for x in v]
        qa = np.percentile([x[0] for x in allv], [20, 40, 60, 80]) if allv else np.array([1, 1.2, 1.4, 1.6])
        qd = np.percentile([x[1] for x in allv], [20, 40, 60, 80]) if allv else np.array([1, 1.2, 1.4, 1.6])
        fdr = []
        for t, name in sorted(tid_name.items(), key=lambda kv: kv[1]):
            cells = []
            for g in gws[:FDR_GWS]:
                fx = lam.get((t, g["gw"])) or []
                cells.append([[x[2], 1 if x[3] else 0, _r(x[0]), _r(x[1]), int(5 - np.searchsorted(qa, x[0])), int(1 + np.searchsorted(qd, x[1]))]
                              for x in fx])
            att_sum = sum(x[0] for g in gws[:FDR_GWS] for x in lam.get((t, g["gw"])) or [])
            cs_sum = sum(math.exp(-x[1]) for g in gws[:FDR_GWS] for x in lam.get((t, g["gw"])) or [])
            fdr.append({"tid": t, "club": name, "gws": cells, "xg_for": _r(att_sum), "cs_sum": _r(cs_sum)})
        # The squad: a MILP over the best candidates per position.
        keep = []
        for p in POS:
            sel = np.flatnonzero(letters == p)
            keep += sel[np.argsort(-h5[sel])][:45].tolist()
            keep += sel[np.argsort(-(h5[sel] / np.maximum(price[sel] - 3.0, 0.5)))][:15].tolist()
        keep = sorted(set(keep))
        sq = optimise_squad([letters[i] for i in keep], [int(tids[i]) for i in keep], price[keep], h5[keep], nxt[keep])
        squad = None
        if sq:
            idx = [keep[i] for i in sq["squad"]]
            xi = {keep[i] for i in sq["xi"]}
            cap = keep[sq["captain"]] if sq["captain"] is not None else None
            xi_sorted = sorted(xi, key=lambda i: -nxt[i])
            vice = next((i for i in xi_sorted if i != cap), None)
            bench = sorted([i for i in idx if i not in xi], key=lambda i: (letters[i] != "G", -h5[i]))
            squad = {"solver": "HiGHS MILP (scipy)", "cost": _r(sq["cost"], 1), "budget": BUDGET, "horizon": HORIZON,
                     "xi": [str(pids[i]) for i in sorted(xi, key=lambda i: (POS.index(letters[i]), -h5[i]))],
                     "bench": [str(pids[i]) for i in bench], "captain": str(pids[cap]) if cap is not None else None,
                     "vice": str(pids[vice]) if vice is not None else None,
                     "xi_h5": _r(float(h5[list(xi)].sum()), 1), "xi_next": _r(float(nxt[list(xi)].sum() + (nxt[cap] if cap is not None else 0)), 1),
                     "formation": "-".join(str(sum(1 for i in xi if letters[i] == p)) for p in ("D", "M", "F"))}
        else:
            g = greedy_squad([letters[i] for i in keep], [int(tids[i]) for i in keep], price[keep], h5[keep])
            squad = {"solver": "greedy (no solver)", "squad": [str(pids[keep[i]]) for i in g]}
        # Suggestions.
        reg = (e_min >= 45) & (p1 >= 0.6)
        captain = [str(pids[i]) for i in np.argsort(-nxt)[:8].tolist()]
        pop_rank = {}
        for p in POS:
            sel = np.flatnonzero(letters == p)
            for r_, i in enumerate(sel[np.argsort(-season[sel, 0])].tolist()):
                pop_rank[i] = r_
        diffs = [i for i in np.argsort(-h5).tolist() if pop_rank.get(i, 0) >= 15 and price[i] <= 7.5 and reg[i]][:12]
        value_buys = [i for i in np.argsort(-(h5 / np.maximum(price - 3.5, 0.5))).tolist() if price[i] <= 6.5 and reg[i]][:12]
        exp_by_price = np.zeros(pids.size)
        for p in POS:
            sel = np.flatnonzero(letters == p)
            if sel.size >= 5:
                coef = np.polyfit(price[sel], h5[sel], 1)
                exp_by_price[sel] = np.polyval(coef, price[sel])
        ppm_season = season[:, 0] / np.maximum(season[:, 2], 1)
        sells = [i for i in np.argsort(-(ppm_season * HORIZON - h5)).tolist() if season[i, 2] >= 3 and price[i] >= 6.0][:12]
        luck = form[:, 0] - form[:, 1]
        buy_low = [i for i in np.argsort(luck).tolist() if form[i, 2] >= 3 and form[i, 1] / max(form[i, 2], 1) >= 4.0 and reg[i]][:12]
        sell_high = [i for i in np.argsort(-luck).tolist() if form[i, 2] >= 3 and luck[i] >= 4.0][:12]
        ids = lambda lst: [str(pids[i]) for i in lst]  # noqa: E731
        payload = {
            "league": slug, "name": e.get("name"), "season": e.get("season"), "as_of": today.isoformat(),
            "gameweeks": [{"gw": g["gw"], "label": g["label"], "start": date.fromordinal(g["start"]).isoformat(),
                           "end": date.fromordinal(g["end"]).isoformat(), "n": len(g["fixtures"])} for g in gws[:max(FDR_GWS, HORIZON)]],
            "n_gameweeks": n_gw, "fields": fields, "rows": rows, "parts": parts_keys, "fdr": fdr, "squad": squad,
            "picks": {"captain": captain, "differentials": ids(diffs), "value": ids(value_buys), "sell": ids(sells),
                      "buy_low": ids(buy_low), "sell_high": ids(sell_high),
                      "buys": {p: ids([i for i in np.argsort(-(h5 - exp_by_price)).tolist() if letters[i] == p and reg[i]][:6]) for p in POS}},
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        path = out_dir / f"{slug}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        tmp.replace(path)
        written.append(slug)
        summary.append({"slug": slug, "name": e.get("name"), "players": len(rows), "gameweeks": n_gw,
                        "next": payload["gameweeks"][0]["label"] if payload["gameweeks"] else None})
    meta = {"scoring": SCORING, "price_ranges": {p: list(v) for p, v in PRICE_RANGE.items()}, "price_power": PRICE_POWER, "budget": BUDGET,
            "squad": SQUAD, "per_club": PER_CLUB, "horizon": HORIZON, "bench_weight": BENCH_WEIGHT, "leagues": summary, "backtest": bt,
            "rates": {"tau_rates_days": TAU_RATES, "tau_minutes_days": TAU_MIN, "span_days": SPAN, "prior_90s": PRIOR_90S,
                      "goals_per_xg": _r(RI.g_per_xg, 3), "assists_per_xa": _r(RI.a_per_xa, 3), "new_at_club_prior": list(MIN_PRIOR)},
            "official_data": "Not used: the Premier League's terms of use forbid reproducing, re-utilising or redistributing its material "
                             "or creating a database from it, so FPL's prices and ownership are left out. Prices here are our own proxy.",
            "today": today.isoformat(), "runtime_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    tmp = out_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    tmp.replace(out_dir / "meta.json")
    for f in out_dir.glob("*.json"):
        if f.name != "meta.json" and f.stem not in written:
            f.unlink()
    logger.info("fantasy: %d leagues, backtest %s rounds; %.1fs", len(written), bt.get("rounds"), meta["runtime_s"])
    return {"leagues": len(written), "backtest": bt, "runtime_s": meta["runtime_s"]}
