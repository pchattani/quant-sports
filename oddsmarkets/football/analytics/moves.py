"""
Who moves next: the chance each player leaves his club in the next transfer window, how
(a transfer, a free, a loan, a loan ending, a release) and where to (the same league, a
stronger or a weaker one, or outside the leagues we follow); each club's expected arrivals
by position; and its ranked targets (fit x availability x plausibility).

Data (no new fetches): the line-ups the value model already reads (value.Rows: every
player-match with minutes, club, role letter and match rating; the match table's xG) and
the transfer store the hourly task fills from Sofascore (each followed club's recent moves
in and out, rated players' whole histories; transfers.normalise). No contract data:
Transfermarkt's, Spotrac's and similar sites' terms forbid reuse, and Sofascore's contract
end dates are a snapshot of today only, so the model cannot learn from them (they are shown
as a fact beside a player where the stores hold one).

Windows are halves of the year, as the fee model and the ledgers use them (transfers.window_of):
May-October is the summer window, November-April the winter window; each league's actual
registration period falls inside its half (value.WINDOWS). A player-window is one row:

    population  a player whose latest club appearance before the window opens (day s) was for
                a club of a followed league, within the last 180 days, with no departure from
                that club recorded since that appearance
    label       he left that club in [s, s + half a year): a move from it in the transfer store
                (a transfer, a free, a loan out, a loan ending, a release to "No team" or
                retirement), or a club appearance for another club in the half (type unknown)
    features    only what was known before s (the 365 days of line-ups before it, the store's
                moves dated before it): age, his share of his club's minutes and its trend,
                starts, his match rating against his unit's teammates, his depth rank in the
                unit, the club's xG difference and its trend, the league's tier and strength,
                a recent arrival, on loan now, loans and moves in the last years, national-team
                minutes, the days since his last appearance, the window's half.

The model is a ridge logistic regression for "leaves" and a ridge multinomial for the type
and the destination among the movers (numpy and scipy, no other dependency). Validation is
walk-forward on held-out windows, pre-registered in docs/research/football_moves.md.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
from scipy.optimize import minimize

from oddsmarkets.football.analytics import value as V

logger = logging.getLogger(__name__)

HALF_DAYS = 184                     # a window is half a year: [s, s + HALF_DAYS) from 1 May or 1 Nov
LOOKBACK = 365                      # features use the year before s
RECENT = 90                         # "recent" share: the last 90 days
ACTIVE_DAYS = 180                   # in the population: a club appearance in the last 180 days
NEW_ARRIVAL_DAYS = 150              # a first appearance for the club within this many days (after another club)
RELEASE_NAMES = ("no team", "retired", "without club", "free agent")
TYPES = ("transfer", "free", "loan", "loan_end", "release")
TYPE_LABELS = {"transfer": "Transfer", "free": "Free transfer", "loan": "Loan out", "loan_end": "Loan ends",
               "release": "Released / no club"}
DESTS = ("same", "stronger", "weaker", "outside")
DEST_LABELS = {"same": "Same league", "stronger": "Stronger league", "weaker": "Weaker league",
               "outside": "Outside our leagues"}
DEST_MARGIN = 0.10                  # goals per match between league offsets: "same level" inside it -> by offset sign
SLOTS = {"G": 1.0, "D": 4.0, "M": 4.0, "F": 2.0}
Q_PRIOR, Q_PRIOR_MIN = 6.7, 450.0     # quality: the match rating shrunk toward 6.7 by 450 rated minutes
TIERS = ("Top five (Europe)", "Other Europe", "South America", "North America", "Asia")
FEATURES = ("age", "age2", "age_na", "share", "share_trend", "starts", "log_min", "rel_rating", "rating_na",
            "depth_over", "team_xgd", "team_trend", "league_off", "tier_oe", "tier_sa", "tier_na", "tier_as",
            "new_arrival", "on_loan", "loans2y", "moves3y", "intl", "days_since", "l_G", "l_D", "l_F", "summer")
TYPE_FEATURES = ("age", "age2", "age_na", "share", "share_trend", "log_min", "rel_rating", "team_xgd", "league_off",
                 "tier_oe", "tier_sa", "tier_na", "tier_as", "on_loan", "loans2y", "new_arrival", "summer")
DEST_FEATURES = ("age", "age2", "share", "rel_rating", "team_xgd", "league_off", "tier_oe", "tier_sa", "tier_na",
                 "tier_as", "summer")


def half_start(d: date) -> date:
    """The first day of the window (half-year) that contains d: 1 May or 1 Nov."""
    if 5 <= d.month <= 10:
        return date(d.year, 5, 1)
    return date(d.year if d.month >= 11 else d.year - 1, 11, 1)


def next_half_start(today: date) -> date:
    """The next window to open after today (the one this page forecasts)."""
    h = half_start(today)
    return date(h.year, 11, 1) if h.month == 5 else date(h.year + 1, 5, 1)


def half_label(s: date) -> str:
    return f"Summer {s.year}" if s.month == 5 else f"Winter {s.year}/{str(s.year + 1)[2:]}"


def move_type(t: dict) -> str | None:
    """A normalised move (transfers.normalise) as one of TYPES; None for a youth promotion or an unknown type."""
    kind = t.get("kind")
    to_name = str(t.get("to_name") or "").strip().lower()
    if to_name in RELEASE_NAMES or (t.get("to") is None and kind not in ("loan", "loan_end")):
        return "release"
    if kind == "loan":
        return "loan"
    if kind == "loan_end":
        return "loan_end"
    if kind == "free":
        return "free"
    if kind in ("fee", "undisclosed"):
        return "transfer"
    return None


# ── the panel ────────────────────────────────────────────────────────────────

@dataclass
class Panel:
    s: date
    pid: np.ndarray
    tid: np.ndarray
    letter: np.ndarray                         # index into V.LETTERS (-1 unknown)
    league: list[str]
    X: np.ndarray                              # (n, len(FEATURES))
    y: np.ndarray | None = None                # 1 left in the window
    typ: list[str | None] = field(default_factory=list)   # the departure's type (None: stayed or unknown)
    dest: list[str | None] = field(default_factory=list)
    dest_tid: list[int | None] = field(default_factory=list)
    info: dict[str, np.ndarray] = field(default_factory=dict)   # raw values for the payloads (share, minutes, rating ...)

    def __len__(self) -> int:
        return int(self.pid.size)


@dataclass
class Records:
    """The store's moves, indexed by player, with the club-of-a-move lookups the panel needs."""
    by_pid: dict[int, list[dict]]

    @classmethod
    def build(cls, moves: list[dict]) -> "Records":
        by: dict[int, list[dict]] = {}
        for t in moves:
            by.setdefault(int(t["pid"]), []).append(t)
        for v in by.values():
            v.sort(key=lambda t: t["day"])
        return cls(by)

    def of(self, pid: int) -> list[dict]:
        return self.by_pid.get(int(pid), [])


class Lineups:
    """Club rows of value.Rows sorted by (player, day), with club match days and xG per club match."""

    def __init__(self, R: V.Rows, league_slugs: set[str]) -> None:
        club_c = np.array([R.comp_scope[c] == "club" for c in range(len(R.comps))], dtype=bool)
        intl_c = ~club_c
        rows = np.flatnonzero(club_c[R.comp] & (R.tid >= 0)) if len(R) else np.zeros(0, dtype=int)
        order = rows[np.lexsort((R.day[rows], R.pid[rows]))]
        self.pid = R.pid[order]
        self.day = R.day[order]
        self.tid = R.tid[order]
        self.mins = R.mins[order].astype(float)
        self.start = R.start[order].astype(float)
        self.letter = R.letter[order]
        self.rating = R.rating[order].astype(float)
        self.comp = R.comp[order]
        u, st = np.unique(self.pid, return_index=True)
        self.span = {int(p): (int(a), int(b)) for p, a, b in zip(u.tolist(), st.tolist(), np.r_[st[1:], self.pid.size].tolist())}
        self.is_league = np.array([R.comps[c] in league_slugs for c in range(len(R.comps))], dtype=bool)
        self.comps = list(R.comps)
        # National-team minutes by player and day.
        ir = np.flatnonzero(intl_c[R.comp]) if len(R) else np.zeros(0, dtype=int)
        io = ir[np.lexsort((R.day[ir], R.pid[ir]))]
        self.i_pid, self.i_day, self.i_min = R.pid[io], R.day[io], R.mins[io].astype(float)
        ui, si = np.unique(self.i_pid, return_index=True)
        self.i_span = {int(p): (int(a), int(b)) for p, a, b in zip(ui.tolist(), si.tolist(), np.r_[si[1:], self.i_pid.size].tolist())}
        # Club matches: day, club, the club's npxG for and against.
        mm = np.flatnonzero(club_c[R.m_comp]) if R.m_day.size else np.zeros(0, dtype=int)
        md, mt, mx, mc = [], [], [], []
        for s_ in (0, 1):
            md.append(R.m_day[mm])
            mt.append(R.m_tid[mm, s_])
            mx.append(R.m_npxg[mm, s_] - R.m_npxg[mm, 1 - s_])
            mc.append(R.m_comp[mm])
        md, mt, mx, mc = np.concatenate(md), np.concatenate(mt), np.concatenate(mx).astype(float), np.concatenate(mc)
        o = np.lexsort((md, mt))
        self.m_day, self.m_tid, self.m_xgd, self.m_comp = md[o], mt[o], mx[o], mc[o]
        ut, stt = np.unique(self.m_tid, return_index=True)
        self.m_span = {int(t): (int(a), int(b)) for t, a, b in zip(ut.tolist(), stt.tolist(), np.r_[stt[1:], self.m_tid.size].tolist())}

    def club_matches(self, tid: int, d0: int, d1: int) -> tuple[int, float, int]:
        """(matches, sum of xG difference, matches with an xG) of a club on days d0 <= day < d1."""
        a, b = self.m_span.get(int(tid), (0, 0))
        if a >= b:
            return 0, 0.0, 0
        days = self.m_day[a:b]
        i, j = a + int(np.searchsorted(days, d0, "left")), a + int(np.searchsorted(days, d1, "left"))
        x = self.m_xgd[i:j]
        ok = np.isfinite(x)
        return j - i, float(x[ok].sum()), int(ok.sum())

    def club_league(self, d0: int, d1: int) -> dict[int, str]:
        """Each club's league (most league minutes) from line-ups on days d0 <= day < d1."""
        sel = (self.day >= d0) & (self.day < d1) & self.is_league[self.comp]
        acc: dict[int, dict[int, float]] = {}
        for t, c, m in zip(self.tid[sel].tolist(), self.comp[sel].tolist(), self.mins[sel].tolist()):
            d = acc.setdefault(t, {})
            d[c] = d.get(c, 0.0) + m
        return {t: self.comps[max(d.items(), key=lambda kv: kv[1])[0]] for t, d in acc.items()}


def _age(dob: str | None, d: date) -> float:
    if not dob:
        return float("nan")
    try:
        return (d - date.fromisoformat(str(dob)[:10])).days / 365.25
    except ValueError:
        return float("nan")


def build_panel(L: Lineups, rec: Records, dob: dict[str, str], s: date, offsets: dict[str, float],
                labels: bool = True, until: date | None = None) -> Panel:
    """
    The player-window rows for the window that opens on day s (features from before s only).
    With `labels`, the departures in [s, s + HALF_DAYS) (capped at `until`, the data's last day).
    """
    s0 = s.toordinal()
    lo = s0 - LOOKBACK
    end = s0 + HALF_DAYS
    if until is not None:
        end = min(end, until.toordinal() + 1)
    leagues = L.club_league(lo, s0)
    after_league = L.club_league(s0, s0 + HALF_DAYS + 120)
    rows: list[list[float]] = []
    pids, tids, letters, lgs = [], [], [], []
    ys, typs, dests, dtids = [], [], [], []
    info: dict[str, list] = {k: [] for k in ("min", "share", "share90", "starts", "rating", "rel_rating", "depth_rank",
                                              "last_day", "on_loan", "arrived", "q", "age")}
    # Unit means of ratings per club (minutes-weighted), and depth ranks, need every club's players first.
    cand: list[tuple] = []
    for p, (a, b) in L.span.items():
        days = L.day[a:b]
        i, j = a + int(np.searchsorted(days, lo, "left")), a + int(np.searchsorted(days, s0, "left"))
        if i >= j:
            continue
        x = int(L.tid[j - 1])
        last_day = int(L.day[j - 1])
        if x not in leagues or last_day < s0 - ACTIVE_DAYS:
            continue
        # A departure from x recorded after his last appearance and before s: no longer there.
        gone = False
        arrived_day, arrived_kind = None, None
        for t in rec.of(p):
            if t["day"] >= s0:
                break
            if t["from"] == x and t["day"] > last_day and move_type(t) is not None:
                gone = True
            if t["to"] == x and t["kind"] != "youth":
                arrived_day, arrived_kind = t["day"], t["kind"]
            elif t["from"] == x and t["kind"] in ("loan_end",):
                arrived_kind = "ended"
        if gone:
            continue
        sel = L.tid[i:j] == x
        mins_x = float(L.mins[i:j][sel].sum())
        if mins_x <= 0:
            continue
        first_x = int(L.day[i:j][sel].min())
        cand.append((p, a, b, i, j, x, last_day, sel, mins_x, first_x, arrived_day, arrived_kind))
    # Club-unit rating means and depth (players with minutes for the club in the lookback).
    unit_acc: dict[tuple[int, int], list[tuple[int, float, float]]] = {}
    per_player: dict[int, dict] = {}
    for (p, a, b, i, j, x, last_day, sel, mins_x, first_x, arr_d, arr_k) in cand:
        lt = L.letter[i:j][sel]
        lt = lt[lt >= 0]
        letter = int(np.bincount(lt).argmax()) if lt.size else -1
        rt = L.rating[i:j][sel]
        mn = L.mins[i:j][sel]
        ok = np.isfinite(rt) & (mn > 0)
        rating = float((rt[ok] * mn[ok]).sum() / mn[ok].sum()) if ok.any() else float("nan")
        per_player[p] = {"letter": letter, "rating": rating, "rmins": float(mn[ok].sum())}
        unit_acc.setdefault((x, letter), []).append((p, mins_x, rating if ok.any() else float("nan")))
    rank_of: dict[int, int] = {}
    unit_mean: dict[int, float] = {}
    for (x, letter), lst in unit_acc.items():
        lst_sorted = sorted(lst, key=lambda r: -r[1])
        for k, (p, m, r) in enumerate(lst_sorted):
            rank_of[p] = k + 1
        tot_m = sum(m for _, m, r in lst if r == r)
        tot_r = sum(m * r for _, m, r in lst if r == r)
        for p, m, r in lst:
            if r == r and tot_m - m > 0:
                unit_mean[p] = (tot_r - m * r) / (tot_m - m)
    for (p, a, b, i, j, x, last_day, sel, mins_x, first_x, arr_d, arr_k) in cand:
        pp = per_player[p]
        n_m, _, _ = L.club_matches(x, first_x, s0)
        share = mins_x / (90.0 * max(n_m, 1))
        r_lo = s0 - RECENT
        dd = L.day[i:j][sel]
        mm = L.mins[i:j][sel]
        rec_min = float(mm[dd >= r_lo].sum())
        n_r, _, _ = L.club_matches(x, max(r_lo, first_x), s0)
        share90 = rec_min / (90.0 * n_r) if n_r > 0 else share
        n_old, _, _ = L.club_matches(x, first_x, max(r_lo, first_x))
        share_old = (mins_x - rec_min) / (90.0 * n_old) if n_old > 0 else share
        starts = float(L.start[i:j][sel].sum()) / max(n_m, 1)
        n_all, xs_all, k_all = L.club_matches(x, lo, s0)
        n_rec, xs_rec, k_rec = L.club_matches(x, r_lo, s0)
        team_xgd = xs_all / k_all if k_all else 0.0
        team_trend = (xs_rec / k_rec - team_xgd) if k_rec >= 3 else 0.0
        lg = leagues.get(x)
        tier = V.LEAGUE_TIERS.get(lg or "", "")
        rating = pp["rating"]
        rel = (rating - unit_mean[p]) if (rating == rating and p in unit_mean) else 0.0
        letter = pp["letter"]
        depth_over = max(rank_of.get(p, 1) - SLOTS.get(V.LETTERS[letter] if letter >= 0 else "M", 3.0), 0.0)
        other_before = bool(((L.tid[i:j] != x) & (L.day[i:j] < first_x)).any())
        new_arrival = 1.0 if (first_x >= s0 - NEW_ARRIVAL_DAYS and other_before) else 0.0
        on_loan = 1.0 if arr_k == "loan" else 0.0
        if arr_d is not None and arr_d >= s0 - NEW_ARRIVAL_DAYS:
            new_arrival = 1.0
        loans2y = sum(1 for t in rec.of(p) if t["kind"] == "loan" and s0 - 730 <= t["day"] < s0)
        moves3y = sum(1 for t in rec.of(p) if t["kind"] in ("fee", "free", "undisclosed") and s0 - 1095 <= t["day"] < s0)
        ia, ib = L.i_span.get(p, (0, 0))
        intl = 0.0
        if ia < ib:
            idays = L.i_day[ia:ib]
            ii, jj = ia + int(np.searchsorted(idays, lo, "left")), ia + int(np.searchsorted(idays, s0, "left"))
            intl = float(L.i_min[ii:jj].sum())
        age = _age(dob.get(str(p)), s)
        age_c = (age - 26.0) if age == age else 0.0
        row = [age_c, age_c * age_c / 10.0, 0.0 if age == age else 1.0, min(share, 1.2), share90 - share_old, min(starts, 1.2),
               math.log1p(mins_x / 90.0), rel, 0.0 if rating == rating else 1.0, min(depth_over, 6.0), team_xgd, team_trend,
               float(offsets.get(lg or "", 0.0)), float(tier == "Other Europe"), float(tier == "South America"),
               float(tier == "North America"), float(tier == "Asia"), new_arrival, on_loan, float(min(loans2y, 3)),
               float(min(moves3y, 3)), math.log1p(intl / 90.0), (s0 - last_day) / 30.0,
               float(letter == 0), float(letter == 1), float(letter == 3), float(s.month == 5)]
        rows.append(row)
        pids.append(p)
        tids.append(x)
        letters.append(letter)
        lgs.append(lg or "")
        for k, v in (("min", mins_x), ("share", share), ("share90", share90), ("starts", starts), ("rating", rating),
                     ("rel_rating", rel), ("depth_rank", rank_of.get(p, 1)), ("last_day", last_day), ("on_loan", on_loan),
                     ("arrived", arr_d if arr_d is not None else -1),
                     ("q", (rating * pp["rmins"] + Q_PRIOR * Q_PRIOR_MIN) / (pp["rmins"] + Q_PRIOR_MIN) if rating == rating else Q_PRIOR),
                     ("age", age)):
            info[k].append(v)
        if labels:
            y, typ, dest, dt = 0, None, None, None
            for t in rec.of(p):
                if t["day"] < s0:
                    continue
                if t["day"] >= end:
                    break
                mt = move_type(t)
                if t["from"] == x and mt is not None:
                    y, typ, dt = 1, mt, t.get("to")
                    break
            if not y:
                # A club appearance for another club inside the window: he left (type unknown).
                jj = a + int(np.searchsorted(L.day[a:b], end, "left"))
                other = (L.tid[j:jj] != x)
                if other.any():
                    y = 1
                    dt = int(L.tid[j:jj][other][0])
            if y and typ != "release" and typ != "loan_end":
                tl = after_league.get(int(dt)) if dt is not None else None
                if dt is None:
                    dest = None
                elif tl is None:
                    dest = "outside"
                elif tl == lg:
                    dest = "same"
                else:
                    diff = float(offsets.get(tl, 0.0)) - float(offsets.get(lg or "", 0.0))
                    dest = "stronger" if diff > 0 else "weaker"
            ys.append(y)
            typs.append(typ)
            dests.append(dest)
            dtids.append(dt)
    P = Panel(s=s, pid=np.array(pids, dtype=np.int64), tid=np.array(tids, dtype=np.int64), letter=np.array(letters),
              league=lgs, X=np.array(rows, dtype=float).reshape(-1, len(FEATURES)),
              y=np.array(ys, dtype=float) if labels else None, typ=typs, dest=dests, dest_tid=dtids,
              info={k: np.array(v, dtype=float) for k, v in info.items()})
    return P


# ── models ───────────────────────────────────────────────────────────────────

@dataclass
class Logit:
    """Ridge logistic regression on standardised columns (the intercept is not penalised)."""
    cols: tuple[str, ...]
    lam: float
    mean: np.ndarray
    sd: np.ndarray
    coef: np.ndarray
    intercept: float

    def predict(self, X: np.ndarray, offset: float | np.ndarray = 0.0) -> np.ndarray:
        Z = (X - self.mean) / self.sd
        return 1.0 / (1.0 + np.exp(-(Z @ self.coef + self.intercept + offset)))

    def to_json(self) -> dict:
        return {"cols": list(self.cols), "lam": self.lam, "mean": [round(float(x), 5) for x in self.mean],
                "sd": [round(float(x), 5) for x in self.sd], "coef": [round(float(x), 5) for x in self.coef],
                "intercept": round(float(self.intercept), 5)}


def _std(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    m = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd < 1e-9] = 1.0
    return m, sd


def fit_logit(X: np.ndarray, y: np.ndarray, cols: tuple[str, ...], lam: float, w: np.ndarray | None = None) -> Logit:
    m, sd = _std(X)
    Z = (X - m) / sd
    n, k = Z.shape
    w = np.ones(n) if w is None else w
    W = w.sum()

    def f(theta):
        b, c = theta[:k], theta[k]
        z = Z @ b + c
        ll = np.sum(w * (np.logaddexp(0.0, z) - y * z)) / W + 0.5 * lam * np.dot(b, b) / W
        p = 1.0 / (1.0 + np.exp(-z))
        g = (Z.T @ (w * (p - y))) / W + lam * b / W
        return ll, np.r_[g, np.sum(w * (p - y)) / W]

    p0 = min(max(float(np.average(y, weights=w)), 1e-4), 1 - 1e-4)
    th0 = np.r_[np.zeros(k), math.log(p0 / (1 - p0))]
    r = minimize(f, th0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return Logit(cols, lam, m, sd, r.x[:k], float(r.x[k]))


@dataclass
class Softmax:
    """Ridge multinomial logistic regression (class 0 is the reference)."""
    cols: tuple[str, ...]
    classes: tuple[str, ...]
    lam: float
    mean: np.ndarray
    sd: np.ndarray
    B: np.ndarray                              # (k, C)
    c: np.ndarray                              # (C,)

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (X - self.mean) / self.sd
        E = Z @ self.B + self.c
        E -= E.max(axis=1, keepdims=True)
        P = np.exp(E)
        return P / P.sum(axis=1, keepdims=True)

    def to_json(self) -> dict:
        return {"cols": list(self.cols), "classes": list(self.classes), "lam": self.lam,
                "mean": [round(float(x), 5) for x in self.mean], "sd": [round(float(x), 5) for x in self.sd],
                "B": [[round(float(x), 5) for x in r] for r in self.B], "c": [round(float(x), 5) for x in self.c]}


def fit_softmax(X: np.ndarray, y: np.ndarray, cols: tuple[str, ...], classes: tuple[str, ...], lam: float) -> Softmax:
    m, sd = _std(X)
    Z = (X - m) / sd
    n, k = Z.shape
    C = len(classes)
    Y = np.zeros((n, C))
    Y[np.arange(n), y] = 1.0

    def f(theta):
        B = theta[:k * C].reshape(k, C)
        c = theta[k * C:]
        E = Z @ B + c
        mx = E.max(axis=1, keepdims=True)
        lse = mx[:, 0] + np.log(np.exp(E - mx).sum(axis=1))
        ll = (np.sum(lse) - np.sum(E * Y)) / n + 0.5 * lam * np.sum(B * B) / n
        P = np.exp(E - lse[:, None])
        G = (Z.T @ (P - Y)) / n + lam * B / n
        return ll, np.r_[G.ravel(), (P - Y).sum(axis=0) / n]

    prior = np.log(np.maximum(Y.mean(axis=0), 1e-4))
    th0 = np.r_[np.zeros(k * C), prior - prior.mean()]
    r = minimize(f, th0, jac=True, method="L-BFGS-B", options={"maxiter": 800})
    return Softmax(cols, classes, lam, m, sd, r.x[:k * C].reshape(k, C), r.x[k * C:])


def cols_of(names: tuple[str, ...]) -> list[int]:
    return [FEATURES.index(c) for c in names]


# ── metrics ──────────────────────────────────────────────────────────────────

def logloss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_ci(a: np.ndarray, b: np.ndarray, groups: np.ndarray, n_boot: int = 2000, seed: int = 11) -> tuple[float, float, float]:
    """Mean of (a - b) with a 95% bootstrap CI, resampling clubs (players of one club move together)."""
    d = a - b
    ug, inv = np.unique(groups, return_inverse=True)
    sums = np.bincount(inv, weights=d, minlength=ug.size)
    cnt = np.bincount(inv, minlength=ug.size).astype(float)
    rng = np.random.default_rng(seed)
    bs = np.empty(n_boot)
    for k in range(n_boot):
        ix = rng.integers(0, ug.size, ug.size)
        bs[k] = sums[ix].sum() / cnt[ix].sum()
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """By decile of the forecast: n, mean forecast, observed rate."""
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    out = []
    for k in range(bins):
        sel = (p >= q[k]) & ((p < q[k + 1]) if k < bins - 1 else (p <= q[k + 1]))
        if sel.sum() == 0:
            continue
        out.append({"lo": round(float(q[k]), 4), "hi": round(float(q[k + 1]), 4), "n": int(sel.sum()),
                    "p_mean": round(float(p[sel].mean()), 4), "y_mean": round(float(y[sel].mean()), 4)})
    return out


def calib_slope(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """(intercept, slope) of the logistic recalibration y ~ a + b logit(p): b near 1, a near 0 when calibrated."""
    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    X = z[:, None]
    m = fit_logit(X, y, ("z",), 1e-6)
    b = float(m.coef[0] / m.sd[0])
    a = float(m.intercept - m.coef[0] * m.mean[0] / m.sd[0])
    return a, b


# ── clubs: needs, arrivals and targets ──────────────────────────────────────

LETTER_UNITS = ("G", "D", "M", "F")
UNIT_NAMES = {"G": "Goalkeeper", "D": "Defence", "M": "Midfield", "F": "Attack"}
CHOICE_FEATURES = ("same_league", "same_tier", "off_diff", "off_diff2", "xgd_diff", "xgd_diff2", "q_gap", "q_gap2",
                   "need", "recent_in")
ARRIVAL_FEATURES = ("log_ed", "team_xgd", "league_off", "tier_oe", "tier_sa", "tier_na", "tier_as", "log_recent", "log_n")
ARRIVAL_KINDS = ("fee", "free", "undisclosed", "loan")


@dataclass
class Clubs:
    """The followed clubs at a window's opening, from the panel and the leave model's probabilities."""
    tids: np.ndarray
    league: list[str]
    off: np.ndarray
    tier: list[str]
    xgd: np.ndarray
    level: np.ndarray                          # (n, 4) minutes-weighted quality by letter unit
    ed: np.ndarray                             # (n, 4) expected departures by letter unit
    slots_used: np.ndarray                     # (n, 4) players with 30%+ of the club's minutes, by unit
    recent_in: np.ndarray                      # recent arrivals among the club's players
    n: np.ndarray                              # players in the panel
    ix: dict[int, int] = field(default_factory=dict)


def club_tables(P: Panel, p_leave: np.ndarray) -> Clubs:
    F = {c: i for i, c in enumerate(FEATURES)}
    u = np.unique(P.tid)
    ix = {int(t): k for k, t in enumerate(u.tolist())}
    n = u.size
    off, xgd = np.zeros(n), np.zeros(n)
    league, tier = [""] * n, [""] * n
    lvl_w, lvl_s = np.zeros((n, 4)), np.zeros((n, 4))
    ed, used = np.zeros((n, 4)), np.zeros((n, 4))
    rec_in, cnt = np.zeros(n), np.zeros(n)
    q, mins, share = P.info["q"], P.info["min"], P.info["share"]
    for i in range(len(P)):
        k = ix[int(P.tid[i])]
        lu = int(P.letter[i]) if P.letter[i] >= 0 else 2
        off[k] = P.X[i, F["league_off"]]
        xgd[k] = P.X[i, F["team_xgd"]]
        league[k] = P.league[i]
        tier[k] = V.LEAGUE_TIERS.get(P.league[i], "")
        lvl_w[k, lu] += mins[i]
        lvl_s[k, lu] += mins[i] * q[i]
        ed[k, lu] += p_leave[i] * min(share[i], 1.0)
        used[k, lu] += 1.0 if share[i] >= 0.3 else 0.0
        rec_in[k] += P.X[i, F["new_arrival"]]
        cnt[k] += 1
    level = np.where(lvl_w > 0, lvl_s / np.maximum(lvl_w, 1e-9), Q_PRIOR)
    return Clubs(u, league, off, tier, xgd, level, ed, used, rec_in, cnt, ix)


def choice_rows(P: Panel, C: Clubs, j: int, cand: np.ndarray) -> np.ndarray:
    """The choice features of mover j (panel row) against candidate clubs `cand` (indices into C)."""
    F = {c: i for i, c in enumerate(FEATURES)}
    o = C.ix[int(P.tid[j])]
    lu = int(P.letter[j]) if P.letter[j] >= 0 else 2
    same_l = np.array([C.league[c] == C.league[o] for c in cand.tolist()], dtype=float)
    same_t = np.array([C.tier[c] == C.tier[o] for c in cand.tolist()], dtype=float)
    od = C.off[cand] - P.X[j, F["league_off"]]
    xd = C.xgd[cand] - P.X[j, F["team_xgd"]]
    qg = P.info["q"][j] - C.level[cand, lu]
    need = C.ed[cand, lu] / SLOTS[LETTER_UNITS[lu]]
    return np.column_stack([same_l, same_t, od, od * od, xd, xd * xd, qg, qg * qg, need, np.log1p(C.recent_in[cand])])


@dataclass
class CLogit:
    """Conditional logit over destination clubs (no intercept: a choice among clubs)."""
    cols: tuple[str, ...]
    lam: float
    coef: np.ndarray

    def utility(self, Z: np.ndarray) -> np.ndarray:
        return Z @ self.coef

    def to_json(self) -> dict:
        return {"cols": list(self.cols), "lam": self.lam, "coef": [round(float(x), 5) for x in self.coef]}


def fit_clogit(groups: list[tuple[np.ndarray, int]], lam: float) -> CLogit:
    """groups: (features of every candidate club, index of the chosen one)."""
    k = groups[0][0].shape[1]

    def f(b):
        ll, g = 0.0, np.zeros(k)
        for Z, ch in groups:
            u = Z @ b
            m = u.max()
            e = np.exp(u - m)
            s = e.sum()
            ll -= u[ch] - m - math.log(s)
            g -= Z[ch] - (e[:, None] * Z).sum(axis=0) / s
        n = len(groups)
        return ll / n + 0.5 * lam * np.dot(b, b) / n, g / n + lam * b / n

    r = minimize(f, np.zeros(k), jac=True, method="L-BFGS-B", options={"maxiter": 400})
    return CLogit(CHOICE_FEATURES, lam, r.x)


def club_arrivals(rec_moves: list[dict], C: Clubs, s: date, end_day: int) -> tuple[np.ndarray, np.ndarray]:
    """(arrivals per club, arrivals per club and letter unit) in [s, end): fees, frees, undisclosed and loans in."""
    s0 = s.toordinal()
    tot = np.zeros(C.tids.size)
    by = np.zeros((C.tids.size, 4))
    for t in rec_moves:
        if t["day"] < s0 or t["day"] >= end_day or t["kind"] not in ARRIVAL_KINDS or t["to"] is None:
            continue
        k = C.ix.get(int(t["to"]))
        if k is None:
            continue
        tot[k] += 1
        lu = LETTER_UNITS.index(t["pos"]) if t.get("pos") in LETTER_UNITS else 2
        by[k, lu] += 1
    return tot, by


def arrival_design(C: Clubs) -> np.ndarray:
    t = C.tier
    return np.column_stack([np.log1p(C.ed.sum(axis=1)), C.xgd, C.off, [float(x == "Other Europe") for x in t],
                            [float(x == "South America") for x in t], [float(x == "North America") for x in t],
                            [float(x == "Asia") for x in t], np.log1p(C.recent_in), np.log(np.maximum(C.n, 1))])


@dataclass
class Poisson:
    cols: tuple[str, ...]
    lam: float
    mean: np.ndarray
    sd: np.ndarray
    coef: np.ndarray
    intercept: float

    def predict(self, X: np.ndarray, offset: float = 0.0) -> np.ndarray:
        return np.exp(((X - self.mean) / self.sd) @ self.coef + self.intercept + offset)

    def to_json(self) -> dict:
        return {"cols": list(self.cols), "lam": self.lam, "mean": [round(float(x), 5) for x in self.mean],
                "sd": [round(float(x), 5) for x in self.sd], "coef": [round(float(x), 5) for x in self.coef],
                "intercept": round(float(self.intercept), 5)}


def fit_poisson(X: np.ndarray, y: np.ndarray, lam: float) -> Poisson:
    m, sd = _std(X)
    Z = (X - m) / sd
    n, k = Z.shape

    def f(th):
        b, c = th[:k], th[k]
        eta = Z @ b + c
        mu = np.exp(eta)
        ll = np.sum(mu - y * eta) / n + 0.5 * lam * np.dot(b, b) / n
        return ll, np.r_[Z.T @ (mu - y) / n + lam * b / n, np.sum(mu - y) / n]

    r = minimize(f, np.r_[np.zeros(k), math.log(max(y.mean(), 1e-3))], jac=True, method="L-BFGS-B")
    return Poisson(ARRIVAL_FEATURES, lam, m, sd, r.x[:k], float(r.x[k]))


def poisson_dev(y: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """Per-club Poisson deviance."""
    mu = np.maximum(mu, 1e-9)
    t = np.where(y > 0, y * np.log(np.maximum(y, 1e-12) / mu), 0.0)
    return 2.0 * (t - (y - mu))


def unit_shares(C: Clubs, base_share: np.ndarray, beta: float) -> np.ndarray:
    """Each club's arrivals split by letter unit: the base mix tilted toward units with more expected departures."""
    need = C.ed / np.array([SLOTS[u] for u in LETTER_UNITS])
    w = base_share[None, :] * np.exp(beta * need)
    return w / w.sum(axis=1, keepdims=True)


def choice_tensor(P: Panel, C: Clubs, rows: np.ndarray) -> np.ndarray:
    """(len(rows), n clubs, len(CHOICE_FEATURES)) choice features of the panel's rows against every club."""
    F = {c: i for i, c in enumerate(FEATURES)}
    lu = np.where(P.letter[rows] >= 0, P.letter[rows], 2).astype(int)
    o = np.array([C.ix[int(t)] for t in P.tid[rows].tolist()])
    lg = np.array(C.league, dtype=object)
    tr = np.array(C.tier, dtype=object)
    same_l = (lg[None, :] == lg[o][:, None]).astype(float)
    same_t = (tr[None, :] == tr[o][:, None]).astype(float)
    od = C.off[None, :] - P.X[rows, F["league_off"]][:, None]
    xd = C.xgd[None, :] - P.X[rows, F["team_xgd"]][:, None]
    qg = P.info["q"][rows][:, None] - C.level[:, lu].T
    need = (C.ed[:, lu] / np.array([SLOTS[LETTER_UNITS[u]] for u in lu])[None, :]).T
    rin = np.broadcast_to(np.log1p(C.recent_in)[None, :], od.shape)
    return np.stack([same_l, same_t, od, od * od, xd, xd * xd, qg, qg * qg, need, rin], axis=2)


def join_probs(P: Panel, C: Clubs, cl: CLogit, p_to_club: np.ndarray, chunk: int = 1500) -> np.ndarray:
    """
    (n players, n clubs): the chance each player joins each club in the window = his chance of moving to a
    club in our leagues (p_to_club) x the conditional logit's share of that club (his own club excluded).
    """
    out = np.zeros((len(P), C.tids.size), dtype=np.float32)
    for a in range(0, len(P), chunk):
        rows = np.arange(a, min(a + chunk, len(P)))
        U = choice_tensor(P, C, rows) @ cl.coef
        o = np.array([C.ix[int(t)] for t in P.tid[rows].tolist()])
        U[np.arange(rows.size), o] = -np.inf
        U -= U.max(axis=1, keepdims=True)
        E = np.exp(U)
        out[rows] = (E / E.sum(axis=1, keepdims=True)) * p_to_club[rows][:, None]
    return out


def topk_eval(J: np.ndarray, P: Panel, C: Clubs, actual: dict[int, set[int]], k: int = 10) -> dict[str, np.ndarray]:
    """Per club with at least one actual signing from the panel: hits in its top k by J, and by two baselines."""
    F = {c: i for i, c in enumerate(FEATURES)}
    clubs = sorted(c for c in actual if actual[c])
    p_av = J.sum(axis=1)                              # availability: his chance of joining any club in our leagues
    res = {"club": [], "model": [], "avail": [], "avail_same": [], "n_actual": []}
    lg = np.array(P.league, dtype=object)
    for c in clubs:
        own = P.tid == C.tids[c]
        act = actual[c]
        sc = J[:, c].astype(float).copy()
        sc[own] = -1
        top = np.argpartition(-sc, k)[:k]
        av = p_av.copy()
        av[own] = -1
        top_a = np.argpartition(-av, k)[:k]
        avs = av + 10.0 * (lg == C.league[c])
        avs[own] = -1
        top_s = np.argpartition(-avs, k)[:k]
        res["club"].append(c)
        res["n_actual"].append(len(act))
        for key, tp in (("model", top), ("avail", top_a), ("avail_same", top_s)):
            res[key].append(sum(1 for i in tp.tolist() if i in act))
    return {key: np.array(v) for key, v in res.items()}


# ── base rates (what is published while the player-level model is under test) ─

BANDS = ("regular", "rotation", "fringe")
BAND_LABELS = {"regular": "regular (50%+ of the club's minutes)", "rotation": "rotation (20-50%)", "fringe": "fringe (under 20%)"}
K_BAND, K_LEAGUE, K_LOAN = 30.0, 60.0, 30.0       # shrinkage (player-windows of prior weight)
REGION_OF = {t: t for t in TIERS}


def band_of(share: float) -> str:
    return "regular" if share >= 0.5 else "rotation" if share >= 0.2 else "fringe"


@dataclass
class BaseRates:
    """Departure rates in a reference window by league x role band, and on loan by region, shrunk."""
    window: str
    overall: float
    region: dict[str, float]
    league: dict[str, float]
    cell: dict[tuple[str, str], float]
    loan: dict[str, float]
    n_league: dict[str, int]
    n_cell: dict[tuple[str, str], int]
    n_loan: dict[str, int]
    n: int

    def rate(self, league: str, share: float, on_loan: bool) -> tuple[float, str]:
        """(rate, basis) for a player: on loan -> his region's on-loan rate; else his league x band cell."""
        reg = V.LEAGUE_TIERS.get(league, "")
        if on_loan:
            return self.loan.get(reg, self.overall), "loan"
        b = band_of(share)
        if (league, b) in self.cell:
            return self.cell[(league, b)], "league_band"
        return self.league.get(league, self.region.get(reg, self.overall)), "region"

    def to_json(self) -> dict:
        return {"window": self.window, "n": self.n, "overall": round(self.overall, 4),
                "region": {k: round(v, 4) for k, v in self.region.items()},
                "league": {k: {"rate": round(v, 4), "n": self.n_league.get(k, 0)} for k, v in self.league.items()},
                "cell": {f"{l}|{b}": {"rate": round(v, 4), "n": self.n_cell.get((l, b), 0)} for (l, b), v in self.cell.items()},
                "loan": {k: {"rate": round(v, 4), "n": self.n_loan.get(k, 0)} for k, v in self.loan.items()}}


def base_rates(P: Panel) -> BaseRates:
    y = P.y
    share, loan = P.info["share"], P.info["on_loan"] > 0
    overall = float(y.mean())
    region: dict[str, float] = {}
    for reg in TIERS:
        s = np.array([V.LEAGUE_TIERS.get(l, "") == reg for l in P.league])
        region[reg] = float((y[s].sum() + K_LEAGUE * overall) / (s.sum() + K_LEAGUE))
    league, n_league, cell, n_cell, lo, n_lo = {}, {}, {}, {}, {}, {}
    for lg in sorted(set(P.league)):
        s = np.array([l == lg for l in P.league]) & ~loan
        r0 = region.get(V.LEAGUE_TIERS.get(lg, ""), overall)
        league[lg] = float((y[s].sum() + K_LEAGUE * r0) / (s.sum() + K_LEAGUE))
        n_league[lg] = int(s.sum())
        for b in BANDS:
            sb = s & np.array([band_of(x) == b for x in share])
            cell[(lg, b)] = float((y[sb].sum() + K_BAND * league[lg]) / (sb.sum() + K_BAND))
            n_cell[(lg, b)] = int(sb.sum())
    for reg in TIERS:
        s = loan & np.array([V.LEAGUE_TIERS.get(l, "") == reg for l in P.league])
        lo[reg] = float((y[s].sum() + K_LOAN * region[reg]) / (s.sum() + K_LOAN))
        n_lo[reg] = int(s.sum())
    return BaseRates(half_label(P.s), overall, region, league, cell, lo, n_league, n_cell, n_lo, len(P))


def base_probs(P: Panel, B: BaseRates) -> tuple[np.ndarray, list[str]]:
    out, basis = np.zeros(len(P)), []
    for i in range(len(P)):
        r, b = B.rate(P.league[i], float(P.info["share"][i]), bool(P.info["on_loan"][i] > 0))
        out[i] = r
        basis.append(b)
    return out, basis


# The Model page's text (meta.method), so the page and the payload say the same thing.
METHOD = (
    "Chance of moving: the share of players like him who left their club in the latest transfer window of the same "
    "kind (last winter for the coming winter), by league and role (regular, rotation, fringe; on loan by region), "
    "from Sofascore's club transfer lists and player histories and our line-ups. It is a base rate, not a player-level "
    "forecast: our player-level model was tested on a held-out window and did not beat the base rate, because the "
    "winter and summer windows move different players (the Americas' main window is our winter, Europe's our summer). "
    "A region-aware version is being forward-tested on this winter's window. If he moves, how (transfer, free, loan, "
    "loan ending, release) and where (same league, a stronger or weaker one, outside our leagues) come from models that "
    "beat the base rates on the held-out window. Targets rank players by their chance of joining the club: availability "
    "x a model of which clubs movers join (league, region, strength, quality against the club's players, the club's "
    "expected departures at the position), which beat availability alone on the held-out window. No contract data: "
    "Transfermarkt's, Spotrac's and similar sites' terms forbid reuse, and Sofascore's contract end dates are a "
    "snapshot of today only, so no model here can learn from them. Windows are halves of the year (May-October, "
    "November-April); every league's registration period falls inside its half."
)

# ── the pre-registered validation (docs/research/football_moves.md), fixed numbers ─

VALIDATION = {
    "registered": "2026-10-22",
    "dev": "Winter 2025/26 (5,924 player-windows, 234 clubs, 17.5% left)",
    "test": "Summer 2026 (7,100 player-windows, 274 clubs, 31.8% left)",
    "leave": {"passed": False, "ll_model": 0.6729, "ll_base": 0.6262, "ll_diff_ci": [0.0468, 0.0286, 0.0654], "auc": 0.577,
              "calib_slope": 0.302,
              "why": "a winter-trained model did not carry to the summer window: in the winter half the Americas' clubs "
                     "(their main window) lose players and Europe's keep them; in the summer half it is the other way round"},
    "type": {"passed": True, "ll_model": 0.9978, "ll_base": 1.1170, "ll_diff_ci": [-0.1192, -0.1489, -0.0897],
             "accuracy_movers": 0.575},
    "dest": {"passed": True, "n": 1506, "ll_model": 1.1772, "ll_base": 1.3266, "ll_diff_ci": [-0.1494, -0.1883, -0.1121]},
    "arrivals": {"passed": False, "dev_model": 5.967, "dev_base": 2.127, "spearman": -0.228},
    "targets": {"passed": True, "clubs": 251, "signings": 840, "precision10": 0.0028, "precision10_avail": 0.0004,
                "precision10_same_league": 0.0024, "precision10_random": 0.0005, "hit25": 0.092, "hit25_same_league": 0.104,
                "diff_avail_ci": [0.0024, 0.0008, 0.0044], "diff_same_ci": [0.0004, -0.0012, 0.0020]},
    "choice": {"n": 840, "ll_model": -4.888, "ll_uniform": -5.610},
}


# ── the build ────────────────────────────────────────────────────────────────

TARGETS_PER_CLUB = 10
TARGET_MIN_MINUTES = 450            # a target has played this much for his club in the last 12 months ...
TARGET_MIN_GAP = 0.0                # ... and rates at least at the club's level in his unit (he would improve it)
AFFORD_CUTOFF = 1.5                 # as value_payloads: a target over 1.5 x the buyer's 90th-percentile budget is left out
MIN_PANEL = 1000                    # a completed window needs this many player-windows to be used
# Labels are complete from this window on: the store's club lists (Sofascore's club transfer pages, about nine
# months deep when the rotation began on 16 October 2026) reach back to about December 2025; earlier windows have
# only the rated players' career histories, so their departures would be undercounted.
LABELS_FROM = date(2025, 11, 1)
P_FIELDS = ["id", "tid", "p", "basis", "band", "loan", "share", "types", "dests", "p_club"]


def horizon_of(today: date) -> date:
    """The window the page forecasts: the half that contains today + 60 days (its opening day)."""
    return half_start(date.fromordinal(today.toordinal() + 60))


def completed_windows(today: date, first_day: date) -> list[date]:
    """Window openings whose half has (all but two weeks) ended, after the first day of line-ups."""
    out = []
    s = half_start(first_day)
    while True:
        s = date(s.year, 11, 1) if s.month == 5 else date(s.year + 1, 5, 1)
        if s.toordinal() + HALF_DAYS - 14 > today.toordinal():
            break
        if s >= LABELS_FROM:
            out.append(s)
    return out


def _round(x, n=4):
    if x is None:
        return None
    f = float(x)
    return round(f, n) if math.isfinite(f) else None


def _why(cur: Panel, j: int, club_name: dict[int, str], same_lg: bool, stronger: bool, qgap: float, unit: str) -> str:
    share = float(min(cur.info["share"][j], 1.0))
    parts = [f"{band_of(share)} at {club_name.get(int(cur.tid[j])) or 'his club'} ({int(round(100 * share))}% of minutes)"]
    parts.append("same league" if same_lg else ("from a stronger league" if stronger else "from a weaker league"))
    if cur.info["on_loan"][j] > 0:
        parts.append("on loan there")
    parts.append(f"rated {qgap:+.2f} against your {UNIT_NAMES[unit].lower()}")
    return "; ".join(parts)


def build_moves(R: V.Rows, moves: list[dict], dob: dict[str, str], offsets: dict[str, float], today: date,
                followed: set[int], club_name: dict[int, str], player_info: dict[int, dict],
                club_of: dict[str, dict | None] | None = None, fee_fn=None, budgets: dict[int, dict] | None = None,
                min_panel: int = MIN_PANEL) -> dict:
    """
    Every followed club's players' chance of leaving in the coming window (base rates of the latest window of the
    same kind, because the player-level model has not passed its test), how and where to if they move (models that
    passed), each club's expected departures and arrivals by position (base rates) and its ranked targets
    (availability x the destination-club model, which passed). Returns {"players", "clubs", "meta"}.
    """
    t0 = datetime.now(timezone.utc)
    L = Lineups(R, set(offsets))
    rec = Records.build(moves)
    horizon = horizon_of(today)
    first = date.fromordinal(int(L.day.min())) if L.day.size else today
    labelled: list[Panel] = []
    for s in completed_windows(today, first):
        P = build_panel(L, rec, dob, s, offsets, labels=True, until=today)
        if len(P) >= min_panel:
            labelled.append(P)
    meta: dict[str, Any] = {"horizon": half_label(horizon), "horizon_start": horizon.isoformat(), "today": today.isoformat(),
                            "windows": [{"window": half_label(P.s), "n": len(P), "rate": _round(P.y.mean())} for P in labelled],
                            "validation": VALIDATION}
    same = [P for P in labelled if P.s.month == horizon.month]
    if not labelled or not same:
        meta.update({"ok": False, "reason": "no completed window of the same kind with line-ups before it"})
        return {"players": {"fields": P_FIELDS, "rows": []}, "clubs": {}, "meta": meta}
    ref = same[-1]
    B = base_rates(ref)
    cur = build_panel(L, rec, dob, today, offsets, labels=False)
    F = {c: i for i, c in enumerate(FEATURES)}
    cur.X[:, F["summer"]] = 1.0 if horizon.month == 5 else 0.0
    # Players Sofascore's squads already list at another club have moved: out of the population.
    if club_of:
        keep = np.array([(club_of.get(str(int(pp))) or {}).get("tid") in (None, int(t))
                         for pp, t in zip(cur.pid.tolist(), cur.tid.tolist())], dtype=bool)
        cur = _subset(cur, keep)
    p, basis = base_probs(cur, B)
    # Type and destination if he moves (pooled over the labelled windows, the window's kind as a term).
    allp = _concat(labelled)
    ti = np.zeros(len(allp), dtype=int)
    for i, (yy, t) in enumerate(zip(allp.y.tolist(), allp.typ)):
        if yy and t:
            ti[i] = TYPES.index(t) + 1
    tc, dc = cols_of(TYPE_FEATURES), cols_of(DEST_FEATURES)
    mv = ti > 0
    tm = fit_softmax(allp.X[mv][:, tc], ti[mv] - 1, TYPE_FEATURES, TYPES, 10.0)
    di = np.array([DESTS.index(d) if d else -1 for d in allp.dest])
    dm = fit_softmax(allp.X[di >= 0][:, dc], di[di >= 0], DEST_FEATURES, DESTS, 10.0)
    PT = tm.predict(cur.X[:, tc])
    PD = dm.predict(cur.X[:, dc])
    ptc = p * (1.0 - PT[:, TYPES.index("release")] - PT[:, TYPES.index("loan_end")]) * (1.0 - PD[:, DESTS.index("outside")])
    # The destination-club model, on every labelled window's movers to our leagues.
    groups = []
    for P in labelled:
        C = club_tables(P, base_probs(P, base_rates(P))[0])
        allc = np.arange(C.tids.size)
        for j in range(len(P)):
            if not P.y[j] or P.typ[j] in ("release", "loan_end") or P.dest_tid[j] is None:
                continue
            c = C.ix.get(int(P.dest_tid[j]))
            o = C.ix[int(P.tid[j])]
            if c is None or c == o:
                continue
            cand = allc[allc != o]
            groups.append((choice_rows(P, C, j, cand), int(np.flatnonzero(cand == c)[0])))
    cl = fit_clogit(groups, 1.0) if groups else None
    Cc = club_tables(cur, p)
    J = join_probs(cur, Cc, cl, ptc) if cl is not None else np.zeros((len(cur), Cc.tids.size), dtype=np.float32)
    nclub = Cc.tids.size
    # Arrivals: the reference window's arrivals per club in each league, its position mix.
    Cr = club_tables(ref, base_probs(ref, B)[0])
    y_tot, y_by = club_arrivals(moves, Cr, ref.s, ref.s.toordinal() + HALF_DAYS)
    mix_all = (y_by.sum(axis=0) + 1.0) / (y_by.sum() + 4.0)
    arr_league: dict[str, tuple[float, np.ndarray, int]] = {}
    for lg in set(Cr.league):
        s = np.array([x == lg for x in Cr.league])
        mix = (y_by[s].sum(axis=0) + 8.0 * mix_all) / (y_by[s].sum() + 8.0)
        arr_league[lg] = (float(y_tot[s].mean()), mix, int(s.sum()))
    reg_mean: dict[str, float] = {}
    for reg in TIERS:
        s = np.array([V.LEAGUE_TIERS.get(x, "") == reg for x in Cr.league])
        if s.any():
            reg_mean[reg] = float(y_tot[s].mean())
    # ── players ──
    rows = []
    for i in range(len(cur)):
        rows.append([str(int(cur.pid[i])), int(cur.tid[i]), _round(p[i], 3), basis[i], band_of(float(cur.info["share"][i])),
                     1 if cur.info["on_loan"][i] > 0 else 0, _round(min(cur.info["share"][i], 1.0), 2),
                     [_round(x, 3) for x in PT[i]], [_round(x, 3) for x in PD[i]], _round(ptc[i], 3)])
    rows.sort(key=lambda r: -(r[2] or 0))
    # ── clubs ──
    clubs: dict[int, dict] = {}
    for t in sorted(followed):
        c = Cc.ix.get(int(t))
        if c is None:
            continue
        mine = np.flatnonzero(cur.tid == t)
        lg = Cc.league[c]
        reg = V.LEAGUE_TIERS.get(lg, "")
        if lg in arr_league:
            lam_c, mix, n_cl = arr_league[lg]
            arr_basis = "league"
        else:
            lam_c, mix, n_cl = reg_mean.get(reg, float(y_tot.mean())), mix_all, 0
            arr_basis = "region"
        exp_in = lam_c * mix
        out_u = {u: 0.0 for u in LETTER_UNITS}
        for i in mine.tolist():
            lu = int(cur.letter[i]) if cur.letter[i] >= 0 else 2
            out_u[LETTER_UNITS[lu]] += float(p[i])
        col = J[:, c].astype(float).copy()
        col[mine] = -1.0
        targets = []
        summer_b = ((budgets or {}).get(int(t)) or {}).get("summer") or {}
        for j in np.argsort(-col).tolist():
            if col[j] <= 0 or len(targets) >= TARGETS_PER_CLUB:
                break
            lu = int(cur.letter[j]) if cur.letter[j] >= 0 else 2
            qgap = float(cur.info["q"][j] - Cc.level[c, lu])
            if cur.info["min"][j] < TARGET_MIN_MINUTES or qgap < TARGET_MIN_GAP:
                continue
            pid = int(cur.pid[j])
            info = player_info.get(pid) or {}
            fee = fee_fn(pid, int(t)) if fee_fn is not None else None
            afford = None
            if fee is not None and summer_b.get("hi80") is not None:
                if fee[0] > AFFORD_CUTOFF * max(float(summer_b["hi80"]), 1.0):
                    continue
                afford = "yes" if fee[0] <= float(summer_b["hi"]) else "stretch" if fee[0] <= float(summer_b["hi80"]) else "no"
            unit = LETTER_UNITS[lu]
            need = float(Cc.ed[c, lu] / SLOTS[unit])
            share_c = float(col[j] / ptc[j]) if ptc[j] > 0 else 0.0
            same_lg = cur.league[j] == lg
            stronger = offsets.get(cur.league[j], 0.0) > offsets.get(lg, 0.0)
            age = cur.info["age"][j]
            targets.append({
                "id": str(pid), "name": info.get("name"), "tid": int(cur.tid[j]), "club": club_name.get(int(cur.tid[j])),
                "league": cur.league[j], "unit": unit, "role": info.get("role"), "age": int(age) if age == age else None,
                "p_join": _round(col[j], 4), "p_move": _round(p[j], 3), "p_club": _round(ptc[j], 3),
                "plaus": _round(share_c * (nclub - 1), 2), "q_gap": _round(qgap, 2), "need": _round(need, 2),
                "proj": _round(info.get("proj"), 3), "fee": _round(fee[0], -4) if fee else None, "afford": afford,
                "why": _why(cur, j, club_name, same_lg, stronger, qgap, unit),
            })
        roster = sorted(([str(int(cur.pid[i])), _round(p[i], 3), TYPES[int(np.argmax(PT[i]))]] for i in mine.tolist()),
                        key=lambda r: -(r[1] or 0))
        clubs[int(t)] = {
            "horizon": half_label(horizon),
            "basis": {"leave": "base_rate", "window": B.window, "arrivals": arr_basis, "arrivals_clubs": n_cl},
            "expected_out": {u: _round(v, 2) for u, v in out_u.items()}, "out_total": _round(sum(out_u.values()), 2),
            "expected_in": {LETTER_UNITS[u]: _round(exp_in[u], 2) for u in range(4)}, "in_total": _round(lam_c, 2),
            "p_add": {LETTER_UNITS[u]: _round(1.0 - math.exp(-exp_in[u]), 3) for u in range(4)},
            "roster": roster, "targets": targets,
        }
    meta.update({
        "ok": True, "method": METHOD, "reference": B.to_json(), "n_players": len(rows), "n_clubs": len(clubs),
        "types": list(TYPES), "type_labels": TYPE_LABELS, "dests": list(DESTS), "dest_labels": DEST_LABELS,
        "units": {u: UNIT_NAMES[u] for u in LETTER_UNITS}, "bands": BAND_LABELS,
        "models": {"type": tm.to_json(), "dest": dm.to_json(), "choice": cl.to_json() if cl is not None else None,
                   "choice_movers": len(groups)},
        "arrivals": {"window": B.window, "mean_per_club": _round(float(y_tot.mean()), 2), "mix": [_round(x, 3) for x in mix_all]},
        "runtime_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 1),
    })
    logger.info("moves: %d players, %d clubs, horizon %s, base window %s (rate %.3f); %.1fs", len(rows), len(clubs),
                half_label(horizon), B.window, B.overall, meta["runtime_s"])
    return {"players": {"fields": P_FIELDS, "rows": rows}, "clubs": clubs, "meta": meta}


def _subset(P: Panel, keep: np.ndarray) -> Panel:
    idx = np.flatnonzero(keep)
    return Panel(P.s, P.pid[idx], P.tid[idx], P.letter[idx], [P.league[i] for i in idx], P.X[idx],
                 P.y[idx] if P.y is not None else None, [P.typ[i] for i in idx] if P.typ else [],
                 [P.dest[i] for i in idx] if P.dest else [], [P.dest_tid[i] for i in idx] if P.dest_tid else [],
                 {k: v[idx] for k, v in P.info.items()})


def _concat(ps: list[Panel]) -> Panel:
    return Panel(ps[-1].s, np.concatenate([p.pid for p in ps]), np.concatenate([p.tid for p in ps]),
                 np.concatenate([p.letter for p in ps]), sum((p.league for p in ps), []), np.vstack([p.X for p in ps]),
                 np.concatenate([p.y for p in ps]), sum((p.typ for p in ps), []), sum((p.dest for p in ps), []),
                 sum((p.dest_tid for p in ps), []), {k: np.concatenate([p.info[k] for p in ps]) for k in ps[0].info})
