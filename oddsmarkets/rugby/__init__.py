"""The Quant Scrum: international rugby union (men's tests first; women's and sevens where ESPN carries them).

Package map (docs/scrum/DATA_PIPELINE.md has the full pipeline):
  config.py          the site's name in one place, the competitions (ESPN league slugs) and the scopes
  store.py           season stores (data/rugby/stores/<scope>/<year>.json.gz) and the raw cache paths
  sources/espn.py    the ESPN client (paced, cached, backed off) and the summary parser
  ratings.py         our team rating (margin Elo with home, neutral, travel and rest) and the margin model
  rankings.py        our replica of the World Rugby rankings (points exchange, published formula)
  comps.py           competition rules: tables with bonus points, tiebreakers, simulators
  players.py         per-80 rates, shrinkage, position groups, percentiles and the value metric
  build.py           the payloads under docs/scrum/data
  follow_build.py    My Teams cards
  site.py            index, search and glossary

Club rugby (Premiership, Top 14, URC, Super Rugby, Champions Cup) is phase 2: a scope is a folder of season
stores, so a club scope is a new entry in config.COMPS with its own scope key and nothing else changes in the store.
"""
