"""
Award probabilities: Hart, Vezina, Norris, Calder, Selke (conditional logit on the verified winners) and the Art Ross
and Rocket Richard trophies (simulation of the rest of the season), compared with the markets.

Player seasons (`player_seasons(season)`; columns player, name, team, pos, gp, g, a, pts, pm, toi_pg, rookie, age,
gp_g, xga, ga, gsax, sv, team_pct, team_gp, value, value_def). Sources, first that answers:
    builder A's stats REST files under <raw>/stats/<season>/ (skater and goalie summary reports, NHL field names);
    else counted from the derived events (goals and assists from GOAL rows, games from on-ice slots, goalies' xG
    faced and goals allowed on unblocked attempts, empty-net excluded);
then builder B's value (`value.for_season`: goals above replacement, and the defensive RAPM term when present) and
GSAx (`goalies.for_season`) are joined when B publishes them. Names / positions / birth dates from the store.
Rookie (Calder rules approximated): no earlier season with more than 25 games in the data, and age <= 26 on
15 September. team_pct = the team's points percentage.

Conditional logit (one per award; seasons 2009-10 to 2025-26 with the winner among the candidates):
    P(i wins | season) = exp(x_i b) / sum_{j in candidates} exp(x_j b),   x = features z-scored within the season,
    b by ridge-penalised maximum likelihood (ridge 0.1). Candidates and features:
    hart    top 30 skaters by points + top 5 goalies by GSAx: pts, g, team_pct, value, goalie x GSAx z-score
    vezina  goalies with >= 40 % of the team's games, top 20 by GSAx: gsax, gp_g, team_pct, sv
    norris  top 25 defencemen by points: pts, value, toi_pg, pm
    calder  top 25 rookie skaters by points + top 5 rookie goalies by GSAx: pts, g, defence, gsax
    selke   top 50 forwards by points with >= 40 % of games: value_def, pm, pts, centre
In season, counting features are projected to the end of the season (current + per-game rate x games left) and
the utilities are multiplied by (0.5 + 0.5 x share of the season played), flattening early-season odds.
Art Ross / Rocket Richard: the top 40 by projected total; each player's remaining points (goals) ~ Poisson(rate x
games left x 0.93 availability), rate shrunk toward last season's with 20 games' weight (0.55 points / 0.22 goals
a game when last season is not on disk); 20,000 draws; Ross ties go to more goals, Richard ties are shared.
"""
from __future__ import annotations

import logging
import math
import unicodedata
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import award_winners as AW

logger = logging.getLogger(__name__)

VERSION = 1
RIDGE = 0.1
LOGIT_AWARDS = ("hart", "vezina", "norris", "calder", "selke")
SIM_AWARDS = ("ross", "richard")
FEATURES = {
    "hart": ["pts", "g", "team_pct", "value", "g_gsax"],
    "vezina": ["gsax", "gp_g", "team_pct", "sv"],
    "norris": ["pts", "value", "toi_pg", "pm"],
    "calder": ["pts", "g", "is_d", "gsax"],
    "selke": ["value_def", "pm", "pts", "is_c"],
}
PS_COLS = ["player", "name", "team", "pos", "gp", "g", "a", "pts", "pm", "toi_pg", "rookie", "age", "gp_g", "xga", "ga",
           "gsax", "sv", "team_pct", "team_gp", "value", "value_def"]


def fold(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("-", " ").replace("'", "")
    s = " ".join(w for w in s.split() if not (w.startswith("(") and w.endswith(")")))
    return " ".join(s.split())


# ── player seasons ───────────────────────────────────────────────────────────

def _store_players(st: dict) -> dict[str, dict]:
    p = (st or {}).get("players") or {}
    if isinstance(p, list):
        p = {str(v.get("id") or v.get("player_id")): v for v in p if isinstance(v, dict)}
    out = {}
    for k, v in p.items():
        v = v or {}
        nm = v.get("name") or " ".join(x for x in (v.get("first"), v.get("last")) if x)
        out[str(k)] = {"name": nm, "pos": str(v.get("pos") or v.get("position") or "")[:1].upper(), "dob": v.get("dob")}
    return out


def _from_stats_files(season: int) -> pd.DataFrame | None:
    base = D.raw_root() / "stats" / str(int(season))
    if not base.exists():
        return None
    sk = gk = None
    for f in sorted(base.iterdir()):
        n = f.name.lower()
        if not n.endswith((".json", ".json.gz")):
            continue
        try:
            from oddsmarkets.nhl.analytics import read_json
            obj = read_json(f)
        except Exception:  # noqa: BLE001
            obj = D.read_json(f)
        rows = obj.get("data") if isinstance(obj, dict) else obj
        if not isinstance(rows, list) or not rows:
            continue
        regular = "_2." in n or not any(f"_{k}." in n for k in (1, 3, 4))      # gameTypeId 2 = regular season
        if not regular:
            continue
        if "skater" in n and "summary" in n:
            sk = pd.DataFrame(rows)
        elif "goalie" in n and "summary" in n:
            gk = pd.DataFrame(rows)
    if sk is None:
        return None
    out = pd.DataFrame({"player": sk["playerId"].astype(str), "name": sk.get("skaterFullName"),
                        "team": sk.get("teamAbbrevs", pd.Series("", index=sk.index)).astype(str).str.split(",").str[-1].str.strip(),
                        "pos": sk.get("positionCode", pd.Series("", index=sk.index)).astype(str).str[:1],
                        "gp": sk.get("gamesPlayed"), "g": sk.get("goals"), "a": sk.get("assists"), "pts": sk.get("points"),
                        "pm": sk.get("plusMinus"), "toi_pg": pd.to_numeric(sk.get("timeOnIcePerGame"), errors="coerce") / 60.0})
    if gk is not None and len(gk):
        go = pd.DataFrame({"player": gk["playerId"].astype(str), "name": gk.get("goalieFullName"),
                           "team": gk.get("teamAbbrevs", pd.Series("", index=gk.index)).astype(str).str.split(",").str[-1].str.strip(),
                           "pos": "G", "gp_g": gk.get("gamesPlayed"), "ga": pd.to_numeric(gk.get("goalsAgainst"), errors="coerce"),
                           "sv": gk.get("savePct"), "shots": pd.to_numeric(gk.get("shotsAgainst"), errors="coerce")})
        # goals saved above an average goalie (league save percentage) stands in for GSAx until builder B's is joined
        lg_sv = 1 - go["ga"].sum() / max(go["shots"].sum(), 1.0)
        go["gsax"] = go["shots"] * (1 - lg_sv) - go["ga"]
        out = pd.concat([out, go], ignore_index=True)
    return out


def _from_events(season: int, st: dict) -> pd.DataFrame | None:
    path = D.raw_root() / "derived" / str(int(season)) / "events.parquet"
    if not path.exists():
        return None
    try:
        g = D.games_from_store(st, season)
        games = {r["game_id"]: {"home": r["home"], "away": r["away"]} for r in g[["game_id", "home", "away"]].to_dict("records")}
        ev = D._events(season, games)
    except Exception as exc:  # noqa: BLE001
        logger.info("awards: events unavailable (%s)", exc)
        return None
    if ev is None or ev.empty:
        return None
    reg = ev["game_id"].astype(str).str[4:6] == "02"
    ev = ev[reg]
    goals = ev[ev["type"] == "GOAL"]
    gcount = goals["p1"].dropna().astype("int64").astype(str).value_counts()
    acount = pd.concat([goals["a1"], goals["a2"]]).dropna().astype("int64").astype(str).value_counts()
    slots = [c for c in ev.columns if c[:1] in ("h", "v") and c[1:].isdigit()]
    on = ev[["game_id", "is_home", "home_team", "away_team"] + slots]
    rows = []
    for c in slots:
        side_home = c.startswith("h")
        x = on[["game_id", c, "home_team" if side_home else "away_team"]].dropna()
        x.columns = ["game_id", "player", "team"]
        rows.append(x)
    gpdf = pd.concat(rows).drop_duplicates(["game_id", "player"]) if rows else pd.DataFrame(columns=["game_id", "player", "team"])
    gpdf["player"] = gpdf["player"].astype("int64").astype(str)
    gp = gpdf.groupby("player").agg(gp=("game_id", "nunique"), team=("team", "last"))
    sk = gp.copy()
    sk["g"] = gcount.reindex(sk.index).fillna(0)
    sk["a"] = acount.reindex(sk.index).fillna(0)
    sk["pts"] = sk["g"] + sk["a"]
    sk = sk.reset_index()
    # goalies: unblocked attempts faced
    fen = ev[ev["type"].isin(["GOAL", "SHOT", "MISS"]) & (ev["st"] != "EN") & ev["goalie"].notna()]
    gk = fen.groupby(fen["goalie"].astype("int64").astype(str)).agg(xga=("xg", "sum"), ga=("type", lambda s: (s == "GOAL").sum()),
                                                                     gp_g=("game_id", "nunique"), shots=("type", lambda s: s.isin(["GOAL", "SHOT"]).sum()))
    conv = float(gk["ga"].sum() / max(gk["xga"].sum(), 1e-9))
    gk["gsax"] = gk["xga"] * conv - gk["ga"]
    gk["sv"] = 1 - gk["ga"] / gk["shots"].clip(lower=1)
    tm = fen.assign(goalie=fen["goalie"].astype("int64").astype(str), dteam=np.where(fen["is_home"] == 1, fen["away_team"], fen["home_team"]))
    gk["team"] = tm.groupby("goalie")["dteam"].agg(lambda s: s.iloc[-1]).reindex(gk.index)
    gk = gk.reset_index().rename(columns={"goalie": "player"})
    gk["pos"] = "G"
    sk = sk[~sk["player"].isin(set(gk["player"]))]
    return pd.concat([sk, gk], ignore_index=True)


_EARLIER: dict = {}


def earlier_gp(season: int) -> tuple[dict[str, int], bool]:
    """({player: most games in any earlier season with stats files on disk}, whether the previous season is there)."""
    if season in _EARLIER:
        return _EARLIER[season]
    out: dict[str, int] = {}
    have_prev = False
    for s in sorted(D.seasons_on_disk()):
        if s >= season:
            continue
        df = _from_stats_files(s)
        if df is None or df.empty:
            continue
        have_prev = have_prev or s == D.prev_season(season)
        gp = pd.to_numeric(df["gp"], errors="coerce").fillna(pd.to_numeric(df.get("gp_g"), errors="coerce")).fillna(0)
        for pid, n in zip(df["player"].astype(str), gp):
            out[pid] = max(out.get(pid, 0), int(n))
    _EARLIER[season] = (out, have_prev)
    return out, have_prev


def player_seasons(season: int, store: dict | None = None, prev_gp: dict | None = None) -> pd.DataFrame:
    st = store if store is not None else D.load_store(season)
    df = _from_stats_files(season)
    if df is None:
        df = _from_events(season, st)
    if df is None or df.empty:
        return pd.DataFrame(columns=PS_COLS)
    sp = _store_players(st)
    df["name"] = [n if isinstance(n, str) and n else sp.get(p, {}).get("name") for p, n in zip(df["player"], df.get("name", [None] * len(df)))]
    df["pos"] = [sp.get(p, {}).get("pos") or (x if isinstance(x, str) else "") for p, x in zip(df["player"], df.get("pos", [""] * len(df)))]
    y = D.start_year(season)
    ages = []
    for p in df["player"]:
        dob = sp.get(p, {}).get("dob")
        try:
            b = date.fromisoformat(str(dob)[:10])
            ref = date(y, 9, 15)
            ages.append(ref.year - b.year - ((ref.month, ref.day) < (b.month, b.day)))
        except (TypeError, ValueError):
            ages.append(np.nan)
    df["age"] = ages
    pg, have_prev = (prev_gp, True) if prev_gp is not None else earlier_gp(season)
    # without the previous season on disk the games-played test is incomplete: also require age <= 23
    cap = 26 if have_prev else 23
    df["rookie"] = [(pg.get(p, 0) <= 25) and (not (a > cap)) for p, a in zip(df["player"], df["age"])]
    # team points percentage
    g = D.games_from_store(st, season)
    g = g[(g["gtype"] == "REG") & g["played"]] if len(g) else g
    pct, tgp = {}, {}
    for t in set(g["home"]) | set(g["away"]) if len(g) else []:
        h = g[g["home"] == t]
        a = g[g["away"] == t]
        w = (h["hs"] > h["as_"]).sum() + (a["as_"] > a["hs"]).sum()
        otl = (h["ot"] & (h["hs"] < h["as_"])).sum() + (a["ot"] & (a["as_"] < a["hs"])).sum()
        n = len(h) + len(a)
        pct[t] = (2 * w + otl) / (2 * n) if n else 0.5
        tgp[t] = n
    df["team_pct"] = df["team"].map(pct).fillna(0.5)
    df["team_gp"] = df["team"].map(tgp).fillna(0)
    for c in PS_COLS:
        if c not in df:
            df[c] = np.nan
    bv = _b_values(season)
    if bv is not None:
        df["value"] = df["player"].map(bv.get("value", {})).astype(float)
        df["value_def"] = df["player"].map(bv.get("value_def", {})).astype(float)
    bg = _b_gsax(season)
    if bg:
        m = df["pos"] == "G"
        got = df.loc[m, "player"].map(bg)
        df.loc[m, "gsax"] = got.where(got.notna(), df.loc[m, "gsax"])
    return df[PS_COLS]


def _b_gsax(season: int) -> dict | None:
    """{goalie: GSAx} from builder B's goalies module."""
    try:
        from oddsmarkets.nhl.models import team_strength as TS
        r = TS.b_goalies(season)
    except Exception:  # noqa: BLE001
        return None
    return {k: v["gsax"] for k, v in (r or {}).items()} or None


def _b_values(season: int) -> dict | None:
    try:
        from oddsmarkets.nhl.models import value as BV
        r = BV.for_season(season)
        from oddsmarkets.nhl.analytics.context import frame_of
        df = frame_of(r.get("skaters") if isinstance(r, dict) and "skaters" in r else r)
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    idc = next((c for c in ("player", "player_id", "pid", "id") if c in df), None)
    vc = next((c for c in ("value", "gar", "rink_value", "goals_above_replacement") if c in df), None)
    dc = next((c for c in ("value_def", "def", "rapm_def", "defence") if c in df), None)
    if idc is None or vc is None:
        return None
    ids = df[idc].astype(str)
    return {"value": dict(zip(ids, df[vc].astype(float))), "value_def": dict(zip(ids, df[dc].astype(float))) if dc else {}}


# ── candidates and features ──────────────────────────────────────────────────

def project(ps: pd.DataFrame, games_left: dict | None = None, season_games: int = 82) -> pd.DataFrame:
    """Counting stats projected to season end (per-game rate x team games left)."""
    df = ps.copy()
    if not games_left:
        return df
    left = df["team"].map(games_left).fillna(0).to_numpy(float)
    for c in ("g", "a", "pts"):
        rate = df[c].fillna(0) / df["gp"].clip(lower=1)
        df[c] = df[c].fillna(0) + rate * left * 0.93
    for c in ("gsax", "xga", "ga"):
        rate = df[c].fillna(0) / df["gp_g"].clip(lower=1)
        df[c] = df[c].fillna(0) + rate * left * 0.6
    return df


def candidates(award: str, ps: pd.DataFrame) -> pd.DataFrame:
    df = ps.copy()
    for c in ("pts", "g", "gsax", "gp", "gp_g", "team_gp"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    sk = df[df["pos"] != "G"]
    gk = df[df["pos"] == "G"]
    tg = df["team_gp"].replace(0, np.nan)
    if award == "hart":
        c = pd.concat([sk.nlargest(30, "pts"), gk.nlargest(5, "gsax")])
    elif award == "vezina":
        q = gk[gk["gp_g"] >= 0.4 * gk["team_gp"].fillna(82).clip(lower=10)]
        c = q.nlargest(20, "gsax")
    elif award == "norris":
        c = sk[sk["pos"] == "D"].nlargest(25, "pts")
    elif award == "calder":
        r = df[df["rookie"].astype(bool)]
        c = pd.concat([r[r["pos"] != "G"].nlargest(25, "pts"), r[r["pos"] == "G"].nlargest(5, "gsax")])
    elif award == "selke":
        f = sk[sk["pos"].isin(["C", "L", "R", "F"]) & (sk["gp"] >= 0.4 * tg.reindex(sk.index).fillna(82))]
        c = f.nlargest(50, "pts")
    else:
        c = sk.nlargest(40, "pts")
    c = c.copy()
    c["is_d"] = (c["pos"] == "D").astype(float)
    c["is_c"] = (c["pos"] == "C").astype(float)
    c["g_gsax"] = np.where(c["pos"] == "G", c["gsax"].fillna(0), 0.0)
    return c.reset_index(drop=True)


def _z(X: np.ndarray) -> np.ndarray:
    X = np.where(np.isfinite(X), X, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # "mean of empty slice" for an all-missing feature
        mu = np.nanmean(X, 0) if len(X) else np.zeros(X.shape[1])
    # a feature missing for every candidate (e.g. B's value not on disk for a season) contributes nothing; left as
    # NaN it made the whole likelihood NaN and the fit stopped at its zero start (Oct 2026 audit: Hart, Norris and
    # Selke committed with all-zero coefficients, so every candidate got the same probability)
    mu = np.where(np.isfinite(mu), mu, 0.0)
    X = np.where(np.isnan(X), mu, X)
    sd = X.std(0)
    return (X - X.mean(0)) / np.where(sd > 1e-9, sd, 1.0)


def winner_index(award: str, season: int, cand: pd.DataFrame) -> int | None:
    rec = AW.WINNERS.get(award, {}).get(int(season))
    if not rec or cand.empty:
        return None
    names = {fold(rec[0][0])} | {fold(a) for a in AW.ALIASES.get(rec[0][0], [])}
    hit = [i for i, n in enumerate(cand["name"].astype(str)) if fold(n) in names]
    return hit[0] if hit else None


def fit_clogit(groups: list[tuple[np.ndarray, int]], ridge: float = RIDGE) -> np.ndarray:
    from scipy.optimize import minimize
    k = groups[0][0].shape[1]

    def f(b):
        ll, g = 0.0, np.zeros(k)
        for X, y in groups:
            u = X @ b
            u = u - u.max()
            e = np.exp(u)
            p = e / e.sum()
            ll += u[y] - math.log(e.sum())
            g += X[y] - p @ X
        return -ll + ridge * b @ b, -g + 2 * ridge * b
    return minimize(f, np.zeros(k), jac=True, method="L-BFGS-B").x


def fit(seasons: list[int] | None = None, ps_of=None) -> dict:
    """Coefficients per logit award on the verified winners; in-sample log-likelihood and top-1 hits."""
    seasons = seasons or sorted(AW.WINNERS["hart"])
    ps_of = ps_of or player_seasons
    tables = {}
    for s in seasons:
        try:
            tables[s] = ps_of(s)
        except Exception as exc:  # noqa: BLE001
            logger.info("awards.fit: %s unavailable (%s)", s, exc)
    out: dict[str, Any] = {"version": VERSION, "awards": {}}
    for aw in LOGIT_AWARDS:
        groups, miss = [], []
        for s, ps in tables.items():
            if ps is None or ps.empty:
                miss.append(s)
                continue
            c = candidates(aw, ps)
            y = winner_index(aw, s, c)
            if y is None:
                miss.append(s)
                continue
            groups.append((_z(c[FEATURES[aw]].to_numpy(float)), y))
        if len(groups) < 6:
            out["awards"][aw] = {"ok": False, "missing": miss, "n_seasons": len(groups)}
            continue
        b = fit_clogit(groups)
        ll, top1 = 0.0, 0
        for X, y in groups:
            u = X @ b
            p = np.exp(u - u.max())
            p /= p.sum()
            ll += math.log(max(p[y], 1e-12))
            top1 += int(np.argmax(p) == y)
        out["awards"][aw] = {"ok": usable_fit({"ok": True, "beta": b.tolist(), "loglik": ll}), "features": FEATURES[aw],
                             "beta": b.tolist(), "n_seasons": len(groups), "missing": miss, "loglik": ll, "top1": top1}
    return out


def save(fitd: dict, committed: bool = False) -> None:
    D.write_json(D.c_cache() / "awards_fit.json", fitd)
    if committed:
        D.write_json(D.FITTED / "awards_fit.json", fitd)


def usable_fit(f: dict | None) -> bool:
    """A fitted award is usable when it says ok, its coefficients are finite and not all zero (the optimiser's start)
    and its log-likelihood is finite; otherwise every candidate would get the same probability."""
    if not f or not f.get("ok"):
        return False
    b = np.asarray(f.get("beta") or [], float)
    ll = f.get("loglik")
    return bool(len(b) and np.isfinite(b).all() and np.abs(b).max() > 1e-9 and ll is not None and np.isfinite(float(ll)))


def load_fit() -> dict | None:
    return D.read_json(D.c_cache() / "awards_fit.json") or D.read_json(D.FITTED / "awards_fit.json")


# ── prediction ───────────────────────────────────────────────────────────────

def logit_probs(award: str, ps: pd.DataFrame, beta, played_share: float = 1.0) -> dict[str, float]:
    c = candidates(award, ps)
    if c.empty:
        return {}
    X = _z(c[FEATURES[award]].to_numpy(float))
    u = (X @ np.asarray(beta, float)) * (0.5 + 0.5 * min(max(played_share, 0.0), 1.0))
    p = np.exp(u - u.max())
    p /= p.sum()
    return {str(pid): float(v) for pid, v in zip(c["player"], p)}


def leader_sim(ps: pd.DataFrame, games_left: dict, col: str = "pts", prev_rate: dict | None = None, n: int = 20000,
               seed: int = 0, tie_goals: bool = True) -> dict[str, float]:
    """P(finishing first in `col`) for the top 40 by projection; Ross ties by goals, Richard ties shared."""
    df = ps[ps["pos"] != "G"].copy()
    if df.empty:
        return {}
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["gp"] = pd.to_numeric(df["gp"], errors="coerce").fillna(0)
    left = df["team"].map(games_left or {}).fillna(0).to_numpy(float)
    pr = df["player"].map(prev_rate or {}).astype(float).to_numpy()
    base = np.where(np.isfinite(pr), pr, np.nan)
    # no earlier season on disk: a first-line prior rate (0.55 points / 0.22 goals a game) carries the 20 games' weight
    base = np.where(np.isnan(base), 0.55 if col == "pts" else 0.22, base)
    k = 20.0
    rate = (df[col].to_numpy(float) + k * base) / (df["gp"].to_numpy(float) + k)
    proj = df[col].to_numpy(float) + rate * left * 0.93
    top = np.argsort(-proj)[:40]
    rng = np.random.default_rng(seed)
    lam = rate[top] * left[top] * 0.93
    fin = df[col].to_numpy(float)[top][None, :] + rng.poisson(np.broadcast_to(lam, (n, len(top))))
    if col == "pts" and tie_goals:
        gr = (df["g"].fillna(0).to_numpy(float) / np.maximum(df["gp"].to_numpy(float), 1))[top]
        fin = fin + (df["g"].fillna(0).to_numpy(float)[top] + gr * left[top] * 0.93) / 1000.0
    mx = fin.max(1, keepdims=True)
    lead = fin >= mx - 1e-9
    share = lead / lead.sum(1, keepdims=True)
    p = share.mean(0)
    return {str(pid): float(v) for pid, v in zip(df["player"].to_numpy()[top], p) if v > 0}


def predict(season: int, ps: pd.DataFrame | None = None, fitd: dict | None = None, games_left: dict | None = None,
            prev: pd.DataFrame | None = None, n: int = 20000) -> dict:
    """{award: {"ok", "probs": {player: p}, "names": {player: name}, "basis"}}."""
    ps = ps if ps is not None else player_seasons(season)
    if ps is None or ps.empty:
        return {a: {"ok": False, "reason": "no player-season data"} for a in LOGIT_AWARDS + SIM_AWARDS}
    fitd = fitd or load_fit() or {"awards": {}}
    gl = games_left or {}
    tgp = pd.to_numeric(ps["team_gp"], errors="coerce").fillna(0)
    total = float(np.nanmax(tgp + ps["team"].map(gl).fillna(0))) if len(ps) else 82.0
    played_share = float(np.nanmedian(tgp) / max(total, 1.0)) if len(ps) else 1.0
    proj = project(ps, gl)
    names = dict(zip(ps["player"].astype(str), ps["name"].astype(str)))
    out = {}
    for a in LOGIT_AWARDS:
        f = (fitd.get("awards") or {}).get(a) or {}
        if not f.get("ok"):
            out[a] = {"ok": False, "reason": "award model not fitted"}
            continue
        if not usable_fit(f):
            out[a] = {"ok": False, "reason": "award model fit degenerate (needs a refit)"}
            continue
        pr = logit_probs(a, proj, f["beta"], played_share)
        out[a] = {"ok": bool(pr), "probs": dict(sorted(pr.items(), key=lambda kv: -kv[1])),
                  "names": {k: names.get(k) for k in pr}, "basis": "clogit", "played_share": played_share}
    prev_rate = {}
    if prev is None:
        # last season's rates shrink the Art Ross / Rocket Richard simulation; the build never passed them, so before
        # 20 games both races were missing (Oct 2026 audit). The stats REST summary on disk is enough (no model run).
        try:
            prev = _from_stats_files(D.prev_season(season))
        except Exception:  # noqa: BLE001 - a missing or unreadable file only means no prior
            prev = None
    if prev is not None and len(prev):
        pv = prev[prev["gp"].fillna(0) >= 20]
        prev_rate = {"pts": dict(zip(pv["player"].astype(str), pv["pts"] / pv["gp"])),
                     "g": dict(zip(pv["player"].astype(str), pv["g"] / pv["gp"]))}
    early = float(np.nanmedian(tgp)) < 20 if len(ps) else True
    for a, col in (("ross", "pts"), ("richard", "g")):
        if early and not prev_rate:
            out[a] = {"ok": False, "reason": "fewer than 20 games played and no previous-season rates on disk"}
            continue
        pr = leader_sim(ps, gl, col, prev_rate.get(col), n=n, tie_goals=(a == "ross"))
        out[a] = {"ok": bool(pr), "probs": dict(sorted(pr.items(), key=lambda kv: -kv[1])),
                  "names": {k: names.get(k) for k in pr}, "basis": "simulation"}
    return out


def compare_markets(pred: dict, futures: dict) -> dict:
    """Model v market per award: rows {player, name, model, market, market_mid} matched by folded name."""
    out = {}
    aw = (futures or {}).get("awards") or {}
    for a, res in (pred or {}).items():
        fld = aw.get(a) or {}
        mk = fld.get("probs") or {}
        mid = fld.get("mid") or {}
        names = (res or {}).get("names") or {}
        by_fold = {fold(v): k for k, v in names.items() if v}
        rows, seen = [], set()
        for key in set(mk) | set(mid):
            nm = key.split(":", 1)[1] if key.startswith("name:") else key
            pid = by_fold.get(fold(nm))
            m = (res.get("probs") or {}).get(pid) if pid else None
            rows.append({"player": pid, "name": nm, "model": m, "market": mk.get(key), "market_mid": mid.get(key)})
            if pid:
                seen.add(pid)
        for pid, m in list((res.get("probs") or {}).items())[:15]:
            if pid not in seen:
                rows.append({"player": pid, "name": names.get(pid), "model": m, "market": None, "market_mid": None})
        rows.sort(key=lambda r: -max(r["model"] or 0, r["market"] or 0, r["market_mid"] or 0))
        out[a] = {"available": bool(fld.get("available")), "reason": fld.get("reason"), "rows": rows[:30]}
    return out
