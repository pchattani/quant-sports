"""
Writes the value section's and the trade simulator's payloads for a level (called by scripts/build_bullpen.py for
MLB and Triple-A and by npb/build.py for NPB):

    <L>/<S>/value.json          every season on disk: the leaderboard and the best at each position
    <L>/<S>/value/<tid>.json    the current season: strengths and needs, candidates, and the club's roster for the
                                trade simulator (MLB and NPB)
    <L>/<S>/trade.json          the current season, MLB and NPB: clubs, units, sensitivity curves
    valuation v2 (analytics/valuation.py, moves_build.py): the current season's value.json carries next season's and three
    seasons' expected WAR with bands, the five-season value, injured-list days and expectation, the position's
    median-starter line (MLB) and the prospect model's value (Triple-A); mlb/moves.json and mlb/trades.json (the
    transactions and the trade ratings) are written with them (`cfg["no_moves"]` skips all of it)

Inputs are payloads already on disk (the catalogues, players.json, teams.json, season.json) plus, for MLB and
Triple-A, position games from the pitch tables (cached). A payload is rewritten only when its content (all but
updated_at) changed, so an hourly build does not churn the deploy. The sensitivity curves are cached for a day
on their inputs (ratings, games played, phase), and reused for up to six hours when those change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import trade as TR
from oddsmarkets.baseball.analytics import value as V

log = logging.getLogger(__name__)
CURVE_TTL = 6 * 3600.0


def _sig(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            from oddsmarkets.baseball.models import _io as _pio
            h.update(_pio.path_sig(p).encode())      # path-independent: relative path, size, content digest
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def write_if_changed(b, rel: str, payload: dict) -> bool:
    """Write unless the file on disk holds the same payload apart from updated_at."""
    p = b.data / rel
    old = an.read_json(p) if p.exists() else None
    if isinstance(old, dict) and isinstance(payload, dict):
        a = {k: v for k, v in old.items() if k != "updated_at"}
        c = json.loads(json.dumps(an.clean({k: v for k, v in payload.items() if k != "updated_at"})))
        if a == c:
            return False
    b.write(rel, an.clean(payload))
    return True


def _cache_dir() -> Path:
    d = an.cache_root() / "value"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── MLB and Triple-A ────────────────────────────────────────────────────────

def posgames(level: str, season: int) -> dict[str, dict] | None:
    """{pid: {pos: games}} from the pitch table (models/war.defensive_games), cached on the Parquet file."""
    from oddsmarkets.baseball.models import _c, war
    path = an.pitch_path(level, season)
    cdir = _cache_dir()
    if not path.exists():
        olds = sorted(cdir.glob(f"posgames_{level}_{season}_*.json"))
        return an.read_json(olds[-1]) if olds else None
    key = _sig(path, war.MODEL_VERSION, V.VERSION)
    cp = cdir / f"posgames_{level}_{season}_{key}.json"
    got = an.read_json(cp)
    if got is not None:
        return got
    cols = ["game_pk", "at_bat_number", "inning_topbot", "home_team", "away_team", "batter"] + [f"fielder_{i}" for i in range(2, 10)]
    p = _c.load_pitches(level, season, cols)
    if p is None or not len(p):
        return None
    pa = p.drop_duplicates(["game_pk", "at_bat_number"]).copy()
    pa["half"] = (pa["inning_topbot"].astype(str).str.lower().str.startswith("bot")).astype(int)
    g = war.defensive_games(pa)
    out: dict[str, dict] = {}
    for pid, pos, games in g[["pid", "pos", "games"]].itertuples(index=False):
        name = V.POS_NUM.get(int(pos)) if str(pos).isdigit() else str(pos)
        if not name or pid is None:
            continue
        d = out.setdefault(str(pid), {})
        d[name] = round(d.get(name, 0.0) + float(games), 2)
    for old in cdir.glob(f"posgames_{level}_{season}_*.json"):
        old.unlink()
    an.write_json(cp, out)
    return out


def season_rows_mlb(b, level: str, season: int) -> list[dict] | None:
    sd = b.data / level / str(season)
    hp, pp = sd / "hitters.json", sd / "pitchers.json"
    key = _sig(hp, pp, V.VERSION, an.pitch_path(level, season))
    cp = _cache_dir() / f"rows_{level}_{season}_{key}.json"
    got = an.read_json(cp)
    if got is not None:
        return got
    hit, pit = an.read_json(hp), an.read_json(pp)
    if not (hit or {}).get("ok") and not (pit or {}).get("ok"):
        return None
    pg = None
    try:
        pg = posgames(level, season)
    except Exception as exc:                        # noqa: BLE001
        log.warning("position games %s %s: %s", level, season, exc)
    rows = V.rows_mlb(hit if (hit or {}).get("ok") else None, pit if (pit or {}).get("ok") else None, pg)
    for old in _cache_dir().glob(f"rows_{level}_{season}_*.json"):
        old.unlink()
    an.write_json(cp, an.clean(rows))
    return rows


def projections(hist: dict, seasons: list[int], level: str) -> tuple[dict, dict, dict]:
    """(k by kind, aging curves, the validation block), cached on the history."""
    key = _sig(V.VERSION, sorted((k, sorted(v.items())) for k, v in hist.items()))
    cp = _cache_dir() / f"proj_{level}_{key}.json"
    got = an.read_json(cp)
    if got:
        return got["k"], got["curve"], got["meta"]
    ks, curves, meta = {}, {}, {}
    for kind in ("H", "P"):
        f = V.fit_projection(hist, seasons, kind)
        ks[kind] = [f["k_final"], f["h_final"]]
        curves[kind] = V.aging_curve(hist, kind)
        meta[kind] = {"k": f["k_final"], "h": f["h_final"], "k_by_target": f["k"], "h_by_target": f["h"], "validation": f.get("validation"),
                      "aging": [round(c, 4) for c in curves[kind]]}
    for old in _cache_dir().glob(f"proj_{level}_*.json"):
        old.unlink()
    an.write_json(cp, {"k": ks, "curve": curves, "meta": meta})
    return ks, curves, meta


def proj_for(hist: dict, s: int, ks: dict, curves: dict, level: str, ext_curve: dict | None = None) -> dict:
    """{"H": {pid: {"rate", "war", "age"}}, "P": ...}: next season (s + 1) from seasons <= s."""
    out = {}
    for kind in ("H", "P"):
        cv = (ext_curve or {}).get(kind) or curves.get(kind) or [0.0, 0.0, 0.0]
        kh = ks.get(kind) or [1500.0, 0.0]
        kh = kh if isinstance(kh, (list, tuple)) else [float(kh), 0.0]
        pr = V.project(hist, s + 1, kind, kh[0], cv, kh[1])
        for pid, p in pr.items():
            h = hist.get(kind + ":" + pid) or {}
            if s not in h:
                continue
            pt = V.marcel_time(h, s, kind, level)
            p["war"] = p["rate"] * pt / V.UNIT[kind]
        out[kind] = {pid: p for pid, p in pr.items() if (hist.get(kind + ":" + pid) or {}).get(s)}
    return out


def contention_mlb(teams_payload: dict | None, phase: str | None) -> dict:
    out = {}
    for t, x in ((teams_payload or {}).get("teams") or {}).items():
        v = x.get("values") or {}
        pp = v.get("p_postseason")
        if pp is None:
            continue
        if phase in ("postseason", "offseason") and pp <= 0.0:
            out[t] = {"out": True, "why": "his club missed the postseason"}
        elif phase == "regular" and pp < 0.05:
            out[t] = {"out": True, "why": f"his club's postseason odds are {100 * pp:.1f}%"}
    return out


_CTX: dict = {}


def valuation_context(b, cfg: dict, today: date | None = None):
    """The MLB valuation context (moves_build.context), built once per build and shared with Triple-A."""
    from oddsmarkets.baseball.analytics import moves_build as MB
    today = today or cfg.get("today") or date.today()
    key = ("mlb", str(today))
    if key in _CTX:
        return _CTX[key]
    seasons = [s for s in an.seasons_on_disk("mlb") if (b.data / "mlb" / str(s) / "hitters.json").exists()]
    rows = {}
    for s in seasons:
        r = season_rows_mlb(b, "mlb", s)
        if r:
            rows[s] = r
    if not rows:
        return None
    hist = V.history_table(rows)
    ks, curves, _ = projections(hist, sorted(rows), "mlb")
    ctx = MB.context("mlb", rows, hist, ks, curves, cfg, today)
    ctx.rows = rows
    _CTX.clear()
    _CTX[key] = ctx
    return ctx


def _merge_fields(pay: dict, extra: dict, fields: list[str]) -> None:
    """Append fields to a value payload's rows ([pid, name, team, kind, ...]) from {(kind, pid): [values]}."""
    pay["fields"] = list(pay.get("fields") or []) + fields
    for row in pay.get("rows") or []:
        row.extend(extra.get((row[3], row[0])) or [None] * len(fields))


def build_level(b, level: str, current: int, cfg: dict, sims: int | None = None) -> dict:
    """MLB or Triple-A: value.json for every season with catalogues; team files and (MLB) the trade payloads for the
    current season."""
    t0 = time.perf_counter()
    seasons = [s for s in an.seasons_on_disk(level) if (b.data / level / str(s) / "hitters.json").exists()]
    rows: dict[int, list] = {}
    for s in seasons:
        r = b.step(f"value rows {level} {s}", lambda: season_rows_mlb(b, level, s), None)
        if r:
            rows[s] = r
    if not rows:
        return {}
    hist = V.history_table(rows)
    ks, curves, meta = projections(hist, sorted(rows), level)
    ext = None
    if level == "aaa":                              # aging from MLB's longer history when it is there
        mc = an.read_json(_cache_dir() / "aging_mlb.json")
        if mc:
            ext = mc
    elif level == "mlb":
        an.write_json(_cache_dir() / "aging_mlb.json", curves)
    vctx = None
    if not cfg.get("no_moves"):
        vctx = b.step(f"valuation context {level}", lambda: valuation_context(b, cfg), None)
    n_written = 0
    for s in sorted(rows):
        tg = 0
        tp = b.data / level / str(s) / "teams.json"
        tpl = an.read_json(tp) if s == current else None
        hit = None
        try:
            hit = an.read_json(b.data / level / str(s) / "hitters.json") if s == current else None
        except Exception:                           # noqa: BLE001
            hit = None
        tg = (hit or {}).get("team_games") or _team_games(rows[s])
        phase = (hit or {}).get("phase") if hit else None
        pj = proj_for(hist, s, ks, curves, level, ext)
        pay = V.value_payload(level, s, rows[s], rows.get(s - 1), pj, tg, phase, meta if s == current else None)
        if s == current and vctx is not None:
            b.step(f"valuation v2 {level} {s}", lambda: _add_v2(b, level, s, pay, rows[s], pj, tpl, tg, vctx))
        n_written += write_if_changed(b, f"{level}/{s}/value.json", pay)
        if s == current:
            b.step(f"value teams {level} {s}", lambda: _current_teams(b, level, s, rows[s], pj, tpl, phase, tg, hist,
                                                                    (ext or curves), cfg, sims))
    if level == "mlb" and vctx is not None:
        b.step("moves and trades mlb", lambda: write_moves(b, vctx, cfg))
    log.info("value %s: %d value files written, %.1f s", level, n_written, time.perf_counter() - t0)
    return {"seasons": sorted(rows)}


def _add_v2(b, level: str, s: int, pay: dict, rows: list[dict], pj: dict, tpl: dict | None, tg: int, vctx) -> None:
    from oddsmarkets.baseball.analytics import moves_build as MB
    from oddsmarkets.baseball.analytics import trade as TR
    if level == "mlb":
        n_teams = len(((tpl or {}).get("teams") or {})) or 30
        unit = TR.units(rows, n_teams, tg or _team_games(rows), V.SCHEDULE.get(level, 162))
        extra, meta = MB.v2_rows(vctx, rows, pj, s, unit, _rpw(level, tpl))
        _merge_fields(pay, extra, MB.V2_FIELDS)
        pay["valuation"] = meta
    else:
        extra, meta = MB.prospect_fields(vctx, rows, s)
        _merge_fields(pay, extra, meta["fields"])
        pay["prospects"] = {"model": {k: ({kk: vv for kk, vv in (v or {}).items()} if v else None) for k, v in (meta["model"] or {}).items()},
                            "notes": ["Prospect value: expected MLB WAR over the next four seasons (discounted 8% a year) from the "
                                      "season's minor-league line at his highest level: level, age against the level's mean, "
                                      "performance against the level's (OPS; strikeouts minus walks per batter faced), sample. "
                                      "A log-link regression on the 2015-2022 cohorts (0 for a player who never reached the majors). "
                                      "Stat lines only, no scouting grades."]}


def write_moves(b, vctx, cfg: dict) -> None:
    """mlb/moves.json and mlb/trades.json (the trade validation is cached for a day on the transactions it saw)."""
    from oddsmarkets.baseball.analytics import moves_build as MB
    from oddsmarkets.baseball.analytics import trade_ratings as TRR
    today = cfg.get("today") or date.today()
    cur = max(vctx.rows)
    tp = an.read_json(b.data / "mlb" / str(cur) / "teams.json") or {}
    teams = {t: {k: x.get(k) for k in ("name", "abbr", "short", "league", "division", "colour")} for t, x in (tp.get("teams") or {}).items()}
    if not teams:
        from oddsmarkets.baseball import canon
        teams = {t: {"name": t} for t in canon.TEAMS}
    write_if_changed(b, "mlb/moves.json", MB.moves_payload(vctx, "mlb", today, teams))
    key = _sig(TRR.VERSION, len(vctx.trades), sorted(vctx.rows), str(today)[:7])
    cp = _cache_dir() / "trade_validation.json"
    got = an.read_json(cp)
    if got and got.get("key") == key:
        val = got["validation"]
    else:
        val = TRR.validate(vctx.world, vctx.trades)
        an.write_json(cp, {"key": key, "validation": val})
    write_if_changed(b, "mlb/trades.json", MB.trades_payload(vctx, "mlb", today, teams, val))


def _team_games(rows: list[dict]) -> int:
    return int(max((r.get("g") or 0) for r in rows if r["kind"] == "H") or 0)


def _rpw(level: str, teams_payload: dict | None) -> float:
    c = (teams_payload or {}).get("constants") or {}
    for k in ("rpw", "runs_per_win"):
        if c.get(k):
            return float(c[k])
    return 10.0 if level != "npb" else 8.3


def _current_teams(b, level: str, s: int, rows: list[dict], pj: dict, tpl: dict | None, phase: str | None, tg: int, hist: dict,
                   curves: dict, cfg: dict, sims: int | None) -> None:
    teams_info = {t: {k: x.get(k) for k in ("name", "abbr", "short", "league", "division", "colour")}
                  for t, x in ((tpl or {}).get("teams") or {}).items()}
    if not teams_info:
        return
    rpw = _rpw(level, tpl)
    unit = TR.units(rows, len(teams_info), tg, V.SCHEDULE.get(level, 162))
    needs = V.team_needs(level, s, [r for r in rows if r.get("team") in teams_info], pj, teams_info, contention_mlb(tpl, phase), unit, rpw)
    for t, pay in needs.items():
        if level == "mlb":
            pay["roster"] = TR.roster_rows(t, rows, pj, unit, rpw, curves.get("H") or [0, 0, 0], level, hist)
            pay["units"]["slot"] = unit
        write_if_changed(b, f"{level}/{s}/value/{t}.json", pay)
    if level != "mlb":
        return
    store = an.load_store(level, s)
    curves_p = cached_curves(level, s, store, lambda: TR.mlb_curves(store, s, n=sims or 1000, carry=TR.mlb_carry(level)))
    if curves_p:
        write_if_changed(b, f"{level}/{s}/trade.json", TR.trade_index(level, s, teams_info, curves_p, unit, rpw, {t: True for t in teams_info}))


def cached_curves(level: str, s: int, store_or_sig: Any, fn) -> dict | None:
    """The sensitivity curves, recomputed when their inputs change and at most once a day."""
    from oddsmarkets.baseball.models import season_sim as SS
    try:
        if isinstance(store_or_sig, dict) and "games" in store_or_sig:
            r = SS.team_ratings(store_or_sig)
            fin = sum(1 for g in SS.regular_games(store_or_sig) if SS.is_final(g))
            sig = _sig(TR.VERSION, SS.phase(store_or_sig), fin, {t: round(v["r"], 3) for t, v in r.items()})
        else:
            sig = _sig(TR.VERSION, store_or_sig)
    except Exception:                               # noqa: BLE001
        sig = _sig(TR.VERSION, time.strftime("%Y-%m-%d"))
    cp = _cache_dir() / f"curves_{level}_{s}.json"
    got = an.read_json(cp)
    # the same inputs: reuse; new inputs (a game finished): reuse for up to six hours, so an hourly build re-runs
    # the simulations a few times a day at most
    if got and (got.get("sig") == sig or time.time() - float(got.get("at") or 0) < CURVE_TTL):
        return got["curves"]
    t0 = time.perf_counter()
    cur = fn()
    an.write_json(cp, {"sig": sig, "at": time.time(), "curves": an.clean(cur)})
    log.info("trade curves %s %s: %.1f s", level, s, time.perf_counter() - t0)
    return cur
