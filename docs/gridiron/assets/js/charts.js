/* The Quant Gridiron — shared chart helpers (GI.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line when its data is
 * missing. Column-oriented payloads ({cols|fields|columns, rows}) are normalised with GI.charts.rows(x).
 * Field coordinates: `yl100` is the yards to the opponent's goal line (nflverse); the charts draw the
 * field from the offence's own goal line (0) to the opponent's (100), so x = 100 - yl100.
 *
 *   rows(x)                            [{...}] from an array of objects or {cols|fields|columns, rows}
 *   driveRows(x)                       normalised drives [{n, team, qtr, clock, start, end, result, plays, yards, epa, time, desc}]
 *                                      from objects with start_yl100|start|yl100_start, end_yl100|end, result, plays, yards, epa,
 *                                      top|time|duration, start_clock|clock (or column-oriented)
 *   driveChart(el, drives, opts)       the drive chart: a field 0-100 (own goal line to the opponent's) with each drive a bar from
 *                                      where it started to where it ended, coloured by result (GI.driveResult), first drive at the
 *                                      top; opts {home, away, height, onDrive(n)}
 *   wpRows(x)                          [{i, qtr, clock, p, desc}] from objects {i|idx|play, qtr, clock, p|p_home|wp_home|wp, desc}
 *                                      or arrays [i, qtr, clock, p, desc] / [i, p, desc]
 *   wpChart(el, ours, opts)            home win probability by play, ours against ESPN's; opts {espn (same shape), fourth:
 *                                      [{i, grade, wp_lost, choice, rec, desc}] markers coloured by decision grade, scoring:
 *                                      [{i, team, desc, kind}] scoring plays, top: [{i, wpa, desc}] numbered, home, away,
 *                                      height, market (pre-game market p_home, a tick at the start)}
 *   fieldHeatmap(el, data, opts)       values by field position: data {x: [own-yard bin centres 0-100], y: [row labels],
 *                                      v: [[row][bin]], n?} or a flat array (one row of equal bins); opts {fmt, scale 'div'|'seq',
 *                                      center, zmin, zmax, invert, title, label, height, yl100: true (x given as yl100)}
 *   passGrid(el, grid, opts)           depth x location: grid {depths: [labels, nearest the line first], locs: ['Left','Middle',
 *                                      'Right'], v: [[per depth][per loc]], n?} or rows [{depth, loc, value|v, n}]; opts {fmt,
 *                                      center, scale, invert, title, label, height}
 *   percentileSliders(metrics, vals, pcts, opts)  HTML: Savant-style sliders (blue low, red high) grouped by METRIC.group;
 *                                      opts {groups: false, note, keys: [subset], onlyKnown, glossary: false, columns: 1}
 *   sliderRow(label, p, valueText, title)        one slider row (HTML)
 *   linescore(g, opts)                 HTML linescore by quarter: g {home, away, hs, as, quarters|linescore: [[away, home], ...]
 *                                      (OT periods after the 4th) or {home: [...], away: [...]}}; opts {link}
 *   distBars(el, dist, opts)           bars of {k: p}; opts {actual, exp, line, xTitle, colour, height, unit, signed, split}
 *   heatTable(spec)                    HTML: {cols, rows:[{label(html), values, titles}], fmt, scale:'div'|'seq', max, invert, corner, center}
 *   probBars(el, items, opts)          items [{label, p, colour, market}] horizontal bars, market as a tick
 *   lines(el, series, opts)            series [{name, x, y, colour, dash, width, err, band:[lo,hi], mode, shape, hover}]
 *   radar(el, series, opts)            series [{name, values:[0-100], colour}]; opts {labels, height}
 *   fieldShapes(opts)                  Plotly shapes for a field 0-100 (end zones, yard lines)
 *   hexA(hex, a)                       rgba string
 */
(function (GI) {
'use strict';

const C = GI.C;
const esc = GI.esc;
const isNum = GI.isNum;

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }
function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(139,148,158,' + a + ')';
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
function first(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }
const DIV_SCALE = [[0, '#2c64c8'], [0.25, '#7a9fd9'], [0.5, '#9a9a9a'], [0.75, '#e08a7a'], [1, '#d62828']];
const SEQ_SCALE = [[0, 'rgba(200,131,74,0.06)'], [0.5, 'rgba(200,131,74,0.5)'], [1, '#e8a46c']];
const FIELD_TICKS = { vals: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100], text: ['G', '10', '20', '30', '40', '50', '40', '30', '20', '10', 'G'] };

// ── field ──────────────────────────────────────────────────────────────────

/* Shapes for a field drawn 0-100 on x (own goal line to the opponent's), across the whole y range. */
function fieldShapes(opts) {
  const o = opts || {};
  const sh = [];
  const turf = o.turf === false ? null : 'rgba(58,154,95,0.07)';
  if (turf) sh.push({ type: 'rect', x0: 0, x1: 100, yref: 'paper', y0: 0, y1: 1, fillcolor: turf, line: { width: 0 }, layer: 'below' });
  sh.push({ type: 'rect', x0: -10, x1: 0, yref: 'paper', y0: 0, y1: 1, fillcolor: o.homeZone || 'rgba(88,166,255,0.10)', line: { width: 0 }, layer: 'below' });
  sh.push({ type: 'rect', x0: 100, x1: 110, yref: 'paper', y0: 0, y1: 1, fillcolor: o.awayZone || 'rgba(200,131,74,0.13)', line: { width: 0 }, layer: 'below' });
  for (let x = 0; x <= 100; x += 10) {
    sh.push({ type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, layer: 'below',
      line: { color: x === 50 ? 'rgba(230,237,243,0.35)' : (x === 0 || x === 100 ? 'rgba(230,237,243,0.4)' : 'rgba(230,237,243,0.10)'), width: x === 0 || x === 100 || x === 50 ? 1.4 : 1 } });
  }
  if (o.redZone) sh.push({ type: 'rect', x0: 80, x1: 100, yref: 'paper', y0: 0, y1: 1, fillcolor: 'rgba(248,81,73,0.05)', line: { width: 0 }, layer: 'below' });
  return sh;
}

// ── drives ─────────────────────────────────────────────────────────────────

function driveRows(x) {
  return rows(x).map((d, k) => {
    const s = first(d, ['start_yl100', 'yl100_start', 'start', 'start_yardline_100', 'drive_start_yl100']);
    let e = first(d, ['end_yl100', 'yl100_end', 'end', 'end_yardline_100', 'drive_end_yl100']);
    const yards = first(d, ['yards', 'yds', 'net_yards']);
    if (!isNum(e) && isNum(s) && isNum(yards)) e = Number(s) - Number(yards);
    const res = String(first(d, ['result', 'drive_result', 'end_result']) || '').toLowerCase();
    if (/^touchdown$|^td$/.test(res)) e = 0;     // a scoring drive ends in the end zone (payloads give the last play's start)
    return {
      n: isNum(d.n) ? Number(d.n) : (isNum(d.drive) ? Number(d.drive) : k + 1),
      team: first(d, ['team', 'posteam', 'offense']), qtr: first(d, ['qtr', 'quarter', 'start_qtr']),
      clock: first(d, ['start_clock', 'clock', 'start_time']), start: isNum(s) ? Number(s) : null, end: isNum(e) ? Number(e) : null,
      result: first(d, ['result', 'drive_result', 'end_result']) || '', plays: first(d, ['plays', 'n_plays', 'play_count']),
      yards: isNum(yards) ? Number(yards) : (isNum(s) && isNum(e) ? Number(s) - Number(e) : null),
      epa: first(d, ['epa', 'total_epa']), time: first(d, ['time', 'top', 'duration', 'time_of_possession']),
      points: first(d, ['points', 'pts']), desc: first(d, ['desc', 'summary']) || '', first_play: first(d, ['first_play', 'play_start', 'i0'])
    };
  }).filter(d => isNum(d.start));
}
function driveChart(el, drives, opts) {
  const o = opts || {};
  const D = driveRows(drives);
  if (!D.length) { empty(el, o.emptyText || 'No drives yet.'); return; }
  const n = D.length;
  const label = d => d.n + ' · ' + GI.teamAbbr(d.team);
  const cats = D.map(label);
  const byRes = {};
  D.forEach(d => {
    const r = GI.driveResult(d.result);
    (byRes[r.label] = byRes[r.label] || { colour: r.colour, items: [] }).items.push(d);
  });
  const hover = d => {
    const r = GI.driveResult(d.result);
    const opp = o.home && o.away ? (String(d.team) === String(o.home) ? o.away : o.home) : null;
    return '<b>' + esc(GI.teamName(d.team)) + '</b> · ' + esc(GI.clockText(d.qtr, d.clock)) +
      '<br>Start ' + esc(GI.fieldPos(d.start, d.team, opp)) + ' → ' + esc(isNum(d.end) ? GI.fieldPos(Math.max(0, Math.min(100, d.end)), d.team, opp) : '—') +
      '<br>' + esc(r.label) + (isNum(d.plays) ? ' · ' + d.plays + ' plays' : '') + (isNum(d.yards) ? ', ' + Math.round(d.yards) + ' yds' : '') +
      (d.time ? ' · ' + esc(GI.fmtClock(d.time)) : '') + (isNum(d.epa) ? '<br>EPA ' + GI.signed(d.epa, 2) : '') + (d.desc ? '<br>' + esc(d.desc) : '');
  };
  const traces = [];
  Object.keys(byRes).forEach(k => {
    const g = byRes[k];
    const x0 = g.items.map(d => 100 - d.start), x1 = g.items.map(d => 100 - (isNum(d.end) ? Math.max(-2, Math.min(102, d.end)) : d.start));
    traces.push({
      type: 'bar', orientation: 'h', name: k, y: g.items.map(label), base: x0.map((v, i) => Math.min(v, x1[i])),
      x: x0.map((v, i) => Math.max(0.8, Math.abs(x1[i] - v))), marker: { color: hexA(g.colour, 0.85), line: { color: g.colour, width: 1 } },
      hovertext: g.items.map(hover), hoverinfo: 'text', width: 0.62
    });
  });
  // the offence's colour at the start of each bar, and a cap at the end showing the direction
  traces.push({ type: 'scatter', mode: 'markers', y: cats, x: D.map(d => 100 - d.start), showlegend: false, hoverinfo: 'skip',
    marker: { symbol: 'line-ns', size: 14, line: { width: 3, color: D.map(d => GI.teamColour(d.team)) } } });
  traces.push({ type: 'scatter', mode: 'markers', y: cats, x: D.map(d => -6), showlegend: false, hoverinfo: 'skip',
    marker: { symbol: 'square', size: 9, color: D.map(d => GI.teamColour(d.team)) } });
  const shapes = fieldShapes({});
  // quarter separators
  let prevQ = null;
  D.forEach((d, i) => {
    if (isNum(d.qtr) && prevQ !== null && Number(d.qtr) !== prevQ && i > 0) {
      shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: n - i - 0.5, y1: n - i - 0.5, line: { color: 'rgba(230,237,243,0.18)', width: 1, dash: 'dot' } });
    }
    if (isNum(d.qtr)) prevQ = Number(d.qtr);
  });
  const ann = [];
  prevQ = null;
  D.forEach((d, i) => { if (isNum(d.qtr) && Number(d.qtr) !== prevQ) { ann.push({ x: 108, y: cats[i], text: GI.qtrLabel(d.qtr), showarrow: false, font: { size: 9, color: C.text3 }, xanchor: 'right' }); prevQ = Number(d.qtr); } });
  GI.plot(el, traces, GI.layout({
    height: o.height || Math.max(240, n * 21 + 80), barmode: 'overlay', shapes: shapes, annotations: ann,
    xaxis: { range: [-10, 110], tickvals: FIELD_TICKS.vals, ticktext: FIELD_TICKS.text, showgrid: false, zeroline: false, fixedrange: true, side: 'top' },
    yaxis: { type: 'category', categoryorder: 'array', categoryarray: cats.slice().reverse(), autorange: true, fixedrange: true, showgrid: false, tickfont: { size: 9 }, automargin: true },
    showlegend: true, legend: { orientation: 'h', y: -0.02, yanchor: 'top', x: 0, font: { size: 10, color: C.text2 } },
    margin: { l: 58, r: 8, t: 26, b: 30 }
  }));
  const nd = node(el);
  if (nd && typeof o.onDrive === 'function' && nd.on) nd.on('plotly_click', ev => { const pt = ev && ev.points && ev.points[0]; if (pt) o.onDrive(parseInt(String(pt.y), 10)); });
}

// ── win probability ────────────────────────────────────────────────────────

function wpRows(x) {
  const list = Array.isArray(x) ? x : rows(x);
  return list.map((r, k) => {
    if (Array.isArray(r)) {
      if (r.length >= 4) return { i: Number(r[0]), qtr: r[1], clock: r[2], p: Number(r[3]), desc: r[4] || '' };
      return { i: Number(r[0]), p: Number(r[1]), desc: r[2] || '' };
    }
    if (r && typeof r === 'object') {
      const p = first(r, ['p_home', 'wp_home', 'p', 'wp', 'wp_home_ours']);
      return { i: isNum(r.i) ? Number(r.i) : (isNum(r.idx) ? Number(r.idx) : (isNum(r.play) ? Number(r.play) : k)), qtr: r.qtr, clock: r.clock, p: Number(p), desc: r.desc || r.label || '' };
    }
    return null;
  }).filter(r => r && isNum(r.i) && isNum(r.p));
}
function wpChart(el, ours, opts) {
  const o = opts || {};
  const R = wpRows(ours);
  const E = wpRows(o.espn);
  if (R.length < 2 && E.length < 2) { empty(el, o.emptyText || 'No win-probability path for this game yet.'); return; }
  const main = R.length >= 2 ? R : E;
  const hc = o.home ? GI.teamColour(o.home) : C.home, ac = o.away ? GI.teamColour(o.away) : C.away;
  const hn = o.home ? GI.teamAbbr(o.home) : 'Home', an = o.away ? GI.teamAbbr(o.away) : 'Away';
  const x = main.map(r => r.i), y = main.map(r => r.p);
  const shapes = [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: '#30363d', width: 1 } }];
  const ann = [];
  // quarter separators, labelled
  let prevQ = null;
  const starts = [];
  main.forEach((r, k) => {
    if (isNum(r.qtr) && Number(r.qtr) !== prevQ) { starts.push([k ? (main[k - 1].i + r.i) / 2 : r.i, Number(r.qtr)]); prevQ = Number(r.qtr); }
  });
  starts.forEach((s, k) => {
    if (k) shapes.push({ type: 'line', x0: s[0], x1: s[0], yref: 'paper', y0: 0, y1: 1, line: { color: '#2b323b', width: 1, dash: 'dot' }, layer: 'below' });
    const end = k + 1 < starts.length ? starts[k + 1][0] : x[x.length - 1];
    ann.push({ x: (s[0] + end) / 2, y: 1.06, yref: 'paper', text: GI.qtrLabel(s[1]), showarrow: false, font: { size: 9, color: C.text3 } });
  });
  const txt = main.map(r => (isNum(r.qtr) ? esc(GI.clockText(r.qtr, r.clock)) + ' · ' : '') + esc(String(r.desc || '').slice(0, 120)) + '<br>' + esc(hn) + ' ' + GI.pct(r.p, 1));
  const traces = [
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.max(v, 0.5)), fill: 'tonexty', fillcolor: hexA(hc, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: x.map(() => 0.5), line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y.map(v => Math.min(v, 0.5)), fill: 'tonexty', fillcolor: hexA(ac, 0.22), line: { width: 0, shape: 'hv' }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', x: x, y: y, name: R.length >= 2 ? (o.mainName || 'Our model') : 'ESPN', line: { color: C.text, width: 2, shape: 'hv' }, text: txt, hovertemplate: '%{text}<extra></extra>' }
  ];
  if (R.length >= 2 && E.length >= 2) {
    traces.push({ type: 'scatter', mode: 'lines', x: E.map(r => r.i), y: E.map(r => r.p), name: 'ESPN', line: { color: C.espn, width: 1.4, dash: 'dot', shape: 'hv' },
      hovertemplate: 'ESPN ' + esc(hn) + ' %{y:.1%}<extra></extra>' });
  }
  const at = i => { let best = null; main.forEach(r => { if (r.i <= i) best = r; }); return best ? best.p : null; };
  // scoring plays
  const sc = (o.scoring || []).filter(s => isNum(s.i));
  if (sc.length) {
    const pts = sc.map(s => ({ x: s.i, y: isNum(s.p) ? s.p : at(s.i), s: s })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'markers', name: 'Score', x: pts.map(p => p.x), y: pts.map(p => p.y), showlegend: false,
      marker: { symbol: 'circle', size: 7, color: pts.map(p => GI.teamColour(p.s.team)), line: { width: 1, color: '#0d1117' } },
      hovertext: pts.map(p => esc(GI.teamAbbr(p.s.team)) + ' ' + esc(p.s.kind || 'score') + (p.s.desc ? '<br>' + esc(String(p.s.desc).slice(0, 120)) : '')), hoverinfo: 'text' });
  }
  // fourth downs, coloured by decision grade
  const fd = (o.fourth || []).filter(s => isNum(s.i));
  if (fd.length) {
    const pts = fd.map(s => ({ x: s.i, y: isNum(s.p) ? s.p : at(s.i), s: s, g: GI.gradeOf(s.grade, s.wp_lost) })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'markers', name: '4th down', x: pts.map(p => p.x), y: pts.map(p => p.y), showlegend: false,
      marker: { symbol: 'diamond', size: 11, color: pts.map(p => p.g.colour), line: { width: 1.5, color: '#0d1117' } },
      hovertext: pts.map(p => '<b>4th down</b> · ' + esc(GI.teamAbbr(p.s.team || '')) + ' ' + esc(GI.choiceLabel(p.s.choice)) +
        (p.s.rec ? ' (model: ' + esc(GI.choiceLabel(p.s.rec)) + ')' : '') + '<br>' + esc(p.g.label) +
        (isNum(p.s.wp_lost) ? ' · WP lost ' + GI.num(Math.abs(p.s.wp_lost) * 100, 1) + ' pp' : '') + (p.s.desc ? '<br>' + esc(String(p.s.desc).slice(0, 120)) : '')),
      hoverinfo: 'text' });
  }
  const top = (o.top || []).filter(s => isNum(s.i)).slice(0, o.nTop || 5);
  if (top.length) {
    const pts = top.map((s, k) => ({ x: s.i, y: isNum(s.p) ? s.p : at(s.i), k: k + 1, s: s })).filter(p => p.y !== null);
    traces.push({ type: 'scatter', mode: 'text', x: pts.map(p => p.x), y: pts.map(p => p.y), text: pts.map(p => String(p.k)), textposition: 'top center',
      textfont: { size: 10, color: C.text }, hovertext: pts.map(p => 'Key play ' + p.k + ': ' + esc(String(p.s.desc || '').slice(0, 120)) + '<br>' + GI.signed((p.s.wpa || 0) * 100, 1) + ' pp for ' + esc(hn)),
      hoverinfo: 'text', showlegend: false });
  }
  if (isNum(o.market)) shapes.push({ type: 'line', x0: x[0] - 0.8, x1: x[0] + 0.8, y0: o.market, y1: o.market, line: { color: C.text, width: 3 } });
  GI.plot(el, traces, GI.layout({
    height: o.height || 320, shapes: shapes, annotations: ann,
    xaxis: { showgrid: false, fixedrange: true, zeroline: false, showticklabels: false, range: [x[0] - 1, x[x.length - 1] + 1] },
    yaxis: { range: [0, 1], tickvals: [0, 0.25, 0.5, 0.75, 1], ticktext: [an + ' 100%', '75%', '50%', '75%', hn + ' 100%'], fixedrange: true, automargin: true },
    showlegend: R.length >= 2 && E.length >= 2, legend: { orientation: 'h', y: -0.06, x: 1, xanchor: 'right', font: { size: 10, color: C.text2 } },
    margin: { l: 70, r: 10, t: 22, b: 24 }
  }));
}

// ── field-position heatmap ─────────────────────────────────────────────────

function fieldHeatmap(el, data, opts) {
  const o = opts || {};
  let d = data;
  if (Array.isArray(d) && d.length && !Array.isArray(d[0])) d = { v: [d] };
  else if (Array.isArray(d)) d = { v: d };
  d = d || {};
  let v = d.v || d.values || d.z;
  if (!Array.isArray(v) || !v.length) { empty(el, o.emptyText || 'No field-position data.'); return; }
  if (!Array.isArray(v[0])) v = [v];
  const nb = v[0].length;
  let xs = d.x || d.bins || Array.from({ length: nb }, (_, i) => (100 * (i + 0.5)) / nb);
  if (o.yl100 || d.yl100) xs = xs.map(b => 100 - Number(b));
  const ys = d.y || d.rows || (v.length === 1 ? [o.rowLabel || ''] : v.map((_, i) => String(i + 1)));
  const flat = [];
  v.forEach(r => (r || []).forEach(x => { if (isNum(x)) flat.push(Number(x)); }));
  if (!flat.length) { empty(el, o.emptyText || 'No field-position data.'); return; }
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
  const fmt = o.fmt ? (x => GI.fmtVal(x, o.fmt)) : (x => GI.num(x, 2));
  const text = v.map((r, i) => (r || []).map((x, j) => (isNum(x) ? fmt(x) + (d.n && d.n[i] && isNum(d.n[i][j]) ? '<br>n ' + d.n[i][j] : '') : '')));
  const width = xs.length > 1 ? Math.abs(xs[1] - xs[0]) : 10;
  GI.plot(el, [{ type: 'heatmap', x: xs, y: ys, z: v, zmin: zmin, zmax: zmax, colorscale: scale, text: text, hoverinfo: 'text', xgap: 2, ygap: 2, opacity: 0.9,
    texttemplate: o.labels === false || xs.length > 12 ? undefined : '%{text}', textfont: { size: 9, color: '#0d1117' },
    colorbar: { thickness: 8, len: 0.9, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0, title: { text: o.label || '', font: { size: 9, color: C.text2 } } } }], GI.layout({
    height: o.height || Math.max(150, 60 + ys.length * 34), shapes: fieldShapes({ turf: false }),
    xaxis: { range: [Math.min(-10, xs[0] - width / 2), Math.max(110, xs[xs.length - 1] + width / 2)], tickvals: FIELD_TICKS.vals, ticktext: FIELD_TICKS.text, showgrid: false, zeroline: false, fixedrange: true,
      title: { text: o.xTitle || 'Own goal line → opponent goal line', font: { size: 10, color: C.text3 } } },
    yaxis: { type: 'category', showgrid: false, zeroline: false, fixedrange: true, automargin: true, autorange: 'reversed' },
    margin: { l: 10, r: 10, t: o.title ? 24 : 8, b: 40 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined
  }));
}

// ── pass depth x location grid ─────────────────────────────────────────────

const DEPTHS = ['Behind LOS', '0–9', '10–19', '20+'];
const LOCS = ['Left', 'Middle', 'Right'];
function gridOf(grid) {
  const g = grid || {};
  if (Array.isArray(g.v || g.values)) return { depths: g.depths || g.y || DEPTHS, locs: g.locs || g.x || LOCS, v: g.v || g.values, n: g.n || null };
  const list = rows(g.rows || g);
  if (!list.length) return null;
  const depths = [], locs = [];
  list.forEach(r => { const dp = String(first(r, ['depth', 'air_depth', 'd'])); const lc = String(first(r, ['loc', 'location', 'pass_location', 'l'])); if (depths.indexOf(dp) < 0) depths.push(dp); if (locs.indexOf(lc) < 0) locs.push(lc); });
  const order = (arr, ref) => arr.sort((a, b) => { const ia = ref.findIndex(r => r.toLowerCase() === a.toLowerCase()), ib = ref.findIndex(r => r.toLowerCase() === b.toLowerCase()); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
  order(locs, LOCS);
  const v = depths.map(() => locs.map(() => null)), n = depths.map(() => locs.map(() => null));
  list.forEach(r => {
    const i = depths.indexOf(String(first(r, ['depth', 'air_depth', 'd']))), j = locs.indexOf(String(first(r, ['loc', 'location', 'pass_location', 'l'])));
    if (i >= 0 && j >= 0) { v[i][j] = first(r, ['value', 'v', 'epa', 'epa_per_play']); n[i][j] = first(r, ['n', 'att', 'targets']); }
  });
  return { depths: depths, locs: locs.map(l => GI.titleCase(l)), v: v, n: n };
}
function passGrid(el, grid, opts) {
  const o = opts || {};
  const g = gridOf(grid);
  if (!g || !g.v.length) { empty(el, o.emptyText || 'No passing grid yet.'); return; }
  const flat = [];
  g.v.forEach(r => (r || []).forEach(x => { if (isNum(x)) flat.push(Number(x)); }));
  if (!flat.length) { empty(el, o.emptyText || 'No passing grid yet.'); return; }
  const seq = o.scale === 'seq';
  let zmin = o.zmin, zmax = o.zmax;
  if (!isNum(zmin) || !isNum(zmax)) {
    if (seq) { zmin = Math.min.apply(null, flat); zmax = Math.max.apply(null, flat); }
    else { const c = isNum(o.center) ? Number(o.center) : 0; const dev = Math.max.apply(null, flat.map(x => Math.abs(x - c))) || 1; zmin = c - dev; zmax = c + dev; }
  }
  const scale = seq ? SEQ_SCALE : (o.invert ? DIV_SCALE.map((s, i) => [s[0], DIV_SCALE[DIV_SCALE.length - 1 - i][1]]) : DIV_SCALE);
  const fmt = o.fmt ? (x => GI.fmtVal(x, o.fmt)) : (x => GI.signed(x, 2));
  const text = g.v.map((r, i) => (r || []).map((x, j) => (isNum(x) ? fmt(x) + (g.n && g.n[i] && isNum(g.n[i][j]) ? '<br><span style="font-size:9px">n ' + g.n[i][j] + '</span>' : '') : '·')));
  GI.plot(el, [{ type: 'heatmap', x: g.locs, y: g.depths, z: g.v, zmin: zmin, zmax: zmax, colorscale: scale, text: text, texttemplate: '%{text}',
    textfont: { size: 12, color: '#0d1117' }, hoverinfo: 'text', xgap: 3, ygap: 3, showscale: o.showscale === true,
    colorbar: { thickness: 8, len: 0.8, tickfont: { size: 9, color: C.text2 }, outlinewidth: 0 } }], GI.layout({
    height: o.height || 300,
    shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 0.5, y1: 0.5, line: { color: C.lace, width: 2, dash: 'dot' } }],
    xaxis: { type: 'category', side: 'bottom', showgrid: false, zeroline: false, fixedrange: true },
    yaxis: { type: 'category', showgrid: false, zeroline: false, fixedrange: true, automargin: true, title: { text: o.yTitle || 'Air yards', font: { size: 10, color: C.text3 } } },
    margin: { l: 70, r: 10, t: o.title ? 26 : 8, b: 30 },
    title: o.title ? { text: o.title, font: { size: 12, color: C.text2 }, x: 0.02 } : undefined
  }));
}

// ── percentile sliders (Savant style) ──────────────────────────────────────

function sliderRow(label, p, valueText, title) {
  const known = isNum(p);
  const x = known ? Math.max(0, Math.min(100, Number(p))) : 0;
  const col = GI.pctColor(p);
  return '<div class="ps-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
    '<span class="ps-label">' + label + '</span>' +
    '<span class="ps-track">' + (known
      ? '<span class="ps-fill" style="width:' + x + '%;background:' + col + '"></span><span class="ps-dot" style="left:' + x + '%;background:' + col + '">' + Math.round(p) + '</span>'
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
  const row = m => sliderRow((o.glossary === false ? esc(m.label) : '<a class="gl-link" href="' + GI.glossHref(m.key) + '">' + esc(m.label) + '</a>') + (m.lower ? ' <span class="ps-lower" title="Lower is better: the percentile already accounts for it">↓</span>' : ''),
    (pcts || {})[m.key], GI.fmtVal((vals || {})[m.key], m.fmt), (m.desc || '') + (isNum(m.stabilises_at) ? ' · stabilises at about ' + m.stabilises_at : ''));
  let body;
  if (o.groups === false) body = '<div class="ps-group">' + list.map(row).join('') + '</div>';
  else {
    const groups = [];
    list.forEach(m => { const g = m.group || 'Other'; let x = groups.find(z => z.name === g); if (!x) { x = { name: g, items: [] }; groups.push(x); } x.items.push(m); });
    body = groups.map(g => '<div class="ps-group"><div class="ps-group-head">' + esc(g.name) + '</div>' + g.items.map(row).join('') + '</div>').join('');
  }
  return '<div class="ps-panel' + (o.columns === 1 ? ' one' : '') + '">' + body + '</div>' +
    '<div class="ps-legend"><span><i style="background:' + GI.pctColor(5) + '"></i>Poor</span><span><i style="background:' + GI.pctColor(50) + '"></i>Average</span><span><i style="background:' + GI.pctColor(95) + '"></i>Great</span>' +
    (o.note ? '<span class="ps-note">' + o.note + '</span>' : '') + '</div>';
}

// ── linescore ──────────────────────────────────────────────────────────────

/* Quarter scores as [[away, home], ...] from g.quarters | g.linescore | g.score_by_quarter, as pairs or {home:[], away:[]}. */
function quartersOf(g) {
  const q = g.quarters || g.linescore || g.score_by_quarter || g.by_quarter || (g.score && Array.isArray(g.score.home) ? g.score : null);
  if (!q) return [];
  if (Array.isArray(q)) return q.map(r => (Array.isArray(r) ? r : [r.away, r.home]));
  if (Array.isArray(q.home) && Array.isArray(q.away)) return q.home.map((h, i) => [q.away[i], h]);
  return [];
}
function linescore(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const qs = quartersOf(g);
  const n = Math.max(4, qs.length);
  const cell = (v, cls) => '<td class="' + (cls || '') + '">' + (v === null || v === undefined ? '' : esc(v)) + '</td>';
  const row = (t, side) => {
    const k = side === 'away' ? 0 : 1;
    let h = '<tr><th class="ls-team">' + (o.link === false ? GI.teamBar(t) + esc(GI.teamAbbr(t)) : GI.teamLink(t, { abbr: true })) + '</th>';
    for (let i = 0; i < n; i++) { const v = qs[i] ? qs[i][k] : null; h += cell(v, v > 0 ? 'ls-run' : ''); }
    const tot = side === 'away' ? g.as : g.hs;
    return h + cell(isNum(tot) ? tot : (qs.length ? qs.reduce((s, r) => s + (Number(r[k]) || 0), 0) : ''), 'ls-r') + '</tr>';
  };
  let head = '<tr><th></th>';
  for (let i = 0; i < n; i++) head += '<th>' + (i < 4 ? i + 1 : (i === 4 ? 'OT' : (i - 3) + 'OT')) + '</th>';
  head += '<th class="ls-r">T</th></tr>';
  return '<div class="table-wrap"><table class="linescore"><thead>' + head + '</thead><tbody>' + row(g.away, 'away') + row(g.home, 'home') + '</tbody></table></div>';
}

// ── generic (as the Bullpen) ───────────────────────────────────────────────

function distBars(el, dist, opts) {
  const o = opts || {};
  let entries;
  if (Array.isArray(dist)) entries = dist.map((p, k) => (Array.isArray(p) ? [Number(p[0]), p[1]] : [k + (o.offset || 0), p]));
  else entries = Object.keys(dist || {}).map(k => [Number(k), dist[k]]);
  entries = entries.filter(e => isNum(e[0]) && isNum(e[1]) && e[1] > 0.0005).sort((a, b) => a[0] - b[0]);
  if (!entries.length) { empty(el, o.emptyText || 'No distribution.'); return; }
  const col = o.colour || C.accent;
  const shapes = [];
  if (isNum(o.line)) shapes.push({ type: 'line', x0: o.line, x1: o.line, yref: 'paper', y0: 0, y1: 1, line: { color: C.text2, width: 1.5, dash: 'dash' } });
  if (isNum(o.exp)) shapes.push({ type: 'line', x0: o.exp, x1: o.exp, yref: 'paper', y0: 0, y1: 1, line: { color: col, width: 1.5, dash: 'dot' } });
  const ks = entries.map(e => e[0]);
  const colourOf = k => {
    if (isNum(o.actual) && Number(k) === Number(o.actual)) return C.text;
    if (o.split !== undefined && o.split !== null) return k > o.split ? hexA(o.colours ? o.colours[0] : col, 0.85) : (k < o.split ? hexA(o.colours ? o.colours[1] : C.blue, 0.85) : hexA(C.text3, 0.8));
    return hexA(col, 0.8);
  };
  GI.plot(el, [{ type: 'bar', x: ks, y: entries.map(e => e[1]), marker: { color: ks.map(colourOf) },
    hovertemplate: (o.signed ? '%{x:+d}' : '%{x}') + ' ' + esc(o.unit || 'pts') + ': %{y:.1%}<extra></extra>' }], GI.layout({
    height: o.height || 220, bargap: 0.12, shapes: shapes,
    xaxis: { title: o.xTitle || '', fixedrange: true, dtick: ks.length > 40 ? 7 : (ks.length > 24 ? 4 : (ks.length > 12 ? 2 : 1)), tickformat: o.signed ? '+d' : 'd' },
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
  const fmt = s.fmt || (v => GI.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? GI.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : GI.divColour(v - centers[i], max, s.invert));
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
    text: rev.map(i => GI.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.accent) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => isNum(i.market))) {
    const mk = rev.filter(i => isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: mk.map(i => i.label), x: mk.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  GI.plot(el, traces, GI.layout({
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
    const col = s.colour || GI.PALETTE[i % GI.PALETTE.length];
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
  GI.plot(el, traces, GI.layout(Object.assign({
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
    const col = s.colour || GI.PALETTE[i % GI.PALETTE.length];
    const r = s.values.map(v => (isNum(v) ? v : 0));
    return { type: 'scatterpolar', r: r.concat([r[0]]), theta: labels.concat([labels[0]]), name: s.name, fill: 'toself',
      fillcolor: hexA(col, 0.18), line: { color: col, width: 2 }, hovertemplate: '%{theta}: %{r:.0f}<extra>' + esc(s.name || '') + '</extra>' };
  });
  GI.plot(el, traces, GI.layout({
    height: o.height || 360,
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { range: [0, 100], tickvals: [25, 50, 75, 100], gridcolor: '#30363d', tickfont: { size: 8, color: C.text3 }, angle: 90 },
      angularaxis: { gridcolor: '#30363d', tickfont: { size: 10, color: C.text2 }, direction: 'clockwise' } },
    showlegend: list.length > 1, legend: { orientation: 'h', y: -0.08, font: { size: 10, color: C.text2 } },
    margin: { l: 50, r: 50, t: 30, b: 30 }
  }));
}

GI.charts = Object.assign(GI.charts || {}, {
  rows: rows, fieldShapes: fieldShapes, FIELD_TICKS: FIELD_TICKS, driveRows: driveRows, driveChart: driveChart, wpRows: wpRows, wpChart: wpChart,
  fieldHeatmap: fieldHeatmap, passGrid: passGrid, gridOf: gridOf, DEPTHS: DEPTHS, LOCS: LOCS,
  percentileSliders: percentileSliders, sliderRow: sliderRow, linescore: linescore, quartersOf: quartersOf,
  distBars: distBars, heatTable: heatTable, probBars: probBars, lines: lines, radar: radar, hexA: hexA, median: median, mean: mean
});
})(window.GI);
