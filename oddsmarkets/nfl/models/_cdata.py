"""
Builder C's data access: games, team alignment and compact per-game unit tables, read from what builders A and B
publish (store.json, nflverse parquet mirrors, canon, models/_io.py) with fallbacks so the models also run on synthetic
inputs and in CI.

Games frame (one row per game; `games_frame`)
    game_id, season, week, gtype (REG/WC/DIV/CON/SB), date (datetime64), home, away, hs, as_ (float, NaN unplayed),
    played (bool), neutral (bool), roof, temp, wind, div_game, home_qb, away_qb, home_coach, away_coach,
    line (market expected home margin = "home favoured by"; NaN without a line), total_line, ml_home, ml_away,
    overtime.
    Sources, first that has the season: the per-season store (docs/gridiron/data/<S>/store.json, builder A), else the
    nflverse schedules mirror (<raw>/raw/schedules/games.parquet). The store's `lines.spread_home` sign is detected
    from the data (corr with the margin; ESPN/DraftKings convention is negative = home favoured, nflverse's
    `spread_line` is positive = home favoured) and normalised to `line`.

Unit table (one row per game x offence team x passer; `unit_rows`, cached as parquet per season)
    game_id, season, week, gtype, date, off, def, home (1 if off is the home side, 0 away, 0.5 neutral),
    qb (gsis id of the passer; "" for no dropbacks), pass_n, pass_epa, pass_sr, rush_n, rush_epa, rush_sr, st_epa
    pass_*: dropbacks (qb_dropback = 1: passes, sacks, scrambles; spikes excluded); rush_*: designed runs (kneels excluded);
    st_epa: the offence team's special-teams EPA net of its opponent's (kickoffs, punts, field goals, extra points; each
    play's EPA from the possession side), carried on the team's first row per game only. Rush and ST totals sit on the
    row of the game's main passer.

Drive table (`drive_rows`): game_id, season, off, def, start (yardline_100 at the drive's first scrimmage play), result
    (TD, FG, PUNT, TO, DOWNS, MISS, HALF, SAFETY, OPPTD), plays, qtr.

Everything here loads one season of play-by-play at a time and keeps only the needed columns.
"""
from __future__ import annotations

import json
import logging
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
VERSION = 1

# ── roots ───────────────────────────────────────────────────────────────────


def data_root() -> Path:
    try:
        from oddsmarkets.nfl.models import _io  # builder B
        f = getattr(_io, "data_root", None)
        if callable(f):
            return Path(f())
    except Exception:  # noqa: BLE001
        pass
    return Path(os.environ.get("GRIDIRON_DATA") or REPO / "docs" / "gridiron" / "data")


def raw_root() -> Path:
    try:
        from oddsmarkets.nfl.models import _io
        f = getattr(_io, "raw_root", None)
        if callable(f):
            return Path(f())
    except Exception:  # noqa: BLE001
        pass
    return Path(os.environ.get("GRIDIRON_RAW") or REPO / "data" / "nfl")


def cache_root() -> Path:
    try:
        from oddsmarkets.nfl.models import _io
        f = getattr(_io, "cache_root", None)
        if callable(f):
            return Path(f())
    except Exception:  # noqa: BLE001
        pass
    return Path(os.environ.get("GRIDIRON_CACHE") or raw_root() / "cache")


def c_cache() -> Path:
    p = cache_root() / "c"
    return p


FITTED = Path(__file__).with_name("fitted")


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


# ── teams / canon ────────────────────────────────────────────────────────────

# Fallback alignment (2002 realignment onward) and home-stadium coordinates, used only when canon.py is absent.
_DIVS = {
    "AFC East": ["BUF", "MIA", "NE", "NYJ"], "AFC North": ["BAL", "CIN", "CLE", "PIT"],
    "AFC South": ["HOU", "IND", "JAX", "TEN"], "AFC West": ["DEN", "KC", "LV", "LAC"],
    "NFC East": ["DAL", "NYG", "PHI", "WAS"], "NFC North": ["CHI", "DET", "GB", "MIN"],
    "NFC South": ["ATL", "CAR", "NO", "TB"], "NFC West": ["ARI", "LA", "SF", "SEA"],
}
# lat, lon, utc offset (standard time; Arizona has no DST, treated as -7 all year)
_HOME = {
    "ARI": (33.528, -112.263, -7), "ATL": (33.755, -84.401, -5), "BAL": (39.278, -76.623, -5), "BUF": (42.774, -78.787, -5),
    "CAR": (35.226, -80.853, -5), "CHI": (41.862, -87.617, -6), "CIN": (39.095, -84.516, -5), "CLE": (41.506, -81.700, -5),
    "DAL": (32.748, -97.093, -6), "DEN": (39.744, -105.020, -7), "DET": (42.340, -83.046, -5), "GB": (44.501, -88.062, -6),
    "HOU": (29.685, -95.411, -6), "IND": (39.760, -86.164, -5), "JAX": (30.324, -81.637, -5), "KC": (39.049, -94.484, -6),
    "LV": (36.091, -115.184, -8), "LAC": (33.953, -118.339, -8), "LA": (33.953, -118.339, -8), "MIA": (25.958, -80.239, -5),
    "MIN": (44.974, -93.258, -6), "NE": (42.091, -71.264, -5), "NO": (29.951, -90.081, -6), "NYG": (40.813, -74.074, -5),
    "NYJ": (40.813, -74.074, -5), "PHI": (39.901, -75.168, -5), "PIT": (40.447, -80.016, -5), "SF": (37.403, -121.970, -8),
    "SEA": (47.595, -122.332, -8), "TB": (27.976, -82.503, -5), "TEN": (36.166, -86.771, -6), "WAS": (38.908, -76.865, -5),
    # pre-relocation homes
    "OAK": (37.752, -122.201, -8), "SD": (32.783, -117.120, -8), "STL": (38.633, -90.189, -6),
}
_ALIAS_HIST = {"OAK": "LV", "SD": "LAC", "STL": "LA", "LAR": "LA", "JAC": "JAX", "WSH": "WAS"}


def franchise(abbr: str) -> str:
    """Current franchise code for any season's abbreviation (OAK -> LV, SD -> LAC, STL -> LA)."""
    a = str(abbr or "").upper()
    return _ALIAS_HIST.get(a, a)


def _canon():
    try:
        from oddsmarkets.nfl import canon  # builder A
        return canon
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=64)
def teams_for(season: int) -> dict[str, dict]:
    """{abbr: {"conference","division","lat","lon","tz"}} for the season's abbreviations."""
    out: dict[str, dict] = {}
    cn = _canon()
    if cn is not None:
        try:
            out = _teams_from_canon(cn, int(season))
        except Exception as exc:  # noqa: BLE001
            logger.info("canon teams unavailable (%s); using the fallback table", exc)
            out = {}
    if len(out) >= 32:
        return out
    out = {}
    for div, members in _DIVS.items():
        for t in members:
            abbr = t
            if t == "LV" and season < 2020:
                abbr = "OAK"
            elif t == "LAC" and season < 2017:
                abbr = "SD"
            elif t == "LA" and season < 2016:
                abbr = "STL"
            lat, lon, tz = _HOME[abbr]
            out[abbr] = {"conference": div[:3], "division": div, "lat": lat, "lon": lon, "tz": tz}
    return out


def _teams_from_canon(cn, season: int) -> dict[str, dict]:
    """Adapter over builder A's canon (tolerant of the exact function names)."""
    fn = getattr(cn, "teams_for", None) or getattr(cn, "teams", None) or getattr(cn, "teams_by_season", None)
    raw = fn(season) if callable(fn) else None
    out = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, (list, tuple)):
        items = [((r.get("abbr") or r.get("team")), r) for r in raw]
    else:
        items = []
    for abbr, v in items:
        if not abbr:
            continue
        v = v or {}
        div = v.get("division") or v.get("div")
        conf = v.get("conference") or v.get("conf") or (str(div)[:3] if div else None)
        lat = v.get("lat")
        lon = v.get("lon")
        st = v.get("stadium") if isinstance(v.get("stadium"), dict) else {}
        lat = lat if lat is not None else st.get("lat")
        lon = lon if lon is not None else st.get("lon")
        fb = _HOME.get(str(abbr).upper()) or _HOME.get(franchise(abbr))
        tz = v.get("tz") if isinstance(v.get("tz"), (int, float)) else (st.get("tz") if isinstance(st.get("tz"), (int, float)) else None)
        if tz is None and fb:
            tz = fb[2]
        if (lat is None or lon is None) and fb:
            lat, lon = fb[0], fb[1]
        if div and conf and str(div)[:3] != str(conf)[:3]:
            div = f"{conf} {div}"
        out[str(abbr)] = {"conference": str(conf), "division": str(div), "lat": lat, "lon": lon, "tz": tz}
    return out


def km(a: tuple | None, b: tuple | None) -> float:
    if not a or not b or a[0] is None or b[0] is None:
        return 0.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


# International and other neutral venues seen in nflverse `stadium` names (lat, lon, utc offset)
VENUES = {
    "wembley": (51.556, -0.280, 0), "twickenham": (51.456, -0.342, 0), "tottenham": (51.604, -0.066, 0),
    "azteca": (19.303, -99.150, -6), "allianz": (48.219, 11.625, 1), "deutsche bank": (50.069, 8.645, 1),
    "frankfurt": (50.069, 8.645, 1), "munich": (48.219, 11.625, 1), "bernab": (40.453, -3.688, 1),
    "corinthians": (-23.545, -46.474, -3), "neo qu": (-23.545, -46.474, -3), "sao paulo": (-23.545, -46.474, -3),
    "croke": (53.361, -6.251, 0), "dublin": (53.361, -6.251, 0), "melbourne": (-37.825, 144.984, 10),
    "rogers centre": (43.641, -79.389, -5), "toronto": (43.641, -79.389, -5), "olympiastadion": (52.515, 13.239, 1),
    "berlin": (52.515, 13.239, 1),
}


def venue_loc(g: dict, teams: dict) -> tuple | None:
    """(lat, lon, tz) of the game's venue: a known neutral venue by stadium name, else the home team's stadium."""
    if g.get("neutral"):
        name = str(g.get("stadium") or "").lower()
        for k, v in VENUES.items():
            if k in name:
                return v
    h = teams.get(str(g.get("home"))) or {}
    if h.get("lat") is not None:
        return (h["lat"], h["lon"], h.get("tz") or 0)
    return None


# ── games ────────────────────────────────────────────────────────────────────

GTYPES = ("REG", "WC", "DIV", "CON", "SB")
_FINAL = {"final", "post", "closed", "complete", "completed", "status_final", "f", "final/ot"}


def store_path(season: int) -> Path:
    return data_root() / str(int(season)) / "store.json"


def load_store(season: int) -> dict:
    try:
        from oddsmarkets.nfl import store as A_store  # builder A
        f = getattr(A_store, "load", None) or getattr(A_store, "load_store", None)
        if callable(f):
            s = f(int(season))
            if isinstance(s, dict) and s.get("games"):
                return s
    except Exception:  # noqa: BLE001
        pass
    return read_json(store_path(season)) or {}


def seasons_on_disk() -> list[int]:
    out = set()
    root = data_root()
    if root.exists():
        for p in root.iterdir():
            if p.is_dir() and p.name.isdigit() and (p / "store.json").exists():
                out.add(int(p.name))
    sched = schedules_path()
    if sched.exists():
        try:
            import pyarrow.parquet as pq
            col = pq.read_table(sched, columns=["season"]).column("season").to_numpy()
            out |= {int(x) for x in np.unique(col)}
        except Exception:  # noqa: BLE001
            pass
    return sorted(out)


def schedules_path() -> Path:
    for p in (raw_root() / "raw" / "schedules" / "games.parquet", raw_root() / "raw" / "schedules" / "schedules.parquet"):
        if p.exists():
            return p
    return raw_root() / "raw" / "schedules" / "games.parquet"


def _num(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _played(g: dict) -> bool:
    if g.get("hs") is None or g.get("as") is None:
        return False
    st = str(g.get("status") or "final").lower()
    return st in _FINAL or st.startswith("final") or st == "" or st == "none"


def _row_from_store(g: dict, season: int) -> dict:
    L = g.get("lines") or {}
    close = L.get("close") if isinstance(L.get("close"), dict) else {}
    # the nflverse closing line (top level) is the primary line, for one consistent source across 1999-2026;
    # ESPN's close (2017 onward) is kept separately
    sp = L.get("spread_home") if L.get("spread_home") is not None else close.get("spread_home")
    tot = L.get("total") if L.get("total") is not None else close.get("total")
    mlh = L.get("ml_home") if L.get("ml_home") is not None else close.get("ml_home")
    mla = L.get("ml_away") if L.get("ml_away") is not None else close.get("ml_away")
    stad = str(g.get("stadium") or "")
    neutral = bool(g.get("neutral")) or str(g.get("location") or "").lower() == "neutral"
    return {
        "game_id": str(g.get("game_id") or g.get("id")), "season": int(g.get("season") or season),
        "week": int(g.get("week") or 0), "gtype": str(g.get("gtype") or "REG").upper(),
        "date": g.get("date") or (str(g.get("kickoff") or "")[:10] or None), "kickoff": g.get("kickoff"),
        "home": str(g.get("home")), "away": str(g.get("away")),
        "hs": _num(g.get("hs")), "as_": _num(g.get("as")), "played": _played(g), "neutral": neutral,
        "stadium": stad, "roof": g.get("roof"), "temp": _num(g.get("temp")), "wind": _num(g.get("wind")),
        "div_game": int(bool(g.get("div_game"))), "home_qb": g.get("home_qb"), "away_qb": g.get("away_qb"),
        "home_coach": g.get("home_coach"), "away_coach": g.get("away_coach"),
        "spread_raw": _num(sp), "total_line": _num(tot), "ml_home": _num(mlh), "ml_away": _num(mla),
        "espn_spread_home": _num(close.get("spread_home")), "espn_ml_home": _num(close.get("ml_home")),
        "espn_ml_away": _num(close.get("ml_away")), "espn_total": _num(close.get("total")),
        "overtime": int(bool(g.get("overtime"))),
        "v_lat": _num(g.get("lat")), "v_lon": _num(g.get("lon")), "v_tz": g.get("tz"),
    }


def _qb_of(v) -> str | None:
    if isinstance(v, dict):
        return v.get("id") or v.get("gsis_id") or v.get("name")
    return v if v else None


def games_from_store(store: dict, season: int | None = None) -> pd.DataFrame:
    rows = []
    for g in (store.get("games") or {}).values():
        if not g:
            continue
        r = _row_from_store(g, int(season or store.get("season") or 0))
        r["home_qb"], r["away_qb"] = _qb_of(r["home_qb"]), _qb_of(r["away_qb"])
        rows.append(r)
    return _finish(pd.DataFrame(rows), source="store")


def games_from_schedules(seasons: Iterable[int] | None = None) -> pd.DataFrame:
    p = schedules_path()
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if seasons is not None:
        df = df[df["season"].isin(list(seasons))]
    if df.empty:
        return pd.DataFrame()
    g = pd.DataFrame({
        "game_id": df["game_id"].astype(str), "season": df["season"].astype(int), "week": df["week"].astype(int),
        "gtype": df["game_type"].astype(str).str.upper(), "date": df["gameday"].astype(str),
        "kickoff": (df["gameday"].astype(str) + "T" + df.get("gametime", pd.Series("13:00", index=df.index)).astype(str)),
        "home": df["home_team"].astype(str), "away": df["away_team"].astype(str),
        "hs": pd.to_numeric(df["home_score"], errors="coerce"), "as_": pd.to_numeric(df["away_score"], errors="coerce"),
        "neutral": df.get("location", pd.Series("Home", index=df.index)).astype(str).str.lower().eq("neutral"),
        "stadium": df.get("stadium", pd.Series("", index=df.index)).astype(str),
        "roof": df.get("roof"), "temp": pd.to_numeric(df.get("temp"), errors="coerce"),
        "wind": pd.to_numeric(df.get("wind"), errors="coerce"),
        "div_game": pd.to_numeric(df.get("div_game"), errors="coerce").fillna(0).astype(int),
        "home_qb": df.get("home_qb_id"), "away_qb": df.get("away_qb_id"),
        "home_coach": df.get("home_coach"), "away_coach": df.get("away_coach"),
        "spread_raw": pd.to_numeric(df.get("spread_line"), errors="coerce"),
        "total_line": pd.to_numeric(df.get("total_line"), errors="coerce"),
        "ml_home": pd.to_numeric(df.get("home_moneyline"), errors="coerce"),
        "ml_away": pd.to_numeric(df.get("away_moneyline"), errors="coerce"),
        "overtime": pd.to_numeric(df.get("overtime"), errors="coerce").fillna(0).astype(int),
    })
    g["played"] = g["hs"].notna() & g["as_"].notna()
    cn = _canon()
    sids = df.get("stadium_id", pd.Series(None, index=df.index)).astype(str).to_numpy()
    lat, lon, tz = [], [], []
    for sid in sids:
        st = None
        if cn is not None and getattr(cn, "stadium", None):
            try:
                st = cn.stadium(sid)
            except Exception:  # noqa: BLE001
                st = None
        st = st or {}
        lat.append(_num(st.get("lat")))
        lon.append(_num(st.get("lon")))
        tz.append(st.get("tz"))
    g["v_lat"], g["v_lon"], g["v_tz"] = lat, lon, tz
    return _finish(g, source="schedules", spread_positive_home=True)


def _finish(df: pd.DataFrame, source: str, spread_positive_home: bool | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["margin"] = df["hs"] - df["as_"]
    df["total"] = df["hs"] + df["as_"]
    sign = 1.0 if spread_positive_home else (spread_sign(df) if spread_positive_home is None else -1.0)
    df["line"] = sign * df["spread_raw"]
    df["source"] = source
    df = df.sort_values(["season", "date", "game_id"]).reset_index(drop=True)
    return df


def spread_sign(df: pd.DataFrame) -> float:
    """+1 when the raw spread is 'home favoured by' (positive = home favourite), -1 for the sportsbook sign."""
    m = df["played"] & df["spread_raw"].notna() & (df["spread_raw"] != 0)
    if m.sum() >= 8:
        c = np.corrcoef(df.loc[m, "spread_raw"], df.loc[m, "margin"])[0, 1]
        if np.isfinite(c):
            return 1.0 if c > 0 else -1.0
    # unplayed only: moneyline favourite agrees with the sign
    m2 = df["spread_raw"].notna() & df["ml_home"].notna() & (df["spread_raw"] != 0)
    if m2.sum():
        agree = ((df.loc[m2, "ml_home"] < 0) == (df.loc[m2, "spread_raw"] > 0)).mean()
        return 1.0 if agree >= 0.5 else -1.0
    return -1.0                                        # contract/ESPN convention: negative = home favoured


def games_frame(seasons: Iterable[int] | None = None, stores: dict[int, dict] | None = None) -> pd.DataFrame:
    """All games of the seasons: stores first (given or on disk), the nflverse schedules for the rest."""
    parts = []
    want = sorted(set(int(s) for s in seasons)) if seasons is not None else None
    covered = set()
    if stores:
        for s, st in stores.items():
            if want is None or int(s) in want:
                df = games_from_store(st, int(s))
                if not df.empty:
                    parts.append(df)
                    covered.add(int(s))
    sched_seasons = None if want is None else [s for s in want if s not in covered]
    if stores is None:
        sch = games_from_schedules(sched_seasons)
        if not sch.empty:
            parts.append(sch)
            covered |= set(int(x) for x in sch["season"].unique())
        # the current season's store carries fresher state (live status, ESPN lines) than the schedules mirror
        for s in (want or seasons_on_disk()):
            if store_path(s).exists():
                st = load_store(s)
                df = games_from_store(st, s)
                if not df.empty:
                    parts = [p[p["season"] != s] for p in parts]
                    parts.append(df)
    parts = [p for p in parts if not p.empty]
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["season", "date", "game_id"]).reset_index(drop=True)


# ── schedule context: rest, travel, time zones ───────────────────────────────

def add_context(df: pd.DataFrame) -> pd.DataFrame:
    """Adds rest_h/rest_a (days since the previous game, 21 after a season start), bye_h/a (rest >= 13), short_h/a
    (rest <= 5), km_h/km_a (venue distance from each team's home stadium), tz_h/tz_a (hours between home time zone and
    venue), intl (venue outside the US)."""
    if df.empty:
        return df
    df = df.copy()
    last: dict[tuple, pd.Timestamp] = {}
    rest_h, rest_a, kh, ka, th, ta, intl = [], [], [], [], [], [], []
    for r in df.itertuples(index=False):
        teams = teams_for(int(r.season))
        g = {"home": r.home, "neutral": bool(r.neutral), "stadium": getattr(r, "stadium", "")}
        v = venue_loc(g, teams)
        vlat, vlon = getattr(r, "v_lat", np.nan), getattr(r, "v_lon", np.nan)
        if vlat is not None and vlon is not None and np.isfinite(vlat) and np.isfinite(vlon):
            off = _tz_offset(getattr(r, "v_tz", None), r.date)
            v = (float(vlat), float(vlon), off if off is not None else (v[2] if v else 0))
        for side, rest_list, km_list, tz_list in (("home", rest_h, kh, th), ("away", rest_a, ka, ta)):
            t = getattr(r, side)
            prev = last.get((int(r.season), t))
            d = r.date
            if prev is not None and pd.notna(d):
                rest_list.append(float((d - prev).days))
            else:
                rest_list.append(21.0)
            if pd.notna(d):
                last[(int(r.season), t)] = d
            info = teams.get(t) or {}
            loc = (info.get("lat"), info.get("lon"))
            km_list.append(km(loc, v[:2]) if v else 0.0)
            tz_list.append(abs((v[2] if v else 0) - (info.get("tz") or (v[2] if v else 0))) if v else 0.0)
        intl.append(bool(v is not None and (v[1] > -50 or v[0] < 15)))
    df["rest_h"], df["rest_a"] = rest_h, rest_a
    df["bye_h"] = (df["rest_h"] >= 13) & (df["week"] > 1)
    df["bye_a"] = (df["rest_a"] >= 13) & (df["week"] > 1)
    df["short_h"] = df["rest_h"] <= 5
    df["short_a"] = df["rest_a"] <= 5
    df["km_h"], df["km_a"], df["tz_h"], df["tz_a"] = kh, ka, th, ta
    df["intl"] = intl
    return df


def _tz_offset(tz, when) -> float | None:
    """Standard-time UTC offset (hours) of an IANA zone or a number; None when unknown."""
    if tz is None or (isinstance(tz, float) and not np.isfinite(tz)):
        return None
    if isinstance(tz, (int, float)):
        return float(tz)
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        z = ZoneInfo(str(tz))
        jan = datetime(2020, 1, 15, tzinfo=z).utcoffset()
        return jan.total_seconds() / 3600.0 if jan is not None else None
    except Exception:  # noqa: BLE001
        return None


# ── play-by-play aggregates ──────────────────────────────────────────────────

PBP_COLS = ["game_id", "season", "week", "season_type", "posteam", "defteam", "home_team", "away_team", "play_type",
            "epa", "success", "qb_dropback", "qb_spike", "qb_kneel", "passer_player_id", "rusher_player_id", "id",
            "fixed_drive", "fixed_drive_result", "drive", "yardline_100", "qtr", "game_date", "special_teams_play",
            "two_point_attempt", "location"]


def pbp_path(season: int) -> Path | None:
    for p in (raw_root() / "raw" / "pbp" / f"play_by_play_{season}.parquet",
              raw_root() / "derived" / str(season) / "plays.parquet"):
        if p.exists():
            return p
    return None


def load_pbp(season: int, columns: list[str] | None = None) -> pd.DataFrame | None:
    """One season of play-by-play, only the needed columns (the mirrored parquet first, then builder A's loader)."""
    cols = columns or PBP_COLS
    p = pbp_path(season)
    if p is not None:
        import pyarrow.parquet as pq
        have = set(pq.read_schema(p).names)
        return pd.read_parquet(p, columns=[c for c in cols if c in have])
    try:
        from oddsmarkets.nfl.sources import nflverse  # builder A
        f = getattr(nflverse, "load_pbp", None)
        if callable(f):
            df = f(int(season), columns=cols)
            if df is not None and len(df):
                return df[[c for c in cols if c in df.columns]]
    except Exception:  # noqa: BLE001
        pass
    return None


def unit_rows_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    """The unit table (module docstring) from one season's play-by-play."""
    d = pbp
    if d is None or d.empty:
        return pd.DataFrame()
    st_type = d["season_type"].astype(str).str.upper() if "season_type" in d else pd.Series("REG", index=d.index)
    epa = pd.to_numeric(d["epa"], errors="coerce")
    ok = epa.notna() & d["posteam"].notna() & d["defteam"].notna()
    pt = d["play_type"].astype(str)
    drop = pd.to_numeric(d.get("qb_dropback"), errors="coerce").fillna(0) > 0
    spike = pd.to_numeric(d.get("qb_spike"), errors="coerce").fillna(0) > 0
    kneel = (pd.to_numeric(d.get("qb_kneel"), errors="coerce").fillna(0) > 0) | (pt == "qb_kneel")
    two = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) > 0
    succ = pd.to_numeric(d.get("success"), errors="coerce").fillna((epa > 0).astype(float))
    is_pass = ok & drop & ~spike & ~two & pt.isin(["pass", "run", "no_play"]) & (pt != "no_play")
    is_rush = ok & ~drop & (pt == "run") & ~kneel & ~two
    is_st = ok & pt.isin(["kickoff", "punt", "field_goal", "extra_point"])
    pid = d["id"] if "id" in d else d.get("passer_player_id")
    if pid is None:
        pid = pd.Series("", index=d.index)
    pid = pid.fillna(d.get("passer_player_id", pd.Series(None, index=d.index))).fillna("").astype(str)
    base = pd.DataFrame({"game_id": d["game_id"].astype(str), "off": d["posteam"].astype(str), "def": d["defteam"].astype(str),
                         "epa": epa, "succ": succ, "qb": pid})
    P = base[is_pass].groupby(["game_id", "off", "def", "qb"], sort=False).agg(
        pass_n=("epa", "size"), pass_epa=("epa", "sum"), pass_sr=("succ", "sum")).reset_index()
    R = base[is_rush].groupby(["game_id", "off", "def"], sort=False).agg(
        rush_n=("epa", "size"), rush_epa=("epa", "sum"), rush_sr=("succ", "sum")).reset_index()
    S = base[is_st].groupby(["game_id", "off"], sort=False)["epa"].sum()
    Sd = base[is_st].groupby(["game_id", "def"], sort=False)["epa"].sum()
    games = d.loc[ok, ["game_id", "season", "week", "home_team", "away_team"]].drop_duplicates("game_id")
    games = games.assign(gtype=st_type.loc[games.index].values)
    if "game_date" in d:
        games = games.assign(date=pd.to_datetime(d.loc[games.index, "game_date"], errors="coerce").values)
    loc = d.loc[games.index, "location"].astype(str).str.lower().values if "location" in d else np.array(["home"] * len(games))
    games = games.assign(neutral=(loc == "neutral"))
    rows = []
    Pg = {k: v for k, v in P.groupby(["game_id", "off"], sort=False)}
    Rg = R.set_index(["game_id", "off"])
    for g in games.itertuples(index=False):
        for off, de in ((g.home_team, g.away_team), (g.away_team, g.home_team)):
            home = 0.5 if g.neutral else (1.0 if off == g.home_team else 0.0)
            st = float(S.get((g.game_id, off), 0.0)) - float(Sd.get((g.game_id, off), 0.0))
            rr = Rg.loc[(g.game_id, off)] if (g.game_id, off) in Rg.index else None
            rush_n = float(rr["rush_n"]) if rr is not None else 0.0
            rush_epa = float(rr["rush_epa"]) if rr is not None else 0.0
            rush_sr = float(rr["rush_sr"]) if rr is not None else 0.0
            pp = Pg.get((g.game_id, off))
            common = {"game_id": g.game_id, "season": int(g.season), "week": int(g.week), "gtype": str(g.gtype),
                      "date": getattr(g, "date", pd.NaT), "off": off, "def": de, "home": home}
            if pp is None or pp.empty:
                rows.append({**common, "qb": "", "pass_n": 0.0, "pass_epa": 0.0, "pass_sr": 0.0, "rush_n": rush_n,
                             "rush_epa": rush_epa, "rush_sr": rush_sr, "st_epa": st})
                continue
            pp = pp.sort_values("pass_n", ascending=False)
            for k, q in enumerate(pp.itertuples(index=False)):
                rows.append({**common, "qb": q.qb, "pass_n": float(q.pass_n), "pass_epa": float(q.pass_epa),
                             "pass_sr": float(q.pass_sr), "rush_n": rush_n if k == 0 else 0.0,
                             "rush_epa": rush_epa if k == 0 else 0.0, "rush_sr": rush_sr if k == 0 else 0.0,
                             "st_epa": st if k == 0 else 0.0})
    return pd.DataFrame(rows)


_RESULT = {"touchdown": "TD", "field goal": "FG", "punt": "PUNT", "turnover": "TO", "turnover on downs": "DOWNS",
           "missed field goal": "MISS", "end of half": "HALF", "safety": "SAFETY", "opp touchdown": "OPPTD"}


def drive_rows_from_pbp(pbp: pd.DataFrame) -> pd.DataFrame:
    d = pbp
    if d is None or d.empty or "fixed_drive" not in d:
        return pd.DataFrame()
    pt = d["play_type"].astype(str)
    m = d["posteam"].notna() & d["fixed_drive"].notna() & d["yardline_100"].notna() & ~pt.isin(["kickoff"])
    x = d.loc[m, ["game_id", "season", "posteam", "defteam", "fixed_drive", "fixed_drive_result", "yardline_100", "qtr"]]
    first = x.groupby(["game_id", "fixed_drive"], sort=False).agg(
        season=("season", "first"), off=("posteam", "first"), defn=("defteam", "first"),
        start=("yardline_100", "first"), result=("fixed_drive_result", "first"), plays=("yardline_100", "size"),
        qtr=("qtr", "first")).reset_index()
    first["result"] = first["result"].astype(str).str.lower().map(_RESULT).fillna("OTHER")
    first = first.rename(columns={"defn": "def"})
    return first


def unit_rows(season: int, refresh: bool = False) -> pd.DataFrame:
    """The season's unit table, from the parquet cache when it is newer than the play-by-play."""
    path = c_cache() / f"units_{int(season)}.parquet"
    src = pbp_path(season)
    if path.exists() and not refresh and (src is None or path.stat().st_mtime >= src.stat().st_mtime):
        return pd.read_parquet(path)
    pbp = load_pbp(season)
    if pbp is None or pbp.empty:
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()
    out = unit_rows_from_pbp(pbp)
    dr = drive_rows_from_pbp(pbp)
    del pbp
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
        if not dr.empty:
            dr.to_parquet(c_cache() / f"drives_{int(season)}.parquet", index=False)
    except OSError as exc:
        logger.info("unit cache write failed: %s", exc)
    return out


def drive_rows(season: int) -> pd.DataFrame:
    path = c_cache() / f"drives_{int(season)}.parquet"
    if not path.exists():
        unit_rows(season, refresh=True)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


# ── on-field snaps (play-by-play participation) ─────────────────────────────

SCRIMMAGE = ("pass", "run", "qb_kneel", "qb_spike")
ROSTER_LEFT = frozenset({"CUT", "UFA", "RFA", "RET", "TRD", "TRT"})     # weekly-roster statuses of players gone


def onfield(season: int) -> pd.DataFrame | None:
    """Offensive and defensive scrimmage snaps per player and game, counted from the play-by-play participation
    (nflverse `pbp_participation`, merged into builder A's derived plays table: NFL Next Gen Stats to 2022, FTN from
    2023; 2016 onward, published after each season). Columns game_id, week, team, player (gsis id), side ("off" /
    "def"), snaps, team_snaps (the team's scrimmage plays on that side in the game). None when the season has no
    participation on disk. Scrimmage = pass, run, kneel, spike (penalty-only plays and special teams excluded).
    This replaces nflverse `snap_counts`, which is Pro Football Reference's data and left out for its terms."""
    p = raw_root() / "derived" / str(int(season)) / "plays.parquet"
    if not p.exists():
        return None
    import pyarrow.parquet as pq
    have = set(pq.read_schema(p).names)
    need = ["game_id", "week", "play_type", "posteam", "defteam", "part_offense_players", "part_defense_players"]
    if not set(need) <= have:
        return None
    d = pd.read_parquet(p, columns=need)
    d = d[d["play_type"].isin(SCRIMMAGE) & d["part_offense_players"].notna() & d["part_defense_players"].notna()]
    if not len(d):
        return None
    out = []
    for side, col, tcol in (("off", "part_offense_players", "posteam"), ("def", "part_defense_players", "defteam")):
        x = d[["game_id", "week", tcol, col]].rename(columns={tcol: "team", col: "player"})
        tot = x.groupby(["game_id", "team"]).size().rename("team_snaps").reset_index()
        x = x.assign(player=x["player"].astype(str).str.split(";")).explode("player")
        x["player"] = x["player"].str.strip()
        x = x[x["player"].str.len() > 0]
        g = x.groupby(["game_id", "week", "team", "player"]).size().rename("snaps").reset_index()
        out.append(g.merge(tot, on=["game_id", "team"]).assign(side=side))
    return pd.concat(out, ignore_index=True)


def roster_at_start(season: int) -> dict[str, str]:
    """{gsis_id: franchise} of the players on each club at the start of `season`: the first regular-season week of each club in
    nflverse's weekly rosters (the NFL's own roster data), statuses of players gone (cut, free agent, retired, traded)
    excluded (each club's first listed week); the season roster release when the weekly file is missing. {} when
    neither is on disk."""
    base = raw_root() / "raw"
    for p, weekly in ((base / "weekly_rosters" / f"roster_weekly_{int(season)}.parquet", True),
                      (base / "rosters" / f"roster_{int(season)}.parquet", False)):
        if not p.exists():
            continue
        try:
            import pyarrow.parquet as pq
            have = set(pq.read_schema(p).names)
            cols = [c for c in ("week", "game_type", "team", "gsis_id", "status") if c in have]
            r = pd.read_parquet(p, columns=cols)
        except Exception as exc:  # noqa: BLE001
            logger.info("roster %s: %s", p.name, exc)
            continue
        if weekly and {"week", "game_type"} <= set(r.columns):
            reg = r[r["game_type"] == "REG"]
            if not len(reg):
                continue
            first = reg.groupby("team")["week"].transform("min")      # per club (2017: TB and MIA had a week-1 bye)
            r = reg[reg["week"] == first]
        if "status" in r.columns:
            r = r[~r["status"].isin(ROSTER_LEFT)]
        r = r.dropna(subset=["gsis_id", "team"])
        return {str(g): franchise(t) for g, t in zip(r["gsis_id"], r["team"])}
    return {}


def pbp_seasons() -> list[int]:
    out = set()
    for base in (raw_root() / "raw" / "pbp",):
        if base.exists():
            for p in base.glob("play_by_play_*.parquet"):
                try:
                    out.add(int(p.stem.rsplit("_", 1)[-1]))
                except ValueError:
                    pass
    der = raw_root() / "derived"
    if der.exists():
        for p in der.iterdir():
            if p.name.isdigit() and (p / "plays.parquet").exists():
                out.add(int(p.name))
    for p in c_cache().glob("units_*.parquet") if c_cache().exists() else []:
        try:
            out.add(int(p.stem.split("_")[1]))
        except ValueError:
            pass
    return sorted(out)
