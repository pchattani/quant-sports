"""
Pregame game model: margin ~ Normal(mu, sigma).

    mu = s * (net_h - net_a) * pace_g / 100                     rating difference, per game
       + HCA * [not neutral]
       + b_b2b  * (b2b_h - b2b_a)                               second night of a back-to-back
       + b_rest * (min(rest_h, 3) - min(rest_a, 3))             days off before the game, capped
       + b_trav * (km_h - km_a) / 1000                          distance from each team's previous venue
       + b_tz   * (tz_h - tz_a)                                 time-zone hours crossed since the previous game
       + b_alt  * [host in DEN/UTA and not neutral]             altitude
       + inj_h - inj_a                                          injuries (optional input)

    pace_g = pace_h + pace_a - league_pace
    inj_X  = -sum_players (impact_p - replacement) * minutes_p / regulation_minutes * pace_g / 100

`net`, `pace` come from `ratings.fit_ratings` (per 100 possessions). The coefficients s, HCA,
b_* and sigma are fitted by `fit_params` on walk-forward history (ratings refitted weekly
from games strictly before each week, with the preseason prior), by ridge regression (penalty 1
on every coefficient, no intercept) of the observed margin on [rating part, 1(not neutral), features];
sigma is the residual sd (degrees-of-freedom corrected).
Defaults (config.GAME_DEFAULTS) are used until history is on disk.

p_home = Phi(mu / sigma); spread_fair = -mu (the home spread, DraftKings sign convention);
total = total_a + total_b * raw + total_post * [playoff game], raw = pts_h + pts_a with
pts_h = (off_h + def_a - L + h/2) * pace_g / 100 + context/2 and pts_a likewise (context = mu minus the
rating and home terms); the calibration (`fit_from_rows`, walk-forward) removes the ratings total's bias
(NBA: about 2 points low in the regular season and 3 to 10 high in the playoffs; docs/research/basketball_edge.md).
The calibration shift is split equally between pts_h and pts_a.

In the NBA, `predict` returns the market-informed model's line instead (`models/informed.py`: market ratings from
earlier closing lines, availability, fitted to closing spreads) when `ctx["informed"]` carries its inputs
(`informed.inputs_for_game`); "model" says which ("base" / "informed") and "base" keeps the base line.

A market spread converts to a probability with `spread_to_p`: p = Phi(-spread_home / sigma_m),
sigma_m fitted as the sd of (margin + spread_home) over history (default = sigma).
"""
from __future__ import annotations

import json
from pathlib import Path
import logging
import math
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
from scipy.stats import norm

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models.config import ALTITUDE_TEAMS, GAME_DEFAULTS, arenas

logger = logging.getLogger(__name__)

FEATURES = ("hca", "b2b", "rest", "travel_1000km", "tz", "altitude")
REFIT_DAYS = 7
VERSION = 4                  # 4: totals calibration (total_a, total_b, total_post)
_PARAMS: dict[str, dict] = {}


def _league(league):
    return "wnba" if str(league or "").lower() == "wnba" else "nba"


# ── parameters ───────────────────────────────────────────────────────────────

FITTED = Path(__file__).with_name("fitted")

def params(league: str) -> dict:
    """Fitted parameters: the local cache, else the committed fit (models/fitted/, written by
    scripts/bb_fit.py on full history, which is what CI uses), else the defaults (rating_scale 1)."""
    league = _league(league)
    if league in _PARAMS:
        return _PARAMS[league]
    p = dict(GAME_DEFAULTS[league])
    p.setdefault("rating_scale", 1.0)
    for path in (G.cache_root() / "game" / f"params_{league}.json", FITTED / f"game_params_{league}.json"):
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "version" in c and c.get("version") != VERSION:
            continue                                  # a local cache from an older model version
        p.update({k: v for k, v in (c.get("result") or {}).items() if v is not None})
        break
    _PARAMS[league] = p
    return p


def set_params(league: str, p: dict | None) -> None:
    """Override (or with None, reset) the in-process parameters (tests, backtests)."""
    league = _league(league)
    if p is None:
        _PARAMS.pop(league, None)
    else:
        base = dict(GAME_DEFAULTS[league])
        base.setdefault("rating_scale", 1.0)
        base.update(p)
        _PARAMS[league] = base


def sigma(league: str) -> float:
    """Residual sd of the game margin (points)."""
    return float(params(league)["sigma"])


def spread_to_p(spread_home: float | None, league: str = "nba", sd: float | None = None) -> float | None:
    """P(home wins) implied by a home spread (negative = home favoured)."""
    if spread_home is None:
        return None
    try:
        s = float(spread_home)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(s):
        return None
    sd = float(sd if sd is not None else params(league).get("sigma_market") or sigma(league))
    return float(norm.cdf(-s / sd))


# ── schedule context ─────────────────────────────────────────────────────────

def _km(a: tuple | None, b: tuple | None) -> float:
    if not a or not b:
        return 0.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


class Schedule:
    """Per-team game days and venues for rest / travel features."""

    def __init__(self, games: dict | Iterable[dict], teams: dict | None, league: str):
        self.league = _league(league)
        self.abbr = {t: (v or {}).get("abbr") for t, v in (teams or {}).items()}
        self.arena = arenas(self.league)
        self.by_team: dict[str, list[tuple[date, str, str]]] = {}
        gl = games.values() if isinstance(games, dict) else games
        for g in gl:
            if not g or g.get("stype") in ("pre", "allstar") or g.get("status") in ("canceled", "postponed"):
                continue
            d = G.local_day(g)
            if d is None:
                continue
            host = str(g.get("home"))
            for t in (str(g.get("home")), str(g.get("away"))):
                self.by_team.setdefault(t, []).append((d, host, str(g.get("id"))))
        for v in self.by_team.values():
            v.sort()
        self._days = {t: [x[0] for x in v] for t, v in self.by_team.items()}

    def loc(self, host: str) -> tuple | None:
        return self.arena.get(self.abbr.get(host) or "")

    def prev(self, team: str, d: date) -> tuple[date, str] | None:
        import bisect
        days = self._days.get(team) or []
        k = bisect.bisect_left(days, d)
        if k == 0:
            return None
        x = self.by_team[team][k - 1]
        return x[0], x[1]

    def team_features(self, team: str, d: date, host: str) -> dict:
        p = self.prev(team, d)
        here = self.loc(host)
        if p is None:
            return {"rest": 3, "b2b": 0, "km": 0.0, "tz": 0.0}
        rest = max(0, (d - p[0]).days - 1)
        there = self.loc(p[1])
        km = _km(there, here) if rest <= 3 else 0.0
        tz = abs((here or (0, 0, 0))[2] - (there or (0, 0, 0))[2]) if (here and there and rest <= 3) else 0.0
        return {"rest": rest, "b2b": int(rest == 0), "km": km, "tz": float(tz)}


def features(home: str, away: str, d: Any, sched: Schedule | None, neutral: bool = False, league: str = "nba") -> dict:
    """The context feature vector (home minus away) for one game."""
    d = G.day(d)
    if sched is None or d is None:
        return {"hca": 0.0 if neutral else 1.0, "b2b": 0.0, "rest": 0.0, "travel_1000km": 0.0, "tz": 0.0, "altitude": 0.0,
                "detail": {}}
    fh = sched.team_features(home, d, home)
    fa = sched.team_features(away, d, home)
    alt = 1.0 if (not neutral and (sched.abbr.get(home) or "") in ALTITUDE_TEAMS[_league(league)]) else 0.0
    return {"hca": 0.0 if neutral else 1.0, "b2b": float(fh["b2b"] - fa["b2b"]),
            "rest": float(min(fh["rest"], 3) - min(fa["rest"], 3)),
            "travel_1000km": (fh["km"] - fa["km"]) / 1000.0, "tz": fh["tz"] - fa["tz"], "altitude": alt,
            "detail": {"home": fh, "away": fa}}


def context(league: str, store: dict | None = None, ratings: dict | None = None, injuries: dict | None = None,
            games: dict | None = None, teams: dict | None = None, prm: dict | None = None) -> dict:
    """Bundle what `predict` needs: ratings, schedule, injuries, parameters."""
    league = _league(league)
    games = games if games is not None else (store or {}).get("games") or {}
    teams = teams if teams is not None else (store or {}).get("teams") or {}
    return {"league": league, "ratings": ratings or {"teams": {}}, "schedule": Schedule(games, teams, league),
            "injuries": injuries or {}, "params": prm or params(league)}


def injury_adjustment(players: list | None, pace_g: float, league: str, replacement: float) -> float:
    """Points lost (negative) by a team missing `players` [{"impact" (per 100), "minutes"}]."""
    if not players:
        return 0.0
    reg_min = 40.0 if _league(league) == "wnba" else 48.0
    tot = 0.0
    for p in players:
        try:
            imp = float(p.get("impact") if isinstance(p, dict) else p[0])
            mins = float(p.get("minutes") if isinstance(p, dict) else p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (math.isfinite(imp) and math.isfinite(mins)):
            continue
        tot -= (imp - replacement) * min(mins, reg_min) / reg_min * pace_g / 100.0
    return tot


def predict(home: str, away: str, date: Any, ctx: dict) -> dict:
    """
    {"p_home","margin","sd","total","spread_fair","pts_home","pts_away",
     "detail": {"rating","hca","rest","b2b","travel","tz","altitude","injury","pace", "home": {...}, "away": {...}}}.

    ctx: from `context(...)`, or a plain dict with "league", "ratings" (fit_ratings output) and
    optionally "schedule", "injuries" ({team_id: [{"impact","minutes"}]}), "params", "neutral".
    """
    league = _league(ctx.get("league"))
    prm = ctx.get("params") or params(league)
    rt = ctx.get("ratings") or {}
    teams = rt.get("teams") or {}
    L = float(rt.get("league_ortg") or prm["ortg"])
    P = float(rt.get("league_pace") or prm["pace"])
    th = teams.get(str(home)) or {"off": L, "def": L, "net": 0.0, "pace": P}
    ta = teams.get(str(away)) or {"off": L, "def": L, "net": 0.0, "pace": P}
    neutral = bool(ctx.get("neutral", False))
    pace_g = float(th.get("pace", P)) + float(ta.get("pace", P)) - P
    rating = float(prm.get("rating_scale", 1.0)) * (float(th["net"]) - float(ta["net"])) * pace_g / 100.0
    f = features(str(home), str(away), date, ctx.get("schedule"), neutral, league)
    terms = {"hca": prm["hca"] * f["hca"], "b2b": prm["b2b"] * f["b2b"], "rest": prm["rest"] * f["rest"],
             "travel": prm["travel_1000km"] * f["travel_1000km"], "tz": prm["tz"] * f["tz"],
             "altitude": prm["altitude"] * f["altitude"]}
    inj = ctx.get("injuries") or {}
    rep = float(prm.get("replacement", -2.0))
    ih = injury_adjustment(inj.get(str(home)), pace_g, league, rep)
    ia = injury_adjustment(inj.get(str(away)), pace_g, league, rep)
    injury = ih - ia
    mu = rating + sum(terms.values()) + injury
    sd = float(prm["sigma"])
    ctx_part = mu - rating - terms["hca"]
    pts_h = (float(th["off"]) + float(ta["def"]) - L) * pace_g / 100 + terms["hca"] / 2 + ctx_part / 2
    pts_a = (float(ta["off"]) + float(th["def"]) - L) * pace_g / 100 - terms["hca"] / 2 - ctx_part / 2
    p = float(norm.cdf(mu / sd))
    raw_total = pts_h + pts_a
    post = 1.0 if str(ctx.get("stype") or "") == "post" else 0.0
    total = float(prm.get("total_a", 0.0)) + float(prm.get("total_b", 1.0)) * raw_total + float(prm.get("total_post", 0.0)) * post
    pts_h += (total - raw_total) / 2
    pts_a += (total - raw_total) / 2
    out = {"p_home": p, "margin": mu, "sd": sd, "total": total, "spread_fair": -mu,
           "pts_home": pts_h, "pts_away": pts_a, "total_raw": raw_total, "model": "base",
           "detail": {"rating": rating, **terms, "injury": injury, "injury_home": ih, "injury_away": ia,
                      "pace": pace_g, **f.get("detail", {})}}
    inf = ctx.get("informed")
    if inf:
        from oddsmarkets.basketball.models import informed as INF
        fit = ctx.get("informed_fit") or (INF.fitted(league) if INF.enabled(league) else None)
        if fit:
            out = _informed(out, INF.predict(inf, f, th, ta, L, P, neutral, ctx.get("stype"), fit), inf, fit, neutral)
    return out


def _informed(base: dict, r: dict, inp: dict, fit: dict, neutral: bool) -> dict:
    """The market-informed model's line (models/informed.py) in `predict`'s shape. The margin parts keep the base
    model's keys so the game page's breakdown still sums to the margin: "rating" = team ratings + market ratings
    (without the market's home edge), "hca" = home court (both models' home terms and the constants), "injury" =
    availability (expected rotation, injury-report Outs), the schedule terms as fitted."""
    t = r["terms"]
    b_mk = float(fit["spread"].get("mk_mu", 0.0))
    mk_home = b_mk * float(inp["mk_h"]) * (0.0 if neutral else 1.0)
    det = dict(base["detail"])
    det.update({"rating": t["rating"] + t["mk_mu"] - mk_home,
                "hca": t["hca"] + mk_home + float(fit["spread"].get("const", 0.0)) + float(fit["cal_c0"]),
                "b2b": t["b2b"], "rest": t["rest"], "travel": t["travel_1000km"], "tz": t["tz"], "altitude": t["altitude"],
                "injury": t["x_av"], "injury_home": None, "injury_away": None,
                "market_rating": t["mk_mu"], "team_rating": t["rating"], "availability": t["x_av"],
                "n_lines": inp.get("n_lines")})
    mu, sd = r["margin"], r["sd"]
    total = r.get("total", base["total"])
    return {**base, "p_home": r["p_home"], "margin": mu, "sd": sd, "spread_fair": -mu, "total": total,
            "pts_home": total / 2 + mu / 2, "pts_away": total / 2 - mu / 2, "model": "informed",
            "base": {"p_home": base["p_home"], "margin": base["margin"], "total": base["total"]}, "detail": det}


# ── walk-forward rows and fitting ────────────────────────────────────────────

def walk_forward(league: str, store: dict, prior: dict | None, refit_days: int = REFIT_DAYS,
                 stypes: Iterable[str] = G.COUNTED, half_life_days: float | None = None, ridge: float | None = None) -> list[dict]:
    """
    One row per finished game of a season with ratings fitted on games strictly before the
    game's refit window (weekly by default): {"id","day","home","away","neutral","margin","hs","as",
    "rating" (net diff x pace / 100, scale 1), "feat": {...}, "spread_home", "total_line", "total_model_base", "pace"}.
    """
    league = _league(league)
    games = store.get("games") or {}
    rows = G.finished(games, league, stypes=stypes)
    if not rows:
        return []
    sched = Schedule(games, store.get("teams") or {}, league)
    out = []
    start = rows[0]["day"]
    cur_fit, cur_until = None, None
    for r in rows:
        if cur_until is None or r["day"] >= cur_until:
            k = (r["day"] - start).days // refit_days
            win_start = start + timedelta(days=k * refit_days)
            cur_until = win_start + timedelta(days=refit_days)
            before = [x for x in rows if x["day"] < win_start]
            cur_fit = R.fit_ratings(before, through=win_start - timedelta(days=1), prior=prior, league=league,
                                    half_life_days=half_life_days, ridge=ridge, teams=R.league_teams(store))
        tm = cur_fit["teams"]
        L, P = cur_fit["league_ortg"], cur_fit["league_pace"]
        th = tm.get(r["home"]) or {"off": L, "def": L, "net": 0.0, "pace": P}
        ta = tm.get(r["away"]) or {"off": L, "def": L, "net": 0.0, "pace": P}
        pace_g = th["pace"] + ta["pace"] - P
        f = features(r["home"], r["away"], r["day"], sched, r["neutral"], league)
        out.append({"id": r["id"], "day": r["day"], "stype": r["stype"], "home": r["home"], "away": r["away"],
                    "neutral": r["neutral"], "margin": r["margin"], "hs": r["hs"], "as": r["as"],
                    "rating": (th["net"] - ta["net"]) * pace_g / 100.0,
                    "base_total": (th["off"] + ta["def"] - L + ta["off"] + th["def"] - L) * pace_g / 100.0,
                    "se": math.hypot(th.get("se_net", 3), ta.get("se_net", 3)) * pace_g / 100.0,
                    "feat": {k: f[k] for k in FEATURES}, "spread_home": r["spread_home"], "total_line": r["total"],
                    "pace": pace_g})
    return out


def fit_from_rows(rows: list[dict], league: str) -> dict:
    """Ridge regression (lambda 1, no intercept) of margin on [rating, hca, b2b, rest, travel, tz, altitude];
    sigma = residual sd. Fewer than 200 games: the defaults."""
    league = _league(league)
    d = dict(GAME_DEFAULTS[league])
    d["rating_scale"] = 1.0
    rows = [r for r in rows if r.get("margin") is not None]
    if len(rows) < 200:
        d["n"] = len(rows)
        d["fitted"] = False
        return d
    X = np.array([[r["rating"]] + [r["feat"][k] for k in FEATURES] for r in rows], float)
    y = np.array([r["margin"] for r in rows], float)
    cols = ["rating_scale", *FEATURES]
    keep = [j for j in range(X.shape[1]) if np.any(X[:, j] != 0)]
    Xk = X[:, keep]
    lam = np.eye(len(keep)) * 1.0
    beta = np.linalg.solve(Xk.T @ Xk + lam, Xk.T @ y)
    res = y - Xk @ beta
    for j, b in zip(keep, beta):
        d[cols[j]] = round(float(b), 4)
    d["sigma"] = round(float(np.sqrt(np.mean(res ** 2) * len(y) / max(1, len(y) - len(keep)))), 4)
    sp = np.array([r["spread_home"] for r in rows if r.get("spread_home") is not None], float)
    mg = np.array([r["margin"] for r in rows if r.get("spread_home") is not None], float)
    if len(sp) >= 100:
        d["sigma_market"] = round(float(np.sqrt(np.mean((mg + sp) ** 2))), 4)
    else:
        d["sigma_market"] = d["sigma"]
    d["n"] = int(len(y))
    d["n_market"] = int(len(sp))
    d.update(fit_total(rows))
    d["fitted"] = True
    return d


def fit_total(rows: list[dict]) -> dict:
    """Totals calibration: (hs + as) ~ total_a + total_b * base_total + total_post * [playoffs], least squares
    on walk-forward rows (a tiny ridge keeps total_post finite without playoff games). Identity below 200 rows."""
    rows = [r for r in rows if r.get("base_total") is not None and r.get("hs") is not None and r.get("as") is not None]
    if len(rows) < 200:
        return {"total_a": 0.0, "total_b": 1.0, "total_post": 0.0}
    X = np.array([[1.0, float(r["base_total"]), 1.0 if r.get("stype") == "post" else 0.0] for r in rows])
    y = np.array([float(r["hs"]) + float(r["as"]) for r in rows])
    P = np.diag([1e-8, 1e-8, 1.0])
    b = np.linalg.solve(X.T @ X + P, X.T @ y)
    res = y - X @ b
    return {"total_a": round(float(b[0]), 4), "total_b": round(float(b[1]), 5), "total_post": round(float(b[2]), 4),
            "sigma_total": round(float(np.sqrt(np.mean(res ** 2))), 4)}


def fit_params(league: str, seasons: Iterable[int] | None = None, write: bool = True, use_cache: bool = True) -> dict:
    """Fit the game-model coefficients and sigma on walk-forward history on disk (cached)."""
    league = _league(league)
    seasons = sorted(seasons) if seasons is not None else G.seasons_on_disk(league)
    sig = G.signature(league, seasons)
    path = G.cache_root() / "game" / f"params_{league}.json"
    if use_cache and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("signature") == sig and c.get("version") == VERSION:
                return c["result"]
        except (OSError, ValueError, KeyError):
            pass
    rows = []
    coef = R.fit_carryover(league, seasons)
    for s in seasons:
        st = G.load_store(league, s)
        if not st:
            continue
        prior = R.preseason_prior(league, s, coef=coef, teams=R.league_teams(st))
        rows += walk_forward(league, st, prior)
    res = fit_from_rows(rows, league)
    res["seasons"] = [int(s) for s in seasons]
    if write:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"signature": sig, "version": VERSION, "result": res}), encoding="utf-8")
        except OSError:
            pass
    _PARAMS.pop(league, None)
    return res


def for_season(league: str, season: int, through: Any = None, injuries: dict | None = None) -> dict:
    """A ready `context` for a season on disk: ratings as of `through`, schedule, injuries, parameters."""
    league = _league(league)
    st = G.load_store(league, season) or {}
    rt = R.for_season(league, season, through=through)
    return context(league, store=st, ratings=rt, injuries=injuries)
