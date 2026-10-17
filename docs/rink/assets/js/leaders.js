/* The Quant Rink — leaderboards (#/leaders).
 *
 * At a glance: the top five on the headline metrics for forwards, defencemen and goalies. Then any metric
 * of the season catalogues, for forwards, defencemen, all skaters or goalies, qualified players only or
 * all, best or worst, one team or all, with the percentile beside each value.
 *
 * Address: #/leaders?p=F|D|A|G&m=<metric key> (&s=<season>).
 * Data: data/<S>/skaters.json and goalies.json (the catalogues), data/<S>/leaders.json as the fallback
 * ({metric: [[pid, value]]}, or {"boards": {...}}). Uses RK.fk. */
(function (RK) {
'use strict';

const K = () => RK.fk;
const S0 = { pool: 'F', metric: '', qual: true, team: '', dir: 'best', n: 50, season: null };
const POOLS = [['F', 'Forwards'], ['D', 'Defence'], ['A', 'All skaters'], ['G', 'Goalies']];

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  const qp = String(qy.p || qy.g || '').toUpperCase();
  if (POOLS.some(p => p[0] === qp)) S0.pool = qp;
  if (qy.m) S0.metric = String(qy.m);
  el.innerHTML = '<div class="card"><div class="card-header">Leaders at a glance <span class="card-sub" id="ld-gsub">Loading…</span></div><div id="ld-glance"></div></div>' +
    '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="ld-sub"></span><span class="gq-ctl">' + k.toggle('ld-pool', POOLS, S0.pool) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Metric<select id="ld-metric" class="gq-wide"></select></label><label>Team<select id="ld-team"><option value="">All teams</option></select></label>' +
    '<label>Show<select id="ld-dir"><option value="best">Best first</option><option value="worst">Worst first</option></select></label><label>How many<select id="ld-n"><option>25</option><option>50</option><option>100</option><option value="999">All</option></select></label>' +
    '<label class="inline"><input id="ld-qual" type="checkbox"> qualified only</label></div><div id="ld-table"></div><div class="pg-note gq-note" id="ld-note"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'skaters.json'), k.loadY(S, 'goalies.json'), k.loadNames()]).then(res => ({ S: S, sk: res[0], gk: res[1] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, sk = k.catOf(o.sk), gk = k.catOf(o.gk), $ = k.$;
    if (!sk && !gk) return fallback(el, S, o.sk);
    if (sk) k.learnCat(sk);
    if (gk) k.learnCat(gk);
    if (S0.season !== S) { S0.season = S; S0.team = ''; }
    const pools = {};
    if (sk) {
      const P = sk.players;
      ['F', 'D'].forEach(g => { pools[g] = { cat: sk, ids: Object.keys(P).filter(id => (P[id].group || k.groupOf(P[id].pos)) === g), metrics: k.metricsFor(sk, g), pctKey: 'pct_pos' }; });
      pools.A = { cat: sk, ids: Object.keys(P).filter(id => (P[id].group || k.groupOf(P[id].pos)) !== 'G'), metrics: k.allMetrics(sk).filter(m => k.scopeOk(m, 'F') && k.scopeOk(m, 'D')), pctKey: 'pct' };
    }
    if (gk) pools.G = { cat: gk, ids: Object.keys(gk.players), metrics: k.allMetrics(gk), pctKey: 'pct' };
    glance(S, pools);
    $('ld-pool').querySelectorAll('button').forEach(b => { b.disabled = !pools[b.dataset.v] || !pools[b.dataset.v].ids.length; });
    if (!pools[S0.pool]) S0.pool = Object.keys(pools)[0];
    $('ld-pool').querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === S0.pool));
    const setup = () => {
      const pl = pools[S0.pool], ms = pl.metrics;
      if (!ms.some(m => m.key === S0.metric)) S0.metric = (k.headline(ms, k.PREFS[S0.pool === 'A' ? 'F' : S0.pool] || [], 1)[0] || ms[0] || {}).key || '';
      $('ld-metric').innerHTML = k.groups(ms).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === S0.metric ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      const teams = Array.from(new Set(pl.ids.map(id => pl.cat.players[id].team).filter(Boolean))).sort();
      if (S0.team && teams.indexOf(S0.team) < 0) S0.team = '';
      $('ld-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '"' + (t === S0.team ? ' selected' : '') + '>' + k.esc(t) + '</option>').join('');
    };
    setup();
    $('ld-dir').value = S0.dir; $('ld-n').value = String(S0.n); $('ld-qual').checked = S0.qual;
    const draw = () => board(S, pools[S0.pool]);
    k.wireToggle(el, 'ld-pool', v => { S0.pool = v; S0.metric = ''; setup(); draw(); });
    $('ld-metric').onchange = e => { S0.metric = e.target.value; draw(); };
    $('ld-team').onchange = e => { S0.team = e.target.value; draw(); };
    $('ld-dir').onchange = e => { S0.dir = e.target.value; draw(); };
    $('ld-n').onchange = e => { S0.n = Number(e.target.value); draw(); };
    $('ld-qual').onchange = e => { S0.qual = e.target.checked; draw(); };
    draw();
  });
}

function glance(S, pools) {
  const k = K();
  const boxes = [];
  [['F', 'Forwards', 3], ['D', 'Defence', 3], ['G', 'Goalies', 3]].forEach(z => {
    const pl = pools[z[0]];
    if (!pl) return;
    const P = pl.cat.players;
    const ids = pl.ids.filter(id => P[id].qualified !== false);
    if (!ids.length) return;
    k.headline(pl.metrics, k.PREFS[z[0]] || [], z[2]).forEach(m => {
      const top = ids.filter(id => k.isNum((P[id].values || {})[m.key])).sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return m.lower ? -d : d; }).slice(0, 5);
      if (!top.length) return;
      boxes.push('<div class="gq-mini"><div class="gq-mini-h"><a href="' + k.withQ('#/leaders', S, { p: z[0], m: m.key }) + '">' + k.esc(z[1] + ' · ' + m.label) + (m.lower ? ' ↓' : '') + '</a></div>' +
        top.map((id, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + k.playerLink(id, P[id].name, S) + '<span class="gq-mini-v">' + k.fmt(m, P[id].values[m.key]) + '</span></div>').join('') + '</div>');
    });
  });
  k.set('ld-glance', boxes.length ? '<div class="gq-glance">' + boxes.join('') + '</div>' : k.muted('No qualified players yet.'));
  k.set('ld-gsub', k.esc(k.sLabel(S)) + ' · qualified players · click a heading for the full board');
}

function board(S, pl) {
  const k = K();
  if (!pl) { k.set('ld-table', k.muted('No catalogue for this pool yet.')); return; }
  const P = pl.cat.players;
  const m = pl.metrics.find(x => x.key === S0.metric);
  if (!m) { k.set('ld-table', k.muted('No metrics for this pool yet.')); return; }
  const scale = k.toiScale(P);
  let ids = pl.ids.filter(id => k.isNum((P[id].values || {})[m.key]) && (!S0.qual || P[id].qualified !== false) && (!S0.team || P[id].team === S0.team));
  ids.sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return (m.lower ? -d : d) * (S0.dir === 'worst' ? -1 : 1); });
  const total = ids.length;
  ids = ids.slice(0, S0.n);
  const vals = ids.map(id => P[id].values[m.key]);
  const lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0]));
  const bar = v => { const span = hi - lo || 1; const z = (0 - lo) / span * 100, w = Math.abs(v) / span * 100; return '<span class="gf-hbar"><i style="left:' + (v >= 0 ? z : z - w).toFixed(1) + '%;width:' + Math.max(1, w).toFixed(1) + '%"></i></span>'; };
  const pc = p => ((S0.pool === 'F' || S0.pool === 'D' ? (p.pct_pos || p.pct) : p.pct) || {})[m.key];
  k.set('ld-table', ids.length ? k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'GP', align: 'right' }, { label: 'TOI', align: 'right', title: 'Minutes' }, { label: m.label + (m.lower ? ' ↓' : ''), align: 'right', title: k.cleanDesc(m.desc || '') }, { label: '', sortable: false }, { label: 'Pct', align: 'right' }],
    ids.map((id, i) => { const p = P[id], v = p.values[m.key];
      return { _href: k.playerHref(id, S), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: p.name, html: k.playerLink(id, p.name, S) + (p.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') }, { v: p.team || '', html: k.teamChip(p.team, S) }, { v: p.pos, html: k.esc(k.posLabel(p.pos || '')) },
        { v: k.gpOf(p), html: k.int(k.gpOf(p)) }, { v: k.toiOf(p, scale), html: k.int(k.toiOf(p, scale)) }, { v: v, html: '<strong>' + k.fmt(m, v) + '</strong>' }, { v: v, html: bar(v) }, { v: pc(p), html: k.pill(pc(p)) }] }; }), { compact: true, sticky: true })
    : k.muted('Nobody with this metric matches.'));
  k.sortable(k.$('ld-table'));
  const name = { F: 'forwards', D: 'defencemen', A: 'skaters', G: 'goalies' }[S0.pool];
  k.set('ld-sub', (S0.dir === 'worst' ? 'Bottom ' : 'Top ') + Math.min(S0.n, total) + ' of ' + total + ' ' + name + ' · ' + k.sLabel(S));
  const q = (pl.cat.qualification || {})[S0.pool === 'A' ? 'F' : S0.pool] || pl.cat.qualification_note;
  k.set('ld-note', '<strong>' + k.esc(m.label) + '</strong>: ' + k.esc(k.cleanDesc(m.desc || '')) + (k.isNum(m.stabilises_at) ? ' Stabilises at about ' + k.int(m.stabilises_at) + ' ' + k.esc(m.unit || (S0.pool === 'G' ? 'shots' : 'minutes')) + '.' : '') +
    (q && typeof q === 'string' ? ' Qualified: ' + k.esc(q) + '.' : '') + ' Percentiles are against qualified ' + (S0.pool === 'F' || S0.pool === 'D' ? name + ' (the position pool)' : name) + ' after shrinking towards the pool mean. ' + k.glossLink(m.key, 'Glossary →') +
    ' · <a href="' + k.withQ('#/lab', S, { kind: S0.pool === 'G' ? 'G' : 'S', x: m.key }) + '">In the lab →</a>');
}

/* leaders.json when the catalogues are missing: {metric: [[pid, value]]} or {"boards": {...}}. */
function fallback(el, S, raw) {
  const k = K();
  return k.loadY(S, 'leaders.json').then(d => {
    if (!k.alive(el)) return;
    // leaders.json: {skaters|goalies: {key: {label, fmt, lower, rows: [[id, value, name, team]]}}} or flat {key: [[id, value]]}
    const boards = [];
    if (d && d.ok !== false) {
      ['skaters', 'goalies'].forEach(kind => { const X = d[kind]; if (X && typeof X === 'object') Object.keys(X).forEach(key => { const b = X[key]; if (b && Array.isArray(b.rows) && b.rows.length) boards.push({ label: (kind === 'goalies' ? 'Goalies · ' : '') + (b.label || k.titleCase(key)), fmt: b.fmt, rows: b.rows }); }); });
      if (!boards.length) { const B = d.boards || d.leaders || d; Object.keys(B).forEach(x => { if (Array.isArray(B[x]) && B[x].length) boards.push({ label: (d.labels || {})[x] || k.titleCase(x), rows: B[x] }); }); }
    }
    if (!boards.length) { el.innerHTML = k.card('Leaders', '', k.notBuilt('The ' + k.sLabel(S) + ' player catalogues', raw)); return; }
    el.innerHTML = k.card('Leaders', k.esc(k.sLabel(S)), '<div class="gq-glance">' + boards.map(b => '<div class="gq-mini"><div class="gq-mini-h">' + k.esc(b.label) + '</div>' +
      b.rows.slice(0, 10).map((r, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + k.playerLink(String(Array.isArray(r) ? r[0] : r.pid), Array.isArray(r) ? r[2] : r.name, S) + '<span class="gq-mini-v">' + k.fmtV(Array.isArray(r) ? r[1] : r.value, b.fmt) + '</span></div>').join('') + '</div>').join('') + '</div>');
  });
}

if (typeof RK.route === 'function') { try { RK.route('leaders', render); } catch (e) { /* bound */ } }
})(window.RK || (window.RK = {}));
