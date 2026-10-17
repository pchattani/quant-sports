/* The Quant Hardwood — shared chart helpers (HW.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when
 * its data is missing. Times are seconds of game time from tip-off (t); periods are
 * 12 minutes in the NBA and 10 in the WNBA, overtimes 5.
 *
 *   court(L, opts)                         Plotly shapes for a half court in feet, rim at (0,0), y up the floor
 *                                          opts {colour, width, full:false}
 *   shotRows(shots)                        {cols, rows} | [obj] -> [obj] with x, y, made, value, xpts, zone, player, team, type, t
 *   shotChart(el, shots, opts)             opts {league, mode:'dots'|'hex'|'zone', colour:'made'|'xpts', grid: shots_league.json,
 *                                          team (filter), player (filter), height, hexSize:1.6, title}
 *   zoneStats(shots)                       {zone: {n, fgm, fg, pps, xpps, freq}}
 *   zoneTable(zones, opts)                 HTML; zones ZONES {zone: {freq, fg, pps, league_pps}} or zoneStats output;
 *                                          opts {league: {zone: {pps, fg, freq}}}
 *   leagueZones(grid)                      shots_league.json -> {zone: {freq, fg, pps}}
 *   periodLen(L) / periodAt(L, t) / periodTicks(L, tMax)
 *   flowChart(el, flow, opts)              flow [[t, margin_home]]; opts {league, home, away, height}
 *   wpChart(el, wp, opts)                  wp {model:[[t,p]], espn:[[t,p]]}; opts {league, home, away, plays, top:6, height}
 *   rotationChart(el, rotation, opts)      rotation {pid: [[t0,t1]...]} for one team; opts {league, team, order, names(pid), height, tMax}
 *   heatTable(spec)                        returns HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   posHeatmap(el, rows, opts)             rows [{label, dist:[p per seed]}]; opts {labels, height, zmax}
 *   probBars(el, items, opts)              items [{label, p, colour, market}] horizontal bars, market as a marker
 *   lines(el, series, opts)                series [{name, x, y, colour, dash, width, err, band:[lo,hi] arrays}]
 *   radar(el, series, opts)                series [{name, values:[0-100], colour}]; opts {labels, height}
 */
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

// ── court ──────────────────────────────────────────────────────────────────

const BASE_Y = -5.25;
function arcPath(cx, cy, r, a0, a1, n) {
  const pts = [];
  const k = n || 40;
  for (let i = 0; i <= k; i++) {
    const a = a0 + (a1 - a0) * i / k;
    pts.push((cx + r * Math.cos(a)).toFixed(3) + ',' + (cy + r * Math.sin(a)).toFixed(3));
  }
  return pts;
}
function court(L, opts) {
  const o = opts || {};
  const league = HW.isLeague(L) ? L : HW.state.league;
  const col = o.colour || 'rgba(139,148,158,0.55)';
  const w = o.width || 1.2;
  const line = { color: col, width: w };
  const R3 = league === 'wnba' ? 22.15 : 23.75;
  const corner = 22;
  const yJoin = Math.sqrt(Math.max(0, R3 * R3 - corner * corner));
  const top = o.full ? 41.75 : 41.75;
  const ftY = 19 + BASE_Y;
  const shapes = [];
  const path = (pts, extra) => shapes.push(Object.assign({ type: 'path', path: 'M ' + pts.join(' L '), line: line, layer: 'below' }, extra || {}));
  // boundary and half-court line
  shapes.push({ type: 'rect', x0: -25, x1: 25, y0: BASE_Y, y1: top, line: line, layer: 'below' });
  // paint (16 ft) and the free-throw circle
  shapes.push({ type: 'rect', x0: -8, x1: 8, y0: BASE_Y, y1: ftY, line: line, layer: 'below' });
  path(arcPath(0, ftY, 6, 0, Math.PI, 40));
  path(arcPath(0, ftY, 6, Math.PI, 2 * Math.PI, 40), { line: { color: col, width: w, dash: 'dot' } });
  // restricted area (4 ft), backboard and rim
  path(['-4,-1'].concat(arcPath(0, 0, 4, Math.PI, 0, 30)).concat(['4,-1']));
  shapes.push({ type: 'line', x0: -3, x1: 3, y0: -1.25, y1: -1.25, line: { color: col, width: w + 0.6 }, layer: 'below' });
  shapes.push({ type: 'circle', x0: -0.75, x1: 0.75, y0: -0.75, y1: 0.75, line: { color: C.wood, width: w + 0.4 }, layer: 'below' });
  // three-point line: corners, then the arc
  const a0 = Math.atan2(yJoin, corner), a1 = Math.PI - a0;
  path([corner + ',' + BASE_Y, corner + ',' + yJoin.toFixed(3)].concat(arcPath(0, 0, R3, a0, a1, 60)).concat([(-corner) + ',' + yJoin.toFixed(3), (-corner) + ',' + BASE_Y]));
  // centre circle at half court
  path(arcPath(0, top, 6, Math.PI, 2 * Math.PI, 30));
  return shapes;
}
function courtLayout(L, extra) {
  const o = extra || {};
  const yMax = o.yMax || 36;
  return HW.layout(Object.assign({
    height: o.height || 440,
    shapes: court(L).concat(o.shapes || []),
    xaxis: { range: [-25.5, 25.5], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, showline: false },
    yaxis: { range: [BASE_Y - 0.5, yMax], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1, showline: false },
    margin: { l: 6, r: 6, t: o.title ? 26 : 6, b: 6 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02, y: 0.99 } : undefined,
    showlegend: !!o.legend, legend: { orientation: 'h', x: 0, y: 1.0, yanchor: 'bottom', font: { size: 10, color: C.text2 } }
  }, o.layout || {}));
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
const DIV_SCALE = [[0, '#3b82f6'], [0.5, '#6b7280'], [1, '#ef4444']];
const XP_SCALE = [[0, '#1f4f8a'], [0.35, '#2f7fd8'], [0.6, '#d29922'], [1, '#f85149']];

function shotChart(el, shots, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  let rows = shotRows(shots);
  if (o.team) rows = rows.filter(s => String(s.team) === String(o.team));
  if (o.player) rows = rows.filter(s => String(s.player) === String(o.player));
  if (!rows.length) { empty(el, o.emptyText || 'No shot locations for this selection.'); return; }
  const mode = o.mode || 'dots';
  const cells = gridCells(o.grid);
  const traces = [];
  const lay = { height: o.height, title: o.title, yMax: o.yMax };
  if (mode === 'hex') {
    const bins = hexBin(rows, o.hexSize || 1.6);
    const maxN = Math.max.apply(null, bins.map(b => b.n)) || 1;
    const rel = cells.length > 0;
    const vals = bins.map(b => {
      const pps = b.pts / b.n;
      if (rel) { const c = nearestCell(cells, b.x, b.y); const lp = c ? (HW.isNum(c.pps) ? c.pps : null) : null; return HW.isNum(lp) ? pps - lp : null; }
      return pps;
    });
    traces.push({
      type: 'scatter', mode: 'markers', x: bins.map(b => b.x), y: bins.map(b => b.y),
      marker: { symbol: 'hexagon', size: bins.map(b => 6 + 16 * Math.sqrt(b.n / maxN)), color: vals.map(v => (HW.isNum(v) ? v : 0)),
        colorscale: rel ? DIV_SCALE : XP_SCALE, cmin: rel ? -0.6 : 0, cmax: rel ? 0.6 : 1.6, line: { width: 0 }, opacity: 0.92,
        showscale: !o.noScale, colorbar: { thickness: 8, len: 0.5, x: 1.0, tickfont: { size: 9, color: C.text2 }, title: { text: rel ? 'PPS ±lg' : 'PPS', font: { size: 9, color: C.text2 } } } },
      text: bins.map((b, i) => b.n + ' FGA · ' + b.fgm + ' made · ' + HW.num(b.pts / b.n, 2) + ' PPS' + (rel && HW.isNum(vals[i]) ? ' (' + HW.signed(vals[i], 2) + ' v league)' : '') + (b.nx ? ' · xPPS ' + HW.num(b.xpts / b.nx, 2) : '')),
      hovertemplate: '%{text}<extra></extra>'
    });
  } else if (mode === 'zone') {
    const zs = zoneStats(rows);
    const lz = leagueZones(o.grid);
    const pos = {};
    rows.forEach(s => { const z = s.zone || 'other'; const p = pos[z] || (pos[z] = { x: 0, y: 0, n: 0 }); p.x += s.x; p.y += s.y; p.n += 1; });
    const keys = Object.keys(zs).filter(k => k !== 'heave');
    // Plot the shots faintly, coloured by zone result against the league.
    keys.forEach(k => {
      const z = zs[k], lp = (lz[k] || {}).pps;
      const d = HW.isNum(lp) ? z.pps - lp : null;
      const col = HW.isNum(d) ? (d > 0.03 ? C.red : d < -0.03 ? '#3b82f6' : '#8b949e') : C.wood;
      const pts = rows.filter(s => (s.zone || 'other') === k);
      traces.push({ type: 'scatter', mode: 'markers', x: pts.map(s => s.x), y: pts.map(s => s.y), hoverinfo: 'skip',
        marker: { size: 5, color: hexA(col.charAt(0) === '#' ? col : '#8b949e', 0.35), line: { width: 0 } } });
      const p = pos[k];
      traces.push({ type: 'scatter', mode: 'text', x: [p.x / p.n], y: [p.y / p.n],
        text: ['<b>' + HW.fmtVal(z.fg, 'pct') + '</b><br>' + z.fgm + '/' + z.n], textfont: { size: 11, color: C.text },
        hovertext: [(ZONE_LABEL[k] || k) + ': ' + z.fgm + '/' + z.n + ' · ' + HW.num(z.pps, 2) + ' PPS' + (HW.isNum(lp) ? ' (league ' + HW.num(lp, 2) + ')' : '')], hoverinfo: 'text' });
    });
  } else {
    const byX = o.colour === 'xpts' && rows.some(s => HW.isNum(s.xpts));
    const made = rows.filter(s => s.made), miss = rows.filter(s => !s.made);
    const txt = s => (s.playerName || (s.player ? HW.playerName(L, s.player) : '')) + (s.type ? ' · ' + s.type : '') + ' · ' + s.value + 'PT ' + (s.made ? 'made' : 'missed') +
      (HW.isNum(s.xpts) ? ' · xPTS ' + HW.num(s.xpts, 2) : '') + (HW.isNum(s.t) ? ' · ' + HW.charts.clockOf(L, s.t) : '');
    const mk = (list, sym, name, colour) => ({
      type: 'scatter', mode: 'markers', name: name, x: list.map(s => s.x), y: list.map(s => s.y), text: list.map(txt), hovertemplate: '%{text}<extra></extra>',
      marker: byX ? { symbol: sym, size: 8, color: list.map(s => s.xpts), colorscale: XP_SCALE, cmin: 0, cmax: 1.5,
        line: { width: sym === 'circle' ? 0.6 : 1.4, color: sym === 'circle' ? '#0d1117' : undefined }, showscale: sym === 'circle' && !o.noScale,
        colorbar: { thickness: 8, len: 0.5, tickfont: { size: 9, color: C.text2 }, title: { text: 'xPTS', font: { size: 9, color: C.text2 } } } }
        : { symbol: sym, size: sym === 'circle' ? 7 : 7, color: colour, line: { width: sym === 'circle' ? 0.6 : 1.6, color: sym === 'circle' ? '#0d1117' : colour }, opacity: 0.9 }
    });
    traces.push(mk(miss, 'x-thin-open', 'Missed', C.miss));
    traces.push(mk(made, 'circle', 'Made', C.make));
    lay.legend = !byX;
  }
  HW.plot(el, traces, courtLayout(L, lay));
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
function periodShapes(ticks) {
  return ticks.lines.map(x => ({ type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: '#30363d', width: 1, dash: 'dot' }, layer: 'below' }));
}

function flowChart(el, flow, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  const pts = (flow || []).filter(p => p && HW.isNum(p[0]) && HW.isNum(p[1]));
  if (pts.length < 2) { empty(el, o.emptyText || 'No scoring flow for this game.'); return; }
  const tMax = pts[pts.length - 1][0];
  const tk = periodTicks(L, tMax);
  const x = [0], y = [0];
  pts.forEach(p => { x.push(p[0]); y.push(p[1]); });
  x.push(Math.max(tMax, tk.end)); y.push(y[y.length - 1]);
  const hc = o.home ? HW.teamColour(L, o.home) : C.blue, ac = o.away ? HW.teamColour(L, o.away) : C.wood;
  const hn = o.home ? HW.teamAbbr(L, o.home) : 'Home', an = o.away ? HW.teamAbbr(L, o.away) : 'Away';
  const pos = y.map(v => Math.max(0, v)), neg = y.map(v => Math.min(0, v));
  const lim = Math.max(5, Math.max.apply(null, y.map(Math.abs))) * 1.1;
  HW.plot(el, [
    { type: 'scatter', mode: 'lines', x: x, y: pos, line: { shape: 'hv', width: 0, color: hc }, fill: 'tozeroy', fillcolor: hexA(hc, 0.45), hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', x: x, y: neg, line: { shape: 'hv', width: 0, color: ac }, fill: 'tozeroy', fillcolor: hexA(ac, 0.45), hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', x: x, y: y, line: { shape: 'hv', width: 1.4, color: C.text }, text: x.map((t, i) => clockOf(L, t) + ' · ' + (y[i] > 0 ? hn + ' +' + y[i] : y[i] < 0 ? an + ' +' + (-y[i]) : 'Tied')),
      hovertemplate: '%{text}<extra></extra>' }
  ], HW.layout({
    height: o.height || 280,
    shapes: periodShapes(tk),
    xaxis: { tickvals: tk.vals, ticktext: tk.text, range: [0, Math.max(tMax, tk.end)], showgrid: false, fixedrange: true },
    yaxis: { range: [-lim, lim], title: '', zeroline: true, zerolinecolor: '#8b949e', fixedrange: true, tickformat: '+d' },
    annotations: [
      { xref: 'paper', yref: 'paper', x: 0.005, y: 0.98, text: hn + ' ahead', showarrow: false, xanchor: 'left', font: { size: 10, color: hc } },
      { xref: 'paper', yref: 'paper', x: 0.005, y: 0.02, text: an + ' ahead', showarrow: false, xanchor: 'left', font: { size: 10, color: ac } }
    ],
    margin: { l: 40, r: 10, t: 10, b: 30 }
  }));
}

function wpChart(el, wp, opts) {
  const o = opts || {};
  const L = o.league || HW.state.league;
  const m = ((wp && wp.model) || []).filter(p => p && HW.isNum(p[0]) && HW.isNum(p[1]));
  const e = ((wp && wp.espn) || []).filter(p => p && HW.isNum(p[0]) && HW.isNum(p[1]));
  if (m.length < 2 && e.length < 2) { empty(el, o.emptyText || 'No win probability for this game.'); return; }
  const tMax = Math.max(m.length ? m[m.length - 1][0] : 0, e.length ? e[e.length - 1][0] : 0);
  const tk = periodTicks(L, tMax);
  const hn = o.home ? HW.teamAbbr(L, o.home) : 'Home', an = o.away ? HW.teamAbbr(L, o.away) : 'Away';
  const hc = o.home ? HW.teamColour(L, o.home) : C.blue, ac = o.away ? HW.teamColour(L, o.away) : C.wood;
  const traces = [];
  if (e.length > 1) traces.push({ type: 'scatter', mode: 'lines', name: 'ESPN', x: e.map(p => p[0]), y: e.map(p => p[1]),
    line: { color: C.text3, width: 1.4, dash: 'dot', shape: 'hv' }, text: e.map(p => clockOf(L, p[0])), hovertemplate: 'ESPN · %{text} · ' + hn + ' %{y:.1%}<extra></extra>' });
  if (m.length > 1) traces.push({ type: 'scatter', mode: 'lines', name: 'Model', x: m.map(p => p[0]), y: m.map(p => p[1]),
    line: { color: C.wood, width: 2, shape: 'hv' }, text: m.map(p => clockOf(L, p[0])), hovertemplate: 'Model · %{text} · ' + hn + ' %{y:.1%}<extra></extra>' });
  const plays = (o.plays || []).filter(p => HW.isNum(p.wpa) && HW.isNum(p.t)).slice().sort((a, b) => Math.abs(b.wpa) - Math.abs(a.wpa)).slice(0, o.top || 6);
  const ref = m.length > 1 ? m : e;
  const at = t => { let v = ref[0][1]; for (let i = 0; i < ref.length; i++) { if (ref[i][0] <= t) v = ref[i][1]; else break; } return v; };
  if (plays.length) {
    traces.push({ type: 'scatter', mode: 'markers+text', name: 'Top plays', x: plays.map(p => p.t), y: plays.map(p => at(p.t)),
      text: plays.map((p, i) => String(i + 1)), textposition: 'top center', textfont: { size: 10, color: C.text },
      marker: { size: 9, color: plays.map(p => (p.wpa > 0 ? hc : ac)), line: { width: 1.5, color: '#0d1117' } },
      hovertext: plays.map(p => clockOf(L, p.t) + ' · ' + HW.esc(String(p.text || '')).slice(0, 90) + ' · WPA ' + HW.signed(p.wpa * 100, 1) + ' pp'), hoverinfo: 'text' });
  }
  HW.plot(el, traces, HW.layout({
    height: o.height || 300,
    shapes: periodShapes(tk).concat([{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#30363d', width: 1 } }]),
    xaxis: { tickvals: tk.vals, ticktext: tk.text, range: [0, Math.max(tMax, tk.end)], showgrid: false, fixedrange: true },
    yaxis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1], ticktext: [an + ' 100%', '75%', '50%', '75%', hn + ' 100%'], fixedrange: true, automargin: true },
    showlegend: true, legend: { orientation: 'h', y: -0.16, font: { size: 10, color: C.text2 } },
    margin: { l: 70, r: 10, t: 10, b: 40 }
  }));
}

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
  const labels = ids.map(id => name(id) + ' ' + Math.round(secs(id) / 60) + "'");
  const tMax = o.tMax || Math.max.apply(null, ids.map(id => Math.max.apply(null, rot[id].map(iv => iv[1]))));
  const tk = periodTicks(L, tMax);
  const colour = o.team ? HW.teamColour(L, o.team) : C.wood;
  const base = [], xs = [], ys = [], txt = [];
  ids.forEach((id, i) => rot[id].forEach(iv => {
    base.push(iv[0]); xs.push(Math.max(1, iv[1] - iv[0])); ys.push(labels[i]);
    txt.push(name(id) + ' · ' + clockOf(L, iv[0]) + ' → ' + clockOf(L, iv[1]) + ' (' + HW.fmtSec(iv[1] - iv[0]) + ')');
  }));
  HW.plot(el, [{ type: 'bar', orientation: 'h', base: base, x: xs, y: ys, marker: { color: hexA(colour, 0.85), line: { width: 0 } },
    text: txt, hovertemplate: '%{text}<extra></extra>', textposition: 'none' }], HW.layout({
    height: o.height || Math.max(220, ids.length * 22 + 50), bargap: 0.25, barmode: 'overlay',
    shapes: periodShapes(tk),
    xaxis: { tickvals: tk.vals, ticktext: tk.text, range: [0, Math.max(tMax, tk.end)], showgrid: false, fixedrange: true },
    yaxis: { autorange: 'reversed', automargin: true, fixedrange: true, tickfont: { size: 10 }, categoryorder: 'array', categoryarray: labels },
    margin: { l: 120, r: 10, t: 6, b: 28 }
  }));
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

function posHeatmap(el, rows, opts) {
  const o = opts || {};
  const list = (rows || []).filter(r => (r.dist || []).length);
  if (!list.length) { empty(el, 'No seed distribution.'); return; }
  const n = Math.max.apply(null, list.map(r => r.dist.length));
  const z = list.map(r => { const a = r.dist.slice(); while (a.length < n) a.push(0); return a.map(p => (p > 0 ? p : null)); });
  const text = z.map(r => r.map(p => (p === null ? '' : p >= 0.095 ? Math.round(p * 100) + '' : p >= 0.01 && n <= 15 ? Math.round(p * 100) + '' : '')));
  HW.plot(el, [{
    type: 'heatmap', z: z, x: Array.from({ length: n }, (_, i) => (o.labels ? o.labels[i] : String(i + 1))), y: list.map(r => r.label),
    text: text, texttemplate: '%{text}', textfont: { size: 9, color: '#e6edf3' },
    colorscale: [[0, '#2a1a0e'], [0.15, '#6b3a17'], [0.4, '#c9773a'], [0.7, '#f0a35e'], [1, '#ffe2b8']], zmin: 0, zmax: o.zmax || null,
    hovertemplate: '%{y} · ' + HW.esc(o.xName || 'seed') + ' %{x}: %{z:.1%}<extra></extra>', xgap: 1, ygap: 1, showscale: false
  }], HW.layout({
    height: o.height || Math.max(240, list.length * 22 + 60),
    xaxis: { side: 'top', tickfont: { size: 10 }, fixedrange: true, type: 'category' }, yaxis: { autorange: 'reversed', tickfont: { size: 10 }, fixedrange: true, automargin: true, type: 'category' },
    margin: { l: 110, r: 10, t: 30, b: 10 }
  }));
}

function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => HW.isNum(i.p) && (i.p > 0 || HW.isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const rev = list.slice().reverse();
  const max = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  const traces = [{
    type: 'bar', orientation: 'h', y: rev.map(i => i.label), x: rev.map(i => i.p), name: o.modelName || 'Model',
    text: rev.map(i => HW.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.wood) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => HW.isNum(i.market))) {
    const m = rev.filter(i => HW.isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: m.map(i => i.label), x: m.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  HW.plot(el, traces, HW.layout({
    height: o.height || Math.max(220, list.length * 28 + 50), bargap: 0.3,
    xaxis: { tickformat: '.0%', range: [0, Math.min(1.08, max * 1.25 + 0.02)], fixedrange: true },
    yaxis: { automargin: true, fixedrange: true, tickfont: { size: 11 } },
    showlegend: traces.length > 1, legend: { orientation: 'h', y: -0.12, font: { color: C.text2 } },
    margin: { l: 110, r: 50, t: 10, b: 35 }
  }));
}

function lines(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => (s.y || []).length);
  if (!list.length) { empty(el, o.emptyText || 'No data.'); return; }
  const traces = [];
  list.forEach((s, i) => {
    const col = s.colour || HW.PALETTE[i % HW.PALETTE.length];
    const x = s.x || s.y.map((_, k) => k + 1);
    if (s.band && s.band[0] && s.band[1]) {
      traces.push({ type: 'scatter', mode: 'lines', x: x, y: s.band[1], line: { width: 0, color: col }, hoverinfo: 'skip', showlegend: false });
      traces.push({ type: 'scatter', mode: 'lines', x: x, y: s.band[0], line: { width: 0, color: col }, fill: 'tonexty', fillcolor: hexA(col, 0.15), hoverinfo: 'skip', showlegend: false });
    }
    traces.push({
      type: 'scatter', mode: s.mode || o.mode || 'lines', name: s.name, x: x, y: s.y,
      line: { color: col, width: s.width || 2, dash: s.dash || 'solid', shape: s.shape || 'linear' },
      marker: { size: 5, color: col }, connectgaps: true, text: s.text,
      error_y: s.err ? { type: 'data', array: s.err, visible: true, color: col, thickness: 1, width: 0 } : undefined,
      hovertemplate: s.hover || (HW.esc(s.name) + ' · %{y}<extra></extra>')
    });
  });
  HW.plot(el, traces, HW.layout(Object.assign({
    height: o.height || 380, showlegend: o.legend !== false,
    legend: { orientation: 'h', y: -0.2, font: { size: 10, color: C.text2 } },
    xaxis: Object.assign({ title: o.xTitle || '' }, o.xaxis || {}), yaxis: Object.assign({ title: o.yTitle || '' }, o.yaxis || {}),
    margin: { l: 55, r: 20, t: 20, b: 55 }
  }, o.layout || {})));
}

function radar(el, series, opts) {
  const o = opts || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(HW.isNum));
  if (!list.length || !labels.length) { empty(el, o.emptyText || 'Not enough data for a radar.'); return; }
  const traces = list.map((s, i) => {
    const col = s.colour || HW.PALETTE[i % HW.PALETTE.length];
    const r = s.values.map(v => (HW.isNum(v) ? v : 0));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself',
      fillcolor: hexA(col, 0.18), line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + HW.esc(s.name || '') + '</extra>' };
  });
  HW.plot(el, traces, HW.layout({
    height: o.height || 360,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [0, 100], tickvals: [25, 50, 75, 100], gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 10, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 50, t: 30, b: 30 }
  }));
}

HW.charts = Object.assign(HW.charts || {}, {
  court: court, courtLayout: courtLayout, shotRows: shotRows, shotChart: shotChart, zoneStats: zoneStats, zoneTable: zoneTable,
  leagueZones: leagueZones, gridCells: gridCells, hexBin: hexBin, ZONE_LABEL: ZONE_LABEL, ZONE_ORDER: ZONE_ORDER,
  periodLen: periodLen, periodStart: periodStart, periodAt: periodAt, periodTicks: periodTicks, clockOf: clockOf,
  flowChart: flowChart, wpChart: wpChart, rotationChart: rotationChart,
  heatTable: heatTable, posHeatmap: posHeatmap, probBars: probBars, lines: lines, radar: radar, hexA: hexA
});
})(window.HW);
