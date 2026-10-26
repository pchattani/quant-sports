"""Detect and repair mojibake: UTF-8 text that was decoded as cp1252 (or latin-1) and re-encoded, so that
"Magalhães" becomes "MagalhÃ£es" and "Ødegaard" becomes "Ã˜degaard".

On Windows the usual causes are `open()` / `read_text()` without `encoding="utf-8"` (the locale is cp1252),
`subprocess.run(..., text=True)` on a child that writes UTF-8, and `requests` `.text` when the server sends no
charset. The repair is the inverse round trip, `s.encode("cp1252").decode("utf-8")`, accepted only when it succeeds
and leaves fewer mojibake markers, so correct names (which fail the round trip or gain nothing) are never touched.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

# A cp1252 view of a UTF-8 continuation byte (0x80-0xBF): latin-1 0x80-0xBF plus the cp1252 specials in 0x80-0x9F.
_CONT = ("\u0080-¿ŒœŠšŸŽžƒˆ˜–—‘-‚"
         "“-„†-•…‰‹›€™")
# A UTF-8 lead byte (2-byte C2-DF, 3-byte E0-EF) seen as cp1252, followed by its continuation byte(s).
MARKER = re.compile("[Â-ß][" + _CONT + "]|[à-ï][" + _CONT + "]{2}")
# The same in JSON written with ensure_ascii=True ("MagalhÃ£es").
_ESC_CONT = r"\\u(?:00[89ab][0-9a-f]|015[23]|016[01]|0178|017[de]|0192|02c6|02dc|201[34389a]|201[cde]|202[0126]|2030|203[9a]|20ac|2122)"
ESC_MARKER = re.compile(r"\\u00(?:c[2-9a-f]|d[0-9a-f]|e[0-9a-f])" + _ESC_CONT, re.I)

# A latin-1 decode (or cp1252's five undefined bytes) leaves C1 controls U+0080-U+009F: encode those back as the
# raw byte.
_C1 = {chr(b): bytes([b]) for b in range(0x80, 0xA0)}


def count_markers(s: str) -> int:
    return len(MARKER.findall(s))


def _to_bytes(s: str) -> bytes | None:
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            b = _C1.get(ch)
            if b is None:
                return None
            out += b
    return bytes(out)


def fix_text(s: str) -> str:
    """The repaired string when `s` is mojibake, else `s` unchanged. Applied repeatedly for double-encoded text."""
    for _ in range(3):
        n = count_markers(s)
        if not n:
            return s
        b = _to_bytes(s)
        if b is None:
            return s
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            return s
        if count_markers(t) >= n:
            return s
        s = t
    return s


def repair(obj):
    """(repaired copy, number of strings changed) for a JSON-like value: keys and string values."""
    n = 0

    def walk(x):
        nonlocal n
        if isinstance(x, str):
            y = fix_text(x)
            if y != x:
                n += 1
            return y
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, dict):
            return {walk(k): walk(v) for k, v in x.items()}
        return x

    out = walk(obj)
    return out, n


def find(obj, limit: int = 20) -> list[str]:
    """Up to `limit` strings (keys or values) in a JSON-like value that contain mojibake markers."""
    hits: list[str] = []

    def walk(x):
        if len(hits) >= limit:
            return
        if isinstance(x, str):
            if MARKER.search(x):
                hits.append(x)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)

    walk(obj)
    return hits


def text_has_markers(t: str) -> bool:
    return bool(MARKER.search(t) or ESC_MARKER.search(t))


def _layout(obj, t: str) -> dict:
    """json.dumps options that reproduce the file's own layout (so a repair changes only the repaired strings)."""
    ascii_ = t.isascii()
    body = t.replace("\r\n", "\n").rstrip("\n")
    for kw in ({"separators": (",", ":")}, {}, {"indent": 1}, {"indent": 2},
               {"indent": 1, "separators": (",", ":")}, {"indent": 2, "separators": (",", ": ")}):
        opts = {"ensure_ascii": ascii_, **kw}
        try:
            if json.dumps(obj, **opts) == body:
                return opts
        except (TypeError, ValueError):
            break
    return {"ensure_ascii": ascii_, "separators": (",", ":")}


def check_file(path: Path, fix: bool = False) -> tuple[int, int]:
    """(repairable, suspect) strings in a .json or .json.gz file: `repairable` pass the safe round trip,
    `suspect` carry markers but fail it (left alone; possibly genuine text). With fix=True a file with repairable
    strings is rewritten in place (same compression, layout and line endings). Non-JSON or unreadable files: (0, 0)."""
    path = Path(path)
    gz = path.name.endswith(".gz")
    try:
        raw = path.read_bytes()
        if gz:
            raw = gzip.decompress(raw)
        t = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError, EOFError, gzip.BadGzipFile):
        return 0, 0
    if not text_has_markers(t):
        return 0, 0
    try:
        obj = json.loads(t)
    except ValueError:
        return 0, 0
    hits = find(obj, limit=10**9)
    repairable = sum(1 for s in hits if fix_text(s) != s)
    suspect = len(hits) - repairable
    if fix and repairable:
        fixed, _n = repair(obj)
        out = json.dumps(fixed, **_layout(obj, t))
        if t.endswith("\n"):
            out += "\n"
        if "\r\n" in t:
            out = out.replace("\n", "\r\n")
        data = out.encode("utf-8")
        if gz:
            data = gzip.compress(data, mtime=0)
        tmp = path.with_name(path.name + ".mojifix.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return repairable, suspect
