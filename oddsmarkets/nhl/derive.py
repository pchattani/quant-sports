"""
Derived per-season tables for The Quant Rink (CONTRACT.md section 1): events.parquet and stints.parquet, built from
the raw api-web play-by-play and the stats REST shift charts, plus an on-ice check per game.

Events (one row per play-by-play event, shootout attempts included but never given on-ice players):
    game_id, season, gtype, event_id, sort, period, ptype (REG / OT / SO), t (seconds into the period), sec (elapsed
    game seconds; a regular-season shootout sits at 3900), type (typeDescKey), team (the event's team: the shooting
    team for every shot type, blocked shots included; the winner of a faceoff; the hitter; the penalised club),
    is_home, x_raw / y_raw (as published), x / y (normalised: the event team attacks +x), zone (O / N / D for the event
    team, from x: blue lines at +-25 ft), zone_raw, shot_type, shooter, goalie (in net), assist1, assist2, player1 /
    player2 (other actors: faceoff winner / loser, hitter / hittee, blocker, penalised / drawn by, giver / taker),
    reason, pen_type, pen_desc, pen_min, sit (situationCode), home_sk / away_sk / home_gin / away_gin (decoded),
    strength (event team v opponent skaters, "5v4"), state (EV / PP / SH / EN / PS for the event team),
    score_home / score_away (before the event), penalty_shot, home_s1..home_s6, home_g, away_s1..away_s6, away_g (on ice
    from shifts), n_home_sk / n_away_sk (skaters counted from shifts), onice_ok (counts and goalies agree with the
    situationCode; NA where not checked; for penalties, stoppages and delayed penalties the players on ice just after
    the call are accepted too, because the published situationCode at that second often already shows the
    post-call state), onice_strict (the same check with the event rule only), stint (index of the stint the event belongs to).

Direction check: the normalised zone of every unblocked shot is compared with the NHL's zoneCode (zone_checked /
zone_agree in the check); MoneyPuck's xCordAdjusted is not a check (it folds every shot to +x).

Direction: per period, the home team's attacking direction is the majority sign of x over unblocked shots taken
more than 25 ft from centre (home shots +, away shots -); a period without such shots falls back to
homeTeamDefendingSide (published from about 2019-20; "right" means home defends +x, so attacks -x), then to the
opposite of the previous period. Disagreements with homeTeamDefendingSide are counted in the check.

On ice at an event at second t of a period: a player whose shift in that period satisfies start < t <= end (the
players leaving at a stoppage were on for the event, those arriving were not), except faceoffs and period starts,
which take start <= t < end (the new players take the draw). Goalies are the players whose position is G.

Stints: the period is cut at every shift start / end; consecutive pieces with the same skaters and goalies on both
sides are merged. Each stint carries period, start / end (game seconds), duration, the on-ice slots, counts, strength
(home view), score at the start, the zone of a faceoff at its first second (home view; "F" when it starts on the
fly), and for / against counts: shots on goal, unblocked attempts (fenwick), all attempts (corsi), goals, penalties;
xg_home / xg_away are left empty for builder B. Events attach to a stint by the same rule as on-ice players.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

import numpy as np
import pandas as pd

from . import canon
from . import store as st
from .sources import stats as stats_src

logger = logging.getLogger(__name__)

SHOT_TYPES = ("shot-on-goal", "missed-shot", "blocked-shot", "goal")
UNBLOCKED = ("shot-on-goal", "missed-shot", "goal")
ON_GOAL = ("shot-on-goal", "goal")
START_RULE = ("faceoff", "period-start")
AFTER_OK = ("penalty", "stoppage", "delayed-penalty")   # situationCode may already show the state after the call
NO_CHECK = ("shootout-complete", "game-end", "game-official")
SLOTS = 6
HOME_COLS = [f"home_s{i}" for i in range(1, SLOTS + 1)]
AWAY_COLS = [f"away_s{i}" for i in range(1, SLOTS + 1)]


def _mmss(s: Any) -> int | None:
    try:
        m, sec = str(s).split(":")
        return int(m) * 60 + int(sec)
    except (ValueError, AttributeError):
        return None


def game_seconds(period: int, t: int, ptype: str, gtype: int) -> int:
    if ptype == "SO":
        return 3900 if gtype == 2 else (period - 1) * 1200
    return (int(period) - 1) * 1200 + int(t)


# ── play-by-play -> events ──────────────────────────────────────────────────

def _positions(raw: dict) -> tuple[dict[int, str], dict[int, int]]:
    pos, team = {}, {}
    for p in raw.get("rosterSpots") or []:
        pos[int(p["playerId"])] = p.get("positionCode")
        team[int(p["playerId"])] = p.get("teamId")
    return pos, team


def _actors(typ: str, d: dict) -> tuple:
    """(shooter, goalie, assist1, assist2, player1, player2) for an event's details."""
    g = d.get("goalieInNetId")
    if typ == "goal":
        return d.get("scoringPlayerId"), g, d.get("assist1PlayerId"), d.get("assist2PlayerId"), d.get("scoringPlayerId"), None
    if typ in ("shot-on-goal", "missed-shot"):
        return d.get("shootingPlayerId"), g, None, None, d.get("shootingPlayerId"), None
    if typ == "blocked-shot":
        return d.get("shootingPlayerId"), None, None, None, d.get("shootingPlayerId"), d.get("blockingPlayerId")
    if typ == "faceoff":
        return None, None, None, None, d.get("winningPlayerId"), d.get("losingPlayerId")
    if typ == "hit":
        return None, None, None, None, d.get("hittingPlayerId"), d.get("hitteePlayerId")
    if typ == "penalty":
        return None, None, None, None, d.get("committedByPlayerId") or d.get("servedByPlayerId"), d.get("drawnByPlayerId")
    if typ in ("giveaway", "takeaway"):
        return None, None, None, None, d.get("playerId"), None
    return None, None, None, None, d.get("playerId"), None


def infer_directions(rows: list[dict], home_id: int) -> tuple[dict[int, int], int, int]:
    """period -> +1 when the home team attacks +x (else -1); also (periods checked against
    homeTeamDefendingSide, disagreements)."""
    votes: dict[int, float] = {}
    side: dict[int, str] = {}
    periods = sorted({r["period"] for r in rows if r["ptype"] != "SO"})
    for r in rows:
        if r.get("hside") and r["period"] not in side:
            side[r["period"]] = r["hside"]
        if r["type"] not in UNBLOCKED or r["ptype"] == "SO" or r["x_raw"] is None or r["team_id"] is None:
            continue
        x = r["x_raw"]
        if abs(x) <= 25:
            continue
        s = 1.0 if x > 0 else -1.0
        votes[r["period"]] = votes.get(r["period"], 0.0) + (s if r["team_id"] == home_id else -s)
    out: dict[int, int] = {}
    checked = disagree = 0
    prev = None
    for p in periods:
        v = votes.get(p, 0.0)
        from_side = None
        if side.get(p) in ("left", "right"):
            from_side = -1 if side[p] == "right" else 1
        if v:
            out[p] = 1 if v > 0 else -1
            if from_side is not None:
                checked += 1
                disagree += int(from_side != out[p])
        elif from_side is not None:
            out[p] = from_side
        elif prev is not None:
            out[p] = -prev
        else:
            out[p] = 1
        prev = out[p]
    return out, checked, disagree


def parse_events(raw: dict, season: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Events of one game (no on-ice columns yet) and facts for the check (home / away ids, side checks)."""
    gid = int(raw["id"])
    season = int(raw.get("season") or canon.season_of_game(gid))
    gtype = int(raw.get("gameType") or canon.game_type(gid))
    home_id, away_id = raw["homeTeam"]["id"], raw["awayTeam"]["id"]
    home, away = raw["homeTeam"].get("abbrev"), raw["awayTeam"].get("abbrev")
    pos, pteam = _positions(raw)
    rows = []
    for p in raw.get("plays") or []:
        pdsc = p.get("periodDescriptor") or {}
        d = p.get("details") or {}
        typ = p.get("typeDescKey")
        period = int(pdsc.get("number") or 0)
        ptype = (pdsc.get("periodType") or "REG").upper()
        t = _mmss(p.get("timeInPeriod")) or 0
        shooter, goalie, a1, a2, p1, p2 = _actors(typ, d)
        owner = d.get("eventOwnerTeamId")
        team_id = owner
        if typ in SHOT_TYPES and shooter and pteam.get(int(shooter)):
            team_id = pteam[int(shooter)]          # the shooting team, whatever the owner convention
        elif typ == "blocked-shot" and p2 and pteam.get(int(p2)):
            team_id = away_id if pteam[int(p2)] == home_id else home_id
        rows.append({"event_id": p.get("eventId"), "sort": p.get("sortOrder"), "period": period, "ptype": ptype,
                     "t": t, "type": typ, "team_id": team_id, "x_raw": d.get("xCoord"), "y_raw": d.get("yCoord"),
                     "zone_raw": d.get("zoneCode"), "shot_type": d.get("shotType"), "shooter": shooter,
                     "goalie": goalie, "assist1": a1, "assist2": a2, "player1": p1, "player2": p2,
                     "reason": d.get("reason") or d.get("secondaryReason"), "pen_type": d.get("typeCode"),
                     "pen_desc": d.get("descKey"), "pen_min": d.get("duration"), "sit": p.get("situationCode"),
                     "hside": p.get("homeTeamDefendingSide")})
    rows.sort(key=lambda r: (r["sort"] if r["sort"] is not None else 10 ** 6, r["event_id"] or 0))
    dirs, checked, disagree = infer_directions(rows, home_id)
    sh = sa = 0
    for r in rows:
        r["score_home"], r["score_away"] = sh, sa
        if r["type"] == "goal" and r["ptype"] != "SO":
            if r["team_id"] == home_id:
                sh += 1
            elif r["team_id"] == away_id:
                sa += 1
        is_home = None if r["team_id"] is None else (r["team_id"] == home_id)
        r["is_home"] = is_home
        r["team"] = home if is_home else away if is_home is False else None
        dh = dirs.get(r["period"], 1)
        if r["x_raw"] is not None and is_home is not None:
            sgn = dh if is_home else -dh
            r["x"], r["y"] = r["x_raw"] * sgn, (r["y_raw"] * sgn if r["y_raw"] is not None else None)
            r["zone"] = "O" if r["x"] > 25 else "D" if r["x"] < -25 else "N"
        else:
            r["x"] = r["y"] = r["zone"] = None
        r["home_dir"] = dh
        dec = canon.decode_situation(r["sit"])
        if dec:
            r["home_sk"], r["away_sk"] = dec["home_skaters"], dec["away_skaters"]
            r["home_gin"], r["away_gin"] = dec["home_goalie"], dec["away_goalie"]
            r["penalty_shot"] = r["ptype"] != "SO" and min(dec["home_skaters"], dec["away_skaters"]) <= 1
            if is_home is not None:
                ts, os_ = (r["home_sk"], r["away_sk"]) if is_home else (r["away_sk"], r["home_sk"])
                tg, og = (r["home_gin"], r["away_gin"]) if is_home else (r["away_gin"], r["home_gin"])
                r["strength"] = canon.strength_label(ts, os_)
                r["state"] = "PS" if r["ptype"] == "SO" else canon.strength_state(ts, os_, tg, og)
            else:
                r["strength"] = r["state"] = None
        else:
            r["home_sk"] = r["away_sk"] = r["home_gin"] = r["away_gin"] = None
            r["penalty_shot"] = False
            r["strength"] = r["state"] = None
        r["sec"] = game_seconds(r["period"], r["t"], r["ptype"], gtype)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, {"game_id": gid}
    df.insert(0, "game_id", gid)
    df.insert(1, "season", season)
    df.insert(2, "gtype", gtype)
    facts = {"game_id": gid, "season": season, "gtype": gtype, "home_id": home_id, "away_id": away_id, "home": home,
             "away": away, "positions": pos, "side_checked": checked, "side_disagree": disagree, "dirs": dirs}
    return df, facts


# ── shifts -> on ice ────────────────────────────────────────────────────────

def _shift_frame(shifts_raw: dict | None, facts: dict) -> pd.DataFrame | None:
    rows = stats_src.compact_shifts(shifts_raw)
    if not rows:
        return None
    sf = pd.DataFrame(rows)
    sf = sf[sf["end"] > sf["start"]]
    sf["side"] = np.where(sf["team_id"] == facts["home_id"], "home",
                          np.where(sf["team_id"] == facts["away_id"], "away", None))
    sf = sf[sf["side"].notna()]
    if sf.empty or sf["side"].nunique() < 2:
        return None
    pos = facts.get("positions") or {}
    sf["goalie"] = sf["pid"].map(lambda p: pos.get(int(p)) == "G")
    return sf.drop_duplicates(["pid", "period", "start", "end"]).reset_index(drop=True)


def _on_ice_at(sf_side: pd.DataFrame, period: np.ndarray, t: np.ndarray, start_rule: np.ndarray):
    """For each event: (sorted skater ids, goalie ids) of one side."""
    sp, ss, se = sf_side["period"].to_numpy(), sf_side["start"].to_numpy(), sf_side["end"].to_numpy()
    pid, gl = sf_side["pid"].to_numpy(), sf_side["goalie"].to_numpy(dtype=bool)
    same = period[:, None] == sp[None, :]
    a = (ss[None, :] <= t[:, None]) & (t[:, None] < se[None, :])
    b = (ss[None, :] < t[:, None]) & (t[:, None] <= se[None, :])
    on = same & np.where(start_rule[:, None], a, b)
    sk, gs = [], []
    for i in range(len(t)):
        m = on[i]
        sk.append(sorted(set(pid[m & ~gl].tolist())))
        gs.append(sorted(set(pid[m & gl].tolist())))
    return sk, gs


def attach_on_ice(ev: pd.DataFrame, sf: pd.DataFrame | None) -> pd.DataFrame:
    n = len(ev)
    for c in HOME_COLS + ["home_g"] + AWAY_COLS + ["away_g", "n_home_sk", "n_away_sk"]:
        ev[c] = pd.array([pd.NA] * n, dtype="Int64")
    ev["onice_ok"] = pd.array([pd.NA] * n, dtype="boolean")
    ev["onice_strict"] = pd.array([pd.NA] * n, dtype="boolean")
    if sf is None or n == 0:
        return ev
    use = (ev["ptype"] != "SO").to_numpy()
    idx = np.flatnonzero(use)
    if not len(idx):
        return ev
    period = ev["period"].to_numpy()[idx].astype(int)
    t = ev["t"].to_numpy()[idx].astype(int)
    rule = ev["type"].isin(START_RULE).to_numpy()[idx]
    after = ev["type"].isin(AFTER_OK).to_numpy()[idx]
    alt_n: dict[str, np.ndarray] = {}
    for side, cols, gcol, ncol in (("home", HOME_COLS, "home_g", "n_home_sk"), ("away", AWAY_COLS, "away_g", "n_away_sk")):
        sfs = sf[sf["side"] == side]
        sk, gs = _on_ice_at(sfs, period, t, rule)
        sk2, gs2 = _on_ice_at(sfs, period, t, after | rule)
        alt_n[side] = np.full(n, -1, dtype=np.int64)
        alt_n[side][idx] = [len(x) for x in sk2]
        alt_n[side + "_g"] = np.zeros(n, dtype=np.int64)
        alt_n[side + "_g"][idx] = [len(x) for x in gs2]
        mat = np.full((len(idx), SLOTS), -1, dtype=np.int64)
        for i, s_ in enumerate(sk):
            s_ = s_[:SLOTS]
            mat[i, :len(s_)] = s_
        for j, c in enumerate(cols):
            col = pd.array(np.where(mat[:, j] >= 0, mat[:, j], 0), dtype="Int64")
            col[mat[:, j] < 0] = pd.NA
            full = ev[c].array.copy()
            full[idx] = col
            ev[c] = full
        g = pd.array([x[0] if x else 0 for x in gs], dtype="Int64")
        g[np.array([not x for x in gs], dtype=bool)] = pd.NA
        full = ev[gcol].array.copy()
        full[idx] = g
        ev[gcol] = full
        cnt = ev[ncol].array.copy()
        cnt[idx] = pd.array([len(x) for x in sk], dtype="Int64")
        ev[ncol] = cnt
        ev[f"_{side}_gn"] = 0
        ev.loc[ev.index[idx], f"_{side}_gn"] = [len(x) for x in gs]
    chk = use & ev["home_sk"].notna().to_numpy() & ~ev["penalty_shot"].fillna(False).to_numpy(dtype=bool) \
        & ~ev["type"].isin(NO_CHECK).to_numpy()
    ok = (ev["n_home_sk"].astype("float").to_numpy() == ev["home_sk"].astype("float").to_numpy()) \
        & (ev["n_away_sk"].astype("float").to_numpy() == ev["away_sk"].astype("float").to_numpy()) \
        & ((ev["_home_gn"].to_numpy() > 0) == (ev["home_gin"].astype("float").to_numpy() > 0)) \
        & ((ev["_away_gn"].to_numpy() > 0) == (ev["away_gin"].astype("float").to_numpy() > 0))
    hsk, ask = ev["home_sk"].astype("float").to_numpy(), ev["away_sk"].astype("float").to_numpy()
    hg_, ag_ = ev["home_gin"].astype("float").to_numpy() > 0, ev["away_gin"].astype("float").to_numpy() > 0
    ok_after = (alt_n["home"] == hsk) & (alt_n["away"] == ask) & ((alt_n["home_g"] > 0) == hg_) & ((alt_n["away_g"] > 0) == ag_)
    strict = pd.array([pd.NA] * n, dtype="boolean")
    strict[chk] = ok[chk]
    ev["onice_strict"] = strict
    res = pd.array([pd.NA] * n, dtype="boolean")
    res[chk] = (ok | (ok_after & ev["type"].isin(AFTER_OK).to_numpy()))[chk]
    ev["onice_ok"] = res
    return ev.drop(columns=["_home_gn", "_away_gn"])


# ── stints ──────────────────────────────────────────────────────────────────

def build_stints(ev: pd.DataFrame, sf: pd.DataFrame | None, facts: dict) -> pd.DataFrame:
    if sf is None or ev.empty:
        return pd.DataFrame()
    gtype = facts["gtype"]
    reg = ev[ev["ptype"] != "SO"]
    goals = reg[reg["type"] == "goal"]
    out = []
    for p in sorted(reg["period"].unique()):
        sp = sf[sf["period"] == p]
        if sp.empty:
            continue
        pe = reg[reg["period"] == p]
        plen = int(max(sp["end"].max(), pe["t"].max() if len(pe) else 0))
        cuts = np.unique(np.clip(np.concatenate([[0, plen], sp["start"].to_numpy(), sp["end"].to_numpy()]), 0, plen))
        ss, se = sp["start"].to_numpy(), sp["end"].to_numpy()
        pid, gl, side = sp["pid"].to_numpy(), sp["goalie"].to_numpy(dtype=bool), sp["side"].to_numpy()
        prev_sig, cur = None, None
        for a, b in zip(cuts[:-1], cuts[1:]):
            cover = (ss <= a) & (se >= b)
            sig = (tuple(sorted(set(pid[cover & ~gl & (side == "home")].tolist()))),
                   tuple(sorted(set(pid[cover & gl & (side == "home")].tolist()))),
                   tuple(sorted(set(pid[cover & ~gl & (side == "away")].tolist()))),
                   tuple(sorted(set(pid[cover & gl & (side == "away")].tolist()))))
            if sig == prev_sig and cur is not None:
                cur["t1"] = int(b)
                continue
            cur = {"period": int(p), "t0": int(a), "t1": int(b), "sig": sig}
            out.append(cur)
            prev_sig = sig
    if not out:
        return pd.DataFrame()
    rows = []
    for k, s in enumerate(out):
        hs, hg, as_, ag = s["sig"]
        r = {"game_id": facts["game_id"], "season": facts["season"], "gtype": gtype, "stint": k, "period": s["period"],
             "start": game_seconds(s["period"], s["t0"], "REG", gtype), "end": game_seconds(s["period"], s["t1"], "REG", gtype),
             "t0": s["t0"], "t1": s["t1"]}
        r["dur"] = r["end"] - r["start"]
        for j in range(SLOTS):
            r[HOME_COLS[j]] = hs[j] if j < len(hs) else None
            r[AWAY_COLS[j]] = as_[j] if j < len(as_) else None
        r["home_g"], r["away_g"] = (hg[0] if hg else None), (ag[0] if ag else None)
        r["n_home_sk"], r["n_away_sk"] = len(hs), len(as_)
        r["home_gin"], r["away_gin"] = int(bool(hg)), int(bool(ag))
        r["strength"] = canon.strength_label(len(hs), len(as_))
        r["state"] = canon.strength_state(len(hs), len(as_), r["home_gin"], r["away_gin"]) if hs and as_ else None
        r["bad"] = not (3 <= len(hs) <= 6 and 3 <= len(as_) <= 6) or len(hg) > 1 or len(ag) > 1
        sec0 = r["start"]
        r["score_home"] = int(((goals["sec"] <= sec0) & (goals["is_home"] == True)).sum())  # noqa: E712
        r["score_away"] = int(((goals["sec"] <= sec0) & (goals["is_home"] == False)).sum())  # noqa: E712
        rows.append(r)
    stn = pd.DataFrame(rows)
    # attach events to stints
    ends = {p: (grp["t1"].to_numpy(), grp.index.to_numpy()) for p, grp in stn.groupby("period")}
    sidx = np.full(len(ev), -1, dtype=np.int64)
    for i, (p, t, typ, pt) in enumerate(zip(ev["period"].to_numpy(), ev["t"].to_numpy(), ev["type"].to_numpy(),
                                             ev["ptype"].to_numpy())):
        if pt == "SO" or p not in ends:
            continue
        e, ix = ends[p]
        j = np.searchsorted(e, t, side="right" if typ in START_RULE else "left")
        j = min(j, len(e) - 1)
        sidx[i] = stn.loc[ix[j], "stint"]
    ev["stint"] = pd.array(np.where(sidx >= 0, sidx, 0), dtype="Int64")
    ev.loc[sidx < 0, "stint"] = pd.NA
    # zone starts (home view) and counts
    fo = ev[(ev["type"] == "faceoff") & ev["stint"].notna()]
    zs = {}
    for _, f in fo.iterrows():
        s = int(f["stint"])
        if s in zs or f["x_raw"] is None or pd.isna(f["x_raw"]):
            continue
        if int(f["t"]) == int(stn.at[s, "t0"]) and int(f["period"]) == int(stn.at[s, "period"]):
            xh = float(f["x_raw"]) * facts["dirs"].get(int(f["period"]), 1)
            zs[s] = "O" if xh > 25 else "D" if xh < -25 else "N"
    stn["start_zone"] = [zs.get(k, "F") for k in stn["stint"]]
    e2 = ev[ev["stint"].notna()]
    for side, flag in (("home", True), ("away", False)):
        mine = e2[e2["is_home"] == flag]
        grp = lambda m: m.groupby("stint").size()  # noqa: E731
        stn[f"{side}_sog"] = stn["stint"].map(grp(mine[mine["type"].isin(ON_GOAL)])).fillna(0).astype(int)
        stn[f"{side}_fenwick"] = stn["stint"].map(grp(mine[mine["type"].isin(UNBLOCKED)])).fillna(0).astype(int)
        stn[f"{side}_corsi"] = stn["stint"].map(grp(mine[mine["type"].isin(SHOT_TYPES)])).fillna(0).astype(int)
        stn[f"{side}_goals"] = stn["stint"].map(grp(mine[mine["type"] == "goal"])).fillna(0).astype(int)
        stn[f"{side}_pen"] = stn["stint"].map(grp(mine[mine["type"] == "penalty"])).fillna(0).astype(int)
        stn[f"xg_{side}"] = np.nan
    for c in HOME_COLS + AWAY_COLS + ["home_g", "away_g"]:
        stn[c] = pd.array(stn[c].tolist(), dtype="Int64")
    stn = stn[stn["dur"] > 0].reset_index(drop=True) if (stn["dur"] > 0).any() else stn
    return stn


# ── one game ────────────────────────────────────────────────────────────────

def derive_game(pbp_raw: dict, shifts_raw: dict | None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(events, stints, check) for one game."""
    ev, facts = parse_events(pbp_raw)
    if ev.empty:
        return ev, pd.DataFrame(), {"game_id": facts["game_id"], "events": 0}
    sf = _shift_frame(shifts_raw, facts)
    ev = attach_on_ice(ev, sf)
    stn = build_stints(ev, sf, facts)
    if "stint" not in ev.columns:
        ev["stint"] = pd.array([pd.NA] * len(ev), dtype="Int64")
    chk = ev["onice_ok"].dropna()
    zc = ev["type"].isin(UNBLOCKED) & ev["zone"].notna() & ev["zone_raw"].notna()
    bad = ev[ev["onice_ok"] == False]  # noqa: E712
    check = {"game_id": facts["game_id"], "events": int(len(ev)), "shifts": sf is not None,
             "checked": int(len(chk)), "ok": int(chk.sum()), "ok_strict": int(ev["onice_strict"].dropna().sum()), "rate": round(float(chk.mean()), 4) if len(chk) else None,
             "side_checked": facts["side_checked"], "side_disagree": facts["side_disagree"],
             "shots_xy": int((ev["type"].isin(SHOT_TYPES) & ev["x"].notna()).sum()),
             "shots": int(ev["type"].isin(SHOT_TYPES).sum()),
             "zone_checked": int(zc.sum()), "zone_agree": int((zc & (ev["zone"] == ev["zone_raw"])).sum()),
             "mismatch_types": {str(k): int(v) for k, v in bad["type"].value_counts().items()},
             "mismatches": [[int(r.event_id), int(r.period), int(r.t), r.type, r.sit, int(r.n_home_sk), int(r.n_away_sk)]
                            for r in bad.head(8).itertuples()]}
    ev = ev.drop(columns=["team_id", "hside", "home_dir"], errors="ignore")
    return ev, stn, check


# ── one season ──────────────────────────────────────────────────────────────

EVENT_DTYPES = {"event_id": "Int32", "sort": "Int32", "period": "Int8", "t": "Int16", "sec": "Int16",
                "x_raw": "Int16", "y_raw": "Int16", "x": "Int16", "y": "Int16", "shooter": "Int64", "goalie": "Int64",
                "assist1": "Int64", "assist2": "Int64", "player1": "Int64", "player2": "Int64", "pen_min": "Int8",
                "home_sk": "Int8", "away_sk": "Int8", "home_gin": "Int8", "away_gin": "Int8", "score_home": "Int8",
                "score_away": "Int8", "is_home": "boolean", "penalty_shot": "boolean", "n_home_sk": "Int8",
                "n_away_sk": "Int8", "stint": "Int32", "gtype": "Int8", "onice_ok": "boolean",
                "onice_strict": "boolean"}
CATEGORIES = ("type", "ptype", "team", "zone", "zone_raw", "shot_type", "reason", "pen_type", "pen_desc", "sit",
              "strength", "state")


def _tidy_events(df: pd.DataFrame) -> pd.DataFrame:
    for c, dt in EVENT_DTYPES.items():
        if c in df.columns:
            try:
                df[c] = pd.to_numeric(df[c], errors="coerce").astype(dt) if dt not in ("boolean",) else df[c].astype(dt)
            except (TypeError, ValueError):
                pass
    for c in CATEGORIES:
        if c in df.columns:
            df[c] = df[c].astype("string").astype("category")
    return df


def _sum_types(checks: list[dict]) -> dict:
    out: dict[str, int] = {}
    for c in checks:
        for k, v in (c.get("mismatch_types") or {}).items():
            out[k] = out.get(k, 0) + v
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def build_season(season: int, game_ids: Iterable[int] | None = None, log_every: int = 200) -> dict:
    """Rebuild events.parquet, stints.parquet and onice_check.json of a season from the raw files on disk."""
    season = int(season)
    pdir = st.pbp_path(season, 0).parent
    if game_ids is None:
        game_ids = sorted(int(p.name.split(".")[0]) for p in pdir.glob("*.json.gz")) if pdir.exists() else []
    evs, sts, checks = [], [], []
    for k, gid in enumerate(game_ids):
        raw = st.read_json_gz(st.pbp_path(season, gid))
        if not raw or not raw.get("plays"):
            continue
        sh = st.read_json_gz(st.shifts_path(season, gid))
        try:
            ev, stn, chk = derive_game(raw, sh)
        except Exception as exc:  # noqa: BLE001 - one bad game must not stop a season
            logger.warning("derive %s failed: %s", gid, exc)
            checks.append({"game_id": gid, "error": str(exc)})
            continue
        evs.append(ev)
        if len(stn):
            sts.append(stn)
        checks.append(chk)
        if log_every and (k + 1) % log_every == 0:
            logger.info("derive %d: %d / %d games", season, k + 1, len(game_ids))
    out = {"season": season, "games": len(checks), "built_at": st.now()}
    if not evs:
        return out
    events = _tidy_events(pd.concat(evs, ignore_index=True))
    del evs
    d = st.derived_dir(season)
    d.mkdir(parents=True, exist_ok=True)
    events.to_parquet(st.events_path(season), index=False)
    if sts:
        stints = pd.concat(sts, ignore_index=True)
        for c in ("strength", "state", "start_zone"):
            stints[c] = stints[c].astype("string").astype("category")
        stints.to_parquet(st.stints_path(season), index=False)
        n_stints = int(len(stints))
        del stints
    else:
        n_stints = 0
    good = [c for c in checks if c.get("checked")]
    n_chk = sum(c["checked"] for c in good)
    n_ok = sum(c["ok"] for c in good)
    shots = events["type"].isin(SHOT_TYPES)
    out.update({
        "events": int(len(events)), "stints": n_stints,
        "games_with_shifts": sum(1 for c in checks if c.get("shifts")),
        "shots": int(shots.sum()), "shots_xy": int((shots & events["x"].notna()).sum()),
        "checked": n_chk, "ok": n_ok, "rate": round(n_ok / n_chk, 4) if n_chk else None,
        "ok_strict": sum(c.get("ok_strict", 0) for c in good),
        "rate_strict": round(sum(c.get("ok_strict", 0) for c in good) / n_chk, 4) if n_chk else None,
        "games_below_98": sorted([c["game_id"] for c in good if c["rate"] is not None and c["rate"] < 0.98]),
        "side_checked": sum(c.get("side_checked", 0) for c in checks),
        "zone_checked": sum(c.get("zone_checked", 0) for c in checks),
        "zone_agree": sum(c.get("zone_agree", 0) for c in checks),
        "side_disagree": sum(c.get("side_disagree", 0) for c in checks),
        "errors": [c for c in checks if c.get("error")],
        "mismatch_types": _sum_types(checks),
        "per_game": {str(c["game_id"]): [c.get("checked"), c.get("ok"), c.get("rate"), c.get("mismatches")]
                     for c in checks if c.get("checked") and (c.get("rate") or 0) < 0.98},
        "no_shifts": sorted(c["game_id"] for c in checks if not c.get("shifts") and not c.get("error")),
    })
    st.write_json(st.onice_check_path(season), out, indent=1)
    del events
    return out
