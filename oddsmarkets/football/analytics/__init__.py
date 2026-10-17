"""
Season aggregates built from a Sofascore store: per-player totals, rates and
match logs, per-team match statistics, and per-match detail.

Every competition's store has the same shape (see `sources/sofascore.py`), so one
set of readers serves the leagues, the cups and the Argentine league; the
registry argument is the only competition-specific input (it canonicalises club
names). The readers tolerate the older, thinner detail format — matches fetched
before the full stat set was kept — by treating absent stats as zero and absent
metadata as unknown, so a store that mixes both formats still aggregates.
"""
