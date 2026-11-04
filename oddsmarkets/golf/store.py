"""
The golf store, one directory per tour and season under data/golf (git-ignored; seeded to CI):

  <tour>/<season>/events.json     {event id: event meta from the leaderboard (purse, cut, courses with hole pars ...)}
  <tour>/<season>/results.parquet one row per player and event: pos, tie, status, strokes, to_par, earnings, points
  <tour>/<season>/rounds.parquet  one row per player-round: strokes, nines, tee time, holes recorded
  <tour>/<season>/holes.parquet   one row per player-hole (PGA Tour): strokes, par
  players.json                    {pid: {name, country, amateur}} across tours

An event is final once its leaderboard was fetched after ESPN marked it final; final events are never fetched again.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TABLES = ("results", "rounds", "holes")


def root() -> Path:
    return Path(os.environ.get("GOLF_DATA") or ROOT / "data" / "golf")


def season_dir(tour: str, season: int) -> Path:
    return root() / tour / str(int(season))


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def load_events(tour: str, season: int) -> dict:
    return _read_json(season_dir(tour, season) / "events.json", {})


def save_events(tour: str, season: int, events: dict) -> None:
    _write_json(season_dir(tour, season) / "events.json", events)


def load_table(tour: str, season: int, name: str) -> pd.DataFrame:
    p = season_dir(tour, season) / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def save_table(tour: str, season: int, name: str, df: pd.DataFrame) -> None:
    p = season_dir(tour, season) / f"{name}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    df.reset_index(drop=True).to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, p)


def replace_events(df: pd.DataFrame, new: pd.DataFrame, events: set[str]) -> pd.DataFrame:
    """`df` without the rows of `events`, plus `new`."""
    keep = df[~df["event"].astype(str).isin(events)] if len(df) else df
    parts = [x for x in (keep, new) if len(x)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_players() -> dict:
    return _read_json(root() / "players.json", {})


def save_players(players: dict) -> None:
    _write_json(root() / "players.json", players)


def seasons(tour: str) -> list[int]:
    d = root() / tour
    return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit()) if d.exists() else []
