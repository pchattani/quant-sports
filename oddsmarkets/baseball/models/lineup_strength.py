"""
Lineup strength (MLB): how much better or worse a posted lineup is than the team's typical lineup, in wOBA points.
Added 22 October 2026 for the market layer (docs/research/mlb_edge.md, "Round 3").

Player value: a Marcel-like wOBA on the date (nothing from the date itself or later): the season to date and the three
seasons before, weights 5 / 4 / 3 / 2 on Savant's woba_value / woba_denom sums, regressed with 1,200 denominator
units to 0.305 (a hitter with no history is a below-average regular). Pitchers batting count as they hit.

Lineup strength of nine batters: slot-weighted mean of their values (expected plate appearances by slot, 4.65 for
the lead-off man down to 3.77 for the ninth). The typical lineup is the mean strength of the team's last 15 lineups
(any games before the date, this season or last), each re-valued with the same day's player values, so a change in
the number reflects who is in the lineup and not a change in how the players are rated.

    delta = strength(posted lineup) - typical             (wOBA points; about 0.010 = one regular out)

Which lineup is "posted" depends on the decision time: the live site uses whatever the store holds at build time; the
research uses the earliest archived pre-game state of the game feed (scripts/mlb_lineup_snapshots.py), never the
lineup that actually took the field.

What the numbers say (2017-2021, scripts/mlb_round3.py): the simulation, which prices the posted lineup directly,
moves its home win logit by SIM_LOGIT_PER_WOBA = 8.9 per unit of (delta_home - delta_away) (0.010 wOBA = 0.089 logit,
about 2 points of win probability); the closing line moves 6.1. The difference is real (what the market layer leaves
has slope -2.4, se 0.26) but too small to score: a lineup term in the layer gains nothing on log-loss (+0.00001, CI
-0.00016 to +0.00018), so the layer has none. The game page shows delta and the simulation's average response.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio

SLOT_PA = np.array([4.65, 4.55, 4.45, 4.35, 4.25, 4.13, 4.01, 3.90, 3.77])
SEASON_W = (5.0, 4.0, 3.0, 2.0)          # season to date, S-1, S-2, S-3
REG_N = 1200.0
REG_TARGET = 0.305
TYPICAL_N = 15
SIM_LOGIT_PER_WOBA = 8.9                 # the simulation's average response to delta_home - delta_away (2017-2021)


def _sums(level: str, season: int) -> pd.DataFrame | None:
    from oddsmarkets.baseball.models import projections as PJ
    try:
        pa = PJ.pa_table(level, season)
    except Exception:  # noqa: BLE001
        return None
    if pa is None or not len(pa):
        return None
    pa = pa[pa["game_type"].astype(str) == "R"] if (pa["game_type"].astype(str) == "R").any() else pa
    return pa[["game_date", "batter", "woba_value", "woba_denom"]].assign(
        batter=pa["batter"].astype(str), game_date=pa["game_date"].astype(str).str[:10])


class Values:
    """Player values for one season, on any date of it (`on(d)`), from that season's PAs before d and the three
    seasons before."""

    def __init__(self, level: str, season: int):
        self.season = season
        prior_v: dict[str, float] = {}
        prior_d: dict[str, float] = {}
        for i, s in enumerate((season - 1, season - 2, season - 3)):
            t = _sums(level, s)
            if t is None:
                continue
            g = t.groupby("batter")[["woba_value", "woba_denom"]].sum()
            w = SEASON_W[i + 1]
            for pid, v, dn in zip(g.index, g["woba_value"].to_numpy(float), g["woba_denom"].to_numpy(float)):
                prior_v[pid] = prior_v.get(pid, 0.0) + w * v
                prior_d[pid] = prior_d.get(pid, 0.0) + w * dn
        self.prior_v, self.prior_d = prior_v, prior_d
        cur = _sums(level, season)
        if cur is not None and len(cur):
            daily = cur.groupby(["game_date", "batter"])[["woba_value", "woba_denom"]].sum().reset_index()
            self.days = np.array(sorted(daily["game_date"].unique()))
            self.daily = daily
        else:
            self.days, self.daily = np.array([], dtype=object), None
        self._cache: dict[str, dict[str, float]] = {}

    def on(self, d: str) -> dict[str, float]:
        """{pid: value} from games before date d (players absent take REG_TARGET via `value`)."""
        d = str(d)[:10]
        k = int(np.searchsorted(self.days, d, side="left"))         # days strictly before d
        key = self.days[k - 1] if k else ""
        if key in self._cache:
            return self._cache[key]
        cv: dict[str, float] = {}
        cd: dict[str, float] = {}
        if k and self.daily is not None:
            g = self.daily[self.daily["game_date"] < d].groupby("batter")[["woba_value", "woba_denom"]].sum()
            cv = dict(zip(g.index, g["woba_value"].to_numpy(float)))
            cd = dict(zip(g.index, g["woba_denom"].to_numpy(float)))
        out = {}
        for pid in set(self.prior_v) | set(cv):
            v = self.prior_v.get(pid, 0.0) + SEASON_W[0] * cv.get(pid, 0.0)
            dn = self.prior_d.get(pid, 0.0) + SEASON_W[0] * cd.get(pid, 0.0)
            out[pid] = (v + REG_N * REG_TARGET) / (dn + REG_N)
        self._cache = {key: out}               # one date at a time (games are processed in date order)
        return out


def strength(lineup: Iterable, vals: dict[str, float]) -> float | None:
    lu = [str(x) for x in (lineup or []) if x not in (None, "")]
    if len(lu) != 9:
        return None
    v = np.array([vals.get(p, REG_TARGET) for p in lu])
    return float(SLOT_PA @ v / SLOT_PA.sum())


def history_lineups(stores: Iterable[dict]) -> dict[str, list[tuple[str, list[str]]]]:
    """{team: [(date, lineup), ...]} in date order from the final games of the given stores (lineups that took the
    field: legitimate for past games)."""
    out: dict[str, list] = {}
    games = []
    for st in stores:
        for g in ((st or {}).get("games") or {}).values():
            if g.get("status") == "final" and g.get("lineups"):
                games.append(g)
    games.sort(key=lambda g: (str(g.get("date")), str(g.get("start") or ""), str(g.get("gpk"))))
    for g in games:
        for tid, lu in (g.get("lineups") or {}).items():
            if lu and len(lu) == 9:
                out.setdefault(str(tid), []).append((str(g["date"])[:10], [str(x) for x in lu]))
    return out


def typical(team: str, d: str, hist: dict[str, list], vals: dict[str, float], n: int = TYPICAL_N) -> float | None:
    """Mean strength of the team's last n lineups before date d, valued with `vals`."""
    rows = hist.get(str(team)) or []
    lo, hi = 0, len(rows)
    while lo < hi:                       # first index with date >= d
        mid = (lo + hi) // 2
        if rows[mid][0] < str(d)[:10]:
            lo = mid + 1
        else:
            hi = mid
    k = lo
    prev = rows[max(0, k - n):k]
    if len(prev) < 5:
        return None
    s = [strength(lu, vals) for _, lu in prev]
    s = [x for x in s if x is not None]
    return float(np.mean(s)) if s else None


def delta(team: str, d: str, lineup: Iterable | None, hist: dict[str, list], vals: dict[str, float]) -> float | None:
    """strength(lineup) - typical (wOBA points), or None (no posted lineup, or too little history)."""
    if not lineup:
        return None
    s = strength(lineup, vals)
    t = typical(team, d, hist, vals)
    if s is None or t is None:
        return None
    return s - t


def season_deltas(level: str, season: int, lineups: dict[str, dict[str, list]] | None = None) -> pd.DataFrame:
    """Research: per final game of the season, lu_h / lu_a (delta of each side) for the given lineups
    ({gpk: {"home": [...], "away": [...]}}; default the store's final lineups) and the typical strengths."""
    st = _dio.load_store(level, season)
    prev = _dio.load_store(level, season - 1)
    hist = history_lineups([prev, st])
    V = Values(level, season)
    games = [g for g in (st.get("games") or {}).values() if g.get("status") == "final"]
    games.sort(key=lambda g: (str(g.get("date")), str(g.get("gpk"))))
    rows = []
    for g in games:
        d = str(g["date"])[:10]
        vals = V.on(d)
        h, a = str(g["home"]), str(g["away"])
        if lineups is not None:
            L = lineups.get(str(g["gpk"])) or {}
            lh, la = L.get("home"), L.get("away")
        else:
            lu = g.get("lineups") or {}
            lh, la = lu.get(h), lu.get(a)
        th, ta = typical(h, d, hist, vals), typical(a, d, hist, vals)
        sh, sa = strength(lh, vals), strength(la, vals)
        rows.append({"gpk": str(g["gpk"]), "date": d, "lu_h": None if sh is None or th is None else sh - th,
                     "lu_a": None if sa is None or ta is None else sa - ta, "typ_h": th, "typ_a": ta})
    return pd.DataFrame(rows)


def game_block(home: str, away: str, d: str, lineups: dict, hist: dict[str, list], vals: dict[str, float],
               p_home: float | None = None) -> dict | None:
    """The game page's lineup-strength block: per side {"strength", "typical", "delta"} (wOBA, 3 dp) and, with the
    model's home win probability, the simulation's average response to the two lineups ("effect_home", probability
    points): p(1-p) x SIM_LOGIT_PER_WOBA x (delta_home - delta_away)."""
    out: dict = {}
    for side, tid in (("home", home), ("away", away)):
        lu = lineups.get(side)
        s, t = strength(lu, vals), typical(tid, d, hist, vals)
        out[side] = {"strength": None if s is None else round(s, 3), "typical": None if t is None else round(t, 3),
                     "delta": None if s is None or t is None else round(s - t, 4)}
    dh, da = out["home"]["delta"], out["away"]["delta"]
    if dh is None and da is None:
        return None
    if p_home is not None and 0 < p_home < 1:
        out["effect_home"] = round(float(p_home * (1 - p_home) * SIM_LOGIT_PER_WOBA * ((dh or 0.0) - (da or 0.0))), 4)
    return out

