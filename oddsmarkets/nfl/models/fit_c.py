"""
Builder C's fitting entry point (called by scripts/nfl_fit.py): unit caches, team-strength carry-over, walk-forward
rows, the game model, the drive model, award models, the season-simulation constants and the backtest.

    fit_all(committed=True)  writes models/fitted/{team_strength_params,game_params,drive_model,awards_fit,
                             season_sim_params}.json (versioned; CI uses them when the caches are cold) and
                             docs/gridiron/data/calibration.json
    report(season)           current ratings, game prices for the coming week, season odds against markets
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

logger = logging.getLogger(__name__)

FIRST, BACKTEST_FROM = 1999, 2006


def fit_all(last: int | None = None, committed: bool = True, season_sims: int = 2000, tuned: dict | None = None,
            se_scales=(0.5, 0.75, 1.0)) -> dict:
    from oddsmarkets.nfl.models import awards as AWD
    from oddsmarkets.nfl.models import backtest as BT
    from oddsmarkets.nfl.models import drive_sim as DS
    from oddsmarkets.nfl.models import game as GM
    from oddsmarkets.nfl.models import team_strength as TS
    t0 = time.perf_counter()
    seasons = D.pbp_seasons()
    last = last or max(seasons)
    log: dict[str, Any] = {}
    for s in range(FIRST, last + 1):
        D.unit_rows(s)
    # team strength: carry-over from the chain, plus any tuned hyper-parameters
    p = TS.params(tuned or {})
    ch = TS.season_chain(list(range(FIRST, last)), prm=p)
    carry = TS.fit_carryover(ch["ends"])
    carry.pop("qb", None)                       # the QB carry is a tuned constant (see team_strength docstring)
    p["carry"].update(carry)
    D.write_json(D.c_cache() / "team_strength_params.json", {"version": TS.VERSION, "result": p})
    if committed:
        D.write_json(D.FITTED / "team_strength_params.json", {"version": TS.VERSION, "result": p})
    log["team_strength"] = {"carry": p["carry"], "half_life_weeks": p["half_life_weeks"], "lam": p["lam"]}
    # walk-forward rows and the game model
    G = D.games_frame(range(FIRST, last + 1))
    wf = GM.walk_forward(list(range(FIRST, last + 1)), games=G, prm_ts=p)
    wf.to_parquet(D.c_cache() / "wf_rows.parquet", index=False)
    gp = GM.fit_from_rows(wf[wf["season"] >= BACKTEST_FROM])
    GM.save_params(gp, committed=committed)
    log["game"] = {k: gp[k] for k in ("s", "hfa", "hfa_trend", "div", "rest", "bye", "short", "travel", "tz", "sigma",
                                      "sigma_market", "t_off", "wind", "cold", "dome", "sigma_total", "n")}
    # drive model with the walk-forward efficiencies
    k = wf.set_index("game_id")
    dr = pd.concat([D.drive_rows(s) for s in range(BACKTEST_FROM, last + 1)], ignore_index=True)
    dr = dr[dr["game_id"].isin(k.index)]
    home = k.loc[dr["game_id"], "home"].to_numpy()
    x = np.where(dr["off"].to_numpy() == home, k.loc[dr["game_id"], "eff_h"].to_numpy(), k.loc[dr["game_id"], "eff_a"].to_numpy())
    recent = pd.concat([D.drive_rows(s) for s in range(max(BACKTEST_FROM, last - 2), last + 1)], ignore_index=True)
    dm = DS.fit(dr, x=np.nan_to_num(x), recent=recent)
    DS.save(dm, committed=committed)
    log["drive"] = {"n": dm["n"], "nll": dm["nll"]}
    del dr, recent
    # awards
    af = AWD.fit(list(range(BACKTEST_FROM, min(last, 2025) + 1)), games=G)
    AWD.save(af, committed=committed)
    log["awards"] = {a: {kk: v.get(kk) for kk in ("n_seasons", "top1", "loglik", "missing")} for a, v in af["awards"].items()}
    # season-simulation spread: choose se_scale by season-odds log-loss (playoffs), then the full backtest
    best = None
    scan = {}
    if season_sims > 0:
        from oddsmarkets.nfl.models import season_sim as SS
        for sc in se_scales:
            D.write_json(D.c_cache() / "season_sim_params.json", {"result": {"se_scale": sc, "drift": SS.DRIFT}})
            cal = BT.season_calibration(list(range(BACKTEST_FROM, min(last, 2025) + 1, 2)), wf, 1000, (1, 5, 10), 0, games=G)
            ll = np.mean([cal["metrics"][kk]["logloss"] for kk in ("playoffs", "div", "sb") if kk in cal["metrics"]])
            scan[str(sc)] = round(float(ll), 5)
            if best is None or ll < best[1]:
                best = (sc, ll)
        obj = {"result": {"se_scale": best[0], "drift": SS.DRIFT}, "scan": scan}
        D.write_json(D.c_cache() / "season_sim_params.json", obj)
        if committed:
            D.write_json(D.FITTED / "season_sim_params.json", obj)
        log["season_sim"] = obj
    bt = BT.backtest(seasons=list(range(BACKTEST_FROM, last + 1)), wf=wf, season_sims=season_sims, games=G)
    log["backtest"] = BT.summary_table(bt)
    # market-line calibration (game.market_cover / market_over): the Platt maps fitted on the backtest's
    # out-of-sample ATS and totals predictions
    mc = bt.get("market_calibration") or {}
    gp["cal_ats"], gp["cal_tot"] = mc.get("cal_ats"), mc.get("cal_tot")
    GM.save_params(gp, committed=committed)
    log["market_calibration"] = mc
    log["runtime_s"] = round(time.perf_counter() - t0, 1)
    return log


def report(season: int, n: int = 20000, market: bool = True, kalshi: dict | None = None, poly: list | None = None) -> dict:
    """Ratings, this week's games (model v market), season odds v markets, win totals v KXNFLWINS."""
    from oddsmarkets.nfl.models import awards as AWD
    from oddsmarkets.nfl.models import game as GM
    from oddsmarkets.nfl.models import season_sim as SS
    from oddsmarkets.nfl.models import team_strength as TS
    out: dict[str, Any] = {}
    t0 = time.perf_counter()
    rt = TS.for_season(season)
    out["ratings_s"] = round(time.perf_counter() - t0, 2)
    out["ratings"] = TS.table(rt)
    G = D.games_frame([season - 2, season - 1, season])
    qb = AWD.qb_starters(season)
    t1 = time.perf_counter()
    sim = SS.simulate(season, n=n, state={"games": G[G["season"].isin([season - 1, season])], "ratings": rt})
    out["sim_s"] = round(time.perf_counter() - t1, 2)
    out["sim"] = sim
    gs = D.add_context(G[G["season"] == season].sort_values(["date", "game_id"]))
    nxt = gs[~gs["played"]]
    if not nxt.empty:
        wk = int(nxt["week"].min())
        gw = gs[(gs["week"] == wk)]
        pf = GM.predict_frame(gw, rt, base=SS._scoring_level(G, season))
        out["week"] = wk
        out["games"] = pf[["game_id", "home", "away", "home_qb", "away_qb", "mu", "mu_total", "p_home", "line",
                           "total_line", "ml_home", "ml_away"]].to_dict("records")
    out["qb_depth_chart"] = qb
    if market:
        from oddsmarkets.nfl.sources import markets as M
        fut = M.futures(season, kalshi=kalshi, poly=poly)
        out["futures"] = fut
        if out.get("games"):
            store = D.load_store(season)
            out["game_markets"] = M.game_prices(season, store=store, kalshi=kalshi)
    return out
