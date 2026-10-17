# Runbook — The Quant Paddock

How to run, publish, check and repair the F1 site day to day. For how the pieces
fit together read [ARCHITECTURE.md](ARCHITECTURE.md); for the data, models and
front-end in depth, [DATA_PIPELINE.md](DATA_PIPELINE.md), [MODELS.md](MODELS.md)
and [DASHBOARD.md](DASHBOARD.md).

Audience: whoever operates the site, including the owner on a bad day.

---

## 1. The moving parts

| Part | Where it runs | When | What it does |
|---|---|---|---|
| Workflow "Paddock Hourly Update" | GitHub Actions, `pchattani/oddsmarkets` (private) | hourly at :37, and on demand | `.github/workflows/update_paddock.yml`: restore raw telemetry from the Actions cache, fetch Jolpica (≤ 8 min) and OpenF1 (≤ 25 min) for the current season, summarise telemetry, build, commit the changed stores back to `main`, rsync `docs/paddock/` to the public repo |
| Public site repo | `pchattani/the-quant-paddock` (public) | pushed by the workflow | a `--delete` mirror of `docs/paddock/`; never edit it by hand |
| GitHub Pages | from the public repo, `main`, root | on every push | serves https://pchattani.github.io/the-quant-paddock/ |
| Backfills | the owner's machine, detached | once (running since 30 September 2026) | `scripts/f1_fetch.py` and `scripts/f1_openf1.py` filling the history; results committed by hand |

Unlike football there is no local scheduled task: Jolpica and OpenF1 answer
GitHub's runners, so CI fetches for itself. The same private-engine, public-site
split applies, for the same reason (Pages is free only for public repositories).
The stores and session records travel with the public site as data.

---

## 2. First-time publication

The site is live. This section is kept for a rebuild from scratch.

Run once, from the repo root, on a machine where `git push` to GitHub works:

```
uv run --no-project --with pynacl python scripts/setup_public_site.py --site paddock --run
```

With `--site paddock` (the `SITES["paddock"]` entry) it does, each step skipped
when already done:

1. creates the public repo `pchattani/the-quant-paddock` with a README so `main`
   exists, description "The Quant Paddock: Formula 1 odds, lap-by-lap race
   simulations, telemetry and Savant-style analytics. Built hourly.";
2. adds a deploy key titled "oddsmarkets update_paddock.yml" with **write**
   access, reusing the key pair saved at
   `~/.ssh/oddsmarkets_PADDOCK_DEPLOY_KEY.base64.txt` (a new ed25519
   pair is generated and saved there if it is missing);
3. stores the private half, base64-encoded, as the Actions secret
   `PADDOCK_DEPLOY_KEY` in `pchattani/oddsmarkets`;
4. sets the Actions variable `PADDOCK_REPO = pchattani/the-quant-paddock`;
5. turns on Pages from `main`, root, and asks for HTTPS;
6. with `--run`, dispatches `update_paddock.yml` once.

The token is `GH_TOKEN` if set, otherwise the one Git's credential manager holds;
it needs the `repo` and `workflow` scopes. (The script's docstring still describes
only the football site; the `--site` flag is what selects the Paddock.)

**By hand instead**: create the public repo with a README and Pages from `main`
root; add the public key as a deploy key with write access; in
`pchattani/oddsmarkets` set the secret `PADDOCK_DEPLOY_KEY` (base64 of the private
key file) and the variable `PADDOCK_REPO`; run "Paddock Hourly Update".

**Check it worked:** the deploy step ends with a push; the public repo has
`index.html`, `assets/`, `data/` and `.nojekyll`; the Pages URL loads the hub.
Without `PADDOCK_REPO` the workflow still builds and commits, and logs "build
only, no deploy".

---

## 3. Daily checks

| Check | How | Healthy |
|---|---|---|
| CI ran | Actions tab, "Paddock Hourly Update" | a green run every hour; the fetch steps may show as failed-but-continued |
| Stores moved | `git log --oneline -5 -- docs/paddock/data` | "Paddock store refresh (CI)" after each session of a race weekend |
| The site is current | the meta line on the live page | "Updated" within the last couple of hours |
| Race weekend | the next race's page after qualifying | a post-qualifying forecast appears at the first hourly run after Jolpica publishes the qualifying classification (it uses the store's qualifying rows, not the OpenF1 session) |
| Backfills (while running) | `tail logs/f1_backfill.log logs/f1_openf1.log` | a line every few seconds; no repeated 429 warnings |

---

## 4. Routine jobs

| Job | Command | Notes |
|---|---|---|
| Full local build | `uv run python scripts/build_paddock.py` | current season full, every other season light |
| Quick build | `uv run python scripts/build_paddock.py --quick --no-market --no-light` | smoke check |
| Preview | `python -m http.server 8898` in `docs/paddock`, then http://127.0.0.1:8898 | the same files Pages serves |
| Tests | `uv run --group dev pytest tests/f1` | 100 tests, offline (8 in `test_fantasy.py`) |
| Backtest | `uv run python -m oddsmarkets.f1.models.backtest --from 2014 --to 2026 --sims 4000` | writes `data/f1/cache/backtest.json` (about 12 minutes for 267 races, about 300 MB); the next build turns it into `calibration.json`, which is committed (CI keeps the committed copy) |
| Fantasy backtest | `uv run python -m oddsmarkets.f1.analytics.fantasy backtest --from 2012 --to 2026 --sims 2000` | writes `data/f1/cache/fantasy/` (about 2 minutes for 308 weekends with the tune pickles; much longer without them, the race components then being built live); the hourly build then extends it with the current season only and writes `fantasy_backtest.json`. Re-run after a change to the race model or the fantasy table (`fantasy.VERSION`) |
| Re-tune the simulator | `python scripts/f1_tune.py prep --from 2012 --to 2026`, then `grid --configs <list.json> --out <grid.json>`, then `select --grid <grid.json>` | walk-forward choice of `PACE_PER_Z_PCT`, `A_BLEND_K`, `PRE_GRID`; the result goes in `oddsmarkets/f1/models/fitted/race_params.json` (committed). Re-run `prep` after any change to the decomposition, circuit profiles or stores |
| Current season by hand | `python scripts/f1_fetch.py --refresh-current --budget 120 --interval 1.0` | what CI does; not while the Jolpica backfill runs |
| OpenF1 for one season | `python scripts/f1_openf1.py --from 2026 --to 2026 --telemetry --budget 3000` | |
| Telemetry summaries | `python scripts/f1_telemetry.py --from 2023 --to 2026` | after raw telemetry arrives; commit the summaries |
| Clear model caches | delete `data/f1/cache/` | after a model change that does not bump a version string |
| JS syntax | `uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/paddock/assets/js/core.js',encoding='utf-8').read())"` | per module |

---

## 5. Backfills

Started on 30 September 2026, detached, from the repo root:

```
python scripts/f1_fetch.py --from 1950 --to 2026 --budget 12000      # log: logs/f1_backfill.log
python scripts/f1_openf1.py --from 2023 --to 2026                    # log: logs/f1_openf1.log
```

Status on 1 October 2026: the Jolpica pass finished at 12:38 (laps 1996 on, pit stops
2011 on) and is committed. The hourly Sofascore refresh's autostash had reverted the
1998–2026 stores mid-backfill (the stash failed to pop at 11:59); the fields were merged
back from that stash before committing. The OpenF1 telemetry pass crashed on a
MemoryError at 2024 Hungaroring; `f1_openf1.py` now skips one driver on MemoryError,
and the pass was restarted for 2023–2024. The telemetry commands:

```
python scripts/f1_openf1.py --from 2023 --to 2026 --telemetry
python scripts/f1_telemetry.py --from 2023 --to 2026
```

Both scripts resume where they stopped; kill and restart freely.

**Is it still running?** In PowerShell:
`Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'f1_' } | Select ProcessId, CommandLine`.
Then `Get-Content logs\f1_backfill.log -Tail 5`.

**When they finish, commit on `main`:**

1. `git pull --rebase` first. CI commits `docs/paddock/data/2026/store.json` and
   new 2026 session files every hour, and the backfill writes the same files
   locally, so expect:
   - "untracked working tree files would be overwritten" for session files CI has
     already committed: the content is the same OpenF1 data, so delete the local
     copies of those files (or move them aside) and pull again;
   - a conflict on `2026/store.json`: take CI's version
     (`git checkout --theirs` during the rebase, or `git checkout origin/main --
     docs/paddock/data/2026/store.json`), then refill 2026 laps with
     `python scripts/f1_fetch.py --phases laps --from 2026 --to 2026 --budget 400`.
2. `git add docs/paddock/data/*/store.json docs/paddock/data/*/sessions docs/paddock/data/*/telemetry`
3. Commit, push, and dispatch the workflow (or wait for :37).
4. Run the backtest (section 4) on the full history and compare with the numbers
   in [MODELS.md](MODELS.md) section 12.2.

**Never run two Jolpica callers on one IP.** The limit (about 4 a second, 500 an
hour) is per address; a second caller slows both to the 429 back-off. CI is on
GitHub's addresses and does not compete.

---

## 6. Rate limits

| Source | Limit | What the code does | If you see 429s |
|---|---|---|---|
| Jolpica | ~4 requests a second burst, 500 an hour, per IP | 7.3 s spacing by default (1.0 s in CI with a 120-call budget); waits `Retry-After` or 60 s × attempt | stop any second caller; let the pacer recover |
| OpenF1 | 30 requests a minute, no key | 0.35 s spacing (latency keeps it near 25 a minute); waits `Retry-After` or 20 s × attempt | nothing; repeated 429s mean the spacing should be raised to about 2 s (HANDOFF) |
| Kalshi, Polymarket | public read APIs | one pass per build; failures give "available: false" | nothing |

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow green but the site does not change | `PADDOCK_REPO` or `PADDOCK_DEPLOY_KEY` missing; the deploy step logs "build only" | section 2 |
| Deploy fails with "Permission denied (publickey)" | deploy key read-only, deleted, or the secret is not base64 | re-add with write access; store `base64 -w0` of the private key |
| Pages shows the public repo's README | the first deploy has not run | dispatch the workflow |
| Public repo updated but the live site is not | Pages did not start a build (seen once on the football site) | Settings → Pages; `POST /repos/pchattani/the-quant-paddock/pages/builds` |
| Calibration page says "not built" | no `data/f1/cache/backtest.json` where the build ran and no committed `docs/paddock/data/calibration.json` | run the backtest locally, build, and commit `calibration.json` (CI keeps the committed copy) |
| A page section is muted | the data does not exist for that season (laps before 1996, OpenF1 before 2023) or the payload failed | the build log names the failing step; `--seasons <y>` rebuilds one season in full |
| A card shows "could not be built (see the build log)" | that payload's step raised | run `build_paddock.py --seasons <y> --no-light` locally and read the traceback |
| Fetch steps fail every hour | Jolpica or OpenF1 down, or OpenF1 rate-limiting | the build still runs on the committed stores; check the step log |
| "push rejected after 3 attempts" in the commit step | concurrent pushes to `main` (a manual commit, the football task) | none; the next run commits again |
| Post-qualifying forecast missing on race weekend | Jolpica has not published qualifying yet | wait; the OpenF1 session alone does not feed the grid |
| Telemetry lab shows no stored traces | no telemetry summary for that session (raw telemetry not fetched yet) | the next CI runs fill the current season; older seasons need the telemetry backfill |
| A driver missing from session-derived numbers | the car number did not resolve (`canon`) | check the store's `number` fields and `canon.number_collisions(year)` |
| Markets "not published: thin" | too few runners accounted for or the implied total outside 0.8–1.3 | normal for race winners and head-to-heads; markets open about a week out |
| Hourly job slow | every run recomputes the model caches (pace fits, circuit records, Elo, forecasts) because `data/f1/cache/` is not cached in CI | see `HANDOFF.md`; the job's limit is 55 minutes |

---

## 8. Seasons and calendar

| When | What |
|---|---|
| Every race weekend | nothing by hand: sessions arrive 30 minutes after they end, results when Jolpica publishes them |
| 1 January | CI's `--refresh-current` and OpenF1 step switch to the new year (`date -u +%Y`); the new year's store is created at once and its calendar re-requested every run, and the build treats it as the current season as soon as it has a calendar (`current_season` in `build_paddock.py`). From then on CI no longer refreshes the previous season |
| New season | check new team and driver names map in `sources/markets.py` (`DRIVER_ALIASES`, `CONSTRUCTOR_ALIASES`); check the Polymarket title slugs (`POLY_TITLE_SLUGS`) and the Kalshi year suffix; confirm `points_system` in `race_sim.py` still matches the regulations |
| A new regulation era | add its first year to `REG_RESET` in `race_sim.py` (2014, 2017, 2022 and 2026 are there) |
| After a season ends | re-run the backtest and commit `calibration.json`; re-tune with `scripts/f1_tune.py` if the scores drift ([MODELS.md](MODELS.md) section 12) |
| When Jolpica or OpenF1 changes a field | the parsers in `sources/jolpica.py` and `sources/openf1.py`, then `CONTRACT.md` |

---

## 9. Secrets and settings

| Name | Kind | Where | Used by |
|---|---|---|---|
| `PADDOCK_REPO` | Actions variable (`pchattani/the-quant-paddock`) | `pchattani/oddsmarkets` | deploy step |
| `PADDOCK_DEPLOY_KEY` | Actions secret (base64 ed25519 private key) | `pchattani/oddsmarkets` | deploy step |
| deploy key "oddsmarkets update_paddock.yml" | deploy key, write | `pchattani/the-quant-paddock` | pushed to by the workflow |
| `GITHUB_TOKEN` | automatic | the workflow (`contents: write`) | committing the stores back to `main` |
| `PADDOCK_DATA`, `PADDOCK_CACHE` | environment variables (optional) | local | point the build at another data or cache root (tests) |

No API keys: Jolpica, OpenF1, Kalshi and Polymarket all serve public data without
one. The local key pair is kept at
`~/.ssh/oddsmarkets_PADDOCK_DEPLOY_KEY.base64.txt`.
