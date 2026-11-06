"""Walk-forward DOTS ratings (no look-ahead).

Each stream (sex x equipment group) is its own scale. For a meet, every lifter's pre-meet rating is
the decayed mean of their past SBD DOTS, shrunk to the stream mean:

    r = (k0 * m0 + sum w * dots) / (k0 + sum w),  w = 0.5 ** (age_days / half_life)

m0 is the mean DOTS of the stream in the training window (so a newcomer is an average lifter of that
stream, not zero). Until 6 Nov 2026 one global mean was used for all six streams; the per-stream prior
is one of the components scored on the sealed test (models/backtest.py). Residual = actual dots - pre.

Besides the rating, each walked row carries what a forecast may know before the meet: the lifter's
previous scored DOTS (last and best), meets so far, days since the last one, and the book's state
after the row (st_t, st_s, st_w), from which the rating on any later date is rebuilt without
re-walking (rating_at), the source of the rankings' 90-day movement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import store


@dataclass(frozen=True)
class Params:
    half_life: float = 365.0
    k0: float = 4.0
    m0: float = 400.0          # the fallback prior; walk(m0=...) gives each stream its own
    min_field: int = 8         # meets smaller than this are not used as updates (the residual is noise)


# chosen on SBD 1990-2019 by RMSE of pre-meet DOTS (models/backtest.py tune; the grid is in tuning.csv). The site
# shipped on 4 Nov 2026 with half_life 365, k0 4 and one global prior: on the sealed test that missed by 57.6 DOTS a
# meet, worse than the last meet alone (31.9); the heavy pull toward the mean dragged every strong lifter down.
CHOSEN = Params(half_life=180.0, k0=0.02)


def stream_of(sex, eq) -> str | None:
    if sex not in ("M", "F") or eq not in ("raw", "wraps", "equipped"):
        return None
    return ("men_" if sex == "M" else "women_") + {"raw": "raw", "wraps": "wraps", "equipped": "eq"}[eq]


def load_scored(entries: pd.DataFrame | None = None) -> pd.DataFrame:
    """SBD rows with a total and DOTS, a bodyweight, and a stream we rate."""
    df = entries if entries is not None else store.load_entries()
    if df.empty:
        return df
    df = df[(df["event"] == "SBD") & df["total"].notna() & df["dots"].notna() & df["bw"].notna()].copy()
    df = df[df["sex"].isin(("M", "F")) & df["eq"].isin(("raw", "wraps", "equipped"))]
    df["stream"] = np.where(df["sex"] == "M", "men_", "women_") + df["eq"].map(
        {"raw": "raw", "wraps": "wraps", "equipped": "eq"})
    df["date"] = pd.to_datetime(df["date"])
    # a lifter entered in two divisions at one meet (Open and Junior, say) is one performance listed twice: keep one,
    # or the second row would be forecast with the first already in the book (same-day look-ahead)
    df = df.sort_values(["total"], ascending=False).drop_duplicates(["meet_id", "pid", "stream"], keep="first")
    return df.sort_values(["date", "meet_id"]).reset_index(drop=True)


def stream_means(rows: pd.DataFrame, end: str) -> dict[str, float]:
    """Mean DOTS per stream up to `end` (the training window): each stream's newcomer prior."""
    d = rows[rows["date"] <= end]
    return {k: float(v) for k, v in d.groupby("stream")["dots"].mean().items() if np.isfinite(v)}


class _Book:
    def __init__(self, p: Params, m0: float | None = None):
        self.p = p
        self.m0 = p.m0 if m0 is None else float(m0)
        self.s: dict[str, float] = {}
        self.w: dict[str, float] = {}
        self.n: dict[str, int] = {}
        self.t: dict[str, pd.Timestamp] = {}

    def _decay(self, pid: str, t: pd.Timestamp) -> float:
        dt = (t - self.t[pid]).days
        return 0.5 ** (dt / self.p.half_life) if dt > 0 else 1.0

    def rating(self, pid: str, t: pd.Timestamp) -> float:
        if pid not in self.t:
            return self.m0
        f = self._decay(pid, t)
        return (self.p.k0 * self.m0 + self.s[pid] * f) / (self.p.k0 + self.w[pid] * f)

    def weight(self, pid: str, t: pd.Timestamp) -> float:
        return self.w[pid] * self._decay(pid, t) if pid in self.t else 0.0

    def add(self, pid: str, t: pd.Timestamp, dots: float) -> None:
        if pid in self.t:
            f = self._decay(pid, t)
            self.s[pid] = self.s[pid] * f + dots
            self.w[pid] = self.w[pid] * f + 1.0
            self.n[pid] += 1
        else:
            self.s[pid], self.w[pid], self.n[pid] = dots, 1.0, 1
        self.t[pid] = t


COLUMNS = ["stream", "meet_id", "pid", "date", "dots", "total", "bw", "sex", "eq", "tested", "pre", "weight", "n",
           "resid", "age", "last_dots", "best_dots", "gap", "first", "st_t", "st_s", "st_w", "scored"]


def walk(rows: pd.DataFrame, p: Params = CHOSEN, m0: dict[str, float] | None = None
         ) -> tuple[pd.DataFrame, dict[str, _Book]]:
    """Per-start rows with the pre-meet rating and pre-meet history, plus the finished book per stream.

    m0: a prior per stream (stream_means of the training window); a stream not in it uses p.m0.
    """
    books: dict[str, _Book] = {}
    last: dict[tuple, float] = {}
    best: dict[tuple, float] = {}
    first: dict[tuple, pd.Timestamp] = {}
    out = []
    ages = rows["age"] if "age" in rows.columns else pd.Series(np.nan, index=rows.index)
    rows = rows.assign(_age=pd.to_numeric(ages, errors="coerce"))
    for (start, meet, stream), g in rows.groupby(["date", "meet_id", "stream"], sort=False):
        book = books.get(stream)
        if book is None:
            book = books[stream] = _Book(p, (m0 or {}).get(stream))
        scored = len(g) >= p.min_field
        for pid, dots, total, bw, sex, eq, tested, age in zip(
                g["pid"], g["dots"], g["total"], g["bw"], g["sex"], g["eq"], g["tested"], g["_age"]):
            key = (stream, pid)
            pre = book.rating(pid, start)
            wt = book.weight(pid, start)
            n = book.n.get(pid, 0)
            prev_t = book.t.get(pid)
            gap = float((start - prev_t).days) if prev_t is not None else np.nan
            dots = float(dots)
            if scored:
                book.add(pid, start, dots)
            st_t = book.t.get(pid)
            out.append((stream, meet, pid, start, dots, float(total), float(bw), sex, eq, bool(tested), pre, wt, n,
                        dots - pre, float(age) if age == age else np.nan, last.get(key, np.nan),
                        best.get(key, np.nan), gap, first.get(key, start),
                        st_t if st_t is not None else pd.NaT, book.s.get(pid, np.nan), book.w.get(pid, np.nan),
                        scored))
            if scored:
                last[key] = dots
                best[key] = max(best.get(key, -1e9), dots)
                first.setdefault(key, start)
    walked = pd.DataFrame(out, columns=COLUMNS)
    return walked, books


def rating_at(walked: pd.DataFrame, at, p: Params = CHOSEN, m0: dict[str, float] | None = None) -> pd.DataFrame:
    """Every lifter's rating per stream as it stood on `at` (using only rows dated on or before it).

    -> stream, pid, rating, weight, n (scored meets so far), last (date of the last scored meet).
    """
    t = pd.Timestamp(at)
    d = walked[(walked["date"] <= t) & walked["scored"]]
    if d.empty:
        return pd.DataFrame(columns=["stream", "pid", "rating", "weight", "n", "last"])
    n = d.groupby(["stream", "pid"]).size().rename("n")
    lastrow = d.groupby(["stream", "pid"], sort=False).tail(1).set_index(["stream", "pid"])
    f = np.power(0.5, (t - lastrow["st_t"]).dt.days.clip(lower=0) / p.half_life)
    m = lastrow.index.get_level_values(0).map(lambda s: (m0 or {}).get(s, p.m0)).to_numpy(dtype=float)
    r = (p.k0 * m + lastrow["st_s"] * f) / (p.k0 + lastrow["st_w"] * f)
    out = pd.DataFrame({"rating": r, "weight": lastrow["st_w"] * f, "last": lastrow["st_t"]}).join(n)
    return out.reset_index()


def current(book: _Book, at: date | None = None, min_meets: int = 5, active_days: int = 400) -> pd.DataFrame:
    t = pd.Timestamp(at or date.today())
    rows = [(pid, book.rating(pid, t), book.weight(pid, t), book.n[pid], book.t[pid]) for pid in book.t
            if book.n[pid] >= min_meets and (t - book.t[pid]) <= timedelta(days=active_days)]
    df = pd.DataFrame(rows, columns=["pid", "rating", "weight", "meets", "last"])
    return df.sort_values("rating", ascending=False).reset_index(drop=True)


def needed_dots(book: _Book, pid: str, at, target: float) -> float | None:
    """The DOTS a lifter's next scored meet (on `at`) must reach to lift the rating to `target`."""
    if pid not in book.t:
        return None
    f = book._decay(pid, pd.Timestamp(at))
    k0, m0 = book.p.k0, book.m0
    return float(target * (k0 + book.w[pid] * f + 1.0) - k0 * m0 - book.s[pid] * f)
