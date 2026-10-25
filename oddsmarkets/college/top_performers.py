"""
Top performers on the team pages: each team's best players overall and at each position, against the whole level.

    write_top(level, data_dir, season) -> summary

adds `top_performers` to data/<L>/<S>/teams/<tid>.json (written by the level's builder just before), from that
season's players.json:

    {"key": metric key, "label", "ours": bool, "pool": "FBS" | "Division I",
     "overall": [row, ...],             the team's best qualified players by the headline metric (value per game,
                                        football; value, basketball), at most OVERALL
     "by_pos": [row, ...]}              the team's best qualified player at each position, ranked by that position's
                                        headline metric (docs/_design/metrics/college.json groups: the first metric)
    row = {"id", "name", "pos", "key", "v", "pct" (within the position, 0-100), "rank", "n" (qualified players at
           the position in the level), "gp"}

Peers are the level's qualified players at the same position (players.json `qualified`: the spec's minimum games);
the percentile is players.json `pct_pos`, so the page and the player pages agree. Played games only: no look-ahead.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OVERALL = 5
# the position's headline metric: the first of its group in docs/_design/metrics/college.json, where players.json
# carries it; value per game (football) and the box rating `r` (basketball). Both are our models' numbers.
CFB_HEAD = {"QB": "value_pg", "RB": "value_pg", "WR": "value_pg", "TE": "value_pg", "DL": "value_pg", "LB": "value_pg",
            "DB": "value_pg", "K": "value_pg", "P": "value_pg", "OL": "value_pg"}
OURS = {"value", "value_pg", "r", "epa_play", "epa"}
POS_ORDER = {"cfb": ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P"], "hoops": ["G", "F", "C"]}


def _num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _players(cat: dict) -> dict:
    from oddsmarkets.college import packing as PK
    P = cat.get("players")
    if PK.is_packed(P):
        P = PK.unpack(P)
    if isinstance(P, list):
        P = {str(r.get("id")): r for r in P if isinstance(r, dict)}
    return P if isinstance(P, dict) else {}


def compute(level: str, cat: dict) -> dict[str, dict]:
    """{team id: top_performers} from a players.json document."""
    P = _players(cat)
    fb = level == "cfb"
    lower = {m.get("key") for m in cat.get("metrics") or [] if m.get("lower")}
    labels = {m.get("key"): m.get("label") or m.get("key") for m in cat.get("metrics") or []}
    overall_key = "value_pg" if fb else "value"
    head = (lambda pos: CFB_HEAD.get(pos, "value_pg")) if fb else (lambda pos: "r" if "r" in labels else "value")
    # the level's qualified players by position, ranked on each position's headline metric
    by_pos: dict[str, list] = {}
    for pid, p in P.items():
        if not isinstance(p, dict) or p.get("qualified") is False or not p.get("pos"):
            continue
        by_pos.setdefault(p["pos"], []).append((str(pid), p))
    rank: dict[tuple, tuple] = {}
    for pos, rows in by_pos.items():
        for key in {head(pos), overall_key}:
            vals = [(pid, _num((p.get("values") or {}).get(key))) for pid, p in rows]
            vals = [x for x in vals if x[1] is not None]
            vals.sort(key=lambda x: (x[1] if key in lower else -x[1], x[0]))
            n = len(vals)
            for i, (pid, _v) in enumerate(vals):
                rank[(pid, key)] = (i + 1, n)

    def row(pid, p, key):
        v = _num((p.get("values") or {}).get(key))
        if v is None or (pid, key) not in rank:
            return None
        r, n = rank[(pid, key)]
        pct = _num((p.get("pct_pos") or {}).get(key))
        if pct is None and n > 1:
            pct = round(100 * (n - r) / (n - 1))
        return {"id": pid, "name": p.get("name"), "pos": p.get("pos"), "key": key, "v": round(v, 3),
                "pct": None if pct is None else int(round(pct)), "rank": r, "n": n, "gp": p.get("gp")}

    teams: dict[str, list] = {}
    for pos, rows in by_pos.items():
        for pid, p in rows:
            teams.setdefault(str(p.get("team")), []).append((pid, p))
    order = POS_ORDER["cfb" if fb else "hoops"]
    out = {}
    for tid, rows in teams.items():
        ov = [x for x in (row(pid, p, overall_key) for pid, p in rows) if x]
        ov.sort(key=lambda x: (-x["v"], x["id"]))
        bp = []
        for pos in sorted({p.get("pos") for _, p in rows}, key=lambda s: (order.index(s) if s in order else 99, s)):
            cands = [x for x in (row(pid, p, head(pos)) for pid, p in rows if p.get("pos") == pos) if x]
            if cands:
                cands.sort(key=lambda x: (x["rank"], x["id"]))
                bp.append(cands[0])
        if ov or bp:
            out[tid] = {"key": overall_key, "label": labels.get(overall_key, overall_key), "ours": overall_key in OURS,
                        "pool": "FBS" if fb else "Division I", "labels": {k: labels.get(k, k) for k in {head(x["pos"]) for x in bp}},
                        "overall": ov[:OVERALL], "by_pos": bp}
    return out


def write_top(level: str, data_dir: Path, season: int) -> dict:
    folder = Path(data_dir) / level / str(season)
    f = folder / "players.json"
    if not f.exists():
        return {"ok": False, "reason": "no players.json"}
    cat = json.loads(f.read_text(encoding="utf-8"))
    if not isinstance(cat, dict) or cat.get("ok") is False:
        return {"ok": False, "reason": "players.json not ok"}
    top = compute(level, cat)
    n = 0
    for tid, tp in top.items():
        tf = folder / "teams" / f"{tid}.json"
        if not tf.exists():
            continue
        try:
            doc = json.loads(tf.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        doc["top_performers"] = tp
        tf.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        n += 1
    return {"ok": True, "team_pages": n}
