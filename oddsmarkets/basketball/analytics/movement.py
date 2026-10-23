"""
Player movement for The Quant Hardwood (NBA and WNBA): every rostered player's chance of moving to another team before
the trade deadline and of not being with his team at next season's first game (split by kind), each team's acquisition
outlook by position (guards, forwards, centres), and its realistic targets on other teams. Engine:
oddsmarkets/common/movement.py; method and validation: docs/research/moves_model.md (shared) and
docs/research/moves_hardwood.md (this sport); payload <league>/movement.json (PAYLOADS.md "Movement").

History. ESPN's transactions endpoint gives us only the last two calendar years (and thinly), so the history is the
box scores: every regular-season game's players and its did-not-play list name who was on which team on which date
(NBA 1997 on, WNBA 1997 on; the did-not-play lists are missing in some older seasons, where a player who did not play
is not seen). A *snapshot* is taken at the same point of every season as today:

  season start (NBA in October): the opening rosters (the first team a player is listed for in the season's first ten
      days); features only from earlier seasons;
  after the season (WNBA after its season): the team a player was last listed for, if he was still listed in the last
      three weeks of its season; features include the season just finished.

Labels, all inferred from the box scores (stated on the page):
  traded or claimed before the deadline   listed next for another team within 21 days of his last listing for this one,
                                          the first listing for the new team no later than ten days after the deadline
                                          (a trade or a waiver claim; the two cannot be told apart without transactions)
  leaves by next season                   the first team he is listed for next season is not this one (or none)
  kind (season-start snapshot)            "trade": moved straight to another team during the season (trade or claim);
                                          "release": stopped being listed with three weeks or more of the team's season
                                          left, without a direct move (waived or bought out); "other": an offseason move
                                          (free agency, an offseason trade, release or retirement: not separable here)
  kind (after-season snapshot)            every departure is an offseason move: the split is not modelled (base shares)

No contract data: salaries, contract years, options and no-trade clauses are not used (Spotrac, HoopsHype and
Basketball-Reference forbid this reuse). Free agency is inferred from age, years since the debut, tenure and role.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.common import movement as MV

log = logging.getLogger(__name__)

VERSION = "hardwood-movement-1"
FIRST = {"nba": 1997, "wnba": 1997}
# first season of the panel (dev choice: the NBA's trade rate drifted up; from 2005 the deadline model is calibrated)
PANEL_FIRST = {"nba": 2005, "wnba": 1999}
# NBA trade deadlines by ESPN season (the year the season ends); others default to the third Thursday of February
NBA_DEADLINES = {1999: "03-11", 2005: "02-24", 2006: "02-23", 2007: "02-22", 2008: "02-21", 2009: "02-19", 2010: "02-18",
                 2011: "02-24", 2012: "03-15", 2013: "02-21", 2014: "02-20", 2015: "02-19", 2016: "02-18", 2017: "02-23",
                 2018: "02-08", 2019: "02-07", 2020: "02-06", 2021: "03-25", 2022: "02-10", 2023: "02-09", 2024: "02-08",
                 2025: "02-06", 2026: "02-05", 2027: "02-04"}
WNBA_DEADLINES = {2025: "08-07"}
OPEN_DAYS = 10            # opening rosters: first listing within this many days of the first game
SWITCH_GAP = 21           # days between the last listing for one team and the first for the next: a direct move
LATE_DAYS = 10            # a direct move counts for the deadline when the new team first lists him by deadline + this
RELEASE_LEFT = 21         # stopped being listed with this many days or more of the team's season left: released
POS_MAP = {"PG": "G", "SG": "G", "G": "G", "SF": "F", "PF": "F", "F": "F", "C": "C", "G-F": "F", "F-G": "F", "F-C": "C", "C-F": "C"}
SLOTS = {"G": 2, "F": 2, "C": 1}
CONTEND, REBUILD = 0.56, 0.44

TYPES = ("trade", "release", "other")
TYPE_LABEL = {"trade": "Traded or claimed during the season", "release": "Waived during the season",
              "other": "Offseason move (free agency, an offseason trade or release, retirement)"}

FEATS_START = ["age", "yrs", "rookie", "tenure", "new_here", "clubs2", "share_prev", "gp_prev", "v_prev", "v_prev2", "v_trend",
               "hpm_prev", "rank_pos", "depth", "big", "guard", "team_wp", "team_traj", "team_age", "team_turn", "first_round"]
FEATS_AFTER = ["age", "yrs", "rookie", "tenure", "joined", "clubs2", "share", "share_prev", "gp_cur", "v_cur", "v_prev", "v_trend",
               "hpm_cur", "rank_pos", "depth", "big", "guard", "team_wp", "team_traj", "team_age", "team_turn", "first_round"]
QUAD_START = ["age", "v_prev", "share_prev"]
QUAD_AFTER = ["age", "v_cur", "share"]
DL_EXTRA = ["v_x_reb", "age_x_reb", "vet_x_cont"]
ARR_FEATS = ["need", "team_wp", "team_traj", "team_turn", "exp_out", "n_pos"]

# pre-registered splits (docs/research/moves_hardwood.md, committed before the sealed seasons were scored)
SPLITS = {"nba": {"dev": list(range(2008, 2023)), "test": [2023, 2024, 2025]},
          "wnba": {"dev": list(range(2008, 2023)), "test": [2023, 2024, 2025]}}


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def pool_of(pos: Any) -> str | None:
    p = str(pos or "").upper()
    return POS_MAP.get(p) or (p if p in ("G", "F", "C") else None)


# ---------------------------------------------------------------------------------------------- inputs

class World:
    """Listings (who was on which team on which date), season bounds, win shares, value rows, bio, for one league."""

    def __init__(self, league: str, today: date, data=None):
        from oddsmarkets.basketball.analytics import bio as BIO
        self.league, self.today = league, today
        root = data or an.data_root()
        seasons = [s for s in an.seasons_on_disk(league) if s >= FIRST[league]]
        self.listings: dict[int, pd.DataFrame] = {}
        self.bounds: dict[int, tuple[date, date]] = {}
        self.wp: dict[int, dict[str, float]] = {}
        self.team_last: dict[int, dict[str, date]] = {}
        self.pool: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.rosters_now: dict[str, list[str]] = {}
        self.team_names: dict[str, str] = {}
        self.conf: dict[str, str] = {}
        self.roster_source = "box_scores"
        for s in seasons:
            st = an.load_store(league, s)
            recs = []
            w: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            dates = []
            for g in (st.get("games") or {}).values():
                if g.get("stype") not in ("reg", "post", "playin"):
                    continue
                d = str(g.get("date") or "")[:10]
                if g.get("stype") == "reg":
                    dates.append(d)
                box = g.get("box") or {}
                for t, b in box.items():
                    for r in (b.get("players") or []):
                        recs.append((str(r[0]), str(t), d, float(r[2] or 0), g["stype"]))
                    for r in (b.get("dnp") or []):
                        recs.append((str(r[0]), str(t), d, 0.0, g["stype"]))
                if g.get("stype") == "reg" and g.get("status") == "post" and g.get("hs") is not None and g.get("as") is not None:
                    try:
                        hw = 1 if int(g["hs"]) > int(g["as"]) else 0
                    except (TypeError, ValueError):
                        continue
                    w[str(g["home"])][0] += hw
                    w[str(g["home"])][1] += 1
                    w[str(g["away"])][0] += 1 - hw
                    w[str(g["away"])][1] += 1
            if dates:
                self.bounds[s] = (_d(min(dates)), _d(max(dates)))
            n_season = 82 if league == "nba" else 40
            self.wp[s] = {t: (x[0] + n_season / 4) / (x[1] + n_season / 2) for t, x in w.items() if x[1]}
            df = pd.DataFrame(recs, columns=["pid", "tid", "date", "sec", "stype"])
            if len(df):
                df = df.sort_values(["date"]).reset_index(drop=True)
                reg = df[df["stype"] == "reg"]
                self.team_last[s] = {t: _d(v) for t, v in reg.groupby("tid")["date"].max().items()}
            self.listings[s] = df
            for pid, p in (st.get("players") or {}).items():
                if p.get("pool"):
                    self.pool[str(pid)] = p["pool"]
                if p.get("name"):
                    self.names[str(pid)] = p["name"]
            for t, x in (st.get("teams") or {}).items():
                if x.get("name"):
                    self.team_names[str(t)] = x["name"]
                if x.get("conference"):
                    self.conf[str(t)] = x["conference"]
            if s == max(seasons):
                self.rosters_now = {str(t): [str(p) for p in (v if isinstance(v, list) else (v or {}).get("players") or [])]
                                    for t, v in ((st.get("meta") or {}).get("rosters") or {}).items()}
        self.seasons = [s for s in seasons if s in self.bounds or s == max(seasons)]
        self.value: dict[int, dict[str, dict]] = {}
        for s in self.seasons:
            v = an.read_json(root / league / str(s) / "value.json") or {}
            cols = v.get("cols") or []
            out = {}
            for r in v.get("rows") or []:
                x = dict(zip(cols, r))
                out[str(x["id"])] = {"war": an.fnum(x.get("war")), "hpm": an.fnum(x.get("hpm")), "min": an.fnum(x.get("min")) or 0.0,
                                     "gp": an.inum(x.get("gp")) or 0, "age": an.fnum(x.get("age")), "pos": x.get("pos"), "team": x.get("team")}
            self.value[s] = out
        self.bio = BIO.players(league)
        self.first_seen: dict[str, int] = {}
        for s in sorted(self.listings):
            for pid in self.listings[s]["pid"].unique():
                self.first_seen.setdefault(pid, s)
        self.cache: dict = {}

    def deadline(self, s: int) -> date:
        if self.league == "nba":
            md = NBA_DEADLINES.get(s)
            if md:
                return date(s, int(md[:2]), int(md[3:]))
            d = date(s, 2, 15)
            while d.weekday() != 3:
                d += timedelta(days=1)
            return d
        md = WNBA_DEADLINES.get(s)
        if md:
            return date(s, int(md[:2]), int(md[3:]))
        lo, hi = self.bounds.get(s, (date(s, 5, 15), date(s, 9, 10)))
        return lo + timedelta(days=int(0.7 * (hi - lo).days))


def season_seq(W: World, s: int) -> dict[str, list[tuple]]:
    """{pid: [(date, tid, sec, stype)] in date order} for the season (regular season, play-in and playoffs)."""
    if ("seq", s) not in W.cache:
        df = W.listings.get(s)
        out: dict[str, list[tuple]] = defaultdict(list)
        if df is not None and len(df):
            for pid, tid, d, sec, st in df.itertuples(index=False):
                out[pid].append((d, tid, sec, st))
        W.cache[("seq", s)] = out
    return W.cache[("seq", s)]


def season_summary(W: World, s: int) -> dict[str, dict]:
    """Per player in the regular season s: the last team, clubs, minutes with that team, his share of its minutes,
    games listed, joined that team during the season."""
    if ("sum", s) in W.cache:
        return W.cache[("sum", s)]
    df = W.listings.get(s)
    out: dict[str, dict] = {}
    if df is not None and len(df):
        reg = df[df["stype"] == "reg"]
        tmin = reg.groupby("tid")["sec"].sum()
        for pid, g in reg.groupby("pid", sort=False):
            last = g.iloc[-1]
            club = last["tid"]
            sec = float(g.loc[g["tid"] == club, "sec"].sum())
            out[pid] = {"club": club, "last": last["date"], "clubs": sorted(set(g["tid"])), "share": sec / max(float(tmin.get(club, 1.0)), 1.0),
                        "joined": 1.0 if g["tid"].iloc[0] != club else 0.0, "first_club": g["tid"].iloc[0], "first": g["date"].iloc[0]}
    W.cache[("sum", s)] = out
    return out


def first_team(W: World, s: int) -> dict[str, str]:
    """{pid: the first team he is listed for in season s (regular season)}."""
    if ("first", s) not in W.cache:
        df = W.listings.get(s)
        out = {}
        if df is not None and len(df):
            reg = df[df["stype"] == "reg"]
            out = reg.groupby("pid")["tid"].first().to_dict()
        W.cache[("first", s)] = out
    return W.cache[("first", s)]


def labelled_next(W: World, s: int) -> bool:
    """Next season's first-team labels are settled: every team of season s has been listed in season s+1."""
    nxt = W.listings.get(s + 1)
    if nxt is None or not len(nxt) or (s + 1) not in W.bounds:
        return False
    if s + 1 < max(W.seasons) or W.bounds[s + 1][1] < W.today - timedelta(days=2):
        return True                                   # next season played in full (teams that folded never block it)
    teams = set(W.wp.get(s, {}))
    seen = set(nxt.loc[nxt["stype"] == "reg", "tid"])
    return len(teams - seen) <= 0 if teams else False


def direct_move(seq: list[tuple], club: str, after: str, until: date | None = None) -> tuple[str | None, str | None, str | None]:
    """The first direct move away from `club` after date `after` in a season's listings: (new team, date first listed
    there, last date listed for club) when the gap is at most SWITCH_GAP days and the new listing is no later than
    `until`; else (None, None, last date listed for club)."""
    last_here = None
    for d, t, sec, st in seq:
        if d < after:
            if t == club:
                last_here = d
            continue
        if t == club:
            last_here = d
            continue
        if last_here is None:
            continue
        gap = ((_d(d) or date.min) - (_d(last_here) or date.min)).days
        if gap <= SWITCH_GAP and (until is None or (_d(d) or date.max) <= until):
            return t, d, last_here
        return None, None, last_here
    return None, None, last_here


# ---------------------------------------------------------------------------------------------- the panel

def phase_of(W: World, today: date) -> tuple[str, float]:
    """("inseason", days since opening night) during a season's first weeks (and before it), else ("offseason", days since
    the last regular-season game) once the season is over. In between (mid-season) the start snapshot is the nearest
    one this module supports and is labelled as such."""
    cur = max(W.seasons)
    b = W.bounds.get(cur)
    if b is None:
        # the season's games are scheduled but not stored with box scores yet: its start
        return "inseason", 0.0
    lo, hi = b
    if today <= hi:
        return "inseason", float(max((today - lo).days, 0))
    return "offseason", float((today - hi).days)


def _yrs(W: World, pid: str, s: int) -> float | None:
    b = W.bio.get(pid) or {}
    deb = b.get("debut") or (b.get("draft") or [None])[0]
    first = W.first_seen.get(pid)
    if deb:
        try:
            return float(s - int(deb))
        except (TypeError, ValueError):
            pass
    if first is not None and first > FIRST[W.league]:
        return float(s - first)
    return None


def panel(W: World, phase: str, x: float = 0.0) -> pd.DataFrame:
    """One row per rostered player per season at the snapshot, with features and labels."""
    recs = []
    cur = max(W.seasons)
    seasons = [s for s in W.seasons if s - 1 in W.listings and s >= max(FIRST[W.league] + 2, PANEL_FIRST[W.league])]
    for s in seasons:
        prev = season_summary(W, s - 1)
        prev2 = season_summary(W, s - 2) if s - 2 in W.listings else {}
        vp = W.value.get(s - 1) or {}
        vp2 = W.value.get(s - 2) or {}
        vc = W.value.get(s) or {}
        wp_prev = W.wp.get(s - 1, {})
        wp_prev2 = W.wp.get(s - 2, {})
        seq = season_seq(W, s)
        bnd = W.bounds.get(s)
        roster: dict[str, dict] = {}
        if phase == "inseason":
            df_s = W.listings.get(s)
            if bnd is not None and df_s is not None and len(df_s) and df_s["stype"].eq("reg").any():
                lo = bnd[0]
                lim = (lo + timedelta(days=OPEN_DAYS)).isoformat()
                reg = df_s[(df_s["stype"] == "reg") & (df_s["date"] <= lim)]
                for pid, tid in reg.groupby("pid")["tid"].first().items():
                    roster[pid] = {"club": tid, "t": lo.isoformat()}
            elif s == cur:
                W.roster_source = "espn_rosters"
                for tid, pids in W.rosters_now.items():
                    for pid in pids:
                        roster[pid] = {"club": tid, "t": W.today.isoformat()}
            if s == cur and not roster:
                continue
            wp = {t: wp_prev.get(t, 0.5) for t in set(wp_prev) | {r["club"] for r in roster.values()}}
            traj = {t: wp_prev.get(t, 0.5) - wp_prev2.get(t, 0.5) for t in wp}
        else:
            summ = season_summary(W, s)
            tl = W.team_last.get(s, {})
            for pid, p in summ.items():
                lastd = _d(p["last"])
                tlast = tl.get(p["club"])
                # still listed late in the season (or in the playoffs)
                post = [r for r in seq.get(pid, []) if r[3] != "reg"]
                club = post[-1][1] if post else p["club"]
                if not post and tlast is not None and lastd is not None and (tlast - lastd).days > RELEASE_LEFT:
                    continue
                roster[pid] = {"club": club, "t": (bnd[1] + timedelta(days=int(x))).isoformat() if bnd else None}
            cw = W.wp.get(s, {})
            wp = {t: cw.get(t, 0.5) for t in cw}
            traj = {t: cw.get(t, 0.5) - wp_prev.get(t, 0.5) for t in cw}
        known_next = labelled_next(W, s)
        nxt_first = first_team(W, s + 1) if known_next else {}
        dl_s = W.deadline(s if phase == "inseason" else s + 1)
        known_dl = dl_s + timedelta(days=LATE_DAYS) <= W.today and (s if phase == "inseason" else s + 1) in W.listings
        seq_next = season_seq(W, s + 1) if (phase == "offseason" and (s + 1) in W.listings) else {}
        for pid, r in roster.items():
            club = r["club"]
            pp, pp2 = prev.get(pid) or {}, prev2.get(pid) or {}
            v1, v2, v0 = vp.get(pid) or {}, vp2.get(pid) or {}, vc.get(pid) or {}
            age = v0.get("age") if phase == "offseason" else None
            if age is None and v1.get("age") is not None:
                age = v1["age"] + 1
            if age is None:
                dob = (W.bio.get(pid) or {}).get("dob")
                if dob:
                    from oddsmarkets.basketball.analytics import bio as BIO
                    age = BIO.season_age(W.league, s, dob)
            yrs = _yrs(W, pid, s)
            pos = pool_of(W.pool.get(pid)) or pool_of(v0.get("pos")) or pool_of(v1.get("pos")) or "F"
            draft = (W.bio.get(pid) or {}).get("draft") or []
            ten = 0
            if phase == "inseason":
                for q in (pp, pp2):
                    if q.get("club") == club:
                        ten += 1
                    else:
                        break
            else:
                cs = season_summary(W, s).get(pid) or {}
                if cs.get("club") == club and not cs.get("joined"):
                    ten = 1
                    if pp.get("club") == club:
                        ten = 2 + (1 if pp2.get("club") == club else 0)
            rec = {"season": s, "pid": pid, "tid": club, "pos": pos, "age": age, "yrs": yrs,
                   "rookie": 1.0 if not pp and not v1 else 0.0, "tenure": float(ten),
                   "new_here": 1.0 if pp.get("club") != club else 0.0,
                   "clubs2": float(len(set(pp.get("clubs") or []) | set(pp2.get("clubs") or []))),
                   "share_prev": pp.get("share"), "gp_prev": (v1.get("gp") or 0) / (82.0 if W.league == "nba" else 40.0),
                   "v_prev": v1.get("war"), "v_prev2": v2.get("war"), "hpm_prev": v1.get("hpm"),
                   "big": 1.0 if pos == "C" else 0.0, "guard": 1.0 if pos == "G" else 0.0,
                   "team_wp": wp.get(club, 0.5), "team_traj": traj.get(club, 0.0),
                   "first_round": 1.0 if len(draft) > 1 and draft[1] == 1 else 0.0, "snap": r["t"]}
            if phase == "offseason":
                cs = season_summary(W, s).get(pid) or {}
                rec.update({"joined": cs.get("joined", 0.0), "share": cs.get("share"), "gp_cur": (v0.get("gp") or 0) / (82.0 if W.league == "nba" else 40.0),
                            "v_cur": v0.get("war"), "hpm_cur": v0.get("hpm"),
                            "clubs2": float(len(set(cs.get("clubs") or []) | set(pp.get("clubs") or [])))})
            # labels
            if phase == "inseason":
                tmove, tdate, last_here = direct_move(seq.get(pid, []), club, r["t"]) if s in W.bounds else (None, None, None)
                if known_dl:
                    dmove, _, _ = direct_move(seq.get(pid, []), club, r["t"], dl_s + timedelta(days=LATE_DAYS))
                    rec["y_dl"] = 1.0 if dmove else 0.0
                    rec["dest_dl"] = dmove
                else:
                    rec["y_dl"], rec["dest_dl"] = np.nan, None
                if known_next:
                    f = nxt_first.get(pid)
                    if f == club:
                        rec["y_next"], rec["y_type"], rec["dest"] = 0.0, -1, None
                    else:
                        tl = W.team_last.get(s, {}).get(club)
                        regs = [q for q in seq.get(pid, []) if q[3] == "reg" and q[1] == club]
                        lh = _d(regs[-1][0]) if regs else None
                        if tmove is not None:
                            typ = 0
                        elif lh is not None and tl is not None and (tl - lh).days >= RELEASE_LEFT:
                            typ = 1
                        else:
                            typ = 2
                        rec["y_next"], rec["y_type"], rec["dest"] = 1.0, typ, f
                else:
                    rec["y_next"], rec["y_type"], rec["dest"] = np.nan, -1, None
            else:
                if known_next:
                    f = nxt_first.get(pid)
                    leave = f != club
                    rec["y_next"], rec["y_type"], rec["dest"] = (1.0, 2, f) if leave else (0.0, -1, None)
                else:
                    rec["y_next"], rec["y_type"], rec["dest"] = np.nan, -1, None
                if known_dl and known_next:
                    f = nxt_first.get(pid)
                    if f == club:
                        nxt_lo = W.bounds[s + 1][0].isoformat()
                        dmove, _, _ = direct_move(seq_next.get(pid, []), club, nxt_lo, dl_s + timedelta(days=LATE_DAYS))
                        rec["y_dl"], rec["dest_dl"] = (1.0 if dmove else 0.0), dmove
                    else:
                        rec["y_dl"], rec["dest_dl"] = 0.0, None
                else:
                    rec["y_dl"], rec["dest_dl"] = np.nan, None
            recs.append(rec)
    df = pd.DataFrame(recs)
    if not len(df):
        return df
    for c in ("age", "yrs", "share_prev", "v_prev", "v_prev2", "hpm_prev", "share", "v_cur", "hpm_cur"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["v_trend"] = (df["v_cur"] if phase == "offseason" else df["v_prev"]).fillna(0) - \
        (df["v_prev"] if phase == "offseason" else df["v_prev2"]).fillna(0)
    if phase == "offseason":
        df["vnow"] = (3 * df["v_cur"].fillna(0) + 2 * df["v_prev"].fillna(0)) / 5
    else:
        df["vnow"] = (3 * df["v_prev"].fillna(0) + 2 * df["v_prev2"].fillna(0)) / 5
    df["rank_pos"] = df.groupby(["season", "tid", "pos"])["vnow"].rank(ascending=False, method="first")
    df["depth"] = df.groupby(["season", "tid", "pos"])["pid"].transform("count")
    df["team_age"] = df.groupby(["season", "tid"])["age"].transform("mean")
    # the team's past turnover: the share of a snapshot roster that left by the next season. At a season-start snapshot
    # last season's share is not settled yet (players first listed later, or never), so it lags one more season.
    tv = df[df["y_next"].notna()].groupby(["season", "tid"])["y_next"].mean()
    lag = 2 if phase == "inseason" else 1
    df["team_turn"] = [tv.get((s - lag, t), np.nan) for s, t in zip(df["season"], df["tid"])]
    df["v_x_reb"] = df["vnow"].fillna(0) * (0.5 - df["team_wp"]).clip(lower=0)
    df["age_x_reb"] = (df["age"] - 27) * (0.5 - df["team_wp"])
    df["vet_x_cont"] = (df["yrs"].fillna(0) >= 8).astype(float) * (df["team_wp"] - 0.5)
    df["y_type"] = df["y_type"].astype(int)
    return df


# ---------------------------------------------------------------------------------------------- configuration and build

WHY = {"rookie": ("a rookie", None), "tenure": ("long tenure here", "short tenure here"),
       "new_here": ("new here this season", "kept from last season"), "joined": ("joined during the season", None),
       "clubs2": ("several teams lately", "settled with one team"), "share": ("a big role", "a small role"),
       "share_prev": ("a big role last season", "a small role last season"), "gp_prev": ("played most games last season", "few games last season"),
       "gp_cur": ("played most games", "few games"),
       "v_prev": ("strong last season", "weak last season"), "v_prev2": ("strong two seasons ago", "weak two seasons ago"),
       "v_cur": ("strong season", "weak season"), "v_trend": ("improving", "declining"),
       "hpm_prev": ("strong impact rate", "weak impact rate"), "hpm_cur": ("strong impact rate", "weak impact rate"),
       "rank_pos": ("behind others at the position", "first choice at the position"),
       "depth": ("a crowded position", "a thin position"), "big": ("a centre", None), "guard": ("a guard", None),
       "team_wp": ("a winning team", "a losing team"), "team_traj": ("team trending up", "team trending down"),
       "team_age": ("an older roster", "a younger roster"), "team_turn": ("a high-turnover team", "a stable team"),
       "first_round": ("a first-round pick", "not a first-round pick"), "v_x_reb": ("value on a rebuilding team", None),
       "age_x_reb": ("a veteran on a rebuilding team", None), "vet_x_cont": ("a veteran on a contender", None)}


def _notes(league: str, phase: str) -> list[str]:
    lg = "NBA" if league == "nba" else "WNBA"
    snap = ("Snapshot: the opening rosters; every feature is from earlier seasons." if phase == "inseason" else
            "Snapshot: after the season; rostered = the team the player was last listed for, if still listed in its last three weeks.")
    return [
        f"Chance of moving: a ridge logistic regression on our own movement history ({lg} box scores and did-not-play lists "
        "since 1997: who was listed for which team on which date), refitted each season and validated on held-out seasons "
        "(Model page). ESPN's transaction list covers only the last two years, so the history is inferred from the box scores.",
        "Traded or claimed: a move straight to another team (listed there within three weeks) before the deadline. A trade and "
        "a waiver claim cannot be told apart without transactions. Leaves: the first team the player is listed for next season is not "
        "this one, or the player is not listed at all.",
        "No contract data: salaries, contract years, options and no-trade clauses are not used, because no source whose terms "
        "allow our use has them. Free agency is inferred from age, years since the debut, tenure and role.",
        snap,
        f"Value is Hardwood WAR, the last two seasons blended 3:2. Positions are pools: guards, forwards, centres.",
        "Outlook: the chance of adding at least one player at the position who was on another team at the snapshot, from a "
        "Poisson model of past arrivals (need there, team strength and trajectory, turnover, expected departures). Draft "
        "picks, two-way call-ups and signings from outside the league are not counted.",
        "Targets: players on other teams who would upgrade the team's weakest regular slot in the pool (its second guard or "
        "forward, its centre), ranked by their chance of joining: the chance the player moves x the chance this team is where they go "
        "(a conditional logit on past moves). An estimate from on-field value and history, not news.",
    ]


def config(league: str, phase: str) -> MV.Config:
    feats = FEATS_START if phase == "inseason" else FEATS_AFTER
    quad = QUAD_START if phase == "inseason" else QUAD_AFTER
    sp = SPLITS[league]
    return MV.Config(level=league, version=VERSION, feats=feats, quad=quad, dl_feats=feats + DL_EXTRA,
                     type_feats=[f for f in feats if f not in ("big", "guard", "depth", "team_age")], arr_feats=ARR_FEATS,
                     types=TYPES, type_label=TYPE_LABEL, dev=sp["dev"], test=sp["test"], slots=SLOTS, contend=CONTEND,
                     rebuild=REBUILD, unit="WAR", age_pivot=28.0, why=WHY, notes=_notes(league, phase),
                     yrs_phrase="{n} seasons in the league", walk_from=None, deadline_label="traded or claimed")


def bucket(phase: str, x: float) -> float:
    return float(round(x / 7) * 7)


def build(league: str, today: date, teams: dict | None = None, data=None) -> dict | None:
    """<league>/movement.json (scripts/build_hardwood.py calls it once a day)."""
    t0 = time.perf_counter()
    W = World(league, today, data)
    if len(W.seasons) < 8:
        return None
    phase, x = phase_of(W, today)
    df = panel(W, phase, x)
    if not len(df):
        return None
    cfg = config(league, phase)
    res = MV.research_cached(df, cfg, W.conf, phase, [bucket(phase, x), W.seasons],
                             an.cache_root() / "movement" / f"research_{league}.json")
    cur = int(df["season"].max())
    names = {pid: W.names.get(pid) for pid in df.loc[df["season"] == cur, "pid"]}
    nxt = cur + 1
    dl = W.deadline(cur if phase == "inseason" else nxt)
    lab = df[df["y_next"].notna()]
    last3 = sorted(lab["season"].unique())[-3:]
    dl_lab = df[df["y_dl"].notna()]
    dl3 = sorted(dl_lab["season"].unique())[-3:]
    recent = {"seasons": [int(s) for s in last3], "next": MV._rr(lab.loc[lab["season"].isin(last3), "y_next"].mean()),
              "deadline": MV._rr(dl_lab.loc[dl_lab["season"].isin(dl3), "y_dl"].mean()) if len(dl_lab) else None,
              "note": "League rates over the last three labelled seasons, for context when a block is not published."}
    pay = MV.payload(df, cfg, W.conf, res, phase, cur, names, today.isoformat(),
                     {"deadline": dl.isoformat(), "next": f"the {nxt} season's first game" if league == "wnba"
                      else f"the {nxt - 1}-{str(nxt)[2:]} season's first game"},
                     extra={"updated_at": an.now(), "league": league, "roster_source": W.roster_source, "recent_rates": recent,
                            "team_names": {t: (v or {}).get("name") for t, v in (teams or {}).items()} or W.team_names})
    log.info("movement %s: %d players, %.1f s", league, len(pay["players"]), time.perf_counter() - t0)
    return _finite(pay)


def _finite(o: Any) -> Any:
    """Non-finite numbers (a metric over an empty base) as None, so the payload is strict JSON."""
    if isinstance(o, dict):
        return {k: _finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_finite(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o
