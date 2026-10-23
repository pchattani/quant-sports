/* The Quant Paddock — the telemetry lab, the race centre's Telemetry tab (#/race/<y>/<r>/telemetry).
 *
 * Two drivers, one lap each, on a shared distance axis: the cumulative time delta, speed, throttle,
 * brake, gear, RPM and DRS; a track map coloured by who is faster in each 50 m segment; a corners
 * table (minimum speed and braking point at each corner of the session's reference lap); per-lap
 * summaries. Fastest laps come from data/<y>/telemetry/<key>.json (every 10 m); any other lap is
 * fetched live from OpenF1 car_data for the lap's time window, distance integrated from speed and
 * rescaled to the reference lap length, as oddsmarkets/f1/telemetry.py does. Shareable state:
 * ?s=<session>&a=<car>&la=<lap>&b=<car>&lb=<lap>. */
(function (PD) {
'use strict';

var esc = PD.esc, isNum = PD.isNum;
var STEP = 10, SEG = 50, APEX_WINDOW_M = 80, BRAKE_LOOKBACK_M = 400, DRS_OPEN = [10, 12, 14];
var OPENF1 = 'https://api.openf1.org/v1/';
var LIVE = {};
var KIND_LABEL = { race: 'Race', quali: 'Qualifying', sprint: 'Sprint', sprint_quali: 'Sprint qualifying', fp1: 'Practice 1', fp2: 'Practice 2', fp3: 'Practice 3' };
var S = null;

function numberMap(sess, race) {
  var out = {}, idx = PD.index() || {}, byCode = {}, byNum = {}, resNum = {};
  var names = PD.NAMES.drivers || {};
  Object.keys(names).forEach(function (id) { var x = names[id]; if (x.code) byCode[String(x.code).toUpperCase()] = id; if (isNum(x.number)) byNum[String(x.number)] = id; });
  Object.keys(idx.drivers || {}).forEach(function (id) { var x = idx.drivers[id]; if (x.code) byCode[String(x.code).toUpperCase()] = id; if (isNum(x.number)) byNum[String(x.number)] = id; });
  ((race || {}).results || []).concat((race || {}).qualifying || []).forEach(function (r) { if (isNum(r.number) && r.driver) resNum[String(r.number)] = r.driver; });
  var D = (sess || {}).drivers || {};
  Object.keys(D).forEach(function (n) { var ac = String(D[n].name_acronym || '').toUpperCase(); out[n] = resNum[n] || byCode[ac] || byNum[n] || null; });
  return out;
}
function dname(n) { var id = S.map[n], D = ((S.sess || {}).drivers || {})[n] || {}; return id ? PD.driverName(id) : (D.full_name ? PD.titleCase(String(D.full_name).toLowerCase()) : '#' + n); }
function dshort(n) { var D = ((S.sess || {}).drivers || {})[n] || {}; return D.name_acronym || (S.map[n] ? PD.driverCode(S.map[n]) : '#' + n); }
function lapRows(n) { return (((S.sess || {}).laps || {})[n] || []).filter(function (r) { return isNum(r[2]) && r[2] > 0 && isNum(r[1]); }); }
function fastestLap(n) {
  var f = ((S.tel || {}).fastest || {})[n];
  if (f && isNum(f.lap)) return f.lap;
  var rows = lapRows(n);
  return rows.length ? rows.slice().sort(function (a, b) { return a[2] - b[2]; })[0][0] : null;
}
function timeFromSpeed(speed, step, lapMs) {
  var t = [0];
  for (var i = 1; i < speed.length; i++) { var v = Math.max(5, (speed[i] + speed[i - 1]) / 2) / 3.6; t.push(t[i - 1] + step / v); }
  var total = t[t.length - 1] + step / Math.max(5, speed[speed.length - 1] / 3.6);
  var k = lapMs && total > 0 ? lapMs / 1000 / total : 1;
  return t.map(function (v) { return v * k; });
}
function storedTrace(n) {
  var f = ((S.tel || {}).fastest || {})[n];
  if (!f) return null;
  var step = f.d || STEP;
  return { n: n, lap: f.lap, ms: f.ms, step: step, d: f.speed.map(function (v, i) { return i * step; }), speed: f.speed, throttle: f.throttle, brake: f.brake, gear: f.gear, rpm: f.rpm, drs: f.drs,
    t: timeFromSpeed(f.speed, step, f.ms), x: f.x || null, y: f.y || null, source: 'stored' };
}
function interp(xs, ys, x) {
  var lo = 0, hi = xs.length - 1;
  if (x <= xs[0]) return ys[0];
  if (x >= xs[hi]) return ys[hi];
  while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  var u = (x - xs[lo]) / ((xs[hi] - xs[lo]) || 1);
  return ys[lo] + u * (ys[hi] - ys[lo]);
}
function iso(d) { return d.toISOString().replace('Z', ''); }
function fetchLap(n, lap) {
  var key = S.key + '|' + n + '|' + lap;
  if (LIVE[key]) return LIVE[key];
  var row = lapRows(n).filter(function (r) { return r[0] === lap; })[0];
  if (!row) return Promise.resolve(null);
  var t0 = Date.parse(((S.sess || {}).session || {}).date_start);
  if (isNaN(t0)) return Promise.reject(new Error('the session record has no start time'));
  var a = new Date(t0 + row[1]), b = new Date(t0 + row[1] + row[2]);
  var url = OPENF1 + 'car_data?session_key=' + S.key + '&driver_number=' + n + '&date>=' + encodeURIComponent(iso(a)) + '&date<=' + encodeURIComponent(iso(b));
  var get = function (attempt) {
    return fetch(url).then(function (r) {
      if (r.status === 429 && attempt === 0) { status('OpenF1 rate limit reached (30 requests a minute); retrying in 30 s…', true); return new Promise(function (res) { setTimeout(res, 30000); }).then(function () { return get(1); }); }
      if (r.status === 429) throw new Error('OpenF1 rate limit (30 requests a minute); try again in a minute');
      if (!r.ok) throw new Error('OpenF1 answered HTTP ' + r.status);
      return r.json();
    });
  };
  LIVE[key] = get(0).then(function (rows) {
    if (!Array.isArray(rows) || rows.length < 20) throw new Error('OpenF1 returned ' + (Array.isArray(rows) ? rows.length : 0) + ' car-data samples for this lap');
    rows.sort(function (p, q) { return Date.parse(p.date) - Date.parse(q.date); });
    var ts = rows.map(function (r) { return (Date.parse(r.date) - a.getTime()) / 1000; });
    var sp = rows.map(function (r) { return isNum(r.speed) ? r.speed : 0; });
    var d = [0];
    for (var i = 1; i < rows.length; i++) d.push(d[i - 1] + (sp[i] / 3.6) * (ts[i] - ts[i - 1]));
    var len = ((S.tel || {}).ref || {}).length_m || d[d.length - 1];
    var scale = d[d.length - 1] > 0 ? len / d[d.length - 1] : 1;
    var ds = d.map(function (v) { return v * scale; });
    var grid = []; for (var x = 0; x < len; x += STEP) grid.push(x);
    var ch = function (k) { return rows.map(function (r) { return isNum(r[k]) ? r[k] : 0; }); };
    var lin = function (arr) { return grid.map(function (g) { return Math.round(interp(ds, arr, g)); }); };
    var near = function (arr) { return grid.map(function (g) { var lo = 0; while (lo < ds.length - 1 && ds[lo + 1] <= g) lo++; return arr[lo]; }); };
    return { n: n, lap: lap, ms: row[2], step: STEP, d: grid, speed: lin(sp), throttle: lin(ch('throttle')), brake: near(ch('brake')), gear: near(ch('n_gear')), rpm: lin(ch('rpm')), drs: near(ch('drs')),
      t: grid.map(function (g) { return interp(ds, ts, g); }), x: null, y: null, source: 'live', raw: rows.length };
  });
  LIVE[key].catch(function () { delete LIVE[key]; });
  return LIVE[key];
}
function getTrace(n, lap) { var f = ((S.tel || {}).fastest || {})[n]; return f && f.lap === lap ? Promise.resolve(storedTrace(n)) : fetchLap(n, lap); }
function geometry(tr) {
  var F = (S.tel || {}).fastest || {};
  var pref = [tr[0] && tr[0].n, tr[1] && tr[1].n, ((S.tel || {}).ref || {}).driver].concat(Object.keys(F));
  for (var i = 0; i < pref.length; i++) { var f = F[pref[i]]; if (f && (f.x || []).length > 10) return Promise.resolve({ x: f.x, y: f.y, step: f.d || STEP }); }
  var A = tr[0];
  if (!A) return Promise.resolve(null);
  var row = lapRows(A.n).filter(function (r) { return r[0] === A.lap; })[0];
  var t0 = Date.parse(((S.sess || {}).session || {}).date_start);
  if (!row || isNaN(t0)) return Promise.resolve(null);
  var a = new Date(t0 + row[1]), b = new Date(t0 + row[1] + row[2]);
  return fetch(OPENF1 + 'location?session_key=' + S.key + '&driver_number=' + A.n + '&date>=' + encodeURIComponent(iso(a)) + '&date<=' + encodeURIComponent(iso(b)))
    .then(function (r) { return r.ok ? r.json() : null; }).then(function (rows) {
      if (!Array.isArray(rows) || rows.length < 20) return null;
      rows.sort(function (p, q) { return Date.parse(p.date) - Date.parse(q.date); });
      var lt = rows.map(function (r) { return (Date.parse(r.date) - a.getTime()) / 1000; });
      var pickK = function (tq) { var k = 0; while (k < lt.length - 1 && lt[k] < tq) k++; return k; };
      return { x: A.t.map(function (tq) { return rows[pickK(tq)].x; }), y: A.t.map(function (tq) { return rows[pickK(tq)].y; }), step: A.step };
    }).catch(function () { return null; });
}
function corners() { return ((S.tel || {}).ref || {}).corners || []; }
function cornerFromTrace(T, c) {
  var vmin = null, start = null;
  for (var i = 0; i < T.d.length; i++) if (T.d[i] >= c.d - APEX_WINDOW_M && T.d[i] <= c.d + APEX_WINDOW_M && (vmin === null || T.speed[i] < vmin)) vmin = T.speed[i];
  for (var j = T.d.length - 1; j > 0; j--) { if (T.d[j] > c.d) continue; if (T.d[j] < c.d - BRAKE_LOOKBACK_M) break; if (T.brake[j] > 0 && T.brake[j - 1] <= 0) { start = j; break; } }
  return { v: vmin, b: start !== null ? Math.round(c.d - T.d[start]) : null };
}
function status(msg, err) { var e = document.getElementById('tl-status'); if (e) { e.innerHTML = msg || ''; e.className = 'pd-cap' + (err ? ' pd-err' : ''); } }

function drawCorners(A, B, delta) {
  var cs = corners();
  if (!cs.length) { PD.set('tl-corners', PD.muted('No corners: the session has no reference lap.')); return; }
  var tel = S.tel || {};
  var sumOf = function (T, i, c) {
    var cm = ((tel.corner_min || {})[T.n] || {})[String(T.lap)], bp = ((tel.brake_points || {})[T.n] || {})[String(T.lap)];
    var own = cornerFromTrace(T, c);
    return { v: cm && isNum(cm[i]) ? cm[i] : own.v, b: bp && isNum(bp[i]) ? bp[i] : own.b };
  };
  var nA = dshort(A.n), nB = dshort(B.n);
  var deltaAt = function (x) { var k = Math.min(delta.length - 1, Math.max(0, Math.round(x / A.step))); return delta[k]; };
  PD.table('tl-corners', [
    { key: 'n', label: 'Corner', num: true, fmt: function (v) { return 'T' + v; } },
    { key: 'd', label: 'Apex', num: true, fmt: function (v) { return PD.num(v, 0) + ' m'; } },
    { key: 'va', label: 'Min ' + nA, num: true, fmt: function (v, r) { return (r.bv === 'a' ? '<b>' : '') + PD.num(v, 0) + (r.bv === 'a' ? '</b>' : ''); } },
    { key: 'vb', label: 'Min ' + nB, num: true, fmt: function (v, r) { return (r.bv === 'b' ? '<b>' : '') + PD.num(v, 0) + (r.bv === 'b' ? '</b>' : ''); } },
    { key: 'ba', label: 'Brake ' + nA, num: true, tip: 'Distance before the apex where braking began; shorter = later braking', fmt: function (v, r) { return isNum(v) ? (r.bb === 'a' ? '<b>' : '') + v + ' m' + (r.bb === 'a' ? '</b>' : '') : '—'; } },
    { key: 'bb2', label: 'Brake ' + nB, num: true, fmt: function (v, r) { return isNum(v) ? (r.bb === 'b' ? '<b>' : '') + v + ' m' + (r.bb === 'b' ? '</b>' : '') : '—'; } },
    { key: 'gain', label: nA + ' gains', num: true, tip: 'Change in the delta across the corner; + = ' + nA + ' gained', fmt: function (v) { return '<span style="color:' + (v > 0 ? 'var(--sky)' : 'var(--coral)') + '">' + PD.signed(v, 3) + ' s</span>'; } }
  ], cs.map(function (c, i) {
    var a = sumOf(A, i, c), b = sumOf(B, i, c);
    var prev = i ? cs[i - 1].d + (c.d - cs[i - 1].d) / 2 : 0, next = i < cs.length - 1 ? c.d + (cs[i + 1].d - c.d) / 2 : A.d[A.d.length - 1];
    var better = function (x, y, low) { return isNum(x) && isNum(y) && x !== y ? ((low ? x < y : x > y) ? 'a' : 'b') : ''; };
    return { n: c.n, d: c.d, va: a.v, vb: b.v, ba: a.b, bb2: b.b, gain: deltaAt(next) - deltaAt(prev), bv: better(a.v, b.v, false), bb: better(a.b, b.b, true) };
  }), { sort: { key: 'n', dir: 'asc' }, maxHeight: 460 });
}

function drawSummary() {
  var tel = S.tel || {}, out = [];
  [S.a, S.b].forEach(function (n, side) {
    if (!n) return;
    var byLap = {};
    (((tel.laps || {})[n]) || []).forEach(function (r) { byLap[r[0]] = r; });
    lapRows(n).forEach(function (r) {
      var s = byLap[r[0]];
      out.push({ side: side, n: n, who: dshort(n), lap: r[0], ms: r[2], out: r[9], top: s ? s[1] : null, mean: s ? s[2] : null, ft: s ? s[3] : null, brk: s ? s[4] : null, coast: s ? s[5] : null, gears: s ? s[6] : null, drs: s ? s[7] : null,
        sel: (side === 0 ? S.lapA : S.lapB) === r[0] });
    });
  });
  if (!out.length) { PD.set('tl-laps', PD.muted('No laps.')); return; }
  PD.table('tl-laps', [
    { key: 'who', label: 'Driver', sticky: true, fmt: function (v, r) { return '<i class="pd-dot" style="--tc:' + (r.side ? 'var(--coral)' : 'var(--sky)') + '"></i>' + esc(v) + (r.sel ? ' <span class="qk-badge accent">shown</span>' : ''); } },
    { key: 'lap', label: 'Lap', num: true },
    { key: 'ms', label: 'Time', num: true, fmt: function (v, r) { return PD.fmtMs(v) + (r.out ? ' <span class="qk-badge">out</span>' : ''); } },
    { key: 'top', label: 'Top km/h', num: true, fmt: function (v) { return PD.num(v, 0); } },
    { key: 'mean', label: 'Mean km/h', num: true, fmt: function (v) { return PD.num(v, 1); } },
    { key: 'ft', label: 'Full throttle', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) + '%' : '—'; } },
    { key: 'brk', label: 'Braking', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) + '%' : '—'; } },
    { key: 'coast', label: 'Coasting', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) + '%' : '—'; } },
    { key: 'gears', label: 'Gear changes', num: true },
    { key: 'drs', label: 'DRS open', num: true, fmt: function (v) { return isNum(v) ? PD.num(v, 1) + 's' : '—'; } },
    { key: 'pick', label: '', sort: false, fmt: function (v, r) { return '<button type="button" class="qk-btn pd-btn-xs" data-pick="' + r.side + '|' + r.lap + '">Show</button>'; } }
  ], out, { sort: { key: 'ms', dir: 'asc' }, maxHeight: 520 });
  var host = document.getElementById('tl-laps');
  if (host && !host.__wired) {
    host.__wired = true;
    host.addEventListener('click', function (ev) {
      var b = ev.target.closest ? ev.target.closest('[data-pick]') : null;
      if (!b) return;
      var p = b.getAttribute('data-pick').split('|');
      if (p[0] === '0') S.lapA = parseInt(p[1], 10); else S.lapB = parseInt(p[1], 10);
      sync(); compare();
      var st = document.getElementById('tl-stack'); if (st) st.scrollIntoView({ block: 'start' });
    });
  }
}

function lapOptions(n, cur) {
  var fl = fastestLap(n), stored = (((S.tel || {}).fastest || {})[n] || {}).lap;
  return lapRows(n).map(function (r) { return '<option value="' + r[0] + '"' + (r[0] === cur ? ' selected' : '') + '>Lap ' + r[0] + ' · ' + PD.fmtMs(r[2]) + (r[0] === fl ? ' · fastest' : '') + (r[0] === stored ? ' (stored)' : '') + (r[9] ? ' · out lap' : '') + '</option>'; }).join('');
}
function driverOptions(cur) {
  var ns = Object.keys((S.sess || {}).laps || {}).filter(function (n) { return lapRows(n).length; });
  var best = function (n) { return Math.min.apply(null, lapRows(n).map(function (r) { return r[2]; })); };
  ns.sort(function (p, q) { return best(p) - best(q); });
  return ns.map(function (n) { return '<option value="' + n + '"' + (n === cur ? ' selected' : '') + '>' + esc(dshort(n) + ' · ' + dname(n) + ' #' + n) + (((S.tel || {}).fastest || {})[n] ? '' : ' (live)') + '</option>'; }).join('');
}
function sync() {
  PD.set('tl-a', driverOptions(S.a)); PD.set('tl-b', driverOptions(S.b));
  PD.set('tl-lap-a', lapOptions(S.a, S.lapA)); PD.set('tl-lap-b', lapOptions(S.b, S.lapB));
}

var TOKEN = 0;
function compare() {
  var tok = ++TOKEN;
  if (!S.a || !S.b || !isNum(S.lapA) || !isNum(S.lapB)) { status('Pick two drivers and a lap each.'); return; }
  var needLive = [[S.a, S.lapA], [S.b, S.lapB]].filter(function (p) { return (((S.tel || {}).fastest || {})[p[0]] || {}).lap !== p[1]; });
  status(needLive.length ? 'Fetching ' + needLive.length + ' lap' + (needLive.length > 1 ? 's' : '') + ' from OpenF1…' : '');
  PD.setHashQuiet(PD.raceHref(S.year, S.round, 'telemetry') + PD.qs({ s: S.kind, a: S.a, la: S.lapA, b: S.b, lb: S.lapB }));
  drawSummary();
  Promise.all([getTrace(S.a, S.lapA), getTrace(S.b, S.lapB)]).then(function (tr) {
    if (tok !== TOKEN || !document.getElementById('tl-stack')) return;
    var A = tr[0], B = tr[1];
    if (!A || !B) { status('No data for one of the laps.', true); return; }
    var live = tr.filter(function (t) { return t.source === 'live'; });
    status((live.length ? live.map(function (t) { return dshort(t.n) + ' lap ' + t.lap + ': ' + t.raw + ' live samples from OpenF1, distance integrated from speed and rescaled to the ' + (((S.tel || {}).ref || {}).length_m || '—') + ' m reference lap. '; }).join('') : 'Both laps from the stored traces (every 10 m). ') +
      'Lap times ' + esc(dshort(A.n)) + ' ' + PD.fmtMs(A.ms) + ', ' + esc(dshort(B.n)) + ' ' + PD.fmtMs(B.ms) + ' (' + PD.fmtGap(A.ms - B.ms) + ').');
    var len = Math.min(A.d.length, B.d.length);
    var delta = A.d.slice(0, len).map(function (x, i) { return B.t[i] - A.t[i]; });
    var names = [dshort(A.n) + ' L' + A.lap, dshort(B.n) + ' L' + B.lap];
    PD.ch.telemetry('tl-stack', A, B, delta, names, corners());
    drawCorners(A, B, delta);
    drawSummary();
    geometry([A, B]).then(function (geo) {
      if (tok !== TOKEN || !document.getElementById('tl-map')) return;
      if (!geo) { PD.ch.segMap('tl-map', null, [], names); return; }
      var L2 = Math.min(A.t.length, B.t.length, geo.x.length), per = Math.max(1, Math.round(SEG / A.step)), segs = [];
      for (var s = 0; s * per < L2 - 1; s++) { var i0 = s * per, i1 = Math.min(L2 - 1, (s + 1) * per); segs.push({ from: i0, to: i1, a: (A.t[i1] - A.t[i0]) <= (B.t[i1] - B.t[i0]) }); }
      PD.ch.segMap('tl-map', { x: geo.x.slice(0, L2), y: geo.y.slice(0, L2) }, segs, [dshort(A.n), dshort(B.n)], { corners: corners(), step: A.step });
    });
    var top = function (T) { return Math.max.apply(null, T.speed); }, mn = function (T) { return T.speed.reduce(function (s, v) { return s + v; }, 0) / T.speed.length; };
    var share = function (T, f) { return 100 * T.speed.filter(function (v, i) { return f(T, i); }).length / T.speed.length; };
    PD.set('tl-kpis', PD.kpis([
      PD.kpi('Gap', PD.fmtGap(A.ms - B.ms), esc(dshort(A.n)) + ' minus ' + esc(dshort(B.n))),
      PD.kpi('Top speed', PD.num(top(A), 0) + ' / ' + PD.num(top(B), 0), 'km/h'),
      PD.kpi('Mean speed', PD.num(mn(A), 1) + ' / ' + PD.num(mn(B), 1), 'km/h over distance'),
      PD.kpi('Full throttle', PD.num(share(A, function (T, i) { return T.throttle[i] >= 98; }), 0) + ' / ' + PD.num(share(B, function (T, i) { return T.throttle[i] >= 98; }), 0) + '%', 'share of distance'),
      PD.kpi('Braking', PD.num(share(A, function (T, i) { return T.brake[i] > 0; }), 0) + ' / ' + PD.num(share(B, function (T, i) { return T.brake[i] > 0; }), 0) + '%', 'share of distance'),
      PD.kpi('DRS open', PD.num(share(A, function (T, i) { return DRS_OPEN.indexOf(T.drs[i]) >= 0; }), 0) + ' / ' + PD.num(share(B, function (T, i) { return DRS_OPEN.indexOf(T.drs[i]) >= 0; }), 0) + '%', 'codes 10, 12, 14')
    ]));
  }, function (err) { if (tok === TOKEN) status('Could not load the lap: ' + esc(err && err.message ? err.message : err) + '. The stored fastest laps still work.', true); });
}

function loadSession(kind, query) {
  S.kind = kind;
  S.key = S.race.sessions[kind];
  status('Loading the session…');
  ['tl-map', 'tl-corners', 'tl-laps', 'tl-kpis'].forEach(function (id) { PD.set(id, ''); });
  return PD.loadAll([S.year + '/sessions/' + S.key + '.json', S.year + '/telemetry/' + S.key + '.json']).then(function (res) {
    if (!document.getElementById('tl-stack')) return;
    S.sess = res[0]; S.tel = res[1];
    if (!S.sess || !S.sess.laps) { status('The session record for ' + esc(KIND_LABEL[kind] || kind) + ' (key ' + esc(S.key) + ') is not on the site yet.', true); PD.ch.none('tl-stack', 'No session record.'); return; }
    S.map = numberMap(S.sess, S.race);
    var byId = {};
    Object.keys(S.map).forEach(function (n) { if (S.map[n]) byId[S.map[n]] = n; });
    var src = kind === 'quali' || kind === 'sprint_quali' ? (S.race.qualifying || []) : kind === 'sprint' ? (S.race.sprint || []) : (S.race.results || []);
    var order = src.slice().sort(function (p, q) { return (p.pos || 99) - (q.pos || 99); }).map(function (r) { return byId[r.driver]; }).filter(function (n) { return n && lapRows(n).length; });
    var best = function (n) { return Math.min.apply(null, lapRows(n).map(function (r) { return r[2]; })); };
    var fastestOrder = Object.keys(S.sess.laps).filter(function (n) { return lapRows(n).length; }).sort(function (p, q) { return best(p) - best(q); });
    var pickN = function (want) { return want && lapRows(String(want)).length ? String(want) : null; };
    var q = query || {};
    S.a = pickN(q.a) || order[0] || fastestOrder[0] || null;
    S.b = pickN(q.b) || order.concat(fastestOrder).filter(function (n) { return n !== S.a; })[0] || null;
    S.lapA = q.la && lapRows(S.a).some(function (r) { return r[0] === parseInt(q.la, 10); }) ? parseInt(q.la, 10) : fastestLap(S.a);
    S.lapB = q.lb && lapRows(S.b).some(function (r) { return r[0] === parseInt(q.lb, 10); }) ? parseInt(q.lb, 10) : fastestLap(S.b);
    var nT = Object.keys((S.tel || {}).fastest || {}).length;
    PD.set('tl-sub', esc(KIND_LABEL[kind] || kind) + ' · session ' + esc(S.key) + ' · ' + Object.keys(S.sess.laps).length + ' cars · ' +
      (nT ? nT + ' stored fastest-lap trace' + (nT === 1 ? '' : 's') + ', reference lap ' + esc(dshort(String(S.tel.ref.driver))) + ' lap ' + S.tel.ref.lap + ' (' + S.tel.ref.length_m + ' m, ' + (S.tel.ref.corners || []).length + ' corners)' : 'no stored telemetry: every lap is fetched live from OpenF1'));
    sync();
    compare();
  });
}

PD.telemetryLab = function (host, race, query) {
  S = { year: race.year, round: race.round, race: race };
  var kinds = ['race', 'quali', 'sprint', 'sprint_quali', 'fp1', 'fp2', 'fp3'].filter(function (k) { return (race.sessions || {})[k]; });
  if (!kinds.length) { host.innerHTML = PD.empty('No telemetry sessions', race.year < 2023 ? 'OpenF1 car data starts in 2023.' : 'OpenF1 has no sessions for this weekend yet.'); return null; }
  var tf = race.telemetry || {};
  var kind = query.s && kinds.indexOf(query.s) >= 0 ? query.s : (kinds.filter(function (k) { return tf[k]; })[0] || (kinds.indexOf('quali') >= 0 ? 'quali' : kinds[0]));
  host.innerHTML = PD.card('Telemetry lab', '<span id="tl-sub"></span>',
    '<div class="pd-toolbar pd-tl-ctl">' +
      '<label>Session<select class="qk-select" id="tl-kind">' + kinds.map(function (k) { return '<option value="' + k + '"' + (k === kind ? ' selected' : '') + '>' + esc(KIND_LABEL[k] || k) + (tf[k] ? '' : ' (live)') + '</option>'; }).join('') + '</select></label>' +
      '<label class="pd-side-a">Driver A<select class="qk-select" id="tl-a"></select></label><label>Lap<select class="qk-select" id="tl-lap-a"></select></label>' +
      '<label class="pd-side-b">Driver B<select class="qk-select" id="tl-b"></select></label><label>Lap<select class="qk-select" id="tl-lap-b"></select></label>' +
      '<button type="button" class="qk-btn" id="tl-swap">⇄ Swap</button></div><p class="pd-cap" id="tl-status"></p><div id="tl-kpis"></div>' +
    '<div id="tl-stack" class="pd-chart" style="--h:900px"></div><p class="pd-cap">Delta: cumulative time gap along the lap, positive when driver A (blue) is ahead. Brake is on/off as OpenF1 reports it. Dotted lines mark the corners of the reference lap.</p>') +
    PD.grid(PD.card('Who is faster where', 'The lap in 50 m segments, coloured by the driver who covered each one quicker.', PD.chartBox('tl-map', 460), { span: 6 }) +
      PD.card('Corners', 'Minimum speed within ±80 m of each apex and the braking point (within 400 m before it).', '<div id="tl-corners"></div>', { span: 6, flush: true }) +
      PD.card('Every lap', 'Per-lap summaries for both drivers (laps under 80% or over 125% of the reference are left out). Show loads a lap above.', '<div id="tl-laps"></div>', { span: 12, flush: true }), 'pd-mt');
  var $ = function (id) { return document.getElementById(id); };
  $('tl-kind').onchange = function (e) { loadSession(e.target.value, {}); };
  $('tl-a').onchange = function (e) { S.a = e.target.value; S.lapA = fastestLap(S.a); sync(); compare(); };
  $('tl-b').onchange = function (e) { S.b = e.target.value; S.lapB = fastestLap(S.b); sync(); compare(); };
  $('tl-lap-a').onchange = function (e) { S.lapA = parseInt(e.target.value, 10); compare(); };
  $('tl-lap-b').onchange = function (e) { S.lapB = parseInt(e.target.value, 10); compare(); };
  $('tl-swap').onclick = function () { var t = S.a, l = S.lapA; S.a = S.b; S.lapA = S.lapB; S.b = t; S.lapB = l; sync(); compare(); };
  return loadSession(kind, query);
};
})(window.PD);
