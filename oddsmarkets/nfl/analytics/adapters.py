"""
Adapters between builders B's and C's models and this layer. Every call is isolated (a model that is missing, raises
or answers in an unexpected shape gives None / {} and is listed in the context's model_errors) and every answer is
normalised to the shapes the catalogues and pages use.

Per play (joined into SeasonContext.plays() on game_id, play_id): ep_ours, epa_ours (ep.for_season), wp_ours
(wp.for_season, the possession team's WP) and the fourth-down columns fd_rec, fd_choice, fd_wp_go, fd_wp_punt,
fd_wp_fg, fd_p_convert, fd_p_fg, fd_wp_lost, fd_go_gain (fourth_down.for_season()["decisions"]).
Per player (`player_tables`): value (player_value, adjusted value summed over roles), composite (qb), cpoe (completion,
percentage points), croe (completion receivers), yacoe (yac), ryoe (ryoe, per carry), pressure_rate / ttt (pressure),
fg_oe / pts_oe (kicking kickers), net_oe (kicking punters, yards over expected per punt).
Per team / season: team_strength (ratings and a week-by-week history), game prices (game.predict_frame on the store's
games with _cdata.add_context), season_sim, awards, markets, backtest.
"""
from __future__ import annotations

import importlib
import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics.context import frame_of

logger = logging.getLogger(__name__)


def _module(name: str):
    try:
        return importlib.import_module(f"oddsmarkets.nfl.models.{name}")
    except Exception as exc:                                     # noqa: BLE001
        logger.debug("model module %s: %s", name, exc)
        return None


def _usable(res: Any) -> bool:
    return not (isinstance(res, dict) and (res.get("ok") is False or res.get("available") is False))


# ---------------------------------------------------------------------------------------------- plays

FD_MAP = {"fd_rec": "rec", "fd_choice": "choice", "fd_wp_go": "wp_go", "fd_wp_punt": "wp_punt", "fd_wp_fg": "wp_fg",
          "fd_p_convert": "p_conv", "fd_p_fg": "p_fg", "fd_wp_lost": "wp_lost", "fd_go_gain": "go_gain", "fd_exp_go": "exp_go"}


def play_scores(ctx) -> pd.DataFrame | None:
    """Per-play model columns for the season, merged on (game_id, play_id)."""
    if not ctx.use_models:
        return None
    parts = []
    for mod, cols in (("ep", {"ep_ours": "ep_ours", "epa_ours": "epa_ours"}), ("wp", {"wp_ours": "wp_ours"})):
        if _module(mod) is None:
            ctx.model_errors.setdefault(mod, "model module not available")
            continue
        res = ctx.model(mod)
        if mod == "wp" and not _usable(res):
            res = _wp_direct(ctx) or res
        df = frame_of(res)
        if df is None or not len(df) or "game_id" not in df:
            if _usable(res):
                ctx.model_errors.setdefault(mod, "no per-play rows (model not fitted?)")
            continue
        sel = pd.DataFrame({"game_id": df["game_id"].astype(str), "play_id": pd.to_numeric(df["play_id"], errors="coerce")})
        for ours, theirs in cols.items():
            if theirs in df:
                sel[ours] = pd.to_numeric(df[theirs], errors="coerce").to_numpy()
        if sel.shape[1] > 2 and sel.iloc[:, 2:].notna().any().any():
            parts.append(sel.drop_duplicates(["game_id", "play_id"]))
        else:
            ctx.model_errors.setdefault(mod, "per-play values all null (model not fitted?)")
    for mod, col, ours in (("completion", "cp_ours", "cp_ours"), ("yac", "xyac", "xyac_ours"), ("ryoe", "xry", "xrush_ours")):
        m = _module(mod)
        f = getattr(m, "season_rows", None) if m is not None else None
        if f is None:
            continue
        try:
            t = f(ctx.season)
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors[f"{mod} rows"] = f"{type(exc).__name__}: {exc}"
            continue
        if t is None or not len(t) or col not in t or "game_id" not in t:
            continue
        sel = pd.DataFrame({"game_id": t["game_id"].astype(str), "play_id": pd.to_numeric(t["play_id"], errors="coerce"),
                            ours: pd.to_numeric(t[col], errors="coerce").to_numpy()})
        if sel[ours].notna().any():
            parts.append(sel.drop_duplicates(["game_id", "play_id"]))
        del t
    if _module("fourth_down") is not None:
        res = ctx.model("fourth_down")
        if _usable(res) and isinstance(res, dict):
            df = frame_of(res.get("decisions"))
            if df is not None and len(df) and "game_id" in df:
                sel = pd.DataFrame({"game_id": df["game_id"].astype(str), "play_id": pd.to_numeric(df["play_id"], errors="coerce")})
                for ours, theirs in FD_MAP.items():
                    if theirs in df:
                        sel[ours] = df[theirs].to_numpy()
                parts.append(sel.drop_duplicates(["game_id", "play_id"]))
    if not parts:
        return None
    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on=["game_id", "play_id"], how="outer")
    return out


def _wp_direct(ctx) -> pd.DataFrame | None:
    """wp.for_season's own steps with a float64 column (its float32 cached column rejects float64 predictions under
    pandas 3); used only when for_season raised."""
    WP = _module("wp")
    try:
        from oddsmarkets.nfl.models import _io
        d = _io.plays(ctx.season)
        if d is None or not len(d):
            return None
        m = WP.is_model_play(d)
        s = d[m]
        X = WP.features(d)[m]
        base = pd.DataFrame({"game_id": s["game_id"].astype(str).to_numpy(),
                             "play_id": pd.to_numeric(s["play_id"], errors="coerce").to_numpy(float)})
        p = _io.cache_root() / "wp_oof" / f"{int(ctx.season)}.parquet"
        if p.exists():
            o = pd.read_parquet(p)
            o["wp_ours"] = o["wp_ours"].astype("float64")
            base = base.merge(o, on=["game_id", "play_id"], how="left")
        else:
            base["wp_ours"] = float("nan")
        base["wp_ours"] = base["wp_ours"].astype("float64")
        miss = base["wp_ours"].isna().to_numpy()
        f = WP.current_fit()
        if miss.any() and f is not None:
            base.loc[miss, "wp_ours"] = np.asarray(WP.predict(f, X[miss]), dtype="float64")
        ctx.model_errors["wp"] = "for_season raised (float32 cache column); scored by the adapter with the same fit"
        return base
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["wp direct"] = f"{type(exc).__name__}: {exc}"
        return None


def fourth_tables(ctx) -> dict | None:
    """fourth_down.for_season's coach / team tables and tries, when it scores."""
    if _module("fourth_down") is None:
        return None
    res = ctx.model("fourth_down")
    return res if _usable(res) and isinstance(res, dict) else None


# ---------------------------------------------------------------------------------------------- players

def _records(res: Any, key: str) -> list[dict]:
    if not _usable(res) or not isinstance(res, dict):
        return []
    v = res.get(key)
    df = frame_of(v)
    return df.to_dict("records") if df is not None else []


def _put(out: dict, metric: str, rows: list[dict], idcol: str, col: str, scale: float = 1.0) -> None:
    d = {}
    for r in rows:
        p, v = an.sid(r.get(idcol)), an.fnum(r.get(col))
        if p and v is not None:
            d[p] = v * scale
    if d:
        out[metric] = d


def player_tables(ctx) -> dict[str, dict[str, float]]:
    """{metric: {pid: value}} from builder B's player-level models (absent or unfitted models give no entry)."""
    out: dict[str, dict[str, float]] = {}
    if not ctx.use_models:
        return out
    if _module("player_value") is not None:
        rows = _records(ctx.model("player_value"), "players")
        tot: dict[str, float] = {}
        for r in rows:
            p, v = an.sid(r.get("player")), an.fnum(r.get("adj_value"))
            if p and v is not None:
                tot[p] = tot.get(p, 0.0) + v
        if tot:
            out["value"] = tot
    if _module("qb") is not None:
        res = ctx.model("qb")
        rows = frame_of(res).to_dict("records") if isinstance(res, list) and res else []
        if not rows and isinstance(res, dict):
            rows = next((_records(res, k) for k in ("qbs", "players", "passers") if _records(res, k)), [])
        if rows:
            idc = next((c for c in ("qb", "passer", "player", "pid") if c in rows[0]), None)
            if idc and "composite" in rows[0]:
                _put(out, "composite", rows, idc, "composite")
    if _module("completion") is not None:
        res = ctx.model("completion")
        _put(out, "cpoe", _records(res, "passers"), "passer", "cpoe")
        # completion.py reports CROE in percentage points; the catalogue metric (fmt "pct") and the play-by-play fallback
        # are fractions, so the model's value is scaled to a fraction (15 Oct 2026: the players page showed 1780% for +17.8 pp)
        _put(out, "croe", _records(res, "receivers"), "receiver", "croe", scale=0.01)
    if _module("yac") is not None:
        _put(out, "yacoe", _records(ctx.model("yac"), "receivers"), "receiver", "yacoe")
    if _module("ryoe") is not None:
        _put(out, "ryoe", _records(ctx.model("ryoe"), "rushers"), "rusher", "ryoe_per_att")
    if _module("pressure") is not None:
        res = ctx.model("pressure")
        qbs = _records(res, "qbs")
        _put(out, "pressure_rate", qbs, "passer", "pressure_rate")
        _put(out, "ttt", qbs, "passer", "ttt")
    if _module("kicking") is not None:
        res = ctx.model("kicking")
        k = _records(res, "kickers")
        _put(out, "fg_oe", k, "kicker", "fgoe")
        _put(out, "pts_oe", k, "kicker", "pts_oe")
        _put(out, "net_oe", _records(res, "punters"), "punter", "per_punt")
    return out


def player_value_season(ctx, season: int) -> dict | None:
    """player_value.for_season for another season (last season's rates for the value pages), isolated."""
    if _module("player_value") is None or not ctx.use_models:
        return None
    try:
        res = _module("player_value").for_season(int(season))
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors[f"player_value {season}"] = f"{type(exc).__name__}: {exc}"
        return None
    return res if _usable(res) else None


def team_pressure(ctx) -> dict[str, dict]:
    """{team: {"pressure_allowed", "pressure_rate_def", "blitz_rate_def", "sroe"}} from builder B's pressure model."""
    if _module("pressure") is None or not ctx.use_models:
        return {}
    res = ctx.model("pressure")
    out: dict[str, dict] = {}
    for r in _records(res, "team_offense"):
        out.setdefault(str(r.get("team")), {})["pressure_allowed"] = an.fnum(r.get("pressure_rate"))
    for r in _records(res, "team_defense"):
        e = out.setdefault(str(r.get("team")), {})
        e["pressure_rate_def"] = an.fnum(r.get("pressure_rate"))
        e["sroe_def"] = an.fnum(r.get("sroe"))
    return out


# ---------------------------------------------------------------------------------------------- teams

def team_ratings(ctx, history: bool = True) -> dict | None:
    """{"teams": {abbr: {overall, off, def, pass_off, rush_off, pass_def, rush_def, st, qb, qb_val, se}}, "history":
    {abbr: [[week, net, off, def], ...]}, "source", "units"} from builder C's team_strength (points per game against an
    average team for overall / off / def / st; EPA per play edges for the pass and rush units)."""
    if _module("team_strength") is None or not ctx.use_models:
        return None
    res = ctx.model("team_strength")
    if not _usable(res) or not isinstance(res, dict) or not res.get("teams"):
        return None
    teams = {}
    for t, v in res["teams"].items():
        teams[t] = {"overall": an.fnum(v.get("net")), "off": an.fnum(v.get("off")), "def": an.fnum(v.get("def")),
                    "pass_off": an.fnum(v.get("pass_off")), "rush_off": an.fnum(v.get("rush_off")), "pass_def": an.fnum(v.get("pass_def")),
                    "rush_def": an.fnum(v.get("rush_def")), "st": an.fnum(v.get("st")), "qb": v.get("qb"), "qb_val": an.fnum(v.get("qb_val")),
                    "se": an.fnum(v.get("se_net")), "games": v.get("games")}
    hist: dict[str, list] = {}
    if history:
        try:
            hist = _ts_history(ctx)
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["team_strength history"] = f"{type(exc).__name__}: {exc}"
    return {"teams": teams, "history": hist, "source": "team_strength", "version": getattr(_module("team_strength"), "VERSION", None),
            "units": "points per game against an average team (pass / rush units: EPA per play edges)", "league": res.get("league")}


def _ts_history(ctx) -> dict[str, list]:
    """Ratings through the end of each completed week (team_strength.for_season(season, through=day after the week))."""
    TS = _module("team_strength")
    by_week: dict[int, str] = {}
    for g in ctx.games.values():
        if g.get("gtype") == "REG" and g.get("status") == "final" and g.get("date"):
            w = int(g.get("week") or 0)
            by_week[w] = max(by_week.get(w, ""), str(g["date"])[:10])
    out: dict[str, list] = {}
    from datetime import date as _d
    for w in sorted(by_week):
        through = (_d.fromisoformat(by_week[w]) + timedelta(days=2)).isoformat()
        rd = TS.for_season(ctx.season, through=through)
        for t, v in (rd.get("teams") or {}).items():
            out.setdefault(t, []).append([w, an.rnd(v.get("net"), 2), an.rnd(v.get("off"), 2), an.rnd(v.get("def"), 2)])
    return out


# ---------------------------------------------------------------------------------------------- games

def game_prices(ctx, games: list[dict]) -> dict[str, dict]:
    """{game_id: {"p_home","p_tie","spread","total","margin","home_pts","away_pts","sigma","sigma_total","net_h","net_a",
    "source"}}: builder C's game model on the season's store games (context: rest, travel, time zones) under the current
    team-strength ratings. spread = the home team's fair betting line (negative = home favoured)."""
    mod = _module("game")
    if mod is None or not games or not ctx.use_models:
        return {}
    for fn in ("price_games", "for_games"):
        f = getattr(mod, fn, None)
        if f is not None:
            res = f(ctx.season, games)
            items = res.items() if isinstance(res, dict) else ((str(r.get("game_id")), r) for r in (res or []))
            return {str(gid): _price(r) for gid, r in items if isinstance(r, dict)}
    rd = ctx.model("team_strength")
    if not _usable(rd) or not isinstance(rd, dict) or not rd.get("teams"):
        ctx.model_errors["game"] = "no team-strength ratings"
        return {}
    from oddsmarkets.nfl.models import _cdata as D
    df = D.games_from_store(ctx.store, ctx.season)
    if df is None or not len(df):
        return {}
    df = D.add_context(df)
    want = {g["game_id"] for g in games}
    sub = df[df["game_id"].astype(str).isin(want)]
    if not len(sub):
        return {}
    pf = mod.predict_frame(sub, rd)
    out = {}
    for r in pf.to_dict("records"):
        out[str(r["game_id"])] = _price({"p_home": r.get("p_home"), "p_tie": r.get("p_tie"), "spread": r.get("spread_fair"),
                                         "margin": r.get("mu"), "total": r.get("mu_total"), "home_pts": r.get("pts_h"),
                                         "away_pts": r.get("pts_a"), "sigma": r.get("sigma"), "sigma_total": r.get("sigma_total"),
                                         "net_h": r.get("net_h"), "net_a": r.get("net_a"), "source": "game"})
    return out


def walk_forward_prices(ctx) -> dict[str, dict]:
    """Pre-game prices of the season's games from builder C's walk-forward (ratings fitted strictly before each week,
    preseason prior from the season before): {game_id: price} with source "walk_forward"; cached on the store, the
    play-by-play files and the game parameters."""
    GMm, TS = _module("game"), _module("team_strength")
    if GMm is None or TS is None or not ctx.use_models or not hasattr(GMm, "walk_forward"):
        return {}
    import hashlib
    from oddsmarkets.nfl.analytics.context import release_files
    parts = [str(getattr(GMm, "VERSION", "")), str(getattr(TS, "VERSION", "")), "wf-1"]
    for q in [an.store_path(ctx.season)] + release_files("pbp", ctx.season) + release_files("pbp", ctx.season - 1):
        try:
            st = q.stat()
            parts.append(f"{q.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{q.name}:-")
    key = hashlib.sha1("|".join(parts + [repr(sorted(GMm.params().items()))]).encode()).hexdigest()[:16]
    cp = an.an_cache() / "walk_forward" / f"{ctx.season}_{key}.json"
    got = an.read_json(cp)
    if isinstance(got, dict):
        return got
    rows = GMm.walk_forward([ctx.season], first=max(an.FIRST_SEASON, ctx.season - 2))
    if rows is None or not len(rows):
        return {}
    p = GMm.params()
    seasons = rows["season"].to_numpy(int)
    mu = GMm.mu_margin(GMm.margin_features(rows), seasons, p)
    tot = GMm.mu_total(GMm.total_features(rows), rows["base"].to_numpy(float), p)
    playoff = rows["gtype"].astype(str).str.upper().ne("REG").to_numpy()
    ph, pt = GMm.win_probs(mu, p["sigma"], playoff, GMm.keys(p))
    out = {}
    for i, gid in enumerate(rows["game_id"].astype(str)):
        out[gid] = _price({"p_home": float(ph[i]), "p_tie": float(pt[i]), "margin": float(mu[i]), "total": float(tot[i]),
                           "home_pts": float((tot[i] + mu[i]) / 2), "away_pts": float((tot[i] - mu[i]) / 2), "sigma": float(p["sigma"]),
                           "sigma_total": float(p["sigma_total"]), "source": "walk_forward"})
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        for old in cp.parent.glob(f"{ctx.season}_*.json"):
            old.unlink(missing_ok=True)
        an.write_json(cp, out)
    except OSError:
        pass
    return out


def price_dist(ctx, pr: dict, g: dict, n: int = 10000) -> dict | None:
    """Score distributions for a priced game: the game model's margin pmf (with its key numbers) and total pmf, cover
    and over probabilities against the store's line, and builder C's drive simulation calibrated to the model's team
    points (team-score quantiles, overtime, margin pmf)."""
    GMm = _module("game")
    if GMm is None or not pr or pr.get("margin") is None or pr.get("total") is None:
        return None
    from scipy.special import ndtr
    p = GMm.params()
    kk = GMm.keys(p)
    mu, sig = float(pr["margin"]), float(pr.get("sigma") or p["sigma"])
    mt, st = float(pr["total"]), float(pr.get("sigma_total") or p["sigma_total"])
    P = GMm.margin_pmf(mu, sig, kk)[0]
    sup = np.asarray(GMm.SUPPORT)
    keep = np.abs(sup) <= 40
    tl = np.arange(10, 91)
    if hasattr(GMm, "total_pmf"):                                  # discrete total with key multipliers (21 Oct 2026)
        T = GMm.total_pmf(mt, st, GMm.total_keys(p))[0][10:91]
    else:
        T = ndtr((tl + 0.5 - mt) / st) - ndtr((tl - 0.5 - mt) / st)
    out: dict = {"margin": {"lo": int(sup[keep][0]), "p": [round(float(x), 5) for x in P[keep]]},
                 "total": {"lo": 10, "p": [round(float(x), 5) for x in T / T.sum()]},
                 "margin_sd": round(sig, 2), "total_sd": round(st, 2)}
    ln = g.get("lines") or {}
    # cover / over at the market's own line: the market-line calibrated probabilities (game.market_cover / market_over)
    cov = getattr(GMm, "market_cover", None) or (lambda m_, s_, l_, k_: GMm.cover_prob(m_, s_, l_, k_))
    ovr = getattr(GMm, "market_over", None) or (lambda m_, s_, l_: GMm.total_prob(m_, s_, l_))
    if ln.get("spread_home") is not None:
        out["cover"] = {k: round(v, 4) for k, v in cov(mu, sig, float(ln["spread_home"]), kk).items()}
    if ln.get("total") is not None:
        out["over"] = {k: round(v, 4) for k, v in ovr(mt, st, float(ln["total"])).items()}
    DS = _module("drive_sim")
    if DS is not None and n > 0 and pr.get("home_pts") is not None and pr.get("away_pts") is not None:
        try:
            r = DS.price(float(pr["home_pts"]), float(pr["away_pts"]), ctx.season, str(g.get("gtype")) != "REG", n=n,
                         spread_home=ln.get("spread_home"), total_line=ln.get("total"))
            out["drive_sim"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()
                                if k in ("p_home", "p_tie", "p_away", "mean_margin", "mean_total", "sd_margin", "sd_total", "pts_h", "pts_a",
                                         "p_ot", "margin_pmf", "total_q", "team_q", "cover", "over")}
            out["drive_sim"]["n"] = n
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["drive_sim"] = f"{type(exc).__name__}: {exc}"
    return out


def _price(r: dict) -> dict:
    p = an.fnum(r.get("p_home") if r.get("p_home") is not None else r.get("home_win"))
    spread = an.fnum(next((r[k] for k in ("spread", "spread_fair", "spread_home") if r.get(k) is not None), None))
    margin = an.fnum(next((r[k] for k in ("margin", "mu", "exp_margin") if r.get(k) is not None), None))
    if spread is None and margin is not None:
        spread = -margin
    if margin is None and spread is not None:
        margin = -spread
    total = an.fnum(next((r[k] for k in ("total", "mu_total", "exp_total") if r.get(k) is not None), None))
    out = {"p_home": an.rnd(p, 4), "spread": an.rnd(spread, 2), "margin": an.rnd(margin, 2), "total": an.rnd(total, 2)}
    for k in ("p_tie", "home_pts", "away_pts", "sigma", "sigma_total", "net_h", "net_a", "dist", "scores", "team_totals", "source"):
        if r.get(k) is not None:
            out[k] = an.rnd(r[k], 4) if isinstance(r[k], float) else r[k]
    return out


LIVE = ("live", "in", "in_progress", "status_in_progress")


def live_wp(ctx, g: dict, rec: dict | None, pregame: dict | None) -> dict | None:
    """Our live home WP for a game in progress (builder C's live.live_wp on the ESPN record, pre-game margin blended)."""
    mod = _module("live")
    if mod is None or not rec or not ctx.use_models:
        return None
    try:
        return mod.live_wp(rec, pregame or {}, ctx.season, g.get("home"))
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["live"] = f"{type(exc).__name__}: {exc}"
        return None


def live_series(ctx, g: dict, rec: dict | None, pregame: dict | None) -> list | None:
    """[[seq, ours, espn]] for every play of the ESPN record (live.wp_series)."""
    mod = _module("live")
    if mod is None or not rec or not ctx.use_models:
        return None
    try:
        return mod.wp_series(rec, pregame or {}, g.get("home"), ctx.season)
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["live series"] = f"{type(exc).__name__}: {exc}"
        return None


# ---------------------------------------------------------------------------------------------- season

SIM_KEYS = {"p_playoffs": ["p_playoffs", "playoffs", "p_postseason", "p_make_playoffs"], "p_div": ["p_div", "p_division", "division"],
            "p_bye": ["p_bye", "bye"], "p_1seed": ["p_1seed", "p_seed1", "p_one_seed"], "p_conf": ["p_conf", "p_conference", "conference"],
            "p_sb": ["p_sb", "p_champion", "p_title", "sb"], "mean_wins": ["mean_wins", "exp_w", "exp_wins", "wins_mean"],
            "p_wildcard": ["p_wildcard"], "rating": ["rating"], "rating_se": ["rating_se"], "w_p05": ["w_p05"], "w_p95": ["w_p95"],
            "p_first_pick": ["p_first_pick", "p_pick1"], "mean_pick": ["mean_pick", "exp_pick"]}


def season_sim(ctx) -> dict:
    """Builder C's season simulation normalised to {"ok", "teams": {abbr: {p_playoffs, p_div, p_bye, p_1seed, p_conf,
    p_sb, mean_wins, seed_dist, win_dist, magic, elim, ...}}, "draft", "bracket", "n"}."""
    mod = _module("season_sim")
    if mod is None:
        return {"ok": False, "reason": "season_sim model not available"}
    try:
        res = mod.for_season(ctx.season, n=ctx.sims)
    except TypeError:
        res = mod.for_season(ctx.season)
    if not isinstance(res, dict):
        return {"ok": False, "reason": "season_sim returned no dict"}
    if not _usable(res):
        return {"ok": False, "reason": res.get("reason") or "season_sim not available"}
    tm = res.get("teams") or res.get("odds") or {}
    df = frame_of(tm)
    if df is not None and len(df):
        tc = next((c for c in ("team", "abbr") if c in df.columns), None)
        tm = {str(r[tc]): r for r in df.to_dict("records")} if tc else {}
    teams = {}
    for t, r in (tm.items() if isinstance(tm, dict) else []):
        if not isinstance(r, dict):
            continue
        row = {k: an.fnum(next((r[c] for c in cs if r.get(c) is not None), None)) for k, cs in SIM_KEYS.items()}
        for k in ("seed_dist", "win_dist", "pick_dist", "magic", "tragic", "elim", "clinched", "eliminated", "status", "p_reach", "current"):
            if k in r:
                row[k] = r[k]
        if r.get("next") is not None or r.get("next_game") is not None:
            row["next_game"] = r.get("next") or r.get("next_game")
        sd = r.get("seed_dist")
        if row.get("p_1seed") is None and isinstance(sd, list) and sd:
            row["p_1seed"] = an.fnum(sd[0])
        dr = r.get("draft") if isinstance(r.get("draft"), dict) else {}
        if dr:
            row["p_first_pick"] = an.fnum(dr.get("p_pick1"))
            row["mean_pick"] = an.fnum(dr.get("exp_pick"))
            row["p_top5"] = an.fnum(dr.get("p_top5"))
            row["p_top10"] = an.fnum(dr.get("p_top10"))
            row["pick_dist"] = dr.get("dist")
        teams[t] = row
    return {"ok": True, "teams": teams, "draft": res.get("draft") or res.get("draft_order"), "bracket": res.get("bracket"),
            "n": res.get("n") or res.get("n_sims") or ctx.sims, "version": res.get("version"),
            "extra": {k: res[k] for k in ("through", "remaining_games", "hfa", "p_tie", "runtime_s", "sigma_noise") if k in res}}


def season_sensitivity(ctx, sim: dict | None, n: int = 2000) -> dict:
    """Per-team outcome curves against a strength shift (season_sim.sensitivity, the trade simulator's input),
    anchored at 0 to the published simulation `sim`. Cached under <cache>/analytics/sensitivity/ on the simulation's
    numeric inputs (ratings, rating errors, each remaining game's mean margin and total, the results so far), the
    published odds and n, so an unchanged season is not re-simulated every hour."""
    mod = _module("season_sim")
    if mod is None or not hasattr(mod, "sensitivity") or not ctx.use_models:
        return {"ok": False, "reason": "season_sim sensitivity not available"}
    if not (sim or {}).get("ok") or not (sim or {}).get("teams"):
        return {"ok": False, "reason": "no season simulation this run"}
    import hashlib
    prep = mod.prepare(ctx.season)
    S0 = prep["S0"]
    base = {t: {"p_playoffs": r.get("p_playoffs"), "p_div": r.get("p_div"), "p_bye": r.get("p_bye"), "p_conf": r.get("p_conf"),
                "p_sb": r.get("p_sb"), "mean_wins": r.get("mean_wins"), "mean_pick": r.get("mean_pick")} for t, r in sim["teams"].items()}
    h = hashlib.sha1()
    for part in (prep["base"], prep["se"], prep["mu"], prep["mt"], prep["hi"], prep["ai"], S0["W"], S0["L"], S0["Ti"], S0["PF"], S0["PA"], S0["FP"]):
        h.update(np.round(np.asarray(part, float), 4).tobytes())
    h.update(repr((sorted(S0["teams"]), n, getattr(mod, "SENS_GRID", None), getattr(mod, "SENS_PROPOSAL", None), "sens-2",
                   sorted((t, tuple(an.rnd(v, 4) for v in b.values())) for t, b in base.items()))).encode())
    key = h.hexdigest()[:16]
    cp = an.an_cache() / "sensitivity" / f"{ctx.season}_{key}.json"
    got = an.read_json(cp)
    if isinstance(got, dict) and got.get("ok"):
        got["cached"] = True
        return got
    res = mod.sensitivity(ctx.season, n=n, state={"prepared": prep}, baseline=base)
    if res.get("ok"):
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            for old in cp.parent.glob(f"{ctx.season}_*.json"):
                old.unlink(missing_ok=True)
            an.write_json(cp, res)
        except OSError:
            pass
    return res


def awards(ctx, sim: dict | None = None) -> dict | None:
    """Builder C's award races: {"races": {award: [{"id","name","team","pos","p"}]}, "share_played", "markets":
    {award: [{"name","team","model","market","edge"}]} | None}; None when the model is not available."""
    mod = _module("awards")
    if mod is None or not ctx.use_models:
        return None
    if hasattr(mod, "for_season"):
        try:
            res = mod.for_season(ctx.season, markets=(ctx.markets() or {}).get("awards"))
        except TypeError:
            res = mod.for_season(ctx.season)
        return res if isinstance(res, dict) and _usable(res) else None
    exp_w = {t: v.get("mean_wins") for t, v in ((sim or {}).get("teams") or {}).items() if v.get("mean_wins") is not None}         if (sim or {}).get("ok") else None
    pred = mod.predict(ctx.season, exp_wins=exp_w or None)
    if not pred:
        ctx.model_errors["awards"] = "no award fit"
        return None
    races = {k: v for k, v in pred.items() if isinstance(v, list)}
    mk = None
    fut = (ctx.markets() or {}).get("futures")
    if fut and hasattr(mod, "compare_markets"):
        try:
            mk = mod.compare_markets(pred, fut)
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["awards markets"] = f"{type(exc).__name__}: {exc}"
    return {"races": races, "share_played": pred.get("share_played"), "markets": mk}


def award_winners(season: int) -> dict:
    """{award: {"name","team","pos"}} from builder C's verified winners table (2006 onward)."""
    mod = _module("award_winners")
    out = {}
    for aw, by in (getattr(mod, "WINNERS", None) or {}).items():
        w = by.get(int(season))
        if w:
            out[aw] = {"name": w[0], "team": w[1], "pos": w[2] if len(w) > 2 else None}
    return out


def markets(ctx) -> dict:
    """Builder C's sources.markets: {"futures": futures(season, store) (champion, conference, division, top_seed,
    playoffs, win_totals, awards, advance), "games": game_prices(season, store, window) ({game_id: {"p_home","basis",
    "sources","spread","total","team_total","book"}})}."""
    try:
        MK = importlib.import_module("oddsmarkets.nfl.sources.markets")
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["markets"] = f"markets module not available: {exc}"
        return {}
    out: dict = {}
    try:
        out["futures"] = MK.futures(ctx.season, ctx.store)
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["markets futures"] = f"{type(exc).__name__}: {exc}"
    try:
        lo, hi = ctx.today - timedelta(days=1), ctx.today + timedelta(days=8)
        out["games"] = MK.game_prices(ctx.season, ctx.store, window=(lo, hi))
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["markets games"] = f"{type(exc).__name__}: {exc}"
    return out


def calibration() -> dict | None:
    """Builder C's backtest output (the calibration payload) when it has written one."""
    mod = _module("backtest")
    if mod is None:
        return None
    for fn in ("calibration_payload", "payload", "load", "latest"):
        f = getattr(mod, fn, None)
        if f is None:
            continue
        try:
            r = f()
            if isinstance(r, dict) and r:
                return r
        except Exception as exc:                                 # noqa: BLE001
            logger.info("backtest.%s: %s", fn, exc)
    return None


def model_versions() -> dict:
    out = {}
    for mod in ("ep", "wp", "fourth_down", "completion", "yac", "ryoe", "pressure", "player_value", "qb", "kicking", "stabilise",
                "team_strength", "game", "drive_sim", "live", "season_sim", "awards"):
        m = _module(mod)
        out[mod] = str(getattr(m, "MODEL_VERSION", None) or getattr(m, "VERSION", None)) if m is not None else None
    return out


def fitted_keys() -> dict:
    """Keys of the fits the models would use (so a refit changes page signatures)."""
    out = {}
    for mod in ("ep", "wp", "fourth_down", "completion", "kicking"):
        m = _module(mod)
        f = getattr(m, "current_fit", None) if m is not None else None
        if f is None:
            continue
        try:
            fit = f()
            out[mod] = (fit or {}).get("key") if isinstance(fit, dict) else None
        except Exception:                                        # noqa: BLE001
            out[mod] = None
    return out
