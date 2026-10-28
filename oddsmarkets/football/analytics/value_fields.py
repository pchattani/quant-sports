"""The player value model's formation role and GAR/90 on the pages' own player payloads (METRICS_SPEC, Footballer).

The value layer (value_payloads.build_value) runs after the competitions and the unified step, so its role and GAR/90
reach the earlier payloads here, in a step that runs once the value files are written:

* `<slug>/players_live.json` players[]: `role` (the formation role of his line in that competition: GK, CB, FB, DM,
  CM, AM, W, ST; a coarse DF / MF / FW for substitute-only lines) and `gar90` (goals added above replacement per 90 in
  that competition, from data/value/lines.json; null under the value model's 90 minutes).
* `lab/<window>/<scope>.json`: three columns appended to `fields` (existing column positions are unchanged): `role`,
  `gar90` and `gar` (goals above replacement, a total). GAR is the value model's over exactly the matches of the
  line (PeopleLines.value_views: each player-match row tagged as the Lab tags it, a club edition by its season, a
  national-team or world-club match by date in the person's frame, the last 12 months, the calendar year), summed
  over the scope's competitions (GAR adds, GAR/90 = 90 x GAR / minutes). So an international line carries the value
  of its own international matches, never the club figure (28 Oct 2026: before, pooled rows summed each competition's
  latest edition whatever its season, and the 365 / ytd / last windows took the 12-month club value). `role` stays the
  line's role (one competition) or the 12-month role.
* `lab/leaders.json`: a `gar` board per scope (all, club, intl): this season's top 15 by goals above replacement
  (rows of lab/season/<scope>.json with 450+ minutes), {id, name, team, tid, comp, mix, value (GAR), minutes, gar90}.
* `value/season.json`: the Value page's "This season" views over every competition, club competitions or national-team
  football, one row per person and scope summed over the same matches as his Lab season line (write_value_season), so
  they never mix one competition's latest edition into another season (28 Oct 2026).
* `people/<pid>.json` `role`: the 12-month role. The unified step writes it from the value files on disk (the previous
  build's), and `refresh_people_roles` rewrites only the files whose role changed in this build's value layer.

Every file is rewritten only when its content changes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
LAB_EXTRA = ("role", "gar90", "gar")
LEAD_MIN = 450
POOLED = ("all", "club", "intl")
# a Lab line takes the value model's GAR only when the model scores at least half its minutes (the rows the value
# collector keeps: a final score and a line-up side), and without the windowed value only a competition line whose
# minutes are within 20% of the row's (the same edition)
LAB_COVER = 0.5
LAB_MATCH = 0.2


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_if_changed(path: Path, payload: Any) -> bool:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _rows(payload: Any, *cols: str) -> list[tuple]:
    fields = (payload or {}).get("fields") or []
    if not all(c in fields for c in cols):
        return []
    idx = [fields.index(c) for c in cols]
    return [tuple(r[i] for i in idx) for r in (payload or {}).get("rows") or [] if isinstance(r, list) and len(r) == len(fields)]


def load(data_dir: Path) -> tuple[dict[tuple[str, str], tuple], dict[str, tuple]]:
    """({(person id, competition slug): (role, gar90)} from value/lines.json, {person id: (role, gar90)} from
    value/players.json); empty when the value layer has not run."""
    lines = {(str(i), str(c)): (r, g) for i, c, r, g in _rows(_read(data_dir / "value" / "lines.json"), "id", "comp", "role", "gar90")}
    players = {str(i): (r, g) for i, r, g in _rows(_read(data_dir / "value" / "players.json"), "id", "role", "gar90")}
    return lines, players


def _num(x):
    return float(x) if isinstance(x, (int, float)) and x == x else None


def load_full(data_dir: Path) -> tuple[dict[tuple[str, str], tuple], dict[str, tuple]]:
    """({(person id, competition slug): (role, gar90, gar, minutes)} from value/lines.json, {person id: (role, gar90,
    gar)} from value/players.json, gar None when the file has no `gar` column)."""
    lp = _read(data_dir / "value" / "lines.json")
    lines = {(str(i), str(c)): (r, g, t, m) for i, c, r, g, t, m in _rows(lp, "id", "comp", "role", "gar90", "gar", "min")}
    pp = _read(data_dir / "value" / "players.json")
    if "gar" in ((pp or {}).get("fields") or []):
        players = {str(i): (r, g, t) for i, r, g, t in _rows(pp, "id", "role", "gar90", "gar")}
    else:
        players = {str(i): (r, g, None) for i, r, g in _rows(pp, "id", "role", "gar90")}
    return lines, players


def _intl_slugs(data_dir: Path) -> set[str]:
    """The national-team competitions from lab/index.json `comps` (empty when absent)."""
    ix = _read(data_dir / "lab" / "index.json") or {}
    return {k for k, v in (ix.get("comps") or {}).items() if (v or {}).get("scope") == "international"}


def _in_scope(scope: str, slug: str, intl: set[str]) -> bool:
    """A competition in a Lab scope: all, club (everything not national-team football), intl, or one competition."""
    if scope == "all":
        return True
    if scope == "club":
        return slug not in intl
    if scope == "intl":
        return slug in intl
    return slug == scope


def windowed(per_slug: dict | None, scope: str, intl: set[str], row_minutes) -> tuple:
    """(gar90, gar) of one Lab row from its person's windowed value ({slug: [GAR, minutes]}, the matches of this
    window as PeopleLines.value_views tags them): GAR adds over the scope's competitions, GAR/90 = 90 x GAR /
    minutes; (None, None) when the value model scores under LAB_COVER of the row's minutes (or none)."""
    g = m = 0.0
    for slug, v in (per_slug or {}).items():
        if not _in_scope(scope, slug, intl) or not isinstance(v, (list, tuple)) or len(v) < 2:
            continue
        t, mins = _num(v[0]), _num(v[1])
        if t is None or not mins:
            continue
        g += t
        m += mins
    rm = _num(row_minutes) or 0.0
    if m <= 0 or m < LAB_COVER * rm:
        return None, None
    return round(90.0 * g / m, 3), round(g, 2)


def roles(data_dir: Path) -> dict[str, str]:
    """{person id: 12-month role} from data/value/players.json (the unified step's source for people/<pid>.json)."""
    return {i: r for i, (r, _g) in load(data_dir)[1].items() if r}


def annotate_players_live(data_dir: Path, lines: dict, players: dict) -> int:
    """role and gar90 on every competition's players_live.json rows; returns the files rewritten."""
    n = 0
    for path in sorted(data_dir.glob("*/players_live.json")):
        live = _read(path)
        if not isinstance(live, dict) or not isinstance(live.get("players"), list):
            continue
        slug = path.parent.name
        for p in live["players"]:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("player_id"))
            ln = lines.get((pid, slug))
            # players_live writes no nulls (absent means unknown): a row without a value drops the key
            vals = {"role": (ln[0] if ln else None) or (players.get(pid) or (None, None))[0],
                    "gar90": ln[1] if ln else None}
            for k, v in vals.items():
                if v is None:
                    p.pop(k, None)
                else:
                    p[k] = v
        n += _write_if_changed(path, live)
    return n


def annotate_lab(data_dir: Path, lines: dict, players: dict, full: tuple | None = None, prev_lines: dict | None = None,
                 lab_value: dict | None = None) -> int:
    """role, gar90 and gar appended to every lab file's fields and rows; returns the files rewritten. `full` is
    load_full()'s pair (read from disk when None); `prev_lines` {(pid, slug): {"role", ...}} gives last season's role
    in one competition; `lab_value` is PeopleLines.value_views ({"windows": {window: {pid: {slug: [GAR, minutes]}}},
    "intl": [slugs]}), the value over exactly each line's matches. Without it (a build without the value layer) only a
    "season" row of one competition takes that competition's own line, and only when its minutes are the row's;
    every other GAR is left empty rather than joined from another window or scope."""
    n = 0
    lf, pf = full if full is not None else load_full(data_dir)
    wins = (lab_value or {}).get("windows") if isinstance(lab_value, dict) else None
    intl = set((lab_value or {}).get("intl") or []) if wins is not None else set()
    intl = intl or _intl_slugs(data_dir)
    for path in sorted((data_dir / "lab").glob("*/*.json")):
        lab = _read(path)
        if not isinstance(lab, dict) or not isinstance(lab.get("fields"), list) or "player_id" not in lab["fields"]:
            continue
        fields = lab["fields"]
        width = len(fields)
        for k in LAB_EXTRA:
            if k not in fields:
                fields.append(k)
        i_id = fields.index("player_id")
        i_min = fields.index("minutes") if "minutes" in fields else None
        i_role, i_g90, i_gar = fields.index("role"), fields.index("gar90"), fields.index("gar")
        window, scope = path.parent.name, path.stem
        one = scope not in POOLED
        wv = wins.get(window) if wins is not None else None
        for r in lab.get("rows") or []:
            if not isinstance(r, list) or len(r) < width:
                continue
            while len(r) < len(fields):
                r.append(None)
            pid = str(r[i_id])
            rmin = r[i_min] if i_min is not None else None
            role = (pf.get(pid) or (None, None, None))[0]
            ln = lf.get((pid, scope)) if one and window == "season" else None
            if ln:
                role = ln[0] or role
            elif one and window == "last":
                role = ((prev_lines or {}).get((pid, scope)) or {}).get("role") or role
            if wv is not None:
                g90, gar = windowed(wv.get(pid), scope, intl, rmin)
            elif ln and _num(ln[1]) is not None and _num(ln[3]) and _num(rmin) and \
                    abs(ln[3] - rmin) <= LAB_MATCH * max(ln[3], rmin):
                g90, gar = ln[1], ln[2] if _num(ln[2]) is not None else round(ln[1] * ln[3] / 90.0, 2)
            else:
                g90 = gar = None
            r[i_role], r[i_g90], r[i_gar] = role, g90, gar
        n += _write_if_changed(path, lab)
    n += annotate_leaders(data_dir)
    return n


def annotate_leaders(data_dir: Path) -> int:
    """lab/leaders.json: a `gar` board per pooled scope from lab/season/<scope>.json (450+ minutes, top 15 by GAR);
    returns 1 when the file was rewritten."""
    path = data_dir / "lab" / "leaders.json"
    board = _read(path)
    if not isinstance(board, dict) or not isinstance(board.get("scopes"), dict):
        return 0
    for scope, lists in board["scopes"].items():
        lab = _read(data_dir / "lab" / "season" / f"{scope}.json")
        if not isinstance(lists, dict) or not isinstance(lab, dict) or "gar" not in (lab.get("fields") or []):
            continue
        I = {f: i for i, f in enumerate(lab["fields"])}
        need = ("player_id", "name", "minutes", "gar", "gar90")
        if not all(k in I for k in need):
            continue
        rows = [r for r in lab.get("rows") or [] if isinstance(r, list) and len(r) == len(I)
                and _num(r[I["gar"]]) is not None and (r[I["minutes"]] or 0) >= LEAD_MIN]
        rows.sort(key=lambda r: (-r[I["gar"]], -(r[I["minutes"]] or 0)))
        get = lambda r, k: r[I[k]] if k in I else None
        lists["gar"] = [{"id": str(get(r, "player_id")), "name": get(r, "name"), "team": get(r, "team"), "tid": get(r, "tid"),
                         "comp": get(r, "comp"), "mix": get(r, "mix"), "value": get(r, "gar"), "minutes": get(r, "minutes"),
                         "gar90": get(r, "gar90")} for r in rows[:15]]
    return int(_write_if_changed(path, board))


SEASON_FIELDS = ["id", "scope", "tid", "name", "min", "gar90", "gar", "par", "rt", "prev90", "comps", "c"]
SEASON_MIN = 90


def _pooled(per_slug: dict | None, scope: str, intl: set[str]) -> dict | None:
    """One person's windowed lines summed over a pooled scope: {"g", "m", "par", "rtw", "rtm", "c": [...], "comps":
    [[slug, minutes]]}, None without minutes. Lists are [GAR, minutes, PAR, rating x minutes, rated minutes,
    components...] (PeopleLines.value_views with value_payloads' `_row_extra`)."""
    out = None
    for slug, v in (per_slug or {}).items():
        if not _in_scope(scope, slug, intl) or not isinstance(v, (list, tuple)) or len(v) < 2:
            continue
        g, m = _num(v[0]), _num(v[1])
        if g is None or not m:
            continue
        if out is None:
            out = {"g": 0.0, "m": 0.0, "par": 0.0, "rtw": 0.0, "rtm": 0.0, "c": [0.0] * max(len(v) - 5, 0), "comps": []}
        out["g"] += g
        out["m"] += m
        if len(v) >= 5:
            out["par"] += _num(v[2]) or 0.0
            out["rtw"] += _num(v[3]) or 0.0
            out["rtm"] += _num(v[4]) or 0.0
            for j, x in enumerate(v[5:5 + len(out["c"])]):
                out["c"][j] += _num(x) or 0.0
        out["comps"].append([slug, int(round(m))])
    if out is None or out["m"] <= 0:
        return None
    out["comps"].sort(key=lambda x: (-x[1], x[0]))
    return out


def write_value_season(data_dir: Path, lab_value: dict | None, players: dict | None = None) -> int:
    """data/value/season.json: the Value page's "This season" pooled views (all, club, intl), one row per person and
    scope over exactly the matches of his Lab season line (PeopleLines.value_views: each competition's matches in the
    person's own season, never another edition), [id, scope, tid (the Lab row's team: his club, or his national team
    for intl), name (only when value/players.json lacks the id), min, gar90, gar, par, rt, prev90 (GAR/90 in the same
    scope last season, 450+ minutes), comps [[slug, minutes]], c (components per 90 less the role's mean)]; rows of
    90+ minutes. Unchanged without the windowed value (the file stays the last value build's). Returns 1 when written."""
    wins = (lab_value or {}).get("windows") if isinstance(lab_value, dict) else None
    if not wins or not wins.get("season"):
        return 0
    intl = set((lab_value or {}).get("intl") or []) or _intl_slugs(data_dir)
    players = players or {}
    rows = []
    for scope in POOLED:
        lab = _read(data_dir / "lab" / "season" / f"{scope}.json") or {}
        f = lab.get("fields") or []
        I = {k: i for i, k in enumerate(f)}
        ident = {str(r[I["player_id"]]): (r[I["tid"]] if "tid" in I else None, r[I["name"]] if "name" in I else None)
                 for r in lab.get("rows") or [] if isinstance(r, list) and len(r) == len(f) and "player_id" in I}
        for pid, per in wins["season"].items():
            a = _pooled(per, scope, intl)
            if a is None or a["m"] < SEASON_MIN:
                continue
            b = _pooled((wins.get("last") or {}).get(pid), scope, intl)
            tid, name = ident.get(pid, (None, None))
            k = a["m"] / 90.0
            rows.append([pid, scope, tid, None if pid in players else name, int(round(a["m"])), round(a["g"] / k, 3),
                         round(a["g"], 2), round(a["par"], 2), round(a["rtw"] / a["rtm"], 2) if a["rtm"] > 0 else None,
                         round(90.0 * b["g"] / b["m"], 3) if b and b["m"] >= 450 else None, a["comps"],
                         [round(x / k, 3) for x in a["c"]] or None])
    rows.sort(key=lambda r: (POOLED.index(r[1]), -(r[6] or 0), r[0]))
    return int(_write_if_changed(data_dir / "value" / "season.json", {"fields": SEASON_FIELDS, "rows": rows}))


def refresh_people_roles(data_dir: Path, before: dict[str, str], after: dict[str, str]) -> int:
    """Rewrite people/<pid>.json `role` where this build's value layer changed it (the unified step wrote the
    previous build's); returns the files rewritten."""
    n = 0
    for pid in set(before) | set(after):
        if before.get(pid) == after.get(pid):
            continue
        path = data_dir / "people" / f"{pid}.json"
        doc = _read(path)
        if not isinstance(doc, dict) or doc.get("merged_into"):
            continue
        if after.get(pid):
            doc["role"] = after[pid]
        else:
            doc.pop("role", None)
        n += _write_if_changed(path, doc)
    return n


def spec_groups() -> list[dict]:
    """The player peer groups of docs/_design/metrics/football.json: [{"id", "codes", "min", "metrics": [(id, lower)]}]."""
    from oddsmarkets.common import similar as SIM
    out = []
    for g in SIM.spec("football").get("groups") or []:
        if g.get("entity") != "player" or not g.get("position_codes"):
            continue
        out.append({"id": g["id"], "codes": list(g["position_codes"]), "min": float((g.get("minimum") or {}).get("value") or 450),
                    "metrics": [(m["id"], m.get("direction") == "lower") for m in g.get("metrics") or [] if m.get("id")]})
    return out


def _mid_rank(vals: list[float], v: float, lower: bool) -> int:
    from bisect import bisect_left, bisect_right
    lo, hi = bisect_left(vals, v), bisect_right(vals, v)
    rank = (lo + 0.5 * (hi - lo)) / len(vals)
    return int(round(100 * (1 - rank if lower else rank)))


def prev_role_pct(rows: list[dict], prev: dict[str, dict], groups: list[dict], floor: float) -> dict[str, tuple[str, dict]]:
    """Last season's percentiles in one competition, against the formation-role group (the front end's FB.peerPct,
    core.js): {player id: (group id, {metric: 0-100})}. rows: that season's player rows (s/<sid>/season.json);
    prev: {player id: {"role", "gar90"}} (the value model's line in that competition last season); a player needs a
    fine role and max(the group's minimum, the season's floor) minutes; a metric needs five peers with a value."""
    code = {c: g for g in groups for c in g["codes"]}
    by_g: dict[str, list[dict]] = {}
    gof: dict[str, dict] = {}
    for r in rows:
        pid = str(r.get("player_id"))
        g = code.get(((prev.get(pid) or {}).get("role")) or "")
        if g and (r.get("minutes") or 0) >= max(g["min"], floor):
            gof[pid] = g
            by_g.setdefault(g["id"], []).append(r)

    def val(r: dict, k: str):
        v = (prev.get(str(r.get("player_id"))) or {}).get("gar90") if k == "gar90" else r.get(k)
        return float(v) if isinstance(v, (int, float)) and v == v else None
    sorted_v: dict[tuple[str, str], list[float]] = {}
    out: dict[str, tuple[str, dict]] = {}
    for r in rows:
        pid = str(r.get("player_id"))
        g = gof.get(pid)
        if not g:
            continue
        pc = {}
        for k, lower in g["metrics"]:
            key = (g["id"], k)
            if key not in sorted_v:
                sorted_v[key] = sorted(x for x in (val(q, k) for q in by_g[g["id"]]) if x is not None)
            v, vals = val(r, k), sorted_v[key]
            if v is not None and len(vals) >= 5:
                pc[k] = _mid_rank(vals, v, lower)
        if pc:
            out[pid] = (g["id"], pc)
    return out


def annotate_people_prev(data_dir: Path, prev_lines: dict[tuple[str, str], dict], prev_sid: dict[str, str | None]) -> int:
    """people/<pid>.json `current`: {"prev_pct_pos": {slug: {metric: 0-100}}, "prev_peer": {slug: {"sid", "season",
    "role", "group", "min"}}} for every player on a competition's players_live.json whose formation-role group last
    season in that competition (the value model's line) is the group of this season's row: last season's percentiles
    against that season's group in that competition, for the kit v3 rail rings (23 Oct 2026). The unified step
    rewrites every people file without `current` first, so a block that no longer applies drops out; returns the
    files rewritten."""
    from oddsmarkets.football.analytics.players import minutes_floor
    groups = spec_groups()
    if not groups or not prev_lines:
        return 0
    code = {c: g["id"] for g in groups for c in g["codes"]}
    per_pid: dict[str, dict] = {}
    for path in sorted(data_dir.glob("*/players_live.json")):
        slug = path.parent.name
        live = _read(path)
        if not isinstance(live, dict) or not isinstance(live.get("players"), list):
            continue
        sid = prev_sid.get(slug)
        if not sid:
            continue
        man = _read(data_dir / slug / "seasons.json") or {}
        ent = next((s for s in man.get("seasons") or [] if str(s.get("sid")) == str(sid)), None)
        past = _read(data_dir / slug / str((ent or {}).get("path") or f"s/{sid}/") / "season.json") if ent else None
        rows = [r for r in ((past or {}).get("players") or []) if isinstance(r, dict)]
        if not rows:
            continue
        prev = {pid: v for (pid, s), v in prev_lines.items() if s == slug}
        floor = float(minutes_floor(rows))
        got = prev_role_pct(rows, prev, groups, floor)
        mins = {str(r.get("player_id")): r.get("minutes") for r in rows}
        for p in live["players"]:
            if not isinstance(p, dict):
                continue
            pid = str(p.get("player_id"))
            if pid not in got or code.get(p.get("role") or "") != got[pid][0]:
                continue
            blk = per_pid.setdefault(pid, {"prev_pct_pos": {}, "prev_peer": {}})
            blk["prev_pct_pos"][slug] = got[pid][1]
            blk["prev_peer"][slug] = {"sid": str(sid), "season": (ent or {}).get("season"), "role": prev[pid]["role"],
                                      "group": got[pid][0], "min": mins.get(pid)}
    n = 0
    for pid, blk in per_pid.items():
        path = data_dir / "people" / f"{pid}.json"
        doc = _read(path)
        if not isinstance(doc, dict) or doc.get("merged_into"):
            continue
        doc["current"] = blk
        n += _write_if_changed(path, doc)
    logger.info("value fields: last-season role percentiles for %d players", len(per_pid))
    return n


def apply(data_dir: Path, roles_before: dict[str, str] | None = None, prev_lines: dict | None = None,
          prev_sid: dict | None = None, lab_value: dict | None = None) -> dict[str, int]:
    """Every annotation above from the value files on disk (and, with `prev_lines` / `prev_sid` from this build's
    value layer, last season's role percentiles on the people files; with `lab_value`, the Lab's GAR over each line's
    own matches); returns {what: files rewritten}."""
    lines, players = load(data_dir)
    if not lines and not players:
        logger.info("value fields: no value layer on disk, nothing added")
        _performers(data_dir)
        return {"players_live": 0, "lab": 0, "people": 0}
    out = {"players_live": annotate_players_live(data_dir, lines, players),
           "lab": annotate_lab(data_dir, lines, players, load_full(data_dir), prev_lines, lab_value)}
    if lab_value:
        out["season"] = write_value_season(data_dir, lab_value, players)
    out["people"] = refresh_people_roles(data_dir, roles_before or {}, {i: r for i, (r, _g) in players.items() if r}) \
        if roles_before is not None else 0
    if prev_lines:
        out["people_prev"] = annotate_people_prev(data_dir, prev_lines, prev_sid or {})
    logger.info("value fields: %s; performers for %d competitions", out, len(_performers(data_dir)))
    return out


def _performers(data_dir: Path) -> dict:
    """The competition pages' top and bottom performers (performers.py), once players_live carries the role and
    GAR/90; a failure never stops the build."""
    try:
        from oddsmarkets.football.analytics import performers
        return performers.write_all(data_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("performers: %s", exc)
        return {}
