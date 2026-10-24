"""
umpires.json (per level and season): builder C's umpire tables (accuracy against the rulebook zone, accuracy
expected from the difficulty of his pitches, consistency with his own zone, zone size, run impact of missed
calls) with direction-aware percentiles among umpires with 500+ called pitches, each umpire's game scorecards,
and the season's ABS challenge analytics (2026).
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext, frame_rows

M = an.metric
MIN_CALLED = 500
METRICS = [
    M("games", "Games", "Umpire", "int", desc="Games behind the plate."),
    M("called", "Called pitches", "Umpire", "int", desc="Called pitches (balls and called strikes) with a location."),
    M("accuracy", "Accuracy", "Umpire", "pct", desc="Calls matching the rulebook zone (plate half-width plus a ball radius; the batter's "
      "zone top and bottom +/- 0.12 ft)."),
    M("x_accuracy", "Expected accuracy", "Umpire", "pct", desc="Accuracy the league surface (without the umpire's effect) would have had on the pitches the umpire called."),
    M("acc_above_x", "Accuracy above expected", "Umpire", "pct", desc="Accuracy minus expected accuracy."),
    M("consistency", "Consistency", "Umpire", "pct", desc="Calls agreeing with the umpire's own fitted zone (league surface plus the umpire's effect)."),
    M("zone_per100", "Zone size (+strikes/100)", "Umpire", "2", desc="Called strikes above the league expectation per 100 called pitches."),
    M("missed_per_game", "Missed calls/game", "Umpire", "2", lower=True, desc="Missed calls per game."),
    M("runs_per_game", "Run impact/game", "Umpire", "2", lower=True, desc="Absolute run-expectancy swing of missed calls per game."),
    M("effect", "Zone effect (log-odds)", "Umpire", "3", desc="The umpire's random effect in the called-strike model (+ = more strikes)."),
]


def build(ctx: SeasonContext) -> dict:
    u = ctx.model("umpire")
    if not u.get("ok"):
        return {"ok": False, "reason": f"umpire model: {u.get('reason')}", "level": ctx.level, "season": ctx.season}
    tab = frame_rows(u.get("umpires"))
    sc = frame_rows(u.get("scorecards"))
    names = ctx.store.get("umpires") or {}
    rows: dict[str, dict] = {}
    if tab is not None:
        for r in tab.to_dict("records"):
            pid = str(r.get("pid"))
            rows[pid] = {"name": (names.get(pid) or {}).get("name") or pid, "values": {m["key"]: r.get(m["key"]) for m in METRICS},
                         "qualified": (r.get("called") or 0) >= MIN_CALLED}
    ref = [p for p, r in rows.items() if r["qualified"]]
    for m in METRICS:
        if m["fmt"] == "int":
            continue
        refv = sorted(an.fnum(rows[p]["values"].get(m["key"])) for p in ref if an.fnum(rows[p]["values"].get(m["key"])) is not None)
        for p, r in rows.items():
            v = an.fnum(r["values"].get(m["key"]))
            if v is not None and len(refv) >= 2 and r["qualified"]:
                r.setdefault("pct", {})[m["key"]] = an._place(refv, v, m["lower"])
    for r in rows.values():
        r["values"] = an.round_values(r["values"], METRICS)
        r.setdefault("pct", {})
        r["games_list"] = []
    gpk_of = {}
    if sc is not None:
        for r in sc.to_dict("records"):
            uid = str(r.get("ump")) if r.get("ump") is not None else None
            gpk = str(int(r["game_pk"])) if r.get("game_pk") is not None else None
            row = [gpk, str(r.get("date"))[:10], r.get("home"), r.get("away"), an.inum(r.get("called")), an.inum(r.get("missed")),
                   an.rnd(r.get("accuracy"), 4), an.rnd(r.get("x_accuracy"), 4), an.rnd(r.get("home_favour"), 3), r.get("favoured") or None,
                   an.rnd(r.get("total_impact"), 3)]
            if uid in rows:
                rows[uid]["games_list"].append(row)
            gpk_of[gpk] = uid
    for r in rows.values():
        r["games_list"].sort(key=lambda x: str(x[1]))
    abs_ = named_abs(ctx, u.get("abs") or {}, names)
    return {**CT.season_meta(ctx), "metrics": [an.public_metric(m) for m in METRICS], "umpires": rows,
            "games_cols": ["gpk", "date", "home", "away", "called", "missed", "accuracy", "x_accuracy", "home_favour", "favoured", "impact"],
            "league": u.get("league"), "abs": abs_, "min_called": MIN_CALLED}


def _add_col(tab: dict | None, key: str, new: str, fn) -> dict | None:
    """A copy of a {"cols", "rows"} table with column `new` = fn(value of column `key`) appended (once)."""
    if not isinstance(tab, dict) or key not in (tab.get("cols") or []) or new in tab["cols"]:
        return tab
    i = tab["cols"].index(key)
    return {**tab, "cols": list(tab["cols"]) + [new], "rows": [list(r) + [fn(r[i]) if len(r) > i else None] for r in tab.get("rows") or []]}


def named_abs(ctx: SeasonContext, abs_: dict, umpires: dict | None = None) -> dict:
    """The ABS tables with names: challengers, best and worst gain the player's `name` (store, then the people index),
    teams the team id `tid` (the tables carry Savant abbreviations) and umpires the umpire's `name`, so the page never
    falls back to a bare id."""
    if not isinstance(abs_, dict) or not abs_:
        return abs_
    out = dict(abs_)

    def pname(pid):
        if pid in (None, ""):
            return None
        n = ctx.name(str(pid))
        return n if n and n != str(pid) else None

    def tid(a):
        if a in (None, ""):
            return None
        return ctx.tid(a) or (str(a) if str(a) in ctx.teams else None)
    for k in ("challengers", "best", "worst"):
        if k in out:
            out[k] = _add_col(out[k], "challenger", "name", pname)
    for k, col in (("teams", "team"), ("by_batting_team", "bat_team")):
        if k in out:
            out[k] = _add_col(out[k], col, "tid", tid)
    um = umpires or {}
    if "umpires" in out:
        out["umpires"] = _add_col(out["umpires"], "ump", "name", lambda x: (um.get(str(x)) or {}).get("name") if x is not None else None)
    return out


def profiles(payload: dict | None) -> dict[str, dict]:
    """{umpire id: raw season values} for game pages."""
    return {k: v.get("values") or {} for k, v in ((payload or {}).get("umpires") or {}).items()}
