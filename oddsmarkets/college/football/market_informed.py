"""
The market-informed game model for college football (promoted 22 Oct 2026; docs/research/college_edge.md round 4).

The base model (`game.py`: points / EPA / success-rate ratings, home field, rest) is stacked with three things the
betting market knows, all from information available before each game day:

    mk  = h [not neutral] + r_home - r_away       market ratings: weighted ridge on the closing spreads of games on
                                                  earlier days (half-life 120 days, ridge 0.1, prior = 0.9 x last
                                                  season's final market rating, regressed toward its conference)
    rd  = h' [not neutral] + d_home - d_away      residual ratings: the same ridge on (line - base model margin), i.e.
                                                  what the market keeps saying about a team beyond the base model
                                                  (no decay, ridge 0.25, carried fully into the next season)
    rp  = returning production (football/returning.py): last season's player value expected back (QB and the rest),
          and transfers in once they have played, home minus away
    margin = c + b . [nn, m0, mk, rd, early and non-FBS interactions, rp]     fitted to closing spreads (seasons
                                                                               2013 .. S-1)
    P(home) = Phi((margin + c0) / sd_phase)                                    probit on earlier seasons' walk-forward
                                                                               predictions

The fit is frozen per season by `scripts/campus_r4.py fit` in `oddsmarkets/college/fitted/informed_cfb.json`, so a
build only runs the current season's ridge paths and returning production. Sealed test 2021-2026 (5,059 games):
log-loss 0.4871 -> 0.4808, paired difference -0.0063 [-0.0092, -0.0034]; Brier and calibration better; 35 % of the
gap to the de-vigged moneyline closed. Totals are unchanged (the base model's).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.college import informed as INF

from . import data

logger = logging.getLogger(__name__)
FIT_PATH = Path(__file__).resolve().parents[1] / "fitted" / "informed_cfb.json"
_FIT: dict = {}


def fitted() -> dict | None:
    if "v" not in _FIT:
        try:
            f = json.loads(FIT_PATH.read_text(encoding="utf-8"))
            _FIT["v"] = f if f.get("version") == 1 and f.get("coefs") else None
        except (OSError, ValueError):
            _FIT["v"] = None
    return _FIT["v"]


def set_fitted(f: dict | None) -> None:
    """Override (tests) or forget the in-process fit."""
    if f is None:
        _FIT.pop("v", None)
    else:
        _FIT["v"] = f


def frame(P: pd.DataFrame, seasons: list[int] | None = None) -> pd.DataFrame:
    """The model frame from pipeline predictions (`backtest.pipeline(...)["preds"]`): one row per game with the base
    model (m0, p0), the closing line, conferences, groups (FBS / non-FBS), phase and scope flags."""
    P = P[P["day"].notna()].copy()
    if seasons is not None:
        P = P[P["season"].isin(seasons)]
    conf, member, opens, open_tot = {}, {}, {}, {}
    for s in sorted(P["season"].unique()):
        st = data.load_store(int(s))
        for t, v in (st.get("teams") or {}).items():
            conf[(int(s), t)] = v.get("conference")
            member[(int(s), t)] = bool(v.get("member"))
        for gid, g in (st.get("games") or {}).items():
            o = g.get("odds") or {}
            opens[str(gid)] = o.get("open_spread_home")
            open_tot[str(gid)] = o.get("open_total")
    F = pd.DataFrame({
        "season": P["season"].astype(int), "gid": P["gid"].astype(str),
        "dayn": [date.fromisoformat(str(d)[:10]).toordinal() for d in P["day"]],
        "home": P["home"].astype(str), "away": P["away"].astype(str), "neutral": P["neutral"].astype(bool),
        "final": P["final"].astype(bool), "hs": P["hs"], "as": P["as"],
        "spread": P["spread_home"].astype(float), "ctotal": P["close_total"].astype(float),
        "m0": P["margin"].astype(float), "p0": P["p_home"].astype(float), "sd0": P["sd"].astype(float),
        "total0": P["total"].astype(float), "week": P["week"], "stype": P["stype"].astype(str),
        "h_member": P["h_member"].astype(bool), "a_member": P["a_member"].astype(bool), "date": P["date"].astype(str),
    })
    F["p_ml"] = [data.devig(a, b) if np.isfinite(a) and np.isfinite(b) else np.nan
                 for a, b in zip(P["ml_home"].to_numpy(float), P["ml_away"].to_numpy(float))]
    F["p_ml"] = F["p_ml"].astype(float)
    F["open_spread"] = pd.to_numeric(F["gid"].map(opens), errors="coerce")
    F["open_total"] = pd.to_numeric(F["gid"].map(open_tot), errors="coerce")
    bad = F["season"].isin(list(data.UNRELIABLE_LINES))
    F.loc[bad, ["spread", "ctotal", "p_ml", "open_spread", "open_total"]] = np.nan
    F.loc[F["open_spread"].abs() > 75, "open_spread"] = np.nan
    F["conf_h"] = [str(conf.get((s, t))) for s, t in zip(F["season"], F["home"])]
    F["conf_a"] = [str(conf.get((s, t))) for s, t in zip(F["season"], F["away"])]
    F["group_h"] = np.where(F["h_member"], "fbs", "fcs")
    F["group_a"] = np.where(F["a_member"], "fbs", "fcs")
    F["fcs"] = ~(F["h_member"] & F["a_member"])
    F["y"] = F["hs"] - F["as"]
    F["scope"] = F["final"] & (F["h_member"] | F["a_member"]) & np.isfinite(F["m0"]) & (F["y"] != 0)
    F["fit_line"] = F["final"] & np.isfinite(F["spread"])
    wk = pd.to_numeric(F["week"], errors="coerce").fillna(99).to_numpy()
    F["phase"] = np.where(F["stype"].isin(["bowl", "cfp"]), "post", np.where(wk <= 3, "early", "mid"))
    return F.reset_index(drop=True)


def add_returning(R: pd.DataFrame, season: int, fit: dict) -> pd.DataFrame:
    from . import returning as RT
    R = R.copy()
    rp = fit.get("rp") or {}
    if rp.get("w") is None:
        R["rp_qb"] = 0.0
        R["rp_oth"] = 0.0
        return R
    built, tabs = RT.current(season, rp["w"], rp["a_k"])
    G = RT.game_features(R, built, tabs)
    R["rp_qb"] = G["rp_qb"].to_numpy(float)
    R["rp_oth"] = G["rp_oth"].to_numpy(float)
    return R


def predict(pipe: dict, season: int) -> dict[str, dict]:
    """{gid: {"p_home", "margin", "mk", "rd", "base_margin", "base_p", "early"}} for every game of `season` (finished
    and upcoming), or {} when no fit is committed for that season."""
    fit = fitted()
    if not fit or int(fit.get("season", -1)) != int(season):
        return {}
    P = pipe.get("preds")
    if P is None or not len(P):
        return {}
    R = frame(P, [int(season)])
    if not len(R):
        return {}
    if "rp_" in json.dumps(fit.get("cfg")):
        try:
            R = add_returning(R, int(season), fit)
        except Exception as exc:  # noqa: BLE001 - the base model still publishes
            logger.warning("cfb returning production failed (%s): informed model off", exc)
            return {}
    out = INF.predict_season(R, "cfb", fit)
    res = {}
    for gid, r, o in zip(R["gid"], R.itertuples(index=False), out.itertuples(index=False)):
        if not np.isfinite(o.mu):
            continue
        res[str(gid)] = {"p_home": float(o.p), "margin": float(o.mu), "mk": float(getattr(o, "mk", np.nan)),
                         "rd": float(getattr(o, "rd", np.nan)), "base_margin": float(r.m0), "base_p": float(r.p0),
                         "early": bool(o.early)}
    return res
