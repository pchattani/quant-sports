"""
Award races: MVP, OPOY, DPOY, OROY, DROY, CPOY and Coach of the Year.

Data per player-season (regular season, from play-by-play; `player_seasons`, cached per season)
    offence: dropbacks, passing EPA / yards / TDs / interceptions, rushing attempts / EPA / yards / TDs, targets,
             receiving EPA / yards / TDs, games;  value = passing EPA + rushing EPA + receiving EPA / 2
             (builder B's player value replaces it when `player_value.season_values(season)` exists)
    defence: sacks (half sacks 0.5), QB hits, interceptions, forced fumbles, tackles for loss, passes defended, solo and
             assisted tackles;  def_score = sacks + 1.5 INT + FF + 0.5 TFL + 0.3 PD + 0.25 QB hits
    names and positions from nflverse depth charts (gsis_id -> full name); rookie = first season the id appears in
    play-by-play (1999 onward) or depth charts; team = the club with most of his plays.
Team context: win percentage, the conference #1 seed (tiebreak.Table on the final standings), points margin.

Model: conditional logit per award (one winner per season among the candidates):
    P(i wins | season) = exp(beta . z_i) / sum_j exp(beta . z_j),
z = features standardised within the season's candidate pool; beta by maximum likelihood with a ridge (0.3), fitted
on the verified winners 2006-2025 (`award_winners`). Candidate pools and features:
    mvp   QBs with >= 200 dropbacks and skill players (top 20 by value, 10 by scrimmage yards, 10 by TDs): value, passing
          EPA, team win %, #1 seed, QB
    opoy  top 30 by value, 20 by scrimmage yards, 15 by TDs: value, scrimmage yards, total TDs, team win %, QB
    dpoy  top 50 by def_score, 20 by tackles, 20 by PD + 2 INT: sacks, INT, FF, TFL, PD, QB hits, tackles, team
          points allowed per game (negated)
    oroy  rookies (top 20 by value, 15 by scrimmage yards, 10 by TDs): value, scrimmage yards, total TDs, team win %, QB
    droy  rookies (top 30 by def_score + tackles / 20, 10 by tackles, 10 by PD + 2 INT): sacks, INT, TFL, PD, tackles, FF
    cpoy  offensive players (top 100 by value, 30 by scrimmage yards): value, value change from last season, games
          missed last season, QB, value two seasons ago (defensive comebacks, 2 of 20 winners, are not modelled)
    coty  head coaches (most games for a club): win %, change in win % from last season, wins above the preseason
          expectation (team_strength prior net * 0.028 + 0.5, times games), #1 seed
In season, counting stats are projected to a full season (x games / games played) and team win % uses the season
simulation's expected wins; the logits are tempered by (0.35 + 0.65 * share of the season played) so early-season
odds are not overconfident.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import award_winners as AW

logger = logging.getLogger(__name__)

VERSION = 1
AWARDS = ("mvp", "opoy", "dpoy", "oroy", "droy", "cpoy", "coty")
FEATURES = {
    "mvp": ["value", "pass_epa", "team_wp", "top_seed", "is_qb"],
    "opoy": ["value", "scrim_yds", "tds", "team_wp", "is_qb"],
    "dpoy": ["sacks", "ints_def", "ff", "tfl", "pd", "qb_hits", "tackles", "team_def"],
    "oroy": ["value", "scrim_yds", "tds", "team_wp", "is_qb"],
    "droy": ["sacks", "ints_def", "tfl", "pd", "tackles", "ff"],
    "cpoy": ["value", "value_delta", "missed_last", "is_qb", "value_prev2"],
    "coty": ["team_wp", "wp_delta", "wins_over_exp", "top_seed"],
}
RIDGE = 0.3
PB_COLS = ["game_id", "season", "season_type", "posteam", "defteam", "play_type", "epa", "qb_dropback",
           "passer_player_id", "rusher_player_id", "receiver_player_id", "passing_yards", "rushing_yards",
           "receiving_yards", "pass_touchdown", "rush_touchdown", "interception", "interception_player_id",
           "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id",
           "forced_fumble_player_1_player_id", "forced_fumble_player_2_player_id", "tackle_for_loss_1_player_id",
           "tackle_for_loss_2_player_id", "pass_defense_1_player_id", "pass_defense_2_player_id",
           "solo_tackle_1_player_id", "solo_tackle_2_player_id", "assist_tackle_1_player_id", "assist_tackle_2_player_id",
           "tackle_with_assist_1_player_id", "tackle_with_assist_2_player_id", "qb_spike", "qb_kneel", "two_point_attempt"]


# ── names ────────────────────────────────────────────────────────────────────

def fold(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace(".", " ").replace("'", "").replace("-", " ")
    toks = [t for t in s.split() if t not in ("jr", "sr", "ii", "iii", "iv", "v")]
    # "j j watt" -> "jj watt"
    out = []
    for t in toks:
        if out and len(t) == 1 and len(out[-1]) == 1:
            out[-1] = out[-1] + t
        else:
            out.append(t)
    return " ".join(out)


def names(seasons: list[int] | None = None) -> pd.DataFrame:
    """gsis_id -> full_name, position (most common), first season seen, from the depth charts on disk."""
    path = D.c_cache() / "player_names.parquet"
    base = D.raw_root() / "raw" / "depth_charts"
    files = sorted(base.glob("depth_charts_*.parquet")) if base.exists() else []
    newest = max((f.stat().st_mtime for f in files), default=0)
    if path.exists() and path.stat().st_mtime >= newest:
        return pd.read_parquet(path)
    rows = []
    for f in files:
        try:
            s = int(f.stem.rsplit("_", 1)[-1])
        except ValueError:
            continue
        d = pd.read_parquet(f)
        if "full_name" in d:
            x = pd.DataFrame({"gsis_id": d["gsis_id"], "name": d["full_name"], "pos": d.get("position"),
                              "team": d.get("club_code"), "season": s})
        elif "player_name" in d:
            x = pd.DataFrame({"gsis_id": d["gsis_id"], "name": d["player_name"], "pos": d.get("pos_abb"),
                              "team": d.get("team"), "season": s})
        else:
            continue
        rows.append(x.dropna(subset=["gsis_id"]).drop_duplicates(["gsis_id", "pos", "team"]))
        del d
    if not rows:
        return pd.DataFrame(columns=["gsis_id", "name", "pos", "first_dc"])
    a = pd.concat(rows, ignore_index=True)
    a["pos"] = a["pos"].astype(str).str.upper().str.replace(r"^[LR](?=(DE|DT|CB|OLB|ILB|G|T)$)", "", regex=True)
    nm = a.groupby("gsis_id").agg(name=("name", "last"), pos=("pos", lambda s: s.value_counts().index[0]),
                                  first_dc=("season", "min")).reset_index()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        nm.to_parquet(path, index=False)
    except OSError:
        pass
    return nm


def qb_starters(season: int) -> dict[str, str]:
    """{team: gsis_id} of the QB1 in the latest depth-chart snapshot of the season (in-season files only)."""
    f = D.raw_root() / "raw" / "depth_charts" / f"depth_charts_{season}.parquet"
    if not f.exists():
        return {}
    d = pd.read_parquet(f)
    if "pos_abb" in d:
        q = d[(d["pos_abb"].astype(str) == "QB") & (pd.to_numeric(d["pos_rank"], errors="coerce") == 1)]
        if "dt" in q and len(q):
            q = q[q["dt"] == q["dt"].max()]
        return {str(t): str(g) for t, g in zip(q["team"], q["gsis_id"]) if isinstance(g, str)}
    q = d[(d["position"].astype(str) == "QB") & (pd.to_numeric(d["depth_team"], errors="coerce") == 1)]
    if "week" in q and len(q):
        q = q[q["week"] == q["week"].max()]
    return {str(t): str(g) for t, g in zip(q["club_code"], q["gsis_id"]) if isinstance(g, str)}


# ── player seasons ───────────────────────────────────────────────────────────

def _count(series_list, weights=None) -> pd.Series:
    parts = []
    for k, s in enumerate(series_list):
        s = s.dropna()
        parts.append(pd.Series(weights[k] if weights else 1.0, index=s.values))
    if not parts:
        return pd.Series(dtype=float)
    c = pd.concat(parts)
    return c.groupby(level=0).sum()


def player_seasons_from_pbp(d: pd.DataFrame) -> pd.DataFrame:
    if "season_type" in d:
        d = d[d["season_type"].astype(str).str.upper() == "REG"]
    epa = pd.to_numeric(d["epa"], errors="coerce").fillna(0.0)
    two = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) > 0
    dk = (pd.to_numeric(d.get("qb_spike"), errors="coerce").fillna(0) > 0) | (pd.to_numeric(d.get("qb_kneel"), errors="coerce").fillna(0) > 0)
    ok = ~two & ~dk
    drop = (pd.to_numeric(d["qb_dropback"], errors="coerce").fillna(0) > 0) & ok
    P = d[drop & d["passer_player_id"].notna()]
    out = {}
    g = P.groupby("passer_player_id")
    out["dropbacks"] = g.size()
    out["pass_epa"] = epa[P.index].groupby(P["passer_player_id"]).sum()
    out["pass_yds"] = g["passing_yards"].sum()
    out["pass_td"] = g["pass_touchdown"].sum()
    out["ints"] = g["interception"].sum()
    Rr = d[ok & d["rusher_player_id"].notna() & (d["play_type"].astype(str) == "run")]
    gr = Rr.groupby("rusher_player_id")
    out["rushes"] = gr.size()
    out["rush_epa"] = epa[Rr.index].groupby(Rr["rusher_player_id"]).sum()
    out["rush_yds"] = gr["rushing_yards"].sum()
    out["rush_td"] = gr["rush_touchdown"].sum()
    Rc = d[ok & d["receiver_player_id"].notna()]
    gc = Rc.groupby("receiver_player_id")
    out["targets"] = gc.size()
    out["rec_epa"] = epa[Rc.index].groupby(Rc["receiver_player_id"]).sum()
    out["rec_yds"] = gc["receiving_yards"].sum()
    out["rec_td"] = gc["pass_touchdown"].sum()
    out["sacks"] = _count([d["sack_player_id"], d["half_sack_1_player_id"], d["half_sack_2_player_id"]], [1.0, 0.5, 0.5])
    out["qb_hits"] = _count([d["qb_hit_1_player_id"], d["qb_hit_2_player_id"]])
    out["ints_def"] = _count([d["interception_player_id"]])
    out["ff"] = _count([d["forced_fumble_player_1_player_id"], d["forced_fumble_player_2_player_id"]])
    out["tfl"] = _count([d["tackle_for_loss_1_player_id"], d["tackle_for_loss_2_player_id"]])
    out["pd"] = _count([d["pass_defense_1_player_id"], d["pass_defense_2_player_id"]])
    out["tackles"] = _count([d["solo_tackle_1_player_id"], d["solo_tackle_2_player_id"], d["assist_tackle_1_player_id"],
                             d["assist_tackle_2_player_id"], d["tackle_with_assist_1_player_id"],
                             d["tackle_with_assist_2_player_id"]], [1, 1, 0.5, 0.5, 1, 1])
    df = pd.DataFrame(out).fillna(0.0)
    df.index.name = "gsis_id"
    # team and games: offence from possession plays, defence from the defending side
    team_rows, game_rows = [], []
    for col, side in (("passer_player_id", "posteam"), ("rusher_player_id", "posteam"), ("receiver_player_id", "posteam"),
                      ("solo_tackle_1_player_id", "defteam"), ("assist_tackle_1_player_id", "defteam"),
                      ("sack_player_id", "defteam"), ("pass_defense_1_player_id", "defteam")):
        x = d[[col, side, "game_id"]].dropna(subset=[col])
        x.columns = ["gsis_id", "team", "game_id"]
        team_rows.append(x)
    tr = pd.concat(team_rows)
    df["team"] = tr.groupby("gsis_id")["team"].agg(lambda s: s.value_counts().index[0])
    df["games"] = tr.groupby("gsis_id")["game_id"].nunique()
    df["team_games"] = df["team"].map(d.groupby("posteam")["game_id"].nunique())
    df["value"] = df["pass_epa"] + df["rush_epa"] + 0.5 * df["rec_epa"]
    df["scrim_yds"] = df["rush_yds"] + df["rec_yds"]
    df["tds"] = df["pass_td"] * 0.5 + df["rush_td"] + df["rec_td"]
    df["def_score"] = df["sacks"] + 1.5 * df["ints_def"] + df["ff"] + 0.5 * df["tfl"] + 0.3 * df["pd"] + 0.25 * df["qb_hits"]
    return df.reset_index()


def player_seasons(season: int, refresh: bool = False) -> pd.DataFrame:
    path = D.c_cache() / f"players_{int(season)}.parquet"
    src = D.pbp_path(season)
    if path.exists() and not refresh and (src is None or path.stat().st_mtime >= src.stat().st_mtime):
        return pd.read_parquet(path)
    d = D.load_pbp(season, PB_COLS)
    if d is None or d.empty:
        return pd.DataFrame()
    out = player_seasons_from_pbp(d)
    out["season"] = int(season)
    del d
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
    except OSError:
        pass
    return out


def _b_values(season: int) -> pd.Series | None:
    """Builder B's season player value (gsis_id -> value), when available."""
    try:
        from oddsmarkets.nfl.models import player_value as PV
        f = getattr(PV, "season_values", None)
        if callable(f):
            v = f(season)
            if isinstance(v, pd.Series) and len(v):
                return v
            if isinstance(v, pd.DataFrame) and len(v) and {"gsis_id", "value"} <= set(v.columns):
                return v.set_index("gsis_id")["value"]
            if isinstance(v, dict) and v:
                return pd.Series(v)
    except Exception:  # noqa: BLE001
        pass
    return None


# ── team context ─────────────────────────────────────────────────────────────

def team_context(season: int, games: pd.DataFrame, exp_wp: dict | None = None) -> pd.DataFrame:
    g = games[(games["season"] == season) & (games["gtype"] == "REG") & games["played"].astype(bool)]
    rows = {}
    for r in g.itertuples(index=False):
        for t, pf, pa in ((r.home, r.hs, r.as_), (r.away, r.as_, r.hs)):
            x = rows.setdefault(t, {"w": 0.0, "n": 0, "pf": 0.0, "pa": 0.0})
            x["n"] += 1
            x["w"] += 1.0 if pf > pa else (0.5 if pf == pa else 0.0)
            x["pf"] += pf
            x["pa"] += pa
    df = pd.DataFrame(rows).T
    if df.empty:
        return pd.DataFrame(columns=["team_wp", "top_seed", "team_def", "games"])
    df["team_wp"] = df["w"] / df["n"].clip(lower=1)
    if exp_wp:
        df["team_wp"] = [exp_wp.get(t, v) for t, v in zip(df.index, df["team_wp"])]
    df["team_def"] = -(df["pa"] / df["n"].clip(lower=1))
    df["top_seed"] = 0.0
    try:
        from oddsmarkets.nfl import tiebreak as TB
        rows_ = [{"home": r.home, "away": r.away, "hs": r.hs, "as": r.as_, "gtype": "REG"} for r in g.itertuples(index=False)]
        seeds = TB.Table(rows_, season).seeds()
        for c in seeds.values():
            if c["seeds"]:
                df.loc[c["seeds"][0], "top_seed"] = 1.0
    except Exception as exc:  # noqa: BLE001
        logger.info("awards: seeds unavailable (%s)", exc)
    df["games"] = df["n"]
    return df


def coaches(season: int, games: pd.DataFrame) -> dict[str, str]:
    g = games[(games["season"] == season) & (games["gtype"] == "REG")]
    rows = pd.concat([pd.DataFrame({"team": g["home"], "coach": g["home_coach"]}),
                      pd.DataFrame({"team": g["away"], "coach": g["away_coach"]})]).dropna()
    if rows.empty:
        return {}
    return {t: s.value_counts().index[0] for t, s in rows.groupby("team")["coach"]}


# ── candidate tables ─────────────────────────────────────────────────────────

def _first_seen(nm: pd.DataFrame, upto: int) -> dict:
    """gsis -> first season seen in pbp player tables (cached player_seasons) or depth charts."""
    first = dict(zip(nm["gsis_id"], nm["first_dc"])) if len(nm) else {}
    for s in range(1999, upto + 1):
        p = D.c_cache() / f"players_{s}.parquet"
        if not p.exists():
            continue
        ids = pd.read_parquet(p, columns=["gsis_id"])["gsis_id"]
        for i in ids:
            if i not in first or first[i] > s:
                first[i] = s
    return first


def candidates(award: str, season: int, games: pd.DataFrame, nm: pd.DataFrame, first: dict,
               exp_wp: dict | None = None, frac: float = 1.0, prior_net: dict | None = None) -> pd.DataFrame:
    tc = team_context(season, games, exp_wp)
    if award == "coty":
        co = coaches(season, games)
        prev = team_context(season - 1, games)
        rows = []
        for t, c in co.items():
            if t not in tc.index:
                continue
            wp = float(tc.loc[t, "team_wp"])
            pwp = float(prev.loc[D.franchise(t), "team_wp"]) if D.franchise(t) in prev.index else (
                float(prev.loc[t, "team_wp"]) if t in prev.index else 0.5)
            exp = 0.5 + 0.028 * float((prior_net or {}).get(t, 0.0))
            rows.append({"id": f"coach:{c}", "name": c, "team": t, "pos": "HC", "team_wp": wp, "wp_delta": wp - pwp,
                         "wins_over_exp": (wp - exp) * 17, "top_seed": float(tc.loc[t, "top_seed"])})
        return pd.DataFrame(rows)
    ps = player_seasons(season)
    if ps.empty:
        return pd.DataFrame()
    bv = _b_values(season)
    if bv is not None:
        ps["value"] = ps["gsis_id"].map(bv).fillna(ps["value"])
    if frac < 1.0:
        scale = 1.0 / max(frac, 0.15)
        for c in ("value", "pass_epa", "scrim_yds", "tds", "sacks", "ints_def", "ff", "tfl", "pd", "qb_hits", "tackles",
                  "def_score"):
            ps[c] = ps[c] * scale
    nmi = nm.set_index("gsis_id") if len(nm) else pd.DataFrame()
    ps["name"] = ps["gsis_id"].map(nmi["name"]) if len(nmi) else None
    ps["pos"] = ps["gsis_id"].map(nmi["pos"]) if len(nmi) else None
    ps["rookie"] = ps["gsis_id"].map(lambda i: first.get(i) == season)
    ps["team_wp"] = ps["team"].map(tc["team_wp"]).fillna(0.5)
    ps["top_seed"] = ps["team"].map(tc["top_seed"]).fillna(0.0)
    ps["team_def"] = ps["team"].map(tc["team_def"]).fillna(tc["team_def"].mean() if len(tc) else 0.0)
    ps["is_qb"] = (ps["dropbacks"] >= 150).astype(float)
    ps["id"] = ps["gsis_id"]
    if award in ("mvp", "opoy", "oroy", "cpoy"):
        pool = ps[(ps["dropbacks"] >= 100 * min(frac, 1.0)) | (ps["rushes"] + ps["targets"] >= 60 * min(frac, 1.0))]
        if award == "oroy":
            pool = pool[pool["rookie"]]
            return _union(pool, [("value", 20), ("scrim_yds", 15), ("tds", 10)])
        if award == "mvp":
            qb = pool[pool["dropbacks"] >= 200 * min(frac, 1.0)]
            sk = _union(pool[pool["dropbacks"] < 100], [("value", 20), ("scrim_yds", 10), ("tds", 10)])
            return pd.concat([qb, sk]).drop_duplicates("gsis_id")
        if award == "cpoy":
            prev = player_seasons(season - 1)
            prev2 = player_seasons(season - 2)
            if prev.empty:
                return pd.DataFrame()
            pv = prev.set_index("gsis_id")
            pv2 = prev2.set_index("gsis_id") if len(prev2) else pd.DataFrame(columns=["value", "games"])
            pool = _union(pool, [("value", 100), ("scrim_yds", 30)]).copy()
            pool["value_last"] = pool["gsis_id"].map(pv["value"]).fillna(0.0)
            pool["games_last"] = pool["gsis_id"].map(pv["games"]).fillna(0.0)
            pool["value_prev2"] = pool["gsis_id"].map(pv2["value"]).fillna(0.0) if len(pv2) else 0.0
            pool["value_delta"] = pool["value"] - pool["value_last"]
            pool["missed_last"] = (17 - pool["games_last"]).clip(lower=0)
            return pool
        return _union(pool, [("value", 30), ("scrim_yds", 20), ("tds", 15)])
    dfp = ps[(ps["tackles"] + ps["sacks"] + ps["pd"]) > 5 * min(frac, 1.0)].copy()
    dfp["cov"] = dfp["pd"] + 2 * dfp["ints_def"]
    if award == "dpoy":
        return _union(dfp, [("def_score", 50), ("tackles", 20), ("cov", 20)])
    if award == "droy":
        dfp = dfp[dfp["rookie"]].copy()
        dfp["k"] = dfp["def_score"] + dfp["tackles"] / 20.0
        return _union(dfp, [("k", 30), ("tackles", 10), ("cov", 10)])
    raise KeyError(award)


def _union(df: pd.DataFrame, picks: list[tuple[str, int]]) -> pd.DataFrame:
    parts = [df.nlargest(n, col) for col, n in picks if col in df]
    return pd.concat(parts).drop_duplicates("gsis_id") if parts else df.head(0)


def winner_index(award: str, season: int, cand: pd.DataFrame) -> int | None:
    w = AW.WINNERS.get(award, {}).get(season)
    if not w or cand.empty:
        return None
    name, team, _pos = w
    if award == "coty":
        lab = AW.INTERIM_TEAM_LABEL.get((award, season))
        m = cand["team"] == (lab or team) if lab else cand["name"].map(fold) == fold(name)
        hit = np.nonzero(m.to_numpy())[0]
        if len(hit) == 0:
            hit = np.nonzero((cand["team"] == team).to_numpy())[0]
        return int(hit[0]) if len(hit) else None
    f = cand["name"].fillna("").map(fold).to_numpy()
    key = fold(name)
    hit = np.nonzero(f == key)[0]
    if len(hit) > 1:
        hit = [h for h in hit if D.franchise(cand.iloc[h]["team"]) == D.franchise(team)] or list(hit)
    if len(hit) == 0:
        last = key.split()[-1]
        hit = [i for i, x in enumerate(f) if x.split()[-1:] == [last] and D.franchise(cand.iloc[i]["team"]) == D.franchise(team)]
    return int(hit[0]) if len(hit) else None


# ── conditional logit ────────────────────────────────────────────────────────

def _z(X: np.ndarray) -> np.ndarray:
    mu = X.mean(0)
    sd = X.std(0)
    return (X - mu) / np.where(sd > 1e-9, sd, 1.0)


def fit_clogit(groups: list[tuple[np.ndarray, int]], ridge: float = RIDGE) -> np.ndarray:
    from scipy.optimize import minimize
    k = groups[0][0].shape[1]

    def f(b):
        ll, g = 0.0, np.zeros(k)
        for X, y in groups:
            u = X @ b
            u -= u.max()
            e = np.exp(u)
            p = e / e.sum()
            ll += u[y] - math.log(e.sum())
            g += X[y] - p @ X
        return -ll + ridge * b @ b, -g + 2 * ridge * b
    r = minimize(f, np.zeros(k), jac=True, method="L-BFGS-B")
    return r.x


def fit(seasons: list[int] | None = None, games: pd.DataFrame | None = None) -> dict:
    """Coefficients per award on the verified winners; in-sample log-likelihood and the winner's rank per season."""
    seasons = seasons or list(range(2006, 2026))
    games = games if games is not None else D.games_frame(range(min(seasons) - 1, max(seasons) + 1))
    nm = names()
    first = _first_seen(nm, max(seasons))
    out = {"version": VERSION, "awards": {}}
    for aw in AWARDS:
        groups, miss, ranks = [], [], {}
        for s in seasons:
            c = candidates(aw, s, games, nm, first)
            if c.empty:
                miss.append(s)
                continue
            y = winner_index(aw, s, c)
            if y is None:
                miss.append(s)
                continue
            X = _z(c[FEATURES[aw]].to_numpy(float))
            groups.append((X, y))
        if len(groups) < 6:
            out["awards"][aw] = {"ok": False, "missing": miss}
            continue
        b = fit_clogit(groups)
        ll, top1 = 0.0, 0
        for X, y in groups:
            u = X @ b
            p = np.exp(u - u.max())
            p /= p.sum()
            ll += math.log(max(p[y], 1e-12))
            top1 += int(np.argmax(p) == y)
        out["awards"][aw] = {"ok": True, "features": FEATURES[aw], "beta": b.tolist(), "n_seasons": len(groups),
                             "missing": miss, "loglik": ll, "top1": top1}
    return out


def save(fitd: dict, committed: bool = False) -> None:
    D.write_json(D.c_cache() / "awards_fit.json", fitd)
    if committed:
        D.write_json(D.FITTED / "awards_fit.json", fitd)


def load_fit() -> dict | None:
    return D.read_json(D.c_cache() / "awards_fit.json") or D.read_json(D.FITTED / "awards_fit.json")


def predict(season: int, games: pd.DataFrame | None = None, exp_wins: dict | None = None, fitd: dict | None = None,
            prior_net: dict | None = None, top: int = 15) -> dict:
    """{award: [{"id","name","team","pos","p"}]} for a season in progress (or complete)."""
    fitd = fitd or load_fit()
    if not fitd:
        return {}
    games = games if games is not None else D.games_frame([season - 2, season - 1, season])
    reg = games[(games["season"] == season) & (games["gtype"] == "REG")]
    n_total = max(int(len(reg)) * 2 / 32.0, 1.0)
    played_g = float(reg["played"].sum()) * 2 / 32.0
    frac = min(1.0, max(played_g / n_total, 0.0)) if n_total else 1.0
    exp_wp = {t: w / 17.0 for t, w in (exp_wins or {}).items()} if exp_wins else None
    nm = names()
    first = _first_seen(nm, season)
    out = {"season": season, "share_played": round(frac, 3)}
    temper = 0.35 + 0.65 * frac
    for aw in AWARDS:
        a = (fitd.get("awards") or {}).get(aw) or {}
        if not a.get("ok"):
            continue
        c = candidates(aw, season, games, nm, first, exp_wp, frac if frac < 1 else 1.0, prior_net)
        if c.empty:
            continue
        X = _z(c[a["features"]].to_numpy(float))
        u = temper * (X @ np.asarray(a["beta"]))
        p = np.exp(u - u.max())
        p /= p.sum()
        c = c.assign(p=p).sort_values("p", ascending=False).head(top)
        out[aw] = [{"id": str(r.id), "name": (r.name if isinstance(r.name, str) else str(r.id)), "team": r.team,
                    "pos": getattr(r, "pos", None), "p": round(float(r.p), 4)} for r in c.itertuples(index=False)]
    return out


def compare_markets(pred: dict, futures: dict) -> dict:
    """{award: [{"name","model","market","edge"}]} matching market runners (by folded name) to model candidates."""
    from oddsmarkets.common import prediction_markets as cpm
    out = {}
    for aw in AWARDS:
        rows = pred.get(aw) or []
        t = ((futures or {}).get("awards") or {}).get(aw) or {}
        probs = t.get("probs") or {}
        names_m = {str(k): v for k, v in probs.items()}
        labels = {k: (k.split(":", 1)[1] if k.startswith("name:") else k) for k in names_m}
        res = []
        used = set()
        for r in rows:
            nmatch = cpm.best_match(r["name"], [labels[k] for k in names_m], floor=0.85) if names_m else None
            key = next((k for k in names_m if labels[k] == nmatch), None) if nmatch else None
            if key:
                used.add(key)
            q = names_m.get(key) if key else None
            res.append({"name": r["name"], "team": r["team"], "model": r["p"], "market": q,
                        "edge": round(r["p"] / q - 1, 4) if q else None})
        for k, q in names_m.items():
            if k not in used and q >= 0.02:
                res.append({"name": labels[k], "team": None, "model": None, "market": q, "edge": None})
        out[aw] = res
    return out
