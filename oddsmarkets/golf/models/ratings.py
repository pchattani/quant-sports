"""
Player skill in strokes per round against an average field, walked forward event by event (no look-ahead).

For each event, in start order across the men's tours (PGA, DP World, LIV share players at majors and co-sanctioned
events, which put them on one scale; the LPGA is its own stream):
  1. every player's pre-event rating r_i (below);
  2. each round's par for the field: e = mean over its players of (strokes + r_i), so beating e by k strokes is k
     strokes gained against an average field whatever the field's strength;
  3. each player-round's strokes gained sg = e - strokes, kept with its date.
A rating at date t is the decayed mean of a player's strokes gained shrunk to a prior:
  r = (k0 * m0 + sum w sg) / (k0 + sum w),  w = 0.5 ** (age_days / half_life)
k0 is the prior's weight in rounds. Shifting m0 shifts every field par and so every rating by the same amount (the
walk is translation-invariant): m0 only places the scale's zero, and `centre` re-zeroes ratings on the average PGA
Tour player-round of the trailing year for display.

Events in team formats are skipped. Multi-course events (Pebble Beach, the American Express) share one par per round
across their courses: ESPN gives no round's course, a known noise source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import store

MEN = ("pga", "eur", "liv")


@dataclass(frozen=True)
class Params:
    half_life: float = 365.0          # days
    k0: float = 12.0                  # prior weight, rounds
    m0: float = -1.5                  # newcomer prior, strokes per round against an average field
    min_field: int = 20               # rounds with fewer players are not scored


# chosen on PGA Tour 2005-2019 by every round's squared error (models/backtest.py tune; the grid in tuning.csv)
CHOSEN = Params(half_life=270.0, k0=2.0)


def load_rounds(tours: tuple[str, ...] = MEN, seasons: list[int] | None = None) -> pd.DataFrame:
    """Every individual player-round of the tours with its event's start date: tour, event, pid, round, strokes, date."""
    parts = []
    for t in tours:
        for s in seasons or store.seasons(t):
            ev = store.load_events(t, s)
            r = store.load_table(t, s, "rounds")
            if not len(r) or not ev:
                continue
            meta = pd.DataFrame([{"event": k, "start": v.get("start"), "team": bool(v.get("team")),
                                  "status": v.get("status")} for k, v in ev.items()])
            r = r.merge(meta, on="event", how="inner")
            r = r[~r["team"] & r["start"].notna()]
            r["tour"] = t
            parts.append(r[["tour", "event", "pid", "round", "strokes", "start"]])
    if not parts:
        return pd.DataFrame(columns=["tour", "event", "pid", "round", "strokes", "start", "date"])
    df = pd.concat(parts, ignore_index=True)
    df["start"] = pd.to_datetime(df["start"])
    df["date"] = df["start"] + pd.to_timedelta(df["round"] - 1, unit="D")
    return df.sort_values(["start", "event", "round"]).reset_index(drop=True)


class _Book:
    """Each player's decayed sums, kept at a reference date so one update is O(1)."""

    def __init__(self, p: Params):
        self.p = p
        self.s: dict[str, float] = {}       # sum w*sg at the player's reference date
        self.w: dict[str, float] = {}       # sum w
        self.n: dict[str, int] = {}         # rounds seen
        self.t: dict[str, pd.Timestamp] = {}

    def _decay(self, pid: str, t: pd.Timestamp) -> float:
        dt = (t - self.t[pid]).days
        return 0.5 ** (dt / self.p.half_life) if dt > 0 else 1.0

    def rating(self, pid: str, t: pd.Timestamp) -> float:
        if pid not in self.t:
            return self.p.m0
        f = self._decay(pid, t)
        return (self.p.k0 * self.p.m0 + self.s[pid] * f) / (self.p.k0 + self.w[pid] * f)

    def weight(self, pid: str, t: pd.Timestamp) -> float:
        return self.w[pid] * self._decay(pid, t) if pid in self.t else 0.0

    def add(self, pid: str, t: pd.Timestamp, sg: float) -> None:
        if pid in self.t:
            f = self._decay(pid, t)
            self.s[pid] = self.s[pid] * f + sg
            self.w[pid] = self.w[pid] * f + 1.0
            self.n[pid] += 1
        else:
            self.s[pid], self.w[pid], self.n[pid] = sg, 1.0, 1
        self.t[pid] = t


def walk(rounds: pd.DataFrame, p: Params = Params()) -> tuple[pd.DataFrame, pd.DataFrame, _Book]:
    """(per player-round strokes gained with the pre-event rating, per player-event pre-event ratings, the final book).

    sg rows: tour, event, pid, round, date, strokes, field_par, sg, pre;
    pre rows: event, pid, start, pre (rating), weight (decayed rounds behind it), n (rounds seen)."""
    book = _Book(p)
    sg_rows, pre_rows = [], []
    for (start, event), g in rounds.groupby(["start", "event"], sort=False):
        pids = g["pid"].unique()
        pre = {pid: book.rating(pid, start) for pid in pids}
        for pid in pids:
            pre_rows.append((event, pid, start, pre[pid], book.weight(pid, start), book.n.get(pid, 0)))
        new = []
        for rnd, gr in g.groupby("round", sort=True):
            if len(gr) < p.min_field:
                continue
            st = gr["strokes"].to_numpy(dtype=float)
            rr = np.array([pre[x] for x in gr["pid"]])
            par = float(np.mean(st + rr))
            sg = par - st
            for pid, s_, sgv, d in zip(gr["pid"], st, sg, gr["date"]):
                new.append((pid, d, sgv))
                sg_rows.append((gr["tour"].iloc[0], event, pid, int(rnd), d, s_, par, sgv, pre[pid]))
        for pid, d, sgv in new:
            book.add(pid, d, float(sgv))
    sg = pd.DataFrame(sg_rows, columns=["tour", "event", "pid", "round", "date", "strokes", "field_par", "sg", "pre"])
    pre = pd.DataFrame(pre_rows, columns=["event", "pid", "start", "pre", "weight", "n"])
    return sg, pre, book


def centre(sg: pd.DataFrame, at: pd.Timestamp, tour: str = "pga", days: int = 365) -> float:
    """The scale's offset at `at`: the mean pre-event rating over the tour's player-rounds of the trailing `days`."""
    d = sg[(sg["tour"] == tour) & (sg["date"] < at) & (sg["date"] >= at - pd.Timedelta(days=days))]
    return float(d["pre"].mean()) if len(d) else 0.0


def current(book: _Book, at: date | None = None, min_rounds: int = 8, active_days: int = 400, offset: float = 0.0) -> pd.DataFrame:
    """Ratings at `at` (default today) of players with min_rounds rounds and a round in the last active_days, less
    `offset` (from `centre`)."""
    t = pd.Timestamp(at or date.today())
    rows = [(pid, book.rating(pid, t) - offset, book.weight(pid, t), book.n[pid], book.t[pid]) for pid in book.t
            if book.n[pid] >= min_rounds and (t - book.t[pid]) <= timedelta(days=active_days)]
    df = pd.DataFrame(rows, columns=["pid", "rating", "weight", "rounds", "last"])
    return df.sort_values("rating", ascending=False).reset_index(drop=True)
