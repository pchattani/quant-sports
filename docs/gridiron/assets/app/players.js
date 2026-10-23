/* The Quant Gridiron — Players (#/players?g=QB|RB|WR|TE|ED|IDL|LB|CB|S|K|P): the season catalogue by comparison group, on
 * Design System 2.0 and the metrics spec (spec.js: docs/METRICS_SPEC.md). A chart of the group's first headline metric
 * (top 15), then a leaderboard: the group's headline set as heat cells on the cold-to-hot percentile scale against the
 * group's qualified players, style metrics uncoloured, search, team and position filters, a sample floor (qualified only
 * by default), extra catalogue metrics on demand and, this season, the chance of leaving (Who moves next).
 * Also exports GI.cat (catalogue helpers) for leaders and the lab. Reads <S>/players.json and <S>/value.json (value per
 * game and the defensive roles). */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum, first = GI.first;
const ST = { group: 'qb', q: '', team: '', pos: '', floor: null, qual: true, extra: [], season: null };
const MV = { map: null, d: null };
const CORE = { qb: 'QB', rb: 'RB', wr: 'WR', te: 'TE', k: 'K', p: 'P', edge: 'DEF', idl: 'DEF', lb: 'DEF', cb: 'DEF', s: 'DEF' };

/* players.json -> {cat, by: {group: [ids]}} (the payload's own groups, for the lab and the leaders' fallbacks) */
function prepare(raw) {
  const cat = GI.catOf(raw);
  if (!cat) return null;
  const P = cat.players, by = {};
  Object.keys(P).forEach(id => { const g = GI.groupOf(P[id].pos, P[id].group); (by[g] = by[g] || []).push(id); });
  return { cat: cat, P: P, by: by };
}
/* A query's group: a spec code (QB, ED, IDL ...) or id, or the old DEF (outside pass rushers first). */
function groupFromQuery(x) {
  const k = String(x || '').toUpperCase();
  if (!k) return null;
  if (k === 'DEF') return 'edge';
  const g = GI.SP.PLAYER.find(z => z.code === k || z.id.toUpperCase() === k);
  return g ? g.id : null;
}
GI.cat = { prepare: prepare, groupFromQuery: groupFromQuery, CORE: CORE };

GI.route('players', function (el, params) {
  const S = Number(params.season);
  const qy = params.query || {};
  if (groupFromQuery(qy.g)) ST.group = groupFromQuery(qy.g);
  return GI.loadAll([GI.ypath('players.json', S), GI.ypath('value.json', S)]).then(res => {
    if (!el.isConnected) return;
    const raw = res[0];
    const head = GI.pageHead('Players · ' + S, 'Player catalogue', 'Every player of the season by comparison group; each cell is coloured by the player\'s percentile among the qualified players of the same group (100 = best). Search the whole league with <kbd>/</kbd>.') + GI.sectionNav('players', 'players') + QK.note('<b>A percentile</b> ranks a player against others in the same role this season: 90th means better than 90 in 100 qualified peers. Outside pass rushers, interior linemen, linebackers, corners and safeties each have their own pool.');
    const X = prepare(raw);
    if (!X) { el.innerHTML = head + GI.notBuilt('The ' + S + ' player catalogue', raw); return; }
    const P = X.P, cat = X.cat;
    const cx = GI.SP.ctx(cat, GI.ok(res[1]) ? res[1] : null);
    if (ST.season !== S) { ST.season = S; ST.floor = null; ST.team = ''; ST.pos = ''; }
    const G = GI.SP.PLAYER;
    if (!GI.SP.members(cx, ST.group).length) ST.group = (G.find(g => GI.SP.members(cx, g.id).length) || G[0]).id;
    el.innerHTML = head +
      '<div class="gi-toolbar">' + GI.seg('cat-group', G.map(g => [g.id, g.code, !GI.SP.members(cx, g.id).length]), ST.group, 'Comparison group') + '</div>' +
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
      const g = GI.SP.BY[ST.group], core = CORE[g.id], ids = GI.SP.members(cx, g.id);
      const metrics = GI.metricsFor(cat, core), meta = GI.metaOf(metrics);
      const sub = {}; ids.forEach(id => { sub[id] = P[id]; });
      const sk = GI.sampleKey(sub, core);
      const maxN = Math.max.apply(null, ids.map(id => GI.sampleOf(P[id], sk[0])).concat([10]));
      $('cat-floor').max = String(Math.ceil(maxN)); $('cat-floor').step = maxN > 200 ? '5' : '1';
      $('cat-floor-u').textContent = sk[1].toLowerCase();
      if (ST.floor === null || ST.floor > maxN) ST.floor = 0;
      $('cat-floor').value = ST.floor; $('cat-floor-v').textContent = ST.floor;
      const teams = Array.from(new Set(ids.map(id => P[id].team).filter(Boolean))).sort();
      $('cat-team').innerHTML = '<option value="">All teams</option>' + teams.map(t => '<option value="' + esc(t) + '"' + (t === ST.team ? ' selected' : '') + '>' + esc(t + ' · ' + GI.teamName(t)) + '</option>').join('');
      const pos = {};
      ids.forEach(id => { const x = P[id].pos; if (x) pos[x] = (pos[x] || 0) + 1; });
      $('cat-pos').innerHTML = '<option value="">All positions</option>' + Object.keys(pos).sort().map(x => '<option value="' + esc(x) + '"' + (x === ST.pos ? ' selected' : '') + '>' + esc(GI.posLabel(x)) + ' (' + pos[x] + ')</option>').join('');
      const setIds = g.m.map(m => m[0]);
      $('cat-extra').innerHTML = '<option value="">—</option>' + GI.metricGroups(metrics.filter(m => setIds.indexOf(m.key) < 0)).map(gr => '<optgroup label="' + esc(gr.name) + '">' + gr.items.map(m => '<option value="' + esc(m.key) + '">' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>').join('');
      ST.extra = ST.extra.filter(x => meta[x]);
      ctx = { g: g, core: core, ids: ids, meta: meta, sk: sk };
    };
    const draw = () => {
      const g = ctx.g, q = GI.fold(ST.q.trim()), sk = ctx.sk[0];
      const extras = ST.extra.map(x => ctx.meta[x]).filter(Boolean);
      const ids = ctx.ids.filter(id => { const p = P[id];
        return GI.sampleOf(p, sk) >= ST.floor && (!ST.qual || p.qualified !== false) && (!ST.team || String(p.team) === ST.team) && (!ST.pos || p.pos === ST.pos) &&
          (!q || GI.fold(String(p.name || GI.playerName(id)) + ' ' + (p.team || '') + ' ' + GI.teamName(p.team)).indexOf(q) >= 0); });
      const m0 = GI.SP.headline(g)[0];
      const v0 = id => GI.SP.value(P[id], id, m0, cx);
      ids.sort((a, b) => { const va = v0(a), vb = v0(b); const d = (isNum(vb) ? vb : -1e9) - (isNum(va) ? va : -1e9); return m0[3] ? -d : d; });
      const mvOn = MV.map && S === GI.currentSeason();
      const rows = ids.slice(0, 400).map(id => { const p = P[id];
        const o = { id: id, name: p.name || GI.playerName(id), team: p.team, sub: GI.posLabel(p.pos || '') + ' · ' + GI.teamAbbr(p.team) + (p.qualified === false ? ' · below the minimum' : ''), age: isNum(p.age) ? Math.round(p.age) : null, games: first(p.games, p.g), n: GI.sampleOf(p, sk) };
        g.m.forEach(m => { o['v_' + m[0]] = GI.SP.value(p, id, m, cx); o['p_' + m[0]] = GI.SP.pct(p, id, g, m, cx); if (m[4]) o['s_' + m[0]] = GI.SP.pct(p, id, g, [m[0], m[1], m[2], 0, 0, m[5], m[6]], cx); });
        extras.forEach(m => { o['x_' + m.key] = (p.values || {})[m.key]; });
        if (mvOn) { const mr = MV.map[id]; o.mvRow = mr || null; o.mv = mr && isNum(mr.p_next) ? mr.p_next : null; }
        return o; });
      const tbl = $('cat-table');
      if (rows.length) QK.leaderboard(tbl, { dense: true, rank: true, maxHeight: 720, rowHref: r => GI.playerHref(r.id, S), sort: { key: 'p_' + m0[0], dir: 'desc' },
        columns: [{ key: 'name', label: 'Player', type: 'entity', sub: 'sub', mark: r => ({ name: GI.teamName(r.team), abbr: GI.teamAbbr(r.team), colour: GI.teamInfo(r.team).colour }), href: r => GI.playerHref(r.id, S) },
          { key: 'age', label: 'Age', num: true }, { key: 'games', label: 'G', num: true }, { key: 'n', label: ctx.sk[1], num: true }]
          .concat(g.m.map(m => (m[4] ? { key: 'v_' + m[0], label: GI.shortLabel(m[1]), type: 'pctl', pctl: 's_' + m[0], style: true, fmt: v => GI.SP.fmt(m, v, cx), tip: m[5] + ' (style: no better or worse)' }
            : { key: 'p_' + m[0], label: GI.shortLabel(m[1]) + (m[3] ? ' ↓' : ''), type: 'pctl', pctl: 'p_' + m[0], fmt: (v, r) => GI.SP.fmt(m, r['v_' + m[0]], cx), tip: m[5] + ' · sorted by percentile' })))
          .concat(extras.map(m => ({ key: 'x_' + m.key, label: GI.shortLabel(m.label) + (m.lower ? ' ↓' : ''), num: true, fmt: v => GI.fmtVal(v, m.fmt), tip: GI.copyText(m.desc || m.label) })))
          .concat(mvOn ? [{ key: 'mv', label: 'Chance of leaving', num: true, fmt: (v, r) => (r.mvRow ? GI.MV.typeBar(r.mvRow, MV.d) : '—'), tip: 'Our chance the player is not with this team at ' + (((MV.d || {}).horizons || {}).next || 'next season') + ' (Who moves next)' }] : []),
        rows: rows });
      else GI.set('cat-table', GI.muted('No player matches these filters.'));
      GI.set('cat-chips', extras.length ? 'Added: ' + extras.map(m => '<button type="button" class="qk-chip" aria-pressed="true" data-rm="' + esc(m.key) + '">' + esc(m.label) + ' ×</button>').join(' ') : '');
      GI.set('cat-note', ids.length + ' of ' + ctx.ids.length + ' ' + esc(g.name.toLowerCase()) + (ids.length > 400 ? ' (first 400 shown)' : '') + '. Peers: ' + esc(g.peer.replace(/^NFL /, '')) + ', qualified (' + esc(GI.SP.minLine(g)) + '); ↓ metrics are flipped so a high percentile is always good, and style metrics carry no colour. ' +
        (GI.SP.NOTE[g.id] ? esc(GI.SP.NOTE[g.id]) + ' ' : '') + 'The metric set comes from our metrics study; every other metric is on each player page, the <a href="' + GI.ghref('leaders', S, { g: g.code }) + '">leaders</a> and the <a href="' + GI.ghref('lab', S, { g: ctx.core }) + '">lab</a>.');
      GI.set('cat-ct', esc(m0[1]) + (m0[3] ? ' (lower is better)' : ''));
      GI.set('cat-cs', 'Top 15 ' + esc(g.name.toLowerCase()) + ' on the current filters · bars coloured by percentile against their peers');
      const top = ids.filter(id => isNum(v0(id))).slice(0, 15);
      if (top.length) GI.ch.bar('cat-chart', { cats: top.map(id => (P[id].name || GI.playerName(id)) + ' · ' + GI.teamAbbr(P[id].team)), series: [{ name: m0[1], data: top.map(v0) }], horizontal: true, labels: true,
        colors: top.map(id => QK.pctHex(GI.SP.pct(P[id], id, g, m0, cx))), hrefs: top.map(id => GI.playerHref(id, S)), fmt: v => GI.SP.fmt(m0, v, cx), labelWidth: 170, valName: m0[1], catName: 'Player' });
      else GI.ch.none('cat-chart', 'Nobody on these filters has this metric.');
      try { history.replaceState(null, '', GI.ghref('players', S, { g: g.code })); } catch (e) { /* ok */ }
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
    if (S === GI.currentSeason() && GI.MV && !MV.map) GI.MV.load().then(md => { if (!md) return; MV.d = md; MV.map = GI.MV.byPid(md); if (el.isConnected) draw(); });
  });
});

})(window.GI);
