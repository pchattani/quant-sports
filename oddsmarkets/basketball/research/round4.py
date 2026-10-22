"""
Round 4 (22-23 October 2026): more sophistication from the free data we already hold (docs/research/basketball_edge.md,
section "Round 4").

No new source. Everything here comes from the season stores (box scores with ESPN's DNP reasons, schedules, venues),
the play-by-play stints (`stints.json`, substitutions reconciled with box minutes), the bio file (dates of birth), the
ESPN line cache and the Kalshi caches already on disk.

The availability term of the informed model (`models/informed.py`) is

    av_t = (S_expected - S_reference)_net x (1 - prior_share)

with S = the five-slot strength of a rotation (player values x expected minutes, replacement level for minutes
nobody fills). This module recomputes it under three changes, one at a time and together:

  A  in-season player values: a prior-centred RAPM refitted every REFIT_EVERY days on the season's stints of games
     already played (days <= D - 1), each player's ridge centre being the value the model starts the season with
     (last season's RAPM/box blend, O and D). Players with few possessions stay at their prior: the Bayesian
     update. S_reference is recomputed with the same values, so a value change moves both sides.
  B  a P(plays) model in place of the miss-streak table: walk-forward logistic regression on player-games (streak,
     the reason ESPN printed for the last absence, minutes load, back-to-backs, age, season phase, team context).
  C  schedule extras: three games in four nights, games in the last seven days, road-trip length, signed time-zone
     change.

`season_walk` walks one season with the production rotation logic (models/informed.Rotation) and writes, per game
and team, the reference S under each value variant, and per rotation player the decision-time features, the value
variants and the outcome (played or not; never an input). `features` turns those into x_dSl / x_tot_dS columns for
the research table, so the informed model's walk-forward fits (`improve.wf_margin`, `improve.probit_wf`) can be
rerun with them.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from oddsmarkets.basketball import store as stmod
from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import impact as IM
from oddsmarkets.basketball.models import informed as INF
from oddsmarkets.basketball.models import ratings as R

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CACHE = _io.cache_root() / "round4"
LAMS = (3000.0, 8000.0, 20000.0)       # in-season RAPM ridge (possessions of prior evidence); chosen on dev seasons
REFIT_EVERY = 7                        # days between in-season refits
MIN_GAMES_REFIT = 40                   # league games with stints before the first in-season refit
CLIP = 12.0
REASONS = ("none", "coach", "absent", "injury", "major", "ill", "rest", "personal", "susp", "gleague", "inactive")


def reason_cat(why: str | None) -> str:
    """ESPN's DNP text (box score of the last game) -> a category."""
    w = str(why or "").upper()
    if not w.strip():
        return "inactive"
    if "COACH" in w or "DECISION" in w:
        return "coach"
    if "SUSPEN" in w:
        return "susp"
    if any(k in w for k in ("PERSONAL", "NOT WITH TEAM", "FAMILY", "BEREAVE", "BIRTH")):
        return "personal"
    if any(k in w for k in ("G LEAGUE", "G-LEAGUE", "GLEAGUE", "ASSIGN", "TWO-WAY", "TWO WAY")):
        return "gleague"
    if "REST" in w or "LOAD" in w or "MANAGEMENT" in w:
        return "rest"
    if any(k in w for k in ("ILLNESS", "SICK", "FLU", "COVID", "PROTOCOL", "VIRUS")):
        return "ill"
    if any(k in w for k in ("SURGERY", "FRACTURE", "TEAR", "TORN", "RUPTURE", "ACL", "MCL", "BROKEN", "REHAB",
                            "RECOVERY", "REPAIR")):
        return "major"
    if "NOT DRESS" in w or "INACTIVE" in w:
        return "inactive"
    return "injury"


def _split_od(v: list[float]) -> tuple[float, float]:
    """(o, d) with o + d = net (the RAPM prior centre for a player valued v = [net, o, d, ...])."""
    net, o, d = float(v[0]), float(v[1]), float(v[2])
    gap = (net - (o + d)) / 2.0
    return o + gap, d + gap


def _age(dob: str | None, d: date) -> float | None:
    try:
        b = date.fromisoformat(str(dob)[:10])
    except (TypeError, ValueError):
        return None
    return (d - b).days / 365.25


def start_values(league: str, season: int) -> dict[str, list[float]]:
    """Start-of-season values [net, o, d] as the research table uses them (research/dataset._season_values: the
    impact caches of the two previous seasons, read directly so no impact model is refitted): net = 0.5 RAPM + 0.5 box,
    each shrunk to a rookie with 250 pseudo-minutes. Identical to production's `informed.values_for`."""
    from oddsmarkets.basketball.research import dataset as D
    com = INF.committed_values(league)

    def one(s):
        c = com.get(str(int(s)))
        if c:
            return {p: list(v) for p, v in c.items()}
        out = {}
        for pid, v in D.player_values(league, s).items():
            r, b, o, d = D._vals({pid: v}, pid)
            out[pid] = [INF.W_RAPM * r + (1 - INF.W_RAPM) * b, o, d, float(v.get("min", 0.0))]
        return out
    res = {p: v[:3] for p, v in one(season - 2).items()}
    for p, v in one(season - 1).items():
        if v[3] >= 100 or p not in res:
            res[p] = v[:3]
    return res


class _Vals:
    """Value variants: 'static' (production) and 'l<lambda>' (in-season RAPM, refitted every REFIT_EVERY days)."""

    def __init__(self, league: str, season: int, static: dict[str, list[float]], lams=LAMS):
        self.league, self.season = league, season
        self.static = {p: [float(v[0]), float(v[1]), float(v[2])] for p, v in static.items()}
        self.lams = tuple(lams)
        self.names = ["static"] + [f"l{int(l)}" for l in self.lams]
        self.cur = {n: self.static for n in self.names}
        self.ver = {n: 0 for n in self.names}
        tab = stmod.load_table(league, season, "stints.json") if self.lams else None
        self.stints = IM.as_stints(tab) if tab else pd.DataFrame()
        self.last_refit: date | None = None

    def vec(self, name: str, pid: str) -> np.ndarray:
        v = self.cur[name].get(pid)
        return np.array(v, float) if v else np.array(INF.ROOKIE, float)

    def maybe_refit(self, D: date, applied_ids: set[str]) -> None:
        if not self.lams or self.stints.empty:
            return
        if self.last_refit is not None and (D - self.last_refit).days < REFIT_EVERY:
            return
        m = self.stints.game_id.isin(applied_ids)
        if self.stints.loc[m, "game_id"].nunique() < MIN_GAMES_REFIT:
            return
        df = self.stints[m]
        ids = sorted(set(np.unique(df[_io.STINT_COLS[3:13]].to_numpy().ravel())))
        pidx = {p: i for i, p in enumerate(ids)}
        P = len(ids)
        X, y, w, _g, _lg = IM._rapm_design(df, pidx)
        Gm, r, _yy, _wt = IM._normal(X, y, w)
        mvec = np.zeros(2 * P + 1)
        for k, pid in enumerate(ids):
            v = self.static.get(pid)
            o, d = _split_od(v) if v else (INF.ROOKIE[1], INF.ROOKIE[2])
            mvec[k], mvec[P + k] = o, d
        for lam in self.lams:
            lv = np.full(2 * P + 1, lam)
            lv[-1] = IM.HCA_RIDGE
            b, _ = IM._solve(Gm, r, lv, mvec)
            nm = f"l{int(lam)}"
            new = dict(self.static)
            for k, pid in enumerate(ids):
                o = max(-CLIP, min(CLIP, float(b[k])))
                d = max(-CLIP, min(CLIP, float(b[P + k])))
                new[pid] = [max(-CLIP, min(CLIP, o + d)), o, d]
            self.cur[nm] = new
            self.ver[nm] += 1
        self.last_refit = D


def _team_weights(players: list) -> dict[str, float] | None:
    secs = sum(float(r[2] or 0) for r in players)
    if secs <= 0:
        return None
    return {str(r[0]): float(r[2] or 0) / secs * 5 for r in players if float(r[2] or 0) > 0}


def season_walk(league: str, season: int, lams=LAMS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(team_rows, player_rows) for every counted finished game of the season; inputs from games of US days <= D - 1.

    team_rows: event_id, season, day, side, team, ps (prior share), ref_<var>_{net,o,d}.
    player_rows: event_id, season, day, side, team, pid, mpg, streak, decision-time features, v_<var>_{net,o,d},
    played (outcome), secs (outcome)."""
    league = INF._league(league)
    st = G.load_store(league, season) or {}
    games = st.get("games") or {}
    rows = G.finished(games, league)
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    static = start_values(league, season)
    vals = _Vals(league, season, static, lams)
    names = vals.names
    ridge, hl = R.RIDGE[league], R.HALF_LIFE[league]
    bio = {}
    try:
        b = json.loads((_io.data_root() / league / "bio.json").read_text(encoding="utf-8"))
        bio = {k: (v or {}).get("dob") for k, v in b.items() if not k.startswith("_") and isinstance(v, dict)}
    except (OSError, ValueError):
        pass
    for pid, p in (st.get("players") or {}).items():
        if p.get("dob") and pid not in bio:
            bio[pid] = p.get("dob")

    # last season: per team, the average lineup weights (S_last = sum w x value), each player's mpg and last team
    prev = G.load_store(league, season - 1)
    w_last: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    n_last: dict[str, int] = defaultdict(int)
    sec_p: dict[str, float] = defaultdict(float)
    gp_p: dict[str, int] = defaultdict(int)
    last_team: dict[str, str] = {}
    if prev:
        for g in sorted((g for g in (prev.get("games") or {}).values() if g.get("status") == "post" and g.get("stype") in G.COUNTED),
                        key=lambda g: str(g.get("date"))):
            for side in ("home", "away"):
                t = str(g[side])
                pl = (((g.get("box") or {}).get(t) or {}).get("players")) or []
                wt = _team_weights(pl)
                if wt is None:
                    continue
                for pid, x in wt.items():
                    w_last[t][pid] += x
                for r in pl:
                    sec = float(r[2] or 0)
                    if sec > 0:
                        sec_p[str(r[0])] += sec
                        gp_p[str(r[0])] += 1
                        last_team[str(r[0])] = t
                n_last[t] += 1
    w_last = {t: {p: x / n_last[t] for p, x in d.items()} for t, d in w_last.items()}
    last_mpg = {p: sec_p[p] / 60.0 / gp_p[p] for p in gp_p}
    last_roster: dict[str, dict[str, float]] = defaultdict(dict)
    for p, t in last_team.items():
        last_roster[t][p] = 1.0
    pre = INF._preseason_roster(st)
    teams = R.league_teams(st)
    init = {t: (dict(pre[t]) if pre.get(t) else dict(last_roster.get(t) or {})) for t in teams}

    # player state (production Rotation semantics, plus the extra features)
    team_of: dict[str, str] = {}
    pst: dict[str, dict[str, dict]] = defaultdict(dict)

    def add(t, pid, mpg, streak=0):
        old = team_of.get(pid)
        prv = None
        if old and old != t:
            prv = pst[old].pop(pid, None)
        team_of[pid] = t
        if pid not in pst[t]:
            pst[t][pid] = {"mpg": float(prv["mpg"] if prv else mpg), "streak": streak, "last_min": 0.0,
                           "reason": "none" if streak == 0 else "absent", "gp": 0, "mins": deque(),
                           "last_play": None, "moved": prv is not None}

    for t, players in init.items():
        for pid, a0 in players.items():
            add(t, pid, last_mpg.get(pid, INF.ROOKIE_MPG), streak=0 if a0 >= 0.5 else 3)

    hist: dict[str, list[tuple[date, dict[str, float], dict]]] = defaultdict(list)
    tgames: dict[str, int] = defaultdict(int)
    twins: dict[str, int] = defaultdict(int)
    reg_days = sorted({r["day"] for r in rows if r["stype"] == "reg"})
    d_first, d_last = (reg_days[0], reg_days[-1]) if reg_days else (None, None)
    sched = GM.Schedule(games, st.get("teams") or {}, league)

    def s_of(weights: dict[str, float], nm: str) -> np.ndarray:
        tot = np.zeros(3)
        for pid, x in weights.items():
            tot += vals.vec(nm, pid) * x
        return tot

    def reference(t: str, D: date, nm: str) -> tuple[np.ndarray, float]:
        wl = w_last.get(t)
        prior = s_of(wl, nm) + INF.REP * max(0.0, 5 - sum(wl.values())) if wl else INF.REP + 0.0
        num, den = prior * ridge, ridge
        key = (nm, vals.ver[nm])
        for dd, wt, cache in hist.get(t) or []:
            w = 0.5 ** (max(0, (D - dd).days) / hl)
            sg = cache.get(key)
            if sg is None:
                sg = cache[key] = s_of(wt, nm)
            num = num + w * sg
            den += w
        return num / den, ridge / den

    def update(g: dict, d: date) -> None:
        for side in ("home", "away"):
            t = str(g[side])
            b = (g.get("box") or {}).get(t) or {}
            players = b.get("players") or []
            wt = _team_weights(players)
            if wt is None:
                continue
            hist[t].append((d, wt, {}))
            tgames[t] += 1
            won = (g["hs"] > g["as"]) == (side == "home")
            twins[t] += int(won)
            seen = set()
            for r in players:
                pid, sec = str(r[0]), float(r[2] or 0)
                seen.add(pid)
                add(t, pid, INF.ROOKIE_MPG)
                s = pst[t][pid]
                s["mpg"] = (1 - INF.MPG_ALPHA) * s["mpg"] + INF.MPG_ALPHA * sec / 60.0
                s["streak"] = 0
                s["last_min"] = sec / 60.0
                if sec > 0:
                    s["gp"] += 1
                    s["last_play"] = d
                    s["mins"].append((d, sec / 60.0))
                s["reason"] = "none"
            for row in b.get("dnp") or []:
                pid, why = str(row[0]), str(row[1] if len(row) > 1 else "")
                seen.add(pid)
                add(t, pid, INF.ROOKIE_MPG, streak=1)
                s = pst[t][pid]
                s["last_min"] = 0.0
                cat = reason_cat(why)
                if cat == "coach":
                    s["mpg"] = (1 - INF.MPG_ALPHA) * s["mpg"]
                    s["streak"] = 0
                    s["reason"] = "coach"
                else:
                    s["streak"] += 1
                    s["reason"] = cat
            for pid, s in (pst.get(t) or {}).items():
                if pid not in seen:
                    s["streak"] += 1
                    s["last_min"] = 0.0
                    if s["reason"] in ("none", "coach"):
                        s["reason"] = "absent"

    team_out, player_out = [], []
    gl = sorted((r["day"], r["id"]) for r in rows)
    by_day: dict[date, list[str]] = defaultdict(list)
    for D, gid in gl:
        by_day[D].append(gid)
    rix = {r["id"]: r for r in rows}
    pi = 0
    applied: set[str] = set()
    for D in sorted(by_day):
        cut = D - timedelta(days=1)
        while pi < len(rows) and rows[pi]["day"] <= cut:
            update(games[rows[pi]["id"]], rows[pi]["day"])
            applied.add(rows[pi]["id"])
            pi += 1
        vals.maybe_refit(D, applied)
        refcache: dict[tuple[str, str], tuple] = {}
        for gid in by_day[D]:
            g = games[gid]
            r = rix[gid]
            feats = GM.features(r["home"], r["away"], D, sched, r["neutral"], league)
            det = feats.get("detail") or {}
            for side in ("home", "away"):
                t = str(g[side])
                k = "h" if side == "home" else "a"
                trow = {"event_id": gid, "season": season, "day": D, "side": k, "team": t}
                for nm in names:
                    if (t, nm) not in refcache:
                        refcache[(t, nm)] = reference(t, D, nm)
                    sr, ps = refcache[(t, nm)]
                    trow["ps"] = ps
                    for j, c in enumerate(("net", "o", "d")):
                        trow[f"ref_{nm}_{c}"] = float(sr[j])
                team_out.append(trow)
                box = (g.get("box") or {}).get(t) or {}
                played = {str(x[0]): float(x[2] or 0) for x in box.get("players") or []}
                tg = tgames[t]
                wp = (twins[t] + 2) / (tg + 4)
                phase = ((D - d_first).days / max(1, (d_last - d_first).days)) if d_first else 0.5
                b2b = int((det.get(side) or {}).get("b2b") or 0)
                rest = (det.get(side) or {}).get("rest", 3)
                for pid, s in (pst.get(t) or {}).items():
                    if s["mpg"] <= 0:
                        continue
                    while s["mins"] and (D - s["mins"][0][0]).days > 7:
                        s["mins"].popleft()
                    rec = {"event_id": gid, "season": season, "day": D, "side": k, "team": t, "pid": pid,
                           "mpg": s["mpg"], "streak": s["streak"], "last_min": s["last_min"], "reason": s["reason"],
                           "gp": s["gp"], "tg": tg, "min7": sum(m for _, m in s["mins"]),
                           "days_off": (D - s["last_play"]).days if s["last_play"] else 99,
                           "age": _age(bio.get(pid), D), "b2b": b2b, "rest": rest, "wp": wp, "phase": phase,
                           "stype": r["stype"], "moved": int(bool(s.get("moved"))),
                           "played": int(played.get(pid, 0.0) > 0), "secs": played.get(pid, 0.0)}
                    for nm in names:
                        v = vals.vec(nm, pid)
                        rec[f"v_{nm}_net"], rec[f"v_{nm}_o"], rec[f"v_{nm}_d"] = float(v[0]), float(v[1]), float(v[2])
                    player_out.append(rec)
    tr = pd.DataFrame(team_out)
    pr = pd.DataFrame(player_out)
    for c in pr.columns:
        if c.startswith("v_") or c in ("mpg", "last_min", "min7", "wp", "phase", "secs"):
            pr[c] = pr[c].astype("float32")
    logger.info("%s %s walk: %d team-games, %d player rows", league, season, len(tr), len(pr))
    return tr, pr


def walk_cached(league: str, season: int, lams=LAMS, rebuild: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = "_".join(str(int(l)) for l in lams) or "static"
    pt, pp = CACHE / f"{league}_{season}_{tag}_team.parquet", CACHE / f"{league}_{season}_{tag}_players.parquet"
    if not rebuild and pt.exists() and pp.exists():
        return pd.read_parquet(pt), pd.read_parquet(pp)
    tr, pr = season_walk(league, season, lams)
    if not tr.empty:
        tr.to_parquet(pt, index=False)
        pr.to_parquet(pp, index=False)
    return tr, pr


# ── P(plays) ─────────────────────────────────────────────────────────────────

STREAK_BUCKETS = (0, 1, 2, 3, 4, 6, 11)


def _sb(streak: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.array(STREAK_BUCKETS[1:]), streak, side="right")


def design(pr: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Decision-time features of each player-game row (no outcome column)."""
    sb = _sb(pr.streak.to_numpy())
    reason = pr.reason.to_numpy()
    cols, names = [], []

    def add(x, nm):
        cols.append(np.asarray(x, float))
        names.append(nm)
    for b in range(1, len(STREAK_BUCKETS)):
        add(sb == b, f"sb{b}")
    out = sb > 0
    for rc in ("injury", "major", "ill", "rest", "personal", "susp", "gleague", "inactive"):
        m = (reason == rc) & out
        add(m, f"r_{rc}")
        add(m & (sb >= 3), f"r_{rc}_long")
    mpg = pr.mpg.to_numpy(float)
    add(np.log1p(mpg), "log_mpg")
    add(np.log1p(mpg) * out, "log_mpg_out")
    lm = pr.last_min.to_numpy(float)
    add(np.where(out, 0.0, np.clip(lm / np.maximum(mpg, 1.0), 0, 2)), "last_ratio")
    add(np.where(out, 0.0, (lm < 0.5 * mpg) & (mpg >= 15)), "short_last")
    add(np.clip(pr.min7.to_numpy(float) / np.maximum(mpg, 5.0), 0, 5), "load7")
    b2b = pr.b2b.to_numpy(float)
    age = pr.age.to_numpy(float)
    has_age = np.isfinite(age)
    a = np.where(has_age, age, 27.0)
    add(b2b, "b2b")
    add(b2b * (a >= 31), "b2b_old")
    add(b2b * (mpg >= 30), "b2b_star")
    add(np.clip(a - 27, -8, 12) / 5.0, "age")
    add(~has_age, "no_age")
    ph = pr.phase.to_numpy(float)
    reg = (pr.stype.to_numpy() == "reg")
    late = reg & (ph > 0.9)
    wp = pr.wp.to_numpy(float)
    add(late, "late")
    add(late * (wp < 0.4), "late_bad")
    add(late * (wp > 0.62), "late_good")
    add(late * (wp < 0.4) * (mpg >= 25), "late_bad_star")
    add(pr.stype.to_numpy() == "post", "post")
    add(pr.stype.to_numpy() == "playin", "playin")
    tg = pr.tg.to_numpy(float)
    add(np.where(tg >= 5, pr.gp.to_numpy(float) / np.maximum(tg, 1), 0.8), "gp_share")
    add(tg < 5, "early")
    add(np.clip(pr.days_off.to_numpy(float), 0, 60) / 30.0 * out, "days_off")
    add(pr.moved.to_numpy(float), "moved")
    return np.column_stack(cols), names


def logit_fit(X: np.ndarray, y: np.ndarray, w: np.ndarray | None = None, l2: float = 1.0) -> np.ndarray:
    """Weighted L2 logistic regression by Newton steps; returns (intercept, coefs)."""
    Xm = np.column_stack([np.ones(len(X)), X])
    w = np.ones(len(X)) if w is None else w
    th = np.zeros(Xm.shape[1])
    P = np.eye(Xm.shape[1]) * l2
    P[0, 0] = 0.0
    for _ in range(60):
        eta = np.clip(Xm @ th, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        g = Xm.T @ (w * (y - p)) - P @ th
        H = (Xm * (w * p * (1 - p))[:, None]).T @ Xm + P
        step = np.linalg.solve(H, g)
        th = th + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return th


def logit_pred(X: np.ndarray, th: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(th[0] + X @ th[1:], -30, 30)))


def pplays_wf(pr: pd.DataFrame, first_train: int, min_mpg_train: float = 5.0, window: int = 8) -> tuple[np.ndarray, dict]:
    """Walk-forward P(plays): season s gets the logistic fit on seasons [s - window, s - 1] (rows with mpg >= min,
    weighted by mpg, so the players who matter count most). Rows of seasons with too little history keep NaN."""
    X, names = design(pr)
    y = pr.played.to_numpy(float)
    seas = pr.season.to_numpy()
    mpg = pr.mpg.to_numpy(float)
    out = np.full(len(pr), np.nan)
    fits = {}
    for s in sorted(np.unique(seas)):
        tr = (seas < s) & (seas >= max(first_train, s - window)) & (mpg >= min_mpg_train)
        if tr.sum() < 20000:
            continue
        th = logit_fit(X[tr], y[tr], w=mpg[tr] / 20.0)
        te = seas == s
        out[te] = logit_pred(X[te], th)
        fits[int(s)] = dict(zip(["const"] + names, np.round(th, 4).tolist()))
    return out, fits


def streak_rate(pr: pd.DataFrame, league: str) -> np.ndarray:
    tab = np.array(INF.AVAIL[league])
    return tab[np.minimum(pr.streak.to_numpy(), len(tab) - 1)]


# ── availability features from the walk ───────────────────────────────────────

def expected_S(pr: pd.DataFrame, a: np.ndarray, var: str, league: str) -> pd.DataFrame:
    """Per (event_id, side): S_expected (net, o, d) of the rotation with P(plays) `a` and values `var`."""
    Gm = _io.game_minutes(league)
    cap = 5 * Gm
    m = np.asarray(a, float) * pr.mpg.to_numpy(float)
    m = np.where(m > 0, m, 0.0)
    df = pd.DataFrame({"event_id": pr.event_id.to_numpy(), "side": pr.side.to_numpy(), "m": m,
                       "vn": m * pr[f"v_{var}_net"].to_numpy(float), "vo": m * pr[f"v_{var}_o"].to_numpy(float),
                       "vd": m * pr[f"v_{var}_d"].to_numpy(float)})
    s = df.groupby(["event_id", "side"], sort=False)[["m", "vn", "vo", "vd"]].sum()
    M = s.m.to_numpy()
    scale = np.where(M > 0, np.minimum(1.0, cap / np.where(M > 0, M, 1.0)), 1.0)
    fill = np.maximum(0.0, cap - M * scale)
    out = pd.DataFrame(index=s.index)
    out["S_net"] = (s.vn.to_numpy() * scale + INF.REP[0] * fill) / Gm
    out["S_o"] = (s.vo.to_numpy() * scale + INF.REP[1] * fill) / Gm
    out["S_d"] = (s.vd.to_numpy() * scale + INF.REP[2] * fill) / Gm
    return out.reset_index()


def av_columns(tr: pd.DataFrame, pr: pd.DataFrame, a: np.ndarray, var: str, league: str, tag: str) -> pd.DataFrame:
    """Per event_id: av_h, av_a (net x (1 - prior share)), tav_h, tav_a (o - d), Sx_h, Sx_a (absolute S_net) under
    P(plays) `a` and values `var`, suffixed _<tag>."""
    e = expected_S(pr, a, var, league)
    t = tr[["event_id", "side", "ps", f"ref_{var}_net", f"ref_{var}_o", f"ref_{var}_d"]].merge(e, on=["event_id", "side"], how="left")
    for c, rep in (("S_net", INF.REP[0]), ("S_o", INF.REP[1]), ("S_d", INF.REP[2])):
        t[c] = t[c].fillna(rep * 5)
    t["av"] = (t.S_net - t[f"ref_{var}_net"]) * (1 - t.ps)
    t["tav"] = (t.S_o - t[f"ref_{var}_o"]) - (t.S_d - t[f"ref_{var}_d"])
    t["sx"] = t.S_net
    w = t.pivot(index="event_id", columns="side", values=["av", "tav", "sx"])
    w.columns = [f"{a_}_{b}_{tag}" for a_, b in w.columns]
    return w.reset_index()


# ── schedule extras (C) ───────────────────────────────────────────────────────

def schedule_extras(league: str, season: int) -> pd.DataFrame:
    """Per finished game: home-minus-away three-in-four, games in the previous 7 days, road-trip length (consecutive
    away games including this one) and signed time-zone change (east positive). Known from the schedule."""
    st = G.load_store(league, season) or {}
    games = st.get("games") or {}
    sched = GM.Schedule(games, st.get("teams") or {}, league)
    out = []
    for r in G.finished(games, league):
        D = r["day"]
        rec = {"event_id": r["id"]}
        vals = {}
        for side, t in (("h", r["home"]), ("a", r["away"])):
            lst = sched.by_team.get(t) or []
            days = [x[0] for x in lst]
            import bisect
            k = bisect.bisect_left(days, D)
            prev = lst[:k]
            g7 = sum(1 for x in prev if (D - x[0]).days <= 7)
            g3 = sum(1 for x in prev if (D - x[0]).days <= 3)
            trip = 0
            if side == "a" or r["neutral"]:
                trip = 1
                for x in reversed(prev):
                    if x[1] != t:
                        trip += 1
                    else:
                        break
            tz = 0.0
            if prev:
                here, there = sched.loc(r["home"]), sched.loc(prev[-1][1])
                if here and there and (D - prev[-1][0]).days <= 3:
                    tz = float(here[2] - there[2])
            vals[side] = (int(g3 >= 2), g7, trip, tz)
        for j, nm in enumerate(("x_3in4", "x_g7", "x_trip", "x_tzs")):
            rec[nm] = float(vals["h"][j] - vals["a"][j])
        out.append(rec)
    return pd.DataFrame(out)


# ── scoring helpers ───────────────────────────────────────────────────────────

def refit_informed(p: pd.DataFrame, league: str, sp_feats: list[str], name: str = "r4",
                   coef_prior: dict | None = None, prior_lam: float = 0.0) -> pd.DataFrame:
    """The informed model's structure (C: closing spread ~ sp_feats walk-forward, then the probit calibration on
    outcomes, train_from MK_TRAIN_FROM) with any feature set; adds p_<name> (fallback p_M1 where no market input).
    With `coef_prior` ({feature: value}, or {season: {feature: value}}) the ridge pulls the coefficients towards it
    with `prior_lam` per training row (the hierarchical borrowing tested for the WNBA)."""
    from oddsmarkets.basketball.research import improve as I
    p = p.copy()
    have = p.dropna(subset=["mk_mu"])
    mu = pd.Series(np.nan, index=p.index)
    coefs = {}
    for s in sorted(have.season.unique()):
        tr = have[(have.season < s) & have.y_sp.notna()]
        te = have[have.season == s]
        if len(tr) < 300 or te.empty:
            continue
        X = tr[sp_feats].fillna(0).to_numpy(float)
        y = tr.y_sp.to_numpy(float)
        Xi = np.column_stack([np.ones(len(X)), X])
        Pm = np.eye(Xi.shape[1]) * 1.0
        Pm[0, 0] = 1e-8
        m0 = np.zeros(Xi.shape[1])
        cp = coef_prior.get(int(s), coef_prior.get(str(int(s)))) if coef_prior and any(
            isinstance(v, dict) for v in coef_prior.values()) else coef_prior
        if cp is not None and prior_lam > 0:
            lamv = np.full(Xi.shape[1], prior_lam * len(X))
            lamv[0] = 1e-8
            Pm = np.diag(lamv)
            m0 = np.array([0.0] + [float(cp.get(f, 0.0)) for f in sp_feats])
        b = np.linalg.solve(Xi.T @ Xi + Pm, Xi.T @ y + Pm @ m0)
        Xt = np.column_stack([np.ones(len(te)), te[sp_feats].fillna(0).to_numpy(float)])
        mu[te.index] = Xt @ b
        coefs[int(s)] = dict(zip(["const"] + sp_feats, np.round(b, 4).tolist()))
    p[f"{name}_mu"] = mu
    v, fits = I.probit_wf(p, f"{name}_mu", train_from=I.MK_TRAIN_FROM[league])
    p[f"p_{name}"] = np.where(np.isfinite(v), v, p["p_M1"])
    p.attrs.setdefault("r4_coef", {})[name] = coefs
    p.attrs.setdefault("r4_probit", {})[name] = fits
    return p


# ── E: Kalshi player-points prices, the teammates' repricing ─────────────────

def _strikes(league: str) -> dict[str, float]:
    from oddsmarkets.basketball.research import props as PR
    p = PR.CACHE / PR.SERIES[league] / "markets.json"
    try:
        return {m["ticker"]: float(m.get("floor_strike")) for m in json.loads(p.read_text()) if m.get("floor_strike") is not None}
    except (OSError, ValueError):
        return {}


def _lg(x: float) -> float:
    x = min(0.98, max(0.02, x))
    return math.log(x / (1 - x))


def props_uplift(league: str, season: int, kind: str = "tip-1h", last_n: int = 10, shrink: float = 4.0) -> pd.DataFrame:
    """Per game with a Kalshi points event: U_h, U_a = mean over the team's listed, quoted players at T of
    logit(mid of the lowest strike) - logit(the player's recent rate of clearing it), and the counts. Points history
    comes from box scores of games of US days <= D - 1."""
    from oddsmarkets.basketball.research import props as PR
    st = G.load_store(league, season) or {}
    games = st.get("games") or {}
    lst = PR.game_listings(league, season, st)
    strike = _strikes(league)
    rows = G.finished(games, league)
    pts: dict[str, list[float]] = defaultdict(list)
    gl = sorted(((G.local_day(g), gid) for gid, g in games.items()
                 if g.get("stype") in G.COUNTED and g.get("status") == "post" and G.local_day(g)), key=lambda x: (x[0], x[1]))
    pi = 0
    out = []
    for D, gid in gl:
        cut = D - timedelta(days=1)
        while pi < len(rows) and rows[pi]["day"] <= cut:
            g0 = games[rows[pi]["id"]]
            for t, b in (g0.get("box") or {}).items():
                for r in b.get("players") or []:
                    if float(r[2] or 0) > 0 and r[3] is not None:
                        pts[str(r[0])].append(float(r[3]))
            pi += 1
        L = lst.get(gid)
        if not L:
            continue
        g = games[gid]
        T = PR.decision_ts(g, kind)
        rec = {"event_id": gid, "day": D}
        for side, k in (("home", "h"), ("away", "a")):
            t = str(g[side])
            zs = []
            by_pid = {r["pid"]: r for r in (L.get(t) or []) if r.get("pid")}
            for pid, s in PR.state_at(L.get(t) or [], T).items():
                if not s["listed"] or s.get("bid") is None or s.get("ask") is None:
                    continue
                if not (0.005 < s["bid"] <= s["ask"] < 0.995):
                    continue
                kk = strike.get(by_pid[pid]["ticker"])
                hist = pts.get(pid) or []
                if kk is None or len(hist) < 3:
                    continue
                hs = sum(1 for x in hist if x > kk)
                ps = (hs + 1) / (len(hist) + 2)
                rec10 = hist[-last_n:]
                pe = (sum(1 for x in rec10 if x > kk) + shrink * ps) / (len(rec10) + shrink)
                zs.append(_lg((s["bid"] + s["ask"]) / 2) - _lg(pe))
            rec[f"U_{k}"] = float(np.mean(zs)) if zs else 0.0
            rec[f"nU_{k}"] = len(zs)
        out.append(rec)
    return pd.DataFrame(out)


def probit_offset_fit(mu: np.ndarray, sd: float, x: np.ndarray, y: np.ndarray) -> float:
    """beta maximising sum log Phi(+-(mu + beta x) / sd) (one coefficient on top of a fixed margin model)."""
    from scipy.optimize import minimize_scalar

    def nll(b):
        z = (mu + b * x) / sd
        return -float(np.sum(y * norm.logcdf(z) + (1 - y) * norm.logcdf(-z)))
    return float(minimize_scalar(nll, bounds=(-20, 20), method="bounded").x)



# ── the round-4 experiment log (scripts/bb_edge.py round4 -> data/edge/basketball_experiments.json) ──────────

DEV = {"nba": range(2014, 2024), "wnba": range(2018, 2024)}
WALK_FROM = {"nba": 2012, "wnba": 2016}
STATIC_FROM = {"nba": 2004, "wnba": 2006}
TEST_CUT = date(2026, 2, 1)                      # E: dev before, test from (the round-3 slices)
TAUS = (0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)


def availability_table(league: str, p: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """p with xd_/xt_/xs_<var>_<a0|aB> columns (availability, totals availability, absolute expected strength; each
    times pace / 100) for every value variant and both P(plays) versions, plus the player-level P(plays) scores."""
    from oddsmarkets.basketball.research import evaluate as V
    trs, prs = zip(*[walk_cached(league, s, LAMS) for s in range(WALK_FROM[league], 2027)])
    TR, PRA = pd.concat(trs, ignore_index=True), pd.concat(prs, ignore_index=True)
    old = [walk_cached(league, s, ())[1] for s in range(STATIC_FROM[league], WALK_FROM[league])]
    cols = list(old[0].columns) if old else [c for c in PRA.columns if not c.startswith("v_l")]
    PRall = pd.concat(old + [PRA[cols]], ignore_index=True)
    PRall["aB"], fits = pplays_wf(PRall, first_train=STATIC_FROM[league])
    PRall["a0"] = streak_rate(PRall, league)
    m = PRall.season.isin(list(DEV[league])) & (PRall.mpg >= 15) & PRall.aB.notna()
    y = PRall.played[m].to_numpy(float)
    pl = {"n": int(m.sum()), "ll_streak": V.logloss(PRall.a0[m], y), "ll_model": V.logloss(PRall.aB[m], y),
          "brier_streak": V.brier(PRall.a0[m], y), "brier_model": V.brier(PRall.aB[m], y),
          "fit_last": fits.get(max(fits)) if fits else None}
    keys = ["event_id", "side", "pid"]
    PRA = PRA.merge(PRall[keys + ["aB"]].drop_duplicates(keys), on=keys, how="left")
    PRA["a0"] = streak_rate(PRA, league)
    PRA["aB"] = PRA["aB"].fillna(PRA["a0"])
    k = p.set_index("event_id")["pace_g"] / 100.0
    q = p.copy()
    for var in ["static"] + [f"l{int(l)}" for l in LAMS]:
        for an in ("a0", "aB"):
            tag = f"{var}_{an}"
            w = av_columns(TR, PRA, PRA[an].to_numpy(), var, league, tag).set_index("event_id")
            kk = k.reindex(w.index)
            q = q.merge(pd.DataFrame({f"xd_{tag}": (w[f"av_h_{tag}"] - w[f"av_a_{tag}"]) * kk,
                                      f"xt_{tag}": (w[f"tav_h_{tag}"] + w[f"tav_a_{tag}"]) * kk,
                                      f"xs_{tag}": (w[f"sx_h_{tag}"] - w[f"sx_a_{tag}"]) * kk}).reset_index(),
                        on="event_id", how="left")
    return q, pl


def _feats(tag: str, absolute: bool = False) -> list[str]:
    from oddsmarkets.basketball.research import experiments as X
    f = [c if c != "x_dSl" else f"xd_{tag}" for c in X.C_SP_FEATS]
    return f + ([f"xs_{tag}"] if absolute else [])


def experiment_log() -> dict:
    """Every round-4 experiment as pre-registered (basketball_edge.md, "Round 4"): dev selections, the single test
    of the combined NBA model, the Kalshi-price rule on the 2026 slices, the WNBA borrowing, schedule extras."""
    from oddsmarkets.basketball.research import experiments as X
    from oddsmarkets.basketball.research import improve as I
    from oddsmarkets.basketball.research import props_eval as PE
    res: dict = {"preregistered": "basketball_edge.md, Round 4 (22 Oct 2026 16:05 UTC)"}
    need = ["p_close", "p_open"]
    ps = {lg: I.add_probs(I.candidates(lg), lg) for lg in ("nba", "wnba")}
    for lg in ("nba", "wnba"):
        q, pl = availability_table(lg, ps[lg])
        q = refit_informed(q, lg, list(X.C_SP_FEATS), "prod")
        q = refit_informed(q, lg, _feats("static_a0"), "b0")
        names = ["prod", "b0"]
        for var in [f"l{int(l)}" for l in LAMS]:
            q = refit_informed(q, lg, _feats(f"{var}_a0"), f"A_{var}")
            q = refit_informed(q, lg, _feats(f"{var}_a0", True), f"Ap_{var}")
            names += [f"A_{var}", f"Ap_{var}"]
        q = refit_informed(q, lg, _feats("static_aB"), "B")
        q = refit_informed(q, lg, _feats("static_a0", True), "S_abs")
        names += ["B", "S_abs"]
        ex = pd.concat([schedule_extras(lg, s) for s in sorted(q.season.unique())])
        q = q.merge(ex, on="event_id", how="left")
        q = refit_informed(q, lg, list(X.C_SP_FEATS) + ["x_3in4", "x_g7", "x_trip", "x_tzs"], "C_sched")
        names.append("C_sched")
        cf = q.attrs["r4_coef"]
        r = {"player_level_pplays": pl, "dev_vs_b0": I.compare(q, [f"p_{n}" for n in names], "p_b0", DEV[lg]),
             "dev_C_vs_prod": I.compare(q, ["p_prod", "p_C_sched"], "p_prod", DEV[lg]),
             "coef_last": {n: (cf[n].get(max(cf[n])) if cf.get(n) else None) for n in names}}
        if lg == "nba":
            r["test_F_vs_prod"] = I.compare(q, ["p_prod", "p_Ap_l20000", "p_close", "p_open"], "p_prod", I.TEST, need=need)
            r["test_diagnostics_vs_prod"] = I.compare(q, ["p_A_l20000", "p_B", "p_S_abs", "p_A_l8000", "p_C_sched"],
                                                       "p_prod", I.TEST, need=need)
            r["test_F_by_season"] = {int(s): I.compare(q, ["p_Ap_l20000"], "p_prod", [s], need=need) for s in I.TEST}
            r["test_vs_close"] = I.compare(q, ["p_prod", "p_Ap_l20000"], "p_close", I.TEST, need=need)
        res[lg] = r
    # D: WNBA coefficients pulled towards the NBA's (NBA fold s = NBA seasons <= s - 1)
    qn = refit_informed(ps["nba"], "nba", list(X.C_SP_FEATS), "prod")
    prior = qn.attrs["r4_coef"]["prod"]
    grid = []
    for tau in TAUS:
        w = refit_informed(ps["wnba"], "wnba", list(X.C_SP_FEATS), "h", coef_prior=prior, prior_lam=tau)
        grid.append({"tau": tau, **I.compare(w, ["p_h"], "p_M0", DEV["wnba"])[0]})
    best = min(grid, key=lambda g: g["logloss"])["tau"]
    w = refit_informed(ps["wnba"], "wnba", list(X.C_SP_FEATS), "h", coef_prior=prior, prior_lam=best)
    res["D_wnba"] = {"dev_grid": grid, "tau": best, "test_vs_M0": I.compare(w, ["p_M0", "p_h"], "p_M0", I.TEST, need=need)}
    # E: teammates' repricing in Kalshi's player-points ladders (NBA 2026; WNBA 2026 secondary)
    p = ps["nba"]
    c0, sd = p.attrs["probit"]["C"][2026]
    u = props_uplift("nba", 2026).drop(columns=["day"])
    x = p[p.season == 2026].merge(u, on="event_id", how="inner")
    x["day"] = pd.to_datetime(x["day"]).dt.date
    x["mu"], x["xU"] = x.c_mu + c0, x.U_h - x.U_a
    dev = x[x.day < TEST_CUT]
    beta = probit_offset_fit(dev.mu.to_numpy(), sd, dev.xU.to_numpy(), dev.y.to_numpy())
    te = x[x.day >= TEST_CUT].copy()
    te["p_base"], te["p_E"] = norm.cdf(te.mu / sd), norm.cdf((te.mu + beta * te.xU) / sd)
    res["E_nba"] = {"beta": beta, "n_dev": len(dev), "test": PE.score(te, ["p_E"], "p_base")}
    pw = ps["wnba"]
    c0w, sdw = pw.attrs["probit"]["C"][2026]
    uw = props_uplift("wnba", 2026).drop(columns=["day"])
    xw = pw[pw.season == 2026].merge(uw, on="event_id", how="inner")
    xw["mu"], xw["xU"] = xw.c_mu + c0w, xw.U_h - xw.U_a
    xw["p_base"], xw["p_E"] = norm.cdf(xw.mu / sdw), norm.cdf((xw.mu + beta * xw.xU) / sdw)
    res["E_wnba"] = PE.score(xw, ["p_E", "p_M0"], "p_base")
    path = X.OUT / "basketball_experiments.json"
    try:
        allres = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        allres = {}
    allres["round4_2026_10"] = res
    path.write_text(json.dumps(allres, default=X._js, indent=1), "utf-8")
    return res
