"""
Starters out for the edge experiments: the production module models/availability.py (moved there on 21 Oct 2026 when
the feature was promoted), with the research cache data/nfl/cache/edge/starters_out.parquet.

Round 3 (22 Oct 2026; pre-registered in docs/research/nfl_edge.md section 10.1):
- `load_dated`: the injury report only (no game-day inactives), each row counted only if its `date_modified` is at
  least 24 h before kickoff: what is known a day out (experiment `so24`, openA rows).
- `load_pv`: each missing starter weighted by his involvement per game relative to the average starter of his group
  (experiment `so_pv`, close rows). `involvement` / `weights` below.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models.availability import (GROUPS, MISSING_STATUS, P_MISS, POS2GRP, attach,  # noqa: F401
                                                 depth_starters, starters_out, team_alias)
from oddsmarkets.nfl.models import availability as _AV

CACHE = D.cache_root() / "edge"
WINDOW = 8          # last games with any involvement
K_SHRINK = 3.0      # games of prior weight toward 1 (the average starter)
NORM_SEASONS = (2009, 2016)
OFF_GROUPS = ("rec", "rb")
DEF_GROUPS = ("dl", "lb", "db")
TACKLES = ("solo_tackle_1_player_id", "solo_tackle_2_player_id", "assist_tackle_1_player_id", "assist_tackle_2_player_id",
           "assist_tackle_3_player_id", "assist_tackle_4_player_id", "tackle_with_assist_1_player_id",
           "tackle_with_assist_2_player_id")
SPLASH = (("sack_player_id", 1.0), ("half_sack_1_player_id", 0.5), ("half_sack_2_player_id", 0.5),
          ("qb_hit_1_player_id", 1.0), ("qb_hit_2_player_id", 1.0), ("tackle_for_loss_1_player_id", 1.0),
          ("tackle_for_loss_2_player_id", 1.0), ("pass_defense_1_player_id", 1.0), ("pass_defense_2_player_id", 1.0),
          ("interception_player_id", 1.0), ("forced_fumble_player_1_player_id", 1.0),
          ("forced_fumble_player_2_player_id", 1.0))


def load(seasons, refresh: bool = False):
    return _AV.load(seasons, refresh=refresh, path=D.cache_root() / "edge" / "starters_out.parquet")


def _load_kw(seasons, path, refresh: bool, **kw) -> pd.DataFrame:
    want = sorted(int(s) for s in set(seasons) if int(s) >= 2009)
    L = pd.read_parquet(path) if path.exists() and not refresh else pd.DataFrame()
    redo = [s for s in want if not len(L) or s not in set(L["season"])]
    if redo:
        new = [x for x in (starters_out(s, **kw) for s in redo) if len(x)]
        keep = L[~L["season"].isin(redo)] if len(L) else L
        L = pd.concat(([keep] if len(keep) else []) + new, ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        L.to_parquet(path, index=False)
    return L[L["season"].isin(want)]


def load_dated(seasons, refresh: bool = False, cutoff_h: float = 24.0) -> pd.DataFrame:
    """Report-only starters out with report rows modified inside the last `cutoff_h` hours before kickoff dropped."""
    return _load_kw(seasons, CACHE / f"starters_out_rep{int(cutoff_h)}.parquet", refresh, use_inactives=False,
                    report_cutoff_h=cutoff_h)


# ── player-level weights (experiment so_pv) ─────────────────────────────────

def involvement(season: int) -> pd.DataFrame:
    """(gsis_id, season, week, off, def): per player and game, targets + carries (off) and tackles + 2 x splash
    plays (def), from nflverse play-by-play."""
    path = CACHE / f"involve_{season}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    cols = ["game_id", "week", "play_type", "receiver_player_id", "rusher_player_id", "two_point_attempt"]
    cols += list(TACKLES) + [c for c, _ in SPLASH]
    d = D.load_pbp(season, cols)
    if d is None or d.empty:
        return pd.DataFrame(columns=["gsis_id", "season", "week", "off", "def"])
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1
    d = d[~tp]
    parts = []
    pas = d["play_type"] == "pass"
    run = d["play_type"] == "run"
    parts.append(pd.DataFrame({"gsis_id": d.loc[pas, "receiver_player_id"], "week": d.loc[pas, "week"], "off": 1.0, "def": 0.0}))
    parts.append(pd.DataFrame({"gsis_id": d.loc[run, "rusher_player_id"], "week": d.loc[run, "week"], "off": 1.0, "def": 0.0}))
    for c in TACKLES:
        if c in d:
            parts.append(pd.DataFrame({"gsis_id": d[c], "week": d["week"], "off": 0.0, "def": 1.0}))
    for c, w in SPLASH:
        if c in d:
            parts.append(pd.DataFrame({"gsis_id": d[c], "week": d["week"], "off": 0.0, "def": 2.0 * w}))
    x = pd.concat(parts, ignore_index=True)
    x = x[x["gsis_id"].notna() & (x["gsis_id"].astype(str) != "")]
    out = x.groupby(["gsis_id", "week"], as_index=False)[["off", "def"]].sum()
    out["week"] = out["week"].astype(int)
    out.insert(1, "season", int(season))
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def _history(seasons) -> pd.DataFrame:
    """Per player and game played (any involvement), rolling WINDOW-game sums and counts through that game."""
    H = pd.concat([involvement(s) for s in seasons], ignore_index=True)
    H["t"] = H["season"] * 100 + H["week"]
    H = H.sort_values(["gsis_id", "t"]).reset_index(drop=True)
    g = H.groupby("gsis_id")
    for c in ("off", "def"):
        H[f"{c}_sum"] = g[c].transform(lambda v: v.rolling(WINDOW, min_periods=1).sum())
    H["n"] = g["t"].transform(lambda v: v.rolling(WINDOW, min_periods=1).count())
    return H[["gsis_id", "t", "off_sum", "def_sum", "n"]]


_HIST: dict = {}


def raw_rates(ST: pd.DataFrame, season: int) -> pd.DataFrame:
    """For starter rows (week, gsis_id, grp) of a season: involvement per game over his last WINDOW games strictly
    before this week (rate) and the number of those games (n)."""
    key = season
    if key not in _HIST:
        _HIST[key] = _history(range(max(2008, season - 3), season + 1))
    H = _HIST[key]
    q = ST[["week", "gsis_id", "grp"]].copy()
    q["t"] = season * 100 + q["week"].astype(int) - 1          # strictly before this week (t - 1: allow_exact on t-1)
    q["_i"] = np.arange(len(q))
    m = pd.merge_asof(q.sort_values("t"), H.sort_values("t"), on="t", by="gsis_id", direction="backward")
    m = m.sort_values("_i")
    off = m["grp"].isin(OFF_GROUPS).to_numpy()
    s = np.where(off, m["off_sum"].to_numpy(float), m["def_sum"].to_numpy(float))
    n = m["n"].fillna(0).to_numpy(float)
    rate = np.where(n > 0, s / np.maximum(n, 1), np.nan)
    return pd.DataFrame({"rate": rate, "n": n}, index=ST.index)


_NORM: dict = {}


def group_norms() -> dict:
    """Mean involvement per game of depth-chart starters (with a history) by group, 2009-2016 (frozen)."""
    if _NORM:
        return _NORM
    path = CACHE / "involve_norms.json"
    if path.exists():
        import json
        _NORM.update(json.loads(path.read_text()))
        return _NORM
    acc = []
    for s in range(NORM_SEASONS[0], NORM_SEASONS[1] + 1):
        ST = _AV.starter_rows(s, use_inactives=False)
        if ST.empty:
            continue
        r = raw_rates(ST, s)
        acc.append(pd.DataFrame({"grp": ST["grp"].to_numpy(), "rate": r["rate"].to_numpy()}))
    A = pd.concat(acc)
    norms = {g: float(A.loc[A["grp"] == g, "rate"].mean()) for g in OFF_GROUPS + DEF_GROUPS}
    import json
    path.write_text(json.dumps(norms, indent=1))
    _NORM.update(norms)
    return _NORM


def weights(season: int, ST: pd.DataFrame) -> np.ndarray:
    """Weight per starter: (n x rate / norm + K) / (n + K); offensive linemen and starters without history 1."""
    nm = group_norms()
    r = raw_rates(ST, season)
    norm = ST["grp"].map(nm).to_numpy(float)
    rel = r["rate"].to_numpy(float) / norm
    n = r["n"].to_numpy(float)
    w = (n * np.nan_to_num(rel, nan=1.0) + K_SHRINK) / (n + K_SHRINK)
    w = np.where(np.isfinite(norm) & np.isfinite(rel), w, 1.0)
    return w


def load_pv(seasons, refresh: bool = False) -> pd.DataFrame:
    """Close-decision starters out (report + inactives, as production) weighted by `weights`."""
    return _load_kw(seasons, CACHE / "starters_out_pv.parquet", refresh, weights=weights)
