"""
Who moves next on The Quant Campus (cfb, mbb, wbb): each rostered player's chance of leaving his team before next
season, split into an inferred transfer (the same ESPN athlete id on another Division I / FBS team next season) and
leaving the data (graduation, the pros, a lower division: absent from next season's rosters and box scores); each
team's outlook by position; and its targets among likely movers.

Inferred from rosters and box scores, not the official transfer portal (whose public lists carry 247Sports ratings,
which may not be republished). No class or eligibility history exists in the stores (only the current season's
rosters carry a class), so experience is the number of earlier seasons with a box-score line.

The model is a preseason one: for season S it uses what is known when S begins (S's roster, S-1's box scores, the
team's turnover into S), so the same model serves every level at any point of a season. Row = a player on a member
team's roster in season S (or in its box scores); label = where he is in S+1.

    features   experience (0, 1, 2, 3, 4+ earlier seasons in the box scores), last season: his team, share of the team's
               minutes (basketball) or games (football), starts, production rank in his team and percentile by position;
               new to the team (a transfer in, or no line last season); the team's scoring margin last season and its
               change, its conference's margin, the share of its roster that left before this season, roster size and
               depth at his position; the level's turnover into this season; the transfer era (2021 on); his position.
    models     ridge logistic for "leaves", ridge logistic for "transfer, given he leaves"; destination team: a
               conditional logit over member teams (margin step, conference strength step, same conference, his
               production x the team's margin, the team's expected departures at his position).

Validation (walk-forward, pre-registered in docs/research/college_moves.md): each test season's transition is
predicted by a model fitted on earlier transitions only.
"""
from __future__ import annotations

import logging
import math
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

from oddsmarkets.college import canon
from oddsmarkets.college import store as ST

logger = logging.getLogger(__name__)

FIRST_ROSTER_SEASON = 2014          # full rosters from 2014 (earlier: box-score players only)
FIRST_BOX_SEASON = 2004
PORTAL_ERA = 2021                   # the one-time transfer exception (April 2021) and the portal's growth
FEATURES = ("exp0", "exp1", "exp2", "exp3", "exp4", "share", "starts", "rank", "pctl", "new_in",
            "no_prev", "margin", "margin_chg", "conf_margin", "team_out", "team_n", "depth",
            "pos1", "pos2", "pos3", "pos4", "pos5", "pos6")
CHOICE = ("m_diff", "m_diff2", "c_diff", "c_diff2", "same_conf", "pctl_x_margin", "need", "need_all", "portal_use")
# Football positions are inferred from the box score in every season (the past stores carry no roster position):
# WR includes tight ends; offensive linemen never have a box-score line.
POS_GROUPS = {"cfb": ("QB", "RB", "WR", "DL", "LB", "DB", "K"), "mbb": ("G", "F", "C"), "wbb": ("G", "F", "C")}
TARGETS_PER_TEAM = 10
CACHE_VERSION = 3


# ── one season, compact ──────────────────────────────────────────────────────

def _cache_dir() -> Path:
    p = ST.paths()["cache"] / "movement"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pos_cfb(row: dict | None) -> str:
    """The position group from a season's box line (the same rule every season; rosters carry no past positions)."""
    r = row or {}
    off = r.get("pass", 0) + r.get("rush", 0) + r.get("rec", 0)
    if r.get("kick", 0) > 0 and off == 0 and r.get("defp", 0) < 3:
        return "K"
    if r.get("pass", 0) > 0 and r.get("pass", 0) >= r.get("rush", 0):
        return "QB"
    if off > 0 and off >= r.get("defp", 0):
        return "RB" if r.get("rush", 0) > r.get("rec", 0) else "WR"
    if r.get("pd", 0) > max(r.get("sacks", 0), 0) or r.get("int", 0) > 0:
        return "DB"
    if r.get("sacks", 0) + r.get("tfl", 0) >= 0.25 * max(r.get("tkl", 0), 1):
        return "DL"
    return "LB"


def season_info(level: str, s: int) -> dict | None:
    """
    {teams: {tid: conf}, roster: {pid: tid}, box: {pid: {team, gp, share, starts, prod}}, pos: {pid: group},
     margin: {tid}, cls: {pid: class}} for one season, cached on the store file's size and mtime.
    """
    path = ST.store_path(level, s)
    if not path.exists():
        return None
    stt = path.stat()
    cp = _cache_dir() / f"{level}_{s}.pkl"
    key = (CACHE_VERSION, stt.st_size, int(stt.st_mtime))
    if cp.exists():
        try:
            k, v = pickle.loads(cp.read_bytes())
            if k == key:
                return v
        except Exception:  # noqa: BLE001 - a stale or broken cache is rebuilt
            pass
    st = ST.load(level, s)
    teams = {str(t): (v or {}).get("conference") for t, v in (st.get("teams") or {}).items() if (v or {}).get("member")}
    roster = {}
    for t, pids in (st.get("rosters") or {}).items():
        if str(t) in teams:
            for p in pids or []:
                roster[str(p)] = str(t)
    players = st.get("players") or {}
    # Scoring margins (every final with a member team) and the box scores.
    mg: dict[str, list[float]] = defaultdict(list)
    team_games: dict[str, int] = defaultdict(int)
    acc: dict[tuple[str, str], dict] = {}
    team_tot: dict[str, float] = defaultdict(float)
    football = canon.is_football(level)
    for g in (st.get("games") or {}).values():
        if g.get("status") != "post" or g.get("hs") is None or g.get("as") is None:
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        for t, o, d in ((h, a, g["hs"] - g["as"]), (a, h, g["as"] - g["hs"])):
            if t in teams:
                mg[t].append(float(d))
        box = g.get("box") or {}
        for t, b in box.items():
            t = str(t)
            if t not in teams:
                continue
            team_games[t] += 1
            if football:
                per: dict[str, dict] = {}
                for cat, block in ((b or {}).get("players") or {}).items():
                    cols = block.get("cols") or []
                    for r in block.get("rows") or []:
                        if not r or not str(r[0]).lstrip("-").isdigit() or str(r[0]).startswith("-"):
                            continue
                        d = per.setdefault(str(r[0]), {})
                        for j, c in enumerate(cols):
                            v = r[j + 1] if j + 1 < len(r) else None
                            if not isinstance(v, (int, float)) or not math.isfinite(v):
                                continue
                            if cat == "passing" and c == "passing_yards":
                                d["pass"] = d.get("pass", 0) + v
                            elif cat == "rushing" and c == "rushing_yards":
                                d["rush"] = d.get("rush", 0) + v
                            elif cat == "receiving" and c == "receiving_yards":
                                d["rec"] = d.get("rec", 0) + v
                            elif cat == "defensive" and c in ("total_tackles", "tackles_for_loss", "sacks", "passes_defended"):
                                w = {"total_tackles": 1.0, "tackles_for_loss": 2.0, "sacks": 3.0, "passes_defended": 2.0}[c]
                                d["defp"] = d.get("defp", 0) + w * v
                                k_ = {"total_tackles": "tkl", "tackles_for_loss": "tfl", "sacks": "sacks", "passes_defended": "pd"}[c]
                                d[k_] = d.get(k_, 0) + v
                            elif cat == "interceptions" and c == "interceptions":
                                d["defp"] = d.get("defp", 0) + 4.0 * v
                                d["int"] = d.get("int", 0) + v
                            elif cat == "kicking" and c == "fgm":
                                d["kick"] = d.get("kick", 0) + v
                            elif cat == "punting" and c == "punts":
                                d["kick"] = d.get("kick", 0) + 0.3 * v
                for p, d in per.items():
                    prod = d.get("pass", 0) / 25.0 + d.get("rush", 0) / 10.0 + d.get("rec", 0) / 10.0 + d.get("defp", 0) + 3.0 * d.get("kick", 0)
                    x = acc.setdefault((p, t), {"gp": 0, "min": 0.0, "starts": 0, "prod": 0.0, "pass": 0, "rush": 0, "rec": 0,
                                                "defp": 0, "pd": 0, "sacks": 0, "tkl": 0, "tfl": 0, "int": 0, "kick": 0})
                    x["gp"] += 1
                    x["prod"] += prod
                    for k in ("pass", "rush", "rec", "defp", "pd", "sacks", "tkl", "tfl", "int", "kick"):
                        x[k] += d.get(k, 0)
            else:
                for r in (b or {}).get("players") or []:
                    try:
                        sec = float(r[2] or 0)
                        stats = [float(x or 0) for x in r[3:17]]
                    except (TypeError, ValueError, IndexError):
                        continue
                    if sec <= 0:
                        continue
                    pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf = stats
                    gs = pts + 0.4 * fgm - 0.7 * fga - 0.4 * (fta - ftm) + 0.7 * oreb + 0.3 * dreb + stl + 0.7 * ast + 0.7 * blk - 0.4 * pf - tov
                    x = acc.setdefault((str(r[0]), t), {"gp": 0, "min": 0.0, "starts": 0, "prod": 0.0})
                    x["gp"] += 1
                    x["min"] += sec / 60.0
                    x["starts"] += 1 if r[1] else 0
                    x["prod"] += gs
                    team_tot[t] += sec / 60.0
    by_p: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (p, t), x in acc.items():
        by_p[p].append((t, x))
    box = {}
    for p, lst in by_p.items():
        lst.sort(key=lambda kv: -(kv[1]["min"] if not football else kv[1]["gp"]))
        t, x = lst[0]
        n_g = max(team_games.get(t, 0), 1)
        if football:
            share = x["gp"] / n_g
            rate = x["prod"] / max(x["gp"], 1)
        else:
            share = x["min"] / max(team_tot.get(t, 0) / 5.0, 1.0)
            rate = 40.0 * (x["prod"] + 0.0) / max(x["min"] + 60.0, 1.0)      # game score per 40, shrunk by 60 minutes
        box[p] = {"team": t, "gp": x["gp"], "share": min(share, 1.0), "starts": x["starts"] / max(x["gp"], 1),
                  "rate": rate, "row": {k: v for k, v in x.items() if k in ("pass", "rush", "rec", "defp", "pd", "sacks", "tkl",
                                                                              "tfl", "int", "kick")}}
    pos = {}
    for p in set(roster) | set(box):
        pi = players.get(p)
        if football:
            pos[p] = _pos_cfb((box.get(p) or {}).get("row"))
        else:
            pp = canon.pool(level, (pi or {}).get("pos")) or (pi or {}).get("pool")
            pos[p] = pp if pp in ("G", "F", "C") else "F"
    for b in box.values():
        b.pop("row", None)
    cls = {p: (players.get(p) or {}).get("class") for p in roster if (players.get(p) or {}).get("class")}
    rpos = {p: canon.pool(level, (players.get(p) or {}).get("pos")) for p in roster if (players.get(p) or {}).get("pos")}
    names = {p: (players.get(p) or {}).get("name") for p in set(roster) | set(box)}
    out = {"teams": teams, "roster": roster, "box": box, "pos": pos, "cls": cls, "names": names, "rpos": rpos,
           "margin": {t: float(np.mean(v)) for t, v in mg.items() if v}, "team_names": {t: (st.get("teams") or {}).get(t, {}).get("short")
                                                                                       or (st.get("teams") or {}).get(t, {}).get("name") for t in teams},
           "n_box_games": sum(team_games.values()) // 2}
    try:
        cp.write_bytes(pickle.dumps((key, out)))
    except OSError:
        pass
    return out


def complete(nxt: dict, cur: dict) -> bool:
    """A season's box scores are complete enough to label the season before: 90% of its games."""
    return nxt["n_box_games"] >= 0.9 * max(cur["n_box_games"], 1)


def where(info: dict, p: str) -> str | None:
    """A player's team in a season: the box-score primary team, else the roster's."""
    b = info["box"].get(p)
    if b:
        return b["team"]
    return info["roster"].get(p)


# ── the panel ────────────────────────────────────────────────────────────────

@dataclass
class Panel:
    level: str
    season: int
    pid: list[str]
    tid: list[str]
    pos: list[str]
    X: np.ndarray
    y: np.ndarray | None = None               # 1 leaves the team before S+1
    typ: np.ndarray | None = None             # 1 transfer, 0 gone (leavers only meaningful)
    dest: list[str | None] = field(default_factory=list)
    info: dict[str, np.ndarray] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.pid)


def _pctl_by_group(vals: dict[str, float], group: dict[str, str]) -> dict[str, float]:
    by: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for p, v in vals.items():
        by[group.get(p, "")].append((p, v))
    out = {}
    for g, lst in by.items():
        xs = np.sort(np.array([v for _, v in lst]))
        for p, v in lst:
            out[p] = float(np.searchsorted(xs, v, side="right")) / max(xs.size, 1)
    return out


def build_panel(level: str, s: int, infos: dict[int, dict], labels: bool = True) -> Panel | None:
    """
    The rows of season s: every player with a box-score line for a member team (his primary team), with what is known
    at the end of s (or so far in s), and, with labels, where he is in s+1 (box scores first, then rosters).
    """
    cur, prev = infos.get(s), infos.get(s - 1)
    if cur is None or prev is None or not cur["box"]:
        return None
    nxt = infos.get(s + 1) if labels else None
    if labels and (nxt is None or not complete(nxt, cur)):
        return None
    groups = POS_GROUPS[level]
    exp: dict[str, int] = defaultdict(int)
    for ss, inf in infos.items():
        if ss < s and inf is not None:
            for p in inf["box"]:
                exp[p] += 1
    rate = {p: b["rate"] for p, b in cur["box"].items()}
    pct = _pctl_by_group(rate, cur["pos"])
    rank: dict[str, float] = {}
    by_team: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for p, b in cur["box"].items():
        by_team[b["team"]].append((p, b["rate"] * b["share"]))
    for t, lst in by_team.items():
        lst.sort(key=lambda kv: -kv[1])
        for k, (p, _) in enumerate(lst):
            rank[p] = k / max(len(lst) - 1, 1)
    # Team turnover into s: the share of last season's players (box) who did not play for the team in s.
    cnt: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p, b in prev["box"].items():
        cnt[b["team"]][0] += 1
        if (cur["box"].get(p) or {}).get("team") != b["team"]:
            cnt[b["team"]][1] += 1
    out_rate = {t: c[1] / c[0] for t, c in cnt.items() if c[0] >= 5}
    level_out = float(np.mean(list(out_rate.values()))) if out_rate else 0.4
    lm = float(np.mean(list(cur["margin"].values()))) if cur["margin"] else 0.0
    conf_m: dict[Any, list[float]] = defaultdict(list)
    for t, c in cur["teams"].items():
        if t in cur["margin"]:
            conf_m[c].append(cur["margin"][t])
    conf_mean = {c: float(np.mean(v)) for c, v in conf_m.items()}
    n_team: dict[str, int] = defaultdict(int)
    depth_n: dict[tuple[str, str], int] = defaultdict(int)
    for p, b in cur["box"].items():
        n_team[b["team"]] += 1
        depth_n[(b["team"], cur["pos"].get(p, ""))] += 1
    rows, pids, tids, poss, ys, typs, dests = [], [], [], [], [], [], []
    info: dict[str, list] = {k: [] for k in ("exp", "share", "rate", "pctl", "new_in", "cls")}
    for p in sorted(cur["box"]):
        b = cur["box"][p]
        t = b["team"]
        if t not in cur["teams"]:
            continue
        pb = prev["box"].get(p)
        e = min(exp.get(p, 0), 4)
        g = cur["pos"].get(p) or groups[0]
        new_in = 1.0 if (pb is not None and pb["team"] != t) else 0.0
        m = cur["margin"].get(t, lm)
        m0 = prev["margin"].get(t, m)
        c = cur["teams"].get(t)
        row = [float(e == 0), float(e == 1), float(e == 2), float(e == 3), float(e >= 4),
               b["share"], b["starts"], rank.get(p, 1.0), pct.get(p, 0.5), new_in, 1.0 if pb is None else 0.0,
               m - lm, m - m0, conf_mean.get(c, lm) - lm, out_rate.get(t, level_out), n_team[t] / 10.0,
               depth_n[(t, g)] / 5.0]
        row += [float(g == x) for x in groups[1:7]] + [0.0] * (6 - len(groups[1:7]))
        rows.append(row)
        pids.append(p)
        tids.append(t)
        poss.append(g)
        info["exp"].append(e)
        info["share"].append(b["share"])
        info["rate"].append(b["rate"])
        info["pctl"].append(pct.get(p, 0.5))
        info["new_in"].append(new_in)
        info["cls"].append(cur["cls"].get(p))
        if labels:
            t1 = (nxt["box"].get(p) or {}).get("team")
            if t1 == t:
                ys.append(0)
                typs.append(-1)
                dests.append(None)
            elif t1 is not None and t1 in nxt["teams"]:
                ys.append(1)
                typs.append(1)
                dests.append(t1)
            else:
                ys.append(1)
                typs.append(0)
                dests.append(None)
    if not rows:
        return None
    return Panel(level, s, pids, tids, poss, np.array(rows, dtype=float),
                 np.array(ys, dtype=float) if labels else None, np.array(typs) if labels else None, dests,
                 {k: np.array(v, dtype=object if k == "cls" else float) for k, v in info.items()})


# ── models ───────────────────────────────────────────────────────────────────

@dataclass
class Logit:
    lam: float
    mean: np.ndarray
    sd: np.ndarray
    coef: np.ndarray
    intercept: float

    def predict(self, X: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-(((X - self.mean) / self.sd) @ self.coef + self.intercept)))

    def to_json(self, cols) -> dict:
        return {"cols": list(cols), "lam": self.lam, "coef": [round(float(x), 5) for x in self.coef],
                "mean": [round(float(x), 5) for x in self.mean], "sd": [round(float(x), 5) for x in self.sd],
                "intercept": round(float(self.intercept), 5)}


def fit_logit(X: np.ndarray, y: np.ndarray, lam: float, w: np.ndarray | None = None) -> Logit:
    m = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd < 1e-9] = 1.0
    Z = (X - m) / sd
    n, k = Z.shape
    w = np.ones(n) if w is None else w
    W = w.sum()

    def f(th):
        b, c = th[:k], th[k]
        z = Z @ b + c
        p = 1.0 / (1.0 + np.exp(-z))
        return (np.sum(w * (np.logaddexp(0, z) - y * z)) + 0.5 * lam * b @ b) / W, \
            np.r_[(Z.T @ (w * (p - y)) + lam * b) / W, np.sum(w * (p - y)) / W]

    p0 = min(max(float(np.average(y, weights=w)), 1e-4), 1 - 1e-4)
    r = minimize(f, np.r_[np.zeros(k), math.log(p0 / (1 - p0))], jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return Logit(lam, m, sd, r.x[:k], float(r.x[k]))


@dataclass
class SeasonLogit:
    """
    Ridge logistic with one intercept per training season (the level moves year to year: the transfer portal), recent
    seasons weighted more (half-life in seasons); a new season is predicted at the latest season's level.
    """
    base: Logit
    seasons: list[int]
    half_life: float

    def predict(self, X: np.ndarray) -> np.ndarray:
        D = np.zeros((X.shape[0], len(self.seasons)))
        D[:, -1] = 1.0
        return self.base.predict(np.hstack([X, D]))

    def to_json(self, cols) -> dict:
        return {**self.base.to_json(list(cols) + [f"season_{x}" for x in self.seasons]), "half_life": self.half_life}


def fit_season_logit(X: np.ndarray, y: np.ndarray, season: np.ndarray, lam: float, half_life: float = 1e9) -> SeasonLogit:
    ss = sorted(set(int(x) for x in season.tolist()))
    D = np.zeros((X.shape[0], len(ss)))
    for k, x in enumerate(ss):
        D[season == x, k] = 1.0
    w = 0.5 ** ((max(ss) - season) / half_life)
    return SeasonLogit(fit_logit(np.hstack([X, D]), y, lam, w), ss, half_life)


@dataclass
class CLogit:
    lam: float
    coef: np.ndarray


def fit_clogit(groups: list[tuple[np.ndarray, int]], lam: float) -> CLogit:
    k = groups[0][0].shape[1]

    def f(b):
        ll, g = 0.0, np.zeros(k)
        for Z, ch in groups:
            u = Z @ b
            mx = u.max()
            e = np.exp(u - mx)
            s_ = e.sum()
            ll -= u[ch] - mx - math.log(s_)
            g -= Z[ch] - (e[:, None] * Z).sum(axis=0) / s_
        n = len(groups)
        return ll / n + 0.5 * lam * b @ b / n, g / n + lam * b / n

    r = minimize(f, np.zeros(k), jac=True, method="L-BFGS-B", options={"maxiter": 300})
    return CLogit(lam, r.x)


def logloss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_ci(d: np.ndarray, groups: list, n_boot: int = 2000, seed: int = 11) -> list[float]:
    """Mean of d with a 95% bootstrap CI resampling teams."""
    ug, inv = np.unique(np.array(groups, dtype=object).astype(str), return_inverse=True)
    sums = np.bincount(inv, weights=d, minlength=ug.size)
    cnt = np.bincount(inv, minlength=ug.size).astype(float)
    rng = np.random.default_rng(seed)
    bs = np.empty(n_boot)
    for k in range(n_boot):
        ix = rng.integers(0, ug.size, ug.size)
        bs[k] = sums[ix].sum() / cnt[ix].sum()
    return [round(float(d.mean()), 5), round(float(np.percentile(bs, 2.5)), 5), round(float(np.percentile(bs, 97.5)), 5)]


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    out = []
    for k in range(bins):
        sel = (p >= q[k]) & ((p < q[k + 1]) if k < bins - 1 else (p <= q[k + 1]))
        if sel.any():
            out.append({"lo": round(float(q[k]), 4), "hi": round(float(q[k + 1]), 4), "n": int(sel.sum()),
                        "p_mean": round(float(p[sel].mean()), 4), "y_mean": round(float(y[sel].mean()), 4)})
    return out


def calib_slope(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    m = fit_logit(z[:, None], y, 1e-6)
    b = float(m.coef[0] / m.sd[0])
    return float(m.intercept - m.coef[0] * m.mean[0] / m.sd[0]), b


# ── destinations ─────────────────────────────────────────────────────────────

@dataclass
class Teams:
    tids: list[str]
    ix: dict[str, int]
    margin: np.ndarray
    conf: list
    conf_margin: np.ndarray
    need: dict[str, np.ndarray]               # position group -> expected departures / roster players there
    need_all: np.ndarray                      # expected departures / players
    portal_use: np.ndarray                    # share of the team's players who transferred in this season


def team_table(P: Panel, p_leave: np.ndarray) -> Teams:
    F = {c: i for i, c in enumerate(FEATURES)}
    tids = sorted(set(P.tid))
    ix = {t: k for k, t in enumerate(tids)}
    n = len(tids)
    margin, cm = np.zeros(n), np.zeros(n)
    conf = [None] * n
    groups = POS_GROUPS[P.level]
    dep = {g: np.zeros(n) for g in groups}
    cnt = {g: np.zeros(n) for g in groups}
    newin = np.zeros(n)
    for i, t in enumerate(P.tid):
        k = ix[t]
        newin[k] += P.X[i, F["new_in"]]
        margin[k] = P.X[i, F["margin"]]
        cm[k] = P.X[i, F["conf_margin"]]
        g = P.pos[i] if P.pos[i] in dep else groups[0]
        dep[g][k] += p_leave[i]
        cnt[g][k] += 1
    need = {g: dep[g] / np.maximum(cnt[g], 1.0) for g in groups}
    tot = sum(cnt.values())
    return Teams(tids, ix, margin, conf, cm, need, sum(dep.values()) / np.maximum(tot, 1.0), newin / np.maximum(tot, 1.0))


def choice_rows(P: Panel, T: Teams, j: int, conf_of: dict[str, Any]) -> np.ndarray:
    """Choice features of mover j against every member team (his own included; the caller masks it)."""
    F = {c: i for i, c in enumerate(FEATURES)}
    md = T.margin - P.X[j, F["margin"]]
    cd = T.conf_margin - P.X[j, F["conf_margin"]]
    my_conf = conf_of.get(P.tid[j])
    same = np.array([conf_of.get(t) == my_conf and my_conf is not None for t in T.tids], dtype=float)
    pct = P.info["pctl"][j]
    pct = 0.0 if pct != pct else pct - 0.5
    g = P.pos[j] if P.pos[j] in T.need else next(iter(T.need))
    return np.column_stack([md / 10.0, (md / 10.0) ** 2, cd / 10.0, (cd / 10.0) ** 2, same, pct * T.margin / 10.0, T.need[g],
                            T.need_all, T.portal_use])


def join_matrix(P: Panel, T: Teams, cl: CLogit, p_tr: np.ndarray, conf_of: dict[str, Any]) -> np.ndarray:
    """(players, teams): chance he transfers x the destination model's share of each team (his own team excluded)."""
    J = np.zeros((len(P), len(T.tids)), dtype=np.float32)
    for j in range(len(P)):
        u = choice_rows(P, T, j, conf_of) @ cl.coef
        u[T.ix[P.tid[j]]] = -np.inf
        u -= u.max()
        e = np.exp(u)
        J[j] = p_tr[j] * e / e.sum()
    return J


def mover_groups(P: Panel, T: Teams, conf_of: dict[str, Any]) -> list[tuple[np.ndarray, int]]:
    out = []
    for j in range(len(P)):
        d = P.dest[j] if P.dest else None
        if d is None or d not in T.ix or d == P.tid[j]:
            continue
        Z = choice_rows(P, T, j, conf_of)
        own = T.ix[P.tid[j]]
        keep = np.arange(len(T.tids)) != own
        ch = int(np.flatnonzero(np.flatnonzero(keep) == T.ix[d])[0])
        out.append((Z[keep], ch))
    return out


# ── the build ────────────────────────────────────────────────────────────────

# Set on the dev seasons (docs/research/college_moves.md): ridge, half-life in seasons, destination ridge; targets
# are published only where they passed the test.
SETTINGS = {"cfb": {"lam": 100.0, "half_life": 2.0, "lam_c": 1.0, "targets": False},
            "mbb": {"lam": 100.0, "half_life": 2.0, "lam_c": 10.0, "targets": True},
            "wbb": {"lam": 100.0, "half_life": 2.0, "lam_c": 1.0, "targets": True}}
MIN_PANEL = 500                    # a season needs this many players to train on
MIN_SEASON_SHARE = 0.25            # the current season is forecast once it has this share of last season's box scores
# The pre-registered walk-forward test (22 October 2026), fixed numbers; scripts/campus_moves.py reproduces them.
VALIDATION = {
    "cfb": {"test": "2022-23, 2023-24, 2024-25 transitions (21,980 players)", "rate": 0.522,
            "leave": {"passed": True, "ll_model": 0.6519, "ll_base": 0.6944, "ll_diff_ci": [-0.0425, -0.0480, -0.0369],
                      "brier_model": 0.2305, "brier_base": 0.2507, "calib_slope": 0.82, "mean_p": 0.502,
                      "note": "positions inferred from the box score in every season (fixed after the first run, which "
                              "used roster positions only the current season has: -0.0435 [-0.0488, -0.0379])"},
            "joint": {"passed": True, "ll_model": 0.9381, "ll_base": 0.9963, "ll_diff_ci": [-0.0582, -0.0646, -0.0517]},
            "targets": {"passed": False, "precision10": 0.0013, "precision10_avail": 0.0021, "diff_ci": [-0.0008, -0.0026, 0.0008],
                        "why": "the destination model did not beat availability alone in the pre-registered run; the re-run "
                               "after the position fix did (0.47% v 0.24% at 10, not at 25), which is post hoc: not shown"}},
    "mbb": {"test": "2023-24, 2024-25, 2025-26 transitions (15,194 players)", "rate": 0.612,
            "leave": {"passed": True, "ll_model": 0.6172, "ll_base": 0.6679, "ll_diff_ci": [-0.0508, -0.0571, -0.0448],
                      "brier_model": 0.2166, "brier_base": 0.2375, "calib_slope": 0.81, "mean_p": 0.569,
                      "note": "mean forecast 0.044 under the observed rate, the base rate 0.053 under"},
            "joint": {"passed": True, "ll_model": 0.9510, "ll_base": 1.0738, "ll_diff_ci": [-0.1228, -0.1305, -0.1152]},
            "targets": {"passed": True, "precision10": 0.0036, "precision10_avail": 0.0009, "diff_ci": [0.0027, 0.0014, 0.0040],
                        "hit25": 0.080, "hit25_avail": 0.023}},
    "wbb": {"test": "2023-24, 2024-25, 2025-26 transitions (14,096 players)", "rate": 0.531,
            "leave": {"passed": True, "ll_model": 0.5898, "ll_base": 0.6914, "ll_diff_ci": [-0.1016, -0.1094, -0.0936],
                      "brier_model": 0.2043, "brier_base": 0.2491, "calib_slope": 0.96, "mean_p": 0.504},
            "joint": {"passed": True, "ll_model": 0.8703, "ll_base": 1.0251, "ll_diff_ci": [-0.1548, -0.1642, -0.1455]},
            "targets": {"passed": True, "precision10": 0.0046, "precision10_avail": 0.0013, "diff_ci": [0.0033, 0.0017, 0.0049],
                        "hit25": 0.109, "hit25_avail": 0.024}},
}
METHOD = (
    "Chance of leaving: a walk-forward model of where each player is next season, trained on every earlier season's "
    "box scores (from 2014), recent seasons weighted more. Moves are inferred, not the official transfer portal: the "
    "same ESPN athlete on another team's box score next season is an inferred transfer; no box-score line next season "
    "covers graduation, the pros, a lower division, injury or not playing. The portal's public lists carry 247Sports "
    "ratings we may not republish. No class history exists in the data (only this season's rosters carry a class), so "
    "experience is the number of earlier seasons with a box-score line; no NIL, coaching or eligibility data. Football box "
    "scores never list offensive linemen, so they have no estimate. Targets rank likely transfers by their chance of "
    "joining the team: availability x a model of which teams transfers join (team and conference strength, his "
    "production x the team's strength, the team's expected departures); shown where that model beat availability alone."
)
P_COLS = ["id", "name", "team", "pos", "p", "p_transfer", "p_gone", "exp", "class", "pctl", "new_in"]


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def build_movement(level: str, current: int) -> dict:
    """
    Every current-season player's chance of leaving before next season (an inferred transfer, or no box-score line),
    each team's outlook by position and, where they passed, its targets. Fitted on every complete transition.
    Returns {"players": [records], "teams": {tid: block}, "meta": {...}}.
    """
    t0 = datetime.now(timezone.utc)
    cfg = SETTINGS[level]
    seasons = [s for s in ST.seasons_on_disk(level) if s >= FIRST_ROSTER_SEASON - 1 and s <= current]
    infos = {s: season_info(level, s) for s in seasons}
    meta: dict[str, Any] = {"level": level, "season": current, "next_season": current + 1, "method": METHOD,
                            "validation": VALIDATION.get(level), "inferred": True, "settings": cfg}
    train = []
    for s in range(FIRST_ROSTER_SEASON + 1, current):
        P = build_panel(level, s, infos, labels=True)
        if P is not None and len(P) >= MIN_PANEL:
            train.append(P)
    cur_info, prev_info = infos.get(current), infos.get(current - 1)
    share = (cur_info or {}).get("n_box_games", 0) / max((prev_info or {}).get("n_box_games", 1), 1)
    meta["season_share"] = round(share, 3)
    if share < MIN_SEASON_SHARE:
        meta.update({"ok": False, "reason": f"the {current} season has {int(round(100 * share))}% of a season's box scores; "
                                            f"the forecast appears from {int(100 * MIN_SEASON_SHARE)}%"})
        return {"players": [], "teams": {}, "meta": meta}
    cur = build_panel(level, current, infos, labels=False)
    if not train or cur is None:
        meta.update({"ok": False, "reason": "no complete season to learn from" if not train else "no current box scores"})
        return {"players": [], "teams": {}, "meta": meta}
    X = np.vstack([P.X for P in train])
    y = np.concatenate([P.y for P in train])
    typ = np.concatenate([P.typ for P in train])
    sea = np.concatenate([np.full(len(P), P.season) for P in train])
    lm = fit_season_logit(X, y, sea, cfg["lam"], cfg["half_life"])
    lv = y == 1
    tm = fit_season_logit(X[lv], (typ[lv] == 1).astype(float), sea[lv], cfg["lam"], cfg["half_life"])
    p = lm.predict(cur.X)
    p_tr = p * tm.predict(cur.X)
    Tc = team_table(cur, p)
    J = None
    cl = None
    if cfg["targets"]:
        groups = []
        for P in train:
            groups += mover_groups(P, team_table(P, lm.predict(P.X)), dict(infos[P.season]["teams"]))
        cl = fit_clogit(groups, cfg["lam_c"]) if groups else None
        if cl is not None:
            J = join_matrix(cur, Tc, cl, p_tr, dict(infos[current]["teams"]))
    names = infos[current]["names"]
    tnames = infos[current]["team_names"]
    groups_l = POS_GROUPS[level]
    # Arrivals by position: the last complete transition's inferred transfers in per team (a base rate, labelled).
    last = train[-1]
    arr: dict[str, float] = defaultdict(float)
    for j in range(len(last)):
        d = last.dest[j]
        if d is not None and d != last.tid[j]:
            arr[last.pos[j]] += 1.0
    n_teams_last = max(len(set(last.tid)), 1)
    mean_in = {g: arr.get(g, 0.0) / n_teams_last for g in groups_l}
    players = []
    for i in range(len(cur)):
        pc = cur.info["pctl"][i]
        players.append({"id": cur.pid[i], "name": names.get(cur.pid[i]), "team": cur.tid[i], "pos": cur.pos[i],
                        "p": round(float(p[i]), 3), "p_transfer": round(float(p_tr[i]), 3), "p_gone": round(float(p[i] - p_tr[i]), 3),
                        "exp": int(cur.info["exp"][i]), "class": cur.info["cls"][i],
                        "pctl": None if pc != pc else int(round(100 * pc)), "new_in": int(cur.info["new_in"][i])})
    players.sort(key=lambda r: -r["p"])
    teams: dict[str, dict] = {}
    for t in Tc.tids:
        k = Tc.ix[t]
        mine = [i for i in range(len(cur)) if cur.tid[i] == t]
        out_g = {g: 0.0 for g in groups_l}
        tr_g = {g: 0.0 for g in groups_l}
        for i in mine:
            g = cur.pos[i] if cur.pos[i] in out_g else groups_l[0]
            out_g[g] += float(p[i])
            tr_g[g] += float(p_tr[i])
        targets = []
        if J is not None:
            col = J[:, k].astype(float).copy()
            for i in mine:
                col[i] = -1.0
            for j in np.argsort(-col)[:TARGETS_PER_TEAM].tolist():
                if col[j] <= 0:
                    break
                pc = cur.info["pctl"][j]
                md = float(Tc.margin[k] - cur.X[j, FEATURES.index("margin")])
                g = cur.pos[j]
                why = [f"{'transferred in to' if cur.info['new_in'][j] else 'at'} {tnames.get(cur.tid[j]) or cur.tid[j]}"]
                if pc == pc:
                    why.append(f"{_ordinal(int(round(100 * pc)))} percentile of {g}s this season")
                why.append("a step up for him" if md > 2 else "a step down for him" if md < -2 else "a similar team")
                why.append(f"you expect {out_g.get(g, 0.0):.1f} {g} departures")
                targets.append({"id": cur.pid[j], "name": names.get(cur.pid[j]), "team": cur.tid[j], "pos": g,
                                "p_join": round(float(col[j]), 4), "p_transfer": round(float(p_tr[j]), 3),
                                "pctl": None if pc != pc else int(round(100 * pc)), "margin_step": round(md, 1),
                                "plaus": round(float(col[j] / p_tr[j] * (len(Tc.tids) - 1)), 2) if p_tr[j] > 0 else None,
                                "why": "; ".join(why)})
        teams[t] = {"season": current, "next_season": current + 1,
                    "expected_out": {g: round(v, 2) for g, v in out_g.items()}, "out_total": round(sum(out_g.values()), 2),
                    "expected_transfers_out": {g: round(v, 2) for g, v in tr_g.items()},
                    "expected_in": {g: round(mean_in[g], 2) for g in groups_l}, "in_basis": "base_rate",
                    "p_add": {g: round(1.0 - math.exp(-mean_in[g]), 3) for g in groups_l},
                    "roster": sorted(([cur.pid[i], round(float(p[i]), 3), round(float(p_tr[i]), 3)] for i in mine), key=lambda r: -r[1]),
                    "targets": targets if cfg["targets"] else None}
    meta.update({"ok": True, "n_players": len(players), "n_teams": len(teams), "positions": list(groups_l),
                 "training": [{"season": P.season, "n": len(P), "rate": round(float(P.y.mean()), 4),
                               "transfer": round(float(np.mean(P.typ == 1)), 4)} for P in train],
                 "arrivals": {"basis": f"inferred transfers in per team, {last.season}-{str(last.season + 1)[2:]} to "
                                       f"{last.season + 1}-{str(last.season + 2)[2:]}", "mean": {g: round(v, 2) for g, v in mean_in.items()}},
                 "models": {"leave": lm.to_json(FEATURES), "transfer": tm.to_json(FEATURES),
                            "choice": {"cols": list(CHOICE), "coef": [round(float(x), 4) for x in cl.coef]} if cl is not None else None},
                 "runtime_s": round((datetime.now(timezone.utc) - t0).total_seconds(), 1)})
    logger.info("movement %s %d: %d players, %d teams, %.1fs", level, current, len(players), len(teams), meta["runtime_s"])
    return {"players": players, "teams": teams, "meta": meta}


def write_movement(level: str, data_dir: Path, current: int | None = None) -> dict:
    """
    data/<L>/<S>/movement.json for the current season, and `movement` added to that season's team pages
    (teams/<tid>.json, written by the level's builder just before). Returns a summary.
    """
    import json

    from oddsmarkets.college import packing

    current = current if current is not None else canon.current_season(level)
    res = build_movement(level, current)
    folder = Path(data_dir) / level / str(current)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"ok": bool(res["meta"].get("ok")), "level": level, "season": current, "updated_at": stamp,
               "meta": res["meta"], "players": packing.pack(res["players"], P_COLS)}
    if not payload["ok"]:
        payload["reason"] = res["meta"].get("reason")
    (folder / "movement.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                                          encoding="utf-8")
    n = 0
    for t, block in res["teams"].items():
        f = folder / "teams" / f"{t}.json"
        if not f.exists():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        doc["movement"] = block
        f.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        n += 1
    return {"ok": True, "published": payload["ok"], "players": len(res["players"]), "team_pages": n,
            "reason": res["meta"].get("reason")}
