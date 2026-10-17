/* The Quant Paddock — races list (#/races/<y>), race centre (#/race/<y>/<r>) and
 * qualifying (#/race/<y>/<r>/quali).
 *
 * Upcoming race: the pre-qualifying forecast (and post-qualifying, sprint when
 * present), the position distribution, P(safety car).
 * Finished race: awards, results, forecast against result, lap-by-lap positions,
 * gaps, lap-time distributions beside corrected pace, tyre strategy, pit stops,
 * race control, weather, overtakes, degradation by compound.
 * Every section degrades to a muted line when its data is missing (no stints,
 * overtakes or race control before 2023, no laps before 1996). */
(function (PD) {
'use strict';

const esc = PD.esc;
const C = PD.C;
const set = (id, html) => { const n = document.getElementById(id); if (n) n.innerHTML = html; };
const has = o => !!o && (Array.isArray(o) ? o.length > 0 : Object.keys(o).length > 0);

function shortName(n) { return PD.season && PD.season.shortName ? PD.season.shortName(n) : String(n || '').replace(/ Grand Prix.*$/, ''); }

// ── races list ─────────────────────────────────────────────────────────────

function renderRaces(el, params) {
  const idx = PD.index() || {};
  const year = PD.isNum(params.year) ? Number(params.year) : PD.currentSeason();
  el.innerHTML = PD.muted('Loading ' + esc(year) + '…');
  return PD.load(year + '/season.json').then(season => {
    if (!el.isConnected) return;
    const head = PD.season ? PD.season.pageHead(year, year + ' races', '', idx.seasons || [year], 'races') : '<h2>' + esc(year) + ' races</h2>';
    if (!PD.ok(season)) { el.innerHTML = head + '<div class="stale-banner">The ' + esc(year) + ' calendar is not available: ' + esc(PD.reason(season)) + '.</div>'; return; }
    PD.setMeta(esc(year) + ' races · ' + season.rounds_done + '/' + season.rounds_total + ' run');
    const cal = season.calendar || [];
    const nxt = cal.find(c => c.status === 'next');
    el.innerHTML = head.replace('<div class="ph-sub"></div>', '<div class="ph-sub">' + season.rounds_done + ' of ' + season.rounds_total + ' rounds run' +
        (nxt ? ' · next: <a href="' + PD.raceHref(year, nxt.round) + '">' + esc(nxt.name) + '</a>, ' + esc(PD.fmtDate(nxt.date, { year: false })) : '') + '</div>') +
      PD.card('Calendar', 'Open a round for its race centre: forecast, results, laps, strategy and telemetry.', '<div id="races-cal"></div>');
    set('races-cal', PD.season ? PD.season.calendarTable(season, { fastest: true }) : PD.muted('Calendar unavailable.'));
    PD.sortable(document.getElementById('races-cal'));
  });
}

// ── shared race header ─────────────────────────────────────────────────────

function raceHead(race, season, view) {
  const y = race.year, r = race.round;
  const cal = PD.ok(season) ? (season.calendar || []) : [];
  const prev = cal.filter(c => c.round < r).sort((a, b) => b.round - a.round)[0];
  const next = cal.filter(c => c.round > r).sort((a, b) => a.round - b.round)[0];
  const calRow = cal.find(c => c.round === r) || {};
  const circ = race.circuit || calRow.circuit || {};
  const status = race.status === 'done' ? PD.chip('result', 'ok') : PD.chip(calRow.status === 'next' ? 'next race' : 'upcoming', 'info');
  const tabs = '<div class="seg-tabs">' +
    '<a href="' + PD.raceHref(y, r) + '" class="' + (view === 'race' ? 'active' : '') + '">Race</a>' +
    '<a href="' + PD.raceHref(y, r, 'quali') + '" class="' + (view === 'quali' ? 'active' : '') + '">Qualifying</a>' +
    '<a href="' + PD.raceHref(y, r, 'telemetry') + '">Telemetry lab</a>' +
    '<a href="#/races/' + y + '">All ' + y + ' races</a></div>';
  return '<div class="race-head"><div>' +
    '<div class="rh-kicker">' + esc(y) + ' · Round ' + esc(r) + (calRow.sprint ? ' · sprint weekend' : '') + '</div>' +
    '<div class="rh-name">' + esc(race.name || calRow.name || 'Round ' + r) + '</div>' +
    '<div class="rh-sub">' + (circ.id ? PD.circuitLink(circ.id, circ.name) : '') + (circ.locality ? ' · ' + esc(circ.locality) : '') + (circ.country ? ', ' + esc(circ.country) : '') +
      ' · ' + esc(PD.fmtDate(race.date || calRow.date)) + '</div></div>' +
    '<div class="rh-side"><div class="rh-chips">' + status + (race.telemetry && race.telemetry.race ? PD.chip('telemetry', '') : '') + '</div>' +
    '<div class="ph-nav">' + (prev ? '<a href="' + PD.raceHref(y, prev.round, view === 'quali' ? 'quali' : '') + '" title="' + esc(prev.name) + '">← ' + esc(shortName(prev.name)) + '</a>' : '<span class="disabled">←</span>') +
    (next ? '<a href="' + PD.raceHref(y, next.round, view === 'quali' ? 'quali' : '') + '" title="' + esc(next.name) + '">' + esc(shortName(next.name)) + ' →</a>' : '<span class="disabled">→</span>') + '</div></div></div>' + tabs;
}

/* Team of a driver at this race: results, qualifying, then the season, then the index. */
function teamMap(race, season) {
  const m = {};
  ((PD.ok(season) && season.standings && season.standings.drivers) || []).forEach(x => { if (x.team) m[x.driver] = x.team; });
  (race.qualifying || []).forEach(x => { if (x.team) m[x.driver] = x.team; });
  (race.sprint || []).forEach(x => { if (x.team) m[x.driver] = x.team; });
  (race.results || []).forEach(x => { if (x.team) m[x.driver] = x.team; });
  return m;
}

// ── forecast pieces ────────────────────────────────────────────────────────

function simTable(sim, teams) {
  const ds = (sim && sim.drivers) || {};
  const ids = Object.keys(ds).sort((a, b) => (ds[a].exp_pos - ds[b].exp_pos) || (ds[b].p_win - ds[a].p_win));
  if (!ids.length) return PD.muted('No forecast.');
  const maxW = Math.max(0.25, Math.max.apply(null, ids.map(id => ds[id].p_win || 0)));
  const hasPts = ids.some(id => PD.isNum(ds[id].exp_points));
  const rows = ids.map((id, i) => {
    const d = ds[id], t = teams[id] || (PD.NAMES.drivers[id] || {}).team;
    return { cells: [
      { v: i + 1, align: 'right', cls: 'muted-inline' },
      { v: PD.driverName(id), html: PD.driverLink(id, { team: t }) + '<span class="drv-code">' + esc(PD.teamName(t)) + '</span>' },
      { v: d.p_win, html: PD.probCell(d.p_win, PD.teamColour(t), maxW) },
      { v: d.p_podium, html: PD.pct(d.p_podium), align: 'right' },
      { v: d.p_points, html: PD.pct(d.p_points), align: 'right' },
      { v: d.p_dnf, html: PD.pct(d.p_dnf), align: 'right' },
      { v: d.exp_pos, html: PD.num(d.exp_pos, 1), align: 'right' }
    ].concat(hasPts ? [{ v: d.exp_points, html: PD.num(d.exp_points, 1), align: 'right' }] : []) };
  });
  return PD.tableHTML([{ label: '#', align: 'right' }, { label: 'Driver' }, { label: 'P(win)' }, { label: 'P(podium)', align: 'right' }, { label: 'P(points)', align: 'right' },
    { label: 'P(DNF)', align: 'right' }, { label: 'Exp. pos', align: 'right' }].concat(hasPts ? [{ label: 'Exp. pts', align: 'right' }] : []), rows, { compact: true });
}

function simHeatmap(elId, sim) {
  const ds = (sim && sim.drivers) || {};
  const ids = Object.keys(ds).sort((a, b) => ds[a].exp_pos - ds[b].exp_pos);
  PD.charts.posHeatmap(elId, ids.map(id => ({ label: PD.driverName(id), dist: ds[id].pos_dist || [] })), { zmax: 0.6, height: ids.length * 30.4 + 62 });
}

function forecastBlock(race, teams) {
  const f = race.forecast || {};
  const views = [];
  if (f.pre_quali && has(f.pre_quali.drivers)) views.push(['pre', 'Before qualifying', f.pre_quali]);
  if (f.post_quali && has(f.post_quali.drivers)) views.push(['post', 'After qualifying', f.post_quali]);
  if (race.sprint_forecast && has(race.sprint_forecast.drivers)) views.push(['sprint', 'Sprint', race.sprint_forecast]);
  return views;
}

function renderForecastCard(hostId, views, teams, title, startKey) {
  const host = document.getElementById(hostId);
  if (!host) return;
  if (!views.length) { host.innerHTML = PD.card(title, '', PD.muted('No forecast was built for this race.')); return; }
  const start = views.find(v => v[0] === startKey) || views[views.length - 1];
  host.innerHTML = '<div class="card"><div class="card-header">' + esc(title) + ' <span class="card-sub" id="' + hostId + '-sub"></span></div>' +
    (views.length > 1 ? '<div class="toggle-row">' + views.map(v => '<button class="tbtn' + (v === start ? ' active' : '') + '" data-k="' + v[0] + '">' + esc(v[1]) + '</button>').join('') + '</div>' : '') +
    '<div class="grid-32" style="gap:0"><div id="' + hostId + '-table"></div><div id="' + hostId + '-heat"></div></div></div>';
  const draw = v => {
    const sim = v[2];
    set(hostId + '-sub', esc(v[1]) + (PD.isNum(sim.p_sc) ? ' · P(safety car) ' + PD.pct(sim.p_sc, 0) : '') + (PD.isNum(sim.p_vsc) ? ' · P(VSC) ' + PD.pct(sim.p_vsc, 0) : '') + (PD.isNum(sim.p_wet) && sim.p_wet > 0.005 ? ' · P(wet) ' + PD.pct(sim.p_wet, 0) : ''));
    set(hostId + '-table', simTable(sim, teams));
    PD.sortable(document.getElementById(hostId + '-table'));
    simHeatmap(hostId + '-heat', sim);
  };
  draw(start);
  host.querySelectorAll('.tbtn').forEach(b => b.addEventListener('click', () => {
    host.querySelectorAll('.tbtn').forEach(x => x.classList.toggle('active', x === b));
    draw(views.find(v => v[0] === b.dataset.k));
  }));
}

// ── finished race sections ─────────────────────────────────────────────────

const AWARDS = [['driver_of_the_day', 'Driver of the day'], ['best_drive_from_back', 'Drive from the back'], ['best_strategy', 'Best strategy'],
  ['fastest_stop', 'Fastest stop'], ['overtake_of_race', 'Overtake of the race'], ['smoothest', 'Smoothest'], ['unluckiest', 'Unluckiest'], ['team_of_weekend', 'Team of the weekend']];

function awardsHTML(aw, teams) {
  const cards = AWARDS.filter(a => aw && aw[a[0]] && (aw[a[0]].driver || aw[a[0]].team)).map(a => {
    const x = aw[a[0]];
    const team = x.team || teams[x.driver];
    const who = x.driver ? PD.driverLink(x.driver, { team: team }) : PD.teamLink(x.team);
    return '<div class="award" style="border-top-color:' + esc(PD.teamColour(team)) + '"><span class="aw-title">' + esc(a[1]) + '</span><span class="aw-who">' + who + '</span>' +
      (x.label ? '<span class="aw-val">' + esc(x.label) + '</span>' : '') + (x.why ? '<span class="aw-why">' + esc(x.why) + '</span>' : '') + '</div>';
  });
  return cards.length ? '<div class="pad awards">' + cards.join('') + '</div>' : '';
}

function resultCells(x, winnerMs, teams, isSprint) {
  const delta = PD.isNum(x.grid) && x.grid > 0 && PD.isNum(x.pos) ? x.grid - x.pos : null;
  const classified = PD.isNum(x.time_ms) || /^(Finished|\+\d+ Laps?|Lapped)$/i.test(String(x.status || ''));
  let gap;
  if (x.pos === 1 && PD.isNum(x.time_ms)) gap = PD.fmtMs(x.time_ms);
  else if (PD.isNum(x.gap_ms) && x.gap_ms > 0) gap = PD.fmtGap(x.gap_ms);
  else if (/^\+\d+ Laps?$/i.test(String(x.status || ''))) gap = esc(x.status);
  else gap = '<span class="muted-inline">' + (PD.isNum(x.laps) ? 'out, lap ' + x.laps : '—') + '</span>';
  const fl = PD.isNum(x.fastest_ms) ? '<span class="' + (x.fastest_rank === 1 ? 'q-best' : '') + '">' + PD.fmtMs(x.fastest_ms) + '</span>' + (PD.isNum(x.fastest_rank) ? '<span class="drv-code">' + x.fastest_rank + '</span>' : '') : '—';
  const team = x.team || teams[x.driver];
  return [
    { v: PD.isNum(x.pos) ? x.pos : 99, html: classified || x.pos ? String(x.pos) : '—', align: 'right' },
    { v: PD.driverName(x.driver), html: PD.driverLink(x.driver, { team: team }) },
    { v: PD.teamName(team), html: '<span class="muted-inline">' + esc(PD.teamName(team)) + '</span>' },
    { v: x.grid, html: x.grid === 0 ? 'PL' : PD.isNum(x.grid) ? String(x.grid) : '—', align: 'right', title: x.grid === 0 ? 'Started from the pit lane' : '' },
    { v: delta, html: delta === null ? '—' : delta > 0 ? '<span class="pos-up">▲' + delta + '</span>' : delta < 0 ? '<span class="pos-down">▼' + (-delta) + '</span>' : '<span class="muted-inline">=</span>', align: 'right' },
    { v: x.status, html: /^Finished$/i.test(x.status || '') ? '<span class="muted-inline">Finished</span>' : esc(x.status || '—') },
    { v: x.points, html: x.points ? '<b>' + PD.num(x.points, x.points % 1 ? 1 : 0) + '</b>' : '<span class="muted-inline">0</span>', align: 'right' },
    { v: PD.isNum(x.time_ms) ? x.time_ms : (PD.isNum(x.gap_ms) ? winnerMs + x.gap_ms : 1e12 - (x.laps || 0)), html: gap, align: 'right' },
    { v: x.fastest_ms, html: fl, align: 'right' }
  ];
}

function resultsTable(results, teams, isSprint) {
  if (!has(results)) return PD.muted('No classification yet.');
  const win = results.find(x => x.pos === 1) || {};
  return PD.tableHTML([{ label: 'Pos', align: 'right' }, { label: 'Driver' }, { label: 'Team' }, { label: 'Grid', align: 'right' }, { label: '+/−', align: 'right', title: 'Places gained from the grid' },
    { label: 'Status' }, { label: 'Pts', align: 'right' }, { label: 'Time / gap', align: 'right' }, { label: 'Fastest lap', align: 'right', title: 'Best lap and its rank' }],
    results.slice().sort((a, b) => (a.pos || 99) - (b.pos || 99)).map(x => ({ cells: resultCells(x, win.time_ms || 0, teams, isSprint) })), { compact: true });
}

function expectedChart(elId, eva, results, teams) {
  const order = (results || []).slice().sort((a, b) => (a.pos || 99) - (b.pos || 99)).map(x => x.driver).filter(id => eva[id] && PD.isNum(eva[id].exp_pos));
  Object.keys(eva || {}).forEach(id => { if (order.indexOf(id) < 0 && PD.isNum(eva[id].exp_pos)) order.push(id); });
  if (!order.length) { set(elId, PD.muted('No forecast to compare with.')); return; }
  const ys = order.map(PD.driverCode);
  const segX = [], segY = [];
  order.forEach((id, i) => { segX.push(eva[id].exp_pos, eva[id].actual, null); segY.push(ys[i], ys[i], null); });
  // pctile_of_actual: 0-100 in the payloads (0-1 accepted too).
  const pc = id => { const v = eva[id].pctile_of_actual; return PD.isNum(v) ? (v <= 1 ? v * 100 : v) : null; };
  const pctTxt = id => (pc(id) !== null ? PD.ordinal(Math.round(pc(id))) + ' percentile' : '');
  const cols = order.map(id => PD.teamColour(teams[id]));
  PD.plot(elId, [
    { type: 'scatter', mode: 'lines', x: segX, y: segY, line: { color: '#30363d', width: 3 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'markers', name: 'Expected', x: order.map(id => eva[id].exp_pos), y: ys, marker: { size: 9, color: 'rgba(0,0,0,0)', line: { color: cols, width: 2 } },
      text: order.map(PD.driverName), hovertemplate: '%{text}: expected P%{x:.1f}<extra></extra>' },
    { type: 'scatter', mode: 'markers+text', name: 'Actual', x: order.map(id => eva[id].actual), y: ys, marker: { size: 9, color: cols },
      text: order.map(id => (pc(id) !== null ? Math.round(pc(id)) + '' : '')), textposition: 'middle right', textfont: { size: 9, color: C.text3 },
      customdata: order.map(id => PD.driverName(id) + ': finished P' + eva[id].actual + (pctTxt(id) ? ' · ' + pctTxt(id) + ' of the forecast' : '')),
      hovertemplate: '%{customdata}<extra></extra>' }
  ], PD.layout({
    height: Math.max(320, order.length * 21 + 70), showlegend: true, legend: { orientation: 'h', y: 1.06, x: 0, font: { color: C.text2 } },
    xaxis: { title: 'Position (hollow: expected, filled: actual; number: percentile of the actual result)', dtick: 2, range: [0, order.length + 2.5], zeroline: false },
    yaxis: { type: 'category', autorange: 'reversed', tickfont: { size: 10 }, fixedrange: true },
    margin: { l: 50, r: 15, t: 30, b: 50 }
  }));
}

function paceTable(pace, teams) {
  const ds = (pace && pace.drivers) || {};
  const ids = Object.keys(ds).filter(id => PD.isNum(ds[id].pace)).sort((a, b) => ds[a].pace - ds[b].pace);
  if (!ids.length) return PD.muted('No corrected pace for this race.');
  return PD.tableHTML([{ label: '#', align: 'right' }, { label: 'Driver' }, { label: 'Pace', align: 'right', title: 'Seconds per lap against the field mean, corrected for fuel, tyres and traffic; negative is faster' },
    { label: '±', align: 'right', title: 'Standard error' }, { label: 'Laps', align: 'right' }, { label: 'Traffic', align: 'right', title: 'Seconds lost in dirty air' }],
    ids.map((id, i) => ({ cells: [{ v: i + 1, align: 'right' }, { v: PD.driverName(id), html: PD.driverLink(id, { team: teams[id], name: PD.driverCode(id) }) },
      { v: ds[id].pace, html: '<span class="' + (ds[id].pace < 0 ? 'edge-pos' : 'edge-neg') + '">' + PD.signed(ds[id].pace, 3) + '</span>', align: 'right' },
      { v: ds[id].se, html: PD.num(ds[id].se, 3), align: 'right' }, { v: ds[id].laps, align: 'right' },
      { v: ds[id].traffic_cost, html: PD.isNum(ds[id].traffic_cost) ? PD.num(ds[id].traffic_cost, 1) + 's' : '—', align: 'right' }] })), { compact: true }) +
    '<div class="section-note">Seconds per lap against the field, corrected for fuel' + (PD.isNum(pace.fuel_coef) ? ' (' + PD.num(pace.fuel_coef, 3) + ' s/lap per lap)' : '') + ', tyres and traffic. Negative is faster.</div>';
}

function degTable(pace, teams) {
  const ds = (pace && pace.drivers) || {};
  const comps = [];
  Object.keys(ds).forEach(id => Object.keys(ds[id].deg || {}).forEach(c => { if (comps.indexOf(c) < 0) comps.push(c); }));
  const ORDER = ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'];
  comps.sort((a, b) => ORDER.indexOf(a.toUpperCase()) - ORDER.indexOf(b.toUpperCase()));
  const ids = Object.keys(ds).filter(id => has(ds[id].deg)).sort((a, b) => (ds[a].pace || 0) - (ds[b].pace || 0));
  if (!comps.length || !ids.length) return PD.muted('No degradation estimates for this race.');
  return PD.charts.heatTable({
    corner: 'Driver', cols: comps.map(c => ({ label: c.charAt(0) + c.slice(1).toLowerCase() })),
    rows: ids.map(id => ({ label: PD.driverLink(id, { team: teams[id] }), values: comps.map(c => (ds[id].deg || {})[c]) })),
    fmt: v => PD.signed(v, 3), scale: 'div', center: 'col', maxWidth: 640
  }) + '<div class="section-note">Seconds per lap lost per lap of tyre age, by compound. Coloured against each compound’s median driver: green degrades least.</div>';
}

function pitSection(pits, teams) {
  const list = (pits || []).filter(p => p && p.driver);
  if (!list.length) return { table: PD.muted('No pit stops recorded.'), stops: [] };
  const rows = list.slice().sort((a, b) => (a.lap - b.lap) || ((a.stop_ms || 9e9) - (b.stop_ms || 9e9)));
  const best = Math.min.apply(null, list.filter(p => PD.isNum(p.stop_ms)).map(p => p.stop_ms));
  const table = PD.tableHTML([{ label: 'Driver' }, { label: 'Lap', align: 'right' }, { label: 'Stationary', align: 'right' }, { label: 'Pit lane', align: 'right', title: 'Total time in the pit lane' }],
    rows.map(p => ({ cells: [{ v: PD.driverName(p.driver), html: PD.driverLink(p.driver, { team: teams[p.driver] }) }, { v: p.lap, align: 'right' },
      { v: p.stop_ms, html: PD.isNum(p.stop_ms) ? '<span class="' + (p.stop_ms === best ? 'q-best' : '') + '">' + PD.num(p.stop_ms / 1000, 2) + 's</span>' : '—', align: 'right' },
      { v: p.lane_ms, html: PD.isNum(p.lane_ms) ? PD.num(p.lane_ms / 1000, 1) + 's' : '—', align: 'right' }] })), { compact: true });
  return { table: '<div style="max-height:420px;overflow-y:auto">' + table + '</div>', stops: list };
}

function stopChart(elId, stops, teams) {
  const s = stops.filter(p => PD.isNum(p.stop_ms) || PD.isNum(p.lane_ms));
  if (!s.length) { set(elId, PD.muted('No stop times.')); return; }
  const useStop = s.some(p => PD.isNum(p.stop_ms));
  const key = useStop ? 'stop_ms' : 'lane_ms';
  const sorted = s.filter(p => PD.isNum(p[key])).sort((a, b) => a[key] - b[key]);
  PD.plot(elId, [{
    type: 'bar', x: sorted.map((p, i) => i + 1), y: sorted.map(p => p[key] / 1000), marker: { color: sorted.map(p => PD.teamColour(teams[p.driver])) },
    text: sorted.map(p => PD.driverCode(p.driver)), textposition: 'outside', textfont: { size: 8, color: C.text2 }, cliponaxis: false,
    customdata: sorted.map(p => PD.driverName(p.driver) + ', lap ' + p.lap), hovertemplate: '%{customdata}: %{y:.2f}s<extra></extra>'
  }], PD.layout({
    height: 300, bargap: 0.2,
    xaxis: { title: 'Stops, fastest first', showticklabels: false, fixedrange: true },
    yaxis: { title: useStop ? 'Stationary time (s)' : 'Pit lane time (s)', rangemode: 'tozero', fixedrange: true },
    margin: { l: 55, r: 10, t: 20, b: 35 }
  }));
}

const RC_ROWS = ['Neutralised', 'Flags', 'Penalties', 'Other'];
function controlTimeline(elId, control, nLaps) {
  const ev = (control || []).filter(e => e && PD.isNum(e.lap) && e.lap >= 1);
  if (!ev.length) { set(elId, PD.muted('No race control messages for this race.')); return; }
  const bands = PD.charts.controlBands(ev.filter(e => !/CHEQUERED/i.test(e.message || '')), nLaps);
  const rowOf = e => (e.kind === 'SC' || e.kind === 'VSC' || e.kind === 'RED' ? 'Neutralised' : e.kind === 'FLAG' ? 'Flags' : e.kind === 'PENALTY' ? 'Penalties' : 'Other');
  const colOf = e => {
    const m = String(e.message || '').toUpperCase();
    if (e.kind === 'RED' || /RED FLAG/.test(m) && !/CHEQUERED/.test(m)) return C.red;
    if (e.kind === 'SC' || e.kind === 'VSC' || /YELLOW/.test(m)) return C.yellow;
    if (/GREEN|CLEAR/.test(m)) return C.green;
    if (/BLUE/.test(m)) return C.blue;
    if (e.kind === 'PENALTY') return C.orange;
    return C.text2;
  };
  const jitter = {};
  const traces = RC_ROWS.map(row => {
    const list = ev.filter(e => rowOf(e) === row);
    return { type: 'scatter', mode: 'markers', name: row, x: list.map(e => { const k = row + e.lap; jitter[k] = (jitter[k] || 0) + 1; return e.lap + Math.min(0.4, (jitter[k] - 1) * 0.08); }),
      y: list.map(() => row), marker: { size: 8, color: list.map(colOf), symbol: row === 'Penalties' ? 'diamond' : 'circle', line: { color: '#0d1117', width: 1 } },
      text: list.map(e => 'Lap ' + e.lap + ': ' + esc(e.message || e.kind)), hovertemplate: '%{text}<extra></extra>' };
  }).filter(t => t.x.length);
  PD.plot(elId, traces, PD.layout({
    height: 230, xaxis: { title: 'Lap', range: [0.5, (nLaps || Math.max.apply(null, ev.map(e => e.lap))) + 0.5], zeroline: false },
    yaxis: { type: 'category', categoryorder: 'array', categoryarray: RC_ROWS.slice().reverse(), fixedrange: true, tickfont: { size: 10 } },
    shapes: PD.charts.bandShapes(bands), margin: { l: 85, r: 15, t: 15, b: 45 }
  }));
}

function controlList(control) {
  const key = (control || []).filter(e => e && (e.kind === 'SC' || e.kind === 'VSC' || e.kind === 'RED' || e.kind === 'PENALTY' ||
    /INVESTIGATION|DELETED|DRS (EN|DIS)ABLED|RED FLAG|CHEQUERED/i.test(e.message || '')));
  if (!key.length) return PD.muted('No neutralisations or penalties.');
  return '<div class="rc-list">' + key.map(e => '<div class="rc-item"><span class="rc-lap">Lap ' + esc(e.lap) + '</span><span>' +
    PD.chip(e.kind, e.kind === 'RED' ? 'red' : e.kind === 'SC' || e.kind === 'VSC' ? 'sc' : e.kind === 'PENALTY' ? 'warn' : '') + '</span><span class="rc-msg">' + esc(e.message || '') + '</span></div>').join('') + '</div>';
}

function weatherChart(elId, weather) {
  const w = (weather || []).filter(x => x && PD.isNum(x.t_ms)).sort((a, b) => a.t_ms - b.t_ms);
  if (w.length < 2) { set(elId, PD.muted('No weather readings for this race.')); return; }
  const x = w.map(r => r.t_ms / 60000);
  const traces = [
    { type: 'scatter', mode: 'lines', name: 'Track °C', x: x, y: w.map(r => (r.track > 0 ? r.track : null)), line: { color: C.orange, width: 2 }, connectgaps: true, hovertemplate: 'Track %{y:.1f}°C at %{x:.0f} min<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: 'Air °C', x: x, y: w.map(r => r.air), line: { color: C.blue, width: 2 }, hovertemplate: 'Air %{y:.1f}°C at %{x:.0f} min<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: 'Wind m/s', x: x, y: w.map(r => r.wind), yaxis: 'y2', line: { color: C.text3, width: 1, dash: 'dot' }, hovertemplate: 'Wind %{y:.1f} m/s<extra></extra>' }
  ];
  const rain = w.filter(r => r.rain);
  const shapes = rain.map(r => ({ type: 'rect', xref: 'x', yref: 'paper', x0: r.t_ms / 60000 - 0.5, x1: r.t_ms / 60000 + 0.5, y0: 0, y1: 1, fillcolor: 'rgba(0,103,173,0.35)', line: { width: 0 }, layer: 'below' }));
  shapes.push({ type: 'line', xref: 'x', yref: 'paper', x0: 0, x1: 0, y0: 0, y1: 1, line: { color: C.text3, width: 1, dash: 'dot' } });
  PD.plot(elId, traces, PD.layout({
    height: 230, showlegend: true, legend: { orientation: 'h', y: 1.15, x: 0, font: { color: C.text2, size: 10 } },
    xaxis: { title: 'Minutes from the start' + (rain.length ? ' (blue: rain)' : ''), zeroline: false },
    yaxis: { title: '°C' }, yaxis2: { overlaying: 'y', side: 'right', showgrid: false, title: 'm/s', rangemode: 'tozero', gridcolor: '#21262d' },
    shapes: shapes, margin: { l: 45, r: 45, t: 25, b: 45 }
  }));
}

function overtakesChart(elId, overtakes, control, nLaps) {
  const ov = (overtakes || []).filter(o => o && PD.isNum(o.lap));
  if (!ov.length) { set(elId, PD.muted('No overtake data for this race (tracked from 2023).')); return; }
  const n = nLaps || Math.max.apply(null, ov.map(o => o.lap));
  const counts = new Array(n + 1).fill(0);
  const who = {};
  ov.forEach(o => { if (o.lap <= n) { counts[o.lap]++; (who[o.lap] = who[o.lap] || []).push(PD.driverCode(o.by) + ' on ' + PD.driverCode(o.on) + (o.pos ? ' for P' + o.pos : '')); } });
  const laps = counts.map((_, i) => i).slice(1);
  PD.plot(elId, [{
    type: 'bar', x: laps, y: laps.map(l => counts[l]), marker: { color: C.blue },
    text: laps.map(l => (who[l] || []).slice(0, 8).join('<br>') + ((who[l] || []).length > 8 ? '<br>…' : '')), hovertemplate: 'Lap %{x}: %{y} overtakes<br>%{text}<extra></extra>', textposition: 'none'
  }], PD.layout({
    height: 230, bargap: 0.15, xaxis: { title: 'Lap', range: [0.5, n + 0.5] }, yaxis: { title: 'Overtakes', rangemode: 'tozero' },
    shapes: PD.charts.bandShapes(PD.charts.controlBands((control || []).filter(e => !/CHEQUERED/i.test(e.message || '')), n)), margin: { l: 50, r: 10, t: 15, b: 45 }
  }));
}

// ── the race page ──────────────────────────────────────────────────────────

function loadRace(params) {
  const y = params.year, r = params.round;
  return Promise.all([PD.load(y + '/races/' + r + '.json'), PD.load(y + '/season.json')]);
}

function missingRace(el, params, race, season) {
  const cal = PD.ok(season) ? (season.calendar || []).find(c => c.round === params.round) : null;
  const stub = { year: params.year, round: params.round, name: cal ? cal.name : 'Round ' + params.round, date: cal ? cal.date : null, circuit: cal ? cal.circuit : {}, status: cal && cal.status === 'done' ? 'done' : 'upcoming' };
  el.innerHTML = raceHead(stub, season, 'race') +
    '<div class="stale-banner">The race centre for this round is not available: ' + esc(PD.reason(race)) + '.</div>' +
    (cal && cal.winner ? PD.card('Result', '', '<div class="pad">Winner ' + PD.driverLink(cal.winner) + (cal.pole ? ' · pole ' + PD.driverLink(cal.pole) : '') + '</div>') : '');
}

function renderRace(el, params) {
  el.innerHTML = PD.muted('Loading the race centre…');
  return loadRace(params).then(arr => {
    if (!el.isConnected) return;
    const race = arr[0], season = arr[1];
    if (!PD.ok(race)) { missingRace(el, params, race, season); return; }
    const teams = teamMap(race, season);
    PD.setMeta(esc(race.year) + ' · ' + esc(race.name));
    document.title = race.name + ' ' + race.year + ' · The Quant Paddock';
    if (race.status !== 'done' || !has(race.results)) renderUpcoming(el, race, season, teams);
    else renderDone(el, race, season, teams);
  });
}

function renderUpcoming(el, race, season, teams) {
  const views = forecastBlock(race, teams);
  const pre = views.find(v => v[0] === 'pre'), post = views.find(v => v[0] === 'post');
  const main = post || pre;
  const ds = main ? main[2].drivers : {};
  const fav = Object.keys(ds || {}).sort((a, b) => ds[b].p_win - ds[a].p_win)[0];
  const idx = PD.index() || {};
  const isNext = idx.next && idx.next.year === race.year && idx.next.round === race.round;
  let sessions = isNext && PD.hub ? PD.hub.sessionsOf(idx.next) : [];
  if (!sessions.length && race.schedule && PD.hub) {
    const sch = Object.assign({}, race.schedule);
    if (race.date && !sch.race) sch.race = race.date + 'T' + (race.time || '12:00:00Z');
    sessions = PD.hub.sessionsOf({ sessions: sch });
  }
  const tiles = '<div class="kpi-grid">' +
    PD.statTile('Favourite', fav ? PD.driverLink(fav, { team: teams[fav] }) : '—', fav ? PD.pct(ds[fav].p_win) + ' to win' : '') +
    PD.statTile('P(safety car)', main && PD.isNum(main[2].p_sc) ? PD.pct(main[2].p_sc, 0) : '—', main && PD.isNum(main[2].p_vsc) ? 'VSC ' + PD.pct(main[2].p_vsc, 0) : 'at least one deployment') +
    PD.statTile('Grid', post ? 'Set' : 'Not yet', post ? 'forecast updated after qualifying' : 'forecast before qualifying') +
    PD.statTile('Race start', sessions.length ? esc(PD.fmtTime((sessions.find(s => s.key === 'race') || {}).iso) || '—') : esc(PD.fmtDate(race.date, { year: false })), sessions.length ? esc(PD.fmtDate((sessions.find(s => s.key === 'race') || {}).iso, { year: false })) + ', your time' : '') +
    '</div>';
  const sched = sessions.length ? PD.card('Weekend schedule', 'In your timezone.', '<div class="pad sched">' + sessions.map(s =>
    '<div class="sched-row' + (s.t.getTime() < Date.now() ? ' past' : '') + '"><span class="sched-day">' + esc(PD.fmtDate(s.iso, { year: false })) + '</span><span class="sched-name">' + esc(s.label) + '</span><span class="sched-time">' + esc(PD.fmtTime(s.iso)) + '</span></div>').join('') + '</div>') : '';
  el.innerHTML = raceHead(race, season, 'race') + tiles +
    '<div id="race-forecast"></div>' + sched +
    (race.forecast && race.forecast.generated_at ? '<div class="section-note">Forecast generated ' + esc(PD.fmtStamp(race.forecast.generated_at)) + '.</div>' : '');
  renderForecastCard('race-forecast', views, teams, 'Forecast', post ? 'post' : 'pre');
}

function renderDone(el, race, season, teams) {
  const res = race.results.slice().sort((a, b) => (a.pos || 99) - (b.pos || 99));
  const order = res.map(x => x.driver);
  const winner = res[0];
  const q = (race.qualifying || []).slice().sort((a, b) => a.pos - b.pos)[0];
  const fl = res.filter(x => PD.isNum(x.fastest_ms)).sort((a, b) => a.fastest_ms - b.fastest_ms)[0];
  const laps = race.laps || {};
  const nLaps = laps.n || (winner && winner.laps) || null;
  const bands = PD.charts.controlBands((race.control || []).filter(e => !/CHEQUERED/i.test(e.message || '')), nLaps);
  const scCount = bands.filter(b => b.kind === 'SC').length, vscCount = bands.filter(b => b.kind === 'VSC').length, redCount = bands.filter(b => b.kind === 'RED').length;
  const pre = race.forecast && race.forecast.pre_quali && race.forecast.pre_quali.drivers;
  const fav = pre ? Object.keys(pre).sort((a, b) => pre[b].p_win - pre[a].p_win)[0] : null;
  const winnerP = pre && winner && pre[winner.driver] ? pre[winner.driver].p_win : null;
  const tiles = '<div class="kpi-grid five">' +
    PD.statTile('Winner', winner ? PD.driverLink(winner.driver, { team: teams[winner.driver] }) : '—', winner ? (winner.grid ? 'from P' + winner.grid : '') + (PD.isNum(winnerP) ? ' · model gave ' + PD.pct(winnerP) : '') : '') +
    PD.statTile('Pole', q ? PD.driverLink(q.driver, { team: teams[q.driver] }) : '—', q ? PD.fmtMs(q.q3 || q.q2 || q.q1) : '') +
    PD.statTile('Fastest lap', fl ? PD.driverLink(fl.driver, { team: teams[fl.driver] }) : '—', fl ? PD.fmtMs(fl.fastest_ms) : '') +
    PD.statTile('Neutralisations', has(race.control) ? String(scCount + vscCount + redCount) : '—', has(race.control) ? [scCount + ' SC', vscCount + ' VSC'].concat(redCount ? [redCount + ' red'] : []).join(' · ') : 'no race control data') +
    PD.statTile('Forecast favourite', fav ? PD.driverLink(fav, { team: teams[fav] }) : '—', fav ? PD.pct(pre[fav].p_win) + ' · finished ' + (function () { const r = res.find(x => x.driver === fav); return r ? 'P' + r.pos : '—'; })() : 'no pre-race forecast') +
    '</div>';
  const awards = awardsHTML(race.awards, teams);
  const hasLaps = has(laps.positions);
  const noLapsNote = race.year < 1996 ? 'Lap-by-lap data starts in 1996.' : 'No lap data for this race.';
  const legendComp = '<div class="legend-row">' + ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET'].map(c => '<span><span class="legend-sw" style="background:' + PD.compoundColour(c) + '"></span>' + c.charAt(0) + c.slice(1).toLowerCase() + '</span>').join('') + '</div>';

  el.innerHTML = raceHead(race, season, 'race') + tiles +
    (awards ? PD.card('Awards', 'The model’s picks of the race.', awards) : '') +
    '<div class="grid-32">' +
      PD.card('Result', race.sprint && race.sprint.length ? '<a href="#race-sprint-card">Sprint result below</a>' : '', '<div id="race-results"></div>') +
      PD.card('Forecast v result', 'Where the model expected each driver against where they finished.', '<div id="race-eva"></div>') +
    '</div>' +
    PD.card('Positions lap by lap', 'Team colours; the second driver of a team is dotted. Bands mark safety cars (amber) and red flags.', '<div id="race-pos">' + (hasLaps ? '' : PD.muted(noLapsNote)) + '</div>') +
    PD.card('Gap to the leader', 'Seconds behind the leader at the end of each lap; the scale is cut so the fight at the front stays readable.', '<div id="race-gap">' + (hasLaps ? '' : PD.muted(noLapsNote)) + '</div>') +
    '<div class="grid-32">' +
      '<div class="card"><div class="card-header">Lap times <span class="card-sub">Green-flag laps within 107% of each driver’s median; lap 1 and pit laps dropped.</span></div>' +
        '<div class="toggle-row" id="race-lt-toggle"><button class="tbtn active" data-k="violin">Violin</button><button class="tbtn" data-k="box">Box</button></div><div id="race-lt"></div></div>' +
      PD.card('Corrected pace', 'From the race lap-time model.', '<div id="race-pace"></div>') +
    '</div>' +
    PD.card('Tyre strategy', 'Stints by compound; hover a stint for its laps.', legendComp + '<div id="race-stints"></div>') +
    '<div class="grid-2">' +
      PD.card('Pit stops', '', '<div id="race-pits"></div>') +
      PD.card('Stop times', 'Every stop, fastest first, in team colours.', '<div id="race-stopchart"></div>') +
    '</div>' +
    '<div class="grid-32">' +
      PD.card('Race control', 'Messages on the lap axis; bands mark neutralisations.', '<div id="race-rc"></div>') +
      PD.card('Key messages', '', '<div id="race-rc-list"></div>') +
    '</div>' +
    '<div class="grid-2">' +
      PD.card('Weather', '', '<div id="race-weather"></div>') +
      PD.card('Overtakes by lap', '', '<div id="race-ot"></div>') +
    '</div>' +
    PD.card('Degradation by compound', '', '<div id="race-deg"></div>') +
    (race.sprint && race.sprint.length ? '<div id="race-sprint-card">' + PD.card('Sprint result', '', '<div id="race-sprint"></div>') + '</div>' : '') +
    '<div id="race-preforecast"></div>';

  set('race-results', resultsTable(res, teams));
  PD.sortable(document.getElementById('race-results'));
  expectedChart('race-eva', race.expected_v_actual || {}, res, teams);
  if (hasLaps) {
    // The final lap follows the official classification (timing-derived orders can
    // disagree with it on the last lap).
    const fixed = Object.assign({}, laps, { positions: {} });
    Object.keys(laps.positions).forEach(id => { fixed.positions[id] = laps.positions[id].slice(); });
    res.forEach(x => {
      const ps = fixed.positions[x.driver];
      if (ps && PD.isNum(x.pos) && x.laps && ps.length >= x.laps && x.laps === nLaps) ps[x.laps - 1] = x.pos;
    });
    PD.charts.positionChart('race-pos', fixed, { order: order, teams: teams, control: race.control });
    PD.charts.gapChart('race-gap', laps, { order: order, teams: teams, control: race.control });
  }
  const lt = kind => PD.charts.lapTimeViolin('race-lt', laps, { order: order, teams: teams, kind: kind, pits: race.pits });
  if (has(laps.times)) {
    lt('violin');
    const box = document.getElementById('race-lt-toggle');
    box.querySelectorAll('.tbtn').forEach(b => b.addEventListener('click', () => { box.querySelectorAll('.tbtn').forEach(x => x.classList.toggle('active', x === b)); lt(b.dataset.k); }));
  } else { set('race-lt', PD.muted(noLapsNote)); const tg = document.getElementById('race-lt-toggle'); if (tg) tg.style.display = 'none'; }
  set('race-pace', paceTable(race.pace, teams));
  PD.sortable(document.getElementById('race-pace'));
  if (has(race.stints)) PD.charts.stintChart('race-stints', race.stints, { order: order, nLaps: nLaps, teams: teams });
  else set('race-stints', PD.muted(race.year < 2023 ? 'Tyre stints are tracked from 2023.' : 'No tyre stints for this race.'));
  const ps = pitSection(race.pits, teams);
  set('race-pits', ps.table);
  PD.sortable(document.getElementById('race-pits'));
  if (ps.stops.length) stopChart('race-stopchart', ps.stops, teams); else set('race-stopchart', PD.muted('No stop times.'));
  if (has(race.control)) { controlTimeline('race-rc', race.control, nLaps); set('race-rc-list', controlList(race.control)); }
  else { set('race-rc', PD.muted(race.year < 2023 ? 'Race control messages are tracked from 2023.' : 'No race control messages.')); set('race-rc-list', PD.muted('—')); }
  weatherChart('race-weather', race.weather);
  overtakesChart('race-ot', race.overtakes, race.control, nLaps);
  set('race-deg', degTable(race.pace, teams));
  if (race.sprint && race.sprint.length) { set('race-sprint', resultsTable(race.sprint, teams, true)); PD.sortable(document.getElementById('race-sprint')); }
  const views = forecastBlock(race, teams);
  if (views.length) renderForecastCard('race-preforecast', views, teams, 'The forecast before the race', views.find(v => v[0] === 'post') ? 'post' : 'pre');
}

// ── qualifying ─────────────────────────────────────────────────────────────

function renderQuali(el, params) {
  el.innerHTML = PD.muted('Loading qualifying…');
  return loadRace(params).then(arr => {
    if (!el.isConnected) return;
    const race = arr[0], season = arr[1];
    if (!PD.ok(race)) { missingRace(el, params, race, season); return; }
    const teams = teamMap(race, season);
    PD.setMeta(esc(race.year) + ' · ' + esc(race.name) + ' · qualifying');
    document.title = race.name + ' ' + race.year + ' qualifying · The Quant Paddock';
    const ql = (race.qualifying || []).slice().sort((a, b) => a.pos - b.pos);
    if (!ql.length) {
      el.innerHTML = raceHead(race, season, 'quali') + PD.card('Qualifying', '', PD.muted(race.status === 'done' ? 'No qualifying classification for this race.' : 'Qualifying has not run yet.'));
      return;
    }
    const fmtQ = v => (PD.isNum(v) ? PD.fmtMs(v) : (v ? esc(v) : '—'));
    const best = k => Math.min.apply(null, ql.map(x => (PD.isNum(x[k]) ? x[k] : Infinity)));
    const b1 = best('q1'), b2 = best('q2'), b3 = best('q3');
    const hasQ2 = isFinite(b2), hasQ3 = isFinite(b3);
    const outIn = x => (hasQ3 && PD.isNum(x.q3) ? null : hasQ2 && PD.isNum(x.q2) ? 'Q2' : hasQ2 || hasQ3 ? 'Q1' : null);
    const rows = [];
    let prevOut = null;
    ql.forEach(x => {
      const out = outIn(x);
      const cut = out !== prevOut && rows.length > 0;
      prevOut = out;
      const cell = (k, b) => ({ v: x[k], html: '<span class="' + (PD.isNum(x[k]) && x[k] === b ? 'q-best' : '') + '">' + fmtQ(x[k]) + '</span>', align: 'right' });
      rows.push({ _class: (out ? 'q-out' : '') + (cut ? ' q-cut' : ''), cells: [
        { v: x.pos, align: 'right' },
        { v: PD.driverName(x.driver), html: PD.driverLink(x.driver, { team: x.team || teams[x.driver] }) },
        { v: PD.teamName(x.team || teams[x.driver]), html: '<span class="muted-inline">' + esc(PD.teamName(x.team || teams[x.driver])) + '</span>' },
        cell('q1', b1), cell('q2', b2), cell('q3', b3),
        { v: x.gap_ms_to_pole, html: x.pos === 1 ? '<span class="muted-inline">pole</span>' : PD.isNum(x.gap_ms_to_pole) ? PD.fmtGap(x.gap_ms_to_pole) : '—', align: 'right' },
        { v: x.teammate_gap_ms, html: PD.isNum(x.teammate_gap_ms) ? '<span class="' + (x.teammate_gap_ms <= 0 ? 'edge-pos' : 'edge-neg') + '">' + (x.teammate_gap_ms <= 0 ? '−' + PD.fmtMs(-x.teammate_gap_ms) : '+' + PD.fmtMs(x.teammate_gap_ms)) + '</span>' : '—', align: 'right' },
        { v: out || 'Q3', html: out ? PD.chip('out in ' + out, '') : (hasQ3 ? PD.chip('Q3', 'info') : '') }
      ] });
    });
    const pole = ql[0];
    const tm = ql.filter(x => PD.isNum(x.teammate_gap_ms));
    el.innerHTML = raceHead(race, season, 'quali') +
      '<div class="kpi-grid">' +
        PD.statTile('Pole', PD.driverLink(pole.driver, { team: pole.team || teams[pole.driver] }), fmtQ(pole.q3 || pole.q2 || pole.q1)) +
        PD.statTile('Front row', ql[1] ? PD.driverLink(ql[1].driver, { team: ql[1].team || teams[ql[1].driver] }) : '—', ql[1] && PD.isNum(ql[1].gap_ms_to_pole) ? PD.fmtGap(ql[1].gap_ms_to_pole) + ' to pole' : '') +
        PD.statTile('Top-10 spread', ql[9] && PD.isNum(ql[9].gap_ms_to_pole) ? PD.fmtGap(ql[9].gap_ms_to_pole) : '—', 'P1 to P10') +
        PD.statTile('Closest teammates', tm.length ? (function () { const m = tm.slice().sort((a, b) => Math.abs(a.teammate_gap_ms) - Math.abs(b.teammate_gap_ms))[0]; return esc(PD.teamName(m.team || teams[m.driver])); })() : '—',
          tm.length ? PD.fmtMs(Math.abs(tm.slice().sort((a, b) => Math.abs(a.teammate_gap_ms) - Math.abs(b.teammate_gap_ms))[0].teammate_gap_ms)) + 's apart' : '') +
      '</div>' +
      '<div class="grid-32">' +
        PD.card('Qualifying', 'Purple: fastest in each segment. Dashed lines mark the knockouts.', '<div id="quali-table"></div>') +
        PD.card('Gap to pole', 'Each driver’s best lap against pole, in team colours.', '<div id="quali-gap"></div>') +
      '</div>';
    set('quali-table', PD.tableHTML([{ label: 'Pos', align: 'right' }, { label: 'Driver' }, { label: 'Team' }, { label: 'Q1', align: 'right' }, { label: 'Q2', align: 'right' }, { label: 'Q3', align: 'right' },
      { label: 'Gap', align: 'right', title: 'To pole' }, { label: 'v teammate', align: 'right', title: 'Best lap against the teammate in the same segment' }, { label: '' }], rows, { compact: true }));
    PD.sortable(document.getElementById('quali-table'));
    const g = ql.filter(x => PD.isNum(x.gap_ms_to_pole));
    if (!g.length) { set('quali-gap', PD.muted('No lap times to compare.')); return; }
    const rev = g.slice().reverse();
    PD.plot('quali-gap', [{
      type: 'bar', orientation: 'h', y: rev.map(x => PD.driverCode(x.driver)), x: rev.map(x => x.gap_ms_to_pole / 1000),
      marker: { color: rev.map(x => PD.teamColour(x.team || teams[x.driver])) }, text: rev.map(x => (x.gap_ms_to_pole ? '+' + PD.num(x.gap_ms_to_pole / 1000, 3) : 'pole')),
      textposition: 'outside', cliponaxis: false, textfont: { size: 9, color: C.text2 },
      customdata: rev.map(x => PD.driverName(x.driver) + ' · P' + x.pos + (outIn(x) ? ' · out in ' + outIn(x) : '')), hovertemplate: '%{customdata}<br>+%{x:.3f}s<extra></extra>'
    }], PD.layout({
      height: Math.max(320, g.length * 21 + 60), xaxis: { title: 'Seconds to pole', rangemode: 'tozero' },
      yaxis: { type: 'category', tickfont: { size: 10 }, fixedrange: true }, margin: { l: 50, r: 45, t: 10, b: 45 },
      shapes: [hasQ3 ? cutShape(g, 10) : null, hasQ2 ? cutShape(g, 15) : null].filter(Boolean)
    }));
  });
}

/* A dashed knockout line after the n-th fastest in the reversed bar order. */
function cutShape(g, n) {
  if (g.length <= n) return null;
  const y = g.length - n - 0.5;
  return { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: y, y1: y, line: { color: '#6e7681', width: 1, dash: 'dash' } };
}

PD.route('races', renderRaces);
PD.route('race', renderRace);
PD.route('quali', renderQuali);
PD.race = { resultsTable: resultsTable, simTable: simTable, teamMap: teamMap, raceHead: raceHead };
})(window.PD);
