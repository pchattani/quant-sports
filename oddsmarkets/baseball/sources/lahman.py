"""
The Lahman Baseball Database (SABR; season totals 1871-2025; CC BY-SA 3.0), used only as a cross-check of
the Retrosheet-derived season totals (team runs and hits; player totals).

SABR publishes the comma-delimited version as a Box shared folder (linked from sabr.org/lahman-database/).
The folder page lists each file's Box id; a file downloads from
    https://sabr.box.com/index.php?rm=box_download_shared_file&shared_name=<folder>&file_id=f_<id>
(verified 1 Oct 2026 for Teams.csv, 1871-2025). Files are cached under <cache>/lahman/.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from .. import store as st
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

PAGE = "https://sabr.org/lahman-database/"
FOLDER = "y1prhc795jk8zvmelfd3jq7tl389y6cd"          # "Comma-delimited version" (2025 release)
DOWNLOAD = "https://sabr.box.com/index.php"
ATTRIBUTION = ("Season totals from the Lahman Baseball Database (SABR), licensed under Creative Commons "
               "Attribution-ShareAlike 3.0.")
FILES = ("Teams.csv", "People.csv", "Batting.csv", "Pitching.csv", "Fielding.csv")


def file_path(name: str) -> Path:
    return st.cache_root() / "lahman" / name


def file_ids(c: Client, folder: str = FOLDER) -> dict[str, str]:
    html = c.get_text(f"https://sabr.box.com/s/{folder}")
    out: dict[str, str] = {}
    for m in re.finditer(r'"typedID":"(f_\d+)","type":"file","id":\d+,[^}]*?"name":"([^"]+)"', html or ""):
        out[m.group(2)] = m.group(1)
    return out


def download(c: Client | None, names=FILES, refresh: bool = False) -> dict[str, Path]:
    out: dict[str, Path] = {}
    todo = [n for n in names if refresh or not file_path(n).exists()]
    ids = file_ids(c) if (todo and c is not None) else {}
    for n in names:
        p = file_path(n)
        if n in todo and n in ids and c is not None:
            data = c.get_bytes(DOWNLOAD, {"rm": "box_download_shared_file", "shared_name": FOLDER, "file_id": ids[n]})
            if data and not data.lstrip().startswith(b"<"):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
        if p.exists():
            out[n] = p
    return out


def load(name: str) -> pd.DataFrame | None:
    p = file_path(name)
    if not p.exists():
        return None
    return pd.read_csv(p, encoding="utf-8-sig", low_memory=False)


def team_totals(season: int) -> pd.DataFrame | None:
    """Teams.csv rows of a season with Retrosheet team codes: teamIDretro, R, H, G, W, L."""
    t = load("Teams.csv")
    if t is None:
        return None
    t = t[t["yearID"] == int(season)]
    return t[["teamIDretro", "lgID", "G", "W", "L", "R", "H", "HR", "BB", "SO"]].reset_index(drop=True)


def check_retro(season: int, pa: pd.DataFrame) -> dict:
    """Regular-season team runs and hits from parsed Retrosheet events against Lahman."""
    t = team_totals(season)
    if t is None or pa is None or pa.empty:
        return {"teams": 0}
    reg = pa[pa["gtype"].astype(str) == "R"]
    agg = reg.assign(h=(reg["hit"] > 0).astype(int)).groupby("bat_team", observed=True).agg(
        R=("runs_on_play", "sum"), H=("h", "sum")).reset_index()
    m = agg.merge(t, left_on="bat_team", right_on="teamIDretro", suffixes=("_retro", "_lahman"))
    return {"teams": int(len(m)), "runs_equal": int((m["R_retro"] == m["R_lahman"]).sum()),
            "hits_equal": int((m["H_retro"] == m["H_lahman"]).sum()),
            "runs": [int(m["R_retro"].sum()), int(m["R_lahman"].sum())],
            "hits": [int(m["H_retro"].sum()), int(m["H_lahman"].sum())]}

