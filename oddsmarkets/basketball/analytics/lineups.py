"""
Lineups, on/off and rotations from lineup stints (stints.json rows, or the stint dicts of
`pbp.stints` for one game).

Team-side stint table (`team_stints`): every stint gives two rows, one per team, with the five on
the floor, seconds, possessions and points for and against.

Lineup tables (`lineup_table`): 5-man units (and 2- / 3-man combinations of them) aggregated over
a team's stints:

    poss       = (poss_for + poss_against) / 2
    ortg       = 100 * pts_for / poss_for,   drtg = 100 * pts_against / poss_against,   net = ortg - drtg
    hpm_sum    = sum of the unit's HPM (per 100; for a 2-man pair the pair's HPM plus 3 x the team's
                 minutes-weighted average HPM of the other players, likewise for trios)
    shrunk_net = (net * poss + K * hpm_sum) / (poss + K),    K = SHRINK_POSS possessions

so a unit with few possessions sits near what its players' impact predicts, and one with many
near its own result.

On/off (`on_off`): for each player, the team's net rating with him on the floor and with him off,
from the same stints (off = the team's totals minus his on-floor totals, on his primary team).
"""
from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _io

SHRINK_POSS = 150.0
MIN_LINEUP_POSS = {5: 25.0, 3: 50.0, 2: 75.0}


def stint_frame(stints: Any) -> pd.DataFrame:
    """stints.json content (or rows) as a typed DataFrame in STINT_COLS order."""
    from oddsmarkets.basketball.models.impact import as_stints
    df = as_stints(stints)
    if df.empty:
        return df
    for c in ("t0", "t1"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def from_game_stints(game_id: str, st: list[dict]) -> pd.DataFrame:
    """The STINT dicts of `pbp.stints` for one game as a stint frame (fives of five only)."""
    from oddsmarkets.basketball import pbp as P
    return stint_frame({"cols": _io.STINT_COLS, "rows": P.stint_rows(game_id, st)})


def team_stints(df: pd.DataFrame, games: dict) -> pd.DataFrame:
    """Two rows per stint: game_id, team, opp, five (sorted tuple), opp_five, t0, t1, sec, poss_for,
    poss_against, pts_for, pts_against."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["game_id", "team", "opp", "five", "opp_five", "t0", "t1", "sec", "poss_for", "poss_against",
                                     "pts_for", "pts_against"])
    gid = df["game_id"].astype(str).to_numpy()
    home = np.array([str((games.get(g) or {}).get("home")) for g in gid])
    away = np.array([str((games.get(g) or {}).get("away")) for g in gid])
    H = [tuple(sorted(r)) for r in df[["h1", "h2", "h3", "h4", "h5"]].astype(str).to_numpy().tolist()]
    A = [tuple(sorted(r)) for r in df[["a1", "a2", "a3", "a4", "a5"]].astype(str).to_numpy().tolist()]
    sec = (df["t1"] - df["t0"]).clip(lower=0).to_numpy(float)
    common = {"game_id": np.concatenate([gid, gid]), "t0": np.concatenate([df["t0"].to_numpy(float)] * 2),
              "t1": np.concatenate([df["t1"].to_numpy(float)] * 2), "sec": np.concatenate([sec, sec])}
    out = pd.DataFrame({**common, "team": np.concatenate([home, away]), "opp": np.concatenate([away, home]),
                        "poss_for": np.concatenate([df["poss_h"].to_numpy(float), df["poss_a"].to_numpy(float)]),
                        "poss_against": np.concatenate([df["poss_a"].to_numpy(float), df["poss_h"].to_numpy(float)]),
                        "pts_for": np.concatenate([df["pts_h"].to_numpy(float), df["pts_a"].to_numpy(float)]),
                        "pts_against": np.concatenate([df["pts_a"].to_numpy(float), df["pts_h"].to_numpy(float)])})
    out["five"] = H + A
    out["opp_five"] = A + H
    return out


def _rates(pf, pa, possf, possa) -> dict:
    ortg = 100.0 * pf / possf if possf > 0 else None
    drtg = 100.0 * pa / possa if possa > 0 else None
    net = ortg - drtg if ortg is not None and drtg is not None else None
    return {"ortg": ortg, "drtg": drtg, "net": net}


def lineup_table(ts: pd.DataFrame, team: str, size: int = 5, hpm: dict | None = None, min_poss: float | None = None,
                 k: float = SHRINK_POSS, limit: int | None = None) -> list[dict]:
    """Units of `size` players for one team, most possessions first:
    [{"players","sec","poss","pts_for","pts_against","ortg","drtg","net","hpm_sum","shrunk_net"}]."""
    sub = ts[ts["team"] == str(team)]
    if sub.empty:
        return []
    agg: dict[tuple, list[float]] = {}
    for five, sec, pf, pa, qf, qa in zip(sub["five"], sub["sec"], sub["pts_for"], sub["pts_against"], sub["poss_for"], sub["poss_against"]):
        units = [five] if size >= 5 else combinations(five, size)
        for u in units:
            a = agg.setdefault(u, [0.0, 0.0, 0.0, 0.0, 0.0])
            a[0] += sec; a[1] += pf; a[2] += pa; a[3] += qf; a[4] += qa
    h = hpm or {}
    # the team's minutes-weighted HPM: fills the missing slots of a 2- / 3-man unit
    sec_p: dict[str, float] = {}
    for five, sec in zip(sub["five"], sub["sec"]):
        for p in five:
            sec_p[p] = sec_p.get(p, 0.0) + sec
    tot = sum(sec_p.values()) or 1.0
    team_avg = sum(_h(h, p) * s for p, s in sec_p.items()) / tot
    floor = MIN_LINEUP_POSS.get(size, 25.0) if min_poss is None else min_poss
    out = []
    for u, (sec, pf, pa, qf, qa) in agg.items():
        poss = 0.5 * (qf + qa)
        r = _rates(pf, pa, qf, qa)
        hs = sum(_h(h, p) for p in u) + (5 - len(u)) * team_avg
        shr = ((r["net"] if r["net"] is not None else 0.0) * poss + k * hs) / (poss + k)
        out.append({"players": list(u), "sec": sec, "poss": poss, "pts_for": pf, "pts_against": pa, **r, "hpm_sum": hs,
                    "shrunk_net": shr, "qualified": poss >= floor})
    out.sort(key=lambda r: -r["poss"])
    return out[:limit] if limit else out


def _h(h: dict, p: str) -> float:
    v = h.get(p)
    if isinstance(v, dict):
        v = v.get("t")
    try:
        x = float(v)
        return x if np.isfinite(x) else -2.0
    except (TypeError, ValueError):
        return -2.0                                          # replacement level for players without HPM


def on_off(ts: pd.DataFrame, team: str | None = None) -> dict[str, dict]:
    """{pid: {"team","poss_on","poss_off","on_ortg","on_drtg","on_net","off_ortg","off_drtg","off_net","diff","sec_on",
    "pts_for_on","pts_against_on","poss_for_on","poss_against_on"}} (per team when `team` is given, else on each
    player's team with the most seconds)."""
    if ts is None or ts.empty:
        return {}
    sub = ts if team is None else ts[ts["team"] == str(team)]
    tot = sub.groupby("team")[["sec", "pts_for", "pts_against", "poss_for", "poss_against"]].sum()
    acc: dict[tuple, np.ndarray] = {}
    for tm, five, sec, pf, pa, qf, qa in zip(sub["team"], sub["five"], sub["sec"], sub["pts_for"], sub["pts_against"],
                                            sub["poss_for"], sub["poss_against"]):
        v = np.array([sec, pf, pa, qf, qa])
        for p in five:
            key = (p, tm)
            if key in acc:
                acc[key] += v
            else:
                acc[key] = v.copy()
    best: dict[str, tuple] = {}
    for (p, tm), v in acc.items():
        if p not in best or v[0] > best[p][1][0]:
            best[p] = (tm, v)
    out = {}
    for p, (tm, v) in best.items():
        t = tot.loc[tm].to_numpy(float)
        off = t - v
        on_r = _rates(v[1], v[2], v[3], v[4])
        off_r = _rates(off[1], off[2], off[3], off[4])
        out[p] = {"team": tm, "sec_on": v[0], "poss_on": 0.5 * (v[3] + v[4]), "poss_off": 0.5 * (off[3] + off[4]),
                  "pts_for_on": v[1], "pts_against_on": v[2], "poss_for_on": v[3], "poss_against_on": v[4],
                  "on_ortg": on_r["ortg"], "on_drtg": on_r["drtg"], "on_net": on_r["net"],
                  "off_ortg": off_r["ortg"], "off_drtg": off_r["drtg"], "off_net": off_r["net"],
                  "diff": (on_r["net"] - off_r["net"]) if on_r["net"] is not None and off_r["net"] is not None else None}
    return out


def rotation(ts: pd.DataFrame, game_id: str) -> dict[str, dict[str, list[list[float]]]]:
    """{team: {pid: [[t0, t1], ...]}}: merged on-floor intervals in game seconds for one game."""
    sub = ts[ts["game_id"] == str(game_id)].sort_values("t0")
    out: dict[str, dict[str, list[list[float]]]] = {}
    for tm, five, t0, t1 in zip(sub["team"], sub["five"], sub["t0"], sub["t1"]):
        d = out.setdefault(str(tm), {})
        for p in five:
            iv = d.setdefault(p, [])
            if iv and abs(iv[-1][1] - t0) < 0.51:
                iv[-1][1] = float(t1)
            else:
                iv.append([float(t0), float(t1)])
    return out


def shots_on_floor(shots: pd.DataFrame, stints: pd.DataFrame, games: dict) -> pd.DataFrame:
    """For each shot, the defending five on the floor: columns def_team, d1..d5 (None where no stint
    covers the shot). `shots` needs game_id, t, team; `stints` is a stint frame."""
    n = len(shots)
    cols = {f"d{i}": np.full(n, None, object) for i in range(1, 6)}
    def_team = np.full(n, None, object)
    if n == 0 or stints is None or stints.empty:
        return pd.DataFrame({"def_team": def_team, **cols}, index=shots.index)
    gids = sorted(set(stints["game_id"].astype(str)) | set(shots["game_id"].astype(str)))
    gi = {g: i for i, g in enumerate(gids)}
    st = stints.assign(_g=stints["game_id"].astype(str).map(gi)).sort_values(["_g", "t0"])
    key0 = st["_g"].to_numpy(float) * 1e5 + st["t0"].to_numpy(float)
    key1 = st["_g"].to_numpy(float) * 1e5 + st["t1"].to_numpy(float)
    sk = shots["game_id"].astype(str).map(gi).to_numpy(float) * 1e5 + pd.to_numeric(shots["t"], errors="coerce").fillna(-1).to_numpy(float)
    j = np.searchsorted(key0, sk, side="right") - 1
    ok = (j >= 0) & (sk <= key1[np.clip(j, 0, len(key1) - 1)] + 0.01)
    # a shot at the exact boundary of two stints belongs to the earlier one (the shot precedes the substitution)
    H = st[["h1", "h2", "h3", "h4", "h5"]].astype(str).to_numpy()
    A = st[["a1", "a2", "a3", "a4", "a5"]].astype(str).to_numpy()
    sg = st["game_id"].astype(str).to_numpy()
    shooter_team = shots["team"].astype(str).to_numpy()
    for k in np.nonzero(ok)[0]:
        jj = j[k]
        g = games.get(sg[jj]) or {}
        home = str(g.get("home"))
        five = A[jj] if shooter_team[k] == home else H[jj]
        def_team[k] = str(g.get("away")) if shooter_team[k] == home else home
        for i in range(5):
            cols[f"d{i + 1}"][k] = five[i]
    return pd.DataFrame({"def_team": def_team, **cols}, index=shots.index)


def rotation_matrix(box: pd.DataFrame, team: str, max_players: int = 18) -> dict:
    """{"games": [gid...], "players": [pid...], "minutes": [[minutes of player i in game j]]} for one team
    (players by total minutes, games by date)."""
    sub = box[(box["team"] == str(team))] if box is not None and not box.empty else pd.DataFrame()
    if sub.empty:
        return {"games": [], "players": [], "minutes": []}
    order_g = sub.drop_duplicates("game_id").sort_values(["date", "game_id"])["game_id"].astype(str).tolist()
    tot = sub.groupby("player_id")["sec"].sum().sort_values(ascending=False)
    players = [str(p) for p in tot.index[:max_players] if tot[p] > 0]
    piv = sub.pivot_table(index="player_id", columns="game_id", values="sec", aggfunc="sum").fillna(0.0)
    mins = [[round(float(piv.at[p, g]) / 60.0, 1) if (p in piv.index and g in piv.columns) else 0.0 for g in order_g] for p in players]
    return {"games": order_g, "players": players, "minutes": mins}


def continuity(box: pd.DataFrame, prev_box: pd.DataFrame | None, team: str) -> float | None:
    """Share of this season's team minutes played by players who also played for the team last season."""
    if box is None or box.empty or prev_box is None or prev_box.empty:
        return None
    cur = box[box["team"] == str(team)]
    prev = set(prev_box[prev_box["team"] == str(team)]["player_id"].astype(str))
    tot = float(cur["sec"].sum())
    if tot <= 0 or not prev:
        return None
    return float(cur[cur["player_id"].astype(str).isin(prev)]["sec"].sum() / tot)


def players_in(units: Iterable[dict]) -> set[str]:
    return {p for u in units for p in u["players"]}
