"""
The Chadwick Baseball Bureau register: one person crosswalk across MLBAM, Retrosheet, Baseball-Reference
and FanGraphs ids (github.com/chadwickbureau/register, data/people-0.csv ... people-f.csv, ~4 MB each,
updated monthly). Licence: Open Data Commons Attribution (ODC-BY 1.0); credit with ATTRIBUTION.

`build(c)` downloads the 16 files (cached under <cache>/chadwick/, refreshed after 30 days) and writes
docs/bullpen/data/people.json:

    {pid: {"name","retro","bbref","fg","birth","debut","last"}}

keyed by MLBAM id for everyone who played, managed or umpired in MLB; people known only to Retrosheet are
keyed "r:<retroid>". `debut` / `last` are first and last MLB playing seasons (years). The full register
rows with an MLBAM id (minor leaguers too, for Triple-A players' bbref minors ids) stay in the cache as
<cache>/chadwick/mlbam.json.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from pathlib import Path

from .. import store as st
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

RAW = "https://raw.githubusercontent.com/chadwickbureau/register/master/data/people-{}.csv"
SHARDS = "0123456789abcdef"
ATTRIBUTION = ("Person identifiers from the Chadwick Baseball Bureau register (github.com/chadwickbureau/register), "
               "available under the Open Data Commons Attribution License (ODC-BY 1.0).")
MAX_AGE_DAYS = 30


def shard_path(k: str) -> Path:
    return st.cache_root() / "chadwick" / f"people-{k}.csv"


def download(c: Client | None, refresh: bool = False) -> int:
    """Fetch stale or missing shards; returns how many were downloaded."""
    n = 0
    for k in SHARDS:
        p = shard_path(k)
        fresh = p.exists() and (time.time() - p.stat().st_mtime) < MAX_AGE_DAYS * 86400
        if fresh and not refresh:
            continue
        if c is None:
            continue
        text = c.get_text(RAW.format(k))
        if not text or not text.startswith("key_person"):
            logger.warning("chadwick: shard %s not fetched", k)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        n += 1
    return n


def _date(y: str, m: str, d: str) -> str | None:
    if not y:
        return None
    if m and d:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return y


def _int(v: str) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def rows_from_text(text: str):
    yield from csv.DictReader(io.StringIO(text))


def build_crosswalk(rows) -> tuple[dict, dict]:
    """(people.json dict, mlbam index of every register row with an MLBAM id)."""
    people: dict[str, dict] = {}
    mlbam: dict[str, dict] = {}
    for r in rows:
        mid = (r.get("key_mlbam") or "").strip()
        retro = (r.get("key_retro") or "").strip() or None
        bbref = (r.get("key_bbref") or "").strip() or None
        fg = (r.get("key_fangraphs") or "").strip() or None
        name = " ".join(x for x in ((r.get("name_first") or "").strip(), (r.get("name_last") or "").strip(),
                                    (r.get("name_suffix") or "").strip()) if x) or None
        rec = {"name": name, "retro": retro, "bbref": bbref, "fg": fg,
               "birth": _date(r.get("birth_year") or "", r.get("birth_month") or "", r.get("birth_day") or ""),
               "debut": _int(r.get("mlb_played_first")), "last": _int(r.get("mlb_played_last"))}
        mlb = any((r.get(k) or "").strip() for k in ("mlb_played_first", "mlb_managed_first", "mlb_umpired_first"))
        if mid:
            mlbam[mid] = {**rec, "bbref_minors": (r.get("key_bbref_minors") or "").strip() or None}
            if mlb or retro:
                people[mid] = rec
        elif retro:
            people[f"r:{retro}"] = rec
    return people, mlbam


def build(c: Client | None, refresh: bool = False) -> dict:
    """Download (when stale) and write people.json; returns counts."""
    got = download(c, refresh)
    texts = []
    for k in SHARDS:
        p = shard_path(k)
        if p.exists():
            texts.append(p.read_text(encoding="utf-8"))
    if not texts:
        return {"downloaded": got, "people": 0}

    def rows():
        for t in texts:
            yield from rows_from_text(t)

    people, mlbam = build_crosswalk(rows())
    people = dict(sorted(people.items(), key=lambda kv: (kv[0].startswith("r:"), kv[0].zfill(10))))
    st.write_json(st.people_path(), people)
    st.write_json(st.cache_root() / "chadwick" / "mlbam.json", mlbam)
    return {"downloaded": got, "shards": len(texts), "people": len(people),
            "mlbam": sum(1 for k in people if not k.startswith("r:")),
            "retro_only": sum(1 for k in people if k.startswith("r:")), "register_mlbam": len(mlbam)}


def load_people() -> dict:
    return st.read_json(st.people_path(), {}) or {}


def load_mlbam_index() -> dict:
    return st.read_json(st.cache_root() / "chadwick" / "mlbam.json", {}) or {}


def enrich_players(players: dict, people: dict | None = None, index: dict | None = None) -> tuple[int, int]:
    """Fill retro / bbref / fg on store players from the crosswalk; returns (matched, total)."""
    people = people if people is not None else load_people()
    index = index if index is not None else {}
    hit = 0
    for pid, p in players.items():
        x = people.get(str(pid)) or index.get(str(pid))
        if not x:
            continue
        hit += 1
        for k in ("retro", "bbref", "fg"):
            if x.get(k) and not p.get(k):
                p[k] = x[k]
        if not p.get("bbref") and x.get("bbref_minors"):
            p["bbref_minors"] = x["bbref_minors"]
    return hit, len(players)
