# Runbook — The Quant Bullpen

How to run, publish, check and repair the baseball site day to day. For how the pieces fit
together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and front-end in
depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md) and
[DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Bullpen Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | `:07` every hour, and on dispatch | `.github/workflows/update_bullpen.yml`: restore the current season's pitch tables and the model caches and the previous deploy's payloads, hydrate each level's current store from the live site, fetch MLB and Triple-A (Stats API, Savant yesterday and today, ESPN lines), build, prune old game pages, rsync `docs/bullpen/` to the public repo. Commits nothing to `oddsmarkets`. |
| Local hourly task | the owner's Windows machine, scheduled task "Sofascore Refresh (all)" running `scripts/refresh_sofascore_all.ps1` | hourly | refreshes the football site's Sofascore stores, then **dispatches every site's workflow** (`update_bullpen.yml` among them) through the GitHub API, because GitHub drops many scheduled runs under load (on 1 October 2026 the Paddock got 2 scheduled runs in 15 hours, the Hardwood 1, the Ace none). The workflow's concurrency group keeps a dispatched run from overlapping a scheduled one. Log: `scripts/refresh_sofascore.log`. |
| Public site repo | `pchattani/the-quant-bullpen` (public) | pushed by the workflow | a `--delete` mirror of `docs/bullpen/` (stores, `people.json` and `calibration.json` included); never edit it by hand except for a deliberate hand deploy (sections 2 and 7) |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-bullpen/ |
| Backfill, fits, backtest, completed seasons, past-season rebuilds | the owner's machine | by hand | `mlb_backfill.ps1`, `mlb_fit.py`, the backtest, committing stores and fits, hand deploys |

**The deploy model in one paragraph.** The engine is private; the site is a public repo
served by Pages. CI never commits: it restores the previous deploy's payloads, hydrates each
level's current store from the live site, fetches, builds, prunes game pages older than the
previous season and pushes the result to the public repo. So **the deployed site is the store
of record for the current season**, whose store is never committed; completed seasons' stores
(with `people.json`, `calibration.json` and the fits) are committed to `oddsmarkets` by hand.
The very first deploy is pushed by hand from a local build, because a cold CI run has no
previous deploy to restore, only the current season's pitch table, and no Retrosheet.

---

## 2. First-time publication

**Done on 1 October 2026.** Both public repos, `pchattani/the-quant-gridiron` and
`pchattani/the-quant-bullpen`, were created and their first deploys pushed by hand that day;
`https://pchattani.github.io/the-quant-bullpen/` is live. The rest
of this section is kept for a rebuild from scratch (or a new site): check section 11's secrets
and variables rather than assuming them.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site bullpen
```

With `--site bullpen` (the `SITES["bullpen"]` entry) it does, each step skipped when already
done:

1. creates the public repo `pchattani/the-quant-bullpen` with a README so `main` exists,
   description "The Quant Bullpen: MLB odds, pitch-level models, game simulations and
   Statcast-era analytics. Built hourly.", homepage the Pages URL;
2. adds a deploy key titled "oddsmarkets update_bullpen.yml" with **write** access, reusing
   the key pair saved at `~/.ssh/oddsmarkets_BULLPEN_DEPLOY_KEY.base64.txt` (a
   new ed25519 pair is generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret `BULLPEN_DEPLOY_KEY` in
   `pchattani/oddsmarkets` (sealed with the repo's public key, PyNaCl);
4. sets the Actions variable `BULLPEN_REPO = pchattani/the-quant-bullpen`;
5. turns on Pages from `main`, root, and asks for HTTPS;
6. with `--run`, dispatches `update_bullpen.yml` once. **Do not pass `--run` before the first
   hand deploy** (below): a cold CI run would publish a site without past seasons or history.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds; it needs the
`repo` and `workflow` scopes. (The script's docstring still describes only the football site;
`--site` selects the Bullpen.)

**The first deploy is pushed by hand** from a local build: a cold CI run would have no previous
deploy to restore, only the current season's pitch table and no Retrosheet tables, so past
seasons, careers and history would be missing. From then on each CI run restores the previous
deploy and hydrates the current season from it. Wait for the backfill (section 5) before the
first deploy, so every season is in. Then (Git Bash):

```bash
# 1. a complete local build
python scripts/mlb_fetch.py --level mlb --refresh-current      # the current season up to date
python scripts/mlb_fetch.py --level aaa --refresh-current
python scripts/build_bullpen.py --game-page-seasons 2          # full build (slow when the model caches are cold)

# 2. a clone of the public repo, filled the way the workflow fills it
git clone git@github.com:pchattani/the-quant-bullpen.git /tmp/site
rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/bullpen/ /tmp/site/

# 3. prune game pages older than the previous season, as the workflow's prune step does
Y=$(date -u +%Y)
for d in /tmp/site/data/{mlb,aaa}/[0-9]*/; do [ -d "$d" ] || continue
  y=$(basename "$d"); [ "$y" -le $((Y-2)) ] && rm -rf "$d/games"; done

# 4. publish
cd /tmp/site && git add . && git commit -m "Site update (by hand)" && git push
```

The local `docs/bullpen/data/` was about 540 MB on 1 October 2026 and about 1.05 GB on
2 October, after the backfill and the first Triple-A build (two seasons of game pages per
level: MLB about 345 MB, Triple-A about 315 MB; everything else about 390 MB). A push of that
size needs `git config http.postBuffer 524288000` and may need to be split into several
commits (for example `data/<L>/<S>/games/` one season at a time). GitHub Pages'
published-site limit is 1 GB, which the full tree now exceeds: prune further before a hand
deploy (for example Triple-A game pages to the current season only). Then dispatch the
workflow once (Actions tab, "Run workflow", or `setup_public_site.py --site bullpen --run`) and
check that its restore step cloned the public repo.

**By hand instead of the script**: create the public repo with a README and Pages from `main`
root; add the public key as a deploy key with write access; in `pchattani/oddsmarkets` set the
secret `BULLPEN_DEPLOY_KEY` (base64 of the private key file) and the variable `BULLPEN_REPO`;
push the first deploy as above; run "Bullpen Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has `index.html`,
`assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub. Without `BULLPEN_REPO` the
workflow builds and logs "build only, no deploy"; without a public repo the restore step logs
"public repo not cloned (first run?): cold build".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Bullpen Hourly Update" | a green run every hour (scheduled or dispatched); the restore, hydrate and fetch steps may show as failed-but-continued |
| The dispatches go out | `scripts/refresh_sofascore.log` | "dispatched update_bullpen.yml" every hour |
| The site is current | `https://pchattani.github.io/the-quant-bullpen/data/index.json`, `updated_at` | within the last couple of hours |
| The live stores moved | `…/data/mlb/<S>/store.json`, `updated_at` | within the last couple of hours in the season |
| Yesterday's pitches landed | a game page from yesterday: Pitches tab | pitch-by-pitch present (Savant posts a day's pitches overnight; the day is re-pulled until it settles) |
| Lines | the fetch log's `espn: … final games mapped, … with lines` | every final game mapped and with lines |
| Build errors | the Build step's log ends with "N step errors" and lists them | 0, or known ones |
| Models | `model_errors` in `<L>/<S>/hitters.json` and the manifest | `{}` |
| Markets | `mlb/<S>/markets.json` present and non-empty in the season | futures and games quoted |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_bullpen.py` | each level's current season full, the rest light (unchanged light seasons skipped) |
| Quick build | `uv run python scripts/build_bullpen.py --quick --no-market --no-light` | smoke check |
| Rebuild everything | `uv run python scripts/build_bullpen.py --force --all-games` | after a model change: light seasons and every page-season game page |
| Preview | `python -m http.server 8897` in `docs/bullpen`, then http://127.0.0.1:8897 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/baseball` | 247 tests, about 3 minutes, offline (15 October 2026) |
| Current season by hand | `python scripts/mlb_hydrate.py`, then `python scripts/mlb_fetch.py --level mlb --refresh-current --budget 900` (and `--level aaa --budget 300`) | what CI does |
| Coverage report | `python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026` | per-season counts from the stores and pitch tables |
| The committed fits | `python scripts/mlb_fit.py` (MLB; `--levels mlb aaa`, `--only b c d proj`, `--season <S>`) | pitch models on the four seasons before and through `--season`, builder C's fits, the transition tables, the weather effects (`weather_mlb.json`) and the league event counts by day (`league_days_mlb.json`, the game model's season environment in CI), the projection aggregates; writes `oddsmarkets/baseball/models/fitted/`; commit the files |
| The game backtest | `uv run python -c "from oddsmarkets.baseball.models import backtest as B; B.write_calibration('mlb', games=B.run('mlb'), checks=B.model_checks('mlb'))"` | every pitch season from 2016, 1,000 simulations a game, projections refitted every 7 days; about 5–6 minutes a season on the owner's machine (2016–2026, 25,374 games, about 60 minutes on 2 October 2026; 856 s for 2026 alone on 1 October); per-season partials cached under `data/baseball/cache/backtest/` (`mlb_<S>_n1000_v<VERSION>.json`; bump `backtest.VERSION` after a model change so stale partials are not reused) so it resumes; writes `docs/bullpen/data/mlb/calibration.json` (the next build re-merges the xwOBA+, fielding and framing checks); commit it |
| Retrosheet for one season | `python scripts/mlb_retro.py --from <S> --to <S> --refresh --lahman` | when Retrosheet publishes a season (in the winter) |
| Clear model caches | delete `data/baseball/cache/` subfolders (keep `chadwick/`, `lahman/`, `feeds/`, `savant/leaderboards/` and `backtest/`) | after a model change that does not bump a version string |
| JS syntax | `node --check docs/bullpen/assets/js/<file>.js` where Node is available | there is no automated JS check |

---

## 5. The backfill

`scripts/mlb_backfill.ps1` starts the historical backfill as detached, hidden PowerShell
processes, newest season first; every step is resumable (re-running the script picks up where
the logs stop):

```
powershell -File scripts/mlb_backfill.ps1 -Which savant   # Savant MLB 2025→2015 (schedule, statcast, games, people,
                                                          #   leaderboards), then Triple-A 2026→2023 (schedule, statcast, people)
powershell -File scripts/mlb_backfill.ps1 -Which espn     # ESPN lines 2025→2015 (schedule, espn; ≤ 1 request a second)
powershell -File scripts/mlb_backfill.ps1 -Which retro    # Retrosheet 2025→1901 with the Lahman cross-check
powershell -File scripts/mlb_backfill.ps1 -Which all      # all three; -From 2015 -To 2025 by default
```

The script prints each process's PID; the logs are `logs/mlb_backfill_savant_mlb.log`,
`logs/mlb_backfill_savant_aaa.log`, `logs/mlb_backfill_espn.log` and
`logs/mlb_backfill_retro.log`. The Savant and ESPN processes write the same stores safely (the
lock and per-phase ownership, [DATA_PIPELINE.md](DATA_PIPELINE.md) section 7). Costs measured on
1 October 2026: Savant about 35 minutes and 260 calls an MLB season (3 s pacing, 7–10 s a
request); ESPN about 50 minutes and 2,670 calls a season; Retrosheet 885 s for 125 seasons.

**After the backfill**, in order:

1. Check coverage: `python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026` (and
   `--level aaa --from 2023 --to 2026`): every final game with Statcast, lines and lineups.
2. Refit (section 4): `python scripts/mlb_fit.py` (only MLB's fits are committed; `--levels mlb
   aaa` would add Triple-A files nothing commits yet). While a season is in progress, refit the
   pitch models through the last completed season, `python scripts/mlb_fit.py --only b --season
   <S-1>`, so the committed Stuff+, Location+, Pitching+ and swing fits stay out-of-sample for
   the current season as the local build's are (the default fits through the latest season on
   disk). Done on 2 October 2026: builder B through 2025 (unchanged), C, D and the projection
   aggregates through 2026.
3. Re-run the backtest over 2016–2026 (section 4) so the Calibration page covers every season.
4. Build locally (`build_bullpen.py --force`) and commit the completed seasons (section 6).
5. If the site is already live, hand-deploy the rebuilt past seasons (section 7).

---

## 6. Committing a completed season

The stores of completed seasons are committed by hand, once, by explicit path (the
`.gitignore` also un-ignores the current season's store). **As of 2 October 2026 none is
committed**: the backfill is finished and MLB 2015–2025 and Triple-A 2023–2025 are ready to
commit.

For the backfilled seasons, once section 5 is done:

```bash
git add docs/bullpen/data/mlb/2015/store.json ... docs/bullpen/data/mlb/2025/store.json \
        docs/bullpen/data/aaa/2023/store.json docs/bullpen/data/aaa/2024/store.json docs/bullpen/data/aaa/2025/store.json \
        docs/bullpen/data/people.json docs/bullpen/data/mlb/calibration.json \
        oddsmarkets/baseball/models/fitted/
```

For each new season, after the World Series (late October or early November; the store should
hold no scheduled or live game) and before 1 January if possible (the workflow's season is the
calendar year):

1. **Bring the stores up to date locally**: `python scripts/mlb_hydrate.py --season <S>`, then a
   last pass so the final schedule, every pitch, the feeds and the closing lines are in:
   `python scripts/mlb_fetch.py --level mlb --from <S> --to <S>` (and `--level aaa`).
2. **Check them**: the coverage report for the season.
3. **Refit and backtest** (section 4): `mlb_fit.py --season <S>`; the backtest; update the
   figures in `docs/baseball/MODELS.md` and the Methodology (`docs.js`) if they moved.
4. **Commit on `main`** the two stores, `people.json`, `calibration.json` and the fits, by
   explicit path.
5. When Retrosheet publishes the season (in the winter), parse it (`mlb_retro.py`) and rebuild
   the history and careers locally, then hand-deploy them (section 7).

---

## 7. Rebuilding past seasons

CI never rebuilds a past season: it holds only the current season's pitch tables and no
Retrosheet, so a past season is skipped ("pitch table not on this machine; payloads kept") and
`history.json` is kept as deployed. A model change, a catalogue fix, a refit or a new Retrosheet
season therefore reaches past seasons only through a local rebuild and a hand deploy:

```bash
# 1. the pitch tables and Retrosheet for the seasons to rebuild (the backfill, or mlb_fetch / mlb_retro)

# 2. the current seasons from the live site, and the deployed payloads under the local ones
python scripts/mlb_hydrate.py
git clone --depth 1 git@github.com:pchattani/the-quant-bullpen.git /tmp/prev
rsync -a --ignore-existing /tmp/prev/data/ docs/bullpen/data/

# 3. rebuild
python scripts/build_bullpen.py --force                              # every season, history and careers
python scripts/build_bullpen.py --levels mlb --seasons 2024 --force   # or one season in full

# 4. hand deploy as in section 2 (rsync into a fresh clone, prune old game pages, push)
```

Game pages of seasons older than the previous one are pruned on every CI run, so rebuilding
them has no lasting effect on the public site. Push while no CI run is in progress (or right
after one), so the next run restores your deploy rather than overwriting it.

---

## 8. Rate limits and sources

| Source | Limit | What the code does | If it misbehaves |
|---|---|---|---|
| Baseball Savant | a silent 25,000-row cap per search; no stated rate limit | 3 s spacing, one day a request, the cap re-split by halves then by pitching team; days re-pulled until settled | raise `--savant-interval`; a failed day is retried next run |
| MLB Stats API | none stated | 0.5 s spacing; 429 or 5xx: `Retry-After` or 10 s × attempt, 4 attempts; feeds trimmed with `fields` | the run resumes next time |
| ESPN site and core APIs | none stated | 1 s spacing; the same retries | 504s were seen during the backfill and retried |
| Retrosheet, SABR Box (Lahman), GitHub raw (Chadwick) | none stated | 1 s spacing (0.2 s for GitHub raw); zips and shards downloaded once and cached | re-run; `--redownload` to refresh the zips |
| Kalshi, Polymarket | public read APIs | one pass per build | nothing; `--no-market` to skip |

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `BULLPEN_REPO` or `BULLPEN_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| No runs for hours | GitHub dropped the scheduled runs and the local task is not dispatching | check `scripts/refresh_sofascore.log`; dispatch by hand |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| "cold build" in the restore step, then a site without past seasons | the public repo could not be cloned | check the key; never let a cold build stand: re-push the last good deploy by hand (section 2) |
| The fetch step times out at 15 minutes for days | the pitch-table cache was evicted (a cold season is about 205 Savant requests) | it catches up over several runs (newest days first; parts kept); or fetch locally and let the next run restore the cache |
| The current season goes backwards | the hydrate step failed, so the build ran on the checkout's (or no) current store | check the hydrate log; re-run; recover with a local `mlb_fetch.py --from <S> --to <S>` and a hand deploy |
| Game pages without pitches | Savant has not posted the day yet, or the day failed | it is re-pulled until settled; check the fetch log for "Savant request failed" |
| Games without lines | ESPN event unmatched (a postponement, a start more than 30 hours off) | the fetch log's "final games mapped"; re-run `mlb_fetch.py --phases espn` for the season |
| Postseason teams shown as "NL Higher Seed" | the Stats API's placeholder teams before a series is set | expected; the next schedule read replaces them |
| `model_errors` lists a model | its fit is missing from the cache and from `models/fitted/`, or it raised | read the build log's traceback; refit (`mlb_fit.py`) and commit |
| History or careers lost their Retrosheet rows | a local build without the Retrosheet tables was hand-deployed | re-run `mlb_retro.py` (or restore `data/baseball/retro/`), rebuild, redeploy |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_bullpen.py` locally and read the traceback |
| Public repo updated but the live site is not | Pages did not start a build | Settings → Pages; `POST /repos/pchattani/the-quant-bullpen/pages/builds` |

---

## 10. Seasons and calendar

| When | What |
|---|---|
| Every game day | nothing by hand: the hourly run reads two schedule weeks, yesterday's and today's Savant days, live feeds and lines |
| Late March | Opening Day (the season window opens on 10 March for openers abroad); the season simulation and projections take over from last season's ratings |
| Late September – early November | the postseason (Wild Card, Division Series, LCS, World Series); the bracket and series odds on the hub and the postseason page |
| After the World Series | commit the completed season (section 6); refit; backtest |
| Winter | Retrosheet publishes the season just finished: parse it and rebuild history (section 6, step 5) |
| 1 January | the current season turns over (calendar years; the workflow's prune and `canon.current_season`). The hydrate 404s for the new season (fine); the first schedule read creates the store. Check: `canon.TEAMS` (renames, relocations, league moves), the Kalshi series suffixes (the season's two digits) and Polymarket titles in `sources/markets.py`, the award winners table (`models/awards.py` `WINNERS`: add the finished season), the ABS rules (`mlb_fetch.ABS_FROM`), any new Savant columns |
| When a source changes a field | the parsers in `sources/{savant,statsapi,espn,retrosheet,chadwick,lahman,markets}.py`, then `CONTRACT.md` and the fixtures in `tests/baseball/fixtures/` |

---

## 11. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `BULLPEN_REPO` | Actions variable (`pchattani/the-quant-bullpen`) | `pchattani/oddsmarkets` | the restore and deploy steps |
| `BULLPEN_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | the restore and deploy steps |
| deploy key "oddsmarkets update_bullpen.yml" | deploy key, write | `pchattani/the-quant-bullpen` | cloned and pushed to by the workflow |
| `BULLPEN_DATA`, `BULLPEN_RAW`, `BULLPEN_CACHE` | environment variables (optional; `--data`, `--raw`, `--cache` on the build) | local, tests | point stores and payloads, pitch tables and Retrosheet, and the caches elsewhere |
| `GH_TOKEN` | environment variable (optional) | the owner's machine | `setup_public_site.py` (else Git's credential manager) |

No API keys: Savant, the Stats API, ESPN, Retrosheet, the Chadwick register, Lahman, Kalshi and
Polymarket all serve public data without one. The workflow's `GITHUB_TOKEN` has `contents: read`
only. The local key pair is kept at
`~/.ssh/oddsmarkets_BULLPEN_DEPLOY_KEY.base64.txt` once the set-up has run.
Notices and licences to keep: the Retrosheet notice verbatim wherever its data appears, the
Chadwick register's ODC-BY attribution, Lahman CC BY-SA, MLBAM data for non-commercial,
informational use (raw feeds and pitch tables never re-hosted); all in the disclaimer, the
footer and the history payload's `meta`.

---

## 12. NPB (the npb level)

Added 13 October 2026. Code in `oddsmarkets/baseball/npb/`, fetch `scripts/npb_fetch.py`, backfill
`scripts/npb_backfill.ps1`, pages `docs/bullpen/assets/js/npb.js` and `assets/npb.css`. Data from npb.jp only
(plus Kalshi's NPB markets); see [DATA_PIPELINE.md](DATA_PIPELINE.md) section 14 for the pages and their terms and
[MODELS.md](MODELS.md) section 23 for the models and the backtest.

| Job | Command | Notes |
|---|---|---|
| Hourly (automatic) | `scripts/local_sites.py`, site "bullpen", step "Fetch NPB": `npb_fetch.py --refresh-current --budget 400` | March to November only (exits at once otherwise): the last four days' day pages, new box scores, this and next month's schedule (probable starters, games not yet played), every six hours the current rosters and the clubs' stat pages, Kalshi prices. About 25 requests an hour, 85 when the stat pages are due; 8-minute step timeout. The build step (`build_bullpen.py`) builds the npb payloads with the other levels. |
| Backfill | `powershell -File scripts/npb_backfill.ps1` (default 2005-2026 games, 1950 on history and rosters, every player) | one detached hidden process, 1.5 s between requests, about 35,000 requests and 14-15 hours; log `logs/npb_backfill.log`; resumable (the page cache and the stores) |
| Monitor the backfill | `Get-Content logs\npb_backfill.log -Tail 20` and `python scripts/npb_fetch.py --report --from 2005 --to 2026` | the report counts games, finals, ties, box scores and player rows per season, history seasons, rosters, players |
| Backtest and parameters | `uv run python -c "from oddsmarkets.baseball.npb import backtest as B; B.run()"` | refits the rating parameters on 2006-2015, scores 2016 on, writes `docs/bullpen/data/npb/calibration.json` and `npb/stores/model_params.json` (the build reads them); a few minutes |
| One season again | `python scripts/npb_fetch.py --from <S> --to <S> --phases days,boxes,stats` | cached pages are not fetched again; delete `data/baseball/npb/html/bis/<S>/` to force it |
| Kalshi history | `python scripts/npb_fetch.py --phases kalshi --from 2026 --to 2026` | every settled KXNPBGAME market and its candles (cached under `data/baseball/cache/kalshi_npb/`) |
| Build NPB alone | `uv run python scripts/build_bullpen.py --levels npb` | about 30 seconds (the lab and value files included); `--force` rebuilds every season |
| Play-by-play (2016 on) | `powershell` detached, as the backfill: `.venv\Scripts\python.exe scripts/npb_fetch.py --phases pbp --from 2016 --to 2026 --interval 1.5 --budget 30000 --log logs/npb_pbp.log` | one request a game (the box score too for complete games and the current season), about 2.6 s a game with the network: ~38 minutes a season, ~6.5 hours for 2016-2025; resumable; the hourly job adds the last three days' games. `--reparse` re-reads every cached page after a parser change (no network); `--pbp-boxes` also reads every box score (pitch counts for 2016-2025, ~8,800 more requests) |

**Committing.** `docs/bullpen/data/npb/<S>/store.json` (completed seasons) and `docs/bullpen/data/npb/stores/*.json`
(history, rosters, people, model parameters) are un-ignored for commits by explicit path, like the MLB stores; none
of them is deployed (`prune_bullpen`). `calibration.json` is deployed.

**Season calendar.** Openers in late March; interleague in late May and June; the regular season ends in late
September or early October; the Climax Series (First Stage about 10-12 October, Final Stage from about 14 October);
the Japan Series from late October (games 1-2 and 6-7 at the Central champion's park in even years). After the
Japan Series: re-run the backtest, commit the season's store and the stores. On 1 January check `npb/canon.py`
(club renames, the DH, extra-inning rules, the Climax Series format) and the Kalshi series (`KXNPBGAME`, `KXNPB-<yy>`).

**If a page layout changes.** The parsers are in `npb/source.py`, each tested on a recorded page in
`tests/baseball/fixtures/npb/`. The 2026 season already moved the day pages to a new layout (links to `/scores/` box
scores) and dropped the BIS calendar for the current season; `parse_day` and `parse_box` read both layouts.

**If NPB objects.** npb.jp's footer forbids secondary use and reproduction of its content. The site shows only facts
in its own layout and our own derived numbers, never NPB's pages, images or text, and keeps the raw stores off the
public site; if NPB nonetheless objects, remove the level: drop `"npb"` from `build_bullpen.py`'s default levels and
the NPB button in `index.html`, delete `docs/bullpen/data/npb/` from the deploy copy, and stop the "Fetch NPB" step.

## 13. Valuation v2, moves and fantasy (16 October 2026)

- One-time backfill of the Stats API inputs: `python -m oddsmarkets.baseball.analytics.mlbapi --from 2015 --to 2026
  --weekly-from 2022` (about 450 calls, 5 minutes) and the minor-league season lines (`mlbapi.season_lines(level, season,
  group, mlbapi.client())` for aaa, aa, hia, a; 96 calls). Afterwards the hourly build refreshes the current month and season
  itself (1-3 calls).
- The build: `build_bullpen.build_level` -> `value_build.build_level` builds the valuation context (about 9 s), the current
  season's value.json with the v2 fields, `mlb/moves.json` and `mlb/trades.json` (about 8 s; the trade validation is cached a
  month); after both levels `fantasy_build.build` writes `mlb/fantasy.json` (about 7 s) and `mlb/fantasy_backtest.json` (the
  backtests are cached per season; the first run takes about 6 minutes, then the season under way is recomputed once a day,
  about a minute). Flags: `--no-moves`, `--no-fantasy`, `--no-statsapi` (cache only).
- Checks: `#/mlb/moves?tab=method` (validation numbers), `#/mlb/fantasy?tab=bt` (backtests), `#/mlb/value` (band coverage).
- When the regular season starts the fantasy page switches itself to rest of season and next week (season_sim.phase "regular").
