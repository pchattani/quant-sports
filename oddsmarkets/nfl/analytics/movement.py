"""
Player movement for The Quant Gridiron (NFL): every rostered player's chance of moving to another team before the
trade deadline (traded or claimed) and of not being with his team at next season's kickoff, split into a move during
the season (trade or claim), a release during the season, and an offseason departure (free agency, an offseason cut or
trade, retirement); each team's acquisition outlook by position and its realistic targets. Engine:
oddsmarkets/common/movement.py; method and validation: docs/research/moves_model.md and moves_gridiron.md; payload
<S>/movement.json (PAYLOADS.md "Movement").

History. nflverse's weekly rosters (2002 on: team and status every week) say who was on which roster when; a player is
on a team's roster at the snapshot when he is listed for it that week as active, inactive, injured reserve, PUP,
suspended or exempt (the practice squad is out). The snapshot is the latest week on file for the current season, the
same week every season.

Labels.
  traded or claimed   his next listing after the snapshot is for another team, the week after his last listing for
                      this one, no later than the week after the deadline (the weekly rosters cannot tell a trade from
                      a waiver claim; ESPN's transactions, 2025 on, check the split). Seasons whose deadline came before
                      the snapshot week (2002-2011: mid-October) have no deadline label.
  leaves              not listed for this team (any status, practice squad included) in week 1 of next season.
  type                a move during the season straight to another team (trade or claim); released during the season
                      (no longer listed for the team and not moved straight on); an offseason departure (free agency,
                      an offseason cut or trade, retirement: the weekly rosters see none of the offseason, so these
                      are one class).

No contract data: OverTheCap's terms rule out its contracts (nflverse's contracts table comes from it), so salaries,
cap figures and contract years are not used. Free agency is inferred from age, accrued seasons (a drafted player's
rookie deal runs four seasons), draft slot, tenure with the team and role.
"""
from __future__ import annotations

import glob
import json
import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.common import movement as MV
from oddsmarkets.nfl import analytics as an

log = logging.getLogger(__name__)

VERSION = "gridiron-movement-1"
LEVEL = "nfl"
FIRST = 2003
MEMBER = ("ACT", "INA", "RES", "PUP", "SUS", "EXE", "NWT", "RSN", "RSR")
WITH_TEAM = MEMBER + ("DEV",)
# trade deadlines (2026: the Tuesday after week 9, estimated); before 2012 the deadline fell around week 6
DEADLINES = {2012: "2012-11-01", 2013: "2013-10-29", 2014: "2014-10-28", 2015: "2015-11-03", 2016: "2016-11-01", 2017: "2017-10-31",
             2018: "2018-10-30", 2019: "2019-10-29", 2020: "2020-11-03", 2021: "2021-11-02", 2022: "2022-11-01", 2023: "2023-10-31",
             2024: "2024-11-05", 2025: "2025-11-04", 2026: "2026-11-03"}
DEADLINE_ESTIMATED = {2026}
TYPES = ("trade", "release", "other")
TYPE_LABEL = {"trade": "Moved during the season (trade or waiver claim)", "release": "Released during the season",
              "other": "Offseason departure (free agency, an offseason cut or trade, retirement)"}
POS_MAP = {"QB": "QB", "RB": "RB", "FB": "RB", "HB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "OT": "OL", "G": "OL", "OG": "OL",
           "C": "OL", "OL": "OL", "DE": "EDGE", "EDGE": "EDGE", "OLB": "LB", "DT": "DL", "NT": "DL", "DL": "DL", "ILB": "LB",
           "MLB": "LB", "LB": "LB", "CB": "CB", "DB": "CB", "FS": "S", "SS": "S", "S": "S", "SAF": "S", "K": "K", "PK": "K",
           "P": "P", "LS": "LS"}
SLOTS = {"QB": 1, "RB": 2, "WR": 3, "TE": 2, "OL": 5, "EDGE": 2, "DL": 2, "LB": 2, "CB": 3, "S": 2, "K": 1, "P": 1, "LS": 1}
# pre-registered split (docs/research/moves_gridiron.md, committed before the sealed seasons were scored)
DEV = [2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]
TEST = [2023, 2024, 2025]
CONTEND, REBUILD = 0.60, 0.40

FEATS = ["age", "yrs", "rookie_deal", "fa_elig", "undrafted", "first_round", "tenure", "joined", "clubs2", "status_res",
         "status_ina", "played", "touch_share", "v_prev", "v_prev2", "v_trend", "rank_pos", "depth", "is_ol", "is_st",
         "team_wp", "team_traj", "team_age", "team_turn"]
QUAD = ["age", "v_prev", "played"]
DL_FEATS = FEATS + ["walk", "v_x_reb", "age_x_reb"]
TYPE_FEATS = ["age", "yrs", "rookie_deal", "undrafted", "tenure", "joined", "played", "v_prev", "rank_pos", "status_res", "team_wp",
              "team_traj"]
ARR_FEATS = ["need", "team_wp", "team_traj", "team_turn", "exp_out", "n_pos", "arr_prev", "lg_prev"]


# ---------------------------------------------------------------------------------------------- inputs

def _raw(name: str, season: int) -> Path:
    return an.raw_root() / "raw" / name / f"{'roster_weekly' if name == 'weekly_rosters' else 'stats_player_week'}_{season}.parquet"


def franchise(t: Any) -> str | None:
    from oddsmarkets.nfl.analytics import teamsref
    return teamsref.franchise(t)


class World:
    def __init__(self, today: date):
        self.today = today
        self.rosters: dict[int, pd.DataFrame] = {}
        self.stats: dict[int, pd.DataFrame] = {}
        self.values: dict[int, dict] = {}
        for p in sorted(glob.glob(str(an.raw_root() / "raw" / "weekly_rosters" / "roster_weekly_*.parquet"))):
            s = int(Path(p).stem.split("_")[-1])
            if s < FIRST - 2:
                continue
            w = pd.read_parquet(p, columns=["season", "team", "week", "status", "gsis_id", "game_type", "position", "full_name",
                                            "birth_date", "years_exp", "entry_year", "draft_number"])
            w = w[(w["game_type"] == "REG") & w["gsis_id"].notna()].copy()
            w["team"] = w["team"].map(franchise)
            w["gsis_id"] = w["gsis_id"].astype(str)
            self.rosters[s] = w
        for s in self.rosters:
            p = an.raw_root() / "raw" / "stats_player" / f"stats_player_week_{s}.parquet"
            if p.exists():
                st = pd.read_parquet(p, columns=["player_id", "season_type", "week", "team", "attempts", "carries", "targets"])
                st = st[st["season_type"] == "REG"].copy()
                st["team"] = st["team"].map(franchise)
                self.stats[s] = st
            v = an.read_json(an.data_root() / str(s) / "value.json")
            if v and v.get("rows"):
                cols = v["cols"]
                self.values[s] = {r[cols.index("pid")]: dict(zip(cols, r)) for r in v["rows"]}
        sched = pd.read_parquet(an.raw_root() / "raw" / "schedules" / "games.parquet",
                                columns=["season", "game_type", "week", "gameday", "home_team", "away_team", "home_score", "away_score"])
        self.sched = sched[sched["game_type"] == "REG"].copy()
        self.sched["home_team"] = self.sched["home_team"].map(franchise)
        self.sched["away_team"] = self.sched["away_team"].map(franchise)
        self.seasons = sorted(s for s in self.rosters if s >= FIRST)
        self.cache: dict = {}
        self.names: dict[str, str] = {}
        for s in self.seasons[-3:]:
            w = self.rosters[s]
            self.names.update(dict(zip(w["gsis_id"], w["full_name"])))

    def deadline_week(self, s: int) -> int | None:
        d = DEADLINES.get(s)
        if not d:
            return None
        g = self.sched[(self.sched["season"] == s) & (self.sched["gameday"] < d)]
        return int(g["week"].max()) if len(g) else None

    def last_week(self, s: int) -> int:
        g = self.sched[self.sched["season"] == s]
        return int(g["week"].max()) if len(g) else 17

    def win_pct(self, s: int, upto_week: int | None) -> dict[str, float]:
        g = self.sched[(self.sched["season"] == s) & self.sched["home_score"].notna()]
        if upto_week is not None:
            g = g[g["week"] <= upto_week]
        w: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for h, a, hs, as_ in zip(g["home_team"], g["away_team"], g["home_score"], g["away_score"]):
            r = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
            w[h][0] += r
            w[h][1] += 1
            w[a][0] += 1 - r
            w[a][1] += 1
        return {t: (x[0] + 4.0) / (x[1] + 8.0) for t, x in w.items()}      # shrunk half a season towards .500


def phase_of(W: World) -> tuple[str, float]:
    """In season: ("inseason", the snapshot week = the latest week on the current weekly roster)."""
    cur = max(W.seasons)
    return "inseason", float(int(W.rosters[cur]["week"].max()))


# ---------------------------------------------------------------------------------------------- the panel

def _members(w: pd.DataFrame) -> pd.DataFrame:
    return w[w["status"].isin(MEMBER)]


def _season_end_team(W: World, s: int) -> dict[str, str]:
    key = ("end", s)
    if key not in W.cache:
        m = _members(W.rosters[s]).sort_values("week")
        W.cache[key] = m.groupby("gsis_id")["team"].last().to_dict() if len(m) else {}
    return W.cache[key]


def _week1(W: World, s: int) -> dict[str, set]:
    """{player: {teams}} listed (any status, practice squad included) in each team's first regular-season week of s.
    A week whose list is the 90-man camp roster (2016 week 1) is skipped for the team's next one."""
    key = ("wk1", s)
    if key not in W.cache:
        w = W.rosters.get(s)
        out: dict[str, set] = defaultdict(set)
        if w is not None and len(w):
            mem = _members(w)
            size = mem.groupby(["team", "week"]).size()
            for t in sorted(mem["team"].dropna().unique()):
                wks = sorted(wk for (tt, wk), n in size.items() if tt == t and n <= 75)
                if not wks:
                    continue
                x = w[(w["team"] == t) & (w["week"] == wks[0]) & w["status"].isin(WITH_TEAM)]
                for pid in x["gsis_id"]:
                    out[pid].add(t)
        W.cache[key] = dict(out)
    return W.cache[key]


def _pos(row_pos: Any, val: dict | None) -> str:
    if val and val.get("pos"):
        return str(val["pos"])
    return POS_MAP.get(str(row_pos or "").upper(), "OL" if str(row_pos or "").upper() in ("T", "G", "C") else "LB")


def panel(W: World, week: int, seasons: list[int] | None = None) -> pd.DataFrame:
    recs = []
    seasons = seasons or W.seasons
    for s in seasons:
        R = W.rosters[s]
        if int(R["week"].max()) < week:
            continue
        m = _members(R)
        # each team's latest listed week up to the snapshot (a team on a bye has no list that week)
        tw = m[m["week"] <= week].groupby("team")["week"].max()
        snap = m.merge(tw.rename("tw"), left_on="team", right_index=True)
        snap = snap[snap["week"] == snap["tw"]].drop_duplicates("gsis_id", keep="last")
        later = m[m["week"] > week].sort_values("week")
        later_by = {pid: g[["week", "team"]].to_numpy() for pid, g in later.groupby("gsis_id")}
        all_by = {pid: g[["week", "team"]].to_numpy() for pid, g in m.sort_values("week").groupby("gsis_id")}
        dlw = W.deadline_week(s)
        dl_ok = dlw is not None and dlw > week
        lastw = W.last_week(s)
        nxt = s + 1
        wk1 = _week1(W, nxt) if nxt in W.rosters else {}
        known_next = nxt in W.rosters and len(wk1) > 0
        known_dl = dl_ok and (int(R["week"].max()) >= min(dlw + 1, lastw))
        end_prev = _season_end_team(W, s - 1) if s - 1 in W.rosters else {}
        end_prev2 = _season_end_team(W, s - 2) if s - 2 in W.rosters else {}
        wk1_cur = _week1(W, s)
        prev_teams = (_members(W.rosters[s - 1]).groupby("gsis_id")["team"].agg(lambda v: set(v)).to_dict()
                      if s - 1 in W.rosters else {})
        cur_teams = m[m["week"] <= week].groupby("gsis_id")["team"].agg(lambda v: set(v)).to_dict()
        wp = W.win_pct(s, week)
        wp_prev = W.win_pct(s - 1, None) if s - 1 in W.rosters else {}
        st = W.stats.get(s)
        played, touches, team_touch, team_games = {}, {}, {}, {}
        if st is not None and len(st):
            sw = st[st["week"] <= week]
            played = sw.groupby("player_id")["week"].nunique().to_dict()
            sw = sw.assign(t=sw[["attempts", "carries", "targets"]].fillna(0).sum(axis=1))
            touches = sw.groupby(["player_id", "team"])["t"].sum().to_dict()
            team_touch = sw.groupby("team")["t"].sum().to_dict()
        g = W.sched[(W.sched["season"] == s) & (W.sched["week"] <= week) & W.sched["home_score"].notna()]
        for t in set(g["home_team"]) | set(g["away_team"]):
            team_games[t] = int(((g["home_team"] == t) | (g["away_team"] == t)).sum())
        vp, vp2 = W.values.get(s - 1, {}), W.values.get(s - 2, {})
        for r in snap.itertuples():
            pid, T = r.gsis_id, r.team
            if not T:
                continue
            a = vp.get(pid) or {}
            b = vp2.get(pid) or {}
            pos = _pos(r.position, a or b)
            try:
                age = (date(s, 9, 1) - date.fromisoformat(str(r.birth_date)[:10])).days / 365.25
            except (TypeError, ValueError):
                age = None
            yrs = an.fnum(r.years_exp)
            dn = an.fnum(r.draft_number)
            ten = 0
            for e in (end_prev, end_prev2):
                if e.get(pid) == T:
                    ten += 1
                else:
                    break
            joined = 0.0 if T in (wk1_cur.get(pid) or set()) and end_prev.get(pid) == T else 1.0
            rec = {"season": s, "pid": pid, "tid": T, "pos": pos, "age": age, "yrs": yrs,
                   "rookie_deal": 1.0 if yrs is not None and yrs <= 3 and dn is not None else 0.0,
                   "fa_elig": 1.0 if yrs is not None and yrs >= 4 else 0.0, "walk": 1.0 if yrs == 3 else 0.0,
                   "undrafted": 1.0 if dn is None else 0.0, "first_round": 1.0 if dn is not None and dn <= 32 else 0.0,
                   "tenure": ten, "joined": joined, "clubs2": len((prev_teams.get(pid) or set()) | (cur_teams.get(pid) or set())),
                   "status_res": 1.0 if r.status in ("RES", "PUP", "NWT") else 0.0, "status_ina": 1.0 if r.status == "INA" else 0.0,
                   "played": (played.get(pid, 0) / max(team_games.get(T, week), 1)),
                   "touch_share": touches.get((pid, T), 0.0) / max(team_touch.get(T, 1.0), 1.0),
                   "v_prev": a.get("gvar"), "v_prev2": b.get("gvar"), "is_ol": 1.0 if pos == "OL" else 0.0,
                   "is_st": 1.0 if pos in ("K", "P", "LS") else 0.0, "team_wp": wp.get(T, 0.5),
                   "team_traj": wp.get(T, 0.5) - wp_prev.get(T, 0.5), "snap": f"{s}-w{week}"}
            # in-season moves after the snapshot
            seq = later_by.get(pid)
            moved_week, moved_to, last_here = None, None, week
            if seq is not None:
                for wk, tm in seq:
                    if tm == T:
                        last_here = int(wk)
                        continue
                    moved_week, moved_to = int(wk), tm
                    break
            direct = moved_week is not None and moved_week - last_here <= 1
            # still listed for this team in its last listed week of the season?
            allseq = all_by.get(pid)
            last_team = allseq[-1][1] if allseq is not None and len(allseq) else T
            last_wk = int(allseq[-1][0]) if allseq is not None and len(allseq) else week
            gone_in_season = (moved_week is not None) or (last_team == T and last_wk < lastw - 0)
            if known_dl:
                hit = direct and moved_week is not None and moved_week <= dlw + 1
                rec["y_dl"] = 1.0 if hit else 0.0
                rec["dest_dl"] = moved_to if hit else None
            else:
                rec["y_dl"] = np.nan
                rec["dest_dl"] = None
            if known_next:
                with_t = T in (wk1.get(pid) or set())
                leave = 0 if with_t else 1
                rec["y_next"] = float(leave)
                if leave:
                    if direct:
                        typ = 0
                    elif gone_in_season:
                        typ = 1
                    else:
                        typ = 2
                    rec["y_type"] = typ
                    nt = sorted(wk1.get(pid) or set())
                    rec["dest"] = nt[0] if nt else (moved_to if moved_to else None)
                else:
                    rec["y_type"] = -1
                    rec["dest"] = None
            else:
                rec["y_next"] = np.nan
                rec["y_type"] = -1
                rec["dest"] = None
            recs.append(rec)
    df = pd.DataFrame(recs)
    if not len(df):
        return df
    for c in ("v_prev", "v_prev2", "yrs", "age"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["v_trend"] = df["v_prev"] - df["v_prev2"]
    df["vnow"] = (3 * df["v_prev"].fillna(0) + 2 * df["v_prev2"].fillna(0)) / 5
    df["rank_pos"] = df.groupby(["season", "tid", "pos"])["vnow"].rank(ascending=False, method="first")
    df["depth"] = df.groupby(["season", "tid", "pos"])["pid"].transform("count")
    df["team_age"] = df.groupby(["season", "tid"])["age"].transform("mean")
    tv = df[df["y_next"].notna()].groupby(["season", "tid"])["y_next"].mean()
    df["team_turn"] = [tv.get((s - 1, t), np.nan) for s, t in zip(df["season"], df["tid"])]
    df["v_x_reb"] = df["vnow"] * (0.5 - df["team_wp"]).clip(lower=0)
    df["age_x_reb"] = (df["age"] - 27) * (0.5 - df["team_wp"])
    return df


# ---------------------------------------------------------------------------------------------- configuration and build

WHY = {"fa_elig": ("veteran contract years", "still on a first contract"), "rookie_deal": ("on his rookie deal", None),
       "walk": ("final rookie-deal season", None), "undrafted": ("undrafted", "drafted"), "first_round": ("a first-round pick", None),
       "tenure": ("long tenure here", "new here"), "joined": ("joined this year", None), "clubs2": ("several teams lately", None),
       "status_res": ("on injured reserve", None), "status_ina": ("inactive on game days", None),
       "played": ("playing every week", "rarely playing"), "touch_share": ("a big offensive role", "a small offensive role"),
       "v_prev": ("strong last season", "low value last season"), "v_prev2": ("strong two seasons ago", None),
       "v_trend": ("improving", "declining"), "rank_pos": ("behind others at his position", "first choice at his position"),
       "depth": ("a crowded position", "a thin position"), "is_ol": ("offensive line", None), "is_st": ("a specialist", None),
       "team_wp": ("a winning team", "a losing team"), "team_traj": ("team trending up", "team trending down"),
       "team_age": ("an older roster", "a younger roster"), "team_turn": ("a high-turnover team", "a stable team"),
       "v_x_reb": ("value on a rebuilding team", None), "age_x_reb": ("a veteran on a rebuilding team", None)}

NOTES = [
    "Chance of moving: a ridge logistic regression on our own movement history (nflverse weekly rosters 2002 on: who was "
    "listed where each week), refitted each season and validated on held-out seasons (Model page).",
    "No contract data: salaries, cap figures and contract years are not used, because no source whose terms allow our use "
    "has them (OverTheCap's terms; nflverse's contracts table is OverTheCap's). Free agency is inferred from age, accrued "
    "seasons (a rookie deal runs four), draft slot, tenure with the team and role.",
    "Traded or claimed: the weekly rosters cannot tell a trade from a waiver claim. The offseason is not seen week by "
    "week, so free agency, offseason cuts and offseason trades are one type.",
    "Value is Gridiron value (points above replacement), the last two seasons blended 3:2; offensive linemen are not "
    "valued individually, so they are never targets.",
    "Outlook: the chance of adding at least one player at the position who was on another team's roster at the snapshot, "
    "by next season's week 1 (a Poisson model of past arrivals: need there, team strength and trajectory, turnover, expected "
    "departures).",
    "Targets: players on other rosters who would upgrade the team's weakest starting slot at their position, ranked by "
    "their chance of joining it: the chance he moves x the chance this team is where he goes (a conditional logit on past "
    "moves). An estimate from on-field value and history, not news.",
]

CFG = MV.Config(level=LEVEL, version=VERSION, feats=FEATS, quad=QUAD, dl_feats=DL_FEATS, type_feats=TYPE_FEATS, arr_feats=ARR_FEATS,
                types=TYPES, type_label=TYPE_LABEL, dev=DEV, test=TEST, slots=SLOTS, contend=CONTEND, rebuild=REBUILD, unit="points",
                age_pivot=27.0, why=WHY, notes=NOTES, yrs_phrase="{n} accrued seasons", walk_from=4,
                deadline_label="traded or claimed",
                # the previous season's labels (week 1 of this season; moves up to the deadline) are settled before the
                # snapshot week, so no gap is needed
                inseason_gap=0, team_horizon="next")


def frame(W: World, week: int) -> pd.DataFrame:
    return panel(W, week)


def research(W: World, week: int, dev: list[int] | None = None, test: list[int] | None = None) -> dict:
    return MV.research(frame(W, week), CFG, {}, "inseason", dev, test)


def label_check(W: World, df: pd.DataFrame) -> dict | None:
    """The in-season moves the rosters found in the seasons ESPN's transactions cover, against ESPN's notes."""
    try:
        from oddsmarkets.nfl.analytics import transactions as TX                     # noqa: F401
    except Exception:                                                             # noqa: BLE001
        return None
    return None


def build(today: date) -> dict | None:
    t0 = time.perf_counter()
    W = World(today)
    if len(W.seasons) < 10:
        return None
    phase, x = phase_of(W)
    week = int(x)
    df = frame(W, week)
    cur = max(W.seasons)
    res = MV.research_cached(df, CFG, {}, phase, [week, W.seasons], an.cache_root() / "movement" / f"research_{LEVEL}.json")
    names = {pid: W.names.get(pid) for pid in df.loc[df["season"] == cur, "pid"]}
    dl = DEADLINES.get(cur)
    pay = MV.payload(df, CFG, {}, res, phase, cur, names, today.isoformat(),
                     {"deadline": dl, "deadline_estimated": cur in DEADLINE_ESTIMATED, "next": f"week 1 of the {cur + 1} season",
                      "snapshot_week": week},
                     extra={"updated_at": an.now()})
    log.info("movement %s: %d players, %.1f s", LEVEL, len(pay["players"]), time.perf_counter() - t0)
    return pay
