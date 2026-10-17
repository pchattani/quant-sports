"""
MoneyPuck shot files (benchmark only). "Data from MoneyPuck.com": free for non-commercial use with credit; file
downloads only, at most nightly, never scraped.

Files (linked from https://moneypuck.com/data.htm, verified 1 Oct 2026):
  https://peter-tanner.com/moneypuck/downloads/shots_{YYYY}.zip    one CSV per season, YYYY = the season's start
                                                                   year (2007 -> 2026; ~18-20 MB zipped, ~120k rows)
Columns used: game_id (the NHL game number within the season, 20001 = regular season game 1; the NHL gameId is
season start year * 10^6 + game_id), id (the NHL play-by-play eventId for api-web era games), period, time
(elapsed seconds in the game), teamCode / isHomeTeam, event (SHOT / MISS / GOAL), shooter / goalie ids, raw and
arena-adjusted coordinates, distance / angle, shot type, rebound / rush flags, skaters on ice, empty nets and the
model outputs xGoal, xRebound, xFroze, xShotWasOnGoal.

Join to events.parquet on (nhl_game_id, time, shooterPlayerId) = (game_id, sec, shooter) for unblocked shots:
99.8% of 2026-27's first 618 MoneyPuck rows match, all with the same event type (`join_events`). MoneyPuck's `id`
is not the api-web eventId.

Each season is converted to <raw>/moneypuck/shots_<season>.parquet (slim columns) and the zip discarded; the
Last-Modified / Content-Length of the file are kept so a completed season is never downloaded twice and the
current season at most once a day.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

URL = "https://peter-tanner.com/moneypuck/downloads/shots_{year}.zip"
CREDIT = "xG benchmark data from MoneyPuck.com"
KEEP = ["shotID", "game_id", "id", "season", "isPlayoffGame", "period", "time", "teamCode", "isHomeTeam",
        "homeTeamCode", "awayTeamCode", "event", "goal", "shooterPlayerId", "shooterName", "goalieIdForShot",
        "xCord", "yCord", "xCordAdjusted", "yCordAdjusted", "arenaAdjustedXCord", "arenaAdjustedYCord",
        "shotDistance", "arenaAdjustedShotDistance", "shotAngleAdjusted", "shotType", "shotWasOnGoal", "shotRebound",
        "shotRush", "shotOnEmptyNet", "homeSkatersOnIce", "awaySkatersOnIce", "homeEmptyNet", "awayEmptyNet",
        "homeTeamGoals", "awayTeamGoals", "xGoal", "xRebound", "xFroze", "xShotWasOnGoal"]


def url(season: int) -> str:
    return URL.format(year=canon.start_year(season))


def head(c: Client, season: int) -> dict | None:
    return c.head(url(season))


def parse_zip(data: bytes, season: int):
    """The slim shot table of a season (pandas DataFrame) from the zip bytes, with nhl_game_id added."""
    import pandas as pd
    z = zipfile.ZipFile(io.BytesIO(data))
    name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    with z.open(name) as fh:
        df = pd.read_csv(fh, low_memory=False)
    return slim(df, season)


def slim(df, season: int):
    import pandas as pd
    cols = [c for c in KEEP if c in df.columns]
    df = df[cols].copy()
    y = canon.start_year(season)
    df["nhl_game_id"] = (y * 1_000_000 + pd.to_numeric(df["game_id"], errors="coerce")).astype("Int64")
    for c in ("xGoal", "xRebound", "xFroze", "xShotWasOnGoal"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")
    return df


def fetch(c: Client, season: int, dest: Path, known: dict | None = None) -> dict | None:
    """Download and convert a season if its file changed since `known` ({last_modified, length}). Returns the new
    marker, or `known` when nothing changed, or None on failure."""
    h = head(c, season)
    if h is None:
        return None
    marker = {"last_modified": h.get("last-modified"), "length": h.get("content-length")}
    if known and known.get("last_modified") == marker["last_modified"] and known.get("length") == marker["length"] \
            and Path(dest).exists():
        return known
    data = c.get_bytes(url(season))
    if not data:
        return None
    df = parse_zip(data, season)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(dest)
    marker["rows"] = int(len(df))
    return marker


def join_events(events, mp):
    """Unblocked-shot events with MoneyPuck's xGoal (column mp_xg) where a MoneyPuck row matches on game, elapsed
    second and shooter (duplicates on that key keep the first)."""
    import pandas as pd
    sh = events[events["type"].astype(str).isin(("shot-on-goal", "missed-shot", "goal"))].copy()
    sh["_sec"] = pd.to_numeric(sh["sec"], errors="coerce").astype("Int64")
    sh["_shooter"] = pd.to_numeric(sh["shooter"], errors="coerce").astype("Int64")
    m = mp[["nhl_game_id", "time", "shooterPlayerId", "xGoal"]].copy()
    m["time"] = pd.to_numeric(m["time"], errors="coerce").astype("Int64")
    m["shooterPlayerId"] = pd.to_numeric(m["shooterPlayerId"], errors="coerce").astype("Int64")
    m = m.drop_duplicates(["nhl_game_id", "time", "shooterPlayerId"])
    out = sh.merge(m, left_on=["game_id", "_sec", "_shooter"], right_on=["nhl_game_id", "time", "shooterPlayerId"],
                   how="left")
    return out.drop(columns=["_sec", "_shooter", "nhl_game_id", "time", "shooterPlayerId"]).rename(columns={"xGoal": "mp_xg"})
