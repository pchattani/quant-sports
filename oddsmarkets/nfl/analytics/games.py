"""
Game cards (index, schedule, weeks) and game centre pages (games/<game_id>.json).

Card: GAME_CARD in PAYLOADS.md. Lines follow the store's convention: spread_home is the home team's betting line
(negative = home favoured). The model block's spread uses the same convention (spread = -expected home margin) and
carries the expected margin as "margin".

Page: pre-game (model win / spread / total and score distribution, market, line open and close, QBs, injuries,
weather, unit matchups), score by quarter, drives with result and EPA, the play table with our EPA / WP against
nflfastR's and ESPN's, the win-probability chart, every fourth down with the recommendation and the WP lost, the box
score with advanced and NGS stats, key plays and game awards. A page is never downgraded: when this machine has no
play-by-play for the game (CI before nflverse publishes it) the previous page's nflverse blocks are kept; a game nflverse
has not published yet is built from ESPN's record (plays, ESPN and our live WP, drives, score by quarter and ESPN's box
score, source "espn"), replaced by the nflverse blocks on the first build after nflverse publishes (the page signature
counts the game's nflverse plays).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num

logger = logging.getLogger(__name__)
PLAY_COLS = ["qtr", "clock", "team", "down", "dist", "yl100", "type", "desc", "epa", "wpa", "wp_home_ours", "wp_home_espn",
             "ep_before", "ep_after", "players"]
EXTRA_PLAY_COLS = ["play_id", "game_seconds", "wp_home_nflfastr", "success", "home_score", "away_score"]
DRIVE_COLS = ["n", "team", "qtr", "clock", "start_yl100", "end_yl100", "plays", "yards", "result", "epa", "top", "first_downs",
              "wp_start", "wp_end"]


# ---------------------------------------------------------------------------------------------- cards

def _live(g: dict) -> dict:
    lv = g.get("live") if isinstance(g.get("live"), dict) else {}
    return {"qtr": lv.get("period", g.get("qtr")), "clock": lv.get("clock", g.get("clock")),
            "possession": lv.get("possession", g.get("possession")), "down": lv.get("down", g.get("down")),
            "dist": lv.get("distance", g.get("dist")), "yl100": lv.get("yardline_100", g.get("yl100")),
            "wp_home": lv.get("wp_home", g.get("wp_home"))}


def line_block(g: dict) -> dict | None:
    ln = g.get("lines") or {}
    if not ln or all(ln.get(k) is None for k in ("spread_home", "total", "ml_home", "ml_away")):
        return None
    return {"spread_home": an.fnum(ln.get("spread_home")), "total": an.fnum(ln.get("total")), "ml_home": an.fnum(ln.get("ml_home")),
            "ml_away": an.fnum(ln.get("ml_away")), "open": ln.get("open"), "close": ln.get("close"), "provider": ln.get("provider")}


def ml_prob(ml_home: Any, ml_away: Any) -> float | None:
    """No-vig home win probability from American moneylines."""
    def imp(x):
        x = an.fnum(x)
        if x is None or x == 0:
            return None
        return 100 / (x + 100) if x > 0 else -x / (-x + 100)
    a, b = imp(ml_home), imp(ml_away)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)


def market_block(g: dict, mk: dict | None) -> dict | None:
    """The prediction-market price of a game (builder C's sources.markets.game_prices, basis "prediction_markets":
    the mean of the Kalshi and Polymarket home-win prices); a bookmaker-only record is the line, not a market."""
    if not mk or mk.get("p_home") is None or mk.get("basis") not in (None, "prediction_markets"):
        return None
    sp, tt = mk.get("spread"), mk.get("total")
    return {"p_home": an.rnd(mk.get("p_home"), 4), "spread": an.fnum(sp) if not isinstance(sp, dict) else None,
            "total": an.fnum(tt) if not isinstance(tt, dict) else None,
            "sources": [s.get("source") if isinstance(s, dict) else s for s in (mk.get("sources") or [])]}


def weather(g: dict) -> dict | None:
    if g.get("temp") is None and g.get("wind") is None and not g.get("roof"):
        return None
    return {"temp": an.fnum(g.get("temp")), "wind": an.fnum(g.get("wind")), "roof": g.get("roof"), "surface": g.get("surface"),
            "desc": g.get("weather")}


def _qb(g: dict, side: str) -> dict | None:
    x = g.get(f"{side}_qb")
    if isinstance(x, dict):
        return {"id": x.get("id"), "name": x.get("name"), "status": x.get("status")}
    if x is None and not g.get(f"{side}_qb_name"):
        return None
    return {"id": x, "name": g.get(f"{side}_qb_name"), "status": g.get(f"{side}_qb_status")}


def card(ctx: SeasonContext, g: dict, model: dict | None = None, market: dict | None = None) -> dict:
    lv = _live(g)
    return {"game_id": g.get("game_id"), "week": g.get("week"), "gtype": g.get("gtype"), "kickoff": g.get("kickoff") or g.get("date"),
            "home": g.get("home"), "away": g.get("away"), "hs": g.get("hs"), "as": g.get("as"), "status": g.get("status"),
            "qtr": lv["qtr"], "clock": lv["clock"], "possession": lv["possession"], "down": lv["down"], "dist": lv["dist"],
            "yl100": lv["yl100"], "model": model, "market": market, "line": line_block(g),
            "wp_home": an.rnd(lv["wp_home"], 4) if g.get("status") == "live" else None,
            "qbs": {"home": _qb(g, "home"), "away": _qb(g, "away")}, "weather": weather(g),
            "overtime": g.get("overtime"), "div_game": g.get("div_game")}


def model_block(pr: dict | None) -> dict | None:
    if not pr or pr.get("p_home") is None:
        return None
    margin = pr.get("margin")
    if margin is None and pr.get("spread") is not None:
        margin = -pr["spread"]
    out = {"p_home": an.rnd(pr.get("p_home"), 4), "spread": an.rnd(pr.get("spread"), 1), "total": an.rnd(pr.get("total"), 1),
           "margin": an.rnd(margin, 1)}
    for k in ("home_pts", "away_pts", "source"):
        if pr.get(k) is not None:
            out[k] = an.rnd(pr[k], 2) if isinstance(pr[k], (int, float)) else pr[k]
    return out


def store_wp(g: dict) -> float | None:
    """The market's home win probability implied by the store's moneylines (no vig)."""
    ln = g.get("lines") or {}
    return ml_prob(ln.get("ml_home"), ln.get("ml_away"))


# ---------------------------------------------------------------------------------------------- pages

def page_sig(g: dict, n_plays: int, mv: dict, n_espn: int = 0) -> str:
    key = [g.get("status"), g.get("hs"), g.get("as"), g.get("lines"), g.get("home_qb"), g.get("away_qb"), n_plays, n_espn,
           sorted((mv or {}).items())]
    return hashlib.sha1(json.dumps(an.clean(key), sort_keys=True, default=str).encode()).hexdigest()[:16]


def _clock(qs: Any) -> str | None:
    x = an.fnum(qs)
    if x is None:
        return None
    x = int(round(x))
    return f"{x // 60}:{x % 60:02d}"


def _players(r: dict) -> list:
    out = []
    for c in ("passer_player_id", "rusher_player_id", "receiver_player_id", "kicker_player_id", "punter_player_id",
              "interception_player_id", "sack_player_id"):
        v = an.sid(r.get(c))
        if v and v not in out:
            out.append(v)
    return out


def _choice(pt: Any) -> str | None:
    return {"pass": "go", "run": "go", "punt": "punt", "field_goal": "fg"}.get(str(pt))


def espn_summary(g: dict) -> dict | None:
    """Builder A's compact ESPN live record for the game (<cache>/espn/summary/<season>/<game_id>.json), if fetched."""
    gid, season = g.get("game_id"), g.get("season")
    if not gid or not season:
        return None
    return an.read_json(an.cache_root() / "espn" / "summary" / str(season) / f"{gid}.json")


def espn_plays(g: dict) -> list | None:
    """ESPN's per-play records [[seq, qtr, clock_s, team, down, dist, yl100, type, text, home_score, away_score,
    wp_home]]: from the GAME's espn / live block, else builder A's cached summary."""
    for blk in (g.get("espn"), g.get("live")):
        if isinstance(blk, dict) and isinstance(blk.get("plays"), list) and blk["plays"]:
            return blk["plays"]
    sm = espn_summary(g)
    if isinstance(sm, dict) and isinstance(sm.get("plays"), list) and sm["plays"]:
        return sm["plays"]
    return None


def _espn_join(df: pd.DataFrame, ep: list | None) -> pd.Series:
    """ESPN home WP aligned to the nflverse plays by quarter and clock (nearest ESPN play at or before)."""
    if not ep or not len(df):
        return pd.Series(np.nan, index=df.index)
    e = pd.DataFrame(ep).iloc[:, :12]
    e.columns = ["seq", "qtr", "clock_s", "team", "down", "dist", "yl100", "type", "text", "hsc", "asc", "wp"][:e.shape[1]]
    if "wp" not in e:
        return pd.Series(np.nan, index=df.index)
    # both keys float: ESPN's whole-number quarters and clocks parse as int64, and merge_asof refuses mixed key dtypes
    # (every CI page of week 6, 2026, failed on it once the ESPN summaries were cached)
    e = e.assign(t=(pd.to_numeric(e["qtr"], errors="coerce") * 1000 - pd.to_numeric(e["clock_s"], errors="coerce")).astype(float))
    e = e.dropna(subset=["t"]).sort_values("t")
    d = pd.DataFrame({"i": df.index, "t": (num(df, "qtr") * 1000 - num(df, "quarter_seconds_remaining")).astype(float)}).dropna().sort_values("t")
    if not len(d) or not len(e):
        return pd.Series(np.nan, index=df.index)
    m = pd.merge_asof(d, e[["t", "wp"]], on="t", direction="backward")
    return pd.Series(pd.to_numeric(m["wp"], errors="coerce").to_numpy(), index=m["i"].to_numpy()).reindex(df.index)


def plays_block(G: pd.DataFrame, g: dict) -> tuple[dict, dict, pd.DataFrame]:
    """(plays {"cols","rows"}, wp chart {"cols","rows"}, the frame with home-perspective columns)."""
    G = G.sort_values(["order_sequence" if "order_sequence" in G and G["order_sequence"].notna().all() else "play_id"]).reset_index(drop=True)
    home = g.get("home")
    is_home = (G["posteam"] == home)
    wp_ff = num(G, "home_wp")
    wp_ours = num(G, "wp_home_ours")
    if wp_ours.isna().all() and "wp_ours" in G:
        w = num(G, "wp_ours")
        wp_ours = w.where(is_home, 1 - w)
    wpa_ours = num(G, "wpa_ours")
    wpa_ff = num(G, "wpa")
    epa = num(G, "epa_ours") if "epa_ours" in G and G["epa_ours"].notna().any() else num(G, "epa")
    ep_b = num(G, "ep_ours") if "ep_ours" in G and G["ep_ours"].notna().any() else num(G, "ep")
    wp_espn = _espn_join(G, espn_plays(g))
    rows = []
    for i, r in enumerate(G.to_dict("records")):
        e, b = an.fnum(epa.iat[i]), an.fnum(ep_b.iat[i])
        wpa = an.fnum(wpa_ours.iat[i]) if not pd.isna(wpa_ours.iat[i]) else an.fnum(wpa_ff.iat[i])
        rows.append([an.inum(r.get("qtr")), r.get("time") or _clock(r.get("quarter_seconds_remaining")), r.get("posteam"),
                     an.inum(r.get("down")), an.inum(r.get("ydstogo")), an.inum(r.get("yardline_100")), r.get("play_type"),
                     r.get("desc"), an.rnd(e, 3), an.rnd(wpa, 4), an.rnd(wp_ours.iat[i], 4), an.rnd(wp_espn.iat[i], 4), an.rnd(b, 3),
                     an.rnd((b + e) if b is not None and e is not None else None, 3), _players(r),
                     an.fnum(r.get("play_id")), an.inum(r.get("game_seconds_remaining")), an.rnd(wp_ff.iat[i], 4),
                     an.inum(r.get("success")), an.inum(r.get("total_home_score")), an.inum(r.get("total_away_score"))])
    wp = {"cols": ["game_seconds_remaining", "wp_home_ours", "wp_home_nflfastr", "wp_home_espn", "play_index"],
          "rows": [[an.inum(G["game_seconds_remaining"].iat[i]) if "game_seconds_remaining" in G else None, an.rnd(wp_ours.iat[i], 4),
                    an.rnd(wp_ff.iat[i], 4), an.rnd(wp_espn.iat[i], 4), i] for i in range(len(G))]}
    wh = wp_ours.fillna(wp_ff)
    G = G.assign(_wp_home=wh, _wp_home_next=wh.shift(-1).fillna(wh), _epa=epa, _wpa=wpa_ours.fillna(wpa_ff))
    return {"cols": PLAY_COLS + EXTRA_PLAY_COLS, "rows": rows}, wp, G


def drives_block(G: pd.DataFrame) -> dict:
    dc = next((c for c in ("fixed_drive", "drive") if c in G and G[c].notna().any()), None)
    if dc is None:                                               # no drive numbers: a new drive at each change of possession
        pt = G["posteam"].ffill()
        G = G.assign(_drive=(pt != pt.shift()).cumsum())
        dc = "_drive"
    rows = []
    S = G[G[dc].notna()]
    for n, d in S.groupby(dc, sort=True):
        d = d[d["posteam"].notna()]
        if "play_type" in d:
            d = d[~d["play_type"].isin(["kickoff", "extra_point"]) & ~(flag(d, "two_point_attempt").fillna(0) == 1)]
        if not len(d):
            continue
        f, l = d.iloc[0], d.iloc[-1]
        scrim = d[d["play_type"].isin(["pass", "run"])] if "play_type" in d else d
        result = f.get("fixed_drive_result") or f.get("drive_end_transition")
        end = 0 if str(result).lower() == "touchdown" else an.inum(l.get("yardline_100"))
        rows.append([an.inum(n), f.get("posteam"), an.inum(f.get("qtr")), f.get("time"), an.inum(f.get("yardline_100")),
                     end, int(len(scrim)), an.inum(num(scrim, "yards_gained").sum()), result, an.rnd(num(d, "_epa").sum(), 3),
                     f.get("drive_time_of_possession"), an.inum(f.get("drive_first_downs")), an.rnd(d["_wp_home"].iloc[0], 4),
                     an.rnd(d["_wp_home_next"].iloc[-1], 4)])
    return {"cols": DRIVE_COLS, "rows": rows}


def quarters(G: pd.DataFrame, g: dict) -> dict:
    out = {"home": [], "away": []}
    if not len(G) or "qtr" not in G:
        return out
    hs, as_ = num(G, "total_home_score").ffill().fillna(0), num(G, "total_away_score").ffill().fillna(0)
    q = num(G, "qtr")
    prev_h = prev_a = 0
    for qq in sorted(q.dropna().unique()):
        m = q == qq
        h, a = int(hs[m].max()), int(as_[m].max())
        out["home"].append(h - prev_h)
        out["away"].append(a - prev_a)
        prev_h, prev_a = h, a
    # the final play's score may not be on the table (PAT after the last snap): reconcile with the result
    if g.get("hs") is not None and out["home"]:
        out["home"][-1] += int(g["hs"]) - sum(out["home"])
        out["away"][-1] += int(g["as"]) - sum(out["away"])
    return out


GRADE_CUTS = ((0.005, "A"), (0.015, "B"), (0.03, "C"), (0.06, "D"))


def grade(wp_lost) -> str | None:
    """Letter grade of a decision from the win probability it gave up against the model's best option: A <= 0.5 pp,
    B <= 1.5, C <= 3, D <= 6, F beyond."""
    x = an.fnum(wp_lost)
    if x is None:
        return None
    for cut, g in GRADE_CUTS:
        if x <= cut:
            return g
    return "F"


def fourth_block(G: pd.DataFrame) -> list[dict]:
    D = G[(num(G, "down") == 4) & G["play_type"].isin(["pass", "run", "punt", "field_goal"])] if "play_type" in G else G.iloc[0:0]
    out = []
    for r in D.to_dict("records"):
        ch = _choice(r.get("play_type"))
        out.append({"play_id": an.fnum(r.get("play_id")), "qtr": an.inum(r.get("qtr")), "clock": r.get("time"), "team": r.get("posteam"),
                    "dist": an.inum(r.get("ydstogo")), "yl100": an.inum(r.get("yardline_100")), "score_diff": an.inum(r.get("score_differential")),
                    "choice": ch, "rec": r.get("fd_rec"), "wp": {"go": an.rnd(r.get("fd_wp_go"), 4), "punt": an.rnd(r.get("fd_wp_punt"), 4),
                                                                 "fg": an.rnd(r.get("fd_wp_fg"), 4)},
                    "p_convert": an.rnd(r.get("fd_p_convert"), 4), "wp_lost": an.rnd(r.get("fd_wp_lost"), 4),
                    "grade": an.sid(r.get("fd_grade")) or grade(r.get("fd_wp_lost")),
                    "result": "converted" if an.inum(r.get("fourth_down_converted")) == 1 else (
                        "failed" if an.inum(r.get("fourth_down_failed")) == 1 else an.sid(r.get("field_goal_result")) or ch),
                    "desc": r.get("desc")})
    return out


def box_block(G: pd.DataFrame, g: dict, names: dict, ngs_w: dict) -> dict:
    out: dict[str, Any] = {}
    S = G[G["play_type"].isin(["pass", "run"])] if "play_type" in G else G.iloc[0:0]
    for side, team in (("home", g.get("home")), ("away", g.get("away"))):
        T = S[S["posteam"] == team]
        Dd = S[S["defteam"] == team]
        blk: dict[str, Any] = {}
        pid = T["passer_id"] if "passer_id" in T else T.get("passer_player_id")
        db = (flag(T, "qb_dropback").fillna(0) == 1)
        rows = []
        if pid is not None:
            for p, d in T[db & pid.notna()].groupby(pid[db & pid.notna()]):
                att = d[(flag(d, "sack").fillna(0) == 0) & (flag(d, "qb_scramble").fillna(0) == 0)]
                cpo = num(att, "cp_ours") if "cp_ours" in att and att["cp_ours"].notna().any() else num(att, "cp")
                n = ngs_w.get(("passing", str(p))) or {}
                rows.append({"pid": str(p), "name": names.get(str(p)), "cmp": int(flag(att, "complete_pass").fillna(0).sum()), "att": int(len(att)),
                             "yds": int(num(att, "yards_gained").fillna(0).where(flag(att, "complete_pass").fillna(0) == 1, 0).sum()),
                             "td": int(flag(d, "pass_touchdown").fillna(0).sum()), "int": int(flag(d, "interception").fillna(0).sum()),
                             "sacks": int(flag(d, "sack").fillna(0).sum()), "epa": an.rnd(num(d, "_epa").sum(), 2),
                             "epa_db": an.rnd(num(d, "_epa").mean(), 3),
                             "cpoe": an.rnd(100 * (flag(att, "complete_pass").fillna(0) - cpo).mean(), 1) if cpo.notna().any() else None,
                             "adot": an.rnd(num(att, "air_yards").mean(), 1), "ttt": an.rnd(n.get("avg_time_to_throw"), 2)})
        blk["passing"] = sorted(rows, key=lambda x: -x["att"])
        rows = []
        R = T[(T["play_type"] == "run") & (flag(T, "qb_scramble").fillna(0) == 0)]
        rid = R["rusher_id"] if "rusher_id" in R else R.get("rusher_player_id")
        if rid is not None and len(R):
            for p, d in R[rid.notna()].groupby(rid[rid.notna()]):
                xr = num(d, "xrush_ours")
                n = ngs_w.get(("rushing", str(p))) or {}
                rows.append({"pid": str(p), "name": names.get(str(p)), "car": int(len(d)), "yds": int(num(d, "yards_gained").fillna(0).sum()),
                             "td": int(flag(d, "rush_touchdown").fillna(0).sum()), "epa": an.rnd(num(d, "_epa").sum(), 2),
                             "success": an.rnd((num(d, "_epa") > 0).mean(), 3),
                             "ryoe": an.rnd((num(d, "yards_gained") - xr).sum(), 1) if xr.notna().any() else an.rnd(n.get("rush_yards_over_expected"), 1)})
        blk["rushing"] = sorted(rows, key=lambda x: -x["car"])
        rows = []
        X = T[(T["play_type"] == "pass")]
        xid = X["receiver_id"] if "receiver_id" in X else X.get("receiver_player_id")
        if xid is not None and len(X):
            for p, d in X[xid.notna()].groupby(xid[xid.notna()]):
                c = flag(d, "complete_pass").fillna(0)
                n = ngs_w.get(("receiving", str(p))) or {}
                xy = num(d, "xyac_ours") if "xyac_ours" in d and d["xyac_ours"].notna().any() else num(d, "xyac_mean_yardage")
                rows.append({"pid": str(p), "name": names.get(str(p)), "tgt": int(len(d)), "rec": int(c.sum()),
                             "yds": int(num(d, "yards_gained").fillna(0).where(c == 1, 0).sum()), "td": int(flag(d, "pass_touchdown").fillna(0).sum()),
                             "epa": an.rnd(num(d, "_epa").sum(), 2), "air": an.inum(num(d, "air_yards").sum()),
                             "yac": an.inum(num(d, "yards_after_catch").where(c == 1).sum()),
                             "yacoe": an.rnd((num(d, "yards_after_catch") - xy).where(c == 1).sum(), 1) if xy.notna().any() else None,
                             "sep": an.rnd(n.get("avg_separation"), 1)})
        blk["receiving"] = sorted(rows, key=lambda x: -x["tgt"])
        # defence: sacks, tackles, interceptions, passes defensed
        drows: dict[str, dict] = {}
        for col, key, w in (("sack_player_id", "sacks", 1.0), ("half_sack_1_player_id", "sacks", 0.5), ("half_sack_2_player_id", "sacks", 0.5),
                            ("solo_tackle_1_player_id", "tkl", 1.0), ("assist_tackle_1_player_id", "tkl", 1.0),
                            ("tackle_with_assist_1_player_id", "tkl", 1.0), ("interception_player_id", "int", 1.0),
                            ("pass_defense_1_player_id", "pd", 1.0), ("pass_defense_2_player_id", "pd", 1.0), ("qb_hit_1_player_id", "hits", 1.0),
                            ("tackle_for_loss_1_player_id", "tfl", 1.0), ("forced_fumble_player_1_player_id", "ff", 1.0)):
            if col not in Dd:
                continue
            for p, c in Dd[col].dropna().astype(str).value_counts().items():
                drows.setdefault(p, {"pid": p, "name": names.get(p)})
                drows[p][key] = drows[p].get(key, 0) + w * int(c)
        blk["defense"] = sorted(drows.values(), key=lambda x: -(x.get("tkl", 0) + 3 * x.get("sacks", 0) + 3 * x.get("int", 0)))[:12]
        # team line
        e = num(T, "_epa")
        third = T[num(T, "down") == 3]
        blk["team"] = {"plays": int(len(T)), "yards": an.inum(num(T, "yards_gained").sum()), "epa": an.rnd(e.sum(), 2),
                       "epa_play": an.rnd(e.mean(), 3), "success": an.rnd((e > 0).mean(), 3),
                       "pass_epa": an.rnd(e[db].mean(), 3), "rush_epa": an.rnd(e[~db].mean(), 3),
                       "third_down": [int(flag(third, "third_down_converted").fillna(0).sum()), int(len(third))],
                       "turnovers": int(flag(T, "interception").fillna(0).sum() + flag(T, "fumble_lost").fillna(0).sum()),
                       "penalties": int((G.get("penalty_team") == team).sum()) if "penalty_team" in G else None,
                       "penalty_yds": an.inum(num(G[G["penalty_team"] == team], "penalty_yards").sum()) if "penalty_team" in G else None,
                       "proe": an.rnd((flag(T, "qb_dropback").fillna(0) - num(T, "xpass")).mean(), 3)}
        out[side] = blk
    return out


def key_plays(G: pd.DataFrame, n: int = 8) -> list[dict]:
    if not len(G):
        return []
    k = G.assign(_a=num(G, "_wpa").abs()).sort_values("_a", ascending=False).head(n)
    return [{"play_id": an.fnum(r.get("play_id")), "qtr": an.inum(r.get("qtr")), "clock": r.get("time"), "team": r.get("posteam"),
             "desc": r.get("desc"), "wpa": an.rnd(r.get("_wpa"), 4), "epa": an.rnd(r.get("_epa"), 3),
             "wp_home_before": an.rnd(r.get("_wp_home"), 4), "wp_home_after": an.rnd(r.get("_wp_home_next"), 4)}
            for r in k.to_dict("records") if r.get("_a") == r.get("_a")]


def game_awards(G: pd.DataFrame, g: dict, names: dict) -> dict:
    """Game balls: the player with the most EPA credit on each side (passer, rusher and receiver credit; receivers get
    the full play EPA on targets, passers on dropbacks), and the play of the game (largest |WPA|)."""
    out = {}
    S = G[G["play_type"].isin(["pass", "run"])] if "play_type" in G else G.iloc[0:0]
    for side, team in (("home", g.get("home")), ("away", g.get("away"))):
        T = S[S["posteam"] == team]
        cred: dict[str, float] = {}
        for c in ("passer_id", "rusher_id", "receiver_id"):
            if c in T:
                for p, v in num(T, "_epa").groupby(T[c]).sum().items():
                    cred[str(p)] = cred.get(str(p), 0.0) + float(v) * (0.5 if c != "rusher_id" else 1.0)
        if cred:
            p = max(cred, key=cred.get)
            out[f"{side}_ball"] = {"pid": p, "name": names.get(p), "epa": an.rnd(cred[p], 2)}
    kp = key_plays(G, 1)
    if kp:
        out["play_of_game"] = kp[0]
    return out


def stadium_name(g: dict) -> str | None:
    if g.get("stadium_name"):
        return g["stadium_name"]
    sid = g.get("stadium")
    try:
        from oddsmarkets.nfl import canon
        st = canon.stadium(sid) if sid else None
        if isinstance(st, dict) and st.get("name"):
            return st["name"]
    except Exception:                                            # noqa: BLE001
        pass
    return sid


def injuries_by_game(ctx: SeasonContext) -> dict[str, dict]:
    """{game_id: {"home": [...], "away": [...]}} from the nflverse injuries release (the week's final report: Out,
    Doubtful, Questionable and their practice status)."""
    df = ctx.release("injuries")
    if df is None or not len(df) or "week" not in df or "team" not in df:
        return {}
    df = df[df["report_status"].notna()] if "report_status" in df else df
    by: dict[tuple, list] = {}
    for r in df.to_dict("records"):
        key = (an.inum(r.get("week")), str(r.get("team")))
        by.setdefault(key, []).append({"pid": an.sid(r.get("gsis_id")), "name": r.get("full_name"), "pos": r.get("position"),
                                       "status": r.get("report_status"), "practice": r.get("practice_status"),
                                       "injury": r.get("report_primary_injury")})
    out = {}
    for gid, g in ctx.games.items():
        w = an.inum(g.get("week"))
        h = by.get((w, g.get("home"))) or []
        a = by.get((w, g.get("away"))) or []
        if h or a:
            out[gid] = {"home": h, "away": a, "source": "nflverse injuries"}
    return out


SO_GROUP_LABEL = {"ol": "OL", "rec": "WR/TE", "rb": "RB", "dl": "DL", "lb": "LB", "db": "DB"}


def availability_by_game(ctx: SeasonContext) -> dict[str, dict]:
    """{game_id: the starters-out term of our price}: per side the depth-chart starters (as of the team's previous
    game; QBs and specialists aside) expected to miss the game, each with his chance of missing (injury report: Out 1,
    Doubtful 0.85, Questionable 0.15; game-day inactives 1 once known) and the points it costs in the model
    (b_so_off / b_so_def per starter, models/availability.py and game_params.json), the side's total and the net
    effect on the home margin. Empty without the models."""
    if not ctx.use_models:
        return {}
    try:
        from oddsmarkets.nfl.models import availability as AV
        from oddsmarkets.nfl.models import game as GMOD
        p = GMOD.params()
        b = {"off": float(p.get("so_off") or 0.0), "def": float(p.get("so_def") or 0.0)}
        if not b["off"] and not b["def"]:
            return {}
        ST = AV.starter_rows(ctx.season)
    except Exception as exc:  # noqa: BLE001 - optional block
        ctx.model_errors["availability"] = f"{type(exc).__name__}: {exc}"
        return {}
    if ST is None or not len(ST):
        return {}
    ST = ST[ST["pm"] > 0]
    by: dict[tuple, list] = {}
    for r in ST.to_dict("records"):
        side = "off" if r["grp"] in ("ol", "rec", "rb") else "def"
        by.setdefault((int(r["week"]), r["team"]), []).append(
            {"pid": an.sid(r["gsis_id"]), "grp": SO_GROUP_LABEL.get(r["grp"], r["grp"]), "side": side, "p_miss": an.rnd(r["pm"], 2),
             "pts": an.rnd(b[side] * float(r["pm"]), 2), "by": "inactives" if r.get("by_inactives") else "report"})
    out = {}
    for gid, g in ctx.games.items():
        w = an.inum(g.get("week"))
        sides = {}
        for s in ("home", "away"):
            t = AV.team_alias(str(g.get(s)), ctx.season)
            pl = sorted(by.get((w, t)) or [], key=lambda x: x["pts"] or 0)
            sides[s] = {"players": pl, "off": an.rnd(sum(x["p_miss"] for x in pl if x["side"] == "off"), 2),
                        "def": an.rnd(sum(x["p_miss"] for x in pl if x["side"] == "def"), 2),
                        "pts": an.rnd(sum(x["pts"] or 0 for x in pl), 2)}
        if not sides["home"]["players"] and not sides["away"]["players"]:
            continue
        src = "inactives" if any(x["by"] == "inactives" for s in sides.values() for x in s["players"]) else "report"
        out[gid] = {**sides, "net_home": an.rnd(sides["home"]["pts"] - sides["away"]["pts"], 2), "src": src,
                    "coef": {"off": an.rnd(b["off"], 3), "def": an.rnd(b["def"], 3)}}
    return out


def _norm_injuries(inj: dict | None, g: dict) -> dict | None:
    """ESPN's summary keys its injury lists by team ({"KC": [...], "LAC": [...]}); the page reads {"home", "away"}
    (until 22 Oct 2026 an upcoming game's ESPN list was published under the team keys and never shown). Players
    ESPN lists as Active are left out."""
    if not isinstance(inj, dict) or "home" in inj or "away" in inj:
        return inj
    h, a = g.get("home"), g.get("away")
    if h not in inj and a not in inj:
        return inj
    keep = lambda rows: [x for x in rows or [] if not (isinstance(x, dict) and str(x.get("status") or "").lower() == "active")]  # noqa: E731
    return {"home": keep(inj.get(h)), "away": keep(inj.get(a)), "source": "ESPN"}


def _injury_impacts(inj: dict | None, av: dict | None) -> dict | None:
    """Fills each injury-list entry's `impact` (points of margin for his team, negative hurts) from the starters-out
    term: a depth-chart starter's cost, 0 for anyone else on the list. ESPN entries are matched by the ESPN id."""
    if not inj or not av:
        return inj
    xw = None
    out = dict(inj)
    for s in ("home", "away"):
        cost = {x["pid"]: x["pts"] for x in (av.get(s) or {}).get("players") or []}
        rows = []
        for x in inj.get(s) or []:
            if not isinstance(x, dict):
                rows.append(x)
                continue
            pid = x.get("pid")
            if not pid and x.get("espn_athlete"):
                if xw is None:
                    from oddsmarkets.nfl.analytics import people
                    xw = people.espn_xwalk()
                pid = xw.get(str(x["espn_athlete"]))
            rows.append({**x, "pid": pid or x.get("pid"), "impact": cost.get(pid, 0.0) if pid else None,
                         "starter": pid in cost if pid else None})
        out[s] = rows
    return out


def build_page(ctx: SeasonContext, g: dict, G: pd.DataFrame | None, crd: dict, pregame: dict | None, old: dict | None,
               names: dict, ngs_w: dict, matchups: dict | None, injuries: dict | None = None,
               availability: dict | None = None) -> dict:
    out = {"ok": True, "game_id": g["game_id"], "season": ctx.season, "updated_at": an.now(), "card": crd,
           "game": {**{k: g.get(k) for k in ("stadium", "roof", "surface", "temp", "wind", "referee", "home_coach", "away_coach",
                                            "home_rest", "away_rest", "div_game", "overtime", "espn_id", "date", "neutral")},
                    "stadium_id": g.get("stadium"), "stadium_name": stadium_name(g)},
           "pregame": pregame or (old or {}).get("pregame"), "matchups": matchups,
           "credits": [an.NFLVERSE_CREDIT] + ([an.FTN_CREDIT] if ctx.season >= 2022 else []) + ([an.NGS_CREDIT] if ctx.season >= 2016 else [])}
    sm = espn_summary(g) if g.get("status") != "final" or not (old or {}).get("injuries") else None
    # the NFL's report via nflverse first once it has this week (complete, with gsis ids); ESPN's list before that
    # (since 22 Oct 2026; ESPN's summary lists about five players a team)
    out["injuries"] = (injuries or {}).get(g["game_id"]) or g.get("injuries") or (sm or {}).get("injuries") or (old or {}).get("injuries")
    av = (availability or {}).get(g["game_id"]) if availability is not None else None
    out["availability"] = av if availability else (old or {}).get("availability")
    out["injuries"] = _injury_impacts(_norm_injuries(out["injuries"], g), out["availability"])
    out["espn_predictor"] = (sm or {}).get("predictor") or (old or {}).get("espn_predictor")
    ep = espn_plays(g) if G is None or not len(G) else None
    if G is not None and len(G):
        plays, wp, G2 = plays_block(G, g)
        out.update(plays=plays, wp=wp, drives=drives_block(G2), score=quarters(G2, g), fourth_downs=fourth_block(G2),
                   box=box_block(G2, g, names, ngs_w), key_plays=key_plays(G2), awards=game_awards(G2, g, names), source="nflverse")
    elif old and old.get("plays") and (old.get("source") == "nflverse" or not ep):
        for k in ("plays", "wp", "drives", "score", "fourth_downs", "box", "key_plays", "awards", "source"):
            out[k] = old.get(k)
    else:
        # nflverse has not published the week yet: the page is built from ESPN's record (plays, drives, ESPN and our
        # live WP, score by quarter, ESPN's box score); the next build after nflverse publishes replaces it
        out.update(plays=None, wp=None, drives=None, score=None, fourth_downs=[], box=None, key_plays=[], awards=None,
                   source="espn" if ep else None)
        if ep:
            from oddsmarkets.nfl.analytics import adapters
            pre = (pregame or {}).get("model") or (crd or {}).get("model")
            rec = {"plays": ep, "status": g.get("status"), "away": g.get("away")}
            ser = adapters.live_series(ctx, g, rec, pre)
            eps = adapters.live_epa(ctx, g, rec)
            out.update(espn_blocks(g, ep, espn_summary(g) or {}, ser, eps))
    return out


ESPN_DRIVE_RESULT = {"TD": "Touchdown", "FG": "Field goal", "PUNT": "Punt", "INT": "Interception", "FUMBLE": "Fumble",
                     "DOWNS": "Turnover on downs", "MISSED FG": "Missed field goal", "BLOCKED FG": "Blocked field goal",
                     "BLOCKED PUNT": "Blocked punt", "END OF HALF": "End of half", "END OF GAME": "End of game", "SAFETY": "Safety",
                     "FG MISSED": "Missed field goal", "END OF 4TH QUARTER": "End of game"}


def _pair(v: Any, sep: str = "/") -> tuple[int | None, int | None]:
    """'20/30' -> (20, 30); '3-25' with sep '-' -> (3, 25)."""
    try:
        a, b = str(v).split(sep, 1)
        return an.inum(a), an.inum(b)
    except (ValueError, AttributeError):
        return None, None


def _game_seconds(qtr: Any, clock_s: Any) -> int | None:
    q, c = an.inum(qtr), an.inum(clock_s)
    if q is None or c is None:
        return None
    return (4 - q) * 900 + c if q <= 4 else c


def espn_box(g: dict, sm: dict, xwalk: dict | None = None) -> dict | None:
    """ESPN's box score in the nflverse box's shape ({"home"|"away": {passing, rushing, receiving, defense, kicking,
    punting, team}}); pid is the gsis id when the crosswalk knows the ESPN athlete, else None (the name always shows)."""
    bx = sm.get("box") or {}
    if not bx:
        return None
    xw = xwalk or {}
    out: dict[str, Any] = {}
    for side in ("home", "away"):
        t = bx.get(g.get(side)) or {}
        pl = t.get("players") or {}

        def rows(cat):
            c = pl.get(cat) or {}
            keys = c.get("keys") or []
            for r in c.get("rows") or []:
                yield {"pid": xw.get(str(r[0])), "name": r[1]}, dict(zip(keys, r[2:]))
        blk: dict[str, Any] = {}
        blk["passing"] = []
        for head, s in rows("passing"):
            cmp_, att = _pair(s.get("completions/passingAttempts"))
            blk["passing"].append({**head, "cmp": cmp_, "att": att, "yds": an.inum(s.get("passingYards")), "td": an.inum(s.get("passingTouchdowns")),
                                   "int": an.inum(s.get("interceptions")), "sacks": _pair(s.get("sacks-sackYardsLost"), "-")[0]})
        blk["rushing"] = [{**head, "car": an.inum(s.get("rushingAttempts")), "yds": an.inum(s.get("rushingYards")),
                           "td": an.inum(s.get("rushingTouchdowns"))} for head, s in rows("rushing")]
        blk["receiving"] = [{**head, "tgt": an.inum(s.get("receivingTargets")), "rec": an.inum(s.get("receptions")),
                             "yds": an.inum(s.get("receivingYards")), "td": an.inum(s.get("receivingTouchdowns"))} for head, s in rows("receiving")]
        ints = {h["name"]: an.inum(s.get("interceptions")) for h, s in rows("interceptions")}
        dfn = []
        for head, s in rows("defensive"):
            dfn.append({**head, "tkl": an.inum(s.get("totalTackles")), "sacks": an.fnum(s.get("sacks")), "tfl": an.inum(s.get("tacklesForLoss")),
                        "pd": an.inum(s.get("passesDefended")), "hits": an.inum(s.get("QBHits")), "int": ints.get(head["name"]) or 0})
        blk["defense"] = sorted(dfn, key=lambda x: -((x["tkl"] or 0) + 3 * (x["sacks"] or 0) + 3 * (x["int"] or 0)))[:12]
        kick = []
        for head, s in rows("kicking"):
            fgm, fga = _pair(s.get("fieldGoalsMade/fieldGoalAttempts"))
            xpm, _ = _pair(s.get("extraPointsMade/extraPointAttempts"))
            kick.append({**head, "fgm": fgm, "fga": fga, "xpm": xpm})
        blk["kicking"] = kick
        blk["punting"] = [{**head, "punts": an.inum(s.get("punts")), "yds": an.inum(s.get("puntYards"))} for head, s in rows("punting")]
        ts = {k: v for k, v in t.get("team") or []}
        third = _pair(ts.get("thirdDownEff"), "-")
        pen = _pair(ts.get("totalPenaltiesYards"), "-")
        blk["team"] = {"plays": an.inum(ts.get("totalOffensivePlays")), "yards": an.inum(ts.get("totalYards")), "epa": None, "epa_play": None,
                       "success": None, "pass_epa": None, "rush_epa": None,
                       "third_down": [third[0], third[1]] if third[1] is not None else None, "turnovers": an.inum(ts.get("turnovers")),
                       "penalties": pen[0], "penalty_yds": pen[1], "proe": None}
        out[side] = blk
    return out if any((out.get(s) or {}).get("passing") for s in ("home", "away")) else None


def espn_blocks(g: dict, ep: list, sm: dict, ser: list | None = None, eps: list | None = None) -> dict:
    """The play-level blocks of a game page from ESPN's record, in the nflverse blocks' shapes. Our WP is the pre-snap
    value on ESPN's states (models/live.wp_series) and WPA its change to the next play; EPA and EP from our EP model
    on the same states (live.epa_series; 22 Oct 2026), provisional until nflverse publishes. Fourth-down grades and
    game balls need nflverse and stay empty."""
    home = g.get("home")
    ours = {an.inum(r[0]): an.fnum(r[1]) for r in ser or [] if isinstance(r, (list, tuple)) and len(r) >= 2}
    has_state = {an.inum(r[0]): bool(r[3]) for r in ser or [] if isinstance(r, (list, tuple)) and len(r) >= 4}
    epd = {an.inum(r[0]): (an.fnum(r[1]), an.fnum(r[2])) for r in eps or [] if isinstance(r, (list, tuple)) and len(r) >= 3}
    P = [p for p in ep if isinstance(p, (list, tuple)) and len(p) >= 12]
    rows, wps = [], []
    for i, p in enumerate(P):
        seq, qtr, clk, team, down, dist, yl, typ, text, hsc, asc, w = p[:12]
        o = ours.get(an.inum(seq))
        # WPA: from this play's state to the next play that has one (timeouts and ends of quarters carry the value
        # and get none, so a swing is credited to the play that made it)
        nxt = next((P[j] for j in range(i + 1, len(P)) if has_state.get(an.inum(P[j][0]), True)), None)
        o_next = ours.get(an.inum(nxt[0])) if nxt is not None else (o if g.get("status") != "final" else
                                                                     (1.0 if (an.fnum(hsc) or 0) > (an.fnum(asc) or 0) else 0.0 if (an.fnum(hsc) or 0) < (an.fnum(asc) or 0) else 0.5))
        if has_state and not has_state.get(an.inum(seq), True):
            o_next = None
            dw = None
        elif o is not None and o_next is not None:
            dw = o_next - o                                         # ours: WP before the next snap - before this one
        else:
            w_prev = an.fnum(P[i - 1][11]) if i else None
            dw = (an.fnum(w) - w_prev) if an.fnum(w) is not None and w_prev is not None else None
        wpa = None if dw is None or not team else (dw if team == home else -dw)
        gs = _game_seconds(qtr, clk)
        w_pre = an.fnum(P[i - 1][11]) if i else None             # ESPN's WP is after its play: before the snap = the last play's
        e_b, e_a = epd.get(an.inum(seq), (None, None))
        rows.append([an.inum(qtr), _clock(clk), team, an.inum(down) or None, an.inum(dist), an.inum(yl), typ, text, an.rnd(e_a, 3),
                     an.rnd(wpa, 4), an.rnd(o, 4), an.rnd(w_pre, 4), an.rnd(e_b, 3),
                     an.rnd(e_b + e_a, 3) if e_b is not None and e_a is not None else None, [], an.inum(seq), gs, None,
                     (1 if e_a > 0 else 0) if e_a is not None else None, an.inum(hsc), an.inum(asc)])
        wps.append([gs, an.rnd(o, 4), None, an.rnd(w_pre, 4), i])
    drives = []
    for n, d in enumerate(sm.get("drives") or [], start=1):
        res = str(d.get("result") or "").strip()
        res = ESPN_DRIVE_RESULT.get(res.upper(), res.title() if res.isupper() else res) or None
        s, y = an.inum(d.get("start_yl100")), an.inum(d.get("yards"))
        end = 0 if res == "Touchdown" else (max(0, min(100, s - y)) if s is not None and y is not None else None)
        drives.append([n, d.get("team"), an.inum(d.get("start_q")), _clock(d.get("start_clock")), s, end, an.inum(d.get("plays")), y, res,
                       None, d.get("elapsed"), None, None, None])
    ls = sm.get("linescores") or {}
    if ls.get("home") and ls.get("away") and len(ls["home"]) == len(ls["away"]):
        score = {"home": [int(x) for x in ls["home"]], "away": [int(x) for x in ls["away"]]}
    else:                                                        # by quarter from the running score of the plays
        score, ph, pa = {"home": [], "away": []}, 0, 0
        for q in sorted({r[0] for r in rows if r[0] is not None}):
            qr = [r for r in rows if r[0] == q and r[19] is not None]
            h, a = (max(r[19] for r in qr), max(r[20] for r in qr)) if qr else (ph, pa)
            score["home"].append(h - ph)
            score["away"].append(a - pa)
            ph, pa = h, a
    kp = sorted((r for r in rows if r[9] is not None), key=lambda r: -abs(r[9]))[:8]
    key = [{"play_id": r[15], "qtr": r[0], "clock": r[1], "team": r[2], "desc": r[7], "wpa": r[9], "epa": r[8],
            "wp_home_before": r[10], "wp_home_after": (r[10] + r[9] * (1 if r[2] == home else -1)) if r[10] is not None and r[9] is not None else None}
           for r in kp]
    from oddsmarkets.nfl.analytics import people
    box = espn_box(g, sm, people.espn_xwalk())
    if box and epd:                                              # team EPA lines from our EPA on ESPN's plays
        for side in ("home", "away"):
            t = g.get(side)
            sc = [r for r in rows if r[2] == t and r[8] is not None and not str(r[6]).startswith(("Punt", "Field Goal", "Penalty"))]
            if not sc or not (box.get(side) or {}).get("team"):
                continue
            e = np.array([r[8] for r in sc], float)
            db = np.array([bool(re_pass(str(r[6]))) for r in sc])
            box[side]["team"].update({"epa": an.rnd(e.sum(), 2), "epa_play": an.rnd(e.mean(), 3), "success": an.rnd((e > 0).mean(), 3),
                                      "pass_epa": an.rnd(e[db].mean(), 3) if db.any() else None,
                                      "rush_epa": an.rnd(e[~db].mean(), 3) if (~db).any() else None})
    return {"plays": {"cols": PLAY_COLS + EXTRA_PLAY_COLS, "rows": rows},
            "wp": {"cols": ["game_seconds_remaining", "wp_home_ours", "wp_home_nflfastr", "wp_home_espn", "play_index"], "rows": wps,
                   "source": "espn"},
            "drives": {"cols": DRIVE_COLS, "rows": drives}, "score": score, "fourth_downs": [], "key_plays": key,
            "box": box, "awards": None, "source": "espn", "epa_source": "ours on ESPN states" if epd else None}


def re_pass(typ: str) -> bool:
    """ESPN play types that are dropbacks (passes, sacks, interceptions)."""
    return any(k in typ for k in ("Pass", "Sack", "Interception"))
