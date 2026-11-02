/* The Quant Scrum — Model: how it works, how we're doing (the ladder against our World Rugby rebuild, calibration, the
 * forecast log), the lab (home advantage, scoring and bonus points through the years, what wins tests), history and
 * records, the glossary and the terms. Reads <S>/model.json, <S>/lab.json, <S>/records.json, glossary.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = SC.ui;
var TABS = [['method', 'How it works'], ['doing', 'How we’re doing'], ['lab', 'Lab'], ['records', 'Records'], ['glossary', 'Glossary'], ['terms', 'Terms']];
var RUNG = { wr: 'Our World Rugby rebuild (the baseline)', elo: 'Our rating with home advantage', unc: '+ uncertainty (Glicko-style)', ctx: '+ travel and rest', kal: '+ the tier-three fix: Kalman learning rates, a blow-out clip, a World Rugby anchor', split: '+ attack and defence', hybrid: 'Hybrid: the rebuild’s chance where a tier-three side plays (chosen after the test years)', hybrid_unc: 'The old hybrid (in use until 2 November 2026)' };
var VAL = { m: 'Metres carried', car: 'Carries', cb: 'Clean breaks', db: 'Defenders beaten', off: 'Offloads', pas: 'Passes', tk: 'Tackles', mt: 'Missed tackles',
  toc: 'Turnovers conceded', ko: 'Knock-ons', pc: 'Penalties conceded', yc: 'Yellow cards', rc: 'Red cards', lo: 'Lineouts won', rk: 'Rucks won', kfh: 'Kicks from hand' };

function method(S, d) {
  var p = d.params || {}, R = d.report || {};
  var ch = R.chosen || 'elo';
  return '<div class="sc-prose">' +
    '<h2>The data</h2><p>Every result, line-up and match statistic comes from ESPN’s public data: ' + (S === 'men' ? 'men’s tests from 1995 (the Five and Six Nations, the Tri Nations and Rugby Championship, World Cups, Lions tours, the new Nations Championship and the summer and autumn tests), with team and player statistics from about 2006' : 'the women’s tests the feed carries') +
    '. Smaller tests are thinner in the early years, so counts of tests are not official caps. World Rugby’s own feeds are not used (their terms are for personal use only).</p>' +
    '<h2>Our rating</h2><p>Each side has a rating in points: how much it would beat an average test side by on a neutral ground. It is split into attack (points scored above average) and defence (points kept out). Before a test, the expected score for each side is half the era’s average total, plus its attack, minus the other side’s defence, plus half the home advantage (minus half for the away side).</p>' +
    '<p>Home advantage is worth <b>' + SC.f(p.H, 1) + ' points</b> at a home ground (none at a neutral venue)' + (p.c_km || p.c_tz || p.c_rest ? ', plus travel (' + SC.f(p.c_km, 2) + ' points per log-thousand kilometres the away side travels further, ' + SC.f(p.c_tz, 2) + ' per time zone) and rest (' + SC.f(p.c_rest, 2) + ' points per extra week since the last test)' : '; travel and rest did not earn a place on the test years') + '. After each test, both sides move toward the score. ' + (p.kal ? 'How far depends on how sure we are of each rating (a Kalman filter): every side carries an uncertainty, wide for a new side (a spread of about ' + Math.round(Math.sqrt(p.v0 || 0)) + ' points) and narrowing with every test, and a side moves by its own uncertainty over the two sides’ plus the test’s own spread. So a new side learns fast against an established one, while a test between two unproven sides moves both much less. Final margins count up to ' + SC.f(p.mclip, 0) + ' points (a 117-3 counts as a 60-point win), any surprise is capped at ' + SC.f(p.cap, 0) + ', and between years every rating shrinks ' + Math.round((p.revert || 0) * 100) + '% toward a target halfway between its tier’s mean and its World Rugby points (our rebuild, results to date only) put on our scale.' :
      SC.f(p.k, 2) + ' of each point of surprise (' + SC.f(p.k_new, 2) + ' for a side’s first ' + (p.n_new || 8) + ' tests), with any surprise capped at ' + SC.f(p.cap, 0) + ' points so a 90-0 against a minnow teaches little. Between years every rating shrinks ' + Math.round((p.revert || 0) * 100) + '% toward its tier’s mean.') + '</p>' +
    '<p><b>Who gets a rank.</b> A rating is only pinned down against the sides a team actually plays, so we rank a side only with five or more tests rated and a tie to the main pool (a tier-one or tier-two side, or three tests against one in four years). The rest carry a provisional rating and no rank. The Lions and other invitational sides are not rated in the table.</p>' +
    '<h2>Win, draw and loss</h2><p>Margins land around our expected margin with a spread that widens with the mismatch: ' + SC.f(p.s0, 1) + ' points for a level test plus ' + SC.f(p.s1, 2) + ' per point of expected margin. A draw is a final margin inside half a point; that gives the 2-3% of tests that are drawn. The total uses the same expected scores with its own spread.</p>' +
    '<h2>Tournaments</h2><p>Every remaining match is played out 20,000 times: a margin and a total from our model, tries from a try model fitted on the past (so the bonus points follow the score), then the real tables, tie-breakers and formats: the Six Nations’ Grand Slam bonus and Triple Crown, the Nations Championship’s finals weekend, and the 2027 World Cup’s six pools, the four best thirds and World Rugby’s permutation table for the round of 16.</p>' +
    '<h2>World Rugby rankings</h2><p>We rebuild the official rankings with the published points exchange: the winner takes (10 − rating gap)/10 points from the loser, the gap capped at 10, half as much again for a win by more than 15, double at a World Cup; before 1 July 2026 the home side’s rating counted 3 points higher. Our live table starts from the published points of 28 September 2026 and adds every result since.</p>' +
    '<h2>Players</h2><p>Minutes come from the substitutions. Rates are per 80 minutes over the last two years, pulled toward the position average as if 240 more minutes at that average had been played. <b>Scrum value</b> is ours: a regression of the final margin on the two sides’ process statistics (carries, metres, breaks, tackles, turnovers, penalties and the rest), fitted on 2004-2018, gives each action its worth in points; a player’s value is that worth per 80 minutes above a replacement-level player in the same position group (the 20th percentile of regulars), plus goal kicking above an average kicker.</p>' +
    '<h2>Honest scoring</h2><p>Every setting is chosen on 2004-2018. The years from 2019 are scored once. A part of the model goes in only when it beats the simpler version on those sealed years: the 95% interval of the per-test log-loss difference must exclude zero, with calibration no worse. The current model is the <b>' + esc(RUNG[ch] || ch) + '</b> rung of that ladder.' +
    (ch === 'kal' ? ' Until 2 November 2026 our rating lost to our World Rugby rebuild wherever a tier-three side played: two unproven sides that only met each other could run up huge ratings (a 117-3 win put Austria fifth). The fix (the uncertainty-aware learning rate, the blow-out clip and the World Rugby anchor) was tuned on 2004-2018 like everything else and then scored once on the test years, where it beat the old rung clearly; our rating is now level with the rebuild overall, so the old hybrid (the rebuild’s chance for tier-three tests) no longer earns its place.' : '') +
    (ch === 'hybrid' ? ' Honestly: on the test years our rating alone loses to our World Rugby rebuild. It is level on tests between tier-one sides and better on tier one against tier two, but much worse wherever a tier-three side plays, and the development years held only ten such tests, so nothing in our rating was ever tuned for them. For those tests the chance now comes from the rebuild; the margin and total stay ours. That choice was made after seeing the test years, so we show its score as after the fact, not sealed. The details are under How we’re doing.' : '') + '</p></div>';
}

function doing(el, S, d) {
  var R = d.report || {}, rungs = R.rungs || {}, pr = R.paired || {};
  var rows = ['wr', 'elo', 'unc', 'ctx', 'kal', 'split', 'hybrid', 'hybrid_unc'].filter(function (k) { return rungs[k]; }).map(function (k) {
    var r = rungs[k], dv = r.dev || {}, ts = r.test || {};
    return [{ v: k, html: esc(RUNG[k]) + (R.chosen === k ? ' <span class="qk-bchip volt">In use</span>' : '') }, { v: dv.logloss, html: SC.f(dv.logloss, 4) }, { v: dv.brier, html: SC.f(dv.brier, 4) },
      { v: ts.logloss, html: '<b>' + SC.f(ts.logloss, 4) + '</b>' }, { v: ts.brier, html: SC.f(ts.brier, 4) }, { v: (r.cal_test || {}).ece, html: SC.f((r.cal_test || {}).ece, 3) }, { v: ts.n, html: fmt.num(ts.n || 0) }];
  });
  var pair = function (k, lab) {
    var x = pr[k];
    if (!x || !x.n) return '';
    return '<li><b>' + esc(lab) + ':</b> ' + SC.signed(x.diff, 4) + ' log loss a test (95% interval ' + SC.signed(x.lo, 4) + ' to ' + SC.signed(x.hi, 4) + ', ' + fmt.num(x.n) + ' tests) — ' + (x.post_hoc ? (x.better ? 'better, chosen after the fact.' : x.lo > 0 ? 'worse.' : 'level.') : x.better ? 'better, promoted.' : x.lo > 0 ? 'worse, not promoted.' : 'not clearly better, not promoted.') + '</li>';
  };
  var tot = R.total || {}, tr = (R.tries || {}).test || {};
  el.innerHTML = '<div id="md-doing"></div>' + U.sec('The ladder', 'Each part has to earn its place', 'Scores on the development years (' + (R.dev || []).join('-') + ', where the settings were chosen) and on the sealed test years (' + (R.test || []).join('-') + '). Lower is better. A three-way coin flip scores 1.10 log loss.',
    U.card('', '', U.table([{ label: 'Model', align: 'left' }, { label: 'Dev log loss' }, { label: 'Dev Brier' }, { label: 'Test log loss' }, { label: 'Test Brier' }, { label: 'Calibration error' }, { label: 'Tests' }], rows, { cls: 'sc-table' }), { flush: true }) +
    '<ul class="sc-pairs">' + pair('elo_vs_wr', 'Our rating against the World Rugby rebuild') + pair('unc_vs_elo', 'Uncertainty in the spread') + pair('ctx_vs_unc', 'Travel and rest') + pair('kal_vs_best', 'The tier-three fix') + pair('split_vs_best', 'Attack and defence') + pair('best_vs_wr', 'The model in use against the World Rugby rebuild') + pair('hybrid_vs_best', 'The hybrid against the sealed choice (after the fact)') + pair('hybrid_vs_hybrid_unc', 'The hybrid on the new rating against the old hybrid (after the fact)') + pair('hybrid_vs_wr', 'The hybrid against the rebuild (after the fact)') + '</ul>' +
    QK.explain('<b>Totals and tries.</b> Our expected total misses by ' + SC.f(tot.mae_test, 1) + ' points a test on the test years, against ' + SC.f(tot.mae_test_baseline, 1) + ' for the long-run average. ' +
      (tr.n ? 'The try model (tries from our expected points) beats a flat try rate by ' + SC.f(-tr.diff, 4) + ' log loss a side (interval ' + SC.signed(-tr.hi, 4) + ' to ' + SC.signed(-tr.lo, 4) + '), so it drives the bonus points in our simulations.' : '')));
  var cal = d.calibration || {};
  QK.doing(QK.$('#md-doing', el), { record: d.record ? { n: d.record.n, won: d.record.won, expected: d.record.expected, days: 0 } : null,
    bins: cal.bins, n: cal.n, league: S === 'men' ? 'Men’s' : 'Women’s', span: cal.span, subject: 'the home side', unit: 'tests' });
  // the forecast log
  var log = d.log || [];
  el.insertAdjacentHTML('beforeend', U.sec('Forecast log', 'Every call, as published', 'Our chance for each test as it stood before kick-off, frozen there, and the result. Calls from before this log started are on the match pages (made the same way, from results up to the day).',
    log.length ? U.card('', '', U.table([{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Away', align: 'left' }, { label: 'Home win' }, { label: 'Draw' }, { label: 'Away win' }, { label: 'Result' }],
      log.map(function (r) { return [{ v: r.date, html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + esc(SC.date(r.date)) + '</a>' }, { v: SC.tname(S, r.home), html: U.teamEnt(S, r.home) }, { v: SC.tname(S, r.away), html: U.teamEnt(S, r.away) },
        U.heat(r.p[0], 0), U.heat(r.p[1], 0), U.heat(r.p[2], 0), { v: isNum(r.hs) ? r.hs - r.as : -999, html: isNum(r.hs) ? r.hs + '–' + r.as : '<span class="qk-muted">to come</span>' }]; }), { cls: 'sc-table', maxHeight: 560 }), { flush: true }) : QK.empty('The log starts with the next test', 'Each forecast is saved before kick-off and never changed.')));
  // by year
  var by = d.by_year || [];
  if (by.length) {
    el.insertAdjacentHTML('beforeend', U.card('Year by year', 'Log loss of our pre-match chances each calendar year (lower is better).', U.chart('md-years', 260, 'Log loss by year')));
    if (window.QKC) QKC.bar(QK.$('#md-years', el), { cats: by.map(function (b) { return String(b.y); }), series: [{ name: 'Log loss', data: by.map(function (b) { return b.logloss; }), color: 'var(--c-1)' }], valName: 'Log loss per test', catName: 'Year' });
  }
  U.wire(el);
}

function posTable(rows) {
  var keys = [['pc', 'Penalties /80', 2], ['cards', 'Cards /80', 3], ['tkpct', 'Tackle success', 'pct'], ['mt', 'Missed tackles /80', 2], ['inv', 'Involvements /80', 1], ['ko', 'Knock-ons /80', 2]];
  var f = function (v, d) { return d === 'pct' ? Math.round(v * 100) + '%' : Number(v).toFixed(d); };
  return U.table([{ label: 'Position group', align: 'left' }, { label: 'Regulars' }].concat(keys.map(function (k) { return { label: k[1] }; })),
    rows.map(function (r) { return [{ v: r.label, html: esc(r.label) }, { v: r.n, html: String(r.n) }].concat(keys.map(function (k) {
      var q = r[k[0]];
      return q ? { v: q[1], html: '<b>' + f(q[1], k[2]) + '</b> <span class="qk-muted">' + f(q[0], k[2]) + '–' + f(q[2], k[2]) + '</span>' } : { v: -1, html: '—' };
    })); }), { cls: 'sc-table dense' });
}

function lab(el, S, d) {
  var ys = d.years || [];
  var v = (d.value || {}).weights || {};
  var vk = Object.keys(v).sort(function (a, b) { return v[b] - v[a]; });
  el.innerHTML = '<div class="qk-g2">' + U.card('Home advantage', 'The share of tests the home side wins, and its average margin, by year (neutral venues left out).', U.chart('lb-home', 300, 'Home advantage by year')) +
    U.card('Points and tries', 'Points a test and tries a test, by year.', U.chart('lb-pts', 300, 'Points and tries by year')) + '</div>' +
    '<div class="qk-g2">' + U.card('Bonus points', 'How often a side scores four tries, and how often a test ends within seven points.', U.chart('lb-bp', 300, 'Bonus-point rates by year')) +
    U.card('How close are tests?', 'Final margins since 2010 (60 means 60 or more).', U.chart('lb-margin', 300, 'Margin distribution')) + '</div>' +
    (d.territory && d.territory.terr ? '<div class="qk-g2">' + U.card('Territory into points', 'Every side in every test with team statistics since 2015: points scored and how often it won, by its share of territory (five-point bins). Territory explains ' +
      (isNum(d.territory.terr.r2) ? Math.round(100 * d.territory.terr.r2) + '% of the variation in points' : 'little of the points') + '; what a side does in the opposition half matters more.', U.chart('lb-terr', 300, 'Points and wins by territory')) +
      U.card('Possession into points', 'The same for possession' + (d.territory.poss && isNum(d.territory.poss.r2) ? ' (it explains ' + Math.round(100 * d.territory.poss.r2) + '% of the variation in points)' : '') + '. More of the ball is not more points by itself.', U.chart('lb-poss', 300, 'Points and wins by possession')) + '</div>' : '') +
    ((d.setpiece || []).length ? '<div class="qk-g2">' + U.card('The set piece and the breakdown', 'Share of own scrums, lineouts and rucks won, by year, every test with team statistics.', U.chart('lb-sp', 300, 'Set-piece success by year')) +
      U.card('Turnovers, steals and penalties', 'Per side per test, by year.', U.chart('lb-to', 300, 'Turnovers and penalties by year')) + '</div>' : '') +
    ((d.positions || []).length ? U.card('Discipline, tackling and work by position', 'Regulars (160+ minutes in the last two years), shrunk per-80 rates: the middle half of each position group (25th to 75th percentile) with the median.', posTable(d.positions), { flush: true }) : '') +
    (vk.length ? U.card('What wins tests', 'Points each action is worth to the final margin, from our value model (fitted on 2004-2018; ' + ((d.value || {}).r2_test !== undefined ? 'it explains ' + Math.round(100 * (d.value.r2_test || 0)) + '% of the margin on the test years' : '') + '). This is what Scrum value adds up.',
      U.chart('lb-value', 420, 'Value of each action')) : '');
  if (!window.QKC) return;
  var x = ys.map(function (y) { return String(y.y); });
  QKC.line(QK.$('#lb-home', el), { x: x, series: [{ name: 'Home win %', data: ys.map(function (y) { return isNum(y.home_win) ? y.home_win * 100 : null; }), color: 'var(--c-1)' }], yName: 'Home side won (%)', xName: 'Year', endLabels: false, ref: { y: 50, label: 'Even' } });
  QKC.line(QK.$('#lb-pts', el), { x: x, series: [{ name: 'Points a test', data: ys.map(function (y) { return y.pts; }), color: 'var(--c-1)' }, { name: 'Tries ×5', data: ys.map(function (y) { return isNum(y.tries) ? y.tries * 5 : null; }), color: 'var(--c-4)' }], yName: 'Points (tries × 5)', xName: 'Year' });
  QKC.line(QK.$('#lb-bp', el), { x: x, series: [{ name: 'Try bonus', data: ys.map(function (y) { return isNum(y.tbp) ? y.tbp * 100 : null; }), color: 'var(--c-1)' }, { name: 'Within 7', data: ys.map(function (y) { return isNum(y.lbp) ? y.lbp * 100 : null; }), color: 'var(--c-2)' }], yName: 'Share of sides / tests (%)', xName: 'Year' });
  var mg = d.margins || [];
  QKC.bar(QK.$('#lb-margin', el), { cats: mg.map(function (m) { return String(m[0]); }), series: [{ name: 'Tests', data: mg.map(function (m) { return m[1]; }), color: 'var(--c-1)' }], valName: 'Tests', catName: 'Final margin (points)' });
  var conv = function (id, key, lab) {
    var b = ((d.territory || {})[key] || {}).bins || [];
    if (b.length < 3 || !QK.$(id, el)) return;
    QKC.line(QK.$(id, el), { x: b.map(function (r) { return r[0] + '%'; }), series: [{ name: 'Points scored', data: b.map(function (r) { return r[2]; }), color: 'var(--c-1)' }, { name: 'Won (%)', data: b.map(function (r) { return Math.round(r[3] * 1000) / 10; }), color: 'var(--c-4)' }],
      yName: 'Points a test / tests won (%)', xName: lab + ' share (five-point bins)' });
  };
  conv('#lb-terr', 'terr', 'Territory');
  conv('#lb-poss', 'poss', 'Possession');
  var sp = d.setpiece || [];
  if (sp.length && QK.$('#lb-sp', el)) {
    var xs = sp.map(function (y) { return String(y.y); });
    QKC.line(QK.$('#lb-sp', el), { x: xs, series: [{ name: 'Scrums', data: sp.map(function (y) { return isNum(y.scrum) ? y.scrum * 100 : null; }), color: 'var(--c-1)' }, { name: 'Lineouts', data: sp.map(function (y) { return isNum(y.lineout) ? y.lineout * 100 : null; }), color: 'var(--c-2)' },
      { name: 'Rucks', data: sp.map(function (y) { return isNum(y.ruck) ? y.ruck * 100 : null; }), color: 'var(--c-3)' }], yName: 'Own ball won (%)', xName: 'Year' });
    QKC.line(QK.$('#lb-to', el), { x: xs, series: [{ name: 'Turnovers won', data: sp.map(function (y) { return y.to_won; }), color: 'var(--c-1)' }, { name: 'Penalties conceded', data: sp.map(function (y) { return y.pens; }), color: 'var(--c-2)' },
      { name: 'Lineout steals', data: sp.map(function (y) { return y.steals; }), color: 'var(--c-3)' }], yName: 'Per side per test', xName: 'Year' });
  }
  if (vk.length) QKC.bar(QK.$('#lb-value', el), { cats: vk.map(function (k) { return VAL[k] || k; }), series: [{ name: 'Points per action', data: vk.map(function (k) { return v[k]; }), color: 'var(--c-1)' }], horizontal: true, diverging: true, valName: 'Points of margin per action', catName: 'Action', labels: true, fmt: function (x) { return SC.signed(x, 2); } });
}

function records(el, S, d) {
  var m = function (r) { return [{ v: r.date, html: '<a href="' + esc(SC.matchHref(S, r.id)) + '">' + esc(SC.date(r.date)) + '</a>' }, { v: SC.tname(S, r.home), html: U.teamEnt(S, r.home) }, { v: r.hs - r.as, html: r.hs + '–' + r.as }, { v: SC.tname(S, r.away), html: U.teamEnt(S, r.away) }, { v: r.comp, html: esc(SC.compName(r.comp)) }]; };
  var mc = [{ label: 'Date', align: 'left' }, { label: 'Home', align: 'left' }, { label: 'Score' }, { label: 'Away', align: 'left' }, { label: 'Competition', align: 'left' }];
  var pc = [{ label: 'Player', align: 'left' }, { label: 'Side', align: 'left' }, { label: 'Tests' }, { label: 'Points' }, { label: 'Tries' }];
  var p = function (r) { return [{ v: r.n, html: '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.n) + '</a>' }, { v: SC.tname(S, r.team), html: U.teamEnt(S, r.team, { abbr: true }) }, { v: r.caps, html: String(r.caps) }, { v: r.pts, html: String(r.pts) }, { v: r.tries, html: String(r.tries) }]; };
  var g = function (r) { return [{ v: r.v, html: '<b>' + r.v + '</b>' }, { v: r.n, html: '<a href="' + esc(SC.playerHref(S, r.id)) + '">' + esc(r.n) + '</a>' }, { v: SC.tname(S, r.team), html: U.teamEnt(S, r.team, { abbr: true }) }, { v: SC.tname(S, r.opp), html: 'v ' + U.teamEnt(S, r.opp, { abbr: true }) }, { v: r.date, html: '<a href="' + esc(SC.matchHref(S, r.mid)) + '">' + esc(SC.date(r.date)) + '</a>' }]; };
  var gc = [{ label: '' }, { label: 'Player', align: 'left' }, { label: 'For', align: 'left' }, { label: 'Against', align: 'left' }, { label: 'Date', align: 'left' }];
  el.innerHTML = U.note('Records in our data: ' + fmt.num(d.n || 0) + ' tests from ' + esc(SC.date((d.span || [])[0])) + ' to ' + esc(SC.date((d.span || [])[1])) + '. Older and smaller tests are missing, so these are records of what our source carries, not the all-time books.') +
    '<div class="qk-g2">' + U.card('Biggest wins', '', U.table(mc, (d.biggest_wins || []).map(m), { cls: 'sc-table' }), { flush: true }) + U.card('Highest scoring', '', U.table(mc, (d.highest_scoring || []).map(m), { cls: 'sc-table' }), { flush: true }) + '</div>' +
    '<div class="qk-g2">' + U.card('Longest winning runs', '', U.table([{ label: 'Side', align: 'left' }, { label: 'Wins' }, { label: 'From', align: 'left' }, { label: 'To', align: 'left' }], (d.win_runs || []).map(function (r) { return [{ v: SC.tname(S, r.team), html: U.teamEnt(S, r.team) }, { v: r.n, html: '<b>' + r.n + '</b>' }, { v: r.from, html: esc(SC.date(r.from)) }, { v: r.to, html: esc(SC.date(r.to)) }]; }), { cls: 'sc-table' }), { flush: true }) +
    U.card('Most tests', '', U.table(pc, (d.most_caps || []).map(p), { cls: 'sc-table', maxHeight: 520 }), { flush: true }) + '</div>' +
    '<div class="qk-g2">' + U.card('Most points', '', U.table(pc, (d.most_points || []).map(p), { cls: 'sc-table', maxHeight: 520 }), { flush: true }) + U.card('Most tries', '', U.table(pc, (d.most_tries || []).map(p), { cls: 'sc-table', maxHeight: 520 }), { flush: true }) + '</div>' +
    '<div class="qk-g2">' + U.card('Most points in a test', '', U.table(gc, (d.match_points || []).map(g), { cls: 'sc-table' }), { flush: true }) + U.card('Most tries in a test', '', U.table(gc, (d.match_tries || []).map(g), { cls: 'sc-table' }), { flush: true }) + '</div>';
  U.wire(el);
}

SC.route('model', function (page, P) {
  var S = P.S, keys = TABS.map(function (t) { return t[0]; }), tab = U.tab(P, keys, 'method');
  page.innerHTML = U.head('Model', 'How the numbers are made, how well they have done, and the bigger picture.', SC.SNAME[S]) +
    U.tabs(TABS.map(function (t, i) { return { key: t[0], label: t[1], href: SC.href(S, 'model', null, i ? 'tab=' + t[0] : '') }; }), tab) + '<div id="md-body">' + QK.skeleton('lines', 6) + '</div>';
  var body = QK.$('#md-body', page);
  if (tab === 'terms') { var t = document.getElementById('disclaimer-template'); body.innerHTML = t ? t.innerHTML : ''; return; }
  if (tab === 'glossary') return SC.load('glossary.json').then(function (g) {
    if (!U.alive(body)) return;
    body.innerHTML = SC.ok(g) ? '<dl class="sc-gloss">' + (g.terms || []).map(function (x) { return '<dt>' + esc(x.t) + '</dt><dd>' + esc(x.d) + '</dd>'; }).join('') + '</dl>' : U.missing('The glossary', g);
  });
  if (tab === 'lab') return SC.load(S + '/lab.json').then(function (d) { if (U.alive(body)) { if (SC.ok(d)) lab(body, S, d); else body.innerHTML = U.missing('The lab', d); } });
  if (tab === 'records') return SC.load(S + '/records.json').then(function (d) { if (U.alive(body)) { if (SC.ok(d)) records(body, S, d); else body.innerHTML = U.missing('Records', d); } });
  return SC.load(S + '/model.json').then(function (d) {
    if (!U.alive(body)) return;
    if (!SC.ok(d)) { body.innerHTML = U.missing('The model page', d); return; }
    if (tab === 'doing') doing(body, S, d);
    else body.innerHTML = method(S, d) + U.note('Settings fitted on results through ' + esc(SC.date(d.fitted_through)) + '.');
  });
});
})();
