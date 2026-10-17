/* The Quant Ace — compare two players (#/<T>/compare/<a>/<b>; #/<T>/compare alone shows the pickers).
 *
 * Identity cards, a verdict strip (who wins more of the catalogue metrics on percentile, and the
 * biggest gaps each way, on the tour or one surface's pool), a radar, the full metric table with
 * gap bars and percentile pills, Elo and serve/return paths overlaid, the charting style side by
 * side, and the head-to-head tally with a link to the full page.
 *
 * Data: data/<T>/players.json (catalogue), data/<T>/players/<a>.json and <b>.json (careers),
 * data/<T>/elo.json (current ratings), data/<T>/style.json (tour medians for the style tables).
 * Uses TA.fk from players.js. */
(function (TA) {
'use strict';

const K = () => TA.fk;
const RADAR_P = ['hold', /^hold$/, 'brk', /^br(ea)?k$/, 'serve_rating', 'return_rating', 'win_pct', 'win_v_top20', 'win_top20', /top_?(10|20)/, 'tb_over', 'dec_over', 'dec_pct', /decid/, 'wins_over_exp', 'over_exp', 'elo_d90', 'spw_real', 'rpw_real'];

function gapBar(gap) {
  const k = K();
  if (!k.has(gap)) return '<span class="cmp-gap" title="no percentile on one side"></span>';
  const w = Math.min(50, Math.abs(gap) / 2);
  return '<span class="cmp-gap" title="' + k.signed(gap, 0) + ' percentile points"><span class="' + (gap >= 0 ? 'a' : 'b') + '" style="width:' + w + '%"></span></span>';
}

function verdictAndTables(metrics, A, B, nameA, nameB, scopeNote) {
  const k = K(), has = k.has;
  const comp = metrics.map(m => ({ m: m, a: (A.pct || {})[m.key], b: (B.pct || {})[m.key] })).filter(x => has(x.a) && has(x.b)).map(x => Object.assign(x, { gap: x.a - x.b }));
  let verdict;
  if (!comp.length) verdict = k.muted('No metric has a percentile for both (one of them may be below the match floor, or not play on this surface).');
  else {
    const wa = comp.filter(x => x.gap > 0).length, wb = comp.filter(x => x.gap < 0).length, lv = comp.length - wa - wb, n = comp.length;
    const topA = comp.filter(x => x.gap > 0).sort((x, y) => y.gap - x.gap).slice(0, 3);
    const topB = comp.filter(x => x.gap < 0).sort((x, y) => x.gap - y.gap).slice(0, 3);
    const say = (list, who) => (list.length ? '<strong>' + k.esc(who) + '</strong>: ' + list.map(x => '+' + Math.round(Math.abs(x.gap)) + ' pct on ' + k.esc(x.m.label)).join('; ') : '<strong>' + k.esc(who) + '</strong>: leads on nothing');
    verdict = '<div class="cmp-verdict"><div class="cmp-verdict-side a">' + say(topA, nameA) + '</div>' +
      '<div class="cmp-verdict-mid"><div class="cmp-score"><span class="a">' + wa + '</span><span class="dash">–</span><span class="b">' + wb + '</span></div>' +
      '<div class="cmp-wins"><span class="a" style="width:' + (100 * wa / n) + '%"></span><span class="t" style="width:' + (100 * lv / n) + '%"></span><span class="b" style="width:' + (100 * wb / n) + '%"></span></div>' +
      '<div class="cmp-score-sub">metrics won of ' + n + (lv ? ' · ' + lv + ' level' : '') + (scopeNote ? ' · ' + scopeNote : '') + '</div></div>' +
      '<div class="cmp-verdict-side b">' + say(topB, nameB) + '</div></div>';
  }
  const row = (m, withGroup) => {
    const va = (A.values || {})[m.key], vb = (B.values || {})[m.key], qa = (A.pct || {})[m.key], qb = (B.pct || {})[m.key];
    const gap = has(qa) && has(qb) ? qa - qb : null;
    const better = has(va) && has(vb) && va !== vb ? ((m.lower ? va < vb : va > vb) ? 'a' : 'b') : '';
    const cells = [{ v: m.label, html: k.glossLink(m.key, k.esc(m.label)) + (m.lower ? ' <span class="muted-inline">↓</span>' : '') }];
    if (withGroup) cells.push({ v: m.group, html: '<span class="muted-inline">' + k.esc(m.group || '') + '</span>' });
    cells.push({ v: has(va) ? va : -1e9, html: (better === 'a' ? '<strong>' : '') + k.fmt(m, va) + (better === 'a' ? '</strong>' : ''), align: 'right' });
    cells.push({ v: has(qa) ? qa : -1, html: k.pill(qa), align: 'center' });
    cells.push({ v: gap === null ? -1 : Math.abs(gap), html: gapBar(gap), align: 'center' });
    cells.push({ v: has(qb) ? qb : -1, html: k.pill(qb), align: 'center' });
    cells.push({ v: has(vb) ? vb : -1e9, html: (better === 'b' ? '<strong>' : '') + k.fmt(m, vb) + (better === 'b' ? '</strong>' : ''), align: 'right' });
    return { cells: cells };
  };
  const cols = wg => [{ label: 'Metric' }].concat(wg ? [{ label: 'Group' }] : []).concat([{ label: nameA, align: 'right' }, { label: 'Pct', align: 'center' },
    { label: 'Gap', align: 'center', title: 'Percentile-point gap: yellow when ' + nameA + ' leads, blue when ' + nameB + ' does' }, { label: 'Pct', align: 'center' }, { label: nameB, align: 'right' }]);
  const byGroup = k.groups(metrics).map(g => '<div class="cmp-group-head">' + k.esc(g.name) + '</div>' + k.table(cols(false), g.items.map(m => row(m, false)), { compact: true })).join('');
  const flat = metrics.map(m => ({ m: m, g: has((A.pct || {})[m.key]) && has((B.pct || {})[m.key]) ? Math.abs(A.pct[m.key] - B.pct[m.key]) : -1 })).sort((x, y) => y.g - x.g);
  const byGap = k.table(cols(true), flat.map(x => row(x.m, true)), { compact: true, sticky: true });
  return { verdict: verdict, byGroup: byGroup, byGap: byGap, n: comp.length };
}

function render(el, params, state) {
  const k = K(), T = k.T(params, state);
  const a = String(params.a || (params.rest || [])[0] || ''), b = String(params.b || (params.rest || [])[1] || '');
  el.innerHTML = '<div class="card"><div class="card-header">Compare ' + k.TN(T) + ' players <span class="card-sub">Pick two; the address updates so a comparison can be shared.</span></div>' +
    '<div class="controls af-pickrow"><span class="cmp-pill-a"></span><span id="cmp-pa"></span><span class="muted-inline">v</span><span class="cmp-pill-b"></span><span id="cmp-pb"></span>' +
    '<button type="button" id="cmp-swap" class="af-btn">⇄ swap</button>' + (a && b ? '<a class="af-btn" href="' + k.h2hHref(T, a, b) + '">Head to head →</a>' : '') + '</div></div><div id="cmp-body"></div>';
  return k.ready().then(() => Promise.all([TA.load(T + '/players.json'), k.loadNames(T)])).then(res => {
    if (!k.alive(el)) return null;
    const cat = res[0];
    k.learnCat(T, cat);
    let pa = a, pb = b;
    const go = () => { if (pa && pb && pa !== pb) location.hash = k.compareHref(T, pa, pb); };
    k.picker(document.getElementById('cmp-pa'), { T: T, value: a, placeholder: 'First player…', onPick: id => { pa = id; go(); } });
    k.picker(document.getElementById('cmp-pb'), { T: T, value: b, placeholder: 'Second player…', onPick: id => { pb = id; go(); } });
    document.getElementById('cmp-swap').onclick = () => { if (a && b) location.hash = k.compareHref(T, b, a); };
    const body = document.getElementById('cmp-body');
    if (!a || !b) {
      const P = (cat && cat.players) || {};
      const top = Object.keys(P).filter(id => k.isNum(P[id].rank)).sort((x, y) => P[x].rank - P[y].rank).slice(0, 8);
      const pairs = [];
      for (let i = 0; i + 1 < top.length; i += 2) pairs.push([top[i], top[i + 1]]);
      if (a && top[0]) pairs.unshift([a, top[0] === a ? top[1] : top[0]]);
      body.innerHTML = k.card('Comparisons to try', 'Neighbours in the official ranking.', pairs.length ? '<div class="af-pairs">' + pairs.map(p => '<a class="af-pair" href="' + k.compareHref(T, p[0], p[1]) + '"><strong>' + k.esc(k.surname(k.name(T, p[0]))) + '</strong> v <strong>' + k.esc(k.surname(k.name(T, p[1]))) + '</strong></a>').join('') + '</div>' : k.muted('Pick two players above.'));
      return null;
    }
    body.innerHTML = k.muted('Loading…');
    return Promise.all([TA.load(T + '/players/' + a + '.json'), TA.load(T + '/players/' + b + '.json'), TA.load(T + '/elo.json')]).then(cs => {
      if (k.alive(el)) build(T, [a, b], cat, [k.ok(cs[0]) ? cs[0] : null, k.ok(cs[1]) ? cs[1] : null], k.ok(cs[2]) ? cs[2] : {}, body);
    });
  });
}

function build(T, ids, cat, careers, E, body) {
  const k = K();
  const P = ((cat || {}).players) || {};
  const metrics = (cat || {}).metrics || [];
  const ps = ids.map(id => P[id] || null);
  const names = ids.map((id, i) => (ps[i] && ps[i].name) || (careers[i] && careers[i].name) || k.name(T, id));
  const short = names.map(k.surname);
  const cols = [k.CA, k.CB];
  const eloOf = i => ((E.current || {})[ids[i]]) || (() => { const r = (((careers[i] || {}).elo) || []).slice(-1)[0]; return r ? { all: r[1], hard: r[2], clay: r[3], grass: r[4] } : {}; })();
  const card = i => {
    const p = ps[i] || {}, c = careers[i] || {}, v = p.values || {}, e = eloOf(i);
    const age = k.isNum(p.age) ? Math.floor(p.age) : k.ageOf(c.dob);
    const yr = (c.seasons || []).slice().sort((x, y) => y.year - x.year)[0] || {};
    const titles = (c.seasons || []).reduce((s, x) => s + (x.titles || 0), 0);
    return '<div class="cmp-id ' + (i ? 'b' : 'a') + '"><div class="pg-num af-badge" style="width:52px;height:52px;font-size:0.95rem">' + k.esc(k.isNum(p.rank) ? '#' + p.rank : k.TN(T)) + '</div><div class="cmp-id-body">' +
      '<div class="cmp-id-name">' + k.playerLink(T, ids[i], names[i]) + '</div>' +
      '<div class="cmp-id-sub">' + k.ctry(p.country || c.country) + (c.hand ? ' · ' + (c.hand === 'L' ? 'left-handed' : c.hand === 'R' ? 'right-handed' : k.esc(c.hand)) : '') + (age !== null ? ' · age ' + age : '') + (k.isNum(c.height) ? ' · ' + k.num(c.height, 0) + ' cm' : '') + '</div>' +
      '<div class="cmp-id-facts">' + [['Elo', k.num(e.all, 0)], ['Hard', k.num(e.hard, 0)], ['Clay', k.num(e.clay, 0)], ['Grass', k.num(e.grass, 0)],
        [String(yr.year || 'Year'), k.rec(yr.w, yr.l)], ['Titles', titles + (yr.titles ? ' (' + yr.titles + ' in ' + yr.year + ')' : '')], ['Hold %', k.fmtV(v.hold, 'pct')], ['Break %', k.fmtV(v.brk, 'pct')]]
        .map(f => '<div class="cmp-fact"><span>' + f[0] + '</span><strong>' + f[1] + '</strong></div>').join('') + '</div></div></div>';
  };
  // Head-to-head tally from the career files.
  const hA = (((careers[0] || {}).h2h) || []).find(r => r[0] === ids[1]), hB = (((careers[1] || {}).h2h) || []).find(r => r[0] === ids[0]);
  const tally = hA ? [hA[1], hA[2], hA[3]] : hB ? [hB[2], hB[1], hB[3]] : null;
  const surfOpts = K().SURFACES.filter(s => ps[0] && ps[1] && (ps[0].pct_surface || {})[s] && (ps[1].pct_surface || {})[s]);

  let h = '<div class="cmp-ids">' + card(0) + card(1) + '</div>';
  h += '<div class="card"><div class="card-header">Verdict <span class="card-sub">Who wins each catalogue metric on percentile, and the three biggest gaps each way.</span>' +
    k.toggle('cmp-pool', [['tour', 'Tour']].concat(surfOpts.map(s => [s, k.SURF_LABEL[s]])), 'tour') + '</div><div id="cmp-verdict"></div>' +
    '<div class="pg-note">' + (tally ? 'Head to head: <strong>' + k.esc(short[0]) + ' ' + tally[0] + '–' + tally[1] + ' ' + k.esc(short[1]) + '</strong>' + (tally[2] ? ', last met ' + k.esc(k.fmtDate(tally[2], { weekday: false })) : '') + '. ' : 'No tour-level meeting on file. ') +
    '<a href="' + k.h2hHref(T, ids[0], ids[1]) + '">Matchup odds on every surface →</a></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Ten headline metrics, tour percentiles.</span></div><div id="cmp-radar" style="height:420px"></div></div>' +
    '<div class="card"><div class="card-header">Elo <span class="card-sub">After every match, career files.</span>' + k.toggle('cmp-elo-s', [['1', 'Overall'], ['2', 'Hard'], ['3', 'Clay'], ['4', 'Grass']], '1') + '</div><div id="cmp-elo" style="height:380px"></div></div></div>';
  h += '<div class="card"><div class="card-header">Every metric <span class="card-sub">The whole catalogue: value, percentile and the gap in percentile points. Bold marks the better raw figure.</span><label class="pg-ctl">order <select id="cmp-metric-mode"><option value="group">by group</option><option value="gap">by size of gap</option></select></label></div><div id="cmp-metrics"></div></div>';
  h += '<div class="card"><div class="card-header">Serve and return paths <span class="card-sub">The score-based serve (s, solid) and return (r, dotted) ratings over time, ±1 standard error shaded.</span>' +
    k.toggle('cmp-sr-s', [['all', 'All']].concat(k.SURFACES.map(s => [s, k.SURF_LABEL[s]])), 'all') + '</div><div id="cmp-sr" style="height:380px"></div></div>';
  h += '<div class="card"><div class="card-header">Style <span class="card-sub">Match Charting Project profiles side by side.</span></div><div class="grid-2 af-style-pair"><div><div class="cmp-group-head"><span class="cmp-pill-a"></span>' + k.esc(names[0]) + '</div><div id="cmp-st-a"></div></div>' +
    '<div><div class="cmp-group-head"><span class="cmp-pill-b"></span>' + k.esc(names[1]) + '</div><div id="cmp-st-b"></div></div></div></div>';
  body.innerHTML = h;

  // Verdict and the metric table, on the tour or a surface pool.
  let tables = null;
  const drawVerdict = pool => {
    const pc = i => (pool === 'tour' ? (ps[i] || {}).pct : (((ps[i] || {}).pct_surface || {})[pool] || {}));
    const A = Object.assign({}, ps[0] || {}, { pct: pc(0) || {} }), B = Object.assign({}, ps[1] || {}, { pct: pc(1) || {} });
    tables = verdictAndTables(metrics, A, B, short[0], short[1], pool === 'tour' ? k.TN(T) + ' percentiles' + (cat && cat.year ? ', ' + cat.year : '') : k.SURF_LABEL[pool] + ' pool');
    document.getElementById('cmp-verdict').innerHTML = (!ps[0] || !ps[1]) ? k.muted((!ps[0] ? k.esc(names[0]) : k.esc(names[1])) + ' has no row in the ' + k.esc((cat || {}).year || '') + ' catalogue, so there is nothing to compare metric by metric.') : tables.verdict;
    drawMetrics();
  };
  const sel = document.getElementById('cmp-metric-mode');
  const drawMetrics = () => { if (!tables) return; document.getElementById('cmp-metrics').innerHTML = sel.value === 'gap' ? tables.byGap : tables.byGroup; k.sortable('cmp-metrics'); };
  sel.onchange = drawMetrics;
  drawVerdict('tour');
  k.wireToggle(body, 'cmp-pool', drawVerdict);

  const pctA = (ps[0] || {}).pct || {}, pctB = (ps[1] || {}).pct || {};
  const axes = k.headline(metrics, RADAR_P, 10, true).filter(m => k.isNum(pctA[m.key]) || k.isNum(pctB[m.key])).map(m => ({ key: m.key, label: k.shortLabel(m.label) }));
  k.radar('cmp-radar', axes, [{ name: names[0], pct: pctA, colour: cols[0] }, { name: names[1], pct: pctB, colour: cols[1] }]);

  const drawElo = col => {
    const c = Number(col);
    const tr = [];
    careers.forEach((cr, i) => {
      const rs = (((cr || {}).elo) || []).filter(r => Array.isArray(r) && k.isNum(r[c]));
      if (rs.length) tr.push({ type: 'scatter', mode: 'lines', name: names[i], x: rs.map(r => r[0]), y: rs.map(r => r[c]), line: { color: cols[i], width: 2, shape: 'hv' }, hovertemplate: '%{x}: %{y:.0f}<extra>' + k.esc(short[i]) + '</extra>' });
    });
    if (tr.length) k.plot('cmp-elo', tr, k.layout(Object.assign(k.legendTop(), { margin: { l: 50, r: 10, t: 34, b: 36 }, xaxis: { type: 'date' }, yaxis: { title: ['', 'Overall', 'Hard', 'Clay', 'Grass'][c] + ' Elo' } })));
    else document.getElementById('cmp-elo').innerHTML = k.muted('No Elo history in either career file.');
  };
  drawElo('1');
  k.wireToggle(body, 'cmp-elo-s', drawElo);

  const drawSR = surf => {
    const tr = [];
    careers.forEach((cr, i) => {
      let rs = (((cr || {}).serve_return) || []).filter(r => Array.isArray(r) && r[1] === surf);
      if (!rs.length && surf === 'all') {
        // No "all" rows: the most-played surface stands in.
        const cnt = {}; (((cr || {}).serve_return) || []).forEach(r => { cnt[r[1]] = (cnt[r[1]] || 0) + 1; });
        const best = Object.keys(cnt).sort((x, y) => cnt[y] - cnt[x])[0];
        rs = (((cr || {}).serve_return) || []).filter(r => r[1] === best);
      }
      if (!rs.length) return;
      k.band(rs.map(r => ({ x: r[0], y: r[2], se: r[6], text: r[0] })), cols[i], short[i] + ' serve').forEach(t => tr.push(t));
      k.band(rs.map(r => ({ x: r[0], y: r[3], se: r[7], text: r[0] })), cols[i], short[i] + ' return', { dash: 'dot' }).forEach(t => tr.push(t));
    });
    if (tr.length) k.plot('cmp-sr', tr, k.layout(Object.assign(k.legendTop(), { margin: { l: 50, r: 10, t: 34, b: 36 }, xaxis: { type: 'date' }, yaxis: { title: 'Rating (log-odds of holding)', zeroline: true, zerolinecolor: '#6e7681' } })));
    else document.getElementById('cmp-sr').innerHTML = k.muted('No serve/return path on this surface for either player.');
  };
  drawSR('all');
  k.wireToggle(body, 'cmp-sr-s', drawSR);

  k.styleBlock(document.getElementById('cmp-st-a'), T, (careers[0] || {}).style || null, { stack: true });
  k.styleBlock(document.getElementById('cmp-st-b'), T, (careers[1] || {}).style || null, { stack: true });

}

if (typeof TA.route === 'function') TA.route('compare', render);
})(window.TA || (window.TA = {}));
