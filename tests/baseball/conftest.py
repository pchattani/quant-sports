"""Shared helpers for The Quant Bullpen tests: recorded fixtures (no network) and isolated data roots."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIX / name


def load_fixture_json(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def load_fixture_text(name: str, encoding: str = "utf-8") -> str:
    return (FIX / name).read_text(encoding=encoding)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No test reaches the MLB Stats API: analytics/mlbapi.client() returns None (cache only)."""
    monkeypatch.setenv("BULLPEN_OFFLINE", "1")


@pytest.fixture
def bullpen_roots(tmp_path, monkeypatch):
    """Point BULLPEN_DATA / BULLPEN_RAW / BULLPEN_CACHE at a temporary directory."""
    data, raw, cache = tmp_path / "data", tmp_path / "raw", tmp_path / "raw" / "cache"
    monkeypatch.setenv("BULLPEN_DATA", str(data))
    monkeypatch.setenv("BULLPEN_RAW", str(raw))
    monkeypatch.setenv("BULLPEN_CACHE", str(cache))
    return {"data": data, "raw": raw, "cache": cache}


def write_synthetic_world(roots: dict, season: int = 2025, n_games: int = 60, seed: int = 1, level: str = "mlb") -> dict:
    """A synthetic season (builder C's generator) written where the build reads it: the store at
    <data>/<level>/<season>/store.json, the pitch table at <raw>/statcast/<level>/<season>.parquet and people.json."""
    from oddsmarkets.baseball.models import synthetic_c as S
    df, store, truth = S.synth_season(n_teams=6, n_games=n_games, season=season, seed=seed, level=level)
    d = roots["data"] / level / str(season)
    d.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = f"{season}-10-01T00:00:00Z"
    (d / "store.json").write_text(json.dumps(store, default=str), encoding="utf-8")
    p = roots["raw"] / "statcast" / level / f"{season}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    people = {pid: {"name": v.get("name"), "retro": None, "bbref": None, "fg": None, "birth": "1995-05-05", "debut": None, "last": None}
              for pid, v in store["players"].items()}
    (roots["data"] / "people.json").write_text(json.dumps(people), encoding="utf-8")
    return {"pitches": df, "store": store, "truth": truth, "season": season, "level": level}


@pytest.fixture
def synthetic_world(bullpen_roots):
    """One synthetic MLB season (2025, 60 games, 6 teams) on disk under isolated roots."""
    from oddsmarkets.baseball import analytics as an
    an._STORES.clear()
    w = write_synthetic_world(bullpen_roots)
    return {**w, "roots": bullpen_roots}
