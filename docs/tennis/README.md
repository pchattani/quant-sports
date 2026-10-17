# The Quant Ace — documentation

ATP and WTA singles odds, exact match models, draw and season simulations, surface
Elo, serve and return ratings inferred from scores, live win probability,
Savant-style player analytics and a Value section (breakout forecasts, luck, the ranking
and the market against the model), published hourly at
https://pchattani.github.io/the-quant-ace/. It is the sister site of The Quant
Footballer, The Quant Paddock and The Quant Hardwood and lives in the same
repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: tennis-data.co.uk, ESPN, the WTA API, the Match Charting Project and why nothing else, coverage by year, identity resolution, the fetch, charting, fit and hydrate scripts, the store format, what is committed, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | surface Elo, the serve/return model fitted to set scores (and the WTA point layer), the exact match chain, the blend, live win probability, the tournament and season simulators, markets, the backtest and its results, the memory incident, known limitations, where the code and the site's Methodology disagree, and the Value section's models and validation (section 15) |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script and its manifests, local preview, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: publishing, daily checks, routine jobs (refits, the backtest, charting), committing a completed year, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents:
`oddsmarkets/tennis/CONTRACT.md` (the data and model interfaces) and
`oddsmarkets/tennis/PAYLOADS.md` (every payload the build writes and the front-end
reads). Where they and the code differ, these documents follow the code and say so.

These Markdown files are not published. The workflow rsyncs `docs/ace/` to the
public repository, which is why this folder is `docs/tennis/` and not
`docs/ace/docs/`. The site's own Methodology page (`#/methodology`, text in
`docs/ace/assets/js/docs.js`) carries the public-facing explanation of the models;
[MODELS.md](MODELS.md) section 14 lists where that text and the code disagree (it
is behind on the WTA fits, among other things).

The football site's documents are one level up, in [`docs/`](../README.md); the F1
site's are in [`docs/f1/`](../f1/README.md) and the basketball site's in
[`docs/basketball/`](../basketball/README.md).
