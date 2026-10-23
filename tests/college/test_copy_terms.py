"""Campus copy pass at the source (23 Oct 2026): the site glossary and the calibration notes carry no betting framing."""
from __future__ import annotations

import json
import re

from oddsmarkets.college import site


def test_site_glossary_has_no_betting_words(tmp_path):
    g = site.build_glossary(tmp_path)
    text = json.dumps(g).lower()
    for bad in ("fair spread", "de-vigged price", "betting line", "not a bet"):
        assert bad not in text, bad
    labels = {e["key"]: e["label"] for grp in g["groups"] for e in grp["entries"]}
    assert labels["edge"] == "Model v market" and labels["spread_fair"] == "Model margin"     # keys unchanged
    assert not re.search(r"\bprices?\b", text)
