/* The Quant Hardwood — the Player lab (#/<L>/lab).
 *
 * The football and F1 labs adapted to basketball: scatter any two metrics of the player
 * catalogue for one season or a window of seasons, filtered by position pool and minutes,
 * with presets for the pairs that separate kinds of player, marker size by minutes and
 * colour by team, pool, season or any metric, medians splitting the chart into quadrants,
 * the players furthest into the good corner labelled, a search highlight, and the group
 * ranked underneath. Small samples can be shrunk towards the pool median with a prior of
 * SHRINK_K minutes, as the football lab does with its 450-minute prior.
 *
 * Data: data/<L>/lab.json (or data/<L>/<S>/lab.json), column-oriented:
 * {fields: [id, name, team, season, pool, gp, min, ...metric keys], metrics, rows, years}. */
(function (HW) {
'use strict';

const FX = () => HW.fx;

/* Presets: [x candidates, y candidates, title, {color}]; candidates are matched in order against metric keys, then labels. */
const PRESETS = [
  [['pox100', 'pox', 'shot_making', 'pox_100', /pox|shot_?making|over_?exp/], ['xpps', 'xefg', 'shot_difficulty', /xpps|xefg|difficult|xpts/], 'Shot-making against shot difficulty (expected points per shot)'],
  [['usg', 'usg_pct', /usg|usage/], ['ts', 'ts_pct', /^ts/], 'Usage against true shooting'],
  [['blk_pct', /blk/], ['hpm_d', 'd_hpm', /hpm_?d/], 'Rim protection: block rate against defensive HPM'],
  [['hpm', 'hpm_t', /^hpm$/], ['on_off', 'on_off_net', 'on_off_diff', /on_?off/], 'On/off against HPM'],
  [['tpar', 'tpa_rate', '3par', 'fg3a_rate', /3pa|tpa_?rate|three.*rate/], ['c3_freq', 'corner3_share', 'freq_corner3', 'corner3_freq', /corner|c3/], 'Three-point rate against corner-three share'],
  [['ast_pct', /ast_?pct|^ast%/], ['tov_pct', /tov/], 'Playmaking: assist rate against turnover rate'],
  [['rim_freq', 'freq_rim', /rim.*freq|freq.*rim/], ['ftr', 'ft_rate', /ftr|ft_?rate/], 'Pressure: rim attempts against free-throw rate'],
  [['hpm_o', 'o_hpm', /hpm_?o/], ['hpm_d', 'd_hpm', /hpm_?d/], 'Two-way: offensive against defensive HPM'],
  [['box_impact', /box/], ['rapm', /^rapm/], 'Box score against RAPM: does the box agree with the lineups?'],
  [['trb_pct', 'reb_pct', /trb|reb_?pct/], ['blk_pct', /blk/], 'Bigs: rebound rate against block rate']
];
const SHRINK_K = 300;   // minutes of prior: a player with 300 minutes sits halfway between the pool median and his own rate
const NO_SHRINK = /^(gp|min|age|season|games|minutes)$/;

let LAB = null, LABL = null;
let S = { win: null, pool: 'all', min: 250, shrink: true, preset: 0, x: '', y: '', color: 'team', q: '' };
const MU = {};

function prep(raw) {
  const idx = {};
  (raw.fields || []).forEach((f, i) => { idx[f] = i; });
  const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('id', ['pid', 'player', 'player_id']); al('season', ['year']); al('min', ['minutes', 'mins']); al('gp', ['games', 'g']); al('pool', ['pos']);
  const meta = {};
  (raw.metrics || []).forEach(m => { meta[m.key] = m; });
  meta.min = meta.min || { key: 'min', label: 'Minutes', fmt: 'int' };
  meta.gp = meta.gp || { key: 'gp', label: 'Games', fmt: 'int' };
  const years = (raw.years && raw.years.length ? raw.years.slice() : Array.from(new Set((raw.rows || []).map(r => r[idx.season])))).filter(v => FX().isNum(v)).map(Number).sort((a, b) => b - a);
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(m => idx[m.key] !== undefined), rows: raw.rows || [], years: years };
}
function resolve(pats) {
  const ms = LAB.metrics;
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(String(x.label || '').toLowerCase())); if (m) return m.key; } }
  return '';
}
function presetList() { return PRESETS.map(p => ({ x: resolve(p[0]), y: resolve(p[1]), title: p[2] })).filter(p => p.x && p.y && p.x !== p.y); }

function raw(r, key) { const i = LAB.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function shrinkable(key) { const m = LAB.meta[key] || {}; return !NO_SHRINK.test(key) && m.fmt !== 'int'; }
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S.shrink || !shrinkable(key)) return v;
  const mu = (MU[key] || {})[raw(r, 'pool') || '_'];
  if (!FX().isNum(mu)) return v;
  const n = raw(r, 'min') || 0;
  return (n * v + SHRINK_K * mu) / (n + SHRINK_K);
}
function lower(key) { return !!(LAB.meta[key] || {}).lower; }
function label(key) { const m = LAB.meta[key] || {}; return (m.label || key) + (S.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return FX().fmtV(v, (LAB.meta[key] || {}).fmt); }
function stats(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

function inWindow(r) {
  const y = raw(r, 'season');
  if (S.win === 'all') return true;
  if (typeof S.win === 'string' && S.win.indexOf('last') === 0) { const k = parseInt(S.win.slice(4), 10); return LAB.years.indexOf(y) >= 0 && LAB.years.indexOf(y) < k; }
  return y === S.win;
}
function pool() { return LAB.rows.filter(r => inWindow(r) && (raw(r, 'min') || 0) >= S.min && (S.pool === 'all' || raw(r, 'pool') === S.pool)); }

function metricOptions(sel, scope) {
  const fx = FX();
  let h = scope === 'color' ? '<option value="team">Team</option><option value="pool">Position pool</option><option value="season">Season</option><option value="">One colour</option>' : '';
  fx.groups(LAB.metrics).forEach(g => { h += '<optgroup label="' + fx.esc(g.name) + '">' + g.items.map(m => '<option value="' + fx.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + fx.esc(m.label) + (m.lower ? ' ↓' : '') + (m.scope === 'pbp' ? ' ·pbp' : '') + '</option>').join('') + '</optgroup>'; });
  if (!scope) h += '<optgroup label="Sample"><option value="min"' + (sel === 'min' ? ' selected' : '') + '>Minutes</option><option value="gp"' + (sel === 'gp' ? ' selected' : '') + '>Games</option></optgroup>';
  return h;
}

function sync() {
  const fx = FX(), $ = id => document.getElementById(id), P = presetList();
  const yl = y => fx.seasonLabel(LABL, y);
  $('lab-win').innerHTML = LAB.years.map(y => '<option value="' + y + '"' + (y === S.win ? ' selected' : '') + '>' + fx.esc(yl(y)) + '</option>').join('') +
    (LAB.years.length > 2 ? '<option value="last3"' + (S.win === 'last3' ? ' selected' : '') + '>Last 3 seasons</option>' : '') +
    (LAB.years.length > 5 ? '<option value="last5"' + (S.win === 'last5' ? ' selected' : '') + '>Last 5 seasons</option>' : '') +
    '<option value="all"' + (S.win === 'all' ? ' selected' : '') + '>Every season since ' + fx.esc(yl(LAB.years[LAB.years.length - 1])) + '</option>';
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + fx.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x); $('lab-y').innerHTML = metricOptions(S.y);
  $('lab-color').innerHTML = metricOptions(S.color, 'color'); $('lab-color').value = S.color;
  $('lab-pool').value = S.pool;
  $('lab-min').value = S.min; $('lab-min-v').textContent = S.min;
  $('lab-shrink').checked = S.shrink; $('lab-q').value = S.q;
}
function applyPreset() {
  const P = presetList();
  if (S.preset < 0 || !P.length) return;
  const p = P[S.preset] || P[0];
  S.x = p.x; S.y = p.y;
}

function draw() {
  const fx = FX(), C = fx.C, I = LAB.idx, L = LABL;
  const base0 = pool();
  // Pool medians for the shrinkage: per position pool within the window and minutes floor.
  Object.keys(MU).forEach(k => delete MU[k]);
  [S.x, S.y, S.color].forEach(k => {
    if (!k || I[k] === undefined || !shrinkable(k)) return;
    MU[k] = {};
    ['G', 'F', 'C'].forEach(pl => { MU[k][pl] = fx.median(base0.filter(r => raw(r, 'pool') === pl).map(r => raw(r, k))); });
    MU[k]._ = fx.median(base0.map(r => raw(r, k)));
    Object.keys(MU[k]).forEach(pl => { if (!fx.isNum(MU[k][pl])) MU[k][pl] = MU[k]._; });
  });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  const multi = S.win === 'all' || String(S.win).indexOf('last') === 0;
  set('lab-sub', rows.length + ' player-seasons' + (multi ? ' (' + (S.win === 'all' ? 'every season' : 'last ' + S.win.slice(4) + ' seasons') + ')' : ' in ' + fx.seasonLabel(L, S.win)) + ' with ' + S.min + '+ minutes' + (S.pool !== 'all' ? ' · ' + S.pool + ' pool' : ''));
  if (rows.length < 3) { set('lab-chart', fx.muted('Too few players for this view: lower the minutes floor, widen the window or pick metrics that exist for these seasons (play-by-play metrics start about 2017).')); set('lab-table', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = fx.median(xs), my = fx.median(ys), sx = stats(xs), sy = stats(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase();
  const nm = r => raw(r, 'name') || fx.playerName(L, raw(r, 'id'));
  const hits = q ? rows.filter(r => (String(nm(r)) + ' ' + fx.teamName(L, raw(r, 'team')) + ' ' + fx.teamAbbr(L, raw(r, 'team'))).toLowerCase().indexOf(q) >= 0) : [];
  // Labels: the eight furthest into the good corner, the four furthest into the bad one, and the search.
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const mins = rows.map(r => raw(r, 'min') || 0), lo = Math.min.apply(null, mins), hi = Math.max.apply(null, mins);
  const size = r => 6 + 14 * (hi > lo ? Math.sqrt(((raw(r, 'min') || 0) - lo) / (hi - lo)) : 0.5);
  const hover = r => '<b>' + fx.esc(nm(r)) + '</b> · ' + fx.esc(fx.teamAbbr(L, raw(r, 'team'))) + ' · ' + fx.esc(fx.seasonLabel(L, raw(r, 'season'))) + ' · ' + (raw(r, 'pool') || '') + ' · ' + fx.num(raw(r, 'min'), 0) + ' min' +
    '<br>' + fx.esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S.x), dirx)) + ')' +
    '<br>' + fx.esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S.y), diry)) + ')' +
    (S.shrink && (shrinkable(S.x) || shrinkable(S.y)) ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  const trace = (pts, name, color, extra) => Object.assign({
    type: 'scatter', mode: 'markers', name: name, x: pts.map(r => val(r, S.x)), y: pts.map(r => val(r, S.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(r => raw(r, 'id') + '|' + raw(r, 'season')),
    marker: { size: pts.map(size), color: color, opacity: 0.82, line: { color: '#0d1117', width: 0.7 } }
  }, extra || {});
  const traces = [];
  const POOLC = { G: '#58a6ff', F: '#3fb950', C: '#f0883e' };
  if (S.color === 'team') {
    Array.from(new Set(rows.map(r => raw(r, 'team')))).forEach(t => traces.push(trace(rows.filter(r => raw(r, 'team') === t), fx.teamAbbr(L, t), fx.teamColour(L, t))));
  } else if (S.color === 'pool') {
    ['G', 'F', 'C'].forEach(pl => { const pts = rows.filter(r => raw(r, 'pool') === pl); if (pts.length) traces.push(trace(pts, pl === 'G' ? 'Guards' : pl === 'F' ? 'Forwards' : 'Centres', POOLC[pl])); });
    const other = rows.filter(r => ['G', 'F', 'C'].indexOf(raw(r, 'pool')) < 0);
    if (other.length) traces.push(trace(other, 'Other', C.text3));
  } else if (S.color === 'season') {
    Array.from(new Set(rows.map(r => raw(r, 'season')))).sort().forEach((y, i) => traces.push(trace(rows.filter(r => raw(r, 'season') === y), fx.seasonLabel(L, y), fx.PALETTE[i % fx.PALETTE.length])));
  } else if (S.color) {
    const cv = rows.map(r => val(r, S.color));
    traces.push(trace(rows, label(S.color), cv, { marker: { size: rows.map(size), color: cv, colorscale: 'RdBu', reversescale: !lower(S.color), opacity: 0.85,
      colorbar: { title: { text: label(S.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.7 } } }));
  } else traces.push(trace(rows, 'Players', C.blue));
  if (hits.length) traces.push(Object.assign(trace(hits, 'Search', '#ffffff'), { marker: { size: 20, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } }, showlegend: false }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S.x), y: val(r, S.y), text: fx.esc(fx.surname(nm(r))) + (multi ? ' ' + String(raw(r, 'season')).slice(2) : ''), showarrow: false, yshift: 11, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  fx.plot('lab-chart', traces, fx.layout({
    showlegend: S.color === 'pool' || S.color === 'season' || (S.color === 'team' && traces.length <= 32), legend: { orientation: 'h', y: -0.16, font: { color: C.text2, size: 10 } }, margin: { l: 70, r: 20, t: 20, b: 80 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S.x), zeroline: false, autorange: lower(S.x) ? 'reversed' : true },
    yaxis: { title: label(S.y), zeroline: false, autorange: lower(S.y) ? 'reversed' : true },
    shapes: [
      { type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } },
      { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }
    ]
  }));
  const node = document.getElementById('lab-chart');
  if (node && node.on) node.on('plotly_click', ev => { const d = ev.points && ev.points[0] && ev.points[0].customdata; if (d && typeof d === 'string') { const parts = d.split('|'); location.hash = fx.playerHref(L, parts[0], Number(parts[1])); } });
  const mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  set('lab-note', 'Dotted lines are the medians of the players on screen. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    'Labelled: the eight players furthest into that corner and the four furthest from it (sum of standard scores on both axes)' + (hits.length ? ', and your search' : '') + '. Marker size is minutes. Click a dot to open the player in that season.' +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the median of the player\'s position pool (guards, forwards, centres, on screen) by ' + SHRINK_K + ' minutes of prior, (minutes × rate + ' + SHRINK_K + ' × median) / (minutes + ' + SHRINK_K + '), so a player with 200 minutes is not ranked on 200 minutes alone; hover shows the raw figures. Counts (games, minutes) are never shrunk.' : '') +
    (mX.desc ? '<br><strong>' + fx.esc(mX.label) + '</strong>: ' + fx.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + fx.esc(mY.label) + '</strong>: ' + fx.esc(mY.desc) : ''));
  const host = document.getElementById('lab-table');
  host.innerHTML = HW.tableHTML([
    { label: '#', sortable: false }, { label: 'Player' }, { label: 'Team' }, { label: 'Season', align: 'right' }, { label: 'Pool' }, { label: 'Min', align: 'right' },
    { label: label(S.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }
  ], ranked.slice(0, 300).map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y);
    return { _href: fx.playerHref(L, raw(r, 'id'), raw(r, 'season')), cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: fx.playerLink(L, raw(r, 'id'), nm(r), raw(r, 'team'), raw(r, 'season')) }, { v: fx.teamAbbr(L, raw(r, 'team')), html: fx.esc(fx.teamAbbr(L, raw(r, 'team'))) },
      { v: raw(r, 'season'), html: fx.esc(fx.seasonLabel(L, raw(r, 'season'))) }, raw(r, 'pool') || '', { v: raw(r, 'min'), html: fx.num(raw(r, 'min'), 0) },
      { v: vx, html: fmt(S.x, vx) }, { v: pOf(sortedX, vx, dirx), html: fx.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S.y, vy) }, { v: pOf(sortedY, vy, diry), html: fx.pill(pOf(sortedY, vy, diry)) },
      { v: o.z, html: '<strong>' + fx.num(o.z, 2) + '</strong>' }
    ] };
  }), { sticky: true, compact: true });
  HW.sortable(host);
}

function renderLab(el, params, state) {
  const fx = FX(), L = fx.L(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">Player lab <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div class="lab-controls hf-controls">' +
    '<label>Seasons<select id="lab-win"></select></label>' +
    '<label>Preset<select id="lab-preset" class="hf-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label>' +
    '<label>Y axis<select id="lab-y"></select></label>' +
    '<label>&nbsp;<button type="button" id="lab-swap" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Position pool<select id="lab-pool"><option value="all">All</option><option value="G">Guards</option><option value="F">Forwards</option><option value="C">Centres</option></select></label>' +
    '<label>Colour<select id="lab-color"></select></label>' +
    '<label>Min minutes <span id="lab-min-v"></span><input id="lab-min" type="range" min="0" max="2000" step="25"></label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink small samples</label>' +
    '<label>Highlight<input id="lab-q" class="pg-search" type="search" placeholder="player or team…"></label>' +
    '</div><div id="lab-chart" class="hf-lab-chart"></div><div class="pg-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">The group by the combined standard score on both axes (top 300). Click a row for the player.</span></div><div id="lab-table"></div></div>';
  return fx.ready().then(() => {
    const Sx = fx.S(params, state, L);
    return fx.first([L + '/lab.json', fx.path(L, Sx, 'lab.json')]).then(rawLab => {
      if (!fx.alive(el)) return;
      if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { document.getElementById('lab-chart').innerHTML = fx.notBuilt('The lab file', rawLab); document.getElementById('lab-sub').textContent = ''; return; }
      if (LABL !== L) { S.win = null; S.x = ''; S.y = ''; S.preset = 0; }
      LAB = prep(rawLab); LABL = L;
      if (S.win === null || (typeof S.win === 'number' && LAB.years.indexOf(S.win) < 0)) S.win = LAB.years.indexOf(Sx) >= 0 ? Sx : LAB.years[0];
      // A season early in its schedule has few minutes: start the floor lower.
      const maxMin = Math.max.apply(null, LAB.rows.filter(inWindow).map(r => raw(r, 'min') || 0).concat([50]));
      if (S.min > maxMin * 0.5) S.min = Math.max(0, Math.round(maxMin * 0.25 / 25) * 25);
      document.getElementById('lab-min').max = String(Math.max(500, Math.ceil(maxMin / 100) * 100));
      const qy = params.query || {};
      if (qy.x && LAB.idx[qy.x] !== undefined) { S.x = qy.x; S.preset = -1; }
      if (qy.y && LAB.idx[qy.y] !== undefined) { S.y = qy.y; S.preset = -1; }
      if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
      if (!S.x || !S.y) { const ms = LAB.metrics; S.x = (ms[0] || {}).key || 'min'; S.y = (ms[1] || {}).key || 'gp'; S.preset = -1; }
      sync();
      const $ = id => document.getElementById(id);
      $('lab-win').onchange = e => { const v = e.target.value; S.win = /^\d+$/.test(v) ? parseInt(v, 10) : v; if (S.win === 'all' && S.color === 'team') S.color = 'season'; sync(); draw(); };
      $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
      $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; sync(); draw(); };
      $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; sync(); draw(); };
      $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
      $('lab-pool').onchange = e => { S.pool = e.target.value; draw(); };
      $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
      $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min; };
      $('lab-min').onchange = () => draw();
      $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
      let timer = null;
      $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
      draw();
    });
  });
}

HW.route('lab', renderLab);
})(window.HW);
