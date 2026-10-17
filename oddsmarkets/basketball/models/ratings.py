"""
Possession-based team ratings: offence, defence, net and pace per 100 possessions.

Static fit (`fit_ratings`)
--------------------------
Every finished game gives two observations, one per offence:

    100 * pts_home / poss = mu + o_home + d_away + h/2 * [not neutral] + e
    100 * pts_away / poss = mu + o_away + d_home - h/2 * [not neutral] + e

where `poss` is the game's possession estimate (FGA - OREB + TOV + 0.44 FTA, averaged over
the two teams), `o_i` is team i's offence above average, `d_i` its defence (points *allowed*
above average, so lower is better) and `h` the home-court effect per 100 possessions on the
margin. Each observation is weighted

    w = 0.5 ** (age_days / half_life_days) * poss / mean_poss

and the team effects get a ridge penalty `ridge * sum (o_i - o_i^prior)^2 + (d_i - d_i^prior)^2`
(ridge is in games-equivalents: ridge = 8 means the prior counts like eight average games).
Without a prior the shrinkage is towards zero (the league mean). The system is solved as one
augmented sparse least-squares problem with `scipy.sparse.linalg.lsqr`. Reported:

    off_i = L + o_i - mean(o),  def_i = L + d_i - mean(d),  net_i = off_i - def_i,  L = league ORtg
    se_net_i from the posterior covariance s^2 (A'WA + P)^-1, s^2 the weighted residual variance.

Pace is a separate ridge fit of possessions per 48 minutes (per 40 in the WNBA):
`pace_game = P + p_home + p_away`, reported as `pace_i = P + p_i`.

Rating paths (`rating_paths`)
-----------------------------
A Kalman filter on the net rating vector (all teams jointly, full covariance):
state n_t ~ random walk with variance `q` per day; each game observes
`100 * margin / poss = n_home - n_away + h + e`, `var(e) = r`. The path is the filtered
estimate after each of a team's games, with its standard error.

Preseason prior (`preseason_prior`)
-----------------------------------
Last season's full-season net (and off/def/pace) regressed towards the mean:
`net_prior = b * net_last`, with `b` the least-squares slope of season-on-season net
ratings fitted on every pair of consecutive seasons on disk (default 0.65 below three pairs),
`se` the residual sd. An optional `roster_impact` ({team_id: summed minutes-weighted player
impact per 100}) is blended in: `net = (1 - blend) * b * net_last + blend * impact_centred`.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from typing import Any, Iterable

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models.config import GAME_DEFAULTS

logger = logging.getLogger(__name__)

HALF_LIFE = {"nba": 75.0, "wnba": 45.0}
RIDGE = {"nba": 8.0, "wnba": 6.0}
DEFAULT_B = 0.65
DEFAULT_SE = {"nba": 4.0, "wnba": 5.0}
EXPANSION_NET = -4.0
Q_PER_DAY = {"nba": 0.03, "wnba": 0.05}
VERSION = 2


def _league(league: str | None) -> str:
    return "wnba" if str(league or "").lower() == "wnba" else "nba"


def impute_poss(rows: list[dict], league: str) -> list[dict]:
    """Rows without a box score get possessions = mean pace of the rows that have one (scaled for
    overtime), so their scores still count; their pace stays None and is left out of the pace fit."""
    paces = [r["pace"] for r in rows if r.get("pace")]
    P = float(np.mean(paces)) if paces else GAME_DEFAULTS[_league(league)]["pace"]
    per = 600 if _league(league) == "wnba" else 720
    out = []
    for r in rows:
        if r.get("poss"):
            out.append(r)
        else:
            secs = 4 * per + 300 * max(0, int(r.get("periods") or 4) - 4)
            out.append({**r, "poss": P * secs / (4 * per), "pace": None, "poss_imputed": True})
    return out


def _rows(games, league, through, stypes):
    if isinstance(games, list) and games and isinstance(games[0], dict) and "margin" in games[0]:
        rows = [r for r in games if not through or r["day"] <= G.day(through)]
    else:
        rows = G.finished(games or {}, league, stypes=stypes, through=through)
    return rows


def fit_ratings(games, through: Any = None, half_life_days: float | None = None, ridge: float | None = None,
                prior: dict | None = None, league: str = "nba", stypes: Iterable[str] = G.COUNTED,
                teams: Iterable[str] | None = None) -> dict:
    """
    {"teams": {tid: {"off","def","net","pace","se_net","games"}}, "hca", "hca_pts", "league_ortg", "league_pace",
     "n_games", "through", "resid_sd"}.

    `games`: {id: GAME} or a list of GAME dicts (several seasons may be merged), or rows from
    `_games.finished`. `through`: last day included (None = all). `prior`: a `preseason_prior` result.
    """
    league = _league(league)
    hl = float(half_life_days if half_life_days is not None else HALF_LIFE[league])
    lam = float(ridge if ridge is not None else RIDGE[league])
    rows = impute_poss(_rows(games, league, through, stypes), league)
    pteams = (prior or {}).get("teams") or {}
    tids = sorted({r["home"] for r in rows} | {r["away"] for r in rows} | set(pteams) | set(teams or []))
    dflt = GAME_DEFAULTS[league]
    if not tids:
        return {"teams": {}, "hca": 0.0, "hca_pts": 0.0, "league_ortg": dflt["ortg"], "league_pace": dflt["pace"],
                "n_games": 0, "through": str(through) if through else None, "resid_sd": None}
    idx = {t: i for i, t in enumerate(tids)}
    T = len(tids)
    L0 = float((prior or {}).get("league_ortg") or dflt["ortg"])
    P0 = float((prior or {}).get("league_pace") or dflt["pace"])
    if not rows:
        return _from_prior(prior, tids, L0, P0, through)

    ref = G.day(through) or max(r["day"] for r in rows)
    age = np.array([(ref - r["day"]).days for r in rows], float)
    poss = np.array([r["poss"] for r in rows], float)
    wg = 0.5 ** (np.maximum(age, 0) / hl) * poss / poss.mean()
    n = len(rows)
    hi = np.array([idx[r["home"]] for r in rows])
    ai = np.array([idx[r["away"]] for r in rows])
    neutral = np.array([r["neutral"] for r in rows], bool)
    hs = np.array([r["hs"] for r in rows], float)
    as_ = np.array([r["as"] for r in rows], float)
    y = np.concatenate([100 * hs / poss, 100 * as_ / poss])
    w = np.concatenate([wg, wg])
    # params: [mu, h, o_0..o_{T-1}, d_0..d_{T-1}]
    p = 2 + 2 * T
    r_ = np.arange(2 * n)
    hsgn = np.where(neutral, 0.0, 0.5)
    off_t = np.concatenate([hi, ai])
    def_t = np.concatenate([ai, hi])
    rows_i = np.concatenate([r_, r_, r_, r_])
    cols_i = np.concatenate([np.zeros(2 * n, int), np.ones(2 * n, int), 2 + off_t, 2 + T + def_t])
    vals = np.concatenate([np.ones(2 * n), np.concatenate([hsgn, -hsgn]), np.ones(2 * n), np.ones(2 * n)])
    A = sp.csr_matrix((vals, (rows_i, cols_i)), shape=(2 * n, p))
    # prior targets for o, d
    o_pr = np.zeros(T)
    d_pr = np.zeros(T)
    for t, i in idx.items():
        pt = pteams.get(t)
        if pt:
            o_pr[i] = float(pt.get("off", L0)) - L0
            d_pr[i] = float(pt.get("def", L0)) - L0
    sw = np.sqrt(w)
    Aw = sp.diags(sw) @ A
    yw = sw * y
    pen_rows = sp.hstack([sp.csr_matrix((2 * T, 2)), sp.identity(2 * T) * math.sqrt(lam)]).tocsr()
    # a weak ridge on h keeps it finite when every game is neutral
    h_row = sp.csr_matrix(([0.05], ([0], [1])), shape=(1, p))
    Ab = sp.vstack([Aw, pen_rows, h_row]).tocsr()
    yb = np.concatenate([yw, math.sqrt(lam) * np.concatenate([o_pr, d_pr]), [0.0]])
    x0 = np.concatenate([[L0, 3.0], o_pr, d_pr])
    sol = lsqr(Ab, yb - Ab @ x0, atol=1e-10, btol=1e-10, iter_lim=5000)[0] + x0
    mu, h = sol[0], sol[1]
    o, d = sol[2:2 + T], sol[2 + T:]
    resid = y - A @ sol
    s2 = float(np.sum(w * resid ** 2) / max(1.0, w.sum() - p * 0.5))
    # posterior covariance (dense: p is ~62)
    Ad = A.toarray()
    H = (Ad * w[:, None]).T @ Ad
    H[2:, 2:] += lam * np.eye(2 * T)
    H[1, 1] += 0.0025
    H[0, 0] += 1e-6
    try:
        cov = np.linalg.inv(H) * s2
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(H) * s2
    om, dm = o.mean(), d.mean()
    L = mu + om + dm
    # pace
    has = np.array([r["pace"] is not None for r in rows], bool)
    np_ = int(has.sum())
    pace = np.array([r["pace"] for r in rows if r["pace"] is not None], float)
    Pa = sp.csr_matrix((np.ones(2 * np_), (np.concatenate([np.arange(np_)] * 2), np.concatenate([hi[has], ai[has]]))),
                       shape=(np_, T))
    Pa = sp.hstack([sp.csr_matrix(np.ones((np_, 1))), Pa]).tocsr()
    pp_pr = np.zeros(T)
    for t, i in idx.items():
        pt = pteams.get(t)
        if pt and pt.get("pace") is not None:
            pp_pr[i] = float(pt["pace"]) - P0
    sg = np.sqrt(wg[has])
    Pb = sp.vstack([sp.diags(sg) @ Pa, sp.hstack([sp.csr_matrix((T, 1)), sp.identity(T) * math.sqrt(lam)])]).tocsr()
    pb = np.concatenate([sg * pace, math.sqrt(lam) * pp_pr])
    px0 = np.concatenate([[P0], pp_pr])
    psol = lsqr(Pb, pb - Pb @ px0, atol=1e-10, btol=1e-10, iter_lim=5000)[0] + px0
    Pm = psol[0] + 2 * psol[1:].mean()
    pc = psol[1:] - psol[1:].mean()
    league_pace = float(Pm)
    counts = np.bincount(np.concatenate([hi, ai]), minlength=T)
    out = {}
    # contrast for the centred net: (o_i - mean o) - (d_i - mean d)
    V = np.zeros((T, p))
    V[:, 2:2 + T] = np.eye(T) - 1.0 / T
    V[:, 2 + T:] = -(np.eye(T) - 1.0 / T)
    net_var = np.einsum("ij,jk,ik->i", V, cov, V)
    for t, i in idx.items():
        var = net_var[i]
        out[t] = {"off": float(L + o[i] - om), "def": float(L + d[i] - dm), "net": float((o[i] - om) - (d[i] - dm)),
                  "pace": float(league_pace + pc[i]), "se_net": float(math.sqrt(max(var, 1e-9))), "games": int(counts[i])}
    return {"teams": out, "hca": float(h), "hca_pts": float(h * league_pace / 100.0), "league_ortg": float(L),
            "league_pace": league_pace, "n_games": n, "through": str(ref), "resid_sd": float(math.sqrt(s2))}


def _from_prior(prior, tids, L0, P0, through):
    pt = (prior or {}).get("teams") or {}
    out = {}
    for t in tids:
        p = pt.get(t) or {}
        net = float(p.get("net", EXPANSION_NET if pt else 0.0))
        out[t] = {"off": float(p.get("off", L0 + net / 2)), "def": float(p.get("def", L0 - net / 2)), "net": net,
                  "pace": float(p.get("pace", P0)), "se_net": float(p.get("se_net", 4.0)), "games": 0}
    return {"teams": out, "hca": float((prior or {}).get("hca", 3.0)), "hca_pts": float((prior or {}).get("hca", 3.0)) * P0 / 100,
            "league_ortg": L0, "league_pace": P0, "n_games": 0, "through": str(through) if through else None,
            "resid_sd": None}


# ── Kalman paths ─────────────────────────────────────────────────────────────

def rating_paths(games, league: str = "nba", prior: dict | None = None, hca: float | None = None,
                 q_per_day: float | None = None, r: float | None = None, through: Any = None,
                 stypes: Iterable[str] = G.COUNTED) -> dict[str, list[dict]]:
    """{tid: [{"date","game","net","se"}]}: the filtered net rating after each of the team's games."""
    league = _league(league)
    rows = impute_poss(_rows(games, league, through, stypes), league)
    pt = (prior or {}).get("teams") or {}
    tids = sorted({x["home"] for x in rows} | {x["away"] for x in rows} | set(pt))
    if not tids:
        return {}
    idx = {t: i for i, t in enumerate(tids)}
    T = len(tids)
    q = float(q_per_day if q_per_day is not None else Q_PER_DAY[league])
    m = np.array([float((pt.get(t) or {}).get("net", 0.0)) for t in tids])
    P = np.diag([float((pt.get(t) or {}).get("se_net", 5.0)) ** 2 for t in tids])
    if hca is None:
        hca = fit_ratings(rows, league=league, half_life_days=1e6, ridge=4.0)["hca"] if rows else 3.0
    if r is None:
        dif = [100 * x["margin"] / x["poss"] for x in rows]
        r = float(np.var(dif)) * 0.8 if len(dif) > 30 else 160.0
    out: dict[str, list[dict]] = {t: [] for t in tids}
    last = None
    for x in rows:
        if last is not None:
            dt = (x["day"] - last).days
            if dt > 0:
                P = P + np.eye(T) * q * min(dt, 60)
        last = x["day"]
        i, j = idx[x["home"]], idx[x["away"]]
        y = 100 * x["margin"] / x["poss"] - (0.0 if x["neutral"] else hca)
        pred = m[i] - m[j]
        Ph = P[:, i] - P[:, j]
        S = Ph[i] - Ph[j] + r
        K = Ph / S
        m = m + K * (y - pred)
        P = P - np.outer(K, Ph)
        for t, k in ((x["home"], i), (x["away"], j)):
            out[t].append({"date": str(x["day"]), "game": x["id"], "net": round(float(m[k]), 3),
                           "se": round(float(math.sqrt(max(P[k, k], 1e-9))), 3)})
    return out


# ── preseason prior ──────────────────────────────────────────────────────────

def season_end_ratings(league: str, season: int, store: dict | None = None) -> dict | None:
    """Full-season (no decay, light ridge) ratings for a season on disk, or None."""
    st = store if store is not None else G.load_store(league, season)
    if not st:
        return None
    rows = G.finished(st.get("games") or {}, league, stypes=G.COUNTED)
    if len(rows) < 30:
        return None
    return fit_ratings(rows, league=league, half_life_days=1e6, ridge=2.0)


def fit_carryover(league: str, seasons: Iterable[int] | None = None, use_cache: bool = True) -> dict:
    """Season-on-season regression slope b (net_s = b * net_{s-1}) and residual sd, fitted on disk history."""
    league = _league(league)
    seasons = sorted(seasons) if seasons is not None else G.seasons_on_disk(league)
    sig = G.signature(league, seasons)
    path = G.cache_root() / "ratings" / f"carryover_{league}.json"
    if use_cache and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("signature") == sig and c.get("version") == VERSION:
                return c["result"]
        except (OSError, ValueError, KeyError):
            pass
    ends = {s: season_end_ratings(league, s) for s in seasons}
    xs, ys, px, py = [], [], [], []
    for s in seasons:
        a, b = ends.get(s - 1), ends.get(s)
        if not a or not b:
            continue
        for t, v in b["teams"].items():
            u = a["teams"].get(t)
            if u and v["games"] >= 20 and u["games"] >= 20:
                xs.append(u["net"]); ys.append(v["net"])
                px.append(u["pace"] - a["league_pace"]); py.append(v["pace"] - b["league_pace"])
    res = {"b": DEFAULT_B, "se": DEFAULT_SE[league], "b_pace": 0.6, "pairs": len(xs), "fitted": False}
    if len(xs) >= 40:
        x, y = np.array(xs), np.array(ys)
        bb = float(x @ y / (x @ x))
        res.update({"b": round(bb, 4), "se": round(float(np.sqrt(np.mean((y - bb * x) ** 2))), 3), "fitted": True})
        x, y = np.array(px), np.array(py)
        if x @ x > 0:
            res["b_pace"] = round(float(x @ y / (x @ x)), 4)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"signature": sig, "version": VERSION, "result": res}), encoding="utf-8")
    except OSError:
        pass
    return res


def preseason_prior(league: str, season: int, roster_impact: dict[str, float] | None = None, blend: float = 0.5,
                    last: dict | None = None, teams: Iterable[str] | None = None, coef: dict | None = None) -> dict:
    """
    {"teams": {tid: {"off","def","net","pace","se_net"}}, "league_ortg", "league_pace", "hca", "coef", "source"}.

    `last` (a fit_ratings result for season-1) and `coef` ({"b","se","b_pace"}) bypass the disk (tests).
    `teams` lists the season's teams (else the store's, else last season's).
    """
    league = _league(league)
    if last is None:
        last = season_end_ratings(league, int(season) - 1)
    if coef is None:
        coef = fit_carryover(league)
    b, se, bp = float(coef.get("b", DEFAULT_B)), float(coef.get("se", DEFAULT_SE[league])), float(coef.get("b_pace", 0.6))
    dflt = GAME_DEFAULTS[league]
    if teams is None:
        st = G.load_store(league, season)
        teams = (league_teams(st) if st else []) or list((last or {}).get("teams") or {})
    teams = list(teams)
    L = float((last or {}).get("league_ortg") or dflt["ortg"])
    P = float((last or {}).get("league_pace") or dflt["pace"])
    lt = (last or {}).get("teams") or {}
    imp = None
    if roster_impact:
        vals = [float(v) for t, v in roster_impact.items() if t in teams and v is not None]
        mean = float(np.mean(vals)) if vals else 0.0
        imp = {t: float(v) - mean for t, v in roster_impact.items() if v is not None}
    out = {}
    for t in teams:
        u = lt.get(t)
        if u:
            net = b * u["net"]
            off_dev = b * (u["off"] - L)
            def_dev = b * (u["def"] - L)
            pace = P + bp * (u["pace"] - P)
            s = se
        else:
            net, off_dev, def_dev, pace, s = EXPANSION_NET, EXPANSION_NET / 2, -EXPANSION_NET / 2, P, se * 1.25
        if imp is not None and t in imp:
            new = (1 - blend) * net + blend * imp[t]
            shift = new - net
            off_dev += shift / 2
            def_dev -= shift / 2
            net = new
            s = s * math.sqrt(1 - blend * 0.5)
        out[t] = {"off": L + off_dev, "def": L + def_dev, "net": net, "pace": pace, "se_net": s}
    return {"teams": out, "league_ortg": L, "league_pace": P, "hca": float((last or {}).get("hca", 3.0)),
            "coef": {"b": b, "se": se, "b_pace": bp, "blend": blend if imp is not None else 0.0},
            "source": "last_season" if last else "none"}


# ── cached loader ────────────────────────────────────────────────────────────

def league_teams(store: dict) -> list[str]:
    """Teams that play regular-season, play-in or playoff games (not exhibition opponents or "TBD")."""
    out = set()
    for g in (store.get("games") or {}).values():
        if (g or {}).get("stype") in ("reg", "playin", "post", "cup") and g.get("home") and g.get("away"):
            out.add(str(g["home"]))
            out.add(str(g["away"]))
    tdict = store.get("teams") or {}
    out = {t for t in out if (tdict.get(t) or {}).get("abbr") not in ("TBD", None) or t not in tdict}
    return sorted(out) or sorted(tdict)


# Leagues whose current season's prior uses today's rosters by default. Switched off on 1 October 2026 because
# it widened the gap to the Kalshi NBA 2026-27 win totals (one season, judged against a market, not outcomes);
# switched on 2 October 2026 after a walk-forward test on OUTCOMES (docs/research/basketball_edge.md): with each
# season's preseason rosters in `meta.rosters`, this prior's RMSE against the actual season net rating is
# NBA 3.60 against 3.75 for last season alone (2012-2026, better in 11 of 15 seasons) and WNBA 4.89 against 5.20
# (2010-2026, 10 of 16). `for_season(..., roster=False)` turns it off for one call.
ROSTER_PRIOR_LEAGUES: tuple[str, ...] = ("nba", "wnba")


def _allocate_minutes(minutes: dict[str, float], cap: float) -> dict[str, float]:
    """Hand out `cap` team minutes to the players with the most projected minutes first (a deep roster's
    13th man gets none, rather than every player being scaled down)."""
    out, left = {}, cap
    for p, m in sorted(minutes.items(), key=lambda kv: -kv[1]):
        take = max(0.0, min(float(m), left))
        out[p] = take
        left -= take
    return out


def _player_values(impact: dict | None) -> dict[str, list[float]]:
    """{pid: [projected HPM for next season, projected minutes]} from an impact.for_season result."""
    if not (impact or {}).get("ok"):
        return {}
    out = {}
    for pid, rec in (impact.get("players") or {}).items():
        pj = (rec or {}).get("proj") or {}
        h = pj.get("hpm_next")
        if h is None:
            h = rec.get("t")
        if h is not None and pj.get("min"):
            out[str(pid)] = [float(h), float(pj["min"])]
    return out


def _last_season_values(league: str, season: int) -> dict[str, list[float]]:
    """`_player_values` for a finished season, cached on the content of that season's store and stints
    (not file times, which a CI checkout resets), so the hourly build does not refit last season's impact
    model whenever the current season's files change."""
    import hashlib
    from oddsmarkets.basketball import store as stmod
    from oddsmarkets.basketball.models import _io
    from oddsmarkets.basketball.models import impact as IM
    h = hashlib.sha1()
    from oddsmarkets.basketball.analytics import bio as _bio
    for p in (G.store_path(league, season), stmod.table_path(league, season, "stints.json"), _bio.bio_path(league)):
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(b"missing")
    key = json.dumps([VERSION, "roster-values-2", h.hexdigest()])
    return _io.cached("ratings", f"roster_values_{league}_{season}", key,
                      lambda: _player_values(IM.for_season(league, season))) or {}


def roster_prior_impact(league: str, season: int, store: dict | None = None, impact: dict | None = None) -> dict | None:
    """{team_id: roster HPM per 100} for the season's current rosters: each rostered player's HPM projected
    to this season (last season's HPM plus the aging step, `impact.projections` "hpm_next") times his
    projected minutes, the shortfall to five players' minutes at replacement (`impact.roster_impact`).
    Rosters are the store's `meta.rosters` (scripts/bb_fetch.py rosters phase), so summer moves count.
    None without rosters or without last season's impact model. `impact` (an impact.for_season result for
    season-1) bypasses the disk (tests)."""
    from oddsmarkets.basketball.models import _io
    from oddsmarkets.basketball.models import impact as IM
    league = _league(league)
    st = store if store is not None else G.load_store(league, season)
    rosters = ((st or {}).get("meta") or {}).get("rosters") or {}
    if not rosters:
        return None
    if impact is not None:
        per = _player_values(impact)
    else:
        per = _last_season_values(league, int(season) - 1)
        if per:
            # a player who missed last season (injury) counts at his season-before-last values
            older = _last_season_values(league, int(season) - 2) if G.load_store(league, int(season) - 2) else {}
            per = {**older, **per}
    if not per:
        return None
    cap = 5.0 * _io.game_minutes(league)
    out = {}
    for tid, pids in rosters.items():
        vals, mins = {}, {}
        for p in pids:
            v = per.get(str(p))
            if not v:
                continue                               # rookies and players without last-season minutes: replacement
            vals[str(p)] = float(v[0])
            mins[str(p)] = float(v[1])
        if not vals:
            continue
        out[str(tid)] = float(IM.roster_impact(vals, _allocate_minutes(mins, cap), league)["net"])
    return out or None


def for_season(league: str, season: int, through: Any = None, roster_impact: dict | None = None,
               use_cache: bool = True, roster: bool | None = None) -> dict:
    """Ratings for a season on disk as of `through` (inclusive), with the preseason prior and paths.
    `roster` (default: the current season of a ROSTER_PRIOR_LEAGUES league) blends today's rosters'
    projected impact into the preseason prior (`roster_prior_impact`) unless `roster_impact` is given."""
    league = _league(league)
    st = G.load_store(league, season) or {}
    if roster_impact is None:
        if roster is None:
            from oddsmarkets.basketball import canon
            roster = league in ROSTER_PRIOR_LEAGUES and int(season) == canon.current_season(league)
        if roster:
            try:
                roster_impact = roster_prior_impact(league, season, store=st)
            except Exception as exc:                  # noqa: BLE001  never let the roster prior break ratings
                logger.warning("%s %s roster prior failed: %s", league, season, exc)
                roster_impact = None
    sig = G.signature(league, [season - 1, season])
    rkey = sorted((t, round(v, 3)) for t, v in roster_impact.items()) if roster_impact else None
    key = json.dumps([VERSION, sig, str(through), rkey])
    path = G.cache_root() / "ratings" / f"{league}_{season}_{through or 'latest'}.json"
    if use_cache and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("key") == key:
                return c["result"]
        except (OSError, ValueError, KeyError):
            pass
    games = st.get("games") or {}
    playing = league_teams(st)
    prior = preseason_prior(league, season, roster_impact=roster_impact, teams=playing or None)
    fit = fit_ratings(games, through=through, prior=prior, league=league, teams=playing)
    fit["prior"] = prior
    fit["paths"] = rating_paths(games, league=league, prior=prior, hca=fit["hca"], through=through)
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"key": key, "result": fit}, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
    return fit
