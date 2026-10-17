"""
Player value ("Gridiron Value"): EPA attributed to passers, rushers and receivers, then adjusted for the
opponent and the supporting cast.

1. Raw credit (conventional, not additive across roles): the passer is credited with the whole EPA of
   his dropbacks (passes, sacks, scrambles); a receiver with the whole EPA of his targets, split into air
   EPA (EP at the catch point, or the whole play when incomplete, less EP before) and YAC EPA (the rest);
   a rusher with his designed runs. A pass's EPA therefore appears under both the passer and the receiver:
   step 2 is where it is shared out. EPA is nflverse's (`epa`, with its `air_epa` / `yac_epa`) by default,
   or ours (`epa_source="ours"`: ep.py's EPA, the air part from our EP model at the catch point).
2. Adjusted value (per season): ridge regression of play EPA on role indicators (passer on dropbacks,
   receiver on targets, rusher on designed runs) plus the defence (a team indicator on every play), with
   unpenalised pass and run intercepts. Each role has its own penalty (LAMBDA, in pseudo-plays: a
   coefficient is shrunk like a mean with that many league-average plays), so a receiver is measured net of
   his quarterback and the defences he faced, and vice versa. Value = coefficient x plays (EPA above an
   average player in that role) and per play.
3. On-field RAPM (2016-2025, participation): ridge of play EPA on the eleven offensive players on the field
   plus the defence team, penalty RAPM_LAMBDA. It is the only measure that reaches offensive linemen, but
   linemen play together almost every snap, so their coefficients are close to collinear and heavily
   shrunk; read them as team-level blocking credit, not individual grades. No defensive individuals: the
   defence enters as a team. Not available in-season (participation is published after each season).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io, ep as epm

MODEL_VERSION = "pv-2"
LAMBDA = {"passer": 200.0, "receiver": 60.0, "rusher": 120.0, "def": 600.0}
RAPM_LAMBDA = 1500.0


def play_rows(d: pd.DataFrame, epa_source: str = "nflverse", ep_fit: dict | None = None) -> pd.DataFrame:
    """Dropbacks and designed runs with EPA, the air / YAC split and role ids."""
    pt = d["play_type"].astype(str)
    db = pd.to_numeric(d["qb_dropback"], errors="coerce").fillna(0) == 1
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    kn = pd.to_numeric(d.get("qb_kneel"), errors="coerce").fillna(0) == 1 if "qb_kneel" in d else False
    run = (pt == "run") & ~db
    m = (db | run) & ~tp & ~kn & pt.isin(["pass", "run"])
    s = d[m].copy()
    if epa_source == "ours" and "epa_ours" in s:
        e = pd.to_numeric(s["epa_ours"], errors="coerce").to_numpy(float)
    else:
        e = pd.to_numeric(s["epa"], errors="coerce").to_numpy(float)
    comp = pd.to_numeric(s["complete_pass"], errors="coerce").fillna(0).to_numpy() == 1
    targeted = s["receiver_player_id"].notna().to_numpy() & (pd.to_numeric(s["pass_attempt"], errors="coerce").fillna(0).to_numpy() == 1) \
        & (pd.to_numeric(s["sack"], errors="coerce").fillna(0).to_numpy() == 0)
    if epa_source == "ours" and ep_fit is not None:
        air = air_epa_ours(s, ep_fit, e)
    else:
        air = pd.to_numeric(s.get("air_epa"), errors="coerce").to_numpy(float) if "air_epa" in s else np.full(len(s), np.nan)
    air = np.where(targeted & ~comp, e, air)
    air = np.where(targeted & ~np.isfinite(air), e, air)
    yac = np.where(targeted & comp, e - air, 0.0)
    out = pd.DataFrame({"season": pd.to_numeric(s["season"], errors="coerce").to_numpy(float),
                        "game_id": s["game_id"].astype(str).to_numpy(), "play_id": pd.to_numeric(s["play_id"], errors="coerce").to_numpy(float),
                        "team": s["posteam"].astype(object).to_numpy(), "opp": s["defteam"].astype(object).to_numpy(),
                        "kind": np.where(db[m].to_numpy(), "pass", "run"), "epa": e,
                        "passer": np.where(db[m].to_numpy(), s["passer_player_id"].astype(object).to_numpy(), None),
                        "receiver": np.where(targeted, s["receiver_player_id"].astype(object).to_numpy(), None),
                        "rusher": np.where(run[m].to_numpy(), s["rusher_player_id"].astype(object).to_numpy(), None),
                        "targeted": targeted, "air_epa": np.where(targeted, air, np.nan), "yac_epa": np.where(targeted, yac, np.nan),
                        "off_players": s["p_off_players"].astype(object).to_numpy() if "p_off_players" in s else None})
    # scrambles: nflverse lists the QB as rusher; the passer column carries him on dropbacks
    sc = (pd.to_numeric(s.get("qb_scramble"), errors="coerce").fillna(0).to_numpy() == 1) if "qb_scramble" in s else np.zeros(len(s), bool)
    out.loc[sc & out["passer"].isna().to_numpy(), "passer"] = s["rusher_player_id"].astype(object).to_numpy()[sc & out["passer"].isna().to_numpy()]
    names = {}
    for col, nm in (("passer_player_id", "passer_player_name"), ("receiver_player_id", "receiver_player_name"),
                    ("rusher_player_id", "rusher_player_name")):
        if col in s and nm in s:
            names.update(dict(zip(s[col].dropna().astype(str), s.loc[s[col].notna(), nm].astype(str))))
    out.attrs["names"] = names
    return out[np.isfinite(out["epa"].to_numpy(float))].reset_index(drop=True)


def air_epa_ours(s: pd.DataFrame, ep_fit: dict, epa: np.ndarray) -> np.ndarray:
    """EP at the catch point (our model) less EP before: first down when the air yards reach the line to gain,
    a touchdown when they reach the goal line, a turnover on downs on a short 4th-down catch."""
    yl = pd.to_numeric(s["yardline_100"], errors="coerce").to_numpy(float)
    ay = pd.to_numeric(s["air_yards"], errors="coerce").to_numpy(float)
    togo = pd.to_numeric(s["ydstogo"], errors="coerce").to_numpy(float)
    dn = pd.to_numeric(s["down"], errors="coerce").to_numpy(float)
    ep0 = pd.to_numeric(s.get("ep_ours"), errors="coerce").to_numpy(float) if "ep_ours" in s else np.full(len(s), np.nan)
    ny = np.clip(yl - np.nan_to_num(ay), 1, 99)
    first = np.nan_to_num(ay) >= togo
    st = s.copy()
    st["yardline_100"] = ny
    st["down"] = np.where(first, 1.0, np.minimum(dn + 1, 4))
    st["ydstogo"] = np.where(first, np.minimum(10, ny), np.maximum(1, togo - np.nan_to_num(ay)))
    st["goal_to_go"] = (st["ydstogo"] >= ny).astype(float)
    ep1 = epm.predict(ep_fit, st)
    tod = (dn == 4) & ~first
    if tod.any():
        so = st.copy()
        so["yardline_100"] = 100 - ny
        so["down"], so["ydstogo"] = 1.0, np.minimum(10, 100 - ny)
        so["score_differential"] = -pd.to_numeric(s["score_differential"], errors="coerce")
        so["home"] = 1 - pd.to_numeric(s["home"], errors="coerce")
        ep1 = np.where(tod, -epm.predict(ep_fit, so), ep1)
    ep1 = np.where(np.nan_to_num(ay) >= yl, 7.0, ep1)
    return ep1 - ep0


def _sum_or_nan(s: pd.Series) -> float:
    return float(s.sum(min_count=1)) if s.notna().any() else float("nan")


def raw_attribution(p: pd.DataFrame) -> pd.DataFrame:
    """Per player-season raw EPA by role: passers all dropback EPA, receivers all target EPA (with the
    air / YAC split), rushers their designed runs."""
    t = p["targeted"].to_numpy(bool)
    air, yac = p["air_epa"].to_numpy(float), p["yac_epa"].to_numpy(float)
    parts = [
        pd.DataFrame({"player": p["passer"], "season": p["season"], "team": p["team"], "role": "passer",
                      "credit": p["epa"], "air": np.nan, "yac": np.nan})[p["passer"].notna().to_numpy()],
        pd.DataFrame({"player": p["receiver"], "season": p["season"], "team": p["team"], "role": "receiver",
                      "credit": p["epa"], "air": air, "yac": yac})[p["receiver"].notna().to_numpy() & t],
        pd.DataFrame({"player": p["rusher"], "season": p["season"], "team": p["team"], "role": "rusher",
                      "credit": p["epa"], "air": np.nan, "yac": np.nan})[p["rusher"].notna().to_numpy() & p["passer"].isna().to_numpy()],
    ]
    r = pd.concat(parts, ignore_index=True)
    return r.groupby(["player", "season", "role"]).agg(team=("team", "last"), raw_epa=("credit", "sum"),
                                                      air_epa=("air", _sum_or_nan), yac_epa=("yac", _sum_or_nan),
                                                      plays=("credit", "size")).reset_index()


def adjusted(p: pd.DataFrame, lam: dict | None = None) -> pd.DataFrame:
    """Role ridge (one season): coefficients per player-role (EPA/play above average) and per defence."""
    import scipy.sparse as sp
    lam = {**LAMBDA, **(lam or {})}
    n = len(p)
    cols, rows, vals, names = [], [], [], []
    base = 2      # pass and run intercepts (unpenalised)
    kind = (p["kind"].to_numpy() == "pass")
    rows += list(range(n)) * 1
    cols += list(np.where(kind, 0, 1))
    vals += [1.0] * n
    names += [("_int", "pass"), ("_int", "run")]
    lam0 = 100.0
    nxt = base
    for role, col in (("passer", "passer"), ("receiver", "receiver"), ("rusher", "rusher"), ("def", "opp")):
        ids = p[col].astype(object).to_numpy()
        if role == "rusher":
            ids = np.where(p["passer"].isna().to_numpy(), ids, None)
        ok = pd.notna(ids)
        codes, uniq = pd.factorize(pd.Series(ids[ok]).astype(str))
        scale = np.sqrt(lam0 / lam[role])
        rows += list(np.flatnonzero(ok))
        cols += list(codes + nxt)
        vals += [scale] * int(ok.sum())
        names += [(role, u) for u in uniq]
        nxt += len(uniq)
    X = sp.csr_matrix((vals, (rows, cols)), shape=(n, nxt))
    b = _io.ridge_sparse(X, p["epa"].to_numpy(float), lam0, unpenalised=base)
    out = []
    counts = {}
    for role, col in (("passer", "passer"), ("receiver", "receiver"), ("rusher", "rusher"), ("def", "opp")):
        ids = p[col].astype(object)
        if role == "rusher":
            ids = ids.where(p["passer"].isna(), None)
        counts[role] = ids.dropna().astype(str).value_counts().to_dict()
    for j, (role, u) in enumerate(names):
        if role == "_int":
            continue
        scale = np.sqrt(lam0 / lam[role])
        coef = float(b[j] * scale)
        nplays = counts[role].get(u, 0)
        out.append({"player": u, "role": role, "per_play": coef, "plays": int(nplays), "value": coef * nplays})
    return pd.DataFrame(out)


def rapm(p: pd.DataFrame, lam: float = RAPM_LAMBDA) -> pd.DataFrame:
    """On-field ridge: play EPA on the eleven offensive players plus the defence (participation seasons)."""
    import scipy.sparse as sp
    q = p[pd.Series(p["off_players"]).notna().to_numpy()]
    q = q[q["off_players"].astype(str).str.len() > 0].reset_index(drop=True)
    if len(q) < 500:
        return pd.DataFrame(columns=["player", "per_play", "plays"])
    ex = q["off_players"].astype(str).str.split(";").explode()
    ex = ex[ex.str.len() > 0]
    pc, pu = pd.factorize(ex.to_numpy())
    dc, du = pd.factorize(q["opp"].astype(str))
    n = len(q)
    rows = np.concatenate([ex.index.to_numpy(), np.arange(n), np.arange(n)])
    cols = np.concatenate([2 + pc, 2 + len(pu) + dc, np.where(q["kind"].to_numpy() == "pass", 0, 1)])
    X = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, 2 + len(pu) + len(du)))
    b = _io.ridge_sparse(X, q["epa"].to_numpy(float), lam, unpenalised=2)
    plays = pd.Series(pc).value_counts().sort_index()
    return pd.DataFrame({"player": pu, "per_play": b[2:2 + len(pu)], "plays": plays.reindex(range(len(pu))).fillna(0).to_numpy()})


def season_value(season: int, d: pd.DataFrame | None = None, epa_source: str = "nflverse") -> dict:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return {}
    ep_fit = None
    if epa_source == "ours":
        ep_fit = epm.current_fit()
        o = epm.for_season(season, d)
        d = d.merge(o[["game_id", "play_id", "ep_ours", "epa_ours"]], on=["game_id", "play_id"], how="left")
    p = play_rows(d, epa_source, ep_fit)
    names = p.attrs.get("names", {})
    raw = raw_attribution(p)
    adj = adjusted(p)
    adj_p = adj[adj["role"] != "def"].rename(columns={"per_play": "adj_per_play", "plays": "adj_plays", "value": "adj_value"})
    raw["player"] = raw["player"].astype(str)
    tab = raw.merge(adj_p, on=["player", "role"], how="outer")
    tab["season"] = int(season)
    pl = _io.players()
    tab["name"] = tab["player"].map(names).fillna(tab["player"].map(pl["display_name"]) if len(pl) else None)
    out = {"players": tab.sort_values("adj_value", ascending=False).reset_index(drop=True),
           "defense": adj[adj["role"] == "def"].rename(columns={"player": "team"}).reset_index(drop=True)}
    if 2016 <= season <= 2025:
        r = rapm(p)
        if len(r):
            pl = _io.players()
            r["name"] = r["player"].map(pl["display_name"]) if len(pl) else None
            r["position"] = r["player"].map(pl["position"]) if len(pl) else None
            r["name"] = r["name"].fillna(r["player"].map(names))
            out["rapm"] = r.sort_values("per_play", ascending=False).reset_index(drop=True)
    return out


def for_season(season: int, epa_source: str = "nflverse", use_cache: bool = True) -> dict:
    f = epm.current_fit() if epa_source == "ours" else None
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, epa_source, (f or {}).get("key"))

    def build():
        r = season_value(season, epa_source=epa_source)
        return {k: _io.clean(v.to_dict("records")) for k, v in r.items()}
    return _io.cached("player_value", f"{int(season)}_{epa_source}", key, build, use_cache)
