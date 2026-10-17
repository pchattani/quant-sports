"""
Fourth-down and two-point decisions: the win probability of each option, the recommendation, the WP lost
by the choice made, and season grades per coach and team.

Options on a 4th down at yard line y (yards from the opponent's goal), distance t, score s, time left:

* go: P(convert) from the conversion model; the yards gained come from the empirical distribution of
  3rd/4th-down gains in the same distance bucket (five quantile points for a conversion, the yards beyond
  the line to gain; five for a failure, the yards gained short of it). A conversion is first down at
  y - g (a touchdown when g >= y: + 6 + P(PAT) and the opponent receives the kickoff); a failure gives the
  opponent the ball at 100 - (y - g).
* field goal (distance y + 17; offered up to 66 yards): P(make) from kicking.py for this kicker, era,
  weather, roof and altitude; a make is + 3 and the opponent receives the kickoff; a miss gives the
  opponent the ball at the spot of the kick (y + 7, at least the 20).
* punt: the receiving team's spot from the punt model (five quantile points) and the return-TD rate.

WP of each resulting state comes from wp.py (from the side with the ball, flipped where the opponent has
it: the score, home, spread, timeouts and the second-half kickoff all swap). The kickoff spot is the
season's median start after a kickoff (it moved with the 2024 and 2025 kickoff rules). Clock: 6 s for a
try, 8 s for a punt, 5 s for a field goal.

Conversion model: LightGBM binary on every 3rd- and 4th-down run or pass (converted = gained the line to
gain or scored, without a turnover), with distance, yard line, goal to go, 4th down, era, roof and team
strength: the offence's and the opponent defence's pregame EPA per play (decayed over previous games,
carried over seasons at 40%, shrunk toward 0 with SHRINK_PLAYS pseudo-plays). Monotone in distance and in
both strengths. Cross-fitted by season; 4th-down calibration is reported on actual 4th-down attempts.

Grades: WP lost = WP(best option) - WP(option chosen) (0 when the choice was the recommendation). The letter
grade on the payloads is analytics/games.grade (GRADE_CUTS: A <= 0.5 pp, B <= 1.5, C <= 3, D <= 6, F beyond).

Go rate over expected: this module also fits a LightGBM model of the go decision (GO_FEATURES: yard line,
distance, score, time and era; `exp_go`) and `_grades` builds coach and team tables from it (go rate over
expected per 100 4th downs, go rate when going beat the best alternative by RECOMMEND_MARGIN). Those tables are
NOT what the site publishes: the build does not use them (analytics/adapters.fourth_tables has no caller). The
published GOE (fourth_downs.json `go_exp`, coaches.json `goe`) comes from analytics/fourth.go_model, a logistic
regression fitted per season on log distance, field position and its square, score, game seconds, WP and
trailing in the last 15 minutes; its "go when the model says go" uses this module's recommendation (`rec`,
the highest-WP option), not RECOMMEND_MARGIN.

Two-point tries: WP(kick) = P(PAT) WP(+1) + (1 - P(PAT)) WP(+0) and WP(go) = P(2pt) WP(+2) + ..., each
WP with the opponent receiving the kickoff; P(PAT) is the season's league rate and P(2pt) the league
two-point rate (pooled, shrunk to 0.48). The two are close in expected points (2 x 0.47 against 0.94), so a
WP difference under TRY_MARGIN is called a toss-up ("either") and costs nothing. Overtime 4th downs are
listed but not graded (`graded`): the WP model has few overtime states and doesn't know the OT rules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io, kicking, wp as wpm
from oddsmarkets.nfl.models.ep import half_of

MODEL_VERSION = "4th-2"
CONV_FEATURES = ["ydstogo", "yardline_100", "goal_to_go", "is4", "off_r", "def_r", "era", "indoor"]
CONV_MONO = {"ydstogo": -1, "off_r": 1, "def_r": 1}
CONV_PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 300, "lambda_l2": 10.0}
GO_FEATURES = ["yardline_100", "ydstogo", "score_differential", "game_seconds_remaining", "half_seconds_remaining", "half", "era"]
GO_PARAMS = {"objective": "binary", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 100, "lambda_l2": 10.0}
TOGO_BUCKETS = [1, 2, 4, 7, 10, 15, 99]       # upper edges: 1, 2, 3-4, 5-7, 8-10, 11-15, 16+
QUANTS = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
DT = {"go": 6.0, "punt": 8.0, "fg": 5.0}
FG_MAX = 66.0
SHRINK_PLAYS = 300.0
DECAY = 0.97
CARRY = 0.4
TWO_PT_PRIOR = 0.48
RECOMMEND_MARGIN = 0.01
TRY_MARGIN = 0.005          # |WP(two) - WP(kick)| below this is a toss-up: no recommendation, no WP lost
OPTIONS = ["go", "punt", "fg"]


# ============================================================================ team strength (pregame EPA/play)

def game_team_epa(d: pd.DataFrame, epa_col: str = "epa") -> pd.DataFrame:
    pt = d["play_type"].astype(str)
    m = pt.isin(["pass", "run"]) & pd.to_numeric(d[epa_col], errors="coerce").notna()
    s = d[m]
    e = pd.to_numeric(s[epa_col], errors="coerce")
    off = s.assign(e=e).groupby(["game_id", "posteam"]).agg(off_sum=("e", "sum"), off_n=("e", "size"),
                                                           season=("season", "first"), week=("week", "first")).reset_index()
    off = off.rename(columns={"posteam": "team"})
    de = s.assign(e=e).groupby(["game_id", "defteam"]).agg(def_sum=("e", "sum"), def_n=("e", "size")).reset_index()
    de = de.rename(columns={"defteam": "team"})
    return off.merge(de, on=["game_id", "team"], how="outer")


def pregame_ratings(g: pd.DataFrame) -> pd.DataFrame:
    """(game_id, team, off_r, def_r): decayed, shrunk EPA/play of the offence and EPA/play allowed by the
    defence over the team's previous games (seasons carried at CARRY)."""
    g = g.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    out = []
    for team, gt in g.groupby("team", sort=False):
        so = no = sd = nd = 0.0
        last = None
        for r in gt.itertuples(index=False):
            if last is not None and r.season != last:
                so, no, sd, nd = so * CARRY, no * CARRY, sd * CARRY, nd * CARRY
            last = r.season
            out.append((r.game_id, team, so / (no + SHRINK_PLAYS), sd / (nd + SHRINK_PLAYS)))
            so = so * DECAY + (r.off_sum if r.off_sum == r.off_sum else 0.0)
            no = no * DECAY + (r.off_n if r.off_n == r.off_n else 0.0)
            sd = sd * DECAY + (r.def_sum if r.def_sum == r.def_sum else 0.0)
            nd = nd * DECAY + (r.def_n if r.def_n == r.def_n else 0.0)
    return pd.DataFrame(out, columns=["game_id", "team", "off_r", "def_r"])


def season_game_epa(season: int, use_cache: bool = True) -> pd.DataFrame:
    srcs = _io.source_files(season)
    key = _io.file_key(*srcs, MODEL_VERSION, "gte")
    recs = _io.cached("fourth_gte", str(int(season)), key,
                      lambda: game_team_epa(_io.plays(season)).to_dict("records") if _io.plays(season) is not None and len(_io.plays(season)) else [],
                      use_cache)
    return pd.DataFrame(recs)


def attach_ratings(d: pd.DataFrame, ratings: pd.DataFrame) -> pd.DataFrame:
    r = ratings
    o = r.rename(columns={"team": "posteam", "off_r": "off_r"})[["game_id", "posteam", "off_r"]]
    df = r.rename(columns={"team": "defteam", "def_r": "def_r"})[["game_id", "defteam", "def_r"]]
    d = d.drop(columns=[c for c in ("off_r", "def_r") if c in d.columns])
    return d.merge(o, on=["game_id", "posteam"], how="left").merge(df, on=["game_id", "defteam"], how="left")


# ============================================================================ conversion model and gains

def conv_rows(d: pd.DataFrame) -> pd.DataFrame:
    pt = d["play_type"].astype(str)
    dn = pd.to_numeric(d["down"], errors="coerce")
    kneel = pd.to_numeric(d.get("qb_kneel"), errors="coerce").fillna(0) if "qb_kneel" in d else 0
    spike = pd.to_numeric(d.get("qb_spike"), errors="coerce").fillna(0) if "qb_spike" in d else 0
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) if "two_point_attempt" in d else 0
    m = pt.isin(["pass", "run"]) & dn.isin([3, 4]) & (kneel == 0) & (spike == 0) & (tp == 0)
    s = d[m]
    yg = pd.to_numeric(s["yards_gained"], errors="coerce").fillna(0).to_numpy(float)
    togo = pd.to_numeric(s["ydstogo"], errors="coerce").to_numpy(float)
    td = (pd.to_numeric(s["touchdown"], errors="coerce").fillna(0).to_numpy() == 1) & \
         (s["td_team"].astype(object).to_numpy() == s["posteam"].astype(object).to_numpy())
    to = (pd.to_numeric(s["interception"], errors="coerce").fillna(0).to_numpy() == 1) | \
         (pd.to_numeric(s["fumble_lost"], errors="coerce").fillna(0).to_numpy() == 1)
    conv = ((yg >= togo) | td) & ~to
    out = pd.DataFrame({"ydstogo": togo, "yardline_100": pd.to_numeric(s["yardline_100"], errors="coerce").to_numpy(float),
                        "goal_to_go": pd.to_numeric(s["goal_to_go"], errors="coerce").to_numpy(float),
                        "is4": (dn[m] == 4).astype(float).to_numpy(),
                        "off_r": s["off_r"].to_numpy(float) if "off_r" in s else np.nan,
                        "def_r": s["def_r"].to_numpy(float) if "def_r" in s else np.nan,
                        "era": pd.to_numeric(s["season"], errors="coerce").to_numpy(float),
                        "indoor": pd.to_numeric(s["indoor"], errors="coerce").to_numpy(float) if "indoor" in s else np.nan,
                        "y": conv.astype(float), "gain": yg, "turnover": to.astype(float),
                        "season": pd.to_numeric(s["season"], errors="coerce").to_numpy(float),
                        "game_id": s["game_id"].astype(str).to_numpy()})
    return out


def bucket(togo) -> np.ndarray:
    return np.searchsorted(TOGO_BUCKETS, np.clip(np.asarray(togo, float), 1, 99), side="left")


def fit_gains(c: pd.DataFrame) -> dict:
    """Quantile points per distance bucket: yards beyond the line on a conversion, yards gained on a failure."""
    b = bucket(c["ydstogo"])
    y = c["y"].to_numpy(float)
    gain = c["gain"].to_numpy(float)
    togo = c["ydstogo"].to_numpy(float)
    succ, fail = [], []
    for k in range(len(TOGO_BUCKETS)):
        m = b == k
        s = m & (y == 1)
        f = m & (y == 0)
        succ.append(np.quantile(gain[s] - togo[s], QUANTS).tolist() if s.sum() >= 20 else [0.0, 1.0, 3.0, 6.0, 12.0])
        fail.append(np.quantile(gain[f] - togo[f], QUANTS).tolist() if f.sum() >= 20 else [-6.0, -3.0, -1.0, -1.0, -1.0])
    return {"buckets": TOGO_BUCKETS, "succ_excess": succ, "fail_short": fail}


def fit_conv(c: pd.DataFrame, k: int = 5) -> tuple[dict, np.ndarray]:
    c = c[np.isfinite(c["ydstogo"]) & np.isfinite(c["yardline_100"])].reset_index(drop=True)
    X, y = c[CONV_FEATURES], c["y"].to_numpy(float)
    folds = _io.fold_ids(c["season"].to_numpy(int), c["game_id"].to_numpy(), k)
    oof, infos = _io.crossfit(X, y, folds, c["game_id"].to_numpy(), "binary", CONV_PARAMS, rounds=600, monotone=CONV_MONO)
    best = int(np.mean([i["best_iter"] for i in infos])) if infos else 200
    model, _ = _io.fit_full(X, y, "binary", CONV_PARAMS, rounds=best, monotone=CONV_MONO)
    return {"model": model, "best_iter": best, "importance": _io.importances(model, CONV_FEATURES)}, oof


def conv_prob(fit: dict, X: pd.DataFrame) -> np.ndarray:
    return _io.lgb_predict(fit["models"]["conv"], X[CONV_FEATURES])


def ko_spots(d: pd.DataFrame) -> float | None:
    """Median yard line (from the receiving team's goal... i.e. yardline_100) of the first snap after a kickoff."""
    d = d.sort_values(["game_id", "play_id"], kind="mergesort")
    pt = d["play_type"].astype(str).to_numpy()
    dn = pd.to_numeric(d["down"], errors="coerce").to_numpy(float)
    yl = pd.to_numeric(d["yardline_100"], errors="coerce").to_numpy(float)
    g = d["game_id"].astype(str).to_numpy()
    out = []
    ko = np.flatnonzero(pt == "kickoff")
    for i in ko:
        if i + 1 < len(d) and g[i + 1] == g[i] and dn[i + 1] == 1:
            out.append(yl[i + 1])
    return float(np.median(out)) if out else None


def default_ko(season: int) -> float:
    return 75.0 if season < 2024 else (70.0 if season == 2024 else 65.0)


# ============================================================================ the decision calculator (pure)

def _states(n: int, **cols) -> pd.DataFrame:
    return pd.DataFrame({k: np.broadcast_to(np.asarray(v, float), (n,)).copy() for k, v in cols.items()})


def _own(b: dict, yl, down, togo, sd, dt) -> pd.DataFrame:
    n = len(b["yardline_100"])
    gsr = np.maximum(0.0, b["game_seconds_remaining"] - dt)
    hsr = np.maximum(0.0, b["half_seconds_remaining"] - dt)
    return _states(n, score_differential=sd, game_seconds_remaining=gsr, half_seconds_remaining=hsr, half=b["half"],
                   down=down, ydstogo=togo, yardline_100=yl, posteam_timeouts_remaining=b["posteam_timeouts_remaining"],
                   defteam_timeouts_remaining=b["defteam_timeouts_remaining"], home=b["home"], pos_spread=b["pos_spread"],
                   receive_2h_ko=b["receive_2h_ko"], season=b["season"])


def _opp(b: dict, opp_yl, sd_off, dt) -> pd.DataFrame:
    """The opponent's 1st and 10 at opp_yl (from the opponent's side), the offence's score diff sd_off."""
    n = len(b["yardline_100"])
    gsr = np.maximum(0.0, b["game_seconds_remaining"] - dt)
    hsr = np.maximum(0.0, b["half_seconds_remaining"] - dt)
    oy = np.clip(np.asarray(opp_yl, float), 1, 99)
    r2 = np.where(b["half"] == 1, 1.0 - b["receive_2h_ko"], 0.0)
    return _states(n, score_differential=-np.asarray(sd_off, float), game_seconds_remaining=gsr,
                   half_seconds_remaining=hsr, half=b["half"], down=1.0, ydstogo=np.minimum(10.0, oy), yardline_100=oy,
                   posteam_timeouts_remaining=b["defteam_timeouts_remaining"],
                   defteam_timeouts_remaining=b["posteam_timeouts_remaining"], home=1.0 - b["home"],
                   pos_spread=-b["pos_spread"], receive_2h_ko=r2, season=b["season"])


def evaluate(base: pd.DataFrame, wp_fn, p_conv: np.ndarray, p_fg: np.ndarray, gains: dict,
             punt_q: np.ndarray, punt_td: np.ndarray, ko_yl: np.ndarray, p_pat: np.ndarray) -> pd.DataFrame:
    """WP of go / punt / FG for each 4th-down state in `base` (columns: yardline_100, ydstogo,
    score_differential, game_seconds_remaining, half_seconds_remaining, half, posteam_timeouts_remaining,
    defteam_timeouts_remaining, home, pos_spread, receive_2h_ko, season). wp_fn(states) -> WP of the side in
    possession. Pure: every probability is an argument."""
    b = {c: pd.to_numeric(base[c], errors="coerce").to_numpy(float) for c in
         ("yardline_100", "ydstogo", "score_differential", "game_seconds_remaining", "half_seconds_remaining", "half",
          "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "pos_spread", "receive_2h_ko", "season")}
    b["pos_spread"] = np.nan_to_num(b["pos_spread"])
    b["receive_2h_ko"] = np.nan_to_num(b["receive_2h_ko"])
    n = len(b["yardline_100"])
    yl, togo, sd = b["yardline_100"], b["ydstogo"], b["score_differential"]
    ko = np.asarray(ko_yl, float) * np.ones(n)
    td_pts = 6.0 + np.asarray(p_pat, float) * np.ones(n)
    k = bucket(togo)
    succ = np.asarray(gains["succ_excess"], float)[k]       # (n, 5)
    fail = np.asarray(gains["fail_short"], float)[k]
    # ---- go
    wp_go = np.zeros(n)
    q = succ.shape[1]
    for j in range(q):
        g = togo + np.maximum(0.0, succ[:, j])
        new = yl - g
        td = new <= 0
        own = _own(b, np.clip(new, 1, 99), 1.0, np.minimum(10.0, np.clip(new, 1, 99)), sd, DT["go"])
        w_own = wp_fn(own)
        w_td = 1.0 - wp_fn(_opp(b, ko, sd + td_pts, DT["go"]))
        wp_go += (np.where(td, w_td, w_own)) * p_conv / q
        gf = np.minimum(togo + fail[:, j], togo - 1)          # short of the line
        opp_yl = 100.0 - (yl - gf)
        safety = opp_yl <= 0            # tackled in our own end zone
        w_fail = 1.0 - wp_fn(_opp(b, np.clip(opp_yl, 1, 99), sd, DT["go"]))
        w_saf = 1.0 - wp_fn(_opp(b, np.full(n, 60.0), sd - 2, DT["go"]))
        wp_go += np.where(safety, w_saf, w_fail) * (1 - p_conv) / q
    # ---- field goal
    dist = yl + 17.0
    w_make = 1.0 - wp_fn(_opp(b, ko, sd + 3.0, DT["fg"]))
    miss_yl = np.minimum(80.0, 100.0 - (yl + 7.0))
    w_miss = 1.0 - wp_fn(_opp(b, miss_yl, sd, DT["fg"]))
    wp_fg = np.where(dist <= FG_MAX, p_fg * w_make + (1 - p_fg) * w_miss, np.nan)
    # ---- punt
    wp_punt = np.zeros(n)
    pq = np.asarray(punt_q, float)
    for j in range(pq.shape[1]):
        wp_punt += (1.0 - wp_fn(_opp(b, pq[:, j], sd, DT["punt"]))) / pq.shape[1]
    # a return touchdown: they score, then we receive the kickoff
    w_rtd = wp_fn(_own(b, ko, 1.0, 10.0, sd - td_pts, DT["punt"]))
    pt = np.asarray(punt_td, float)
    wp_punt = (1 - pt) * wp_punt + pt * w_rtd
    out = pd.DataFrame({"wp_go": wp_go, "wp_punt": wp_punt, "wp_fg": wp_fg, "p_conv": p_conv, "p_fg": np.where(dist <= FG_MAX, p_fg, np.nan)})
    W = out[["wp_go", "wp_punt", "wp_fg"]].to_numpy(float)
    Wn = np.where(np.isfinite(W), W, -1.0)
    out["rec"] = np.array(OPTIONS)[np.argmax(Wn, axis=1)]
    out["wp_best"] = Wn.max(axis=1)
    srt = np.sort(Wn, axis=1)
    out["margin"] = srt[:, -1] - srt[:, -2]
    alt = np.where(np.isfinite(W[:, 1:]), W[:, 1:], -1.0).max(axis=1)
    out["go_gain"] = W[:, 0] - alt
    return out


def evaluate_two_point(base: pd.DataFrame, wp_fn, p_pat: np.ndarray, p_two: np.ndarray, ko_yl: np.ndarray) -> pd.DataFrame:
    """WP of kicking the PAT and of going for two from the try (score_differential includes the touchdown)."""
    b = {c: pd.to_numeric(base[c], errors="coerce").to_numpy(float) for c in
         ("yardline_100", "score_differential", "game_seconds_remaining", "half_seconds_remaining", "half",
          "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "pos_spread", "receive_2h_ko", "season")}
    b["pos_spread"] = np.nan_to_num(b["pos_spread"])
    b["receive_2h_ko"] = np.nan_to_num(b["receive_2h_ko"])
    n = len(b["score_differential"])
    sd = b["score_differential"]
    ko = np.asarray(ko_yl, float) * np.ones(n)
    w = {pts: 1.0 - wp_fn(_opp(b, ko, sd + pts, 0.0)) for pts in (0.0, 1.0, 2.0)}
    pk, p2 = np.asarray(p_pat, float) * np.ones(n), np.asarray(p_two, float) * np.ones(n)
    wk = pk * w[1.0] + (1 - pk) * w[0.0]
    w2 = p2 * w[2.0] + (1 - p2) * w[0.0]
    gain = w2 - wk
    return pd.DataFrame({"wp_kick": wk, "wp_two": w2,
                         "rec": np.where(gain > TRY_MARGIN, "two", np.where(gain < -TRY_MARGIN, "kick", "either")),
                         "two_gain": gain})


# ============================================================================ fitting

def _season_rows(season: int, ratings: pd.DataFrame | None = None, d: pd.DataFrame | None = None) -> pd.DataFrame:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame()
    if ratings is not None and len(ratings):
        d = attach_ratings(d, ratings)
    return conv_rows(d)


def all_ratings(seasons: list[int]) -> pd.DataFrame:
    parts = [season_game_epa(s) for s in seasons]
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame(columns=["game_id", "team", "off_r", "def_r"])
    return pregame_ratings(pd.concat(parts, ignore_index=True))


def go_rows(d: pd.DataFrame) -> pd.DataFrame:
    """4th-down decisions (go / punt / FG) with the league go-propensity features."""
    pt = d["play_type"].astype(str)
    dn = pd.to_numeric(d["down"], errors="coerce")
    m = (dn == 4) & pt.isin(["pass", "run", "punt", "field_goal"])
    if "qb_kneel" in d:
        m &= pd.to_numeric(d["qb_kneel"], errors="coerce").fillna(0) == 0
    s = d[m]
    out = pd.DataFrame({c: pd.to_numeric(s[c], errors="coerce").to_numpy(float) for c in
                        ("yardline_100", "ydstogo", "score_differential", "game_seconds_remaining", "half_seconds_remaining")})
    out["half"] = half_of(s["qtr"])
    out["era"] = pd.to_numeric(s["season"], errors="coerce").to_numpy(float)
    out["y"] = s["play_type"].astype(str).isin(["pass", "run"]).astype(float).to_numpy()
    out["season"] = out["era"]
    out["game_id"] = s["game_id"].astype(str).to_numpy()
    return out


def fit(seasons=None, k: int = 5, use_cache: bool = True) -> dict:
    """Conversion model (cross-fitted, 4th-down calibration), gains, league go propensity, kickoff spots,
    two-point rate. Needs wp and kicking fits for grading (`for_season`), not for fitting."""
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("fourth_down", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    ratings = all_ratings(seasons)
    parts, gos, ko, two = [], [], {}, [0.0, 0.0]
    for s in seasons:
        d = _io.plays(s)
        if d is None or not len(d):
            continue
        d = attach_ratings(d, ratings)
        parts.append(conv_rows(d))
        gos.append(go_rows(d))
        v = ko_spots(d)
        if v is not None:
            ko[str(int(s))] = v
        tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1
        r = d.loc[tp, "two_point_conv_result"].astype(str)
        two[0] += float((r == "success").sum())
        two[1] += float(r.isin(["success", "failure"]).sum())
        del d
    c = pd.concat(parts, ignore_index=True)
    conv, oof = fit_conv(c, k)
    g = pd.concat(gos, ignore_index=True)
    gm, _ = _io.fit_full(g[GO_FEATURES], g["y"].to_numpy(float), "binary", GO_PARAMS, rounds=300)
    is4 = c["is4"].to_numpy(float) == 1
    ok = np.isfinite(oof)
    cal4 = _io.calibration(c["y"].to_numpy(float)[is4 & ok], oof[is4 & ok], 10)
    cal4["logloss"] = round(_io.log_loss(c["y"].to_numpy(float)[is4 & ok], oof[is4 & ok]), 5)
    base = float(c["y"].to_numpy(float)[is4 & ok].mean()) if (is4 & ok).any() else float("nan")
    cal4["logloss_base_rate"] = round(_io.log_loss(c["y"].to_numpy(float)[is4 & ok], np.full((is4 & ok).sum(), base)), 5)
    by_togo = {}
    for lo, hi in ((1, 1), (2, 2), (3, 4), (5, 7), (8, 10), (11, 99)):
        m = is4 & ok & (c["ydstogo"].to_numpy(float) >= lo) & (c["ydstogo"].to_numpy(float) <= hi)
        if m.any():
            by_togo[f"{lo}-{hi}"] = {"n": int(m.sum()), "pred": round(float(oof[m].mean()), 4),
                                     "obs": round(float(c["y"].to_numpy(float)[m].mean()), 4)}
    cal4["by_togo"] = by_togo
    p_two = (two[0] + TWO_PT_PRIOR * 100) / (two[1] + 100)
    out = {"ok": True, "version": MODEL_VERSION, "key": key, "seasons": seasons, "n_conv": int(len(c)),
           "conv_best_iter": conv["best_iter"], "conv_importance": conv["importance"], "gains": fit_gains(c),
           "ko_yl": ko, "two_pt_rate": p_two, "n_two": int(two[1]), "calibration_4th": cal4,
           "models": {"conv": conv["model"], "go": gm}}
    _io.store_fit("fourth_down", out)
    del c, g, oof
    return out


def current_fit() -> dict | None:
    return _io.get_fit("fourth_down", MODEL_VERSION)


# ============================================================================ grading a season

def _base_frame(s: pd.DataFrame) -> pd.DataFrame:
    b = pd.DataFrame({c: pd.to_numeric(s[c], errors="coerce").to_numpy(float) for c in
                      ("yardline_100", "ydstogo", "score_differential", "game_seconds_remaining", "half_seconds_remaining",
                       "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "pos_spread", "season")})
    b["half"] = half_of(s["qtr"])
    b["receive_2h_ko"] = s["receive_2h_ko"].to_numpy(float)
    return b


def grade_season(season: int, d: pd.DataFrame | None = None, fits: dict | None = None) -> dict:
    """Every 4th down and try of the season with WP by option, recommendation and WP lost; coach and team
    tables. `fits` = {"fourth", "wp", "kick"} (current fits by default)."""
    fits = fits or {"fourth": current_fit(), "wp": wpm.current_fit(), "kick": kicking.current_fit()}
    f4, fw, fk = fits.get("fourth"), fits.get("wp"), fits.get("kick")
    if not (f4 and fw and fk):
        return {"ok": False, "reason": "missing fits"}
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return {"ok": False, "reason": "no plays"}
    d = d.sort_values(["game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    d["receive_2h_ko"] = wpm.receive_2h_ko(d)
    prev = [s for s in (season - 1, season) if _io.release_path("pbp", s) is not None or s == season]
    rt = all_ratings(prev) if d is None or "off_r" not in d else None
    if rt is not None and len(rt):
        d = attach_ratings(d, rt)
    wp_fn = _wp_fn(fw)
    ko = (f4.get("ko_yl") or {}).get(str(int(season))) or default_ko(int(season))
    p_pat = kicking.pat_prob(fk, int(season))
    # ---- 4th downs
    g = go_rows(d)
    pt = d["play_type"].astype(str)
    dn = pd.to_numeric(d["down"], errors="coerce")
    m = (dn == 4) & pt.isin(["pass", "run", "punt", "field_goal"])
    if "qb_kneel" in d:
        m &= pd.to_numeric(d["qb_kneel"], errors="coerce").fillna(0) == 0
    s = d[m].reset_index(drop=True)
    res = {"ok": True, "season": int(season)}
    if len(s):
        base = _base_frame(s)
        cx = pd.DataFrame({"ydstogo": base["ydstogo"], "yardline_100": base["yardline_100"],
                           "goal_to_go": pd.to_numeric(s["goal_to_go"], errors="coerce").to_numpy(float),
                           "is4": 1.0, "off_r": s["off_r"].to_numpy(float) if "off_r" in s else np.nan,
                           "def_r": s["def_r"].to_numpy(float) if "def_r" in s else np.nan,
                           "era": base["season"], "indoor": pd.to_numeric(s.get("indoor"), errors="coerce").to_numpy(float)})
        p_conv = conv_prob(f4, cx)
        kick_team = _team_kickers(d)
        kid = s["posteam"].map(kick_team).to_numpy(object)
        p_fg = kicking.fg_prob(fk["fg"], base["yardline_100"].to_numpy() + 17.0, base["season"].to_numpy(),
                               pd.to_numeric(s["wind"], errors="coerce").to_numpy(float),
                               pd.to_numeric(s["temp"], errors="coerce").to_numpy(float),
                               pd.to_numeric(s.get("indoor"), errors="coerce").to_numpy(float),
                               pd.to_numeric(s.get("altitude"), errors="coerce").to_numpy(float), kid)
        pq, ptd = kicking.punt_outcomes(fk["punt"], base["yardline_100"])
        ev = evaluate(base, wp_fn, p_conv, p_fg, f4["gains"], pq, ptd, ko, p_pat)
        choice = np.where(s["play_type"].astype(str).isin(["pass", "run"]), "go",
                          np.where(s["play_type"].astype(str) == "punt", "punt", "fg"))
        W = ev[["wp_go", "wp_punt", "wp_fg"]].to_numpy(float)
        ci = np.array([OPTIONS.index(c) for c in choice])
        wchosen = W[np.arange(len(ci)), ci]
        ev["choice"] = choice
        ev["wp_chosen"] = wchosen
        best = ev["wp_best"].to_numpy(float)
        ev["wp_lost"] = np.clip(best - np.where(np.isfinite(wchosen), wchosen, best), 0, None)
        ev["exp_go"] = _io.lgb_predict(f4["models"]["go"], g[GO_FEATURES]) if len(g) == len(s) else np.nan
        coach = np.where(s["home"].to_numpy(float) == 1, s["home_coach"].astype(object), s["away_coach"].astype(object))
        info = pd.DataFrame({"game_id": s["game_id"].astype(str), "play_id": s["play_id"].to_numpy(float),
                             "week": pd.to_numeric(s["week"], errors="coerce").to_numpy(float), "posteam": s["posteam"],
                             "defteam": s["defteam"], "coach": coach, "qtr": pd.to_numeric(s["qtr"], errors="coerce").to_numpy(float),
                             "game_seconds_remaining": base["game_seconds_remaining"], "ydstogo": base["ydstogo"],
                             "yardline_100": base["yardline_100"], "score_differential": base["score_differential"],
                             "wp_before": pd.to_numeric(s.get("wp"), errors="coerce").to_numpy(float)})
        dec = pd.concat([info, ev], axis=1)
        dec["wp_now"] = wp_fn(_own_now(base))
        # overtime is listed but not graded: the WP model sees few OT states and not the OT possession rules
        dec["graded"] = dec["qtr"].to_numpy(float) <= 4
        res["decisions"] = dec
        res["coaches"] = _grades(dec, "coach")
        res["teams"] = _grades(dec, "posteam")
    # ---- tries
    tp = (pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1) | (pt == "extra_point")
    t = d[tp].reset_index(drop=True)
    if len(t):
        bt = _base_frame(t)
        p_two = float(f4.get("two_pt_rate") or TWO_PT_PRIOR)
        e2 = evaluate_two_point(bt, wp_fn, p_pat, p_two, ko)
        went = (pd.to_numeric(t.get("two_point_attempt"), errors="coerce").fillna(0) == 1).to_numpy()
        e2["choice"] = np.where(went, "two", "kick")
        lost = np.where(went, np.clip(e2["wp_kick"] - e2["wp_two"], 0, None), np.clip(e2["wp_two"] - e2["wp_kick"], 0, None))
        e2["wp_lost"] = np.where(e2["rec"] == "either", 0.0, lost)
        coach = np.where(t["home"].to_numpy(float) == 1, t["home_coach"].astype(object), t["away_coach"].astype(object))
        e2 = pd.concat([pd.DataFrame({"game_id": t["game_id"].astype(str), "play_id": t["play_id"].to_numpy(float),
                                      "posteam": t["posteam"], "coach": coach,
                                      "score_differential": bt["score_differential"],
                                      "game_seconds_remaining": bt["game_seconds_remaining"]}), e2], axis=1)
        res["tries"] = e2
    return res


def _own_now(base: pd.DataFrame) -> pd.DataFrame:
    x = base.copy()
    x["down"] = 4.0
    return x[[c for c in wpm.FEATURES if c in x] + [c for c in ("season",) if c in x]]


def _wp_fn(fw: dict):
    """A WP callable for evaluate(): a small object, not a closure over arrays."""
    return _WP(fw)


class _WP:
    __slots__ = ("fit",)

    def __init__(self, fit: dict):
        self.fit = fit

    def __call__(self, states: pd.DataFrame) -> np.ndarray:
        return wpm.state_wp(self.fit, wpm.features(states))


def _team_kickers(d: pd.DataFrame) -> dict:
    k = d[d["play_type"].astype(str).isin(["field_goal", "extra_point"]) & d["kicker_player_id"].notna()]
    if not len(k):
        return {}
    return k.groupby("posteam")["kicker_player_id"].agg(lambda s: s.value_counts().index[0]).to_dict()


def _grades(dec: pd.DataFrame, by: str) -> pd.DataFrame:
    x = dec[dec[by].notna() & (dec["graded"] if "graded" in dec else True)].copy()
    x["went"] = (x["choice"] == "go").astype(float)
    x["should_go"] = (x["go_gain"] > RECOMMEND_MARGIN).astype(float)
    x["went_when_should"] = np.where(x["should_go"] == 1, x["went"], np.nan)
    x["kicked_when_should_go"] = np.where(x["should_go"] == 1, 1 - x["went"], np.nan)
    x["agree"] = (x["choice"] == x["rec"]).astype(float)
    g = x.groupby(by).agg(n=("went", "size"), go=("went", "sum"), exp_go=("exp_go", "sum"), wp_lost=("wp_lost", "sum"),
                          should_go=("should_go", "sum"), went_when_should=("went_when_should", "mean"),
                          agree=("agree", "mean"), go_gain_taken=("go_gain", lambda s: float(np.nansum(np.clip(s, 0, None)))))
    g["go_rate"] = g["go"] / g["n"]
    g["go_oe_per100"] = 100.0 * (g["go"] - g["exp_go"]) / g["n"]
    g["wp_lost_per_game"] = g["wp_lost"] / x.groupby(by)["game_id"].nunique()
    return g.reset_index().sort_values("go_oe_per100", ascending=False).reset_index(drop=True)


def for_season(season: int, use_cache: bool = True) -> dict:
    """Payload-ready records: decisions, tries, coach and team tables, plus the season summary."""
    fits = {"fourth": current_fit(), "wp": wpm.current_fit(), "kick": kicking.current_fit()}
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, *[(f or {}).get("key") for f in fits.values()])

    def build():
        r = grade_season(season, fits=fits)
        if not r.get("ok"):
            return r
        out = {"ok": True, "season": int(season)}
        for k in ("decisions", "tries", "coaches", "teams"):
            if k in r:
                out[k] = _io.clean(r[k].to_dict("records"), 4)
        return out
    return _io.cached("fourth_down", str(int(season)), key, build, use_cache, gz=True)


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("fourth_down", f)
    return {k: v for k, v in f.items() if k != "models"}
