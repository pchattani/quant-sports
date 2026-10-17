"""
Walk-forward game table for the edge research: one row per finished game with every model input as known at
the decision time, the outcome, and the betting lines (`lines.game_lines`).

Decision time: the morning (08:00 US Eastern) of the game's US day. Inputs use games of US days <= D - `lag`
(lag 1 = through last night; lag 2 = a day earlier, the sensitivity check). Schedule context (rest, travel,
time zones, altitude) is known in advance.

Team strength
-------------
* `net_h/net_a, off/def, pace`: `ratings.fit_ratings` refitted DAILY on games through D - lag with the
  preseason prior (last season carried over; the carry-over slope fitted on earlier seasons only).
* Roster / availability strength `S` (points per 100 for the five slots): sum over a team's players of
  value_p x expected minutes_p / 48 (40 WNBA), minutes short of five players' at replacement (-2.0).
  Player values come from LAST season's impact model only (`cache/impact/<L>_<s-1>_all.json`, else s-2);
  three variants are carried separately because S is linear in the values: RAPM total, box impact total, and
  HPM offence / defence. Players with no earlier value (rookies) get `ROOKIE`.
  Expected minutes = availability(miss streak) x minutes-per-game EWMA. The roster starts from the preseason box
  scores (players and DNP list) and otherwise from last season's team; a player seen with another team leaves.
  `dS = S_expected - S_reference`, where S_reference is what the team rating already reflects: last season's
  actual S (the prior, weight RIDGE games) blended with this season's actual S per game (same decay as the
  ratings). `prior_share` = RIDGE / (RIDGE + sum of game weights) splits roster change from availability.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import elo as E
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.research import lines as LN

logger = logging.getLogger(__name__)

REPLACEMENT = -2.0
ROOKIE = {"t": -2.0, "o": -1.0, "d": -1.0}
MPG_ALPHA = 0.2                       # EWMA weight of the latest game in minutes per game
ROOKIE_MPG = 10.0
VALUE_PSEUDO_MIN = 250.0                # minutes of rookie-level evidence added to every player value
# P(plays) by the number of the team's consecutive games the player has missed (0 = played last game);
# measured on NBA 2008-2016 / WNBA 2005-2016 for players averaging 24+ minutes (training seasons only).
AVAIL = {"nba": [0.94, 0.62, 0.37, 0.24, 0.18, 0.17, 0.14, 0.12, 0.06], "wnba": [0.96, 0.56, 0.33, 0.21, 0.16, 0.16, 0.12, 0.08, 0.06]}
COACH = ("coach", "decision")


def _league(x):
    return "wnba" if str(x).lower() == "wnba" else "nba"


def _g_min(league):
    return 40.0 if league == "wnba" else 48.0


def player_values(league: str, season: int) -> dict[str, dict]:
    """{pid: {"rapm","box","o","d","t","min"}} from the impact model of `season` (its whole season)."""
    p = _io.cache_root() / "impact" / f"{league}_{season}_all.json"
    try:
        res = json.loads(p.read_text("utf-8"))["result"]
    except (OSError, ValueError, KeyError):
        return {}
    if not res.get("ok"):
        return {}
    out = {}
    for pid, r in (res.get("players") or {}).items():
        rp = r.get("rapm") or {}
        box = (r.get("box_o") or 0.0) + (r.get("box_d") or 0.0) if r.get("box_o") is not None else None
        t = r.get("t")
        if t is None:
            continue
        o, d = r.get("o"), r.get("d")
        if o is None or d is None or abs(o) > 15 or abs(d) > 15:
            # NBA 2015-16's impact cache has O/D splits of +-48 that cancel in the total (bad O/D identification)
            o = d = t / 2
        mins = float(r.get("minutes") or 0.0)
        k = mins / (mins + VALUE_PSEUDO_MIN)          # shrink small samples towards a rookie
        vals = {"rapm": rp.get("t", t), "box": box if box is not None else t, "t": t, "o": o, "d": d}
        sh = {kk: max(-12.0, min(12.0, k * float(v) + (1 - k) * ROOKIE["t" if kk in ("rapm", "box", "t") else "o"]))
              for kk, v in vals.items()}
        out[str(pid)] = {**sh, "min": mins}
    return out


def _season_values(league: str, season: int) -> dict[str, dict]:
    a = player_values(league, season - 2)
    b = player_values(league, season - 1)
    out = {}
    for pid, v in a.items():
        out[pid] = dict(v)
    for pid, v in b.items():
        if v.get("min", 0) >= 100 or pid not in out:
            out[pid] = dict(v)
    return out


def _vals(vals: dict, pid: str) -> tuple[float, float, float, float]:
    v = vals.get(pid)
    if not v or v.get("t") is None:
        return ROOKIE["t"], ROOKIE["t"], ROOKIE["o"], ROOKIE["d"]
    t = float(v["t"])
    return (float(v["rapm"] if v.get("rapm") is not None else t), float(v["box"] if v.get("box") is not None else t),
            float(v["o"] if v.get("o") is not None else t / 2), float(v["d"] if v.get("d") is not None else t / 2))


class Rosters:
    """Per-team player state for one season; `expected(team)` -> S vector, `update(game)` after a game."""

    NV = 4                                       # rapm, box, o, d

    def __init__(self, league: str, vals: dict, init: dict[str, dict[str, float]], last_mpg: dict[str, float],
                 s_last: dict[str, np.ndarray], ridge: float, half_life: float):
        self.league, self.vals = league, vals
        self.G = _g_min(league)
        self.cap = 5 * self.G
        self.av = AVAIL[league]
        self.ridge, self.hl = ridge, half_life
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

    def _vec(self, pid):
        return np.array(_vals(self.vals, pid), float)

    def expected(self, t: str) -> np.ndarray:
        """S (rapm, box, o, d) for the team's expected rotation."""
        ps = self.st.get(t) or {}
        tot = np.zeros(self.NV)
        mins = 0.0
        contrib = []
        for pid, s in ps.items():
            a = self.av[min(s["streak"], len(self.av) - 1)]
            m = a * s["mpg"]
            if m <= 0:
                continue
            contrib.append((m, self._vec(pid)))
            mins += m
        scale = min(1.0, self.cap / mins) if mins > 0 else 1.0
        for m, v in contrib:
            tot += v * m * scale
        fill = max(0.0, self.cap - mins * scale)
        rep = np.array([REPLACEMENT, REPLACEMENT, REPLACEMENT / 2, REPLACEMENT / 2])
        return (tot + rep * fill) / self.G

    def reference(self, t: str, d: date) -> tuple[np.ndarray, float]:
        """(S the team rating reflects, prior share)."""
        prior = self.s_last.get(t)
        if prior is None:
            prior = np.array([REPLACEMENT, REPLACEMENT, REPLACEMENT / 2, REPLACEMENT / 2]) + 0.0
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
            seen = set()
            if secs <= 0:
                # an all-zero box (NBA 2013-2018 CHI / NO: ~90 games a season in the stores) says nothing
                continue
            if secs > 0:
                tot = np.zeros(self.NV)
                for r in players:
                    pid, sec = str(r[0]), float(r[2] or 0)
                    if sec > 0:
                        tot += self._vec(pid) * sec
                self.hist[t].append((d, tot / secs * 5))
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


def _season_actual(store: dict | None, vals: dict, league: str) -> tuple[dict[str, np.ndarray], dict[str, float], dict[str, dict[str, float]]]:
    """From a finished season: ({team: average actual S}, {pid: mpg}, {team: {pid: 1}} last-20-games roster)."""
    if not store:
        return {}, {}, {}
    s_sum: dict[str, np.ndarray] = {}
    s_n: dict[str, int] = defaultdict(int)
    sec_p: dict[str, float] = defaultdict(float)
    gp: dict[str, int] = defaultdict(int)
    last_team: dict[str, tuple[str, str]] = {}
    games = sorted((g for g in (store.get("games") or {}).values() if g.get("status") == "post" and g.get("stype") in G.COUNTED),
                   key=lambda g: str(g.get("date")))
    for g in games:
        for side in ("home", "away"):
            t = str(g[side])
            players = (((g.get("box") or {}).get(t) or {}).get("players")) or []
            secs = sum(float(r[2] or 0) for r in players)
            if secs <= 0:
                continue
            tot = np.zeros(4)
            for r in players:
                pid, sec = str(r[0]), float(r[2] or 0)
                if sec > 0:
                    tot += np.array(_vals(vals, pid)) * sec
                    sec_p[pid] += sec
                    gp[pid] += 1
                    last_team[pid] = (str(g.get("date")), t)
            s_sum[t] = s_sum.get(t, np.zeros(4)) + tot / secs * 5
            s_n[t] += 1
    s_avg = {t: s_sum[t] / s_n[t] for t in s_sum}
    mpg = {p: sec_p[p] / 60.0 / gp[p] for p in gp}
    roster: dict[str, dict[str, float]] = defaultdict(dict)
    for p, (_, t) in last_team.items():
        roster[t][p] = 1.0
    return s_avg, mpg, roster


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


def decision_time(day: date) -> datetime:
    """08:00 US Eastern on the game's US day (EDT Mar-Nov, EST otherwise; approximate DST)."""
    h = 12 if 3 <= day.month <= 10 else 13
    return datetime(day.year, day.month, day.day, h, 0, tzinfo=timezone.utc)


def _carry(ends: dict[int, dict | None], before: int, league: str) -> dict:
    xs, ys, px, py = [], [], [], []
    for s in sorted(ends):
        if s >= before:
            continue
        a, b = ends.get(s - 1), ends.get(s)
        if not a or not b:
            continue
        for t, v in b["teams"].items():
            u = a["teams"].get(t)
            if u and v["games"] >= 20 and u["games"] >= 20:
                xs.append(u["net"]); ys.append(v["net"])
                px.append(u["pace"] - a["league_pace"]); py.append(v["pace"] - b["league_pace"])
    res = {"b": R.DEFAULT_B, "se": R.DEFAULT_SE[league], "b_pace": 0.6}
    if len(xs) >= 40:
        x, y = np.array(xs), np.array(ys)
        bb = float(x @ y / (x @ x))
        res.update({"b": bb, "se": float(np.sqrt(np.mean((y - bb * x) ** 2)))})
        x, y = np.array(px), np.array(py)
        if x @ x > 0:
            res["b_pace"] = float(x @ y / (x @ x))
    return res


def garbage_adjusted(league: str, season: int) -> dict[str, tuple[float, float, float]]:
    """{game_id: (home pts, away pts, possessions, all home pts, all away pts)} excluding garbage-time stints: in the 4th quarter, a stint that
    starts with the margin at least 25 (12:00-9:00 left), 20 (9:00-6:00) or 10 (under 6:00) (Cleaning the Glass'
    thresholds, starters condition dropped; WNBA quarter scaled to 10 minutes). Games without stints are absent."""
    from oddsmarkets.basketball import store as bb_store
    tab = bb_store.load_table(league, season, "stints.json")
    if not tab:
        return {}
    cols = tab["cols"]
    ix = {c: i for i, c in enumerate(cols)}
    q = 600.0 if league == "wnba" else 720.0
    out: dict[str, list[float]] = {}
    margin: dict[str, float] = {}
    for r in sorted(tab["rows"], key=lambda r: (r[0], r[1])):
        gid = str(r[0])
        t0 = float(r[ix["t0"]])
        m = margin.get(gid, 0.0)
        left = 4 * q - t0
        garbage = False
        if 3 * q <= t0 < 4 * q:
            frac = left / q                                   # share of the 4th quarter left
            thr = 25 if frac > 0.75 else (20 if frac > 0.5 else 10)
            garbage = abs(m) >= thr
        ph, pa = float(r[ix["pts_h"]] or 0), float(r[ix["pts_a"]] or 0)
        margin[gid] = m + ph - pa
        acc = out.setdefault(gid, [0.0, 0.0, 0.0, 0.0, 0.0])
        if not garbage:
            acc[0] += ph
            acc[1] += pa
            acc[2] += 0.5 * (float(r[ix["poss_h"]] or 0) + float(r[ix["poss_a"]] or 0))
        acc[3] += ph
        acc[4] += pa
    return {g: tuple(v) for g, v in out.items() if v[2] > 20}


def production_roster_impact(league: str, season: int, store: dict) -> dict[str, float] | None:
    """`ratings.roster_prior_impact` as the site computes it (projected HPM x projected minutes, `meta.rosters`), with
    the season's PRESEASON rosters (players in its preseason box scores) standing in for `meta.rosters`, which only
    the current season has."""
    from oddsmarkets.basketball.models import impact as IM

    def pv(s):
        try:
            res = json.loads((_io.cache_root() / "impact" / f"{league}_{s}_all.json").read_text("utf-8"))["result"]
        except (OSError, ValueError, KeyError):
            return {}
        return R._player_values(res)
    per = {**pv(season - 2), **pv(season - 1)}
    pre = _preseason_roster(store)
    if not per or not pre:
        return None
    cap = 5 * _io.game_minutes(league)
    out = {}
    for t, pids in pre.items():
        vals = {p: per[p][0] for p in pids if p in per}
        mins = {p: per[p][1] for p in pids if p in per}
        if vals:
            out[t] = float(IM.roster_impact(vals, R._allocate_minutes(mins, cap), league)["net"])
    return out or None


def build(league: str, seasons: Iterable[int], lag: int = 1, first_on_disk: int | None = None,
          garbage: bool = False, roster_prior: bool = False) -> pd.DataFrame:
    league = _league(league)
    seasons = sorted(int(s) for s in seasons)
    on_disk = G.seasons_on_disk(league)
    lo = first_on_disk or on_disk[0]
    stores = {s: G.load_store(league, s) for s in on_disk if lo <= s <= max(seasons)}
    ends = {s: R.season_end_ratings(league, s, store=st) for s, st in stores.items() if st}
    hist = E.history(league)
    elo_p = E.pregame(hist)
    out = []
    for s in seasons:
        st = stores.get(s)
        if not st:
            continue
        coef = _carry(ends, s, league)
        last = ends.get(s - 1) if ends.get(s - 1) and ends[s - 1]["n_games"] >= 30 else None
        teams = R.league_teams(st)
        imp = production_roster_impact(league, s, st) if roster_prior else None
        prior = R.preseason_prior(league, s, last=last, coef=coef, teams=teams, roster_impact=imp)
        vals = _season_values(league, s)
        s_last, last_mpg, last_roster = _season_actual(stores.get(s - 1), vals, league)
        pre = _preseason_roster(st)
        init = {t: (dict(pre[t]) if pre.get(t) else dict(last_roster.get(t) or {})) for t in teams}
        ros = Rosters(league, vals, init, last_mpg, s_last, R.RIDGE[league], R.HALF_LIFE[league])
        games = st.get("games") or {}
        rows = G.finished(games, league)
        fit_rows = rows
        if garbage:
            adj = garbage_adjusted(league, s)
            fit_rows = []
            for r in rows:
                a = adj.get(r["id"])
                # only when the stint totals reconcile with the final score (within 3 points each side)
                if a and r.get("poss") and abs(a[3] - r["hs"]) <= 3 and abs(a[4] - r["as"]) <= 3:
                    fit_rows.append({**r, "hs": a[0], "as": a[1], "poss": a[2]})
                else:
                    fit_rows.append(r)
            fit_by_id = {r["id"]: r for r in fit_rows}
        if not rows:
            continue
        sched = GM.Schedule(games, st.get("teams") or {}, league)
        ln = LN.game_lines(league, s)
        days = sorted({r["day"] for r in rows})
        by_day: dict[date, list[dict]] = defaultdict(list)
        for r in rows:
            by_day[r["day"]].append(r)
        pending = list(rows)
        pi = 0
        applied: list[dict] = []
        for D in days:
            cutoff = D - timedelta(days=lag)
            while pi < len(pending) and pending[pi]["day"] <= cutoff:
                r = pending[pi]
                ros.update(games[r["id"]], r["day"])
                applied.append(fit_by_id[r["id"]] if garbage else r)
                pi += 1
            fit = R.fit_ratings(applied, through=cutoff, prior=prior, league=league, teams=teams)
            tm = fit["teams"]
            L, P = fit["league_ortg"], fit["league_pace"]
            exp_cache: dict[str, Any] = {}
            for r in by_day[D]:
                g = games[r["id"]]
                feats = GM.features(r["home"], r["away"], D, sched, r["neutral"], league)
                th = tm.get(r["home"]) or {"off": L, "def": L, "net": 0.0, "pace": P, "se_net": 4.0, "games": 0}
                ta = tm.get(r["away"]) or {"off": L, "def": L, "net": 0.0, "pace": P, "se_net": 4.0, "games": 0}
                pace_g = th["pace"] + ta["pace"] - P
                rec = {"event_id": r["id"], "league": league, "season": s, "start_time": r["date"], "day": D,
                       "decision_time": decision_time(D), "stype": r["stype"], "home": r["home"], "away": r["away"],
                       "neutral": r["neutral"], "hs": r["hs"], "as": r["as"], "margin": r["margin"],
                       "total_pts": r["hs"] + r["as"], "periods": r["periods"],
                       "net_h": th["net"], "net_a": ta["net"], "off_h": th["off"], "def_h": th["def"],
                       "off_a": ta["off"], "def_a": ta["def"], "pace_h": th["pace"], "pace_a": ta["pace"],
                       "se_h": th.get("se_net", 4.0), "se_a": ta.get("se_net", 4.0), "gp_h": th.get("games", 0),
                       "gp_a": ta.get("games", 0), "lg_ortg": L, "lg_pace": P, "pace_g": pace_g,
                       "rating": (th["net"] - ta["net"]) * pace_g / 100.0,
                       "base_total": (th["off"] + ta["def"] - L + ta["off"] + th["def"] - L) * pace_g / 100.0,
                       "elo_p": elo_p.get(r["id"])}
                for k in GM.FEATURES:
                    rec[k] = feats[k]
                det = feats.get("detail") or {}
                for side, key in (("h", "home"), ("a", "away")):
                    dd = det.get(key) or {}
                    rec[f"rest_{side}"] = dd.get("rest")
                    rec[f"b2b_{side}"] = dd.get("b2b")
                for side, t in (("h", r["home"]), ("a", r["away"])):
                    if t not in exp_cache:
                        se = ros.expected(t)
                        sr, ps = ros.reference(t, D)
                        exp_cache[t] = (se, sr, ps)
                    se, sr, ps = exp_cache[t]
                    for j, nm in enumerate(("rapm", "box", "o", "d")):
                        rec[f"S_{nm}_{side}"] = float(se[j])
                        rec[f"dS_{nm}_{side}"] = float(se[j] - sr[j])
                    rec[f"prior_share_{side}"] = ps
                lg = ln.get(r["id"]) or {}
                for when in ("open", "close"):
                    b = lg.get(when) or {}
                    for k in ("ml_h", "ml_a", "sp_h", "spo_h", "spo_a", "tot", "over", "under"):
                        rec[f"{when}_{k}"] = b.get(k)
                rec["line_src"] = lg.get("src")
                so = (g.get("odds") or {})
                rec["store_sp_h"] = so.get("spread_home")
                rec["store_tot"] = so.get("total")
                out.append(rec)
        logger.info("%s %s: %d games", league, s, len(by_day and rows))
    return pd.DataFrame(out)
