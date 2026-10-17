"""Shared helpers for The Quant Rink tests: recorded fixtures (no network) and isolated data roots.

Fixtures (tests/nhl/fixtures/, recorded 1 Oct 2026; trimmed of logos, clips and broadcast links):
  pbp_2026020006.json.gz         api-web play-by-play, 2026-09-30 PIT 7 @ PHI 0 (homeTeamDefendingSide present)
  shifts_2026020006.json.gz      stats REST shift charts of that game (shifts + goal markers)
  box_2026020006.json.gz         its boxscore (goalies with starter / decision)
  pbp_2010020100.json.gz         a 2010-11 game, BUF @ NJD (no homeTeamDefendingSide)
  shifts_2010020100.json.gz      its shift charts
  schedule_2026-09-30.json       /schedule/2026-09-30, first two days of the game week
  standings_2026-09-30.json      /standings/2026-09-30
  espn_scoreboard_20260930.json  ESPN scoreboard of 2026-09-30 (3 events), trimmed
  espn_summary_401891821.json    ESPN summary of PIT @ PHI: header, gameInfo, pickcenter (DraftKings open / close)
  espn_odds_401559298.json       ESPN core odds of 2023-10-20 CGY @ CBJ (several books, open / close blocks)
  partner_now.json               /partner-game/US/now (DraftKings via the NHL), 2026-10-01
  moneypuck_shots_2026_slice.parquet  300 rows of MoneyPuck's shots_2026 (slimmed; "Data from MoneyPuck.com")
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FIX / name


def load_fixture(name: str):
    p = FIX / name
    if name.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture
def rink_roots(tmp_path, monkeypatch):
    """Point RINK_DATA / RINK_RAW / RINK_CACHE at a temporary directory."""
    data, raw, cache = tmp_path / "data", tmp_path / "raw", tmp_path / "raw" / "cache"
    monkeypatch.setenv("RINK_DATA", str(data))
    monkeypatch.setenv("RINK_RAW", str(raw))
    monkeypatch.setenv("RINK_CACHE", str(cache))
    return {"data": data, "raw": raw, "cache": cache}


@pytest.fixture(scope="session")
def modern_game():
    from oddsmarkets.nhl import derive
    return derive.derive_game(load_fixture("pbp_2026020006.json.gz"), load_fixture("shifts_2026020006.json.gz"))


@pytest.fixture(scope="session")
def old_game():
    from oddsmarkets.nhl import derive
    return derive.derive_game(load_fixture("pbp_2010020100.json.gz"), load_fixture("shifts_2010020100.json.gz"))
