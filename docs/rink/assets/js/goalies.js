/* The Quant Rink — goaltenders (#/goalies): goals saved above expected by shot danger and shot type, and
 * workload.
 *
 * The catalogue table (any metric can be added), GSAx split by low, medium and high danger for the
 * busiest goalies, a heat table of GSAx (or save percentage) by shot type, and workload: shots and
 * expected goals faced against GSAx per 60, sized by games. GSAx = expected goals faced − goals allowed,
 * on unblocked shots on goal with our xG model (see the methodology).
 *
 * Data: data/<S>/goalies.json, the catalogue {"metrics", "players": {pid: {"name","team","pos","age","gp","toi",
 * "qualified","values","pct","pct_pos"}}}. Keys are found by METRIC.group ("By danger", "By shot type",
 * "Workload") and by name patterns. Address: #/goalies (&s=<season>). Uses RK.fk (skaters.js). */
(function (RK) {
'use strict';

const K = () => RK.fk;
const ST = { q: '', team: '', floor: null, qual: true, extra: [], season: null, typeMode: 'gsax', work: 'shots' };

const DANGER = [['low', 'Low danger', /(^|_)(low|ld|lo)(_|$)|low_danger/], ['med', 'Medium danger', /(^|_)(med|md|mid|medium)(_|$)|med(ium)?_danger/], ['high', 'High danger', /(^|_)(high|hd|hi)(_|$)|high_danger/]];
const TYPES = [['wrist', 'Wrist and snap'], ['snap', 'Snap'], ['slap', 'Slap'], ['back', 'Backhand'], ['tip', 'Tip-in'], ['deflect', 'Deflection'], ['wrap', 'Wrap-around'], ['bat', 'Batted'], ['poke', 'Poke'], ['between', 'Between the legs'], ['cradle', 'Cradle']];

/* Danger keys for GSAx (and save %): {low: key, med: key, high: key}. */
function dangerKeys(metrics, kind) {
  const re = kind === 'sv' ? /(sv|save)/ : /gsax|gsa_x|saved_above/;
  const out = {};
  DANGER.forEach(d => { const m = metrics.find(x => re.test(x.key) && d[2].test(x.key) && !/60|per/.test(x.key)); if (m) out[d[0]] = m; });
  return out;
}
function typeKeys(metrics, kind) {
  const re = kind === 'sv' ? /(sv|save)/ : /gsax|gsa_x|saved_above/;
  const out = [];
  TYPES.forEach(t => { const m = metrics.find(x => re.test(x.key) && x.key.indexOf(t[0]) >= 0 && !out.some(o => o.m === x)); if (m) { const l = String(m.label || '').replace(/^GSAx\s*/i, '').replace(/\s*sv%$/i, '').trim(); out.push({ type: t[0], label: l ? l.charAt(0).toUpperCase() + l.slice(1) : t[1], m: m }); } });
  return out;
}

function render(el, params, state) {
  const k = K();
  el.innerHTML = '<div class="card"><div class="card-header">Goaltenders <span class="card-sub" id="gk-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls"><label>Search<input id="gk-q" class="gq-search" type="search" placeholder="name or team…"></label>' +
    '<label>Team<select id="gk-team"><option value="">All teams</option></select></label>' +
    '<label><span>Min TOI <span id="gk-floor-v"></span> min</span><input id="gk-floor" type="range" min="0" max="4000" step="20"></label>' +
    '<label>Add any metric<select id="gk-extra" class="gq-wide"><option value="">—</option></select></label>' +
    '<label class="inline"><input id="gk-qual" type="checkbox"> qualified only</label><label>&nbsp;<button type="button" id="gk-clear" class="gq-btn">Clear added</button></label></div>' +
    '<div id="gk-chips" class="gq-chips"></div><div id="gk-table">' + k.muted('Loading…') + '</div><div class="pg-note gq-note" id="gk-note"></div></div>' +
    '<div class="card"><div class="card-header">GSAx by shot danger <span class="card-sub">Goals saved above expected on low-, medium- and high-danger shots (danger bands from our xG); the busiest goalies by shots faced. Right of zero is better than an average goalie on the same shots.</span></div><div id="gk-danger" class="gf-chart-lg"></div></div>' +
    '<div class="card"><div class="card-header">By shot type <span class="card-sub" id="gk-type-sub">Each cell is the goalie against one shot type; red is better than expected, blue worse.</span><span class="gq-ctl">' + k.toggle('gk-type-m', [['gsax', 'GSAx'], ['sv', 'Save %']], ST.typeMode) + '</span></div><div id="gk-types"></div></div>' +
    '<div class="card"><div class="card-header">Workload <span class="card-sub">How much each goalie faced against how well he did it; marker size is games played. Click a dot for the goalie.</span><span class="gq-ctl">' + k.toggle('gk-work', [['shots', 'Shots faced'], ['xga', 'xG faced / 60']], ST.work) + '</span></div><div id="gk-work-c" class="gf-chart-lg"></div><div class="pg-note gq-note" id="gk-work-n"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'goalies.json'), k.loadNames()]).then(res => ({ S: S, raw: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = k.catOf(o.raw), $ = k.$;
    if (!cat) { $('gk-table').innerHTML = k.notBuilt('The ' + k.sLabel(S) + ' goaltender catalogue', o.raw); $('gk-sub').textContent = ''; ['gk-danger', 'gk-types', 'gk-work-c'].forEach(x => k.empty(x, '')); return; }
    k.learnCat(cat);
    if (ST.season !== S) { ST.season = S; ST.floor = null; ST.team = ''; }
    const P = cat.players;
    const ids = Object.keys(P);
    const scale = k.toiScale(P);
    const metrics = k.allMetrics(cat), meta = k.metaOf(metrics);
    const maxN = Math.max.apply(null, ids.map(id => k.toiOf(P[id], scale)).concat([60]));
    $('gk-floor').max = String(Math.ceil(maxN / 20) * 20);
    const floorDef = [cat.toi_floor, cat.floor, (cat.floors || {}).G].find(k.isNum);
    if (ST.floor === null || ST.floor > maxN) ST.floor = k.isNum(floorDef) ? Math.min(floorDef * (floorDef > 6000 ? 1 / 60 : 1), maxN) : 0;
    $('gk-floor').value = ST.floor; $('gk-floor-v').textContent = k.int(ST.floor);
    const teams = Array.from(new Set(ids.map(id => P[id].team).filter(Boolean))).sort();
    $('gk-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + k.esc(t + ' · ' + k.teamName(t)) + '</option>').join('');
    $('gk-extra').innerHTML = '<option value="">—</option>' + k.groups(metrics).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '">' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
    ST.extra = ST.extra.filter(x => meta[x]);
    const heads = k.headline(metrics, k.PREFS.G, 7);
    if (!typeKeys(metrics, 'sv').length) { const tg = k.$('gk-type-m'); if (tg) tg.style.display = 'none'; ST.typeMode = 'gsax'; }
    const ctx = { S: S, P: P, ids: ids, scale: scale, metrics: metrics, meta: meta, heads: heads, cat: cat };
    const draw = () => { drawTable(ctx); drawDanger(ctx); drawTypes(ctx); drawWork(ctx); };
    $('gk-q').value = ST.q; $('gk-qual').checked = ST.qual;
    let t = null;
    $('gk-q').oninput = e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(() => drawTable(ctx), 150); };
    $('gk-team').onchange = e => { ST.team = e.target.value; draw(); };
    $('gk-qual').onchange = e => { ST.qual = e.target.checked; draw(); };
    $('gk-floor').oninput = e => { ST.floor = Number(e.target.value); $('gk-floor-v').textContent = k.int(ST.floor); };
    $('gk-floor').onchange = draw;
    $('gk-extra').onchange = e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0 && heads.every(m => m.key !== x)) ST.extra.push(x); e.target.value = ''; drawTable(ctx); };
    $('gk-clear').onclick = () => { ST.extra = []; drawTable(ctx); };
    $('gk-chips').onclick = ev => { const b = ev.target.closest('[data-rm]'); if (!b) return; ST.extra = ST.extra.filter(x => x !== b.dataset.rm); drawTable(ctx); };
    k.wireToggle(el, 'gk-type-m', v => { ST.typeMode = v; drawTypes(ctx); });
    k.wireToggle(el, 'gk-work', v => { ST.work = v; drawWork(ctx); });
    draw();
  });
}

function pool(ctx) {
  const k = K(), P = ctx.P;
  return ctx.ids.filter(id => { const p = P[id]; return k.toiOf(p, ctx.scale) >= ST.floor && (!ST.qual || p.qualified !== false) && (!ST.team || String(p.team) === ST.team); });
}

function drawTable(ctx) {
  const k = K(), P = ctx.P, S = ctx.S;
  const q = k.fold(ST.q.trim());
  const extras = ST.extra.map(x => ctx.meta[x]).filter(Boolean);
  const cols = ctx.heads.concat(extras.filter(m => ctx.heads.indexOf(m) < 0));
  const ids = pool(ctx).filter(id => !q || k.fold(String(P[id].name || k.name(id)) + ' ' + (P[id].team || '') + ' ' + k.teamName(P[id].team)).indexOf(q) >= 0);
  const sm = ctx.heads[0] || {};
  ids.sort((a, b) => { const qa = P[a].qualified === false ? 1 : 0, qb = P[b].qualified === false ? 1 : 0; if (qa !== qb) return qa - qb; const va = (P[a].values || {})[sm.key], vb = (P[b].values || {})[sm.key]; return ((k.isNum(vb) ? vb : -1e9) - (k.isNum(va) ? va : -1e9)) * (sm.lower ? -1 : 1) || k.toiOf(P[b], ctx.scale) - k.toiOf(P[a], ctx.scale); });
  const head = [{ label: '#', sortable: false }, { label: 'Goalie' }, { label: 'Team' }, { label: 'Age', align: 'right' }, { label: 'GP', align: 'right' }, { label: 'TOI', align: 'right', title: 'Minutes in net' }]
    .concat(cols.map(m => ({ label: k.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: k.cleanDesc(m.desc || m.label) + (k.isNum(m.stabilises_at) ? ' · stabilises at about ' + k.int(m.stabilises_at) + ' ' + (m.unit || 'shots') : '') })));
  const rows = ids.map((id, i) => { const p = P[id], gp = k.gpOf(p);
    return { _href: k.playerHref(id, S), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: p.name || k.name(id), html: '<a class="ply-link" href="' + k.playerHref(id, S) + '">' + k.esc(p.name || k.name(id)) + '</a>' + (p.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') },
      { v: p.team || '', html: k.teamChip(p.team, S) }, { v: p.age, html: k.isNum(p.age) ? k.num(p.age, 0) : '—', align: 'right' }, { v: gp, html: k.int(gp), align: 'right' }, { v: k.toiOf(p, ctx.scale), html: k.int(k.toiOf(p, ctx.scale)), align: 'right' }]
      .concat(cols.map(m => { const v = (p.values || {})[m.key], pc = (p.pct || {})[m.key]; return { v: k.isNum(v) ? (m.lower ? -v : v) : -1e9, html: '<span class="gq-val">' + k.fmt(m, v) + '</span> ' + k.pill(pc), align: 'right' }; })) }; });
  k.set('gk-table', rows.length ? k.table(head, rows, { compact: true, sticky: true }) : k.muted('No goalie matches these filters.'));
  k.sortable(k.$('gk-table'));
  k.set('gk-chips', extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="gq-chip" data-rm="' + k.esc(m.key) + '">' + k.esc(m.label) + ' ×</button>').join(' ') : '');
  k.set('gk-sub', ids.length + ' of ' + ctx.ids.length + ' goalies · ' + k.sLabel(S) + ' · sorted by ' + k.esc(sm.label || 'ice time') + '; click a header to sort');
  const gs = ctx.metrics.find(m => /^gsax$/.test(m.key)) || ctx.metrics.find(m => /gsax/.test(m.key));
  const gpFloor = ((ctx.cat && ctx.cat.reference) || {}).floors ? ctx.cat.reference.floors.gp : null;
  k.set('gk-note', 'Pills are percentiles among qualified goalies (100 = best)' + (k.isNum(gpFloor) ? '; GSAx totals, value and the other counts need ' + k.int(gpFloor) + ' games and rates 100 unblocked shots faced before they get one, so early in the season most cells are values only' : '') + '. ' + (gs && k.isNum(gs.stabilises_at) ? 'GSAx per shot stabilises only at about ' + k.int(gs.stabilises_at) + ' ' + k.esc(gs.unit || 'shots') + ': a season of a backup is mostly noise, and the percentiles shrink it towards the mean before ranking. ' : 'Save percentage and GSAx take thousands of shots to stabilise; the percentiles shrink small samples towards the mean before ranking. ') +
    'GSAx counts unblocked shots on goal only (misses and blocks never test the goalie), with the shooter\'s xG from our model; rebounds the goalie allowed are themselves shots and count against him. ' + k.glossLink('gsax', 'Glossary →') + ' · <a href="#/methodology/goalies">Methodology →</a>');
}

function drawDanger(ctx) {
  const k = K(), P = ctx.P, node = k.$('gk-danger');
  if (!node) return;
  const D = dangerKeys(ctx.metrics, 'gsax');
  if (Object.keys(D).length < 2) { k.empty(node, 'GSAx by danger is not in this catalogue yet.'); return; }
  const shotsKey = k.pick(ctx.metrics, ['shots_faced', 'sa', 'shots_against', /shots?_faced|^sa$|shots_against/]);
  const ids = pool(ctx).filter(id => Object.keys(D).some(d => k.isNum((P[id].values || {})[D[d].key])));
  ids.sort((a, b) => (shotsKey ? ((P[b].values || {})[shotsKey] || 0) - ((P[a].values || {})[shotsKey] || 0) : k.toiOf(P[b], ctx.scale) - k.toiOf(P[a], ctx.scale)));
  const top = ids.slice(0, k.narrow(node) ? 18 : 32);
  const tot = id => k.sum(Object.keys(D).map(d => (P[id].values || {})[D[d].key]));
  top.sort((a, b) => tot(b) - tot(a));
  const COL = { low: '#79c0ff', med: '#d29922', high: '#f85149' };
  const names = top.map(id => k.surname(P[id].name || k.name(id)) + ' ' + (P[id].team || ''));
  const tr = DANGER.filter(d => D[d[0]]).map(d => ({ type: 'bar', orientation: 'h', name: d[1], y: names, x: top.map(id => (P[id].values || {})[D[d[0]].key]), customdata: top.map(id => k.playerHref(id, ctx.S)),
    marker: { color: COL[d[0]] }, hovertemplate: '%{y}<br>' + d[1] + ': %{x:+.1f} GSAx<extra></extra>' }));
  tr.push({ type: 'scatter', mode: 'markers', name: 'Total', y: names, x: top.map(tot), marker: { symbol: 'diamond', size: 9, color: '#e6edf3', line: { color: '#0d1117', width: 1 } }, hovertemplate: '%{y}<br>Total %{x:+.1f} GSAx<extra></extra>' });
  node.style.height = Math.max(320, 22 * top.length + 90) + 'px';
  k.plot(node, tr, k.layout(Object.assign({ barmode: 'relative', margin: { l: 120, r: 12, t: 34, b: 36 }, yaxis: { autorange: 'reversed', automargin: true, tickfont: { size: 10 } }, xaxis: { title: 'Goals saved above expected', zeroline: true, zerolinecolor: '#8b949e' } }, k.legendTop())));
  k.clickThrough(node);
}

function drawTypes(ctx) {
  const k = K(), P = ctx.P, host = k.$('gk-types');
  if (!host) return;
  let T = typeKeys(ctx.metrics, ST.typeMode);
  if (!T.length && ST.typeMode === 'sv') T = typeKeys(ctx.metrics, 'gsax');
  if (!T.length) { host.innerHTML = k.muted('Splits by shot type are not in this catalogue yet.'); return; }
  const ids = pool(ctx).filter(id => T.some(t => k.isNum((P[id].values || {})[t.m.key])));
  const shotsKey = k.pick(ctx.metrics, ['shots_faced', 'sa', /shots?_faced|^sa$/]);
  ids.sort((a, b) => (shotsKey ? ((P[b].values || {})[shotsKey] || 0) - ((P[a].values || {})[shotsKey] || 0) : k.toiOf(P[b], ctx.scale) - k.toiOf(P[a], ctx.scale)));
  const max = {};
  T.forEach(t => { const vs = ids.map(id => (P[id].values || {})[t.m.key]).filter(k.isNum); const md = ST.typeMode === 'sv' ? k.median(vs) : 0; max[t.type] = { c: md, m: Math.max.apply(null, vs.map(v => Math.abs(v - md)).concat([1e-6])) }; });
  const cell = (id, t) => {
    const v = (P[id].values || {})[t.m.key];
    if (!k.isNum(v)) return { v: null, html: '—', align: 'right' };
    const z = (v - max[t.type].c) / max[t.type].m * (t.m.lower ? -1 : 1);
    const bg = z >= 0 ? 'rgba(248,81,73,' + (0.1 + 0.55 * Math.min(1, z)).toFixed(2) + ')' : 'rgba(88,166,255,' + (0.1 + 0.55 * Math.min(1, -z)).toFixed(2) + ')';
    return { v: v, html: k.fmt(t.m, v), align: 'right', style: 'background:' + bg, title: (P[id].name || '') + ' · ' + t.label + ': ' + k.fmt(t.m, v) };
  };
  host.innerHTML = k.table([{ label: 'Goalie' }, { label: 'Team' }].concat(T.map(t => ({ label: t.label, align: 'right', title: k.cleanDesc(t.m.desc || t.m.label) }))),
    ids.slice(0, 60).map(id => ({ _href: k.playerHref(id, ctx.S), cells: [{ v: P[id].name, html: k.playerLink(id, P[id].name, ctx.S) }, { v: P[id].team || '', html: k.teamChip(P[id].team, ctx.S) }].concat(T.map(t => cell(id, t))) })), { compact: true, sticky: true });
  k.sortable(host);
  k.set('gk-type-sub', (ST.typeMode === 'sv' ? 'Save percentage by shot type, coloured against the median goalie' : 'Goals saved above expected by shot type') + '; red is better, blue worse. The busiest 60 goalies in the filter above; small cells are noisy.');
}

function drawWork(ctx) {
  const k = K(), P = ctx.P, node = k.$('gk-work-c');
  if (!node) return;
  const xKey = ST.work === 'xga' ? k.pick(ctx.metrics, ['xga60', 'xg_faced60', /xga_?(per_?)?60|xg.*faced.*60/]) : k.pick(ctx.metrics, ['shots_faced', 'sa', 'shots_against', /shots?_faced|^sa$/]);
  const yKey = k.pick(ctx.metrics, ['gsax60', 'gsax_60', /gsax.*60/]) || k.pick(ctx.metrics, ['gsax', /^gsax/]);
  if (!xKey || !yKey) { k.empty(node, 'Workload metrics are not in this catalogue yet.'); k.set('gk-work-n', ''); return; }
  const ids = pool(ctx).filter(id => k.isNum((P[id].values || {})[xKey]) && k.isNum((P[id].values || {})[yKey]));
  if (ids.length < 3) { k.empty(node, 'Too few goalies above the floor.'); k.set('gk-work-n', ''); return; }
  const X = ids.map(id => P[id].values[xKey]), Y = ids.map(id => P[id].values[yKey]);
  const gp = ids.map(id => k.gpOf(P[id]) || 1), gmax = Math.max.apply(null, gp);
  const mx = ctx.meta[xKey], my = ctx.meta[yKey];
  k.plot(node, [{ type: 'scatter', mode: 'markers+text', x: X, y: Y, text: ids.map(id => k.surname(P[id].name || k.name(id))), textposition: 'top center', textfont: { size: 9, color: '#c9d1d9' },
    customdata: ids.map(id => k.playerHref(id, ctx.S)), hovertext: ids.map((id, i) => '<b>' + k.esc(P[id].name || k.name(id)) + '</b> ' + k.esc(P[id].team || '') + '<br>' + k.esc(mx.label) + ': ' + k.fmt(mx, X[i]) + '<br>' + k.esc(my.label) + ': ' + k.fmt(my, Y[i]) + '<br>' + gp[i] + ' GP'), hoverinfo: 'text',
    marker: { size: gp.map(g => 6 + 18 * Math.sqrt(g / gmax)), color: ids.map(id => k.teamColour(P[id].team)), opacity: 0.85, line: { color: '#0d1117', width: 1 } } }],
  k.layout({ margin: { l: 60, r: 12, t: 12, b: 46 }, xaxis: { title: mx.label, zeroline: false }, yaxis: { title: my.label, zeroline: true, zerolinecolor: '#6e7681' },
    shapes: [{ type: 'line', x0: k.median(X), x1: k.median(X), yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot' } }] }));
  k.clickThrough(node);
  const r = k.corr(X, Y);
  k.set('gk-work-n', 'Correlation r = ' + k.num(r, 2) + ' across ' + ids.length + ' goalies. ' + (k.isNum(r) && Math.abs(r) < 0.2 ? 'Little relation: on this evidence, facing more did not make goalies better or worse. ' : '') + 'The dotted line is the median workload.');
}

if (typeof RK.route === 'function') { try { RK.route('goalies', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
