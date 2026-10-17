# The Quant Bullpen — documentation

MLB and Triple-A (and, since 13 October 2026, Nippon Professional Baseball: the NPB level, see
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 14, [MODELS.md](MODELS.md) sections 23-24 and [RUNBOOK.md](RUNBOOK.md)
section 12; since 15 October 2026 player value, team strengths and needs and a trade simulator on every level,
[MODELS.md](MODELS.md) section 25 and [DASHBOARD.md](DASHBOARD.md) section 12) game, series, season and award odds from a
plate-appearance simulation,
pitch-level models (Stuff+, Location+, Pitching+, tunneling, swing decisions, bat
tracking), xwOBA+, catch probability, framing, umpires, our own park factors and run
expectancy, Bullpen WAR, projections, and Savant-style catalogues for the Statcast era
with Retrosheet careers back to 1908, published at
https://pchattani.github.io/the-quant-bullpen/. It is the sister site of The Quant
Footballer, The Quant Paddock, The Quant Hardwood, The Quant Ace and The Quant Gridiron and
lives in the same repository.

| Document | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | what the site is, how it was built, the system diagram, the repo map, design decisions, getting started, glossary. **Start here.** |
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | extraction: Baseball Savant and its 25,000-row cap, the MLB Stats API, ESPN lines, Retrosheet, the Chadwick register, Lahman, the markets and why nothing else, coverage by season, identity, the fetch, Retrosheet, fit and hydrate scripts, the store format and merge rules, what is committed, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | pitch physics, Stuff+ / Location+ / Pitching+, tunneling, swing decisions, bat tracking, fatigue, xwOBA+, catch probability, framing and umpires, run and win expectancy, park factors, Bullpen WAR, history, stabilisation, projections, the game simulation, live WP, the season and postseason simulation, awards, markets, the backtest and its results, known limitations, and where the code and the site's Methodology disagree |
| [DASHBOARD.md](DASHBOARD.md) | the website: routes, pages, the payload files and what builds them, the front-end modules, the build script and its manifests, local preview, tests, how to add a metric or a page |
| [RUNBOOK.md](RUNBOOK.md) | operations: the deploy model, first-time publication, daily checks, routine jobs (refits, the backtest), the backfill, committing a completed season, rebuilding past seasons, troubleshooting, the season calendar, secrets |

Two contracts inside the package complement these documents:
`oddsmarkets/baseball/CONTRACT.md` (the data and model interfaces) and
`oddsmarkets/baseball/PAYLOADS.md` (every payload the build writes and the front-end
reads, with an "As built" section). Where they and the code differ, these documents follow
the code and say so.

These Markdown files are not published. The workflow rsyncs `docs/bullpen/` to the public
repository, which is why this folder is `docs/baseball/` and not `docs/bullpen/docs/`.
The site's own Methodology page (`#/methodology`, text in
`docs/bullpen/assets/js/docs.js`) carries the public-facing explanation of the models;
[MODELS.md](MODELS.md) section 22 lists where that text and the code disagreed (it said
the game backtest covers every season from 2016, while the committed run then covered 2026
only, among other things) and how each was resolved on 1 October 2026. Since 2 October 2026,
after the backfill, the committed backtest does cover 2016–2026 (25,374 games).

The football site's documents are one level up, in [`docs/`](../README.md); the F1 site's
are in [`docs/f1/`](../f1/README.md), the basketball site's in
[`docs/basketball/`](../basketball/README.md), the tennis site's in
[`docs/tennis/`](../tennis/README.md) and the NFL site's in [`docs/nfl/`](../nfl/README.md).
