/* The Quant Hardwood — Model ▸ How it works, for fans (round 9, 28 Oct 2026). The tab opens with what the site does
 * and one diagram per model in plain words (a flow of boxes: what goes in, what the model does, what comes out, and
 * where you see it); the technical document (data sources, code paths, endpoints, constants: docs.js) is folded under
 * "Technical detail". It never leads with markets or closing lines.
 *   HW.method.html(L) -> the fan opening (HTML)
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (HW) {
'use strict';

const esc = HW.esc;

/* [kicker, title, plain words, steps [in, model, out], where (route, label)] */
const MODELS = [
  ['Game model', 'Who wins tonight', 'Every team has a rating: how many points per 100 trips it scores and allows, adjusted for who it played. For a game we add home court, rest, travel and who is injured, turn that into an expected margin, and the margin into a win chance. A 70% favourite still loses 3 times in 10.',
    ['Team ratings, home court, rest and travel, the injury report', 'Expected margin and its spread', 'Our win chance for each side'], ['games', 'Games']],
  ['Season simulation', 'Who makes the playoffs', 'We play out the rest of the season 20,000 times with the game model, including the play-in and every playoff series, with a little extra uncertainty because ratings drift. Playoffs 60% means a playoff place in about 12,000 of the 20,000 seasons.',
    ['Every remaining game, today’s ratings', '20,000 simulated seasons, play-in and playoffs', 'Playoff, seed and title chances, projected wins'], ['standings?tab=chances', 'Standings ▸ Chances']],
  ['Player impact (HPM)', 'Who helps their team', 'How the team does with a player on the floor and off it, from every play since about 2017, blended with what the box score says. HPM is points per 100 trips added over an average player; wins above replacement (WAR) turns that and the minutes into wins.',
    ['Who was on the floor for every possession, and the box score', 'Impact per 100 possessions (HPM), offence and defence', 'HPM, WAR and the percentiles against the same role'], ['scout', 'Scouting Room']],
  ['Live win chance', 'Who wins from here', 'During a game, the chance moves with the score, the clock, who has the ball and how strong the two teams are. Before the tip it starts from our pre-game call.',
    ['Score, time left, possession, the pre-game margin', 'A model fitted on past play-by-play', 'The live chance, and the swing of every play'], ['games', 'Game pages']],
  ['Shot quality (xPTS)', 'Good shots, or good shooting', 'Every located shot gets the points an average shooter would expect from that spot and that kind of shot. Scoring more than that is shot-making; taking better shots is shot selection.',
    ['Where the shot came from, its type, the clock', 'Expected points of each shot', 'Shot-making (points over expected) and shot charts'], ['scout?view=chart', 'Scouting Room ▸ Chart']],
  ['Award races', 'Who wins the awards', 'Our chance for each award from what has decided past votes (team success, the box score, our impact numbers, games played), fitted on earlier winners and projected to the season’s end with the season simulation.',
    ['This season’s numbers for every eligible player', 'A model of past votes', 'Our chance for each award'], ['standings?tab=races', 'Standings ▸ Races']],
  ['Who moves next', 'Who will be somewhere else', 'From who has changed teams since 1997 (age, years in the league, role and value, how long with the team), our chance a player is gone by next season, and how: traded, waived or an off-season move. No contract data: no source we may use has it.',
    ['Every player’s age, role, value and history of moves', 'A model checked on seasons it never saw', 'The chance of moving, by how'], ['value?tab=next', 'Value ▸ Who moves next']],
  ['Value and trades', 'What a player is worth', 'Four seasons of wins above replacement, with ageing and our uncertainty, and later seasons counted for a little less. Trades are graded on the share of that value each side got.',
    ['WAR, age and minutes', 'Four-season value with its range', 'Values, trade grades and the trade simulator'], ['value', 'Value & Moves']]
];

function flow(steps) {
  const lab = ['What goes in', 'What the model does', 'What you see'];
  return '<div class="hw-flow" role="img" aria-label="' + esc(steps.join(', then ')) + '">' + steps.map((s, i) => '<div class="hw-flow-s s' + i + '"><small>' + lab[i] + '</small><span>' + esc(s) + '</span></div>' + (i < steps.length - 1 ? '<i aria-hidden="true">→</i>' : '')).join('') + '</div>';
}

function html(L) {
  const LN = HW.leagueName(L);
  return '<section class="qk-section">' + QK.sectionHead({ kicker: 'How it works', title: 'What this site does', sub: 'The Quant Hardwood turns every ' + LN + ' game, possession and shot into forecasts, ratings and player numbers you can read in plain English. Here is each model in one picture: what goes in, what it does, and where you see it. The full detail (sources, formulas and every constant) is under “Technical detail” at the foot.' }) +
    '<div class="hw-method">' + MODELS.map(m => '<article class="qk-card hw-method-c"><div class="qk-card-body"><div class="hw-method-k">' + esc(m[0]) + '</div><h3>' + esc(m[1]) + '</h3><p>' + esc(m[2]) + '</p>' + flow(m[3]) +
      '<a class="qk-link" href="#/' + L + '/' + esc(m[4][0]) + '">See it on ' + esc(m[4][1]) + ' →</a></div></article>').join('') + '</div>' +
    QK.explain('Every forecast here is checked against what happened, on games the model never saw. The record is on <a class="qk-link" href="' + esc(HW.href(L, 'model') + '?tab=calibration') + '">How we’re doing</a>.', { title: 'How sure are we?' }) + '</section>';
}

HW.method = { html: html, MODELS: MODELS };
})(window.HW);
