"""
Season-level and site-wide payloads: standings (with the historical dropped-score rules),
points progression, the calendar, team colours, the season payload, the index, driver
careers, the Elo tables, the lab and the markets comparison.

Standings
---------
Gross points = the sum of every results and sprint row's points as awarded. Until 1990 only a
driver's best results counted; `DROP_RULES[year]` lists (rounds in the block, results counted)
blocks in calendar order, a None block length meaning "the rest of the season" (e.g. 1967:
best 5 of the first 6 rounds plus best 4 of the remaining 5; 1981-1990: best 11). Counted
points = sum over blocks of the best k per-round scores (a round's score = the sum of the
driver's rows in it, so a shared drive counts once). Constructors (from 1958): 1958-1978 a
constructor scores only its best-placed car's points in each round, with the same block rule
applied (an approximation of the period rules); from 1979 every car's points count. The
Indianapolis 500 (a drivers' round 1950-60) never counted for constructors, and in 1958-59 the
fastest-lap point went to the driver only, so a constructor's round score there is the position
table value of its best car (`CONSTRUCTOR_TABLE_YEARS`). Ties are broken by countback (most
wins, then second places, ...; Grand Prix results only).

Exclusions (`EXCLUDED`): Michael Schumacher was excluded from the 1997 drivers' championship and
McLaren from the 2007 constructors' championship. Their rows keep their results and gross
points, carry `"excluded": "<reason>"` and 0 counted points, and rank last.

The season payload's championship block maps `models.championship.simulate_championship`:
p_title, exp_points, p05/p95 (5th/95th percentile of final points), pos_dist, the magic
number (points still needed to be sure of the title), clinched, eliminated; finished seasons
get null.

Title history (`title_history`): one snapshot of the championship simulation per completed round, for a
chance-over-time chart with a band: {"after_round", "rounds_done", "as_of", "n_sims", "drivers" | "constructors":
{id: {"p_title", "exp_points", "p05", "p25", "p50", "p75", "p95", "points"}}} (points = actual points when the
snapshot was taken; p05-p95 = quantiles of simulated final points). The first build after a round's results
records it; a later build in the same state replaces it only with more simulations (a quick run never locks in
a point). Each build carries the previous season.json's series forward, so the series starts with the first
build that wrote it (22 Oct 2026, after round 17 of 2026): earlier rounds were never simulated and stored, and the
cached walk-forward race forecasts cannot stand in for them (each is one race, made with data up to that race,
so a title chance built from them would see results after the snapshot). When the season finishes a final
entry ("final": true) gives the champion 1 and every other entrant 0 at their final points.

Team colours: OpenF1 `team_colour` (2023-; the colour most often attached to the team's cars in
the season's race sessions), else a fixed colour for well-known constructors, else a
deterministic palette slot from a hash of the constructorId.
"""
from __future__ import annotations

import hashlib
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from typing import Any

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import driver_name, fnum, inum, rnd as _r, seasons_on_disk, status_kind, team_name

logger = logging.getLogger(__name__)

DROP_RULES: dict[int, list[tuple[int | None, int]]] = {
    **{y: [(None, 4)] for y in range(1950, 1954)}, **{y: [(None, 5)] for y in range(1954, 1958)},
    1958: [(None, 6)], 1959: [(None, 5)], 1960: [(None, 6)], 1961: [(None, 5)], 1962: [(None, 5)],
    1963: [(None, 6)], 1964: [(None, 6)], 1965: [(None, 6)], 1966: [(None, 5)],
    1967: [(6, 5), (None, 4)], 1968: [(6, 5), (None, 5)], 1969: [(6, 5), (None, 4)], 1970: [(7, 6), (None, 5)],
    1971: [(6, 5), (None, 4)], 1972: [(6, 5), (None, 5)], 1973: [(8, 7), (None, 6)], 1974: [(8, 7), (None, 6)],
    1975: [(7, 6), (None, 6)], 1976: [(8, 7), (None, 7)], 1977: [(9, 8), (None, 7)], 1978: [(8, 7), (None, 7)],
    1979: [(7, 4), (None, 4)], 1980: [(7, 5), (None, 5)], **{y: [(None, 11)] for y in range(1981, 1991)},
}

# Seasons whose constructors' round score is the position table value of the best car (no fastest-lap point).
CONSTRUCTOR_TABLE_YEARS: dict[int, list[float]] = {1958: [8, 6, 4, 3, 2], 1959: [8, 6, 4, 3, 2]}
# (year, "drivers" | "constructors", id) -> reason: excluded from that championship by the FIA.
EXCLUDED: dict[tuple[int, str, str], str] = {
    (1997, "drivers", "michael_schumacher"): "Excluded from the 1997 championship (European Grand Prix collision)",
    (2007, "constructors", "mclaren"): "Excluded from the 2007 constructors' championship",
}


def _indy(race: dict) -> bool:
    return "indianapolis" in str(race.get("name") or "").lower()


def _constructor_score(year: int, row: dict, points: float) -> float:
    """A row's points as they count for its constructor (module docstring)."""
    table = CONSTRUCTOR_TABLE_YEARS.get(int(year))
    if table is None:
        return points
    pos = inum(row.get("position"))
    if not pos or pos > len(table):
        return 0.0
    return min(points, float(table[pos - 1]))


def _apply_exclusions(year: int, kind: str, rows: list[dict], key: str) -> None:
    """Zero the counted points of excluded entries, flag them, and move them to the end (in place)."""
    hit = False
    for r in rows:
        why = EXCLUDED.get((int(year), kind, r[key]))
        if why:
            r["points"], r["excluded"], hit = 0.0, why, True
    if hit:
        rows.sort(key=lambda r: bool(r.get("excluded")))     # stable: the others keep their order

KNOWN_COLOURS = {
    "ferrari": "#E8002D", "mclaren": "#FF8000", "mercedes": "#27F4D2", "red_bull": "#3671C6", "williams": "#64C4FF",
    "alpine": "#0093CC", "aston_martin": "#229971", "haas": "#B6BABD", "sauber": "#52E252", "rb": "#6692FF",
    "alphatauri": "#5E8FAA", "alfa": "#C92D4B", "renault": "#FFF500", "racing_point": "#F596C8", "force_india": "#F596C8",
    "toro_rosso": "#469BFF", "lotus_f1": "#FFB800", "team_lotus": "#FFD700", "lotus-climax": "#FFD700", "brabham": "#00A651",
    "tyrrell": "#3D5A99", "benetton": "#00A0DE", "jordan": "#F5D300", "brawn": "#B8FD6E", "toyota": "#CC0000",
    "bmw_sauber": "#3B82F6", "honda": "#D9D9D9", "jaguar": "#0B6E4F", "stewart": "#FFFFFF", "ligier": "#1D4ED8",
    "minardi": "#111111", "arrows": "#F97316", "prost": "#2563EB", "maserati": "#B91C1C", "vanwall": "#065F46",
    "cooper": "#14532D", "brm": "#3F6212", "matra": "#1E40AF", "march": "#DC2626", "shadow": "#1F2937", "cadillac": "#C0C0C0",
    "audi": "#BB0A30",
}
PALETTE = ["#E6194B", "#3CB44B", "#FFE119", "#4363D8", "#F58231", "#911EB4", "#46F0F0", "#F032E6", "#BCF60C", "#FABEBE",
           "#008080", "#E6BEFF", "#9A6324", "#FFFAC8", "#AAFFC3", "#808000", "#FFD8B1", "#7F7FFF", "#FF6F61", "#6B8E23"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rounds(store: dict) -> list[str]:
    return sorted((k for k in (store.get("races") or {}) if str(k).isdigit()), key=int)


# ============================================================================== colours

def team_colours(year: int) -> dict[str, str]:
    """{constructorId: '#RRGGBB'} for the season (module docstring)."""
    st = canon.season(year)
    teams = set((st.get("constructors") or {}).keys())
    for r in (st.get("races") or {}).values():
        for row in (r.get("results") or []) + (r.get("qualifying") or []):
            if row.get("constructor"):
                teams.add(row["constructor"])
    votes: dict[str, Counter] = defaultdict(Counter)
    if year >= 2023:
        for e in sorted(canon.session_index(year), key=lambda e: e.get("date") or "", reverse=True):
            if e.get("type") != "Race" or e.get("round") is None:
                continue
            rec = canon.load_session(e["path"])
            for num, info in ((rec or {}).get("drivers") or {}).items():
                col = str((info or {}).get("team_colour") or "").strip().lstrip("#")
                d = canon.driver_for_number(year, num, e["round"])
                t = canon.team_for(year, e["round"], d) if d else None
                if t and len(col) == 6:
                    votes[t]["#" + col.upper()] += 1
            if teams and all(t in votes for t in teams):
                break
    out = {}
    for t in sorted(teams):
        if votes.get(t):
            out[t] = votes[t].most_common(1)[0][0]
        elif t in KNOWN_COLOURS:
            out[t] = KNOWN_COLOURS[t]
        else:
            out[t] = PALETTE[int(hashlib.sha1(t.encode()).hexdigest(), 16) % len(PALETTE)]
    return out


# ============================================================================== standings

def _counted(scores: list[float], rule: list[tuple[int | None, int]] | None) -> float:
    """Counted points from per-round scores (calendar order) under a dropped-score rule."""
    if not rule:
        return sum(scores)
    tot, i = 0.0, 0
    for length, best in rule:
        block = scores[i:] if length is None else scores[i:i + length]
        i = len(scores) if length is None else i + length
        tot += sum(sorted(block, reverse=True)[:best])
    return tot


def standings(year: int) -> dict:
    """{"drivers": [{pos, driver, team, points, points_gross, wins, podiums, poles}], "constructors": [...], "rounds_done"}."""
    st = canon.season(year)
    rule = DROP_RULES.get(int(year))
    rounds = [k for k in _rounds(st) if (st["races"][k].get("results"))]
    d_scores: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(rounds))
    t_scores: dict[str, list[float]] = defaultdict(lambda: [0.0] * len(rounds))
    d_cb: dict[str, list[int]] = defaultdict(lambda: [0] * 30)
    t_cb: dict[str, list[int]] = defaultdict(lambda: [0] * 30)
    team_last: dict[str, str] = {}
    team_count: dict[str, Counter] = defaultdict(Counter)
    poles: Counter = Counter()
    indy_only: dict[str, bool] = {}
    for i, k in enumerate(rounds):
        race = st["races"][k]
        best_car: dict[str, float] = {}
        indy = _indy(race)
        for row in race.get("results") or []:
            if row.get("constructor"):
                indy_only[row["constructor"]] = indy_only.get(row["constructor"], True) and indy
        for row in (race.get("results") or []) + (race.get("sprint") or []):
            d, t, p = row.get("driver"), row.get("constructor"), fnum(row.get("points")) or 0.0
            if not d:
                continue
            d_scores[d][i] += p
            if t:
                team_last[d] = t
                team_count[d][t] += 1
                if indy:                                       # never a constructors' round
                    continue
                if 1958 <= int(year) <= 1978:                  # only the best-placed car scored (no sprints then)
                    best_car[t] = max(best_car.get(t, 0.0), _constructor_score(year, row, p))
                else:
                    t_scores[t][i] += p
        for t, p in best_car.items():
            t_scores[t][i] += p
        for row in race.get("results") or []:
            pos = inum(row.get("position"))
            if pos and status_kind(row) == "finished" and pos <= 30:
                d_cb[row["driver"]][pos - 1] += 1
                if row.get("constructor") and not indy:
                    t_cb[row["constructor"]][pos - 1] += 1
        q = next((r.get("driver") for r in race.get("qualifying") or [] if inum(r.get("position")) == 1), None)
        q = q or next((r.get("driver") for r in race.get("results") or [] if inum(r.get("grid")) == 1), None)
        if q:
            poles[q] += 1
    drivers = []
    for d, sc in d_scores.items():
        drivers.append({"driver": d, "team": team_last.get(d), "teams": [t for t, _ in team_count[d].most_common()],
                        "points": round(_counted(sc, rule), 2), "points_gross": round(sum(sc), 2),
                        "wins": d_cb[d][0], "podiums": sum(d_cb[d][:3]), "poles": poles.get(d, 0), "_cb": d_cb[d]})
    drivers.sort(key=lambda r: (-r["points"], [-x for x in r["_cb"]], r["driver"]))
    _apply_exclusions(year, "drivers", drivers, "driver")
    for k, r in enumerate(drivers, 1):
        r["pos"] = k
        r.pop("_cb")
    cons = []
    if int(year) >= 1958:
        for t, sc in t_scores.items():
            if indy_only.get(t):
                continue
            cons.append({"team": t, "points": round(_counted(sc, rule if int(year) <= 1978 else None), 2), "points_gross": round(sum(sc), 2),
                         "wins": t_cb[t][0], "podiums": sum(t_cb[t][:3]), "_cb": t_cb[t]})
        cons.sort(key=lambda r: (-r["points"], [-x for x in r["_cb"]], r["team"]))
        _apply_exclusions(year, "constructors", cons, "team")
        for k, r in enumerate(cons, 1):
            r["pos"] = k
            r.pop("_cb")
    return {"drivers": drivers, "constructors": cons, "rounds_done": [int(k) for k in rounds], "dropped_scores": bool(rule)}


def progression(year: int) -> dict:
    """Cumulative gross points after each finished round: {"rounds", "drivers": {d: [...]}, "constructors": {t: [...]}}."""
    st = canon.season(year)
    rounds = [k for k in _rounds(st) if st["races"][k].get("results")]
    dp: dict[str, list[float]] = {}
    tp: dict[str, list[float]] = {}
    acc_d: dict[str, float] = defaultdict(float)
    acc_t: dict[str, float] = defaultdict(float)
    for i, k in enumerate(rounds):
        race = st["races"][k]
        best_car: dict[str, float] = {}
        indy = _indy(race)
        for row in (race.get("results") or []) + (race.get("sprint") or []):
            d, t, p = row.get("driver"), row.get("constructor"), fnum(row.get("points")) or 0.0
            if d:
                acc_d[d] += p
            if t and not indy:
                if 1958 <= int(year) <= 1978 and row in (race.get("results") or []):
                    best_car[t] = max(best_car.get(t, 0.0), _constructor_score(year, row, p))
                else:
                    acc_t[t] += p
        for t, p in best_car.items():
            acc_t[t] += p
        for d in acc_d:
            dp.setdefault(d, [0.0] * i).append(round(acc_d[d], 2))
        if int(year) >= 1958:
            for t in acc_t:
                tp.setdefault(t, [0.0] * i).append(round(acc_t[t], 2))
    return {"rounds": [int(k) for k in rounds], "drivers": dp, "constructors": tp}


# ============================================================================== season payload

def finished(year: int, current: int) -> bool:
    st = canon.season(year)
    rs = _rounds(st)
    done = [k for k in rs if st["races"][k].get("results")]
    return bool(rs) and (len(done) == len(rs) or (int(year) < int(current) and bool(done)))


def calendar(year: int, forecasts: dict[int, dict] | None = None) -> list[dict]:
    st = canon.season(year)
    out, nxt = [], None
    for k in _rounds(st):
        race = st["races"][k]
        c = race.get("circuit") or {}
        res = race.get("results") or []
        done = bool(res)
        if not done and nxt is None:
            nxt = k
        status = "done" if done else ("next" if nxt == k else "upcoming")
        win = next((r.get("driver") for r in res if inum(r.get("position")) == 1), None)
        pole = next((r.get("driver") for r in race.get("qualifying") or [] if inum(r.get("position")) == 1), None)
        fastest = next((r.get("driver") for r in res if inum(r.get("fastest_rank")) == 1), None)
        fc = (forecasts or {}).get(int(k)) or {}
        sim = fc.get("post") or fc.get("pre")
        top = []
        if sim:
            top = sorted(((d, v.get("p_win") or 0.0) for d, v in sim["drivers"].items()), key=lambda x: -x[1])[:3]
            top = [[d, round(p, 4)] for d, p in top]
        out.append({"round": int(k), "name": race.get("name"), "date": race.get("date"), "time": race.get("time"),
                    "circuit": {"id": c.get("id"), "name": c.get("name"), "country": c.get("country"), "locality": c.get("locality")},
                    "sprint": bool(race.get("sprint") or (race.get("sessions") or {}).get("sprint")), "status": status,
                    "winner": win, "winner_team": next((r.get("constructor") for r in res if inum(r.get("position")) == 1), None),
                    "pole": pole, "fastest": fastest, "p_win_top": top})
    return out


def _champ_block(sim: dict | None) -> dict | None:
    if not sim or not sim.get("drivers"):
        return None

    def ent(v: dict) -> dict:
        q = v.get("points_q") or {}
        mg = v.get("magic") or {}
        return {"p_title": _r(v.get("p_title"), 4), "exp_points": _r(v.get("exp_points"), 2), "p05": _r(q.get("q5"), 1),
                "p95": _r(q.get("q95"), 1), "p50": _r(q.get("q50"), 1), "pos_dist": [round(float(x), 4) for x in v.get("pos_dist") or []],
                "exp_pos": _r(v.get("exp_pos"), 2), "current_points": v.get("current_points"),
                "magic": _r(mg.get("magic_number"), 1), "clinched": bool(mg.get("clinched")), "eliminated": bool(mg.get("eliminated")),
                "team": v.get("team"),
                "per_round_exp_points": v.get("per_round_exp_points")}
    return {"drivers": {d: ent(v) for d, v in sim["drivers"].items()},
            "constructors": {t: ent(v) for t, v in (sim.get("constructors") or {}).items()},
            "conditional": sim.get("conditionals") or {}, "n_sims": sim.get("n"), "remaining": sim.get("remaining"),
            "max_points_left": sim.get("max_points_left"), "runtime_s": sim.get("runtime_s"), "sources": sim.get("sources")}


def _hist_ent(v: dict) -> dict:
    q = v.get("points_q") or {}
    return {"p_title": _r(v.get("p_title"), 4), "exp_points": _r(v.get("exp_points"), 1), "p05": _r(q.get("q5"), 1),
            "p25": _r(q.get("q25"), 1), "p50": _r(q.get("q50"), 1), "p75": _r(q.get("q75"), 1), "p95": _r(q.get("q95"), 1),
            "points": _r(v.get("current_points"), 1)}


def title_history(prev: dict | None, sim: dict | None, stand: dict | None = None, finished_season: bool = False) -> list[dict]:
    """The previous season.json's "title_history" with this build's snapshot added (module docstring)."""
    hist = [h for h in ((prev or {}).get("title_history") or []) if isinstance(h, dict) and h.get("after_round") is not None]
    if finished_season:
        if hist and not hist[-1].get("final") and stand and stand.get("drivers"):
            rd = stand.get("rounds_done") or []
            champ_d = stand["drivers"][0]["driver"]
            champ_t = (stand.get("constructors") or [{}])[0].get("team")

            def fin(rows, key, champ):
                return {r[key]: {"p_title": 1.0 if r[key] == champ else 0.0, "points": r.get("points"), "exp_points": r.get("points"),
                                 "p05": r.get("points"), "p25": r.get("points"), "p50": r.get("points"), "p75": r.get("points"),
                                 "p95": r.get("points")} for r in rows}
            hist.append({"after_round": max(rd) if rd else None, "rounds_done": len(rd), "as_of": _now(), "n_sims": None, "final": True,
                         "drivers": fin(stand["drivers"], "driver", champ_d),
                         "constructors": fin(stand.get("constructors") or [], "team", champ_t)})
        return hist
    if not sim or not sim.get("drivers"):
        return hist
    done = sorted(int(r) for r in sim.get("completed") or [])
    if not done:
        return hist
    snap = {"after_round": done[-1], "rounds_done": len(done), "as_of": _now(), "n_sims": sim.get("n"),
            "drivers": {d: _hist_ent(v) for d, v in sorted(sim["drivers"].items())},
            "constructors": {t: _hist_ent(v) for t, v in sorted((sim.get("constructors") or {}).items())}}
    hist = [h for h in hist if not h.get("final")]
    same = [h for h in hist if h["after_round"] == snap["after_round"]]
    if same and (same[-1].get("n_sims") or 0) >= (snap["n_sims"] or 0):
        return hist
    return sorted([h for h in hist if h["after_round"] != snap["after_round"]] + [snap], key=lambda h: h["after_round"])


def season_elo(history: dict | None, year: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for race in (history or {}).get("races") or []:
        if race.get("year") != year:
            continue
        for d, r in (race.get("drivers") or {}).items():
            out[d] = {"elo": r.get("elo"), "elo_teammate": r.get("elo_teammate"), "elo_quali": r.get("elo_quali")}
    return out


def build_season(year: int, current: int, *, forecasts: dict | None = None, effects: dict | None = None, split: dict | None = None,
                 championship: dict | None = None, elo: dict | None = None, colours: dict | None = None,
                 stand: dict | None = None, prev: dict | None = None) -> dict:
    """season.json (PAYLOADS). `prev` is the season.json on disk: its "title_history" is carried forward."""
    st = canon.season(year)
    rs = _rounds(st)
    if not rs:
        return {"ok": False, "reason": "no season store on disk", "year": year}
    stand = stand or standings(year)
    eff = effects or {}
    colours = colours or team_colours(year)
    teams: dict[str, dict] = {}
    for r in stand["drivers"]:
        for t in r.get("teams") or []:
            teams.setdefault(t, {"name": team_name(st, t), "colour": colours.get(t), "drivers": []})["drivers"].append(r["driver"])
    fin = finished(year, current)
    return {
        "ok": True, "year": year, "updated_at": _now(), "rounds_total": len(rs), "rounds_done": len(stand["rounds_done"]),
        "finished": fin, "calendar": calendar(year, forecasts),
        "standings": {"drivers": [{k: r[k] for k in ("pos", "driver", "team", "points", "points_gross", "wins", "podiums", "poles", "excluded")
                                   if k in r} for r in stand["drivers"]],
                      "constructors": [{k: r[k] for k in ("pos", "team", "points", "points_gross", "wins", "podiums", "excluded") if k in r}
                                       for r in stand["constructors"]],
                      "dropped_scores": stand.get("dropped_scores", False)},
        "progression": progression(year),
        "championship": None if fin else _champ_block(championship),
        "car_pace": {"race": eff.get("car") or {}, "quali": eff.get("quali_car") or {}},
        "driver_effects": {"race": eff.get("driver") or {}, "quali": eff.get("quali_driver") or {}},
        "effects_params": eff.get("params") or {},
        "car_driver_split": split or {},
        "elo": season_elo(elo, year),
        "teams": teams,
        "names": {d: driver_name(st, d) for d in (st.get("drivers") or {})},
        "title_history": title_history(prev, championship, stand, fin),
    }


# ============================================================================== site-wide

def _iso(day: str | None, time: str | None) -> str | None:
    if not day:
        return None
    return f"{day}T{time}" if time else day


def index(current: int, years: list[int], metas: dict[int, dict], colours: dict[str, str] | None = None) -> dict:
    """index.json (PAYLOADS)."""
    st = canon.season(current)
    today = date.today().isoformat()
    nxt, last = None, None
    for y in sorted({current, current + 1} & set(years) | {current}):
        s = canon.season(y)
        for k in _rounds(s):
            race = s["races"][k]
            if race.get("results"):
                if y == current:
                    last = (y, k, race)
            elif nxt is None and (race.get("date") or "9999") >= today:
                nxt = (y, k, race)
    if last is None:
        for y in sorted(years, reverse=True):
            s = canon.season(y)
            dk = [k for k in _rounds(s) if s["races"][k].get("results")]
            if dk:
                last = (y, dk[-1], s["races"][dk[-1]])
                break
    out: dict[str, Any] = {"updated_at": _now(), "current_season": current, "seasons": sorted(years, reverse=True), "next": None, "last": None}
    if nxt:
        y, k, race = nxt
        ss = race.get("sessions") or {}
        c = race.get("circuit") or {}
        out["next"] = {"year": y, "round": int(k), "name": race.get("name"), "date": race.get("date"),
                       "circuit": {"id": c.get("id"), "name": c.get("name"), "country": c.get("country"), "locality": c.get("locality")},
                       "sessions": {"fp1": ss.get("fp1"), "fp2": ss.get("fp2"), "fp3": ss.get("fp3"), "quali": ss.get("quali"),
                                    "sprint_quali": ss.get("sprint_quali"), "sprint": ss.get("sprint"),
                                    "race": _iso(race.get("date"), race.get("time"))}}
    if last:
        y, k, race = last
        win = next((r.get("driver") for r in race.get("results") or [] if inum(r.get("position")) == 1), None)
        out["last"] = {"year": y, "round": int(k), "name": race.get("name"), "winner": win, "date": race.get("date"),
                       "winner_team": next((r.get("constructor") for r in race.get("results") or [] if inum(r.get("position")) == 1), None)}
    drivers = {}
    rounds = _rounds(st)
    latest = max((int(k) for k in rounds if st["races"][k].get("results") or st["races"][k].get("qualifying")), default=None)
    lineup = canon.lineup(current, latest) if latest else {}
    seen = set()
    for k in rounds:
        for row in (st["races"][k].get("results") or []) + (st["races"][k].get("qualifying") or []):
            if row.get("driver"):
                seen.add(row["driver"])
    for d in sorted(seen):
        info = (st.get("drivers") or {}).get(d) or {}
        drivers[d] = {"name": driver_name(st, d), "code": info.get("code"), "number": info.get("number"),
                      "nationality": info.get("nationality"), "team": lineup.get(d) or canon.team_for(current, latest or 1, d)}
    out["drivers"] = drivers
    cols = colours or team_colours(current)
    tset = set(lineup.values()) | {v["team"] for v in drivers.values() if v["team"]}
    out["teams"] = {t: {"name": team_name(st, t), "colour": cols.get(t)} for t in sorted(tset)}
    out["seasons_meta"] = {str(y): metas.get(y) for y in sorted(years, reverse=True) if metas.get(y)}
    return out


def season_meta(year: int, current: int, stand: dict | None = None) -> dict:
    st = canon.season(year)
    rs = _rounds(st)
    stand = stand or standings(year)
    fin = finished(year, current)
    return {"rounds": len(rs), "completed": len(stand["rounds_done"]),
            "champion": stand["drivers"][0]["driver"] if fin and stand["drivers"] else None,
            "constructors_champion": stand["constructors"][0]["team"] if fin and stand["constructors"] else None}


# ============================================================================== careers

def careers(years: list[int], stands: dict[int, dict], elo: dict | None, finished_years: set[int] | None = None) -> dict[str, dict]:
    """data/drivers/<id>.json for every driver in the stores: seasons, Elo path, team-mate head-to-heads, totals."""
    out: dict[str, dict] = {}
    for y in sorted(years):
        st = canon.season(y)
        stand = stands.get(y) or standings(y)
        pos = {r["driver"]: r for r in stand["drivers"]}
        agg: dict[str, dict] = defaultdict(lambda: {"races": 0, "wins": 0, "podiums": 0, "poles": 0, "teams": Counter(), "best": None})
        h2h_q: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        h2h_r: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
        for k in _rounds(st):
            race = st["races"][k]
            res = race.get("results") or []
            by_team: dict[str, list[dict]] = defaultdict(list)
            for row in res:
                d = row.get("driver")
                if not d or status_kind(row) == "dns":
                    continue
                a = agg[d]
                a["races"] += 1
                a["teams"][row.get("constructor")] += 1
                p = inum(row.get("position"))
                if status_kind(row) == "finished" and p:
                    a["wins"] += p == 1
                    a["podiums"] += p <= 3
                    a["best"] = p if a["best"] is None else min(a["best"], p)
                by_team[row.get("constructor")].append(row)
            for t, rows in by_team.items():
                for i in range(len(rows)):
                    for j in range(i + 1, len(rows)):
                        a, b = rows[i], rows[j]
                        ca, cb = status_kind(a) == "finished", status_kind(b) == "finished"
                        if not (ca or cb):
                            continue
                        a_wins = (ca and not cb) or (ca and cb and (inum(a.get("position")) or 99) < (inum(b.get("position")) or 99))
                        h2h_r[(a["driver"], b["driver"])][0 if a_wins else 1] += 1
                        h2h_r[(b["driver"], a["driver"])][1 if a_wins else 0] += 1
            q = [r for r in race.get("qualifying") or [] if r.get("driver") and inum(r.get("position"))]
            qt: dict[str, list[dict]] = defaultdict(list)
            for r in q:
                qt[r.get("constructor")].append(r)
            for rows in qt.values():
                for i in range(len(rows)):
                    for j in range(i + 1, len(rows)):
                        a, b = rows[i], rows[j]
                        a_wins = inum(a["position"]) < inum(b["position"])
                        h2h_q[(a["driver"], b["driver"])][0 if a_wins else 1] += 1
                        h2h_q[(b["driver"], a["driver"])][1 if a_wins else 0] += 1
            pole = next((r.get("driver") for r in race.get("qualifying") or [] if inum(r.get("position")) == 1), None)
            pole = pole or next((r.get("driver") for r in res if inum(r.get("grid")) == 1), None)
            if pole:
                agg[pole]["poles"] += 1
        for d, a in agg.items():
            info = (st.get("drivers") or {}).get(d) or {}
            c = out.setdefault(d, {"driver": d, "name": driver_name(st, d), "dob": info.get("dob"), "nationality": info.get("nationality"),
                                   "code": info.get("code"), "seasons": [], "elo": [], "teammates": []})
            c["name"] = driver_name(st, d) or c["name"]
            sr = pos.get(d) or {}
            c["seasons"].append({"year": y, "team": a["teams"].most_common(1)[0][0] if a["teams"] else None,
                                 "teams": [t for t, _ in a["teams"].most_common()], "races": a["races"], "wins": a["wins"],
                                 "podiums": a["podiums"], "poles": a["poles"], "points": sr.get("points_gross"),
                                 "points_counted": sr.get("points"), "pos": sr.get("pos"), "best_finish": a["best"]})
        mates = defaultdict(set)
        for (a, b) in list(h2h_r) + list(h2h_q):
            mates[a].add(b)
        for d, ms in mates.items():
            if d in out:
                for m in sorted(ms):
                    out[d]["teammates"].append({"year": y, "teammate": m, "h2h_quali": list(h2h_q.get((d, m), [0, 0])),
                                                "h2h_race": list(h2h_r.get((d, m), [0, 0]))})
    for race in (elo or {}).get("races") or []:
        for d, r in (race.get("drivers") or {}).items():
            if d in out:
                out[d]["elo"].append([race["year"], race["round"], r.get("elo"), r.get("elo_teammate")])
    champs = Counter()
    for y in years:
        stand = stands.get(y)
        if stand and stand["drivers"] and y in (finished_years or set()):
            champs[stand["drivers"][0]["driver"]] += 1
    for d, c in out.items():
        ss = c["seasons"]
        peaks = ((elo or {}).get("peaks") or {}).get(d) or {}
        c["totals"] = {"seasons": len(ss), "races": sum(s["races"] for s in ss), "wins": sum(s["wins"] for s in ss),
                       "podiums": sum(s["podiums"] for s in ss), "poles": sum(s["poles"] for s in ss),
                       "points": round(sum(s["points"] or 0 for s in ss), 2), "titles": champs.get(d, 0),
                       "best_finish": min((s["best_finish"] for s in ss if s["best_finish"]), default=None),
                       "first_year": min(s["year"] for s in ss), "last_year": max(s["year"] for s in ss),
                       "teams": list(dict.fromkeys(t for s in ss for t in s["teams"] if t)),
                       "peak_elo": (peaks.get("elo") or {}).get("value"), "peak_elo_teammate": (peaks.get("elo_teammate") or {}).get("value"),
                       "peak_elo_quali": (peaks.get("elo_quali") or {}).get("value")}
    return out


# ============================================================================== elo, lab, markets

def elo_payload(history: dict | None) -> dict:
    h = history or {}
    at = []
    for r in (h.get("all_time") or [])[:200]:
        at.append({"driver": r["driver"], "name": r.get("name"), "peak_teammate": r.get("peak_teammate"), "peak_field": r.get("peak_field"),
                   "peak_quali": r.get("peak_quali"), "races": r.get("starts"), "years": [r.get("first_year"), r.get("last_year")],
                   "peak_teammate_at": r.get("peak_teammate_at")})
    cur = {d: {"elo": v.get("elo"), "elo_teammate": v.get("elo_teammate"), "elo_quali": v.get("elo_quali"), "name": v.get("name"),
               "starts": v.get("starts")}
           for d, v in (h.get("current") or {}).items() if v.get("active")}
    return {"updated_at": _now(), "all_time": at, "current": cur, "params": h.get("params") or {}, "seasons": h.get("seasons") or []}


def lab_payload(catalogues: dict[int, dict], current: int) -> dict:
    """lab.json: one row per driver-season (2018-), columns = driverId, name, team, year, races, then every catalogue metric."""
    from oddsmarkets.f1.analytics.drivers import METRICS
    keys = [m["key"] for m in METRICS if m["key"] != "races"]
    fields = ["driver", "name", "team", "year", "races"] + keys
    rows = []
    for y in sorted(catalogues, reverse=True):
        if y < 2018:
            continue
        for d, e in (catalogues[y].get("drivers") or {}).items():
            v = e.get("values") or {}
            rows.append([d, e.get("name"), e.get("team"), y, e.get("races")] + [v.get(k) for k in keys])
    metrics = [{k: m[k] for k in ("key", "label", "group", "fmt", "lower", "scope")} | {"desc": m.get("desc", "")}
               for m in (catalogues.get(current) or next(iter(catalogues.values()), {})).get("metrics") or METRICS if m["key"] != "races"]
    return {"updated_at": _now(), "fields": fields, "metrics": metrics, "rows": rows, "windows": {"season": current},
            "years": sorted({r[3] for r in rows}, reverse=True)}


def _title(mk: dict | None, model: dict[str, float]) -> dict:
    mk = mk or {}
    prices = {k: round(float(v), 4) for k, v in (mk.get("probs") or {}).items()}
    edge = {k: round(model[k] / p - 1.0, 4) for k, p in prices.items() if p > 0 and k in model}
    return {"available": bool(mk.get("available")), "prices": prices, "model": {k: round(float(v), 4) for k, v in model.items()},
            "edge": edge, "sources": sorted((mk.get("sources") or {}).keys()), "by_source": mk.get("sources") or {},
            "eliminated": mk.get("eliminated") or [], "implied_total": mk.get("implied_total"), "reason": mk.get("reason"),
            "markets": mk.get("markets") or {}}


def _p_ahead(da: list[float], db: list[float]) -> float | None:
    """P(a finishes ahead of b) from two position distributions, treated as independent (ties split)."""
    if not da or not db:
        return None
    n = max(len(da), len(db))
    a = list(da) + [0.0] * (n - len(da))
    b = list(db) + [0.0] * (n - len(db))
    cb = [0.0] * (n + 1)
    for j in range(n - 1, -1, -1):
        cb[j] = cb[j + 1] + b[j]
    p = sum(a[i] * (cb[i + 1] + 0.5 * b[i]) for i in range(n))
    return round(p / ((sum(a) or 1) * (sum(b) or 1)), 4)


def markets_payload(year: int, championship: dict | None, next_race: tuple[int, dict | None] | None, fetch: bool = True) -> dict:
    """markets.json: title markets v the championship simulation, the next race winner v its forecast, head-to-heads."""
    out: dict[str, Any] = {"updated_at": _now(), "year": year}
    md = {d: v.get("p_title", 0.0) for d, v in ((championship or {}).get("drivers") or {}).items()}
    mc = {t: v.get("p_title", 0.0) for t, v in ((championship or {}).get("constructors") or {}).items()}
    if fetch:
        from oddsmarkets.f1.sources import markets as f1m
        dt, ct = f1m.title_prices("drivers", year), f1m.title_prices("constructors", year)
    else:
        dt = ct = {"available": False, "reason": "market fetch skipped (--no-market)"}
    out["drivers_title"] = _title(dt, md)
    out["constructors_title"] = _title(ct, mc)
    nr: dict[str, Any] = {"year": year, "round": None, "prices": {}, "model": {}, "sources": [], "available": False}
    if next_race:
        rnd_, sim = next_race
        nr["round"] = rnd_
        nr["model"] = {d: round(float(v.get("p_win") or 0.0), 4) for d, v in ((sim or {}).get("drivers") or {}).items()}
        if fetch:
            from oddsmarkets.f1.sources import markets as f1m
            rw = f1m.race_winner_prices(year, rnd_)
            nr.update({"prices": {k: round(float(v), 4) for k, v in (rw.get("probs") or {}).items()},
                       "sources": sorted((rw.get("sources") or {}).keys()), "available": bool(rw.get("available")),
                       "reason": rw.get("reason"), "markets": rw.get("markets") or {}})
            nr["edge"] = {k: round(nr["model"][k] / p - 1.0, 4) for k, p in nr["prices"].items() if p > 0 and k in nr["model"]}
        else:
            nr["reason"] = "market fetch skipped (--no-market)"
    out["next_race"] = nr
    h2h = []
    if fetch:
        from oddsmarkets.f1.sources import markets as f1m
        hp = f1m.h2h_prices(year)
        race_sim = (next_race or (None, None))[1] or {}
        for row in hp.get("race") or []:
            m = None
            if next_race and row.get("round") == next_race[0]:
                da = ((race_sim.get("drivers") or {}).get(row["a"]) or {}).get("pos_dist")
                db = ((race_sim.get("drivers") or {}).get(row["b"]) or {}).get("pos_dist")
                m = _p_ahead(da, db)
            h2h.append({**row, "scope": "race", "model_a": m})
        for row in hp.get("season") or []:
            ch = (championship or {}).get("drivers") or {}
            m = _p_ahead((ch.get(row["a"]) or {}).get("pos_dist"), (ch.get(row["b"]) or {}).get("pos_dist"))
            h2h.append({**row, "scope": "season", "model_a": m})
    out["h2h"] = h2h
    return out
