"""
Walk-forward backtest of the game model and the season simulation; writes docs/gridiron/data/calibration.json.

Games (2006 onward; every regular-season and playoff game with a result)
-----------------------------------------------------------------------
Ratings: `game.walk_forward` (team_strength refitted before every week from that season's earlier games, preseason
prior chained from 1999). Coefficients: refitted before every week on all earlier walk-forward rows (earlier seasons
and this season's earlier weeks; key-number multipliers once per season). Predictors:
    model               the game model (margin features, season home field, discrete margin distribution)
    model_ratings_only  rating difference and a constant home field only (s, HFA refitted the same way)
    elo                 NFL Elo: K = 20, home 48 Elo points, margin multiplier ln(|m| + 1) * 2.2 / (0.001 dElo + 2.2),
                        a third of the way back to 1505 between seasons (FiveThirtyEight's published method)
    market_ml           closing moneyline (nflverse schedules, 2006 onward), de-vigged multiplicatively
    market_spread       closing spread through the same discrete margin distribution, sigma_m fitted on earlier games
    book:<name>         ESPN closing lines by book (store GAME.lines.books, 2017 onward) where the store has them
Ties are left out of win-probability scoring (n given). Scores: log-loss, Brier, reliability in 10 bins; margin RMSE.
Every predictor is also scored on the games with a closing moneyline ("vs_market"), so the comparison is like for like.

Against the spread: P(home covers the closing spread) from the model's margin distribution (push removed and
renormalised), scored against covers (pushes excluded): log-loss against ln 2, Brier, reliability, and the record
of the side the model prefers when P >= 0.55. Totals: P(over the closing total) from the discrete total distribution
with the season's total key multipliers likewise; RMSE of the model's total against the closing total's.
Since 21 Oct 2026 the published ATS and totals probabilities carry the market-line calibration (game.market_cover /
market_over): a Platt map fitted walk-forward on the earlier seasons' backtest predictions (applied once 500 earlier
games exist; earlier seasons stay raw). The uncalibrated scores are kept as `ats_raw` / `totals_raw`, and the map
fitted on every season (`market_calibration`) is what fit_c saves into game_params.json for the site.

Season odds: at checkpoints before weeks 1, 5, 10 and 14 of each completed season, 2,000 simulations with ratings and
coefficients fitted strictly before the checkpoint; scored against playoffs (played a postseason game), division
winner, #1 seed (bye), conference champion (Super Bowl appearance) and Super Bowl winner.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Iterable

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import season_sim as SS
from oddsmarkets.nfl.models import team_strength as TS

logger = logging.getLogger(__name__)

EPS = 1e-4
CHECK_WEEKS = (1, 5, 10, 14)


def score(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
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
            "reliability": rel}


def _strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "reliability"}


# ── Elo ──────────────────────────────────────────────────────────────────────

def elo_history(games: pd.DataFrame, k: float = 20.0, hfa: float = 48.0, revert: float = 1 / 3) -> pd.Series:
    """Pregame P(home win) by game_id (games sorted by date; neutral sites without home Elo)."""
    r: dict[str, float] = {}
    out = {}
    last_season = None
    for g in games.sort_values(["date", "game_id"]).itertuples(index=False):
        if g.season != last_season:
            r = {t: 1505.0 + (v - 1505.0) * (1 - revert) for t, v in r.items()}
            last_season = g.season
        h, a = D.franchise(g.home), D.franchise(g.away)
        rh, ra = r.get(h, 1505.0), r.get(a, 1505.0)
        d = rh - ra + (0.0 if g.neutral else hfa)
        p = 1.0 / (1.0 + 10 ** (-d / 400.0))
        out[g.game_id] = p
        if g.played and np.isfinite(g.margin):
            m = float(g.margin)
            y = 1.0 if m > 0 else (0.0 if m < 0 else 0.5)
            mult = math.log(abs(m) + 1) * 2.2 / ((d if m > 0 else -d) * 0.001 + 2.2) if m != 0 else 1.0
            delta = k * mult * (y - p)
            r[h], r[a] = rh + delta, ra - delta
    return pd.Series(out)


# ── books from the store ─────────────────────────────────────────────────────

def book_lines(seasons: Iterable[int]) -> pd.DataFrame:
    """Closing lines by ESPN book from the stores (GAME.lines.books): game_id, book, ml_home, ml_away, spread_home."""
    rows = []
    for s in seasons:
        st = D.load_store(s)
        for gid, g in (st.get("games") or {}).items():
            books = ((g or {}).get("lines") or {}).get("books") or []
            if isinstance(books, dict):
                books = [dict(v, provider=k) for k, v in books.items()]
            for b in books:
                if not isinstance(b, dict):
                    continue
                c = b.get("close") if isinstance(b.get("close"), dict) else b
                rows.append({"game_id": gid, "book": str(b.get("name") or b.get("provider") or b.get("book") or "book"),
                             "ml_home": c.get("ml_home"), "ml_away": c.get("ml_away"), "spread_home": c.get("spread_home")})
    return pd.DataFrame(rows)


# ── the backtest ─────────────────────────────────────────────────────────────

def _ratings_only_fit(rows: pd.DataFrame) -> tuple[float, float, float]:
    r = rows[rows["played"].astype(bool) & rows["margin"].notna()]
    if len(r) < 100:
        return 1.0, 2.0, 13.5
    X = np.column_stack([r["f_net"].to_numpy(float), r["f_hfa"].to_numpy(float)])
    y = r["margin"].to_numpy(float)
    b = TS.spd_inv(X.T @ X + np.eye(2) * 1e-6) @ (X.T @ y)
    sd = float(np.sqrt(np.mean((y - X @ b) ** 2)))
    return float(b[0]), float(b[1]), sd


def backtest(seasons: Iterable[int] | None = None, wf: pd.DataFrame | None = None, season_sims: int = 2000,
             check_weeks: Iterable[int] = CHECK_WEEKS, write: bool = True, seed: int = 0, units_of=None,
             games: pd.DataFrame | None = None) -> dict:
    t0 = time.perf_counter()
    if wf is None:
        path = D.c_cache() / "wf_rows.parquet"
        wf = pd.read_parquet(path) if path.exists() else GM.walk_forward(list(range(1999, 2027)))
    seasons = sorted(seasons) if seasons is not None else sorted(s for s in wf["season"].unique() if s >= 2006)
    wf = wf.sort_values(["season", "week", "date", "game_id"]).reset_index(drop=True)
    elo = elo_history(wf)
    preds: list[dict] = []
    params_by_season = {}
    keys_by_season: dict = {}
    tkeys_by_season: dict = {}
    for s in seasons:
        earlier_all = wf[wf["season"] < s]
        p_season = GM.fit_from_rows(earlier_all)            # includes key multipliers
        kk = GM.keys(p_season)
        keys_by_season[s] = p_season.get("keys")
        tkeys_by_season[s] = p_season.get("tkeys")
        params_by_season[str(s)] = {k: p_season.get(k) for k in ("s", "hfa", "hfa_trend", "div", "rest", "bye", "short",
                                                               "travel", "tz", "sigma", "sigma_market", "t_off", "wind",
                                                               "cold", "dome", "sigma_total", "n")}
        ws = wf[wf["season"] == s]
        for w in sorted(ws["week"].unique()):
            gw = ws[(ws["week"] == w) & ws["played"].astype(bool) & ws["margin"].notna()]
            if gw.empty:
                continue
            prior_rows = pd.concat([earlier_all, ws[ws["week"] < w]])
            p = GM.fit_from_rows(prior_rows, with_keys=False) if w > 1 else dict(p_season)
            p["keys"] = p_season["keys"]
            p["hfa_by_season"] = p.get("hfa_by_season") or {}
            so, ho, sdo = _ratings_only_fit(prior_rows)
            MF = GM._mf(gw)
            sea = gw["season"].to_numpy(int)
            mu = GM.mu_margin(MF, sea, p)
            playoff = gw["gtype"].astype(str).ne("REG").to_numpy()
            ph, pt = GM.win_probs(mu, p["sigma"], playoff, kk)
            mu_ro = so * MF["net"].to_numpy() + ho * MF["hfa"].to_numpy()
            ph_ro, pt_ro = GM.win_probs(mu_ro, sdo, playoff, kk)
            TF = GM._tf(gw)
            mt = GM.mu_total(TF, gw["base"].to_numpy(float), p)
            lines = gw["line"].to_numpy(float)
            sm = float(p.get("sigma_market") or p["sigma"])
            fin = np.isfinite(lines)
            p_spread = np.full(len(gw), np.nan)
            if fin.any():
                a_, b_ = GM.win_probs(lines[fin], sm, False, kk)
                p_spread[fin] = a_ + b_ / 2
            for i, r in enumerate(gw.itertuples(index=False)):
                rec = {"game_id": r.game_id, "season": int(r.season), "week": int(r.week), "gtype": r.gtype,
                       "margin": float(r.margin), "total": float(r.total), "mu": float(mu[i]), "mu_total": float(mt[i]),
                       "sigma": p["sigma"], "sigma_total": p["sigma_total"], "sigma_m": p.get("sigma_market") or p["sigma"],
                       "p_model": float(ph[i] + pt[i] / 2), "p_ro": float(ph_ro[i] + pt_ro[i] / 2),
                       "p_elo": float(elo.get(r.game_id, np.nan)), "line": float(r.line) if np.isfinite(r.line) else np.nan,
                       "total_line": float(r.total_line) if np.isfinite(r.total_line) else np.nan,
                       "ml_home": r.ml_home, "ml_away": r.ml_away, "p_spread": float(p_spread[i]),
                       "keys_season": s}
                preds.append(rec)
    P = pd.DataFrame(preds)
    kk_by = {int(s): GM.keys({"keys": v}) for s, v in keys_by_season.items()}
    P["p_ml"] = [GM.ml_to_p(a, b) for a, b in zip(P["ml_home"], P["ml_away"])]
    P["p_ml"] = P["p_ml"].astype(float)
    decided = P["margin"] != 0
    y = (P["margin"] > 0).astype(float)
    metrics, vs_market, per_season = {}, {}, {}
    cols = {"model": "p_model", "model_ratings_only": "p_ro", "elo": "p_elo", "market_ml": "p_ml", "market_spread": "p_spread"}
    has_ml = P["p_ml"].notna() & decided
    for name, c in cols.items():
        m = P[c].notna() & decided
        metrics[name] = score(P.loc[m, c], y[m])
        mm = m & has_ml
        vs_market[name] = _strip(score(P.loc[mm, c], y[mm]))
    for s, g in P.groupby("season"):
        dd = g["margin"] != 0
        yy = (g["margin"] > 0).astype(float)
        per_season[str(s)] = {}
        for name, c in cols.items():
            m = g[c].notna() & dd
            if m.sum():
                per_season[str(s)][name] = _strip(score(g.loc[m, c], yy[m]))
    # ESPN books
    books = {}
    bl = book_lines(seasons)
    if not bl.empty:
        bl["p"] = [GM.ml_to_p(a, b) for a, b in zip(bl["ml_home"], bl["ml_away"])]
        bl = bl.merge(P[["game_id", "margin", "p_model"]], on="game_id")
        bl = bl[bl["p"].notna() & (bl["margin"] != 0)]
        for b, g in bl.groupby("book"):
            yy = (g["margin"] > 0).astype(float)
            books[b] = {"book": _strip(score(g["p"].astype(float), yy)), "model_same_games": _strip(score(g["p_model"], yy))}
    # margin RMSE
    def rmse(a, b):
        a, b = np.asarray(a, float), np.asarray(b, float)
        m = np.isfinite(a) & np.isfinite(b)
        return round(float(np.sqrt(np.mean((a[m] - b[m]) ** 2))), 4) if m.any() else None
    has_line = P["line"].notna()
    margin_rmse = {"model": rmse(P["mu"], P["margin"]), "model_on_line_games": rmse(P.loc[has_line, "mu"], P.loc[has_line, "margin"]),
                   "market_line": rmse(P.loc[has_line, "line"], P.loc[has_line, "margin"])}
    # ATS
    ats_rows, tot_rows = [], []
    tk_by = {int(s): GM.total_keys({"tkeys": v}) for s, v in tkeys_by_season.items()}
    for r in P[has_line].itertuples(index=False):
        spread_home = -r.line
        c = GM.cover_prob(r.mu, r.sigma, spread_home, kk_by.get(int(r.season)))
        if abs(r.margin + spread_home) < 1e-9:
            continue
        pc = c["home"] / max(c["home"] + c["away"], 1e-9)
        ats_rows.append((pc, 1.0 if r.margin + spread_home > 0 else 0.0, r.season))
    for r in P[P["total_line"].notna()].itertuples(index=False):
        c = GM.total_prob(r.mu_total, r.sigma_total, r.total_line, tk_by.get(int(r.season)))
        if abs(r.total - r.total_line) < 1e-9:
            continue
        po = c["over"] / max(c["over"] + c["under"], 1e-9)
        tot_rows.append((po, 1.0 if r.total > r.total_line else 0.0, r.season))
    ats_cal, cal_ats = market_calibration(ats_rows)
    tot_cal, cal_tot = market_calibration(tot_rows)
    ats = _side_summary(ats_cal)
    totals = _side_summary(tot_cal)
    ats_raw = _side_summary(ats_rows)
    totals_raw = _side_summary(tot_rows)
    totals["rmse_model_total"] = rmse(P.loc[P["total_line"].notna(), "mu_total"], P.loc[P["total_line"].notna(), "total"])
    totals["rmse_market_total"] = rmse(P.loc[P["total_line"].notna(), "total_line"], P.loc[P["total_line"].notna(), "total"])
    # home field by season: mean of (mu - s * net) over non-neutral games, from the season's final coefficients
    hfa = hfa_by_season(wf, seasons)
    # season simulation calibration
    sim = season_calibration(seasons, wf, season_sims, check_weeks, seed, units_of=units_of, games=games) if season_sims > 0 else {}
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "model_version": GM.VERSION,
           "seasons": [int(s) for s in seasons], "games": int(len(P)), "ties_excluded": int((~decided).sum()),
           "metrics": metrics, "metrics_vs_market": vs_market, "per_season": per_season, "books": books,
           "margin_rmse": margin_rmse, "ats": ats, "totals": totals, "ats_raw": _strip_season(ats_raw),
           "totals_raw": _strip_season(totals_raw), "market_calibration": {"cal_ats": cal_ats, "cal_tot": cal_tot},
           "hfa_by_season": hfa,
           "params_by_season": params_by_season, "season_sim": sim, "runtime_s": round(time.perf_counter() - t0, 1)}
    if write:
        write_calibration(out)
        try:
            P.to_parquet(D.c_cache() / "backtest_games.parquet", index=False)
        except OSError:
            pass
    return out


def _platt_fit(p: np.ndarray, y: np.ndarray) -> list[float]:
    """(a, b) of y ~ Bernoulli(expit(a + b logit p)), Newton steps."""
    q = np.clip(p, EPS, 1 - EPS)
    x = np.log(q / (1 - q))
    a, b = 0.0, 1.0
    for _ in range(50):
        z = 1 / (1 + np.exp(-(a + b * x)))
        w = z * (1 - z)
        g = np.array([np.sum(y - z), np.sum((y - z) * x)])
        H = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]]) + np.eye(2) * 1e-9
        st = np.linalg.solve(H, g)
        a, b = a + st[0], b + st[1]
        if np.abs(st).max() < 1e-10:
            break
    return [round(float(a), 5), round(float(b), 5)]


def market_calibration(rows: list[tuple], min_rows: int = 500) -> tuple[list[tuple], list[float] | None]:
    """Walk-forward Platt map of (p, y, season) rows: each season's p mapped with (a, b) fitted on the earlier
    seasons (seasons with fewer than min_rows earlier rows stay raw). Returns the mapped rows and the map fitted on
    every row (what the site uses)."""
    if not rows:
        return rows, None
    a = np.array(rows, float)
    p, y, sea = a[:, 0], a[:, 1], a[:, 2]
    out = p.copy()
    for s in np.unique(sea):
        tr = sea < s
        if tr.sum() < min_rows:
            continue
        ab = _platt_fit(p[tr], y[tr])
        te = sea == s
        out[te] = [GM.platt(v, ab) for v in p[te]]
    return [(float(o), float(yy), ss) for o, yy, ss in zip(out, y, sea)], (_platt_fit(p, y) if len(p) >= min_rows else None)


def _strip_season(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("by_season", "reliability")}


def _side_summary(rows: list[tuple]) -> dict:
    if not rows:
        return {"n": 0}
    a = np.array(rows, float)
    p, y = a[:, 0], a[:, 1]
    sc = score(p, y)
    sc["logloss_coin"] = round(math.log(2), 5)
    lean = np.abs(p - 0.5) >= 0.05
    pick = np.where(p >= 0.5, y, 1 - y)
    sc["picks_p55"] = {"n": int(lean.sum()), "win_rate": round(float(pick[lean].mean()), 4) if lean.any() else None}
    sc["by_season"] = {str(int(s)): {"n": int((a[:, 2] == s).sum()),
                                     "logloss": round(float(-np.mean(np.where(y[a[:, 2] == s] > 0, np.log(np.clip(p[a[:, 2] == s], EPS, 1)),
                                                                              np.log(np.clip(1 - p[a[:, 2] == s], EPS, 1))))), 5)}
                       for s in np.unique(a[:, 2])}
    return sc


def hfa_by_season(wf: pd.DataFrame, seasons) -> dict:
    """Estimated home advantage (points) per season: fitted on all rows (in-sample, descriptive), averaged over the
    season's non-neutral games including the travel / time-zone / division terms."""
    p = GM.fit_from_rows(wf[wf["season"] >= min(seasons)])
    out = {}
    for s in seasons:
        g = wf[(wf["season"] == s) & ~wf["neutral"].astype(bool)]
        if g.empty:
            continue
        MF = GM._mf(g)
        mu = GM.mu_margin(MF, g["season"].to_numpy(int), p)
        out[str(s)] = round(float(np.mean(mu - p["s"] * MF["net"].to_numpy())), 3)
    return out


def season_outcomes(games: pd.DataFrame, season: int) -> dict | None:
    g = games[games["season"] == season]
    post = g[g["gtype"] != "REG"]
    if post.empty or not post["played"].all():
        return None
    sb = post[post["gtype"] == "SB"]
    if sb.empty:
        return None
    r = sb.iloc[0]
    champ = r["home"] if r["hs"] > r["as_"] else r["away"]
    playoffs = set(post["home"]) | set(post["away"])
    out = {"playoffs": playoffs, "conf": {r["home"], r["away"]}, "sb": champ}
    try:
        from oddsmarkets.nfl import tiebreak as TB
        rows = [{"home": x.home, "away": x.away, "hs": x.hs, "as": x.as_, "gtype": "REG"}
                for x in g[(g["gtype"] == "REG") & g["played"]].itertuples(index=False)]
        seeds = TB.Table(rows, season).seeds()
        out["div"] = {t for c in seeds.values() for t in c["division_winners"]}
        out["bye"] = {t for c in seeds.values() for t in c["byes"]}
    except Exception:  # noqa: BLE001
        out["div"], out["bye"] = set(), set()
    return out


def season_calibration(seasons, wf: pd.DataFrame, n: int, check_weeks, seed: int, units_of=None,
                       games: pd.DataFrame | None = None) -> dict:
    units_of = units_of or D.unit_rows
    G = games if games is not None else D.games_frame([s for s in range(min(seasons) - 1, max(seasons) + 1)])
    pts = {k: [] for k in ("playoffs", "div", "bye", "conf", "sb")}
    runs = []
    p_ts = TS.params()
    last, book = None, {}
    chain_seasons = list(range(min(seasons) - 3, max(seasons) + 1))
    for s in chain_seasons:
        u = units_of(s)
        prior = TS.preseason_prior(last, s, p_ts, book, TS.continuity(s))
        if s in seasons:
            out = season_outcomes(G, s)
            gs = G[(G["season"] == s) & (G["gtype"] == "REG")]
            if out is not None and not gs.empty:
                for w in check_weeks:
                    wk = gs[gs["week"] == w]
                    if wk.empty:
                        continue
                    thr = wk["date"].min()
                    r = TS.fit(u, s, thr, prior, p_ts, teams=sorted(set(gs["home"]) | set(gs["away"])))
                    rd = r.as_dict()
                    rd["qb_prior"] = prior["qbs"]
                    prm = GM.fit_from_rows(wf[(wf["season"] < s) | ((wf["season"] == s) & (wf["week"] < w))])
                    t1 = time.perf_counter()
                    try:
                        res = SS.simulate(s, n=n, seed=seed, state={"games": G[G["season"].isin([s - 1, s])],
                                                                   "through": thr, "ratings": rd, "params": prm})
                    except Exception as exc:  # noqa: BLE001
                        runs.append({"season": s, "week": w, "error": str(exc)})
                        continue
                    for t, v in res["teams"].items():
                        pts["playoffs"].append((v["p_playoffs"], int(t in out["playoffs"]), s, w))
                        pts["div"].append((v["p_div"], int(t in out["div"]), s, w))
                        pts["bye"].append((v["p_bye"], int(t in out["bye"]), s, w))
                        pts["conf"].append((v["p_conf"], int(t in out["conf"]), s, w))
                        pts["sb"].append((v["p_sb"], int(t == out["sb"]), s, w))
                    runs.append({"season": s, "week": w, "runtime_s": round(time.perf_counter() - t1, 2),
                                 "p_champion": res["teams"].get(out["sb"], {}).get("p_sb")})
        end = TS.fit(u, s, None, prior, p_ts)
        TS.update_qb_book(book, end)
        last = end
        del u
    res = {}
    for k, v in pts.items():
        if not v:
            continue
        a = np.array([(x[0], x[1]) for x in v], float)
        res[k] = score(a[:, 0], a[:, 1])
        by_w = {}
        for w in check_weeks:
            sel = [(x[0], x[1]) for x in v if x[3] == w]
            if sel:
                b = np.array(sel, float)
                by_w[str(w)] = _strip(score(b[:, 0], b[:, 1]))
        res[k]["by_week"] = by_w
    return {"metrics": res, "runs": runs, "n_sims": n, "check_weeks": list(check_weeks)}


def write_calibration(out: dict) -> None:
    """docs/gridiron/data/calibration.json, merged into an existing file (other builders' sections kept)."""
    try:
        from oddsmarkets.nfl import store as A_store
        path = A_store.calibration_path()
    except Exception:  # noqa: BLE001
        path = D.data_root() / "calibration.json"
    cur = D.read_json(path) or {}
    cur["game_model"] = {k: v for k, v in out.items() if k != "season_sim"}
    cur["season_sim"] = out.get("season_sim")
    cur["updated_at"] = out["generated_at"]
    D.write_json(path, cur)


def summary_table(bt: dict) -> list[dict]:
    rows = []
    for scope in ("metrics", "metrics_vs_market"):
        for m, v in (bt.get(scope) or {}).items():
            if v.get("n"):
                rows.append({"scope": "all" if scope == "metrics" else "ml_games", "model": m, "logloss": v.get("logloss"),
                             "brier": v.get("brier"), "n": v["n"]})
    return rows
