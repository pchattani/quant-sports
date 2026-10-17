/* The Quant Gridiron — leaderboards (#/leaders).
 *
 * At a glance: the top five on the headline metrics of every position group. Then any metric of the
 * season catalogue for any group, qualified players only or above a sample floor, best or worst,
 * one team or all, with the percentile beside each value.
 *
 * Address: #/leaders?g=<group>&m=<metric key>.
 * Data: data/<S>/players.json (the catalogue), data/<S>/leaders.json as the fallback ({metric: [[pid,
 * value]]}, or {"boards": {...}}). Uses GI.fk. */
(function (GI) {
'use strict';

const K = () => GI.fk;
const S0 = { group: 'QB', metric: '', qual: true, team: '', dir: 'best', n: 50, season: null };

function render(el, params, state) {
  const k = K();
  const qy = params.query || {};
  if (qy.g && k.GROUPS.indexOf(String(qy.g).toUpperCase()) >= 0) S0.group = String(qy.g).toUpperCase();
  if (qy.m) S0.metric = String(qy.m);
  el.innerHTML = '<div class="card"><div class="card-header">Leaders at a glance <span class="card-sub" id="ld-gsub">Loading…</span></div><div id="ld-glance"></div></div>' +
    '<div class="card"><div class="card-header">Leaderboard <span class="card-sub" id="ld-sub"></span><span class="gq-ctl">' + k.toggle('ld-group', k.GROUPS.map(g => [g, g]), S0.group) + '</span></div>' +
    '<div class="lab-controls gq-controls"><label>Metric<select id="ld-metric" class="gq-wide"></select></label><label>Team<select id="ld-team"><option value="">All teams</option></select></label>' +
    '<label>Show<select id="ld-dir"><option value="best">Best first</option><option value="worst">Worst first</option></select></label><label>How many<select id="ld-n"><option>25</option><option>50</option><option>100</option><option value="999">All</option></select></label>' +
    '<label class="inline"><input id="ld-qual" type="checkbox"> qualified only</label></div><div id="ld-table"></div><div class="pg-note gq-note" id="ld-note"></div></div>';
  return k.ready().then(() => {
    const S = k.S(params, state);
    return Promise.all([k.loadY(S, 'players.json'), k.loadNames()]).then(res => ({ S: S, raw: res[0] }));
  }).then(o => {
    if (!k.alive(el)) return;
    const S = o.S, cat = k.catOf(o.raw), $ = k.$;
    if (!cat) return fallback(el, S, o.raw);
    k.learnCat(cat);
    if (S0.season !== S) { S0.season = S; S0.team = ''; }
    const P = cat.players;
    const by = {};
    Object.keys(P).forEach(id => { const g = k.groupOf(P[id].pos, P[id].group); (by[g] = by[g] || []).push(id); });
    glance(S, cat, by);
    $('ld-group').querySelectorAll('button').forEach(b => { b.disabled = !(by[b.dataset.v] || []).length; });
    const setup = () => {
      const ms = k.metricsFor(cat, S0.group);
      if (!ms.some(m => m.key === S0.metric)) S0.metric = (k.headline(ms, k.PREFS[S0.group] || [], 1)[0] || ms[0] || {}).key || '';
      $('ld-metric').innerHTML = k.groups(ms).map(g => '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === S0.metric ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      const teams = Array.from(new Set((by[S0.group] || []).map(id => P[id].team).filter(Boolean))).sort();
      $('ld-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + k.esc(t) + '"' + (t === S0.team ? ' selected' : '') + '>' + k.esc(t) + '</option>').join('');
      return ms;
    };
    let ms = setup();
    $('ld-dir').value = S0.dir; $('ld-n').value = String(S0.n); $('ld-qual').checked = S0.qual;
    const draw = () => board(S, cat, by, ms);
    k.wireToggle(el, 'ld-group', v => { S0.group = v; S0.metric = ''; S0.team = ''; ms = setup(); draw(); });
    $('ld-metric').onchange = e => { S0.metric = e.target.value; draw(); };
    $('ld-team').onchange = e => { S0.team = e.target.value; draw(); };
    $('ld-dir').onchange = e => { S0.dir = e.target.value; draw(); };
    $('ld-n').onchange = e => { S0.n = Number(e.target.value); draw(); };
    $('ld-qual').onchange = e => { S0.qual = e.target.checked; draw(); };
    draw();
  });
}

function glance(S, cat, by) {
  const k = K(), P = cat.players;
  const boxes = [];
  k.GROUPS.forEach(g => {
    const ids = (by[g] || []).filter(id => P[id].qualified !== false);
    if (!ids.length) return;
    const ms = k.headline(k.metricsFor(cat, g), k.PREFS[g] || [], g === 'QB' || g === 'WR' ? 3 : 2);
    ms.forEach(m => {
      const top = ids.filter(id => k.isNum((P[id].values || {})[m.key])).sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return m.lower ? -d : d; }).slice(0, 5);
      if (!top.length) return;
      boxes.push('<div class="gq-mini"><div class="gq-mini-h"><a href="' + k.withQ('#/leaders', S, { g: g, m: m.key }) + '">' + k.esc(g + ' · ' + m.label) + (m.lower ? ' ↓' : '') + '</a></div>' +
        top.map((id, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + k.playerLink(id, P[id].name, S) + '<span class="gq-mini-v">' + k.fmt(m, P[id].values[m.key]) + '</span></div>').join('') + '</div>');
    });
  });
  k.set('ld-glance', boxes.length ? '<div class="gq-glance">' + boxes.join('') + '</div>' : k.muted('No qualified players yet.'));
  k.set('ld-gsub', S + ' · qualified players · click a heading for the full board');
}

function board(S, cat, by, ms) {
  const k = K(), P = cat.players;
  const m = ms.find(x => x.key === S0.metric);
  if (!m) { k.set('ld-table', k.muted('No metrics for this group yet.')); return; }
  const sk = k.sampleKey(P, S0.group);
  let ids = (by[S0.group] || []).filter(id => k.isNum((P[id].values || {})[m.key]) && (!S0.qual || P[id].qualified !== false) && (!S0.team || P[id].team === S0.team));
  ids.sort((a, b) => { const d = P[b].values[m.key] - P[a].values[m.key]; return (m.lower ? -d : d) * (S0.dir === 'worst' ? -1 : 1); });
  const total = ids.length;
  ids = ids.slice(0, S0.n);
  const vals = ids.map(id => P[id].values[m.key]);
  const lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0]));
  const bar = v => { const span = hi - lo || 1; const z = (0 - lo) / span * 100, w = Math.abs(v) / span * 100; return '<span class="gf-hbar"><i style="left:' + (v >= 0 ? z : z - w).toFixed(1) + '%;width:' + Math.max(1, w).toFixed(1) + '%"></i></span>'; };
  k.set('ld-table', ids.length ? k.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'G', align: 'right' }, { label: sk[1], align: 'right' }, { label: m.label + (m.lower ? ' ↓' : ''), align: 'right', title: m.desc || '' }, { label: '', sortable: false }, { label: 'Pct', align: 'right' }],
    ids.map((id, i) => { const p = P[id], v = p.values[m.key];
      return { _href: k.playerHref(id, S), cells: [{ v: i + 1, cls: 'pos-cell' }, { v: p.name, html: k.playerLink(id, p.name, S) + (p.qualified === false ? ' <span class="gq-tag">small sample</span>' : '') }, { v: p.team || '', html: k.teamChip(p.team, S) }, { v: p.pos, html: k.esc(p.pos || '') },
        { v: p.games, html: k.int(p.games) }, { v: k.sampleOf(p, sk[0]), html: k.int(k.sampleOf(p, sk[0])) }, { v: v, html: '<strong>' + k.fmt(m, v) + '</strong>' }, { v: v, html: bar(v) }, { v: (p.pct || {})[m.key], html: k.pill((p.pct || {})[m.key]) }] }; }), { compact: true, sticky: true })
    : k.muted('Nobody with this metric matches.'));
  k.sortable(k.$('ld-table'));
  k.set('ld-sub', (S0.dir === 'worst' ? 'Bottom ' : 'Top ') + Math.min(S0.n, total) + ' of ' + total + ' ' + (k.GROUP_NAME[S0.group] || '').toLowerCase() + ' · ' + S);
  const q = (cat.qualification || {})[S0.group];
  k.set('ld-note', '<strong>' + k.esc(m.label) + '</strong>: ' + k.esc(m.desc || '') + (k.isNum(m.stabilises_at) ? ' Stabilises at about ' + k.int(m.stabilises_at) + ' ' + k.esc(sk[1].toLowerCase()) + '.' : '') +
    (q ? ' Qualified: ' + k.esc(q) + '.' : '') + ' Percentiles are against qualified ' + k.esc((k.GROUP_NAME[S0.group] || '').toLowerCase()) + ' after shrinking towards the group mean. ' + k.glossLink(m.key, 'Glossary →') + ' · <a href="' + k.withQ('#/lab', S, { g: S0.group, x: m.key }) + '">In the lab →</a>');
}

/* leaders.json when the catalogue is missing: {metric: [[pid, value]]} or {"boards": {...}}. */
function fallback(el, S, raw) {
  const k = K();
  return k.loadY(S, 'leaders.json').then(d => {
    if (!k.alive(el)) return;
    const B = d && d.ok !== false ? (d.boards || d.leaders || d) : null;
    const keys = B ? Object.keys(B).filter(x => Array.isArray(B[x]) && B[x].length) : [];
    if (!keys.length) { el.innerHTML = k.card('Leaders', '', k.notBuilt('The ' + S + ' player catalogue', raw)); return; }
    el.innerHTML = k.card('Leaders', S, '<div class="gq-glance">' + keys.map(x => '<div class="gq-mini"><div class="gq-mini-h">' + k.esc(k.titleCase(x)) + '</div>' +
      B[x].slice(0, 10).map((r, i) => '<div class="gq-mini-r"><span class="gq-mini-n">' + (i + 1) + '</span>' + k.playerLink(String(r[0]), null, S) + '<span class="gq-mini-v">' + k.fmtV(r[1]) + '</span></div>').join('') + '</div>').join('') + '</div>');
  });
}

if (typeof GI.route === 'function') { try { GI.route('leaders', render); } catch (e) { /* bound */ } }
})(window.GI || (window.GI = {}));
