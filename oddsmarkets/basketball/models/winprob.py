"""
Live win probability, win probability added (WPA), leverage, clutch, excitement and comeback.

Model
-----
A game state is (margin m = home - away, seconds left tau, possession p = +1 home / -1 away / 0
unknown, pregame expected home margin s, league). tau is the regulation time left (or the time left in
the current overtime), T the regulation length (2880 s NBA, 2400 s WNBA) and u = tau / T. If the rest
of the game were a random walk with drift s / T per second and variance proportional to time, the home
side would win with probability Phi((m + s u + c p) / (sigma sqrt(tau))). We fit the logistic
analogue with time-varying coefficients:

    logit P(home wins) = b1 m / sqrt(tau + K) + b2 m u / sqrt(tau + K)
                       + b3 s u / sqrt(tau + K) + b4 p / sqrt(tau + K) + b5 p u / sqrt(tau + K)

* no intercept: a pick'em (s = 0) at tip-off is exactly 0.5, and home court enters through s;
* s = -spread_home (DraftKings via ESPN pickcenter); with no line, s = DEFAULT_HCA[league] at a home
  venue and 0 at a neutral one;
* K (seconds) regularises the end of the game (m / sqrt(K) at tau = 0) and is picked from K_GRID by
  log-likelihood; b by Newton/IRLS with a small ridge (`_io.logistic_fit`);
* a finished game (tau = 0 after regulation, m != 0) is 1 or 0 exactly; a tie at tau = 0 is overtime.
Fouls to give are not in the model (no team-foul counts in the compact play-by-play).

The model is fitted on every play-by-play state (after each play) of past games with the final result
as the label; `states_from_pbp` builds those states from the compact play-by-play (`compact_pbp`),
taking possession from builder A's parsed possessions when given and otherwise inferring it from the
play text (made shot / defensive rebound / turnover / last free throw switch it). Possession is the state
*after* the play, so a made basket, turnover or made last free throw already hands the ball over, and a
missed field goal (or missed last free throw) leaves a loose ball worth p = side * (2 r - 1) to the
shooting side, with r = OREB_FG (OREB_FT) the offensive-rebound rate: the miss itself carries most of the
lost possession, the defensive rebound only the rest, the offensive rebound the recovery.

WPA
---
Baseball convention: every play's dWP is credited in full to *both* teams, each in its own terms (+dWP
to the home side, -dWP to the away side), so a team's players sum to that team's change in win
probability. Within a team:
* the acting team (the play's team): its listed participants share it, the first 1 - ASSIST_SHARE and
  any team-mates (the assister) ASSIST_SHARE;
* the other team: its listed participants (blocker, stealer, fouled player) share DEF_SHARE and its
  five on the floor (builder A's lineups) split the rest equally; with no listed participant the five
  share all of it (defence on a made or missed shot, a rebound conceded);
* the acting team with no listed participant (team rebound, timeout, substitution) likewise credits
  its five on the floor;
* a team with nobody to credit (no lineups and no participant; the final step to 1 or 0) books it to
  "unattributed"[team].
So, for each team exactly,

    sum(team's players' WPA) + unattributed[team] = team's WP(final) - WP(tip-off)

(and hence sum(home) - sum(away) + unattributed[home] - unattributed[away] = 2 (WP(final) - WP(tip-off))).
exactly. Leverage index LI = |dWP/dm| at the state before the play divided by its mean over the
fitting states (1 = an average possession). Clutch = the NBA definition (last 5 minutes of the 4th or
overtime, margin within 5). Excitement = sum |dWP| over the game; comeback = the winner's minimum WP.
"""
from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _io

MODEL_VERSION = "wp-2"

K_GRID = [2.0, 5.0, 10.0, 20.0, 40.0, 80.0]
RIDGE = 1e-3
DEFAULT_HCA = {"nba": 2.5, "wnba": 2.0}       # points, used only when the game has no line
ASSIST_SHARE = 0.3
DEF_SHARE = 0.5          # a listed defender's (blocker, stealer, fouled player) share of his side's credit
OREB_FG = 0.27           # offensive-rebound rate on a missed field goal (loose-ball possession value)
OREB_FT = 0.14           # offensive-rebound rate on a missed last free throw
CLUTCH_S = 300
CLUTCH_MARGIN = 5
FEATURES = ["m", "m_u", "s_u", "p", "p_u"]
STATE_COLS = ["game_id", "margin", "t_left", "period", "poss", "exp_margin", "league", "home_win"]


# ============================================================================ states

def t_left(league: str, period: int, clock_s: float) -> float:
    """Regulation seconds left (in the current overtime period once past regulation)."""
    p = int(period)
    if p <= _io.REG_PERIODS:
        return (_io.REG_PERIODS - p) * _io.PERIOD_S.get(str(league).lower(), 720) + float(clock_s)
    return float(clock_s)


def exp_margin(game: dict | None, league: str = "nba") -> float:
    """Pregame expected home margin: -spread_home if there is a line, else DEFAULT_HCA (0 when neutral)."""
    g = game or {}
    odds = g.get("odds") or {}
    sp_ = odds.get("spread_home")
    if sp_ is not None:
        try:
            return -float(sp_)
        except (TypeError, ValueError):
            pass
    return 0.0 if g.get("neutral") else DEFAULT_HCA.get(str(league).lower(), 2.5)


def make_state(margin: float, period: int, clock_s: float, poss: int = 0, exp_margin_: float = 0.0, league: str = "nba") -> dict:
    return {"margin": float(margin), "t_left": t_left(league, period, clock_s), "period": int(period), "poss": int(poss),
            "exp_margin": float(exp_margin_), "league": league}


def _features(df: pd.DataFrame, K: float) -> np.ndarray:
    lg = df["league"].astype(str).str.lower().to_numpy() if "league" in df else np.full(len(df), "nba")
    T = np.where(lg == "wnba", 2400.0, 2880.0)
    tau = np.clip(df["t_left"].to_numpy(float), 0, None)
    u = np.clip(tau / T, 0.0, 1.0)
    den = np.sqrt(tau + K)
    m = df["margin"].to_numpy(float)
    s = df["exp_margin"].to_numpy(float) if "exp_margin" in df else np.zeros(len(df))
    p = df["poss"].to_numpy(float) if "poss" in df else np.zeros(len(df))
    return np.column_stack([m / den, m * u / den, s * u / den, p / den, p * u / den])


def _over(df: pd.DataFrame) -> np.ndarray:
    """Final states: no time left, at least regulation played, not tied."""
    return ((df["t_left"].to_numpy(float) <= 0) & (df["period"].to_numpy(int) >= _io.REG_PERIODS)
            & (df["margin"].to_numpy(float) != 0))


def fit_wp(states: Any, k_grid: Iterable[float] = K_GRID) -> dict:
    """Fit the win-probability model on game states (DataFrame or list of dicts with STATE_COLS; the label
    is home_win 0/1). Returns {"ok","version","K","beta","features","n","loglik","li_ref","by_K"}."""
    df = _io.as_frame(states, STATE_COLS)
    if df.empty or "home_win" not in df:
        return {"ok": False, "reason": "no states"}
    df = df.dropna(subset=["margin", "t_left", "home_win"])
    df = df[~_over(df)]
    if len(df) < 100:
        return {"ok": False, "reason": f"only {len(df)} states"}
    y = df["home_win"].to_numpy(float)
    best, by_k = None, {}
    P = RIDGE * np.eye(len(FEATURES))
    for K in k_grid:
        X = _features(df, K)
        res = _io.logistic_fit(X, y, P)
        by_k[str(K)] = res["loglik"]
        if best is None or res["loglik"] > best[1]["loglik"]:
            best = (K, res)
    K, res = best
    model = {"ok": True, "version": MODEL_VERSION, "K": float(K), "beta": [float(b) for b in res["beta"]], "features": FEATURES,
             "n": int(len(df)), "loglik": float(res["loglik"]), "by_K": by_k, "home_win_rate": float(y.mean())}
    g = _slope(model, df)
    model["li_ref"] = float(np.mean(g)) if len(g) else 1.0
    return model


def _wp_frame(model: dict, df: pd.DataFrame) -> np.ndarray:
    X = _features(df, model["K"])
    p = _io.sigmoid(X @ np.asarray(model["beta"], float))
    over = _over(df)
    p = np.where(over, (df["margin"].to_numpy(float) > 0).astype(float), p)
    return p


def wp(model: dict, state: dict | pd.DataFrame | list) -> float | np.ndarray:
    """P(home wins) for one state dict (float) or a DataFrame / list of states (array). A state needs margin,
    and t_left or (period, clock_s); optional poss, exp_margin (or spread_home / neutral), league, period."""
    single = isinstance(state, dict)
    rows = [state] if single else state
    df = _io.as_frame(rows).copy()
    if "league" not in df:
        df["league"] = "nba"
    if "t_left" not in df:
        df["t_left"] = [t_left(l, p, c) for l, p, c in zip(df["league"], df["period"], df["clock_s"])]
    if "period" not in df:
        df["period"] = 1
    if "exp_margin" not in df:
        if "spread_home" in df:
            df["exp_margin"] = -pd.to_numeric(df["spread_home"], errors="coerce").fillna(0.0)
        else:
            df["exp_margin"] = 0.0
    if "poss" not in df:
        df["poss"] = 0
    df["exp_margin"] = df["exp_margin"].fillna(0.0)
    df["poss"] = df["poss"].fillna(0)
    out = _wp_frame(model, df)
    return float(out[0]) if single else out


def _slope(model: dict, df: pd.DataFrame) -> np.ndarray:
    """|dWP / d margin| by central difference (one point each way)."""
    if df.empty:
        return np.zeros(0)
    up, dn = df.copy(), df.copy()
    up["margin"] = up["margin"] + 1
    dn["margin"] = dn["margin"] - 1
    X1, X0 = _features(up, model["K"]), _features(dn, model["K"])
    b = np.asarray(model["beta"], float)
    return np.abs(_io.sigmoid(X1 @ b) - _io.sigmoid(X0 @ b)) / 2.0


def leverage(model: dict, states: pd.DataFrame | dict) -> float | np.ndarray:
    single = isinstance(states, dict)
    df = _io.as_frame([states] if single else states)
    li = _slope(model, df) / max(model.get("li_ref") or 1.0, 1e-9)
    return float(li[0]) if single else li


# ============================================================================ play-by-play -> states

def _pbp_plays(pbp: dict) -> list[list]:
    plays = [list(p) + [None] * (14 - len(p)) for p in (pbp or {}).get("plays") or []]
    plays.sort(key=lambda p: (int(p[1] or 0), -float(p[2] if p[2] is not None else 0), int(p[0] or 0)))
    return plays


def _is_sub(text: str) -> bool:
    t = text.lower()
    return "enters the game" in t or "substitution" in t


def infer_possession(plays: list[list], home: str, away: str, team_of: dict | None = None) -> list[int]:
    """Possession after each play (+1 home, -1 away, 0 unknown) from the play text and flags: a made field
    goal or the last made free throw hands the ball over, a defensive rebound or steal / turnover changes it,
    an offensive rebound keeps it; otherwise the last known possession carries on (reset at each period)."""
    out, cur, last_period = [], 0, None
    for p in plays:
        _seq, per, _clk, _typ, team, parts, _x, _y, val, shooting, scoring = p[:11]
        text = str(p[13] or "").lower()
        if per != last_period:
            cur, last_period = 0, per
        side = 1 if team == home else -1 if team == away else 0
        if side == 0 and parts and team_of:
            t0 = team_of.get(str(parts[0]))
            side = 1 if t0 == home else -1 if t0 == away else 0
        if "free throw" in text:
            last = any(s in text for s in ("1 of 1", "2 of 2", "3 of 3"))
            if last and scoring:
                cur = -side if side else cur
            elif side:
                cur = side
        elif shooting:
            cur = -side if scoring and side else (side or cur)
        elif "defensive rebound" in text or "defensive team rebound" in text:
            cur = side or cur
        elif "offensive rebound" in text or "offensive team rebound" in text:
            cur = side or cur
        elif "rebound" in text:
            cur = side or cur
        elif "turnover" in text or "bad pass" in text or "traveling" in text or "lost ball" in text or "offensive foul" in text \
                or "violation" in text and "kicked" not in text:
            cur = -side if side else cur
        elif "steal" in text:
            cur = side or cur
        elif "jump ball" in text or "end of" in text:
            cur = 0 if "end of" in text else cur
        out.append(cur)
    return out


def _poss_from_events(possessions: list[dict], times: np.ndarray, home: str) -> tuple[np.ndarray, np.ndarray]:
    """Possession (+1 home / -1 away / 0) after each play at elapsed time t, from parsed possessions: the first
    possession that has not ended by t (one in progress, or the next one when t falls in the gap after a made
    basket / dead ball before it starts); 0 after a period's last possession."""
    if not possessions:
        return np.zeros(len(times), int)
    ps = sorted(possessions, key=lambda q: (float(q.get("start_t") or 0), float(q.get("end_t") or 0)))
    ends = np.maximum.accumulate(np.array([float(q.get("end_t") or 0) for q in ps]))
    sides = np.array([1 if q.get("team") == home else -1 for q in ps])
    pers = np.array([int(q.get("period") or 0) for q in ps])
    j = np.searchsorted(ends, times, side="right")
    ok = j < len(ps)
    jj = np.clip(j, 0, len(ps) - 1)
    return np.where(ok, sides[jj], 0), np.where(ok, pers[jj], 0)


def _team_of(game: dict) -> dict:
    m = {}
    for tid, b in ((game or {}).get("box") or {}).items():
        for r in b.get("players") or []:
            m[str(r[0])] = tid
        for r in b.get("dnp") or []:
            m.setdefault(str(r[0]), tid)
    return m


def _parsed(parsed: Any) -> tuple[list[dict] | None, list[dict] | None]:
    """(possessions, events) from builder A's GameEvents (object or dict) or a bare possessions list."""
    if parsed is None:
        return None, None
    if isinstance(parsed, list):
        return parsed, None
    get = parsed.get if isinstance(parsed, dict) else (lambda k, d=None: getattr(parsed, k, d))
    return get("possessions"), get("events")


def _poss_by_index(possessions: list[dict], events: list[dict], plays: list[list], home: str) -> np.ndarray | None:
    """Possession after each play using the parser's event indices: after event i the ball belongs to the first
    possession whose end_i > i, if it is in the same period. None when the indices are unavailable."""
    if not possessions or not events or any("end_i" not in q for q in possessions):
        return None
    ps = sorted(possessions, key=lambda q: int(q["end_i"]))
    ends = np.array([int(q["end_i"]) for q in ps])
    sides = np.array([1 if q.get("team") == home else -1 for q in ps])
    pers = np.array([int(q.get("period") or 0) for q in ps])
    idx = {e.get("seq"): (int(e.get("i", k)), int(e.get("period") or 0)) for k, e in enumerate(events)}
    out = np.zeros(len(plays), float)
    for k, p in enumerate(plays):
        hit = idx.get(p[0]) or idx.get(str(p[0]))
        if hit is None:
            return None
        i, per = hit
        j = int(np.searchsorted(ends, i, side="right"))
        if j < len(ps) and pers[j] in (per, 0):
            out[k] = sides[j]
    return out


def _play_side(p: list, home: str, away: str, team_of: dict) -> int:
    team = p[4]
    if team not in (home, away) and p[5]:
        team = team_of.get(str(p[5][0]))
    return 1 if team == home else -1 if team == away else 0


def _is_ft(text: str) -> bool:
    return "free throw" in text


def _last_ft(text: str) -> bool:
    return any(s in text for s in ("1 of 1", "2 of 2", "3 of 3"))


def _loose_ball(plays: list[list], poss: np.ndarray, home: str, away: str, team_of: dict) -> np.ndarray:
    """After a missed field goal or a missed last free throw the ball is loose: possession value
    side * (2 r - 1), r the offensive-rebound rate, instead of the shooting side keeping it until the rebound."""
    out = poss.copy()
    for k, p in enumerate(plays):
        shooting, scoring = p[9], p[10]
        if not shooting or scoring:
            continue
        text = str(p[13] or "").lower()
        if _is_ft(text) and not _last_ft(text):
            continue
        side = _play_side(p, home, away, team_of)
        if side:
            r = OREB_FT if _is_ft(text) else OREB_FG
            out[k] = side * (2.0 * r - 1.0)
    return out


def _lineups_by_seq(parsed: Any) -> dict:
    """{seq: {team: (5 ids)}} from builder A's GameEvents (events + lineups), else {}."""
    if parsed is None or isinstance(parsed, list):
        return {}
    get = parsed.get if isinstance(parsed, dict) else (lambda k, d=None: getattr(parsed, k, d))
    ev, lu = get("events") or [], get("lineups") or []
    if len(ev) != len(lu):
        return {}
    out = {}
    for e, l in zip(ev, lu):
        if l:
            out[e.get("seq")] = l
            out[str(e.get("seq"))] = l
    return out


def states_from_pbp(pbp: dict, game: dict, possessions: Any = None, league: str = "nba") -> pd.DataFrame:
    """One state per play (after the play): STATE_COLS plus seq, clock_s, espn_wp. Labelled with the result
    when the game is final. `possessions`: builder A's GameEvents (preferred: exact, by event index), its
    possessions list (by time), or None (inferred from the play text)."""
    plays = _pbp_plays(pbp)
    if not plays or not game:
        return pd.DataFrame(columns=STATE_COLS)
    home, away = game.get("home"), game.get("away")
    team_of = _team_of(game)
    per = np.array([int(p[1] or 1) for p in plays])
    clk = np.array([float(p[2] or 0) for p in plays])
    tl = np.array([t_left(league, a, b) for a, b in zip(per, clk)])
    elapsed = np.array([_io.period_start(league, a) + _io.period_len(league, a) - b for a, b in zip(per, clk)])
    plist, events = _parsed(possessions)
    poss = _poss_by_index(plist, events, plays, home) if plist else None
    if poss is None and plist:
        poss, pper = _poss_from_events(plist, elapsed, home)
        poss = np.where((pper == per) | (pper == 0), poss, 0)
    if poss is None:
        poss = np.array(infer_possession(plays, home, away, team_of))
    poss = _loose_ball(plays, np.asarray(poss, float), home, away, team_of)
    hs = np.array([float(p[11] or 0) for p in plays])
    as_ = np.array([float(p[12] or 0) for p in plays])
    hs, as_ = np.maximum.accumulate(hs), np.maximum.accumulate(as_)
    wpmap = (pbp or {}).get("wp") or {}
    hw = None
    if game.get("status") == "post" and game.get("hs") is not None and game.get("as") is not None:
        hw = int(float(game["hs"]) > float(game["as"]))
    return pd.DataFrame({"game_id": str(game.get("id")), "seq": [p[0] for p in plays], "period": per, "clock_s": clk,
                         "margin": hs - as_, "t_left": tl, "poss": poss, "exp_margin": exp_margin(game, league), "league": league,
                         "home_win": hw, "espn_wp": [wpmap.get(str(p[0]), wpmap.get(p[0])) for p in plays]})


# ============================================================================ WPA

def _credit(parts: list[str], act_team: str | None, home: str, away: str, team_of: dict, lineup: dict | None,
            sub: bool) -> tuple[dict[str, float], dict[str, float], dict[str, str]]:
    """Shares of a play's credit per player, summing to 1 within each team that has anyone to credit:
    ({pid: share}, {team: share left unattributed (1.0)}, {pid: team})."""
    shares: dict[str, float] = defaultdict(float)
    left = {}
    team: dict[str, str] = {}
    known = [] if sub else [p for p in parts if team_of.get(p) in (home, away)]
    for T in (home, away):
        mine = [p for p in known if team_of[p] == T]
        five = [str(x) for x in ((lineup or {}).get(T) or ()) if x]
        team.update({q: T for q in mine + five})
        if mine and T == act_team:
            if len(mine) > 1:
                shares[mine[0]] += 1.0 - ASSIST_SHARE
                for q in mine[1:]:
                    shares[q] += ASSIST_SHARE / (len(mine) - 1)
            else:
                shares[mine[0]] += 1.0
        elif mine:
            if five:
                for q in mine:
                    shares[q] += DEF_SHARE / len(mine)
                for q in five:
                    shares[q] += (1.0 - DEF_SHARE) / len(five)
            else:
                for q in mine:
                    shares[q] += 1.0 / len(mine)
        elif five:
            for q in five:
                shares[q] += 1.0 / len(five)
        else:
            left[T] = 1.0
    return dict(shares), left, team


def wpa(game: dict, pbp: dict, model: dict, events: Any = None, league: str = "nba") -> dict:
    """
    Per-play WPA for one game (see the module docstring for the credit rules). `pbp` is the compact
    play-by-play; `events` optionally builder A's parse output (GameEvents) for exact possession and the
    lineups on the floor (without it only listed participants are credited). Returns
    {"plays": [{"seq","period","clock_s","team","margin","poss","wp","dwp","li","clutch","espn_wp","credit":{pid: wpa}}],
     "players": {pid: {"team","wpa","pos","neg","clutch_wpa","li_wpa","plays"}}, "teams": {tid: sum of its players},
     "unattributed": {tid: WP change booked to nobody}, "wp0", "wp_final", "check" (largest per-team identity
     residual, ~0), "excitement", "comeback", "home_win", "top": [the 5 largest |dwp| plays]}.
    """
    st = states_from_pbp(pbp, game, events, league)
    home, away = game.get("home"), game.get("away")
    team_of = _team_of(game)
    lineups = _lineups_by_seq(events)
    s0 = pd.DataFrame([{"margin": 0.0, "t_left": float(_io.regulation_s(league)), "period": 1, "poss": 0.0,
                        "exp_margin": exp_margin(game, league), "league": league}])
    wp0 = float(_wp_frame(model, s0)[0])
    if st.empty:
        return {"plays": [], "players": {}, "teams": {}, "unattributed": {home: 0.0, away: 0.0}, "wp0": wp0, "wp_final": wp0,
                "check": 0.0, "excitement": 0.0, "comeback": None, "home_win": None, "top": []}
    w = _wp_frame(model, st)
    before = pd.concat([s0, st[s0.columns]], ignore_index=True).iloc[:-1]
    li = _slope(model, before) / max(model.get("li_ref") or 1.0, 1e-9)
    clutch = ((before["t_left"].to_numpy() <= CLUTCH_S) & (before["period"].to_numpy() >= _io.REG_PERIODS)
              & (np.abs(before["margin"].to_numpy()) <= CLUTCH_MARGIN))
    plays = _pbp_plays(pbp)
    players: dict[str, dict] = {}
    unattr = {home: 0.0, away: 0.0}
    prev = wp0
    rows = []
    path = [wp0]
    for k, p in enumerate(plays):
        cur = float(w[k])
        d = cur - prev
        parts = [str(x) for x in (p[5] or []) if x is not None]
        text = str(p[13] or "")
        side = _play_side(p, home, away, team_of)
        act = home if side == 1 else away if side == -1 else None
        shares, left, tmap = _credit(parts, act, home, away, team_of, lineups.get(p[0]), _is_sub(text))
        cr_out = {}
        for pid, sh in shares.items():
            tm = tmap[pid]
            c = sh * d * (1.0 if tm == home else -1.0)
            cr_out[pid] = c
            r = players.setdefault(pid, {"team": tm, "wpa": 0.0, "pos": 0.0, "neg": 0.0, "clutch_wpa": 0.0, "li_wpa": 0.0, "plays": 0})
            r["wpa"] += c
            r["pos"] += max(c, 0.0)
            r["neg"] += min(c, 0.0)
            r["plays"] += 1
            if clutch[k]:
                r["clutch_wpa"] += c
            r["li_wpa"] += c / max(li[k], 0.1)
        for T, sh in left.items():
            unattr[T] += sh * d * (1.0 if T == home else -1.0)
        rows.append({"seq": p[0], "period": int(p[1] or 0), "clock_s": float(p[2] or 0), "team": p[4],
                     "margin": float(st["margin"].iloc[k]), "poss": float(st["poss"].iloc[k]), "wp": cur, "dwp": d,
                     "li": float(li[k]), "clutch": bool(clutch[k]), "espn_wp": st["espn_wp"].iloc[k], "credit": cr_out, "text": text})
        prev = cur
        path.append(cur)
    hw = st["home_win"].iloc[0]
    final = prev
    if hw is not None and not pd.isna(hw):
        final = float(hw)
        if abs(final - prev) > 0:
            unattr[home] += final - prev
            unattr[away] -= final - prev
            path.append(final)
    teams: dict[str, float] = {home: 0.0, away: 0.0}
    for r in players.values():
        teams[r["team"]] = teams.get(r["team"], 0.0) + r["wpa"]
    dh = final - wp0
    check = max(abs(teams[home] + unattr[home] - dh), abs(teams[away] + unattr[away] + dh))
    arr = np.array(path)
    exc = float(np.sum(np.abs(np.diff(arr))))
    comeback = None
    if hw is not None and not pd.isna(hw):
        comeback = float(arr.min()) if int(hw) == 1 else float((1 - arr).min())
    top = sorted(rows, key=lambda r: -abs(r["dwp"]))[:5]
    return {"plays": rows, "players": players, "teams": teams, "unattributed": unattr, "wp0": wp0, "wp_final": final,
            "check": check, "excitement": exc, "comeback": comeback, "home_win": None if hw is None or pd.isna(hw) else int(hw),
            "top": [{k: r[k] for k in ("seq", "period", "clock_s", "dwp", "wp", "text")} for r in top]}


def season_wpa(results: Iterable[dict]) -> dict:
    """Per-player season totals from `wpa` results: {pid: {"team","wpa","pos","neg","clutch_wpa","li_wpa","games"}}."""
    out: dict[str, dict] = {}
    for res in results:
        for pid, r in (res or {}).get("players", {}).items():
            o = out.setdefault(pid, {"team": r["team"], "wpa": 0.0, "pos": 0.0, "neg": 0.0, "clutch_wpa": 0.0, "li_wpa": 0.0, "games": 0})
            for k in ("wpa", "pos", "neg", "clutch_wpa", "li_wpa"):
                o[k] += r[k]
            o["games"] += 1
            o["team"] = r["team"]
    return out


def calibration(model: dict, states: Any, bins: int = 10) -> dict:
    """Our model (and ESPN's per-play wp where the states carry espn_wp) against outcomes: Brier, log-loss,
    and a reliability table by predicted-probability bin. Both scored on the same states."""
    df = _io.as_frame(states).copy()
    df = df.dropna(subset=["home_win"])
    if df.empty:
        return {"n": 0}
    y = df["home_win"].to_numpy(float)
    ours = np.clip(wp(model, df), 1e-6, 1 - 1e-6)
    out: dict[str, Any] = {"n": int(len(df))}

    def score(p, yy):
        return {"brier": float(np.mean((p - yy) ** 2)), "logloss": float(-np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p)))}

    def table(p, yy):
        edges = np.linspace(0, 1, bins + 1)
        b = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
        return [{"lo": float(edges[i]), "hi": float(edges[i + 1]), "n": int((b == i).sum()),
                 "p_mean": float(p[b == i].mean()) if (b == i).any() else None,
                 "y_mean": float(yy[b == i].mean()) if (b == i).any() else None} for i in range(bins)]

    out["ours"] = {**score(ours, y), "table": table(ours, y)}
    if "espn_wp" in df:
        e = pd.to_numeric(df["espn_wp"], errors="coerce").to_numpy(float)
        ok = np.isfinite(e)
        if ok.any():
            pe = np.clip(e[ok], 1e-6, 1 - 1e-6)
            out["espn"] = {**score(pe, y[ok]), "table": table(pe, y[ok])}
            out["ours_on_espn_rows"] = score(ours[ok], y[ok])
            out["mean_abs_diff"] = float(np.mean(np.abs(ours[ok] - pe)))
            out["n_espn"] = int(ok.sum())
    return out


compare_espn = calibration


# ============================================================================ season loader

def _load_pbp(league: str, season: int, gid: str) -> dict | None:
    p = _io.pbp_root() / league / str(season) / f"{gid}.json.gz"
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _events(pbp: dict, game: dict) -> Any:
    try:
        from oddsmarkets.basketball import pbp as pbp_mod   # builder A
        return pbp_mod.parse(pbp, game)
    except Exception:
        return None


def season_states(league: str, season: int, through: str | None = None, use_parser: bool = True) -> pd.DataFrame:
    store = _io.season_file(league, season, "store.json") or {}
    frames = []
    for gid, g in (store.get("games") or {}).items():
        if g.get("status") != "post" or not g.get("has_pbp") or (through and str(g.get("date") or "")[:10] > through):
            continue
        pbp = _load_pbp(league, season, gid)
        if not pbp:
            continue
        ev = _events(pbp, g) if use_parser else None
        frames.append(states_from_pbp(pbp, g, ev, league))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STATE_COLS)


def model_for(league: str, season: int, n_seasons: int = 3, use_cache: bool = True) -> dict:
    """The win-probability model fitted on the `n_seasons` seasons before `season` (out of sample for it);
    falls back to including `season` itself when no earlier play-by-play is on disk."""
    root = _io.pbp_root() / league
    seasons = [s for s in range(season - n_seasons, season) if (root / str(s)).exists()]
    if not seasons:
        # CI holds only the current season's raw files: an in-sample refit on a few weeks of games is
        # worse than the committed model fitted on earlier seasons (scripts/bb_fit.py)
        fitted = Path(__file__).with_name("fitted") / f"winprob_{league}.json"
        try:
            m = json.loads(fitted.read_text(encoding="utf-8"))
            if m.get("ok") and m.get("version") == MODEL_VERSION:
                return m
        except (OSError, ValueError):
            pass
        seasons = [season]
    key = _io.file_key(MODEL_VERSION, seasons, [len(list((root / str(s)).glob("*.json.gz"))) if (root / str(s)).exists() else 0
                                                 for s in seasons])

    def build():
        st = pd.concat([season_states(league, s) for s in seasons], ignore_index=True)
        return fit_wp(st)

    return _io.cached("winprob", f"model_{league}_{season}", key, build, use_cache)


def for_season(league: str, season: int, through: str | None = None, use_cache: bool = True) -> dict:
    """WPA for every finished game with play-by-play: {"ok","model","games": {gid: {"excitement","comeback",
    "wp0","home_win","top"}}, "players": season totals, "calibration": ours vs ESPN on this season}."""
    try:
        model = model_for(league, season, use_cache=use_cache)
        if not model.get("ok"):
            return {"ok": False, "reason": model.get("reason", "no model")}
        store = _io.season_file(league, season, "store.json") or {}
        path = _io.pbp_root() / league / str(season)
        key = _io.file_key(MODEL_VERSION, model.get("beta"), through, _io.data_root() / league / str(season) / "store.json",
                           len(list(path.glob("*.json.gz"))) if path.exists() else 0)

        def build():
            games, results, states = {}, [], []
            for gid, g in (store.get("games") or {}).items():
                if g.get("status") != "post" or not g.get("has_pbp") or (through and str(g.get("date") or "")[:10] > through):
                    continue
                pbp = _load_pbp(league, season, gid)
                if not pbp:
                    continue
                ev = _events(pbp, g)
                res = wpa(g, pbp, model, ev, league)
                results.append(res)
                games[gid] = {k: res[k] for k in ("excitement", "comeback", "wp0", "home_win", "top")}
                states.append(states_from_pbp(pbp, g, ev, league))
            cal = calibration(model, pd.concat(states, ignore_index=True)) if states else {"n": 0}
            return _io.clean({"ok": True, "league": league, "season": int(season), "model": model, "games": games,
                              "players": season_wpa(results), "calibration": cal})

        return _io.cached("winprob", f"{league}_{season}_{through or 'all'}", key, build, use_cache)
    except Exception as exc:                                          # pragma: no cover - defensive
        return {"ok": False, "reason": f"winprob failed: {exc}"}
