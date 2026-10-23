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
            p["role"] = (ln[0] if ln else None) or (players.get(pid) or (None, None))[0]
            p["gar90"] = ln[1] if ln else None
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


def apply(data_dir: Path, roles_before: dict[str, str] | None = None) -> dict[str, int]:
    """Every annotation above from the value files on disk; returns {what: files rewritten}."""
    lines, players = load(data_dir)
    if not lines and not players:
        logger.info("value fields: no value layer on disk, nothing added")
        return {"players_live": 0, "lab": 0, "people": 0}
    out = {"players_live": annotate_players_live(data_dir, lines, players), "lab": annotate_lab(data_dir, lines, players)}
    out["people"] = refresh_people_roles(data_dir, roles_before or {}, {i: r for i, (r, _g) in players.items() if r}) \
        if roles_before is not None else 0
    logger.info("value fields: %s", out)
    return out
