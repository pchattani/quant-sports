"""
Walk-forward feature rows at explicit decision times (docs/research/EDGE_PROTOCOL.md section 2).

For every game the production ratings (team_strength.fit, chained preseason priors) are attached three times:

    close   ratings fitted on the season's games dated before the game's week; each side's QB = the GAME's listed
            starter (known at kickoff, after inactives); weather = the game-day reading. For bets at the close.
    openA   the same ratings; QB = the expected starter before the week's injury reports: the team's starter in
            its latest game this season (the depth chart's QB1 before its first game); no weather. Valid when the
            opener is posted after the previous week's games.
    openB   ratings fitted on games before the PREVIOUS week (one more week stale), QB as of then. Valid also for
            look-ahead openers posted before the previous week was played (the conservative open).

Unit rows may be swapped (`units_of`) for variants (garbage time, fumble luck). Nothing in a row is computed
from a game on or after its own week's first date, except the listed QB and weather on `close` rows.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import team_strength as TS

logger = logging.getLogger(__name__)

MODES = ("close", "openA", "openB")


@lru_cache(maxsize=64)
def depth_qb1(season: int) -> dict[str, str]:
    """{team: gsis id} of each team's QB1 on the depth chart before its first game of `season` (preseason chart)."""
    p = D.raw_root() / "raw" / "depth_charts" / f"depth_charts_{season}.parquet"
    if not p.exists():
        return {}
    d = pd.read_parquet(p)
    out: dict[str, str] = {}
    if "dt" in d.columns:                                    # 2025 -> snapshot format
        q = d[(d["pos_abb"] == "QB") & (d["pos_rank"] == 1)].copy()
        q["dt"] = pd.to_datetime(q["dt"], utc=True, errors="coerce")
        sch = pd.read_parquet(D.schedules_path(), columns=["season", "gameday"])
        first = pd.Timestamp(sch.loc[sch["season"] == season, "gameday"].min(), tz="UTC") if (sch["season"] == season).any() else None
        if first is not None:
            q = q[q["dt"] < first]
        q = q.sort_values("dt").groupby("team").tail(1)
        out = {str(r.team): str(r.gsis_id) for r in q.itertuples(index=False) if isinstance(r.gsis_id, str)}
    else:
        q = d[(d["position"] == "QB") & (d["formation"] == "Offense") & (d["depth_team"].astype(str) == "1")
              & (d["game_type"] == "REG")].copy()
        if q.empty:
            return {}
        q = q.sort_values("week").groupby("club_code").head(1)
        out = {str(r.club_code): str(r.gsis_id) for r in q.itertuples(index=False) if isinstance(r.gsis_id, str)}
    alias = {"LAR": "LA", "JAC": "JAX", "OAK": "LV" if season >= 2020 else "OAK", "SD": "LAC" if season >= 2017 else "SD",
             "STL": "LA" if season >= 2016 else "STL"}
    return {alias.get(k, k): v for k, v in out.items()}


def _qbv(rd: dict, team: str, qb) -> float:
    if isinstance(qb, str) and qb:
        return float(TS.qb_value(rd, qb))
    return float(((rd.get("teams") or {}).get(team) or {}).get("qb_val", 0.0))


def _attach(gw: pd.DataFrame, rd: dict, mode: str, season: int) -> pd.DataFrame:
    if mode == "close":
        out = GM.attach_ratings(gw, rd, use_listed_qb=True)
    else:
        starters = rd.get("starters") or {}
        dq = depth_qb1(season)
        over = {t: dq[t] for t in set(gw["home"]) | set(gw["away"]) if t not in starters and t in dq}
        out = GM.attach_ratings(gw, rd, use_listed_qb=False, qb_override=over)
    out["qbv_h"] = [_qbv(rd, t, q) for t, q in zip(out["home"], out["qb_h"])]
    out["qbv_a"] = [_qbv(rd, t, q) for t, q in zip(out["away"], out["qb_a"])]
    lg = rd.get("league") or {}
    out["np_lg"] = float(lg.get("np", TS.DEFAULTS["np"]))
    return out


def walk_forward(seasons: list[int], first: int = 1999, units_of=None, prm_ts: dict | None = None,
                 games: pd.DataFrame | None = None, modes=MODES) -> pd.DataFrame:
    """Rows (one per game x mode) with ratings-derived columns (net_h, net_a, sr_h, sr_a, off_sum, eff_h, eff_a,
    qb_h, qb_a), the add_context columns, outcomes and `mode`. Chained from `first`."""
    units_of = units_of or D.unit_rows
    p = prm_ts or TS.params()
    seasons = sorted(seasons)
    chain = list(range(first, seasons[-1] + 1))
    G = games if games is not None else D.games_frame(chain)
    G = D.add_context(G[G["season"].isin(chain)])
    out = []
    last = None
    book: dict = {}
    base_num, base_den = 0.0, 0.0
    decay = 0.5 ** (1 / 256.0)
    for s in chain:
        u = units_of(s)
        gs = G[G["season"] == s]
        prior = TS.preseason_prior(last, s, p, book, TS.continuity(s))
        if gs.empty:
            continue
        teams = sorted(set(gs["home"]) | set(gs["away"]))
        weeks = sorted(gs["week"].unique())
        prev_rd = None
        for w in weeks:
            gw = gs[gs["week"] == w]
            thr = gw["date"].min()
            r = TS.fit(u, s, thr, prior, p, teams=teams)
            rd = r.as_dict()
            rd["qb_prior"] = prior["qbs"]
            base = base_num / base_den if base_den > 0 else GM.DEFAULTS["t_base"]
            if s in seasons:
                for mode in modes:
                    use = rd if mode != "openB" else (prev_rd if prev_rd is not None else rd)
                    a = _attach(gw, use, mode, s).assign(base=base, n_games_rated=r.league.get("n_games", 0), mode=mode)
                    if mode != "close":
                        a = a.assign(temp=np.nan, wind=np.nan)
                    out.append(a)
            prev_rd = rd
            for t in gw.loc[gw["played"], "total"].to_numpy(float):
                base_num = base_num * decay + t
                base_den = base_den * decay + 1.0
        end = TS.fit(u, s, None, prior, p)
        TS.update_qb_book(book, end)
        last = end
        del u
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    MF = GM.margin_features(df)
    TF = GM.total_features(df)
    for c in MF.columns:
        df["f_" + c] = MF[c]
    for c in TF.columns:
        df["t_" + c] = TF[c]
    return df
