"""
Line-up strength: how much better or worse a starting XI is than the club's usual XI.

Line-ups are announced about an hour before kick-off. The match model's ratings follow
the last few weeks of closing prices (docs/MODELS.md 2.5), so they price a club at its
usual strength; a weakened or rotated XI is news the model has not seen. This module
measures that news in the player-value currency of section 11b (goals of expected goal
difference per match):

    v_p(day)  = a * (beta . prior per-90 rates of p) + b * (prior rating of p)
                the player's matches on earlier days only, shrunk over PRIOR_MINUTES
                toward his letter's mean (value.prior_rates, evaluated at any day)
    X         = sum of v_p over today's eleven starters
    U         = mean over the club's last N line-ups (earlier days, club competitions)
                of the same sum at today's values (so form changes cancel and only
                selection remains)
    delta     = X - U

and turns it into a tilt of the match's goal rates (`tilt`):

    d = delta_home - delta_away,  t = c * d / (lam_h + lam_a)
    lam_h -> lam_h * e^t,  lam_a -> lam_a * e^-t   (expected goal difference moves by about c * d)

Research: scripts/football_lineups.py (pre-registered in docs/research/football_edge.md
"Round 3"). Everything here is pure computation over value.Rows, so it runs offline and
is tested on synthetic rows.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from oddsmarkets.football.analytics import value as V

MIN_HISTORY = 5          # a club needs this many earlier line-ups for a usual XI
XI_SIZE = 11


@dataclass
class ValueWeights:
    beta: np.ndarray        # box-score weights (sign-applied), per action
    scale: float            # a: weight of the box-score index
    rating_w: float         # b: goals per 90 per rating point
    n_fit: int = 0
    cutoff: str | None = None

    def to_json(self) -> dict:
        return {"beta": [round(float(x), 6) for x in self.beta], "scale": round(float(self.scale), 6),
                "rating_w": round(float(self.rating_w), 6), "n_fit": int(self.n_fit), "cutoff": self.cutoff}


def fit_weights(R: V.Rows, before_day: int | None = None) -> ValueWeights:
    """The section 11b weights, fitted on club matches before `before_day` (a date ordinal; None: all)."""
    club = V._club_rows(R)
    D = V.match_design(R, club)
    sel = np.ones(D.match.size, dtype=bool) if before_day is None else D.day < before_day
    if sel.sum() < V.MIN_FIT_MATCHES:
        return ValueWeights(V.default_beta(), 1.0, V.DEFAULT_RATING_W, int(sel.sum()),
                            None if before_day is None else date.fromordinal(int(before_day)).isoformat())
    idx = np.flatnonzero(sel)
    order = idx[np.argsort(D.day[idx], kind="stable")]
    beta, _h, _lam = V.fit_weights_cv(D.dA[order], D.y_xgd[order])
    a, b = V.stack_weights(D.dA[idx] @ beta, D.dR[idx], D.y_xgd[idx])
    return ValueWeights(beta, a, b, int(sel.sum()), None if before_day is None else date.fromordinal(int(before_day)).isoformat())


class PlayerIndex:
    """Each player's prior per-90 value at any day, from his club lines on earlier days."""

    def __init__(self, R: V.Rows, w: ValueWeights, m0: float = V.PRIOR_MINUTES / 90.0,
                 mean_before: int | None = None) -> None:
        self.w, self.m0 = w, m0
        club = V._club_rows(R)
        sel = np.flatnonzero(club)
        bx = (R.X[sel] @ w.beta) * w.scale                  # box-score goals in each line (its minutes)
        mins = R.mins[sel]
        rt = R.rating[sel]
        rated = np.isfinite(rt)
        rw = np.where(rated, rt, 0.0) * mins
        rm = np.where(rated, mins, 0.0)
        # Letter means (per 90): on club lines before `mean_before` (None: every line).
        lx = np.where(R.letter[sel] >= 0, R.letter[sel], 4)
        use = np.ones(sel.size, dtype=bool) if mean_before is None else R.day[sel] < mean_before
        self.mu_bx = np.zeros(5)
        self.mu_r = np.full(5, 6.7)
        for li in range(5):
            s = use & ((lx == li) if li < 4 else True)
            m = mins[s].sum()
            if m > 0:
                self.mu_bx[li] = bx[s].sum() / m * 90.0
            if rm[s].sum() > 0:
                self.mu_r[li] = rw[s].sum() / rm[s].sum()
        # Per player: days and running sums (to a day, inclusive), for searchsorted lookups.
        pid = R.pid[sel]
        order = np.lexsort((R.day[sel], pid))
        pid_o, day_o = pid[order], R.day[sel][order]
        cols = np.column_stack([bx[order], mins[order], rw[order], rm[order]])
        self._data: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        starts = np.flatnonzero(np.r_[True, pid_o[1:] != pid_o[:-1]])
        ends = np.r_[starts[1:], pid_o.size]
        for s, e in zip(starts, ends):
            self._data[int(pid_o[s])] = (day_o[s:e], np.cumsum(cols[s:e], axis=0))
        self.letter_of: dict[int, int] = {}
        for p, l in zip(R.pid[sel], R.letter[sel]):
            if l >= 0:
                self.letter_of[int(p)] = int(l)

    def totals(self, pid: int, day: int) -> np.ndarray:
        """(box goals, minutes, rating x minutes, rated minutes) on days before `day`."""
        d = self._data.get(int(pid))
        if d is None:
            return np.zeros(4)
        k = int(np.searchsorted(d[0], day, side="left"))
        return d[1][k - 1] if k > 0 else np.zeros(4)

    def value(self, pid: int, day: int, letter: int | None = None) -> float:
        """Prior value per 90 (goals of expected goal difference; the rating part without its constant)."""
        li = letter if letter is not None and letter >= 0 else self.letter_of.get(int(pid), 4)
        bx, m, rw, rm = self.totals(pid, day)
        m90 = m / 90.0
        box = (bx + self.m0 * self.mu_bx[li]) / (m90 + self.m0)
        rating = (rw + self.m0 * 90.0 * self.mu_r[li]) / (rm + self.m0 * 90.0)
        return float(box + self.w.rating_w * rating)

    def minutes(self, pid: int, day: int) -> float:
        return float(self.totals(pid, day)[1])


@dataclass
class TeamXIs:
    """Every club's starting XIs in date order: tid -> [(day, match index, [(pid, letter)])]."""

    by_team: dict[int, list[tuple[int, int, list[tuple[int, int]]]]] = field(default_factory=dict)
    by_match: dict[tuple[int, int], list[tuple[int, int]]] = field(default_factory=dict)   # (match, side) -> XI

    @classmethod
    def from_rows(cls, R: V.Rows) -> "TeamXIs":
        out = cls()
        club = V._club_rows(R)
        sel = np.flatnonzero(club & (R.start == 1))
        for i in sel:
            key = (int(R.match[i]), int(R.side[i]))
            out.by_match.setdefault(key, []).append((int(R.pid[i]), int(R.letter[i])))
        for (mi, s), xi in out.by_match.items():
            tid = int(R.m_tid[mi, s])
            # A line-up without substitute flags lists everyone as a starter: not an XI.
            if tid < 0 or len(xi) != XI_SIZE:
                continue
            out.by_team.setdefault(tid, []).append((int(R.m_day[mi]), mi, xi))
        for t in out.by_team.values():
            t.sort(key=lambda r: (r[0], r[1]))
        return out

    def earlier(self, tid: int, day: int, n: int) -> list[list[tuple[int, int]]]:
        """The club's last `n` XIs on days before `day` (most recent last)."""
        hist = self.by_team.get(int(tid)) or []
        days = [h[0] for h in hist]
        k = int(np.searchsorted(np.array(days, dtype=np.int64), day, side="left")) if days else 0
        return [h[2] for h in hist[max(0, k - n):k]]


@dataclass
class XIStrength:
    x: float                 # today's XI
    u: float                 # the usual XI (mean of the last n)
    delta: float
    n_usual: int
    players: list[dict]      # today's starters: pid, value, share of the usual XIs started
    absent: list[dict]       # usual starters not in today's XI: pid, value, share


def xi_strength(idx: PlayerIndex, xis: TeamXIs, tid: int, day: int, xi: list[tuple[int, int]],
                n: int = 10, min_history: int = MIN_HISTORY) -> XIStrength | None:
    """Today's XI against the club's usual XI, both valued at today's priors. None without enough history."""
    if len(xi) != XI_SIZE:
        return None
    hist = xis.earlier(tid, day, n)
    if len(hist) < min_history:
        return None
    vals: dict[int, float] = {}

    def v(pid: int, letter: int) -> float:
        if pid not in vals:
            vals[pid] = idx.value(pid, day, letter)
        return vals[pid]

    x = sum(v(p, l) for p, l in xi)
    starts: dict[int, int] = {}
    letters: dict[int, int] = {}
    tot = 0.0
    for h in hist:
        tot += sum(v(p, l) for p, l in h)
        for p, l in h:
            starts[p] = starts.get(p, 0) + 1
            letters.setdefault(p, l)
    u = tot / len(hist)
    today = {p for p, _ in xi}
    players = [{"pid": p, "v": v(p, l), "share": starts.get(p, 0) / len(hist)} for p, l in xi]
    absent = sorted(({"pid": p, "v": v(p, letters[p]), "share": c / len(hist)} for p, c in starts.items()
                     if p not in today and c / len(hist) >= 0.5), key=lambda r: -r["share"])
    return XIStrength(x=x, u=u, delta=x - u, n_usual=len(hist), players=players, absent=absent)


def tilt(lam_h, lam_a, d, c: float):
    """The goal rates after the line-up term: lam_h e^t, lam_a e^-t with t = c d / (lam_h + lam_a)."""
    lam_h = np.asarray(lam_h, dtype=float)
    lam_a = np.asarray(lam_a, dtype=float)
    t = c * np.asarray(d, dtype=float) / np.maximum(lam_h + lam_a, 1e-6)
    return lam_h * np.exp(t), lam_a * np.exp(-t)


def tilt_matrix(M: np.ndarray, lam_h: float, lam_a: float, d: float, c: float) -> np.ndarray:
    """
    The same tilt applied to a finished score matrix (any model: Dixon-Coles, the Elo blend):
    M'[i, j] ∝ M[i, j] e^(t i) e^(-t j). Exact for independent Poisson sides, and for the
    Dixon-Coles matrix up to the tau cells' small dependence on the rates.
    """
    if not math.isfinite(d) or c == 0 or d == 0:
        return M
    t = c * d / max(lam_h + lam_a, 1e-6)
    G = M.shape[0]
    k = np.arange(G)
    W = M * np.exp(t * k)[:, None] * np.exp(-t * k)[None, :]
    s = W.sum()
    return W / s if s > 0 else M


# ── production: the term for fixtures whose line-ups are posted ──────────────

PARAMS_PATH = Path(__file__).resolve().parents[1] / "competitions" / "league" / "data" / "model_params.json"
DEFAULT_C, DEFAULT_N = 0.75, 10
WINDOW_BEFORE_H = 3.0        # a posted XI is applied from this long before kick-off ...
WINDOW_AFTER_H = 3.0         # ... until this long after (the line shown during the match)


def term_params() -> tuple[float, int, int]:
    """(c, n_usual, min_history) from model_params.json `lineup_term` (c 0 turns the term off)."""
    try:
        block = json.loads(PARAMS_PATH.read_text(encoding="utf-8")).get("lineup_term") or {}
        return float(block.get("c", DEFAULT_C)), int(block.get("n_usual", DEFAULT_N)), int(block.get("min_history", MIN_HISTORY))
    except Exception:  # noqa: BLE001
        return DEFAULT_C, DEFAULT_N, MIN_HISTORY


def _ko(m: dict) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(m.get("date") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def posted(store: dict, now: datetime | None = None) -> dict[str, tuple[dict, dict]]:
    """gid -> (match, pre-match record) for confirmed line-ups of matches not finished, kicking off within the window."""
    now = now or datetime.now(timezone.utc)
    out = {}
    matches = store.get("matches") or {}
    for gid, rec in (store.get("prematch") or {}).items():
        m = matches.get(str(gid))
        if not isinstance(rec, dict) or not rec.get("confirmed") or not isinstance(m, dict):
            continue
        if m.get("status") in ("finished", "canceled", "cancelled", "postponed"):
            continue
        ko = _ko(m)
        if ko is None or not (now - timedelta(hours=WINDOW_AFTER_H) <= ko <= now + timedelta(hours=WINDOW_BEFORE_H)):
            continue
        out[str(gid)] = (m, rec)
    return out


def live_terms(league_stores: dict[str, dict], other_stores: dict[str, dict] | None = None,
               scopes: dict[str, str] | None = None, now: datetime | None = None) -> dict[str, dict[str, dict]]:
    """
    slug -> gid -> the line-up term of every league fixture whose confirmed XIs are in
    its store (`prematch`, written by fetch_sofascore_leagues.py in the hour before
    kick-off). Player values come from every club store's line-ups (the section 11b
    model, weights fitted on all of them); empty when nothing is posted, so a normal
    hourly build pays nothing.
    """
    now = now or datetime.now(timezone.utc)
    c, n, min_hist = term_params()
    todo = {slug: posted(st, now) for slug, st in league_stores.items()}
    todo = {k: v for k, v in todo.items() if v}
    if not todo or c <= 0:
        return {}
    col = V.ValueCollector()
    names: dict[int, str] = {}
    for slug, st in list(league_stores.items()) + list((other_stores or {}).items()):
        scope = (scopes or {}).get(slug, "club")
        if scope != "club":
            continue
        col.add_store(slug, st, scope="club")
        for pid, meta in (st.get("players") or {}).items():
            if isinstance(meta, dict) and meta.get("n") and str(pid).isdigit():
                names.setdefault(int(pid), str(meta["n"]))
    R = col.finish()
    w = fit_weights(R)
    idx = PlayerIndex(R, w)
    xis = TeamXIs.from_rows(R)
    out: dict[str, dict[str, dict]] = {}
    for slug, items in todo.items():
        for gid, (m, rec) in items.items():
            ko = _ko(m)
            day = ko.date().toordinal()
            sides = {}
            for side in ("home", "away"):
                blk = rec.get(side) or {}
                xi = [(int(p[0]), V.LETTERS.index(p[2]) if p[2] in V.LETTERS else -1) for p in blk.get("xi") or []]
                for p in blk.get("xi") or []:
                    names.setdefault(int(p[0]), str(p[1]))
                tid = m.get(f"{side}_id")
                s = xi_strength(idx, xis, int(tid), day, xi, n=n, min_history=min_hist) if tid is not None else None
                sides[side] = (blk, s)
            ok = all(s is not None for _b, s in sides.values())
            d = sides["home"][1].delta - sides["away"][1].delta if ok else None
            term = {"at": rec.get("at"), "c": c, "n_usual": n, "applied": bool(ok), "d": round(d, 3) if ok else None}
            for side, (blk, s) in sides.items():
                info: dict = {"f": blk.get("f"), "xi": [{"id": int(p[0]), "n": str(p[1]), "pos": p[2], "no": p[3]} for p in blk.get("xi") or []]}
                if blk.get("missing"):
                    info["missing"] = [{"id": x[0], "n": x[1], "type": x[2]} for x in blk["missing"]]
                if s is not None:
                    mean_u = s.u / XI_SIZE
                    by_id = {pl["pid"]: pl for pl in s.players}
                    for p in info["xi"]:
                        pl = by_id.get(p["id"])
                        if pl:
                            p["v"] = round(pl["v"] - mean_u, 3)
                            p["share"] = round(pl["share"], 2)
                    info["out"] = [{"id": a["pid"], "n": names.get(a["pid"], ""), "v": round(a["v"] - mean_u, 3), "share": round(a["share"], 2)}
                                   for a in s.absent]
                    info.update({"delta": round(s.delta, 3), "n_usual": s.n_usual})
                else:
                    info["no_history"] = True
                term[side] = info
            out.setdefault(slug, {})[gid] = term
    return out
