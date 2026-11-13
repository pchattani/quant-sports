# The Quant Scrum — models

Men's international rugby union (the women's tab reuses the men's settings: 88 women's World Cup matches are too few
to fit on). Code: `oddsmarkets/rugby/` (`ratings.py`, `models.py`, `rankings.py`, `comps.py`, `players.py`,
`analytics.py`); fit with `scripts/scrum_fit.py`, which writes `oddsmarkets/rugby/fitted/params.json` and
`report.json`. Every number below comes from that report: the re-run of 13 Nov 2026 on results through 8 Nov 2026,
after the venue fixes (section 2a). The settings in use were chosen on 2 Nov 2026 (results through 31 Oct) and kept
by the 13 Nov re-run (section 2b).

## 1. Data and the honest split

7,177 men's tests with a result, 1871-2026: 1,896 from ESPN and 5,281 from Wikipedia only (tour matches against club
and provincial sides are dropped). Calendar years. **Development years 2004-2018** (2,731 scored tests) choose every
setting; **sealed test years 2019-2026** (1,205) are scored once; everything before 2004 is burn-in. Every forecast is
made before the match from results already played (the walk-forward updates after forecasting).

The coverage gap: ESPN's "International Test Match" feed starts in 2015, so the development years were thin on tests
with a tier-three side until the Wikipedia history arrived (2 Nov 2026). On the test years the tier pairings are one v
one 389 tests, one v two 159, two v two 221, two v three 90, three v three 346.

## 2. The ladder (promotion rule: the paired 95% interval of the per-test log-loss difference on the test years
excludes zero, with calibration no worse)

The 13 Nov 2026 re-run, every rung tuned again on the development years:

| Rung | Dev log loss | Dev Brier | Test log loss | Test Brier | Test ECE |
|---|---|---|---|---|---|
| Our World Rugby rebuild + a logistic (the baseline) | 0.5993 | 0.3601 | 0.6072 | 0.3704 | 0.036 |
| Our margin rating with home advantage (`elo`) | 0.5967 | 0.3616 | 0.5957 | 0.3618 | 0.025 |
| + uncertainty, Glicko-style (`unc`) | 0.5914 | 0.3566 | 0.5887 | 0.3562 | 0.029 |
| + travel and rest (`ctx`) | 0.5905 | 0.3561 | 0.5895 | 0.3568 | 0.023 |
| + the tier-three fix (`kal`), re-tuned | 0.5554 | 0.3291 | 0.5760 | 0.3470 | 0.046 |
| + altitude (`alt`) | 0.5896 | 0.3553 | 0.5914 | 0.3579 | 0.034 |
| + attack and defence (`split`) | 0.5804 | 0.3496 | 0.5913 | 0.3583 | 0.043 |
| Hybrid (post hoc): the rebuild's chance for tests with a tier-three side | 0.5875 | 0.3515 | 0.5903 | 0.3579 | 0.036 |
| **The model in use: `kal` with its 2 Nov settings, on the same inputs** | **0.5556** | **0.3293** | **0.5793** | **0.3491** | **0.039** |

Paired differences on the test years (negative = the newer rung better):
- `elo` v the rebuild: −0.0143 (95% interval −0.0309 to +0.0023, 1,196 tests; Lions tests are outside the
  rankings): level;
- uncertainty v rating: −0.0071 (−0.0131 to −0.0011): promoted;
- travel and rest v uncertainty: +0.0009 (−0.0009 to +0.0027): not promoted;
- the re-tuned tier-three fix v uncertainty: −0.0127 (−0.0260 to +0.0006), calibration worse (ECE 0.046 against
  0.029): not promoted on this re-run (on the development years −0.0360, −0.0463 to −0.0257);
- altitude and attack-and-defence v uncertainty: +0.0027 and +0.0026, intervals across zero: not promoted;
- so the re-run's own choice is `unc`; against the model in use it is **+0.0094 (−0.0043 to +0.0231)**, and +0.0358
  (+0.0255 to +0.0460) on the development years: not better, so **the model in use stays** (2b). The re-tuned `kal`
  against the model in use: −0.0033 (−0.0106 to +0.0040), ECE 0.046 against 0.039: not promoted either;
- the model in use v the rebuild: −0.0294 (−0.0448 to −0.0140): better.

By tier pairing on the test years (log loss: the model in use, the re-run's `unc`, the rebuild): one v one 0.618,
0.618, 0.631; one v two 0.298, 0.309, 0.328; two v two 0.685, 0.673, 0.728; two v three 0.319, 0.334, 0.382; three v
three 0.665, 0.697, 0.689.

### 2a. Who is at home (13 Nov 2026)

Two venue faults, found on 13 Nov 2026, had been sending the model wrong inputs:
- **"Allianz Stadium" is three grounds.** ESPN gives every past test at a ground the ground's current name, so England's
  tests at Twickenham back to 1991 read "Allianz Stadium, London" (renamed 2024); Sydney's football stadium carries the
  name too, and so does Juventus's ground in Turin (Italy's home tests there in 2024, 2025 and 2026; ESPN venue 308704,
  no address). Our ground table put every "Allianz Stadium" in Sydney, so England's 126 home tests at Twickenham (and
  Italy's three in Turin) were treated as "home tests far from home", that is neutral. The city now picks the ground
  (`nations.SHARED`); with no city, the home side's country. The rest of the table was checked: no other ground name
  is shared, and the ambiguous cities (Perth, Newcastle, Hamilton, Wellington) are now told apart by the ground's name
  (Optus Stadium is Perth, Western Australia; McDiarmid Park is Perth, Scotland), which also put Hamilton, Bermuda on
  the map. The feed's "Perth (WA)" now reads as Perth.
- **"Far from home" was a radius, not a border.** A "home" test more than 1,500 km from the side's one home city
  (Sydney for Australia) counted as neutral: the rule meant for Fiji's home tests in Britain also took the home
  advantage from Australia in Perth (3,277 km) and Townsville, and gave it to England, Ireland, Scotland, Wales and
  Italy at the 2023 World Cup in France (inside 1,500 km of home). The rule now
  reads the venue's country where our ground and city tables know it (`nations.place`, every city with its union):
  **a side is at home in its own country, anywhere in it, and nowhere else**, whatever the source's flag says.
  Where we do not know the venue's country, the source's flag stands unless the home side is more than 1,500 km from
  home (as before).
- **A host listed second.** The match model only gave home advantage to the side listed first. The tournament rule
  (section 3, "Australia at home, everyone else neutral") already treated a host as at home whichever way the fixture
  is listed, and the model's history gives every host nation its home advantage at its own World Cup (New Zealand
  2011, Japan 2019, France 2023, Australia 2003). So a side listed second in its own country now takes the advantage
  (`Model.context` "side" −1): New Zealand v Australia in Sydney at the 2027 World Cup, Fiji's 2026 "home" tests in
  Cardiff, Liverpool and Edinburgh, the women's World Cup finals of 2022 and 2025.

214 of 8,567 tests (men and women) changed their call: 176 from neutral to home, 25 from home to neutral, 13 to the
side listed second. On the same results (through 8 Nov 2026) the model in use scored
**0.5834 log loss on the test years before the fix and 0.5793 after** (paired −0.0042, −0.0080 to −0.0004; on the 82
test-year tests whose call changed −0.0085, −0.0470 to +0.0300); 0.5572 and 0.5556 on the development years. Brier
0.3527 to 0.3491, ECE 0.039 both times. The rebuild moves from 0.6105 to 0.6072 (the duplicate ids below). Every rung of
the re-run improves on its 13 Nov counterpart before the fix (`elo` 0.6109 to 0.5957, `unc` 0.6085 to 0.5887).

**Duplicate ids (13 Nov 2026).** ESPN's World Cup league kept its first ids for Spain, Zimbabwe and Cote d'Ivoire (18,
42, 63; the 1987-1999 World Cups) while its test-match feed and the 2027 World Cup fixtures use newer ones (289211,
289356, 289358). The Wikipedia merge hung the older tests on the first id, so each side had two ratings and Spain two
rows on the power board. `store.unify_ids` keeps the first id a side appears under and rewrites the rest; old team
links redirect (`index.json` "alias").

### 2b. The model in use and re-runs

A re-run tunes every rung again, and coordinate descent is path dependent: on 13 Nov the corrected inputs moved the
`elo` rung's settings (no shrink between years), the re-tuned `kal` rung inherited them, its World Rugby anchor (which
works through that shrink) went quiet, and its calibration slipped. So `scripts/scrum_fit.py` now scores the model in
use on the same inputs and **replaces it only if the re-run's choice clears the ladder's own promotion rule against
it** (`--replace` skips the check, for a planned re-split). On 13 Nov it did not, so every setting in use stays and
`params.json` gains only `checked_through`. A one-setting check on the model in use: home advantage tuned alone on the
development years would move from 4.5 to 5.0 points (0.5551 against 0.5556), and scores 0.5805 against 0.5793 on the
test years: worse, so it stays at 4.5.

**The tier-three fix (2 Nov 2026).** The rating jumps the site showed (Austria fifth after a 117-3 win over
Slovakia, five other tier-three sides in the top 20) had one cause: sides that only play each other form islands whose
ratings are identified only up to an offset, and the old learning rate (0.70 a point of surprise for a side's first
eight tests, the surprise capped at 40) let two unproven sides throw each other ±28 points a match. Three changes, tuned
together on the development years (`models.GRID_KAL`) and then scored once:
1. **Kalman learning rates.** Each side carries a rating variance v (900 points² for a new side, a spread of 30; +10
   at each new year, never above the start). A result moves side i by v_i / (v_h + v_a + sd²) of the surprise (sd =
   the test's base spread), and v_i shrinks by the same factor. A new side learns fast against an established one; two
   new sides move each other much less. The margin spread is √(sd² + v_h + v_a).
2. **A blow-out clip.** The final margin counts up to 40 points before the surprise is taken (cap 60 on the surprise).
3. **A World Rugby anchor.** The 10% shrink between years aims at the side's World Rugby points (our rebuild from
   results to date, so no look-ahead) mapped onto our scale: 8 + 3.0 × (points − 78).

Settings in use (`fitted/params.json`): home advantage 4.5 points to a side in its own country (2a); the Kalman rates
above; margin spread 10.0 + 0.2 per point of expected margin plus the two sides' variances; draw = final margin within
±0.5. Ranking rule on the site (`pages.ratings_payload`): a side is ranked only with five or more tests rated and a
tier-one or tier-two side or three or more tests against one in four years; the rest are provisional and unranked,
and invitational sides (Lions, Barbarians) are not in the ratings table. (Barbados shared the Barbarians' code until
2 Nov 2026 and was wrongly treated as invitational; it is now BRB.)

Calibration of the model in use on the test years (our home-win chance, then how often it happened): 0-10% 6%→4%
(83), 10-20% 15%→23% (98), 20-30% 24%→29% (92), 30-40% 35%→35% (77), 40-50% 45%→49% (68), 50-60% 55%→54% (107),
60-70% 65%→63% (95), 70-80% 75%→70% (135), 80-90% 86%→78% (192), 90-100% 95%→93% (258).

**Totals:** the expected total in use (the attack/defence ratings) misses by 12.8 points a test on the test years,
against 13.4 for the development years' average total (the re-run's re-tuned one misses by 13.6); it is kept because
the simulations need one per match (spread 17.5).

**Tries (the try-count model):** tries ~ Poisson(−1.56 + 0.169 × our expected points) against a flat 2.30-try rate:
−0.019 log loss a side on the test years, interval −0.340 to +0.303, so it is not promoted as a forecast. It is used
where a try count is unavoidable, the bonus points in the simulations, conditional on the simulated score (tries ≈
−1.03 + 0.146 × points, binomial on the five-point blocks).

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
  everyone else neutral. The match model gives the 2027 fixtures the same calls from their venues (2a): Australia at
  home in Perth, Brisbane, Townsville and Sydney (also where the fixture lists it second), everyone else neutral.

## 4. World Rugby rankings rebuild (`rankings.py`, `validate.py`)

The published points exchange (Wikipedia, "World Rugby Rankings", How to calculate the Points Exchange): the winner
takes (10 − gap)/10 from the loser, the gap capped at ±10; ×1.5 for a win by more than 15; ×2 at a World Cup; a draw
moves gap/10 from the favourite; before 1 July 2026 the home side counts 3 points higher. Golden tests in
`tests/scrum/test_scrum.py`.

**Accuracy** (the 13 Nov 2026 report). Rebuilt from 1987 with tier priors (78 / 66 / 52) and no published input
(Lions and invitational sides excluded, as World Rugby excludes them):
- against the published top 30 of 28 Sep 2026: mean absolute error 2.93 points (2.34 for the top ten), a level shift
  of +1.06, 2.78 points after the level; rank correlation 0.992;
- against the published order of 1 Dec 2025 (the World Cup draw seeding): rank correlation 0.964; 8 of 24 exactly,
  18 within one.
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
  abroad is neutral, 2a) but they have not earned a place on the test years (the 13 Nov re-run gave them a small
  weight on the development years, +0.0009 on the test years).
- The tier-three gap: the 2 Nov 2026 fix closed it (three v three 0.665 against the rebuild's 0.689 on the 13 Nov
  inputs). Once enough tier-two/three tests are in the past (the feed has them from 2015), a re-split
  (for example development 2004-2022, test 2023-) can choose settings that see them; decided in advance, scored once.
- Women: no separate fit (88 matches). Sevens: only the Olympic tournaments are in the feed, not enough for ratings.
