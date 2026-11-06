/* The Quant Iron — the model page (#/model?tab=method|doing|records|glossary|terms) and #/records, #/disclaimer.
 * How it works, how we're doing on the sealed years (against simple baselines, paired intervals, calibration, the
 * podium chances), all-time records with their progressions, the glossary and the terms. Reads model.json,
 * records.json and glossary.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;
var TABS = [['method', 'How it works'], ['doing', 'How we’re doing'], ['records', 'Records'], ['glossary', 'Glossary'], ['terms', 'Terms']];
var VNAME = { last: 'The last meet', buckets: '+ stage, age and time away', full: '+ distance from level and best (live)' };

function f1(v, d) { return isNum(v) ? v.toFixed(d === undefined ? 1 : d) : '–'; }
function pair(x, lab) {
  if (!x || !isNum(x.diff)) return '';
  return '<li><b>' + esc(lab) + ':</b> ' + IR.signed(x.diff, 1) + ' squared DOTS a lifter-meet (95% interval ' + IR.signed(x.lo, 1) + ' to ' + IR.signed(x.hi, 1) + ', ' + fmt.num(x.n) + ' lifter-meets in ' + fmt.num(x.clusters || 0) + ' meets) — ' + (x.better ? 'better, interval clear of zero.' : x.hi < 0 ? 'worse.' : 'not clearly better.') + '</li>';
}

function method(el, m) {
  var c = m.coverage || {}, rep = m.report || {}, co = (rep.coef || {}).coef || {}, P = m.params || {};
  var html = '<div class="ir-prose">' +
    '<h3>The data</h3><p>Every result in the OpenPowerlifting archive (public domain, weekly): ' + fmt.num(c.scored || 0) + ' full-power performances by ' + fmt.num(c.lifters || 0) + ' lifters at ' + fmt.num(c.meets || 0) + ' meets, ' + esc(IR.date(c.from)) + ' to ' + esc(IR.date(c.to)) + '. Bench-only and deadlift-only entries are shown on meet pages but not rated. A lifter entered in two divisions at one meet is one performance.</p>' +
    '<h3>Streams and classes</h3><p>Six ranking pools: men and women, raw (sleeves), wraps, and equipped (single-ply, multi-ply, unlimited). DOTS puts every bodyweight on one scale; weight classes are the IPF’s from the bodyweight on the day, whatever the federation used.</p>' +
    '<h3>Our rating</h3><p>The DOTS we expect at the lifter’s next meet. It starts from the last meet and adds what the training years (1990 to 2019) say about lifters at that stage of a career: <b>meets so far</b> (newer lifters gain fastest), <b>age</b>, <b>time since the last meet</b>, and how the last meet sits against the lifter’s longer-run level (a decayed mean of their DOTS, half-life ' + esc(P.half_life) + ' days) and their best. One least-squares fit; coefficients below. A first-time lifter gets the stream’s average first meet.</p>' +
    '<p>Why not the long-run level alone? Lifters improve: on the sealed test the decayed mean missed by ' + f1(((rep.baselines || {}).test || {}).rating && rep.baselines.test.rating.rmse) + ' DOTS a meet, the last meet alone by ' + f1((((rep.variants || {}).last || {}).test || {}).rmse) + ', the full forecast by ' + f1((((rep.variants || {}).full || {}).test || {}).rmse) + '. The site shipped on 4 November 2026 with a heavier pull toward the stream mean (missing by 57.6 DOTS a meet, worse than the last meet); that was replaced on 6 November after this test.</p>' +
    '<h3>Expected totals and podium chances</h3><p>Expected DOTS turn into kilos at the bodyweight on the day. For each flight (meet, division, class, equipment) we simulate the meet 400 times: every lifter’s total drawn around our expectation with the spread the training years show for their stage and time away, and a bomb-out with the stream’s training rate. The podium chance blends the simulation with a rank table (how often our 1st, 2nd, 3rd... expected finished on the podium in training flights of that size), ' + Math.round(100 * (1 - (((rep.podium || {}).eps) || 0))) + '% simulation, chosen on 2020 to 2022: the simulation alone was too sure in the tails.</p>' +
    '<h3>Percentiles and shrinkage</h3><p>Lifter percentiles compare active lifters (two or more meets in two years) of the same stream and class. Rates are shrunk toward the average so one meet cannot top a list: attempts made as if nine more attempts at the stream rate, third attempts with six, beating our forecast toward half with four meets, meet value toward zero with three, bomb-outs with five, progress toward zero for a short span.</p>' +
    '<h3>No look-ahead</h3><p>Every expectation and chance on a meet page uses only meets dated before it; meets to the end of 2025 are scored with the model fitted on 1990 to 2019, later meets with the model refitted through 2025. Rankings 90 days ago are rebuilt from the meets before that day.</p></div>';
  var names = Object.keys(co);
  if (names.length) {
    html += U.card('The forecast’s coefficients', 'Added to the last meet’s DOTS (fitted on 1990 to 2019). a: the intercept; b: × (decayed level − last); c: × (best − last); the rest are offsets for a bucket (age against 24 to 28).',
      U.table([{ label: 'Term', align: 'left' }, { label: 'DOTS' }], names.map(function (k) { return [{ v: k, html: esc(k.replace('nb:', 'meets so far: ').replace('ab:', 'age: ').replace('gb:', 'days since last: ')) }, { v: co[k], html: IR.signed(co[k], k === 'b' || k === 'c' ? 3 : 1) }]; }), { cls: 'dense' }), { flush: true });
  }
  if ((m.grid || []).length) html += U.card('Tuning the long-run level', 'The decayed mean alone as a forecast, by half-life and prior weight, chosen on the training years.', U.table(
    [{ label: 'Half-life (days)' }, { label: 'Prior weight' }, { label: 'Train RMSE' }, { label: 'Valid RMSE' }, { label: 'Test RMSE' }],
    m.grid.map(function (g) { return [{ v: g.half_life, html: String(g.half_life) }, { v: g.k0, html: String(g.k0) }, { v: g.train_rmse, html: f1(g.train_rmse, 2) }, { v: g.valid_rmse, html: f1(g.valid_rmse, 2) }, { v: g.test_rmse, html: f1(g.test_rmse, 2) }]; }), { cls: 'dense' }), { flush: true });
  el.innerHTML = html;
  U.wire(el);
}

function doing(el, m) {
  var rep = m.report || {}, V = rep.variants || {}, B = rep.baselines || {}, P = rep.paired || {}, pod = rep.podium || {};
  var t = (V[rep.live] || {}).test || {};
  var html = QK.stats([
    { label: 'Miss per meet (sealed 2023-25)', value: f1(t.rmse) + ' DOTS', signal: true, sub: 'root mean square, ' + fmt.num(t.n || 0) + ' lifter-meets; typical (median-like) miss ' + f1(t.mae) },
    { label: 'The last meet alone', value: f1(((V.last || {}).test || {}).rmse) + ' DOTS', sub: 'the simple baseline' },
    { label: 'Inside our 80% band', value: IR.pctv(100 * (rep.band80 || 0), 1), sub: 'of sealed results (80% is right)' },
    { label: 'Podium chance, log loss', value: f1(((pod.test || {}).p_pod || {}).logloss, 3), sub: 'rank table ' + f1(((pod.test || {}).p_rank || {}).logloss, 3) + ' · even share ' + f1(((pod.test || {}).p_even || {}).logloss, 3) }
  ]);
  html += U.card('Expected DOTS, every window', 'Lifters with at least one earlier scored meet. Train 1990 to 2019 (fitted), valid 2020 to 2022 (choices), test 2023 to 2025 (scored once).', U.table(
    [{ label: 'Forecast', align: 'left' }, { label: 'Train RMSE' }, { label: 'Valid RMSE' }, { label: 'Test RMSE' }, { label: 'Test MAE' }, { label: 'Test bias' }, { label: 'Test r' }],
    [['rating', 'The long-run level alone (decayed mean)', B]].concat(['last', 'buckets', 'full'].map(function (v) { return [v, VNAME[v] + (v === rep.chosen ? ' · chosen on valid' : ''), V]; })).map(function (x) {
      var g = function (w) { return x[0] === 'rating' ? ((B[w] || {}).rating || {}) : ((V[x[0]] || {})[w] || {}); };
      return [{ v: x[1], html: esc(x[1]) }, { v: g('train').rmse, html: f1(g('train').rmse, 2) }, { v: g('valid').rmse, html: f1(g('valid').rmse, 2) }, { v: g('test').rmse, html: '<b>' + f1(g('test').rmse, 2) + '</b>' },
        { v: g('test').mae, html: f1(g('test').mae, 2) }, { v: g('test').bias, html: IR.signed(g('test').bias, 2) }, { v: g('test').r, html: f1(g('test').r, 3) }];
    }), { cls: 'dense' }), { flush: true });
  html += U.card('The promotion rule', 'A component goes live only if it beats the simpler one on the sealed years, with a paired 95% interval (clustered by meet) clear of zero. Positive: the new one has the smaller squared error.',
    '<ul class="ir-list ir-bul">' + pair(P.vs_last, 'Our forecast against the last meet') + pair(P.vs_rating, 'Our forecast against the long-run level') + pair(P.last_vs_rating, 'The last meet against the long-run level') +
    '<li><b>Live:</b> ' + esc(VNAME[rep.live] || rep.live) + '.</li></ul>');
  html += '<div class="qk-g2 ir-gap">' + U.card('Calibration of expected DOTS', 'Sealed test, in ten bins of our expectation: the average expected against the average lifted. On the diagonal is right.', U.chart('md-cal', 320, 'Calibration of expected DOTS')) +
    U.card('Where it is hard', 'Sealed test RMSE by meets so far: our forecast against the last meet alone.', U.chart('md-n', 320, 'Error by meets so far')) + '</div>';
  var tt = pod.test || {}, vv = pod.valid || {};
  html += U.card('Podium chances', 'Flights of four or more (meet, division, class, equipment). ' + fmt.num(tt.n || 0) + ' lifter-flights in ' + fmt.num(tt.flights || 0) + ' flights on the sealed years; ' + IR.pctv(100 * (tt.base_rate || 0), 1) + ' made the podium. Blend: ' + Math.round(100 * (1 - (pod.eps || 0))) + '% simulation (spread ×' + (pod.sd_scale || 1) + '), the rest the rank table, chosen on 2020 to 2022.',
    U.table([{ label: 'Chance', align: 'left' }, { label: 'Valid Brier' }, { label: 'Valid log loss' }, { label: 'Test Brier' }, { label: 'Test log loss' }],
      [['p_pod', 'Ours (simulation blended with the rank table)'], ['p_sim', 'The simulation alone'], ['p_rank', 'The rank table alone'], ['p_even', 'An even share (3 in the flight size)']].map(function (x) {
        return [{ v: x[1], html: esc(x[1]) }, { v: ((vv[x[0]] || {}).brier), html: f1((vv[x[0]] || {}).brier, 4) }, { v: ((vv[x[0]] || {}).logloss), html: f1((vv[x[0]] || {}).logloss, 4) }, { v: ((tt[x[0]] || {}).brier), html: '<b>' + f1((tt[x[0]] || {}).brier, 4) + '</b>' }, { v: ((tt[x[0]] || {}).logloss), html: '<b>' + f1((tt[x[0]] || {}).logloss, 4) + '</b>' }];
      }), { cls: 'dense' }) +
    '<ul class="ir-list ir-bul">' + ['sim_vs_rank', 'sim_vs_rank_brier', 'sim_vs_even'].map(function (k) {
      var x = tt[k]; if (!x || !isNum(x.diff)) return '';
      return '<li><b>' + ({ sim_vs_rank: 'Ours against the rank table, log loss', sim_vs_rank_brier: 'Ours against the rank table, Brier', sim_vs_even: 'Ours against the even share, log loss' })[k] + ':</b> ' + IR.signed(x.diff, 4) + ' a lifter (95% interval ' + IR.signed(x.lo, 4) + ' to ' + IR.signed(x.hi, 4) + ', clustered by flight) — ' + (x.better ? 'better.' : 'not clearly better.') + '</li>';
    }).join('') + '<li><b>Live:</b> ' + (pod.promoted ? 'the blend.' : 'the rank table (the blend did not clear the rule).') + ' Win chance, sealed: Brier ' + f1((tt.win || {}).brier, 4) + ' (rank table ' + f1((tt.win || {}).rank_brier, 4) + '), log loss ' + f1((tt.win || {}).logloss, 4) + ' (rank table ' + f1((tt.win || {}).rank_logloss, 4) + ').</li></ul>' +
    U.chart('md-pod', 320, 'Podium chance calibration'));
  el.innerHTML = html;
  U.wire(el);
  var cal = rep.calibration || [];
  if (cal.length && window.QKC) QKC.scatter(QK.$('#md-cal', el), { points: cal.map(function (b) { return { x: b.pred, y: b.actual, name: fmt.num(b.n) + ' lifter-meets · expected ' + f1(b.pred) + ', lifted ' + f1(b.actual), size: 12 }; }),
    xName: 'Average expected DOTS (bin)', yName: 'Average actual DOTS', diagonal: { label: 'Perfect' }, xMin: Math.floor(cal[0].pred / 10) * 10 - 10, yMin: Math.floor(cal[0].pred / 10) * 10 - 10, xMax: Math.ceil(cal[cal.length - 1].pred / 10) * 10 + 10, yMax: Math.ceil(cal[cal.length - 1].pred / 10) * 10 + 10, xFmt: function (v) { return fmt.num(v, 0); }, yFmt: function (v) { return fmt.num(v, 0); }, label: 'Calibration' });
  var bn = rep.by_n || [];
  if (bn.length && window.QKC) QKC.bar(QK.$('#md-n', el), { cats: bn.map(function (x) { return x.nb; }), series: [{ name: 'Our forecast', data: bn.map(function (x) { return x.rmse; }), color: IR.col(1) }, { name: 'The last meet', data: bn.map(function (x) { return x.rmse_last; }), color: IR.col('ink-4') }],
    valName: 'RMSE (DOTS)', catName: 'Scored meets before this one', fmt: function (v) { return v.toFixed(1); } });
  var rel = tt.reliability || [];
  if (rel.length && window.QKC && QKC.calibration) QKC.calibration(QK.$('#md-pod', el), { bins: rel.map(function (b) { return { lo: b.lo, hi: b.hi, n: b.n, mean_p: b.pred, freq: b.actual }; }), subject: 'the lifter', unit: 'lifters', xName: 'Our podium chance (%)', yName: 'Made the podium (%)', label: 'Podium calibration' });
  else if (rel.length && window.QKC) QKC.scatter(QK.$('#md-pod', el), { points: rel.map(function (b) { return { x: 100 * b.pred, y: 100 * b.actual, name: fmt.num(b.n) + ' lifters', size: 12 }; }),
    xName: 'Our podium chance (%)', yName: 'Made the podium (%)', diagonal: { label: 'Perfect' }, xFmt: function (v) { return Math.round(v) + '%'; }, yFmt: function (v) { return Math.round(v) + '%'; }, label: 'Podium calibration' });
}

var LIFTN = { squat: 'Squat', bench: 'Bench', dead: 'Deadlift', total: 'Total' };
function records(el, r, q) {
  var R = r.records || {}, keys = Object.keys(R);
  var set = R[q.set] ? q.set : (R.men_raw ? 'men_raw' : keys[0]);
  var lift = LIFTN[q.lift] ? q.lift : 'total';
  var A = r.all_time || {};
  var html = U.note('The heaviest lifts in the archive per sex, equipment and IPF class (bodyweight on the day), every federation, tested or not, from full-power meets. A record listed here is an archive best, not a federation’s official record.') +
    '<div class="ir-controls"><label>Records <select class="qk-select" id="rc-set">' + keys.map(function (k) { return '<option value="' + k + '"' + (k === set ? ' selected' : '') + '>' + esc(R[k].label) + '</option>'; }).join('') + '</select></label>' + U.seg('rc-l', Object.keys(LIFTN).map(function (k) { return [k, LIFTN[k]]; }), lift, 'Lift') + '</div>' +
    '<div id="rc-tab"></div><div class="qk-g2 ir-gap">' + U.card('How the record moved', 'Every time the record in the chosen class went up.', '<div class="ir-controls"><select class="qk-select" id="rc-cls"></select></div>' + U.chart('rc-prog', 320, 'Record progression')) + '<div id="rc-steps"></div></div>' +
    '<h2 class="ir-h2">All-time best DOTS</h2><div class="ir-controls">' + U.seg('at-s', IR.STREAM_KEYS.filter(function (k) { return A[k]; }).map(function (k) { return [k, IR.STREAMS[k]]; }), 'men_raw', 'Stream') + '</div><div id="at-body"></div>';
  el.innerHTML = html;
  function drawSet() {
    var S = R[QK.$('#rc-set', el).value] || { classes: [] };
    QK.$('#rc-tab', el).innerHTML = U.card(S.label + ' · ' + LIFTN[lift], '', U.table([{ label: 'Class' }, { label: 'Record' }, { label: 'Lifter', align: 'left' }, { label: 'Date' }, { label: 'Federation', align: 'left' }, { label: 'Times broken' }],
      S.classes.filter(function (c) { return c.lifts[lift]; }).map(function (c) { var L = c.lifts[lift]; return [{ v: c.cls, html: esc(c.cls) + ' kg' }, { v: L.kg, html: '<b>' + IR.kg(L.kg) + '</b>' }, { v: L.name, html: IR.playerLink(L.pid, L.name) }, { v: L.date, html: esc(IR.date(L.date)) }, { v: L.fed, html: esc(L.fed) }, { v: L.n_steps, html: String(L.n_steps) }]; }), { cls: 'dense' }), { flush: true });
    var cs = QK.$('#rc-cls', el), prev = cs.value;
    cs.innerHTML = S.classes.filter(function (c) { return c.lifts[lift]; }).map(function (c) { return '<option value="' + esc(c.cls) + '"' + (c.cls === prev ? ' selected' : '') + '>' + esc(c.cls) + ' kg</option>'; }).join('');
    drawProg();
    U.wire(el);
  }
  function drawProg() {
    var S = R[QK.$('#rc-set', el).value] || { classes: [] }, c = S.classes.filter(function (x) { return x.cls === QK.$('#rc-cls', el).value; })[0];
    var L = c && c.lifts[lift];
    if (!L) { QK.$('#rc-prog', el).innerHTML = ''; QK.$('#rc-steps', el).innerHTML = ''; return; }
    QKC.line(QK.$('#rc-prog', el), { x: L.steps.map(function (s) { return s.date; }), xType: 'category', series: [{ name: 'The record', data: L.steps.map(function (s) { return s.kg; }), color: IR.col(1) }], step: true,
      yName: LIFTN[lift] + ' record (kg)', xName: 'Date it was set', endLabels: false, yFmt: function (v) { return fmt.num(v, 0); } });
    QK.$('#rc-steps', el).innerHTML = U.card('The record’s history', (L.n_steps > L.steps.length ? 'The last ' + L.steps.length + ' of ' + L.n_steps + ' times it moved.' : L.n_steps + ' times it moved.'), U.table([{ label: 'Date' }, { label: 'Kilos' }, { label: 'Lifter', align: 'left' }, { label: 'Federation', align: 'left' }],
      L.steps.slice().reverse().map(function (s) { return [{ v: s.date, html: esc(IR.date(s.date)) }, { v: s.kg, html: IR.kg(s.kg) }, { v: s.name, html: esc(s.name) }, { v: s.fed, html: esc(s.fed) }]; }), { cls: 'dense', maxHeight: 360 }), { flush: true });
  }
  function drawAll(k) {
    var a = A[k] || {}, decs = Object.keys(a.decades || {}).sort();
    QK.$('#at-body', el).innerHTML = '<div class="qk-g75 ir-gap"><div>' + U.card('The top 50 ever', 'Each lifter’s best DOTS in ' + IR.STREAMS[k].toLowerCase() + '.', U.table([{ label: '#' }, { label: 'Lifter', align: 'left' }, { label: 'DOTS' }, { label: 'Total' }, { label: 'BW' }, { label: 'Meet', align: 'left' }],
      (a.top || []).map(function (x, i) { return [{ v: i + 1, html: String(i + 1) }, { v: x.name, html: IR.playerLink(x.pid, x.name) + ' <small class="qk-muted">' + esc(x.cc || '') + '</small>' }, { v: x.dots, html: '<b>' + IR.dots(x.dots) + '</b>' }, { v: x.total, html: IR.kgn(x.total) }, { v: x.bw, html: IR.kgn(x.bw) }, { v: x.date, html: IR.eventLink(x.meet, x.meet_name || x.date) + ' <small class="qk-muted">' + esc(IR.year(x.date)) + '</small>' }]; }), { cls: 'dense', maxHeight: 640 }), { flush: true }) + '</div><div>' +
      U.card('The best of each decade', '', decs.reverse().map(function (dd) { return '<h3 class="ir-flight">' + esc(dd) + 's</h3><ul class="ir-list">' + a.decades[dd].slice(0, 5).map(function (x) { return '<li>' + esc(x.name) + '<span class="v">' + IR.dots(x.dots) + '</span><small>' + esc(IR.year(x.date)) + '</small></li>'; }).join('') + '</ul>'; }).join('')) + '</div></div>';
    U.wire(el);
  }
  drawSet();
  drawAll('men_raw');
  QK.$('#rc-set', el).addEventListener('change', drawSet);
  QK.$('#rc-cls', el).addEventListener('change', drawProg);
  QK.seg(QK.$('#rc-l', el), function (v) { lift = v; drawSet(); });
  QK.seg(QK.$('#at-s', el), drawAll);
}

function glossary(el, g) {
  el.innerHTML = '<dl class="ir-gloss">' + (g.terms || []).map(function (t) { return '<dt>' + esc(t.t) + '</dt><dd>' + esc(t.d) + '</dd>'; }).join('') + '</dl>';
}
function terms(el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = t ? t.innerHTML : '';
}

function modelPage(el, params, forced) {
  var q = params.query || {};
  var tab = forced || (TABS.map(function (t) { return t[0]; }).indexOf(q.tab) >= 0 ? q.tab : 'method');
  el.innerHTML = U.head('Model', 'How our ratings, expected totals and podium chances are built, how they have done on years they never saw, the archive’s records, the words we use and the terms.', 'The Quant Iron') +
    U.tabs(TABS.map(function (t) { return { key: t[0], label: t[1], href: '#/model?tab=' + t[0] }; }), tab) + '<div id="md-body">' + QK.skeleton('lines', 6) + '</div>';
  var body = QK.$('#md-body', el);
  if (tab === 'terms') { terms(body); return null; }
  if (tab === 'glossary') return IR.load('glossary.json').then(function (g) { glossary(body, g); });
  if (tab === 'records') return IR.load('records.json').then(function (r) { records(body, r, q); });
  return IR.load('model.json').then(function (m) { (tab === 'doing' ? doing : method)(body, m); });
}
IR.page('model', function (el, params) { return modelPage(el, params); });
IR.page('records', function (el, params) { return modelPage(el, params, 'records'); });
IR.page('disclaimer', function (el, params) { return modelPage(el, params, 'terms'); });
})();
