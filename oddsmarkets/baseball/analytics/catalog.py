"""
Shared catalogue plumbing: model tables as lookups, Savant leaderboards, positions and roles, qualification,
and the finishing pass (rounding, direction-aware percentiles with sample floors and stabilisation shrinkage).
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics.context import SeasonContext, frame_rows

POS_NAME = {1: "P", 2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF", 10: "DH"}
POS_GROUP = {"C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS", "CF": "CF", "LF": "LF/RF", "RF": "LF/RF",
             "OF": "LF/RF", "DH": "DH", "TWP": "DH"}


def lookup(obj: Any, key: str = "pid") -> dict[str, dict]:
    """{"cols","rows"} or {pid: {...}} -> {pid: row dict}."""
    if not obj:
        return {}
    if isinstance(obj, dict) and "cols" in obj:
        df = frame_rows(obj)
        if df is None or key not in df:
            return {}
        return {str(r[key]): r for r in df.to_dict("records") if r.get(key) is not None}
    if isinstance(obj, dict):
        return {str(k): v for k, v in obj.items() if isinstance(v, dict)}
    return {}


def leaderboard(name: str, season: int, id_cols=("player_id", "id")) -> dict[str, dict]:
    """A cached Savant leaderboard as {pid: row} (builder A's cache; no network)."""
    try:
        from oddsmarkets.baseball.sources import savant
        df = savant.leaderboard(None, name, season)
    except Exception:                                            # noqa: BLE001
        df = None
    if df is None or not len(df):
        return {}
    idc = next((c for c in id_cols if c in df), None)
    if not idc:
        return {}
    out = {}
    for r in df.to_dict("records"):
        try:
            out[str(int(r[idc]))] = r
        except (TypeError, ValueError):
            continue
    return out


def pos_of(ctx: SeasonContext, pid: str, war_pos: Any = None) -> str | None:
    if war_pos is not None and not (isinstance(war_pos, float) and np.isnan(war_pos)):
        try:
            return POS_NAME.get(int(war_pos), str(war_pos))
        except (TypeError, ValueError):
            s = str(war_pos)
            return s if s and s != "nan" else None
    p = (ctx.players.get(pid) or {}).get("pos")
    return p or None


def finish(ctx: SeasonContext, rows: dict[str, dict], metrics: list[dict], reference: list[str], role_of: dict[str, str],
           floors: dict[str, float]) -> dict:
    """Percentiles (on raw values, shrunk for placement) then rounding; returns the shrinkage targets."""
    means = an.add_percentiles(rows, metrics, reference, role_of, floors, ctx.level)
    for r in rows.values():
        r["values"] = an.round_values(r["values"], metrics)
        r["pct"] = {k: v for k, v in r["pct"].items() if r["values"].get(k) is not None}
        r["pct_role"] = {k: v for k, v in r["pct_role"].items() if r["values"].get(k) is not None}
    return means


def safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:                                            # noqa: BLE001
        return default


def g(d: dict | None, k: str) -> float | None:
    return an.fnum((d or {}).get(k)) if d else None


def season_meta(ctx: SeasonContext, extra: dict | None = None) -> dict:
    return {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase,
            "team_games": ctx.team_games(), "model_errors": dict(ctx.model_errors), **(extra or {})}
