"""Shared helpers for The Quant Gridiron tests: recorded fixtures (no network) and isolated data roots.

Fixtures (tests/nfl/fixtures/, recorded 1 Oct 2026):
  pbp_2025_slice.parquet            300 plays: all of 2025_13_JAX_TEN (incl. a two-point try) + more 2-pt tries and 4th downs
  ftn_2025_slice.parquet            FTN charting of 2025_13_JAX_TEN
  participation_2025_slice.parquet  pbp_participation of 2025_13_JAX_TEN
  ngs_passing_slice.parquet         NGS passing, 2025 weeks 0-1
  schedules_slice.parquet           games.parquet rows: seasons 2022 and 2025, 2026 weeks 3-4
  espn_summary_401872947.json       2026 week 3 NYG @ LA summary (drives, plays, win probability, pickcenter, injuries), trimmed
  espn_odds_<event>.json            core odds: 400874483 (2016, offshore books + "Opening"), 401127927 (2019, in-play rows),
                                    401872947 (2026, DraftKings open/close)
  espn_scoreboard_2026_w4.json      2026 week 4 scoreboard, trimmed
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIX / name


def load_fixture_json(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture
def gridiron_roots(tmp_path, monkeypatch):
    """Point GRIDIRON_DATA / GRIDIRON_RAW / GRIDIRON_CACHE at a temporary directory."""
    data, raw, cache = tmp_path / "data", tmp_path / "raw", tmp_path / "raw" / "cache"
    monkeypatch.setenv("GRIDIRON_DATA", str(data))
    monkeypatch.setenv("GRIDIRON_RAW", str(raw))
    monkeypatch.setenv("GRIDIRON_CACHE", str(cache))
    return {"data": data, "raw": raw, "cache": cache}


@pytest.fixture
def schedules():
    import pandas as pd
    return pd.read_parquet(FIX / "schedules_slice.parquet")
