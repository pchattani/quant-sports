# The Quant Sports: build repository

The code, models and front ends behind The Quant Sports, eight free, non-commercial sports analytics sites, and the GitHub
Actions workflows that fetch, build and publish them every hour:

| Site | Sport | Workflow |
|---|---|---|
| [The Quant Footballer](https://pchattani.github.io/the-quant-footballer/) | football, 69 competitions | `football.yml` |
| [The Quant Paddock](https://pchattani.github.io/the-quant-paddock/) | Formula 1 | `paddock.yml` |
| [The Quant Hardwood](https://pchattani.github.io/the-quant-hardwood/) | NBA and WNBA | `hardwood.yml` |
| [The Quant Ace](https://pchattani.github.io/the-quant-ace/) | ATP and WTA tennis | `ace.yml` |
| [The Quant Bullpen](https://pchattani.github.io/the-quant-bullpen/) | MLB | `bullpen.yml` |
| [The Quant Gridiron](https://pchattani.github.io/the-quant-gridiron/) | NFL | `gridiron.yml` |
| [The Quant Rink](https://pchattani.github.io/the-quant-rink/) | NHL | `rink.yml` |
| [The Quant Campus](https://pchattani.github.io/the-quant-campus/) | college football (FBS), men's and women's college basketball (D-I) | `campus.yml` |
| [The Quant Sports](https://pchattani.github.io/the-quant/) | the landing page, every sport in one place | `home.yml` |

## Layout

* `oddsmarkets/<sport>/`: data sources, stores, models, simulations and analytics, one package per sport
  (`football`, `f1`, `basketball`, `tennis`, `baseball`, `nfl`, `nhl`, `college`; shared code in `common` and `sports`).
* `scripts/`: the fetchers (`*_fetch.py`), fits (`*_fit.py`), hydrate steps and site builds (`build_*.py`);
  `scripts/ci_site.py` is the shared CI helper (restore, completeness guards, prune and deploy).
* `docs/<site>/`: each site's static front end and its committed inputs (completed seasons' stores,
  calibrations); `docs/_design/` is the shared design kit and `docs/home/` the landing page.
* `docs/<sport>/*.md` and `docs/MODELS.md` etc.: the method documentation.
* `tests/`: the test suite (`uv run pytest tests`). A few tests depend on raw third-party responses that are
  not published here (see `DATA_LICENSES.md`) and are skipped.

## How a site is built

Each workflow checks out this repository, restores its raw-data cache, clones the site's Pages repository
(the previous deploy), hydrates the current season from it, fetches what changed, builds, checks that the
working set is complete (a cold cache must never publish wrong pages), prunes and pushes the result to the
Pages repository. The football stores come from a fetch that runs elsewhere and are read from a private
repository; nothing raw from that source is published here.

This repository is an export: the code is developed in a private repository and published here
automatically. Pull requests are not accepted.

## Licence

All rights reserved; see `LICENSE`. Third-party data keeps its own terms: see `DATA_LICENSES.md`.
