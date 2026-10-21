"""
Game cards (schedule.json, index.json) and game centre pages (games/<gpk>.json).

GAME_CARD (PAYLOADS.md): {"gpk","date","start","status","gtype","series","home","away","hs","as","inning",
"probables","model":{"p_home","total","rl_home"},"market":{"p_home","sources"}|null,"line":{"ml","total","rl"}|null,
"wp_home"}. Model prices, in order of preference: a fresh game-model price (builder D's PA simulation) for games not
yet final; the pre-game price frozen on the game's page when it went live; the walk-forward backtest's price
(builder D's cache, priced from data before the game). Market: Kalshi / Polymarket (fetched for today and
tomorrow) else the de-vigged DraftKings closing moneyline from the store.

Game page: the card plus
* pregame: model (win, run line, total and first-five distributions), market and the ESPN / DraftKings line
  (current, open, close), lineups with matchup projections (each hitter v the opposing starter: projected wOBA and
  K% from builder D's rates by hand, odds-ratio combined with the league), weather, park factors and the plate
  umpire's season profile;
* live / final: linescore; `pitches` (column-oriented, PAYLOADS columns plus balls, strikes, outs, pitching);
  win probability per plate appearance, ours (builder D's live Markov model on the pre-game strengths, or a
  league-average model when the game context is unavailable) and ESPN's (when cached); the umpire scorecard
  (missed calls against the rulebook zone, each with its run-expectancy cost and the team it favoured); ABS
  challenges; a box score with expected stats; each pitcher's arsenal that day against his season norm; WPA
  leaders of the game.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import pitchagg as PG
from oddsmarkets.baseball.analytics.context import SeasonContext, frame_rows

logger = logging.getLogger(__name__)
PAGE_VERSION = 1
PITCH_COLS = ["inning", "half", "ab", "pitch_no", "batter", "pitcher", "pitch_type", "velo", "spin", "ivb", "hb", "plate_x",
              "plate_z", "sz_top", "sz_bot", "call", "desc", "stuff", "location", "launch_speed", "launch_angle", "xwoba_plus",
              "xwoba_savant", "hc_x", "hc_y", "event", "re24", "wpa", "balls", "strikes", "outs", "pitching"]
FINAL = ("final",)
_NEUTRAL: dict = {}


# ---------------------------------------------------------------------------------------------- prices

def backtest_prices(level: str, season: int) -> dict[str, dict]:
    """Walk-forward pre-game prices from builder D's backtest cache: {gpk: {"p_home","total","rl"}}."""
    d = an.cache_root() / "backtest"
    out: dict[str, dict] = {}
    try:
        files = sorted(d.glob(f"{level}_{season}_n*_v*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return out
    for p in files:
        r = an.read_json(p) or {}
        r = r.get("result", r) if isinstance(r, dict) else {}
        for row in r.get("games") or []:
            gpk = str(row.get("gpk"))
            md = row.get("margin_dist") or {}
            rl = None
            if md:
                rl = sum(float(v) for k, v in md.items() if int(k) >= 2)
            out[gpk] = {"p_home": row.get("model"), "total": row.get("model_total"), "rl_home": rl, "source": "backtest"}
    return out


def market_from_store(g: dict) -> dict | None:
    try:
        from oddsmarkets.baseball.sources import markets as MK
        ln = MK.store_lines(g, "close" if g.get("status") == "final" else "current")
    except Exception:                                            # noqa: BLE001
        return None
    if ln.get("p_home") is None:
        return None
    return {"p_home": round(ln["p_home"], 4), "sources": ["draftkings_ml"], "total": ln.get("total"), "p_over": ln.get("p_over")}


def line_of(g: dict) -> dict | None:
    L = g.get("lines") or {}
    if not L:
        return None
    return {"ml": L.get("ml"), "total": (L.get("total") or {}).get("line") if isinstance(L.get("total"), dict) else L.get("total"),
            "rl": (L.get("rl") or {}).get("home") if isinstance(L.get("rl"), dict) else L.get("rl")}


def price(ctx: SeasonContext, g: dict, n: int) -> dict | None:
    """Builder D's game model for one game: the summary plus its inputs (None when the context is unavailable)."""
    gc = ctx.game_ctx()
    if gc is None:
        return None
    T = ctx.teams
    if (T.get(str(g.get("home"))) or {}).get("placeholder") or (T.get(str(g.get("away"))) or {}).get("placeholder"):
        return None
    from oddsmarkets.baseball.models import game_inputs as GI
    from oddsmarkets.baseball.models import game_sim as G
    res = GI.predict(g, gc, n=n)
    out = G.summary_for_payload(res)
    lay = market_layer(ctx)
    if lay is not None:
        try:
            out = lay.apply(out, g)
        except Exception as exc:                                 # noqa: BLE001
            logger.info("market layer %s failed: %s", g.get("gpk"), exc)
    return an.clean(out)


def market_layer(ctx: SeasonContext):
    """The MLB market layer (models/market_layer.py) for the context's season as of its `today`, built once per
    context; None for Triple-A, without history, or when it fails (the simulation is then published as it is)."""
    if "_market_layer" not in ctx.__dict__:
        lay = None
        if ctx.level == "mlb":
            try:
                from oddsmarkets.baseball.models import market_layer as ML
                lay = ML.build(ctx.level, ctx.season, ctx.store, as_of=ctx.today)
            except Exception as exc:                             # noqa: BLE001
                logger.info("market layer unavailable: %s", exc)
        ctx.__dict__["_market_layer"] = lay
    return ctx.__dict__["_market_layer"]


def model_block(summary: dict | None, g: dict) -> dict | None:
    if not summary:
        return None
    rl_line = None
    L = g.get("lines") or {}
    if isinstance(L.get("rl"), dict):
        rl_line = an.fnum(L["rl"].get("home"))
    rlm = summary.get("runline") or {}
    if rl_line is not None and rl_line > 0:
        rl = rlm.get("home_+1.5")
    else:
        rl = rlm.get("home_-1.5")
    return {"p_home": an.rnd(summary.get("p_home"), 4), "total": an.rnd((summary.get("runs") or {}).get("total"), 2),
            "rl_home": an.rnd(rl, 4)}


# ---------------------------------------------------------------------------------------------- cards

def inning_of(g: dict) -> int | None:
    inn = g.get("innings")
    if isinstance(inn, (int, float)):
        return int(inn) or None
    return len(inn or []) or None


def card(ctx: SeasonContext, g: dict, model: dict | None = None, market: dict | None = None, wp_home: float | None = None) -> dict:
    st = g.get("status")
    return {"gpk": str(g.get("gpk")), "date": g.get("date"), "start": g.get("start"), "status": st, "gtype": g.get("gtype"),
            "series": g.get("series"), "home": str(g.get("home")), "away": str(g.get("away")), "hs": g.get("hs"), "as": g.get("as"),
            "inning": inning_of(g) if st in ("live", "final") else None, "probables": g.get("probables") or {"home": None, "away": None},
            "model": model, "market": market, "line": line_of(g), "wp_home": an.rnd(wp_home, 4) if st == "live" else None,
            "venue": g.get("venue")}


# ---------------------------------------------------------------------------------------------- live model

def live_model(ctx: SeasonContext, g: dict):
    """(LiveModel, "model" | "league") for a game: the pre-game strengths when builder D's context is available,
    else a league-average model (one shared instance)."""
    try:
        from oddsmarkets.baseball.models import live as LV
        # the game's own model (pre-game strengths) for games in play or just finished in the current season; a shared
        # league-average model for the archive (one Markov solve instead of one per page)
        recent = ctx.current and (g.get("status") != "final" or str(g.get("date")) >= (ctx.today - timedelta(days=1)).isoformat())
        gc = ctx.game_ctx() if recent else None
        if gc is not None:
            return LV.LiveModel(gc.spec(g)), "model"
        key = (ctx.level, ctx.season >= 2020 and g.get("gtype") == "R")
        if key not in _NEUTRAL:
            from oddsmarkets.baseball.models import game_sim as G
            from oddsmarkets.baseball.models._dio import NE
            L = G.league_split()
            spec = {"home": G.neutral_side(L), "away": G.neutral_side(L), "league": L, "auto_runner": key[1], "hfa": np.ones(NE),
                    "level": ctx.level}
            _NEUTRAL[key] = LV.LiveModel(spec)
        return _NEUTRAL[key], "league"
    except Exception as exc:                                     # noqa: BLE001
        logger.info("live model unavailable: %s", exc)
        return None, None


def _bases(row) -> int:
    b = 0
    for bit, c in ((1, "on_1b"), (2, "on_2b"), (4, "on_3b")):
        x = row.get(c)
        if x is not None and not (isinstance(x, float) and math.isnan(x)) and not pd.isna(x):
            b |= bit
    return b


def wp_series(gp: pd.DataFrame, lm, g: dict) -> tuple[list, dict]:
    """Our win probability before every PA and at the end: [[pa_index, inning, half, wp_home], ...], and per-PA WPA
    (batting side) keyed by at_bat_number."""
    if lm is None or not len(gp):
        return [], {}
    first = gp.groupby("at_bat_number", sort=True).head(1)
    out, wp = [], {}
    prev = None
    prev_ab = None
    for i, r in enumerate(first.to_dict("records")):
        top = str(r.get("inning_topbot") or "").lower().startswith("t")
        hs = an.fnum(r.get("home_score")) or 0
        as_ = an.fnum(r.get("away_score")) or 0
        st = {"inning": int(r.get("inning") or 1), "top": top, "outs": int(an.fnum(r.get("outs_when_up")) or 0), "bases": _bases(r),
              "score": [int(as_), int(hs)]}
        try:
            p = float(lm.win_prob(st))
        except Exception:                                        # noqa: BLE001
            continue
        out.append([i, st["inning"], 0 if top else 1, round(p, 4)])
        if prev is not None and prev_ab is not None:
            wp[prev_ab] = (p - prev[0]) * (1 if not prev[1] else -1)
        prev, prev_ab = (p, top), int(r["at_bat_number"])
    if g.get("status") == "final" and g.get("hs") is not None and g.get("as") is not None and out:
        end = 1.0 if g["hs"] > g["as"] else 0.0
        if prev is not None and prev_ab is not None:
            wp[prev_ab] = (end - prev[0]) * (1 if not prev[1] else -1)
        out.append([len(out), out[-1][1], out[-1][2], end])
    return out, wp


def espn_wp(ctx: SeasonContext, gpk: str) -> list | None:
    p = an.cache_root() / "espn_wp" / str(ctx.season) / f"{gpk}.json"
    w = an.read_json(p)
    if not w:
        return None
    n = max(len(w) - 1, 1)
    return [[round(i / n, 4), an.rnd(x[1] / 100.0 if (x[1] or 0) > 1 else x[1], 4)] for i, x in enumerate(w) if x and x[1] is not None]


# ---------------------------------------------------------------------------------------------- the page

def game_pitches(ctx: SeasonContext, gpks: list[str]) -> pd.DataFrame:
    """All pitches (every game type) of the given games, with builder B's per-pitch scores and builder C's xwOBA+."""
    if not gpks or not ctx.has_pitches():
        return pd.DataFrame()
    df = PG.load(ctx.level, ctx.season, PG.GAME_COLS, None, games=gpks)
    if not len(df):
        return df
    sc = ctx.scores()
    if sc is not None and len(sc):
        s2 = sc[sc["game_pk"].isin(df["game_pk"].unique())]
        df = df.merge(s2, on=["game_pk", "at_bat_number", "pitch_number"], how="left")
    b = ctx.bip()
    if b is not None and len(b) and "xwoba" in b:
        b2 = b[b["game_pk"].isin(df["game_pk"].unique())][["game_pk", "at_bat_number", "xwoba"]].drop_duplicates(["game_pk", "at_bat_number"])
        last = df.groupby(["game_pk", "at_bat_number"])["pitch_number"].transform("max") == df["pitch_number"]
        df = df.merge(b2.rename(columns={"xwoba": "_xwp"}), on=["game_pk", "at_bat_number"], how="left")
        df["_xwp"] = np.where(last.to_numpy(), df["_xwp"], np.nan)
    # The season's batted-ball scores cover regular-season games only; score the rest (postseason,
    # spring) with the committed model so every game page carries xwOBA+.
    try:
        need = df["launch_speed"].notna() & ("_xwp" not in df or df["_xwp"].isna())
        if bool(need.any()):
            from oddsmarkets.baseball.models import xwoba
            sub = df[need]
            sc2 = xwoba.predict_fitted(sub, ctx.store, ctx.level)
            if sc2 is None and ctx.level != "mlb":
                # no committed Triple-A fit (only MLB's is committed): the MLB model, which takes the park from the store
                sc2 = xwoba.predict_fitted(sub, ctx.store, "mlb")
            if sc2 is not None and len(sc2) and "xwoba" in sc2:
                k = ["game_pk", "at_bat_number"]
                m2 = sc2[k + ["xwoba"]].drop_duplicates(k).rename(columns={"xwoba": "_xwp2"})
                df = df.merge(m2, on=k, how="left")
                last = df.groupby(k)["pitch_number"].transform("max") == df["pitch_number"]
                fill = np.where(last.to_numpy(), df["_xwp2"], np.nan)
                df["_xwp"] = df["_xwp"].fillna(pd.Series(fill, index=df.index)) if "_xwp" in df else fill
                df = df.drop(columns=["_xwp2"])
    except Exception as e:                      # never break a game page over xwOBA+
        logger.warning("xwOBA+ fallback scoring failed: %s", e)
    return df


def build_page(ctx: SeasonContext, g: dict, gp: pd.DataFrame | None, card_: dict, pregame: dict | None, old: dict | None,
               season_arsenal: dict | None = None, umps: dict | None = None, re_info: dict | None = None,
               parks: dict | None = None, fl: pd.DataFrame | None = None, pa: pd.DataFrame | None = None) -> dict:
    gpk = str(g.get("gpk"))
    page: dict[str, Any] = {"ok": True, "version": PAGE_VERSION, "level": ctx.level, "season": ctx.season, "updated_at": an.now(),
                            **card_, "teams": {s: an.team_info(ctx.store, g.get(s)) for s in ("home", "away")},
                            "weather": g.get("weather"), "venue": _venue(ctx, g, parks), "umpire_hp": _ump(ctx, g, umps),
                            "decisions": g.get("decisions"), "abs_summary": g.get("abs"), "mound_visits": g.get("mound_visits"),
                            "linescore": g.get("innings"), "lines": g.get("lines")}
    page["pregame"] = pregame or (old or {}).get("pregame")
    page["lineups"] = _lineups(ctx, g)
    has = gp is not None and len(gp) > 0
    page["has_statcast"] = bool(has)
    if not has:
        if old and old.get("pitches") and old.get("status") == g.get("status") and old.get("hs") == g.get("hs"):
            for k in ("pitches", "wp", "umpire", "abs", "box", "arsenal", "wpa_leaders", "has_statcast"):
                if k in old:
                    page[k] = old[k]                     # never downgrade a page built with pitch data
        return page
    if fl is None or len(fl) != len(gp):
        gp = gp.sort_values(["at_bat_number", "pitch_number"]).reset_index(drop=True)
        fl, pa = None, None
    lm, kind = live_model(ctx, g)
    series, wpa = wp_series(gp, lm, g)
    page["wp"] = {"ours": series, "ours_kind": kind, "espn": espn_wp(ctx, gpk)}
    page["pitches"] = _pitch_rows(gp, wpa)
    page["umpire"] = _scorecard(ctx, g, gp, re_info, umps)
    page["abs"] = _abs(ctx, gp)
    page["box"] = _box(ctx, g, gp, wpa, fl, pa)
    page["linescore_totals"] = (page["box"] or {}).get("totals")
    page["arsenal"] = _arsenal_vs_norm(gp, season_arsenal or {})
    page["wpa_leaders"] = _wpa_leaders(ctx, gp, wpa)
    if g.get("status") == "live" and series:
        page["wp_home"] = series[-1][3]
    return page


def _venue(ctx: SeasonContext, g: dict, parks: dict | None) -> dict | None:
    vid = str(g.get("venue") or "")
    v = (ctx.store.get("venues") or {}).get(vid)
    if not v:
        return None
    out = {"id": vid, **{k: v.get(k) for k in ("name", "city", "roof", "elev_ft", "dims", "azimuth", "turf")}}
    home_abbr = (ctx.teams.get(str(g.get("home"))) or {}).get("abbr")
    pk = ((parks or {}).get("parks") or {}).get(home_abbr) if home_abbr else None
    if pk:
        out["factors"] = {k: an.rnd(x, 3) for k, x in ((pk.get("factors") or {}).items())}
    return out


def _ump(ctx: SeasonContext, g: dict, umps: dict | None) -> dict | None:
    u = g.get("umpire_hp")
    if not u:
        return None
    nm = ((ctx.store.get("umpires") or {}).get(str(u)) or {}).get("name")
    prof = (umps or {}).get(str(u)) or {}
    return {"id": str(u), "name": nm, "season": {k: prof.get(k) for k in ("called", "games", "accuracy", "x_accuracy", "acc_above_x",
                                                                         "consistency", "zone_per100", "runs_per_game")} if prof else None}


def _lineups(ctx: SeasonContext, g: dict) -> dict | None:
    """Posted (or projected) lineups with each hitter's matchup projection against the opposing starter."""
    gc = ctx.game_ctx() if g.get("status") != "final" or ctx.full else None
    lus = g.get("lineups") or {}
    out = {}
    for side, opp in (("home", "away"), ("away", "home")):
        tid = str(g.get(side))
        lu = lus.get(tid) or []
        src = "posted" if lu else None
        if not lu and gc is not None and g.get("status") != "final":
            try:
                from oddsmarkets.baseball.models import game_inputs as GI
                ab = gc.tid_to_abbr.get(tid, tid)
                sp = (g.get("probables") or {}).get(opp)
                th = (gc.pitcher(sp) or {}).get("throws", "R") if sp else "R"
                lu = gc.usage.lineup(ab, GI._d(g.get("date")), th) or []
                src = "projected"
            except Exception:                                    # noqa: BLE001
                lu = []
        sp = (g.get("probables") or {}).get(opp)
        rows = []
        for i, pid in enumerate([str(x) for x in lu][:9]):
            rows.append({"slot": i + 1, "pid": pid, "name": ctx.name(pid), "pos": (ctx.players.get(pid) or {}).get("pos"),
                         "bats": (ctx.players.get(pid) or {}).get("bats"), "matchup": _matchup(gc, pid, sp)})
        out[side] = {"source": src, "batters": rows, "opp_starter": sp, "opp_starter_name": ctx.name(sp) if sp else None}
    return out


def _matchup(gc, hitter: str, pitcher: str | None) -> dict | None:
    if gc is None or not pitcher:
        return None
    try:
        from oddsmarkets.baseball.models import game_sim as G
        h = gc.hitter(hitter)
        p = gc.pitcher(pitcher)
        th = p.get("throws", "R")
        bh = G._bat_hand(h.get("bats", "R"), th)
        probs = G.odds_ratio(np.asarray(h["rates"][th], float), np.asarray(p["rates"][bh], float), np.asarray(gc.league[bh + th], float))
        probs = probs / probs.sum()
        w = gc.woba if gc.woba is not None else np.array([0, .69, .72, .88, 1.25, 1.58, 2.03, 0, 0])
        return {"woba": round(float(np.dot(probs, w)), 3), "k": round(float(probs[0]), 3), "bb": round(float(probs[1]), 3),
                "hr": round(float(probs[6]), 4), "hand": bh + th, "unknown": bool(h.get("unknown") or p.get("unknown"))}
    except Exception:                                            # noqa: BLE001
        return None


def _num(x, nd=2):
    v = an.fnum(x)
    return None if v is None else round(v, nd)


def _pitch_rows(gp: pd.DataFrame, wpa: dict) -> dict:
    ev = PG._s(gp, "events")
    desc = PG._s(gp, "description")
    des = PG._s(gp, "des") if "des" in gp else pd.Series("", index=gp.index)
    top = PG._s(gp, "inning_topbot").str.lower().str.startswith("t")
    last = gp.groupby("at_bat_number")["pitch_number"].transform("max") == gp["pitch_number"]
    pth = PG._s(gp, "p_throws").to_numpy()
    arm = np.where(pth == "L", 1.0, -1.0)
    ivb = PG._f(gp, "pfx_z") * 12
    hb = PG._f(gp, "pfx_x") * 12 * arm
    rows = []
    for i, r in enumerate(gp.to_dict("records")):
        is_last = bool(last.iloc[i])
        abn = int(r["at_bat_number"])
        rows.append([int(r.get("inning") or 0), 0 if top.iloc[i] else 1, abn, int(r["pitch_number"]), str(int(r["batter"])),
                     str(int(r["pitcher"])), r.get("pitch_type") if isinstance(r.get("pitch_type"), str) else None,
                     _num(r.get("release_speed"), 1), an.inum(r.get("release_spin_rate")), _num(ivb[i], 1), _num(hb[i], 1),
                     _num(r.get("plate_x"), 3), _num(r.get("plate_z"), 3), _num(r.get("sz_top"), 2), _num(r.get("sz_bot"), 2),
                     desc.iloc[i] or None, (des.iloc[i] or None) if is_last else None, an.inum(r.get("stuff")), an.inum(r.get("location")),
                     _num(r.get("launch_speed"), 1), an.inum(r.get("launch_angle")), _num(r.get("_xwp"), 3),
                     _num(r.get("estimated_woba_using_speedangle"), 3), _num(r.get("hc_x"), 1), _num(r.get("hc_y"), 1),
                     (ev.iloc[i] or None) if is_last else None, _num(r.get("delta_run_exp"), 3),
                     _num(wpa.get(abn), 4) if is_last else None, an.inum(r.get("balls")), an.inum(r.get("strikes")),
                     an.inum(r.get("outs_when_up")), an.inum(r.get("pitching"))])
    return {"cols": PITCH_COLS, "rows": rows}


def _scorecard(ctx: SeasonContext, g: dict, gp: pd.DataFrame, re_info: dict | None, umps: dict | None) -> dict | None:
    """Missed calls against the rulebook zone (|plate_x| <= 0.83 ft, sz_bot - 0.12 <= plate_z <= sz_top + 0.12), each
    valued for the batting team with builder C's call values (run value of a ball minus a strike at that count and
    base-out state); favour = runs gained by the home batters minus the away batters."""
    d = gp[PG._s(gp, "description").isin(["called_strike", "ball", "blocked_ball"])].copy()
    d = d[d["plate_x"].notna() & d["plate_z"].notna()]
    if not len(d):
        return None
    top_ = pd.to_numeric(d["sz_top"], errors="coerce").fillna(3.4)
    bot_ = pd.to_numeric(d["sz_bot"], errors="coerce").fillna(1.55)
    px, pz = pd.to_numeric(d["plate_x"], errors="coerce"), pd.to_numeric(d["plate_z"], errors="coerce")
    d["in_zone"] = ((px.abs() <= 0.83) & (pz >= bot_ - 0.12) & (pz <= top_ + 0.12)).astype(int)
    d["y"] = PG._s(d, "description").eq("called_strike").astype(int)
    vals = None
    try:
        if re_info and re_info.get("re") is not None and re_info.get("counts"):
            from oddsmarkets.baseball.models import umpire as U
            dd = d.copy()
            for c in ("balls", "strikes", "outs_when_up"):
                dd[c] = pd.to_numeric(dd[c], errors="coerce").fillna(0).astype(int)
            vals = U.call_values(dd, np.asarray(re_info["re"], float), re_info["counts"])
    except Exception:                                            # noqa: BLE001
        vals = None
    if vals is None:
        vals = np.full(len(d), 0.125)
    d["value"] = vals
    wrong = d["y"] != d["in_zone"]
    d["impact_bat"] = np.where(wrong, np.where(d["y"] == 1, -d["value"], d["value"]), 0.0)
    d["home_bat"] = ~PG._s(d, "inning_topbot").str.lower().str.startswith("t")
    miss = d[wrong]
    home_gain = float(d.loc[d["home_bat"], "impact_bat"].sum())
    away_gain = float(d.loc[~d["home_bat"], "impact_bat"].sum())
    fav = home_gain - away_gain
    calls = [[int(r["inning"]), 0 if not hb else 1, int(r["at_bat_number"]), int(r["pitch_number"]), str(int(r["batter"])),
              str(int(r["pitcher"])), an.inum(r["balls"]), an.inum(r["strikes"]), _num(r["plate_x"], 3), _num(r["plate_z"], 3),
              _num(r["sz_top"], 2), _num(r["sz_bot"], 2), "strike" if r["y"] == 1 else "ball", round(float(r["impact_bat"]), 3)]
             for r, hb in zip(miss.to_dict("records"), miss["home_bat"].to_numpy())]
    calls.sort(key=lambda x: -abs(x[-1]))
    u = g.get("umpire_hp")
    return {"umpire": str(u) if u else None, "name": ((ctx.store.get("umpires") or {}).get(str(u)) or {}).get("name") if u else None,
            "called": int(len(d)), "missed": int(wrong.sum()), "accuracy": round(float(1 - wrong.mean()), 4),
            "home_gain": round(home_gain, 3), "away_gain": round(away_gain, 3), "home_favour": round(fav, 3),
            "favoured": str(g.get("home")) if fav > 0.005 else (str(g.get("away")) if fav < -0.005 else None),
            "total_impact": round(float(np.abs(d["impact_bat"]).sum()), 3),
            "calls_cols": ["inning", "half", "ab", "pitch_no", "batter", "pitcher", "balls", "strikes", "plate_x", "plate_z", "sz_top",
                           "sz_bot", "call", "runs_batting"], "calls": calls,
            "season": {k: (umps or {}).get(str(u), {}).get(k) for k in ("accuracy", "x_accuracy", "acc_above_x", "consistency")} if u else None}


def _abs(ctx: SeasonContext, gp: pd.DataFrame) -> list | None:
    """ABS challenges in the play text (2026): [{inning, half, ab, who, kind, result, batter, pitcher}]."""
    if "des" not in gp:
        return None
    from oddsmarkets.baseball.models import umpire as U
    des = PG._s(gp, "des")
    m = des.str.contains(" challenged (", regex=False)
    if not m.any():
        return []
    x = gp[m].drop_duplicates(["at_bat_number"])
    ex = PG._s(x, "des").str.extract(U.DES_RE)
    out = []
    def _t(v):
        return v.strip() if isinstance(v, str) and v.strip() else None
    for (_, r), (_, e) in zip(x.iterrows(), ex.iterrows()):
        out.append({"inning": an.inum(r["inning"]), "half": 0 if str(r["inning_topbot"]).lower().startswith("t") else 1,
                    "ab": int(r["at_bat_number"]), "who": _t(e.get("who")), "kind": _t(e.get("kind")),
                    "result": (_t(e.get("res")) or "").lower() or None, "batter": str(int(r["batter"])), "pitcher": str(int(r["pitcher"]))})
    return out


BOX_COLS = ["pa", "ab", "h", "hr", "bb", "ibb", "k", "hbp", "tb", "w_num", "w_den", "xw_num", "pitches_all", "csw", "contact", "whiff",
            "pitches"]


def _rows(df: pd.DataFrame) -> dict:
    cols = list(df.columns)
    return {k: dict(zip(cols, map(float, row))) for k, row in zip(df.index, df.to_numpy())}


def _box(ctx: SeasonContext, g: dict, gp: pd.DataFrame, wpa: dict, fl: pd.DataFrame | None = None, pa: pd.DataFrame | None = None) -> dict:
    """Batting and pitching lines with expected stats, and the R/H/E totals (E = Statcast field_error events: a lower bound,
    errors on other plays are not in the pitch data). Earned runs are not in the pitch data: pitchers carry R."""
    fl = PG.flags(gp) if fl is None else fl
    top = PG._s(gp, "inning_topbot").str.lower().str.startswith("t").to_numpy()
    bat_side = np.where(top, "away", "home")
    out: dict[str, Any] = {"batting": {"home": [], "away": []}, "pitching": {"home": [], "away": []}}
    xwp = pd.to_numeric(gp.get("_xwp"), errors="coerce") if "_xwp" in gp else pd.Series(np.nan, index=gp.index)
    wpa_s = pd.Series(gp["at_bat_number"].map(lambda a: wpa.get(int(a), 0.0)).to_numpy(), index=gp.index)
    last = (gp.groupby("at_bat_number")["pitch_number"].transform("max") == gp["pitch_number"]).to_numpy()
    for side in ("home", "away"):
        m = bat_side == side
        if not m.any():
            continue
        sub, f = gp[m], fl[m]
        agg = _rows(f[BOX_COLS].groupby(sub["batter"].astype(str).to_numpy(), sort=False).sum())
        x_num = pd.Series(np.where(last[m] & np.isfinite(xwp[m].to_numpy()), xwp[m].to_numpy(),
                                   np.where(last[m], pd.to_numeric(sub["woba_value"], errors="coerce").fillna(0), 0)), index=sub.index)
        xn = x_num.groupby(sub["batter"].astype(str).to_numpy(), sort=False).sum()
        wp_b = wpa_s[m].where(last[m], 0.0).groupby(sub["batter"].astype(str).to_numpy(), sort=False).sum()
        bkey = sub["batter"].astype(str)
        evmax = pd.to_numeric(sub["launch_speed"], errors="coerce").groupby(bkey).max()
        order = list(dict.fromkeys(bkey))
        for pid in order:
            r = agg[pid]
            out["batting"][side].append({"pid": pid, "name": ctx.name(pid), "pa": int(r["pa"]), "ab": int(r["ab"]), "h": int(r["h"]),
                                         "hr": int(r["hr"]), "bb": int(r["bb"] + r["ibb"]), "so": int(r["k"]), "hbp": int(r["hbp"]),
                                         "tb": int(r["tb"]), "xwoba_plus": an.rnd(an.div(xn.get(pid), r["w_den"]), 3),
                                         "xwoba_savant": an.rnd(an.div(r["xw_num"], r["w_den"]), 3),
                                         "woba": an.rnd(an.div(r["w_num"], r["w_den"]), 3), "ev_max": an.rnd(evmax.get(pid), 1),
                                         "pitches": int(r["pitches_all"]), "wpa": an.rnd(wp_b.get(pid), 3)})
    pa = PG.pa_table(gp) if pa is None else pa
    ev = PG._s(gp, "events")
    errs = ev.eq("field_error").to_numpy()
    out["totals"] = {}
    for side in ("home", "away"):
        m = bat_side == side
        out["totals"][side] = {"r": g.get("hs") if side == "home" else g.get("as"), "h": int(fl.loc[m, "h"].sum()),
                               "e": int((errs & ~m).sum())}
    for side, fld_top in (("home", True), ("away", False)):
        m = top if fld_top else ~top
        if not m.any():
            continue
        sub, f = gp[m], fl[m]
        agg = _rows(f[BOX_COLS].groupby(sub["pitcher"].astype(str).to_numpy(), sort=False).sum())
        pas = pa[pa["half"] == (0 if fld_top else 1)]
        ln = pas.groupby(pas["pitcher"].astype(str)).agg(outs=("outs_rec", "sum"), runs=("runs", "sum"))
        sc = sub.groupby(sub["pitcher"].astype(str))[["stuff", "pitching"]].mean() if "stuff" in sub else None
        velo = pd.to_numeric(sub["release_speed"], errors="coerce").groupby(sub["pitcher"].astype(str)).max()
        wp_p = (-wpa_s[m].where(last[m], 0.0)).groupby(sub["pitcher"].astype(str).to_numpy(), sort=False).sum()
        xn_p = pd.Series(np.where(last[m] & np.isfinite(xwp[m].to_numpy()), xwp[m].to_numpy(),
                                  np.where(last[m], pd.to_numeric(sub["woba_value"], errors="coerce").fillna(0), 0)),
                         index=sub.index).groupby(sub["pitcher"].astype(str).to_numpy(), sort=False).sum()
        for pid in dict.fromkeys(sub["pitcher"].astype(str)):
            r = agg[pid]
            outs = int(ln["outs"].get(pid, 0)) if len(ln) else 0
            out["pitching"][side].append({"pid": pid, "name": ctx.name(pid), "ip": f"{outs // 3}.{outs % 3}", "outs": outs,
                                          "bf": int(r["pa"]), "h": int(r["h"]), "r": int(ln["runs"].get(pid, 0)) if len(ln) else None,
                                          "bb": int(r["bb"] + r["ibb"]), "so": int(r["k"]), "hr": int(r["hr"]),
                                          "pitches": int(r["pitches_all"]), "strikes": int(r["csw"] + r["contact"]),
                                          "whiffs": int(r["whiff"]), "csw": an.rnd(an.div(r["csw"], r["pitches"]), 3),
                                          "velo_max": an.rnd(velo.get(pid), 1),
                                          "stuff": an.inum(sc.loc[pid, "stuff"]) if sc is not None and pid in sc.index else None,
                                          "pitching": an.inum(sc.loc[pid, "pitching"]) if sc is not None and pid in sc.index else None,
                                          "xwoba_plus": an.rnd(an.div(xn_p.get(pid), r["w_den"]), 3),
                                          "xwoba_savant": an.rnd(an.div(r["xw_num"], r["w_den"]), 3), "wpa": an.rnd(wp_p.get(pid), 3)})
    return out


def _arsenal_vs_norm(gp: pd.DataFrame, season_arsenal: dict) -> dict:
    """{pitcher: {pt: {n, velo, ivb, hb, spin, stuff, whiffs, csw, d_velo, d_ivb, d_hb, d_spin, d_stuff}}} (season norm deltas)."""
    pth = PG._s(gp, "p_throws").to_numpy()
    arm = np.where(pth == "L", 1.0, -1.0)
    d = pd.DataFrame({"pitcher": gp["pitcher"].astype(str).to_numpy(), "pt": PG._s(gp, "pitch_type").to_numpy(),
                      "velo": PG._f(gp, "release_speed"), "spin": PG._f(gp, "release_spin_rate"), "ivb": PG._f(gp, "pfx_z") * 12,
                      "hb": PG._f(gp, "pfx_x") * 12 * arm, "stuff": PG._f(gp, "stuff") if "stuff" in gp else np.nan,
                      "whiff": PG._s(gp, "description").isin(PG.WHIFFS).to_numpy().astype(float),
                      "csw": PG._s(gp, "description").isin(PG.WHIFFS | {"called_strike"}).to_numpy().astype(float)})
    d = d[d["pt"] != ""]
    out: dict[str, dict] = {}
    for (pid, pt), x in d.groupby(["pitcher", "pt"]):
        norm = (season_arsenal.get(pid) or {}).get(pt) or {}
        row = {"n": int(len(x)), "velo": _num(x["velo"].mean(), 1), "velo_max": _num(x["velo"].max(), 1), "ivb": _num(x["ivb"].mean(), 1),
               "hb": _num(x["hb"].mean(), 1), "spin": an.inum(x["spin"].mean()), "stuff": an.inum(x["stuff"].mean()),
               "whiffs": int(x["whiff"].sum()), "csw": _num(x["csw"].mean(), 3)}
        for k in ("velo", "ivb", "hb", "spin", "stuff"):
            a, b = an.fnum(row.get(k)), an.fnum(norm.get(k))
            row[f"d_{k}"] = None if a is None or b is None else round(a - b, 1)
        out.setdefault(pid, {})[pt] = row
    return out


def _wpa_leaders(ctx: SeasonContext, gp: pd.DataFrame, wpa: dict) -> list:
    if not wpa:
        return []
    first = gp.groupby("at_bat_number").head(1)
    rows = []
    for r in first.to_dict("records"):
        abn = int(r["at_bat_number"])
        if abn in wpa:
            rows.append({"ab": abn, "inning": an.inum(r.get("inning")), "batter": str(int(r["batter"])), "pitcher": str(int(r["pitcher"])),
                         "wpa": round(float(wpa[abn]), 4)})
    rows.sort(key=lambda x: -abs(x["wpa"]))
    return rows[:8]


def page_sig(g: dict, n_pitches: int, model_versions: tuple) -> str:
    parts = [PAGE_VERSION, model_versions, g.get("status"), g.get("hs"), g.get("as"), bool(g.get("lines")), g.get("lineups") is not None,
             g.get("umpire_hp"), n_pitches, json.dumps(g.get("abs"), sort_keys=True, default=str)]
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


def model_versions() -> tuple:
    out = []
    for mod, attr in (("stuff", "MODEL_VERSION"), ("location", "MODEL_VERSION"), ("pitching", "MODEL_VERSION"), ("xwoba", "MODEL_VERSION"),
                      ("game_sim", "VERSION"), ("re24", "MODEL_VERSION"), ("umpire", "MODEL_VERSION")):
        try:
            import importlib
            out.append(str(getattr(importlib.import_module(f"oddsmarkets.baseball.models.{mod}"), attr)))
        except Exception:                                        # noqa: BLE001
            out.append("-")
    return tuple(out)


def pitch_counts(level: str, season: int) -> dict[str, int]:
    """Pitches per game in the season's table (a cheap column read), for page signatures."""
    p = an.pitch_path(level, season)
    if not p.exists():
        return {}
    try:
        s = pd.read_parquet(p, columns=["game_pk"])["game_pk"]
        return {str(int(k)): int(v) for k, v in s.value_counts().items()}
    except Exception:                                            # noqa: BLE001
        return {}
