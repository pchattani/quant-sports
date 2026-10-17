# The Quant Hardwood — documentation

NBA and WNBA odds, season simulations, team ratings with uncertainty, player impact,
shot quality, live win probability and Savant-style player and team analytics,
published hourly at https://pchattani.github.io/the-quant-hardwood/. It is the
sister site of The Quant Footballer and The Quant Paddock and lives in the same
repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: the ESPN APIs and why only ESPN, coverage by season, the fetch, derive, pack and hydrate scripts, the store and derived-table formats, play-by-play reconstruction, what is committed, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | team ratings, the game model, the season simulation, Elo, the shot model (xPTS), RAPM / box impact / HPM, win probability and WPA, award races, markets, the backtest and its results, known limitations, and where the code and the site's Methodology disagree |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script and its manifests, local preview, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: publishing, daily checks, routine jobs, the backfill and committing completed seasons, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents:
`oddsmarkets/basketball/CONTRACT.md` (the data and model interfaces) and
`oddsmarkets/basketball/PAYLOADS.md` (every payload the build writes and the
front-end reads). Where they and the code differ, these documents follow the code
and say so.

These Markdown files are not published. The workflow rsyncs `docs/hardwood/` to the
public repository, which is why this folder is `docs/basketball/` and not
`docs/hardwood/docs/`. The site's own Methodology page (`#/methodology`, text in
`docs/hardwood/assets/js/docs.js`) carries the public-facing explanation of the
models; [MODELS.md](MODELS.md) section 13 lists where that text and the code
disagree.

The football site's documents are one level up, in [`docs/`](../README.md); the F1
site's are in [`docs/f1/`](../f1/README.md).
