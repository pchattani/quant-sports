/* The Quant Ace — compare (#/<T>/compare/<a>/<b>[/<c>]), Design System 2.0 (the Rink compare page is the reference).
 *
 * Two or three players side by side (QK.compareView) on the headline metric set of METRICS_SPEC.md (TA.v2), ranked
 * against the tour or, with a surface picked, the players with enough matches on it; where each one sits in the peer
 * distribution; Elo and serve/return paths; the whole catalogue as the classic view (first two players); the
 * charting style side by side; the head-to-head tally. With nobody picked the top two by ranking open; with one, the
 * most similar player (the spec's weighted distance). *
 * Data: data/<T>/players.json (catalogue), data/<T>/players/<a>.json and <b>.json (careers),
 * data/<T>/elo.json (current ratings), data/<T>/style.json (tour medians for the style tables).
 * Uses TA.fk from players.js. */
(function (TA) {
'use strict';

const K = () => TA.fk;
const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);

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

const ECOL = ['var(--wp-a)', 'var(--wp-b)', 'var(--c-3)'];

function render(el, params, state) {
  const k = K(), T = k.T(params, state), V = TA.v2;
  let ids = [params.a, params.b].concat(params.rest || []).filter(Boolean).map(String).slice(0, 3);
  el.innerHTML = QK.skeleton('lines', 6);
  return k.ready().then(() => Promise.all([TA.load(T + '/players.json'), k.loadNames(T)])).then(res => {
    if (!k.alive(el)) return null;
    const cat = res[0];
    if (!k.ok(cat) || !cat.players) { el.innerHTML = V.card('Compare', '', k.notBuilt('The ' + k.TN(T) + ' player catalogue', cat)); return null; }
    k.learnCat(T, cat);
    const P = cat.players;
    // nobody picked: the top two by ranking; one picked: the most similar player
    if (!ids.length) ids = Object.keys(P).filter(id => P[id].qualified && isNum(P[id].rank)).sort((x, y) => P[x].rank - P[y].rank).slice(0, 2);
    else if (ids.length === 1) { const s1 = V.similar(T, ids[0], cat, 1)[0]; if (s1) ids.push(s1.id); }
    el.innerHTML = '<div class="ta-cmp-pick">' + [0, 1, 2].map(i => '<div class="ta-cmp-slot" style="--ec:' + ECOL[i] + '"><span class="qk-kicker">' + (i === 2 ? 'Third player (optional)' : 'Player ' + (i + 1)) + '</span><span id="cmp-p' + i + '"></span></div>').join('') + '</div><div id="cmp-body"></div>';
    const cur = ids.slice();
    const go = () => { const list = cur.filter(Boolean); if (list.length >= 2) location.hash = k.href(T, 'compare/' + list.map(encodeURIComponent).join('/')); };
    [0, 1, 2].forEach(i => k.picker(document.getElementById('cmp-p' + i), { T: T, value: ids[i], placeholder: i === 2 ? 'Add a third…' : 'Type a player…', onPick: id => { cur[i] = id; go(); } }));
    const body = document.getElementById('cmp-body');
    if (ids.length < 2) { body.innerHTML = V.card('Pick players', '', QK.empty('Pick at least two players', 'Type a name in each box.')); return null; }
    body.innerHTML = QK.skeleton('lines', 6);
    return Promise.all(ids.map(id => TA.load(T + '/players/' + id + '.json')).concat([TA.load(T + '/elo.json')])).then(cs => {
      if (k.alive(el)) build(T, ids, cat, ids.map((_, i) => (k.ok(cs[i]) ? cs[i] : null)), body);
    });
  });
}

const CMP_GROUPS = [['Strength', ['elo', 'elo_hard', 'elo_clay', 'elo_grass']], ['Results', ['games_won_pct', 'win_pct', 'win_v_top50']],
  ['Serve and return, inferred from scores', ['hold', 'brk', 'hold_plus_break']], ['Serve statistics (WTA)', ['dominance', 'ace_pct']]];

function build(T, ids, cat, careers, body) {
  const k = K(), V = TA.v2;
  const P = ((cat || {}).players) || {};
  const metrics = (cat || {}).metrics || [];
  const ps = ids.map(id => P[id] || null);
  const names = ids.map((id, i) => (ps[i] && ps[i].name) || (careers[i] && careers[i].name) || k.name(T, id));
  const short = names.map(k.surname);
  const cols = ['wpA', 'wpB', 'c3'];
  const surfOpts = V.SURF.filter(s => ps.every(p => V.inPool(p, s, cat)));
  const hA = (((careers[0] || {}).h2h) || []).find(r => r[0] === ids[1]), hB = (((careers[1] || {}).h2h) || []).find(r => r[0] === ids[0]);
  const tally = hA ? [hA[1], hA[2], hA[3]] : hB ? [hB[2], hB[1], hB[3]] : null;

  let h = V.card('Side by side', '<span id="cmp-sub"></span>', V.seg('cmp-pool', [['', 'Tour']].concat(surfOpts.map(s => [s, k.SURF_LABEL[s]])), '', 'Peer group') + '<div id="cmp-view" style="margin-top:12px"></div><p class="ta-cap" id="cmp-cap"></p>',
    { foot: '<span>' + (tally ? 'Head to head: <b>' + k.esc(short[0]) + ' ' + tally[0] + '–' + tally[1] + ' ' + k.esc(short[1]) + '</b>' + (tally[2] ? ', last met ' + k.esc(k.fmtDate(tally[2], { weekday: false })) : '') : 'No tour-level meeting on file') + '</span><a href="' + k.h2hHref(T, ids[0], ids[1]) + '">Head to head, our chance on every surface →</a>' });
  h += '<section class="qk-section">' + V.card('Where they sit', 'Every qualified player in the peer group, with each one marked', '<div class="qk-seg" id="cmp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px;flex-wrap:wrap"></div>' + V.chart('cmp-dist', 260, 'Peer distribution with the players marked')) + '</section>';
  h += '<div class="card"><div class="card-header">Elo <span class="card-sub">After every match, career files.</span>' + k.toggle('cmp-elo-s', [['1', 'Overall'], ['2', 'Hard'], ['3', 'Clay'], ['4', 'Grass']], '1') + '</div><div id="cmp-elo" style="height:380px"></div></div>';
  h += '<div class="card"><div class="card-header">Serve and return paths <span class="card-sub">The score-based serve (solid) and return (dotted) ratings over time, ±1 standard error shaded.</span>' +
    k.toggle('cmp-sr-s', [['all', 'All']].concat(k.SURFACES.map(s => [s, k.SURF_LABEL[s]])), 'all') + '</div><div id="cmp-sr" style="height:380px"></div></div>';
  h += '<div class="card"><div class="card-header">Every metric (classic) <span class="card-sub">' + k.esc(short[0]) + ' and ' + k.esc(short[1]) + ' on the whole catalogue: who leads each metric on percentile, then value, percentile and the gap. Tiebreak, deciding-set and over-expected rows are mostly luck.</span>' +
    '<label class="pg-ctl">order <select id="cmp-metric-mode"><option value="group">by group</option><option value="gap">by size of gap</option></select></label></div><div id="cmp-verdict"></div><div id="cmp-metrics"></div></div>';
  h += '<div class="card"><div class="card-header">Style <span class="card-sub">Match Charting Project profiles side by side.</span></div><div class="grid-2 af-style-pair"><div><div class="cmp-group-head">' + k.esc(names[0]) + '</div><div id="cmp-st-a"></div></div>' +
    '<div><div class="cmp-group-head">' + k.esc(names[1]) + '</div><div id="cmp-st-b"></div></div></div></div>';
  body.innerHTML = h;

  let distKey = null;
  const drawView = sf => {
    const set = V.set(T, sf).concat(['hold_plus_break']);
    const groups = CMP_GROUPS.map(g => ({ label: g[0], rows: set.filter(x => g[1].indexOf(x) >= 0).map(x => ({ label: V.label(x, sf), tip: (V.META[x] || [])[1], better: 'high',
      values: ps.map(p => V.value(p, x, sf)), pctls: ps.map(p => (V.inPool(p, sf, cat) ? V.pctl(p, x, sf, cat) : null)), fmt: v => V.fmt(x, v),
      dfmt: (V.META[x] || [])[2] === 'pct' ? (d => (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d * 100).toFixed(1) + ' pts') : null })) }));
    const ents = ids.map((id, i) => {
      const n = sf ? (((ps[i] || {}).values_surface || {})[sf] || {}).matches : (ps[i] || {}).matches;
      return { name: names[i], href: k.playerHref(T, id), abbr: short[i], sub: [ps[i] && ps[i].country, ps[i] && isNum(ps[i].rank) ? 'No. ' + ps[i].rank : '', isNum(n) ? n + (sf ? ' ' + sf : '') + ' matches' : ''].filter(Boolean).join(' · ') };
    });
    document.getElementById('cmp-view').innerHTML = QK.compareView({ entities: ents, groups: groups });
    document.getElementById('cmp-sub').textContent = 'Value · percentile against ' + V.peer(T, sf, cat) + ' (100 = best)' + (ids.length === 2 ? ' · difference, green when ' + short[0] + ' is better' : ' · the best of three in bold');
    const outs = ps.map((p, i) => (V.inPool(p, sf, cat) ? '' : names[i])).filter(Boolean);
    document.getElementById('cmp-cap').textContent = (outs.length ? outs.join(', ') + (outs.length > 1 ? ' are' : ' is') + ' short of the floor, so ' + (outs.length > 1 ? 'they have' : 'there is') + ' no percentile. ' : '') + 'Hold and break are inferred from set scores, not measured point by point.';
    const segEl = document.getElementById('cmp-dist-m');
    const dset = V.set(T, sf);
    if (dset.indexOf(distKey) < 0) distKey = dset[0];
    segEl.innerHTML = dset.map(x => '<button type="button" aria-pressed="' + (x === distKey) + '" data-value="' + x + '">' + k.esc(V.label(x)) + '</button>').join('');
    const dd = x => {
      distKey = x;
      const xs = Object.keys(P).filter(id => V.inPool(P[id], sf, cat)).map(id => V.value(P[id], x, sf)).filter(isNum).sort((a, b) => a - b);
      if (xs.length < 5) { document.getElementById('cmp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
      const f = (V.META[x] || [])[2] === 'pct' ? (v => (v * 100).toFixed(1) + '%') : (v => V.fmt(x, v));
      QKC.distribution('#cmp-dist', { values: xs, binCount: 20, fmt: f, colorBy: 'flat', xName: V.label(x, sf) + ' · ' + xs.length + ' qualified peers', yName: 'Players',
        marks: ps.map((p, i) => ({ x: V.value(p, x, sf), label: short[i], color: cols[i] })).filter(m => isNum(m.x)), label: 'Distribution of ' + V.label(x) });
    };
    dd(distKey);
    QK.seg(segEl, dd);
  };
  drawView('');
  QK.seg(document.getElementById('cmp-pool'), drawView);

  // every metric (classic): the first two players on the tour percentiles
  const sel = document.getElementById('cmp-metric-mode');
  const tables = verdictAndTables(metrics, Object.assign({}, ps[0] || {}, { pct: (ps[0] || {}).pct || {} }), Object.assign({}, ps[1] || {}, { pct: (ps[1] || {}).pct || {} }), short[0], short[1], k.TN(T) + ' percentiles' + (cat && cat.year ? ', ' + cat.year : ''));
  const drawMetrics = () => { document.getElementById('cmp-metrics').innerHTML = sel.value === 'gap' ? tables.byGap : tables.byGroup; k.sortable('cmp-metrics'); };
  document.getElementById('cmp-verdict').innerHTML = (!ps[0] || !ps[1]) ? k.muted((!ps[0] ? k.esc(names[0]) : k.esc(names[1])) + ' has no row in the ' + k.esc((cat || {}).year || '') + ' catalogue, so there is nothing to compare metric by metric.') : tables.verdict;
  sel.onchange = drawMetrics;
  drawMetrics();

  const drawElo = col => {
    const c = Number(col);
    const tr = [];
    careers.forEach((cr, i) => {
      const rs = (((cr || {}).elo) || []).filter(r => Array.isArray(r) && k.isNum(r[c]));
      if (rs.length) tr.push({ type: 'scatter', mode: 'lines', name: names[i], x: rs.map(r => r[0]), y: rs.map(r => r[c]), line: { color: ECOL[i], width: 2, shape: 'hv' }, hovertemplate: '%{x}: %{y:.0f}<extra>' + k.esc(short[i]) + '</extra>' });
    });
    if (tr.length) k.plot('cmp-elo', tr, k.layout(Object.assign(k.legendTop(), { margin: { l: 50, r: 10, t: 34, b: 36 }, xaxis: { type: 'date', title: 'Date' }, yaxis: { title: ['', 'Overall', 'Hard', 'Clay', 'Grass'][c] + ' Elo' } })));
    else document.getElementById('cmp-elo').innerHTML = k.muted('No Elo history in the career files.');
  };
  drawElo('1');
  k.wireToggle(body, 'cmp-elo-s', drawElo);

  const drawSR = surf => {
    const tr = [];
    careers.forEach((cr, i) => {
      let rs = (((cr || {}).serve_return) || []).filter(r => Array.isArray(r) && r[1] === surf);
      if (!rs.length && surf === 'all') {
        const cnt = {}; (((cr || {}).serve_return) || []).forEach(r => { cnt[r[1]] = (cnt[r[1]] || 0) + 1; });
        const best = Object.keys(cnt).sort((x, y) => cnt[y] - cnt[x])[0];
        rs = (((cr || {}).serve_return) || []).filter(r => r[1] === best);
      }
      if (!rs.length) return;
      k.band(rs.map(r => ({ x: r[0], y: r[2], se: r[6], text: r[0] })), ECOL[i], short[i] + ' serve').forEach(t => tr.push(t));
      k.band(rs.map(r => ({ x: r[0], y: r[3], se: r[7], text: r[0] })), ECOL[i], short[i] + ' return', { dash: 'dot' }).forEach(t => tr.push(t));
    });
    if (tr.length) k.plot('cmp-sr', tr, k.layout(Object.assign(k.legendTop(), { margin: { l: 50, r: 10, t: 34, b: 36 }, xaxis: { type: 'date', title: 'Date' }, yaxis: { title: 'Rating (log-odds of holding)', zeroline: true, zerolinecolor: '#6e7681' } })));
    else document.getElementById('cmp-sr').innerHTML = k.muted('No serve/return path on this surface.');
  };
  drawSR('all');
  k.wireToggle(body, 'cmp-sr-s', drawSR);

  k.styleBlock(document.getElementById('cmp-st-a'), T, (careers[0] || {}).style || null, { stack: true });
  k.styleBlock(document.getElementById('cmp-st-b'), T, (careers[1] || {}).style || null, { stack: true });
}

if (typeof TA.route === 'function') TA.route('compare', render);
})(window.TA || (window.TA = {}));
