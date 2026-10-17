/* The Quant Gridiron — Compare (#/compare/<a>/<b>), in the Lab: two players or two teams (t:KC).
 * Who wins each shared metric by percentile, the biggest gaps each way, a radar of the headline metrics,
 * a percentile butterfly of every shared metric, and the full list with values. With one side picked
 * the other defaults to the most similar. Reads <S>/players.json and <S>/teams.json. Exports GI.picker. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
let MODE = 'player';
const TEAM_HEAD = ['rating', 'off_rating', 'def_rating', 'off_epa', 'def_epa', 'off_pass_epa', 'off_rush_epa', 'def_pass_epa', 'def_rush_epa', 'st_epa_g', 'go_rate_rec', 'fd_wp_lost'];

/* A typeahead. host: element; o {items: {id: {name, sub}}, value, label, placeholder, min, onPick(id)} */
GI.picker = function (host, o) {
  host.classList.add('gi-picker');
  host.innerHTML = '<input type="search" class="qk-input" autocomplete="off" spellcheck="false" aria-label="' + esc(o.placeholder || 'Search') + '" placeholder="' + esc(o.placeholder || 'Type a name…') + '"><div class="gi-pick-list" role="listbox"></div>';
  const input = host.querySelector('input'), list = host.querySelector('.gi-pick-list');
  if (o.value) input.value = o.label || '';
  const items = Object.keys(o.items).map(id => ({ id: id, n: o.items[id].name || id, s: o.items[id].sub || '', f: GI.fold((o.items[id].name || id) + ' ' + (o.items[id].sub || '')) })).sort((a, b) => a.n.localeCompare(b.n));
  const close = () => { list.style.display = 'none'; list.innerHTML = ''; };
  const show = () => {
    const q = GI.fold(input.value.trim());
    if (q.length < (o.min === undefined ? 2 : o.min)) { close(); return; }
    const words = q.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.f.indexOf(w) >= 0)).slice(0, 12);
    list.innerHTML = hits.length ? hits.map(h => '<button type="button" role="option" data-id="' + esc(h.id) + '"><span>' + esc(h.n) + '</span><span class="gi-pick-sub">' + esc(h.s) + '</span></button>').join('') : '<div class="gi-pick-none">No match.</div>';
    list.style.display = 'block';
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { input.select(); });
  input.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); if (ev.key === 'Enter') { const b = list.querySelector('button[data-id]'); if (b) { ev.preventDefault(); b.click(); } } });
  list.addEventListener('click', ev => { const b = ev.target.closest('button[data-id]'); if (!b) return; input.value = o.items[b.dataset.id].name; close(); if (o.onPick) o.onPick(b.dataset.id); });
  const outside = ev => { if (!host.contains(ev.target)) close(); };
  document.addEventListener('click', outside);
  GI.onLeave(() => document.removeEventListener('click', outside));
};

function teamId(s) { const m = /^t:?([A-Za-z]{2,3})$/.exec(String(s || '')); return m ? m[1].toUpperCase() : (/^[A-Z]{2,3}$/.test(String(s || '')) ? String(s) : null); }
function entity(id, cat, tc) {
  const t = teamId(id);
  if (t && tc && tc.teams[t]) { const x = tc.teams[t]; return { kind: 'team', id: t, name: GI.teamName(t), values: x.values || {}, pct: x.pct || {}, rank: x.rank || {}, team: t, rec: x.record || {} }; }
  const p = cat && cat.players[String(id)];
  if (!p) return null;
  return { kind: 'player', id: String(id), name: p.name || GI.playerName(id), values: p.values || {}, pct: p.pct || {}, rank: {}, team: p.team, pos: p.pos, group: GI.groupOf(p.pos, p.group), age: p.age, games: p.games, qualified: p.qualified };
}
function nearest(A, cat, tc) {
  let best = null, bd = 1e9;
  if (A.kind === 'team') {
    Object.keys(tc.teams).forEach(t => { if (t === A.id) return; const p = tc.teams[t].pct || {}; let d = 0, n = 0; TEAM_HEAD.forEach(x => { if (isNum(A.pct[x]) && isNum(p[x])) { d += (A.pct[x] - p[x]) * (A.pct[x] - p[x]); n++; } }); if (n >= 3 && d / n < bd) { bd = d / n; best = t; } });
    return best;
  }
  const heads = GI.headline(GI.metricsFor(cat, A.group), GI.PREFS[A.group] || [], 10);
  Object.keys(cat.players).forEach(id => {
    const p = cat.players[id];
    if (id === A.id || p.qualified === false || GI.groupOf(p.pos, p.group) !== A.group) return;
    let d = 0, n = 0;
    heads.forEach(m => { const x = A.pct[m.key], y = (p.pct || {})[m.key]; if (isNum(x) && isNum(y)) { d += (x - y) * (x - y); n++; } });
    if (n >= 3 && d / n < bd) { bd = d / n; best = id; }
  });
  return best;
}
function idCard(S, X, side) {
  const v = X.values;
  let facts;
  if (X.kind === 'player') facts = [['Team', X.team ? GI.teamChip(X.team, S) : '—'], ['Pos', esc(X.pos || '—')], ['Age', isNum(X.age) ? GI.num(X.age, 0) : '—'], ['Games', GI.int(X.games)]];
  else { const rc = X.rec || {}; facts = [['W-L', GI.record(rc.w, rc.l, rc.t)], ['Rating', GI.signed(v.rating, 1)], ['Off EPA', GI.signed(v.off_epa, 3)], ['Def EPA', GI.signed(v.def_epa, 3)]]; }
  const col = X.team ? GI.tc(X.team) : 'var(--accent)';
  return '<div class="qk-card gi-cmp-id" style="--tc:' + esc(col) + '"><div class="gi-toolbar">' + (X.kind === 'team' ? GI.mark(X.team, 'lg') : '<div class="qk-avatar" style="--tc:' + esc(col) + ';width:52px;height:52px;font-size:18px">' + esc(QK.fmt.initials(X.name)) + '</div>') +
    '<div><span class="qk-kicker" style="color:' + (side === 'a' ? 'var(--c-1)' : 'var(--c-2)') + '">' + (side === 'a' ? 'Blue' : 'Orange') + '</span><br><a class="gi-link" style="font-size:var(--fs-lg)" href="' + (X.kind === 'team' ? GI.teamHref(X.id, S) : GI.playerHref(X.id, S)) + '">' + esc(X.name) + '</a>' + (X.qualified === false ? ' <span class="gi-tag">small sample</span>' : '') + '</div></div>' +
    GI.kpis(facts.map(f => GI.kpi(f[0], f[1]))) + '</div>';
}

GI.route('compare', function (el, params) {
  const S = Number(params.season);
  const a0 = params.a || '', b0 = params.b || '';
  return GI.loadAll([GI.ypath('players.json', S), GI.ypath('teams.json', S)]).then(res => {
    if (!el.isConnected) return;
    const cat = GI.catOf(res[0]);
    const tc = GI.TM.of(res[1]);
    if (a0 || b0) MODE = teamId(a0 || b0) && tc && tc.teams[teamId(a0 || b0)] ? 'team' : 'player';
    let A = a0 ? entity(a0, cat, tc) : null, B = b0 ? entity(b0, cat, tc) : null;
    if (A && A.kind !== MODE) A = null;
    if (B && B.kind !== MODE) B = null;
    if (A && !B) { const n = nearest(A, cat, tc); if (n) B = entity(MODE === 'team' ? 't:' + n : n, cat, tc); }
    const src = MODE === 'team' ? tc : cat;
    const metrics = !A || !B ? [] : MODE === 'team' ? (tc.metrics || []) : GI.metricsFor(cat, A.group).filter(m => GI.metricsFor(cat, B.group).some(x => x.key === m.key));
    let h = GI.pageHead('Lab · ' + S, 'Compare', 'Two players (the metrics they share are compared) or two teams, by percentile.') + GI.sectionNav('lab', 'compare') +
      GI.card('', '', '<div class="gi-toolbar">' + GI.seg('cmp-mode', [['player', 'Players'], ['team', 'Teams']], MODE, 'Compare') + '<div id="cmp-pa"></div><button type="button" class="qk-btn" id="cmp-swap" aria-label="Swap">⇄</button><div id="cmp-pb"></div></div>');
    if (!src) h += GI.notBuilt('The ' + (MODE === 'team' ? 'team' : 'player') + ' catalogue', MODE === 'team' ? res[1] : res[0]);
    else if (!A || !B) h += QK.empty('Pick ' + (A ? 'a second ' : 'two ') + (MODE === 'team' ? 'teams' : 'players'), (a0 && !A ? a0 + ' is not in the ' + S + ' catalogue. ' : '') + 'Type a name above.');
    else {
      const ms = metrics.filter(m => isNum(A.pct[m.key]) && isNum(B.pct[m.key]));
      let wa = 0, wb = 0;
      const gaps = ms.map(m => { const d = A.pct[m.key] - B.pct[m.key]; if (d > 0.5) wa++; else if (d < -0.5) wb++; return { m: m, d: d }; });
      const tot = Math.max(1, wa + wb);
      const gl = list => list.map(g => '<b>' + esc(g.m.label) + '</b> (' + Math.round(Math.abs(g.d)) + ')').join(', ') || 'nothing by much';
      h += '<div class="gi-cmp-ids">' + idCard(S, A, 'a') + idCard(S, B, 'b') + '</div>' +
        GI.card('', '', '<div class="gi-verdict"><div>' + esc(A.name) + ' is ahead on ' + gl(gaps.filter(g => g.d > 0).sort((x, y) => y.d - x.d).slice(0, 3)) + '.</div>' +
          '<div class="gi-verdict-mid"><div class="gi-verdict-score"><span class="a">' + wa + '</span><span>–</span><span class="b">' + wb + '</span></div>' + QK.probBar(wa / tot, null, wb / tot, { name: A.name }, { name: B.name }) + '<div class="qk-sub">metrics won by percentile, of ' + ms.length + '</div></div>' +
          '<div class="gi-verdict-side b">' + esc(B.name) + ' is ahead on ' + gl(gaps.filter(g => g.d < 0).sort((x, y) => x.d - y.d).slice(0, 3)) + '.</div></div>' +
          (A.kind === 'player' && A.group !== B.group ? '<p class="gi-cap">Different position groups: each percentile is against the player\'s own group.</p>' : '')) +
        GI.grid(GI.card('Profile', 'headline metrics as percentiles (100 = best)', GI.chartBox('cmp-radar', 420, 'Percentile radar'), { span: 5 }) +
          GI.card('Every shared metric', 'percentile, blue left and orange right', GI.chartBox('cmp-fly', Math.max(300, ms.length * 24 + 40), 'Percentile butterfly'), { span: 7 })) +
        GI.card('The numbers', '', '<div id="cmp-all"></div>', { flush: true });
    }
    el.innerHTML = h;
    const tag = x => (MODE === 'team' ? 't:' + x : x);
    const go = (a, b) => { location.hash = GI.compareHref(a ? tag(a) : '', b ? tag(b) : '') + GI.sq(S); };
    const items = {};
    if (MODE === 'team' && tc) Object.keys(tc.teams).forEach(t => { items[t] = { name: GI.teamName(t), sub: t }; });
    else if (cat) Object.keys(cat.players).forEach(id => { const p = cat.players[id]; items[id] = { name: p.name || GI.playerName(id), sub: [p.pos, p.team].filter(Boolean).join(' · ') }; });
    const pa = document.getElementById('cmp-pa'), pb = document.getElementById('cmp-pb');
    if (pa) GI.picker(pa, { items: items, value: A ? A.id : null, label: A ? A.name : '', placeholder: MODE === 'team' ? 'First team' : 'First player', min: MODE === 'team' ? 1 : 2, onPick: id => go(id, B ? B.id : '') });
    if (pb) GI.picker(pb, { items: items, value: B ? B.id : null, label: B ? B.name : '', placeholder: MODE === 'team' ? 'Second team' : 'Second player', min: MODE === 'team' ? 1 : 2, onPick: id => go(A ? A.id : '', id) });
    const sw = document.getElementById('cmp-swap');
    if (sw) sw.addEventListener('click', () => { if (A || B) go(B ? B.id : '', A ? A.id : ''); });
    GI.wireSeg(el, 'cmp-mode', v => { MODE = v; if (location.hash.replace(/[?].*$/, '') === '#/compare') GI.render(); else location.hash = '#/compare' + GI.sq(S); });
    if (!A || !B || !src) return;
    const heads = (A.kind === 'team' ? TEAM_HEAD.map(x => metrics.find(m => m.key === x)).filter(Boolean) : GI.headline(metrics, GI.PREFS[A.group] || [], 10)).filter(m => isNum(A.pct[m.key]) || isNum(B.pct[m.key])).slice(0, 10);
    GI.ch.radar('cmp-radar', [{ name: A.name, values: heads.map(m => A.pct[m.key]), colour: '#3987e5' }, { name: B.name, values: heads.map(m => B.pct[m.key]), colour: '#e8833a' }], { labels: heads.map(m => GI.shortLabel(m.label)) });
    const ms = metrics.filter(m => isNum(A.pct[m.key]) && isNum(B.pct[m.key]));
    GI.ch.mount('cmp-fly', T => {
      const cats = ms.map(m => m.label + (m.lower ? ' ↓' : ''));
      const ya = GI.ch.ax(T, { type: 'category', data: cats, split: false, inverse: true });
      ya.axisLabel.color = T.ink2; ya.axisLabel.width = 150; ya.axisLabel.overflow = 'truncate';
      return { grid: { left: 8, right: 16, top: 26, bottom: 8, containLabel: true }, legend: GI.ch.legend(T, { data: [A.name, B.name] }),
        xAxis: GI.ch.ax(T, { min: -100, max: 100, fmt: v => String(Math.abs(v)) }), yAxis: ya,
        tooltip: GI.ch.tip(T, { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: ps => { const m = ms[ps[0].dataIndex]; return GI.ch.thead(esc(m.label)) + GI.ch.trow(T.model, A.name, GI.fmtVal(A.values[m.key], m.fmt) + ' · ' + Math.round(A.pct[m.key]) + 'th') + GI.ch.trow(T.market, B.name, GI.fmtVal(B.values[m.key], m.fmt) + ' · ' + Math.round(B.pct[m.key]) + 'th'); } }),
        series: [{ type: 'bar', name: A.name, stack: 's', data: ms.map(m => -A.pct[m.key]), barMaxWidth: 12, itemStyle: { color: T.model, borderRadius: [3, 0, 0, 3] } },
          { type: 'bar', name: B.name, stack: 's', data: ms.map(m => B.pct[m.key]), barMaxWidth: 12, itemStyle: { color: T.market, borderRadius: [0, 3, 3, 0] } }] };
    }, 'Percentile butterfly');
    GI.set('cmp-all', GI.tableHTML([{ label: 'Group' }, { label: 'Metric' }, { label: A.name, align: 'right' }, { label: 'Pct', align: 'right' }, { label: B.name, align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Gap', align: 'right', title: 'Percentile points, blue minus orange' }],
      metrics.filter(m => isNum(A.values[m.key]) || isNum(B.values[m.key])).map(m => { const pa2 = A.pct[m.key], pb2 = B.pct[m.key], d = isNum(pa2) && isNum(pb2) ? pa2 - pb2 : null;
        return [m.group || '', { html: GI.glossLink(m.key, esc(m.label)) + (m.lower ? ' ↓' : ''), v: m.label }, { html: GI.fmtVal(A.values[m.key], m.fmt), v: A.values[m.key] }, { html: QK.pctlChip(pa2) || '—', v: pa2 }, { html: GI.fmtVal(B.values[m.key], m.fmt), v: B.values[m.key] }, { html: QK.pctlChip(pb2) || '—', v: pb2 }, { html: GI.deltaHTML(d, 0), v: d }]; }), { sticky: true, maxHeight: 600 }));
    GI.sortable(document.getElementById('cmp-all'));
  });
});

})(window.GI);
