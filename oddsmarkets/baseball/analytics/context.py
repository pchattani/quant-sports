"""
SeasonContext: everything the catalogues and pages of one (level, season) read, loaded lazily and once.

* `store`, `people`, `phase` ("preseason" | "regular" | "postseason" | "offseason"), team id maps.
* `model(name)`: one builder B/C/D model's season output (`for_season`), isolated: a model that raises or is
  not ready gives {"ok": False, "reason"} and is listed in `model_errors`, never an exception.
* `agg()`: the season's regular-season counting tables from one chunked pass over the pitch table
  (pitchagg.flags summed per hitter, pitcher, team and pitcher x pitch type), cached on disk under
  <cache>/analytics/agg/ keyed on the Parquet file, so light seasons and re-runs skip the pass.
* `scores()`: builder B's per-pitch stuff / location / pitching scores and swing-decision values (one
  scoring pass over the season, cached as Parquet), for game pages, zone grids and decision maps.
* `wpa()`: builder C's per-PA win expectancy, WPA, leverage and RE24 (re24.statcast_season, cached).
* `bip()`: builder C's per-ball xwOBA+ table (xwoba.load_bip).
Memory: one season of pitches at a time; `release()` drops the frames.
"""
from __future__ import annotations

import gc
import hashlib
import importlib
import logging
import time
import traceback
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import pitchagg as PG

logger = logging.getLogger(__name__)
AGG_VERSION = "agg-4"
SCORES_VERSION = "scores-1"
WPA_VERSION = "wpa-1"
CHUNK = 150_000

# name -> (module, call); every call returns a dict
_B = ("physics", "stuff", "location", "pitching", "tunneling", "swing", "battrack", "fatigue")
_C = ("xwoba", "catchprob", "framing", "umpire", "re24", "war")


def _file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        try:
            st = p.stat()
            h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
        except (AttributeError, OSError):
            h.update(str(p).encode())
        h.update(b"|")
    return h.hexdigest()[:16]


class SeasonContext:
    def __init__(self, level: str, season: int, full: bool = True, today: date | None = None, current: bool = False,
                 sims: int = 20000, fetch_markets: bool = False, use_models: bool = True):
        self.level, self.season, self.full = level, int(season), full
        self.today = today or date.today()
        self.current = current
        self.sims = sims
        self.fetch_markets = fetch_markets
        self.use_models = use_models
        self.store = an.load_store(level, season)
        self.people = an.load_people()
        self.teams = self.store.get("teams") or {}
        self.games = self.store.get("games") or {}
        self.players = self.store.get("players") or {}
        self.a2t = an.abbr_to_tid(self.store)
        self.model_errors: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self._models: dict[str, dict] = {}
        self._agg: dict | None = None
        self._frame: pd.DataFrame | None = None
        self._scores: pd.DataFrame | None = None
        self._wpa: pd.DataFrame | None = None
        self._bip: pd.DataFrame | None = None
        self._gctx = None
        self._gctx_tried = False
        self._markets: dict | None = None
        self._sim: dict | None = None
        self.phase = self._phase()

    # ------------------------------------------------------------------ basics
    def _phase(self) -> str:
        try:
            from oddsmarkets.baseball.models import season_sim as SS
            ph = SS.phase(self.store)
        except Exception:                                        # noqa: BLE001
            ph = "regular"
        if ph == "complete":
            return "offseason"
        if ph == "preseason" and any((g or {}).get("status") == "final" for g in self.games.values()):
            return "regular"
        return ph

    def has_pitches(self) -> bool:
        return an.pitch_path(self.level, self.season).exists()

    def tid(self, abbr: Any) -> str | None:
        if abbr is None:
            return None
        return self.a2t.get(str(abbr).upper())

    def name(self, pid: Any) -> str:
        return an.player_name(self.store, pid, self.people)

    def team_games(self) -> int:
        """Most regular-season games any team has completed (qualification thresholds scale with it)."""
        n: dict[str, int] = {}
        for g in self.games.values():
            if (g or {}).get("gtype") == "R" and g.get("status") == "final":
                for t in (str(g.get("home")), str(g.get("away"))):
                    n[t] = n.get(t, 0) + 1
        return max(n.values()) if n else 0

    # ------------------------------------------------------------------ models
    def model(self, name: str) -> dict:
        if name in self._models:
            return self._models[name]
        t0 = time.perf_counter()
        res: Any
        if not self.use_models:
            res = {"ok": False, "reason": "models disabled for this run"}
        else:
            try:
                res = self._call(name)
            except Exception as exc:                             # noqa: BLE001 - a model never takes a catalogue down
                logger.warning("model %s %s %s failed: %s\n%s", name, self.level, self.season, exc, traceback.format_exc(limit=4))
                res = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        if not isinstance(res, dict):
            res = {"ok": False, "reason": "no result"}
        if res.get("ok") is False or res.get("available") is False:
            self.model_errors[name] = str(res.get("reason") or "not available")
        self._models[name] = res
        self.timings[f"model {name}"] = time.perf_counter() - t0
        return res

    def _call(self, name: str) -> dict:
        L, S = self.level, self.season
        if name in _B or name in _C:
            if not self.has_pitches():
                return {"ok": False, "reason": f"no pitch table for {L} {S}"}
            mod = importlib.import_module(f"oddsmarkets.baseball.models.{name}")
            return mod.for_season(L, S)
        if name == "parks":
            from oddsmarkets.baseball.models import parks
            return parks.park_factors(L, S)
        if name == "stabilise":
            from oddsmarkets.baseball.models import stabilise
            return {"ok": True, "metrics": stabilise._fitted(L) or {}}
        if name == "proj_next":
            from oddsmarkets.baseball.models import projections as PJ
            r = PJ.for_season(L, S + 1, "next")
            return {"ok": bool(r.get("hitters") or r.get("pitchers")), **r}
        if name == "proj_pre":
            # the projection made before the season from the three seasons before it: cached on those seasons' inputs
            from oddsmarkets.baseball.analytics import fallbacks
            from oddsmarkets.baseball.models import projections as PJ
            parts = [str(getattr(PJ, "VERSION", ""))]
            for s_ in range(S - 3, S):
                for q in (an.pitch_path(L, s_), *fallbacks.agg_paths(L, s_), an.pitch_path("aaa", s_)):
                    parts.append(f"{q.name}:{_file_key(q) if q.exists() else '-'}")
            cp = an.an_cache() / "proj" / f"{L}_{S}_pre_{hashlib.sha1('|'.join(parts).encode()).hexdigest()[:16]}.json"
            r = an.read_json(cp)
            if r is None:
                r = PJ.for_season(L, S, "next")
                r = {"ok": bool(r.get("hitters") or r.get("pitchers")), **r}
                try:
                    for old in cp.parent.glob(f"{L}_{S}_pre_*.json"):
                        old.unlink(missing_ok=True)
                    an.write_json(cp, r)
                except Exception:                                # noqa: BLE001
                    pass
            return r
        if name == "awards":
            from oddsmarkets.baseball.models import awards as AW
            mk = (self.markets() or {}).get("awards") if self.full else None
            r = AW.for_season(L, S, markets=mk)
            return {"ok": True, **r}
        if name == "history":
            from oddsmarkets.baseball.models import history as H
            return H.build(L)
        raise KeyError(name)

    # ------------------------------------------------------------------ pitch tables
    def frame(self) -> pd.DataFrame:
        """Regular-season pitches of the season (SEASON_COLS)."""
        if self._frame is None:
            t0 = time.perf_counter()
            self._frame = PG.load(self.level, self.season, PG.SEASON_COLS, PG.REGULAR)
            self.timings["load pitches"] = time.perf_counter() - t0
        return self._frame

    def release(self) -> None:
        self._frame = None
        self._scores = None
        self._wpa = None
        self._bip = None
        gc.collect()

    def agg(self) -> dict:
        """{"bat","pit","bat_team","fld_team","pit_pt","bat_ex","pit_ex","pa","lines","bat_last","pit_last"}."""
        if self._agg is not None:
            return self._agg
        path = an.pitch_path(self.level, self.season)
        if not path.exists():
            self._agg = {}
            return self._agg
        key = _file_key(path) + AGG_VERSION
        cp = an.an_cache() / "agg" / f"{self.level}_{self.season}_{key}.pkl"
        if cp.exists():
            try:
                self._agg = pd.read_pickle(cp)
                return self._agg
            except Exception:                                    # noqa: BLE001
                pass
        t0 = time.perf_counter()
        df = self.frame()
        out: dict[str, Any] = {}
        if len(df):
            acc: dict[str, list] = {"bat": [], "pit": [], "bat_team": [], "fld_team": [], "pit_pt": [], "bat_pt": []}
            for lo in range(0, len(df), CHUNK):
                part = df.iloc[lo:lo + CHUNK]
                fl = PG.flags(part)
                acc["bat"].append(PG.aggregate(part, fl, "batter"))
                acc["pit"].append(PG.aggregate(part, fl, "pitcher"))
                acc["bat_team"].append(PG.aggregate(part, fl, PG.team_of(part, "bat")))
                acc["fld_team"].append(PG.aggregate(part, fl, PG.team_of(part, "fld")))
                key2 = part["pitcher"].astype(str) + "|" + PG._s(part, "pitch_type")
                acc["pit_pt"].append(PG.aggregate(part, fl, key2))
                del fl
            for k, parts in acc.items():
                if parts:
                    out[k] = pd.concat(parts).groupby(level=0).sum()
            out["bat_ex"] = PG.extras(df, "batter")
            out["pit_ex"] = PG.extras(df, "pitcher")
            pa = PG.pa_table(df)
            out["pa"] = pa
            out["lines"] = PG.pitcher_lines(pa)
            out["bat_last"] = PG.last_team(df, "batter", "bat")
            out["pit_last"] = PG.last_team(df, "pitcher", "fld")
            out["dates"] = [str(df["game_date"].min())[:10], str(df["game_date"].max())[:10]]
        self._agg = out
        self.timings["pitch pass"] = time.perf_counter() - t0
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            for old in cp.parent.glob(f"{self.level}_{self.season}_*.pkl"):
                old.unlink(missing_ok=True)
            pd.to_pickle(out, cp)
        except Exception:                                        # noqa: BLE001
            pass
        return out

    def scores(self) -> pd.DataFrame | None:
        """Per pitch (regular season and postseason): game_pk, at_bat_number, pitch_number, stuff, location,
        pitching (builder B, 100 = average) and swing decisions (dv, swing_adv, p_sw); None when B's models
        are not available."""
        if self._scores is not None:
            return self._scores
        path = an.pitch_path(self.level, self.season)
        if not path.exists() or not self.use_models:
            return None
        try:
            from oddsmarkets.baseball.models import location, pitching, prep, stuff, swing
            sm, lm, pm = stuff.model_for(self.level, self.season), location.model_for(self.level, self.season), \
                pitching.model_for(self.level, self.season)
            wm = swing.model_for(self.level, self.season)
        except Exception as exc:                                 # noqa: BLE001
            self.model_errors["scores"] = str(exc)
            return None
        if not (sm.get("ok") and lm.get("ok") and pm.get("ok")):
            self.model_errors["scores"] = "stuff / location / pitching model not ready"
            return None
        sig = hashlib.sha1(repr((SCORES_VERSION, _file_key(path), sm.get("seasons"), sm.get("scale"), lm.get("scale"),
                                 pm.get("scale"), wm.get("seasons") if wm.get("ok") else None)).encode()).hexdigest()[:16]
        cp = an.an_cache() / "scores" / f"{self.level}_{self.season}_{sig}.parquet"
        if cp.exists():
            try:
                self._scores = pd.read_parquet(cp)
                return self._scores
            except Exception:                                    # noqa: BLE001
                pass
        t0 = time.perf_counter()
        try:
            df = prep.prepared(self.level, self.season)
            sc = pitching.season_scores(self.level, self.season, df=df, models=(sm, lm, pm))
            keep = ["game_pk", "at_bat_number", "pitch_number", "stuff", "location", "pitching"]
            out = sc[[c for c in keep if c in sc]].copy()
            del sc
            if wm.get("ok"):
                dec = swing.decisions(df[swing.usable(df)], wm)
                d2 = dec[["game_pk", "at_bat_number", "pitch_number", "dv", "swing_adv", "p_sw"]]
                out = out.merge(d2, on=["game_pk", "at_bat_number", "pitch_number"], how="outer")
                del dec
            del df
            gc.collect()
            for c in ("game_pk", "at_bat_number", "pitch_number"):
                out[c] = out[c].astype(np.int64)
            for c in out.columns[3:]:
                out[c] = out[c].astype(np.float32)
            self._scores = out
            cp.parent.mkdir(parents=True, exist_ok=True)
            for old in cp.parent.glob(f"{self.level}_{self.season}_*.parquet"):
                old.unlink(missing_ok=True)
            out.to_parquet(cp, index=False)
        except Exception as exc:                                 # noqa: BLE001
            logger.warning("per-pitch scores %s %s failed: %s", self.level, self.season, exc)
            self.model_errors["scores"] = f"{type(exc).__name__}: {exc}"
            self._scores = None
        self.timings["scores"] = time.perf_counter() - t0
        return self._scores

    def wpa(self) -> pd.DataFrame | None:
        """Per PA (regular season): game_pk, at_bat_number, batter, pitcher, we_before, we_after, wpa (batting side),
        li, re24 (builder C's run and win expectancy)."""
        if self._wpa is not None:
            return self._wpa
        path = an.pitch_path(self.level, self.season)
        if not path.exists() or not self.use_models:
            return None
        cp = an.an_cache() / "wpa" / f"{self.level}_{self.season}_{_file_key(path)}_{WPA_VERSION}.parquet"
        if cp.exists():
            try:
                self._wpa = pd.read_parquet(cp)
                return self._wpa
            except Exception:                                    # noqa: BLE001
                pass
        t0 = time.perf_counter()
        try:
            from oddsmarkets.baseball.models import re24
            res = re24.statcast_season(self.level, self.season, with_wpa=True, count=False)
            pa = res["pa"] if res else None
            if pa is None or not len(pa):
                return None
            keep = [c for c in ("game_pk", "at_bat_number", "batter", "pitcher", "half", "inning", "we_before", "we_after", "wpa",
                                "li", "re24", "lead") if c in pa]
            out = pa[keep].copy()
            out["batter"] = out["batter"].map(_sid)
            out["pitcher"] = out["pitcher"].map(_sid)
            for c in ("game_pk", "at_bat_number"):
                out[c] = out[c].astype(np.int64)
            self._wpa = out
            cp.parent.mkdir(parents=True, exist_ok=True)
            for old in cp.parent.glob(f"{self.level}_{self.season}_*.parquet"):
                old.unlink(missing_ok=True)
            out.to_parquet(cp, index=False)
        except Exception as exc:                                 # noqa: BLE001
            logger.warning("WPA %s %s failed: %s", self.level, self.season, exc)
            self.model_errors["wpa"] = f"{type(exc).__name__}: {exc}"
            self._wpa = None
        self.timings["wpa"] = time.perf_counter() - t0
        return self._wpa

    def bip(self) -> pd.DataFrame | None:
        if self._bip is not None:
            return self._bip
        if not self.has_pitches() or not self.use_models:
            return None
        try:
            from oddsmarkets.baseball.models import xwoba
            x = self.model("xwoba")
            if not x.get("ok"):
                return None
            b = xwoba.load_bip(self.level, self.season)
            if b is not None:
                b = b.copy()
                for c in ("game_pk", "at_bat_number"):
                    b[c] = pd.to_numeric(b[c], errors="coerce").fillna(0).astype(np.int64)
                b["batter"] = b["batter"].map(_sid)
                b["pitcher"] = b["pitcher"].map(_sid)
            self._bip = b
        except Exception as exc:                                 # noqa: BLE001
            self.model_errors["bip"] = str(exc)
            self._bip = None
        return self._bip

    # ------------------------------------------------------------------ game model, simulation, markets
    def game_ctx(self):
        """Builder D's game-model context (projections, usage, parks, umpires), built once; None on failure."""
        if self._gctx is None and not self._gctx_tried:
            self._gctx_tried = True
            if not self.use_models:
                self.model_errors["game_ctx"] = "models disabled for this run"
                return None
            t0 = time.perf_counter()
            try:
                from oddsmarkets.baseball.models import game_inputs as GI
                self._gctx = GI.build_context(self.level, self.season, self.store)
            except Exception as exc:                             # noqa: BLE001
                logger.warning("game context %s %s failed: %s", self.level, self.season, exc)
                self.model_errors["game_ctx"] = f"{type(exc).__name__}: {exc}"
            self.timings["game ctx"] = time.perf_counter() - t0
        return self._gctx

    def sim(self) -> dict:
        """Builder D's season / postseason simulation (season_sim.for_season), with the game model's pair matrix
        when the game context is available."""
        if self._sim is None:
            t0 = time.perf_counter()
            try:
                from oddsmarkets.baseball.models import season_sim as SS
                ctx = self.game_ctx() if self.level == "mlb" else None
                self._sim = SS.for_season(self.level, self.season, n=self.sims, use_model=ctx is not None, ctx=ctx)
            except Exception as exc:                             # noqa: BLE001
                self._sim = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
            if not self._sim.get("available"):
                self.model_errors["season_sim"] = str(self._sim.get("reason"))
            self.timings["season sim"] = time.perf_counter() - t0
        return self._sim

    def markets(self) -> dict:
        """Kalshi / Polymarket futures and game prices (builder D's sources.markets); {} when not fetched."""
        if self._markets is None:
            self._markets = {}
            if self.fetch_markets and self.level == "mlb":
                t0 = time.perf_counter()
                try:
                    from oddsmarkets.baseball.sources import markets as MK
                    fut = MK.futures(self.season, self.store)
                    games = {}
                    for d in (self.today, self.today.fromordinal(self.today.toordinal() + 1)):
                        games.update(MK.game_prices(d, self.store) or {})
                    self._markets = {"futures": fut, "games": games, "awards": _award_markets(fut)}
                except Exception as exc:                         # noqa: BLE001
                    logger.warning("markets failed: %s", exc)
                    self.model_errors["markets"] = str(exc)
                self.timings["markets"] = time.perf_counter() - t0
        return self._markets


def _award_markets(fut: dict) -> dict:
    """futures()["awards"] keyed as awards.for_season expects ("al_mvp", "nl_cy", ...)."""
    out = {}
    for k, v in ((fut or {}).get("awards") or {}).items():
        kk = str(k).lower().replace("roty", "roy").replace("cya", "cy").replace("cy_young", "cy")
        out[kk] = v
    return out


def _sid(x: Any) -> str | None:
    if x is None:
        return None
    try:
        if isinstance(x, float) and not np.isfinite(x):
            return None
        return str(int(x))
    except (TypeError, ValueError):
        s = str(x)
        return s if s and s != "nan" else None


def frame_rows(obj: Any) -> pd.DataFrame | None:
    """builder C's {"cols","rows"} back to a DataFrame (pid as str)."""
    if not obj or not isinstance(obj, dict) or "cols" not in obj:
        return None
    df = pd.DataFrame(obj.get("rows") or [], columns=obj["cols"])
    if "pid" in df:
        df["pid"] = df["pid"].map(_sid)
    return df
