"""
CFP committee-ranking proxy: a linear resume score fitted to ESPN's historical CFP rankings (2014 on, every
weekly ranking and the final selection ranking) by pairwise logistic regression:

    P(team i ranked above team j) = sigmoid(w . (x_i - x_j))

over every ordered pair of ranked teams and every (ranked, unranked top-60-by-rating) pair, the selection-day
ranking weighted 3x. Features (standardised, computed from games before the ranking's release day):
wins, losses, our points rating at that day (walk-forward snapshot), strength of schedule (mean opponent
rating), wins over our top 25, losses to teams outside our top 60 or below FBS, conference champion
(title game won), power-conference member (SEC, Big Ten, Big 12, ACC, Pac-12 to 2023, Big East to 2012; Notre Dame).

Out-of-sample accuracy: leave one season out (fit on the other seasons, score the held-out season's selection
ranking): Spearman correlation of our order with the committee's over its top 25, top-12 and top-4 overlap,
against the AP poll of the same week as a reference. In the season sim, team scores get Gumbel noise so that
pairwise orders follow the fitted logistic.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import spearmanr

from . import data

FEATURES = ["wins", "losses", "rating", "sos", "top25_wins", "bad_losses", "conf_champ", "power_conf"]
VERSION = "cfb-committee-2"
FIRST = 2014


def snapshot_at(snaps: dict, final: dict, day: str, kind: str = "pts") -> dict:
    """The walk-forward rating snapshot for games before `day` (the first snapshot day >= day, else final)."""
    days = sorted(d for d in snaps if d >= day)
    if days:
        u = snaps[days[0]].get(kind)
        if u is not None:
            return u
    return None


def _net(u, teams: list[str]) -> dict[str, float]:
    if u is None:
        return {}
    if isinstance(u.get("off"), dict):
        return {t: u["off"][t] + u["def"][t] for t in u["off"]}
    return {t: float(u["off"][i] + u["def"][i]) for i, t in enumerate(teams)}


def resume(season: int, st: dict, gf: pd.DataFrame, rating: dict[str, float], before_day: str | None) -> pd.DataFrame:
    """Resume features of every FBS member from finished games before `before_day` (None = all)."""
    tm = st.get("teams") or {}
    mem = [t for t, v in tm.items() if v.get("member")]
    g = gf[gf["final"]]
    if before_day:
        g = g[g["day"] < before_day]
    fbs_r = sorted(((rating.get(t, -99.0), t) for t in mem), reverse=True)
    top25 = {t for _, t in fbs_r[:25]}
    top60 = {t for _, t in fbs_r[:60]}
    rows = {t: {"wins": 0, "losses": 0, "opp": [], "top25_wins": 0, "bad_losses": 0, "conf_champ": 0} for t in mem}
    for h, a, hs, as_, stype in zip(g["home"], g["away"], g["hs"], g["as"], g["stype"]):
        for t, o, won in ((h, a, hs > as_), (a, h, as_ > hs)):
            if t not in rows:
                continue
            r = rows[t]
            r["opp"].append(rating.get(o, -20.0))
            if won:
                r["wins"] += 1
                if o in top25:
                    r["top25_wins"] += 1
                if stype == "conf":
                    r["conf_champ"] = 1
            elif hs != as_:
                r["losses"] += 1
                if o not in top60:
                    r["bad_losses"] += 1
    out = []
    for t, r in rows.items():
        out.append({"team": t, "wins": r["wins"], "losses": r["losses"], "rating": rating.get(t, 0.0),
                    "sos": float(np.mean(r["opp"])) if r["opp"] else 0.0, "top25_wins": r["top25_wins"],
                    "bad_losses": r["bad_losses"], "conf_champ": r["conf_champ"],
                    "power_conf": int(data.is_power((tm.get(t) or {}).get("conference"), season, t))})
    return pd.DataFrame(out)


def ranking_tables(pipe: dict, seasons: list[int] | None = None) -> list[dict]:
    """[{season, week, day, final: bool, X: frame, ranked: [tid in order], ap: [tid...]}] for every CFP ranking."""
    out = []
    for s in sorted(seasons or pipe["seasons"]):
        if s < FIRST or s >= pipe["current"] and s not in (seasons or []):
            continue
        st = data.load_store(s)
        cfp = (st.get("rankings") or {}).get("cfp") or {}
        weeks = sorted((w for w in cfp if w.isdigit()), key=int)
        if not weeks:
            continue
        ws = data.week_starts(st)
        gf = data.games_frame(s, st)
        snaps = pipe["snapshots"].get(s) or {}
        teams = pipe["teams"].get(s) or []
        last = weeks[-1]
        for w in weeks:
            day = ws.get(w)
            if not day:
                continue
            u = snapshot_at(snaps, pipe["final"].get(s, {}), day)
            rating = _net(u, teams) if u is not None else _net(pipe["final"][s]["pts"], teams)
            X = resume(s, st, gf, rating, day)
            ranked = [str(r[1]) for r in sorted(cfp[w], key=lambda r: r[0])]
            ap = (st.get("rankings") or {}).get("ap", {}).get(w) or []
            out.append({"season": s, "week": w, "day": day, "final": w == last, "X": X, "ranked": ranked,
                        "ap": [str(r[1]) for r in sorted(ap, key=lambda r: r[0])]})
    return out


def _pairs(tab: dict, mu: np.ndarray, sd: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    X = tab["X"].set_index("team")
    ranked = [t for t in tab["ranked"] if t in X.index]
    if len(ranked) < 10:
        return np.zeros((0, len(FEATURES))), np.zeros(0)
    Z = (X[FEATURES].to_numpy(float) - mu) / sd
    pos = {t: i for i, t in enumerate(X.index)}
    unr = [t for t in X.sort_values("rating", ascending=False).index[:60] if t not in set(ranked)]
    D = []
    for i, a in enumerate(ranked):
        for b in ranked[i + 1:]:
            D.append(Z[pos[a]] - Z[pos[b]])
        for b in unr:
            D.append(Z[pos[a]] - Z[pos[b]])
    w = np.full(len(D), 3.0 if tab["final"] else 1.0)
    return np.array(D), w


def fit(tabs: list[dict], l2: float = 0.01) -> dict:
    allX = pd.concat([t["X"][FEATURES] for t in tabs], ignore_index=True) if tabs else pd.DataFrame(columns=FEATURES)
    mu = allX.mean().to_numpy(float) if len(allX) else np.zeros(len(FEATURES))
    sd = allX.std().replace(0, 1).fillna(1).to_numpy(float) if len(allX) else np.ones(len(FEATURES))
    Ds, Ws = [], []
    for t in tabs:
        D, w = _pairs(t, mu, sd)
        if len(D):
            Ds.append(D)
            Ws.append(w)
    if not Ds:
        return {"w": np.zeros(len(FEATURES)), "mu": mu, "sd": sd, "n_pairs": 0}
    D = np.vstack(Ds)
    W = np.concatenate(Ws)

    def f(w):
        z = D @ w
        l = np.logaddexp(0, -z)
        g = -(D * (W * (1 - 1 / (1 + np.exp(-z))))[:, None]).sum(axis=0)
        return float((W * l).sum() / W.sum() + l2 * w @ w), g / W.sum() + 2 * l2 * w

    r = minimize(f, np.zeros(len(FEATURES)), jac=True, method="L-BFGS-B")
    return {"w": r.x, "mu": mu, "sd": sd, "n_pairs": len(D)}


def score(model: dict, X: pd.DataFrame) -> np.ndarray:
    Z = (X[FEATURES].to_numpy(float) - model["mu"]) / model["sd"]
    return Z @ model["w"]


def evaluate(tab: dict, model: dict) -> dict:
    X = tab["X"].copy()
    X["score"] = score(model, X)
    order = list(X.sort_values("score", ascending=False)["team"])
    pr = {t: i + 1 for i, t in enumerate(order)}
    act = [t for t in tab["ranked"] if t in pr][:25]
    sp = spearmanr(range(1, len(act) + 1), [pr[t] for t in act]).correlation if len(act) > 2 else None
    out = {"spearman": None if sp is None else float(sp),
           "top12": len(set(order[:12]) & set(tab["ranked"][:12])) / 12.0,
           "top4": len(set(order[:4]) & set(tab["ranked"][:4])) / 4.0}
    if tab.get("ap"):
        ap = [t for t in tab["ap"]]
        apr = {t: i + 1 for i, t in enumerate(ap)}
        out["ap_top12"] = len(set(ap[:12]) & set(tab["ranked"][:12])) / 12.0
        out["ap_top4"] = len(set(ap[:4]) & set(tab["ranked"][:4])) / 4.0
        both = [t for t in act if t in apr]
        if len(both) > 2:
            out["ap_spearman"] = float(spearmanr(range(1, len(both) + 1), [apr[t] for t in both]).correlation)
    return out


def fit_and_validate(pipe: dict, use_cache: bool = True) -> dict:
    """Production fit on every season with CFP rankings before the current one, with leave-one-season-out
    accuracy on each season's selection ranking."""
    seasons = [s for s in pipe["seasons"] if FIRST <= s < pipe["current"]]
    key = hashlib.md5(f"{VERSION}|{pipe['key']}|{seasons}".encode()).hexdigest()[:16]
    if use_cache:
        c = data.cache_get("committee", key)
        if c is not None:
            return c
    tabs = ranking_tables(pipe, seasons)
    model = fit(tabs)
    per = []
    for s in sorted({t["season"] for t in tabs}):
        train = [t for t in tabs if t["season"] != s]
        test = [t for t in tabs if t["season"] == s and t["final"]]
        if not train or not test:
            continue
        m = fit(train)
        e = evaluate(test[0], m)
        e["season"] = s
        e["week"] = test[0]["week"]
        per.append(e)
    def avg(k):
        v = [p[k] for p in per if p.get(k) is not None]
        return round(float(np.mean(v)), 4) if v else None
    out = {"model": model, "per_season": per, "n_seasons": len(per),
           "spearman": avg("spearman"), "top12_overlap": avg("top12"), "top4_overlap": avg("top4"),
           "ap_spearman": avg("ap_spearman"), "ap_top12_overlap": avg("ap_top12"), "ap_top4_overlap": avg("ap_top4"),
           "features": FEATURES, "weights": [round(float(x), 4) for x in model["w"]], "key": key}
    data.cache_put("committee", key, out)
    return out
