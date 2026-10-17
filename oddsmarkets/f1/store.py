"""
Season stores for the F1 site: one JSON per season, the single source of truth
the build reads, mirroring the football stores.

    docs/paddock/data/<year>/store.json
    {
      "season": 2026,
      "races": {"<round>": {name, date, time, circuit{id,name,locality,country,lat,long}, sessions{...},
                            results[...], qualifying[...], sprint[...], pitstops[...],
                            laps{driver: [ms per lap, None where missing]}, positions{driver: [pos per lap]}}},
      "drivers": {driverId: {code, number, given, family, dob, nationality}},
      "constructors": {constructorId: {name, nationality}},
      "meta": {fetched: {"<round>": {"results": ts, "qualifying": ts, ...}}, updated_at}
    }

Lap times are kept compactly (one list per driver) so 1996-2026 fits in tens of
megabytes. OpenF1's richer per-session data lives beside it under
docs/paddock/data/<year>/sessions/ (see sources/openf1.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "paddock" / "data"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def season_path(year: int) -> Path:
    return DATA / str(year) / "store.json"


def new_store(year: int) -> dict[str, Any]:
    return {"season": year, "races": {}, "drivers": {}, "constructors": {}, "meta": {"fetched": {}, "updated_at": None}}


def load(year: int) -> dict[str, Any]:
    p = season_path(year)
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            for k, v in new_store(year).items():
                s.setdefault(k, v)
            s["meta"].setdefault("fetched", {})
            return s
        except (OSError, ValueError):
            pass
    return new_store(year)


def save(store: dict[str, Any]) -> Path:
    p = season_path(int(store["season"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    store["meta"]["updated_at"] = now()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    return p


def mark(store: dict[str, Any], rnd: str, what: str) -> None:
    store["meta"]["fetched"].setdefault(str(rnd), {})[what] = now()


def has(store: dict[str, Any], rnd: str, what: str) -> bool:
    return what in (store["meta"]["fetched"].get(str(rnd)) or {})
