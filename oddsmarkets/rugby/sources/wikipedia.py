"""
English Wikipedia article pages for The Quant Scrum (CC BY-SA 4.0; "Wikipedia contributors").

Only plain article pages are read (`/wiki/<title>`): robots.txt welcomes "friendly, low-speed bots" on article pages
and disallows /w/ and /api/, so neither the Action API nor the REST API is used (the tennis precedent,
docs/research/data_sources.md). Wikidata SPARQL stays out (robots.txt); nothing here uses it.

Fetching goes through `oddsmarkets.common.polite` (robots.txt obeyed, one request at a time on this PC, at least
`INTERVAL` seconds apart, back-off on refusals, every page cached gzipped under data/rugby/wiki/ which git ignores,
local fetch only). `SOURCE_WIKIPEDIA_RUGBY_ENABLED=0` turns the source off: nothing is fetched or parsed and the
builders drop every row it supplied.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from ...common import polite

ROOT = Path(__file__).resolve().parents[3]
FLAG = "SOURCE_WIKIPEDIA_RUGBY_ENABLED"
INTERVAL = 2.0
CREDIT = "Wikipedia contributors (CC BY-SA 4.0)"
LICENSE = {"name": "Wikipedia", "url": "https://en.wikipedia.org/", "license": "CC BY-SA 4.0",
           "attribution": "Historic results, referees and caps: Wikipedia contributors (CC BY-SA 4.0)"}


def raw_dir() -> Path:
    return Path(os.environ.get("RUGBY_WIKI") or (ROOT / "data" / "rugby" / "wiki"))


SRC = polite.Source(name="wikipedia_rugby", base="https://en.wikipedia.org", flag=FLAG, raw_dir=raw_dir(),
                    interval=INTERVAL, credit=CREDIT)


def enabled() -> bool:
    return SRC.enabled()


def path_of(title: str) -> str:
    return "/wiki/" + quote(title.replace(" ", "_"), safe="_()',.-–:!")


def client(budget: int | None = None, offline: bool = False) -> polite.Client:
    return SRC.client(budget=budget, offline=offline)


def page(c: polite.Client, title: str) -> str | None:
    """Article HTML (cached forever once fetched; pass a fresh client with max_age via `page_fresh`)."""
    return c.get(path_of(title))


def page_fresh(c: polite.Client, title: str, max_age: float) -> str | None:
    return c.get(path_of(title), max_age=max_age)
