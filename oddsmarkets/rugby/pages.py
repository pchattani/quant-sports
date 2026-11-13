"""
The Quant Scrum's payload writers: one function per page family, all reading the Scope state from build.py.
build_scope() is the entry point (scripts/build_scrum.py calls it once per scope, inside a guarded step).
"""
from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import analytics as AN, build as B, comps, config, extras as X, models, nations, players as PL, rankings, store, validate
from .sources import espn

COMP_NAME = {v["key"]: v["name"] for v in config.COMPS.values()}
COMP_NAME.update({"w6n": "Women's Six Nations", "wxv": "WXV"})
COMP_TIER = {"rwc": 50, "wrwc": 40, "nc": 38, "six": 40, "trc": 36, "lions": 42, "tri20": 30, "test": 22,
             "oly7m": 24, "oly7w": 22}
r1 = B.r1


def game_value(st: dict, mins: float, grp: str | None, ana: dict, weights: dict | None) -> float | None:
    """A player's Scrum value for one test: the value model's points for what he did (models.VALUE_TEAM weights on
    the player's counts), minus a replacement-level player of his group over the same minutes, plus goal kicking
    above an average kicker (2.5 points a kick). None without statistics or minutes."""
    if not st or not weights or mins <= 0:
        return None
    v = sum((weights.get(k) or 0.0) * float(st.get(k) or 0.0) for k in PL.VALUE_KEYS)
    v -= (ana.get("repl") or {}).get(grp, 0.0) * mins / 80.0
    made = (st.get("con") or 0) + (st.get("pg") or 0)
    kp = st.get("kpct")
    if made and isinstance(kp, (int, float)) and kp > 0:
        v += 2.5 * (made - AN.KICK_AVG * made / kp)
    return v


def win_chance_path(m: dict, fc: dict | None) -> list | None:
    """Our home-win chance through a finished test, from the scoring events: at minute t with the home side d points
    up, the final margin is d plus the pre-match expected margin over the time left, spread by the pre-match spread
    times the square root of the time left. [[minute, chance]] from kick-off to full time."""
    evs = [e for e in (m.get("events") or []) if isinstance(e[0], (int, float)) and e[5] is not None and e[6] is not None]
    if not fc or not evs or fc.get("margin") is None:
        return None
    mg, sd = float(fc["margin"]), float(fc.get("sd") or 14.0)

    def p_at(t, d):
        f = max(0.0, (80.0 - min(t, 80.0)) / 80.0)
        if f <= 0:
            return 1.0 if d > 0 else (0.0 if d < 0 else 0.5)
        mu, s_ = d + mg * f, sd * math.sqrt(f)
        return 1.0 - 0.5 * (1.0 + math.erf((0.5 - mu) / (s_ * math.sqrt(2.0))))
    out = [[0, round(p_at(0, 0), 4)]]
    for e in evs:
        t = min(int(e[0]), 80)
        out.append([t, round(p_at(t, e[5] - e[6]), 4)])
    fin = m["hs"] - m["as"]
    out.append([80, 1.0 if fin > 0 else (0.0 if fin < 0 else 0.5)])
    return out


def short_card(S, m, fc):
    c = B.card(S, m, fc)
    return c


# ── matches ───────────────────────────────────────────────────────────────────────────────────────────────

# the team measures the match page's tale of the tape compares (docs/scrum/assets/js/sc-matches.js TAPE_IDS)
TAPE_METRICS = ["pf", "pa", "tf", "ta", "metres", "breaks", "gainline", "tackle_pct", "to_won", "ruck_pct", "scrum_pct",
                "lineout_pct", "pens", "kick_pct"]


class GoingIn:
    """How the two sides stood going into a test that has started or finished (no look-ahead: a game page never shows
    numbers that include the test itself or anything after it). Each side's last five results, the head to head, our
    ratings rank (build.walk, from the ratings at the start of the day), World Rugby points (the replica's points
    before the test) and the team profile over the two years before (analytics.team_profiles on the tests played before
    that day). All of it comes from tests dated before the start, so every past page is backfilled by the normal page
    writer at the next build."""

    def __init__(self, S, w, rep):
        self.S, self.w, self.rep = S, w, rep
        self.days = [m["date"][:10] for m in S.finals]
        self.res: dict = defaultdict(list)          # team -> [(day, W|D|L)]
        self.pairs: dict = defaultdict(list)        # (team, team) sorted -> [match]
        self.stat_days: dict = defaultdict(list)    # team -> [day] of its tests with team statistics
        for m in S.finals:
            h, a, d = m["home"]["id"], m["away"]["id"], m["date"][:10]
            r = "W" if m["hs"] > m["as"] else ("D" if m["hs"] == m["as"] else "L")
            self.res[h].append((d, r))
            self.res[a].append((d, {"W": "L", "L": "W"}.get(r, r)))
            self.pairs[tuple(sorted((h, a)))].append(m)
            if m.get("hstat") and m.get("astat"):
                self.stat_days[h].append(d)
                self.stat_days[a].append(d)
        self._prof: dict = {}

    def form(self, tid: str, day: str, n: int = 5) -> str:
        rs = self.res.get(tid) or []
        i = bisect_left(rs, (day, ""))
        return "".join(r for _d, r in rs[max(0, i - n):i])

    def h2h(self, h: str, a: str, day: str) -> dict | None:
        out = {"p": 0, "w": 0, "d": 0, "l": 0, "pf": 0, "pa": 0, "ro": 0, "first": None, "last": None}
        for m in self.pairs.get(tuple(sorted((h, a)))) or []:
            if m["date"][:10] >= day:
                break
            us, th = (m["hs"], m["as"]) if m["home"]["id"] == h else (m["as"], m["hs"])
            out["p"] += 1
            out["w" if us > th else ("d" if us == th else "l")] += 1
            if m.get("ro"):
                out["ro"] += 1
            else:
                out["pf"] += us
                out["pa"] += th
            out["first"] = out["first"] or m["date"][:10]
            out["last"] = {"id": m["id"], "date": m["date"][:10], "us": us, "them": th, "ro": 1 if m.get("ro") else 0}
        return out if out["p"] else None

    def profile(self, h: str, a: str, day: str, days: int = 730, min_n: int = 6) -> dict | None:
        since = (date.fromisoformat(day) - timedelta(days=days)).isoformat()

        def n_in(t):
            ds = self.stat_days.get(t) or []
            return bisect_left(ds, day) - bisect_left(ds, since)
        if n_in(h) < min_n or n_in(a) < min_n:
            return None
        if day not in self._prof:
            lo, hi = bisect_left(self.days, since), bisect_left(self.days, day)
            self._prof[day] = AN.team_profiles(self.S.finals[lo:hi], day, days=days, min_n=min_n)["teams"]
        ph, pa = self._prof[day].get(h), self._prof[day].get(a)
        if not ph or not pa:
            return None
        rows = {}
        for k in TAPE_METRICS:
            x, y = ph["m"].get(k), pa["m"].get(k)
            if x and y and x.get("pct") is not None and y.get("pct") is not None:
                rows[k] = [[r1(x["raw"], 3), x["pct"]], [r1(y["raw"], 3), y["pct"]]]
        return {"n": [ph["n"], pa["n"]], "since": since, "m": rows} if rows else None

    def block(self, m: dict, fc: dict | None) -> dict:
        h, a, day = m["home"]["id"], m["away"]["id"], m["date"][:10]
        out = {"before": m["date"], "form": [self.form(h, day), self.form(a, day)], "h2h": self.h2h(h, a, day)}
        if fc and fc.get("rank") is not None:
            out["rank"], out["of"] = fc["rank"], fc.get("of")
        ex = self.rep["exchange"].get(m["id"])
        if ex:
            out["wr"] = ex["before"]
        elif m["status"] != "final":
            live = self.rep["live"].points
            if h in live and a in live:
                out["wr"] = [round(live[h], 2), round(live[a], 2)]
        pr = self.profile(h, a, day)
        if pr:
            out["profile"] = pr
        return out


def started(S, m: dict) -> bool:
    """Under way or over: a final or live status, or a kick-off time already passed (the feed can lag)."""
    return m.get("status") in ("final", "live") or str(m.get("date") or "") <= S.now.strftime("%Y-%m-%dT%H:%M")


def match_page(S, w, rep, m, ana, gi: GoingIn | None = None) -> dict:
    fc = w["fc"].get(m["id"]) or w["up"].get(m["id"])
    out = {"ok": True, "match": B.card(S, m, fc), "season": int(m["date"][:4]), "comp_name": COMP_NAME.get(m.get("comp"), ""),
           "attendance": m.get("attendance")}
    rf = m.get("referee") or {}
    if rf.get("name"):
        out["referee"] = {"name": rf["name"], "union": rf.get("union") or "", "k": X.fold(rf["name"])}
    vi = X.venue_of(m)
    if vi:
        out["venue"] = {"place": vi.get("place"), "elev": round(vi["elev"]) if isinstance(vi.get("elev"), (int, float)) else None,
                        "alt": X.at_altitude(m)}
    wx = X.weather_of(m)
    if wx:
        out["weather"] = {k: wx.get(k) for k in ("temp", "rh", "wind", "gust", "rain", "kind", "issued") if wx.get(k) is not None}
    if m.get("source") == "wikipedia":
        out["source"] = {"name": "Wikipedia", "page": m.get("page") or "", "licence": "CC BY-SA 4.0"}
    elif m.get("source") == "sofascore":
        out["source"] = {"name": "Sofascore", "page": m.get("note") or "", "licence": ""}
    if m.get("stat_src") == "sofascore":
        out["stat_src"] = "Sofascore"
    if m.get("ro"):
        out["ro"] = 1
    hh, ah = m.get("hh"), m.get("ah")       # [half-time, full-time] for each side
    evs = [e for e in (m.get("events") or []) if isinstance(e[0], (int, float)) and e[5] is not None]
    if hh and ah and ((hh[0] or 0) + (ah[0] or 0) > 0 or (m.get("hs") or 0) + (m.get("as") or 0) == 0):
        out["halves"] = [hh, ah]
    elif evs and m.get("hs") is not None:
        # the feed sends a 0-0 half-time when it has none: the score at the last scoring event of the first 40
        # minutes instead (an estimate: stoppage time is not marked), else no half-time at all
        first = [e for e in evs if e[0] <= 40]
        ht = (first[-1][5], first[-1][6]) if first else (0, 0)
        out["halves"] = [[ht[0], m["hs"]], [ht[1], m["as"]]]
        out["halves_est"] = 1
    wp = win_chance_path(m, fc) if m.get("status") == "final" else None
    if wp:
        out["wp"] = wp
    if fc:
        ctx = fc.get("ctx") or {}
        out["forecast"] = {"p": [r1(fc["p_home"], 4), r1(fc["p_draw"], 4), r1(fc["p_away"], 4)], "margin": r1(fc["margin"]),
                           "total": r1(fc.get("total")), "exp": [r1(fc.get("exp_h")), r1(fc.get("exp_a"))],
                           "rating": [r1(fc.get("r_h"), 2), r1(fc.get("r_a"), 2)], "edge": r1(fc.get("edge")),
                           "travel_km": [round(ctx.get("km_h", 0)), round(ctx.get("km_a", 0))],
                           "zones": [r1(ctx.get("tz_h"), 1), r1(ctx.get("tz_a"), 1)],
                           "rest": [ctx.get("rest_h"), ctx.get("rest_a")], "alt": ctx.get("alt") or 0,
                           # the margin's spread (the model's normal sd behind p): the match page's likely-range bar
                           "sd": r1(fc.get("sd"))}
        if (fc.get("ctx") or {}).get("side") == -1:
            out["forecast"]["at_home"] = "a"        # the side listed second plays in its own country (Model.context)
    if gi is not None and started(S, m):
        out["pre"] = gi.block(m, fc)
    # World Rugby exchange (replica): the points each side took
    ex = rep["exchange"].get(m["id"])
    if ex:
        out["wr"] = ex
    if m.get("hstat") and m.get("astat"):
        out["stats"] = {"home": m["hstat"], "away": m["astat"]}
    lines = {}
    weights = S.fit.get("value") or {}
    any_stats = False
    for side in ("h", "a"):
        rows = m.get("l" + side) or []
        if not rows:
            continue
        mins = PL.minutes(m, side)
        lines[side] = []
        for r in rows:
            aid = r[0]
            a = S.athletes.get(aid) or {}
            mn, est = mins.get(aid, (0.0, True))
            st = r[5] or {}
            has = any(isinstance(v, (int, float)) and v for v in st.values())
            any_stats = any_stats or has
            pos = r[2] if r[2] != "R" else (ana["pos"].get(aid) or "R")
            gv = game_value(st, mn, PL.POS_GROUP.get(ana["pos"].get(aid) or pos), ana, weights) if has else None
            lines[side].append({"id": aid, "n": a.get("name") or aid, "j": r[1], "pos": pos,
                                "st": r[3], "c": r[4], "min": int(round(mn)), "est": 1 if est else 0, "s": st if has else {},
                                "gv": r1(gv, 2)})
    if lines:
        out["lines"] = lines
        out["has_stats"] = 1 if any_stats else 0
    if m.get("events"):
        out["events"] = [e for e in m["events"]]
    return out


def year_payloads(S, w, data: Path) -> dict:
    by = defaultdict(list)
    for m in S.finals:
        by[int(m["date"][:4])].append(B.card(S, m, w["fc"].get(m["id"])))
    for m in S.upcoming:
        by[int(m["date"][:4])].append(B.card(S, m, w["up"].get(m["id"])))
    for y, lst in by.items():
        lst.sort(key=lambda c: c["date"])
        B.write(data / "years" / f"{y}.json", {"ok": True, "year": y, "matches": lst})
    return {"years": sorted(by)}


# ── the forecast log ──────────────────────────────────────────────────────────────────────────────────────

def forecast_log(S, w) -> dict:
    """Our published forecasts, frozen: an upcoming match's entry is refreshed at every build until kick-off, then
    never changed; the result is added once the match is final. Kept in the stores (survives CI) and published."""
    p = store.paths()["stores"] / f"forecast_log_{S.scope}.json"
    try:
        logd = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logd = {"v": 1, "rows": {}}
    rows = logd.setdefault("rows", {})
    for k in [k for k, r in rows.items() if r.get("home") not in S.teams or r.get("away") not in S.teams]:
        del rows[k]                     # a placeholder side (a final's "winner of ...") is not a forecast
    now_iso = S.now.strftime("%Y-%m-%dT%H:%MZ")
    horizon = (S.now + timedelta(days=21)).strftime("%Y-%m-%dT%H:%M")
    for m in S.upcoming:
        if m["date"] > horizon:
            continue
        fc = w["up"].get(m["id"])
        if not fc:
            continue
        if m["date"] <= S.now.strftime("%Y-%m-%dT%H:%M"):
            continue                                  # started: the entry is frozen
        rows[m["id"]] = {"date": m["date"], "comp": m.get("comp"), "home": m["home"]["id"], "away": m["away"]["id"],
                         "p": [r1(fc["p_home"], 4), r1(fc["p_draw"], 4), r1(fc["p_away"], 4)], "m": r1(fc["margin"]),
                         "t": r1(fc["total"]), "published": now_iso}
    for m in S.finals:
        r = rows.get(m["id"])
        if r and "hs" not in r:
            r["hs"], r["as"] = m["hs"], m["as"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(logd, separators=(",", ":")), encoding="utf-8")
    return logd


# ── ratings and rankings ──────────────────────────────────────────────────────────────────────────────────

def monthly(hist: list) -> list:
    """[(date, rating)] -> the last value of each month, as [[YYYY-MM, rating]]."""
    out = {}
    for d, v in hist:
        out[d[:7]] = v
    return [[k, v] for k, v in sorted(out.items())]


# a rating is ranked only when it is tied to the main pool of test sides: five or more tests rated, and a tier-one or
# tier-two side or three or more tests against one in the last four years. Ratings are identified only up to an offset
# within each group of sides that play each other, so a side that meets only other tier-three sides gets a
# provisional rating with no rank. Invitational sides (the Lions, the Barbarians) are outside the ratings table.
RANK_MIN_TESTS = 5
RANK_MIN_CONN = 3


def comparable(t: dict) -> bool:
    return (t.get("n") or 0) >= RANK_MIN_TESTS and ((t.get("tier") or 3) <= 2 or (t.get("conn") or 0) >= RANK_MIN_CONN)


def ratings_payload(S, w, rep, wr_rank: dict | None = None) -> dict:
    mdl = w["model"]
    active_from = (S.now - timedelta(days=4 * 365)).date().isoformat()
    teams = []
    for tid, hist in w["hist"].items():
        if not hist or hist[-1][0] < active_from:
            continue
        if nations.invitational(S.name(tid)):
            continue
        now_r = mdl.rating(tid)

        def at(days):
            cut = (S.now - timedelta(days=days)).date().isoformat()
            prev = [v for d, v in hist if d <= cut]
            return prev[-1] if prev else None
        r30, r365 = at(30), at(365)
        res = B.team_results(S, tid)
        yr = [m for m in res if m["date"][:10] >= (S.now - timedelta(days=365)).date().isoformat()]
        wdl = Counter()
        for m in yr:
            us = m["hs"] if m["home"]["id"] == tid else m["as"]
            th = m["as"] if m["home"]["id"] == tid else m["hs"]
            wdl["w" if us > th else ("d" if us == th else "l")] += 1
        teams.append({"id": tid, "rating": r1(now_r, 2), "att": r1(mdl.att.get(tid), 2), "dfn": r1(mdl.dfn.get(tid), 2),
                      "n": mdl.n.get(tid, 0), "last": hist[-1][0], "d30": r1(now_r - r30, 2) if r30 is not None else None,
                      "d365": r1(now_r - r365, 2) if r365 is not None else None, "form": B.form_of(S, tid),
                      "rec12": [wdl["w"], wdl["d"], wdl["l"]], "wr": r1(rep["live"].points.get(tid), 2),
                      "tier": (S.teams.get(tid) or {}).get("tier"),
                      "conn": sum(1 for m in res if m["date"][:10] >= active_from and
                                  (S.teams.get(m["away"]["id"] if m["home"]["id"] == tid else m["home"]["id"]) or {}).get("tier", 3) <= 2),
                      "hist": monthly([h for h in hist if h[0] >= "2003-01-01"])})
    teams.sort(key=lambda t: -(t["rating"] if t["rating"] is not None else -99))
    k = 0
    for t in teams:
        if comparable(t):
            k += 1
            t["rank"] = k
        else:
            t["rank"] = None
            t["prov"] = 1
        t["wr_rank"] = (wr_rank or {}).get(t["id"])
    return {"ok": True, "asof": S.today, "teams": teams, "n_ranked": k, "model": S.fit.get("model"), "home_adv": r1(S.p.H, 2),
            "mu": r1(mdl.mu, 1), "rank_rule": {"min_tests": RANK_MIN_TESTS, "min_conn": RANK_MIN_CONN}}


def rankings_payload(S, w, rep) -> dict:
    live, burn = rep["live"], rep["burn"]
    active = (S.now - timedelta(days=4 * 365)).date().isoformat()
    tab = [(t, p) for t, p in live.table() if (live.last.get(t) or burn.last.get(t) or "") >= active]
    # last week's table: the live table rolled back over the matches of the last 7 days
    week_ago = (S.now - timedelta(days=7)).date().isoformat()
    prev = dict(live.points)
    for d, h, ph, a, pa, x in reversed(live.history):
        if d <= week_ago:
            break
        prev[h] = prev.get(h, ph) - x
        prev[a] = prev.get(a, pa) + x
    prev_rank = {t: i + 1 for i, (t, _p) in enumerate(sorted([(t, prev.get(t, p)) for t, p in tab], key=lambda r: -r[1]))}
    rows = []
    for i, (t, p) in enumerate(tab):
        rows.append({"id": t, "rank": i + 1, "pts": round(p, 2), "prev": round(prev.get(t, p), 2), "prev_rank": prev_rank.get(t),
                     "played": live.played.get(t, 0) or burn.played.get(t, 0), "last": live.last.get(t) or burn.last.get(t)})
    # history: the burn-in replica's points at each month end (top 20 today), then the live table after the anchor
    top = [r["id"] for r in rows[:20]]
    hist = defaultdict(dict)
    for d, h, ph, a, pa, _x in burn.history:
        for t, v in ((h, ph), (a, pa)):
            if t in top and d >= "2004-01-01":
                hist[t][d[:7]] = v
    for d, h, ph, a, pa, _x in live.history:
        for t, v in ((h, ph), (a, pa)):
            if t in top:
                hist[t][d[:7]] = v
    history = {t: [[k, round(v, 2)] for k, v in sorted(d.items())] for t, d in hist.items()}
    # what each result would do: the next 12 tests between ranked sides
    wi = []
    for m in S.upcoming[:40]:
        h, a = m["home"]["id"], m["away"]["id"]
        if h not in live.points or a not in live.points:
            continue
        rows_wi = rankings.what_if(live.points[h], live.points[a], None if m.get("neutral") else "a", m["date"],
                                   world_cup=m.get("comp") in ("rwc", "wrwc"))
        fc = w["up"].get(m["id"]) or {}
        wi.append({"id": m["id"], "date": m["date"], "home": h, "away": a, "comp": m.get("comp"),
                   "pts": [round(live.points[h], 2), round(live.points[a], 2)], "bands": rows_wi,
                   "p": [r1(fc.get("p_home"), 3), r1(fc.get("p_draw"), 3), r1(fc.get("p_away"), 3)] if fc else None})
        if len(wi) >= 12:
            break
    moves = []
    for d, h, ph, a, pa, x in reversed(live.history[-30:]):
        moves.append({"date": d, "home": h, "away": a, "x": x, "h_after": ph, "a_after": pa})
    return {"ok": True, "asof": S.today, "source": rep["source"], "anchor": {"date": validate.PUBLISHED_DATE,
            "text": "World Rugby's published table of 28 September 2026 (quoted on Wikipedia)"} if rep["source"] == "anchored" else None,
            "table": rows, "history": history, "what_if": wi, "moves": moves, "check": rep["check"],
            "rule": {"home_bonus": rankings.HOME_BONUS, "home_bonus_ends": rankings.HOME_BONUS_ENDS}}


# ── teams ─────────────────────────────────────────────────────────────────────────────────────────────────

def h2h(S, tid) -> list:
    rec = defaultdict(lambda: {"p": 0, "w": 0, "d": 0, "l": 0, "pf": 0, "pa": 0, "last": None, "first": None})
    for m in B.team_results(S, tid):
        home = m["home"]["id"] == tid
        opp = m["away"]["id"] if home else m["home"]["id"]
        us, th = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
        r = rec[opp]
        r["p"] += 1
        r["w" if us > th else ("d" if us == th else "l")] += 1
        if not m.get("ro"):
            r["pf"] += us
            r["pa"] += th
        else:
            r["ro"] = r.get("ro", 0) + 1
        r["first"] = r["first"] or m["date"][:10]
        r["last"] = {"id": m["id"], "date": m["date"][:10], "us": us, "them": th, "ro": 1 if m.get("ro") else 0}
    out = [{"opp": o, **v} for o, v in rec.items()]
    out.sort(key=lambda r: (-r["p"], r["opp"]))
    return out


def team_page(S, w, rep, ana, prof, tid, comps_out, ratings: dict | None = None) -> dict:
    t = S.teams.get(tid) or {}
    res = B.team_results(S, tid)
    mdl = w["model"]
    rows = []
    for m in res[-60:][::-1]:
        rows.append(B.card(S, m, w["fc"].get(m["id"])))
    nxt = [B.card(S, m, w["up"].get(m["id"])) for m in S.upcoming if tid in (m["home"]["id"], m["away"]["id"])][:6]
    # squad: players capped for the side in the last 12 months; most capped all time in our data
    since = (S.now - timedelta(days=365)).date().isoformat()
    caps = Counter()
    recent = Counter()
    last_seen = {}
    pts = Counter()
    tries = Counter()
    for aid, gs in ana["games"].items():
        for g in gs:
            if g["team"] != tid:
                continue
            caps[aid] += 1
            pts[aid] += (g["stats"] or {}).get("pts") or 0
            tries[aid] += (g["stats"] or {}).get("tries") or 0
            last_seen[aid] = max(last_seen.get(aid, ""), g["date"])
            if g["date"] >= since:
                recent[aid] += 1
    def prow(aid):
        a = S.athletes.get(aid) or {}
        rec = ana["players"].get(aid) or {}
        cur = rec.get("cur") or {}
        return {"id": aid, "n": a.get("name") or aid, "pos": rec.get("pos"), "caps": caps[aid], "pts": int(pts[aid]),
                "tries": int(tries[aid]), "last": last_seen.get(aid), "age": AN.age_on(a.get("dob"), S.today),
                "val": r1((cur.get("rates") or {}).get("val80"), 2) if cur.get("qual") else None,
                "wcaps": (CAPS.get("by_aid") or {}).get(aid, {}).get("caps")}
    squad = sorted((prow(a) for a in recent), key=lambda r: (PL.GROUP_ORDER.index(PL.POS_GROUP.get(r["pos"] or "", "back_three")) if r["pos"] else 9, -r["caps"]))
    most = [prow(a) for a, _n in caps.most_common(20)]
    top_pts = [prow(a) for a, _n in pts.most_common(10) if pts[a] > 0]
    top_tries = [prow(a) for a, _n in tries.most_common(10) if tries[a] > 0]
    p = prof["teams"].get(tid)
    profile = None
    if p:
        profile = {"n": p["n"], "since": prof["since"], "m": {k: {"v": r1(v["raw"], 3), "adj": r1(v["adj"], 3), "pct": v["pct"]} for k, v in p["m"].items()},
                   "sw": AN.strengths(p)}
    hist = w["hist"].get(tid) or []
    wr_hist = [[d[:7], v] for d, v in _team_wr_hist(rep, tid)]
    chances = []
    for key, c in comps_out.items():
        sim = (c.get("next") or {}).get("sim") or c.get("sim")
        if not sim:
            continue
        for r in sim.get("teams") or []:
            if r["team"] == t.get("name"):
                chances.append({"comp": key, "season": (c.get("next") or {}).get("season") or c.get("season"),
                                "title": r.get("title", r.get("champion")), "row": r})
    allrec = Counter()
    for m in res:
        us = m["hs"] if m["home"]["id"] == tid else m["as"]
        th = m["as"] if m["home"]["id"] == tid else m["hs"]
        allrec["w" if us > th else ("d" if us == th else "l")] += 1
    rr = next((x for x in (ratings or {}).get("teams") or [] if x["id"] == tid), None) or {}
    # results against our chances: the last 40 tests, cumulative wins and the wins we expected
    xw, cw, ce = [], 0.0, 0.0
    for m in res[-40:]:
        f = w["fc"].get(m["id"]) or {}
        home = m["home"]["id"] == tid
        us, th = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
        p = f.get("p_home") if home else f.get("p_away")
        if p is None:
            continue
        cw += 1.0 if us > th else (0.5 if us == th else 0.0)
        ce += p + 0.5 * (f.get("p_draw") or 0.0)
        xw.append([m["date"][:10], round(cw, 2), round(ce, 2), m["id"]])
    return {"ok": True, "id": tid, "team": t, "rank": rr.get("rank"), "of": (ratings or {}).get("n_ranked"),
            "prov": 1 if rr and not rr.get("rank") else 0, "wr_rank": (rep.get("wr_rank") or {}).get(tid),
            "invitational": 1 if nations.invitational(t.get("name") or "") else 0,
            "rating": r1(mdl.rating(tid), 2), "att": r1(mdl.att.get(tid), 2),
            "dfn": r1(mdl.dfn.get(tid), 2), "wr": r1(rep["live"].points.get(tid), 2), "form": B.form_of(S, tid, n=10),
            "record": [allrec["w"], allrec["d"], allrec["l"]], "first": res[0]["date"][:10] if res else None,
            "results": rows, "next": nxt, "h2h": h2h(S, tid), "squad": squad, "most_capped": most,
            "top_points": top_pts, "top_tries": top_tries, "profile": profile,
            "rating_hist": monthly(hist), "wr_hist": wr_hist, "chances": chances,
            "career_caps": (CAPS.get("most") or {}).get(tid), "caps_asof": CAPS.get("asof"),
            "xw": xw, "combos": combos(S, ana, tid), "grades": (GRADES.get(S.scope) or {}).get(tid),
            "years": form_years(S, w, tid)}


def form_years(S, w, tid) -> list:
    """Form year by year for the progression page: [year, tests, won, drawn, lost, points for, against, expected wins,
    tests with a forecast, margin over our forecast per test]. Expected wins and the forecast margin are our pre-match
    numbers (the walk-forward forecast made before each test: no look-ahead); a draw counts half a win. Tests before
    1891 carry the result only, so their points are left out."""
    rows = {}
    for m in B.team_results(S, tid):
        y = int(m["date"][:4])
        r = rows.setdefault(y, [y, 0, 0, 0, 0, 0, 0, 0.0, 0, 0.0])
        home = m["home"]["id"] == tid
        us, th = (m["hs"], m["as"]) if home else (m["as"], m["hs"])
        r[1] += 1
        r[2 if us > th else (3 if us == th else 4)] += 1
        if not m.get("ro"):
            r[5] += us
            r[6] += th
        f = w["fc"].get(m["id"]) or {}
        p = f.get("p_home") if home else f.get("p_away")
        if p is not None and not m.get("ro") and f.get("margin") is not None:
            r[7] += p + 0.5 * (f.get("p_draw") or 0.0)
            r[8] += 1
            r[9] += (us - th) - (f["margin"] if home else -f["margin"])
    out = []
    for y in sorted(rows):
        r = rows[y]
        out.append(r[:7] + [round(r[7], 2), r[8], round(r[9] / r[8], 1) if r[8] else None])
    return out


def progression_ref(S, ana) -> dict:
    """Each season's qualified players per position group: the 10th, 25th, 50th, 75th and 90th percentile of every
    per-80 rate (the kit's progression_ref.json shape: the peer band on the progression chart)."""
    by = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for rec in ana["players"].values():
        g = rec.get("grp")
        if not g:
            continue
        for y, s in (rec.get("seasons") or {}).items():
            if not s.get("qual"):
                continue
            for k in AN.PM_IDS:
                v = (s.get("rates") or {}).get(k)
                if isinstance(v, (int, float)) and not math.isnan(v):
                    by[str(y)][g][k].append(v)

    def q(vs, p):
        vs = sorted(vs)
        i = (len(vs) - 1) * p
        lo = int(math.floor(i))
        hi = min(lo + 1, len(vs) - 1)
        return vs[lo] + (vs[hi] - vs[lo]) * (i - lo)
    seasons = {}
    for y, groups in by.items():
        for g, mets in groups.items():
            n = max((len(v) for v in mets.values()), default=0)
            if n < 5:
                continue
            seasons.setdefault(y, {})[g] = {"n": n, "m": {k: [r1(q(v, p), 3) for p in (0.1, 0.25, 0.5, 0.75, 0.9)]
                                                           for k, v in mets.items() if len(v) >= 5}}
    return {"ok": True, "q": [10, 25, 50, 75, 90], "seasons": seasons}


# the pairings that decide a test: the half-backs (9 and 10), the centres (12 and 13), the locks (4 and 5)
PAIRS = [("halves", "Half-backs", (9, 10)), ("centres", "Centres", (12, 13)), ("locks", "Locks", (4, 5))]


def combos(S, ana, tid) -> list:
    """The most-used starting pairs over the last four years, with their record and points difference."""
    since = (S.now - timedelta(days=4 * 365)).date().isoformat()
    out = []
    for key, label, (j1, j2) in PAIRS:
        rec = defaultdict(lambda: {"n": 0, "w": 0, "d": 0, "l": 0, "pd": 0, "last": ""})
        for m in B.team_results(S, tid):
            if m["date"][:10] < since:
                continue
            side = "h" if m["home"]["id"] == tid else "a"
            st = {r[1]: r[0] for r in (m.get("l" + side) or []) if r[3]}
            if j1 not in st or j2 not in st:
                continue
            us, th = (m["hs"], m["as"]) if side == "h" else (m["as"], m["hs"])
            x = rec[(st[j1], st[j2])]
            x["n"] += 1
            x["w" if us > th else ("d" if us == th else "l")] += 1
            x["pd"] += us - th
            x["last"] = max(x["last"], m["date"][:10])
        rows = sorted(rec.items(), key=lambda kv: (-kv[1]["n"], -kv[1]["pd"]))[:5]
        out.append({"key": key, "label": label, "jerseys": [j1, j2],
                    "rows": [{"a": a, "an": (S.athletes.get(a) or {}).get("name") or a, "b": b, "bn": (S.athletes.get(b) or {}).get("name") or b,
                              **v} for (a, b), v in rows]})
    return out


# career caps (Wikipedia) and physical profiles, filled by build_scope before the team and player pages
CAPS: dict = {}
PHYS: dict = {}


# position-group grades: each side's best regulars at the position (Scrum value per 80, the current window), ranked
# against the other ranked sides; filled by build_scope before the team pages are written
GRADES: dict = {}
GRADE_TOP = {"front_row": 4, "lock": 2, "back_row": 3, "halves": 2, "centres": 2, "back_three": 3}


def grade_table(S, ana, ratings) -> dict:
    ranked = {t["id"] for t in ratings["teams"] if t.get("rank")}
    last_year = (S.now - timedelta(days=400)).date().isoformat()
    pool = defaultdict(lambda: defaultdict(list))
    for aid, rec in ana["players"].items():
        cur = rec.get("cur") or {}
        g = rec.get("grp")
        if not g or not cur.get("qual") or rec["career"]["last"] < last_year:
            continue
        team = Counter(x["team"] for x in ana["games"][aid] if x["date"] >= ana["cur_from"]).most_common(1)
        if not team or team[0][0] not in ranked:
            continue
        pool[team[0][0]][g].append((cur["rates"]["val80"], aid))
    score = defaultdict(dict)
    for t, gs in pool.items():
        for g, lst in gs.items():
            lst.sort(reverse=True)
            k = GRADE_TOP[g]
            if len(lst) >= max(1, k // 2):
                top = lst[:k]
                score[g][t] = (sum(v for v, _a in top) / len(top), top)
    out = defaultdict(dict)
    for g, d in score.items():
        order = sorted(d.items(), key=lambda kv: -kv[1][0])
        n = len(order)
        for i, (t, (v, top)) in enumerate(order):
            q = i / max(1, n - 1)
            grade = "A" if q < 0.15 else "B" if q < 0.4 else "C" if q < 0.65 else "D" if q < 0.85 else "F"
            out[t][g] = {"rank": i + 1, "of": n, "v": round(v, 2), "grade": grade,
                         "lead": {"id": top[0][1], "n": (S.athletes.get(top[0][1]) or {}).get("name") or top[0][1], "v": round(top[0][0], 2)},
                         "weak": {"id": top[-1][1], "n": (S.athletes.get(top[-1][1]) or {}).get("name") or top[-1][1], "v": round(top[-1][0], 2)} if len(top) > 1 else None}
    return dict(out)


def _team_wr_hist(rep, tid):
    out = []
    for d, h, ph, a, pa, _x in rep["burn"].history:
        if h == tid:
            out.append((d, ph))
        elif a == tid:
            out.append((d, pa))
    if rep["source"] == "anchored":
        out = [x for x in out if x[0] <= validate.PUBLISHED_DATE]
        for d, h, ph, a, pa, _x in rep["live"].history:
            if h == tid:
                out.append((d, ph))
            elif a == tid:
                out.append((d, pa))
    dd = {}
    for d, v in out:
        dd[d[:7]] = round(v, 2)
    return sorted(dd.items())


def teams_payload(S, w, rep, prof, ratings: dict | None = None) -> dict:
    mdl = w["model"]
    rows = []
    # every ranked side (provisional and invitational sides are not ranked: see ratings_payload), so the board's ranks
    # are the Rankings page's; the profile (`m`) only where the source has six tests with team stats in two years
    for r in (ratings or {}).get("teams") or []:
        if not r.get("rank"):
            continue
        tid = r["id"]
        p = prof["teams"].get(tid) or {"n": 0, "m": {}}
        t = S.teams.get(tid) or {}
        rows.append({"id": tid, "rank": r["rank"], "rating": r1(mdl.rating(tid), 2), "att": r1(mdl.att.get(tid), 2), "dfn": r1(mdl.dfn.get(tid), 2),
                     "n": p["n"], "tests": r.get("n"), "form": B.form_of(S, tid, n=10), "tier": t.get("tier"),
                     "m": {k: [r1(v["raw"], 3), v["pct"]] for k, v in p["m"].items()}})
    rows.sort(key=lambda r: -(r["rating"] or -99))
    return {"ok": True, "asof": S.today, "since": prof["since"], "teams": rows,
            "metrics": [{"id": i, "label": l, "dir": d, "group": g, "unit": AN.TEAM_UNITS.get(i, "per test"),
                         "style": i in AN.STYLE} for i, l, d, g, _h in AN.TEAM_METRICS],
            "field": {k: r1(v, 3) for k, v in prof["field"].items()}}


# ── players ───────────────────────────────────────────────────────────────────────────────────────────────

def player_page(S, ana, aid, w) -> dict:
    rec = ana["players"][aid]
    a = S.athletes.get(aid) or {}
    gs = ana["games"][aid]
    teams = Counter(g["team"] for g in gs)
    team = teams.most_common(1)[0][0] if teams else None
    car = rec["career"]
    seasons = []
    for y, s in sorted(rec["seasons"].items()):
        ag = s["agg"]
        seasons.append({"y": y, "team": max(ag["teams"].items(), key=lambda kv: kv[1])[0] if ag["teams"] else team,
                        "n": ag["n"], "st": ag["starts"], "min": int(ag["min"]), "pts": int(ag["sums"].get("pts", 0)),
                        "tries": int(ag["sums"].get("tries", 0)), "q": 1 if s.get("qual") else 0,
                        "v": {k: r1(s["rates"].get(k), 3) for k in AN.PM_IDS if s["rates"].get(k) is not None},
                        "pc": {k: v for k, v in (s.get("pct") or {}).items() if v is not None}})
    # appearances before player stats exist (lineups only): caps by year
    caps_by_year = Counter(g["season"] for g in gs)
    log = []
    weights = S.fit.get("value") or {}
    for g in gs[-40:][::-1]:
        st = g["stats"] or {}
        m = S.by_id.get(g["mid"]) or {}
        gv = game_value(st, g["min"], rec.get("grp"), ana, weights) if any(isinstance(v, (int, float)) and v for v in st.values()) else None
        log.append({"id": g["mid"], "date": g["date"], "opp": g["opp"], "h": 1 if g["side"] == "h" else 0, "res": g["res"],
                    "sc": [m.get("hs"), m.get("as")] if g["side"] == "h" else [m.get("as"), m.get("hs")],
                    "comp": g["comp"], "j": g["jersey"], "st": 1 if g["starter"] else 0, "min": int(round(g["min"])),
                    "s": {k: st.get(k) for k in ("pts", "tries", "ta", "m", "car", "cb", "db", "off", "tk", "mt", "pc", "lo", "toc") if st.get(k)},
                    "gv": r1(gv, 2)})
    cur = rec.get("cur") or {}
    # most similar: within the group, on the current percentile vector
    sim = []
    if cur.get("pct") and cur.get("qual"):
        me = cur["pct"]
        keys = [k for k in AN.PM_IDS if me.get(k) is not None]
        for oid, orec in ana["players"].items():
            if oid == aid or orec.get("grp") != rec.get("grp"):
                continue
            oc = orec.get("cur") or {}
            if not oc.get("qual") or not oc.get("pct"):
                continue
            ks = [k for k in keys if oc["pct"].get(k) is not None]
            if len(ks) < 8:
                continue
            d = math.sqrt(sum((me[k] - oc["pct"][k]) ** 2 for k in ks) / len(ks))
            sim.append((d, oid))
        sim.sort()
        sim = [{"id": o, "n": (S.athletes.get(o) or {}).get("name") or o, "d": round(d, 1),
                "team": Counter(g["team"] for g in ana["games"][o]).most_common(1)[0][0]} for d, o in sim[:5]]
    return {"ok": True, "id": aid, "name": a.get("name") or aid, "bio": {k: a.get(k) for k in ("dob", "ht_cm", "wt_kg", "born") if a.get(k)},
            "age": AN.age_on(a.get("dob"), S.today), "pos": rec.get("pos"), "grp": rec.get("grp"), "team": team,
            "teams": dict(teams), "caps": car["n"], "starts": car["starts"], "capt": car["capt"], "first": car["first"], "last": car["last"],
            "wdl": [car["w"], car["d"], car["l"]], "min": int(car["min"]), "pts": int(car["sums"].get("pts", 0)),
            "tries": int(car["sums"].get("tries", 0)), "caps_by_year": sorted([[y, n] for y, n in caps_by_year.items()]),
            "cur": {"from": ana["cur_from"], "n": cur["agg"]["n"], "min": int(cur["agg"]["min"]), "q": 1 if cur.get("qual") else 0,
                    "v": {k: r1(cur["rates"].get(k), 3) for k in AN.PM_IDS if cur["rates"].get(k) is not None},
                    "pc": {k: v for k, v in (cur.get("pct") or {}).items() if v is not None}} if cur else None,
            "seasons": seasons, "log": log, "similar": sim, "splits": splits(S, ana, aid, rec),
            "wcaps": (CAPS.get("by_aid") or {}).get(aid), "phys": (PHYS.get("by_aid") or {}).get(aid),
            "phys_med": (PHYS.get("median") or {}).get(rec.get("grp"))}


SPLIT_KEYS = ["val80", "m", "car", "cb", "tk", "tkpct", "pc", "pts"]


def splits(S, ana, aid, rec) -> list:
    """Per-80 rates (shrunk toward the position like every rate on the site) over the current window, split by
    venue, result, role and the last ten tests."""
    grp = rec.get("grp")
    prior = (ana.get("prior") or {}).get(grp)
    weights = S.fit.get("value") or {}
    repl = (ana.get("repl") or {}).get(grp, 0.0)
    gs = [g for g in ana["games"][aid] if g["date"] >= ana["cur_from"] and g["stats"]]
    if len(gs) < 4:
        return []
    groups = [("All tests", gs), ("Home", [g for g in gs if g["side"] == "h"]), ("Away", [g for g in gs if g["side"] == "a"]),
              ("Won", [g for g in gs if g["res"] == "W"]), ("Lost", [g for g in gs if g["res"] == "L"]),
              ("Started", [g for g in gs if g["starter"]]), ("From the bench", [g for g in gs if not g["starter"]]), ("Last 10", gs[-10:])]
    out = []
    for label, sel in groups:
        if not sel:
            continue
        a = next(iter(PL.aggregate(sel).values()))
        rt = PL.rates(a, prior)
        rt["val80"] = PL.value_per80(rt, weights, {}) - repl
        out.append({"label": label, "n": a["n"], "min": int(a["min"]), **{k: r1(rt.get(k), 3) for k in SPLIT_KEYS}})
    return out


def board_payload(S, ana) -> dict:
    """The Scouting Room's board: every player with minutes in the current window, column-oriented."""
    cols = ["id", "n", "team", "pos", "grp", "age", "gp", "min", "q", "tier", "last"] + AN.PM_IDS + ["p_" + k for k in AN.PM_IDS]
    rows = []
    for aid, rec in ana["players"].items():
        cur = rec.get("cur")
        if not cur or cur["agg"]["min"] < 40:
            continue
        a = S.athletes.get(aid) or {}
        team = Counter(g["team"] for g in ana["games"][aid] if g["date"] >= ana["cur_from"]).most_common(1)
        row = [aid, a.get("name") or aid, team[0][0] if team else None, rec.get("pos"), rec.get("grp"), AN.age_on(a.get("dob"), S.today),
               cur["agg"]["n"], int(cur["agg"]["min"]), 1 if cur.get("qual") else 0,
               (S.teams.get(team[0][0]) or {}).get("tier") if team else None, rec["career"]["last"]]
        row += [r1(cur["rates"].get(k), 3) for k in AN.PM_IDS]
        row += [(cur.get("pct") or {}).get(k) for k in AN.PM_IDS]
        rows.append(row)
    return {"ok": True, "asof": S.today, "from": ana["cur_from"], "cols": cols, "rows": rows,
            "metrics": [{"id": i, "label": l, "short": s, "dir": d, "family": f} for i, l, s, d, f in AN.PLAYER_METRICS],
            "groups": [{"id": g, "label": PL.GROUP_NAME[g], "n": ana["n_cur"].get(g, 0),
                        "pos": [p for p, gg in PL.POS_GROUP.items() if gg == g]} for g in PL.GROUP_ORDER],
            "min_q": PL.QUAL_MIN["season"], "repl": {k: r1(v, 3) for k, v in ana["repl"].items()}}


# ── model, lab, records ───────────────────────────────────────────────────────────────────────────────────

def model_payload(S, w, rep, flog) -> dict:
    R = S.report or {}
    rows = []
    for m in S.finals:
        f = w["fc"].get(m["id"])
        if f:
            rows.append({"y": int(m["date"][:4]), "p": (f["p_home"], f["p_draw"], f["p_away"]), "o": models.outcome(m)})
    yrs = sorted({r["y"] for r in rows})
    by_year = []
    for y in yrs:
        s = models.score([dict(r, id=i) for i, r in enumerate(rows) if r["y"] == y], y, y)
        by_year.append({"y": y, "n": s["n"], "logloss": s["logloss"], "brier": s["brier"]})
    cal = models.calibration([dict(r, id=i) for i, r in enumerate(rows)], models.TEST_FROM, 2100)
    entries = sorted(flog.get("rows", {}).items(), key=lambda kv: kv[1]["date"], reverse=True)
    log = [dict(id=k, **v) for k, v in entries[:200]]
    done = [x for x in log if "hs" in x]
    rec = None
    if done:
        won = sum(1 for x in done if (x["hs"] > x["as"] and x["p"][0] >= x["p"][2]) or (x["as"] > x["hs"] and x["p"][2] > x["p"][0]))
        exp = sum(max(x["p"][0], x["p"][2]) for x in done)
        rec = {"n": len(done), "won": won, "expected": round(exp, 1)}
    return {"ok": True, "asof": S.today, "report": {k: R.get(k) for k in ("n", "dev", "test", "rungs", "paired", "chosen", "total", "tries", "value", "replica",
                                                                          "incumbent", "kept_in_use")},
            "params": S.fit.get("params"), "fitted_through": S.fit.get("fitted_through"), "by_year": by_year,
            "calibration": {"n": cal["n"], "bins": cal["bins"], "ece": cal["ece"], "span": f"{models.TEST_FROM} to {S.now.year}"},
            "log": log, "record": rec}


def territory_conversion(S) -> dict:
    """Since 2015: each side's territory (and possession) share in a test against the points it scored and how often it
    won, in five-point bins; and the share of the variation in points that territory explains."""
    out = {}
    for key in ("terr", "poss"):
        bins = defaultdict(lambda: [0, 0.0, 0.0])
        xs, ys = [], []
        for m in S.finals:
            if m["date"][:4] < "2015" or not m.get("hstat") or not m.get("astat"):
                continue
            for side, pf, pa in (("hstat", m["hs"], m["as"]), ("astat", m["as"], m["hs"])):
                v = (m.get(side) or {}).get(key)
                if not isinstance(v, (int, float)) or not 0.2 <= v <= 0.8:
                    continue
                b = int(round(v * 100 / 5.0) * 5)
                x = bins[b]
                x[0] += 1
                x[1] += pf
                x[2] += 1.0 if pf > pa else (0.5 if pf == pa else 0.0)
                xs.append(v)
                ys.append(pf)
        n = len(xs)
        r = None
        if n > 20:
            mx, my = sum(xs) / n, sum(ys) / n
            sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
            sxx = sum((a - mx) ** 2 for a in xs)
            syy = sum((b - my) ** 2 for b in ys)
            r = sxy / math.sqrt(sxx * syy) if sxx and syy else None
        out[key] = {"bins": [[b, x[0], round(x[1] / x[0], 2), round(x[2] / x[0], 3)] for b, x in sorted(bins.items()) if x[0] >= 8],
                    "n": n, "r2": None if r is None else round(r * r, 3)}
    return out


def setpiece_years(S) -> list:
    """League-wide set piece and breakdown by year (tests with team statistics): scrum, lineout and ruck success,
    lineout steals, turnovers won and penalties a test."""
    by = defaultdict(lambda: defaultdict(float))
    for m in S.finals:
        for side in ("hstat", "astat"):
            st = m.get(side) or {}
            if not st:
                continue
            y = by[int(m["date"][:4])]
            y["n"] += 1
            for k in ("scrums_won", "scrums", "lineouts_won", "lineouts", "rucks_won", "rucks", "lineout_steals", "to_won", "pens"):
                v = st.get(k)
                if isinstance(v, (int, float)):
                    y[k] += v
                    y["n_" + k] += 1          # sides that carry the stat (the early feed has only some)
    out = []
    for yr in sorted(by):
        y = by[yr]
        if y["n"] < 20:
            continue
        sh = lambda a, b: round(y[a] / y[b], 4) if y[b] and y["n_" + b] >= 20 else None
        per = lambda a: round(y[a] / y["n_" + a], 2) if y["n_" + a] >= 20 else None
        out.append({"y": yr, "n": int(y["n"] / 2), "scrum": sh("scrums_won", "scrums"), "lineout": sh("lineouts_won", "lineouts"),
                    "ruck": sh("rucks_won", "rucks"), "steals": per("lineout_steals"), "to_won": per("to_won"), "pens": per("pens")})
    return out


def position_profile(ana) -> list:
    """Discipline, tackling and work by position group: the middle half (25th to 75th percentile) and the median of
    the regulars' shrunk per-80 rates over the current window."""
    keys = [("pc", "Penalties conceded per 80"), ("cards", "Cards per 80"), ("tkpct", "Tackle success"), ("mt", "Missed tackles per 80"),
            ("inv", "Involvements per 80"), ("ko", "Knock-ons per 80")]
    out = []
    for g in PL.GROUP_ORDER:
        vals = defaultdict(list)
        for rec in ana["players"].values():
            cur = rec.get("cur") or {}
            if rec.get("grp") != g or not cur.get("qual"):
                continue
            for k, _l in keys:
                v = cur["rates"].get(k)
                if v is not None:
                    vals[k].append(v)
        row = {"grp": g, "label": PL.GROUP_NAME[g], "n": len(vals.get("pc", []))}
        for k, _l in keys:
            v = sorted(vals.get(k, []))
            if len(v) >= 8:
                q = lambda f: v[int(f * (len(v) - 1))]
                row[k] = [round(q(0.25), 3), round(q(0.5), 3), round(q(0.75), 3)]
        out.append(row)
    return out


def lab_payload(S, w, ana=None) -> dict:
    """League-wide analytics: home advantage and scoring by year, the try share of points, bonus-point rates,
    the margin distribution, and the value model's weights."""
    by = defaultdict(lambda: {"n": 0, "hw": 0, "d": 0, "pts": 0, "tries": 0, "tpts": 0, "n_t": 0, "tbp": 0, "lbp": 0, "margin": 0.0, "n_home": 0})
    margins = Counter()
    for m in S.finals:
        y = int(m["date"][:4])
        b = by[y]
        b["n"] += 1
        if not m.get("neutral"):
            b["n_home"] += 1
            b["hw"] += 1 if m["hs"] > m["as"] else 0
            b["margin"] += m["hs"] - m["as"]
        b["d"] += 1 if m["hs"] == m["as"] else 0
        b["pts"] += m["hs"] + m["as"]
        th, ta = (m.get("hstat") or {}).get("tries"), (m.get("astat") or {}).get("tries")
        if th is not None and ta is not None:
            b["n_t"] += 1
            b["tries"] += th + ta
            b["tpts"] += m["hs"] + m["as"]
            b["tbp"] += (th >= 4) + (ta >= 4)
            b["lbp"] += 1 if 0 < abs(m["hs"] - m["as"]) <= 7 else 0
        if y >= 2010:
            margins[min(60, abs(m["hs"] - m["as"]))] += 1
    years = []
    for y in sorted(by):
        b = by[y]
        if b["n"] < 10:
            continue
        years.append({"y": y, "n": b["n"], "home_win": r1(b["hw"] / b["n_home"], 3) if b["n_home"] else None,
                      "home_margin": r1(b["margin"] / b["n_home"], 2) if b["n_home"] else None, "draw": r1(b["d"] / b["n"], 3),
                      "pts": r1(b["pts"] / b["n"], 1), "tries": r1(b["tries"] / b["n_t"], 2) if b["n_t"] else None,
                      "try_share": r1(5 * b["tries"] / b["tpts"], 3) if b["tpts"] else None,
                      "tbp": r1(b["tbp"] / (2 * b["n_t"]), 3) if b["n_t"] >= 10 else None, "lbp": r1(b["lbp"] / b["n_t"], 3) if b["n_t"] >= 10 else None})
    val = (S.report or {}).get("value") or {}
    return {"ok": True, "years": years, "margins": [[k, margins[k]] for k in range(0, 61)], "value": val,
            "territory": territory_conversion(S), "setpiece": setpiece_years(S), "positions": position_profile(ana) if ana else None,
            "home_adv": r1(S.p.H, 2), "travel": {"c_km": S.p.c_km, "c_tz": S.p.c_tz, "c_rest": S.p.c_rest, "c_alt": S.p.c_alt},
            "clock": X.scoring_clock(S), "ages": X.age_curve(S, ana) if ana else None, "weather": X.weather_lab(S, w)}


def records_payload(S, ana) -> dict:
    fin = S.finals
    scored = [m for m in fin if not m.get("ro")]
    big = sorted(scored, key=lambda m: -abs(m["hs"] - m["as"]))[:15]
    high = sorted(scored, key=lambda m: -(m["hs"] + m["as"]))[:15]
    def mrow(m):
        return {"id": m["id"], "date": m["date"][:10], "home": m["home"]["id"], "away": m["away"]["id"], "hs": m["hs"], "as": m["as"], "comp": m.get("comp")}
    # longest winning runs
    runs = []
    by_team = defaultdict(list)
    for m in fin:
        for side in ("home", "away"):
            tid = m[side]["id"]
            us = m["hs"] if side == "home" else m["as"]
            th = m["as"] if side == "home" else m["hs"]
            by_team[tid].append((m["date"][:10], us > th))
    for tid, lst in by_team.items():
        best, cur, start, bstart, bend = 0, 0, None, None, None
        for d, wn in lst:
            if wn:
                cur += 1
                start = start or d
                if cur > best:
                    best, bstart, bend = cur, start, d
            else:
                cur, start = 0, None
        if best >= 8:
            runs.append({"team": tid, "n": best, "from": bstart, "to": bend})
    runs.sort(key=lambda r: -r["n"])
    # players: points, tries, caps in our data
    tot = []
    for aid, rec in ana["players"].items():
        c = rec["career"]
        tot.append((aid, c["n"], int(c["sums"].get("pts", 0)), int(c["sums"].get("tries", 0)), Counter(g["team"] for g in ana["games"][aid]).most_common(1)[0][0]))
    def prow(x):
        a = S.athletes.get(x[0]) or {}
        return {"id": x[0], "n": a.get("name") or x[0], "caps": x[1], "pts": x[2], "tries": x[3], "team": x[4]}
    # single-match bests
    best_pts, best_tries = [], []
    for aid, gs in ana["games"].items():
        for g in gs:
            st = g["stats"] or {}
            if (st.get("pts") or 0) >= 25:
                best_pts.append((st["pts"], aid, g))
            if (st.get("tries") or 0) >= 3:
                best_tries.append((st["tries"], aid, g))
    def grow(x):
        v, aid, g = x
        return {"v": v, "id": aid, "n": (S.athletes.get(aid) or {}).get("name") or aid, "team": g["team"], "opp": g["opp"], "date": g["date"], "mid": g["mid"]}
    return {"ok": True, "biggest_wins": [mrow(m) for m in big], "highest_scoring": [mrow(m) for m in high],
            "win_runs": runs[:15], "most_caps": [prow(x) for x in sorted(tot, key=lambda x: -x[1])[:25]],
            "most_points": [prow(x) for x in sorted(tot, key=lambda x: -x[2])[:25]],
            "most_tries": [prow(x) for x in sorted(tot, key=lambda x: -x[3])[:25]],
            "match_points": [grow(x) for x in sorted(best_pts, key=lambda x: (-x[0], x[2]["date"]))[:15]],
            "match_tries": [grow(x) for x in sorted(best_tries, key=lambda x: (-x[0], x[2]["date"]))[:15]],
            "span": [fin[0]["date"][:10], fin[-1]["date"][:10]] if fin else None, "n": len(fin),
            "career_caps": career_caps_all(S), "n_wiki": sum(1 for m in fin if m.get("source") == "wikipedia"),
            "decades": decades(S)}


def career_caps_all(S) -> list:
    """The most-capped players of every nation (Wikipedia's all-time tables), merged, top 30."""
    rows = []
    for tid, lst in (CAPS.get("most") or {}).items():
        for r in lst:
            rows.append({"team": tid, "n": r["name"], "caps": r["caps"], "years": r.get("years") or "", "id": r.get("id")})
    rows.sort(key=lambda r: -r["caps"])
    return rows[:30]


def decades(S) -> list:
    """Tests a decade in our data, and how many came from Wikipedia rather than ESPN."""
    by = defaultdict(lambda: [0, 0])
    for m in S.finals:
        d = int(m["date"][:3]) * 10
        by[d][0] += 1
        if m.get("source") == "wikipedia":
            by[d][1] += 1
    return [[d, v[0], v[1]] for d, v in sorted(by.items())]


# ── overview ──────────────────────────────────────────────────────────────────────────────────────────────

def significance(S, m, fc, rep) -> float:
    s = COMP_TIER.get(m.get("comp"), 18)
    if m.get("note") and any(k in m["note"].lower() for k in ("final", "semi")):
        s += 20
    live = rep["live"].table()
    rk = {t: i + 1 for i, (t, _p) in enumerate(live)}
    for t in (m["home"]["id"], m["away"]["id"]):
        r = rk.get(t, 40)
        s += max(0, 12 - r) * 0.8
    if fc:
        s += 8 * (1 - abs(fc["p_home"] - fc["p_away"]))
    hrs = (datetime.fromisoformat(m["date"].replace("Z", "+00:00")) - S.now).total_seconds() / 3600
    s -= max(0.0, hrs) * 0.05
    return s


def digest(S, w) -> dict:
    """The last test window's top lines: results, our favourites' record, the upset, the biggest win, the week's
    best try scorer. The window is the last 7 days, else the last 7 days that had tests."""
    if not S.finals:
        return {}
    end = S.now.date()
    recent = [m for m in S.finals if m["date"][:10] > (end - timedelta(days=7)).isoformat()]
    label = "This week"
    if not recent:
        last = date.fromisoformat(S.finals[-1]["date"][:10])
        recent = [m for m in S.finals if m["date"][:10] > (last - timedelta(days=7)).isoformat()]
        label = "The last test weekend"
    won = exp = 0.0
    up = None
    for m in recent:
        f = w["fc"].get(m["id"])
        if not f or m["hs"] == m["as"]:
            continue
        fav_home = f["p_home"] >= f["p_away"]
        exp += max(f["p_home"], f["p_away"])
        won += 1 if (m["hs"] > m["as"]) == fav_home else 0
        wp = f["p_home"] if m["hs"] > m["as"] else f["p_away"]
        if wp < 0.4 and (up is None or wp < up["p"]):
            up = {"id": m["id"], "p": round(wp, 3), "winner": m["home" if m["hs"] > m["as"] else "away"]["id"],
                  "loser": m["away" if m["hs"] > m["as"] else "home"]["id"], "score": [max(m["hs"], m["as"]), min(m["hs"], m["as"])]}
    big = max(recent, key=lambda m: abs(m["hs"] - m["as"]))
    tries = Counter()
    for m in recent:
        for e in m.get("events") or []:
            if e[1] == "try" and e[3]:
                tries[e[3]] += 1
    tt = tries.most_common(1)
    return {"label": label, "from": recent[0]["date"][:10], "to": recent[-1]["date"][:10], "n": len(recent),
            "record": {"n": sum(1 for m in recent if m["hs"] != m["as"] and w["fc"].get(m["id"])), "won": int(won), "expected": round(exp, 1)},
            "upset": up, "biggest": {"id": big["id"], "winner": big["home" if big["hs"] >= big["as"] else "away"]["id"],
                                     "loser": big["away" if big["hs"] >= big["as"] else "home"]["id"], "score": [max(big["hs"], big["as"]), min(big["hs"], big["as"])]},
            "tries": {"id": tt[0][0], "n": (S.athletes.get(tt[0][0]) or {}).get("name") or tt[0][0], "k": tt[0][1]} if tt and tt[0][1] >= 2 else None,
            "results": [B.card(S, m, w["fc"].get(m["id"])) for m in recent[-12:]]}


def overview_payload(S, w, rep, ratings, comps_out, ana) -> dict:
    ups = [m for m in S.upcoming if m["date"] <= (S.now + timedelta(days=UPCOMING_WINDOW)).strftime("%Y-%m-%dT%H:%M")]
    if not ups:
        ups = S.upcoming[:12]
    cards = [B.card(S, m, w["up"].get(m["id"])) for m in ups[:24]]
    feat = None
    if ups:
        best = max(ups[:30], key=lambda m: significance(S, m, w["up"].get(m["id"]), rep))
        feat = B.card(S, best, w["up"].get(best["id"]))
        feat["why"] = _why(S, best, w["up"].get(best["id"]), rep)
    elif S.finals:
        feat = B.card(S, S.finals[-1], w["fc"].get(S.finals[-1]["id"]))
    # the power board ranks sides whose rating is tied to the main pool: tier one and two, or three or more tests
    # against them in four years (a side that only plays other tier-three sides has a rating on its own scale)
    power = [t for t in ratings["teams"] if t.get("rank")][:20]
    # stories: the biggest riser and faller of the last year among rated sides, the hottest run, who's for real
    act = [t for t in ratings["teams"] if t["d365"] is not None and t["n"] >= 15 and (t.get("tier") or 3) <= 2]
    up = max(act, key=lambda t: t["d365"]) if act else None
    dn = min(act, key=lambda t: t["d365"]) if act else None
    stories = []
    if up:
        stories.append({"kind": "riser", "team": up["id"], "d": up["d365"], "rating": up["rating"], "hist": up["hist"][-24:]})
    if dn:
        stories.append({"kind": "faller", "team": dn["id"], "d": dn["d365"], "rating": dn["rating"], "hist": dn["hist"][-24:]})
    runs = []
    for t in [x for x in ratings["teams"] if x.get("rank")][:30]:
        f = B.form_of(S, t["id"], n=30)
        k = len(f) - len(f.rstrip("W")) if f.endswith("W") else 0
        runs.append((k, t["id"]))
    runs.sort(reverse=True)
    if runs and runs[0][0] >= 3:
        stories.append({"kind": "run", "team": runs[0][1], "n": runs[0][0]})
    # who's for real: win share over the last two years against our rating
    real = []
    since = (S.now - timedelta(days=730)).date().isoformat()
    for t in power[:24]:
        res = [m for m in B.team_results(S, t["id"]) if m["date"][:10] >= since]
        if len(res) < 8:
            continue
        wins = sum(1 for m in res if (m["hs"] > m["as"]) == (m["home"]["id"] == t["id"]) and m["hs"] != m["as"])
        real.append({"id": t["id"], "x": t["rating"], "y": round(wins / len(res), 3), "n": len(res)})
    # players to watch: the top Scrum value per group (qualified, current window, still capped in the last year)
    stars = []
    last_year = (S.now - timedelta(days=400)).date().isoformat()
    for g in PL.GROUP_ORDER:
        cand = [(rec["cur"]["rates"]["val80"], aid) for aid, rec in ana["players"].items()
                if rec.get("grp") == g and (rec.get("cur") or {}).get("qual") and rec["career"]["last"] >= last_year]
        cand.sort(reverse=True)
        if cand:
            v, aid = cand[0]
            nxt = cand[1] if len(cand) > 1 else None
            team = Counter(x["team"] for x in ana["games"][aid]).most_common(1)[0][0]
            stars.append({"grp": g, "id": aid, "n": (S.athletes.get(aid) or {}).get("name") or aid, "team": team, "v": r1(v, 2),
                          "next": {"id": nxt[1], "n": (S.athletes.get(nxt[1]) or {}).get("name"), "v": r1(nxt[0], 2)} if nxt else None})
    races = []
    for key in ("nc", "six", "rwc", "trc"):
        c = comps_out.get(key)
        if not c:
            continue
        sim = (c.get("next") or {}).get("sim") or c.get("sim")
        if sim:
            races.append({"comp": key, "season": (c.get("next") or {}).get("season") or c.get("season"),
                          "rows": [{"team": r["team"], "p": r.get("title", r.get("champion"))} for r in sim["teams"][:8]]})
    champs = []
    ids = B.ids_by_name(S)
    six = comps_out.get("six") or {}
    if six.get("season") == S.now.year and six.get("table") and len(six.get("results") or []) == 15:
        top = six["table"][0]
        champs.append({"comp": "six", "season": six["season"], "team": ids.get(top["team"]), "decided": max(r["date"] for r in six["results"]),
                       "how": "in the Six Nations" + (" with a Grand Slam" if top.get("w") == 5 else "")})
    for m in reversed(S.finals[-60:]):
        if m.get("comp") == "nc" and "final" in str(m.get("note") or "").lower() and "place" not in str(m.get("note") or "").lower()                 and "semi" not in str(m.get("note") or "").lower() and m["hs"] != m["as"]:
            hw = m["hs"] > m["as"]
            champs.append({"comp": "nc", "season": int(m["date"][:4]), "team": m["home" if hw else "away"]["id"],
                           "opp": m["away" if hw else "home"]["id"], "decided": m["date"][:10],
                           "score": [max(m["hs"], m["as"]), min(m["hs"], m["as"])], "how": "in the Nations Championship final"})
            break
    return {"ok": True, "asof": S.now.strftime("%Y-%m-%dT%H:%MZ"), "digest": digest(S, w), "featured": feat, "champions": champs,
            "upcoming": cards, "power": [{k: t.get(k) for k in ("id", "rating", "att", "dfn", "rank", "d30", "d365", "form", "wr", "wr_rank", "rec12")} for t in power],
            "stories": stories, "real": real, "stars": stars, "races": races,
            "counts": {"matches": len(S.finals), "teams": len(S.teams), "players": len(ana["players"]),
                       "from": S.finals[0]["date"][:4] if S.finals else None}}


UPCOMING_WINDOW = 21


def _why(S, m, fc, rep) -> str:
    if not fc:
        return ""
    h, a = S.name(m["home"]["id"]), S.name(m["away"]["id"])
    fav, p = (h, fc["p_home"]) if fc["p_home"] >= fc["p_away"] else (a, fc["p_away"])
    comp = COMP_NAME.get(m.get("comp"), "Test")
    if p < 0.58:
        return f"{comp}: as close as tests get. We have {fav} at {round(p * 100)}%."
    return f"{comp}: {fav} by about {abs(round(fc['margin']))} in our numbers, a {round(p * 100)}% chance."


# ── search and index pieces ───────────────────────────────────────────────────────────────────────────────

def search_rows(S, ana) -> list:
    out = []
    cut = (S.now - timedelta(days=6 * 365)).date().isoformat()
    for tid, t in S.teams.items():
        if not any(m["date"][:10] >= cut for m in B.team_results(S, tid)):
            continue
        out.append({"t": t["name"], "s": ("Men's" if S.scope == "men" else "Women's") + " national team", "href": f"#/{S.scope}/team/{tid}",
                    "w": 3 if t.get("tier") == 1 else (2 if t.get("tier") == 2 else 1)})
    for aid, rec in ana["players"].items():
        if rec["career"]["last"] < cut:
            continue
        a = S.athletes.get(aid) or {}
        team = Counter(g["team"] for g in ana["games"][aid]).most_common(1)[0][0]
        out.append({"t": a.get("name") or aid, "s": (PL.POS_NAME.get(rec.get("pos") or "", "Player")) + " · " + S.name(team),
                    "href": f"#/{S.scope}/player/{aid}", "w": 1 if rec["career"]["n"] >= 20 else 0})
    return out


# ── the scope ─────────────────────────────────────────────────────────────────────────────────────────────

def build_scope(scope: str, data_root: Path, sims: int = 20000, now: datetime | None = None, game_pages: bool = True) -> dict:
    now = now or B.now_utc()
    S = B.Scope(scope, now)
    if not S.finals:
        B.write(data_root / scope / "overview.json", {"ok": False, "reason": "no matches in the store yet"})
        return {"ok": False, "reason": "no matches"}
    data = data_root / scope
    w = B.walk(S)
    rep = B.replica(S)
    # the exchange of each match in the replica (burn-in before the anchor, live after)
    ex = {}
    # rebuild a match-id keyed exchange from the burn-in replica (date-ordered like S.finals)
    rk = rankings.Ranker(default=lambda t, d: {1: 78.0, 2: 66.0, 3: 52.0}[nations.tier(S.name(t))])
    for m in S.finals:
        h, a = m["home"]["id"], m["away"]["id"]
        if nations.invitational(m["home"]["name"]) or nations.invitational(m["away"]["name"]) or int(m["date"][:4]) < models.REPLICA_FROM:
            continue
        if rep["source"] == "anchored" and m["date"][:10] > validate.PUBLISHED_DATE:
            break
        ra, rb = rk.get(h, m["date"]), rk.get(a, m["date"])
        x = rk.update(h, a, m["hs"], m["as"], m["date"], neutral=bool(m.get("neutral")), world_cup=m.get("comp") in ("rwc", "wrwc"))
        ex[m["id"]] = {"before": [round(ra, 2), round(rb, 2)], "x": round(x, 2), "src": "rebuilt"}
    if rep["source"] == "anchored":
        # the live table's matches with their before values
        live_hist = rep["live"].history
        for (d, h, ph, a, pa, x), m in zip(live_hist, [m for m in S.finals if m["date"][:10] > validate.PUBLISHED_DATE
                                                        and not nations.invitational(m["home"]["name"]) and not nations.invitational(m["away"]["name"])]):
            ex[m["id"]] = {"before": [round(ph - x, 2), round(pa + x, 2)], "x": round(x, 2), "src": "anchored"}
    rep["exchange"] = ex
    ana = AN.player_tables(S.finals, S.athletes, S.today, S.fit.get("value"))
    prof = AN.team_profiles(S.finals, S.today)
    CAPS.clear()
    CAPS.update(X.caps_tables(S, ana))
    PHYS.clear()
    PHYS.update(X.physical(S, ana))
    comps_out = B.comp_payloads(S, w, rep, sims)
    rk_pay = rankings_payload(S, w, rep)
    rep["wr_rank"] = {r["id"]: r["rank"] for r in rk_pay["table"]}
    ratings = ratings_payload(S, w, rep, rep["wr_rank"])
    flog = forecast_log(S, w)
    sizes = Counter()
    sizes["ratings"] += B.write(data / "ratings.json", ratings)
    sizes["rankings"] += B.write(data / "rankings.json", rk_pay)
    sizes["overview"] += B.write(data / "overview.json", overview_payload(S, w, rep, ratings, comps_out, ana))
    fx = {"ok": True, "asof": S.today, "upcoming": [B.card(S, m, w["up"].get(m["id"])) for m in S.upcoming[:200]],
          "results": [B.card(S, m, w["fc"].get(m["id"])) for m in S.finals[-B.RECENT_RESULTS:]][::-1],
          "live": [B.card(S, m, w["up"].get(m["id"])) for m in S.live]}
    sizes["fixtures"] += B.write(data / "fixtures.json", fx)
    yp = year_payloads(S, w, data)
    for key, c in comps_out.items():
        sizes["comps"] += B.write(data / "comps" / f"{key}.json", dict(ok=True, **c))
    GRADES[S.scope] = grade_table(S, ana, ratings)
    sizes["teams"] += B.write(data / "teams.json", teams_payload(S, w, rep, prof, ratings))
    cut = (S.now - timedelta(days=10 * 365)).date().isoformat()
    team_ids = [t for t in S.teams if any(m["date"][:10] >= cut for m in B.team_results(S, t))]
    for tid in team_ids:
        sizes["team_pages"] += B.write(data / "teams" / f"{tid}.json", team_page(S, w, rep, ana, prof, tid, comps_out, ratings))
    for aid in ana["players"]:
        sizes["player_pages"] += B.write(data / "players" / f"{aid}.json", player_page(S, ana, aid, w))
    sizes["board"] += B.write(data / "players.json", board_payload(S, ana))
    sizes["progression_ref"] += B.write(data / "progression_ref.json", progression_ref(S, ana))
    if game_pages:
        gi = GoingIn(S, w, rep)
        for m in S.finals + S.upcoming + S.live:
            if m["status"] == "final" and not (m.get("hstat") or m.get("lh") or m.get("events")) and m["date"][:4] < "2004":
                pass
            sizes["match_pages"] += B.write(data / "matches" / f"{m['id']}.json", match_page(S, w, rep, m, ana, gi))
    sizes["model"] += B.write(data / "model.json", model_payload(S, w, rep, flog))
    sizes["lab"] += B.write(data / "lab.json", lab_payload(S, w, ana))
    sizes["records"] += B.write(data / "records.json", records_payload(S, ana))
    sizes["referees"] += B.write(data / "referees.json", X.referees_payload(S, w))
    info = {"ok": True, "label": config.SCOPES[scope]["label"], "short": config.SCOPES[scope]["short"],
            "teams": {tid: dict(S.teams[tid], **({"active": 1} if tid in set(team_ids) else {})) for tid in S.teams}, "years": yp["years"], "latest": S.finals[-1]["date"][:10],
            "next": S.upcoming[0]["date"] if S.upcoming else None, "comps": sorted(comps_out),
            "n_matches": len(S.finals), "n_players": len(ana["players"]), "first": S.finals[0]["date"][:10],
            "merge": store.MERGE_REPORT.get(scope), "caps": {k: CAPS.get(k) for k in ("matched", "rows")},
            # a second id a side once had (store.unify_ids): an old team link resolves to the id kept
            "alias": dict(store.ID_ALIAS.get(scope) or {})}
    return {"ok": True, "info": info, "sizes": dict(sizes), "search": search_rows(S, ana), "S": S, "w": w, "rep": rep,
            "ana": ana, "prof": prof, "comps": comps_out, "ratings": ratings}
