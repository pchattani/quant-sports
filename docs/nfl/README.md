# The Quant Gridiron — documentation

NFL game, season and playoff odds, our own expected points and win probability,
every fourth down graded, completion, YAC, rushing and kicking models, opponent-adjusted
team units, a season simulation with the NFL's published tiebreakers, and Savant-style
player and team catalogues from 1999, published at
https://pchattani.github.io/the-quant-gridiron/. It is the sister site of The Quant
Footballer, The Quant Paddock, The Quant Hardwood, The Quant Ace and The Quant Bullpen
and lives in the same repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: the nflverse release mirror and its timestamp gate, ESPN (lines by book, live records), the prediction markets and why nothing else, coverage by season, identity, the fetch, fit and hydrate scripts, the store format and merge rules, what is committed, the scheduled job, the backfill |
| [MODELS.md](MODELS.md) | expected points, win probability, fourth downs, completion, YAC, RYOE, kicking, player value, the QB composite, stabilisation, team strength, the game model, the drive simulation, live WP, the season simulation, awards, markets, the backtest and its results, known limitations, and where the code and the site's Methodology disagree |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script and its manifests, local preview, tests, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: the deploy model, first-time publication, daily checks, routine jobs (refits, the backtest), committing a completed season, rebuilding past seasons, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents:
`oddsmarkets/nfl/CONTRACT.md` (the data and model interfaces) and
`oddsmarkets/nfl/PAYLOADS.md` (every payload the build writes and the front-end reads,
with an "As built" section). Where they and the code differ, these documents follow the
code and say so.

These Markdown files are not published. The workflow rsyncs `docs/gridiron/` to the
public repository, which is why this folder is `docs/nfl/` and not
`docs/gridiron/docs/`. The site's own Methodology page (`#/methodology`, text in
`docs/gridiron/assets/js/docs.js`) carries the public-facing explanation of the models;
[MODELS.md](MODELS.md) section 17 lists where that text and the code disagreed (it quoted
several pre-fit defaults where the site runs on committed fits, among other things) and how
each was resolved on 1 October 2026.

The football site's documents are one level up, in [`docs/`](../README.md); the F1
site's are in [`docs/f1/`](../f1/README.md), the basketball site's in
[`docs/basketball/`](../basketball/README.md), the tennis site's in
[`docs/tennis/`](../tennis/README.md) and the baseball site's in
[`docs/baseball/`](../baseball/README.md).
