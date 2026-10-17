"""
Game Elo, 1997 onward (FiveThirtyEight's NBA Elo recipe).

    E_home = 1 / (1 + 10 ** (-(R_h - R_a + HCA * [not neutral]) / 400))
    R_h <- R_h + K * M * (S_home - E_home),   R_a <- R_a - (same)
    M = (|MOV| + 3) ** 0.8 / (7.5 + 0.006 * D),  D = Elo difference from the winner's side
        (home advantage included)                                   margin-of-victory multiplier
    between seasons: R <- carry * R + (1 - carry) * mean          (carry 0.75 NBA / 0.70 WNBA, mean 1505)
    a team's first game: R = new_team (1300 NBA, 1350 WNBA) in an expansion season, else the mean
    point spread equivalent: (R_h - R_a + HCA) x pts_per_elo     (1/28 NBA, 1/30 WNBA)

Constants per league in config.ELO_DEFAULTS (K 20; HCA 100 NBA / 90 WNBA; carry and pts_per_elo as above). Regular season,
NBA Cup, play-in and playoff games are rated; preseason and All-Star games are not.

`history(league)` runs over every season on disk, never raises on missing data, and caches to
<cache>/elo/<league>.json keyed on the stores' sizes and modification times.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Iterable

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models.config import ELO_DEFAULTS

logger = logging.getLogger(__name__)
VERSION = 1


def _league(league):
    return "wnba" if str(league or "").lower() == "wnba" else "nba"


def expected(rh: float, ra: float, hca: float, neutral: bool = False) -> float:
    return 1.0 / (1.0 + 10.0 ** (-(rh - ra + (0.0 if neutral else hca)) / 400.0))


def mov_mult(mov: float, diff_winner: float) -> float:
    return (abs(mov) + 3.0) ** 0.8 / (7.5 + 0.006 * diff_winner)


def compute(stores: dict[int, dict], league: str = "nba", prm: dict | None = None) -> dict:
    """Elo history over {season: store}: {"games": [...], "current": {tid: elo}, "params", "seasons"}."""
    league = _league(league)
    p = dict(ELO_DEFAULTS[league])
    p.update(prm or {})
    K, HCA, carry, mean, new = p["k"], p["hca"], p["carry"], p["mean"], p["new_team"]
    R: dict[str, float] = {}
    games_out = []
    seasons = sorted(stores)
    first_season = seasons[0] if seasons else None
    names = {}
    for s in seasons:
        st = stores[s] or {}
        for t, v in (st.get("teams") or {}).items():
            names[t] = (v or {}).get("abbr") or names.get(t)
        for t in list(R):
            R[t] = carry * R[t] + (1 - carry) * mean
        rows = G.finished(st.get("games") or {}, league, stypes=G.COUNTED)
        for r in rows:
            h, a = r["home"], r["away"]
            for t in (h, a):
                if t not in R:
                    R[t] = mean if (s == first_season or not R) else new
            rh, ra = R[h], R[a]
            hca = 0.0 if r["neutral"] else HCA
            e = expected(rh, ra, hca)
            sh = 1.0 if r["margin"] > 0 else 0.0
            dw = (rh + hca - ra) if sh else (ra - rh - hca)
            d = K * mov_mult(r["margin"], dw) * (sh - e)
            R[h], R[a] = rh + d, ra - d
            games_out.append([r["id"], str(r["day"]), int(s), h, a, round(rh, 2), round(ra, 2), round(e, 5),
                              round(R[h], 2), round(R[a], 2), r["stype"]])
    return {"cols": ["id", "day", "season", "home", "away", "elo_h_pre", "elo_a_pre", "p_home", "elo_h", "elo_a", "stype"],
            "games": games_out, "current": {t: round(v, 2) for t, v in R.items()}, "params": p, "seasons": seasons,
            "league": league}


def history(league: str = "nba", seasons: Iterable[int] | None = None, stores: dict[int, dict] | None = None,
            use_cache: bool = True) -> dict:
    """Elo for every game of every season on disk (see module docstring). `stores` bypasses disk and cache."""
    league = _league(league)
    if stores is not None:
        return compute(stores, league)
    seasons = sorted(seasons) if seasons is not None else G.seasons_on_disk(league)
    sig = G.signature(league, seasons)
    path = G.cache_root() / "elo" / f"{league}.json"
    if use_cache and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("version") == VERSION and c.get("signature") == sig:
                return c
        except (OSError, ValueError):
            pass
    out = compute(G.all_games(league, seasons), league)
    out["signature"] = sig
    out["version"] = VERSION
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.info("elo cache not written: %s", exc)
    return out


def ratings_before(hist: dict, when: Any) -> dict[str, float]:
    """Each team's latest post-game Elo strictly before day `when` (no season regression applied)."""
    d = str(G.day(when))
    out: dict[str, float] = {}
    for g in hist.get("games") or []:
        if g[1] >= d:
            break
        out[g[3]] = g[8]
        out[g[4]] = g[9]
    return out


def pregame(hist: dict) -> dict[str, float]:
    """{game_id: Elo P(home wins)} for every rated game."""
    return {g[0]: g[7] for g in hist.get("games") or []}


def predict(hist_or_ratings: dict, home: str, away: str, neutral: bool = False, league: str = "nba") -> dict:
    """{"p_home","spread"} from current ratings (a history or a {tid: elo} map)."""
    league = _league(league)
    p = ELO_DEFAULTS[league]
    R = hist_or_ratings.get("current", hist_or_ratings) if isinstance(hist_or_ratings, dict) else {}
    rh, ra = float(R.get(home, p["mean"])), float(R.get(away, p["mean"]))
    hca = 0.0 if neutral else p["hca"]
    return {"p_home": expected(rh, ra, hca), "spread": -(rh - ra + hca) * p["pts_per_elo"]}
