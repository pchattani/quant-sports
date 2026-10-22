"""
Team strength: score- and venue-adjusted 5v5 xG and shot rates, power-play and penalty-kill units, penalty drawing
and taking, finishing, and a goaltending component with the starter as an input; time decay and preseason priors.

Units (one weighted ridge each, rows = team-games from `_cdata.team_games`, weights = minutes x decay)
-------------------------------------------------------------------------------------------------
    5v5 xG       xGF60_{g,t} = mu_ev + O_t + D_o + e        O_t: xG/60 created above the league,
                                                             D_o: xG/60 *allowed* above the league (+ = worse)
    5v5 shots    FF60_{g,t}  = mu_ff + SO_t + SD_o + e       unblocked attempts per 60 (reported; game-model input)
    power play   PPxG60_{g,t} = mu_pp + PP_t + PK_o + e      own PP xG/60 v the opponent's kill (PK + = worse kill)
    penalties    PPmin_{g,t} = mu_pen + DR_t + TK_o + e      power-play minutes per game: drawn by t, taken by o
    goals        GF_{g,t}    = mu_g + A_t + G_o + e          all-strength goals per game (the goals-only model,
                                                             used alone when there is no event data)
Each ridge minimises sum_i w_i (y_i - x_i b)^2 + sum_j lam_j (b_j - m_j)^2 with lam_j in the row weight's unit
(minutes, or games for penalties and goals), so lam_j is the prior's weight; w_i = minutes_i x 0.5^(age_i / H),
age in days before the fit date, H = half_life_days. The 5v5 rates are already venue adjusted (`_cdata`), so home
advantage is left to the game model.

Finishing and goaltending (decayed sums over the season's games, shrunk toward the prior)
    conv          = sum GA_nonEN / sum xGA_nonEN over the league (the xG model's calibration)
    fin_t         = (sum GF_nonEN - conv * sum xGF_nonEN + k_fin * m_t) / (sum xGF_nonEN + k_fin) / conv
    goalie val_q  = (sum GA - conv * sum xGA + k_g * m_q) / (sum xGA + k_g) / conv   over games q started
val_q is goals allowed per expected goal above the league (negative = better); GSAx = -val_q * conv * xGA. When
builder B's `goalies` module publishes GSAx, a goalie's val is B's -GSAx / (conv * xGA) shrunk the same way.

Expected goals for a game (`expected_goals`, regulation, empty-net goals excluded), side h against side a:
    PPmin_h = clip(mu_pen + DR_h + TK_a, 1, 12),  EVmin = 60 - PPmin_h - PPmin_a   (4v4 / 3v3 counted at 5v5 rates)
    xG_h    = EVmin/60 (mu_ev + O_h + D_a) + PPmin_h/60 (mu_pp + PP_h + PK_a) + PPmin_a/60 mu_sh
    G_h     = conv * xG_h * (1 + fin_h) * (1 + val_{starter_a})
The starter is an input (`goalie_h` / `goalie_a`); the default is the team's most frequent starter in its last ten
games. Net rating (goals per game against a league-average team and goalie) = G_t - G_against_t.

Priors for season S: m = carry_unit x (S-1 end-of-season value), franchise-mapped (ATL->WPG, PHX/ARI->UTA);
goalies carry their latest value x carry_goalie per idle season (new goalies start at goalie_new). `fit_carryover`
fits carry as the no-intercept OLS slope of a franchise's end-of-season value on the previous season's.

Schedule effects (fitted in game.py on these features, defined here): back-to-back, rest (days, capped at 3),
travel (km / 1000 from the previous game's venue) and time-zone change (hours), each home minus away.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D

logger = logging.getLogger(__name__)

VERSION = 1
UNITS = ("ev_off", "ev_def", "ff_off", "ff_def", "pp", "pk", "draw", "take", "g_att", "g_def", "fin")
DEFAULTS: dict[str, Any] = {
    "half_life_days": 300.0,
    "lam": {"ev": 1500.0, "ff": 900.0, "pp": 260.0, "pen": 30.0, "goals": 45.0},
    "k_fin": 160.0, "k_goalie": 110.0,
    "carry": {"ev_off": 0.6, "ev_def": 0.6, "ff_off": 0.65, "ff_def": 0.65, "pp": 0.45, "pk": 0.4, "draw": 0.5, "take": 0.5,
              "g_att": 0.75, "g_def": 0.75, "fin": 0.35, "goalie": 0.7},
    "goalie_new": 0.03,
    "league": {"ev_xg60": 2.45, "ff60": 42.0, "pp_xg60": 6.6, "pp_min": 4.6, "sh_g60": 0.75, "conv": 1.0, "goals_pg": 2.95},
}
SCHED_FEATURES = ("b2b", "rest", "travel", "tz")


def params(over: dict | None = None, fresh: bool = False) -> dict:
    """DEFAULTS, updated by the fitted file (cache, else committed; skipped with fresh=True), then by `over`."""
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    fit = None if fresh else (D.read_json(D.c_cache() / "team_strength_params.json") or D.read_json(D.FITTED / "team_strength_params.json"))
    for src in ((fit or {}).get("result", fit or {}), over or {}):
        for k, v in (src or {}).items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k].update(v)
            elif k in p:
                p[k] = v
    return p


# ── the ridge ────────────────────────────────────────────────────────────────

def spd_inv(A: np.ndarray) -> np.ndarray:
    import scipy.linalg as sl
    try:
        return sl.cho_solve(sl.cho_factor(A, check_finite=False), np.eye(len(A)), check_finite=False)
    except (np.linalg.LinAlgError, ValueError):
        return sl.pinvh(A)


def ridge_two_way(y, w, a_idx, b_idx, n, lam, prior_a, prior_b, mu0=None, dec=None):
    """y ~ mu + a[a_idx] + b[b_idx], ridge toward priors (mu free). Returns (mu, a, b, var_a, var_b, s2)."""
    y, w = np.asarray(y, float), np.asarray(w, float)
    npar = 1 + 2 * n
    A = np.zeros((npar, npar))
    rhs = np.zeros(npar)
    cols = [np.zeros(len(y), int), 1 + np.asarray(a_idx, int), 1 + n + np.asarray(b_idx, int)]
    for ci in cols:
        rhs += np.bincount(ci, weights=w * y, minlength=npar)
        for cj in cols:
            np.add.at(A, (ci, cj), w)
    lv = np.concatenate([[1e-6], np.full(n, lam), np.full(n, lam)])
    pv = np.concatenate([[mu0 if mu0 is not None else 0.0], prior_a, prior_b])
    if mu0 is not None:
        lv[0] = 1e-3
    A[np.diag_indices(npar)] += lv
    rhs += lv * pv
    inv = spd_inv(A)
    beta = inv @ rhs
    fit = beta[cols[0]] + beta[cols[1]] + beta[cols[2]]
    # w = minutes x decay, so E[w res^2] = decay x s2 (s2 = residual variance of one minute's rate)
    den = float(np.sum(dec)) if dec is not None else float(len(y))
    s2 = float(np.sum(w * (y - fit) ** 2) / max(den, 1e-9)) if len(y) else 1.0
    d = np.diag(inv)
    return float(beta[0]), beta[1:1 + n], beta[1 + n:], d[1:1 + n], d[1 + n:], s2


# ── ratings ──────────────────────────────────────────────────────────────────

@dataclass
class Ratings:
    season: int
    through: Any
    mode: str = "xg"
    teams: dict[str, dict] = field(default_factory=dict)
    goalies: dict[str, dict] = field(default_factory=dict)
    league: dict = field(default_factory=dict)
    starters: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"season": self.season, "through": str(self.through) if self.through is not None else None,
                "mode": self.mode, "teams": self.teams, "goalies": self.goalies, "league": self.league,
                "starters": self.starters}


def _decay(dates: pd.Series, through, hl_days: float) -> np.ndarray:
    if through is None or len(dates) == 0:
        return np.ones(len(dates))
    age = (pd.Timestamp(through) - pd.to_datetime(dates)).dt.days.to_numpy(dtype=float)
    age = np.where(np.isfinite(age), np.maximum(age, 0.0), 0.0)
    return 0.5 ** (age / max(hl_days, 1e-6))


def _starters(tg: pd.DataFrame) -> dict[str, str]:
    out = {}
    if tg.empty or "goalie" not in tg:
        return out
    t = tg[tg["goalie"].notna()].sort_values("date")
    for team, g in t.groupby("team"):
        last = g.tail(10)["goalie"].astype(str)
        if len(last):
            vc = last.value_counts()
            top = vc[vc == vc.max()].index
            out[str(team)] = str(last[last.isin(top)].iloc[-1])
    return out


def fit(tg: pd.DataFrame, season: int, through: Any = None, prior: dict | None = None, prm: dict | None = None,
        teams: list[str] | None = None, goalie_ext: dict | None = None) -> Ratings:
    """Ratings from the team-game rows of `season` dated strictly before `through` (all when None), pulled toward
    `prior` ({"teams": {t: {unit: v}}, "goalies": {q: v}}). goalie_ext: {q: {"gsax", "xga"}} from builder B."""
    p = prm or params()
    hl = float(p["half_life_days"])
    lam = p["lam"]
    u = tg if tg is not None else pd.DataFrame(columns=D.TG_COLS)
    if len(u):
        u = u[u["season"] == int(season)]
        if through is not None:
            u = u[pd.to_datetime(u["date"]) < pd.Timestamp(through)]
    pr_t = (prior or {}).get("teams") or {}
    pr_g = (prior or {}).get("goalies") or {}
    tl = sorted(set(teams or []) | (set(u["team"].astype(str)) if len(u) else set()) | set(pr_t))
    if not tl:
        tl = sorted(D.teams_for(season))
    ti = {t: i for i, t in enumerate(tl)}
    T = len(tl)
    thr = pd.Timestamp(through) if through is not None else (pd.to_datetime(u["date"]).max() + pd.Timedelta(days=1) if len(u) else None)
    L = dict(p["league"])
    L.update({k: v for k, v in ((prior or {}).get("league") or {}).items() if k in L})
    has_xg = bool(len(u)) and float(u["ev_xgf"].notna().mean()) >= 0.5 and u["ev_xgf"].notna().sum() >= 20
    mode = "xg" if has_xg or (not len(u) and (prior or {}).get("mode") == "xg") else "goals"
    out = Ratings(season=int(season), through=through, mode=mode)
    dec = _decay(u["date"], thr, hl) if len(u) else np.zeros(0)
    a_i = u["team"].map(ti).to_numpy(int) if len(u) else np.zeros(0, int)
    b_i = u["opp"].map(ti).to_numpy(int) if len(u) else np.zeros(0, int)

    def pri(unit):
        return np.array([float((pr_t.get(t) or {}).get(unit, 0.0)) for t in tl])

    res: dict[str, tuple] = {}

    def run(name, ycol, wcol, ua, ub, lam_v, mu_default, per60=True, min_w=0.0):
        if len(u):
            num = u[ycol].to_numpy(float)
            den = u[wcol].to_numpy(float) if wcol else np.ones(len(u))
            m = np.isfinite(num) & np.isfinite(den) & (den > min_w)
            if m.sum() >= 4:
                y = num[m] / den[m] * (60.0 if per60 else 1.0)
                w = den[m] * dec[m]
                mu, a, b, va, vb, s2 = ridge_two_way(y, w, a_i[m], b_i[m], T, lam_v, pri(ua), pri(ub), dec=dec[m])
                # s2 is per unit weight (minutes); a row of weight W has variance s2 / W
                res[name] = (mu, a, b, va * s2, vb * s2, True)
                return
        res[name] = (mu_default, pri(ua), pri(ub), np.full(T, s2_default(lam_v)), np.full(T, s2_default(lam_v)), False)

    def s2_default(lam_v):
        return 1.0 / max(lam_v, 1e-6)

    run("ev", "ev_xgf", "ev_toi", "ev_off", "ev_def", lam["ev"], L["ev_xg60"], min_w=5.0)
    run("ff", "ev_ff", "ev_toi", "ff_off", "ff_def", lam["ff"], L["ff60"], min_w=5.0)
    run("pp", "pp_xgf", "pp_toi", "pp", "pk", lam["pp"], L["pp_xg60"], min_w=0.5)
    run("pen", "pp_toi", None, "draw", "take", lam["pen"], L["pp_min"], per60=False)
    run("goals", "gf", None, "g_att", "g_def", lam["goals"], L["goals_pg"], per60=False)
    if res["ev"][5]:
        L["ev_xg60"] = res["ev"][0]
    if res["ff"][5]:
        L["ff60"] = res["ff"][0]
    if res["pp"][5]:
        L["pp_xg60"] = res["pp"][0]
    if res["pen"][5]:
        L["pp_min"] = float(np.clip(res["pen"][0], 1.5, 10.0))
    if res["goals"][5]:
        L["goals_pg"] = res["goals"][0]
    # conversion, shorthanded goals, finishing, goalies
    tf = {t: 0.0 for t in tl}
    if len(u) and has_xg:
        xa = u["xga_all"].to_numpy(float)
        ga = u["ga_all"].to_numpy(float)
        m = np.isfinite(xa) & np.isfinite(ga)
        if m.sum() and np.sum(dec[m] * xa[m]) > 5:
            L["conv"] = float(np.sum(dec[m] * ga[m]) / np.sum(dec[m] * xa[m]))
        pkt = u["pk_toi"].to_numpy(float)
        shg = (u["ga_all"].to_numpy(float) - u["ev_ga"].to_numpy(float) - u["pk_ga"].to_numpy(float))
        # goals against while the team is on the power play are shorthanded goals for the opponent (approximated
        # here as the league's non-5v5, non-PK goals per PP minute of the opponent)
        ppt = u["pp_toi"].to_numpy(float)
        mm = np.isfinite(shg) & np.isfinite(ppt) & (ppt > 0)
        if mm.sum() and np.sum(dec[mm] * ppt[mm]) > 30:
            L["sh_g60"] = float(np.clip(np.sum(dec[mm] * np.maximum(shg[mm], 0) * 0.35) / np.sum(dec[mm] * ppt[mm]) * 60, 0.2, 1.5))
        # finishing: own goals v own xG (the opponent's xga_all row of the same game)
        opp_rows = u.set_index(["game_id", "team"])
        key = pd.MultiIndex.from_arrays([u["game_id"], u["opp"]])
        xf = opp_rows["xga_all"].reindex(key).to_numpy(float)
        gfn = opp_rows["ga_all"].reindex(key).to_numpy(float)
        conv = L["conv"]
        mf = np.isfinite(xf) & np.isfinite(gfn)
        sx = np.bincount(a_i[mf], weights=dec[mf] * xf[mf], minlength=T)
        sr = np.bincount(a_i[mf], weights=dec[mf] * (gfn[mf] - conv * xf[mf]), minlength=T)
        kf = float(p["k_fin"])
        pf = pri("fin")
        fin = (sr / max(conv, 1e-6) + kf * pf) / (sx + kf)
        tf = {t: float(fin[i]) for t, i in ti.items()}
    # goalies
    gl: dict[str, dict] = {}
    if len(u) and "goalie" in u and u["goalie"].notna().any():
        conv = L["conv"]
        kg = float(p["k_goalie"])
        gg = u[u["goalie"].notna()].copy()
        gg["w"] = _decay(gg["date"], thr, hl)
        if has_xg:
            gg = gg[gg["xga_all"].notna()]
            gg["r"] = gg["w"] * (gg["ga_all"] - conv * gg["xga_all"])
            gg["x"] = gg["w"] * gg["xga_all"]
        else:
            # goals mode: goals allowed above what the opponent's attack and own defence predict
            gg["r"] = 0.0
            gg["x"] = 0.0
        agg = gg.groupby(gg["goalie"].astype(str)).agg(r=("r", "sum"), x=("x", "sum"), n=("game_id", "count"),
                                                       team=("team", "last"), last=("date", "max"))
        for q, r in agg.iterrows():
            m0 = float(pr_g.get(q, p["goalie_new"]))
            ext = (goalie_ext or {}).get(q)
            if ext and ext.get("xga"):
                rr = -float(ext["gsax"]) / max(conv, 1e-6)
                xx = float(ext["xga"]) / max(conv, 1e-6)
                val = (rr + kg * m0) / (xx + kg)
                xs = xx
            else:
                val = (r["r"] / max(conv, 1e-6) + kg * m0) / (r["x"] + kg)
                xs = r["x"]
            gl[q] = {"val": float(val), "xga": float(xs), "n": int(r["n"]), "team": str(r["team"]),
                     "se": float(0.9 / math.sqrt(max(xs, 0.0) + kg)), "gsax": float(-(val) * conv * xs)}
    for q, v in pr_g.items():
        if q not in gl:
            gl[q] = {"val": float(v), "xga": 0.0, "n": 0, "team": None, "se": float(0.9 / math.sqrt(p["k_goalie"])), "gsax": 0.0}
    out.goalies = gl
    out.starters = _starters(u) if len(u) else dict((prior or {}).get("starters") or {})
    L["n_games"] = int(u["game_id"].nunique()) if len(u) else 0
    out.league = L
    ev, ff, pp, pen, gs = res["ev"], res["ff"], res["pp"], res["pen"], res["goals"]
    for t, i in ti.items():
        rec = {"ev_off": float(ev[1][i]), "ev_def": float(ev[2][i]), "ff_off": float(ff[1][i]), "ff_def": float(ff[2][i]),
               "pp": float(pp[1][i]), "pk": float(pp[2][i]), "draw": float(pen[1][i]), "take": float(pen[2][i]),
               "g_att": float(gs[1][i]), "g_def": float(gs[2][i]), "fin": float(tf.get(t, 0.0)),
               "var": {"ev_off": float(ev[3][i]), "ev_def": float(ev[4][i]), "pp": float(pp[3][i]), "pk": float(pp[4][i]),
                       "g_att": float(gs[3][i]), "g_def": float(gs[4][i])},
               "games": int((u["team"] == t).sum()) if len(u) else 0}
        rec["goalie"] = out.starters.get(t)
        out.teams[t] = rec
    rd = out.as_dict()
    for t in tl:
        gf, ga = side_goals(rd, t)
        out.teams[t].update({"gf_g": gf, "ga_g": ga, "net": gf - ga, "se_net": net_se(rd, t),
                             "g_val": goalie_value(rd, out.teams[t].get("goalie"), p)})
    return out


# ── composition ──────────────────────────────────────────────────────────────

AVG = {"ev_off": 0.0, "ev_def": 0.0, "pp": 0.0, "pk": 0.0, "draw": 0.0, "take": 0.0, "g_att": 0.0, "g_def": 0.0, "fin": 0.0}


def goalie_value(rd: dict, q: str | None, prm: dict | None = None) -> float:
    """Goals allowed per expected goal above the league for goalie q (0 = league average; unknown -> goalie_new)."""
    if q is None:
        return 0.0
    g = (rd.get("goalies") or {}).get(str(q))
    if g is not None:
        return float(g["val"])
    book = rd.get("goalie_prior") or {}
    if str(q) in book:
        return float(book[str(q)])
    return float((prm or DEFAULTS)["goalie_new"])


def expected_goals(rd: dict, home: str, away: str, goalie_h: str | None = None, goalie_a: str | None = None,
                   detail: bool = False, ev_h: float | None = None, ev_a: float | None = None):
    """(G_home, G_away) regulation goals (no empty-net goals) on neutral terms; goalie_x None = the team's starter
    ("avg" = a league-average goalie). With detail=True also a dict of the parts. ev_h / ev_a replace the 5v5 xG
    rates (per 60) of the team-aggregate composition (the player composition, models/players.py)."""
    L = rd.get("league") or DEFAULTS["league"]
    th = (rd.get("teams") or {}).get(home) or AVG
    ta = (rd.get("teams") or {}).get(away) or AVG
    gq_h = 0.0 if goalie_h == "avg" else goalie_value(rd, goalie_h if goalie_h is not None else th.get("goalie"))
    gq_a = 0.0 if goalie_a == "avg" else goalie_value(rd, goalie_a if goalie_a is not None else ta.get("goalie"))
    if (rd.get("mode") or "xg") == "goals":
        gh = max(L.get("goals_pg", 2.95) + th.get("g_att", 0.0) + ta.get("g_def", 0.0), 0.5) * (1 + gq_a)
        ga = max(L.get("goals_pg", 2.95) + ta.get("g_att", 0.0) + th.get("g_def", 0.0), 0.5) * (1 + gq_h)
        if detail:
            return gh, ga, {"mode": "goals", "gq_h": gq_h, "gq_a": gq_a}
        return gh, ga
    ppm_h = float(np.clip(L["pp_min"] + th.get("draw", 0.0) + ta.get("take", 0.0), 1.0, 12.0))
    ppm_a = float(np.clip(L["pp_min"] + ta.get("draw", 0.0) + th.get("take", 0.0), 1.0, 12.0))
    evm = 60.0 - ppm_h - ppm_a
    ev_h = max(L["ev_xg60"] + th.get("ev_off", 0.0) + ta.get("ev_def", 0.0) if ev_h is None else ev_h, 0.4)
    ev_a = max(L["ev_xg60"] + ta.get("ev_off", 0.0) + th.get("ev_def", 0.0) if ev_a is None else ev_a, 0.4)
    pp_h = max(L["pp_xg60"] + th.get("pp", 0.0) + ta.get("pk", 0.0), 1.0)
    pp_a = max(L["pp_xg60"] + ta.get("pp", 0.0) + th.get("pk", 0.0), 1.0)
    sh = L.get("sh_g60", 0.75) / max(L.get("conv", 1.0), 1e-6)
    xg_h = evm / 60 * ev_h + ppm_h / 60 * pp_h + ppm_a / 60 * sh
    xg_a = evm / 60 * ev_a + ppm_a / 60 * pp_a + ppm_h / 60 * sh
    conv = L.get("conv", 1.0)
    gh = conv * xg_h * (1 + th.get("fin", 0.0)) * (1 + gq_a)
    ga = conv * xg_a * (1 + ta.get("fin", 0.0)) * (1 + gq_h)
    if detail:
        return gh, ga, {"mode": "xg", "ppm_h": ppm_h, "ppm_a": ppm_a, "ev_h": ev_h, "ev_a": ev_a, "pp_h": pp_h, "pp_a": pp_a,
                        "xg_h": xg_h, "xg_a": xg_a, "gq_h": gq_h, "gq_a": gq_a}
    return gh, ga


def goals_model(rd: dict, home: str, away: str, goalie_h=None, goalie_a=None) -> tuple[float, float]:
    """The goals-only ratings' expected goals (a second opinion the game model weighs against the xG composition)."""
    L = rd.get("league") or DEFAULTS["league"]
    th = (rd.get("teams") or {}).get(home) or AVG
    ta = (rd.get("teams") or {}).get(away) or AVG
    return (max(L.get("goals_pg", 2.95) + th.get("g_att", 0.0) + ta.get("g_def", 0.0), 0.5),
            max(L.get("goals_pg", 2.95) + ta.get("g_att", 0.0) + th.get("g_def", 0.0), 0.5))


_AVG_TEAM = "__avg__"


def side_goals(rd: dict, team: str, goalie: str | None = None) -> tuple[float, float]:
    """(goals for, goals against) per game against a league-average team and goalie."""
    gf, ga = expected_goals(rd, team, _AVG_TEAM, goalie, "avg")
    return float(gf), float(ga)


def net_se(rd: dict, team: str) -> float:
    """Approximate sd of the net rating (goals per game) from the unit posteriors."""
    t = (rd.get("teams") or {}).get(team) or {}
    v = t.get("var") or {}
    conv = (rd.get("league") or {}).get("conv", 1.0)
    if (rd.get("mode") or "xg") == "goals":
        return float(math.sqrt(max(v.get("g_att", 0.04) + v.get("g_def", 0.04), 1e-6)))
    evm = 52.0 / 60.0
    ppm = 4.6 / 60.0
    var = conv ** 2 * (evm ** 2 * (v.get("ev_off", 0.01) + v.get("ev_def", 0.01)) + ppm ** 2 * (v.get("pp", 0.3) + v.get("pk", 0.3)))
    g = (rd.get("goalies") or {}).get(str(t.get("goalie"))) or {}
    var += (g.get("se", 0.06) * 2.8) ** 2 + (0.03 * 2.8) ** 2     # goalie and finishing uncertainty on ~2.8 xG against
    return float(math.sqrt(max(var, 1e-6)))


# ── schedule features ────────────────────────────────────────────────────────

def schedule_features(df: pd.DataFrame) -> pd.DataFrame:
    """Home-minus-away schedule features from `_cdata.add_context` columns."""
    r_h = np.minimum(df["rest_h"].to_numpy(float), 3.0)
    r_a = np.minimum(df["rest_a"].to_numpy(float), 3.0)
    return pd.DataFrame({"b2b": df["b2b_h"].to_numpy(float) - df["b2b_a"].to_numpy(float), "rest": r_h - r_a,
                         "travel": (df["km_h"].to_numpy(float) - df["km_a"].to_numpy(float)) / 1000.0,
                         "tz": np.abs(df["tz_h"].to_numpy(float)) - np.abs(df["tz_a"].to_numpy(float))}, index=df.index)


# ── priors and carry-over ────────────────────────────────────────────────────

def preseason_prior(last: Ratings | dict | None, season: int, prm: dict | None = None, goalie_book: dict | None = None,
                    teams: list[str] | None = None) -> dict:
    p = prm or params()
    c = p["carry"]
    out: dict[str, Any] = {"teams": {}, "goalies": {}, "starters": {}}
    cur = teams or sorted(D.teams_for(season))
    if last is not None:
        ld = last.as_dict() if isinstance(last, Ratings) else last
        out["mode"] = ld.get("mode")
        out["league"] = dict(ld.get("league") or {})
        by_fr = {D.franchise(t): v for t, v in (ld.get("teams") or {}).items()}
        st_fr = {D.franchise(t): q for t, q in (ld.get("starters") or {}).items()}
        for t in cur:
            v = by_fr.get(D.franchise(t))
            if v:
                out["teams"][t] = {u: float(c.get(u, 0.5)) * float(v.get(u, 0.0)) for u in UNITS}
            if st_fr.get(D.franchise(t)):
                out["starters"][t] = st_fr[D.franchise(t)]
    for q, v in (goalie_book or {}).items():
        idle = max(1, start_year(season) - start_year(int(v["season"])))
        k = float(c["goalie"]) ** idle
        out["goalies"][q] = k * float(v["val"]) + (1 - k) * float(p["goalie_new"]) * 0.5
    return out


def start_year(s: int) -> int:
    return D.start_year(s)


def update_goalie_book(book: dict, r: Ratings, min_xga: float = 15.0) -> dict:
    for q, v in r.goalies.items():
        if v.get("xga", 0) >= min_xga:
            book[q] = {"val": v["val"], "season": r.season, "xga": v["xga"]}
    return book


def fit_carryover(ends: dict[int, Ratings]) -> dict:
    xs: dict[str, list] = {u: [] for u in UNITS}
    ys: dict[str, list] = {u: [] for u in UNITS}
    qx, qy = [], []
    for s in sorted(ends):
        a, b = ends.get(D.prev_season(s)), ends.get(s)
        if not a or not b:
            continue
        af = {D.franchise(t): v for t, v in a.teams.items()}
        for t, v in b.teams.items():
            w = af.get(D.franchise(t))
            if not w or v.get("games", 0) < 30 or w.get("games", 0) < 30:
                continue
            for u in UNITS:
                xs[u].append(w[u])
                ys[u].append(v[u])
        for q, v in b.goalies.items():
            if q in a.goalies and v.get("xga", 0) >= 60 and a.goalies[q].get("xga", 0) >= 60:
                qx.append(a.goalies[q]["val"])
                qy.append(v["val"])
    out = {}
    for u in UNITS:
        x, y = np.array(xs[u]), np.array(ys[u])
        if len(x) >= 40 and float(x @ x) > 0:
            out[u] = float(np.clip(x @ y / (x @ x), 0.0, 1.0))
    if len(qx) >= 30:
        x, y = np.array(qx), np.array(qy)
        out["goalie"] = float(np.clip(x @ y / (x @ x), 0.0, 1.0))
    return out


def b_goalies(season: int) -> dict | None:
    """{goalie: {"gsax","xga"}} from builder B's goalies module when it publishes a season table, else None."""
    try:
        from oddsmarkets.nhl.models import goalies as GB
    except Exception:  # noqa: BLE001
        return None
    for fn in ("for_season", "season_table", "gsax"):
        f = getattr(GB, fn, None)
        if not callable(f):
            continue
        try:
            r = f(season)
        except Exception:  # noqa: BLE001
            continue
        try:
            from oddsmarkets.nhl.analytics.context import frame_of
            df = frame_of(r.get("goalies") if isinstance(r, dict) and "goalies" in r else r)
        except Exception:  # noqa: BLE001
            df = None
        if df is None or df.empty:
            continue
        idc = next((c for c in ("goalie", "player_id", "pid", "id") if c in df), None)
        gc = next((c for c in ("gsax", "GSAx", "gsax_total") if c in df), None)
        xc = next((c for c in ("xga", "xGA", "xg_against", "xga_total") if c in df), None)
        if idc is None or gc is None or xc is None:
            if df.index.name or idc is None:
                df = df.reset_index().rename(columns={"index": "goalie"})
                idc = "goalie"
            if gc is None or xc is None:
                continue
        return {str(r_[idc]): {"gsax": float(r_[gc]), "xga": float(r_[xc])} for r_ in df.to_dict("records")
                if r_.get(gc) is not None and r_.get(xc)}
    return None


# ── season chain ─────────────────────────────────────────────────────────────

def season_chain(seasons: list[int], tg_of=None, prm: dict | None = None) -> dict:
    """End-of-season fits for consecutive seasons with chained priors: {"ends": {S: Ratings}, "priors", "books"}."""
    tg_of = tg_of or D.team_games
    p = prm or params()
    ends, priors, books = {}, {}, {}
    book: dict = {}
    last = None
    for s in sorted(seasons):
        tg = tg_of(s)
        books[s] = dict(book)
        pr = preseason_prior(last, s, p, book)
        priors[s] = pr
        r = fit(tg, s, None, pr, p)
        ends[s] = r
        update_goalie_book(book, r)
        last = r
        del tg
    return {"ends": ends, "priors": priors, "books": books}


_FS_CACHE: dict = {}


def for_season(season: int, through: Any = None, prm: dict | None = None, back: int = 4, tg_of=None) -> dict:
    """Ratings for `season` through a date (exclusive), with the preseason prior chained from up to `back` earlier
    seasons; a plain dict (Ratings.as_dict) with "goalie_prior" and "prior" attached."""
    tg_of = tg_of or D.team_games
    p = prm or params()
    on_disk = set(D.seasons_on_disk())
    chain = [D.sid(D.start_year(season) - k) for k in range(back, 0, -1)]
    chain = [s for s in chain if s in on_disk or tg_of is not D.team_games]
    key = (tuple(chain), repr(sorted((k, str(v)) for k, v in p.items())))
    if key in _FS_CACHE:
        ch = _FS_CACHE[key]
    else:
        ch = season_chain(chain, tg_of=tg_of, prm=p) if chain else {"ends": {}, "books": {}}
        _FS_CACHE.clear()
        _FS_CACHE[key] = ch
    last = ch["ends"].get(D.prev_season(season))
    book: dict = {}
    for s in sorted(ch["ends"]):
        update_goalie_book(book, ch["ends"][s])
    teams = sorted(D.teams_for(season))
    pr = preseason_prior(last, season, p, book, teams)
    tg = tg_of(season)
    r = fit(tg, season, through, pr, p, teams=teams, goalie_ext=b_goalies(season))
    out = r.as_dict()
    out["goalie_prior"] = dict(pr["goalies"])
    out["prior"] = pr
    if tg_of is D.team_games and season >= 20102011:
        # the player composition (each team's latest skaters, walk-forward RAPM through `through`): game.features'
        # lp term; left out on any failure (the game model then reads the team composition in its place)
        from oddsmarkets.nhl.models import players as PL
        PL.attach(out, season, through)
    return out


def table(rd: dict) -> list[dict]:
    rows = []
    for t, v in (rd.get("teams") or {}).items():
        rows.append({"team": t, "net": round(v["net"], 3), "se": round(v["se_net"], 3), "gf": round(v["gf_g"], 3),
                     "ga": round(v["ga_g"], 3), "ev_off": round(v["ev_off"], 3), "ev_def": round(v["ev_def"], 3),
                     "pp": round(v["pp"], 3), "pk": round(v["pk"], 3), "fin": round(v["fin"], 4),
                     "goalie": v.get("goalie"), "g_val": round(v.get("g_val", 0.0), 4), "games": v.get("games")})
    rows.sort(key=lambda r: -r["net"])
    return rows
