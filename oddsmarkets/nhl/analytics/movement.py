"""
Player movement for The Quant Rink (NHL): every rostered player's chance of moving to another club before the trade
deadline and of not being in the club's lineup next season (split into trade, release or waiver, other), each club's
acquisition outlook by position, and its realistic targets on other clubs. Engine: oddsmarkets/common/movement.py;
method and validation: docs/research/moves_model.md (shared) and docs/research/moves_rink.md (this sport); payload
<S>/movement.json (PAYLOADS.md "Movement").

History. The NHL box scores (analytics/gamelog.box_rows, every regular-season game from 2009-10: who dressed for which
club, time on ice) say who played where and when; the value payloads (<S>/value.json, Rink WAR, 2010-11 on) give the
value currency; the season stores give dates, standings points and birth dates. ESPN's NHL transactions are cached only
from March 2024 (sources/moves.py), so the kind of a departure is known from them for the 2024-25 season's departures
only; everything else is read from the games.

Snapshot. The same point of every season as today: in season, the same share of the regular season's dates; after
it, the same number of days after the last regular-season game. A player is on a club's roster at the snapshot when
the last club he played for that season (to the snapshot) is that club.

Labels (inferred from games, never from text):
  y_dl    he next plays for another NHL club, his last game for this club falling before the deadline and his first
          for the new one within three weeks of it: a trade or a waiver claim (the games cannot tell which; the page says
          "traded or claimed").
  y_next  his first NHL game of the next season is not for this club, or he plays no NHL game next season ("not in
          the lineup next season": traded, released, signed elsewhere, retired, or in the minors all season). A season
          is labelled once the next regular season is complete, so the latest labels are two seasons back live; in the
          backtest the season before the one predicted is labelled with hindsight (a mild optimism, stated).
  y_type  only where ESPN rows cover the window (2024-25): the first trade naming him (trade), waivers, a claim, a
          release or a buy-out (release or waiver), else other (free agency, retirement, minors). With one typed
          season the split cannot be validated: the page shows those shares as base rates, labelled.

No contract data: cap hits, terms, no-trade clauses and RFA/UFA status are not used (CapFriendly, PuckPedia and Spotrac
forbid this reuse). Unrestricted free agency (27 or older, or seven seasons) is inferred from age and years since the
draft, with tenure and role.

Clubs are compared by franchise (Atlanta = Winnipeg, Phoenix/Arizona = Utah), so a relocation is not a departure.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.common import movement as MV
from oddsmarkets.nhl import analytics as an

log = logging.getLogger(__name__)

VERSION = "rink-movement-1"
LEVEL = "nhl"
FIRST_VALUE = 20102011
FIRST_PANEL = 20112012
FRANCHISE = {"ATL": "WPG", "PHX": "UTA", "ARI": "UTA"}
DEADLINES = {20112012: "2012-02-27", 20122013: "2013-04-03", 20132014: "2014-03-05", 20142015: "2015-03-02",
             20152016: "2016-02-29", 20162017: "2017-03-01", 20172018: "2018-02-26", 20182019: "2019-02-25",
             20192020: "2020-02-24", 20202021: "2021-04-12", 20212022: "2022-03-21", 20222023: "2023-03-03",
             20232024: "2024-03-08", 20242025: "2025-03-07", 20252026: "2026-03-06"}
DEADLINE_DEFAULT_MD = "03-05"          # a season whose deadline is not in the table: about the first Friday of March
MOVE_LAG = 21                          # days after the deadline by which a moved player's first game for his new club falls
TYPES = ("trade", "release", "other")
TYPE_LABEL = {"trade": "Trade", "release": "Waivers, claim, release or buy-out", "other": "Other (free agency, retirement, minors)"}
POS = {"C": "C", "L": "LW", "R": "RW", "D": "D", "G": "G"}
# the weakest regular slot a target must beat: third-line centre and wingers, second-pair defence, the starting goalie
SLOTS = {"C": 3, "LW": 3, "RW": 3, "D": 4, "G": 1}
CONTEND, REBUILD = 0.60, 0.50          # points share (points / 2 per game; the league mean is about 0.555), shrunk
WP_MID = 0.555
UFA_AGE = 27.0
ESPN_FROM = date(2024, 3, 13)          # first day of the cached ESPN transactions
# pre-registered split (docs/research/moves_rink.md, committed before the sealed seasons were scored)
DEV = [20132014, 20142015, 20152016, 20162017, 20172018, 20182019, 20192020, 20202021, 20212022]
TEST = [20222023, 20232024, 20242025]
# the engine walks seasons as consecutive integers (s - 1, cur - 2): it sees the season's start year
DEV_Y = [an.start_year(s) for s in DEV]
TEST_Y = [an.start_year(s) for s in TEST]

FEATS = ["age", "ufa", "yrs", "tenure", "joined", "clubs2", "share", "gp_share", "share_prev", "gp_prev", "v_cur", "v_prev",
         "v_trend", "rank_pos", "depth", "goalie", "defence", "team_wp", "team_traj", "team_age", "team_turn"]
QUAD = ["age", "share", "v_prev"]
DL_FEATS = FEATS + ["ufa_x_reb", "v_x_reb", "age_x_reb", "v_x_ufa"]
TYPE_FEATS = ["age", "ufa", "share", "v_prev", "team_wp"]
ARR_FEATS = ["need", "team_wp", "team_traj", "team_turn", "exp_out", "n_pos"]


def _d(s: Any) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def fr(team: Any) -> str | None:
    """The franchise's current code (relocations are not departures)."""
    if team is None:
        return None
    t = str(team)
    return FRANCHISE.get(t, t)


def deadline(season: int) -> date:
    d = DEADLINES.get(int(season))
    if d:
        return date.fromisoformat(d)
    y = an.end_year(int(season))
    return date(y, int(DEADLINE_DEFAULT_MD[:2]), int(DEADLINE_DEFAULT_MD[3:]))


def _prev(s: int, k: int = 1) -> int:
    for _ in range(k):
        s = an.prev_season(s)
    return s


def _next(s: int) -> int:
    return an.season_id(an.start_year(s) + 1)


# ---------------------------------------------------------------------------------------------- inputs

class World:
    """Appearances by club and date, value, season bounds, club strength, people, drafts and ESPN typed moves."""

    def __init__(self, today: date, seasons: list[int] | None = None, espn: bool = True):
        from oddsmarkets.nhl.analytics import gamelog as GL
        from oddsmarkets.nhl.analytics import valuation as VV
        self.today = today
        self.cache: dict = {}
        on_disk = [s for s in an.seasons_on_disk() if s >= FIRST_VALUE]
        if seasons is not None:
            on_disk = [s for s in on_disk if s in set(seasons)]
        self.app: dict[int, pd.DataFrame] = {}
        self.bounds: dict[int, tuple[date, date]] = {}
        self.games: dict[int, pd.DataFrame] = {}
        self.people: dict[str, dict] = {}
        self.names: dict[str, str] = {}
        self.league: dict[str, str] = {}
        for s in on_disk:
            st = an.load_store(s) if s == max(on_disk) else (an.read_json(an.store_path(s)) or {})
            g = [x for x in (st.get("games") or {}).values() if int(x.get("type") or 0) == 2 and x.get("date")]
            if not g:
                continue
            ds = sorted(str(x["date"])[:10] for x in g)
            self.bounds[s] = (date.fromisoformat(ds[0]), date.fromisoformat(ds[-1]))
            gr = [{"date": str(x["date"])[:10], "home": fr(x["home"]), "away": fr(x["away"]), "hs": x.get("hs"), "as": x.get("as"),
                   "ot": bool(x.get("ot") or x.get("so"))} for x in g if x.get("status") == "final" and x.get("hs") is not None]
            self.games[s] = pd.DataFrame(gr)
            date_of = {int(x["game_id"]): str(x["date"])[:10] for x in g}
            for pid, p in (st.get("players") or {}).items():
                if isinstance(p, dict):
                    self.people[str(pid)] = {**self.people.get(str(pid), {}), **{k: v for k, v in p.items() if v is not None}}
                    if p.get("name"):
                        self.names[str(pid)] = p["name"]
            for t, x in (st.get("teams") or {}).items():
                if isinstance(x, dict) and x.get("conference"):
                    self.league[fr(t)] = x.get("conference")
            try:
                sk, gk, _ = GL.box_rows(s)
            except Exception as exc:                        # noqa: BLE001
                log.warning("box rows %s: %s", s, exc)
                continue
            parts = []
            if len(sk):
                a = sk[["game_id", "team", "pid", "pos", "toi"]].copy()
                a["kind"] = "S"
                parts.append(a)
            if len(gk):
                b = gk[["game_id", "team", "pid", "toi"]].copy()
                b["pos"] = "G"
                b["kind"] = "G"
                parts.append(b)
            if not parts:
                continue
            ap = pd.concat(parts, ignore_index=True)
            ap["game_id"] = ap["game_id"].astype(int)
            ap = ap[(ap["game_id"] // 10000) % 100 == 2]
            ap["date"] = ap["game_id"].map(date_of)
            ap = ap.dropna(subset=["date"])
            ap["pid"] = ap["pid"].astype(str)
            ap["team"] = ap["team"].map(fr)
            ap["toi"] = pd.to_numeric(ap["toi"], errors="coerce").fillna(0.0)
            ap = ap[ap["toi"] > 0]
            self.app[s] = ap.sort_values(["date", "game_id"]).reset_index(drop=True)
        self.value: dict[int, dict[str, dict]] = {}
        for s, x in VV.value_rows().items():
            d: dict[str, dict] = {}
            for r in x["rows"]:
                pid = str(r.get("id"))
                if pid not in d or (r.get("toi") or 0) > (d[pid].get("toi") or 0):
                    d[pid] = {"war": an.fnum(r.get("war")), "pos": r.get("pos"), "kind": r.get("kind"), "age": an.fnum(r.get("age")),
                              "toi": an.fnum(r.get("toi"))}
                if r.get("name"):
                    self.names.setdefault(pid, r["name"])
            self.value[s] = d
        self.seasons = sorted(s for s in self.app if s in self.bounds)
        self.draft = self._drafts()
        self.espn = self._espn(today) if espn else {}

    def _drafts(self) -> dict[str, int]:
        try:
            from oddsmarkets.nhl.sources import moves as SM
            dr = SM.drafts(list(range(2005, self.today.year + 1)), fetch=False)
        except Exception as exc:                            # noqa: BLE001
            log.warning("drafts: %s", exc)
            return {}
        out = {}
        for y, d in dr.items():
            cols = d.get("cols") or []
            for r in d.get("rows") or []:
                rec = dict(zip(cols, r))
                if rec.get("pid"):
                    out.setdefault(str(rec["pid"]), int(y))
        return out

    def _espn(self, today: date) -> dict[str, list[tuple[str, str, str]]]:
        """{pid: [(date, kind, club)]} from the cached ESPN rows: kind trade / release (waivers, claim, release, buy-out),
        club the row's club (for a claim: the claiming club)."""
        try:
            from oddsmarkets.nhl.analytics import moves as MO
            from oddsmarkets.nhl.sources import moves as SM
        except Exception:                                   # noqa: BLE001
            return {}
        rows = SM.tx_rows([y for y in range(ESPN_FROM.year, today.year + 1)])
        if not rows:
            return {}
        stores = {s: (an.read_json(an.store_path(s)) or {}) for s in self.seasons[-4:]}
        pidx = an.read_json(an.data_root() / "players_index.json") or {}
        ix = MO.build_index(stores, pidx, {})
        out: dict[str, list] = defaultdict(list)
        for row in rows:
            for c in MO.parse_row(row):
                typ = c.get("type")
                if typ not in ("trade", "claim", "waivers", "release"):
                    continue
                kind = "trade" if typ == "trade" else "release"
                for p in c.get("players") or []:
                    pid, how = ix.match(p.get("name") or "", {c.get("team")}, p.get("pos"))
                    if pid:
                        out[str(pid)].append((c["date"], kind, fr(c.get("team"))))
        for v in out.values():
            v.sort()
        return dict(out)


def _age(W: World, pid: str, s: int) -> float | None:
    dob = (W.people.get(pid) or {}).get("dob")
    return an.age_on(dob, s) if dob else None


def _points_share(W: World, s: int, upto: date | None) -> dict[str, tuple[float, int]]:
    g = W.games.get(s)
    if g is None or not len(g):
        return {}
    if upto is not None:
        g = g[g["date"] <= upto.isoformat()]
    pts: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for h, a, hs, as_, ot in zip(g["home"], g["away"], g["hs"], g["as"], g["ot"]):
        if hs > as_:
            pts[h][0] += 2
            pts[a][0] += 1 if ot else 0
        else:
            pts[a][0] += 2
            pts[h][0] += 1 if ot else 0
        pts[h][1] += 1
        pts[a][1] += 1
    return {t: (x[0] / (2.0 * x[1]), x[1]) for t, x in pts.items() if x[1]}


# ---------------------------------------------------------------------------------------------- snapshots

def phase_of(W: World, today: date) -> tuple[str, float]:
    cur = max(W.seasons)
    lo, hi = W.bounds[cur]
    if today < lo:
        prev = W.bounds.get(_prev(cur), (lo, hi))[1]
        return "offseason", float((today - prev).days)
    if today <= hi:
        return "inseason", (today - lo).days / max((hi - lo).days, 1)
    return "offseason", float((today - hi).days)


def snap_date(W: World, s: int, phase: str, x: float) -> date:
    lo, hi = W.bounds[s]
    if phase == "inseason":
        return lo + timedelta(days=int(round(x * (hi - lo).days)))
    return hi + timedelta(days=int(min(max(x, 1.0), 150.0)))


def season_info(W: World, s: int, upto: date | None) -> dict[str, dict]:
    key = (s, upto)
    if key in W.cache:
        return W.cache[key]
    ap = W.app.get(s)
    out: dict[str, dict] = {}
    if ap is not None and len(ap):
        a = ap if upto is None else ap[ap["date"] <= upto.isoformat()]
        if len(a):
            from bisect import bisect_left
            tot = a.groupby(["kind", "team"])["toi"].sum()
            club_dates = {c: sorted(set(zip(g["date"], g["game_id"]))) for c, g in a.groupby("team")}
            agg = a.groupby(["pid", "kind"], sort=False).agg(club=("team", "last"), pos=("pos", "last"), last=("date", "last"),
                                                             first_team=("team", "first"), toi=("toi", "sum"),
                                                             clubs=("team", lambda v: sorted(set(v))))
            a2 = a.merge(agg[["club"]].reset_index(), on=["pid", "kind"])
            here = a2[a2["team"] == a2["club"]].groupby(["pid", "kind"]).agg(first_club=("date", "first"), gp=("game_id", "size"),
                                                                             toi_club=("toi", "sum"))
            agg = agg.join(here)
            for (pid, kind), r in agg.iterrows():
                cd = club_dates.get(r["club"], [])
                cg = len(cd) - bisect_left(cd, (r["first_club"], -1))
                rec = {"club": r["club"], "kind": kind, "pos": r["pos"], "last": r["last"], "first_club": r["first_club"],
                       "share": float(r["toi_club"]) / max(float(tot.get((kind, r["club"]), 1.0)), 1.0), "gp": int(r["gp"]),
                       "clubs": r["clubs"], "joined": 1.0 if r["first_team"] != r["club"] else 0.0, "toi": float(r["toi"]),
                       "gp_share": int(r["gp"]) / max(cg, 1)}
                old = out.get(pid)
                if old is None or rec["toi"] > old["toi"]:
                    out[pid] = rec
    W.cache[key] = out
    return out


def _after(W: World, s: int, t: date) -> dict[str, list[tuple[str, str]]]:
    """{pid: [(date, club)]} of the season's games after t (one entry per game)."""
    key = ("after", s, t)
    if key in W.cache:
        return W.cache[key]
    ap = W.app.get(s)
    out: dict[str, list] = defaultdict(list)
    if ap is not None:
        a = ap[ap["date"] > t.isoformat()]
        for pid, d, club in zip(a["pid"], a["date"], a["team"]):
            out[pid].append((d, club))
    W.cache[key] = dict(out)
    return W.cache[key]


def _first_next(W: World, s: int) -> dict[str, str]:
    key = ("first", s)
    if key not in W.cache:
        ap = W.app.get(s)
        W.cache[key] = ap.groupby("pid")["team"].first().to_dict() if ap is not None and len(ap) else {}
    return W.cache[key]


def move_before(games_after: list[tuple[str, str]], club: str, dl: date) -> str | None:
    """The club he moved straight to before the deadline (his last game for `club` before it, his first for the new
    club within MOVE_LAG days of it), else None."""
    last_here = None
    for d, c in games_after:
        if c == club:
            last_here = d
            continue
        if last_here is not None and last_here > dl.isoformat():
            return None
        if d <= (dl + timedelta(days=MOVE_LAG)).isoformat():
            return c
        return None
    return None


def espn_type(events: list[tuple[str, str, str]], lo: date, hi: date) -> int:
    """Kind of a departure from the ESPN rows in (lo, hi]: 0 trade, 1 release or waiver, 2 other."""
    for d, kind, club in events:
        if lo.isoformat() < d <= hi.isoformat():
            return 0 if kind == "trade" else 1
    return 2


# ---------------------------------------------------------------------------------------------- the panel

def _value(W: World, s: int, pid: str) -> dict:
    return (W.value.get(s) or {}).get(pid) or {}


def panel(W: World, phase: str, x: float, seasons: list[int] | None = None) -> pd.DataFrame:
    seasons = seasons or [s for s in W.seasons if s >= FIRST_PANEL and _prev(s) in W.app]
    recs = []
    for s in sorted(seasons):
        t = snap_date(W, s, phase, x)
        upto = t if phase == "inseason" else None
        info = season_info(W, s, upto)
        info_p = season_info(W, _prev(s), None) if _prev(s) in W.app else {}
        info_p2 = season_info(W, _prev(s, 2), None) if _prev(s, 2) in W.app else {}
        info_p3 = season_info(W, _prev(s, 3), None) if _prev(s, 3) in W.app else {}
        nxt = _next(s)
        # labels known: the next regular season complete (y_next); the deadline plus the lag passed (y_dl)
        known_next = nxt in W.bounds and nxt in W.app and W.bounds[nxt][1] < W.today
        dl = deadline(s if phase == "inseason" else nxt)
        known_dl = (dl + timedelta(days=MOVE_LAG)) < W.today and (s if phase == "inseason" else nxt) in W.app
        after = _after(W, s, t) if phase == "inseason" else (_after(W, nxt, W.bounds[nxt][0] - timedelta(days=1)) if nxt in W.app else {})
        first_next = _first_next(W, nxt) if nxt in W.app else {}
        ps_now = _points_share(W, s, upto)
        ps_prev = _points_share(W, _prev(s), None)
        wp = {}
        for club in set(ps_now) | set(ps_prev):
            pts, gp = ps_now.get(club, (0.5, 0))
            pr = ps_prev.get(club, (0.5, 0))[0]
            wp[club] = (pts * gp + pr * 20.0) / (gp + 20.0) if phase == "inseason" else (pts * gp + 0.5 * 20.0) / (gp + 20.0)
        wp_prev = {c: v[0] for c, v in ps_prev.items()}
        for pid, p in info.items():
            club = p["club"]
            v, vp, vp2 = _value(W, s, pid), _value(W, _prev(s), pid), _value(W, _prev(s, 2), pid)
            role = (vp.get("pos") if phase == "inseason" else v.get("pos")) or vp.get("pos") or p["pos"]
            pos = POS.get(str(role)[:1], None) if role else None
            if pos is None:
                pos = "G" if p["kind"] == "G" else "C"
            age = _age(W, pid, s)
            dy = W.draft.get(pid)
            yrs = (an.start_year(s) - dy) if dy else (10 if (age or 0) >= 25 else None)
            ten = 0
            for ip in (info_p, info_p2, info_p3):
                if (ip.get(pid) or {}).get("club") == club:
                    ten += 1
                else:
                    break
            if p["joined"]:
                ten = 0
            pp = info_p.get(pid) or {}
            rec = {"season": s, "pid": pid, "tid": club, "kind": p["kind"], "pos": pos, "age": age, "yrs": min(yrs, 12) if yrs is not None else None,
                   "ufa": 1.0 if age is not None and age + 0.75 >= UFA_AGE else 0.0, "tenure": ten, "joined": p["joined"],
                   "clubs2": len(set(p["clubs"]) | set(pp.get("clubs") or [])), "share": p["share"], "gp_share": p["gp_share"],
                   "share_prev": pp.get("share"), "gp_prev": pp.get("gp"),
                   "v_cur": v.get("war") if phase == "offseason" else None, "v_prev": vp.get("war"), "v_prev2": vp2.get("war"),
                   "goalie": 1.0 if pos == "G" else 0.0, "defence": 1.0 if pos == "D" else 0.0,
                   "team_wp": wp.get(club, 0.5), "team_traj": wp.get(club, 0.5) - wp_prev.get(club, 0.5), "snap": t.isoformat()}
            if known_next:
                fn = first_next.get(pid)
                leave = 0 if fn == club else 1
                rec["y_next"] = float(leave)
                rec["dest"] = fn if (leave and fn and fn != club) else None
                typ = -1
                if leave and t >= ESPN_FROM:
                    hi = W.bounds[nxt][0]
                    typ = espn_type(W.espn.get(pid, []), t, hi)
                rec["y_type"] = typ
            else:
                rec["y_next"], rec["dest"], rec["y_type"] = np.nan, None, -1
            if known_dl:
                if phase == "inseason":
                    to = move_before(after.get(pid, []), club, dl)
                else:                                            # next season: he opens with the club, then moves
                    g = after.get(pid, [])
                    to = move_before(g, club, dl) if (g and g[0][1] == club) else None
                rec["y_dl"] = 1.0 if to else 0.0
                rec["dest_dl"] = to
            else:
                rec["y_dl"], rec["dest_dl"] = np.nan, None
            recs.append(rec)
    df = pd.DataFrame(recs)
    if not len(df):
        return df
    for c in ("v_cur", "v_prev", "v_prev2", "share_prev", "gp_prev", "age", "yrs"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["v_trend"] = df["v_cur"].fillna(df["v_prev"]) - df["v_prev"].fillna(0) if phase == "offseason" else \
        df["v_prev"].fillna(0) - df["v_prev2"].fillna(df["v_prev"]).fillna(0)
    df["vnow"] = ((3 * df["v_cur"].fillna(df["v_prev"]).fillna(0) + 2 * df["v_prev"].fillna(0)) / 5 if phase == "offseason" else
                  (3 * df["v_prev"].fillna(0) + 2 * df["v_prev2"].fillna(0)) / 5)
    df["rank_pos"] = df.groupby(["season", "tid", "pos"])["vnow"].rank(ascending=False, method="first")
    df["depth"] = df.groupby(["season", "tid", "pos"])["pid"].transform("count")
    df["team_age"] = df.groupby(["season", "tid"])["age"].transform("mean")
    # past turnover: the share of the club's roster that was gone the season after, two seasons back (the last
    # season whose label is settled at the snapshot)
    tv = df[df["y_next"].notna()].groupby(["season", "tid"])["y_next"].mean()
    df["team_turn"] = [tv.get((_prev(s, 2), t), np.nan) for s, t in zip(df["season"], df["tid"])]
    df["ufa_x_reb"] = df["ufa"] * (WP_MID - df["team_wp"])
    df["v_x_reb"] = df["vnow"] * (WP_MID - df["team_wp"]).clip(lower=0)
    df["age_x_reb"] = (df["age"].fillna(27) - 27) * (WP_MID - df["team_wp"])
    df["v_x_ufa"] = df["vnow"] * df["ufa"]
    return df


# ---------------------------------------------------------------------------------------------- configuration and build

WHY = {"ufa": ("free-agent age", "before free-agent age"), "tenure": ("long tenure here", "short tenure here"),
       "joined": ("joined this season", None), "clubs2": ("several clubs lately", "settled with one club"),
       "share": ("a big role", "a small role"), "gp_share": ("in the lineup every night", "in and out of the lineup"),
       "share_prev": ("a big role last season", "a small role last season"), "gp_prev": ("many games last season", "few games last season"),
       "v_prev": ("strong last season", "weak last season"), "v_trend": ("improving", "declining"),
       "rank_pos": ("behind others at his position", "first choice at his position"),
       "depth": ("a crowded position", "a thin position"), "goalie": ("goalie", None), "defence": ("defenceman", "forward"),
       "team_wp": ("a winning club", "a losing club"), "team_traj": ("club trending up", "club trending down"),
       "team_age": ("an older roster", "a younger roster"), "team_turn": ("a high-turnover club", "a stable club"),
       "v_x_reb": ("value on a rebuilding club", None), "v_x_ufa": ("value at free-agent age", None),
       "age_x_reb": ("a veteran on a rebuilding club", None), "ufa_x_reb": ("free-agent age on a rebuilding club", None)}

NOTES = [
    "Chance of moving: a ridge logistic regression on our own movement history (who played for which club in every "
    "regular-season game since 2009-10), refitted each season and validated on held-out seasons (Model page).",
    "No contract data: cap hits, contract years, no-trade clauses and RFA/UFA status are not used, because no source "
    "whose terms allow our use has them. Free agency is inferred from age (27 or older is unrestricted), years since "
    "the draft, tenure with the club and role.",
    "Traded or claimed: the box scores show a straight move to another club, not whether it was a trade or a waiver "
    "claim. Next season: not in this club's NHL lineup next season (traded, released, signed elsewhere, retired or in "
    "the minors all season).",
    "Kind of departure: ESPN's transactions are cached only from March 2024, so the split is the 2024-25 departures' "
    "shares (base rates), not a model.",
    "Value is Rink WAR, the last two completed seasons blended 3:2. Rostered: the last club he played for this season.",
    "Outlook: the chance of adding at least one player at the position who was on another NHL club, before the deadline "
    "(during the season) or by next season (after it), from a Poisson model of past arrivals (need there, club strength "
    "and trajectory, turnover, expected departures). Call-ups from the club's own system are not counted.",
    "Targets: players on other clubs who would upgrade the club's weakest regular slot at their position (third-line "
    "centre or winger, second-pair defenceman, starting goalie), ranked by their chance of joining it: the chance he moves "
    "x the chance this club is where he goes (a conditional logit on past moves). An estimate from on-field value and "
    "history, not news.",
]

CFG = MV.Config(level=LEVEL, version=VERSION, feats=FEATS, quad=QUAD, dl_feats=DL_FEATS, type_feats=TYPE_FEATS, arr_feats=ARR_FEATS,
                types=TYPES, type_label=TYPE_LABEL, dev=DEV_Y, test=TEST_Y, slots=SLOTS, contend=CONTEND, rebuild=REBUILD, unit="WAR",
                age_pivot=28.0, why=WHY, notes=NOTES, yrs_phrase="{n} years since his draft", walk_from=None,
                deadline_label="traded or claimed")


def frame(W: World, phase: str, x: float) -> pd.DataFrame:
    """The panel with "season" as the start year (2024 = 2024-25), the consecutive integers the engine's walk-forward gap
    (Config.inseason_gap: season s fitted on seasons before s - 1 in season) counts with."""
    df = panel(W, phase, x)
    if len(df):
        df["season"] = df["season"].map(an.start_year).astype(int)
    return df


def bucket(phase: str, x: float) -> float:
    return float(round(x / 5) * 5) if phase == "offseason" else round(x * 20) / 20


def _target_bits(c) -> list[str]:
    a = c.get("age") if hasattr(c, "get") else None
    try:
        return ["free-agent age"] if a is not None and float(a) + 0.75 >= UFA_AGE else []
    except (TypeError, ValueError):
        return []


def espn_check(W: World, df: pd.DataFrame) -> dict:
    """How the games-based labels compare with ESPN's rows where both exist (in-season moves of 2024-25 and 2025-26)."""
    out = {}
    for y in sorted(df["season"].unique()):
        s = an.season_id(int(y))
        if W.bounds[s][0] < ESPN_FROM:
            continue
        mv = df[(df["season"] == y) & (df["y_dl"] == 1)]
        if not len(mv):
            continue
        dl = deadline(s)
        typed = [espn_type(W.espn.get(r.pid, []), _d(r.snap), dl + timedelta(days=1)) for r in mv.itertuples()]
        out[str(s)] = {"moves": int(len(mv)), "espn_trade": int(sum(1 for k in typed if k == 0)),
                       "espn_waiver_claim": int(sum(1 for k in typed if k == 1)), "no_espn_row": int(sum(1 for k in typed if k == 2))}
    return out


def base_arrivals(df: pd.DataFrame, phase: str, cur: int) -> dict:
    """{pos: [P(adds >= 1), mean arrivals]} per club over the labelled seasons: the base rate shown when the arrivals model
    is not published."""
    col = "dest" if phase == "offseason" else "dest_dl"
    lab = df[(df["season"] < cur) & df[col].notna()]
    seasons = sorted(df.loc[(df["season"] < cur) & df["y_dl" if phase == "inseason" else "y_next"].notna(), "season"].unique())
    if not seasons:
        return {}
    n_clubs = sum(df.loc[df["season"] == s, "tid"].nunique() for s in seasons)
    out = {}
    for pos in sorted(df["pos"].dropna().unique()):
        m = float(((lab["pos"] == pos) & lab["season"].isin(seasons)).sum()) / max(n_clubs, 1)
        out[pos] = [round(1 - math.exp(-m), 3), round(m, 2)]
    return out


def build(today: date) -> dict | None:
    """<S>/movement.json for the Rink build (scripts/build_rink.py, once a day)."""
    t0 = time.perf_counter()
    W = World(today)
    if len(W.seasons) < 8:
        return None
    phase, x = phase_of(W, today)
    df = frame(W, phase, x)
    res = MV.research_cached(df, CFG, W.league, phase, [bucket(phase, x), W.seasons],
                             an.cache_root() / "movement" / "research_nhl.json")
    cur = max(W.seasons)
    cur_y = an.start_year(cur)
    names = {pid: W.names.get(pid) for pid in df.loc[df["season"] == cur_y, "pid"]}
    dl = deadline(cur if phase == "inseason" else _next(cur))
    pay = MV.payload(df, CFG, W.league, res, phase, cur_y, names, today.isoformat(),
                     {"deadline": dl.isoformat(), "deadline_estimated": int(cur if phase == "inseason" else _next(cur)) not in DEADLINES,
                      "next": f"{an.season_label(_next(cur))} opening night"},
                     extra={"updated_at": an.now(), "season": cur, "label_check": espn_check(W, df),
                            "base_arrivals": base_arrivals(df, phase, cur_y), "split": {"dev": DEV, "test": TEST}},
                     target_bits=_target_bits)
    pay["reasons"]["type"] = ("ESPN's transactions are cached only from March 2024: one season (2024-25) of typed departures, too few "
                              "to fit and test a type model. The split shown is that season's shares among leavers (a base rate).")
    log.info("movement %s: %d players, %.1f s", LEVEL, len(pay["players"]), time.perf_counter() - t0)
    return pay
