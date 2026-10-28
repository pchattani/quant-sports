"""Player progression on The Quant Footballer (round 6; oddsmarkets/common/progression.py, MIGRATION_V4.md
"Progression"): a person's career season by season, club and international apart, on the role group's deep metrics.

Rows. One per season (`era`: "2025/26" in a split-year frame, "2026" in a calendar one) and scope (club or
international), from the person's own competition lines in people/<pid>.json (`seasons` and `archive`):
minutes, appearances, goals, assists, xG, xA, shots, key passes and the rating, summed over the scope's competitions
(the rating minutes-weighted; the xG rates only over the competitions with xG, and only when they hold at least half
the minutes). Where the season is one of the Lab's windows ("season": this season, "last": last season;
lab/<window>/<club|intl>.json, the person's frame deciding the window's era, and its minutes within 20% of the row's) the row also carries
the Lab's deep line for that scope: the role from the value model, GAR/90 and every per-90 and percentage of the spec's groups.

Kinds (the `prog.keys` sets): "out" and "gk" (seasons with a Lab line: the deep set of the outfield groups, or the
goalkeepers', then the box keys) and "box" (older seasons: the box keys only). The peer group is the value model's
role of the Lab line, else the person's 12-month role, else the listed position (spec groups cb, fb, dm_cm, am_w, st,
gk). Qualified: 450 minutes (goalkeepers 900), the spec's minimum. Pools are per scope and season
("club:2025/26"): every competition the site follows, pooled, as the Lab's "club" and "international" views are.

Writes people/<pid>.json `progression` (rows {key, scope, era, min, apps, g, a, tid, team, teams, comps, kd, dv, dp,
pg}) and `prog` = {"v", "keys_in": "progression_ref.json"}, and data/progression_ref.json, which also carries the
kinds' key lists (`prog.keys`: one copy instead of one per people file, about 25 MB); a file is rewritten only when
its content changes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from oddsmarkets.common import progression as PG

logger = logging.getLogger(__name__)
PROG_FILE = "progression_ref.json"
OUT_GROUPS = ["st", "am_w", "dm_cm", "fb", "cb"]
BOX_KEYS = ["ga_90", "goals_90", "assists_90", "xg_90", "xa_90", "xg_xa_90", "shots_90", "key_passes_90", "rating"]
ROLE_GROUP = {"CB": "cb", "FB": "fb", "DM": "dm_cm", "CM": "dm_cm", "AM": "am_w", "W": "am_w", "ST": "st", "GK": "gk",
              "DF": "cb", "MF": "dm_cm", "FW": "st"}
POS_GROUP = {"G": "gk", "D": "cb", "M": "dm_cm", "F": "st"}
SCOPE = {"club": "club", "international": "intl"}
MIN_Q = {"gk": 900}
MIN_Q_DEFAULT = 450
MIN_ROW = 90
LAB_SKIP = {"tid", "age", "matches", "factor", "minutes"}
LAB_MATCH = 0.2
# the Lab's international lines carry the club GAR (last season's: the club line's own numbers; this season's: not the
# line's minutes), so the international rows leave GAR out until value_fields scores international lines on their own
INTL_SKIP = {"gar90", "gar"}


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _f(x: Any) -> float | None:
    return PG.fnum(x)


def lab_lines(data_dir: Path) -> tuple[dict[tuple[str, str, str], dict], dict[str, dict]]:
    """({(pid, scope, window): {field: value}}, {window: {"split": era, "calendar": era}}) from the Lab's season and
    last windows, club and international scopes."""
    idx = _read(data_dir / "lab" / "index.json") or {}
    eras = {w.get("key"): w.get("eras") or {} for w in idx.get("windows") or [] if w.get("key") in ("season", "last")}
    out: dict[tuple[str, str, str], dict] = {}
    for win in eras:
        for scope in ("club", "intl"):
            d = _read(data_dir / "lab" / win / f"{scope}.json") or {}
            f = d.get("fields") or []
            if "player_id" not in f:
                continue
            i = f.index("player_id")
            for r in d.get("rows") or []:
                if isinstance(r, list) and len(r) == len(f):
                    out[(str(r[i]), scope, win)] = dict(zip(f, r))
    return out, eras


def _sum_rows(rows: list[dict]) -> dict:
    """Box totals over one scope-season's competition lines."""
    mins = sum(_f(r.get("min")) or 0 for r in rows)
    tot = {k: sum(_f(r.get(k)) or 0 for r in rows) for k in ("apps", "g", "a", "sh", "kp")}
    xr = [r for r in rows if _f(r.get("xg")) is not None or _f(r.get("xa")) is not None]
    xmin = sum(_f(r.get("min")) or 0 for r in xr)
    rr = [r for r in rows if _f(r.get("rt")) is not None and (_f(r.get("min")) or 0) > 0]
    rmin = sum(_f(r.get("min")) for r in rr)
    v: dict[str, Any] = {}
    if mins > 0:
        v["goals_90"] = 90 * tot["g"] / mins
        v["assists_90"] = 90 * tot["a"] / mins
        v["ga_90"] = 90 * (tot["g"] + tot["a"]) / mins
        sh_rows = [r for r in rows if r.get("sh") is not None]
        sh_min = sum(_f(r.get("min")) or 0 for r in sh_rows)
        if sh_min >= 0.5 * mins and sh_min > 0:
            v["shots_90"] = 90 * sum(_f(r.get("sh")) or 0 for r in sh_rows) / sh_min
            v["key_passes_90"] = 90 * sum(_f(r.get("kp")) or 0 for r in sh_rows) / sh_min
        if xmin >= 0.5 * mins and xmin > 0:
            xg = sum(_f(r.get("xg")) or 0 for r in xr)
            xa = sum(_f(r.get("xa")) or 0 for r in xr)
            v["xg_90"], v["xa_90"], v["xg_xa_90"] = 90 * xg / xmin, 90 * xa / xmin, 90 * (xg + xa) / xmin
    if rmin > 0:
        v["rating"] = sum(_f(r.get("rt")) * _f(r.get("min")) for r in rr) / rmin
    return {"min": int(round(mins)), "apps": int(tot["apps"]), "g": int(tot["g"]), "a": int(tot["a"]), "values": v}


def person_rows(p: dict, lab: dict, eras: dict) -> list[dict]:
    """The person's scope-season rows (without the progression handles), oldest first."""
    pid = str(p.get("id"))
    frame = p.get("frame") or "split"
    lines: dict[tuple[str, str], list] = {}
    seen = set()
    for r in list(p.get("seasons") or []) + list(p.get("archive") or []):
        sc = SCOPE.get(r.get("scope"))
        era = r.get("era")
        if not sc or not era:
            continue
        k = (r.get("comp"), str(r.get("sid")), era, r.get("tid"))
        if k in seen:
            continue
        seen.add(k)
        lines.setdefault((sc, era), []).append(r)
    win_of = {(eras.get(w) or {}).get(frame): w for w in eras}
    base_gid = ROLE_GROUP.get(p.get("role") or "") or POS_GROUP.get(p.get("pos") or "")
    out = []
    for (sc, era), rows in lines.items():
        t = _sum_rows(rows)
        if t["min"] < MIN_ROW:
            continue
        by_t: dict[Any, float] = {}
        names = {}
        for r in rows:
            by_t[r.get("tid")] = by_t.get(r.get("tid"), 0) + (_f(r.get("min")) or 0)
            names[r.get("tid")] = r.get("team")
        teams = [t_ for t_, _ in sorted(by_t.items(), key=lambda kv: -kv[1]) if t_ is not None]
        v = dict(t["values"])
        kind = "box"
        gid = base_gid
        w = win_of.get(era)
        ln = lab.get((pid, sc, w)) if w else None
        lm = _f((ln or {}).get("minutes")) or 0
        if ln and abs(lm - t["min"]) > LAB_MATCH * max(lm, t["min"]):
            ln = None                     # the Lab's window is another span (a move between a split and a calendar frame)
        if ln:
            for k, x in ln.items():
                if k not in v and isinstance(x, (int, float)) and not isinstance(x, bool) and k not in LAB_SKIP                         and not (sc == "intl" and k in INTL_SKIP):
                    v[k] = x
            if _f(ln.get("xg_90")) is not None and _f(ln.get("xa_90")) is not None:
                v["xg_xa_90"] = _f(ln["xg_90"]) + _f(ln["xa_90"])
            gid = ROLE_GROUP.get(ln.get("role") or "") or gid
        if ln:
            kind = "gk" if gid == "gk" else "out"
        out.append({"key": f"{sc}:{era}", "scope": sc, "era": era, "min": t["min"], "apps": t["apps"], "g": t["g"], "a": t["a"],
                    "tid": teams[0] if teams else None, "team": names.get(teams[0]) if teams else None, "teams": teams,
                    "comps": len({r.get("comp") for r in rows}), "_kind": kind, "_gid": gid, "_v": v,
                    "_q": bool(gid) and t["min"] >= MIN_Q.get(gid or "", MIN_Q_DEFAULT)})
    out.sort(key=lambda r: (r["scope"], _era_x(r["era"])))
    return out


def _era_x(era: str) -> float:
    """A number on the season axis: a split season by the year it ends ("2024/25" -> 2025), a calendar one by itself."""
    s = str(era)
    try:
        if "/" in s:
            a = int(s[:4])
            return a + 1.0
        return float(int(s[:4]))
    except ValueError:
        return 0.0


def keys_for(have: dict[str, set]) -> dict[str, list[str]]:
    keys = {"box": [k for k in BOX_KEYS if k in (have.get("box") or set()) | (have.get("out") or set())]}
    if have.get("out"):
        keys["out"] = PG.deep_keys("football", OUT_GROUPS, have["out"], extra=BOX_KEYS)
    if have.get("gk"):
        keys["gk"] = PG.deep_keys("football", ["gk"], have["gk"], extra=BOX_KEYS)
    return keys


def build(people: dict[str, dict], lab: dict, eras: dict) -> tuple[dict[str, list[dict]], dict, dict]:
    """({pid: rows with dv / dp / pg / kd}, progression_ref.json, prog block) for the given people payloads (tests and
    small runs; `apply` streams the files instead)."""
    rows = {pid: person_rows(p, lab, eras) for pid, p in people.items()}
    return _place(rows)


def _place(rows: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], dict, dict]:
    have: dict[str, set] = {}
    for rs in rows.values():
        for r in rs:
            have.setdefault(r["_kind"], set()).update(k for k, x in r["_v"].items() if _f(x) is not None)
    keys = keys_for(have)
    pb = PG.Builder("football", keys)
    for rs in rows.values():
        for r in rs:
            r["_h"] = pb.add(r["key"], r["_kind"], r["_gid"], r["_v"], r["_q"])
    pb.finish()
    out = {}
    for pid, rs in rows.items():
        lst = []
        for r in rs:
            h = r.pop("_h")
            kind = r.pop("_kind")
            for k in ("_gid", "_v", "_q"):
                r.pop(k)
            lst.append({**r, "kd": kind, **h})
        out[pid] = lst
    return out, pb.reference(), pb.prog_block()


def carry(path: Path, payload: dict) -> dict:
    """The unified step's people writer keeps the last build's `progression` and `prog` (this step refreshes them after
    the value layer), so an unchanged person's file is not rewritten twice a build."""
    old = _read(path) if path.exists() else None
    if isinstance(old, dict):
        for k in ("progression", "prog"):
            if k in old and k not in payload:
                payload[k] = old[k]
    return payload


def apply(data_dir: Path) -> int:
    """people/<pid>.json `progression` and `prog`, and progression_ref.json; returns the files rewritten."""
    data_dir = Path(data_dir)
    lab, eras = lab_lines(data_dir)
    files = sorted((data_dir / "people").glob("*.json"))
    rows: dict[str, list[dict]] = {}
    for f in files:
        p = _read(f)
        if isinstance(p, dict) and p.get("id") is not None:
            rs = person_rows(p, lab, eras)
            if rs:
                rows[f.stem] = rs
    placed, ref, block = _place(rows)
    ref["prog"] = block                   # the kinds' key lists live here once, not in 20,000 people files
    block = {"v": block.get("v"), "keys_in": PROG_FILE}
    (data_dir / PROG_FILE).write_text(json.dumps(ref, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = 0
    for f in files:
        p = _read(f)
        if not isinstance(p, dict):
            continue
        new = placed.get(f.stem)
        if not new and "progression" not in p:
            continue
        before = json.dumps(p, sort_keys=True, ensure_ascii=False)
        p.pop("progression", None)
        p.pop("prog", None)
        if new:
            p["progression"] = new
            p["prog"] = block
        if json.dumps(p, sort_keys=True, ensure_ascii=False) != before:
            f.write_text(json.dumps(p, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
    logger.info("progression: %d people with rows, %d files rewritten", len(placed), n)
    return n
