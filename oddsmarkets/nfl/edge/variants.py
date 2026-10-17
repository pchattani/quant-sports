"""
Team-strength input variants for the edge experiments: (units_of, team_strength params) by name.

garbage   unit rows without garbage time: plays with nflfastR WP outside [0.05, 0.95], and fourth-quarter plays
          outside [0.10, 0.90], are dropped before aggregation (WP is the pre-snap in-game estimate, no look-ahead)
fumble    fumble-recovery luck neutralised: every fumble play's EPA is replaced by the season's mean EPA of fumble
          plays of the same type (pass / run), so who fell on the ball no longer moves a rating
cont      roster-continuity priors: team_strength's continuity term k = 0.5 for every unit (production 0)
hl15/hl60 team-strength half-life 15 / 60 weeks (production 30)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import team_strength as TS

EXTRA = ["wp", "fumble"]


def _units(season: int, kind: str) -> pd.DataFrame:
    path = D.cache_root() / "edge" / f"units_{kind}_{season}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    d = D.load_pbp(season, D.PBP_COLS + EXTRA)
    if d is None or d.empty:
        return pd.DataFrame()
    if kind == "garbage" and "wp" in d:
        wp = pd.to_numeric(d["wp"], errors="coerce")
        bad = (wp < 0.05) | (wp > 0.95) | ((d["qtr"] == 4) & ((wp < 0.10) | (wp > 0.90)))
        d = d[~bad.fillna(False)]
    if kind == "fumble" and "fumble" in d:
        f = pd.to_numeric(d["fumble"], errors="coerce").fillna(0) > 0
        epa = pd.to_numeric(d["epa"], errors="coerce")
        for pt in ("pass", "run"):
            m = f & (d["play_type"] == pt) & epa.notna()
            if m.any():
                epa = epa.where(~m, float(epa[m].mean()))
        d = d.assign(epa=epa)
    out = D.unit_rows_from_pbp(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def get(name: str):
    p = TS.params()
    if name in ("garbage", "fumble"):
        return (lambda s: _units(s, name)), p
    if name == "cont":
        p["cont"] = {k: 0.5 for k in p["cont"]}
        return None, p
    if name.startswith("hl"):
        p["half_life_weeks"] = float(name[2:])
        return None, p
    raise KeyError(name)
