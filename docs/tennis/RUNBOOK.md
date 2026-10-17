# Runbook — The Quant Ace

How to run, publish, check and repair the tennis site day to day. For how the pieces
fit together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and
front-end in depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md) and
[DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Ace Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | hourly at :27, and on demand | `.github/workflows/update_ace.yml`: restore model caches and the previous deploy's payloads, hydrate the current year's store, registry and style tables from the live site, fetch both tours' current year, build, prune old match pages, rsync `docs/ace/` to the public repo. Commits nothing to `oddsmarkets`. |
| Public site repo | `pchattani/the-quant-ace` (public) | pushed by the workflow | a `--delete` mirror of `docs/ace/` (stores, registries and style tables included); never edit it by hand |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-ace/ |
| Fits, backtest, charting, completed years | the owner's machine | by hand (after a season, or when a model changes) | `tn_fit.py`, `tn_charting.py`, committing stores and fits |

There is no local scheduled task: ESPN, the WTA API and tennis-data answer GitHub's
runners. The deployed site is the store of record for the current year.

---

## 2. First-time publication

The site is live. This section is kept for a rebuild from scratch.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site ace --run
```

With `--site ace` (the `SITES["ace"]` entry) it does, each step skipped when already
done:

1. creates the public repo `pchattani/the-quant-ace` with a README so `main` exists,
   description "The Quant Ace: ATP and WTA odds, exact match models, draw simulations,
   serve/return analytics. Built hourly.";
2. adds a deploy key titled "oddsmarkets update_ace.yml" with **write** access,
   reusing the key pair saved at
   `~/.ssh/oddsmarkets_ACE_DEPLOY_KEY.base64.txt` (a new ed25519 pair is
   generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret `ACE_DEPLOY_KEY` in
   `pchattani/oddsmarkets`;
4. sets the Actions variable `ACE_REPO = pchattani/the-quant-ace`;
5. turns on Pages from `main`, root, and asks for HTTPS;
6. with `--run`, dispatches `update_ace.yml` once.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds; it
needs the `repo` and `workflow` scopes. (The script's docstring still describes only
the football site; `--site` selects the Ace.)

**The first deploy was pushed by hand** on 1 October 2026 from a local build, because
a cold CI run would have had no current-year store (CI fetches only the last few days)
and no payloads to restore. From then on each CI run restores the previous deploy and
hydrates the current year from it. To redo it:

```bash
python scripts/build_ace.py --match-page-years 2          # full local build (slow when caches are cold)
# delete docs/ace/data/<T>/matches/*.json older than last year (the workflow's prune step)
git clone git@github.com:pchattani/the-quant-ace.git /tmp/site
rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/ace/ /tmp/site/
cd /tmp/site && git add . && git commit -m "Site update (by hand)" && git push
```

The local `docs/ace/data/` is about 340 MB; a push of that size can need
`git config http.postBuffer 524288000`.

**By hand instead of the script**: create the public repo with a README and Pages from
`main` root; add the public key as a deploy key with write access; in
`pchattani/oddsmarkets` set the secret `ACE_DEPLOY_KEY` (base64 of the private key
file) and the variable `ACE_REPO`; run "Ace Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has
`index.html`, `assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub. Without
`ACE_REPO` the workflow builds and logs "build only, no deploy".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Ace Hourly Update" | a green run every hour; the restore, hydrate and fetch steps may show as failed-but-continued |
| The site is current | `https://pchattani.github.io/the-quant-ace/data/index.json`, `updated_at` | within the last couple of hours |
| The live stores moved | `…/data/<T>/<year>/store.json`, `updated_at` | within the last couple of hours during the season |
| Yesterday's matches landed | `#/<T>/calendar`, then an event in play | final scores; tennis-data's results and closing odds follow when its workbook updates (usually within a day or two) |
| Identity | the fetch step's log ends with `identity: {...}` | tennis-data `rate` ≥ 0.999; new `unresolved_examples` deserve an `overrides.json` entry |
| Build errors | the Build step's log ends with "N step errors" and lists them | 0, or known ones |
| Markets | the build log's "markets: N match prices, M tournament fields" | non-zero while events are on |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_ace.py` | current year full, the rest light (unchanged light years skipped) |
| Quick build | `uv run python scripts/build_ace.py --quick --no-market --no-light` | smoke check |
| One tour | `uv run python scripts/build_ace.py --tours wta` | |
| Rebuild everything | `uv run python scripts/build_ace.py --force --all-matches` | after a refit: light years and finished match pages are not rebuilt otherwise |
| Preview | `python -m http.server 8898` in `docs/ace`, then http://127.0.0.1:8898 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/tennis` | 156 test functions (197 tests), about 3-5 minutes (5 on a busy machine), offline |
| Current year by hand | `python scripts/tn_hydrate.py`, then `python scripts/tn_fetch.py --tour atp --refresh-current --budget 300` (and `wta`, 400) | what CI does |
| Coverage report | `python scripts/tn_fetch.py --tour wta --report --from 2016 --to 2026` | per-year counts from the stores |
| Elo and serve/return constants | `python scripts/tn_fit.py` (both tours) or `--tours wta`; `--no-elo` / `--no-sr` to keep one | writes `oddsmarkets/tennis/models/fitted/elo_params_<T>.json` (Nelder-Mead, 800 evaluations, a minute or two) and `serve_return_<T>.json` (keeps the committed tuning; refits the frozen model through the latest match); commit them |
| Re-tune serve/return | `serve_return.tune(matches, checkpoints)` from a Python session, then `export_fits(tour, tuned={...})` | the grids in the committed files took minutes per cell; only when the model changes |
| Backtest and blend | `python scripts/tn_fit.py --tours atp --no-elo --no-sr --backtest` (or `python scripts/_tn_backtest_c.py atp`) | about 28 minutes (ATP) and 45 (WTA) with warm caches; writes `data/tennis/cache/backtest_<T>.json`, `docs/ace/data/<T>/calibration.json` and `fitted/predict_<T>.json`; commit both files. Watch memory (MODELS section 12) |
| Style tables | `python scripts/tn_charting.py --tour atp` (`--refresh` to re-download the CSVs) | then commit `docs/ace/data/<T>/style.json` (or let CI's hydrated copy stand) |
| Clear model caches | delete `data/tennis/cache/` (keep `backtest_*.json` and `backtest_sr/` to avoid a long rerun) | after a model change that does not bump a version string |
| JS syntax | `uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/ace/assets/js/value.js',encoding='utf-8').read())"` (or `node --check`) | per module; `tests/tennis/test_value.py` also checks `value.js` for `?.` / `??` |
| Dates of birth | `python scripts/tn_bio.py --tour atp` (and `wta`; `--dry-run` counts) | ESPN's core athlete API, 0.5 s a call, only players without a date (re-asked after 180 days); writes `docs/ace/data/<T>/bio.json`; commit it. About 13 minutes for both tours the first time, seconds after |
| Value section | runs inside the build (`value.json`, `value_validation.json`) | the validation is cached per quarter (`data/tennis/cache/ace_value/<T>_history.json`) and rebuilt when the quarter, a completed year's store, a fit, `bio.json` or `analytics/value.py` changes; delete the file to force it |

---

## 5. Committing a completed year

Do this once each tour's season is over (after the Finals in November; the store
should hold no live or upcoming tour-level match), and before 1 January if possible.

1. **Bring the store up to date locally**: `python scripts/tn_hydrate.py --year <Y>`,
   then a last full pass for the year so tennis-data's final workbook and the WTA's
   last statistics are merged:
   `python scripts/tn_fetch.py --tour atp --from <Y> --to <Y> --force-td` (and `wta`).
2. **Check it**: `python scripts/tn_fetch.py --tour atp --report --from <Y> --to <Y>`;
   every tour-level event done with a champion; odds coverage close to the match count.
3. **Refit and backtest** (section 4): `tn_fit.py` for both tours, then
   `--backtest`; update the figures in `docs/tennis/MODELS.md` section 10.2, the
   Methodology (`docs.js`) and the h2h constants (`h2h.js`) if they changed.
4. **Commit on `main`**, by explicit path (the `.gitignore` also un-ignores the current
   year's store):

   ```bash
   git add docs/ace/data/atp/<Y>/store.json docs/ace/data/wta/<Y>/store.json \
           docs/ace/data/atp/registry.json docs/ace/data/wta/registry.json \
           docs/ace/data/atp/bio.json docs/ace/data/wta/bio.json \
           docs/ace/data/atp/style.json docs/ace/data/wta/style.json \
           docs/ace/data/atp/calibration.json docs/ace/data/wta/calibration.json \
           oddsmarkets/tennis/models/fitted/
   ```

   Take the registries from the live site (hydrate) so they match the stores.

---

## 6. Rate limits and sources

| Source | Limit | What the code does | If it misbehaves |
|---|---|---|---|
| tennis-data.co.uk | none stated; a small site | 1 s spacing, budget ≤ 200; the link page once per run; completed years downloaded once; the current year by conditional GET | the hidden prefix moves: `links()` re-reads `data.php`; if both link pages change shape, fix `_LINK` in `sources/tennisdata.py` |
| ESPN site API | none stated | 0.5 s spacing; 429 or 5xx: `Retry-After` or 10 s × attempt, 4 attempts; budget per run | raise `--interval`; the run resumes next time |
| WTA API | none stated | 0.5 s spacing, the `Referer` header; finished tournaments and stats read from the raw cache | a backfill of 20,000+ calls took about 3 hours without trouble; on 429s raise `--interval` |
| Match Charting Project (GitHub raw) | GitHub's | 1 s spacing, 20 calls | the files are large (95 MB men); download once |
| Kalshi, Polymarket | public read APIs | one pass per build; failures give "available: false" | nothing; `--no-market` to skip |
| atptour.com, Sofascore, Sackmann's `tennis_atp` / `tennis_wta` | blocked or gone (404 since 1 Oct 2026) | not used | — |

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `ACE_REPO` or `ACE_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| "cold build" in the restore step, then a slow or timed-out build | the public repo could not be cloned | check the key; a timed-out build deploys nothing, so the site stays on the last deploy |
| The current year goes backwards (matches missing that were there) | the hydrate step failed or fetched an older store, so the build ran on the checkout's (or no) current-year store | check the hydrate log; re-run the workflow; recover with a local `tn_fetch.py --from <Y> --to <Y>` and a hand deploy |
| No new results or closing odds for days | tennis-data's prefix moved and neither link page parses, or its workbook has not been updated | the fetch log says "no download links found" or "unchanged"; ESPN still supplies scores |
| A player appears twice (an `x:` id beside the real one) | a name no rule resolves | add the raw name to `overrides.json` (`names`, with a `_why`), then re-run `tn_fetch.py --force-td` for the affected years; the redirect fixes the stores on load |
| A player shows another player's name | an ESPN profile with the wrong name (ATP 5029) | `overrides.json` `espn_names` |
| An ATP draw looks scrambled | ESPN gives no bracket order: the draw is reconstructed and first-round blocks no later round links are appended in date order | expected until the second round is set (DATA_PIPELINE section 7.4) |
| WTA event page without seeds | a Slam (ITF, no WTA draw), or the WTA draw call failed | the next run retries while the event is live |
| Calibration page "has not been run yet" | no committed `calibration.json` and no `backtest_<T>.json` in the cache | section 4, backtest; commit `calibration.json` |
| The WTA calibration build step is slow | `validate_stats` with a cold cache (ten pairs of fits) | it is cached under `ace_validation`; `--no-validate` locally |
| A backtest eats memory | a regression of the chain's memory fix | `pytest tests/tennis/test_models_c.py -k free_memory`; MODELS section 12 |
| Head-to-head prices differ from the match centre | the h2h page prices in the browser from published rates with hard-coded constants (stale for the WTA) | known; [MODELS.md](MODELS.md) section 14.2 |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_ace.py --tours <T>` locally and read the traceback |
| The Value page says "not available" | `value.json` is `{"ok": false}` (the `<T> value build` step raised) | the build log's traceback; the step needs the Elo and game-share histories and, for good forecasts, the backtest's serve/return fits under `data/tennis/cache/backtest_sr` |
| Value forecasts without ages (ATP) | `bio.json` missing | `python scripts/tn_bio.py --tour atp` |
| Markets "thin: ..." | too few runners accounted for or implied total outside 0.8–1.3 | normal for small tournaments and early fields |
| Many market names unmatched | Challenger or qualifying players absent from the store, or new players | the build log's `LAST_STATS` split; nothing for the first, the registry learns the second as they play |
| Public repo updated but the live site is not | Pages did not start a build (seen once on the football site) | Settings → Pages; `POST /repos/pchattani/the-quant-ace/pages/builds` |

---

## 8. Seasons and calendar

| When | What |
|---|---|
| Every match day | nothing by hand: matches are fetched each hour from ESPN (six days of scoreboards) and the WTA API; tennis-data's results, ranks and closing odds arrive when its workbook updates |
| Weekly | the official rankings (ESPN top 150 ATP; WTA API top 1,000) refresh with the store; `rankings.json` `move` compares with the last snapshot the build saw |
| November | the ATP and WTA Finals end the season (the round robin is simulated by `tournament_sim`); the Race and year-end No. 1 settle |
| After the Finals | commit the completed year (section 5); refit; backtest |
| 1 January | the current year turns over (`canon.current_year`: UTC calendar year). The hydrate 404s for the new year (fine); the first refresh creates the new store from the day scoreboards; tennis-data's new workbook appears in January (the td phase keeps re-reading the previous year through January). Check (the next-season Slams key `slams_<year + 1>` and the backtest driver's year range follow the season on their own): `canon.KNOWN_LEVELS`, `DRAW96` and `POINTS` against the new calendar and rulebooks; `canon.final_set_rule` if a Slam changes its rule; the Kalshi and Polymarket series names in `sources/markets.py` |
| When a source changes a field | the parsers in `sources/{tennisdata,espn,wta,charting}.py`, then `CONTRACT.md` and the fixtures in `tests/tennis/fixtures/` |

---

## 9. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `ACE_REPO` | Actions variable (`pchattani/the-quant-ace`) | `pchattani/oddsmarkets` | restore and deploy steps |
| `ACE_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | restore and deploy steps |
| deploy key "oddsmarkets update_ace.yml" | deploy key, write | `pchattani/the-quant-ace` | cloned and pushed to by the workflow |
| `ACE_DATA`, `ACE_CACHE`, `ACE_RAW` | environment variables (optional; `--data`, `--cache` on the build) | local, tests | point stores and payloads, model caches and raw downloads elsewhere |

No API keys: tennis-data, ESPN, the WTA API, the Match Charting Project, Kalshi and
Polymarket all serve public data without one. The workflow's `GITHUB_TOKEN` has
`contents: read` only. The local key pair is kept at
`~/.ssh/oddsmarkets_ACE_DEPLOY_KEY.base64.txt`. Licences to keep: the
Match Charting Project's CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike for
`style.json`) and the credit to tennis-data.co.uk, both in the disclaimer and the
footer.
