"""
Kalshi-props availability: the per-player table and the walk through a season (research; see props.py).

`player_table(league, season, kind)` walks the season with the production rotation state (models/informed.Rotation,
inputs from games of earlier days, as `informed.season_inputs`), and for every game with a Kalshi points event
returns one row per rotation player of each team: the rotation's streak and minutes, the Kalshi state at the
decision time (listed / quoted / ask), the player's earlier listing share, and whether he played (the outcome,
used only to estimate the cell rates on the development slice and to score).

`av_shift(league, season, rates, kind)` returns, per game, the availability terms with and without the Kalshi
overrides (production code: `Rotation.expected(..., p_override=...)`).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import pandas as pd

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import informed as INF
from oddsmarkets.basketball.research import props as PR

MIN_MPG = 12.0                 # rotation players the table keeps (expected minutes per game before the game)


def _played(g: dict, t: str) -> set[str]:
    b = (g.get("box") or {}).get(t) or {}
    return {str(r[0]) for r in b.get("players") or [] if float(r[2] or 0) > 0}


def _walk(league: str, season: int):
    """Yields (game_id, game, day, rotation) for every counted game in date order; the rotation holds games of
    earlier days only."""
    st = G.load_store(league, season) or {}
    games = st.get("games") or {}
    vals = INF.values_for(league, season)
    rot = INF.rotation_for(league, season, st, vals)
    rows = INF._rows(st, league)
    gl = sorted(((G.local_day(g), gid) for gid, g in games.items()
                 if g.get("stype") in G.COUNTED and g.get("status") == "post" and G.local_day(g)), key=lambda x: (x[0], x[1]))
    pi = 0
    for D, gid in gl:
        cut = D - timedelta(days=1)
        while pi < len(rows) and rows[pi]["day"] <= cut:
            rot.update(games[rows[pi]["id"]], rows[pi]["day"])
            pi += 1
        yield gid, games[gid], D, rot, st


def player_table(league: str, season: int, kind: str = "tip-1h") -> pd.DataFrame:
    st0 = G.load_store(league, season) or {}
    lst = PR.game_listings(league, season, st0)
    hist: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])     # (team, pid) -> [played, listed]
    out = []
    for gid, g, D, rot, st in _walk(league, season):
        L = lst.get(gid)
        if not L:
            continue
        T = PR.decision_ts(g, kind)
        tip = PR.tip_ts(g)
        for side in ("home", "away"):
            t = str(g[side])
            state = PR.state_at(L.get(t) or [], T)
            n_listed = sum(1 for s in state.values() if s["listed"])
            played = _played(g, t)
            listed_by_tip = {pid for pid, s in PR.state_at(L.get(t) or [], tip).items() if s["listed"]}
            for pid, s in (rot.st.get(t) or {}).items():
                if s["mpg"] < MIN_MPG:
                    continue
                k = state.get(pid) or {}
                h = hist[(t, pid)]
                out.append({"game": gid, "day": D, "team": t, "side": side, "pid": pid, "mpg": s["mpg"],
                            "streak": s["streak"], "listed": bool(k.get("listed")), "quoted": bool(k.get("quoted")),
                            "ask": k.get("ask"), "bid": k.get("bid"), "team_listed": n_listed,
                            "prev_played": h[0], "prev_listed": h[1], "played": pid in played})
            for pid in played:
                hist[(t, pid)][0] += 1
                if pid in listed_by_tip:
                    hist[(t, pid)][1] += 1
    return pd.DataFrame(out)


def overrides(state: dict[str, dict], rot_team: dict[str, dict], hist: dict[str, list[int]], rates: dict) -> dict[str, float]:
    """P(plays) overrides for one team at T: listed players -> rates["listed_bid"] (a yes bid at T) or
    rates["listed_nobid"]; when the team is active (at least
    rates["active_min"] of its players listed), an unlisted regular (listed in at least rates["reg_share"] of his
    earlier Kalshi games played, at least rates["reg_min"] such games) -> min(streak rate, rates["unlisted_regular"])."""
    n_listed = sum(1 for s in state.values() if s["listed"])
    out: dict[str, float] = {}
    for pid in rot_team:
        s = state.get(pid)
        if s and s["listed"]:
            out[pid] = rates["listed_bid"] if (s.get("bid") or 0) > 0 else rates["listed_nobid"]
            continue
        if n_listed >= rates["active_min"]:
            h = hist.get(pid) or [0, 0]
            if h[0] >= rates["reg_min"] and h[1] >= rates["reg_share"] * h[0]:
                out[pid] = -1.0                                  # resolved by the caller: min(streak rate, rate)
    return out


def av_shift(league: str, season: int, rates: dict, kind: str = "tip-1h") -> pd.DataFrame:
    """Per game with a Kalshi event: the availability terms (av_h, av_a; points per 100 before the pace factor)
    without and with the overrides, and the number of players overridden."""
    st0 = G.load_store(league, season) or {}
    lst = PR.game_listings(league, season, st0)
    hist: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    out = []
    for gid, g, D, rot, st in _walk(league, season):
        L = lst.get(gid)
        if not L:
            continue
        T = PR.decision_ts(g, kind)
        tip = PR.tip_ts(g)
        rec = {"event_id": gid, "day": D}
        for side in ("home", "away"):
            t = str(g[side])
            state = PR.state_at(L.get(t) or [], T)
            team = rot.st.get(t) or {}
            ov = overrides(state, team, {p: hist[(t, p)] for p in team}, rates)
            for p, v in list(ov.items()):
                if v < 0:
                    base = rot.av[min(team[p]["streak"], len(rot.av) - 1)]
                    ov[p] = min(base, rates["unlisted_regular"])
            a0 = INF._team_av(rot, t, D)
            a1 = INF._team_av(rot, t, D, p_over=ov)
            k = "h" if side == "home" else "a"
            rec[f"av0_{k}"], rec[f"av1_{k}"] = a0[0], a1[0]
            rec[f"tav0_{k}"], rec[f"tav1_{k}"] = a0[1], a1[1]
            rec[f"n_over_{k}"] = len(ov)
            played = _played(g, t)
            listed_by_tip = {p for p, s in PR.state_at(L.get(t) or [], tip).items() if s["listed"]}
            for p in played:
                hist[(t, p)][0] += 1
                if p in listed_by_tip:
                    hist[(t, p)][1] += 1
        out.append(rec)
    return pd.DataFrame(out)


def dev_rates(t: pd.DataFrame, before) -> dict:
    """The rule's cell rates, from the player table's development slice (games before `before`)."""
    d = t[t.day < before]
    listed = d[d.listed]
    bid = listed.bid.fillna(0) > 0
    act = d.team_listed >= 2
    reg = (d.prev_played >= 2) & (d.prev_listed >= 0.5 * d.prev_played)
    unl = d[act & ~d.listed & reg]
    return {"listed_bid": float(listed[bid].played.mean()), "listed_nobid": float(listed[~bid].played.mean()),
            "unlisted_regular": float(unl.played.mean()), "active_min": 2, "reg_min": 2, "reg_share": 0.5,
            "n": {"listed_bid": int(bid.sum()), "listed_nobid": int((~bid).sum()), "unlisted_regular": len(unl)}}


def apply_shift(p: pd.DataFrame, sh: pd.DataFrame, season: int) -> pd.DataFrame:
    """The research table's informed probability (C + probit, the season's walk-forward fold) with x_dSl moved by
    the availability shift: rows of `sh` only. Adds p_base, p_kalshi, dx."""
    b = float(p.attrs["coef"]["c"][season]["x_dSl"])
    c0, sd = p.attrs["probit"]["C"][season]
    x = p[p.season == season].merge(sh, on="event_id", how="inner", suffixes=("", "_sh"))
    k = x["pace_g"] / 100.0
    x["dx"] = ((x.av1_h - x.av0_h) - (x.av1_a - x.av0_a)) * k
    from scipy.stats import norm
    x["p_base"] = norm.cdf((x["c_mu"] + c0) / sd)
    x["p_kalshi"] = norm.cdf((x["c_mu"] + b * x["dx"] + c0) / sd)
    x["x_prod"] = (x.av0_h - x.av0_a) * k
    return x


def kalshi_game_mid(x: pd.DataFrame, league: str, hours_before: float = 1.0) -> pd.Series:
    """Kalshi's game-winner mid for the home side at tip-off minus `hours_before` (research/kalshi.py), by event_id."""
    from oddsmarkets.basketball.research import kalshi as K
    abbr = {}
    for s in x.season.unique():
        st = G.load_store(league, int(s)) or {}
        abbr[int(s)] = {k: (v or {}).get("abbr") for k, v in (st.get("teams") or {}).items()}
    k = K.load(league, x, abbr, hours_before=hours_before)
    if k.empty:
        return pd.Series(dtype=float)
    k = k.dropna(subset=["dec_ask_h", "dec_bid_h"])
    return pd.Series(((k.dec_ask_h + k.dec_bid_h) / 2).to_numpy(), index=k.event_id.to_numpy())


def score(x: pd.DataFrame, cols: list[str], base: str = "p_base") -> list[dict]:
    """Log-loss / Brier / calibration of `cols` against `base` on x's rows (all columns present), paired
    day-clustered bootstrap (the research convention, evaluate.paired_ll_diff)."""
    from oddsmarkets.basketball.research import evaluate as V
    from oddsmarkets.basketball.research.improve import calib
    import numpy as np
    z = x.dropna(subset=list(set(cols + [base])))
    y = z.y.to_numpy(float)
    g = z.day.astype(str).to_numpy()
    out = []
    for c in cols:
        v = z[c].to_numpy(float)
        d = V.paired_ll_diff(v, z[base].to_numpy(float), y, g)
        bd = V.boot_ci((v - y) ** 2 - (z[base].to_numpy(float) - y) ** 2, g)
        out.append({"forecast": c, "n": int(len(z)), "logloss": V.logloss(v, y), "brier": V.brier(v, y),
                    "d_ll": d[0], "d_lo": d[1], "d_hi": d[2], "d_brier": bd[0], "db_lo": bd[1], "db_hi": bd[2],
                    **{k: round(float(val), 4) for k, val in calib(v, y).items()}})
    return out
