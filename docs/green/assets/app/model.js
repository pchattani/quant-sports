/* The Quant Green — the model page (#/model?tab=method|doing|tests|glossary): how the ratings and the simulations
 * work, how the forecasts did on the sealed test seasons (log loss against base rates, calibration), the promotion
 * tests every change had to pass (models/promotion.json), and a glossary. Reads model.json (pages.py _model). */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, GR = window.GR, fmt = QK.fmt;
var esc = GR.esc, isNum = GR.isNum;

function calText(cal) {
  var w = (cal && cal.win) || [];
  if (!w.length) return '';
  var top = w[w.length - 1], big = w.slice().sort(function (a, b) { return b.n - a.n; })[0];
  var ratio = top.p > 0 ? top.freq / top.p : 1;
  var verdict = ratio > 1.2 ? 'Our strongest favourites win more often than we say, so the top of each field is undersold.'
    : ratio < 0.8 ? 'Our strongest favourites win less often than we say, so the top of each field is oversold.'
    : 'Our strongest favourites win about as often as we say.';
  return '<p>Players we gave ' + GR.pct(top.lo) + ' or more to win (' + GR.pct(top.p) + ' on average) won ' + GR.pct(top.freq) + ' of the time, across ' + fmt.num(top.n) + ' players. ' + verdict + '</p>' +
    '<p>The busiest bucket, ' + fmt.num(big.n) + ' players given ' + GR.pct(big.lo) + '–' + GR.pct(big.hi) + ', won ' + GR.pct(big.freq) + ' against ' + GR.pct(big.p) + ' forecast.</p>';
}
function calBins(b) { return (b || []).map(function (x) { return { lo: x.lo, hi: x.hi, n: x.n, mean_p: x.p, freq: x.freq }; }); }
function ci(x) { return x ? GR.signed(x.diff, 4) + ' (' + GR.signed(x.lo, 4) + ' to ' + GR.signed(x.hi, 4) + ')' : ''; }

function method(m) {
  var rd = m.rounds;
  return '<section class="qk-section gr-prose">' +
    '<h3>Ratings: strokes against the field</h3>' +
    '<p>Every round of every event is compared with the field that played it. A round’s par for the field is the score an average player would have made that day: the mean of everyone’s score plus the rating they brought in. Beating it by three strokes is three strokes gained, whether the course was easy or brutal and whatever the field’s strength. The PGA Tour, the DP World Tour, LIV and the Korn Ferry Tour share one scale, tied together by the majors, the events they share and the players who move between them; the LPGA is its own.</p>' +
    '<p>A player’s rating is the weighted mean of their strokes gained, newer rounds counting for more: a round counts half after ' + Math.round(m.params.half_life) + ' days. It is pulled lightly toward a newcomer’s level (worth ' + m.params.k0 + ' rounds), so a player with a short record can sit high on a few good weeks; those ratings are marked <i>thin record</i>. Ratings are shown against an average PGA Tour (LPGA Tour) player of the last year. Incomplete rounds (a withdrawal mid-round) and events still under way never enter the walk.</p>' +
    '<h3>Chances: simulated tournaments</h3>' +
    '<p>Each player’s round is their rating plus noise, a spread of ' + fmt.num(m.sd.men, 2) + ' strokes a round (men; ' + fmt.num(m.sd.women, 2) + ' women), rounded to whole strokes. We play the event ' + fmt.num(m.sims.now) + ' times with its real cut rule and count how often each player wins, makes the top 5, 10 or 20, and makes the cut. A tie for first goes to a playoff between equals; top-10 finishes count ties. While an event is under way, the live chances start from each player’s score and the holes they have left.</p>' +
    '<p>Every chance on an event page was made with nothing from that event or after it: the ratings are walked forward event by event.</p>' +
    '<h3>The Scouting Room numbers</h3>' +
    '<p>Strokes gained by round and by nine come from the same walk (a nine against the field’s average nine that day). Hole numbers (par 3, 4 and 5 scoring, birdie and bogey rates) use the hole-by-hole scores ESPN carries for the PGA Tour and the Korn Ferry Tour. Ball-striking numbers (distance, accuracy, greens in regulation, putts per green hit, sand saves) are the PGA Tour’s season statistics on ESPN from 2017. Every rate is shrunk toward the average of the peers: 12 rounds of weight for strokes gained, 72 holes for hole rates, 10 starts for results.</p>' +
    '<p>Strokes gained by category is <b>our estimate</b>, not ShotLink’s: a regression of each player-season’s strokes gained on the five statistics' + (m.cats ? ', which explains ' + GR.pct(m.cats.r2_test) + ' of the spread in seasons the fit never saw' : '') + '.</p>' +
    '<h3>Chosen once, tested once</h3>' +
    '<p>The two settings (how fast old rounds fade and how hard to pull toward a newcomer’s level) were chosen on PGA Tour rounds of ' + rd.train.years[0] + '–' + rd.train.years[1] + ' by squared error, checked on ' + rd.valid.years[0] + '–' + rd.valid.years[1] + ', and scored once on ' + rd.test.years[0] + '–' + rd.test.years[1] + '. A change ships only when it beats the model before it on the sealed test seasons: the Tests tab has every one.</p>' +
    '<h3>Data</h3><p>Schedules, leaderboards, round and hole scores, courses, prize money, season statistics and player bios come from ESPN’s public golf feeds, used non-commercially and credited here. The PGA Tour’s ShotLink data is licensed and Data Golf’s is paid: neither is used. The points ranking is our own rebuild from results; the Official World Golf Ranking’s terms forbid reusing its data, so none is used.</p></section>' +
    '<div class="qk-g2 gr-gap">' + GR.card('Tuning grid', 'Mean squared error per round, lower is better; the chosen row first', '<div id="md-g"></div>', { flush: true }) +
    GR.card('Coverage', 'Seasons on file (ESPN). Hole-by-hole scores on the PGA Tour and the Korn Ferry Tour.', '<div id="md-cv"></div>', { flush: true }) + '</div>';
}

function doing(m) {
  var ev = m.events, rd = m.rounds;
  return QK.stats([
      { label: 'Favourite won', value: GR.pct(ev.favourite_won), sub: ev.events + ' PGA Tour events, ' + ev.years[0] + '–' + ev.years[1] },
      { label: 'Win skill', value: GR.pct(ev.win.skill), sub: 'log loss ' + ev.win.model + ' against ' + ev.win.base + ' for an even draw', signal: true },
      { label: 'Top-10 skill', value: GR.pct(ev.top10.skill), sub: 'log loss ' + ev.top10.model + ' against ' + ev.top10.base, signal: true },
      { label: 'Cut skill', value: GR.pct(ev.cut.skill), sub: ev.cut.events + ' events with a cut', signal: true },
      { label: 'Round correlation', value: fmt.num(rd.test.r, 3), sub: 'rating against strokes gained, ' + fmt.num(rd.test.n) + ' test rounds' }]) +
    QK.note('Skill is the improvement in log loss over the simplest honest forecast: an even chance for every player to win, 10 in the field for a top 10, and the field’s own cut rate. The test seasons were never used to choose anything.') +
    '<div class="qk-g2 gr-gap">' + GR.card('Win chances', 'Our pre-event chance to win against how often it happened, sealed test events', GR.chart('md-cw', 320, 'Win calibration')) +
      GR.card('Top-10 chances', 'Our pre-event top-10 chance against how often it happened', GR.chart('md-ct', 320, 'Top-10 calibration')) + '</div>' +
    '<div class="qk-g2 gr-gap">' + GR.card('Making the cut', 'Our pre-event chance to make the cut against how often it happened', GR.chart('md-cc', 320, 'Cut calibration')) +
      GR.card('What the test says', '', '<div class="gr-prose">' + calText(m.calibration) + '<p>Round level: the rating explains strokes gained with a correlation of ' + fmt.num(rd.test.r, 3) + ' on test rounds (mean squared error ' + fmt.num(rd.test.mse, 2) + ' against ' + fmt.num(rd.test.mse_zero, 2) + ' for a rating of zero). Golf is noisy: a round is the rating plus or minus about ' + fmt.num(m.sd.men, 1) + ' strokes.</p></div>') + '</div>';
}

function tests(m) {
  var p = m.promotion || {};
  var ts = p.tests || [];
  if (!ts.length) return QK.empty('No promotion tests on file', '');
  var rows = ts.map(function (t) {
    return [{ v: t.name, html: '<b>' + esc(t.name) + '</b>' }, { v: 0, html: ci(t.round_dev) }, { v: 0, html: ci(t.round_test) }, { v: 0, html: ci(t.win) }, { v: 0, html: ci(t.top10) }, { v: 0, html: ci(t.cut) }, { v: 0, html: esc(t.verdict) }];
  });
  var ll = p.logloss || {}, ece = p.ece || {};
  return '<div class="gr-prose"><p>' + esc(p.note || '') + ' Choices were made on ' + (p.dev || []).join('–') + '; ' + (p.test || []).join('–') + ' was scored once. Each cell is the paired mean difference with its 95% interval: negative favours the change. A change ships only when the interval on the sealed test excludes zero with no loss of calibration.</p></div>' +
    GR.card('Every change tested', 'Round level: squared error per round; event level: log loss per event (' + (p.events || '') + ' PGA Tour test events).',
      GR.table([{ label: 'Change', align: 'left' }, { label: 'Rounds, dev' }, { label: 'Rounds, test' }, { label: 'Win, test' }, { label: 'Top 10, test' }, { label: 'Cut, test' }, { label: 'Verdict', align: 'left' }], rows), { flush: true }) +
    '<div class="qk-g2 gr-gap">' + GR.card('Log loss on the test events', 'A: the walk shipped on 4 Nov; C: partial rounds out; B: C plus the Korn Ferry Tour (live).', GR.table([{ label: 'Market', align: 'left' }, { label: 'A' }, { label: 'C' }, { label: 'B (live)' }],
      [['Win', 'win'], ['Top 10', 't10'], ['Make the cut', 'cut']].map(function (x) { var r = ll[x[1]] || {}; return [{ v: x[0], html: x[0] }, { v: r.A, html: fmt.num(r.A, 5) }, { v: r.C, html: fmt.num(r.C, 5) }, { v: r.B, html: '<b>' + fmt.num(r.B, 5) + '</b>' }]; })), { flush: true }) +
    GR.card('Calibration error on the test events', 'The average gap between our chance and how often it happened, by bucket (lower is better).', GR.table([{ label: 'Market', align: 'left' }, { label: 'A' }, { label: 'C' }, { label: 'B (live)' }],
      [['Win', 'win'], ['Top 10', 't10'], ['Make the cut', 'cut']].map(function (x) { return [{ v: x[0], html: x[0] }, { v: 0, html: fmt.num((ece.A || {})[x[1]], 4) }, { v: 0, html: fmt.num((ece.C || {})[x[1]], 4) }, { v: 0, html: '<b>' + fmt.num((ece.B || {})[x[1]], 4) + '</b>' }]; })) +
      GR.note('The cut’s calibration error rose slightly (' + fmt.num((ece.A || {}).cut, 4) + ' to ' + fmt.num((ece.B || {}).cut, 4) + ') while its log loss fell: we report it rather than hide it. Taking out the partial rounds shrank the round spread from ' + fmt.num((p.sd || {}).A, 2) + ' to ' + fmt.num((p.sd || {}).B, 2) + ' strokes, so the chances are sharper.'), { flush: false }) + '</div>';
}

var GLOSS = [
  ['Strokes gained (SG)', 'Strokes better than an average tour field would have made on the same course on the same day. The field’s par is everyone’s score plus the rating they brought in, averaged.'],
  ['Rating', 'A player’s decayed, shrunk average strokes gained per round: the number the forecasts use, shown against an average PGA Tour (or LPGA Tour) player of the last year.'],
  ['Form', 'Strokes gained per round over the last eight events.'],
  ['Course fit', 'How far a player has beaten their own rating at a course in earlier editions, shrunk toward zero with 32 rounds. Shown as history only: it did not improve the forecasts out of sample.'],
  ['Wave', 'Rounds 1 and 2 split into the early and the late half of the tee sheet: the weather draw.'],
  ['Par 3, 4 and 5 scoring', 'Strokes better than the field on the same hole in the same round, per hole: hole-by-hole tours only (PGA Tour, Korn Ferry Tour).'],
  ['Greens in regulation (GIR)', 'Reaching the green in par minus two strokes or fewer. Putts per GIR: putts taken on those greens.'],
  ['Off the tee, approach, around the green, putting', 'Our estimate of strokes gained by category from season statistics: not ShotLink’s shot-by-shot numbers.'],
  ['Percentile', 'Where a player ranks against the regulars of the last two years (30+ rounds): 90 is better than nine in ten.'],
  ['Shrinkage', 'Pulling a small sample toward the average so a handful of rounds cannot top a list.'],
  ['Thin record', 'Fewer than 20 decayed rounds behind a rating: it can swing a long way on a few results.'],
  ['Log loss', 'The penalty a forecast pays for what happened: lower is better. Skill is the improvement over a simple baseline.'],
  ['Calibration', 'Whether things we give 20% happen about 20% of the time.'],
  ['Points ranking', 'Our rebuild of a world-ranking-style table from results: points by finish, scaled by field strength, fading over two years.']
];

GR.page('model', function (el, params) {
  var q = params.query || {};
  var tab = ['method', 'doing', 'tests', 'glossary'].indexOf(q.tab) >= 0 ? q.tab : 'method';
  return GR.load('model.json').then(function (m) {
    if (!el.isConnected) return;
    var body = tab === 'doing' ? doing(m) : tab === 'tests' ? tests(m) : tab === 'glossary' ? GR.table([{ label: 'Term', align: 'left' }, { label: 'What it means', align: 'left' }], GLOSS.map(function (g) { return [{ v: g[0], html: '<b>' + esc(g[0]) + '</b>' }, { v: g[1], html: esc(g[1]) }]; })) : method(m);
    el.innerHTML = GR.head('How it works and how we’re doing', 'Ratings from every round against the field, chances from simulated tournaments, and every number tested on seasons the model never saw.', 'The model') +
      GR.tabs([['method', 'How it works', '#/model'], ['doing', 'How we’re doing', '#/model?tab=doing'], ['tests', 'Tests', '#/model?tab=tests'], ['glossary', 'Glossary', '#/model?tab=glossary'], ['terms', 'Terms', '#/disclaimer']], tab) + body;
    QK.sortable(el);
    if (tab === 'doing') {
      GR.safe(function () { QKC.calibration(el.querySelector('#md-cw'), { bins: calBins(m.calibration.win), subject: 'the player', unit: 'players', label: 'Win calibration' }); });
      GR.safe(function () { QKC.calibration(el.querySelector('#md-ct'), { bins: calBins(m.calibration.top10), subject: 'the player', unit: 'players', label: 'Top-10 calibration' }); });
      GR.safe(function () { QKC.calibration(el.querySelector('#md-cc'), { bins: calBins(m.calibration.cut), subject: 'the player', unit: 'players', label: 'Cut calibration' }); });
    }
    if (tab === 'method') {
      var cov = Object.keys(m.coverage || {}).map(function (t) { var c = m.coverage[t]; var s = c.seasons || []; return { tour: c.name, from: s[0], to: s[s.length - 1], n: s.length, holes: c.holes ? 'yes' : 'no' }; });
      QK.table(el.querySelector('#md-g'), { dense: true, rows: m.grid || [], columns: [
        { key: 'half_life', label: 'Half-life (days)', num: true, raw: true }, { key: 'k0', label: 'Prior (rounds)', num: true, raw: true },
        { key: 'train', label: 'Train', num: true, fmt: function (v) { return fmt.num(v, 3); } }, { key: 'valid', label: 'Valid', num: true, fmt: function (v) { return fmt.num(v, 3); } }] });
      QK.table(el.querySelector('#md-cv'), { dense: true, rows: cov, columns: [
        { key: 'tour', label: 'Tour' }, { key: 'from', label: 'From', raw: true }, { key: 'to', label: 'To', raw: true }, { key: 'n', label: 'Seasons', num: true }, { key: 'holes', label: 'Holes' }] });
    }
  });
});
})();
