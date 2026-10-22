"""
Builder C's fitting entry point: team-strength carry-over, walk-forward rows, the game model, award models, the
season-simulation spread and the backtest; and a report of the current season against the markets.

    fit_all(committed=True)  writes models/fitted/{team_strength_params,game_params,awards_fit,season_sim_params}.json
                             (CI uses them when the caches are cold) and docs/rink/data/calibration.json
    report(season)           ratings, today's / next games (model v market), season odds v futures, points v
                             KXNHLSEASONPTS, awards v markets, timings
Seasons are those with a store on disk (one season of team-game rows in memory at a time).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D

logger = logging.getLogger(__name__)


def seasons_with_games(last: int | None = None) -> list[int]:
    """Seasons with a store and 100+ played games, through `last` (default: the last completed season, the same
    set as fit_b and scripts/nhl_fit.py)."""
    if last is None:
        from oddsmarkets.nhl import canon
        last = D.prev_season(canon.current_season())
    out = []
    for s in D.seasons_on_disk():
        g = D.games_from_store(D.load_store(s), s)
        if len(g) and g["played"].sum() >= 100 and (last is None or s <= last):
            out.append(s)
    return out


def fit_all(committed: bool = True, season_sims: int = 1000, se_scales=(0.5, 0.75, 1.0, 1.25, 1.5), last: int | None = None) -> dict:
    from oddsmarkets.nhl.models import awards as AWD
    from oddsmarkets.nhl.models import backtest as BT
    from oddsmarkets.nhl.models import game as GM
    from oddsmarkets.nhl.models import team_strength as TS
    t0 = time.perf_counter()
    seasons = seasons_with_games(last)
    log: dict[str, Any] = {"seasons": seasons}
    if len(seasons) < 2:
        return {**log, "ok": False, "reason": "fewer than two seasons with games on disk"}
    p = TS.params(fresh=True)
    consecutive = [s for s in seasons if D.prev_season(s) in seasons]
    if consecutive:
        ch = TS.season_chain(seasons, prm=p)
        carry = TS.fit_carryover(ch["ends"])
        p["carry"].update(carry)
        log["carry"] = carry
    D.write_json(D.c_cache() / "team_strength_params.json", {"version": TS.VERSION, "result": p})
    if committed:
        D.write_json(D.FITTED / "team_strength_params.json", {"version": TS.VERSION, "result": p})
    G = D.games_frame(sorted(set(seasons) | {D.prev_season(s) for s in seasons}))
    t1 = time.perf_counter()
    wf = GM.walk_forward(seasons, games=G, prm_ts=p, players=True)
    log["walk_forward_s"] = round(time.perf_counter() - t1, 1)
    wf.to_parquet(D.c_cache() / "wf_rows.parquet", index=False)
    gp = GM.fit_from_rows(wf)
    GM.save_params(gp, committed=committed)
    log["game"] = {k: gp.get(k) for k in ("b0", "b_xg", "b_p", "b_g", "home", "s", "theta", "tie_k", "r_en", "k_pull", "k_ot",
                                         "so_home", "n", "loglik_reg")}
    try:
        af = AWD.fit()
        AWD.save(af, committed=committed)
        log["awards"] = {a: {k: v.get(k) for k in ("ok", "n_seasons", "top1")} for a, v in af["awards"].items()}
    except Exception as exc:  # noqa: BLE001
        log["awards"] = {"error": str(exc)}
    if season_sims:
        from oddsmarkets.nhl.models import season_sim as SS
        done = D.completed(seasons)
        scan, best = {}, None
        for sc in se_scales:
            D.write_json(D.c_cache() / "season_sim_params.json", {"result": {"se_scale": sc, "drift": SS.DRIFT}})
            cal = BT.season_calibration(done, wf, 500, (0, 60), 0, games=G)
            ms = [cal["metrics"][k]["logloss"] for k in ("playoffs", "div", "cup") if k in cal["metrics"]]
            if not ms:
                continue
            ll = float(np.mean(ms))
            scan[str(sc)] = round(ll, 5)
            if best is None or ll < best[1]:
                best = (sc, ll)
        if best is not None:
            obj = {"result": {"se_scale": best[0], "drift": SS.DRIFT}, "scan": scan}
            D.write_json(D.c_cache() / "season_sim_params.json", obj)
            if committed:
                D.write_json(D.FITTED / "season_sim_params.json", obj)
            log["season_sim"] = obj
    bt = BT.backtest(seasons=seasons, wf=wf, season_sims=season_sims, games=G)
    log["backtest"] = BT.summary_table(bt)
    log["runtime_s"] = round(time.perf_counter() - t0, 1)
    return log


def report(season: int | None = None, n: int = 20000, market: bool = True, kalshi: dict | None = None,
           poly: list | None = None, poly_games: list | None = None, today: date | None = None) -> dict:
    from oddsmarkets.nhl.models import awards as AWD
    from oddsmarkets.nhl.models import game as GM
    from oddsmarkets.nhl.models import season_sim as SS
    from oddsmarkets.nhl.models import team_strength as TS
    season = int(season or D.season_of_date(today or datetime.now(timezone.utc).date()))
    today = today or datetime.now(timezone.utc).date()
    out: dict[str, Any] = {"season": season}
    t0 = time.perf_counter()
    rd = TS.for_season(season)
    out["ratings_s"] = round(time.perf_counter() - t0, 2)
    out["ratings"] = TS.table(rd)
    out["mode"] = rd.get("mode")
    store = D.load_store(season)
    t1 = time.perf_counter()
    sim = SS.simulate(season, n=n, state={"store": store, "ratings": rd})
    out["sim_s"] = round(time.perf_counter() - t1, 2)
    out["sim"] = sim
    G = D.add_context(D.games_frame([D.prev_season(season), season]))
    gs = G[(G["season"] == season)]
    up = gs[~gs["played"] & (gs["date"] >= pd.Timestamp(today)) & (gs["date"] <= pd.Timestamp(today) + pd.Timedelta(days=2))]
    if len(up):
        pf = GM.predict_frame(up, rd)
        out["games"] = pf[["game_id", "date", "home", "away", "goalie_h", "goalie_a", "mu_h", "mu_a", "p_home", "p_reg_home",
                           "p_ot", "pl_home", "exp_total", "fair_total", "ml_home", "ml_away", "total_line"]].to_dict("records")
    if market:
        from oddsmarkets.nhl.sources import markets as M
        fut = M.futures(season, store=store, kalshi=kalshi, poly=poly)
        out["futures"] = fut
        if len(up):
            out["game_markets"] = M.game_prices(season, store=store, kalshi=kalshi, poly=poly_games,
                                                window=(today, today + pd.Timedelta(days=2).to_pytimedelta()))
    try:
        ps = AWD.player_seasons(season, store)
        left = {t: v["current"]["remaining"] for t, v in (sim.get("teams") or {}).items()}
        prev = AWD.player_seasons(D.prev_season(season))
        out["awards"] = AWD.predict(season, ps, games_left=left, prev=prev, n=min(n, 20000))
        if market and out.get("futures"):
            out["awards_v_market"] = AWD.compare_markets(out["awards"], out["futures"])
    except Exception as exc:  # noqa: BLE001
        out["awards"] = {"error": str(exc)}
    out["runtime_s"] = round(time.perf_counter() - t0, 2)
    return out
