"""
History (data/<L>/history.json) and the Retrosheet-era part of the career files.

Builder C's history model: player-seasons from 1908 (Retrosheet event files; seasons after the last Retrosheet
year from the Statcast PA table), batting by each season's own linear weights, the era-adjusted wRC+-style index
(league = that season, not park-adjusted) and RA9- for pitchers, Bullpen WAR (fielding a Lahman range-factor proxy
before Statcast); careers summed and all-time leaderboards.

Every payload built from Retrosheet carries the required notice verbatim in meta.retrosheet_notice.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an

STATCAST_FROM = 2015


def notice_meta() -> dict:
    try:
        from oddsmarkets.baseball.sources import retrosheet
        notice = getattr(retrosheet, "NOTICE", None) or an.RETRO_NOTICE
    except Exception:                                            # noqa: BLE001
        notice = an.RETRO_NOTICE
    return {"retrosheet_notice": notice, "attribution": [an.CHADWICK_ATTRIBUTION, an.LAHMAN_ATTRIBUTION]}


def season_rows(level: str = "mlb") -> tuple[pd.DataFrame, pd.DataFrame]:
    from oddsmarkets.baseball.models import history as H
    return H.season_rows(level, people=an.load_people())


def build(level: str, rows: tuple[pd.DataFrame, pd.DataFrame] | None = None, n: int = 50) -> dict:
    from oddsmarkets.baseball.models import history as H
    b, p = rows if rows is not None else season_rows(level)
    if not len(b) and not len(p):
        return {"ok": False, "reason": "no Retrosheet or Statcast seasons on this machine", "level": level, "meta": notice_meta()}
    people = an.load_people()
    names = {pid: (v or {}).get("name") for pid, v in people.items()}
    try:
        from oddsmarkets.baseball.models import _c
        maps = _c.retro_maps(people)
        names.update(dict(maps.get("name") or {}))
    except Exception:                                            # noqa: BLE001
        pass
    car = H.careers(b, p, names)
    leaders = H.leaderboards(car, n)
    r2m = {str(v.get("retro")): pid for pid, v in people.items() if isinstance(v, dict) and v.get("retro") and not str(pid).startswith("r:")}
    leaders = {k: _relink(v, r2m, names) for k, v in leaders.items()}
    aw = _all_war(car, n, r2m, names)
    if aw is not None:
        leaders["all_war"] = aw
    era = _era(b, p)
    seasons = sorted(set(b["season"].astype(int))) if len(b) else []
    return {"ok": True, "level": level, "updated_at": an.now(), "meta": notice_meta(), "seasons": seasons,
            "first": seasons[0] if seasons else None, "last": seasons[-1] if seasons else None, "leaders": leaders, "era": era,
            "n_batters": int(len(car.get("batters", []))), "n_pitchers": int(len(car.get("pitchers", []))),
            "rules": {"min_pa_rate": H.MIN_PA_RATE, "min_outs_rate": H.MIN_OUTS_RATE},
            "sources": {"retrosheet": [s for s in seasons if s < STATCAST_FROM or s not in set(an.pitch_seasons(level))],
                        "statcast": [s for s in seasons if s in set(an.pitch_seasons(level))]}}


def _pid(pid: str, r2m: dict) -> str:
    """A Retrosheet-only id "r:<retro>" mapped to the MLBAM pid when the crosswalk knows it."""
    s = str(pid)
    return r2m.get(s[2:], s) if s.startswith("r:") else s


def _relink(board: dict, r2m: dict, names: dict) -> dict:
    """Leaderboard rows with MLBAM pids where people.json maps the Retrosheet id, and a filled name column."""
    cols = list(board.get("cols") or [])
    if "pid" not in cols:
        return board
    i = cols.index("pid")
    if "name" not in cols:
        cols.append("name")
    j = cols.index("name")
    rows = []
    for r in board.get("rows") or []:
        r = list(r) + [None] * (len(cols) - len(r))
        old = str(r[i])
        r[i] = _pid(old, r2m)
        r[j] = r[j] or names.get(r[i]) or names.get(old) or names.get(old[2:] if old.startswith("r:") else old)
        rows.append(r)
    return {"cols": cols, "rows": rows}


def _all_war(car: dict, n: int, r2m: dict, names: dict) -> dict | None:
    """All-time WAR board with each player's first and last season, PA and innings."""
    t = car.get("total")
    if t is None or not len(t):
        return None
    B, P = car.get("batters"), car.get("pitchers")
    top = t.sort_values("war", ascending=False).head(n)
    rows = []
    for pid, r in top.iterrows():
        fb = B.loc[pid] if B is not None and pid in B.index else None
        fp = P.loc[pid] if P is not None and pid in P.index else None
        firsts = [int(x["first"]) for x in (fb, fp) if x is not None and pd.notna(x.get("first"))]
        lasts = [int(x["last"]) for x in (fb, fp) if x is not None and pd.notna(x.get("last"))]
        q = _pid(pid, r2m)
        rows.append([q, names.get(q) or names.get(str(pid)) or r.get("name"), _v(r.get("war")), _v(r.get("war_bat")), _v(r.get("war_pit")),
                     min(firsts) if firsts else None, max(lasts) if lasts else None,
                     _v(fb.get("pa")) if fb is not None else 0, _v(fp.get("ip")) if fp is not None else 0])
    return {"cols": ["pid", "name", "war", "war_bat", "war_pit", "first", "last", "pa", "ip"], "rows": rows}


def _era(b: pd.DataFrame, p: pd.DataFrame) -> list:
    """Per season: league runs per PA, PA, HR per PA, K and BB rates, RA9 (the run environment)."""
    if not len(b):
        return []
    g = b.groupby("season")
    t = pd.DataFrame({"pa": g["pa"].sum(), "hr": g["hr"].sum() if "hr" in b else 0, "k": g["k"].sum() if "k" in b else 0,
                      "bb": g["bb"].sum() if "bb" in b else 0, "lg_rpa": g["lg_rpa"].first() if "lg_rpa" in b else np.nan})
    if len(p) and "lg_ra9" in p:
        t["lg_ra9"] = p.groupby("season")["lg_ra9"].first()
    out = []
    for s, r in t.iterrows():
        out.append([int(s), int(r["pa"]), an.rnd(r["lg_rpa"], 4), an.rnd(an.div(r["hr"], r["pa"]), 4), an.rnd(an.div(r["k"], r["pa"]), 4),
                    an.rnd(an.div(r["bb"], r["pa"]), 4), an.rnd(r.get("lg_ra9"), 3)])
    return out


ERA_COLS = ["season", "pa", "runs_per_pa", "hr_pa", "k_pct", "bb_pct", "ra9"]
BAT_KEYS = ["season", "pa", "ab", "h", "b2", "b3", "hr", "bb", "k", "woba", "wrc_plus", "wraa", "war"]
PIT_KEYS = ["season", "games", "outs", "bf", "runs", "k", "bb", "hr", "ra9", "ra9_minus", "war"]


def player_history(rows: tuple[pd.DataFrame, pd.DataFrame], pids: set[str] | None = None, before: int | None = STATCAST_FROM) -> dict[str, dict]:
    """{pid: {"batting": [[...BAT_KEYS]], "pitching": [[...PIT_KEYS]]}} for seasons before `before` (the Retrosheet era)."""
    b, p = rows
    out: dict[str, dict] = {}
    for kind, df, keys in (("batting", b, BAT_KEYS), ("pitching", p, PIT_KEYS)):
        if df is None or not len(df):
            continue
        d = df[df["season"] < before] if before else df
        if pids is not None:
            d = d[d.index.isin(list(pids))]
        if not len(d):
            continue
        d = d.copy()
        if kind == "batting" and "wrc_plus" not in d and {"wraa", "lg_rpa", "pa"} <= set(d.columns):
            d["wrc_plus"] = 100 * (d["wraa"] / d["pa"].replace(0, np.nan) + d["lg_rpa"]) / d["lg_rpa"]
        if kind == "pitching":
            if "ra9" not in d and {"runs", "outs"} <= set(d.columns):
                d["ra9"] = 27 * d["runs"] / d["outs"].replace(0, np.nan)
            if "ra9_minus" not in d and "lg_ra9" in d:
                d["ra9_minus"] = 100 * d["ra9"] / d["lg_ra9"]
        for pid, r in zip(d.index, d.to_dict("records")):
            out.setdefault(str(pid), {}).setdefault(kind, []).append([_v(r.get(k)) for k in keys])
    for v in out.values():
        for k in v:
            v[k].sort(key=lambda x: x[0] or 0)
    return out


def _v(x: Any):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else round(float(x), 3)
    return x
