"""
The Quant Scrum's second-wave payload pieces (2 Nov 2026): referees, match weather and venue elevation, the scoring
clock, the age curve, physical profiles and career caps. Sources: ESPN (bios from the core API), Wikipedia (referees,
attendances, historic results, squads and caps; CC BY-SA 4.0) and Open-Meteo (weather and elevation; CC BY 4.0).
Each piece degrades to nothing when its source is switched off (SOURCE_WIKIPEDIA_RUGBY_ENABLED,
SOURCE_OPENMETEO_RUGBY_ENABLED).

No look-ahead: realised weather is shown on finished tests and in the Lab only; upcoming tests show the forecast as
issued. Referee tendencies count finished tests only.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import build as B, nations, players as PL, store

r1 = B.r1
ALT_M = nations.ALT_M      # a venue this high or higher is "at altitude" (Johannesburg 1,750 m, Pretoria 1,340 m)
ALT_HOME = nations.ALT_HOME


# ── names ────────────────────────────────────────────────────────────────────────────────────────────────────

def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^a-z ]+", "", s.replace("-", " ")).strip()


def name_index(S, ana) -> dict:
    """{team id: {folded full name: aid, ('last', initial): [aid, ...]}} over every player capped for the side."""
    idx: dict = defaultdict(lambda: {"full": {}, "li": defaultdict(list), "last": defaultdict(list)})
    for aid, gs in ana["games"].items():
        teams = {g["team"] for g in gs}
        nm = fold((S.athletes.get(aid) or {}).get("name") or "")
        if not nm:
            continue
        parts = nm.split()
        for t in teams:
            d = idx[t]
            d["full"].setdefault(nm, aid)
            if len(parts) >= 2:
                d["li"][(parts[-1], parts[0][0])].append(aid)
                d["last"][parts[-1]].append(aid)
    return idx


def match_name(idx_team: dict, name: str) -> str | None:
    nm = fold(name)
    if not nm or not idx_team:
        return None
    if nm in idx_team["full"]:
        return idx_team["full"][nm]
    parts = nm.split()
    if len(parts) >= 2:
        c = list(dict.fromkeys(idx_team["li"].get((parts[-1], parts[0][0])) or []))
        if len(c) == 1:
            return c[0]
        # two-word surnames ("de Klerk", "van der Merwe"): match the last two or three words
        for k in (2, 3):
            if len(parts) > k:
                tail = " ".join(parts[-k:])
                hits = [a for f, a in idx_team["full"].items() if f.endswith(" " + tail) and f.split()[0][0] == parts[0][0]]
                if len(set(hits)) == 1:
                    return hits[0]
    return None


# ── career caps (Wikipedia squads and all-time tables) ──────────────────────────────────────────────────────

def caps_tables(S, ana) -> dict:
    """{"by_aid": {aid: {"caps", "asof"}}, "most": {team id: [{name, caps, years, id}]}, "matched", "rows"}: the current
    squad's career caps and the all-time most-capped table from each national team's Wikipedia article, the players
    matched by name to the side's players in our data."""
    from . import wiki
    if not wiki.enabled():
        return {"by_aid": {}, "most": {}, "matched": 0, "rows": 0}
    W = wiki.load(S.scope) or {}
    sq = W.get("squads") or {}
    built = str(W.get("built") or "")[:10]
    ids = {}
    for tid, t in S.teams.items():
        ids.setdefault(nations.base_name(t["name"]), tid)
    idx = name_index(S, ana)
    by_aid, most, matched, rows = {}, {}, 0, 0
    for team_name, tabs in sq.items():
        tid = ids.get(nations.base_name(nations.canonical(team_name.replace(" Women", ""))))
        if not tid:
            continue
        it = idx.get(tid)
        for r in tabs.get("current") or []:
            rows += 1
            aid = match_name(it, r["name"]) if it else None
            if aid:
                matched += 1
                cur = by_aid.get(aid)
                if not cur or r["caps"] > cur["caps"]:
                    by_aid[aid] = {"caps": r["caps"], "asof": built}
                if r.get("dob") and not (S.athletes.get(aid) or {}).get("dob"):
                    S.athletes.setdefault(aid, {})["dob"] = r["dob"]
        seen = set()
        lst = []
        for r in sorted(tabs.get("most_caps") or [], key=lambda x: -x["caps"]):
            k = fold(r["name"])
            if k in seen:
                continue
            seen.add(k)
            aid = match_name(it, r["name"]) if it else None
            lst.append({"name": r["name"], "caps": r["caps"], "years": r.get("years") or "", "id": aid})
            if aid:
                cur = by_aid.get(aid)
                if not cur or r["caps"] > cur["caps"]:
                    by_aid[aid] = {"caps": r["caps"], "asof": built}
        if lst:
            most[tid] = lst[:15]
    return {"by_aid": by_aid, "most": most, "matched": matched, "rows": rows}


# ── physical profile ──────────────────────────────────────────────────────────────────────────────────────────

def physical(S, ana) -> dict:
    """Height and weight percentiles within each position group, among players capped in the last four years with a
    bio: {aid: {"ht_pct", "wt_pct"}}, plus each group's median."""
    since = (S.now - timedelta(days=4 * 365)).date().isoformat()
    vals = defaultdict(lambda: {"ht": [], "wt": []})
    who = {}
    for aid, rec in ana["players"].items():
        g = rec.get("grp")
        a = S.athletes.get(aid) or {}
        if not g or rec["career"]["last"] < since:
            continue
        ht, wt = a.get("ht_cm"), a.get("wt_kg")
        if isinstance(ht, (int, float)) and 155 <= ht <= 215:
            vals[g]["ht"].append(ht)
        if isinstance(wt, (int, float)) and 60 <= wt <= 160:
            vals[g]["wt"].append(wt)
        who[aid] = g
    for g in vals.values():
        g["ht"].sort()
        g["wt"].sort()

    def pct(lst, v):
        if not lst or not isinstance(v, (int, float)):
            return None
        lo = sum(1 for x in lst if x < v)
        eq = sum(1 for x in lst if x == v)
        return round(100.0 * (lo + 0.5 * eq) / len(lst))
    out = {}
    for aid, g in who.items():
        a = S.athletes.get(aid) or {}
        out[aid] = {"ht_pct": pct(vals[g]["ht"], a.get("ht_cm")), "wt_pct": pct(vals[g]["wt"], a.get("wt_kg"))}
    med = {g: {"ht": v["ht"][len(v["ht"]) // 2] if v["ht"] else None, "wt": v["wt"][len(v["wt"]) // 2] if v["wt"] else None,
               "n": len(v["ht"])} for g, v in vals.items()}
    return {"by_aid": out, "median": med}


# ── weather and venues ────────────────────────────────────────────────────────────────────────────────────────

def venue_key(m: dict) -> str:
    v = m.get("venue") or {}
    return f"{(v.get('name') or '').strip()}|{(v.get('city') or '').strip()}"


def venue_of(m: dict) -> dict | None:
    from .sources import weather as WX
    if not WX.enabled():
        return None
    v = store.stores_extra("venues", "venues").get(venue_key(m))
    return v or None


def weather_of(m: dict) -> dict | None:
    from .sources import weather as WX
    if not WX.enabled():
        return None
    return store.stores_extra("weather").get(m["id"])


def elev_of(m: dict) -> float | None:
    v = venue_of(m)
    e = (v or {}).get("elev")
    return float(e) if isinstance(e, (int, float)) else None


def at_altitude(m: dict) -> int:
    """1 when a home side plays at a venue 1,000 m up against a side from lower down (the Highveld effect)."""
    from .sources import weather as WX
    if not WX.enabled():
        return 0
    if (m.get("venue") or {}).get("elev") is None:
        e = elev_of(m)
        if e is not None:
            m.setdefault("venue", {})["elev"] = round(e)
    return nations.altitude_edge(m)


# ── referees ─────────────────────────────────────────────────────────────────────────────────────────────────

def _cards(m: dict, side: str) -> tuple[int | None, int | None]:
    st = m.get(side + "stat") or {}
    if isinstance(st.get("yc"), (int, float)):
        return int(st.get("yc") or 0), int(st.get("rc") or 0)
    if m.get("events"):
        k = "h" if side == "h" else "a"
        return (sum(1 for e in m["events"] if e[1] == "yc" and e[2] == k), sum(1 for e in m["events"] if e[1] == "rc" and e[2] == k))
    return None, None


def referees_payload(S, w) -> dict:
    """Every referee with five or more of our tests: tests, span, the home side's results against our pre-match
    chances, penalties and cards a test (where the feed has team statistics or the cards in the key moments), the
    home side's share of the penalties, points and tries a test, and their next appointments."""
    from . import wiki
    if not wiki.enabled():
        return {"ok": True, "refs": [], "upcoming": [], "n": 0, "disabled": 1}
    agg = defaultdict(lambda: defaultdict(float))
    meta = {}
    for m in S.finals:
        rf = m.get("referee") or {}
        nm = rf.get("name")
        if not nm or m.get("ro"):
            continue
        k = fold(nm)
        a = agg[k]
        mt = meta.setdefault(k, {"name": nm, "union": rf.get("union") or "", "first": m["date"][:10], "last": m["date"][:10],
                                 "comps": Counter(), "teams": Counter(), "recent": []})
        mt["last"] = m["date"][:10]
        mt["comps"][m.get("comp") or "test"] += 1
        a["n"] += 1
        a["pts"] += m["hs"] + m["as"]
        if not m.get("neutral"):
            a["n_home"] += 1
            a["hw"] += 1.0 if m["hs"] > m["as"] else (0.5 if m["hs"] == m["as"] else 0.0)
            f = w["fc"].get(m["id"])
            if f:
                a["n_exp"] += 1
                a["hw_x"] += 1.0 if m["hs"] > m["as"] else (0.5 if m["hs"] == m["as"] else 0.0)
                a["exp"] += f["p_home"] + 0.5 * f["p_draw"]
        hst, ast = m.get("hstat") or {}, m.get("astat") or {}
        if isinstance(hst.get("pens"), (int, float)) and isinstance(ast.get("pens"), (int, float)):
            a["n_pen"] += 1
            a["pens"] += hst["pens"] + ast["pens"]
            if not m.get("neutral"):
                a["n_pen_home"] += 1
                a["pens_home"] += hst["pens"]
                a["pens_both_home"] += hst["pens"] + ast["pens"]
        yh, rh = _cards(m, "h")
        ya, ra = _cards(m, "a")
        if yh is not None and ya is not None:
            a["n_card"] += 1
            a["yc"] += yh + ya
            a["rc"] += rh + ra
        if isinstance(hst.get("tries"), (int, float)) and isinstance(ast.get("tries"), (int, float)):
            a["n_try"] += 1
            a["tries"] += hst["tries"] + ast["tries"]
        mt["recent"].append(m["id"])
        for s in ("home", "away"):
            mt["teams"][m[s]["id"]] += 1
    # the field's averages (every refereed test with the stat), for the comparisons
    tot = defaultdict(float)
    for a in agg.values():
        for k, v in a.items():
            tot[k] += v
    field = {"pens": r1(tot["pens"] / tot["n_pen"], 2) if tot["n_pen"] else None,
             "yc": r1(tot["yc"] / tot["n_card"], 2) if tot["n_card"] else None,
             "rc": r1(tot["rc"] / tot["n_card"], 3) if tot["n_card"] else None,
             "home_pen_share": r1(tot["pens_home"] / tot["pens_both_home"], 3) if tot["pens_both_home"] else None,
             "pts": r1(tot["pts"] / tot["n"], 1) if tot["n"] else None,
             "home_vs_exp": r1((tot["hw_x"] - tot["exp"]) / tot["n_exp"], 3) if tot["n_exp"] else None}
    refs = []
    for k, a in agg.items():
        if a["n"] < 5:
            continue
        mt = meta[k]
        refs.append({"k": k, "name": mt["name"], "union": mt["union"], "n": int(a["n"]), "first": mt["first"], "last": mt["last"],
                     "home_win": r1(a["hw"] / a["n_home"], 3) if a["n_home"] else None, "n_home": int(a["n_home"]),
                     "home_vs_exp": r1((a["hw_x"] - a["exp"]) / a["n_exp"], 3) if a["n_exp"] >= 5 else None, "n_exp": int(a["n_exp"]),
                     "pens": r1(a["pens"] / a["n_pen"], 2) if a["n_pen"] >= 5 else None, "n_pen": int(a["n_pen"]),
                     "home_pen_share": r1(a["pens_home"] / a["pens_both_home"], 3) if a["n_pen_home"] >= 5 and a["pens_both_home"] else None,
                     "yc": r1(a["yc"] / a["n_card"], 2) if a["n_card"] >= 5 else None, "rc": r1(a["rc"] / a["n_card"], 3) if a["n_card"] >= 5 else None,
                     "n_card": int(a["n_card"]), "pts": r1(a["pts"] / a["n"], 1), "tries": r1(a["tries"] / a["n_try"], 2) if a["n_try"] >= 5 else None,
                     "comps": dict(mt["comps"].most_common(4)), "recent": mt["recent"][-8:][::-1],
                     "teams": [t for t, _n in mt["teams"].most_common(5)]})
    refs.sort(key=lambda r: (-r["n"], r["name"]))
    up = []
    for m in S.upcoming:
        rf = m.get("referee") or {}
        if rf.get("name"):
            up.append({"id": m["id"], "date": m["date"], "home": m["home"]["id"], "away": m["away"]["id"], "comp": m.get("comp"),
                       "ref": rf["name"], "union": rf.get("union") or "", "k": fold(rf["name"])})
    n_ref = sum(1 for m in S.finals if (m.get("referee") or {}).get("name"))
    return {"ok": True, "asof": S.today, "refs": refs, "upcoming": up[:24], "field": field, "n": n_ref,
            "since": min((r["first"] for r in refs), default=None), "min_tests": 5}


# ── the Lab's new sections ────────────────────────────────────────────────────────────────────────────────────

def scoring_clock(S) -> dict:
    """Points and tries by ten-minute band (from the key moments: tests since 2006 with a full scoring record), the
    minute of the first try, and how often the side leading at half-time wins."""
    bands = defaultdict(lambda: {"pts": 0, "tries": 0, "pens": 0, "cards": 0})
    n = 0
    first_try = Counter()
    ht_lead = {"n": 0, "won": 0, "drew": 0}
    pts_v = {"try": 5, "con": 2, "pg": 3, "dg": 3}
    for m in S.finals:
        ev = [e for e in m.get("events") or [] if isinstance(e[0], (int, float))]
        sc = [e for e in ev if e[1] in pts_v]
        if len(sc) < 2:
            continue
        got = sum(pts_v[e[1]] for e in sc)
        if abs(got - (m["hs"] + m["as"])) > 2:          # a partial scoring record: left out
            continue
        n += 1
        ft = None
        for e in ev:
            b = min(7, max(0, (int(e[0]) - 1) // 10))
            if e[1] in pts_v:
                bands[b]["pts"] += pts_v[e[1]]
                if e[1] == "try":
                    bands[b]["tries"] += 1
                    ft = e[0] if ft is None else ft
                if e[1] == "pg":
                    bands[b]["pens"] += 1
            elif e[1] in ("yc", "rc"):
                bands[b]["cards"] += 1
        if ft is not None:
            first_try[min(80, int(ft)) // 5 * 5] += 1
        first = [e for e in sc if e[0] <= 40]
        if first:
            hh, aa = first[-1][5], first[-1][6]
            if hh is not None and aa is not None and hh != aa:
                ht_lead["n"] += 1
                lead_home = hh > aa
                if m["hs"] == m["as"]:
                    ht_lead["drew"] += 1
                elif (m["hs"] > m["as"]) == lead_home:
                    ht_lead["won"] += 1
    rows = [{"band": f"{10 * b + 1}-{10 * b + 10}" if b < 7 else "71-80+", "pts": r1(bands[b]["pts"] / n, 2) if n else None,
             "tries": r1(bands[b]["tries"] / n, 3) if n else None, "pens": r1(bands[b]["pens"] / n, 3) if n else None,
             "cards": r1(bands[b]["cards"] / n, 3) if n else None} for b in range(8)]
    return {"n": n, "bands": rows, "first_try": [[k, first_try[k]] for k in sorted(first_try)],
            "ht_lead": {"n": ht_lead["n"], "won": r1(ht_lead["won"] / ht_lead["n"], 3) if ht_lead["n"] else None,
                        "drew": r1(ht_lead["drew"] / ht_lead["n"], 3) if ht_lead["n"] else None}}


def age_curve(S, ana) -> dict:
    """Scrum value per 80 by age (each qualified player-season since 2006, the age at 1 July of that year), overall and
    for forwards and backs: the mean, and the share of a group's minutes by age."""
    by = defaultdict(lambda: {"n": 0, "v": 0.0, "min": 0.0, "fwd_n": 0, "fwd_v": 0.0, "back_n": 0, "back_v": 0.0})
    tot_min = 0.0
    for aid, rec in ana["players"].items():
        dob = (S.athletes.get(aid) or {}).get("dob")
        g = rec.get("grp")
        if not dob or not g:
            continue
        for y, s in rec["seasons"].items():
            if not s.get("qual") or "val80" not in s["rates"]:
                continue
            try:
                age = (date(int(y), 7, 1) - date.fromisoformat(dob[:10])).days / 365.25
            except ValueError:
                continue
            if not 18 <= age < 40:
                continue
            b = by[int(age)]
            v = s["rates"]["val80"]
            b["n"] += 1
            b["v"] += v
            b["min"] += s["agg"]["min"]
            tot_min += s["agg"]["min"]
            fw = g in ("front_row", "lock", "back_row")
            b["fwd_n" if fw else "back_n"] += 1
            b["fwd_v" if fw else "back_v"] += v
    # the within-player curve (the delta method): the average change in a player's value from one qualified year to
    # the next, by his age in the first, chained into a curve. The cross-section above is shaped by selection (only good
    # young players are capped, only good old ones stay); following the same players removes most of that
    dlt = defaultdict(lambda: [0, 0.0])
    for aid, rec in ana["players"].items():
        dob = (S.athletes.get(aid) or {}).get("dob")
        if not dob:
            continue
        ss = {int(y): s for y, s in rec["seasons"].items() if s.get("qual") and "val80" in s["rates"]}
        for y, s in ss.items():
            nx = ss.get(y + 1)
            if not nx:
                continue
            try:
                age = int((date(y, 7, 1) - date.fromisoformat(dob[:10])).days / 365.25)
            except ValueError:
                continue
            if 18 <= age < 39:
                w = min(s["agg"]["min"], nx["agg"]["min"])
                dlt[age][0] += w
                dlt[age][1] += w * (nx["rates"]["val80"] - s["rates"]["val80"])
    rows = []
    for a in sorted(by):
        b = by[a]
        if b["n"] < 8:
            continue
        rows.append({"age": a, "n": b["n"], "v": r1(b["v"] / b["n"], 3), "share": r1(b["min"] / tot_min, 4) if tot_min else None,
                     "fwd": r1(b["fwd_v"] / b["fwd_n"], 3) if b["fwd_n"] >= 6 else None,
                     "back": r1(b["back_v"] / b["back_n"], 3) if b["back_n"] >= 6 else None})
    ages = [r["age"] for r in rows]
    # chained only over ages with 4,000 minutes of pairs or more (about 25 player pairs); the chain stops at a gap
    cum, chain = 0.0, {}
    for a in ages:
        if a < 20 or a > 35:
            continue
        chain[a] = cum
        d = dlt.get(a)
        if not d or d[0] < 4000:
            break
        cum += d[1] / d[0]
    if chain:
        top = max(chain.values())
        for r in rows:
            r["within"] = r1(chain[r["age"]] - top, 3) if r["age"] in chain else None
    peak = max(rows, key=lambda r: r["v"])["age"] if rows else None
    peak_w = max(rows, key=lambda r: r["within"] if r.get("within") is not None else -99)["age"] if chain else None
    return {"rows": rows, "peak": peak, "peak_within": peak_w, "n": sum(r["n"] for r in rows),
            "pairs": int(sum(v[0] for v in dlt.values()) / 80)}


def weather_lab(S, w) -> dict:
    """Realised weather against the result (finished tests with weather; descriptive, never a model input): points a
    test by rain and by wind, goal-kicking success by wind, our margin error by rain, and home sides at altitude."""
    from .sources import weather as WX
    if not WX.enabled():
        return {}
    rain_b = [(0.0, 0.1, "Dry"), (0.1, 1.0, "Light (under 1 mm)"), (1.0, 3.0, "Wet (1-3 mm)"), (3.0, 999, "Heavy (3 mm+)")]
    wind_b = [(0, 15, "Under 15 km/h"), (15, 25, "15-25"), (25, 35, "25-35"), (35, 999, "35 km/h +")]
    rr = defaultdict(lambda: defaultdict(float))
    ww = defaultdict(lambda: defaultdict(float))
    n = 0
    for m in S.finals:
        if m["date"][:4] < "1987" or m.get("ro"):
            continue
        wx = weather_of(m)
        if not wx or wx.get("kind") != "era5":
            continue
        n += 1
        f = w["fc"].get(m["id"]) or {}
        tot = m["hs"] + m["as"]
        rain, wind = wx.get("rain"), wx.get("wind")
        if isinstance(rain, (int, float)):
            lab = next(l for lo, hi, l in rain_b if lo <= rain < hi)
            b = rr[lab]
            b["n"] += 1
            b["pts"] += tot
            if f.get("total") is not None:
                b["n_t"] += 1
                b["terr"] += tot - f["total"]
        if isinstance(wind, (int, float)):
            lab = next(l for lo, hi, l in wind_b if lo <= wind < hi)
            b = ww[lab]
            b["n"] += 1
            b["pts"] += tot
            for side in ("hstat", "astat"):
                st = m.get(side) or {}
                made = (st.get("cons") or 0) + (st.get("pen_goals") or 0)
                miss = (st.get("cons_missed") or 0) + (st.get("pen_goals_missed") or 0)
                if isinstance(st.get("cons"), (int, float)) and made + miss > 0:
                    b["k_made"] += made
                    b["k_att"] += made + miss
    rain = [{"band": l, "n": int(rr[l]["n"]), "pts": r1(rr[l]["pts"] / rr[l]["n"], 1) if rr[l]["n"] else None,
             "vs_exp": r1(rr[l]["terr"] / rr[l]["n_t"], 2) if rr[l]["n_t"] >= 10 else None} for _lo, _hi, l in rain_b]
    wind = [{"band": l, "n": int(ww[l]["n"]), "pts": r1(ww[l]["pts"] / ww[l]["n"], 1) if ww[l]["n"] else None,
             "kick": r1(ww[l]["k_made"] / ww[l]["k_att"], 3) if ww[l]["k_att"] >= 40 else None, "kicks": int(ww[l]["k_att"])}
            for _lo, _hi, l in wind_b]
    # altitude: home sides at 1,000 m+ against visitors from lower down, against our expected margin (which has no
    # altitude term unless the model promoted one)
    alt = {"n": 0, "won": 0.0, "mg": 0.0, "err": 0.0}
    low = {"n": 0, "won": 0.0, "mg": 0.0, "err": 0.0}
    for m in S.finals:
        if m.get("neutral") or m.get("ro") or m["date"][:4] < "1995":
            continue
        e = elev_of(m)
        f = w["fc"].get(m["id"])
        if e is None or not f:
            continue
        hn = nations.base_name(nations.canonical(m["home"]["name"]))
        if hn not in ALT_HOME:
            continue
        b = alt if at_altitude(m) else (low if e < 500 else None)
        if b is None:
            continue
        b["n"] += 1
        b["won"] += 1.0 if m["hs"] > m["as"] else (0.5 if m["hs"] == m["as"] else 0.0)
        b["mg"] += m["hs"] - m["as"]
        b["err"] += (m["hs"] - m["as"]) - f["margin"]
    fin = lambda b: {"n": b["n"], "won": r1(b["won"] / b["n"], 3) if b["n"] else None, "margin": r1(b["mg"] / b["n"], 1) if b["n"] else None,
                     "vs_exp": r1(b["err"] / b["n"], 2) if b["n"] else None}
    return {"n": n, "rain": rain, "wind": wind, "altitude": {"high": fin(alt), "low": fin(low), "min_m": ALT_M}}
