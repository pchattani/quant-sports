"""
Inputs for the game model: a store GAME -> a game_sim spec.

Usage log (from plate appearances, so it is available for any date of a season)
    apps     one row per pitcher appearance: game_pk, date, team (abbr), pitcher, pitches, bf, start
    lineups  one row per batting slot: game_pk, date, team, slot (1-9, order of first PA), batter, opp_sp_hand
Every query takes `before=date` and uses rows strictly before it.

Lineup     GAME.lineups[tid] when posted; else the team's most recent lineup against a starter of the same
           hand as today's opposing starter (else its most recent lineup).
Starter    GAME.probables; else the team's rested (>= 4 days) recent starter with the longest rest.
           Exit model inputs: mean / sd of his pitch counts over his last 10 starts (>= 3 starts; else the
           projection's last-season mean, else 88 / 12), and pitches per batter relative to the league.
Bullpen    relievers = pitchers who appeared for the team in the last 30 days and started < 50 % of their
           games. Availability: unavailable after > 30 pitches yesterday or after pitching on each of the
           last two days; half weight after pitching yesterday; otherwise full. The best three available
           by projected wOBA allowed form the "hi" tier, the rest "mid"; inside a tier relievers are
           weighted by availability x recent batters faced. Rates are mixed per opposing hand.
League     the season's environment (projections.game_env); every projection is moved into it from its own
           environment (`league_from_projections`), so league-average players return it exactly.
Unknown players (no projection) get the league rates moved to replacement level (wOBA ~ -0.020: K odds x1.08,
           hit odds x0.94 for hitters; the mirror for pitchers); a known pitcher batting without a hitting
           projection takes the pitchers' batting rates (`pitcher_batting_rates`).
Park       builder C's park factors when its module exposes them per outcome (centred so the average park is
           neutral on every outcome); else our own multi-season
           home / road event-rate ratios, regressed to 1 with k PA (K 4000, BB 6000, HBP 20000, 1B 8000,
           2B 6000, 3B 3000, HR 4000, outs 20000) per team's home park.
Umpire     K and BB odds of the home-plate umpire's games relative to the league, regressed with k = 4000 PA
           (builder C's umpire zone model when it provides K/BB effects).
Weather    game_sim.weather_mult (temperature, wind; nothing under a closed roof) with coefficients fitted on the
           earlier seasons within parks (`fit_weather`), relative to the venue's own average weather (the park
           factors already carry each park's usual climate).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio
from oddsmarkets.baseball.models import game_sim as G
from oddsmarkets.baseball.models._dio import E, EVENTS, NE

logger = logging.getLogger(__name__)

REPL_HIT = np.array([1.08, 0.93, 1.0, 0.94, 0.93, 0.93, 0.90, 1.0, 1.0])
REPL_PIT = 1.0 / REPL_HIT
PARK_K = np.array([4000, 6000, 20000, 8000, 6000, 3000, 4000, 20000, 20000], float)
UMP_K = 4000.0


def _d(x) -> date | None:
    return _dio.to_date(x)


# ── usage log ────────────────────────────────────────────────────────────────

def usage_from_pa(pa: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(apps, lineups) from a PA table (one season or a slice)."""
    if pa is None or not len(pa):
        return (pd.DataFrame(columns=["game_pk", "date", "team", "pitcher", "pitches", "bf", "start", "throws"]),
                pd.DataFrame(columns=["game_pk", "date", "team", "slot", "batter", "opp_sp_hand", "stand"]))
    fld_team = np.where(pa["top"].to_numpy(), pa["home_team"].to_numpy(), pa["away_team"].to_numpy())
    bat_team = np.where(pa["top"].to_numpy(), pa["away_team"].to_numpy(), pa["home_team"].to_numpy())
    d = pd.DataFrame({"game_pk": pa["game_pk"].to_numpy(), "date": pa["game_date"].astype(str).str[:10].to_numpy(),
                      "team": fld_team, "pitcher": pa["pitcher"].to_numpy(), "pitches": pa["pitches"].to_numpy(),
                      "ab": pa["ab"].to_numpy(), "throws": pa["p_throws"].to_numpy()})
    apps = d.groupby(["game_pk", "team", "pitcher"], sort=False).agg(
        date=("date", "first"), pitches=("pitches", "sum"), bf=("ab", "size"), first=("ab", "min"),
        throws=("throws", "first")).reset_index()
    first = apps.groupby(["game_pk", "team"])["first"].transform("min")
    apps["start"] = apps["first"] == first
    apps = apps.drop(columns=["first"])
    b = pd.DataFrame({"game_pk": pa["game_pk"].to_numpy(), "date": d["date"].to_numpy(), "team": bat_team,
                      "batter": pa["batter"].to_numpy(), "ab": pa["ab"].to_numpy(), "stand": pa["stand"].to_numpy()})
    fb = b.groupby(["game_pk", "team", "batter"], sort=False).agg(date=("date", "first"), ab=("ab", "min"),
                                                                    stand=("stand", "first")).reset_index()
    fb = fb.sort_values(["game_pk", "team", "ab"])
    fb["slot"] = fb.groupby(["game_pk", "team"]).cumcount() + 1
    fb = fb[fb["slot"] <= 9]
    sp = apps[apps["start"]][["game_pk", "team", "throws"]].rename(columns={"team": "fteam", "throws": "opp_sp_hand"})
    fb = fb.merge(sp, on="game_pk", how="left")
    fb = fb[fb["fteam"] != fb["team"]].drop(columns=["fteam", "ab"])
    return apps, fb


@dataclass
class Usage:
    apps: pd.DataFrame
    lineups: pd.DataFrame

    @classmethod
    def from_pa(cls, pa: pd.DataFrame) -> "Usage":
        a, l = usage_from_pa(pa)
        return cls(a, l)

    def extend(self, pa: pd.DataFrame) -> None:
        a, l = usage_from_pa(pa)
        self.apps = pd.concat([self.apps, a], ignore_index=True)
        self.lineups = pd.concat([self.lineups, l], ignore_index=True)

    def lineup(self, team: str, before: date, opp_hand: str | None = None) -> list[str] | None:
        L = self.lineups
        if not len(L):
            return None
        sub = L[(L["team"] == team) & (L["date"] < before.isoformat())]
        if not len(sub):
            return None
        if opp_hand:
            same = sub[sub["opp_sp_hand"] == opp_hand]
            if len(same):
                sub = same
        g = sub[sub["date"] == sub["date"].max()]
        g = g[g["game_pk"] == g["game_pk"].max()].sort_values("slot")
        return [str(x) for x in g["batter"]][:9]

    def starts(self, pitcher: str, before: date, n: int = 10) -> pd.DataFrame:
        A = self.apps
        s = A[(A["pitcher"] == pitcher) & A["start"].astype(bool) & (A["date"] < before.isoformat())]
        return s.sort_values("date").tail(n).astype({"pitches": float, "bf": float})

    def guess_starter(self, team: str, before: date) -> str | None:
        A = self.apps
        s = A[(A["team"] == team) & A["start"].astype(bool) & (A["date"] < before.isoformat())].sort_values("date")
        if not len(s):
            return None
        recent = s.tail(12)
        last = recent.groupby("pitcher")["date"].max()
        rot = list(dict.fromkeys(reversed(recent["pitcher"].tolist())))[:5]
        rest = {p: (before - date.fromisoformat(last[p])).days for p in rot}
        ok = [p for p in rot if rest[p] >= 4] or rot
        return str(max(ok, key=lambda p: rest[p]))

    def bullpen(self, team: str, before: date, days: int = 30) -> pd.DataFrame:
        """Relievers with availability weight and recent batters faced."""
        A = self.apps
        lo = (before - timedelta(days=days)).isoformat()
        s = A[(A["team"] == team) & (A["date"] >= lo) & (A["date"] < before.isoformat())]
        if not len(s):
            return pd.DataFrame(columns=["pitcher", "bf", "avail", "throws"])
        s = s.astype({"bf": float, "pitches": float, "start": bool})
        g = s.groupby("pitcher").agg(bf=("bf", "sum"), starts=("start", "mean"), throws=("throws", "first"))
        g = g[g["starts"] < 0.5]
        y1 = (before - timedelta(days=1)).isoformat()
        y2 = (before - timedelta(days=2)).isoformat()
        p1 = s[s["date"] == y1].groupby("pitcher")["pitches"].sum()
        p2 = s[s["date"] == y2].groupby("pitcher")["pitches"].sum()
        av = []
        for p in g.index:
            a = 1.0
            if p in p1.index:
                a = 0.5
                if p1[p] > 30 or p in p2.index:
                    a = 0.0
            av.append(a)
        g["avail"] = av
        return g.reset_index()


# ── parks and umpires ────────────────────────────────────────────────────────

def park_factors_from_pa(pas: list[pd.DataFrame]) -> dict[str, np.ndarray]:
    """{home team abbr: odds multipliers} from home / road event rates over the given PA tables."""
    acc_home, acc_road = {}, {}
    for pa in pas:
        if pa is None or not len(pa):
            continue
        ev = pa["ev"].to_numpy()
        home = pa["home_team"].to_numpy()
        bat = np.where(pa["top"].to_numpy(), pa["away_team"].to_numpy(), pa["home_team"].to_numpy())
        fld = np.where(pa["top"].to_numpy(), pa["home_team"].to_numpy(), pa["away_team"].to_numpy())
        oh = np.zeros((len(ev), NE))
        oh[np.arange(len(ev)), ev] = 1
        df = pd.DataFrame(oh, columns=EVENTS)
        df["home"] = home
        hc = df.groupby("home")[list(EVENTS)].sum()
        for t, row in hc.iterrows():
            acc_home[t] = acc_home.get(t, 0) + row.to_numpy()
        # road: games where team t batted or fielded away from home
        for who in (bat, fld):
            dd = df[list(EVENTS)].copy()
            dd["t"] = who
            dd = dd[who != home]
            rc = dd.groupby("t")[list(EVENTS)].sum()
            for t, row in rc.iterrows():
                acc_road[t] = acc_road.get(t, 0) + row.to_numpy() / 2.0
    out = {}
    for t, h in acc_home.items():
        r = acc_road.get(t)
        if r is None:
            continue
        nh, nr = h.sum(), r.sum()
        if nh <= 0 or nr <= 0:
            continue
        ratio = (h / nh) / np.maximum(r / nr, 1e-9)
        reg = (nh * ratio + PARK_K) / (nh + PARK_K)
        out[str(t)] = reg / np.exp(np.mean(np.log(reg)))      # keep the overall level neutral
    return out


def park_factors_c(level: str, season: int) -> dict[str, np.ndarray]:
    """Builder C's park factors as {venue id or team abbr: odds multipliers} when its module provides them."""
    mod = _dio.sibling("parks")
    if mod is None:
        return {}
    for fn in ("factors", "park_factors", "for_season"):
        f = getattr(mod, fn, None)
        if not f:
            continue
        try:
            res = f(level, season)
        except Exception:  # noqa: BLE001
            continue
        rows = res.get("parks") if isinstance(res, dict) and isinstance(res.get("parks"), dict) else res
        if not isinstance(rows, dict):
            continue
        out = {}
        for k, v in rows.items():
            if not isinstance(v, dict):
                continue
            src = v.get("factors") if isinstance(v.get("factors"), dict) else v
            m = np.ones(NE)
            hit = False
            for e in EVENTS:
                for alias in (e, e.lower(), {"1B": "single", "2B": "double", "3B": "triple", "HR": "hr", "K": "so",
                                             "BB": "bb"}.get(e, e)):
                    x = src.get(alias)
                    if isinstance(x, (int, float)) and x > 0:
                        m[E[e]] = float(x) / (100.0 if x > 5 else 1.0)
                        hit = True
                        break
            if not hit and isinstance(src.get("runs"), (int, float)):
                rf = float(src["runs"]) / (100.0 if src["runs"] > 5 else 1.0)
                for e in ("1B", "2B", "3B", "HR"):
                    m[E[e]] = rf ** 0.9
                hit = True
            if hit:
                out[str(k)] = m
        if out:
            # builder C's factors are contact ratios that are not centred: across the 30 parks their geometric
            # means ran 0.96-0.98 on singles and 1.02-1.16 on triples (2015-2025). Centre each outcome so the
            # league's average park is neutral, as park_factors_from_pa does.
            M = np.array(list(out.values()))
            g = np.exp(np.mean(np.log(M), axis=0))
            return {k: v / g for k, v in out.items()}
    return {}


def umpire_factors(store_games: dict, pa: pd.DataFrame) -> dict[str, np.ndarray]:
    """{umpire pid: odds multipliers on K and BB} from the season's PA table and the store's umpire_hp."""
    if pa is None or not len(pa):
        return {}
    ump = {int(g["gpk"]) if str(g.get("gpk", "")).isdigit() else None: str(g.get("umpire_hp"))
           for g in (store_games or {}).values() if g.get("umpire_hp")}
    ump.pop(None, None)
    if not ump:
        return {}
    u = pa["game_pk"].map(ump)
    ok = u.notna()
    if not ok.any():
        return {}
    ev = pa["ev"].to_numpy()
    lk, lb = (ev == E["K"]).mean(), (ev == E["BB"]).mean()
    df = pd.DataFrame({"u": u[ok].to_numpy(), "k": (ev[ok.to_numpy()] == E["K"]), "b": (ev[ok.to_numpy()] == E["BB"])})
    g = df.groupby("u").agg(n=("k", "size"), k=("k", "sum"), b=("b", "sum"))
    out = {}
    for uid, r in g.iterrows():
        rk = (r["k"] + UMP_K * lk) / (r["n"] + UMP_K)
        rb = (r["b"] + UMP_K * 1.5 * lb) / (r["n"] + UMP_K * 1.5)
        m = np.ones(NE)
        m[E["K"]] = (rk / (1 - rk)) / (lk / (1 - lk))
        m[E["BB"]] = (rb / (1 - rb)) / (lb / (1 - lb))
        out[str(uid)] = m
    return out


# ── context ──────────────────────────────────────────────────────────────────

def _arr(x) -> np.ndarray:
    a = np.asarray(x, float)
    return a / a.sum()


@dataclass
class Context:
    """Everything needed to price a game on a date."""
    level: str
    season: int
    store: dict
    hitters: dict            # pid -> {"L": arr, "R": arr, "hand": "L|R|S", "all": arr}
    pitchers: dict           # pid -> {"L": arr, "R": arr, "hand": "L|R", "all": arr, "pc_mean": float|None}
    league: dict             # {"LL","LR","RL","RR", "all"}
    usage: Usage
    parks: dict = field(default_factory=dict)     # team abbr or venue id -> mult
    umpires: dict = field(default_factory=dict)
    abbr_to_tid: dict = field(default_factory=dict)
    tid_to_abbr: dict = field(default_factory=dict)
    woba: np.ndarray | None = None
    ppa_league: float = 3.9
    weather_norm: np.ndarray | None = None        # league mean weather multiplier (divided out: rates already
                                                  # reflect the average game's temperature and wind)
    pb_rates: dict | None = None                  # {"L","R"}: a pitcher batting with no hitting projection
    weather_coef: dict | None = None              # fitted weather coefficients (fit_weather); None: the defaults
    weather_ref: dict | None = None               # store whose games give each venue's average weather (else `store`)

    # players
    def hitter(self, pid: str, store_players: dict | None = None) -> dict:
        h = self.hitters.get(str(pid))
        if h:
            return {"pid": str(pid), "bats": h.get("hand") or "R", "rates": {"L": h["L"], "R": h["R"]}}
        sp = (store_players or self.store.get("players") or {}).get(str(pid)) or {}
        bats = (sp.get("bats") or "R")[:1]
        if self.pb_rates and str(pid) in self.pitchers:
            # a pitcher batting (NL parks before 2022) with no hitting projection of his own
            return {"pid": str(pid), "bats": bats, "rates": dict(self.pb_rates), "unknown": True}
        rates = {}
        for th in ("L", "R"):
            bh = G._bat_hand(bats, th)
            rates[th] = _arr(self.league[bh + th] * REPL_HIT)
        return {"pid": str(pid), "bats": bats, "rates": rates, "unknown": True}

    def pitcher(self, pid: str | None, before: date | None = None) -> dict:
        p = self.pitchers.get(str(pid)) if pid else None
        sp = (self.store.get("players") or {}).get(str(pid) or "", {}) or {}
        throws = (p or {}).get("hand") or (sp.get("throws") or "R")[:1]
        if p:
            rates = {"L": p["L"], "R": p["R"]}
        else:
            th = "L" if throws == "L" else "R"
            rates = {"L": _arr(self.league["L" + th] * REPL_PIT), "R": _arr(self.league["R" + th] * REPL_PIT)}
        mu, sd, ppa = 88.0, 12.0, 1.0
        if pid and before is not None and len(self.usage.apps):
            st = self.usage.starts(str(pid), before)
            if len(st) >= 3:
                mu = float(st["pitches"].mean())
                sd = float(max(st["pitches"].std(), 6.0))
                ppa = float(st["pitches"].sum() / max(st["bf"].sum(), 1) / self.ppa_league)
            elif p and p.get("pc_mean"):
                mu = float(p["pc_mean"])
        if not (40 <= mu <= 120):
            mu = 88.0
        return {"pid": pid, "throws": throws, "rates": rates, "pc_mean": mu, "pc_sd": sd, "ppa": float(np.clip(ppa, 0.8, 1.2)),
                "unknown": p is None}

    def quality(self, pid: str) -> float:
        p = self.pitchers.get(str(pid))
        r = p["all"] if p else self.league["all"] * REPL_PIT
        w = self.woba if self.woba is not None else np.array([0, .69, .72, .88, 1.25, 1.58, 2.03, 0, 0])
        return float(np.dot(_arr(r), w))

    def bullpen(self, team_abbr: str, before: date) -> dict:
        bp = self.usage.bullpen(team_abbr, before)
        if not len(bp) or bp["avail"].sum() <= 0:
            return G.neutral_bullpen(self.league)
        bp = bp[bp["avail"] > 0].copy()
        bp["q"] = [self.quality(p) for p in bp["pitcher"]]
        bp = bp.sort_values("q")
        tiers = {"hi": bp.head(3), "mid": bp.iloc[3:] if len(bp) > 3 else bp}
        out = {}
        for name, t in tiers.items():
            # weighted by availability x recent batters faced: a reliever's share of the bullpen's batters is his
            # share of its recent work (the square root used before 2 October 2026 gave the rarely used arms, the
            # weakest, more of the innings than they get)
            w = (t["avail"].astype(float) * t["bf"].astype(float).clip(lower=1)).to_numpy(float)
            w = w / w.sum()
            rL, rR = np.zeros(NE), np.zeros(NE)
            shl = 0.0
            for wi, pid, th in zip(w, t["pitcher"], t["throws"]):
                p = self.pitcher(pid)
                rL += wi * p["rates"]["L"]
                rR += wi * p["rates"]["R"]
                shl += wi * (1.0 if str(th) == "L" else 0.0)
            out[name] = {"rates": {"L": _arr(rL), "R": _arr(rR)}, "share_L": float(shl), "n": int(len(t))}
        return out

    # a full spec
    def spec(self, game: dict, lineups: dict | None = None, starters: dict | None = None) -> dict:
        d = _d(game.get("date")) or date(self.season, 7, 1)
        home, away = str(game.get("home")), str(game.get("away"))
        ha, aa = self.tid_to_abbr.get(home, home), self.tid_to_abbr.get(away, away)
        prob = game.get("probables") or {}
        starters = starters or {}
        sp = {}
        for side, tid, ab in (("home", home, ha), ("away", away, aa)):
            pid = starters.get(side) or prob.get(side) or self.usage.guess_starter(ab, d)
            sp[side] = self.pitcher(str(pid) if pid else None, d)
        lus = {}
        posted = (lineups or game.get("lineups") or {}) or {}
        for side, tid, ab, opp in (("home", home, ha, "away"), ("away", away, aa, "home")):
            lu = posted.get(tid) or posted.get(side)
            if not lu or len(lu) < 9:
                lu = self.usage.lineup(ab, d, sp[opp]["throws"])
            lu = [str(x) for x in (lu or [])][:9]
            hitters = [self.hitter(x) for x in lu]
            while len(hitters) < 9:
                hitters.append(G.neutral_hitter(self.league, "R") | {"unknown": True})
            lus[side] = hitters
        env = np.ones(NE)
        venue = str(game.get("venue") or "")
        park = self.parks.get(venue) if venue in self.parks else self.parks.get(ha)
        if park is not None:
            env = env * park
        roof = ((self.store.get("venues") or {}).get(venue) or {}).get("roof")
        wm = G.weather_mult(game.get("weather"), roof, self.weather_coef)
        if self.weather_norm is None:
            self.weather_norm = weather_norm(self.weather_ref or self.store, self.weather_coef)
        env = env * wm / self.weather_norm.get(venue, self.weather_norm["_league"])
        ump = game.get("umpire_hp")
        if ump and str(ump) in self.umpires:
            env = env * self.umpires[str(ump)]
        return {
            "home": {"lineup": lus["home"], "starter": sp["home"], "bullpen": self.bullpen(ha, d)},
            "away": {"lineup": lus["away"], "starter": sp["away"], "bullpen": self.bullpen(aa, d)},
            "league": self.league, "env": env, "level": self.level,
            "auto_runner": G.auto_runner_rule(self.season, game.get("gtype")),
            # seven-inning doubleheader games in 2020-2021 (Stats API scheduledInnings)
            "innings": int(game.get("scheduled_innings") or 9) if 5 <= int(game.get("scheduled_innings") or 9) <= 9 else 9,
            "meta": {"home_sp": sp["home"]["pid"], "away_sp": sp["away"]["pid"],
                     "lineup_source": {s: ("posted" if (posted.get(t) or posted.get(s)) else "projected")
                                       for s, t in (("home", home), ("away", away))}},
        }


def save_weather(level: str, seasons: list[int]) -> dict:
    """Write models/fitted/weather_<level>.json (fit_weather on `seasons`) for runs without the pitch tables."""
    import json
    res = fit_weather(level, seasons)
    if res.get("source") != "fitted":
        return {"ok": False, "reason": f"{res.get('n_games')} games"}
    p = _dio.fitted_dir() / f"weather_{level}.json"
    p.write_text(json.dumps({k: v for k, v in res.items() if k != "source"}, indent=1), encoding="utf-8")
    return {"ok": True, "path": str(p), **res}


def weather_norm(store: dict, coef: dict | None = None, min_games: int = 20) -> dict:
    """{venue id: geometric mean of game_sim.weather_mult over the store's games at the venue, "_league": over every
    game} (closed roofs count as neutral). A game's weather is taken relative to its venue's mean: the park factors
    already hold each park's usual weather, so dividing by the league mean counted a hot park's heat twice.
    Venues with fewer than `min_games` reports use the league mean."""
    venues = store.get("venues") or {}
    by: dict[str, list] = {}
    allm = []
    for g in (store.get("games") or {}).values():
        if not g.get("weather"):
            continue
        v = str(g.get("venue") or "")
        m = np.log(G.weather_mult(g.get("weather"), (venues.get(v) or {}).get("roof"), coef))
        by.setdefault(v, []).append(m)
        allm.append(m)
    lg = np.exp(np.mean(np.array(allm), axis=0)) if len(allm) >= 50 else np.ones(NE)
    out = {"_league": lg}
    for v, ms in by.items():
        if len(ms) >= min_games:
            out[v] = np.exp(np.mean(np.array(ms), axis=0))
    return out


_WX_CACHE: dict = {}


def fit_weather(level: str, seasons: list[int], min_games: int = 500) -> dict:
    """
    {"temp_hr", "wind_hr", "temp_bip", "n_games", "seasons"}: within-park weather effects fitted on the given
    seasons' regular-season games (open air only). Home runs per plate appearance: logit = venue + a dt + b wind;
    non-home-run hits per non-home-run ball in play: logit = venue + c dt (binomial, IRLS, a light ridge on the
    weather terms). dt and wind as game_sim.weather_terms. The defaults (game_sim) without enough games.
    """
    from oddsmarkets.baseball.models import projections as PJ
    key = (level, tuple(sorted(seasons)))
    if key in _WX_CACHE:
        return _WX_CACHE[key]
    rows = []
    for s in seasons:
        pa = PJ.pa_table(level, s)
        store = _dio.load_store(level, s)
        if not len(pa) or not store.get("games"):
            continue
        pa = pa[pa["game_type"] == "R"]
        ev = pa["ev"].to_numpy()
        bip_nh = np.isin(ev, [E["1B"], E["2B"], E["3B"], E["GO"], E["AO"]])
        hit_nh = np.isin(ev, [E["1B"], E["2B"], E["3B"]])
        g = pd.DataFrame({"gpk": pa["game_pk"].astype(str).to_numpy(), "hr": (ev == E["HR"]).astype(float),
                          "bip": bip_nh.astype(float), "hit": hit_nh.astype(float)}).groupby("gpk").agg(
            pa=("hr", "size"), hr=("hr", "sum"), bip=("bip", "sum"), hit=("hit", "sum"))
        venues = store.get("venues") or {}
        for gpk, r in g.iterrows():
            gm = store["games"].get(gpk)
            if not gm:
                continue
            v = str(gm.get("venue") or "")
            tw = G.weather_terms(gm.get("weather"), (venues.get(v) or {}).get("roof"))
            if tw is None:
                continue
            rows.append((v, tw[0], tw[1], r["pa"], r["hr"], r["bip"], r["hit"]))
    out = {"temp_hr": G.TEMP_HR, "wind_hr": G.WIND_HR, "temp_bip": G.TEMP_BIP, "n_games": len(rows),
           "seasons": sorted(seasons), "source": "default"}
    if len(rows) < min_games:
        # CI holds no earlier season's plate appearances: the committed fit (scripts/mlb_fit.py --only d)
        p = _dio.fitted_dir() / f"weather_{level}.json"
        if p.exists():
            try:
                import json
                out = {**json.loads(p.read_text(encoding="utf-8")), "source": "committed"}
            except Exception:  # noqa: BLE001
                pass
        _WX_CACHE[key] = out
        return out
    df = pd.DataFrame(rows, columns=["v", "dt", "w", "pa", "hr", "bip", "hit"])
    vc = df["v"].value_counts()
    df = df[df["v"].isin(vc.index[vc >= 20])]
    V = pd.get_dummies(df["v"]).to_numpy(float)

    def irls(X, k, n, ridge_cols):
        b = np.zeros(X.shape[1])
        p0 = k.sum() / n.sum()
        b[:V.shape[1]] = np.log(p0 / (1 - p0))
        lam = np.zeros(X.shape[1])
        lam[ridge_cols] = 1.0
        for _ in range(30):
            z = X @ b
            p = 1 / (1 + np.exp(-z))
            W = n * p * (1 - p)
            grad = X.T @ (k - n * p) - lam * b
            H = (X.T * W) @ X + np.diag(lam)
            step = np.linalg.solve(H, grad)
            b = b + step
            if np.abs(step).max() < 1e-9:
                break
        return b
    nv = V.shape[1]
    b_hr = irls(np.c_[V, df["dt"], df["w"]], df["hr"].to_numpy(float), df["pa"].to_numpy(float), [nv, nv + 1])
    b_h = irls(np.c_[V, df["dt"]], df["hit"].to_numpy(float), df["bip"].to_numpy(float), [nv])
    out.update(temp_hr=float(b_hr[nv]), wind_hr=float(b_hr[nv + 1]), temp_bip=float(b_h[nv]), n_games=int(len(df)),
               source="fitted")
    _WX_CACHE[key] = out
    return out


def abbr_map(store: dict, pa: pd.DataFrame | None) -> tuple[dict, dict]:
    """(abbr -> tid, tid -> abbr), joined on game_pk where both are present, else the store's abbr."""
    a2t, t2a = {}, {}
    for tid, t in (store.get("teams") or {}).items():
        if t.get("abbr"):
            a2t[str(t["abbr"])] = str(tid)
            t2a[str(tid)] = str(t["abbr"])
    if pa is not None and len(pa) and store.get("games"):
        g = pa.groupby("game_pk")[["home_team", "away_team"]].first()
        for gpk, row in g.iterrows():
            gm = store["games"].get(str(gpk))
            if not gm:
                continue
            a2t[str(row["home_team"])] = str(gm["home"])
            a2t[str(row["away_team"])] = str(gm["away"])
            t2a[str(gm["home"])] = str(row["home_team"])
            t2a[str(gm["away"])] = str(row["away_team"])
    return a2t, t2a


def rates_from_projection(df: pd.DataFrame, rescale: np.ndarray | None = None) -> dict:
    """{pid: {"L","R","all","hand","pc_mean"}}; `rescale` (odds multipliers) moves every rate vector into another
    league environment (pitchers' projections into the hitters' environment, see `league_from_projections`)."""
    out = {}
    if df is None or not len(df):
        return out
    f = (lambda v: _arr(np.asarray(v, float) * rescale)) if rescale is not None else _arr
    for pid, r in df.iterrows():
        out[str(pid)] = {"L": f(r["rates_L"]), "R": f(r["rates_R"]), "all": f(r["rates"]),
                         "hand": r.get("hand") or "R",
                         "pc_mean": float(r["pc_mean_last"]) if "pc_mean_last" in r and pd.notna(r.get("pc_mean_last")) else None}
    return out


def league_from_projections(hitters: pd.DataFrame | None, pitchers: pd.DataFrame | None,
                            fallback: np.ndarray | None = None) -> tuple[dict, np.ndarray | None, np.ndarray | None]:
    """
    (league dict for game_sim, odds rescale for the hitters' rates, odds rescale for the pitchers'). The odds-ratio
    matchup b*p/l is unbiased only when b, p and l share one environment: a league-average hitter against a
    league-average pitcher must return l. Each projection is centred on its own environment (attrs["env"]: the
    seasons and weights of its counts; hitters and pitchers are weighted differently); both are moved by
    env_game / env into the season's environment (attrs["env_game"], projections.game_env), which is l.
    """
    def env(df, key="env"):
        v = df.attrs.get(key) if df is not None else None
        return None if v is None else np.asarray(v, float)
    env_h, env_p = env(hitters), env(pitchers)
    base = env(hitters, "env_game")
    if base is None:
        base = env(pitchers, "env_game")
    if base is None:
        base = env_h if env_h is not None else (env_p if env_p is not None else fallback)
    if base is None:
        base = G.LEAGUE_DEFAULT.copy()
    base = _arr(base)
    rh = base / np.maximum(_arr(env_h), 1e-9) if env_h is not None else None
    rp = base / np.maximum(_arr(env_p), 1e-9) if env_p is not None else None
    return G.league_split(base) | {"all": base}, rh, rp


def pitcher_batting_rates(hitters: pd.DataFrame | None, league: dict) -> dict | None:
    """{"L","R"} rates for a pitcher batting without a projection of his own: the pitchers' batting rates of the
    projection (attrs["pb_rates"]) with the league's platoon ratios (as a right-handed batter)."""
    pb = hitters.attrs.get("pb_rates") if hitters is not None else None
    if pb is None:
        return None
    pb = _arr(pb)
    env_h = hitters.attrs.get("env")
    if env_h is not None:
        pb = _arr(pb * _arr(league["all"]) / np.maximum(_arr(env_h), 1e-9))      # into the season's environment
    lg = _arr(league["all"])
    return {th: _arr(pb * league["R" + th] / lg) for th in ("L", "R")}


def build_context(level: str, season: int, store: dict | None = None, through: Any = None,
                  hitters: pd.DataFrame | None = None, pitchers: pd.DataFrame | None = None,
                  pa: pd.DataFrame | None = None, park_seasons: int = 3) -> Context:
    """
    Context for pricing games of `season` (rest-of-season projections through the latest data; the usage log
    from the season's PA table, plus the previous season's when the season is young).
    """
    from oddsmarkets.baseball.models import projections as PJ
    store = store if store is not None else _dio.load_store(level, season)
    if pa is None:
        pa = PJ.pa_table(level, season)
    if through is not None and len(pa):
        pa = pa[pa["game_date"] < str(_d(through))]
    part_h, part_p = PJ.aggregates_from_pa(pa) if len(pa) else (None, None)
    if hitters is None:
        dates = (str(pa["game_date"].min())[:10], str(pa["game_date"].max())[:10]) if len(pa) else None
        hitters = PJ.project(level, season, "ros", role="hitter", partial=part_h, partial_pitchers=part_p,
                             partial_dates=dates)
    if pitchers is None:
        pitchers = PJ.project(level, season, "ros", role="pitcher", partial=part_p)
    h_counts = part_h if part_h is not None else PJ.season_aggregates(level, season - 1)[0]
    # the league reference is the projections' own environment, not the season-to-date table (see
    # league_from_projections); the table is only the fallback when a projection carries no environment
    league, rescale_h, rescale = league_from_projections(hitters, pitchers, PJ.league_table(h_counts))
    prev = PJ.pa_table(level, season - 1) if len(pa) < 30000 else pd.DataFrame()
    usage = Usage.from_pa(pd.concat([prev, pa], ignore_index=True) if len(prev) else pa)
    a2t, t2a = abbr_map(store, pa)
    parks = park_factors_c(level, season)
    if not parks:
        pas = [pa] + [PJ.pa_table(level, s) for s in range(season - park_seasons + 1, season)]
        parks = park_factors_from_pa(pas)
    umps = umpire_factors(store.get("games") or {}, pa)
    ww = PJ.woba_weights(season)
    woba = np.array([0, ww["BB"], ww["HBP"], ww["1B"], ww["2B"], ww["3B"], ww["HR"], 0, 0])
    ppa = float(pa["pitches"].mean()) if len(pa) and "pitches" in pa else 3.9
    prev_store = _dio.load_store(level, season - 1)
    wx = fit_weather(level, [s for s in range(season - 3, season) if s in _dio.pitch_seasons(level)])
    return Context(level, season, store, rates_from_projection(hitters, rescale_h), rates_from_projection(pitchers, rescale), league,
                   usage, parks, umps, a2t, t2a, woba, ppa, pb_rates=pitcher_batting_rates(hitters, league),
                   weather_coef=wx, weather_ref=prev_store if prev_store.get("games") else None)


def predict(game: dict, ctx: Context, n: int = G.N_SIMS, seed: int = 0, **kw) -> dict:
    spec = ctx.spec(game, **kw)
    res = G.simulate(spec, n=n, seed=seed)
    res["inputs"] = spec["meta"]
    return res


def for_date(level: str, d: Any, n: int = G.N_SIMS, ctx: Context | None = None, markets: dict | None = None,
             store: dict | None = None) -> dict:
    """
    {"date", "games": {gpk: {"home","away","model": summary, "inputs", "market": game_prices row, "edge": {...}}}}
    for every non-final game of the store on day d (the payload the hub and game centre read). `markets` is a
    `sources.markets.game_prices` result (fetched when None). Never raises per game.
    """
    from oddsmarkets.baseball.sources import markets as MK
    day = _d(d)
    store = store if store is not None else _dio.load_store(level, day.year)
    ctx = ctx or build_context(level, day.year, store)
    mk = markets if markets is not None else MK.game_prices(day, store)
    out = {}
    for g in (store.get("games") or {}).values():
        if str(g.get("date"))[:10] != day.isoformat() or str(g.get("status")) in ("final", "postponed", "cancelled"):
            continue
        gid = str(g.get("gpk"))
        T = store.get("teams") or {}
        if (T.get(str(g.get("home"))) or {}).get("placeholder") or (T.get(str(g.get("away"))) or {}).get("placeholder"):
            out[gid] = {"ok": False, "reason": "opponent not yet decided"}
            continue
        try:
            res = predict(g, ctx, n=n)
        except Exception as exc:  # noqa: BLE001
            out[gid] = {"ok": False, "reason": str(exc)}
            continue
        m = mk.get(gid) or {}
        edge = {}
        if m.get("p_home") is not None:
            edge["home"] = MK.edge(res["p_home"], m["p_home"])
            edge["away"] = MK.edge(1 - res["p_home"], 1 - m["p_home"])
        out[gid] = {"ok": True, "home": str(g["home"]), "away": str(g["away"]), "model": G.summary_for_payload(res),
                    "market": m or None, "edge": edge}
    return {"date": day.isoformat(), "level": level, "games": out}
