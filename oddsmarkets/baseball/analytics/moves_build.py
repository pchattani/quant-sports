"""
Builds the valuation v2 context and writes the transactions and trade-rating payloads (MLB; called by value_build.py):

    mlb/moves.json      the last twelve months of moves (trades, signings, call-ups, options, injured-list moves, releases
                        ...) as facts, every club's counts, who is on the injured list now
    mlb/trades.json     every trade of the last twelve months rated for each club (value at the time, realised since,
                        grades, the winner), the clubs' net over the window, and the model's validation
    cache value/valuation_<L>.json   the fits value.json's valuation v2 fields use (horizons, bands, injured list,
                        prospects), and the prospect fit Triple-A reuses

Transactions come from the MLB Stats API through analytics/mlbapi.py (cached; refreshed when the build may use the
network, `cfg["statsapi"]`). Only facts and our own numbers are written; the API's text is not.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import mlbapi
from oddsmarkets.baseball.analytics import moves as M
from oddsmarkets.baseball.analytics import trade_ratings as TRR
from oddsmarkets.baseball.analytics import valuation as VA
from oddsmarkets.baseball.analytics import value as V

log = logging.getLogger(__name__)
TX_FIRST = date(2014, 10, 1)
SOURCE = ("MLB Stats API (statsapi.mlb.com), MLB Advanced Media's public API and already the site's source of schedules, "
          "rosters and injured lists. Its notice permits individual, non-commercial, non-bulk use; the site is "
          "non-commercial, the calls are paced and cached, and only facts (dates, clubs, players, the kind of move) and our "
          "own numbers are shown, never MLBAM's text. Contracts and salaries are not shown: no source with terms that allow "
          "our use has them (Spotrac, Cot's Contracts, Baseball-Reference and FanGraphs forbid this kind of reuse).")


class Ctx:
    """What the value, moves, trades and fantasy payloads share for one build."""
    parsed: list[dict]
    trades: list[dict]
    stints: dict
    il: dict
    world: TRR.World
    fits: dict


def context(level: str, rows: dict[int, list[dict]], hist: dict, ks: dict, curves: dict, cfg: dict, today: date) -> Ctx:
    t0 = time.perf_counter()
    c = mlbapi.client(60) if cfg.get("statsapi") else None
    ctx = Ctx()
    raw = mlbapi.transactions(level, TX_FIRST, today, c, today=today)
    ctx.parsed = M.parse_all(raw)
    ctx.trades = M.trades(ctx.parsed)
    stores = {s: an.load_store(level, s) for s in sorted(rows)}
    bounds = M.season_bounds(stores)
    ctx.stints = M.il_stints(ctx.parsed)
    ctx.il = VA.il_table(M.il_days(ctx.stints, bounds, today))
    seasons = sorted(rows)
    hfit = VA.horizon_fit(hist, seasons, ks, curves, level)
    bfit = VA.band_fit(hist, seasons, ks, curves, hfit, level)
    ilfit = VA.il_fit(hist, ctx.il, seasons)
    splits = VA.Splits({s: VA.stint_table(level, s, stores[s]) for s in seasons})
    people = an.load_people()
    pids = {p["pid"] for t in ctx.trades for p in t["pieces"]}
    extra = mlbapi.people(pids, c)
    prows = VA.prospect_rows(VA.minor_lines(range(min(seasons), max(seasons) + 1)))
    pfit = VA.prospect_fit(prows, hist, people, max(seasons))
    W = TRR.World(hist, ks, curves, hfit, splits, stores, bounds, people, extra, prows, pfit)
    W.retention = TRR.retention_fit(W, ctx.trades, max(seasons) - 1)
    W.base = TRR.base_rates(W, ctx.trades)
    ctx.world = W
    ctx.fits = {"horizon": hfit, "band": bfit, "il": ilfit, "prospect": pfit, "retention": W.retention, "base": W.base}
    log.info("valuation context %s: %d transactions, %d trades, %.1f s", level, len(ctx.parsed), len(ctx.trades), time.perf_counter() - t0)
    if c is not None:
        log.info("statsapi: %s", c.report())
    return ctx


# ── valuation v2 fields for value.json ──────────────────────────────────────

V2_FIELDS = ["e1", "lo1", "hi1", "e3", "lo3", "hi3", "v5", "il3", "il_exp", "il_p30", "pos_line", "over_line"]


def v2_rows(ctx: Ctx, rows: list[dict], proj: dict, season: int, slot: dict, rpw: float) -> tuple[dict, dict]:
    """({(kind, pid): [V2_FIELDS values]}, meta): next season's expected WAR and 80% band, three seasons' with band, the
    five-season value, injured-list days (the last three seasons), next season's expected days and chance of 30+, the
    position's median-starter line and his wins over it."""
    W = ctx.world
    fits = ctx.fits
    lines = VA.scarcity(rows, proj, slot, rpw)
    use_pt = {k: bool(((fits["il"] or {}).get(k) or {}).get("validation", {}).get("pt_helps")) for k in ("H", "P")}
    out = {}
    for r in rows:
        kind, pid = r["kind"], r["pid"]
        pv = VA.player_valuation(kind, pid, proj.get(kind) or {}, W.hist, W.curves, fits["horizon"], fits["band"], ctx.il, fits["il"],
                                 season, use_pt)
        if pv is None:
            continue
        pos = r.get("pos")
        line = (lines.get(pos) or {}).get("line")
        p = (proj.get(kind) or {}).get(pid) or {}
        own = V.slot_value(r, pos, p.get("rate"), slot, rpw) if pos in V.POSITIONS else None
        out[(kind, pid)] = [an.rnd(pv["e1"], 2), an.rnd(pv["lo1"], 1), an.rnd(pv["hi1"], 1), an.rnd(pv["e3"], 2), an.rnd(pv["lo3"], 1),
                            an.rnd(pv["hi3"], 1), an.rnd(pv["value"], 2), pv["il_days"], an.rnd(pv["il_exp"], 0), an.rnd(pv["il_p30"], 2),
                            an.rnd(line, 2), an.rnd(own - line, 2) if own is not None and line is not None else None]
    meta = {"fields": V2_FIELDS, "discount": VA.DISCOUNT, "horizon": VA.HORIZON, "age_bands": [list(b) for b in VA.AGE_BANDS],
            "horizon_fit": fits["horizon"], "band_fit": fits["band"], "il_fit": fits["il"], "positions": lines,
            "il_in_playing_time": use_pt,
            "notes": ["Next season (e1) and three seasons (e3): expected WAR from the projection aged season by season and "
                      "calibrated on history (attrition, injuries and regression included); lo/hi: the 10th and 90th percentiles "
                      "of what players with that expectation went on to produce.",
                      "Value (v5): five seasons, discounted 8% a year; WAR is above replacement, so this is the surplus over a "
                      "freely available player. Salaries are not known (no legitimate free source), so it is not net of pay.",
                      "Injured list (il3): days in each of the last three seasons from the MLB Stats API transactions; il_exp and "
                      "il_p30: next season's expected days and the chance of 30 or more.",
                      "pos_line: the projected full-season value of the median starter (15th best) at the player's position; "
                      "over_line: his projected value there minus that line."]}
    return out, meta


def prospect_fields(ctx: Ctx, rows: list[dict], season: int) -> tuple[dict, dict]:
    """Triple-A value rows: {(kind, pid): [level of the line, z, expected MLB WAR over four seasons]} from the season's
    minor-league line (the prospect model), and the model's meta."""
    W = ctx.world
    out = {}
    for r in rows:
        pr = W.prows.get((season, r["kind"], r["pid"]))
        if not pr or VA._established(W.hist, r["kind"], r["pid"], season, W.people):
            continue
        pv = VA.prospect_value(W.pfit, r["kind"], pr)
        if pv is None:
            continue
        out[(r["kind"], r["pid"])] = [pr["level"], an.rnd(pr["z"], 2), an.rnd(pv, 2)]
    return out, {"fields": ["p_level", "p_z", "p_value"], "model": W.pfit}


# ── moves.json ──────────────────────────────────────────────────────────────

def moves_payload(ctx: Ctx, level: str, today: date, teams: dict) -> dict:
    lo = (today - timedelta(days=365)).isoformat()
    hi = today.isoformat()
    mlb = set(teams)
    rows = M.feed_rows(ctx.parsed, lo, hi, mlb)
    names = {}
    out_rows = []
    for d, k, pid, name, f, to, det in rows:
        if pid and name:
            names[pid] = name
        out_rows.append([d, k, pid, f if f in mlb else None, to if to in mlb else None, det])
    on = M.on_il(ctx.stints, today)
    il_now = []
    for pid, x in on.items():
        if x.get("club") not in mlb:
            continue
        il_now.append([pid, x.get("club"), x.get("il"), x.get("start"), x.get("part"), (today - date.fromisoformat(x["start"])).days + 1])
        nm = next((t.get("name") for t in reversed(ctx.parsed) if t.get("pid") == pid and t.get("name")), None)
        if nm:
            names[pid] = nm
    il_now.sort(key=lambda r: (str(r[1]), -r[5]))
    return {"ok": True, "level": level, "updated_at": an.now(), "window": [lo, hi], "fields": ["date", "kind", "pid", "from", "to", "detail"],
            "rows": out_rows, "names": names, "kinds": {k: M.LABEL.get(k, k) for k in M.FEED_KINDS}, "ledger": M.ledger_counts(rows, mlb),
            "il_now": il_now, "il_fields": ["pid", "club", "list", "start", "part", "days"], "teams": teams, "source": SOURCE,
            "notes": ["Facts from the MLB Stats API's transactions, parsed into the kind of move; minor-league contracts, "
                      "assignments within a system and number changes are left out.",
                      "Injured list: the list's length (10, 15 or 60 days; 7 for concussions), the date the placement is "
                      "retroactive to when it differs, and the body part (a category we read from the placement)."]}


# ── trades.json ─────────────────────────────────────────────────────────────

PIECE_FIELDS = ["pid", "name", "from", "to", "type", "kind", "age", "service", "value", "rest", "next", "realised", "detail"]


def trades_payload(ctx: Ctx, level: str, today: date, teams: dict, validation: dict | None = None) -> dict:
    W = ctx.world
    lo = (today - timedelta(days=365)).isoformat()
    rated = [TRR.rate(W, t) for t in ctx.trades if lo <= t["date"] <= today.isoformat() and any(c in teams for c in t["teams"])]
    out_trades = []
    table: dict[str, dict] = {t: {"n": 0, "in": 0.0, "out": 0.0, "net": 0.0, "r_in": 0.0, "r_out": 0.0, "r_net": 0.0, "won": 0, "lost": 0}
                              for t in teams}
    for r in rated:
        pcs = []
        for p in r["pieces"]:
            v = p["v"]
            det = ""
            if v["type"] == "prospect":
                det = f"{VA.MINOR_NAME.get(v.get('level'), v.get('level'))} {v.get('line_season')}, z {v.get('z'):+.1f}"
            elif v["type"] == "base":
                det = f"no MLB or minor-league line: age band {v.get('band')}"
            nxt = (v.get("path") or [None])[0] if v["type"] == "mlb" else None
            pcs.append([p["pid"], p.get("name"), p["from"], p["to"], v["type"], v.get("kind"), an.rnd(v.get("age"), 1), v.get("service"),
                        an.rnd(v["value"], 2), an.rnd(v.get("rest"), 2), an.rnd(nxt, 2), an.rnd(p["r"]["total"], 2), det])
        clubs = {c: {k: (an.rnd(x, 2) if isinstance(x, float) else x) for k, x in v.items()} for c, v in r["clubs"].items()}
        out_trades.append({"id": r["id"], "date": r["date"], "teams": r["teams"], "winner": r["winner"], "r_winner": r["r_winner"],
                           "clubs": clubs, "pieces": pcs})
        for c, v in r["clubs"].items():
            if c not in table:
                continue
            tb = table[c]
            tb["n"] += 1
            for k in ("in", "out", "net", "r_in", "r_out", "r_net"):
                tb[k] += v[k]
            tb["won"] += int(r["winner"] == c)
            tb["lost"] += int(r["winner"] is not None and r["winner"] != c)
    for tb in table.values():
        for k in ("in", "out", "net", "r_in", "r_out", "r_net"):
            tb[k] = round(tb[k], 2)
    out_trades.sort(key=lambda t: (t["date"], t["id"]), reverse=True)
    return {"ok": True, "level": level, "updated_at": an.now(), "window": [lo, today.isoformat()], "teams": teams, "trades": out_trades,
            "piece_fields": PIECE_FIELDS, "table": table, "grades": [[c, g] for c, g in TRR.GRADE_CUTS] + [[None, "F"]],
            "validation": validation, "retention": W.retention, "base_rates": W.base,
            "prospect_model": {k: ({kk: vv for kk, vv in (v or {}).items() if kk != "coef"} if v else None) for k, v in (W.pfit or {}).items()},
            "discount": VA.DISCOUNT, "source": SOURCE,
            "notes": ["Value at the time: expected Bullpen WAR for the club that received the player, from data before the trade "
                      "date only: the rest of the season and four more (five seasons between seasons), each later season "
                      "weighted by the chance he is still with the club and discounted 8% a year.",
                      "Retention stands in for contracts and club control, which no legitimate free source gives: of traded "
                      "players who played in the majors in a later season, the share who did so mainly for the club that "
                      "acquired them, by years since their MLB debut and by in-season or off-season trade.",
                      "Prospects: expected MLB WAR over four seasons from their latest minor-league season (level, age for the "
                      "level, performance, sample); players with no line: the average of traded players of their age band. "
                      "The model sees stat lines only, not scouting grades, and under-rates the very best prospects.",
                      "Realised: WAR produced for the club since the trade (the season split by plate appearances or batters "
                      "faced with the club, adjusted by his wOBA there against his season's).",
                      "Cash, players to be named later, bonus pool money and draft picks are listed but not valued.",
                      "Grades from the net expected value: A +2 wins or more, B +0.75, C within 0.75, D -0.75, F -2 or worse."]}
