/* The Quant Paddock — the telemetry lab (#/race/<y>/<r>/telemetry).
 *
 * Two drivers, one lap each, overlaid on a shared distance axis: the cumulative time
 * delta, speed, throttle, brake, gear, RPM and DRS; a track map coloured by which
 * driver is faster in each 50 m segment; a corners table (minimum speed and braking
 * point at each corner found on the session's reference lap); and per-lap summaries.
 *
 * Fastest laps come from the stored traces (data/<y>/telemetry/<key>.json, sampled
 * every 10 m). Any other lap is fetched live from OpenF1 car_data for the lap's time
 * window (session date_start + the lap's t_start_ms from data/<y>/sessions/<key>.json),
 * distance is integrated from speed (d += v·dt) and rescaled to the reference lap
 * length, as oddsmarkets/f1/telemetry.py does.
 *
 * Telemetry and session files key drivers by car NUMBER; the race payload keys by
 * driverId. The map number -> driverId goes: session drivers' name_acronym -> the
 * driver code in data/index.json (or harvested names), then the car number in
 * index.json, then the race results' number when present. */
(function (PD) {
'use strict';

const { esc, num, pct, isNum, card, muted, tableHTML, sortable, plot, layout, C } = PD;
const PG = () => PD.pg;
const STEP = 10;            // m, as STEP_M in telemetry.py
const SEG = 50;             // m, track-map segment
const APEX_WINDOW_M = 80;   // as telemetry.py
const BRAKE_LOOKBACK_M = 400;
const DRS_OPEN = [10, 12, 14];
const OPENF1 = 'https://api.openf1.org/v1/';
const LIVE = {};            // fetched laps, by session|driver|lap
const CA = C.blue, CB = C.orange;
const KIND_LABEL = { race: 'Race', quali: 'Qualifying', sprint: 'Sprint', sprint_quali: 'Sprint qualifying', fp1: 'Practice 1', fp2: 'Practice 2', fp3: 'Practice 3' };

let S = null;   // page state

/* number (string) -> driverId */
function numberMap(sessionRec, race) {
  const out = {};
  const idx = PD.index() || {};
  const byCode = {}, byNum = {};
  const names = PD.NAMES.drivers || {};
  Object.keys(names).forEach(id => { const x = names[id]; if (x.code) byCode[String(x.code).toUpperCase()] = id; if (isNum(x.number)) byNum[String(x.number)] = id; });
  Object.keys(idx.drivers || {}).forEach(id => { const x = idx.drivers[id]; if (x.code) byCode[String(x.code).toUpperCase()] = id; if (isNum(x.number)) byNum[String(x.number)] = id; });
  const resNum = {};
  ((race || {}).results || []).concat((race || {}).qualifying || []).forEach(r => { if (isNum(r.number) && r.driver) resNum[String(r.number)] = r.driver; });
  const D = (sessionRec || {}).drivers || {};
  Object.keys(D).forEach(n => {
    const ac = String(D[n].name_acronym || '').toUpperCase();
    out[n] = resNum[n] || byCode[ac] || byNum[n] || null;
  });
  return out;
}

function dname(n) {
  const id = S.map[n];
  const D = ((S.sess || {}).drivers || {})[n] || {};
  return id ? PD.driverName(id) : (D.full_name ? PD.titleCase(String(D.full_name).toLowerCase()) : '#' + n);
}
function dshort(n) { const D = ((S.sess || {}).drivers || {})[n] || {}; return D.name_acronym || (S.map[n] ? PD.driverCode(S.map[n]) : '#' + n); }
function dcolour(n) {
  const id = S.map[n], D = ((S.sess || {}).drivers || {})[n] || {};
  if (D.team_colour) return '#' + String(D.team_colour).replace('#', '');
  return id ? PD.driverColour(id) : C.text3;
}
function lapRows(n) { return (((S.sess || {}).laps || {})[n] || []).filter(r => isNum(r[2]) && r[2] > 0 && isNum(r[1])); }
function fastestLap(n) {
  const f = ((S.tel || {}).fastest || {})[n];
  if (f && isNum(f.lap)) return f.lap;
  const rows = lapRows(n);
  if (!rows.length) return null;
  return rows.slice().sort((a, b) => a[2] - b[2])[0][0];
}

// ── traces ─────────────────────────────────────────────────────────────────

/* Cumulative time at each grid point from speed, scaled to the lap time. */
function timeFromSpeed(speed, step, lapMs) {
  const t = [0];
  for (let i = 1; i < speed.length; i++) { const v = Math.max(5, (speed[i] + speed[i - 1]) / 2) / 3.6; t.push(t[i - 1] + step / v); }
  const total = t[t.length - 1] + step / Math.max(5, speed[speed.length - 1] / 3.6);
  const k = lapMs && total > 0 ? lapMs / 1000 / total : 1;
  return t.map(v => v * k);
}

function storedTrace(n) {
  const f = ((S.tel || {}).fastest || {})[n];
  if (!f) return null;
  const step = f.d || STEP;
  return { n: n, lap: f.lap, ms: f.ms, step: step, d: f.speed.map((v, i) => i * step), speed: f.speed, throttle: f.throttle, brake: f.brake, gear: f.gear, rpm: f.rpm, drs: f.drs,
    t: timeFromSpeed(f.speed, step, f.ms), x: f.x || null, y: f.y || null, source: 'stored' };
}

function interp(xs, ys, x) {
  let lo = 0, hi = xs.length - 1;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[hi]) return ys[hi];
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  const u = (x - xs[lo]) / ((xs[hi] - xs[lo]) || 1);
  return ys[lo] + u * (ys[hi] - ys[lo]);
}

/* Fetch one lap's car data from OpenF1 and resample it every STEP metres. */
function fetchLap(n, lap) {
  const key = S.key + '|' + n + '|' + lap;
  if (LIVE[key]) return LIVE[key];
  const row = lapRows(n).find(r => r[0] === lap);
  if (!row) return Promise.resolve(null);
  const t0 = Date.parse(((S.sess || {}).session || {}).date_start);
  if (isNaN(t0)) return Promise.reject(new Error('the session record has no start time'));
  const a = new Date(t0 + row[1]), b = new Date(t0 + row[1] + row[2]);
  const iso = d => d.toISOString().replace('Z', '');
  const url = OPENF1 + 'car_data?session_key=' + S.key + '&driver_number=' + n + '&date>=' + encodeURIComponent(iso(a)) + '&date<=' + encodeURIComponent(iso(b));
  // One automatic retry after a rate-limit answer (OpenF1 allows 30 requests a minute).
  const get = attempt => fetch(url).then(r => {
    if (r.status === 429 && attempt === 0) {
      status('OpenF1 rate limit reached (30 requests a minute); retrying in 30 s…', true);
      return new Promise(res => setTimeout(res, 30000)).then(() => get(1));
    }
    if (r.status === 429) throw new Error('OpenF1 rate limit (30 requests a minute); try again in a minute');
    if (!r.ok) throw new Error('OpenF1 answered HTTP ' + r.status);
    return r.json();
  });
  LIVE[key] = get(0).then(rows => {
    if (!Array.isArray(rows) || rows.length < 20) throw new Error('OpenF1 returned ' + (Array.isArray(rows) ? rows.length : 0) + ' car-data samples for this lap');
    rows.sort((p, q) => Date.parse(p.date) - Date.parse(q.date));
    const ts = rows.map(r => (Date.parse(r.date) - a.getTime()) / 1000);
    const sp = rows.map(r => (isNum(r.speed) ? r.speed : 0));
    const d = [0];
    for (let i = 1; i < rows.length; i++) d.push(d[i - 1] + (sp[i] / 3.6) * (ts[i] - ts[i - 1]));
    const len = ((S.tel || {}).ref || {}).length_m || d[d.length - 1];
    const scale = d[d.length - 1] > 0 ? len / d[d.length - 1] : 1;
    const ds = d.map(v => v * scale);
    const grid = []; for (let x = 0; x < len; x += STEP) grid.push(x);
    const ch = k => rows.map(r => (isNum(r[k]) ? r[k] : 0));
    const lin = arr => grid.map(x => Math.round(interp(ds, arr, x)));
    const near = arr => grid.map(x => { let lo = 0; while (lo < ds.length - 1 && ds[lo + 1] <= x) lo++; return arr[lo]; });
    const tt = grid.map(x => interp(ds, ts, x));
    LIVE[key + ':raw'] = { start: a.getTime(), end: b.getTime() };
    return { n: n, lap: lap, ms: row[2], step: STEP, d: grid, speed: lin(sp), throttle: lin(ch('throttle')), brake: near(ch('brake')), gear: near(ch('n_gear')), rpm: lin(ch('rpm')), drs: near(ch('drs')), t: tt, x: null, y: null, source: 'live', raw: rows.length };
  });
  LIVE[key].catch(() => { delete LIVE[key]; });
  return LIVE[key];
}

function getTrace(n, lap) {
  const f = ((S.tel || {}).fastest || {})[n];
  if (f && f.lap === lap) return Promise.resolve(storedTrace(n));
  return fetchLap(n, lap);
}

/* Track geometry for the map: any stored trace with x/y, else fetch the first driver's lap location. */
function geometry(tr) {
  const F = (S.tel || {}).fastest || {};
  const pref = [tr[0] && tr[0].n, tr[1] && tr[1].n, ((S.tel || {}).ref || {}).driver].concat(Object.keys(F));
  for (let i = 0; i < pref.length; i++) { const f = F[pref[i]]; if (f && (f.x || []).length > 10) return Promise.resolve({ x: f.x, y: f.y, step: f.d || STEP }); }
  // Live: location for driver A's lap, placed on distance by time.
  const A = tr[0];
  if (!A) return Promise.resolve(null);
  const row = lapRows(A.n).find(r => r[0] === A.lap);
  const t0 = Date.parse(((S.sess || {}).session || {}).date_start);
  if (!row || isNaN(t0)) return Promise.resolve(null);
  const a = new Date(t0 + row[1]), b = new Date(t0 + row[1] + row[2]);
  const iso = d => d.toISOString().replace('Z', '');
  return fetch(OPENF1 + 'location?session_key=' + S.key + '&driver_number=' + A.n + '&date>=' + encodeURIComponent(iso(a)) + '&date<=' + encodeURIComponent(iso(b)))
    .then(r => (r.ok ? r.json() : null)).then(rows => {
      if (!Array.isArray(rows) || rows.length < 20) return null;
      rows.sort((p, q) => Date.parse(p.date) - Date.parse(q.date));
      const lt = rows.map(r => (Date.parse(r.date) - a.getTime()) / 1000);
      const tScale = A.source === 'stored' ? 1 : 1;
      const x = A.t.map(tq => { let k = 0; while (k < lt.length - 1 && lt[k] < tq * tScale) k++; return rows[k].x; });
      const y = A.t.map(tq => { let k = 0; while (k < lt.length - 1 && lt[k] < tq * tScale) k++; return rows[k].y; });
      return { x: x, y: y, step: A.step };
    }).catch(() => null);
}

// ── drawing ────────────────────────────────────────────────────────────────

function cornerMarks() {
  return (((S.tel || {}).ref || {}).corners || []);
}

function drawStack(A, B) {
  const len = Math.min(A.d.length, B.d.length);
  const d = A.d.slice(0, len);
  const delta = d.map((x, i) => B.t[i] - A.t[i]);   // + means A ahead
  const nA = dshort(A.n) + ' L' + A.lap, nB = dshort(B.n) + ' L' + B.lap;
  const tr = [];
  const ax = (i) => (i === 1 ? '' : String(i));
  const add = (k, row, name, colour, data, extra) => tr.push(Object.assign({ type: 'scatter', mode: 'lines', name: name, x: d, y: data.slice(0, len), xaxis: 'x', yaxis: 'y' + ax(row), line: { color: colour, width: 1.6 }, legendgroup: name, showlegend: row === 2, hovertemplate: name + ' %{x} m: %{y}<extra>' + k + '</extra>' }, extra || {}));
  tr.push({ type: 'scatter', mode: 'lines', name: 'Delta', x: d, y: delta, xaxis: 'x', yaxis: 'y', line: { color: '#e6edf3', width: 1.5 }, fill: 'tozeroy', fillcolor: 'rgba(139,148,158,0.15)', showlegend: false, hovertemplate: '%{x} m: %{y:+.3f} s (+ = ' + esc(dshort(A.n)) + ' ahead)<extra>delta</extra>' });
  [['speed', 2, 'km/h'], ['throttle', 3, '%'], ['brake', 4, ''], ['gear', 5, ''], ['rpm', 6, ''], ['drs', 7, '']].forEach(c => {
    add(c[0], c[1], nA, CA, A[c[0]], c[0] === 'gear' ? { line: { color: CA, width: 1.6, shape: 'hv' } } : null);
    add(c[0], c[1], nB, CB, B[c[0]], c[0] === 'gear' ? { line: { color: CB, width: 1.6, shape: 'hv' } } : null);
  });
  const H = [0.14, 0.26, 0.13, 0.08, 0.11, 0.13, 0.08];   // top to bottom share
  const gap = 0.012;
  let top = 1;
  const axes = {};
  const titles = ['Delta (s)', 'Speed', 'Throttle %', 'Brake', 'Gear', 'RPM', 'DRS'];
  H.forEach((h, i) => {
    const lo = Math.max(0, top - h);
    axes['yaxis' + ax(i + 1)] = { domain: [lo + gap / 2, top - gap / 2], title: { text: titles[i], font: { size: 10 } }, gridcolor: '#21262d', zerolinecolor: '#6e7681', linecolor: '#30363d', fixedrange: true };
    top = lo;
  });
  axes.yaxis4.range = [-5, 105]; axes.yaxis4.tickvals = [0, 100]; axes.yaxis3.range = [-5, 105];
  const shapes = cornerMarks().map(c => ({ type: 'line', x0: c.d, x1: c.d, yref: 'paper', y0: 0, y1: 1, line: { color: '#30363d', width: 1, dash: 'dot' } }));
  const ann = cornerMarks().map(c => ({ x: c.d, y: 1, yref: 'paper', text: 'T' + c.n, showarrow: false, yanchor: 'bottom', font: { size: 9, color: C.text3 } }));
  plot('tl-stack', tr, layout(Object.assign({ showlegend: true, legend: { orientation: 'h', y: 1.04, x: 0.5, xanchor: 'center', font: { color: C.text2 } }, hovermode: 'x unified',
    margin: { l: 60, r: 15, t: 40, b: 40 }, xaxis: { title: 'Distance (m)', anchor: 'y7', range: [0, d[d.length - 1]], showspikes: true, spikemode: 'across', spikecolor: '#6e7681', spikethickness: 1 }, shapes: shapes, annotations: ann }, axes)));
  return delta;
}

function drawMap(A, B, geo) {
  if (!geo) { document.getElementById('tl-map').innerHTML = muted('No position data for this session: the map needs a stored trace or the OpenF1 location feed.'); return; }
  const len = Math.min(A.t.length, B.t.length, geo.x.length);
  const perSeg = Math.max(1, Math.round(SEG / A.step));
  const xa = [], ya = [], xb = [], yb = [], txt = [];
  let winsA = 0, winsB = 0;
  for (let s = 0; s * perSeg < len - 1; s++) {
    const i0 = s * perSeg, i1 = Math.min(len - 1, (s + 1) * perSeg);
    const dtA = A.t[i1] - A.t[i0], dtB = B.t[i1] - B.t[i0];
    const fasterA = dtA <= dtB;
    if (fasterA) winsA++; else winsB++;
    const X = fasterA ? xa : xb, Y = fasterA ? ya : yb;
    for (let i = i0; i <= i1; i++) { X.push(geo.x[i]); Y.push(geo.y[i]); }
    X.push(null); Y.push(null);
    txt.push(fasterA);
  }
  const cs = cornerMarks().map(c => { const k = Math.min(len - 1, Math.round(c.d / A.step)); return { x: geo.x[k], y: geo.y[k], text: String(c.n), showarrow: false, font: { size: 10, color: '#ffffff' }, bgcolor: 'rgba(13,17,23,0.75)', borderpad: 2 }; });
  plot('tl-map', [
    { type: 'scatter', mode: 'lines', x: geo.x.slice(0, len), y: geo.y.slice(0, len), line: { color: '#30363d', width: 10 }, hoverinfo: 'skip', showlegend: false },
    { type: 'scatter', mode: 'lines', name: dshort(A.n) + ' faster (' + winsA + ')', x: xa, y: ya, line: { color: CA, width: 5 }, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'lines', name: dshort(B.n) + ' faster (' + winsB + ')', x: xb, y: yb, line: { color: CB, width: 5 }, hoverinfo: 'skip' },
    { type: 'scatter', mode: 'markers', x: [geo.x[0]], y: [geo.y[0]], marker: { symbol: 'square', size: 10, color: '#ffffff' }, showlegend: false, hovertemplate: 'start/finish<extra></extra>' }
  ], layout({ showlegend: true, legend: { orientation: 'h', y: -0.02, font: { color: C.text2 } }, margin: { l: 10, r: 10, t: 10, b: 30 }, annotations: cs, xaxis: { visible: false, scaleanchor: 'y' }, yaxis: { visible: false } }));
}

/* Corner minimum and braking point from a trace (when the summary file lacks this lap). */
function cornerFromTrace(T, c) {
  let vmin = null, start = null;
  for (let i = 0; i < T.d.length; i++) {
    if (T.d[i] >= c.d - APEX_WINDOW_M && T.d[i] <= c.d + APEX_WINDOW_M && (vmin === null || T.speed[i] < vmin)) vmin = T.speed[i];
  }
  for (let i = T.d.length - 1; i > 0; i--) {
    if (T.d[i] > c.d) continue;
    if (T.d[i] < c.d - BRAKE_LOOKBACK_M) break;
    if (T.brake[i] > 0 && T.brake[i - 1] <= 0) { start = i; break; }
  }
  return { v: vmin, b: start !== null ? Math.round(c.d - T.d[start]) : null };
}

function drawCorners(A, B, delta) {
  const cs = cornerMarks();
  if (!cs.length) { document.getElementById('tl-corners').innerHTML = muted('No corners: the session has no reference lap.'); return; }
  const tel = S.tel || {};
  const sumOf = (T, i, c) => {
    const cm = ((tel.corner_min || {})[T.n] || {})[String(T.lap)], bp = ((tel.brake_points || {})[T.n] || {})[String(T.lap)];
    const own = cornerFromTrace(T, c);
    return { v: cm && isNum(cm[i]) ? cm[i] : own.v, b: bp && isNum(bp[i]) ? bp[i] : own.b };
  };
  const nA = dshort(A.n), nB = dshort(B.n);
  const deltaAt = x => { const k = Math.min(delta.length - 1, Math.max(0, Math.round(x / A.step))); return delta[k]; };
  const rows = cs.map((c, i) => {
    const a = sumOf(A, i, c), b = sumOf(B, i, c);
    const prev = i ? cs[i - 1].d + (c.d - cs[i - 1].d) / 2 : 0, next = i < cs.length - 1 ? c.d + (cs[i + 1].d - c.d) / 2 : A.d[A.d.length - 1];
    const gained = deltaAt(next) - deltaAt(prev);
    const better = (x, y, low) => (isNum(x) && isNum(y) && x !== y ? ((low ? x < y : x > y) ? 'a' : 'b') : '');
    const bv = better(a.v, b.v, false), bb = better(a.b, b.b, true);
    return ['T' + c.n, { v: c.d, html: num(c.d, 0) + ' m' }, { v: c.v, html: num(c.v, 0) },
      { v: a.v, html: (bv === 'a' ? '<strong>' : '') + num(a.v, 0) + (bv === 'a' ? '</strong>' : '') }, { v: b.v, html: (bv === 'b' ? '<strong>' : '') + num(b.v, 0) + (bv === 'b' ? '</strong>' : '') },
      { v: a.b, html: (bb === 'a' ? '<strong>' : '') + (isNum(a.b) ? a.b + ' m' : '—') + (bb === 'a' ? '</strong>' : '') }, { v: b.b, html: (bb === 'b' ? '<strong>' : '') + (isNum(b.b) ? b.b + ' m' : '—') + (bb === 'b' ? '</strong>' : '') },
      { v: gained, html: '<span style="color:' + (gained > 0 ? CA : CB) + '">' + PD.signed(gained, 3) + ' s</span>' }];
  });
  document.getElementById('tl-corners').innerHTML = tableHTML([{ label: 'Corner' }, { label: 'Apex at', align: 'right' }, { label: 'Ref min', align: 'right', title: 'Reference lap minimum speed, km/h' },
    { label: 'Min ' + nA, align: 'right' }, { label: 'Min ' + nB, align: 'right' }, { label: 'Brake ' + nA, align: 'right', title: 'Distance before the apex where braking began; shorter = later braking' }, { label: 'Brake ' + nB, align: 'right' },
    { label: 'Time ' + nA + ' gains', align: 'right', title: 'Change in the delta from halfway to the previous corner to halfway to the next; + = ' + nA + ' gained' }], rows, { compact: true });
  sortable('tl-corners');
}

function drawSummary() {
  const tel = S.tel || {};
  const out = [];
  [S.a, S.b].forEach((n, side) => {
    if (!n) return;
    const sumRows = ((tel.laps || {})[n]) || [];
    const byLap = {}; sumRows.forEach(r => { byLap[r[0]] = r; });
    lapRows(n).forEach(r => {
      const s = byLap[r[0]];
      const sel = (side === 0 ? S.lapA : S.lapB) === r[0];
      out.push({ _class: sel ? 'tl-sel' : '', _style: sel ? 'outline:1px solid ' + (side ? CB : CA) : '', cells: [{ v: side, html: '<span class="cmp-pill-' + (side ? 'b' : 'a') + '"></span>' + esc(dshort(n)) }, r[0],
        { v: r[2], html: PD.fmtMs(r[2]) + (r[9] ? ' <span class="pg-tag">out</span>' : '') }, { v: s ? s[1] : null, html: s ? num(s[1], 0) : '—' }, { v: s ? s[2] : null, html: s ? num(s[2], 1) : '—' },
        { v: s ? s[3] : null, html: s ? num(s[3], 1) + '%' : '—' }, { v: s ? s[4] : null, html: s ? num(s[4], 1) + '%' : '—' }, { v: s ? s[5] : null, html: s ? num(s[5], 1) + '%' : '—' },
        { v: s ? s[6] : null, html: s ? String(s[6]) : '—' }, { v: s ? s[7] : null, html: s ? num(s[7], 1) + 's' : '—' },
        { v: '', html: '<a href="javascript:void(0)" data-pick="' + side + '|' + r[0] + '">show</a>' }] });
    });
  });
  const host = document.getElementById('tl-laps');
  host.innerHTML = out.length ? tableHTML([{ label: 'Driver' }, { label: 'Lap', align: 'right' }, { label: 'Time', align: 'right' }, { label: 'Top km/h', align: 'right' }, { label: 'Mean km/h', align: 'right' },
    { label: 'Full throttle', align: 'right', title: 'Share of lap time at throttle ≥ 98' }, { label: 'Braking', align: 'right', title: 'Share of lap time with the brake on' }, { label: 'Coasting', align: 'right', title: 'Throttle < 2 and no brake' },
    { label: 'Gear changes', align: 'right' }, { label: 'DRS open', align: 'right' }, { label: '', sortable: false }], out, { compact: true, sticky: true }) : muted('No laps.');
  sortable(host);
  host.querySelectorAll('a[data-pick]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const p = a.dataset.pick.split('|');
    if (p[0] === '0') S.lapA = parseInt(p[1], 10); else S.lapB = parseInt(p[1], 10);
    syncControls(); compare();
    document.getElementById('tl-stack').scrollIntoView({ block: 'start' });
  }));
}

// ── controls and flow ──────────────────────────────────────────────────────

function lapOptions(n, cur) {
  const fl = fastestLap(n);
  const stored = (((S.tel || {}).fastest || {})[n] || {}).lap;
  return lapRows(n).map(r => '<option value="' + r[0] + '"' + (r[0] === cur ? ' selected' : '') + '>Lap ' + r[0] + ' · ' + PD.fmtMs(r[2]) + (r[0] === fl ? ' · fastest' : '') + (r[0] === stored ? ' (stored)' : '') + (r[9] ? ' · out lap' : '') + '</option>').join('');
}
function driverOptions(cur) {
  const ns = Object.keys((S.sess || {}).laps || {}).filter(n => lapRows(n).length);
  ns.sort((p, q) => { const a = lapRows(p), b = lapRows(q); return Math.min.apply(null, a.map(r => r[2])) - Math.min.apply(null, b.map(r => r[2])); });
  return ns.map(n => '<option value="' + n + '"' + (n === cur ? ' selected' : '') + '>' + esc(dshort(n) + ' · ' + dname(n) + ' #' + n) + (((S.tel || {}).fastest || {})[n] ? '' : ' (live only)') + '</option>').join('');
}
function syncControls() {
  const $ = id => document.getElementById(id);
  $('tl-a').innerHTML = driverOptions(S.a); $('tl-b').innerHTML = driverOptions(S.b);
  $('tl-lap-a').innerHTML = lapOptions(S.a, S.lapA); $('tl-lap-b').innerHTML = lapOptions(S.b, S.lapB);
}
function status(msg, err) { const e = document.getElementById('tl-status'); if (e) { e.innerHTML = msg || ''; e.className = 'tl-status' + (err ? ' err' : ''); } }

let TOKEN = 0;
function compare() {
  const tok = ++TOKEN;
  if (!S.a || !S.b || !isNum(S.lapA) || !isNum(S.lapB)) { status('Pick two drivers and a lap each.'); return; }
  const needLive = [[S.a, S.lapA], [S.b, S.lapB]].filter(p => (((S.tel || {}).fastest || {})[p[0]] || {}).lap !== p[1]);
  status(needLive.length ? 'Fetching ' + needLive.length + ' lap' + (needLive.length > 1 ? 's' : '') + ' from OpenF1…' : '');
  const h = '#/race/' + S.year + '/' + S.round + '/telemetry?s=' + S.kind + '&a=' + S.a + '&la=' + S.lapA + '&b=' + S.b + '&lb=' + S.lapB;
  if (location.hash !== h) history.replaceState(null, '', h);
  drawSummary();
  Promise.all([getTrace(S.a, S.lapA), getTrace(S.b, S.lapB)]).then(tr => {
    if (tok !== TOKEN || !document.getElementById('tl-stack')) return;
    const A = tr[0], B = tr[1];
    if (!A || !B) { status('No data for one of the laps.', true); return; }
    const live = tr.filter(t => t.source === 'live');
    status((live.length ? live.map(t => dshort(t.n) + ' lap ' + t.lap + ': ' + t.raw + ' live samples from OpenF1, distance integrated from speed and rescaled to the ' + (((S.tel || {}).ref || {}).length_m || '—') + ' m reference lap. ').join('') : 'Both laps from the stored traces (every 10 m). ') +
      'Lap times ' + esc(dshort(A.n)) + ' ' + PD.fmtMs(A.ms) + ', ' + esc(dshort(B.n)) + ' ' + PD.fmtMs(B.ms) + ' (' + PD.fmtGap(A.ms - B.ms) + ').');
    const delta = drawStack(A, B);
    drawCorners(A, B, delta);
    drawSummary();
    geometry([A, B]).then(geo => { if (tok === TOKEN && document.getElementById('tl-map')) drawMap(A, B, geo); });
    const kp = document.getElementById('tl-kpis');
    if (kp) {
      const top = T => Math.max.apply(null, T.speed), mn = T => T.speed.reduce((s, v) => s + v, 0) / T.speed.length;
      const share = (T, f) => 100 * T.speed.filter((v, i) => f(T, i)).length / T.speed.length;
      kp.innerHTML = '<div class="kpi-grid six" style="padding:12px 12px 0">' + [
        PD.statTile('Gap', PD.fmtGap(A.ms - B.ms), esc(dshort(A.n)) + ' minus ' + esc(dshort(B.n))),
        PD.statTile('Top speed', num(top(A), 0) + ' / ' + num(top(B), 0), 'km/h, ' + esc(dshort(A.n)) + ' / ' + esc(dshort(B.n))),
        PD.statTile('Mean speed', num(mn(A), 1) + ' / ' + num(mn(B), 1), 'km/h over distance'),
        PD.statTile('Full throttle', num(share(A, (T, i) => T.throttle[i] >= 98), 0) + '% / ' + num(share(B, (T, i) => T.throttle[i] >= 98), 0) + '%', 'share of distance'),
        PD.statTile('Braking', num(share(A, (T, i) => T.brake[i] > 0), 0) + '% / ' + num(share(B, (T, i) => T.brake[i] > 0), 0) + '%', 'share of distance'),
        PD.statTile('DRS open', num(share(A, (T, i) => DRS_OPEN.indexOf(T.drs[i]) >= 0), 0) + '% / ' + num(share(B, (T, i) => DRS_OPEN.indexOf(T.drs[i]) >= 0), 0) + '%', 'codes 10, 12, 14')
      ].join('') + '</div>';
    }
  }, err => { if (tok === TOKEN) status('Could not load the lap: ' + esc(err && err.message ? err.message : err) + '. The stored fastest laps still work.', true); });
}

function loadSession(kind, query) {
  S.kind = kind;
  S.key = S.race.sessions[kind];
  status('Loading the session…');
  ['tl-stack', 'tl-map', 'tl-corners', 'tl-laps'].forEach(id => { const e = document.getElementById(id); if (e) e.innerHTML = ''; });
  return PD.loadAll([S.year + '/sessions/' + S.key + '.json', S.year + '/telemetry/' + S.key + '.json']).then(res => {
    if (!document.getElementById('tl-stack')) return;
    S.sess = res[0]; S.tel = res[1];
    if (!S.sess || !S.sess.laps) { status('The session record for ' + esc(KIND_LABEL[kind] || kind) + ' (key ' + esc(S.key) + ') is not on the site yet.', true); return; }
    S.map = numberMap(S.sess, S.race);
    // Default drivers: the top two of the session's classification, else the two fastest laps.
    const byId = {}; Object.keys(S.map).forEach(n => { if (S.map[n]) byId[S.map[n]] = n; });
    const order = (kind === 'quali' || kind === 'sprint_quali' ? (S.race.qualifying || []) : kind === 'sprint' ? (S.race.sprint || []) : (S.race.results || [])).slice().sort((p, q) => (p.pos || 99) - (q.pos || 99)).map(r => byId[r.driver]).filter(n => n && lapRows(n).length);
    const fastestOrder = Object.keys(S.sess.laps).filter(n => lapRows(n).length).sort((p, q) => Math.min.apply(null, lapRows(p).map(r => r[2])) - Math.min.apply(null, lapRows(q).map(r => r[2])));
    const pickN = want => (want && lapRows(String(want)).length ? String(want) : null);
    const q = query || {};
    S.a = pickN(q.a) || order[0] || fastestOrder[0] || null;
    S.b = pickN(q.b) || order.concat(fastestOrder).filter(n => n !== S.a)[0] || null;
    S.lapA = q.la && lapRows(S.a).some(r => r[0] === parseInt(q.la, 10)) ? parseInt(q.la, 10) : fastestLap(S.a);
    S.lapB = q.lb && lapRows(S.b).some(r => r[0] === parseInt(q.lb, 10)) ? parseInt(q.lb, 10) : fastestLap(S.b);
    const nT = Object.keys((S.tel || {}).fastest || {}).length;
    document.getElementById('tl-sub').innerHTML = esc(KIND_LABEL[kind] || kind) + ' · session ' + esc(S.key) + ' · ' + Object.keys(S.sess.laps).length + ' cars · ' +
      (nT ? nT + ' stored fastest-lap trace' + (nT === 1 ? '' : 's') + ', reference lap ' + esc(dshort(String(S.tel.ref.driver))) + ' lap ' + S.tel.ref.lap + ' (' + S.tel.ref.length_m + ' m, ' + (S.tel.ref.corners || []).length + ' corners)' : 'no stored telemetry: every lap is fetched live from OpenF1');
    syncControls();
    compare();
  });
}

function renderTelemetry(el, params) {
  const y = params.year, r = params.round;
  S = { year: y, round: r };
  el.innerHTML = muted('Loading…');
  return PD.load(y + '/races/' + r + '.json').then(race => {
    if (!PG().alive(el)) return null;
    if (!race || !race.sessions) {
      el.innerHTML = card('Telemetry lab', '', PG().notBuilt('The race file for ' + y + ' round ' + r, race));
      return null;
    }
    S.race = race;
    const kinds = ['race', 'quali', 'sprint', 'sprint_quali', 'fp1', 'fp2', 'fp3'].filter(k => race.sessions[k]);
    if (!kinds.length) { el.innerHTML = card('Telemetry lab', '', muted('No OpenF1 sessions for this race (OpenF1 starts in 2023).')); return null; }
    const q = params.query || {};
    const tf = race.telemetry || {};
    const kind = q.s && kinds.indexOf(q.s) >= 0 ? q.s : (kinds.find(k => tf[k]) || (kinds.indexOf('quali') >= 0 ? 'quali' : kinds[0]));
    el.innerHTML = '<div class="pg-head" style="--team:' + C.purple + '"><div class="pg-body"><h2>' + esc(y + ' ' + (race.name || 'Round ' + r)) + ': telemetry</h2><div class="pg-sub">' + PD.circuitLink((race.circuit || {}).id, (race.circuit || {}).name) +
      '<span class="chip">Round ' + r + '</span>' + PD.raceLink(y, r, 'Race centre →') + '</div></div></div>' +
      '<div class="card"><div class="card-header">Telemetry lab <span class="card-sub" id="tl-sub"></span></div><div class="tl-controls">' +
      '<label>Session<select id="tl-kind">' + kinds.map(k => '<option value="' + k + '"' + (k === kind ? ' selected' : '') + '>' + esc(KIND_LABEL[k] || k) + (tf[k] ? '' : ' (live)') + '</option>').join('') + '</select></label>' +
      '<label class="tl-side-a">Driver A<select id="tl-a"></select></label><label>Lap<select id="tl-lap-a"></select></label>' +
      '<label class="tl-side-b">Driver B<select id="tl-b"></select></label><label>Lap<select id="tl-lap-b"></select></label>' +
      '<label>&nbsp;<button type="button" id="tl-swap">⇄ swap</button></label></div><div class="tl-status" id="tl-status"></div><div id="tl-kpis"></div>' +
      '<div id="tl-stack" style="height:980px"></div><div class="pg-note">Delta: cumulative time gap at each point of the lap, positive when driver A (blue) is ahead. Brake is on/off as OpenF1 reports it. Dotted lines mark the corners found on the reference lap (speed minima with at least 25 km/h of prominence, at least 150 m apart).</div></div>' +
      '<div class="grid-2"><div class="card"><div class="card-header">Who is faster where <span class="card-sub">The lap in 50 m segments, coloured by the driver who covered each segment quicker.</span></div><div id="tl-map" style="height:480px"></div></div>' +
      '<div class="card"><div class="card-header">Corners <span class="card-sub">Minimum speed within ±80 m of each apex and the braking point (the start of the braking zone, within 400 m before the apex).</span></div><div id="tl-corners"></div></div></div>' +
      '<div class="card"><div class="card-header">Every lap <span class="card-sub">Per-lap summaries for both drivers from the telemetry file (laps shorter than 80% or longer than 125% of the reference are left out). "show" loads that lap above.</span></div><div id="tl-laps" style="max-height:520px;overflow-y:auto"></div></div>';
    const $ = id => document.getElementById(id);
    $('tl-kind').onchange = e => { loadSession(e.target.value, {}); };
    $('tl-a').onchange = e => { S.a = e.target.value; S.lapA = fastestLap(S.a); syncControls(); compare(); };
    $('tl-b').onchange = e => { S.b = e.target.value; S.lapB = fastestLap(S.b); syncControls(); compare(); };
    $('tl-lap-a').onchange = e => { S.lapA = parseInt(e.target.value, 10); compare(); };
    $('tl-lap-b').onchange = e => { S.lapB = parseInt(e.target.value, 10); compare(); };
    $('tl-swap').onclick = () => { const t = S.a, l = S.lapA; S.a = S.b; S.lapA = S.lapB; S.b = t; S.lapB = l; syncControls(); compare(); };
    return loadSession(kind, q);
  });
}

PD.route('telemetry', renderTelemetry);
})(window.PD);
