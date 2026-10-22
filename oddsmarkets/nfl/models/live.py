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
every play of the ESPN record (for the game-centre chart of ours against ESPN's) on pre-snap states (`espn_states`);
`epa_series` gives our EP and EPA on the same states, for game pages built from ESPN before nflverse publishes.
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


# ESPN play types that are not a scrimmage state (the WP and EP models take only downs 1-4 between the 1 and 99)
NON_STATE = ("Kickoff", "Timeout", "Official Timeout", "Two-minute warning", "End Period", "End of Half", "End of Game",
             "End of Regulation", "Extra Point", "Two-Point", "Coin Toss")
# NFL gamebook codes ESPN's play text uses for a few teams ("Timeout #1 by ARZ")
TEXT_CODES = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "JAC": "JAX", "LAR": "LA", "WSH": "WAS"}
KICKOFF_YL100 = 70.0         # a kickoff's receiving team is given 1st and 10 at its own 30 (about the 2025 average start)
_TO_RE = None


def _timeout_team(text, home, away):
    global _TO_RE
    if _TO_RE is None:
        import re
        _TO_RE = re.compile(r"Timeout #(\d) by ([A-Z]{2,3})")
    m = _TO_RE.search(str(text or ""))
    if not m:
        return None, None
    t = TEXT_CODES.get(m.group(2), m.group(2))
    return (t if t in (home, away) else None), int(m.group(1))


_PUNT_RE = None


def _punt_yl100(text, team, home, away, yl):
    """ESPN's yardsToEndzone on a punt is measured for either side (about half each in 2026), so the yard line is
    checked against the text: "punts 56 yards to BLT 23" puts the line of scrimmage 23 + 56 = 79 yards from the end
    zone (ESPN's value or 100 minus it, whichever is nearer)."""
    global _PUNT_RE
    if _PUNT_RE is None:
        import re
        _PUNT_RE = re.compile(r"punts (\d+) yards? to (end zone|([A-Z]{2,3}) (\d{1,2})\b)")
    m = _PUNT_RE.search(str(text or ""))
    if not m:
        return yl
    dist = int(m.group(1))
    if m.group(2) == "end zone":
        land = 0
    else:
        side, n = TEXT_CODES.get(m.group(3), m.group(3)), int(m.group(4))
        if side not in (home, away) and n != 50:
            return yl
        land = n if (side != team or n == 50) else 100 - n
    c = land + dist
    y = float(yl)
    return y if abs(y - c) <= abs(100 - y - c) else 100 - y


def espn_states(plays: list, home, away=None, season: int | None = None) -> pd.DataFrame:
    """One row per ESPN play with the PRE-SNAP game state (22 Oct 2026). ESPN's homeScore / awayScore are the score
    AFTER the play while down, distance and yard line are its start, so the score before a play is the previous play's;
    timeouts used are read from "Timeout #n by XXX" plays (reset each half; two in overtime); the team that kicked off
    first receives the second half. Columns: seq, qtr, type, poss, kind ("scrim" a down 1-4 state, "kick" a kickoff,
    given to the receiving team at its own 30, "none" otherwise), down, ydstogo, yardline_100, game / half seconds
    left, half, home / away score before (hs, as) and after, the possession side's and the defence's timeouts left,
    receive_2h_ko, espn (ESPN's home WP after the play)."""
    P = [p for p in plays if isinstance(p, (list, tuple)) and len(p) >= 11]
    if away is None:
        away = next((p[3] for p in P if p[3] and p[3] != home), None)
    opener = next((p[3] for p in P if str(p[7] or "").startswith("Kickoff") and int(p[1] or 1) == 1 and p[3]), None)
    rows = []
    hs = as_ = 0.0
    half_now, used = None, {}
    for p in P:
        q = int(p[1] or 1)
        h = 1 if q <= 2 else (2 if q <= 4 else 3)
        if h != half_now:
            half_now, used = h, {home: 0, away: 0}
        typ = str(p[7] or "")
        if typ == "Timeout":
            t, n = _timeout_team(p[8], home, away)
            if t is not None:
                used[t] = max(used.get(t, 0), n)
        gs, hsec = secs_left(q, p[2])
        team = p[3] if p[3] in (home, away) else None
        down, dist, yl = p[4], p[5], p[6]
        kind = "none"
        if "Punt" in typ and team is not None and yl is not None:
            yl = _punt_yl100(p[8], team, home, away, yl)
        if team is not None and not typ.startswith(NON_STATE) and down in (1, 2, 3, 4) and yl is not None and 1 <= float(yl) <= 99:
            kind, poss = "scrim", team
            dn, dt, y = float(down), float(dist or 10), float(yl)
        elif typ.startswith("Kickoff") and team is not None and away is not None:
            kind, poss = "kick", (away if team == home else home)
            dn, dt, y = 1.0, 10.0, KICKOFF_YL100
        else:
            poss, dn, dt, y = team, np.nan, np.nan, np.nan
        n_to = 2 if h == 3 else 3
        other = (away if poss == home else home) if poss is not None else None
        ha = float(p[9]) if p[9] is not None else hs
        aa = float(p[10]) if p[10] is not None else as_
        rows.append({"seq": p[0], "qtr": q, "type": typ, "poss": poss, "kind": kind, "down": dn, "ydstogo": dt,
                     "yardline_100": y, "game_seconds_remaining": gs, "half_seconds_remaining": hsec, "half": float(h),
                     "hs": hs, "as": as_, "hs_after": ha, "as_after": aa,
                     "pos_to": float(max(n_to - used.get(poss, 0), 0)) if poss is not None else np.nan,
                     "def_to": float(max(n_to - used.get(other, 0), 0)) if other is not None else np.nan,
                     "receive_2h_ko": 1.0 if (h == 1 and poss is not None and poss == opener) else 0.0,
                     "espn": p[11] if len(p) > 11 else None})
        hs, as_ = ha, aa
    S = pd.DataFrame(rows)
    S.attrs["home"], S.attrs["away"] = home, away
    return S


def wp_series(rec: dict, pregame: dict | None = None, home: str | None = None, season: int | None = None) -> list[list]:
    """[[seq, ours, espn, state]] for each play of an ESPN record (plays: [seq, qtr, clock_s, team, down, dist, yl100,
    type, text, home_score, away_score, wp_home]; state: the value is the model's on this play's own state, not carried): our home WP BEFORE the snap (as on the nflverse pages), from B's model
    on the pre-snap state (espn_states). Plays without a state (timeouts, ends of quarters) carry the last value; a
    kickoff is valued as the receiving team's 1st and 10 at its 30 with the score after the try. Until 22 Oct 2026
    the post-play score was paired with the pre-snap field position (a touchdown counted twice on its own play), and
    timeouts and kickoffs were scored as yard line 0 or the kicking side's 1st and 10, which made the line jump."""
    plays = [p for p in (rec.get("plays") or []) if isinstance(p, (list, tuple)) and len(p) >= 11]
    if not plays:
        return []
    mu = float((pregame or {}).get("margin", 0.0) or 0.0)
    sigma = float(GM.params()["sigma"])
    S = espn_states(plays, home, rec.get("away"), season)
    ours = np.full(len(S), np.nan)
    st = S[S["kind"] != "none"]
    if len(st):
        hp = (st["poss"] == home).to_numpy()
        sign = np.where(hp, 1.0, -1.0)
        X = pd.DataFrame({"score_differential": sign * (st["hs"].to_numpy(float) - st["as"].to_numpy(float)),
                          "game_seconds_remaining": st["game_seconds_remaining"].to_numpy(float),
                          "half_seconds_remaining": st["half_seconds_remaining"].to_numpy(float), "qtr": st["qtr"].to_numpy(float),
                          "half": st["half"].to_numpy(float), "down": st["down"].to_numpy(float), "ydstogo": st["ydstogo"].to_numpy(float),
                          "yardline_100": st["yardline_100"].to_numpy(float), "posteam_timeouts_remaining": st["pos_to"].to_numpy(float),
                          "defteam_timeouts_remaining": st["def_to"].to_numpy(float), "home": hp.astype(float),
                          "pos_spread": sign * mu, "receive_2h_ko": st["receive_2h_ko"].to_numpy(float),
                          "season": int(season or 2026)})
        fit = _b_fit()
        pw = None
        if fit is not None:
            try:
                from oddsmarkets.nfl.models import wp as WP
                pw = np.asarray(WP.state_wp(fit, X), float)
            except Exception as exc:  # noqa: BLE001
                logger.info("live: batched wp failed (%s); fallback", exc)
        if pw is None:
            pw = np.array([fallback_wp(d, ep_simple(y, dn, dt), m, sigma, g, int(q)) for d, y, dn, dt, m, g, q in
                           zip(X["score_differential"], X["yardline_100"], X["down"], X["ydstogo"], X["pos_spread"],
                               X["game_seconds_remaining"], X["qtr"])])
        ours[st.index.to_numpy()] = np.where(hp, pw, 1.0 - pw)
    pre = (pregame or {}).get("p_home")
    last = float(pre) if pre is not None else fallback_wp(0.0, 0.0, mu, sigma, 3600.0, 1)
    final = str(rec.get("status") or "").lower() in ("final", "post", "status_final")
    out = []
    for k, r in enumerate(S.itertuples(index=False)):
        v = ours[k]
        if r.type == "End of Game" or (final and k == len(S) - 1 and r.kind == "none"):
            v = 1.0 if r.hs_after > r.as_after else (0.0 if r.hs_after < r.as_after else 0.5)
        if not np.isfinite(v):
            v = last
        last = v
        out.append([plays[k][0], round(float(v), 4), plays[k][11] if len(plays[k]) > 11 else None,
                    bool(r.kind != "none" or r.type == "End of Game" or (final and k == len(S) - 1))])
    return out


def _ep_fit():
    try:
        from oddsmarkets.nfl.models import ep as EP
        return EP.current_fit()
    except Exception as exc:  # noqa: BLE001
        logger.info("live: EP fit unavailable (%s)", exc)
        return None


def epa_series(rec: dict, home: str | None = None, season: int | None = None, roof: str | None = None) -> list[list]:
    """[[seq, ep_before, epa]] for each ESPN play with a scrimmage state (others [seq, None, None]), from our EP model
    (models/ep.py) on the pre-snap state (espn_states): EPA = EP after - EP before, where EP after is the points
    scored on the play (touchdown 7, field goal 3, safety 2, + for the scoring side; the try is not counted, as in
    the EP model), else the next scrimmage play's EP (sign flipped on a change of possession; none across a kickoff),
    else 0 at the end of a half. Provisional: nflverse's states are more exact (enforced penalties, play timing)."""
    plays = [p for p in (rec.get("plays") or []) if isinstance(p, (list, tuple)) and len(p) >= 11]
    fit = _ep_fit() if plays else None
    if not plays or fit is None:
        return []
    from oddsmarkets.nfl.models import _io
    from oddsmarkets.nfl.models import ep as EP
    S = espn_states(plays, home, rec.get("away"), season)
    away = S.attrs.get("away")
    out = [[p[0], None, None] for p in plays]
    sc = S[S["kind"] == "scrim"]
    if not len(sc):
        return out
    hp = (sc["poss"] == home).to_numpy()
    sign = np.where(hp, 1.0, -1.0)
    rc = _io.ROOF_CODE.get(str(roof).lower()) if roof else None
    X = pd.DataFrame({"down": sc["down"].to_numpy(float), "ydstogo": sc["ydstogo"].to_numpy(float),
                      "yardline_100": sc["yardline_100"].to_numpy(float),
                      "half_seconds_remaining": sc["half_seconds_remaining"].to_numpy(float), "half": sc["half"].to_numpy(float),
                      "qtr": sc["qtr"].to_numpy(float),
                      "score_differential": sign * (sc["hs"].to_numpy(float) - sc["as"].to_numpy(float)),
                      "posteam_timeouts_remaining": sc["pos_to"].to_numpy(float),
                      "defteam_timeouts_remaining": sc["def_to"].to_numpy(float), "home": hp.astype(float),
                      "roof_code": float(rc) if rc is not None else np.nan, "season": int(season or 2026)})
    ep = np.asarray(EP.predict(fit, X), float)
    idx = sc.index.to_numpy()
    poss = sc["poss"].to_numpy(object)
    half = sc["half"].to_numpy(float)
    kick = S["kind"].to_numpy(object) == "kick"
    for j, i in enumerate(idx):
        r = S.iloc[i]
        dh, da = r["hs_after"] - r["hs"], r["as_after"] - r["as"]
        if dh > 0 or da > 0:
            pts, scorer = (dh, home) if dh >= da else (da, away)
            v = 7.0 if pts >= 6 else (3.0 if pts == 3 else (2.0 if pts == 2 else float(pts)))
            after = v if scorer == poss[j] else -v
        elif j + 1 < len(idx) and half[j + 1] == half[j] and not kick[i + 1:idx[j + 1]].any():
            after = ep[j + 1] if poss[j + 1] == poss[j] else -ep[j + 1]
        else:
            after = 0.0
        out[i] = [plays[i][0], round(float(ep[j]), 3), round(float(after - ep[j]), 3)]
    return out
