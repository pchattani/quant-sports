"""
The per-competition analytics payload (analytics.json): round-by-round teams
and players of the week with awards, season XIs on four bases, the best and
worst performers on every headline metric, and each team's statistical profile
with within-competition percentiles.

Everything here is descriptive and built from what the other analytics modules
already produce: the player rows of `aggregate_players` (with percentiles and
`qualified` from `add_percentiles`), the match logs of `player_match_logs`,
the team rows of `team_match_stats` and the season's fixtures. Every section
degrades on its own: a competition without team sheets gets empty team
performers and profiles, one without player logs gets no rounds, and nothing
here raises.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable

from oddsmarkets.football.analytics.glossary import TEAM_METRICS
from oddsmarkets.football.analytics.players import METRICS, minutes_floor

logger = logging.getLogger("insights")

# (defenders, midfielders, forwards) shapes the XI optimiser may choose from.
SHAPES: tuple[tuple[int, int, int], ...] = ((4, 3, 3), (4, 4, 2), (3, 5, 2), (3, 4, 3), (5, 3, 2), (5, 4, 1), (4, 5, 1), (3, 6, 1))

# The player metrics with a top and bottom eight.
PERFORMER_KEYS = ["rating", "ga_90", "npxg_xa_90", "finishing", "placement", "xa_per_kp", "shot_creation_90",
                  "prog_actions_90", "padj_tkl_int_90", "ball_wins_90", "duel_pct", "aerial_pct", "loss_per_100",
                  "pass_pct", "km_90", "goals_prevented_90", "save_pct"]

TOTW_MINUTES = 45      # a team-of-the-week place needs this many minutes in the match
POTW_MINUTES = 60      # player of the week
WALL_MINUTES = 60      # the goalkeeping award
FORM_MATCHES = 6       # matches in a team's form strip
FORM_XI_MATCHES = 5    # matches behind the form XI's mean rating
FORM_XI_MIN_MATCHES = 3
GOAL_CAP = 8           # the Poisson score matrix runs 0..GOAL_CAP goals a side
PERF_N = 8
BENCH_N = 3
PTS = {"W": 3, "D": 1, "L": 0}


# ── small helpers ────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _r(v, nd: int = 3):
    f = _num(v)
    return None if f is None else round(f, nd)


def _f0(v) -> float:
    f = _num(v)
    return 0.0 if f is None else f


def _int(v) -> int:
    f = _num(v)
    return 0 if f is None else int(round(f))


def _pos(v) -> str:
    return v if v in ("G", "D", "M", "F") else "M"


def _safe(name: str, fn: Callable[[], Any], default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("analytics: %s failed: %s", name, exc)
        return default


# ── expected points from a Poisson score matrix ──────────────────────────────

def poisson_score_matrix(lam_h: float, lam_a: float, cap: int = GOAL_CAP) -> list[list[float]]:
    """P(home goals = i, away goals = j) for i, j in 0..cap, independent Poissons, renormalised to sum to 1."""
    lam_h, lam_a = max(_f0(lam_h), 0.0), max(_f0(lam_a), 0.0)
    ph = [math.exp(-lam_h) * lam_h ** k / math.factorial(k) for k in range(cap + 1)]
    pa = [math.exp(-lam_a) * lam_a ** k / math.factorial(k) for k in range(cap + 1)]
    total = sum(ph) * sum(pa)
    if total <= 0:
        return [[1.0 if i == j == 0 else 0.0 for j in range(cap + 1)] for i in range(cap + 1)]
    return [[ph[i] * pa[j] / total for j in range(cap + 1)] for i in range(cap + 1)]


def expected_points(xg, xga, cap: int = GOAL_CAP) -> dict[str, float] | None:
    """
    A team's expected points from a match with means (xg for, xg against):
    3 × P(win) + P(draw) over the Poisson score matrix. None when either is unknown.
    """
    a, b = _num(xg), _num(xga)
    if a is None or b is None:
        return None
    m = poisson_score_matrix(a, b, cap)
    win = sum(m[i][j] for i in range(cap + 1) for j in range(cap + 1) if i > j)
    draw = sum(m[i][i] for i in range(cap + 1))
    loss = max(1.0 - win - draw, 0.0)
    return {"xpts": 3.0 * win + draw, "win": win, "draw": draw, "loss": loss}


# ── the formation optimiser ──────────────────────────────────────────────────

def pick_formation(candidates: list[dict], shapes=SHAPES) -> tuple[str | None, list[dict], list[dict]]:
    """
    The best eleven under one of `shapes`. Each candidate is {"pos": G/D/M/F,
    "score": float (what the XI maximises), "key": tuple (sort order, ascending),
    "line": the PLAYER_LINE to emit}. Returns (formation or None, xi, bench):
    one goalkeeper, then the (D, M, F) shape with the highest total score, the
    xi ordered G, D..., M..., F... with each line in descending order. When
    fewer than eleven qualify (or no shape fits), the best eleven by rank are
    returned with formation None.
    """
    ordered = sorted(candidates, key=lambda c: c["key"])
    by_pos: dict[str, list[dict]] = {"G": [], "D": [], "M": [], "F": []}
    for c in ordered:
        by_pos[_pos(c.get("pos"))].append(c)
    best: tuple[float, str, list[dict]] | None = None
    if len(ordered) >= 11 and by_pos["G"]:
        for d, m, f in shapes:
            if len(by_pos["D"]) < d or len(by_pos["M"]) < m or len(by_pos["F"]) < f:
                continue
            chosen = [by_pos["G"][0]] + by_pos["D"][:d] + by_pos["M"][:m] + by_pos["F"][:f]
            total = sum(_f0(c.get("score")) for c in chosen)
            if best is None or total > best[0]:
                best = (total, f"{d}-{m}-{f}", chosen)
    if best is None:
        formation, chosen = None, ordered[:11]
    else:
        _, formation, chosen = best
    taken = {id(c) for c in chosen}
    bench = [c for c in ordered if id(c) not in taken][:BENCH_N]
    return formation, [c["line"] for c in chosen], [c["line"] for c in bench]


# ── player lines ─────────────────────────────────────────────────────────────

def _line_from_log(pid: str, entry: dict, row: dict, pos: str) -> dict:
    """PLAYER_LINE from one match-log row."""
    return {
        "id": str(pid), "name": entry.get("name") or "", "team": row.get("team") or entry.get("team") or "",
        "pos": pos, "rt": _r(row.get("rt")), "g": _int(row.get("g")), "a": _int(row.get("a")),
        "xg": _r(row.get("xg")) or 0.0, "xa": _r(row.get("xa")) or 0.0, "min": _int(row.get("min")),
        "gid": str(row.get("gid")) if row.get("gid") is not None else None,
        "opp": row.get("opp"), "ha": row.get("ha"), "gf": row.get("gf"), "ga": row.get("ga"),
    }


def _season_line(p: dict, pos: str, value: float) -> dict:
    """PLAYER_LINE for a season XI: season totals, the basis value in `rt` and `value`."""
    return {
        "id": str(p.get("player_id")), "name": p.get("name") or "", "team": p.get("team") or "", "pos": pos,
        "rt": _r(value), "g": _int(p.get("goals")), "a": _int(p.get("assists")),
        "xg": _r(p.get("xg")) or 0.0, "xa": _r(p.get("xa")) or 0.0, "min": _int(p.get("minutes")),
        "gid": None, "opp": None, "ha": None, "gf": None, "ga": None, "value": _r(value),
    }


def _rank_key(row: dict) -> tuple:
    """Rating, then goals + assists, then xG + xA (all descending), then name."""
    return (-_f0(row.get("rt")), -(_f0(row.get("g")) + _f0(row.get("a"))), -(_f0(row.get("xg")) + _f0(row.get("xa"))))


_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count(n: int, noun: str) -> str:
    if n == 1:
        return f"{'an' if noun[0] in 'aeiou' else 'a'} {noun}"
    return f"{_WORDS.get(n, str(n))} {noun}s"


def _why(line: dict, row: dict) -> str:
    """'9.1 rating, two goals and an assist in a 3-1 win at Brighton'."""
    rt = _f0(line.get("rt"))
    gf, ga = line.get("gf"), line.get("ga")
    result = ""
    if gf is not None and ga is not None:
        res = "win" if gf > ga else "draw" if gf == ga else "defeat"
        venue = f"at {line['opp']}" if line.get("ha") == "A" else f"at home to {line['opp']}"
        result = f" in a {gf}-{ga} {res} {venue}"
    parts = []
    if line.get("pos") == "G":
        sv = _int(row.get("sv"))
        if sv:
            parts.append(_count(sv, "save"))
        gp = _num(row.get("gp"))
        if gp is not None and gp >= 0.5:
            parts.append(f"{gp:.2f} goals prevented")
    else:
        if line.get("g"):
            parts.append(_count(line["g"], "goal"))
        if line.get("a"):
            parts.append(_count(line["a"], "assist"))
        if not parts:
            involvement = _f0(line.get("xg")) + _f0(line.get("xa"))
            if involvement >= 0.5:
                parts.append(f"{involvement:.2f} xG + xA")
    if parts:
        return f"{rt:.1f} rating, {' and '.join(parts)}{result}"
    return f"{rt:.1f} rating{result}"


# ── rounds ───────────────────────────────────────────────────────────────────

def _week_key(date) -> str | None:
    """'w2026-38' for a kickoff in ISO week 38 of 2026; None without a parseable date."""
    from datetime import date as _date

    try:
        d = _date.fromisoformat(str(date)[:10])
    except (TypeError, ValueError):
        return None
    y, w, _ = d.isocalendar()
    return f"w{y}-{w:02d}"


def _week_label(key: str) -> str:
    from datetime import date as _date

    y, w = int(key[1:5]), int(key[6:8])
    monday = _date.fromisocalendar(y, w, 1)
    return f"{monday.day} {monday.strftime('%b')}"


def _round_groups(fixtures: list[dict], round_labels: dict | None) -> list[dict]:
    """The rounds with a finished match, newest first: league and group stages as 'Round N', knockout rounds by label."""
    groups: dict[tuple[str, str], dict] = {}
    for f in fixtures or []:
        if not isinstance(f, dict) or f.get("status") != "finished":
            continue
        stage = str(f.get("stage") or "league")
        if stage == "qualifying":
            continue
        rnd = f.get("round")
        if rnd is None:
            # Sofascore gives no round for MLS, many national cups and the
            # national-team calendars: group those by calendar week instead.
            wk = _week_key(f.get("date"))
            if wk is None:
                continue
            rnd = wk
        g = groups.setdefault((stage, str(rnd)), {"round": rnd, "stage": stage, "gids": set(), "dates": []})
        g["gids"].add(str(f.get("id")))
        if f.get("date"):
            g["dates"].append(str(f["date"]))
    labels = round_labels or {}
    out = []
    for g in groups.values():
        rnd = g["round"]
        if isinstance(rnd, str) and rnd.startswith("w") and len(rnd) == 8:
            label = f"Week of {_week_label(rnd)}"
        else:
            label = (labels.get(str(rnd)) or f"Round {rnd}") if g["stage"] == "playoff" else f"Round {rnd}"
        dates = sorted(g["dates"])
        out.append({"round": rnd, "stage": g["stage"], "label": label,
                    "dates": [dates[0], dates[-1]] if dates else [None, None], "gids": g["gids"]})
    out.sort(key=lambda g: (g["dates"][1] or "", str(g["round"])), reverse=True)
    return out


def _log_rows_by_gid(logs: dict, positions: dict[str, str]) -> dict[str, list[tuple[str, dict, dict, str]]]:
    out: dict[str, list[tuple[str, dict, dict, str]]] = {}
    for pid, entry in (logs or {}).items():
        if not isinstance(entry, dict):
            continue
        for row in entry.get("matches") or []:
            if not isinstance(row, dict) or row.get("gid") is None:
                continue
            pos = _pos(row.get("pos") or entry.get("pos") or positions.get(str(pid)))
            out.setdefault(str(row["gid"]), []).append((str(pid), entry, row, pos))
    return out


def team_of_week(rows: list[tuple[str, dict, dict, str]]) -> dict:
    """{"formation", "xi", "bench"} from the round's log rows (pid, entry, row, pos)."""
    best: dict[str, tuple] = {}
    for pid, entry, row, pos in rows:
        if _f0(row.get("min")) < TOTW_MINUTES or _num(row.get("rt")) is None:
            continue
        key = _rank_key(row)
        if pid not in best or key < best[pid][0]:
            best[pid] = (key, entry, row, pos)
    candidates = [{"pos": pos, "score": _f0(row.get("rt")), "key": key + (entry.get("name") or "",),
                   "line": _line_from_log(pid, entry, row, pos)}
                  for pid, (key, entry, row, pos) in best.items()]
    formation, xi, bench = pick_formation(candidates)
    return {"formation": formation, "xi": xi, "bench": bench}


def player_of_week(rows: list[tuple[str, dict, dict, str]]) -> dict | None:
    pool = [(pid, entry, row, pos) for pid, entry, row, pos in rows
            if _f0(row.get("min")) >= POTW_MINUTES and _num(row.get("rt")) is not None]
    if not pool:
        return None
    pid, entry, row, pos = min(pool, key=lambda t: _rank_key(t[2]) + (t[1].get("name") or "",))
    line = _line_from_log(pid, entry, row, pos)
    line["why"] = _why(line, row)
    return line


def round_awards(rows: list[tuple[str, dict, dict, str]]) -> dict[str, dict]:
    """finisher, creator, wall, engine, ball_winner; a key is absent when nobody qualifies."""
    played = [(pid, entry, row, pos) for pid, entry, row, pos in rows if _f0(row.get("min")) > 0]

    def best(name: str, label: str, qualifies, value, tie=lambda row: 0.0) -> None:
        pool = [(value(row), tie(row), pid, entry, row, pos) for pid, entry, row, pos in played if qualifies(row, pos)]
        if not pool:
            return
        v, _, pid, entry, row, pos = max(pool, key=lambda t: (t[0], t[1], -_f0(t[4].get("min"))))
        line = _line_from_log(pid, entry, row, pos)
        line["value"] = _r(v)
        line["label"] = label
        out[name] = line

    out: dict[str, dict] = {}
    best("finisher", "Goals − xG", lambda r, p: _f0(r.get("g")) >= 1, lambda r: _f0(r.get("g")) - _f0(r.get("xg")), lambda r: _f0(r.get("g")))
    best("creator", "xA", lambda r, p: _f0(r.get("a")) >= 1 or _f0(r.get("xa")) >= 0.3, lambda r: _f0(r.get("xa")), lambda r: _f0(r.get("kp")))
    best("wall", "Goals prevented", lambda r, p: p == "G" and _f0(r.get("min")) >= WALL_MINUTES and _num(r.get("gp")) is not None,
         lambda r: _f0(r.get("gp")), lambda r: _f0(r.get("sv")))
    best("engine", "Distance (km)", lambda r, p: _f0(r.get("km")) > 0, lambda r: _f0(r.get("km")))
    # Outfield only: a goalkeeper's recoveries are every loose ball in his own box.
    best("ball_winner", "Ball wins", lambda r, p: p != "G" and _f0(r.get("tw")) + _f0(r.get("int")) + _f0(r.get("rec")) > 0,
         lambda r: _f0(r.get("tw")) + _f0(r.get("int")) + _f0(r.get("rec")))
    return out


def _team_rows_by_gid(by_team: dict[str, list[dict]]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for team, rows in (by_team or {}).items():
        for r in rows or []:
            if isinstance(r, dict) and r.get("gid") is not None:
                out.setdefault(str(r["gid"]), {})[team] = r
    return out


def _match_line(team: str, r: dict, opp_row: dict | None) -> dict | None:
    """A team's match as (xg, xga, gf, ga, pts, xpts); None without xG both ways."""
    xg = _num(r.get("xg"))
    xga = _num(r.get("xga"))
    if xga is None and opp_row:
        xga = _num(opp_row.get("xg"))
    gf, ga = _num(r.get("gf")), _num(r.get("ga"))
    res = r.get("res") or (None if gf is None or ga is None else "W" if gf > ga else "D" if gf == ga else "L")
    pts = PTS.get(res)
    xp = expected_points(xg, xga) if xg is not None and xga is not None else None
    return {"team": team, "opp": r.get("opp"), "ha": r.get("ha"), "gid": str(r.get("gid")), "date": r.get("date"),
            "round": r.get("round"), "gf": r.get("gf"), "ga": r.get("ga"), "res": res, "pts": pts,
            "xg": xg, "xga": xga, "xpts": xp["xpts"] if xp else None}


def team_awards(gids: set[str], team_rows: dict[str, dict[str, dict]]) -> dict[str, dict]:
    """best_xg_diff, luckiest, unluckiest, smash_and_grab over the round's team rows."""
    lines = []
    for gid in gids:
        sides = team_rows.get(gid) or {}
        for team, r in sides.items():
            opp = next((o for t, o in sides.items() if t != team), None)
            lines.append(_match_line(team, r, opp))

    def award(m: dict, value: float) -> dict:
        return {"team": m["team"], "opp": m["opp"], "ha": m["ha"], "gf": m["gf"], "ga": m["ga"],
                "xg": _r(m["xg"]), "xga": _r(m["xga"]), "value": _r(value), "gid": m["gid"]}

    out: dict[str, dict] = {}
    with_xg = [m for m in lines if m["xg"] is not None and m["xga"] is not None]
    if with_xg:
        m = max(with_xg, key=lambda m: (m["xg"] - m["xga"], m["xg"]))
        out["best_xg_diff"] = award(m, m["xg"] - m["xga"])
    with_pts = [m for m in with_xg if m["pts"] is not None and m["xpts"] is not None]
    if with_pts:
        lucky = max(with_pts, key=lambda m: m["pts"] - m["xpts"])
        unlucky = min(with_pts, key=lambda m: m["pts"] - m["xpts"])
        out["luckiest"] = award(lucky, lucky["pts"] - lucky["xpts"])
        out["unluckiest"] = award(unlucky, unlucky["pts"] - unlucky["xpts"])
    wins = [(m["xg"] / (m["xg"] + m["xga"]), m) for m in with_xg if m["res"] == "W" and (m["xg"] + m["xga"]) > 0]
    wins = [(s, m) for s, m in wins if s < 0.4]
    if wins:
        share, m = min(wins, key=lambda t: t[0])
        out["smash_and_grab"] = award(m, share)
    return out


def build_rounds(fixtures: list[dict], logs: dict, by_team: dict, positions: dict[str, str], round_labels: dict | None) -> list[dict]:
    groups = _round_groups(fixtures, round_labels)
    if not groups:
        return []
    log_rows = _log_rows_by_gid(logs, positions)
    team_rows = _team_rows_by_gid(by_team)
    out = []
    for g in groups:
        rows = [t for gid in g["gids"] for t in log_rows.get(gid, [])]
        if not rows and not any(gid in team_rows for gid in g["gids"]):
            continue
        out.append({
            "round": g["round"], "stage": g["stage"], "label": g["label"], "dates": g["dates"], "matches": len(g["gids"]),
            "team_of_week": _safe("team of the week", lambda: team_of_week(rows), {"formation": None, "xi": [], "bench": []}),
            "player_of_week": _safe("player of the week", lambda: player_of_week(rows), None),
            "awards": _safe("awards", lambda: round_awards(rows), {}),
            "team_awards": _safe("team awards", lambda: team_awards(g["gids"], team_rows), {}),
        })
    return out


# ── season XIs ───────────────────────────────────────────────────────────────

def _player_pos(p: dict) -> str:
    if p.get("is_gk"):
        return "G"
    return _pos(p.get("position"))


def _qualified(players: list[dict], floor: int) -> list[dict]:
    return [p for p in players or [] if isinstance(p, dict)
            and (p["qualified"] if "qualified" in p else _f0(p.get("minutes")) >= floor)]


def _xi(candidates: list[dict], basis: str) -> dict:
    formation, xi, _ = pick_formation(candidates)
    return {"formation": formation, "xi": xi, "basis": basis}


def season_xis(players: list[dict], logs: dict, floor: int) -> dict[str, dict]:
    qualified = _qualified(players, floor)

    def cands(value_of: Callable[[dict, str], tuple[float | None, float]]) -> list[dict]:
        out = []
        for p in qualified:
            pos = _player_pos(p)
            value, tie = value_of(p, pos)
            if value is None:
                continue
            out.append({"pos": pos, "score": value, "key": (-value, -tie, -_f0(p.get("minutes")), p.get("name") or ""),
                        "line": _season_line(p, pos, value)})
        return out

    def rating(p, pos):
        return _num(p.get("rating")), _f0(p.get("minutes"))

    def output(p, pos):
        key = "goals_prevented_90" if pos == "G" else "npxg_xa_90"
        return _num(p.get(key)), _f0(p.get("goals")) + _f0(p.get("assists"))

    def defence(p, pos):
        if pos == "G":
            return _num(p.get("goals_prevented_90")), 0.0
        if pos == "F":
            return _num(p.get("def_actions_90")), _f0(p.get("ball_wins_90"))
        return _num(p.get("padj_tkl_int_90")), _f0(p.get("ball_wins_90"))

    by_id = {str(p.get("player_id")): p for p in players or [] if isinstance(p, dict)}

    def form_candidates() -> list[dict]:
        out = []
        for pid, entry in (logs or {}).items():
            if not isinstance(entry, dict):
                continue
            rated = [_num(r.get("rt")) for r in entry.get("matches") or [] if isinstance(r, dict) and _num(r.get("rt")) is not None
                     and _f0(r.get("min")) > 0]
            if len(rated) < FORM_XI_MIN_MATCHES:
                continue
            recent = rated[:FORM_XI_MATCHES]           # rows are newest first
            value = sum(recent) / len(recent)
            p = by_id.get(str(pid)) or {"player_id": pid, "name": entry.get("name"), "team": entry.get("team"),
                                        "minutes": sum(_f0(r.get("min")) for r in entry.get("matches") or [])}
            pos = _player_pos(p) if p.get("position") or p.get("is_gk") else _pos(entry.get("pos"))
            line = _season_line(p, pos, value)
            line["team"] = entry.get("team") or line["team"]
            out.append({"pos": pos, "score": value, "key": (-value, -len(rated), p.get("name") or ""), "line": line})
        return out

    return {
        "rating": _safe("rating XI", lambda: _xi(cands(rating), "minutes-weighted rating"), _xi([], "minutes-weighted rating")),
        "output": _safe("output XI", lambda: _xi(cands(output), "npxG + xA per 90 (goalkeepers: goals prevented per 90)"),
                        _xi([], "npxG + xA per 90")),
        "defence": _safe("defence XI", lambda: _xi(cands(defence), "possession-adjusted tackles + interceptions per 90 "
                                                                    "(forwards: defensive actions per 90; goalkeepers: goals prevented per 90)"),
                         _xi([], "possession-adjusted tackles + interceptions per 90")),
        "form": _safe("form XI", lambda: _xi(form_candidates(), f"mean rating over the last {FORM_XI_MATCHES} matches"),
                      _xi([], f"mean rating over the last {FORM_XI_MATCHES} matches")),
    }


# ── performers ───────────────────────────────────────────────────────────────

def player_performers(players: list[dict], floor: int) -> dict[str, dict]:
    catalogue = {m["key"]: m for m in METRICS}
    qualified = _qualified(players, floor)
    out: dict[str, dict] = {}
    for key in PERFORMER_KEYS:
        m = catalogue.get(key)
        if not m:
            continue
        gk = m.get("scope") == "gk"
        lower = bool(m.get("lower"))
        pool = [p for p in qualified if bool(p.get("is_gk")) == gk and _num(p.get(key)) is not None]
        ranked = sorted(pool, key=lambda p: ((1 if lower else -1) * float(p[key]), -_f0(p.get("minutes")), p.get("name") or ""))

        def perf(p: dict) -> dict:
            pct = (p.get("pct") or {}).get(key) if isinstance(p.get("pct"), dict) else None
            return {"id": str(p.get("player_id")), "name": p.get("name") or "", "team": p.get("team") or "",
                    "pos": _player_pos(p), "value": _r(p.get(key)), "minutes": _int(p.get("minutes")), "pct": pct}

        out[key] = {"label": m["label"], "fmt": m.get("fmt"), "lower": lower, "scope": "gk" if gk else "out",
                    "top": [perf(p) for p in ranked[:PERF_N]], "bottom": [perf(p) for p in ranked[::-1][:PERF_N]]}
    return out


# ── team metrics ─────────────────────────────────────────────────────────────

def team_metric_values(rows: list[dict], opp_of: Callable[[dict], dict | None]) -> dict[str, float | None]:
    """
    A team's per-match profile over its played matches. Simple quantities are
    averaged over the matches where they exist; ratios are built from summed
    numerators and denominators over the matches where both exist.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    pairs: dict[str, list[float]] = {}

    def add(key: str, v) -> None:
        f = _num(v)
        if f is None:
            return
        sums[key] = sums.get(key, 0.0) + f
        counts[key] = counts.get(key, 0) + 1

    def pair(key: str, num, den) -> None:
        a, b = _num(num), _num(den)
        if a is None or b is None:
            return
        acc = pairs.setdefault(key, [0.0, 0.0])
        acc[0] += a
        acc[1] += b

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        opp = opp_of(r) or {}
        m = _match_line("", r, opp)
        xg, xga = m["xg"], m["xga"]
        add("xg", xg)
        add("xga", xga)
        if xg is not None and xga is not None:
            add("xgd", xg - xga)
        add("gf", m["gf"])
        add("ga", m["ga"])
        if xg is not None and m["gf"] is not None:
            add("fin", _f0(m["gf"]) - xg)
        if xga is not None and m["ga"] is not None:
            add("keep", xga - _f0(m["ga"]))
        if m["xpts"] is not None:
            add("xpts", m["xpts"])
            if m["pts"] is not None:
                add("luck", m["pts"] - m["xpts"])
        add("poss", r.get("poss"))
        own_box, opp_box = _num(r.get("box_touches")), _num(opp.get("box_touches"))
        if own_box is not None and opp_box is not None:
            pair("tilt", own_box, own_box + opp_box)
        tk, ic, fl = _num(r.get("tackles")), _num(r.get("interceptions")), _num(r.get("fouls"))
        if None not in (tk, ic, fl) and _num(opp.get("passes")) is not None:
            pair("ppda", opp.get("passes"), tk + ic + fl)
        shots = _num(r.get("shots"))
        shots_ag = _num(r.get("shots_ag"))
        if shots_ag is None:
            shots_ag = _num(opp.get("shots"))
        add("shots", shots)
        add("shots_ag", shots_ag)
        pair("sq", xg, shots)
        pair("sqa", xga, shots_ag)
        pair("sot", r.get("sot"), shots)
        add("big_chances", r.get("big_chances"))
        add("big_chances_missed", r.get("big_chances_missed"))
        add("corners", r.get("corners"))
        pair("aerial", r.get("aerial_won"), r.get("aerial_total"))
        pair("ground", r.get("ground_won"), r.get("ground_total"))
        add("passes", r.get("passes"))
        pair("pass", r.get("passes_acc"), r.get("passes"))
        pair("long", r.get("long_balls_att"), r.get("passes"))
        add("crosses", r.get("crosses_att") if r.get("crosses_att") is not None else r.get("crosses"))
        add("dribbles", r.get("dribbles"))
        add("fouls", fl)
        yellow = _num(r.get("yellow"))
        if yellow is not None:
            add("cards", yellow + 2.0 * _f0(r.get("red")))
        add("km", r.get("km"))
        add("sprints", r.get("sprints"))
        add("rating", r.get("rating"))

    def mean(key: str):
        return sums[key] / counts[key] if counts.get(key) else None

    def ratio(key: str, scale: float = 1.0):
        acc = pairs.get(key)
        return scale * acc[0] / acc[1] if acc and acc[1] > 0 else None

    return {
        "xg_for": mean("xg"), "xg_against": mean("xga"), "xg_diff": mean("xgd"),
        "goals_for": mean("gf"), "goals_against": mean("ga"), "finishing": mean("fin"), "keeping": mean("keep"),
        "xpts_per_match": mean("xpts"), "luck": mean("luck"), "possession": mean("poss"),
        "field_tilt": ratio("tilt", 100.0), "ppda": ratio("ppda"),
        "shots": mean("shots"), "shots_against": mean("shots_ag"), "shot_quality": ratio("sq"), "shot_quality_against": ratio("sqa"),
        "sot_pct": ratio("sot", 100.0), "big_chances": mean("big_chances"), "big_chances_missed": mean("big_chances_missed"),
        "corners": mean("corners"), "aerial_pct": ratio("aerial", 100.0), "ground_duel_pct": ratio("ground", 100.0),
        "passes": mean("passes"), "pass_pct": ratio("pass", 100.0), "long_ball_share": ratio("long", 100.0),
        "crosses": mean("crosses"), "dribbles": mean("dribbles"), "fouls": mean("fouls"), "cards": mean("cards"),
        "km": mean("km"), "sprints": mean("sprints"), "rating": mean("rating"),
    }


def percentile_ranks(values: dict[str, float], lower: bool = False) -> dict[str, int]:
    """Rank-based 0-100 percentiles, direction-aware: 100 is always the best value, 0 the worst."""
    clean = {k: f for k, f in ((k, _num(v)) for k, v in values.items()) if f is not None}
    n = len(clean)
    if n < 2:
        return {}
    vals = sorted(clean.values())
    out = {}
    for k, v in clean.items():
        below = sum(1 for x in vals if x < v)
        ties = sum(1 for x in vals if x == v)
        rank = (below + 0.5 * (ties - 1)) / (n - 1)
        if lower:
            rank = 1.0 - rank
        out[k] = int(round(100 * rank))
    return out


def team_profiles(by_team: dict[str, list[dict]]) -> tuple[dict[str, dict], dict[str, dict]]:
    """(teams block, team performers) from the team match rows."""
    team_rows = _team_rows_by_gid(by_team)

    def opp_of(team: str):
        return lambda r: next((o for t, o in (team_rows.get(str(r.get("gid"))) or {}).items() if t != team), None)

    values: dict[str, dict[str, float | None]] = {}
    teams: dict[str, dict] = {}
    for team, rows in (by_team or {}).items():
        rows = [r for r in rows or [] if isinstance(r, dict)]
        values[team] = _safe(f"{team} metrics", lambda: team_metric_values(rows, opp_of(team)), {})
        lines = [_match_line(team, r, opp_of(team)(r)) for r in rows]
        newest = sorted(lines, key=lambda m: (str(m.get("date") or ""), m["gid"]), reverse=True)
        teams[team] = {
            "played": len(rows),
            "profile": {},
            "form": [{"gid": m["gid"], "date": m["date"], "opp": m["opp"], "ha": m["ha"], "gf": m["gf"], "ga": m["ga"], "res": m["res"],
                      "xg": _r(m["xg"]), "xga": _r(m["xga"]), "xpts": _r(m["xpts"]), "pts": m["pts"]} for m in newest[:FORM_MATCHES]],
            "rounds": [{"round": m["round"], "pts": m["pts"], "xpts": _r(m["xpts"]), "xg": _r(m["xg"]), "xga": _r(m["xga"])}
                       for m in reversed(newest)],
        }
    performers: dict[str, dict] = {}
    if not any(v.get(m["key"]) is not None for v in values.values() for m in TEAM_METRICS):
        return teams, performers                    # no team sheets and no xG: nothing to rank
    for m in TEAM_METRICS:
        key = m["key"]
        col = {t: v.get(key) for t, v in values.items() if v.get(key) is not None}
        pct = percentile_ranks(col, bool(m.get("lower")))
        for t, v in col.items():
            teams[t]["profile"][key] = {"v": _r(v), "pct": pct.get(t)}
        ranking = sorted(col.items(), key=lambda kv: ((1 if m.get("lower") else -1) * kv[1], kv[0]))
        performers[key] = {"label": m["label"], "fmt": m["fmt"], "lower": bool(m.get("lower")),
                           "ranking": [{"team": t, "value": _r(v), "pct": pct.get(t)} for t, v in ranking]}
    return teams, performers


# ── the payload ──────────────────────────────────────────────────────────────

def _empty(floor: int, season, updated_at: str) -> dict:
    return {
        "updated_at": updated_at, "minutes_floor": int(floor or 0), "season": season, "rounds": [],
        "season_xi": {k: {"formation": None, "xi": [], "basis": b} for k, b in (
            ("rating", "minutes-weighted rating"), ("output", "npxG + xA per 90"),
            ("defence", "possession-adjusted tackles + interceptions per 90"), ("form", f"mean rating over the last {FORM_XI_MATCHES} matches"))},
        "performers": {"players": {}, "teams": {}}, "teams": {},
        "team_metrics": TEAM_METRICS, "player_metrics": list(PERFORMER_KEYS),
    }


def build_analytics(players: list[dict], logs: dict, by_team: dict, fixtures: list[dict], floor: int | None = None,
                    season: str | None = None, round_labels: dict | None = None, updated_at: str | None = None) -> dict:
    """
    analytics.json for one competition. `players` are the season rows (with
    `qualified` and `pct` when percentiles have been added), `logs` the match
    logs by player id, `by_team` the team match rows, `fixtures` the season's
    fixture rows (`status`, `round`, `stage`, `date`, `id`). Never raises.
    """
    updated_at = updated_at or _now()
    try:
        players = [p for p in players or [] if isinstance(p, dict)]
        if floor is None:
            floor = minutes_floor(players) if players else 0
        payload = _empty(int(floor), season, updated_at)
        positions = {str(p.get("player_id")): _player_pos(p) for p in players}
        payload["rounds"] = _safe("rounds", lambda: build_rounds(fixtures, logs, by_team, positions, round_labels), [])
        payload["season_xi"] = _safe("season XIs", lambda: season_xis(players, logs, int(floor)), payload["season_xi"])
        payload["performers"]["players"] = _safe("player performers", lambda: player_performers(players, int(floor)), {})
        teams, team_perf = _safe("team profiles", lambda: team_profiles(by_team), ({}, {}))
        payload["teams"] = teams
        payload["performers"]["teams"] = team_perf
        payload["player_metrics"] = [k for k in PERFORMER_KEYS if k in payload["performers"]["players"]] or list(PERFORMER_KEYS)
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.error("analytics payload failed: %s", exc)
        return _empty(int(floor or 0), season, updated_at)
