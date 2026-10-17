# Runbook — The Quant Rink

How to run, publish, check and repair the NHL site day to day. For how the pieces fit
together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and front-end in
depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md) and
[DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Rink Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | `:32` every hour; `:02`, `:17`, `:47` when a game is live or about to start; on dispatch | `.github/workflows/update_rink.yml`: restore the current season's raw NHL data and the model caches and the previous deploy's payloads, hydrate the current season's store from the live site, fetch (schedule, play-by-play, shifts, boxscores, standings, EDGE, ESPN odds, MoneyPuck at most daily; then the derived tables), build, prune old game pages, rsync `docs/rink/` to the public repo. Commits nothing to `oddsmarkets`. |
| Local hourly task | the owner's Windows machine, scheduled task "Sofascore Refresh (all)" running `scripts/refresh_sofascore_all.ps1` | hourly | refreshes the football site's Sofascore stores, then **dispatches every site's workflow** (`update_rink.yml` among them) through the GitHub API, because GitHub drops many scheduled runs under load. The workflow's concurrency group keeps a dispatched run from overlapping a scheduled one. Log: `scripts/refresh_sofascore.log` ("dispatched update_rink.yml" every hour from 20:06 EDT on 1 October 2026; the 19:04 dispatch answered 404 because the workflow was not yet on `main`). |
| Public site repo | `pchattani/the-quant-rink` (public) | pushed by the workflow | a `--delete` mirror of `docs/rink/` (stores and `calibration.json` included); never edit it by hand except for a deliberate hand deploy (sections 2 and 6) |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-rink/ |
| Backfill, fits, backtest, completed seasons, past-season rebuilds | the owner's machine | by hand (after a season, or when a model changes) | `nhl_backfill.ps1`, `fit_b`, `fit_c.fit_all`, `nhl_fit.py`, committing stores and fits, hand deploys |

**The deploy model in one paragraph.** The engine is private; the site is a public repo
served by Pages. CI never commits: it restores the previous deploy's payloads, hydrates the
current season's store from the live site, fetches, builds, prunes game pages older than the
previous season and pushes the result to the public repo. So **the deployed site is the
store of record for the current season**, whose store is never committed; completed seasons'
stores (and `calibration.json` and the fits) are committed to `oddsmarkets` by hand. The very
first deploy was pushed by hand from a local build, because a cold CI run has no previous
deploy to restore and only the current season's raw data.

---

## 2. First-time publication

**Done on 1 October 2026.** The public repo `pchattani/the-quant-rink` was created with
`setup_public_site.py --site rink` and the first deploy pushed by hand that day (the deploy
key file is dated 23:15 EDT). The rest of this section is kept for a rebuild from scratch:
check section 10's secrets and variables rather than assuming them.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site rink
```

With `--site rink` (the `SITES["rink"]` entry) it does, each step skipped when already done:

1. creates the public repo `pchattani/the-quant-rink` with a README so `main` exists,
   description "The Quant Rink: NHL odds, expected goals, RAPM, goalie and skater analytics,
   game and season simulations. Built hourly.", homepage the Pages URL;
2. adds a deploy key titled "oddsmarkets update_rink.yml" with **write** access, reusing the
   key pair saved at `~/.ssh/oddsmarkets_RINK_DEPLOY_KEY.base64.txt` (a new
   ed25519 pair is generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret `RINK_DEPLOY_KEY` in
   `pchattani/oddsmarkets` (sealed with the repo's public key, PyNaCl);
4. sets the Actions variable `RINK_REPO = pchattani/the-quant-rink`;
5. turns on Pages from `main`, root, and asks for HTTPS (the certificate can take a few
   minutes);
6. with `--run`, dispatches `update_rink.yml` once. **Do not pass `--run` before the first
   hand deploy** (below): a cold CI run would publish a site without past seasons.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds; it needs
the `repo` and `workflow` scopes. (The script's docstring still describes only the football
site; `--site` selects the Rink.)

**The first deploy is pushed by hand** from a local build: a cold CI run would have no
previous deploy to restore and only the current season's raw data, so every past season's
payloads, the careers and the history would be missing. From then on each CI run restores
the previous deploy and hydrates the current season from it. To do it (Git Bash):

```bash
# 1. a complete local build: the raw data for every season, then the payloads
powershell -File scripts/nhl_backfill.ps1 -Which all          # if the raw data is not on this machine (hours; resumable)
python scripts/nhl_fetch.py --refresh-current                  # the current season up to date
python scripts/build_rink.py --game-page-seasons 2             # full build

# 2. a clone of the public repo, filled the way the workflow fills it
git clone git@github.com:pchattani/the-quant-rink.git /tmp/site
rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/rink/ /tmp/site/

# 3. prune game pages older than the previous season, as the workflow's prune step does
S=$(python -c "from oddsmarkets.nhl import canon; print(canon.current_season())")
CUT=$(( (S / 10000 - 2) * 10001 + 1 ))
for d in /tmp/site/data/[0-9]*/; do y=$(basename "$d"); [ "$y" -le $CUT ] && rm -rf "$d/games"; done

# 4. publish
cd /tmp/site && git add . && git commit -m "Site update (by hand)" && git push
```

The local `docs/rink/data/` was about 109 MB on 1 October 2026 (two seasons of game pages,
45 MB); a push of that size can need `git config http.postBuffer 524288000`. Then dispatch
the workflow once (Actions tab, "Run workflow", or `setup_public_site.py --site rink --run`)
and check that its restore step cloned the public repo.

**By hand instead of the script**: create the public repo with a README and Pages from
`main` root; add the public key as a deploy key with write access; in `pchattani/oddsmarkets`
set the secret `RINK_DEPLOY_KEY` (base64 of the private key file) and the variable
`RINK_REPO`; push the first deploy as above; run "Rink Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has `index.html`,
`assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub. Without `RINK_REPO` the
workflow builds and logs "RINK_REPO / RINK_DEPLOY_KEY not set: build only, no deploy";
without a public repo the restore step logs "public repo not cloned (first run?): cold
build".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Rink Hourly Update" | a green run at least every hour (scheduled or dispatched); in game windows every 15 minutes; outside them the `:02/:17/:47` runs stop after the gate step ("game window: False"); the restore, hydrate and fetch steps may show as failed-but-continued |
| The dispatches go out | `scripts/refresh_sofascore.log` | "dispatched update_rink.yml" every hour |
| The site is current | `https://pchattani.github.io/the-quant-rink/data/index.json`, `updated_at` | within the last hour (15 minutes during games) |
| The live store moved | `…/data/<S>/store.json`, `updated_at` | within the last hour in the season |
| Last night's games landed | `#/games` for yesterday | final scores, shot maps, xG and lines on the game pages (shift-based blocks once the chart is published; a game is re-read once it has settled, after noon UTC the next day) |
| Lines | the fetch log's `<S> espn: ... final games with lines N / M` | every final game with lines |
| Shift charts | the fetch log's `<S> shifts: ... (N from HTML TOI reports, N empty ...)` | no empty charts for settled games |
| On-ice agreement | `meta.derived.rate` in the store (or the fetch log's "derived" line) | about 0.99 or better |
| Build errors | the Build step's log ends with "N step errors" and lists them | 0, or known ones |
| Models | `data/<S>/manifest.json` `model_errors` and `xg_source` | `{}` and "model" |
| Markets | the build log's markets step and `<S>/markets.json` | futures present in the season |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_rink.py` | current season full, the rest light (unchanged light seasons skipped) |
| Quick build | `uv run python scripts/build_rink.py --quick --no-market --no-light` | smoke check |
| Rebuild everything | `uv run python scripts/build_rink.py --force --all-games` | after a model change or a refit: light seasons and every page-season game page |
| Preview | `python -m http.server` in `docs/rink`, then http://localhost:8000 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/nhl` | 103 test functions in the working tree (102 at `21cce5e`), offline |
| Current season by hand | `python scripts/nhl_hydrate.py`, then `python scripts/nhl_fetch.py --refresh-current --budget 3000` | what CI does |
| Backfill | `powershell -File scripts/nhl_backfill.ps1 -Which nhl\|espn\|moneypuck\|all` (`-From 2009 -To 2025` by default) | detached hidden workers, resumable: re-run to pick up where they stopped; logs `logs/nhl_backfill_{nhl_a,nhl_b,espn,moneypuck}.log`; [DATA_PIPELINE.md](DATA_PIPELINE.md) section 10 |
| Coverage report | `python scripts/nhl_fetch.py --report --from 2009 --to 2026` | per-season counts from the stores and the raw files; no network |
| Canon check | `python scripts/nhl_fetch.py --check-canon --from 2009 --to 2026` | clubs and divisions against `/v1/standings`; exit 1 on a mismatch |
| Shot and player fits (builder B) | `python -m oddsmarkets.nhl.models.fit_b` (every season with derived events, the current one included; pass 8-digit ids to choose, e.g. `20092010 ... 20252026`) or `python scripts/nhl_fit.py --only b` (completed seasons only) | xG, stabilisation, the RAPM prior, the value model → `oddsmarkets/nhl/models/fitted/`; commit the files |
| Team, game and season fits and the backtest (builder C) | `python -c "from oddsmarkets.nhl.models import fit_c; print(fit_c.fit_all())"` | team-strength carry-over, walk-forward rows, the game model, award models, the se_scale scan, the backtest → `team_strength_params`, `game_params`, `awards_fit`, `season_sim_params` and `docs/rink/data/calibration.json`; commit them. `scripts/nhl_fit.py --only c` does **not** do this today ([MODELS.md](MODELS.md) section 16.2, item 14) |
| Everything | `fit_b`, then `fit_c.fit_all()`, then `scripts/nhl_fit.py` (builder B again on completed seasons only), then `build_rink.py --force` | the order of [MODELS.md](MODELS.md) section 14.3 |
| Clear model caches | delete `data/nhl/cache/` except `espn/` and `stats_seasons.json` | after a model change that does not bump a version string |
| JS syntax | `node --check docs/rink/assets/js/<file>.js` where Node is available | there is no automated JS check |

### The refit after the 1 October backfill

The committed fits and `calibration.json` of 1 October 2026 were made mid-backfill (xG on
two seasons; the game model and backtest on four seasons rated on goals only). When the
backfill finishes (expected about 03:15 EDT on 2 October 2026):

1. Confirm it finished: both `logs/nhl_backfill_nhl_{a,b}.log` end with a `calls:` line, and
   `python scripts/nhl_fetch.py --report --from 2009 --to 2026` shows events and stints for
   every season from 2010–11 (2009–10: events only) and lines for 2019–20 on.
2. Refit in the order of [MODELS.md](MODELS.md) section 14.3 (builder B, then
   `fit_c.fit_all()`, then `scripts/nhl_fit.py`).
3. Rebuild with the deployed payloads under the local ones and `--force` (section 6), read
   the new `calibration.json` and update [MODELS.md](MODELS.md) sections 2, 8–10, 12–14 and
   the Methodology's figures (`docs.js`), resolving the open items of section 16.
4. Commit the fitted files, `calibration.json` and the completed seasons' stores
   (section 5), and hand-deploy (section 6).

---

## 5. Committing a completed season

Do this once the season is over (after the Stanley Cup Final in June; the store should hold
no scheduled or live game), and before 1 July if possible (on 1 July `canon.current_season`
turns over and CI starts hydrating the next season).

1. **Bring the store up to date locally**: `python scripts/nhl_hydrate.py --season <S>`,
   then a last pass so every game's raw files, lines and the derived tables are in:
   `python scripts/nhl_fetch.py --seasons <S>`.
2. **Check it**: `python scripts/nhl_fetch.py --report --seasons <S>`; every game final, with
   play-by-play, shifts, boxscores, lines and an on-ice agreement near 0.99.
3. **Refit and backtest** (section 4); update the figures in `docs/nhl/MODELS.md` section 14
   and the Methodology (`docs.js`) if they moved.
4. **Commit on `main`**, by explicit path (the `.gitignore` also un-ignores the current
   season's store):

   ```bash
   git add docs/rink/data/<S>/store.json docs/rink/data/calibration.json \
           oddsmarkets/nhl/models/fitted/
   ```

5. **Deploy**: nothing to do; the next CI run restores and redeploys. If the refit changed
   past seasons' payloads, publish them by hand (section 6).

**On 1 October 2026 no store was committed yet**: `docs/rink/data/` is wholly untracked.
After the backfill and the refit, commit every completed season's store (2009–10 to
2025–26) and `calibration.json` this way, once.

---

## 6. Rebuilding past seasons

CI never rebuilds a past season: it has only the current season's raw data, so a past
season is skipped ("events not on this machine; payloads kept") and its payloads come from
the previous deploy. A model change, a fix in a catalogue or a refit therefore reaches past
seasons only through a local rebuild and a hand deploy:

```bash
# 1. the raw data and derived tables for the seasons to rebuild
powershell -File scripts/nhl_backfill.ps1 -Which nhl          # resumable; skips what is on disk

# 2. the current season from the live site, and the deployed payloads under the local ones
python scripts/nhl_hydrate.py
git clone --depth 1 git@github.com:pchattani/the-quant-rink.git /tmp/prev
rsync -a --ignore-existing /tmp/prev/data/ docs/rink/data/

# 3. rebuild (light seasons are forced; game pages for the page seasons)
python scripts/build_rink.py --force                           # every season
python scripts/build_rink.py --seasons 20242025 --force        # or one season in full

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
| NHL api-web, stats REST (and www.nhl.com HTML reports) | none published; 3–5 requests a second tolerated | 0.25 s per host and a 0.25 s global gap by default (0.6 s per backfill worker); 429 or 5xx: `Retry-After` or 10 s × attempt, 4 attempts; budget per run | raise `--interval` / `--min-gap`; the run resumes next time |
| NHL EDGE | as api-web; 404 for seasons before 2021–22 and untracked players | a 404 is remembered (`"none"`) and not asked again for a completed season | – |
| ESPN site and core APIs | none stated | 1 s spacing (`--espn-interval`) | raise it; the run resumes next time |
| MoneyPuck | file downloads only, at most nightly, non-commercial with credit | HEAD first; a completed season once; the current season at most once in 20 hours; 2 s spacing | the previous file is kept |
| Kalshi, Polymarket | public read APIs | one pass per build; failures give empty futures | `--no-market` to skip |

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `RINK_REPO` or `RINK_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| No runs for hours | GitHub dropped the scheduled runs and the local task is not dispatching (machine off, no token from `git credential fill`) | check `scripts/refresh_sofascore.log`; dispatch by hand |
| Dispatch logs "(404) Not Found" | the workflow file is not on `main` (seen at 19:04 EDT on 1 October 2026) | merge it to `main` |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| "cold build" in the restore step, then a site without past seasons | the public repo could not be cloned | check the key; never let a cold build deploy over a good site: re-push the last good deploy by hand (section 2) |
| The current season goes backwards (games, lines or goalies missing that were there) | the hydrate step failed, so the build ran on the checkout's (or no) current store | check the hydrate log; re-run the workflow; recover with a local `nhl_fetch.py --seasons <S>` and a hand deploy |
| A game page without shifts or lines the morning after | the shift chart was empty or the game had not settled | wait for the next runs (a game is re-read once settled; an empty chart falls back to the HTML reports) |
| `xg_source` "fallback" in a manifest | the xG fit is missing from the cache and from `models/fitted/`, or raised | read the build log; refit builder B and commit |
| `model_errors` lists a model | its fit is missing or it raised | read the traceback in the build log; refit and commit |
| Playoff odds empty, `sim_reason` set | the season simulation failed or had no ratings | read the build log; the standings page still shows standings and seeds |
| Award races empty with "award model not fitted" | `awards_fit.json` has no fitted award (the 1 October state) | `fit_c.fit_all()` on the full history and commit |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_rink.py` locally and read the traceback |
| Futures missing | Kalshi or Polymarket changed a series or title, or the field is thin | the series names and patterns are in `sources/markets.py` |
| `TimeoutError: lock … held too long` in a fetch | another writer held the store's lock past 900 s | re-run; a lock older than 120 s is broken automatically |
| A backfill worker seems stuck | check its log's last line and whether its PID is alive | re-run `nhl_backfill.ps1` for that `-Which`: it resumes from the files on disk |
| Public repo updated but the live site is not | Pages did not start a build | Settings → Pages; `POST /repos/pchattani/the-quant-rink/pages/builds` |

---

## 9. Seasons and calendar

| When | What |
|---|---|
| Game nights (most evenings October to June) | nothing by hand: the `:02/:17/:47` runs join the hourly one inside game windows, so the site moves every 15 minutes |
| The morning after | games are re-read once settled (after noon UTC the day after); shift-based blocks, lines and goalies fill in |
| Weekly | rosters and EDGE refresh in the current season; the season reports at most every 20 hours |
| June | the Stanley Cup Final ends the season; commit the completed season (section 5); refit |
| 1 July | `canon.current_season` turns over. The hydrate finds no store for the new season (fine); the next fetch builds it from the schedule once the NHL lists it. Check: `canon.formats` (games per team, playoff format), `canon.teams` and the division tables (run `--check-canon`), new arena names in `canon.ARENAS` aliases, ESPN team ids, the Kalshi series suffix (the season's end year) in `sources/markets.py`, the award winners table (`models/award_winners.py`: add the season just finished), the lottery odds in `season_sim.LOTTERY_ODDS` if the format changes. Note `_cdata.season_of_date` and `markets.season_for` turn over on 1 August ([MODELS.md](MODELS.md) section 16.2, item 13) |
| September | the preseason; the season window opens with the stats REST season dates |
| When a source changes a field | the parsers in `sources/{nhl,stats,edge,espn,moneypuck,markets}.py`, then `CONTRACT.md` and the fixtures in `tests/nhl/fixtures/` |

---

## 10. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `RINK_REPO` | Actions variable (`pchattani/the-quant-rink`) | `pchattani/oddsmarkets` | the restore and deploy steps |
| `RINK_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | the restore and deploy steps |
| deploy key "oddsmarkets update_rink.yml" | deploy key, write | `pchattani/the-quant-rink` | cloned and pushed to by the workflow |
| `RINK_DATA`, `RINK_RAW`, `RINK_CACHE` | environment variables (optional; `--data`, `--raw`, `--cache` on the scripts) | local, tests | point stores and payloads, the raw files and the caches elsewhere |
| `RINK_THREADS` | environment variable (optional) | local | LightGBM threads (default 2 under 100,000 rows, else up to 16) |
| `GH_TOKEN` | environment variable (optional) | the owner's machine | `setup_public_site.py` (else Git's credential manager) |

No API keys: the NHL APIs, ESPN, MoneyPuck, Kalshi and Polymarket all serve public data
without one. The workflow's `GITHUB_TOKEN` has `contents: read` only. The local key pair is
kept at `~/.ssh/oddsmarkets_RINK_DEPLOY_KEY.base64.txt`. Terms to keep: NHL data
for informational, non-commercial use; MoneyPuck's data with the credit "xG benchmark data
from MoneyPuck.com", non-commercially, downloads at most nightly; all in the disclaimer, the
footer and the glossary.
