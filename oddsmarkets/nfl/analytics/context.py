"""
SeasonContext: everything the catalogues and pages of one season read, loaded lazily and once.

* `store` (builder A's season store, or games built from the nflverse schedule when the store is missing), `games`
  {game_id: GAME}, `teams` {abbr: {...}}, `phase` ("preseason" | "regular" | "playoffs" | "offseason"), `week`.
* `pbp()`: the season's nflverse play-by-play (a column subset, REG + POST), with FTN charting and (2016-2025)
  participation joined by `plays()`; our own EP / WP / fourth-down columns joined when builder B's models score.
* `release(name)`: any other nflverse release for the season (ngs_*, player stats, rosters, injuries, depth charts),
  via builder A's `sources.nflverse.load` or a glob of the raw mirror. Pro Football Reference's releases (snap counts,
  advanced stats, trades, draft picks, combine) are not mirrored (sources/nflverse.LEFT_OUT).
* `model(name)`: one builder B/C model's season output (`for_season`), isolated: a model that raises or is missing
  gives {"ok": False, "reason"} and is listed in `model_errors`.
Memory: one season of plays at a time; `free()` drops the frames.
"""
from __future__ import annotations

import gc
import importlib
import logging
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import teamsref

logger = logging.getLogger(__name__)

# the team of each credited tackler / fumble forcer (nflfastR): the tackler after a turnover or on a punt is not the defteam
TEAM_CREDIT_COLS = ["solo_tackle_1_team", "solo_tackle_2_team", "assist_tackle_1_team", "assist_tackle_2_team",
                    "assist_tackle_3_team", "assist_tackle_4_team", "tackle_with_assist_1_team", "tackle_with_assist_2_team",
                    "forced_fumble_player_1_team", "forced_fumble_player_2_team"]
PBP_COLS = [
    "game_id", "play_id", "season", "week", "season_type", "game_date", "home_team", "away_team", "posteam", "defteam",
    "posteam_type", "yardline_100", "qtr", "down", "ydstogo", "time", "game_seconds_remaining", "half_seconds_remaining",
    "quarter_seconds_remaining", "desc", "play_type", "yards_gained", "shotgun", "no_huddle", "qb_dropback", "qb_scramble",
    "qb_kneel", "qb_spike", "pass_length", "pass_location", "air_yards", "yards_after_catch", "run_location", "run_gap",
    "field_goal_result", "kick_distance", "extra_point_result", "two_point_conv_result", "two_point_attempt",
    "posteam_timeouts_remaining", "defteam_timeouts_remaining", "total_home_score", "total_away_score", "posteam_score",
    "defteam_score", "score_differential", "ep", "epa", "wp", "def_wp", "home_wp", "away_wp", "wpa", "vegas_wp", "vegas_home_wp",
    "home_wp_post", "air_epa", "yac_epa", "comp_air_epa", "comp_yac_epa", "xyac_epa", "xyac_mean_yardage", "first_down",
    "incomplete_pass", "touchback", "interception", "fumble", "fumble_lost", "sack", "touchdown", "pass_touchdown",
    "rush_touchdown", "complete_pass", "penalty", "penalty_team", "penalty_type", "penalty_yards", "penalty_player_id",
    "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name", "rusher_player_id",
    "rusher_player_name", "kicker_player_id", "kicker_player_name", "punter_player_id", "punter_player_name",
    "interception_player_id", "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id",
    "qb_hit_2_player_id", "solo_tackle_1_player_id", "tackle_with_assist_1_player_id", "assist_tackle_1_player_id",
    "pass_defense_1_player_id", "pass_defense_2_player_id", "forced_fumble_player_1_player_id", "tackle_for_loss_1_player_id",
    "qb_hit", "tackled_for_loss", "fixed_drive", "fixed_drive_result", "drive", "drive_play_count", "drive_time_of_possession",
    "drive_first_downs", "drive_start_yard_line", "drive_end_yard_line", "drive_quarter_start", "drive_game_clock_start",
    "series", "series_success", "cp", "cpoe", "xpass", "pass_oe", "success", "pass", "rush", "special", "play", "passer_id",
    "rusher_id", "receiver_id", "passer", "rusher", "receiver", "home_coach", "away_coach", "roof", "surface", "temp", "wind",
    "result", "total", "spread_line", "total_line", "div_game", "timeout", "timeout_team", "td_team", "punt_blocked",
    "return_yards", "play_deleted", "aborted_play", "special_teams_play", "fourth_down_converted",
    "fourth_down_failed", "third_down_converted", "third_down_failed", "out_of_bounds", "order_sequence",
    # official-style yardage (laterals credited to the lateral player) and every credited defender with his team
    "passing_yards", "receiving_yards", "rushing_yards", "pass_attempt", "rush_attempt", "td_player_id",
    "lateral_receiver_player_id", "lateral_receiving_yards", "lateral_rusher_player_id", "lateral_rushing_yards",
    "solo_tackle_2_player_id", "assist_tackle_2_player_id", "assist_tackle_3_player_id", "assist_tackle_4_player_id",
    "tackle_with_assist_2_player_id", "tackle_for_loss_2_player_id", "forced_fumble_player_2_player_id",
    *TEAM_CREDIT_COLS,
]
FTN_COLS = ["nflverse_game_id", "nflverse_play_id", "is_motion", "is_play_action", "is_screen_pass", "is_rpo", "is_trick_play",
            "is_qb_out_of_pocket", "is_interception_worthy", "is_throw_away", "is_catchable_ball", "is_contested_ball",
            "is_created_reception", "is_drop", "is_qb_sneak", "n_blitzers", "n_pass_rushers", "n_defense_box",
            "is_qb_fault_sack", "qb_location", "n_offense_backfield", "is_no_huddle"]
PART_COLS = ["nflverse_game_id", "play_id", "offense_formation", "offense_personnel", "defenders_in_box", "defense_personnel",
             "number_of_pass_rushers", "time_to_throw", "was_pressure", "route", "defense_man_zone_type", "defense_coverage_type",
             "offense_players", "defense_players", "ngs_air_yards"]
GTYPE_ORDER = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4}


# ---------------------------------------------------------------------------------------------- raw readers

def _read_parquet(path: Path, columns: list[str] | None = None, filters=None) -> pd.DataFrame | None:
    try:
        import pyarrow.parquet as pq
        schema = pq.read_schema(path)
        cols = None if columns is None else [c for c in dict.fromkeys(columns) if c in schema.names]
        return pd.read_parquet(path, columns=cols, filters=filters)
    except Exception as exc:                                     # noqa: BLE001
        logger.info("read %s failed: %s", path, exc)
        return None


def release_files(release: str, season: int | None = None) -> list[Path]:
    """Raw mirror files of a release (<raw>/raw/<release>/*.parquet), those naming the season first, then the
    all-season files (names without a four-digit year)."""
    d = an.raw_root() / "raw" / release
    try:
        files = sorted(p for p in d.glob("*.parquet"))
    except OSError:
        return []
    if season is None:
        return files
    s = str(int(season))
    named = [p for p in files if s in p.stem]
    if named:
        return named
    import re
    return [p for p in files if not re.search(r"(19|20)\d\d", p.stem)]


def load_release(release: str, season: int | None = None, columns: list[str] | None = None, kind: str | None = None) -> pd.DataFrame | None:
    """One nflverse release for a season: builder A's `nflverse.load(release, season)` when it answers, else the
    mirror files read directly (filtered on a "season" column when the file holds every season)."""
    df = None
    try:
        from oddsmarkets.nfl.sources import nflverse as NV
        f = getattr(NV, "load", None)
        if f is not None:
            # the kind (NGS passing / rushing / receiving, QBR season / week) must reach the loader: without it every
            # kind read the release's first file, so NGS rushing and receiving were the passing rows (separation,
            # cushion, 8-man boxes empty on every season until 22 Oct 2026)
            kw = {"kind": kind} if kind else {}
            try:
                df = f(release, season, columns=columns, **kw) if columns is not None else f(release, season, **kw)
            except TypeError:
                df = None if kind else f(release, season)
    except Exception as exc:                                     # noqa: BLE001
        logger.debug("nflverse.load(%s, %s): %s", release, season, exc)
        df = None
    if df is None or not isinstance(df, pd.DataFrame):
        files = release_files(release, season)
        if kind:
            files = [p for p in files if kind in p.stem] or ([] if any(kind in q.stem for q in release_files(release)) else files)
        parts = [x for x in (_read_parquet(p, columns + ["season"] if columns else None) for p in files) if x is not None]
        if not parts:
            return None
        df = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    elif columns is not None:
        df = df[[c for c in dict.fromkeys(columns + ["season"]) if c in df.columns]]
    if season is not None and "season" in df.columns:
        sv = pd.to_numeric(df["season"], errors="coerce")
        if (sv == int(season)).any() or sv.notna().any():
            df = df[sv == int(season)]
    return df.reset_index(drop=True)


def load_pbp(season: int, columns: list[str] | None = None) -> pd.DataFrame | None:
    cols = columns or PBP_COLS
    try:
        from oddsmarkets.nfl.sources import nflverse as NV
        f = getattr(NV, "load_pbp", None)
        if f is not None:
            df = f(season, columns=cols)
            if isinstance(df, pd.DataFrame) and len(df):
                return df[[c for c in dict.fromkeys(cols) if c in df.columns]].reset_index(drop=True)
    except Exception as exc:                                     # noqa: BLE001
        logger.debug("nflverse.load_pbp(%s): %s", season, exc)
    files = [p for p in release_files("pbp", season) if str(season) in p.stem]
    for p in files:
        df = _read_parquet(p, cols)
        if df is not None and len(df):
            return df
    dp = an.raw_root() / "derived" / str(season) / "plays.parquet"
    if dp.exists():
        return _read_parquet(dp, cols)
    return None


# ---------------------------------------------------------------------------------------------- the context

class SeasonContext:
    def __init__(self, season: int, full: bool = True, today: date | None = None, current: bool = False, sims: int = 20000,
                 fetch_markets: bool = False, use_models: bool = True):
        self.season, self.full = int(season), full
        self.today = today or date.today()
        self.current = current
        self.sims = sims
        self.fetch_markets = fetch_markets
        self.use_models = use_models
        self.store = an.load_store(season)
        self.store_source = "store" if self.store.get("games") else "schedule"
        if not self.store.get("games"):
            self.store = {"season": self.season, "teams": {}, "games": games_from_schedule(self.season), "meta": {"source": "nflverse schedule"}}
        self.games: dict[str, dict] = self.store.get("games") or {}
        self.teams: dict[str, dict] = teamsref.season_teams(self.season, self.store.get("teams") or {})
        in_games = {t for g in self.games.values() for t in (g.get("home"), g.get("away")) if t}
        if in_games:
            self.teams = {t: (self.teams.get(t) or teamsref.info(t, self.season)) for t in sorted(in_games)}
        self.model_errors: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self._models: dict[str, Any] = {}
        self._pbp: pd.DataFrame | None = None
        self._plays: pd.DataFrame | None = None
        self._rel: dict[tuple, Any] = {}
        self._markets: dict | None = None
        self._sim: dict | None = None
        self.phase, self.week = self._phase()

    # ------------------------------------------------------------------ basics
    def _phase(self) -> tuple[str, int | None]:
        gs = list(self.games.values())
        if not gs:
            return "offseason", None
        final = [g for g in gs if g.get("status") == "final"]
        reg = [g for g in gs if g.get("gtype") == "REG"]
        post = [g for g in gs if g.get("gtype") in ("WC", "DIV", "CON", "SB")]
        sb = [g for g in post if g.get("gtype") == "SB"]
        if sb and all(g.get("status") == "final" for g in sb):
            return "offseason", max(int(g.get("week") or 0) for g in gs)
        if not final:
            return "preseason", 1
        unfinished = [g for g in gs if g.get("status") != "final"]
        if post and all(g.get("status") == "final" for g in reg):
            wk = min((int(g.get("week") or 0) for g in unfinished), default=max(int(g.get("week") or 0) for g in gs))
            return "playoffs", wk
        if not unfinished:
            return "offseason", max(int(g.get("week") or 0) for g in gs)
        # the current week: the earliest week with an unfinished game, unless today is past it
        wk = min(int(g.get("week") or 0) for g in unfinished)
        return ("playoffs" if wk > max((int(g.get("week") or 0) for g in reg), default=18) else "regular"), wk

    def name(self, abbr: str) -> str:
        return (self.teams.get(abbr) or {}).get("name") or abbr

    def team_games(self) -> int:
        n: dict[str, int] = {}
        for g in self.games.values():
            if g.get("gtype") == "REG" and g.get("status") == "final":
                for t in (g.get("home"), g.get("away")):
                    n[t] = n.get(t, 0) + 1
        return max(n.values()) if n else 0

    # ------------------------------------------------------------------ plays
    def has_pbp(self) -> bool:
        return bool(release_files("pbp", self.season)) or (an.raw_root() / "derived" / str(self.season) / "plays.parquet").exists()

    def pbp(self) -> pd.DataFrame:
        """The season's plays (PBP_COLS present in the file), REG and POST, deleted / aborted plays dropped."""
        if self._pbp is None:
            t0 = time.perf_counter()
            df = load_pbp(self.season)
            if df is None:
                df = pd.DataFrame(columns=["game_id", "play_id"])
            df = df.loc[:, ~df.columns.duplicated()]
            if "play_deleted" in df:
                df = df[df["play_deleted"].fillna(0) != 1]
            for c in ("posteam", "defteam", "home_team", "away_team", "penalty_team", "timeout_team", "td_team", *TEAM_CREDIT_COLS):
                if c in df:
                    df[c] = df[c].map(lambda x: teamsref.canon_abbr(x, self.season) if isinstance(x, str) else x)
            self._pbp = df.reset_index(drop=True)
            self.timings["load pbp"] = time.perf_counter() - t0
        return self._pbp

    def plays(self) -> pd.DataFrame:
        """pbp() with FTN charting (2022 onward), participation (2016-2025) and our model columns joined:
        ep_ours, wp_ours (home perspective wp_home_ours), and the fourth-down decision columns when builder B's
        models score the season."""
        if self._plays is not None:
            return self._plays
        t0 = time.perf_counter()
        df = self.pbp().copy()
        if len(df) and "play_id" in df:
            df["play_id"] = pd.to_numeric(df["play_id"], errors="coerce")
            ftn = self.ftn()
            if ftn is not None and len(ftn):
                f = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
                f["play_id"] = pd.to_numeric(f["play_id"], errors="coerce")
                f = f.drop(columns=[c for c in f.columns if c in df.columns and c not in ("game_id", "play_id")])
                df = df.merge(f.drop_duplicates(["game_id", "play_id"]), on=["game_id", "play_id"], how="left")
            part = self.participation()
            if part is not None and len(part):
                p = part.rename(columns={"nflverse_game_id": "game_id"})
                p["play_id"] = pd.to_numeric(p["play_id"], errors="coerce")
                p = p.drop(columns=[c for c in p.columns if c in df.columns and c not in ("game_id", "play_id")])
                df = df.merge(p.drop_duplicates(["game_id", "play_id"]), on=["game_id", "play_id"], how="left")
            df = self._ours(df)
        self._plays = df.loc[:, ~df.columns.duplicated()]
        self.timings["plays"] = time.perf_counter() - t0
        return df

    def _ours(self, df: pd.DataFrame) -> pd.DataFrame:
        """Join builder B's per-play scores (EP, WP, fourth-down decisions) by (game_id, play_id)."""
        from oddsmarkets.nfl.analytics import adapters
        try:
            sc = adapters.play_scores(self)
        except Exception as exc:                                 # noqa: BLE001
            self.model_errors["play_scores"] = f"{type(exc).__name__}: {exc}"
            sc = None
        if sc is not None and len(sc):
            sc = sc.copy()
            sc["play_id"] = pd.to_numeric(sc["play_id"], errors="coerce")
            sc = sc.drop(columns=[c for c in sc.columns if c in df.columns and c not in ("game_id", "play_id")])
            df = df.merge(sc.drop_duplicates(["game_id", "play_id"]), on=["game_id", "play_id"], how="left")
        return df

    def ftn(self) -> pd.DataFrame | None:
        if self.season < 2022:
            return None
        return self.release("ftn_charting", FTN_COLS)

    def participation(self) -> pd.DataFrame | None:
        if self.season < 2016:
            return None
        return self.release("pbp_participation", PART_COLS)

    def release(self, name: str, columns: list[str] | None = None, kind: str | None = None) -> pd.DataFrame | None:
        key = (name, tuple(columns or ()), kind)
        if key not in self._rel:
            t0 = time.perf_counter()
            try:
                self._rel[key] = load_release(name, self.season, columns, kind)
            except Exception as exc:                             # noqa: BLE001
                logger.info("release %s %s: %s", name, self.season, exc)
                self._rel[key] = None
            self.timings[f"release {name}{'/' + kind if kind else ''}"] = time.perf_counter() - t0
        return self._rel[key]

    def ngs(self, kind: str) -> pd.DataFrame | None:
        """NGS season rows (week 0, regular season) for passing / rushing / receiving."""
        if self.season < 2016:
            return None
        df = self.release("nextgen_stats", None, kind)
        if df is None or not len(df):
            return None
        if "week" in df:
            wk0 = df[pd.to_numeric(df["week"], errors="coerce").fillna(-1) == 0]
            if "season_type" in wk0:
                wk0 = wk0[wk0["season_type"].astype(str).str.upper().str.startswith("REG")]
            return wk0 if len(wk0) else None
        return df

    def ngs_weekly(self, kind: str) -> pd.DataFrame | None:
        if self.season < 2016:
            return None
        df = self.release("nextgen_stats", None, kind)
        if df is None or "week" not in df:
            return None
        return df[pd.to_numeric(df["week"], errors="coerce").fillna(0) > 0]

    def free(self) -> None:
        self._pbp = None
        self._plays = None
        self._rel.clear()
        gc.collect()

    # ------------------------------------------------------------------ models
    def model(self, name: str, *args, **kw) -> Any:
        """builder B / C model `for_season(season)`, isolated and memoised; {"ok": False, "reason"} on failure."""
        key = (name, args, tuple(sorted(kw.items())))
        if key in self._models:
            return self._models[key]
        t0 = time.perf_counter()
        if not self.use_models:
            res: Any = {"ok": False, "reason": "models disabled for this run"}
        else:
            try:
                mod = importlib.import_module(f"oddsmarkets.nfl.models.{name}")
                fn = getattr(mod, "for_season")
                res = fn(self.season, *args, **kw)
            except Exception as exc:                             # noqa: BLE001
                logger.warning("model %s %s failed: %s\n%s", name, self.season, exc, traceback.format_exc(limit=4))
                res = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        if res is None:
            res = {"ok": False, "reason": "no result"}
        if isinstance(res, dict) and (res.get("ok") is False or res.get("available") is False):
            self.model_errors[name] = str(res.get("reason") or "not available")
        self._models[key] = res
        self.timings[f"model {name}"] = self.timings.get(f"model {name}", 0.0) + time.perf_counter() - t0
        return res

    def sim(self) -> dict:
        if self._sim is None:
            from oddsmarkets.nfl.analytics import adapters
            t0 = time.perf_counter()
            try:
                self._sim = adapters.season_sim(self)
            except Exception as exc:                             # noqa: BLE001
                self._sim = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            if not self._sim.get("ok", True) or self._sim.get("available") is False:
                self.model_errors["season_sim"] = str(self._sim.get("reason"))
            self.timings["season sim"] = time.perf_counter() - t0
        return self._sim

    def markets(self) -> dict:
        if self._markets is None:
            self._markets = {}
            if self.fetch_markets:
                from oddsmarkets.nfl.analytics import adapters
                t0 = time.perf_counter()
                try:
                    self._markets = adapters.markets(self) or {}
                except Exception as exc:                         # noqa: BLE001
                    logger.warning("markets failed: %s", exc)
                    self.model_errors["markets"] = str(exc)
                self.timings["markets"] = time.perf_counter() - t0
        return self._markets


# ---------------------------------------------------------------------------------------------- games from the schedule

def _gtype(x: Any) -> str:
    s = str(x or "REG").upper()
    return {"REG": "REG", "WC": "WC", "DIV": "DIV", "CON": "CON", "SB": "SB", "POST": "WC"}.get(s, s)


def games_from_schedule(season: int) -> dict[str, dict]:
    """GAME records (CONTRACT.md) from the nflverse schedule when builder A's store is missing."""
    df = load_release("schedules", season)
    if df is None or not len(df):
        return {}
    out = {}
    for r in df.to_dict("records"):
        gid = an.sid(r.get("game_id"))
        if not gid:
            continue
        hs, as_ = an.inum(r.get("home_score")), an.inum(r.get("away_score"))
        home = teamsref.canon_abbr(r.get("home_team"), season)
        away = teamsref.canon_abbr(r.get("away_team"), season)
        kickoff = None
        if r.get("gameday"):
            kickoff = f"{str(r['gameday'])[:10]}T{(str(r.get('gametime') or '13:00'))[:5]}:00-04:00"
        sl = an.fnum(r.get("spread_line"))                       # nflverse: points the home team is favoured by
        lines = {"spread_home": -sl if sl is not None else None, "total": an.fnum(r.get("total_line")),
                 "ml_home": an.fnum(r.get("home_moneyline")), "ml_away": an.fnum(r.get("away_moneyline")), "open": None, "close": None,
                 "books": []}
        out[gid] = {"game_id": gid, "season": int(season), "week": an.inum(r.get("week")), "gtype": _gtype(r.get("game_type")),
                    "date": str(r.get("gameday") or "")[:10] or None, "kickoff": kickoff, "home": home, "away": away, "hs": hs, "as": as_,
                    "status": "final" if hs is not None and as_ is not None else "scheduled", "stadium": r.get("stadium"), "roof": r.get("roof"),
                    "surface": r.get("surface"), "temp": an.fnum(r.get("temp")), "wind": an.fnum(r.get("wind")), "referee": r.get("referee"),
                    "home_qb": an.sid(r.get("home_qb_id")), "away_qb": an.sid(r.get("away_qb_id")), "home_qb_name": r.get("home_qb_name"),
                    "away_qb_name": r.get("away_qb_name"),
                    "home_coach": r.get("home_coach"), "away_coach": r.get("away_coach"), "lines": lines, "espn_id": an.sid(r.get("espn")),
                    "overtime": bool(an.inum(r.get("overtime")) or 0), "div_game": bool(an.inum(r.get("div_game")) or 0),
                    "home_rest": an.inum(r.get("home_rest")), "away_rest": an.inum(r.get("away_rest"))}
    return out


def frame_of(obj: Any) -> pd.DataFrame | None:
    """A model output as a DataFrame: a DataFrame, {"cols","rows"}, a list of dicts, or {key: {...}} records."""
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, dict) and "cols" in obj and "rows" in obj:
        return pd.DataFrame(obj.get("rows") or [], columns=obj["cols"])
    if isinstance(obj, list) and (not obj or isinstance(obj[0], dict)):
        return pd.DataFrame(obj)
    return None


def num(df: pd.DataFrame, c: str, default: float = np.nan) -> pd.Series:
    """A numeric column, or a constant Series when the column is missing."""
    if c in df:
        return pd.to_numeric(df[c], errors="coerce")
    return pd.Series(default, index=df.index, dtype=float)


def flag(df: pd.DataFrame, c: str) -> pd.Series:
    """A 0/1 column (bool, numeric or missing -> 0) as float with NaN where missing in the source."""
    if c not in df:
        return pd.Series(np.nan, index=df.index, dtype=float)
    s = df[c]
    if s.dtype == bool:
        return s.astype(float)
    return pd.to_numeric(s.map(lambda x: 1.0 if x is True else (0.0 if x is False else x)), errors="coerce")
