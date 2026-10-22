# The Quant Campus: college basketball models (men's `mbb`, women's `wbb` Division I)

Code: `oddsmarkets/college/hoops/` (data, ratings, model, backtest, elo, tourney, ncaa, sim, players, build).
Inputs: the season stores of `oddsmarkets/college/store.py` only (ESPN scoreboards, summaries / box scores,
play-by-play, ESPN core odds, AP / Coaches polls, rosters), read only. No KenPom, Barttorvik, Sports-Reference,
NET or other scraped ratings, and no recruiting rankings (247Sports, On3, Rivals are off limits). Every validation
number below is walk-forward (no game is predicted with information from its own day or later) and is regenerated
by every build into `data/<L>/calibration.json`.

Numbers in this document: build of 21 Oct 2026 on the completed backfill (stores 2002-2027, box scores and closing
lines for every season ESPN has them).

## 1. Data handling

- **Teams.** Every Division I member of the season is rated individually; all non-D-I opponents are pooled into one
  pseudo-team per season (`nd1`, about 55-60 points per 100 below the D-I average). Games between two non-members
  are dropped. Game day = the US calendar day (UTC - 6 h).
- **Box scores are checked** (`data.box_ok`): a box counts only when each side's box points (2 FGM + 3PM + FTM)
  match the final score and turnovers are recorded. ESPN's women's boxes 2004-2013 are partial (a 100-point side
  whose box sums to 60, no turnovers: 0 of about 1,300 a season pass), women's 2014-2016 cover about a quarter of
  games, and about one men's game in eight in 2018-2023 lacks a player's line. Possessions use exact boxes only;
  player value tolerates a missing bench line (box points within 10% of the score).
- **Possessions.** Box score: FGA - OREB + TOV + 0.475 FTA (team turnovers included), the mean of the two teams.
  Scoreboard only (ESPN's line has FGA/FTA but no OREB/TOV): k_s x (FGA + 0.475 FTA), k_s = the season's ratio
  box/scoreboard over games with both (at least 200), else the level's pooled ratio (men 1.061, women 1.091; MAE
  3.3 / 3.7 possessions against 5.2 / 5.1 for a constant). Games with neither (men 2002-2004, women before 2014
  except a few scoreboard lines) get possessions from the teams' fitted tempo.
- **Closing lines** (`data.clean_odds`): ESPN core odds as stored by the fetch (consensus 2013; median of five to
  nine offshore books 2014-2016; median of the last lines of several US books 2017-2022; ESPN BET's close block
  2023-2025; DraftKings' close block 2026). Sanity rules: |spread| <= 60, totals inside 95-215 (men) / 80-200
  (women), American moneylines of size 100 or more. This drops the 304 ESPN BET men's games of 2023 whose spread
  and total fields hold the -110 vig instead of the line. Moneylines are de-vigged proportionally.
- **Neutral sites.** ESPN's flag from 2008 (men) / 2011 (women). Before, inferred from the venue (a game is neutral
  when its venue differs from the home team's usual home venue); without a venue, NCAA and conference tournament
  games are neutral (women's games before 2011 have no venues, so their regular-season neutral games count as
  home games).

## 2. Ratings (`ratings.py`)

Two observations per game, one per offence:

    100 pts_home / poss = mu + o_home + d_away + h/2 [not neutral] + e
    100 pts_away / poss = mu + o_away + d_home - h/2 [not neutral] + e

weighted 0.5^(age/60 days) x poss / mean poss, ridge penalty 6 games-equivalents toward the preseason prior,
solved by the normal equations. Reported on the D-I scale: `off` / `def` = adjusted points scored / allowed per 100
possessions against an average D-I team, `rating` = off - def (adjusted efficiency margin), `se` from the posterior
covariance. Tempo: possessions per 40 minutes, pace_game = P + p_home + p_away (ridge 4 toward the prior).
Half-life and ridge were chosen on men's 2005-2012 (seasons without lines): half-life 30/60/120/inf x ridge 3/6/10
gave margin MAE 8.60-8.68; 60 days and 6 were best. Blowout damping changed MAE by under 0.01 and is off.

**Kalman paths** (team pages, `rating_paths`): the rating vector as a random walk (q = 0.04 per day), each game
observing 100 margin / poss - h = r_home - r_away + e; weekly snapshots.

**Preseason prior.** rating_prior = b1 rating_last + b2 conf_mean_last + c + roster adjustment, where
conf_mean_last is last season's mean rating of the team's conference as constituted this season (realignment
carries the new conference's level) and new D-I members get the fitted new-member mean. b1, b2, c and the residual
sd are fitted walk-forward on season pairs before the target season. Latest (2027): men b1 0.63, b2 0.33, sd 6.65,
new members -11.1; women b1 0.73, b2 0.24, sd 8.11, new members -13.0. Tempo regressed with slope 0.64 / 0.57.

**Roster turnover** (`model.roster_adjustments`, walk-forward, active once 300 earlier team-seasons with box scores exist: about 2007 men, 2019 women): the residual of
the season-end rating from that prior is regressed (ridge) on three values in points above replacement (section 8),
all from last season's box scores: the team's own returning players, incoming D-I transfers (same ESPN athlete id,
different team), and the team's whole last-season total. Latest fit (2027, 7,353 men's / 3,171 women's
team-seasons): men +2.90 per 100 points of returning value, +2.01 per 100 of incoming transfer value, -1.48 per 100
of last season's total (sd of the prior's error 6.69 -> 6.06); women +3.04 / +2.15 / -1.84 (8.56 -> 7.58). A
transfer's value carries over about two-thirds as well as a returning player's. Membership of a past season's
team is who appeared for it in that season's box scores (ESPN's historical rosters are unreliable: they list later
teams); that is information a preseason roster carries except for players who never played (injury, redshirt).
For 2027 the membership is ESPN's current rosters (fetched October 2026), so the 2026-27 portal moves are in the
prior. **Freshmen are invisible** (no recruiting data is allowed), which is the prior's largest blind spot: Duke,
for example, sits 10th in our men's preseason while the title market makes it the favourite.

Ablation (men, 2002-2026): without the roster adjustment the backtest margin MAE is 8.806 (8.754 with), log loss
0.5214 (0.5178); in games where a team had played 0-4 games, MAE 9.573 -> 9.411, and on games with a closing line
the gap to the close shrinks from 0.42 to 0.23 points.

## 3. Game model (`model.py`)

    pace_g = tempo_h + tempo_a - P,   x = (rating_h - rating_a) pace_g / 100
    margin = s x + HCA [not neutral],   sd^2 = s0^2 + s1 (se_h^2 + se_a^2) (pace_g/100)^2,   p_home = Phi(margin / sd)
    total  = t0 + t1 (off_h + def_a + off_a + def_h - 2L) pace_g / 100

Parameters for season S are least squares on D-I v D-I games of seasons < S (walk-forward). Latest: men s 1.04,
HCA 3.6 points, s0 10.1, s1 1.6, t0 6.5, t1 0.96; women s 1.07, HCA 3.2, s0 10.8, s1 1.5, t0 1.9, t1 0.99.
A probit recalibration did not help out of sample and is off.

## 4. Walk-forward backtest (`backtest.py`, `calibration.json`)

D-I v D-I games, 2002-2026; ratings refitted every game day from earlier days only; game parameters from earlier
seasons only.

| | Men | Women |
|---|---|---|
| games | 131,597 | 126,649 |
| model Brier / log loss / accuracy | 0.1743 / 0.518 / 73.4% | 0.1572 / 0.473 / 76.4% |
| Elo baseline Brier / log loss | 0.1811 / 0.539 | 0.1675 / 0.506 |
| model margin MAE / RMSE | 8.75 / 11.12 | 9.50 / 12.03 |

**Against the closing line** (pooled over every season with a line: men 2013-2026, women 2020-2026):

| | Men | Women |
|---|---|---|
| games with a closing spread | 65,965 | 11,886 |
| margin MAE model / close | 8.85 / 8.71 | 9.73 / 9.88 |
| ATS hit of the model's side v the close | 50.9% ± 0.2 (n 65,136) | 55.1% ± 0.5 (n 11,857) |
| totals MAE model / close (n) | 13.31 / 13.15 (61,318) | 12.69 / 12.85 (11,699) |
| over/under hit v the closing total | 51.1% ± 0.2 | 54.9% ± 0.5 |
| Brier / log loss, model v de-vigged moneyline (same games) | 0.1865 / 0.550 v 0.1830 / 0.542 (53,589) | 0.1665 / 0.499 v 0.1708 / 0.512 (10,729) |

Per season (men):

| season | games | with close | MAE model | MAE model (close games) | MAE close | ATS hit ± se | totals MAE model / close | Brier model / ML | log loss model / ML |
|---|---|---|---|---|---|---|---|---|---|
| 2013 | 5414 | 3475 | 8.56 | 8.42 | 8.68 | 53.8 ± 0.9 | - | - | - |
| 2014 | 5503 | 3892 | 8.41 | 8.37 | 8.43 | 51.9 ± 0.8 | 13.57 / 13.49 | 0.2161 / 0.2130 | 0.625 / 0.616 |
| 2015 | 5494 | 3969 | 8.40 | 8.29 | 8.18 | 52.2 ± 0.8 | 13.27 / 13.28 | 0.2076 / 0.2002 | 0.606 / 0.588 |
| 2016 | 5514 | 4010 | 8.63 | 8.54 | 8.37 | 51.1 ± 0.8 | 13.61 / 13.52 | 0.1907 / 0.1892 | 0.564 / 0.560 |
| 2017 | 5520 | 3709 | 8.75 | 8.86 | 8.72 | 49.8 ± 0.8 | 13.34 / 13.24 | 0.1910 / 0.1894 | 0.564 / 0.560 |
| 2018 | 5532 | 3947 | 8.89 | 8.87 | 8.79 | 50.5 ± 0.8 | 13.57 / 13.45 | 0.1832 / 0.1803 | 0.543 / 0.535 |
| 2019 | 5597 | 5459 | 8.90 | 8.87 | 8.81 | 51.1 ± 0.7 | 13.47 / 13.34 | 0.1888 / 0.1882 | 0.557 / 0.556 |
| 2020 | 5328 | 5310 | 8.90 | 8.91 | 8.73 | 50.6 ± 0.7 | 13.20 / 13.12 | 0.1869 / 0.1835 | 0.552 / 0.544 |
| 2021 | 3944 | 3844 | 9.32 | 9.33 | 9.05 | 50.3 ± 0.8 | 13.38 / 13.10 | 0.1920 / 0.1866 | 0.561 / 0.549 |
| 2022 | 5475 | 5414 | 8.87 | 8.86 | 8.62 | 50.2 ± 0.7 | 13.07 / 12.94 | 0.1808 / 0.1761 | 0.534 / 0.525 |
| 2023 | 5715 | 5705 | 9.02 | 9.02 | 8.80 | 49.8 ± 0.7 | 13.06 / 12.96 | 0.1867 / 0.1832 | 0.552 / 0.543 |
| 2024 | 5726 | 5724 | 8.98 | 8.98 | 8.84 | 51.3 ± 0.7 | 13.14 / 12.90 | 0.1827 / 0.1797 | 0.540 / 0.533 |
| 2025 | 5764 | 5763 | 9.01 | 9.01 | 8.79 | 50.6 ± 0.7 | 12.89 / 12.66 | 0.1810 / 0.1769 | 0.533 / 0.525 |
| 2026 | 5752 | 5744 | 9.18 | 9.18 | 8.94 | 50.7 ± 0.7 | 13.73 / 13.39 | 0.1849 / 0.1784 | 0.543 / 0.528 |

Per season (women; no lines before 2020):

| season | games | with close | MAE model | MAE model (close games) | MAE close | ATS hit ± se | totals MAE model / close | Brier model / ML | log loss model / ML |
|---|---|---|---|---|---|---|---|---|---|
| 2020 | 5171 | 278 | 9.69 | 9.48 | 10.53 | 58.8 ± 3.0 | 12.00 / 12.92 | 0.1631 / 0.2205 | 0.484 / 0.636 |
| 2021 | 3677 | 409 | 9.90 | 9.91 | 10.38 | 58.1 ± 2.5 | 13.82 / 14.31 | 0.1792 / 0.1887 | 0.543 / 0.560 |
| 2022 | 5204 | 1276 | 9.60 | 9.84 | 9.80 | 52.7 ± 1.4 | 12.55 / 12.66 | 0.1683 / 0.1739 | 0.503 / 0.522 |
| 2023 | 5516 | 4863 | 9.58 | 9.55 | 9.66 | 54.6 ± 0.7 | 12.71 / 12.87 | 0.1690 / 0.1714 | 0.507 / 0.515 |
| 2024 | 5531 | 2934 | 9.69 | 9.95 | 10.24 | 56.0 ± 0.9 | 12.84 / 13.01 | 0.1687 / 0.1754 | 0.505 / 0.525 |
| 2025 | 5588 | 1219 | 9.51 | 9.67 | 9.67 | 54.8 ± 1.4 | 12.51 / 12.62 | 0.1485 / 0.1502 | 0.446 / 0.457 |
| 2026 | 5624 | 907 | 9.66 | 9.86 | 9.85 | 56.5 ± 1.7 | 12.35 / 12.23 | 0.1624 / 0.1636 | 0.481 / 0.487 |

By line type (`by_line`): men, explicit closes (ESPN BET / DraftKings close blocks, 17,134 games) MAE 9.05 v
8.86, ATS 50.9% ± 0.4; last listed lines / medians (48,831) 8.78 v 8.66, ATS 50.9% ± 0.2. Women, explicit closes
(3,901) 9.84 v 9.91, ATS 55.5% ± 0.8; others (7,985) 9.67 v 9.86, ATS 54.9% ± 0.6.

By spread (men, ATS): 0-3 51.0%, 3-6 50.4%, 6-10 50.5%, 10-15 51.2%, 15-25 52.4% (n 6,606), 25+ 52.0%;
the close's MAE is lower in every bucket. Women: 54.4 / 54.0 / 53.9 / 56.7 / 57.5 / 54.1%, the model's MAE lower
in every bucket but 6-10.

By stage (men, games with a close): teams with 0-4 games played MAE 9.47 v the close's 9.24; 5-9 9.10 v 8.95;
10-19 8.74 v 8.60; 20+ 8.62 v 8.52. Women: 10.69 v 11.09; 10.07 v 10.21; 9.48 v 9.61; 9.33 v 9.40.

Calibration (men): every decile within 1.2 points except the 0.9-1.0 bin (predicted 0.951, observed 0.959) and
0.1-0.2 (0.156 v 0.145); home teams win about one point less often than predicted in the middle deciles. Women: the
0.1-0.4 deciles are 1.2-2.0 points over-confident for the home side, the rest within 1.3. By game type (men): regular
season log loss 0.515, conference tournaments 0.561, NCAA 0.543, NIT 0.590.

**Honest reading.** Men: the closing line is better than the model by 0.14 points of MAE (0.19 on explicit closes)
and on log loss; the 50.9% ATS is about four standard errors above 50% but well below the 52.4% needed to beat
-110, and it is highest in 2013-2015 when the stored "close" is a consensus or a median of single offshore lines,
not a true close. Women: the model is ahead of the stored lines on every measure (MAE 9.73 v 9.88, 55% ATS on
11,857 games, 55.5% on explicit closes, better Brier than the de-vigged moneyline). Women's college lines are thin
markets with low limits, ESPN shows lines for only a third to a half of games, and the earliest seasons' "closes"
may be stale; treat it as evidence that the market is soft, not as a proven betting advantage. ESPN's matchup predictor
is not stored for any backfilled game (it is captured only before tip-off), so there is no comparison yet.

## 4b. Market-informed line (men: on trial; women: not promoted)

Round 4 (22 Oct 2026, `docs/research/college_edge.md`) stacked the game model with ratings learned from earlier games'
closing spreads (market ratings: weighted ridge, half-life 60 days, ridge 0.25, prior 0.7 x last season's final) and
residual ratings (the same ridge on the closing spread minus our margin: half-life 60 days, ridge 4, carry 0.5),
fitted to closing spreads of earlier seasons, with a walk-forward probit (`hoops/market_informed.py`,
`oddsmarkets/college/informed.py`).

- **Men**, sealed test 2021-2026 (32,376 games): log-loss 0.5349 -> 0.5278, paired difference -0.0071 [-0.0085,
  -0.0057], every season's interval below zero; Brier -0.0028; 73 % of the gap to the de-vigged closing moneyline
  closed (0.0098 -> 0.0027 nats); margin error on lined games 9.05 -> 8.91 (the close 8.83; ESPN's stored opener 8.96
  on the games that have one). It was **not promoted**: its calibration slope (0.94 against the model's 1.00) missed
  the pre-registered tolerance. A recalibrated version (the probit fitted on the last two seasons only, chosen on the
  2015-2020 dev seasons: slope 0.975 there) is tested forward on 2026-27 to Selection Sunday with the fit frozen in
  `oddsmarkets/college/fitted/informed_mbb.json`. Until then game pages show it as a trial line beside the published
  model, with the market-ratings line.
- **Women**, sealed test 2023-2026 (22,259 games): no change (-0.0001 [-0.0008, +0.0006]). The women's lines are thin
  (a third of games) and the model already beats the de-vigged moneyline by 0.0117 nats on the games that have one,
  so earlier lines teach it nothing. Not used.

Rest days and back-to-backs added nothing on the men's dev seasons (-0.0037 with or without them).

## 5. Season simulation (`sim.py`)

Team strengths drawn per run from N(rating, se); every remaining regular-season game simulated with the game model;
conference standings by conference win pct; **conference tournaments are generic and approximate** (formats are not
in any free feed): every member, single elimination, seeded by the simulated standings, byes to the next power of
two, neutral floors; teams that already lost a conference-tournament game are out and a played final keeps its
champion. The champion takes the automatic bid. Then the selection and seeding proxy on each run's simulated resume,
the S-curve bracket and the tournament (women: the top-4 seeds host the first two rounds, 2016 on). Finished
seasons show the pre-tournament odds on the actual bracket instead (`actual` filled). 2020 shows a hypothetical
field. 20,000 runs per build.

## 6. Selection and seeding proxy (`tourney.py`, `ncaa.py`)

Actual fields from ESPN's tournament games (seeds are in the events): First Four = the (field - 64) earliest games;
automatic bid = the conference's last intra-conference game winner before the tournament (else its only field
team, else its best conference record: the Ivy League before 2017). Resume at Selection Sunday: our rating and rank
(fitted through the day before the tournament), wins, win pct, quadrant wins / losses on our rank with the NET venue
cut-offs (Q1 home 1-30 / neutral 1-50 / away 1-75 ...), SOS, conference mean. At-large: ridge logistic regression;
seeds: linear regression dealt into lines in predicted order. Leave-one-season-out:

| | Men (24 seasons) | Women (24 seasons) |
|---|---|---|
| at-large hit rate | 90.6% of 851 | 91.2% of 804 |
| seed MAE / exact / within one line | 0.96 / 39% / 78% | 0.89 / 39% / 79% |

Bracketing: four per line, S-curve snake into regions, First Four for the last four at-large and the four lowest
automatic bids; the committee's conference-separation and geography rules are not modelled.

## 7. Tournament forecast backtest

Pre-tournament ratings, the actual bracket, 4,000 runs, scored against what happened, v a seed-only baseline
(P = Phi(c (seed_b - seed_a)), c fitted on earlier tournaments only):

| | Men (24 tournaments, 1,577 games) | Women (23, 1,469) |
|---|---|---|
| round Brier (R32..title, per team-round) | 0.0733 v seed 0.0756 | 0.0506 v 0.0565 |
| game log loss / Brier | 0.543 / 0.184 v 0.563 / 0.193 | 0.411 / 0.136 v 0.450 / 0.149 |
| champion log loss | 2.46 v 2.67 | 1.59 v 2.27 |

Per-tournament rows are in `calibration.json` (`sim.tournament_per_season`).

## 8. Players (`players.py`)

Division I players only (non-D-I opponents' box rows are dropped). Team-constrained box value: Hollinger game score
per 40 minutes (shrunk to the league mean with 150 pseudo-minutes), scaled so the five-man floor sum of a team's
player ratings equals its adjusted efficiency margin (the slope is the season's regression of team rating on
minutes-weighted game score; the residual is spread evenly over minutes). r = points per 100 possessions above an
average D-I player; value = (r - replacement) x possessions played / 100, replacement = the minutes-weighted r of
players outside their team's top eight. Positions: ESPN roster position pooled to G/F/C, else inferred from assist /
block / rebound rates. Usage, TS% (FGA + 0.475 FTA) and points per 100 possessions used alongside. Seasons with
player value: men 2005-2026, women 2014-2026 (2014-2016 on the quarter of games with a box).

Validation: the value predicts next season's team (section 2): returning value explains about a tenth of the
variance the regressed rating leaves (men sd 6.69 -> 6.06). Strengths and needs: team value at G/F/C plus
shooting, ball security, rebounding, free throws and shot defence, graded by percentile against every team
(strengths and needs never overlap; preseason has only G/F/C and offence/defence). Suggestions = the best players
at a weak position elsewhere, labelled as model suggestions (no eligibility, portal, NIL or fit information;
current and previous season only). **Transfers are inferred** (same ESPN athlete id on a different team from one
season to the next, from box scores, or before games from ESPN's current rosters), not the official portal.

Fantasy: points (PTS 1, REB 1.2, AST 1.5, STL 3, BLK 3, TO -1, ours) and 9-category z-scores. Walk-forward check of
the per-game projection (exponentially weighted per-minute rate x weighted minutes, half-life 8 games, from earlier
games only) against the naive season-to-date average; 2026 numbers in section 10.

## 9. Payloads and size

`data/<L>/` calibration, history, markets (Kalshi KXMARMAD / KXWMARMAD and Polymarket via `sources/markets.py`),
players/<pid> (careers: D-I players with a game in the last two seasons with box scores); `data/<L>/<S>/` season,
schedule, bracket, teams, teams/<tid>, players, value, moves, fantasy, lab_players, lab_teams for every season, and
games/<gid> (the current season's played games and the previous season's postseason: NCAA, NIT, WBIT, other
postseason and conference tournaments). Seasons before the previous one are written compactly (PAYLOADS.md:
compact CARDs, qualified players only, top-12 rosters, no suggestions) to stay under 250 MB per level. Sizes
after the build of 21 Oct 2026: men 243 MB (team pages 100, careers 41 for 7,173 players, schedules 34), women
204 MB (6,537 careers). Markets: when the pooled champion book is flagged thin (Polymarket's overround; men on 21
Oct 2026, implied total 1.40), `markets.json` carries Kalshi alone, normalised, with `champion.fallback` saying so.

## 10. 2026 retro and 2027 preseason (build of 21 Oct 2026)

**2026 retro.** Men: Michigan won as the model's pre-tournament favourite (17.7% to win it, 46% to reach the Final
Four; next Florida 13.3%, Purdue 12.8%, Duke 8.2%). Final ratings: Michigan +39.4, Florida +36.7, Purdue +35.1,
Illinois +34.0, Houston +34.0, Arizona +34.0, Iowa State +32.6, Duke +32.5, UConn +30.5, Michigan State +29.0.
The leave-one-season-out proxy put 66 of the 68 actual teams in its field. Women: UCLA won as the second favourite
(22.7%; UConn 41.9%, Texas 16.2%, South Carolina 14.6%); final ratings UCLA +63.4, UConn +63.0, Texas +61.1, South
Carolina +59.3, LSU +54.1; the proxy field matched all 68.

**2027 preseason** (prior only; 20,000 season simulations; Kalshi KXMARMAD-27 / KXWMARMAD-27 fetched 21 Oct):

| Men | rating | P(title) | Kalshi | | Women | rating | P(title) | Kalshi |
|---|---|---|---|---|---|---|---|---|
| Florida | 41.6 | 26.3% | 11.7% | | UConn | 57.7 | 25.5% | 21.6% |
| Texas Tech | 36.0 | 10.4% | 3.0% | | Michigan | 56.6 | 23.2% | 3.5% |
| Iowa State | 35.7 | 9.1% | 1.4% | | LSU | 51.5 | 10.9% | 3.2% |
| Miami | 32.7 | 5.2% | 2.1% | | South Carolina | 51.5 | 11.4% | 32.7% |
| Tennessee | 32.1 | 4.5% | 2.1% | | Vanderbilt | 48.9 | 6.4% | - |
| Cincinnati | 32.0 | 4.6% | 0.2% | | Louisville | 47.1 | 4.9% | 1.5% |
| Houston | 31.8 | 4.7% | 1.8% | | Iowa | 46.2 | 4.3% | 1.7% |
| Illinois | 31.8 | 4.6% | 6.7% | | Ohio State | 42.7 | 2.0% | 0.0% |
| Nebraska | 31.5 | 4.0% | 0.6% | | Minnesota | 42.2 | 2.0% | 0.0% |
| Duke | 30.1 | 3.1% | 14.1% | | Illinois | 41.4 | 1.4% | - |

Where the model and the market disagree most, the market sees what the prior cannot: freshmen (Duke men,
the title favourite at 14%), players returning from a season lost to injury (USC women, 16.6% on Kalshi and 0.1%
here: their star missed 2026, so she has no 2026 value) and coaching changes. The preseason title probabilities
are also more concentrated than the market's (our top four men 51%, Kalshi's top four 37%); the preseason simulation has not
been backtested against past preseason futures, so read the leaders as "strongest returning rosters", not as a
forecast to trade on. Inferred 2026 -> 2027 moves: men 1,440 (311 teams receiving; biggest net gains Cincinnati, Louisville,
Tennessee, Miami, Houston), women 881 (252; Ole Miss, Texas Tech, UCLA, West Virginia, Baylor).

**Player value and fantasy (2026).** Value leaders: men Cameron Boozer (Duke) 459 points above replacement, AJ
Dybantsa (BYU) 356, Yaxel Lendeborg (Michigan) 351; women Hannah Hidalgo (Notre Dame) 629, Sarah Strong (UConn)
595, Madison Booker (Texas) 514. Replacement level -2.3 (men) / -2.7 (women) per 100. Fantasy walk-forward
(2026 player-games after each player's third game): men MAE 6.76 v naive 6.85, daily rank correlation 0.690 v
0.682 (n 105,191); women 6.59 v 6.66, 0.701 v 0.693 (n 102,859): small, consistent gains.
