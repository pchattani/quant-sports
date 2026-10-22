"""
Availability: depth-chart starters out (game-model feature `so_off` / `so_def`, added 21 Oct 2026; research in
docs/research/nfl_edge.md, module edge/starters.py re-exports this one).

Depth-chart starters as of the team's previous game who miss this one, by position group. Before 2020 (and wherever
the weekly roster has no game-day status) a starter's chance of missing is read from the final injury report
(Out 1, Doubtful 0.85, Questionable 0.15; nflverse injuries, 2009 onward). From 2020, nflverse weekly rosters carry
the game-day status, so the actual inactives (INA) and reserve / suspended / released players count 1 and everyone
else 0: known about 90 minutes before kickoff, so close decisions only (open rows get 0).

No snap counts are needed (Pro Football Reference data is not used), so the 2009-2016 design seasons have the
feature too, unlike the `inj` experiment of 2 Oct 2026 (participation snap shares, 2016 onward).

Long-term absentees are mostly not counted: a player hurt weeks ago is off the previous game's chart (his absence is
already in the ratings and in the market ratings, which were fitted on lines that priced it).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

P_MISS = {"Out": 1.0, "Doubtful": 0.85, "Questionable": 0.15}
GROUPS = {
    "ol": ("LT", "LG", "C", "RG", "RT", "T", "G", "OT", "OG", "OL"),
    "rec": ("WR", "SE", "FL", "SWR", "LWR", "RWR", "SLOT", "TE", "Y"),
    "rb": ("RB", "HB", "FB", "TB"),
    "dl": ("DE", "DT", "NT", "LDE", "RDE", "LDT", "RDT", "DL", "EDGE", "LEO", "RUSH"),
    "lb": ("OLB", "ILB", "MLB", "LB", "LOLB", "ROLB", "WLB", "SLB", "LILB", "RILB", "MIKE", "WILL", "SAM", "JACK"),
    "db": ("CB", "LCB", "RCB", "FS", "SS", "S", "NB", "DB", "SAF", "NICKEL"),
}
POS2GRP = {p: g for g, ps in GROUPS.items() for p in ps}
MISSING_STATUS = ("INA", "RES", "SUS", "CUT", "PUP", "NWT", "RSN", "RSR", "EXE", "TRD", "TRC", "TRT")


def team_alias(t: str, season: int) -> str:
    if t in ("LAR", "STL") and season >= 2016:
        return "LA"
    if t == "JAC":
        return "JAX"
    if t == "SD" and season >= 2017:
        return "LAC"
    if t == "OAK" and season >= 2020:
        return "LV"
    return t


def depth_starters(season: int, sched: pd.DataFrame) -> pd.DataFrame:
    """(week, team, gsis_id, grp): non-QB, non-special-teams starters on the depth chart as of the team's previous
    game (week w-1's weekly chart; from 2025, daily snapshots: the last one before the previous game day + 12 h; a
    team's first game uses its chart for that game)."""
    p = D.raw_root() / "raw" / "depth_charts" / f"depth_charts_{season}.parquet"
    if not p.exists():
        return pd.DataFrame(columns=["week", "team", "gsis_id", "grp"])
    d = pd.read_parquet(p)
    g = sched[sched["season"] == season]
    rows = []
    teams = set(g["home_team"]) | set(g["away_team"])
    if "dt" in d.columns:
        d = d[d["pos_rank"] == 1].copy()
        d["grp"] = d["pos_abb"].map(POS2GRP)
        d = d[d["grp"].notna() & d["gsis_id"].notna()]
        d["dt"] = pd.to_datetime(d["dt"], utc=True, errors="coerce")
        d["team"] = d["team"].map(lambda x: team_alias(x, season))
        for team in teams:
            tg = g[(g["home_team"] == team) | (g["away_team"] == team)].sort_values("gameday")
            days = [pd.Timestamp(x, tz="UTC") for x in tg["gameday"]]
            dd = d[d["team"] == team]
            snaps = np.array(sorted(dd["dt"].dropna().unique()))
            for k, w in enumerate(tg["week"].astype(int)):
                ref = days[k - 1] + pd.Timedelta(hours=12) if k > 0 else days[k]
                cand = snaps[snaps < ref] if len(snaps) else snaps
                if not len(cand):
                    continue
                sn = dd[dd["dt"] == cand[-1]]
                rows += [(w, team, r.gsis_id, r.grp) for r in sn.drop_duplicates("gsis_id").itertuples(index=False)]
    else:
        d = d[(d["depth_team"].astype(str) == "1") & d["formation"].isin(["Offense", "Defense"]) & d["week"].notna()].copy()
        d["grp"] = d["depth_position"].map(POS2GRP)
        d["grp"] = d["grp"].fillna(d["position"].map(POS2GRP))
        d = d[d["grp"].notna() & d["gsis_id"].notna()]
        d["team"] = d["club_code"].map(lambda x: team_alias(x, season))
        d["week"] = d["week"].astype(int)
        for team in teams:
            tg = g[(g["home_team"] == team) | (g["away_team"] == team)].sort_values("gameday")
            dd = d[d["team"] == team]
            avail = sorted(dd["week"].unique())
            prev = None
            for w in tg["week"].astype(int):
                src = prev if prev is not None else w
                cand = [x for x in avail if x <= src]
                if cand:
                    rows += [(w, team, r.gsis_id, r.grp) for r in dd[dd["week"] == cand[-1]].drop_duplicates("gsis_id").itertuples(index=False)]
                prev = w
    return pd.DataFrame(rows, columns=["week", "team", "gsis_id", "grp"])


def _kickoffs(season: int) -> pd.DataFrame:
    """(week, team, ko): each team's kickoff (UTC) by week, from the schedules (gameday + gametime, US Eastern)."""
    from oddsmarkets.nfl.sources.nflverse import kickoff_utc
    s = pd.read_parquet(D.schedules_path(), columns=["season", "week", "gameday", "gametime", "home_team", "away_team"])
    s = s[s["season"] == season]
    ko = pd.to_datetime([kickoff_utc(a, b) for a, b in zip(s["gameday"], s["gametime"])], utc=True)
    rows = [pd.DataFrame({"week": s["week"].astype(int).to_numpy(), "team": s[c].map(lambda x: team_alias(x, season)).to_numpy(),
                          "ko": ko}) for c in ("home_team", "away_team")]
    return pd.concat(rows, ignore_index=True).drop_duplicates(["week", "team"])


def starter_rows(season: int, use_inactives: bool = True, report_cutoff_h: float | None = None) -> pd.DataFrame:
    """(week, team, gsis_id, grp, pm, src, by_inactives): each depth-chart starter and his chance of missing the game
    (by_inactives: read from the game-day inactives rather than the injury report).
    report_cutoff_h (research, 22 Oct 2026): count an injury-report row only if its `date_modified` is at least that
    many hours before the team's kickoff (a later-modified row counts 0); seasons without `date_modified` (2009,
    2025 on) count every row. Use with use_inactives=False for a decision a day out."""
    sched = pd.read_parquet(D.schedules_path(), columns=["season", "week", "gameday", "home_team", "away_team"])
    ST = depth_starters(season, sched)
    if ST.empty:
        return pd.DataFrame()
    key = pd.MultiIndex.from_arrays([ST["week"], ST["team"], ST["gsis_id"]])
    pm = np.zeros(len(ST))
    ip = D.raw_root() / "raw" / "injuries" / f"injuries_{season}.parquet"
    has_rep = ip.exists()
    if has_rep:
        inj = pd.read_parquet(ip)
        inj = inj[inj["report_status"].isin(list(P_MISS)) & inj["gsis_id"].notna() & inj["week"].notna()]
        inj = inj.assign(team=inj["team"].map(lambda x: team_alias(x, season)), week=inj["week"].astype(int),
                         pm=inj["report_status"].map(P_MISS))
        if report_cutoff_h is not None and "date_modified" in inj.columns:
            dm = pd.to_datetime(inj["date_modified"], utc=True, errors="coerce")
            if dm.notna().any():
                k = inj[["week", "team"]].merge(_kickoffs(season), on=["week", "team"], how="left")["ko"].to_numpy()
                late = (dm.to_numpy() > (pd.DatetimeIndex(k) - pd.Timedelta(hours=report_cutoff_h)).to_numpy())
                inj = inj.assign(pm=np.where(late, 0.0, inj["pm"].to_numpy(float)))
        miss = inj.groupby(["week", "team", "gsis_id"])["pm"].max()
        pm = miss.reindex(key).fillna(0.0).to_numpy()
    src = "report" if has_rep else "none"
    known = np.zeros(len(ST), dtype=bool)
    rp = D.raw_root() / "raw" / "weekly_rosters" / f"roster_weekly_{season}.parquet"
    if use_inactives and rp.exists():
        r = pd.read_parquet(rp, columns=["week", "team", "gsis_id", "status"])
        if (r["status"] == "INA").any():
            r = r[r["gsis_id"].notna() & r["week"].notna()]
            r = r.assign(team=r["team"].map(lambda x: team_alias(x, season)), week=r["week"].astype(int))
            st = r.drop_duplicates(["week", "team", "gsis_id"]).set_index(["week", "team", "gsis_id"])["status"].reindex(key)
            known = np.array(st.notna().to_numpy(), dtype=bool)
            # a week whose roster has no INA rows at all (not yet published) keeps the report
            wk_has = r.groupby("week")["status"].apply(lambda s: (s == "INA").any())
            known = known & np.array(ST["week"].map(wk_has).fillna(False).to_numpy(), dtype=bool)
            # news only: missing now, and either on this week's injury report or active the week before (a starter
            # listed on a stale chart while on reserve for weeks is already in the ratings and the market ratings)
            st_all = r.drop_duplicates(["week", "team", "gsis_id"]).set_index(["week", "team", "gsis_id"])["status"]
            prev_key = pd.MultiIndex.from_arrays([ST["week"] - 1, ST["team"], ST["gsis_id"]])
            was_act = np.array(st_all.reindex(prev_key).eq("ACT").to_numpy(), dtype=bool)
            on_rep = pm > 0
            actual = np.array(st.isin(MISSING_STATUS).to_numpy(), dtype=float) * (was_act | on_rep)
            pm = np.where(known, actual, pm)
            src = "inactives"
    return ST.assign(pm=pm, src=src, by_inactives=known)


def starters_out(season: int, use_inactives: bool = True, report_cutoff_h: float | None = None,
                 weights=None) -> pd.DataFrame:
    """(season, week, team, out_<grp>, src): expected depth-chart starters missing the game, by position group.
    weights (research): a function of the starter rows returning one weight per starter (default 1 each)."""
    ST = starter_rows(season, use_inactives, report_cutoff_h)
    if ST.empty:
        return pd.DataFrame()
    src = ST["src"].iloc[0]
    if weights is not None:
        ST = ST.assign(pm=ST["pm"].to_numpy(float) * np.asarray(weights(season, ST), float))
    out = ST.pivot_table(index=["week", "team"], columns="grp", values="pm", aggfunc="sum").reset_index()
    for gname in GROUPS:
        if gname not in out:
            out[gname] = 0.0
    out = out.rename(columns={gname: f"out_{gname}" for gname in GROUPS}).fillna(0.0)
    out["season"] = season
    out["src"] = src
    return out


def _inputs_mtime(season: int) -> float:
    paths = [D.raw_root() / "raw" / sub / f"{tpl}_{season}.parquet" for sub, tpl in
             (("depth_charts", "depth_charts"), ("injuries", "injuries"), ("weekly_rosters", "roster_weekly"))]
    return max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)


def load(seasons, refresh: bool = False, path=None) -> pd.DataFrame:
    """starters_out for the seasons (2009 onward), cached; a season is recomputed when its raw inputs are newer
    than the cache (the current season every time its reports or rosters update)."""
    path = path or (D.c_cache() / "availability.parquet")
    L = pd.read_parquet(path) if path.exists() and not refresh else pd.DataFrame()
    stamp = path.stat().st_mtime if path.exists() and not refresh else 0.0
    want = sorted(int(s) for s in set(seasons) if int(s) >= 2009)
    redo = [s for s in want if not len(L) or s not in set(L["season"]) or _inputs_mtime(s) > stamp]
    if redo:
        new = [x for x in (starters_out(s) for s in redo) if len(x)]
        keep = L[~L["season"].isin(redo)] if len(L) else L
        L = pd.concat(([keep] if len(keep) else []) + new, ignore_index=True) if new or len(keep) else pd.DataFrame()
        if len(L):
            path.parent.mkdir(parents=True, exist_ok=True)
            L.to_parquet(path, index=False)
    return L[L["season"].isin(want)] if len(L) else L


def attach(R: pd.DataFrame, L: pd.DataFrame, open_modes_zero: bool = True) -> pd.DataFrame:
    """f_so_<grp> (home - away), f_so_off / f_so_def (pooled), t_so / t_so_def (both sides' offensive / defensive
    starters out) on a rows frame (season, week, home, away, mode)."""
    m = L.drop_duplicates(["season", "week", "team"]).set_index(["season", "week", "team"]) if len(L) else None
    out = R.copy()
    cols = [f"out_{g}" for g in GROUPS]
    for side, col in (("h", "home"), ("a", "away")):
        if m is None:
            for c in cols:
                out[f"{c}_{side}"] = 0.0
            continue
        sub = m.reindex(pd.MultiIndex.from_arrays([out["season"], out["week"], out[col]]))
        for c in cols:
            out[f"{c}_{side}"] = sub[c].fillna(0.0).to_numpy()
    for g in GROUPS:
        out[f"f_so_{g}"] = out[f"out_{g}_h"] - out[f"out_{g}_a"]
    out["f_so_off"] = out[["f_so_ol", "f_so_rec", "f_so_rb"]].sum(axis=1)
    out["f_so_def"] = out[["f_so_dl", "f_so_lb", "f_so_db"]].sum(axis=1)
    out["t_so"] = sum(out[f"out_{g}_{s}"] for g in ("ol", "rec", "rb") for s in ("h", "a"))
    out["t_so_def"] = sum(out[f"out_{g}_{s}"] for g in ("dl", "lb", "db") for s in ("h", "a"))
    if open_modes_zero and "mode" in out:
        so = [c for c in out.columns if c.startswith(("f_so_", "t_so"))]
        out.loc[out["mode"] != "close", so] = 0.0
    return out
