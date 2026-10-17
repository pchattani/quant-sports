"""
Builder C's data layer: roots, the season stores as a games frame, schedule context (rest, back-to-backs, travel,
time zones), the per-team-game table the team ratings are fitted on, and canon fallbacks.

Games frame (`games_frame(seasons)`), one row per NHL game (preseason and All-Star games dropped):
    game_id (str), season (int, 20262027), date (local game date, Timestamp), start (UTC Timestamp or NaT),
    gtype "REG" / "PO", home, away, hs, as_ (final, shootout winner credited one goal as the NHL records it),
    played, ot, so (bools), reg_h, reg_a (regulation goals: the tied score when the game went past regulation),
    margin, total, goalie_h, goalie_a (starters when known), venue, neutral, and the closing line fields
    ml_home, ml_away, pl_home (home puck line, -1.5 = home favoured), pl_price_home, pl_price_away, total_line,
    over_price, under_price, ml_home_open, ml_away_open (American odds), book.
`add_context` adds rest_h / rest_a (days since the team's previous game, capped at 7; 7 for a season opener),
b2b_h / b2b_a (played the day before), km_h / km_a (great-circle km from the venue of the team's previous game to
this venue), tz_h / tz_a (time-zone hours from the previous venue to this one, signed: + = travelled east).

Team-game table (`team_games(season)`), two rows per played game, the side's perspective:
    game_id, season, date, team, opp, home (1/0), gf, ga (regulation + OT goals, no shootout),
    ev_toi (5v5 minutes), ev_xgf, ev_xga (score- and venue-adjusted 5v5 xG), ev_ff, ev_fa (5v5 unblocked attempts),
    ev_gf, ev_ga, pp_toi, pp_xgf, pp_gf (own power play), pk_toi, pk_xga, pk_ga (own penalty kill),
    xga_all, ga_all (all non-empty-net xG and goals against: the goaltending denominator), goalie (starter),
    en_gf, en_ga (empty-net goals), src ("events" | "store").
Built from builder A's derived events / stints (normalised by builder D's `analytics.context`), xG from the events'
own column when builder B has filled it, else builder D's season-fitted fallback logistic (`analytics.xgfallback`).
Without derived data the table is goals-only (src "store"): every xG and TOI column is NaN and team_strength falls
back to a goals model. Score/venue adjustment (McCurdy style): each 5v5 attempt's xG is multiplied by
0.5 / s(d, v), s the league's xG share of a side leading by d (clipped to +-3) at venue v that season, clipped to
[0.7, 1.4]; home / away inflation is therefore removed from the 5v5 rates and modelled in the game model.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).with_name("fitted")
TG_VERSION = 2


# ── roots and json ───────────────────────────────────────────────────────────

def data_root() -> Path:
    return Path(os.environ.get("RINK_DATA") or REPO / "docs" / "rink" / "data")


def raw_root() -> Path:
    return Path(os.environ.get("RINK_RAW") or REPO / "data" / "nhl")


def cache_root() -> Path:
    return Path(os.environ.get("RINK_CACHE") or raw_root() / "cache")


def c_cache() -> Path:
    return cache_root() / "c"


def read_json(path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _json_default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return str(o)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    return o


def write_json(path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_clean(obj), separators=(",", ":"), default=_json_default), encoding="utf-8")
    os.replace(tmp, path)


# ── seasons ──────────────────────────────────────────────────────────────────

def sid(start_year: int) -> int:
    return int(start_year) * 10000 + int(start_year) + 1


def start_year(season: int) -> int:
    s = int(season)
    return s // 10000 if s > 9999 else s


def prev_season(season: int) -> int:
    return sid(start_year(season) - 1)


def next_season(season: int) -> int:
    return sid(start_year(season) + 1)


def season_of_date(d) -> int:
    """The season in progress or next to start on date d: canon's rule (turns over on 1 July)."""
    d = pd.Timestamp(d)
    return sid(d.year if d.month >= 7 else d.year - 1)


def regular_games(season: int) -> int:
    """Games per team in the regular season (84 from 2026-27, 82 before; 48 in 2012-13; 56 in 2020-21)."""
    y = start_year(season)
    try:
        from oddsmarkets.nhl import canon
        for fn in ("regular_season_games", "games_per_team", "n_games"):
            f = getattr(canon, fn, None)
            if callable(f):
                v = f(season)
                if v:
                    return int(v)
    except Exception:  # noqa: BLE001
        pass
    if y == 2012:
        return 48
    if y == 2020:
        return 56
    return 84 if y >= 2026 else 82


# ── canon fallbacks ──────────────────────────────────────────────────────────

_NAMES = {
    "ANA": "Anaheim Ducks", "ARI": "Arizona Coyotes", "ATL": "Atlanta Thrashers", "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres", "CAR": "Carolina Hurricanes", "CBJ": "Columbus Blue Jackets", "CGY": "Calgary Flames",
    "CHI": "Chicago Blackhawks", "COL": "Colorado Avalanche", "DAL": "Dallas Stars", "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers", "FLA": "Florida Panthers", "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens", "NJD": "New Jersey Devils", "NSH": "Nashville Predators", "NYI": "New York Islanders",
    "NYR": "New York Rangers", "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers", "PHX": "Phoenix Coyotes",
    "PIT": "Pittsburgh Penguins", "SEA": "Seattle Kraken", "SJS": "San Jose Sharks", "STL": "St. Louis Blues",
    "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs", "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights", "WPG": "Winnipeg Jets", "WSH": "Washington Capitals",
}
# home arena: lat, lon, standard-time UTC offset (Arizona -7 all year)
ARENAS = {
    "ANA": (33.808, -117.877, -8), "ARI": (33.532, -112.261, -7), "ATL": (33.757, -84.396, -5), "BOS": (42.366, -71.062, -5),
    "BUF": (42.875, -78.876, -5), "CAR": (35.803, -78.722, -5), "CBJ": (39.969, -83.006, -5), "CGY": (51.037, -114.052, -7),
    "CHI": (41.881, -87.674, -6), "COL": (39.749, -105.008, -7), "DAL": (32.790, -96.810, -6), "DET": (42.341, -83.055, -5),
    "EDM": (53.547, -113.498, -7), "FLA": (26.158, -80.326, -5), "LAK": (34.043, -118.267, -8), "MIN": (44.945, -93.101, -6),
    "MTL": (45.496, -73.569, -5), "NJD": (40.734, -74.171, -5), "NSH": (36.159, -86.779, -6), "NYI": (40.712, -73.726, -5),
    "NYR": (40.751, -73.993, -5), "OTT": (45.297, -75.927, -5), "PHI": (39.901, -75.172, -5), "PHX": (33.532, -112.261, -7),
    "PIT": (40.439, -79.989, -5), "SEA": (47.622, -122.354, -8), "SJS": (37.333, -121.901, -8), "STL": (38.627, -90.203, -6),
    "TBL": (27.943, -82.452, -5), "TOR": (43.643, -79.379, -5), "UTA": (40.768, -111.901, -7), "VAN": (49.278, -123.109, -8),
    "VGK": (36.103, -115.178, -8), "WPG": (49.893, -97.144, -6), "WSH": (38.898, -77.021, -5),
}
FRANCHISE = {"ATL": "WPG", "PHX": "UTA", "ARI": "UTA"}      # ARI's players and hockey operations moved to Utah (2024)
# market / feed code aliases -> NHL tri-codes
ALIASES = {"LA": "LAK", "SJ": "SJS", "NJ": "NJD", "TB": "TBL", "UTAH": "UTA", "UTH": "UTA", "LV": "VGK", "LAS": "VGK",
           "VEG": "VGK", "MON": "MTL", "CAL": "CGY", "WAS": "WSH", "NAS": "NSH", "CLB": "CBJ", "CLS": "CBJ", "MAN": "WPG",
           "WIN": "WPG", "ANH": "ANA", "PHO": "ARI", "TAM": "TBL", "STLB": "STL", "NYIS": "NYI"}

_ATL_E = ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"]
_MET = ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"]


def _alignment(y: int) -> dict[str, list[str]]:
    """Fallback divisions by season start year (canon.py is the source of truth when present)."""
    if y >= 2024:
        return {"Atlantic": _ATL_E, "Metropolitan": _MET, "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
                "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"]}
    if y >= 2021:
        return {"Atlantic": _ATL_E, "Metropolitan": _MET, "Central": ["ARI", "CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG"],
                "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"]}
    if y == 2020:
        return {"North": ["CGY", "EDM", "MTL", "OTT", "TOR", "VAN", "WPG"], "East": ["BOS", "BUF", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
                "Central": ["CAR", "CBJ", "CHI", "DAL", "DET", "FLA", "NSH", "TBL"],
                "West": ["ANA", "ARI", "COL", "LAK", "MIN", "SJS", "STL", "VGK"]}
    if y >= 2013:
        pac = ["ANA", "ARI" if y >= 2014 else "PHX", "CGY", "EDM", "LAK", "SJS", "VAN"] + (["VGK"] if y >= 2017 else [])
        return {"Atlantic": _ATL_E, "Metropolitan": _MET, "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "WPG"], "Pacific": pac}
    return {"Atlantic": ["NJD", "NYI", "NYR", "PHI", "PIT"], "Northeast": ["BOS", "BUF", "MTL", "OTT", "TOR"],
            "Southeast": ["CAR", "FLA", "TBL", "WSH", "WPG" if y >= 2011 else "ATL"],
            "Central": ["CBJ", "CHI", "DET", "NSH", "STL"], "Northwest": ["CGY", "COL", "EDM", "MIN", "VAN"],
            "Pacific": ["ANA", "DAL", "LAK", "PHX", "SJS"]}


def _conf_of_div(div: str, y: int) -> str:
    if y == 2020:
        return div                     # 2020-21: four divisions, no conferences (each division its own bracket)
    return "Eastern" if div in ("Atlantic", "Metropolitan", "Northeast", "Southeast") else "Western"


def _canon():
    try:
        from oddsmarkets.nhl import canon
        return canon
    except Exception:  # noqa: BLE001
        return None


def teams_for(season: int) -> dict[str, dict]:
    """{abbr: {"name","division","conference","lat","lon","tz"}}: canon when present, else the fallback alignment."""
    y = start_year(season)
    out: dict[str, dict] = {}
    cn = _canon()
    if cn is not None:
        for fn in ("teams_for_season", "season_teams", "teams"):
            f = getattr(cn, fn, None)
            if f is None:
                continue
            try:
                r = f(season) if callable(f) else f
            except Exception:  # noqa: BLE001
                continue
            if isinstance(r, list):
                r = {str(v.get("abbr") or v.get("team")): v for v in r if isinstance(v, dict)}
            if isinstance(r, dict) and r and all(isinstance(v, dict) for v in r.values()):
                for k, v in r.items():
                    out[str(k)] = {"name": v.get("name") or v.get("full_name") or _NAMES.get(str(k), str(k)),
                                   "division": v.get("division") or v.get("div"),
                                   "conference": v.get("conference") or v.get("conf")}
                    loc = v.get("arena") if isinstance(v.get("arena"), dict) else v
                    lat, lon = loc.get("lat"), loc.get("lon") or loc.get("lng")
                    tz = loc.get("utc_offset", loc.get("tz_offset"))
                    if lat is not None and lon is not None:
                        out[str(k)].update({"lat": float(lat), "lon": float(lon)})
                    if isinstance(tz, (int, float)):
                        out[str(k)]["tz"] = float(tz)
                break
    if not out or not all(v.get("division") for v in out.values()):
        out = {}
        for d, mem in _alignment(y).items():
            for t in mem:
                out[t] = {"name": _NAMES.get(t, t), "division": d, "conference": _conf_of_div(d, y)}
    for t, v in out.items():
        a = ARENAS.get(t) or ARENAS.get(FRANCHISE.get(t, t))
        if a:
            v.setdefault("lat", a[0])
            v.setdefault("lon", a[1])
            v.setdefault("tz", float(a[2]))
        if t == "ARI" and 2022 <= y <= 2023:                   # Mullett Arena, Tempe
            v["lat"], v["lon"] = 33.424, -111.933
    return out


def franchise(abbr: str) -> str:
    a = norm_code(abbr)
    return FRANCHISE.get(a, a)


def norm_code(code) -> str:
    c = str(code or "").strip().upper()
    return ALIASES.get(c, c)


def km(a: tuple | None, b: tuple | None) -> float:
    if not a or not b or a[0] is None or b[0] is None:
        return 0.0
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


# ── stores ───────────────────────────────────────────────────────────────────

def store_path(season: int) -> Path:
    return data_root() / str(int(season)) / "store.json"


_STORE: dict = {}


def load_store(season: int) -> dict:
    p = store_path(season)
    try:
        st = p.stat()
    except OSError:
        return {}
    key = (str(p), st.st_size, st.st_mtime_ns)
    if _STORE.get("key") != key:
        _STORE.clear()
        _STORE["key"] = key
        _STORE["val"] = read_json(p) or {}
    return _STORE["val"]


def seasons_on_disk() -> list[int]:
    out = set()
    for base, need in ((data_root(), "store.json"),):
        try:
            for p in base.iterdir():
                if p.is_dir() and p.name.isdigit() and len(p.name) == 8 and (p / need).exists():
                    out.add(int(p.name))
        except OSError:
            pass
    return sorted(out)


def store_games(store: dict) -> list[dict]:
    g = (store or {}).get("games") or []
    if isinstance(g, dict):
        return [dict(v, game_id=str(v.get("game_id") or k)) for k, v in g.items() if isinstance(v, dict)]
    return [dict(v, game_id=str(v.get("game_id"))) for v in g if isinstance(v, dict)]


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _gtype(g: dict) -> str:
    t = g.get("type")
    s = str(t if t is not None else "").upper()
    if s in ("2", "02", "R", "REG", "REGULAR"):
        return "REG"
    if s in ("3", "03", "P", "PO", "PLAYOFF", "PLAYOFFS", "POST"):
        return "PO"
    if s in ("1", "01", "PR", "PRE", "PRESEASON"):
        return "PRE"
    gid = str(g.get("game_id") or "")
    return {"01": "PRE", "02": "REG", "03": "PO", "04": "AS"}.get(gid[4:6], "REG")


FINAL = {"final", "off", "f", "final/ot", "final/so", "completed", "official"}


def _played(g: dict) -> bool:
    st = str(g.get("status") or "").strip().lower()
    if st in ("live", "crit", "in", "in_progress", "scheduled", "fut", "pre", "postponed", "ppd"):
        return False
    return _num(g.get("hs")) is not None and _num(g.get("as")) is not None and (st in FINAL or st == "" or st.startswith("final"))


def _side(v, side: str):
    """A two-sided field: {"home","away"} / {"h","a"} or a [home, away] list (builder A's store)."""
    if isinstance(v, dict):
        return v.get(side) if side in v else v.get(side[0])
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return v[0] if side == "home" else v[1]
    return None


def line_fields(lines: dict | None) -> dict:
    """Closing (else current) line fields from a store GAME.lines record (American odds)."""
    out = {k: None for k in ("ml_home", "ml_away", "pl_home", "pl_price_home", "pl_price_away", "total_line",
                             "over_price", "under_price", "ml_home_open", "ml_away_open", "book")}
    if not isinstance(lines, dict):
        return out
    close = lines.get("close") if isinstance(lines.get("close"), dict) else {}
    op = lines.get("open") if isinstance(lines.get("open"), dict) else {}

    def ok(k, v):
        # a close block whose puck line / total holds a price (some 2022-23 ESPN captures) falls back to the main line
        if k in ("puck_line", "spread") and isinstance(v, dict):
            h = v.get("home") if not isinstance(v.get("home"), dict) else v["home"].get("line")
            h = _num(h if h is not None else v.get("line"))
            return h is None or abs(h) <= 4.5
        if k in ("total", "over_under"):
            t = _num(v.get("line", v.get("total")) if isinstance(v, dict) else v)
            return t is None or 3.0 <= t <= 12.0
        return True

    def pick(*keys, src=None):
        for s in ([src] if src is not None else [close, lines]):
            for k in keys:
                if isinstance(s, dict) and s.get(k) is not None and ok(k, s.get(k)):
                    return s.get(k)
        return None
    ml = pick("ml")
    two = isinstance(ml, (dict, list, tuple))
    out["ml_home"] = _num(_side(ml, "home")) if two else _num(pick("ml_home", "home_ml"))
    out["ml_away"] = _num(_side(ml, "away")) if two else _num(pick("ml_away", "away_ml"))
    pl = pick("puck_line", "spread")
    if isinstance(pl, dict):
        out["pl_home"] = _num(pl.get("home") if not isinstance(pl.get("home"), dict) else pl["home"].get("line"))
        if out["pl_home"] is None:
            out["pl_home"] = _num(pl.get("line"))
        hp = pl.get("home_price", pl.get("home_odds", _side(pl.get("price"), "home")))
        ap = pl.get("away_price", pl.get("away_odds", _side(pl.get("price"), "away")))
        if isinstance(pl.get("home"), dict):
            hp = pl["home"].get("price", hp)
        if isinstance(pl.get("away"), dict):
            ap = pl["away"].get("price", ap)
        out["pl_price_home"], out["pl_price_away"] = _num(hp), _num(ap)
    else:
        out["pl_home"] = _num(pl if pl is not None else pick("puck_line_home", "spread_home"))
    tot = pick("total", "over_under")
    if isinstance(tot, dict):
        out["total_line"] = _num(tot.get("line", tot.get("total")))
        out["over_price"], out["under_price"] = _num(tot.get("over")), _num(tot.get("under"))
    else:
        out["total_line"] = _num(tot)
        out["over_price"], out["under_price"] = _num(pick("over_price", "over_odds")), _num(pick("under_price", "under_odds"))
    oml = op.get("ml") if isinstance(op, dict) else None
    out["ml_home_open"] = _num(_side(oml, "home")) if oml is not None else _num(op.get("ml_home"))
    out["ml_away_open"] = _num(_side(oml, "away")) if oml is not None else _num(op.get("ml_away"))
    out["book"] = lines.get("provider") or lines.get("book") or lines.get("src")
    return out


def _row(g: dict, season: int) -> dict:
    hs, as_ = _num(g.get("hs")), _num(g.get("as"))
    played = _played(g)
    so = bool(g.get("so")) or str(g.get("status") or "").upper().endswith("SO")
    ot = bool(g.get("ot")) or so or str(g.get("status") or "").upper().endswith("OT") or (_num(g.get("period")) or 0) > 3 and played
    if played and hs is not None and as_ is not None:
        if ot or so:
            reg_h = reg_a = min(hs, as_)
        else:
            reg_h, reg_a = hs, as_
    else:
        reg_h = reg_a = None
    date = g.get("date") or str(g.get("start") or "")[:10]
    gl = g.get("goalies") or {}
    lf = line_fields(g.get("lines"))
    return {"game_id": str(g.get("game_id")), "season": int(season), "date": pd.Timestamp(str(date)[:10]) if date else pd.NaT,
            "start": pd.Timestamp(g["start"]) if g.get("start") else pd.NaT, "gtype": _gtype(g),
            "home": norm_code(g.get("home")), "away": norm_code(g.get("away")), "hs": hs, "as_": as_, "played": played,
            "ot": bool(ot) and played, "so": bool(so) and played, "reg_h": reg_h, "reg_a": reg_a,
            "goalie_h": _gid(gl.get("home") if isinstance(gl, dict) else None),
            "goalie_a": _gid(gl.get("away") if isinstance(gl, dict) else None),
            "venue": g.get("venue"), "neutral": bool(g.get("neutral", False)), **lf}


def _gid(v):
    if isinstance(v, dict):
        v = v.get("starter") or v.get("id") or v.get("playerId")
    if v is None:
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v)


def games_from_store(store: dict, season: int) -> pd.DataFrame:
    rows = [_row(g, season) for g in store_games(store)]
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["gtype"].isin(["REG", "PO"])]
    return _finish(df)


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    for c in ("hs", "as_", "reg_h", "reg_a", "ml_home", "ml_away", "pl_home", "total_line"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["margin"] = df["hs"] - df["as_"]
    df["total"] = df["hs"] + df["as_"]
    df["played"] = df["played"].astype(bool)
    return df.sort_values(["date", "game_id"]).reset_index(drop=True)


def games_frame(seasons: Iterable[int] | None = None, stores: dict[int, dict] | None = None) -> pd.DataFrame:
    """Games of the given seasons from the stores on disk (or `stores` {season: store})."""
    if stores is not None:
        parts = [games_from_store(st, s) for s, st in stores.items() if seasons is None or s in set(seasons)]
    else:
        parts = [games_from_store(load_store(s), s) for s in (seasons if seasons is not None else seasons_on_disk())]
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=["game_id", "season", "date", "gtype", "home", "away", "hs", "as_", "played"])
    return pd.concat(parts, ignore_index=True).sort_values(["date", "game_id"]).reset_index(drop=True)


def add_context(df: pd.DataFrame) -> pd.DataFrame:
    """rest, back-to-back, travel and time-zone columns (see module doc); a team's previous game is looked up across
    the whole frame (a season opener gets rest 7, no travel)."""
    if df.empty:
        return df.assign(rest_h=[], rest_a=[], b2b_h=[], b2b_a=[], km_h=[], km_a=[], tz_h=[], tz_a=[])
    df = df.sort_values(["date", "game_id"]).reset_index(drop=True)
    tinfo: dict[int, dict] = {}
    last: dict[str, tuple] = {}            # team -> (date, venue_team, season)
    rest_h, rest_a, km_h, km_a, tz_h, tz_a = ([] for _ in range(6))
    for r in df.itertuples(index=False):
        s = int(r.season)
        if s not in tinfo:
            tinfo[s] = teams_for(s)
        T = tinfo[s]
        venue = r.home
        loc = (T.get(venue, {}).get("lat"), T.get(venue, {}).get("lon"))
        tzv = T.get(venue, {}).get("tz", -5.0)
        for team, R, K, Z in ((r.home, rest_h, km_h, tz_h), (r.away, rest_a, km_a, tz_a)):
            prev = last.get(team)
            if prev is None or prev[2] != s or pd.isna(r.date) or pd.isna(prev[0]):
                R.append(7.0)
                K.append(0.0)
                Z.append(0.0)
            else:
                d = float((r.date - prev[0]).days)
                R.append(float(min(max(d - 1.0, 0.0), 7.0)))
                pv = T.get(prev[1], {})
                K.append(km((pv.get("lat"), pv.get("lon")), loc))
                Z.append(float(tzv - pv.get("tz", tzv)))
            last[team] = (r.date, venue, s)
    out = df.copy()
    out["rest_h"], out["rest_a"] = rest_h, rest_a
    out["b2b_h"] = (out["rest_h"] == 0).astype(float)
    out["b2b_a"] = (out["rest_a"] == 0).astype(float)
    out["km_h"], out["km_a"] = km_h, km_a
    out["tz_h"], out["tz_a"] = tz_h, tz_a
    return out


# ── team-game table ──────────────────────────────────────────────────────────

TG_COLS = ["game_id", "season", "date", "team", "opp", "home", "gf", "ga", "ev_toi", "ev_xgf", "ev_xga", "ev_ff", "ev_fa",
           "ev_gf", "ev_ga", "pp_toi", "pp_xgf", "pp_gf", "pk_toi", "pk_xga", "pk_ga", "xga_all", "ga_all", "goalie",
           "en_gf", "en_ga", "src"]


def tg_from_games(g: pd.DataFrame) -> pd.DataFrame:
    """Goals-only team-game rows from a games frame (played games; regulation + OT goals, shootout goal removed)."""
    p = g[g["played"]]
    if p.empty:
        return pd.DataFrame(columns=TG_COLS)
    so = p["so"].astype(bool).to_numpy()
    hs = p["hs"].to_numpy(float) - (so & (p["hs"] > p["as_"]).to_numpy())
    as_ = p["as_"].to_numpy(float) - (so & (p["as_"] > p["hs"]).to_numpy())
    nan = np.full(len(p), np.nan)
    rows = []
    for side in (1, 0):
        rows.append(pd.DataFrame({
            "game_id": p["game_id"].to_numpy(), "season": p["season"].to_numpy(), "date": p["date"].to_numpy(),
            "team": (p["home"] if side else p["away"]).to_numpy(), "opp": (p["away"] if side else p["home"]).to_numpy(),
            "home": float(side), "gf": hs if side else as_, "ga": as_ if side else hs,
            **{c: nan for c in ("ev_toi", "ev_xgf", "ev_xga", "ev_ff", "ev_fa", "ev_gf", "ev_ga", "pp_toi", "pp_xgf", "pp_gf",
                                "pk_toi", "pk_xga", "pk_ga", "xga_all", "en_gf", "en_ga")},
            "ga_all": as_ if side else hs,
            "goalie": (p["goalie_h"] if side else p["goalie_a"]).to_numpy(), "src": "store"}))
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out[TG_COLS].sort_values(["date", "game_id", "home"], ascending=[True, True, False]).reset_index(drop=True)


def _events(season: int, games: dict) -> pd.DataFrame | None:
    """Normalised events with xG (builder D's normaliser; xG from the table, builder B, or D's fallback)."""
    path = raw_root() / "derived" / str(int(season)) / "events.parquet"
    if not path.exists():
        return None
    try:
        from oddsmarkets.nhl.analytics import context as CX
        raw = CX.read_parquet(path)
        if raw is None or raw.empty:
            return None
        ev = CX.normalise_events(raw, games)
        del raw
    except Exception as exc:  # noqa: BLE001
        logger.info("team_games: events unreadable (%s)", exc)
        return None
    if "xg" not in ev or ev["xg"].isna().all():
        xg = None
        try:
            from oddsmarkets.nhl.models import xg as XG          # builder B
            for fn in ("score_events", "predict_events", "predict"):
                f = getattr(XG, fn, None)
                if callable(f):
                    v = f(ev.assign(idx=ev["event_id"]) if "idx" not in ev and "event_id" in ev else ev)
                    xg = np.asarray(v.get("xg") if isinstance(v, pd.DataFrame) else v, float)
                    if len(xg) == len(ev) and np.isfinite(xg).any():
                        break
                    xg = None
        except Exception as exc:  # noqa: BLE001
            logger.info("team_games: builder B xg unavailable (%s)", exc)
        if xg is None:
            try:
                from oddsmarkets.nhl.analytics import xgfallback
                xg = xgfallback.score(ev)
            except Exception:  # noqa: BLE001
                xg = np.full(len(ev), np.nan)
        ev["xg"] = xg
    return ev


def _stint_toi(season: int, games: dict) -> pd.DataFrame | None:
    path = raw_root() / "derived" / str(int(season)) / "stints.parquet"
    if not path.exists():
        return None
    try:
        from oddsmarkets.nhl.analytics import context as CX
        raw = CX.read_parquet(path)
        st = CX.normalise_stints(raw, games)
        del raw
    except Exception as exc:  # noqa: BLE001
        logger.info("team_games: stints unreadable (%s)", exc)
        return None
    nh, nv = st["n_h"].to_numpy(float), st["n_v"].to_numpy(float)
    hg_in = ~np.isnan(st["hg"].to_numpy(float)) if "hg" in st else np.ones(len(st), bool)
    vg_in = ~np.isnan(st["vg"].to_numpy(float)) if "vg" in st else np.ones(len(st), bool)
    both = hg_in & vg_in
    dur = st["dur"].to_numpy(float) / 60.0
    reg = st["period"].fillna(1).to_numpy(float) <= 3 if "period" in st else np.ones(len(st), bool)
    st = pd.DataFrame({"game_id": st["game_id"].to_numpy(),
                       "ev": dur * (both & (nh == 5) & (nv == 5)),
                       "pp_h": dur * (both & (nh > nv) & (nv >= 3)), "pp_a": dur * (both & (nv > nh) & (nh >= 3)),
                       "reg": dur * reg})
    return st.groupby("game_id").sum()


def team_games_from_b_stints(season: int, g: pd.DataFrame) -> pd.DataFrame | None:
    """Team-game rows from builder B's enriched stints (`_stints.for_season`: strength per stint, xG / Fenwick / goals
    per side, score- and venue-adjusted 5v5 columns *_adj). None when B has no stints or no xG for the season."""
    try:
        from oddsmarkets.nhl.models import _stints as BS
        st = BS.for_season(int(season))
    except Exception as exc:  # noqa: BLE001
        logger.info("team_games: builder B stints unavailable (%s)", exc)
        return None
    need = {"game_id", "strength", "dur", "h_xg", "a_xg", "h_xg_adj", "a_xg_adj", "h_ff_adj", "a_ff_adj", "h_gf", "a_gf"}
    if st is None or not len(st) or not need <= set(st.columns) or float(np.nansum(st["h_xg"].to_numpy(float))) <= 0:
        return None
    sv = st["strength"].astype(str).to_numpy()
    dur = st["dur"].to_numpy(float) / 60.0
    f = {k: st[k].to_numpy(float) for k in need - {"game_id", "strength", "dur"}}
    five = sv == "5v5"
    pph, ppa = sv == "pp_h", sv == "pp_a"
    en_h, en_a, en_b = sv == "en_h", sv == "en_a", sv == "en"
    df = pd.DataFrame({
        "game_id": st["game_id"].map(lambda x: str(int(x)) if pd.notna(x) else None).to_numpy(),
        "ev_toi": dur * five, "h_ev_xg": f["h_xg_adj"] * five, "a_ev_xg": f["a_xg_adj"] * five,
        "h_ev_ff": f["h_ff_adj"] * five, "a_ev_ff": f["a_ff_adj"] * five, "h_ev_g": f["h_gf"] * five, "a_ev_g": f["a_gf"] * five,
        "pp_h_toi": dur * pph, "pp_a_toi": dur * ppa, "h_pp_xg": f["h_xg"] * pph, "a_pp_xg": f["a_xg"] * ppa,
        "h_pp_g": f["h_gf"] * pph, "a_pp_g": f["a_gf"] * ppa,
        "xga_h": f["a_xg"] * ~(en_h | en_b), "ga_h": f["a_gf"] * ~(en_h | en_b),
        "xga_a": f["h_xg"] * ~(en_a | en_b), "ga_a": f["h_gf"] * ~(en_a | en_b),
        "en_h_g": f["h_gf"] * (en_a | en_b), "en_a_g": f["a_gf"] * (en_h | en_b)}).groupby("game_id").sum()
    base = tg_from_games(g)
    if base.empty:
        return None
    A = df.reindex(base["game_id"].astype(str))
    have = A["ev_toi"].notna().to_numpy() & (A["ev_toi"].fillna(0).to_numpy() > 10)
    A = A.fillna(0.0)
    ih = base["home"].to_numpy() == 1
    pick = lambda hcol, acol: np.where(ih, A[hcol].to_numpy(), A[acol].to_numpy())  # noqa: E731
    out = base.copy()
    out["ev_toi"] = A["ev_toi"].to_numpy()
    out["ev_xgf"], out["ev_xga"] = pick("h_ev_xg", "a_ev_xg"), pick("a_ev_xg", "h_ev_xg")
    out["ev_ff"], out["ev_fa"] = pick("h_ev_ff", "a_ev_ff"), pick("a_ev_ff", "h_ev_ff")
    out["ev_gf"], out["ev_ga"] = pick("h_ev_g", "a_ev_g"), pick("a_ev_g", "h_ev_g")
    out["pp_toi"], out["pk_toi"] = pick("pp_h_toi", "pp_a_toi"), pick("pp_a_toi", "pp_h_toi")
    out["pp_xgf"], out["pp_gf"] = pick("h_pp_xg", "a_pp_xg"), pick("h_pp_g", "a_pp_g")
    out["pk_xga"], out["pk_ga"] = pick("a_pp_xg", "h_pp_xg"), pick("a_pp_g", "h_pp_g")
    out["xga_all"], out["ga_all"] = pick("xga_h", "xga_a"), pick("ga_h", "ga_a")
    out["en_gf"], out["en_ga"] = pick("en_h_g", "en_a_g"), pick("en_a_g", "en_h_g")
    cols = ["ev_toi", "ev_xgf", "ev_xga", "ev_ff", "ev_fa", "ev_gf", "ev_ga", "pp_toi", "pp_xgf", "pp_gf", "pk_toi", "pk_xga",
            "pk_ga", "xga_all", "en_gf", "en_ga"]
    out.loc[~have, cols] = np.nan
    out.loc[~have, "ga_all"] = out.loc[~have, "ga"]
    out["src"] = np.where(have, "events", "store")
    return _no_zero_xg(out[TG_COLS])


def team_games_from_events(season: int, g: pd.DataFrame, games: dict) -> pd.DataFrame | None:
    ev = _events(season, games)
    if ev is None or ev.empty:
        return None
    toi = _stint_toi(season, games)
    fen = ev["type"].isin(["GOAL", "SHOT", "MISS"]).to_numpy()
    e = ev.loc[fen, ["game_id", "team", "is_home", "type", "st", "state", "score_diff", "xg"]].copy()
    del ev
    e = e[e["is_home"].notna()]
    e["goal"] = (e["type"] == "GOAL").astype(float)
    e["xg"] = e["xg"].fillna(0.0)
    e["is5"] = (e["state"] == "5v5")
    # score/venue adjustment from the season's own 5v5 xG shares
    d = e["score_diff"].fillna(0).clip(-3, 3).astype(int).to_numpy()
    h = e["is_home"].to_numpy(int)
    m5 = e["is5"].to_numpy()
    rate = np.zeros((7, 2))
    np.add.at(rate, (d[m5] + 3, h[m5]), e["xg"].to_numpy()[m5])
    share = rate / np.maximum(rate + rate[::-1, ::-1], 1e-9)       # opponent state: (-d, 1-h)
    w = np.clip(0.5 / np.maximum(share, 1e-3), 0.7, 1.4)
    w[(rate + rate[::-1, ::-1]) < 1.0] = 1.0
    e["xg_adj"] = np.where(m5, e["xg"].to_numpy() * w[d + 3, h], e["xg"].to_numpy())
    st = e["st"].astype(str)
    agg = pd.DataFrame({
        "game_id": e["game_id"], "team": e["team"],
        "ev_xg": e["xg_adj"].where(e["is5"], 0.0), "ev_ff": e["is5"].astype(float), "ev_g": e["goal"].where(e["is5"], 0.0),
        "pp_xg": e["xg"].where(st == "PP", 0.0), "pp_g": e["goal"].where(st == "PP", 0.0),
        "ne_xg": e["xg"].where(st != "EN", 0.0), "ne_g": e["goal"].where(st != "EN", 0.0),
        "en_g": e["goal"].where(st == "EN", 0.0)}).groupby(["game_id", "team"]).sum()
    del e
    base = tg_from_games(g)
    if base.empty:
        return None
    k_for = pd.MultiIndex.from_arrays([base["game_id"], base["team"]])
    k_opp = pd.MultiIndex.from_arrays([base["game_id"], base["opp"]])
    A = agg.reindex(k_for)
    B = agg.reindex(k_opp)
    have = A["ev_ff"].notna().to_numpy() | B["ev_ff"].notna().to_numpy()
    A, B = A.fillna(0.0), B.fillna(0.0)
    out = base.copy()
    out["ev_xgf"], out["ev_xga"] = A["ev_xg"].to_numpy(), B["ev_xg"].to_numpy()
    out["ev_ff"], out["ev_fa"] = A["ev_ff"].to_numpy(), B["ev_ff"].to_numpy()
    out["ev_gf"], out["ev_ga"] = A["ev_g"].to_numpy(), B["ev_g"].to_numpy()
    out["pp_xgf"], out["pp_gf"] = A["pp_xg"].to_numpy(), A["pp_g"].to_numpy()
    out["pk_xga"], out["pk_ga"] = B["pp_xg"].to_numpy(), B["pp_g"].to_numpy()
    out["xga_all"], out["ga_all"] = B["ne_xg"].to_numpy(), B["ne_g"].to_numpy()
    out["en_gf"], out["en_ga"] = A["en_g"].to_numpy(), B["en_g"].to_numpy()
    if toi is not None and not toi.empty:
        T = toi.reindex(out["game_id"])
        ih = out["home"].to_numpy() == 1
        out["ev_toi"] = T["ev"].to_numpy()
        out["pp_toi"] = np.where(ih, T["pp_h"].to_numpy(), T["pp_a"].to_numpy())
        out["pk_toi"] = np.where(ih, T["pp_a"].to_numpy(), T["pp_h"].to_numpy())
    else:                                                       # league-typical minutes when shifts are missing
        out["ev_toi"], out["pp_toi"], out["pk_toi"] = 48.5, 4.6, 4.6
    out.loc[~have, ["ev_xgf", "ev_xga", "ev_ff", "ev_fa", "ev_gf", "ev_ga", "pp_xgf", "pp_gf", "pk_xga", "pk_ga", "xga_all",
                    "en_gf", "en_ga", "ev_toi", "pp_toi", "pk_toi"]] = np.nan
    out.loc[~have, "ga_all"] = out.loc[~have, "ga"]
    out["src"] = np.where(have, "events", "store")
    return _no_zero_xg(out[TG_COLS])


def _no_zero_xg(df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose xG columns are all zero (no xG model scored the season) are goals-only."""
    z = (df["ev_xgf"].fillna(0) + df["ev_xga"].fillna(0) + df["xga_all"].fillna(0)) <= 0
    if z.any():
        df.loc[z, ["ev_xgf", "ev_xga", "pp_xgf", "pk_xga", "xga_all"]] = np.nan
        df.loc[z, "src"] = np.where(df.loc[z, "ev_toi"].notna(), "events_no_xg", "store")
    return df


def team_games(season: int, refresh: bool = False, store: dict | None = None) -> pd.DataFrame:
    """The season's team-game table (cached as <cache>/c/tg_<season>.parquet, invalidated by the store's size, the
    derived files' mtimes and builder B's xG fit key: a refitted xG model must reach team strength)."""
    st = store if store is not None else load_store(season)
    g = games_from_store(st, season) if st else pd.DataFrame()
    if g is None or g.empty:
        return pd.DataFrame(columns=TG_COLS)
    der = raw_root() / "derived" / str(int(season))
    sig = [TG_VERSION, int(g["played"].sum())]
    for f in ("events.parquet", "stints.parquet"):
        try:
            sig.append(int((der / f).stat().st_mtime))
        except OSError:
            sig.append(0)
    try:
        from oddsmarkets.nhl.models import xg as XG          # builder B
        sig.append(str((XG.current_fit() or {}).get("key")))
    except Exception:  # noqa: BLE001
        sig.append(None)
    path = c_cache() / f"tg_{int(season)}.parquet"
    meta = c_cache() / f"tg_{int(season)}.json"
    if not refresh and store is None and path.exists() and (read_json(meta) or {}).get("sig") == sig:
        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:  # noqa: BLE001
            pass
    games = {r["game_id"]: {"home": r["home"], "away": r["away"]} for r in g[["game_id", "home", "away"]].to_dict("records")}
    df = team_games_from_b_stints(season, g)
    if df is None:
        df = team_games_from_events(season, g, games)
    if df is None:
        df = tg_from_games(g)
    if store is None:
        try:
            c_cache().mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
            write_json(meta, {"sig": sig})
        except Exception as exc:  # noqa: BLE001
            logger.info("team_games cache write failed: %s", exc)
    return df


def completed(seasons) -> list[int]:
    """The seasons before the current one (canon.current_season): the ones the season-odds calibration scores."""
    from oddsmarkets.nhl import canon
    cur = int(canon.current_season())
    return [int(s) for s in seasons if int(s) < cur]
