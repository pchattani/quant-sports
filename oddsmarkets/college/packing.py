"""Column-packed lists of records for The Quant Campus payloads (size budget, PAYLOADS.md "Packed lists").

A list of flat-ish records is written as {"$cols": [key, ...], "$rows": [[v, ...], ...]}: the keys once, the values
row by row; a mapping of records (id -> record) as the same plus "$keys": [id, ...] (one per row). One level of
nesting (objects with fixed keys) is flattened into dotted columns ("model.p_home"). A None value means the key is
absent (the CARD convention: a missing key reads as null). The front end expands every packed list on load
(docs/campus/assets/js/cc-core.js `CC.unpack`), and so does `unpack` here (site.py and tests read payloads with it),
so a packed and an unpacked payload read the same.
"""
from __future__ import annotations

from typing import Any, Iterable

COLS, ROWS, KEYS = "$cols", "$rows", "$keys"


def pack(records: Iterable[dict], order: Iterable[str] | None = None) -> dict:
    """{"$cols", "$rows"} for `records` (dicts); columns in first-seen order (after `order`, if given)."""
    recs = [r for r in records if isinstance(r, dict)]
    cols: list[str] = list(order or [])
    seen = set(cols)
    flat_rows = []
    for r in recs:
        f: dict[str, Any] = {}
        for k, v in r.items():
            if (isinstance(v, dict) and v and "." not in k and all(not isinstance(x, (dict, list)) for x in v.values())
                    and not any(str(a)[:1].isdigit() or "." in str(a) for a in v)):     # fixed-key objects only
                for a, b in v.items():
                    f[f"{k}.{a}"] = b
            else:
                f[k] = v
        for k in f:
            if k not in seen:
                seen.add(k)
                cols.append(k)
        flat_rows.append(f)
    rows = [[f.get(k) for k in cols] for f in flat_rows]
    # drop trailing columns that are None in every row (order= columns may be unused)
    keep = [i for i, k in enumerate(cols) if any(row[i] is not None for row in rows)]
    if len(keep) < len(cols):
        cols = [cols[i] for i in keep]
        rows = [[row[i] for i in keep] for row in rows]
    return {COLS: cols, ROWS: rows}


def pack_keyed(mapping: dict, order: Iterable[str] | None = None) -> dict:
    """{"$keys", "$cols", "$rows"} for a mapping id -> record."""
    keys = list(mapping)
    out = pack([mapping[k] for k in keys], order)
    return {KEYS: [str(k) for k in keys], **out}


def is_packed(o: Any) -> bool:
    return isinstance(o, dict) and COLS in o and ROWS in o


def unpack_rows(o: dict) -> list[dict]:
    cols = o[COLS]
    out = []
    for row in o[ROWS]:
        r: dict[str, Any] = {}
        for k, v in zip(cols, row):
            if v is None:
                continue
            if "." in k:
                a, b = k.split(".", 1)
                r.setdefault(a, {})[b] = v
            else:
                r[k] = v
        out.append(r)
    return out


def unpack(o: Any) -> Any:
    """`o` with every packed list expanded (recursively)."""
    if is_packed(o):
        rows = [unpack(r) for r in unpack_rows(o)]
        return dict(zip(o[KEYS], rows)) if KEYS in o else rows
    if isinstance(o, dict):
        return {k: unpack(v) for k, v in o.items()}
    if isinstance(o, list):
        return [unpack(v) for v in o]
    return o
