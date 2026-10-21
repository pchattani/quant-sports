"""
Expected points (EP), EPA and success rate fitted on college plays (ESPN play-by-play, `data/college/cfb/plays`).

Label: the next score in the same half from the snap team's point of view, one of seven classes
TD (+7), FG (+3), safety (+2), none (0), opp safety (-2), opp FG (-3), opp TD (-7), as in the NFL model
(oddsmarkets/nfl/models/ep.py). Scoring events come from the play type (ESPN's running score on college plays is
written per drive and is not reliable play by play): offensive TD types (rushing/passing TD, kickoff-return TD for
the receiving team), defensive TD types (interception/fumble/punt-return/blocked-kick TDs), field goals good,
safeties.

Model: a multinomial logistic regression (closed-form features, scipy L-BFGS with the analytic gradient, L2
1e-3) on yards to the end zone (linear + hinge basis at 5/10/20/35/50/65/80/90/95), down dummies and their
interactions with field position and log distance, goal to go, seconds left in the half (and a final-two-minutes
ramp interacted with field position) and the half. Overtime plays are excluded.
No season is scored by a model that saw it: seasons up to 2011 (no closing lines) are cross-fitted inside that
block (round-robin folds); every later season is scored by a model fitted on the seasons before it (walk-forward,
refitted every two seasons), so the EPA inputs of the backtest against closing lines use earlier seasons only;
the current season is scored by the model fitted on every completed season. Fits subsample at most 700,000
plays (whole games).

EPA = EP after - EP before: after = the points when the play scores (+7/+3 for the offence, -7/-2 when the
defence scores), else the next snap's EP in the same half (sign-flipped on a change of possession), else 0
at the end of the half.
Success: 50% of the distance on 1st down, 70% on 2nd, 100% on 3rd/4th (or a touchdown); turnovers fail.
Garbage time (excluded from team ratings): score margin above 38 in the 2nd quarter, 28 in the 3rd, 22 in the
4th (Connelly's thresholds), margin from the score rebuilt from the scoring events.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from oddsmarkets.college import store

from . import data

VERSION = "cfb-ep-8"
CLASSES = ["td", "fg", "safety", "none", "opp_safety", "opp_fg", "opp_td"]
VALUES = np.array([7.0, 3.0, 2.0, 0.0, -2.0, -3.0, -7.0])
REF = 3
KNOTS = (5, 10, 20, 35, 50, 65, 80, 90, 95)
MAX_FIT_ROWS = 700_000
EARLY_END = 2011       # last season without closing lines
STEP = 2               # walk-forward refit interval (seasons)
L2 = 1e-3

PASS_T = {24, 3, 7, 67, 26, 36, 63, 4, 6, 51}     # 6 "Pass Interception" (2008-2014), 51 "Pass" (2005-2007)
RUSH_T = {5, 68}
FUMBLE_T = {9, 29, 69, 39}
PUNT_T = {52, 14, 17, 37, 34}
FG_T = {59, 60, 18, 38, 40}
KICKOFF_T = {53, 12, 32}
PEN_T = {8}
OFF_TD_T = {67, 68, 32}
DEF_TD_T = {34, 36, 37, 38, 39}
GARBAGE = {2: 38, 3: 28, 4: 22}
# administrative rows never used as snaps: timeouts, period/half/game ends, coin toss, PATs and two-point tries
NON_SNAP_T = {21, 2, 65, 66, 79, 70, 61, 62, 56, 57}
_TD_RE = re.compile(r"\bFOR A TD\b|\bTD\b\s*\(|\bTD\s*$|\bYD (?:RUN|PASS|RETURN|INTERCEPTION RETURN|FUMBLE RETURN)\b[^,]*\bTD\b")


# ── play frame ──────────────────────────────────────────────────────────────

def _kind(tp: np.ndarray, text: np.ndarray) -> np.ndarray:
    out = np.full(len(tp), "other", dtype=object)
    low = np.array([str(t).lower() for t in text], dtype=object)
    for i, (t, s) in enumerate(zip(tp, low)):
        if t in PASS_T:
            out[i] = "pass"
        elif t in RUSH_T:
            out[i] = "rush"
        elif t in FUMBLE_T:
            out[i] = "pass" if (" pass" in s or "sack" in s) else ("rush" if (" rush" in s or " run " in s or " run for" in s) else "other")
        elif t in PUNT_T:
            out[i] = "punt"
        elif t in FG_T:
            out[i] = "fg"
        elif t in KICKOFF_T:
            out[i] = "kickoff"
        elif t in PEN_T:
            out[i] = "penalty"
        elif t == 20:
            out[i] = "safety"
        if out[i] == "rush" and ("kneel" in s):
            out[i] = "kneel"
        if out[i] == "pass" and ("spike" in s and "pass" not in s):
            out[i] = "spike"
    return out


def _event_by_type(t: int, s: str) -> tuple[float, str]:
    """Points and side of a play ESPN flags as scoring (or, for games without flags, a play of a scoring type)."""
    if t == 57 or "DEFENSIVE PAT" in s or "DEFENSIVE 2PT" in s:
        return 0.0, ""
    if t == 38 or (t in (18, 40) and ("TOUCHDOWN" in s or _TD_RE.search(s))):
        return 7.0, "def"
    if t == 59 or ("FIELD GOAL" in s and "MISSED" not in s and "NO GOOD" not in s and "BLOCKED" not in s):
        return 3.0, "off"
    if t == 20 or "SAFETY" in s:
        return 2.0, "def"
    if t in KICKOFF_T:
        return 7.0, "off"
    if t in DEF_TD_T or t in PUNT_T or t in (26, 29, 36, 63):
        return 7.0, "def"
    if t != 9 and ("RECOVERED BY" in s and ("FUMBLE" in s) and "RETURN" in s) or "INTERCEPTED" in s:
        return 7.0, "def"
    return 7.0, "off"


def _score_events(tp: np.ndarray, scoring: np.ndarray, text: np.ndarray, flagged_game: np.ndarray | None = None
                  ) -> tuple[np.ndarray, np.ndarray]:
    """(points value 7/3/2/0, side 'off'/'def'/'') per row. ESPN's `scoring` flag decides whether a play scored
    (text alone misleads: "TOUCHDOWN nullified by penalty", plays under review); the type and text decide who.
    Games whose feed carries no flags at all fall back to the scoring play types."""
    n = len(tp)
    val = np.zeros(n)
    side = np.full(n, "", dtype=object)
    fg = np.ones(n, bool) if flagged_game is None else flagged_game
    for i in range(n):
        t = int(tp[i])
        s = str(text[i]).upper()
        if fg[i]:
            if not scoring[i]:
                continue
            val[i], side[i] = _event_by_type(t, s)
        else:
            nullified = "NULLIFIED" in s or "NO PLAY" in s
            if nullified:
                continue
            td = "TOUCHDOWN" in s or _TD_RE.search(s) is not None
            if t in OFF_TD_T or t in DEF_TD_T or t in (59, 20) or (td and t not in (57,)):
                val[i], side[i] = _event_by_type(t, s)
    return val, side


def season_plays(season: int) -> pd.DataFrame:
    """Every play row of a season with derived columns (no EP yet). Empty frame when no plays file."""
    raw = data.load_plays_raw(season)
    cols = raw.get("cols") or store.PLAY_COLS
    rows, gids = [], []
    for gid, gp in (raw.get("games") or {}).items():
        pl = gp.get("plays") or []
        rows.extend(pl)
        gids.extend([str(gid)] * len(pl))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=cols)
    df.insert(0, "gid", gids)
    # ESPN sometimes serves a play twice (two feeds): drop exact repeats of (game, period, clock, type, text)
    df = df[~df.duplicated(subset=["gid", "period", "clock_s", "type_id", "text"], keep="first")].reset_index(drop=True)
    df["season"] = int(season)
    df["row"] = np.arange(len(df))
    for c in ("period", "clock_s", "type_id", "down", "distance", "yte", "yards", "end_yte", "scoring", "turnover", "penalty"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["wp_home"] = pd.to_numeric(df["wp_home"], errors="coerce")
    df["offense"] = df["offense"].astype(str)
    df["defense"] = df["defense"].astype(str)
    df["text"] = df["text"].fillna("").astype(str)
    tp = df["type_id"].fillna(-1).astype(int).to_numpy()
    df["kind"] = _kind(tp, df["text"].to_numpy())
    p = df["period"].fillna(0).astype(int).to_numpy()
    df["half"] = np.where(p <= 2, 1, np.where(p <= 4, 2, 3))
    clk = df["clock_s"].fillna(0).to_numpy(float)
    df["half_sec"] = np.where(np.isin(p, [1, 3]), clk + 900.0, clk)
    flag = df["scoring"].fillna(0).to_numpy()
    flagged_game = pd.Series(flag > 0).groupby(df["gid"].to_numpy()).transform("any").to_numpy()
    val, side = _score_events(tp, flag, df["text"].to_numpy(), flagged_game)
    df["pts"] = val
    df["score_side"] = side
    off = df["offense"].to_numpy()
    dfn = df["defense"].to_numpy()
    df["scorer"] = np.where(side == "off", off, np.where(side == "def", dfn, ""))
    # rebuilt running score (before each play) from the scoring events, per game; margin from the offence's view
    st = data.load_store(season)
    games = st.get("games") or {}
    home = df["gid"].map(lambda g: str((games.get(g) or {}).get("home"))).to_numpy()
    hp = np.where(df["scorer"].to_numpy() == home, val, 0.0)
    ap = np.where((df["scorer"].to_numpy() != home) & (val > 0), val, 0.0)
    g = df["gid"].to_numpy()
    hcum = pd.Series(hp).groupby(g).cumsum().to_numpy() - hp
    acum = pd.Series(ap).groupby(g).cumsum().to_numpy() - ap
    df["home_team"] = home
    df["margin_off"] = np.where(off == home, hcum - acum, acum - hcum)
    am = np.abs(df["margin_off"].to_numpy())
    thr = np.array([GARBAGE.get(int(x), 1e9) for x in p])
    df["garbage"] = am > thr
    yte = df["yte"].to_numpy(float)
    d = df["down"].to_numpy(float)
    kind = df["kind"].to_numpy()
    df["model_play"] = ((p >= 1) & (p <= 4) & np.isin(d, [1, 2, 3, 4]) & (yte >= 1) & (yte <= 99)
                        & np.isin(kind, ["pass", "rush", "punt", "fg", "penalty", "other", "kneel", "spike"])
                        & ~np.isin(tp, list(NON_SNAP_T)))
    return df


# ── labels and features ─────────────────────────────────────────────────────

def next_score_class(df: pd.DataFrame) -> np.ndarray:
    """Class index of the next score in the same game-half from each row's offence (NaN outside regulation)."""
    val = df["pts"].to_numpy(float)
    key = pd.factorize(df["gid"].astype(str) + "_" + df["half"].astype(str))[0]
    idx = pd.Series(np.where(val > 0, np.arange(len(df)), np.nan))
    nxt = idx.groupby(key).bfill().to_numpy()
    has = np.isfinite(nxt)
    j = np.where(has, nxt, 0).astype(int)
    v = np.where(has, val[j], 0.0)
    scorer = df["scorer"].to_numpy()[j]
    same = scorer == df["offense"].to_numpy()
    signed = np.where(has, np.where(same, v, -v), 0.0)
    cls = np.select([signed == 7, signed == 3, signed == 2, signed == 0, signed == -2, signed == -3, signed == -7],
                    [0, 1, 2, 3, 4, 5, 6], default=3).astype(float)
    cls[df["half"].to_numpy() > 2] = np.nan
    return cls


def design(yte, down, dist, half_sec, half) -> np.ndarray:
    yte = np.clip(np.asarray(yte, float), 1, 99)
    down = np.asarray(down, float)
    dist = np.clip(np.nan_to_num(np.asarray(dist, float), nan=10.0), 1, 30)
    hs = np.clip(np.nan_to_num(np.asarray(half_sec, float), nan=900.0), 0, 1800)
    half = np.asarray(half, float)
    y = yte / 100.0
    cols = [np.ones_like(y), y]
    cols += [np.maximum(0.0, yte - k) / 100.0 for k in KNOTS]
    d2, d3, d4 = (down == 2).astype(float), (down == 3).astype(float), (down == 4).astype(float)
    ld = np.log1p(dist) / 3.0
    gtg = (dist >= yte).astype(float)
    late = np.maximum(0.0, 120.0 - hs) / 120.0
    cols += [d2, d3, d4, d2 * y, d3 * y, d4 * y, ld, ld * d3, ld * d4, gtg, gtg * y,
             hs / 1800.0, late, late * y, (half == 2).astype(float), late * (half == 2)]
    return np.column_stack(cols)


N_FEAT = 2 + len(KNOTS) + 16


def _softmax_logits(X: np.ndarray, W: np.ndarray) -> np.ndarray:
    Z = X @ W                       # n x 7 (column REF fixed 0)
    Z -= Z.max(axis=1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(axis=1, keepdims=True)


def fit_multinomial(X: np.ndarray, y: np.ndarray, l2: float = L2) -> np.ndarray:
    n, k = X.shape
    Y = np.zeros((n, 7))
    Y[np.arange(n), y.astype(int)] = 1.0
    free = [c for c in range(7) if c != REF]

    def unpack(w):
        W = np.zeros((k, 7))
        W[:, free] = w.reshape(k, 6)
        return W

    def f(w):
        W = unpack(w)
        Z = X @ W
        m = Z.max(axis=1, keepdims=True)
        lse = (m[:, 0] + np.log(np.exp(Z - m).sum(axis=1)))
        ll = (Z * Y).sum(axis=1) - lse
        P = np.exp(Z - lse[:, None])
        G = X.T @ (P - Y) / n
        loss = -ll.mean() + l2 * (w @ w)
        return loss, G[:, free].ravel() + 2 * l2 * w

    w0 = np.zeros(k * 6)
    r = minimize(f, w0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return unpack(r.x)


def predict_proba(W: np.ndarray, df: pd.DataFrame) -> np.ndarray:
    X = design(df["yte"], df["down"], df["distance"], df["half_sec"], df["half"])
    return _softmax_logits(X, W)


def _sample_games(t: pd.DataFrame, cap: int, seed: int = 7) -> pd.DataFrame:
    if len(t) <= cap:
        return t
    rng = np.random.default_rng(seed)
    g = np.array(sorted(t["gid"].unique()), dtype=object)
    rng.shuffle(g)
    per = len(t) / max(len(g), 1)
    keep = set(g[: int(cap / per)])
    return t[t["gid"].isin(keep)]


def _mlogloss(y: np.ndarray, P: np.ndarray) -> float:
    p = np.clip(P[np.arange(len(y)), y.astype(int)], 1e-12, 1)
    return float(-np.mean(np.log(p)))


# ── fit pipeline (cached) ───────────────────────────────────────────────────

def _training(season: int) -> pd.DataFrame:
    df = season_plays(season)
    if not len(df):
        return df
    df["y"] = next_score_class(df)
    t = df[df["model_play"] & np.isfinite(df["y"])]
    return t[["gid", "season", "yte", "down", "distance", "half_sec", "half", "y"]].reset_index(drop=True)


def fit(current: int, seasons: list[int] | None = None, k: int = 5, use_cache: bool = True) -> dict:
    """{"W": production weights (completed seasons), "folds": {season: W}, "validation": {...}, "key"}."""
    seasons = sorted(seasons if seasons is not None else data.plays_seasons())
    done = [s for s in seasons if s < int(current)]
    files = [data.file_md5(store.plays_path(s)) for s in seasons]
    key = hashlib.md5(f"{VERSION}|{current}|{seasons}|{files}|{k}".encode()).hexdigest()[:16]
    if use_cache:
        c = data.cache_get("ep_fit", key)
        if c is not None:
            return c
    tabs = {s: _training(s) for s in seasons}
    tabs = {s: t for s, t in tabs.items() if len(t)}
    done = [s for s in done if s in tabs]
    out = {"key": key, "version": VERSION, "seasons": sorted(tabs), "folds": {}, "validation": {}}
    if not done:
        # nothing completed: fit on what exists (synthetic / first season)
        allt = pd.concat(list(tabs.values()), ignore_index=True) if tabs else None
        if allt is None or not len(allt):
            out["W"] = None
            return out
        t = _sample_games(allt, MAX_FIT_ROWS)
        out["W"] = fit_multinomial(design(t["yte"], t["down"], t["distance"], t["half_sec"], t["half"]), t["y"].to_numpy())
        return out
    def fit_on(train: list[int], seed: int = 7) -> np.ndarray:
        tt = _sample_games(pd.concat([tabs[s] for s in train], ignore_index=True), MAX_FIT_ROWS, seed=seed)
        return fit_multinomial(design(tt["yte"], tt["down"], tt["distance"], tt["half_sec"], tt["half"]), tt["y"].to_numpy())

    out["W"] = fit_on(done)
    # Which seasons train the model that scores each completed season (never the season itself):
    #   seasons up to EARLY_END (no closing lines exist): cross-fitted inside that block (round-robin folds);
    #   later seasons: walk-forward, a model fitted on every season before the season's anchor (refitted every
    #   STEP seasons), so the EPA inputs of every season in the v-close backtest come from earlier seasons only.
    early = [s for s in done if s <= EARLY_END]
    late = [s for s in done if s > EARLY_END]
    plan: dict[int, tuple] = {}
    kk = min(k, len(early)) if len(early) >= 2 else 0
    if kk:
        fold_of = {s: i % kk for i, s in enumerate(sorted(early))}
        for s in early:
            plan[s] = tuple(x for x in early if fold_of[x] != fold_of[s])
    for s in late:
        anchor = s - ((s - (EARLY_END + 1)) % STEP)
        plan[s] = tuple(x for x in done if x < anchor)
    for s in done:                       # nothing earlier: the other completed seasons, else in-sample (flagged)
        if not plan.get(s):
            plan[s] = tuple(x for x in done if x != s) or (s,)
    models: dict[tuple, np.ndarray] = {}
    val_rows = []
    for i, s in enumerate(sorted(done)):
        train = plan[s]
        if train not in models:
            models[train] = out["W"] if tuple(sorted(train)) == tuple(sorted(done)) else fit_on(list(train), seed=len(models))
        W = models[train]
        out["folds"][s] = W
        te = tabs[s]
        P = predict_proba(W, te)
        y = te["y"].to_numpy().astype(int)
        base = np.bincount(np.concatenate([tabs[x]["y"].to_numpy().astype(int) for x in train]), minlength=7)
        base = base / base.sum()
        val_rows.append({"season": s, "n": len(te), "logloss": round(_mlogloss(y, P), 4),
                         "logloss_base": round(_mlogloss(y, np.tile(base, (len(y), 1))), 4),
                         "ep_cal": _ep_cal(VALUES[y], P @ VALUES), "in_sample": s in train,
                         "train": [min(train), max(train), len(train)],
                         "scheme": "cross-fit (early block)" if s in early and kk else "walk-forward"})
    n = sum(r["n"] for r in val_rows)
    out["validation"] = {
        "per_season": val_rows,
        "n": n,
        "logloss": round(sum(r["logloss"] * r["n"] for r in val_rows) / max(n, 1), 4),
        "logloss_base": round(sum(r["logloss_base"] * r["n"] for r in val_rows) / max(n, 1), 4),
        "ep_cal_mae": round(sum(r["ep_cal"]["mae_weighted"] * r["n"] for r in val_rows) / max(n, 1), 4),
        "n_models": len(models), "early_end": EARLY_END, "step": STEP, "rows_per_fit_max": MAX_FIT_ROWS,
        "cross_fitted": True,
        "scheme": f"seasons to {EARLY_END}: cross-fitted within that block; later seasons: fitted on every season before "
                  f"(refitted every {STEP} seasons); the current season: fitted on every completed season"}
    data.cache_put("ep_fit", key, out)
    return out


def _ep_cal(v: np.ndarray, ep: np.ndarray) -> dict:
    b = np.clip(np.floor(ep), -3, 6)
    rows, err = [], 0.0
    for kk in np.unique(b):
        m = b == kk
        mp, mo = float(ep[m].mean()), float(v[m].mean())
        rows.append([float(kk), round(mp, 3), round(mo, 3), int(m.sum())])
        err += m.sum() * abs(mp - mo)
    return {"bins": rows, "mae_weighted": round(err / max(len(v), 1), 4)}


# ── EPA per play ────────────────────────────────────────────────────────────

def add_epa(df: pd.DataFrame, W: np.ndarray) -> pd.DataFrame:
    """Adds ep, epa, success, explosive to a season_plays frame (NaN off model plays)."""
    df = df.copy()
    m = df["model_play"].to_numpy()
    ep = np.full(len(df), np.nan)
    if m.any() and W is not None:
        ep[m] = predict_proba(W, df[m]) @ VALUES
    df["ep"] = ep
    idx = np.flatnonzero(m)
    epa = np.full(len(df), np.nan)
    if len(idx):
        g = df["gid"].to_numpy()
        h = df["half"].to_numpy()
        off = df["offense"].to_numpy()
        pts = df["pts"].to_numpy(float)
        side = df["score_side"].to_numpy()
        nxt = np.append(idx[1:], -1)
        ok = nxt >= 0
        bb = np.where(ok, nxt, 0)
        same_half = ok & (g[bb] == g[idx]) & (h[bb] == h[idx])
        same_pos = off[bb] == off[idx]
        after = np.where(same_half, np.where(same_pos, ep[bb], -ep[bb]), 0.0)
        # a scoring event at or after this snap and before the next snap (same game-half): use the points
        sc_rows = np.flatnonzero(pts > 0)
        if len(sc_rows):
            pos = np.searchsorted(sc_rows, idx)
            has = pos < len(sc_rows)
            first = sc_rows[np.minimum(pos, len(sc_rows) - 1)]
            limit = np.where(same_half, bb, np.iinfo(np.int64).max)
            valid_sc = has & (first < limit) & (g[first] == g[idx]) & (h[first] == h[idx])
            scorer = np.where(side[first] == "off", off[first], df["defense"].to_numpy()[first])
            signed = np.where(scorer == off[idx], pts[first], -pts[first])
            after = np.where(valid_sc, signed, after)
        epa[idx] = after - ep[idx]
    df["epa"] = epa
    kind = df["kind"].to_numpy()
    d = df["down"].to_numpy(float)
    dist = df["distance"].to_numpy(float)
    yds = df["yards"].fillna(0).to_numpy(float)
    need = np.where(d == 1, 0.5, np.where(d == 2, 0.7, 1.0)) * dist
    td = (df["pts"].to_numpy() == 7) & (df["score_side"].to_numpy() == "off")
    to = (df["turnover"].fillna(0).to_numpy() > 0) | (df["score_side"].to_numpy() == "def")
    scrim = np.isin(kind, ["pass", "rush"]) & m
    succ = np.where(scrim, ((yds >= need) | td) & ~to, np.nan)
    df["success"] = succ.astype(float)
    df["explosive"] = np.where(scrim, ((kind == "rush") & (yds >= 15)) | ((kind == "pass") & (yds >= 20)), np.nan).astype(float)
    df["scrim"] = scrim
    return df


def season_epa(season: int, fitd: dict) -> pd.DataFrame:
    """The season's plays with EP/EPA (the cross-fitted fold model for completed seasons, else production). Cached."""
    W = (fitd.get("folds") or {}).get(int(season))
    if W is None:
        W = fitd.get("W")
    key = hashlib.md5(f"{VERSION}|{fitd.get('key')}|{season}|{data.file_md5(store.plays_path(season))}".encode()).hexdigest()[:16]
    c = data.cache_get(f"plays_epa_{season}", key)
    if c is not None:
        return c
    df = season_plays(season)
    if not len(df) or W is None:
        return pd.DataFrame()
    df = add_epa(df, W)
    keep = ["gid", "season", "row", "period", "clock_s", "offense", "defense", "type_id", "down", "distance", "yte",
            "yards", "kind", "half", "pts", "scorer", "margin_off", "garbage", "model_play", "scrim", "ep", "epa",
            "success", "explosive", "turnover", "wp_home", "home_team", "text", "drive"]
    out = df[keep].copy()
    for c2 in ("ep", "epa", "success", "explosive", "wp_home", "margin_off"):
        out[c2] = out[c2].astype("float32")
    data.cache_put(f"plays_epa_{season}", key, out)
    return out


def team_game_stats(pl: pd.DataFrame) -> pd.DataFrame:
    """Per (gid, team): offensive and defensive EPA/play, success rate, pass/rush EPA, explosive rate, plays
    (scrimmage pass/rush snaps outside garbage time)."""
    if not len(pl):
        return pd.DataFrame(columns=["gid", "team", "opp", "n", "epa", "sr", "pass_epa", "rush_epa", "expl", "n_pass", "n_rush"])
    s = pl[pl["scrim"] & ~pl["garbage"] & (pl["period"] <= 4)]
    s = s.assign(is_pass=(s["kind"] == "pass").astype(float), is_rush=(s["kind"] == "rush").astype(float))
    s = s.assign(pe=s["epa"] * s["is_pass"], re=s["epa"] * s["is_rush"])
    g = s.groupby(["gid", "offense", "defense"], sort=False).agg(
        n=("epa", "size"), epa=("epa", "mean"), sr=("success", "mean"), expl=("explosive", "mean"),
        pe=("pe", "sum"), re=("re", "sum"), n_pass=("is_pass", "sum"), n_rush=("is_rush", "sum")).reset_index()
    g["pass_epa"] = g["pe"] / g["n_pass"].clip(lower=1)
    g["rush_epa"] = g["re"] / g["n_rush"].clip(lower=1)
    g = g.rename(columns={"offense": "team", "defense": "opp"}).drop(columns=["pe", "re"])
    return g
