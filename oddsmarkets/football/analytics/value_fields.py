"""The player value model's formation role and GAR/90 on the pages' own player payloads (METRICS_SPEC, Footballer).

The value layer (value_payloads.build_value) runs after the competitions and the unified step, so its role and GAR/90
reach the earlier payloads here, in a step that runs once the value files are written:

* `<slug>/players_live.json` players[]: `role` (the formation role of his line in that competition: GK, CB, FB, DM,
  CM, AM, W, ST; a coarse DF / MF / FW for substitute-only lines) and `gar90` (goals added above replacement per 90 in
  that competition, from data/value/lines.json; null under the value model's 90 minutes).
* `lab/<window>/<scope>.json`: two columns appended to `fields` (existing column positions are unchanged): `role` and
  `gar90`. The "season" window of a single competition reads that competition's line; every other row reads the
  person's 12-month value (data/value/players.json).
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
LAB_EXTRA = ("role", "gar90")


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


def annotate_lab(data_dir: Path, lines: dict, players: dict) -> int:
    """role and gar90 appended to every lab file's fields and rows; returns the files rewritten."""
    n = 0
    for path in sorted((data_dir / "lab").glob("*/*.json")):
        lab = _read(path)
        if not isinstance(lab, dict) or not isinstance(lab.get("fields"), list) or "player_id" not in lab["fields"]:
            continue
        fields = lab["fields"]
        width = len(fields)
        for k in LAB_EXTRA:
            if k not in fields:
                fields.append(k)
        i_id, i_comp = fields.index("player_id"), fields.index("comp") if "comp" in fields else None
        i_role, i_gar = fields.index("role"), fields.index("gar90")
        season = path.parent.name == "season"
        for r in lab.get("rows") or []:
            if not isinstance(r, list) or len(r) < width:
                continue
            while len(r) < len(fields):
                r.append(None)
            pid = str(r[i_id])
            comp = r[i_comp] if i_comp is not None else None
            ln = lines.get((pid, str(comp))) if season and isinstance(comp, str) else None
            role, gar = ln if ln else players.get(pid) or (None, None)
            r[i_role], r[i_gar] = role, gar
        n += _write_if_changed(path, lab)
    return n


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
          prev_sid: dict | None = None) -> dict[str, int]:
    """Every annotation above from the value files on disk (and, with `prev_lines` / `prev_sid` from this build's
    value layer, last season's role percentiles on the people files); returns {what: files rewritten}."""
    lines, players = load(data_dir)
    if not lines and not players:
        logger.info("value fields: no value layer on disk, nothing added")
        return {"players_live": 0, "lab": 0, "people": 0}
    out = {"players_live": annotate_players_live(data_dir, lines, players), "lab": annotate_lab(data_dir, lines, players)}
    out["people"] = refresh_people_roles(data_dir, roles_before or {}, {i: r for i, (r, _g) in players.items() if r}) \
        if roles_before is not None else 0
    if prev_lines:
        out["people_prev"] = annotate_people_prev(data_dir, prev_lines, prev_sid or {})
    logger.info("value fields: %s", out)
    return out
