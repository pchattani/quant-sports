"""
Live win probability from an ESPN game state, blended with pregame strength.

Primary: builder B's win-probability model (`wp.state_wp` on its current fit), fed the live state with our pregame
expected margin as the possession team's spread (`pos_spread`), so the pregame strength fades with the clock exactly as
that model learned (nflfastR-style spread_time = spread * exp(-4 elapsed)).

Fallback (no fit on disk, or a state the model cannot take):
    WP_home = Phi((D + E + mu * f) / (sigma * sqrt(f) + 0.5)),  f = seconds left / 3600 (overtime: 600 / 3600)
D = home minus away score; E = the possession's expected points from the home side (+ for home possession), from a
linear field-position approximation EP = 6.3 - 0.07 * yardline_100 - 0.35 (down - 1) - 0.03 (distance - 10) clipped to
[-1, 6]; mu = pregame expected home margin; sigma = the game model's margin sd. At zero time a non-tied game is decided.

`live_wp(rec, pregame)` returns {"wp_home", "source", "espn_wp_home", "secs_left"}; `wp_series(rec, pregame)` scores
every play of the ESPN record (for the game-centre chart of ours against ESPN's).
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

from oddsmarkets.nfl.models import game as GM

logger = logging.getLogger(__name__)

_FIT: Any = None
_FIT_TRIED = False


def _b_fit():
    global _FIT, _FIT_TRIED
    if not _FIT_TRIED:
        _FIT_TRIED = True
        try:
            from oddsmarkets.nfl.models import wp as WP
            _FIT = WP.current_fit()
        except Exception as exc:  # noqa: BLE001
            logger.info("live: B's WP fit unavailable (%s)", exc)
            _FIT = None
    return _FIT


def clock_seconds(clock) -> float:
    if clock is None:
        return 0.0
    if isinstance(clock, (int, float)):
        return float(clock)
    s = str(clock).strip()
    if ":" in s:
        mm, ss = s.split(":", 1)
        try:
            return 60.0 * float(mm) + float(ss)
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def secs_left(period, clock) -> tuple[float, float]:
    """(game seconds left in regulation, half seconds left); overtime returns (clock, clock)."""
    q = int(period or 1)
    c = clock_seconds(clock)
    if q >= 5:
        return c, c
    game = (4 - q) * 900 + c
    half = ((2 - q) * 900 + c) if q <= 2 else ((4 - q) * 900 + c)
    return float(game), float(half)


def ep_simple(yl100, down, dist) -> float:
    try:
        y = float(yl100)
    except (TypeError, ValueError):
        return 0.0
    d = float(down or 1)
    t = float(dist or 10)
    return float(np.clip(6.3 - 0.07 * y - 0.35 * (d - 1) - 0.03 * (t - 10), -1.0, 6.0))


def fallback_wp(diff: float, ep_home: float, mu: float, sigma: float, game_secs: float, period: int) -> float:
    f = (600.0 if period >= 5 else max(game_secs, 0.0)) / 3600.0
    if f <= 0:
        return 1.0 if diff > 0 else (0.0 if diff < 0 else 0.5)
    return float(ndtr((diff + ep_home + mu * f) / (sigma * math.sqrt(f) + 0.5)))


def live_wp(rec: dict, pregame: dict | None = None, season: int | None = None, home: str | None = None) -> dict:
    """rec: the ESPN compact live record (CONTRACT.md); pregame: {"margin"} (expected home margin) or game.predict."""
    mu = float((pregame or {}).get("margin", 0.0) or 0.0)
    sigma = float(GM.params()["sigma"])
    hs, as_ = float(rec.get("home_score") or 0), float(rec.get("away_score") or 0)
    period = int(rec.get("period") or 1)
    gs, hsec = secs_left(period, rec.get("clock"))
    status = str(rec.get("status") or "").lower()
    espn = None
    plays = rec.get("plays") or []
    if plays and isinstance(plays[-1], (list, tuple)) and len(plays[-1]) >= 12:
        espn = plays[-1][11]
    if status in ("final", "post", "status_final") or (gs <= 0 and period >= 4 and hs != as_):
        return {"wp_home": 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5), "source": "final", "espn_wp_home": espn,
                "secs_left": 0.0}
    poss = rec.get("possession")
    home_poss = None
    if poss is not None and home is not None:
        home_poss = str(poss) == str(home)
    fit = _b_fit()
    if fit is not None and home_poss is not None and rec.get("yardline_100") is not None:
        try:
            from oddsmarkets.nfl.models import wp as WP
            sign = 1.0 if home_poss else -1.0
            st = pd.DataFrame([{
                "score_differential": sign * (hs - as_), "game_seconds_remaining": gs, "half_seconds_remaining": hsec,
                "qtr": period, "half": 3 if period >= 5 else (1 if period <= 2 else 2),
                "down": float(rec.get("down") or 1), "ydstogo": float(rec.get("distance") or 10),
                "yardline_100": float(rec.get("yardline_100")), "posteam_timeouts_remaining": float(rec.get("pos_timeouts", 3) or 3),
                "defteam_timeouts_remaining": float(rec.get("def_timeouts", 3) or 3), "home": 1.0 if home_poss else 0.0,
                "pos_spread": sign * mu, "receive_2h_ko": float(rec.get("receive_2h_ko", 0) or 0),
                "season": int(season or 2026)}])
            p = float(WP.state_wp(fit, st)[0])
            return {"wp_home": p if home_poss else 1.0 - p, "source": "wp_model", "espn_wp_home": espn, "secs_left": gs}
        except Exception as exc:  # noqa: BLE001
            logger.info("live: wp model failed (%s); fallback", exc)
    ep = ep_simple(rec.get("yardline_100"), rec.get("down"), rec.get("distance"))
    ep_home = 0.0 if home_poss is None else (ep if home_poss else -ep)
    return {"wp_home": fallback_wp(hs - as_, ep_home, mu, sigma, gs, period), "source": "fallback",
            "espn_wp_home": espn, "secs_left": gs}


def wp_series(rec: dict, pregame: dict | None = None, home: str | None = None, season: int | None = None) -> list[list]:
    """[[seq, ours, espn]] for each play of an ESPN record (plays: [seq, qtr, clock_s, team, down, dist, yl100, type,
    text, home_score, away_score, wp_home]). B's model is called once for all plays with a possession and yard line;
    the rest use the fallback."""
    plays = [p for p in (rec.get("plays") or []) if isinstance(p, (list, tuple)) and len(p) >= 11]
    if not plays:
        return []
    mu = float((pregame or {}).get("margin", 0.0) or 0.0)
    sigma = float(GM.params()["sigma"])
    ours = [None] * len(plays)
    fit = _b_fit()
    idx, rows = [], []
    for k, p in enumerate(plays):
        hs, as_ = float(p[9] or 0), float(p[10] or 0)
        q = int(p[1] or 1)
        gs, hsec = secs_left(q, p[2])
        hp = (str(p[3]) == str(home)) if (home is not None and p[3] is not None) else None
        if fit is not None and hp is not None and p[6] is not None:
            sign = 1.0 if hp else -1.0
            idx.append((k, hp))
            rows.append({"score_differential": sign * (hs - as_), "game_seconds_remaining": gs,
                         "half_seconds_remaining": hsec, "qtr": q, "half": 3 if q >= 5 else (1 if q <= 2 else 2),
                         "down": float(p[4] or 1), "ydstogo": float(p[5] or 10), "yardline_100": float(p[6]),
                         "posteam_timeouts_remaining": 3.0, "defteam_timeouts_remaining": 3.0, "home": 1.0 if hp else 0.0,
                         "pos_spread": sign * mu, "receive_2h_ko": 0.0, "season": int(season or 2026)})
        else:
            ep = ep_simple(p[6], p[4], p[5])
            eh = 0.0 if hp is None else (ep if hp else -ep)
            ours[k] = fallback_wp(hs - as_, eh, mu, sigma, gs, q)
    if rows:
        try:
            from oddsmarkets.nfl.models import wp as WP
            pw = WP.state_wp(fit, pd.DataFrame(rows))
            for (k, hp), v in zip(idx, pw):
                ours[k] = float(v) if hp else 1.0 - float(v)
        except Exception as exc:  # noqa: BLE001
            logger.info("live: batched wp failed (%s)", exc)
            for k, hp in idx:
                p = plays[k]
                ours[k] = live_wp({"home_score": p[9], "away_score": p[10], "period": p[1], "clock": p[2],
                                   "possession": None, "status": "in"}, pregame, season, home)["wp_home"]
    return [[p[0], round(float(o), 4), p[11] if len(p) > 11 else None] for p, o in zip(plays, ours)]
