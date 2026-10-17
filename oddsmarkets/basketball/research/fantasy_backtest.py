"""
Walk-forward check of the Hardwood fantasy projections (analytics/fantasy.py) against what happened, with naive baselines.
Writes data/<league>/fantasy_backtest.json (scripts/bb_fantasy_backtest.py; the build only reads it).

For each completed season and each weekly checkpoint c (from FIRST_DAYS after the season's first regular-season game
to WINDOW days before its last), using only games before c:
  ours            impact.projections (per-36 rates, this season and last, recent games weighted, shrunk to the
                  position; minutes half-life 12 games) x rest factor of the game's rest days (fitted on the three
                  seasons before) x the opponent's pace x the opponent's category factors (fantasy.opponent_factors on
                  games before c), blended with the season-to-date line (BLEND x min(1, games / 20) once he has
                  MIN_GAMES; production fantasy.STD_BLEND); P(play) = his share of this season's team games x the rest
                  factor (production uses valuation v2's two-season share and the injury report, which has no history)
                  Chosen on WNBA 2023-2025 (blend 0, 0.3, 0.5, 0.7; availability from the impact model or this
                  season's share); the NBA seasons and WNBA 2026 are out of sample for those choices.
  season to date  the player's average so far this season (last season's when he has fewer than MIN_GAMES)
  last season     last season's average (this season's so far when he did not play last season)
Scored in standard fantasy points (fantasy.PRESETS["standard"]) and per category:
  next_week        player-games in [c, c + WINDOW): MAE of points per game played; Spearman over players of the
                   window's mean points per game played against the prediction
  next_week_total  per player over the window, games missed included: ours = sum of P(play) x per game; baselines =
                   average x team games in the window x share of team games played so far
  ros              players with ROS_MIN games after c: MAE and Spearman of points per game played over the rest
Only players with a value from every method are scored, so the methods face the same players.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import fantasy as FN
from oddsmarkets.basketball.models import _io
from oddsmarkets.basketball.models import impact as IM

logger = logging.getLogger(__name__)

FIRST_DAYS = 21
WINDOW = 7
STEP = 7
MIN_GAMES = 3
ROS_MIN = 10
W = FN.PRESETS["standard"]["w"]
CATS = ("pts", "reb", "ast", "stl", "blk", "tpm", "tov")
AVAIL = "std"                    # "impact": share of the team's last 20 games; "std": share of this season's team games
BLEND = 0.5                         # weight of the season-to-date average in ours (fantasy.STD_BLEND in production)


def _fp(df: pd.DataFrame) -> pd.Series:
    return sum(float(W.get(k, 0.0)) * df[k] for k in W if k in df)


def _prep(bx: pd.DataFrame) -> pd.DataFrame:
    b = bx.copy()
    b["reb"] = b["oreb"] + b["dreb"]
    b["fp"] = _fp(b)
    return b


def _spearman(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 10:
        return None
    ra, rb = pd.Series(a).rank().to_numpy(), pd.Series(b).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def _blend(pred: float, pid: str, std_avg, std_n) -> float:
    """BLEND x the season-to-date average (when he has MIN_GAMES) + the rest from the model, the weight growing with games
    played up to BLEND at FN.STD_FULL games."""
    n = int(std_n.get(pid, 0))
    if BLEND <= 0 or n < MIN_GAMES:
        return pred
    w = BLEND * min(1.0, n / FN.STD_FULL)
    return (1.0 - w) * pred + w * float(std_avg[pid])


def season_backtest(league: str, season: int) -> dict | None:
    st = an.load_store(league, season)
    prev = an.load_store(league, season - 1)
    if not st.get("games") or not prev.get("games"):
        return None
    cur = _io.box_frame(an.real_games(st), ("reg",))
    pb = _io.box_frame(an.real_games(prev), ("reg",))
    if cur.empty or pb.empty:
        return None
    rest_frames = [_io.box_frame(an.real_games(an.load_store(league, s)), ("reg",)) for s in range(season - 3, season)]
    rest = FN.rest_factors([f for f in rest_frames if f is not None and not f.empty])
    players = st.get("players") or {}
    curp, pbp = _prep(cur), _prep(pb)
    played_c = curp[curp["sec"] > 0]
    played_p = pbp[pbp["sec"] > 0]
    last_avg = played_p.groupby("player_id")["fp"].mean()
    last_cat = played_p.groupby("player_id")[list(CATS)].mean()
    # team games with rest days
    tg = cur.drop_duplicates(["game_id", "team"])[["game_id", "team", "opp", "date", "team_poss"]].copy()
    tg["day"] = pd.to_datetime(tg["date"])
    tg = tg.sort_values(["team", "day"])
    tg["rest"] = tg.groupby("team")["day"].diff().dt.days.sub(1).clip(lower=0, upper=3).fillna(3).astype(int)
    rest_of = {(g, t): r for g, t, r in zip(tg["game_id"], tg["team"], tg["rest"])}
    days = sorted(cur["date"].unique())
    d0, d1 = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    cps = []
    c = d0 + timedelta(days=FIRST_DAYS)
    while c <= d1 - timedelta(days=WINDOW):
        cps.append(c)
        c += timedelta(days=STEP)
    acc = {k: {m: [] for m in ("ours", "season_to_date", "last_season")} for k in ("next_week", "next_week_total", "ros")}
    sp = {k: {m: [] for m in ("ours", "season_to_date", "last_season")} for k in ("next_week", "ros")}
    cat_err = {m: {c: [] for c in CATS} for m in ("ours", "season_to_date")}
    both = pd.concat([pb, cur], ignore_index=True)
    for c in cps:
        cs = str(c)
        ce = str(c + timedelta(days=WINDOW))
        before = played_c[played_c["date"] < cs]
        proj = IM.projections(both, asof=cs, players=players)
        opp = FN.opponent_factors(cur[cur["date"] < cs], pb, 0.5)
        pace = tg[tg["date"] < cs].groupby("team")["team_poss"].mean()
        lg_pace = float(pace.mean()) if len(pace) else 100.0
        std_avg = before.groupby("player_id")["fp"].mean()
        std_n = before.groupby("player_id")["game_id"].nunique()
        std_cat = before.groupby("player_id")[list(CATS)].mean()
        team_n = tg[tg["date"] < cs].groupby("team")["game_id"].nunique()

        def per_game(pid, gid, team, opp_t):
            pj = proj.get(pid)
            if not pj:
                return None, None
            r = {k: float(v) / 36.0 for k, v in (pj.get("rates") or {}).items()}
            r["reb"] = r.get("oreb", 0.0) + r.get("dreb", 0.0)
            rs = str(rest_of.get((gid, team), 3))
            mins = float(pj.get("min") or 0.0) * float(rest["min"].get(rs, 1.0))
            pf = float(pace.get(opp_t, lg_pace)) / lg_pace
            g = FN.game_stats(r, mins, pf, opp.get(str(opp_t)) or {}, {})
            if AVAIL == "std" and int(team_n.get(team, 0)) >= MIN_GAMES:
                av = min(1.0, int(std_n.get(pid, 0)) / max(1, int(team_n.get(team, 1))))
            else:
                av = float(pj.get("avail") or 0.9)
            pplay = av * float(rest["play"].get(rs, 1.0))
            return g, pplay

        def base(pid):
            n = int(std_n.get(pid, 0))
            s = float(std_avg[pid]) if n >= MIN_GAMES else (float(last_avg[pid]) if pid in last_avg.index else None)
            ls = float(last_avg[pid]) if pid in last_avg.index else (float(std_avg[pid]) if n >= 1 else None)
            return s, ls

        win = played_c[(played_c["date"] >= cs) & (played_c["date"] < ce)]
        rows = []
        for pid, gid, team, opp_t, fp in zip(win["player_id"], win["game_id"], win["team"], win["opp"], win["fp"]):
            g, _p = per_game(pid, gid, team, opp_t)
            s, ls = base(pid)
            if g is None or s is None or ls is None:
                continue
            pred = sum(float(W.get(k, 0.0)) * g.get(k, 0.0) for k in W)
            pred = _blend(pred, pid, std_avg, std_n)
            rows.append((pid, fp, pred, s, ls))
            acc["next_week"]["ours"].append(abs(fp - pred))
            acc["next_week"]["season_to_date"].append(abs(fp - s))
            acc["next_week"]["last_season"].append(abs(fp - ls))
            act_row = win[(win["player_id"] == pid) & (win["game_id"] == gid)].iloc[0]
            for k in CATS:
                cat_err["ours"][k].append(abs(float(act_row[k]) - g.get(k, 0.0)))
                sc = float(std_cat.loc[pid, k]) if pid in std_cat.index and int(std_n.get(pid, 0)) >= MIN_GAMES else \
                    (float(last_cat.loc[pid, k]) if pid in last_cat.index else 0.0)
                cat_err["season_to_date"][k].append(abs(float(act_row[k]) - sc))
        if rows:
            df = pd.DataFrame(rows, columns=["pid", "fp", "ours", "std", "ls"]).groupby("pid").mean()
            if len(df) >= 10:
                sp["next_week"]["ours"].append(_spearman(df["fp"], df["ours"]))
                sp["next_week"]["season_to_date"].append(_spearman(df["fp"], df["std"]))
                sp["next_week"]["last_season"].append(_spearman(df["fp"], df["ls"]))
        # totals over the window, games missed included (players who played in the two weeks before c)
        recent = set(played_c[(played_c["date"] >= str(c - timedelta(days=14))) & (played_c["date"] < cs)]["player_id"])
        twin = tg[(tg["date"] >= cs) & (tg["date"] < ce)]
        for pid in recent:
            team = before[before["player_id"] == pid]["team"].iloc[-1]
            games = twin[twin["team"] == team]
            if games.empty:
                continue
            s, ls = base(pid)
            if s is None or ls is None or pid not in proj:
                continue
            ours = 0.0
            for gid, opp_t in zip(games["game_id"], games["opp"]):
                g, pplay = per_game(pid, gid, team, opp_t)
                if g is not None:
                    ours += pplay * _blend(sum(float(W.get(k, 0.0)) * g.get(k, 0.0) for k in W), pid, std_avg, std_n)
            share = min(1.0, int(std_n.get(pid, 0)) / max(1, int(team_n.get(team, 1))))
            act = float(win[(win["player_id"] == pid) & (win["team"] == team)]["fp"].sum())
            acc["next_week_total"]["ours"].append(abs(act - ours))
            acc["next_week_total"]["season_to_date"].append(abs(act - s * len(games) * share))
            acc["next_week_total"]["last_season"].append(abs(act - ls * len(games) * share))
        # rest of season, points per game played
        after = played_c[played_c["date"] >= cs]
        agg = after.groupby("player_id").agg(fp=("fp", "mean"), n=("game_id", "nunique"), team=("team", "last"), opp=("opp", "last"),
                                             gid=("game_id", "last"))
        rr = []
        for pid, x in agg[agg["n"] >= ROS_MIN].iterrows():
            g, _p = per_game(pid, x["gid"], x["team"], None)
            s, ls = base(pid)
            if g is None or s is None or ls is None:
                continue
            pred = _blend(sum(float(W.get(k, 0.0)) * g.get(k, 0.0) for k in W), pid, std_avg, std_n)
            rr.append((x["fp"], pred, s, ls))
        if rr:
            a = np.array(rr)
            for i, m in enumerate(("ours", "season_to_date", "last_season")):
                acc["ros"][m].extend(list(np.abs(a[:, 0] - a[:, i + 1])))
                sp["ros"][m].append(_spearman(a[:, 0], a[:, i + 1]))
    summ = {}
    for hz, d in acc.items():
        summ[hz] = {}
        for m, v in d.items():
            s_list = [x for x in (sp.get(hz) or {}).get(m, []) if x is not None]
            summ[hz][m] = {"mae": round(float(np.mean(v)), 3) if v else None, "spearman": round(float(np.mean(s_list)), 4) if s_list else None, "n": len(v)}
    cats = {m: {k: round(float(np.mean(v)), 3) for k, v in d.items() if v} for m, d in cat_err.items()}
    return {"season": season, "checkpoints": len(cps), "summary": summ, "cats": cats, "rest": rest}


def run(league: str, seasons: list[int]) -> dict:
    per = {}
    for s in seasons:
        logger.info("%s %s fantasy backtest", league, s)
        r = season_backtest(league, s)
        if r:
            per[s] = r
    # pooled: weight each season's MAE by its n, Spearman by its checkpoints
    summ: dict = {}
    for hz in ("next_week", "next_week_total", "ros"):
        summ[hz] = {}
        for m in ("ours", "season_to_date", "last_season"):
            xs = [(r["summary"][hz][m]["mae"], r["summary"][hz][m]["n"], r["summary"][hz][m]["spearman"], r["checkpoints"]) for r in per.values()
                  if r["summary"][hz][m]["mae"] is not None]
            n = sum(x[1] for x in xs)
            sps = [(x[2], x[3]) for x in xs if x[2] is not None]
            summ[hz][m] = {"mae": round(sum(x[0] * x[1] for x in xs) / n, 3) if n else None,
                           "spearman": round(sum(a * w for a, w in sps) / sum(w for _a, w in sps), 4) if sps else None, "n": n}
    return {"ok": True, "league": league, "updated_at": an.now(), "seasons": sorted(per), "checkpoints": sum(r["checkpoints"] for r in per.values()),
            "n": summ["next_week"]["ours"]["n"], "summary": summ, "by_season": {str(s): {k: r[k] for k in ("summary", "cats", "checkpoints")} for s, r in per.items()},
            "scoring": W, "constants": {"first_days": FIRST_DAYS, "window": WINDOW, "step": STEP, "min_games": MIN_GAMES, "ros_min": ROS_MIN}}
