"""
Live win probability from the score, the clock, the strength state, empty nets and pregame strength.

The rest of regulation is a Markov chain on the goal difference d (home minus away, -10..10) in 10-second steps,
with the game model's pregame regulation means mu_h, mu_a (goals per 60) as the base rates, so pregame strength
fades exactly as the clock runs down:
    rate_h = mu_h / 60 per minute x strength multiplier, likewise away;
    power play (home 5v4 / 4v3 for the penalty time left): home x k_pp, away x k_sh; 5v3: x k_pp3 / x k_sh3;
    4v4 / 3v3: both x k_even;
    late game: the game model's rule (tied -> x tie_k; trailing by one with <= pull1 minutes, or by two with <= pull2,
    -> trailing side x k_pull and the leader + r_en per minute), and an empty net reported now is honoured for the
    next minute whatever the clock.
At the end of regulation: d > 0 home, d < 0 away, d = 0 overtime, which the game model settles (regular season:
5 minutes of 3-on-3, goal probability 1 - exp(-5 k_ot (mu_h + mu_a) / 60), the scorer home with probability
mu_h / (mu_h + mu_a), else a shootout won by the home side with probability so_home; playoffs: sudden death at
mu_h / (mu_h + mu_a)). In overtime itself the remaining overtime time is used; in a shootout so_home.

`live_wp(state, pregame)`: state {"period", "sec_left" (in the period) or "clock" "MM:SS", "hs", "as",
"home_skaters", "away_skaters", "pp_left" (seconds of the current power play), "home_en", "away_en" (goalie pulled),
"playoff", "season"}; pregame {"mu_h", "mu_a"} (or {"p_home"} alone: means solved for at a 6-goal total).
Returns {"wp_home", "p_reg_home", "p_ot", "secs_left", "source"}. `wp_series(states, pregame)` maps a list of states.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from oddsmarkets.nhl.models import game as GM

K_PP, K_SH, K_PP3, K_SH3, K_EVEN = 2.4, 0.3, 4.0, 0.2, 1.15
DMAX = 10
STEP = 10.0


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


def means_from_p(p_home: float, total: float = 6.0, prm: dict | None = None, season: int | None = None) -> tuple[float, float]:
    """Symmetric regulation means (mu_h, mu_a) whose pregame P(home) is p_home, at a mean total near `total`."""
    prm = prm or GM.params()
    p_home = min(max(float(p_home), 0.03), 0.97)
    lo, hi = -1.5, 1.5
    m = total / 2.0 * 0.97
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        ph = GM.outcome_probs([m * math.exp(mid)], [m * math.exp(-mid)], prm, False, season)["p_home"][0]
        if ph < p_home:
            lo = mid
        else:
            hi = mid
    d = 0.5 * (lo + hi)
    return m * math.exp(d), m * math.exp(-d)


def _ot_home(mu_h, mu_a, prm, playoff, season, ot_left_min: float | None = None, in_so: bool = False) -> float:
    share = mu_h / max(mu_h + mu_a, 1e-9)
    if playoff:
        return share
    if in_so:
        return float(prm["so_home"])
    k = prm["k_ot"][GM.ot_era(season)] if isinstance(prm.get("k_ot"), dict) else float(prm["k_ot"])
    left = 5.0 if ot_left_min is None else max(ot_left_min, 0.0)
    p_dec = 1.0 - math.exp(-left * k * (mu_h + mu_a) / 60.0)
    return p_dec * share + (1 - p_dec) * float(prm["so_home"])


def live_wp(state: dict, pregame: dict | None = None, prm: dict | None = None) -> dict:
    prm = prm or GM.params()
    st = dict(state or {})
    season = st.get("season")
    playoff = bool(st.get("playoff"))
    pg = pregame or {}
    if pg.get("mu_h") and pg.get("mu_a"):
        mu_h, mu_a = float(pg["mu_h"]), float(pg["mu_a"])
    else:
        mu_h, mu_a = means_from_p(pg.get("p_home", 0.54), prm=prm, season=season)
    period = int(st.get("period") or 1)
    sec_in = clock_seconds(st.get("sec_left") if st.get("sec_left") is not None else st.get("clock"))
    hs, as_ = int(st.get("hs") or 0), int(st.get("as") or 0)
    d0 = hs - as_
    final = str(st.get("status") or "").lower().startswith("final")
    if final:
        w = 1.0 if d0 > 0 else (0.0 if d0 < 0 else 0.5)
        return {"wp_home": w, "p_reg_home": None, "p_ot": 0.0, "secs_left": 0.0, "source": "final"}
    if period >= 4:
        if playoff:
            return {"wp_home": _ot_home(mu_h, mu_a, prm, True, season), "p_reg_home": None, "p_ot": 1.0, "secs_left": sec_in,
                    "source": "chain"}
        if d0 != 0:
            return {"wp_home": 1.0 if d0 > 0 else 0.0, "p_reg_home": None, "p_ot": 1.0, "secs_left": 0.0, "source": "chain"}
        return {"wp_home": _ot_home(mu_h, mu_a, prm, False, season, sec_in / 60.0, in_so=period >= 5), "p_reg_home": None,
                "p_ot": 1.0, "secs_left": sec_in, "source": "chain"}
    secs_left = max(0.0, (3 - period) * 1200.0 + sec_in)
    n = 2 * DMAX + 1
    P = np.zeros(n)
    P[min(max(d0, -DMAX), DMAX) + DMAX] = 1.0
    dvals = np.arange(-DMAX, DMAX + 1)
    steps = int(math.ceil(secs_left / STEP))
    hk, ak = int(st.get("home_skaters") or 5), int(st.get("away_skaters") or 5)
    pp_left = float(st.get("pp_left") or (120.0 if hk != ak else 0.0))
    en_h, en_a = bool(st.get("home_en")), bool(st.get("away_en"))
    rh0, ra0 = mu_h / 60.0, mu_a / 60.0
    dt = STEP / 60.0
    for k in range(steps):
        t_left = (secs_left - k * STEP) / 60.0          # minutes left at the start of the step
        el = k * STEP
        mh = ma = 1.0
        if el < pp_left and hk != ak:
            if hk > ak:
                mh, ma = (K_PP3, K_SH3) if hk - ak >= 2 else (K_PP, K_SH)
            else:
                ma, mh = (K_PP3, K_SH3) if ak - hk >= 2 else (K_PP, K_SH)
        elif el < pp_left and hk == ak and hk < 5:
            mh = ma = K_EVEN
        rh = np.full(n, rh0 * mh)
        ra = np.full(n, ra0 * ma)
        tie = dvals == 0
        rh = np.where(tie, rh * prm["tie_k"], rh)
        ra = np.where(tie, ra * prm["tie_k"], ra)
        pull_h = ((dvals == -1) & (t_left <= prm["pull1"])) | ((dvals == -2) & (t_left <= prm["pull2"]))
        pull_a = ((dvals == 1) & (t_left <= prm["pull1"])) | ((dvals == 2) & (t_left <= prm["pull2"]))
        if el < 60.0:
            pull_h = pull_h | (en_h & (dvals < 0))
            pull_a = pull_a | (en_a & (dvals > 0))
        rh2 = np.where(pull_h, rh0 * prm["k_pull"], np.where(pull_a, rh + prm["r_en"], rh))
        ra2 = np.where(pull_a, ra0 * prm["k_pull"], np.where(pull_h, ra + prm["r_en"], ra))
        frac = min(1.0, (secs_left - k * STEP) / STEP)
        ph = np.clip(rh2 * dt * frac, 0, 0.45)
        pa = np.clip(ra2 * dt * frac, 0, 0.45)
        new = P * (1 - ph - pa)
        new[1:] += (P * ph)[:-1]
        new[-1] += (P * ph)[-1]
        new[:-1] += (P * pa)[1:]
        new[0] += (P * pa)[0]
        P = new
    p_reg_h = float(P[dvals > 0].sum())
    p_ot = float(P[dvals == 0].sum())
    wp = p_reg_h + p_ot * _ot_home(mu_h, mu_a, prm, playoff, season)
    return {"wp_home": float(min(max(wp, 0.0), 1.0)), "p_reg_home": p_reg_h, "p_ot": p_ot, "secs_left": secs_left,
            "source": "chain"}


def period_length(period: int, playoff: bool = False) -> float:
    """Seconds in a period: 1200 in regulation and playoff overtime, 300 in regular-season overtime, 0 in a shootout."""
    period = int(period or 1)
    if period <= 3 or playoff:
        return 1200.0
    return 300.0 if period == 4 else 0.0


def elapsed(period: int, sec_left: float, playoff: bool = False) -> float:
    """Elapsed game seconds at `sec_left` on the clock of `period` (regular-season overtime is 5 minutes, so its
    elapsed time runs 3600 -> 3900; a shootout sits at 3900; playoff overtime periods are 20 minutes each)."""
    period = int(period or 1)
    if period <= 3 or playoff:
        return (period - 1) * 1200.0 + 1200.0 - min(max(sec_left, 0.0), 1200.0)
    if period == 4:
        return 3600.0 + 300.0 - min(max(sec_left, 0.0), 300.0)
    return 3900.0


def wp_series(states: list[dict], pregame: dict | None = None, prm: dict | None = None) -> list[list]:
    """[[game_seconds_elapsed, wp_home], ...] for a sequence of states (e.g. one per goal / penalty / period edge).
    A state may carry its own "elapsed" (game seconds); otherwise it is derived from period and clock, with
    regular-season overtime 5 minutes long."""
    prm = prm or GM.params()
    out = []
    for s in states:
        r = live_wp(s, pregame, prm)
        if s.get("elapsed") is not None:
            el = float(s["elapsed"])
        else:
            period = int(s.get("period") or 1)
            el = elapsed(period, clock_seconds(s.get("sec_left") if s.get("sec_left") is not None else s.get("clock")),
                         bool(s.get("playoff")))
        out.append([round(el, 1), round(r["wp_home"], 4)])
    return out


def _is_playoff_id(gid) -> bool:
    s = str(gid or "").split(".")[0]
    return len(s) >= 6 and s[4:6] == "03"


def from_events(ev: Any, pregame: dict | None = None, prm: dict | None = None, game_id: str | None = None,
                playoff: bool | None = None, season: int | None = None) -> list[list]:
    """WP after every goal, penalty and faceoff of a normalised events frame (builder D's normalise_events
    columns: game_id, period, sec (elapsed game seconds), type, score_home, score_away (before the event),
    n_h, n_v, h_net, v_net). One row per kept event, at the event's own elapsed seconds; a goal's row carries the
    score after it. Regular-season overtime is 5 minutes (elapsed 3600 -> 3900), playoff overtime 20 minutes a
    period; `playoff` defaults to the game id's type digits ("03")."""
    import pandas as pd
    if ev is None or len(ev) == 0:
        return []
    e = ev[ev["game_id"] == game_id] if game_id is not None and "game_id" in ev else ev
    keep = e["type"].isin(["GOAL", "PENL", "FAC"]) if "type" in e else pd.Series(True, index=e.index)
    e = e[keep]
    if playoff is None:
        gid = game_id if game_id is not None else (e["game_id"].iloc[0] if "game_id" in e and len(e) else None)
        playoff = _is_playoff_id(gid)
    states = []
    for r in e.itertuples(index=False):
        per = int(getattr(r, "period", 1) or 1)
        el = float(getattr(r, "sec", 0.0) or 0.0)
        if el != el:
            el = 0.0
        if per <= 3 or playoff:
            sec_left = max(0.0, per * 1200.0 - el)
        elif per == 4:
            sec_left = max(0.0, 3900.0 - el)
        else:
            sec_left = 0.0
        hs = int(getattr(r, "score_home", 0) or 0)
        as_ = int(getattr(r, "score_away", 0) or 0)
        if getattr(r, "type", None) == "GOAL" and (per <= 4 or playoff):
            ih = getattr(r, "is_home", None)
            if ih == ih and ih is not None:
                if int(ih) == 1:
                    hs += 1
                else:
                    as_ += 1
        states.append({"period": per, "sec_left": sec_left, "elapsed": el, "hs": hs, "as": as_, "playoff": playoff,
                       "season": season,
                       "home_skaters": int(getattr(r, "n_h", 5) or 5), "away_skaters": int(getattr(r, "n_v", 5) or 5),
                       "home_en": getattr(r, "h_net", 1) == 0, "away_en": getattr(r, "v_net", 1) == 0})
    return wp_series(states, pregame, prm)
