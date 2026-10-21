"""
Walk-forward backtest of the game model and the season simulation.

Games
-----
For every finished regular-season, Cup, play-in and playoff game of the chosen seasons:

* ``model``: the game model with ratings refitted weekly from games strictly before the week
  (`game.walk_forward`, preseason prior from the previous season) and coefficients / sigma
  fitted on the *earlier* seasons only (`game.fit_from_rows`; defaults for the first season). In a league that
  uses the market-informed model (`informed.INFORMED_LEAGUES`) it is that model wherever it applies (daily
  ratings, market ratings from earlier games' closing lines, availability; its walk-forward fit for the season,
  `informed_<L>.json` "wf"); ``model_base`` is the base model on every game.
* ``model_ratings_only``: the same ratings with home court only (no rest / travel / altitude).
* ``elo``: the pregame Elo probability (`elo.history`).
* ``market``: the DraftKings closing spread from ESPN pickcenter, p = Phi(-spread_home / sigma_m),
  sigma_m fitted on earlier seasons (sd of margin + spread); only games with a line.
* ``espn``: ESPN's pregame predictor where the store carries one (GAME["predictor"]["home"]).

Scores: log-loss -mean(y ln p + (1-y) ln(1-p)) (p clipped to [1e-4, 1-1e-4]), Brier mean((p-y)^2),
reliability in 10 equal-width bins, and the margin RMSE of model / Elo / market point spreads.
Every model is also scored on the games that have a market line ("vs_market"), so the model and
the market are compared on identical games.

Season simulation
-----------------
At fixed checkpoints of each completed season (opening day and 25 / 50 / 75 % of the regular
season by date) the season is simulated with ratings fitted through the checkpoint (2,000 sims)
and the forecasts are scored against what happened: playoffs (appeared in a playoff game),
finals (appeared in the last playoff game) and title (won the last playoff game).

Results go to <cache>/backtest_<league>.json.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import numpy as np
from scipy.stats import norm

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import elo as E
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models import season_sim as SS

logger = logging.getLogger(__name__)
EPS = 1e-4
CHECKPOINTS = (0.0, 0.25, 0.5, 0.75)


def score(rows: list[tuple[float, int]]) -> dict:
    """{"n","logloss","brier","base_rate","reliability": [{"lo","hi","n","mean_p","freq"}]}"""
    if not rows:
        return {"n": 0}
    p = np.clip(np.array([a for a, _ in rows], float), EPS, 1 - EPS)
    y = np.array([b for _, b in rows], float)
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    bins = []
    edges = np.linspace(0, 1, 11)
    for i in range(10):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < 9 else (p <= 1))
        if m.any():
            bins.append({"lo": round(edges[i], 1), "hi": round(edges[i + 1], 1), "n": int(m.sum()),
                         "mean_p": round(float(p[m].mean()), 4), "freq": round(float(y[m].mean()), 4)})
    return {"n": int(len(p)), "logloss": round(ll, 5), "brier": round(br, 5), "base_rate": round(float(y.mean()), 4),
            "reliability": bins}


def _rmse(pairs):
    if not pairs:
        return None
    a = np.array(pairs, float)
    return round(float(np.sqrt(np.mean((a[:, 0] - a[:, 1]) ** 2))), 4)


def _mu(row: dict, prm: dict, ratings_only: bool = False) -> float:
    f = row["feat"]
    mu = prm.get("rating_scale", 1.0) * row["rating"] + prm["hca"] * f["hca"]
    if not ratings_only:
        mu += prm["b2b"] * f["b2b"] + prm["rest"] * f["rest"] + prm["travel_1000km"] * f["travel_1000km"] + \
            prm["tz"] * f["tz"] + prm["altitude"] * f["altitude"]
    return mu


def season_outcomes(store: dict) -> dict:
    """{"playoffs": set, "finalists": set, "champion": tid|None} from the store's playoff games."""
    allpost = [g for g in (store.get("games") or {}).values() if (g or {}).get("stype") == "post"]
    if any(g.get("status") in ("pre", "in", "postponed") for g in allpost):
        return {"playoffs": set(), "finalists": set(), "champion": None}       # postseason not finished
    post = [g for g in allpost if g.get("status") == "post" and g.get("hs") is not None]
    if not post:
        return {"playoffs": set(), "finalists": set(), "champion": None}
    post.sort(key=lambda g: str(g.get("date")))
    last = post[-1]
    champ = str(last["home"]) if int(last["hs"]) > int(last["as"]) else str(last["away"])
    teams = {str(g["home"]) for g in post} | {str(g["away"]) for g in post}
    return {"playoffs": teams, "finalists": {str(last["home"]), str(last["away"])}, "champion": champ}


def _odds_cache_lines(league: str, season: int, store: dict) -> dict:
    """Closing lines for the market-informed model's history: the store's, filled from the local ESPN line cache
    (scripts/bb_odds_history.py; absent on CI) where the store has none (the NBA 2024 and 2025 stores carry no lines)."""
    from oddsmarkets.basketball.models import informed as INF
    out = INF.store_lines(store.get("games") or {})
    try:
        from oddsmarkets.basketball.research import lines as LN
        cache = LN.game_lines(league, season)
    except Exception:  # noqa: BLE001
        cache = {}
    for gid, v in cache.items():
        c = v.get("close") or {}
        if c.get("sp_h") is not None or c.get("tot") is not None:
            cur = out.get(str(gid)) or {}
            out[str(gid)] = {"sp": c.get("sp_h") if c.get("sp_h") is not None else cur.get("sp"),
                             "tot": c.get("tot") if c.get("tot") is not None else cur.get("tot")}
    return out


def informed_season(league: str, season: int, store: dict, prior: dict, prm: dict, fit: dict) -> dict[str, dict]:
    """{game_id: game.predict output} of the market-informed model for every finished game of a season, as the site
    would have shown it before tip-off: daily ratings through the day before, inputs from games of earlier days, the
    walk-forward fit `fit` (seasons before this one only)."""
    from oddsmarkets.basketball.models import informed as INF
    lines_for = lambda s, st: _odds_cache_lines(league, s, st)  # noqa: E731
    si = INF.season_inputs(league, season, store, lines=lines_for(season, store),
                           prior=INF.season_market_prior(league, season, lines_for=lines_for), live=False)
    games = store.get("games") or {}
    sched = GM.Schedule(games, store.get("teams") or {}, league)
    teams = R.league_teams(store)
    fits: dict = {}
    out = {}
    for r in G.finished(games, league):
        inp = INF.inputs_for_game(si, r["day"], r["home"], r["away"])
        if inp is None:
            continue
        if r["day"] not in fits:
            fits[r["day"]] = R.fit_ratings(games, through=r["day"] - timedelta(days=1), prior=prior, league=league, teams=teams)
        ctx = {"league": league, "ratings": fits[r["day"]], "schedule": sched, "params": prm, "neutral": r["neutral"],
               "stype": r["stype"], "informed": inp, "informed_fit": fit}
        out[r["id"]] = GM.predict(r["home"], r["away"], r["day"], ctx)
    return out


def backtest(league: str = "nba", seasons: Iterable[int] | None = None, refit_days: int = GM.REFIT_DAYS,
             write: bool = True, season_sims: int = 2000, checkpoints: Iterable[float] = CHECKPOINTS,
             stores: dict[int, dict] | None = None, seed: int = 0, informed: bool | None = None) -> dict:
    """Walk-forward backtest (module docstring). `stores` ({season: store}) bypasses the disk (tests). `informed`
    (default: on for an INFORMED_LEAGUES league read from disk) scores the market-informed model as "model" wherever
    it applies, with its walk-forward fit for the season (`informed_<L>.json` "wf"); "model_base" keeps the base
    model on every game."""
    t0 = time.perf_counter()
    league = "wnba" if str(league).lower() == "wnba" else "nba"
    from oddsmarkets.basketball.models import informed as INF
    if informed is None:
        informed = stores is None and INF.enabled(league)
    inf_wf = ((INF.fitted(league) or {}).get("wf") or {}) if informed else {}
    if stores is None:
        on_disk = G.seasons_on_disk(league)
        seasons = sorted(seasons) if seasons is not None else on_disk
        stores = G.all_games(league, [s for s in on_disk if s <= max(seasons or [0])])
    else:
        seasons = sorted(seasons) if seasons is not None else sorted(stores)
    all_seasons = sorted(stores)
    hist = E.history(league, stores=stores)
    elo_p = E.pregame(hist)
    # carry-over coefficient from the stores at hand
    ends = {s: R.fit_ratings(G.finished(stores[s].get("games") or {}, league), league=league, half_life_days=1e6, ridge=2.0)
            for s in all_seasons}
    xs, ys = [], []
    for s in all_seasons:
        a, b = ends.get(s - 1), ends.get(s)
        if a and b:
            for t, v in b["teams"].items():
                if t in a["teams"] and v["games"] >= 10 and a["teams"][t]["games"] >= 10:
                    xs.append(a["teams"][t]["net"]); ys.append(v["net"])
    coef = {"b": R.DEFAULT_B, "se": R.DEFAULT_SE[league], "b_pace": 0.6}
    if len(xs) >= 40:
        x, y = np.array(xs), np.array(ys)
        bb = float(x @ y / (x @ x))
        coef.update({"b": bb, "se": float(np.sqrt(np.mean((y - bb * x) ** 2)))})
    wf: dict[int, list[dict]] = {}
    for s in all_seasons:
        last = ends.get(s - 1) if ends.get(s - 1) and ends[s - 1]["n_games"] >= 30 else None
        prior = R.preseason_prior(league, s, last=last, coef=coef, teams=R.league_teams(stores[s]))
        wf[s] = GM.walk_forward(league, stores[s], prior, refit_days=refit_days)
        for r in wf[s]:
            g = (stores[s].get("games") or {}).get(r["id"]) or {}
            pr = g.get("predictor") or {}
            r["espn"] = pr.get("home") if isinstance(pr, dict) else None
    rows: dict[str, list] = {}
    vs_mkt: dict[str, list] = {}
    rm: dict[str, list] = {}
    per_season = {}
    params_used = {}
    for s in seasons:
        if s not in wf:
            continue
        earlier = [r for ss in all_seasons if ss < s for r in wf[ss]]
        prm = GM.fit_from_rows(earlier, league)
        params_used[str(s)] = {k: prm.get(k) for k in ("rating_scale", "hca", "b2b", "rest", "travel_1000km", "tz",
                                                         "altitude", "sigma", "sigma_market", "n", "fitted")}
        srows: dict[str, list] = {}
        inf_pred: dict[str, dict] = {}
        if inf_wf.get(str(s)):
            last = ends.get(s - 1) if ends.get(s - 1) and ends[s - 1]["n_games"] >= 30 else None
            prior = R.preseason_prior(league, s, last=last, coef=coef, teams=R.league_teams(stores[s]))
            try:
                inf_pred = informed_season(league, s, stores[s], prior, prm, {"version": INF.VERSION, **inf_wf[str(s)]})
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s %s informed model failed: %s", league, s, exc)
            params_used[str(s)]["informed_games"] = len(inf_pred)
        for r in wf[s]:
            y = int(r["margin"] > 0)
            mu = _mu(r, prm)
            base_p = float(norm.cdf(mu / prm["sigma"]))
            preds = {"model": base_p, "model_base": base_p,
                     "model_ratings_only": float(norm.cdf(_mu(r, prm, True) / prm["sigma"]))}
            ip = inf_pred.get(r["id"])
            if ip and ip.get("model") == "informed":
                preds["model"] = float(ip["p_home"])
                mu = float(ip["margin"])
            if r["id"] in elo_p:
                preds["elo"] = float(elo_p[r["id"]])
            mk = GM.spread_to_p(r["spread_home"], league, sd=prm.get("sigma_market") or prm["sigma"])
            if mk is not None:
                preds["market"] = mk
            if r.get("espn") is not None:
                try:
                    e = float(r["espn"])
                    preds["espn"] = e / 100.0 if e > 1 else e
                except (TypeError, ValueError):
                    pass
            for k, p in preds.items():
                rows.setdefault(k, []).append((p, y))
                srows.setdefault(k, []).append((p, y))
                if mk is not None:
                    vs_mkt.setdefault(k, []).append((p, y))
            rm.setdefault("model", []).append((mu, r["margin"]))
            if r["id"] in elo_p:
                ep = min(max(elo_p[r["id"]], 1e-6), 1 - 1e-6)
                rm.setdefault("elo", []).append((-math.log10(1 / ep - 1) * 400 * hist["params"]["pts_per_elo"], r["margin"]))
            if r["spread_home"] is not None:
                rm.setdefault("market", []).append((-float(r["spread_home"]), r["margin"]))
                rm.setdefault("model_on_market_games", []).append((mu, r["margin"]))
        per_season[str(s)] = {k: {kk: vv for kk, vv in score(v).items() if kk != "reliability"} for k, v in srows.items()}
    metrics = {k: score(v) for k, v in rows.items()}
    metrics_vs_market = {k: {kk: vv for kk, vv in score(v).items() if kk != "reliability"} for k, v in vs_mkt.items()}
    margin_rmse = {k: _rmse(v) for k, v in rm.items()}
    # season simulation calibration
    sims = {"playoffs": [], "finals": [], "title": []}
    sim_runs = []
    for s in seasons:
        st = stores.get(s)
        if not st or season_sims <= 0:
            continue
        out = season_outcomes(st)
        if not out["champion"]:
            continue
        reg = sorted(r["day"] for r in G.finished(st.get("games") or {}, league, stypes=G.STANDINGS))
        if len(reg) < 50:
            continue
        first, last_d = reg[0], reg[-1]
        last = ends.get(s - 1) if ends.get(s - 1) and ends[s - 1]["n_games"] >= 30 else None
        prior = R.preseason_prior(league, s, last=last, coef=coef, teams=R.league_teams(st))
        for frac in checkpoints:
            through = first - timedelta(days=1) + timedelta(days=int(round(frac * (last_d - first).days)))
            rt = R.fit_ratings(st.get("games") or {}, through=through, prior=prior, league=league,
                               teams=R.league_teams(st))
            try:
                res = SS.simulate(league, s, n=season_sims, seed=seed, state={"store": st, "through": through, "ratings": rt,
                                                                             "params": params_used.get(str(s))})
            except Exception as exc:  # noqa: BLE001
                sim_runs.append({"season": s, "checkpoint": frac, "error": str(exc)})
                continue
            for t, v in (res.get("teams") or {}).items():
                sims["playoffs"].append((v["p_playoffs"], int(t in out["playoffs"])))
                sims["finals"].append((v["p_conf"], int(t in out["finalists"])))
                sims["title"].append((v["p_title"], int(t == out["champion"])))
            sim_runs.append({"season": s, "checkpoint": frac, "through": str(through), "runtime_s": res.get("runtime_s"),
                             "p_champion": (res["teams"].get(out["champion"]) or {}).get("p_title")})
    season_metrics = {k: score(v) for k, v in sims.items()}
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "league": league,
           "seasons": [int(s) for s in seasons if s in wf], "games": len(rows.get("model", [])),
           "refit_days": refit_days, "carryover": coef, "params_by_season": params_used,
           "metrics": metrics, "metrics_vs_market": metrics_vs_market, "margin_rmse": margin_rmse,
           "per_season": per_season, "season_sim": season_metrics, "season_sim_runs": sim_runs,
           "runtime_s": round(time.perf_counter() - t0, 1)}
    if write:
        path = G.cache_root() / f"backtest_{league}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
        except OSError as exc:
            out["write_error"] = str(exc)
    return out


def summary_table(bt: dict) -> list[dict]:
    """Flat rows {scope, model, logloss, brier, n} for printing."""
    rows = []
    for scope in ("metrics", "metrics_vs_market"):
        for m, v in (bt.get(scope) or {}).items():
            if v.get("n"):
                rows.append({"scope": "all" if scope == "metrics" else "market_games", "model": m,
                             "logloss": v.get("logloss"), "brier": v.get("brier"), "n": v["n"]})
    for k, v in (bt.get("season_sim") or {}).items():
        if v.get("n"):
            rows.append({"scope": "season_sim", "model": k, "logloss": v.get("logloss"), "brier": v.get("brier"), "n": v["n"]})
    return rows
