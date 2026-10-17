"""
NHL EDGE tracking (2021-22 onward) for the catalogues: skating speed and bursts, shot speed, distance skated and
zone time, read from builder A's raw EDGE files (`<raw>/edge/<season>/...`, JSON per player or a season table) or
builder A's `sources.edge` loaders. Nothing is fetched here. Missing files give {}.
"""
from __future__ import annotations

import gzip
import importlib
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

# our key -> candidate paths inside an EDGE player record (dotted; first numeric value wins)
SKATER_KEYS = {
    "edge_max_speed": ["topSkatingSpeed.imperial", "skatingSpeed.speedMax.imperial", "maxSkatingSpeed.imperial", "max_speed",
                       "topSpeed", "speedMax.imperial", "skatingSpeedDetails.maxSkatingSpeed.imperial"],
    "edge_bursts_20": ["burstsOver20", "skatingSpeed.burstsOver20.value", "bursts_20", "speedBursts20", "bursts20"],
    "edge_bursts_22": ["burstsOver22", "skatingSpeed.burstsOver22.value", "bursts_22", "speedBursts22", "bursts22"],
    "edge_shot_speed": ["topShotSpeed.imperial", "hardestShot.imperial", "shotSpeed.topShotSpeed.imperial", "max_shot_speed",
                        "hardest_shot"],
    "edge_avg_shot_speed": ["avgShotSpeed.imperial", "shotSpeed.avgShotSpeed.imperial", "avg_shot_speed"],
    "edge_distance": ["totalDistanceSkated.imperial", "distanceSkated.total.imperial", "distance_total", "skatingDistance.total.imperial"],
    "edge_oz_time": ["zoneTime.offensiveZonePctg", "offensiveZonePctg", "oz_pct", "zoneTimeDetails.offensiveZonePctg"],
}
GOALIE_KEYS = {
    "edge_hd_sv_pct": ["highDangerSavePctg", "savePctgHighDanger", "hd_sv_pct"],
    "edge_md_sv_pct": ["midRangeSavePctg", "savePctgMidRange", "md_sv_pct"],
    "edge_ld_sv_pct": ["longRangeSavePctg", "savePctgLongRange"],
}


def _get(d: Any, path: str) -> Any:
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and cur and isinstance(cur[0], dict):
            cur = cur[0].get(part)
        else:
            return None
    return cur


def _first(rec: dict, paths: list[str]) -> float | None:
    for p in paths:
        v = _get(rec, p)
        if isinstance(v, dict):
            v = v.get("value") or v.get("imperial")
        x = an.fnum(v)
        if x is not None:
            return x
    return None


def _read(p: Path) -> Any:
    try:
        if p.name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        if p.suffix == ".parquet":
            return pd.read_parquet(p)
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None


def _records(season: int, kind: str) -> dict[str, dict]:
    """{pid: record} for one season's EDGE player files (builder A's loader first, else a glob of the raw tree)."""
    out: dict[str, dict] = {}
    try:
        E = importlib.import_module("oddsmarkets.nhl.sources.edge")
        for fn in (f"load_{kind}s", f"{kind}s", "load"):
            f = getattr(E, fn, None)
            if f is None:
                continue
            try:
                r = f(season) if fn != "load" else f(season, kind)
            except TypeError:
                continue
            except Exception as exc:                             # noqa: BLE001
                logger.debug("edge.%s: %s", fn, exc)
                continue
            if isinstance(r, pd.DataFrame) and len(r):
                idc = next((c for c in ("player_id", "playerId", "pid", "id") if c in r.columns), None)
                if idc:
                    return {an.sid(x[idc]): x for x in r.to_dict("records") if an.sid(x[idc])}
            if isinstance(r, dict) and r:
                return {an.sid(k): v for k, v in r.items() if isinstance(v, dict)}
    except Exception:                                            # noqa: BLE001
        pass
    base = an.raw_root() / "edge" / str(season)
    if not base.exists():
        return out
    # builder A: <raw>/edge/<season>/{skater,goalie,team}/<id>_<game type>.json.gz (regular season = _2)
    for p in list(base.rglob("*.json")) + list(base.rglob("*.json.gz")):
        name = p.name.split(".")[0]
        parent = p.parent.name.lower()
        if parent == "team" or (kind == "skater" and "goalie" in (parent + p.name.lower())):
            continue
        if kind == "goalie" and "goalie" not in (parent + p.name.lower()):
            continue
        ident, _, gt = name.partition("_")
        if gt and gt != "2":
            continue
        rec = _read(p)
        if isinstance(rec, dict):
            pid = an.sid(rec.get("playerId") or _get(rec, "player.id") or (ident if ident.isdigit() else None))
            if pid:
                out[pid] = rec
    for p in base.rglob("*.parquet"):
        if (kind == "goalie") != ("goalie" in p.name.lower()):
            continue
        df = _read(p)
        if isinstance(df, pd.DataFrame) and len(df):
            idc = next((c for c in ("player_id", "playerId", "pid", "id") if c in df.columns), None)
            if idc:
                for x in df.to_dict("records"):
                    if an.sid(x[idc]):
                        out.setdefault(an.sid(x[idc]), x)
    return out


def skaters(ctx) -> dict[str, dict]:
    if an.start_year(ctx.season) < an.start_year(an.EDGE_FIRST):
        return {}
    recs = _records(ctx.season, "skater")
    out = {}
    for pid, rec in recs.items():
        v = {k: _first(rec, paths) for k, paths in SKATER_KEYS.items()}
        if v.get("edge_oz_time") is not None and v["edge_oz_time"] > 1:
            v["edge_oz_time"] /= 100.0
        for k in ("edge_max_speed", "edge_shot_speed", "edge_avg_shot_speed"):
            if not v.get(k):                                    # EDGE reports 0.0 when there is no tracked event
                v[k] = None
        if any(x is not None for x in v.values()):
            out[pid] = v
    return out


def goalies(ctx) -> dict[str, dict]:
    if an.start_year(ctx.season) < an.start_year(an.EDGE_FIRST):
        return {}
    out = {}
    for pid, rec in _records(ctx.season, "goalie").items():
        v = {k: _first(rec, paths) for k, paths in GOALIE_KEYS.items()}
        # NHL EDGE goalie detail: shotLocationSummary [{locationCode all | high | mid | long, savePctg, ...}]
        for row in rec.get("shotLocationSummary") or [] if isinstance(rec, dict) else []:
            code = str((row or {}).get("locationCode") or "")
            key = {"high": "edge_hd_sv_pct", "mid": "edge_md_sv_pct", "long": "edge_ld_sv_pct"}.get(code)
            if key and an.fnum(row.get("savePctg")) is not None and (an.fnum(row.get("saves")) or 0) + (an.fnum(row.get("goalsAgainst")) or 0) > 0:
                v[key] = an.fnum(row.get("savePctg"))
        if any(x is not None for x in v.values()):
            out[pid] = v
    return out


_BLOCKS: dict[int, dict] = {}


def player_block(season: int, pid: str) -> dict | None:
    """The EDGE block of a player's career file: the season's headline numbers (skaters or goalies)."""
    if season not in _BLOCKS:
        _BLOCKS.clear()

        class _C:
            pass
        c = _C()
        c.season = season
        sk = skaters(c)
        gk = goalies(c)
        _BLOCKS[season] = {**{p: v for p, v in gk.items()}, **{p: v for p, v in sk.items()}}
    v = _BLOCKS[season].get(str(pid))
    if not v:
        return None
    return {"season": season, **{k: an.rnd(x, 3) for k, x in v.items()}}
