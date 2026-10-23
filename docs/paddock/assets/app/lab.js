/* The Quant Paddock — the Lab (#/lab): scatter any two metrics of the driver catalogue against each
 * other for one season (or every season since 2018), with presets, size and colour by any metric
 * (or team / season), medians splitting the chart into quadrants, the drivers furthest into the good
 * corner labelled, a search highlight, and the whole group ranked underneath. Small samples can be
 * shrunk towards the group median (3 races of prior). Shareable axes: ?x=&y=. Reads lab.json. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var PRESETS = [
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
var SHRINK_K = 3;
var LAB = null, MU = {};
var S = { year: null, min: 3, shrink: true, preset: 0, x: '', y: '', size: 'races', color: 'team', q: '' };

function labNav(active) { return PD.subnav([['#/lab', 'Driver lab', 'lab'], ['#/compare/drivers', 'Compare drivers', 'drivers'], ['#/compare/teams', 'Compare teams', 'teams']], active, 'Lab views'); }
PD.labNav = labNav;

function prep(raw) {
  var idx = {};
  (raw.fields || []).forEach(function (f, i) { idx[f] = i; });
  var al = function (want, list) { if (idx[want] === undefined) for (var i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('driver', ['driverId', 'driver_id', 'id']); al('name', ['driver_name']); al('team', ['constructorId', 'team_id', 'constructor']); al('year', ['season']); al('races', ['starts', 'n_races']);
  var meta = {};
  (raw.metrics || []).forEach(function (m) { meta[m.key] = m; });
  meta.races = meta.races || { key: 'races', label: 'Races', fmt: 'int' };
  var years = (raw.rows || []).map(function (r) { return r[idx.year]; }).filter(function (v, i, a) { return isNum(v) && a.indexOf(v) === i; }).sort(function (a, b) { return b - a; });
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(function (m) { return idx[m.key] !== undefined; }), rows: raw.rows || [], years: years };
}
function resolve(pats) {
  pats = pats.map(function (p) { return typeof p === 'string' ? new RegExp('^' + p + '$') : p; });
  for (var i = 0; i < pats.length; i++) { var m = LAB.metrics.filter(function (x) { return pats[i].test(x.key); })[0]; if (m) return m.key; }
  return '';
}
function presets() { return PRESETS.map(function (p) { return { x: resolve(p[0]), y: resolve(p[1]), title: p[2], color: p[3] && p[3].color ? resolve(p[3].color) : '' }; }).filter(function (p) { return p.x && p.y && p.x !== p.y; }); }
function raw(r, k) { var i = LAB.idx[k]; if (i === undefined) return null; var v = r[i]; return v === null || v === undefined || (typeof v === 'number' && isNaN(v)) ? null : v; }
function val(r, k) { var v = raw(r, k); if (v === null || !S.shrink || k === 'races' || k === 'year' || MU[k] === undefined) return v; var n = r[LAB.idx.races] || 0; return (n * v + SHRINK_K * MU[k]) / (n + SHRINK_K); }
function lower(k) { return !!(LAB.meta[k] || {}).lower; }
function label(k) { var m = LAB.meta[k] || {}; return (m.label || k) + (S.shrink && k !== 'races' && k !== 'year' ? ' (shrunk)' : ''); }
function fmt(k, v) { return PD.fmtVal(v, (LAB.meta[k] || {}).fmt); }
function stats(a) { var n = a.length; if (!n) return { m: 0, s: 1 }; var m = a.reduce(function (x, y) { return x + y; }, 0) / n; var v = a.reduce(function (x, y) { return x + (y - m) * (y - m); }, 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { var lo = 0, hi = sorted.length; while (lo < hi) { var mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } var up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function options(sel, scope) {
  var groups = [];
  LAB.metrics.forEach(function (m) { var g = groups.filter(function (x) { return x.name === (m.group || 'Other'); })[0]; if (!g) { g = { name: m.group || 'Other', items: [] }; groups.push(g); } g.items.push(m); });
  var h = scope === 'size' ? '<option value="races">Races</option><option value="">Same size</option>' : scope === 'color' ? '<option value="team">Team</option><option value="year">Season</option><option value="">One colour</option>' : '';
  groups.forEach(function (g) { h += '<optgroup label="' + esc(g.name) + '">' + g.items.map(function (m) { return '<option value="' + esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + esc(m.label) + (m.lower ? ' ↓' : '') + '</option>'; }).join('') + '</optgroup>'; });
  return h;
}
function sync() {
  var P = presets();
  PD.set('lab-year', LAB.years.map(function (y) { return '<option value="' + y + '"' + (y === S.year ? ' selected' : '') + '>' + y + '</option>'; }).join('') + '<option value="all"' + (S.year === 'all' ? ' selected' : '') + '>Every season since ' + (LAB.years[LAB.years.length - 1] || 2018) + '</option>');
  PD.set('lab-preset', P.map(function (p, i) { return '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + esc(p.title) + '</option>'; }).join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>');
  PD.set('lab-x', options(S.x)); PD.set('lab-y', options(S.y));
  PD.set('lab-size', options(S.size, 'size')); document.getElementById('lab-size').value = S.size;
  PD.set('lab-color', options(S.color, 'color')); document.getElementById('lab-color').value = S.color;
  document.getElementById('lab-min').value = S.min; PD.set('lab-min-v', String(S.min));
  document.getElementById('lab-shrink').checked = S.shrink; document.getElementById('lab-q').value = S.q;
}
function applyPreset() {
  var P = presets();
  if (S.preset < 0 || !P.length) return;
  var p = P[S.preset] || P[0];
  S.x = p.x; S.y = p.y;
  if (p.color) S.color = p.color; else if (S.color !== 'team' && S.color !== 'year') S.color = 'team';
}

function draw() {
  var I = LAB.idx;
  var base0 = LAB.rows.filter(function (r) { return (S.year === 'all' || r[I.year] === S.year) && (r[I.races] || 0) >= S.min; });
  Object.keys(MU).forEach(function (k) { delete MU[k]; });
  [S.x, S.y, S.size, S.color].forEach(function (k) { if (k && I[k] !== undefined && k !== 'races' && k !== 'year' && k !== 'team') { var a = base0.map(function (r) { return raw(r, k); }).filter(function (v) { return v !== null; }); if (a.length) MU[k] = PD.median(a); } });
  var rows = base0.filter(function (r) { return val(r, S.x) !== null && val(r, S.y) !== null; });
  PD.setHashQuiet('#/lab' + PD.qs({ x: S.x, y: S.y }));
  PD.set('lab-sub', rows.length + ' driver-seasons' + (S.year === 'all' ? ' since ' + (LAB.years[LAB.years.length - 1] || '') : ' in ' + S.year) + ' with ' + S.min + '+ races');
  if (rows.length < 3) { PD.ch.none('lab-chart', 'Too few drivers for this view; lower the race minimum or pick another season.'); PD.set('lab-table', ''); return; }
  var xs = rows.map(function (r) { return val(r, S.x); }), ys = rows.map(function (r) { return val(r, S.y); });
  var mx = PD.median(xs), my = PD.median(ys), sx = stats(xs), sy = stats(ys);
  var dx = lower(S.x) ? -1 : 1, dy = lower(S.y) ? -1 : 1;
  var ranked = rows.map(function (r) { return { r: r, z: dx * (val(r, S.x) - sx.m) / sx.s + dy * (val(r, S.y) - sy.m) / sy.s }; }).sort(function (a, b) { return b.z - a.z; });
  var q = S.q.trim().toLowerCase();
  var hit = function (r) { return q && (String(r[I.name] || '') + ' ' + String(r[I.driver] || '') + ' ' + PD.teamName(r[I.team])).toLowerCase().indexOf(q) >= 0; };
  var top10 = ranked.slice(0, 10).map(function (o) { return o.r; });
  var sortedX = xs.slice().sort(function (a, b) { return a - b; }), sortedY = ys.slice().sort(function (a, b) { return a - b; });
  var pOf = function (sorted, v, dir) { var p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  var nm = function (r) { return r[I.name] || PD.driverName(r[I.driver]); };
  var sizes = S.size ? rows.map(function (r) { return S.size === 'races' ? r[I.races] : val(r, S.size); }).filter(function (v) { return v !== null; }) : [];
  var slo = sizes.length ? Math.min.apply(null, sizes) : 0, shi = sizes.length ? Math.max.apply(null, sizes) : 1;
  var sizeOf = function (r) { if (!S.size) return 11; var x = S.size === 'races' ? r[I.races] : val(r, S.size); if (x === null) return 6; if (lower(S.size)) x = shi - (x - slo); return 7 + 15 * (shi > slo ? (x - slo) / (shi - slo) : 0.5); };
  var yrs = LAB.years.slice().sort();
  var cv = S.color && S.color !== 'team' && S.color !== 'year' ? rows.map(function (r) { return val(r, S.color); }).filter(function (v) { return v !== null; }) : [];
  var clo = cv.length ? Math.min.apply(null, cv) : 0, chi = cv.length ? Math.max.apply(null, cv) : 1;
  var colourOf = function (r) {
    if (S.color === 'team') return PD.teamColour(r[I.team]);
    if (S.color === 'year') return PD.PALETTE[yrs.indexOf(r[I.year]) % PD.PALETTE.length];
    if (S.color) { var v = val(r, S.color); if (v === null) return PD.col('grey'); var t = chi > clo ? (v - clo) / (chi - clo) : 0.5; if (lower(S.color)) t = 1 - t; return window.QK.pctHex(100 * t); }
    return PD.col('sky');
  };
  PD.ch.scatter('lab-chart', rows.map(function (r) {
    var vx = val(r, S.x), vy = val(r, S.y);
    return { x: vx, y: vy, name: nm(r) + (S.year === 'all' ? ' ' + r[I.year] : ''), short: String(nm(r)).split(' ').slice(-1)[0] + (S.year === 'all' ? ' ' + String(r[I.year]).slice(2) : ''), colour: colourOf(r), size: sizeOf(r),
      href: PD.driverHref(r[I.driver]), label: top10.indexOf(r) >= 0, hit: hit(r), sub: PD.teamName(r[I.team]) + ' · ' + r[I.year] + ' · ' + (r[I.races] || 0) + ' races',
      extra: window.QKC.tipRow(PD.col('grey'), 'Percentiles', Math.round(pOf(sortedX, vx, dx)) + ' / ' + Math.round(pOf(sortedY, vy, dy))) + (S.shrink ? window.QKC.tipRow(PD.col('grey'), 'Unshrunk', fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y))) : '') };
  }), { xName: label(S.x), yName: label(S.y), invX: lower(S.x), invY: lower(S.y), refX: mx, refY: my, xFmt: function (v) { return fmt(S.x, v); }, yFmt: function (v) { return fmt(S.y, v); }, label: 'Driver lab scatter' });
  var mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  PD.set('lab-note', 'Dashed lines are the medians of this group. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the ten drivers furthest into that corner (sum of standard scores)' + (q ? ', and your search (outlined)' : '') + '. Click a dot to open the driver.' +
    (S.shrink ? ' Shrunk values are pulled towards the group median by ' + SHRINK_K + ' races of prior, (races × value + ' + SHRINK_K + ' × median) / (races + ' + SHRINK_K + ').' : '') +
    (mX.desc ? '<br><b>' + esc(mX.label) + '</b>: ' + esc(mX.desc) : '') + (mY.desc ? '<br><b>' + esc(mY.label) + '</b>: ' + esc(mY.desc) : ''));
  PD.table('lab-table', [
    { key: 'name', label: 'Driver', sticky: true, fmt: function (v, r) { return PD.driverLink(r.id, { name: v, team: r.team }); } },
    { key: 'team', label: 'Team', fmt: function (v) { return esc(PD.teamName(v)); } },
    { key: 'year', label: 'Season', num: true, fmt: String }, { key: 'races', label: 'Races', num: true },
    { key: 'vx', label: label(S.x), num: true, pctl: 'px', fmt: function (v) { return fmt(S.x, v); } },
    { key: 'vy', label: label(S.y), num: true, pctl: 'py', fmt: function (v) { return fmt(S.y, v); } },
    { key: 'z', label: 'Combined', num: true, tip: 'Sum of standard scores in the better direction', fmt: function (v) { return '<b>' + PD.num(v, 2) + '</b>'; } }
  ], ranked.map(function (o) { var r = o.r, vx = val(r, S.x), vy = val(r, S.y); return { id: r[I.driver], name: nm(r), team: r[I.team], year: r[I.year], races: r[I.races] || 0, vx: vx, vy: vy, px: pOf(sortedX, vx, dx), py: pOf(sortedY, vy, dy), z: o.z }; }),
  { sort: { key: 'z', dir: 'desc' }, rank: true, maxHeight: 560 });
}

function render(el, params, state) {
  el.innerHTML = PD.pageHead('Lab', 'Build your own chart', '<span id="lab-sub">Loading…</span>') + labNav('lab') +
    PD.card('', '', '<div class="pd-toolbar pd-lab-ctl">' +
      '<label>Season<select class="qk-select" id="lab-year"></select></label>' +
      '<label class="pd-wide">Preset<select class="qk-select" id="lab-preset"></select></label>' +
      '<label>X axis<select class="qk-select" id="lab-x"></select></label><label>Y axis<select class="qk-select" id="lab-y"></select></label>' +
      '<button type="button" class="qk-btn" id="lab-swap" title="Swap the axes">⇄ Swap</button>' +
      '<label>Size<select class="qk-select" id="lab-size"></select></label><label>Colour<select class="qk-select" id="lab-color"></select></label>' +
      '<label>Min races <b id="lab-min-v"></b><input id="lab-min" type="range" min="1" max="20" step="1"></label>' +
      '<label class="pd-check"><input id="lab-shrink" type="checkbox"> Shrink small samples</label>' +
      '<label>Highlight<input class="qk-input" id="lab-q" type="search" placeholder="Driver or team…"></label></div>' +
      PD.chartBox('lab-chart', 600) + '<p class="pd-cap" id="lab-note"></p>') +
    PD.card('Ranked', 'The whole group by the combined standard score on both axes.', '<div id="lab-table"></div>', { flush: true, cls: 'pd-mt' });
  return PD.load('lab.json').then(function (rawLab) {
    if (!PD.alive(el)) return;
    if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { PD.ch.none('lab-chart', 'The lab file is not built yet.'); PD.set('lab-sub', ''); return; }
    LAB = prep(rawLab);
    if (S.year === null || (S.year !== 'all' && LAB.years.indexOf(S.year) < 0)) { var want = (rawLab.windows || {}).season || state.year; S.year = LAB.years.indexOf(want) >= 0 ? want : LAB.years[0]; }
    var q = params.query || {};
    if (q.x && LAB.idx[q.x] !== undefined) { S.x = q.x; S.preset = -1; }
    if (q.y && LAB.idx[q.y] !== undefined) { S.y = q.y; S.preset = -1; }
    if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
    if (!S.x || !S.y) { S.x = (LAB.metrics[0] || {}).key || 'races'; S.y = (LAB.metrics[1] || {}).key || 'races'; S.preset = -1; }
    sync();
    var $ = function (id) { return document.getElementById(id); };
    $('lab-year').onchange = function (e) { S.year = e.target.value === 'all' ? 'all' : parseInt(e.target.value, 10); if (S.year === 'all' && S.color === 'team') S.color = 'year'; sync(); draw(); };
    $('lab-preset').onchange = function (e) { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
    $('lab-x').onchange = function (e) { S.x = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-y').onchange = function (e) { S.y = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-swap').onclick = function () { var t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
    $('lab-size').onchange = function (e) { S.size = e.target.value; draw(); };
    $('lab-color').onchange = function (e) { S.color = e.target.value; draw(); };
    $('lab-min').oninput = function (e) { S.min = parseInt(e.target.value, 10); PD.set('lab-min-v', String(S.min)); };
    $('lab-min').onchange = function () { draw(); };
    $('lab-shrink').onchange = function (e) { S.shrink = e.target.checked; draw(); };
    var timer = null;
    $('lab-q').oninput = function (e) { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
    draw();
  });
}

PD.route('lab', render);
})(window.PD);
