"""
Walk-forward backtest of the game model (2016 -> 2026 by default) and the model checks that feed the Calibration
page. The committed calibration.json (2 October 2026, 08:34 UTC) covers 2016-2026: 25,374 games, 25,162 with a
closing moneyline; model log-loss 0.6766 pooled (close 0.6714 on its games), 9.04 simulated runs a game against
9.03, over/under log-loss 0.6999 (a coin 0.6931).

Games (per season, processed month by month; only one season's plate appearances are held at a time)
------------------------------------------------------------------------------------------------
Every final regular-season and postseason game in the store with a Statcast record is priced before it is
played:
* ``model``: the PA simulation (`game_sim`, `n_sims` per game) with inputs from data strictly before the
  game's date: rest-of-season projections refitted every `refit_days` days from the season's PAs to date
  plus the previous seasons (`projections.project(kind="ros")`), the usage log (lineups, starters' pitch
  counts, bullpen availability) to the day before, park factors from the three previous seasons, weather effects
  fitted on the three previous seasons (each venue's average weather from the previous season), base-out /
  running / pitches-per-outcome tables fitted on the two previous seasons (`game_sim.fit_tables`), posted
  lineups, probables and scheduled innings from the store (else the projected ones).
* ``ratings``: team ratings only (run differential to date, regressed with 50 games to half last season's
  final rating; home field season_sim.HFA_LOGIT = 0.12 logit).
* ``starter_record``: a logistic regression on [logit of the two teams' regressed win % (log5), the two
  starters' regressed RA9 difference (season to date, 40 IP of league average), home] fitted on the earlier
  seasons' games (fixed starting coefficients in the first season).
* ``market``: ESPN's closing moneyline (GAME.lines.close.ml, else the current line), de-vigged
  multiplicatively: p = q_h / (q_h + q_a) with q = 100 / (ml + 100) or -ml / (-ml + 100); checked against the
  record's other books for in-game lines (`_market`).
Scores: log-loss, Brier, reliability in 10 bins; every model is also scored on the games with a market line.
Totals: P(total > closing line) from the simulated distribution (pushes on whole lines excluded) against the
outcome, binned. Run line: P(home covers the closing home run line). Postseason series: at each series' first
game, P(home-field team wins) from the closed form with the model's game-1 home probability and the mirrored
away probability (logit - 2 x season_sim.HFA_LOGIT, i.e. 2 x 0.12), against the result. (0.16 is only the
starter-and-record model's starting home coefficient in BASE_COEF.)

Other checks (`model_checks`)
* projections v the Marcel-like baseline (`projections.evaluate`);
* xwOBA+ v Savant xwOBA at predicting second-half wOBA (builder C's `xwoba.predictive_test`);
* stuff validity: correlation of a pitcher's stuff score in season Y (builder B, else fastball velocity)
  with his K% and RA9 in Y+1 (>= 300 BF in both), against the same for his season-Y K%.

Output: docs/bullpen/data/mlb/calibration.json (`write_calibration`), per-season partials cached under
<cache>/backtest/ so a run can resume.
"""
from __future__ import annotations

import gc
import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio
from oddsmarkets.baseball.models import game_inputs as GI
from oddsmarkets.baseball.models import game_sim as G
from oddsmarkets.baseball.models import projections as PJ
from oddsmarkets.baseball.models import season_sim as SS

logger = logging.getLogger(__name__)

EPS = 1e-4
VERSION = 5
BASE_COEF = np.array([0.0, 1.0, 0.08, 0.16])        # intercept, log5 logit, RA9 diff (away - home), home flag


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


TOTAL_RANGE = (5.0, 16.0)        # a pre-game full-game total; ESPN's lead book sometimes holds an in-game line


def _market(g: dict) -> dict:
    """
    The closing line: ESPN's close, else its current line, checked against the other books ESPN lists. Some
    records' lead book carries an in-game line (2018-2019 above all: totals of 1.5, 4.5 or 18.5, run lines of
    +-4.5 or -9.5, moneylines of 0) while every other book shows the pre-game one; scored as closing lines they
    put the market's own in-game knowledge into the comparison. When the lead book's total is missing, outside
    TOTAL_RANGE or a run or more from the books' median total, or its moneyline is empty, every field is taken
    from the books instead: the median de-vigged moneyline, the books at the median total (their over
    price averaged), the books on the +-1.5 run line.
    """
    from oddsmarkets.baseball.sources.markets import store_lines
    ln = store_lines(g, "close")
    if ln.get("p_home") is None:
        cur = store_lines(g, "current")
        ln = {**cur, **{k: v for k, v in ln.items() if v is not None}}
    # ESPN's in-play feed ("... - Live Odds", from 2024) is a book of its own: never a closing line
    books = [store_lines({"lines": b}, "current") for b in ((g.get("lines") or {}).get("books") or [])
             if isinstance(b, dict) and "live" not in str(b.get("name") or "").lower()]
    tots = [b["total"] for b in books if b.get("total") is not None and TOTAL_RANGE[0] <= b["total"] <= TOTAL_RANGE[1]
            and b.get("p_over") is not None]
    if not tots:
        if ln.get("total") is not None and not (TOTAL_RANGE[0] <= ln["total"] <= TOTAL_RANGE[1]):
            ln = {k: v for k, v in ln.items() if k not in ("total", "p_over")}
        return ln
    med = float(np.median(tots))
    lead = ln.get("total")
    live = lead is None or not (TOTAL_RANGE[0] <= lead <= TOTAL_RANGE[1]) or abs(lead - med) >= 1.0 or ln.get("p_home") is None
    if not live:
        return ln
    out = {}
    ph = [b["p_home"] for b in books if b.get("p_home") is not None and 0.02 < b["p_home"] < 0.98]
    if ph:
        out["p_home"] = float(np.median(ph))
    line = min(tots, key=lambda t: abs(t - med))
    po = [b["p_over"] for b in books if b.get("total") == line and b.get("p_over") is not None]
    out["total"] = float(line)
    if po:
        out["p_over"] = float(np.mean(po))
    rls = [b for b in books if b.get("rl_home") is not None and abs(abs(b["rl_home"]) - 1.5) < 1e-9 and b.get("p_rl_home") is not None]
    if rls:
        sign = 1.0 if sum(1 for b in rls if b["rl_home"] > 0) * 2 > len(rls) else -1.0
        same = [b for b in rls if b["rl_home"] * sign > 0]
        out["rl_home"] = 1.5 * sign
        out["p_rl_home"] = float(np.mean([b["p_rl_home"] for b in same]))
    out["cleaned"] = True
    return out


def _ra9_table(pa: pd.DataFrame) -> pd.DataFrame:
    if not len(pa):
        return pd.DataFrame(columns=["runs", "outs"])
    outs = (pa["outs_post"] - pa["outs"]).clip(0, 3)
    return pd.DataFrame({"p": pa["pitcher"], "runs": pa["runs"], "outs": outs}).groupby("p")[["runs", "outs"]].sum()


def _fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, b0: np.ndarray | None = None) -> np.ndarray:
    b = np.array(BASE_COEF if b0 is None else b0, float)
    for _ in range(25):
        z = X @ b
        p = 1 / (1 + np.exp(-z))
        W = p * (1 - p)
        g = X.T @ (y - p) - l2 * (b - BASE_COEF)
        H = -(X.T * W) @ X - l2 * np.eye(len(b))
        step = np.linalg.solve(H, g)
        b = b - step
        if np.abs(step).max() < 1e-8:
            break
    return b


def _context(level: str, season: int, store: dict, pa_before: pd.DataFrame, prev_tail: pd.DataFrame, parks: dict,
             umps: dict, a2t: dict, t2a: dict, woba: np.ndarray, aging_cache: dict, weather: dict | None = None,
             weather_ref: dict | None = None) -> GI.Context:
    # an empty season-to-date (opening day) must stay empty: None would make `project` read the whole season
    part_h, part_p = PJ.aggregates_from_pa(pa_before) if len(pa_before) else (pd.DataFrame(columns=PJ.COUNT_COLS),
                                                                               pd.DataFrame(columns=PJ.COUNT_COLS))
    dates = (str(pa_before["game_date"].min())[:10], str(pa_before["game_date"].max())[:10]) if len(pa_before) else None
    hit = PJ.project(level, season, "ros", role="hitter", partial=part_h, extras_season=season - 1,
                     partial_pitchers=part_p, partial_dates=dates)
    pit = PJ.project(level, season, "ros", role="pitcher", partial=part_p, extras_season=season - 1)
    # the league reference is the projections' own environment (GI.league_from_projections), not the
    # season-to-date table: see projections.project
    league, rescale_h, rescale = GI.league_from_projections(hit, pit, PJ.league_table(PJ.season_aggregates(level, season - 1)[0]))
    usage = GI.Usage.from_pa(pd.concat([prev_tail, pa_before], ignore_index=True) if len(prev_tail) else pa_before)
    ppa = float(pa_before["pitches"].mean()) if len(pa_before) else (float(prev_tail["pitches"].mean()) if len(prev_tail) else 3.9)
    return GI.Context(level, season, store, GI.rates_from_projection(hit, rescale_h), GI.rates_from_projection(pit, rescale), league,
                      usage, parks, umps, a2t, t2a, woba, ppa, pb_rates=GI.pitcher_batting_rates(hit, league),
                      weather_coef=weather, weather_ref=weather_ref)


VARIANTS = ("post", "open", "open_rot")


def variant_game(g: dict, variant: str = "post") -> dict:
    """
    The game record as the model may see it at a decision time. "post" (the default, about an hour before first
    pitch): posted lineups, the probables, the umpire and the game-time weather report. "open" (the opening line,
    usually the day before): no posted lineups (each team's latest against a starter of the same hand), the
    probables (books list them and void the bet when they change), the umpire (the crew's rotation sets him), the
    temperature (a day-ahead forecast is good to a few degrees) but no wind (day-ahead wind forecasts are poor).
    "open_rot": "open" without the probables (each team's most rested regular starter): the store's probables are
    the pitchers who started, so a starter changed after the open is known to "open"; "open_rot" never is.
    """
    if variant == "post":
        return g
    if variant not in ("open", "open_rot"):
        raise ValueError(f"unknown variant {variant!r}")
    g = dict(g)
    g["lineups"] = None
    if variant == "open_rot":
        g["probables"] = None
    wx = g.get("weather")
    if isinstance(wx, dict):
        g["weather"] = {"temp": wx.get("temp"), "cond": wx.get("cond")}
    return g


def cache_name(level: str, season: int, n_sims: int, variant: str = "post") -> str:
    return f"{level}_{season}_n{n_sims}_v{VERSION}" + ("" if variant == "post" else f"_{variant}") + ".json"


def backtest_season(level: str, season: int, n_sims: int = 1000, refit_days: int = 7, coef: np.ndarray | None = None,
                    prior_ratings: dict | None = None, max_games: int | None = None, seed: int = 0,
                    store: dict | None = None, variant: str = "post") -> dict:
    """Rows for one season: {"games": [...], "series": [...], "final_ratings": {...}, "seconds"}. `variant` is the
    decision time the inputs respect (`variant_game`)."""
    t0 = time.perf_counter()
    store = store if store is not None else _dio.load_store(level, season)
    pa = PJ.pa_table(level, season)
    if not store or not store.get("games") or not len(pa):
        return {"games": [], "series": [], "final_ratings": {}, "reason": "no store or pitch table"}
    have = set(pa["game_pk"].astype(str).unique())
    games = [g for g in store["games"].values() if SS.is_final(g) and str(g.get("gpk")) in have
             and str(g.get("gtype") or "R") in ("R", "F", "D", "L", "W")]
    games.sort(key=lambda g: (str(g.get("date")), str(g.get("gpk"))))
    if max_games:
        games = games[:max_games]
    prev = PJ.pa_table(level, season - 1)
    # the previous season's last 30 days seed the usage log (lineups, rotations) for opening week
    prev_tail = prev[prev["game_date"] >= str(date.fromisoformat(str(prev["game_date"].max())[:10]) - timedelta(days=30))].copy()         if len(prev) else prev
    parks = GI.park_factors_c(level, season - 1) or GI.park_factors_from_pa([PJ.pa_table(level, s) for s in range(season - 3, season)])
    prev_store = _dio.load_store(level, season - 1)
    umps = GI.umpire_factors(prev_store.get("games") or {}, prev)
    # weather effects fitted within parks on the three previous seasons; each venue's average weather from the
    # previous season's games (no outcome of the season priced enters either)
    wx = GI.fit_weather(level, [s for s in range(season - 3, season) if s in _dio.pitch_seasons(level)])
    wx_ref = prev_store if prev_store.get("games") else None
    # base-out, running and pitches-per-outcome tables from the two previous seasons (the committed tables are fitted
    # on the latest seasons, which would leak later base running into earlier ones)
    tables = G.fit_tables(level, [s for s in (season - 2, season - 1) if s in _dio.pitch_seasons(level)])
    trans, ppe = tables if tables else (None, None)
    del prev
    gc.collect()
    a2t, t2a = GI.abbr_map(store, pa)
    ww = PJ.woba_weights(season)
    woba = np.array([0, ww["BB"], ww["HBP"], ww["1B"], ww["2B"], ww["3B"], ww["HR"], 0, 0])
    coef = BASE_COEF if coef is None else coef
    rows = []
    failures: list[str] = []
    ctx = None
    last_refit = None
    ra9_lg = None
    by_month: dict[str, list] = {}
    for g in games:
        by_month.setdefault(str(g["date"])[:7], []).append(g)
    for month, mg in by_month.items():
        days = sorted({str(g["date"])[:10] for g in mg})
        for dstr in days:
            d = date.fromisoformat(dstr)
            if ctx is None or (d - last_refit).days >= refit_days:
                before = pa[pa["game_date"] < dstr]
                ctx = _context(level, season, store, before, prev_tail, parks, umps, a2t, t2a, woba, {}, wx, wx_ref)
                ra = _ra9_table(before)
                ra9_lg = 9 * ra["runs"].sum() / max(ra["outs"].sum() / 3, 1) if len(ra) else 4.4
                ratings = SS.team_ratings(store, through=d, prior={t: 0.5 * v.get("r", 0.0) for t, v in (prior_ratings or {}).items()})
                last_refit = d
                del before
            else:
                # usage moves daily (lineups, bullpen rest): extend the log with the previous day
                prevday = (d - timedelta(days=1)).isoformat()
                add = pa[(pa["game_date"] >= prevday) & (pa["game_date"] < dstr)]
                if len(add) and not (ctx.usage.apps["date"] >= prevday).any():
                    ctx.usage.extend(add)
                ratings = SS.team_ratings(store, through=d, prior={t: 0.5 * v.get("r", 0.0) for t, v in (prior_ratings or {}).items()})
            for g in [x for x in mg if str(x["date"])[:10] == dstr]:
                try:
                    spec = ctx.spec(variant_game(g, variant))
                    if ppe is not None:
                        spec["pitches_per_event"] = ppe
                    res = G.simulate(spec, n=n_sims, seed=seed + int(str(g["gpk"])[-6:]), trans=trans)
                except Exception as exc:  # noqa: BLE001
                    logger.info("game %s failed: %s", g.get("gpk"), exc)
                    failures.append(str(g.get("gpk")))
                    if len(failures) > 25 and len(failures) > len(rows):
                        raise RuntimeError(f"backtest {season}: {len(failures)} games failed, last: {exc}") from exc
                    continue
                h, a = str(g["home"]), str(g["away"])
                y = int(int(g["hs"]) > int(g["as"]))
                rh, ra_ = ratings.get(h, {}).get("r", 0.0), ratings.get(a, {}).get("r", 0.0)
                p_rat = float(1 / (1 + math.exp(-(rh - ra_ + SS.HFA_LOGIT))))
                # starter / record baseline features
                wh, lh, wa, la = _record(store, h, d), _record(store, h, d, loss=True), _record(store, a, d), _record(store, a, d, loss=True)
                ph_ = (wh + 40 * 0.5) / (wh + lh + 40)
                pa_ = (wa + 40 * 0.5) / (wa + la + 40)
                log5 = math.log(ph_ / (1 - ph_)) - math.log(pa_ / (1 - pa_))
                ra_h = _starter_ra9(ra, spec["meta"]["home_sp"], ra9_lg)
                ra_a = _starter_ra9(ra, spec["meta"]["away_sp"], ra9_lg)
                x = np.array([1.0, log5, ra_a - ra_h, 1.0])
                p_sr = float(1 / (1 + math.exp(-(x @ coef))))
                mk = _market(g)
                tot = int(g["hs"]) + int(g["as"])
                row = {"gpk": str(g["gpk"]), "date": dstr, "gtype": g.get("gtype") or "R", "home": h, "away": a, "y": y,
                       "model": round(res["p_home"], 5), "ratings": round(p_rat, 5), "starter_record": round(p_sr, 5),
                       "x": [round(float(v), 4) for v in x], "market": mk.get("p_home"), "total": tot,
                       "sp": [spec["meta"]["home_sp"], spec["meta"]["away_sp"]],
                       "margin": int(g["hs"]) - int(g["as"]), "model_total": res["runs"]["total"],
                       # kept so closing lines that arrive later can be scored without re-simulating
                       "total_dist": [round(x, 4) for x in res["total_dist"][:31]],
                       "margin_dist": {int(k): round(v, 4) for k, v in res["margin_dist"].items()}}
                if mk.get("total") is not None:
                    row["line_total"] = mk["total"]
                    row["p_over"] = G.p_over(res, mk["total"])
                    row["mkt_p_over"] = mk.get("p_over")
                if mk.get("rl_home") is not None:
                    L = float(mk["rl_home"])
                    md = res["margin_dist"]
                    row["rl_home"] = L
                    row["p_rl"] = round(sum(v for k, v in md.items() if int(k) + L > 0), 5)
                    row["mkt_p_rl"] = mk.get("p_rl_home")
                rows.append(row)
        gc.collect()
    series = _series_rows(rows)
    final = SS.team_ratings(store, prior={t: 0.5 * v.get("r", 0.0) for t, v in (prior_ratings or {}).items()})
    return {"games": rows, "series": series, "final_ratings": final, "failures": failures,
            "seconds": round(time.perf_counter() - t0, 1)}


_REC_CACHE: dict = {}


def _record(store: dict, team: str, d: date, loss: bool = False) -> int:
    key = (id(store), d)
    if key not in _REC_CACHE:
        if len(_REC_CACHE) > 400:
            _REC_CACHE.clear()
        w, l = {}, {}
        for g in store["games"].values():
            if (g.get("gtype") or "R") != "R" or not SS.is_final(g) or str(g.get("date"))[:10] >= d.isoformat():
                continue
            hw = int(g["hs"]) > int(g["as"])
            win, los = (str(g["home"]), str(g["away"])) if hw else (str(g["away"]), str(g["home"]))
            w[win] = w.get(win, 0) + 1
            l[los] = l.get(los, 0) + 1
        _REC_CACHE[key] = (w, l)
    w, l = _REC_CACHE[key]
    return (l if loss else w).get(team, 0)


def _starter_ra9(ra: pd.DataFrame, pid: str | None, lg: float, k_ip: float = 40.0) -> float:
    if pid is None or not len(ra) or str(pid) not in ra.index:
        return lg
    r = ra.loc[str(pid)]
    ip = r["outs"] / 3
    return float((r["runs"] + k_ip * lg / 9) / (ip + k_ip) * 9)


def _series_rows(rows: list[dict]) -> list[dict]:
    """Postseason series: P(home-field team wins) at game 1 v the result."""
    post = [r for r in rows if r["gtype"] in SS.GTYPE_ROUND]
    out = []
    groups: dict = {}
    for r in sorted(post, key=lambda r: (r["date"], r["gpk"])):
        groups.setdefault((r["gtype"], frozenset((r["home"], r["away"]))), []).append(r)
    for (gt, pair), rs in groups.items():
        rnd = SS.GTYPE_ROUND[gt]
        first = rs[0]
        hf = first["home"]
        ph = first["model"]
        pa = 1 / (1 + math.exp(-(math.log(ph / (1 - ph)) - 2 * SS.HFA_LOGIT)))
        p = SS.series_prob(ph, pa, SS.BEST_OF[rnd], SS.PATTERN[rnd])
        wins = sum((r["y"] == 1) == (r["home"] == hf) for r in rs)
        need = SS.BEST_OF[rnd] // 2 + 1
        if wins < need and len(rs) - wins < need:
            continue          # incomplete
        out.append({"round": rnd, "home_field": hf, "p": round(p, 5), "y": int(wins >= need)})
    return out


def run(level: str = "mlb", seasons: Iterable[int] | None = None, n_sims: int = 1000, refit_days: int = 7,
        use_cache: bool = True, max_games: int | None = None, variant: str = "post") -> dict:
    """Walk-forward over seasons (each season's starter/record coefficients fitted on the earlier seasons)."""
    seasons = sorted(seasons or [s for s in _dio.pitch_seasons(level) if s >= 2016])
    cdir = _dio.cache_root() / "backtest"
    per = {}
    coef = BASE_COEF.copy()
    train_X, train_y = [], []
    prior = None
    for s in seasons:
        cp = cdir / cache_name(level, s, n_sims, variant)
        res = None
        if use_cache and cp.exists() and max_games is None:
            try:
                import json
                res = json.loads(cp.read_text())
            except Exception:  # noqa: BLE001
                res = None
        if res is None:
            res = backtest_season(level, s, n_sims=n_sims, refit_days=refit_days, coef=coef, prior_ratings=prior,
                                  max_games=max_games, variant=variant)
            res["coef"] = [float(c) for c in coef]
            if max_games is None and res.get("games"):
                _dio.jdump(res, cp)
        per[s] = res
        prior = res.get("final_ratings")
        for r in res.get("games") or []:
            if r["gtype"] == "R":
                train_X.append(r["x"])
                train_y.append(r["y"])
        if len(train_y) > 500:
            coef = _fit_logit(np.array(train_X), np.array(train_y, float))
        logger.info("backtest %s: %d games in %ss", s, len(res.get("games") or []), res.get("seconds"))
    return summarize(per)


def _tot_rows(rs: list[dict], key_p: str, key_line: str, outcome) -> list[tuple[float, int]]:
    out = []
    for r in rs:
        p, L = r.get(key_p), r.get(key_line)
        if p is None or L is None:
            continue
        y = outcome(r, L)
        if y is None:
            continue
        out.append((p, y))
    return out


def summarize(per: dict) -> dict:
    seasons = {}
    allg, alls = [], []
    for s, res in sorted(per.items()):
        gs = res.get("games") or []
        allg += gs
        alls += res.get("series") or []
        seasons[str(s)] = _summ(gs) | {"series": score([(r["p"], r["y"]) for r in res.get("series") or []]),
                                       "seconds": res.get("seconds")}
    out = {"version": VERSION, "seasons": seasons, "pooled": _summ(allg),
           "series": score([(r["p"], r["y"]) for r in alls])}
    return out


def _summ(gs: list[dict]) -> dict:
    out = {"n_games": len(gs)}
    for m in ("model", "ratings", "starter_record"):
        out[m] = score([(r[m], r["y"]) for r in gs])
    wm = [r for r in gs if r.get("market") is not None]
    out["vs_market"] = {m: score([(r[m], r["y"]) for r in wm]) for m in ("model", "ratings", "starter_record", "market")}
    if wm:
        # a 50/50 blend shows how much independent information the model carries beyond the close
        out["vs_market"]["blend_50"] = score([(0.5 * r["model"] + 0.5 * r["market"], r["y"]) for r in wm])

    def over(r, L):
        if float(L).is_integer() and r["total"] == L:
            return None
        return int(r["total"] > L)

    def cover(r, L):
        v = r["margin"] + L
        return None if v == 0 else int(v > 0)
    out["totals"] = score(_tot_rows(gs, "p_over", "line_total", over))
    out["totals_market"] = score(_tot_rows(gs, "mkt_p_over", "line_total", over))
    out["runline"] = score(_tot_rows(gs, "p_rl", "rl_home", cover))
    out["runline_market"] = score(_tot_rows(gs, "mkt_p_rl", "rl_home", cover))
    if gs:
        out["runs"] = {"model_mean_total": round(float(np.mean([r["model_total"] for r in gs])), 3),
                       "actual_mean_total": round(float(np.mean([r["total"] for r in gs])), 3)}
    return out


# ── other checks ─────────────────────────────────────────────────────────────

def stuff_validity(level: str = "mlb", seasons: Iterable[int] | None = None, min_bf: int = 300) -> dict:
    """corr(stuff_Y, K%_{Y+1}) and corr(stuff_Y, RA9_{Y+1}) v the same for K%_Y."""
    avail = _dio.pitch_seasons(level)
    seasons = [s for s in (seasons or avail) if s + 1 in avail]
    xs, ks, ks1, ra1 = [], [], [], []
    src = None
    for s in seasons:
        st = PJ.stuff_scores(level, s)
        src = src or ("stuff" if len(st) else None)
        if not len(st):
            st = PJ.velocity(level, s)
            src = src or "velocity"
        _, p0 = PJ.season_aggregates(level, s)
        _, p1 = PJ.season_aggregates(level, s + 1)
        pa1 = PJ.pa_table(level, s + 1)
        ra = _ra9_table(pa1)
        if not len(p0) or not len(p1):
            continue
        ids = p0.index[(p0["PA"] >= min_bf)].intersection(p1.index[p1["PA"] >= min_bf]).intersection(st.index)
        for pid in ids:
            xs.append(float(st[pid]))
            ks.append(float(p0.loc[pid, "K"] / p0.loc[pid, "PA"]))
            ks1.append(float(p1.loc[pid, "K"] / p1.loc[pid, "PA"]))
            r = ra.loc[pid] if pid in ra.index else None
            ra1.append(float(9 * r["runs"] / max(r["outs"] / 3, 1)) if r is not None else np.nan)
    if len(xs) < 20:
        return {"n": len(xs), "available": False}
    xs, ks, ks1, ra1 = map(np.array, (xs, ks, ks1, ra1))
    ok = np.isfinite(ra1)

    def c(a, b):
        return round(float(np.corrcoef(a, b)[0, 1]), 4)
    return {"available": True, "n": int(len(xs)), "score": src, "stuff_vs_next_k": c(xs, ks1), "k_vs_next_k": c(ks, ks1),
            "stuff_vs_next_ra9": c(xs[ok], ra1[ok]), "k_vs_next_ra9": c(ks[ok], ra1[ok])}


def model_checks(level: str = "mlb") -> dict:
    out = {}
    try:
        out["projections"] = PJ.evaluate(level)
    except Exception as exc:  # noqa: BLE001
        out["projections"] = {"error": str(exc)}
    try:
        xw = _dio.sibling("xwoba")
        out["xwoba"] = xw.predictive_test(level) if xw and hasattr(xw, "predictive_test") else {"available": False}
    except Exception as exc:  # noqa: BLE001
        out["xwoba"] = {"error": str(exc)}
    try:
        out["stuff"] = stuff_validity(level)
    except Exception as exc:  # noqa: BLE001
        out["stuff"] = {"error": str(exc)}
    return out


def write_calibration(level: str = "mlb", games: dict | None = None, checks: dict | None = None, extra: dict | None = None):
    """Write docs/bullpen/data/<level>/calibration.json (keys: games, checks, + extra), merging with what exists."""
    import json
    p = _dio.data_root() / level / "calibration.json"
    cur = {}
    if p.exists():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cur = {}
    from datetime import datetime, timezone
    cur["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if games is not None:
        cur["games"] = games
    if checks is not None:
        cur["checks"] = checks
    for k, v in (extra or {}).items():
        cur[k] = v
    _dio.jdump(cur, p)
    return p


def refresh_market(res: dict, store: dict, sims: dict | None = None) -> dict:
    """
    Re-attach closing lines from a newer store to finished backtest rows (lines arrive after the games are
    priced; the model columns never change). Total and run-line probabilities need the simulated
    distributions, so only the moneyline, the line values and the market's own over / cover prices are refreshed
    unless the row already has the model's distribution-derived numbers for that line.
    """
    for r in res.get("games") or []:
        g = (store.get("games") or {}).get(r["gpk"])
        if not g:
            continue
        mk = _market(g)
        r["market"] = mk.get("p_home")
        if mk.get("total") is None:
            for k in ("line_total", "p_over", "mkt_p_over"):
                r.pop(k, None)
        if mk.get("rl_home") is None:
            for k in ("rl_home", "p_rl", "mkt_p_rl"):
                r.pop(k, None)
        if mk.get("total") is not None and r.get("line_total") == mk["total"]:
            r["mkt_p_over"] = mk.get("p_over")
        elif mk.get("total") is not None and r.get("total_dist"):
            r["line_total"] = mk["total"]
            r["p_over"] = G.p_over({"total_dist": r["total_dist"]}, mk["total"])
            r["mkt_p_over"] = mk.get("p_over")
        if mk.get("rl_home") is not None and r.get("margin_dist"):
            L = float(mk["rl_home"])
            r["rl_home"] = L
            r["p_rl"] = round(sum(v for k, v in r["margin_dist"].items() if int(k) + L > 0), 5)
            r["mkt_p_rl"] = mk.get("p_rl_home")
    return res
