"""
Per game and per player aggregates from the season's events and stints (one pass each, vectorised):

* `individual(ev)`: per (game_id, pid, team) individual counts: goals, primary / secondary assists, shots on goal,
  unblocked and all attempts, ixG (all situations and by strength), hits, hits taken, blocks, giveaways, takeaways,
  faceoffs won / lost (by zone), minor / major penalties taken and drawn, PIM.
* `onice(ev)`: per (game_id, pid, team) on-ice counts for and against (CF, FF, SF, GF, xGF and their against) by the
  player's strength ("5v5", "PP", "SH", "oth"), and on-ice faceoffs by zone at 5v5 (zone starts).
* `toi(st)`: per (game_id, pid, team) time on ice in seconds by strength, from the stints.
* `goalie_games(ev)`: per (game_id, goalie, team) shots, goals, xG faced by strength, danger band and shot type.
* `team_games(ev, st)`: per (game_id, team) counts for / against by strength, and 5v5 time.
* `combos(ev, st, pos_of)`: forward lines and defence pairs at 5v5 (TOI, on-ice for / against).
* `competition(st, metric)`: TOI-weighted teammate and opponent means of a per-player metric at 5v5 (QoT / QoC).

Strength labels are from the player's (or team's) side: 5v5 (both goalies in), PP (more skaters), SH (fewer), oth
(4v4, 3v3, empty net and the rest). Regular-season shootouts (period 5+) are excluded everywhere.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.analytics.context import BLOCK, CORSI, FAC, FENWICK, GIVE, GOAL, HIT, MISS, PENL, SHOT, SLOTS, TAKE

STRENGTHS = ("5v5", "PP", "SH", "oth")
DANGER = ((0.0, 0.08, "low"), (0.08, 0.20, "med"), (0.20, 1.01, "high"))


def playable(ev: pd.DataFrame) -> pd.DataFrame:
    """Drop regular-season shootout rows (period >= 5 in REG games) and preseason / all-star games."""
    if not len(ev):
        return ev
    gt = ev["game_id"].astype(str).str[4:6]
    keep = gt.isin(["02", "03"])
    keep &= ~((gt == "02") & (ev["period"].fillna(0) >= 5))
    return ev[keep.to_numpy()]


def fix_block_team(ev: pd.DataFrame) -> pd.DataFrame:
    """Make `team` the shooting team on blocked shots (the NHL feed's owner is the blocking team): detected from where
    the shooter sits on the ice."""
    b = (ev["type"] == BLOCK).to_numpy()
    if not b.any():
        return ev
    B = ev[b]
    H = B[[f"h{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    V = B[[f"v{j}" for j in range(1, SLOTS + 1)]].to_numpy()
    p = B["p1"].to_numpy(float)
    in_h = (H == p[:, None]).any(axis=1)
    in_v = (V == p[:, None]).any(axis=1)
    known = in_h | in_v
    if known.sum() < 20:
        return ev
    ih = B["is_home"].to_numpy(float)
    shooter_side_home = in_h
    agree = ((ih == 1) == shooter_side_home)[known].mean()
    if agree >= 0.5:
        return ev
    ev = ev.copy()
    idx = np.where(b)[0]
    t, o = ev["team"].to_numpy(object).copy(), ev["opp"].to_numpy(object).copy()
    t[idx], o[idx] = o[idx].copy(), ev["team"].to_numpy(object)[idx]
    ev["team"], ev["opp"] = t, o
    ihv = ev["is_home"].to_numpy(float).copy()
    ihv[idx] = 1 - ihv[idx]
    ev["is_home"] = ihv
    st = ev["st"].to_numpy(object).copy()
    swap = {"PP": "SH", "SH": "PP"}
    st[idx] = [swap.get(s, s) for s in st[idx]]
    ev["st"] = st
    state = ev["state"].to_numpy(object).copy()
    state[idx] = [s if "v" not in str(s) else "v".join(reversed(str(s).split("v"))) for s in state[idx]]
    ev["state"] = state
    ev["score_diff"] = np.where(np.isin(np.arange(len(ev)), idx), -ev["score_diff"].to_numpy(float), ev["score_diff"].to_numpy(float))
    return ev


def strength_label(st: np.ndarray, state: np.ndarray) -> np.ndarray:
    """Event-team strength label: 5v5, PP, SH or oth."""
    return np.where(state == "5v5", "5v5", np.where(st == "PP", "PP", np.where(st == "SH", "SH", "oth")))


def _flip(lab: np.ndarray) -> np.ndarray:
    return np.where(lab == "PP", "SH", np.where(lab == "SH", "PP", lab))


def danger(xg: np.ndarray) -> np.ndarray:
    out = np.full(len(xg), "", dtype=object)
    for lo, hi, nm in DANGER:
        out[(xg >= lo) & (xg < hi)] = nm
    return out


# ---------------------------------------------------------------------------------------------- individual

def individual(ev: pd.DataFrame) -> pd.DataFrame:
    cols = ["game_id", "pid", "team"]
    if not len(ev):
        return pd.DataFrame(columns=cols)
    lab = strength_label(ev["st"].to_numpy(object), ev["state"].to_numpy(object))
    xg = ev["xg"].to_numpy(float) if "xg" in ev else np.full(len(ev), np.nan)
    t = ev["type"].to_numpy(object)
    parts = []

    def add(mask, pid_col, team_col, **vals):
        m = mask & ~np.isnan(ev[pid_col].to_numpy(float))
        if not m.any():
            return
        d = {"game_id": ev["game_id"].to_numpy(object)[m], "pid": ev[pid_col].to_numpy(float)[m],
             "team": ev[team_col].to_numpy(object)[m]}
        for k, v in vals.items():
            d[k] = (np.broadcast_to(v, len(ev))[m]).astype(float)
        parts.append(pd.DataFrame(d))
    is_goal = t == GOAL
    fen = np.isin(t, FENWICK)
    cor = np.isin(t, CORSI)
    sog = np.isin(t, (GOAL, SHOT))
    xg0 = np.nan_to_num(xg)
    ev_cols = {}
    for s in STRENGTHS:
        ms = (lab == s)
        ev_cols[f"g_{s}"] = (is_goal & ms)
        ev_cols[f"ixg_{s}"] = np.where(fen & ms, xg0, 0.0)
        ev_cols[f"iff_{s}"] = (fen & ms)
        ev_cols[f"sog_{s}"] = (sog & ms)
        ev_cols[f"icf_{s}"] = (cor & ms)
    dist = ev["dist"].to_numpy(float) if "dist" in ev else np.full(len(ev), np.nan)
    st_l = ev["shot_type"].astype(str).str.lower().to_numpy(object) if "shot_type" in ev else np.full(len(ev), "", dtype=object)
    reb = ev["rebound"].fillna(0).to_numpy(float) if "rebound" in ev else np.zeros(len(ev))
    rush = ev["rush"].fillna(0).to_numpy(float) if "rush" in ev else np.zeros(len(ev))
    shooter = cor
    add(shooter, "p1", "team", g=is_goal, sog=sog, iff=fen, icf=cor, ixg=np.where(fen, xg0, 0.0), miss=(t == MISS), blocked_by=(t == BLOCK),
        sdist=np.where(fen, np.nan_to_num(dist), 0.0), ndist=(fen & ~np.isnan(dist)),
        reb_att=(fen & (reb == 1)), rush_att=(fen & (rush == 1)), hd_att=(fen & (xg0 >= 0.20)), hd_g=(is_goal & (xg0 >= 0.20)),
        wrist=(fen & np.isin(st_l, ("wrist", "snap"))), slap=(fen & (st_l == "slap")), tip=(fen & np.isin(st_l, ("tip-in", "deflected"))),
        backhand=(fen & (st_l == "backhand")), **{k: v for k, v in ev_cols.items()})
    for c, nm in (("a1", "a1"), ("a2", "a2")):
        if c in ev:
            vals = {nm: np.ones(len(ev))}
            for s in STRENGTHS:
                vals[f"{nm}_{s}"] = (lab == s).astype(float)
            add(is_goal, c, "team", **vals)
    add(t == HIT, "p1", "team", hits=1.0)
    add(t == HIT, "p2", "opp", hits_taken=1.0)
    # a shot blocked by the shooter's own team-mate (the feed's "teammate-blocked") is not a block for the defence
    mate = _teammate_block(ev)
    add((t == BLOCK) & ~mate, "p2", "opp", blocks=1.0)
    add(t == GIVE, "p1", "team", give=1.0)
    add(t == TAKE, "p1", "team", take=1.0)
    zone = _zone_for_event_team(ev)
    fo = t == FAC
    add(fo, "p1", "team", fow=1.0, fow_oz=(zone == "O"), fow_dz=(zone == "D"), fow_nz=(zone == "N"), fow_5v5=(lab == "5v5"))
    add(fo, "p2", "opp", fol=1.0, fol_oz=(zone == "D"), fol_dz=(zone == "O"), fol_nz=(zone == "N"), fol_5v5=(lab == "5v5"))
    pm = ev["pen_min"].to_numpy(float) if "pen_min" in ev else np.full(len(ev), 2.0)
    pm = np.where(np.isnan(pm), 2.0, pm)
    pen = t == PENL
    add(pen, "p1", "team", pen_taken=(pm <= 4), pen_major=(pm == 5), pim=pm)
    add(pen, "p2", "opp", pen_drawn=(pm <= 4))
    if not parts:
        return pd.DataFrame(columns=cols)
    df = pd.concat(parts, ignore_index=True).fillna(0.0)
    return df.groupby(cols, sort=False).sum().reset_index()


def _teammate_block(ev: pd.DataFrame) -> np.ndarray:
    """True on blocked shots whose blocker is on the shooting side (the feed's reason, else the on-ice slots)."""
    b = (ev["type"] == BLOCK).to_numpy()
    out = np.zeros(len(ev), dtype=bool)
    if not b.any():
        return out
    if "reason" in ev:
        out |= b & ev["reason"].astype(str).str.contains("teammate", case=False, na=False).to_numpy()
    H = ev[[f"h{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
    V = ev[[f"v{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
    p2 = ev["p2"].to_numpy(float)
    ih = ev["is_home"].to_numpy(float)
    own = np.where((ih == 1)[:, None], H, V)
    out |= b & (own == p2[:, None]).any(axis=1)
    return out


def side_teams(ev: pd.DataFrame, st: pd.DataFrame) -> pd.DataFrame:
    """(game_id, pid) -> team from the on-ice slots (stints, else events): the side the player skated on."""
    parts = []
    for df in (st, ev):
        if df is None or not len(df):
            continue
        for pre, tcol in (("h", "home_team"), ("v", "away_team")):
            r, pid = _melt(df, pre)
            if len(r):
                parts.append(pd.DataFrame({"game_id": df["game_id"].to_numpy(object)[r], "pid": pid,
                                           "side_team": df[tcol].to_numpy(object)[r]}))
        if parts:
            break
    if not parts:
        return pd.DataFrame(columns=["game_id", "pid", "side_team"])
    m = pd.concat(parts, ignore_index=True)
    c = m.groupby(["game_id", "pid", "side_team"]).size().reset_index(name="n").sort_values("n", ascending=False)
    return c.drop_duplicates(["game_id", "pid"])[["game_id", "pid", "side_team"]].reset_index(drop=True)


def _zone_for_event_team(ev: pd.DataFrame) -> np.ndarray:
    """O / D / N from the event team's side: the feed's zone code (relative to the event owner) when present, else
    the x coordinate (|x| <= 25 neutral; the attacking-right normalisation puts the event team's offensive zone at +x)."""
    if "zone" in ev and ev["zone"].notna().any():
        z = ev["zone"].astype(str).str.upper().str[:1].to_numpy(object)
        return np.where(np.isin(z, ("O", "D", "N")), z, "")
    x = ev["x"].to_numpy(float)
    return np.where(np.isnan(x), "", np.where(x > 25, "O", np.where(x < -25, "D", "N")))


# ---------------------------------------------------------------------------------------------- on ice

def _melt(df: pd.DataFrame, pre: str) -> tuple[np.ndarray, np.ndarray]:
    M = df[[f"{pre}{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
    r, c = np.nonzero(~np.isnan(M))
    return r, M[r, c]


def onice(ev: pd.DataFrame) -> pd.DataFrame:
    cols = ["game_id", "pid", "team"]
    E = ev[ev["type"].isin(CORSI + (FAC,)).to_numpy()]
    if not len(E):
        return pd.DataFrame(columns=cols)
    lab = strength_label(E["st"].to_numpy(object), E["state"].to_numpy(object))
    t = E["type"].to_numpy(object)
    xg = np.nan_to_num(E["xg"].to_numpy(float)) if "xg" in E else np.zeros(len(E))
    zone = _zone_for_event_team(E)
    ih = E["is_home"].to_numpy(float)
    out = []
    for pre, side_home in (("h", 1.0), ("v", 0.0)):
        r, pid = _melt(E, pre)
        if not len(r):
            continue
        is_for = ih[r] == side_home
        team = np.where(side_home == 1.0, E["home_team"].to_numpy(object)[r], E["away_team"].to_numpy(object)[r])
        pl = np.where(is_for, lab[r], _flip(lab[r]))
        tt = t[r]
        d = {"game_id": E["game_id"].to_numpy(object)[r], "pid": pid, "team": team}
        cor = np.isin(tt, CORSI)
        fen = np.isin(tt, FENWICK)
        sog = np.isin(tt, (GOAL, SHOT))
        gl = tt == GOAL
        x = xg[r]
        for s in STRENGTHS:
            ms = pl == s
            for nf, na, m, w in (("cf", "ca", cor, None), ("ff", "fa", fen, None), ("sf", "sa", sog, None), ("gf", "ga", gl, None),
                                 ("xgf", "xga", fen, x)):
                vf = (m & ms & is_for)
                va = (m & ms & ~is_for)
                d[f"{nf}_{s}"] = vf * (w if w is not None else 1.0)
                d[f"{na}_{s}"] = va * (w if w is not None else 1.0)
            if s == "5v5":
                d["hdf_5v5"] = (fen & ms & is_for & (x >= 0.20)).astype(float)
                d["hda_5v5"] = (fen & ms & ~is_for & (x >= 0.20)).astype(float)
        fo = (tt == FAC) & (pl == "5v5")
        z = zone[r]
        zp = np.where(is_for, z, np.where(z == "O", "D", np.where(z == "D", "O", z)))
        d["ozs"] = (fo & (zp == "O")).astype(float)
        d["dzs"] = (fo & (zp == "D")).astype(float)
        d["nzs"] = (fo & (zp == "N")).astype(float)
        out.append(pd.DataFrame(d))
    df = pd.concat(out, ignore_index=True)
    num = [c for c in df.columns if c not in cols]
    df[num] = df[num].astype(float)
    return df.groupby(cols, sort=False).sum().reset_index()


# ---------------------------------------------------------------------------------------------- time on ice

def stint_labels(st: pd.DataFrame, side_home: bool) -> np.ndarray:
    own = st["n_h" if side_home else "n_v"].to_numpy(float)
    opp = st["n_v" if side_home else "n_h"].to_numpy(float)
    hg = st["hg"].to_numpy(float) if "hg" in st else np.zeros(len(st))
    vg = st["vg"].to_numpy(float) if "vg" in st else np.zeros(len(st))
    has_g = not (np.isnan(hg).all() and np.isnan(vg).all())
    both_g = (~np.isnan(hg) & ~np.isnan(vg)) if has_g else np.ones(len(st), dtype=bool)
    lab = np.where(both_g & (own == 5) & (opp == 5), "5v5",
                   np.where(both_g & (own > opp), "PP", np.where(both_g & (own < opp), "SH", "oth")))
    return lab


def playable_stints(st: pd.DataFrame) -> pd.DataFrame:
    if not len(st):
        return st
    gt = st["game_id"].astype(str).str[4:6]
    keep = gt.isin(["02", "03"])
    if "period" in st:
        keep &= ~((gt == "02") & (st["period"].fillna(0) >= 5))
    return st[keep.to_numpy()]


def toi(st: pd.DataFrame) -> pd.DataFrame:
    cols = ["game_id", "pid", "team"]
    if not len(st):
        return pd.DataFrame(columns=cols)
    out = []
    dur = st["dur"].to_numpy(float)
    for pre, side_home in (("h", True), ("v", False)):
        r, pid = _melt(st, pre)
        if not len(r):
            continue
        lab = stint_labels(st, side_home)[r]
        d = {"game_id": st["game_id"].to_numpy(object)[r], "pid": pid,
             "team": st["home_team" if side_home else "away_team"].to_numpy(object)[r]}
        dd = dur[r]
        d["toi"] = dd
        for s in STRENGTHS:
            d[f"toi_{s}"] = np.where(lab == s, dd, 0.0)
        d["shifts"] = np.ones(len(r))
        out.append(pd.DataFrame(d))
    df = pd.concat(out, ignore_index=True)
    return df.groupby(cols, sort=False).sum().reset_index()


def goalie_toi(st: pd.DataFrame) -> pd.DataFrame:
    cols = ["game_id", "pid", "team"]
    if not len(st) or "hg" not in st:
        return pd.DataFrame(columns=cols + ["toi"])
    out = []
    for g, tcol, side_home in (("hg", "home_team", True), ("vg", "away_team", False)):
        m = ~np.isnan(st[g].to_numpy(float))
        lab = stint_labels(st, side_home)
        out.append(pd.DataFrame({"game_id": st["game_id"].to_numpy(object)[m], "pid": st[g].to_numpy(float)[m],
                                 "team": st[tcol].to_numpy(object)[m], "toi": st["dur"].to_numpy(float)[m],
                                 "toi_5v5": np.where(lab == "5v5", st["dur"].to_numpy(float), 0.0)[m],
                                 "toi_SH": np.where(lab == "SH", st["dur"].to_numpy(float), 0.0)[m]}))
    df = pd.concat(out, ignore_index=True)
    return df.groupby(cols, sort=False).sum().reset_index()


# ---------------------------------------------------------------------------------------------- goalies

def goalie_games(ev: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, goalie, team): sa, ga, fa (unblocked faced), xga, by strength (from the goalie's side), danger and
    shot type, rebounds allowed (an attempt by the shooting team within 3 s of a save)."""
    cols = ["game_id", "pid", "team"]
    E = ev[ev["type"].isin(FENWICK).to_numpy()]
    if not len(E):
        return pd.DataFrame(columns=cols)
    g = E["goalie"].to_numpy(float)
    ih = E["is_home"].to_numpy(float)
    # the goalie in net against the shot (the event's goalie column, else the defending side's goalie)
    alt = np.where(ih == 1, E["vg"].to_numpy(float), E["hg"].to_numpy(float))
    g = np.where(np.isnan(g), alt, g)
    m = ~np.isnan(g)
    if not m.any():
        return pd.DataFrame(columns=cols)
    E = E[m]
    g = g[m]
    t = E["type"].to_numpy(object)
    xg = np.nan_to_num(E["xg"].to_numpy(float))
    lab = _flip(strength_label(E["st"].to_numpy(object), E["state"].to_numpy(object)))
    gl = (t == GOAL).astype(float)
    sog = np.isin(t, (GOAL, SHOT)).astype(float)
    dz = danger(xg)
    stp = E["shot_type"].astype(str).str.lower().to_numpy(object) if "shot_type" in E else np.full(len(E), "", dtype=object)
    reb, _ = _rebounds_after(ev, E.index.to_numpy())
    d = {"game_id": E["game_id"].to_numpy(object), "pid": g, "team": E["opp"].to_numpy(object),
         "fa": np.ones(len(E)), "sa": sog, "ga": gl, "xga": xg, "reb": reb, "xreb": np.zeros(len(E))}
    for s in ("5v5", "SH", "PP", "oth"):
        ms = lab == s
        d[f"sa_{s}"], d[f"ga_{s}"], d[f"xga_{s}"], d[f"fa_{s}"] = sog * ms, gl * ms, xg * ms, ms.astype(float)
    for nm in ("low", "med", "high"):
        md = dz == nm
        d[f"sa_{nm}"], d[f"ga_{nm}"], d[f"xga_{nm}"], d[f"fa_{nm}"] = sog * md, gl * md, xg * md, md.astype(float)
    for nm, keys in (("wrist", ("wrist", "snap")), ("slap", ("slap",)), ("tip", ("tip-in", "deflected")), ("back", ("backhand",)),
                     ("other", None)):
        mt = np.isin(stp, keys) if keys else ~np.isin(stp, ("wrist", "snap", "slap", "tip-in", "deflected", "backhand"))
        d[f"ga_{nm}"], d[f"xga_{nm}"], d[f"fa_{nm}"] = gl * mt, xg * mt, mt.astype(float)
    df = pd.DataFrame(d)
    return df.groupby(cols, sort=False).sum().reset_index()


def _rebounds_after(ev: pd.DataFrame, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """1 where the next event of the game is an attempt by the same team within 3 s (a rebound allowed)."""
    gid = ev["game_id"].to_numpy(object)
    sec = ev["sec"].to_numpy(float)
    team = ev["team"].to_numpy(object)
    t = ev["type"].to_numpy(object)
    pos = ev.index.get_indexer(idx)
    nxt = pos + 1
    ok = nxt < len(ev)
    nxt_c = np.where(ok, nxt, 0)
    rb = ok & (gid[nxt_c] == gid[pos]) & np.isin(t[nxt_c], CORSI) & (team[nxt_c] == team[pos]) & \
        ((sec[nxt_c] - sec[pos]) <= 3) & (t[pos] == SHOT)
    return rb.astype(float), np.zeros(len(idx))


# ---------------------------------------------------------------------------------------------- teams

def team_games(ev: pd.DataFrame, st: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, team): cf/ca, ff/fa, sf/sa, gf/ga, xgf/xga by strength (team's side), hd chances, penalties, faceoffs,
    toi by strength."""
    cols = ["game_id", "team"]
    out = []
    if len(ev):
        E = ev[ev["type"].isin(CORSI + (FAC, PENL, HIT, GIVE, TAKE)).to_numpy()]
        lab = strength_label(E["st"].to_numpy(object), E["state"].to_numpy(object))
        t = E["type"].to_numpy(object)
        xg = np.nan_to_num(E["xg"].to_numpy(float)) if "xg" in E else np.zeros(len(E))
        pm = E["pen_min"].to_numpy(float) if "pen_min" in E else np.full(len(E), 2.0)
        for for_side in (True, False):
            team = E["team" if for_side else "opp"].to_numpy(object)
            pl = lab if for_side else _flip(lab)
            d = {"game_id": E["game_id"].to_numpy(object), "team": team}
            sfx = "f" if for_side else "a"
            for s in STRENGTHS + ("all",):
                ms = (pl == s) if s != "all" else np.ones(len(E), dtype=bool)
                d[f"c{sfx}_{s}"] = (np.isin(t, CORSI) & ms).astype(float)
                d[f"f{sfx}_{s}"] = (np.isin(t, FENWICK) & ms).astype(float)
                d[f"s{sfx}_{s}"] = (np.isin(t, (GOAL, SHOT)) & ms).astype(float)
                d[f"g{sfx}_{s}"] = ((t == GOAL) & ms).astype(float)
                d[f"xg{sfx}_{s}"] = np.where(np.isin(t, FENWICK) & ms, xg, 0.0)
                d[f"hd{sfx}_{s}"] = (np.isin(t, FENWICK) & ms & (xg >= 0.20)).astype(float)
            d[f"pen_{'taken' if for_side else 'drawn'}"] = ((t == PENL) & (np.nan_to_num(pm, nan=2.0) <= 4)).astype(float)
            d[f"fo{'w' if for_side else 'l'}"] = (t == FAC).astype(float)
            d[f"hits_{'f' if for_side else 'a'}"] = (t == HIT).astype(float)
            d[f"give" if for_side else "give_opp"] = (t == GIVE).astype(float)
            d[f"take" if for_side else "take_opp"] = (t == TAKE).astype(float)
            out.append(pd.DataFrame(d))
    if len(st):
        for side_home, tcol in ((True, "home_team"), (False, "away_team")):
            lab = stint_labels(st, side_home)
            d = {"game_id": st["game_id"].to_numpy(object), "team": st[tcol].to_numpy(object)}
            dur = st["dur"].to_numpy(float)
            d["toi_all"] = dur
            for s in STRENGTHS:
                d[f"toi_{s}"] = np.where(lab == s, dur, 0.0)
            out.append(pd.DataFrame(d))
    if not out:
        return pd.DataFrame(columns=cols)
    df = pd.concat(out, ignore_index=True)
    num = [c for c in df.columns if c not in cols]
    df[num] = df[num].astype(float).fillna(0.0)
    return df.groupby(cols, sort=False)[num].sum().reset_index()


# ---------------------------------------------------------------------------------------------- lines

def combos(ev: pd.DataFrame, st: pd.DataFrame, pos_of: dict[float, str]) -> pd.DataFrame:
    """5v5 forward lines (three forwards) and defence pairs (two defencemen) per team: toi, games, cf/ca, xgf/xga,
    gf/ga. Columns: team, kind ("F" / "D"), ids (tuple of float pids, sorted), toi, games, cf, ca, xgf, xga, gf, ga."""
    cols = ["team", "kind", "key", "toi", "games", "cf", "ca", "xgf", "xga", "gf", "ga"]
    if not len(st):
        return pd.DataFrame(columns=cols)
    S = st[(stint_labels(st, True) == "5v5")]
    rows = []
    keys_by_side: dict[tuple, np.ndarray] = {}
    for pre, tcol in (("h", "home_team"), ("v", "away_team")):
        M = S[[f"{pre}{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
        fk, dk = _line_keys(M, pos_of)
        keys_by_side[(pre, "F")] = fk
        keys_by_side[(pre, "D")] = dk
        for kind, k in (("F", fk), ("D", dk)):
            rows.append(pd.DataFrame({"team": S[tcol].to_numpy(object), "kind": kind, "key": k, "toi": S["dur"].to_numpy(float),
                                      "game_id": S["game_id"].to_numpy(object)}))
    T = pd.concat(rows, ignore_index=True)
    T = T[T["key"] != ""]
    if not len(T):
        return pd.DataFrame(columns=cols)
    agg = T.groupby(["team", "kind", "key"]).agg(toi=("toi", "sum"), games=("game_id", "nunique")).reset_index()
    # events at 5v5 by line key
    E = ev[ev["type"].isin(CORSI).to_numpy() & (ev["state"] == "5v5").to_numpy()]
    if len(E):
        t = E["type"].to_numpy(object)
        xg = np.nan_to_num(E["xg"].to_numpy(float))
        ih = E["is_home"].to_numpy(float)
        evrows = []
        for pre, side in (("h", 1.0), ("v", 0.0)):
            M = E[[f"{pre}{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
            fk, dk = _line_keys(M, pos_of)
            team = E["home_team" if pre == "h" else "away_team"].to_numpy(object)
            is_for = ih == side
            for kind, k in (("F", fk), ("D", dk)):
                evrows.append(pd.DataFrame({
                    "team": team, "kind": kind, "key": k,
                    "cf": is_for.astype(float), "ca": (~is_for).astype(float),
                    "xgf": np.where(is_for & np.isin(t, FENWICK), xg, 0.0), "xga": np.where(~is_for & np.isin(t, FENWICK), xg, 0.0),
                    "gf": (is_for & (t == GOAL)).astype(float), "ga": (~is_for & (t == GOAL)).astype(float)}))
        EV = pd.concat(evrows, ignore_index=True)
        EV = EV[EV["key"] != ""].groupby(["team", "kind", "key"]).sum().reset_index()
        agg = agg.merge(EV, on=["team", "kind", "key"], how="left")
    for c in ("cf", "ca", "xgf", "xga", "gf", "ga"):
        if c not in agg:
            agg[c] = 0.0
        agg[c] = agg[c].fillna(0.0)
    return agg[cols]


def _line_keys(M: np.ndarray, pos_of: dict[float, str]) -> tuple[np.ndarray, np.ndarray]:
    """Per row: the sorted forward trio and defence pair as "p1-p2-p3" keys ("" when the row is not three forwards and
    two defencemen)."""
    n = len(M)
    fk = np.full(n, "", dtype=object)
    dk = np.full(n, "", dtype=object)
    if not n:
        return fk, dk
    have = ~np.isnan(M)
    isd = np.isin(M, np.array([p for p, g in pos_of.items() if g == "D"], dtype=float)) & have
    isf = have & ~isd
    ok = (have.sum(axis=1) == 5) & (isf.sum(axis=1) == 3) & (isd.sum(axis=1) == 2)
    if not ok.any():
        return fk, dk
    F = np.sort(np.where(isf, M, np.inf), axis=1)[ok][:, :3].astype(np.int64).astype(str)
    D = np.sort(np.where(isd, M, np.inf), axis=1)[ok][:, :2].astype(np.int64).astype(str)
    fk[ok] = [f"{a}-{b}-{c}" for a, b, c in F]
    dk[ok] = [f"{a}-{b}" for a, b in D]
    return fk, dk


# ---------------------------------------------------------------------------------------------- competition

def competition(st: pd.DataFrame, metric: dict[float, float]) -> pd.DataFrame:
    """Per pid: qot / qoc = 5v5 TOI-weighted mean of teammates' / opponents' metric values."""
    if not len(st) or not metric:
        return pd.DataFrame(columns=["pid", "qot", "qoc"])
    S = st[(stint_labels(st, True) == "5v5")]
    if not len(S):
        return pd.DataFrame(columns=["pid", "qot", "qoc"])
    dur = S["dur"].to_numpy(float)
    vals = {}
    for pre in ("h", "v"):
        M = S[[f"{pre}{j}" for j in range(1, SLOTS + 1)]].to_numpy(float)
        V = pd.Series(M.ravel()).map(metric).to_numpy(dtype=float).reshape(M.shape) if M.size else M
        vals[pre] = (M, V)
    out = []
    for pre, opp in (("h", "v"), ("v", "h")):
        M, V = vals[pre]
        Mo, Vo = vals[opp]
        s_own = np.nansum(V, axis=1)
        n_own = np.sum(~np.isnan(V), axis=1)
        s_opp = np.nansum(Vo, axis=1)
        n_opp = np.sum(~np.isnan(Vo), axis=1)
        r, c = np.nonzero(~np.isnan(M))
        pv = V[r, c]
        own_cnt = n_own[r] - (~np.isnan(pv)).astype(int)
        own_sum = s_own[r] - np.nan_to_num(pv)
        qot = np.where(own_cnt > 0, own_sum / np.maximum(own_cnt, 1), np.nan)
        qoc = np.where(n_opp[r] > 0, s_opp[r] / np.maximum(n_opp[r], 1), np.nan)
        out.append(pd.DataFrame({"pid": M[r, c], "w": dur[r], "qot": qot, "qoc": qoc}))
    df = pd.concat(out, ignore_index=True)
    res = []
    for k in ("qot", "qoc"):
        m = df[k].notna()
        g = (df.loc[m, k] * df.loc[m, "w"]).groupby(df.loc[m, "pid"]).sum() / df.loc[m, "w"].groupby(df.loc[m, "pid"]).sum()
        res.append(g.rename(k))
    return pd.concat(res, axis=1).reset_index().rename(columns={"index": "pid"})
