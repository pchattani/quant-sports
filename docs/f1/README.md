# The Quant Paddock — documentation

Formula 1 odds, lap-by-lap race simulations, championship forecasts, telemetry and
Savant-style driver and team analytics, published hourly at
https://pchattani.github.io/the-quant-paddock/. It is the sister site of The Quant
Footballer and lives in the same repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: Jolpica and OpenF1, their rate limits, coverage by year, the fetch scripts, the season store and session record formats, telemetry, identity resolution, the hourly job, the one-off backfills |
| [MODELS.md](MODELS.md) | the lap-time model, the car/driver decomposition, the qualifying model, circuit profiles, the race and championship simulators, Elo, Plackett-Luce, the walk-forward forecasts, the backtest and its results, markets, telemetry processing, known limitations |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script, local preview, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: publishing, daily checks, routine jobs, backfills, rate limits, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents and are kept current
with the code: `oddsmarkets/f1/CONTRACT.md` (the data and model interfaces) and
`oddsmarkets/f1/PAYLOADS.md` (every payload the build writes and the front-end
reads).

These Markdown files are not published. The workflow rsyncs `docs/paddock/` to the
public repository, which is why this folder is `docs/f1/` and not
`docs/paddock/docs/`. The site's own Methodology page (`#/methodology`, text in
`docs/paddock/assets/js/docs.js`) carries the public-facing explanation of the
models; [MODELS.md](MODELS.md) lists where that text and the code disagree.

The football site's documents are one level up, in [`docs/`](../README.md).
