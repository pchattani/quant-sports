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
| Our World Rugby rebuild + a logistic (the baseline) | 0.5819 | 0.3495 | 0.5836 | 0.3674 | 0.041 |
| Our margin rating with home advantage (`elo`) | 0.5558 | 0.3313 | 0.6326 | 0.3826 | 0.061 |
| + uncertainty, Glicko-style (`unc`) | 0.5537 | 0.3303 | 0.6171 | 0.3797 | 0.053 |
| + travel and rest (`ctx`) | 0.5537 | 0.3303 | 0.6171 | 0.3797 | 0.053 |
| + attack and defence (`split`) | 0.5535 | 0.3304 | 0.6374 | 0.3838 | 0.067 |
| **Hybrid (post hoc):** `unc`, with the rebuild's chance for tests involving a tier-three side | 0.5506 | 0.3281 | **0.5821** | **0.3655** | **0.036** |

Paired differences on the test years (negative = the newer rung better):
- our rating v the rebuild: +0.049 (95% interval +0.011 to +0.087, 825 tests; Lions tests are outside the rankings):
  **worse**. By pairing (`unc`): level on tier one v one (348 tests, 0.618 v 0.612), better on tier one v two (144,
  0.220 v 0.253), slightly worse on tier two v two (112, 0.787 v 0.776), much worse with a tier-three side (two v
  three, 37, 0.557 v 0.395; three v three, 184, 0.840 v 0.710): the tests the development years never saw, where
  our margin spread (chosen on tier-one rugby) is too confident;
- uncertainty v rating: −0.0155 (−0.0258 to −0.0051): **promoted** (the sealed choice);
- travel and rest: the development years chose zero weights (no change): not promoted;
- attack and defence v the uncertainty rung: +0.020 (+0.007 to +0.034): not promoted (it supplies the total only).

**In use: the hybrid.** It was decided after the test years showed the gap, so its test score is **not** a sealed
result: on the same 838 tests it beats the sealed choice by 0.035 (−0.063 to −0.007) and ties the rebuild (−0.0015,
−0.020 to +0.017), with the best calibration (ECE 0.036). The reasoning is coverage, not fit: with 10 development
tests involving a tier-three side, our rating has no settings chosen for them, while the rebuild's logistic has no
free parameter that depends on the tier. The margin and total for every test still come from our rating.

Settings (`fitted/params.json`): home advantage 5.0 points (none at a neutral venue or a "home" test far from home);
learning rate 0.15 a point of surprise (0.70 for a side's first 8 tests); surprise capped at 40 points; 15% shrink
toward the tier mean each new year; margin spread 12.0 + 0.12 per point of expected margin, widened by 20 points ×
√(1/(tests+1)) for each side's rating uncertainty; draw = final margin within ±0.5. The rebuild's logistic: P(home
win | no draw) = 1 / (1 + e^−(0.084 + 0.169 × gap)), draws 2.4%.

Calibration of the hybrid on the test years (our home-win chance, then how often it happened): 0-10% 5%→3% (39),
10-20% 15%→14% (50), 20-30% 26%→38% (53), 30-40% 36%→40% (57), 40-50% 45%→43% (56), 50-60% 55%→49% (97),
60-70% 65%→64% (131), 70-80% 74%→64% (99), 80-90% 85%→85% (114), 90-100% 95%→94% (142).

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

## 6. Team profile

23 per-test team measures over the last two years, opponent-adjusted (a team's average minus how far its opponents'
average conceded is from the field's), percentiles among sides with six or more tests. Possession, territory, kicking
metres and offloads are marked as style.

## 7. What did not make it, and next

- Travel and rest are built (distance in log-thousand-km, time zones, days since the last test; a "home" test played
  far from home is treated as neutral) but the development years gave them zero weight.
- The tier-three gap: once enough tier-two/three tests are in the past (the feed has them from 2015), a re-split
  (for example development 2004-2022, test 2023-) can choose settings that see them; decided in advance, scored once.
- Women: no separate fit (88 matches). Sevens: only the Olympic tournaments are in the feed, not enough for ratings.
