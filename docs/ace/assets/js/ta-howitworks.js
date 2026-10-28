/* The Quant Ace — "How it works" for fans (round 9, 28 Oct 2026): the top of Model › How it works (#/methodology). What
 * the site does, then one picture per model in plain words:
 *   Elo ratings            our chance against the rating gap (the Elo curve);
 *   serve and return       how a few points more on serve become many more holds (the game formula);
 *   the match forecast     points -> games -> sets -> match, worked through for one example with the exact chain
 *                          (TA.fk.chain, the same code the head-to-head page runs);
 *   draws and the season   the simulation as a flow;
 *   who moves next         the breakout model as a flow.
 * The full methodology (data sources, constants, code paths, fits) follows, folded under "Technical detail" (docs.js).
 * Every chart is computed here from the formulas the models use; nothing is read from a payload.
 * Older-browser rule: no optional chaining, no nullish coalescing. */
(function (TA) {
'use strict';

const esc = s => TA.esc(s);
const pct = (p, d) => (p * 100).toFixed(d === undefined ? 0 : d) + '%';
const elo = d => 1 / (1 + Math.pow(10, -d / 400));
function game(p) { const q = 1 - p; return Math.pow(p, 4) * (1 + 4 * q + 10 * q * q) + 20 * Math.pow(p * q, 3) * p * p / (1 - 2 * p * q); }

function flow(steps) {
  return '<ol class="ta-flow">' + steps.map(s => '<li><span class="ta-flow-k">' + esc(s[0]) + '</span><b>' + esc(s[1]) + '</b>' + (s[2] ? '<span class="ta-flow-s">' + esc(s[2]) + '</span>' : '') + '</li>').join('') + '</ol>';
}
function block(n, kicker, title, text, pic) {
  return '<section class="qk-card ta-hiw"><div class="qk-card-body"><div class="ta-hiw-n qk-outline" aria-hidden="true">' + n + '</div><div class="ta-hiw-t">' +
    '<div class="qk-kicker">' + esc(kicker) + '</div><h3>' + esc(title) + '</h3><p>' + text + '</p></div><div class="ta-hiw-pic">' + pic + '</div></div></section>';
}

function html() {
  const ch = TA.fk && TA.fk.chain;
  const pa = 0.66, pb = 0.62;
  const ha = game(pa), hb = game(pb);
  let m = null;
  try { m = ch && ch.match ? ch.match(pa, pb, 3, 'tb7') : null; } catch (e) { m = null; }
  const intro = QK.explain('The Quant Ace gives a chance to every ATP and WTA tour-level match before the first ball and during it, simulates every draw and the race to the Finals, and rates every player on serve, return and results, overall and on each surface. Five models do the work. Here is each one in plain words, with a picture; the technical detail, every source and every constant, is folded underneath.', { title: 'What the site does.' });
  return '<div class="ta-hiw-wrap">' + intro +
    block(1, 'Elo ratings', 'Who is stronger, and by how much', 'Every result moves two ratings: beat a stronger player and you gain a lot, beat a weaker one and you gain a little. Each player has one rating overall and one per surface, so a clay specialist can sit far higher on clay. The gap between two ratings turns into a chance: 100 points makes the stronger player about a ' + pct(elo(100)) + ' favourite, 200 points about ' + pct(elo(200)) + '.',
      '<div id="hiw-elo" class="qk-chart" style="--h:260px" role="img" aria-label="Our chance against the Elo gap"></div>') +
    block(2, 'Serve and return', 'How a player wins, read from the scores', 'Most matches publish only the score. From who held and who broke, set by set, and against whom, we infer how often each player wins a point on serve and on return. Small differences there are huge: a player who wins 66% of serve points holds ' + pct(ha) + ' of service games, one who wins 62% holds ' + pct(hb) + '.',
      '<div id="hiw-hold" class="qk-chart" style="--h:260px" role="img" aria-label="Hold percentage against serve points won"></div>') +
    block(3, 'The match forecast', 'Points become games, games sets, sets a match', 'We blend the Elo chance with the serve and return model, then play the match out exactly, point by point, every possible score at once. The same chain gives the likeliest scores, the games we expect, and the live chance after every game.',
      flow([['Points', 'A ' + pct(pa) + ' · B ' + pct(pb), 'serve points won'], ['Games', 'A holds ' + pct(ha) + ' · B ' + pct(hb), 'from the points'], ['Sets', m ? 'A in straight sets ' + pct((m.sets || {})['2-0'] || 0) : 'every set score', 'tiebreaks included'], ['Match', m ? 'A ' + pct(m.p) + ' to win' : 'the chance to win', 'best of three']])) +
    block(4, 'Draws and the season', 'Every path through the draw', 'For a tournament in play we play the rest of the draw 20,000 times with the match forecast, so each player gets a chance of every round and of the title. For the season we play out every remaining tournament 10,000 times: the race to the Finals and the year-end No. 1.',
      flow([['The draw', 'Who is left, who meets whom', ''], ['Each match', 'Our chance, round by round', ''], ['20,000 runs', 'Play it all out', ''], ['The answer', 'Chance of each round and the title', '']])) +
    block(5, 'Who moves next', 'Where the ranking is heading', 'The ranking adds up a year of points, so it trails the level. Our breakout model reads the gap between a player’s ranking and our rating, age, form, time out and the points about to drop off, and forecasts the ranking six and twelve months on. Its record is on Model › Who moves next.',
      flow([['Now', 'Ranking and our rating', ''], ['Signals', 'Age, form, time out, points to defend', ''], ['Forecast', 'The ranking in 6 and 12 months', ''], ['Checked', 'Against what happened, every season since 2010', '']])) +
    '</div>';
}

function draw(root) {
  const el1 = root.querySelector('#hiw-elo'), el2 = root.querySelector('#hiw-hold');
  if (el1 && window.QKC) {
    const xs = []; for (let d = 0; d <= 400; d += 10) xs.push(d);
    QKC.line(el1, { xType: 'value', x: xs, series: [{ name: 'Our chance for the stronger player', data: xs.map(d => Math.round(1000 * elo(d)) / 10), color: QK.cssVar('--signal') || '#7d93ff' }],
      xName: 'Elo gap (points)', yName: 'Chance to win (%)', yMin: 50, yMax: 100, xFmt: v => String(v), yFmt: v => v + '%', ref: { x: 100, label: '100 points: ' + pct(elo(100)) }, endLabels: false, label: 'Our chance against the Elo gap' });
  }
  if (el2 && window.QKC) {
    const xs = []; for (let p = 50; p <= 80; p += 1) xs.push(p);
    QKC.line(el2, { xType: 'value', x: xs, series: [{ name: 'Service games held', data: xs.map(p => Math.round(1000 * game(p / 100)) / 10), color: QK.cssVar('--signal') || '#7d93ff' }],
      xName: 'Serve points won (%)', yName: 'Service games held (%)', yMin: 50, yMax: 100, xFmt: v => v + '%', yFmt: v => v + '%', ref: { x: 64, label: 'ATP average, about 64%' }, endLabels: false, label: 'Hold percentage against serve points won' });
  }
}

TA.howItWorks = { html: html, draw: draw };
})(window.TA);
