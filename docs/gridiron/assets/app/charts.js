/* The Quant Gridiron — chart helpers (GI.ch) on the kit's ECharts layer (QKC.mount, tokens, axis, tooltip).
 * Every helper takes a target (element or id) first, builds from the design tokens at paint time (so the
 * theme toggle repaints it), is disposed when the viewer leaves the page, and writes a short note instead
 * of a blank box when its data is missing. Field coordinates: yl100 is the yards to the opponent's goal
 * line (nflverse); the field charts draw from the offence's own goal line (0) to the opponent's (100).
 *
 *   mount(el, build, label, o)      QKC.mount with cleanup        rows(x)    {cols, rows} | [{}] -> [{}]
 *   line(el, spec) bar(el, spec) scatter(el, spec) dumbbell(el, spec) heatmap(el, spec)   kit charts with cleanup
 *   lines(el, series, o)            numeric-x lines with bands and error bars
 *   driveRows(x) driveChart(el, drives, o)      every drive as a bar on the field, coloured by result
 *   wpRows(x) wpChart(el, ours, o)              home win probability by play, ours v ESPN, 4th downs and scores marked
 *   fieldHeatmap(el, data, o) passGrid(el, grid, o) distBars(el, dist, o) probBars(el, items, o)
 *   radar(el, series, o) reliability(el, series, o) linescore(g, o) (HTML) */
(function (GI) {
'use strict';

const QK = window.QK, QKC = window.QKC;
const esc = GI.esc, isNum = GI.isNum;

function node(x) { return typeof x === 'string' ? document.getElementById(x) : x; }
function none(x, text) { const n = node(x); if (n) { n.classList.add('gi-chart-empty'); n.innerHTML = '<div class="gi-chart-msg">' + esc(text) + '</div>'; } return null; }
function lift(hex, T) { return QK.color.parse(hex) ? QK.color.ensure(hex, T.s1, 3) : hex; }
function tip(T, extra) { return QKC.tooltip(T, extra); }
function ax(T, o) { return QKC.axis(T, o); }
function trow(c, name, v) { return QKC.tipRow(c, name, v); }
function thead(t) { return '<div style="font-weight:600;margin-bottom:4px;max-width:280px;white-space:normal">' + t + '</div>'; }
function hexA(h, a) { return QKC.hexA(h, a); }
function legend(T, o) { return Object.assign({ top: 0, left: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { color: T.ink2, fontSize: 11 }, type: 'scroll', pageTextStyle: { color: T.ink3 } }, o || {}); }
function narrow(x) { const n = node(x); return n ? n.clientWidth < 560 : false; }

function mount(x, build, label, o) {
  const n = node(x);
  if (!n) return null;
  n.classList.remove('gi-chart-empty');
  n.innerHTML = '';
  const c = QKC.mount(n, build, Object.assign({ label: label }, o || {}));
  if (c) GI.onLeave(() => { try { c.dispose(); } catch (e) { /* gone */ } });
  return c;
}
function wrap(fn) {
  return function (x, spec) {
    const n = node(x);
    if (!n) return null;
    n.classList.remove('gi-chart-empty');
    const c = fn(n, spec);
    if (c) GI.onLeave(() => { try { c.dispose(); } catch (e) { /* gone */ } });
    return c;
  };
}
const line = wrap(QKC.line), bar = wrap(QKC.bar), scatter = wrap(QKC.scatter), dumbbell = wrap(QKC.dumbbell), heatmap = wrap(QKC.heatmap);

function rows(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns;
  if (Array.isArray(cols) && Array.isArray(x.rows)) return x.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  if (Array.isArray(x.rows)) return rows(x.rows);
  return [];
}
function firstOf(o, keys) { for (let i = 0; i < keys.length; i++) { const v = o[keys[i]]; if (v !== undefined && v !== null && v !== '') return v; } return null; }
const FIELD_LABEL = v => (v <= 0 ? 'G' : v >= 100 ? 'G' : v === 50 ? '50' : String(v < 50 ? v : 100 - v));

/* Numeric-x lines. series [{name, x, y, colour, dash, width, band: [lo[], hi[]], err[], step, area, symbol}];
 * o: {xName, yName, yFmt, xFmt, yMin, yMax, xMin, xMax, ref: {y, label}, legend, label, xLabel(x), inverse} */
function lines(x, series, o) {
  o = o || {};
  const list = (series || []).filter(s => (s.y || []).some(isNum));
  if (!list.length) return none(x, o.emptyText || 'No data.');
  const intX = list.every(s => (s.x || []).every(v => !isNum(v) || Math.round(v) === Number(v)));
  return mount(x, T => {
    const out = [];
    list.forEach((s, i) => {
      const c = s.colour ? lift(s.colour, T) : T.cat[i % 8];
      const xs = s.x || s.y.map((_, k) => k + 1);
      if (s.band && s.band[0] && s.band[1]) {
        out.push({ type: 'line', data: xs.map((v, k) => [v, s.band[0][k]]), lineStyle: { opacity: 0 }, stack: 'b' + i, symbol: 'none', silent: true, tooltip: { show: false }, emphasis: { disabled: true } });
        out.push({ type: 'line', data: xs.map((v, k) => [v, isNum(s.band[1][k]) && isNum(s.band[0][k]) ? s.band[1][k] - s.band[0][k] : null]), lineStyle: { opacity: 0 }, stack: 'b' + i, symbol: 'none', silent: true,
          areaStyle: { color: hexA(c, 0.16) }, tooltip: { show: false }, emphasis: { disabled: true } });
      }
      out.push({ type: 'line', name: s.name, data: xs.map((v, k) => [v, isNum(s.y[k]) ? Number(s.y[k]) : null]), connectNulls: true,
        showSymbol: !!s.symbol || xs.length < 30, symbolSize: 6, step: s.step ? 'end' : false,
        lineStyle: { color: c, width: s.width || 2, type: s.dash ? 'dashed' : 'solid' }, itemStyle: { color: c },
        areaStyle: s.area ? { color: hexA(c, 0.14) } : undefined, z: 3,
        markLine: i === 0 && o.ref ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { color: T.ink3, fontSize: 10, formatter: o.ref.label || '', position: 'insideEndTop' }, data: [{ yAxis: o.ref.y }] } : undefined });
      if (s.err) out.push({ type: 'custom', name: s.name + ' ±', silent: true, z: 2, tooltip: { show: false },
        renderItem: (params, api) => { const xv = api.value(0), y = api.value(1), e = api.value(2); if (!isNum(e) || !isNum(y)) return null; const a = api.coord([xv, y - e]), b = api.coord([xv, y + e]); return { type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: { stroke: c, lineWidth: 1.2 } }; },
        data: xs.map((v, k) => [v, s.y[k], s.err[k]]) });
    });
    return {
      grid: { left: 8, right: 16, top: (o.legend === false || list.length < 2 ? 18 : 34) + (o.yName ? 12 : 0), bottom: o.xName ? 26 : 8, containLabel: true },
      legend: o.legend === false || list.length < 2 ? undefined : legend(T, { data: list.map(s => s.name) }),
      xAxis: Object.assign(ax(T, { type: 'value', name: o.xName, nameLocation: 'middle', nameGap: 26, min: o.xMin, max: o.xMax, fmt: o.xFmt, split: false, line: true, scale: true }), intX ? { minInterval: 1 } : {}),
      yAxis: (a => { a.axisLine.onZero = false; return a; })(ax(T, { name: o.yName, nameAlign: 'left', nameLocation: o.inverse ? 'start' : 'end', min: o.yMin, max: o.yMax, fmt: o.yFmt, scale: o.yMin === undefined, inverse: !!o.inverse })),
      tooltip: tip(T, { trigger: 'axis', formatter: ps => {
        const real = ps.filter(p => p.seriesName && p.seriesType === 'line' && list.some(s => s.name === p.seriesName));
        if (!real.length) return '';
        const xv = real[0].value[0];
        return '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(o.xLabel ? o.xLabel(xv) : (o.xName ? o.xName + ' ' : '') + xv) + '</div>' +
          real.map(p => trow(p.color, p.seriesName, o.yFmt ? o.yFmt(p.value[1]) : GI.num(p.value[1], 2))).join('');
      } }),
      series: out
    };
  }, o.label);
}

// ── drives ────────────────────────────────────────────────────────────────

function driveRows(x) {
  return rows(x).map((d, k) => {
    const s = firstOf(d, ['start_yl100', 'yl100_start', 'start', 'start_yardline_100', 'drive_start_yl100']);
    let e = firstOf(d, ['end_yl100', 'yl100_end', 'end', 'end_yardline_100', 'drive_end_yl100']);
    const yards = firstOf(d, ['yards', 'yds', 'net_yards']);
    if (!isNum(e) && isNum(s) && isNum(yards)) e = Number(s) - Number(yards);
    const res = String(firstOf(d, ['result', 'drive_result', 'end_result']) || '').toLowerCase();
    if (/^touchdown$|^td$/.test(res)) e = 0;
    return {
      n: isNum(d.n) ? Number(d.n) : (isNum(d.drive) ? Number(d.drive) : k + 1),
      team: firstOf(d, ['team', 'posteam', 'offense']), qtr: firstOf(d, ['qtr', 'quarter', 'start_qtr']),
      clock: firstOf(d, ['start_clock', 'clock', 'start_time']), start: isNum(s) ? Number(s) : null, end: isNum(e) ? Number(e) : null,
      result: firstOf(d, ['result', 'drive_result', 'end_result']) || '', plays: firstOf(d, ['plays', 'n_plays', 'play_count']),
      yards: isNum(yards) ? Number(yards) : (isNum(s) && isNum(e) ? Number(s) - Number(e) : null),
      epa: firstOf(d, ['epa', 'total_epa']), time: firstOf(d, ['time', 'top', 'duration', 'time_of_possession']),
      points: firstOf(d, ['points', 'pts']), desc: firstOf(d, ['desc', 'summary']) || ''
    };
  }).filter(d => isNum(d.start));
}
/* Each drive a bar on the field, own goal line (0) to the opponent's (100), first drive at the top. */
function driveChart(x, drives, o) {
  o = o || {};
  const D = driveRows(drives);
  if (!D.length) return none(x, o.emptyText || 'No drives yet.');
  const n = node(x);
  if (n) n.style.setProperty('--h', Math.max(260, D.length * 22 + 70) + 'px');
  const cats = D.map(d => d.n + ' · ' + GI.teamAbbr(d.team));
  const groups = {};
  D.forEach((d, i) => { const r = GI.driveResult(d.result); (groups[r.label] = groups[r.label] || { colour: r.colour, items: [] }).items.push([i, d]); });
  return mount(x, T => {
    const series = Object.keys(groups).map(k => ({
      type: 'custom', name: k, itemStyle: { color: groups[k].colour },
      renderItem: (params, api) => {
        const i = api.value(0), a = api.value(1), b = api.value(2);
        const p0 = api.coord([Math.min(a, b), i]), p1 = api.coord([Math.max(a, b), i]);
        const h = api.size([0, 1])[1] * 0.6;
        return { type: 'rect', shape: { x: p0[0], y: p0[1] - h / 2, width: Math.max(3, p1[0] - p0[0]), height: h, r: 3 }, style: { fill: hexA(groups[k].colour, 0.85), stroke: groups[k].colour } };
      },
      encode: { x: [1, 2], y: 0 },
      data: groups[k].items.map(it => { const d = it[1]; const s0 = 100 - d.start, e0 = 100 - (isNum(d.end) ? Math.max(-2, Math.min(102, d.end)) : d.start); return { value: [it[0], s0, e0], d: d }; })
    }));
    series.push({ type: 'scatter', name: 'Offence', symbol: 'rect', symbolSize: [5, 14], silent: true, tooltip: { show: false }, z: 4,
      data: D.map((d, i) => ({ value: [100 - d.start, i], itemStyle: { color: lift(GI.teamColour(d.team), T) } })) });
    let prevQ = null;
    const qLines = [];
    D.forEach((d, i) => { if (isNum(d.qtr) && prevQ !== null && Number(d.qtr) !== prevQ) qLines.push({ yAxis: i - 0.5 }); if (isNum(d.qtr)) prevQ = Number(d.qtr); });
    series[0].markLine = qLines.length ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [2, 3] }, label: { show: false }, data: qLines } : undefined;
    series[0].markArea = { silent: true, data: [[{ xAxis: -10, itemStyle: { color: hexA(T.model, 0.08) } }, { xAxis: 0 }], [{ xAxis: 100, itemStyle: { color: hexA(T.market, 0.1) } }, { xAxis: 110 }]] };
    const yA = ax(T, { type: 'category', data: cats, split: false, inverse: true });
    yA.axisLabel.fontSize = 9.5;
    const xA = ax(T, { type: 'value', min: -10, max: 110, interval: 10, fmt: v => (v < 0 || v > 100 ? '' : FIELD_LABEL(v)) });
    xA.position = 'top';
    xA.name = o.xName || 'Field position (yards)'; xA.nameLocation = 'middle'; xA.nameGap = 22;
    return {
      grid: { left: 8, right: 10, top: 46, bottom: 30, containLabel: true },
      legend: legend(T, { top: 'auto', bottom: 0, data: Object.keys(groups), icon: 'roundRect', itemHeight: 8, itemWidth: 12 }),
      xAxis: xA, yAxis: yA,
      tooltip: tip(T, { formatter: p => {
        const d = p.data && p.data.d; if (!d) return '';
        const r = GI.driveResult(d.result);
        const opp = o.home && o.away ? (String(d.team) === String(o.home) ? o.away : o.home) : null;
        return thead(esc(GI.teamName(d.team)) + ' · ' + esc(GI.clockText(d.qtr, d.clock))) +
          trow(r.colour, r.label, (isNum(d.plays) ? d.plays + ' plays' : '') + (isNum(d.yards) ? ', ' + Math.round(d.yards) + ' yds' : '')) +
          trow(T.ink3, 'From', GI.fieldPos(d.start, d.team, opp) + ' → ' + (isNum(d.end) ? GI.fieldPos(Math.max(0, Math.min(100, d.end)), d.team, opp) : '—')) +
          (isNum(d.epa) ? trow(T.ink3, 'EPA', GI.signed(d.epa, 2)) : '') + (d.time ? trow(T.ink3, 'Time', GI.fmtClock(d.time)) : '');
      } }),
      series: series
    };
  }, o.label || 'Drive chart: every drive on the field, coloured by result');
}

// ── win probability ───────────────────────────────────────────────────────

function wpRows(x) {
  const list = Array.isArray(x) ? x : rows(x);
  return list.map((r, k) => {
    if (Array.isArray(r)) {
      if (r.length >= 4) return { i: Number(r[0]), qtr: r[1], clock: r[2], p: Number(r[3]), desc: r[4] || '' };
      return { i: Number(r[0]), p: Number(r[1]), desc: r[2] || '' };
    }
    if (r && typeof r === 'object') {
      const p = firstOf(r, ['p_home', 'wp_home', 'p', 'wp', 'wp_home_ours']);
      return { i: isNum(r.i) ? Number(r.i) : (isNum(r.idx) ? Number(r.idx) : (isNum(r.play) ? Number(r.play) : k)), qtr: r.qtr, clock: r.clock, p: Number(p), desc: r.desc || r.label || '' };
    }
    return null;
  }).filter(r => r && isNum(r.i) && isNum(r.p));
}
/* Home win probability by play: our model (fill above/below 50% in each club's colour), ESPN dotted, every 4th
 * down a diamond coloured by grade, scoring plays dots in the scorer's colour, key plays numbered.
 * o: {espn, fourth, scoring, top, home, away, market, tName, yName (axis titles)} */
function wpChart(x, ours, o) {
  o = o || {};
  const R = wpRows(ours), E = wpRows(o.espn);
  if (R.length < 2 && E.length < 2) return none(x, o.emptyText || 'No win-probability path for this game yet.');
  const main = R.length >= 2 ? R : E;
  const xs = main.map(r => r.i);
  const idxOf = i => { let b = 0; for (let k = 0; k < xs.length; k++) if (xs[k] <= i) b = k; return b; };
  const hn = o.home ? GI.teamAbbr(o.home) : 'Home', an = o.away ? GI.teamAbbr(o.away) : 'Away';
  return mount(x, T => {
    let hc = o.home ? lift(GI.teamColour(o.home), T) : T.model, ac = o.away ? lift(GI.teamColour(o.away), T) : T.market;
    if (QK.color.contrast(hc, ac) < 1.6) ac = T.market;
    const p = main.map(r => r.p);
    const qMarks = [];
    let prevQ = null;
    main.forEach((r, k) => { if (isNum(r.qtr) && Number(r.qtr) !== prevQ) { if (prevQ !== null) qMarks.push({ xAxis: k, label: { formatter: GI.qtrLabel(r.qtr), position: 'end', rotate: 0, distance: 4 } }); prevQ = Number(r.qtr); } });
    /* the fill between 50% and the curve, one polygon per side (stepped like the line) */
    const fill = {
      type: 'custom', silent: true, z: 1, tooltip: { show: false }, data: [[0, 0.5]],
      renderItem: (params, api) => {
        const up = [], dn = [];
        for (let k = 0; k < p.length; k++) {
          const v = p[k], nx = k + 1 < p.length ? k + 1 : k;
          [[k, v], [nx, v]].forEach(pt => { up.push(api.coord([pt[0], Math.max(0.5, pt[1])])); dn.push(api.coord([pt[0], Math.min(0.5, pt[1])])); });
        }
        const b0 = api.coord([0, 0.5]), b1 = api.coord([p.length - 1, 0.5]);
        return { type: 'group', children: [
          { type: 'polygon', shape: { points: [b0].concat(up).concat([b1]) }, style: { fill: hexA(hc, 0.22) } },
          { type: 'polygon', shape: { points: [b0].concat(dn).concat([b1]) }, style: { fill: hexA(ac, 0.22) } }] };
      }
    };
    const series = [
      fill,
      { type: 'line', name: R.length >= 2 ? 'Our model' : 'ESPN', data: p.map((v, k) => [k, v]), showSymbol: false, step: 'end', z: 5, lineStyle: { width: 2, color: T.ink1 }, itemStyle: { color: T.ink1 },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: true, position: 'insideEndTop', color: T.ink3, fontSize: 9.5 }, data: [{ yAxis: 0.5, label: { show: false } }].concat(qMarks) } }
    ];
    if (R.length >= 2 && E.length >= 2) {
      const ep = xs.map(i => { let b = null; E.forEach(r => { if (r.i <= i) b = r.p; }); return b; });
      series.push({ type: 'line', name: 'ESPN', data: ep.map((v, k) => [k, v]), showSymbol: false, step: 'end', z: 4, lineStyle: { width: 1.4, type: [3, 3], color: T.ink3 }, itemStyle: { color: T.ink3 } });
    }
    const sc = (o.scoring || []).filter(s => isNum(s.i));
    if (sc.length) series.push({ type: 'scatter', name: 'Score', z: 6, symbolSize: 8,
      data: sc.map(s => { const k = idxOf(s.i); return { value: [k, isNum(s.p) ? s.p : p[k]], s: s, itemStyle: { color: lift(GI.teamColour(s.team), T), borderColor: T.s1, borderWidth: 1.5 } }; }) });
    const fd = (o.fourth || []).filter(s => isNum(s.i));
    if (fd.length) series.push({ type: 'scatter', name: '4th down', z: 7, symbol: 'diamond', symbolSize: 11,
      data: fd.map(s => { const k = idxOf(s.i); const g = GI.gradeOf(s.grade, s.wp_lost); return { value: [k, isNum(s.p) ? s.p : p[k]], f: s, g: g, itemStyle: { color: g.colour, borderColor: T.s1, borderWidth: 1.5 } }; }) });
    const top = (o.top || []).filter(s => isNum(s.i)).slice(0, o.nTop || 5);
    if (top.length) series.push({ type: 'scatter', name: 'Key play', z: 8, symbolSize: 16, symbol: 'circle',
      label: { show: true, formatter: q => String(q.data.k), color: T.ink1, fontSize: 9.5, fontWeight: 700 },
      data: top.map((s, j) => { const k = idxOf(s.i); return { value: [k, isNum(s.p) ? s.p : p[k]], t: s, k: j + 1, itemStyle: { color: T.s4, borderColor: T.ink2, borderWidth: 1 } }; }) });
    const xa = ax(T, { type: 'value', min: 0, max: Math.max(1, p.length - 1), split: false, line: true });
    xa.axisLabel.show = false;
    const gB = 8 + QKC.nameAxis(xa, o.tName === undefined ? 'Play' : o.tName, 'bottom');
    const ya = ax(T, { min: 0, max: 1, interval: 0.25, fmt: v => (v === 1 ? hn + ' 100%' : v === 0 ? an + ' 100%' : v === 0.5 ? '50%' : (v > 0.5 ? Math.round(v * 100) : Math.round((1 - v) * 100)) + '%') });
    const yN = o.yName === undefined ? 'Win probability' : o.yName;
    if (yN) { ya.name = yN; ya.nameLocation = 'middle'; ya.nameRotate = 90; ya.nameGap = 16 + 6.4 * (Math.max(hn.length, an.length) + 5); }
    return {
      grid: { left: yN ? 24 : 8, right: 14, top: 26, bottom: gB, containLabel: true },
      legend: R.length >= 2 && E.length >= 2 ? legend(T, { right: 0, left: 'auto', data: ['Our model', 'ESPN'] }) : undefined,
      xAxis: xa,
      yAxis: ya,
      tooltip: tip(T, { trigger: 'item', formatter: q => {
        if (q.seriesName === 'Score') { const s = q.data.s; return thead(esc(GI.teamAbbr(s.team)) + ' ' + esc(s.kind || 'score')) + esc(String(s.desc || '').slice(0, 140)); }
        if (q.seriesName === '4th down') { const s = q.data.f, g = q.data.g; return thead('4th down · ' + esc(GI.teamAbbr(s.team || '')) + ' ' + esc(GI.choiceLabel(s.choice))) + trow(g.colour, g.label, isNum(s.wp_lost) ? GI.num(Math.abs(s.wp_lost) * 100, 1) + ' pts lost' : '') + (s.rec ? trow(T.ink3, 'Model said', GI.choiceLabel(s.rec)) : '') + (s.desc ? '<div style="max-width:280px;white-space:normal;color:' + T.ink3 + '">' + esc(String(s.desc).slice(0, 140)) + '</div>' : ''); }
        if (q.seriesName === 'Key play') { const s = q.data.t; return thead('Key play ' + q.data.k) + trow(T.ink3, hn + ' WPA', GI.signed((s.wpa || 0) * 100, 1) + ' pts') + '<div style="max-width:280px;white-space:normal">' + esc(String(s.desc || '').slice(0, 160)) + '</div>'; }
        const r = main[q.dataIndex]; if (!r) return '';
        return '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(GI.clockText(r.qtr, r.clock)) + '</div>' + trow(hc, hn, GI.pct(r.p, 1)) + trow(ac, an, GI.pct(1 - r.p, 1)) +
          (r.desc ? '<div style="max-width:300px;white-space:normal;margin-top:4px;color:' + T.ink2 + '">' + esc(String(r.desc).slice(0, 160)) + '</div>' : '');
      } }),
      series: series
    };
  }, o.label || 'Win probability through the game');
}

// ── field position, passing grid ──────────────────────────────────────────

function fieldHeatmap(x, data, o) {
  o = o || {};
  let d = data;
  if (Array.isArray(d) && d.length && !Array.isArray(d[0])) d = { v: [d] };
  else if (Array.isArray(d)) d = { v: d };
  d = d || {};
  let v = d.v || d.values || d.z;
  if (!Array.isArray(v) || !v.length) return none(x, o.emptyText || 'No field-position data.');
  if (!Array.isArray(v[0])) v = [v];
  const nb = v[0].length;
  let xs = d.x || d.bins || Array.from({ length: nb }, (_, i) => (100 * (i + 0.5)) / nb);
  if (o.yl100 || d.yl100) xs = xs.map(b => 100 - Number(b));
  const ys = d.y || d.rows || (v.length === 1 ? [o.rowLabel || ''] : v.map((_, i) => String(i + 1)));
  const cells = [];
  v.forEach((r, yi) => (r || []).forEach((val, xi) => { if (isNum(val)) cells.push([xi, yi, Number(val)]); }));
  if (!cells.length) return none(x, o.emptyText || 'No field-position data.');
  const lab = c => { const y = Math.round(Number(c)); return y === 50 ? '50' : y < 50 ? 'Own ' + y : 'Opp ' + (100 - y); };
  const n = node(x);
  if (n) n.style.setProperty('--h', (o.height || Math.max(170, 90 + ys.length * 34)) + 'px');
  return heatmap(x, { xName: o.xName || 'Field position', yName: o.yName, x: xs.map(lab), y: ys, data: cells, diverging: o.scale !== 'seq', mid: isNum(o.center) ? o.center : GI.median(cells.map(c => c[2])), fmt: o.fmt ? (q => GI.fmtVal(q, o.fmt)) : (q => GI.num(q, 2)), cellLabels: xs.length <= 12, label: o.label });
}
const DEPTHS = ['Behind LOS', '0–9', '10–19', '20+'];
const LOCS = ['Left', 'Middle', 'Right'];
function gridOf(grid) {
  const g = grid || {};
  if (Array.isArray(g.v || g.values)) return { depths: g.depths || g.y || DEPTHS, locs: g.locs || g.x || LOCS, v: g.v || g.values, n: g.n || null };
  const list = rows(g.rows || g);
  if (!list.length) return null;
  const depths = [], locs = [];
  list.forEach(r => { const dp = String(firstOf(r, ['depth', 'air_depth', 'd'])); const lc = String(firstOf(r, ['loc', 'location', 'pass_location', 'l'])); if (depths.indexOf(dp) < 0) depths.push(dp); if (locs.indexOf(lc) < 0) locs.push(lc); });
  locs.sort((a, b) => { const ia = LOCS.findIndex(r => r.toLowerCase() === a.toLowerCase()), ib = LOCS.findIndex(r => r.toLowerCase() === b.toLowerCase()); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib); });
  const v = depths.map(() => locs.map(() => null)), n = depths.map(() => locs.map(() => null));
  list.forEach(r => {
    const i = depths.indexOf(String(firstOf(r, ['depth', 'air_depth', 'd']))), j = locs.indexOf(String(firstOf(r, ['loc', 'location', 'pass_location', 'l'])));
    if (i >= 0 && j >= 0) { v[i][j] = firstOf(r, ['value', 'v', 'epa', 'epa_per_play']); n[i][j] = firstOf(r, ['n', 'att', 'targets']); }
  });
  return { depths: depths, locs: locs.map(l => GI.titleCase(l)), v: v, n: n };
}
/* Depth x location grid (deepest on top). o: {fmt, center, scale: 'seq', label} */
function passGrid(x, grid, o) {
  o = o || {};
  const g = gridOf(grid);
  if (!g || !g.v.length) return none(x, o.emptyText || 'No passing grid yet.');
  const cells = [];
  const dep = g.depths.slice().reverse();
  g.v.forEach((r, i) => (r || []).forEach((val, j) => { if (isNum(val)) cells.push([j, g.depths.length - 1 - i, Number(val)]); }));
  if (!cells.length) return none(x, o.emptyText || 'No passing grid yet.');
  return heatmap(x, { xName: o.xName || 'Pass direction', yName: o.yName || 'Air yards', x: g.locs, y: dep, data: cells, diverging: o.scale !== 'seq', mid: isNum(o.center) ? o.center : 0, fmt: o.fmt ? (q => GI.fmtVal(q, o.fmt)) : (q => GI.signed(q, 2)), label: o.label || 'Passing by depth and direction' });
}

// ── distributions, probability bars, radar, reliability ───────────────────

/* Bars of {k: p} (or [[k, p]]). o: {actual, exp, line, xName, yName ('Probability'), colour, unit, signed, split, colours: [above, below]} */
function distBars(x, dist, o) {
  o = o || {};
  let entries;
  if (Array.isArray(dist)) entries = dist.map((p, k) => (Array.isArray(p) ? [Number(p[0]), p[1]] : [k + (o.offset || 0), p]));
  else entries = Object.keys(dist || {}).map(k => [Number(k), dist[k]]);
  entries = entries.filter(e => isNum(e[0]) && isNum(e[1]) && e[1] > 0.0005).sort((a, b) => a[0] - b[0]);
  if (!entries.length) return none(x, o.emptyText || 'No distribution.');
  return mount(x, T => {
    const col = o.colour ? lift(o.colour, T) : T.model;
    const ca = o.colours ? lift(o.colours[0], T) : T.model, cb = o.colours ? lift(o.colours[1], T) : T.market;
    const colourOf = k => {
      if (isNum(o.actual) && Number(k) === Number(o.actual)) return T.ink1;
      if (o.split !== undefined && o.split !== null) return k > o.split ? ca : (k < o.split ? cb : T.ink3);
      return col;
    };
    const ml = [];
    if (isNum(o.line)) ml.push({ xAxis: o.line, label: { formatter: 'line ' + (o.signed ? GI.signed(o.line, 1) : o.line) } });
    if (isNum(o.exp)) ml.push({ xAxis: o.exp, label: { formatter: 'model ' + (o.signed ? GI.signed(o.exp, 1) : GI.num(o.exp, 1)) } });
    return {
      grid: { left: 8, right: 14, top: 22 + (o.yName === '' ? 0 : 12), bottom: o.xName ? 26 : 8, containLabel: true },
      xAxis: ax(T, { type: 'value', name: o.xName, nameLocation: 'middle', nameGap: 26, split: false, line: true, scale: true, fmt: v => (o.signed && v > 0 ? '+' : '') + v }),
      yAxis: (a => { a.axisLine.onZero = false; return a; })(ax(T, { name: o.yName === undefined ? 'Probability' : o.yName, nameAlign: 'left', fmt: v => Math.round(v * 100) + '%' })),
      tooltip: tip(T, { formatter: q => thead((o.signed && q.value[0] > 0 ? '+' : '') + q.value[0] + ' ' + esc(o.unit || 'pts')) + trow(q.color, 'Chance', GI.pct(q.value[1], 1)) }),
      series: [{ type: 'bar', barWidth: '80%', data: entries.map(e => ({ value: e, itemStyle: { color: colourOf(e[0]), borderRadius: [2, 2, 0, 0] } })),
        markLine: ml.length ? { silent: true, symbol: 'none', lineStyle: { color: T.ink2, type: [4, 3] }, label: { color: T.ink2, fontSize: 10, position: 'insideEndTop' }, data: ml } : undefined }]
    };
  }, o.label || 'Distribution');
}
/* Horizontal probability bars with the market as a tick. items [{label, p, colour, market, href}];
 * o.valName titles the value axis ('Probability' unless given). */
function probBars(x, items, o) {
  o = o || {};
  const list = (items || []).filter(i => isNum(i.p) && (i.p > 0 || isNum(i.market))).slice(0, o.top || 12);
  if (!list.length) return none(x, o.emptyText || 'Nothing to show.');
  const n = node(x);
  if (n && !o.keepHeight) n.style.setProperty('--h', Math.max(200, list.length * 30 + 40) + 'px');
  const mx = Math.max.apply(null, list.map(i => Math.max(i.p || 0, i.market || 0)));
  return mount(x, T => {
    const cats = list.map(i => i.label);
    const ya = ax(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = o.labelWidth || 120; ya.axisLabel.overflow = 'truncate'; ya.axisLabel.fontSize = 11;
    const xa = ax(T, { min: 0, max: Math.min(1, mx * 1.18 + 0.02), fmt: v => Math.round(v * 100) + '%' });
    const gB = 6 + QKC.nameAxis(xa, o.valName === undefined ? 'Probability' : o.valName, 'bottom');
    const series = [{ type: 'bar', name: o.modelName || 'Model', barMaxWidth: 16, cursor: 'pointer',
      data: list.map(i => ({ value: i.p, href: i.href, itemStyle: { color: i.colour ? lift(i.colour, T) : T.model, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: 'right', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: q => GI.pct(q.value, q.value < 0.1 ? 1 : 0) } }];
    if (list.some(i => isNum(i.market))) series.push({ type: 'scatter', name: o.marketName || 'Market', symbol: 'rect', symbolSize: [3, 18], z: 5,
      itemStyle: { color: T.market }, data: list.map((i, k) => (isNum(i.market) ? [i.market, k] : null)).filter(Boolean) });
    return {
      grid: { left: 8, right: 44, top: series.length > 1 ? 26 : 6, bottom: gB, containLabel: true },
      legend: series.length > 1 ? legend(T, { data: [o.modelName || 'Model', o.marketName || 'Market'] }) : undefined,
      xAxis: xa, yAxis: ya,
      tooltip: tip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, 0.04) } }, formatter: ps => {
        const it = list[ps[0].dataIndex]; if (!it) return '';
        return thead(esc(it.label)) + trow(T.model, o.modelName || 'Model', GI.pct(it.p, 1)) + (isNum(it.market) ? trow(T.market, o.marketName || 'Market', GI.pct(it.market, 1)) + trow(T.other, 'Gap', GI.signed((it.p - it.market) * 100, 1) + ' pts') : '');
      } }),
      series: series
    };
  }, o.label || 'Probabilities');
}
/* series [{name, values: [0-100], colour}]; o: {labels} */
function radar(x, series, o) {
  o = o || {};
  const labels = o.labels || [];
  const list = (series || []).filter(s => (s.values || []).some(isNum));
  if (!list.length || labels.length < 3) return none(x, o.emptyText || 'Not enough data for a radar.');
  return mount(x, T => ({
    legend: list.length > 1 ? legend(T, { data: list.map(s => s.name), icon: 'circle', itemWidth: 9, itemHeight: 9 }) : undefined,
    radar: { indicator: labels.map(l => ({ name: l, max: 100, min: 0 })), radius: narrow(x) ? '58%' : '66%', center: ['50%', '55%'], splitNumber: 4,
      axisName: { color: T.ink2, fontSize: 10.5 }, splitLine: { lineStyle: { color: T.grid } }, splitArea: { show: false }, axisLine: { lineStyle: { color: T.grid } } },
    tooltip: tip(T, { formatter: q => thead(esc(q.name)) + labels.map((l, i) => trow(q.color, l, isNum(q.value[i]) ? Math.round(q.value[i]) + 'th pct' : '—')).join('') }),
    series: [{ type: 'radar', symbolSize: 4, data: list.map((s, i) => { const c = s.colour ? lift(s.colour, T) : T.cat[i % 8]; return { name: s.name, value: s.values.map(v => (isNum(v) ? v : 0)), lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, areaStyle: { color: hexA(c, 0.16) } }; }) }]
  }), o.label || 'Percentile radar');
}
function binsOf(bins) {
  return (bins || []).map(b => (Array.isArray(b) ? (b.length >= 4 ? { x: b[1], y: b[2], n: b[3] || 0 } : { x: b[0], y: b[1], n: b[2] || 0 })
    : { x: [b.mean_p, b.p, b.pred, b.x, b.forecast, b.mean_pred].find(isNum), y: [b.freq, b.obs, b.y, b.observed, b.actual, b.rate, b.mean_obs].find(isNum), n: b.n || b.count || 0 }))
    .filter(b => isNum(b.x) && isNum(b.y));
}
/* Reliability diagram: series [{name, colour, bins}], points sized by n. o: {min, max, fmt} */
function reliability(x, series, o) {
  o = o || {};
  const S = (series || []).map(s => Object.assign({}, s, { b: binsOf(s.bins).filter(b => !o.minN || b.n >= o.minN) })).filter(s => s.b.length);
  if (!S.length) return none(x, 'No reliability bins.');
  const lo = isNum(o.min) ? o.min : 0, hi = isNum(o.max) ? o.max : 1;
  const f = o.fmt || (v => Math.round(v * 100) + '%');
  return mount(x, T => {
    const maxN = Math.max.apply(null, S.map(s => Math.max.apply(null, s.b.map(b => b.n || 1))));
    return {
      grid: { left: 8, right: 16, top: S.length > 1 ? 30 : 12, bottom: 28, containLabel: true },
      legend: S.length > 1 ? legend(T, { data: S.map(s => s.name) }) : undefined,
      xAxis: ax(T, { min: lo, max: hi, fmt: f, name: o.xName || 'Forecast', nameLocation: 'middle', nameGap: 26 }),
      yAxis: ax(T, { min: lo, max: hi, fmt: f, name: o.yName || 'Observed' }),
      tooltip: tip(T, { formatter: q => thead(esc(q.seriesName)) + trow(q.color, 'Forecast', f(q.value[0])) + trow(q.color, 'Observed', f(q.value[1])) + trow(T.ink3, 'n', GI.int(q.value[2])) }),
      series: [{ type: 'line', silent: true, data: [[lo, lo], [hi, hi]], showSymbol: false, lineStyle: { color: T.axis, type: [3, 3], width: 1 }, tooltip: { show: false } }]
        .concat(S.map((s, i) => { const c = s.colour ? lift(s.colour, T) : T.cat[i % 8]; return { type: 'line', name: s.name, data: s.b.map(b => [b.x, b.y, b.n]), symbolSize: v => 5 + 12 * Math.sqrt((v[2] || 1) / maxN), lineStyle: { color: c, width: 1.6, type: s.dash ? 'dashed' : 'solid' }, itemStyle: { color: c } }; }))
    };
  }, o.label || 'Reliability diagram');
}

// ── linescore (HTML) ──────────────────────────────────────────────────────

function quartersOf(g) {
  const q = g.quarters || g.linescore || g.score_by_quarter || g.by_quarter || (g.score && Array.isArray(g.score.home) ? g.score : null);
  if (!q) return [];
  if (Array.isArray(q)) return q.map(r => (Array.isArray(r) ? r : [r.away, r.home]));
  if (Array.isArray(q.home) && Array.isArray(q.away)) return q.home.map((h, i) => [q.away[i], h]);
  return [];
}
function linescore(g) {
  if (!g) return '';
  const qs = quartersOf(g);
  const n = Math.max(4, qs.length);
  const row = (t, k, tot) => {
    let h = '<tr><td class="sticky-col">' + GI.teamLink(t, { abbr: true }) + '</td>';
    for (let i = 0; i < n; i++) { const v = qs[i] ? qs[i][k] : null; h += '<td class="num' + (v > 0 ? ' gi-ls-run' : '') + '">' + (v === null || v === undefined ? '' : esc(v)) + '</td>'; }
    return h + '<td class="num gi-ls-t">' + (isNum(tot) ? tot : (qs.length ? qs.reduce((s, r) => s + (Number(r[k]) || 0), 0) : '')) + '</td></tr>';
  };
  let head = '<tr><th class="sticky-col"></th>';
  for (let i = 0; i < n; i++) head += '<th class="num">' + (i < 4 ? i + 1 : (i === 4 ? 'OT' : (i - 3) + 'OT')) + '</th>';
  head += '<th class="num">T</th></tr>';
  return '<div class="qk-table-wrap"><table class="qk-table dense gi-ls"><thead>' + head + '</thead><tbody>' + row(g.away, 0, g.as) + row(g.home, 1, g.hs) + '</tbody></table></div>';
}

GI.ch = { mount: mount, none: none, rows: rows, line: line, bar: bar, scatter: scatter, dumbbell: dumbbell, heatmap: heatmap, lines: lines,
  driveRows: driveRows, driveChart: driveChart, wpRows: wpRows, wpChart: wpChart, fieldHeatmap: fieldHeatmap, passGrid: passGrid, gridOf: gridOf,
  distBars: distBars, probBars: probBars, radar: radar, reliability: reliability, binsOf: binsOf, linescore: linescore, quartersOf: quartersOf,
  lift: lift, tip: tip, ax: ax, trow: trow, thead: thead, legend: legend, hexA: hexA, narrow: narrow, FIELD_LABEL: FIELD_LABEL };
})(window.GI);
