# The Quant Scrum — models

Men's international rugby union (the women's tab reuses the men's settings: 88 women's World Cup matches are too few
to fit on). Code: `oddsmarkets/rugby/` (`ratings.py`, `models.py`, `rankings.py`, `comps.py`, `players.py`,
`analytics.py`); fit with `scripts/scrum_fit.py`, which writes `oddsmarkets/rugby/fitted/params.json` and
`report.json` (every number below comes from that report, fitted 2 Nov 2026 on results through 31 Oct 2026).

## 1. Data and the honest split

1,890 men's tests with a result, 1987-2026 (ESPN; tour matches against club and provincial sides are dropped).
Calendar years. **Development years 2004-2018** (711 scored matches) choose every setting; **sealed test years
2019-2026** (838) are scored once; 1987-2003 is burn-in. Every forecast is made before the match from results
already played (the walk-forward updates after forecasting).

The coverage gap, found on the test years and reported: ESPN's "International Test Match" feed starts in 2015, so the
development years hold 505 tier-one v tier-one tests, 115 tier one v two, 81 tier two v two, and only 10 tests with a
tier-three side; the test years hold 226 tests with a tier-three side (184 between two tier-three sides).

## 2. The ladder (promotion rule: the paired 95% interval of the per-test log-loss difference on the test years
excludes zero, with calibration no worse)

| Rung | Dev log loss | Dev Brier | Test log loss | Test Brier | Test ECE |
|---|---|---|---|---|---|
| Our World Rugby rebuild + a logistic (the baseline) | 0.5819 | 0.3495 | 0.5835 | 0.3674 | 0.041 |
| Our margin rating with home advantage (`elo`) | 0.5558 | 0.3313 | 0.6326 | 0.3826 | 0.061 |
| + uncertainty, Glicko-style (`unc`) | 0.5537 | 0.3303 | 0.6171 | 0.3797 | 0.053 |
| + travel and rest (`ctx`) | 0.5537 | 0.3303 | 0.6171 | 0.3797 | 0.053 |
| **+ the tier-three fix (`kal`, in use since 2 Nov 2026)** | **0.5484** | **0.3266** | **0.5779** | **0.3578** | **0.038** |
| + attack and defence (`split`) | 0.5535 | 0.3304 | 0.6374 | 0.3838 | 0.067 |
| Hybrid on `kal` (post hoc): the rebuild's chance for tests with a tier-three side | 0.5476 | 0.3260 | 0.5710 | 0.3580 | 0.043 |
| The old hybrid on `unc` (in use until 2 Nov 2026, post hoc) | 0.5506 | 0.3281 | 0.5823 | 0.3657 | 0.036 |

Paired differences on the test years (negative = the newer rung better):
- `elo` v the rebuild: +0.048 (95% interval +0.010 to +0.086, 830 tests; Lions tests are outside the rankings):
  worse;
- uncertainty v rating: −0.0155 (−0.0258 to −0.0051): promoted;
- travel and rest: the development years chose zero weights (no change): not promoted;
- **the tier-three fix v the uncertainty rung: −0.039 (−0.060 to −0.019): promoted** (chosen on 2004-2018, where it
  scores −0.005, −0.015 to +0.005; calibration better, ECE 0.038 against 0.053);
- attack and defence v the fix: +0.059 (+0.030 to +0.088): not promoted (it supplies the total only);
- the model in use v the rebuild: −0.006 (−0.032 to +0.020): level (it was +0.048 worse before the fix);
- the hybrid v the fix: −0.007 (−0.027 to +0.013): not clearly better, so **the hybrid is retired**; against the old
  hybrid it is −0.011 (−0.023 to −0.000), but that comparison is after the fact.

By tier pairing on the test years (log loss: `unc`, `kal`, the rebuild): tier one v one (348 tests) 0.618, 0.609,
0.612; one v two (144) 0.220, 0.205, 0.253; two v two (112) 0.787, 0.751, 0.776; two v three (37) 0.557, 0.471,
0.395; three v three (189) 0.830, 0.723, 0.706. The fix closes most of the tier-three gap and widens our lead where
tier-one and tier-two sides meet.

**The tier-three fix (2 Nov 2026).** The rating jumps the site showed (Austria fifth after a 117-3 win over
Slovakia, five other tier-three sides in the top 20) had one cause: sides that only play each other form islands whose
ratings are identified only up to an offset, and the old learning rate (0.70 a point of surprise for a side's first
eight tests, the surprise capped at 40) let two unproven sides throw each other ±28 points a match. Three changes, tuned
together on the development years (`models.GRID_KAL`) and then scored once:
1. **Kalman learning rates.** Each side carries a rating variance v (2,500 points² for a new side, a spread of 50;
   +25 at each new year, never above the start). A result moves side i by v_i / (v_h + v_a + sd²) of the surprise
   (sd = the test's base spread), and v_i shrinks by the same factor. A new side learns fast against an established
   one; two new sides move each other much less. The margin spread is √(sd² + v_h + v_a).
2. **A blow-out clip.** The final margin counts up to 60 points before the surprise is taken (cap 40 on the surprise).
3. **A World Rugby anchor.** The 15% shrink between years aims halfway between the tier mean and the side's World
   Rugby points (our rebuild from results to date, so no look-ahead) mapped onto our scale: 8 + 2.2 × (points − 78).

Settings (`fitted/params.json`): home advantage 5.0 points (none at a neutral venue or a "home" test far from home);
the Kalman rates above; margin spread 11.0 + 0.05 per point of expected margin plus the two sides' variances;
draw = final margin within ±0.5. Ranking rule on the site (`pages.ratings_payload`): a side is ranked only with five
or more tests rated and a tier-one or tier-two side or three or more tests against one in four years; the rest are
provisional and unranked, and invitational sides (Lions, Barbarians) are not in the ratings table. (Barbados shared
the Barbarians' code until 2 Nov 2026 and was wrongly treated as invitational; it is now BRB.)

Calibration of the model in use on the test years (our home-win chance, then how often it happened): 0-10% 5%→11%
(70), 10-20% 15%→19% (43), 20-30% 26%→31% (54), 30-40% 35%→46% (56), 40-50% 44%→41% (74), 50-60% 55%→56% (102),
60-70% 65%→66% (97), 70-80% 74%→69% (70), 80-90% 85%→82% (96), 90-100% 96%→93% (176).

**Totals:** our expected total (the attack/defence ratings) misses by 13.8 points a test on the test years, against
13.3 for the development years' average total: not better, so treat the total as a rough guide; it is kept because
the simulations need one per match (spread 16.9).

**Tries (the try-count model):** tries ~ Poisson(−0.99 + 0.146 × our expected points) beats a flat 2.30-try rate by
0.193 log loss a side on the test years, but the interval (−0.445 to +0.060) touches zero, so it is not promoted as a
forecast. It is used where a try count is unavoidable, the bonus points in the simulations, conditional on the
simulated score (tries ≈ −1.03 + 0.146 × points, binomial on the five-point blocks).

## 3. Tournaments (`comps.py`)

20,000 simulations a competition (10,000 for the World Cup): a margin from our model, a total (spread 16.8), tries
from the score, then the real rules (verified 2 Nov 2026 against the competitions' Wikipedia articles):
- **Six Nations 2027** (fixtures announced 9 March 2026): 4 a win, 2 a draw, try and losing bonus points, 3 for a
  Grand Slam; level on points: points difference, then tries. Triple Crown and wooden spoon tracked.
- **Nations Championship 2026:** two conferences of six, each side plays the other conference once (three home, three
  away), standard bonus points, then the finals weekend at Twickenham (27-29 November: N1 v S1 for the title, N2 v S2
  third place ... N6 v S6), England at home there.
- **Rugby World Cup 2027** (Australia): the pools from the draw of 3 December 2025, top two plus the four best thirds
  to a round of 16 (World Rugby's 15-row permutation table for the thirds), then the published bracket; pool
  tie-breakers head to head, points difference, try difference, points, tries, then the rankings. Australia at home,
  everyone else neutral.

## 4. World Rugby rankings rebuild (`rankings.py`, `validate.py`)

The published points exchange (Wikipedia, "World Rugby Rankings", How to calculate the Points Exchange): the winner
takes (10 − gap)/10 from the loser, the gap capped at ±10; ×1.5 for a win by more than 15; ×2 at a World Cup; a draw
moves gap/10 from the favourite; before 1 July 2026 the home side counts 3 points higher. Golden tests in
`tests/scrum/test_scrum.py`.

**Accuracy.** Rebuilt from 1995 with tier priors (78 / 66 / 52) and no published input (Lions and invitational sides excluded,
as World Rugby excludes them):
- against the published top 30 of 28 Sep 2026: mean absolute error 3.53 points (4.62 for the top ten), a level shift
  of −2.59 (the zero-sum pool keeps the priors' level), 2.60 points after the level; rank correlation 0.946; 10 sides
  in exactly the right place, 14 within one;
- against the published order of 1 Dec 2025 (the World Cup draw seeding): rank correlation 0.974; 12 of 24 exactly,
  19 within one.
The gap is the matches ESPN does not carry (tier-two and three tests before 2015, most of the qualifiers). The live
table therefore starts from the published points of 28 Sep 2026 and adds every result since with the formula (no
home allowance since July 2026), and "what each result would do" uses it.

## 5. Players (`players.py`, `analytics.py`, spec `docs/_design/metrics/rugby.json`)

Minutes from the substitutions; per-80 rates over the last two years shrunk toward the position group with 240
minutes of weight; percentiles within six groups (front row, locks, back row, half-backs, centres, back three) among
players with 160+ minutes. **Scrum value:** a ridge regression (λ = 50) of the final margin on the two sides'
differences in quality stats, fitted on 2004-2018 (379 matches with team stats); it explains 69% of the margin on the
development years and 70% on the 277 test matches. Points per unit: clean break +0.86, turnover conceded −1.17,
penalty −0.68, yellow card −0.94, red card −4.29, missed tackle −0.24, defender beaten +0.15, tackle +0.09, metre
+0.05, offload −0.11, lineout won +0.29 (team only). Volume stats (carries, passes, rucks, kicks, knock-ons) are left
out because they follow possession and the scoreline. A player's value is the weighted sum of shrunk rates minus the
group's replacement level (its 20th percentile), plus goal kicking above a 72% kicker. Year-to-year reliability of
each metric and the minutes it takes to settle (m50) are in the spec; ESPN's player "lineouts won" is the hooker's
throws (it is zero for every lock), so it is not a player metric.

**Rugby-specific player measures (2 Nov 2026).** Lineout throws won (the hooker's throws: our source credits the
thrower; shrunk toward 86% with 30 throws of weight, shown from five throws), mauls won, knock-ons, cards (a red counts
as two yellows), goal-kicking points and involvements (carries + tackles + rucks won), all per 80 and shrunk like the
rest. Kicking success by distance and ruck speed are not possible: the feed has no kick distance or ruck timing.

**Game value.** A player's value in one test: the value weights on his own counts, minus a replacement-level player of
his group over the same minutes, plus goal kicking above an average kicker. It drives "who made the difference" on the
match page and the test-by-test chart on the player page.

**Team-page extras.** Position-group grades (each side's best regulars by Scrum value per 80: four front-rowers, two
locks, three back-rowers, two half-backs, two centres, three in the back three; ranked against the ranked sides, A the
top 15% and F the bottom 15%); the most-used starting pairs (9-10, 12-13, 4-5) with their record; wins against the wins
our pre-test chances expected over the last 40 tests. **Win chance through a test:** from the pre-match margin and
spread and the score at each scoring event, the remaining margin shrinking with the time left (spread × √(time left)).

## 6. Team profile

30 per-test team measures over the last two years, opponent-adjusted (a team's average minus how far its opponents'
average conceded is from the field's), percentiles among sides with six or more tests with team statistics. Groups:
attack, defence, breakdown (turnovers won, ruck retention, breakdown penalties), set piece (scrum and lineout success,
steals, maul metres, scrum penalties won), discipline (penalties, cards, turnovers conceded, offside penalties), kicking
(kicking metres, goal kicking, kicks regathered, territory, possession) and conversion (points per 10% of territory and
of possession). Possession, territory, kicking metres and offloads are marked as style. Our source has no team or
player statistics for the 2026 Nations Championship, so only ten sides have a profile today.

## 7. What did not make it, and next

- Travel and rest are built (distance in log-thousand-km, time zones, days since the last test; a "home" test played
  far from home is treated as neutral) but the development years gave them zero weight.
- The tier-three gap: the 2 Nov 2026 fix closed most of it (three v three 0.723 against the rebuild's 0.706). Once enough tier-two/three tests are in the past (the feed has them from 2015), a re-split
  (for example development 2004-2022, test 2023-) can choose settings that see them; decided in advance, scored once.
- Women: no separate fit (88 matches). Sevens: only the Olympic tournaments are in the feed, not enough for ratings.
