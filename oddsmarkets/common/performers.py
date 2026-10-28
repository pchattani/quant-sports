"""
Top and bottom performers on the league pages: a compact, precomputed `performers.json` per league and season.

    board(rows, metric, n=5)          -> one metric's boards: the top n and the bottom n among the qualified rows
    view(key, label, rows, metrics, entity="player", peer="", min_text="", n=5) -> a view (a position group, or teams)
    document(views, **meta)           -> {"schema", "n", "views": [...], **meta}
    write(path, doc)                  -> writes it compact (separators without spaces), returns the byte size

The front end draws it with the kit's QKL.leaders (docs/_design/league.js), which documents the same shape:

    VIEW   = {"key", "label", "entity": "player" | "team", "peer", "min", "n", "metrics": [METRIC]}
    METRIC = {"key", "label", "unit", "dir": "higher" | "lower", "ours" (our model's name, or absent), "fmt" (a
              QKL.fmtVal code: "1", "2", "+2", "3", "pct0", "pct1"), "tip", "n" (qualified with a value),
              "top": [ROW], "bot": [ROW]}
    ROW    = [id, name, team, value, pct, rank]   pct 0-100 with 100 the best; rank 1 the best (ties share a rank)

rows = [{"id", "name", "team", "v": {metric key: value}}]: the caller passes only qualified rows (the spec's
minimums), so every board ranks the same pool. A metric whose direction is "lower" ranks the smallest first. The
bottom board lists the last n in rank order (the very bottom last), and never repeats a row from the top board.
Played games only: callers build rows from season-to-date payloads, so there is no look-ahead.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

SCHEMA = 1
N = 5
MIN_POOL = 2   # a metric needs at least this many qualified rows with a value to get a board


def num(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _digits(fmt: str | None) -> int:
    """Decimal places to keep for a QKL.fmtVal code (one more than shown, so the page rounds, not the builder)."""
    f = str(fmt or "")
    if f in ("pct0", "pct1"):
        return 4
    if f.startswith("+"):
        f = f[1:]
    try:
        return max(0, int(f)) + 1
    except ValueError:
        return 4


def board(rows: list[dict], metric: dict, n: int = N) -> dict | None:
    """One metric's boards from qualified rows; None when fewer than MIN_POOL rows carry a value."""
    key = metric["key"]
    lower = metric.get("dir") == "lower"
    vals = []
    for r in rows:
        v = num((r.get("v") or {}).get(key))
        if v is not None:
            vals.append((v, str(r.get("name") or ""), r))
    if len(vals) < MIN_POOL:
        return None
    vals.sort(key=lambda t: ((t[0] if lower else -t[0]), t[1]))
    total = len(vals)
    d = _digits(metric.get("fmt"))
    out_rows = []
    better = 0
    for i, (v, _nm, r) in enumerate(vals):
        if i and vals[i - 1][0] != v:
            better = i
        rank = better + 1
        pct = round(100 * (total - rank) / (total - 1)) if total > 1 else 50
        out_rows.append([str(r.get("id")), r.get("name") or "", r.get("team") or "", round(v, d), pct, rank])
    out = {k: metric[k] for k in ("key", "label", "unit", "dir", "ours", "fmt", "tip") if metric.get(k) not in (None, "")}
    out["n"] = total
    out["top"] = out_rows[:min(n, total)]
    out["bot"] = out_rows[max(n, total - n):] if total > n else []
    return out


def view(key: str, label: str, rows: list[dict], metrics: list[dict], *, entity: str = "player", peer: str = "",
         min_text: str = "", n: int = N) -> dict | None:
    """A view: the boards of every metric for one pool (a position group, all players, or the teams); None if empty."""
    boards = [b for b in (board(rows, m, n) for m in metrics) if b]
    if not boards:
        return None
    out = {"key": key, "label": label, "entity": entity, "n": len(rows), "metrics": boards}
    if peer:
        out["peer"] = peer
    if min_text:
        out["min"] = min_text
    return out


def document(views: list[dict | None], n: int = N, **meta) -> dict:
    doc = {"schema": SCHEMA, "n": n}
    doc.update({k: v for k, v in meta.items() if v is not None})
    doc["views"] = [v for v in views if v]
    return doc


def write(path: Path | str, doc: dict) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    p.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


SPEC_DIR = Path(__file__).resolve().parents[2] / "docs" / "_design" / "metrics"


def load_spec(sport: str) -> dict:
    """A sport's metrics spec (docs/_design/metrics/<sport>.json, the machine form of docs/METRICS_SPEC.md)."""
    return json.loads((SPEC_DIR / f"{sport}.json").read_text(encoding="utf-8"))


def spec_metrics(spec: dict, group_id: str, *, ours_names: dict | None = None, fmt: dict | None = None,
                 skip: set | None = None, only: set | None = None, extra: list[dict] | None = None) -> list[dict]:
    """The headline metrics of a spec group in the spec's order, our model metrics first: each {"key", "label",
    "unit", "dir", "tip", "ours"?, "fmt"?}. Style metrics (neither better nor worse) are left out; `ours_names` maps
    our model keys to the name in the tag's tooltip (default the registry's name); `fmt` gives the display codes;
    `skip` / `only` filter ids (a payload that lacks a metric); `extra` appends metrics the caller defines."""
    grp = next((g for g in spec.get("groups") or [] if g.get("id") == group_id), None)
    if not grp:
        return []
    ours = spec.get("our_models") or {}
    models, omap = ours.get("models") or {}, ours.get("metrics") or {}
    heads = sorted((x for x in grp.get("metrics") or [] if x.get("set") == "headline" and x.get("id")),
                   key=lambda x: x.get("order") or 99)
    out = []
    for x in heads:
        mid = x["id"]
        if (skip and mid in skip) or (only is not None and mid not in only) or x.get("style"):
            continue
        m = {"key": mid, "label": x.get("display") or mid, "unit": x.get("unit") or "",
             "dir": "lower" if x.get("direction") == "lower" else "higher", "tip": x.get("explanation") or ""}
        if mid in omap:
            mk = omap[mid]
            m["ours"] = (ours_names or {}).get(mk) or (models.get(mk) or {}).get("name") or "Our model"
        if fmt and mid in fmt:
            m["fmt"] = fmt[mid]
        out.append(m)
    out.extend(extra or [])
    # our model metrics first (the brief: "starting with our model metrics"), the spec's order kept within each
    out.sort(key=lambda m: 0 if m.get("ours") else 1)
    return out
