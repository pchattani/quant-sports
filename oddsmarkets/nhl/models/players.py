"""
Player ratings composed into team strength (round 4 of the model program, 22 Oct 2026: docs/research/nhl_edge.md,
"Round 4"; research code scripts/nhl_edge_r4.py).

Walk-forward RAPM on 5v5 xG (rapm.design: offence O and defence D per skater, controls for home, zone starts, score
state and back-to-backs), ridge LAM = 1,000 towards CARRY x the skater's previous end-of-season estimate (0 for a new
skater), fitted on the season's games before `through`. A team's player composition is its latest lineup (the
skaters of its last game before `through`), each weighted by 5 x his share of the lineup's expected 5v5 TOI (his mean
over his last WINDOW games, NEW_TOI seconds with none):

    OP_team = sum_i s_i O_i        DP_team = sum_i s_i D_i        s_i = 5 toi_i / sum_j toi_j

and the game model's player term replaces team strength's 5v5 xG rate (league + ev_off_h + ev_def_a) by
league + OP_h - DP_a (team_strength.expected_goals(ev_h=..., ev_a=...)): lp_h, lp_a in game.features, weighted b_p in
game.means next to the team-aggregate composition (b_xg) and the goals model (b_g).

Priors: `fitted/player_ratings.json` carries, for the last seasons, the chained end-of-season estimates the next
season starts from ({"priors": {"<season>": {pid: [o, d]}}}) and each skater's latest expected 5v5 TOI ("toi"), so a
cold CI cache needs only the current season's stints and player-games. Older seasons chain from FIRST in the cache.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D

logger = logging.getLogger(__name__)

MODEL_VERSION = "nhlplayers-1"
LAM = 1000.0
CARRY = 0.7
NEW_TOI = 600.0
WINDOW = 10
FIRST = 20102011
_MEMO: dict = {}


# ── the walk-forward RAPM of one season ─────────────────────────────────────

class SeasonRAPM:
    """Normal equations of one season's 5v5 stints, accumulated in date order and solved on demand."""

    def __init__(self, season: int, prior: dict, dates: dict | None = None):
        from oddsmarkets.nhl.models import _stints
        from oddsmarkets.nhl.models import rapm as RP
        self.RP = RP
        self.season = int(season)
        st = _stints.for_season(season)
        d = RP.design(st, "xg") if len(st) else None
        if dates is None:
            g = D.games_frame([season])
            dates = dict(zip(g["game_id"].astype(str), g["date"]))
        if d is None or d["P"] == 0:
            self.ids = np.zeros(0, np.int64)
            self.P = 0
            self.day = np.zeros(0, "datetime64[D]")
            self.n_rows = 0
            self.prior = prior
            return
        self.ids = d["ids"].astype(np.int64)
        self.P = d["P"]
        gd = pd.to_datetime(pd.Series(d["games"]).astype(str).map(dates))
        day = gd.to_numpy("datetime64[D]")
        ok = ~pd.isna(gd).to_numpy()
        X, y, w = d["X"][np.flatnonzero(ok)], d["y"][ok], d["w"][ok]
        day = day[ok]
        order = np.argsort(day, kind="mergesort")
        self.X, self.y, self.w, self.day = X[order], y[order], w[order], day[order]
        n = self.X.shape[1]
        self.Gm = np.zeros((n, n))
        self.r = np.zeros(n)
        self.pos = 0
        self.n_rows = 0
        self.m = np.zeros(n)
        for k, pid in enumerate(self.ids):
            v = prior.get(int(pid))
            if v is not None:
                self.m[k], self.m[self.P + k] = CARRY * v[0], CARRY * v[1]
        self.lv = RP._lam_vec(LAM, self.P, 0)
        self.prior = prior

    def advance(self, through=None) -> None:
        if self.P == 0:
            return
        end = len(self.day) if through is None else int(np.searchsorted(
            self.day, np.datetime64(pd.Timestamp(through).date(), "D"), "left"))
        if end > self.pos:
            Gk, rk, _ = self.RP._normal(self.X[self.pos:end], self.y[self.pos:end], self.w[self.pos:end])
            self.Gm += Gk
            self.r += rk
            self.n_rows += end - self.pos
            self.pos = end

    def solve(self) -> dict:
        """{pid: (o, d)} for every skater of the season (those without minutes yet sit at their prior)."""
        if self.P == 0:
            return {}
        b = self.m.copy() if self.n_rows == 0 else self.RP._solve(self.Gm, self.r, self.lv, self.m)[0]
        return {int(p): (float(b[k]), float(b[self.P + k])) for k, p in enumerate(self.ids)}


def rating_of(rat: dict, prior: dict, pid) -> tuple[float, float]:
    v = rat.get(int(pid))
    if v is not None:
        return v
    pv = prior.get(int(pid))
    return (CARRY * pv[0], CARRY * pv[1]) if pv is not None else (0.0, 0.0)


def composite(rat: dict, prior: dict, lineup) -> tuple[float, float] | None:
    """(OP, DP) of a lineup [(pid, expected 5v5 TOI)]."""
    if not lineup:
        return None
    tot = sum(t for _, t in lineup) or 1.0
    o = d = 0.0
    for p, t in lineup:
        v = rating_of(rat, prior, p)
        o += 5.0 * t / tot * v[0]
        d += 5.0 * t / tot * v[1]
    return o, d


# ── priors ──────────────────────────────────────────────────────────────────

def committed() -> dict:
    f = D.read_json(D.FITTED / "player_ratings.json") or {}
    return f if f.get("version") == MODEL_VERSION else {}


def _as_prior(dd: dict | None) -> dict:
    return {int(k): (float(v[0]), float(v[1])) for k, v in (dd or {}).items()}


def chain(last: int) -> dict:
    """{season: prior dict} for FIRST .. last + 1: each season's prior is the accumulated end-of-season estimates of
    the seasons before it (a skater keeps his latest). Cached in the C cache."""
    key = ("chain", int(last))
    if key in _MEMO:
        return _MEMO[key]
    cp = D.c_cache() / f"player_priors_{int(last)}.json"
    c = D.read_json(cp)
    if c and c.get("version") == MODEL_VERSION:
        out = {int(s): _as_prior(v) for s, v in c["priors"].items()}
        _MEMO[key] = out
        return out
    out, acc, s = {}, {}, FIRST
    while s <= last:
        out[s] = dict(acc)
        try:
            m = SeasonRAPM(s, acc)
            m.advance(None)
            acc = {**acc, **m.solve()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("player ratings %s: %s", s, exc)
        s = D.next_season(s)
    out[s] = dict(acc)
    D.write_json(cp, {"version": MODEL_VERSION, "priors": {str(k): {str(p): [round(v[0], 5), round(v[1], 5)]
                                                                    for p, v in d.items()} for k, d in out.items()}})
    _MEMO[key] = out
    return out


def prior_for(season: int) -> dict:
    """The prior of `season`: the committed file's when it has the season, else the cached chain, else {}."""
    c = committed()
    if str(season) in (c.get("priors") or {}):
        return _as_prior(c["priors"][str(season)])
    try:
        return chain(D.prev_season(season)).get(int(season), {})
    except Exception as exc:  # noqa: BLE001
        logger.warning("player prior %s: %s", season, exc)
        return {}


# ── lineups ─────────────────────────────────────────────────────────────────

def _player_games(season: int, build: bool = True) -> pd.DataFrame | None:
    from oddsmarkets.nhl.models import _io, _stints
    p = D.raw_root() / "cache" / "player_games" / f"{_io.sid(season)}.parquet"
    try:
        if build:
            q = _stints.player_games_cached(season)
        elif p.exists():
            q = pd.read_parquet(p)
        else:
            return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("player games %s: %s", season, exc)
        return None
    if q is None or not len(q):
        return None
    q = q[["player", "game_id", "team", "toi", "toi5"]].copy()
    try:
        grp = _io.players(season)["group"]
        q = q[q["player"].map(lambda v: grp.get(int(v)) != "G")]
    except Exception:  # noqa: BLE001
        pass
    q = q[q["toi"] > 0]
    q["game_id"] = q["game_id"].astype(str)
    return q


class LineupBook:
    """Skater-games of a season and the one before (goalies dropped) with dates and each skater's expected 5v5 TOI
    after every game (mean over his last WINDOW games through it). `lineup(team, before)`: the team's skaters in its
    last game before `before` (exclusive; None = the latest)."""

    def __init__(self, season: int, build: bool = True):
        cur = _player_games(season, build=build)
        prev = _player_games(D.prev_season(season), build=False)
        parts = [x for x in (prev, cur) if x is not None]
        if not parts:
            self.pg = pd.DataFrame(columns=["player", "game_id", "fr", "date", "m"])
            self.last = {}
            return
        pg = pd.concat(parts, ignore_index=True)
        on = set(D.seasons_on_disk())
        g = D.games_frame([s for s in (D.prev_season(season), season) if s in on])
        pg = pg.merge(g[["game_id", "date"]].assign(game_id=g["game_id"].astype(str)), on="game_id", how="inner")
        pg = pg.sort_values(["player", "date", "game_id"]).reset_index(drop=True)
        pg["m"] = pg.groupby("player")["toi5"].transform(lambda v: v.rolling(WINDOW, min_periods=1).mean())
        toi_c = committed().get("toi") or {}
        if prev is None and toi_c:
            # no previous-season games on disk: a skater's first games lean on his committed expected TOI
            n = (pg.groupby("player").cumcount() + 1).to_numpy()
            base = pg["player"].map(lambda q: toi_c.get(str(int(q)))).astype(float).to_numpy()
            k = np.minimum(n, WINDOW)
            pg["m"] = np.where(np.isfinite(base) & (n < WINDOW), (pg["m"].to_numpy() * k + np.nan_to_num(base) * (WINDOW - k))
                               / WINDOW, pg["m"].to_numpy())
        pg["fr"] = pg["team"].map(lambda t: D.franchise(D.norm_code(t)))
        self.pg = pg
        tg = pg.drop_duplicates(["fr", "game_id"])[["fr", "game_id", "date"]].sort_values(["date", "game_id"])
        self.games = {fr: (q["date"].to_numpy("datetime64[ns]"), q["game_id"].to_numpy()) for fr, q in tg.groupby("fr")}
        self.by_game = {k: list(zip(q["player"].astype(np.int64).to_numpy(), q["m"].fillna(NEW_TOI).to_numpy(float)))
                        for k, q in pg.groupby(["game_id", "fr"], sort=False)}

    def lineup(self, team: str, before=None) -> list | None:
        fr = D.franchise(team)
        g = self.games.get(fr)
        if g is None:
            return None
        k = len(g[0]) if before is None else int(np.searchsorted(g[0], np.datetime64(pd.Timestamp(before), "ns"), "left"))
        if k == 0:
            return None
        return self.by_game.get((g[1][k - 1], fr))


def lineups(season: int, through=None) -> dict:
    """{franchise: [(pid, expected 5v5 TOI)]} of every team's last game before `through` (None = the latest)."""
    b = LineupBook(season)
    return {fr: b.lineup(fr, through) for fr in b.games if b.lineup(fr, through)}


# ── the block team strength carries ──────────────────────────────────────────

def for_season(season: int, through=None) -> dict:
    """{"ok", "version", "teams": {franchise: {"op", "dp", "n"}}, "n_rows"}: the player composition of every team's
    latest lineup with ratings through `through` (exclusive)."""
    season = int(season)
    key = ("fs", season, None if through is None else str(pd.Timestamp(through).date()))
    if key in _MEMO:
        return _MEMO[key]
    prior = prior_for(season)
    m = SeasonRAPM(season, prior)
    m.advance(through)
    rat = m.solve()
    lu = lineups(season, through)
    teams = {}
    for fr, l in lu.items():
        c = composite(rat, prior, l)
        if c is not None:
            teams[fr] = {"op": round(c[0], 5), "dp": round(c[1], 5), "n": len(l)}
    out = {"ok": bool(teams), "version": MODEL_VERSION, "season": season, "teams": teams, "n_rows": int(m.n_rows),
           "through": None if through is None else str(pd.Timestamp(through).date())}
    if len(_MEMO) > 64:
        _MEMO.clear()
    _MEMO[key] = out
    return out


def player_table(season: int, through=None) -> dict:
    """{pid: {"o", "d", "team", "toi5", "share", "xgd60"}} for the skaters of every team's latest lineup (through
    `through`): his walk-forward RAPM, his expected 5v5 TOI (s), his weight in the lineup term (5 x his TOI share) and
    what he adds to his team's 5v5 xG differential per 60 through it (share x (o + d)). Others with a rating this
    season get o and d only."""
    key = ("pt", int(season), None if through is None else str(pd.Timestamp(through).date()))
    if key in _MEMO:
        return _MEMO[key]
    prior = prior_for(season)
    m = SeasonRAPM(season, prior)
    m.advance(through)
    rat = m.solve()
    out = {int(p): {"o": round(v[0], 4), "d": round(v[1], 4)} for p, v in rat.items()}
    for fr, l in lineups(season, through).items():
        tot = sum(t for _, t in l) or 1.0
        for p, t in l:
            o, d = rating_of(rat, prior, p)
            sh = 5.0 * t / tot
            out[int(p)] = {"o": round(o, 4), "d": round(d, 4), "team": fr, "toi5": round(float(t), 1),
                           "share": round(float(sh), 4), "xgd60": round(float(sh * (o + d)), 4)}
    _MEMO[key] = out
    return out


def attach(rd: dict, season: int, through=None) -> dict:
    """rd["players"] = for_season(...)["teams"] when it has every rated team; rd unchanged on any failure."""
    try:
        res = for_season(season, through)
        if res.get("ok"):
            rd["players"] = res["teams"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("player composition %s: %s", season, exc)
    return rd


def lineup_of(rd: dict, team: str) -> dict | None:
    return (rd.get("players") or {}).get(D.franchise(team))


def export(last: int, write: bool = True) -> dict:
    """fitted/player_ratings.json: the priors of the seasons last - 1 .. last + 1 and each skater's latest expected 5v5
    TOI (mean of his last WINDOW games through `last`)."""
    ch = chain(last)
    keep = [s for s in sorted(ch) if s >= D.prev_season(last)]
    toi: dict[str, float] = {}
    pg = _player_games(last, build=True)
    if pg is not None:
        g = D.games_frame([last])
        pg = pg.merge(g[["game_id", "date"]].assign(game_id=g["game_id"].astype(str)), on="game_id")
        pg = pg.sort_values(["player", "date"])
        toi = {str(int(p)): round(float(v.tail(WINDOW).mean()), 1) for p, v in pg.groupby("player")["toi5"]}
    obj: dict[str, Any] = {"version": MODEL_VERSION, "lam": LAM, "carry": CARRY, "through_season": int(last),
                           "priors": {str(s): {str(p): [round(v[0], 4), round(v[1], 4)] for p, v in ch[s].items()}
                                      for s in keep},
                           "toi": toi}
    if write:
        D.write_json(D.FITTED / "player_ratings.json", obj)
    return {"seasons": keep, "n": {str(s): len(ch[s]) for s in keep}, "toi": len(toi)}


def ev_rates(rd: dict, home: str, away: str) -> tuple[float, float] | None:
    """(5v5 xG rate of the home side, of the away side) from the player composition; None without it."""
    ph, pa = lineup_of(rd, home), lineup_of(rd, away)
    if ph is None or pa is None:
        return None
    L = rd.get("league") or {}
    base = float(L.get("ev_xg60", 2.45))
    if not math.isfinite(base):
        return None
    return base + ph["op"] - pa["dp"], base + pa["op"] - ph["dp"]
