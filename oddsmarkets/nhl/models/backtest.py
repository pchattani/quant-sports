"""
Walk-forward backtest of the game model and the season simulation; writes docs/rink/data/calibration.json.

Games (every regular-season and playoff game with a result, 2010-11 onward; chunked one season at a time)
-----------------------------------------------------------------------------------------------------
Ratings: `game.walk_forward` (team_strength refitted every 7 days from that season's earlier games, preseason prior
chained from the season before the first). Game-model coefficients for season S are fitted on the walk-forward rows of
seasons before S only (`game.fit_means` every season, the distribution shape every third season; defaults for the
first; a warm-up season with fewer than MIN_PRIOR_ROWS earlier rows is priced with game.DEFAULTS, never a fit that saw it,
and is flagged "warm_up" in by_season). Predictors of P(home wins, any manner):
    model         the game model
    xg_baseline   5v5 xG ratings only: logistic(a + b (xev_h - xev_a)), xev = 5v5 xG/60 for minus against, a, b
                  refitted each season on earlier seasons (goals-model net rating where a season has no xG)
    elo           FiveThirtyEight-style NHL Elo: K = 6, home ice 50 Elo points, margin multiplier
                  0.6686 ln(margin) + 0.8048 times 2.05 / (0.001 dElo_winner + 2.05), playoff differences x 1.25,
                  a third of the way back to 1505 between seasons (franchise-mapped); shootout games count margin 1
    market        the store's closing moneyline (ESPN, 2019-20 onward: the close block where ESPN has one, 2022-23 on,
                  else the last line it lists after the game), de-vigged multiplicatively
Scores: log-loss, Brier, reliability in 10 bins; every predictor is also scored on the games with a closing line
("vs_market"). Regulation calibration: P(regulation tie) against overtime, P(home regulation win) against it; puck line
P(home -1.5 covers) against margin >= 2; totals P(over the closing total) against the result (pushes dropped), with
the market's own de-vigged over price where the store has one.

Season odds: checkpoints at the season's first game and after 60 and 120 days of completed 2013-14 .. 2025-26 seasons
(not 2019-20 / 2020-21), 1,000 simulations each with ratings and coefficients fitted strictly before the checkpoint;
scored against playoffs, division winner, Presidents' Trophy, conference champion and Stanley Cup winner.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import game as GM
from oddsmarkets.nhl.models import team_strength as TS

logger = logging.getLogger(__name__)

EPS = 1e-4
MIN_PRIOR_ROWS = 600            # fewer earlier walk-forward rows than this: a warm-up season priced with the defaults
CHECK_DAYS = (0, 60, 120)


def score(p, y, bins: int = 10) -> dict:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    if len(p) == 0:
        return {"n": 0}
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    br = float(np.mean((p - y) ** 2))
    edges = np.linspace(0, 1, bins + 1)
    rel = []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1))
        if m.any():
            rel.append({"lo": round(edges[i], 2), "hi": round(edges[i + 1], 2), "n": int(m.sum()),
                        "mean_p": round(float(p[m].mean()), 4), "freq": round(float(y[m].mean()), 4)})
    return {"n": int(len(p)), "logloss": round(ll, 5), "brier": round(br, 5), "base_rate": round(float(y.mean()), 4),
            "mean_p": round(float(p.mean()), 4), "reliability": rel}


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "reliability"}


# ── Elo ──────────────────────────────────────────────────────────────────────

def elo_history(games: pd.DataFrame, k: float = 6.0, hfa: float = 50.0, revert: float = 1 / 3) -> pd.Series:
    r: dict[str, float] = {}
    out = {}
    last = None
    for g in games.sort_values(["date", "game_id"]).itertuples(index=False):
        if g.season != last:
            r = {t: 1505.0 + (v - 1505.0) * (1 - revert) for t, v in r.items()}
            last = g.season
        h, a = D.franchise(g.home), D.franchise(g.away)
        rh, ra = r.get(h, 1505.0), r.get(a, 1505.0)
        d = rh - ra + (0.0 if getattr(g, "neutral", False) else hfa)
        if g.gtype == "PO":
            d *= 1.25
        p = 1.0 / (1.0 + 10 ** (-d / 400.0))
        out[g.game_id] = p
        if g.played and np.isfinite(g.margin):
            m = float(g.margin)
            if g.so:
                m = 1.0 if m > 0 else -1.0
            y = 1.0 if m > 0 else 0.0
            dw = d if m > 0 else -d
            mult = (0.6686 * math.log(max(abs(m), 1.0)) + 0.8048) * 2.05 / (dw * 0.001 + 2.05)
            delta = k * mult * (y - p)
            r[h], r[a] = rh + delta, ra - delta
    return pd.Series(out)


def _logit_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    from scipy.optimize import minimize

    def f(b):
        z = np.clip(b[0] + b[1] * x, -30, 30)
        p = 1 / (1 + np.exp(-z))
        return -np.sum(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12)) + 0.01 * b @ b
    r = minimize(f, np.array([0.1, 1.0]), method="L-BFGS-B")
    return float(r.x[0]), float(r.x[1])


# ── the backtest ─────────────────────────────────────────────────────────────

def _season_params(wf: pd.DataFrame, s: int, cache: dict) -> dict:
    prior = wf[wf["season"] < s]
    if GM._played_rows(prior).shape[0] < MIN_PRIOR_ROWS:
        # warm-up season: the code defaults, never a fit that saw this season (GM.params() may be the all-season fit)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in GM.DEFAULTS.items()}
    p = GM.fit_means(prior, GM.params())
    n_seasons = prior["season"].nunique()
    key = n_seasons // 3
    if key not in cache:
        cache[key] = GM.fit_ot(prior, GM.fit_shape(prior, p, max_games=4000))
    shp = cache[key]
    for k in ("theta", "tie_k", "r_en", "k_pull", "k_ot", "so_home"):
        p[k] = shp[k]
    return GM.recenter(prior, p)


def predictions(wf: pd.DataFrame, games: pd.DataFrame | None = None) -> pd.DataFrame:
    """Walk-forward predictions for every row: model columns, elo, xg baseline, market."""
    seasons = sorted(wf["season"].unique())
    G = games if games is not None else wf
    elo = elo_history(G[G["season"].isin(range(min(seasons) - 30001, max(seasons) + 1))] if len(G) else wf)
    cache: dict = {}
    parts = []
    for s in seasons:
        rows = wf[wf["season"] == s].copy()
        p = _season_params(wf, s, cache)
        mh, ma = GM.means(rows, p)
        po = (rows["gtype"] == "PO").to_numpy()
        o = GM.outcome_probs(mh, ma, p, po, int(s))
        rows["mu_h"], rows["mu_a"] = mh, ma
        for k in ("p_home", "p_reg_home", "p_reg_away", "p_ot", "pl_home", "pl_away", "exp_total"):
            rows[k] = o[k]
        tl = rows["total_line"].to_numpy(float) if "total_line" in rows else np.full(len(rows), np.nan)
        pov, ppush = np.full(len(rows), np.nan), np.full(len(rows), np.nan)
        for i in range(len(rows)):
            if np.isfinite(tl[i]):
                pov[i] = GM.total_over(o["total_pmf"][i], tl[i])
                ppush[i] = GM.total_push(o["total_pmf"][i], tl[i])
        rows["p_over"], rows["p_push"] = pov, ppush
        # xG baseline (earlier seasons' fit)
        prior = wf[(wf["season"] < s) & wf["played"].astype(bool)]
        xd_all = (rows["xev_h"] - rows["xev_a"]).to_numpy(float)
        if (np.abs(xd_all) < 1e-12).all():
            xd_all = (rows["net_h"] - rows["net_a"]).to_numpy(float)
        if len(prior) >= 600:
            xd = (prior["xev_h"] - prior["xev_a"]).to_numpy(float)
            if (np.abs(xd) < 1e-12).all():
                xd = (prior["net_h"] - prior["net_a"]).to_numpy(float)
            a, b = _logit_fit(xd, (prior["margin"] > 0).to_numpy(float))
        else:
            a, b = 0.15, 1.6
        rows["p_xg"] = 1 / (1 + np.exp(-(a + b * xd_all)))
        rows["p_elo"] = rows["game_id"].map(elo).to_numpy(float)
        rows["p_market"] = [GM.ml_to_p(h, a_) for h, a_ in zip(rows.get("ml_home", [None] * len(rows)),
                                                             rows.get("ml_away", [None] * len(rows)))]
        rows["p_over_market"] = [GM.two_way(o_, u_) for o_, u_ in zip(rows.get("over_price", [None] * len(rows)),
                                                                     rows.get("under_price", [None] * len(rows)))]
        parts.append(rows.drop(columns=[c for c in rows.columns if c.startswith("_")], errors="ignore"))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def game_metrics(pr: pd.DataFrame) -> dict:
    r = pr[pr["played"].astype(bool) & pr["margin"].notna()]
    y = (r["margin"] > 0).to_numpy(float)
    out: dict = {"metrics": {}, "metrics_vs_market": {}, "by_season": {}}
    preds = {"model": "p_home", "xg_baseline": "p_xg", "elo": "p_elo", "market": "p_market"}
    for name, col in preds.items():
        v = pd.to_numeric(r[col], errors="coerce").to_numpy(float)
        m = np.isfinite(v)
        if m.sum():
            out["metrics"][name] = score(v[m], y[m])
    mk = np.isfinite(pd.to_numeric(r["p_market"], errors="coerce").to_numpy(float))
    if mk.sum():
        for name, col in preds.items():
            v = pd.to_numeric(r[col], errors="coerce").to_numpy(float)
            m = mk & np.isfinite(v)
            out["metrics_vs_market"][name] = score(v[m], y[m])
    for s, g in r.groupby("season"):
        yy = (g["margin"] > 0).to_numpy(float)
        rec = {}
        for name, col in preds.items():
            v = pd.to_numeric(g[col], errors="coerce").to_numpy(float)
            m = np.isfinite(v)
            if m.sum():
                rec[name] = _strip(score(v[m], yy[m]))
        prior_rows = int((r["season"] < s).sum())
        if prior_rows < MIN_PRIOR_ROWS:
            rec["warm_up"] = True
        out["by_season"][str(int(s))] = rec
    out["warm_up"] = [int(s) for s in sorted(r["season"].unique()) if int((r["season"] < s).sum()) < MIN_PRIOR_ROWS]
    # regulation, OT, puck line, totals
    ot = r["ot"].astype(bool).to_numpy()
    reg = r[~ot]
    out["ot"] = score(r["p_ot"].to_numpy(float), ot.astype(float))
    out["reg_home"] = score(r["p_reg_home"].to_numpy(float), ((r["reg_h"] > r["reg_a"]) & ~r["ot"].astype(bool)).to_numpy(float))
    out["puck_line_home"] = score(r["pl_home"].to_numpy(float), (r["margin"] >= 2).to_numpy(float))
    tl = pd.to_numeric(r.get("total_line"), errors="coerce").to_numpy(float) if "total_line" in r else np.full(len(r), np.nan)
    tot = r["total"].to_numpy(float)
    m = np.isfinite(tl) & (np.abs(tot - tl) > 1e-9)
    if m.sum():
        pover = r["p_over"].to_numpy(float)[m] / np.maximum(1 - np.nan_to_num(r["p_push"].to_numpy(float)[m]), 1e-9)
        out["totals_model"] = score(pover, (tot[m] > tl[m]).astype(float))
        pom = pd.to_numeric(r["p_over_market"], errors="coerce").to_numpy(float)[m]
        mm = np.isfinite(pom)
        if mm.sum():
            out["totals_market"] = score(pom[mm], (tot[m][mm] > tl[m][mm]).astype(float))
            out["totals_model_same_games"] = score(pover[mm], (tot[m][mm] > tl[m][mm]).astype(float))
        out["total_rmse"] = {"model": round(float(np.sqrt(np.mean((r["exp_total"].to_numpy(float)[m] - tot[m]) ** 2))), 4),
                             "line": round(float(np.sqrt(np.mean((tl[m] - tot[m]) ** 2))), 4), "n": int(m.sum())}
    del reg
    return out


# ── season odds ──────────────────────────────────────────────────────────────

def season_outcomes(games: pd.DataFrame, season: int) -> dict | None:
    from oddsmarkets.nhl.models import season_sim as SS
    g = games[games["season"] == season]
    po = g[(g["gtype"] == "PO") & g["played"]]
    if po.empty:
        return None
    last = po.sort_values(["date", "game_id"])
    # the Cup winner: the team that won the last series (four wins over the last opponent)
    fin = last.iloc[-1]
    pair = {fin["home"], fin["away"]}
    fg = last[last["home"].isin(pair) & last["away"].isin(pair)]
    wins = {t: int(((fg["home"] == t) & (fg["hs"] > fg["as_"])).sum() + ((fg["away"] == t) & (fg["as_"] > fg["hs"])).sum()) for t in pair}
    cup = max(wins, key=wins.get)
    S0 = SS.build_state(season, store={}, games=g)
    kind, steps = SS.tiebreak_steps(season)
    order = SS._current_order(S0, kind, steps, 0)
    divw = {t for t, r in order["div"].items() if r == 1}
    pres = [t for t, r in order["league"].items() if r == 1]
    return {"playoffs": set(po["home"]) | set(po["away"]), "div": divw, "pres": set(pres), "conf": pair, "cup": cup}


def season_calibration(seasons, wf: pd.DataFrame, n: int = 1000, check_days=CHECK_DAYS, seed: int = 0, tg_of=None,
                       games: pd.DataFrame | None = None) -> dict:
    from oddsmarkets.nhl.models import season_sim as SS
    tg_of = tg_of or D.team_games
    G = games if games is not None else D.games_frame(sorted(set(seasons)))
    pts = {k: [] for k in ("playoffs", "div", "pres", "conf", "cup")}
    runs = []
    for s in seasons:
        if SS.fmt(s) != "wildcard" or D.start_year(s) in (2019, 2020):
            continue
        out = season_outcomes(G, s)
        gs = G[(G["season"] == s)]
        if out is None or gs.empty:
            continue
        d0 = gs[gs["gtype"] == "REG"]["date"].min()
        for cd in check_days:
            thr = d0 + pd.Timedelta(days=cd)
            rd = TS.for_season(s, through=thr, tg_of=tg_of)
            prm = GM.fit_means(wf[(wf["season"] < s) | ((wf["season"] == s) & (wf["date"] < thr))], GM.params())
            t1 = time.perf_counter()
            try:
                res = SS.simulate(s, n=n, seed=seed, state={"games": gs, "through": thr, "ratings": rd, "params": prm,
                                                           "store": {}})
            except Exception as exc:  # noqa: BLE001
                runs.append({"season": s, "day": cd, "error": str(exc)})
                continue
            for t, v in res["teams"].items():
                pts["playoffs"].append((v["p_playoffs"], int(t in out["playoffs"]), s, cd))
                pts["div"].append((v["p_div"], int(t in out["div"]), s, cd))
                pts["pres"].append((v["p_pres"], int(t in out["pres"]), s, cd))
                pts["conf"].append((v["p_conf"], int(t in out["conf"]), s, cd))
                pts["cup"].append((v["p_cup"], int(t == out["cup"]), s, cd))
            runs.append({"season": s, "day": cd, "runtime_s": round(time.perf_counter() - t1, 2),
                         "p_champion": res["teams"].get(out["cup"], {}).get("p_cup")})
    res = {}
    for k, v in pts.items():
        if not v:
            continue
        a = np.array([(x[0], x[1]) for x in v], float)
        res[k] = score(a[:, 0], a[:, 1])
        res[k]["by_day"] = {str(cd): _strip(score(np.array([x[0] for x in v if x[3] == cd]), np.array([x[1] for x in v if x[3] == cd])))
                            for cd in check_days if any(x[3] == cd for x in v)}
    return {"metrics": res, "runs": runs, "n_sims": n, "check_days": list(check_days)}


def backtest(seasons: Iterable[int] | None = None, wf: pd.DataFrame | None = None, season_sims: int = 1000,
             games: pd.DataFrame | None = None, tg_of=None, write: bool = True) -> dict:
    t0 = time.perf_counter()
    seasons = sorted(int(s) for s in (seasons or [D.sid(y) for y in range(2010, 2027)]))
    if wf is None:
        wf = GM.walk_forward(seasons, games=games, tg_of=tg_of)
    pr = predictions(wf, games)
    out: dict = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "seasons": [int(seasons[0]), int(seasons[-1])], **game_metrics(pr)}
    out["runtime_games_s"] = round(time.perf_counter() - t0, 1)
    if season_sims:
        done = D.completed(seasons)
        out["season_sim"] = season_calibration(done, wf, season_sims, tg_of=tg_of, games=games)
    out["runtime_s"] = round(time.perf_counter() - t0, 1)
    if write:
        write_calibration(out)
    return out


def write_calibration(out: dict) -> None:
    path = D.data_root() / "calibration.json"
    cur = D.read_json(path) or {}
    cur["game_model"] = {k: v for k, v in out.items() if k != "season_sim"}
    # a games-only refresh (season_sims=0) keeps the season-odds block already in the file
    cur["season_sim"] = out.get("season_sim") or cur.get("season_sim")
    cur["updated_at"] = out["generated_at"]
    D.write_json(path, cur)


def summary_table(bt: dict) -> list[dict]:
    rows = []
    for scope in ("metrics", "metrics_vs_market"):
        for m, v in (bt.get(scope) or {}).items():
            if v.get("n"):
                rows.append({"scope": "all" if scope == "metrics" else "line_games", "model": m, "logloss": v.get("logloss"),
                             "brier": v.get("brier"), "n": v["n"]})
    return rows
