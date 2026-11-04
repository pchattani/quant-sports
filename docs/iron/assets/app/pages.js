/* The Quant Iron — overview, meets, rankings, lifters, lifter, model and terms. The meet page is meet.js. */
(function () {
'use strict';

var QK = window.QK, QKC = window.QKC, IR = window.IR, fmt = QK.fmt;
var esc = IR.esc, isNum = IR.isNum;

function chartSafe(fn) { try { fn(); } catch (e) { if (window.console) console.error(e); } }

function topTable(rows, href) {
  return '<ol class="ir-list">' + (rows || []).map(function (r) {
    return '<li><span>' + r.rank + '. ' + IR.playerLink(r.pid, r.name) + ' <span class="ir-muted">' + esc(r.cc || '') + '</span></span><b class="num">' + IR.rating(r.rt) + '</b></li>';
  }).join('') + '</ol><p class="ir-meta"><a href="' + href + '">Full rankings \u2192</a></p>';
}

IR.page('overview', function (el) {
  return IR.load('index.json').then(function (ix) {
    if (!el.isConnected) return;
    var m = ix.model || {};
    var head = QK.sectionHead({ tag: 'h1', size: 'lg', kicker: 'Powerlifting by the numbers', title: 'The Quant Iron',
      sub: 'Walk-forward DOTS ratings and expected totals from the OpenPowerlifting archive. Updated ' + fmt.ago(ix.updated_at) + '.' });
    var recent = '<ul class="ir-list">' + (ix.recent || []).map(function (s) {
      return '<li><span>' + IR.eventLink(s.id, s.name) + '</span><span class="num">' + s.n + '</span>' +
        '<small>' + esc(s.fed) + ' · ' + esc(IR.dayMonth(s.date)) + ' · ' + esc(s.country || '') + '</small></li>';
    }).join('') + '</ul>';
    var stats = QK.stats([
      { label: 'Sealed-test RMSE', value: isNum(m.rmse) ? m.rmse.toFixed(1) : '\u2014', sub: 'DOTS, 2023\u20132025, lifters we had already seen', tip: 'Root-mean-square error of the pre-meet rating against the DOTS they actually scored, on years the model never saw while it was tuned.' },
      { label: 'Correlation', value: isNum(m.r) ? m.r.toFixed(2) : '\u2014', sub: 'predicted vs actual DOTS', signal: true },
      { label: 'Scored meets', value: fmt.num((ix.counts || {}).scored), sub: 'SBD totals with a bodyweight' },
      { label: 'Lifters on file', value: fmt.num((ix.counts || {}).lifters), sub: 'from OpenPowerlifting' }
    ]);
    el.innerHTML = head +
      '<section class="qk-section"><div class="qk-grid">' +
        '<div class="qk-span-4">' + IR.card('Men · Raw', 'Our rating in DOTS, tested and untested together', topTable((ix.top || {}).men_raw, '#/standings?s=men_raw')) + '</div>' +
        '<div class="qk-span-4">' + IR.card('Women · Raw', 'Our rating in DOTS, tested and untested together', topTable((ix.top || {}).women_raw, '#/standings?s=women_raw')) + '</div>' +
        '<div class="qk-span-4">' + IR.card('Latest meets', 'Most recently added results', recent) + '</div>' +
      '</div></section>' +
      '<section class="qk-section">' + QK.sectionHead({ title: 'How we\u2019re doing', sub: 'Scored once on years the model never saw while it was tuned.', actions: '<a class="qk-btn" href="#/model">How it works</a>' }) + stats + '</section>';
  });
});

IR.page('meets', function (el, params) {
  return IR.load('schedule/years.json').then(function (ys) {
    var years = (ys.years || []).slice().sort(function (a, b) { return b - a; });
    var year = params.year ? +params.year : years[0];
    if (years.indexOf(year) < 0) year = years[0];
    return IR.load('schedule/' + year + '.json').then(function (sc) {
      if (!el.isConnected) return;
      var ctl = '<div class="ir-controls"><label for="ir-year">Year</label><select id="ir-year" class="qk-select">' +
        years.map(function (s) { return '<option value="' + s + '"' + (s === year ? ' selected' : '') + '>' + s + '</option>'; }).join('') + '</select></div>';
      el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'Meets', title: String(year),
        sub: (sc.meets || []).length + ' sanctioned meets on file this year. A meet page is built when it is recent or large.' }) + ctl + '<div id="ir-tb"></div>';
      el.querySelector('#ir-year').addEventListener('change', function (e) { location.hash = '#/fixtures/' + e.target.value; });
      QK.table(el.querySelector('#ir-tb'), {
        dense: true, maxHeight: 900, rows: sc.meets || [], sort: { key: 'date', dir: 'desc' },
        rowHref: function (m) { return m.page ? '#/event/' + encodeURIComponent(m.id) : ''; },
        columns: [
          { key: 'date', label: 'Date' },
          { key: 'name', label: 'Meet', fmt: function (v, m) { return IR.eventLink(m.id, v); } },
          { key: 'fed', label: 'Federation' },
          { key: 'country', label: 'Country' },
          { key: 'n', label: 'Lifters', num: true }
        ]
      });
    });
  });
});

IR.page('rankings', function (el, params) {
  return IR.load('rankings.json').then(function (rk) {
    if (!el.isConnected) return;
    var keys = Object.keys(rk.streams || {});
    var on = params.query.s && rk.streams[params.query.s] ? params.query.s : 'men_raw';
    var stream = rk.streams[on];
    var rows = stream.rows || [];
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'Our rankings', title: stream.label,
      sub: 'The rating is expected DOTS at a meet tomorrow: a recency-weighted mean of past full-power totals, shrunk toward the stream average. Ranked: at least ' + rk.min_meets + ' scored meets and a meet in the last ' + rk.active_days + ' days.' }) +
      '<div class="ir-controls">' + IR.seg('ir-stream', keys.map(function (k) { return [k, (rk.streams[k].label || k)]; }), on, 'Stream') + '</div>' +
      '<div id="ir-rk"></div>';
    QK.seg(el.querySelector('#ir-stream'), function (v) { location.hash = '#/standings?s=' + v; });
    QK.table(el.querySelector('#ir-rk'), {
      dense: true, maxHeight: 900, rows: rows, sort: { key: 'rank', dir: 'asc' },
      rowHref: function (r) { return '#/player/' + encodeURIComponent(r.pid); },
      columns: [
        { key: 'rank', label: 'Rank', num: true, raw: true },
        { key: 'name', label: 'Lifter', sticky: true, fmt: function (v, r) { return IR.playerLink(r.pid, v) + IR.thinTag(r.wt); } },
        { key: 'cc', label: 'Country' },
        { key: 'rt', label: 'Rating', num: true, ours: 'Ratings', tip: 'Expected DOTS at a meet tomorrow', fmt: function (v) { return '<b>' + IR.rating(v) + '</b>'; } },
        { key: 'n', label: 'Meets', num: true, tip: 'Scored full-power meets behind the rating' },
        { key: 'best12', label: '12-month best', num: true, fmt: function (v) { return IR.dots(v); } },
        { key: 'starts12', label: '12-month starts', num: true },
        { key: 'last', label: 'Last meet' }
      ]
    });
  });
});

IR.page('players', function (el) {
  return IR.load('rankings.json').then(function (rk) {
    if (!el.isConnected) return;
    var seen = {}, all = [];
    Object.keys(rk.streams || {}).forEach(function (k) {
      (rk.streams[k].rows || []).forEach(function (r) {
        if (seen[r.pid]) return;
        seen[r.pid] = 1;
        all.push({ pid: r.pid, name: r.name, cc: r.cc || '', stream: rk.streams[k].label, rt: r.rt, n: r.n, last: r.last });
      });
    });
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'Lifters', title: 'Who we rate',
      sub: all.length.toLocaleString('en-GB') + ' lifters with enough recent full-power meets to publish a rating. Search by name or country.' }) +
      '<div class="ir-controls"><input id="ir-q" class="qk-input ir-search" type="search" placeholder="Search lifters" aria-label="Search lifters"></div><div id="ir-pl"></div>';
    var t = QK.table(el.querySelector('#ir-pl'), {
      dense: true, maxHeight: 900, rows: all, sort: { key: 'rt', dir: 'desc' },
      rowHref: function (x) { return '#/player/' + encodeURIComponent(x.pid); },
      columns: [
        { key: 'name', label: 'Lifter', fmt: function (v, x) { return IR.playerLink(x.pid, v); } },
        { key: 'cc', label: 'Country' },
        { key: 'stream', label: 'Stream' },
        { key: 'rt', label: 'Rating', num: true, fmt: function (v) { return IR.rating(v); } },
        { key: 'n', label: 'Meets', num: true },
        { key: 'last', label: 'Last meet' }
      ]
    });
    function norm(s) { return String(s || '').toLowerCase(); }
    el.querySelector('#ir-q').addEventListener('input', function (e) {
      var q = norm(e.target.value).trim();
      t.setRows(q ? all.filter(function (x) { return norm(x.name).indexOf(q) >= 0 || norm(x.cc).indexOf(q) >= 0; }) : all);
    });
  });
});

IR.page('player', function (el, params) {
  return IR.load('players/' + encodeURIComponent(params.id) + '.json').then(function (p) {
    if (!el.isConnected) return;
    var hist = p.hist || [];
    el.innerHTML = QK.playerHeader({
      name: p.name,
      kicker: (IR.STREAMS[p.stream] || p.stream) + (p.cc ? ' · ' + p.cc : ''),
      meta: [p.cc ? ['Country', p.cc] : null, ['Scored meets', String(p.n || 0)], p.last ? ['Last meet', IR.dayMonth(p.last)] : null].filter(Boolean),
      strip: [
        { label: 'Our rating', value: IR.rating(p.rt), sub: 'expected DOTS', signal: true },
        { label: 'Best DOTS', value: IR.dots(p.best) },
        { label: 'Best total', value: IR.kg(p.best_total) },
        { label: 'Meets', value: fmt.num(p.n) }
      ]
    }) +
      '<section class="qk-section">' + IR.card('Rating over time', 'Pre-meet rating before each full-power total', '<div class="qk-chart" id="ir-hist" style="height:300px"></div>') + '</section>' +
      '<section class="qk-section">' + IR.card('Meets', 'Our pre-meet expected total against what they lifted', '<div id="ir-ev"></div>', { flush: true }) + '</section>';
    chartSafe(function () {
      QKC.line(el.querySelector('#ir-hist'), {
        xType: 'time',
        series: [
          { name: 'Pre-meet rating', color: QKC.tokens().model, data: hist.map(function (h) { return [h.date, h.pre]; }), area: true },
          { name: 'Actual DOTS', data: hist.map(function (h) { return [h.date, h.dots]; }) }
        ],
        yName: 'DOTS', label: 'Rating over time'
      });
    });
    QK.table(el.querySelector('#ir-ev'), {
      dense: true, rows: hist.slice().reverse(), sort: { key: 'date', dir: 'desc' },
      rowHref: function (h) { return '#/event/' + encodeURIComponent(h.meet); },
      columns: [
        { key: 'date', label: 'Date' },
        { key: 'meet_name', label: 'Meet', fmt: function (v, h) { return IR.eventLink(h.meet, v || h.meet); } },
        { key: 'bw', label: 'Bodyweight', num: true, fmt: function (v) { return IR.kg(v); } },
        { key: 'total', label: 'Total', num: true, fmt: function (v) { return IR.kg(v); } },
        { key: 'exp', label: 'Our total', num: true, ours: 'Expected total', fmt: function (v) { return IR.kg(v); } },
        { key: 'dots', label: 'DOTS', num: true, fmt: function (v) { return IR.dots(v); } },
        { key: 'pre', label: 'Our DOTS', num: true, fmt: function (v) { return IR.dots(v); } }
      ]
    });
  });
});

IR.page('model', function (el) {
  return IR.load('model.json').then(function (m) {
    if (!el.isConnected) return;
    var p = m.params || {}, t = m.test || {}, v = m.valid || {};
    var cal = m.calibration || [];
    el.innerHTML = QK.sectionHead({ tag: 'h1', kicker: 'The model', title: 'How we rate a lifter',
      sub: 'Walk-forward, no look-ahead. Tuned on meets through 2019; 2023\u20132025 is sealed.' }) +
      '<div class="ir-prose">' +
        '<p>Each full-power total is converted to <b>DOTS</b> (Konertz / BVDK 2019), which already adjusts for bodyweight. A lifter\u2019s rating at a meet is the recency-weighted mean of their previous DOTS, shrunk toward the stream average with prior weight k<sub>0</sub> = ' + p.k0 + ' meets and a half-life of ' + p.half_life + ' days. Newcomers start at the training-window mean (' + (p.m0 || '\u2014') + ' DOTS). Meets with fewer than ' + p.min_field + ' scored totals do not update the book.</p>' +
        '<p>Men and women, and raw / wraps / equipped, are separate streams. Tested and untested totals share a stream (the archive tags tested meets; we show that on the meet page) because a tested-only book is too thin outside the IPF.</p>' +
        '<p>' + esc(m.credit || '') + '</p>' +
      '</div>' +
      QK.stats([
        { label: 'Sealed RMSE', value: isNum(t.rmse) ? t.rmse.toFixed(1) : '\u2014', sub: (t.n || 0) + ' totals in 2023\u20132025', signal: true },
        { label: 'Sealed r', value: isNum(t.r) ? t.r.toFixed(2) : '\u2014', sub: 'predicted vs actual DOTS' },
        { label: 'Validation RMSE', value: isNum(v.rmse) ? v.rmse.toFixed(1) : '\u2014', sub: '2020\u20132022' },
        { label: 'Scored totals', value: fmt.num((m.coverage || {}).scored), sub: ((m.coverage || {}).from || '') + ' \u2013 ' + ((m.coverage || {}).to || '') }
      ]) +
      '<section class="qk-section">' + QK.sectionHead({ title: 'Calibration', sub: 'On the sealed years, each dot is a bin of forecasts. A well-calibrated model sits on the diagonal.' }) +
        '<div class="qk-chart" id="ir-cal" style="height:320px"></div></section>' +
      '<section class="qk-section">' + QK.sectionHead({ title: 'Tuning grid' }) + '<div id="ir-grid"></div></section>';
    chartSafe(function () {
      QKC.scatter(el.querySelector('#ir-cal'), {
        points: cal.map(function (b) { return { x: b.pred, y: b.actual, name: fmt.num(b.n) + ' totals', size: 8 + Math.min(18, Math.sqrt(b.n) / 4) }; }),
        xName: 'Our DOTS', yName: 'Actual DOTS', diagonal: true, label: 'Predicted vs actual DOTS'
      });
    });
    if ((m.grid || []).length) {
      QK.table(el.querySelector('#ir-grid'), {
        dense: true, rows: m.grid,
        columns: [
          { key: 'half_life', label: 'Half-life (days)', num: true, raw: true },
          { key: 'k0', label: 'Prior (meets)', num: true, raw: true },
          { key: 'train_rmse', label: 'Train RMSE', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(2) : '\u2014'; } },
          { key: 'valid_rmse', label: 'Valid RMSE', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(2) : '\u2014'; } },
          { key: 'test_rmse', label: 'Test RMSE', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(2) : '\u2014'; } },
          { key: 'test_r', label: 'Test r', num: true, fmt: function (v) { return isNum(v) ? v.toFixed(2) : '\u2014'; } }
        ]
      });
    }
  });
});

IR.page('disclaimer', function (el) {
  var t = document.getElementById('disclaimer-template');
  el.innerHTML = t ? t.innerHTML : '';
});

})();
