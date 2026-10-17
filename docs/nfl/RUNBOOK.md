# Runbook — The Quant Gridiron

How to run, publish, check and repair the NFL site day to day. For how the pieces fit
together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and front-end in
depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md) and
[DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Gridiron Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | `:52` every hour; `:07`, `:22`, `:37` when a game is live or about to kick off; on dispatch | `.github/workflows/update_gridiron.yml`: restore the nflverse mirror and model caches and the previous deploy's payloads, hydrate the current season's store from the live site, fetch (nflverse timestamp-gated, the store, the play table, ESPN odds and live records), build, prune old game pages, rsync `docs/gridiron/` to the public repo. Commits nothing to `oddsmarkets`. |
| Local hourly task | the owner's Windows machine, scheduled task "Sofascore Refresh (all)" running `scripts/refresh_sofascore_all.ps1` | hourly | refreshes the football site's Sofascore stores, then **dispatches every site's workflow** (`update_gridiron.yml` among them) through the GitHub API, because GitHub drops many scheduled runs under load (on 1 October 2026 the Paddock got 2 scheduled runs in 15 hours, the Hardwood 1, the Ace none). The workflow's concurrency group keeps a dispatched run from overlapping a scheduled one. Log: `scripts/refresh_sofascore.log`. |
| Public site repo | `pchattani/the-quant-gridiron` (public) | pushed by the workflow | a `--delete` mirror of `docs/gridiron/` (stores and `calibration.json` included); never edit it by hand except for a deliberate hand deploy (sections 2 and 6) |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-gridiron/ |
| Fits, backtest, completed seasons, past-season rebuilds | the owner's machine | by hand (after a season, or when a model changes) | `nfl_fetch.py` backfills, `nfl_fit.py`, committing stores and fits, hand deploys |

**The deploy model in one paragraph.** The engine is private; the site is a public repo
served by Pages. CI never commits: it restores the previous deploy's payloads, hydrates
the current season's store from the live site, fetches, builds, prunes game pages older
than the previous season and pushes the result to the public repo. So **the deployed site
is the store of record for the current season**, whose store is never committed;
completed seasons' stores (and `calibration.json` and the fits) are committed to
`oddsmarkets` by hand. The very first deploy is pushed by hand from a local build, because a
cold CI run has no previous deploy to restore and only the current season's play-by-play.

---

## 2. First-time publication

**Done on 1 October 2026.** Both public repos, `pchattani/the-quant-gridiron` and
`pchattani/the-quant-bullpen`, were created and their first deploys pushed by hand that day;
`https://pchattani.github.io/the-quant-gridiron/` is live. The rest
of this section is kept for a rebuild from scratch (or a new site): check section 10's secrets
and variables rather than assuming them.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site gridiron
```

With `--site gridiron` (the `SITES["gridiron"]` entry) it does, each step skipped when
already done:

1. creates the public repo `pchattani/the-quant-gridiron` with a README so `main` exists,
   description "The Quant Gridiron: NFL odds, expected points and win probability,
   fourth-down decisions, game and season simulations. Built hourly.", homepage the Pages
   URL;
2. adds a deploy key titled "oddsmarkets update_gridiron.yml" with **write** access,
   reusing the key pair saved at
   `~/.ssh/oddsmarkets_GRIDIRON_DEPLOY_KEY.base64.txt` (a new ed25519 pair is
   generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret `GRIDIRON_DEPLOY_KEY` in
   `pchattani/oddsmarkets` (sealed with the repo's public key, PyNaCl);
4. sets the Actions variable `GRIDIRON_REPO = pchattani/the-quant-gridiron`;
5. turns on Pages from `main`, root, and asks for HTTPS (the certificate can take a few
   minutes);
6. with `--run`, dispatches `update_gridiron.yml` once. **Do not pass `--run` before the
   first hand deploy** (below): a cold CI run would publish a site without past seasons.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds; it needs
the `repo` and `workflow` scopes. (The script's docstring still describes only the football
site; `--site` selects the Gridiron.)

**The first deploy is pushed by hand** from a local build: a cold CI run would have no
previous deploy to restore and only the current season's play-by-play, so every past
season's payloads, the careers and the history would be missing. From then on each CI run
restores the previous deploy and hydrates the current season from it. To do it (Git Bash):

```bash
# 1. a complete local build: the mirror for every season, then the payloads
python scripts/nfl_fetch.py --from 1999 --to 2026            # if the mirror is not on this machine
python scripts/nfl_fetch.py --refresh-current --espn          # the current season up to date
python scripts/build_gridiron.py --game-page-seasons 2        # full build (about 6-11 minutes)

# 2. a clone of the public repo, filled the way the workflow fills it
git clone git@github.com:pchattani/the-quant-gridiron.git /tmp/site
rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/gridiron/ /tmp/site/

# 3. prune game pages older than the previous season, as the workflow's prune step does
S=$(python -c "from oddsmarkets.nfl import canon; print(canon.current_season())")
for d in /tmp/site/data/[0-9]*/; do y=$(basename "$d"); [ "$y" -le $((S-2)) ] && rm -rf "$d/games"; done

# 4. publish
cd /tmp/site && git add . && git commit -m "Site update (by hand)" && git push
```

The local `docs/gridiron/data/` is about 134 MB; a push of that size can need
`git config http.postBuffer 524288000`. Then dispatch the workflow once (Actions tab, "Run
workflow", or `setup_public_site.py --site gridiron --run`) and check that its restore step
cloned the public repo.

**By hand instead of the script**: create the public repo with a README and Pages from
`main` root; add the public key as a deploy key with write access; in `pchattani/oddsmarkets`
set the secret `GRIDIRON_DEPLOY_KEY` (base64 of the private key file) and the variable
`GRIDIRON_REPO`; push the first deploy as above; run "Gridiron Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has `index.html`,
`assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub. Without
`GRIDIRON_REPO` the workflow builds and logs "build only, no deploy"; without a public repo
the restore step logs "public repo not cloned (first run?): cold build".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Gridiron Hourly Update" | a green run at least every hour (scheduled or dispatched); in game windows every 15 minutes; outside them the `:07/:22/:37` runs stop after the gate step ("game window: False"); the restore, hydrate and fetch steps may show as failed-but-continued |
| The dispatches go out | `scripts/refresh_sofascore.log` | "dispatched update_gridiron.yml" every hour |
| The site is current | `https://pchattani.github.io/the-quant-gridiron/data/index.json`, `updated_at` | within the last hour (15 minutes during games) |
| The live store moved | `…/data/<S>/store.json`, `updated_at` | within the last hour in the season |
| Last week's games landed | `#/week` for last week | final scores; play-level pages once nflverse publishes the play-by-play (usually the next morning); ESPN's plays and WP fill the page before that |
| Lines | the fetch log's `<S> espn: … with lines` line | the week's games have ESPN books |
| Build errors | the Build step's log ends with "N step errors" and lists them | 0, or known ones |
| Models | `data/<S>/manifest.json` `model_errors` | `{}` |
| Markets | the build log's markets fetch step and `<S>/markets.json` `futures_error` | futures present in the season; `futures_error` null |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_gridiron.py` | current season full, the rest light (unchanged light seasons skipped) |
| Quick build | `uv run python scripts/build_gridiron.py --quick --no-market --no-light` | smoke check |
| Rebuild everything | `uv run python scripts/build_gridiron.py --force --all-games` | after a model change: light seasons and every page-season game page |
| Preview | `python -m http.server 8899` in `docs/gridiron`, then http://127.0.0.1:8899 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/nfl` | 84 test functions (85 tests), about 2 minutes, offline |
| Current season by hand | `python scripts/nfl_hydrate.py`, then `python scripts/nfl_fetch.py --refresh-current --espn --budget 1500` | what CI does |
| Coverage report | `python scripts/nfl_fetch.py --report --from 1999 --to 2026` | per-season counts from the stores and the mirror |
| Play-model fits | `python scripts/nfl_fit.py --only b` (or `--models ep wp fourth_down`) | refits on every completed season and writes `oddsmarkets/nfl/models/fitted/`; needs the full mirror; commit the files |
| Team, game and season fits and the backtest | `python scripts/nfl_fit.py --only c` | team-strength carry-over, the walk-forward game fit (about a minute), the drive model, the award models, the season-simulation constants, then the backtest (about 2 minutes) writing `docs/gridiron/data/calibration.json`; commit the fitted files and `calibration.json` |
| Fantasy fit and backtest | `python scripts/nfl_fantasy_fit.py` | tunes on 2014–2018, refits the constants on every completed season and runs the 2019→ walk-forward backtest; writes `oddsmarkets/nfl/models/fitted/fantasy.json` (commit it). About 15 minutes on two cores; rerun after a season ends |
| Transactions refresh | automatic in the build (ESPN, at most every 6 hours, cached in `data/nfl/cache/espn/transactions/`) | `--no-transactions` skips the pages, `--no-market` stops the fetch |
| Everything | `python scripts/nfl_fit.py` | builder B then builder C; `--through <S>` to stop at a season |
| Clear model caches | delete `data/nfl/cache/` (keep `espn/`: the raw odds and live records) | after a model change that does not bump a version string |
| JS syntax | `uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/gridiron/assets/js/<file>.js',encoding='utf-8').read())"` | per file (no Node on this machine) |

---

## 5. Committing a completed season

Do this once the season is over (after the Super Bowl in February; the store should hold no
scheduled or live game), and before 1 March if possible (on 1 March `canon.current_season`
turns over and CI starts hydrating the next season).

1. **Bring the store up to date locally**: `python scripts/nfl_hydrate.py --season <S>`,
   then a last pass for the season so the final schedules, the play table and every game's
   closing ESPN lines are in:
   `python scripts/nfl_fetch.py --from <S> --to <S> --espn`.
2. **Check it**: `python scripts/nfl_fetch.py --report --from <S> --to <S>`; every game final
   with nflverse lines and ESPN books.
3. **Refit and backtest** (section 4): `python scripts/nfl_fit.py --through <S>`; update the
   figures in `docs/nfl/MODELS.md` section 15 and the Methodology (`docs.js`) if they moved.
   Participation for the season arrives later (nflverse publishes it after the season; the
   2025 file was dated 10 February 2026): refit `completion`, `yac`, `ryoe` and
   `player_value` once it is on disk.
4. **Commit on `main`**, by explicit path (the `.gitignore` also un-ignores the current
   season's store):

   ```bash
   git add docs/gridiron/data/<S>/store.json docs/gridiron/data/calibration.json \
           oddsmarkets/nfl/models/fitted/
   ```

5. **Deploy**: nothing to do; the next CI run restores and redeploys. If the refit changed
   past seasons' payloads, publish them by hand (section 6).

---

## 6. Rebuilding past seasons

CI never rebuilds a past season: it has only the current season's play-by-play, so a past
season is skipped ("play-by-play not on this machine; payloads kept") and its payloads come
from the previous deploy. A model change, a fix in a catalogue or a refit therefore reaches
past seasons only through a local rebuild and a hand deploy:

```bash
# 1. the mirror for the seasons to rebuild (the gate skips what is current)
python scripts/nfl_fetch.py --from 1999 --to 2025

# 2. the current season from the live site, and the deployed payloads under the local ones
python scripts/nfl_hydrate.py
git clone --depth 1 git@github.com:pchattani/the-quant-gridiron.git /tmp/prev
rsync -a --ignore-existing /tmp/prev/data/ docs/gridiron/data/

# 3. rebuild (light seasons are forced; game pages for the page seasons)
python scripts/build_gridiron.py --force                       # every season
python scripts/build_gridiron.py --seasons 2024 --force        # or one season in full

# 4. hand deploy as in section 2 (rsync into a fresh clone, prune old game pages, push)
```

Game pages of seasons older than the previous one are pruned on every CI run, so rebuilding
them (`--game-page-seasons N --all-games`) has no lasting effect on the public site. Rebuild
and push while no CI run is in progress (or right after one), so the next run restores your
deploy rather than overwriting it with the previous one.

---

## 7. Rate limits and sources

| Source | Limit | What the code does | If it misbehaves |
|---|---|---|---|
| nflverse release assets (github.com → release-assets.githubusercontent.com) | not API-rate-limited | 0.2 s spacing; one `timestamp.txt` per release per run; HEAD and download only when a release moved; schema-checked replace | a broken download is discarded and the copy on disk kept; a schema change needs `REQUIRED` updated |
| ESPN site and core APIs | none stated | 1 s spacing; 429 or 5xx: `Retry-After` or 10 s × attempt, 4 attempts; budget per run | raise `--espn-interval`; the run resumes next time |
| Kalshi, Polymarket | public read APIs | one pass per build; failures give an empty futures block with `futures_error` | nothing; `--no-market` to skip |
| Pro Football Reference (directly or through nflverse: snap counts, advanced stats, trades, draft picks, combine, pre-2008 draft slots, PFR ids), the NFL's NGS API | terms / not public | not used (DATA_PIPELINE.md 14.1) | – |

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `GRIDIRON_REPO` or `GRIDIRON_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| No runs for hours | GitHub dropped the scheduled runs and the local task is not dispatching (machine off, no token from `git credential fill`) | check `scripts/refresh_sofascore.log`; dispatch by hand |
| Dispatch logs "(404) Not Found" | the workflow file is not on `main` (seen at 21:04 UTC on 1 October 2026) | merge it to `main` |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| "cold build" in the restore step, then a site without past seasons | the public repo could not be cloned | check the key; never let a cold build deploy over a good site: re-push the last good deploy by hand (section 2) |
| The current season goes backwards (games or lines missing that were there) | the hydrate step failed, so the build ran on the checkout's (or no) current store | check the hydrate log; re-run the workflow; recover with a local `nfl_fetch.py --from <S> --to <S> --espn` and a hand deploy |
| Game pages without plays the day after a game | nflverse has not published the play-by-play yet (the release's timestamp has not moved) | wait; the ESPN live record fills the page meanwhile |
| A game has no ESPN books | no ESPN id, or the odds endpoint answered empty | `nfl_fetch.py --from <S> --to <S> --phases espn --espn` re-reads final games read before kickoff + 3 h |
| `model_errors` lists a model | its fit is missing from the cache and from `models/fitted/`, or it raised | read the traceback in the build log; refit (`nfl_fit.py --models <name>`) and commit |
| Playoff odds empty, `sim_reason` set | the season simulation failed or had no ratings | read the build log; the season page still shows standings and seeds |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_gridiron.py` locally and read the traceback |
| Futures missing | Kalshi or Polymarket changed a series or title, or the field is thin | `futures_error` in `markets.json`; the series names and patterns are in `sources/markets.py` |
| `TimeoutError: lock … held too long` in a fetch | another writer held the store's lock past 300 s | re-run; a lock older than 600 s is broken automatically |
| Public repo updated but the live site is not | Pages did not start a build (seen once on the football site) | Settings → Pages; `POST /repos/pchattani/the-quant-gridiron/pages/builds` |

---

## 9. Seasons and calendar

| When | What |
|---|---|
| Game days (Thursday, Sunday, Monday nights; late-season Saturdays; the playoffs) | nothing by hand: the `:07/:22/:37` runs join the hourly one inside game windows, so the site moves every 15 minutes |
| The morning after | nflverse publishes the play-by-play; the next run's gate fetches it and the game pages gain their plays, EPA and fourth downs |
| Weekly | injuries, depth charts and rosters refresh with the releases; ratings refit with every build |
| February | the Super Bowl ends the season; commit the completed season (section 5); refit; the participation file for the season appears in nflverse later |
| 1 March | `canon.current_season` turns over (March to February is one season). The hydrate 404s for the new season (fine); the next fetch builds the new store from the schedules once nflverse lists them. Check: `canon.formats` (games, weeks, playoff format), new stadium ids in `canon.STADIUMS`, ESPN team ids, the Kalshi series suffixes in `sources/markets.py` (most use the following year's two digits, `KXNFL1SEED` the season's own), the award winners table (`models/award_winners.py`: add the season just finished), the kickoff-spot default in `fourth_down.default_ko` if the kickoff rule changes |
| August | the preseason; the season window opens on 1 August (`canon.season_window`) |
| When a source changes a field | the parsers in `sources/{nflverse,espn,markets}.py`, `nflverse.REQUIRED`, then `CONTRACT.md` and the fixtures in `tests/nfl/fixtures/` |

---

## 10. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `GRIDIRON_REPO` | Actions variable (`pchattani/the-quant-gridiron`) | `pchattani/oddsmarkets` | the restore and deploy steps |
| `GRIDIRON_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | the restore and deploy steps |
| deploy key "oddsmarkets update_gridiron.yml" | deploy key, write | `pchattani/the-quant-gridiron` | cloned and pushed to by the workflow |
| `GRIDIRON_DATA`, `GRIDIRON_RAW`, `GRIDIRON_CACHE` | environment variables (optional; `--data`, `--raw`, `--cache` on the build) | local, tests | point stores and payloads, the mirror and the caches elsewhere |
| `GH_TOKEN` | environment variable (optional) | the owner's machine | `setup_public_site.py` (else Git's credential manager) |

No API keys: nflverse, ESPN, Kalshi and Polymarket all serve public data without one. The
workflow's `GITHUB_TOKEN` has `contents: read` only. The local key pair is kept at
`~/.ssh/oddsmarkets_GRIDIRON_DEPLOY_KEY.base64.txt` once the set-up has run.
Licences to keep: nflverse CC BY 4.0 (credit), FTN Data via nflverse CC BY-SA 4.0 (credit;
derived charting data shared alike), NFL Next Gen Stats credited and informational,
non-commercial; all in the disclaimer, the footer and the glossary.
