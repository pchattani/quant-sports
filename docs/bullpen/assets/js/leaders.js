/* The Quant Bullpen — leaderboards (#/<L>/leaders).
 *
 * Any catalogue metric for hitters or pitchers, or any per-pitch arsenal metric for one pitch
 * type, with a sample floor, a qualified-only switch, a team filter, best or worst first and the
 * league's distribution drawn behind the leaders. "At a glance" shows the builder's own
 * pre-filtered boards (leaders.json) when they exist.
 *
 * Address: ?k=hitter|pitcher|pitch&m=<metric>&pt=<pitch type> presets the board.
 * Data: data/<L>/<S>/hitters.json, pitchers.json ("arsenal"), leaders.json. Uses BP.gk. */
(function (BP) {
'use strict';

const K = () => BP.gk;
const S0 = { kind: 'hitter', metric: '', pt: 'FF', floor: null, qual: true, team: '', dir: 'best', n: 50 };
const ARS_METRICS = [['stuff_plus', 'Stuff+', 'plus'], ['location_plus', 'Location+', 'plus'], ['pitching_plus', 'Pitching+', 'plus'], ['velo', 'Velocity', '1'], ['ivb', 'Induced vertical break', '1'], ['hb', 'Horizontal break', '1'],
  ['spin', 'Spin rate', 'rpm'], ['vaa', 'Vertical approach angle', '1'], ['ext', 'Extension', '1'], ['whiff_pct', 'Whiff%', 'pct'], ['csw_pct', 'CSW%', 'pct'], ['rv', 'Run value', 'signed'], ['rv100', 'Run value per 100', 'signed2'], ['usage', 'Usage', 'pct'], ['xwoba_plus', 'xwOBA+ against', '3']];
const ALIAS = { stuff_plus: ['stuff_plus', 'stuff'], location_plus: ['location_plus', 'location'], pitching_plus: ['pitching_plus', 'pitching'], velo: ['velo', 'velocity', 'release_speed'], ivb: ['ivb', 'induced_vb'], hb: ['hb', 'horz_break'],
  spin: ['spin', 'spin_rate'], vaa: ['vaa'], ext: ['ext', 'extension'], whiff_pct: ['whiff_pct', 'whiff'], csw_pct: ['csw_pct', 'csw'], rv: ['rv', 'run_value'], rv100: ['rv100', 'rv_per_100'], usage: ['usage', 'usage_pct'], xwoba_plus: ['xwoba_plus', 'xwoba', 'xwoba_against'] };
const LOWER_ARS = { xwoba_plus: true };

function render(el, params, state) {
  const k = K();
  const L = k.L(params, state);
  const q = params.query || {};
  if (q.k && /^(hitter|pitcher|pitch)$/.test(q.k)) S0.kind = q.k;
  if (q.m) S0.metric = q.m;
  if (q.pt) S0.pt = q.pt;
  el.innerHTML = '<div class="card"><div class="card-header">' + k.LN(L) + ' leaders <span class="card-sub" id="ld-sub">Loading…</span></div>' +
    '<div class="lab-controls gq-controls">' +
    '<label>Board' + k.select('ld-kind', [['hitter', 'Hitters'], ['pitcher', 'Pitchers'], ['pitch', 'Pitch types']], S0.kind) + '</label>' +
    '<label id="ld-pt-l">Pitch type<select id="ld-pt"></select></label>' +
    '<label>Metric<select id="ld-metric" class="gq-wide"></select></label>' +
    '<label>Min <span id="ld-floor-u"></span> <span id="ld-floor-v"></span><input id="ld-floor" type="range" min="0" max="700" step="5"></label>' +
    '<label class="inline"><input type="checkbox" id="ld-qual"> qualified only</label>' +
    '<label>Team<select id="ld-team"><option value="">All teams</option></select></label>' +
    '<label>Order' + k.select('ld-dir', [['best', 'Best first'], ['worst', 'Worst first']], S0.dir) + '</label>' +
    '<label>Show' + k.select('ld-n', [[25, 'Top 25'], [50, 'Top 50'], [100, 'Top 100'], [1000, 'All']], S0.n) + '</label>' +
    '</div><div id="ld-chart" style="height:420px"></div><div id="ld-table"></div><div class="pg-note gq-note" id="ld-note"></div></div>' +
    '<div class="card"><div class="card-header">At a glance <span class="card-sub">The top five on the headline metrics, qualified players only.</span></div><div id="ld-glance" class="gq-glance"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(L, S, 'hitters.json'), k.loadY(L, S, 'pitchers.json'), k.loadY(L, S, 'leaders.json'), k.loadNames()]).then(res => ({ S: S, res: res }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, hc = k.catOf(o.res[0], 'hitters'), pc = k.catOf(o.res[1], 'pitchers'), lead = o.res[2];
    if (hc) k.learnCat(hc);
    if (pc) k.learnCat(pc);
    const $ = id => document.getElementById(id);
    if (!hc && !pc) { $('ld-chart').innerHTML = k.notBuilt('The ' + k.LN(L) + ' ' + S + ' catalogues', o.res[0]); $('ld-sub').textContent = ''; $('ld-chart').style.height = 'auto'; glance(L, S, lead, null, null); return; }
    const ars = (pc && pc.arsenal) || {};
    const pts = {};
    Object.keys(ars).forEach(pid => Object.keys(ars[pid] || {}).forEach(pt => { if (pt !== 'all' && pt !== 'ALL') pts[pt] = (pts[pt] || 0) + 1; }));
    const ptList = Object.keys(pts).sort((a, b) => pts[b] - pts[a]);
    $('ld-pt').innerHTML = ptList.map(pt => '<option value="' + k.esc(pt) + '"' + (pt === S0.pt ? ' selected' : '') + '>' + k.esc(k.pitchName(pt)) + ' (' + pts[pt] + ')</option>').join('');
    if (!ptList.length) $('ld-kind').querySelector('option[value=pitch]').disabled = true;
    const teams = {};
    [hc, pc].forEach(c => { if (c) Object.keys(c.players).forEach(id => { const t = c.players[id].team; if (t) teams[t] = 1; }); });
    $('ld-team').innerHTML = '<option value="">All teams</option>' + Object.keys(teams).sort((a, b) => k.teamAbbr(a).localeCompare(k.teamAbbr(b))).map(t => '<option value="' + k.esc(t) + '">' + k.esc(k.teamAbbr(t)) + '</option>').join('');
    $('ld-qual').checked = S0.qual;
    const sync = () => {
      const kind = S0.kind;
      $('ld-pt-l').style.display = kind === 'pitch' ? '' : 'none';
      if (kind === 'pitch') {
        if (ptList.indexOf(S0.pt) < 0) S0.pt = ptList[0];
        const avail = ARS_METRICS.filter(m => Object.keys(ars).some(pid => { const r = (ars[pid] || {})[S0.pt]; return r && k.isNum(k.val(r, ALIAS[m[0]] || [m[0]])); }));
        if (!avail.find(m => m[0] === S0.metric)) S0.metric = (avail[0] || ARS_METRICS[0])[0];
        $('ld-metric').innerHTML = avail.map(m => '<option value="' + m[0] + '"' + (m[0] === S0.metric ? ' selected' : '') + '>' + k.esc(m[1]) + '</option>').join('');
        $('ld-floor-u').textContent = 'pitches';
      } else {
        const cat = kind === 'pitcher' ? pc : hc;
        const ms = (cat && cat.metrics) || [];
        if (!ms.find(m => m.key === S0.metric)) S0.metric = (k.headline(ms, kind === 'pitcher' ? k.PIT_PREFS : k.HIT_PREFS, 1)[0] || {}).key || '';
        $('ld-metric').innerHTML = k.groups(ms).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === S0.metric ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
        $('ld-floor-u').textContent = kind === 'pitcher' ? 'BF' : 'PA';
      }
      const maxN = kind === 'pitch' ? Math.max.apply(null, Object.keys(ars).map(pid => { const r = (ars[pid] || {})[S0.pt]; return r ? (k.val(r, ['n', 'pitches', 'count']) || 0) : 0; }).concat([100]))
        : Math.max.apply(null, Object.keys(((kind === 'pitcher' ? pc : hc) || { players: {} }).players).map(id => k.sampleOf((kind === 'pitcher' ? pc : hc).players[id], kind)).concat([100]));
      $('ld-floor').max = String(Math.ceil(maxN / 10) * 10);
      if (S0.floor === null || S0.floor > maxN) S0.floor = kind === 'pitch' ? Math.min(100, Math.round(maxN * 0.1)) : 0;
      $('ld-floor').value = S0.floor; $('ld-floor-v').textContent = S0.floor;
      $('ld-qual').parentNode.style.display = kind === 'pitch' ? 'none' : '';
    };
    const draw = () => drawBoard(L, S, hc, pc);
    $('ld-kind').onchange = e => { S0.kind = e.target.value; S0.floor = null; sync(); draw(); };
    $('ld-pt').onchange = e => { S0.pt = e.target.value; S0.floor = null; sync(); draw(); };
    $('ld-metric').onchange = e => { S0.metric = e.target.value; draw(); };
    $('ld-floor').oninput = e => { S0.floor = Number(e.target.value); $('ld-floor-v').textContent = S0.floor; };
    $('ld-floor').onchange = draw;
    $('ld-qual').onchange = e => { S0.qual = e.target.checked; draw(); };
    $('ld-team').onchange = e => { S0.team = e.target.value; draw(); };
    $('ld-dir').onchange = e => { S0.dir = e.target.value; draw(); };
    $('ld-n').onchange = e => { S0.n = Number(e.target.value); draw(); };
    sync();
    draw();
    glance(L, S, lead, hc, pc);
  });
}

function drawBoard(L, S, hc, pc) {
  const k = K();
  const kind = S0.kind;
  let rows = [], m, lower = false, fmt = '';
  if (kind === 'pitch') {
    const ars = (pc && pc.arsenal) || {};
    const def = ARS_METRICS.find(x => x[0] === S0.metric) || ARS_METRICS[0];
    m = { key: def[0], label: def[1] + ' · ' + k.pitchName(S0.pt), fmt: def[2] };
    lower = !!LOWER_ARS[def[0]]; fmt = def[2];
    Object.keys(ars).forEach(pid => {
      const r = (ars[pid] || {})[S0.pt];
      if (!r) return;
      const v = k.val(r, ALIAS[def[0]] || [def[0]]), n = k.val(r, ['n', 'pitches', 'count']) || 0;
      if (!k.isNum(v) || n < S0.floor) return;
      const p = ((pc || {}).players || {})[pid] || {};
      if (S0.team && String(p.team) !== S0.team) return;
      rows.push({ pid: pid, v: v, n: n, team: p.team, pct: (r.pct || {})[k.pick(r, ALIAS[def[0]] || [def[0]])], name: p.name, href: k.pitcherHref(L, pid, S) });
    });
  } else {
    const cat = kind === 'pitcher' ? pc : hc;
    if (!cat) { document.getElementById('ld-table').innerHTML = k.notBuilt('This catalogue', null); return; }
    m = k.metaOf(cat.metrics)[S0.metric] || { key: S0.metric, label: S0.metric };
    lower = !!m.lower; fmt = m.fmt;
    Object.keys(cat.players).forEach(pid => {
      const p = cat.players[pid], v = (p.values || {})[m.key], n = k.sampleOf(p, kind);
      if (!k.isNum(v) || n < S0.floor) return;
      if (S0.qual && p.qualified === false) return;
      if (S0.team && String(p.team) !== S0.team) return;
      rows.push({ pid: pid, v: v, n: n, team: p.team, pct: (p.pct || {})[m.key], name: p.name, pos: kind === 'pitcher' ? k.roleOf(p) : p.pos, href: kind === 'pitcher' ? k.pitcherHref(L, pid, S) : k.hitterHref(L, pid, S) });
    });
  }
  const all = rows.map(r => r.v);
  const good = (S0.dir === 'best') !== lower;
  rows.sort((a, b) => (good ? b.v - a.v : a.v - b.v) || b.n - a.n);
  const shown = rows.slice(0, S0.n);
  const host = document.getElementById('ld-table');
  const unit = kind === 'pitch' ? 'Pitches' : kind === 'pitcher' ? 'BF' : 'PA';
  host.innerHTML = shown.length ? k.table([{ label: '#', sortable: false }, { label: kind === 'hitter' ? 'Hitter' : 'Pitcher' }, { label: 'Team' }].concat(kind === 'pitch' ? [] : [{ label: kind === 'pitcher' ? 'Role' : 'Pos' }])
    .concat([{ label: unit, align: 'right' }, { label: m.label + (lower ? ' ↓' : ''), align: 'right', title: m.desc || '' }, { label: 'Pct', align: 'right', title: 'Percentile (100 = best)' }]),
  shown.map((r, i) => ({ _href: r.href, cells: [{ v: i + 1, cls: 'pos-cell' }, { v: r.name || k.name(r.pid), html: '<a class="ply-link" href="' + r.href + '">' + k.esc(r.name || k.name(r.pid)) + '</a>' }, { v: k.teamAbbr(r.team), html: k.teamChip(L, r.team, S) }]
    .concat(kind === 'pitch' ? [] : [{ v: r.pos || '', html: k.esc(r.pos || '—') }]).concat([{ v: r.n, html: k.int(r.n) }, { v: r.v, html: '<strong>' + k.fmtV(r.v, fmt) + '</strong>' }, { v: r.pct, html: k.pill(r.pct) }]) })), { compact: true, sticky: true })
    : k.muted('Nobody meets these filters. Lower the floor or untick qualified.');
  k.sortable(host);
  const sub = document.getElementById('ld-sub');
  if (sub) sub.textContent = rows.length + ' with a value · ' + (S0.dir === 'best' ? 'best' : 'worst') + ' first · ' + S;
  // Chart: the distribution as a strip, the leaders on top.
  const node = document.getElementById('ld-chart');
  const top = shown.slice(0, 20).slice().reverse();
  if (!top.length) { node.innerHTML = ''; node.style.height = 'auto'; return; }
  node.style.height = Math.max(260, 18 * top.length + 70) + 'px';
  const med = k.median(all);
  k.plot(node, [{ type: 'bar', orientation: 'h', y: top.map(r => k.surname(r.name || k.name(r.pid)) + ' · ' + k.teamAbbr(r.team)), x: top.map(r => r.v), marker: { color: top.map(r => k.pctColor(k.isNum(r.pct) ? r.pct : 50)) },
    customdata: top.map(r => r.href), text: top.map(r => k.fmtV(r.v, fmt)), textposition: 'outside', cliponaxis: false, hovertemplate: '%{y}: %{text}<extra></extra>' }],
  k.layout({ margin: { l: 150, r: 40, t: 10, b: 36 }, xaxis: { title: m.label, zeroline: false, range: rangeOf(all, top.map(r => r.v)) }, yaxis: { type: 'category', automargin: true },
    shapes: k.isNum(med) ? [{ type: 'line', x0: med, x1: med, yref: 'paper', y0: 0, y1: 1, line: { color: '#6e7681', dash: 'dot', width: 1 } }] : [] }));
  if (node.on) node.on('plotly_click', ev => { const h = ev.points && ev.points[0] && ev.points[0].customdata; if (h) location.hash = h; });
  const note = document.getElementById('ld-note');
  if (note) note.innerHTML = 'The dotted line is the median of everyone above the floor (' + k.fmtV(med, fmt) + '). ' + (kind === 'pitch' ? 'Per-pitch boards come from each pitcher\'s arsenal; percentiles are within the pitch type.' : 'Qualified means at or above the catalogue\'s sample floor; unticking it shows everyone with a value, and small samples swing a lot (the glossary gives each metric\'s stabilisation point).') +
    (m.desc ? ' <strong>' + k.esc(m.label) + '</strong>: ' + k.esc(m.desc) : '');
}
function rangeOf(all, top) {
  const k = K();
  const v = top.concat([k.median(all)]).filter(k.isNum);
  let lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
  if (lo > 0 && hi > 0 && lo / hi > 0.6) { const pad = (hi - lo) * 0.25 || hi * 0.05; return [lo - pad, hi + pad * 0.6]; }
  return [Math.min(0, lo), hi + (hi - Math.min(0, lo)) * 0.08];
}

/* The builder's boards (leaders.json: {hitters|pitchers: {metric: [[pid, v]]}} or {metric: [[pid, v]]}), else computed. */
function glance(L, S, lead, hc, pc) {
  const k = K();
  const host = document.getElementById('ld-glance');
  if (!host) return;
  const boards = [];
  const want = kind0 => (kind0 === 'pitcher' ? k.PIT_PREFS : k.HIT_PREFS).filter(x => typeof x === 'string').slice(0, 6);
  const fromLead = (obj, kind, cat) => want(kind).filter(key => (obj || {})[key]).forEach(key => {
    const list = obj[key];
    if (!Array.isArray(list) || !list.length) return;
    const m = (cat && k.metaOf(cat.metrics)[key]) || { key: key, label: key, fmt: '' };
    boards.push({ m: m, kind: kind, rows: list.slice(0, 5).map(r => (Array.isArray(r) ? { pid: String(r[0]), v: r[1] } : { pid: String(r.pid || r.id), v: r.value !== undefined ? r.value : r.v })) });
  });
  if (lead && lead.ok !== false) {
    if (lead.hitters || lead.pitchers) { fromLead(lead.hitters, 'hitter', hc); fromLead(lead.pitchers, 'pitcher', pc); }
    else fromLead(lead.leaders || lead, 'hitter', hc);
  }
  if (!boards.length) {
    [[hc, 'hitter', k.HIT_PREFS], [pc, 'pitcher', k.PIT_PREFS]].forEach(x => {
      if (!x[0]) return;
      k.headline(x[0].metrics, x[2], 6).forEach(m => {
        const rows = Object.keys(x[0].players).filter(pid => x[0].players[pid].qualified !== false && k.isNum((x[0].players[pid].values || {})[m.key]))
          .map(pid => ({ pid: pid, v: x[0].players[pid].values[m.key] })).sort((a, b) => (m.lower ? a.v - b.v : b.v - a.v)).slice(0, 5);
        if (rows.length) boards.push({ m: m, kind: x[1], rows: rows });
      });
    });
  }
  host.innerHTML = boards.length ? boards.map(b => '<div class="gq-mini"><div class="gq-mini-h">' + k.esc(b.m.label || b.m.key) + ' <span class="muted-inline">' + (b.kind === 'pitcher' ? 'pitchers' : 'hitters') + '</span></div>' +
    b.rows.map((r, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + k.playerLink(L, r.pid, null, S, b.kind) + '<span class="gq-mini-v">' + k.fmtV(r.v, b.m.fmt) + '</span></div>').join('') + '</div>').join('')
    : k.muted('No leaderboards yet.');
}

if (typeof BP.route === 'function') { BP.route('leaders', render); try { BP.route('#/<L>/leaders', render); } catch (e) { /* bound */ } }
})(window.BP || (window.BP = {}));
