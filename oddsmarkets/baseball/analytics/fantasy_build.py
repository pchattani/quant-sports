"""
The fantasy payloads and their walk-forward backtests (analytics/fantasy.py is the engine; MODELS.md section 28).

    mlb/fantasy.json           the current projections: next season's draft lines (between seasons) or the rest of the
                               season and next week (in season), 5x5 and points values, positions, tiers, dynasty
                               values, skills against results (buy low / sell high), steals, closers and set-up men,
                               two-start and streaming starters (in season), our picks
    mlb/fantasy_backtest.json  the backtests: season (draft) projections 2018-2026 against the official lines, against
                               last season; rest of season from 1 June, 1 July and 1 August (2022 on) against the season-to-
                               date pace; next week (2022 on) against the season-to-date rate, with and without matchups

Every projection uses data before its date only: the component projections of the seasons before (and the season to
date), and the context fits (runs, RBI, wins, playing time, roles) on the seasons before. The backtests are cached under
<cache>/fantasy/ by season, so a build recomputes only the season under way.

Sources: official lines from the MLB Stats API (analytics/mlbapi.py), the Statcast pitch tables, the stores (lineups,
probable starters, schedules), our park factors. Third-party fantasy data (ADP, ownership, platform rankings) is not used:
the platforms' terms do not allow it (and FanGraphs, Baseball-Reference, NFBC data cannot be scraped), so "our picks" are
judged against our own baselines (last season, season to date), not against a market.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import fantasy as F
from oddsmarkets.baseball.analytics import mlbapi

log = logging.getLogger(__name__)
VERSION = "fantasy-1"
FIRST = 2015


# ── the data a projection needs ─────────────────────────────────────────────

class Data:
    def __init__(self, level: str = "mlb", last: int | None = None, statsapi: bool = False, today: date | None = None):
        self.level = level
        seasons = an.seasons_on_disk(level)
        self.last = last or (max(seasons) if seasons else 2026)
        c = mlbapi.client(40) if statsapi else None
        self.lines: dict[int, dict] = {}
        for s in range(FIRST, self.last + 1):
            h = mlbapi.season_lines(level, s, "hitting", c if s >= self.last - 0 else None, today=today)
            p = mlbapi.season_lines(level, s, "pitching", c if s >= self.last - 0 else None, today=today)
            if h or p:
                self.lines[s] = {"hitting": h or {}, "pitching": p or {}}
        self.leagues = {s: F.league(v["hitting"], v["pitching"]) for s, v in self.lines.items()}
        self.stores = {s: an.load_store(level, s) for s in self.lines}
        self.ctx = {s: F.store_context(st) for s, st in self.stores.items()}
        self.sprint: dict[int, dict] = {}
        self.client = c
        self.today = today

    def sprint_of(self, s: int) -> dict:
        if s not in self.sprint:
            d: dict = {}
            try:
                from oddsmarkets.baseball.models import projections as PJ
                ser = PJ.sprint_speed(s)
                d = {str(k): float(v) for k, v in ser.items()}
            except Exception:                              # noqa: BLE001
                d = {}
            if not d:
                cat = an.read_json(an.data_root() / self.level / str(s) / "hitters.json") or {}
                for pid, r in (cat.get("players") or {}).items():
                    v = (r.get("values") or {}).get("sprint_speed")
                    if v is not None:
                        d[pid] = float(v)
            self.sprint[s] = d
        return self.sprint[s]

    def weeks(self, s: int) -> dict:
        c = self.client if s == self.last else None          # the season under way: new weeks are fetched
        return {g: mlbapi.week_lines(self.level, s, g, self.stores.get(s), c, self.today) for g in ("hitting", "pitching")}


def fits_for(D: Data, T: int) -> dict:
    """The context fits for target season T from seasons before it."""
    prior = [s for s in sorted(D.lines) if s < T and s != 2020][-6:]
    return {"ctx": F.fit_context(prior, D.lines, D.ctx, D.leagues),
            "time": F.fit_time([s for s in sorted(D.lines) if s + 1 < T], D.lines),
            "roles": F.fit_roles([s for s in sorted(D.lines) if s + 1 < T], D.lines)}


def _prev_full(D: Data, T: int) -> int:
    s = T - 1
    return s


# ── next season ─────────────────────────────────────────────────────────────

def project_next(D: Data, T: int, teams: dict[str, str] | None = None, fits: dict | None = None) -> dict:
    """{"H": {pid: line}, "P": {pid: line}, "meta": {pid: {...}}} for season T from data through T-1. teams: the club
    each player will play for (from the transactions) when it differs from his last club."""
    from oddsmarkets.baseball.models import projections as PJ
    fits = fits or fits_for(D, T)
    S = T - 1
    lg = dict(D.leagues.get(S) or {})
    lg_rg = lg.get("rg") or 4.5
    cx = D.ctx.get(S) or {}
    hit = PJ.project(D.level, T, "next", role="hitter")
    pit = PJ.project(D.level, T, "next", role="pitcher")
    lh = (D.lines.get(S) or {}).get("hitting") or {}
    lh2 = (D.lines.get(S - 1) or {}).get("hitting") or {}
    lp = (D.lines.get(S) or {}).get("pitching") or {}
    lp2 = (D.lines.get(S - 1) or {}).get("pitching") or {}
    scale = 162.0 / 60.0 if S == 2020 else 1.0
    scale2 = 162.0 / 60.0 if S - 1 == 2020 else 1.0
    th, tp = fits["time"].get("H"), fits["time"].get("P")
    sprint = D.sprint_of(S)
    out: dict[str, Any] = {"H": {}, "P": {}, "meta": {}}
    seasons = [s for s in (S, S - 1, S - 2) if s in D.lines]
    pb = set(hit.attrs.get("pitcher_batters") or [])
    for pid, r in hit.iterrows():
        pid = str(pid)
        if pid in pb:
            continue
        x, x2 = lh.get(pid) or {}, lh2.get(pid) or {}
        pa1, pa2 = float(x.get("pa") or 0) * scale, float(x2.get("pa") or 0) * scale2
        if pa1 + pa2 <= 0:
            continue
        age = float(r["age"]) - 28.0 if r.get("age") is not None and np.isfinite(r.get("age") or np.nan) else 0.0
        pa = float(np.dot(th, [1.0, pa1, pa2, age, age * age])) if th else 0.5 * pa1 + 0.1 * pa2 + 200
        pa = min(max(pa, 0.0), 720.0)
        tid = (teams or {}).get(pid) or x.get("team") or cx.get("player_team", {}).get(pid)
        rg_rel = 0.5 * (F.team_rg(cx, tid, lg_rg) - lg_rg)
        att, succ = F.sb_rates(pid, seasons, D.lines, D.leagues, sprint.get(pid), lg)
        line = F.hitter_line(r["rates"], pa, lg, fits["ctx"], att, succ, rg_rel, F.mean_slot(cx, pid))
        out["H"][pid] = line
        out["meta"]["H:" + pid] = {"age": r.get("age"), "team": tid, "woba": r.get("wOBA"), "slot": round(F.mean_slot(cx, pid), 1),
                                   "sb_att": att, "sb_succ": succ, "sprint": sprint.get(pid)}
    tot_sv = defaultdict(float)
    tot_hld = defaultdict(float)
    for x in lp.values():
        if x.get("team"):
            tot_sv[x["team"]] += float(x.get("sv") or 0)
            tot_hld[x["team"]] += float(x.get("hld") or 0)
    roles = fits["roles"]
    for pid, r in pit.iterrows():
        pid = str(pid)
        x, x2 = lp.get(pid) or {}, lp2.get(pid) or {}
        bf1, bf2 = float(x.get("bf") or 0) * scale, float(x2.get("bf") or 0) * scale2
        if bf1 + bf2 <= 0:
            continue
        g1, gs1 = float(x.get("g") or 0) + 0.5 * float(x2.get("g") or 0), float(x.get("gs") or 0) + 0.5 * float(x2.get("gs") or 0)
        share = gs1 / max(g1, 1.0)
        age = float(r["age"]) - 28.0 if r.get("age") is not None and np.isfinite(r.get("age") or np.nan) else 0.0
        bf = float(np.dot(tp, [1.0, bf1, bf2, share, age])) if tp else 0.5 * bf1 + 0.1 * bf2 + 60
        bf = min(max(bf, 0.0), 900.0)
        bf_all = float(x.get("bf") or 0) + float(x2.get("bf") or 0)
        relief_g = max(g1 - gs1, 0.0)
        relief_bf = relief_g * 4.3
        start_bf = max(bf_all - relief_bf * (1.0 if x2 else 1.0), 0.0)
        bf_per_gs = min(max(start_bf / gs1, 15.0), 28.0) if gs1 > 0 else 22.0
        start_share = start_bf / max(start_bf + relief_bf, 1.0) if gs1 > 0 else 0.0
        gs = bf * start_share / bf_per_gs
        g = gs + bf * (1 - start_share) / 4.3
        tid = (teams or {}).get(pid) or x.get("team") or x2.get("team")
        wp = 0.5 + 0.5 * (F.team_wpct(cx, tid) - 0.5)
        sv_sh = float(x.get("sv") or 0) / tot_sv[tid] if tid and tot_sv.get(tid) else 0.0
        hl_sh = float(x.get("hld") or 0) / tot_hld[tid] if tid and tot_hld.get(tid) else 0.0
        moved = bool((teams or {}).get(pid)) and (teams or {}).get(pid) != x.get("team")
        keep = 0.6 if moved else 1.0
        team_sv = (lg.get("sv_team") or 40.0) * wp / 0.5
        line = F.pitcher_line(r["rates"], bf, gs, g, lg, fits["ctx"], wp, roles.get("sv", 0.6) * sv_sh * keep,
                              roles.get("hld", 0.5) * hl_sh * keep, team_sv, lg.get("hld_team") or 60.0)
        out["P"][pid] = line
        out["meta"]["P:" + pid] = {"age": r.get("age"), "team": tid, "sv_share": round(sv_sh, 3), "hld_share": round(hl_sh, 3),
                                   "role": "SP" if start_share >= 0.5 else "RP"}
    return out


# ── season backtest ─────────────────────────────────────────────────────────

def _baseline(D: Data, T: int, kind: str, pid: str) -> dict | None:
    s = T - 1
    g = "hitting" if kind == "H" else "pitching"
    x = ((D.lines.get(s) or {}).get(g) or {}).get(pid)
    if not x:
        return None
    y = F.actual_line(x, kind)
    if s == 2020:
        y = {k: (v * 162.0 / 60.0 if k not in ("avg", "era", "whip") else v) for k, v in y.items()}
    return y


def season_backtest(D: Data, T: int) -> dict:
    """Projection for T against T's official lines, with last season's line as the naive forecast, on the players a
    drafter would have considered: those who qualified the season before (300 PA; 50 IP) and whom the projection covers.
    A player who did not play in T counts with an empty line (the honest draft-day test: injuries and lost jobs count)."""
    proj = project_next(D, T)
    out = {}
    for kind, g, need0 in (("H", "hitting", 300), ("P", "pitching", 150)):
        act = (D.lines.get(T) or {}).get(g) or {}
        prev = (D.lines.get(T - 1) or {}).get(g) or {}
        ids, P_, A_, B_ = [], {}, {}, {}
        empty = F.actual_line({}, kind)
        for pid in prev:
            b = _baseline(D, T, kind, pid)
            if not b or (b.get("pa") if kind == "H" else b.get("outs")) < need0 or pid not in proj[kind]:
                continue
            ids.append(pid)
            P_[pid], B_[pid] = proj[kind][pid], b
            A_[pid] = F.actual_line(act[pid], kind) if pid in act else dict(empty)
        if len(ids) < 30:
            continue
        cats = ("r", "hr", "rbi", "sb", "avg") if kind == "H" else ("w", "sv", "so", "era", "whip")
        res: dict[str, Any] = {"n": len(ids)}
        for c in cats:
            if c in ("avg", "era", "whip"):
                wk = "ab" if kind == "H" else "ip"
                w = np.array([A_[p][wk] for p in ids]) + 1e-9
                e1 = np.array([abs(P_[p][c] - A_[p][c]) for p in ids])
                e0 = np.array([abs(B_[p][c] - A_[p][c]) for p in ids])
                res[c] = {"model": round(float((w * e1).sum() / w.sum()), 4), "last": round(float((w * e0).sum() / w.sum()), 4)}
            else:
                res[c] = {"model": round(float(np.mean([abs(P_[p][c] - A_[p][c]) for p in ids])), 2),
                          "last": round(float(np.mean([abs(B_[p][c] - A_[p][c]) for p in ids])), 2)}
        pts_p = [F.points(P_[p], kind) for p in ids]
        pts_a = [F.points(A_[p], kind) for p in ids]
        pts_b = [F.points(B_[p], kind) for p in ids]
        res["points"] = {"model": round(float(np.mean(np.abs(np.array(pts_p) - pts_a))), 1),
                         "last": round(float(np.mean(np.abs(np.array(pts_b) - pts_a))), 1),
                         "rank_model": _r(F.spearman(pts_p, pts_a)), "rank_last": _r(F.spearman(pts_b, pts_a))}
        n_pool = min(F.N_HIT if kind == "H" else F.N_PIT, len(ids))
        zp, _ = F.zvalues(P_, kind, n_pool)
        za, _ = F.zvalues(A_, kind, n_pool)
        zb, _ = F.zvalues(B_, kind, n_pool)
        res["value_5x5"] = {"rank_model": _r(F.spearman([zp[p]["total"] for p in ids], [za[p]["total"] for p in ids])),
                            "rank_last": _r(F.spearman([zb[p]["total"] for p in ids], [za[p]["total"] for p in ids]))}
        out[kind] = res
    return out


def _r(x):
    return round(x, 3) if x is not None else None


# ── rest of season and next week ────────────────────────────────────────────

def _partial(level: str, S: int, D_: str):
    from oddsmarkets.baseball.models import projections as PJ
    pa = PJ.pa_table(level, S)
    if pa is None or not len(pa):
        return None, None, None
    pa = pa[(pa["game_type"].astype(str) == "R") & (pa["game_date"].astype(str) < D_)]
    if not len(pa):
        return None, None, None
    h, p = PJ.aggregates_from_pa(pa)
    return h, p, (str(pa["game_date"].min())[:10], str(pa["game_date"].max())[:10])


def ros_rates(level: str, S: int, D_: str) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Rest-of-season component projections as of date D_ (counts before D_), cached per date."""
    from oddsmarkets.baseball.models import projections as PJ
    cdir = an.cache_root() / "fantasy"
    cdir.mkdir(parents=True, exist_ok=True)
    src = an.pitch_path(level, S)
    stamp = int(src.stat().st_mtime) if src.exists() else 0
    cp = cdir / f"ros_{level}_{S}_{D_}_{stamp if D_ >= str(date.today() - timedelta(days=3)) else 0}.pkl"
    if cp.exists():
        try:
            return pd.read_pickle(cp)
        except Exception:                                 # noqa: BLE001
            pass
    h, p, dates = _partial(level, S, D_)
    if h is None:
        return None
    hit = PJ.project(level, S, "ros", role="hitter", partial=h, extras_season=S - 1, partial_pitchers=p, partial_dates=dates)
    pit = PJ.project(level, S, "ros", role="pitcher", partial=p, extras_season=S - 1)
    keep = ["rates", "rates_L", "rates_R", "hand", "age", "wOBA", "PA"]
    res = (hit[[c for c in keep if c in hit.columns]], pit[[c for c in keep if c in pit.columns]])
    pd.to_pickle(res, cp)
    return res


def _sum_lines(weeks: dict, lo: str, hi: str | None = None) -> dict[str, dict]:
    """Sum of weekly lines whose Monday is in [lo, hi)."""
    out: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for mon, rows in weeks.items():
        if mon < lo or (hi and mon >= hi):
            continue
        for pid, x in (rows or {}).items():
            o = out[pid]
            for k, v in x.items():
                if isinstance(v, (int, float)) and k not in ("teams", "age"):
                    o[k] += v
            o["team"] = x.get("team") or o.get("team")
    return {k: dict(v) for k, v in out.items()}


def _team_games(store: dict, lo: str, hi: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for g in (store.get("games") or {}).values():
        if g.get("gtype") != "R":
            continue
        d = str(g.get("date"))[:10]
        if lo <= d < hi and g.get("status") not in ("postponed", "cancelled"):
            out[g.get("home")] += 1
            out[g.get("away")] += 1
    return dict(out)


def ros_project(D: Data, S: int, D_: str, fits: dict, weeks: dict) -> dict | None:
    """Rest-of-season lines as of D_ (the team's games from D_ to the end of the regular season)."""
    rr = ros_rates(D.level, S, D_)
    if rr is None:
        return None
    hit, pit = rr
    st = D.stores.get(S) or {}
    end = "9999"
    left = _team_games(st, D_, end)
    played = _team_games(st, "0000", D_)
    std_h = _sum_lines(weeks["hitting"], "0000", D_)
    std_p = _sum_lines(weeks["pitching"], "0000", D_)
    lg = dict(D.leagues.get(S - 1) or {})
    cx = F.store_context(st, None, (date.fromisoformat(D_) - timedelta(days=1)).isoformat())
    lg_rg = lg.get("rg") or 4.5
    prev_h = (D.lines.get(S - 1) or {}).get("hitting") or {}
    prev_p = (D.lines.get(S - 1) or {}).get("pitching") or {}
    sprint = D.sprint_of(S - 1)
    out: dict[str, Any] = {"H": {}, "P": {}, "std": {"H": std_h, "P": std_p}, "games_left": left, "games_played": played}
    seasons = [s for s in (S - 1, S - 2, S - 3) if s in D.lines]
    for pid, r in hit.iterrows():
        pid = str(pid)
        x = std_h.get(pid) or {}
        tid = cx.get("player_team", {}).get(pid) or x.get("team")
        if not tid or not played.get(tid):
            continue
        k = 30.0
        per_g = (float(x.get("pa") or 0) + k * float((prev_h.get(pid) or {}).get("pa") or 0) / 162.0) / (played[tid] + k)
        pa = per_g * left.get(tid, 0)
        if pa < 5:
            continue
        att, succ = F.sb_rates(pid, seasons, D.lines, D.leagues, sprint.get(pid), lg)
        rg_rel = F.team_rg(cx, tid, lg_rg) - lg_rg
        out["H"][pid] = F.hitter_line(r["rates"], pa, lg, fits["ctx"], att, succ, rg_rel, F.mean_slot(cx, pid))
    tot_sv, tot_hld = defaultdict(float), defaultdict(float)
    for x in std_p.values():
        if x.get("team"):
            tot_sv[x["team"]] += x.get("sv", 0.0)
            tot_hld[x["team"]] += x.get("hld", 0.0)
    for pid, r in pit.iterrows():
        pid = str(pid)
        x = std_p.get(pid) or {}
        tid = x.get("team") or cx.get("player_team", {}).get(pid)
        if not tid or not played.get(tid):
            continue
        prev = prev_p.get(pid) or {}
        k = 30.0
        bf = (float(x.get("bf") or 0) + k * float(prev.get("bf") or 0) / 162.0) / (played[tid] + k) * left.get(tid, 0)
        gs = (float(x.get("gs") or 0) + k * float(prev.get("gs") or 0) / 162.0) / (played[tid] + k) * left.get(tid, 0)
        g = (float(x.get("g") or 0) + k * float(prev.get("g") or 0) / 162.0) / (played[tid] + k) * left.get(tid, 0)
        if bf < 5:
            continue
        wp = F.team_wpct(cx, tid)
        tl = left.get(tid, 0)
        sv_sh = x.get("sv", 0.0) / tot_sv[tid] if tot_sv.get(tid) else 0.0
        hl_sh = x.get("hld", 0.0) / tot_hld[tid] if tot_hld.get(tid) else 0.0
        out["P"][pid] = F.pitcher_line(r["rates"], bf, gs, g, lg, fits["ctx"], wp, sv_sh, hl_sh,
                                       tot_sv[tid] / max(played[tid], 1) * tl, tot_hld[tid] / max(played[tid], 1) * tl)
    return out


def ros_backtest(D: Data, S: int, fits: dict, cutoffs=("06-01", "07-01", "08-01")) -> dict:
    """Rest-of-season projections from each cutoff (the Monday on or after it) against the official lines after it; the
    naive forecast is the season-to-date pace (totals per team game times the games left; rates as they are)."""
    weeks = D.weeks(S)
    if not weeks["hitting"]:
        return {}
    mondays = sorted(weeks["hitting"])
    res: dict[str, Any] = {}
    for cut in cutoffs:
        D_ = next((m for m in mondays if m >= f"{S}-{cut}"), None)
        if not D_:
            continue
        pr = ros_project(D, S, D_, fits, weeks)
        if not pr:
            continue
        for kind, g, need_std, need_ros in (("H", "hitting", 100, 50), ("P", "pitching", 60, 30)):
            act = _sum_lines(weeks[g], D_)
            std = pr["std"][kind]
            ids = []
            for pid, a in act.items():
                s0 = std.get(pid) or {}
                n_std = s0.get("pa", 0) if kind == "H" else s0.get("outs", 0)
                n_ros = a.get("pa", 0) if kind == "H" else a.get("outs", 0)
                if n_std >= need_std and n_ros >= need_ros and pid in pr[kind]:
                    ids.append(pid)
            if len(ids) < 30:
                continue
            A_ = {p: F.actual_line(act[p], kind) for p in ids}
            B_ = {}
            for p in ids:
                s0 = std[p]
                tid = s0.get("team")
                f = (pr["games_left"].get(tid, 0) / max(pr["games_played"].get(tid, 1), 1)) if tid else 1.0
                b = F.actual_line(s0, kind)
                B_[p] = {k: (v * f if k not in ("avg", "era", "whip") else v) for k, v in b.items()}
            cell = res.setdefault(kind, defaultdict(lambda: [0.0, 0.0, 0, [], [], []]))
            for c in (("r", "hr", "rbi", "sb") if kind == "H" else ("w", "sv", "so")):
                z = cell[c]
                z[0] += sum(abs(pr[kind][p][c] - A_[p][c]) for p in ids)
                z[1] += sum(abs(B_[p][c] - A_[p][c]) for p in ids)
                z[2] += len(ids)
            z = cell["points"]
            pp = [F.points(pr[kind][p], kind) for p in ids]
            pa_ = [F.points(A_[p], kind) for p in ids]
            pb = [F.points(B_[p], kind) for p in ids]
            z[0] += float(np.abs(np.array(pp) - pa_).sum())
            z[1] += float(np.abs(np.array(pb) - pa_).sum())
            z[2] += len(ids)
            z[3].append(F.spearman(pp, pa_))
            z[4].append(F.spearman(pb, pa_))
    return {k: {c: v for c, v in d.items()} for k, d in res.items()}


def _week_pt(D: Data, S: int, mon: str, sun: str, std_h: dict, cx: dict) -> dict:
    """Games, starts and matchups of each club in the week: {tid: [(date, home?, opponent, opp probable, venue)]}."""
    st = D.stores.get(S) or {}
    out: dict[str, list] = defaultdict(list)
    for g in (st.get("games") or {}).values():
        if g.get("gtype") != "R":
            continue
        d = str(g.get("date"))[:10]
        if not (mon <= d <= sun) or g.get("status") in ("postponed", "cancelled"):
            continue
        pr = g.get("probables") or {}
        out[g.get("home")].append((d, True, g.get("away"), pr.get("away"), g.get("venue"), pr.get("home")))
        out[g.get("away")].append((d, False, g.get("home"), pr.get("home"), g.get("venue"), pr.get("away")))
    return dict(out)


def week_project(D: Data, S: int, mon: str, fits: dict, weeks: dict, parks: dict | None, matchups: bool = True,
                 throws: dict | None = None) -> dict | None:
    """Next-week lines from Monday `mon`: rest-of-season rates as of Monday; hitters' plate appearances = the club's
    games x the share of games he started in the last 21 days (shrunk) x plate appearances per start by lineup slot;
    starters' starts from the probable pitchers (two-start weeks), relievers' games from their rate per club game. With
    matchups: each game's rates against the opposing starter's hand (platoon) and the park's run and home-run factors."""
    rr = ros_rates(D.level, S, mon)
    if rr is None:
        return None
    hit, pit = rr
    sun = (date.fromisoformat(mon) + timedelta(days=6)).isoformat()
    st = D.stores.get(S) or {}
    cx_all = F.store_context(st, None, (date.fromisoformat(mon) - timedelta(days=1)).isoformat())
    cx21 = F.store_context(st, (date.fromisoformat(mon) - timedelta(days=21)).isoformat(), (date.fromisoformat(mon) - timedelta(days=1)).isoformat())
    sched = _week_pt(D, S, mon, sun, {}, cx_all)
    lg = dict(D.leagues.get(S - 1) or {})
    lg_rg = lg.get("rg") or 4.5
    std_p = _sum_lines(weeks["pitching"], "0000", mon)
    played = _team_games(st, "0000", mon)
    sprint = D.sprint_of(S - 1)
    seasons = [s for s in (S - 1, S - 2, S - 3) if s in D.lines]
    throws = throws or {}
    out: dict[str, Any] = {"H": {}, "P": {}, "starts": {}}
    for pid, r in hit.iterrows():
        pid = str(pid)
        tid = cx_all.get("player_team", {}).get(pid)
        games = sched.get(tid) or []
        if not tid or not games:
            continue
        s21 = (cx21.get("slot") or {}).get(pid)
        tg21 = ((cx21.get("team") or {}).get(tid) or {}).get("g") or 0
        p_start = ((s21[1] if s21 else 0) + 2 * 0.5) / (tg21 + 2) if tg21 else 0.0
        if p_start < 0.15:
            continue
        slot = F.mean_slot(cx21, pid, k=5.0)
        pa_start = 4.75 - 0.105 * (slot - 1.0)
        att, succ = F.sb_rates(pid, seasons, D.lines, D.leagues, sprint.get(pid), lg)
        rg_rel = F.team_rg(cx_all, tid, lg_rg) - lg_rg
        tot = None
        for (d, home, opp, opp_sp, venue, own_sp) in games:
            rates = r["rates"]
            pa = p_start * pa_start
            mult_r = mult_hr = 1.0
            if matchups:
                hand = throws.get(str(opp_sp)) if opp_sp else None
                if hand in ("L", "R") and isinstance(r.get("rates_" + hand), (list, np.ndarray)):
                    rates = 0.65 * np.asarray(r["rates_" + hand], float) + 0.35 * np.asarray(r["rates"], float)
                pf = ((parks or {}).get(str(venue)) or {}).get("factors") or {}
                mult_r, mult_hr = float(pf.get("runs") or 1.0), float(pf.get("HR") or 1.0)
            ln = F.hitter_line(rates, pa, lg, fits["ctx"], att, succ, rg_rel, slot)
            ln["hr"] *= mult_hr
            ln["r"] *= mult_r
            ln["rbi"] *= mult_r
            if tot is None:
                tot = dict(ln)
            else:
                for k_, v in ln.items():
                    tot[k_] += v
        if tot:
            tot["avg"] = tot["h"] / tot["ab"] if tot["ab"] > 0 else 0.0
            out["H"][pid] = tot
    for pid, r in pit.iterrows():
        pid = str(pid)
        x = std_p.get(pid) or {}
        tid = x.get("team") or cx_all.get("player_team", {}).get(pid)
        games = sched.get(tid) or []
        if not tid or not games:
            continue
        starts = [gm for gm in games if str(gm[5]) == pid]
        gs_std, g_std = float(x.get("gs") or 0), float(x.get("g") or 0)
        relief_rate = max(g_std - gs_std, 0.0) / max(played.get(tid, 1), 1)
        g_rel = relief_rate * len(games) if gs_std < 0.5 * max(g_std, 1) else 0.0
        if not starts and g_rel < 0.3:
            continue
        bf_gs = (float(x.get("bf") or 0) - 4.3 * max(g_std - gs_std, 0)) / gs_std if gs_std else 22.0
        bf_gs = min(max(bf_gs, 15.0), 28.0)
        bf_rel = 4.3
        bf = len(starts) * bf_gs + g_rel * bf_rel
        wp = F.team_wpct(cx_all, tid)
        tot_sv = sum((y.get("sv") or 0) for y in std_p.values() if y.get("team") == tid)
        tot_hld = sum((y.get("hld") or 0) for y in std_p.values() if y.get("team") == tid)
        sv_sh = (x.get("sv") or 0) / tot_sv if tot_sv else 0.0
        hl_sh = (x.get("hld") or 0) / tot_hld if tot_hld else 0.0
        rates = np.asarray(r["rates"], float)
        mult = 1.0
        if matchups and starts:
            m = []
            for gm in starts:
                pf = ((parks or {}).get(str(gm[4])) or {}).get("factors") or {}
                m.append(float(pf.get("runs") or 1.0))
            mult = float(np.mean(m))
        ln = F.pitcher_line(rates, bf, float(len(starts)), float(len(starts)) + g_rel, lg, fits["ctx"], wp, sv_sh, hl_sh,
                            tot_sv / max(played.get(tid, 1), 1) * len(games), tot_hld / max(played.get(tid, 1), 1) * len(games))
        ln["er"] *= mult
        ln["era"] *= mult
        out["P"][pid] = ln
        out["starts"][pid] = [[gm[0], gm[2], gm[1]] for gm in starts]
    return out


def week_backtest(D: Data, S: int, fits: dict, parks: dict | None, throws: dict) -> dict:
    """Every week from the fourth: the projection (with and without matchups) against the official week, and the season-
    to-date rate (points per club game for hitters and relievers, per start for starters) as the naive forecast; regular
    hitters (100+ PA to date) and pitchers with a start in the week or 15+ relief games to date."""
    weeks = D.weeks(S)
    mondays = sorted(weeks["hitting"])
    acc: dict[str, Any] = {}
    st = D.stores.get(S) or {}
    for mon in mondays[3:]:
        act_h, act_p = weeks["hitting"].get(mon) or {}, weeks["pitching"].get(mon) or {}
        if not act_h:
            continue
        pm = week_project(D, S, mon, fits, weeks, parks, True, throws)
        p0 = week_project(D, S, mon, fits, weeks, parks, False, throws)
        if not pm or not p0:
            continue
        std_h = _sum_lines(weeks["hitting"], "0000", mon)
        std_p = _sum_lines(weeks["pitching"], "0000", mon)
        played = _team_games(st, "0000", mon)
        sun = (date.fromisoformat(mon) + timedelta(days=6)).isoformat()
        wk_games = _team_games(st, mon, (date.fromisoformat(sun) + timedelta(days=1)).isoformat())
        for kind, act, std in (("H", act_h, std_h), ("P", act_p, std_p)):
            ids = []
            for pid in pm[kind]:
                s0 = std.get(pid) or {}
                if kind == "H" and s0.get("pa", 0) < 100:
                    continue
                if kind == "P" and not (pm["starts"].get(pid) or s0.get("g", 0) - s0.get("gs", 0) >= 15):
                    continue
                ids.append(pid)
            if len(ids) < 20:
                continue
            a = [F.points(F.actual_line(act[p], kind), kind) if p in act else 0.0 for p in ids]
            m = [F.points(pm[kind][p], kind) for p in ids]
            z = [F.points(p0[kind].get(p) or pm[kind][p], kind) for p in ids]
            b = []
            for p in ids:
                s0 = std.get(p) or {}
                tid = s0.get("team")
                pts = F.points(F.actual_line(s0, kind), kind) if s0 else 0.0
                if kind == "P" and pm["starts"].get(p):
                    b.append(pts / max(s0.get("gs", 0) or 1, 1) * len(pm["starts"][p]) if s0.get("gs") else pts / max(played.get(tid, 1), 1) * wk_games.get(tid, 6))
                else:
                    b.append(pts / max(played.get(tid, 1), 1) * wk_games.get(tid, 6))
            c = acc.setdefault(kind, {"n": 0, "mae_model": 0.0, "mae_nomatch": 0.0, "mae_std": 0.0, "rank_model": [], "rank_nomatch": [],
                                      "rank_std": []})
            a_ = np.array(a)
            c["n"] += len(ids)
            c["mae_model"] += float(np.abs(np.array(m) - a_).sum())
            c["mae_nomatch"] += float(np.abs(np.array(z) - a_).sum())
            c["mae_std"] += float(np.abs(np.array(b) - a_).sum())
            for key, arr in (("rank_model", m), ("rank_nomatch", z), ("rank_std", b)):
                v = F.spearman(arr, a)
                if v is not None:
                    c[key].append(v)
        cs = (pm.get("starts") or {})
        c2 = acc.setdefault("two_start", {"n": 0, "pts_two": 0.0, "pts_one": 0.0, "n_one": 0})
        for p, lst in cs.items():
            if p in act_p:
                pts = F.points(F.actual_line(act_p[p], "P"), "P")
                if len(lst) >= 2:
                    c2["n"] += 1
                    c2["pts_two"] += pts
                elif len(lst) == 1:
                    c2["n_one"] += 1
                    c2["pts_one"] += pts
    return acc


def _finish_week(acc: dict) -> dict:
    out = {}
    for kind in ("H", "P"):
        c = acc.get(kind)
        if not c or not c["n"]:
            continue
        out[kind] = {"n": c["n"], "mae_model": round(c["mae_model"] / c["n"], 2), "mae_nomatch": round(c["mae_nomatch"] / c["n"], 2),
                     "mae_std": round(c["mae_std"] / c["n"], 2),
                     "rank_model": _r(float(np.mean(c["rank_model"]))) if c["rank_model"] else None,
                     "rank_nomatch": _r(float(np.mean(c["rank_nomatch"]))) if c["rank_nomatch"] else None,
                     "rank_std": _r(float(np.mean(c["rank_std"]))) if c["rank_std"] else None, "weeks": len(c["rank_model"])}
    t = acc.get("two_start")
    if t and t["n"]:
        out["two_start"] = {"n": t["n"], "points_two": round(t["pts_two"] / t["n"], 1), "n_one": t["n_one"],
                            "points_one": round(t["pts_one"] / max(t["n_one"], 1), 1)}
    return out


def _merge_week(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if k not in a:
            a[k] = v
            continue
        for kk, vv in v.items():
            if isinstance(vv, list):
                a[k][kk] = a[k][kk] + vv
            else:
                a[k][kk] = a[k][kk] + vv
    return a


def _finish_ros(cells: list[dict]) -> dict:
    out = {}
    for kind in ("H", "P"):
        tot: dict = {}
        for c in cells:
            for cat, z in (c.get(kind) or {}).items():
                t = tot.setdefault(cat, [0.0, 0.0, 0, [], []])
                t[0] += z[0]
                t[1] += z[1]
                t[2] += z[2]
                t[3] += [x for x in z[3] if x is not None]
                t[4] += [x for x in z[4] if x is not None]
        if tot:
            out[kind] = {cat: {"n": t[2], "mae_model": round(t[0] / max(t[2], 1), 2), "mae_pace": round(t[1] / max(t[2], 1), 2),
                               **({"rank_model": _r(float(np.mean(t[3]))), "rank_pace": _r(float(np.mean(t[4])))} if t[3] else {})}
                         for cat, t in tot.items()}
    return out


def backtests(D: Data, current: int, force: bool = False) -> dict:
    """All three backtests, cached per season under <cache>/fantasy/ (a past season's results are kept; the current
    season's are recomputed when its stat lines or pitch table change)."""
    cdir = an.cache_root() / "fantasy"
    cdir.mkdir(parents=True, exist_ok=True)
    parks_by = {}
    people = an.load_people()
    throws = {}
    for s, st in D.stores.items():
        for pid, p in (st.get("players") or {}).items():
            if p.get("throws"):
                throws[pid] = p["throws"]
    seasons = [T for T in range(2018, current + 1) if T != 2020 and T in D.lines and T - 1 in D.lines]
    out = {"season": {}, "ros": {}, "week": {}}
    for T in seasons:
        src = an.pitch_path(D.level, T)
        # a past season is fixed; the season under way is recomputed once a day
        sig = f"{VERSION}-{len(D.lines[T]['hitting'])}-" + (str(date.today()) if T == current else str(int(src.stat().st_mtime) if src.exists() else 0))
        cp = cdir / f"backtest_{D.level}_{T}.json"
        got = an.read_json(cp)
        if got and got.get("sig") == sig and not force:
            res = got["res"]
        else:
            t0 = time.perf_counter()
            fits = fits_for(D, T)
            res = {"season": season_backtest(D, T)}
            if T >= 2022:
                if T - 1 not in parks_by:
                    parks_by[T - 1] = ((an.read_json(an.data_root() / D.level / str(T - 1) / "parks.json") or {}).get("parks")) or {}
                res["ros"] = ros_backtest(D, T, fits)
                res["week"] = week_backtest(D, T, fits, parks_by[T - 1], throws)
            an.write_json(cp, {"sig": sig, "res": an.clean(res)})
            res = an.read_json(cp)["res"]
            log.info("fantasy backtest %s: %.1f s", T, time.perf_counter() - t0)
        out["season"][str(T)] = res.get("season")
        if res.get("ros"):
            out["ros"][str(T)] = res["ros"]
        if res.get("week"):
            out["week"][str(T)] = res["week"]
    return out


def summarize(bt: dict) -> dict:
    """Pooled numbers for the page: per kind and category the model's and the baseline's error, and the rank correlations."""
    summ: dict[str, Any] = {"season": {}, "ros": {}, "week": {}}
    for kind in ("H", "P"):
        acc: dict = defaultdict(lambda: [0.0, 0.0, 0])
        rk: dict = defaultdict(list)
        for T, r in (bt.get("season") or {}).items():
            x = (r or {}).get(kind)
            if not x:
                continue
            n = x["n"]
            for c, v in x.items():
                if c == "n":
                    continue
                if c in ("points",):
                    acc[c][0] += v["model"] * n
                    acc[c][1] += v["last"] * n
                    acc[c][2] += n
                    rk["points_model"].append(v["rank_model"])
                    rk["points_last"].append(v["rank_last"])
                elif c == "value_5x5":
                    rk["value_model"].append(v["rank_model"])
                    rk["value_last"].append(v["rank_last"])
                else:
                    acc[c][0] += v["model"] * n
                    acc[c][1] += v["last"] * n
                    acc[c][2] += n
        summ["season"][kind] = {c: {"model": round(a / max(n, 1), 4 if c in ("avg", "era", "whip") else 2),
                                    "last": round(b / max(n, 1), 4 if c in ("avg", "era", "whip") else 2), "n": n} for c, (a, b, n) in acc.items()}
        summ["season"][kind]["ranks"] = {k: _r(float(np.mean([x for x in v if x is not None]))) if any(x is not None for x in v) else None
                                         for k, v in rk.items()}
    summ["ros"] = _finish_ros([v for v in (bt.get("ros") or {}).values()])
    wk: dict = {}
    for v in (bt.get("week") or {}).values():
        wk = _merge_week(wk, {k: (dict(x) if isinstance(x, dict) else x) for k, x in v.items()})
    summ["week"] = _finish_week(wk)
    return summ


# ── luck against skills (the buy-low / sell-high signal's check) ────────────

def luck_check(level: str, seasons: list[int]) -> dict:
    """How much of a gap between results and skills closes the next season: hitters' wOBA minus Savant's xwOBA against
    next season's wOBA change (300+ PA both seasons), pitchers' ERA-scale runs (RA9) minus our expected RA9 (xRA9) against
    next season's RA9 change (100+ IP both). Slope (-1: the gap closes fully; 0: it persists) and correlation."""
    cats = {}
    for s in seasons:
        h = an.read_json(an.data_root() / level / str(s) / "hitters.json") or {}
        p = an.read_json(an.data_root() / level / str(s) / "pitchers.json") or {}
        cats[s] = ({k: (v.get("pa"), v.get("values") or {}) for k, v in (h.get("players") or {}).items()},
                   {k: (v.get("bf"), v.get("values") or {}) for k, v in (p.get("players") or {}).items()})
    out = {}
    for kind, idx, gap_keys, val_key, need in (("H", 0, ("woba", "xwoba_savant"), "woba", 300), ("P", 1, ("ra9", "xra9"), "ra9", 430)):
        xs, ys = [], []
        for s in seasons:
            if s + 1 not in cats or s in (2020,) or s + 1 == 2020:
                continue
            a, b = cats[s][idx], cats[s + 1][idx]
            for pid, (n, v) in a.items():
                if (n or 0) < need or pid not in b or (b[pid][0] or 0) < need:
                    continue
                g1, g2 = v.get(gap_keys[0]), v.get(gap_keys[1])
                nxt = b[pid][1].get(val_key)
                if g1 is None or g2 is None or nxt is None:
                    continue
                xs.append(g1 - g2)
                ys.append(nxt - g1)
        if len(xs) >= 50:
            x, y = np.array(xs), np.array(ys)
            slope = float(((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum())
            out[kind] = {"n": len(xs), "slope": round(slope, 3), "corr": round(float(np.corrcoef(x, y)[0, 1]), 3),
                         "gap": f"{gap_keys[0]} - {gap_keys[1]}"}
    return out


# ── the payload ─────────────────────────────────────────────────────────────

H_FIELDS = ["pid", "name", "team", "elig", "age", "pa", "ab", "h", "b1", "d", "t", "hr", "r", "rbi", "sb", "cs", "bb", "hbp", "so", "avg",
            "pts", "z_r", "z_hr", "z_rbi", "z_sb", "z_avg", "val", "usd", "rank", "pos_rank", "tier", "dyn", "dyn_rank",
            "last", "last_rank", "skills", "il", "flags", "slot", "sb_att", "sb_succ", "sprint"]
P_FIELDS = ["pid", "name", "team", "role", "age", "ip", "outs", "gs", "g", "w", "l", "sv", "hld", "so", "h", "bb", "hbp", "er", "era",
            "whip", "pts", "z_w", "z_sv", "z_so", "z_era", "z_whip", "val", "usd", "rank", "pos_rank", "tier", "dyn", "dyn_rank",
            "last", "last_rank", "skills", "il", "flags", "sv_share", "hld_share"]
F_IDX = {"H": {f: i for i, f in enumerate(H_FIELDS)}, "P": {f: i for i, f in enumerate(P_FIELDS)}}
MOVE_KINDS = ("trade", "signing", "claim", "selected", "purchase", "rule5")
FA_KINDS = ("free_agency", "release")


def current_teams(parsed: list[dict], after: str) -> dict[str, str | None]:
    """The club each player has moved to since `after` (a trade, a major-league signing, a claim, a selection, a purchase,
    the Rule 5 draft), or None for one who elected free agency or was released and has not signed since."""
    out: dict[str, str | None] = {}
    for t in sorted(parsed, key=lambda t: (t.get("date") or "", t.get("id") or 0)):
        if not t.get("pid") or (t.get("date") or "") <= after:
            continue
        if t["kind"] in MOVE_KINDS and t.get("to"):
            out[t["pid"]] = t["to"]
        elif t["kind"] in FA_KINDS:
            out[t["pid"]] = None
    return out


def _r1(v, nd=1):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if np.isfinite(x) else None


def build(b, cfg: dict, vctx=None) -> dict | None:
    """Writes mlb/fantasy.json and mlb/fantasy_backtest.json; returns the backtest summary."""
    level = "mlb"
    today = cfg.get("today") or date.today()
    D = Data(level, statsapi=bool(cfg.get("statsapi")), today=today)
    if not D.lines:
        return None
    cur = max(D.lines)
    from oddsmarkets.baseball.models import season_sim as SS
    ph = SS.phase(D.stores.get(cur) or {})
    in_season = ph == "regular"
    T = cur if in_season else cur + 1
    parsed = vctx.parsed if vctx is not None else []
    # the club each player is with now: every move this season and since (a deadline trade, a signing after the season)
    moved = current_teams(parsed, f"{cur}-01-01") if (parsed and not in_season) else {}
    t0 = time.perf_counter()
    week = None
    if in_season:
        fits = fits_for(D, cur)
        weeks = D.weeks(cur)
        proj = ros_project(D, cur, today.isoformat(), fits, weeks)
        parks = (an.read_json(an.data_root() / level / str(cur) / "parks.json") or {}).get("parks") or {}
        throws = {pid: p.get("throws") for pid, p in ((D.stores.get(cur) or {}).get("players") or {}).items() if p.get("throws")}
        nxt = today - timedelta(days=today.weekday()) + timedelta(days=7)
        week = week_project(D, cur, nxt.isoformat(), fits, weeks, parks, True, throws)
    else:
        fits = fits_for(D, T)
        proj = project_next(D, T, moved, fits)
    if not proj:
        return None
    vrows = an.read_json(an.data_root() / level / str(cur) / "value.json") or {}
    VF = {f: i for i, f in enumerate(vrows.get("fields") or [])}
    vby = {(r[VF["kind"]], r[VF["pid"]]): r for r in vrows.get("rows") or []} if VF else {}
    cat_h = (an.read_json(an.data_root() / level / str(cur) / "hitters.json") or {}).get("players") or {}
    cat_p = (an.read_json(an.data_root() / level / str(cur) / "pitchers.json") or {}).get("players") or {}
    people = an.load_people()
    names: dict = {}
    for st in (D.stores.get(cur) or {}, D.stores.get(cur - 1) or {}):
        for pid, p in (st.get("players") or {}).items():
            names.setdefault(pid, p.get("name"))
    for pid, x in people.items():
        names.setdefault(pid, x.get("name"))

    def elig_h(pid):
        r = vby.get(("H", pid))
        if r is not None and "elig" in VF:
            e = list(r[VF["elig"]] or [])
            return F.eligible_slots(e or [r[VF["pos"]]], "H")
        return ["UT"]

    meta_all = proj.get("meta") or {}
    lines_h = {p: x for p, x in proj["H"].items() if x["pa"] >= 60}
    lines_p = {p: x for p, x in proj["P"].items() if x["ip"] >= 15}
    zh, sh = F.zvalues(lines_h, "H", F.N_HIT)
    zp, sp = F.zvalues(lines_p, "P", F.N_PIT)
    elig = {p: elig_h(p) for p in lines_h}
    lvl_h, _ = F.replacement({p: zh[p]["total"] for p in lines_h}, elig)
    var_h = {p: zh[p]["total"] - min(lvl_h.get(s, 0.0) for s in elig[p]) for p in lines_h}
    ranked_p = sorted(lines_p, key=lambda p: -zp[p]["total"])
    rep_p = zp[ranked_p[F.N_PIT]]["total"] if len(ranked_p) > F.N_PIT else 0.0
    var_p = {p: zp[p]["total"] - rep_p for p in lines_p}
    usd_h = F.dollars(var_h, F.N_HIT, 0.67)
    usd_p = F.dollars(var_p, F.N_PIT, 0.33)
    # last season's lines and values: the naive ranking our picks are judged against
    last_h = {p: F.actual_line(x, "H") for p, x in ((D.lines.get(cur) or {}).get("hitting") or {}).items() if (x.get("pa") or 0) >= 60}
    last_p = {p: F.actual_line(x, "P") for p, x in ((D.lines.get(cur) or {}).get("pitching") or {}).items() if (x.get("outs") or 0) >= 45}
    lzh, _ = F.zvalues(last_h, "H", F.N_HIT)
    lzp, _ = F.zvalues(last_p, "P", F.N_PIT)
    lall = sorted([(lzh[p]["total"], "H", p) for p in last_h] + [(lzp[p]["total"], "P", p) for p in last_p], key=lambda t: -t[0])
    lrank = {(k, p): i + 1 for i, (_, k, p) in enumerate(lall)}
    allv = sorted([("H", p, var_h[p]) for p in lines_h] + [("P", p, var_p[p]) for p in lines_p], key=lambda x: -x[2])
    rank = {(k, p): i + 1 for i, (k, p, _) in enumerate(allv)}

    def mult(kind, pid, age):
        r = vby.get((kind, pid))
        if r is not None and "v5" in VF and r[VF["e1"]] is not None and r[VF["e1"]] >= 0.5 and r[VF["v5"]] is not None:
            return max(min(r[VF["v5"]] / r[VF["e1"]], 4.6), 0.3)
        a = float(age or 28)
        return 4.0 if a < 26 else 3.4 if a < 30 else 2.6 if a < 33 else 1.6
    dyn = {(k, p): max(v, 0.0) * mult(k, p, (meta_all.get(f"{k}:{p}") or {}).get("age")) for k, p, v in allv}
    aaa = an.read_json(an.data_root() / "aaa" / str(cur) / "value.json") or {}
    AF = {f: i for i, f in enumerate(aaa.get("fields") or [])}
    prospects = []
    c_war = None
    if "p_value" in AF:
        xs, ys = [], []
        for (k, p) in dyn:
            r = vby.get((k, p))
            if r is not None and "e1" in VF and r[VF["e1"]] is not None and r[VF["e1"]] > 0.5:
                xs.append(r[VF["e1"]])
                ys.append(var_h.get(p) if k == "H" else var_p.get(p))
        c_war = float(np.dot(xs, ys) / max(np.dot(xs, xs), 1e-9)) if xs else 1.0
        for r in aaa.get("rows") or []:
            pv = r[AF["p_value"]]
            if pv is None or (r[AF["kind"]], r[AF["pid"]]) in dyn:
                continue
            prospects.append([r[AF["pid"]], r[AF["name"]], r[AF["team"]], r[AF["kind"]], r[AF["pos"]], r[AF["age"]], r[AF["p_level"]],
                              r[AF["p_z"]], pv, round(c_war * pv, 2)])
        prospects.sort(key=lambda x: -x[8])
        prospects = prospects[:150]
    dyn_all = sorted([(v, k, p) for (k, p), v in dyn.items()] + [(x[9], "X", x[0]) for x in prospects], key=lambda t: -t[0])
    dyn_rank = {(k, p): i + 1 for i, (v, k, p) in enumerate(dyn_all)}
    for x in prospects:
        x.append(dyn_rank.get(("X", x[0])))
    il_now = {}
    if vctx is not None:
        from oddsmarkets.baseball.analytics import moves as M
        il_now = M.on_il(vctx.stints, today)
    out: dict[str, list] = {"H": [], "P": []}
    for kind, lines, Z, var, usd, last in (("H", lines_h, zh, var_h, usd_h, last_h), ("P", lines_p, zp, var_p, usd_p, last_p)):
        pos_of = {p: (elig[p][0] if kind == "H" else ((meta_all.get(f"P:{p}") or {}).get("role") or
                                                       ("SP" if lines[p]["gs"] >= 0.5 * max(lines[p]["g"], 1) else "RP"))) for p in lines}
        groups: dict[str, list] = defaultdict(list)
        for p in lines:
            groups[pos_of[p]].append(p)
        pos_rank, tier = {}, {}
        for pos, lst in groups.items():
            lst.sort(key=lambda p: -var[p])
            for i, p in enumerate(lst):
                pos_rank[p] = i + 1
            top = lst[:60]
            for p, t in zip(top, F.tiers([var[p] for p in top], 6)):
                tier[p] = t
        rows = []
        for p, x in lines.items():
            m = meta_all.get(f"{kind}:{p}") or {}
            vr = vby.get((kind, p))
            la = last.get(p)
            il = None
            if vr is not None and "il_exp" in VF:
                il3 = vr[VF["il3"]] or []
                il = [vr[VF["il_exp"]], vr[VF["il_p30"]], il3[-1] if il3 else None, None, None]
            if p in il_now:
                il = (il or [None, None, None, None, None])[:3] + [il_now[p].get("il"), il_now[p].get("part")]
            cat = (cat_h if kind == "H" else cat_p).get(p) or {}
            v = cat.get("values") or {}
            if kind == "H":
                skills = [v.get("xwoba_plus"), v.get("woba"), v.get("xwoba_savant"), v.get("barrel_pct"), v.get("bat_speed_adj") or v.get("bat_speed"),
                          v.get("sprint_speed"), v.get("k_pct"), v.get("babip")]
            else:
                skills = [v.get("stuff_plus"), v.get("pitching_plus"), v.get("ra9"), v.get("xra9"), v.get("fip"), v.get("k_pct"), v.get("csw_pct"),
                          v.get("babip_against")]
            flags = _flags(kind, x, la, skills, rank.get((kind, p)), lrank.get((kind, p)), m.get("age"), il)
            z = Z[p]["z"]
            if la:
                core = ([round(la["r"]), round(la["hr"]), round(la["rbi"]), round(la["sb"]), round(la["avg"], 3)] if kind == "H" else
                        [round(la["w"]), round(la["sv"]), round(la["so"]), round(la["era"], 2), round(la["whip"], 2)])
                last_out = [round(la["pa"] if kind == "H" else la["ip"])] + core + [round(F.points(la, kind))]
            else:
                last_out = None
            team = m.get("team")
            common_tail = [round(var[p], 2), round(usd[p]), rank.get((kind, p)), pos_rank.get(p), tier.get(p), round(dyn[(kind, p)], 2),
                           dyn_rank.get((kind, p)), last_out, lrank.get((kind, p)), skills, il, flags]
            if kind == "H":
                rows.append([p, names.get(p), team, elig[p], _r1(m.get("age")), round(x["pa"]), round(x["ab"]), _r1(x["h"]), _r1(x["b1"]), _r1(x["d"]),
                             _r1(x["t"]), _r1(x["hr"]), _r1(x["r"]), _r1(x["rbi"]), _r1(x["sb"]), _r1(x["cs"]), _r1(x["bb"]), _r1(x["hbp"]), _r1(x["so"]),
                             round(x["avg"], 3), round(F.points(x, "H")), *[round(z[c], 2) for c in F.HIT_CATS], *common_tail,
                             m.get("slot"), _r1(m.get("sb_att"), 3), _r1(m.get("sb_succ"), 3), _r1(m.get("sprint"))])
            else:
                rows.append([p, names.get(p), team, pos_of[p], _r1(m.get("age")), _r1(x["ip"]), round(x["outs"]), _r1(x["gs"]), _r1(x["g"]), _r1(x["w"]),
                             _r1(x["l"]), _r1(x["sv"]), _r1(x["hld"]), _r1(x["so"]), _r1(x["h"]), _r1(x["bb"]), _r1(x["hbp"]), _r1(x["er"]),
                             round(x["era"], 2), round(x["whip"], 3), round(F.points(x, "P")), *[round(z[c], 2) for c in F.PIT_CATS], *common_tail,
                             m.get("sv_share"), m.get("hld_share")])
        rows.sort(key=lambda r: r[F_IDX[kind]["rank"]] or 9999)
        out[kind] = rows
    I = F_IDX["P"]
    closers: dict[str, list] = defaultdict(list)
    for r in out["P"]:
        if r[I["role"]] == "RP" and r[I["team"]]:
            closers[r[I["team"]]].append([r[0], r[I["sv"]], r[I["hld"]], r[I["era"]], r[I["so"]], r[I["sv_share"]], r[I["hld_share"]]])
    for t in closers:
        closers[t].sort(key=lambda x: (-(x[1] or 0), -(x[2] or 0)))
        closers[t] = closers[t][:4]
    J = F_IDX["H"]
    steals = sorted(out["H"], key=lambda r: -(r[J["sb"]] or 0))[:60]
    steals = [[r[0], r[J["sb"]], r[J["sb_att"]], r[J["sb_succ"]], r[J["sprint"]], r[J["pa"]], r[J["last"]][4] if r[J["last"]] else None]
              for r in steals]
    upside = [r for r in out["H"] if r[J["sprint"]] and r[J["sprint"]] >= 28.5 and (r[J["sb_att"]] or 0) < 0.08 and r[J["pa"]] >= 300]
    upside = [[r[0], r[J["sb"]], r[J["sb_att"]], r[J["sprint"]], r[J["pa"]]] for r in sorted(upside, key=lambda r: -(r[J["sprint"]] or 0))[:25]]
    two, stream = [], []
    if in_season and week:
        top150 = {r[0] for r in out["P"] if (r[I["rank"]] or 9999) <= 150}
        for p, st_ in (week.get("starts") or {}).items():
            ln = week["P"].get(p)
            if not ln or not st_:
                continue
            item = [p, names.get(p), len(st_), st_, round(F.points(ln, "P"), 1), _r1(ln["so"]), round(ln["era"], 2), _r1(ln["w"], 2)]
            if len(st_) >= 2:
                two.append(item)
            if p not in top150:
                stream.append(item)
        two.sort(key=lambda x: -x[4])
        stream.sort(key=lambda x: -x[4])
        stream = stream[:30]
    week_h = []
    if in_season and week:
        week_h = sorted([[p, names.get(p), round(F.points(x, "H"), 1), _r1(x["pa"]), _r1(x["hr"]), _r1(x["r"]), _r1(x["rbi"]), _r1(x["sb"])]
                         for p, x in week["H"].items()], key=lambda r: -r[2])[:150]
    picks = _picks(out)
    teams_info = {t: {k: (x or {}).get(k) for k in ("name", "abbr", "short")} for t, x in ((D.stores.get(cur) or {}).get("teams") or {}).items()
                  if not (x or {}).get("placeholder")}
    pay = {"ok": True, "level": level, "updated_at": an.now(), "season": cur, "target": T, "phase": ph, "in_season": in_season,
           "mode": "rest of season" if in_season else f"{T} draft", "h_fields": H_FIELDS, "p_fields": P_FIELDS, "hitters": out["H"],
           "pitchers": out["P"], "prospects": prospects,
           "prospect_fields": ["pid", "name", "team", "kind", "pos", "age", "level", "z", "p_value", "dyn", "dyn_rank"],
           "war_to_value": _r1(c_war, 3), "closers": dict(closers), "closer_fields": ["pid", "sv", "hld", "era", "so", "sv_share", "hld_share"],
           "steals": steals, "steal_fields": ["pid", "sb", "att", "succ", "sprint", "pa", "sb_last"], "sb_upside": upside,
           "two_start": two, "streaming": stream, "start_fields": ["pid", "name", "starts", "games", "pts", "so", "era", "w"],
           "week_hitters": week_h, "week_fields": ["pid", "name", "pts", "pa", "hr", "r", "rbi", "sb"], "picks": picks, "teams": teams_info,
           "points": F.POINTS, "league": {"teams": F.TEAMS, "roster": F.ROSTER, "pitchers": 9, "budget": F.BUDGET,
                                          "replacement": {**{k: round(v, 2) for k, v in lvl_h.items()}, "P": round(rep_p, 2)}},
           "skills_fields": {"H": ["xwOBA+", "wOBA", "xwOBA (Savant)", "Barrel%", "Bat speed", "Sprint speed", "K%", "BABIP"],
                             "P": ["Stuff+", "Pitching+", "RA9", "xRA9", "FIP", "K%", "CSW%", "BABIP against"]},
           "il_fields": ["expected days next season", "chance of 30+", "days last season", "list now", "body part"],
           "fits": {"context": fits["ctx"], "time": fits["time"], "roles": fits["roles"]}, "notes": _notes(in_season, T)}
    b.write(f"{level}/fantasy.json", an.clean(pay))
    log.info("fantasy payload: %.1f s", time.perf_counter() - t0)
    bt = backtests(D, cur)
    summ = summarize(bt)
    luck = luck_check(level, sorted(D.lines))
    b.write(f"{level}/fantasy_backtest.json", an.clean({
        "ok": True, "level": level, "updated_at": an.now(), "by_season": bt, "summary": summ, "luck": luck, "version": VERSION,
        "notes": ["Season (draft): our projection made after the season before against the official line, on players who "
                  "qualified the season before (300 PA; 50 IP); a player who did not play counts with an empty line. The naive "
                  "forecast is his line of the season before (2020 scaled to 162 games). Mean absolute errors (AVG, ERA, WHIP "
                  "weighted by at-bats and innings) and the rank correlation of points and of 5x5 value.",
                  "Rest of season: from the Monday on or after 1 June, 1 July and 1 August (2022 on) against the official lines "
                  "after it, players with 100 PA (20 IP) to date and 50 PA (10 IP) after; the naive forecast is the season-to-date "
                  "pace.",
                  "Next week: every week from the fourth (2022 on), regular hitters (100+ PA) and pitchers with a probable start "
                  "or 15+ relief games; the naive forecast is the season-to-date points per club game (per start for starters). "
                  "nomatch is the same projection without the platoon and park adjustments.",
                  "Luck: the next season's change against this season's gap between results and expected results (a slope of -1 "
                  "means the gap closes fully, 0 that it persists)."]}))
    return summ


def _flags(kind: str, x: dict, last: dict | None, skills: list, rank, lrank, age, il) -> list[str]:
    """Short reasons for the picks: results against skills, playing time, injuries, age, the move against last season."""
    f = []
    if kind == "H":
        woba, xw = skills[1], skills[2]
        if woba is not None and xw is not None:
            if xw - woba >= 0.025:
                f.append("unlucky: xwOBA {:.3f} v wOBA {:.3f}".format(xw, woba))
            elif woba - xw >= 0.025:
                f.append("lucky: wOBA {:.3f} v xwOBA {:.3f}".format(woba, xw))
        if last and last.get("pa", 0) < 400 and x["pa"] >= 500:
            f.append("more playing time")
    else:
        ra9, xra9 = skills[2], skills[3]
        if ra9 is not None and xra9 is not None:
            if ra9 - xra9 >= 0.6:
                f.append("unlucky: RA9 {:.2f} v xRA9 {:.2f}".format(ra9, xra9))
            elif xra9 - ra9 >= 0.6:
                f.append("lucky: RA9 {:.2f} v xRA9 {:.2f}".format(ra9, xra9))
        if skills[0] is not None and skills[0] >= 110:
            f.append(f"Stuff+ {skills[0]}")
    if age is not None and age < 25:
        f.append("young")
    if il and il[1] is not None and il[1] >= 0.4:
        f.append(f"injury risk {int(round(100 * il[1]))}%")
    if rank and lrank:
        if lrank - rank >= 60:
            f.append("rises v last season")
        elif rank - lrank >= 60:
            f.append("falls v last season")
    return f


def _picks(out: dict) -> dict:
    """Our picks: sleepers (in our top 150 and at least 60 places better than last season's value rank, or new), fades
    (in last season's top 100 and at least 60 places worse in ours), young risers (25 or younger, in our top 200, better
    than last season), each with its reasons."""
    picks: dict[str, list] = {"sleepers": [], "fades": [], "young": []}
    for kind in ("H", "P"):
        I = F_IDX[kind]
        for r in out[kind]:
            rk, lr = r[I["rank"]], r[I["last_rank"]]
            if rk is None:
                continue
            item = [kind, r[0], rk, lr, r[I["flags"]]]
            if rk <= 150 and (lr is None or lr - rk >= 60):
                picks["sleepers"].append(item)
            if lr is not None and lr <= 100 and rk - lr >= 60:
                picks["fades"].append(item)
            if r[I["age"]] is not None and r[I["age"]] <= 25.5 and rk <= 200 and (lr is None or lr > rk):
                picks["young"].append(item)
    for k in picks:
        picks[k].sort(key=lambda x: x[2])
        picks[k] = picks[k][:25]
    return picks


def _notes(in_season: bool, T: int) -> list[str]:
    first = (("In season: rest-of-season lines from the component projections with the season to date folded in, over each "
              "club's games left; next week from the probable starters, the club's games, lineup slots, the opposing starter's "
              "hand and the park.") if in_season else
             (f"Between seasons: {T} draft projections from the seasons before, aged; playing time from the last two seasons and "
              "age; clubs from the transactions of the season and since (a free agent is projected with a league-average club)."))
    return [first,
            "5x5 values: z-scores over a 12-team mixed league's pool (C, 1B, 2B, 3B, SS, CI, MI, 5 OF, UT; 9 P), AVG, ERA and WHIP "
            "weighted by at-bats and innings, minus the replacement level of the player's best position; dollars on a $260 "
            "budget (67% hitters).",
            "Positions: 20 games at a position last season (or his most); outfield spots count as OF.",
            "Points: our default scheme, editable on the page; the projections carry every counting stat it uses.",
            "Dynasty: this season's value above replacement times the player's five-season multiplier from valuation v2 "
            "(expected WAR over five seasons, discounted, against next season's), plus the best prospects from the minor-league "
            "model.",
            "No ADP, ownership or platform rankings: their terms do not allow our use. Rises and falls are against last season's "
            "value rank; streaming starters are those outside our top 150 (a proxy for availability)."]
