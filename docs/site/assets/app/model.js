/* The Quant Footballer — Model (#/model): how the numbers are made, and where they are wrong.
 *
 *   #/model                         overview: one card per model with its headline check, linking into the rest
 *   #/model/methodology[/<section>] the full methodology document with a sticky contents list;
 *                                   ?c=<slug> adds the competition's own card (settings, calibration, format)
 *   #/model/glossary[/<key>]        every metric and model term, searchable, grouped; a key deep-links
 *   #/model/calibration             what the models' own checks say: match-model calibration by competition,
 *                                   the value model's out-of-sample fit, the fee model and the fantasy backtest
 *   #/model/coverage                which seasons are complete and why some rows are lower bounds
 *   #/model/disclaimer              the disclaimer and terms (from <template id="disclaimer-template">)
 *
 * Reads glossary.json, value/meta.json, fantasy/meta.json and each competition's meta.json (table.json,
 * bracket.json for a competition card), only where the competition writes them. The methodology text follows
 * docs/MODELS.md and docs/DATA_PIPELINE.md (ported from the previous site); the coverage text follows
 * docs/football_data_audit.md and docs/site/UNIFIED_PAYLOADS.md section 13. */
(function (FB) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = FB.esc, isNum = FB.isNum, num = FB.num, pct = FB.pct;

// ── glossary: fallback definitions (the payload normally carries them) ──────

var DESC = {
  goals: 'Goals scored, penalties included.',
  goals_90: 'Goals per 90 minutes: goals divided by (minutes / 90).',
  npg: 'Non-penalty goals: goals minus penalties scored, with penalties counted from the match incidents.',
  npg_90: 'Non-penalty goals per 90 minutes.',
  xg: 'Expected goals: the sum of Sofascore\'s chance quality over every shot the player took. A penalty carries 0.79.',
  xg_90: 'Expected goals per 90 minutes.',
  npxg: 'Non-penalty expected goals: xG with 0.79 removed for each penalty taken, floored at zero.',
  npxg_90: 'Non-penalty xG per 90 minutes; the cleanest measure of the chances a player gets from open play and set pieces.',
  xgot: 'Expected goals on target: the post-shot value of the shots that hit the target, given where in the goal frame they went. Off-target shots count zero.',
  xgot_90: 'xGOT per 90 minutes.',
  g_minus_xg: 'Goals minus expected goals. Positive means the player has scored more than the chances were worth; over a season it is mostly finishing variance.',
  shots: 'Shots taken, blocked shots included.',
  shots_90: 'Shots per 90 minutes.',
  sot: 'Shots on target.',
  sot_90: 'Shots on target per 90 minutes.',
  sot_pct: 'Share of shots that hit the target: shots on target divided by shots.',
  xg_per_shot: 'Average chance quality: total xG divided by shots. High values mean the player shoots from good positions.',
  big_chances_missed: 'Big chances (Sofascore\'s label for a clear scoring opportunity) that the player failed to score.',
  pens: 'Penalties scored.',
  assists: 'Assists: the last pass before a goal.',
  assists_90: 'Assists per 90 minutes.',
  xa: 'Expected assists: the xG of the shots the player\'s passes created, whether or not they were scored.',
  xa_90: 'Expected assists per 90 minutes.',
  key_passes: 'Key passes: passes that led directly to a shot.',
  key_passes_90: 'Key passes per 90 minutes.',
  big_chances: 'Big chances created: passes that produced a clear scoring opportunity.',
  big_chances_90: 'Big chances created per 90 minutes.',
  passes: 'Passes attempted.',
  passes_90: 'Passes attempted per 90 minutes.',
  pass_pct: 'Pass completion: accurate passes divided by passes attempted, both summed over the season.',
  opp_half_passes_90: 'Passes played in the opposition half per 90 minutes.',
  long_balls_90: 'Accurate long balls per 90 minutes.',
  long_ball_pct: 'Long-ball accuracy: accurate long balls divided by long balls attempted.',
  crosses_90: 'Accurate crosses per 90 minutes.',
  cross_pct: 'Cross accuracy: accurate crosses divided by crosses attempted.',
  touches: 'Touches of the ball.',
  touches_90: 'Touches per 90 minutes: how involved the player is.',
  dribbles: 'Dribbles completed (take-ons that beat the defender).',
  dribbles_90: 'Completed dribbles per 90 minutes.',
  dribble_pct: 'Dribble success: completed dribbles divided by dribbles attempted.',
  carries_90: 'Carries per 90 minutes.',
  prog_carries_90: 'Progressive carries per 90 minutes: carries that move the ball a meaningful distance towards the opposition goal.',
  carry_dist_90: 'Distance carried with the ball per 90 minutes, in metres.',
  dispossessed_90: 'Times tackled off the ball per 90 minutes. Lower is better.',
  poss_lost_90: 'Possession lost per 90 minutes, from any cause: misplaced passes, failed dribbles, being dispossessed. Lower is better.',
  tackles: 'Tackles made.',
  tackles_90: 'Tackles per 90 minutes.',
  tackle_pct: 'Tackle success: tackles won divided by tackles attempted.',
  interceptions: 'Interceptions.',
  interceptions_90: 'Interceptions per 90 minutes.',
  clearances_90: 'Clearances per 90 minutes.',
  blocks_90: 'Blocked shots per 90 minutes.',
  recoveries: 'Ball recoveries: loose balls regained.',
  recoveries_90: 'Ball recoveries per 90 minutes.',
  errors: 'Errors that led directly to an opposition shot. Lower is better.',
  duels_won: 'Duels won, ground and aerial.',
  duels_won_90: 'Duels won per 90 minutes.',
  duel_pct: 'Duel success: duels won divided by duels contested.',
  aerials_won_90: 'Aerial duels won per 90 minutes.',
  aerial_pct: 'Aerial success: aerial duels won divided by aerial duels contested.',
  fouls_90: 'Fouls committed per 90 minutes. Lower is better.',
  fouled_90: 'Fouls suffered per 90 minutes.',
  saves: 'Saves made.',
  saves_90: 'Saves per 90 minutes.',
  save_pct: 'Save percentage: saves divided by (saves + goals conceded). Goals conceded in a partial appearance are scaled by minutes played over 90.',
  goals_prevented: 'Goals prevented: the post-shot xG (xGOT) of the shots faced minus the goals conceded. Positive means the keeper has stopped more than an average keeper would.',
  goals_prevented_90: 'Goals prevented per 90 minutes.',
  conceded: 'Goals conceded while on the pitch (the opponent\'s goals, scaled by minutes played over 90). Lower is better.',
  conceded_90: 'Goals conceded per 90 minutes. Lower is better.',
  saves_in_box: 'Saves from shots taken inside the penalty area.',
  sweeper_90: 'Sweeper-keeper actions per 90 minutes: clearances and interceptions outside the area.',
  high_claims_90: 'High balls claimed per 90 minutes.',
  punches: 'Punched clearances.',
  km: 'Distance covered, in kilometres (from Sofascore\'s tracking data, where the competition provides it).',
  km_90: 'Distance covered per 90 minutes, in kilometres.',
  hsr_km_90: 'High-speed running per 90 minutes, in kilometres.',
  sprints: 'Sprints.',
  sprints_90: 'Sprints per 90 minutes.',
  top_speed: 'Fastest recorded speed this season, in km/h.',
  npxg_xa_90: 'Non-penalty xG plus xA per 90 minutes: total expected involvement in goals, penalties excluded.',
  ga_90: 'Goals plus assists per 90 minutes: the realised counterpart of npxG + xA.',
  finishing: 'Finishing: (non-penalty goals minus non-penalty xG) divided by non-penalty shots. Per shot, so volume does not dominate; positive means better than the chances deserved.',
  placement: 'Shot placement: (xGOT minus xG) divided by shots. How much a player\'s placement adds to the chance they had; xGOT only counts shots on target.',
  xa_per_kp: 'Expected assists per key pass: the average quality of the chances a player creates.',
  shot_creation_90: 'Shots plus key passes per 90 minutes: shot-ending and shot-creating volume together.',
  prog_actions_90: 'Progressive carries plus completed dribbles per 90 minutes: carrying the ball forward.',
  def_actions_90: 'Tackles + interceptions + blocks + clearances per 90 minutes: raw defensive volume.',
  padj_tkl_int_90: 'Possession-adjusted tackles + interceptions per 90: each match\'s (tackles + interceptions) is multiplied by 50 over the opponent\'s possession share (clamped to 25–75%, from the team sheet; matches without a sheet count unadjusted). A side without the ball has more to defend.',
  ball_wins_90: 'Tackles won + interceptions + recoveries per 90 minutes: regaining the ball.',
  duels_90: 'Duels contested per 90 minutes, the volume behind the duel success rate.',
  aerials_90: 'Aerial duels contested per 90 minutes, the volume behind the aerial success rate.',
  loss_per_100: 'Possession lost per 100 touches: ball security independent of how often the player is on the ball. Lower is better.',
  rating: 'Sofascore\'s match rating (roughly 6 to 9), averaged over the season with each match weighted by minutes played. It is the source\'s rating, not the site\'s.',
  yellow: 'Yellow cards. Lower is better.',
  red: 'Red cards. Lower is better.',
  minutes: 'Minutes played.',
  matches: 'Appearances (any minutes played).',
  starts: 'Matches started.'
};

var MODEL_TERMS = [
  ['dixon_coles', 'Dixon-Coles model', 'The match model: each team has an attack and a defence parameter, goals are Poisson with a correction for low scores, and any fixture yields a full score distribution. See the methodology, section 2.', 'Match model'],
  ['attack', 'Attack', 'A team\'s attack parameter in the Dixon-Coles fit. Expected goals scored are exp(attack + opponent defence [+ home advantage]); higher means more goals scored.', 'Match model'],
  ['defence', 'Defence', 'A team\'s defence parameter. Higher means more goals conceded, so a good defence has a low (negative) value.', 'Match model'],
  ['home_adv', 'Home advantage', 'One global term added to the home side\'s log expected goals; set to zero at a neutral venue. In Elo it is a fixed number of rating points (30 to 70 per league, 50 in cups and internationals).', 'Match model'],
  ['rho', 'Rho', 'The Dixon-Coles low-score correction: a negative rho makes 0-0 and 1-1 a little more likely, and 1-0 / 0-1 a little less, than independent Poissons would. Bounded in [-0.99, 0].', 'Match model'],
  ['xi', 'Time decay (xi)', 'How fast old matches lose weight in the fit: each match counts exp(-xi × days ago). At xi = 0.0035 a match is worth half after about 198 days.', 'Match model'],
  ['ridge', 'Ridge', 'A penalty on the squared attack and defence parameters that keeps small samples near average. Fixed in size, so as data ages it pulls harder.', 'Match model'],
  ['elo', 'Elo', 'A slow-moving rating updated after every match from win, draw or loss only (no margin of victory). Seeded from last season\'s table in leagues; flat at 1500 in cups.', 'Match model'],
  ['ensemble', 'Ensemble and DC weight', 'The blend of the Dixon-Coles and Elo probabilities. dc_weight is the Dixon-Coles share (1.0 everywhere since 21 October 2026; it was 0.65 to 1.0 in leagues); Elo enters at 0.30 when a team is unknown to the fit.', 'Match model'],
  ['calibration', 'Calibration', 'The draw rate and goals per match measured from the competition\'s own training matches. They shape the Elo side of the blend.', 'Match model'],
  ['o25', '3 or more goals', 'Our chance of three or more goals in the match: the sum of the score-matrix cells with home + away goals of at least 3.', 'Match model'],
  ['btts', 'Both teams to score', 'The sum of the score-matrix cells where both sides score at least once.', 'Match model'],
  ['pooled', 'Pooled scale', 'One Dixon-Coles fit over every league and every club cup, with clubs prefixed by their league, so that clubs from different leagues sit on one scale. Cup matches are the only bridges between leagues.', 'Match model'],
  ['scoring_factor', 'Scoring factor', 'The multiplier that puts a league\'s attacking rates on the pooled scale: exp(pool mean defence minus the league\'s mean defence). Below 1 means the league\'s defences are weaker than the pool\'s.', 'Players'],
  ['league_adjusted', 'League-adjusted rate', 'A per-90 attacking rate multiplied by its league\'s scoring factor, so players from different leagues can be compared. Only the twelve pooled leagues carry a factor.', 'Players'],
  ['percentile', 'Percentile', 'Where a value sits among the positional pool: the share of peers below it (ties count half). 100 is the best; for metrics where lower is better the scale is flipped, so red is always good.', 'Players'],
  ['pool', 'Positional pool', 'The players a percentile is measured against: goalkeepers, defenders, midfielders or forwards of the same competition (or of every competition, for global percentiles), with at least the minutes floor.', 'Players'],
  ['minutes_floor', 'Minutes floor', 'The minimum minutes for percentiles: max(90, min(270, 35% of the most-played player\'s minutes)) within a competition, 270 in the global pool.', 'Players'],
  ['shrinkage', 'Shrinkage', 'In the Player lab, a rate becomes (minutes × rate + 450 × group median) / (minutes + 450), so five matches move a player halfway from the median to their own figure.', 'Players'],
  ['monte_carlo', 'Monte Carlo simulation', 'The rest of the season played out tens of thousands of times (30,000 on the published site) by sampling every remaining match from the model\'s score matrix. Probabilities are the share of simulations in which something happened.', 'Simulation'],
  ['bands', 'Bands', 'The blocks of finishing positions that matter: title, continental places, playoffs, relegation. A band probability sums the position distribution over its positions.', 'Simulation'],
  ['exp_pts', 'Expected points', 'The mean final points total over the simulations. p05 and p95 are the 5th and 95th percentiles of the same distribution.', 'Simulation'],
  ['forced', 'Forced ties', 'Cup ties already decided on the pitch are taken as played in every simulation rather than re-drawn.', 'Simulation'],
  ['strength_ppg', 'Strength (expected PPG)', 'Expected points per game against an average opponent at a neutral venue: the mean of 3 × P(win) + P(draw) over every other team in the competition.', 'Power rankings'],
  ['rank_delta', 'Rank delta', 'Table position minus the model\'s strength rank. Positive means the club sits below where its strength says.', 'Power rankings'],
  ['xpts', 'Expected points (xPts)', 'Points a match deserved on xG: with the two xG totals as independent Poisson means, 3 × P(win) + P(draw). Summed over the season it is the basis of luck.', 'Power rankings'],
  ['luck', 'Luck', 'Actual points minus expected points from xG. Sustained luck is usually finishing variance, not a skill.', 'Power rankings'],
  ['sos', 'Strength of schedule', 'The mean strength of opponents already played (sos_played) and still to play (sos_remaining); the delta is remaining minus played.', 'Power rankings'],
  ['field_tilt', 'Field tilt', 'A team\'s share of the touches in both penalty areas: its box touches over its own plus the opponent\'s. Territory, not possession.', 'Teams'],
  ['ppda', 'PPDA', 'Passes allowed per defensive action: the opponent\'s passes divided by the team\'s tackles, interceptions and other defensive actions, over the whole pitch. Lower means a higher press.', 'Teams'],
  ['expected_result', 'Expected result', 'On a match page, every shot replayed 20,000 times as a coin flip at its xG, seeded by the match id. Rebounds count as separate chances.', 'Match centre'],
  ['devig', 'De-vig', 'Removing a market\'s margin: each implied probability divided by their sum, so the three outcomes add to one. Used only to show the market as a reference beside our chance.', 'Market reference'],
  ['consensus', 'Consensus', 'The median de-vigged probability across the sources that quote a fixture, renormalised: the market reference on match pages.', 'Market reference'],
  ['goals_added', 'Goals added (GA)', 'The site\'s player value, in goals of non-penalty expected goal difference: sixteen actions per match plus the match rating, each weighted by how well it predicted later matches, centred on each competition and moved by its strength on the pooled scale.', 'Player value'],
  ['gar', 'GAR/90 (goals above replacement per 90)', 'Goals added per 90 minutes minus the replacement level of the player\'s role. Projected GAR/90 shrinks it toward replacement by 900 minutes of evidence.', 'Player value'],
  ['par', 'PAR (points above replacement)', 'Goals above replacement turned into league points with the slope of expected points on goal difference at the league\'s scoring rate (about 0.65 to 0.75 points a goal).', 'Player value'],
  ['replacement_level', 'Replacement level', 'For each role, the value per 90 of the 20th-percentile regular (900+ minutes in the last 12 months) across every followed competition.', 'Player value'],
  ['role', 'Role', 'GK, CB, FB, DM, CM, AM, W or ST, read from the starting formation (Sofascore lists each line right to left); where a player starts most, else Sofascore\'s defender, midfielder or forward.', 'Player value'],
  ['unit_grade', 'Unit grade', 'A club unit graded against its league on the projected value of the current players used there this season: A is the top fifth, E the bottom fifth.', 'Player value'],
  ['fair_value_index', 'Fair value index (FVI)', 'Expected points above replacement over four seasons at 2,500 minutes a season, discounted 15% a year, with ageing and career length; 100 is the median top-five-league regular. An index, not euros.', 'Player value'],
  ['sensitivity_curve', 'Sensitivity curve', 'A club\'s season numbers re-simulated at several shifts of its strength; the transfer simulator interpolates them.', 'Player value'],
  ['value_v2', 'Value (valuation v2)', 'Expected points above replacement over the next four seasons, discounted 15% a year: the projected GAR/90 drawn from its uncertainty, moved each year by the ageing curve, times the minutes the player\'s availability promises, times the chance the player is still a regular; with a 10-90% band from 400 draws.', 'Transfers'],
  ['availability', 'Availability', 'The share of the club minutes a player played in the last 12 months (each club counted from the first to the last appearance there, the current club up to today), shrunk toward 50% by eight matches.', 'Transfers'],
  ['fair_fee', 'Fair fee', 'What a club would pay, in euros, from a model fitted on real transfer fees (Sofascore\'s): the player\'s value at the time, age, position, minutes and both clubs\' strength. Shown to a club like the player\'s own, or to the buyer in the simulator, with the middle half of similar deals.', 'Transfers'],
  ['deal_grade', 'Deal grade', 'For each club in a move of the last 12 months: the fee against the fair fee at the time, then the value the player has delivered since, weighted in as the minutes come in. A is the best fifth of the year\'s deals, E the worst.', 'Transfers'],
  ['transfer_budget', 'Transfer budget', 'A club\'s likely gross spend in a window, from a model fitted across the followed clubs on the latest summer window: its previous window\'s spending and sales, its league\'s and its own strength (and its squad\'s market value once enough squads are valued); a 25-75% range.', 'Transfers'],
  ['market_value', 'Market value', 'Sofascore\'s proposed market value for a player, from the current squads, shown for reference beside our fair fee.', 'Transfers'],
  ['fantasy_points', 'Fantasy points', 'FPL\'s 2025/26 scoring applied by us to Sofascore\'s match data, with the bonus replaced by 3/2/1 for the three best Sofascore ratings in the match.', 'Fantasy'],
  ['fantasy_price', 'Fantasy cost', 'Our own cost proxy: a player\'s expected points above replacement next season, ranked within league and position and mapped onto FPL-like ranges. FPL\'s official figures and ownership are not used.', 'Fantasy'],
  ['fdr', 'Fixture difficulty', 'A club\'s upcoming fixtures rated 1 (easiest fifth) to 5 by the match model\'s expected goals for (attackers) or against (defenders).', 'Fantasy'],
  ['underlying_points', 'Underlying points', 'The fantasy points a player\'s numbers were worth: goals and assists at xG and xA, clean sheets and goals conceded at the opponent\'s expected goals while the player was on. Actual minus underlying is luck.', 'Fantasy']
];

function G(key, text) { return '<a class="fb-md-gl" href="#/model/glossary/' + esc(key) + '">' + (text === undefined ? esc(key) : text) + '</a>'; }
function formula(text) { return '<pre class="fb-md-formula">' + esc(text) + '</pre>'; }
function note(html, warn) { return '<div class="qk-note fb-md-note' + (warn ? ' warn' : '') + '"><span>' + html + '</span></div>'; }
function simpleTable(cols, rows) {
  return '<div class="qk-table-wrap fb-md-tbl"><table class="qk-table dense"><thead><tr>' + cols.map(function (c) { return '<th scope="col">' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
    rows.map(function (r) { return '<tr>' + r.map(function (x) { return '<td>' + x + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
}
/* The 22 September 2026 tuner run, per league: [name, slug, method, xi, ridge, Elo HA, K, dc_weight, log-loss, baseline]. */
var TUNED = [
  ['Premier League', 'premier-league', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '1.051', '1.099'], ['LaLiga', 'la-liga', 'global', '0.002', '2.0', '50', '30', '1.0', '0.992', '1.044'],
  ['Serie A', 'serie-a', 'per-league', '0.001', '1.0', '30', '15', '0.65', '0.970', '1.079'], ['Bundesliga', 'bundesliga', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '0.987', '1.079'],
  ['Ligue 1', 'ligue-1', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '1.031', '1.099'], ['Eredivisie', 'eredivisie', 'per-league', '0.001', '0.25', '30', '15', '1.0', '0.997', '1.087'],
  ['Liga Portugal', 'primeira-liga', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '0.952', '1.097'], ['Brasileirão', 'brasileirao', 'global', '0.002', '2.0', '50', '30', '1.0', '1.014', '1.054'],
  ['MLS', 'mls', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '1.054', '1.067'], ['Saudi Pro League', 'saudi-pro-league', 'pooled', '0.0035', '1.0', '50', '30', '1.0', '0.942', '1.080'],
  ['Liga Argentina', 'liga-argentina', 'per-league', '0.008', '2.0', '70', '30', '0.8', '1.065', '1.081'], ['Liga MX', 'liga-mx', 'per-league', '0.005', '2.0', '50', '15', '0.8', '1.048', '1.069'],
  ['Belgian Pro League', 'belgian-pro-league', 'per-league', '0.001', '0.25', '30', '20', '0.8', '0.969', '1.066']
];
/* The tuner table: "in use now" from each league's meta.json model block (metas: slug -> meta, or null while loading),
   then the 22 September run's choice and its log-loss. A league whose meta.json is missing shows a dash, never the old value. */
function tunerTable(metas) {
  var cur = function (slug, k, d) {
    if (!metas) return '…';
    var m = ((metas[slug] || {}).model) || {};
    return isNum(m[k]) ? Number(m[k]).toFixed(d === undefined ? 1 : d).replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '.0') : '—';
  };
  return simpleTable(['League', 'Fit', 'xi now', 'ridge now', 'dc_weight now', 'Elo HA', 'K', 'Tuned 22 Sep: xi / ridge / dc_weight', 'log-loss', 'baseline'], TUNED.map(function (r) {
    var m = metas ? (((metas[r[1]] || {}).model) || {}) : {};
    return [esc(r[0]), esc(m.params_method || r[2]), cur(r[1], 'dc_xi', 4), cur(r[1], 'dc_ridge', 2), cur(r[1], 'dc_weight', 2),
      metas && isNum(m.elo_home_advantage) ? String(Math.round(m.elo_home_advantage)) : esc(r[5]), metas && isNum(m.elo_k_league) ? String(m.elo_k_league) : esc(r[6]),
      esc(r[3] + ' / ' + r[4] + ' / ' + r[7]), esc(r[8]), esc(r[9])];
  }));
}
/* Fill the live parts of the methodology: the tuner table and the international rho. */
function fillLive(el) {
  var slugs = TUNED.map(function (r) { return r[1]; }).filter(function (sl) { return FB.comp(sl); });
  Promise.all(slugs.map(function (sl) { return FB.compFile(sl, 'meta'); })).then(function (list) {
    if (!FB.alive(el)) return;
    var metas = {};
    slugs.forEach(function (sl, i) { metas[sl] = list[i] || {}; });
    var box = el.querySelector('#md-tuner');
    if (box) box.innerHTML = tunerTable(metas);
  });
  FB.load('nations.json').then(function (n) {
    var r = (((n || {}).model) || {}).rho, sp = el.querySelector('#md-rho');
    if (!sp || !FB.alive(el)) return;
    sp.textContent = isNum(r) ? (r < 0 ? '−' : '') + Math.abs(r).toFixed(3) : 'a value near −0.04';
  });
}
function kv(rows) { return simpleTable(['Setting', 'Value', 'Where it applies'], rows.map(function (r) { return [esc(r[0]), r[1], esc(r[2] || '')]; })); }

// ── methodology: the document (text ported from the previous site) ─────────

function sections() {
  var S = [];

  S.push({ id: 'data', title: 'Data', html: `
<h5>Source</h5>
<p>Almost everything on the site comes from <strong>Sofascore's unofficial JSON API</strong>. It is unofficial: there is no licence, no documentation and no guarantee, and Sofascore blocks datacenter addresses outright, so nothing can be fetched from the cloud. Fetching runs only on the owner's home connection through a scheduled task, and the site is built and deployed from the same machine. The client presents a browser TLS fingerprint and tries two hosts in order (<code>api.sofascore.com</code>, then <code>api.sofavpn.com</code>); a call that fails on both returns nothing rather than raising.</p>
<h5>What a match record holds</h5>
<p>The fixture list of a season costs two unbudgeted calls (past and future pages). Each match is stored with its Sofascore id, both club names canonicalised through a per-league name registry (so "Liverpool FC" in the Champions League is the same club as "Liverpool" in the league store), the round (a number, or a knockout key such as <code>r16</code>, <code>qf</code>, <code>sf</code>, <code>final</code>, <code>po</code>, <code>r32</code>), the status, the score, the kickoff in UTC, the stage (<code>league</code>, <code>playoff</code>, <code>qualifying</code>, <code>split</code>, <code>other</code>), the group, the penalty-shootout winner where a drawn tie was settled, the aggregate winner on a second leg, and the team ids and countries that link a cup entrant back to its league.</p>
<p>A finished match can then be given <strong>detail</strong>, which costs five budgeted calls: the line-ups with 72 kept statistics per player (minutes, scoring and creation, passing and carrying, defending and duels, goalkeeping, physical output and Sofascore's rating; unused substitutes are dropped), the team-statistics sheet (whole-match values such as possession, expected goals, shots, passes, box touches, with denominators kept for ratio rows), the shot map (each shot's position as a distance from the goal line and a position across the pitch, its xG and xGOT, type, body part, situation, minute, goal-mouth coordinates and the goalkeeper faced), the momentum graph and the incident list (goals, cards, substitutions, VAR). A match "counts" as detailed only when its line-ups arrived with at least one player's statistics.</p>
<h5>The hourly refresh</h5>
<p>One scheduled task runs every hour on the owner's machine, in this order: the Argentine league (budget 100 detail calls), discovery of up to six competitions not yet mapped to Sofascore ids, every other league, cup and national-team competition in one process (budget 150), and the archive of past seasons and player careers (budget 60). It commits the stores once and pushes. The same machine then runs the build (about three quarters of an hour for all competitions) and syncs <code>docs/site/</code> to the public repository. The build writes JSON only; the pages you are reading are static files that fetch that JSON.</p>
<h5>Budgets and pacing</h5>
<p>Detail is charged at five calls per match, so the default budget of 150 covers thirty matches an hour, taken round-robin across every competition that has matches waiting, newest first. Fixture pages, probes and discovery are not charged. The fetcher pauses half a second between fixture pages, a quarter of a second after each detail call and a second between matches, and stops at the first HTTP 403 or after three consecutive matches without line-ups. A competition whose store has no match within seven days either side of today, and whose fixtures were refreshed within the last day, is <strong>dormant</strong> and skipped, which keeps the hourly call count down through the off-season.</p>
<h5>The 403 challenge</h5>
<p>Sofascore answers HTTP 403 to every endpoint from an address it has decided to challenge. It is triggered by bursts (once after about 3,000 calls in one sitting; once, on 29 September 2026, after fewer than a thousand in an hour when a manual backfill and the hourly task overlapped), it lasts on the order of thirteen hours, and every call made while challenged is wasted and may prolong it. Every fetcher therefore probes with a single call before doing anything, exits when blocked, and never runs a backfill on top of the hourly task. When a refresh fails the site simply keeps serving the last good data; a competition whose store is more than 24 hours old shows a "could not be refreshed" banner, and one whose most recent match is more than 30 days old (60 for cups, 120 for national teams) is flagged as possibly out of season.</p>
<h5>The calendar backfill</h5>
<p>Behind the current season's needs, the fetcher also queues last season's finished matches dated within the past 365 days that have no detail, newest first, under the same hourly budget. That detail feeds the Player lab's "last 12 months" and "calendar year so far" views, where a player five matches into a new league season is compared on the same stretch of calendar as one twenty matches in. As of 30 September 2026 that is roughly 4,000 matches, about 20,000 calls, so the window fills over about a week once the address is clear. Season pages never count that detail: every season aggregate is built from the store restricted to the current season's matches.</p>
<h5>What exists for older matches, and what does not</h5>
<ul>
<li><strong>Previous season</strong>: fixtures, results and dates only. They train the match model as goals rows (section 2); they carry no xG, no line-ups and no player statistics.</li>
<li><strong>Thin detail</strong>: matches fetched by the older fetchers have line-ups with a short statistic list (roughly twelve to twenty-six keys) and no team sheet, so they contribute xG and basic player lines but no possession, field tilt, PPDA, xGOT-against or physical data. The hourly task upgrades a few such matches per run to the full format, newest first.</li>
<li><strong>Followed-only detail</strong>: national cups, super cups and the Leagues Cup fetch detail only for matches in which at least one side is a club of a followed league, so a tie between two lower-division clubs has a result and nothing else.</li>
<li><strong>The match centre degrades per section</strong>: a match with no shard shows the header and the model line; one in the thin format shows the shot map and xG race but not the team sheet, formations or goal-mouth views.</li>
<li><strong>Names</strong>: a spelling the registry does not know is kept as Sofascore spells it, which can leave a club out of a join (the table, a cup entrant's league) until an alias is added. Crests are fetched by hand and committed; a missing crest shows as a monogram.</li>
</ul>
<p>The archive (past season tables, season leaders and player careers) fills at 60 calls an hour. It feeds the season picker's older editions (official final tables and leaders, no match list) and the season-by-season rows on each player's page that predate the match stores.</p>` });

  S.push({ id: 'match-model', title: 'The match model', html: `
<p>Every probability on the site starts from a ${G('dixon_coles', 'Dixon-Coles')} model blended with an ${G('elo', 'Elo')} rating. The Dixon-Coles fit gives each team an attack and a defence parameter and returns a full score distribution for any fixture; Elo is a slow-moving prior and a fallback; the blend is calibrated to each competition's own draw rate and scoring.</p>
<h5>Dixon-Coles: parameterisation</h5>
${formula('lam_home = exp(att[home] + def[away] + home_adv)\nlam_away = exp(att[away] + def[home])')}
<p>A higher ${G('attack')} means more goals scored; a higher ${G('defence')} means more goals conceded, so a good defence has a negative value. ${G('home_adv', 'Home advantage')} is one global term, set to zero when a fixture is played at a neutral venue. The parameter vector holds every team's attack and defence plus home advantage and rho (2n + 2 entries); teams are sorted alphabetically and the first team's defence is fixed at 0 as the anchor. The fit has no neutral-venue term: a neutral match trains home advantage as if the listed home side were at home, and neutrality is honoured only at prediction time and in the Elo replay.</p>
<h5>Likelihood, time decay and ridge</h5>
<p>Each training match gets a weight that decays with age, with an optional per-row weight (friendlies count half in the international fit):</p>
${formula('w_i = exp(−xi × days_ago_i) × weight_i')}
<p><strong>Goals rows</strong> (matches without xG on both sides) use the Dixon-Coles likelihood: independent Poissons with the low-score correction tau, whose strength is ${G('rho')}:</p>
${formula('ll_i = log Pois(hg; lam_h) + log Pois(ag; lam_a) + log tau\n\ntau(0,0) = 1 − lam_h × lam_a × rho     tau(1,0) = 1 + lam_a × rho\ntau(0,1) = 1 + lam_h × rho             tau(1,1) = 1 − rho\ntau(x,y) = 1 otherwise')}
<p><strong>xG rows</strong> (current-season matches with line-ups, where team xG is the sum of the players' Sofascore expected goals) replace the goals entirely with a continuous Poisson likelihood on the two xG totals, with no tau:</p>
${formula('ll_i = hx × log(lam_h) − lam_h − lgamma(hx + 1) + ax × log(lam_a) − lam_a − lgamma(ax + 1)')}
<p>This is a substitution, not a blend: a match with xG contributes only its xG, a match without contributes only its goals, and club xG is used raw (Sofascore's sums, not rescaled to goals). Because rho appears only in goals rows, it is identified only by matches without xG, and almost every club match in the stores has xG. So club fits hold rho fixed at one value (−0.045), estimated by maximum likelihood on the goals of 132,114 matches in 35 leagues, 2014–2025. The national-team fit, whose earlier editions carry no xG (about 3,500 goals-only matches), fits its own: <span id="md-rho">a value near −0.04</span> in the current fit (a profile-likelihood scan of its goals-only matches peaked at −0.061, with a 95% interval of −0.11 to −0.02 that contains the club value); a fit with fewer than 300 goals-only matches holds the club value instead. The objective adds a ${G('ridge')} penalty on the team parameters, not on home advantage or rho:</p>
${formula('minimise   −Σ w_i × ll_i  +  ridge × (Σ att² + Σ def²)')}
<p>The ridge is not scaled by the number of matches. As the data ages every weight shrinks by the same factor while the ridge stays fixed, so the effective regularisation strengthens with wall-clock time and parameters drift very slowly towards zero even with no new matches (about 3 × 10⁻⁵ on a home-win probability per day). The fit is <code>scipy</code>'s L-BFGS-B with numerical gradients, starting from all team parameters at 0, home advantage 0.1 and rho −0.1; rho is bounded in [−0.99, 0]. A fit needs at least 50 matches (30 for the international fit).</p>
<h5>Closing-line rows</h5>
<p>The league fits also learn from bookmakers' closing lines, as one more source of information about past matches: the eleven leagues with a football-data.co.uk file (every league here but the Saudi Pro League, in the pooled fit or their own) and Argentina. For every finished league match that football-data.co.uk lists with a closing line, the closing home/draw/away and 2.5-goal lines are turned into the pair of goal rates that reproduces them under a Dixon-Coles score model, and that pair enters the fit as one extra continuous-Poisson row, beside the match's own goals or xG row. The lines are Pinnacle's where the files have them (to January 2026), then the Betfair exchange close, then the bookmakers' average. Only the lines of matches already played enter a fit, never those of the match being forecast. Since 21 October 2026 each such row weighs 96 and decays with its own half-life of 23 days:</p>
${formula('w_market = 96 × exp(−0.03 × days_ago)      w_goals = exp(−xi × days_ago)')}
<p>So the team ratings mostly follow the last few weeks of closing lines, and goals and xG move them at the margin. In a walk-forward test on the 2019/20 to 2026/27 seasons (settings chosen on 2014 to 2018), this cut the log-loss of those twelve leagues' home/draw/away lines by 0.0075 (95% CI 0.0064 to 0.0087) against the October 2 version (weight 3, no own decay), and the gap to Pinnacle's pre-match snapshot fell from 0.014 to 0.005. Our forecast still trails both the snapshot and the closing line: it can only learn what past lines said, and it knows nothing about team news. The Saudi Pro League, the cups and the national teams have no such lines and are fitted on goals and xG alone (cup clubs from the twelve leagues carry their league ratings through the pooled fit).</p>
<h5>Line-ups (since 22 October 2026)</h5>
<p>Clubs announce their starting XIs about an hour before kick-off. For a league match, the hourly fetch asks Sofascore for the line-ups of every match starting within the next 100 minutes (one call each, inside the same call budget) until Sofascore marks them confirmed; the time they were read is kept. Each XI is then valued with the player-value model described under “Player value and transfers” (every player's box score and rating per 90 from earlier matches only) and compared with the club's usual XI, the average of its last ten line-ups valued the same way on the same day, so a player's form does not count, only who plays:</p>
${formula('delta_side = value(today\'s XI) − mean value(the last 10 XIs)      goals of expected goal difference a match\nd = delta_home − delta_away;   t = 0.75 × d / (lam_h + lam_a)\nlam_h → lam_h × e^t,   lam_a → lam_a × e^−t')}
<p>The 0.75 and the ten line-ups were chosen on 2025 matches, then tested once on 3,230 league matches from 1 January to 20 October 2026, a test registered before it was run: the line-ups cut the home/draw/away log-loss by 0.0034 (95% CI 0.0008 to 0.0063) and improved calibration, and the distance to the closing line, which already knows the line-ups, fell from 0.010 to 0.007. Our forecast still trails the close. The term needs both clubs to have five earlier line-ups in the stores; otherwise the XIs are shown without changing the line. It applies to the league matches (the twelve leagues and Argentina's; not the cups or national teams, where it was not tested), and the line is adjusted only when a build runs after the XIs are read, so near kick-off the page can still show the line without them.</p>
<h5>Prediction</h5>
<p>For any pairing the model builds a 9 × 9 matrix of <code>Pois(i; lam_h) × Pois(j; lam_a) × tau(i, j)</code> (goals 0 to 8 each way), clamps negative cells to zero and renormalises, which discards the mass above eight goals. Home win, draw and away win are the lower triangle, the trace and the upper triangle. A team missing from the fit gets attack = defence = 0, the centre of the ridge prior. Negative "scores" that Sofascore uses for voided or awarded matches are dropped before fitting, and a non-finite likelihood aborts the fit rather than silently freezing every club at average.</p>
<h5>Parameters</h5>
${kv([
  ['Time decay (xi)', '0.0035 in every league since 21 October 2026 (the pooled set; class default 0.0018); own-fit cups 0.0035; international 0.002', 'half-life ln 2 / xi: about 198 days at 0.0035'],
  ['Ridge', '1.0 in every league since 21 October 2026; pooled 1.0; cups 1.0; international 1.0', ''],
  ['Closing-line rows', 'weight 96, own decay 0.03 a day (half-life 23 days)', 'every league but the Saudi Pro League, and Argentina'],
  ['Maximum goals', '8', 'every competition'],
  ['Rho bounds', '[−0.99, 0]', 'fixed'],
  ['Minimum matches to fit', '50 (leagues, cups, Argentina, the pool); 30 (international)', 'below it the ensemble is Elo only']
])}
<h5>Elo</h5>
${formula('dr  = R_home − R_away + (home_advantage if not neutral else 0)\nE_h = 1 / (1 + 10^(−dr / 400))\nS_h = 1 (win), 0.5 (draw), 0 (loss)\nR_home += K × (S_h − E_h);   R_away += K × ((1 − S_h) − (1 − E_h))')}
<p>Goal difference is ignored: only the result enters, with no margin-of-victory multiplier, and the update uses the same home-advantage-adjusted expectation the model predicts, so home wins are not over-rewarded. Leagues seed each club at <code>1500 + (n_teams − last season's rank) × 15</code>, with promoted clubs at the bottom, then replay every training match. K comes from each league's tuned parameters (15, 20 or 30; the pooled set uses 30, the class default is 20) and home advantage from the same file (30 to 70 points). Cups use K 20 and 50 points but <strong>never seed or update</strong>, so every club sits at 1500 and the Elo column of a cup's power rankings is flat; the international fit uses K 20 and 50 points, unseeded, replaying every national-team match (friendlies at full weight here, unlike in the Dixon-Coles fit).</p>
<h5>The ensemble and dc_weight</h5>
<p>The ${G('ensemble', 'blend')} weight adapts to what is known about the two teams:</p>
${formula('dc_w = 0                            if Dixon-Coles is unfitted, or |rho| ≥ 0.99\n     = max(dc_weight − 0.30, 0.40)  if either team has no attack parameter\n     = dc_weight                    otherwise\nelo_w = 1 − dc_w')}
<p>On the Elo side the logistic expectation is read as the home-win probability and the rest of the mass is split with the competition's measured draw rate; an Elo score matrix comes from independent Poissons with means <code>max(p_E × lam_scale, 0.3)</code> and <code>max((1 − p_E) × lam_scale, 0.3)</code>. The blend is linear and renormalised:</p>
${formula('H = dc_w × H_DC + elo_w × elo_home   (likewise D and A)\nscore_matrix = normalise(dc_w × M_DC + elo_w × M_Elo)\nlambda_home / lambda_away = the Dixon-Coles lambdas')}
<p>Tuned dc_weight is 0.65 to 1.0 in the leagues and 1.0 in every cup and the international fit; with 1.0 Elo enters only when a club is unknown to the fit, at weight 0.30, and in a cup that Elo is a pure home-advantage prior (p_E = 0.571 for the home side). One inconsistency to know about: on a blended fixture the win/draw/loss triple (a linear blend using Elo's draw-rate split) and the triple implied by the blended score matrix (which uses Elo's Poisson matrix) can differ by a few points. The simulators sample from the matrix; the fixture line, the ladder and the strength table read the triple.</p>
<h5>Calibration</h5>
<p>Measured from each model's own training matches: the ${G('calibration', 'draw rate')} is the share of level scores, <code>mean_goals</code> is the average of the mean home and mean away goals, and <code>lam_scale = 2 × mean_goals</code>. The home-win rate is reported on the competition's methodology card but not used. A competition with fewer than 30 training rows takes the defaults (draw rate 0.25, scale 2.6, 1.3 goals per team, 45% home wins). The away penalty on the Elo side is 1.0 everywhere on this site (the legacy World Cup site used 0.75).</p>
<h5>Our forecast for a fixture</h5>
<p>Every unplayed fixture carries our forecast. <strong>h, d, a</strong> are the ensemble's home, draw and away chances; <strong>lh, la</strong> the Dixon-Coles expected goals; ${G('o25', '3 or more goals')} is the sum of matrix cells with i + j ≥ 3; ${G('btts', 'both to score')} the sum of cells with i ≥ 1 and j ≥ 1; the most likely score is the largest cell. A fixture is played as neutral when the store flags it or the competition's rules say so (cup finals and neutral rounds, and the national-team tournaments played at neutral venues).</p>
<h5>How the parameters were chosen</h5>
<p>A tuner scores each league by walk-forward three-way log-loss on its own matches (expanding folds: 200 matches minimum, six folds), in three stages: Dixon-Coles alone over xi × ridge, Elo alone over home advantage × K, then the blend weight. Four candidates compete: the league's own best, one global set minimising the match-weighted loss across leagues, a pooled fit over all leagues, and the defaults. The global set is the reference; the pooled, then the per-league, candidate replaces it only by beating it by 0.002 of log-loss, and the winner must also beat the better of two baselines, uniform (ln 3 = 1.0986) and a home-advantage-only prior. The table shows the settings each league uses now, read from its latest build, beside what the tuner chose on 22 September 2026 and that run's log-loss. <strong>Since 21 October 2026</strong> every league fitted on its own uses xi 0.0035, ridge 1.0 and dc_weight 1.0 instead (the Elo, K and home-advantage columns are unchanged): once the closing-line rows carry most of the weight, the long decays, the heavier ridges and the Elo share of the old table lost log-loss in a walk-forward test on 2014 to 2018 football-data seasons, and the tuner's own folds do not see those rows.</p>
<div id="md-tuner">${tunerTable(null)}</div>
<p>A league whose method is "pooled" reads the build's pooled fit (section 3) through a view that strips the league prefixes; if that fit is unavailable it falls back to its own fit with the same parameters. Note that the tuner's pooled candidate contained leagues only, while the deployed pool includes the cups.</p>` });

  S.push({ id: 'pooled', title: 'The pooled scale', html: `
<p>Three things need clubs from different leagues on one scale: the Clubs across leagues page, every club cup (whose entrants come from many leagues), and the scoring factors that put players from different leagues on one footing. They come from one ${G('pooled', 'pooled Dixon-Coles fit')}.</p>
<h5>Club prefixes and cups as bridges</h5>
<p>The training frame takes every followed league except Argentina, with each club renamed <code>&lt;league-slug&gt;:&lt;club&gt;</code>, plus every cup store whose family is not national teams. A cup entrant is renamed to its league's prefix when its country maps to a followed league and the club appears in that league's frame; otherwise it keeps the cup's own prefix, <code>&lt;cup-slug&gt;:&lt;club&gt;</code>. Cup matches between clubs of different leagues are therefore the <strong>only edges connecting the leagues' parameter blocks</strong>; without them the leagues would be separate components identified only by the ridge. The fit uses xi 0.0035 and ridge 1.0, needs at least 50 rows, covers roughly 530 clubs with about 1,060 parameters, and is the slowest step of the build.</p>
<p>Two consequences of the prefixing: a club from a league the site does not follow exists once per cup it plays in, with no shared parameters (an Argentine club can be both <code>libertadores:X</code> and <code>copa-argentina:X</code>); and Argentina, whose own model is fitted separately, always carries cup prefixes in the pool.</p>
<h5>Clubs outside the followed leagues (since 22 October 2026)</h5>
<p>The ridge shrinks every club toward attack and defence of zero, which is about an average top-flight club. A lower-division side that met only other lower-division sides in a national cup was therefore rated by the ridge rather than by its results, and some ranked among the ten strongest clubs in the world. Clubs under a cup's prefix now belong to a tier: domestic (national cups and super cups) or continental (continental club cups). Each tier has its own attack and defence offsets, fitted from its matches against league clubs, and its clubs are shrunk toward them; a club with no rated match takes its tier's level. In a walk-forward test on 1,569 cup matches (December 2025 to October 2026) this cut the home/draw/away log-loss by 0.029 (95% CI 0.012 to 0.046). Calibration error rose by 0.0012, a little over the tolerance set in advance and well within noise; the change was adopted on that basis. Since the same day, clubs from the English, German, Italian, Spanish and French lower divisions (levels two to five, from football-data.co.uk's division files) have a tier per level, so a League Two side is no longer rated like an amateur one; Portuguese, Dutch and Belgian second-tier clubs, which have no such file, stay in the amateur tier.</p>
<h5>Reading the pool back</h5>
${formula('att_bar, def_bar = mean attack / defence over clubs under a league prefix\n\nfor each club c (neutral venue, against the average club):\n  M          = score matrix(att_c, def_c, att_bar, def_bar, rho, home_adv = 0)\n  strength   = 3 × P(win) + P(draw)          expected points per game v the pool-average club\n  xg_for     = exp(att_c + def_bar)\n  xg_against = exp(att_bar + def_c)\n\nfor each league L (means over its clubs):\n  factor_att = exp(def_bar − mean_def_L)     scoring-rate multiplier for players (< 1: weaker defences)\n  factor_def = exp(att_bar − mean_att_L)\n  strength   = mean club strength; leagues ranked by it\n  connection = cup-match appearances by L\'s clubs')}
<p>The pool's own home advantage and rho are shown on the Clubs page and used by the in-browser forecast ("If they met" and the compare page), which rebuilds the score matrix from two clubs' attack and defence exactly as above, with home advantage applied or not according to the venue toggle.</p>
<h5>Why cross-block ranks are weak</h5>
<p>Each league and continental cup belongs to a block: Europe, South America, North America, Asia, Africa or World (the Club World Cup and the Intercontinental Cup). Within Europe the UEFA competitions connect the leagues every week. Between blocks the fit has only a handful of matches, time-decayed (on 29 September 2026: Asia–World 3, North America–South America 1, South America–World 1, Europe–South America 1, six in all). The ridge pulls every block towards the same centre, so a cross-block league ranking mostly reflects each block's internal spread and the prior, not measured strength. The <code>connection</code> count also overstates bridging, because domestic cups mostly link a league to itself or to lower-division clubs. Treat cross-block rankings, the scoring factors that depend on them, and any club-versus-club chance across blocks as our best guess with wide error; the Clubs page prints the bridge counts for this reason.</p>
<h5>Scoring factors and league-adjusted rates</h5>
<p>For the global leaderboards and the Player lab, every qualified player's attacking rates per 90 (goals, non-penalty goals, assists, xG, npxG, xA, xGOT, shots, key passes and big chances; the lab adds npxG + xA, goals + assists and shots + key passes) are multiplied by the competition's <code>factor_att</code> into a ${G('league_adjusted', 'league-adjusted')} twin. Only the twelve pooled leagues have a factor; cups, national-team competitions and Argentina get 1.0, which is no adjustment. Percentiles are then recomputed over the whole pool of qualified players by position, with a global minutes floor of 270. In a calendar window a player who played in several competitions carries the minutes-weighted blend of their factors.</p>` });

  S.push({ id: 'national-teams', title: 'National teams', html: `
<p>National teams are fitted separately from the club pool, on every national-team store the site follows: the World Cup, the Euro, Copa América, the Nations Leagues, the qualifiers, AFCON, the Asian Cup, the Gold Cup and the friendlies.</p>
<ul>
<li><strong>Friendlies at half weight.</strong> Rows from the friendlies competition carry <code>weight = 0.5</code> in the Dixon-Coles likelihood; everything else counts 1.0. (The Elo replay counts friendlies in full.)</li>
<li><strong>Neutral venues.</strong> Tournaments played on neutral ground (World Cup, Euro, Copa América, AFCON, Asian Cup, Gold Cup) mark every match neutral. The fit itself drops that column, so one home-advantage term serves qualifiers and neutral finals alike; neutrality is honoured when a fixture is forecast and in the Elo replay.</li>
<li><strong>Parameters.</strong> Dixon-Coles with xi 0.002 and ridge 1.0 on at least 30 matches; Elo with K 20 and 50 points of home advantage, unseeded; ensemble with dc_weight 1.0 and the fit's own draw rate and scale.</li>
<li><strong>Not simulated.</strong> National-team competitions publish their tables and knockout ladders as played, and each fixture carries the fit's line; there is no season simulation, no probabilities tab and no history. The banner on those pages says so.</li>
<li><strong>Ratings.</strong> The National teams page ranks every nation by strength: 3 × P(win) + P(draw) against the mean nation (mean attack and mean defence over all fitted nations) at a neutral venue, alongside attack, defence, Elo and matches played.</li>
</ul>
${note('The fit is wide but shallow. On 2 October 2026 it rests on about 4,000 matches for 234 nations, a median of 33 per nation, with 25 nations on fewer than five. National teams play few competitive matches a year and rarely meet across confederations, so ranks between confederations lean on the ridge prior and on a handful of World Cup and intercontinental play-off meetings.', true)}` });

  S.push({ id: 'simulations', title: 'Simulations', html: `
<p>Every season probability is a ${G('monte_carlo', 'Monte Carlo')} estimate: the remainder of the season is played out many times by sampling each remaining match from the model's score matrix, and a probability is the share of simulations in which the thing happened.</p>
<h5>Sampling</h5>
<p>A sampler caches one flattened score distribution per (home, away, neutral) pairing, so the model is called once per pairing however many simulations run; a draw is a binary search into that distribution. A degenerate matrix (no mass, or non-finite) falls back to independent Poissons with mean 1.2. The published site runs <strong>30,000 simulations</strong> per competition, in chunks of 25,000 with random seed 42 (the count is on each competition's meta line; the build's default is 100,000 and its <code>--sims</code> flag sets it). The Monte Carlo standard error on a probability is at most sqrt(0.25 / 30,000), about 0.003. Points quantiles (<code>p05</code>, <code>p50</code>, <code>p95</code>) are taken from the first 2,000 simulations only.</p>
<h5>Leagues</h5>
<ol>
<li>Points, goals for and against and wins are seeded from finished matches.</li>
<li>Every remaining non-playoff fixture is sampled for all simulations at once.</li>
<li>Each simulated table is ranked on the competition's tiebreak: points, goal difference, goals scored by default; points, wins, goal difference, goals scored in the Brasileirão and MLS; then a uniform random jitter as the drawing of lots, which avoids an alphabetical bias.</li>
</ol>
<p><strong>Head-to-head is not simulated.</strong> LaLiga and Serie A break level points on head-to-head record; the simulator cannot vectorise that and uses goal difference and goals scored instead, which matters only for clubs finishing exactly level. The outputs are the ${G('bands', 'position distribution')} (the finishing-position heatmap), the title probability, ${G('exp_pts', 'expected points')} and quantiles, band probabilities (each band sums the position distribution over its places; MLS bands read the conference table and Belgium's the post-split table), and each team's mean remaining goals, which feed the top-scorer model.</p>
<h5>Split seasons (Belgium)</h5>
<p>After the regular season each simulation splits its own table into a championship group of 6, a Europe group of 6 and a relegation group of 6. Carried points are <code>ceil(points / 2)</code>; goal difference and goals carry over unhalved. Each group plays a double round-robin sampled per simulation and is ranked on (points, goal difference, goals, lots). The champion is first in the championship group and the bands read the post-split order. The split is always simulated from the full regular-season table; a split already under way is not recognised.</p>
<h5>Playoffs, two-legged ties, extra time and penalties</h5>
<p>A single-leg tie hosted by one side is resolved from the match matrix with the draw split between extra time, weighted by strength, and a shootout that is a coin flip:</p>
${formula('P(home advances) = H + D × (etw × H / (H + A) + (1 − etw) × 0.5)        etw = 0.5')}
<p>A neutral single leg (cup finals, neutral rounds, the Argentine final) symmetrises the venue: <code>p = 0.5 × (A1[h, a] + 1 − A1[a, h])</code>. A two-legged tie convolves the goal-difference distributions of the two legs (the second leg's host reversed) to get the aggregate; there is no away-goals rule, and a level aggregate is split exactly as a single-leg draw.</p>
<ul>
<li><strong>MLS Cup playoffs</strong>, per conference: seeds 1–7 qualify directly; 8 hosts 9 in a single wildcard match; Round One is best-of-three (1 v wildcard winner, 2 v 7, 3 v 6, 4 v 5) with the higher seed hosting games one and three, <code>P(series) = p_h p_a + p_h (1 − p_a) p_h + (1 − p_h) p_a p_h</code>; winners are re-seeded; the semi-finals and conference finals are single matches at the better seed; MLS Cup is hosted by the finalist with more regular-season points.</li>
<li><strong>Liga MX Liguilla</strong>: play-in 7 v 8 and 9 v 10, the 7-v-8 loser hosting the 9-v-10 winner for the last place; quarter-finals 1 v 8, 2 v 7, 3 v 6, 4 v 5; semi-finals and the final re-seeded, all three rounds two-legged with the higher seed at home in the second leg. Two-legged ties here use an extra-time weight of 1.0, so a level aggregate goes entirely by the strength share (the real rule favours the higher seed).</li>
<li><strong>Argentina</strong>: two zones of 15; the top 8 of each zone enter a fixed single-leg tree (A1–B8, A4–B5, A2–B7, A3–B6, B1–A8, B4–A5, B2–A7, B3–A6), the better zone rank hosting, with a neutral final. The Tabla Anual (both tournaments' zone points, playoffs excluded) sets the continental berths behind the two champions and the Copa Argentina winner, six Libertadores and six Sudamericana places. Two clubs go down: the worst three-season promedio (prior points plus this year's over prior matches plus this year's) and the last club in the Tabla Anual, with the next-worst promedio stepping in if they coincide.</li>
</ul>
<p><strong>${G('forced', 'Forced results')}.</strong> Ties already decided on the pitch are forced by club pair: one decisive game, or two wins in a best-of-three, settles a pair; a two-legged tie is forced after its first decisive leg, so a first leg alone forces the Liguilla tie to that leg's winner, and a level aggregate falls back to the recorded aggregate or penalty winner.</p>
<h5>Cup kinds</h5>
${simpleTable(['Kind', 'Competitions', 'How the bracket is resolved'], [
  ['<code>swiss</code>', 'Champions League, Europa League, Conference League', CUP_KIND_TEXT.swiss + '. Undrawn pairings are drawn at random within the seeding rules; later rounds are two-legged with the better league-phase seed hosting the second leg.'],
  ['<code>groups</code>', 'Libertadores, Sudamericana, CAF Champions League, Club World Cup', CUP_KIND_TEXT.groups + ' (by rejection, up to 20 reshuffles). In the Sudamericana the runners-up first meet an "outside side" of average strength over two legs.'],
  ['<code>regional_swiss</code>', 'AFC Champions League Elite', CUP_KIND_TEXT.regional_swiss + '.'],
  ['<code>knockout</code>', 'CONCACAF Champions Cup, the national cups and super cups', CUP_KIND_TEXT.knockout + '. Rounds and legs come from the competition\'s configuration; a store left with more than one survivor is settled by neutral coin-flip rounds.'],
  ['<code>fixed</code>', 'Intercontinental Cup', CUP_KIND_TEXT.fixed + ' (the Libertadores champion, for example); cups are built in an order that makes those distributions available. All ties are single matches and the final is neutral.'],
  ['<code>international</code>', 'The 16 national-team competitions', 'Not simulated (section 4).']
])}
<p>The league or group phase of a cup is simulated as a league on (points, goal difference, goals, lots); decided ties are forced on aggregate; draws already made fix the pairings and undrawn rounds are drawn at random per simulation. Cups publish the winner probability, the chance of reaching each round, the league-phase or group position distribution, bands and expected points. The top-scorer race is not simulated for cups. One known gap: the Club World Cup's group and early knockout matches are sampled with home advantage for the listed home side although the tournament is neutral; only its final is neutral, and the fixture lines are unaffected.</p>
<h5>The top-scorer race</h5>
<p>For leagues and Argentina the same simulation carries a Golden Boot model. Candidates are the top twelve non-goalkeepers per club by goals, xG and minutes. Within a team, each simulation's remaining goals are split by one multinomial draw over the candidates plus an "other" bucket, with weights <code>2.0 × goals so far + 1.2 × goals per 90 + role base</code> (forward 0.40, midfielder 0.15; 1.5 for the whole "other" bucket). A player's total is current goals plus simulated goals; the leader wins, ties broken by assists then at random. Shares are fixed for the rest of the season and weighted heavily by goals already scored; injuries, transfers and rotation are not modelled.</p>
<h5>The position distribution and history</h5>
<p>The Table tab's heatmap is the finishing-position distribution per club, with the band cut lines drawn through it; split seasons show the post-split final position. Every hourly run appends a snapshot of the headline probabilities (title, the first band, relegation; MLS Cup and the Shield; a cup's winner and first band) to a store that keeps 400; the History tab plots the last 60, so the chart needs two runs before it appears.</p>` });

  S.push({ id: 'power', title: 'Power rankings', html: `
<p>The Power Rankings tab ranks clubs by what the model thinks, separately from the table.</p>
${simpleTable(['Column', 'Definition'], [
  ['<strong>' + G('strength_ppg', 'Strength') + '</strong>', 'Expected points per game against an average opponent at a neutral venue: the mean, over every other team in the competition, of 3 × P(win) + P(draw) from the full ensemble prediction. Averaging over every opponent removes the schedule, which real points per game cannot. (The Clubs across leagues page uses a synthetic pool-average club instead of the competition\'s field, so the two strengths are not the same number.)'],
  ['Strength rank, ' + G('rank_delta', 'rank delta'), 'The rank by strength, and table position minus strength rank within the club\'s zone or conference. Positive means the club sits below where its strength says.'],
  ['Attack, defence, Elo', 'The model\'s Dixon-Coles parameters and the final Elo after replaying the training frame. In cups Elo reads 1500 for everyone.'],
  ['Form', 'The last 6 finished non-playoff matches: results, points, goals for and against.'],
  ['xG for / against / difference', 'Sums of team xG over the matches that have it (the players\' Sofascore expected goals summed per side).'],
  ['Expected points, ' + G('luck', 'luck'), 'Per match, ' + G('xpts', 'xPts') + ' treats the two xG totals as independent Poisson means truncated at 8 goals and returns 3 × P(win) + P(draw); expected points is their sum and luck is actual points minus that sum (0 when there is no xG). Sustained over time it is usually finishing variance, not a skill.'],
  [G('sos', 'Strength of schedule'), 'The mean strength of opponents already played and still to play, and their difference (remaining minus played). Positive means the hard part is still to come.'],
  ['Elo over the season', 'Elo replayed from a fresh seed over the current season\'s or tournament\'s finished matches only, so the trajectory\'s endpoint differs from the Elo column, which is replayed over the whole training frame.']
])}` });

  S.push({ id: 'players', title: 'Player analytics', html: `
<h5>Aggregation and per-90 rates</h5>
<p>Every per-match statistic in a player's line-ups is summed over the season by player id; the club shown is the team of the player's latest appearance. The ${G('rating')} is the minutes-weighted mean of Sofascore's match ratings. Non-penalty goals are goals minus penalties counted from the incidents, and non-penalty xG is <code>max(xG − 0.79 × penalties taken, 0)</code>, 0.79 being the value the site assigns a penalty. A goalkeeper's goals conceded are the opponent's goals scaled by <code>min(minutes, 90) / 90</code>, and save percentage is saves over saves plus conceded. Ratio statistics (shots on target, pass completion, dribble success, duel success and so on) are built from summed numerators and denominators, never from averaged percentages. Every counting statistic gets a per-90 twin: <code>total / (max(minutes, 1) / 90)</code>.</p>
<h5>The catalogue</h5>
<p>The metric catalogue lists every metric the site computes (98 at the time of writing, in the groups Scoring, Creating, Passing, Carrying, Defending, Duels, Goalkeeping, Physical, Advanced, Rating, Discipline and Playing time), each with its label, format, scope (outfield, goalkeepers or all), whether it gets a ${G('percentile')} and whether lower is better. The leaderboards, the sliders on player pages, the compare page and the Player lab are built from that list, and the ${G('percentile', 'glossary')} defines every entry.</p>
<h5>Minutes floor and percentiles</h5>
${formula('floor = max(90, min(270, round(0.35 × most minutes played by anyone in the competition)))\n\npct   = round(100 × (peers below + 0.5 × ties) / n)      flipped for lower-is-better metrics')}
<p>${G('pool', 'Pools')} are positional: goalkeepers (by Sofascore's keeper flag), defenders, midfielders and forwards, with a residual outfield pool for anyone unlabelled; only players at or above the ${G('minutes_floor', 'floor')} are pooled, and a player below it has no percentiles ("not enough minutes"). A percentile is skipped when the pool has fewer than three values or the metric's scope does not fit the pool (goalkeeper metrics only for keepers, outfield metrics never for them). A leaderboard showing a season total uses the percentile of its per-90 twin.</p>
<h5>The advanced metrics</h5>
${simpleTable(['Key', 'Definition', 'Why'], [
  ['<code>npxg_xa_90</code>', '(npxG + xA) per 90', 'total expected involvement in goals, penalties excluded'],
  ['<code>ga_90</code>', '(goals + assists) per 90', 'the realised counterpart'],
  ['<code>finishing</code>', '(npG − npxG) / non-penalty shots', 'finishing above or below expectation, per shot so volume does not dominate'],
  ['<code>placement</code>', '(xGOT − xG) / shots', 'how much a player\'s placement adds to the chance they had; xGOT counts only shots on target'],
  ['<code>xa_per_kp</code>', 'xA / key passes', 'the quality of the chances a player creates'],
  ['<code>shot_creation_90</code>', '(shots + key passes) per 90', 'shot-ending and shot-creating volume'],
  ['<code>prog_actions_90</code>', '(progressive carries + completed dribbles) per 90', 'carrying the ball forward'],
  ['<code>def_actions_90</code>', '(tackles + interceptions + blocks + clearances) per 90', 'raw defensive volume'],
  ['<code>padj_tkl_int_90</code>', 'Σ over matches of (tackles + interceptions) × 50 / opponent possession, per 90; opponent possession clamped to 25–75% and read from the team sheet, matches without a sheet unadjusted', 'possession-adjusted defending: a side without the ball has more to defend'],
  ['<code>ball_wins_90</code>', '(tackles won + interceptions + recoveries) per 90', 'regaining the ball'],
  ['<code>duels_90</code>, <code>aerials_90</code>', 'duels / aerials contested per 90', 'the volume behind the success rates'],
  ['<code>loss_per_100</code>', 'possession lost per 100 touches (lower is better)', 'ball security independent of how often a player is on the ball']
])}
<h5>League adjustment and the global pool</h5>
<p>The global leaderboards and the Player lab put players from different competitions together. Attacking rates are multiplied by the league's ${G('scoring_factor', 'scoring factor')} from the pooled fit (section 3), percentiles are recomputed over the global positional pools with a floor of 270 minutes, and the raw value, the factor and the adjusted value are all shown. Cups, national teams and Argentina carry a factor of 1.</p>
<h5>The Player lab: shrinkage and calendar windows</h5>
<p>The lab scatters any two catalogue metrics for one position group. "Shrink small samples" (on by default) pulls each rate towards the group median with 450 minutes of prior:</p>
${formula('shrunk rate = (minutes × rate + 450 × group median) / (minutes + 450)')}
<p>Five full matches move a player halfway from the median to their own figure; two thousand minutes leave a player almost untouched. Hover shows the unshrunk figures and the axes say "(shrunk)". Axes where less is better are reversed so better is always up and to the right; the twelve players furthest into that corner by summed standard scores are labelled. The two calendar views ("last 12 months", "calendar year so far") read one line per player across every competition played in over that window, club and national team, with the club being the player's latest club and league adjustment using the minutes-weighted blend of the factors of the player's competitions; a banner names any competition whose detail does not yet reach back to the window's start (section 1). The minutes floor is 450 across competitions and 270 within one.</p>
<p>Sofascore labels positions only G, D, M and F, so wingers usually sit with the midfielders and wing-backs with the defenders, and a player's percentiles are against that label's pool.</p>` });

  S.push({ id: 'teams', title: 'Team analytics', html: `
<h5>Per-match rows and season profiles</h5>
<p>Each match with a team-statistics sheet gives one row per side: possession, xG and xGOT, shots (on target, off target, blocked, inside and outside the box), big chances, corners, offsides, fouls, cards, passes and accurate passes, touches in the box, final-third entries, long balls, crosses, through balls, tackles, interceptions, recoveries, clearances, errors, duels (ground and aerial, won and contested), dribbles, dispossessions, saves, goals prevented, distance and sprints, plus the opponent's shooting against (xG against, shots against, shots on target against, xGOT against). Where a sheet lacks xG the row falls back to the line-up sum. The season profile is the mean over the matches in which each value exists, with derived rates from sums:</p>
${formula('xg_diff     = xG − xG against                  xg_per_shot = Σ xG / Σ shots\nconv        = Σ goals / Σ shots                pass_pct    = Σ accurate passes / Σ passes\naerial_pct  = Σ aerials won / Σ aerials       ground_pct  = Σ ground duels won / Σ ground duels\nsave_pct    = (Σ shots on target against − Σ goals against) / Σ shots on target against')}
<p>Within-competition percentiles over the team catalogue use the same formula as players (share of clubs below, ties counting half, flipped for lower-is-better metrics such as xG against); the club page shows them as sliders and the compare page as pills with the club's rank. Two style measures are built on the match sheets: ${G('field_tilt')} is a team's share of the touches in both penalty areas (its box touches over its own plus the opponent's), territory rather than possession; ${G('ppda', 'PPDA')} is the opponent's passes divided by the team's defensive actions over the whole pitch, so a lower figure means a higher press. A match's ${G('xpts', 'expected points')} come from the two xG totals as independent Poisson means truncated at 8 goals (3 × P(win) + P(draw)); summed and subtracted from actual points they give ${G('luck', 'luck')} (section 6).</p>
<h5>Team of the week and the season XI</h5>
<p>The Analytics tab picks a team of the week for each round and a best XI for the season from the players' match ratings. A player needs 45 minutes in a match to be considered for a team of the week and a minimum of 60 minutes per match on average for the season XI, so a cameo cannot make either. Within those, a formation optimiser tries each listed shape (the shapes the tab shows, from a back four with three midfielders through a back three) and, for each, fills every line with the best-rated eligible players at that position, keeping the shape whose eleven rate highest in total. Positions are Sofascore's G, D, M and F, so the optimiser cannot distinguish a winger from a central midfielder.</p>` });

  S.push({ id: 'match-centre', title: 'The match centre', html: `
<p>A match page is descriptive; only two parts involve any computation.</p>
<h5>The expected result</h5>
<p>Every shot in the match is replayed <strong>20,000 times</strong> as a coin flip at its xG, seeded by the match id so that the card is stable between visits. The share of replays each side wins, draws or loses is the ${G('expected_result', 'expected result')}, alongside the chance of the actual scoreline and a scoreline heatmap with the real score outlined. One caveat the card states: rebounds count as separate chances, so a saved shot followed by a tap-in is two chances in the replay although only one could have been a goal.</p>
<h5>The pitch and the goal mouth</h5>
<p>Sofascore records a shot's position as its distance from the goal line being attacked (0 at the line) and its position across the pitch, both in percent of the pitch. The full-pitch shot map draws the home side attacking right, marker size by xG, colour by outcome, ring by team and symbol by body part; filters cover team, situation (open play, set pieces, penalties) and outcome, with a running summary of the filtered shots. "Where the shots went" draws each team's goal frame from the shooter's view with markers sized by xGOT; on Sofascore's goal-mouth scale the posts sit at y 44.6 and 55.4 and the bar at z 38, with higher y being the shooter's left. The xG race is the cumulative xG step line per side with a dot per shot sized by xG and goals in green; the momentum chart is Sofascore's pressure index (positive is home pressure).</p>
<h5>Everything else</h5>
<p>The summary tiles (xG and non-penalty xG, xG on target, shots and on target, xG per shot, big chances, possession), the chance-creators chart (xG and xA stacked per player), the team statistics by phase (with a derived block first: xG per shot, non-penalty xG, pass accuracy, field tilt, PPDA, xGOT − xG), the line-ups drawn on the pitch from the formation string and coloured by rating, and the sortable player table are read straight from the match's shard. Starters are kept in Sofascore's order within each line (from the team's right to its left) so that the drawing is faithful; when a formation string does not add up to ten outfielders the drawing is skipped and the starters are listed instead.</p>` });

  S.push({ id: 'markets', title: 'The market, as a reference', html: `
<p>Match pages and this Model section show the prediction markets' number beside ours, in grey and labelled with its source, as a check on our forecast. Nothing on this site is an offer or a recommendation; the market is usually the better-informed of the two.</p>
<h5>Prediction markets: Polymarket and Kalshi</h5>
<p>Since 30 September 2026 the match and title markets are read from the public data of Polymarket and Kalshi, with no key. A market's probability is the <strong>midpoint of the best bid and ask</strong>; a market with no live two-sided quote, or a spread wider than 0.12, is skipped. A fixture has three yes/no markets (home, draw, away); each source's three probabilities are ${G('devig', 'de-vigged')} multiplicatively (<code>p_i = q_i / Σ_j q_j</code>) and the sources are pooled by taking the median per outcome and renormalising (the ${G('consensus')}). A market event is matched to a fixture within 36 hours of kick-off when both clubs match after folding accents and suffixes (FC, AFC, CF…), by token subset or a similarity of at least 0.72, with ambiguous ties refused and a small alias table for city names (Kalshi's "Eindhoven" is PSV).</p>
<p><strong>Titles.</strong> Kalshi's champion series and Polymarket's champion event are averaged per club and shown beside the simulation's title chance (the cup or playoff winner chance where that is the prize). The title market is shown only when at least half the field is quoted and the implied probabilities sum to between 0.8 and 1.3; a market that does not quote every team would otherwise inflate the de-vigged probabilities. Markets usually list a matchday about a week ahead; every fixture carries our forecast regardless.</p>
${note('Early in a season the two can differ a lot. The first run rated Manchester City 38% for the 2026–27 Premier League against the market\'s 18%, and Liverpool 0.4% against 7%, which says more about a model fitted mostly on five matches of a new season than about the market.', true)}
<h5>Bookmaker lines (not shown)</h5>
<p>Bookmaker head-to-head lines can be fetched from The Odds API when a key is present in the build environment; without one the fetch is skipped. The bookmaker path currently returns no fixtures because the fetcher's row shape (one row per bookmaker outcome) does not match what the builder expects (rows grouped by fixture), so no bookmaker number appears anywhere on the site.</p>` });

  S.push({ id: 'value', title: 'Player value and transfers', html: `
<p>The ${G('goals_added', 'value')} pages (<a href="#/value">Player value</a>, a club's "Strengths and needs", the <a href="#/transfer">transfer simulator</a>) measure every player's minutes in one currency: <strong>goals of non-penalty expected goal difference</strong>. Every number is rebuilt with the site each hour.</p>
<h5>What is counted</h5>
<p>Each player-match line in the stores gives sixteen actions: non-penalty xG, xA, key passes, progressive carries, dribbles completed, accurate passes in the opposition half, possession lost, tackles won, interceptions, blocks, clearances and recoveries (these six out-of-possession actions multiplied by 50 / the opponent's possession, clamped to 25–75%, as the PAdj metrics are), aerial duels won, errors leading to a shot, and for goalkeepers goals prevented and high claims plus sweeper actions. The second input is Sofascore's match rating.</p>
<h5>How the weights are fitted</h5>
${formula('per club match:  npxG difference (home − away)  ≈  h + Σ_actions β_k × (A_home,k − A_away,k)\n\nA_side,k = Σ_players (minutes / 90) × the player\'s per-90 rate of action k from earlier days only,\n           shrunk toward the position\'s mean (also from earlier days) by 450 minutes\n\nβ_k ≥ 0 after signing "bad" actions negative; ridge chosen on the last 20% of the training matches\n\nsecond stage:  npxG difference ≈ c + a × (box-score index) + b × (line-ups\' prior rating), a, b ≥ 0')}
<p>The weights are therefore <em>predictive</em>: an action that does not help forecast later matches gets little or no weight, however often it appears. A goal of goal difference is worth the slope of expected points at the league's scoring rate (two Poisson sides; about 0.65 to 0.75 points), which turns goals into ${G('par', 'points')}.</p>
<h5>Is it better than the rating?</h5>
<p>Walk-forward over the club matches with both line-ups: the matches are put in date order, the last 60% cut into five blocks, and each block predicted by models fitted only on earlier matches, every input from before the match day. On the 15 October 2026 stores (3,479 test matches) the line-ups' value explained 21.6% of the variance in a match's non-penalty xG difference, against 15.4% for the line-ups' Sofascore rating alone and 16.3% for each team's own prior xG difference; for goal difference, which is mostly luck in a single match, 16.6% against 13.9%. The box-score part alone explains 18.6% of xG difference but only 12.7% of goal difference, which is why the rating is kept as an input. Split into odd and even matches, a regular's value correlates 0.82 with itself and the rating 0.56. The <a href="#/value">value page</a> shows the current build's numbers.</p>
<h5>One scale, roles and replacement</h5>
<p>A player's raw value is relative to the opposition in the player's competition, so every competition is centred on its own mean and moved by its strength on the ${G('pooled', 'pooled scale')}: the minutes-weighted expected goal difference of its clubs against the pool-average club, shared over eleven players (Argentina, outside the pool, is bridged through its clubs in continental cups). ${G('role', 'Roles')} come from the starting formations, since Sofascore lists each line of an XI right to left: a 4-2-3-1 is FB, CB, CB, FB, DM, DM, W, AM, W, ST. ${G('gar', 'GAR/90')} subtracts the ${G('replacement_level', 'replacement level')} of the role (the 20th-percentile regular with 900+ minutes in the last 12 months), and projected GAR/90 shrinks it toward replacement by 900 minutes.</p>
<h5>Strengths and needs</h5>
<p>Each club of a followed league is graded unit by unit (goalkeeper, centre-backs, full-backs, central midfield, attacking midfield and wingers, strikers) on the projected value of its current players, weighted by their minutes there this season, against the other clubs of its league: A is the top fifth, E the bottom fifth. The three best and worst units are its strengths and weaknesses, with the component that stands out. For each weakness the targets are the players who would add the most over the weakest current regular in the unit, among players at a club of similar or lower pooled strength (at most 0.15 points per game stronger), from a league at most a quarter of a goal per match stronger, aged 31 or under with 900+ minutes in 12 months, or listed by Sofascore without a club (33 or under). Hints appear only where the data supports them: a contract ending within a year (Sofascore's dates), surplus depth at the player's club (two or more regulars beyond the unit's usual starters), or a club with nothing left to play for (title, every band and relegation below 2% in its simulation). Nothing here knows wages, fees, contracts beyond Sofascore's contract dates, fit or availability.</p>
<h5>The transfer simulator</h5>
<p>A signing takes minutes in the player's unit: each unit's usual number of players a match is filled best projection first, each player's 85 minutes a match split over the units the player played in this season (so nobody plays twice), the rest going to a replacement-level player; players leaving free their minutes the same way. The change in goals per match becomes a strength shift (divided by the club's expected goal difference gained per unit of shift), and the club's ${G('sensitivity_curve', 'sensitivity curves')} turn the shift into title, European, relegation and expected-points changes. The curves come from re-running the competition's own season simulator with the club's goal rate multiplied by exp(±shift / 2) and its opponents' by the inverse, at shifts of ±0.15 and ±0.3 (2,000 runs each, common random numbers), applied as changes to the published probabilities.</p>
<h5>Valuation v2, fair fees and budgets (16 October 2026)</h5>
<p>${G('value_v2', 'Value')} is the expected points above replacement a player adds over the next four seasons, discounted 15% a year: the player's projected GAR/90 drawn from its uncertainty (the fewer the minutes, the wider), moved each year by the ageing curve plus a random year-to-year change, times 3,400 minutes a season scaled by the player's ${G('availability', 'availability')}, times the chance the player is still a regular; 400 draws give the band. A ${G('fair_fee', 'fair fee')} model is fitted on real fees: Sofascore's transfer data (already the site's source; the hourly task fetches each followed club's recent transfers and players' histories inside its existing call budget). For every published fee whose player had 450+ club minutes in our data in the year before, the model sees the player's value as it was the day before the move, age, position and minutes, and both clubs' strength on the pooled scale. On 16 October 2026 it was fitted on 701 fees: out of sample (five folds by player) its typical error was a factor of 1.82 (45% of fees within ±50%), against 2.40 for the median fee of the buyer's league tier and position, and a factor of 1.78 on the latest 30% of fees predicted from the earlier 70%; rank-correlated with Sofascore's market values over 3,411 players, 0.76. The buyer's strength matters most: the same player costs more to a stronger club, which is why the simulator values the player for the chosen buyer. Position scarcity enters through the model's position terms.</p>
<p>Every move of the last 12 months gets a ${G('deal_grade', 'grade')} for each club: the fee against the fair fee at the time (cross-fitted, so a deal never grades itself, and weighted by how much of the player we had seen), then the value delivered since the move (GAR/90 for the new club against the projection at the time, and the player's share of the minutes), counting more as those minutes accumulate. Club pages carry a ledger (ins and outs, spend by window, market value added) and a ${G('transfer_budget', 'budget')}: a model fitted across the 266 followed clubs on the latest summer window from the previous window's spending and sales and the league's and club's strength (out of sample: rank correlation 0.72, half the clubs inside their 25-75% range). The suggestions on club pages carry each target's fair fee to that club and whether it fits the budget; targets far beyond it are left out. Undisclosed fees are counted, never summed, and older windows rest on players' histories, which are still filling in. Sofascore's market value is shown for reference. The ${G('fair_value_index', 'fair value index')} of the first version is still computed and is the fallback when too few fees are available.</p>
<p>Transfer windows are typical registration periods, not the exact dates of each year. Nothing here knows wages, bonuses, release clauses or owners' money.</p>` });

  S.push({ id: 'fantasy', title: 'Fantasy', html: `
<p>The <a href="#/fantasy">fantasy pages</a> score every followed league with ${G('fantasy_points', 'FPL-style points')} computed by us from Sofascore's match data (FPL's 2025/26 rules: minutes, goals by position, assists, clean sheets, goals conceded, saves, cards, own goals, missed penalties and defensive contributions; the bonus is 3/2/1 for the three best match ratings; penalty saves are not scored).</p>
<p>Each player is projected fixture by fixture: expected minutes and the chances of playing and of 60+ minutes from the player's recent share of the club's league minutes; per-90 rates of goals and assists (70% expected, 30% actual), saves, cards, bonus and defensive contributions, recency-weighted and shrunk to the position; the fixture from the match model's expected goals, so a striker's goals rise against a weak defence and a defender's clean sheet is exp(-expected goals against). Projections are scaled by 0.90, the ratio of actual to projected points in the backtest.</p>
<p>Walk-forward backtest (16 October 2026, 389 league rounds, 198,657 player-rounds, each projected only from earlier matches with a stand-in for the fixture's expected goals): mean absolute error 1.50 points against 1.52 for last-five form, 1.63 for season-to-date points per match and 1.64 for the last 365 days; root mean square error 2.35 against 2.50-2.62; rank correlation within a round 0.54 against 0.48-0.52; the 20 highest-projected players of a round scored 4.35 points on average against 3.68-3.80 for the baselines' top 20. Goalkeepers are the exception: last-five form beats the projection on their absolute error.</p>
<p>${G('fantasy_price', 'Costs')} are our own proxy from the value model; FPL's official figures and ownership are not used because the Premier League's terms forbid reproducing or re-using its material. Without ownership, differentials are players our projection rates highly whose points so far rank outside the top 15 at their position. The suggested squad is the integer programme FPL managers solve (15 players, 2/5/5/3, three a club, £100.0, the best XI in a legal formation and a captain), solved exactly. ${G('fdr', 'Fixture difficulty')} rates each fixture 1-5 by the model's expected goals; ${G('underlying_points', 'underlying points')} separate form from luck.</p>` });

  S.push({ id: 'limitations', title: 'Limitations', html: `
<ul>
<li><strong>Player value is a box score plus a rating.</strong> It credits what Sofascore counts; positioning, pressing without a tackle and off-ball runs are invisible, so defenders and goalkeepers are measured less well than attackers. Weights are refitted every hour and move slightly. A player who changes club carries their value across leagues by the pooled strengths alone.</li>
<li><strong>Early-season noise.</strong> A league five matches old is forecast mostly from last season's goals and the pool's prior; xG rows exist only for the current season. Probabilities move a lot in the first two months, and a title market's disagreement with the model in September is more likely the model's error than the market's.</li>
<li><strong>Unofficial data.</strong> Everything rests on an unofficial API that blocks bursts and datacenter addresses. A challenge or an outage leaves the site on its last good data, flagged as stale; a spelling the registries do not know can drop a club from a join until an alias is added; voided and awarded matches arrive as negative scores and are dropped.</li>
<li><strong>Cross-block identification is weak.</strong> About six cup matches connect the continents in the pooled fit, so league ranks, scoring factors and league-adjusted player rates across blocks are mostly prior (section 3).</li>
<li><strong>The international fit is shallow between confederations</strong> (few cross-confederation matches), and national-team competitions are not simulated (section 4).</li>
<li><strong>Position labels are only G, D, M and F.</strong> Wingers sit with midfielders and wing-backs with defenders in every positional pool, radar and XI. Only the player value pages read finer roles, from the starting formations.</li>
<li><strong>No event data.</strong> Sofascore gives match totals, shots and incidents, not the full event stream. Progressive passes, passes into the box, pressures and packing do not exist here; "progressive carries" and "field tilt" are the closest available proxies.</li>
<li><strong>The rating is Sofascore's.</strong> It is their algorithm's match rating, minutes-weighted; the site does not compute its own.</li>
<li><strong>xG replaces goals rather than blending with them</strong>, club xG is not calibrated to goals, and club fits hold rho at one value estimated across leagues from goals, because their own goals rows are too few to identify it (section 2).</li>
<li><strong>The fit drifts with the calendar</strong>: because the ridge is not rescaled with the time weights, parameters shrink very slowly towards zero between refreshes, a deterministic effect of about 3 × 10⁻⁵ per day on a home-win probability.</li>
<li><strong>Head-to-head tiebreaks are approximated</strong> by goal difference and goals scored in LaLiga and Serie A, and cups use (points, goal difference, goals) in place of their real tiebreak orders. The Belgian split is always simulated from scratch, and points quantiles use 2,000 simulations rather than the full run.</li>
<li><strong>Liguilla forced results are not aggregate-aware</strong>: a two-legged tie is forced after its first decisive leg and a level aggregate goes by strength share rather than seed.</li>
<li><strong>The ensemble's win/draw/loss triple and its score matrix disagree by a few points</strong> on blended fixtures; the simulators use the matrix, the fixture line the triple.</li>
<li><strong>Cup Elo is flat</strong> (unseeded, never updated), so an unknown club in a cup falls back to a pure home-advantage prior.</li>
<li><strong>The market reference.</strong> Bookmaker lines are empty because of the row-shape defect; prediction-market numbers exist only where those markets list a fixture, usually a week ahead.</li>
</ul>` });

  S.push({ id: 'glossary', title: 'Glossary', html: `
<p>Every metric in the catalogue and every model term above is defined in the <a href="#/glossary">glossary</a>, searchable and grouped as on the player pages. Terms linked from this document (dotted underline) open their glossary entry, for example ${G('npxg_90', 'npxG per 90')}, ${G('padj_tkl_int_90', 'possession-adjusted tackles and interceptions')}, ${G('strength_ppg', 'strength')} or ${G('luck', 'luck')}.</p>
<p>The technical references this document follows are the repository's <code>docs/MODELS.md</code> (every model, parameter and formula, read from the code) and <code>docs/DATA_PIPELINE.md</code> (sources, budgets, stores and scheduling), both checked against the code on 29–30 September 2026. Where the code and its own comments disagree, this document follows the code.</p>` });

  return S;
}

var TABS = [['', 'Overview'], ['methodology', 'Methodology'], ['glossary', 'Glossary'], ['calibration', 'Model checks'], ['coverage', 'Data coverage'], ['disclaimer', 'Disclaimer']];

function head(tab, sub) {
  return FB.pageHead('Model', tab === 'glossary' ? 'Glossary' : tab === 'methodology' ? 'Methodology' : tab === 'calibration' ? 'Model checks' : tab === 'coverage' ? 'Data coverage' : tab === 'disclaimer' ? 'Disclaimer and terms' : 'How the numbers are made', sub) +
    FB.subnav(TABS.map(function (t) { return ['#/model' + (t[0] ? '/' + t[0] : ''), t[1], t[0]]; }), tab, 'Model sections');
}

FB.route('model', function (el, p) {
  var tab = p.tab || '';
  if (tab === 'methodology') return methodology(el, p);
  if (tab === 'glossary') return glossary(el, p);
  if (tab === 'calibration') return calibration(el);
  if (tab === 'coverage') return coverage(el);
  if (tab === 'disclaimer') return disclaimer(el);
  return overview(el);
});

// ── overview ────────────────────────────────────────────────────────────────

/* "We say it. Then we check it." (kit v4 QK.howSure: three big numbers over the we-said / it-happened bars): the match
   model's walk-forward record from data/calibration.json, at the top of the overview and of Model checks. The section
   stays empty until the file exists (the data build adds it). */
function howSure(el) {
  return FB.load('calibration.json').then(function (j) {
    var box = el.querySelector('#md-sure');
    if (!box || !FB.alive(el)) return;
    var cb = FB.calibOf ? FB.calibOf(j) : QK.calib.find(j);
    if (!cb || !cb.bins || !cb.bins.length) { box.innerHTML = ''; return; }
    box.innerHTML = '<section class="qk-section fb-md-sure">' + QK.sectionHead({ kicker: 'How sure are we?', title: 'We say it. Then we check it.',
      sub: 'Every match in our backtest, grouped by the chance we gave ' + esc((j && j.subject) || 'the home side') + ' to win, against how often it happened. When the two bars match, our numbers mean what they say.' }) + '<div id="md-sure-in"></div></section>';
    QK.howSure(box.querySelector('#md-sure-in'), { bins: cb.bins, brier: cb.brier, n: cb.n, league: (j && j.league) || 'Football', span: (j && j.span) || '', subject: (j && j.subject) || 'the home side', unit: 'matches' });
  });
}

function overview(el) {
  var live = FB.comps().filter(function (c) { return c.ok; }).length;
  el.innerHTML = head('', 'Every chance, rating and value on the site comes from a model fitted to match data. Here is what each one does, how well it checks out, and where it is wrong.') +
    '<div id="md-sure"></div><div id="md-ov" class="fb-md-ov">' + FB.loading('card', 6) + '</div>';
  howSure(el);
  return Promise.all([FB.load('value/meta.json'), FB.load('fantasy/meta.json')]).then(function (arr) {
    if (!FB.alive(el)) return;
    var vm = arr[0] || {}, fm = arr[1] || {};
    var r2 = ((vm.validation || {}).r2 || {}).xgd || {};
    var fee = (((vm.fee || {}).validation || {}).cv || {}).model || {};
    var bt = ((fm.backtest || {}).methods || {}).model || {};
    var cards = [
      ['match-model', 'The match model', 'Dixon-Coles goals model blended with Elo: a full score distribution for every fixture and our home, draw and away chances.', '30,000', 'simulations a competition', '#/model/methodology/match-model'],
      ['simulations', 'Season simulations', 'The rest of every season played out tens of thousands of times: title, qualification, relegation and cup chances, finishing positions.', String(live), 'competitions modelled', '#/model/methodology/simulations'],
      ['pooled', 'One scale for every club', 'One fit across every league and club cup, so a Brazilian club and a Belgian one can be measured against each other.', '', '', '#/model/methodology/pooled'],
      ['value', 'Player value', 'Goals added above a replacement player per 90, from sixteen match actions and the rating, checked out of sample.', isNum(r2.value) ? num(r2.value, 2) : '—', 'R² on later xG difference', '#/model/methodology/value'],
      ['transfers', 'Transfers and fair fees', 'A fee model fitted on real transfer fees, deal grades for both clubs, and each club\'s likely budget.', isNum(fee.within_50pct) ? pct(fee.within_50pct) : '—', 'fees within 50%, cross-validated', '#/model/methodology/value'],
      ['fantasy', 'Fantasy projections', 'Points per gameweek from expected minutes, goals, assists and clean sheets, backtested on every round played.', isNum(bt.mae) ? num(bt.mae, 2) : '—', 'mean absolute error, points', '#/model/methodology/fantasy'],
      ['coverage', 'Data coverage', 'Seasons are counted the way fans count them; where line-ups are missing, the row says so and Sofascore\'s season totals stand in.', '', '', '#/model/coverage'],
      ['markets', 'The market, as a reference', 'Kalshi and Polymarket numbers with the margin removed, shown in grey beside ours on match pages, before kick-off only.', '', '', '#/model/methodology/markets']
    ];
    FB.set('md-ov', '<div class="fb-md-cards">' + cards.map(function (c) {
      return '<a class="qk-card is-link accent-top fb-md-card" href="' + esc(c[5]) + '"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">' + esc(c[1]) + '</h3></div></div>' +
        '<div class="qk-card-body"><p class="qk-sub">' + esc(c[2]) + '</p>' + (c[3] ? '<div class="fb-md-stat"><b class="fb-num">' + esc(c[3]) + '</b><span>' + esc(c[4]) + '</span></div>' : '') + '</div>' +
        '<div class="qk-card-foot"><span></span><span>Read →</span></div></a>';
    }).join('') + '</div>' +
      '<div class="fb-sec">' + FB.grid(
        FB.card('Where the models are wrong', 'Read this before reading anything into a probability.', '<ul class="fb-md-list">' +
          '<li>A probability is not a prediction that something will happen: a 70% favourite loses three times in ten.</li>' +
          '<li>The models know results, xG, past line-ups and ratings. Until the XIs are announced, about an hour before kick-off, they do not know injuries announced this morning, a new manager, or a club playing its reserves; once a league match\'s XIs are in, its line includes them.</li>' +
          '<li>Clubs from different continents meet rarely, so the one-scale ratings across continents are the least certain numbers on the site.</li>' +
          '<li>Some past seasons are incomplete; a row marked <span class="fb-cov partial">Partial</span> is a lower bound. See <a href="#/model/coverage">data coverage</a>.</li></ul>', { span: 7 }) +
        FB.card('Look something up', 'Every metric and model term, in plain words.', '<p class="qk-sub">' + G('npxg_90', 'npxG per 90') + ', ' + G('strength_ppg', 'strength') + ', ' + G('gar', 'GAR/90') + ', ' + G('xpts', 'expected points') + ', ' + G('luck', 'luck') + ' and 200 more.</p><a class="qk-btn" href="#/model/glossary">Open the glossary →</a>', { span: 5 })
      ) + '</div>' + '<div id="md-moves"></div>');
    movesBlock(el, vm.moves);
  });
}

/* "Who moves next": the moves payload's meta.method verbatim and the pre-registered test (meta.validation), from the
   copy value/meta.json carries under `moves` (no request for value/moves.json). Rendered only when it is there. */
var MOVE_ROWS = [
  ['leave', 'Chance of leaving', 'log-loss', 'll_model', 'll_base', 'll_diff_ci'], ['type', 'Type of move', 'log-loss', 'll_model', 'll_base', 'll_diff_ci'],
  ['dest', 'Destination', 'log-loss', 'll_model', 'll_base', 'll_diff_ci'], ['arrivals', 'Arrivals', 'deviance', 'dev_model', 'dev_base', null],
  ['targets', 'Targets', 'top-10 hit rate', 'precision10', 'precision10_avail', 'diff_avail_ci']
];
function movesBlock(el, meta) {
  (function () {
    var box = el.querySelector('#md-moves');
    if (!box || !box.isConnected) return;
    meta = meta || {};
    if (meta.ok === false || !meta.method) return;
    var V = meta.validation || {};
    var f = function (x, d) { return isNum(x) ? num(x, d === undefined ? 4 : d) : '—'; };
    var rows = MOVE_ROWS.filter(function (r) { return V[r[0]]; }).map(function (r) {
      var v = V[r[0]], ci = r[5] ? v[r[5]] : null;
      return [esc(r[1]), esc(r[2]), f(v[r[3]]), f(v[r[4]]), Array.isArray(ci) && ci.length === 3 ? f(ci[1]) + ' to ' + f(ci[2]) : '—',
        v.passed ? '<span class="qk-tag signal">Model</span>' : '<span class="qk-tag">Base rate</span>'];
    });
    var method = Array.isArray(meta.method) ? meta.method.map(function (t) { return '<p>' + esc(t) + '</p>'; }).join('') : String(meta.method).split(/\n\n+/).map(function (t) { return '<p>' + esc(t) + '</p>'; }).join('');
    box.innerHTML = '<section class="fb-sec">' + FB.secHead('Who moves next', 'How the movement views are made' + (meta.horizon ? ' for ' + esc(meta.horizon) : '') + ', and which parts passed their held-out test.') +
      FB.grid(FB.card('Method', '', '<div class="fb-md-doc">' + method + '</div>', { span: 6 }) +
        FB.card('The pre-registered test', 'Each part against its base rate on the held-out window. A part that passed is shown as a model; one that did not is shown as a base rate and labelled so.',
          rows.length ? simpleTable(['Part', 'Measure', 'Model', 'Base rate', '95% CI, difference', 'Shown as'], rows) + (V.test ? '<p class="fb-cap fb-md-pad">Held-out window: ' + esc(V.test) + '. Lower log-loss and deviance are better; higher precision is better.</p>' : '') : FB.muted('No validation table in the payload.'), { span: 6, flush: !!rows.length })) + '</section>';
  })();
}

// ── methodology ─────────────────────────────────────────────────────────────

var SECS = null;
function secs() { if (!SECS) SECS = sections(); return SECS; }

var METHOD_LABELS = { pooled: 'the pooled fit over every league and club cup', global: 'the parameter set shared across leagues', 'per-league': 'this competition\'s own tuned fit', 'default': 'the untuned defaults', 'international fit': 'the international fit (national teams)' };
var CUP_KIND_TEXT = {
  swiss: 'a 36-club league phase; places 1–8 go straight to the Round of 16, places 9–24 play a two-legged play-off (9 v 24 … 16 v 17, the higher finisher at home in the second leg), then a fixed two-legged bracket [1, 8, 4, 5, 2, 7, 3, 6] and a single-match neutral final',
  groups: 'groups whose top two go through; the first knockout round pairs group winners (hosting the second leg) with runners-up from other groups, drawn at random per simulation',
  regional_swiss: 'two regional leagues of 16; the top 8 of each play a two-legged Round of 16 within the region, then West meets East at random from the quarter-finals, which are single neutral legs',
  knockout: 'a straight knockout read from the draw: pairs come from the draw where known and from a random pairing of the survivors otherwise, with byes for odd counts',
  fixed: 'ties fixed by the competition\'s rules; a slot held by another cup\'s champion is drawn per simulation from that cup\'s winner distribution',
  international: 'national-team competition: not simulated; tables and the knockout ladder are shown as played and each fixture carries the international fit\'s line'
};

function competitionCard(c, m, t, b) {
  m = m || {}; t = t || {}; b = b || {};
  var model = m.model || {}, cal = m.calibration || {};
  var k = c.kind || 'league';
  var played = isNum(m.games_played) ? m.games_played : c.games_played, total = isNum(m.games_total) ? m.games_total : c.games_total;
  var tiles = [
    FB.kpi('Season', esc(k === 'liga' ? 'Torneo ' + (m.phase === 'clausura' ? 'Clausura' : 'Apertura') : (FB.currentSeason(c).season || m.season || c.season || '—')), { text: true, sub: (played || 0) + ' of ' + (total || 0) + ' matches played' }),
    FB.kpi('Simulations', m.unsimulated ? 'none' : FB.int(m.n_sims || 0), { sub: m.unsimulated ? 'national teams are not simulated' : isNum(m.runtime_s) ? 'run in ' + num(m.runtime_s, 1) + ' s' : '' }),
    FB.kpi('Training matches', isNum(m.training_matches) ? FB.int(m.training_matches) : '—', { sub: model.params_method ? 'parameters: ' + esc(model.params_method) : '' }),
    FB.kpi('Store', m.store_fresh === false ? '<span class="fb-down">stale</span>' : m.store_fresh === true ? 'fresh' : '—', { text: true, sub: (isNum(m.store_age_hours) ? num(m.store_age_hours, 1) + ' h since the last refresh' : '') + (m.updated_at ? ' · built ' + esc(FB.fmtStamp(m.updated_at)) : '') }),
    FB.kpi('Match detail', isNum(m.detail_matches) ? FB.int(m.detail_matches) : '—', { sub: 'matches with line-ups' + (isNum(m.sheet_matches) ? ' · ' + m.sheet_matches + ' with the team sheet' : '') })
  ];
  var params = [];
  if (model.params_method) params.push(['Parameter set', esc(METHOD_LABELS[model.params_method] || model.params_method), 'model_params.json']);
  if (isNum(model.dc_xi)) params.push(['Dixon-Coles time decay (xi)', model.dc_xi + ' per day <span class="qk-muted">(half-life ' + Math.round(Math.log(2) / model.dc_xi) + ' days)</span>', 'every match weighted exp(−xi × days ago)']);
  if (isNum(model.dc_ridge)) params.push(['Ridge', String(model.dc_ridge), 'penalty on the squared attack and defence parameters']);
  if (isNum(model.dc_weight)) params.push(['Dixon-Coles weight in the blend', String(model.dc_weight), model.dc_weight >= 1 ? 'Elo enters only for a club unknown to the fit (at 0.30)' : 'the rest is Elo']);
  if (isNum(model.elo_home_advantage)) params.push(['Elo home advantage', model.elo_home_advantage + ' points', 'added to the home rating in the expectation']);
  if (isNum(model.elo_k_league)) params.push(['Elo K', String(model.elo_k_league), 'rating change per match, scaled by the surprise']);
  if (model.dc_fitted === false) params.push(['Dixon-Coles', '<span class="fb-down">not fitted</span>', 'too few matches; Elo only']);
  if (isNum(cal.draw_rate)) params.push(['Measured draw rate', pct(cal.draw_rate, 1), 'from the training matches']);
  if (isNum(cal.mean_goals)) params.push(['Goals per team per match', num(cal.mean_goals, 2) + (isNum(cal.lam_scale) ? ' <span class="qk-muted">(scale ' + num(cal.lam_scale, 2) + ')</span>' : ''), 'sets the Elo side\'s goal expectation']);
  if (isNum(cal.home_win_rate)) params.push(['Home wins', pct(cal.home_win_rate, 1), 'reported, not used']);
  var format = [];
  if (k === 'liga') {
    format.push('30 clubs in two zones of 15; each club plays 16 matches (14 in its zone plus 2 interzone). The top 8 of each zone reach a single-match Round of 16 on a fixed tree; the final is at a neutral venue.');
    format.push('The Tabla Anual adds Apertura and Clausura points; it decides the Libertadores and Sudamericana berths behind the two champions and the Copa Argentina winner. Two clubs go down: the worst three-season promedio and the last club in the Tabla Anual.');
  } else if (k === 'cup' || c.cup_kind) {
    var ck = c.cup_kind || m.cup_kind || '';
    if (CUP_KIND_TEXT[ck]) format.push('Format (' + esc(ck.replace('_', ' ')) + '): ' + CUP_KIND_TEXT[ck] + '.');
    if (b.note) format.push(esc(b.note));
    if (m.forced_ties) format.push(m.forced_ties + ' ties already decided on the pitch are forced in every simulation.');
    if (m.phase === 'pre') format.push(esc(m.phase_note || 'The main phase has not started; nothing is simulated yet.'));
    if (m.cup_complete) format.push('This edition is complete.');
  } else {
    if (t.conferences) format.push(Object.keys(t.conferences).length + ' ' + esc(((t.group_label || 'conference') + 's').toLowerCase()) + (t.matches_per_team ? ', ' + t.matches_per_team + ' matches per club' : '') + '.');
    else if (t.matches_per_team) format.push('One table, ' + t.matches_per_team + ' matches per club.');
    (t.bands || []).forEach(function (bd) { format.push(esc(bd.label) + ': ' + (bd.first === bd.last ? 'position ' + bd.first : 'positions ' + bd.first + '–' + bd.last) + (t.conferences ? ' in each ' + esc((t.group_label || 'conference').toLowerCase()) : '') + '.'); });
    if (t.split) format.push('Split season: after the regular season the table splits into groups of ' + t.split.top + ' (championship), ' + t.split.europe + ' (Europe) and ' + t.split.relegation + (t.split.halve_points ? ', carrying half their points (rounded up)' : '') + '; each group plays a double round-robin in every simulation.');
    if (b.note) format.push(esc(b.note));
  }
  var tb = t.tiebreak || (k === 'liga' ? ['pts', 'gd', 'gf'] : null);
  if (tb) {
    var names = { pts: 'points', w: 'wins', gd: 'goal difference', gf: 'goals scored', h2h: 'head-to-head' };
    format.push('Tiebreak in the simulation: ' + tb.map(function (x) { return names[x] || x; }).join(', then ') + ', then lots (a uniform random jitter).' +
      (t.h2h_tiebreak || m.h2h_tiebreak ? ' The real rules break level points on head-to-head record first; the simulation uses goal difference, which only matters for clubs finishing level on points.' : ''));
  }
  if (m.unsimulated) format.push('This is a national-team competition: nothing is simulated. Standings and the knockout ladder are as played; the model line on each fixture comes from the international fit.');
  if (m.league_complete && k === 'league') format.push('The season is complete; probabilities reflect the final table.');
  return '<section class="qk-card accent-top" id="method-this"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">This competition: ' + esc(c.name) + '</h3>' +
    '<div class="qk-card-sub">The model settings, calibration and format behind its pages. <a href="' + esc(FB.href.comp(c.slug)) + '">Open ' + esc(c.short_name || c.name) + ' →</a></div></div></div>' +
    '<div class="qk-card-body">' + FB.kpis(tiles) +
    (params.length ? '<div class="qk-table-wrap fb-md-kv"><table class="qk-table dense"><thead><tr><th>Setting</th><th>Value</th><th>Where it applies</th></tr></thead><tbody>' +
      params.map(function (r) { return '<tr><td>' + esc(r[0]) + '</td><td class="num">' + r[1] + '</td><td class="qk-muted">' + esc(r[2]) + '</td></tr>'; }).join('') + '</tbody></table></div>' : '') +
    (format.length ? '<h4 class="fb-md-h">Format and rules as simulated</h4><ul class="fb-md-list">' + format.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul>' : '') +
    '</div></section>';
}

function methodology(el, p) {
  var slug = (p.query || {}).c;
  var c = slug ? FB.comp(slug) : null;
  if (c && !c.ok) c = null;
  var S = secs();
  var toc = '<nav class="fb-md-toc" aria-label="Contents"><div class="qk-kicker">Contents</div><ol>' +
    (c ? '<li><a href="#method-this" data-target="method-this">This competition</a></li>' : '') +
    S.map(function (s) { return '<li><a href="#/model/methodology/' + esc(s.id) + '" data-target="method-' + esc(s.id) + '">' + esc(s.title) + '</a></li>'; }).join('') +
    '</ol><div class="qk-kicker fb-md-also">See also</div><ol class="fb-md-also-l"><li><a href="#/model/coverage">Data coverage</a></li><li><a href="#/model/calibration">Model checks</a></li><li><a href="#/model/disclaimer">Disclaimer</a></li></ol></nav>';
  var body = S.map(function (s, i) {
    return '<section class="qk-card fb-md-sec" id="method-' + esc(s.id) + '"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">' + (i + 1) + '. ' + esc(s.title) +
      ' <a class="fb-md-anchor" href="#/model/methodology/' + esc(s.id) + '" aria-label="Link to this section">#</a></h3></div></div><div class="qk-card-body fb-md-doc">' + FB.fixLinks(s.html) + '</div></section>';
  }).join('');
  el.innerHTML = head('methodology', 'How The Quant Footballer gets its data, forecasts a match, simulates a season, ranks clubs and players, and where it is wrong. Written for a numerate fan; every constant is the one in the code.' +
    (c ? '' : ' Each competition\'s own settings: pick one in <a href="#/competitions">Competitions</a>, or add <code>?c=</code> here.')) +
    '<div class="fb-md-layout">' + toc + '<div class="fb-md-body"><div id="md-this"></div>' + body + '</div></div>';
  Array.prototype.forEach.call(el.querySelectorAll('.fb-md-toc a[data-target]'), function (a) {
    a.addEventListener('click', function (ev) {
      var t = document.getElementById(a.getAttribute('data-target'));
      if (!t) return;
      ev.preventDefault();
      t.scrollIntoView({ block: 'start' });
      var id = a.getAttribute('data-target').replace(/^method-/, '');
      if (id !== 'this') FB.setHashQuiet('#/model/methodology/' + id + FB.qs(p.query));
    });
  });
  var scrollTo = function () {
    if (!p.key) return;
    var t = document.getElementById('method-' + p.key);
    if (t) setTimeout(function () { if (FB.alive(el)) t.scrollIntoView({ block: 'start' }); }, 30);
  };
  fillLive(el);
  if (!c) { scrollTo(); return; }
  FB.setCompPicker(c.slug);
  FB.set('md-this', FB.loading('lines', 4));
  return FB.compFiles(c.slug, ['meta', 'table', 'bracket']).then(function (d) {
    if (!FB.alive(el)) return;
    FB.set('md-this', competitionCard(c, d.meta, d.table, d.bracket));
    if (!p.key) { var t = document.getElementById('method-this'); if (t && window.scrollY < 10) { /* the card is first in the body */ } }
    scrollTo();
  });
}

// ── glossary ────────────────────────────────────────────────────────────────

function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
/* glossary.json carries the clean wording since the builder pass (b463b937..a7f39783; live and local checked 23 Oct
   2026: no "Edge", "Fair odds", "Fantasy price" or "Odds" group), so it is shown as built. */
function loadGlossary() {
  return FB.load('glossary.json').then(function (g) {
    if (g && (g.groups || []).length) {
      return { groups: g.groups.map(function (grp) { return { name: grp.name, entries: grp.entries || [] }; }),
        model: (g.model || []).length ? g.model : MODEL_TERMS.map(function (t) { return { key: t[0], label: t[1], desc: t[2], group: t[3] }; }), updated_at: g.updated_at };
    }
    var groups = {};
    Object.keys(DESC).forEach(function (k) { (groups.Metrics = groups.Metrics || []).push({ key: k, label: k, desc: DESC[k] }); });
    return { groups: [{ name: 'Metrics', entries: groups.Metrics }], model: MODEL_TERMS.map(function (t) { return { key: t[0], label: t[1], desc: t[2], group: t[3] }; }), updated_at: null };
  });
}
function tags(e) {
  var out = [];
  var key = String(e.key || ''), label = String(e.label || '');
  if (/_90$/.test(key) || /\/90/.test(label) || /per 90/i.test(label)) out.push('per 90');
  if (e.fmt === 'pct' || /_pct$/.test(key)) out.push('%'); else if (e.fmt === '3') out.push('ratio'); else if (e.fmt === 'int') out.push('count');
  if (e.lower) out.push('lower is better');
  if (e.scope === 'gk') out.push('goalkeepers'); else if (e.scope === 'out') out.push('outfield');
  return out.map(function (t) { return '<span class="fb-md-tag' + (t === 'lower is better' ? ' low' : '') + '">' + esc(t) + '</span>'; }).join('');
}
function slugOf(s) { return norm(s).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

function glossary(el, p) {
  el.innerHTML = head('glossary', 'Every metric the site computes and every model term it uses. Percentiles, per-90 rates and the flags on each entry are explained in the <a href="#/model/methodology">methodology</a>.') +
    '<div id="md-gl">' + FB.loading('lines', 8) + '</div>';
  return loadGlossary().then(function (g) {
    if (!FB.alive(el)) return;
    var groups = (g.groups || []).map(function (x) { return { name: x.name, slug: slugOf(x.name), entries: x.entries || [], model: false }; });
    var mg = {};
    (g.model || []).forEach(function (t) { var n = t.group || 'Model'; (mg[n] = mg[n] || []).push(t); });
    var all = groups.concat(Object.keys(mg).map(function (n) { return { name: n, slug: 'model-' + slugOf(n), entries: mg[n], model: true }; }));
    var total = all.reduce(function (s, x) { return s + x.entries.length; }, 0);
    var entry = function (e, isModel) {
      return '<div class="fb-md-entry" id="gl-' + esc(e.key) + '" data-q="' + esc(norm([e.label, e.key, e.desc, e.group].join(' '))) + '"><dt><span class="fb-md-term">' + esc(e.label || e.key) +
        ' <a class="fb-md-anchor" href="#/model/glossary/' + esc(e.key) + '" aria-label="Link to ' + esc(e.label || e.key) + '">#</a></span><span class="fb-md-tags"><code>' + esc(e.key) + '</code>' +
        (isModel ? '<span class="fb-md-tag model">model</span>' : tags(e)) + '</span></dt><dd>' + (e.desc ? esc(e.desc) : '<span class="qk-muted">No definition yet.</span>') + '</dd></div>';
    };
    FB.set('md-gl',
      '<div class="fb-md-glbar">' + FB.toolbar([FB.field('Filter', '<input class="qk-input" id="md-gl-q" type="search" placeholder="xG, pressing, expected points…" autocomplete="off" spellcheck="false">'),
        '<span class="fb-cap" id="md-gl-n">' + total + ' entries' + (g.updated_at ? ' · updated ' + esc(FB.fmtStamp(g.updated_at)) : '') + '</span>']) +
      '<div class="qk-chips fb-md-glidx">' + all.map(function (x) { return '<a class="qk-chip" href="#md-g-' + esc(x.slug) + '" data-group="' + esc(x.slug) + '"' + (x.model ? ' style="--ca:var(--c-1)"' : '') + '>' + esc(x.name) + ' <span class="n">' + x.entries.length + '</span></a>'; }).join('') + '</div></div>' +
      '<div class="fb-md-glgrid">' + all.map(function (x) {
        return '<section class="qk-card fb-md-glgroup" id="md-g-' + esc(x.slug) + '"><div class="qk-card-head"><div class="fb-card-titles"><h3 class="qk-card-title">' + esc(x.name) + '</h3><div class="qk-card-sub">' +
          (x.model ? 'Model term' : /team/i.test(x.name) ? 'Club metrics' : 'Player metrics') + ' · ' + x.entries.length + '</div></div></div><div class="qk-card-body"><dl class="fb-md-dl">' +
          x.entries.map(function (e) { return entry(e, x.model); }).join('') + '</dl></div></section>';
      }).join('') + '</div><div id="md-gl-none" hidden>' + FB.empty('Nothing matches', 'Try a shorter word.') + '</div>');
    var input = el.querySelector('#md-gl-q');
    var entries = Array.prototype.slice.call(el.querySelectorAll('.fb-md-entry'));
    var cards = Array.prototype.slice.call(el.querySelectorAll('.fb-md-glgroup'));
    var filter = function () {
      var q = norm(input.value.trim());
      var shown = 0;
      entries.forEach(function (e) { var hit = !q || e.getAttribute('data-q').indexOf(q) >= 0; e.hidden = !hit; if (hit) shown++; });
      cards.forEach(function (c) { c.hidden = !c.querySelector('.fb-md-entry:not([hidden])'); });
      el.querySelector('#md-gl-none').hidden = shown > 0;
      el.querySelector('#md-gl-n').textContent = q ? shown + ' of ' + total + ' entries' : total + ' entries';
    };
    input.addEventListener('input', filter);
    input.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { input.value = ''; filter(); } });
    Array.prototype.forEach.call(el.querySelectorAll('.fb-md-glidx a'), function (a) {
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        var t = document.getElementById('md-g-' + a.getAttribute('data-group'));
        if (t) { t.hidden = false; t.scrollIntoView({ block: 'start' }); }
      });
    });
    if (p.key) {
      var t = document.getElementById('gl-' + p.key) || document.getElementById('md-g-' + String(p.key).replace(/^g:/, ''));
      if (t) { t.classList.add('hit'); setTimeout(function () { if (FB.alive(el)) t.scrollIntoView({ block: 'center' }); }, 30); }
    }
  });
}

// ── model checks ────────────────────────────────────────────────────────────

function metaComps() { return FB.comps().filter(function (c) { return c.ok; }); }
function calibration(el) {
  el.innerHTML = head('calibration', 'What the models\' own checks say. Every number here is measured on matches the model had not seen when it made the call, or (for the match model) on the matches it was fitted to.') +
    '<div id="md-sure"></div><div id="md-cal">' + FB.loading('chart', 2) + '</div>';
  howSure(el);
  var leagues = metaComps().filter(function (c) { return FB.familyOf(c) === 'league'; });
  return Promise.all([FB.load('value/meta.json'), FB.load('fantasy/meta.json'), Promise.all(leagues.map(function (c) { return FB.compFile(c.slug, 'meta'); }))]).then(function (arr) {
    if (!FB.alive(el)) return;
    var vm = arr[0] || {}, fm = arr[1] || {}, metas = arr[2];
    var html = '';
    // match model calibration by league
    var rowsC = leagues.map(function (c, i) { var m = metas[i] || {}; var cal = m.calibration || {}; return { slug: c.slug, name: c.short_name || c.name, draw: cal.draw_rate, goals: cal.mean_goals, home: cal.home_win_rate, train: m.training_matches, method: (m.model || {}).params_method, dcw: (m.model || {}).dc_weight }; })
      .filter(function (r) { return isNum(r.draw); });
    html += '<section class="fb-sec">' + FB.grid(
      FB.card('The match model, league by league', 'What each league\'s training matches look like: the draw rate and goals per team that shape the Elo side of the blend, and the home-win rate.', FB.chartBox('md-cal-c', Math.max(260, rowsC.length * 26 + 40), 'Draw and home-win rates by league'), { span: 7 }) +
      FB.card('Settings', 'The fitted parameter set and how much of the line is Dixon-Coles.', '<div id="md-cal-t"></div>', { span: 5, flush: true })
    ) + '</section>';
    // value model
    var V = vm.validation || {}, r2 = V.r2 || {};
    if (V.ok) html += '<section class="fb-sec">' + FB.grid(
      FB.card('Player value: does it predict?', 'Out of sample (' + FB.int(V.n_test) + ' of ' + FB.int(V.n_matches) + ' matches, ' + V.folds + ' folds, walking forward from ' + esc(V.first_test_day || '') + '): how much of each match\'s later expected-goal difference (xGD) and goal difference (GD) the line-ups\' values explain.', FB.chartBox('md-cal-v', 280, 'R squared by method'), { span: 7 }) +
      FB.card('Reliability', 'The same players\' numbers in two halves of their minutes (1,800+ minutes): how stable each measure is.', '<div id="md-cal-r"></div>', { span: 5 })
    ) + '</section>';
    // fee model
    var fv = ((vm.fee || {}).validation || {});
    if (fv.cv) html += '<section class="fb-sec">' + FB.card('Fair fees against real fees', 'Cross-validated on ' + FB.int(fv.n) + ' transfers with a published fee: the share of fees within 50% of the prediction and the rank correlation, against a model on value and age only and against the median fee.', FB.chartBox('md-cal-f', 240, 'Fee model checks') + '<div id="md-cal-ft" class="fb-mt"></div>') + '</section>';
    // fantasy backtest
    var B = fm.backtest || {};
    if (B.ok) html += '<section class="fb-sec">' + FB.grid(
      FB.card('Fantasy projections, backtested', FB.int(B.rounds) + ' gameweeks and ' + FB.int(B.player_rounds) + ' player-rounds, each projected with only the data before it. Mean absolute error in points per player per round (lower is better).', FB.chartBox('md-cal-b', 260, 'Fantasy backtest MAE'), { span: 7 }) +
      FB.card('By position', 'Our projection\'s error by position.', FB.chartBox('md-cal-bp', 260, 'Fantasy MAE by position'), { span: 5 })
    ) + (B.calibration_note ? FB.note(esc('Scale: ' + num(B.calibration, 3) + ' — ' + B.calibration_note)) : '') + '</section>';
    FB.set('md-cal', html || FB.empty('No checks published', 'The model checks appear after the next build.'));
    if (rowsC.length) {
      QKC.bar(el.querySelector('#md-cal-c'), { horizontal: true, legend: true, labelWidth: 120, fmt: function (v) { return pct(v); }, valName: 'Share of matches', cats: rowsC.map(function (r) { return r.name; }),
        series: [{ name: 'Draws', color: QK.cssVar('--c-3'), data: rowsC.map(function (r) { return r.draw; }) }, { name: 'Home wins', color: QK.cssVar('--c-4'), data: rowsC.map(function (r) { return r.home; }) }], label: 'Draw and home-win rates by league' });
      FB.table(el.querySelector('#md-cal-t'), [
        { key: 'name', label: 'League', sticky: true, fmt: function (v, r) { return FB.compLink(r.slug, { short: true, q: null }); } },
        { key: 'goals', label: 'Goals/team', num: true, d: 2, fmt: function (v) { return num(v, 2); } },
        { key: 'train', label: 'Matches', num: true },
        { key: 'dcw', label: 'DC weight', num: true, fmt: function (v) { return num(v, 2); } },
        { key: 'method', label: 'Fit', fmt: function (v) { return esc(v || '—'); } }
      ], rowsC, { caption: 'Match model settings by league' });
    }
    if (V.ok) {
      var meth = [['rating', 'Rating only'], ['team', 'Team strength'], ['box', 'Box score'], ['value', 'Our value']];
      QKC.bar(el.querySelector('#md-cal-v'), { legend: true, fmt: function (v) { return num(v, 2); }, valName: 'R², out of sample', cats: meth.map(function (m) { return m[1]; }),
        series: [{ name: 'R² on later xGD', color: QK.cssVar('--c-3'), data: meth.map(function (m) { return (r2.xgd || {})[m[0]]; }) }, { name: 'R² on later GD', color: QK.cssVar('--c-7'), data: meth.map(function (m) { return (r2.gd || {})[m[0]]; }) }], label: 'Value model R squared' });
      var rel = vm.reliability || {};
      FB.set('md-cal-r', QK.pctlBars([
        { label: 'Our value', pctl: (rel.value_r || 0) * 100, value: num(rel.value_r, 2) },
        { label: 'Box score', pctl: (rel.box_r || 0) * 100, value: num(rel.box_r, 2) },
        { label: 'Rating', pctl: (rel.rating_r || 0) * 100, value: num(rel.rating_r, 2) }
      ]) + '<p class="fb-cap">Split-half correlation over ' + FB.int(rel.n_players) + ' players. 1 would be perfectly stable.</p>');
    }
    if (fv.cv) {
      var fm3 = [['model', 'Fee model'], ['value_age_only', 'Value and age only'], ['baseline_median', 'Median fee']].filter(function (x) { return fv.cv[x[0]]; });
      QKC.bar(el.querySelector('#md-cal-f'), { horizontal: true, legend: true, labelWidth: 120, fmt: function (v) { return num(v, 2); }, max: 1, valName: 'Share or correlation', cats: fm3.map(function (x) { return x[1]; }),
        series: [{ name: 'Within 50%', color: QK.cssVar('--c-3'), data: fm3.map(function (x) { return fv.cv[x[0]].within_50pct; }) }, { name: 'Rank correlation', color: QK.cssVar('--c-7'), data: fm3.map(function (x) { return fv.cv[x[0]].spearman; }) }], label: 'Fee model checks' });
      FB.set('md-cal-ft', '<p class="fb-cap">Typical miss: a factor of ' + num(fv.cv.model.error_factor, 1) + ' either way (median ' + FB.money(fv.cv.model.median_abs_eur) + ').' +
        (fv.time_split && fv.time_split.model ? ' Trained up to ' + esc(fv.time_split.train_until) + ' and tested after: ' + pct(fv.time_split.model.within_50pct) + ' within 50%.' : '') + '</p>');
    }
    if (B.ok) {
      var ms = B.methods || {};
      var keys = Object.keys(ms);
      QKC.bar(el.querySelector('#md-cal-b'), { horizontal: true, labels: true, labelWidth: 170, fmt: function (v) { return num(v, 2); }, cats: keys.map(function (k) { return ms[k].label || k; }),
        valName: 'MAE (points per round)', series: [{ name: 'MAE', data: keys.map(function (k) { return ms[k].mae; }) }], colors: keys.map(function (k) { return k === 'model' ? QK.cssVar('--c-1') : QK.cssVar('--c-other'); }), label: 'Fantasy backtest MAE' });
      var bp = (ms.model || {}).by_position || {};
      var pos = ['G', 'D', 'M', 'F'].filter(function (k) { return bp[k]; });
      QKC.bar(el.querySelector('#md-cal-bp'), { labels: true, fmt: function (v) { return num(v, 2); }, cats: pos.map(function (k) { return FB.POS_GROUP[k]; }), valName: 'MAE (points per round)', series: [{ name: 'MAE', data: pos.map(function (k) { return bp[k].mae; }) }], label: 'Fantasy MAE by position' });
    }
  });
}

// ── data coverage ───────────────────────────────────────────────────────────

function coverage(el) {
  el.innerHTML = head('coverage', 'Which seasons are complete, how a season is counted, and what the coverage chips on club and player pages mean.') +
    FB.grid(
      FB.card('One season model', 'How the site counts a season, the same way on every page.', '<div class="fb-md-doc">' +
        '<p><strong>Two frames.</strong> A split season runs July to June and reads <code>2026/27</code>; a calendar season is the year, <code>2026</code>. The Brasileirão, MLS, Liga MX (both halves), Argentina, the Libertadores, the Sudamericana and the other South and North American competitions are calendar competitions; every other club competition is split.</p>' +
        '<p><strong>An edition belongs to the season its matches fall in</strong>, from the median date of its matches, not from the label Sofascore gives it: a super cup played in August opens the new season.</p>' +
        '<p><strong>International football has no season of its own.</strong> A player\'s international matches count in the player\'s own frame by date, the split year turning on 1 August, so a June or July tournament closes the season it ends: a European\'s 2026 World Cup is in their 2025/26, a Brazilian\'s in their 2026. The Club World Cup and the Intercontinental Cup are treated the same way on club pages.</p>' +
        '<p><strong>Year by year adds up.</strong> A player\'s or club\'s season row is the sum of its competitions, so the competitions always add up to the season.</p></div>', { span: 7 }) +
      FB.card('The coverage chips', 'Shown on club and player season rows when a row is not complete.', '<dl class="fb-md-dl">' +
        '<div class="fb-md-entry"><dt><span class="fb-cov full">Full</span></dt><dd>Every finished match of that team in that edition has line-ups. Usually shown as nothing at all.</dd></div>' +
        '<div class="fb-md-entry"><dt><span class="fb-cov partial">Partial · 30/38</span></dt><dd>Some matches have no line-ups yet: the row is a <strong>lower bound</strong>. Hover for why: queued in the hourly backfill, not published by Sofascore, or ties the fetch does not follow.</dd></div>' +
        '<div class="fb-md-entry"><dt><span class="fb-cov totals">Season totals</span></dt><dd>Our line-ups were partial, so Sofascore\'s own season totals for that player and edition stand in; the totals are complete.</dd></div>' +
        '<div class="fb-md-entry"><dt><span class="fb-cov none">No line-ups</span></dt><dd>Results are known but no line-ups exist for that team in that edition.</dd></div></dl>', { span: 5 })
    ) +
    '<section class="fb-sec">' + FB.card('Line-ups this season, by competition', 'Matches with line-ups (which feed player numbers) against matches played in the current edition. A gap means some player rows are lower bounds until the backfill reaches them.', '<div id="md-cov"></div>', { flush: true }) + '</section>' +
    '<section class="fb-sec">' + FB.card('The backfill', 'Why last season can still be filling in.', '<div class="fb-md-doc">' +
      '<p>Player minutes come from match line-ups. Until 17 October 2026 the fetch asked only for the last twelve months of matches, so the first rounds of every 2025/26 league and most of 2025 in the calendar leagues were missing (Brasileirão 2025 player minutes were about 28% of the true totals). The fetch now queues every finished match of every season it holds, newest first: the current season\'s new matches, then the previous seasons of the followed leagues, the continental cups and the rest.</p>' +
      '<p>A match Sofascore answers without line-ups is asked again after one, then seven days; on the third such answer it is marked unavailable for good. While that happens, season rows say <span class="fb-cov partial">Partial</span> or take Sofascore\'s season totals.</p></div>') + '</section>';
  var list = metaComps();
  return Promise.all(list.map(function (c) { return FB.compFile(c.slug, 'meta'); })).then(function (metas) {
    if (!FB.alive(el)) return;
    var rows = list.map(function (c, i) {
      var m = metas[i] || {};
      var played = isNum(m.games_played) ? m.games_played : c.games_played;
      return { slug: c.slug, name: c.name, fam: FB.familyOf(c), season: FB.currentSeason(c).season, played: played, detail: m.detail_matches, share: isNum(m.detail_matches) && played ? Math.min(1, m.detail_matches / played) : null };
    }).filter(function (r) { return isNum(r.played) && r.played > 0; });
    var famLabel = {}; FB.FAMILIES.forEach(function (f) { famLabel[f.key] = f.label; });
    FB.table(el.querySelector('#md-cov'), [
      { key: 'name', label: 'Competition', sticky: true, fmt: function (v, r) { return FB.compLink(r.slug); } },
      { key: 'fam', label: 'Family', fmt: function (v) { return esc(famLabel[v] || v); } },
      { key: 'season', label: 'Season', fmt: function (v) { return esc(v || '—'); } },
      { key: 'played', label: 'Played', num: true },
      { key: 'detail', label: 'With line-ups', num: true },
      { key: 'share', label: 'Coverage', num: true, fmt: function (v) { return isNum(v) ? '<span class="fb-rowbar"><i style="width:' + (v * 100).toFixed(0) + '%;background:' + (v >= 0.97 ? 'var(--st-good)' : v >= 0.8 ? 'var(--st-warn)' : 'var(--st-serious)') + '"></i></span> ' + pct(v) : '—'; } }
    ], rows, { sort: { key: 'share', dir: 'asc' }, maxHeight: 520, caption: 'Line-up coverage by competition' });
  });
}

// ── disclaimer ──────────────────────────────────────────────────────────────

function disclaimer(el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = head('disclaimer', 'The terms of use, the data sources and where to get help with gambling.') +
    FB.card('', '', '<div class="fb-prose">' + (t ? t.innerHTML : '<p>For information and entertainment only; not betting advice.</p>') + '</div>');
}

})(window.FB);
