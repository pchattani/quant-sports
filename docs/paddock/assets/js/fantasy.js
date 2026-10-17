/* The Quant Paddock — fantasy (#/fantasy).
 *
 * Our own fantasy-style points table (qualifying, Grand Prix and sprint positions, places gained, fastest
 * laps, overtakes, retirements; constructors add qualifying progression and pit-stop bands), with every
 * projection from the race simulation: the next weekend with a floor and a ceiling (10th / 90th percentiles
 * of the simulated weekend), the rest of the season (one season-long simulation), tiers, value against our
 * form line (a price proxy: the official F1 Fantasy prices are not used), differentials, risers and fades,
 * our suggested picks with generated reasons, the schedule ahead and the walk-forward backtest.
 *
 * Data: data/<y>/fantasy.json (current season), data/fantasy_backtest.json (site-wide backtest). */
(function (PD) {
'use strict';

const { esc, num, signed, isNum, card, muted, tableHTML, sortable, statTile, plot, layout, C } = PD;
const PG = () => PD.pg;

const COMP = {
  quali: ['Qualifying', '#58a6ff'], race_pos: ['Race finish', '#3fb950'], race_gain: ['Places gained', '#39d0d8'], race_fl: ['Fastest lap', '#bc8cff'],
  overtakes: ['Overtakes', '#d29922'], sprint_pos: ['Sprint finish', '#7ee787'], sprint_gain: ['Sprint places', '#79c0ff'], sprint_fl: ['Sprint fastest lap', '#d2a8ff'],
  race_dnf: ['Retirement risk', '#f85149'], sprint_dnf: ['Sprint retirement risk', '#ff7b72']
};
const METHODS = { model: 'Our projection', std: 'Season-to-date average', prev: 'Previous weekend', last: 'Last season\'s average', blend: 'Half ours, half season average' };
const PICK_GROUPS = [
  ['top', 'Top picks', 'The five highest projections for the next weekend.'],
  ['boost', 'Boost pick', 'The highest expected score: the one to double.'],
  ['value', 'Value', 'Projection above the form line (our price proxy), among drivers who score.'],
  ['differentials', 'Differentials', 'Projection ranks well above the form line. No ownership data is used.'],
  ['risers', 'Risers / buy low', 'Underlying pace, car development or bad luck ahead of the form.'],
  ['fades', 'Form flatters / sell high', 'Form line above what we project for the rest of the season.'],
  ['constructors', 'Constructors', 'The two highest constructor projections.'],
  ['constructor_value', 'Constructor value', 'Constructor projection above its form line.']
];

let F = null, BT = null;
const ST = { view: 'next', sched: 'drivers' };

function rowsOf(cols, rows) {
  return (rows || []).map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}
const pts = (v, d) => (isNum(v) ? num(v, d === undefined ? 1 : d) : '—');
const pc = v => (isNum(v) ? Math.round(100 * v) + '%' : '—');
const val = v => (isNum(v) ? '<span class="' + (v > 0.05 ? 'pg-up' : v < -0.05 ? 'pg-down' : '') + '">' + signed(v, 1) + '</span>' : '<span class="muted-inline">—</span>');
const tierPill = t => (isNum(t) ? '<span class="ft-tier t' + t + '">T' + t + '</span>' : '<span class="muted-inline">—</span>');

/* Floor to ceiling as a small bar on a shared scale, the mean as a dot. */
function rangeBar(lo, mean, hi, min, max) {
  if (!isNum(lo) || !isNum(hi) || !isNum(mean) || max <= min) return '';
  const x = v => Math.max(0, Math.min(100, 100 * (v - min) / (max - min)));
  return '<span class="ft-range" title="10th percentile ' + num(lo, 0) + ', mean ' + num(mean, 1) + ', 90th percentile ' + num(hi, 0) + '">' +
    '<span class="ft-rbar" style="left:' + x(lo).toFixed(1) + '%;width:' + Math.max(1, x(hi) - x(lo)).toFixed(1) + '%"></span>' +
    '<span class="ft-rdot" style="left:' + x(mean).toFixed(1) + '%"></span><span class="ft-rzero" style="left:' + x(0).toFixed(1) + '%"></span></span>';
}

function driverCell(r) {
  return PD.driverLink(r.id, { name: r.name, team: r.team });
}

function pickCard(key, title, sub, items, teamsById) {
  const list = Array.isArray(items) ? items : (items ? [items] : []);
  if (!list.length) return '';
  const isTeam = key.indexOf('constructor') === 0;
  return '<div class="ft-pick"><div class="ft-pick-h">' + esc(title) + '</div><div class="ft-pick-sub">' + esc(sub) + '</div>' + list.map(p => {
    const who = isTeam ? PD.teamLink(p.id, (teamsById[p.id] || {}).name) : PD.driverLink(p.id, { name: (F.names.drivers || {})[p.id], team: ((F._byId || {})[p.id] || {}).team });
    return '<div class="ft-pick-r"><div class="ft-pick-top">' + who + '<span class="ft-pick-v">' + pts(p.proj) + ' <span class="muted-inline">pts</span>' +
      (isNum(p.value) ? ' · ' + val(p.value) : '') + '</span></div>' + (p.why && p.why.length ? '<ul class="ft-why">' + p.why.map(w => '<li>' + esc(w) + '</li>').join('') + '</ul>' : '') + '</div>';
  }).join('') + '</div>';
}

function driverTable(D) {
  const nextRows = D.filter(r => isNum(r.next));
  const lo = Math.min.apply(null, nextRows.map(r => (ST.view === 'next' ? r.p10 : r.ros_p10)).filter(isNum).concat([0]));
  const hi = Math.max.apply(null, nextRows.map(r => (ST.view === 'next' ? r.p90 : r.ros_p90)).filter(isNum).concat([1]));
  if (ST.view === 'next') {
    const cols = [{ label: '#', align: 'right' }, { label: 'Tier', title: 'Tiers of the next-weekend projection (optimal 1-D breaks)' }, { label: 'Driver' },
      { label: 'Projected', align: 'right', title: 'Expected fantasy points next weekend (our table)' }, { label: 'Floor – ceiling', sortable: false, title: '10th to 90th percentile of the simulated weekend; the dot is the mean, the tick zero' },
      { label: 'Floor', align: 'right' }, { label: 'Ceiling', align: 'right' }, { label: 'Q3', align: 'right', title: 'Reaches Q3 (top ten in qualifying)' },
      { label: 'Front rows', align: 'right', title: 'Qualifies in the top four' }, { label: 'DNF', align: 'right', title: 'Not classified in the Grand Prix' },
      { label: 'Fastest lap', align: 'right' }, { label: 'Form line', align: 'right', title: 'Our price proxy: season-to-date points per weekend blended with last season (n×form + 3×last)/(n + 3)' },
      { label: 'Value', align: 'right', title: 'Projection minus the form line' }];
    const rows = nextRows.slice().sort((a, b) => b.next - a.next).map((r, i) => ({ _href: '#/driver/' + encodeURIComponent(r.id), cells: [i + 1, { v: r.tier_next, html: tierPill(r.tier_next) },
      { v: r.name, html: driverCell(r) }, { v: r.next, html: '<strong>' + pts(r.next) + '</strong>' }, { v: r.next, html: rangeBar(r.p10, r.next, r.p90, lo, hi) },
      { v: r.p10, html: pts(r.p10, 0) }, { v: r.p90, html: pts(r.p90, 0) }, { v: r.p_q3, html: pc(r.p_q3) }, { v: r.p_front, html: pc(r.p_front) }, { v: r.p_dnf, html: pc(r.p_dnf) },
      { v: r.p_fl, html: pc(r.p_fl) }, { v: r.price, html: pts(r.price) }, { v: r.value, html: val(r.value) }] }));
    return tableHTML(cols, rows, { compact: true, sticky: true, id: 'ft-dtab' });
  }
  const cols = [{ label: '#', align: 'right' }, { label: 'Tier', title: 'Tiers of the rest-of-season points per weekend' }, { label: 'Driver' },
    { label: 'Rest of season', align: 'right', title: 'Expected fantasy points over the remaining rounds' }, { label: 'Range', sortable: false, title: '10th to 90th percentile of the season-long simulation' },
    { label: 'Floor', align: 'right' }, { label: 'Ceiling', align: 'right' }, { label: 'Rounds', align: 'right' }, { label: 'Per weekend', align: 'right' },
    { label: 'Form line', align: 'right' }, { label: 'Value / weekend', align: 'right', title: 'Per-weekend projection minus the form line' }, { label: 'Season so far', align: 'right', title: 'Average points per weekend this season (our table)' }];
  const rows = nextRows.slice().sort((a, b) => (b.ros || 0) - (a.ros || 0)).map((r, i) => ({ _href: '#/driver/' + encodeURIComponent(r.id), cells: [i + 1, { v: r.tier, html: tierPill(r.tier) },
    { v: r.name, html: driverCell(r) }, { v: r.ros, html: '<strong>' + pts(r.ros, 0) + '</strong>' }, { v: r.ros, html: rangeBar(r.ros_p10, r.ros, r.ros_p90, lo, hi) },
    { v: r.ros_p10, html: pts(r.ros_p10, 0) }, { v: r.ros_p90, html: pts(r.ros_p90, 0) }, { v: r.rounds_left, html: String(r.rounds_left || 0) }, { v: r.ros_per, html: pts(r.ros_per) },
    { v: r.price, html: pts(r.price) }, { v: r.value_ros, html: val(r.value_ros) }, { v: r.form, html: pts(r.form) + ' <span class="muted-inline">(' + (r.form_n || 0) + ')</span>' }] }));
  return tableHTML(cols, rows, { compact: true, sticky: true, id: 'ft-dtab' });
}

function teamTable(T) {
  const live = T.filter(r => isNum(r.next));
  const lo = Math.min.apply(null, live.map(r => r.p10).filter(isNum).concat([0])), hi = Math.max.apply(null, live.map(r => r.p90).filter(isNum).concat([1]));
  const cols = [{ label: '#', align: 'right' }, { label: 'Tier' }, { label: 'Constructor' }, { label: 'Projected', align: 'right' }, { label: 'Floor – ceiling', sortable: false },
    { label: 'Drivers', align: 'right', title: 'Both drivers\' expected points' }, { label: 'Qualifying', align: 'right', title: 'Expected qualifying-progression bonus' },
    { label: 'Pit stops', align: 'right', title: 'Expected pit-stop band points (stationary times)' }, { label: 'Rest of season', align: 'right' }, { label: 'Per weekend', align: 'right' },
    { label: 'Form line', align: 'right' }, { label: 'Value', align: 'right' }];
  const rows = live.map((r, i) => ({ _href: '#/team/' + encodeURIComponent(r.id), cells: [i + 1, { v: r.tier, html: tierPill(r.tier) }, { v: r.name, html: PD.teamLink(r.id, r.name) },
    { v: r.next, html: '<strong>' + pts(r.next) + '</strong>' }, { v: r.next, html: rangeBar(r.p10, r.next, r.p90, lo, hi) }, { v: r.drivers, html: pts(r.drivers) },
    { v: r.q_bonus, html: pts(r.q_bonus) }, { v: r.pit, html: pts(r.pit) }, { v: r.ros, html: pts(r.ros, 0) }, { v: r.ros_per, html: pts(r.ros_per) }, { v: r.price, html: pts(r.price) },
    { v: r.value, html: val(r.value) }] }));
  return tableHTML(cols, rows, { compact: true, id: 'ft-ttab' });
}

function breakdownChart(elId, D) {
  const rows = D.filter(r => isNum(r.next) && F.comp[r.id]).sort((a, b) => a.next - b.next);
  if (!rows.length) { document.getElementById(elId).innerHTML = muted('No projection.'); return; }
  const ci = {};
  (F.comp_cols || []).forEach((c, i) => { ci[c] = i; });
  const keys = Object.keys(COMP).filter(k => ci[k] !== undefined && rows.some(r => Math.abs(F.comp[r.id][ci[k]] || 0) > 0.05));
  const narrow = (document.getElementById(elId).clientWidth || 600) < 520;
  const labels = rows.map(r => (narrow ? PD.driverCode(r.id) : r.name));
  const traces = keys.map(k => ({ type: 'bar', orientation: 'h', name: COMP[k][0], y: labels, x: rows.map(r => F.comp[r.id][ci[k]] || 0),
    marker: { color: COMP[k][1] }, hovertemplate: '%{y}<br>' + COMP[k][0] + ': %{x:.1f}<extra></extra>' }));
  traces.push({ type: 'scatter', mode: 'markers', name: 'Total', y: labels, x: rows.map(r => r.next), marker: { color: '#e6edf3', size: 7, symbol: 'diamond' },
    hovertemplate: '%{y}<br>Total: %{x:.1f}<extra></extra>' });
  document.getElementById(elId).style.height = Math.max(320, 22 * rows.length + 110) + 'px';
  plot(elId, traces, layout({ barmode: 'relative', showlegend: true, legend: { orientation: 'h', y: -0.06, yanchor: 'top', font: { color: C.text2, size: 10 } },
    margin: { l: narrow ? 44 : 130, r: 10, t: 10, b: 90 }, xaxis: { title: 'Expected points next weekend', zeroline: true }, yaxis: { automargin: true, tickfont: { size: 10 } } }));
}

function valueChart(elId, D) {
  const rows = D.filter(r => isNum(r.next) && isNum(r.price));
  if (!rows.length) { document.getElementById(elId).innerHTML = muted('No form line yet.'); return; }
  const all = rows.map(r => r.next).concat(rows.map(r => r.price));
  const lo = Math.min.apply(null, all) - 2, hi = Math.max.apply(null, all) + 2;
  plot(elId, [{ type: 'scatter', mode: 'lines', x: [lo, hi], y: [lo, hi], line: { color: '#6e7681', dash: 'dot', width: 1 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'markers+text', x: rows.map(r => r.price), y: rows.map(r => r.next), text: rows.map(r => PD.driverCode(r.id)), textposition: 'top center',
      textfont: { size: 9, color: C.text2 }, marker: { size: 9, color: rows.map(r => PD.teamColour(r.team)), line: { color: '#0d1117', width: 1 } },
      customdata: rows.map(r => [r.name, r.value]), hovertemplate: '%{customdata[0]}<br>form line %{x:.1f}, projection %{y:.1f} (value %{customdata[1]:+.1f})<extra></extra>' }],
    layout({ margin: { l: 55, r: 15, t: 10, b: 50 }, xaxis: { title: 'Form line (points per weekend so far)', range: [lo, hi] }, yaxis: { title: 'Projected next weekend', range: [lo, hi] } }));
}

function scheduleTable(kind) {
  const S = F.schedule || {};
  const rounds = S.rounds || [];
  if (!rounds.length) return muted('No rounds left.');
  const src = kind === 'teams' ? (S.teams || {}) : (S.drivers || {});
  const order = kind === 'teams' ? rowsOf(F.team_cols, F.teams).filter(r => src[r.id]).map(r => r.id) : rowsOf(F.driver_cols, F.drivers).filter(r => src[r.id]).map(r => r.id);
  return PD.charts.heatTable({
    corner: kind === 'teams' ? 'Constructor' : 'Driver',
    cols: rounds.map(r => ({ label: 'R' + r[0] + (r[2] ? ' S' : ''), title: (r[1] || '') + (r[2] ? ' (sprint weekend)' : '') })),
    rows: order.map(id => ({ label: kind === 'teams' ? PD.teamLink(id) : PD.driverLink(id, { code: true, team: ((F._byId || {})[id] || {}).team }), values: src[id],
      titles: rounds.map(r => (r[1] || '') + ': expected points') })),
    fmt: v => num(v, 1), center: 'col', invert: true
  });
}

function historyTable() {
  const H = F.history || {};
  const rounds = (H.rounds || []).slice(-10);
  if (!rounds.length) return muted('No rounds run yet this season.');
  const k = (H.rounds || []).length - rounds.length;
  const order = rowsOf(F.driver_cols, F.drivers).map(r => r.id).filter(id => (H.drivers || {})[id]);
  return PD.charts.heatTable({
    corner: 'Driver', cols: rounds.map(r => ({ label: 'R' + r[0], title: r[1] || '' })),
    rows: order.map(id => ({ label: PD.driverLink(id, { code: true, team: ((F._byId || {})[id] || {}).team }), values: H.drivers[id].slice(k), titles: rounds.map(r => r[1] || '') })),
    fmt: v => num(v, 0), center: 'col', invert: true
  });
}

function backtestCard() {
  const B = PD.ok(BT) && BT.metrics ? BT : null;
  const S = B ? null : (F.backtest && F.backtest.ok ? F.backtest : null);
  if (!B && !S) return card('Does it work? The backtest', '', '<div class="pad">' + PG().notBuilt('The fantasy backtest', BT) + '</div>');
  const M = B ? B.metrics : S;
  const seasons = B ? B.seasons : S.seasons;
  const span = seasons && seasons.length ? seasons[0] + '–' + seasons[seasons.length - 1] : '';
  const tbl = (g, title) => {
    const m = M[g];
    if (!m || !m.model) return '';
    const names = ['model', 'std', 'prev', 'last', 'blend'].filter(k => m[k]);
    const best = key => { let b = null; names.forEach(k => { const v = m[k][key]; if (isNum(v) && (b === null || (key === 'mae' ? v < b.v : v > b.v))) b = { k: k, v: v }; }); return b ? b.k : null; };
    const bm = best('mae'), bs = best('spearman'), bt = best('top5');
    const hl = (k, key, v, d) => (isNum(v) ? (k === key ? '<strong style="color:' + C.green + '">' + num(v, d) + '</strong>' : num(v, d)) : '—');
    return '<div class="ft-bt-h">' + esc(title) + ' <span class="muted-inline">' + (m.model.n || 0).toLocaleString() + ' ' + (g.indexOf('teams') === 0 ? 'constructor' : 'driver') + '-weekends, ' + (m.model.races || 0) + ' weekends</span></div>' +
      tableHTML([{ label: 'Method' }, { label: 'MAE', align: 'right', title: 'Mean absolute error, points per weekend (lower is better)' }, { label: 'Bias', align: 'right', title: 'Mean of projection minus actual' },
        { label: 'Rank corr.', align: 'right', title: 'Spearman rank correlation of projection and actual within each weekend, averaged over weekends' },
        { label: 'Top-5 overlap', align: 'right', title: 'Share of the actual top five the method had in its top five' }, { label: 'Top pick scored', align: 'right', title: 'Average actual points of the method\'s number one' },
        { label: '10–90% interval', align: 'right', title: 'Share of actual totals inside the floor-ceiling interval (target 80%)' }],
        names.map(k => [{ v: METHODS[k], html: (k === 'model' ? '<strong>' : '') + esc(METHODS[k]) + (k === 'model' ? '</strong>' : '') }, { v: m[k].mae, html: hl(k, bm, m[k].mae, 2) },
          { v: m[k].bias, html: isNum(m[k].bias) ? signed(m[k].bias, 2) : '—' }, { v: m[k].spearman, html: hl(k, bs, m[k].spearman, 3) }, { v: m[k].top5, html: hl(k, bt, m[k].top5, 2) },
          { v: m[k].top_pick, html: pts(m[k].top_pick) }, { v: m[k].coverage_80, html: isNum(m[k].coverage_80) ? pc(m[k].coverage_80) : '—' }]), { compact: true });
  };
  const dc = M.drivers_core || {};
  let read = '';
  if (dc.model && dc.std) {
    const gain = 100 * (1 - dc.model.mae / dc.std.mae);
    read = '<p>Over ' + (dc.model.races || 0) + ' weekends (' + esc(span) + '), projected before qualifying with only the data before each weekend, our projection misses a driver\'s weekend score by ' +
      num(dc.model.mae, 1) + ' points on average against ' + num(dc.std.mae, 1) + ' for the season-to-date average (' + num(gain, 0) + '% smaller), ' + num((dc.prev || {}).mae, 1) +
      ' for the previous weekend and ' + num((dc.last || {}).mae, 1) + ' for last season\'s average; it orders the field better too (rank correlation ' + num(dc.model.spearman, 2) + ' against ' + num(dc.std.spearman, 2) + ').' +
      ' A single weekend stays hard: retirements (−20), lap-one chaos and safety cars move scores by tens of points, which is why the floor–ceiling ranges are wide.</p>';
    if (B && B.pit && B.pit.model && B.pit.std) read += '<p>Pit-stop points are close to unpredictable from a team\'s history: ' + num(B.pit.model.mae, 2) + ' points MAE against ' + num(B.pit.std.mae, 2) + ' for its season-to-date average (' + B.pit.model.n + ' constructor-races with OpenF1 stationary times).</p>';
  }
  let h = '<div class="pad doc-body">' + read + '</div>' + tbl('drivers_core', 'Drivers, core scoring (all seasons; no overtakes or pit stops)') + tbl('drivers_full', 'Drivers, full scoring (' + ((B && B.full_from) || 2024) + ' on: overtakes included)') +
    tbl('teams_core', 'Constructors, core scoring') + tbl('teams_full', 'Constructors, full scoring (overtakes; pit points apart)');
  if (B && B.per_season) {
    const ys = Object.keys(B.per_season).sort().reverse();
    h += '<div class="ft-bt-h">By season <span class="muted-inline">drivers, core scoring</span></div>' + tableHTML([{ label: 'Season' }, { label: 'Weekends', align: 'right' }, { label: 'MAE ours', align: 'right' },
      { label: 'MAE season avg', align: 'right' }, { label: 'MAE previous', align: 'right' }, { label: 'MAE last season', align: 'right' }, { label: 'Rank corr. ours', align: 'right' }, { label: 'Rank corr. season avg', align: 'right' }],
      ys.map(y => { const m = (B.per_season[y] || {}).drivers_core || {}; const g = k => (m[k] || {}); return [y, g('model').races, { v: g('model').mae, html: '<strong>' + num(g('model').mae, 2) + '</strong>' }, num(g('std').mae, 2), num(g('prev').mae, 2),
        num(g('last').mae, 2), num(g('model').spearman, 3), num(g('std').spearman, 3)]; }), { compact: true });
  }
  if (B && (B.per_race || []).length) h += '<div id="ft-bt-races" style="height:300px"></div>';
  return card('Does it work? The walk-forward backtest', 'Every weekend ' + esc(span) + ' projected before qualifying with only the data before it, scored with the same table. Green: the best method.', h, 'ft-bt');
}

function drawBacktestChart() {
  const pr = (BT && BT.per_race) || [];
  const el = document.getElementById('ft-bt-races');
  if (!el || !pr.length) return;
  const roll = (arr, k) => arr.map((v, i) => { const s = arr.slice(Math.max(0, i - k + 1), i + 1).filter(isNum); return s.length ? s.reduce((a, b) => a + b, 0) / s.length : null; });
  const x = pr.map((r, i) => i), lab = pr.map(r => r[0] + ' R' + r[1]);
  const ticks = [], tt = [];
  pr.forEach((r, i) => { if (!i || r[0] !== pr[i - 1][0]) { ticks.push(i); tt.push(String(r[0]).slice(2)); } });
  plot(el, [{ type: 'scatter', mode: 'lines', name: 'Our projection', x: x, y: roll(pr.map(r => r[2]), 10), text: lab, line: { color: C.blue, width: 2 }, hovertemplate: '%{text}: %{y:.2f}<extra>ours, 10-weekend mean</extra>' },
    { type: 'scatter', mode: 'lines', name: 'Season-to-date average', x: x, y: roll(pr.map(r => r[3]), 10), text: lab, line: { color: C.orange, width: 1.5 }, hovertemplate: '%{text}: %{y:.2f}<extra>season average, 10-weekend mean</extra>' }],
    layout({ showlegend: true, legend: { orientation: 'h', y: 1.15, font: { color: C.text2 } }, margin: { l: 50, r: 10, t: 30, b: 40 }, xaxis: { tickvals: ticks, ticktext: tt, title: 'Season' },
      yaxis: { title: 'MAE, points (10-weekend mean)' } }));
}

function scoringCard() {
  const rows = (F.scoring || []).map(r => [{ v: r[0], html: '<strong>' + esc(r[0]) + '</strong>' }, esc(r[1]), { v: r[2], html: '<span class="ft-pts">' + esc(r[2]) + '</span>' }, { v: r[3], html: '<span class="muted-inline">' + esc(r[3]) + '</span>' }]);
  const ex = (F.excluded || []).map(r => '<li><strong>' + esc(r[0]) + '.</strong> ' + esc(r[1]) + '</li>').join('');
  return card('Our scoring table', 'Ours, in the usual shape of F1 fantasy games; computed from Jolpica results and OpenF1 records.',
    tableHTML([{ label: 'Part', sortable: false }, { label: 'Item', sortable: false }, { label: 'Points', sortable: false }, { label: 'Notes', sortable: false }], rows, { compact: true }) +
    '<div class="pad doc-body"><p><strong>Left out, and why:</strong></p><ul>' + ex + '</ul></div>', 'ft-scoring');
}

function render(el) {
  const y = PD.currentSeason();
  el.innerHTML = muted('Loading…');
  return PD.loadAll([y + '/fantasy.json', 'fantasy_backtest.json']).then(res => {
    if (!PG().alive(el)) return;
    F = res[0]; BT = res[1];
    if (!PD.ok(F) || !F.drivers) {
      el.innerHTML = card('Fantasy ' + y, '', '<div class="pad">' + PG().notBuilt('The ' + y + ' fantasy page', F) + '</div>');
      return;
    }
    const D = rowsOf(F.driver_cols, F.drivers), T = rowsOf(F.team_cols, F.teams);
    F._byId = {};
    D.forEach(r => { F._byId[r.id] = r; });
    F.names = F.names || { drivers: {}, teams: {} };
    const tById = {};
    T.forEach(r => { tById[r.id] = r; });
    const nx = F.next || {};
    const live = D.filter(r => isNum(r.next));
    let h = '<div class="page-head"><div><h2>Fantasy ' + y + '</h2><div class="ph-sub muted-inline">' +
      (F.projection_ok ? 'Next: ' + esc(nx.name || ('round ' + nx.round)) + ' (round ' + esc(nx.round) + ')' + (nx.sprint ? ', a sprint weekend' : '') +
        (nx.quali_known ? ' · qualifying is in: its points are actual' : ' · projected before qualifying') : esc(F.reason || 'No rounds left to project')) + '</div></div>' +
      '<div class="ph-nav"><a href="#/value">Driver value →</a> <a href="#/swap">Swap simulator →</a> <a href="#/methodology/fantasy">How it works →</a></div></div>';
    h += '<div class="pv-label">' + esc(F.label || '') + '</div>';
    const top = live.slice().sort((a, b) => b.next - a.next)[0];
    const bv = live.filter(r => isNum(r.value) && (r.next || 0) >= 5).sort((a, b) => b.value - a.value)[0];
    const bd = ((F.backtest || {}).drivers_core || {});
    h += '<div class="kpi-grid five">' + [
      statTile('Next weekend', esc(nx.name ? nx.name.replace(/ Grand Prix.*$/, '') : '—'), nx.round ? 'round ' + esc(nx.round) + (nx.sprint ? ' · sprint' : '') : ''),
      statTile('Top projection', top ? PD.driverLink(top.id, { code: true, team: top.team }) + ' <span class="kpi-dim">' + pts(top.next) + '</span>' : '—', top ? 'floor ' + pts(top.p10, 0) + ', ceiling ' + pts(top.p90, 0) : ''),
      statTile('Best value', bv ? PD.driverLink(bv.id, { code: true, team: bv.team }) + ' <span class="kpi-dim">' + signed(bv.value, 1) + '</span>' : '—', 'projection v form line'),
      statTile('Backtest MAE', bd.model ? num(bd.model.mae, 2) : '—', bd.std ? 'season average ' + num(bd.std.mae, 2) : ''),
      statTile('Rank correlation', bd.model ? num(bd.model.spearman, 2) : '—', bd.std ? 'season average ' + num(bd.std.spearman, 2) : '')
    ].join('') + '</div>';
    if (F.picks && Object.keys(F.picks).length) {
      h += card('Our suggested picks', 'Model suggestions from our own projections, with the reasons the numbers give. Not the official game\'s prices or ownership.',
        '<div class="ft-picks">' + PICK_GROUPS.map(g => pickCard(g[0], g[1], g[2], F.picks[g[0]], tById)).join('') + '</div>');
    }
    h += card('Drivers', 'Click a heading to sort. Projections from ' + (F.n ? Number(F.n).toLocaleString() + ' ' : '') + 'simulated seasons; value = projection minus the form line (our price proxy).',
      '<div class="pad ft-ctl">' + PG().toggle('ft-view', [['next', 'Next weekend'], ['ros', 'Rest of season']], ST.view) + '</div><div id="ft-dbox"></div>' +
      '<div class="pg-note">Floor and ceiling: the 10th and 90th percentiles of the simulated total (a retirement costs 20). Tiers: optimal breaks of the projection into five groups. Form line: season-to-date points per weekend blended with last season\'s average while the sample is small, (n × form + 3 × last) / (n + 3).</div>');
    h += '<div class="grid-2"><div class="card"><div class="card-header">Where the points come from <span class="card-sub">Expected points by item, next weekend; the diamond is the total.</span></div><div id="ft-break"></div></div>' +
      '<div class="card"><div class="card-header">Projection v form <span class="card-sub">Above the diagonal: we expect more than the form line says.</span></div><div id="ft-value" style="height:420px"></div></div></div>';
    h += card('Constructors', 'Both drivers plus qualifying progression and pit-stop bands.', teamTable(T));
    h += card('The schedule ahead', 'Expected points per remaining round, coloured against the round\'s median (green above). S = sprint weekend.',
      '<div class="pad ft-ctl">' + PG().toggle('ft-sched', [['drivers', 'Drivers'], ['teams', 'Constructors']], ST.sched) + '</div><div id="ft-sbox"></div>');
    h += card('Season so far', 'Actual points per weekend with our table, the last ten rounds; green above the round median.', historyTable());
    h += backtestCard();
    h += scoringCard();
    el.innerHTML = h;
    PD.setMeta('Fantasy · ' + y);
    const drawD = () => { document.getElementById('ft-dbox').innerHTML = driverTable(D); sortable('ft-dbox'); };
    const drawS = () => { document.getElementById('ft-sbox').innerHTML = scheduleTable(ST.sched); };
    drawD();
    drawS();
    sortable(el);
    PG().wireToggle(el, 'ft-view', v => { ST.view = v; drawD(); });
    PG().wireToggle(el, 'ft-sched', v => { ST.sched = v; drawS(); });
    breakdownChart('ft-break', D);
    valueChart('ft-value', D);
    drawBacktestChart();
  });
}

PD.route('fantasy', render);
})(window.PD);
