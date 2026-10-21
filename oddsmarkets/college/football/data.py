"""
Season inputs for the football models: game frames from the season stores, team and conference tables,
and the model cache (CAMPUS_CACHE). Read-only on the stores (`store.load`, atomic replace by the backfill).

Cache keys never contain absolute paths: they are built from the season, a model version and an md5 of the
input file's bytes (or of the store's game results), so a cache restored on another machine still hits.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.college import store

LEVEL = "cfb"
# Seasons whose stored lines fail the sign check and are left out of every comparison with the market:
# ESPN's 2012 "consensus" spreads correlate 0.01 with the final margin (2013: -0.75; the magnitude is plausible,
# |spread| v |margin| 0.54, but the side is not), so the favourite cannot be trusted.
UNRELIABLE_LINES = {2012: "ESPN's 2012 consensus spreads fail the sign check (correlation with the margin 0.01, "
                          "-0.70 to -0.75 in every other season); 2012 lines are not used"}
INDEPENDENT = "18"
NOTRE_DAME = "87"
# Power conferences by season (Big East an automatic-qualifier conference through 2012, Pac-12 through 2023)
_POWER = {"8": (2001, 9999), "5": (2001, 9999), "4": (2001, 9999), "1": (2001, 9999), "9": (2001, 2023),
          "10": (2001, 2012)}


def is_power(conf: str | None, season: int, tid: str | None = None) -> bool:
    if tid == NOTRE_DAME:
        return True
    a, b = _POWER.get(str(conf), (0, -1))
    return a <= int(season) <= b


# ── time helpers ────────────────────────────────────────────────────────────

def us_day(iso: str | None) -> str | None:
    """The US calendar day of a UTC kickoff (UTC - 8 h: a 7 pm Hawaii kickoff at 05:00Z stays on Saturday)."""
    if not iso:
        return None
    try:
        t = datetime.strptime(str(iso)[:19].replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            t = datetime.strptime(str(iso)[:16], "%Y-%m-%dT%H:%M")
        except ValueError:
            return str(iso)[:10]
    return (t - timedelta(hours=8)).strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── stores (memoised per file signature) ────────────────────────────────────

_MEMO: dict[Any, Any] = {}


def _sig(p: Path) -> tuple:
    try:
        st = p.stat()
        return (st.st_size, int(st.st_mtime))
    except OSError:
        return (0, 0)


def load_store(season: int) -> dict:
    p = store.store_path(LEVEL, season)
    k = ("store", int(season), str(store.paths()["stores"]), _sig(p))
    if k not in _MEMO:
        for kk in [kk for kk in _MEMO if kk[0] == "store" and kk[1] == int(season)]:
            _MEMO.pop(kk, None)
        _MEMO[k] = store.load(LEVEL, season)
    return _MEMO[k]


def load_plays_raw(season: int) -> dict:
    p = store.plays_path(season)
    k = ("plays", int(season), str(store.paths()["raw"]), _sig(p))
    if k not in _MEMO:
        for kk in [kk for kk in _MEMO if kk[0] == "plays" and kk[1] == int(season)]:
            _MEMO.pop(kk, None)
        _MEMO[k] = store.load_plays(season)
    return _MEMO[k]


def clear_memo() -> None:
    _MEMO.clear()


def seasons_available() -> list[int]:
    return store.seasons_on_disk(LEVEL)


def plays_seasons() -> list[int]:
    d = store.paths()["raw"] / "cfb" / "plays"
    if not d.exists():
        return []
    return sorted(int(p.name.split(".")[0]) for p in d.glob("*.json.gz") if p.name.split(".")[0].isdigit())


def file_md5(p: Path) -> str:
    h = hashlib.md5()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "missing"
    return h.hexdigest()[:16]


def results_key(season: int, st: dict | None = None) -> str:
    """A content key of a season's results and lines (what the ratings and backtest depend on)."""
    st = st if st is not None else load_store(season)
    rows = sorted((gid, g.get("status"), g.get("hs"), g.get("as"), g.get("home"), g.get("away"), g.get("date"),
                   (g.get("odds") or {}).get("spread_home"), (g.get("odds") or {}).get("total"),
                   (g.get("odds") or {}).get("ml_home"), bool(g.get("box")))
                  for gid, g in (st.get("games") or {}).items())
    mem = sorted((t, v.get("member"), v.get("conference"), v.get("division")) for t, v in (st.get("teams") or {}).items())
    return hashlib.md5(json.dumps([rows, mem], default=str).encode()).hexdigest()[:16]


# ── cache ───────────────────────────────────────────────────────────────────

def cache_dir(*parts: str) -> Path:
    d = store.paths()["cache"] / "cfb"
    for p in parts:
        d = d / p
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_get(name: str, key: str) -> Any:
    p = cache_dir() / f"{name}.pkl.gz"
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rb") as fh:
            obj = pickle.load(fh)
        if isinstance(obj, dict) and obj.get("__key") == key:
            return obj["value"]
    except Exception:  # noqa: BLE001
        return None
    return None


def cache_put(name: str, key: str, value: Any) -> None:
    p = cache_dir() / f"{name}.pkl.gz"
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp, "wb", compresslevel=3) as fh:
        pickle.dump({"__key": key, "value": value}, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, p)


# ── frames ──────────────────────────────────────────────────────────────────

def real_team(t: Any) -> bool:
    s = str(t or "")
    return bool(s) and not s.startswith("-")


def games_frame(season: int, st: dict | None = None) -> pd.DataFrame:
    """One row per game with a real pairing: ids, day, flags, scores, closing line and moneylines, member flags."""
    st = st if st is not None else load_store(season)
    teams = st.get("teams") or {}
    rows = []
    for gid, g in (st.get("games") or {}).items():
        h, a = str(g.get("home")), str(g.get("away"))
        if not (real_team(h) and real_team(a)) or g.get("status") in ("canceled", "postponed"):
            continue
        o = g.get("odds") or {}
        th, ta = teams.get(h) or {}, teams.get(a) or {}
        rows.append({
            "gid": str(gid), "season": int(season), "date": g.get("date"), "day": us_day(g.get("date")),
            "week": g.get("week"), "stype": g.get("stype") or "reg", "round": g.get("round"), "status": g.get("status"),
            "neutral": bool(g.get("neutral")), "conf_game": bool(g.get("conf_game")), "home": h, "away": a,
            "hs": g.get("hs"), "as": g.get("as"),
            "h_member": bool(th.get("member")), "a_member": bool(ta.get("member")),
            "h_conf": th.get("conference"), "a_conf": ta.get("conference"),
            "spread_home": o.get("spread_home"), "total": o.get("total"), "ml_home": o.get("ml_home"),
            "ml_away": o.get("ml_away"), "provider": o.get("provider"), "odds_source": o.get("source"),
            "predictor": (g.get("predictor") or {}).get("home") if isinstance(g.get("predictor"), dict) else None,
            "hr": (g.get("ranks") or {}).get("home"), "ar": (g.get("ranks") or {}).get("away"),
        })
    df = pd.DataFrame(rows)
    if not len(df):
        return pd.DataFrame(columns=["gid", "season", "date", "day", "home", "away", "hs", "as", "status"])
    for c in ("hs", "as", "spread_home", "total", "ml_home", "ml_away", "predictor"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # sanity of stored lines (a few 2019-2023 core-odds rows carry moneyline-like numbers in `total`)
    df.loc[~df["total"].between(20, 110), "total"] = np.nan
    df.loc[df["spread_home"].abs() > 75, "spread_home"] = np.nan
    for c in ("ml_home", "ml_away"):
        df.loc[df[c].abs() < 100, c] = np.nan
    if int(season) in UNRELIABLE_LINES:
        df[["spread_home", "total", "ml_home", "ml_away"]] = np.nan
    df = df.sort_values(["date", "gid"], kind="mergesort").reset_index(drop=True)
    df["final"] = (df["status"] == "post") & df["hs"].notna() & df["as"].notna()
    return df


def member_ids(st: dict) -> list[str]:
    return sorted(t for t, v in (st.get("teams") or {}).items() if v.get("member"))


def conf_of(st: dict) -> dict[str, str | None]:
    return {t: v.get("conference") for t, v in (st.get("teams") or {}).items()}


def week_starts(st: dict) -> dict[str, str]:
    """{week label: start day} from the season calendar (regular-season weeks)."""
    out = {}
    for row in (st.get("meta") or {}).get("calendar") or []:
        try:
            stype, wk, _label, start, _end = row[:5]
        except (TypeError, ValueError):
            continue
        if int(stype) == 2:
            out[str(int(wk))] = str(start)[:10]
    return out


def devig(ml_home: float | None, ml_away: float | None) -> float | None:
    """Home win probability from two American moneylines, de-vigged proportionally."""
    def imp(ml):
        if ml is None or not np.isfinite(ml) or ml == 0:
            return None
        return 100.0 / (ml + 100.0) if ml > 0 else -ml / (-ml + 100.0)
    a, b = imp(ml_home), imp(ml_away)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)
