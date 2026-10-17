# Runbook — The Quant Hardwood

How to run, publish, check and repair the NBA and WNBA site day to day. For how the
pieces fit together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and
front-end in depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md) and
[DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day. Commands run
from the repository root.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Hardwood Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | hourly at :47, and on demand | `.github/workflows/update_hardwood.yml`: restore raw play-by-play and model caches, restore the previous deploy, hydrate the current season from the live site, fetch ESPN for each league in season, derive, build, prune old game pages, rsync `docs/hardwood/` to the public repo. Commits nothing to this repository. |
| Public site repo | `pchattani/the-quant-hardwood` (public) | pushed by the workflow | a `--delete` mirror of `docs/hardwood/` (without the plain `shots.json` / `stints.json`); never edit it by hand |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-hardwood/ |
| The live site's data | the public repo | every deploy | also the store of record for the **current** season: CI hydrates it back each run (`bb_hydrate.py`) |
| Backfill | the owner's machine, detached | once (1 October 2026, finished) | `scripts/bb_fetch.py` for both leagues, newest season first; completed seasons committed by hand afterwards (done 1 October 2026) |

There is no local scheduled task: ESPN answers GitHub's runners. The private-engine,
public-site split is the same as for football and F1 (Pages is free only for public
repositories).

---

## 2. First-time publication

The site is live. This section is kept for a rebuild from scratch.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site hardwood --run
```

With `--site hardwood` (the `SITES["hardwood"]` entry) it does, each step skipped when
already done:

1. creates the public repo `pchattani/the-quant-hardwood` with a README so `main`
   exists, description "The Quant Hardwood: NBA and WNBA odds, season simulations, shot
   charts, lineups and Savant-style analytics. Built hourly.";
2. adds a deploy key titled "oddsmarkets update_hardwood.yml" with **write** access,
   reusing the key pair saved at
   `~/.ssh/oddsmarkets_HARDWOOD_DEPLOY_KEY.base64.txt` (a new ed25519 pair
   is generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret
   `HARDWOOD_DEPLOY_KEY` in `pchattani/oddsmarkets`;
4. sets the Actions variable `HARDWOOD_REPO = pchattani/the-quant-hardwood`;
5. turns on Pages from `main`, root, and asks for HTTPS;
6. with `--run`, dispatches `update_hardwood.yml` once.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds; it
needs the `repo` and `workflow` scopes. (The script's docstring still describes only
the football site; `--site` selects the Hardwood.)

**The first deploy was pushed by hand** on 1 October 2026 from a local build (408 MB),
because a cold CI run would have had no history: no completed season is committed yet,
and CI fetches only the current season. From then on each CI run restores the previous
deploy and builds on it. To redo it: build locally (`python scripts/build_hardwood.py
--game-page-seasons 3`), delete game pages older than each league's three latest
seasons, then clone the public repo and
`rsync -a --delete --exclude='.git' --exclude='shots.json' --exclude='stints.json' docs/hardwood/ <clone>/`,
commit and push. A push of this size can need `git config http.postBuffer 524288000`.

**By hand instead of the script**: create the public repo with a README and Pages from
`main` root; add the public key as a deploy key with write access; in
`pchattani/oddsmarkets` set the secret `HARDWOOD_DEPLOY_KEY` (base64 of the private key
file) and the variable `HARDWOOD_REPO`; run "Hardwood Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has `index.html`,
`assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub. Without
`HARDWOOD_REPO` the workflow builds and logs "build only, no deploy".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Hardwood Hourly Update" | a green run every hour; fetch, derive, restore and hydrate steps may show as failed-but-continued |
| The site is current | the meta line on the live page | "Updated" within the last couple of hours |
| Games land | yesterday's games on `#/<L>/games` | final scores, box scores, and for play-by-play games flow, win probability and shots |
| The live store moved | `https://pchattani.github.io/the-quant-hardwood/data/<L>/<S>/store.json`, `updated_at` | within the last couple of hours while the league is in season |
| Build errors | the Build step's log ends with "N step errors" and lists them | 0, or known ones |
| Backfill (while running) | `Get-Content logs\bb_backfill_nba.log -Tail 5` in PowerShell (the log is UTF-16) | a progress line every 25 games, about 0.7 s a game |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_hardwood.py` | current seasons full, the rest light (unchanged light seasons skipped) |
| Quick build | `uv run python scripts/build_hardwood.py --quick --no-market --no-light` | smoke check |
| One league, one season | `uv run python scripts/build_hardwood.py --leagues wnba --seasons 2026` | |
| Rebuild everything | `uv run python scripts/build_hardwood.py --force --all-games` | slow: every light season and every game page |
| Preview | `python -m http.server 8897` in `docs/hardwood`, then http://127.0.0.1:8897 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/basketball` | 111 test functions, offline |
| Current season by hand | `python scripts/bb_fetch.py --league nba --refresh-current --budget 600` then `python scripts/bb_derive.py --league nba` | what CI does |
| Current season without ESPN | `python scripts/bb_hydrate.py` | copies the live site's current-season inputs |
| Rosters (ages) | `python scripts/bb_fetch.py --league nba --rosters --phases none --budget 100` | current season only; also run daily by `--refresh-current` |
| Game-model parameters and the live WP model | `python scripts/bb_fit.py` | refits on every store on disk and writes `oddsmarkets/basketball/models/fitted/` (commit it; CI reads it); about 1.5 minutes |
| Backtest | `uv run python -c "from oddsmarkets.basketball.models.backtest import backtest; backtest('wnba')"` (and `'nba'`) | writes `data/basketball/cache/backtest_<L>.json`; the next build turns it into `<L>/calibration.json`, which is then committed |
| Clear model caches | delete `data/basketball/cache/` (keep `game/` and `backtest_*.json` if you want to keep fitted parameters and the backtest) | after a model change that does not bump a version string |
| JS syntax | `uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/hardwood/assets/js/core.js',encoding='utf-8').read())"` | per module |

---

## 5. The backfill, and committing completed seasons

Started on 1 October 2026 at about 00:49 UTC, detached, from the repo root:

```
python scripts/bb_fetch.py --league nba --from 1997 --to 2027 --budget 60000 --interval 0.6   # log: logs/bb_backfill_nba.log
python scripts/bb_fetch.py --league wnba ... (1997-2026)                                      # log: logs/bb_backfill_wnba.log
```

Both passes finished on 1 October 2026 and were followed by `bb_derive.py` for every
season; the steps below were then done the same day (Cup finals relabelled, stray
games removed, derived, packed, committed, refitted, rebuilt, redeployed; see
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3). They are kept as the procedure for a
future backfill or a season's completion. A backfill resumes where it stopped: kill
and restart freely.

**Is it still running?** In PowerShell:
`Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'bb_' } | Select ProcessId, CommandLine`.
Two processes for one backfill is normal (the venv launcher and its interpreter). Then
`Get-Content logs\bb_backfill_nba.log -Tail 5`. The logs are UTF-16 PowerShell
redirections; `tail` and most editors show them garbled.

**When a backfill pass finishes**, in this order:

1. **Check the Cup-final labels and the standings counts.** Each season with a Cup
   final should hold exactly one `cup` game and every team the format's number of
   regular-season games. A re-fetched summary relabels a game `cup` (`merge_game` lets
   `cup` replace `reg`), and the games phase re-fetches any final game without a fetch
   stamp. So drop the stamps and re-run the games phase. Targeted, when the game ids
   are known (from the schedule page or ESPN):

   ```
   uv run python -c "from oddsmarkets.basketball import store as st; s = st.load('wnba', 2024); [s['meta']['fetched'].pop(g, None) for g in ['<game id>']]; st.save(s)"
   python scripts/bb_fetch.py --league wnba --from 2024 --to 2024 --phases games --budget 50
   ```

   Or for whole seasons (robust, about 250 calls per WNBA season and 1,400 per NBA
   season), replace the list with `list(s['meta']['fetched'])`. Check afterwards that
   each repaired season has exactly one game with `stype == "cup"`.
2. **Derive** every completed season (and re-derive the repaired games):
   `python scripts/bb_derive.py --league nba --from 1997 --to 2026` and
   `python scripts/bb_derive.py --league wnba --from 1997 --to 2025`.
3. **Pack**: `python scripts/bb_pack.py` (verifies every `.gz`; skips the current seasons).
4. **Commit the completed seasons only**, on `main`. The `.gitignore` un-ignores every
   season's inputs, current ones included, so add explicitly and leave out NBA 2027 and
   WNBA 2026 (WNBA 2026 becomes completed after its Finals):

   In Git Bash (a missing file would make a plain `git add` of a list fail, hence the
   test):

   ```
   for lg_to in nba:2026 wnba:2025; do lg=${lg_to%%:*}; to=${lg_to##*:}
     for s in $(seq 1997 $to); do for f in store.json recon.json shots.json.gz stints.json.gz; do
       p=docs/hardwood/data/$lg/$s/$f; [ -f "$p" ] && git add "$p"; done; done; done
   git status --short docs/hardwood/data        # nothing from nba/2027 or wnba/2026
   ```

   An NBA season's inputs are about 8 MB (store 3.2 MB, shots 3.5 MB, stints 0.9 MB,
   recon 0.3 MB for 2026), so the full history adds a few hundred MB to the repository.
   CI commits nothing, so there are no conflicts to expect.
5. **Refit and rebuild**: `python scripts/bb_fit.py`, the backtests (NBA 2017–2026 and
   WNBA 2014–2026 were run on 1 October 2026), then
   `python scripts/build_hardwood.py --force --game-page-seasons 3`; commit
   `models/fitted/` and both `calibration.json` files, and compare with
   [MODELS.md](MODELS.md) section 11.2. A cold local model cache makes the first build
   slow (about an hour for the NBA's award history); CI's builds take a few minutes.

**Do not run a second fetcher for a league whose backfill is running**: both write the
same `store.json`, and the last save wins.

---

## 6. Rate limits and sources

| Source | Limit | What the code does | If it misbehaves |
|---|---|---|---|
| ESPN site API | none stated | 0.5 s spacing (0.6 in the backfill); 429 or 5xx: `Retry-After` or 10 s × attempt, 4 attempts; budget per run | raise `--interval`; the run resumes next time |
| ESPN core and v2 APIs | none stated | the same client | |
| `cdn.nba.com`, `stats.nba.com` | blocked by Akamai locally and in CI | not used | — |
| Kalshi, Polymarket | public read APIs | one pass per build; failures give "available: false" | nothing; `--no-market` to skip |

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `HARDWOOD_REPO` or `HARDWOOD_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| "cold build" in the restore step, then a slow or timed-out build | the public repo could not be cloned | check the key; a timed-out build deploys nothing, so the site stays on the last deploy |
| The current season goes backwards (games missing that were there) | hydrate fetched an older store, or the restore failed and the checkout's copy was used | hydrate keeps the newer `updated_at`; check the hydrate step log; re-run the workflow |
| Calibration page says "no cached backtest" | no `backtest_<L>.json` where the build ran and no committed `calibration.json` | run the backtest locally, build, commit `calibration.json` |
| Calibration page: shot-model table "not in this backtest file yet" | front-end bug: `calibration.js` reads `d.shots` instead of `d.shots.by_zone` | HANDOFF Task 20 |
| Game page has box score but no flow or win probability | built where the raw play-by-play was not present, or the WP model could not fit (fewer than 100 states early in a season in CI) | rebuild that season where the raw files are (`--seasons <S> --all-games`) and redeploy |
| Live game pages without model WP in CI | CI's WP model falls back to the current season only (section 12 of [MODELS.md](MODELS.md)) | HANDOFF Task 21 |
| A Cup final counts in the standings | it is stored as `reg` (a game note `canon.stype` does not recognise) | section 5 step 1; add the note to `canon.stype` |
| WNBA seasons before 2002 show no results | ESPN gives those games status `pre` / `in` | known; HANDOFF Task 21 |
| Player ages blank | no date of birth: the player is not on a current roster (retired players stay blank), or rosters were not fetched | `--rosters` |
| Preseason win-total edges missing | hidden on purpose while `phase == "preseason"`: the prior is last season only (the roster term is off: it widened the gap to the market) | HANDOFF Task 18 |
| Fetch steps fail every hour | ESPN down or slow | the build still runs on the hydrated stores; check the step log |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_hardwood.py --leagues <L> --seasons <S>` locally and read the traceback |
| Markets "thin: ..." | too few runners accounted for or implied total outside 0.8–1.3 | normal for award markets and early in a season |
| Public repo updated but the live site is not | Pages did not start a build (seen once on the football site) | Settings → Pages; `POST /repos/pchattani/the-quant-hardwood/pages/builds` |
| Pages warns about site size | the public repo approaches GitHub Pages' recommended 1 GB | lower `--game-page-seasons` and the prune window in the workflow |

---

## 8. Seasons and calendar

| When | What |
|---|---|
| Every game night | nothing by hand: games are fetched at the first hourly run after ESPN marks them final, and again for 48 hours |
| Late September | the NBA's current season turns over (`canon.current_season`: September); the new season's store is created by the first refresh, from the calendar on the 15 January probe day |
| NBA preseason (October) | phase `preseason` until the first counted game; win-total edges hidden; preseason ratings are last season carried forward plus the roster term (`ratings.ROSTER_PRIOR_LEAGUES = ("nba", "wnba")`, on since 2 October 2026) |
| December | the NBA Cup final: check that it is stored as `cup` (it should be, from the summary's game note) and does not count in the standings |
| April | the WNBA's current season turns over (`current_season`: April) |
| Mid-season | the WNBA Commissioner's Cup final: check it is `cup` |
| After each league's Finals | the season is completed: derive, pack and commit its inputs (section 5 steps 2–4); refit (`fit_params`) and re-run the backtest; commit `calibration.json` |
| New season | check `config.py` (team counts, games, play-in, series lengths; WNBA expansion), `canon.FRANCHISE_MOVES` for moves and new teams, `config.WNBA_CONFERENCES` / `NBA_DIVISIONS` and arenas for new teams, `sources/markets.py` `CODE_ALIASES` and the Polymarket titles, and `models/award_winners.py` for last season's winners |
| When ESPN changes a field | the parsers in `sources/espn.py` and `pbp.py`, then `CONTRACT.md` and the fixtures in `tests/basketball/fixtures/` |

---

## 9. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `HARDWOOD_REPO` | Actions variable (`pchattani/the-quant-hardwood`) | `pchattani/oddsmarkets` | restore and deploy steps |
| `HARDWOOD_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | restore and deploy steps |
| deploy key "oddsmarkets update_hardwood.yml" | deploy key, write | `pchattani/the-quant-hardwood` | cloned and pushed to by the workflow |
| `HARDWOOD_DATA`, `HARDWOOD_CACHE`, `HARDWOOD_PBP` | environment variables (optional; `--data`, `--cache`, `--pbp`) | local, tests | point stores and payloads, model caches and raw play-by-play elsewhere |

No API keys: ESPN, Kalshi and Polymarket all serve public data without one. The
workflow's `GITHUB_TOKEN` has `contents: read` only. The local key pair is kept at
`~/.ssh/oddsmarkets_HARDWOOD_DEPLOY_KEY.base64.txt`.
