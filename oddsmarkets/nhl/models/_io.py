"""
Shared plumbing for The Quant Rink models (builder B creates; builder C imports).

* Roots: `RINK_DATA` (default docs/rink/data), `RINK_RAW` (default data/nhl) and `RINK_CACHE` (default
  data/nhl/cache); committed fits in models/fitted/ (`FITTED`).
* Seasons are NHL ids (20252026); `sid(2025)` maps a start year to the id (canon.norm_season).
* `events(season)`: builder A's `<raw>/derived/<season>/events.parquet` normalised to one canonical frame
  (EVENT_COLS below) whatever the exact column names on disk (`ALIASES`), sorted in game order, with the
  strength state (skaters / goalie in net per side), the score *before* the event, home and away teams and
  the season; cached as Parquet under the cache root keyed on the source file.
* `stints_raw(season)`: `<raw>/derived/<season>/stints.parquet` normalised (STINT_COLS); the enriched
  stint table (events attributed, xG, zone starts, score state, back-to-backs) lives in `_stints.py`.
* `store(season)`, `games(season)` (dates, teams, type) and `players(season)` (name, position) read builder A's
  `docs/rink/data/<season>/store.json` when present, else fall back to what the events show.
* JSON cache (`cached`, `cached_frame`), JSON writers, `clean`, fitted read/write (`write_fit`, `read_fit`,
  `export_fit`, `get_fit`), LightGBM helpers (text dumps, bounded in-process booster cache, cross-fitting by
  season), statistics (log-loss, AUC, calibration, Pearson, shrinkage, ridge).

Memory: one season of events in memory per call; multi-season fits stack compact float32 feature tables.
No closures hold arrays (module-level functions throughout).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).resolve().with_name("fitted")

GOAL_X = 89.0                      # goal line, feet from centre ice (attacking team shoots at +x)
BLUE_X = 25.0
TRACKING_FIRST = 20232024          # seasons before this get the arena adjustment: the home/road distance-ratio spread across
                                   # arenas (sd 0.07 in 2019-20 .. 2021-22, 0.04 in 2022-23) falls to the noise floor (~0.025) only
                                   # from 2023-24, so the 2020-21 tracking roll-out did not yet remove scorer bias (2 Oct 2026 refit)
SHOT_TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "poke", "bat",
              "between-legs", "cradle"]
UNBLOCKED = ("goal", "shot-on-goal", "missed-shot")
ATTEMPTS = UNBLOCKED + ("blocked-shot",)
EVENT_TYPES = ["faceoff", "hit", "giveaway", "takeaway", "shot-on-goal", "missed-shot", "blocked-shot", "goal",
               "penalty", "stoppage", "delayed-penalty", "period-start", "period-end", "game-end",
               "failed-shot-attempt", "shootout-complete"]
TYPE_CODE = {t: i for i, t in enumerate(EVENT_TYPES)}
SLOTS_H = [f"h{i}" for i in range(1, 7)]
SLOTS_A = [f"a{i}" for i in range(1, 7)]

EVENT_COLS = ["season", "game_id", "idx", "period", "sec", "type", "team", "home_team", "away_team", "is_home",
              "x", "y", "zone", "shot_type", "shooter", "goalie", "assist1", "assist2", "winner", "loser",
              "pen_by", "pen_drawn", "pen_min", "blocker", "hitter", *SLOTS_H, *SLOTS_A, "hg", "ag", "sk_h", "sk_a", "g_h",
              "g_a", "score_h", "score_a", "game_type", "shootout", "penalty_shot", "ord"]
STINT_COLS = ["season", "game_id", "start", "end", "dur", "period", *SLOTS_H, *SLOTS_A, "hg", "ag", "sk_h", "sk_a",
              "home_team", "away_team", "bad"]

# canonical name -> candidate names on disk (first present wins; case-insensitive)
ALIASES: dict[str, list[str]] = {
    "game_id": ["game_id", "gameid", "game"],
    "idx": ["idx", "event_idx", "sort_order", "sortorder", "event_index", "order", "seq", "event_id", "eventid"],
    "period": ["period", "period_number", "periodnumber"],
    "sec": ["sec", "game_sec", "game_seconds", "elapsed", "t", "time_elapsed"],
    "period_sec": ["period_sec", "time_in_period", "timeinperiod", "period_seconds"],
    "type": ["type", "event_type", "typedesckey", "type_desc_key", "event"],
    "team": ["team", "event_team", "team_abbrev", "owner_team", "shooting_team", "teamcode", "team_code"],
    "home_team": ["home_team", "home", "home_abbrev", "hometeam", "home_team_abbrev"],
    "away_team": ["away_team", "away", "away_abbrev", "awayteam", "away_team_abbrev"],
    "x": ["x", "x_norm", "xcoord", "x_coord", "x_adj"],
    "y": ["y", "y_norm", "ycoord", "y_coord", "y_adj"],
    "zone": ["zone", "zone_code", "zonecode"],
    "shot_type": ["shot_type", "shottype", "secondary_type"],
    "shooter": ["shooter", "shooter_id", "shooting_player", "shootingplayerid", "scoring_player", "scorer"],
    "player1": ["player1", "p1"],
    "player2": ["player2", "p2"],
    "ord": ["sort", "sort_order", "sortorder"],
    "penalty_shot": ["penalty_shot", "is_penalty_shot"],
    "bad": ["bad", "is_bad"],
    "goalie": ["goalie", "goalie_id", "goalie_in_net", "goalieinnetid", "goalie_in_net_id"],
    "assist1": ["assist1", "assist_1", "a1_player", "assist1_id", "primary_assist"],
    "assist2": ["assist2", "assist_2", "a2_player", "assist2_id", "secondary_assist"],
    "winner": ["winner", "faceoff_winner", "winning_player", "winningplayerid", "fo_winner"],
    "loser": ["loser", "faceoff_loser", "losing_player", "losingplayerid", "fo_loser"],
    "pen_by": ["pen_by", "committed_by", "committedbyplayerid", "penalty_player", "penalized", "pen_player"],
    "pen_drawn": ["pen_drawn", "drawn_by", "drawnbyplayerid", "penalty_drawn_by"],
    "pen_min": ["pen_min", "penalty_minutes", "duration", "pim", "pen_duration"],
    "blocker": ["blocker", "blocking_player", "blockingplayerid", "blocked_by"],
    "hitter": ["hitter", "hitting_player", "hittingplayerid"],
    "situation": ["situation_code", "situationcode", "sit", "situation", "strength_code", "strength"],
    "score_h": ["score_home", "home_score", "homescore", "score_h"],
    "score_a": ["score_away", "away_score", "awayscore", "score_a"],
    "hg": ["home_goalie", "hg", "home_g", "goalie_home", "home_goalie_id"],
    "ag": ["away_goalie", "ag", "away_g", "goalie_away", "away_goalie_id"],
    "start": ["start", "start_sec", "t0", "begin"],
    "end": ["end", "end_sec", "t1", "finish"],
}
for _i in range(1, 7):
    ALIASES[f"h{_i}"] = [f"home_s{_i}", f"home_sk{_i}", f"home_skater{_i}", f"home_skater_{_i}", f"home_{_i}", f"home{_i}", f"h{_i}",
                         f"home_on_{_i}", f"home_p{_i}"]
    ALIASES[f"a{_i}"] = [f"away_s{_i}", f"away_sk{_i}", f"away_skater{_i}", f"away_skater_{_i}", f"away_{_i}", f"away{_i}", f"a{_i}",
                         f"away_on_{_i}", f"away_p{_i}"]
LIST_COLS = {"home_on": SLOTS_H, "away_on": SLOTS_A, "home_skaters": SLOTS_H, "away_skaters": SLOTS_A}

TYPE_MAP = {"shot": "shot-on-goal", "sog": "shot-on-goal", "shot-on-goal": "shot-on-goal", "miss": "missed-shot",
            "missed-shot": "missed-shot", "missed": "missed-shot", "block": "blocked-shot", "blocked-shot": "blocked-shot",
            "blocked": "blocked-shot", "goal": "goal", "fac": "faceoff", "faceoff": "faceoff", "penl": "penalty",
            "penalty": "penalty", "give": "giveaway", "giveaway": "giveaway", "take": "takeaway",
            "takeaway": "takeaway", "hit": "hit", "stop": "stoppage", "stoppage": "stoppage"}


# ----------------------------------------------------------------------------- roots and seasons

def data_root() -> Path:
    return Path(os.environ.get("RINK_DATA") or (ROOT / "docs" / "rink" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("RINK_RAW") or (ROOT / "data" / "nhl"))


def cache_root() -> Path:
    return Path(os.environ.get("RINK_CACHE") or (raw_root() / "cache"))


def sid(season: int | str) -> int:
    """NHL season id, canon's convention: 20252026 stays; a start year 2025 or "2025-26" becomes 20252026."""
    t = str(season).strip()
    if "-" in t:
        y = int(t.split("-")[0])
        return y * 10000 + y + 1
    s = int(t[:8]) if len(t) >= 8 else int(t)
    if s < 10000:
        return s * 10000 + s + 1
    return s


def season_of_game(game_id: int) -> int:
    y = int(game_id) // 1_000_000
    return y * 10000 + y + 1


def game_type(game_id) -> np.ndarray:
    """2 regular season, 3 playoffs, 1 preseason (digits 5-6 of the NHL game id)."""
    g = np.asarray(game_id, dtype=np.int64)
    return (g // 10000) % 100


def derived_dir(season: int) -> Path:
    return raw_root() / "derived" / str(sid(season))


def events_path(season: int) -> Path:
    return derived_dir(season) / "events.parquet"


def stints_path(season: int) -> Path:
    return derived_dir(season) / "stints.parquet"


def store_path(season: int) -> Path:
    return data_root() / str(sid(season)) / "store.json"


def seasons_on_disk(need_stints: bool = False) -> list[int]:
    d = raw_root() / "derived"
    if not d.exists():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and p.name.isdigit() and len(p.name) == 8 and (p / "events.parquet").exists():
            if need_stints and not (p / "stints.parquet").exists():
                continue
            out.append(int(p.name))
    return sorted(out)


def completed_seasons(need_stints: bool = False) -> list[int]:
    """Seasons on disk before the current one (canon.current_season): the default fitting set of fit_b, fit_c and
    scripts/nhl_fit.py."""
    from oddsmarkets.nhl import canon
    cur = int(canon.current_season())
    return [s for s in seasons_on_disk(need_stints) if s < cur]


def season_range(seasons: Iterable[int] | None = None, need_stints: bool = False) -> list[int]:
    """The given seasons as ids (start years accepted), else every completed season on disk."""
    return sorted(sid(s) for s in (seasons if seasons is not None else completed_seasons(need_stints)))


def source_files(season: int) -> list[Path]:
    return [p for p in (events_path(season), stints_path(season), store_path(season)) if p.exists()]


# ----------------------------------------------------------------------------- parquet and normalisation

def parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.read_schema(path).names)
    except Exception:  # noqa: BLE001
        return []


def _pick(cols: list[str], cands: list[str]) -> str | None:
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def rename_canonical(df: pd.DataFrame, names: Iterable[str]) -> pd.DataFrame:
    """Rename the first matching alias of each canonical name to it (others untouched)."""
    cols = list(df.columns)
    ren = {}
    used = set()
    for canon in names:
        if canon in cols:
            used.add(canon)
            continue
        c = _pick([x for x in cols if x not in used and x not in ren], ALIASES.get(canon, [canon]))
        if c is not None and c not in ren:
            ren[c] = canon
            used.add(canon)
    df = df.rename(columns=ren)
    # list-valued on-ice columns (one list per row) expand into slots
    for lc, slots in LIST_COLS.items():
        if lc in df.columns and not all(s in df.columns for s in slots):
            vals = df[lc].tolist()
            arr = np.full((len(df), 6), np.nan)
            for i, v in enumerate(vals):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                seq = list(v)[:6]
                for j, p in enumerate(seq):
                    try:
                        arr[i, j] = float(p)
                    except (TypeError, ValueError):
                        pass
            for j, s in enumerate(slots):
                if s not in df.columns:
                    df[s] = arr[:, j]
    return df


def _num(s: pd.Series) -> np.ndarray:
    return pd.to_numeric(s, errors="coerce").to_numpy(float)


def _nullish(v) -> bool:
    return v is None or v is pd.NA or (isinstance(v, float) and v != v)


def _str(s: pd.Series) -> pd.Series:
    """Object series of str / None (pandas 3 string and categorical columns included)."""
    return pd.Series([None if _nullish(v) else str(v) for v in s.astype(object).tolist()], index=s.index, dtype=object)


def norm_type(s: pd.Series) -> pd.Series:
    t = [None if v is None else v.strip().lower().replace("_", "-").replace(" ", "-") for v in _str(s).tolist()]
    return pd.Series([TYPE_MAP.get(v, v) if v is not None else None for v in t], index=s.index, dtype=object)


def norm_shot_type(s: pd.Series) -> pd.Series:
    def f(v):
        if v is None:
            return None
        v = v.strip().lower().replace("_", "-").replace(" ", "-")
        return {"wrist-shot": "wrist", "snap-shot": "snap", "slap-shot": "slap", "tip": "tip-in", "deflection": "deflected",
                "wrap": "wrap-around", "wraparound": "wrap-around", "back": "backhand"}.get(v, v)
    return pd.Series([f(v) for v in _str(s).tolist()], index=s.index, dtype=object)


# ----------------------------------------------------------------------------- store: games and players

def read_store(season: int) -> dict:
    s = read_json(store_path(season))
    return s if isinstance(s, dict) else {}


def _games_list(store: dict) -> list[dict]:
    g = store.get("games") or []
    if isinstance(g, dict):
        out = []
        for k, v in g.items():
            if isinstance(v, dict):
                v = dict(v)
                v.setdefault("game_id", k)
                out.append(v)
        return out
    return [x for x in g if isinstance(x, dict)]


def games(season: int, ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per game: game_id, date (YYYY-MM-DD or None), home, away, game_type, venue. From the store when
    present; teams from events otherwise."""
    rows = _games_list(read_store(season))
    if rows:
        df = pd.DataFrame([{"game_id": int(r.get("game_id")), "date": (str(r.get("date"))[:10] if r.get("date") else None),
                            "home": r.get("home"), "away": r.get("away"), "venue": r.get("venue"),
                            "neutral": bool(r.get("neutral") or False)}
                           for r in rows if r.get("game_id") is not None])
    else:
        df = pd.DataFrame(columns=["game_id", "date", "home", "away", "venue", "neutral"])
    if ev is not None and len(ev):
        e = ev.drop_duplicates("game_id")[["game_id", "home_team", "away_team"]]
        df = e.rename(columns={"home_team": "home_e", "away_team": "away_e"}).merge(df, on="game_id", how="left")
        df["home"] = df["home"].where(df["home"].notna(), df["home_e"])
        df["away"] = df["away"].where(df["away"].notna(), df["away_e"])
        df = df.drop(columns=["home_e", "away_e"])
    if len(df):
        df["game_type"] = game_type(df["game_id"].to_numpy())
    else:
        df["game_type"] = []
    return df.sort_values("game_id").reset_index(drop=True)


def back_to_back(g: pd.DataFrame) -> pd.DataFrame:
    """Per game: b2b_home, b2b_away (team played the previous calendar day). Zeros when dates are unknown."""
    g = g.copy()
    g["b2b_home"] = 0.0
    g["b2b_away"] = 0.0
    if "date" not in g or g["date"].isna().all():
        return g
    d = pd.to_datetime(g["date"], errors="coerce")
    long = pd.concat([pd.DataFrame({"game_id": g["game_id"], "team": g["home"], "d": d}),
                      pd.DataFrame({"game_id": g["game_id"], "team": g["away"], "d": d})])
    long = long.dropna(subset=["d"]).sort_values(["team", "d", "game_id"])
    long["prev"] = long.groupby("team")["d"].shift(1)
    long["b2b"] = ((long["d"] - long["prev"]).dt.days == 1).astype(float)
    m = long.set_index(["game_id", "team"])["b2b"]
    m = m[~m.index.duplicated()]
    g["b2b_home"] = m.reindex(pd.MultiIndex.from_arrays([g["game_id"], g["home"]])).fillna(0.0).to_numpy()
    g["b2b_away"] = m.reindex(pd.MultiIndex.from_arrays([g["game_id"], g["away"]])).fillna(0.0).to_numpy()
    return g


POS_GROUP = {"C": "F", "L": "F", "R": "F", "LW": "F", "RW": "F", "F": "F", "W": "F", "D": "D", "G": "G"}


def players(season: int, ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """Index player id (int): name, pos, group (F/D/G). The store first; goalies and faceoff takers inferred
    from events for anyone missing (others default to F)."""
    st = read_store(season).get("players") or {}
    rows = []
    items = st.items() if isinstance(st, dict) else [(p.get("id") or p.get("player_id"), p) for p in st if isinstance(p, dict)]
    for k, v in items:
        try:
            pid = int(k)
        except (TypeError, ValueError):
            continue
        v = v or {}
        name = v.get("name") or " ".join(x for x in [v.get("first"), v.get("last")] if x) or str(pid)
        pos = str(v.get("pos") or v.get("position") or "").upper() or None
        sh = str(v.get("shoots") or v.get("shootsCatches") or "").upper()[:1] or None
        rows.append({"player_id": pid, "name": name, "pos": pos, "shoots": sh})
    df = pd.DataFrame(rows, columns=["player_id", "name", "pos", "shoots"]).drop_duplicates("player_id").set_index("player_id")
    if ev is not None and len(ev):
        gl = set(pd.unique(np.concatenate([ev["hg"].dropna().to_numpy(), ev["ag"].dropna().to_numpy(),
                                           ev["goalie"].dropna().to_numpy()])).astype(np.int64).tolist())
        fo = set(pd.unique(np.concatenate([ev["winner"].dropna().to_numpy(), ev["loser"].dropna().to_numpy()])).astype(np.int64).tolist())
        sk = set(pd.unique(ev[SLOTS_H + SLOTS_A].to_numpy().ravel()).tolist())
        sk = {int(p) for p in sk if p == p}
        add = []
        for p in (gl | fo | sk) - set(df.index):
            add.append({"player_id": p, "name": str(p), "pos": "G" if p in gl else ("C" if p in fo else None), "shoots": None})
        if add:
            df = pd.concat([df, pd.DataFrame(add).set_index("player_id")])
        miss = df["pos"].isna()
        if miss.any():
            df.loc[miss & df.index.isin(list(gl)), "pos"] = "G"
    df["group"] = df["pos"].map(lambda p: POS_GROUP.get(str(p).upper(), "F") if p else "F")
    return df


# ----------------------------------------------------------------------------- events

def _mode(s: pd.Series):
    return s.value_counts().index[0]


def _normalise_events(raw: pd.DataFrame, season: int, store_games: pd.DataFrame | None = None) -> pd.DataFrame:
    df = rename_canonical(raw, list(ALIASES))
    n = len(df)
    out = pd.DataFrame(index=range(n))
    out["season"] = np.full(n, sid(season), dtype=np.int64)
    out["game_id"] = pd.to_numeric(df["game_id"], errors="coerce").astype("int64").to_numpy()
    out["period"] = _num(df["period"]) if "period" in df else np.nan
    if "sec" in df:
        out["sec"] = _num(df["sec"])
    elif "period_sec" in df:
        ps = df["period_sec"]
        if ps.dtype == object or pd.api.types.is_string_dtype(ps):
            def mmss(v):
                try:
                    m, s = str(v).split(":")
                    return int(m) * 60 + int(s)
                except (ValueError, AttributeError):
                    return np.nan
            ps = ps.map(mmss)
        out["sec"] = (out["period"] - 1) * 1200.0 + pd.to_numeric(ps, errors="coerce").to_numpy(float)
    else:
        out["sec"] = np.nan
    out["idx"] = _num(df["idx"]) if "idx" in df else np.arange(n, dtype=float)
    out["type"] = norm_type(df["type"]).to_numpy() if "type" in df else None
    for c in ("team", "home_team", "away_team", "zone"):
        out[c] = _str(df[c]).to_numpy() if c in df else None
    if "zone" in df:
        out["zone"] = pd.Series([None if v is None else str(v)[:1].upper() for v in out["zone"].tolist()], dtype=object).to_numpy()
    out["shot_type"] = norm_shot_type(df["shot_type"]).to_numpy() if "shot_type" in df else None
    for c in ("x", "y", "shooter", "goalie", "assist1", "assist2", "winner", "loser", "pen_by", "pen_drawn", "pen_min",
              "blocker", "hitter", *SLOTS_H, *SLOTS_A, "hg", "ag"):
        out[c] = _num(df[c]) if c in df else np.nan
    # builder A's role-dependent player1 / player2: faceoff winner / loser, hitter / hittee, penalty taker / drawer,
    # blocked shot: shooter / blocker
    p1 = _num(df["player1"]) if "player1" in df else np.full(n, np.nan)
    p2 = _num(df["player2"]) if "player2" in df else np.full(n, np.nan)
    ty = out["type"].to_numpy(object)
    for col, typ, src in (("winner", "faceoff", p1), ("loser", "faceoff", p2), ("hitter", "hit", p1),
                          ("pen_by", "penalty", p1), ("pen_drawn", "penalty", p2), ("blocker", "blocked-shot", p2),
                          ("shooter", "blocked-shot", p1)):
        cur = out[col].to_numpy(float).copy()
        m = (ty == typ) & ~np.isfinite(cur) & np.isfinite(src)
        if m.any():
            cur[m] = src[m]
            out[col] = cur
    hit = out["type"] == "hit"
    out.loc[hit & out["hitter"].isna(), "hitter"] = out.loc[hit & out["hitter"].isna(), "shooter"]
    out["penalty_shot"] = (np.array([0.0 if _nullish(v) else float(bool(v)) for v in df["penalty_shot"].astype(object).tolist()])
                           if "penalty_shot" in df else np.zeros(n))
    out["ord"] = _num(df["ord"]) if "ord" in df else out["idx"].to_numpy(float)
    # teams from the store when the events lack them
    if (out["home_team"].isna().all() or out["away_team"].isna().all()) and store_games is not None and len(store_games):
        m = store_games.set_index("game_id")
        out["home_team"] = out["game_id"].map(m["home"]).to_numpy()
        out["away_team"] = out["game_id"].map(m["away"]).to_numpy()
    if out["home_team"].isna().all() and "is_home" in df:
        # home / away teams from the events' own is_home flag (the commonest team of each side in each game)
        ihs = [None if _nullish(v) else bool(v) for v in df["is_home"].astype(object).tolist()]
        tmp = pd.DataFrame({"g": out["game_id"], "t": out["team"], "h": pd.Series(ihs, dtype=object)}).dropna()
        if len(tmp):
            hm = tmp[tmp["h"] == True].groupby("g")["t"].agg(_mode)  # noqa: E712
            aw = tmp[tmp["h"] == False].groupby("g")["t"].agg(_mode)  # noqa: E712
            out["home_team"] = out["game_id"].map(hm).to_numpy()
            out["away_team"] = out["game_id"].map(aw).to_numpy()
    out["is_home"] = np.where(out["team"].isna(), np.nan, (out["team"] == out["home_team"]).astype(float))
    # strength: the situation code (away goalie, away skaters, home skaters, home goalie) when present,
    # else counts of the on-ice slots
    sk_h = np.sum(np.isfinite(out[SLOTS_H].to_numpy(float)), axis=1).astype(float)
    sk_a = np.sum(np.isfinite(out[SLOTS_A].to_numpy(float)), axis=1).astype(float)
    g_h = np.isfinite(out["hg"].to_numpy(float)).astype(float)
    g_a = np.isfinite(out["ag"].to_numpy(float)).astype(float)
    if "situation" in df:
        sc = _str(df["situation"]).map(lambda v: v if v is not None and len(v) == 4 and v.isdigit() else None)
        ok = sc.notna().to_numpy()
        if ok.any():
            code = sc[ok].astype(str)
            g_a[ok] = code.str[0].astype(float).to_numpy()
            sk_a[ok] = code.str[1].astype(float).to_numpy()
            sk_h[ok] = code.str[2].astype(float).to_numpy()
            g_h[ok] = code.str[3].astype(float).to_numpy()
    out["sk_h"], out["sk_a"], out["g_h"], out["g_a"] = sk_h, sk_a, g_h, g_a
    out["game_type"] = game_type(out["game_id"].to_numpy())
    # idx: the per-game index after sorting by (period, sec, source event index) -- the join key builders C / D use;
    # rows are then ordered by the feed's own sort order (`ord`) where present, which is what previous-event
    # features need
    out = out.sort_values(["game_id", "period", "sec", "idx"], kind="mergesort").reset_index(drop=True)
    out["idx"] = out.groupby("game_id").cumcount().astype(float)
    out = out.sort_values(["game_id", "period", "sec", "ord", "idx"], kind="mergesort").reset_index(drop=True)
    out["shootout"] = ((out["game_type"] == 2) & (out["period"] >= 5)).astype(float)
    # score before each event (shootout goals do not count)
    goal = (out["type"] == "goal").to_numpy() & (out["shootout"].to_numpy() == 0)
    gh = (goal & (out["is_home"].to_numpy() == 1)).astype(float)
    ga = (goal & (out["is_home"].to_numpy() == 0)).astype(float)
    g = out["game_id"].to_numpy()
    out["score_h"] = pd.Series(gh).groupby(g).cumsum().to_numpy() - gh
    out["score_a"] = pd.Series(ga).groupby(g).cumsum().to_numpy() - ga
    return out[EVENT_COLS]


def events(season: int, use_cache: bool = True) -> pd.DataFrame:
    """The canonical event frame for one season (empty frame when the file is missing)."""
    season = sid(season)
    src = events_path(season)
    if not src.exists():
        return pd.DataFrame(columns=EVENT_COLS)
    key = file_key(src, store_path(season), "events-3")
    path = cache_root() / "events" / f"{season}.parquet"
    meta = path.with_suffix(".key")
    if use_cache and path.exists() and meta.exists():
        try:
            if meta.read_text().strip() == key:
                return _objects(pd.read_parquet(path))
        except (OSError, ValueError):
            pass
    raw = pd.read_parquet(src)
    g = games(season)
    out = _normalise_events(raw, season, g)
    del raw
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        f = out.copy()
        for c in f.columns:
            if f[c].dtype == np.float64 and c not in ("sec",):
                f[c] = f[c].astype("float64")
        f.to_parquet(path, index=False)
        meta.write_text(key)
    except Exception:  # noqa: BLE001
        pass
    return out


def _objects(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        dt = df[c].dtype
        if isinstance(dt, pd.CategoricalDtype) or (dt != object and pd.api.types.is_string_dtype(dt)):
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def stints_raw(season: int) -> pd.DataFrame:
    """Builder A's stints normalised: game_id, start, end, dur, period, h1..h6, a1..a6, hg, ag, sk_h, sk_a,
    home_team, away_team (teams may be None)."""
    season = sid(season)
    src = stints_path(season)
    if not src.exists():
        return pd.DataFrame(columns=STINT_COLS)
    raw = rename_canonical(pd.read_parquet(src), list(ALIASES))
    n = len(raw)
    out = pd.DataFrame(index=range(n))
    out["season"] = season
    out["game_id"] = pd.to_numeric(raw["game_id"], errors="coerce").astype("int64").to_numpy()
    out["start"] = _num(raw["start"])
    out["end"] = _num(raw["end"])
    out["dur"] = out["end"] - out["start"]
    out["period"] = _num(raw["period"]) if "period" in raw else np.floor(out["start"] / 1200.0) + 1
    for c in (*SLOTS_H, *SLOTS_A, "hg", "ag"):
        out[c] = _num(raw[c]) if c in raw else np.nan
    out["sk_h"] = np.sum(np.isfinite(out[SLOTS_H].to_numpy(float)), axis=1).astype(float)
    out["sk_a"] = np.sum(np.isfinite(out[SLOTS_A].to_numpy(float)), axis=1).astype(float)
    for c in ("home_team", "away_team"):
        out[c] = _str(raw[c]).to_numpy() if c in raw else None
    out["bad"] = (np.array([0.0 if _nullish(v) else float(bool(v)) for v in raw["bad"].astype(object).tolist()])
                  if "bad" in raw else np.zeros(n))
    out = out[np.isfinite(out["dur"]) & (out["dur"] > 0)]
    return out.sort_values(["game_id", "start"], kind="mergesort").reset_index(drop=True)


# ----------------------------------------------------------------------------- JSON / cache

def resolve(path: Path) -> Path:
    p = Path(path)
    gz = p.with_name(p.name + ".gz")
    if gz.exists() and (not p.exists() or gz.stat().st_mtime_ns >= p.stat().st_mtime_ns):
        return gz
    return p


def read_json(path: Path) -> Any:
    p = resolve(path)
    try:
        if p.name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def clean(x: Any, nd: int = 4) -> Any:
    """Round floats, map non-finite to None, recurse into dicts/lists (for payloads)."""
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return [clean(v, nd) for v in x.tolist()]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x


def write_json(path: Path, obj: Any, gz: bool = False, nd: int | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(clean(obj, nd) if nd else clean(obj, 8), separators=(",", ":"), default=_json_default)
    if gz or p.name.endswith(".gz"):
        p = p if p.name.endswith(".gz") else p.with_name(p.name + ".gz")
        with gzip.open(p, "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(txt)
    else:
        p.write_text(txt, encoding="utf-8")
    return p


def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            try:
                st = p.stat()
                h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
            except OSError:
                h.update(f"{p}|missing".encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True, gz: bool = False) -> Any:
    """JSON cache under cache_root()/kind/name.json[.gz], invalidated by `key`. Never raises on IO."""
    path = cache_root() / kind / (f"{name}.json.gz" if gz else f"{name}.json")
    if use_cache and resolve(path).exists():
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    try:
        write_json(path, {"key": key, "result": out}, gz=gz)
    except (OSError, TypeError, ValueError):
        pass
    return out


def cached_frame(kind: str, name: str, key: str, build: Callable[[], pd.DataFrame], use_cache: bool = True) -> pd.DataFrame:
    """Parquet cache for per-season derived tables, invalidated by `key`."""
    d = cache_root() / kind
    path, meta = d / f"{name}.parquet", d / f"{name}.key"
    if use_cache and path.exists() and meta.exists():
        try:
            if meta.read_text().strip() == key:
                return _objects(pd.read_parquet(path))
        except (OSError, ValueError):
            pass
    out = build()
    try:
        d.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
        meta.write_text(key)
    except Exception:  # noqa: BLE001
        pass
    return out


def write_fit(name: str, obj: Any, gz: bool = False) -> Path:
    FITTED.mkdir(parents=True, exist_ok=True)
    return write_json(FITTED / f"{name}.json", obj, gz=gz, nd=6)


def read_fit(name: str) -> Any:
    return read_json(FITTED / f"{name}.json")


def load_fitted(name: str, version: str) -> dict | None:
    m = read_fit(name)
    if isinstance(m, dict) and m.get("version") == version and m.get("ok", True):
        return m
    return None


def write_booster(name: str, model_str: str) -> str:
    FITTED.mkdir(parents=True, exist_ok=True)
    p = FITTED / f"{name}.txt.gz"
    with gzip.open(p, "wt", encoding="utf-8", compresslevel=9) as fh:
        fh.write(model_str)
    return p.name


def read_booster(fname: str) -> str | None:
    try:
        with gzip.open(FITTED / fname, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def store_fit(name: str, fit: dict) -> None:
    """A full fit (booster dumps inline under fit["models"]) to the cache (gzip JSON)."""
    try:
        write_json(cache_root() / "fits" / f"{name}.json", fit, gz=True, nd=8)
    except (OSError, TypeError, ValueError):
        pass


def get_fit(name: str, version: str) -> dict | None:
    """The cached fit when its version matches, else the committed one in models/fitted/ (boosters re-read
    from their .txt.gz files), else None."""
    c = read_json(cache_root() / "fits" / f"{name}.json")
    if isinstance(c, dict) and c.get("version") == version and c.get("ok", True):
        return c
    f = load_fitted(name, version)
    if f is None:
        return None
    files = f.get("model_files") or {}
    if files:
        models = {}
        for k, fn in files.items():
            s = read_booster(fn)
            if s is None:
                return None
            models[k] = s
        f = {**f, "models": models}
    return f


def export_fit(name: str, fit: dict) -> Path:
    """Commit a fit to models/fitted/: boosters as <name>_<key>.txt.gz, the rest as <name>.json."""
    out = {k: v for k, v in fit.items() if k != "models"}
    files = {}
    for k, s in (fit.get("models") or {}).items():
        files[k] = write_booster(f"{name}_{k}", s)
    if files:
        out["model_files"] = files
    return write_fit(name, out)


# ----------------------------------------------------------------------------- LightGBM

_BOOSTERS: dict[str, Any] = {}


def threads(n_rows: int = 10**6) -> int:
    env = os.environ.get("RINK_THREADS")
    if env:
        return int(env)
    return 2 if n_rows < 100_000 else min(16, max(1, (os.cpu_count() or 4) - 4))


def lgb_train(X: pd.DataFrame, y: np.ndarray, objective: str, params: dict | None = None, X_val=None, y_val=None,
              rounds: int = 400, early: int = 30, weight: np.ndarray | None = None,
              monotone: dict | None = None, categorical: list[str] | None = None) -> tuple[Any, dict]:
    """Train a LightGBM booster; returns (booster, {"best_iter", "val_metric"}). Deterministic."""
    import lightgbm as lgb
    p = {"objective": objective, "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 200,
         "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1,
         "seed": 7, "deterministic": True, "force_col_wise": True, "num_threads": threads(len(X))}
    if params:
        p.update(params)
    if monotone:
        p["monotone_constraints"] = [int(monotone.get(c, 0)) for c in X.columns]
        p.setdefault("monotone_constraints_method", "advanced")
    cat = [c for c in (categorical or []) if c in X.columns] or "auto"
    ds = lgb.Dataset(X, label=np.asarray(y, float), weight=weight, free_raw_data=True, categorical_feature=cat)
    valid, cbs = [], []
    if X_val is not None and len(X_val):
        valid = [lgb.Dataset(X_val, label=np.asarray(y_val, float), reference=ds, categorical_feature=cat)]
        cbs = [lgb.early_stopping(early, verbose=False)]
    bst = lgb.train(p, ds, num_boost_round=rounds, valid_sets=valid or None, callbacks=cbs or None)
    info = {"best_iter": int(bst.best_iteration or bst.current_iteration())}
    if valid:
        bs = bst.best_score.get("valid_0") or {}
        info["val_metric"] = {k: float(v) for k, v in bs.items()}
    return bst, info


def booster_dump(bst) -> str:
    return bst.model_to_string(num_iteration=bst.best_iteration or -1)


def booster(model_str: str):
    import lightgbm as lgb
    h = hashlib.sha1(model_str.encode()).hexdigest()
    b = _BOOSTERS.get(h)
    if b is None:
        b = lgb.Booster(model_str=model_str)
        if len(_BOOSTERS) > 16:
            _BOOSTERS.clear()
        _BOOSTERS[h] = b
    return b


def lgb_predict(model_str: str, X: pd.DataFrame, chunk: int = 400_000) -> np.ndarray:
    b = booster(model_str)
    if len(X) == 0:
        return np.zeros((0,))
    nt = threads(len(X))
    out = [b.predict(X.iloc[i:i + chunk], num_threads=nt) for i in range(0, len(X), chunk)]
    return np.concatenate(out).astype(float)


def importances(model_str: str, features: list[str]) -> dict:
    b = booster(model_str)
    g = b.feature_importance(importance_type="gain").astype(float)
    tot = g.sum() or 1.0
    names = b.feature_name() or features
    return {n: round(float(v / tot), 4) for n, v in sorted(zip(names, g), key=lambda t: -t[1])}


def season_folds(seasons: Iterable[int], k: int = 5) -> list[list[int]]:
    s = sorted(set(int(x) for x in seasons))
    k = max(1, min(k, len(s)))
    return [s[i::k] for i in range(k)]


def fold_ids(seasons: np.ndarray, games_: np.ndarray, k: int = 5) -> np.ndarray:
    """Fold per row: by season when there are >= 3 seasons (cross-fitting by season), else by game."""
    us = np.unique(seasons)
    if len(us) >= 3:
        folds = season_folds(us, k)
        m = {s: i for i, f in enumerate(folds) for s in f}
        return np.array([m[s] for s in seasons], dtype=int)
    codes = pd.factorize(pd.Series(games_).astype(str))[0]
    return (codes * 2654435761 % 2**32) % k


def _valid_mask(games_: np.ndarray, frac: float = 0.1) -> np.ndarray:
    codes = pd.factorize(pd.Series(games_).astype(str))[0]
    return ((codes * 40503 + 17) % 1000) < frac * 1000


def crossfit(X: pd.DataFrame, y: np.ndarray, folds: np.ndarray, games_: np.ndarray, objective: str,
             params: dict | None = None, rounds: int = 800, categorical: list[str] | None = None) -> tuple[np.ndarray, list[dict]]:
    """Out-of-fold predictions: each fold predicted by a model trained on the other folds (early stopping on a
    10% game holdout of the training folds). Returns (oof, infos)."""
    n = len(X)
    oof = np.full(n, np.nan)
    infos = []
    vm = _valid_mask(games_)
    for f in np.unique(folds):
        te = folds == f
        tr = ~te & ~vm
        va = ~te & vm
        if tr.sum() < 50 or te.sum() == 0:
            continue
        bst, info = lgb_train(X[tr], y[tr], objective, params, X[va], y[va], rounds=rounds, categorical=categorical)
        oof[te] = bst.predict(X[te], num_iteration=bst.best_iteration or None, num_threads=threads(int(te.sum())))
        info["fold"] = int(f)
        info["n_train"] = int(tr.sum())
        infos.append(info)
        del bst
    return oof, infos


def fit_full(X: pd.DataFrame, y: np.ndarray, objective: str, params: dict | None = None, rounds: int = 300,
             categorical: list[str] | None = None) -> tuple[str, dict]:
    bst, info = lgb_train(X, y, objective, params, rounds=max(10, int(rounds)), categorical=categorical)
    s = booster_dump(bst)
    del bst
    return s, info


# ----------------------------------------------------------------------------- statistics

def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(y) else float("nan")


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve (Mann-Whitney, ties averaged)."""
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    n1 = float((y == 1).sum())
    n0 = float(len(y) - n1)
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = pd.Series(p).rank(method="average").to_numpy()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, float)
    return float(np.mean((np.asarray(p, float) - y) ** 2)) if len(y) else float("nan")


def calibration(y: np.ndarray, p: np.ndarray, bins: Iterable[float] | int = (0, .02, .04, .06, .08, .1, .15, .2, .3, .5, 1.0)) -> dict:
    """Binned calibration: [[lo, hi, mean_pred, mean_obs, n], ...] plus ECE (count-weighted |pred - obs|)."""
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    edges = np.linspace(0, 1, int(bins) + 1) if isinstance(bins, int) else np.asarray(list(bins), float)
    b = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    rows, ece = [], 0.0
    for i in range(len(edges) - 1):
        m = b == i
        n = int(m.sum())
        if not n:
            continue
        mp, mo = float(p[m].mean()), float(y[m].mean())
        rows.append([float(edges[i]), float(edges[i + 1]), round(mp, 4), round(mo, 4), n])
        ece += n * abs(mp - mo)
    return {"bins": rows, "ece": round(ece / max(len(y), 1), 5), "n": int(len(y)),
            "mean_pred": float(p.mean()) if len(p) else None, "mean_obs": float(y.mean()) if len(y) else None}


def pearson(a, b) -> float | None:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return None
    a, b = a[ok], b[ok]
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def shrink(total: float, n: float, k: float, prior: float = 0.0) -> float:
    return float((total + k * prior) / (n + k)) if (n + k) > 0 else float(prior)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -35, 35)))


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def platt(y: np.ndarray, p: np.ndarray, iters: int = 50) -> tuple[float, float]:
    """Logistic recalibration a + b logit(p) by Newton; returns (a, b)."""
    z = logit(p)
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(z)), z])
    beta = np.array([0.0, 1.0])
    for _ in range(iters):
        mu = sigmoid(X @ beta)
        g = X.T @ (y - mu)
        H = X.T @ (X * (mu * (1 - mu))[:, None]) + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, g)
        beta = beta + step
        if np.max(np.abs(step)) < 1e-10:
            break
    return float(beta[0]), float(beta[1])


def apply_platt(p: np.ndarray, ab: tuple[float, float] | list | None) -> np.ndarray:
    if not ab:
        return np.asarray(p, float)
    return sigmoid(ab[0] + ab[1] * logit(p))


def wridge(Z: np.ndarray, y: np.ndarray, w: np.ndarray, lam: float) -> np.ndarray:
    """Weighted ridge with a free intercept (first coefficient)."""
    n, k = Z.shape
    Xa = np.column_stack([np.ones(n), Z])
    L = np.diag([0.0] + [lam] * k)
    A = Xa.T @ (Xa * w[:, None]) + L
    return np.linalg.solve(A + 1e-9 * np.eye(k + 1), Xa.T @ (w * y))


def ids_str(x) -> str | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return str(int(v)) if math.isfinite(v) else None
