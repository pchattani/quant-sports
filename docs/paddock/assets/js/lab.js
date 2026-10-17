/* The Quant Paddock — the Driver lab (#/lab).
 *
 * The football site's Player lab adapted to drivers: scatter any two metrics of the
 * driver catalogue against each other for one season (or every season since 2018),
 * with presets for the pairs that separate kinds of driver, marker size and colour
 * by any metric (or team / season), medians splitting the chart into quadrants, the
 * drivers furthest into the good corner labelled, a search highlight, and the whole
 * group ranked underneath. Small samples can be shrunk towards the group median.
 *
 * Data: data/lab.json, column-oriented: {fields, metrics, rows, windows}. */
(function (PD) {
'use strict';

const { esc, num, isNum, muted, tableHTML, sortable, pctPill, plot, layout, C, PALETTE } = PD;
const PG = () => PD.pg;

/* Presets: [x patterns, y patterns, title, {size, color}]; patterns are matched in order against metric keys. */
const PRESETS = [
  [['quali_gap_tm_pct', /quali.*tm/], ['race_pace_tm_delta', /pace.*tm/], 'Beating the team-mate: qualifying gap against race-pace gap'],
  [['overtakes_made', /overtak/], ['late_gain', /gain/], 'Racecraft: overtakes per race against places gained after lap 1'],
  [['deg_medium', /deg/], ['race_pace', /race.*pace/], 'Tyres: medium-tyre degradation against race pace'],
  [['tyre_mgmt'], ['race_pace'], 'Tyre management against race pace'],
  [['brake_earliness', /brak/], ['corner_speed_delta', /corner/], 'Telemetry style: braking earliness against minimum corner speed'],
  [['full_throttle'], ['coasting'], 'Telemetry style: full throttle against coasting'],
  [['exp_points', /exp.*points/], ['points_v_expected', /points.*exp/], 'Points against expected, coloured by race pace', { color: ['race_pace'] }],
  [['quali_pace', /quali.*pace/], ['race_pace'], 'Saturday against Sunday: qualifying pace against race pace'],
  [['lap1_gain'], ['late_gain'], 'Starts against the rest of the race'],
  [['driver_effect'], ['quali_driver_effect'], 'Driver effects: race against qualifying']
];
const SHRINK_K = 3;   // races of prior: a driver three races in sits halfway between the group median and his own figure

let LAB = null;
let S = { year: null, min: 3, shrink: true, preset: 0, x: '', y: '', size: 'races', color: 'team', q: '' };
const MU = {};

function prep(raw) {
  const idx = {};
  (raw.fields || []).forEach((f, i) => { idx[f] = i; });
  // Field aliases.
  const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('driver', ['driverId', 'driver_id', 'id']); al('name', ['driver_name']); al('team', ['constructorId', 'team_id', 'constructor']); al('year', ['season']); al('races', ['starts', 'n_races']);
  const meta = {};
  (raw.metrics || []).forEach(m => { meta[m.key] = m; });
  meta.races = meta.races || { key: 'races', label: 'Races', fmt: 'int' };
  const years = Array.from(new Set((raw.rows || []).map(r => r[idx.year]))).filter(isNum).sort((a, b) => b - a);
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(m => idx[m.key] !== undefined), rows: raw.rows || [], years: years, windows: raw.windows || {} };
}

function resolve(pats) {
  pats = pats.map(p => (typeof p === 'string' ? new RegExp('^' + p + '$') : p));
  for (let i = 0; i < pats.length; i++) { const m = LAB.metrics.find(x => pats[i].test(x.key)); if (m) return m.key; }
  for (let i = 0; i < pats.length; i++) { const m = LAB.metrics.find(x => pats[i].test(String(x.label || '').toLowerCase())); if (m) return m.key; }
  return '';
}
function presetList() {
  return PRESETS.map(p => ({ x: resolve(p[0]), y: resolve(p[1]), title: p[2], color: p[3] && p[3].color ? resolve(p[3].color) : '' })).filter(p => p.x && p.y && p.x !== p.y);
}

function raw(r, key) {
  const i = LAB.idx[key];
  if (i === undefined) return null;
  const v = r[i];
  return v === null || v === undefined || (typeof v === 'number' && isNaN(v)) ? null : v;
}
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S.shrink || key === 'races' || key === 'year' || MU[key] === undefined) return v;
  const n = r[LAB.idx.races] || 0;
  return (n * v + SHRINK_K * MU[key]) / (n + SHRINK_K);
}
function lower(key) { return !!(LAB.meta[key] || {}).lower; }
function label(key) { const m = LAB.meta[key] || {}; return (m.label || key) + (S.shrink && key !== 'races' && key !== 'year' ? ' (shrunk)' : ''); }
function fmt(key, v) { return PD.fmtVal(v, (LAB.meta[key] || {}).fmt); }
function stats(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function pool() {
  const I = LAB.idx;
  return LAB.rows.filter(r => (S.year === 'all' || r[I.year] === S.year) && (r[I.races] || 0) >= S.min);
}

function metricOptions(sel, scope) {
  const groups = PG().groups(LAB.metrics);
  let h = scope === 'size' ? '<option value="races">Races</option><option value="">Same size</option>' : scope === 'color' ? '<option value="team">Team</option><option value="year">Season</option><option value="">One colour</option>' : '';
  groups.forEach(g => { h += '<optgroup label="' + esc(g.name) + '">' + g.items.map(m => '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>').join('') + '</optgroup>'; });
  if (!scope) h += '<optgroup label="Sample"><option value="races"' + (sel === 'races' ? ' selected' : '') + '>Races</option></optgroup>';
  return h;
}

function sync() {
  const $ = id => document.getElementById(id);
  const P = presetList();
  $('lab-year').innerHTML = LAB.years.map(y => '<option value="' + y + '"' + (y === S.year ? ' selected' : '') + '>' + y + '</option>').join('') + '<option value="all"' + (S.year === 'all' ? ' selected' : '') + '>Every season since ' + (LAB.years[LAB.years.length - 1] || 2018) + '</option>';
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + esc(p.title) + '</option>').join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x); $('lab-y').innerHTML = metricOptions(S.y);
  $('lab-size').innerHTML = metricOptions(S.size, 'size'); $('lab-size').value = S.size;
  $('lab-color').innerHTML = metricOptions(S.color, 'color'); $('lab-color').value = S.color;
  $('lab-min').value = S.min; $('lab-min-v').textContent = S.min;
  $('lab-shrink').checked = S.shrink; $('lab-q').value = S.q;
}
function applyPreset() {
  const P = presetList();
  if (S.preset < 0 || !P.length) return;
  const p = P[S.preset] || P[0];
  S.x = p.x; S.y = p.y;
  if (p.color) S.color = p.color; else if (LAB.idx[S.color] !== undefined && S.color !== 'team' && S.color !== 'year') S.color = 'team';
}

function draw() {
  const I = LAB.idx;
  const base0 = pool();
  Object.keys(MU).forEach(k => delete MU[k]);
  [S.x, S.y, S.size, S.color].forEach(k => { if (k && I[k] !== undefined && k !== 'races' && k !== 'year' && k !== 'team') { const a = base0.map(r => raw(r, k)).filter(v => v !== null); if (a.length) MU[k] = PG().median(a); } });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  set('lab-sub', rows.length + ' driver-seasons' + (S.year === 'all' ? ' since ' + (LAB.years[LAB.years.length - 1] || '') : ' in ' + S.year) + ' with ' + S.min + '+ races');
  if (rows.length < 3) { set('lab-chart', muted('Too few drivers for this view; lower the race minimum or pick another season.')); set('lab-table', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = PG().median(xs), my = PG().median(ys), sx = stats(xs), sy = stats(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase();
  const hits = q ? rows.filter(r => (String(r[I.name] || '') + ' ' + String(r[I.driver] || '') + ' ' + PD.teamName(r[I.team])).toLowerCase().indexOf(q) >= 0) : [];
  const labelled = new Set(ranked.slice(0, 10).map(o => o.r).concat(hits));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const nm = r => r[I.name] || PD.driverName(r[I.driver]);
  const sizeOf = (() => {
    if (!S.size) return () => 11;
    const v = rows.map(r => (S.size === 'races' ? r[I.races] : val(r, S.size))).filter(x => x !== null);
    const lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    return r => { let x = S.size === 'races' ? r[I.races] : val(r, S.size); if (x === null) return 6; if (lower(S.size)) x = hi - (x - lo); return 7 + 17 * (hi > lo ? (x - lo) / (hi - lo) : 0.5); };
  })();
  const hover = r => '<b>' + esc(nm(r)) + '</b> · ' + esc(PD.teamName(r[I.team])) + ' · ' + r[I.year] + ' · ' + (r[I.races] || 0) + ' races' +
    '<br>' + esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S.x), dirx)) + ')' +
    '<br>' + esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S.y), diry)) + ')' +
    (S.shrink ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  const trace = (pts, name, color, extra) => Object.assign({
    type: 'scatter', mode: 'markers', name: name, x: pts.map(r => val(r, S.x)), y: pts.map(r => val(r, S.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(r => r[I.driver] + '|' + r[I.year]),
    marker: { size: pts.map(sizeOf), color: color, opacity: 0.85, line: { color: '#0d1117', width: 0.8 } }
  }, extra || {});
  const traces = [];
  if (S.color === 'team') {
    const teams = Array.from(new Set(rows.map(r => r[I.team])));
    teams.forEach(t => traces.push(trace(rows.filter(r => r[I.team] === t), PD.teamName(t), PD.teamColour(t))));
  } else if (S.color === 'year') {
    const yrs = Array.from(new Set(rows.map(r => r[I.year]))).sort();
    yrs.forEach((y, i) => traces.push(trace(rows.filter(r => r[I.year] === y), String(y), PALETTE[i % PALETTE.length])));
  } else if (S.color) {
    const cv = rows.map(r => val(r, S.color));
    traces.push(trace(rows, label(S.color), cv, { marker: { size: rows.map(sizeOf), color: cv, colorscale: 'RdBu', reversescale: !lower(S.color), opacity: 0.85,
      colorbar: { title: { text: label(S.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.8 } } }));
  } else traces.push(trace(rows, 'Drivers', C.blue));
  if (hits.length) traces.push(Object.assign(trace(hits, 'Search', '#ffffff'), { marker: { size: 20, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } }, showlegend: false }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S.x), y: val(r, S.y), text: esc(PD.driverSurname(r[I.driver]) === PD.titleCase(r[I.driver]) ? String(nm(r)).split(' ').slice(-1)[0] : PD.driverSurname(r[I.driver])) + (S.year === 'all' ? ' ' + String(r[I.year]).slice(2) : ''), showarrow: false, yshift: 12, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  plot('lab-chart', traces, layout({
    showlegend: S.color === 'team' || S.color === 'year', legend: { orientation: 'h', y: -0.16, font: { color: C.text2 } }, margin: { l: 70, r: 20, t: 20, b: 70 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S.x), zeroline: false, autorange: lower(S.x) ? 'reversed' : true },
    yaxis: { title: label(S.y), zeroline: false, autorange: lower(S.y) ? 'reversed' : true },
    shapes: [
      { type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } },
      { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }
    ]
  }));
  const node = document.getElementById('lab-chart');
  if (node && node.on) node.on('plotly_click', ev => { const d = ev.points && ev.points[0] && ev.points[0].customdata; if (d && typeof d === 'string') { const parts = d.split('|'); PD.setYear(parts[1], true); location.hash = '#/driver/' + parts[0]; } });
  const mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  set('lab-note', 'Dotted lines are the medians of this group. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the ten drivers furthest into that corner (sum of standard scores on both axes)' + (hits.length ? ', and your search' : '') + '. Click a dot to open the driver in that season.' +
    (S.shrink ? ' Values marked "shrunk" are pulled towards the group median by ' + SHRINK_K + ' races of prior, (races × value + ' + SHRINK_K + ' × median) / (races + ' + SHRINK_K + '), so a driver with two starts is not ranked on two starts alone; hover shows the raw figures.' : '') +
    (mX.desc ? '<br><strong>' + esc(mX.label) + '</strong>: ' + esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + esc(mY.label) + '</strong>: ' + esc(mY.desc) : ''));
  const host = document.getElementById('lab-table');
  host.innerHTML = tableHTML([
    { label: '#', sortable: false }, { label: 'Driver' }, { label: 'Team' }, { label: 'Season', align: 'right' }, { label: 'Races', align: 'right' },
    { label: label(S.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }
  ], ranked.map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y);
    return { _href: '#/driver/' + r[I.driver], cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: PD.driverLink(r[I.driver], { name: nm(r), team: r[I.team] }) }, { v: PD.teamName(r[I.team]), html: esc(PD.teamName(r[I.team])) }, r[I.year], r[I.races] || 0,
      { v: vx, html: fmt(S.x, vx) }, { v: pOf(sortedX, vx, dirx), html: pctPill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S.y, vy) }, { v: pOf(sortedY, vy, diry), html: pctPill(pOf(sortedY, vy, diry)) },
      { v: o.z, html: '<strong>' + num(o.z, 2) + '</strong>' }
    ] };
  }), { sticky: true, compact: true });
  sortable(host);
}

function renderLab(el, params, state) {
  el.innerHTML = '<div class="card"><div class="card-header">Driver lab <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div class="lab-controls">' +
    '<label>Season<select id="lab-year"></select></label>' +
    '<label>Preset<select id="lab-preset" style="max-width:340px"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label>' +
    '<label>Y axis<select id="lab-y"></select></label>' +
    '<label>&nbsp;<button type="button" id="lab-swap" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Size<select id="lab-size"></select></label>' +
    '<label>Colour<select id="lab-color"></select></label>' +
    '<label>Min races <span id="lab-min-v"></span><input id="lab-min" type="range" min="1" max="20" step="1"></label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink small samples</label>' +
    '<label>Highlight<input id="lab-q" class="pg-search" type="search" placeholder="driver or team…"></label>' +
    '</div><div id="lab-chart" style="height:620px"></div><div class="pg-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">The whole group by the combined standard score on both axes. Click a row for the driver.</span></div><div id="lab-table"></div></div>';
  return PD.load('lab.json').then(rawLab => {
    if (!PG().alive(el)) return;
    if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { document.getElementById('lab-chart').innerHTML = PG().notBuilt('The lab file', rawLab); document.getElementById('lab-sub').textContent = ''; return; }
    LAB = prep(rawLab);
    if (S.year === null || (S.year !== 'all' && LAB.years.indexOf(S.year) < 0)) {
      const want = (rawLab.windows || {}).season || state.year;
      S.year = LAB.years.indexOf(want) >= 0 ? want : LAB.years[0];
    }
    if (params.query && params.query.x && LAB.idx[params.query.x] !== undefined) { S.x = params.query.x; S.preset = -1; }
    if (params.query && params.query.y && LAB.idx[params.query.y] !== undefined) { S.y = params.query.y; S.preset = -1; }
    if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
    if (!S.x || !S.y) { const ms = LAB.metrics; S.x = (ms[0] || {}).key || 'races'; S.y = (ms[1] || {}).key || 'races'; S.preset = -1; }
    sync();
    const $ = id => document.getElementById(id);
    $('lab-year').onchange = e => { S.year = e.target.value === 'all' ? 'all' : parseInt(e.target.value, 10); if (S.year === 'all' && S.color === 'team') S.color = 'year'; sync(); draw(); };
    $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
    $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
    $('lab-size').onchange = e => { S.size = e.target.value; draw(); };
    $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
    $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min; };
    $('lab-min').onchange = () => draw();
    $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
    let timer = null;
    $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
    draw();
  });
}

PD.route('lab', renderLab);
})(window.PD);
