"""
Market-informed game model (model-improvement program, October 2026; docs/research/basketball_edge.md).

The production game model (`game.predict`: ratings + home court + rest / travel / altitude) ignores two things the
betting market prices: what earlier closing lines say about each team, and who is likely to play. This model adds
both, as a close predictor (the research model "C"):

    mk     = h_m [not neutral] + r_home - r_away          market ratings from the closing spreads of games played
                                                          before the day (weighted ridge, half-life 20 days, ridge 1,
                                                          prior = 0.6 x last season's final market ratings)
    av_t   = (S_expected - S_reference) x (1 - prior_share)    availability: the expected rotation's strength
                                                          (last game's participation; P(plays) by games missed;
                                                          last season's player values) minus what team t's rating
                                                          already reflects, points per 100
    mu_C   = const + b_mk mk + b_r rating + b_av (av_h - av_a) pace_g / 100 + b_b2b b2b + b_rest rest + ...
    margin = mu_C + cal_c0,  P(home wins) = Phi(margin / cal_sd)

The coefficients of mu_C are fitted to CLOSING SPREADS (a less noisy target than results) and (cal_c0, cal_sd) by
a probit on outcomes of out-of-sample predictions (`research/improve.py final_fit`, written by scripts/bb_fit.py to
`models/fitted/informed_<L>.json`). Totals likewise: total = const + b mk_tot + b base_total + roster O/D change +
schedule terms, fitted to closing totals.

Walk-forward on the 2024-2026 test seasons (NBA, 3,937 games with ESPN open and close prices): log-loss 0.6043 ->
0.5934 (paired difference -0.0108 [-0.0154, -0.0065]), level with ESPN's opening line (0.5930), short of the close
(0.5815); total RMSE 18.55 -> 18.44. In the WNBA the gain did not reach significance (908 games), so the WNBA keeps
the base model (`INFORMED_LEAGUES`).

Inputs come only from the store: lines are the store's `odds` (the last line ESPN showed before tip-off, which is
the close for 99 % of games), boxes give participation, the impact model of the two previous seasons gives player
values. Live games: players listed Out on ESPN's injury report get P(plays) = 0 inside the availability term
(instead of the base model's separate injury adjustment, so nothing is counted twice).

Fallback to the base model: before the season's first stored line when last season has no stored lines either, and
once 50 games have been played while fewer than half of them have a stored line (the NBA 2024 and 2025 stores carry
no lines; the 2026 store has none before mid-November 2025).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import ratings as R

logger = logging.getLogger(__name__)

INFORMED_LEAGUES: tuple[str, ...] = ("nba",)
VERSION = 1
FITTED = Path(__file__).with_name("fitted")

MK_HALF_LIFE, MK_RIDGE, MK_CARRY = 20.0, 1.0, 0.6
MK_PRIOR_DEPTH = 2                     # seasons back the market-rating prior chain is followed
MIN_LINE_SHARE, FALLBACK_AFTER = 0.5, 50

REPLACEMENT = -2.0
ROOKIE = (-2.0, -1.0, -1.0)            # (net, o, d) per 100 for a player without an earlier value
REP = np.array([REPLACEMENT, REPLACEMENT / 2, REPLACEMENT / 2])
MPG_ALPHA = 0.2                        # EWMA weight of the latest game in minutes per game
ROOKIE_MPG = 10.0
VALUE_PSEUDO_MIN = 250.0               # minutes of replacement-level evidence added to every player value
W_RAPM = 0.5                           # net value = 0.5 RAPM + 0.5 box impact
# P(plays) by the team's consecutive games the player has missed (0 = played last game); measured on NBA 2008-16 /
# WNBA 2005-16 for players averaging 24+ minutes
AVAIL = {"nba": [0.94, 0.62, 0.37, 0.24, 0.18, 0.17, 0.14, 0.12, 0.06],
         "wnba": [0.96, 0.56, 0.33, 0.21, 0.16, 0.16, 0.12, 0.08, 0.06]}
COACH = ("coach", "decision")

SPREAD_FEATS = ("mk_mu", "rating", "x_av", "b2b", "rest", "travel_1000km", "tz", "altitude", "hca")
TOTAL_FEATS = ("mk_tot", "base_total", "x_tot_av", "x_b2b_sum", "x_rest_sum", "x_early", "x_post", "x_alt_tot",
               "lg_pace", "lg_ortg")
_FIT: dict[str, dict | None] = {}


def _league(x) -> str:
    return "wnba" if str(x or "").lower() == "wnba" else "nba"


def enabled(league: str) -> bool:
    return _league(league) in INFORMED_LEAGUES and bool(fitted(league))


def fitted(league: str) -> dict | None:
    """The committed fit (`models/fitted/informed_<L>.json`, written by scripts/bb_fit.py), or None."""
    league = _league(league)
    if league not in _FIT:
        try:
            c = json.loads((FITTED / f"informed_{league}.json").read_text(encoding="utf-8"))
            _FIT[league] = c if c.get("version") == VERSION and c.get("spread") else None
        except (OSError, ValueError):
            _FIT[league] = None
    return _FIT[league]


def set_fitted(league: str, fit: dict | None) -> None:
    """Override (tests) or with None forget the in-process fit."""
    if fit is None:
        _FIT.pop(_league(league), None)
    else:
        _FIT[_league(league)] = fit


# ── market ratings ───────────────────────────────────────────────────────────

def store_lines(games: dict) -> dict[str, dict]:
    """{game_id: {"sp": home spread, "tot": total}} from the store's `odds` (the last line before tip-off)."""
    out = {}
    for gid, g in (games or {}).items():
        o = (g or {}).get("odds") or {}
        sp, tot = _num(o.get("spread_home")), _num(o.get("total"))
        if sp is not None and abs(sp) > 30:
            sp = None
        if sp is not None or tot is not None:
            out[str(gid)] = {"sp": sp, "tot": tot}
    return out


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _solve(T: int, hi, ai, y, w, neutral, prior, lam, kind) -> np.ndarray:
    X = np.zeros((len(y), T + 1))
    if kind == "spread":
        X[:, 0] = (~neutral).astype(float)
        X[np.arange(len(y)), 1 + hi] += 1.0
        X[np.arange(len(y)), 1 + ai] -= 1.0
    else:
        X[:, 0] = 1.0
        X[np.arange(len(y)), 1 + hi] += 1.0
        X[np.arange(len(y)), 1 + ai] += 1.0
    A = X.T @ (X * w[:, None])
    b = X.T @ (w * y)
    P = np.eye(T + 1) * lam
    P[0, 0] = 1e-6
    A = A + P
    b = b + P @ np.concatenate([[0.0], prior])
    if kind == "spread":
        A[0, 0] += 1e-3
        b[0] += 1e-3 * 2.5
    else:
        A[0, 0] += 1e-6
    return np.linalg.solve(A, b)


def _rows(store: dict, league: str) -> list[dict]:
    return G.finished(store.get("games") or {}, league)


def market_path(league: str, season: int, store: dict | None = None, lines: dict | None = None, prior: dict | None = None,
                days: list[date] | None = None) -> dict[date, dict]:
    """Market ratings for each day of `days` (default: every day with a finished game) from the lines of finished
    games of days <= D - 1: {day: {"h", "r": {team}, "c", "t": {team} | None, "n" lines used, "n_games"}}.
    `lines` ({game_id: {"sp", "tot"}}) replaces the store's; `prior` ({"r", "t"} centred, last season's end)."""
    st = store if store is not None else (G.load_store(league, season) or {})
    rows = _rows(st, league)
    ln = lines if lines is not None else store_lines(st.get("games") or {})
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows} | set(R.league_teams(st) if st.get("games") else []))
    if not teams:
        return {}
    ix = {t: i for i, t in enumerate(teams)}
    prior = prior or {}
    pr_r = np.array([MK_CARRY * float((prior.get("r") or {}).get(t, 0.0)) for t in teams])
    pr_t = np.array([MK_CARRY * float((prior.get("t") or {}).get(t, 0.0)) for t in teams])
    rd = np.array([r["day"] for r in rows], dtype=object)
    hi = np.array([ix[r["home"]] for r in rows], int)
    ai = np.array([ix[r["away"]] for r in rows], int)
    neu = np.array([bool(r["neutral"]) for r in rows], bool)
    sp = np.array([(ln.get(r["id"]) or {}).get("sp") if (ln.get(r["id"]) or {}).get("sp") is not None else np.nan for r in rows], float)
    tot = np.array([(ln.get(r["id"]) or {}).get("tot") if (ln.get(r["id"]) or {}).get("tot") is not None else np.nan for r in rows], float)
    want = sorted(set(days) if days is not None else set(rd.tolist()))
    out: dict[date, dict] = {}
    sol_r = sol_t = None
    for D in want:
        cut = D - timedelta(days=1)
        m = np.array([x <= cut for x in rd], bool) if len(rd) else np.zeros(0, bool)
        ms = m & np.isfinite(sp)
        if ms.any():
            w = 0.5 ** (np.array([(D - x).days for x in rd[ms]], float) / MK_HALF_LIFE)
            sol_r = _solve(len(teams), hi[ms], ai[ms], -sp[ms], w, neu[ms], pr_r, MK_RIDGE, "spread")
        else:
            sol_r = np.concatenate([[2.5], pr_r])
        mt = m & np.isfinite(tot)
        if mt.any():
            w = 0.5 ** (np.array([(D - x).days for x in rd[mt]], float) / MK_HALF_LIFE)
            sol_t = _solve(len(teams), hi[mt], ai[mt], tot[mt], w, neu[mt], pr_t, MK_RIDGE, "total")
        else:
            sol_t = None
        out[D] = {"h": float(sol_r[0]), "r": {t: float(sol_r[1 + i]) for t, i in ix.items()},
                  "c": float(sol_t[0]) if sol_t is not None else None,
                  "t": {t: float(sol_t[1 + i]) for t, i in ix.items()} if sol_t is not None else None,
                  "n": int(ms.sum()), "n_games": int(m.sum()), "prior": bool(prior.get("r"))}
    return out


def season_market_prior(league: str, season: int, depth: int = MK_PRIOR_DEPTH, lines_for=None) -> dict:
    """Last season's final market ratings ({"r", "t"}, centred), following the prior chain `depth` seasons back.
    `lines_for(season, store)` may supply lines (the local fit and backtest add the odds cache); default: the store."""
    if depth <= 0:
        return {}
    st = G.load_store(league, season - 1)
    if not st:
        return {}
    ln = lines_for(season - 1, st) if lines_for else None
    prior = season_market_prior(league, season - 1, depth - 1, lines_for)
    rows = _rows(st, league)
    if not rows:
        return {}
    last = market_path(league, season - 1, st, ln, prior, days=[rows[-1]["day"]]).get(rows[-1]["day"])
    if not last:
        return {}
    rv = np.mean(list(last["r"].values()))
    end = {"r": {t: v - float(rv) for t, v in last["r"].items()}}
    if last.get("t"):
        tv = np.mean(list(last["t"].values()))
        end["t"] = {t: v - float(tv) for t, v in last["t"].items()}
    return end


# ── availability ─────────────────────────────────────────────────────────────

def _player_values(impact: dict | None) -> dict[str, list[float]]:
    """{pid: [net, o, d, minutes]} shrunk towards a rookie with VALUE_PSEUDO_MIN minutes, clipped to +-12."""
    if not (impact or {}).get("ok"):
        return {}
    out = {}
    for pid, r in (impact.get("players") or {}).items():
        t = r.get("t")
        if t is None:
            continue
        rp = (r.get("rapm") or {}).get("t", t)
        box = (r.get("box_o") or 0.0) + (r.get("box_d") or 0.0) if r.get("box_o") is not None else t
        o, d = r.get("o"), r.get("d")
        if o is None or d is None or abs(o) > 15 or abs(d) > 15:
            o = d = t / 2
        mins = float(r.get("minutes") or 0.0)
        k = mins / (mins + VALUE_PSEUDO_MIN)

        def sh(v, rookie):
            return max(-12.0, min(12.0, k * float(v) + (1 - k) * rookie))
        net = W_RAPM * sh(rp if rp is not None else t, ROOKIE[0]) + (1 - W_RAPM) * sh(box, ROOKIE[0])
        out[str(pid)] = [net, sh(o, ROOKIE[1]), sh(d, ROOKIE[2]), mins]
    return out


def _content_key(league: str, season: int) -> str:
    from oddsmarkets.basketball import store as stmod
    from oddsmarkets.basketball.analytics import bio as _bio
    h = hashlib.sha1()
    for p in (G.store_path(league, season), stmod.table_path(league, season, "stints.json"), _bio.bio_path(league)):
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"missing")
    return h.hexdigest()


def committed_values(league: str) -> dict[str, dict]:
    """{season: {pid: [net, o, d, minutes]}} committed by scripts/bb_fit.py (`fitted/informed_values_<L>.json`) for
    the finished seasons the current season needs, so CI never refits a past season's impact model for them."""
    try:
        return json.loads((FITTED / f"informed_values_{_league(league)}.json").read_text(encoding="utf-8")).get("seasons") or {}
    except (OSError, ValueError):
        return {}


def season_player_values(league: str, season: int, use_committed: bool = True) -> dict[str, list[float]]:
    """Player values for one finished season: the committed copy, else computed from the impact model (cached on
    the content of the season's store, stints and bio)."""
    from oddsmarkets.basketball.models import impact as IM
    if use_committed:
        c = committed_values(league).get(str(int(season)))
        if c:
            return c
    if not G.load_store(league, season):
        return {}
    key = json.dumps([VERSION, "values-1", _content_key(league, season)])
    return _io.cached("informed", f"values_{league}_{season}", key, lambda: _player_values(IM.for_season(league, season))) or {}


def values_for(league: str, season: int) -> dict[str, list[float]]:
    """Values a season starts from: the season before last, overwritten by last season's where the player had 100+
    minutes last season or no earlier value."""
    out = {p: list(v) for p, v in season_player_values(league, season - 2).items()}
    for p, v in season_player_values(league, season - 1).items():
        if v[3] >= 100 or p not in out:
            out[p] = list(v)
    return out


def _vec(vals: dict, pid: str) -> np.ndarray:
    v = vals.get(pid)
    return np.array(v[:3], float) if v else np.array(ROOKIE, float)


class Rotation:
    """Per-team expected rotation for one season: `expected(team)` -> S (net, o, d per 100 for the five slots),
    `reference(team, day)` -> (S the team rating already reflects, prior share), `update(game, day)` after a game."""

    def __init__(self, league: str, vals: dict, init: dict[str, dict[str, float]], last_mpg: dict[str, float],
                 s_last: dict[str, np.ndarray]):
        self.league, self.vals = league, vals
        self.G = _io.game_minutes(league)
        self.cap = 5 * self.G
        self.av = AVAIL[league]
        self.ridge, self.hl = R.RIDGE[league], R.HALF_LIFE[league]
        self.team_of: dict[str, str] = {}
        self.st: dict[str, dict[str, dict]] = defaultdict(dict)
        for t, players in init.items():
            for pid, avail0 in players.items():
                self._add(t, pid, last_mpg.get(pid, ROOKIE_MPG), streak=0 if avail0 >= 0.5 else 3)
        self.s_last = s_last
        self.hist: dict[str, list[tuple[date, np.ndarray]]] = defaultdict(list)

    def _add(self, t, pid, mpg, streak=0):
        old = self.team_of.get(pid)
        prev = None
        if old and old != t:
            prev = self.st[old].pop(pid, None)
        self.team_of[pid] = t
        if pid not in self.st[t]:
            self.st[t][pid] = {"mpg": float(prev["mpg"] if prev else mpg), "streak": streak}

    def expected(self, t: str, out: set[str] | None = None, p_over: dict[str, float] | None = None) -> np.ndarray:
        """S of team t's expected rotation; `out` players get P(plays) = 0, `p_over` sets P(plays) per player
        (e.g. from pre-game market listings) in place of the participation-streak rate."""
        tot = np.zeros(3)
        mins = 0.0
        contrib = []
        for pid, s in (self.st.get(t) or {}).items():
            a = self.av[min(s["streak"], len(self.av) - 1)]
            if p_over and pid in p_over:
                a = float(p_over[pid])
            if out and pid in out:
                a = 0.0
            m = a * s["mpg"]
            if m <= 0:
                continue
            contrib.append((m, _vec(self.vals, pid)))
            mins += m
        scale = min(1.0, self.cap / mins) if mins > 0 else 1.0
        for m, v in contrib:
            tot += v * m * scale
        fill = max(0.0, self.cap - mins * scale)
        return (tot + REP * fill) / self.G

    def reference(self, t: str, d: date) -> tuple[np.ndarray, float]:
        prior = self.s_last.get(t)
        if prior is None:
            prior = REP + 0.0
        num = prior * self.ridge
        den = self.ridge
        for dd, s in self.hist.get(t) or []:
            w = 0.5 ** (max(0, (d - dd).days) / self.hl)
            num = num + w * s
            den += w
        return num / den, self.ridge / den

    def update(self, g: dict, d: date) -> None:
        for side in ("home", "away"):
            t = str(g[side])
            b = (g.get("box") or {}).get(t) or {}
            players = b.get("players") or []
            secs = sum(float(r[2] or 0) for r in players)
            if secs <= 0:
                continue                      # an all-zero box (NBA 2013-2018 CHI / NO) says nothing
            tot = np.zeros(3)
            for r in players:
                sec = float(r[2] or 0)
                if sec > 0:
                    tot += _vec(self.vals, str(r[0])) * sec
            self.hist[t].append((d, tot / secs * 5))
            seen = set()
            for r in players:
                pid, sec = str(r[0]), float(r[2] or 0)
                seen.add(pid)
                self._add(t, pid, ROOKIE_MPG)
                s = self.st[t][pid]
                s["mpg"] = (1 - MPG_ALPHA) * s["mpg"] + MPG_ALPHA * sec / 60.0
                s["streak"] = 0
            for row in b.get("dnp") or []:
                pid, why = str(row[0]), str(row[1] if len(row) > 1 else "").lower()
                seen.add(pid)
                self._add(t, pid, ROOKIE_MPG, streak=1)
                s = self.st[t][pid]
                if any(k in why for k in COACH):
                    s["mpg"] = (1 - MPG_ALPHA) * s["mpg"]
                    s["streak"] = 0
                else:
                    s["streak"] += 1
            for pid, s in (self.st.get(t) or {}).items():
                if pid not in seen:
                    s["streak"] += 1


def _season_actual(store: dict | None, vals: dict) -> tuple[dict[str, np.ndarray], dict[str, float], dict[str, dict[str, float]]]:
    """From a finished season: ({team: average actual S}, {pid: mpg}, {team: {pid: 1}} each player's last team)."""
    if not store:
        return {}, {}, {}
    s_sum: dict[str, np.ndarray] = {}
    s_n: dict[str, int] = defaultdict(int)
    sec_p: dict[str, float] = defaultdict(float)
    gp: dict[str, int] = defaultdict(int)
    last_team: dict[str, str] = {}
    games = sorted((g for g in (store.get("games") or {}).values() if g.get("status") == "post" and g.get("stype") in G.COUNTED),
                   key=lambda g: str(g.get("date")))
    for g in games:
        for side in ("home", "away"):
            t = str(g[side])
            players = (((g.get("box") or {}).get(t) or {}).get("players")) or []
            secs = sum(float(r[2] or 0) for r in players)
            if secs <= 0:
                continue
            tot = np.zeros(3)
            for r in players:
                pid, sec = str(r[0]), float(r[2] or 0)
                if sec > 0:
                    tot += _vec(vals, pid) * sec
                    sec_p[pid] += sec
                    gp[pid] += 1
                    last_team[pid] = t
            s_sum[t] = s_sum.get(t, np.zeros(3)) + tot / secs * 5
            s_n[t] += 1
    roster: dict[str, dict[str, float]] = defaultdict(dict)
    for p, t in last_team.items():
        roster[t][p] = 1.0
    return {t: s_sum[t] / s_n[t] for t in s_sum}, {p: sec_p[p] / 60.0 / gp[p] for p in gp}, roster


def _preseason_roster(store: dict) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for g in (store.get("games") or {}).values():
        if g.get("stype") != "pre" or g.get("status") != "post":
            continue
        for t, b in (g.get("box") or {}).items():
            for r in b.get("players") or []:
                out[str(t)][str(r[0])] = 1.0
            for r in b.get("dnp") or []:
                why = str(r[1] if len(r) > 1 else "").lower()
                pid = str(r[0])
                if pid not in out[str(t)]:
                    out[str(t)][pid] = 1.0 if any(k in why for k in COACH) else 0.0
    return out


def rotation_for(league: str, season: int, store: dict, vals: dict | None = None) -> Rotation:
    vals = vals if vals is not None else values_for(league, season)
    s_last, last_mpg, last_roster = _season_actual(G.load_store(league, season - 1), vals)
    pre = _preseason_roster(store)
    teams = R.league_teams(store) if store.get("games") else []
    init = {t: (dict(pre[t]) if pre.get(t) else dict(last_roster.get(t) or {})) for t in teams}
    return Rotation(league, vals, init, last_mpg, s_last)


# ── per-day inputs for a season ──────────────────────────────────────────────

def _team_av(rot: Rotation, t: str, d: date, out: set[str] | None = None,
             p_over: dict[str, float] | None = None) -> list[float]:
    se = rot.expected(t, out, p_over)
    sr, ps = rot.reference(t, d)
    ds = se - sr
    return [float(ds[0] * (1 - ps)), float(ds[1] - ds[2])]


def season_inputs(league: str, season: int, store: dict | None = None, lines: dict | None = None,
                  prior: dict | None = None, vals: dict | None = None, live: bool = True) -> dict:
    """{"days": {iso day: {"mk": {...}, "av": {team: [av, tot_av]}}}, "live": {...} | None, "line_share", ...}.
    Every day with a game (finished or scheduled) gets inputs from games of earlier days. "live" (the state after
    every finished game, for games not yet played) carries each team's rotation so injury-report Outs can be applied."""
    league = _league(league)
    st = store if store is not None else (G.load_store(league, season) or {})
    games = st.get("games") or {}
    rows = _rows(st, league)
    gdays = sorted({d for d in (G.local_day(g) for g in games.values()
                                if g and g.get("stype") in G.COUNTED and g.get("status") not in ("canceled", "postponed"))
                    if d is not None})
    if not gdays:
        return {"days": {}, "live": None}
    if prior is None:
        prior = season_market_prior(league, season)
    mk = market_path(league, season, st, lines, prior, days=gdays)
    rot = rotation_for(league, season, st, vals)
    teams = R.league_teams(st)
    days_out: dict[str, dict] = {}
    pi = 0
    for D in gdays:
        cut = D - timedelta(days=1)
        while pi < len(rows) and rows[pi]["day"] <= cut:
            rot.update(games[rows[pi]["id"]], rows[pi]["day"])
            pi += 1
        days_out[D.isoformat()] = {"mk": mk.get(D), "av": {t: _team_av(rot, t, D) for t in teams}}
    live_state = None
    if live:
        while pi < len(rows):
            rot.update(games[rows[pi]["id"]], rows[pi]["day"])
            pi += 1
        live_state = rot
    return {"days": days_out, "live": live_state, "teams": teams}


def inputs_for_game(si: dict, d: date, home: str, away: str, out: dict[str, set[str]] | None = None,
                    upcoming: bool = False) -> dict | None:
    """The model inputs of one game: {"mk_mu", "mk_tot", "av_h", "av_a", "tav_h", "tav_a", "n_lines", "n_games"}, or
    None when the season's lines are too thin (fallback to the base model). `out` ({team: {player ids}}) applies
    injury-report Outs (upcoming games only)."""
    day = (si.get("days") or {}).get(d.isoformat())
    if not day or not day.get("mk"):
        return None
    mk = day["mk"]
    if mk["n_games"] >= FALLBACK_AFTER and mk["n"] < MIN_LINE_SHARE * mk["n_games"]:
        return None                                   # the season's lines are too thin
    if mk["n"] == 0 and not mk.get("prior"):
        return None                                   # no line yet and none last season: the ratings would be empty
    r = mk["r"]
    if home not in r or away not in r:
        return None
    av = day["av"]
    ah, aa = av.get(home), av.get(away)
    rot = si.get("live")
    if upcoming and out and rot is not None:
        ah = _team_av(rot, home, d, out.get(home))
        aa = _team_av(rot, away, d, out.get(away))
    if ah is None or aa is None:
        return None
    return {"mk_h": mk["h"], "mk_r_h": r[home], "mk_r_a": r[away],
            "mk_tot": (mk["c"] + mk["t"][home] + mk["t"][away]) if mk.get("t") and home in mk["t"] and away in mk["t"] else None,
            "av_h": ah[0], "av_a": aa[0], "tav_h": ah[1], "tav_a": aa[1], "n_lines": mk["n"], "n_games": mk["n_games"]}


# ── prediction ───────────────────────────────────────────────────────────────

def predict(inp: dict, f: dict, th: dict, ta: dict, L: float, P: float, neutral: bool, stype: str | None,
            fit: dict) -> dict:
    """Margin, P(home), total from the inputs (`inputs_for_game`), the schedule features `f` (game.features), the two
    teams' ratings (fit_ratings entries) and the league means. Returns the model's terms for the payload."""
    pace_g = float(th.get("pace", P)) + float(ta.get("pace", P)) - P
    k = pace_g / 100.0
    det = f.get("detail") or {}
    dh, da = det.get("home") or {}, det.get("away") or {}
    x = {"mk_mu": inp["mk_h"] * (0.0 if neutral else 1.0) + inp["mk_r_h"] - inp["mk_r_a"],
         "rating": (float(th["net"]) - float(ta["net"])) * k,
         "x_av": (inp["av_h"] - inp["av_a"]) * k,
         **{c: float(f.get(c, 0.0)) for c in ("b2b", "rest", "travel_1000km", "tz", "altitude", "hca")}}
    cs = fit["spread"]
    terms = {c: float(cs.get(c, 0.0)) * x[c] for c in SPREAD_FEATS}
    mu = float(cs.get("const", 0.0)) + sum(terms.values()) + float(fit["cal_c0"])
    sd = float(fit["cal_sd"])
    b_av = float(cs.get("x_av", 0.0))
    out = {"margin": mu, "sd": sd, "p_home": float(norm.cdf(mu / sd)), "x": x, "terms": terms,
           # the availability term split by team, in points of home margin (home + away = terms["x_av"])
           "av_parts": {"home": b_av * inp["av_h"] * k, "away": -b_av * inp["av_a"] * k}}
    ct = fit.get("total")
    if ct and inp.get("mk_tot") is not None:
        L_, base = float(L), (float(th["off"]) + float(ta["def"]) - L + float(ta["off"]) + float(th["def"]) - L) * k
        xt = {"mk_tot": inp["mk_tot"], "base_total": base, "x_tot_av": (inp["tav_h"] + inp["tav_a"]) * k,
              "x_b2b_sum": float(dh.get("b2b") or 0) + float(da.get("b2b") or 0),
              "x_rest_sum": float(min(dh.get("rest", 3), 3)) + float(min(da.get("rest", 3), 3)),
              "x_early": 1.0 if (int(th.get("games") or 0) + int(ta.get("games") or 0)) < 20 else 0.0,
              "x_post": 1.0 if str(stype or "") == "post" else 0.0, "x_alt_tot": float(f.get("altitude", 0.0)),
              "lg_pace": float(P), "lg_ortg": L_}
        out["total"] = float(ct.get("const", 0.0)) + sum(float(ct.get(c, 0.0)) * xt[c] for c in TOTAL_FEATS)
        out["xt"] = xt
    return out
