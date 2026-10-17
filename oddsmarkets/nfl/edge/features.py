"""
Extra walk-forward features for the edge experiments (each value uses only games / reports dated before the game).

pace(seasons)      per game: each side's exponentially weighted (half-life `hl` team games, carried across seasons)
                   offensive plays per game, neutral-situation seconds per snap (same drive, quarters 1-3, score within
                   7) and fourth-down go rate on 4th and 1-3 between the own 40 and the opponent 35.
injuries(seasons)  per game and side: snap-share-weighted availability lost to the final injury report
                   (Out 1, Doubtful 0.85, Questionable 0.15), offence and defence separately, QBs excluded (the QB term
                   is handled by the expected / listed starter). Importance = the player's mean offence / defence snap
                   share over the team's last four games before this one (0 when he did not play), so a long-term
                   absentee already absent from the ratings counts ~0. Snap shares are counted from the play-by-play
                   participation (`_cdata.onfield`: NFL Next Gen Stats / FTN, 2016-2025, published after each
                   season; nflverse snap counts are Pro Football Reference's and are not used), injuries from
                   nflverse (2009 onward): games without both get 0. Reports are dated (date_modified); `cutoff_hours` drops reports
                   modified later than kickoff minus that many hours.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

PACE_COLS = ["game_id", "season", "week", "posteam", "defteam", "play_type", "qtr", "game_seconds_remaining",
             "score_differential", "fixed_drive", "qb_kneel", "qb_spike", "down", "ydstogo", "yardline_100", "game_date"]
P_MISS = {"Out": 1.0, "Doubtful": 0.85, "Questionable": 0.15}


def _cache(name: str):
    return D.cache_root() / "edge" / name


def team_game_pace(season: int) -> pd.DataFrame:
    path = _cache(f"pace_{season}.parquet")
    if path.exists():
        return pd.read_parquet(path)
    d = D.load_pbp(season, PACE_COLS)
    if d is None or d.empty:
        return pd.DataFrame()
    pt = d["play_type"].astype(str)
    snap = pt.isin(["pass", "run"]) & (d["qb_kneel"].fillna(0) == 0) & (d["qb_spike"].fillna(0) == 0)
    x = d[snap].copy()
    x = x.sort_values(["game_id", "fixed_drive", "game_seconds_remaining"], ascending=[True, True, False])
    x["dt"] = -x.groupby(["game_id", "fixed_drive"])["game_seconds_remaining"].diff()
    neutral = (x["qtr"] <= 3) & (x["score_differential"].abs() <= 7) & x["dt"].between(5, 60)
    plays = x.groupby(["game_id", "posteam"]).size().rename("plays")
    spp = x[neutral].groupby(["game_id", "posteam"])["dt"].mean().rename("spp")
    f = d[(d["down"] == 4) & d["ydstogo"].between(1, 3) & d["yardline_100"].between(35, 60) & pt.isin(["pass", "run", "punt", "field_goal"])]
    go = f.assign(go=f["play_type"].isin(["pass", "run"]).astype(float)).groupby(["game_id", "posteam"])["go"].agg(["sum", "count"])
    meta = d.groupby("game_id").agg(season=("season", "first"), week=("week", "first"), date=("game_date", "first"))
    out = pd.concat([plays, spp, go.rename(columns={"sum": "go_n", "count": "go_opp"})], axis=1).reset_index()
    out = out.rename(columns={"posteam": "team"}).merge(meta.reset_index(), on="game_id")
    out["date"] = pd.to_datetime(out["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def pace(seasons, hl: float = 8.0) -> pd.DataFrame:
    """game_id -> pace_h, pace_a (plays/game EWMA), spp_h, spp_a (seconds/snap EWMA), go_h, go_a (go rate, shrunk)."""
    T = pd.concat([team_game_pace(s) for s in seasons], ignore_index=True)
    T = T.sort_values(["date", "game_id"])
    T["fr"] = T["team"].map(D.franchise)
    a = 0.5 ** (1.0 / hl)
    state: dict[str, list] = {}
    rows = []
    lg_plays, lg_spp = 63.0, 28.0
    for gid, g in T.groupby("game_id", sort=False):
        for r in g.itertuples(index=False):
            st = state.get(r.fr)
            rows.append({"game_id": gid, "team": r.team,
                         "pace": st[0] / st[1] if st else lg_plays, "spp": st[2] / st[3] if st and st[3] > 0 else lg_spp,
                         "go": (st[4] + 2.0 * 0.25) / (st[5] + 2.0) if st else 0.25})
        for r in g.itertuples(index=False):
            st = state.setdefault(r.fr, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            st[:] = [v * a for v in st[:4]] + [v * 0.5 ** (1 / 32.0) for v in st[4:]]
            st[0] += r.plays
            st[1] += 1.0
            if np.isfinite(r.spp):
                st[2] += r.spp
                st[3] += 1.0
            st[4] += float(r.go_n) if np.isfinite(r.go_n) else 0.0
            st[5] += float(r.go_opp) if np.isfinite(r.go_opp) else 0.0
    return pd.DataFrame(rows)


def attach_pace(G: pd.DataFrame, PC: pd.DataFrame) -> pd.DataFrame:
    """Adds t_pace (sum of both sides' plays/game minus the season-to-date league mean x2, in plays), t_spp and
    t_go (sums of deviations) to a rows frame with game_id, home, away."""
    m = PC.set_index(["game_id", "team"])
    out = G.copy()
    for side in ("h", "a"):
        key = list(zip(out["game_id"], out["home" if side == "h" else "away"]))
        sub = m.reindex(key)
        out[f"pace_{side}"] = sub["pace"].to_numpy()
        out[f"spp_{side}"] = sub["spp"].to_numpy()
        out[f"go_{side}"] = sub["go"].to_numpy()
    out["t_pace"] = (out["pace_h"] + out["pace_a"]).fillna(126.0) - 126.0
    out["t_spp"] = (out["spp_h"] + out["spp_a"]).fillna(56.0) - 56.0
    out["t_go"] = (out["go_h"] + out["go_a"]).fillna(0.5) - 0.5
    return out


# ── injuries ────────────────────────────────────────────────────────────────

def _snap_shares(season: int) -> pd.DataFrame | None:
    """week, team, player (gsis id), offense_pct, defense_pct per game from the play-by-play participation
    (`_cdata.onfield`); None for seasons without participation."""
    O = D.onfield(season)
    if O is None or not len(O):
        return None
    O = O.assign(pct=O["snaps"] / O["team_snaps"])
    s = O.pivot_table(index=["game_id", "week", "team", "player"], columns="side", values="pct", aggfunc="max").reset_index()
    for side in ("off", "def"):
        if side not in s.columns:
            s[side] = 0.0
    return s.rename(columns={"off": "offense_pct", "def": "defense_pct"}).fillna({"offense_pct": 0.0, "defense_pct": 0.0})


def injury_load(season: int, cutoff_hours: float = 0.0, kickoffs: pd.Series | None = None) -> pd.DataFrame:
    """game_id, team, inj_off, inj_def (snap-share starters lost; QBs excluded)."""
    ip = D.raw_root() / "raw" / "injuries" / f"injuries_{season}.parquet"
    S = _snap_shares(season)
    if not ip.exists() or S is None:
        return pd.DataFrame(columns=["season", "week", "team", "inj_off", "inj_def"])
    inj = pd.read_parquet(ip)
    inj = inj[inj["report_status"].isin(list(P_MISS)) & (inj["position"] != "QB")].copy()
    inj["pid"] = inj["gsis_id"]
    inj["pmiss"] = inj["report_status"].map(P_MISS)
    inj["week"] = inj["week"].astype(int)
    if kickoffs is not None and cutoff_hours > 0:
        ko = inj.apply(lambda r: kickoffs.get((int(season), int(r["week"]), r["team"])), axis=1)
        ok = pd.to_datetime(inj["date_modified"], utc=True) <= pd.to_datetime(ko, utc=True) - pd.Timedelta(hours=cutoff_hours)
        inj = inj[ok.fillna(False)]
    # importance: mean share over the team's last 4 game-weeks before `week` (0 when absent)
    S = S.copy()
    rows = []
    for team, st in S.groupby("team"):
        wk = sorted(st["week"].unique())
        off = st.pivot_table(index="player", columns="week", values="offense_pct", aggfunc="max").reindex(columns=wk).fillna(0.0)
        de = st.pivot_table(index="player", columns="week", values="defense_pct", aggfunc="max").reindex(columns=wk).fillna(0.0)
        ti = inj[inj["team"] == team]
        for w, g in ti.groupby("week"):
            prev = [x for x in wk if x < w][-4:]
            if not prev:
                continue
            io = off[prev].mean(axis=1)
            idf = de[prev].mean(axis=1)
            pm = g.dropna(subset=["pid"]).groupby("pid")["pmiss"].max()
            rows.append({"season": season, "week": int(w), "team": team,
                         "inj_off": float((io.reindex(pm.index).fillna(0.0) * pm).sum()),
                         "inj_def": float((idf.reindex(pm.index).fillna(0.0) * pm).sum())})
    return pd.DataFrame(rows)


def attach_injuries(G: pd.DataFrame, seasons, cutoff_hours: float = 0.0) -> pd.DataFrame:
    kick = None
    if cutoff_hours > 0:
        from oddsmarkets.nfl.edge import prices as PR
        pr = PR.game_prices(seasons)
        kick = {}
        for r in pr.itertuples(index=False):
            kick[(int(r.season), int(r.week), r.home)] = r.kickoff
            kick[(int(r.season), int(r.week), r.away)] = r.kickoff
    L = pd.concat([injury_load(s, cutoff_hours, kick) for s in seasons], ignore_index=True)
    m = L.set_index(["season", "week", "team"]) if len(L) else None
    out = G.copy()
    for side, col in (("h", "home"), ("a", "away")):
        if m is None:
            out[f"inj_off_{side}"] = 0.0
            out[f"inj_def_{side}"] = 0.0
            continue
        sub = m.reindex(list(zip(out["season"], out["week"], out[col])))
        out[f"inj_off_{side}"] = sub["inj_off"].fillna(0.0).to_numpy()
        out[f"inj_def_{side}"] = sub["inj_def"].fillna(0.0).to_numpy()
    out["f_inj_off"] = out["inj_off_h"] - out["inj_off_a"]
    out["f_inj_def"] = out["inj_def_h"] - out["inj_def_a"]
    out["t_inj"] = out["inj_off_h"] + out["inj_off_a"] - 0.5 * (out["inj_def_h"] + out["inj_def_a"])
    return out
