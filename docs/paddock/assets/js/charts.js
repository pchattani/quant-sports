/* The Quant Paddock — shared chart helpers (PD.charts).
 *
 * Every helper takes a target (element or id) first and degrades to a muted line
 * when its data is missing. Driver colours come from their team (PD.teamColour);
 * the second driver of a team is drawn dashed so teammates stay apart.
 *
 *   positionChart(el, laps, opts)        laps = race payload `laps`; opts {order, teams, control, height}
 *   gapChart(el, laps, opts)             gap to the leader per lap; opts {order, teams, control, maxGap}
 *   lapTimeViolin(el, laps, opts)        per-driver lap-time distribution; opts {order, teams, kind:'violin'|'box', clip:1.07, pits}
 *   stintChart(el, stints, opts)         horizontal stints by compound; opts {order, nLaps, pits, teams}
 *   trackMap(el, tel, opts)              tel {x:[], y:[], speed?...}; opts {colourBy: channel name or array, label, corners:[{n,d}], step, colorscale}
 *   telemetryOverlay(el, series, opts)   series [{name, colour, step|d, speed, throttle, brake, gear, rpm, drs, dash}]; opts {channels, delta, corners, height}
 *   heatTable(spec)                      returns HTML: {cols:[label|{label,title}], rows:[{label(html), values:[], href}], fmt(v), scale:'div'|'seq', max, invert, corner}
 *   posHeatmap(el, rows, opts)           rows [{label, dist:[p per position]}]; finishing-position heatmap
 *   probBars(el, items, opts)            items [{label, p, colour, market}] horizontal bars, market as a marker
 *   lines(el, series, opts)              series [{name, x, y, colour, dash, width}] simple line chart
 *   controlBands(control, nLaps)         [{kind:'SC'|'VSC'|'RED', from, to}] from race control messages
 *   bandShapes(bands, axis)              Plotly shapes for those bands on the lap axis
 */
(function (PD) {
'use strict';

const C = PD.C;

function node(el) { return typeof el === 'string' ? document.getElementById(el) : el; }
function empty(el, text) { const n = node(el); if (n) n.innerHTML = '<div class="muted">' + text + '</div>'; }

/* Colour and dash per driver: team colour; the second-listed teammate dashed. */
function styleMap(ids, teams) {
  const seen = {}, out = {};
  ids.forEach(id => {
    const t = (teams && teams[id]) || (PD.NAMES.drivers[id] || {}).team || null;
    const key = t || id;
    out[id] = { colour: t ? PD.teamColour(t) : PD.driverColour(id), dash: seen[key] ? 'dot' : 'solid', team: t };
    seen[key] = true;
  });
  return out;
}

function orderOf(obj, order) {
  const keys = Object.keys(obj || {});
  if (!order || !order.length) return keys;
  const set = {};
  keys.forEach(k => { set[k] = 1; });
  const head = order.filter(k => set[k]);
  return head.concat(keys.filter(k => head.indexOf(k) < 0));
}

// ── race control bands ─────────────────────────────────────────────────────

function controlBands(control, nLaps) {
  const evs = (control || []).filter(e => e && PD.isNum(e.lap) && (e.kind === 'SC' || e.kind === 'VSC' || e.kind === 'RED') && !/CHEQUERED/i.test(e.message || ''))
    .slice().sort((a, b) => (a.lap - b.lap) || ((a.t_ms || 0) - (b.t_ms || 0)));
  const bands = [];
  const open = {};
  evs.forEach(e => {
    const m = String(e.message || '').toUpperCase();
    const k = e.kind;
    const ending = /(IN THIS LAP|ENDING|WITHDRAWN|ENDED|RESUM|TRACK CLEAR|GREEN)/.test(m);
    if (!ending) {
      if (open[k] === undefined) open[k] = e.lap;
    } else if (open[k] !== undefined) {
      bands.push({ kind: k, from: open[k], to: Math.max(e.lap, open[k] + 0.5) });
      delete open[k];
    }
  });
  Object.keys(open).forEach(k => bands.push({ kind: k, from: open[k], to: k === 'RED' ? open[k] + 1 : Math.min(nLaps || open[k] + 3, open[k] + 3) }));
  return bands;
}
const BAND_COL = { SC: 'rgba(210,153,34,0.16)', VSC: 'rgba(210,153,34,0.08)', RED: 'rgba(248,81,73,0.18)' };
function bandShapes(bands, axis) {
  return (bands || []).map(b => ({
    type: 'rect', xref: axis || 'x', yref: 'paper', x0: b.from - 0.5, x1: b.to + 0.5, y0: 0, y1: 1,
    fillcolor: BAND_COL[b.kind] || 'rgba(255,255,255,0.05)', line: { width: 0 }, layer: 'below'
  }));
}
function bandNotes(bands) {
  return (bands || []).map(b => ({ x: (b.from + b.to) / 2, y: 1.0, xref: 'x', yref: 'paper', yanchor: 'bottom', text: b.kind, showarrow: false,
    font: { size: 9, color: b.kind === 'RED' ? C.red : C.yellow } }));
}

// ── position and gap charts ────────────────────────────────────────────────

function maxPos(pos, ids) {
  let m = ids.length;
  ids.forEach(id => (pos[id] || []).forEach(v => { if (PD.isNum(v) && v > m) m = v; }));
  return m;
}

function positionChart(el, laps, opts) {
  const o = opts || {};
  const pos = (laps || {}).positions || {};
  const ids = orderOf(pos, o.order).filter(id => (pos[id] || []).some(v => PD.isNum(v)));
  if (!ids.length) { empty(el, 'No lap-by-lap positions for this race.'); return; }
  const st = styleMap(ids, o.teams);
  let n = (laps || {}).n || 0;
  const traces = ids.map(id => {
    const ys = pos[id];
    n = Math.max(n, ys.length);
    return {
      type: 'scatter', mode: 'lines', name: PD.driverCode(id), x: ys.map((_, i) => i + 1), y: ys,
      line: { color: st[id].colour, width: 2, dash: st[id].dash, shape: 'linear' }, connectgaps: false,
      hovertemplate: PD.esc(PD.driverName(id)) + ' · P%{y} on lap %{x}<extra></extra>'
    };
  });
  const last = ids.map(id => { const ys = pos[id]; let i = ys.length - 1; while (i >= 0 && !PD.isNum(ys[i])) i--; return { id: id, i: i, y: ys[i] }; }).filter(v => v.i >= 0);
  const notes = last.map(v => ({ x: v.i + 1, y: v.y, xanchor: 'left', text: ' ' + PD.driverCode(v.id), showarrow: false, font: { size: 10, color: st[v.id].colour } }));
  const bands = controlBands(o.control, n);
  PD.plot(el, traces, PD.layout({
    height: o.height || 520, hovermode: 'closest',
    xaxis: { title: 'Lap', range: [0.5, n + 3.5], zeroline: false },
    yaxis: { title: 'Position', range: [maxPos(pos, ids) + 0.5, 0.5], dtick: 1, zeroline: false, fixedrange: true },
    shapes: bandShapes(bands), annotations: notes.concat(bandNotes(bands)),
    margin: { l: 50, r: 20, t: 20, b: 45 }
  }));
}

function gapChart(el, laps, opts) {
  const o = opts || {};
  const gaps = (laps || {}).gaps || {};
  const ids = orderOf(gaps, o.order).filter(id => (gaps[id] || []).some(v => PD.isNum(v)));
  if (!ids.length) { empty(el, 'No gap data for this race.'); return; }
  const st = styleMap(ids, o.teams);
  const all = [];
  ids.forEach(id => gaps[id].forEach(v => { if (PD.isNum(v)) all.push(v); }));
  all.sort((a, b) => a - b);
  const cap = o.maxGap || Math.max(10, all[Math.floor(all.length * 0.9)] * 1.15 || 60);
  let n = (laps || {}).n || 0;
  const traces = ids.map(id => {
    n = Math.max(n, gaps[id].length);
    return {
      type: 'scatter', mode: 'lines', name: PD.driverCode(id), x: gaps[id].map((_, i) => i + 1), y: gaps[id],
      line: { color: st[id].colour, width: 1.8, dash: st[id].dash }, connectgaps: false,
      hovertemplate: PD.esc(PD.driverName(id)) + ' · +%{y:.1f}s on lap %{x}<extra></extra>'
    };
  });
  const bands = controlBands(o.control, n);
  PD.plot(el, traces, PD.layout({
    height: o.height || 440,
    xaxis: { title: 'Lap', range: [0.5, n + 0.5] },
    yaxis: { title: 'Gap to leader (s)', range: [cap, -cap * 0.03], zeroline: true },
    shapes: bandShapes(bands), annotations: bandNotes(bands),
    showlegend: true, legend: { orientation: 'h', y: -0.18, font: { size: 10, color: C.text2 } },
    margin: { l: 55, r: 20, t: 20, b: 50 }
  }));
}

// ── lap-time distribution ──────────────────────────────────────────────────

function cleanLaps(times, clip, pitLaps) {
  const v = (times || []).map((t, i) => ({ lap: i + 1, s: PD.isNum(t) ? t / 1000 : null }))
    .filter(x => x.s !== null && x.lap > 1 && !(pitLaps && (pitLaps[x.lap] || pitLaps[x.lap - 1])));
  if (!v.length) return [];
  const sorted = v.map(x => x.s).sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)];
  return v.filter(x => x.s <= med * (clip || 1.07));
}

function lapTimeViolin(el, laps, opts) {
  const o = opts || {};
  const times = (laps || {}).times || {};
  const pitIdx = {};
  (o.pits || []).forEach(p => { (pitIdx[p.driver] = pitIdx[p.driver] || {})[p.lap] = 1; });
  const ids = orderOf(times, o.order).filter(id => cleanLaps(times[id], o.clip, pitIdx[id]).length >= 3);
  if (!ids.length) { empty(el, 'No lap times for this race.'); return; }
  const st = styleMap(ids, o.teams);
  const kind = o.kind === 'box' ? 'box' : 'violin';
  const traces = ids.map(id => {
    const v = cleanLaps(times[id], o.clip, pitIdx[id]);
    const t = {
      type: kind, name: PD.driverCode(id), y: v.map(x => x.s), x: v.map(() => PD.driverCode(id)),
      text: v.map(x => 'Lap ' + x.lap), line: { color: st[id].colour, width: 1 }, fillcolor: hexA(st[id].colour, 0.35),
      marker: { color: st[id].colour, size: 3 }, hoveron: 'points', hovertemplate: PD.esc(PD.driverName(id)) + ' · %{text} · %{y:.3f}s<extra></extra>'
    };
    if (kind === 'violin') Object.assign(t, { points: false, box: { visible: true, width: 0.25, fillcolor: 'rgba(13,17,23,0.6)', line: { color: C.text2 } }, meanline: { visible: false }, spanmode: 'hard', scalemode: 'width', width: 0.85 });
    else Object.assign(t, { boxpoints: 'outliers', boxmean: false });
    return t;
  });
  PD.plot(el, traces, PD.layout({
    height: o.height || 440,
    xaxis: { type: 'category', categoryorder: 'array', categoryarray: ids.map(PD.driverCode), tickfont: { size: 10 } },
    yaxis: { title: 'Lap time (s)', zeroline: false },
    margin: { l: 55, r: 15, t: 15, b: 45 }, violingap: 0.15, boxgap: 0.3
  }));
}

function hexA(hex, a) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
}

// ── tyre stints ────────────────────────────────────────────────────────────

const COMP_ORDER = ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET', 'UNKNOWN'];
function stintChart(el, stints, opts) {
  const o = opts || {};
  const ids = orderOf(stints, o.order).filter(id => (stints[id] || []).length);
  if (!ids.length) { empty(el, 'No tyre stints for this race.'); return; }
  const n = o.nLaps || Math.max.apply(null, ids.map(id => Math.max.apply(null, stints[id].map(s => s.to || 0))));
  const byComp = {};
  ids.forEach(id => stints[id].forEach((s, i) => {
    const c = s.compound ? String(s.compound).toUpperCase() : 'UNKNOWN';
    const key = COMP_ORDER.indexOf(c) >= 0 ? c : 'UNKNOWN';
    const b = byComp[key] = byComp[key] || { y: [], x: [], base: [], text: [], hov: [] };
    const from = s.from || 1, to = s.to || n;
    b.y.push(PD.driverCode(id)); b.base.push(from - 1); b.x.push(to - from + 1);
    b.text.push(to - from + 1 >= 3 ? (key === 'UNKNOWN' ? '' : key.charAt(0)) + (to - from + 1 >= 6 ? ' ' + (to - from + 1) : '') : '');
    b.hov.push(PD.esc(PD.driverName(id)) + ' · stint ' + (i + 1) + ' · ' + (s.compound ? PD.esc(s.compound) : 'compound unknown') + '<br>laps ' + from + '–' + to + (PD.isNum(s.age_start) && s.age_start > 0 ? ' · ' + s.age_start + ' laps old at fitting' : ''));
  }));
  const traces = COMP_ORDER.filter(k => byComp[k]).map(k => ({
    type: 'bar', orientation: 'h', name: k === 'UNKNOWN' ? 'Unknown' : k.charAt(0) + k.slice(1).toLowerCase(),
    y: byComp[k].y, x: byComp[k].x, base: byComp[k].base, text: byComp[k].text, textposition: 'inside', insidetextanchor: 'middle', textangle: 0, constraintext: 'none',
    textfont: { color: k === 'HARD' || k === 'MEDIUM' ? '#0d1117' : '#ffffff', size: 10 },
    marker: { color: PD.compoundColour(k), line: { color: '#0d1117', width: 1.5 } },
    hovertext: byComp[k].hov, hovertemplate: '%{hovertext}<extra></extra>'
  }));
  PD.plot(el, traces, PD.layout({
    height: o.height || Math.max(260, ids.length * 24 + 80), barmode: 'overlay', bargap: 0.28,
    xaxis: { title: 'Lap', range: [0, n + 0.5], zeroline: false },
    yaxis: { type: 'category', categoryorder: 'array', categoryarray: ids.map(PD.driverCode).reverse(), fixedrange: true, tickfont: { size: 10 } },
    showlegend: o.legend === true, legend: { orientation: 'h', y: 1.06, x: 0, font: { color: C.text2 } },
    margin: { l: 50, r: 15, t: o.legend === true ? 30 : 10, b: 45 }
  }));
}

// ── track map and telemetry ────────────────────────────────────────────────

function trackMap(el, tel, opts) {
  const o = opts || {};
  const x = (tel || {}).x || [], y = (tel || {}).y || [];
  if (x.length < 10) { empty(el, 'No position data for a track map.'); return; }
  const cb = typeof o.colourBy === 'string' ? (tel[o.colourBy] || null) : (o.colourBy || null);
  const label = o.label || (typeof o.colourBy === 'string' ? o.colourBy : '');
  const traces = [{
    type: 'scatter', mode: 'lines', x: x, y: y, line: { color: '#30363d', width: 10 }, hoverinfo: 'skip'
  }];
  if (cb) {
    traces.push({
      type: 'scatter', mode: 'markers', x: x, y: y,
      marker: { size: o.size || 5, color: cb, colorscale: o.colorscale || 'Plasma', showscale: o.scale !== false,
                colorbar: { title: { text: label, side: 'right' }, thickness: 10, len: 0.7, tickfont: { color: C.text2 } } },
      text: cb.map(v => label + ' ' + v), hovertemplate: '%{text}<extra></extra>'
    });
  } else {
    traces.push({ type: 'scatter', mode: 'lines', x: x, y: y, line: { color: o.colour || C.blue, width: 3 }, hoverinfo: 'skip' });
  }
  const notes = [];
  const step = o.step || tel.d || 10;
  (o.corners || []).forEach(c => {
    const i = Math.round((c.d || 0) / step);
    if (i >= 0 && i < x.length) notes.push({ x: x[i], y: y[i], text: String(c.n), showarrow: false, font: { size: 9, color: C.text }, bgcolor: 'rgba(13,17,23,0.7)' });
  });
  PD.plot(el, traces, PD.layout({
    height: o.height || 420,
    xaxis: { visible: false, fixedrange: true }, yaxis: { visible: false, scaleanchor: 'x', scaleratio: 1, fixedrange: true },
    annotations: notes, margin: { l: 10, r: 10, t: 10, b: 10 }
  }));
}

const CH_LABEL = { speed: 'Speed (km/h)', throttle: 'Throttle %', brake: 'Brake', gear: 'Gear', rpm: 'RPM', drs: 'DRS', delta: 'Delta (s)' };

/* Cumulative time (s) along the lap from speed samples at a fixed distance step. */
function cumTime(speed, step) {
  const out = [0];
  for (let i = 1; i < speed.length; i++) {
    const v = Math.max(5, ((speed[i] || 0) + (speed[i - 1] || 0)) / 2) / 3.6;
    out.push(out[i - 1] + step / v);
  }
  return out;
}

function telemetryOverlay(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => s && (s.speed || []).length);
  if (!list.length) { empty(el, 'No telemetry for this selection.'); return; }
  let chans = (o.channels || ['speed', 'throttle', 'brake', 'gear']).filter(c => list.some(s => (s[c] || []).length));
  const withDelta = o.delta !== false && list.length >= 2;
  if (withDelta) chans = ['delta'].concat(chans);
  const weights = chans.map(c => (c === 'speed' ? 2.2 : c === 'delta' ? 1.2 : 1));
  const tot = weights.reduce((a, b) => a + b, 0), gap = 0.03;
  const dom = [];
  let top = 1;
  weights.forEach(w => { const h = (1 - gap * (chans.length - 1)) * w / tot; dom.push([Math.max(0, top - h), top]); top -= h + gap; });
  const traces = [];
  const xs = s => (Array.isArray(s.d) ? s.d : s.speed.map((_, i) => i * (s.step || s.d || 10)));
  const ref = list[0], refT = cumTime(ref.speed, ref.step || ref.d || 10), refX = xs(ref);
  chans.forEach((c, k) => {
    const ax = k === 0 ? '' : String(k + 1);
    list.forEach((s, j) => {
      let y;
      if (c === 'delta') {
        if (j === 0) return;
        const t = cumTime(s.speed, s.step || s.d || 10), x = xs(s);
        y = x.map((d, i) => { const ri = Math.min(refT.length - 1, Math.round(d / (ref.step || ref.d || 10))); return t[i] - refT[ri]; });
        traces.push({ type: 'scatter', mode: 'lines', x: x, y: y, xaxis: 'x', yaxis: 'y' + ax, name: s.name + ' v ' + ref.name,
          line: { color: s.colour || PD.PALETTE[j], width: 1.6 }, hovertemplate: PD.esc(s.name) + ' %{y:+.3f}s at %{x} m<extra></extra>', showlegend: false });
        return;
      }
      y = s[c] || [];
      if (c === 'brake') y = y.map(v => (v > 1 ? v / 100 : v));
      traces.push({ type: 'scatter', mode: 'lines', x: xs(s), y: y, xaxis: 'x', yaxis: 'y' + ax, name: s.name, legendgroup: s.name, showlegend: k === (withDelta ? 1 : 0),
        line: { color: s.colour || PD.PALETTE[j % PD.PALETTE.length], width: c === 'speed' ? 1.8 : 1.3, dash: s.dash || 'solid', shape: c === 'gear' || c === 'drs' ? 'hv' : 'linear' },
        hovertemplate: PD.esc(s.name) + ' · ' + CH_LABEL[c] + ' %{y} at %{x} m<extra></extra>' });
    });
  });
  const lay = PD.layout({
    height: o.height || (180 + chans.length * 110), hovermode: 'x unified', showlegend: true,
    legend: { orientation: 'h', y: 1.04, x: 0, font: { color: C.text2 } },
    margin: { l: 60, r: 15, t: 30, b: 40 },
    xaxis: { title: 'Distance (m)', anchor: 'y' + (chans.length > 1 ? chans.length : ''), zeroline: false }
  });
  chans.forEach((c, k) => {
    const key = k === 0 ? 'yaxis' : 'yaxis' + (k + 1);
    lay[key] = Object.assign({}, PD.DARK_LAYOUT.yaxis, { domain: dom[k], title: { text: CH_LABEL[c] || c, font: { size: 10 } }, zeroline: c === 'delta', fixedrange: true },
      c === 'brake' ? { range: [-0.05, 1.05], tickvals: [0, 1], ticktext: ['off', 'on'] } : {}, c === 'throttle' ? { range: [-3, 103] } : {});
  });
  const corners = o.corners || [];
  lay.shapes = corners.map(cn => ({ type: 'line', xref: 'x', yref: 'paper', x0: cn.d, x1: cn.d, y0: 0, y1: 1, line: { color: 'rgba(139,148,158,0.18)', width: 1, dash: 'dot' } }));
  lay.annotations = corners.map(cn => ({ x: cn.d, y: 1, xref: 'x', yref: 'paper', yanchor: 'bottom', text: 'T' + cn.n, showarrow: false, font: { size: 9, color: C.text3 } }));
  PD.plot(el, traces, lay);
}

// ── tables and heatmaps ────────────────────────────────────────────────────

function heatTable(spec) {
  const s = spec || {};
  const rows = s.rows || [];
  if (!rows.length) return '<div class="muted">No data.</div>';
  // center: 'col' colours each value against its column median (for all-positive scales).
  const nCols = Math.max.apply(null, rows.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(PD.isNum(s.center) ? s.center : 0); continue; }
    const col = rows.map(r => (r.values || [])[i]).filter(PD.isNum).sort((a, b) => a - b);
    centers.push(col.length ? col[Math.floor(col.length / 2)] : 0);
  }
  const vals = [];
  rows.forEach(r => (r.values || []).forEach((v, i) => { if (PD.isNum(v)) vals.push(Math.abs(v - centers[i])); }));
  vals.sort((a, b) => a - b);
  const max = s.max || vals[Math.floor(vals.length * 0.95)] || vals[vals.length - 1] || 1;
  const fmt = s.fmt || (v => PD.num(v, 2));
  const colour = (v, i) => (s.scale === 'seq' ? PD.seqColour(v / (s.max || (vals[vals.length - 1] || 1))) : PD.divColour(v - centers[i], max, s.invert));
  let h = '<div class="table-wrap heat-wrap"' + (s.maxWidth ? ' style="max-width:' + s.maxWidth + 'px"' : '') + '><table class="wc-table heat-table"><thead><tr><th class="heat-corner">' + PD.esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th' + (cc.title ? ' title="' + PD.esc(cc.title) + '"' : '') + '>' + PD.esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(r => {
    h += '<tr><td class="heat-label">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, i) => {
      const t = r.titles && r.titles[i] ? ' title="' + PD.esc(r.titles[i]) + '"' : '';
      h += PD.isNum(v) ? '<td class="heat-cell" style="background:' + colour(v, i) + '"' + t + '>' + fmt(v) + '</td>' : '<td class="heat-cell heat-empty"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}

function posHeatmap(el, rows, opts) {
  const o = opts || {};
  const list = (rows || []).filter(r => (r.dist || []).length);
  if (!list.length) { empty(el, 'No position distribution.'); return; }
  const n = Math.max.apply(null, list.map(r => r.dist.length));
  const z = list.map(r => { const a = r.dist.slice(); while (a.length < n) a.push(0); return a.map(p => (p > 0 ? p : null)); });
  const text = z.map(r => r.map(p => (p === null ? '' : p >= 0.095 ? Math.round(p * 100) + '' : p >= 0.01 && n <= 12 ? Math.round(p * 100) + '' : '')));
  PD.plot(el, [{
    type: 'heatmap', z: z, x: Array.from({ length: n }, (_, i) => (o.labels ? o.labels[i] : 'P' + (i + 1))), y: list.map(r => r.label),
    text: text, texttemplate: '%{text}', textfont: { size: 9, color: '#e6edf3' },
    colorscale: [[0, '#0d2340'], [0.15, '#1f4f8a'], [0.4, '#2f7fd8'], [0.7, '#d29922'], [1, '#f85149']], zmin: 0, zmax: o.zmax || null,
    hovertemplate: '%{y} · %{x}: %{z:.1%}<extra></extra>', xgap: 1, ygap: 1, showscale: false
  }], PD.layout({
    height: o.height || Math.max(260, list.length * 22 + 70),
    xaxis: { side: 'top', tickfont: { size: 10 }, fixedrange: true }, yaxis: { autorange: 'reversed', tickfont: { size: 10 }, fixedrange: true, automargin: true },
    margin: { l: 110, r: 10, t: 30, b: 10 }
  }));
}

function probBars(el, items, opts) {
  const o = opts || {};
  const list = (items || []).filter(i => PD.isNum(i.p) && (i.p > 0 || PD.isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) { empty(el, o.emptyText || 'Nothing to show.'); return; }
  const rev = list.slice().reverse();
  const max = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  const traces = [{
    type: 'bar', orientation: 'h', y: rev.map(i => i.label), x: rev.map(i => i.p), name: o.modelName || 'Model',
    text: rev.map(i => PD.pct(i.p)), textposition: 'outside', cliponaxis: false, textfont: { color: C.text, size: 11 },
    marker: { color: rev.map(i => i.colour || C.blue) }, showlegend: false, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.modelName || 'Model') + '</extra>'
  }];
  if (list.some(i => PD.isNum(i.market))) {
    const m = rev.filter(i => PD.isNum(i.market));
    traces.push({ type: 'scatter', mode: 'markers', name: o.marketName || 'Market', y: m.map(i => i.label), x: m.map(i => i.market),
      marker: { symbol: 'line-ns-open', size: 18, color: C.text, line: { width: 3, color: C.text } }, hovertemplate: '%{y}: %{x:.1%}<extra>' + (o.marketName || 'Market') + '</extra>' });
  }
  PD.plot(el, traces, PD.layout({
    height: o.height || Math.max(220, list.length * 30 + 50), bargap: 0.3,
    xaxis: { tickformat: '.0%', range: [0, Math.min(1.05, max * 1.25 + 0.02)], fixedrange: true },
    yaxis: { automargin: true, fixedrange: true, tickfont: { size: 11 } },
    showlegend: traces.length > 1, legend: { orientation: 'h', y: -0.12, font: { color: C.text2 } },
    margin: { l: 110, r: 50, t: 10, b: 35 }
  }));
}

function lines(el, series, opts) {
  const o = opts || {};
  const list = (series || []).filter(s => (s.y || []).length);
  if (!list.length) { empty(el, o.emptyText || 'No data.'); return; }
  const traces = list.map((s, i) => ({
    type: 'scatter', mode: s.mode || o.mode || 'lines', name: s.name, x: s.x || s.y.map((_, k) => k + 1), y: s.y,
    line: { color: s.colour || PD.PALETTE[i % PD.PALETTE.length], width: s.width || 2, dash: s.dash || 'solid', shape: s.shape || 'linear' },
    marker: { size: 5, color: s.colour || PD.PALETTE[i % PD.PALETTE.length] }, connectgaps: true,
    error_y: s.err ? { type: 'data', array: s.err, visible: true, color: s.colour, thickness: 1, width: 0 } : undefined,
    hovertemplate: s.hover || (PD.esc(s.name) + ' · %{y}<extra></extra>')
  }));
  PD.plot(el, traces, PD.layout(Object.assign({
    height: o.height || 380, showlegend: o.legend !== false,
    legend: { orientation: 'h', y: -0.2, font: { size: 10, color: C.text2 } },
    xaxis: Object.assign({ title: o.xTitle || '' }, o.xaxis || {}), yaxis: Object.assign({ title: o.yTitle || '' }, o.yaxis || {}),
    margin: { l: 55, r: 20, t: 20, b: 55 }
  }, o.layout || {})));
}

PD.charts = Object.assign(PD.charts || {}, {
  positionChart: positionChart, gapChart: gapChart, lapTimeViolin: lapTimeViolin, stintChart: stintChart,
  trackMap: trackMap, telemetryOverlay: telemetryOverlay, heatTable: heatTable, posHeatmap: posHeatmap,
  probBars: probBars, lines: lines, controlBands: controlBands, bandShapes: bandShapes, styleMap: styleMap, cumTime: cumTime, hexA: hexA
});
})(window.PD);
