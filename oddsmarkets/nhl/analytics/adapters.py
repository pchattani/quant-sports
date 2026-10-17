"""
Adapters between builders B's and C's models and this layer. Every call is isolated (a model that is missing, raises
or answers in an unexpected shape gives None / {} and is listed in the context's model_errors) and every answer is
normalised to the shapes the catalogues and pages use.

Builder B: xg (per-shot xG joined to the events on (game_id, idx)), shooting, goalies, onice, rapm, value, lines,
stabilise (shrinkage constants and stabilisation points). Builder C: team_strength, game (prices), live (win
probability), season_sim, awards, backtest (calibration), sources.markets.

Player tables come back as {metric_key: {pid: value}} through candidate column names (`PLAYER_MAP`), so a renamed
column in a model costs one entry here, not a catalogue change.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics.context import frame_of

logger = logging.getLogger(__name__)
ID_COLS = ("player_id", "pid", "player", "playerId", "id", "goalie", "goalie_id", "skater", "shooter")


def _module(name: str, pkg: str = "models"):
    try:
        return importlib.import_module(f"oddsmarkets.nhl.{pkg}.{name}")
    except Exception as exc:                                     # noqa: BLE001
        logger.debug("module %s: %s", name, exc)
        return None


def usable(res: Any) -> bool:
    return res is not None and not (isinstance(res, dict) and (res.get("ok") is False or res.get("available") is False))


def _call(f, *args, **kw):
    """Call f with the keyword arguments its signature accepts."""
    try:
        sig = inspect.signature(f)
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            kw = {k: v for k, v in kw.items() if k in sig.parameters}
    except (TypeError, ValueError):
        pass
    return f(*args, **kw)


def frames(res: Any, keys: tuple[str, ...] = ()) -> list[pd.DataFrame]:
    """Every DataFrame-like table inside a model answer: the answer itself, then res[k] for the given keys, then
    any other table-valued entry."""
    out = []
    df = frame_of(res) if not isinstance(res, dict) or "cols" in res else None
    if df is not None and len(df):
        out.append(df)
    if isinstance(res, dict):
        seen = set()
        for k in list(keys) + [k for k in res if k not in keys]:
            if k in seen or k not in res:
                continue
            seen.add(k)
            v = res.get(k)
            if isinstance(v, (pd.DataFrame, list)) or (isinstance(v, dict) and ("cols" in v or (v and all(isinstance(x, dict) for x in v.values())))):
                f = frame_of(v)
                if f is not None and len(f):
                    f.attrs["key"] = k
                    out.append(f)
    return out


def _idcol(df: pd.DataFrame) -> str | None:
    for c in ID_COLS + ("key",):
        if c in df.columns:
            return c
    return None


def table_map(res: Any, mapping: dict[str, list[str]], keys: tuple[str, ...] = (), scale: dict[str, float] | None = None) -> dict[str, dict[str, float]]:
    """{our_key: {pid: value}} from the first table that has an id column and each candidate column."""
    out: dict[str, dict[str, float]] = {}
    if not usable(res):
        return out
    for df in frames(res, keys):
        idc = _idcol(df)
        if idc is None:
            continue
        ids = df[idc].map(an.sid)
        for ours, cands in mapping.items():
            if ours in out:
                continue
            c = next((c for c in cands if c in df.columns), None)
            if c is None:
                continue
            v = pd.to_numeric(df[c], errors="coerce") * (scale or {}).get(ours, 1.0)
            d = {p: float(x) for p, x in zip(ids, v) if p and x == x}
            if d:
                out[ours] = d
    return out


# ---------------------------------------------------------------------------------------------- B: xG

def shot_xg(ctx, ev: pd.DataFrame) -> np.ndarray | None:
    """Builder B's per-shot xG aligned to the events (joined on game_id and the per-game index); None when the model
    does not score the season or covers under half the unblocked attempts."""
    if not ctx.use_models or _module("xg") is None:
        return None
    res = ctx.model("xg")
    if not usable(res):
        return None
    cand = None
    for df in frames(res, ("shots", "events", "xg", "rows", "table")):
        cols = set(df.columns)
        xc = next((c for c in ("xg", "xG", "p_goal", "xgoal") if c in cols), None)
        if "game_id" in cols and xc and ("idx" in cols or "event_idx" in cols):
            cand = (df, xc, "idx" if "idx" in cols else "event_idx")
            break
    if cand is None:
        ctx.model_errors.setdefault("xg", "xg.for_season answered without a (game_id, idx, xg) table")
        return None
    df, xc, ic = cand
    k = pd.DataFrame({"game_id": df["game_id"].map(an.sid), "idx": pd.to_numeric(df[ic], errors="coerce"),
                      "_xg": pd.to_numeric(df[xc], errors="coerce")}).drop_duplicates(["game_id", "idx"])
    m = ev[["game_id", "idx"]].merge(k, on=["game_id", "idx"], how="left")
    x = m["_xg"].to_numpy(float)
    fen = ev["type"].isin(("GOAL", "SHOT", "MISS")).to_numpy()
    if fen.sum() and np.isfinite(x[fen]).mean() < 0.5:
        ctx.model_errors.setdefault("xg", f"xg covers {np.isfinite(x[fen]).mean():.0%} of unblocked attempts; fallback used")
        return None
    return x


def xg_benchmark(ctx) -> dict | None:
    """The xG model's own validation (this season, out of fold) and its benchmark against MoneyPuck's xGoal on the same
    shots, when the xg answer carries them: {"validation", "benchmark", "arena", "model"}."""
    res = ctx.model("xg") if ctx.use_models and _module("xg") is not None else None
    if not usable(res) or not isinstance(res, dict):
        return None
    out = {k: res.get(k) for k in ("validation", "benchmark", "arena", "model") if res.get(k) is not None}
    return out or None


# ---------------------------------------------------------------------------------------------- B: players

PLAYER_MAP = {
    "shooting": {
        "gax": ["gax", "goals_above_xg", "g_minus_xg", "gae"],
        "shooting_talent": ["gax_shrunk", "shooting_talent"],
        "sh_pct_x": ["xsh_pct", "x_sh_pct", "expected_sh_pct"],
        "fsh_pct_shrunk": ["fsh_shrunk", "sh_pct_shrunk", "finishing_pct"],
    },
    "goalies": {
        "gsax_m": ["gsax", "GSAx", "gsax_total"],
        "gsax_low_m": ["gsax_low", "gsax_ld"], "gsax_med_m": ["gsax_med", "gsax_md"], "gsax_high_m": ["gsax_high", "gsax_hd"],
        "gsax_rebound_m": ["gsax_rebound", "gsax_reb"], "gsax_rush_m": ["gsax_rush"],
        "gsax_per60_m": ["gsax_60", "gsax_per60", "gsax60"], "gsax_shrunk": ["gsax_shrunk", "talent", "gsax_talent"],
        "gsax_pct": ["gsax_per_shot", "gsax_pct", "dsv_pct", "dfsv_pct"],
    },
    "onice": {
        "adj_xgf60": ["xgf60_adj", "adj_xgf60"], "adj_xga60": ["xga60_adj", "adj_xga60"],
        "adj_cf60": ["cf60_adj", "adj_cf60"], "adj_ca60": ["ca60_adj", "adj_ca60"],
        "adj_xgf_pct": ["xgf_pct_adj", "adj_xgf_pct"],
        "pp_xgf60_m": ["pp_xgf60", "xgf60_pp"], "pk_xga60_m": ["pk_xga60", "xga60_pk"],
    },
    "rapm": {
        "rapm_off": ["off", "rapm_off", "xgf", "off_xgf60", "offence", "offense"],
        "rapm_def": ["def", "rapm_def", "xga", "def_xga60", "defence", "defense"],
        "rapm_net": ["net", "rapm_net", "total", "xg_net"],
        "rapm_off_se": ["off_se", "se_off"], "rapm_def_se": ["def_se", "se_def"], "rapm_net_se": ["net_se", "se_net"],
        "rapm_cf": ["cf", "rapm_cf", "off_cf60"], "rapm_ca": ["ca", "rapm_ca", "def_ca60"],
        "rapm_pp": ["pp", "rapm_pp", "pp_off"], "rapm_pk": ["pk", "rapm_pk", "pk_def"],
        "rapm_gf": ["gf", "rapm_gf"], "rapm_ga": ["ga", "rapm_ga"],
        "rapm_pen": ["pen", "penalties", "rapm_pen"],
    },
    "value": {
        "gar": ["gar", "goals_above_replacement", "value_goals", "rink_value"], "war": ["war", "wins_above_replacement", "value_wins"],
        "gar_ev_off": ["ev_off", "gar_ev_off", "evo"], "gar_ev_def": ["ev_def", "gar_ev_def", "evd"],
        "gar_pp": ["pp", "gar_pp"], "gar_pk": ["pk", "gar_pk", "sh"], "gar_shooting": ["shooting", "gar_shooting", "finishing"],
        "gar_pen": ["pen", "penalties", "gar_pen"], "gar_fo": ["faceoffs", "gar_fo", "fo"],
        "gar_60": ["gar60", "gar_60", "per60"], "spar": ["spar", "standings_points"],
    },
}


def player_tables(ctx) -> dict[str, dict[str, float]]:
    """{metric: {pid: value}} from builder B's player models (absent or unfitted models give no entry)."""
    out: dict[str, dict[str, float]] = {}
    if not ctx.use_models:
        return out
    for mod, mp in PLAYER_MAP.items():
        if _module(mod) is None:
            ctx.model_errors.setdefault(mod, "model module not available")
            continue
        res = ctx.model(mod)
        keys = {"shooting": ("players", "shooters", "skaters"), "goalies": ("goalies", "players"), "onice": ("players", "skaters", "5v5"),
                "rapm": ("players", "skaters", "coef", "coefficients"), "value": ("skaters", "players", "goalies")}[mod]
        for k, v in table_map(res, mp, keys).items():
            out.setdefault(k, v)
    return out


def goalie_value(ctx) -> dict[str, float]:
    """Goalie Rink value (goals above replacement) from value.for_season's goalie table."""
    if not ctx.use_models or _module("value") is None:
        return {}
    res = ctx.model("value")
    if not usable(res) or not isinstance(res, dict):
        return {}
    for k in ("goalies", "goalie"):
        if k in res:
            t = table_map({"x": res[k]}, {"gar": ["gar", "goals_above_replacement", "value_goals", "value"],
                                          "war": ["war", "wins_above_replacement"]}, ("x",))
            return t
    return {}


def projections(ctx) -> dict[str, dict]:
    """{pid: {..}} next-season / rest-of-season projections when value.py or rapm.py export them."""
    out: dict[str, dict] = {}
    if not ctx.use_models:
        return out
    for mod in ("value", "rapm", "shooting"):
        if _module(mod) is None:
            continue
        res = ctx.model(mod)
        if not usable(res) or not isinstance(res, dict):
            continue
        for k in ("projections", "projection", "proj"):
            df = frame_of(res.get(k))
            if df is not None and len(df) and _idcol(df):
                idc = _idcol(df)
                for r in df.to_dict("records"):
                    p = an.sid(r.get(idc))
                    if p:
                        out.setdefault(p, {}).update({kk: (an.rnd(vv, 3) if isinstance(vv, float) else vv) for kk, vv in r.items() if kk != idc})
    return out


def model_lines(ctx) -> dict | None:
    """Builder B's lines.for_season: {"forwards": [...], "pairs": [...]} rows when it answers."""
    if not ctx.use_models or _module("lines") is None:
        return None
    res = ctx.model("lines")
    return res if usable(res) and isinstance(res, dict) else None


# ---------------------------------------------------------------------------------------------- B: stabilisation

_STAB: dict[str, Any] = {}


def _stab_mod():
    if "mod" not in _STAB:
        _STAB["mod"] = _module("stabilise")
    return _STAB["mod"]


def _stab_known(S, name: str) -> bool:
    """Only metrics stabilise.py fits or has a default for (its shrink_k answers 200 for anything else)."""
    if name in (getattr(S, "DEFAULT_K", None) or {}):
        return True
    try:
        f = S._io.read_fit("stabilise") if hasattr(S, "_io") else None
        return bool(isinstance(f, dict) and name in (f.get("metrics") or {}))
    except Exception:                                            # noqa: BLE001
        return False


def stab_k(name: str) -> float | None:
    S = _stab_mod()
    if S is None or not _stab_known(S, name):
        return None
    key = ("k", name)
    if key in _STAB:
        return _STAB[key]
    v = None
    for fn in ("shrink_k", "k", "k_for", "get_k"):
        f = getattr(S, fn, None)
        if f is None:
            continue
        try:
            v = an.fnum(f(name))
        except Exception:                                        # noqa: BLE001
            v = None
        if v is not None:
            break
    if v is None:
        tab = getattr(S, "DEFAULT_K", None) or getattr(S, "K", None) or getattr(S, "DEFAULTS", None)
        if isinstance(tab, dict):
            x = tab.get(name)
            v = an.fnum(x.get("k") if isinstance(x, dict) else x)
    _STAB[key] = v
    return v


def stab_point(name: str) -> float | None:
    S = _stab_mod()
    if S is None or not _stab_known(S, name):
        return None
    key = ("pt", name)
    if key in _STAB:
        return _STAB[key]
    v = None
    for fn in ("point", "stabilises_at", "n70", "stab_point"):
        f = getattr(S, fn, None)
        if f is None:
            continue
        try:
            v = an.fnum(f(name))
        except Exception:                                        # noqa: BLE001
            v = None
        if v is not None:
            break
    _STAB[key] = v
    return v


# ---------------------------------------------------------------------------------------------- C: teams

TS_KEYS = {"rating": ["rating", "net", "overall", "goal_diff"], "off5": ["off5", "ev_off", "off_5v5"],
           "def5": ["def5", "ev_def", "def_5v5"], "pp": ["pp", "pp_off"], "pk": ["pk", "pk_def"],
           "goalie": ["g_val", "goaltending", "gsax60"], "se": ["se_net", "se", "rating_se"], "gf_g": ["gf_g", "gf_pg"],
           "ga_g": ["ga_g", "ga_pg"], "fin": ["fin", "finishing"]}


def team_ratings(ctx) -> dict | None:
    """{"teams": {abbr: {rating, off5, def5, pp, pk, goalie, se, ...}}, "history": {abbr: [[date, rating, off5, def5], ...]},
    "units", "version"} from builder C's team_strength."""
    if not ctx.use_models or _module("team_strength") is None:
        return None
    res = ctx.model("team_strength")
    if not usable(res) or not isinstance(res, dict):
        return None
    tm = res.get("teams") or res.get("ratings")
    df = frame_of(tm)
    rows: dict[str, dict] = {}
    if isinstance(tm, dict) and tm and all(isinstance(v, dict) for v in tm.values()):
        rows = {str(k): v for k, v in tm.items()}
    elif df is not None and len(df):
        tc = next((c for c in ("team", "abbr", "key") if c in df.columns), None)
        if tc:
            rows = {str(r[tc]): r for r in df.to_dict("records")}
    if not rows:
        return None
    teams = {}
    for t, v in rows.items():
        e = {k: an.fnum(next((v[c] for c in cs if v.get(c) is not None and not isinstance(v.get(c), (dict, list))), None)) for k, cs in TS_KEYS.items()}
        for k, val in v.items():
            if k not in e and isinstance(val, (int, float)) and not isinstance(val, bool):
                e[k] = an.fnum(val)
        if isinstance(v.get("goalie"), dict):
            e["starter"] = v["goalie"].get("starter") or v["goalie"].get("id")
        teams[t] = e
    hist = res.get("history") or {}
    if not isinstance(hist, dict):
        hd = frame_of(hist)
        hist = {}
        if hd is not None and "team" in hd:
            for t, g in hd.groupby("team"):
                hist[str(t)] = g.drop(columns=["team"]).values.tolist()
    return {"teams": teams, "history": hist, "units": res.get("units") or "goals per 60 against an average team",
            "version": getattr(_module("team_strength"), "VERSION", None) or res.get("version"), "league": res.get("league")}


# ---------------------------------------------------------------------------------------------- C: games

PRICE_KEYS = {"p_home": ["p_home", "home_win", "win_home", "p_win_home"], "p_reg_home": ["p_reg_home", "p_home_reg", "reg_home", "p_home_regulation"],
              "p_reg_away": ["p_reg_away", "p_away_reg", "reg_away"], "p_ot": ["p_ot", "ot", "p_overtime"], "p_so": ["p_so", "shootout", "p_shootout"],
              "total": ["total", "exp_total", "mu_total", "goals_total"], "home_goals": ["home_goals", "mu_home", "lam_home", "xg_home", "exp_home"],
              "away_goals": ["away_goals", "mu_away", "lam_away", "xg_away", "exp_away"],
              "puck_line_home": ["puck_line_home", "p_home_cover", "p_cover_home", "home_minus_1_5", "p_home_m15"],
              "p_over": ["p_over", "over"], "total_line": ["total_line"], "fair_total": ["fair_total", "median_total"]}


def _ratings(ctx) -> dict | None:
    rd = ctx.model("team_strength")
    return rd if usable(rd) and isinstance(rd, dict) and rd.get("teams") else None


def _starter(g: dict, side: str) -> str | None:
    v = (g.get("goalies") or {}).get(side)
    return an.sid(v.get("starter") if isinstance(v, dict) else v)


def game_prices(ctx, games: list[dict]) -> dict[str, dict]:
    """{game_id: price} from builder C's game model for the given store games: game.predict_frame on the season's
    games with _cdata.add_context (rest, back-to-backs, travel, time zones) under team_strength's current ratings,
    the starters from GAME.goalies; game.predict adds the final-score matrix and totals pmf per game."""
    GMm = _module("game")
    if GMm is None or not games or not ctx.use_models:
        return {}
    for fn in ("price_games", "for_games"):
        f = getattr(GMm, fn, None)
        if f is not None:
            res = _call(f, ctx.season, games)
            items = res.items() if isinstance(res, dict) else ((an.sid(r.get("game_id")), r) for r in (res or []) if isinstance(r, dict))
            return {an.sid(gid): norm_price(r) for gid, r in items if isinstance(r, dict)}
    rd = _ratings(ctx)
    if rd is None:
        ctx.model_errors.setdefault("game", "no team-strength ratings")
        return {}
    want = {str(g["game_id"]) for g in games}
    sub = None
    try:
        from oddsmarkets.nhl.models import _cdata as D
        G = D.add_context(D.games_frame([ctx.season]))
        sub = G[G["game_id"].astype(str).isin(want)].copy()
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["game context"] = f"{type(exc).__name__}: {exc}"
    out: dict[str, dict] = {}
    gmap = {str(g["game_id"]): g for g in games}
    if sub is not None and len(sub):
        sub["goalie_h"] = [_starter(gmap.get(str(x)) or {}, "home") for x in sub["game_id"]]
        sub["goalie_a"] = [_starter(gmap.get(str(x)) or {}, "away") for x in sub["game_id"]]
        tl = []
        for x in sub["game_id"]:
            ln = (gmap.get(str(x)) or {}).get("lines") or {}
            t = ln.get("total")
            tl.append(an.fnum(t.get("line") if isinstance(t, dict) else t))
        sub["total_line"] = [np.nan if v is None else v for v in tl]
        pf = GMm.predict_frame(sub, rd)
        for r in pf.to_dict("records"):
            gid = an.sid(r["game_id"])
            pmf = r.get("_total_pmf")
            out[gid] = {"p_home": an.fnum(r.get("p_home")), "p_reg_home": an.fnum(r.get("p_reg_home")),
                        "p_reg_away": an.fnum(r.get("p_reg_away")), "p_ot": an.fnum(r.get("p_ot")), "p_so": an.fnum(r.get("p_so")),
                        "p_ot_home": an.fnum(r.get("p_ot_home")), "puck_line_home": an.fnum(r.get("pl_home")),
                        "puck_line_away": an.fnum(r.get("pl_away")), "total": an.fnum(r.get("exp_total")),
                        "fair_total": an.fnum(r.get("fair_total")), "p_over": an.fnum(r.get("p_over")),
                        "total_line": an.fnum(r.get("total_line")), "home_goals": an.fnum(r.get("mu_h")),
                        "away_goals": an.fnum(r.get("mu_a")), "goalies": {"home": r.get("goalie_h"), "away": r.get("goalie_a")},
                        "total_dist": [round(float(v), 5) for v in pmf][:16] if pmf is not None else None, "source": "game"}
    # the final-score matrix (game.predict) for the games just priced
    pred = getattr(GMm, "predict", None)
    for gid, pr in out.items():
        g = gmap.get(gid) or {}
        if pred is None:
            break
        try:
            r = pred(g.get("home"), g.get("away"), ctx.season, rd,
                     {"playoff": g.get("gtype") == "PO", "goalie_h": pr["goalies"]["home"], "goalie_a": pr["goalies"]["away"],
                      "neutral": bool(g.get("neutral"))})
            pr["score_matrix"] = r.get("score_matrix")
            pr["score_dist"] = {"rows": "home goals 0-6", "cols": "away goals 0-6", "p": r.get("score_matrix")}
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["game.predict"] = f"{type(exc).__name__}: {exc}"
            break
    return out


def norm_price(r: dict) -> dict:
    out = {}
    for k, cs in PRICE_KEYS.items():
        v = next((r[c] for c in cs if r.get(c) is not None and not isinstance(r.get(c), (dict, list))), None)
        out[k] = an.fnum(v)
    for k in ("score_dist", "scores", "dist", "goalies", "inputs", "source", "score_matrix", "total_dist"):
        if r.get(k) is not None:
            out[k] = r[k]
    return out


def walk_forward(ctx) -> dict[str, dict]:
    """Pre-game prices of the season's games from builder C's walk-forward (ratings refitted weekly on games strictly
    before each block, preseason prior chained from the season before): {game_id: price} with source "walk_forward";
    cached under <cache>/analytics/walk_forward on the store, derived tables and the model parameters."""
    GMm = _module("game")
    if GMm is None or not ctx.use_models or not hasattr(GMm, "walk_forward"):
        return {}
    import hashlib
    parts = [str(getattr(GMm, "VERSION", "")), str(getattr(_module("team_strength"), "VERSION", "")), "wf-2"]
    for q in (an.store_path(ctx.season), an.store_path(an.prev_season(ctx.season)), an.events_path(ctx.season),
              an.events_path(an.prev_season(ctx.season))):
        try:
            st = q.stat()
            parts.append(f"{q}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{q}:-")
    try:
        parts.append(repr(sorted((k, str(v)) for k, v in GMm.params().items())))
    except Exception:                                            # noqa: BLE001
        pass
    key = hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]
    cp = an.an_cache() / "walk_forward" / f"{ctx.season}_{key}.json"
    got = an.read_json(cp)
    if isinstance(got, dict):
        return got
    rows = GMm.walk_forward([ctx.season])
    if rows is None or not len(rows):
        return {}
    p = GMm.params()
    mu_h, mu_a = GMm.means(rows, p)
    po = (rows["gtype"].astype(str) == "PO").to_numpy() if "gtype" in rows else False
    o = GMm.outcome_probs(mu_h, mu_a, p, po, ctx.season)
    out = {}
    for i, gid in enumerate(rows["game_id"].map(an.sid)):
        out[gid] = {"p_home": round(float(o["p_home"][i]), 4), "p_reg_home": round(float(o["p_reg_home"][i]), 4),
                    "p_reg_away": round(float(o["p_reg_away"][i]), 4), "p_ot": round(float(o["p_ot"][i]), 4),
                    "puck_line_home": round(float(o["pl_home"][i]), 4), "total": round(float(o["exp_total"][i]), 3),
                    "home_goals": round(float(mu_h[i]), 3), "away_goals": round(float(mu_a[i]), 3),
                    "p_so": round(float(o["p_so"][i]), 4), "puck_line_away": round(float(o["pl_away"][i]), 4),
                    "total_dist": [round(float(v), 4) for v in o["total_pmf"][i][:16]], "source": "walk_forward"}
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        for old in cp.parent.glob(f"{ctx.season}_*.json"):
            old.unlink(missing_ok=True)
        an.write_json(cp, out)
    except OSError:
        pass
    return out


def _live_means(mod, pregame: dict | None, season: int) -> dict:
    """{"mu_h", "mu_a"} for the live model: the pre-game goal means, else solved once from p_home (the live model would
    otherwise re-solve them at every state)."""
    if not pregame:
        return {}
    if pregame.get("home_goals") and pregame.get("away_goals"):
        return {"mu_h": pregame["home_goals"], "mu_a": pregame["away_goals"]}
    if pregame.get("p_home") is not None:
        f = getattr(mod, "means_from_p", None)
        if f is not None:
            try:
                mh, ma = f(float(pregame["p_home"]), float(pregame.get("total") or 6.0), season=season)
                return {"mu_h": mh, "mu_a": ma}
            except Exception:                                    # noqa: BLE001
                pass
        return {"p_home": pregame["p_home"]}
    return {}


def live_now(ctx, g: dict, pregame: dict | None) -> float | None:
    """The home WP of a game in progress from the store's period / clock / score (builder C's live.live_wp)."""
    mod = _module("live")
    if mod is None or not ctx.use_models or g.get("status") != "live":
        return None
    pg = _live_means(mod, pregame, ctx.season)
    try:
        r = mod.live_wp({"period": g.get("period"), "clock": g.get("clock") or "20:00", "hs": g.get("hs"), "as": g.get("as"),
                         "playoff": g.get("gtype") == "PO", "season": ctx.season}, pg or None)
        return an.rnd(r.get("wp_home"), 4)
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["live now"] = f"{type(exc).__name__}: {exc}"
        return None


def live_wp(ctx, g: dict, ev_game: pd.DataFrame | None, pregame: dict | None) -> dict | None:
    """Our win-probability series for a game with events: builder C's live.from_events (after every goal, penalty and
    faceoff) from the pre-game means: {"now", "series": [[sec, p_home], ...]}."""
    mod = _module("live")
    if mod is None or not ctx.use_models or ev_game is None or not len(ev_game):
        return None
    pg = _live_means(mod, pregame, ctx.season)
    f = getattr(mod, "from_events", None)
    if f is None:
        return None
    try:
        ser = _call(f, ev_game, pg or None, playoff=g.get("gtype") == "PO", season=ctx.season)
    except Exception as exc:                                     # noqa: BLE001
        ctx.model_errors["live"] = f"{type(exc).__name__}: {exc}"
        return None
    if not ser:
        return None
    # one row per goal / penalty / faceoff state, in order, at the events' own elapsed seconds (overtime included)
    ser = [[an.rnd(a, 0), an.rnd(b, 4)] for a, b in ser]
    if g.get("status") == "final" and g.get("hs") is not None and g.get("as") is not None and g["hs"] != g["as"]:
        ser.append([ser[-1][0], 1.0 if g["hs"] > g["as"] else 0.0])
    return {"now": ser[-1][1], "series": ser}


# ---------------------------------------------------------------------------------------------- C: season

SIM_KEYS = {"p_playoffs": ["p_playoffs", "playoffs", "p_make_playoffs", "p_po"], "p_div": ["p_div", "p_division", "division"],
            "p_pres": ["p_pres", "p_presidents", "presidents", "p_presidents_trophy"], "p_conf": ["p_conf", "p_conference", "p_final", "conference"],
            "p_cup": ["p_cup", "p_champion", "cup", "p_title"], "mean_pts": ["mean_pts", "exp_pts", "points_mean", "pts_mean", "exp_points"],
            "pts_p05": ["pts_p05", "p05"], "pts_p50": ["pts_p50"], "pts_p95": ["pts_p95", "p95"], "p_r2": ["p_r2", "p_round2"],
            "p_r3": ["p_r3", "p_round3"], "p_first_pick": ["p_first_pick", "p_pick1", "p_lottery_win"], "mean_pick": ["mean_pick", "exp_pick"],
            "rating": ["rating"], "rating_se": ["rating_se"], "p_wildcard": ["p_wildcard", "p_wc"], "p_top3": ["p_top3"],
            "exp_w": ["exp_w", "mean_wins"]}


def season_sim(ctx) -> dict:
    """Builder C's season simulation normalised to {"ok", "teams": {abbr: {p_playoffs, p_div, p_pres, p_conf, p_cup,
    mean_pts, points_dist, seed_dist, magic, elim, next_game, ...}}, "lottery", "bracket", "n"}."""
    mod = _module("season_sim")
    if mod is None:
        return {"ok": False, "reason": "season_sim model not available"}
    if not ctx.use_models:
        return {"ok": False, "reason": "models disabled for this run"}
    f = getattr(mod, "for_season", None) or getattr(mod, "simulate", None)
    if f is None:
        return {"ok": False, "reason": "season_sim has no for_season"}
    res = _call(f, ctx.season, n=ctx.sims, n_sims=ctx.sims, sims=ctx.sims)
    if not isinstance(res, dict):
        return {"ok": False, "reason": "season_sim returned no dict"}
    if not usable(res):
        return {"ok": False, "reason": res.get("reason") or "season_sim not available"}
    tm = res.get("teams") or res.get("odds") or {}
    df = frame_of(tm) if not (isinstance(tm, dict) and all(isinstance(v, dict) for v in tm.values())) else None
    if df is not None and len(df):
        tc = next((c for c in ("team", "abbr") if c in df.columns), None)
        tm = {str(r[tc]): r for r in df.to_dict("records")} if tc else {}
    teams = {}
    for t, r in (tm.items() if isinstance(tm, dict) else []):
        if not isinstance(r, dict):
            continue
        row = {k: an.fnum(next((r[c] for c in cs if r.get(c) is not None and not isinstance(r.get(c), (dict, list))), None))
               for k, cs in SIM_KEYS.items()}
        for k in ("points_dist", "pts_dist", "seed_dist", "pick_dist", "magic", "elim", "tragic", "clinched", "eliminated", "status",
                  "p_reach", "current", "next_game", "next", "round_dist", "draft", "p_points_ge", "div_rank_dist", "lottery",
                  "conference", "division"):
            if k in r:
                row["points_dist" if k == "pts_dist" else ("next_game" if k == "next" else k)] = r[k]
        row["exp_pts"] = row.get("mean_pts")
        lot = r.get("lottery") if isinstance(r.get("lottery"), dict) else {}
        if row.get("p_first_pick") is None and lot.get("p_first") is not None:
            row["p_first_pick"] = an.fnum(lot.get("p_first"))
        teams[str(t)] = row
    lot = res.get("lottery") or res.get("draft")
    if isinstance(lot, dict):
        def _top(r, k):
            pdist = (r.get("lottery") or {}).get("pick_dist") or []
            return round(float(sum(pdist[:k])), 5) if pdist else None
        lot = {**lot, "teams": {t: {"p_first": r.get("p_first_pick"), "p_top2": (r.get("lottery") or {}).get("p_top2") or _top(r, 2),
                                    "p_top3": _top(r, 3), "pick_dist": (r.get("lottery") or {}).get("pick_dist")}
                                for t, r in teams.items() if isinstance(r.get("lottery"), dict)}}
    return {"ok": True, "teams": teams, "lottery": lot, "bracket": res.get("bracket"),
            "n": res.get("n") or res.get("n_sims") or ctx.sims, "version": res.get("version") or getattr(mod, "VERSION", None),
            "pts_lines": res.get("pts_lines") or res.get("points_lines"), "format": res.get("format"), "groups": res.get("groups"),
            "extra": {k: res[k] for k in ("through", "remaining_games", "runtime_s", "seeds_now", "tiebreak", "notes", "format") if k in res}}


def awards(ctx, sim: dict | None = None) -> dict | None:
    """Award races from builder C's awards.predict: {"races": {award: [{"id", "name", "p"}]}, "basis": {award: basis},
    "reasons": {award: why not}, "markets": compare_markets rows when futures were fetched}."""
    mod = _module("awards")
    if mod is None or not ctx.use_models:
        return None
    f = getattr(mod, "for_season", None) or getattr(mod, "predict", None)
    if f is None:
        return None
    gl = None
    if sim and sim.get("ok"):
        gl = {t: (r.get("current") or {}).get("remaining") for t, r in (sim.get("teams") or {}).items()
              if isinstance(r.get("current"), dict) and (r.get("current") or {}).get("remaining") is not None}
    res = _call(f, ctx.season, games_left=gl or None)
    if not isinstance(res, dict) or not usable(res):
        return None
    races, basis, reasons = {}, {}, {}
    for aw, r in res.items():
        if not isinstance(r, dict):
            continue
        if not r.get("ok"):
            reasons[aw] = r.get("reason")
            continue
        names = r.get("names") or {}
        races[aw] = [{"id": an.sid(pid), "name": names.get(pid), "p": an.rnd(pv, 4)} for pid, pv in list((r.get("probs") or {}).items())[:25]]
        basis[aw] = r.get("basis")
    out = {"races": races or None, "basis": basis, "reasons": reasons}
    fut = (ctx.markets() or {}).get("futures")
    cm = getattr(mod, "compare_markets", None)
    if fut and cm is not None:
        try:
            out["markets"] = cm(res, fut)
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["awards markets"] = f"{type(exc).__name__}: {exc}"
    return out


def award_winners(season: int) -> dict:
    """{award: [{"name", "team", "value"?}]} from builder C's verified winners table (award_winners.WINNERS)."""
    tab = None
    for modname, attr in (("award_winners", "WINNERS"), ("awards", "WINNERS")):
        mod = _module(modname)
        tab = getattr(mod, attr, None) if mod is not None else None
        if isinstance(tab, dict):
            break
    out = {}
    if not isinstance(tab, dict):
        return out
    for aw, by in tab.items():
        if not isinstance(by, dict):
            continue
        w = by.get(int(season)) or by.get(str(season))
        if not w:
            continue
        rows = w if isinstance(w, list) else [w]
        lst = []
        for x in rows:
            if isinstance(x, (list, tuple)) and x:
                lst.append({"name": x[0], "team": x[1] if len(x) > 1 else None, "value": x[2] if len(x) > 2 else None})
            elif isinstance(x, dict):
                lst.append({"name": x.get("name"), "team": x.get("team"), "value": x.get("value")})
            elif isinstance(x, str):
                lst.append({"name": x, "team": None, "value": None})
        if lst:
            out[aw] = lst
    return out


def markets(ctx) -> dict:
    """Builder C's sources.markets: {"futures": {...}, "games": {game_id: {"p_home","sources",...}}, "awards", "points"}."""
    MK = _module("markets", "sources")
    if MK is None:
        ctx.model_errors["markets"] = "markets module not available"
        return {}
    out: dict = {}
    f = getattr(MK, "futures", None)
    if f is not None:
        try:
            fut = _call(f, ctx.season, store=ctx.store)
            out["futures"] = fut
            if isinstance(fut, dict):
                out["awards"] = fut.get("awards")
                out["points"] = fut.get("points")
                if fut.get("error"):
                    ctx.model_errors["markets futures"] = str(fut["error"])
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["markets futures"] = f"{type(exc).__name__}: {exc}"
    for fn in ("game_prices", "games"):
        f = getattr(MK, fn, None)
        if f is None:
            continue
        try:
            lo, hi = ctx.today - timedelta(days=1), ctx.today + timedelta(days=4)
            g = _call(f, ctx.season, store=ctx.store, window=(lo, hi))
            out["games"] = {an.sid(k): v for k, v in (g or {}).items()} if isinstance(g, dict) else {}
        except Exception as exc:                                 # noqa: BLE001
            ctx.model_errors["markets games"] = f"{type(exc).__name__}: {exc}"
        break
    return out


def calibration() -> dict | None:
    """Builder C's backtest output (the calibration payload) when it has written one."""
    mod = _module("backtest")
    if mod is None:
        return None
    for fn in ("calibration_payload", "payload", "load", "latest", "calibration"):
        f = getattr(mod, fn, None)
        if f is None or not callable(f):
            continue
        try:
            r = f()
            if isinstance(r, dict) and r:
                return r
        except Exception as exc:                                 # noqa: BLE001
            logger.info("backtest.%s: %s", fn, exc)
    return None


MODELS_B = ("xg", "shooting", "goalies", "onice", "rapm", "value", "lines", "stabilise")
MODELS_C = ("team_strength", "game", "live", "season_sim", "awards", "backtest")


def model_versions() -> dict:
    out = {}
    for mod in MODELS_B + MODELS_C:
        m = _module(mod)
        out[mod] = str(getattr(m, "MODEL_VERSION", None) or getattr(m, "VERSION", None)) if m is not None else None
    return out


def _fitted_json(name: str) -> dict:
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "models" / "fitted" / f"{name}.json"
    try:
        import json
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}


def _lit(v):
    """A fitted file's stringified dict / list back to an object (older exports wrote repr strings)."""
    if isinstance(v, str) and v[:1] in "{[":
        import ast
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return None
    return v


def fitted_summary(catalogues: dict | None = None) -> dict:
    """The committed fits the site runs on (models/fitted/), for the Methodology page to quote instead of code
    defaults: team strength (half-life, carry-overs), the game model's coefficients and late-game constants, the
    live model's strength multipliers, the season simulation's spread, the xG model (seasons, folding rule, best
    iteration, Platt, feature importance, out-of-fold validation), stabilisation constants, Rink value's box prior and
    Pythagorean exponent, the award models, and the catalogue sizes."""
    out: dict = {}
    ts = (_fitted_json("team_strength_params").get("result") or {})
    if ts:
        out["team_strength"] = {k: ts.get(k) for k in ("half_life_days", "lam", "k_fin", "k_goalie", "carry", "goalie_new")}
    gp = (_fitted_json("game_params").get("result") or {})
    if gp:
        out["game"] = {k: gp.get(k) for k in ("b0", "b_xg", "b_g", "home", "s", "theta", "tie_k", "k_pull", "r_en", "pull1",
                                             "pull2", "k_ot", "so_home", "n", "seasons", "fitted")}
    lv = _module("live")
    if lv is not None:
        out["live"] = {k.lower(): getattr(lv, k, None) for k in ("K_PP", "K_SH", "K_PP3", "K_SH3", "K_EVEN", "STEP")}
    sp = _fitted_json("season_sim_params")
    if sp:
        out["season_sim"] = {**(sp.get("result") or {}), "scan": sp.get("scan")}
    xg = _fitted_json("xg")
    if xg:
        seasons = xg.get("seasons") or []
        imp = _lit(xg.get("importance")) or {}
        val = _lit(xg.get("validation")) or {}
        out["xg"] = {"seasons": seasons, "n_seasons": len(seasons), "folding": "season" if len(seasons) >= 3 else "game",
                     "features": xg.get("features"), "best_iter": xg.get("best_iter"), "platt": xg.get("platt"),
                     "importance": imp, "validation": (val or {}).get("overall") if isinstance(val, dict) else None}
    st = _fitted_json("stabilise")
    if st:
        out["stabilise"] = {k: {"k": v.get("k"), "n70": v.get("n70"), "unit": v.get("unit"), "seasons": v.get("seasons")}
                            for k, v in (st.get("metrics") or {}).items() if isinstance(v, dict)}
    va = _fitted_json("value")
    if va:
        box = va.get("box") or {}
        out["value"] = {"pythag_x": va.get("pythag_x"), "seasons": va.get("seasons"), "r2_o": box.get("r2_o"),
                        "r2_d": box.get("r2_d"), "n": box.get("n")}
    aw = _fitted_json("awards_fit")
    if aw:
        out["awards"] = {a: {k: v.get(k) for k in ("ok", "n_seasons", "top1")} for a, v in (aw.get("awards") or {}).items()
                         if isinstance(v, dict)}
    rp = _fitted_json("rapm_prior")
    if rp:
        out["rapm"] = {k: rp.get(k) for k in ("season", "lam", "lambda", "shrink", "version") if k in rp}
    if catalogues:
        out["catalogues"] = catalogues
    return an.clean(out) if hasattr(an, "clean") else out
