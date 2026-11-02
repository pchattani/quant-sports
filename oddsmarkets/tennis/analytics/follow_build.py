"""The Ace's follow cards (My Teams): one small card per player at data/follow/<T>/<pid>.json, for the ATP and the WTA.

The schema and the fact engine are oddsmarkets/common/follow.py; this module only gathers what the Ace build has
already written (no new fetching):

    <T>/players_index.json        who gets a card (select(), below): its rank and last-match columns; names and countries
    <T>/rankings.json             the current official ranking (select())
    index.json tours[T]           today / upcoming / live / recent match cards (the next match with our chance, the
                                  latest results), events_now (the tournaments in play)
    <T>/events/<id>.json          the draws in play (who is playing this week), their results, the title simulation
    <T>/players/<pid>.json        current (rank, points, race, Elo and Elo rank), odds (Finals qualification, the
                                  year-end No. 1), results, seasons, Elo history, points to defend
    <T>/players.json              this season's catalogue: the serve and return percentiles for the profile and the
                                  league ranks for the facts (qualified players only)
    <T>/race.json                 our Finals and year-end No. 1 chances now; <T>/chance_log.json the same by day (the
                                  7-day change)
    <T>/<Y>/events.json           event names and levels, which tournaments are still to come (the phase)

Who gets a card: `select()`: a current official ranking of 500 or better (rankings.json), or a players_index rank of 500
or better with a tour-level match in the last 52 weeks, or a player in a today / upcoming / live match of index.json,
or in the main draw of a tournament in events_now (scripts/build_home.py lists the same players in Home's search). Ids must be plain (letters and digits): the follow key is
'ace:<T>:<pid>' and the site route '#/<T>/player/<pid>'.

    build(data_root, tour, now=None) -> {"n", "bytes", "max", "ids"}        (python -m oddsmarkets.tennis.analytics.follow_build)

No look-ahead: a result counts only once its date is at or before the build clock, a finished match carries the
pre-match chance frozen before the first ball (the match card's model price), the next match is one that has not
started, and the 7-day change compares two chance-log snapshots taken on those days (plus race.json's own day).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL

log = logging.getLogger(__name__)

SITE, SPORT = "ace", "tennis"
TOP = 500
TOUR = {"atp": "ATP", "wta": "WTA"}
TOUR_LONG = {"atp": "ATP Tour", "wta": "WTA Tour"}
PID = re.compile(r"^[A-Za-z0-9]+$")
ACTIVE_DAYS = 365                 # "active": a tour-level match in the last 52 weeks (the card's own active test)
ROUND = {"F": "final", "SF": "semi-final", "QF": "quarter-final", "R16": "round of 16", "R32": "round of 32", "R64": "round of 64",
         "R128": "round of 128", "RR": "round robin", "BR": "bronze-medal match", "Q1": "qualifying", "Q2": "qualifying", "Q3": "qualifying"}
LEVEL = {"slam": "Grand Slam", "finals": "Finals", "m1000": "1000", "500": "500", "250": "250"}
PLAYED = ("done", "ret", "def")
# the profile: serve and return first (the site's percentiles, this season's catalogue), then the results set
PROFILE = (("serve_rating", "Serve rating"), ("hold", "Hold %"), ("first_won", "1st-serve points won"), ("second_won", "2nd-serve points won"),
           ("return_rating", "Return rating"), ("brk", "Break %"), ("bp_conv_pct", "Break points converted"), ("bp_saved_pct", "Break points saved"),
           ("games_won_pct", "Games won"), ("win_v_top10", "Win % v top 10"), ("win_v_top50", "Win % v top 50"), ("tb_pct", "Tiebreaks won"),
           ("dec_pct", "Deciding sets won"), ("close_sets_pct", "Close sets won"), ("elo_hard", "Hard-court Elo"), ("elo_clay", "Clay Elo"),
           ("elo_grass", "Grass Elo"))
# the league-rank facts ("3rd-best break % on the ATP Tour this year"): the predictive core only
PCTL = (("serve_rating", "Serve rating"), ("return_rating", "Return rating"), ("hold", "Hold %"), ("brk", "Break %"),
        ("games_won_pct", "Share of games won"), ("win_v_top10", "Win % against the top 10"))


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_num = FL._num


def _fmt(v, f) -> str:
    v = _num(v)
    if v is None:
        return ""
    if f in ("pct", "prob"):
        return f"{v * 100:.1f}%"
    if f == "2":
        return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.2f}"
    if f == "1":
        return f"{v:,.0f}"
    if f == "signed":
        return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.1f}"
    if f == "int":
        return f"{v:.0f}"
    return f"{v:g}"


def _start(c: dict) -> str | None:
    """A match card's date as ISO UTC ('2026-10-30T12:30' is UTC; a bare date is kept as it is)."""
    d = str(c.get("date") or "")
    return d + ":00Z" if len(d) == 16 else (d or None)


def _surname(short: str | None, name: str | None) -> str:
    s = str(short or name or "").strip()
    out = re.sub(r"^([A-Z][a-z]?\.\s*)+", "", s)
    return out or s


def _sets(score: str | None) -> list[int] | None:
    """'6-7(7) 7-6(2) 6-3 6-4' (the player's side first) -> [3, 1]; None when unreadable."""
    us = them = 0
    for part in str(score or "").split():
        m = re.match(r"^(\d+)-(\d+)", part)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            us += 1
        elif b > a:
            them += 1
    return [us, them] if us + them else None


def _card_sets(c: dict, side: int) -> list[int] | None:
    us = them = 0
    for s in c.get("sets") or []:
        if not s or s[0] is None or s[1] is None:
            continue
        a, b = (s[0], s[1]) if side == 0 else (s[1], s[0])
        us += a > b
        them += b > a
    return [int(us), int(them)] if us + them else None


def _event_name(events: dict, eid: str | None) -> str:
    e = (events or {}).get(eid) or {}
    nm = e.get("name") or str(eid or "").rsplit("-", 1)[0].replace("-", " ").title()
    return nm


def _event_short(events: dict, eid: str | None) -> str:
    """'Basel', 'Wimbledon', 'the Australian Open': the city for most events, the name for the Slams and the Finals."""
    e = (events or {}).get(eid) or {}
    if e.get("level") in ("slam", "finals"):
        return e.get("name") or _event_name(events, eid)
    return e.get("city") or _event_name(events, eid)


def _the(name: str) -> str:
    """'the Australian Open', 'the ATP Finals', 'Wimbledon', 'Basel'."""
    return ("the " + name) if re.match(r"^(Australian Open|US Open|French Open|ATP Finals|WTA Finals|Nitto|Davis Cup|United Cup|Billie Jean)", name or "") else name


def _nice_day(s: str) -> str:
    d = datetime.fromisoformat(str(s)[:10])
    return f"{('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[d.weekday()]} {d.day} {('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[d.month - 1]}"


def _rank(values: dict, higher: bool = True) -> dict:
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if higher else t[0])
    out, prev, prev_rank = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        r = prev_rank if prev is not None and v == prev else i
        out[k] = r
        prev, prev_rank = v, r
    return out


def select(data: Path, tour: str, now: datetime | None = None) -> tuple[list[str], dict]:
    """The players who get a card (and the only ones Home's search and the follow picker list): an active player in
    the top TOP, or anyone playing this week. Active and ranked means either a current official ranking of TOP or
    better (rankings.json `official`, the tours' own list, or players_index's official flag: the same list) or a
    players_index rank of TOP or better (the official rank, else the rank at the player's last tour-level match)
    with a tour-level match in the last ACTIVE_DAYS (players_index's last-match column). The Ace's follow stars
    (docs/ace/assets/js/overview.js flOk) apply the same rule to players_index. Playing this week: a today / upcoming / live match in index.json, or the
    main draw of a tournament in events_now. A players_index without the last-match column (a payload from before
    1 Nov 2026) falls back to its rank alone. Ids must be plain (PID). -> (sorted ids, {pid: "rank" | "week"})."""
    data = Path(data)
    asof = (now or datetime.now(timezone.utc)).date()
    pi = (_read(data / tour / "players_index.json") or {}).get("players") or {}
    official = {}
    for r in (_read(data / tour / "rankings.json") or {}).get("official") or []:
        if isinstance(r, list) and len(r) > 1 and _num(r[0]) is not None and _num(r[0]) <= TOP:
            official[str(r[1])] = int(_num(r[0]))
    dated = any(isinstance(row, list) and len(row) > 4 for row in pi.values())
    why: dict = {}
    for pid, row in pi.items():
        pid = str(pid)
        if not PID.match(pid) or not isinstance(row, list):
            continue
        rk = _num(row[3]) if len(row) > 3 else None
        if pid in official or (len(row) > 5 and row[5] == 1 and rk is not None and rk <= TOP):
            why[pid] = "rank"
        elif rk is not None and rk <= TOP:
            last = row[4] if len(row) > 4 else None
            if not dated:
                why[pid] = "rank"
            elif last:
                try:
                    if (asof - datetime.fromisoformat(str(last)[:10]).date()).days <= ACTIVE_DAYS:
                        why[pid] = "rank"
                except ValueError:
                    pass
    ti = ((_read(data / "index.json") or {}).get("tours") or {}).get(tour) or {}
    week = set()
    for key in ("today", "upcoming", "live"):
        for c in ti.get(key) or []:
            week.update(str(p) for p in (c.get("p1"), c.get("p2")) if p)
    for e in ti.get("events_now") or []:
        ev = _read(data / tour / "events" / f"{e.get('event')}.json") or {}
        for s in ((ev.get("draw") or {}).get("slots") or []):
            if isinstance(s, list) and len(s) > 1 and s[1]:
                week.add(str(s[1]))
    for p in week:
        if PID.match(p):
            why.setdefault(p, "week")
    return sorted(why), why


def _facts(ctx: dict, mine: list[dict], asof, phase: str) -> list[dict]:
    """follow.py's candidates for the subject-free templates (the league ranks, the 7-day swing) plus this module's
    player templates (a player is 'he' or 'she' to nobody here: every line names the player or has no subject), ranked
    as follow.facts ranks them: best first, no two of a kind, no repeated text, at most five."""
    cands = FL.candidates(ctx, asof) + mine
    if phase == "offseason":
        cands = [c for c in cands if c["kind"] not in FL.LIVE_KINDS]
    seen_k, seen_t, out = set(), set(), []
    for c in sorted(cands, key=lambda c: (-c["score"], FL.KINDS.index(c["kind"]) if c["kind"] in FL.KINDS else 99)):
        t = " ".join(c["text"].split()).strip()
        if c["score"] < FL.MIN_SCORE or c["kind"] in seen_k or t.lower() in seen_t:
            continue
        seen_k.add(c["kind"])
        seen_t.add(t.lower())
        out.append({"kind": c["kind"], "text": t, "score": round(c["score"], 1)})
        if len(out) >= FL.MAX_FACTS:
            break
    return out


def build(data: Path, tour: str = "atp", now: datetime | None = None, out_dir: Path | None = None) -> dict:
    """Write data/follow/<tour>/<pid>.json for every selected player; returns write_cards' summary."""
    data = Path(data)
    asof = now or datetime.now(timezone.utc)
    if asof.tzinfo is None:
        asof = asof.replace(tzinfo=timezone.utc)
    today = asof.date().isoformat()
    idx = _read(data / "index.json") or {}
    ti = (idx.get("tours") or {}).get(tour) or {}
    year = int(ti.get("year") or asof.year)
    TN, TL = TOUR[tour], TOUR_LONG[tour]
    ids, why = select(data, tour, asof)
    pi = (_read(data / tour / "players_index.json") or {}).get("players") or {}
    events = (_read(data / tour / str(year) / "events.json") or {}).get("events") or {}
    prev_events = (_read(data / tour / str(year - 1) / "events.json") or {}).get("events") or {}
    cat = _read(data / tour / "players.json") or {}
    cat_p = {str(k): v for k, v in (cat.get("players") or {}).items()} if int(cat.get("year") or 0) == year else {}
    cat_m = {m["key"]: m for m in cat.get("metrics") or [] if m.get("key")}
    qual = {p: x for p, x in cat_p.items() if x.get("qualified")}
    race = _read(data / tour / "race.json") or {}
    # the simulation's own time stamp (its day alone would read as noon, after a morning build)
    race_day = str(race.get("updated_at") or race.get("as_of") or "")
    race_ok = FL._dt(race_day) is not None and FL._dt(race_day) <= asof
    clog = ((_read(data / tour / "chance_log.json") or {}).get(str(year)) or {})
    # the phase: the season runs while a tournament on this year's calendar has not ended
    left = [e for e in events.values() if str(e.get("end") or "") >= today and e.get("status") != "done" and e.get("level") in LEVEL]
    phase = "season" if (left or ti.get("events_now")) and year == asof.year else "offseason"
    # this week's tournaments: the draws and their title simulations
    ev_now = {}
    for e in ti.get("events_now") or []:
        ev = _read(data / tour / "events" / f"{e.get('event')}.json")
        if ev:
            ev_now[str(e.get("event"))] = ev
    # match cards: the next match (not started at the clock) and finished results (the latest results lag in the
    # career files, so the index's and the draws' results are merged in by match id)
    upcoming, done_cards = {}, {}
    cards_all = list(ti.get("today") or []) + list(ti.get("upcoming") or []) + list(ti.get("live") or []) + list(ti.get("recent") or [])
    for ev in ev_now.values():
        cards_all += list(ev.get("results") or [])
    for c in cards_all:
        st = str(c.get("status") or "")
        t = FL._dt(_start(c))
        if t is None:
            continue
        for side, p in enumerate((c.get("p1"), c.get("p2"))):
            if not p:
                continue
            p = str(p)
            if st == "upcoming" and len(str(c.get("date") or "")) == 16 and t > asof:
                if p not in upcoming or t < FL._dt(_start(upcoming[p][0])):
                    upcoming[p] = (c, side)
            elif st in PLAYED and t <= asof and c.get("winner"):
                done_cards.setdefault(p, {})[str(c.get("id"))] = (c, side)
    # Elo ranks of everyone with a career file: the opponents' "#N" and the "of N"
    elo_rank, cur_of = {}, 0
    files = {}
    for pid in ids:
        j = _read(data / tour / "players" / f"{pid}.json")
        if j and j.get("ok") is not False:
            files[pid] = j
            er = (j.get("current") or {}).get("elo_rank")
            if _num(er) is not None:
                elo_rank[pid] = int(er)
                cur_of = max(cur_of, int(er))
    rk_list = (_read(data / tour / "rankings.json") or {}).get("elo") or []
    for r in rk_list:
        if isinstance(r, list) and len(r) > 1:
            elo_rank.setdefault(str(r[1]), int(r[0]))
    # league ranks on this season's catalogue (qualified players)
    lg_rank = {}
    for key, _lab in PCTL + (("titles", ""), ("win_pct", "")):
        m = cat_m.get(key) or {}
        lg_rank[key] = _rank({p: (x.get("values") or {}).get(key) for p, x in qual.items()}, higher=not m.get("lower"))
    from oddsmarkets.common import featured as FT
    from oddsmarkets.tennis.analytics import site as SI
    cards = {}
    for pid in ids:
        j = files.get(pid) or {}
        row = pi.get(pid) or []
        name = j.get("name") or (row[0] if row else None) or f"Player {pid}"
        short = j.get("short") or (row[1] if len(row) > 1 else None) or name
        sur = _surname(short, name)
        country = j.get("country") or (row[2] if len(row) > 2 else None)
        cur = j.get("current") or {}
        rank = _num(cur.get("rank"))
        if rank is None and row and _num(row[3]) is not None:
            rank = _num(row[3])
        team = {"name": name, "short": sur, "abbr": (country or "")[:3] or None, "href": f"#/{tour}/player/{pid}", "league": TN,
                "group": country}
        # results: the career file's (newest first), with this week's finished matches merged in
        res = {}
        for r in j.get("results") or []:
            t = FL._dt(r.get("date"))
            if t is None or t > asof or r.get("status") not in PLAYED:
                continue
            res[str(r.get("match"))] = {"start": str(r.get("date")), "res": "W" if r.get("won") else "L", "p": _num(r.get("p_pre")),
                                        "opp": str(r.get("opp") or ""), "event": r.get("event"), "round": r.get("round"),
                                        "score": _sets(r.get("score")), "id": str(r.get("match"))}
        for mid, (c, side) in (done_cards.get(pid) or {}).items():
            p1 = _num((c.get("model") or {}).get("p1"))
            res[mid] = {"start": _start(c), "res": "W" if str(c.get("winner")) == pid else "L",
                        "p": None if p1 is None else round(p1 if side == 0 else 1 - p1, 4),
                        "opp": str(c.get("p2") if side == 0 else c.get("p1")), "event": c.get("event"), "round": c.get("round"),
                        "score": _card_sets(c, side), "id": mid}
        results = sorted(res.values(), key=lambda r: (str(r["start"])[:10], FL._dt(r["start"]) or asof))
        this_year = [r for r in results if str(r["start"])[:4] == str(year)]
        last_seen = results[-1]["start"][:10] if results else None
        active = bool(last_seen) and (asof.date() - datetime.fromisoformat(last_seen).date()).days <= 365
        cphase = phase if active else "offseason"
        wl = (sum(1 for r in this_year if r["res"] == "W"), sum(1 for r in this_year if r["res"] == "L"))
        rec = FL.record_text(*wl) if sum(wl) else None
        # now: the ranking, our Elo
        pts = _num(cur.get("points"))
        # ranked now (the official list) though without a tour-level match in a year (playing the lower tours, or
        # injured): the current rank, not "last ranked"
        off_now = bool(row) and len(row) > 5 and row[5] == 1
        if rank is not None and (active or off_now):
            st = {"pos": int(rank), "text": f"No. {int(rank)} in the {TN} rankings" + (f" · {pts:,.0f} pts" if pts else "")}
        elif rank is not None:
            st = {"pos": int(rank), "text": f"Last ranked No. {int(rank)}" + (f", in {last_seen[:4]}" if last_seen else "")}
        else:
            st = None
        elo = _num((cur.get("elo") or {}).get("all"))
        er = _num(cur.get("elo_rank"))
        rt = {"value": round(elo, 1), "text": f"{elo:,.0f}", "rank": int(er), "of": max(cur_of, int(er)), "label": "Elo"} if elo is not None and er is not None and active else None
        now_blk = {"record": rec, "form": FL.form_letters(results, asof) if cphase != "offseason" else None, "standing": st, "rating": rt}
        sk = FL.streak_of(results, asof)
        if sk and cphase != "offseason" and sk[1] >= 2:
            now_blk["streak"] = f"{sk[0]}{sk[1]}"
        # chances: this week's title (still in the draw), the year-end No. 1, the Finals
        odds = j.get("odds") or {}
        fq = _num((race.get("finals_qual") or {}).get(pid)) if race_ok and race.get("finals_qual") else _num(odds.get("finals_qual"))
        no1 = _num((race.get("year_end_no1") or {}).get(pid)) if race_ok and race.get("year_end_no1") else _num(odds.get("year_end_no1"))
        if race_ok and race.get("finals_qual") and fq is None:
            fq = 0.0
        evt = None
        for eid, ev in ev_now.items():
            sp = ((ev.get("sim") or {}).get("players") or {}).get(pid) or {}
            p = _num(sp.get("p_title"))
            if p is not None and 0 < p < 1 and not (ev.get("event") or {}).get("champion"):
                evt = (eid, p)
        ser_fq = {d: (v or {}).get(pid) for d, v in (clog.get("finals_qual") or {}).items() if isinstance(v, dict) and d <= today}
        if race_ok and fq is not None:
            ser_fq[race_day] = fq
        ser_fq = {d: (v if v is not None else 0.0) for d, v in ser_fq.items()}
        chances = []
        if cphase == "season":
            if evt:
                chances.append({"key": "p_event", "label": f"{_event_short(events, evt[0])} title", "p": round(evt[1], 4), "d7": None})
            if no1 is not None and 0.005 <= no1:
                ser_no1 = {d: (v or {}).get(pid, 0.0) for d, v in (clog.get("year_end_no1") or {}).items() if isinstance(v, dict) and d <= today}
                if race_ok:
                    ser_no1[race_day] = no1
                chances.append({"key": "year_end_no1", "label": "Year-end No. 1", "p": round(no1, 4), "d7": FL.change_since(ser_no1, asof, 7)})
            if fq is not None and fq >= 0.005:
                chances.append({"key": "finals_qual", "label": "Finals", "p": round(fq, 4), "d7": FL.change_since(ser_fq, asof, 7)})
            # the headline (the card shows the last one): a race still open leads
            open_ = [c for c in chances if 0.005 <= c["p"] < 0.995]
            if open_:
                lead = open_[-1]
                chances = [c for c in chances if c is not lead] + [lead]
        # the next match
        nxt, next_ctx = [], None
        if cphase == "season" and pid in upcoming:
            c, side = upcoming[pid]
            opp = str(c.get("p2") if side == 0 else c.get("p1"))
            p1 = _num((c.get("model") or {}).get("p1"))
            m1 = _num((c.get("market") or {}).get("p1"))
            g = (SI.digest_games([c], events, tour) or [None])[0]
            sg = FT.significance(g, asof) if g else {"score": 0, "reasons": []}
            orow = pi.get(opp) or []
            oname = _surname(orow[1] if len(orow) > 1 else None, orow[0] if orow else None) or opp
            comp = f"{_event_short(events, c.get('event'))} · {ROUND.get(c.get('round'), c.get('round') or '')}".strip(" ·")
            nxt.append({"id": str(c.get("id")), "start": _start(c), "home": True,
                        "opp": {"name": oname, "abbr": ((orow[2] if len(orow) > 2 else None) or "")[:3] or None, "rank": elo_rank.get(opp)},
                        "comp": comp, "p": None if p1 is None else round(p1 if side == 0 else 1 - p1, 4),
                        "mkt": None if m1 is None else round(m1 if side == 0 else 1 - m1, 4), "why": sg["reasons"][:2],
                        "href": f"#/{tour}/match/{c.get('id')}"})
            next_ctx = {"start": _start(c), "opp": oname, "p": nxt[0]["p"], "score": sg["score"], "round": c.get("round"), "event": c.get("event")}
        note = None
        if not nxt:
            alive = [eid for eid, ev in ev_now.items() if _num((((ev.get("sim") or {}).get("players") or {}).get(pid) or {}).get("p_title")) not in (None, 0)]
            if cphase == "offseason":
                note = (f"No tour-level match since {last_seen[:4]}." if off_now else f"Not on tour since {last_seen[:4]}.") if not active and last_seen                     else f"Off-season. The {year + 1} season starts in January."
            elif alive:
                note = f"Still in the draw at {_event_short(events, alive[0])}; the next match is not on the schedule yet."
            else:
                note = "No match on the schedule this week."
        # the last result
        last = None
        if results:
            x = results[-1]
            orow = pi.get(x["opp"]) or []
            ev_all = events if str(x["start"])[:4] == str(year) else prev_events
            last = {"id": x["id"], "start": x["start"], "home": True,
                    "opp": {"name": _surname(orow[1] if len(orow) > 1 else None, orow[0] if orow else None) or x["opp"]},
                    "score": x["score"], "res": x["res"], "p": x["p"], "upset": FL.upset_flag(x["p"], x["res"]),
                    "comp": f"{_event_short(ev_all, x['event'])} · {ROUND.get(x['round'], x['round'] or '')}".strip(" ·"),
                    "href": f"#/{tour}/match/{x['id']}"}
        # the season line
        seas = next((s for s in (j.get("seasons") or []) if int(s.get("year") or 0) == year), None) or {}
        titles = int(seas.get("titles") or 0)
        line = None
        if rec:
            line = f"{rec} in {year}" + (f", {titles} title{'s' if titles != 1 else ''}" if titles else "") + "."
        elif not active and last_seen:
            line = f"Last played on tour in {last_seen[:4]}."
        # the profile: this season's percentiles among the qualified players (serve and return first)
        profile = None
        cp = qual.get(pid)
        if cp and active:
            pc, vals = cp.get("pct") or {}, cp.get("values") or {}
            rows = [{"id": k, "label": lab, "pct": int(round(pc[k])), "text": _fmt(vals.get(k), (cat_m.get(k) or {}).get("fmt"))}
                    for k, lab in PROFILE if _num(pc.get(k)) is not None and _num(vals.get(k)) is not None]
            if len(rows) >= 5:
                srt = sorted(rows, key=lambda r: -r["pct"])
                profile = {"strong": srt[:3], "weak": sorted(srt[3:], key=lambda r: r["pct"])[:2]}
        # ── the facts
        # follow.py's templates write about a team ("The Brewers have ..."): only its subject-free ones get a context
        # here (the league ranks and the 7-day swing); the player lines are this module's own (below)
        ctx = {"name": name, "short": sur, "the": False, "phase": cphase, "final": cphase == "offseason",
               "league_name": f"the {TN} this year"}
        if cp and active:
            pr = []
            for k, lab in PCTL:
                rkd = lg_rank.get(k) or {}
                if pid in rkd:
                    pr.append({"label": lab, "rank": rkd[pid], "of": len(rkd), "tied": list(rkd.values()).count(rkd[pid]) > 1,
                               "text": _fmt((cp.get("values") or {}).get(k), (cat_m.get(k) or {}).get("fmt")), "model": k.endswith("_rating")})
            ctx["pctl"] = pr
        if cphase == "season" and fq is not None and ser_fq:
            ctx["chances"] = [{"label": "Finals", "series": ser_fq}]
        mine = []
        who = sur
        if sk and cphase == "season" and sk[1] >= 3:
            kind, n = sk
            longest = FL.longest_run(this_year, asof, kind)
            tail = ", the longest run of the year" if n >= 5 and longest == n and kind == "W" else ""
            mine.append({"kind": "streak", "score": (12 if kind == "W" else 9) * min(n, 8) + (10 if tail else 0),
                         "text": f"{who} has {'won' if kind == 'W' else 'lost'} {n} matches in a row{tail}."})
        rp = [r for r in results if r["p"] is not None][-10:]
        if cphase == "season" and len(rp) == 10:
            won = sum(1 for r in rp if r["res"] == "W")
            xp = sum(r["p"] for r in rp)
            if abs(won - xp) >= 2:
                mine.append({"kind": "form_xp", "score": 22 + 9 * abs(won - xp),
                             "text": f"{who} has won {won} of the last 10 matches; our pre-match chances added up to {xp:.1f}."})
        if rt:
            sc = 50 if rt["rank"] == 1 else max(FL.MIN_SCORE + 1, 34 - 1.5 * (rt["rank"] - 1)) if rt["rank"] <= 30 else FL.MIN_SCORE + 1
            mine.append({"kind": "rating", "score": sc, "text": f"{who} is {FL.ordinal(rt['rank'])} in our Elo ratings ({rt['text']})."})
        eh = sorted((FL._dt(e[0]), _num(e[1])) for e in (j.get("elo") or []) if isinstance(e, list) and len(e) > 1 and FL._dt(e[0]) and _num(e[1]) is not None)
        eh = [e for e in eh if e[0] <= asof]
        if eh and cphase == "season":
            base = [e for e in eh if e[0] <= asof - timedelta(days=30)]
            if base and eh[-1][0] > asof - timedelta(days=30):
                d = eh[-1][1] - base[-1][1]
                if abs(d) >= 25:
                    mine.append({"kind": "rating_move", "score": 28 + 0.4 * min(abs(d), 100),
                                 "text": f"{who}{chr(39)}s Elo is {'up' if d > 0 else 'down'} {abs(d):.0f} points in the last 30 days, to {eh[-1][1]:,.0f}."})
        if cp and active:
            tr, wr = lg_rank.get("titles") or {}, lg_rank.get("win_pct") or {}
            if titles and tr.get(pid) == 1:
                tied = list(tr.values()).count(1) > 1
                mine.append({"kind": "best_record", "score": 66 if not tied else 54,
                             "text": f"{titles} title{'s' if titles != 1 else ''} in {year}, {'the joint-most' if tied else 'the most'} on the {TL}."})
            elif wr.get(pid) in (1, 2) and rec:
                mine.append({"kind": "best_record", "score": 62 if wr[pid] == 1 else 44,
                             "text": f"{'The best' if wr[pid] == 1 else 'The 2nd-best'} win-loss record on the {TL} this year: {rec}."})
            v = cp.get("values") or {}
            for k, what in (("tb_over", "tiebreaks"), ("dec_over", "deciding sets")):
                ov = _num(v.get(k))
                if ov is not None and abs(ov) >= 2:
                    mine.append({"kind": "luck", "score": 24 + 4 * min(abs(ov), 6),
                                 "text": f"{who} has won {abs(ov):.1f} {'more' if ov > 0 else 'fewer'} {what} than expected from the points won on serve and return this year."})
                    break
        if rec and cphase == "season":
            ly = [r for r in results if str(r["start"])[:4] == str(year - 1) and str(r["start"])[5:10] <= today[5:10]]
            if len(ly) >= 10 and sum(wl) >= 10:
                lw = (sum(1 for r in ly if r["res"] == "W"), sum(1 for r in ly if r["res"] == "L"))
                dw = (wl[0] - wl[1]) - (lw[0] - lw[1])
                if abs(dw) >= 6:
                    mine.append({"kind": "vs_last", "score": 24 + 1.5 * min(abs(dw), 24) + (6 if dw > 0 else 0),
                                 "text": f"{who} is {rec} this year, against {FL.record_text(*lw)} at this point of {year - 1}."})
        if cphase == "season" and fq is not None and fq >= 0.9995 and (rank or 999) <= 20:
            mine.append({"kind": "clinch", "score": 48, "text": f"In the {TN} Finals field in every one of our {int(race.get('n_sims') or 10000):,} simulated seasons."})
        elif cphase == "season" and no1 is not None and 0.05 <= no1 < 0.995:
            mine.append({"kind": "call", "score": 40 + 30 * no1, "text": f"Our call: {FL.pct_text(no1)} to finish {year} as the world No. 1."})
        dfd = [d for d in (j.get("to_defend") or []) if isinstance(d, list) and len(d) > 2 and str(d[1]) >= today and _num(d[2])]
        if dfd and cphase == "season":
            d0 = dfd[0]
            more = f", then {_num(dfd[1][2]):,.0f} from {_the(_event_short(prev_events, dfd[1][0]))}" if len(dfd) > 1 else ""
            mine.append({"kind": "sos", "score": 26 + min(30, _num(d0[2]) / 50),
                         "text": f"Points to defend: {_num(d0[2]):,.0f} from {_the(_event_short(prev_events, d0[0]))} last year, coming off on {_nice_day(d0[1])}{more}."})
        # the next match is on the card already; a fact only when it is a big one (follow.py's big-game bar, 45)
        if next_ctx and next_ctx["start"] and FL._dt(next_ctx["start"]) > asof and (_num(next_ctx["score"]) or 0) >= 45:
            rd = ROUND.get(next_ctx["round"], next_ctx["round"] or "next round")
            pc_ = f"; our chance {FL.pct_text(next_ctx['p'])}" if next_ctx["p"] is not None else ""
            mine.append({"kind": "big_game", "score": min(80, max(FL.MIN_SCORE + 2, _num(next_ctx["score"]) or 0)),
                         "text": f"Next: the {rd} at {_the(_event_short(events, next_ctx['event']))} against {next_ctx['opp']}{pc_}."})
        if last and cphase == "season" and last.get("score"):
            sc = f"{last['score'][0]}{FL.DASH}{last['score'][1]}"
            mine.append({"kind": "form_xp", "score": FL.MIN_SCORE + 1,
                         "text": f"Last time out: {'beat' if last['res'] == 'W' else 'lost to'} {last['opp']['name']} {sc} in sets ({last['comp'].replace(' · ', ', ')})."})
        fx = _facts(ctx, mine, asof, cphase)
        cards[pid] = FL.make_card(site=SITE, sport=SPORT, scope=tour, ident=pid, team=team, asof=asof, phase=cphase, season=year,
                                  now=now_blk, chances=chances, next_games=nxt, next_note=note, last=last, line=line, profile=profile,
                                  facts=fx)
    return FL.write_cards(out_dir or (data / "follow"), tour, cards)


def main(argv=None) -> int:
    import argparse
    from oddsmarkets.tennis import analytics as an
    ap = argparse.ArgumentParser(description="Write the Ace's follow cards from the payloads on disk")
    ap.add_argument("--data", default=None)
    ap.add_argument("--tours", nargs="*", default=["atp", "wta"])
    ap.add_argument("--now", default=None, help="ISO build clock (default now)")
    a = ap.parse_args(argv)
    data = Path(a.data) if a.data else an.data_root()
    now = FL._dt(a.now) if a.now else None
    for t in a.tours:
        s = build(data, t, now)
        print(f"{t}: {s['n']} cards, {s['bytes'] / 1024:.0f} KB, largest {s['max']} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
