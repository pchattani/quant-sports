"""
Late-season stakes from the season simulation at the decision (model-improvement program, Oct 2026).

For every regular-season week from FROM_WEEK on, the season simulation is run as of the week's first game date with
everything fitted before it (team strength chained from three seasons earlier with the preseason prior and fitted on
the season's games before the week; game coefficients from walk-forward rows dated before it; market ratings only from
games already played). For each team whose next game is in that week, the simulation's conditional odds give the
game's leverage: d_<target> = P(target | win) - P(target | loss) for playoffs, division, bye (No. 1 seed) and the
title, and the current p_playoffs.

Features (per side; the margin model uses home minus away):
    clinched   nothing at stake (every d < STAKE_EPS) and p_playoffs > 0.99 (a team that may rest its starters)
    elim       nothing at stake and p_playoffs < 0.01 (a team playing out the season)
    stake      d_playoffs + d_bye (how much the game matters)
Known at the open of the week (they use only games played before it).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import season_sim as SS
from oddsmarkets.nfl.models import team_strength as TS

logger = logging.getLogger(__name__)

FROM_WEEK = 12
STAKE_EPS = 0.005


def season_stakes(season: int, wf: pd.DataFrame, n: int = 4000, seed: int = 0, from_week: int = FROM_WEEK) -> pd.DataFrame:
    """Rows (game_id, team, week, p_playoffs, d_playoffs, d_div, d_bye, d_sb) for the season's weeks >= from_week."""
    p_ts = TS.params()
    last, book = None, {}
    for s in range(season - 3, season):
        u = D.unit_rows(s)
        prior = TS.preseason_prior(last, s, p_ts, book, TS.continuity(s))
        end = TS.fit(u, s, None, prior, p_ts)
        TS.update_qb_book(book, end)
        last = end
    prior = TS.preseason_prior(last, season, p_ts, book, TS.continuity(season))
    G = D.games_frame([season - 1, season])
    gs = G[(G["season"] == season) & (G["gtype"] == "REG")]
    u = D.unit_rows(season)
    teams = sorted(set(gs["home"]) | set(gs["away"]))
    rows = []
    for w in sorted(gs["week"].unique()):
        if w < from_week:
            continue
        wk = gs[gs["week"] == w]
        thr = wk["date"].min()
        if not wk["played"].any() and not (gs["played"] & (gs["week"] < w)).any():
            continue
        r = TS.fit(u, season, thr, prior, p_ts, teams=teams)
        rd = r.as_dict()
        rd["qb_prior"] = prior["qbs"]
        hist = wf[pd.to_datetime(wf["date"]) < thr]
        prm = GM.fit_from_rows(hist)
        try:
            res = SS.simulate(season, n=n, seed=seed, state={"games": G, "through": thr, "ratings": rd, "params": prm})
        except Exception as exc:  # noqa: BLE001
            logger.warning("stakes %s w%s: %s", season, w, exc)
            continue
        for t, v in res["teams"].items():
            nx = v.get("next") or {}
            if not nx or int(nx.get("week", -1)) != int(w):
                continue
            iw, il = nx.get("if_win") or {}, nx.get("if_loss") or {}

            def d(k):
                a, b = iw.get(k), il.get(k)
                return float(a - b) if a is not None and b is not None else np.nan
            rows.append({"game_id": nx["game_id"], "team": t, "season": season, "week": int(w),
                         "p_playoffs": v["p_playoffs"], "p_bye": v["p_bye"], "d_playoffs": d("p_playoffs"),
                         "d_div": d("p_div"), "d_bye": d("p_bye"), "d_sb": d("p_sb")})
        logger.info("stakes %s week %s done", season, w)
    return pd.DataFrame(rows)


def stakes(seasons, wf: pd.DataFrame, n: int = 4000, refresh: bool = False) -> pd.DataFrame:
    path = D.cache_root() / "edge" / "stakes.parquet"
    cur = pd.read_parquet(path) if path.exists() and not refresh else pd.DataFrame()
    have = set(cur["season"].unique()) if len(cur) else set()
    parts = [cur] if len(cur) else []
    for s in seasons:
        if s in have:
            continue
        parts.append(season_stakes(s, wf, n=n))
        out = pd.concat(parts, ignore_index=True)
        out.to_parquet(path, index=False)
    return pd.concat(parts, ignore_index=True) if parts else cur


def attach_stakes(R: pd.DataFrame, ST: pd.DataFrame) -> pd.DataFrame:
    """f_clinch, f_elim, f_stake (home - away) on rows with game_id, home, away; 0 where no stakes row exists."""
    S = ST.copy()
    nost = (S[["d_playoffs", "d_div", "d_bye"]].abs().max(axis=1) < STAKE_EPS)
    S["clinched"] = (nost & (S["p_playoffs"] > 0.99)).astype(float)
    S["elim"] = (nost & (S["p_playoffs"] < 0.01)).astype(float)
    S["stake"] = S["d_playoffs"].fillna(0) + S["d_bye"].fillna(0)
    m = S.drop_duplicates(["game_id", "team"]).set_index(["game_id", "team"])
    out = R.copy()
    for side, col in (("h", "home"), ("a", "away")):
        sub = m.reindex(list(zip(out["game_id"], out[col])))
        for c in ("clinched", "elim", "stake"):
            out[f"{c}_{side}"] = sub[c].fillna(0.0).to_numpy()
    out["f_clinch"] = out["clinched_h"] - out["clinched_a"]
    out["f_elim"] = out["elim_h"] - out["elim_a"]
    out["f_stake"] = out["stake_h"] - out["stake_a"]
    out["t_nostake"] = out["clinched_h"] + out["clinched_a"] + out["elim_h"] + out["elim_a"]
    return out
