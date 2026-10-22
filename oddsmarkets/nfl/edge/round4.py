"""
Round 4 candidate features (pre-registered in docs/research/nfl_edge.md section 11.1). Each value uses only games
played (or forecasts issued) before the decision; see each function.

weather_attach   wx_close / wx24: realised weather on training rows, forecasts on scored rows (`<col>__pred`, read by
                 fit.wf_predict for the predicted week only)
referee          t_ref (shrunk market residual of the referee's earlier games' totals), t_refpen (shrunk flag rate)
qb_cpoe          f_qbx: the expected starters' shrunk, exponentially weighted CPOE, home minus away
kalman           f_kf / t_kf: state-space market ratings from earlier closing lines (optionally results too)
late_stakes      the section-9 stakes features times 1[regular-season week >= 17]
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

logger = logging.getLogger(__name__)
CACHE = D.cache_root() / "edge"


def _wk_first(R: pd.DataFrame) -> pd.Series:
    """Per row: the first date of its season-week (the information cut-off of every feature here)."""
    d = pd.to_datetime(R["date"])
    return d.groupby([R["season"], R["week"]]).transform("min")


# ── weather ─────────────────────────────────────────────────────────────────

def load_weather() -> pd.DataFrame:
    return pd.read_parquet(CACHE / "weather.parquet")


def _outdoor(R: pd.DataFrame) -> np.ndarray:
    roof = R["roof"].astype(str).str.lower()
    return (~roof.isin(["dome", "closed"])).to_numpy(float)


def weather_attach(R: pd.DataFrame, W: pd.DataFrame, mode: str, rain: str | None, scored: str,
                   test_from: str = "2024-02-01") -> pd.DataFrame:
    """Rows of one decision mode with t_wind, t_cold (and t_rain / t_wet when `rain`) set for training from realised
    weather (nflverse reading, else ERA5; precipitation ERA5) and `<col>__pred` for the predicted week from `scored`:
    'realised' (the design proxy), 'fc1' (forecast about a day old: close rows) or 'fc2' (about two days old: the
    t - 24 h rows). Close rows keep the nflverse reading on scored rows and fill only its gaps from the forecast.
    Forecast wind / precipitation exist from February 2024 (temperature from March 2021); earlier scored rows get the
    production defaults (wind 5 mph, 60 F, no precipitation)."""
    R = R.merge(W, on="game_id", how="left")
    out = _outdoor(R)
    rd_w = pd.to_numeric(R["wind"], errors="coerce") if mode == "close" else pd.Series(np.nan, index=R.index)
    rd_t = pd.to_numeric(R["temp"], errors="coerce") if mode == "close" else pd.Series(np.nan, index=R.index)
    # realised (training): the game-day reading where nflverse has one, else ERA5 (the close rows of the same game)
    if mode != "close":
        S = load_readings()
        rd_w = R["game_id"].map(S["wind"])
        rd_t = R["game_id"].map(S["temp"])
    wind_r = rd_w.fillna(R.get("era5_wind")).fillna(5.0).to_numpy(float)
    temp_r = rd_t.fillna(R.get("era5_temp")).fillna(60.0).to_numpy(float)
    prec_r = R.get("era5_precip", pd.Series(np.nan, index=R.index)).fillna(0.0).to_numpy(float)
    if scored == "realised":
        wind_p, temp_p, prec_p = wind_r, temp_r, prec_r
    else:
        fw = R.get(f"{scored}_wind", pd.Series(np.nan, index=R.index))
        ft = R.get(f"{scored}_temp", pd.Series(np.nan, index=R.index))
        fp = R.get(f"{scored}_precip", pd.Series(np.nan, index=R.index))
        if mode == "close":                  # the game-day reading is known at the close; the forecast fills gaps
            wind_p = pd.to_numeric(R["wind"], errors="coerce").fillna(fw).fillna(5.0).to_numpy(float)
            temp_p = pd.to_numeric(R["temp"], errors="coerce").fillna(ft).fillna(60.0).to_numpy(float)
        else:
            wind_p = fw.fillna(5.0).to_numpy(float)
            temp_p = ft.fillna(60.0).to_numpy(float)
        prec_p = fp.fillna(0.0).to_numpy(float)
    R["t_wind"] = np.maximum(wind_r - 8.0, 0.0) * out
    R["t_cold"] = np.maximum(45.0 - temp_r, 0.0) * out
    R["t_wind__pred"] = np.maximum(wind_p - 8.0, 0.0) * out
    R["t_cold__pred"] = np.maximum(45.0 - temp_p, 0.0) * out
    if rain == "t_rain":
        R["t_rain"] = np.minimum(prec_r, 10.0) * out
        R["t_rain__pred"] = np.minimum(prec_p, 10.0) * out
    elif rain == "t_wet":
        R["t_wet"] = (prec_r >= 1.0) * out
        R["t_wet__pred"] = (prec_p >= 1.0) * out
    return R


_READ = None


def load_readings() -> pd.DataFrame:
    """game_id -> nflverse game-day wind / temp (the close rows' reading; realised weather for training)."""
    global _READ
    if _READ is None:
        r = pd.read_parquet(CACHE / "wf_base.parquet", columns=["game_id", "mode", "wind", "temp"])
        _READ = r[r["mode"] == "close"].drop_duplicates("game_id").set_index("game_id")[["wind", "temp"]]
    return _READ


# ── officials ───────────────────────────────────────────────────────────────

def penalties(seasons) -> pd.DataFrame:
    """game_id -> plays with a penalty flag (both teams; nflverse play-by-play)."""
    path = CACHE / "penalties.parquet"
    if path.exists():
        P = pd.read_parquet(path)
        if set(seasons) <= set(P["season"]):
            return P
    out = []
    for s in seasons:
        d = D.load_pbp(s, ["game_id", "penalty"])
        if d is None or d.empty:
            continue
        g = d.groupby("game_id")["penalty"].sum().rename("pen").reset_index()
        g["season"] = s
        out.append(g)
    P = pd.concat(out, ignore_index=True)
    P.to_parquet(path, index=False)
    return P


def referee(R: pd.DataFrame, k: float, hl_seasons: float = 3.0) -> pd.DataFrame:
    """game_id -> t_ref, t_refpen, ref_n (summed weight). Built from the close rows of R (one per game): referee from the
    nflverse schedules, residual = total - nflverse closing total, flags = penalties - the mean of the previous 256 games'
    penalties. Only games dated before the row's week enter."""
    sch = pd.read_parquet(D.schedules_path(), columns=["game_id", "referee"])
    C = R[R["mode"] == "close"].drop_duplicates("game_id")[["game_id", "season", "week", "date", "total", "total_line",
                                                            "played"]].copy()
    C = C.merge(sch, on="game_id", how="left")
    P = penalties(sorted(C["season"].unique()))
    C = C.merge(P[["game_id", "pen"]], on="game_id", how="left")
    C["date"] = pd.to_datetime(C["date"])
    C = C.sort_values(["date", "game_id"]).reset_index(drop=True)
    C["first"] = _wk_first(C)
    C["res"] = np.where(C["played"].astype(bool), C["total"] - C["total_line"], np.nan)
    lg = C["pen"].where(C["played"].astype(bool)).shift(1).rolling(256, min_periods=50).mean()
    C["flag"] = C["pen"] - lg
    out_ref = np.zeros(len(C))
    out_pen = np.zeros(len(C))
    out_n = np.zeros(len(C))
    hist: dict[str, list] = {}
    days = C["date"].to_numpy()
    for first, idx in C.groupby("first", sort=True).groups.items():
        g = C.loc[idx]
        for i, r in zip(idx, g.itertuples(index=False)):
            h = hist.get(r.referee)
            if not isinstance(r.referee, str) or not h:
                continue
            hd, hr, hp = (np.array(x) for x in zip(*h))
            keep = hd < np.datetime64(first)
            if not keep.any():
                continue
            age = (np.datetime64(first) - hd[keep]).astype("timedelta64[D]").astype(float) / 365.25
            w = 0.5 ** (age / hl_seasons)
            a, b = hr[keep], hp[keep]
            ma, mb = np.isfinite(a), np.isfinite(b)
            out_ref[i] = float((w[ma] * a[ma]).sum() / (w[ma].sum() + k))
            out_pen[i] = float((w[mb] * b[mb]).sum() / (w[mb].sum() + k))
            out_n[i] = float(w.sum())
        # add this week's played games to the history only after the week (games of the week never see each other)
        for i in idx:
            r = C.loc[i]
            if isinstance(r["referee"], str) and bool(r["played"]):
                hist.setdefault(r["referee"], []).append((np.datetime64(r["date"]), r["res"], r["flag"]))
    del days
    return pd.DataFrame({"game_id": C["game_id"], "t_ref": out_ref, "t_refpen": out_pen, "ref_n": out_n,
                         "referee": C["referee"], "pen": C["pen"], "flag": C["flag"]})


# ── QB composite (CPOE) ─────────────────────────────────────────────────────

def qb_cpoe_book(seasons, hl: float = 400.0) -> pd.DataFrame:
    """Per QB and game: the exponentially weighted CPOE state after the game (S, N over attempts, half-life `hl`
    attempts, carried across seasons). Built from nflverse play-by-play `cpoe` (pass attempts with air yards)."""
    path = CACHE / f"qb_cpoe_hl{int(hl)}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    parts = []
    for s in seasons:
        d = D.load_pbp(s, ["game_id", "game_date", "passer_player_id", "cpoe"])
        if d is None or d.empty:
            continue
        d = d[d["cpoe"].notna() & d["passer_player_id"].notna()]
        parts.append(d)
    A = pd.concat(parts, ignore_index=True)
    A["game_date"] = pd.to_datetime(A["game_date"])
    A = A.sort_values(["passer_player_id", "game_date", "game_id"])
    a = 0.5 ** (1.0 / hl)
    rows = []
    for q, g in A.groupby("passer_player_id", sort=False):
        S = N = 0.0
        for (gid, gd), gg in g.groupby(["game_id", "game_date"], sort=False):
            x = gg["cpoe"].to_numpy(float)
            n = len(x)
            # attempts in a game: decay within the game as attempts accumulate
            wts = a ** np.arange(n - 1, -1, -1)
            S = S * a ** n + float((wts * x).sum())
            N = N * a ** n + float(wts.sum())
            rows.append((q, gid, gd, S, N))
    B = pd.DataFrame(rows, columns=["qb", "game_id", "date", "S", "N"])
    B.to_parquet(path, index=False)
    return B


def qb_cpoe(R: pd.DataFrame, B: pd.DataFrame, k: float = 300.0) -> pd.DataFrame:
    """R with f_qbx = shrunk CPOE of qb_h minus qb_a, each as of the row's week (games before its first date)."""
    R = R.copy()
    first = _wk_first(R)
    B = B.sort_values("date")
    vals = {}
    for side in ("h", "a"):
        q = R[f"qb_{side}"].astype(object).where(R[f"qb_{side}"].notna(), None)
        key = pd.DataFrame({"qb": q.astype(str), "first": first.to_numpy(), "_i": np.arange(len(R))}).sort_values("first")
        key["first"] = pd.to_datetime(key["first"]) - pd.Timedelta(seconds=1)
        m = pd.merge_asof(key, B.rename(columns={"date": "first"})[["qb", "first", "S", "N"]].sort_values("first"),
                          on="first", by="qb", allow_exact_matches=False, direction="backward")
        v = (m["S"] / (m["N"] + k)).fillna(0.0).to_numpy(float)
        out = np.zeros(len(R))
        out[m["_i"].to_numpy(int)] = v
        vals[side] = out
    R["qbx_h"], R["qbx_a"] = vals["h"], vals["a"]
    R["f_qbx"] = R["qbx_h"] - R["qbx_a"]
    return R


# ── Kalman market ratings ───────────────────────────────────────────────────

def kalman(G: pd.DataFrame, prm: dict, qadj: pd.Series | None = None) -> pd.DataFrame:
    """For every game in G (one row per game: game_id, season, week, date, home, away, neutral, line (home favoured
    by, close), total_line, margin, total, played): kf_line / kf_total (state before the game's week) and
    kf_line_b / kf_total_b (before the previous week). prm: q, rho, q0, sl (line noise sd), res (use results),
    qt, rhot, q0t, st (totals)."""
    G = G.sort_values(["season", "week", "date", "game_id"]).reset_index(drop=True)
    G["fr_h"] = G["home"].map(D.franchise)
    G["fr_a"] = G["away"].map(D.franchise)
    teams = sorted(set(G["fr_h"]) | set(G["fr_a"]))
    ti = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    qa = qadj.reindex(G["game_id"]).to_numpy(float) if qadj is not None else np.zeros(len(G))
    qa = np.where(np.isfinite(qa), qa, 0.0)
    # spread state: [hfa, r_1..r_T]; totals state: [c, t_1..t_T]
    x = np.zeros(T + 1)
    x[0] = 2.5
    P = np.eye(T + 1) * 16.0
    P[0, 0] = 1.0
    xt = np.zeros(T + 1)
    xt[0] = 43.0
    Pt = np.eye(T + 1) * 9.0
    Pt[0, 0] = 9.0
    out = {k: np.full(len(G), np.nan) for k in ("kf_line", "kf_total", "kf_line_b", "kf_total_b")}
    snaps: list[tuple] = []
    last_season = None
    sm = prm.get("sm", 13.5)
    stm = prm.get("stm", 13.5)
    for (s, w), idx in G.groupby(["season", "week"], sort=False).groups.items():
        if last_season is not None and s != last_season:
            x[1:] *= prm["rho"]
            P[1:, 1:] = prm["rho"] ** 2 * P[1:, 1:] + np.eye(T) * prm["q0"]
            P[1:, 0] *= prm["rho"]
            P[0, 1:] *= prm["rho"]
            xt[1:] *= prm["rhot"]
            Pt[1:, 1:] = prm["rhot"] ** 2 * Pt[1:, 1:] + np.eye(T) * prm["q0t"]
            Pt[1:, 0] *= prm["rhot"]
            Pt[0, 1:] *= prm["rhot"]
        elif last_season is not None:
            P[1:, 1:] += np.eye(T) * prm["q"]
            P[0, 0] += 0.002
            Pt[1:, 1:] += np.eye(T) * prm["qt"]
            Pt[0, 0] += 0.05
        last_season = s
        g = G.loc[idx]
        hi = g["fr_h"].map(ti).to_numpy(int)
        ai = g["fr_a"].map(ti).to_numpy(int)
        hind = (~g["neutral"].astype(bool)).to_numpy(float)
        cur = (x.copy(), xt.copy())
        prev = snaps[-1] if snaps else cur
        snaps.append(cur)
        for j, i in enumerate(idx):
            out["kf_line"][i] = cur[0][0] * hind[j] + cur[0][1 + hi[j]] - cur[0][1 + ai[j]]
            out["kf_total"][i] = cur[1][0] + cur[1][1 + hi[j]] + cur[1][1 + ai[j]]
            out["kf_line_b"][i] = prev[0][0] * hind[j] + prev[0][1 + hi[j]] - prev[0][1 + ai[j]]
            out["kf_total_b"][i] = prev[1][0] + prev[1][1 + hi[j]] + prev[1][1 + ai[j]]
        # update with this week's played games (observations become known after the week)
        for j, i in enumerate(idx):
            r = G.loc[i]
            if not bool(r["played"]):
                continue
            h = np.zeros(T + 1)
            h[0] = hind[j]
            h[1 + hi[j]] += 1.0
            h[1 + ai[j]] -= 1.0
            obs = []
            if np.isfinite(r["line"]):
                obs.append((float(r["line"]) - qa[i], prm["sl"] ** 2))
            if prm.get("res") and np.isfinite(r["margin"]):
                obs.append((float(r["margin"]) - qa[i], sm ** 2))
            for y, rv in obs:
                Ph = P @ h
                sk = float(h @ Ph + rv)
                K = Ph / sk
                x = x + K * (y - float(h @ x))
                P = P - np.outer(K, Ph)
            ht = np.zeros(T + 1)
            ht[0] = 1.0
            ht[1 + hi[j]] += 1.0
            ht[1 + ai[j]] += 1.0
            obs = []
            if np.isfinite(r["total_line"]):
                obs.append((float(r["total_line"]), prm["st"] ** 2))
            if prm.get("res") and np.isfinite(r["total"]):
                obs.append((float(r["total"]), stm ** 2))
            for y, rv in obs:
                Ph = Pt @ ht
                sk = float(ht @ Ph + rv)
                K = Ph / sk
                xt = xt + K * (y - float(ht @ xt))
                Pt = Pt - np.outer(K, Ph)
    return pd.DataFrame({"game_id": G["game_id"], **out})


# ── late stakes ─────────────────────────────────────────────────────────────

def late_stakes(R: pd.DataFrame) -> pd.DataFrame:
    """f_clinch17, f_elim17, f_stake17, t_nostake17: the stakes features times 1[REG week >= 17]."""
    R = R.copy()
    late = ((R["week"] >= 17) & (R["gtype"].astype(str) == "REG")).to_numpy(float)
    for c in ("f_clinch", "f_elim", "f_stake", "t_nostake"):
        R[c + "17"] = R[c].to_numpy(float) * late
    return R
