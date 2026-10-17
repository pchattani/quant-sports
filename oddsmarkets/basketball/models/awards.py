"""
Award races: MVP, Rookie of the Year, Defensive Player, Sixth Man / Sixth Player, Most Improved, Clutch.

Model
-----
Each award is a conditional logit over that season's candidate pool c:

    P(i wins | pool) = exp(theta_i) / sum_{j in pool} exp(theta_j),   theta_i = sum_k w_k z_ik

z_ik is feature k of player i standardised within the season's pool (so eras and leagues with
different scoring levels are comparable). This is Plackett-Luce truncated at the winner
(`oddsmarkets.common.ranking`); the feature weights w are fitted on past winners
(`award_winners.py`, hand-entered) by maximising sum_seasons log P(winner) - ridge/2 |w|^2 with
L-BFGS. A season with tied winners counts each with weight 1/k. With no usable history the weights are
DEFAULT_WEIGHTS (hand-set, documented below).

Features (per player-season, `season_table`):
* mvp:    hpm_value (HPM x share of team minutes x games played), ppg, team_win_pct, hpm_t
* roy:    ppg, mpg, hpm_value, team_win_pct              (pool: rookies = first season in the stores)
* dpoy:   hpm_d_value, bpg, spg, dpg (defensive rebounds), team_def (league ORtg - team DRtg)
* 6moy:   ppg, hpm_value, mpg, team_win_pct              (pool: starts < half of games played)
* mip:    d_hpm, d_ppg, d_mpg, ppg                       (pool: played the previous season)
* clutch: clutch_wpa, wpa, team_win_pct                  (pool: has clutch play-by-play)
Pool floor: at least MIN_GAMES_SHARE of the team's games and MIN_MPG minutes a game (to date).

Eligibility: NBA seasons from 2024 (the 2023 CBA) need 65 qualifying games for MVP, DPOY, MIP and
Clutch (RULE_65): a game counts at 20+ minutes, plus at most two games of 15-20 minutes. ROY and
6MOY are left out of the rule here (the author was not certain of their treatment; see the report).

Projection to season end (`race`): N_SIMS simulated finishes. Each player's remaining games played
~ Binomial(team games left, his availability so far); counting stats accumulate at his per-game rates;
HPM drifts by N(0, HPM_DRIFT_SD^2 x share of season left); team wins come from builder B's season
simulation ({tid: {"exp_w","w_p05","w_p95"}}, normal with sd (p95 - p05) / 3.29) or, without it,
Binomial(games left, current win %). Features are recomputed per simulation, ineligible players are
removed, and the winner is drawn with the Gumbel trick (an exact Plackett-Luce first place).
P(win) = share of simulations won.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import award_winners as aw

MODEL_VERSION = "awards-1"

AWARDS = aw.AWARDS
FEATURES = {
    "mvp": ["hpm_value", "ppg", "team_win_pct", "hpm_t"],
    "roy": ["ppg", "mpg", "hpm_value", "team_win_pct"],
    "dpoy": ["hpm_d_value", "bpg", "spg", "dpg", "team_def"],
    "6moy": ["ppg", "hpm_value", "mpg", "team_win_pct"],
    "mip": ["d_hpm", "d_ppg", "d_mpg", "ppg"],
    "clutch": ["clutch_wpa", "wpa", "team_win_pct"],
}
# hand-set fallbacks on pool-standardised features (larger = more weight)
DEFAULT_WEIGHTS = {
    "mvp": [1.6, 0.8, 1.0, 0.4],
    "roy": [1.6, 0.6, 0.6, 0.2],
    "dpoy": [1.2, 0.8, 0.4, 0.4, 0.8],
    "6moy": [1.6, 0.6, 0.4, 0.4],
    "mip": [1.2, 1.2, 0.6, 0.4],
    "clutch": [1.6, 0.4, 0.8],
}
RULE_65 = {"mvp", "dpoy", "mip", "clutch"}
RULE_65_FROM = 2024
RULE_65_GAMES = 65
MIN_GAMES_SHARE = 0.4
MIN_MPG = 12.0
RIDGE = 0.5
N_SIMS = 5000
HPM_DRIFT_SD = 1.5
SEASON_GAMES = {"nba": 82, "wnba": 44}


# ============================================================================ season table

def season_table(games: Any, players: dict | None = None, hpm: dict | None = None, wpa: dict | None = None,
                 prev: pd.DataFrame | None = None, rookies: Iterable[str] | None = None, league: str = "nba",
                 stypes: Iterable[str] = ("reg",)) -> pd.DataFrame:
    """Per-player season-to-date table from GAME boxes (dict / list of games, or a `_io.box_frame`).
    Index player_id; columns: team, games, starts, minutes, mpg, ppg, rpg, apg, spg, bpg, dpg, elig_games,
    elig_rate (share of his games that qualify), team_games, team_wins, team_win_pct, team_left (regular-
    season games his team has left, from status "pre" games), team_def, hpm_t/o/d, hpm_value, hpm_d_value,
    wpa, clutch_wpa, rookie, bench, d_hpm, d_ppg, d_mpg, has_prev, name."""
    if isinstance(games, pd.DataFrame):
        bf, glist = games, None
    else:
        glist = list(games.values()) if isinstance(games, dict) else list(games)
        bf = _io.box_frame(glist, stypes)
    if bf.empty:
        return pd.DataFrame()
    played = bf[bf["sec"] > 0].copy()
    played["min"] = played["sec"] / 60.0
    played["reb"] = played["oreb"] + played["dreb"]
    g = played.groupby("player_id")
    out = pd.DataFrame({"games": g.size(), "starts": g["starter"].sum(), "minutes": g["min"].sum()})
    for s, name in (("pts", "ppg"), ("reb", "rpg"), ("ast", "apg"), ("stl", "spg"), ("blk", "bpg"), ("dreb", "dpg")):
        out[name] = g[s].sum() / out["games"]
    out["mpg"] = out["minutes"] / out["games"]
    full = g["min"].apply(lambda m: int((m >= 20).sum()))
    part = g["min"].apply(lambda m: int(((m >= 15) & (m < 20)).sum()))
    out["elig_games"] = full + np.minimum(part, 2)
    out["elig_rate"] = out["elig_games"] / out["games"]
    tm = played.groupby(["player_id", "team"])["sec"].sum().reset_index().sort_values("sec").drop_duplicates("player_id", keep="last")
    out["team"] = tm.set_index("player_id")["team"].reindex(out.index)
    tg = bf.drop_duplicates(["game_id", "team"])
    team_games = tg.groupby("team").size()
    team_wins = tg.assign(w=(tg["team_pts"] > tg["opp_pts"]).astype(int)).groupby("team")["w"].sum()
    tt = tg.groupby("team")[["team_pts", "opp_pts", "team_poss"]].sum()
    lg_ortg = 100 * tt["team_pts"].sum() / max(tt["team_poss"].sum(), 1e-9)
    team_drtg = 100 * tt["opp_pts"] / tt["team_poss"].clip(lower=1.0)
    out["team_games"] = out["team"].map(team_games).fillna(0).astype(int)
    out["team_wins"] = out["team"].map(team_wins).fillna(0).astype(int)
    out["team_win_pct"] = out["team_wins"] / out["team_games"].clip(lower=1)
    out["team_def"] = lg_ortg - out["team"].map(team_drtg)
    left = {}
    for gm in glist or []:
        if gm and gm.get("status") == "pre" and gm.get("stype") in set(stypes):
            for t in (gm.get("home"), gm.get("away")):
                left[t] = left.get(t, 0) + 1
    out["team_left"] = out["team"].map(left).fillna(0).astype(int)
    gmin = _io.game_minutes(league)
    h = hpm or {}
    for side in ("t", "o", "d"):
        out[f"hpm_{side}"] = [float((h.get(p) or {}).get(side, 0.0) or 0.0) for p in out.index]
    # impact over the season: HPM x five-man minute share x games (points per 100 "season units")
    out["hpm_value"] = (out["hpm_t"] + 2.0) * out["minutes"] / gmin / 10.0
    out["hpm_d_value"] = (out["hpm_d"] + 1.0) * out["minutes"] / gmin / 10.0
    w = wpa or {}
    out["wpa"] = [float((w.get(p) or {}).get("wpa", 0.0) or 0.0) for p in out.index]
    out["clutch_wpa"] = [float((w.get(p) or {}).get("clutch_wpa", 0.0) or 0.0) for p in out.index]
    out["has_clutch"] = [p in w for p in out.index]
    rk = set(rookies or [])
    out["rookie"] = [p in rk for p in out.index]
    out["bench"] = out["starts"] < out["games"] / 2.0
    if prev is not None and not prev.empty:
        out["has_prev"] = [p in prev.index for p in out.index]
        for a, b in (("d_hpm", "hpm_t"), ("d_ppg", "ppg"), ("d_mpg", "mpg")):
            out[a] = out[b] - prev[b].reindex(out.index)
    else:
        out["has_prev"] = False
        out["d_hpm"] = out["d_ppg"] = out["d_mpg"] = np.nan
    out["name"] = [str(((players or {}).get(p) or {}).get("name") or p) for p in out.index]
    out.index.name = "player_id"
    return out


def pool(table: pd.DataFrame, award: str) -> pd.DataFrame:
    """Candidates for `award` (before the 65-game rule)."""
    if table.empty:
        return table
    t = table[(table["games"] >= MIN_GAMES_SHARE * table["team_games"].clip(lower=1)) & (table["mpg"] >= MIN_MPG)]
    if award == "roy":
        t = t[t["rookie"]]
    elif award == "6moy":
        t = t[t["bench"]]
    elif award == "mip":
        t = t[t["has_prev"] & t["d_hpm"].notna()]
    elif award == "clutch":
        t = t[t["has_clutch"]]
    return t


def _z(X: np.ndarray) -> np.ndarray:
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd[~np.isfinite(sd) | (sd < 1e-9)] = 1.0
    Z = (X - mu) / sd
    return np.nan_to_num(Z, nan=0.0)


# ============================================================================ fit

def fit_award(award: str, seasons: list[tuple[pd.DataFrame, list[str]]], ridge: float = RIDGE) -> dict:
    """Fit conditional-logit weights from past seasons: [(season table, [winner pid, ...]), ...].
    Seasons whose winner is not in the pool are skipped. Returns {"award","features","weights","n_seasons",
    "loglik","fitted": bool, "top1": share of training seasons where the winner had the highest theta}."""
    feats = FEATURES[award]
    data = []
    for table, wins in seasons:
        pl = pool(table, award)
        if pl.empty:
            continue
        idx = [list(pl.index).index(w) for w in wins if w in pl.index]
        if not idx:
            continue
        data.append((_z(pl[feats].to_numpy(float)), idx))
    if len(data) < 3:
        return {"award": award, "features": feats, "weights": list(DEFAULT_WEIGHTS[award]), "n_seasons": len(data),
                "fitted": False}

    def obj(w):
        f, g = 0.0, np.zeros_like(w)
        for Z, idx in data:
            th = Z @ w
            mx = th.max()
            e = np.exp(th - mx)
            p = e / e.sum()
            lse = mx + math.log(e.sum())
            for i in idx:
                f -= (th[i] - lse) / len(idx)
                g -= (Z[i] - p @ Z) / len(idx)
        f += 0.5 * ridge * float(w @ w)
        g += ridge * w
        return f, g

    res = minimize(obj, np.array(DEFAULT_WEIGHTS[award], float), jac=True, method="L-BFGS-B")
    w = res.x
    top1 = float(np.mean([int(np.argmax(Z @ w) in idx) for Z, idx in data]))
    return {"award": award, "features": feats, "weights": [float(v) for v in w], "n_seasons": len(data),
            "loglik": float(-res.fun), "fitted": True, "top1": top1}


# ============================================================================ race

def _eligible(award: str, league: str, season: int | None) -> bool:
    return str(league).lower() == "nba" and award in RULE_65 and season is not None and int(season) >= RULE_65_FROM


def race(award: str, table: pd.DataFrame, model: dict | None = None, team_wins: dict | None = None, n: int = N_SIMS,
         seed: int = 0, league: str = "nba", season: int | None = None, final: bool = False) -> dict:
    """P(win) per candidate, projected to season end: {pid: {"p","p_top3","theta_now","can_qualify"
    (can still reach the 65 games), "p_eligible"}} sorted by p. `final=True` scores the table as it stands (no simulation of remaining games).
    `team_wins`: builder B's {tid: {"exp_w","w_p05","w_p95"}} (season totals)."""
    model = model or {"features": FEATURES[award], "weights": DEFAULT_WEIGHTS[award]}
    feats, w = model["features"], np.asarray(model["weights"], float)
    pl = pool(table, award)
    if pl.empty:
        return {}
    rng = np.random.default_rng(seed)
    N = len(pl)
    rule = _eligible(award, league, season)
    G = pl["games"].to_numpy(float)
    teamG = pl["team_games"].to_numpy(float).clip(min=1)
    left = np.zeros(N) if final else pl["team_left"].to_numpy(float)
    S = 1 if final else n
    avail = np.clip(G / teamG, 0.02, 1.0)
    add = rng.binomial(left.astype(int)[None, :].repeat(S, 0), avail[None, :]) if not final else np.zeros((1, N))
    Gf = G[None, :] + add
    frac_left = left / np.maximum(teamG + left, 1.0)
    cols: dict[str, np.ndarray] = {}
    for c in set(feats) | {"ppg", "mpg", "hpm_t", "hpm_d"}:
        cols[c] = np.repeat(pl[c].to_numpy(float)[None, :], S, axis=0) if c in pl else np.zeros((S, N))
    if not final:
        drift = rng.normal(0, HPM_DRIFT_SD, (S, N)) * np.sqrt(frac_left)[None, :]
        cols["hpm_t"] = cols["hpm_t"] + drift
        cols["hpm_d"] = cols["hpm_d"] + 0.5 * drift
        # team wins
        tw = pl["team_wins"].to_numpy(float)
        tids = pl["team"].to_numpy()
        final_w = np.zeros((S, N))
        for t in np.unique(tids):
            k = tids == t
            j = np.argmax(k)
            gl = left[j]
            tg = teamG[j]
            info = (team_wins or {}).get(t)
            if info and info.get("exp_w") is not None:
                sd = max((float(info.get("w_p95", info["exp_w"])) - float(info.get("w_p05", info["exp_w"]))) / 3.29, 0.5)
                draws = np.clip(rng.normal(float(info["exp_w"]), sd, S), tw[j], tw[j] + gl)
            else:
                draws = tw[j] + rng.binomial(int(gl), min(max(tw[j] / tg, 0.02), 0.98), S)
            final_w[:, k] = draws[:, None]
        cols["team_win_pct"] = final_w / (teamG + left)[None, :]
        mins = pl["minutes"].to_numpy(float)[None, :] + add * pl["mpg"].to_numpy(float)[None, :]
        gmin = _io.game_minutes(league)
        if "hpm_value" in feats:
            cols["hpm_value"] = (cols["hpm_t"] + 2.0) * mins / gmin / 10.0
        if "hpm_d_value" in feats:
            cols["hpm_d_value"] = (cols["hpm_d"] + 1.0) * mins / gmin / 10.0
        if "d_hpm" in feats and "d_hpm" in pl:
            cols["d_hpm"] = pl["d_hpm"].to_numpy(float)[None, :] + (cols["hpm_t"] - pl["hpm_t"].to_numpy(float)[None, :])
    X = np.stack([cols[c] for c in feats], axis=2)                  # S x N x K
    mu = np.nanmean(X, axis=1, keepdims=True)
    sd = np.nanstd(X, axis=1, keepdims=True)
    sd[~np.isfinite(sd) | (sd < 1e-9)] = 1.0
    Z = np.nan_to_num((X - mu) / sd)
    th = Z @ w
    elig = np.ones((S, N), bool)
    if rule:
        e_rate = pl["elig_rate"].to_numpy(float)
        ef = pl["elig_games"].to_numpy(float)[None, :] + np.round(add * e_rate[None, :])
        elig = ef >= RULE_65_GAMES
    th_now = th[0] if final else (_z(pl[feats].to_numpy(float)) @ w)
    if final:
        from oddsmarkets.common.ranking import pl_probabilities
        ids = [pid for i, pid in enumerate(pl.index) if elig[0][i]]
        pr = pl_probabilities({pid: float(th[0][list(pl.index).index(pid)]) for pid in ids}, top_k=(3,), n=n, seed=seed) if ids else {}
        res = {pid: {"p": float((pr.get(pid) or {}).get("p_win", 0.0)), "p_top3": float((pr.get(pid) or {}).get("p_top3", 0.0)),
                     "theta_now": float(th_now[i]), "can_qualify": bool(elig[0][i]), "p_eligible": float(elig[0][i])}
               for i, pid in enumerate(pl.index)}
    else:
        gum = rng.gumbel(size=(S, N))
        score = np.where(elig, th + gum, -np.inf)
        ok = np.isfinite(score).any(axis=1)
        rank = np.argsort(-score, axis=1)
        win = rank[ok, 0]
        p = np.bincount(win, minlength=N) / S
        top3 = np.zeros(N)
        for k in range(min(3, N)):
            col = rank[ok, k]
            fin = np.isfinite(score[ok, :][np.arange(ok.sum()), col])
            top3 += np.bincount(col[fin], minlength=N)
        top3 /= S
        can = (pl["elig_games"].to_numpy(float) + left >= RULE_65_GAMES) if rule else np.ones(N, bool)
        res = {pid: {"p": float(p[i]), "p_top3": float(top3[i]), "theta_now": float(th_now[i]),
                     "can_qualify": bool(can[i]), "p_eligible": float(elig[:, i].mean())} for i, pid in enumerate(pl.index)}
    return dict(sorted(res.items(), key=lambda kv: -kv[1]["p"]))


def races(table: pd.DataFrame, models: dict | None = None, team_wins: dict | None = None, league: str = "nba",
          season: int | None = None, n: int = N_SIMS, seed: int = 0, awards: Iterable[str] | None = None) -> dict:
    """Contract shape {award: {pid: p}} for every award with a non-empty pool."""
    out = {}
    for a in awards or AWARDS:
        if a == "clutch" and str(league).lower() != "nba":
            continue
        r = race(a, table, (models or {}).get(a), team_wins, n=n, seed=seed, league=league, season=season)
        if r:
            out[a] = {pid: v["p"] for pid, v in r.items()}
    return out


# ============================================================================ season loader

def resolve_winners(names: list[str], table: pd.DataFrame) -> list[str]:
    """Map winner names to player ids in a season table by folded name."""
    if table.empty or not names:
        return []
    by = {}
    for pid, nm in zip(table.index, table["name"]):
        by.setdefault(_io.fold_name(nm), pid)
    return [by[_io.fold_name(n)] for n in names if _io.fold_name(n) in by]


def _seasons_on_disk(league: str) -> list[int]:
    root = _io.data_root() / league
    return sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit() and (p / "store.json").exists()) if root.exists() else []


def _table_for(league: str, season: int, through: str | None, use_cache: bool, seen_before: set | None,
               n_before: int, prev: pd.DataFrame | None) -> pd.DataFrame:
    from oddsmarkets.basketball.models import impact, winprob
    store = _io.season_file(league, season, "store.json") or {}
    games = {k: g for k, g in (store.get("games") or {}).items() if not through or str(g.get("date") or "")[:10] <= through
             or g.get("status") == "pre"}
    imp = impact.for_season(league, season, through=through, use_cache=use_cache)
    hp = {p: r for p, r in (imp.get("players") or {}).items() if "t" in r} if imp.get("ok") else {}
    wp = {}
    if (_io.pbp_root() / league / str(season)).exists():
        w = winprob.for_season(league, season, through=through, use_cache=use_cache)
        wp = w.get("players") or {} if w.get("ok") else {}
    players = store.get("players") or {}
    rookies = None
    if seen_before is not None:
        rookies = []
        for pid, info in players.items():
            if pid in seen_before:
                continue
            age = None
            try:
                age = (int(season) - int(str(info.get("dob"))[:4])) if info.get("dob") else None
            except ValueError:
                age = None
            if n_before >= 5 or (age is not None and age <= 24):
                rookies.append(pid)
    return season_table(list(games.values()), players, hp, wp, prev, rookies, league)


def for_season(league: str, season: int, through: str | None = None, team_wins: dict | None = None,
               use_cache: bool = True, n: int = N_SIMS) -> dict:
    """Award races for one league-season: weights fitted on every earlier season on disk whose winner is in
    `award_winners`, current table from the stores, impact and WPA models, projected to season end.
    Returns {"ok","races": {award: {pid: {"p","p_top3",...}}}, "models": {award: fit}, "features": {award: {pid: {...}}}}."""
    try:
        seasons = [s for s in _seasons_on_disk(league) if s <= int(season)]
        if int(season) not in seasons:
            return {"ok": False, "reason": "no store for season"}
        key = _io.file_key(MODEL_VERSION, through, team_wins, n,
                           *[_io.data_root() / league / str(s) / "store.json" for s in seasons])

        def build():
            seen: set[str] = set()
            tables: dict[int, pd.DataFrame] = {}
            prev = None
            for k, s in enumerate(seasons):
                t = _table_for(league, s, through if s == int(season) else None, use_cache, seen, k, prev)
                tables[s] = t
                prev = t
                st = _io.season_file(league, s, "store.json") or {}
                for g in (st.get("games") or {}).values():
                    for tb in (g.get("box") or {}).values():
                        seen.update(str(r[0]) for r in tb.get("players") or [] if len(r) > 2 and (r[2] or 0) > 0)
            models = {}
            for a in AWARDS:
                hist = []
                for s in (x for x in seasons if x < int(season)):
                    wins = resolve_winners(aw.winner_names(league, a, s), tables[s])
                    if wins:
                        hist.append((tables[s], wins))
                models[a] = fit_award(a, hist)
            cur = tables[int(season)]
            out_r, feats = {}, {}
            for a in AWARDS:
                if a == "clutch" and league != "nba":
                    continue
                r = race(a, cur, models[a], team_wins, n=n, league=league, season=int(season))
                if r:
                    out_r[a] = r
                    pl = pool(cur, a)
                    feats[a] = {pid: {c: pl.at[pid, c] for c in FEATURES[a] + ["name", "team", "games", "elig_games"]}
                                for pid in list(r)[:25]}
            return _io.clean({"ok": True, "league": league, "season": int(season), "through": through, "races": out_r,
                              "models": models, "features": feats})

        return _io.cached("awards", f"{league}_{season}_{through or 'all'}", key, build, use_cache)
    except Exception as exc:                                          # pragma: no cover - defensive
        return {"ok": False, "reason": f"awards failed: {exc}"}
