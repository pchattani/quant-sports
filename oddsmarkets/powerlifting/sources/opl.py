"""OpenPowerlifting bulk CSV (public domain). Download the weekly zip; do not scrape the site.

https://openpowerlifting.gitlab.io/opl-csv/bulk-csv.html
Attribution (requested, not required): This page uses data from the OpenPowerlifting project,
https://www.openpowerlifting.org. You may download a copy of the data at https://data.openpowerlifting.org.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from .. import canon, identity, store

logger = logging.getLogger(__name__)

UA = "TheQuantIron/1.0 (non-commercial; +https://pchattani.github.io/the-quant-iron)"
URLS = (
    "https://openpowerlifting.gitlab.io/opl-csv/files/openpowerlifting-latest.zip",
    "https://openpowerlifting.gitlab.io/opl-csv/openpowerlifting-latest.zip",
)
KEEP = [
    "Name", "Sex", "Event", "Equipment", "Age", "Division", "BodyweightKg", "WeightClassKg",
    "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "TotalKg", "Place", "Dots", "Goodlift",
    "Tested", "Country", "Federation", "ParentFederation", "Date", "MeetCountry", "MeetState",
    "MeetName", "Sanctioned",
    # schema 2 (6 Nov 2026): attempts (negative = missed), Wilks, the age class and the birth-year class
    "Squat1Kg", "Squat2Kg", "Squat3Kg", "Bench1Kg", "Bench2Kg", "Bench3Kg",
    "Deadlift1Kg", "Deadlift2Kg", "Deadlift3Kg", "Wilks", "AgeClass", "BirthYearClass",
]
# schema 3 (13 Nov 2026): lifter ids from identity.pids (a bare Name that holds several people is split), so a
# schema-2 store is re-parsed from the cached zip by scripts/pl_fetch.py
SCHEMA = 3
ATTEMPTS = {"s1": "Squat1Kg", "s2": "Squat2Kg", "s3": "Squat3Kg", "b1": "Bench1Kg", "b2": "Bench2Kg", "b3": "Bench3Kg",
            "d1": "Deadlift1Kg", "d2": "Deadlift2Kg", "d3": "Deadlift3Kg"}


def _open(url: str, method: str = "GET", etag: str | None = None, timeout: int = 180):
    headers = {"User-Agent": UA, "Accept": "application/zip,*/*"}
    if etag:
        headers["If-None-Match"] = etag
    req = Request(url, method=method, headers=headers)
    return urlopen(req, timeout=timeout)


def find_url(etag: str | None = None) -> tuple[str, object]:
    last = None
    for url in URLS:
        try:
            r = _open(url, "HEAD", etag=etag, timeout=30)
            return url, r
        except HTTPError as e:
            if e.code == 304:
                raise
            last = e
            if e.code == 404:
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise last or RuntimeError("no OpenPowerlifting zip URL answered")


def download(dest: Path, etag: str | None = None) -> dict:
    """Write the weekly zip to dest. Returns {changed, etag, bytes, url}. 304 → changed False."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        url, head = find_url(etag)
        new_etag = head.headers.get("ETag") or head.headers.get("etag")
        length = int(head.headers.get("Content-Length") or 0)
        head.close()
        if etag and new_etag and new_etag == etag and dest.exists():
            return {"changed": False, "etag": new_etag, "bytes": dest.stat().st_size, "url": url}
        logger.info("downloading %s (%s bytes)", url, length or "?")
        with _open(url, "GET", timeout=300) as r:
            data = r.read()
            new_etag = r.headers.get("ETag") or r.headers.get("etag") or new_etag
        dest.write_bytes(data)
        return {"changed": True, "etag": new_etag, "bytes": len(data), "url": url}
    except HTTPError as e:
        if e.code == 304:
            return {"changed": False, "etag": etag, "bytes": dest.stat().st_size if dest.exists() else 0, "url": ""}
        raise


def parse_zip(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(entries, meets) from the bulk zip. Only sanctioned SBD / BD / B / D rows we can identify."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        raw = z.read(name)
    usecols = None
    header = pd.read_csv(io.BytesIO(raw), nrows=0)
    usecols = [c for c in KEEP if c in header.columns]
    df = pd.read_csv(io.BytesIO(raw), usecols=usecols, dtype=str, keep_default_na=False, na_values=["", "NA"])
    df = df[df["Name"].astype(str).str.len() > 0]
    df = df[df["Date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)]
    if "Sanctioned" in df.columns:
        df = df[df["Sanctioned"].fillna("Yes").isin(["Yes", ""])]
    df["eq"] = df["Equipment"].map(canon.EQ_GROUP)
    df = df[df["eq"].notna()]
    for c in ("BodyweightKg", "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "TotalKg", "Dots", "Goodlift", "Age",
              "Wilks", *ATTEMPTS.values()):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["tested"] = df["Tested"].fillna("").eq("Yes") if "Tested" in df.columns else False
    df["pid"] = ""                                  # set below from the parsed rows (identity.pids)
    df["meet_id"] = [
        canon.meet_id(str(f), str(d), str(n), str(c))
        for f, d, n, c in zip(df["Federation"], df["Date"], df["MeetName"], df["MeetCountry"])
    ]
    entries = pd.DataFrame({
        "pid": df["pid"],
        "name": df["Name"],
        "sex": df["Sex"],
        "event": df["Event"],
        "eq": df["eq"],
        "equipment": df["Equipment"],
        "age": df["Age"] if "Age" in df.columns else pd.NA,
        "bw": df["BodyweightKg"] if "BodyweightKg" in df.columns else pd.NA,
        "wclass": df["WeightClassKg"] if "WeightClassKg" in df.columns else "",
        "squat": df["Best3SquatKg"] if "Best3SquatKg" in df.columns else pd.NA,
        "bench": df["Best3BenchKg"] if "Best3BenchKg" in df.columns else pd.NA,
        "dead": df["Best3DeadliftKg"] if "Best3DeadliftKg" in df.columns else pd.NA,
        "total": df["TotalKg"] if "TotalKg" in df.columns else pd.NA,
        "place": df["Place"] if "Place" in df.columns else "",
        "dots": df["Dots"] if "Dots" in df.columns else pd.NA,
        "gl": df["Goodlift"] if "Goodlift" in df.columns else pd.NA,
        "tested": df["tested"],
        "country": df["Country"] if "Country" in df.columns else "",
        "fed": df["Federation"],
        "parent": df["ParentFederation"] if "ParentFederation" in df.columns else "",
        "date": df["Date"],
        "meet_id": df["meet_id"],
        "meet_name": df["MeetName"],
        "meet_country": df["MeetCountry"],
        "meet_state": df["MeetState"] if "MeetState" in df.columns else "",
        "division": df["Division"] if "Division" in df.columns else "",
        "wilks": df["Wilks"] if "Wilks" in df.columns else pd.NA,
        "age_class": df["AgeClass"] if "AgeClass" in df.columns else "",
        "byc": df["BirthYearClass"] if "BirthYearClass" in df.columns else "",
    })
    for k, col in ATTEMPTS.items():
        entries[k] = (df[col] if col in df.columns else pd.Series(np.nan, index=df.index)).astype("float32")
    # one OpenPowerlifting Name can hold several people until the archive adds a "#N": split on hard evidence
    entries["pid"] = identity.pids(entries).to_numpy()
    meets = (
        entries.groupby("meet_id", as_index=False)
        .agg(date=("date", "first"), name=("meet_name", "first"), fed=("fed", "first"),
             parent=("parent", "first"), country=("meet_country", "first"),
             state=("meet_state", "first"), n=("pid", "size"),
             n_sbd=("event", lambda s: int((s == "SBD").sum())))
        .sort_values("date")
        .reset_index(drop=True)
    )
    return entries.reset_index(drop=True), meets


def ingest(zip_path: Path) -> dict:
    entries, meets = parse_zip(zip_path)
    store.save_table(store.entries_path(), entries)
    store.save_table(store.meets_path(), meets)
    return {"schema": SCHEMA, "entries": len(entries), "meets": len(meets), "from": str(entries["date"].min()) if len(entries) else None,
            "to": str(entries["date"].max()) if len(entries) else None}
