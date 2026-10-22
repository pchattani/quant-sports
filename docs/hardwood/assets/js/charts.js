/* The Quant Hardwood — shared chart helpers (HW.charts), drawn with the kit's ECharts layer (QKC); Design System 2.0.
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its data is missing. Times
 * are seconds of game time from tip-off (t); periods are 12 minutes in the NBA and 10 in the WNBA, overtimes 5.
 * Court charts use feet with the rim at (0, 0) and y up the floor, over the kit's court surface (QKC.SURF.court).
 *
 *   courtMount(el, build, label)           an ECharts chart on the half court (axes hidden; build(T) -> series...)
 *   shotRows(shots)                        {cols, rows} | [obj] -> [obj] with x, y, made, value, xpts, zone, player, team, type, t
 *   shotChart(el, shots, opts)             opts {league, mode:'dots'|'hex'|'zone', colour:'made'|'xpts', grid: shots_league.json,
 *                                          team (filter), player (filter), hexSize:1.6}
 *   cellChart(el, L, cells, opts)          league-relative cells (pps v league) as hexagons on the court
 *   zoneStats(shots) / zoneTable(zones, opts) / leagueZones(grid)
 *   periodLen(L) / periodAt(L, t) / periodTicks(L, tMax) / clockOf(L, t)
 *   flowChart(el, flow, opts)              flow [[t, margin_home]]; opts {league, home, away, height}
 *   wpChart(el, wp, opts)                  wp {model:[[t,p]], espn:[[t,p]]}; opts {league, home, away, plays, top:6, height}
 *   rotationChart(el, rotation, opts)      rotation {pid: [[t0,t1]...]} for one team; opts {league, team, order, names(pid), height, tMax}
 *   heatTable(spec)                        returns HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   posHeatmap(el, rows, opts)             rows [{label, dist:[p per seed]}]; opts {labels, height, zmax, xTitle, yTitle}
 *   probBars(el, items, opts)              items [{label, p, colour, market}]: our chance as bars, the market a grey tick
 *   lines(el, series, opts)                series [{name, x, y, colour, dash, width, err, band:[lo,hi] arrays}]
 *   radar(el, series, opts)                series [{name, values:[0-100], colour}]; opts {labels, height}
 * Every value axis carries a title (the standing rule). */
(function (HW) {
'use strict';

const C = HW.C;
const ZONE_LABEL = { rim: 'At the rim', paint: 'Paint (non-RA)', mid: 'Mid-range', corner3: 'Corner 3', ab3: 'Above-the-break 3', heave: 'Heaves' };
const ZONE_ORDER = ['rim', 'paint', 'mid', 'corner3', 'ab3', 'heave'];

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }
function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(139,148,158,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
}

// ── shots ──────────────────────────────────────────────────────────────────

/* The game payload's {cols, rows} (or a list of objects) as objects with x, y, made, value, xpts, zone... */
function shotRows(shots) {
  if (!shots) return [];
  let list;
  if (Array.isArray(shots)) list = shots;
  else if (Array.isArray(shots.rows) && Array.isArray(shots.cols)) {
    const cols = shots.cols;
    list = shots.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  } else return [];
  return list.map(s => {
    const x = HW.isNum(s.x) ? Number(s.x) : (HW.isNum(s.x_ft) ? Number(s.x_ft) : null);
    const y = HW.isNum(s.y) ? Number(s.y) : (HW.isNum(s.y_ft) ? Number(s.y_ft) : null);
    const made = s.made === true || s.made === 1 || s.made === '1';
    return Object.assign({}, s, { x: x, y: y, made: made, value: HW.isNum(s.value) ? Number(s.value) : 2,
      xpts: HW.isNum(s.xpts) ? Number(s.xpts) : null, player: s.player !== undefined ? s.player : s.shooter, type: s.type || s.shot_type });
  }).filter(s => s.x !== null && s.y !== null);
}

/* shots_league.json -> a list of grid cells {x, y, n, fg, pps} (accepts {grid:{cols,rows}}, {grid:[...]}, {cells}, {cols,rows}). */
function gridCells(grid) {
  if (!grid) return [];
  const g = grid.grid || grid.league_grid || grid.cells || grid;
  if (Array.isArray(g)) return g.filter(c => c && HW.isNum(c.x) && HW.isNum(c.y));
  if (g && Array.isArray(g.rows) && Array.isArray(g.cols)) return g.rows.map(r => { const o = {}; g.cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  if (g && typeof g === 'object' && Array.isArray(g.x)) return g.x.map((x, i) => { const o = {}; Object.keys(g).forEach(k => { o[k] = g[k][i]; }); return o; });
  return [];
}
/* shots_league.json -> {zone: {freq, fg, pps}}. */
function leagueZones(grid) {
  if (!grid) return {};
  const z = grid.zones || grid.zone_table || grid.calibration || grid.calibration_table;
  const out = {};
  const put = (k, v) => { if (!k || !v) return; out[k] = { freq: v.freq !== undefined ? v.freq : v.share, fg: HW.isNum(v.fg) ? v.fg : v.p_mean, pps: HW.isNum(v.pps) ? v.pps : (HW.isNum(v.pts) && v.n ? v.pts / v.n : null), n: v.n }; };
  if (Array.isArray(z)) z.forEach(r => put(r.zone || r.cat || r.index, r));
  else if (z && Array.isArray(z.rows) && Array.isArray(z.cols)) z.rows.forEach(r => { const o = {}; z.cols.forEach((c, i) => { o[c] = r[i]; }); put(o.zone || o.cat || o.index, o); });
  else if (z && typeof z === 'object') Object.keys(z).forEach(k => put(k, z[k]));
  const tot = Object.keys(out).reduce((a, k) => a + (out[k].n || 0), 0);
  if (tot) Object.keys(out).forEach(k => { if (!HW.isNum(out[k].freq) && out[k].n) out[k].freq = out[k].n / tot; });
  return out;
}
function zoneStats(rows) {
  const out = {};
  const list = rows || [];
  list.forEach(s => {
    const z = s.zone || 'other';
    const o = out[z] || (out[z] = { n: 0, fgm: 0, pts: 0, xpts: 0, nx: 0 });
    o.n += 1; if (s.made) { o.fgm += 1; o.pts += s.value; }
    if (HW.isNum(s.xpts)) { o.xpts += s.xpts; o.nx += 1; }
  });
  Object.keys(out).forEach(z => {
    const o = out[z];
    o.fg = o.n ? o.fgm / o.n : null; o.pps = o.n ? o.pts / o.n : null; o.xpps = o.nx ? o.xpts / o.nx : null; o.freq = list.length ? o.n / list.length : null;
  });
  return out;
}
function zoneTable(zones, opts) {
  const o = opts || {};
  const z = zones || {};
  const keys = ZONE_ORDER.filter(k => z[k]).concat(Object.keys(z).filter(k => ZONE_ORDER.indexOf(k) < 0));
  if (!keys.length) return HW.muted('No shots.');
  const lg = o.league || {};
  const rows = keys.map(k => {
    const v = z[k] || {};
    const lp = HW.isNum(v.league_pps) ? v.league_pps : (lg[k] || {}).pps;
    const diff = HW.isNum(v.pps) && HW.isNum(lp) ? v.pps - lp : null;
    return [
      { v: ZONE_ORDER.indexOf(k), html: HW.esc(ZONE_LABEL[k] || HW.titleCase(k)) },
      { v: v.n, html: HW.isNum(v.n) ? String(v.n) : '—', align: 'right' },
      { v: v.freq, html: HW.fmtVal(v.freq, 'pct'), align: 'right' },
      { v: v.fg, html: HW.fmtVal(v.fg, 'pct'), align: 'right' },
      { v: v.pps, html: HW.num(v.pps, 2), align: 'right' },
      { v: v.xpps, html: HW.num(v.xpps, 2), align: 'right' },
      { v: lp, html: HW.num(lp, 2), align: 'right' },
      { v: diff, html: HW.isNum(diff) ? '<span class="' + (diff > 0 ? 'edge-pos' : 'edge-neg') + '">' + HW.signed(diff, 2) + '</span>' : '—', align: 'right' }
    ];
  });
  const cols = [{ label: 'Zone' }, { label: 'FGA', align: 'right' }, { label: 'Share', align: 'right' }, { label: 'FG%', align: 'right' },
    { label: 'PPS', align: 'right', title: 'Points per shot (made shots × value / attempts; free throws not counted)' },
    { label: 'xPPS', align: 'right', title: 'Expected points per shot from the shot model' },
    { label: 'Lg PPS', align: 'right', title: 'League points per shot from the zone' }, { label: '±Lg', align: 'right' }];
  const showX = rows.some(r => HW.isNum(r[5].v)), showL = rows.some(r => HW.isNum(r[6].v));
  const keep = cols.map((c, i) => !((i === 5 && !showX) || ((i === 6 || i === 7) && !showL)));
  return HW.tableHTML(cols.filter((c, i) => keep[i]), rows.map(r => r.filter((c, i) => keep[i])), { compact: true });
}

function nearestCell(cells, x, y) {
  let best = null, bd = Infinity;
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    const d = (c.x - x) * (c.x - x) + (c.y - y) * (c.y - y);
    if (d < bd) { bd = d; best = c; }
  }
  return bd <= 16 ? best : null;
}
/* Pointy-top hex lattice binning (axial rounding), circumradius r. */
function hexBin(rows, r) {
  const sq3 = Math.sqrt(3);
  const bins = {};
  rows.forEach(s => {
    const q = (sq3 / 3 * s.x - s.y / 3) / r, rr = (2 / 3 * s.y) / r;
    let xq = q, zq = rr, yq = -xq - zq;
    let rx = Math.round(xq), ry = Math.round(yq), rz = Math.round(zq);
    const dx = Math.abs(rx - xq), dy = Math.abs(ry - yq), dz = Math.abs(rz - zq);
    if (dx > dy && dx > dz) rx = -ry - rz; else if (dy > dz) ry = -rx - rz; else rz = -rx - ry;
    const k = rx + ',' + rz;
    const b = bins[k] || (bins[k] = { x: r * sq3 * (rx + rz / 2), y: r * 1.5 * rz, n: 0, fgm: 0, pts: 0, xpts: 0, nx: 0 });
    b.n += 1; if (s.made) { b.fgm += 1; b.pts += s.value; }
    if (HW.isNum(s.xpts)) { b.xpts += s.xpts; b.nx += 1; }
  });
  return Object.keys(bins).map(k => bins[k]);
}
// ── game time ──────────────────────────────────────────────────────────────

function periodLen(L) { return (HW.isLeague(L) ? L : HW.state.league) === 'wnba' ? 600 : 720; }
function periodStart(L, p) { const n = periodLen(L); return p <= 4 ? (p - 1) * n : 4 * n + (p - 5) * 300; }
function periodAt(L, t) {
  const n = periodLen(L);
  if (t < 4 * n) return Math.floor(t / n) + 1;
  return 5 + Math.floor((t - 4 * n) / 300);
}
/* "Q3 4:12" from seconds of game time. */
function clockOf(L, t) {
  if (!HW.isNum(t)) return '';
  const p = periodAt(L, t);
  const end = p <= 4 ? periodStart(L, p) + periodLen(L) : periodStart(L, p) + 300;
  return HW.periodLabel(L, p) + ' ' + HW.fmtSec(Math.max(0, end - t));
}
function periodTicks(L, tMax) {
  const n = periodLen(L);
  const vals = [], text = [], lines = [];
  let p = 1;
  while (periodStart(L, p) < Math.max(tMax, 4 * n) - 1) {
    const s = periodStart(L, p), e = p <= 4 ? s + n : s + 300;
    vals.push((s + e) / 2); text.push(HW.periodLabel(L, p));
    if (p > 1) lines.push(s);
    p += 1;
    if (p > 12) break;
  }
  return { vals: vals, text: text, lines: lines, end: periodStart(L, p) };
}
// ── generic ────────────────────────────────────────────────────────────────

function heatTable(spec) {
  const s = spec || {};
  const rows = s.rows || [];
  if (!rows.length) return '<div class="muted">No data.</div>';
  const nCols = Math.max.apply(null, rows.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(HW.isNum(s.center) ? s.center : 0); continue; }
    const col = rows.map(r => (r.values || [])[i]).filter(HW.isNum).sort((a, b) => a - b);
    centers.push(col.length ? col[Math.floor(col.length / 2)] : 0);
  }
  const vals = [];
  rows.forEach(r => (r.values || []).forEach((v, i) => { if (HW.isNum(v)) vals.push(Math.abs(v - centers[i])); }));
  vals.sort((a, b) => a - b);
  const max = s.max || vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;
  const fmt = s.fmt || (v => HW.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? HW.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : HW.divColour(v - centers[i], max, s.invert));
  let h = '<div class="table-wrap heat-wrap"' + (s.maxWidth ? ' style="max-width:' + s.maxWidth + 'px"' : '') + '><table class="wc-table heat-table"><thead><tr><th class="heat-corner">' + HW.esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th' + (cc.title ? ' title="' + HW.esc(cc.title) + '"' : '') + '>' + HW.esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(r => {
    h += '<tr><td class="heat-label">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, i) => {
      const t = r.titles && r.titles[i] ? ' title="' + HW.esc(r.titles[i]) + '"' : '';
      h += HW.isNum(v) ? '<td class="heat-cell" style="background:' + colour(v, i) + '"' + t + '>' + fmt(v) + '</td>' : '<td class="heat-cell heat-empty"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}

// ── ECharts court charts (Design System 2.0; the Plotly shim is no longer used here) ─────────────────────

function nodeOf(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function isN(x) { return HW.isNum(x); }
/* A chart on the half court: chart coordinates in feet (rim at 0,0, y up the floor), the kit's court surface
 * drawn behind a hidden pair of value axes, so every mark sits where it happened. build(T) returns the option
 * (series, tooltip, legend); the grid and axes are set here. */
function courtMount(el, build, label) {
  const node = nodeOf(el);
  if (!node || !window.QKC) return null;
  const S = QKC.SURF.court;
  node.classList.add('qk-chart', 'sq', 'qk-surface');
  node.style.setProperty('--ar', (S.x[1] - S.x[0]) + ' / ' + (S.y[1] - S.y[0]));
  return QKC.mount(node, T => {
    node.style.backgroundImage = 'url("data:image/svg+xml,' + encodeURIComponent(QKC.surfaceSVG('court', T)) + '")';
    const o = build(T);
    const ax = r => ({ type: 'value', min: r[0], max: r[1], show: false });
    return Object.assign({ grid: { left: 0, right: 0, top: 0, bottom: 0 }, xAxis: ax(S.x), yAxis: ax(S.y) }, o);
  }, { label: label || 'Shot chart on the half court' });
}
/* A one-line key under a chart (kept in step when the chart is drawn again). */
function chartKey(el, html) {
  const node = nodeOf(el);
  if (!node || !node.parentNode) return;
  let k = node.nextElementSibling;
  if (!k || !k.classList.contains('hw-chartkey')) { k = document.createElement('div'); k.className = 'hw-chartkey'; node.parentNode.insertBefore(k, node.nextSibling); }
  k.innerHTML = html || '';
}
/* Cold-to-hot colour for a value on [lo, hi] (the kit's percentile scale; theme-following hex). */
function heat(v, lo, hi) { return QK.pctHex(isN(v) ? Math.max(0, Math.min(100, 100 * (v - lo) / ((hi - lo) || 1))) : 50); }
const DIFF_MAX = 0.6;
function hexPoly(api, x, y, rFeet) {
  const c = api.coord([x, y]), u = api.size([1, 0])[0], R = rFeet * u, pts = [];
  for (let k = 0; k < 6; k++) { const a = Math.PI / 180 * (60 * k - 30); pts.push([c[0] + R * Math.cos(a), c[1] + R * Math.sin(a)]); }
  return pts;
}
function legendTop(T) { return { top: 6, right: 8, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 } }; }

/* Shot chart. opts { league, team, player, mode: 'dots' | 'hex' | 'zone', colour: 'made' | 'xpts', grid: shots_league.json }.
 * dots: made filled (team colour), missed a grey ring, size = expected points; colour 'xpts' colours every shot by
 * its expected points instead. hex: hexagons sized by attempts, coloured by points per shot (against the league
 * from the same spot when the league grid is there). zone: each zone's FG% and makes over attempts. */
function shotChart(el, shots, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  let rows = shotRows(shots).filter(s => s.y <= 41.5);
  if (o.team) rows = rows.filter(s => String(s.team) === String(o.team));
  if (o.player) rows = rows.filter(s => String(s.player) === String(o.player));
  if (!rows.length) { empty(el, o.emptyText || 'No shot locations for this selection.'); chartKey(el, ''); return; }
  const mode = o.mode || 'dots';
  const cells = gridCells(o.grid);
  const tc = o.team ? HW.teamColour(L, o.team) : null;
  const txt = s => (s.playerName || (s.player ? HW.playerName(L, s.player) : '')) + (s.type ? ' · ' + s.type : '') + ' · ' + s.value + 'PT ' + (s.made ? 'made' : 'missed') +
    (isN(s.xpts) ? ' · xPTS ' + HW.num(s.xpts, 2) : '') + (isN(s.t) ? ' · ' + clockOf(L, s.t) : '');
  if (mode === 'hex') {
    const r = o.hexSize || 1.6;
    const bins = hexBin(rows, r);
    const maxN = Math.max.apply(null, bins.map(b => b.n)) || 1;
    const rel = cells.length > 0;
    const vals = bins.map(b => {
      const pps = b.pts / b.n;
      if (rel) { const c = nearestCell(cells, b.x, b.y); const lp = c && isN(c.pps) ? c.pps : null; return isN(lp) ? pps - lp : null; }
      return pps;
    });
    courtMount(el, T => ({
      tooltip: QKC.tooltip(T, { formatter: p => { const b = bins[p.dataIndex], v = vals[p.dataIndex];
        return '<div style="font-weight:600">' + b.n + ' attempts · ' + b.fgm + ' made</div>' + QKC.tipRow(p.color, 'Points per shot', HW.num(b.pts / b.n, 2)) +
          (rel && isN(v) ? QKC.tipRow(p.color, 'v league', HW.signed(v, 2)) : '') + (b.nx ? QKC.tipRow(T.ink3, 'Expected per shot', HW.num(b.xpts / b.nx, 2)) : ''); } }),
      series: [{ type: 'custom', data: bins.map(b => [b.x, b.y, b.n]), encode: { x: 0, y: 1 }, z: 3,
        renderItem: (params, api) => {
          const b = bins[params.dataIndex], v = vals[params.dataIndex];
          const col = rel ? heat(v, -DIFF_MAX, DIFF_MAX) : heat(v, 0, 1.6);
          return { type: 'polygon', shape: { points: hexPoly(api, b.x, b.y, r * (0.35 + 0.65 * Math.sqrt(b.n / maxN))) }, style: { fill: QKC.hexA(col, 0.9), stroke: T.s1, lineWidth: 0.6 } };
        } }]
    }), (HW.teamName(L, o.team) || 'Team') + ' shots, hexagons');
    chartKey(el, 'Size: attempts. Colour: ' + (rel ? 'points per shot against the league from the same spot (blue below, grey level, red above)' : 'points per shot (blue low, red high)') + '.');
    return;
  }
  if (mode === 'zone') {
    const zs = zoneStats(rows), lz = leagueZones(o.grid), pos = {};
    rows.forEach(s => { const z = s.zone || 'other'; const p = pos[z] || (pos[z] = { x: 0, y: 0, n: 0 }); p.x += s.x; p.y += s.y; p.n += 1; });
    const keys = Object.keys(zs).filter(k => k !== 'heave' && pos[k]);
    const dz = k => { const lp = (lz[k] || {}).pps; return isN(lp) && isN(zs[k].pps) ? zs[k].pps - lp : null; };
    courtMount(el, T => ({
      tooltip: QKC.tooltip(T, { formatter: p => { const k = p.data.zone, z = zs[k], d = dz(k);
        return '<div style="font-weight:600">' + HW.esc(ZONE_LABEL[k] || k) + '</div>' + QKC.tipRow(p.color, 'Made', z.fgm + ' of ' + z.n) + QKC.tipRow(p.color, 'Points per shot', HW.num(z.pps, 2)) +
          (isN(d) ? QKC.tipRow(T.ink3, 'v league', HW.signed(d, 2)) : ''); } }),
      series: [{ type: 'scatter', silent: true, symbolSize: 5, z: 2, data: rows.filter(s => keys.indexOf(s.zone || 'other') >= 0).map(s => ({ value: [s.x, s.y], itemStyle: { color: QKC.hexA(heat(dz(s.zone), -DIFF_MAX / 2, DIFF_MAX / 2), 0.45) } })) },
        { type: 'scatter', z: 4, symbol: 'roundRect', symbolSize: [62, 34], data: keys.map(k => ({ value: [pos[k].x / pos[k].n, pos[k].y / pos[k].n], zone: k,
          itemStyle: { color: QKC.hexA(T.s1, 0.9), borderColor: heat(dz(k), -DIFF_MAX / 2, DIFF_MAX / 2), borderWidth: 2 },
          label: { show: true, color: T.ink1, fontFamily: T.fontNum, fontSize: 10.5, lineHeight: 13, formatter: HW.fmtVal(zs[k].fg, 'pct') + '\n' + zs[k].fgm + '/' + zs[k].n } })) }]
    }), (HW.teamName(L, o.team) || 'Team') + ' shots by zone');
    chartKey(el, 'Each zone: field-goal % and makes over attempts. Ring and dots: points per shot against the league (blue below, red above).');
    return;
  }
  const byX = o.colour === 'xpts' && rows.some(s => isN(s.xpts));
  courtMount(el, T => {
    let made = tc ? QK.color.ensure(tc, T.s1, 3) : T.wpB;
    const miss = T.other;
    const rgb = QK.color.parse(made);
    if ((QK.color.distinct && !QK.color.distinct(made, miss)) || (rgb && Math.max(rgb[0], rgb[1], rgb[2]) - Math.min(rgb[0], rgb[1], rgb[2]) < 48)) made = T.wpB;   // a grey kit would read as a miss
    const sz = s => Math.max(5, Math.sqrt(isN(s.xpts) ? s.xpts / 3 : 0.3) * 18);
    const pts = flag => rows.filter(s => !!s.made === flag).map(s => {
      const c = byX ? heat(s.xpts, 0, 1.5) : (flag ? made : miss);
      return { value: [s.x, s.y], name: txt(s), symbolSize: sz(s), itemStyle: flag ? { color: c, borderColor: T.s1, borderWidth: 1.2 } : { color: QKC.hexA(c, byX ? 0.25 : 0.12), borderColor: c, borderWidth: 1.2 } };
    });
    return {
      legend: byX ? { show: false } : legendTop(T),
      tooltip: QKC.tooltip(T, { formatter: p => '<div style="font-weight:600">' + HW.esc(p.data.name) + '</div>' }),
      series: [{ type: 'scatter', name: 'Missed', z: 2, data: pts(false), itemStyle: { color: miss } }, { type: 'scatter', name: 'Made', z: 3, data: pts(true), itemStyle: { color: made } }]
    };
  }, (HW.teamName(L, o.team) || 'Team') + ' shot chart');
  chartKey(el, byX ? 'Colour: expected points of each shot (blue low, red high). Filled: made; ring: missed.' : 'Size: expected points of the shot. Filled: made; grey ring: missed.');
}

/* The margin through the game: the home lead above the line in its colour, the away lead below. */
function flowChart(el, flow, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  const pts = (flow || []).filter(p => p && isN(p[0]) && isN(p[1]));
  if (pts.length < 2) { empty(el, o.emptyText || 'No scoring flow for this game.'); return; }
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || 260) + 'px');
  const tMax = pts[pts.length - 1][0], tk = periodTicks(L, tMax), end = Math.max(tMax, tk.end);
  const data = [[0, 0]].concat(pts).concat([[end, pts[pts.length - 1][1]]]);
  const hn = o.home ? HW.teamAbbr(L, o.home) : 'Home', an = o.away ? HW.teamAbbr(L, o.away) : 'Away';
  QKC.mount(node, T => {
    const pc = HW.ui && o.home && o.away ? HW.ui.pair(L, o.home, o.away) : [T.wpB, T.wpA];
    return {
      grid: { left: 8, right: 16, top: 30, bottom: 30, containLabel: true },
      xAxis: QKC.axis(T, { type: 'value', min: 0, max: end, split: false, line: true, name: 'Game time', nameLocation: 'middle', nameGap: 26, ticks: { values: tk.vals, labels: tk.text } }),
      yAxis: QKC.axis(T, { fmt: v => (v > 0 ? '+' : '') + v, name: hn + ' lead (points)', nameAlign: 'left' }),
      tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: ps => { const t = ps[0].value[0]; const m = (ps[0].value[1] || 0) + ((ps[1] || { value: [0, 0] }).value[1] || 0);
        return '<div style="color:' + T.ink3 + ';font-size:11px">' + HW.esc(clockOf(L, t)) + '</div>' + (m === 0 ? 'Tied' : QKC.tipRow(m > 0 ? pc[0] : pc[1], (m > 0 ? hn : an) + ' lead', String(Math.abs(m)))); } }),
      series: [0, 1].map(k => ({ type: 'line', step: 'end', showSymbol: false, name: k ? an : hn,
        data: data.map(x => [x[0], k ? Math.min(0, x[1]) : Math.max(0, x[1])]), lineStyle: { width: 1.6, color: pc[k] }, itemStyle: { color: pc[k] }, areaStyle: { color: QKC.hexA(pc[k], 0.22) },
        markLine: k ? undefined : { silent: true, symbol: 'none', label: { show: false }, data: [{ yAxis: 0, lineStyle: { color: T.axis, type: [3, 3] } }].concat(tk.lines.map(x => ({ xAxis: x, lineStyle: { color: T.grid, type: [2, 3] } }))) } }))
    };
  }, { label: 'Margin through the game' });
}

/* Our live win chance through the game (ESPN's own number dashed), the biggest swings numbered. */
function wpChart(el, wp, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  const m = ((wp && wp.model) || []).filter(p => p && isN(p[0]) && isN(p[1]));
  const e = ((wp && wp.espn) || []).filter(p => p && isN(p[0]) && isN(p[1]));
  const ref = m.length > 1 ? m : e;
  if (ref.length < 2) { empty(el, o.emptyText || 'No win probability for this game.'); return; }
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || 300) + 'px');
  const tMax = ref[ref.length - 1][0], tk = periodTicks(L, tMax);
  const plays = (o.plays || []).filter(p => isN(p.wpa) && isN(p.t)).slice().sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa)).slice(0, o.top || 6);
  const pc = HW.ui && o.home && o.away ? HW.ui.pair(L, o.home, o.away) : [null, null];
  QKC.winProb(node, {
    t: ref.map(x => x[0]), p: ref.map(x => x[1]), step: true, tMin: 0, tMax: Math.max(tMax, tk.end), periods: tk.lines,
    home: { name: HW.teamName(L, o.home), abbr: HW.teamAbbr(L, o.home), colour: pc[0] }, away: { name: HW.teamName(L, o.away), abbr: HW.teamAbbr(L, o.away), colour: pc[1] },
    tFmt: v => { const i = tk.vals.findIndex(x => Math.abs(x - v) < 1); return i >= 0 ? tk.text[i] : ''; }, interval: periodLen(L) / 2, tLabel: t => clockOf(L, t),
    events: plays.map((x, i) => ({ t: x.t, label: String(i + 1) })),
    compare: m.length > 1 && e.length > 1 ? { name: 'ESPN', t: e.map(x => x[0]), p: e.map(x => x[1]) } : null,
    label: 'Win chance through the game'
  });
}

/* Who was on the floor when: one row per player (starters first), a bar for each stint. */
function rotationChart(el, rotation, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  const rot = rotation || {};
  let ids = Object.keys(rot).filter(id => (rot[id] || []).length);
  if (!ids.length) { empty(el, o.emptyText || 'No rotation data.'); return; }
  const secs = id => (rot[id] || []).reduce((a, iv) => a + Math.max(0, (iv[1] || 0) - (iv[0] || 0)), 0);
  const first = id => Math.min.apply(null, rot[id].map(iv => iv[0]));
  if (o.order && o.order.length) ids = o.order.filter(id => rot[id]).concat(ids.filter(id => o.order.indexOf(id) < 0));
  else ids.sort((a, b) => (first(a) - first(b)) || (secs(b) - secs(a)));
  const name = o.names || (id => HW.playerShort(L, id));
  const labels = ids.map(id => name(id) + ' ' + Math.round(secs(id) / 60) + '′');
  const tMax = o.tMax || Math.max.apply(null, ids.map(id => Math.max.apply(null, rot[id].map(iv => iv[1]))));
  const tk = periodTicks(L, tMax), end = Math.max(tMax, tk.end);
  const segs = [];
  ids.forEach((id, i) => rot[id].forEach(iv => segs.push([iv[0], iv[1], i, name(id)])));
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || Math.max(240, ids.length * 22 + 70)) + 'px');
  QKC.mount(node, T => {
    const c = o.team ? QK.color.ensure(HW.teamColour(L, o.team), T.s1, 3) : T.model;
    const ya = QKC.axis(T, { type: 'category', data: labels, inverse: true, split: false });
    ya.axisLabel.color = T.ink2; ya.axisLabel.fontSize = 10.5;
    QKC.nameAxis(ya, 'Player (minutes)', 'side');
    return {
      grid: { left: 8, right: 14, top: 28, bottom: 30, containLabel: true },
      xAxis: QKC.axis(T, { type: 'value', min: 0, max: end, split: false, line: true, name: 'Game time', nameLocation: 'middle', nameGap: 26, ticks: { values: tk.vals, labels: tk.text } }),
      yAxis: ya,
      tooltip: QKC.tooltip(T, { formatter: p => { const s = segs[p.dataIndex]; return '<div style="font-weight:600">' + HW.esc(s[3]) + '</div>' + HW.esc(clockOf(L, s[0]) + ' → ' + clockOf(L, s[1]) + ' (' + HW.fmtSec(s[1] - s[0]) + ')'); } }),
      series: [{ type: 'custom', data: segs.map(s => [s[0], s[1], s[2]]), encode: { x: [0, 1], y: 2 },
        renderItem: (params, api) => { const a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]), h = api.size([0, 1])[1] * 0.62;
          return { type: 'rect', shape: { x: a[0], y: a[1] - h / 2, width: Math.max(1, b[0] - a[0]), height: h, r: 2 }, style: { fill: QKC.hexA(c, 0.88) } }; },
        markLine: tk.lines.length ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: T.grid, type: [2, 3] }, data: tk.lines.map(x => ({ xAxis: x })) } : undefined }]
    };
  }, { label: 'Rotation: who was on the floor when' });
}

/* Seed (or any position) distribution as a heat map: rows [{ label, dist: [p per seed] }]. */
function posHeatmap(el, rows, opts) {
  const o = opts || {};
  const list = (rows || []).filter(r => (r.dist || []).length);
  if (!list.length) { empty(el, 'No seed distribution.'); return; }
  const n = Math.max.apply(null, list.map(r => r.dist.length));
  const xs = Array.from({ length: n }, (_, i) => (o.labels ? String(o.labels[i]) : String(i + 1)));
  const data = [];
  list.forEach((r, yi) => r.dist.forEach((p, xi) => { if (isN(p) && p > 0) data.push([xi, yi, p]); }));
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || Math.max(260, list.length * 24 + 110)) + 'px');
  QKC.heatmap(node, { x: xs, y: list.map(r => r.label), data: data, min: 0, max: o.zmax || Math.max.apply(null, data.map(d => d[2])), fmt: v => Math.round(v * 100) + '%',
    labelIf: v => v >= 0.095, xName: o.xTitle || 'Final seed', yName: o.yTitle || 'Team', label: 'Chance of each final seed' });
}

/* Our chance as horizontal bars (team colours), the market a grey tick where there is one. */
function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => isN(i.p) && (i.p > 0 || isN(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || Math.max(220, list.length * 28 + 70)) + 'px');
  QKC.chances(node, { rows: list.map(i => ({ label: i.label, p: i.p, market: isN(i.market) ? i.market : null, color: i.colour || null, href: i.href })),
    valName: o.xTitle || 'Chance', marketName: o.marketName || 'Market (reference)', oursName: o.modelName || 'Our chance', labelWidth: o.labelWidth || 130 });
}

/* Lines with optional bands and error bars: series [{ name, x, y, colour, dash, width, err, band: [lo, hi] }];
 * opts { xTitle, yTitle, height, xaxis: { type: 'date' }, yaxis: { tickformat }, legend } */
function lines(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => (s.y || []).length);
  if (!list.length) { empty(el, o.emptyText || 'No data.'); return; }
  const node = nodeOf(el);
  node.style.setProperty('--h', (o.height || 360) + 'px');
  const xt = o.xaxis && o.xaxis.type === 'date' ? 'time' : (list.every(s => (s.x || s.y.map((_, k) => k + 1)).every(isN)) ? 'value' : 'category');
  const xv = v => (xt === 'time' ? Date.parse(v) : v);
  const pct = o.yaxis && /%/.test(String(o.yaxis.tickformat || ''));
  const xs = xt === 'category' ? (list[0].x || list[0].y.map((_, k) => k + 1)) : undefined;
  QKC.line(node, {
    xType: xt, x: xs,
    series: list.map(s => {
      const x = s.x || s.y.map((_, k) => k + 1);
      return { name: s.name, color: s.colour, dash: s.dash && s.dash !== 'solid', width: s.width, err: s.err,
        data: xt === 'category' ? s.y : s.y.map((v, k) => [xv(x[k]), v]),
        band: s.band && s.band[0] && s.band[1] ? { lo: s.band[0], hi: s.band[1], x: xt === 'category' ? undefined : x.map(xv) } : undefined };
    }),
    xName: o.xTitle || (xt === 'time' ? 'Date' : ''), yName: o.yTitle || '', yScale: true,
    xFmt: xt === 'time' ? (v => HW.fmtDate(new Date(v).toISOString(), { year: false, weekday: false })) : undefined,
    xLabel: xt === 'time' ? (v => HW.fmtDate(new Date(v).toISOString(), { weekday: false })) : undefined,
    yFmt: pct ? (v => Math.round(v * 100) + '%') : (v => HW.num(v, Math.abs(v) < 10 ? 1 : 0)), legend: o.legend === true, label: o.label || o.yTitle
  });
}

/* Percentile radar: series [{ name, values: [0-100], colour }], opts { labels }. */
function radar(el, series, opts) {
  const o = opts || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(isN));
  const node = nodeOf(el);
  if (!node) return;
  if (!list.length || labels.length < 3) { empty(el, o.emptyText || 'Not enough data for a radar.'); return; }
  node.style.setProperty('--h', (o.height || 380) + 'px');
  QKC.mount(node, T => {
    const narrow = (node.clientWidth || 600) < 480;
    return {
      legend: list.length > 1 ? { bottom: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2 } } : { show: false },
      radar: { indicator: labels.map(l => ({ name: String(l).replace(/<br>/g, '\n'), max: 100, min: 0 })), radius: narrow ? '58%' : '68%', center: ['50%', list.length > 1 ? '47%' : '52%'],
        axisName: { color: T.ink2, fontSize: narrow ? 9 : 10.5, fontFamily: T.fontUI }, splitNumber: 4,
        splitLine: { lineStyle: { color: T.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: T.grid } } },
      tooltip: QKC.tooltip(T, { formatter: p => '<div style="font-weight:600">' + HW.esc(p.name) + '</div>' + labels.map((l, i) => QKC.tipRow(p.color, String(l).replace(/<br>/g, ' '), isN(p.value[i]) ? Math.round(p.value[i]) + 'th percentile' : '—')).join('') }),
      series: [{ type: 'radar', symbolSize: 4, data: list.map((s, i) => {
        const c = s.colour ? QK.color.ensure(s.colour, T.s1, 3) : (i ? T.wpB : T.model);
        return { name: s.name, value: s.values.map(v => (isN(v) ? v : 0)), lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, areaStyle: { color: QKC.hexA(c, 0.16) } };
      }) }]
    };
  }, { label: 'Percentile radar' });
}

/* League-relative cells on the court: cells [{ x, y, n, fg, pps, pps_diff | lg_pps | league_pps }]. */
function cellChart(el, L, cells, opts) {
  const o = opts || {};
  const rows = (cells || []).filter(c => isN(c.x) && isN(c.y) && c.y <= 41.5);
  if (!rows.length) { empty(el, 'No located shots.'); return; }
  const diffOf = c => (isN(c.pps_diff) ? c.pps_diff : isN(c.pps) && isN(c.lg_pps) ? c.pps - c.lg_pps : isN(c.pps) && isN(c.league_pps) ? c.pps - c.league_pps : null);
  const maxN = Math.max.apply(null, rows.map(c => c.n || 1));
  const diffs = rows.map(diffOf);
  const step = o.size || 1.6;
  courtMount(el, T => ({
    tooltip: QKC.tooltip(T, { formatter: p => { const c = rows[p.dataIndex], d = diffs[p.dataIndex];
      return '<div style="font-weight:600">' + (c.n || 0) + ' shots · FG ' + HW.fmtVal(c.fg, 'pct') + '</div>' + QKC.tipRow(p.color, 'Points per shot', HW.num(c.pps, 2)) + (isN(d) ? QKC.tipRow(T.ink3, 'v league', HW.signed(d, 2)) : ''); } }),
    series: [{ type: 'custom', data: rows.map(c => [c.x, c.y]), encode: { x: 0, y: 1 },
      renderItem: (params, api) => { const c = rows[params.dataIndex];
        return { type: 'polygon', shape: { points: hexPoly(api, c.x, c.y, step * (0.35 + 0.65 * Math.sqrt((c.n || 1) / maxN))) }, style: { fill: QKC.hexA(heat(diffs[params.dataIndex], -0.4, 0.4), 0.9), stroke: T.s1, lineWidth: 0.6 } }; } }]
  }), o.title || 'Shot cells');
  chartKey(el, (o.title ? '<b>' + HW.esc(o.title) + '</b> · ' : '') + 'Size: attempts. Colour: points per shot against the league from the same spot (blue below, red above).');
}

HW.charts = Object.assign(HW.charts || {}, {
  courtMount: courtMount, chartKey: chartKey, cellChart: cellChart, shotRows: shotRows, shotChart: shotChart, zoneStats: zoneStats, zoneTable: zoneTable,
  leagueZones: leagueZones, gridCells: gridCells, hexBin: hexBin, ZONE_LABEL: ZONE_LABEL, ZONE_ORDER: ZONE_ORDER,
  periodLen: periodLen, periodStart: periodStart, periodAt: periodAt, periodTicks: periodTicks, clockOf: clockOf,
  flowChart: flowChart, wpChart: wpChart, rotationChart: rotationChart,
  heatTable: heatTable, posHeatmap: posHeatmap, probBars: probBars, lines: lines, radar: radar, hexA: hexA
});
})(window.HW);
