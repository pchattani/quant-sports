"""
SeasonContext: everything the catalogues and pages of one season read, loaded lazily and once.

* `store` (builder A's season store), `games` {game_id: GAME}, `teams` {abbr: {...}}, `players` {pid: {...}},
  `phase` ("preseason" | "regular" | "playoffs" | "offseason").
* `events()`: builder A's derived events.parquet normalised to this layer's column names (`EV_COLS`), with the
  shot's xG joined (builder B's xg.for_season when it scores, else this layer's fallback logistic fitted on the
  season's own shots and flagged xg_source = "fallback").
* `stints()`: builder A's stints.parquet normalised (game_id, period, start, end, dur, home/away skater slots,
  goalies, strength).
* `model(name)`: one builder B/C model's season output (`for_season`), isolated: a model that raises or is missing
  gives {"ok": False, "reason"} and is listed in `model_errors`.
Memory: one season of events and stints at a time; `free()` drops the frames.
"""
from __future__ import annotations

import gc
import importlib
import logging
import re
import time
import traceback
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an

logger = logging.getLogger(__name__)

# normalised event types
GOAL, SHOT, MISS, BLOCK, FAC, HIT, GIVE, TAKE, PENL = "GOAL", "SHOT", "MISS", "BLOCK", "FAC", "HIT", "GIVE", "TAKE", "PENL"
TYPE_MAP = {
    "goal": GOAL, "shot-on-goal": SHOT, "shot_on_goal": SHOT, "shot": SHOT, "sog": SHOT, "missed-shot": MISS, "missed_shot": MISS,
    "miss": MISS, "blocked-shot": BLOCK, "blocked_shot": BLOCK, "block": BLOCK, "faceoff": FAC, "fac": FAC, "hit": HIT,
    "giveaway": GIVE, "give": GIVE, "takeaway": TAKE, "take": TAKE, "penalty": PENL, "penl": PENL,
}
FENWICK = (GOAL, SHOT, MISS)
CORSI = (GOAL, SHOT, MISS, BLOCK)
SLOTS = 6

# candidate source names per normalised column (first present wins)
CANDS: dict[str, list[str]] = {
    "game_id": ["game_id", "gameId", "game"],
    # the same preference as builder B's _io.ALIASES["idx"], so the per-game event index matches B's (xG joins on it)
    "event_id": ["idx", "event_idx", "sort_order", "sortorder", "event_index", "order", "seq", "event_id", "eventid"],
    "period": ["period", "period_number", "periodNumber", "per"],
    "sec": ["sec", "game_sec", "game_seconds", "elapsed", "t", "time_elapsed", "seconds"],
    "period_sec": ["period_sec", "time_in_period", "timeinperiod", "period_seconds"],
    "type": ["type", "event_type", "typeDescKey", "type_desc_key", "event"],
    "team": ["team", "event_team", "team_abbrev", "owner_team", "shooting_team", "teamcode", "team_code", "owner", "team_abbr"],
    "x": ["x", "x_norm", "xcoord", "x_coord", "x_adj", "xn"],
    "y": ["y", "y_norm", "ycoord", "y_coord", "y_adj", "yn"],
    "zone": ["zone", "zone_code", "zoneCode"],
    "shot_type": ["shot_type", "shotType", "secondary_type"],
    # builder A's player1 is the event's actor (shooter / faceoff winner / hitter / penalised / giver / taker)
    "p1": ["player1", "p1", "shooter", "shooter_id", "shooting_player", "shootingplayerid", "scoring_player", "scorer", "player_id",
           "player"],
    "goalie": ["goalie", "goalie_id", "goalie_in_net", "goalieInNetId", "goalie_in_net_id"],
    "a1": ["assist1", "assist_1", "a1_player", "assist1_id", "primary_assist"],
    "a2": ["assist2", "assist_2", "a2_player", "assist2_id", "secondary_assist"],
    "p2": ["player2", "p2"],
    "strength": ["strength", "strength_state", "state"],
    "situation": ["situation_code", "situationcode", "sit", "situation", "strength_code"],
    "score_home": ["score_home", "home_score", "homescore", "score_h"],
    "score_away": ["score_away", "away_score", "awayscore", "score_a"],
    "home_goalie": ["home_goalie", "hg", "home_g", "goalie_home", "home_goalie_id"],
    "away_goalie": ["away_goalie", "ag", "away_g", "goalie_away", "away_goalie_id"],
    "xg": ["xg", "xG", "x_goal", "xgoal"],
    "home_team": ["home_team", "home", "home_abbrev", "hometeam", "home_team_abbrev"],
    "away_team": ["away_team", "away", "away_abbrev", "awayteam", "away_team_abbrev"],
    "rebound": ["rebound", "is_rebound"],
    "rush": ["rush", "is_rush"],
    "empty_net": ["empty_net", "is_empty_net", "en"],
    "dist": ["dist", "distance", "shot_distance"],
    "angle": ["angle", "shot_angle"],
    "pen_min": ["pen_min", "duration", "penalty_minutes", "pim"],
    "pen_type": ["pen_type", "desc_key", "penalty_type", "descKey", "penalty"],
    "speed": ["shot_speed", "speed"],
    "reason": ["reason", "secondary_reason"],
}
# role-specific player columns some event tables carry (mapped onto p1 / p2 by type)
ROLE_COLS = {
    "winner": ["winner", "faceoff_winner", "winning_player", "winningPlayerId", "fo_winner"],
    "loser": ["loser", "faceoff_loser", "losing_player", "losingPlayerId", "fo_loser"],
    "hitter": ["hitter", "hitting_player", "hittingPlayerId"],
    "hittee": ["hittee", "hittee_player", "hitteePlayerId", "hit_player"],
    "blocker": ["blocker", "blocking_player", "blockingPlayerId", "blocked_by"],
    "committed": ["pen_by", "committed_by", "committedByPlayerId", "penalty_player", "penalized", "pen_player", "committed"],
    "drawn": ["pen_drawn", "drawn_by", "drawnByPlayerId", "penalty_drawn_by", "drawn"],
    "actor": ["actor", "playerId", "player_id_event", "giveaway_player", "takeaway_player"],
}
STINT_CANDS = {
    "game_id": ["game_id", "gameId"],
    "period": ["period"],
    "start": ["start", "start_sec", "t0", "begin"],
    "end": ["end", "end_sec", "t1", "stop"],
    "dur": ["dur", "duration", "seconds", "toi"],
    "strength": ["strength", "strength_state", "state"],
    "home_goalie": ["home_goalie", "home_goalie_id", "home_g"],
    "away_goalie": ["away_goalie", "away_goalie_id", "away_g"],
    "home_team": ["home", "home_team"],
    "away_team": ["away", "away_team"],
}


def _pick(df: pd.DataFrame, names: list[str]) -> str | None:
    for n in names:
        if n in df.columns:
            return n
    low = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


def slot_cols(df: pd.DataFrame, side: str) -> list[str]:
    """The on-ice skater slot columns of one side ("home" / "away"): home_on_1..6, home_sk1.., home_1.., h1..."""
    pats = [rf"^{side}_s_?\d$", rf"^{side}_on_?\d$", rf"^{side}_sk(ater)?_?\d$", rf"^{side}_skater_?\d$", rf"^{side}_p_?\d$", rf"^{side}_\d$",
            rf"^{side}\d$", rf"^{side[0]}_?\d$", rf"^{side[0]}on_?\d$", rf"^{side}On\d$", rf"^{side}_player_?\d$"]
    for p in pats:
        cols = sorted([c for c in df.columns if re.match(p, str(c), flags=re.I)], key=lambda c: int(re.findall(r"\d+", str(c))[-1]))
        if cols:
            return cols[:SLOTS]
    return []


def _list_col(df: pd.DataFrame, side: str) -> str | None:
    for n in (f"{side}_on", f"{side}_skaters", f"{side}_players", f"{side}_ids", f"{side}_onice"):
        if n in df.columns:
            return n
    return None


def _explode_list(df: pd.DataFrame, col: str, side: str) -> pd.DataFrame:
    vals = df[col].tolist()
    arr = np.full((len(vals), SLOTS), np.nan)
    for i, v in enumerate(vals):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        if isinstance(v, str):
            v = [x for x in re.split(r"[ ,;|]+", v.strip("[]")) if x]
        try:
            seq = list(v)
        except TypeError:
            continue
        for j, x in enumerate(seq[:SLOTS]):
            f = an.fnum(x)
            if f is not None:
                arr[i, j] = f
    for j in range(SLOTS):
        df[f"{side[0]}{j + 1}"] = arr[:, j]
    return df


def _ids(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("float64")


def norm_type(v: Any) -> str:
    s = str(v or "").strip().lower()
    return TYPE_MAP.get(s, s.upper())


def parse_situation(code: Any) -> tuple[int | None, int | None, int | None, int | None]:
    """NHL situationCode "1551" -> (away goalie in net, away skaters, home skaters, home goalie in net)."""
    s = an.sid(code)
    if not s or not s.isdigit() or len(s) != 4:
        return None, None, None, None
    return int(s[0]), int(s[1]), int(s[2]), int(s[3])


def normalise_events(raw: pd.DataFrame, games: dict[str, dict] | None = None) -> pd.DataFrame:
    """Builder A's events table -> this layer's columns: game_id (str), event_id, period, sec, type (GOAL, SHOT, MISS,
    BLOCK, FAC, HIT, GIVE, TAKE, PENL, ...), team, opp, is_home, x, y, zone, shot_type, p1 (shooter / winner / hitter /
    committer / actor), p2 (blocker / loser / hittee / drawer), a1, a2, goalie, h1..h6, a_1..: ("v1".."v6" away),
    hg / vg (goalies), n_h / n_v (skaters on ice), score_home / score_away, xg (when the table has one), rebound, rush,
    empty_net, pen_min, pen_type, dist, angle."""
    df = raw
    out = pd.DataFrame(index=df.index)
    for k, names in CANDS.items():
        c = _pick(df, names)
        if c is not None:
            out[k] = df[c].to_numpy()
    if "game_id" not in out:
        raise ValueError("events table has no game_id column")
    out["game_id"] = out["game_id"].map(an.sid)
    out["type"] = out["type"].map(norm_type) if "type" in out else ""
    for k in ("period", "sec", "x", "y", "score_home", "score_away", "xg", "dist", "angle", "pen_min", "speed", "event_id"):
        if k in out:
            out[k] = pd.to_numeric(out[k], errors="coerce")
    if "sec" not in out and "period_sec" in out and "period" in out:
        def mmss(v):
            if isinstance(v, str) and ":" in v:
                try:
                    m_, s_ = v.split(":")
                    return int(m_) * 60 + int(s_)
                except ValueError:
                    return np.nan
            return an.fnum(v) if an.fnum(v) is not None else np.nan
        out["sec"] = (out["period"] - 1) * 1200.0 + out["period_sec"].map(mmss).astype(float)
    out.pop("period_sec", None) if "period_sec" in out else None
    for k in ("p1", "p2", "a1", "a2", "goalie", "home_goalie", "away_goalie"):
        if k in out:
            out[k] = _ids(out[k])
    # role columns onto p1 / p2
    roles = {r: _pick(df, names) for r, names in ROLE_COLS.items()}
    t = out["type"]
    for ty, r1, r2 in ((FAC, "winner", "loser"), (HIT, "hitter", "hittee"), (PENL, "committed", "drawn"), (BLOCK, None, "blocker"),
                       (GIVE, "actor", None), (TAKE, "actor", None)):
        m = (t == ty).to_numpy()
        if not m.any():
            continue
        for slot, role in (("p1", r1), ("p2", r2)):
            if role and roles.get(role):
                v = _ids(df[roles[role]])
                if slot not in out:
                    out[slot] = np.nan
                cur = out[slot].to_numpy(dtype="float64", copy=True)
                vv = v.to_numpy()
                fill = m & ~np.isnan(vv)
                cur[fill] = vv[fill]
                out[slot] = cur
    for k in ("p1", "p2", "a1", "a2", "goalie"):
        if k not in out:
            out[k] = np.nan
    # skater slots
    for side, pre in (("home", "h"), ("away", "v")):
        cols = slot_cols(df, side)
        if cols:
            for j, c in enumerate(cols):
                out[f"{pre}{j + 1}"] = _ids(df[c]).to_numpy()
        else:
            lc = _list_col(df, side)
            if lc is not None:
                tmp = _explode_list(df[[lc]].copy(), lc, side)
                for j in range(SLOTS):
                    out[f"{pre}{j + 1}"] = tmp[f"{side[0]}{j + 1}"].to_numpy()
        for j in range(SLOTS):
            if f"{pre}{j + 1}" not in out:
                out[f"{pre}{j + 1}"] = np.nan
    out["hg"] = out.pop("home_goalie") if "home_goalie" in out else np.nan
    out["vg"] = out.pop("away_goalie") if "away_goalie" in out else np.nan
    H = out[[f"h{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    V = out[[f"v{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    # goalies listed among the slots are not skaters
    for G, M in ((out["hg"].to_numpy(), H), (out["vg"].to_numpy(), V)):
        same = (M == G[:, None]) & ~np.isnan(G)[:, None]
        M[same] = np.nan
    for j in range(SLOTS):
        out[f"h{j + 1}"] = H[:, j]
        out[f"v{j + 1}"] = V[:, j]
    n_h = (~np.isnan(H)).sum(axis=1).astype(float)
    n_v = (~np.isnan(V)).sum(axis=1).astype(float)
    # skater counts from the situation code when the slots are empty (pre-shift-chart seasons)
    if "situation" in out:
        sit = out["situation"].map(parse_situation)
        ag = np.array([s[0] if s[0] is not None else np.nan for s in sit], dtype=float)
        ask = np.array([s[1] if s[1] is not None else np.nan for s in sit], dtype=float)
        hsk = np.array([s[2] if s[2] is not None else np.nan for s in sit], dtype=float)
        hgk = np.array([s[3] if s[3] is not None else np.nan for s in sit], dtype=float)
        miss = (n_h == 0) & ~np.isnan(hsk)
        n_h[miss] = hsk[miss]
        miss = (n_v == 0) & ~np.isnan(ask)
        n_v[miss] = ask[miss]
        out["h_net"] = hgk
        out["v_net"] = ag
    else:
        out["h_net"] = np.where(np.isnan(out["hg"].to_numpy()), np.nan, 1.0)
        out["v_net"] = np.where(np.isnan(out["vg"].to_numpy()), np.nan, 1.0)
    if "strength" in out and (n_h == 0).all():
        st = out["strength"].astype(str).str.extract(r"(\d)\s*v\s*(\d)")
        n_h = pd.to_numeric(st[0], errors="coerce").fillna(0).to_numpy(float)
        n_v = pd.to_numeric(st[1], errors="coerce").fillna(0).to_numpy(float)
    out["n_h"], out["n_v"] = n_h, n_v
    # teams: event team, home / away from the store
    g = games or {}
    if "home_team" not in out:
        out["home_team"] = out["game_id"].map(lambda x: (g.get(x) or {}).get("home"))
    if "away_team" not in out:
        out["away_team"] = out["game_id"].map(lambda x: (g.get(x) or {}).get("away"))
    if "team" not in out:
        out["team"] = None
    out["team"] = out["team"].astype("object")
    out["is_home"] = (out["team"] == out["home_team"]).astype(float)
    out.loc[out["team"].isna(), "is_home"] = np.nan
    out["opp"] = np.where(out["is_home"] == 1, out["away_team"], np.where(out["is_home"] == 0, out["home_team"], None))
    for k in ("rebound", "rush", "empty_net"):
        if k in out:
            out[k] = pd.to_numeric(out[k].map(lambda v: 1.0 if v is True else (0.0 if v is False else v)), errors="coerce")
    if "sec" not in out:
        out["sec"] = np.nan
    if "period" not in out:
        out["period"] = np.nan
    if "event_id" not in out:
        out["event_id"] = np.arange(len(out), dtype=float)
    out = out.sort_values(["game_id", "period", "sec", "event_id"], kind="mergesort").reset_index(drop=True)
    out["idx"] = out.groupby("game_id").cumcount().astype(float)      # builder B's per-game event index
    _add_geometry(out)
    _add_states(out)
    return out


def _add_geometry(ev: pd.DataFrame) -> None:
    """Distance and angle to the attacked net (89, 0) after the attacking-right normalisation; flips shots recorded
    at negative x on non-normalised tables."""
    if "x" not in ev or "y" not in ev:
        ev["x"], ev["y"] = np.nan, np.nan
    x = ev["x"].to_numpy(float)
    y = ev["y"].to_numpy(float)
    shot = ev["type"].isin(CORSI).to_numpy()
    # normalised tables have shots at +x (offensive zone); a raw table has half at -x: flip those
    if shot.any() and np.nanmean(x[shot] < 0) > 0.3:
        flip = x < 0
        x = np.where(flip, -x, x)
        y = np.where(flip, -y, y)
        ev["x"], ev["y"] = x, y
    dx = 89.0 - x
    if "dist" not in ev or ev["dist"].isna().all():
        ev["dist"] = np.sqrt(dx ** 2 + y ** 2)
    if "angle" not in ev or ev["angle"].isna().all():
        ev["angle"] = np.degrees(np.arctan2(np.abs(y), np.abs(dx)))


def _add_states(ev: pd.DataFrame) -> None:
    """state: the event team's strength ("5v5", "5v4", "4v5", "4v4", "3v3", "EN" when a net is empty, "other"),
    st: "EV" (equal strength), "PP", "SH", "EN"; score_diff from the event team's side."""
    ih = ev["is_home"].to_numpy(float)
    nh, nv = ev["n_h"].to_numpy(float), ev["n_v"].to_numpy(float)
    own = np.where(ih == 1, nh, nv)
    opp = np.where(ih == 1, nv, nh)
    hn, vn = ev["h_net"].to_numpy(float), ev["v_net"].to_numpy(float)
    own_net = np.where(ih == 1, hn, vn)
    opp_net = np.where(ih == 1, vn, hn)
    en = (opp_net == 0) | (own_net == 0)
    if "empty_net" in ev:
        en = en | (ev["empty_net"].to_numpy(float) == 1)
    state = np.array([f"{int(a)}v{int(b)}" if a > 0 and b > 0 else "other" for a, b in zip(np.nan_to_num(own), np.nan_to_num(opp))],
                     dtype=object)
    state[en] = "EN"
    st = np.where(en, "EN", np.where(own > opp, "PP", np.where(own < opp, "SH", "EV")))
    st = np.where((own == 0) | (opp == 0), "other", st)
    ev["state"] = state
    ev["st"] = st
    if "score_home" in ev and "score_away" in ev:
        sh, sa = ev["score_home"].to_numpy(float), ev["score_away"].to_numpy(float)
        ev["score_diff"] = np.where(ih == 1, sh - sa, sa - sh)
    else:
        ev["score_diff"] = np.nan


def normalise_stints(raw: pd.DataFrame, games: dict[str, dict] | None = None) -> pd.DataFrame:
    """Builder A's stints -> game_id, period, start, end, dur, h1..h6, v1..v6, hg, vg, n_h, n_v, home_team, away_team."""
    df = raw
    out = pd.DataFrame(index=df.index)
    for k, names in STINT_CANDS.items():
        c = _pick(df, names)
        if c is not None:
            out[k] = df[c].to_numpy()
    out["game_id"] = out["game_id"].map(an.sid)
    for k in ("period", "start", "end", "dur"):
        if k in out:
            out[k] = pd.to_numeric(out[k], errors="coerce")
    if "dur" not in out:
        out["dur"] = out["end"] - out["start"]
    for side, pre in (("home", "h"), ("away", "v")):
        cols = slot_cols(df, side)
        if cols:
            for j, c in enumerate(cols):
                out[f"{pre}{j + 1}"] = _ids(df[c]).to_numpy()
        else:
            lc = _list_col(df, side)
            if lc is not None:
                tmp = _explode_list(df[[lc]].copy(), lc, side)
                for j in range(SLOTS):
                    out[f"{pre}{j + 1}"] = tmp[f"{side[0]}{j + 1}"].to_numpy()
        for j in range(SLOTS):
            if f"{pre}{j + 1}" not in out:
                out[f"{pre}{j + 1}"] = np.nan
    out["hg"] = _ids(out.pop("home_goalie")) if "home_goalie" in out else np.nan
    out["vg"] = _ids(out.pop("away_goalie")) if "away_goalie" in out else np.nan
    H = out[[f"h{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    V = out[[f"v{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    for G, M in ((out["hg"].to_numpy(float), H), (out["vg"].to_numpy(float), V)):
        same = (M == G[:, None]) & ~np.isnan(G)[:, None]
        M[same] = np.nan
    for j in range(SLOTS):
        out[f"h{j + 1}"] = H[:, j]
        out[f"v{j + 1}"] = V[:, j]
    out["n_h"] = (~np.isnan(H)).sum(axis=1)
    out["n_v"] = (~np.isnan(V)).sum(axis=1)
    g = games or {}
    if "home_team" not in out:
        out["home_team"] = out["game_id"].map(lambda x: (g.get(x) or {}).get("home"))
    if "away_team" not in out:
        out["away_team"] = out["game_id"].map(lambda x: (g.get(x) or {}).get("away"))
    out = out[out["dur"].fillna(0) > 0]
    return out.reset_index(drop=True)


# builder A's event columns this layer never reads (left on disk to bound memory)
EV_SKIP = ("x_raw", "y_raw", "zone_raw", "t", "ptype", "pen_desc", "onice_ok", "onice_strict", "stint", "gtype", "season", "sort",
           "home_sk", "away_sk", "home_gin", "away_gin", "n_home_sk", "n_away_sk", "penalty_shot", "state", "strength")


def read_parquet(path, columns: list[str] | None = None, exclude: tuple[str, ...] | None = None) -> pd.DataFrame | None:
    try:
        import pyarrow.parquet as pq
        names = pq.read_schema(path).names
        if exclude and columns is None:
            columns = [c for c in names if c not in exclude]
        cols = None if columns is None else [c for c in dict.fromkeys(columns) if c in names]
        return pd.read_parquet(path, columns=cols)
    except Exception as exc:                                     # noqa: BLE001
        logger.info("read %s failed: %s", path, exc)
        return None


def game_type(gid: Any) -> str:
    """"PRE" / "REG" / "PO" / "AS" from the NHL gameId (season + 01/02/03/04 + number)."""
    s = an.sid(gid) or ""
    t = s[4:6] if len(s) >= 6 else ""
    return {"01": "PRE", "02": "REG", "03": "PO", "04": "AS"}.get(t, "REG")


# ---------------------------------------------------------------------------------------------- the context

class SeasonContext:
    def __init__(self, season: int, full: bool = True, today: date | None = None, current: bool = False, sims: int = 20000,
                 fetch_markets: bool = False, use_models: bool = True):
        self.season, self.full = int(season), full
        self.today = today or datetime.now(timezone.utc).date()
        self.current = current
        self.sims = sims
        self.fetch_markets = fetch_markets
        self.use_models = use_models
        self.store = an.load_store(season)
        self.games: dict[str, dict] = {}
        for k, g in (self.store.get("games") or {}).items() if isinstance(self.store.get("games"), dict) else \
                ((str(g.get("game_id")), g) for g in (self.store.get("games") or [])):
            gid = an.sid(k) or an.sid((g or {}).get("game_id"))
            if gid and isinstance(g, dict):
                g = dict(g)
                g["game_id"] = gid
                g.setdefault("gtype", game_type(gid))
                g["status"] = norm_status(g.get("status"))
                self.games[gid] = g
        self.teams: dict[str, dict] = self._teams()
        self.players: dict[str, dict] = {an.sid(k): v for k, v in (self.store.get("players") or {}).items() if isinstance(v, dict)} \
            if isinstance(self.store.get("players"), dict) else {an.sid(p.get("id")): p for p in (self.store.get("players") or [])
                                                               if isinstance(p, dict)}
        self.model_errors: dict[str, str] = {}
        self.timings: dict[str, float] = {}
        self._models: dict[Any, Any] = {}
        self._ev: pd.DataFrame | None = None
        self._st: pd.DataFrame | None = None
        self._markets: dict | None = None
        self._sim: dict | None = None
        self.xg_source: str | None = None
        self.phase = self._phase()

    # ------------------------------------------------------------------ basics
    def _teams(self) -> dict[str, dict]:
        raw = self.store.get("teams") or {}
        if isinstance(raw, list):
            raw = {str(t.get("abbr") or t.get("team") or t.get("id")): t for t in raw if isinstance(t, dict)}
        out: dict[str, dict] = {}
        canon_info = _canon_teams(self.season)
        in_games = {t for g in self.games.values() if g.get("gtype") in ("REG", "PO") for t in (g.get("home"), g.get("away")) if t}
        for t in sorted(set(raw) | in_games or set(canon_info)):
            r = dict(canon_info.get(t) or {})
            r.update({k: v for k, v in (raw.get(t) or {}).items() if v is not None})
            r.setdefault("abbr", t)
            r.setdefault("name", t)
            out[t] = r
        if in_games:
            out = {t: v for t, v in out.items() if t in in_games}
        return out

    def _phase(self) -> str:
        gs = [g for g in self.games.values() if g.get("gtype") in ("REG", "PO")]
        if not gs:
            return "preseason" if self.games else "offseason"
        reg = [g for g in gs if g["gtype"] == "REG"]
        po = [g for g in gs if g["gtype"] == "PO"]
        if not any(g.get("status") in ("final", "live") for g in reg):
            return "preseason"
        if reg and all(g.get("status") == "final" for g in reg):
            if po and any(g.get("status") != "final" for g in po):
                return "playoffs"
            if po and all(g.get("status") == "final" for g in po) and _cup_decided(po):
                return "offseason"
            return "playoffs" if (self.current or po) else "offseason"
        return "regular"

    def name(self, abbr: str) -> str:
        return (self.teams.get(abbr) or {}).get("name") or abbr

    def player_name(self, pid: Any) -> str | None:
        p = self.players.get(an.sid(pid)) or {}
        nm = p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x)
        if nm:
            return nm
        k = an.sid(pid)
        if not k:
            return None
        return self.extra_names().get(k) or None

    def extra_names(self) -> dict[str, str]:
        """Names of players the store's roster pass missed (call-ups after it ran, which otherwise publish as their id):
        full names from the stats reports of this season, then of the seasons either side. Read once, on the first miss
        (a few small files; the play-by-play roster spots would cost a minute a season)."""
        xn = getattr(self, "_xnames", None)
        if xn is not None:
            return xn
        import gzip
        import json as _json
        out: dict[str, str] = {}
        root = an.raw_root()
        for season in (self.season, self.season - 10001, self.season + 10001):
            for rep, col in (("skater_summary_2", "skaterFullName"), ("skater_summary_3", "skaterFullName"),
                             ("goalie_summary_2", "goalieFullName"), ("goalie_summary_3", "goalieFullName")):
                try:
                    with gzip.open(root / "stats" / str(season) / f"{rep}.json.gz", "rt", encoding="utf-8") as fh:
                        rows = _json.load(fh)
                except (OSError, ValueError, EOFError):
                    continue
                for r in rows or []:
                    k, v = an.sid(r.get("playerId")), r.get(col)
                    if k and v:
                        out.setdefault(k, str(v))
        self._xnames = out
        return out

    def team_games(self) -> int:
        n: dict[str, int] = {}
        for g in self.games.values():
            if g.get("gtype") == "REG" and g.get("status") == "final":
                for t in (g.get("home"), g.get("away")):
                    n[t] = n.get(t, 0) + 1
        return max(n.values()) if n else 0

    def season_games(self) -> int:
        y = an.start_year(self.season)
        try:
            from oddsmarkets.nhl import canon
            f = getattr(canon, "season_games", None) or getattr(canon, "games_per_team", None)
            if f is not None:
                return int(f(self.season))
        except Exception:                                        # noqa: BLE001
            pass
        if y >= 2026:
            return 84
        return {2012: 48, 2020: 56, 2019: 82}.get(y, 82)

    # ------------------------------------------------------------------ tables
    def has_events(self) -> bool:
        return an.events_path(self.season).exists()

    def has_stints(self) -> bool:
        return an.stints_path(self.season).exists()

    def events(self) -> pd.DataFrame:
        """The season's events (normalised); an empty frame when there is no derived table."""
        if self._ev is None:
            t0 = time.perf_counter()
            raw = read_parquet(an.events_path(self.season), exclude=EV_SKIP) if self.has_events() else None
            if raw is None or not len(raw):
                self._ev = pd.DataFrame(columns=["game_id", "type", "team", "period", "sec", "xg"])
            else:
                ev = normalise_events(raw, self.games)
                del raw
                self._ev = self._join_xg(ev)
            self.timings["load events"] = time.perf_counter() - t0
        return self._ev

    def stints(self) -> pd.DataFrame:
        if self._st is None:
            t0 = time.perf_counter()
            raw = read_parquet(an.stints_path(self.season)) if self.has_stints() else None
            if raw is None or not len(raw):
                self._st = pd.DataFrame(columns=["game_id", "dur"])
            else:
                self._st = normalise_stints(raw, self.games)
            self.timings["load stints"] = time.perf_counter() - t0
        return self._st

    def _join_xg(self, ev: pd.DataFrame) -> pd.DataFrame:
        from oddsmarkets.nhl.analytics import adapters
        try:
            src = adapters.shot_xg(self, ev)
        except Exception as exc:                                 # noqa: BLE001
            self.model_errors["xg join"] = f"{type(exc).__name__}: {exc}"
            src = None
        if src is not None:
            ev["xg"] = src
            self.xg_source = "model"
        elif "xg" in ev and ev["xg"].notna().sum() > 0.5 * ev["type"].isin(FENWICK).sum():
            self.xg_source = "table"
        else:
            from oddsmarkets.nhl.analytics import xgfallback
            try:
                ev["xg"] = xgfallback.score(ev)
                self.xg_source = "fallback"
                self.model_errors.setdefault("xg", "the expected-goals model does not score this season: a fallback logistic (distance, angle, "
                                                   "shot type, rebound, rush, strength) fitted on the season's shots")
            except Exception as exc:                             # noqa: BLE001
                self.model_errors["xg fallback"] = f"{type(exc).__name__}: {exc}"
                ev["xg"] = np.nan
        fen = ev["type"].isin(FENWICK)
        ev.loc[~fen, "xg"] = np.nan
        return ev

    def free(self) -> None:
        self._ev = None
        self._st = None
        self._models.clear()
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
                mod = importlib.import_module(f"oddsmarkets.nhl.models.{name}")
                fn = getattr(mod, "for_season")
                res = fn(self.season, *args, **kw)
            except ModuleNotFoundError as exc:
                res = {"ok": False, "reason": f"model module not available ({exc.name})"}
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
            from oddsmarkets.nhl.analytics import adapters
            t0 = time.perf_counter()
            try:
                self._sim = adapters.season_sim(self)
            except Exception as exc:                             # noqa: BLE001
                self._sim = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            if not self._sim.get("ok", True):
                self.model_errors["season_sim"] = str(self._sim.get("reason"))
            self.timings["season sim"] = time.perf_counter() - t0
        return self._sim

    def markets(self) -> dict:
        if self._markets is None:
            self._markets = {}
            if self.fetch_markets:
                from oddsmarkets.nhl.analytics import adapters
                t0 = time.perf_counter()
                try:
                    self._markets = adapters.markets(self) or {}
                except Exception as exc:                         # noqa: BLE001
                    logger.warning("markets failed: %s", exc)
                    self.model_errors["markets"] = str(exc)
                self.timings["markets"] = time.perf_counter() - t0
        return self._markets


def norm_status(s: Any) -> str:
    v = str(s or "").strip().lower()
    if v in ("final", "off", "final/ot", "final/so", "official", "post"):
        return "final"
    if v in ("live", "crit", "in", "in_progress", "inprogress"):
        return "live"
    if v in ("pre", "fut", "scheduled", "", "none", "preview"):
        return "scheduled" if v != "pre" else "pre"
    if v in ("ppd", "postponed", "cancelled", "canceled"):
        return "postponed"
    return v


def _cup_decided(po: list[dict]) -> bool:
    """True when some playoff series has reached four wins in the last round."""
    rounds: dict[str, dict] = {}
    for g in po:
        s = an.sid(g.get("game_id")) or ""
        rnd = s[6:8] if len(s) >= 10 else ""
        if g.get("status") != "final" or g.get("hs") is None:
            continue
        w = g["home"] if (g.get("hs") or 0) > (g.get("as") or 0) else g["away"]
        rounds.setdefault(rnd, {})
        rounds[rnd][w] = rounds[rnd].get(w, 0) + 1
    if not rounds:
        return False
    last = max(rounds)
    return last >= "04" and max(rounds[last].values()) >= 4


def _canon_teams(season: int) -> dict[str, dict]:
    """{abbr: {"name","division","conference","colour","alt"}} from builder A's canon when it answers."""
    try:
        from oddsmarkets.nhl import canon
    except Exception:                                            # noqa: BLE001
        return {}
    for fn in ("teams_for_season", "season_teams", "teams"):
        f = getattr(canon, fn, None)
        if f is None:
            continue
        try:
            r = f(season) if callable(f) else f
        except TypeError:
            continue
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(r, dict) and r:
            out = {}
            for k, v in r.items():
                if isinstance(v, dict):
                    out[str(k)] = {"name": v.get("name") or v.get("full_name"), "division": v.get("division"),
                                   "conference": v.get("conference"), "colour": v.get("colour") or v.get("color"),
                                   "alt": v.get("alt") or v.get("colour2") or v.get("secondary")}
                elif isinstance(v, (list, tuple)) and v:
                    out[str(k)] = {"name": v[0]}
            return out
        if isinstance(r, list) and r and isinstance(r[0], dict):
            return {str(v.get("abbr")): {"name": v.get("name"), "division": v.get("division"), "conference": v.get("conference"),
                                         "colour": v.get("colour") or v.get("color"), "alt": v.get("alt")} for v in r if v.get("abbr")}
    return {}


def frame_of(obj: Any) -> pd.DataFrame | None:
    """A model output as a DataFrame: a DataFrame, {"cols","rows"}, a list of dicts, or {key: {...}} records."""
    if obj is None:
        return None
    if isinstance(obj, pd.DataFrame):
        return obj
    if isinstance(obj, dict) and "cols" in obj and "rows" in obj:
        return pd.DataFrame(obj.get("rows") or [], columns=obj["cols"])
    if isinstance(obj, dict) and obj and all(isinstance(v, list) for v in obj.values()):
        lens = {len(v) for v in obj.values()}
        if len(lens) == 1:
            return pd.DataFrame(obj)
    if isinstance(obj, list) and (not obj or isinstance(obj[0], dict)):
        return pd.DataFrame(obj)
    if isinstance(obj, dict) and obj and all(isinstance(v, dict) for v in obj.values()):
        df = pd.DataFrame.from_dict(obj, orient="index")
        df.index.name = "key"
        return df.reset_index()
    return None
