/* The Quant — chart kit (v1) on Apache ECharts 5.
 * Load after quant.js and after
 *   <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js" defer></script>
 *
 * Every chart is built from the design tokens at render time, so dark/light switching
 * re-renders with the right ink, grid and series colours. If ECharts fails to load the
 * container says so and the page carries on (tables hold the same numbers).
 *
 *   QKC.mount(el, build, {label})       low-level: build(T) -> ECharts option; T = tokens
 *   QKC.line(el, spec)  QKC.bar(el, spec)  QKC.dumbbell(el, spec)  QKC.scatter(el, spec)
 *   QKC.heatmap(el, spec)  QKC.winProb(el, spec)  QKC.shotMap(el, spec)  QKC.surfaceSVG(kind)
 *   QKC.tokens()  QKC.palette()  QKC.plotlyLayout()  (migration shim for existing Plotly charts) */
(function (root) {
'use strict';

var QK = root.QK;
var esc = QK.esc, isNum = QK.isNum, fmt = QK.fmt;
var QKC = {};
var REG = [];

function tok(n) { return QK.cssVar(n); }
QKC.tokens = function () {
  var T = {
    ink1: tok('--ink-1'), ink2: tok('--ink-2'), ink3: tok('--ink-3'), ink4: tok('--ink-4'),
    s1: tok('--s-1'), s2: tok('--s-2'), s3: tok('--s-3'), s4: tok('--s-4'), bg: tok('--bg'),
    grid: tok('--grid'), axis: tok('--axis'), line2: tok('--line-2'),
    model: tok('--c-1'), market: tok('--c-2'), other: tok('--c-other'), accent: tok('--accent'), brand: tok('--brand'),
    up: tok('--up'), down: tok('--down'), live: tok('--live'),
    neg: tok('--div-neg'), mid: tok('--div-mid'), pos: tok('--div-pos'),
    seq: [tok('--seq-1'), tok('--seq-2'), tok('--seq-3'), tok('--seq-4'), tok('--seq-5')],
    fontUI: tok('--font-ui') || 'system-ui, sans-serif', fontNum: tok('--font-num') || 'monospace',
    dark: QK.theme.get() === 'dark'
  };
  T.cat = [1, 2, 3, 4, 5, 6, 7, 8].map(function (i) { return tok('--c-' + i); });
  return T;
};
QKC.palette = function () { return QKC.tokens().cat; };

/* Shared option pieces */
function base(T) {
  var anim = !QK.reducedMotion();
  return {
    backgroundColor: 'transparent',
    color: T.cat,
    animation: anim, animationDuration: anim ? 500 : 0, animationDurationUpdate: anim ? 300 : 0, animationEasing: 'cubicOut',
    textStyle: { fontFamily: T.fontUI, color: T.ink2, fontSize: 11 },
    tooltip: tooltip(T)
  };
}
function tooltip(T, extra) {
  var t = {
    trigger: 'item', confine: true, appendToBody: false,
    backgroundColor: T.s4, borderColor: T.line2, borderWidth: 1, padding: [8, 10],
    textStyle: { color: T.ink1, fontFamily: T.fontUI, fontSize: 12 },
    extraCssText: 'border-radius:8px;box-shadow:0 12px 32px rgba(0,0,0,.35);',
    axisPointer: { type: 'line', lineStyle: { color: T.axis, width: 1 }, crossStyle: { color: T.axis }, label: { backgroundColor: T.s4, color: T.ink1, fontFamily: T.fontNum } }
  };
  if (extra) Object.keys(extra).forEach(function (k) { t[k] = extra[k]; });
  return t;
}
function axis(T, o) {
  o = o || {};
  var a = {
    type: o.type || 'value',
    axisLine: { show: !!o.line, lineStyle: { color: T.axis } },
    axisTick: { show: false },
    axisLabel: { color: T.ink3, fontFamily: T.fontNum, fontSize: 10.5, margin: 10, hideOverlap: true, formatter: o.fmt },
    splitLine: { show: o.split !== false, lineStyle: { color: T.grid, width: 1 } },
    nameTextStyle: { color: T.ink3, fontFamily: T.fontUI, fontSize: 11, fontWeight: 600 },
    name: o.name || '', nameLocation: o.nameLocation || 'end', nameGap: o.nameGap || 10,
    inverse: !!o.inverse, scale: !!o.scale
  };
  /* only pass keys that are set: an explicit undefined overrides ECharts defaults (boundaryGap, min…) */
  ['min', 'max', 'interval', 'data', 'boundaryGap'].forEach(function (k) { if (o[k] !== undefined) a[k] = o[k]; });
  if (o.data) a.axisLabel.fontFamily = T.fontUI;
  return a;
}
function tipRow(c, name, val) { return '<div style="display:flex;gap:10px;align-items:center;justify-content:space-between"><span style="display:inline-flex;align-items:center;gap:6px"><i style="width:8px;height:8px;border-radius:2px;background:' + c + ';display:inline-block"></i>' + esc(name) + '</span><b style="font-family:var(--font-num);font-weight:600">' + esc(val) + '</b></div>'; }
QKC.tipRow = tipRow;
QKC.axis = axis; QKC.base = base; QKC.tooltip = tooltip;

/* ─────────────────────────────────────── mount */
function resolve(el) { return typeof el === 'string' ? document.querySelector(el) : el; }
QKC.mount = function (el, build, o) {
  el = resolve(el); o = o || {};
  if (!el) return null;
  el.classList.add('qk-chart');
  if (o.label) { el.setAttribute('role', 'img'); el.setAttribute('aria-label', o.label); }
  if (typeof root.echarts === 'undefined') {
    el.innerHTML = '<div class="qk-chart-fallback">The chart library did not load. The table beside this chart carries the same numbers.</div>';
    return null;
  }
  var prev = el.__qkc; if (prev) { try { prev.chart.dispose(); } catch (e) { /* gone */ } }
  var chart = root.echarts.init(el, null, { renderer: o.renderer || 'canvas' });
  var entry = { el: el, build: build, chart: chart, o: o };
  function paint() {
    var T = QKC.tokens();
    var opt = build(T, entry);
    var b = base(T);
    Object.keys(opt).forEach(function (k) { b[k] = opt[k]; });
    chart.setOption(b, true);
  }
  entry.paint = paint;
  paint();
  if (o.onClick) chart.on('click', o.onClick);
  else chart.on('click', function (p) { var d = p.data || {}; if (d && d.href) root.location.href = d.href; });
  if (root.ResizeObserver) { entry.ro = new ResizeObserver(function () { chart.resize(); }); entry.ro.observe(el); }
  else root.addEventListener('resize', function () { chart.resize(); });
  el.__qkc = entry; REG.push(entry);
  return chart;
};
QK.theme.onChange(function () {
  /* tokens change with the theme: repaint every live chart after the CSS swap lands */
  setTimeout(function () { REG = REG.filter(function (e) { return e.el.isConnected; }); REG.forEach(function (e) { e.paint(); }); }, 30);
});

/* ─────────────────────────────────────── line / area */
/* spec: { x: [...], xType: 'category'|'time'|'value', series: [{ name, data, color, area, dash, width, href }],
 *         yFmt, xFmt, yMin, yMax, yName, ref: {y, label}, endLabels: true, legend: false, step } */
QKC.line = function (el, s) {
  return QKC.mount(el, function (T) {
    var ser = s.series.map(function (x, i) {
      var c = x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8];
      return {
        type: 'line', name: x.name, data: x.data, showSymbol: false, symbol: 'circle', symbolSize: 8, smooth: s.smooth ? 0.25 : false, step: s.step || false,
        lineStyle: { width: x.width || 2, color: c, type: x.dash ? 'dashed' : 'solid', cap: 'round', join: 'round' },
        itemStyle: { color: c, borderColor: T.s1, borderWidth: 2 },
        emphasis: { focus: 'series', lineStyle: { width: (x.width || 2) + 1 } },
        areaStyle: x.area || s.area ? { color: new root.echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: hexA(c, 0.28) }, { offset: 1, color: hexA(c, 0) }]) } : undefined,
        endLabel: s.endLabels !== false && s.series.length > 1 ? { show: true, formatter: x.label || x.name, color: T.ink2, fontFamily: T.fontUI, fontSize: 11, fontWeight: 600, distance: 6 } : undefined,
        labelLayout: { moveOverlap: 'shiftY' },
        markLine: i === 0 && s.ref ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3], width: 1 }, label: { color: T.ink3, fontSize: 10, formatter: s.ref.label || '', position: 'insideEndTop' }, data: [{ yAxis: s.ref.y }] } : undefined
      };
    });
    return {
      grid: { left: 8, right: s.series.length > 1 && s.endLabels !== false ? 92 : 16, top: s.yName ? 30 : 14, bottom: 8, containLabel: true },
      legend: s.legend ? { top: 0, right: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 3, textStyle: { color: T.ink2 } } : undefined,
      xAxis: axis(T, { type: s.xType || 'category', data: s.xType === 'category' || !s.xType ? s.x : undefined, split: false, line: true, fmt: s.xFmt, boundaryGap: false, min: s.xMin, max: s.xMax, name: s.xName, nameLocation: 'middle', nameGap: 28 }),
      yAxis: axis(T, { fmt: s.yFmt, min: s.yMin, max: s.yMax, name: s.yName, scale: s.yScale }),
      tooltip: tooltip(T, {
        trigger: 'axis',
        formatter: function (ps) {
          var head = '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(s.xLabel ? s.xLabel(ps[0].axisValue) : ps[0].axisValueLabel) + '</div>';
          return head + ps.slice().sort(function (a, b) { return (val(b) || 0) - (val(a) || 0); }).map(function (p) { return tipRow(p.color, p.seriesName, s.yFmt ? s.yFmt(val(p)) : fmt.num(val(p), 1)); }).join('');
        }
      }),
      series: ser
    };
  }, { label: s.label });
};
function val(p) { var v = p.value; return Array.isArray(v) ? v[v.length - 1] : v; }
function hexA(hex, a) { var c = QK.color.parse(hex); return c ? 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')' : hex; }
QKC.hexA = hexA;

/* ─────────────────────────────────────── bar (vertical or horizontal) */
/* spec: { cats: [...], series: [{ name, data, color }], horizontal, stack, fmt, colors: [per-bar], hrefs: [...],
 *         labels: true (value at bar end), max, diverging (colour by sign) } */
QKC.bar = function (el, s) {
  return QKC.mount(el, function (T) {
    var hz = !!s.horizontal;
    var ser = s.series.map(function (x, i) {
      var c = x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8];
      return {
        type: 'bar', name: x.name, stack: s.stack ? 'a' : undefined, barMaxWidth: hz ? 16 : 28, barCategoryGap: '30%', barGap: '20%',
        data: x.data.map(function (v, j) {
          var cc = s.diverging ? (v >= 0 ? T.pos : T.neg) : (s.colors && s.colors[j] ? QK.color.ensure(s.colors[j], T.s1, 3) : c);
          return { value: v, href: s.hrefs ? s.hrefs[j] : undefined, itemStyle: { color: cc, borderRadius: hz ? (v < 0 ? [4, 0, 0, 4] : [0, 4, 4, 0]) : (v < 0 ? [0, 0, 4, 4] : [4, 4, 0, 0]) } };
        }),
        label: s.labels ? { show: true, position: hz ? 'right' : 'top', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: function (p) { return s.fmt ? s.fmt(p.value) : fmt.num(p.value, 1); } } : undefined,
        emphasis: { itemStyle: { shadowBlur: 0, opacity: 1 }, focus: 'none' },
        cursor: s.hrefs ? 'pointer' : 'default'
      };
    });
    var catAx = axis(T, { type: 'category', data: s.cats, split: false, line: !hz, inverse: hz });
    catAx.axisLabel.color = T.ink2; catAx.axisLabel.fontSize = 11; catAx.axisLabel.width = s.labelWidth || 110; catAx.axisLabel.overflow = 'truncate';
    var valAx = axis(T, { fmt: s.fmt, max: s.max, min: s.min, show: !s.labels });
    if (s.labels && hz) { valAx.axisLabel.show = false; valAx.splitLine.show = false; }
    return {
      grid: { left: 8, right: s.labels && hz ? 52 : 12, top: s.legend ? 30 : 10, bottom: 6, containLabel: true },
      legend: s.legend ? { top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: T.ink2 } } : undefined,
      xAxis: hz ? valAx : catAx, yAxis: hz ? catAx : valAx,
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, T.dark ? 0.05 : 0.04) } },
        formatter: function (ps) { return '<div style="font-weight:600;margin-bottom:4px">' + esc(ps[0].name) + '</div>' + ps.map(function (p) { return tipRow(p.color, p.seriesName || '', s.fmt ? s.fmt(p.value) : fmt.num(p.value, 2)); }).join(''); } }),
      series: ser
    };
  }, { label: s.label });
};

/* ─────────────────────────────────────── dumbbell: model v market (or any A v B on one scale) */
/* spec: { rows: [{ label, a, b, href, sub }], aName: 'Model', bName: 'Market', fmt: QK.fmt.pct, min: 0, max: 1 } */
QKC.dumbbell = function (el, s) {
  var rows = s.rows;
  return QKC.mount(el, function (T) {
    var cats = rows.map(function (r) { return r.label; });
    var aN = s.aName || 'Model', bN = s.bName || 'Market';
    var f = s.fmt || fmt.pct;
    return {
      grid: { left: 8, right: 20, top: 26, bottom: 6, containLabel: true },
      legend: { top: 0, left: 0, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2 }, data: [aN, bN] },
      xAxis: axis(T, { min: isNum(s.min) ? s.min : 0, max: isNum(s.max) ? s.max : 1, fmt: function (v) { return f(v, 0); } }),
      yAxis: (function () { var a = axis(T, { type: 'category', data: cats, split: false, inverse: true }); a.axisLabel.color = T.ink2; a.axisLabel.width = s.labelWidth || 170; a.axisLabel.overflow = 'truncate'; a.axisLabel.fontSize = 11; return a; })(),
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, 0.04) } },
        formatter: function (ps) {
          var r = rows[ps[0].dataIndex];
          return '<div style="font-weight:600;margin-bottom:4px;max-width:240px;white-space:normal">' + esc(r.label) + '</div>' + (r.sub ? '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(r.sub) + '</div>' : '') +
            tipRow(T.model, aN, f(r.a)) + tipRow(T.market, bN, f(r.b)) + tipRow(T.other, 'Gap', fmt.pp(r.a - r.b));
        } }),
      series: [
        { type: 'custom', name: 'gap', silent: true, z: 1,
          renderItem: function (params, api) {
            var y = api.value(2), p1 = api.coord([api.value(0), y]), p2 = api.coord([api.value(1), y]);
            return { type: 'line', shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] }, style: { stroke: hexA(T.ink2, 0.55), lineWidth: 2.5, lineCap: 'round' } };
          },
          data: rows.map(function (r, i) { return [r.a, r.b, i]; }), encode: { x: [0, 1], y: 2 } },
        { type: 'scatter', name: bN, z: 2, symbolSize: 11, itemStyle: { color: T.market, borderColor: T.s1, borderWidth: 2 }, data: rows.map(function (r, i) { return { value: [r.b, i], href: r.href }; }) },
        { type: 'scatter', name: aN, z: 3, symbolSize: 11, itemStyle: { color: T.model, borderColor: T.s1, borderWidth: 2 }, data: rows.map(function (r, i) { return { value: [r.a, i], href: r.href }; }) }
      ]
    };
  }, { label: s.label || (s.aName || 'Model') + ' against ' + (s.bName || 'market') });
};

/* ─────────────────────────────────────── scatter */
/* spec: { points: [{ x, y, name, color, size, href, label }], xName, yName, xFmt, yFmt, refX, refY,
 *         quadrants: ['top-left text', 'top-right', 'bottom-left', 'bottom-right'], labelTop: 6 } */
QKC.scatter = function (el, s) {
  return QKC.mount(el, function (T) {
    var pts = s.points;
    var show = {};
    if (s.labelAll) pts.forEach(function (p, i) { show[i] = 1; });
    else if (s.labelTop) {
      var mx = isNum(s.refX) ? s.refX : avg(pts.map(function (p) { return p.x; })), my = isNum(s.refY) ? s.refY : avg(pts.map(function (p) { return p.y; }));
      pts.map(function (p, i) { return [Math.abs(p.x - mx) / (spread(pts, 'x') || 1) + Math.abs(p.y - my) / (spread(pts, 'y') || 1), i]; })
        .sort(function (a, b) { return b[0] - a[0]; }).slice(0, s.labelTop).forEach(function (x) { show[x[1]] = 1; });
    }
    var ml = [];
    if (isNum(s.refX)) ml.push({ xAxis: s.refX });
    if (isNum(s.refY)) ml.push({ yAxis: s.refY });
    var gr = { left: 8, right: 24, top: 28, bottom: 26, containLabel: true };
    return {
      grid: gr,
      xAxis: axis(T, { fmt: s.xFmt, name: s.xName, nameLocation: 'middle', nameGap: 30, scale: true, min: s.xMin, max: s.xMax }),
      yAxis: axis(T, { fmt: s.yFmt, name: s.yName, scale: true, min: s.yMin, max: s.yMax }),
      tooltip: tooltip(T, { formatter: function (p) { var d = pts[p.dataIndex]; return '<div style="font-weight:600;margin-bottom:4px">' + esc(d.name) + '</div>' + tipRow(p.color, s.xName || 'x', s.xFmt ? s.xFmt(d.x) : fmt.num(d.x, 2)) + tipRow(p.color, s.yName || 'y', s.yFmt ? s.yFmt(d.y) : fmt.num(d.y, 2)); } }),
      graphic: s.quadrants ? quadrantLabels(T, s.quadrants) : undefined,
      series: [{
        type: 'scatter', symbolSize: function (v, p) { return pts[p.dataIndex].size || 12; },
        data: pts.map(function (p, i) {
          var c = p.color ? QK.color.ensure(p.color, T.s1, 3) : T.model;
          return { value: [p.x, p.y], name: p.name, href: p.href, itemStyle: { color: c, borderColor: T.s1, borderWidth: 1.5, opacity: 0.95 },
            label: { show: !!show[i], formatter: p.label || p.name, position: 'top', color: T.ink2, fontSize: 10.5, fontWeight: 600, fontFamily: T.fontUI } };
        }),
        emphasis: { scale: 1.4, label: { show: true } },
        labelLayout: { hideOverlap: true },
        markLine: ml.length ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4], width: 1 }, label: { show: false }, data: ml } : undefined
      }]
    };
  }, { label: s.label });
};
function avg(a) { return a.reduce(function (x, y) { return x + y; }, 0) / (a.length || 1); }
function spread(pts, k) { var v = pts.map(function (p) { return p[k]; }); return Math.max.apply(null, v) - Math.min.apply(null, v); }
function quadrantLabels(T, q) {
  var st = { fill: T.ink3, font: '600 10px ' + T.fontUI, opacity: 0.85 };
  return [
    { type: 'text', left: 70, top: 34, style: Object.assign({ text: q[0] }, st), silent: true },
    { type: 'text', right: 34, top: 34, style: Object.assign({ text: q[1], align: 'right' }, st), silent: true },
    { type: 'text', left: 70, bottom: 60, style: Object.assign({ text: q[2] }, st), silent: true },
    { type: 'text', right: 34, bottom: 60, style: Object.assign({ text: q[3], align: 'right' }, st), silent: true }
  ].filter(function (g) { return g.style.text; });
}

/* ─────────────────────────────────────── heatmap */
/* spec: { x: [...], y: [...], data: [[xi, yi, v], ...], diverging: true, mid: 0, min, max, fmt, cellLabels: true } */
QKC.heatmap = function (el, s) {
  return QKC.mount(el, function (T) {
    var vals = s.data.map(function (d) { return d[2]; }).filter(isNum);
    var lo = isNum(s.min) ? s.min : Math.min.apply(null, vals), hi = isNum(s.max) ? s.max : Math.max.apply(null, vals);
    if (s.diverging) { var m = Math.max(Math.abs(lo - (s.mid || 0)), Math.abs(hi - (s.mid || 0))); lo = (s.mid || 0) - m; hi = (s.mid || 0) + m; }
    var xa = axis(T, { type: 'category', data: s.x, split: false }); xa.splitArea = { show: false }; xa.axisLabel.color = T.ink2; xa.position = 'top';
    var ya = axis(T, { type: 'category', data: s.y, split: false, inverse: true }); ya.axisLabel.color = T.ink2;
    return {
      grid: { left: 8, right: 8, top: 26, bottom: 44, containLabel: true },
      xAxis: xa, yAxis: ya,
      visualMap: { min: lo, max: hi, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: 160,
        textStyle: { color: T.ink3, fontFamily: T.fontNum, fontSize: 10 }, formatter: function (v) { return s.fmt ? s.fmt(v) : fmt.num(v, 1); },
        inRange: { color: s.diverging ? [T.neg, T.mid, T.pos] : (T.dark ? T.seq : T.seq) } },
      tooltip: tooltip(T, { formatter: function (p) { return '<div style="font-weight:600">' + esc(s.y[p.value[1]]) + ' · ' + esc(s.x[p.value[0]]) + '</div><div style="font-family:var(--font-num)">' + esc(s.fmt ? s.fmt(p.value[2]) : fmt.num(p.value[2], 2)) + '</div>'; } }),
      series: [{ type: 'heatmap', data: s.data, itemStyle: { borderColor: T.s1, borderWidth: 2, borderRadius: 3 },
        label: { show: s.cellLabels !== false, fontFamily: T.fontNum, fontSize: 10, color: T.ink1, formatter: function (p) { return s.fmt ? s.fmt(p.value[2]) : fmt.num(p.value[2], 1); } },
        emphasis: { itemStyle: { borderColor: T.ink1, borderWidth: 1 } } }]
    };
  }, { label: s.label });
};

/* ─────────────────────────────────────── win probability */
/* spec: { t: [minutes or play index], p: [home win prob 0-1], home: {name, colour}, away: {name, colour},
 *         events: [{ t, label }], tMax, tFmt, periods: [12, 24, 36, 48] } */
QKC.winProb = function (el, s) {
  return QKC.mount(el, function (T) {
    var hc = s.home && s.home.colour ? QK.color.ensure(s.home.colour, T.s1, 3) : T.model;
    var ac = s.away && s.away.colour ? QK.color.ensure(s.away.colour, T.s1, 3) : T.market;
    if (QK.color.contrast(hc, ac) < 1.6) ac = T.market;
    var data = s.p.slice();
    var evIdx = (s.events || []).map(function (e) { var i = nearestIdx(s.t, e.t); return { coord: [i, s.p[i]], value: e.label }; });
    return {
      grid: { left: 8, right: 44, top: 22, bottom: 8, containLabel: true },
      xAxis: (function () { var a = axis(T, { type: 'category', data: s.t, split: false, line: true, fmt: s.tFmt, boundaryGap: false }); if (s.interval) a.axisLabel.interval = s.interval - 1; a.axisLabel.fontFamily = T.fontNum; return a; })(),
      yAxis: axis(T, { min: 0, max: 1, interval: 0.25, fmt: function (v) { return v === 0.5 ? '50%' : v === 1 ? (s.home ? QK.fmt.initials(s.home.abbr || s.home.name) : '100%') : v === 0 ? (s.away ? QK.fmt.initials(s.away.abbr || s.away.name) : '0%') : ''; } }),
      visualMap: { show: false, dimension: 1, seriesIndex: 4, pieces: [{ gte: 0.5, lte: 1, color: hc }, { gte: 0, lt: 0.5, color: ac }] },
      tooltip: tooltip(T, { trigger: 'axis', formatter: function (ps) { var q = ps.filter(function (x) { return x.seriesIndex === 4; })[0] || ps[0]; var p = q.value; return '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(s.tFmt ? s.tFmt(q.axisValue) : q.axisValue) + '</div>' + tipRow(hc, (s.home || {}).name || 'Home', fmt.pct(p)) + tipRow(ac, (s.away || {}).name || 'Away', fmt.pct(1 - p)); } }),
      /* fill between the 50% line and the curve: a transparent 0.5 base with the excess stacked on it,
       * one stack per side so each side takes its own team colour */
      series: [
        band('up', s.t.map(function () { return 0.5; }), null),
        band('up', s.p.map(function (p) { return Math.max(0, p - 0.5); }), hc),
        band('dn', s.t.map(function () { return 0.5; }), null),
        band('dn', s.p.map(function (p) { return Math.min(0, p - 0.5); }), ac),
        {
          type: 'line', data: data, showSymbol: false, step: s.step ? 'end' : false, lineStyle: { width: 2 }, z: 5,
          markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false },
            data: [{ yAxis: 0.5 }].concat((s.periods || []).map(function (x) { return { xAxis: nearestIdx(s.t, x) }; })) },
          markPoint: evIdx.length ? { symbol: 'circle', symbolSize: 7, itemStyle: { color: T.ink1, borderColor: T.s1, borderWidth: 2 },
            label: { show: true, position: 'top', color: T.ink2, fontSize: 10, fontWeight: 600, formatter: function (p) { return p.value; } }, data: evIdx } : undefined
        }
      ]
    };
    function band(stack, vals, c) {
      return { type: 'line', stack: stack, stackStrategy: 'all', data: vals, showSymbol: false, silent: true, step: s.step ? 'end' : false,
        lineStyle: { width: 0, opacity: 0 }, areaStyle: c ? { color: hexA(c, 0.22) } : { opacity: 0 }, tooltip: { show: false }, emphasis: { disabled: true } };
    }
  }, { label: s.label || 'Win probability through the game' });
};
function nearestIdx(ts, t) { var b = 0; for (var i = 0; i < ts.length; i++) if (Math.abs(ts[i] - t) < Math.abs(ts[b] - t)) b = i; return b; }

/* ─────────────────────────────────────── playing surfaces (SVG, chart coordinates, y up) */
var SURF = {
  pitch: { x: [0, 105], y: [0, 68] },
  rink: { x: [-100, 100], y: [-42.5, 42.5] },
  court: { x: [-25, 25], y: [-5.25, 41.75] },
  field: { x: [-260, 260], y: [-20, 440] }
};
QKC.SURF = SURF;
QKC.surfaceSVG = function (kind, T) {
  T = T || QKC.tokens();
  var S = SURF[kind]; if (!S) return '';
  var x0 = S.x[0], w = S.x[1] - S.x[0], y0 = S.y[0], hgt = S.y[1] - S.y[0];
  var st = T.dark ? 'rgba(255,255,255,0.22)' : 'rgba(13,17,23,0.28)';
  var fillA = T.dark ? 'rgba(255,255,255,0.025)' : 'rgba(13,17,23,0.025)';
  var g = '';
  var L = function (d) { g += '<path d="' + d + '"/>'; };
  if (kind === 'pitch') {
    L('M0 0H105V68H0Z'); L('M52.5 0V68');
    g += '<circle cx="52.5" cy="34" r="9.15"/><circle cx="52.5" cy="34" r="0.4" fill="' + st + '"/>';
    L('M0 13.84H16.5V54.16H0'); L('M105 13.84H88.5V54.16H105'); L('M0 24.84H5.5V43.16H0'); L('M105 24.84H99.5V43.16H105');
    g += '<circle cx="11" cy="34" r="0.4" fill="' + st + '"/><circle cx="94" cy="34" r="0.4" fill="' + st + '"/>';
    L('M16.5 26.69A9.15 9.15 0 0 1 16.5 41.31'); L('M88.5 26.69A9.15 9.15 0 0 0 88.5 41.31');
    L('M0 30.34H-1.5V37.66H0'); L('M105 30.34H106.5V37.66H105');
  } else if (kind === 'rink') {
    L('M-72 -42.5H72A28 28 0 0 1 100 -14.5V14.5A28 28 0 0 1 72 42.5H-72A28 28 0 0 1 -100 14.5V-14.5A28 28 0 0 1 -72 -42.5Z');
    g += '<path d="M0 -42.5V42.5" stroke="' + (T.dark ? 'rgba(230,103,103,0.55)' : 'rgba(227,73,72,0.55)') + '" stroke-width="1"/>';
    g += '<path d="M-25 -42.5V42.5M25 -42.5V42.5" stroke="' + (T.dark ? 'rgba(57,135,229,0.6)' : 'rgba(42,120,214,0.6)') + '" stroke-width="1"/>';
    L('M-89 -38V38'); L('M89 -38V38');
    g += '<circle cx="0" cy="0" r="15"/>';
    [[-69, 22], [-69, -22], [69, 22], [69, -22]].forEach(function (c) { g += '<circle cx="' + c[0] + '" cy="' + c[1] + '" r="15"/>'; });
    L('M-89 -4A6 6 0 0 1 -83 0A6 6 0 0 1 -89 4'); L('M89 -4A6 6 0 0 0 83 0A6 6 0 0 0 89 4');
  } else if (kind === 'court') {
    L('M-25 -5.25H25V41.75H-25Z'); L('M-8 -5.25V13.75H8V-5.25'); L('M-6 -5.25V13.75M6 -5.25V13.75');
    g += '<circle cx="0" cy="13.75" r="6"/><circle cx="0" cy="0" r="0.75"/>';
    L('M-3 -1.25H3'); L('M-4 0A4 4 0 0 0 4 0');
    L('M-22 -5.25V8.95A23.75 23.75 0 0 0 22 8.95V-5.25');
    L('M-6 41.75A6 6 0 0 1 6 41.75');
  } else if (kind === 'field') {
    var d = 400 / Math.SQRT2;
    g += '<path d="M0 0L' + (-d) + ' ' + d + 'A400 400 0 0 0 ' + d + ' ' + d + 'Z" fill="' + fillA + '"/>';
    L('M0 0L-63.6 63.6L0 127.3L63.6 63.6Z');
    L('M-' + (95 / Math.SQRT2).toFixed(1) + ' ' + (95 / Math.SQRT2).toFixed(1) + 'A95 95 0 0 0 ' + (95 / Math.SQRT2).toFixed(1) + ' ' + (95 / Math.SQRT2).toFixed(1));
    g += '<circle cx="0" cy="60.5" r="9"/>';
    [150, 250, 350].forEach(function (r) { var q = r / Math.SQRT2; g += '<path d="M' + (-q).toFixed(1) + ' ' + q.toFixed(1) + 'A' + r + ' ' + r + ' 0 0 0 ' + q.toFixed(1) + ' ' + q.toFixed(1) + '" stroke-dasharray="2 4" opacity=".55"/>'; });
  }
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + x0 + ' ' + (-(y0 + hgt)) + ' ' + w + ' ' + hgt + '" preserveAspectRatio="none"><style>path,circle,rect{vector-effect:non-scaling-stroke}</style>' +
    '<g transform="scale(1,-1)" fill="none" stroke="' + st + '" stroke-width="1.25">' +
    (kind !== 'field' ? '<rect x="' + x0 + '" y="' + y0 + '" width="' + w + '" height="' + hgt + '" fill="' + fillA + '" stroke="none"/>' : '') + g + '</g></svg>';
  return svg;
};

/* ─────────────────────────────────────── shot / spray map */
/* spec: { surface: 'pitch'|'rink'|'court'|'field', shots: [{ x, y, v (xG, 0-1), made, name, href }],
 *         sizeScale: 34 (px at v = 1; marker area grows with v), madeLabel: 'Goal', missLabel: 'Shot', colorMade, colorMiss } */
QKC.shotMap = function (el, s) {
  el = resolve(el);
  if (!el) return null;
  var S = SURF[s.surface];
  el.classList.add('qk-chart', 'sq', 'qk-surface');
  el.style.setProperty('--ar', (S.x[1] - S.x[0]) + ' / ' + (S.y[1] - S.y[0]));
  return QKC.mount(el, function (T) {
    el.style.backgroundImage = 'url("data:image/svg+xml,' + encodeURIComponent(QKC.surfaceSVG(s.surface, T)) + '")';
    var made = s.colorMade || T.market, miss = s.colorMiss || T.model;
    function pts(flag) {
      return s.shots.filter(function (p) { return !!p.made === flag; }).map(function (p) {
        return { value: [p.x, p.y, p.v], name: p.name, href: p.href, itemStyle: { color: flag ? made : hexA(miss, 0.55), borderColor: flag ? T.s1 : miss, borderWidth: flag ? 1.5 : 1 } };
      });
    }
    function sz(v) { var x = isNum(v[2]) ? v[2] : 0.08; return Math.max(5, Math.sqrt(x) * (s.sizeScale || 34)); }
    var ax = function (r) { return { type: 'value', min: r[0], max: r[1], show: false }; };
    return {
      grid: { left: 0, right: 0, top: 0, bottom: 0 },
      xAxis: ax(S.x), yAxis: ax(S.y),
      tooltip: tooltip(T, { formatter: function (p) { return '<div style="font-weight:600">' + esc(p.data.name || p.seriesName) + '</div>' + (isNum(p.value[2]) ? tipRow(p.color, s.vName || 'xG', fmt.num(p.value[2], 2)) : ''); } }),
      legend: { top: 6, right: 8, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 } },
      series: [
        { type: 'scatter', name: s.missLabel || 'Shot', symbolSize: sz, data: pts(false), z: 2 },
        { type: 'scatter', name: s.madeLabel || 'Goal', symbolSize: sz, data: pts(true), z: 3 }
      ]
    };
  }, { label: s.label || 'Shot map' });
};

/* ─────────────────────────────────────── Plotly migration shim */
/* While a site still draws with Plotly, Plotly.newPlot(el, traces, Object.assign(QKC.plotlyLayout(), layout), QKC.PLOTLY_CONFIG)
 * gets the same ink, grid, fonts and categorical order as the ECharts kit. */
QKC.plotlyLayout = function () {
  var T = QKC.tokens();
  return {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', colorway: T.cat,
    font: { family: T.fontUI, color: T.ink2, size: 11 },
    margin: { l: 44, r: 16, t: 16, b: 36 },
    xaxis: { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } },
    yaxis: { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } },
    hoverlabel: { bgcolor: T.s4, bordercolor: T.line2, font: { family: T.fontUI, color: T.ink1 } },
    legend: { orientation: 'h', y: 1.1, font: { color: T.ink2 } }
  };
};
QKC.PLOTLY_CONFIG = { displayModeBar: false, responsive: true };

root.QKC = QKC;
})(window);
