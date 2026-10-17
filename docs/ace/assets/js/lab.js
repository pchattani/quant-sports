/* The Quant Ace — the player lab (#/<T>/lab).
 *
 * The football and Hardwood labs adapted to tennis: scatter any two metrics of the player
 * catalogue for one year or a rolling window of years, optionally on one surface, with presets
 * for the pairs that separate kinds of player, marker size by matches, colour by country,
 * year, surface or any metric, medians splitting the chart into quadrants, the players
 * furthest into the good corner labelled, a search highlight, and the group ranked underneath.
 * Small samples can be shrunk towards the median of the players on screen with a prior of
 * SHRINK_K matches, as the football lab does with its 450-minute prior.
 *
 * Address: ?x=<key>&y=<key> preset the axes.
 *
 * Data: data/<T>/lab.json, column-oriented {"fields": ["id","name","year","matches", ...metric keys],
 * "metrics": [METRIC], "rows": [[...]], "years": [...]}. An optional "surface" field (rows per
 * player-year-surface, "all" for the whole year) enables the surface filter. Uses TA.fk. */
(function (TA) {
'use strict';

const K = () => TA.fk;

/* Presets: [x candidates, y candidates, title, tour ('' = both)]. Candidates match keys (strings exact, then regexes). */
const PRESETS = [
  [['hold', /^hold/], ['brk', 'break', /^br(ea)?k/], 'Hold % against break %: the two halves of the game', ''],
  [['spw_exp', 'xspw', /x_?spw|spw_?(exp|inf)/], ['spw_real', 'spw', /^spw$/], 'Inferred against real serve points won: does the score model see the serve?', 'wta'],
  [['rpw_exp', 'xrpw', /x_?rpw|rpw_?exp/], ['rpw_real', 'rpw', /^rpw$/], 'Inferred against real return points won', 'wta'],
  [['rank', /^rank$/, 'points', /^points$/, 'elo_rank'], ['tb_over', /tb.*(over|exp)/], 'Tiebreak wins over expected against ranking', ''],
  [['ace_pct', /^ace/], ['first_won', /first_?won|1st_?won/], 'Aces against first-serve points won', 'wta'],
  [['rank', /^rank$/, 'points', /^points$/], ['elo', /^elo$/], 'Elo against the official ranking', ''],
  [['serve_rating', /serve_?r/], ['return_rating', /return_?r/], 'Serve rating against return rating', ''],
  [['win_pct', /win_?pct/], ['wins_over_exp', 'over_exp', /over_?exp/], 'Win % against wins over expected: who beats their prices?', ''],
  [['hold_real', /hold_?real/], ['hold', /^hold$/], 'Real against inferred hold % (WTA stats)', 'wta'],
  [['first_in', /first_?in/], ['second_won', /second_?won|2nd/], 'First serves in against second-serve points won', 'wta'],
  [['rally_len', /rally_?len/], ['winners_pp', 'winners_pt', /winner/], 'Rally length against winners per point (charted players)', ''],
  [['tb_pct', 'tb_win', /tb_?win/], ['dec_pct', 'deciding_win', /decid/], 'Tiebreaks against deciding sets', ''],
  [['elo_hard', /elo_?hard/], ['elo_clay', /elo_?clay/], 'Hard-court Elo against clay Elo', '']
];
const SHRINK_K = 15;    // matches of prior: a player with 15 matches sits halfway between the median and her own rate
const NO_SHRINK = /^(matches|year|age|rank|points|race_points|to_defend)$|elo|rating|_se$|_rank$/;
const LATEST = /elo|rating|^rank$|^points$|race_points|^age$|to_defend/;
const SUM = /^(w|l|matches)$|_over$|over_exp$/;   // plus every fmt 'int' count

let LAB = null, LABT = null;
let S = { win: null, surf: 'all', min: 10, shrink: true, preset: 0, x: '', y: '', color: 'country', q: '' };
const MU = {};

function prep(raw) {
  const k = K(), idx = {};
  (raw.fields || []).forEach((f, i) => { idx[f] = i; });
  const al = (want, list) => { if (idx[want] === undefined) for (let i = 0; i < list.length; i++) if (idx[list[i]] !== undefined) { idx[want] = idx[list[i]]; break; } };
  al('id', ['pid', 'player', 'player_id']); al('year', ['season', 'window']); al('matches', ['n', 'm', 'played']);
  const meta = {};
  (raw.metrics || []).forEach(m => { meta[m.key] = m; });
  meta.matches = meta.matches || { key: 'matches', label: 'Matches', fmt: 'int', group: 'Sample' };
  const ys = (raw.years && raw.years.length ? raw.years.slice() : Array.from(new Set((raw.rows || []).map(r => r[idx.year]))));
  const num = ys.filter(k.isNum).map(Number).sort((a, b) => b - a), lab = ys.filter(y => !k.isNum(y));
  return { idx: idx, meta: meta, metrics: (raw.metrics || []).filter(m => idx[m.key] !== undefined), rows: raw.rows || [], years: num, labels: lab, hasSurf: idx.surface !== undefined };
}
function resolve(pats) {
  const ms = LAB.metrics.concat(LAB.idx.rank !== undefined && !LAB.meta.rank ? [{ key: 'rank' }] : []);
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (typeof p === 'string') { const m = ms.find(x => x.key === p); if (m) return m.key; } }
  for (let i = 0; i < pats.length; i++) { const p = pats[i]; if (p instanceof RegExp) { const m = ms.find(x => p.test(x.key)); if (m) return m.key; } }
  return '';
}
function presetList() { return PRESETS.filter(p => !p[3] || p[3] === LABT).map(p => ({ x: resolve(p[0]), y: resolve(p[1]), title: p[2] })).filter(p => p.x && p.y && p.x !== p.y); }

function raw(r, key) { const i = LAB.idx[key]; if (i === undefined) return null; const v = r[i]; return v === null || v === undefined || (typeof v === 'number' && !isFinite(v)) ? null : v; }
function shrinkable(key) { const m = LAB.meta[key] || {}; return !NO_SHRINK.test(key) && m.fmt !== 'int' && m.fmt !== 'signed'; }
function lower(key) { return !!(LAB.meta[key] || {}).lower || key === 'rank'; }
function label(key) { const m = LAB.meta[key] || {}; return (m.label || (key === 'rank' ? 'Ranking' : key)) + (S.shrink && shrinkable(key) ? ' (shrunk)' : ''); }
function fmt(key, v) { return K().fmtV(v, (LAB.meta[key] || {}).fmt || (key === 'rank' ? 'int' : '')); }
function zs(a) { const n = a.length; if (!n) return { m: 0, s: 1 }; const m = a.reduce((x, y) => x + y, 0) / n; const v = a.reduce((x, y) => x + (y - m) * (y - m), 0) / n; return { m: m, s: Math.sqrt(v) || 1 }; }
function pctRank(sorted, v) { let lo = 0, hi = sorted.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < v) lo = mid + 1; else hi = mid; } let up = lo; while (up < sorted.length && sorted[up] === v) up++; return sorted.length ? 100 * ((lo + up) / 2) / sorted.length : null; }

/* The rows for the window and surface; a multi-year window aggregates each player into one row:
 * rates matches-weighted, counts and over-expected figures summed, ratings and ranks from the latest year. */
function windowRows() {
  const k = K();
  const surfOk = r => !LAB.hasSurf || String(raw(r, 'surface') || 'all') === S.surf;
  if (typeof S.win === 'number' || (typeof S.win === 'string' && LAB.labels.indexOf(S.win) >= 0)) return LAB.rows.filter(r => surfOk(r) && raw(r, 'year') === S.win);
  const n = S.win === 'all' ? LAB.years.length : parseInt(String(S.win).slice(4), 10);
  const yrs = LAB.years.slice(0, n);
  const by = {};
  LAB.rows.forEach(r => { if (!surfOk(r) || yrs.indexOf(raw(r, 'year')) < 0) return; const id = raw(r, 'id'); (by[id] || (by[id] = [])).push(r); });
  const keys = Object.keys(LAB.idx);
  return Object.keys(by).map(id => {
    const rs = by[id].slice().sort((a, b) => raw(b, 'year') - raw(a, 'year'));
    const out = new Array(LAB.rows[0] ? LAB.rows[0].length : keys.length).fill(null);
    const set = (key, v) => { out[LAB.idx[key]] = v; };
    const tot = rs.reduce((s, r) => s + (raw(r, 'matches') || 0), 0);
    keys.forEach(key => {
      if (key === 'id' || key === 'name' || key === 'surface') { set(key, raw(rs[0], key)); return; }
      if (key === 'year') { set(key, rs.length > 1 ? raw(rs[rs.length - 1], 'year') + '–' + String(raw(rs[0], 'year')).slice(2) : raw(rs[0], 'year')); return; }
      if (key === 'matches') { set(key, tot); return; }
      const vals = rs.map(r => [raw(r, key), raw(r, 'matches') || 0]).filter(x => k.isNum(x[0]));
      if (!vals.length) return;
      if (LATEST.test(key)) set(key, vals[0][0]);
      else if (SUM.test(key) || (LAB.meta[key] || {}).fmt === 'int') set(key, vals.reduce((s, x) => s + Number(x[0]), 0));
      else { const w = vals.reduce((s, x) => s + x[1], 0); set(key, w ? vals.reduce((s, x) => s + x[0] * x[1], 0) / w : k.mean(vals.map(x => x[0]))); }
    });
    return out;
  });
}
function val(r, key) {
  const v = raw(r, key);
  if (v === null || !S.shrink || !shrinkable(key)) return v;
  const mu = MU[key];
  if (!K().isNum(mu)) return v;
  const n = raw(r, 'matches') || 0;
  return (n * v + SHRINK_K * mu) / (n + SHRINK_K);
}

function metricOptions(sel, scope) {
  const k = K();
  let h = scope === 'color' ? '<option value="country">Country</option><option value="year">Year</option>' + (LAB.hasSurf ? '' : '') + '<option value="">One colour</option>' : '';
  k.groups(LAB.metrics).forEach(g => { h += '<optgroup label="' + k.esc(g.name) + '">' + g.items.map(m => '<option value="' + k.esc(m.key) + '"' + (m.key === sel ? ' selected' : '') + '>' + k.esc(m.label) + (m.lower ? ' ↓' : '') + (m.scope === 'wta_stats' ? ' ·stats' : m.scope === 'charted' ? ' ·charted' : '') + '</option>').join('') + '</optgroup>'; });
  if (!scope) h += '<optgroup label="Sample"><option value="matches"' + (sel === 'matches' ? ' selected' : '') + '>Matches</option>' + (LAB.idx.rank !== undefined && !LAB.meta.rank ? '<option value="rank"' + (sel === 'rank' ? ' selected' : '') + '>Ranking</option>' : '') + '</optgroup>';
  return h;
}

function sync() {
  const k = K(), $ = id => document.getElementById(id), P = presetList();
  $('lab-win').innerHTML = LAB.years.map(y => '<option value="' + y + '"' + (y === S.win ? ' selected' : '') + '>' + y + '</option>').join('') +
    LAB.labels.map(y => '<option value="' + k.esc(y) + '"' + (y === S.win ? ' selected' : '') + '>' + k.esc(y) + '</option>').join('') +
    [2, 3, 5].filter(n => LAB.years.length > n - 1 && n > 1).map(n => '<option value="last' + n + '"' + (S.win === 'last' + n ? ' selected' : '') + '>Last ' + n + ' years (combined)</option>').join('') +
    (LAB.years.length > 1 ? '<option value="all"' + (S.win === 'all' ? ' selected' : '') + '>Every year on file, combined</option>' : '');
  $('lab-surf').disabled = !LAB.hasSurf;
  $('lab-surf').value = S.surf;
  $('lab-preset').innerHTML = P.map((p, i) => '<option value="' + i + '"' + (i === S.preset ? ' selected' : '') + '>' + k.esc(p.title) + '</option>').join('') + '<option value="-1"' + (S.preset < 0 ? ' selected' : '') + '>Custom axes</option>';
  $('lab-x').innerHTML = metricOptions(S.x); $('lab-y').innerHTML = metricOptions(S.y);
  $('lab-x').value = S.x; $('lab-y').value = S.y;
  $('lab-color').innerHTML = metricOptions(S.color, 'color'); $('lab-color').value = S.color;
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
  const k = K(), C = k.C, T = LABT;
  const base0 = windowRows().filter(r => (raw(r, 'matches') || 0) >= S.min);
  Object.keys(MU).forEach(key => delete MU[key]);
  [S.x, S.y, S.color].forEach(key => { if (key && LAB.idx[key] !== undefined && shrinkable(key)) MU[key] = k.median(base0.map(r => raw(r, key))); });
  const rows = base0.filter(r => val(r, S.x) !== null && val(r, S.y) !== null);
  const set = (id, h) => { const e = document.getElementById(id); if (e) e.innerHTML = h; };
  const multi = typeof S.win === 'string' && LAB.labels.indexOf(S.win) < 0;
  set('lab-sub', rows.length + ' players' + (multi ? ' (' + (S.win === 'all' ? 'every year on file' : 'last ' + S.win.slice(4) + ' years') + ', combined)' : ' in ' + k.esc(S.win)) + (LAB.hasSurf && S.surf !== 'all' ? ' on ' + S.surf : '') + ' with ' + S.min + '+ matches');
  if (rows.length < 3) { set('lab-chart', k.muted('Too few players for this view: lower the match floor, widen the window, pick all surfaces, or pick metrics that exist for these players (real serve stats are WTA only; style metrics need charted matches).')); set('lab-table', ''); set('lab-note', ''); return; }
  const xs = rows.map(r => val(r, S.x)), ys = rows.map(r => val(r, S.y));
  const mx = k.median(xs), my = k.median(ys), sx = zs(xs), sy = zs(ys);
  const dirx = lower(S.x) ? -1 : 1, diry = lower(S.y) ? -1 : 1;
  const score = r => dirx * (val(r, S.x) - sx.m) / sx.s + diry * (val(r, S.y) - sy.m) / sy.s;
  const ranked = rows.map(r => ({ r: r, z: score(r) })).sort((a, b) => b.z - a.z);
  const q = S.q.trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const nm = r => raw(r, 'name') || k.name(T, raw(r, 'id'));
  const ctry = r => raw(r, 'country') || k.country(T, raw(r, 'id')) || '—';
  const hits = q ? rows.filter(r => (String(nm(r)) + ' ' + ctry(r)).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').indexOf(q) >= 0) : [];
  const labelled = new Set(ranked.slice(0, 8).map(o => o.r).concat(ranked.slice(-4).map(o => o.r)).concat(hits.slice(0, 20)));
  const sortedX = xs.slice().sort((a, b) => a - b), sortedY = ys.slice().sort((a, b) => a - b);
  const pOf = (sorted, v, dir) => { const p = pctRank(sorted, v); return dir > 0 ? p : 100 - p; };
  const ns = rows.map(r => raw(r, 'matches') || 0), lo = Math.min.apply(null, ns), hi = Math.max.apply(null, ns);
  const size = r => 6 + 14 * (hi > lo ? Math.sqrt(((raw(r, 'matches') || 0) - lo) / (hi - lo)) : 0.5);
  const hover = r => '<b>' + k.esc(nm(r)) + '</b> · ' + k.esc(ctry(r)) + ' · ' + k.esc(raw(r, 'year')) + ' · ' + (raw(r, 'matches') || 0) + ' matches' +
    '<br>' + k.esc(label(S.x)) + ': ' + fmt(S.x, val(r, S.x)) + ' (pct ' + Math.round(pOf(sortedX, val(r, S.x), dirx)) + ')' +
    '<br>' + k.esc(label(S.y)) + ': ' + fmt(S.y, val(r, S.y)) + ' (pct ' + Math.round(pOf(sortedY, val(r, S.y), diry)) + ')' +
    (S.shrink && (shrinkable(S.x) || shrinkable(S.y)) ? '<br><span style="color:#8b949e">unshrunk: ' + fmt(S.x, raw(r, S.x)) + ' · ' + fmt(S.y, raw(r, S.y)) + '</span>' : '');
  const trace = (pts, name, color, extra) => Object.assign({
    type: 'scatter', mode: 'markers', name: name, x: pts.map(r => val(r, S.x)), y: pts.map(r => val(r, S.y)),
    text: pts.map(hover), hovertemplate: '%{text}<extra></extra>', customdata: pts.map(r => raw(r, 'id')),
    marker: { size: pts.map(size), color: color, opacity: 0.82, line: { color: '#0d1117', width: 0.7 } }
  }, extra || {});
  const traces = [];
  if (S.color === 'country') {
    const cnt = {};
    rows.forEach(r => { cnt[ctry(r)] = (cnt[ctry(r)] || 0) + 1; });
    const top = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]).slice(0, 9);
    top.forEach((c, i) => traces.push(trace(rows.filter(r => ctry(r) === c), c + ' (' + cnt[c] + ')', k.PALETTE[i % k.PALETTE.length])));
    const rest = rows.filter(r => top.indexOf(ctry(r)) < 0);
    if (rest.length) traces.push(trace(rest, 'Other countries', '#6e7681'));
  } else if (S.color === 'year') {
    Array.from(new Set(rows.map(r => String(raw(r, 'year'))))).sort().forEach((y, i) => traces.push(trace(rows.filter(r => String(raw(r, 'year')) === y), y, k.PALETTE[i % k.PALETTE.length])));
  } else if (S.color) {
    const cv = rows.map(r => val(r, S.color));
    traces.push(trace(rows, label(S.color), cv, { marker: { size: rows.map(size), color: cv, colorscale: 'RdBu', reversescale: !lower(S.color), opacity: 0.85,
      colorbar: { title: { text: label(S.color), side: 'right' }, thickness: 10, tickfont: { color: C.text2 } }, line: { color: '#0d1117', width: 0.7 } } }));
  } else traces.push(trace(rows, 'Players', LAB.hasSurf && S.surf !== 'all' ? k.surfColour(S.surf) : C.blue));
  if (hits.length) traces.push(Object.assign(trace(hits, 'Search', '#ffffff'), { marker: { size: 20, color: 'rgba(0,0,0,0)', symbol: 'star-open', line: { color: '#ffffff', width: 2 } }, showlegend: false }));
  const ann = Array.from(labelled).map(r => ({ x: val(r, S.x), y: val(r, S.y), text: k.esc(k.surname(nm(r))), showarrow: false, yshift: 11, font: { size: 10, color: hits.indexOf(r) >= 0 ? '#ffffff' : '#c9d1d9' } }));
  // A y = x reference when both axes are the same kind of rate (inferred v real).
  const diag = (/spw|rpw/.test(S.x) && /spw|rpw/.test(S.y)) || (/^hold/.test(S.x) && /^hold/.test(S.y));
  const lim = diag ? [Math.min(Math.min.apply(null, xs), Math.min.apply(null, ys)), Math.max(Math.max.apply(null, xs), Math.max.apply(null, ys))] : null;
  if (diag) traces.unshift({ type: 'scatter', mode: 'lines', x: lim, y: lim, line: { color: '#6e7681', dash: 'dash', width: 1 }, hoverinfo: 'skip', showlegend: false, name: 'y = x' });
  k.plot('lab-chart', traces, k.layout({
    showlegend: S.color === 'country' || S.color === 'year', legend: { orientation: 'h', y: -0.16, font: { color: C.text2, size: 10 } }, margin: { l: 70, r: 20, t: 20, b: 80 }, annotations: ann, hovermode: 'closest',
    xaxis: { title: label(S.x), zeroline: false, autorange: lower(S.x) ? 'reversed' : true, tickformat: (LAB.meta[S.x] || {}).fmt === 'pct' ? '.0%' : '' },
    yaxis: { title: label(S.y), zeroline: false, autorange: lower(S.y) ? 'reversed' : true, tickformat: (LAB.meta[S.y] || {}).fmt === 'pct' ? '.0%' : '' },
    shapes: [
      { type: 'line', x0: mx, x1: mx, yref: 'paper', y0: 0, y1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } },
      { type: 'line', y0: my, y1: my, xref: 'paper', x0: 0, x1: 1, line: { color: '#3d444d', dash: 'dot', width: 1 } }
    ]
  }));
  const node = document.getElementById('lab-chart');
  if (node && node.on) node.on('plotly_click', ev => { const d = ev.points && ev.points[0] && ev.points[0].customdata; if (d && typeof d === 'string') location.hash = k.playerHref(T, d); });
  const mX = LAB.meta[S.x] || {}, mY = LAB.meta[S.y] || {};
  set('lab-note', 'Dotted lines are the medians of the players on screen. ' + (lower(S.x) || lower(S.y) ? 'Axes where less is better (and the ranking) are reversed, so better is always up and to the right. ' : 'Better is up and to the right. ') +
    (diag ? 'The dashed diagonal is equality: a dot above it won more points on serve than the score model inferred. ' : '') +
    'Labelled: the eight players furthest into the good corner and the four furthest from it (sum of standard scores on both axes)' + (hits.length ? ', and your search' : '') + '. Marker size is matches. Click a dot to open the player.' +
    (S.shrink ? ' Rates marked "shrunk" are pulled towards the median of the players on screen by ' + SHRINK_K + ' matches of prior, (matches × rate + ' + SHRINK_K + ' × median) / (matches + ' + SHRINK_K + '), so a player with five matches is not ranked on five matches alone; hover shows the raw figures. Ratings, Elo, ranks and counts are never shrunk: the models behind them already regularise.' : '') +
    (multi ? ' A combined window sums counts and over-expected figures, averages rates weighted by matches, and takes ratings and ranks from the latest year.' : '') +
    (mX.desc ? '<br><strong>' + k.esc(mX.label) + '</strong>: ' + k.esc(mX.desc) : '') + (mY.desc ? '<br><strong>' + k.esc(mY.label) + '</strong>: ' + k.esc(mY.desc) : ''));
  const host = document.getElementById('lab-table');
  host.innerHTML = k.table([
    { label: '#', sortable: false }, { label: 'Player' }, { label: 'Ctry' }, { label: 'Year', align: 'right' }, { label: 'Matches', align: 'right' },
    { label: label(S.x), align: 'right' }, { label: 'Pct', align: 'right' }, { label: label(S.y), align: 'right' }, { label: 'Pct', align: 'right' }, { label: 'Combined', align: 'right', title: 'Sum of standard scores in the better direction' }
  ], ranked.slice(0, 300).map((o, i) => {
    const r = o.r, vx = val(r, S.x), vy = val(r, S.y);
    return { _href: k.playerHref(T, raw(r, 'id')), cells: [
      { v: i + 1, cls: 'pos-cell' }, { v: nm(r), html: k.playerLink(T, raw(r, 'id'), nm(r)) }, { v: ctry(r), html: k.ctry(ctry(r)) },
      { v: String(raw(r, 'year')), html: k.esc(raw(r, 'year')) }, { v: raw(r, 'matches'), html: String(raw(r, 'matches') || 0) },
      { v: vx, html: fmt(S.x, vx) }, { v: pOf(sortedX, vx, dirx), html: k.pill(pOf(sortedX, vx, dirx)) }, { v: vy, html: fmt(S.y, vy) }, { v: pOf(sortedY, vy, diry), html: k.pill(pOf(sortedY, vy, diry)) },
      { v: o.z, html: '<strong>' + k.num(o.z, 2) + '</strong>' }
    ] };
  }), { sticky: true, compact: true });
  k.sortable(host);
}

function render(el, params, state) {
  const k = K(), T = k.T(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + k.TN(T) + ' player lab <span class="card-sub" id="lab-sub">Loading…</span></div>' +
    '<div class="lab-controls af-controls">' +
    '<label>Years<select id="lab-win"></select></label>' +
    '<label>Surface<select id="lab-surf"><option value="all">All surfaces</option><option value="hard">Hard</option><option value="clay">Clay</option><option value="grass">Grass</option></select></label>' +
    '<label>Preset<select id="lab-preset" class="af-wide"></select></label>' +
    '<label>X axis<select id="lab-x"></select></label>' +
    '<label>Y axis<select id="lab-y"></select></label>' +
    '<label>&nbsp;<button type="button" id="lab-swap" title="Swap the axes">⇄ swap</button></label>' +
    '<label>Colour<select id="lab-color"></select></label>' +
    '<label>Min matches <span id="lab-min-v"></span><input id="lab-min" type="range" min="0" max="80" step="1"></label>' +
    '<label class="inline"><input id="lab-shrink" type="checkbox"> shrink small samples</label>' +
    '<label>Highlight<input id="lab-q" class="pg-search" type="search" placeholder="player or country…"></label>' +
    '</div><div id="lab-chart" class="af-lab-chart"></div><div class="pg-note" id="lab-note"></div></div>' +
    '<div class="card"><div class="card-header">Ranked <span class="card-sub">The group by the combined standard score on both axes (top 300). Click a row for the player.</span></div><div id="lab-table"></div></div>';
  return k.ready().then(() => Promise.all([TA.load(T + '/lab.json'), k.loadNames(T)])).then(res => {
    if (!k.alive(el)) return;
    const rawLab = res[0];
    if (!rawLab || rawLab.ok === false || !(rawLab.rows || []).length) { document.getElementById('lab-chart').innerHTML = k.notBuilt('The ' + k.TN(T) + ' lab file', rawLab); document.getElementById('lab-sub').textContent = ''; return; }
    if (LABT !== T) { S.win = null; S.x = ''; S.y = ''; S.preset = 0; }
    LAB = prep(rawLab); LABT = T;
    const Y = k.Y(params, state, T);
    if (S.win === null || (typeof S.win === 'number' && LAB.years.indexOf(S.win) < 0)) S.win = LAB.years.indexOf(Y) >= 0 ? Y : (LAB.years[0] !== undefined ? LAB.years[0] : LAB.labels[0]);
    if (!LAB.hasSurf) S.surf = 'all';
    const maxN = Math.max.apply(null, windowRows().map(r => raw(r, 'matches') || 0).concat([10]));
    if (S.min > maxN * 0.5) S.min = Math.max(0, Math.round(maxN * 0.2));
    document.getElementById('lab-min').max = String(Math.max(40, Math.ceil(maxN / 10) * 10));
    const qy = params.query || {};
    if (qy.x && LAB.idx[qy.x] !== undefined) { S.x = qy.x; S.preset = -1; }
    if (qy.y && LAB.idx[qy.y] !== undefined) { S.y = qy.y; S.preset = -1; }
    if (!S.x || LAB.idx[S.x] === undefined || !S.y || LAB.idx[S.y] === undefined) { if (S.preset < 0) S.preset = 0; applyPreset(); }
    if (!S.x || !S.y) { const ms = LAB.metrics; S.x = (ms[0] || {}).key || 'matches'; S.y = (ms[1] || {}).key || 'matches'; S.preset = -1; }
    sync();
    const $ = id => document.getElementById(id);
    const rewin = () => { const mx2 = Math.max.apply(null, windowRows().map(r => raw(r, 'matches') || 0).concat([10])); $('lab-min').max = String(Math.max(40, Math.ceil(mx2 / 10) * 10)); if (S.min > mx2) { S.min = Math.round(mx2 * 0.2); } };
    $('lab-win').onchange = e => { const v = e.target.value; S.win = /^\d+$/.test(v) ? parseInt(v, 10) : v; rewin(); sync(); draw(); };
    $('lab-surf').onchange = e => { S.surf = e.target.value; rewin(); sync(); draw(); };
    $('lab-preset').onchange = e => { S.preset = parseInt(e.target.value, 10); applyPreset(); sync(); draw(); };
    $('lab-x').onchange = e => { S.x = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-y').onchange = e => { S.y = e.target.value; S.preset = -1; sync(); draw(); };
    $('lab-swap').onclick = () => { const t = S.x; S.x = S.y; S.y = t; S.preset = -1; sync(); draw(); };
    $('lab-color').onchange = e => { S.color = e.target.value; draw(); };
    $('lab-min').oninput = e => { S.min = parseInt(e.target.value, 10); $('lab-min-v').textContent = S.min; };
    $('lab-min').onchange = () => draw();
    $('lab-shrink').onchange = e => { S.shrink = e.target.checked; draw(); };
    let timer = null;
    $('lab-q').oninput = e => { S.q = e.target.value; clearTimeout(timer); timer = setTimeout(draw, 250); };
    draw();
  });
}

if (typeof TA.route === 'function') TA.route('lab', render);
})(window.TA || (window.TA = {}));
