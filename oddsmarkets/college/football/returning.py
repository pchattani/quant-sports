"""
Returning production for the football models (round 4; docs/research/college_edge.md), built only from what is
known before each game.

For season S and team t, last season's players (box-score player value, `players.season_value`, per game) are
split into expected returners and expected departures:

    p0(i)  = P(player i appears for t in season S)      logistic on earlier season pairs only: seasons already in
                                                         the box scores (eligibility), games-played share, position
                                                         group, value per game (walk-forward: fitted on pairs
                                                         (S'-1, S') with S' < S)
    in season, before day D: p(i) = 1 if i has appeared for t before D, else p0(i) x a_k, with a_k = P(appears later |
    absent from the team's first k games) / P(appears), measured on the same earlier pairs
    lost_t(D)   = sum_i (1 - p(i)) value_pg(i)          (QB and the rest separately)
    gained_t(D) = sum of last season's value_pg of players who have appeared for t before D after playing for
                  another team last season (inferred transfers in; zero before t's first game)

Rosters in the stores mix seasons (MODELS_CFB.md section 2), so membership comes from box scores only. Freshmen,
redshirts and transfers in are invisible before a team's first game.
"""
from __future__ import annotations

import gzip
import logging
import pickle
from datetime import date

import numpy as np
import pandas as pd

from . import data, players

logger = logging.getLogger(__name__)
KMAX = 4


def _box(season: int) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    p = data.cache_dir() / f"players_{season}.pkl.gz"
    try:
        with gzip.open(p, "rb") as fh:
            v = pickle.load(fh)["value"]
        return v["box"], v["credit"]
    except (OSError, KeyError, EOFError, pickle.UnpicklingError):
        return None


def season_tables(seasons: list[int]) -> dict[int, dict]:
    """{S: {"val": per (pid, team) value per game, pos, gp; "app": (pid, team, dayn) first appearances by game}}."""
    pos_map = players.position_map([s for s in seasons if s >= max(seasons) - 6])
    out = {}
    for s in seasons:
        b = _box(s)
        if b is None or not len(b[0]):
            continue
        box, credit = b
        st = data.load_store(s)
        val = players.season_value(s, box, credit if credit is not None else pd.DataFrame(columns=["gid", "pid"]), pos_map, st)
        if not len(val):
            continue
        tg = box.groupby("team")["gid"].nunique()
        val = val[["pid", "team", "pos", "gp", "value"]].copy()
        val["team_g"] = val["team"].map(tg).fillna(1).clip(lower=1)
        val["value_pg"] = val["value"] / val["team_g"]
        app = box[["pid", "team", "gid", "date"]].copy()
        app["dayn"] = [date.fromisoformat(str(data.us_day(d))[:10]).toordinal() if d else -1 for d in app["date"]]
        out[s] = {"val": val, "app": app}
    return out


def _feat(df: pd.DataFrame) -> np.ndarray:
    k = df["nseas"].clip(upper=5).to_numpy(int)
    oh = np.zeros((len(df), 5))
    oh[np.arange(len(df)), np.clip(k, 1, 5) - 1] = 1.0
    share = (df["gp"] / df["team_g"]).clip(0, 1).to_numpy(float)
    vpg = df["value_pg"].clip(-3, 6).to_numpy(float)
    qb = (df["pos"] == "QB").to_numpy(float)
    skill = df["pos"].isin(["RB", "WR", "TE"]).to_numpy(float)
    de = df["pos"].isin(["DL", "LB", "DB"]).to_numpy(float)
    return np.column_stack([oh, share, vpg, qb, skill, de, share * oh[:, 3:].sum(axis=1)])


def _logit_fit(X: np.ndarray, y: np.ndarray, l2: float = 1e-2) -> np.ndarray:
    from scipy.optimize import minimize
    Xb = np.column_stack([np.ones(len(X)), X])

    def f(w):
        z = Xb @ w
        p = 1 / (1 + np.exp(-z))
        ll = -np.mean(y * np.log(np.clip(p, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1)))
        g = Xb.T @ (p - y) / len(y)
        return ll + l2 * np.sum(w[1:] ** 2), g + 2 * l2 * np.r_[0, w[1:]]
    return minimize(f, np.zeros(Xb.shape[1]), jac=True, method="L-BFGS-B").x


def _nseas(tabs: dict) -> dict[int, dict[str, int]]:
    seen: dict[str, int] = {}
    out: dict[int, dict[str, int]] = {}
    for s in sorted(tabs):
        for p in set(tabs[s]["val"]["pid"]):
            seen[p] = seen.get(p, 0) + 1
        out[s] = dict(seen)                       # seasons with a box appearance through s
    return out


def _pair(tabs: dict, nseas: dict, s: int) -> pd.DataFrame:
    """Season s-1's players with their features and how (and when) they appeared in season s."""
    v = tabs[s - 1]["val"].copy()
    v["nseas"] = v["pid"].map(nseas[s - 1]).fillna(1).astype(int)
    app = tabs[s]["app"] if s in tabs else pd.DataFrame(columns=["pid", "team", "dayn"])
    first = app.groupby(["pid", "team"])["dayn"].min()
    v["first_day"] = [first.get((p, t), np.nan) for p, t in zip(v["pid"], v["team"])]
    v["returned"] = np.isfinite(v["first_day"].astype(float)).astype(float)
    v["tseason"] = s
    return v


def build(seasons: list[int], oracle: bool = False) -> tuple[dict[int, pd.DataFrame], dict]:
    """{S: last season's players of each team with nseas, p0 (walk-forward), returned flag and first appearance day}.
    attrs: "a_k" (absence factors) and "w" (the return model's weights, fitted on the eight earlier pairs).
    oracle=True sets p0 to the realised return (an upper bound only; never a model input)."""
    tabs = season_tables(sorted(set(seasons) | {s - 1 for s in seasons}))
    nseas = _nseas(tabs)
    pairs = {s: _pair(tabs, nseas, s) for s in sorted(tabs) if s - 1 in tabs}
    out = {}
    for s in sorted(pairs):
        v = pairs[s].copy()
        tr = [pairs[q] for q in pairs if s - 8 <= q < s]
        w = None
        if oracle:
            v["p0"] = v["returned"]
        elif sum(len(t) for t in tr) < 2000:
            v["p0"] = float(np.mean([t["returned"].mean() for t in tr])) if tr else 0.6
        else:
            T = pd.concat(tr, ignore_index=True)
            w = _logit_fit(_feat(T), T["returned"].to_numpy(float))
            v["p0"] = p0_of(v, w)
        v.attrs["a_k"] = absence_factors(tr, tabs) if not oracle else [1.0] * (KMAX + 1)
        v.attrs["w"] = None if w is None else [float(x) for x in w]
        out[s] = v
    return out, tabs


def p0_of(v: pd.DataFrame, w) -> np.ndarray:
    z = np.column_stack([np.ones(len(v)), _feat(v)]) @ np.asarray(w, float)
    return 1 / (1 + np.exp(-z))


def current(season: int, w, a_k: list[float], history: int = 7) -> tuple[dict[int, pd.DataFrame], dict]:
    """Production: season S's returning-production table from a committed return model (weights `w`, absence
    factors `a_k`, both fitted on earlier seasons by scripts/campus_r4.py fit), loading only S-history..S."""
    tabs = season_tables(list(range(int(season) - history, int(season) + 1)))
    if season - 1 not in tabs:
        return {}, tabs
    v = _pair(tabs, _nseas({k: t for k, t in tabs.items() if k < season}), season)
    v["p0"] = p0_of(v, w)
    v.attrs["a_k"] = list(a_k)
    return {int(season): v}, tabs


def absence_factors(tr: list[pd.DataFrame], tabs: dict) -> list[float]:
    """a_k = P(appears later | absent from the team's first k games) / P(appears), k = 0..KMAX, from earlier pairs."""
    if not tr:
        return [1.0] + [0.5 ** k for k in range(1, KMAX + 1)]
    num = np.zeros(KMAX + 1)
    den = np.zeros(KMAX + 1)
    base_r, base_n = 0.0, 0
    for v in tr:
        s = int(v["tseason"].iloc[0]) if len(v) else None
        base_r += float(v["returned"].sum())
        base_n += len(v)
        app = tabs.get(s, {}).get("app") if s else None
        if app is None:
            continue
        tdays = app.groupby("team")["dayn"].apply(lambda x: sorted(set(x))).to_dict()
        for t, fd in zip(v["team"], v["first_day"]):
            days = tdays.get(t) or []
            for k in range(KMAX + 1):
                if k >= len(days):
                    break
                cutoff = days[k] if k < len(days) else None   # absent from the first k games = first_day >= days[k]
                if np.isfinite(fd) and fd < cutoff:
                    continue
                den[k] += 1
                num[k] += 1.0 if np.isfinite(fd) else 0.0
    pr = base_r / max(base_n, 1)
    return [float(min(1.0, (num[k] / den[k]) / pr)) if den[k] > 50 else 0.5 ** k for k in range(KMAX + 1)]


def game_features(F: pd.DataFrame, built: dict[int, pd.DataFrame], tabs: dict) -> pd.DataFrame:
    """Per row of F (season, dayn, home, away): rp_qb / rp_oth = (gained - lost) home minus away, value per game."""
    out = pd.DataFrame(index=F.index, data={"rp_qb": 0.0, "rp_oth": 0.0, "rp_have": 0.0})
    for s, R in F.groupby("season"):
        v = built.get(int(s))
        if v is None or int(s) not in tabs:
            continue
        a_k = v.attrs.get("a_k") or [1.0] * (KMAX + 1)
        app = tabs[int(s)]["app"]
        tdays = app.groupby("team")["dayn"].apply(lambda x: np.array(sorted(set(x)))).to_dict()
        prev = tabs.get(int(s) - 1, {}).get("val")
        prev_pg = prev.groupby("pid")["value_pg"].max().to_dict() if prev is not None else {}
        prev_team = prev.set_index("pid")["team"].to_dict() if prev is not None else {}
        prev_pos = prev.set_index("pid")["pos"].to_dict() if prev is not None else {}
        first_any = app.groupby(["pid", "team"])["dayn"].min().reset_index()
        by_team = {t: g for t, g in v.groupby("team")}
        inc = {t: g for t, g in first_any.groupby("team")}
        cache: dict = {}

        def team_val(t, d, cache=cache, by_team=by_team, tdays=tdays, a_k=a_k, inc=inc, prev_team=prev_team,
                     prev_pg=prev_pg, prev_pos=prev_pos):
            key = (t, d)
            if key in cache:
                return cache[key]
            g = by_team.get(t)
            k = int(np.sum(tdays.get(t, np.array([])) < d))
            lq = lo = 0.0
            if g is not None:
                appeared = np.isfinite(g["first_day"].to_numpy(float)) & (g["first_day"].to_numpy(float) < d)
                p = np.where(appeared, 1.0, g["p0"].to_numpy(float) * a_k[min(k, KMAX)])
                lost = (1 - p) * g["value_pg"].to_numpy(float).clip(min=0)
                q = (g["pos"] == "QB").to_numpy(bool)
                lq, lo = float(lost[q].sum()), float(lost[~q].sum())
            gq = go = 0.0
            ii = inc.get(t)
            if ii is not None and k > 0:
                own = set(g["pid"]) if g is not None else set()
                for pid, fd in zip(ii["pid"], ii["dayn"]):
                    if fd < d and pid in prev_team and prev_team[pid] != t and pid not in own:
                        val = max(0.0, float(prev_pg.get(pid, 0.0)))
                        if prev_pos.get(pid) == "QB":
                            gq += val
                        else:
                            go += val
            cache[key] = (gq - lq, go - lo, 1.0 if g is not None else 0.0)
            return cache[key]
        qd, od, hv = [], [], []
        for d, h, a in zip(R["dayn"].astype(int), R["home"], R["away"]):
            th, ta = team_val(h, d), team_val(a, d)
            qd.append(th[0] - ta[0])
            od.append(th[1] - ta[1])
            hv.append(min(th[2], ta[2]))
        out.loc[R.index, "rp_qb"] = qd
        out.loc[R.index, "rp_oth"] = od
        out.loc[R.index, "rp_have"] = hv
    return out
