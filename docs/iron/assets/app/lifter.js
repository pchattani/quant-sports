/* The Quant Iron — the lifter page (#/player/<id>), in the Rink's order: the hero with the black strip and the short
 * version; percentiles within the weight class (last year's ring) beside the tale of the tape against the closest
 * match (chips switch), verdicts and similar lifters; the last meet against our forecast beside DOTS meet by meet;
 * the meet log ("Every meet", the best meet highlighted); then lifts, the age curve, the lift shares, attempts, where
 * the lifter sits in the class, splits and year by year. Reads players/<id>.json, scout/<stream>.json, lab.json and
 * build.json (the "as of"). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;
var FAMILY = [['rating', 'Our rating'], ['points', 'Points'], ['lifts', 'Lifts'], ['relative', 'Relative strength'], ['attempts', 'Attempts'], ['meet day', 'Meet day'], ['progress', 'Progress'], ['shape', 'Shape (a style, not a grade)']];
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
    yName: 'DOTS', xName: 'Meet date', endLabels: false, legend: true, yFmt: function (v) { return fmt.num(v, 0); } });
}
function totalChart(el, P) {
  var log = (P.log || []).filter(function (x) { return x.st === P.stream && isNum(x.tot); });
  if (!el || !window.QKC || log.length < 2) { if (el) el.innerHTML = QK.empty('Fewer than two totals', ''); return; }
  QKC.line(el, { x: log.map(function (x) { return x.date; }), xType: 'category',
    series: [{ name: 'Squat', data: log.map(function (x) { return x.sq; }), color: IR.col(1) }, { name: 'Bench', data: log.map(function (x) { return x.bp; }), color: IR.col(3) },
      { name: 'Deadlift', data: log.map(function (x) { return x.dl; }), color: IR.col(5) }],
    yName: 'Kilograms (best of each lift)', xName: 'Meet date', endLabels: false, legend: true, yFmt: function (v) { return fmt.num(v, 0); } });
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
    valName: 'Share of the total (%)', catName: 'Lift', labels: true, legend: true, fmt: function (v) { return v.toFixed(1) + '%'; } });
}
function peerChart(el, P, pool, key, M) {
  if (!el || !window.QKC || !QKC.distribution || !pool || !P.cur) return;
  var cols = pool.cols || [], ic = cols.indexOf('cls'), ik = cols.indexOf(key);
  var vs = (pool.rows || []).filter(function (r) { return r[ic] === P.cur.cls && isNum(r[ik]); }).map(function (r) { return r[ik]; });
  var me = P.cur.v[key];
  if (vs.length < 10 || !isNum(me)) { el.innerHTML = QK.empty('Too few lifters in the pool to compare', ''); return; }
  var m = M[key] || {};
  QKC.distribution(el, { values: vs, binCount: 22, lowerBetter: m.dir === 'lower', fmt: function (v) { return IR.vfmt(key, v, M); },
    xName: (m.label || key) + ' · ' + vs.length + ' ' + IR.STREAMS[P.stream].toLowerCase() + ' lifters at ' + P.cur.cls + ' kg in the Scouting Room pool', yName: 'Lifters',
    marks: [{ x: me, label: QK.surname(P.name) }], label: 'Where ' + P.name + ' sits' });
}

/* The tale of the tape's rows: our rating and the points, relative strength, then attempts and meet day */
var TAPE_GROUPS = [['Rating and points', ['rt', 'dots', 'total']], ['Relative strength', ['rel_s', 'rel_b', 'rel_d']], ['Attempts and meet day', ['make', 'third', 'beat', 'prog']]];

/* who to put on the tape: the closest profiles in the class that have a page; when none has one, the lifters with a
 * page nearest on our rating in the same stream and class (the Scouting Room pool, already loaded) */
function tapeCands(P, C, pool) {
  var out = [], seen = {};
  (P.similar || []).forEach(function (s) { if (s.pg && !seen[s.pid]) { seen[s.pid] = 1; out.push({ pid: s.pid, name: s.n, kind: 'profile', d: s.d }); } });
  if (!out.length && pool && C && isNum(P.rt)) {
    var cols = pool.cols || [], ii = cols.indexOf('id'), inn = cols.indexOf('n'), ic = cols.indexOf('cls'), ip = cols.indexOf('pg'), ir = cols.indexOf('rt');
    (pool.rows || []).filter(function (r) { return r[ic] === C.cls && r[ip] && r[ii] !== P.pid && isNum(r[ir]); })
      .sort(function (a, b) { return Math.abs(a[ir] - P.rt) - Math.abs(b[ir] - P.rt); }).slice(0, 3)
      .forEach(function (r) { out.push({ pid: r[ii], name: r[inn], kind: 'rating', rt: r[ir] }); });
  }
  return out.slice(0, 3);
}
function inPool(pool, pid) {
  var ii = ((pool && pool.cols) || []).indexOf('id');
  return ii >= 0 && (pool.rows || []).some(function (r) { return r[ii] === pid; });
}

/* the nine attempts as plain text for the CSV ("140 152.5 160 · 85 92.5 -95 · ..."; negative = missed) */
function attText(a) {
  if (!a || !a.some(isNum)) return 'not reported';
  var g = [];
  for (var i = 0; i < 3; i++) g.push(a.slice(i * 3, i * 3 + 3).map(function (v) { return isNum(v) && v !== 0 ? String(v) : '-'; }).join(' '));
  return g.join(' · ');
}
function madeOf(a) {
  var m = 0, t = 0, by = [[0, 0], [0, 0], [0, 0]];
  (a || []).forEach(function (v, i) { if (isNum(v) && v !== 0) { t += 1; by[Math.floor(i / 3)][1] += 1; if (v > 0) { m += 1; by[Math.floor(i / 3)][0] += 1; } } });
  return { m: m, t: t, by: by };
}
function placeWords(pl) {
  var n = parseInt(pl, 10);
  if (!isNaN(n) && String(n) === String(pl)) return QK.ordinal(n);
  return pl === 'DQ' ? 'Bombed out' : pl === 'G' ? 'Guest lifter' : pl === 'NS' ? 'No show' : (pl || '');
}

/* the last meet: the result against the total we expected before it (earlier meets only) */
function lastMeetHTML(P) {
  var log = P.log || [], x = log[log.length - 1];
  if (!x) return '';
  var pw = placeWords(x.pl), mm = madeOf(x.a);
  var ttl = x.bomb ? 'Bombed out' : (/^\d/.test(pw) ? pw + ', ' + IR.kg(x.tot) : IR.kg(x.tot) + (x.pl === 'G' ? ' as a guest' : ''));
  var diff = isNum(x.dots) && isNum(x.exp) ? x.dots - x.exp : null;
  var tiles = [
    { label: 'Total', value: x.bomb ? 'No total' : IR.kg(x.tot), text: !!x.bomb, sub: x.bomb ? 'bombed out: three misses on one lift' : 'squat ' + IR.kgn(x.sq) + ' · bench ' + IR.kgn(x.bp) + ' · deadlift ' + IR.kgn(x.dl) + (x.pr ? ' · a lifetime best' : '') },
    { label: 'DOTS', value: IR.dots(x.dots), sub: isNum(x.gl) ? 'IPF GL ' + IR.dots(x.gl) + (isNum(x.wilks) ? ' · Wilks ' + IR.dots(x.wilks) : '') : 'points for the total at ' + IR.kg(x.bw) },
    isNum(diff) ? { label: 'Against our forecast', value: IR.signed(diff), unit: 'DOTS', sub: 'We expected ' + IR.dots(x.exp) + ' DOTS' + (isNum(x.exp_kg) ? ' (' + IR.kg(x.exp_kg) + ')' : '') + ', from earlier meets only.' } : null,
    mm.t ? { label: 'Attempts made', value: mm.m + ' of ' + mm.t, sub: 'squat ' + mm.by[0][0] + '/' + mm.by[0][1] + ' · bench ' + mm.by[1][0] + '/' + mm.by[1][1] + ' · deadlift ' + mm.by[2][0] + '/' + mm.by[2][1] } : null
  ];
  var meta = [IR.date(x.date), x.fed, (x.cls ? x.cls + ' kg class' : '') + (isNum(x.bw) ? ' at ' + IR.kg(x.bw) : ''), x.div, x.t ? 'tested' : 'untested', x.st !== P.stream ? IR.STREAMS[x.st] : '', IR.asof()].filter(Boolean);
  var why = isNum(diff) ? (Math.abs(diff) < 10 ? 'Close to our number: within 10 DOTS.' : diff > 0 ? 'Above our number by ' + IR.dots(diff) + ' DOTS.' : 'Below our number by ' + IR.dots(-diff) + ' DOTS.') : (x.bomb ? 'No total, so no comparison with our forecast.' : 'No forecast: the first meet in our data.');
  return QK.sectionHead({ kicker: 'Last meet', title: ttl }) +
    '<article class="qk-card ir-card ir-last"><div class="qk-card-body"><div class="ir-last-mn">' + (x.meet ? IR.eventLink(x.meet, x.mn) : esc(x.mn)) + '</div><div class="ir-meta">' + meta.map(function (s) { return '<span>' + esc(s) + '</span>'; }).join('') + '</div>' +
    '<div class="ir-last-tiles">' + QK.stats(tiles) + '</div>' +
    '<div class="ir-last-att"><span class="ir-last-k">Attempts (kg; struck through: missed)</span>' + IR.attempts(x.a) + '</div>' +
    '<p class="ir-last-why">' + esc(why) + '</p></div></article>';
}

/* the meet log: every meet in the data, newest first, the best meet on DOTS highlighted (a qk-table, as the Rink's
 * game log); data-csv keeps the CSV clean where a cell carries chips or a sub-line */
function meetLogHTML(P) {
  var log = P.log || [];
  if (!log.length) return '';
  var bestI = -1, bestD = -1;
  log.forEach(function (x, i) { if (x.st === P.stream && x.sc && isNum(x.dots) && x.dots > bestD) { bestD = x.dots; bestI = i; } });
  var b = bestI >= 0 ? log[bestI] : null;
  var th = function (lab, num, tip) { return '<th scope="col"' + (num ? ' class="num"' : '') + ' aria-sort="none"><button type="button">' + (tip ? '<span data-tip="' + esc(tip) + '">' + esc(lab) + '</span>' : esc(lab)) + '</button></th>'; };
  var td = function (v, html, o) { o = o || {}; return '<td data-v="' + esc(v === null || v === undefined ? '' : v) + '"' + (o.num ? ' class="num"' : '') + (o.csv !== undefined ? ' data-csv="' + esc(o.csv) + '"' : '') + '>' + html + '</td>'; };
  var rows = log.map(function (x, i) { return [x, i]; }).reverse().map(function (p) {
    var x = p[0], d = isNum(x.dots) && isNum(x.exp) ? x.dots - x.exp : null;
    return '<tr' + (p[1] === bestI ? ' class="hl"' : '') + '>' + td(x.date, esc(IR.date(x.date))) +
      td(x.mn, IR.eventLink(x.meet, x.mn) + ' <small class="qk-muted">' + esc(x.fed || '') + (x.st !== P.stream ? ' · ' + esc(IR.STREAMS[x.st] || '') : '') + '</small>', { csv: x.mn + (x.fed ? ' (' + x.fed + ')' : '') }) +
      td(x.cls, esc(x.cls || '–')) + td(isNum(x.bw) ? x.bw : '', IR.kgn(x.bw), { num: true }) + td(madeOf(x.a).m, IR.attempts(x.a), { csv: attText(x.a) }) +
      td(isNum(x.tot) ? x.tot : 0, x.bomb ? '<span class="qk-muted">bombed</span>' : '<b>' + IR.kgn(x.tot) + '</b>' + (x.pr ? ' <span class="ir-pr" title="Lifetime best total">★</span>' : ''), { num: true, csv: x.bomb ? 'bombed' : (isNum(x.tot) ? String(x.tot) : '') + (x.pr ? ' PR' : '') }) +
      td(isNum(x.dots) ? x.dots : '', IR.dots(x.dots), { num: true }) + td(isNum(x.exp_kg) ? x.exp_kg : '', IR.kgn(x.exp_kg), { num: true }) +
      td(isNum(d) ? d : -999, IR.delta(x.dots, x.exp) || '–', { num: true, csv: isNum(d) ? d.toFixed(1) : '' }) + td(parseInt(x.pl, 10) || 999, esc(x.pl || '–'), { num: true }) + '</tr>';
  }).join('');
  var sub = (b ? IR.dots(b.dots) + ' DOTS (' + IR.kg(b.tot) + ' at ' + IR.kg(b.bw) + ') at ' + esc(b.mn) + ', ' + esc(IR.date(b.date)) + ', is the best meet in ' + esc(IR.STREAMS[P.stream].toLowerCase()) + ' (highlighted). ' : '') +
    'Newest first. Expected: the total we forecast before the meet, from earlier meets only; v forecast: DOTS above or below it. ★ a lifetime best total.';
  return U.sec('Meet log', 'Every meet', sub, '<article class="qk-card ir-card"><div class="qk-card-body flush"><div class="qk-table-wrap" style="--table-max:720px"><table class="qk-table dense ir-log"><thead><tr>' +
    th('Date') + th('Meet') + th('Class') + th('BW (kg)', true) + th('Attempts (kg)', false, 'Squat, bench and deadlift, three attempts each; struck through: missed') + th('Total (kg)', true) + th('DOTS', true) +
    th('Expected (kg)', true, 'Our forecast of the total before the meet, from earlier meets only') + th('v forecast (DOTS)', true, 'DOTS at the meet minus the DOTS we expected before it') + th('Place', true) +
    '</tr></thead><tbody>' + rows + '</tbody></table></div></div></article>');
}

IR.page('player', function (el, params) {
  var pid = params.id;
  return IR.load('players/' + encodeURIComponent(pid) + '.json').then(function (P) {
    return Promise.all([IR.load('scout/' + P.stream + '.json').catch(function () { return null; }), IR.load('lab.json').catch(function () { return {}; }), IR.built()]).then(function (res) {
      var pool = res[0], lab = res[1] || {};
      var M = metaOf(pool);
      var C = P.cur;
      var sur = QK.surname(P.name);
      var streamLow = IR.STREAMS[P.stream].toLowerCase();
      document.title = P.name + ' · ' + IR.SITE;
      var meta = [];
      if (isNum(P.age)) meta.push(['Age', String(P.age)]);
      if (isNum(P.bw)) meta.push(['Bodyweight', IR.kg(P.bw)]);
      if (P.fed) meta.push(['Federation', P.fed]);
      meta.push(['Meets', String(P.n)]);
      if (isNum(P.tested)) meta.push(['Tested meets', Math.round(P.tested * 100) + '%']);
      meta.push(['Since', IR.year(P.first)]);
      /* a DOTS score converts to kilograms at one bodyweight: the last scored meet's (DOTS / total) */
      var lastSc = (P.log || []).filter(function (x) { return x.st === P.stream && x.sc && isNum(x.dots) && isNum(x.tot) && x.tot > 0; }).pop();
      var short = '';
      if (C && C.pc) {
        var rel = ['dots', 'rel_s', 'rel_b', 'rel_d', 'make', 'third', 'beat', 'prog', 'cons', 'bomb'];
        var ks = rel.filter(function (k) { return isNum(C.pc[k]); }).sort(function (a, b) { return C.pc[b] - C.pc[a]; });
        var lab1 = function (k) { return ((M[k] || {}).label || k).toLowerCase(); };
        if (ks.length >= 3) short = P.name + ' stands out among ' + C.cls + ' kg ' + IR.STREAMS[P.stream].replace(' · ', ', ').toLowerCase() + ' lifters on ' + lab1(ks[0]) + ' and ' + lab1(ks[1]) + ', and is weakest on ' + lab1(ks[ks.length - 1]) + '.' +
          (isNum(P.rt) ? ' We expect about ' + IR.dots(P.rt) + ' DOTS at the next meet' + (lastSc ? ' (a total near ' + IR.kg(Math.round(P.rt * lastSc.tot / lastSc.dots / 2.5) * 2.5) + ' at the last meet’s ' + IR.kg(lastSc.bw) + ' bodyweight)' : '') + '.' : '');
      } else short = P.name + ' has ' + P.n + ' scored meets in our data; percentiles need two in the last two years.';
      /* the strip: five numbers, each with its unit and peer group; "A year" and "To No. 1" only exist for ranked
         lifters, so the others get two real profile numbers in their place */
      var pc = C && C.pc ? C.pc : {};
      var strip = [{ label: 'Our rating', value: IR.dots(P.rt), pctl: isNum(pc.rt) ? pc.rt : null, signal: true, sub: (P.rank ? 'No. ' + P.rank + ' of ' + P.of + ' ranked' : 'not ranked') + ' · DOTS we expect at the next meet', tip: 'Our forecast of the DOTS at the lifter’s next meet, from every meet before today. The percentile is against active ' + (C ? C.cls + ' kg ' : '') + streamLow + ' lifters.' },
        { label: 'Best total', value: IR.kg(P.best_total), sub: 'lifetime · best lifts ' + IR.kgn(P.best_sq) + ' / ' + IR.kgn(P.best_bp) + ' / ' + IR.kgn(P.best_dl) + ' kg' },
        C && isNum(C.v.dots) ? { label: 'Best DOTS', value: IR.dots(C.v.dots), pctl: isNum(pc.dots) ? pc.dots : null, sub: 'last two years · lifetime best ' + IR.dots(P.best) } : { label: 'Best DOTS', value: IR.dots(P.best), sub: 'lifetime best' },
        isNum(P.d365) ? { label: 'A year', value: IR.signed(P.d365), unit: 'DOTS', sub: 'our rating against a year ago' }
          : (C && isNum(C.v.make) ? { label: 'Attempts made', value: Math.round(C.v.make) + '%', pctl: isNum(pc.make) ? pc.make : null, sub: 'of attempts reported, last two years' } : null),
        isNum(P.need1) ? { label: 'To No. 1', value: IR.kg(P.need1), sub: 'total at the next meet, same bodyweight' + (isNum(P.need_up) ? ' · ' + IR.kg(P.need_up) + ' to go up one' : '') }
          : P.rank === 1 ? { label: 'Rank', value: 'No. 1', text: true, sub: 'of ' + P.of + ' ranked ' + streamLow + ' lifters' }
          : isNum(P.need_up) ? { label: 'To go up one', value: IR.kg(P.need_up), sub: 'total at the next meet, same bodyweight' }
          : (C && isNum(C.v.beat) ? { label: 'Beat our forecast', value: Math.round(C.v.beat) + '%', pctl: isNum(pc.beat) ? pc.beat : null, sub: 'of meets in the last two years' } : null)].filter(Boolean);
      var html = '<nav class="ir-crumb"><a href="#/scout?s=' + P.stream + '">Scouting Room</a> / ' + esc(P.name) + '</nav>';
      html += QK.playerHeader({ name: P.name, face: P.cls || '', kicker: IR.STREAMS[P.stream] + (P.cls ? ' · ' + P.cls + ' kg class' : ''),
        team: { name: P.cc || 'Country not listed', abbr: P.cc ? String(P.cc).slice(0, 3).toUpperCase() : '' }, meta: meta,
        strip: strip, short: short, follow: IR.followItem(P.pid, P.name, P.cc) });
      var prev = P.prev && P.prev.pc ? P.prev : null;
      var cands = tapeCands(P, C, pool);
      if (C && C.v) {
        var groups = FAMILY.map(function (f) {
          var rows = Object.keys(M).filter(function (k) { return M[k].family === f[0] && isNum(C.v[k]) && isNum(C.pc[k]); }).map(function (k) {
            return { label: M[k].label, pctl: C.pc[k], value: IR.vfmt(k, C.v[k], M), tip: M[k].tip + (M[k].dir === 'lower' ? ' (lower is better; the percentile is turned so higher is better)' : ''),
              early: C.n < 3, prev: prev && isNum(prev.pc[k]) ? prev.pc[k] : undefined };
          });
          return { label: f[1], rows: rows };
        }).filter(function (g) { return g.rows.length; });
        html += '<section class="qk-section"><div class="qk-g75 ir-gap"><div>' + QK.pctCard({ title: 'Against the ' + C.cls + ' kg class', kicker: 'Last two years', peer: C.peers + ' active ' + streamLow + ' lifters at ' + C.cls + ' kg', ringLabel: prev ? String(prev.y) : undefined,
          sample: C.n + ' meets since ' + IR.date(C.from), groups: groups }) +
          QK.explain('<b>How sure are we?</b> ' + C.n + ' meet' + (C.n === 1 ? '' : 's') + ' in two years is ' + (C.n < 4 ? 'a small sample: rates like attempts made and beating our forecast are pulled toward the average, and a dashed box marks a percentile still settling.' : 'a fair sample; attempt rates still swing from meet to meet.') +
            (prev ? ' The ▼ marks ' + prev.y + ': rows that sit on it are the steady part of the profile, rows far from it are the ones to watch.' : '')) +
          '</div><div class="ir-stack">' + (cands.length ? '<div id="pl-tape-h"></div><div class="qk-chips ir-pick" id="pl-tape-pick" role="group" aria-label="Compare with"></div><div id="pl-tape">' + QK.skeleton('lines', 6) + '</div><div id="pl-verd"></div>' : '') +
          U.card('Most similar lifters', 'Closest in the ' + C.cls + ' kg class on the percentile profile (relative squat, bench and deadlift, attempts made, progress, DOTS and steadiness); the number is the average gap in percentile points. Names without a link have no page yet.', (P.similar || []).length ? '<ul class="ir-list">' + P.similar.map(function (s) {
            return '<li>' + IR.playerLink(s.pid, s.n, s.pg) + ' <small>' + esc(s.cc || '') + '</small><span class="v" title="Average gap in percentile points">' + IR.dots(s.d) + ' pts apart</span></li>';
          }).join('') + '</ul>' : QK.empty('Not enough meets to compare', '')) +
          '</div></div></section>';
      }
      /* the last meet beside the meet-by-meet line, as the Rink's last game beside its race chart */
      html += '<section class="qk-section"><div class="qk-g2 ir-gap"><div>' + lastMeetHTML(P) + '</div><div>' +
        QK.sectionHead({ kicker: 'Meet by meet', title: 'DOTS against our forecast' }) +
        U.card('', 'DOTS at each meet in ' + streamLow + ' (blue), and what we expected before it from earlier meets only (dashed).', U.chart('pl-prog', 300, 'DOTS by meet')) + '</div></div></section>';
      html += meetLogHTML(P);
      html += '<div class="qk-g2 ir-gap">' + U.card('Lifts, meet by meet', 'Best squat, bench and deadlift at each meet (kg).', U.chart('pl-lifts', 300, 'Lifts by meet')) +
        U.card('The age curve', 'Each dot a meet at the lifter’s age; the dashed line is how ' + streamLow + ' lifters typically change with age (within-lifter, since 2005), anchored on this lifter. Peak age for the stream: ' + esc(String((((lab.ages || {})[P.stream] || {}).peak || {}).total || '–')) + '.', U.chart('pl-age', 300, 'DOTS by age')) + '</div>';
      html += '<div class="qk-g2 ir-gap">' + U.card('The shape of the total', 'Squat, bench and deadlift as shares of the best total, against the class median (whiskers: the middle half). A style, not a grade.', U.chart('pl-ratio', 300, 'Lift shares')) +
        U.card('Attempts', 'Share made by lift and attempt, every meet with attempts reported.', U.chart('pl-att', 300, 'Attempts made')) + '</div>';
      var poolN = pool && pool.rows ? pool.rows.length : 0;
      var poolLo = null;
      if (pool && C) { var ic0 = (pool.cols || []).indexOf('cls'), ir0 = (pool.cols || []).indexOf('rt'); (pool.rows || []).forEach(function (r) { if (r[ic0] === C.cls && isNum(r[ir0]) && (poolLo === null || r[ir0] < poolLo)) poolLo = r[ir0]; }); }
      html += '<div class="qk-g2 ir-gap">' + U.card('Among the class', 'The Scouting Room pool (the top ' + fmt.num(poolN) + ' ' + streamLow + ' lifters on our rating) at ' + esc((C && C.cls) || P.cls) + ' kg on one metric, with ' + esc(sur) + ' marked.' +
          (C && isNum(P.rt) && poolLo !== null && P.rt < poolLo ? ' On our rating ' + esc(sur) + ' (' + IR.dots(P.rt) + ') sits below the pool, which starts at ' + IR.dots(poolLo) + ' here.' : ''), '<div class="qk-seg" id="pl-pk" role="group" aria-label="Metric" style="margin-bottom:10px">' +
          [['rt', 'Rating'], ['total', 'Total'], ['rel', 'Total/BW'], ['make', 'Made'], ['prog', 'Progress']].map(function (k, i) { return '<button type="button" data-value="' + k[0] + '" aria-pressed="' + (i === 0) + '">' + esc(k[1]) + '</button>'; }).join('') + '</div>' + U.chart('pl-peer', 240, 'Class distribution')) +
        U.card('Splits', 'Meets in ' + streamLow + ': average and best DOTS, best total (kg), attempts made and meet value (average DOTS above our pre-meet expectation).', (P.splits || []).length ? U.table(
          [{ label: 'Split', align: 'left' }, { label: 'Meets' }, { label: 'Avg DOTS' }, { label: 'Best' }, { label: 'Total' }, { label: 'Made' }, { label: 'Value' }],
          P.splits.map(function (x) { return [{ v: x.label, html: esc(x.label) }, { v: x.n, html: String(x.n) }, { v: x.dots || 0, html: IR.dots(x.dots) }, { v: x.best || 0, html: IR.dots(x.best) }, { v: x.tot || 0, html: IR.kgn(x.tot) }, { v: x.made || 0, html: IR.pctv(x.made) }, { v: isNum(x.val) ? x.val : -999, html: '<span class="' + IR.cls(x.val) + '">' + IR.signed(x.val) + '</span>' }]; }), { cls: 'dense' }) : QK.empty('No splits', ''), { flush: true }) + '</div>';
      html += U.card('Year by year', 'Bests in each calendar year (' + streamLow + '; kilograms). Value: average DOTS above our pre-meet expectation.', U.table(
        [{ label: 'Year' }, { label: 'Meets' }, { label: 'Class' }, { label: 'BW' }, { label: 'Squat' }, { label: 'Bench' }, { label: 'Dead' }, { label: 'Total' }, { label: 'DOTS' }, { label: 'GL' }, { label: 'Wilks' }, { label: 'Made' }, { label: 'Value' }],
        (P.seasons || []).slice().reverse().map(function (s) {
          return [{ v: s.y, html: String(s.y) }, { v: s.n, html: String(s.n) }, { v: s.cls, html: esc(s.cls || '–') }, { v: s.bw || 0, html: IR.kgn(s.bw) }, { v: s.sq || 0, html: IR.kgn(s.sq) }, { v: s.bp || 0, html: IR.kgn(s.bp) }, { v: s.dl || 0, html: IR.kgn(s.dl) },
            { v: s.tot || 0, html: '<b>' + IR.kgn(s.tot) + '</b>' }, { v: s.dots || 0, html: IR.dots(s.dots) }, { v: s.gl || 0, html: IR.dots(s.gl) }, { v: s.wilks || 0, html: IR.dots(s.wilks) }, { v: s.made || 0, html: IR.pctv(s.made) },
            { v: isNum(s.val) ? s.val : -999, html: '<span class="' + IR.cls(s.val) + '">' + IR.signed(s.val) + '</span>' }];
        }), { cls: 'dense' }), { flush: true });
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
      // the tale of the tape against the closest match (chips switch between up to three)
      var tapeEl = QK.$('#pl-tape', el), pick = QK.$('#pl-tape-pick', el);
      if (!tapeEl || !C || !cands.length) return;
      var drawn = 0;
      var draw = function (cand, fallbackI) {
        IR.load('players/' + encodeURIComponent(cand.pid) + '.json').then(function (O) {
          if (!U.alive(tapeEl)) return;
          if (!O.cur) throw new Error('no profile');
          drawn += 1;
          var oc = O.cur, best = [null, null];
          var tg = TAPE_GROUPS.map(function (g) {
            return { label: g[0], rows: g[1].filter(function (k) { return isNum(C.v[k]) && isNum(oc.v[k]); }).map(function (k) {
              var pa = C.pc[k], pb = oc.pc[k];
              [[pa, pb, 0], [pb, pa, 1]].forEach(function (z) { if (isNum(z[0]) && isNum(z[1]) && z[0] - z[1] > 0 && (!best[z[2]] || z[0] - z[1] > best[z[2]].d)) best[z[2]] = { k: k, d: z[0] - z[1] }; });
              var kgU = (M[k] || {}).unit === 'kg';
              return { label: ((M[k] || {}).label || k) + (kgU ? ' (kg)' : ''), tip: (M[k] || {}).tip, values: [C.v[k], oc.v[k]], pctls: [pa, pb], better: (M[k] || {}).dir === 'lower' ? 'low' : 'high', fmt: function (v) { return kgU ? IR.kgn(v) : IR.vfmt(k, v, M); } };
            }) };
          });
          var why = cand.kind === 'profile' ? 'The ' + (isNum(cand.d) ? 'closest profile with a page in the class: ' + IR.dots(cand.d) + ' percentile points apart on average.' : 'closest profile with a page in the class.')
            : 'None of the five closest profiles has a page yet, so this is the ' + C.cls + ' kg lifter with a page nearest on our rating: ' + IR.dots(oc.v.rt) + ' against ' + IR.dots(C.v.rt) + ' DOTS.';
          QK.$('#pl-tape-h', el).innerHTML = QK.sectionHead({ kicker: 'Tale of the tape', title: sur + ' or ' + QK.surname(O.name) + '?',
            sub: why + ' Bar length = percentile against active ' + C.cls + ' kg ' + streamLow + ' lifters, last two years; the better number in each row is solid.' });
          tapeEl.innerHTML = QK.compareView({ entities: [
            { name: P.name, short: sur, sub: [P.cc, C.cls + ' kg', C.n + ' meets'].filter(Boolean).join(' · '), href: IR.playerHref(P.pid) },
            { name: O.name, short: QK.surname(O.name), sub: [O.cc, oc.cls + ' kg', oc.n + ' meets'].filter(Boolean).join(' · '), href: IR.playerHref(O.pid) }], groups: tg });
          QK.$('#pl-verd', el).innerHTML = QK.verdicts([[P, C, best[0]], [O, oc, best[1]]].map(function (x) {
            var bb = x[2];
            return bb ? { title: 'Better on ' + String((M[bb.k] || {}).short || bb.k).toLowerCase(), who: QK.surname(x[0].name), text: String((M[bb.k] || {}).label || bb.k).toLowerCase() + ' (' + IR.vfmt(bb.k, x[1].v[bb.k], M) + ', ' + QK.ordinal(Math.round(x[1].pc[bb.k])) + ' percentile).' } : null;
          }));
        }).then(null, function () {
          /* that lifter's page is missing or has no profile: try the next one, else say so */
          if (!U.alive(tapeEl)) return;
          if (isNum(fallbackI) && fallbackI + 1 < cands.length) { draw(cands[fallbackI + 1], fallbackI + 1); return; }
          if (!drawn) { QK.$('#pl-tape-h', el).innerHTML = ''; tapeEl.innerHTML = ''; if (pick) pick.innerHTML = ''; }
        });
      };
      if (pick) {
        var all3 = cands.every(function (c) { return inPool(pool, c.pid); }) && inPool(pool, P.pid);
        pick.innerHTML = cands.length > 1 || all3 ? cands.map(function (c, i) { return '<button type="button" class="qk-chip" data-i="' + i + '" aria-pressed="' + (i === 0) + '">' + esc(QK.surname(c.name)) + '</button>'; }).join('') +
          (all3 ? '<a class="qk-chip" href="' + esc('#/scout?s=' + P.stream + '&cmp=' + [P.pid].concat(cands.map(function (c) { return c.pid; })).join(',')) + '">All in the compare tray</a>' : '') : '';
        QK.$$('button', pick).forEach(function (b) { b.addEventListener('click', function () {
          QK.$$('button', pick).forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
          draw(cands[Number(b.getAttribute('data-i'))]);
        }); });
      }
      draw(cands[0], 0);
    });
  });
});
})();
