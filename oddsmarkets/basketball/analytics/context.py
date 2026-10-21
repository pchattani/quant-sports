"""
`SeasonContext`: everything one league-season's payloads share, loaded once and lazily (each
piece is computed on first use, and a piece that fails is logged and left empty, so one missing
model never stops the rest of the season's payloads).

    store, games (league members only), box (regular-season box rows), box_all (every counted game),
    shots (the season's shot table with xPTS), stints (stint frame) and team_stints, xpts (shots.for_season),
    impact (impact.for_season), ratings (ratings.for_season), informed (the market-informed game model's inputs),
    wp_model, pbp (the pbp pass), sim (season_sim),
    elo (the league history, shared), markets (futures and game prices for the current season).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import cached_property
from typing import Any

import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import lineups as LU
from oddsmarkets.basketball.models import _io

logger = logging.getLogger(__name__)
CATALOGUE_STYPES = ("reg",)              # the Cup final does not count in the standings or season stats
COUNTED = ("reg", "cup", "playin", "post")


def _safe(name: str, fn, default):
    try:
        v = fn()
        return default if v is None else v
    except Exception as exc:  # noqa: BLE001
        logger.warning("context %s failed: %s", name, exc, exc_info=True)
        return default


class SeasonContext:
    def __init__(self, league: str, season: int, current: int | None = None, full: bool = False, elo: dict | None = None,
                 sims: int = 20000, fetch_markets: bool = False, today: date | None = None):
        self.league = league
        self.season = int(season)
        self.current = int(current or season)
        self.full = full
        self.elo_hist = elo or {}
        self.sims = sims
        self.fetch_markets = fetch_markets
        self.today = today or date.today()
        self.errors: list[str] = []
        self.pages_due: set[str] = set()
        self.pbp_summaries: dict = {}
        self.pbp_totals: dict = {"players": {}, "teams": {}, "wpa": {}}
        self.pbp_available = False

    # ------------------------------------------------------------------ data
    @cached_property
    def store(self) -> dict:
        return an.load_store(self.league, self.season)

    @cached_property
    def games(self) -> dict[str, dict]:
        return an.real_games(self.store)

    @cached_property
    def member_store(self) -> dict:
        """The store with only games between league members (what the standings and the simulation see)."""
        return {**self.store, "games": self.games, "teams": {t: v for t, v in (self.store.get("teams") or {}).items() if t in set(self.teams)}}

    @cached_property
    def teams(self) -> list[str]:
        return an.member_teams(self.store)

    @cached_property
    def players(self) -> dict:
        """The season's player records, with a missing date of birth filled from the current season's store
        (only the rosters phase, which reads today's rosters, records dates of birth; a date of birth does not
        change, so ages in past seasons' catalogues come from it), then from data/<L>/bio.json (scripts/bb_bio.py)."""
        from oddsmarkets.basketball.analytics import bio as _bio
        pl = self.store.get("players") or {}
        if self.current == self.season or all((r or {}).get("dob") for r in pl.values()):
            return _bio.fill_dob(self.league, pl)
        cur = (an.load_store(self.league, self.current) or {}).get("players") or {}
        out = {}
        for pid, r in pl.items():
            d = (cur.get(pid) or {}).get("dob")
            out[pid] = {**r, "dob": d} if d and not (r or {}).get("dob") else r
        return _bio.fill_dob(self.league, out)

    @cached_property
    def box(self) -> pd.DataFrame:
        return _safe("box", lambda: _io.box_frame(self.games, CATALOGUE_STYPES), pd.DataFrame())

    @cached_property
    def box_all(self) -> pd.DataFrame:
        return _safe("box_all", lambda: _io.box_frame(self.games, COUNTED), pd.DataFrame())

    @cached_property
    def has_pm(self) -> bool:
        for g in self.games.values():
            for b in (g.get("box") or {}).values():
                for r in b.get("players") or []:
                    if len(r) > 17 and r[17] is not None:
                        return True
        return False

    @cached_property
    def xpts(self) -> dict:
        from oddsmarkets.basketball.models import shots as SH
        return _safe("xpts", lambda: SH.for_season(self.league, self.season), {"ok": False, "reason": "failed"})

    @cached_property
    def xmodel(self) -> dict | None:
        return (self.xpts or {}).get("model") if (self.xpts or {}).get("ok") else None

    @cached_property
    def shots(self) -> pd.DataFrame:
        """The season's shot table with p, xpts, pts (empty without shots.json[.gz])."""
        from oddsmarkets.basketball.models import shots as SH

        def build():
            raw = an.load_table(self.league, self.season, "shots.json")
            if not raw or not raw.get("rows"):
                return pd.DataFrame()
            df = SH.as_shots(raw)
            if self.xmodel:
                df = SH.with_xpts(df, self.xmodel)
            else:
                df["pts"] = df["made"] * df["value"]
            return df
        return _safe("shots", build, pd.DataFrame())

    @cached_property
    def stints(self) -> pd.DataFrame:
        return _safe("stints", lambda: LU.stint_frame(an.load_table(self.league, self.season, "stints.json")), pd.DataFrame())

    @cached_property
    def team_stints(self) -> pd.DataFrame:
        return _safe("team_stints", lambda: LU.team_stints(self.stints, self.games), pd.DataFrame())

    @cached_property
    def recon(self) -> dict:
        return an.load_table(self.league, self.season, "recon.json") or {}

    # ------------------------------------------------------------------ models
    @cached_property
    def impact(self) -> dict:
        from oddsmarkets.basketball.models import impact as IM
        return _safe("impact", lambda: IM.for_season(self.league, self.season), {"ok": False})

    @cached_property
    def hpm(self) -> dict[str, dict]:
        imp = self.impact or {}
        return {p: r for p, r in (imp.get("players") or {}).items() if r.get("t") is not None} if imp.get("ok") else {}

    @cached_property
    def ratings(self) -> dict:
        from oddsmarkets.basketball.models import ratings as R
        return _safe("ratings", lambda: R.for_season(self.league, self.season), {"teams": {}})

    @cached_property
    def params(self) -> dict:
        from oddsmarkets.basketball.models import game as GM
        return _safe("params", lambda: GM.params(self.league), {})

    @cached_property
    def prior(self) -> dict:
        return (self.ratings or {}).get("prior") or {}

    _fits: dict

    def ratings_before(self, d: date) -> dict:
        """Ratings fitted on games strictly before day `d` (with the preseason prior), memoised by day."""
        from oddsmarkets.basketball.models import ratings as R
        if not hasattr(self, "_fits"):
            self._fits = {}
        key = str(d)
        if key not in self._fits:
            self._fits[key] = _safe(f"ratings before {d}", lambda: R.fit_ratings(
                self.store.get("games") or {}, through=d - timedelta(days=1), prior=self.prior or None, league=self.league,
                teams=self.teams), {"teams": {}})
        return self._fits[key]

    @cached_property
    def informed(self) -> dict | None:
        """Per-day inputs of the market-informed game model (`models/informed.py`): market ratings from the store's
        closing lines and expected availability; None where the league does not use it, and for past seasons (their
        game pages keep the base model; the calibration page scores the informed model walk-forward)."""
        from oddsmarkets.basketball.models import informed as INF
        if not INF.enabled(self.league) or self.season != self.current:
            return None
        return _safe("informed inputs", lambda: INF.season_inputs(self.league, self.season, self.store), None)

    @cached_property
    def schedule(self):
        from oddsmarkets.basketball.models import game as GM
        return GM.Schedule(self.store.get("games") or {}, self.store.get("teams") or {}, self.league)

    @cached_property
    def wp_model(self) -> dict | None:
        if not an.has_pbp_dir(self.league, self.season):
            return None
        from oddsmarkets.basketball.models import winprob as W
        m = _safe("wp model", lambda: W.model_for(self.league, self.season), None)
        return m if m and m.get("ok") else None

    @cached_property
    def elo_season(self) -> dict:
        """{"games": {gid: [pre_h, pre_a, p_home, post_h, post_a]}, "end": {tid: elo after the team's last game}}."""
        g, end = {}, {}
        for row in (self.elo_hist or {}).get("games") or []:
            if int(row[2]) != self.season:
                continue
            g[row[0]] = [row[5], row[6], row[7], row[8], row[9]]
            end[row[3]] = row[8]
            end[row[4]] = row[9]
        return {"games": g, "end": end}

    @cached_property
    def sim(self) -> dict | None:
        if not self.full or self.phase == "offseason":
            return None
        from oddsmarkets.basketball.models import season_sim as SS
        return _safe("season sim", lambda: SS.simulate(self.league, self.season, n=self.sims, seed=self.season,
                                                       state={"store": self.member_store, "ratings": self.ratings}), None)

    @cached_property
    def phase(self) -> str:
        # placeholder ("TBD") playoff games still count here: they mean the playoffs are not over
        sup = an.superseded(self.store)
        gl = {k: g for k, g in (self.store.get("games") or {}).items() if k not in sup and g.get("stype") != "allstar"}
        return season_phase(gl, self.today)

    # ------------------------------------------------------------------ markets
    @cached_property
    def futures(self) -> dict | None:
        if not (self.fetch_markets and self.season == self.current):
            return None
        from oddsmarkets.basketball.sources import markets as MK
        return _safe("futures", lambda: MK.futures(self.league, self.season, store=self.store), None)

    @cached_property
    def game_prices(self) -> dict[str, dict]:
        if not (self.fetch_markets and self.season == self.current):
            return {}
        from oddsmarkets.basketball.sources import markets as MK
        out: dict[str, dict] = {}
        poly = _safe("poly events", lambda: MK._poly_events(self.league), [])
        for k in range(0, 3):
            d = self.today + timedelta(days=k)
            out.update(_safe(f"game prices {d}", lambda: MK.game_prices(self.league, d, store=self.store, poly_events=poly), {}) or {})
        return out



def season_phase(games: dict[str, dict], today: date | None = None) -> str:
    """preseason | regular | playin | playoffs | offseason from the games' stypes and statuses (pending
    games more than three days in the past are stale schedule entries and are ignored)."""
    gl = [g for g in games.values() if g.get("stype") in ("reg", "playin", "post", "cup")]
    if not gl:
        return "preseason"
    stale = str((today or date.today()) - timedelta(days=3))
    played = [g for g in gl if g.get("status") == "post"]
    pending = [g for g in gl if g.get("status") in ("pre", "in") and str(g.get("date") or "")[:10] >= stale]
    if not played:
        return "preseason"
    reg_pending = [g for g in pending if g.get("stype") in ("reg", "cup")]
    if reg_pending:
        return "regular"
    post_played = [g for g in played if g.get("stype") == "post"]
    if any(g.get("stype") == "post" for g in pending) or (post_played and _series_open(gl)):
        return "playoffs"
    if any(g.get("stype") == "playin" for g in pending) or (any(g.get("stype") == "playin" for g in played) and not post_played):
        return "playin"
    if post_played:
        return "offseason"
    return "regular" if pending else "offseason"


def _series_open(gl: list[dict]) -> bool:
    """True when the last playoff game played does not look like a deciding game (a series still running)."""
    return any(g.get("status") == "in" for g in gl)
