"""
Player movement for The Quant Bullpen (MLB): every rostered player's chance of being traded before the next trade
deadline and of leaving his club by next season (split into trade, release or waiver, free agency and other), each
club's acquisition outlook by position, and its realistic targets on other clubs. Engine: oddsmarkets/common/movement.py;
method and validation: docs/research/moves_model.md; payload mlb/movement.json (PAYLOADS.md "Movement").

History. The MLB Stats API transactions (cached by analytics/mlbapi.py, October 2014 on; analytics/moves.py parses
them) say who was traded, claimed, released, who elected free agency and who retired, and when. The plate-appearance
tables (valuation.stint_table: per player, club and date) say who played where. A *snapshot* is taken at the same
point of every season as today: during the regular season, the same share of the schedule played; after it, the same
number of days after the last regular-season game. A player is on a club's roster at the snapshot when the last club he
played for that season is that club and no transaction has moved him off it since.

Labels. From the snapshot, the transactions are replayed (a trade or a waiver claim moves him to the other club; a
release, electing free agency or retiring takes him off; a signing, a claim or a purchase by a club puts him there) up
to the next season's first game; he has left when he is then not with the club and does not play for it next season.
The kind of departure is the first move off the club: a trade; a release or waiver (released, claimed by another club,
returned as a Rule 5 pick, or electing free agency after being outrighted or designated); free agency (electing it
otherwise: the end of a contract); other (retired, or gone with no transaction on record). Traded before the deadline:
a trade away from the club between the snapshot and the deadline.

No contract data. Salaries, contract years and options are not used: no source whose terms allow our use has them
(Spotrac, Cot's, Baseball-Reference and FanGraphs forbid this reuse). Free agency is inferred from age, years since
the MLB debut (the service-time proxy: six years is free agency, three to five arbitration), tenure with the club and
role. The page says so.
"""
from __future__ import annotations

import glob
import json
import logging
import math
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.common import movement as MV

log = logging.getLogger(__name__)

VERSION = "bullpen-movement-1"
LEVEL = "mlb"
FIRST = 2015
# trade deadlines (non-waiver deadline; 2020: the shortened season's)
DEADLINES = {2015: "07-31", 2016: "08-01", 2017: "07-31", 2018: "07-31", 2019: "07-31", 2020: "08-31", 2021: "07-30",
             2022: "08-02", 2023: "08-01", 2024: "07-30", 2025: "07-31", 2026: "07-31"}
DEFAULT_DEADLINE = "07-31"
TYPES = ("trade", "release", "free_agency", "other")
TYPE_LABEL = {"trade": "Trade", "release": "Release or waiver", "free_agency": "Free agency", "other": "Other (retirement, no record)"}
# pre-registered split (docs/research/moves_model.md, written before the sealed seasons were scored)
DEV = [2018, 2019, 2020, 2021, 2022]
TEST = [2023, 2024, 2025]
SLOTS = {"SP": 5, "RP": 7}
MIN_SHARE_CAND = 0.0
CONTEND, REBUILD = 0.53, 0.46

FEATS = ["age", "yrs", "arb", "fa_elig", "walk", "tenure", "joined", "clubs2", "share", "share_prev", "v_cur", "v_prev", "v_trend",
         "rank_pos", "depth", "pitcher", "starter", "il_cur", "il_prev", "team_wp", "team_traj", "team_age", "team_turn"]
QUAD = ["age", "v_cur", "share"]
# traded before the deadline: the same plus the walk year and how a rebuilding or contending club treats value and age
DL_FEATS = FEATS + ["walk", "walk_x_wp", "v_x_reb", "v_x_walk", "age_x_reb"]
TYPE_FEATS = ["age", "yrs", "fa_elig", "arb", "tenure", "joined", "share", "v_cur", "v_prev", "rank_pos", "pitcher", "team_wp",
              "team_traj", "il_cur"]
ARR_FEATS = ["need", "team_wp", "team_traj", "team_turn", "exp_out", "n_pos"]
DEST_FEATS = ["gain", "need", "wp_x_age", "wp_x_v", "turn", "exp_out_pos", "same_league"]


# ---------------------------------------------------------------------------------------------- inputs

def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def deadline(season: int) -> date:
    md = DEADLINES.get(season, DEFAULT_DEADLINE)
    return date(season, int(md[:2]), int(md[3:]))


def _rows_from_cache(season: int) -> list[dict] | None:
    fs = sorted(glob.glob(str(an.cache_root() / "value" / f"rows_{LEVEL}_{season}_*.json")), key=lambda p: Path(p).stat().st_mtime)
    return an.read_json(Path(fs[-1])) if fs else None


class World:
    """Everything the panel needs, loaded once: plate-appearance stints, value rows, parsed transactions, season bounds,
    team records, people."""

    def __init__(self, today: date, rows: dict[int, list[dict]] | None = None, parsed: list[dict] | None = None,
                 il: dict | None = None, teams: dict | None = None):
        from oddsmarkets.baseball.analytics import moves as M
        from oddsmarkets.baseball.analytics import valuation as VA
        self.today = today
        seasons = [s for s in an.seasons_on_disk(LEVEL) if s >= FIRST]
        self.rows: dict[int, list[dict]] = {}
        for s in seasons:
            r = (rows or {}).get(s) or _rows_from_cache(s)
            if r:
                self.rows[s] = r
        self.stints: dict[int, pd.DataFrame] = {}
        for s in seasons:
            try:
                st = VA.stint_table(LEVEL, s)
            except Exception as exc:                    # noqa: BLE001
                log.warning("stints %s: %s", s, exc)
                st = None
            if st is not None and len(st):
                st = st.copy()
                st["pid"] = st["pid"].astype(str)
                st["tid"] = st["tid"].astype(str)
                self.stints[s] = st
        self.seasons = sorted(s for s in seasons if s in self.stints and s in self.rows)
        stores = {s: an.load_store(LEVEL, s) for s in self.seasons}
        self.bounds = M.season_bounds(stores)
        self.wp = {s: _win_pct(stores[s]) for s in self.seasons}
        self.league = {}
        for s in self.seasons:
            for t, x in ((stores[s] or {}).get("teams") or {}).items():
                if x.get("league") in ("AL", "NL"):
                    self.league[str(t)] = x.get("league")
        self.mlb_teams = {t for s in self.seasons for t, x in self.wp[s].items()} & (set(self.league) or set(self.wp[self.seasons[-1]]))
        if parsed is None:
            from oddsmarkets.baseball.analytics import mlbapi
            from oddsmarkets.baseball.analytics.moves_build import TX_FIRST
            parsed = M.parse_all(mlbapi.transactions(LEVEL, TX_FIRST, today, None, today=today))
        self.tx: dict[str, list[dict]] = defaultdict(list)
        for t in parsed:
            if t.get("pid") and t.get("date"):
                self.tx[str(t["pid"])].append(t)
        for v in self.tx.values():
            v.sort(key=lambda t: (t["date"], t.get("id") or 0))
        if il is None:
            il = VA.il_table(M.il_days(M.il_stints(parsed), self.bounds, today))
        self.il = il
        self.people = an.load_people()
        self.teams = teams or {}
        self.cache: dict = {}
        self.names: dict[str, str] = {}
        for s in self.seasons:
            for r in self.rows[s]:
                self.names[str(r["pid"])] = r.get("name")


def _win_pct(store: dict) -> dict[str, float]:
    w: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for g in ((store or {}).get("games") or {}).values():
        if g.get("gtype") != "R" or g.get("status") != "final" or g.get("hs") is None or g.get("as") is None:
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        hw = 1 if g["hs"] > g["as"] else 0
        w[h][0] += hw
        w[h][1] += 1
        w[a][0] += 1 - hw
        w[a][1] += 1
    return {t: (x[0] + 40.5) / (x[1] + 81.0) for t, x in w.items() if x[1]}    # shrunk half a season towards .500


# ---------------------------------------------------------------------------------------------- snapshots

def phase_of(W: World, today: date) -> tuple[str, float]:
    """("inseason", share of the schedule played) or ("offseason", days since the last regular-season game) for today."""
    cur = max(W.seasons)
    lo, hi = W.bounds[cur]
    if today < lo:                                       # before opening day: the previous season's offseason
        prev = W.bounds.get(cur - 1, (lo, hi))[1]
        return "offseason", float((today - prev).days)
    if today <= hi:
        return "inseason", (today - lo).days / max((hi - lo).days, 1)
    return "offseason", float((today - hi).days)


def snap_date(W: World, s: int, phase: str, x: float) -> date:
    lo, hi = W.bounds[s]
    if phase == "inseason":
        return lo + timedelta(days=int(round(x * (hi - lo).days)))
    return hi + timedelta(days=int(min(max(x, 1.0), 150.0)))


def _season_info(W: World, s: int, upto: date | None) -> dict:
    key = (s, upto)
    if key not in W.cache:
        W.cache[key] = _season_info_(W, s, upto)
    return W.cache[key]


def _season_info_(W: World, s: int, upto: date | None) -> dict:
    """Per player in season s up to `upto` (None: the whole season): last club and date, clubs, usage by club, his
    share of his last club's usage, joined that club during the season."""
    st = W.stints[s]
    if upto is not None:
        st = st[st["date"] <= upto.isoformat()]
    if not len(st):
        return {}
    tot = st.groupby(["kind", "tid"])["n"].sum()
    g = st.sort_values("date")
    out: dict[str, dict] = {}
    first_date = W.bounds[s][0].isoformat()
    for (pid, kind), grp in g.groupby(["pid", "kind"], sort=False):
        last = grp.iloc[-1]
        club = str(last["tid"])
        n_club = float(grp.loc[grp["tid"] == club, "n"].sum())
        share = n_club / max(float(tot.get((kind, club), 1.0)), 1.0)
        joined = 1.0 if (grp["tid"].iloc[0] != club) else 0.0
        rec = out.get(pid)
        cand = {"club": club, "last": str(last["date"]), "kind": kind, "n": float(grp["n"].sum()), "share": share,
                "clubs": sorted(set(grp["tid"])), "joined": joined, "first_club_date": str(grp.loc[grp["tid"] == club, "date"].iloc[0]),
                "start": str(grp["date"].iloc[0]) <= (W.bounds[s][0] + timedelta(days=10)).isoformat() or str(grp["date"].iloc[0]) <= first_date}
        if rec is None or cand["n"] * (1.0 if kind == "H" else 1.15) > rec["n"] * (1.0 if rec["kind"] == "H" else 1.15):
            if rec is not None:
                cand["clubs"] = sorted(set(cand["clubs"]) | set(rec["clubs"]))
            out[pid] = cand
        else:
            rec["clubs"] = sorted(set(cand["clubs"]) | set(rec["clubs"]))
    return out


DEPART_ANY = ("release", "free_agency", "retired")


def replay(events: list[dict], club: str, lo: date, hi: date, mlb: set[str]) -> tuple[str | None, str | None, date | None, list]:
    """Replay a player's transactions in (lo, hi] from `club`: (club at hi or None, kind of the first move off the
    starting club, its date, [clubs he joined]). Kinds: trade, release, free_agency, other."""
    cur: str | None = club
    first, fdate = None, None
    prior_out = False
    joined = []
    lo_s, hi_s = lo.isoformat(), hi.isoformat()
    for e in events:
        d = e["date"]
        if d <= lo_s:
            continue
        if d > hi_s:
            break
        k, f, to = e["kind"], e.get("from"), e.get("to")
        f = str(f) if f is not None else None
        to = str(to) if to is not None else None
        club_of = to or f
        if k in ("outright", "dfa") and cur is not None and (f == cur or club_of == cur):
            prior_out = True
            continue
        if k in ("trade", "claim", "returned", "rule5"):
            if cur is not None and f == cur and to != cur:
                if first is None and cur == club:
                    first, fdate = ("trade" if k == "trade" else "release"), _d(d)
                cur = to if to in mlb else None
                if cur:
                    joined.append(cur)
            elif to in mlb and to != cur:
                cur = to
                joined.append(cur)
            continue
        if k in DEPART_ANY:
            if cur is not None and club_of == cur:
                if first is None and cur == club:
                    first = "release" if (k == "release" or prior_out) else ("other" if k == "retired" else "free_agency")
                    fdate = _d(d)
                cur = None
            continue
        if k in ("signing", "signing_minor", "purchase", "selected"):
            if to in mlb and to != cur:
                cur = to
                joined.append(cur)
    return cur, first, fdate, joined


def _prior_out(events: list[dict], club: str, lo: date, hi: date) -> bool:
    """Outrighted or designated by the club in (lo, hi] (a departure with no record after it reads as a release)."""
    lo_s, hi_s = lo.isoformat(), hi.isoformat()
    for e in events:
        if lo_s < e["date"] <= hi_s and e["kind"] in ("outright", "dfa") and club in (str(e.get("from")), str(e.get("to"))):
            return True
    return False


# ---------------------------------------------------------------------------------------------- the panel

def _value(rows: list[dict]) -> dict[str, dict]:
    """{pid: {war, pos, age, kind}} with the kind of the larger usage."""
    out: dict[str, dict] = {}
    for r in rows:
        pid = str(r["pid"])
        n = float(r.get("n") or 0) * (1.0 if r["kind"] == "H" else 1.15)
        if pid not in out or n > out[pid]["_n"]:
            out[pid] = {"war": an.fnum(r.get("war")), "pos": r.get("pos"), "age": an.fnum(r.get("age")), "kind": r["kind"],
                        "team": str(r.get("team")) if r.get("team") is not None else None, "_n": n, "g": r.get("g")}
    return out


def panel(W: World, phase: str, x: float, seasons: list[int] | None = None) -> pd.DataFrame:
    """One row per rostered player per season at the snapshot, with features, labels and the arrival bookkeeping."""
    seasons = seasons or [s for s in W.seasons if s - 1 in W.seasons]
    recs = []
    turn_prev: dict[tuple, float] = {}
    for s in sorted(seasons):
        t = snap_date(W, s, phase, x)
        upto = t if phase == "inseason" else None
        info = _season_info(W, s, upto)
        info_prev = _season_info(W, s - 1, None) if s - 1 in W.stints else {}
        info_prev2 = _season_info(W, s - 2, None) if s - 2 in W.stints else {}
        val = _value(W.rows[s]) if phase == "offseason" else {}
        val_prev = _value(W.rows.get(s - 1) or [])
        val_prev2 = _value(W.rows.get(s - 2) or [])
        nxt = s + 1
        dl = deadline(nxt if phase == "offseason" else s)
        end_next = W.bounds[nxt][0] if nxt in W.bounds else None
        known_next = nxt in W.stints and end_next is not None and end_next <= W.today
        known_dl = dl <= W.today
        info_next = _season_info(W, nxt, None) if nxt in W.stints else {}
        first_next = {}
        if nxt in W.stints:
            g = W.stints[nxt].sort_values("date")
            first_next = g.groupby("pid")["tid"].first().to_dict()
            all_next = g.groupby("pid")["tid"].agg(lambda v: set(v)).to_dict()
        else:
            all_next = {}
        # inside the season: rows played since the snapshot (the in-season arrival check)
        after = None
        if phase == "inseason":
            st = W.stints[s]
            after = st[st["date"] > t.isoformat()].groupby("pid")["tid"].agg(lambda v: set(v)).to_dict()
        wp = W.wp.get(s, {})
        wp_prev = W.wp.get(s - 1, {})
        if phase == "inseason":                          # standings to the snapshot are not stored per date: blend
            wp = {k: (1 - x) * wp_prev.get(k, 0.5) + x * v for k, v in wp.items()}
        for pid, p in info.items():
            club = p["club"]
            if club not in W.mlb_teams:
                continue
            ev = W.tx.get(pid, [])
            # gone already between his last game and the snapshot
            cur, first, fdate, _ = replay(ev, club, _d(p["last"]), t, W.mlb_teams)
            if first is not None or cur != club:
                continue
            v = val.get(pid) or {}
            vp = val_prev.get(pid) or {}
            vp2 = val_prev2.get(pid) or {}
            pos = v.get("pos") or vp.get("pos") or ("RP" if p["kind"] == "P" else "DH")
            age = v.get("age") if v.get("age") is not None else (vp.get("age") + 1 if vp.get("age") is not None else None)
            person = W.people.get(pid) or {}
            if age is None and person.get("birth"):
                age = an.age_on(person.get("birth"), s)
            debut = person.get("debut")
            yrs = (s - int(debut) + 1) if debut else None
            ten = 0
            for prev_info in (info_prev, info_prev2):
                if (prev_info.get(pid) or {}).get("club") == club:
                    ten += 1
                else:
                    break
            if p["joined"]:
                ten = 0
            share_prev = (info_prev.get(pid) or {}).get("share")
            clubs2 = len(set(p["clubs"]) | set((info_prev.get(pid) or {}).get("clubs") or []))
            v_cur = v.get("war") if phase == "offseason" else None
            v_prev = vp.get("war")
            il_cur = (W.il.get(pid) or {}).get(s, 0) if phase == "offseason" else None
            il_prev = (W.il.get(pid) or {}).get(s - 1, 0)
            rec = {"season": s, "pid": pid, "tid": club, "kind": p["kind"], "pos": pos, "age": age, "yrs": yrs,
                   "arb": 1.0 if yrs is not None and 3 <= yrs <= 6 else 0.0, "fa_elig": 1.0 if yrs is not None and yrs >= 7 else 0.0,
                   "tenure": ten, "joined": p["joined"], "clubs2": clubs2, "share": p["share"], "share_prev": share_prev,
                   "v_cur": v_cur, "v_prev": v_prev, "v_prev2": vp2.get("war"), "il_cur": il_cur, "il_prev": il_prev,
                   "pitcher": 1.0 if p["kind"] == "P" else 0.0, "starter": 1.0 if pos == "SP" else 0.0,
                   "team_wp": wp.get(club, 0.5), "team_traj": wp.get(club, 0.5) - wp_prev.get(club, 0.5), "snap": t.isoformat()}
            # labels
            if known_next:
                cur2, first2, fdate2, joined2 = replay(ev, club, t, end_next, W.mlb_teams)
                fn = first_next.get(pid)
                plays_here = club in all_next.get(pid, set())
                if cur2 == club:
                    # with the club on opening day by the record; a player who instead opens the season elsewhere with
                    # no move on record at all (a missing transaction) has left
                    later = replay(ev, club, end_next, W.bounds[nxt][1], W.mlb_teams)[1] if nxt in W.bounds else None
                    if not plays_here and fn is not None and fn != club and later is None:
                        leave, typ, dest = 1, TYPES.index("other"), fn
                    else:
                        leave, typ, dest = 0, -1, None
                else:
                    leave = 1
                    if first2 in TYPES:
                        typ = TYPES.index(first2)
                    else:
                        typ = TYPES.index("release") if _prior_out(ev, club, t, end_next) else TYPES.index("other")
                    dest = cur2 if cur2 else (fn if fn and fn != club else None)
                rec["y_next"] = float(leave)
                rec["y_type"] = typ if leave else -1
                rec["dest"] = dest if leave else None
            else:
                rec["y_next"] = np.nan
                rec["y_type"] = -1
                rec["dest"] = None
            if known_dl:
                traded = any(e["kind"] == "trade" and str(e.get("from")) == club and t.isoformat() < e["date"] <= dl.isoformat() for e in ev)
                rec["y_dl"] = 1.0 if traded else 0.0
                # where he went before the deadline (the in-season acquisitions)
                if phase == "inseason":
                    cur3, first3, _, _ = replay(ev, club, t, dl, W.mlb_teams)
                    rec["dest_dl"] = cur3 if (first3 is not None and cur3 and cur3 != club) else None
                else:
                    rec["dest_dl"] = None
            else:
                rec["y_dl"] = np.nan
                rec["dest_dl"] = None
            recs.append(rec)
    df = pd.DataFrame(recs)
    if not len(df):
        return df
    # value now: this season's WAR after it, last season's (prorated) during it
    df["v_cur"] = df["v_cur"].astype(float)
    df["v_prev"] = pd.to_numeric(df["v_prev"], errors="coerce")
    df["v_trend"] = df["v_cur"].fillna(df["v_prev"]) - df["v_prev"].fillna(0)
    df["vnow"] = (3 * df["v_cur"].fillna(df["v_prev"]).fillna(0) + 2 * df["v_prev"].fillna(0)) / 5 if phase == "offseason" else \
        (3 * df["v_prev"].fillna(0) + 2 * pd.to_numeric(df["v_prev2"], errors="coerce").fillna(0)) / 5
    df["rank_pos"] = df.groupby(["season", "tid", "pos"])["vnow"].rank(ascending=False, method="first")
    df["depth"] = df.groupby(["season", "tid", "pos"])["pid"].transform("count")
    df["team_age"] = df.groupby(["season", "tid"])["age"].transform("mean")
    # past turnover: the share of the club's snapshot roster that left by the next season, the season before
    tv = df[df["y_next"].notna()].groupby(["season", "tid"])["y_next"].mean()
    df["team_turn"] = [tv.get((s - 1, t), np.nan) for s, t in zip(df["season"], df["tid"])]
    return df


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in ("il_cur", "il_prev"):
        df[c] = pd.to_numeric(df[c], errors="coerce").clip(upper=186)
    df["walk"] = df["yrs"].isin([6, 7]).astype(float)             # the last season or two before free agency
    df["walk_x_wp"] = df["walk"] * (df["team_wp"] - 0.5)
    df["v_x_reb"] = df["vnow"].fillna(0) * (0.5 - df["team_wp"]).clip(lower=0)
    df["v_x_walk"] = df["vnow"].fillna(0) * df["walk"]
    df["age_x_reb"] = (df["age"] - 28) * (0.5 - df["team_wp"])
    return df




# ---------------------------------------------------------------------------------------------- configuration and build

WHY = {"fa_elig": ("free-agent service (7+ seasons)", "years before free agency"),
       "walk": ("a year or two from free agency", None), "arb": ("arbitration years", "pre-arbitration years"),
       "tenure": ("long tenure here", "short tenure here"), "joined": ("joined this season", None),
       "clubs2": ("several clubs lately", "settled with one club"), "share": ("a big role", "a small role"),
       "share_prev": ("a big role last season", "a small role last season"),
       "v_cur": ("strong season", "weak season"), "v_prev": ("strong last season", "weak last season"),
       "v_trend": ("improving", "declining"), "rank_pos": ("behind others at his position", "first choice at his position"),
       "depth": ("a crowded position", "a thin position"), "pitcher": ("pitcher", "position player"), "starter": ("starter", None),
       "il_cur": ("injured-list time", "healthy"), "il_prev": ("injured-list time last season", None),
       "team_wp": ("a winning club", "a losing club"), "team_traj": ("club trending up", "club trending down"),
       "team_age": ("an older roster", "a younger roster"), "team_turn": ("a high-turnover club", "a stable club"),
       "v_x_reb": ("value on a rebuilding club", None), "v_x_walk": ("value in his walk year", None),
       "age_x_reb": ("a veteran on a rebuilding club", None)}

NOTES = [
    "Chance of moving: a ridge logistic regression on our own movement history (MLB Stats API transactions from October "
    "2014 and who played where), refitted each season and validated on held-out seasons (Model page).",
    "No contract data: salaries, contract years, options and no-trade clauses are not used, because no source whose terms "
    "allow our use has them. Free agency is inferred from age, years since the MLB debut (the service-time proxy: six "
    "years for free agency, three to five for arbitration), tenure with the club and role.",
    "Value is Bullpen WAR, the last two seasons blended 3:2. Rostered: the last club he played for this season, with no "
    "move off it since.",
    "Outlook: the chance of adding at least one player at the position who was on another MLB club, by next season, from "
    "a Poisson model of past arrivals (need there, club strength and trajectory, turnover, expected departures). Prospects "
    "from the club's own system and signings from outside MLB are not counted.",
    "Targets: players on other clubs who would upgrade the club's weakest regular slot at their position (the fifth "
    "starter, the seventh reliever, else the regular), ranked by their chance of joining it: the chance he moves x the "
    "chance this club is where he goes (a conditional logit on past moves: the upgrade, the need, contenders and veterans, "
    "rebuilders and youth, turnover, same league). An estimate from on-field value and history, not news.",
]

CFG = MV.Config(level=LEVEL, version=VERSION, feats=FEATS, quad=QUAD, dl_feats=DL_FEATS, type_feats=TYPE_FEATS, arr_feats=ARR_FEATS,
                types=TYPES, type_label=TYPE_LABEL, dev=DEV, test=TEST, slots=SLOTS, contend=CONTEND, rebuild=REBUILD, unit="WAR",
                age_pivot=29.0, why=WHY, notes=NOTES, yrs_phrase="{n} seasons since his debut", walk_from=6, deadline_label="traded")


def frame(W: World, phase: str, x: float) -> pd.DataFrame:
    return _finish(panel(W, phase, x))


def research(W: World, phase: str, x: float, dev: list[int] | None = None, test: list[int] | None = None) -> dict:
    return MV.research(frame(W, phase, x), CFG, W.league, phase, dev, test)


def bucket(phase: str, x: float) -> float:
    return float(round(x / 5) * 5) if phase == "offseason" else round(x * 20) / 20


def build(today: date, rows=None, parsed=None, il=None, teams=None) -> dict | None:
    """mlb/movement.json for the build (value_build.write_movement calls it with the valuation context)."""
    t0 = time.perf_counter()
    W = World(today, rows, parsed, il, teams)
    if len(W.seasons) < 6:
        return None
    phase, x = phase_of(W, today)
    df = frame(W, phase, x)
    res = MV.research_cached(df, CFG, W.league, phase, [bucket(phase, x), W.seasons],
                             an.cache_root() / "movement" / f"research_{LEVEL}.json")
    cur = max(W.seasons)
    names = {pid: (W.names.get(pid) or (W.people.get(pid) or {}).get("name")) for pid in df.loc[df["season"] == cur, "pid"]}
    dl = deadline(cur + 1 if phase == "offseason" else cur)
    pay = MV.payload(df, CFG, W.league, res, phase, cur, names, today.isoformat(),
                     {"deadline": dl.isoformat(), "next": f"{cur + 1} opening day"},
                     extra={"updated_at": an.now(), "team_names": {t: (x or {}).get("name") for t, x in (teams or {}).items()}})
    log.info("movement %s: %d players, %.1f s", LEVEL, len(pay["players"]), time.perf_counter() - t0)
    return pay
