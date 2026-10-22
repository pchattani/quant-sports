/* The Quant Gridiron — Players (#/players?g=QB|RB|WR|TE|K|P|DEF): the season catalogue by position group, on Design
 * System 2.0. A chart of the group's headline metric (top 15), then a leaderboard: the group's metric set as heat cells
 * on the cold-to-hot percentile scale against the player's peer group (QB, RB, WR/TE, DL and outside rushers, LB, DB,
 * K, P), search, team and position filters, a sample floor (qualified only by default) and extra metrics on demand. Also exports GI.cat (catalogue helpers) for leaders and the lab.
 * Reads <S>/players.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum, first = GI.first;
const ST = { group: 'QB', q: '', team: '', pos: '', floor: null, qual: true, extra: [], season: null };

/* players.json -> {cat, by: {group: [ids]}} */
function prepare(raw) {
  const cat = GI.catOf(raw);
  if (!cat) return null;
  const P = cat.players, by = {};
  Object.keys(P).forEach(id => { const g = GI.groupOf(P[id].pos, P[id].group); (by[g] = by[g] || []).push(id); });
  return { cat: cat, P: P, by: by };
}
GI.cat = { prepare: prepare };

GI.route('players', function (el, params) {
  const S = Number(params.season);
  const qy = params.query || {};
  if (qy.g && GI.GROUPS.indexOf(String(qy.g).toUpperCase()) >= 0) ST.group = String(qy.g).toUpperCase();
  return GI.load(GI.ypath('players.json', S)).then(raw => {
    if (!el.isConnected) return;
    const head = GI.pageHead('Players · ' + S, 'Player catalogue', 'Every player of the season by position group; each cell is coloured by his percentile against qualified players in his peer group (100 = best). Search the whole league with <kbd>/</kbd>.') + GI.sectionNav('players', 'players');
    const X = prepare(raw);
    if (!X) { el.innerHTML = head + GI.notBuilt('The ' + S + ' player catalogue', raw); return; }
    const P = X.P, by = X.by, cat = X.cat;
    if (ST.season !== S) { ST.season = S; ST.floor = null; ST.team = ''; ST.pos = ''; }
    if (!(by[ST.group] || []).length) ST.group = GI.GROUPS.find(g => (by[g] || []).length) || 'QB';
    el.innerHTML = head +
      '<div class="gi-toolbar">' + GI.seg('cat-group', GI.GROUPS.map(g => [g, g, !(by[g] || []).length]), ST.group, 'Position group') + '</div>' +
      GI.card('<span id="cat-ct"></span>', '<span id="cat-cs"></span>', GI.chartBox('cat-chart', 380, 'Top of the group'), { span: 12 }) +
      GI.card('', '', '<div class="gi-toolbar" style="margin-bottom:12px">' +
        GI.field('Search', '<input id="cat-q" class="qk-input" type="search" placeholder="Name or team">') +
        GI.field('Team', '<select id="cat-team" class="qk-select"></select>') + GI.field('Position', '<select id="cat-pos" class="qk-select"></select>') +
        GI.field('Add a metric', '<select id="cat-extra" class="qk-select"></select>') +
        '<label class="gi-field"><span>Min <span id="cat-floor-u"></span> <b id="cat-floor-v"></b></span><input id="cat-floor" type="range" min="0" max="700" step="1"></label>' +
        '<label class="gi-check"><input id="cat-qual" type="checkbox"' + (ST.qual ? ' checked' : '') + '> qualified only</label></div>' +
        '<div class="gi-chips-row" id="cat-chips"></div><div id="cat-table"></div><p class="gi-cap" id="cat-note"></p>');
    const $ = id => document.getElementById(id);
    let ctx = null;
    const setup = () => {
      const g = ST.group, ids = by[g] || [];
      const metrics = GI.metricsFor(cat, g), meta = GI.metaOf(metrics);
      const sub = {}; ids.forEach(id => { sub[id] = P[id]; });
      const sk = GI.sampleKey(sub, g);
      const maxN = Math.max.apply(null, ids.map(id => GI.sampleOf(P[id], sk[0])).concat([10]));
      $('cat-floor').max = String(Math.ceil(maxN)); $('cat-floor').step = maxN > 200 ? '5' : '1';
      $('cat-floor-u').textContent = sk[1].toLowerCase();
      const floorDef = [((cat.floors || {})[g]), cat.floor].find(isNum);
      if (ST.floor === null || ST.floor > maxN) ST.floor = isNum(floorDef) ? Math.min(floorDef, maxN) : 0;
      $('cat-floor').value = ST.floor; $('cat-floor-v').textContent = ST.floor;
      const teams = Array.from(new Set(ids.map(id => P[id].team).filter(Boolean))).sort();
      $('cat-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + esc(t + ' · ' + GI.teamName(t)) + '</option>').join('');
      const pos = {};
      ids.forEach(id => { const x = P[id].pos; if (x) pos[x] = (pos[x] || 0) + 1; });
      $('cat-pos').innerHTML = '<option value="">All positions</option>' + Object.keys(pos).sort().map(x => '<option value="' + esc(x) + '"' + (x === ST.pos ? ' selected' : '') + '>' + esc(x) + ' (' + pos[x] + ')</option>').join('');
      $('cat-extra').innerHTML = '<option value="">—</option>' + GI.metricGroups(metrics).map(gr => '<optgroup label="' + esc(gr.name) + '">' + gr.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      ST.extra = ST.extra.filter(x => meta[x]);
      ctx = { g: g, ids: ids, metrics: metrics, meta: meta, sk: sk, heads: [].concat.apply([], GI.playerSet(g, metrics, 7).map(x => x[1])).map(k => meta[k]).filter(Boolean) };
    };
    const draw = () => {
      const g = ctx.g, q = GI.fold(ST.q.trim()), sk = ctx.sk[0];
      const extras = ST.extra.map(x => ctx.meta[x]).filter(Boolean);
      const cols = ctx.heads.concat(extras.filter(m => ctx.heads.indexOf(m) < 0));
      const ids = ctx.ids.filter(id => { const p = P[id];
        return GI.sampleOf(p, sk) >= ST.floor && (!ST.qual || p.qualified !== false) && (!ST.team || String(p.team) === ST.team) && (!ST.pos || p.pos === ST.pos) &&
          (!q || GI.fold(String(p.name || GI.playerName(id)) + ' ' + (p.team || '') + ' ' + GI.teamName(p.team)).indexOf(q) >= 0); });
      const m0 = ctx.heads[0] || {};
      ids.sort((a, b) => { const va = (P[a].values || {})[m0.key], vb = (P[b].values || {})[m0.key]; const d = (isNum(vb) ? vb : -1e9) - (isNum(va) ? va : -1e9); return m0.lower ? -d : d; });
      const rows = ids.slice(0, 400).map(id => { const p = P[id], pc = GI.peerPct(p, g);
        const o = { id: id, name: p.name || GI.playerName(id), team: p.team, sub: GI.posLabel(p.pos || '') + ' · ' + GI.teamAbbr(p.team) + (p.qualified === false ? ' · small sample' : ''), age: isNum(p.age) ? Math.round(p.age) : null, games: first(p.games, p.g), n: GI.sampleOf(p, sk) };
        cols.forEach(m => { o['v_' + m.key] = (p.values || {})[m.key]; o['p_' + m.key] = isNum(pc[m.key]) ? pc[m.key] : null; });
        return o; });
      const tbl = $('cat-table');
      if (rows.length) QK.leaderboard(tbl, { dense: true, rank: true, maxHeight: 720, rowHref: r => GI.playerHref(r.id, S), sort: { key: 'p_' + (m0.key || ''), dir: 'desc' },
        columns: [{ key: 'name', label: GI.titleCase(GI.GROUP_ONE[g] || 'player'), type: 'entity', sub: 'sub', mark: r => ({ name: GI.teamName(r.team), abbr: GI.teamAbbr(r.team), colour: GI.teamInfo(r.team).colour }), href: r => GI.playerHref(r.id, S) },
          { key: 'age', label: 'Age', num: true }, { key: 'games', label: 'G', num: true }, { key: 'n', label: ctx.sk[1], num: true }]
          .concat(cols.map(m => ({ key: 'p_' + m.key, label: GI.shortLabel(m.label) + (m.lower ? ' ↓' : ''), type: 'pctl', pctl: 'p_' + m.key, fmt: (v, r) => GI.fmtVal(r['v_' + m.key], m.fmt),
            tip: GI.copyText(m.desc || m.label) + (isNum(m.stabilises_at) ? ' · stabilises at about ' + GI.int(m.stabilises_at) : '') + ' · sorted by percentile' }))),
        rows: rows });
      else GI.set('cat-table', GI.muted('No ' + (GI.GROUP_ONE[g] || 'player') + ' matches these filters.'));
      GI.set('cat-chips', extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="qk-chip" aria-pressed="true" data-rm="' + esc(m.key) + '">' + esc(m.label) + ' ×</button>').join(' ') : '');
      GI.set('cat-note', ids.length + ' of ' + ctx.ids.length + ' ' + esc((GI.GROUP_NAME[g] || g).toLowerCase()) + (ids.length > 400 ? ' (first 400 shown)' : '') + '. Peers: ' + esc(g === 'DEF' ? 'each defender against his own line (DL and outside rushers, linebackers or defensive backs)' : GI.peerOf({}, g).name.replace(/^NFL /, '')) + ', qualified (' + esc((cat.qualification || {})[g] || 'the sample floor') + '). Rates are shrunk towards the group mean by their stabilisation point before ranking; ↓ metrics are flipped so a high percentile is always good. ' +
        'Every metric is on each player page, the <a href="' + GI.ghref('leaders', S, { g: g }) + '">leaders</a> and the <a href="' + GI.ghref('lab', S, { g: g }) + '">lab</a>.' +
        (g === 'DEF' ? ' Defenders are rated on what the public data records (pass rush, tackles, takeaways); there is no in-season coverage charting.' : ''));
      GI.set('cat-ct', esc(m0.label || 'Top of the group') + (m0.lower ? ' (lower is better)' : ''));
      GI.set('cat-cs', 'Top 15 ' + esc((GI.GROUP_NAME[g] || g).toLowerCase()) + ' on the current filters · bars coloured by percentile against their peers');
      const top = ids.filter(id => isNum((P[id].values || {})[m0.key])).slice(0, 15);
      if (top.length) GI.ch.bar('cat-chart', { cats: top.map(id => (P[id].name || GI.playerName(id)) + ' · ' + GI.teamAbbr(P[id].team)), series: [{ name: m0.label, data: top.map(id => P[id].values[m0.key]) }], horizontal: true, labels: true,
        colors: top.map(id => QK.pctHex(GI.peerPct(P[id], g)[m0.key])), hrefs: top.map(id => GI.playerHref(id, S)), fmt: v => GI.fmtVal(v, m0.fmt), labelWidth: 170, valName: m0.label, catName: 'Player' });
      else GI.ch.none('cat-chart', 'Nobody on these filters has this metric.');
      try { history.replaceState(null, '', GI.ghref('players', S, { g: g })); } catch (e) { /* ok */ }
    };
    setup();
    $('cat-q').value = ST.q;
    let t = null;
    $('cat-q').addEventListener('input', e => { ST.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); });
    $('cat-team').addEventListener('change', e => { ST.team = e.target.value; draw(); });
    $('cat-pos').addEventListener('change', e => { ST.pos = e.target.value; draw(); });
    $('cat-qual').addEventListener('change', e => { ST.qual = e.target.checked; draw(); });
    $('cat-floor').addEventListener('input', e => { ST.floor = Number(e.target.value); $('cat-floor-v').textContent = ST.floor; });
    $('cat-floor').addEventListener('change', draw);
    $('cat-extra').addEventListener('change', e => { const x = e.target.value; if (x && ST.extra.indexOf(x) < 0) ST.extra.push(x); e.target.value = ''; draw(); });
    $('cat-chips').addEventListener('click', ev => { const b = ev.target.closest('[data-rm]'); if (b) { ST.extra = ST.extra.filter(x => x !== b.dataset.rm); draw(); } });
    GI.wireSeg(el, 'cat-group', v => { ST.group = v; ST.floor = null; ST.team = ''; ST.pos = ''; ST.extra = []; setup(); draw(); });
    draw();
  });
});

})(window.GI);
