"""
Play-by-play parsing, possessions, lineups (stints) and the shot table
(CONTRACT.md section 2), from the compact play-by-play of sources/espn.compact_pbp.

    ev = parse(pbp, game)                 # GameEvents: .events, .possessions, .lineups
    st = stints(game, ev)                 # lineup stints with possessions, points and four-factor counts
    sh = shots(game, ev)                  # SHOT rows (SHOT_COLS)
    reconcile(game, st)                   # stint minutes against box-score minutes
    points_check(game, ev)                # points from events against the final score (exact)

ESPN facts this relies on (verified on the fixtures in tests/basketball/fixtures):

* Substitutions (type 584) read "X enters the game for Y" with participants [X (enters), Y (leaves)].
  Changes made at a period break are logged at the new period's opening clock (12:00 / 10:00 / 5:00).
* Shots: participants [shooter, assister] for assisted makes ("(Z assists)"), [shooter, blocker] for
  blocked misses ("B blocks S's 5-foot layup"); the play's team is the shooting team.
* Turnovers: participants [player, stealer] when the text says "(Z steals)"; team turnovers (shot clock,
  8 seconds) have no participant but carry the team.
* Free throws read "makes/misses free throw [technical|flagrant|clear path] n of m".
* Coordinates (half court, whole feet): x runs 0..50 across the court with the rim at x = 25; y runs
  along the court from the shooting team's basket, with the rim centre at y = 0.75 (fitted on the
  "N-foot" distances in the play text, mean absolute error 0.4 ft; the baseline sits near y = -4.5).
  Heaves from the far half reach y = 75. Plays without a location carry about -2.1e8 (dropped upstream).

Lineups: starters come from the box score; substitutions are applied in order; each later period's
five is inferred from who is subbed out before being subbed in, plus who acts before any sub of
theirs, topped up from the previous period's closing five. A player who acts while not on the floor
(a missing substitution) is put on and the most plausible absentee is taken off. Each stint is
checked against box-score minutes by `reconcile` (ESPN box minutes are whole minutes, so 30 s of
any error is rounding).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from . import canon

SHOT_COLS = ["game_id", "t", "period", "team", "shooter", "x_ft", "y_ft", "dist_ft", "angle_deg", "zone", "shot_type",
             "value", "made", "assisted", "assister", "blocked", "putback", "transition", "margin_before", "clutch"]
STINT_COLS = ["game_id", "t0", "t1", "h1", "h2", "h3", "h4", "h5", "a1", "a2", "a3", "a4", "a5",
              "poss_h", "poss_a", "pts_h", "pts_a"]

RIM_X, RIM_Y = 25.0, 0.75
HEAVE_FT = 40.0
PUTBACK_S = 3.0
TRANSITION_S = 6.0
CLUTCH_S, CLUTCH_MARGIN = 300.0, 5
RECON_TOL_S = 60.0

# ── ESPN type ids ───────────────────────────────────────────────────────────

SHOT_TYPE_IDS = {
    "dunk": {96, 115, 116, 117, 118, 138, 149, 150, 151, 152, 153},
    "layup": {95, 109, 110, 111, 112, 125, 126, 127, 128, 129, 141, 142, 143},
    "tip": {94},
    "hook": {93, 119, 120, 123, 139, 140},
    "floater": {130, 144, 145},
    "pullup": {131, 133, 146},
    "stepback": {132},
    "fadeaway": {121, 135, 137, 148},
    "turnaround": {114, 136},
    "jumper": {92, 113, 122, 124, 134, 147, 282},
}
SHOT_TYPE_OF = {i: k for k, ids in SHOT_TYPE_IDS.items() for i in ids}
PUTBACK_IDS = {94, 125, 138, 150}
REB_OFF, REB_DEF = 156, 155
SUB = 584
JUMP_IDS = {11, 615}
TIMEOUT_IDS = {16, 17, 18, 19, 20}
PERIOD_START, PERIOD_END, GAME_END = 411, 412, 402

_TEXT_SHOT_TYPES = [("dunk", "dunk"), ("tip", "tip"), ("alley oop", "layup"), ("layup", "layup"), ("finger roll", "layup"),
                    ("hook", "hook"), ("float", "floater"), ("step back", "stepback"), ("stepback", "stepback"),
                    ("pullup", "pullup"), ("pull-up", "pullup"), ("fade", "fadeaway"), ("turnaround", "turnaround"),
                    ("jump", "jumper"), ("three point", "jumper")]
_FT_N = re.compile(r"(\d)\s+of\s+(\d)")
_FOOT = re.compile(r"(\d+)-foot")


# ── events ──────────────────────────────────────────────────────────────────

@dataclass
class GameEvents:
    game_id: str
    league: str
    season: int | None
    home: str
    away: str
    periods: int
    events: list[dict]
    possessions: list[dict] = field(default_factory=list)
    lineups: list[dict] = field(default_factory=list)       # per event: {team_id: tuple(5 ids)} on the floor at that event
    period_fives: dict = field(default_factory=dict)        # {period: {team: [ids]}} inferred openers
    lineup_fixes: int = 0


def _classify(type_id: int, text: str, type_text: str, shooting: int, pa: int) -> tuple[str, dict]:
    tl, tt = text.lower(), type_text.lower()
    if type_id == SUB or " enters the game for " in tl:
        return "sub", {}
    if "free throw" in tl or "free throw" in tt:
        m = _FT_N.search(tl) or _FT_N.search(tt)
        n, of = (int(m.group(1)), int(m.group(2))) if m else (1, 1)
        return "ft", {"technical": "technical" in tl or "technical" in tt, "flagrant": "flagrant" in tl or "flagrant" in tt,
                      "clear_path": "clear path" in tl or "clear path" in tt, "n": n, "of": n if "technical" in tl + tt else of}
    if type_id in SHOT_TYPE_OF or (shooting and pa in (2, 3)):
        return "shot", {}
    if type_id in (REB_OFF, REB_DEF) or " rebound" in tl:
        off = type_id == REB_OFF or (type_id != REB_DEF and "offensive" in tl)
        return "reb", {"off": off}
    if "turnover" in tl or "turnover" in tt or "traveling" in tl or "travelling" in tl or 61 <= type_id <= 91:
        return "tov", {"steal": "steal" in tl}
    if type_id in TIMEOUT_IDS or "timeout" in tl:
        return "timeout", {}
    if type_id in JUMP_IDS or ("gains possession" in tl):
        return "jump", {}
    if type_id in (PERIOD_END, GAME_END) or tl.startswith("end of"):
        return "period_end", {}
    if type_id == PERIOD_START or tl.startswith("start of"):
        return "period_start", {}
    if "foul" in tl or "foul" in tt or "techfoul" in tl:
        return "foul", {"technical": "technical" in tl or "technical" in tt or "techfoul" in tl, "flagrant": "flagrant" in tl or "flagrant" in tt,
                        "offensive": "offensive" in tl or "charge" in tl or "offensive" in tt, "shooting": "shooting" in tl}
    return "other", {}


def _infer_league(rows: list[list]) -> str:
    p1 = [r[2] for r in rows if r[1] == 1]
    return "nba" if p1 and max(p1) > 650 else "wnba"


def parse(pbp: dict, game: dict, league: str | None = None, season: int | None = None) -> GameEvents:
    """Typed events, lineups on the floor at every event, and possessions."""
    rows = pbp.get("plays") or []
    lg = (league or _infer_league(rows)).lower()
    types = pbp.get("types") or {}
    home, away = str(game.get("home")), str(game.get("away"))
    events: list[dict] = []
    hs = as_ = 0
    for i, r in enumerate(rows):
        seq, period, clk, tid, team, parts, x, y, sv, shooting, scoring, h_sc, a_sc, text = r[:14]
        pa = r[14] if len(r) > 14 else 0
        kind, info = _classify(int(tid or 0), text or "", types.get(str(tid), ""), shooting, pa)
        t = canon.game_t(lg, period, clk, season)
        e = {"i": i, "seq": seq, "period": period, "clock": clk, "t": t, "type": tid, "kind": kind, "team": team,
             "players": list(parts or []), "x": x, "y": y, "pts": int(sv or 0) if scoring else 0, "text": text or "",
             "pa": pa, "hs_before": hs, "as_before": as_, **info}
        if kind == "shot":
            e["made"] = 1 if scoring else 0
            if not pa or pa not in (2, 3):
                e["pa"] = 3 if "three point" in e["text"].lower() else 2
            if e["made"] and not e["pts"]:        # 2017-18 rows can carry scoreValue 0 on scoring plays
                e["pts"] = e["pa"]
        elif kind == "ft":
            e["made"] = 1 if scoring or " makes " in f" {e['text'].lower()} " else 0
            e["pts"] = 1 if e["made"] else 0
        hs, as_ = (h_sc if h_sc is not None else hs), (a_sc if a_sc is not None else as_)
        events.append(e)
    # The running score from the events themselves (row scores can lag or lead in 2017-18 data).
    run = {home: 0, away: 0}
    for e in events:
        e["hs_before"], e["as_before"] = run[home], run[away]
        if e["pts"] and e["team"] in run:
            run[e["team"]] += e["pts"]
    periods = max((e["period"] for e in events), default=0)
    ge = GameEvents(str(game.get("id") or pbp.get("id")), lg, season, home, away, periods, events)
    _lineups(ge, game)
    _possessions(ge)
    return ge


# ── lineups ─────────────────────────────────────────────────────────────────

def _actors(e: dict) -> list[str]:
    """Players an event shows to be on the floor (not substitutions, technicals or timeouts)."""
    k = e["kind"]
    if k in ("shot", "reb", "tov", "jump"):
        return e["players"]
    if k == "ft":
        return [] if e.get("technical") else e["players"][:1]
    if k == "foul":
        return [] if e.get("technical") else e["players"][:1]
    return []


def _roster(game: dict) -> dict[str, str]:
    team_of = {}
    for tid, b in (game.get("box") or {}).items():
        for r in b.get("players") or []:
            team_of[str(r[0])] = str(tid)
        for r in b.get("dnp") or []:
            team_of.setdefault(str(r[0]), str(tid))
    return team_of


def _lineups(ge: GameEvents, game: dict) -> None:
    team_of = _roster(game)
    box = game.get("box") or {}
    starters = {t: [str(r[0]) for r in (box.get(t) or {}).get("players") or [] if r[1]] for t in (ge.home, ge.away)}
    minutes = {str(r[0]): (r[2] or 0) for t in (ge.home, ge.away) for r in (box.get(t) or {}).get("players") or []}
    ev = ge.events
    by_period: dict[int, list[int]] = {}
    for e in ev:
        by_period.setdefault(e["period"], []).append(e["i"])
    prev_end: dict[str, list[str]] = {t: list(starters[t]) for t in (ge.home, ge.away)}
    lineups: list[dict] = [None] * len(ev)  # type: ignore[list-item]
    fixes = 0
    same_clock_subs: dict[tuple, set] = {}
    for e in ev:
        if e["kind"] == "sub":
            same_clock_subs.setdefault((e["period"], e["clock"]), set()).update(e["players"][:2])
    for p in sorted(by_period):
        idxs = by_period[p]
        fives: dict[str, list[str]] = {}
        for team in (ge.home, ge.away):
            fives[team] = _period_five(ev, idxs, team, team_of, prev_end[team], starters[team] if p == 1 else None, minutes,
                                       same_clock_subs)
        ge.period_fives[p] = {k: list(v) for k, v in fives.items()}
        on = {t: list(v) for t, v in fives.items()}
        for j, i in enumerate(idxs):
            e = ev[i]
            if e["kind"] == "sub" and len(e["players"]) >= 2:
                pin, pout = e["players"][0], e["players"][1]
                team = e["team"] or team_of.get(pin) or team_of.get(pout)
                if team in on:
                    cur = on[team]
                    if pout in cur and pin not in cur:
                        cur[cur.index(pout)] = pin
                    elif pout in cur and pin in cur:
                        cur.remove(pout)
                        fixes += 1
                    elif pin not in cur:
                        victim = _absentee(ev, idxs[j + 1:], cur, team_of, team)
                        if victim is not None and len(cur) >= 5:
                            cur[cur.index(victim)] = pin
                        else:
                            cur.append(pin)
                        fixes += 1
            else:
                for pid in _actors(e):
                    team = team_of.get(pid)
                    if team not in on or pid in on[team]:
                        continue
                    if pid in same_clock_subs.get((p, e["clock"]), ()):
                        continue        # logged out of order with a substitution at the same clock
                    cur = on[team]
                    if len(cur) < 5:
                        cur.append(pid)
                    else:
                        victim = _absentee(ev, idxs[j:], cur, team_of, team, exclude=set(_actors(e)))
                        if victim is None:
                            continue
                        cur[cur.index(victim)] = pid
                    fixes += 1
            lineups[i] = {t: tuple(v) for t, v in on.items()}
        prev_end = {t: list(v) for t, v in on.items()}
    ge.lineups = lineups
    ge.lineup_fixes = fixes


def _absentee(ev: list[dict], rest: list[int], cur: list[str], team_of: dict, team: str, exclude: set | None = None) -> str | None:
    """The on-floor player most likely to have left unrecorded: the first whose next appearance is
    being subbed in; otherwise the one who goes longest without acting (or never acts again)."""
    exclude = exclude or set()
    nxt: dict[str, tuple[int, str]] = {}
    for i in rest:
        e = ev[i]
        if e["kind"] == "sub" and len(e["players"]) >= 2:
            for pid, how in ((e["players"][0], "in"), (e["players"][1], "out")):
                if pid in cur and pid not in nxt:
                    nxt[pid] = (i, how)
        else:
            for pid in _actors(e):
                if pid in cur and pid not in nxt:
                    nxt[pid] = (i, "act")
        if len(nxt) == len(cur):
            break
    cands = [p for p in cur if p not in exclude]
    if not cands:
        return None
    subbed_in = [p for p in cands if nxt.get(p, (0, ""))[1] == "in"]
    if subbed_in:
        return min(subbed_in, key=lambda p: nxt[p][0])
    never = [p for p in cands if p not in nxt]
    if never:
        return never[0]
    return max(cands, key=lambda p: nxt[p][0])


def _period_five(ev: list[dict], idxs: list[int], team: str, team_of: dict, prev: list[str], box_starters: list[str] | None,
                 minutes: dict, same_clock_subs: dict | None = None) -> list[str]:
    if box_starters and len(box_starters) == 5:
        return list(box_starters)
    first: dict[str, tuple[int, str]] = {}
    acts: dict[str, int] = {}
    for i in idxs:
        e = ev[i]
        if e["kind"] == "sub" and len(e["players"]) >= 2:
            for pid, how in ((e["players"][0], "in"), (e["players"][1], "out")):
                if team_of.get(pid) == team and pid not in first:
                    first[pid] = (i, how)
        else:
            for pid in _actors(e):
                if team_of.get(pid) == team:
                    acts[pid] = acts.get(pid, 0) + 1
                    if pid in (same_clock_subs or {}).get((e["period"], e["clock"]), ()):
                        continue        # acts at the clock of his own substitution: the order is unreliable
                    first.setdefault(pid, (i, "act"))
    sure = [p for p, (i, how) in sorted(first.items(), key=lambda kv: kv[1][0]) if how == "out"]
    acted = [p for p, (i, how) in sorted(first.items(), key=lambda kv: kv[1][0]) if how == "act"]
    five = sure + [p for p in acted if p not in sure]
    if len(five) > 5:
        five = sure[:5] + sorted([p for p in acted if p not in sure], key=lambda p: -acts.get(p, 0))[: max(0, 5 - len(sure))]
        five = five[:5]
    if len(five) < 5:
        came_in = {p for p, (i, how) in first.items() if how == "in"}
        for p in prev:
            if len(five) >= 5:
                break
            if p not in five and p not in came_in:
                five.append(p)
    if len(five) < 5:   # rare: fill with the team's biggest-minute players not known to have come in
        came_in = {p for p, (i, how) in first.items() if how == "in"}
        pool = sorted((p for p, t in team_of.items() if t == team and p not in five and p not in came_in), key=lambda p: -minutes.get(p, 0))
        five.extend(pool[: 5 - len(five)])
    return five[:5]


# ── possessions ─────────────────────────────────────────────────────────────

_SIGNIFICANT = {"shot", "ft", "reb", "tov", "jump", "period_end"}


def _possessions(ge: GameEvents) -> None:
    ev = ge.events
    poss: list[dict] = []
    cur: dict | None = None
    next_kind = "period"
    pending: dict | None = None          # a made field goal that may yet be an and-one

    def other(team: str | None) -> str | None:
        return ge.away if team == ge.home else ge.home if team == ge.away else None

    def start(team: str | None, e: dict, kind: str) -> None:
        nonlocal cur
        if team not in (ge.home, ge.away):
            return
        lu = ge.lineups[e["i"]] or {}
        cur = {"team": team, "start_t": e["t"], "end_t": e["t"], "start_kind": kind, "pts": 0, "end": None,
               "players_off": list(lu.get(team, ())), "players_def": list(lu.get(other(team), ())),
               "period": e["period"], "start_i": e["i"], "end_i": e["i"]}

    owner_next: str | None = None        # who has the ball after a made basket, last free throw or turnover

    def end(e: dict, how: str, t: float | None = None) -> None:
        nonlocal cur, next_kind, owner_next
        if cur is None:
            return
        owner_next = other(cur["team"]) if how in ("made", "ft", "tov") else None
        cur["end"], cur["end_t"], cur["end_i"] = how, e["t"] if t is None else t, e["i"]
        poss.append(cur)
        cur = None
        next_kind = {"made": "made", "ft": "made", "dreb": "tr", "period": "period"}.get(how, "dead")

    def ensure(team: str | None, e: dict) -> None:
        """The event says `team` has the ball: open a possession for it, closing a stale one."""
        if team not in (ge.home, ge.away):
            return
        if cur is not None and cur["team"] != team:
            end(e, "other")
        if cur is None:
            start(team, e, next_kind)

    for e in ev:
        k = e["kind"]
        e["poss"] = None
        if pending is not None and k in _SIGNIFICANT:
            pe = pending
            and_one = (k == "ft" and not e.get("technical") and e["team"] == pe["team"] and e["period"] == pe["period"]
                       and abs(e["clock"] - pe["clock"]) < 0.05)
            if not and_one:
                end(pe, "made")
            else:
                e["and_one"] = True
            pending = None
        team = e["team"]
        if k == "shot":
            ensure(team, e)
            if e["made"]:
                pending = e
        elif k == "ft":
            if e.get("technical"):
                pass
            else:
                ensure(team, e)
                last = e.get("n", 1) >= e.get("of", 1)
                # a lone free throw that is not an and-one (take foul, away-from-play foul) keeps the ball
                keeps = e.get("flagrant") or e.get("clear_path") or (e.get("of", 1) == 1 and not e.get("and_one"))
                if last and e["made"] and not keeps:
                    if cur is not None:
                        cur["pts"] += e["pts"]
                        e["poss"] = len(poss)
                        end(e, "ft")
                        continue
        elif k == "reb":
            if e.get("off"):
                ensure(team, e)
            else:
                if cur is not None and cur["team"] == team:
                    # a "defensive" rebound by the team already on offence (ESPN's dead-ball team rebounds)
                    pass
                else:
                    if cur is not None:
                        end(e, "dreb")
                        next_kind = "tr" if e["players"] else "dead"
                    if team in (ge.home, ge.away):
                        start(team, e, next_kind)
        elif k == "tov":
            if (cur is not None and cur["team"] != team and cur["pts"] == 0 and poss and poss[-1]["team"] == team
                    and poss[-1]["end"] == "other" and abs(poss[-1]["end_t"] - e["t"]) < 1.0):
                # a held-ball jump already moved the ball; ESPN then logs the loser's turnover: book it there
                poss[-1]["end"], poss[-1]["end_i"] = "tov", e["i"]
                e["poss"] = len(poss) - 1
                continue
            ensure(team, e)
            if cur is not None:
                e["poss"] = len(poss)
                end(e, "tov")
                next_kind = "tr" if e.get("steal") else "dead"
                continue
        elif k == "jump":
            if team in (ge.home, ge.away):
                if cur is None and next_kind != "period" and owner_next not in (None, team):
                    start(owner_next, e, next_kind)       # a held ball on the side that had just got the ball
                if cur is None:
                    start(team, e, next_kind)
                elif cur["team"] != team:
                    end(e, "other")
                    start(team, e, "dead")
        elif k == "period_end":
            end(e, "period")
            next_kind, owner_next = "period", None
        if cur is not None:
            if e["pts"] and team == cur["team"]:
                cur["pts"] += e["pts"]
            e["poss"] = len(poss)
    if pending is not None:
        end(pending, "made")
    if cur is not None:
        end(ev[-1], "period")
    ge.possessions = poss


# ── stints ──────────────────────────────────────────────────────────────────

def stints(game: dict, ge: GameEvents) -> list[dict]:
    """Constant-lineup stretches. Event counts go to the stint holding the event; a possession counts
    in the stint holding its last event; seconds run from the stint's first event to the next change
    (or the period's end)."""
    ev, home, away = ge.events, ge.home, ge.away
    out: list[dict] = []
    if not ev:
        return out
    poss_end = {}
    for p in ge.possessions:
        poss_end.setdefault(p["end_i"], []).append(p["team"])
    cur = None
    for e in ev:
        lu = ge.lineups[e["i"]] or {}
        key = (e["period"], tuple(lu.get(home, ())), tuple(lu.get(away, ())))
        if cur is None or key != cur["_key"]:
            new_period = cur is None or cur["_key"][0] != e["period"]
            if cur is not None:
                cur["t1"] = _period_end_t(ge, cur["_key"][0]) if new_period else e["t"]
                out.append(cur)
            t0 = canon.period_start(ge.league, e["period"], ge.season) if new_period else e["t"]
            cur = {"_key": key, "t0": t0, "t1": t0, "home": list(key[1]), "away": list(key[2]),
                   "poss_home": 0, "poss_away": 0, "pts_home": 0, "pts_away": 0,
                   "fga_h": 0, "fga_a": 0, "tov_h": 0, "tov_a": 0, "oreb_h": 0, "oreb_a": 0, "fta_h": 0, "fta_a": 0}
        side = "h" if e["team"] == home else "a" if e["team"] == away else None
        if side:
            cur["pts_home" if side == "h" else "pts_away"] += e["pts"]
            if e["kind"] == "shot":
                cur[f"fga_{side}"] += 1
            elif e["kind"] == "ft":
                cur[f"fta_{side}"] += 1
            elif e["kind"] == "tov":
                cur[f"tov_{side}"] += 1
            elif e["kind"] == "reb" and e.get("off") and e["players"]:
                cur[f"oreb_{side}"] += 1
        for team in poss_end.get(e["i"], []):
            cur["poss_home" if team == home else "poss_away"] += 1
    if cur is not None:
        cur["t1"] = _period_end_t(ge, cur["_key"][0])
        out.append(cur)
    res = []
    for s in out:
        s.pop("_key")
        s["t0"], s["t1"] = round(float(s["t0"]), 1), round(float(s["t1"]), 1)
        if s["t1"] > s["t0"] or any(s[k] for k in ("poss_home", "poss_away", "pts_home", "pts_away")):
            res.append(s)
    return res


def _period_end_t(ge: GameEvents, period: int) -> float:
    return float(canon.period_start(ge.league, period, ge.season) + canon.period_len(ge.league, period, ge.season))


def reconcile(game: dict, st: list[dict]) -> dict:
    """Seconds on the floor from stints against box-score seconds, per player."""
    on: dict[str, float] = {}
    bad = 0.0
    for s in st:
        d = max(0.0, s["t1"] - s["t0"])
        for pid in list(s["home"]) + list(s["away"]):
            on[pid] = on.get(pid, 0.0) + d
        if len(s["home"]) != 5 or len(s["away"]) != 5:
            bad += d
    per: dict[str, float] = {}
    for tid, b in (game.get("box") or {}).items():
        for r in b.get("players") or []:
            pid, sec = str(r[0]), r[2]
            if sec is None:
                continue
            per[pid] = round(on.get(pid, 0.0) - sec, 1)
    for pid, v in on.items():
        if pid not in per and v > 0:
            per[pid] = round(v, 1)
    mx = max((abs(v) for v in per.values()), default=0.0)
    return {"max_err_s": round(mx, 1), "per_player": per, "ok": mx <= RECON_TOL_S, "bad_lineup_s": round(bad, 1)}


def points_check(game: dict, ge: GameEvents) -> dict:
    """Points summed from scoring events against the final score; exact match required."""
    pts = {ge.home: 0, ge.away: 0}
    for e in ge.events:
        if e["pts"] and e["team"] in pts:
            pts[e["team"]] += e["pts"]
    h, a = game.get("hs"), game.get("as")
    return {"home": [pts[ge.home], h], "away": [pts[ge.away], a], "ok": pts[ge.home] == h and pts[ge.away] == a}


# ── shots ───────────────────────────────────────────────────────────────────

def shot_geometry(x: float | None, y: float | None) -> tuple[float | None, float | None, float | None, float | None]:
    """(x_ft, y_ft, dist_ft, angle_deg) from ESPN coordinates; angle 0 = straight on, +-90 = along the baseline."""
    if x is None or y is None:
        return None, None, None, None
    xf, yf = float(x) - RIM_X, float(y) - RIM_Y
    return round(xf, 2), round(yf, 2), round(math.hypot(xf, yf), 1), round(math.degrees(math.atan2(xf, yf)))


def is_three(league: str, season: int | None, x_ft: float, y_ft: float, tol: float = 0.5) -> bool:
    arc, corner = canon.three_point_line(league, season)
    if y_ft <= canon.CORNER_Y_FT:
        return abs(x_ft) >= corner - tol
    return math.hypot(x_ft, y_ft) >= arc - tol


def zone(league: str, season: int | None, x_ft: float | None, y_ft: float | None, dist: float | None, value: int) -> str | None:
    if dist is None:
        return None
    if dist > HEAVE_FT and value == 3:
        return "heave"
    if value == 3:
        return "corner3" if y_ft is not None and y_ft <= canon.CORNER_Y_FT and abs(x_ft or 0) >= 20 else "ab3"
    if dist < 4:
        return "rim"
    if x_ft is not None and abs(x_ft) <= canon.LANE_HALF_W_FT and y_ft is not None and y_ft <= canon.FT_LINE_Y_FT:
        return "paint"
    return "mid"


def shot_type(type_id: int, text: str, type_text: str = "") -> str:
    if type_id in SHOT_TYPE_OF:
        return SHOT_TYPE_OF[type_id]
    s = f"{type_text} {text}".lower()
    for kw, st in _TEXT_SHOT_TYPES:
        if kw in s:
            return st
    return "other"


def shots(game: dict, ge: GameEvents, pbp_types: dict | None = None) -> list[list]:
    """SHOT rows (SHOT_COLS order). The zone follows ESPN's value (pointsAttempted): geometry decides
    rim/paint/mid and corner/above-break, and `geo_three` agreement is reported by `shot_quality`."""
    rows = []
    poss = ge.possessions
    last_oreb: dict[str, dict] = {}
    for e in ge.events:
        if e["kind"] == "reb" and e.get("off") and e["players"]:
            last_oreb[e["team"]] = e
        if e["kind"] != "shot" or e["team"] not in (ge.home, ge.away):
            continue
        team = e["team"]
        x_ft, y_ft, dist, ang = shot_geometry(e["x"], e["y"])
        if dist is None:
            m = _FOOT.search(e["text"])
            dist = float(m.group(1)) if m else None
        value = 3 if e["pa"] == 3 else 2
        z = zone(ge.league, ge.season, x_ft, y_ft, dist, value)
        txt = e["text"].lower()
        made = int(e.get("made", 0))
        assisted = 1 if made and "assist" in txt else 0
        assister = e["players"][1] if assisted and len(e["players"]) > 1 else None
        blocked = 1 if (not made and " blocks " in f" {txt} ") else 0
        shooter = e["players"][0] if e["players"] else None
        ob = last_oreb.get(team)
        putback = 1 if (e["type"] in PUTBACK_IDS or (ob is not None and ob["period"] == e["period"] and 0 <= e["t"] - ob["t"] <= PUTBACK_S
                                                    and ob.get("poss") == e.get("poss"))) else 0
        p = poss[e["poss"]] if e.get("poss") is not None and e["poss"] < len(poss) else None
        transition = 1 if p is not None and p["team"] == team and p["start_kind"] == "tr" and e["t"] - p["start_t"] <= TRANSITION_S else 0
        own, opp = (e["hs_before"], e["as_before"]) if team == ge.home else (e["as_before"], e["hs_before"])
        margin = own - opp
        late = e["period"] >= canon.reg_periods(ge.league, ge.season) and e["clock"] <= CLUTCH_S
        clutch = 1 if late and abs(margin) <= CLUTCH_MARGIN else 0
        st = shot_type(int(e["type"] or 0), e["text"], (pbp_types or {}).get(str(e["type"]), ""))
        rows.append([ge.game_id, round(e["t"], 1), e["period"], team, shooter, x_ft, y_ft, dist, ang, z, st, value, made,
                     assisted, assister, blocked, putback, transition, margin, clutch])
    return rows


def shot_quality(ge: GameEvents) -> dict:
    """Agreement between the coordinates' side of the three-point line and ESPN's pointsAttempted."""
    n = agree = 0
    for e in ge.events:
        if e["kind"] != "shot" or e["x"] is None:
            continue
        x_ft, y_ft, dist, _ = shot_geometry(e["x"], e["y"])
        n += 1
        agree += int(is_three(ge.league, ge.season, x_ft, y_ft) == (e["pa"] == 3))
    return {"n": n, "agree": agree, "share": round(agree / n, 4) if n else None}


def stint_rows(game_id: str, st: list[dict]) -> list[list]:
    """stints.json rows (STINT_COLS); stints without five a side are left out."""
    out = []
    for s in st:
        if len(s["home"]) != 5 or len(s["away"]) != 5 or s["t1"] <= s["t0"] and not (s["poss_home"] or s["poss_away"]):
            continue
        out.append([str(game_id), s["t0"], s["t1"], *s["home"], *s["away"], s["poss_home"], s["poss_away"], s["pts_home"], s["pts_away"]])
    return out


def derive(pbp: dict, game: dict, league: str | None = None, season: int | None = None) -> dict[str, Any]:
    """Everything bb_derive needs for one game: shot rows, stint rows and the reconciliation summary."""
    ge = parse(pbp, game, league, season)
    st = stints(game, ge)
    rec = reconcile(game, st)
    pc = points_check(game, ge)
    sq = shot_quality(ge)
    poss_n = {ge.home: 0, ge.away: 0}
    for p in ge.possessions:
        if p["team"] in poss_n:
            poss_n[p["team"]] += 1
    summary = {"max_err_s": rec["max_err_s"], "ok": rec["ok"], "bad_lineup_s": rec["bad_lineup_s"],
               "n_err_60": sum(1 for v in rec["per_player"].values() if abs(v) > RECON_TOL_S),
               "points_ok": pc["ok"], "pts": [pc["home"][0], pc["away"][0]], "poss": [poss_n[ge.home], poss_n[ge.away]],
               "three_agree": sq["share"], "fixes": ge.lineup_fixes, "stints": len(st)}
    return {"shots": shots(game, ge, pbp.get("types")), "stints": stint_rows(ge.game_id, st), "recon": summary, "events": ge}
