# The Quant Rink — documentation

NHL game, puck-line, total, season and playoff odds, our own expected goals, goals saved
above expected, score- and venue-adjusted on-ice rates, RAPM, player value, lines and
deployment, a season simulation with the NHL's published tiebreakers and draft lottery, and
Savant-style skater and goalie catalogues from 2009–10, published at
https://pchattani.github.io/the-quant-rink/. It is the sister site of The Quant Footballer,
The Quant Paddock, The Quant Hardwood, The Quant Ace, The Quant Bullpen and The Quant
Gridiron and lives in the same repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: NHL api-web, the stats REST shift charts and reports, NHL EDGE, ESPN lines by book, the MoneyPuck benchmark files, the markets and why nothing else; events, shifts and stints; coverage by season; identity; the fetch, fit and hydrate scripts; the store format and merge rules; what is committed; the scheduled job; the backfill |
| [MODELS.md](MODELS.md) | expected goals and its MoneyPuck benchmark, shooting, goaltending, on-ice rates, RAPM, Rink value, lines, stabilisation, team strength, the game model, live win probability, the season simulation, awards, markets, the backtest and its results as of 1 October 2026, the refit after the backfill, known limitations, and where the code and the site's Methodology disagree (open items) |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script and its manifests, local preview, tests, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: the deploy model, first-time publication, daily checks, routine jobs (the backfill, refits, the backtest), committing a completed season, rebuilding past seasons, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents:
`oddsmarkets/nhl/CONTRACT.md` (the data and model interfaces, with builder A's "As built"
section) and `oddsmarkets/nhl/PAYLOADS.md` (every payload the build writes and the
front-end reads, with builder D's "As built" section). Where they and the code differ,
these documents follow the code and say so.

These Markdown files are not published. The workflow rsyncs `docs/rink/` to the public
repository, which is why this folder is `docs/nhl/` and not `docs/rink/docs/`. The site's
own Methodology page (`#/methodology`, text in `docs/rink/assets/js/docs.js`) carries the
public-facing explanation of the models; [MODELS.md](MODELS.md) section 16 lists where that
text, the glossary, the docstrings and the scripts disagree with the code and the committed
fits. Those items are **open**: these documents were written without touching the code.

**The numbers are as of 1 October 2026.** The committed fits and `calibration.json` were
made while the historical backfill was still running, on the seasons then on disk (the xG
model on 2024–25 and 2025–26; the game model and backtest on four seasons rated on goals
only). The backfill was expected to finish at about 03:15 EDT on 2 October 2026; every
model is then to be refitted on the full history ([MODELS.md](MODELS.md) section 14.3,
[RUNBOOK.md](RUNBOOK.md) section 4), and the figures in these documents and in the
Methodology updated.

The football site's documents are one level up, in [`docs/`](../README.md); the F1 site's
are in [`docs/f1/`](../f1/README.md), the basketball site's in
[`docs/basketball/`](../basketball/README.md), the tennis site's in
[`docs/tennis/`](../tennis/README.md), the baseball site's in
[`docs/baseball/`](../baseball/README.md) and the NFL site's in [`docs/nfl/`](../nfl/README.md).
