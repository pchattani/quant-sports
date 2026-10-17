# Models: technical reference (tennis)

Every model behind The Quant Ace, read from `oddsmarkets/tennis/models/` and the
committed fits in `oddsmarkets/tennis/models/fitted/`. Data and identity are in
[DATA_PIPELINE.md](DATA_PIPELINE.md); how the results reach the pages is in
[DASHBOARD.md](DASHBOARD.md). Section 14 lists where the code, the site's
Methodology (`docs/ace/assets/js/docs.js`) and the contracts disagree.

Contents

1. Overview
2. Surface Elo: `elo.py`
3. The serve/return model from scores: `serve_return.py`
4. The exact match chain: `match_chain.py`
5. The match price: `predict.py`
6. Live win probability: `live.py`
7. Tournament simulation: `tournament_sim.py`
8. Season simulation: `season_sim.py`
9. Markets: `sources/markets.py`
10. Backtest: `backtest.py`
11. Other models: Bradley-Terry, synthetic matches, draw difficulty, awards
12. The memory incident (1 October 2026)
13. Known limitations
14. Where the code and other texts disagree
15. Value: breakouts, luck, over/undervalue

---

## 1. Overview

### 1.1 How the models feed each other

```
 stores (MATCH rows) ──► elo.history ──► ratings_at(date), pre_match[mid] ─────────────┐
        │                                                                             │
        └──► serve_return.fit (per season end, per month checkpoint, per refit) ──► hold_prob(i, j)
                                                                                      │
                     predict.predict_many:  sr_p = chain(G⁻¹(h_ij), G⁻¹(h_ji))         │
                                            logit p = w_elo·logit(elo_p) + w_sr·logit(sr_p)
                                            shift the serve-point edge until chain = p
                                            distributions from the σ-mixture
                                                          │
       ┌─────────────────────┬────────────────────────────┼────────────────────┬───────────────────┐
  match centre        live.path (WP game by game)   tournament_sim       season_sim          backtest
  (analytics/matches)                               (prob_matrix)        (prob_matrix)       (walk-forward)
```

### 1.2 Model inventory

| Model | File | Fitted where | Used for |
|---|---|---|---|
| Surface Elo | `elo.py` | constants: `fitted/elo_params_<tour>.json` (2005–2019 log-loss); ratings sequential | half of every match price, Elo pages, draw difficulty, wins over expected |
| Serve/return | `serve_return.py` | constants: `fitted/serve_return_<tour>.json`; fits redone per date from the stores | the other half of the price, hold/break and serve-point metrics, the chain's serve level |
| Game-share Elo | `gelo.py` | constants `gelo.PARAMS` (dev years 2012–2017, docs/research/tennis_edge.md); ratings sequential | the blend's third term (margin of victory), H2H page |
| WTA point layer | `serve_return.py` (`stats=True`) | in the same fit, WTA only | sharper WTA strengths, calibrated hold and SPW, real-stat expectations |
| Match chain | `match_chain.py` | no parameters | win, set-score, games, handicap, tiebreak probabilities; live WP |
| Blend and σ | `predict.py` | `fitted/predict_<tour>.json` (backtest) | the match price |
| Live path | `live.py` | – | WP charts, leverage, excitement, comeback |
| Tournament sim | `tournament_sim.py` | – | event pages, title odds, next-match odds |
| Season sim | `season_sim.py` | entry probabilities hand-set | race.json: Finals, year-end No. 1, ranks |
| Bradley-Terry | `bt.py` | – | a cross-check (not used by the build) |
| Value: model rating, breakout model, luck | `analytics/value.py` | ridge and logistic fits per quarter, cached (`ACE_CACHE/ace_value`); Pythagorean exponents on matches to 2017 | the Value section and the player page's Value card (section 15) |

---

## 2. Surface Elo: `elo.py`

Each player carries four ratings: overall, hard, clay, grass (carpet folds into
hard; there is no indoor term). For a match on surface S:

```
m_i  = w · R_i,S + (1 − w) · R_i,all                                  surface blend
P(i) = 1 / (1 + 10^(−f · (m_i − m_j) / 400)),   f = bo5 for best of 5, else 1
K(n) = k_a / (n + k_b)^k_c                                            n = matches already rated
R_i,all += g · K(n_i,all) · (S_i − E_all)      E_all from overall ratings only (w = 0)
R_i,S   += g · K(n_i,S)   · (S_i − E_S)        E_S from surface ratings only (w = 1)
```

g = 1 for a completed match, `ret_k` for a retirement or default; walkovers are never
rated. **Inactivity**: before a match, a player idle for more than `idle_days` is
pulled towards 1500 on all four ratings, R ← 1500 + (R − 1500) · ρ^((gap −
idle_days)/365); `ratings_at(hist, date)` applies the same pull up to the date.
**Entry**: a player's first rating (all four) is c₀ − c₁ · ln(rank) from the rank on
the MATCH row, or `unranked`.

Ratings run over every rated match on disk (qualifying and Challenger / WTA 125
included); the loss that fits the constants counts only completed tour-level matches
dated **2005–2019**. `fit_params` minimises the mean walk-forward log-loss by
Nelder-Mead (adaptive, on a box-normalised vector; `idle_days` fixed at 60;
`maxfev` 800). `history(tour)` is cached under `ACE_CACHE/elo/`, keyed on the
stores' sizes and mtimes and the constants; the build's `TourData.elo` runs it on
the redirected stores (cached under `ace_elo`).

| Constant | Default | ATP (fitted) | WTA (fitted) |
|---|---|---|---|
| k_a, k_b, k_c | 250, 5, 0.4 | 115.564, 4.552, 0.2769 | 90.838, 0.5146, 0.2194 |
| w (surface weight) | 0.5 | 0.4593 | 0.2840 |
| bo5 stretch f | 1.1 | 1.3658 | 0.9958 (unused: no best-of-5 WTA matches) |
| idle_days, ρ | 60, 0.8 | 60, 0.5801 | 60, 0.6580 |
| c₀, c₁, unranked | 1900, 70, 1400 | 2000.04, 99.34, 1213.12 | 2088.61, 121.01, 1355.09 |
| ret_k | 0.5 | 0.8664 | 0.8987 |
| log-loss (fitted v default) | – | 0.5853 v 0.5884 on 38,985 matches | 0.6031 v 0.6068 on 31,158 matches |

K at 0 / 10 / 100 / 1,000 matches: ATP 76 / 55 / 32 / 17; WTA 105 / 54 / 33 / 20.
The WTA's ratings lean much more on the overall rating (w 0.28 against 0.46).

### 2.1 Game-share Elo: `gelo.py` (added 2 October 2026)

A margin-of-victory rating from the share of games won, added after the edge research
(docs/research/tennis_edge.md, experiment E3: the largest single improvement found). Ratings live on the logit
scale of the game share, overall and per surface (carpet folds into hard), all starting at 0:

```
before:  m_i = w · G_i,S + (1 − w) · G_i,all          diff = m_i − m_j  (0 if either was never rated)
after:   share = (games_i + 0.5) / (games + 1)
         g = (1 done, 0.5 ret/def) · min(1, games / 18)
         k = K · g · (1 + 3 / (1 + min(n_i, n_j) / 20))
         G_i,X += 4k (share − σ(G_i,X − G_j,X)),  G_j,X −= the same,   X ∈ {all, S}
```

Walkovers and matches without games are skipped. K and w per tour (ATP 0.06 / 0.4, WTA 0.12 / 0.2) were chosen on
the dev years 2012–2017 only, over the grid K ∈ {0.06, 0.12, 0.24} × w ∈ {0.2, 0.4, 0.6}. Out of sample (2018–2025)
adding it to the blend cut log-loss by 0.0024 (ATP) and 0.0046 (WTA), with 95 % CIs excluding zero. `history(tour)` is
cached under `ACE_CACHE/gelo/` (the build's `TourData.gelo` under `ace_gelo`); about 3 s per tour.

---

## 3. The serve/return model from scores: `serve_return.py`

The core of the site. There is no point-level ATP data (DATA_PIPELINE section 2.7),
so each player's serve and return strength is estimated from the **game and set
scores alone**, by an exact likelihood of every observed set.

### 3.1 Game, tiebreak and set probabilities

A server who wins each point independently with probability p (q = 1 − p) holds with

```
G(p) = p⁴ (1 + 4q + 10q²) + 20 p³q³ · p² / (1 − 2pq)          G(0.6) = 0.7357
```

`point_prob_from_hold(h)` inverts it exactly (34 bisection steps then 3 Newton
steps, to about 1e-15), with dp/dh = 1 / G′(p) for gradients.

**Tiebreaks** (to 7, or to 10): the tiebreak's first server serves point 0, then the
serve alternates every two points (A serves point k when ⌊(k+1)/2⌋ is even). An exact
lattice DP runs to (N−1, N−1); from a tie the next two points are one serve each, so
the pair is won with W = p_A(1 − p_B), lost with L = (1 − p_A)p_B, split with T, and
P(win from a tie) = W/(W + L); long tiebreak scores have probability P(tie) · T^(k−1)
· W.

**Sets**: with h_A, h_B the two hold probabilities and A serving game 0, the same DP
over games runs to 5-5; 6-x (x ≤ 4) comes from the lattice, 7-5 = P(5,5)·W,
5-7 = P(5,5)·L, 6-6 = P(5,5)·T (W, L, T now over holds), and 6-6 goes to a tiebreak
(to 7; to 10 in a "tb10" deciding set) whose first server is the set's first server.
Advantage sets continue in pairs, P(n+2 : n) = P(5,5) · T^(n−5) · W, up to `cap`
(20) games for the winner; "tb7@12" (Wimbledon 2019–21) is a 7-point tiebreak at
12-12. The next set's first server flips exactly when the set had an odd number of
games (a tiebreak counts as one). `set_score_probs(h1, h2, first_server, rule)` is the
public scalar version; the fit uses vectorised forward-mode versions (`_lattice`,
`_set_logp`, `_tb_logp`) that carry derivatives with respect to both holds.

### 3.2 The match likelihood of a scoreline

`parse_sets` turns a MATCH's sets into codes, stopping at the first set that is not a
completed set: kind 0 = 6-x, kind 1 = (n+2):n with n ≥ 5 (7-5, or a longer advantage
deciding set), kind 2 = a tiebreak at m-m (to N = 7, or 10 in a tb10 deciding set;
a deciding 7-6 whose tiebreak points only make sense to 10 is read as to 10). Exact
tiebreak points are used when the source gives them and they are consistent
(`_tb_points`), else only who won. Retirements and defaults keep their completed
sets; walkovers are excluded.

The match's first server is unknown, so

```
L(match) = ½ ∏_k P(set k | chain from p1 serving first) + ½ ∏_k P(set k | chain from p2 serving first)
```

on the log scale (`match_loglik_vec`, one row per set, `np.logaddexp` per match).

### 3.3 The model and the fit

```
logit P(i holds v j) = μ + clay/grass + indoor + bo5 + level + (s_i + ds_i,surf) − (r_j + dr_j,surf)
```

for surface in {hard (carpet folds in), clay, grass}; levels slam, finals, m1000,
500, 250, other, ch, q. Penalised maximum likelihood:

```
max  Σ_m w_m log L_m − λ/2 (|s|² + |r|²) − λ_d/2 (|ds|² + |dr|²) − λ_b/2 |base|²
w_m = 0.5^(age_days / half_life)            matches older than window_days dropped
```

with L-BFGS-B on the exact gradient (forward-mode through the game, set and tiebreak
DPs and through G⁻¹), vectorised over every set of the window, warm-started from a
previous fit (`prior`). The penalty makes the additive constants identifiable (μ is
unpenalised; s and r centre on zero).

**Mirror symmetry.** With the first server unknown, a scoreline is exactly as likely
under holds (h_A, h_B) as under (1 − h_B, 1 − h_A): every game flips from "server
won" to "receiver won", which is the same game sequence with the serving order
swapped, and the likelihood mixes both orders (tiebreak winners do not break it; only
exact tiebreak point scores and the stats layer do, weakly and strongly). The
score-only likelihood therefore has two modes, (μ, s, r) and (−μ, r, s) with every
baseline term negated. The fit keeps the physical one, **μ > 0** (tour-average holds
above 50 %, true of every tour-level season on both tours): when L-BFGS lands with
μ < 0, the exact image (`_mirror`) is taken and polished (`"mirrored": true` in the
output). Both committed fits converged without mirroring.

**Uncertainty (Laplace).** Per player an 8×8 block (s, ds_hard, ds_clay, ds_grass,
r, dr_…) of the empirical-Fisher matrix (sums of w · g g′ of each match's score by
surface; the s–r cross terms matter because set scores pin s_i + r_i far better than
s_i − r_i) plus the ridge, inverted; se of s_i + ds_i,surf is √(e′H⁻¹e). Opponent and
baseline covariance is ignored, so the bands are a little narrow.

**What the pages show** (`_assemble`): per player and per surface (and "all", the
player's own surface mix), against the **average tour-level opponent** on that
surface (`base.ref`: mean s and r over tour-level appearances):
`hold = σ(μ_surf + s − r̄ + k_hold)`, `break = 1 − σ(μ_surf + s̄ − r + k_hold)`,
`spw = σ(logit G⁻¹(hold_chain) + k_spw)`, `rpw` likewise, plus the chain-scale
`hold_chain`, `break_chain` and the standard errors. Unknown players take the mean
strengths of players with five or fewer matches (`new_s`, `new_r`).

### 3.4 Constants and tuning

`tune` is a forward-validation grid: fit at 1 January and 1 July of 2014–2019, score
the next 181 days of tour-level scorelines by out-of-sample log-likelihood per set.

| | half-life | λ | λ_d | λ_b | window | log-lik per set (chosen) | without player effects |
|---|---|---|---|---|---|---|---|
| Defaults | 365 d | 2 | 8 | 1 | 1,460 d | – | – |
| ATP | 540 d | 8 | 64 | 1 | 1,460 d | −2.7822 | −2.8615 |
| WTA | 365 d | 16 | 64 | 1 | 1,460 d | −2.7235 | −2.7781 |

The grids are stored in `fitted/serve_return_<tour>.json` (`tuning`). The same file
holds `model`, a fit through 1 October 2026 trimmed to players seen in the last two
years, which stands in when nothing can be fitted (DATA_PIPELINE section 8):

| Fit through 2026-10-01 | ATP | WTA |
|---|---|---|
| matches / sets / matches with stats | 15,709 / 39,587 / 0 | 22,748 / 52,384 / 16,400 |
| players kept | 617 | 1,047 |
| μ, clay, grass, indoor, bo5 | 1.092, −0.167, +0.322, +0.151, −0.233 | 0.245, −0.128, +0.248, +0.139, 0 |
| levels slam, finals, m1000, 500, 250, other, q | +0.132, +0.135, +0.065, +0.122, +0.076, −0.365, −0.109 | −0.119, −0.107, +0.018, −0.000, −0.067, −0.083, −0.161 (ch −0.114) |
| k_hold, k_spw | 0, 0 (no stats) | 0.352, 0.162 |

So an average ATP server holds about σ(1.09) ≈ 75 % on hard against the average
returner; the WTA's chain-scale hold is σ(0.245) ≈ 56 %, and the calibrated
(displayed) one σ(0.245 + 0.352) ≈ 64.5 %, against a real mean hold of 65.1 % in the
WTA statistics.

### 3.5 The WTA point layer (`stats=True`)

Where a WTA match has statistics, each player adds two binomial terms: serve points
won (`fs_won + ss_won` of `sv_pts`, at least 10 points) with
p_obs = σ(logit G⁻¹(h) + k_spw), and service games held (`sv_gms − (bp_faced −
bp_saved)` of `sv_gms`) with h_obs = σ(η + k_hold), weighted by `stats_weight` (1).
The two tour-level offsets exist because real tennis is not i.i.d.: the hold level
that best reproduces scorelines under the i.i.d. chain differs from real holds, and
both differ from G(real serve points won). So h (the **chain-scale hold**) stays the
quantity whose exact chain fits the scores, which is what match pricing needs, while
the statistics sharpen s and r and calibrate the displayed hold and serve points won.
Scores and statistics describe the same matches, a mild double count that makes the
standard errors a little optimistic where statistics exist. `for_tour` turns the layer
on for the WTA by default; the backtest's serve/return predictions and the
validation's "raw" model switch it off.

### 3.6 Validation against the real WTA statistics

Two checks, both in the WTA `calibration.json`:

- **`validation`** (`backtest.validate_hold`): the score-only model fitted through
  the latest date on disk, each player's inferred hold and serve points won averaged
  over her matches with statistics in the last 730 days against those opponents,
  against her real numbers (players with 15+ such matches). Committed run (151
  players, window to 2026-10-03): hold Pearson **0.723** (Spearman 0.709, RMSE
  0.082, bias −0.066); serve points won Pearson **0.730** (Spearman 0.706, RMSE 0.041,
  bias −0.036). The inferred numbers are on the chain scale, hence the negative bias.
- **`validation_stats`** (`serve_return.validate_stats`, run by the build on the
  completed years with statistics, 2016–2025, 47,667 player-match rows): for each
  year Y the score-only and the stats model are fitted through 31 December Y and
  compared on Y's matches (in sample) and on January–June of Y+1 (out of sample),
  at match and at player-season level (15+ matches). Player-season correlations of
  hold with the real hold:

  | | score-only raw | score-only calibrated (k offsets) | stats model |
  |---|---|---|---|
  | in sample (748 player-seasons) | 0.427 | 0.432 | 0.945 |
  | out of sample (512) | 0.283 | 0.278 | 0.651 |

  The calibrated offsets remove most of the bias (in-sample hold bias −0.108 raw,
  −0.034 calibrated) but not the noise: a single season's set scores carry much less
  information about a player's hold than her own service statistics. Yearly offsets:
  k_hold 0.28–0.40, k_spw 0.115–0.167. Real means: hold 0.651, serve points won
  0.569, mean G(real serve points won) 0.648.

The two numbers answer different questions: about 0.72–0.73 for two-year player
averages (`validation`), 0.43 in sample and 0.28 out of sample for single seasons
(`validation_stats`).

### 3.7 Public API

`game_hold`, `point_prob_from_hold`, `tiebreak_win`, `tiebreak_score_probs`,
`set_score_probs`, `match_loglik`, `fit`, `hold_prob(model, server, returner, surface,
level, best_of, indoor, calibrated=False)`, `serve_point_probs`, `score_loglik`,
`walk_forward`, `validate_stats`, `constants(tour)`, `for_tour(tour, through)` (cached
under `ACE_CACHE/serve_return/`; the committed model when no stores exist), `tune`,
`export_fits`. `hold_prob` returns the chain-scale hold unless `calibrated=True`.

---

## 4. The exact match chain: `match_chain.py`

Inputs: the two serve-point probabilities p₁, p₂ (scalars or arrays, one entry per
match). Everything is exact, not simulated.

- **Game**: `game_win(p)` (closed form), `game_from(p, a, b)` from any point score
  (backward recursion; deuce D = p²/(p² + q²)).
- **Tiebreak**: `tiebreak_win(p1, p2, to, first_server, points)` from any score, by an
  **iterative** backward pass over the lattice (section 12) with the closed form from
  ties.
- **Set**: `set_dist(p1, p2, first_server, rule, start, points)` gives {(g1, g2): P}
  from any games and points score. Rules: "tb7" (every non-deciding set, and deciding
  sets outside the Slam changes), "tb10" (Slam deciding sets from 2022, the
  Australian Open from 2019), "tb12"/"tb7@12" (Wimbledon 2019–2021), "adv" (followed
  exactly to CAP = 30 games each, then closed onto (CAP+2)-CAP with the exact win
  probability, so P(win) is exact and only the total-games tail beyond 60 is
  approximate).
- **Match**: `match_batch` / `match(p1, p2, best_of, final_set_rule, state)` run a
  forward pass over (sets won, next first server) carrying the total-games and
  game-margin distributions and the mass of paths without a tiebreak, giving
  `p1_win`, `sets` ("2-0" …), `games` {n: p}, `handicap` {g1 − g2: p}, `p_tiebreak`,
  `p_straight`, `exp_games`. The first server is a coin toss unless given. `state`
  ({sets, games, points, server, played}) starts from a live score.
- **LiveTable** gives P(p1 wins) from any (sets, games, server, points) state by
  backward recursion, O(1) per state after construction, vectorised over matches;
  `match_win_prob` (the fast path used everywhere a price is needed) is its
  pre-match value. It agrees exactly with `match(..., state=...)`.
- **Dispersion**: points are not i.i.d. over a whole match (a player's level on the
  day varies), so real matches are more lopsided at set level than one fixed pair
  implies. `match_mix` averages the chain over a per-match edge e ~ N(0, σ²) applied as
  (p₁ + e, p₂ − e), with 7-node Gauss-Hermite quadrature; `solve_shift(target, pA, pB,
  sigma=)` re-centres it so P(win) still equals the target. σ is fitted by the
  backtest (section 10.1) and stored in `predict_<tour>.json` (0.04 on both tours).

---

## 5. The match price: `predict.py`

1. **Serve/return**: h_i = `hold_prob(model, i, j, surface, level, best_of)` for each
   server (chain scale), p_i = G⁻¹(h_i), and `sr_p` = the chain's P(win).
2. **Elo**: `elo_p` = `elo.p_win(r1, r2, surface, best_of, params)`.
3. **Blend** on the log-odds scale with no intercept (the model is symmetric):
   `logit p = w_elo · logit(elo_p) + w_sr · logit(sr_p) + w_gelo · gelo_diff`, gelo_diff the game-share Elo
   difference (section 2.1; 0 when either player was never rated, and `w_gelo` 0 when a fit does not carry it).
   `blend_w` = w_elo / (w_elo + w_sr) is the Elo share among the two probability terms.
4. **Shift**: δ (40 bisection steps) such that the chain at (p_A + δ, p_B − δ)
   returns p; the serve dominance p_A + p_B, which drives tiebreaks and total games,
   is kept from the serve/return model. `p_srv` is that centre pair (it reproduces p
   exactly in the plain chain; live WP uses it).
5. **Distributions** (`dist`): the σ-mixture re-centred by its own shift, so
   `dist["p1_win"]` equals p and the set scores, games, handicap and tiebreak odds
   carry the dispersion.

| Weights | w_elo | w_sr | w_gelo | σ | Fitted on |
|---|---|---|---|---|---|
| `DEFAULT_BLEND` ATP | 0.55 | 0.45 | 0 | 0.03 | – |
| `DEFAULT_BLEND` WTA | 0.6 | 0.4 | 0 | 0.03 | – |
| `predict_atp.json` | 0.4924 | 0.2110 | 1.0511 | 0.04 | 41,491 matches 2010–2026, log-loss 0.5945 (was 0.6569 / 0.2879 / –, 0.5964) |
| `predict_wta.json` | 0.4661 | 0.2896 | 0.7204 | 0.04 | 39,238 matches 2010–2026, log-loss 0.6011 (was 0.7041 / 0.2985 / –, 0.6049) |

With the game-share term the two probability weights shrink (it carries part of the strength signal). The
game-share term is added only in the full blend (Elo and serve/return both present). Fallbacks: without a serve/return
model the serve level is `BASE_SPW` (ATP hard .645, clay .625, grass .665; WTA .565,
.555, .58) and Elo alone sets the edge; without Elo, `sr_p` alone. The deciding-set
rule comes from the MATCH (`final_set_rule`), else `default_final_rule` via
`canon.final_set_rule`. `prob_matrix(ctx, pids, ...)` gives every ordered pair's P in
one vectorised call (the simulators use it). Every row passes the match's indoor flag
(and the raw surface, so carpet counts as indoor) to `hold_prob`, as
`backtest.predictions` does, so the site serves the price the backtest scored.

**Which fit prices which match** (`analytics/matches.py`): a finished match uses the
exact pre-match Elo P from the Elo history, the exact pre-match game-share difference
(`TourData.gelo_pre`) and the serve/return fit through the day
before the first of its month (`checkpoint`), so a match never sees itself or
anything after its month began; live and upcoming matches use today's ratings and
the fit through yesterday. A past context without exact values prices the game-share
term at 0 (no monthly rating snapshots are built).

---

## 6. Live win probability: `live.py`

The serve-point pair is fixed before the match (`p_srv`, no in-match updating) and
the LiveTable is evaluated at each state. Sources give games per set, not the order of
games, so for a finished or live match without an observed sequence the path is
**reconstructed** (`"reconstructed": true`):

- the match's first server is the one that makes the observed set scores most likely
  (`first_server_ml`; a live feed's named server fixes it);
- within a set, among the game orders that reach the score without ending the set
  early, the most likely under the hold probabilities (holds as served, only the
  breaks the score needs), ties going to the most even spread of breaks
  (`set_sequence`);
- a tiebreak set is 12 games to 6-6 plus the tiebreak as one step; a long advantage
  set is pairs of holds then the two deciding games.

So excitement and comeback are exact at set boundaries and approximate within sets.
Measures: leverage of a game = P(win | p1 wins it) − P(win | p1 loses it);
excitement = Σ |Δp| from the pre-match price to the final 0/1; comeback = the
winner's minimum win probability and where; swings = the five largest |Δp| steps.

---

## 7. Tournament simulation: `tournament_sim.py`

`simulate(event, n=20000, matches, tour, ctx)`:

- **Knockout.** The DRAW's round-1 slots are padded to a power of two. An empty slot
  is a bye, unless its entry is Q or LL (a qualifier or lucky loser not yet known):
  that slot is a placeholder priced `QUALIFIER_LOGIT` = 0.4 below the field's median
  on the logit scale. Each finished match fixes its bracket node, and because a later
  result implies the earlier ones, both players' earlier nodes are fixed as wins too.
  A lucky loser named by the results is added. Remaining matches are won with
  P(i beats j) from `predict.prob_matrix` (the event's surface, best-of, level and
  deciding-set rule). `STRENGTH_SD` = 0 (no per-simulation strength draw by default).
- **Round robin** (ATP / WTA Finals): two groups of four (from `event["groups"]`, the
  round-robin pairings, or slots 1–4 / 5–8), every pair once, best of three; the
  winner of each simulated match is drawn with P, the set split and each set's games
  from the chain's distributions given the winner. Group order: wins; two tied → head
  to head; three tied → % sets won, then % games won, then seed/rank, with head to
  head whenever exactly two remain tied. Semi-finals A1–B2, B1–A2.
- **Outputs** per player: `p_title`, `p_final`, `p_sf`, `p_qf`, `reach` {round: p},
  `exp_points` (from `_points.table`, canon's tables; a bye followed by a loss earns
  first-round points), and `next`: the next match's opponents and the odds if they
  win or lose it, **interventional**: each simulation is weighted by 1/P(win | that
  simulation's opponent) (losses by 1/P(loss | …)) so the conditional odds measure the
  match's own effect, not the weaker opponents that winning simulations over-sample
  (the basketball season-simulation fix).

`bracket_from_results` rebuilds a finished knockout's tree from its results (the
backtest and events without a stored draw use it). For ATP events in progress the
stored DRAW is the reconstructed one (DATA_PIPELINE section 7.4), so paths beyond the
current round are approximate until it is set.

---

## 8. Season simulation: `season_sim.py`

`for_tour(tour, as_of, n=10000)` plays the rest of the calendar 10,000 times for the
top `N_PLAYERS` = 120:

- **Events**: this season's unfinished events, plus last season's events shifted by 52
  weeks for those not listed yet (carrying last season's names). An event in progress
  with a DRAW is simulated by `tournament_sim` with its results fixed; without one,
  the players still alive play out the rounds in a random bracket.
- **Entry** for events not yet drawn: Slams and 1000s `ENTRY["mandatory"]` = 0.92
  (ATP Monte Carlo is not mandatory), scaled by the player's own 12-month
  participation unless they played the event last season; 500s and 250s played last
  season 0.70; players in Race positions 6–20 chasing the Finals 0.45 (500) and 0.30
  (250); otherwise 0.20 (500) and 0.08 (250), halved for the top 10 at 250s. A player
  who has missed `INACTIVE["missed_big"]` = 2 or more Slams / 1000s since their last
  match returns this season with probability 0.5 (one draw per simulation). No one
  plays two events in a week (higher level first). Direct acceptances by rank fill
  80 % of the draw; the rest are "field" placeholders at the median strength of ranks
  60–120. Seeds (a quarter of the draw) in standard positions, random within tiers;
  byes to the top seeds.
- **Pricing**: one `prob_matrix` per (surface, best-of), **every future match priced
  as a 500 with a 7-point deciding-set tiebreak**.
- **Finals**: the Race's top 8 (ATP: a season Slam champion ranked 9–20 replaces the
  8th); seeds 1/2 head groups A/B, 3–4, 5–6, 7–8 split at random; round robin
  ordered by wins and head to head between two, otherwise at random; top two to the
  semi-finals.
- **Points**: year-end points = Race points + simulated points + Finals points (the
  year-end window is this season's events only; `basis` "race + new + Finals"); the
  snapshot route (official points − drops + points since + new) is reported per
  player as a check (`via_snapshot_mean`).

Outputs: `year_end_no1`, `finals_qual`, `finals_title`, `rank_dist` (ranks 1–20 and
21+), `points` and `race` {mean, p05, p95, now}, `events`, `simplifications`,
`basis`. The published simplifications: every result counts (no best-19 / best-18
rule); no injuries or withdrawals beyond random non-entry, no Finals alternates;
simulated Finals groups by wins and head to head; no qualifying or Challenger
points; strengths frozen; injury absences inferred from missed big events; the
calendar completed from last season.

---

## 9. Markets: `sources/markets.py`

- **Series**: Kalshi `KXATPMATCH`/`KXWTAMATCH` (per match, two markets named by
  player), `KXATP`/`KXWTA` (tournament winners, including next season's Slams by code
  AO/FO/WIM/USO), `KXATPFINALS`/`KXWTAFINALS`, `KXATP1RANK`/`KXWTA1RANK`,
  `KXATPFINALSQUAL`/`KXWTAFINALSQUAL` (binary, eight qualify),
  `KXATPGRANDSLAM`/`KXWTAGRANDSLAM` (binary: a Slam next year). Polymarket tag
  `tennis` (paged by 100): match moneylines (slug `atp-<a>-<b>-YYYY-MM-DD`), winner
  fields, "End of Year Rankings: Player to be Number 1" and "… Top 10", "Player to
  Qualify". Not used: set winners, game spreads and totals, exact scores, doubles.
- **Prices**: the midpoint (bid + ask)/2 of a live two-sided quote, 0 < bid ≤ ask < 1
  and spread ≤ 0.12; sources averaged per runner. A field is published only when at
  least max(4, half the field) runners are accounted for (quoted, written off by a
  "no bid, ask ≤ 2c" quote, or settled No) and the implied total is within 0.8–1.3;
  then de-vigged multiplicatively. Binary per-player markets are averaged, not
  de-vigged (a near-certain "bid ≥ 0.90, ask 1.00" is priced (bid + 1)/2). A match
  price: Kalshi's two sides de-vigged, q_a/(q_a + q_b); Polymarket's moneyline mid is
  already two-way; `p1` = the mean of the prediction-market sources, else Pinnacle's
  de-vigged close, else the average close (`basis`).
- **Names**: labels are full names; `map_player` tries the match's or event's field
  first, then the tour: exact folded name or alias, the same tokens in any order,
  "Surname I." via `canon.abbrev_matches`, surname plus first initial, a token subset
  with the same first name, a unique surname within the field. Unmatched labels are
  reported (`LAST_STATS`), split into players the registry knows but the store lacks
  (Challengers, qualifying) and unknown names; never guessed.
- **Edges** on the site are model minus market in percentage points; qualifying
  matches are never shown with an edge (`site.EDGE_HIDE_LEVELS`).

---

## 10. Backtest: `backtest.py`

### 10.1 Method

`backtest(tour, years=2010→, refit_days=30, warmup_years=2, tournament_sims=3000,
sigma="fit")`:

- **Matches scored**: tour-level singles (slam, finals, m1000, 500, 250) with status
  `done`, 2010 onward (retirements, walkovers and defaults feed the ratings but are
  not scored, since bookmakers settle them differently). Each match is oriented at
  random by an MD5 of its id, so y is 0 or 1.
- **Forecasters**, all from data strictly before the match: `elo` (the sequential
  history; its constants were fitted on 2005–2019, so for 2010–2019 the constants
  are in sample, and the output says so); `serve_return` (score-only fit refitted
  every 30 days through the day before each month, warm-started, cached under
  `ACE_CACHE/backtest_sr`); `model` (the blend, weights for year Y fitted on the
  years before Y, two warm-up years preceding 2010); `rank` (P = σ(b · (ln rank₂ −
  ln rank₁)), unranked = 300, b fitted on earlier years); `pinnacle`, `b365`, `avg`,
  `max` (closing odds de-vigged multiplicatively).
- **Scores**: log-loss (p clipped to [1e-4, 1 − 1e-4]), Brier, 10-bin reliability;
  overall, on the matches with a Pinnacle price (`vs_pinnacle`), with an average price
  (`vs_avg`), per year and per level.
- **Distributions**: σ fitted walk-forward per year over the grid 0–0.08 by
  set-score likelihood on earlier years; set-score calibration and multi-class
  log-loss, straight sets, at least one tiebreak, total games over lines (bo3
  19.5–25.5, bo5 33.5–41.5) with a randomised PIT histogram, the handicap log-loss and
  live P at each set boundary.
- **Tournaments**: each completed knockout's bracket rebuilt from its results, every
  entrant priced with the Elo they carried into their first match and the fit current
  at the start, simulated 3,000 times before the first round ("pre") and at the
  quarter-finals ("qf"); title, final and semi-final odds scored.
- **Validation** (WTA): `validate_hold` (section 3.6).

Output: `ACE_CACHE/backtest_<tour>.json` and `docs/ace/data/<tour>/calibration.json`
(`page_copy`); with `export_blend`, `fitted/predict_<tour>.json` (the blend on every
scored year and σ). Run by `scripts/tn_fit.py --backtest` or
`scripts/_tn_backtest_c.py`; runtimes 1,662 s (ATP) and 2,676 s (WTA).

### 10.2 Results (committed `calibration.json`, regenerated 2 October 2026 with the game-share term)

**ATP, 2010–2026, 41,491 matches (39,012 with Pinnacle, 40,442 with an average price)**

| Forecaster | log-loss, all | Brier, all | log-loss, Pinnacle subset |
|---|---|---|---|
| model (blend with game-share Elo) | 0.5948 | 0.2052 | **0.5940** (two-term blend: 0.5959) |
| Elo | 0.5981 | 0.2066 | 0.5974 |
| serve/return | 0.6053 | 0.2091 | 0.6045 |
| rank | 0.6161 | 0.2142 | 0.6160 |
| Pinnacle | 0.5703 | 0.1948 | **0.5703** |
| Bet365 / average / best | 0.5728 / 0.5729 / 0.5715 | 0.1957 / 0.1957 / 0.1953 | 0.5720 / 0.5722 / 0.5708 |

**WTA, 2010–2026, 39,238 matches (36,325 with Pinnacle, 37,766 with an average price)**

| Forecaster | log-loss, all | Brier, all | log-loss, Pinnacle subset |
|---|---|---|---|
| model (blend with game-share Elo) | 0.6013 | 0.2077 | **0.6034** (two-term blend: 0.6069) |
| Elo | 0.6062 | 0.2098 | 0.6083 |
| serve/return | 0.6121 | 0.2123 | 0.6136 |
| rank | 0.6277 | 0.2191 | 0.6278 |
| Pinnacle | 0.5829 | 0.2000 | **0.5829** |
| Bet365 / average / best | 0.5828 / 0.5832 / 0.5818 | 0.1999 / 0.1999 / 0.1996 | 0.5840 / 0.5845 / 0.5832 |

The rows other than the model are unchanged from the 1 October run (same data to within ten matches). The edge
research (docs/research/tennis_edge.md) found no model or feature that closes the remaining gap to Pinnacle.

The blend beats Elo alone by about 0.0014 (ATP) and 0.0011–0.0014 (WTA) every way it
is cut, and the serve/return chain alone is 0.006–0.007 behind Elo; Pinnacle is
about 0.026 (ATP) and 0.022–0.024 (WTA) better than the model. By level (ATP model /
Pinnacle): Slams 0.515 / 0.482, 1000s 0.605 / 0.586, 500s 0.593 / 0.568, 250s 0.632 /
0.604. Per year the ATP model ranges 0.562–0.622 (Pinnacle 0.541–0.598); 2026 holds
only 69 ATP and 98 WTA matches with a Pinnacle price. The walk-forward blend weights
drift from Elo-heavy (ATP 2010: 0.95 / 0.09) to 0.69 / 0.27 by 2026, as the
serve/return history lengthens; the WTA's stay near 0.65–0.72 / 0.22–0.29.

**Score distributions** (σ = 0.04 both tours, the best of the grid on all years;
per-year σ 0.04 ATP, 0.05 WTA from 2011):

| Check | ATP predicted v observed | WTA predicted v observed |
|---|---|---|
| bo3 set scores 2-0 / 2-1 (store orientation) | 0.319 v 0.321 / 0.180 v 0.180 | 0.338 v 0.334 / 0.161 v 0.166 |
| bo5 set scores 3-0 / 3-1 / 3-2 | 0.262 v 0.245 / 0.149 v 0.159 / 0.097 v 0.100 | – |
| straight sets | 0.615 v 0.609 | 0.677 v 0.665 |
| at least one tiebreak | **0.324 v 0.394** | **0.188 v 0.222** |
| mean total games bo3 / bo5 | 22.8 v 23.4 / 35.2 v 36.4 | 21.3 v 21.8 |
| set-score multi-class log-loss bo3 / bo5 | 1.262 / 1.507 | 1.232 |
| live P at set boundaries (log-loss, Brier) | 0.483, 0.159 (67,322 states) | 0.495, 0.162 (52,239) |

Set-score calibration is within about 2 points everywhere (best of three within 0.8;
best of five within 1.7); the chain **under-predicts tiebreaks** (7 points ATP, 3.4
WTA, in every reliability bin) and with them total games (about half a game in best of
three, 1.3 in best of five; the PIT histograms are light in the lowest bins); every
over line is under-predicted, by 1.3–5.3 points.

**Tournaments** (3,000 simulations a draw): ATP 1,042 events, title log-loss 0.0787
pre-draw and 0.0610 at the quarter-finals; the champion was the model's favourite
29.9 % of the time and in its top three 60.5 % (median rank 3). WTA 914 events, 0.0835
and 0.0610; favourite 24.0 %, top three 45.7 % (median 4).

**Validation**: section 3.6.

---

## 11. Other models

- **Bradley-Terry** (`bt.py`): each completed match a two-item Plackett-Luce order
  via `oddsmarkets.common.ranking.fit_strengths`, time-decayed (half-life 365 d,
  ridge 0.5, window 1,460 d), optional surface filter. A cross-check; nothing in the
  build calls it.
- **Synthetic matches** (`synthetic.py`): point-by-point simulation from planted
  serve/return strengths, emitted as MATCH rows with tiebreak points and WTA-style
  STATS; the tests use it to check that the fit recovers planted strengths.
- **Draw difficulty** (`analytics/events.py`): with Elo at the event's start, the
  bracket recursion gives each player's chance of reaching each round and their
  likely opponents; `exp_opp_elo` is the mean expected opponent's surface-blended Elo
  over the rounds (rank 1 = hardest path); an unknown qualifier counts at the field's
  25th percentile.
- **Awards and upsets**: match awards (`analytics/matches.py`: upset when the winner's
  pre-match P < 0.35, comeback when the winner's minimum P < 0.25, dominant at 70 % of
  games, tiebreaks against the chain's expectation); event upsets (winner's P < 0.40,
  at most 10), event awards (most wins over expected, most dominant, best in
  tiebreaks).
- **Clutch and wins over expected** (`analytics/players.py`): tiebreaks, deciding sets
  and wins from a set down against the chain's expectation from the season-end fit;
  wins against Elo's walk-forward expectation; on the WTA, real holds and serve points
  won against the calibrated expectation.

---

## 12. The memory incident (1 October 2026)

The first full backtest grew to about **270–296 GB** of memory. The cause was a
reference-cycle leak in `match_chain`: the tiebreak and set-class tables were built by
**recursive closures** (a nested function that called itself through the enclosing
scope) holding numpy arrays. A self-referencing closure is a reference cycle, so the
tables were not freed when they went out of scope; only the cyclic garbage collector
could reclaim them, and with arrays of thousands of matches built for every month and
every (best-of, rule) group they accumulated faster than it ran.

The fix (`79c62e9`):

1. `tiebreak_win` became an **iterative** backward pass over the lattice ("no
   recursive closure (no reference cycle)").
2. The set-class recursion became a class, `_SetClasses`, whose memo is an attribute,
   so discarded tables are freed by reference counting.
3. The backtest is **chunked** (`CHUNK` = 2,000 matches per mixture call, since the
   σ-mixture expands each row 7-fold) and keeps serve/return fits as cache paths, not
   models (about 200 monthly fits in memory had been the bulk of the remaining
   footprint); the tournament checkpoints load one fit at a time.
4. A regression test, `tests/tennis/test_models_c.py::test_chain_tables_free_memory_without_gc`,
   disables the garbage collector and checks that 20 repetitions of a 3,000-match
   best-of-five tb10 chain and tiebreak grow traced memory by less than 5 MB.

`tournament_sim.bracket_from_results` and `store.reconstruct_draw` still use
recursive closures, but over small lists of ids, not arrays.

---

## 13. Known limitations

1. **Inferred, not measured** (ATP everywhere, WTA before 2016 and at the Slams).
   Scores say who held, not how; and single-season inferred holds correlate only
   0.28 (out of sample) to 0.43 (in sample) with real ones (section 3.6). Two-year averages are much better
   (0.72).
2. **Points are i.i.d. within a match** apart from the σ dispersion: tiebreaks and
   total games are under-predicted (section 10.2).
3. **Indoor** is fitted in the serve/return model and passed with every match price
   (since 1 October); Elo has no indoor term. Tournament and season simulations price
   their matches without it, as the tournament backtest does.
4. **No in-match updating**: live probabilities hold the pre-match serve-point pair;
   reconstructed game orders make within-set paths approximate.
5. **ATP draws are reconstructed**: without seeds, and approximate beyond the current
   round until it is set.
6. **Simulations** freeze strengths, ignore retirements and injuries (beyond the
   season simulation's inactivity rule), price every future season match as a 500 with
   a tb7 deciding set, and count every result (no best-N rule).
7. **Hand-entered tables** (points, levels, draw sizes, deciding-set rules) are marked
   VERIFY in `canon.py` and apply the 2025 points to every year.
8. **Charted style data is a selected sample** weighted to big matches and well-known
   players, and is a career profile, not a season one.
9. **The market beats the model**, as it should: Pinnacle's closing price is about
   0.025 better in log-loss on both tours.

---

## 14. Where the code and other texts disagree

Every item below was found on 1 October 2026 and fixed the same day (marked **Fixed**,
with what changed). Items 7 and 13 changed the stated text rather than, or as well as,
the code where the code was right.

### 14.1 The site's Methodology (`docs/ace/assets/js/docs.js`) against the code

1. **"The WTA has no committed fits and runs on the code defaults."** Said in the
   file's header comment, the Elo table's column heading ("Code default (WTA until
   fitted)"), the serve/return fitting paragraph, the match-price list, the
   Limitations ("The WTA runs on defaults …") and the page's intro line. The WTA fits
   were committed on 1 October (`9d58ffb`, `e3071b8`): Elo constants (table in
   section 2), serve/return constants (365 d, λ 16, λ_d 64) and the blend (0.7041,
   0.2985, σ 0.04). **Fixed 1 October 2026.** Every such claim is gone; the Elo table has ATP,
   WTA and code-default columns, and the serve/return section gives both tours' baselines
   and constants.
2. **ATP blend weights**: the Methodology says w_Elo = 0.7262, w_SR = 0.1954 (Elo share
   0.79, sum 0.92). `predict_atp.json` holds 0.6569 and 0.2879 (Elo share 0.695, sum
   0.945), from the 2010–2026 backtest. **Fixed 1 October 2026.** Both tours' committed weights
   are quoted (ATP 0.6569 / 0.2879, WTA 0.7041 / 0.2985).
3. **Dispersion**: "σ = 0.03 by default (the ATP prediction file carries no fitted
   σ)", and "the set-score, games and tiebreak distributions come from the shifted
   chain". Both prediction files carry σ = 0.04 (fitted walk-forward), and the
   distributions come from the σ-mixture with its own shift. **Fixed 1 October 2026.**
4. **The direction of the chain's bias** (Limitations): "the backtest shows fewer
   straight sets and more total games forecast than happen". The committed backtest
   shows the opposite: slightly more straight sets forecast than happen (ATP 0.615 v
   0.609, WTA 0.677 v 0.665) and fewer total games (ATP 22.8 v 23.4 in best of three,
   35.2 v 36.4 in best of five; WTA 21.3 v 21.8). The larger miss, tiebreaks
   under-predicted (ATP 0.324 v 0.394, WTA 0.188 v 0.222), is not mentioned. **Fixed 1 October 2026.**
5. **Season simulation**: the Methodology says "year-end points are the latest
   ranking minus last season's points that drop off plus points earned since and
   simulated". The code's year-end points are Race + simulated + Finals points; the
   snapshot route is only a reported check (`via_snapshot_mean`). It also omits the
   chase entry probabilities (0.45 / 0.30 for Race positions 6–20) and the inactivity
   rule (two or more missed Slams / 1000s → returns with probability 0.5). **Fixed 1 October 2026.**
6. **Catalogue size**: "about 110 metrics"; the code has 138 (`analytics/players.py`
   `METRICS`). **Fixed 1 October 2026.** (138 in the Methodology, `PAYLOADS.md` and the
   `players.py` docstring).
7. **The WTA point layer**: "real WTA holds run a few points below what G applied to
   the real serve-point rate predicts" (the `serve_return.py` docstring says "about 5
   points below"). In the committed validation the mean real hold (0.651) is slightly
   above the mean G(real serve points won) (0.648). What is true is that the
   chain-scale holds sit below real holds (k_hold = +0.35). **Fixed 1 October 2026.** The
   Methodology and the `serve_return.py` docstring now say exactly this.
8. **ESPN coverage**: "read from 2004": `ESPN_FROM = 2004`, but the season scoreboards
   are empty before 2007. **Fixed 1 October 2026.** `ESPN_FROM = 2007` in `tn_fetch.py`, and the
   Methodology says the season scoreboards are read from 2007.
9. **Deciding-set rules**: the list ends "every other event a 7-point tiebreak at
   6-6"; `canon.final_set_rule` also gives the Olympics advantage final sets to 2012.
   **Fixed 1 October 2026.** The Olympics rule is listed.
10. **The WTA validation**: the backtest paragraph describes only the per-player
    730-day check; the WTA page also carries `validation_stats` (per year,
    player-season, in and out of sample; section 3.6). **Fixed 1 October 2026.** Both are
    described: the two-year window (r ≈ 0.72 hold, 0.73 SPW) and the single seasons
    (0.28–0.43).

### 14.2 The head-to-head page (`docs/ace/assets/js/h2h.js`) against the fits

11. The in-browser matchup uses hard-coded constants: `W_SURF.wta = 0.5` and
    `BO5.wta = 1.1` (fitted 0.2840 and 0.9958), the ATP surface offsets `SURF_OFF`
    for both tours (the WTA's own clay and grass terms are −0.128 and +0.248), and a
    fallback `BLEND` of ATP 0.72621 / 0.19541 and WTA 0.6 / 0.4 (used only when
    `calibration.json` has no `blend_all_years`; the committed files have it, with
    the fitted weights). Its note says "The WTA runs on the code-default constants
    until its own fits are committed". `data/<T>/model.json` publishes exactly these
    constants per tour, but no page reads it. **Fixed 1 October 2026.** `h2h.js` loads
    `data/<T>/model.json` and takes from it the Elo surface weight and best-of-5 stretch,
    the blend weights and σ (the set scores now come from the σ-mixture, as in
    `predict`), the serve/return surface terms (centred on the tour's `surface_share`),
    best-of-5 term and `k_hold` (the chain is priced on the chain scale), and `base_spw`;
    the hard-coded constants, the `calibration.json` / `BLEND` fallback and the "WTA runs
    on defaults" note are gone. Without `model.json` the page says the matchup cannot be
    priced. No other page carries model constants (checked: calibration.js reads the
    backtest's own weights).

### 14.3 Within the code and the contracts

12. **Indoor in the backtest but not on the site**: `backtest.predictions` passes the
    match's `indoor` flag to `hold_prob`; `predict.Context.p_srv` (every price on the
    site) does not. The backtest therefore scores a slightly different serve/return
    price from the one the site serves. **Fixed 1 October 2026.** `Context.p_srv` takes `indoor`
    and the raw surface; `predict_many` rows, `predict` and `prob_matrix` carry it, and
    `analytics/matches.predictions` passes each match's flag (tests in
    `tests/tennis/test_ace_fixes.py`).
13. **The workflow comment** says the model fits come "from the Actions cache (the
    committed fits in oddsmarkets/tennis/models/fitted/ when the cache is cold)". With
    the committed stores a cold cache refits serve/return from the stores; the frozen
    model is used only when a fit fails within 45 days of today or no stores exist.
    The constants and the blend always come from `fitted/`. **Fixed 1 October 2026.** Measured:
    a cold serve/return fit takes about 20 s (ATP) and 40–80 s (WTA), and a cold build
    makes about 50 ATP and 40 WTA of them (monthly checkpoints of the match-page years
    and every season end for the careers), past the Build step's 30-minute limit, so
    refitting everything in CI is not cheap and a cold cache could never warm. The loader
    (`TourData.sr_fit`) now refits past checkpoints only within `ACE_SR_FIT_BUDGET`
    seconds (600 in the workflow; unset locally = no limit). A fit within 45 days of
    today is always made, the committed model standing in if it fails; a past checkpoint
    beyond the budget gets no serve/return model that run (never the committed one, which
    saw later matches) and the match pages and light years built with it are left
    unsigned, so later runs rebuild them as the cache warms. The workflow comment says
    so.
14. **`validate_hold`'s window** ends at the latest date of any match on disk,
    scheduled ones included (the committed run says 2026-10-03, two days after it
    ran). **Fixed 1 October 2026.** The default window ends at the last completed (rated)
    match on or before the run date.
15. **`backtest.evaluate`** falls back to `DEFAULT_BLEND["atp"]` for both tours when a
    year has no earlier predictions (never reached with two warm-up years). **Fixed 1 October 2026.**
    `evaluate(..., tour=)` falls back to `predict.blend_params(tour)` (the tour's committed
    fit, else its own default); `backtest` passes its tour.
16. **`_points.FALLBACK`** has WTA 250 QF = 57; `canon.POINTS` (which wins) has 54.
    **Fixed 1 October 2026.** `FALLBACK` is deleted; `_points.table` is `canon.points_table` with the
    Finals keys renamed, and a level canon has no table for earns nothing (the old
    fallback gave an ATP Challenger the 250 table). canon's tables were checked round by
    round against the WTA 2024 ranking point chart (approved 14 September 2023: WTA 250
    QF = 54) and the ATP 2025 rulebook; all agree.
17. **`_tn_backtest_c.py`** hard-codes the last year (`range(y0, 2027)`). **Fixed 1 October 2026.**
    The range ends at the last season with a store (`_io.years_on_disk`).
18. **Match-page signatures** (`analytics/matches.page_sig`) include the model
    versions and `w_elo` but not the fits; a refit does not rebuild finished matches'
    pages (`--all-matches` does). **Fixed 1 October 2026.** `page_sig` and the light-year
    `year_sig` (which gates event pages) include `_io.fits_signature(tour)`, a digest of
    the parsed `predict_`, `serve_return_` and `elo_params_<tour>.json`, so a refit
    rebuilds finished match and event pages (the first build after this change rebuilt
    them all once).
19. **`PAYLOADS.md`** says ~110 metrics in its main section and ~140 in "As built";
    there are 138. Its `rankings.json` contract says the Elo list is "active: a rated
    match in the last year, ≥ 10 rated", which matches the code. **Fixed 1 October 2026.** Both
    say 138. The hard-coded `slams_2027` payload key is now `slams_<current season + 1>`
    (`analytics/site.markets_payload`), read by `markets.js` from whichever
    `slams_<year>` key is present.
20. **The figures quoted in conversation** (1 October): "ATP model 0.596 v Elo 0.597 v
    rank 0.616 v Pinnacle 0.570" are the Pinnacle-subset numbers (all matches: 0.5967,
    0.5981, 0.6161, Pinnacle 0.5703); "inferred hold v real WTA r ≈ 0.74 (player
    level)" is 0.723 (hold) and 0.730 (serve points won) in the committed
    `calibration.json`.

---

## 15. Value: breakouts, luck, over/undervalue (`analytics/value.py`, added 15 October 2026)

The Value section (`#/<T>/value`, DASHBOARD section 3.11) answers "who will rise or fall, how much of a record is luck, and
where do the ranking and the market disagree with the model". Payloads: PAYLOADS.md, "The Value section". Every number
quoted below is from the run of 15 October 2026 (models trained on the windows closed by 1 October 2026) and is in
`docs/ace/data/<T>/value_validation.json`; the Validation view shows the live figures.

### 15.1 The match table and the model rating

`match_table` puts every finished match of any level (walkovers included) into numpy columns, one row per player: date,
level, round, best of, status, games and completed sets won and lost, the ranks and points on the row, the pre-match Elo of
both players (surface-blended; walkovers take each player's latest overall rating), the de-vigged close (Pinnacle, else the
Betfair exchange, else the average), WTA points won and break points, the seed band in the event (the order of the entrants'
ranks: 1-2, 3-4, 5-8, 9-16, 17-32 within the draw's seeds, else unseeded) and the event's field strength (the mean pre-match
Elo of its entrants).

The **model rating** linearises the match price (section 5) around an even best-of-three hard-court match:

```
R = w_elo E + (400 / ln 10) (w_sr beta (s + r) + w_gelo G)      E = overall Elo, G = game-share Elo, s + r = serve + return
beta = d logit(chain P) / d(s + r) at an even match with the fit's mu   (1.99 ATP)
```

A constant is added so the active top 100 average as on Elo; surface ratings use the surface blends and the surface s + r.
`implied_ranks` hands the official ranks of the players with both (inside the top 300) out in the order of R: the **rank the
model implies**. The ratings at any date come from one pass over the Elo and game-share histories (`elo_states`,
`gelo_states`, equal to `elo.ratings_at` / `gelo.ratings_at`, tested) and, for past snapshots, from the backtest's monthly
score-only serve/return fits (`backtest_sr`, the newest file per date; never refitted here).

### 15.2 The breakout model

| Item | Choice |
|---|---|
| Snapshots | 1 January, April, July, October; from 2008 (ATP) and 2009 (WTA) |
| Universe | latest official rank on a match row in the 120 days before the snapshot, 150 or better (the live list: the official snapshot's top 150) |
| Target | log(rank observed nearest the snapshot + 365 (182) days, within 45 days) - log(rank); none there = unobserved |
| Features | log rank; ranking v model = log rank - log implied rank (shrunk by n / (n + k), n = rated matches in 12 months); age, age² and an unknown-age flag; Elo change and log-rank change over 6 months; log(1 + days out); log(1 + rated matches in 12 months); tour-level points dropping within the horizon / official points; tour-level points held / official points; close-match and draw luck per match over 12 months; the closing market's rating minus Elo's (12 months, shrunk by 10 matches) |
| Model | ridge regression on standardised features (missing = the training mean), refitted every year on the snapshots whose window closed by 1 January (`walk_forward`); the same features fitted to the Elo change |
| Settings | lambda in {1, 10, 100, 1000} x k in {0, 5, 10, 20, 40} by mean yearly Spearman on the dev years 2010-2017: lambda 100, k 0 (both tours; the grid is flat) |
| Events | breakout: rank at least a third better and 5+ places up; regression: at least half worse and 5+ places down, or unobserved. Probabilities: logistic on (the forecast's distance from the event's threshold at that rank, log rank), walk-forward; the threshold is min(log 2/3, log((rank - 5) / rank)) for a breakout and max(log 1.5, log((rank + 5) / rank)) for a regression |
| Range | 10th-90th percentile of past residuals in the rank band (1-20, 21-50, 51-100, 101-150) |
| Snapshot filter | a snapshot whose universe is under half observed at the horizon is dropped (the 2020 stoppage: at 12 months the 1 July 2019 snapshot on both tours; at 6 months 1 January 2020; `value_validation.json` `panel.dropped` lists the 12-month ones) |

Walk-forward results (Spearman of forecast v actual change, 95 % CI resampling players; hit = share of each snapshot's ten
likeliest breakouts outside the top 10 / regressions that happened, against the base rate):

| | ATP 12 m | WTA 12 m | ATP 6 m | WTA 6 m |
|---|---|---|---|---|
| test 2018-2025: model | **0.459** [0.422, 0.499] | **0.477** [0.440, 0.517] | **0.517** [0.489, 0.544] | **0.562** [0.535, 0.586] |
| rank only (same ridge) | 0.278 (+0.181 [0.123, 0.237]) | 0.287 (+0.191 [0.144, 0.234]) | 0.192 | 0.222 |
| rank + model gap | 0.341 | 0.441 | 0.368 | 0.470 |
| Elo change (its own fit) | 0.409 | 0.339 | 0.319 | 0.275 |
| breakout list hit v base | 44 % v 18 % (lift 2.4) | 52 % v 20 % (2.6) | 43 % v 14 % (3.1) | 45 % v 15 % (3.0) |
| regression list hit v base | 71 % v 43 % | 71 % v 43 % | 71 % v 29 % | 67 % v 32 % |
| Brier breakout (model v base) | 0.138 v 0.148 | 0.143 v 0.158 | 0.105 v 0.118 | 0.110 v 0.125 |
| Brier regression (model v base) | 0.226 v 0.239 | 0.224 v 0.240 | 0.181 v 0.200 | 0.192 v 0.211 |
| dev 2010-2017: model | 0.430 | 0.419 | 0.513 | 0.529 |

Per test year (ATP 12 m) 0.38-0.52; the weakest years are the latest (2025: 0.38) and 2022 on the WTA (0.35). Dropping a
feature (test years, 12 m) costs: ATP age 0.071, model gap 0.051, log rank 0.020, market 0.010; WTA model gap 0.094, age
0.023, log rank 0.012, market 0.010; at 6 m the points to defend (0.018 / 0.017) and the tour-level share (0.010 / 0.009)
join them. The trends, days out, activity and both luck features add nothing measurable. Standardised coefficients (12 m,
log-rank units, negative = a better rank): ATP gap -0.23, log rank -0.12, age +0.12 (age² +0.07), market -0.06, days out
+0.03; WTA gap -0.28, log rank -0.16, age +0.09, market -0.08, days out +0.05. The age curve (mean 12-month change in rank by
age) runs from about -36 % at 19 to +56 % at 34 and over (ATP; WTA -25 % to +37 %), crossing zero at about 25 (ATP) and 23-24 (WTA).

Limits: the universe is the official top 150, so a player returning from a long absence outside it gets no forecast (the
over/undervalue table still rates him); ranks are observed only on tour-level main-draw rows (ATP ranks below the ESPN top
150 come from the latest match), so "unobserved" mixes falls, injuries and retirements; the points calendar counts
tour-level points only (no Challenger, WTA 125 or ITF points in the data); the blend weights inside the model rating were
fitted on 2010-2026 match outcomes (not on ranking changes).

### 15.3 Luck

Per player and window (tour-level main draws; the page: the last 52 weeks and the current season, 10+ matches):

```
close-match luck = wins - sum over completed matches of P(win | s),  P = s^k / (s^k + (1 - s)^k) = sigmoid(k logit s),
                   s = (games won + 0.5) / (games + 1); k by MLE on completed tour-level matches to 2017:
                   ATP 20.2 (best of 3), 26.3 (best of 5); WTA 19.3
points version   = the same from the share of points won (WTA statistics; k 27.4, every season with statistics)
conversion       = sum P(win | games) - sum P(win | points)              shown, not counted (r about 0.5 season to season)
tiebreaks, deciding sets = won - the chain's P (the catalogue's clutch measures, the season's serve/return fit)
break points     = saved - faced x (serve points won outside break points + offset), converted likewise; offset +0.0145 / -0.0145
draw luck        = sum [Elo P(v the opponent) - mean_q Elo P(v field strength + q)], q = 19 quantiles (5 %...95 %) of
                   (opponent Elo - field strength) at that level, round and seed band in the years before
strength of schedule = mean (opponent Elo - the typical opponent's mean), centred on the window's players; reported, not counted
free wins        = walkovers received (1 - Elo P) + opponents' retirements (1 - P(win | completed sets), independent sets
                   with the per-set probability that reproduces the Elo P)
wins above expectation = close-match luck + draw luck + free wins;   luck-adjusted win % = (wins - close - draw) / matches
```

Averaging P over the reference distribution (not P at the mean reference opponent) matters: with the mean, draw luck
correlated 0.44 from one season to the next on the ATP (strong players always "unlucky", since P is concave for them);
with the distribution and the field-relative reference, 0.12.

Evidence (players with 20+ tour-level matches in consecutive seasons; ATP 1,916 pairs 2000-2025, WTA 1,209 pairs 2007-2025;
Pearson r with 95 % CI resampling players):

| Season to season | ATP | WTA |
|---|---|---|
| wins above expectation per match | 0.08 [0.04, 0.13] | 0.04 [-0.02, 0.10] |
| close-match luck | 0.06 [0.01, 0.12] | 0.05 [-0.01, 0.11] |
| tiebreaks over expected | 0.04 [-0.01, 0.08] | -0.02 [-0.07, 0.05] |
| deciding sets over expected | 0.07 [0.03, 0.12] | 0.08 [0.03, 0.14] |
| draw luck | 0.12 [0.07, 0.17] | 0.03 [-0.03, 0.09] |
| free wins | 0.05 [-0.01, 0.10] | -0.03 [-0.08, 0.03] |
| break points saved / converted over expected | – | -0.02 [-0.12, 0.06] / 0.10 [0.01, 0.18] |
| points-to-games conversion (not counted) | – | 0.50 |
| strength of schedule (not counted) | 0.14 | -0.02 |
| win % / share of games won (skill) | 0.67 / 0.72 | 0.57 / 0.64 |
| next-season win %: raw, Pythagorean, luck-adjusted (r) | 0.667, 0.679, 0.683 | 0.570, 0.578, 0.582 |
| luck-adjusted minus raw | +0.016 [0.007, 0.026] | +0.012 [0.002, 0.024] |
| walk-forward RMSE of next-season win %, raw v adjusted | 0.101 v 0.098 | 0.108 v 0.107 |

### 15.4 The market against the model

`market_view`: over the last 52 weeks, every tour-level match with the build's pre-match price (`analytics/matches.predictions`,
the exact pre-match Elo and game-share difference, the month's serve/return fit) and a de-vigged close; per player the mean of
logit(market) - logit(model) in Elo points (divided by the best-of-five stretch for those), actual wins against both
expectations, and both log-losses; the same with Kalshi's mid about 4 h before the start where the research cache has it
(`research/kalshi_edge.load`, decision "late"; June 2025 - 1 October 2026). On 15 October 2026: ATP 2,468 matches, log-loss
market 0.594 v model 0.613 (Kalshi subset 1,939: 0.590 v 0.610); WTA 2,450, 0.572 v 0.588 (Kalshi 1,863: 0.577 v 0.593). The
page frames gaps as disagreements (section 13, item 9; docs/research/tennis_edge.md).

### 15.5 Dates of birth

The age terms need dates of birth, which tennis-data and ESPN's scoreboards do not carry and the WTA API gives for some players
only. `scripts/tn_bio.py` asks ESPN's core athlete API (`sports.core.api.espn.com/v2/sports/tennis/leagues/<T>/athletes/<id>`,
"dateOfBirth") for players with an ESPN id and 5+ rated matches since 2005, writing `docs/ace/data/<T>/bio.json`; on
15 October 2026 it found dates for 956 of the 962 ATP and 590 of the 605 WTA players asked (1,567 calls, no failures). `TourData.players`
fills a missing `dob` from it, so ATP ages now appear in the catalogue too.
