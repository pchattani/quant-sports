/* The Quant Ace — Value (#/<T>/value), Design System 2.0: who is likely to rise or fall over the next 6-12 months, how
 * much of a record is luck, and whose ranking runs ahead of or behind our rating. Round 9: the market comparison is the
 * Model section's "Our forecasts v the market" (#/<T>/versus, TA.value.market), the validation its "Who moves next"
 * (#/<T>/who-moves-next, TA.value.validation), and the surfaces the Rankings section's Elo view (TA.value.surfaces); the
 * old ?v=market / validation / surface links land there.
 *
 *   ?v=breakout     breakout and regression candidates with their reasons, the points calendar, the age curve
 *   ?v=luck         wins above expectation and its components (last 52 weeks or this season), and why it is luck
 *   ?v=over         official rank against the rank the model implies; points at that rank
 *   (surfaces)      surface ratings against the overall rating (specialists): drawn in the Elo view
 *   (market)        the closing market and Kalshi against our pre-match chance: drawn on the calibration page
 *   (validation)    the walk-forward record of the breakout model and the luck evidence: Model › Who moves next
 *   (?h=12m|6m on breakout and validation, ?w=52w|season on luck, ?s=hard|clay|grass on surface)
 *
 * Reads <T>/value.json and <T>/value_validation.json (analytics/value.py). TA.value.card(T, pid, el) draws the
 * compact card on the player page. */
(function (TA) {
'use strict';

const esc = TA.esc, isNum = TA.isNum;
/* round 9: Surfaces moved to the Rankings section's Elo view (TA.value.surfaces) and Validation to the Model section's
   "Who moves next" (#/<T>/who-moves-next, TA.value.validation); the old ?v= links land there (core.js redirectOf) */
const VIEWS = [
  { key: 'breakout', label: 'Breakouts' }, { key: 'nextgen', label: 'Next Gen (U21)' }, { key: 'luck', label: 'Luck' }, { key: 'over', label: 'Ranking v our rating' }
];
const H_LABEL = { '12m': '12 months', '6m': '6 months' };
const FEATURE_LABEL = {
  lr: 'Ranking level', gap: 'Ranking v model', age: 'Age', d_elo: 'Elo trend', d_rank: 'Rank trend', idle: 'Days out',
  n12: 'Activity', drop: 'Points to defend', tl: 'Tour-level share', luck: 'Close-match luck', draw: 'Draw luck', mk: 'Market v Elo'
};

function n0(v) { return isNum(v) ? TA.num(v, 0) : '—'; }
function sgn(v, d) { return isNum(v) ? TA.signed(v, d === undefined ? 1 : d) : '—'; }
function rk(v) { return isNum(v) ? 'No. ' + Math.round(v) : '—'; }
function ci(a) { return Array.isArray(a) && isNum(a[0]) ? TA.num(a[0], 3) + (isNum(a[1]) ? ' <span class="muted-inline">[' + TA.num(a[1], 2) + ', ' + TA.num(a[2], 2) + ']</span>' : '') : '—'; }
function signCls(v, goodHigh) { if (!isNum(v) || Math.abs(v) < 1e-9) return ''; return (v > 0) === (goodHigh !== false) ? 'edge-pos' : 'edge-neg'; }
function coloured(v, d, goodHigh) { return isNum(v) ? '<span class="' + signCls(v, goodHigh) + '">' + TA.signed(v, d === undefined ? 1 : d) + '</span>' : '—'; }
function pctEff(c) { return Math.round((Math.exp(c) - 1) * 100); }
function glossLink(key, text) { return '<a href="#/glossary/' + esc(key) + '" title="Definition">' + esc(text) + '</a>'; }
function setQuery(T, q) {
  const qs = Object.keys(q).filter(k => q[k] !== undefined && q[k] !== null && q[k] !== '').map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  try { history.replaceState(null, '', '#/' + T + '/value' + (qs ? '?' + qs : '')); } catch (e) { /* old browsers: the view still works */ }
}
function byPid(rows) { const m = {}; (rows || []).forEach(r => { if (r && r.pid) m[r.pid] = r; }); return m; }

/* One reason chip: what the feature says about the player and its effect on the predicted rank. */
function reasonChip(T, key, c, r, h) {
  let txt = FEATURE_LABEL[key] || key;
  switch (key) {
    case 'gap': txt = isNum(r.imp) ? 'Ranked ' + r.rank + ', model implies ' + Math.round(r.imp) : 'Ranking v model'; break;
    case 'age': txt = isNum(r.age) ? 'Age ' + TA.num(r.age, 1) : 'Age unknown'; break;
    case 'lr': txt = 'Rank ' + r.rank + (c < 0 ? ': room to rise' : ': hard to hold'); break;
    case 'd_elo': txt = 'Elo ' + sgn(r.d_elo, 0) + ' in 6 months'; break;
    case 'd_rank': txt = isNum(r.d_rank) && r.d_rank !== 0 ? 'Rank ' + (r.d_rank < 0 ? 'up' : 'down') + ' from ' + Math.round(r.rank * Math.exp(-r.d_rank)) + ' in 6 months' : 'Rank trend'; break;
    case 'idle': txt = n0(r.idle) + ' days since the last match'; break;
    case 'n12': txt = n0(r.n12) + ' matches in 12 months'; break;
    case 'drop': { const d = r['drop' + h]; txt = n0(d) + ' points to defend in ' + H_LABEL[h]; break; }
    case 'tl': txt = isNum(r.held) && isNum(r.pts) && r.pts > 0 ? Math.round(100 * r.held / r.pts) + '% of points from tour level' : 'Tour-level share'; break;
    case 'luck': txt = 'Close-match luck ' + sgn(r.luck, 1) + ' wins'; break;
    case 'draw': txt = 'Draw luck ' + sgn(r.draw, 1) + ' wins'; break;
    case 'mk': txt = isNum(r.mk) ? 'Market rates ' + Math.abs(Math.round(r.mk)) + (r.mk >= 0 ? ' above' : ' below') + ' Elo' : 'Market v Elo'; break;
    default: break;
  }
  const e = pctEff(c);
  const good = c < 0;
  return '<span class="chip vx-why ' + (good ? 'ok' : 'red') + '" title="' + esc((FEATURE_LABEL[key] || key) + ': moves the predicted rank by ' + (e > 0 ? '+' : '') + e + '% (negative = a better rank)') + '">' +
    esc(txt) + ' <b>' + (good ? '▲' : '▼') + '</b></span>';
}
function reasonsHTML(T, r, h, max) {
  const list = (r['why' + h] || []).slice(0, max || 3);
  return list.length ? '<span class="vx-whys">' + list.map(x => reasonChip(T, x[0], x[1], r, h)).join('') + '</span>' : '<span class="muted-inline">close to the average snapshot</span>';
}
function rangeHTML(r, h) {
  return '<b>' + rk(r['r' + h]) + '</b>' + (isNum(r['lo' + h]) ? '<div class="vx-sub">' + Math.round(r['lo' + h]) + '–' + Math.round(r['hi' + h]) + '</div>' : '');
}

// ── breakout ───────────────────────────────────────────────────────────────

function testStrip(V, h) {
  const t = (((V || {}).breakout || {}).test || {})[h] || {};
  const rs = t.risers || {}, fs = t.fallers || {};
  const yrs = t.years ? t.years[0] + '–' + t.years[1] : 'test years';
  return '<div class="kpi-grid vx-kpis">' +
    TA.statTile('Rank correlation', ci(t.rho), 'predicted v actual rank change, ' + yrs + ' · ' + glossLink('v_spearman', 'what is this')) +
    TA.statTile('Ranking alone', isNum(t.rho_rank_only) ? TA.num(t.rho_rank_only, 3) : '—', 'the same model on the rank only (regression to the mean)') +
    TA.statTile('Top-10 risers that broke out', isNum(rs.hit) ? TA.pct(rs.hit, 0) : '—', isNum(rs.base) ? 'base rate ' + TA.pct(rs.base, 0) + ' · lift ' + TA.num(rs.lift, 1) + '×' : '') +
    TA.statTile('Top-10 fallers that regressed', isNum(fs.hit) ? TA.pct(fs.hit, 0) : '—', isNum(fs.base) ? 'base rate ' + TA.pct(fs.base, 0) + ' · lift ' + TA.num(fs.lift, 1) + '×' : '') + '</div>';
}

function breakoutTable(T, rows, h, kind) {
  const isRise = kind === 'rise';
  const cols = [{ label: 'Player' }, { label: 'Age', align: 'right', cls: 'hide-sm' }, { label: 'Rank', align: 'right' },
    { label: 'Model implies', align: 'right', title: 'The official rank the model rating corresponds to', cls: 'hide-sm' },
    { label: 'In ' + H_LABEL[h], align: 'right', title: 'Predicted rank (10th–90th percentile below)' },
    { label: isRise ? 'P(breakout)' : 'P(regression)', align: 'right', title: isRise ? 'Rank improves by a third or more and 5+ places' : 'Rank worsens by half or more and 5+ places, or drops out' },
    { label: 'Points to defend', align: 'right', title: 'Tour-level points dropping in the next ' + H_LABEL[h] + ' / the mean earned at this level in the same time', cls: 'hide-sm' },
    { label: 'Why', sortable: false, cls: 'hide-sm' }];
  return TA.tableHTML(cols, rows.map(r => ({ _href: TA.playerHref(T, r.pid), cells: [
    { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true }) + '<div class="show-sm vx-mwhy">' + reasonsHTML(T, r, h, 2) + '</div>' },
    { v: r.age, html: isNum(r.age) ? TA.num(r.age, 1) : '—', cls: 'hide-sm' },
    { v: r.rank, html: String(r.rank) },
    { v: r.imp, html: n0(r.imp), cls: 'hide-sm' },
    { v: r['r' + h], html: rangeHTML(r, h) },
    { v: isRise ? r['p_rise' + h] : r['p_fall' + h], html: isNum(isRise ? r['p_rise' + h] : r['p_fall' + h]) ? TA.pct(isRise ? r['p_rise' + h] : r['p_fall' + h], 0) : '—' },
    { v: r['drop' + h], html: n0(r['drop' + h]) + (isNum(r['exp_earn' + h]) ? ' <span class="muted-inline">/ ' + n0(r['exp_earn' + h]) + '</span>' : ''), cls: 'hide-sm' },
    { v: '', html: reasonsHTML(T, r, h, 3), cls: 'hide-sm' }
  ] })), { compact: true });
}

function breakout(T, V, Val, body, q) {
  const h = q.h === '6m' ? '6m' : '12m';
  const B = V.breakout || {};
  const rows = (B.rows || []).filter(r => isNum(r['y' + h]));
  const pr = (r, k) => (isNum(r[k + h]) ? r[k + h] : -1);
  const rise = rows.filter(r => r.rank > 10).slice().sort((a, b) => pr(b, 'p_rise') - pr(a, 'p_rise') || a['y' + h] - b['y' + h]).slice(0, 20);
  const fall = rows.slice().sort((a, b) => pr(b, 'p_fall') - pr(a, 'p_fall') || b['y' + h] - a['y' + h]).slice(0, 20);
  const base = ((B.base_rise || {})[h]);
  body.innerHTML =
    '<div class="card"><div class="toggle-row" id="vx-h">Horizon ' + TA.toggles([{ key: '12m', label: '12 months' }, { key: '6m', label: '6 months' }], h, 'data-h') + '</div>' +
    testStrip(V, h) +
    '<div class="section-note">Every player in the official top ' + (V.universe || 150) + ' gets a forecast of where the ranking will be in ' + H_LABEL[h] +
    '. The model was fitted on quarterly snapshots since ' + (T === 'atp' ? '2008' : '2009') + ' and is scored here on years it never saw (' +
    '<a href="' + TA.href(T, 'who-moves-next') + '?h=' + h + '">validation</a>). The reasons are the features that move each forecast most against the average player; ' +
    '▲ pushes the rank up, ▼ down. ' + (isNum(base) ? 'About ' + TA.pct(base, 0) + ' of players outside the top 10 break out in a typical ' + H_LABEL[h] + '.' : '') + '</div></div>' +
    '<div class="card"><div class="card-header">Who could break out <span class="card-sub">Most likely to rise by a third or more, outside the top 10</span></div>' + breakoutTable(T, rise, h, 'rise') + '</div>' +
    '<div class="card"><div class="card-header">Who could slip back <span class="card-sub">Most likely to fall by half or more (and 5+ places), or out of tour-level draws</span></div>' + breakoutTable(T, fall, h, 'fall') + '</div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Age curve <span class="card-sub">Mean change in rank over the next 12 months by age, all snapshots (95% CI)</span></div><div id="vx-age" style="height:300px"></div></div>' +
    '<div class="card"><div class="card-header">The points to defend <span class="card-sub">Points to defend in the next ' + H_LABEL[h] + ' against what players at the model\'s level earn in that time</span></div><div id="vx-cal" style="height:300px"></div></div></div>' +
    '<div class="card"><div class="card-header">Everyone in the top ' + (V.universe || 150) + ' <span class="card-sub">Sortable; click a row for the player</span></div><div id="vx-all">' + allTable(T, rows, h) + '</div></div>';
  TA.sortable(body);
  TA.wireToggles(document.getElementById('vx-h'), 'data-h', k => { q.h = k; setQuery(T, { v: 'breakout', h: k }); breakout(T, V, Val, body, q); });
  ageChart('vx-age', Val);
  calendarChart(T, 'vx-cal', rows, h);
}

function allTable(T, rows, h) {
  const list = rows.slice().sort((a, b) => a.rank - b.rank);
  return TA.tableHTML([{ label: 'Rank', align: 'right' }, { label: 'Player' }, { label: 'Age', align: 'right', cls: 'hide-sm' },
    { label: 'Model implies', align: 'right', cls: 'hide-sm' }, { label: 'In ' + H_LABEL[h], align: 'right' },
    { label: 'Change', align: 'right', title: 'Predicted change in rank, %' }, { label: 'P(up)', align: 'right', cls: 'hide-sm' },
    { label: 'P(down)', align: 'right', cls: 'hide-sm' }, { label: 'Elo change', align: 'right', title: 'Predicted change in overall Elo', cls: 'hide-sm' }],
  list.map(r => ({ _href: TA.playerHref(T, r.pid), cells: [
    { v: r.rank, html: '<b>' + r.rank + '</b>' }, { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true }) },
    { v: r.age, html: isNum(r.age) ? TA.num(r.age, 1) : '—', cls: 'hide-sm' }, { v: r.imp, html: n0(r.imp), cls: 'hide-sm' },
    { v: r['r' + h], html: n0(r['r' + h]) },
    { v: r['y' + h], html: isNum(r['y' + h]) ? '<span class="' + (r['y' + h] < 0 ? 'edge-pos' : 'edge-neg') + '">' + (r['y' + h] > 0 ? '+' : '') + pctEff(r['y' + h]) + '%</span>' : '—' },
    { v: r['p_rise' + h], html: isNum(r['p_rise' + h]) ? TA.pct(r['p_rise' + h], 0) : '—', cls: 'hide-sm' },
    { v: r['p_fall' + h], html: isNum(r['p_fall' + h]) ? TA.pct(r['p_fall' + h], 0) : '—', cls: 'hide-sm' },
    { v: r['elo' + h], html: coloured(r['elo' + h], 0), cls: 'hide-sm' }] })), { compact: true, sticky: true });
}

function ageChart(id, Val) {
  const a = (Val && Val.age_curve) || [];
  const node = document.getElementById(id);
  if (!node) return;
  if (!a.length) { node.innerHTML = TA.muted('The age curve is not available yet.'); return; }
  node.classList.add('qk-chart');
  const pc = v => (Math.exp(v) - 1) * 100;
  QKC.line(node, { x: a.map(r => r[0]), xType: 'value', series: [{ name: 'Mean change in rank', data: a.map(r => pc(r[2])), color: QK.cssVar('--signal'), symbols: true,
    band: { lo: a.map(r => pc(r[3])), hi: a.map(r => pc(r[4])) } }], xName: 'Age at the snapshot (18 = 18 or younger, 34 = 34+)', yName: 'Mean change in rank number, %',
    yFmt: v => (v > 0 ? '+' : '') + Math.round(v) + '%', xFmt: v => String(Math.round(v)), ref: { y: 0 }, label: 'Age curve' });
}

function calendarChart(T, id, rows, h) {
  const node = document.getElementById(id);
  if (!node) return;
  const pts = rows.filter(r => isNum(r['drop' + h]) && isNum(r['exp_earn' + h]));
  if (!pts.length) { node.innerHTML = TA.muted('No points calendar yet.'); return; }
  const mx = Math.max.apply(null, pts.map(r => Math.max(r['drop' + h], r['exp_earn' + h]))) * 1.05;
  TA.v2.scatter(node, { points: pts.map(r => ({ x: Math.max(1, r['exp_earn' + h]), y: Math.max(1, r['drop' + h]), color: r['drop' + h] > r['exp_earn' + h] ? 'down' : 'up', href: TA.playerHref(T, r.pid),
    name: esc(TA.playerName(T, r.pid)) + ' (No. ' + r.rank + ')<br>To defend ' + n0(r['drop' + h]) + '<br>Expected at this level ' + n0(r['exp_earn' + h]) })),
    xLog: true, yLog: true, diagonal: [1, mx], xName: 'Expected tour-level points at our rating', yName: 'Tour-level points to defend', xFmt: v => n0(v), yFmt: v => n0(v),
    keys: [{ name: 'More to defend than expected', color: 'down' }, { name: 'Less to defend', color: 'up' }], label: 'Points to defend against points expected' });
}

// ── luck ───────────────────────────────────────────────────────────────────

function luckCell(x, key) {
  const v = x[key];
  return { v: v, html: coloured(v, 2) };
}
function clutchCell(c) {
  if (!c) return { v: null, html: '—' };
  return { v: c.over, html: c.w + '–' + c.l + ' <span class="' + signCls(c.over) + '">(' + TA.signed(c.over, 1) + ')</span>' };
}

function luckTable(T, list, w, wta) {
  const cols = [{ label: 'Player' }, { label: 'W–L', align: 'right' },
    { label: 'Expected wins', align: 'right', title: 'Pythagorean: the sum of P(win | share of games won) over completed matches', cls: 'hide-sm' },
    { label: 'Close matches', align: 'right', title: 'Wins minus the Pythagorean expectation' },
    { label: 'Tiebreaks', align: 'right', title: 'Won–lost (over the chain\'s expectation)', cls: 'hide-sm' },
    { label: 'Deciders', align: 'right', title: 'Deciding sets won–lost (over expectation)', cls: 'hide-sm' },
    { label: 'Draw', align: 'right', title: 'Wins from easier-than-typical opponents for the round and seed band' },
    { label: 'Free wins', align: 'right', title: 'Walkovers and retirements received', cls: 'hide-sm' },
    { label: 'Total', align: 'right', title: 'Wins above expectation = close matches + draw + free wins' },
    { label: 'Adj. win %', align: 'right', title: 'Luck-adjusted win %', cls: 'hide-sm' }]
    .concat(wta ? [{ label: 'BP saved', align: 'right', title: 'Break points saved over expected', cls: 'hide-sm' },
      { label: 'BP won', align: 'right', title: 'Break points converted over expected', cls: 'hide-sm' },
      { label: 'Pts→games', align: 'right', title: 'Points-to-games conversion (not counted as luck)', cls: 'hide-sm' }] : [])
    .concat([{ label: 'Schedule', align: 'right', title: 'Strength of schedule: mean opponent Elo v typical (not luck)', cls: 'hide-sm' }]);
  return TA.tableHTML(cols, list.map(r => {
    const x = r[w];
    return { _href: TA.playerHref(T, r.pid), cells: [
      { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true, rank: true }) },
      { v: x.w, html: x.w + '–' + x.l },
      { v: x.exp_games, html: isNum(x.exp_games) ? TA.num(x.exp_games, 1) : '—', cls: 'hide-sm' },
      luckCell(x, 'close'),
      Object.assign(clutchCell(x.tb), { cls: 'hide-sm' }), Object.assign(clutchCell(x.dec), { cls: 'hide-sm' }),
      luckCell(x, 'draw'), Object.assign(luckCell(x, 'free'), { cls: 'hide-sm' }),
      { v: x.total, html: '<b>' + coloured(x.total, 1) + '</b>' },
      { v: x.adj_win_pct, html: isNum(x.adj_win_pct) ? TA.pct(x.adj_win_pct, 1) + ' <span class="muted-inline">(' + TA.pct(x.win_pct, 0) + ')</span>' : '—', cls: 'hide-sm' }]
      .concat(wta ? [Object.assign(luckCell(x, 'bp_saved_over'), { cls: 'hide-sm' }), Object.assign(luckCell(x, 'bp_conv_over'), { cls: 'hide-sm' }),
        Object.assign(luckCell(x, 'conv'), { cls: 'hide-sm' })] : [])
      .concat([{ v: x.sos, html: isNum(x.sos) ? TA.signed(x.sos, 0) : '—', cls: 'hide-sm' }]) };
  }), { compact: true, sticky: true });
}

function evidenceHTML(Val) {
  const E = (Val && Val.luck_evidence) || {};
  const C = E.correlations || [];
  const get = k => C.find(c => c.key === k) || {};
  const P = E.prediction || [];
  const pr = k => P.find(c => c.key === k) || {};
  const tot = get('total_pm'), win = get('win_pct');
  const raw = pr('raw'), adj = pr('luck_adjusted'), d = pr('adjusted_minus_raw');
  return '<div class="kpi-grid vx-kpis">' +
    TA.statTile('Luck next season', isNum(tot.r) ? 'r = ' + TA.num(tot.r, 2) : '—', 'season-to-season correlation of wins above expectation per match' + (isNum(tot.lo) ? ' [' + TA.num(tot.lo, 2) + ', ' + TA.num(tot.hi, 2) + ']' : '')) +
    TA.statTile('Win % next season', isNum(win.r) ? 'r = ' + TA.num(win.r, 2) : '—', 'the same for win %: skill persists') +
    TA.statTile('Predicting next season', isNum(adj.r) ? TA.num(adj.r, 3) + ' v ' + TA.num(raw.r, 3) : '—', 'correlation with next season\'s win %: luck-adjusted v raw' + (isNum(d.lo) ? ' (difference ' + TA.signed(d.r, 3) + ' [' + TA.num(d.lo, 3) + ', ' + TA.num(d.hi, 3) + '])' : '')) +
    TA.statTile('Error next season', isNum(adj.rmse_wf) ? TA.num(adj.rmse_wf * 100, 1) + ' v ' + TA.num(raw.rmse_wf * 100, 1) : '—', 'walk-forward RMSE of next season\'s win % (points): adjusted v raw') + '</div>';
}

function evidenceChart(id, Val) {
  const node = document.getElementById(id);
  const C = ((Val && Val.luck_evidence) || {}).correlations || [];
  if (!node) return;
  if (!C.length) { node.innerHTML = TA.muted('The evidence is not available yet.'); return; }
  node.classList.add('qk-chart');
  const col = { luck: QK.cssVar('--signal'), skill: QK.cssVar('--c-1'), schedule: QK.cssVar('--c-7'), structural: QK.cssVar('--c-2') };
  const name = { luck: 'Luck (counted)', skill: 'Skill', schedule: 'Schedule (not counted)', structural: 'Structural (not counted)' };
  const kinds = ['luck', 'skill', 'schedule', 'structural'].filter(k => C.some(c => c.kind === k));
  QKC.bar(node, { cats: C.map(c => c.label), horizontal: true, labels: false, min: -0.2, max: 1, labelWidth: 230, fmt: v => Number(v).toFixed(2),
    series: [{ name: 'Correlation', data: C.map(c => c.r), lo: C.map(c => (isNum(c.lo) ? c.lo : null)), hi: C.map(c => (isNum(c.hi) ? c.hi : null)) }],
    colors: C.map(c => col[c.kind] || QK.cssVar('--c-other')), legendItems: kinds.map(k => ({ name: name[k], color: col[k] })),
    valName: 'Correlation, one season with the next (95% interval)', catName: 'Measure', label: 'Season-to-season correlations: luck against skill' });
}

function luck(T, V, Val, body, q) {
  const w = q.w === 'season' ? 'season' : '52w';
  const L = V.luck || {};
  const wta = T === 'wta';
  const rows = (L.rows || []).filter(r => r[w]);
  const by = k => rows.slice().sort((a, b) => (b[w][k] || 0) - (a[w][k] || 0));
  const top = by('total').slice(0, 8), bottom = by('total').reverse().slice(0, 8);
  const mini = list => TA.tableHTML([{ label: 'Player' }, { label: 'W–L', align: 'right' }, { label: 'Total', align: 'right' }, { label: 'Biggest part', sortable: false }],
    list.map(r => {
      const x = r[w];
      const parts = [['close matches', x.close], ['draws', x.draw], ['free wins', x.free]].filter(p => isNum(p[1])).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
      return { _href: TA.playerHref(T, r.pid), cells: [{ v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { rank: true }) }, { v: x.w, html: x.w + '–' + x.l },
        { v: x.total, html: '<b>' + coloured(x.total, 1) + '</b>' }, { v: '', html: parts.length ? esc(parts[0][0]) + ' ' + coloured(parts[0][1], 1) : '—' }] };
    }), { compact: true });
  const wins = L.windows || {};
  const win = wins[w] ? TA.fmtDate(wins[w][0], { weekday: false }) + ' – ' + TA.fmtDate(wins[w][1], { weekday: false }) : '';
  body.innerHTML =
    '<div class="card"><div class="toggle-row" id="vx-w">Window ' + TA.toggles([{ key: '52w', label: 'Last 52 weeks' }, { key: 'season', label: 'This season' }], w, 'data-w') +
    '<span class="muted-inline">' + esc(win) + ' · tour-level main draws · players with ' + (L.min_matches || 10) + '+ matches</span></div>' +
    evidenceHTML(Val) +
    '<div class="section-note">Wins above expectation = <b>close-match luck</b> (wins beyond what the share of games won deserves: a Pythagorean expectation, exponent ' +
    (isNum((L.params || {}).k_games_bo3) ? TA.num(L.params.k_games_bo3, 1) : '≈20') + ' for best of three) + <b>draw luck</b> (opponents weaker than the typical draw for the round and seed band at that event) + <b>free wins</b> (walkovers and retirements received). ' +
    'Tiebreaks and deciding sets against the chain\'s odds show where close-match luck came from' + (wta ? '; break points saved and won against the player\'s own serve and return rates are the point-level view' : '') + '. ' +
    'All of it regresses: the next season it is close to zero for everyone. ' + glossLink('v_total_luck', 'Definitions') + '</div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">The luckiest <span class="card-sub">Most wins above expectation</span></div>' + mini(top) + '</div>' +
    '<div class="card"><div class="card-header">The unluckiest <span class="card-sub">Fewest wins above expectation</span></div>' + mini(bottom) + '</div></div>' +
    '<div class="card"><div class="card-header">Every player <span class="card-sub">Wins above expectation and its parts; sortable</span></div>' + (rows.length ? luckTable(T, by('total'), w, wta) : TA.muted('No player has enough matches in this window yet.')) + '</div>' +
    '<div class="card"><div class="card-header">Why this is luck <span class="card-sub">Each measure in one season against the next, players with 20+ matches in both (95% CI)</span></div><div id="vx-ev" style="height:' + (wta ? 440 : 360) + 'px"></div></div>';
  TA.sortable(body);
  TA.wireToggles(document.getElementById('vx-w'), 'data-w', k => { q.w = k; setQuery(T, { v: 'luck', w: k }); luck(T, V, Val, body, q); });
  evidenceChart('vx-ev', Val);
}

// ── over / undervalue ──────────────────────────────────────────────────────

function overTable(T, list) {
  return TA.tableHTML([{ label: 'Player' }, { label: 'Rank', align: 'right' }, { label: 'Model implies', align: 'right' },
    { label: 'Gap', align: 'right', title: 'Places between the official rank and the rank the model implies (+ = underrated by the ranking)' },
    { label: 'Points', align: 'right', cls: 'hide-sm' }, { label: 'At implied rank', align: 'right', title: 'Points held by the player at the implied rank', cls: 'hide-sm' },
    { label: 'Model rating', align: 'right', cls: 'hide-sm' }, { label: 'Model rank', align: 'right', title: 'Among active players', cls: 'hide-sm' },
    { label: 'Elo · game · s+r', align: 'right', title: 'Ranks of the three parts of the rating: Elo, game-share Elo, serve plus return', cls: 'hide-sm' }],
  list.map(r => ({ _href: TA.playerHref(T, r.pid), cells: [
    { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true }) },
    { v: r.rank, html: isNum(r.rank) ? String(r.rank) : '—' }, { v: r.imp, html: isNum(r.imp) ? String(r.imp) : '—' },
    { v: isNum(r.rank) && isNum(r.imp) ? r.rank - r.imp : null, html: isNum(r.rank) && isNum(r.imp) ? coloured(r.rank - r.imp, 0) : '—' },
    { v: r.pts, html: n0(r.pts), cls: 'hide-sm' }, { v: r.pts_imp, html: n0(r.pts_imp), cls: 'hide-sm' },
    { v: r.R, html: n0(r.R), cls: 'hide-sm' }, { v: r.mrank, html: String(r.mrank), cls: 'hide-sm' },
    { v: r.elo_rank, html: [r.elo_rank, r.g_rank, r.sr_rank].map(x => (isNum(x) ? x : '—')).join(' · '), cls: 'hide-sm' }] })), { compact: true });
}

/* Round 9 (Phase 4): the Next Gen board. The under-21s in the breakout model's universe (age on the model's as-of day),
   ranked by where it sees them in twelve months: the ranking now against our forecast (the middle 80% as the range), the
   chance of a big climb, the Elo trend over six months and last year's matches. The model is the Breakouts view's,
   validated on Model › Who moves next. */
function rankPos(r) { return isNum(r) && r > 0 ? Math.max(0, Math.min(100, 100 * (1 - Math.log(r) / Math.log(400)))) : 0; }
function nextGen(T, V, Val, body) {
  const B = V.breakout || {};
  const rows = (B.rows || []).filter(r => isNum(r.age) && r.age < 21 && isNum(r.rank) && isNum(r.r12m)).sort((a, b) => a.r12m - b.r12m);
  if (!rows.length) { body.innerHTML = TA.card('Next Gen', '', TA.muted('No under-21 players in the model’s ranking universe right now.')); return; }
  const def = B.rise_def || {};
  const ours = QK.ours ? QK.ours({ short: true, model: 'Breakout model' }) : '';
  const top = rows.slice(0, 3).map(r => {
    const goal = Math.max(1, Math.min(Math.round(r.rank * Math.exp(isNum(def.log) ? def.log : -0.405)), r.rank - (def.places || 5)));
    return { kicker: 'Next Gen', name: TA.playerName(T, r.pid), sub: [TA.playerCountry(T, r.pid), 'age ' + Math.floor(r.age)].filter(Boolean).join(' · '), href: TA.playerHref(T, r.pid) + '?view=progression', sport: 'tennis',
      value: rk(r.r12m), unit: 'our forecast in a year',
      from: { label: 'Ranked now', value: rk(r.rank), pos: rankPos(r.rank) }, to: { label: 'A year on', value: rk(r.r12m), pos: rankPos(r.r12m) },
      text: (isNum(r.p_rise12m) ? TA.pct(r.p_rise12m, 0) + ' chance of a big climb (No. ' + goal + ' or better). ' : '') + (isNum(r.d_elo) && Math.abs(r.d_elo) >= 25 ? 'Elo ' + (r.d_elo > 0 ? 'up ' : 'down ') + Math.abs(Math.round(r.d_elo)) + ' in six months.' : ''), link: { text: 'Progression' } };
  });
  body.innerHTML = '<section class="qk-section">' + QK.sectionHead({ kicker: 'Next Gen', title: 'The under-21s, a year from now', html: true,
      sub: 'Every player under 21 in the ' + TA.tourName(T) + ' top ' + (V.universe || 150) + ', ordered by where our breakout model' + ours + ' sees them in twelve months.',
      actions: '<a class="qk-more" href="' + TA.href(T, 'scout') + '?age=u21">Every under-21 in the Scouting Room</a>' }) + QK.storyCards(top, { cols: 3 }) + '</section>' +
    '<div class="card"><div class="card-header">The board <span class="card-sub">' + rows.length + ' players · forecasts as of ' + esc(TA.fmtDate(V.as_of, { weekday: false })) + '</span></div>' +
    TA.tableHTML([{ label: '#', align: 'right' }, { label: 'Player' }, { label: 'Age', align: 'right' }, { label: 'Rank now', align: 'right' }, { label: 'In 12 months', align: 'right', title: 'Our forecast ranking a year on, with the middle 80% of outcomes' },
      { label: 'Big climb', align: 'right', title: 'Our chance of a big climb within a year' }, { label: 'Elo, 6 months', align: 'right', cls: 'hide-sm', title: 'Change in Elo over the last six months' }, { label: 'Matches, 12 months', align: 'right', cls: 'hide-sm' }],
    rows.map((r, i) => ({ _href: TA.playerHref(T, r.pid), cells: [{ v: i + 1, html: '<b>' + (i + 1) + '</b>' }, { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true }) },
      { v: r.age, html: TA.num(r.age, 1) }, { v: r.rank, html: String(r.rank) },
      { v: r.r12m, html: '<b>' + rk(r.r12m) + '</b>' + (isNum(r.lo12m) ? ' <span class="muted-inline">' + Math.round(r.lo12m) + '–' + Math.round(r.hi12m) + '</span>' : '') },
      { v: r.p_rise12m, html: isNum(r.p_rise12m) ? TA.pct(r.p_rise12m, 0) : '—' }, { v: r.d_elo, html: coloured(r.d_elo, 0), cls: 'hide-sm' }, { v: r.n12, html: isNum(r.n12) ? String(r.n12) : '—', cls: 'hide-sm' }] })), { compact: true }) + '</div>' +
    QK.note('<b>How sure are we?</b> Young players move the most and the hardest to call: the range is where the ranking lands 8 times in 10 in our forecast. The model’s record is on <a href="' + TA.href(T, 'who-moves-next') + '">Model › Who moves next</a>.');
  TA.sortable(body);
}

function over(T, V, Val, body) {
  const rows = ((V.value || {}).rows || []).filter(r => isNum(r.rank) && isNum(r.imp));
  const top200 = rows.filter(r => r.rank <= 200);
  const under = top200.filter(r => r.gap > 0).sort((a, b) => b.gap - a.gap).slice(0, 15);
  const overr = top200.filter(r => r.gap < 0).sort((a, b) => a.gap - b.gap).slice(0, 15);
  body.innerHTML =
    '<div class="card"><div class="section-note">The <b>model rating</b> is our match forecast in one number per player (Elo, the serve/return model and game-share Elo, blended as our match forecasts are). ' +
    'Ordering players by it and handing out the official ranks in that order gives the <b>rank the model implies</b>. A player ranked well below it is underrated by the ranking (often back from injury, or winning more than the points show); above it, overrated (points from a hot spell, or luck). ' +
    'Ranks below the ESPN top 150 (ATP) come from the latest match on record. The points column is the official total; "at implied rank" is what the player holding that rank has. ' + glossLink('v_implied_rank', 'Definitions') + '</div>' +
    '<div id="vx-sc" style="height:440px"></div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Underrated by the ranking <span class="card-sub">Ranked furthest below the model</span></div>' + overTable(T, under) + '</div>' +
    '<div class="card"><div class="card-header">Overrated by the ranking <span class="card-sub">Ranked furthest above the model</span></div>' + overTable(T, overr) + '</div></div>' +
    '<div class="card"><div class="card-header">Model ranking <span class="card-sub">Active players by model rating; sortable</span></div>' + overTable(T, ((V.value || {}).rows || []).slice(0, 150)) + '</div>';
  TA.sortable(body);
  const pts = top200;
  if (!pts.length) { document.getElementById('vx-sc').innerHTML = TA.muted('No ranking to compare yet.'); return; }
  const lab = new Set(under.slice(0, 6).concat(overr.slice(0, 6)).map(r => r.pid));
  TA.v2.scatter('vx-sc', { points: pts.map(r => ({ x: r.rank, y: r.imp, color: r.gap > 0.15 ? 'up' : r.gap < -0.15 ? 'down' : 'ink3', label: lab.has(r.pid) ? TA.playerSurname(T, r.pid) : '',
    href: TA.playerHref(T, r.pid), name: esc(TA.playerName(T, r.pid)) + '<br>Ranked ' + r.rank + ', our rating implies ' + r.imp + '<br>Our rank ' + r.mrank })),
    xLog: true, yLog: true, xInverse: true, yInverse: true, diagonal: [1, 300], xName: 'Official rank (log scale)', yName: 'Rank our rating implies (log scale)',
    xFmt: v => String(Math.round(v)), yFmt: v => String(Math.round(v)), keys: [{ name: 'Underrated by the ranking', color: 'up' }, { name: 'Overrated', color: 'down' }, { name: 'In line', color: 'ink3' }],
    label: 'Official rank against the rank our rating implies' });
}

// ── surfaces ───────────────────────────────────────────────────────────────

function surface(T, V, Val, body, q) {
  const s = ['hard', 'clay', 'grass'].indexOf(q.s) >= 0 ? q.s : 'hard';
  const rows = ((V.value || {}).rows || []).filter(r => r.surf && r.surf[s]);
  const minN = s === 'grass' ? 6 : 10;
  const rated = rows.filter(r => r.surf[s][2] >= minN);
  const best = rated.slice().sort((a, b) => b.surf[s][0] - a.surf[s][0]).slice(0, 30);
  const spec = rated.map(r => ({ r: r, g: r.surf[s][0] - r.R })).sort((a, b) => b.g - a.g);
  const tbl = list => TA.tableHTML([{ label: 'Player' }, { label: TA.surfaceLabel(s) + ' rating', align: 'right' }, { label: TA.surfaceLabel(s) + ' rank', align: 'right' },
    { label: 'Overall rank', align: 'right' }, { label: 'Surface gap', align: 'right', title: 'Surface rating minus the overall rating' },
    { label: 'Matches', align: 'right', title: 'Rated matches on the surface in the last 3 years', cls: 'hide-sm' }, { label: 'Official', align: 'right', cls: 'hide-sm' }],
  list.map(x => { const r = x.r || x; const sv = r.surf[s]; return { _href: TA.playerHref(T, r.pid), cells: [
    { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true }) }, { v: sv[0], html: '<b>' + n0(sv[0]) + '</b>' }, { v: sv[1], html: String(sv[1]) },
    { v: r.mrank, html: String(r.mrank) }, { v: sv[0] - r.R, html: coloured(sv[0] - r.R, 0) }, { v: sv[2], html: String(sv[2]), cls: 'hide-sm' },
    { v: r.rank, html: isNum(r.rank) ? String(r.rank) : '—', cls: 'hide-sm' }] }; }), { compact: true });
  body.innerHTML =
    '<div class="card"><div class="toggle-row" id="vx-s">Surface ' + TA.toggles([{ key: 'hard', label: 'Hard' }, { key: 'clay', label: 'Clay' }, { key: 'grass', label: 'Grass' }], s, 'data-s') + '</div>' +
    '<div class="section-note">The model rating on one surface uses the surface-blended Elo and game-share Elo and the serve/return record on that surface. The <b>surface gap</b> is the surface rating minus the overall one, in Elo points: who gains or loses most on ' +
    esc(TA.surfaceLabel(s).toLowerCase()) + '. Players with ' + minN + '+ rated matches on it in the last three years. ' + glossLink('v_surface', 'Definition') + '</div></div>' +
    '<div class="card"><div class="card-header">Best on ' + esc(TA.surfaceLabel(s).toLowerCase()) + ' <span class="card-sub">By surface rating</span></div>' + tbl(best) + '</div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">Specialists <span class="card-sub">Gain most on ' + esc(TA.surfaceLabel(s).toLowerCase()) + '</span></div>' + tbl(spec.slice(0, 12)) + '</div>' +
    '<div class="card"><div class="card-header">Weakest on it <span class="card-sub">Lose most on ' + esc(TA.surfaceLabel(s).toLowerCase()) + '</span></div>' + tbl(spec.slice().reverse().slice(0, 12)) + '</div></div>';
  TA.sortable(body);
  TA.wireToggles(document.getElementById('vx-s'), 'data-s', k => { q.s = k; if (q._route) q._route({ s: k }); else setQuery(T, { v: 'surface', s: k }); surface(T, V, Val, body, q); });
}

// ── market v model ─────────────────────────────────────────────────────────

function market(T, V, Val, body) {
  const M = V.market || {};
  const S = M.summary || {};
  const rows = (M.rows || []).filter(r => r.n >= 8);
  const hiM = rows.filter(r => r.gap > 0).sort((a, b) => b.gap - a.gap).slice(0, 12);
  const loM = rows.filter(r => r.gap < 0).sort((a, b) => a.gap - b.gap).slice(0, 12);
  const src = S.sources || {};
  const srcTxt = Object.keys(src).map(k => ({ ps: 'Pinnacle', bfe: 'Betfair exchange', avg: 'bookmakers\' average' }[k] || k) + ' ' + src[k]).join(', ');
  const tbl = list => TA.tableHTML([{ label: 'Player' }, { label: 'Matches', align: 'right' }, { label: 'Market v ours', align: 'right', title: 'Elo points: + = the market rates the player above our model' },
    { label: 'Wins', align: 'right' }, { label: 'We expected', align: 'right', cls: 'hide-sm' }, { label: 'Market expected', align: 'right', cls: 'hide-sm' },
    { label: 'Closer', align: 'right', title: 'Which forecaster had the lower log-loss on these matches' },
    { label: 'Kalshi', align: 'right', title: 'Kalshi v our model, Elo points (matches with a Kalshi quote)', cls: 'hide-sm' }],
  list.map(r => ({ _href: TA.playerHref(T, r.pid), cells: [
    { v: TA.playerName(T, r.pid), html: TA.playerLink(T, r.pid, { country: true, rank: true }) }, { v: r.n, html: String(r.n) },
    { v: r.gap, html: '<b>' + coloured(r.gap, 0) + '</b>' }, { v: r.w, html: String(r.w) },
    { v: r.x_model, html: isNum(r.x_model) ? TA.num(r.x_model, 1) : '—', cls: 'hide-sm' }, { v: r.x_market, html: isNum(r.x_market) ? TA.num(r.x_market, 1) : '—', cls: 'hide-sm' },
    { v: isNum(r.ll_model) && isNum(r.ll_market) ? r.ll_model - r.ll_market : null, html: isNum(r.ll_model) && isNum(r.ll_market) ? (r.ll_market < r.ll_model ? 'market' : 'ours') : '—' },
    { v: r.k_gap, html: r.k_n ? coloured(r.k_gap, 0) + ' <span class="muted-inline">(' + r.k_n + ')</span>' : '—', cls: 'hide-sm' }] })), { compact: true });
  body.innerHTML =
    '<div class="card"><div class="card-header">The market as a reference</div><div class="section-note vx-warn">The market is the sharper forecaster. In the backtest the closing line beats our model by about 0.02–0.03 in log-loss (ATP and WTA, 2010–2026), our research found nothing that closes the gap, and blending our model into Kalshi\'s number made it worse. ' +
    'So a difference below is a <b>disagreement</b>: the market usually knows something the scores do not (injury, form below tour level, motivation). It is not a recommendation.</div>' +
    '<div class="kpi-grid vx-kpis">' +
    TA.statTile('Matches compared', isNum(S.n) ? TA.num(S.n, 0) : '—', 'tour-level, last 52 weeks, with a closing line' + (srcTxt ? ' (' + esc(srcTxt) + ')' : '')) +
    TA.statTile('Log-loss: market v ours', isNum(S.ll_market) ? TA.num(S.ll_market, 4) + ' v ' + TA.num(S.ll_model, 4) : '—', 'lower is better; the difference is how much sharper the market is') +
    TA.statTile('Kalshi v ours', isNum(S.kalshi_ll_market) ? TA.num(S.kalshi_ll_market, 4) + ' v ' + TA.num(S.kalshi_ll_model, 4) : '—', S.kalshi_n ? S.kalshi_n + ' matches with a Kalshi quote about 4 h before the start' : 'no Kalshi quotes cached') + '</div>' +
    '<div class="section-note">Per player: the mean difference between the market\'s pre-match probability and ours, turned into Elo points (+ = the market rates the player higher), over the player\'s matches with a market number in the last 52 weeks (8 or more). "Closer" says which forecaster scored better on those matches. Kalshi quotes come from the research cache (June 2025 – 1 October 2026). ' + glossLink('v_market_gap', 'Definitions') + '</div></div>' +
    '<div class="grid-2"><div class="card"><div class="card-header">The market rates higher <span class="card-sub">Than we do</span></div>' + tbl(hiM) + '</div>' +
    '<div class="card"><div class="card-header">The market rates lower <span class="card-sub">Than we do</span></div>' + tbl(loM) + '</div></div>' +
    '<div class="card"><div class="card-header">Every player <span class="card-sub">Sortable</span></div>' + tbl(rows) + '</div>';
  TA.sortable(body);
}

// ── validation ─────────────────────────────────────────────────────────────

function validation(T, V, Val, body, q) {
  const h = q.h === '6m' ? '6m' : '12m';
  if (!TA.ok(Val)) { body.innerHTML = TA.card('Validation', '', TA.notBuilt('The validation', Val)); return; }
  const v = ((Val.validation || {})[h]) || {};
  const per = v.per_year || {};
  const def = Val.definitions || {};
  const test = def.test_years || [2018, 2025], dev = def.dev_years || [2010, 2017];
  const pooled = v.pooled || {};
  const tile = (name, p) => TA.statTile(name + (p.years ? ' ' + p.years[0] + '–' + p.years[1] : ''), ci(p.rho),
    'rank only ' + (isNum(p.rho_rank_only) ? TA.num(p.rho_rank_only, 3) : '—') + ' · rank + model gap ' + (isNum(p.rho_rank_model) ? TA.num(p.rho_rank_model, 3) : '—') + ' · Elo change ' + (p.rho_elo ? TA.num(p.rho_elo[0], 3) : '—'));
  const years = Object.keys(per).sort();
  const yrRows = years.map(y => {
    const b = per[y] || {}, rs = b.risers || {}, fs = b.fallers || {};
    const isTest = Number(y) >= test[0] && Number(y) <= test[1];
    return { cells: [{ v: Number(y), html: '<b>' + y + '</b> ' + (isTest ? '<span class="chip ok">test</span>' : '<span class="chip">dev</span>') },
      { v: b.n_obs, html: (isNum(b.n_obs) ? b.n_obs : '—') + ' <span class="muted-inline">/ ' + (b.n || '—') + '</span>', cls: 'hide-sm' },
      { v: b.rho ? b.rho[0] : null, html: ci(b.rho) }, { v: b.rho_rank_only, html: isNum(b.rho_rank_only) ? TA.num(b.rho_rank_only, 3) : '—' },
      { v: b.rho_rank_model, html: isNum(b.rho_rank_model) ? TA.num(b.rho_rank_model, 3) : '—', cls: 'hide-sm' },
      { v: b.rho_elo ? b.rho_elo[0] : null, html: b.rho_elo ? TA.num(b.rho_elo[0], 3) : '—', cls: 'hide-sm' },
      { v: rs.hit, html: isNum(rs.hit) ? TA.pct(rs.hit, 0) + ' <span class="muted-inline">v ' + TA.pct(rs.base, 0) + '</span>' : '—' },
      { v: fs.hit, html: isNum(fs.hit) ? TA.pct(fs.hit, 0) + ' <span class="muted-inline">v ' + TA.pct(fs.base, 0) + '</span>' : '—', cls: 'hide-sm' }] };
  });
  const coef = ((Val.coefficients || {})[h]) || {};
  const drop = ((Val.drop_one || {})[h]) || [];
  const dropMap = {}; drop.forEach(d => { dropMap[d[0]] = d[1]; });
  const coefRows = (coef.rank || []).map(c => ({ cells: [{ v: FEATURE_LABEL[c[0]] || c[0], html: esc(FEATURE_LABEL[c[0]] || c[0]) + ' <span class="muted-inline">' + esc(c[0]) + '</span>' },
    { v: c[1], html: coloured(-c[1], 3) }, { v: dropMap[c[0]], html: isNum(dropMap[c[0]]) ? TA.signed(dropMap[c[0]], 3) : (c[0] === 'age2' || c[0] === 'age_na' ? '<span class="muted-inline">with age</span>' : '—') },
    { v: '', html: '<span class="muted-inline">' + esc(((Val.features || []).find(f => f.key === c[0]) || {}).desc || '') + '</span>', cls: 'hide-sm' }] }));
  const recent = (v.recent || []).slice().reverse();
  const recentHTML = recent.map(s => '<div class="card"><div class="card-header">Snapshot ' + esc(TA.fmtDate(s.t, { weekday: false })) + ' <span class="card-sub">Top 10 predicted risers and where they were ' + H_LABEL[h] + ' later</span></div>' +
    TA.tableHTML([{ label: 'Player' }, { label: 'Rank then', align: 'right' }, { label: 'Predicted', align: 'right' }, { label: 'Actual', align: 'right' }],
      (s.risers || []).map(x => ({ _href: TA.playerHref(T, x[0]), cells: [{ v: TA.playerName(T, x[0]), html: TA.playerLink(T, x[0]) }, { v: x[1], html: String(x[1]) },
        { v: x[2], html: n0(x[1] * Math.exp(x[2])) }, { v: x[3], html: isNum(x[3]) ? '<span class="' + (x[3] < x[1] ? 'edge-pos' : 'edge-neg') + '">' + x[3] + '</span>' : '<span class="muted-inline">not on record</span>' }] })), { compact: true }) + '</div>').join('');
  const tu = Val.tuned || {};
  const P = Val.panel || {};
  body.innerHTML =
    '<div class="card"><div class="toggle-row" id="vx-vh">Horizon ' + TA.toggles([{ key: '12m', label: '12 months' }, { key: '6m', label: '6 months' }], h, 'data-h') + '</div>' +
    '<div class="kpi-grid vx-kpis">' + tile('Test', pooled.test || {}) + tile('Dev', pooled.dev || {}) +
    TA.statTile('Risers (test)', ((pooled.test || {}).risers || {}).hit !== undefined ? TA.pct(pooled.test.risers.hit, 0) + ' v ' + TA.pct(pooled.test.risers.base, 0) : '—', 'top-10 predicted risers that broke out v all players · recall ' + (isNum(((pooled.test || {}).risers || {}).recall) ? TA.pct(pooled.test.risers.recall, 0) : '—')) +
    TA.statTile('Brier (test)', (pooled.test || {}).brier_rise ? TA.num(pooled.test.brier_rise[0], 3) + ' v ' + TA.num(pooled.test.brier_rise[1], 3) : '—', 'breakout probability v the base rate; regression ' + ((pooled.test || {}).brier_fall ? TA.num(pooled.test.brier_fall[0], 3) + ' v ' + TA.num(pooled.test.brier_fall[1], 3) : '—')) + '</div>' +
    '<div class="section-note">How it was tested. Snapshots on 1 January, April, July and October from ' + (def.first_snapshot || '') + '; the universe is the official top ' + (def.universe || 150) +
    ' (the latest rank on a match in the ' + (def.rank_before_days || 120) + ' days before). The target is the change in log rank to the rank on record nearest the horizon (±' + (def.target_window_days || 45) + ' days); ' +
    'a player with none there (usually out of tour-level main draws) counts as a regression and never as a breakout. Each year is predicted by a model fitted only on snapshots whose outcome was known by 1 January of that year. ' +
    'Ridge penalty ' + (isNum(tu.lam) ? tu.lam : '—') + ' and shrinkage ' + (isNum(tu.k_shrink) ? tu.k_shrink : '—') + ' were chosen on ' + dev[0] + '–' + dev[1] + ' only; ' + test[0] + '–' + test[1] + ' are the test years. ' +
    'Spearman CIs resample players (400 draws). ' + (P.rows ? P.rows.toLocaleString() + ' player-snapshots, ' + P.snapshots + ' snapshots' : '') + (P.dropped && P.dropped.length ? '; dropped (no tennis at the horizon): ' + esc(P.dropped.join(', ')) : '') + '.</div></div>' +
    '<div class="card"><div class="card-header">Year by year <span class="card-sub">Rank correlation (95% CI), the two baselines, Elo change, and the top-10 hit rates against the base rates</span></div>' +
    '<div id="vx-yr" style="height:300px"></div>' +
    TA.tableHTML([{ label: 'Year' }, { label: 'Observed / all', align: 'right', cls: 'hide-sm' }, { label: 'Model', align: 'right' }, { label: 'Rank only', align: 'right' },
      { label: 'Rank + model gap', align: 'right', cls: 'hide-sm' }, { label: 'Elo change', align: 'right', cls: 'hide-sm' }, { label: 'Risers hit', align: 'right' }, { label: 'Fallers hit', align: 'right', cls: 'hide-sm' }], yrRows, { compact: true }) + '</div>' +
    '<div class="card"><div class="card-header">What drives the forecast <span class="card-sub">Standardised coefficients (+ = towards a better rank) and the test-years correlation lost without each feature</span></div>' +
    TA.tableHTML([{ label: 'Feature' }, { label: 'Coefficient', align: 'right' }, { label: 'Without it', align: 'right', title: 'Change in the mean yearly Spearman correlation, test years' }, { label: 'What it is', sortable: false, cls: 'hide-sm' }], coefRows, { compact: true }) + '</div>' +
    '<div class="card"><div class="card-header">Luck: the evidence <span class="card-sub">Season-to-season correlations and next-season win %</span></div>' + evidenceHTML(Val) + '<div id="vx-ev2" style="height:' + (T === 'wta' ? 440 : 360) + 'px"></div></div>' +
    '<div class="card"><div class="card-header">Age curve</div><div id="vx-age2" style="height:300px"></div></div>' +
    '<div class="day-head">The last scored snapshots</div><div class="grid-2">' + recentHTML + '</div>';
  TA.sortable(body);
  TA.wireToggles(document.getElementById('vx-vh'), 'data-h', k => { q.h = k; if (q._route) q._route({ h: k }); else setQuery(T, { v: 'validation', h: k }); validation(T, V, Val, body, q); });
  const ys = years.filter(y => per[y] && per[y].rho);
  const xs = ys.map(Number);
  const yn = document.getElementById('vx-yr');
  if (yn && xs.length) {
    yn.classList.add('qk-chart');
    QKC.line(yn, { x: xs, xType: 'value', series: [
      { name: 'Our model (95% CI)', data: ys.map(y => per[y].rho[0]), color: QK.cssVar('--signal'), lo: ys.map(y => (isNum(per[y].rho[1]) ? per[y].rho[1] : null)), hi: ys.map(y => (isNum(per[y].rho[2]) ? per[y].rho[2] : null)), symbols: true },
      { name: 'Rank only', data: ys.map(y => per[y].rho_rank_only), color: QK.cssVar('--c-other'), dash: true, symbols: true }],
      xName: 'Snapshot year' + (test ? ' (test years from ' + test[0] + ')' : ''), yName: 'Spearman: predicted v actual rank change', yMin: 0, yMax: 0.8, xFmt: v => String(Math.round(v)),
      yFmt: v => Number(v).toFixed(2), ref: test ? { x: test[0] - 0.5, label: 'test years →' } : undefined, label: 'Rank correlation by year' });
  }
  evidenceChart('vx-ev2', Val);
  ageChart('vx-age2', Val);
}

// ── page ───────────────────────────────────────────────────────────────────

function render(el, params) {
  const T = params.tour;
  const q = Object.assign({}, params.query || {});
  let view = q.v;
  if (!VIEWS.some(v => v.key === view)) view = 'breakout';
  const tabs = '<nav class="qk-tabs ta-tabs" aria-label="Value views">' + VIEWS.map(v => '<a class="qk-tab" href="#/' + T + '/value?v=' + v.key + '"' + (v.key === view ? ' aria-selected="true" aria-current="page"' : ' aria-selected="false"') + '>' + esc(v.label) + '</a>').join('') +
    '</nav><p class="ta-moved">How the breakout model is built: <a href="#/methodology/m-value">Model › How it works</a>. How well it has called the climbers: <a href="' + TA.href(T, 'who-moves-next') + '">Model › Who moves next</a>.</p>';
  el.innerHTML = tabs + '<div id="vx-body" style="margin-top:var(--sp-4)">' + QK.skeleton('lines', 6) + '</div>';
  return TA.loadAll([TA.tpath('value.json', T), TA.tpath('value_validation.json', T)]).then(arr => {
    if (!el.isConnected) return;
    const V = arr[0], Val = TA.ok(arr[1]) ? arr[1] : null;
    const body = document.getElementById('vx-body');
    if (!TA.ok(V)) { body.innerHTML = TA.card('Value', '', TA.notBuilt('The Value section', V)); return; }
    const fn = { breakout: breakout, nextgen: nextGen, luck: luck, over: over }[view];
    fn(T, V, Val, body, q);
    TA.setMeta('Value as of ' + esc(TA.fmtDate(V.as_of, { year: false })) + (V.model_asof ? ' · model fitted ' + esc(TA.fmtDate(V.model_asof, { weekday: false })) : ''));
  });
}

/* The compact card on the player page: breakout forecast, luck, ranking v our rating. */
function card(T, pid, el) {
  if (!el) return Promise.resolve();
  return TA.load(TA.tpath('value.json', T)).then(V => {
    if (!el.isConnected) return;
    if (!TA.ok(V)) { el.innerHTML = ''; return; }
    const b = byPid((V.breakout || {}).rows)[pid], l = byPid((V.luck || {}).rows)[pid], v = byPid((V.value || {}).rows)[pid], m = byPid((V.market || {}).rows)[pid];
    if (!b && !l && !v && !m) { el.innerHTML = ''; return; }
    const link = k => TA.href(T, 'value') + '?v=' + k;
    const tiles = [];
    if (b) {
      const pr = isNum(b.p_rise12m) ? 'P(breakout) ' + TA.pct(b.p_rise12m, 0) + ' · ' : '';
      tiles.push(TA.statTile('In 12 months', rk(b.r12m) + (isNum(b.lo12m) ? ' <span class="vx-sub-inline">' + Math.round(b.lo12m) + '–' + Math.round(b.hi12m) + '</span>' : ''),
        pr + 'P(regression) ' + (isNum(b.p_fall12m) ? TA.pct(b.p_fall12m, 0) : '—') + ' · <a href="' + link('breakout') + '">breakouts →</a>'));
    } else {
      tiles.push(TA.statTile('In 12 months', '—', 'forecasts cover the official top ' + (V.universe || 150)));
    }
    const x = l ? (l['52w'] || l.season) : null;
    tiles.push(TA.statTile('Luck, 52 weeks', x ? coloured(x.total, 1) + ' <span class="vx-sub-inline">wins</span>' : '—',
      x ? 'close matches ' + sgn(x.close, 1) + ' · draws ' + sgn(x.draw, 1) + ' · free ' + sgn(x.free, 1) + ' · <a href="' + link('luck') + '">luck →</a>' : 'fewer than ' + ((V.luck || {}).min_matches || 10) + ' tour-level matches'));
    tiles.push(TA.statTile('Ranking v our rating', v && isNum(v.imp) ? 'No. ' + (isNum(v.rank) ? v.rank : '—') + ' v ' + v.imp : (v ? 'model No. ' + v.mrank : '—'),
      v ? (isNum(v.rank) && isNum(v.imp) ? (v.rank > v.imp ? 'underrated by ' + (v.rank - v.imp) + ' places' : v.rank < v.imp ? 'overrated by ' + (v.imp - v.rank) + ' places' : 'in line') + ' · rating ' + n0(v.R) + ' · ' : '') + '<a href="' + link('over') + '">ranking v our rating →</a>' : 'not rated (fewer than 10 rated matches or inactive)'));
    const why = b && (b.why12m || []).length ? '<div class="vx-card-why">Forecast drivers: ' + reasonsHTML(T, b, '12m', 4) + '</div>' : '';
    el.innerHTML = TA.v2.card('Where the ranking is heading', 'Our ranking forecast for a year from now, how much of the last 52 weeks was luck, and whether the ranking runs ahead of or behind our rating (' +
      '<a href="' + TA.href(T, 'who-moves-next') + '">how good is this?</a>)', '<div class="kpi-grid">' + tiles.join('') + '</div>' + why +
      QK.note((b && isNum(b.lo12m) && isNum(b.hi12m) ? 'The range ' + Math.round(b.lo12m) + '–' + Math.round(b.hi12m) + ' is where the ranking lands 8 times in 10 in our forecast. ' : '') + 'Luck counts wins beyond what the games won predicted, kind draws and walkovers; it rarely repeats from one year to the next.'), { cls: 'vx-card' });
  });
}

/* The market comparison for the Model section (calibration page): the closing market and Kalshi against our chance. */
function marketView(T, el) {
  if (!el) return Promise.resolve();
  return TA.load(TA.tpath('value.json', T)).then(V => {
    if (!el.isConnected) return;
    if (!TA.ok(V) || !V.market) { el.innerHTML = ''; return; }
    market(T, V, null, el);
  });
}

/* The surface ratings (best on a surface, specialists, weakest) for the Rankings section's Elo view; q.s picks the surface,
   q._route(change) keeps the address. */
function surfacesView(T, el, q) {
  if (!el) return Promise.resolve();
  return TA.load(TA.tpath('value.json', T)).then(V => {
    if (!el.isConnected) return;
    if (!TA.ok(V)) { el.innerHTML = ''; return; }
    surface(T, V, null, el, q || {});
  });
}
/* The breakout model's walk-forward record for the Model section's "Who moves next" */
function validationView(T, el, q) {
  if (!el) return Promise.resolve();
  return TA.loadAll([TA.tpath('value.json', T), TA.tpath('value_validation.json', T)]).then(arr => {
    if (!el.isConnected) return;
    validation(T, arr[0] || {}, TA.ok(arr[1]) ? arr[1] : null, el, q || {});
  });
}

TA.value = { card: card, market: marketView, surfaces: surfacesView, validation: validationView };
TA.route('value', render);
})(window.TA);
