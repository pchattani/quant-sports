/* The Quant Bullpen — shared chart helpers (BP.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its
 * data is missing. Pitch rows follow PAYLOADS.md games/<gpk>.json "pitches" (objects, or
 * {cols|fields, rows} column-oriented: normalise with BP.charts.rows(x)).
 *
 *   rows(x)                            [{...}] from an array of objects or {cols|fields|columns, rows}
 *   strikeZone(el, pitches, opts)      catcher's view; plate 17 in; zone from the batters' sz_top/sz_bot.
 *                                      opts {colourBy: 'type'|'call'|'stuff'|'xwoba'|'location', height, numbers (label
 *                                      pitch numbers), highlight: fn(p)->bool (ringed, e.g. missed calls), legend, zone:{top,bot},
 *                                      title, hover: fn(p)->html}
 *   sprayChart(el, balls, opts)        batted balls (hc_x, hc_y) on a field drawn from park dims {lf,lcf,cf,rcf,rf} (ft).
 *                                      opts {dims, metric: 'xwoba_plus'|'xwoba_savant'|'launch_speed', height, title, hover}
 *   movementPlot(el, data, opts)       IVB x HB (inches; HB + toward the arm side for either hand, as the build writes it;
 *                                      opts.view 'catcher' for raw Statcast pfx_x signs). data: pitches or per-type
 *                                      means [{pitch_type, hb, ivb, n|usage, velo}]. opts {throws:'R'|'L', armAngle (deg,
 *                                      0 sidearm, 90 over the top), league: {type: {hb, ivb, sd_hb, sd_ivb}} reference
 *                                      ellipses (1 sd), height, means: bool}
 *   zoneHeatmap(el, grid, opts)        grid {x:[centres], z:[centres], v:[[per z row][per x col]], n} (ft; catcher's view);
 *                                      opts {fmt, center, zmin, zmax, scale: 'div'|'seq', title, height, invert, label}
 *   wpChart(el, ours, opts)            home win probability by play: rows [[i, inning, half, p_home, label]] or objects
 *                                      {i, inning, half, p|p_home, desc}; opts {espn: same shape, top: [{i, wpa, desc}],
 *                                      home, away, height, market (pre-game market p_home)}
 *   percentileSliders(metrics, vals, pcts, opts)  HTML: Savant-style sliders (blue low, red high) grouped by METRIC.group;
 *                                      opts {groups: false, note, keys: [subset], role: 'pct_role' label}
 *   sliderRow(label, p, valueText, title)        one slider row (HTML)
 *   pitchTrend(el, rows, opts)         velocity / spin trend: rows [{x, pitch_type, y}] (x date or game no.);
 *                                      opts {yTitle, baseline: {type: v}, height, mode}
 *   linescore(g, opts)                 HTML linescore: g {home, away, innings:[[a,h]...], hs, as, linescore:{r,h,e}}; opts {link}
 *   pitchLegend(types)                 HTML legend chips for pitch types
 *   mlbBracket(el, post, opts)         the postseason bracket: post {series:[SERIES], seeds:{AL:[tid x6],NL:[...]},
 *                                      teams:{tid:{seed}}}; opts {level, narrow, onSeries(series)}
 *   distBars(el, dist, opts)           bars of {k: p}; opts {actual, exp, line, xTitle, colour, height, unit}
 *   heatTable(spec)                    HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   probBars(el, items, opts)          items [{label, p, colour, market}] horizontal bars, market as a tick
 *   lines(el, series, opts)            series [{name, x, y, colour, dash, width, err, band:[lo,hi]}]
 *   radar(el, series, opts)            series [{name, values:[0-100], colour}]; opts {labels, height}
 *   hexA(hex, a)                       rgba string
 */
(function (BP) {
'use strict';

const C = BP.C;
const esc = BP.esc;
const isNum = BP.isNum;

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
/* A height that suits an equal-aspect chart in this element: aspect x width, within [lo, hi]. */
function fitH(el, want, aspect, lo) {
  const n = node(el);
  const w = n && n.clientWidth ? n.clientWidth : 0;
  if (!w) return want;
  return Math.round(Math.max(lo || 240, Math.min(want, w * aspect)));
}
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }
function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return BP.alpha ? BP.alpha(hex, a) : 'rgba(139,148,158,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
}
/* Rows from an array of objects or a column-oriented {cols|fields|columns, rows}. */
function rows(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns;
  if (Array.isArray(cols) && Array.isArray(x.rows)) return x.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  if (Array.isArray(x.rows)) return rows(x.rows);
  return [];
}
function median(a) { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function mean(a) { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; }
const DIV_SCALE = [[0, '#2c64c8'], [0.25, '#7a9fd9'], [0.5, '#9a9a9a'], [0.75, '#e08a7a'], [1, '#d62828']];
const SEQ_SCALE = [[0, 'rgba(217,128,78,0.06)'], [0.5, 'rgba(217,128,78,0.5)'], [1, '#f0a070']];
const XWOBA_SCALE = [[0, '#3a6fd8'], [0.2, '#7aa0e0'], [0.35, '#a0a0a0'], [0.6, '#e8a060'], [1, '#e8484a']];

// ── strike zone ────────────────────────────────────────────────────────────

const PLATE_HALF = 17 / 24;          // 8.5 in, in feet
const BALL_R = 1.45 / 12;            // a ball's radius, in feet

function zoneShapes(top, bot, opts) {
  const o = opts || {};
  const sh = [];
  const w = PLATE_HALF;
  // the zone and its thirds
  sh.push({ type: 'rect', x0: -w, x1: w, y0: bot, y1: top, line: { color: '#c9d1d9', width: 1.6 }, layer: 'below' });
  const dx = 2 * w / 3, dy = (top - bot) / 3;
  for (let i = 1; i < 3; i++) {
    sh.push({ type: 'line', x0: -w + i * dx, x1: -w + i * dx, y0: bot, y1: top, line: { color: '#3d444d', width: 1, dash: 'dot' }, layer: 'below' });
    sh.push({ type: 'line', x0: -w, x1: w, y0: bot + i * dy, y1: bot + i * dy, line: { color: '#3d444d', width: 1, dash: 'dot' }, layer: 'below' });
  }
  // the edge a ball can touch and still be a strike
  if (o.edge !== false) sh.push({ type: 'rect', x0: -w - BALL_R, x1: w + BALL_R, y0: bot - BALL_R, y1: top + BALL_R, line: { color: '#30363d', width: 1, dash: 'dash' }, layer: 'below' });
  // home plate, catcher's view (the point toward the viewer)
  const py = o.plateY !== undefined ? o.plateY : 0.32;
  sh.push({ type: 'path', path: 'M ' + (-w) + ' ' + (py + 0.12) + ' L ' + w + ' ' + (py + 0.12) + ' L ' + w + ' ' + py + ' L 0 ' + (py - 0.14) + ' L ' + (-w) + ' ' + py + ' Z',
    fillcolor: 'rgba(230,237,243,0.10)', line: { color: '#8b949e', width: 1 }, layer: 'below' });
  return sh;
}
function zoneOf(list, opts) {
  const o = opts || {};
  if (o.zone && isNum(o.zone.top) && isNum(o.zone.bot)) return [Number(o.zone.top), Number(o.zone.bot)];
  const batters = {};
  list.forEach(p => { if (p.batter) batters[p.batter] = 1; });
  const f = Object.keys(batters).length === 1 ? mean : median;
  const top = f(list.map(p => p.sz_top)), bot = f(list.map(p => p.sz_bot));
  return [isNum(top) ? top : 3.45, isNum(bot) ? bot : 1.6];
}
function pitchHover(p) {
  const ci = BP.callInfo(p.desc || p.call);
  const bits = [];
  if (isNum(p.pitch_no)) bits.push('#' + p.pitch_no);
  bits.push(BP.pitchName(p.pitch_type) + (isNum(p.velo) ? ' ' + BP.num(p.velo, 1) + ' mph' : ''));
  let h = bits.join(' · ') + '<br>' + esc(ci.label) + (p.event ? ' · ' + esc(BP.eventLabel(p.event)) : '');
  if (isNum(p.balls) && isNum(p.strikes)) h += '<br>Count ' + p.balls + '-' + p.strikes;
  if (p.batter || p.pitcher) h += '<br>' + esc(p.pitcher ? BP.playerShort(p.pitcher) : '') + (p.batter ? ' to ' + esc(BP.playerShort(p.batter)) : '');
  if (isNum(p.inning)) h += ' · ' + esc(BP.inningLabel(p.inning, p.half, true));
  if (isNum(p.stuff)) h += '<br>Stuff+ ' + Math.round(p.stuff) + (isNum(p.location) ? ' · Location+ ' + Math.round(p.location) : '');
  if (isNum(p.launch_speed)) h += '<br>' + BP.num(p.launch_speed, 1) + ' mph' + (isNum(p.launch_angle) ? ' at ' + BP.num(p.launch_angle, 0) + '°' : '');
  if (isNum(p.xwoba_plus) || isNum(p.xwoba_savant)) h += '<br>xwOBA+ ' + BP.fmtAvg(p.xwoba_plus) + ' · Savant ' + BP.fmtAvg(p.xwoba_savant);
  return h;
}
function strikeZone(el, pitches, opts) {
  const o = opts || {};
  const list = rows(pitches).filter(p => isNum(p.plate_x) && isNum(p.plate_z));
  if (!list.length) { empty(el, o.emptyText || 'No pitch locations to plot.'); return; }
  const zt = zoneOf(list, o);
  const by = o.colourBy || 'type';
  const traces = [];
  const hov = o.hover || pitchHover;
  const size = list.length > 250 ? 6 : list.length > 80 ? 8 : 11;
  const base = (sub, extra) => Object.assign({
    type: 'scatter', mode: o.numbers ? 'markers+text' : 'markers',
    x: sub.map(p => Number(p.plate_x)), y: sub.map(p => Number(p.plate_z)),
    text: o.numbers ? sub.map(p => (isNum(p.pitch_no) ? String(p.pitch_no) : '')) : undefined,
    textfont: { size: 9, color: '#0d1117' }, textposition: 'middle center',
    hovertext: sub.map(hov), hoverinfo: 'text'
  }, extra);
  if (by === 'type') {
    const types = {};
    list.forEach(p => { const t = String(p.pitch_type || 'UN').toUpperCase(); (types[t] = types[t] || []).push(p); });
    BP.PITCH_ORDER.concat(Object.keys(types)).filter((t, i, a) => types[t] && a.indexOf(t) === i).forEach(t => {
      traces.push(base(types[t], { name: BP.pitchName(t), marker: { size: size, color: BP.pitchColour(t), opacity: 0.88, line: { width: 1, color: '#0d1117' } } }));
    });
  } else if (by === 'call') {
    const kinds = { ball: [], called: [], swinging: [], foul: [], inplay: [], hbp: [], other: [] };
    const lab = { ball: 'Ball', called: 'Called strike', swinging: 'Swinging strike', foul: 'Foul', inplay: 'In play', hbp: 'Hit by pitch', other: 'Other' };
    const col = { ball: '#58a6ff', called: '#f85149', swinging: '#d9804e', foul: '#d29922', inplay: '#3fb950', hbp: '#bc8cff', other: '#6e7681' };
    list.forEach(p => { const k = BP.callInfo(p.desc || p.call).kind; (kinds[k] || kinds.other).push(p); });
    Object.keys(kinds).filter(k => kinds[k].length).forEach(k => {
      traces.push(base(kinds[k], { name: lab[k], marker: { size: size, color: col[k], opacity: 0.88, symbol: k === 'swinging' ? 'x' : 'circle', line: { width: 1, color: '#0d1117' } } }));
    });
  } else {
    const key = by === 'stuff' ? 'stuff' : by === 'location' ? 'location' : (o.metric || 'xwoba_plus');
    const plus = key === 'stuff' || key === 'location';
    const has = list.filter(p => isNum(p[key])), rest = list.filter(p => !isNum(p[key]));
    if (rest.length) traces.push(base(rest, { name: 'No value', marker: { size: Math.max(5, size - 3), color: '#30363d', line: { width: 0 } } }));
    if (has.length) {
      traces.push(base(has, { name: plus ? (key === 'stuff' ? 'Stuff+' : 'Location+') : 'xwOBA+', marker: {
        size: size + (plus ? 0 : 2), color: has.map(p => Number(p[key])), colorscale: plus ? DIV_SCALE : XWOBA_SCALE,
        cmin: plus ? 70 : 0, cmax: plus ? 130 : 1.2, line: { width: 1, color: '#0d1117' },
        colorbar: { thickness: 8, len: 0.6, tickfont: { size: 9, color: C.text2 }, title: { text: plus ? (key === 'stuff' ? 'Stuff+' : 'Loc+') : 'xwOBA', font: { size: 9, color: C.text2 } }, outlinewidth: 0 }
      } }));
    }
  }
  const hl = typeof o.highlight === 'function' ? list.filter(o.highlight) : [];
  if (hl.length) {
    traces.push({ type: 'scatter', mode: 'markers', name: o.highlightName || 'Flagged', x: hl.map(p => Number(p.plate_x)), y: hl.map(p => Number(p.plate_z)),
      marker: { size: size + 9, color: 'rgba(0,0,0,0)', line: { width: 2, color: o.highlightColour || '#e6edf3' } }, hovertext: hl.map(hov), hoverinfo: 'text' });
  }
  const showLeg = o.legend !== false && traces.length > 1 && (by === 'type' || by === 'call');
  BP.plot(el, traces, BP.layout({
    height: fitH(el, o.height || 380, 1.12, 260), shapes: zoneShapes(zt[0], zt[1], o),
    xaxis: { range: [-2.1, 2.1], constrain: 'domain', zeroline: false, showgrid: false, fixedrange: true, showticklabels: false, title: { text: o.xTitle || '', font: { size: 10, color: C.text3 } } },
    yaxis: { range: [0, 4.7], zeroline: false, showgrid: false, fixedrange: true, showticklabels: false, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' },
    showlegend: showLeg, legend: { orientation: 'h', y: -0.04, x: 0.5, xanchor: 'center', font: { size: 10, color: C.text2 } },
    margin: { l: 8, r: 8, t: o.title ? 26 : 6, b: showLeg ? 40 : 24 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined
  }));
}

// ── spray chart ────────────────────────────────────────────────────────────

const HP_X = 125.42, HP_Y = 198.27, FT_PER = 2.495;
function sprayXY(b) {
  if (isNum(b.x) && isNum(b.y) && !isNum(b.hc_x)) return [Number(b.x), Number(b.y)];
  if (!isNum(b.hc_x) || !isNum(b.hc_y)) return null;
  return [FT_PER * (Number(b.hc_x) - HP_X), FT_PER * (HP_Y - Number(b.hc_y))];
}
/* The outfield wall from the five distances: polar, angle from centre field (deg, + toward right field). */
function wallPoints(dims) {
  const d = dims || {};
  const pts = [[-45, d.lf || 330], [-22.5, d.lcf || 375], [0, d.cf || 400], [22.5, d.rcf || 375], [45, d.rf || 330]];
  const out = [];
  for (let a = -45; a <= 45; a += 1.5) {
    let k = 0;
    while (k < pts.length - 2 && a > pts[k + 1][0]) k++;
    const a0 = pts[k][0], a1 = pts[k + 1][0];
    const t = (a - a0) / (a1 - a0);
    const u = (1 - Math.cos(Math.PI * t)) / 2;
    const r = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * u;
    const rad = a * Math.PI / 180;
    out.push([r * Math.sin(rad), r * Math.cos(rad)]);
  }
  return out;
}
function fieldShapes(dims) {
  const wall = wallPoints(dims);
  const sh = [];
  const first = wall[0], last = wall[wall.length - 1];
  // grass: the fair territory
  sh.push({ type: 'path', path: 'M 0 0 L ' + first[0].toFixed(1) + ' ' + first[1].toFixed(1) + ' ' + wall.map(p => 'L ' + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ') + ' Z',
    fillcolor: 'rgba(63,185,80,0.07)', line: { color: '#3d444d', width: 1 }, layer: 'below' });
  // the wall
  sh.push({ type: 'path', path: 'M ' + wall.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L '), line: { color: '#c9d1d9', width: 2.2 }, layer: 'below' });
  // foul lines
  sh.push({ type: 'line', x0: 0, y0: 0, x1: first[0], y1: first[1], line: { color: '#8b949e', width: 1.2 }, layer: 'below' });
  sh.push({ type: 'line', x0: 0, y0: 0, x1: last[0], y1: last[1], line: { color: '#8b949e', width: 1.2 }, layer: 'below' });
  // infield dirt arc (95 ft from the rubber) and the diamond
  const arc = [];
  for (let a = -45; a <= 45; a += 3) {
    const rad = a * Math.PI / 180;
    // a point at distance 95 from the rubber (0, 60.5) along this bearing from home: solve |p - rubber| = 95
    const ux = Math.sin(rad), uy = Math.cos(rad);
    const b = 2 * (-60.5 * uy), c = 60.5 * 60.5 - 95 * 95;
    const r = (-b + Math.sqrt(b * b - 4 * c)) / 2;
    arc.push([r * ux, r * uy]);
  }
  sh.push({ type: 'path', path: 'M 0 0 L ' + arc.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L ') + ' Z', fillcolor: 'rgba(217,128,78,0.10)', line: { color: 'rgba(217,128,78,0.35)', width: 1 }, layer: 'below' });
  const b = 90 / Math.SQRT2;
  sh.push({ type: 'path', path: 'M 0 0 L ' + b + ' ' + b + ' L 0 ' + (2 * b) + ' L ' + (-b) + ' ' + b + ' Z', line: { color: '#8b949e', width: 1 }, fillcolor: 'rgba(63,185,80,0.08)', layer: 'below' });
  return sh;
}
function ballHover(b) {
  let h = '';
  if (b.batter) h += esc(BP.playerShort(b.batter));
  if (b.event) h += (h ? ' · ' : '') + esc(BP.eventLabel(b.event));
  if (isNum(b.inning)) h += ' · ' + esc(BP.inningLabel(b.inning, b.half, true));
  if (isNum(b.launch_speed)) h += '<br>' + BP.num(b.launch_speed, 1) + ' mph' + (isNum(b.launch_angle) ? ', ' + BP.num(b.launch_angle, 0) + '°' : '');
  if (isNum(b.xwoba_plus) || isNum(b.xwoba_savant)) h += '<br>xwOBA+ ' + BP.fmtAvg(b.xwoba_plus) + ' · Savant xwOBA ' + BP.fmtAvg(b.xwoba_savant);
  return h || 'Batted ball';
}
function sprayChart(el, balls, opts) {
  const o = opts || {};
  const list = rows(balls).map(b => ({ b: b, xy: sprayXY(b) })).filter(x => x.xy);
  const dims = o.dims || {};
  const key = o.metric || 'xwoba_plus';
  const wall = wallPoints(dims);
  const maxR = Math.max.apply(null, wall.map(p => Math.hypot(p[0], p[1]))) || 400;
  const traces = [];
  if (list.length) {
    const has = list.filter(x => isNum(x.b[key])), rest = list.filter(x => !isNum(x.b[key]));
    const sym = x => (BP.isHit(x.b.event) ? 'circle' : 'circle-open');
    if (rest.length) traces.push({ type: 'scatter', mode: 'markers', name: 'No value', x: rest.map(x => x.xy[0]), y: rest.map(x => x.xy[1]),
      marker: { size: 8, color: '#6e7681', symbol: rest.map(sym), line: { width: 1.5, color: '#6e7681' } }, hovertext: rest.map(x => ballHover(x.b)), hoverinfo: 'text' });
    if (has.length) {
      const ls = key === 'launch_speed';
      traces.push({ type: 'scatter', mode: 'markers', name: key, x: has.map(x => x.xy[0]), y: has.map(x => x.xy[1]),
        marker: { size: 10, color: has.map(x => Number(x.b[key])), colorscale: XWOBA_SCALE, cmin: ls ? 60 : 0, cmax: ls ? 110 : 1.2,
          symbol: has.map(sym), line: { width: has.map(x => (BP.isHit(x.b.event) ? 1 : 2)), color: '#0d1117' },
          colorbar: { thickness: 8, len: 0.5, y: 0.7, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0,
            title: { text: ls ? 'EV' : (key === 'xwoba_savant' ? 'Savant' : 'xwOBA+'), font: { size: 9, color: C.text2 } } } },
        hovertext: has.map(x => ballHover(x.b)), hoverinfo: 'text' });
    }
  }
  const lim = maxR * 1.04;
  BP.plot(el, traces.length ? traces : [{ type: 'scatter', x: [0], y: [0], mode: 'markers', marker: { size: 1, color: 'rgba(0,0,0,0)' }, hoverinfo: 'skip' }], BP.layout({
    height: fitH(el, o.height || 380, 0.82, 240), shapes: fieldShapes(dims),
    xaxis: { range: [-lim * 0.76, lim * 0.76], constrain: 'domain', showgrid: false, zeroline: false, showticklabels: false, fixedrange: true },
    yaxis: { range: [-25, lim], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' },
    annotations: o.labels === false ? [] : [
      { x: wall[0][0] * 0.92, y: wall[0][1] * 0.92 + 18, text: (dims.lf || '') + '', showarrow: false, font: { size: 9, color: C.text3 } },
      { x: 0, y: (dims.cf || 400) + 14, text: (dims.cf || '') + '', showarrow: false, font: { size: 9, color: C.text3 } },
      { x: wall[wall.length - 1][0] * 0.92, y: wall[wall.length - 1][1] * 0.92 + 18, text: (dims.rf || '') + '', showarrow: false, font: { size: 9, color: C.text3 } }
    ],
    margin: { l: 4, r: 4, t: o.title ? 24 : 4, b: 4 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined
  }));
  if (!list.length && o.emptyText) { const n = node(el); if (n) n.insertAdjacentHTML('beforeend', '<div class="chart-note">' + esc(o.emptyText) + '</div>'); }
}

// ── movement ───────────────────────────────────────────────────────────────

function ellipsePath(cx, cy, rx, ry) {
  const pts = [];
  for (let a = 0; a <= 360; a += 12) { const r = a * Math.PI / 180; pts.push((cx + rx * Math.cos(r)).toFixed(2) + ' ' + (cy + ry * Math.sin(r)).toFixed(2)); }
  return 'M ' + pts.join(' L ') + ' Z';
}
function movementPlot(el, data, opts) {
  const o = opts || {};
  const list = rows(data).filter(p => isNum(p.hb) && isNum(p.ivb));
  if (!list.length) { empty(el, o.emptyText || 'No movement data.'); return; }
  const means = o.means !== undefined ? o.means : list.every(p => isNum(p.n) || isNum(p.usage));
  const traces = [];
  const shapes = [
    { type: 'line', x0: -26, x1: 26, y0: 0, y1: 0, line: { color: '#30363d', width: 1 }, layer: 'below' },
    { type: 'line', x0: 0, x1: 0, y0: -26, y1: 26, line: { color: '#30363d', width: 1 }, layer: 'below' }
  ];
  [6, 12, 18, 24].forEach(r => shapes.push({ type: 'circle', x0: -r, x1: r, y0: -r, y1: r, line: { color: '#21262d', width: 1 }, layer: 'below' }));
  const lg = o.league || {};
  Object.keys(lg).forEach(t => {
    const r = lg[t];
    if (!r || !isNum(r.hb) || !isNum(r.ivb)) return;
    const col = BP.pitchColour(t);
    shapes.push({ type: 'path', path: ellipsePath(Number(r.hb), Number(r.ivb), isNum(r.sd_hb) ? Number(r.sd_hb) : 3, isNum(r.sd_ivb) ? Number(r.sd_ivb) : 3),
      line: { color: hexA(col, 0.55), width: 1, dash: 'dot' }, fillcolor: hexA(col, 0.06), layer: 'below' });
  });
  const ann = [];
  // HB convention: 'arm' (default, as the build writes it: + toward the pitcher's arm side for either hand) or
  // 'catcher' (Statcast pfx_x: + toward first base, so a right-hander's arm side is negative)
  const throwsL = String(o.throws || '').toUpperCase() === 'L';
  const catcherView = o.view === 'catcher';
  const armSign = catcherView ? (throwsL ? 1 : -1) : 1;
  if (isNum(o.armAngle)) {
    const a = Number(o.armAngle) * Math.PI / 180;
    shapes.push({ type: 'line', x0: 0, y0: 0, x1: armSign * 24 * Math.cos(a), y1: 24 * Math.sin(a), line: { color: C.clay, width: 2, dash: 'dash' } });
    ann.push({ x: armSign * 25 * Math.cos(a), y: 25 * Math.sin(a) + 1.5, text: 'Arm angle ' + Math.round(o.armAngle) + '°', showarrow: false, font: { size: 10, color: C.clay } });
  }
  if (o.throws || !catcherView) {
    ann.push({ x: armSign * 22, y: -24, text: 'Arm side', showarrow: false, font: { size: 10, color: C.text3 } });
    ann.push({ x: -armSign * 22, y: -24, text: 'Glove side', showarrow: false, font: { size: 10, color: C.text3 } });
  }
  const types = {};
  list.forEach(p => { const t = String(p.pitch_type || 'UN').toUpperCase(); (types[t] = types[t] || []).push(p); });
  BP.PITCH_ORDER.concat(Object.keys(types)).filter((t, i, a) => types[t] && a.indexOf(t) === i).forEach(t => {
    const sub = types[t];
    const col = BP.pitchColour(t);
    const size = means ? sub.map(p => 12 + 26 * Math.sqrt(Math.max(0, Number(isNum(p.usage) ? p.usage : 0.15)))) : (list.length > 300 ? 5 : 7);
    traces.push({ type: 'scatter', mode: means ? 'markers+text' : 'markers', name: BP.pitchName(t), x: sub.map(p => Number(p.hb)), y: sub.map(p => Number(p.ivb)),
      text: means ? sub.map(() => t) : undefined, textfont: { size: 9, color: '#0d1117' },
      marker: { size: size, color: col, opacity: means ? 0.95 : 0.6, line: { width: 1, color: '#0d1117' } },
      hovertext: sub.map(p => esc(BP.pitchName(t)) + (isNum(p.velo) ? ' · ' + BP.num(p.velo, 1) + ' mph' : '') + '<br>IVB ' + BP.num(p.ivb, 1) + ' in · HB ' + BP.num(p.hb, 1) + ' in' +
        (isNum(p.usage) ? '<br>Usage ' + BP.pct(p.usage, 0) : '') + (isNum(p.stuff) ? ' · Stuff+ ' + Math.round(p.stuff) : '')), hoverinfo: 'text' });
  });
  BP.plot(el, traces, BP.layout({
    height: fitH(el, o.height || 400, 1.0, 280), shapes: shapes, annotations: ann,
    xaxis: { range: [-27, 27], constrain: 'domain', zeroline: false, fixedrange: true, title: { text: catcherView ? 'Horizontal break (in, catcher\'s view)' : 'Horizontal break (in, + toward the arm side)', font: { size: 10 } }, dtick: 6 },
    yaxis: { range: [-27, 27], zeroline: false, fixedrange: true, title: { text: 'Induced vertical break (in)', font: { size: 10 } }, dtick: 6, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' },
    showlegend: !means && Object.keys(types).length > 1, legend: { orientation: 'h', y: -0.18, font: { size: 10, color: C.text2 } },
    margin: { l: 48, r: 10, t: 10, b: 44 }
  }));
}

// ── zone heatmap ───────────────────────────────────────────────────────────

function zoneHeatmap(el, grid, opts) {
  const o = opts || {};
  const g = grid || {};
  let xs = g.x || g.xs, zs = g.z || g.zs, v = g.v || g.values;
  if (Array.isArray(g) && g.length && Array.isArray(g[0])) {
    v = g;
    const nx = g[0].length, nz = g.length;
    xs = Array.from({ length: nx }, (_, i) => -1.4 + (2.8 * (i + 0.5)) / nx);
    zs = Array.from({ length: nz }, (_, i) => 1.0 + (3.4 * (i + 0.5)) / nz);
  }
  if (!Array.isArray(v) || !v.length || !Array.isArray(xs) || !Array.isArray(zs)) { empty(el, o.emptyText || 'No zone data.'); return; }
  const flat = [];
  v.forEach(r => (r || []).forEach(x => { if (isNum(x)) flat.push(Number(x)); }));
  if (!flat.length) { empty(el, o.emptyText || 'No zone data.'); return; }
  const seq = o.scale === 'seq';
  let zmin = o.zmin, zmax = o.zmax;
  if (!isNum(zmin) || !isNum(zmax)) {
    if (seq) { zmin = Math.min.apply(null, flat); zmax = Math.max.apply(null, flat); }
    else {
      const c = isNum(o.center) ? Number(o.center) : median(flat);
      const dev = Math.max.apply(null, flat.map(x => Math.abs(x - c))) || 1;
      zmin = c - dev; zmax = c + dev;
    }
  }
  const scale = seq ? SEQ_SCALE : (o.invert ? DIV_SCALE.map((s, i) => [s[0], DIV_SCALE[DIV_SCALE.length - 1 - i][1]]) : DIV_SCALE);
  const fmt = o.fmt ? (x => BP.fmtVal(x, o.fmt)) : (x => BP.num(x, 3));
  const text = v.map((r, i) => (r || []).map((x, j) => (isNum(x) ? fmt(x) + (g.n && g.n[i] && isNum(g.n[i][j]) ? '<br>n ' + g.n[i][j] : '') : '')));
  const top = isNum(g.sz_top) ? g.sz_top : 3.45, bot = isNum(g.sz_bot) ? g.sz_bot : 1.6;
  BP.plot(el, [{ type: 'heatmap', x: xs, y: zs, z: v, zmin: zmin, zmax: zmax, colorscale: scale, text: text, hoverinfo: 'text', xgap: 1, ygap: 1,
    colorbar: { thickness: 8, len: 0.7, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0, title: { text: o.label || '', font: { size: 9, color: C.text2 } } } }], BP.layout({
    height: o.height || 340, shapes: zoneShapes(top, bot, { edge: false, plateY: Math.min(0.55, bot - 0.5) }),
    xaxis: { constrain: 'domain', range: [Math.min(-1.6, xs[0] - 0.2), Math.max(1.6, xs[xs.length - 1] + 0.2)], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true },
    yaxis: { range: [0.1, Math.max(4.4, zs[zs.length - 1] + 0.3)], showgrid: false, zeroline: false, showticklabels: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1, constrain: 'domain' },
    margin: { l: 4, r: 4, t: o.title ? 24 : 4, b: 4 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined
  }));
}

// ── win probability ────────────────────────────────────────────────────────

function wpRows(x) {
  return (x || []).map((r, k) => {
    if (Array.isArray(r)) {
      if (r.length >= 4) return { i: Number(r[0]), inning: r[1], half: r[2], p: Number(r[3]), desc: r[4] || '' };
      return { i: Number(r[0]), p: Number(r[1]), desc: r[2] || '' };
    }
    if (r && typeof r === 'object') return { i: isNum(r.i) ? Number(r.i) : (isNum(r.idx) ? Number(r.idx) : k), inning: r.inning, half: r.half, p: Number(isNum(r.p_home) ? r.p_home : r.p), desc: r.desc || r.label || '' };
    return null;
  }).filter(r => r && isNum(r.i) && isNum(r.p));
}
function wpChart(el, ours, opts) {
  const o = opts || {};
  const R = wpRows(ours);
  const E = wpRows(o.espn);
  if (R.length < 2 && E.length < 2) { empty(el, o.emptyText || 'No win-probability path for this game yet.'); return; }
  const main = R.length >= 2 ? R : E;
  const hc = o.colours ? o.colours[0] : (o.home ? BP.teamColour(o.home) : C.home), ac = o.colours ? o.colours[1] : (o.away ? BP.teamColour(o.away) : C.away);
  const hn = o.home ? BP.teamAbbr(o.home) : 'Home', an = o.away ? BP.teamAbbr(o.away) : 'Away';
  const x = main.map(r => r.i), y = main.map(r => r.p);
  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#30363d', width: 1 } }];
  const ann = [];
  // inning separators (at each top half), labelled
  let prevInn = null;
  const starts = [];
  main.forEach((r, k) => {
    if (isNum(r.inning) && r.inning !== prevInn) { starts.push([k ? (main[k - 1].i + r.i) / 2 : r.i, r.inning]); prevInn = r.inning; }
  });
  starts.forEach((s, k) => {
    if (k) shapes.push({ type: 'line', x0: s[0], x1: s[0], yref: 'paper', y0: 0, y1: 1, line: { color: '#2b323b', width: 1, dash: 'dot' }, layer: 'below' });
    const end = k + 1 < starts.length ? starts[k + 1][0] : x[x.length - 1];
    ann.push({ x: (s[0] + end) / 2, y: 1.05, yref: 'paper', text: String(s[1]), showarrow: false, font: { size: 9, color: C.text3 } });
  });
  const txt = main.map(r => (isNum(r.inning) ? BP.inningLabel(r.inning, r.half, true) + ' · ' : '') + esc(r.desc || '') + '<br>' + esc(hn) + ' ' + BP.pct(r.p, 1));
  const traces = [
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.max(v, 0.5)), fill: 'tonexty', fillcolor: hexA(hc, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.min(v, 0.5)), fill: 'tonexty', fillcolor: hexA(ac, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y, name: R.length >= 2 ? 'Our model' : 'ESPN', line: { color: C.text, width: 2, shape: 'hv' }, text: txt, hovertemplate: '%{text}<extra></extra>' }
  ];
  if (R.length >= 2 && E.length >= 2) {
    traces.push({ type: 'scatter', mode: 'lines', x: E.map(r => r.i), y: E.map(r => r.p), name: 'ESPN', line: { color: C.espn, width: 1.4, dash: 'dot', shape: 'hv' },
      hovertemplate: 'ESPN ' + esc(hn) + ' %{y:.1%}<extra></extra>' });
  }
  const top = (o.top || []).filter(s => isNum(s.i)).slice(0, o.nTop || 5);
  if (top.length) {
    const at = i => { let best = null; main.forEach(r => { if (r.i <= i) best = r; }); return best ? best.p : null; };
    const pts = top.map((s, k) => ({ x: s.i, y: isNum(s.p) ? s.p : at(s.i), k: k + 1, s: s })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'markers+text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => String(p.k)), textposition: 'top center',
      textfont: { size: 10, color: C.text }, marker: { size: 11, color: pts.map(p => ((p.s.wpa || 0) > 0 ? hc : ac)), line: { width: 1.5, color: '#0d1117' } },
      hovertext: pts.map(p => 'Play ' + p.k + ': ' + esc(p.s.desc || '') + '<br>' + BP.signed((p.s.wpa || 0) * 100, 1) + ' pp for ' + esc(hn)), hoverinfo: 'text', showlegend: false });
  }
  if (isNum(o.market)) shapes.push({ type: 'line', x0: x[0] - 0.8, x1: x[0] + 0.8, y0: o.market, y1: o.market, line: { color: C.text, width: 3 } });
  BP.plot(el, traces, BP.layout({
    height: o.height || 320, shapes: shapes, annotations: ann,
    xaxis: { showgrid: false, fixedrange: true, zeroline: false, showticklabels: false, title: { text: 'Inning', font: { size: 10, color: C.text3 }, standoff: 4 } },
    yaxis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1], ticktext: [an + ' 100%', '75%', '50%', '75%', hn + ' 100%'], fixedrange: true, automargin: true },
    showlegend: R.length >= 2 && E.length >= 2, legend: { orientation: 'h', y: -0.12, x: 1, xanchor: 'right', font: { size: 10, color: C.text2 } },
    margin: { l: 70, r: 10, t: 20, b: 34 }
  }));
}

// ── percentile sliders (Savant style) ──────────────────────────────────────

function sliderRow(label, p, valueText, title) {
  const known = isNum(p);
  const x = known ? Math.max(0, Math.min(100, Number(p))) : 0;
  const col = BP.pctColor(p);
  return '<div class="ps-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
    '<span class="ps-label">' + label + '</span>' +
    '<span class="ps-track">' + (known
      ? '<span class="ps-fill" style="width:' + x + '%;background:' + col + '"></span><span class="ps-dot" style="left:' + x + '%;background:' + col + ';color:' + (BP.pctInk ? BP.pctInk(p) : '#fff') + '">' + Math.round(p) + '</span>'
      : '<span class="ps-none">below the sample floor</span>') +
    '<i class="ps-tick" style="left:10%"></i><i class="ps-tick mid" style="left:50%"></i><i class="ps-tick" style="left:90%"></i></span>' +
    '<span class="ps-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
}
function percentileSliders(metrics, vals, pcts, opts) {
  const o = opts || {};
  let list = (metrics || []).filter(m => m && m.key);
  if (o.keys) list = o.keys.map(k => list.find(m => m.key === k)).filter(Boolean);
  if (o.onlyKnown) list = list.filter(m => isNum((pcts || {})[m.key]));
  if (!list.length) return '<div class="muted">No percentiles yet.</div>';
  const row = m => sliderRow((o.glossary === false ? esc(m.label) : '<a class="gl-link" href="' + BP.glossHref(m.key) + '">' + esc(m.label) + '</a>') + (m.lower ? ' <span class="ps-lower" title="Lower is better: the percentile already accounts for it">↓</span>' : ''),
    (pcts || {})[m.key], BP.fmtVal((vals || {})[m.key], m.fmt), (m.desc || '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + m.stabilises_at : ''));
  let body;
  if (o.groups === false) body = '<div class="ps-group">' + list.map(row).join('') + '</div>';
  else {
    const groups = [];
    list.forEach(m => { const g = m.group || 'Other'; let x = groups.find(z => z.name === g); if (!x) { x = { name: g, items: [] }; groups.push(x); } x.items.push(m); });
    body = groups.map(g => '<div class="ps-group"><div class="ps-group-head">' + esc(g.name) + '</div>' + g.items.map(row).join('') + '</div>').join('');
  }
  return '<div class="ps-panel' + (o.columns === 1 ? ' one' : '') + '">' + body + '</div>' +
    '<div class="ps-legend"><span><i style="background:' + BP.pctColor(5) + '"></i>Poor</span><span><i style="background:' + BP.pctColor(50) + '"></i>Average</span><span><i style="background:' + BP.pctColor(95) + '"></i>Great</span>' +
    (o.note ? '<span class="ps-note">' + o.note + '</span>' : '') + '</div>';
}

// ── trends ─────────────────────────────────────────────────────────────────

function pitchTrend(el, data, opts) {
  const o = opts || {};
  const list = rows(data).filter(r => isNum(r.y) || isNum(r.velo) || isNum(r.value));
  if (!list.length) { empty(el, o.emptyText || 'No trend data.'); return; }
  const yOf = r => Number(isNum(r.y) ? r.y : isNum(r.velo) ? r.velo : r.value);
  const types = {};
  list.forEach(r => { const t = String(r.pitch_type || 'ALL').toUpperCase(); (types[t] = types[t] || []).push(r); });
  const traces = [];
  const shapes = [];
  const isDate = list.some(r => /^\d{4}-\d\d-\d\d/.test(String(r.x || r.date || '')));
  BP.PITCH_ORDER.concat(Object.keys(types)).filter((t, i, a) => types[t] && a.indexOf(t) === i).forEach(t => {
    const sub = types[t];
    const col = t === 'ALL' ? C.clay : BP.pitchColour(t);
    traces.push({ type: 'scatter', mode: o.mode || 'lines+markers', name: t === 'ALL' ? (o.name || 'All') : BP.pitchName(t), x: sub.map(r => r.x || r.date || r.game), y: sub.map(yOf),
      line: { color: col, width: 2 }, marker: { size: 5, color: col }, connectgaps: true,
      hovertemplate: esc(t === 'ALL' ? '' : BP.pitchName(t)) + ' %{x}: %{y:.1f}<extra></extra>' });
    const b = (o.baseline || {})[t];
    if (isNum(b)) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: b, y1: b, line: { color: hexA(col, 0.6), width: 1, dash: 'dash' } });
  });
  BP.plot(el, traces, BP.layout({
    height: o.height || 300, shapes: shapes,
    xaxis: { type: isDate ? 'date' : '-', title: o.xTitle || '' }, yaxis: { title: o.yTitle || 'mph', fixedrange: true },
    showlegend: traces.length > 1, legend: { orientation: 'h', y: -0.22, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 12, t: 10, b: 48 }
  }));
}

// ── linescore ──────────────────────────────────────────────────────────────

function linescore(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const ls = g.linescore || {};
  const inn = ls.innings || g.innings || [];
  const n = Math.max(9, inn.length);
  const tot = (side) => {
    const k = side === 'away' ? 0 : 1;
    const r = ls.r ? ls.r[k] : (side === 'away' ? g.as : g.hs);
    return [r, ls.h ? ls.h[k] : null, ls.e ? ls.e[k] : null];
  };
  const cell = (v, cls) => '<td class="' + (cls || '') + '">' + (v === null || v === undefined ? '' : (v === 'x' ? 'x' : esc(v))) + '</td>';
  const row = (tid, side) => {
    const k = side === 'away' ? 0 : 1;
    let h = '<tr><th class="ls-team">' + (o.link === false ? BP.teamBar(tid) + esc(BP.teamAbbr(tid)) : BP.teamLink(tid, { abbr: true })) + '</th>';
    for (let i = 0; i < n; i++) {
      const v = inn[i] ? inn[i][k] : null;
      const unplayed = !inn[i] || v === null || v === undefined;
      h += cell(unplayed ? (side === 'home' && i === inn.length - 1 && inn[i] && BP.isFinal(g) ? 'x' : '') : v, v > 0 ? 'ls-run' : '');
    }
    const t = tot(side);
    return h + cell(t[0], 'ls-r') + cell(t[1], 'ls-h') + cell(t[2], 'ls-e') + '</tr>';
  };
  let head = '<tr><th></th>';
  for (let i = 0; i < n; i++) head += '<th>' + (i + 1) + '</th>';
  head += '<th class="ls-r">R</th><th class="ls-h">H</th><th class="ls-e">E</th></tr>';
  return '<div class="table-wrap"><table class="linescore"><thead>' + head + '</thead><tbody>' + row(g.away, 'away') + row(g.home, 'home') + '</tbody></table></div>';
}
function pitchLegend(types) {
  return '<div class="pt-legend">' + (types || []).map(t => '<span><i style="background:' + BP.pitchColour(t) + '"></i>' + esc(BP.pitchName(t)) + '</span>').join('') + '</div>';
}

// ── postseason bracket ─────────────────────────────────────────────────────

const ROUNDS = ['WC', 'DS', 'LCS', 'WS'];
function seriesList(post) {
  const p = post || {};
  return (p.series || []).map(s => Object.assign({}, s, { rk: BP.roundKey(s.round), teams: (s.teams || []).map(String) }));
}
function seedMap(post) {
  const out = {};
  const p = post || {};
  if (p.seeds) ['AL', 'NL'].forEach(lg => (p.seeds[lg] || []).forEach((t, i) => { out[String(t)] = i + 1; }));
  if (p.teams) Object.keys(p.teams).forEach(t => { const x = p.teams[t]; if (x && isNum(x.seed) && !out[t]) out[t] = Number(x.seed); });
  (p.series || []).forEach(s => { if (Array.isArray(s.seeds)) (s.teams || []).forEach((t, i) => { if (isNum(s.seeds[i]) && !out[String(t)]) out[String(t)] = Number(s.seeds[i]); }); });
  return out;
}
function leagueOf(s, seeds, post) {
  if (s.league) return s.league;
  if (s.rk === 'WS') return 'WS';
  for (let i = 0; i < s.teams.length; i++) { const lg = BP.teamInfo(s.teams[i]).league; if (lg === 'AL' || lg === 'NL') return lg; }
  const p = post || {};
  if (p.seeds) for (let i = 0; i < s.teams.length; i++) { if ((p.seeds.AL || []).map(String).indexOf(s.teams[i]) >= 0) return 'AL'; if ((p.seeds.NL || []).map(String).indexOf(s.teams[i]) >= 0) return 'NL'; }
  return '';
}
function winnerOf(s) {
  if (!s || !s.wins || !isNum(s.best_of)) return null;
  const need = Math.floor(s.best_of / 2) + 1;
  if (s.wins[0] >= need) return s.teams[0];
  if (s.wins[1] >= need) return s.teams[1];
  return s.winner ? String(s.winner) : null;
}
/* The bracket as slots: {AL: {wc36, wc45, ds1, ds2, lcs}, NL: {...}, WS} each {teams:[a|null,b|null], series|null}. */
function bracketModel(post) {
  const list = seriesList(post);
  const seeds = seedMap(post);
  const bySeed = { AL: {}, NL: {} };
  Object.keys(seeds).forEach(t => { const lg = BP.teamInfo(t).league || ((post && post.seeds && (post.seeds.AL || []).map(String).indexOf(t) >= 0) ? 'AL' : 'NL'); if (bySeed[lg]) bySeed[lg][seeds[t]] = t; });
  const out = { AL: {}, NL: {}, WS: null, seeds: seeds };
  const has = (s, t) => t && s.teams.indexOf(String(t)) >= 0;
  ['AL', 'NL'].forEach(lg => {
    const S = bySeed[lg];
    const mine = list.filter(s => leagueOf(s, seeds, post) === lg);
    const find = (rk, t1, t2) => mine.find(s => s.rk === rk && ((t1 && has(s, t1)) || (t2 && has(s, t2)))) || null;
    const wcs = mine.filter(s => s.rk === 'WC');
    let wc36 = find('WC', S[3], S[6]), wc45 = find('WC', S[4], S[5]);
    if (!wc36 && !wc45 && wcs.length) { wc36 = wcs[0]; wc45 = wcs[1] || null; }
    else if (!wc36) wc36 = wcs.find(s => s !== wc45) || null;
    else if (!wc45) wc45 = wcs.find(s => s !== wc36) || null;
    const slot = (s, a, b) => ({ teams: s ? s.teams.slice() : [a || null, b || null], series: s });
    out[lg].wc36 = slot(wc36, S[3], S[6]);
    out[lg].wc45 = slot(wc45, S[4], S[5]);
    const w36 = winnerOf(wc36), w45 = winnerOf(wc45);
    const dss = mine.filter(s => s.rk === 'DS');
    let ds1 = find('DS', S[1], w45), ds2 = find('DS', S[2], w36);
    if (!ds1 && !ds2 && dss.length) { ds1 = dss[0]; ds2 = dss[1] || null; }
    else if (!ds1) ds1 = dss.find(s => s !== ds2) || null;
    else if (!ds2) ds2 = dss.find(s => s !== ds1) || null;
    out[lg].ds1 = slot(ds1, S[1], w45);
    out[lg].ds2 = slot(ds2, S[2], w36);
    const lcs = mine.find(s => s.rk === 'LCS') || null;
    out[lg].lcs = slot(lcs, winnerOf(ds1), winnerOf(ds2));
  });
  const ws = list.find(s => s.rk === 'WS') || null;
  out.WS = { teams: ws ? ws.teams.slice() : [winnerOf(out.AL.lcs.series), winnerOf(out.NL.lcs.series)], series: ws };
  return out;
}
function seriesBox(slot, title, o, seeds) {
  const s = slot.series;
  const L = o.level || 'mlb';
  const done = s && winnerOf(s);
  const live = s && !done && s.wins && (Number(s.wins[0]) + Number(s.wins[1])) > 0;
  const teamRow = (t, i) => {
    if (!t) return '<div class="bk-team tbd"><span class="bk-seed"></span><span class="bk-name">TBD</span><span class="bk-w"></span><span class="bk-p"></span></div>';
    const won = done && done === t, lost = done && done !== t;
    const p = s && s.p && isNum(s.p[i]) ? Number(s.p[i]) : null;
    const mk = s && s.market && isNum(s.market[i]) ? Number(s.market[i]) : null;
    return '<div class="bk-team' + (won ? ' won' : '') + (lost ? ' lost' : '') + '">' +
      '<span class="bk-seed">' + (seeds[t] || '') + '</span>' +
      '<span class="bk-name">' + BP.teamLink(t, { abbr: true, level: L }) + '<span class="bk-full">' + esc(BP.teamShort(t)) + '</span></span>' +
      '<span class="bk-w">' + (s && s.wins ? esc(s.wins[i]) : '') + '</span>' +
      '<span class="bk-p" title="' + (mk !== null ? 'Model ' + BP.pct(p, 1) + ' · market ' + BP.pct(mk, 1) : 'Model probability of winning the series') + '">' +
        (done ? '' : (p !== null ? BP.pct(p, 0) : '')) + (mk !== null && !done ? '<small>mkt ' + BP.pct(mk, 0) + '</small>' : '') + '</span></div>';
  };
  const games = s && s.games ? s.games : [];
  const last = games.length ? games[games.length - 1] : null;
  const lk = last ? '<a class="bk-link" href="' + BP.gameHref(last, L) + '" title="Latest game">' + (live ? '<span class="live-dot"></span>' : '↗') + '</a>' : '';
  return '<div class="bk-series' + (done ? ' done' : '') + (live ? ' live' : '') + '"' + (s && s.id ? ' data-sid="' + esc(s.id) + '"' : '') + '>' +
    '<div class="bk-head">' + esc(title) + (s && isNum(s.best_of) ? '<span>best of ' + s.best_of + '</span>' : '') + lk + '</div>' +
    teamRow(slot.teams[0], 0) + teamRow(slot.teams[1], 1) + '</div>';
}
function mlbBracket(el, post, opts) {
  const root = node(el);
  if (!root) return null;
  const o = opts || {};
  const m = bracketModel(post);
  const seeds = m.seeds;
  const anything = ['AL', 'NL'].some(lg => ['wc36', 'wc45', 'ds1', 'ds2', 'lcs'].some(k => m[lg][k].series || m[lg][k].teams.some(Boolean))) || m.WS.series;
  if (!anything) { root.innerHTML = '<div class="muted">The bracket is not set yet.</div>'; return null; }
  let roundSel = null;
  const col = (lg, keys, titles) => '<div class="bk-col">' + keys.map((k, i) => seriesBox(m[lg][k], titles[i], o, seeds)).join('') + '</div>';
  const draw = () => {
    const narrow = o.narrow !== undefined ? o.narrow : (root.clientWidth || 1000) < 900;
    if (!narrow) {
      root.innerHTML = '<div class="bk-wrap"><div class="bk-grid">' +
        '<div class="bk-round"><div class="bk-title">AL Wild Card</div>' + col('AL', ['wc45', 'wc36'], ['AL WC · 4 v 5', 'AL WC · 3 v 6']) + '</div>' +
        '<div class="bk-round"><div class="bk-title">AL Division</div>' + col('AL', ['ds1', 'ds2'], ['ALDS · 1 v 4/5', 'ALDS · 2 v 3/6']) + '</div>' +
        '<div class="bk-round"><div class="bk-title">ALCS</div>' + col('AL', ['lcs'], ['ALCS']) + '</div>' +
        '<div class="bk-round bk-ws"><div class="bk-title">World Series</div><div class="bk-col">' + seriesBox(m.WS, 'World Series', o, seeds) + '</div></div>' +
        '<div class="bk-round"><div class="bk-title">NLCS</div>' + col('NL', ['lcs'], ['NLCS']) + '</div>' +
        '<div class="bk-round"><div class="bk-title">NL Division</div>' + col('NL', ['ds1', 'ds2'], ['NLDS · 1 v 4/5', 'NLDS · 2 v 3/6']) + '</div>' +
        '<div class="bk-round"><div class="bk-title">NL Wild Card</div>' + col('NL', ['wc45', 'wc36'], ['NL WC · 4 v 5', 'NL WC · 3 v 6']) + '</div>' +
        '</div></div>';
    } else {
      if (roundSel === null) {
        roundSel = 'WC';
        ['WC', 'DS', 'LCS', 'WS'].forEach(rk => {
          const slots = rk === 'WS' ? [m.WS] : rk === 'LCS' ? [m.AL.lcs, m.NL.lcs] : rk === 'DS' ? [m.AL.ds1, m.AL.ds2, m.NL.ds1, m.NL.ds2] : [];
          if (slots.some(x => x.series && x.series.wins && Number(x.series.wins[0]) + Number(x.series.wins[1]) > 0)) roundSel = rk;
        });
      }
      const boxes = roundSel === 'WC' ? [['AL', 'wc45', 'AL WC · 4 v 5'], ['AL', 'wc36', 'AL WC · 3 v 6'], ['NL', 'wc45', 'NL WC · 4 v 5'], ['NL', 'wc36', 'NL WC · 3 v 6']]
        : roundSel === 'DS' ? [['AL', 'ds1', 'ALDS · 1 v 4/5'], ['AL', 'ds2', 'ALDS · 2 v 3/6'], ['NL', 'ds1', 'NLDS · 1 v 4/5'], ['NL', 'ds2', 'NLDS · 2 v 3/6']]
          : roundSel === 'LCS' ? [['AL', 'lcs', 'ALCS'], ['NL', 'lcs', 'NLCS']] : [];
      root.innerHTML = '<div class="toggle-row bk-rounds">' + BP.toggles(ROUNDS.map(r => ({ key: r, label: BP.roundLabel(r, true) })), roundSel, 'data-rd') + '</div>' +
        '<div class="bk-list">' + (roundSel === 'WS' ? seriesBox(m.WS, 'World Series', o, seeds) : boxes.map(b => seriesBox(m[b[0]][b[1]], b[2], o, seeds)).join('')) + '</div>';
      BP.wireToggles(root.querySelector('.bk-rounds'), 'data-rd', k => { roundSel = k; draw(); });
    }
    if (typeof o.onSeries === 'function') root.querySelectorAll('.bk-series[data-sid]').forEach(x => x.addEventListener('click', ev => {
      if (ev.target.closest('a')) return;
      const sid = x.getAttribute('data-sid');
      o.onSeries(seriesList(post).find(s => String(s.id) === sid) || null);
    }));
  };
  draw();
  let lastW = root.clientWidth;
  const onResize = () => { if (!root.isConnected) return; const w = root.clientWidth; if ((w < 900) !== (lastW < 900)) { roundSel = null; draw(); } lastW = w; };
  window.addEventListener('resize', onResize);
  BP.onLeave(() => window.removeEventListener('resize', onResize));
  return { model: m, redraw: draw };
}

// ── generic (as the Ace and Hardwood) ──────────────────────────────────────

function distBars(el, dist, opts) {
  const o = opts || {};
  let entries;
  if (Array.isArray(dist)) entries = dist.map((p, k) => [k, p]);
  else entries = Object.keys(dist || {}).map(k => [Number(k), dist[k]]);
  entries = entries.filter(e => isNum(e[0]) && isNum(e[1]) && e[1] > 0.0005).sort((a, b) => a[0] - b[0]);
  if (!entries.length) { empty(el, o.emptyText || 'No distribution.'); return; }
  const col = o.colour || C.clay;
  const shapes = [];
  if (isNum(o.line)) shapes.push({ type: 'line', x0: o.line, x1: o.line, yref: 'paper', y0: 0, y1: 1, line: { color: C.text2, width: 1.5, dash: 'dash' } });
  if (isNum(o.exp)) shapes.push({ type: 'line', x0: o.exp, x1: o.exp, yref: 'paper', y0: 0, y1: 1, line: { color: col, width: 1.5, dash: 'dot' } });
  const ks = entries.map(e => e[0]);
  BP.plot(el, [{ type: 'bar', x: ks, y: entries.map(e => e[1]),
    marker: { color: ks.map(k => (isNum(o.actual) && Number(k) === Number(o.actual) ? C.text : (o.split !== undefined ? (k > o.split ? col : hexA(C.blue, 0.8)) : hexA(col, 0.8)))) },
    hovertemplate: (o.signed ? '%{x:+d}' : '%{x}') + ' ' + esc(o.unit || 'runs') + ': %{y:.1%}<extra></extra>' }], BP.layout({
    height: o.height || 220, bargap: 0.12, shapes: shapes,
    xaxis: { title: o.xTitle || '', fixedrange: true, dtick: ks.length > 24 ? 4 : (ks.length > 12 ? 2 : 1), tickformat: o.signed ? '+d' : 'd' },
    yaxis: { tickformat: '.0%', fixedrange: true },
    margin: { l: 44, r: 10, t: 10, b: o.xTitle ? 42 : 28 }
  }));
}
function heatTable(spec) {
  const s = spec || {};
  const rws = s.rows || [];
  if (!rws.length) return '<div class="muted">No data.</div>';
  const nCols = Math.max.apply(null, rws.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(isNum(s.center) ? s.center : 0); continue; }
    const col = rws.map(r => (r.values || [])[i]).filter(isNum).sort((a, b) => a - b);
    centers.push(col.length ? col[Math.floor(col.length / 2)] : 0);
  }
  const vals = [];
  rws.forEach(r => (r.values || []).forEach((v, i) => { if (isNum(v)) vals.push(Math.abs(v - centers[i])); }));
  vals.sort((a, b) => a - b);
  const max = s.max || vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;
  const fmt = s.fmt || (v => BP.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? BP.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : BP.divColour(v - centers[i], max, s.invert));
  let h = '<div class="table-wrap heat-wrap"' + (s.maxWidth ? ' style="max-width:' + s.maxWidth + 'px"' : '') + '><table class="wc-table heat-table"><thead><tr><th class="heat-corner">' + esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th' + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rws.forEach(r => {
    h += '<tr><td class="heat-label">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, i) => {
      const t = r.titles && r.titles[i] ? ' title="' + esc(r.titles[i]) + '"' : '';
      h += isNum(v) ? '<td class="heat-cell" style="background:' + colour(v, i) + '"' + t + '>' + fmt(v, i) + '</td>' : '<td class="heat-cell heat-empty"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}
function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => isNum(i.p) && (i.p > 0 || isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const rev = list.slice().reverse();
  const max = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  const traces = [{
    type: 'bar', orientation: 'h', y: rev.map(i => i.label), x: rev.map(i => i.p), name: o.modelName || 'Model',
    text: rev.map(i => BP.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.clay) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => isNum(i.market))) {
    const mk = rev.filter(i => isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: mk.map(i => i.label), x: mk.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  BP.plot(el, traces, BP.layout({
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
    const col = s.colour || BP.PALETTE[i % BP.PALETTE.length];
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
      hovertemplate: s.hover || (esc(s.name) + ' · %{y}<extra></extra>')
    });
  });
  BP.plot(el, traces, BP.layout(Object.assign({
    height: o.height || 380, showlegend: o.legend !== false,
    legend: { orientation: 'h', y: -0.2, font: { size: 10, color: C.text2 } },
    xaxis: Object.assign({ title: o.xTitle || '' }, o.xaxis || {}), yaxis: Object.assign({ title: o.yTitle || '' }, o.yaxis || {}),
    margin: { l: 55, r: 20, t: 20, b: 55 }
  }, o.layout || {})));
}
function radar(el, series, opts) {
  const o = opts || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(isNum));
  if (!list.length || !labels.length) { empty(el, o.emptyText || 'Not enough data for a radar.'); return; }
  const traces = list.map((s, i) => {
    const col = s.colour || BP.PALETTE[i % BP.PALETTE.length];
    const r = s.values.map(v => (isNum(v) ? v : 0));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself',
      fillcolor: hexA(col, 0.18), line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + esc(s.name || '') + '</extra>' };
  });
  BP.plot(el, traces, BP.layout({
    height: o.height || 360,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [0, 100], tickvals: [25, 50, 75, 100], gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 10, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 50, t: 30, b: 30 }
  }));
}

BP.charts = Object.assign(BP.charts || {}, {
  rows: rows, strikeZone: strikeZone, zoneShapes: zoneShapes, pitchHover: pitchHover, sprayChart: sprayChart, sprayXY: sprayXY, wallPoints: wallPoints,
  movementPlot: movementPlot, zoneHeatmap: zoneHeatmap, wpChart: wpChart, wpRows: wpRows,
  percentileSliders: percentileSliders, sliderRow: sliderRow, pitchTrend: pitchTrend, velocityTrend: pitchTrend,
  linescore: linescore, pitchLegend: pitchLegend, mlbBracket: mlbBracket, bracketModel: bracketModel, winnerOf: winnerOf, seriesList: seriesList, seedMap: seedMap,
  distBars: distBars, gamesDist: distBars, heatTable: heatTable, probBars: probBars, lines: lines, radar: radar, hexA: hexA, median: median, mean: mean
});
})(window.BP);
