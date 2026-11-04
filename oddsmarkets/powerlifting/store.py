"""Local OpenPowerlifting stores under data/powerlifting (env POWERLIFTING_DATA)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def root() -> Path:
    return Path(os.environ.get("POWERLIFTING_DATA") or (ROOT / "data" / "powerlifting"))


def entries_path() -> Path:
    return root() / "entries.parquet"


def meets_path() -> Path:
    return root() / "meets.parquet"


def stamp_path() -> Path:
    return root() / "stamp.json"


def load_stamp() -> dict:
    p = stamp_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_stamp(obj: dict) -> None:
    p = stamp_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def load_entries() -> pd.DataFrame:
    p = entries_path()
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def load_meets() -> pd.DataFrame:
    p = meets_path()
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def save_table(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
