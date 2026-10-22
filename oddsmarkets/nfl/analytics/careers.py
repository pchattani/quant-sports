"""
Career files (players/<pid>.json, 1999 onward) and players_index.json.

Each season's catalogue is reduced to compact career rows (`reduce_cat`, a few counting stats and rates per position
group, with an era-adjusted "plus" for rates: 100 + 10 z within the season's qualified pool). The current season adds
a "current" block per player (`current_blocks`): the game log, charts (QB depth x location grid, receivers' target
depth profile, RB rush yards over expected by game), the NGS season row, FTN-derived rates and similar players.
A player's file is rewritten only when its content changed.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import people
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num

logger = logging.getLogger(__name__)
SEASON_KEYS = {
    "QB": ["att", "pass_yds", "pass_td", "ints", "epa_db", "epa_total", "cpoe", "anya", "success", "sack_rate", "composite", "value"],
    "RB": ["carries", "rush_yds", "rush_td", "rush_epa", "ryoe", "ypc", "targets", "rec", "rec_yds", "value"],
    "WR": ["targets", "rec", "rec_yds", "rec_td", "rec_epa", "rec_epa_tgt", "target_share", "adot", "yacoe", "value"],
    "TE": ["targets", "rec", "rec_yds", "rec_td", "rec_epa", "rec_epa_tgt", "target_share", "adot", "yacoe", "value"],
    "K": ["fga", "fgm", "fg_pct", "fg_oe", "pts_oe", "fg_50", "xp_pct"],
    "P": ["punts", "gross", "net", "inside20", "epa_punt", "punt_epa", "net_oe"],
    "DEF": ["tackles", "sacks", "qb_hits", "tfl", "ints", "pd", "ff", "def_value"],
}
PLUS_KEYS = {"QB": ["epa_db", "anya", "cpoe", "success", "composite"], "RB": ["rush_epa", "ryoe", "ypc"],
             "WR": ["rec_epa_tgt", "target_share", "yacoe"], "TE": ["rec_epa_tgt", "target_share", "yacoe"], "K": ["fg_oe", "fg_pct"],
             "P": ["net", "epa_punt"], "DEF": ["def_value"]}
LOWER = {"sack_rate"}
MIN_FILE = {"QB": ("att", 20), "RB": ("carries", 10), "WR": ("targets", 8), "TE": ("targets", 6), "K": ("fga", 3), "P": ("punts", 10),
            "DEF": ("tackles", 10)}


def real_pid(pid: Any) -> bool:
    """False for the placeholder ids play-by-play carries where no player is recorded ("0", "00-0000000", blanks,
    "nan"): such an id pools many unknown players, so it gets no career file and no players_index entry."""
    s = an.sid(pid)
    return bool(s) and s.strip().lower() not in ("na", "null", "none") and re.fullmatch(r"[0\-\s]*", s) is None


def reduce_cat(cat: dict | None, season: int) -> dict[str, dict] | None:
    """{pid: {season, team, group, pos, name, games, qualified, values: {...}, plus: {...}}} for career files and history."""
    if not cat or not cat.get("players"):
        return None
    P = cat["players"]
    plus: dict[str, dict] = {}
    for grp, keys in PLUS_KEYS.items():
        mem = [r for r in P.values() if r.get("group") == grp and r.get("qualified")]
        for k in keys:
            v = [an.fnum((r.get("values") or {}).get(k)) for r in mem]
            v = [x for x in v if x is not None]
            if len(v) < 5:
                continue
            mu, sd = float(np.mean(v)), float(np.std(v)) or 1.0
            plus.setdefault(grp, {})[k] = (mu, sd)
    out = {}
    for pid, r in P.items():
        grp = r.get("group")
        keys = SEASON_KEYS.get(grp) or []
        vals = {k: (r.get("values") or {}).get(k) for k in keys}
        pl = {}
        if r.get("qualified"):
            for k, (mu, sd) in (plus.get(grp) or {}).items():
                x = an.fnum(vals.get(k))
                if x is not None:
                    pl[k] = int(round(100 + 10 * ((mu - x) if k in LOWER else (x - mu)) / sd))
        out[pid] = {"season": int(season), "team": r.get("team"), "group": grp, "pos": r.get("pos"), "name": r.get("name"),
                    "games": r.get("games"), "qualified": r.get("qualified"), "age": r.get("age"), "values": vals, "plus": pl}
    return out


def _gamelog(P: pd.DataFrame, ctx: SeasonContext) -> dict[str, list]:
    """Per player per game: [game_id, week, team, opp, role stats...] with a column list per player kind. Counting
    rules match players.py (and so the season totals): two-point tries out, spikes are attempts, official yardage
    columns with laterals credited to the lateral player, every defensive credit on every play."""
    from oddsmarkets.nfl.analytics.players import def_credits, lateral_yards, pass_yards, rec_yards, rush_yards, scrimmage
    S = scrimmage(P, two_point=False)
    if not len(S):
        return {}
    epa = num(S, "epa")
    out: dict[str, dict] = {}

    def add(pid, gid, key, val):
        d = out.setdefault(pid, {}).setdefault(gid, {})
        d[key] = d.get(key, 0.0) + val
    S = S.assign(_epa=epa.fillna(0), _cmp=flag(S, "complete_pass").fillna(0), _ptd=flag(S, "pass_touchdown").fillna(0),
                 _int=flag(S, "interception").fillna(0), _sack=flag(S, "sack").fillna(0), _rtd=flag(S, "rush_touchdown").fillna(0))
    from oddsmarkets.nfl.analytics.players import _pid, td_credit
    pid = _pid(S, "passer_id", "passer_player_id") if ("passer_id" in S or "passer_player_id" in S) else None
    if pid is not None:
        D = S[(flag(S, "qb_dropback").fillna(0) == 1) & pid.notna()]
        D = D.assign(_p=pid[D.index], _att=((flag(D, "sack").fillna(0) == 0) & (flag(D, "qb_scramble").fillna(0) == 0)).astype(float))
        g = D.groupby(["_p", "game_id"]).agg(att=("_att", "sum"), cmp=("_cmp", "sum"), td=("_ptd", "sum"),
                                             ints=("_int", "sum"), sacks=("_sack", "sum"), epa=("_epa", "sum"), db=("_epa", "size"))
        yd = pass_yards(D).where(D["_att"] == 1, 0).groupby([D["_p"], D["game_id"]]).sum()
        for (p, gid), r in g.iterrows():
            for k in ("att", "cmp", "td", "ints", "sacks", "epa", "db"):
                add(str(p), gid, "p_" + k, float(r[k]))
            add(str(p), gid, "p_yds", float(yd.get((p, gid), 0)))
        # spikes are pass attempts (incomplete) in the official count
        K = P[(P["play_type"] == "qb_spike")] if "play_type" in P else P.iloc[0:0]
        if len(K):
            K = K.assign(_k=_pid(K, "passer_id", "passer_player_id"))
            for (p, gid), n in K[["_k", "game_id"]].dropna().groupby(["_k", "game_id"]).size().items():
                if str(p) in out and gid in out[str(p)]:
                    add(str(p), gid, "p_att", float(n))
    rid = _pid(S, "rusher_player_id", "rusher_id") if ("rusher_id" in S or "rusher_player_id" in S) else None
    if rid is not None:
        R = S[(S["play_type"] == "run") & (flag(S, "qb_scramble").fillna(0) == 0) & rid.notna()]
        R = R.assign(_p=rid[R.index], _y=rush_yards(R), _x=num(R, "xrush_ours"))
        R = R.assign(_rtd=td_credit(R.assign(pid=R["_p"]), "rush_touchdown"))
        g = R.groupby(["_p", "game_id"]).agg(car=("_y", "size"), yds=("_y", "sum"), td=("_rtd", "sum"), epa=("_epa", "sum"),
                                             xr=("_x", "sum"), xn=("_x", "count"))
        for (p, gid), r in g.iterrows():
            for k in ("car", "yds", "td", "epa"):
                add(str(p), gid, "r_" + k, float(r[k]))
            if r["xn"] >= 0.5 * r["car"]:
                add(str(p), gid, "r_ryoe", float(r["yds"] - r["xr"]))
        for (p, gid), y in lateral_yards(S, "rushing").items():
            add(p, gid, "r_yds", float(y))
    xid = S["receiver_id"] if "receiver_id" in S else S.get("receiver_player_id")
    if xid is not None:
        X = S[(S["play_type"] == "pass") & xid.notna()]
        c = flag(X, "complete_pass").fillna(0)
        X = X.assign(_p=xid[X.index], _c=c, _y=rec_yards(X), _air=num(X, "air_yards").fillna(0))
        X = X.assign(_ptd=td_credit(X.assign(pid=X["_p"]), "pass_touchdown"))
        g = X.groupby(["_p", "game_id"]).agg(tgt=("_c", "size"), rec=("_c", "sum"), yds=("_y", "sum"), td=("_ptd", "sum"),
                                             epa=("_epa", "sum"), air=("_air", "sum"))
        for (p, gid), r in g.iterrows():
            for k in ("tgt", "rec", "yds", "td", "epa", "air"):
                add(str(p), gid, "x_" + k, float(r[k]))
        for (p, gid), y in lateral_yards(S, "receiving").items():
            add(p, gid, "x_yds", float(y))
        for (p, gid), y in lateral_yards(S, "receiving", tds=True).items():
            add(p, gid, "x_td", float(y))
    short = {"sacks": "d_sacks", "qb_hits": "d_hits", "tfl": "d_tfl", "ints": "d_int", "pd": "d_pd", "ff": "d_ff", "tackles": "d_tkl"}
    C = def_credits(P) if "play_type" in P and P["play_type"].isin(["pass", "run"]).any() else def_credits(P.iloc[0:0])
    if len(C):
        for (p, gid, stat), w in C.groupby(["pid", "game_id", "stat"])["w"].sum().items():
            add(str(p), gid, short[stat], float(w))
    if "play_type" in P and "kicker_player_id" in P:
        K = P[P["play_type"].isin(["field_goal", "extra_point"]) & P["kicker_player_id"].notna()]
        for r in K[["kicker_player_id", "game_id", "play_type", "field_goal_result", "extra_point_result", "kick_distance"]
                   if "extra_point_result" in K else ["kicker_player_id", "game_id", "play_type", "field_goal_result", "kick_distance"]].to_dict("records"):
            p, gid = str(r["kicker_player_id"]), r["game_id"]
            if r["play_type"] == "field_goal":
                add(p, gid, "k_fga", 1.0)
                add(p, gid, "k_fgm", 1.0 if str(r.get("field_goal_result")) == "made" else 0.0)
            else:
                add(p, gid, "k_xpa", 1.0)
                add(p, gid, "k_xpm", 1.0 if str(r.get("extra_point_result")) == "good" else 0.0)
    if "play_type" in P and "punter_player_id" in P:
        U = P[(P["play_type"] == "punt") & P["punter_player_id"].notna()]
        net = num(U, "kick_distance") - num(U, "return_yards").fillna(0) - 20 * flag(U, "touchback").fillna(0)
        for p, gid, x in zip(U["punter_player_id"].astype(str), U["game_id"], net):
            add(p, gid, "u_punts", 1.0)
            add(p, gid, "u_net", float(x) if x == x else 0.0)
    meta = {gid: (g.get("week"), g.get("home"), g.get("away")) for gid, g in ctx.games.items()}
    team_of: dict[tuple, str] = {}
    for col in ("passer_id", "passer_player_id", "rusher_id", "rusher_player_id", "receiver_id", "lateral_receiver_player_id",
                "lateral_rusher_player_id", "kicker_player_id", "punter_player_id"):
        if col in P:
            d = P[[col, "game_id", "posteam"]].dropna().drop_duplicates([col, "game_id"])
            team_of.update({(str(a), b): c for a, b, c in d.itertuples(index=False)})
    if len(C):
        d = C[["pid", "game_id", "team"]].dropna().drop_duplicates(["pid", "game_id"])
        team_of.update({(str(a), b): c for a, b, c in d.itertuples(index=False)})
    for col in ("passer_id", "rusher_id", "receiver_id"):
        if col in S:
            d = S[[col, "game_id", "posteam"]].dropna().drop_duplicates([col, "game_id"])
            team_of.update({(str(a), b): c for a, b, c in d.itertuples(index=False)})
    res: dict[str, list] = {}
    for p, games in out.items():
        rows = []
        for gid, st in sorted(games.items(), key=lambda kv: (meta.get(kv[0], (0,))[0] or 0, kv[0])):
            wk, h, a = meta.get(gid, (None, None, None))
            t = team_of.get((p, gid))
            rows.append({"game_id": gid, "week": wk, "team": t, "opp": (a if t == h else h) if t else None,
                         **{k: (round(v, 2) if k.endswith(("epa", "ryoe", "sacks", "net")) else int(round(v))) for k, v in st.items()}})
        res[p] = rows
    return res


def _qb_grid(D: pd.DataFrame) -> list:
    out = []
    att = D[(flag(D, "sack").fillna(0) == 0) & (flag(D, "qb_scramble").fillna(0) == 0) & D.get("pass_length", pd.Series(index=D.index)).notna()]
    for (ln, loc), d in att.groupby([att["pass_length"], att["pass_location"]]) if len(att) and "pass_location" in att else []:
        out.append({"depth": ln, "loc": loc, "att": int(len(d)), "cmp_pct": an.rnd(flag(d, "complete_pass").fillna(0).mean(), 3),
                    "epa": an.rnd(num(d, "epa").mean(), 3), "td": int(flag(d, "pass_touchdown").fillna(0).sum()),
                    "int": int(flag(d, "interception").fillna(0).sum())})
    return out


def _depth_profile(X: pd.DataFrame) -> list:
    if not len(X):
        return []
    air = num(X, "air_yards")
    bins = pd.cut(air, [-100, 0, 10, 20, 100], right=False, labels=["behind", "0-9", "10-19", "20+"])
    out = []
    for b, d in X.groupby(bins, observed=True):
        out.append({"depth": str(b), "tgt": int(len(d)), "catch": an.rnd(flag(d, "complete_pass").fillna(0).mean(), 3),
                    "epa": an.rnd(num(d, "epa").mean(), 3), "yds": an.inum(num(d, "yards_gained").where(flag(d, "complete_pass") == 1).sum())})
    return out


NGS_KEEP = {"passing": ["avg_time_to_throw", "avg_completed_air_yards", "avg_intended_air_yards", "avg_air_yards_differential",
                        "aggressiveness", "max_completed_air_distance", "avg_air_yards_to_sticks", "completion_percentage_above_expectation",
                        "expected_completion_percentage", "passer_rating"],
            "rushing": ["efficiency", "percent_attempts_gte_eight_defenders", "avg_time_to_los", "expected_rush_yards",
                        "rush_yards_over_expected", "rush_yards_over_expected_per_att", "rush_pct_over_expected"],
            "receiving": ["avg_cushion", "avg_separation", "avg_intended_air_yards", "percent_share_of_intended_air_yards",
                          "catch_percentage", "avg_yac", "avg_expected_yac", "avg_yac_above_expectation"]}


def current_blocks(ctx: SeasonContext, cat: dict | None) -> dict[str, dict]:
    """{pid: {"season","log","charts","ngs","ftn","similar","projection"}} for the full season's players."""
    from oddsmarkets.nfl.analytics.players import reg_plays, ngs_map
    if not cat or not cat.get("players"):
        return {}
    P = reg_plays(ctx)
    if not len(P):
        return {}
    logs = _gamelog(P, ctx)
    S = P[P["play_type"].isin(["pass", "run"])]
    ngs = {k: ngs_map(ctx, k) for k in NGS_KEEP}
    pid_p = S["passer_id"] if "passer_id" in S else S.get("passer_player_id")
    pid_x = S["receiver_id"] if "receiver_id" in S else S.get("receiver_player_id")
    by_p = {str(k): v for k, v in S[(flag(S, "qb_dropback").fillna(0) == 1)].groupby(pid_p)} if pid_p is not None else {}
    by_x = {str(k): v for k, v in S[S["play_type"] == "pass"].groupby(pid_x)} if pid_x is not None else {}
    similar = similar_players(cat)
    from oddsmarkets.nfl.analytics.players import league_fg_curve
    FG = P[(P["play_type"] == "field_goal") & P["kicker_player_id"].notna()] if "kicker_player_id" in P else P.iloc[0:0]
    fg_curve = num(FG, "fg_prob_ours") if "fg_prob_ours" in FG and FG["fg_prob_ours"].notna().any() else league_fg_curve(FG)
    FG = FG.assign(_xp=fg_curve)
    by_k = {str(k): v for k, v in FG.groupby("kicker_player_id")} if len(FG) else {}
    PU = P[(P["play_type"] == "punt") & P["punter_player_id"].notna()] if "punter_player_id" in P else P.iloc[0:0]
    by_u = {str(k): v for k, v in PU.groupby("punter_player_id")} if len(PU) else {}
    out = {}
    for pid, r in cat["players"].items():
        grp = r.get("group")
        charts: dict[str, Any] = {}
        ftn: dict[str, Any] = {}
        if grp == "QB" and pid in by_p:
            D = by_p[pid]
            charts["qb_grid"] = _qb_grid(D)
            if "is_play_action" in D and D["is_play_action"].notna().any():
                ftn = {"play_action": an.rnd(flag(D, "is_play_action").mean(), 3), "screen": an.rnd(flag(D, "is_screen_pass").mean(), 3),
                       "out_of_pocket": an.rnd(flag(D, "is_qb_out_of_pocket").mean(), 3),
                       "interception_worthy": int(flag(D, "is_interception_worthy").fillna(0).sum()),
                       "throw_aways": int(flag(D, "is_throw_away").fillna(0).sum()), "blitzed": an.rnd((num(D, "n_blitzers") > 0).mean(), 3)}
        if grp in ("WR", "TE", "RB") and pid in by_x:
            X = by_x[pid]
            charts["depth_profile"] = _depth_profile(X)
            if "is_catchable_ball" in X and X["is_catchable_ball"].notna().any():
                ftn = {"catchable": int(flag(X, "is_catchable_ball").fillna(0).sum()), "drops": int(flag(X, "is_drop").fillna(0).sum()),
                       "contested": int(flag(X, "is_contested_ball").fillna(0).sum()),
                       "created": int(flag(X, "is_created_reception").fillna(0).sum()), "screens": int(flag(X, "is_screen_pass").fillna(0).sum())}
        if grp == "K" and pid in by_k:
            charts["fg"] = _fg_chart(by_k[pid], fg_curve)
        if grp == "P" and pid in by_u:
            charts["punts"] = _punt_chart(by_u[pid])
        lg = logs.get(pid) or []
        if grp == "DEF":
            charts["splash_by_game"] = [[x["week"], x.get("d_tkl", 0), x.get("d_sacks", 0), x.get("d_hits", 0), x.get("d_int", 0) +
                                         x.get("d_pd", 0)] for x in lg]
            charts["splash_cols"] = ["week", "tackles", "sacks", "qb_hits", "int_pd"]
        if grp == "RB":
            charts["ryoe_by_game"] = [[x["week"], x.get("r_ryoe")] for x in lg if "r_car" in x]
        ng = None
        kind = {"QB": "passing", "RB": "rushing", "WR": "receiving", "TE": "receiving"}.get(grp)
        if kind and ngs.get(kind, {}).get(pid):
            row = ngs[kind][pid]
            ng = {k: an.rnd(row.get(k), 3) for k in NGS_KEEP[kind] if row.get(k) is not None}
        out[pid] = {"season": ctx.season, "group": grp, "values": r.get("values"), "pct": r.get("pct"), "pct_pos": r.get("pct_pos"),
                    "log": lg, "charts": charts, "ngs": ng, "ftn": ftn or None, "similar": similar.get(pid) or [], "projection": None}
    return out


FG_BANDS = ((0, 30), (30, 40), (40, 50), (50, 55), (55, 80))
PUNT_ZONES = ((0, 40, "opp 40 or closer"), (40, 60, "midfield"), (60, 80, "own 20-40"), (80, 100, "inside own 20"))


def _fg_chart(F: pd.DataFrame, _curve=None) -> list:
    """Field goals by distance band: [{lo, hi, att, made, exp}] (exp from the make-probability model)."""
    d = num(F, "kick_distance")
    made = (F["field_goal_result"].astype(str) == "made").astype(float)
    xp = num(F, "_xp")
    out = []
    for lo, hi in FG_BANDS:
        m = (d >= lo) & (d < hi)
        if m.any():
            out.append({"lo": lo, "hi": hi, "att": int(m.sum()), "made": int(made[m].sum()), "exp": an.rnd(xp[m].sum(), 2)})
    return out


def _punt_chart(U: pd.DataFrame) -> list:
    """Punts by launch spot (yards to the opponent's goal): [{zone, lo, hi, punts, gross, net, inside20}]."""
    yl = num(U, "yardline_100")
    gross = num(U, "kick_distance")
    ret = num(U, "return_yards").fillna(0)
    tb = flag(U, "touchback").fillna(0)
    net = gross - ret - 20 * tb
    end = (yl - gross + ret).where(tb == 0, 20)
    out = []
    for lo, hi, name in PUNT_ZONES:
        m = (yl > lo) & (yl <= hi)
        if m.any():
            out.append({"zone": name, "lo": lo, "hi": hi, "punts": int(m.sum()), "gross": an.rnd(gross[m].mean(), 1),
                        "net": an.rnd(net[m].mean(), 1), "inside20": an.rnd(((end[m] <= 20) & (tb[m] == 0)).mean(), 3)})
    return out


def similar_players(cat: dict, n: int = 5) -> dict[str, list]:
    """Nearest neighbours within the position group on the percentile vector (qualified players)."""
    out: dict[str, list] = {}
    for grp, keys in (cat.get("groups") or {}).items():
        mem = [(p, r) for p, r in cat["players"].items() if r.get("group") == grp and r.get("qualified")]
        if len(mem) < 3:
            continue
        keys = [k for k in keys if sum(1 for _, r in mem if k in (r.get("pct") or {})) >= 0.7 * len(mem)]
        if not keys:
            continue
        M = np.array([[((r.get("pct") or {}).get(k, 50)) for k in keys] for _, r in mem], dtype=float)
        for i, (p, r) in enumerate(mem):
            d = np.sqrt(((M - M[i]) ** 2).mean(axis=1))
            d[i] = np.inf
            idx = np.argsort(d)[:n]
            out[p] = [[mem[j][0], mem[j][1].get("name"), mem[j][1].get("team"), an.rnd(100 - d[j], 1)] for j in idx]
    return out


def write_careers(write: Callable[[str, Any], None], rows_by_season: dict[int, dict | None], blocks: dict[str, dict],
                  old_reader: Callable[[str], dict | None] | None = None, current_season: int | None = None) -> dict[str, list]:
    """players/<pid>.json for every player with enough volume in some season; returns the players_index entries
    {pid: [name, team, pos, first_season, last_season]}. Placeholder ids (`real_pid` false, e.g. "0") are skipped."""
    ppl = people.people()
    by: dict[str, list] = {}
    for s, rows in sorted(rows_by_season.items()):
        for pid, r in (rows or {}).items():
            by.setdefault(pid, []).append(r)
    idx: dict[str, list] = {}
    written = 0
    for pid, seasons in by.items():
        if not real_pid(pid):
            continue
        ok = False
        for r in seasons:
            k, floor = MIN_FILE.get(r.get("group"), ("games", 99))
            if (an.fnum((r.get("values") or {}).get(k)) or 0) >= floor:
                ok = True
                break
        if not ok and pid not in blocks:
            continue
        seasons.sort(key=lambda r: r["season"])
        last = seasons[-1]
        p = ppl.get(pid) or {}
        payload = {"ok": True, "id": pid, "name": p.get("name") or last.get("name"), "pos": p.get("pos") or last.get("pos"),
                   "group": last.get("group"), "college": p.get("college"), "draft": p.get("draft"), "dob": p.get("dob"),
                   "height": p.get("height"), "weight": p.get("weight"),
                   "seasons": [{"season": r["season"], "team": r.get("team"), "group": r.get("group"), "games": r.get("games"),
                                "qualified": r.get("qualified"), "age": r.get("age"), **(r.get("values") or {}),
                                "plus": r.get("plus") or {}, "epa": _epa_of(r), "value": _value_of(r)} for r in seasons],
                   "current": None, "similar": []}
        blk = blocks.get(pid)
        if blk:
            payload["current"] = {k: blk.get(k) for k in ("season", "log", "charts", "ngs", "ftn", "projection", "values", "pct", "pct_pos")}
            payload["similar"] = blk.get("similar") or []
        elif old_reader is not None:
            old = old_reader(pid)
            if old and (old.get("current") or {}).get("season") in [r["season"] for r in seasons]:
                payload["current"] = old.get("current")
                payload["similar"] = old.get("similar") or []
        if old_reader is not None:
            old = old_reader(pid)
            if old is not None and _same(old, payload):
                idx[pid] = [payload["name"], last.get("team"), payload["pos"], seasons[0]["season"], last["season"]]
                continue
        write(f"players/{pid}.json", payload)
        written += 1
        idx[pid] = [payload["name"], last.get("team"), payload["pos"], seasons[0]["season"], last["season"]]
    logger.info("careers: %d files written, %d indexed", written, len(idx))
    return idx


def _value_of(r: dict) -> Any:
    """The season's value in points: Gridiron Value (offence), splash EPA (defence), points over expected (kickers),
    punting EPA (punters)."""
    v = r.get("values") or {}
    for k in {"K": ("pts_oe",), "P": ("punt_epa",), "DEF": ("def_value",)}.get(r.get("group"), ("value",)):
        if v.get(k) is not None:
            return v[k]
    return v.get("value")


def _epa_of(r: dict) -> Any:
    v = r.get("values") or {}
    for k in ("epa_total", "rec_epa", "def_value", "punt_epa", "pts_oe"):
        if v.get(k) is not None:
            return v[k]
    if v.get("rush_epa") is not None and v.get("carries"):
        return round(v["rush_epa"] * v["carries"], 2)
    return None


def _same(a: dict, b: dict) -> bool:
    import json
    try:
        ka = json.dumps(an.clean({k: v for k, v in a.items() if k != "updated_at"}), sort_keys=True)
        kb = json.dumps(an.clean({k: v for k, v in b.items() if k != "updated_at"}), sort_keys=True)
        return ka == kb
    except (TypeError, ValueError):
        return False
