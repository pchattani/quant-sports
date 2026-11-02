"""The Quant Scrum: the name in one place, the competitions and the scopes.

Rename the site here (SITE) and in docs/scrum/index.html's <title> and data-site-name; every payload, the follow
cards and the Home entry read SITE.
"""
from __future__ import annotations

SITE = {
    "name": "The Quant Scrum",
    "word": "Scrum",                       # the site word in the logo ("THE QUANT SCRUM")
    "slug": "scrum",                       # docs/<slug>, the follow scope prefix, the CI site key
    "repo": "the-quant-scrum",             # the public Pages repo (pchattani/<repo>)
    "url": "https://pchattani.github.io/the-quant-scrum/",
    "sport": "rugby",                      # QK sport key (data-sport)
}

USER_AGENT = "TheQuantScrum/1.0 (non-commercial; +https://pchattani.github.io/the-quant-scrum)"

# Scopes: one folder of season stores each. Men's internationals are the full-depth scope; women's and sevens
# go in as the second tab where ESPN has the data. Phase 2 (club rugby) adds scopes such as "prem", "top14",
# "urc", "super", "ecc" with kind "club" and the same store shape.
SCOPES = {
    "men": {"label": "Men's tests", "short": "Men", "kind": "international"},
    "women": {"label": "Women's tests", "short": "Women", "kind": "international"},
    "sevens": {"label": "Sevens", "short": "7s", "kind": "sevens"},
}

# ESPN site-API league slugs (site.api.espn.com/apis/site/v2/sports/rugby/<slug>/...). `wc` doubles the World
# Rugby points exchange; `first`/`last` bound the backfill (years ESPN answers with events, probed 2 Nov 2026).
COMPS = {
    "180659": {"key": "six", "name": "Six Nations", "scope": "men", "first": 1995},
    "244293": {"key": "trc", "name": "The Rugby Championship", "scope": "men", "first": 1996},
    "17567": {"key": "nc", "name": "Nations Championship", "scope": "men", "first": 2026},
    "164205": {"key": "rwc", "name": "Rugby World Cup", "scope": "men", "first": 1987, "wc": True},
    "289234": {"key": "test", "name": "Test match", "scope": "men", "first": 1995},
    "268565": {"key": "lions", "name": "Lions tour", "scope": "men", "first": 1997},
    "19940": {"key": "tri20", "name": "Tri Nations 2020", "scope": "men", "first": 2020},
    "289237": {"key": "wrwc", "name": "Women's Rugby World Cup", "scope": "women", "first": 1991, "wc": True},
    "282": {"key": "oly7m", "name": "Olympic sevens (men)", "scope": "sevens", "first": 2016},
    "283": {"key": "oly7w", "name": "Olympic sevens (women)", "scope": "sevens", "first": 2016},
}
COMP_BY_KEY = {v["key"]: dict(v, slug=k) for k, v in COMPS.items()}


def comp(slug_or_key: str) -> dict:
    s = str(slug_or_key)
    if s in COMPS:
        return dict(COMPS[s], slug=s)
    return COMP_BY_KEY.get(s) or {"key": s, "name": s, "scope": "men", "slug": s}


def scope_slugs(scope: str) -> list[str]:
    return [k for k, v in COMPS.items() if v["scope"] == scope]
