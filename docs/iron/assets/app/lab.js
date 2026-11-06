/* The Quant Iron — the Lab (#/lab?tab=): attempt selection, age curves and peak ages, weight-class moves, federation
 * strength, tested against untested, the points formulas across bodyweight, lift ratios by class and bomb-outs.
 * Reads lab.json (oddsmarkets/powerlifting/analytics.py). */
(function () {
'use strict';
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt, U = IR.ui;
var TABS = [['attempts', 'Attempts'], ['ages', 'Age curves'], ['moves', 'Class moves'], ['feds', 'Federations'], ['formulas', 'Points formulas'], ['ratios', 'Lift ratios'], ['bombs', 'Bomb-outs'], ['sticks', 'What sticks']];
var LIFT = { squat: 'Squat', bench: 'Bench', dead: 'Deadlift' };

function attempts(el, d) {
  var A = d.attempts || {};
  if (!A.lifts) { el.innerHTML = QK.empty('No attempt data yet', 'Attempts arrive with the next archive update.'); return; }
  var bs = A.by_stream || {};
  var html = U.note(fmt.num(A.n_lifters) + ' full-power entries since ' + esc(A.since) + ' with at least six attempts reported (not every federation reports attempts; negative weights in the archive are misses).');
  html += QK.stats(IR.STREAM_KEYS.filter(function (k) { return bs[k]; }).map(function (k) {
    return { label: IR.STREAMS[k], value: IR.pctv(bs[k].made, 1), sub: 'attempts made · ' + IR.pctv(bs[k].nine, 1) + ' went nine for nine' + (isNum(bs[k].tested) && isNum(bs[k].untested) ? ' · tested ' + IR.pctv(bs[k].tested, 1) + ', untested ' + IR.pctv(bs[k].untested, 1) : '') };
  }));
  html += '<div class="qk-g2 ir-gap">' + U.card('Make rate by attempt', 'Openers go; third attempts are where meets are won and lost.', U.chart('lb-att', 300, 'Make rate by attempt')) +
    U.card('The jump and the make rate', 'The next attempt after a made one, by the size of the jump (as a share of the made weight).', '<div class="qk-seg" id="lb-jl" role="group" aria-label="Lift" style="margin-bottom:10px">' +
      Object.keys(LIFT).map(function (k, i) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + LIFT[k] + '</button>'; }).join('') + '</div>' + U.chart('lb-jump', 280, 'Make rate by jump size')) + '</div>';
  html += U.card('The third attempt', 'After a made second: how many kilos to add. Expected gain is the jump times the chance of making it, the kilos a third attempt adds to the total on average. After a missed second, repeating the weight against going up.', '<div class="qk-seg" id="lb-tl" role="group" aria-label="Lift" style="margin-bottom:10px">' +
    Object.keys(LIFT).map(function (k, i) { return '<button type="button" data-value="' + k + '" aria-pressed="' + (i === 0) + '">' + LIFT[k] + '</button>'; }).join('') + '</div><div class="qk-g2"><div>' + U.chart('lb-third', 300, 'Third attempt: jump, make rate and expected gain') + '</div><div id="lb-third-t"></div></div>');
  el.innerHTML = html;
  var cats = [], s1 = [], s2 = [], s3 = [];
  Object.keys(LIFT).forEach(function (k) { var a = (A.lifts[k] || {}).attempts || []; cats.push(LIFT[k]); s1.push((a[0] || {}).made); s2.push((a[1] || {}).made); s3.push((a[2] || {}).made); });
  QKC.bar(QK.$('#lb-att', el), { cats: cats, series: [{ name: 'Opener', data: s1, color: IR.col(1) }, { name: 'Second', data: s2, color: IR.col(3) }, { name: 'Third', data: s3, color: IR.col(5) }],
    valName: 'Attempts made (%)', catName: 'Lift', labels: true, fmt: function (v) { return Math.round(v) + '%'; } });
  function jump(k) {
    var js = (A.jumps || {})[k] || [], bins = [];
    js.forEach(function (x) { if (bins.indexOf(x.bin) < 0) bins.push(x.bin); });
    var get = function (att) { return bins.map(function (b) { var r = js.filter(function (x) { return x.att === att && x.bin === b; })[0]; return r ? r.made : null; }); };
    QKC.bar(QK.$('#lb-jump', el), { cats: bins, series: [{ name: 'Second attempt', data: get(2), color: IR.col(3) }, { name: 'Third attempt', data: get(3), color: IR.col(5) }],
      valName: 'Made (%)', catName: 'Jump from the last made attempt', fmt: function (v) { return Math.round(v) + '%'; } });
  }
  function third(k) {
    var T = (A.third || {})[k] || {}, rows = T.after_make || [];
    QKC.bar(QK.$('#lb-third', el), { cats: rows.map(function (r) { return r.kg + ' kg'; }), series: [{ name: 'Made (%)', data: rows.map(function (r) { return r.made; }), color: IR.col(5) }],
      valName: 'Third attempts made (%)', catName: 'Kilos added after a made second', labels: true, fmt: function (v) { return Math.round(v) + '%'; } });
    var best = rows.slice().sort(function (a, b) { return (b.exp || 0) - (a.exp || 0); })[0];
    QK.$('#lb-third-t', el).innerHTML = U.table([{ label: 'Jump', align: 'left' }, { label: 'Thirds' }, { label: 'Made' }, { label: 'Kilos added on average' }],
      rows.map(function (r) { return [{ v: r.kg, html: esc(r.kg) + ' kg' + (best && r.kg === best.kg ? ' <span class="ir-pr">best</span>' : '') }, { v: r.n, html: fmt.num(r.n) }, { v: r.made, html: IR.pctv(r.made, 1) }, { v: r.exp, html: (r.exp || 0).toFixed(2) + ' kg' }]; }), { cls: 'dense' }) +
      U.note('After a missed second at the same weight, lifters made the repeat ' + IR.pctv((T.after_miss_same || {}).made, 1) + ' of the time (' + fmt.num((T.after_miss_same || {}).n || 0) + '); going up after a miss, ' + IR.pctv((T.after_miss_up || {}).made, 1) + ' (' + fmt.num((T.after_miss_up || {}).n || 0) + '). Descriptive: stronger lifters take bigger jumps, so this is what happened, not a causal rule.');
  }
  jump('squat'); third('squat');
  QK.seg(QK.$('#lb-jl', el), jump);
  QK.seg(QK.$('#lb-tl', el), third);
}

function ages(el, d) {
  var G = d.ages || {};
  var keys = IR.STREAM_KEYS.filter(function (k) { return G[k]; });
  if (!keys.length) { el.innerHTML = QK.empty('No age curves', ''); return; }
  el.innerHTML = U.note('How lifters change with age, from pairs of the same lifter’s meets 60 to 730 days apart since 2005 (a trimmed mean per year of age), summed from age 16. Cross-sectional averages flatter older ages because the lifters who stay in the sport are the good ones; following the same lifters takes that out. Lifts are bodyweight-adjusted (each lift × the DOTS factor).') +
    QK.stats(keys.map(function (k) { var p = G[k].peak || {}; return { label: IR.STREAMS[k], value: 'Peak ' + p.total, sub: 'squat ' + p.squat + ' · bench ' + p.bench + ' · deadlift ' + p.dead }; })) +
    '<div class="ir-controls">' + U.seg('lb-as', keys.map(function (k) { return [k, IR.STREAMS[k]]; }), keys[0], 'Stream') + '</div>' +
    '<div class="qk-g2 ir-gap">' + U.card('The within-lifter curve', 'DOTS gained since age 16 for a typical lifter, total and each lift.', U.chart('lb-age', 340, 'Age curve')) +
    U.card('The cross-section', 'Average DOTS of everyone at each age (biased by who stays).', U.chart('lb-cross', 340, 'Average DOTS by age')) + '</div>';
  function draw(k) {
    var g = G[k];
    QKC.line(QK.$('#lb-age', el), { x: g.ages, xType: 'value', series: [{ name: 'Total (DOTS)', data: g.total, color: IR.col(1) }, { name: 'Squat', data: g.squat, color: IR.col(3), dash: true }, { name: 'Bench', data: g.bench, color: IR.col(5), dash: true }, { name: 'Deadlift', data: g.dead, color: IR.col(7), dash: true }],
      yName: 'DOTS gained since 16', xName: 'Age (years)', endLabels: false, ref: { x: g.peak.total, label: 'Peak ' + g.peak.total }, yFmt: function (v) { return fmt.num(v, 0); } });
    QKC.line(QK.$('#lb-cross', el), { x: g.ages, xType: 'value', series: [{ name: 'Average DOTS', data: g.cross, color: IR.col(1) }], yName: 'Average DOTS', xName: 'Age (years)', endLabels: false, yFmt: function (v) { return fmt.num(v, 0); } });
  }
  draw(keys[0]);
  QK.seg(QK.$('#lb-as', el), draw);
}

function moves(el, d) {
  var M = d.moves || {};
  var keys = Object.keys(M).filter(function (k) { return (M[k] || []).length; });
  if (!keys.length) { el.innerHTML = QK.empty('No class moves', ''); return; }
  el.innerHTML = U.note('Consecutive scored meets 60 to 400 days apart since 2012: lifters who moved down an IPF class, stayed, or moved up, and what happened to the total in kilos and to DOTS. A move up usually adds kilos and costs DOTS; the question is whether the kilos outrun the formula.') +
    keys.map(function (k) {
      return U.card(IR.STREAMS[k], '', U.table([{ label: 'Move', align: 'left' }, { label: 'Pairs' }, { label: 'Bodyweight' }, { label: 'Total' }, { label: 'DOTS' }, { label: 'DOTS improved' }],
        M[k].map(function (r) { return [{ v: r.move, html: esc(r.move) }, { v: r.n, html: fmt.num(r.n) }, { v: r.bw, html: IR.signed(r.bw) + ' kg' }, { v: r.kg, html: IR.signed(r.kg) + ' kg' }, { v: r.dots, html: '<span class="' + IR.cls(r.dots) + '">' + IR.signed(r.dots) + '</span>' }, { v: r.better, html: IR.pctv(r.better) }]; }), { cls: 'dense' }), { flush: true });
    }).join('');
}

function feds(el, d) {
  var F = d.feds || {}, T = d.tested || {};
  var keys = Object.keys(F).filter(function (k) { return (F[k] || []).length; });
  if (!keys.length) { el.innerHTML = QK.empty('No federation table', ''); return; }
  el.innerHTML = U.note('Raw full power since 2015, federations with 400+ starts. Two readings of strength: the field (median DOTS and the mean of the top 50 lifters’ bests) and the same-lifter effect: lifters who compete in more than one federation, with each lifter’s own level taken out, show how many DOTS more (or fewer) the same lifter totals there than on average (judging, testing, equipment rules and the day). The effect rests on the shared lifters; few shared lifters means a loose number.') +
    '<div class="ir-controls">' + U.seg('lb-fs', keys.map(function (k) { return [k, IR.STREAMS[k]]; }), keys[0], 'Stream') + '</div><div id="lb-tested"></div>' +
    '<div class="qk-g2 ir-gap">' + U.card('Same lifter, different federation', 'DOTS against the all-federation average, the 20 federations with the most shared lifters.', U.chart('lb-fe', 520, 'Federation effect')) + '<div id="lb-ft"></div></div>';
  function draw(k) {
    var rows = F[k] || [];
    var tt = T[k] || {};
    QK.$('#lb-tested', el).innerHTML = tt.tested && tt.untested ? QK.stats([
      { label: 'Tested lifters', value: fmt.num(tt.tested.lifters), sub: 'median best ' + IR.dots(tt.tested.median) + ' · top 100 ' + IR.dots(tt.tested.top100) + ' DOTS' },
      { label: 'Untested lifters', value: fmt.num(tt.untested.lifters), sub: 'median best ' + IR.dots(tt.untested.median) + ' · top 100 ' + IR.dots(tt.untested.top100) + ' DOTS' },
      { label: 'The gap at the top', value: IR.signed(tt.untested.top100 - tt.tested.top100) + ' DOTS', sub: 'untested top 100 against tested top 100', signal: true }]) : '';
    var fe = rows.filter(function (r) { return isNum(r.effect) && r.shared >= 30; }).sort(function (a, b) { return b.shared - a.shared; }).slice(0, 20).sort(function (a, b) { return b.effect - a.effect; });
    QKC.bar(QK.$('#lb-fe', el), { cats: fe.map(function (r) { return r.fed; }), series: [{ name: 'Same-lifter effect', data: fe.map(function (r) { return r.effect; }), color: IR.col(1) }], horizontal: true, diverging: true,
      valName: 'DOTS against the average federation', catName: 'Federation', labels: true, fmt: function (v) { return IR.signed(v); } });
    QK.$('#lb-ft', el).innerHTML = U.card('The field', 'Sorted by the top 50.', U.table([{ label: 'Federation', align: 'left' }, { label: 'Parent', align: 'left' }, { label: 'Lifters' }, { label: 'Median' }, { label: 'Top 50' }, { label: 'Tested' }, { label: 'Effect' }, { label: 'Shared' }],
      rows.map(function (r) { return [{ v: r.fed, html: esc(r.fed) }, { v: r.parent, html: esc(r.parent || '–') }, { v: r.lifters, html: fmt.num(r.lifters) }, { v: r.median, html: IR.dots(r.median) }, { v: r.top50, html: '<b>' + IR.dots(r.top50) + '</b>' },
        { v: r.tested, html: IR.pctv(r.tested) }, { v: isNum(r.effect) ? r.effect : -999, html: '<span class="' + IR.cls(r.effect) + '">' + IR.signed(r.effect) + '</span>' }, { v: r.shared, html: fmt.num(r.shared) }]; }), { cls: 'dense', maxHeight: 520 }), { flush: true });
    U.wire(el);
  }
  draw(keys[0]);
  QK.seg(QK.$('#lb-fs', el), draw);
}

function formulas(el, d) {
  var F = d.formulas || {};
  if (!(F.men || []).length) { el.innerHTML = QK.empty('No formula table', ''); return; }
  el.innerHTML = U.note('Is a points formula fair across bodyweight? For each IPF class, the mean points of its top 20 raw lifters since 2018 (each lifter’s best) under DOTS, IPF GL and Wilks. A fair formula draws flat lines: the best of every class score the same. Where a line rises, that formula favours the heavier classes.') +
    '<div class="qk-g2 ir-gap">' + U.card('Men, raw', '', U.chart('lb-fm', 320, 'Formula fairness, men')) + U.card('Women, raw', '', U.chart('lb-fw', 320, 'Formula fairness, women')) + '</div>';
  [['men', '#lb-fm'], ['women', '#lb-fw']].forEach(function (x) {
    var r = F[x[0]] || [];
    QKC.line(QK.$(x[1], el), { x: r.map(function (q) { return q.cls; }), series: [{ name: 'DOTS', data: r.map(function (q) { return q.dots; }), color: IR.col(1) }, { name: 'IPF GL', data: r.map(function (q) { return q.gl; }), color: IR.col(3) }, { name: 'Wilks', data: r.map(function (q) { return q.wilks; }), color: IR.col(5) }],
      yName: 'Mean points of the class top 20', xName: 'IPF class (kg)', endLabels: true, yFmt: function (v) { return fmt.num(v, 0); } });
  });
}

function ratios(el, d) {
  var R = d.ratios || {};
  var keys = Object.keys(R).filter(function (k) { return (R[k] || []).length; });
  if (!keys.length) { el.innerHTML = QK.empty('No lift ratios', ''); return; }
  el.innerHTML = U.note('Squat, bench and deadlift as shares of the total, raw full power since 2018, by IPF class: the median and the middle half. The lifter pages and the Scouting Room place every lifter on these (a style, not a grade).') +
    keys.map(function (k) {
      return U.card(IR.STREAMS[k], '', U.chart('lb-r-' + k, 300, 'Lift shares by class') + U.table([{ label: 'Class' }, { label: 'Totals' }, { label: 'Squat %' }, { label: 'Bench %' }, { label: 'Deadlift %' }, { label: 'Squat/BW' }, { label: 'Bench/BW' }, { label: 'Dead/BW' }],
        R[k].map(function (r) { return [{ v: r.cls, html: esc(r.cls) + ' kg' }, { v: r.n, html: fmt.num(r.n) }, { v: r.squat[1], html: r.squat[1] + ' <small class="qk-muted">' + r.squat[0] + '–' + r.squat[2] + '</small>' }, { v: r.bench[1], html: r.bench[1] + ' <small class="qk-muted">' + r.bench[0] + '–' + r.bench[2] + '</small>' },
          { v: r.dead[1], html: r.dead[1] + ' <small class="qk-muted">' + r.dead[0] + '–' + r.dead[2] + '</small>' }, { v: r.squat_bw, html: (r.squat_bw || 0).toFixed(2) + '×' }, { v: r.bench_bw, html: (r.bench_bw || 0).toFixed(2) + '×' }, { v: r.dead_bw, html: (r.dead_bw || 0).toFixed(2) + '×' }]; }), { cls: 'dense' }));
    }).join('');
  keys.forEach(function (k) {
    var r = R[k];
    QKC.bar(QK.$('#lb-r-' + k, el), { cats: r.map(function (q) { return q.cls; }), series: [{ name: 'Squat', data: r.map(function (q) { return q.squat[1]; }), color: IR.col(1) }, { name: 'Bench', data: r.map(function (q) { return q.bench[1]; }), color: IR.col(3) }, { name: 'Deadlift', data: r.map(function (q) { return q.dead[1]; }), color: IR.col(5) }],
      stack: true, valName: 'Share of the total (%)', catName: 'IPF class (kg)', fmt: function (v) { return v.toFixed(1) + '%'; } });
  });
}

function bombs(el, d) {
  var B = d.bombouts || {};
  if (!isNum(B.rate)) { el.innerHTML = QK.empty('No bomb-out data', ''); return; }
  el.innerHTML = U.note('A bomb-out is a full-power meet without a total: three misses on one lift, or a disqualification (OpenPowerlifting’s DQ). Since 2012, ' + fmt.num(B.n) + ' entries.') +
    QK.stats([{ label: 'All full-power entries', value: IR.pctv(B.rate, 1), signal: true, sub: 'finished without a total' }].concat(IR.STREAM_KEYS.filter(function (k) { return isNum((B.by_stream || {})[k]); }).map(function (k) { return { label: IR.STREAMS[k], value: IR.pctv(B.by_stream[k], 1) }; }))) +
    ((B.lift_lost || []).length ? U.card('Which lift ended the day', 'Bomb-outs with attempts reported: the lift with three misses.', U.chart('lb-bl', 260, 'Bomb-outs by lift')) : '');
  if ((B.lift_lost || []).length) QKC.bar(QK.$('#lb-bl', el), { cats: B.lift_lost.map(function (x) { return x.lift; }), series: [{ name: 'Share of bomb-outs', data: B.lift_lost.map(function (x) { return x.share; }), color: IR.col(5) }], valName: 'Share of bomb-outs (%)', catName: 'Lift with three misses', labels: true, fmt: function (v) { return v.toFixed(0) + '%'; } });
}

function sticks(el, d) {
  var R = d.reliability || {};
  var ids = Object.keys(R);
  if (!ids.length) { el.innerHTML = QK.empty('No reliability table', ''); return; }
  return IR.load('scout/men_raw.json').then(function (sc) {
    var M = {};
    (sc.metrics || []).forEach(function (m) { M[m.id] = m; });
    ids.sort(function (a, b) { return R[b].yoy_r - R[a].yoy_r; });
    el.innerHTML = U.note('Which numbers describe the lifter and which are noise? For the same lifters in consecutive calendar years (2022 to 2025, two or more meets in each year), the rank correlation of each metric with itself a year later (does it stick?) and with next year’s best DOTS (does it predict?). Strength sticks almost perfectly; attempts made, beating our forecast and progress barely repeat, so read them as this year’s story, not a trait.') +
      '<div class="qk-g2 ir-gap">' + U.card('Does it stick?', 'Year-to-year rank correlation.', U.chart('lb-yoy', 640, 'Year to year correlation by metric')) +
      U.card('Does it predict?', 'Rank correlation with next year’s best DOTS.', U.chart('lb-pred', 640, 'Correlation with next year best DOTS')) + '</div>' +
      U.card('Every metric', '', U.table([{ label: 'Metric', align: 'left' }, { label: 'Lifter-years' }, { label: 'Year to year' }, { label: 'With next year’s DOTS' }],
        ids.map(function (k) { return [{ v: (M[k] || {}).label || k, html: esc((M[k] || {}).label || k) }, { v: R[k].n, html: fmt.num(R[k].n) }, { v: R[k].yoy_r, html: R[k].yoy_r.toFixed(2) }, { v: R[k].pred_r, html: R[k].pred_r.toFixed(2) }]; }), { cls: 'dense' }), { flush: true });
    var lab = function (k) { return (M[k] || {}).short || k; };
    QKC.bar(QK.$('#lb-yoy', el), { cats: ids.map(lab), series: [{ name: 'Year to year', data: ids.map(function (k) { return R[k].yoy_r; }), color: IR.col(1) }], horizontal: true, valName: 'Rank correlation, year to year', catName: 'Metric', labels: true, fmt: function (v) { return v.toFixed(2); } });
    var ps = ids.slice().sort(function (a, b) { return R[b].pred_r - R[a].pred_r; });
    QKC.bar(QK.$('#lb-pred', el), { cats: ps.map(lab), series: [{ name: 'With next year’s best DOTS', data: ps.map(function (k) { return R[k].pred_r; }), color: IR.col(3) }], horizontal: true, diverging: true, valName: 'Rank correlation with next year’s best DOTS', catName: 'Metric', labels: true, fmt: function (v) { return v.toFixed(2); } });
    U.wire(el);
  });
}

IR.page('lab', function (el, params) {
  var tab = TABS.map(function (t) { return t[0]; }).indexOf((params.query || {}).tab) >= 0 ? params.query.tab : 'attempts';
  return IR.load('lab.json').then(function (d) {
    el.innerHTML = U.head('The Lab', 'What sixty years of meets say about lifting: attempt selection, age, weight classes, federations, the points formulas and the shape of a total. Descriptive, from the OpenPowerlifting archive; nothing here is advice.', 'The Quant Iron') +
      U.tabs(TABS.map(function (t) { return { key: t[0], label: t[1], href: '#/lab?tab=' + t[0] }; }), tab) + '<div id="lb-body"></div>';
    var body = QK.$('#lb-body', el);
    return ({ attempts: attempts, ages: ages, moves: moves, feds: feds, formulas: formulas, ratios: ratios, bombs: bombs, sticks: sticks })[tab](body, d);
  });
});
})();
