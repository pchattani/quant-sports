/* The Quant Gridiron — Player value (#/value?pos=&team=), the first view of Value & Moves.
 * One currency: points (EPA) above a replacement-level player at the same position. Top 20 overall as a
 * chart, the best at each position, the leaderboard with filters and sample floors, and (current season)
 * projected multi-season value with its band, position scarcity and the draft-pick value curve.
 * Reads <S>/value.json and, for the current season, <S>/valuation.json. */
(function (GI) {
'use strict';

const QK = window.QK;
const esc = GI.esc, isNum = GI.isNum;
const ST = { pos: '', team: '', qual: true, sort: 'gvar', n: 50, q: '', season: null };
const PV = { pos: '', n: 50, sort: 'value' };
const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P'];
const WHY = { pass: ['Passing', 'pts'], rush: ['Rushing', 'pts'], rec: ['Receiving', 'pts'], epa_db: ['EPA/db', 'epa'], cpoe: ['CPOE', 'pp'], composite: ['Composite', 'int'], ryoe: ['RYOE/carry', '2'], ypc: ['Y/C', '2'],
  yacoe: ['YACOE', '2'], croe: ['CROE', 'pctpp'], target_share: ['Tgt share', 'pct'], fg_oe: ['FG OE', '2'], fg_50: ['50+ made', 'int'], fg_pct: ['FG%', 'pct'], net: ['Net', '1'], inside20: ['Inside 20', 'pct'], net_oe: ['Net OE', '2'],
  sacks: ['Sacks', '1'], qb_hits: ['QB hits', 'int'], tfl: ['TFL', 'int'], ff: ['FF', 'int'], pd: ['PD', 'int'], ints: ['INT', 'int'] };
function fmtWhy(v, f) {
  if (!isNum(v)) return null;
  const x = Number(v);
  return f === 'pts' ? GI.signed(x, 1) : f === 'epa' ? GI.signed(x, 3) : f === 'pp' ? GI.signed(x, 1) + ' pts' : f === 'pctpp' ? GI.signed(x * 100, 1) + ' pts' : f === 'pct' ? (x * 100).toFixed(1) + '%' : f === 'int' ? String(Math.round(x)) : f === '1' ? x.toFixed(1) : GI.signed(x, 2);
}
function whyText(why, keys, n) {
  const out = [];
  (keys || []).forEach((k, i) => { const f = WHY[k]; if (!f) return; const s = fmtWhy((why || [])[i], f[1]); if (s !== null) out.push(f[0] + ' ' + s); });
  return out.slice(0, n || 4).join(' · ');
}

GI.route('value', function (el, params) {
  const S = Number(params.season);
  const cur = S === GI.currentSeason();
  const qy = params.query || {};
  if (qy.pos && POS_ORDER.indexOf(String(qy.pos).toUpperCase()) >= 0) ST.pos = String(qy.pos).toUpperCase();
  if (qy.team) ST.team = String(qy.team).toUpperCase();
  return GI.loadAll([GI.ypath('value.json', S)].concat(cur ? [GI.ypath('valuation.json', S)] : [])).then(res => {
    if (!el.isConnected) return;
    const d = res[0], v = cur && GI.ok(res[1]) ? res[1] : null;
    const head = GI.pageHead('Value & Moves · ' + S, 'Player value', 'One currency for every position: points (EPA) above a replacement-level player at the same position.') + GI.sectionNav('value', 'value');
    if (ST.season !== S) { ST.season = S; if (!qy.team) ST.team = ''; }
    if (!GI.ok(d) || !d.rows) { el.innerHTML = head + GI.notBuilt('The ' + S + ' value table', d); return; }
    const rows = GI.colRows(d), by = {};
    rows.forEach(r => { by[r.pid] = r; });
    const notes = d.notes || {}, labels = d.labels || {};
    const qual = rows.filter(r => r.q).sort((a, b) => (b.gvar || 0) - (a.gvar || 0));
    el.innerHTML = head +
      GI.kpis([qual[0] ? GI.kpi('Most valuable', GI.playerLink(qual[0].pid, qual[0].name), GI.signed(qual[0].gvar, 1) + ' pts · ' + esc(qual[0].pos) + ' · ' + esc(qual[0].team || '')) : '',
        (() => { const nq = qual.filter(r => r.pos !== 'QB')[0]; return nq ? GI.kpi('Best non-QB', GI.playerLink(nq.pid, nq.name), GI.signed(nq.gvar, 1) + ' pts · ' + esc(nq.pos)) : ''; })(),
        (() => { const t = qual.filter(r => isNum(r.trend)).sort((a, b) => b.trend - a.trend)[0]; return t ? GI.kpi('Biggest riser', GI.playerLink(t.pid, t.name), GI.signed(t.trend, 2) + ' per game v last season') : ''; })(),
        GI.kpi('Players valued', GI.int(rows.length), GI.int(qual.length) + ' qualified')], 'gi-kpis-4') +
      GI.grid(GI.card('Top 20 this season', 'points above replacement so far · colour: team', GI.chartBox('gv-top', 560, 'Top 20 by value'), { span: 7 }) +
        GI.card('The currency', esc(notes.currency || ''), '<div class="gi-prose"><p><b>QB, RB, WR, TE</b>: Gridiron Value (EPA credited to the passer, receiver or rusher, adjusted for the opponent and the teammates on the play) above the position\'s replacement level. <b>K</b>: points over expected from our make-probability model. <b>P</b>: punting EPA over the average punt. <b>Defenders</b>: ' + esc(notes.defence || '') + '</p><p><b>Offensive line</b>: ' + esc(notes.ol || '') + '</p><p>Replacement level: the ' + Math.round(100 * (d.repl_q || 0.2)) + 'th-percentile rate among the position\'s regulars.</p></div>', { span: 5 })) +
      '<section class="qk-section"><div class="qk-section-head"><div><h2>Best at each position</h2><div class="qk-sub">Top five qualified players by value; hover for what drives it. Tap a position for its full table.</div></div></div><div class="qk-auto" style="--min:250px">' +
        POS_ORDER.map(pos => { const ids = ((d.best || {})[pos] || []).filter(id => by[id]).slice(0, 5);
          return GI.card('<button type="button" class="gi-linkbtn" data-gvpos="' + pos + '">' + esc(labels[pos] || pos) + ' →</button>', '', ids.length ? '<ol class="gi-ldl">' + ids.map(id => { const r = by[id]; return '<li title="' + esc(whyText(r.why, (d.why || {})[pos], 4)) + '">' + GI.mark(r.team) + GI.playerLink(id, { name: r.name, season: S }) + '<b class="gi-num">' + GI.signed(r.gvar, 1) + '</b></li>'; }).join('') + '</ol>' : GI.muted('No qualified player yet.')); }).join('') + '</div></section>' +
      GI.card('Leaderboard', '<span id="gv-sub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.field('Position', GI.select('gv-pos', [['', 'All']].concat(POS_ORDER.map(p => [p, labels[p] || p])), ST.pos, 'Position')) +
        GI.field('Team', GI.select('gv-team', [['', 'All teams']].concat(Array.from(new Set(rows.map(r => r.team).filter(Boolean))).sort().map(t => [t, t])), ST.team, 'Team')) +
        GI.field('Sort', GI.select('gv-sort', [['gvar', 'Season value'], ['gvar_pg', 'Value per game'], ['pct', 'Percentile'], ['trend', 'Trend']], ST.sort, 'Sort')) +
        GI.field('How many', GI.select('gv-n', [['25', '25'], ['50', '50'], ['100', '100'], ['9999', 'All']], String(ST.n), 'How many')) +
        GI.field('Find', '<input id="gv-q" class="qk-input" type="search" placeholder="Name">') + '<label class="gi-check"><input id="gv-qual" type="checkbox"' + (ST.qual ? ' checked' : '') + '> qualified only</label></div><div id="gv-table"></div>' +
        '<p class="gi-cap">Season value: points above replacement so far. Per game: per game played. Percentile: of value per game among qualified players at the position. Trend: Gridiron Value per game v last season. ' + esc(notes.trend || '') + '</p>') +
      (v ? '<div id="gv-proj"></div>' : '');
    const $ = id => document.getElementById(id);
    const top = qual.slice(0, 20);
    GI.ch.bar('gv-top', { cats: top.map(r => r.name + ' · ' + r.pos), series: [{ name: 'Value', data: top.map(r => r.gvar) }], horizontal: true, labels: true, colors: top.map(r => GI.teamColour(r.team)), hrefs: top.map(r => GI.playerHref(r.pid, S)), fmt: x => GI.signed(x, 1), labelWidth: 170 });
    $('gv-q').value = ST.q;
    const draw = () => {
      const q = GI.fold(ST.q.trim());
      let list = rows.filter(r => (!ST.pos || r.pos === ST.pos) && (!ST.team || r.team === ST.team) && (!ST.qual || r.q) && (!q || GI.fold(r.name).indexOf(q) >= 0));
      list.sort((a, b) => (isNum(b[ST.sort]) ? b[ST.sort] : -1e9) - (isNum(a[ST.sort]) ? a[ST.sort] : -1e9));
      const total = list.length;
      list = list.slice(0, ST.n);
      const sample = r => (r.pos === 'K' ? r.opp + ' FGA' : r.pos === 'P' ? r.opp + ' punts' : ['EDGE', 'DL', 'LB', 'CB', 'S'].indexOf(r.pos) >= 0 ? r.games + ' g' : GI.int(r.opp) + ' plays');
      GI.set('gv-table', list.length ? GI.tableHTML([{ label: '#', align: 'right', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'G', align: 'right' }, { label: 'Sample', align: 'right' },
        { label: 'Value', align: 'right' }, { label: 'Per game', align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Trend', align: 'right' }, { label: 'Why', sortable: false }],
        list.map((r, i) => ({ _href: GI.playerHref(r.pid, S), cells: [i + 1, { html: GI.playerLink(r.pid, { name: r.name, season: S }) + (r.q ? '' : ' <span class="gi-tag">small sample</span>'), v: r.name },
          { html: r.team ? GI.teamChip(r.team, S) : '<span class="qk-muted">unsigned</span>', v: r.team || '' }, { v: r.pos }, { html: GI.num(r.age, 0), v: r.age }, { v: r.games }, { html: esc(sample(r)), v: r.opp },
          { html: '<b>' + GI.signed(r.gvar, 1) + '</b>', v: r.gvar }, { html: GI.signed(r.gvar_pg, 2), v: r.gvar_pg }, { html: QK.pctlChip(r.pct) || '—', v: r.pct }, { html: GI.deltaHTML(r.trend, 2), v: r.trend },
          { html: '<span class="gi-play-desc">' + esc(whyText(r.why, (d.why || {})[r.pos], 3)) + '</span>' }] })), { sticky: true, maxHeight: 640 }) : GI.muted('No player matches.'));
      GI.sortable($('gv-table'));
      GI.set('gv-sub', (ST.pos ? esc(labels[ST.pos] || ST.pos) : 'All positions') + (ST.team ? ' · ' + ST.team : '') + ' · ' + Math.min(ST.n, total) + ' of ' + total + ' · ' + S);
    };
    [['gv-pos', 'pos'], ['gv-team', 'team'], ['gv-sort', 'sort']].forEach(x => $(x[0]).addEventListener('change', e => { ST[x[1]] = e.target.value; draw(); }));
    $('gv-n').addEventListener('change', e => { ST.n = Number(e.target.value); draw(); });
    $('gv-qual').addEventListener('change', e => { ST.qual = e.target.checked; draw(); });
    $('gv-q').addEventListener('input', e => { ST.q = e.target.value; draw(); });
    el.querySelectorAll('[data-gvpos]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); ST.pos = a.getAttribute('data-gvpos'); $('gv-pos').value = ST.pos; draw(); const t = $('gv-table'); if (t && t.scrollIntoView) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
    draw();
    if (!v) return;
    // projected value (valuation v2)
    const vr = GI.colRows(v), yrs = v.seasons || [];
    const sc = v.scarcity || {}, pc = v.pick_curve || {};
    GI.set('gv-proj', '<section class="qk-section"><div class="qk-section-head"><div><h2>Projected value</h2><div class="qk-sub">The rest of ' + yrs[0] + ' and the next three seasons: ageing and availability by position, discounted 10% a season. ' + esc((v.notes || {}).salary || '') + '</div></div></div>' +
      GI.grid(GI.card('Position scarcity', 'how far the top five sit above the last starter-quality player (next season)', GI.chartBox('gv-sc', 300, 'Position scarcity'), { span: 6 }) +
        GI.card('Draft-pick value curve', 'points over four seasons by pick · used by the trade ratings', pc.ok ? GI.chartBox('gv-pc', 300, 'Draft pick value curve') : GI.muted(esc(pc.reason || 'Not available.')), { span: 6 })) +
      GI.card('Projected leaderboard', '<span id="gv-psub"></span>', '<div class="gi-toolbar" style="margin-bottom:12px">' + GI.field('Position', GI.select('gv-ppos', [['', 'All']].concat(POS_ORDER.map(p => [p, p])), PV.pos, 'Position')) +
        GI.field('Sort', GI.select('gv-psort', [['value', 'Value'], ['wins', 'Wins'], ['lvl', 'Level now'], ['over_ms', 'v marginal starter'], ['age', 'Age']], PV.sort, 'Sort')) +
        GI.field('How many', GI.select('gv-pn', [['25', '25'], ['50', '50'], ['100', '100'], ['9999', 'All']], String(PV.n), 'How many')) + '</div><div id="gv-ptable"></div>' +
        '<p class="gi-cap">' + esc((v.notes || {}).value || '') + ' ' + esc((v.notes || {}).qb || '') + ' ' + esc((v.notes || {}).availability || '') + ' Wins = value × ' + GI.num(v.k_resp, 2) + ' × ' + GI.num(v.wins_per_point, 4) + ' wins per point of margin.</p>') + '</section>');
    const scP = Object.keys(sc).sort((a, b) => sc[b].index - sc[a].index);
    GI.ch.bar('gv-sc', { cats: scP, series: [{ name: 'Scarcity index', data: scP.map(p => sc[p].index) }], labels: true, fmt: x => GI.num(x, 1) });
    if (pc.ok && (pc.picks || []).length) GI.ch.lines('gv-pc', [{ name: 'Pick value', x: pc.picks.map((_, i) => i + 1), y: pc.picks, area: true }], { legend: false, xName: 'Pick', xLabel: x => 'Pick ' + x, yFmt: y => GI.num(y, 0) });
    const drawP = () => {
      let list = vr.filter(r => !PV.pos || r.pos === PV.pos);
      list.sort((a, b) => (isNum(b[PV.sort]) ? b[PV.sort] : -1e9) - (isNum(a[PV.sort]) ? a[PV.sort] : -1e9));
      const total = list.length;
      list = list.slice(0, PV.n);
      GI.set('gv-ptable', GI.tableHTML([{ label: '#', align: 'right', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Pos' }, { label: 'Age', align: 'right' }, { label: 'Level now', align: 'right', title: 'Current per-game value above replacement' },
        { label: 'Per game ' + yrs.slice(1).join(' / '), align: 'right' }, { label: 'Games', align: 'right', title: 'Expected games: rest of this season, then each season' }, { label: 'Value', align: 'right' }, { label: 'Band', align: 'right', title: '10th–90th percentile' }, { label: 'Wins', align: 'right' }, { label: 'v marginal starter', align: 'right' }],
        list.map((r, i) => ({ _href: GI.playerHref(r.pid), cells: [i + 1, { html: GI.playerLink(r.pid, r.name) + (r.status === 'RES' ? ' <span class="qk-badge">IR</span>' : '') + (r.status === 'FA' ? ' <span class="qk-badge">unsigned</span>' : ''), v: r.name },
          { html: r.team ? GI.teamChip(r.team) : '—', v: r.team || '' }, { v: r.pos }, { html: GI.num(r.age, 0), v: r.age }, { html: GI.signed(r.lvl, 2), v: r.lvl },
          { html: (r.proj || []).slice(1).map(x => GI.num(x, 2)).join(' / '), v: (r.proj || [])[1] }, { html: (r.games || []).map(x => GI.num(x, 0)).join(' / '), v: (r.games || [])[0] },
          { html: '<b>' + GI.num(r.value, 0) + '</b>', v: r.value }, { html: GI.num(r.lo, 0) + '–' + GI.num(r.hi, 0), v: r.lo }, { html: GI.num(r.wins, 2), v: r.wins }, { html: GI.signed(r.over_ms, 2), v: r.over_ms }] })), { sticky: true, maxHeight: 600 }));
      GI.sortable($('gv-ptable'));
      GI.set('gv-psub', (PV.pos || 'All positions') + ' · ' + Math.min(PV.n, total) + ' of ' + total);
    };
    $('gv-ppos').addEventListener('change', e => { PV.pos = e.target.value; drawP(); });
    $('gv-psort').addEventListener('change', e => { PV.sort = e.target.value; drawP(); });
    $('gv-pn').addEventListener('change', e => { PV.n = Number(e.target.value); drawP(); });
    drawP();
  });
});

})(window.GI);
