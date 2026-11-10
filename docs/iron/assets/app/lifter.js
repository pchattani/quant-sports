/* The Quant Iron — the lifter page (#/player/<id>): the hero, percentiles within the weight class (last year's ring),
 * the tale of the tape against the closest match with verdicts, similar lifters, progression against our expectation,
 * the age curve, the lift-ratio profile, attempts, where the lifter sits in the class, year by year, splits and the meet
 * log with attempts and meet value. Reads players/<id>.json, scout/<stream>.json and lab.json. */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;
var FAMILY = [['rating', 'Our rating'], ['points', 'Points'], ['lifts', 'Lifts'], ['relative', 'Relative strength'], ['attempts', 'Attempts'], ['meet day', 'Meet day'], ['progress', 'Progress'], ['shape', 'Shape (a style, not a grade)']];
var TAPE = ['rt', 'dots', 'total', 'rel_s', 'rel_b', 'rel_d', 'make', 'third', 'beat', 'prog'];
IR.vfmt = function (id, v, M) {
  if (!isNum(v)) return '–';
  var m = (M && M[id]) || {};
  if (m.unit === '%') return v.toFixed(0) + '%';
  if (m.unit === 'kg') return IR.kgn(v) + ' kg';
  if (m.unit === 'x BW') return v.toFixed(2) + '×';
  if (id === 'value' || id === 'prog') return IR.signed(v, 1);
  if (id === 'meets') return String(Math.round(v));
  return v.toFixed(1);
};

function metaOf(pool) {
  var M = {};
  ((pool && pool.metrics) || []).forEach(function (m) { M[m.id] = m; });
  return M;
}

function progChart(el, P) {
  var log = (P.log || []).filter(function (x) { return x.st === P.stream && x.sc && isNum(x.dots); });
  if (!el || !window.QKC || log.length < 2) { if (el) el.innerHTML = QK.empty('Fewer than two scored meets', ''); return; }
  QKC.line(el, { x: log.map(function (x) { return x.date; }), xType: 'category',
    series: [{ name: 'DOTS at the meet', data: log.map(function (x) { return x.dots; }), color: IR.col(1) },
      { name: 'Our expectation before it', data: log.map(function (x) { return isNum(x.exp) ? x.exp : null; }), color: IR.col('ink-3'), dash: true }],
    yName: 'DOTS', xName: 'Meet date', endLabels: false, yFmt: function (v) { return fmt.num(v, 0); } });
}
function totalChart(el, P) {
  var log = (P.log || []).filter(function (x) { return x.st === P.stream && isNum(x.tot); });
  if (!el || !window.QKC || log.length < 2) { if (el) el.innerHTML = QK.empty('Fewer than two totals', ''); return; }
  QKC.line(el, { x: log.map(function (x) { return x.date; }), xType: 'category',
    series: [{ name: 'Squat', data: log.map(function (x) { return x.sq; }), color: IR.col(1) }, { name: 'Bench', data: log.map(function (x) { return x.bp; }), color: IR.col(3) },
      { name: 'Deadlift', data: log.map(function (x) { return x.dl; }), color: IR.col(5) }],
    yName: 'Kilograms (best of each lift)', xName: 'Meet date', endLabels: false, yFmt: function (v) { return fmt.num(v, 0); } });
}
function ageChart(el, P, lab) {
  var cur = ((lab.ages || {})[P.stream]) || null;
  var log = (P.log || []).filter(function (x) { return x.st === P.stream && x.sc && isNum(x.dots); });
  if (!el || !window.QKC || !cur || !isNum(P.age) || log.length < 2) { if (el) el.innerHTML = QK.empty('No age curve for this lifter', 'The archive has no age for this lifter, or too few meets.'); return; }
  var now = new Date(QK.now()).getTime();
  var pts = log.map(function (x) { var t = new Date(x.date + 'T12:00:00').getTime(); return [Math.round((P.age - (now - t) / (365.25 * 864e5)) * 10) / 10, x.dots]; });
  var ages = cur.ages, tot = cur.total;
  /* anchor the stream's within-lifter curve at the lifter's own mean DOTS and mean age */
  var ma = pts.reduce(function (s, p) { return s + p[0]; }, 0) / pts.length, md = pts.reduce(function (s, p) { return s + p[1]; }, 0) / pts.length;
  var near = 0, bd = 1e9;
  ages.forEach(function (a, i) { if (Math.abs(a - ma) < bd) { bd = Math.abs(a - ma); near = i; } });
  var shift = md - tot[near];
  QKC.mount(el, function (T) {
    var ax = QKC.axis ? QKC.axis(T, {}) : {};
    return { grid: { left: 54, right: 20, top: 30, bottom: 46 }, tooltip: { trigger: 'item' },
      legend: { top: 0, textStyle: { color: T.ink2 } },
      xAxis: Object.assign({}, ax, { type: 'value', name: 'Age (years)', nameLocation: 'middle', nameGap: 28, min: Math.max(14, Math.floor(Math.min(ma - 8, pts[0][0] - 2))), max: Math.min(75, Math.ceil(Math.max(ma + 12, pts[pts.length - 1][0] + 4))) }),
      yAxis: Object.assign({}, ax, { type: 'value', name: 'DOTS', nameLocation: 'middle', nameGap: 40, scale: true }),
      series: [{ name: 'The typical path from here (stream, within-lifter)', type: 'line', showSymbol: false, data: ages.map(function (a, i) { return [a, Math.round((tot[i] + shift) * 10) / 10]; }), lineStyle: { type: 'dashed', color: T.ink3 }, itemStyle: { color: T.ink3 } },
        { name: P.name, type: 'scatter', data: pts, symbolSize: 8, itemStyle: { color: T.signal || '#7d93ff' } }] };
  });
}
function attemptChart(el, P) {
  var made = [0, 0, 0, 0, 0, 0, 0, 0, 0], tried = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  (P.log || []).forEach(function (x) { if (x.st !== P.stream) return; (x.a || []).forEach(function (v, i) { if (isNum(v) && v !== 0) { tried[i] += 1; if (v > 0) made[i] += 1; } }); });
  if (!el || !window.QKC || tried.reduce(function (s, x) { return s + x; }, 0) < 9) { if (el) el.innerHTML = QK.empty('No attempts reported', 'This lifter’s federations report best lifts only.'); return; }
  QKC.bar(el, { cats: ['Squat 1', 'Squat 2', 'Squat 3', 'Bench 1', 'Bench 2', 'Bench 3', 'Dead 1', 'Dead 2', 'Dead 3'],
    series: [{ name: 'Made', data: made.map(function (x, i) { return tried[i] ? Math.round(1000 * x / tried[i]) / 10 : null; }), color: IR.col(1) }],
    valName: 'Attempts made (%)', catName: 'Lift and attempt', labels: true, fmt: function (v) { return Math.round(v) + '%'; } });
}
function ratioChart(el, P, lab) {
  var C = P.cur, rows = (((lab.ratios || {})[P.stream]) || []).filter(function (r) { return r.cls === (C && C.cls); })[0];
  if (!el || !window.QKC || !C || !isNum(C.v.sh_s)) { if (el) el.innerHTML = QK.empty('No lift shares', 'Needs a full-power total with all three lifts.'); return; }
  QKC.bar(el, { cats: ['Squat', 'Bench', 'Deadlift'], series: [{ name: P.name, data: [C.v.sh_s, C.v.sh_b, C.v.sh_d], color: IR.col(1) }].concat(rows ? [{ name: 'The class median (' + C.cls + ' kg)', data: [rows.squat[1], rows.bench[1], rows.dead[1]], color: IR.col('ink-4'), lo: [rows.squat[0], rows.bench[0], rows.dead[0]], hi: [rows.squat[2], rows.bench[2], rows.dead[2]] }] : []),
    valName: 'Share of the total (%)', catName: 'Lift', labels: true, fmt: function (v) { return v.toFixed(1) + '%'; } });
}
function peerChart(el, P, pool, key, M) {
  if (!el || !window.QKC || !QKC.distribution || !pool || !P.cur) return;
  var cols = pool.cols || [], ic = cols.indexOf('cls'), ik = cols.indexOf(key);
  var vs = (pool.rows || []).filter(function (r) { return r[ic] === P.cur.cls && isNum(r[ik]); }).map(function (r) { return r[ik]; });
  var me = P.cur.v[key];
  if (vs.length < 10 || !isNum(me)) { el.innerHTML = QK.empty('Too few lifters in the pool to compare', ''); return; }
  var m = M[key] || {};
  QKC.distribution(el, { values: vs, binCount: 22, lowerBetter: m.dir === 'lower', fmt: function (v) { return IR.vfmt(key, v, M); },
    xName: (m.label || key) + ' · ' + vs.length + ' ranked ' + IR.STREAMS[P.stream].toLowerCase() + ' lifters at ' + P.cur.cls + ' kg', yName: 'Lifters',
    marks: [{ x: me, label: QK.surname(P.name) }], label: 'Where ' + P.name + ' sits' });
}

IR.page('player', function (el, params) {
  var pid = params.id;
  return IR.load('players/' + encodeURIComponent(pid) + '.json').then(function (P) {
    return Promise.all([IR.load('scout/' + P.stream + '.json').catch(function () { return null; }), IR.load('lab.json').catch(function () { return {}; })]).then(function (res) {
      var pool = res[0], lab = res[1] || {};
      var M = metaOf(pool);
      var C = P.cur;
      document.title = P.name + ' · ' + IR.SITE;
      var meta = [];
      if (isNum(P.age)) meta.push(['Age', String(P.age)]);
      if (isNum(P.bw)) meta.push(['Bodyweight', IR.kg(P.bw)]);
      if (P.fed) meta.push(['Federation', P.fed]);
      meta.push(['Meets', String(P.n)]);
      if (isNum(P.tested)) meta.push(['Tested meets', Math.round(P.tested * 100) + '%']);
      meta.push(['Since', IR.year(P.first)]);
      var short = '';
      if (C && C.pc) {
        var rel = ['dots', 'rel_s', 'rel_b', 'rel_d', 'make', 'third', 'beat', 'prog', 'cons', 'bomb'];
        var ks = rel.filter(function (k) { return isNum(C.pc[k]); }).sort(function (a, b) { return C.pc[b] - C.pc[a]; });
        var lab1 = function (k) { return ((M[k] || {}).label || k).toLowerCase(); };
        if (ks.length >= 3) short = P.name + ' stands out among ' + P.cur.cls + ' kg ' + IR.STREAMS[P.stream].replace(' · ', ', ').toLowerCase() + ' lifters on ' + lab1(ks[0]) + ' and ' + lab1(ks[1]) + ', and is weakest on ' + lab1(ks[ks.length - 1]) + '.' +
          (isNum(P.rt) ? ' We expect about ' + IR.dots(P.rt) + ' DOTS at the next meet' + (isNum(P.bw) ? ' (a total near ' + IR.kg(Math.round(P.rt / (P.best / P.best_total || 1))) + ' at the same bodyweight)' : '') + '.' : '');
      } else short = P.name + ' has ' + P.n + ' scored meets in our data; percentiles need two in the last two years.';
      var html = '<nav class="ir-crumb"><a href="#/scout?s=' + P.stream + '">Scouting Room</a> / ' + esc(P.name) + '</nav>';
      html += QK.playerHeader({ name: P.name, face: P.cls || '', kicker: IR.STREAMS[P.stream] + (P.cls ? ' · ' + P.cls + ' kg class' : ''),
        team: { name: P.cc || 'Country not listed', abbr: P.cc ? String(P.cc).slice(0, 3).toUpperCase() : '' }, meta: meta,
        strip: [{ label: 'Our rating', value: IR.dots(P.rt), pctl: C && C.pc ? C.pc.rt : null, signal: true, sub: P.rank ? 'No. ' + P.rank + ' of ' + P.of : 'not ranked' },
          { label: 'Best total', value: IR.kg(P.best_total), sub: IR.kgn(P.best_sq) + ' / ' + IR.kgn(P.best_bp) + ' / ' + IR.kgn(P.best_dl) },
          { label: 'Best DOTS', value: IR.dots(P.best), pctl: C && C.pc ? C.pc.dots : null },
          { label: 'A year', value: IR.signed(P.d365), sub: 'rating change' },
          { label: 'To No. 1', value: isNum(P.need1) ? IR.kg(P.need1) : (P.rank === 1 ? 'No. 1' : '–'), sub: isNum(P.need_up) ? IR.kg(P.need_up) + ' to go up one' : '' }],
        short: short, follow: IR.followItem(P.pid, P.name, P.cc) });
      var prev = P.prev && P.prev.pc ? P.prev : null;
      if (C && C.v) {
        var groups = FAMILY.map(function (f) {
          var rows = Object.keys(M).filter(function (k) { return M[k].family === f[0] && isNum(C.v[k]) && isNum(C.pc[k]); }).map(function (k) {
            return { label: M[k].label, pctl: C.pc[k], value: IR.vfmt(k, C.v[k], M), tip: M[k].tip + (M[k].dir === 'lower' ? ' (lower is better; the percentile is turned so higher is better)' : ''),
              early: C.n < 3, prev: prev && isNum(prev.pc[k]) ? prev.pc[k] : undefined };
          });
          return { label: f[1], rows: rows };
        }).filter(function (g) { return g.rows.length; });
        html += '<div class="qk-g75 ir-gap"><div>' + QK.pctCard({ title: 'Against the ' + C.cls + ' kg class', kicker: 'Last two years', peer: C.peers + ' active ' + IR.STREAMS[P.stream].toLowerCase() + ' lifters at ' + C.cls + ' kg', ringLabel: prev ? String(prev.y) : undefined,
          sample: C.n + ' meets since ' + IR.date(C.from), groups: groups }) +
          QK.explain('<b>How sure are we?</b> ' + C.n + ' meets is ' + (C.n < 4 ? 'a small sample: rates like attempts made and beating our forecast are pulled toward the average, and a dashed box marks a percentile still settling.' : 'a fair sample; attempt rates still swing from meet to meet.')) +
          '</div><div id="pl-tape"></div></div>';
      }
      html += '<div class="qk-g2 ir-gap">' + U.card('Progression', 'DOTS at each meet in ' + IR.STREAMS[P.stream].toLowerCase() + ', and what we expected before it (dashed).', U.chart('pl-prog', 300, 'DOTS by meet')) +
        U.card('Lifts, meet by meet', 'Best squat, bench and deadlift at each meet (kg).', U.chart('pl-lifts', 300, 'Lifts by meet')) + '</div>';
      html += '<div class="qk-g2 ir-gap">' + U.card('The age curve', 'Each dot a meet at the lifter’s age; the dashed line is how ' + IR.STREAMS[P.stream].toLowerCase() + ' lifters typically change with age (within-lifter, since 2005), anchored on this lifter. Peak age for the stream: ' + esc(String((((lab.ages || {})[P.stream] || {}).peak || {}).total || '–')) + '.', U.chart('pl-age', 300, 'DOTS by age')) +
        U.card('The shape of the total', 'Squat, bench and deadlift as shares of the best total, against the class median (whiskers: the middle half). A style, not a grade.', U.chart('pl-ratio', 300, 'Lift shares')) + '</div>';
      html += '<div class="qk-g2 ir-gap">' + U.card('Attempts', 'Share made by lift and attempt, every meet with attempts reported.', U.chart('pl-att', 280, 'Attempts made')) +
        U.card('Among the class', 'Every ranked lifter in the class on one metric, with ' + esc(QK.surname(P.name)) + ' marked.', '<div class="qk-seg" id="pl-pk" role="group" aria-label="Metric" style="margin-bottom:10px">' +
          [['rt', 'Rating'], ['total', 'Total'], ['rel', 'Total/BW'], ['make', 'Made'], ['prog', 'Progress']].map(function (k, i) { return '<button type="button" data-value="' + k[0] + '" aria-pressed="' + (i === 0) + '">' + esc(k[1]) + '</button>'; }).join('') + '</div>' + U.chart('pl-peer', 240, 'Class distribution')) + '</div>';
      html += '<div class="qk-g2 ir-gap">' + U.card('Most similar lifters', 'Closest in the same class on the percentile profile: relative squat, bench and deadlift, attempts made, progress, DOTS and steadiness.', (P.similar || []).length ? '<ul class="ir-list">' + P.similar.map(function (s) {
        return '<li>' + IR.playerLink(s.pid, s.n, s.pg) + ' <small>' + esc(s.cc || '') + '</small><span class="v" title="Average gap in percentile points">' + IR.dots(s.d) + ' pts apart</span></li>';
      }).join('') + '</ul>' : QK.empty('Not enough meets to compare', '')) +
        U.card('Splits', 'Meets in ' + IR.STREAMS[P.stream].toLowerCase() + ': average and best DOTS, best total, attempts made and meet value (DOTS above our expectation).', (P.splits || []).length ? U.table(
          [{ label: 'Split', align: 'left' }, { label: 'Meets' }, { label: 'Avg DOTS' }, { label: 'Best' }, { label: 'Total' }, { label: 'Made' }, { label: 'Value' }],
          P.splits.map(function (x) { return [{ v: x.label, html: esc(x.label) }, { v: x.n, html: String(x.n) }, { v: x.dots || 0, html: IR.dots(x.dots) }, { v: x.best || 0, html: IR.dots(x.best) }, { v: x.tot || 0, html: IR.kgn(x.tot) }, { v: x.made || 0, html: IR.pctv(x.made) }, { v: isNum(x.val) ? x.val : -999, html: '<span class="' + IR.cls(x.val) + '">' + IR.signed(x.val) + '</span>' }]; }), { cls: 'dense' }) : QK.empty('No splits', ''), { flush: true }) + '</div>';
      html += U.card('Year by year', 'Bests in each calendar year (' + IR.STREAMS[P.stream].toLowerCase() + '). Value: average DOTS above our pre-meet expectation.', U.table(
        [{ label: 'Year' }, { label: 'Meets' }, { label: 'Class' }, { label: 'BW' }, { label: 'Squat' }, { label: 'Bench' }, { label: 'Dead' }, { label: 'Total' }, { label: 'DOTS' }, { label: 'GL' }, { label: 'Wilks' }, { label: 'Made' }, { label: 'Value' }],
        (P.seasons || []).slice().reverse().map(function (s) {
          return [{ v: s.y, html: String(s.y) }, { v: s.n, html: String(s.n) }, { v: s.cls, html: esc(s.cls || '–') }, { v: s.bw || 0, html: IR.kgn(s.bw) }, { v: s.sq || 0, html: IR.kgn(s.sq) }, { v: s.bp || 0, html: IR.kgn(s.bp) }, { v: s.dl || 0, html: IR.kgn(s.dl) },
            { v: s.tot || 0, html: '<b>' + IR.kgn(s.tot) + '</b>' }, { v: s.dots || 0, html: IR.dots(s.dots) }, { v: s.gl || 0, html: IR.dots(s.gl) }, { v: s.wilks || 0, html: IR.dots(s.wilks) }, { v: s.made || 0, html: IR.pctv(s.made) },
            { v: isNum(s.val) ? s.val : -999, html: '<span class="' + IR.cls(s.val) + '">' + IR.signed(s.val) + '</span>' }];
        }), { cls: 'dense' }), { flush: true });
      html += U.card('Meet log', 'Every full-power meet in our data, newest first, with the nine attempts (struck through: missed). Expected: our total before the meet, from earlier meets only. ★ PR: a lifetime best.', U.table(
        [{ label: 'Date', align: 'left' }, { label: 'Meet', align: 'left' }, { label: 'Class' }, { label: 'BW' }, { label: 'Attempts', align: 'left' }, { label: 'Total' }, { label: 'DOTS' }, { label: 'Expected' }, { label: 'Value' }, { label: 'Place' }],
        (P.log || []).slice().reverse().map(function (x) {
          return [{ v: x.date, html: esc(IR.date(x.date)) }, { v: x.mn, html: IR.eventLink(x.meet, x.mn) + ' <small class="qk-muted">' + esc(x.fed || '') + (x.st !== P.stream ? ' · ' + esc(IR.STREAMS[x.st] || '') : '') + '</small>' },
            { v: x.cls, html: esc(x.cls || '–') }, { v: x.bw || 0, html: IR.kgn(x.bw) }, { v: x.tot || 0, html: IR.attempts(x.a) },
            { v: x.tot || 0, html: x.bomb ? '<span class="qk-muted">bombed</span>' : '<b>' + IR.kgn(x.tot) + '</b>' + (x.pr ? ' <span class="ir-pr">★</span>' : '') },
            { v: x.dots || 0, html: IR.dots(x.dots) }, { v: x.exp_kg || 0, html: IR.kgn(x.exp_kg) }, { v: isNum(x.dots) && isNum(x.exp) ? x.dots - x.exp : -999, html: IR.delta(x.dots, x.exp) },
            { v: parseInt(x.pl, 10) || 999, html: esc(x.pl || '–') }];
        }), { cls: 'dense', maxHeight: 720 }), { flush: true });
      el.innerHTML = html;
      U.wire(el);
      progChart(QK.$('#pl-prog', el), P);
      totalChart(QK.$('#pl-lifts', el), P);
      ageChart(QK.$('#pl-age', el), P, lab);
      ratioChart(QK.$('#pl-ratio', el), P, lab);
      attemptChart(QK.$('#pl-att', el), P);
      peerChart(QK.$('#pl-peer', el), P, pool, 'rt', M);
      var sg = QK.$('#pl-pk', el);
      if (sg) QK.seg(sg, function (k) { peerChart(QK.$('#pl-peer', el), P, pool, k, M); });
      // the tale of the tape against the closest match
      var sim = (P.similar || []).filter(function (x) { return x.pg; })[0], tapeEl = QK.$('#pl-tape', el);
      if (sim && tapeEl && C) {
        IR.load('players/' + encodeURIComponent(sim.pid) + '.json').then(function (O) {
          if (!U.alive(tapeEl) || !O.cur) return;
          var ids = TAPE.filter(function (k) { return isNum(C.v[k]) && isNum(O.cur.v[k]); });
          tapeEl.innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: esc(QK.surname(P.name) + ' or ' + QK.surname(O.name) + '?'), html: true }) +
            QK.tape({ left: { name: P.name, short: QK.surname(P.name), sub: (P.cc || '') + ' · ' + P.cls + ' kg', href: IR.playerHref(P.pid) },
              right: { name: O.name, short: QK.surname(O.name), sub: (O.cc || '') + ' · ' + O.cls + ' kg', href: IR.playerHref(O.pid) },
              rows: ids.map(function (k) { return { label: (M[k] || {}).label || k, a: C.v[k], b: O.cur.v[k], ta: IR.vfmt(k, C.v[k], M), tb: IR.vfmt(k, O.cur.v[k], M), pa: C.pc[k], pb: O.cur.pc[k] }; }) }) +
            QK.verdicts([[P, C, O.cur], [O, O.cur, C]].map(function (x) {
              var best = null, gap = 0;
              ids.forEach(function (k) { var a = x[1].pc[k], b = x[2].pc[k]; if (isNum(a) && isNum(b) && a - b > gap) { gap = a - b; best = k; } });
              return best ? { title: 'Better on ' + ((M[best] || {}).short || best).toLowerCase(), who: QK.surname(x[0].name), text: ((M[best] || {}).label || best).toLowerCase() + ' (' + IR.vfmt(best, x[1].v[best], M) + ', ' + QK.ordinal(Math.round(x[1].pc[best])) + ' percentile).' } : null;
            }));
        }, function () { /* the match's page is not built */ });
      }
    });
  });
});
})();
