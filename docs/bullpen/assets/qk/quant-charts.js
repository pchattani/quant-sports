/* The Quant — chart kit (v2 "Signal"; every v1 call still works) on Apache ECharts 5. Conventions: STYLE_GUIDE.md.
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
 *   QKC.range(el, spec) (floor–ceiling)  QKC.butterfly(el, spec) (two sides of one category list)
 *   QKC.tokens()  QKC.palette()  QKC.axis(T, {ticks})  QKC.legendSeries(T, items)
 *   QKC.plotlyLayout()  and the optional module plotly-ec.js (window.Plotly on this kit) for old views
 * v2: QKC.forecast(el, spec) (538-style chance over time: end labels, annotations, bands, today, projection)
 *     QKC.distribution(el, spec) (histogram on the percentile scale with labelled marks)
 *     QKC.chances(el, spec) (our chance as bars, the market as a quiet tick)
 *     T.model is the signal (ours), T.market a quiet grey; dumbbells read "Our model" v "Market", no gap row.
 *
 * ECharts 5.5.1 note: never pair a line series with a piecewise visualMap (it throws "coord" errors on
 * some data); colour a line by side with two series or area fills instead (winProb does). */
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
    model: tok('--c-model') || tok('--signal'), market: tok('--c-market'), other: tok('--c-other'), accent: tok('--accent'), brand: tok('--signal'), signal: tok('--signal'),
    wpA: tok('--wp-a'), wpB: tok('--wp-b'), c3: tok('--c-3'),
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
  if (o.nameAlign) a.nameTextStyle.align = o.nameAlign;
  /* only pass keys that are set: an explicit undefined overrides ECharts defaults (boundaryGap, min…) */
  ['min', 'max', 'interval', 'data', 'boundaryGap', 'position'].forEach(function (k) { if (o[k] !== undefined) a[k] = o[k]; });
  if (o.data) a.axisLabel.fontFamily = T.fontUI;
  if (o.show === false) { a.axisLabel.show = false; a.splitLine.show = false; }
  /* custom ticks: { values: [..], labels: [..] } puts labels at exactly those values. containLabel measures the
   * default ticks, not these, so QKC.mount widens the grid by the longest label (see fitTicks). */
  if (o.ticks && o.ticks.values && o.ticks.values.length) {
    var tv = o.ticks.values.slice(), tl = o.ticks.labels || null, f0 = o.fmt;
    a.axisLabel.customValues = tv;
    a.axisTick = { show: false, customValues: tv };
    a.axisLabel.hideOverlap = false;
    a.axisLabel.formatter = function (v) {
      for (var i = 0; i < tv.length; i++) if (Math.abs(tv[i] - v) < 1e-9 * Math.max(1, Math.abs(v))) return tl ? String(tl[i]) : (f0 ? f0(v) : String(v));
      return '';
    };
    a._ttMax = Math.max.apply(null, tv.map(function (v, i) { return String(tl ? tl[i] : (f0 ? f0(v) : v)).length; }));
  }
  return a;
}
/* Room for custom tick labels on y axes (containLabel cannot see them): ~6.4 px a character at 10.5 px. */
function fitTicks(opt) {
  if (!opt.grid) return;
  var grids = Array.isArray(opt.grid) ? opt.grid : [opt.grid];
  var ys = opt.yAxis ? (Array.isArray(opt.yAxis) ? opt.yAxis : [opt.yAxis]) : [];
  ys.forEach(function (a) {
    if (!a || !a._ttMax || (a.axisLabel && a.axisLabel.show === false)) return;
    var g = grids[a.gridIndex || 0];
    if (!g || g.containLabel === false) return;
    var extra = Math.round(a._ttMax * 6.4) + 4;
    if (a.position === 'right') g.right = (isNum(g.right) ? g.right : 0) + extra; else g.left = (isNum(g.left) ? g.left : 0) + extra;
  });
}
QKC.fitTicks = fitTicks;
/* Category labels on narrow charts: a 170 px name column leaves a phone's plot area ~120 px wide. The label
 * column takes at most ~40% of the chart's width (never under 64 px); wider charts keep the width asked for. */
function labelW(el, want) {
  var w = el && el.clientWidth ? el.clientWidth : 0;
  return w ? Math.max(64, Math.min(want, Math.round(w * 0.4))) : want;
}
QKC.labelW = labelW;
/* Axis titles: every axis says what it measures. A value axis across the bottom takes its title centred under
 * the ticks; one up the side takes it at the top end, as line and scatter do. Returns the grid room it needs. */
function nameAxis(a, name, where) {
  if (!name) return 0;
  var hidden = a.axisLabel && a.axisLabel.show === false;
  a.name = name;
  if (where === 'bottom') { a.nameLocation = 'middle'; a.nameGap = hidden ? 8 : 26; return hidden ? 14 : 22; }
  /* left-aligned from the axis line, so a long title runs over the plot instead of off the card's edge */
  a.nameLocation = a.inverse ? 'start' : 'end'; a.nameGap = 8; a.nameTextStyle.align = 'left';
  return 16;
}
QKC.nameAxis = nameAxis;
/* Legend entries that carry their own colour (per-point or per-bar colours, made v missed shots ...):
 * items [{ name, color, icon: 'roundRect' | 'circle' | 'line' }] -> empty series the legend can show. */
QKC.legendSeries = function (T, items) {
  return (items || []).map(function (it) {
    var c = it.color || T.other;
    return { type: it.icon === 'line' ? 'line' : 'scatter', name: it.name, data: [], silent: true, tooltip: { show: false },
      itemStyle: { color: c, borderColor: it.border || c }, lineStyle: { color: c, width: 2 }, symbol: it.icon === 'line' ? 'none' : (it.icon || 'roundRect') };
  });
};
var LINE_ICON = 'path://M0,4L12,4L12,6.5L0,6.5Z';
function legendOpt(T, o, items) {
  var l = { top: 0, left: 0, icon: 'roundRect', itemWidth: 10, itemHeight: 10, textStyle: { color: T.ink2 }, type: 'scroll', pageTextStyle: { color: T.ink3 }, pageIconColor: T.ink2, pageIconInactiveColor: T.ink4 };
  if (o) Object.keys(o).forEach(function (k) { l[k] = o[k]; });
  /* legend items drawn as a line (a market tick, a reference) get a line icon */
  if (items && l.data) l.data = l.data.map(function (n) { var it = items.filter(function (x) { return x.name === n; })[0]; return it && it.icon === 'line' ? { name: n, icon: LINE_ICON } : n; });
  return l;
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
    var opt = entry.build(T, entry);   /* entry.build: a page may wrap the build after drawing */
    var b = base(T);
    Object.keys(opt).forEach(function (k) { b[k] = opt[k]; });
    fitTicks(b);
    chart.setOption(b, true);
  }
  entry.paint = paint;
  paint();
  if (o.onClick) chart.on('click', o.onClick);
  else chart.on('click', function (p) { var d = p.data || {}; if (d && d.href) root.location.href = d.href; });
  var bucket = function () { var w = el.clientWidth || 0; return w < 420 ? 0 : w < 720 ? 1 : 2; }, lastB = bucket();
  if (root.ResizeObserver) { entry.ro = new ResizeObserver(function () { var b = bucket(); if (b !== lastB) { lastB = b; paint(); } chart.resize(); }); entry.ro.observe(el); }
  else root.addEventListener('resize', function () { chart.resize(); });
  el.__qkc = entry; REG.push(entry);
  return chart;
};
QK.theme.onChange(function () {
  /* tokens change with the theme: repaint every live chart after the CSS swap lands */
  setTimeout(function () { REG = REG.filter(function (e) { return e.el.isConnected; }); REG.forEach(function (e) { e.paint(); }); }, 30);
});

/* ─────────────────────────────────────── line / area */
/* spec: { x: [...], xType: 'category'|'value'|'time', series: [{ name, data, color, area, dash, width, href, label,
 *           band: { lo: [..], hi: [..] }       shaded interval in the series colour (±1 se, 80% range ...)
 *           err: [..] | lo: [..], hi: [..]     error bars: half-widths, or absolute bounds per point
 *           symbols: true }],
 *         yFmt, xFmt, xMin, xMax, yMin, yMax, yName, xName, yScale, yInverse: true (ranks: 1 at the top),
 *         ref: { y, label } | { x, label }, endLabels: true, legend: false, step, smooth,
 *         bands: [{ x, lo, hi, color, name }]  (bands not tied to one series) }
 * With xType 'value' or 'time', data may be plain y values (zipped with x) or [x, y] pairs. */
QKC.line = function (el, s) {
  return QKC.mount(el, function (T) {
    var numX = s.xType === 'value' || s.xType === 'time';
    function pts(arr, xs) {
      xs = xs || s.x;
      if (!numX) return arr;
      return (arr || []).map(function (v, j) { return Array.isArray(v) ? v : [xs ? xs[j] : j, v]; });
    }
    var extra = [];
    var ser = s.series.map(function (x, i) {
      var c = x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8];
      var hasErr = !!(x.err || (x.lo && x.hi));
      if (x.band && x.band.lo && x.band.hi) extra.push(bandSeries(T, x.band.lo, x.band.hi, x.band.x || s.x, numX, x.band.color || c, x.name));
      if (hasErr) extra.push(errSeries(T, x, s.x, numX, c));
      return {
        type: 'line', name: x.name, data: pts(x.data), showSymbol: !!(x.symbols || hasErr), symbol: 'circle', symbolSize: hasErr ? 6 : 8, smooth: s.smooth ? 0.25 : false, step: s.step || false, z: 3,
        lineStyle: { width: x.width || 2, color: c, type: x.dash ? 'dashed' : 'solid', cap: 'round', join: 'round' },
        itemStyle: { color: c, borderColor: T.s1, borderWidth: hasErr ? 1 : 2 },
        emphasis: { focus: 'series', lineStyle: { width: (x.width || 2) + 1 } },
        areaStyle: x.area || s.area ? { color: new root.echarts.graphic.LinearGradient(0, s.yInverse ? 1 : 0, 0, s.yInverse ? 0 : 1, [{ offset: 0, color: hexA(c, 0.28) }, { offset: 1, color: hexA(c, 0) }]) } : undefined,
        endLabel: s.endLabels !== false && s.series.length > 1 ? { show: true, formatter: x.label || x.name, color: T.ink2, fontFamily: T.fontUI, fontSize: 11, fontWeight: 600, distance: 6 } : undefined,
        labelLayout: { moveOverlap: 'shiftY' },
        markLine: i === 0 && s.ref ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3], width: 1 }, label: { color: T.ink3, fontSize: 10, formatter: s.ref.label || '', position: 'insideEndTop' }, data: [isNum(s.ref.x) || (s.ref.x !== undefined && s.ref.y === undefined) ? { xAxis: s.ref.x } : { yAxis: s.ref.y }] } : undefined
      };
    });
    (s.bands || []).forEach(function (b, k) { extra.unshift(bandSeries(T, b.lo, b.hi, b.x || s.x, numX, b.color || T.cat[k % 8], b.name)); });
    var below = extra.filter(function (e) { return e._band; }), above = extra.filter(function (e) { return !e._band; });
    var extraBefore = below.length;
    var xa = axis(T, { type: s.xType || 'category', data: numX ? undefined : s.x, split: false, line: true, fmt: s.xFmt, boundaryGap: numX ? undefined : false, min: s.xMin !== undefined ? s.xMin : (numX ? 'dataMin' : undefined), max: s.xMax !== undefined ? s.xMax : (numX ? 'dataMax' : undefined), name: s.xName, nameLocation: 'middle', nameGap: 28, ticks: s.xTicks });
    var ya = axis(T, { fmt: s.yFmt, min: s.yMin, max: s.yMax, name: s.yName, scale: s.yScale, inverse: !!s.yInverse, ticks: s.yTicks, interval: s.yInterval, nameLocation: s.yInverse ? 'start' : 'end', nameAlign: 'left' });
    return {
      grid: { left: 8, right: s.series.length > 1 && s.endLabels !== false ? 92 : 16, top: s.yName ? 30 : 14, bottom: s.xName ? 30 : 8, containLabel: true },
      legend: s.legend ? legendOpt(T, { right: 0, left: 'auto', itemWidth: 12, itemHeight: 3, data: s.series.map(function (x) { return x.name; }) }) : undefined,
      xAxis: xa,
      yAxis: ya,
      tooltip: tooltip(T, {
        trigger: 'axis',
        formatter: function (ps) {
          ps = ps.filter(function (p) { return p.seriesType === 'line' && p.seriesName && String(p.seriesName).charAt(0) !== '_'; });
          if (!ps.length) return '';
          var xv = ps[0].axisValue;
          var head = '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(s.xLabel ? s.xLabel(xv) : (numX && s.xFmt ? s.xFmt(xv) : ps[0].axisValueLabel)) + '</div>';
          var dir = s.yInverse ? -1 : 1;
          return head + ps.slice().sort(function (a, b) { return dir * ((val(b) || 0) - (val(a) || 0)); }).map(function (p) {
            var x = s.series[p.seriesIndex - extraBefore] || {};
            var v = val(p), txt = s.yFmt ? s.yFmt(v) : fmt.num(v, 1);
            var j = p.dataIndex;
            if (x.err && isNum(x.err[j])) txt += ' ± ' + (s.yFmt ? s.yFmt(x.err[j]) : fmt.num(x.err[j], 1));
            else if (x.lo && x.hi && isNum(x.lo[j]) && isNum(x.hi[j])) txt += ' (' + (s.yFmt ? s.yFmt(x.lo[j]) : fmt.num(x.lo[j], 1)) + '–' + (s.yFmt ? s.yFmt(x.hi[j]) : fmt.num(x.hi[j], 1)) + ')';
            else if (x.band && x.band.lo && isNum(x.band.lo[j]) && isNum(x.band.hi[j])) txt += ' (' + (s.yFmt ? s.yFmt(x.band.lo[j]) : fmt.num(x.band.lo[j], 1)) + '–' + (s.yFmt ? s.yFmt(x.band.hi[j]) : fmt.num(x.band.hi[j], 1)) + ')';
            return tipRow(p.color, p.seriesName, txt);
          }).join('');
        }
      }),
      series: below.concat(ser).concat(above)
    };
  }, { label: s.label });
};
/* A shaded interval [lo, hi] as one polygon (works on category and numeric axes, gaps split it). */
function bandSeries(T, lo, hi, xs, numX, c, name) {
  var n = Math.min(lo.length, hi.length), data = [];
  for (var j = 0; j < n; j++) {
    var x = numX ? (xs ? xs[j] : j) : j;
    if (isNum(lo[j]) && isNum(hi[j])) { data.push([x, lo[j], j]); data.push([x, hi[j], j]); }
  }
  return {
    type: 'custom', name: '_band' + (name || ''), _band: true, silent: true, tooltip: { show: false }, z: 1, data: data, encode: { x: 0, y: 1 },
    renderItem: function (params, api) {
      if (params.dataIndex !== 0) return null;
      var runs = [], cur = [], last = -2;
      for (var k = 0; k < data.length; k += 2) {
        var j = data[k][2];
        if (j !== last + 1 && cur.length) { runs.push(cur); cur = []; }
        cur.push([data[k][0], data[k][1], data[k + 1][1]]); last = j;
      }
      if (cur.length) runs.push(cur);
      return { type: 'group', children: runs.filter(function (r) { return r.length > 1; }).map(function (r) {
        var top = r.map(function (q) { return api.coord([q[0], q[2]]); }), bot = r.slice().reverse().map(function (q) { return api.coord([q[0], q[1]]); });
        return { type: 'polygon', shape: { points: top.concat(bot) }, style: { fill: hexA(c, 0.16), stroke: null } };
      }) };
    }
  };
}
/* Error bars with caps: x.err (half-widths) or x.lo / x.hi (absolute bounds), at each point of a series. */
function errSeries(T, x, xs, numX, c) {
  var data = [];
  (x.data || []).forEach(function (v, j) {
    var px = Array.isArray(v) ? v[0] : (numX ? (xs ? xs[j] : j) : j), py = Array.isArray(v) ? v[1] : v;
    var lo = x.err ? (isNum(x.err[j]) ? py - x.err[j] : null) : x.lo[j], hi = x.err ? (isNum(x.err[j]) ? py + x.err[j] : null) : x.hi[j];
    if (isNum(py) && isNum(lo) && isNum(hi)) data.push([px, lo, hi]);
  });
  return {
    type: 'custom', name: '_err' + (x.name || ''), silent: true, tooltip: { show: false }, z: 2, data: data, encode: { x: 0, y: [1, 2] },
    renderItem: function (params, api) {
      var a = api.coord([api.value(0), api.value(1)]), b = api.coord([api.value(0), api.value(2)]), w = 4;
      var st = { stroke: hexA(c, 0.85), lineWidth: 1.4 };
      return { type: 'group', children: [
        { type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: st },
        { type: 'line', shape: { x1: a[0] - w, y1: a[1], x2: a[0] + w, y2: a[1] }, style: st },
        { type: 'line', shape: { x1: b[0] - w, y1: b[1], x2: b[0] + w, y2: b[1] }, style: st }
      ] };
    }
  };
}
function val(p) { var v = p.value; return Array.isArray(v) ? v[v.length - 1] : v; }
function hexA(hex, a) { var c = QK.color.parse(hex); return c ? 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')' : hex; }
QKC.hexA = hexA;

/* ─────────────────────────────────────── bar (vertical or horizontal) */
/* spec: { cats: [...], series: [{ name, data, color, lo: [..], hi: [..] (whiskers), market: [..] (market tick) }],
 *         horizontal, stack, fmt, colors: [per-bar], hrefs: [...], labels: true (value at bar end), max, min,
 *         diverging (colour by sign), legend: true, legendItems: [{ name, color }] (entries for per-bar colours),
 *         marketName: 'Market', labelWidth, valTicks: { values, labels },
 *         valName / catName (axis titles; or xName / yName by position) } */
QKC.bar = function (el, s) {
  return QKC.mount(el, function (T, ent) {
    var hz = !!s.horizontal;
    var nS = s.series.length;
    var ser = s.series.map(function (x, i) {
      var c = x.color === 'model' ? T.model : x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8];
      return {
        type: 'bar', name: x.name, stack: s.stack ? 'a' : undefined, barMaxWidth: hz ? 16 : 28, barCategoryGap: '30%', barGap: '20%',
        itemStyle: { color: s.diverging ? T.pos : c },
        data: x.data.map(function (v, j) {
          var cc = s.diverging ? (v >= 0 ? T.pos : T.neg) : (s.colors && s.colors[j] ? QK.color.ensure(s.colors[j], T.s1, 3) : c);
          return { value: v, href: s.hrefs ? s.hrefs[j] : undefined, itemStyle: { color: cc, borderRadius: hz ? (v < 0 ? [4, 0, 0, 4] : [0, 4, 4, 0]) : (v < 0 ? [0, 0, 4, 4] : [4, 4, 0, 0]) } };
        }),
        label: s.labels ? { show: true, position: hz ? 'right' : 'top', distance: x.hi || x.market ? 8 : 5, color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: function (p) { return s.fmt ? s.fmt(p.value) : fmt.num(p.value, 1); } } : undefined,
        emphasis: { itemStyle: { shadowBlur: 0, opacity: 1 }, focus: 'none' },
        cursor: s.hrefs ? 'pointer' : 'default'
      };
    });
    /* whiskers and market ticks sit on their bar: same slot maths as ECharts' grouped bars */
    var marks = [];
    s.series.forEach(function (x, i) {
      if (!(x.lo && x.hi) && !x.market) return;
      var slot = s.stack ? 0 : i, slots = s.stack ? 1 : nS;
      var data = [];
      x.data.forEach(function (v, j) {
        var lo = x.lo ? x.lo[j] : null, hi = x.hi ? x.hi[j] : null, m = x.market ? x.market[j] : null;
        if (!isNum(lo) && !isNum(m)) return;
        data.push([j, isNum(lo) ? lo : m, isNum(hi) ? hi : m, isNum(m) ? m : NaN, isNum(lo) ? 1 : 0]);
      });
      marks.push({
        type: 'custom', name: '_marks' + i, silent: true, tooltip: { show: false }, z: 4, data: data,
        encode: hz ? { y: 0, x: [1, 2, 3] } : { x: 0, y: [1, 2, 3] },
        renderItem: function (params, api) {
          var j = api.value(0), catW = hz ? api.size([0, 1])[1] : api.size([1, 0])[0];
          var band = catW * 0.7, w = Math.min(band / (slots + (slots - 1) * 0.2), hz ? 16 : 28), tot = slots * w + (slots - 1) * 0.2 * w;
          var off = -tot / 2 + slot * 1.2 * w + w / 2;
          function pt(v) { var q = hz ? api.coord([v, j]) : api.coord([j, v]); if (hz) q[1] += off; else q[0] += off; return q; }
          var kids = [], cap = Math.max(3, w * 0.28);
          if (api.value(4)) {
            var a = pt(api.value(1)), b = pt(api.value(2)), st = { stroke: T.ink2, lineWidth: 1.4 };
            kids.push({ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: st });
            [a, b].forEach(function (e) { kids.push({ type: 'line', shape: hz ? { x1: e[0], y1: e[1] - cap, x2: e[0], y2: e[1] + cap } : { x1: e[0] - cap, y1: e[1], x2: e[0] + cap, y2: e[1] }, style: st }); });
          }
          var mv = api.value(3);
          if (isNum(mv)) {
            var mp = pt(mv), half = w / 2 + 3;
            kids.push({ type: 'line', shape: hz ? { x1: mp[0], y1: mp[1] - half, x2: mp[0], y2: mp[1] + half } : { x1: mp[0] - half, y1: mp[1], x2: mp[0] + half, y2: mp[1] }, style: { stroke: T.market, lineWidth: 2.5, lineCap: 'round' } });
          }
          return { type: 'group', children: kids };
        }
      });
    });
    var anyMarket = s.series.some(function (x) { return !!x.market; });
    var legendItems = (s.legendItems || []).map(function (it) { return it.color === 'model' || it.color === 'ink' ? { name: it.name, color: it.color === 'model' ? T.model : T.ink2, icon: it.icon } : it; });
    if (anyMarket && (s.legend || legendItems.length)) legendItems.push({ name: s.marketName || 'Market', color: T.market, icon: 'line' });
    var catAx = axis(T, { type: 'category', data: s.cats, split: false, line: !hz, inverse: hz });
    catAx.axisLabel.color = T.ink2; catAx.axisLabel.fontSize = 11; catAx.axisLabel.width = hz ? labelW(ent.el, s.labelWidth || 110) : (s.labelWidth || 110); catAx.axisLabel.overflow = 'truncate';
    var valAx = axis(T, { fmt: s.fmt, max: s.max, min: s.min, ticks: s.valTicks });
    if (s.labels && hz) { valAx.axisLabel.show = false; valAx.splitLine.show = false; }
    var showLegend = !!s.legend || legendItems.length > 0;
    /* axis titles: valName / catName, or xName / yName by position. The bottom axis takes its title under the
     * ticks; the side axis at its top end, below the legend when there is one. */
    var vN = s.valName || (hz ? s.xName : s.yName), cN = s.catName || (hz ? s.yName : s.xName);
    var gB = 6 + nameAxis(hz ? valAx : catAx, hz ? vN : cN, 'bottom');
    var gT = (showLegend ? 30 : 10) + nameAxis(hz ? catAx : valAx, hz ? cN : vN, 'side');
    return {
      grid: { left: 8, right: s.labels && hz ? 52 : (hz ? 26 : 12), top: gT, bottom: gB, containLabel: true },
      legend: showLegend ? legendOpt(T, { data: (s.legend ? s.series.map(function (x) { return x.name; }) : []).concat(legendItems.map(function (it) { return it.name; })) }, legendItems) : undefined,
      xAxis: hz ? valAx : catAx, yAxis: hz ? catAx : valAx,
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, T.dark ? 0.05 : 0.04) } },
        formatter: function (ps) {
          ps = ps.filter(function (p) { return p.seriesType === 'bar'; });
          if (!ps.length) return '';
          return '<div style="font-weight:600;margin-bottom:4px">' + esc(ps[0].name) + '</div>' + ps.map(function (p) {
            var x = s.series[p.seriesIndex] || {}, j = p.dataIndex, f = s.fmt || function (v) { return fmt.num(v, 2); };
            var txt = f(p.value);
            if (x.lo && x.hi && isNum(x.lo[j]) && isNum(x.hi[j])) txt += ' (' + f(x.lo[j]) + '–' + f(x.hi[j]) + ')';
            var row = tipRow(p.color, p.seriesName || '', txt);
            if (x.market && isNum(x.market[j])) row += tipRow(T.market, s.marketName || 'Market', f(x.market[j]));
            return row;
          }).join('');
        } }),
      series: ser.concat(marks).concat(QKC.legendSeries(T, legendItems))
    };
  }, { label: s.label });
};

/* ─────────────────────────────────────── dumbbell: model v market (or any A v B on one scale) */
/* spec: { rows: [{ label, a, b, href, sub }], aName: 'Model', bName: 'Market', fmt: QK.fmt.pct, min: 0, max: 1,
 *         valName (axis title; 'Probability' by default when fmt is a percentage) } */
QKC.dumbbell = function (el, s) {
  var rows = s.rows;
  return QKC.mount(el, function (T, ent) {
    var cats = rows.map(function (r) { return r.label; });
    var aN = s.aName || 'Our model', bN = s.bName || 'Market';
    var f = s.fmt || fmt.pct;
    /* the value axis says what it measures: a probability unless the caller names it (valName / xName) */
    var vName = s.valName || s.xName || (!s.fmt || s.fmt === fmt.pct ? 'Probability' : '');
    var xa = axis(T, { min: isNum(s.min) ? s.min : 0, max: isNum(s.max) ? s.max : 1, fmt: function (v) { return f(v, 0); } });
    var ya = axis(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = labelW(ent.el, s.labelWidth || 170); ya.axisLabel.overflow = 'truncate'; ya.axisLabel.fontSize = 11;
    var gB = 6 + nameAxis(xa, vName, 'bottom');
    return {
      grid: { left: 8, right: 20, top: 26, bottom: gB, containLabel: true },
      legend: { top: 0, left: 0, itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2 }, data: [{ name: aN, icon: 'circle' }, { name: bN, icon: 'emptyCircle' }] },
      xAxis: xa,
      yAxis: ya,
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, 0.04) } },
        formatter: function (ps) {
          var r = rows[ps[0].dataIndex];
          return '<div style="font-weight:600;margin-bottom:4px;max-width:240px;white-space:normal">' + esc(r.label) + '</div>' + (r.sub ? '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(r.sub) + '</div>' : '') +
            tipRow(T.model, aN, f(r.a)) + tipRow(T.market, bN, f(r.b));
        } }),
      series: [
        { type: 'custom', name: 'gap', silent: true, z: 1,
          renderItem: function (params, api) {
            var y = api.value(2), p1 = api.coord([api.value(0), y]), p2 = api.coord([api.value(1), y]);
            return { type: 'line', shape: { x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] }, style: { stroke: hexA(T.ink3, 0.35), lineWidth: 2, lineCap: 'round' } };
          },
          data: rows.map(function (r, i) { return [r.a, r.b, i]; }), encode: { x: [0, 1], y: 2 } },
        { type: 'scatter', name: bN, z: 2, symbol: 'emptyCircle', symbolSize: 8, itemStyle: { color: T.market, borderColor: T.market, borderWidth: 2 }, data: rows.map(function (r, i) { return { value: [r.b, i], href: r.href }; }) },
        { type: 'scatter', name: aN, z: 3, symbolSize: 13, itemStyle: { color: T.model, borderColor: T.s1, borderWidth: 2 }, data: rows.map(function (r, i) { return { value: [r.a, i], href: r.href }; }) }
      ]
    };
  }, { label: s.label || (s.aName || 'Our model') + ', with ' + (s.bName || 'the market') + ' for reference' });
};

/* ─────────────────────────────────────── scatter */
/* spec: { points: [{ x, y, name, color, size, href, label }], xName, yName, xFmt, yFmt, refX, refY,
 *         quadrants: ['top-left text', 'top-right', 'bottom-left', 'bottom-right'], labelTop: 6,
 *         yInverse / xInverse (ranks: 1 at the top), diagonal: true | { label } (the y = x line, e.g. model v actual),
 *         legendItems: [{ name, color }] (what the point colours mean) } */
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
    if (s.diagonal) {
      var xs0 = pts.map(function (p) { return p.x; }).filter(isNum), ys0 = pts.map(function (p) { return p.y; }).filter(isNum);
      var lo0 = Math.min.apply(null, xs0.concat(ys0)), hi0 = Math.max.apply(null, xs0.concat(ys0));
      if (isNum(s.xMin) && isNum(s.yMin)) lo0 = Math.min(s.xMin, s.yMin);
      if (isNum(s.xMax) && isNum(s.yMax)) hi0 = Math.max(s.xMax, s.yMax);
      if (isNum(lo0) && isNum(hi0)) ml.push([{ coord: [lo0, lo0], label: { show: !!s.diagonal.label, formatter: s.diagonal.label || '', position: 'insideEndTop', color: T.ink3, fontSize: 10 } }, { coord: [hi0, hi0] }]);
    }
    var legendItems = s.legendItems || [];
    var gr = { left: 8, right: 24, top: legendItems.length ? 34 : 28, bottom: 26, containLabel: true };
    return {
      grid: gr,
      legend: legendItems.length ? legendOpt(T, { icon: 'circle', left: 'auto', right: 0, data: legendItems.map(function (it) { return it.name; }) }) : undefined,
      xAxis: axis(T, { fmt: s.xFmt, name: s.xName, nameLocation: 'middle', nameGap: 30, scale: true, min: s.xMin, max: s.xMax, inverse: !!s.xInverse, ticks: s.xTicks }),
      yAxis: axis(T, { fmt: s.yFmt, name: s.yName, scale: true, min: s.yMin, max: s.yMax, inverse: !!s.yInverse, ticks: s.yTicks, nameLocation: s.yInverse ? 'start' : 'end', nameAlign: 'left' }),
      tooltip: tooltip(T, { formatter: function (p) { if (p.seriesIndex !== 0 || p.componentType !== 'series') return ''; var d = pts[p.dataIndex]; return '<div style="font-weight:600;margin-bottom:4px">' + esc(d.name) + '</div>' + tipRow(p.color, s.xName || 'x', s.xFmt ? s.xFmt(d.x) : fmt.num(d.x, 2)) + tipRow(p.color, s.yName || 'y', s.yFmt ? s.yFmt(d.y) : fmt.num(d.y, 2)); } }),
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
      }].concat(QKC.legendSeries(T, legendItems.map(function (it) { return { name: it.name, color: it.color, icon: 'circle' }; })))
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
/* spec: { x: [...], y: [...], data: [[xi, yi, v], ...], diverging: true, mid: 0, min, max, fmt, cellLabels: true,
 *         labelMin: n (label only cells at least n from the midpoint, or n and above on a sequential scale),
 *         labelIf: fn(v) -> bool, xName, yName (axis titles) }  Label ink is black or white, whichever reads on that cell's colour. */
QKC.heatmap = function (el, s) {
  return QKC.mount(el, function (T) {
    var vals = s.data.map(function (d) { return d[2]; }).filter(isNum);
    var lo = isNum(s.min) ? s.min : Math.min.apply(null, vals), hi = isNum(s.max) ? s.max : Math.max.apply(null, vals);
    if (s.diverging) { var m = Math.max(Math.abs(lo - (s.mid || 0)), Math.abs(hi - (s.mid || 0))); lo = (s.mid || 0) - m; hi = (s.mid || 0) + m; }
    var xa = axis(T, { type: 'category', data: s.x, split: false }); xa.splitArea = { show: false }; xa.axisLabel.color = T.ink2; xa.position = 'top';
    var ya = axis(T, { type: 'category', data: s.y, split: false, inverse: true }); ya.axisLabel.color = T.ink2;
    if (s.xName) { xa.name = s.xName; xa.nameLocation = 'middle'; xa.nameGap = 24; }
    if (s.yName) { ya.name = s.yName; ya.nameLocation = 'middle'; ya.nameRotate = 90; ya.nameGap = Math.min(90, 14 + 6.4 * Math.max.apply(null, (s.y || ['']).map(function (v) { return String(v).length; }))); }
    var ramp = s.diverging ? [T.neg, T.mid, T.pos] : T.seq;
    function cellColour(v) {
      var t = hi > lo ? Math.max(0, Math.min(1, (v - lo) / (hi - lo))) : 0.5, k = t * (ramp.length - 1), i0 = Math.min(ramp.length - 2, Math.floor(k));
      return QK.color.mix(ramp[i0], ramp[i0 + 1], k - i0);
    }
    function labelled(v) {
      if (!isNum(v) || s.cellLabels === false) return false;
      if (s.labelIf) return !!s.labelIf(v);
      if (isNum(s.labelMin)) return s.diverging ? Math.abs(v - (s.mid || 0)) >= s.labelMin : v >= s.labelMin;
      return true;
    }
    var cells = s.data.map(function (d) {
      var v = d[2];
      return { value: d, label: { show: labelled(v), color: isNum(v) ? QK.color.ink(cellColour(v)) : T.ink1 } };
    });
    return {
      grid: { left: s.yName ? 24 : 8, right: 8, top: s.xName ? 44 : 26, bottom: 44, containLabel: true },
      xAxis: xa, yAxis: ya,
      visualMap: { min: lo, max: hi, calculable: false, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: 160,
        textStyle: { color: T.ink3, fontFamily: T.fontNum, fontSize: 10 }, formatter: function (v) { return s.fmt ? s.fmt(v) : fmt.num(v, 1); },
        inRange: { color: s.diverging ? [T.neg, T.mid, T.pos] : (T.dark ? T.seq : T.seq) } },
      tooltip: tooltip(T, { formatter: function (p) { return '<div style="font-weight:600">' + esc(s.y[p.value[1]]) + ' · ' + esc(s.x[p.value[0]]) + '</div><div style="font-family:var(--font-num)">' + esc(s.fmt ? s.fmt(p.value[2]) : fmt.num(p.value[2], 2)) + '</div>'; } }),
      series: [{ type: 'heatmap', data: cells, itemStyle: { borderColor: T.s1, borderWidth: 2, borderRadius: 3 },
        label: { show: s.cellLabels !== false, fontFamily: T.fontNum, fontSize: 10, color: T.ink1, formatter: function (p) { return s.fmt ? s.fmt(p.value[2]) : fmt.num(p.value[2], 1); } },
        emphasis: { itemStyle: { borderColor: T.ink1, borderWidth: 1 } } }]
    };
  }, { label: s.label });
};

/* ─────────────────────────────────────── win probability */
/* spec: { t: [game clock: minutes, seconds or ms timestamps], p: [home win prob 0-1], home: {name, abbr, colour},
 *         away: {…}, events: [{ t, p (optional), label }], periods: [t of each break], tMin, tMax,
 *         tFmt (axis labels), tLabel (tooltip head; defaults to tFmt), interval (axis step in t units),
 *         xType: 'value' (default) | 'time', step: true (hold each value until the next play),
 *         compare: { name, t, p } (a second, dashed curve: another model or the market),
 *         tName (x title, default 'Game time'), yName (default '<home> win probability'; '' for none) }
 * The x axis is numeric, so uneven play times sit where they happened. The line is ink; the fill above 50%
 * takes the home colour and below the away colour (two area series with origin 0.5; no piecewise
 * visualMap, which errors on line series in ECharts 5.5.1). Non-numeric t falls back to the play index. */
QKC.winProb = function (el, s) {
  var numeric = (s.t || []).every(function (x) { return isNum(x); });
  var ts = numeric ? s.t : (s.t || []).map(function (_, i) { return i; });
  var lab = numeric ? null : s.t;
  function tf(v) { if (lab) { var k = Math.round(v); return lab[k] !== undefined ? String(lab[k]) : ''; } return s.tFmt ? s.tFmt(v) : (s.xType === 'time' ? QK.fmt.time(new Date(v).toISOString()) : fmt.num(v, 0)); }
  function pAt(t) { var v = s.p[0]; for (var i = 0; i < ts.length && ts[i] <= t; i++) v = s.p[i]; if (!s.step) { var j = nearestIdx(ts, t); v = s.p[j]; } return v; }
  return QKC.mount(el, function (T) {
    var hc = s.home && s.home.colour ? QK.color.ensure(s.home.colour, T.s1, 3) : T.model;
    var ac = s.away && s.away.colour ? QK.color.ensure(s.away.colour, T.s1, 3) : T.market;
    if (!(QK.color.distinct ? QK.color.distinct(hc, ac) : QK.color.contrast(hc, ac) >= 1.6)) ac = T.wpB || T.market;
    var pts = ts.map(function (t, i) { return [t, s.p[i]]; }).filter(function (q) { return isNum(q[0]) && isNum(q[1]); });
    var step = s.step ? 'end' : false;
    var ev = (s.events || []).map(function (e) { var t = numeric ? e.t : nearestIdx(s.t, e.t); return { coord: [t, isNum(e.p) ? e.p : pAt(t)], name: e.label, value: e.label }; });
    function band(up, c) {
      return { type: 'line', name: '_wp' + (up ? 'h' : 'a'), step: step, data: pts.map(function (q) { return [q[0], up ? Math.max(0.5, q[1]) : Math.min(0.5, q[1])]; }), showSymbol: false, silent: true, z: 1,
        lineStyle: { width: 0, opacity: 0 }, areaStyle: { color: hexA(c, 0.24), origin: 0.5 }, tooltip: { show: false }, emphasis: { disabled: true } };
    }
    var hN = (s.home || {}).name || 'Home', aN = (s.away || {}).name || 'Away';
    var xa = axis(T, { type: s.xType === 'time' ? 'time' : 'value', split: false, line: true, fmt: tf, interval: s.interval,
      min: isNum(s.tMin) ? s.tMin : (pts.length ? pts[0][0] : undefined), max: isNum(s.tMax) ? s.tMax : (pts.length ? pts[pts.length - 1][0] : undefined), ticks: s.tTicks });
    var tName = s.tName === undefined ? 'Game time' : s.tName;
    var gB = 8 + nameAxis(xa, tName, 'bottom');
    var yN = s.yName === undefined ? (s.home ? (s.home.abbr || s.home.name) + ' win probability' : 'Win probability') : s.yName;
    return {
      grid: { left: 8, right: 28, top: yN ? 28 : 22, bottom: gB, containLabel: true },
      xAxis: xa,
      yAxis: axis(T, { name: yN, nameGap: 10, nameAlign: 'left', min: 0, max: 1, interval: 0.25, fmt: function (v) { return v === 0.5 ? '50%' : v === 1 ? (s.home ? (s.home.abbr || QK.fmt.initials(s.home.name)) : '100%') : v === 0 ? (s.away ? (s.away.abbr || QK.fmt.initials(s.away.name)) : '0%') : ''; } }),
      tooltip: tooltip(T, { trigger: 'axis', formatter: function (ps) {
        var t = ps[0].axisValue, p = pAt(t);
        var head = '<div style="color:' + T.ink3 + ';font-size:11px">' + esc(s.tLabel ? s.tLabel(t) : tf(t)) + '</div>';
        var cmp = ps.filter(function (q) { return q.seriesName === ((s.compare || {}).name || 'Compare'); })[0];
        return head + tipRow(hc, hN, fmt.pct(p)) + tipRow(ac, aN, fmt.pct(1 - p)) + (cmp ? tipRow(T.ink3, cmp.seriesName + ' · ' + hN, fmt.pct(val(cmp))) : '');
      } }),
      series: [
        band(true, hc), band(false, ac),
        {
          type: 'line', name: hN, data: pts, showSymbol: false, step: step, z: 5, lineStyle: { width: 2, color: T.ink1 }, itemStyle: { color: T.ink1 },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false },
            data: [{ yAxis: 0.5 }].concat((s.periods || []).map(function (x) { return { xAxis: numeric ? x : nearestIdx(s.t, x) }; })) },
          markPoint: ev.length ? { symbol: 'circle', symbolSize: 7, itemStyle: { color: T.brand, borderColor: T.s1, borderWidth: 2 },
            label: { show: true, position: 'top', color: T.ink2, fontSize: 10, fontWeight: 600, formatter: function (p) { return p.name || p.value; } }, data: ev } : undefined
        }
      ].concat(s.compare && s.compare.p && s.compare.p.length ? [{
        type: 'line', name: s.compare.name || 'Compare', silent: true, z: 4, showSymbol: false, step: step,
        data: (s.compare.t || ts).map(function (t, i) { return [t, s.compare.p[i]]; }), lineStyle: { width: 1.2, type: [3, 3], color: T.ink3 }, itemStyle: { color: T.ink3 }
      }] : [])
    };
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
    var made = s.colorMade || T.wpB || T.market, miss = s.colorMiss || T.wpA || T.model;
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
      legend: s.legend === false ? { show: false } : { top: 6, right: 8, icon: 'circle', itemWidth: 9, itemHeight: 9, textStyle: { color: T.ink2, fontSize: 11 } },
      series: [
        { type: 'scatter', name: s.missLabel || 'Shot', symbolSize: sz, data: pts(false), z: 2, itemStyle: { color: hexA(miss, 0.55), borderColor: miss, borderWidth: 1 } },
        { type: 'scatter', name: s.madeLabel || 'Goal', symbolSize: sz, data: pts(true), z: 3, itemStyle: { color: made, borderColor: T.s1, borderWidth: 1.5 } }
      ]
    };
  }, { label: s.label || 'Shot map' });
};

/* ─────────────────────────────────────── range: floor to ceiling, with a projection dot */
/* spec: { rows: [{ label, lo, hi, mid, href, sub, color }], fmt, min, max, loName: 'Floor', hiName: 'Ceiling',
 *         midName: 'Projection', labelWidth, ref: { x, label }, valName (axis title) } — horizontal, one row per player / team. */
QKC.range = function (el, s) {
  var rows = s.rows || [];
  return QKC.mount(el, function (T, ent) {
    var f = s.fmt || function (v) { return fmt.num(v, 1); };
    var mN = s.midName || 'Projection', loN = s.loName || 'Floor', hiN = s.hiName || 'Ceiling';
    var ya = axis(T, { type: 'category', data: rows.map(function (r) { return r.label; }), split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = labelW(ent.el, s.labelWidth || 150); ya.axisLabel.overflow = 'truncate'; ya.axisLabel.fontSize = 11;
    var xa = axis(T, { fmt: f, min: s.min, max: s.max, scale: !isNum(s.min) });
    var gB = 6 + nameAxis(xa, s.valName || s.xName, 'bottom');
    return {
      grid: { left: 8, right: 20, top: 26, bottom: gB, containLabel: true },
      legend: legendOpt(T, { icon: 'roundRect', data: [loN + '–' + hiN, mN] }),
      xAxis: xa,
      yAxis: ya,
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, 0.04) } },
        formatter: function (ps) {
          var r = rows[ps[0].dataIndex] || {};
          return '<div style="font-weight:600;margin-bottom:4px">' + esc(r.label) + '</div>' + (r.sub ? '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(r.sub) + '</div>' : '') +
            tipRow(T.other, hiN, f(r.hi)) + (isNum(r.mid) ? tipRow(T.model, mN, f(r.mid)) : '') + tipRow(T.other, loN, f(r.lo));
        } }),
      series: [
        { type: 'custom', name: loN + '–' + hiN, z: 2, itemStyle: { color: hexA(T.model, 0.35) },
          renderItem: function (params, api) {
            var y = api.value(2), a = api.coord([api.value(0), y]), b = api.coord([api.value(1), y]);
            var r = rows[params.dataIndex] || {}, c = r.color ? QK.color.ensure(r.color, T.s1, 3) : T.model, hgt = Math.min(12, api.size([0, 1])[1] * 0.5);
            return { type: 'rect', shape: { x: Math.min(a[0], b[0]), y: a[1] - hgt / 2, width: Math.max(2, Math.abs(b[0] - a[0])), height: hgt, r: hgt / 2 }, style: { fill: hexA(c, 0.32), stroke: hexA(c, 0.7), lineWidth: 1 } };
          },
          data: rows.map(function (r, i) { return { value: [r.lo, r.hi, i], href: r.href }; }), encode: { x: [0, 1], y: 2 } },
        { type: 'scatter', name: mN, z: 3, symbolSize: 10, itemStyle: { color: T.model, borderColor: T.s1, borderWidth: 2 },
          data: rows.map(function (r, i) { return { value: [isNum(r.mid) ? r.mid : null, i], href: r.href, itemStyle: r.color ? { color: QK.color.ensure(r.color, T.s1, 3), borderColor: T.s1, borderWidth: 2 } : undefined }; }),
          markLine: s.ref ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: !!s.ref.label, formatter: s.ref.label || '', color: T.ink3, fontSize: 10 }, data: [{ xAxis: s.ref.x }] } : undefined }
      ]
    };
  }, { label: s.label || 'Range from floor to ceiling' });
};

/* ─────────────────────────────────────── butterfly: two measures back to back on one category list */
/* spec: { cats: [...], left: { name, data, color }, right: { name, data, color }, fmt, labels: true, labelWidth, hrefs, valName }
 * e.g. offence v defence, home v away, for v against. Values are drawn outward from the middle. */
QKC.butterfly = function (el, s) {
  return QKC.mount(el, function (T, ent) {
    var f = s.fmt || function (v) { return fmt.num(v, 1); };
    var lc = s.left.color ? QK.color.ensure(s.left.color, T.s1, 3) : T.model, rc = s.right.color ? QK.color.ensure(s.right.color, T.s1, 3) : T.market;
    function side(x, c, neg) {
      return { type: 'bar', name: x.name, stack: 'bf', barMaxWidth: 16, barCategoryGap: '30%', itemStyle: { color: c },
        data: x.data.map(function (v, j) { return { value: isNum(v) ? (neg ? -Math.abs(v) : Math.abs(v)) : null, raw: v, href: s.hrefs ? s.hrefs[j] : undefined, itemStyle: { color: c, borderRadius: neg ? [4, 0, 0, 4] : [0, 4, 4, 0] } }; }),
        label: s.labels !== false ? { show: true, position: neg ? 'left' : 'right', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: function (p) { return isNum(p.data.raw) ? f(p.data.raw) : ''; } } : undefined,
        emphasis: { focus: 'none' }, cursor: s.hrefs ? 'pointer' : 'default' };
    }
    var all = s.left.data.concat(s.right.data).filter(isNum).map(Math.abs), m = all.length ? Math.max.apply(null, all) : 1;
    var ya = axis(T, { type: 'category', data: s.cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = labelW(ent.el, s.labelWidth || 110); ya.axisLabel.overflow = 'truncate'; ya.axisLabel.fontSize = 11;
    var xa = axis(T, { min: -m * 1.18, max: m * 1.18, fmt: function (v) { return f(Math.abs(v)); } });
    if (s.labels !== false) { xa.axisLabel.show = false; xa.splitLine.show = false; }
    var gB = 6 + nameAxis(xa, s.valName || s.xName, 'bottom');
    return {
      grid: { left: 8, right: 12, top: 30, bottom: gB, containLabel: true },
      legend: legendOpt(T, { data: [s.left.name, s.right.name] }),
      xAxis: xa, yAxis: ya,
      tooltip: tooltip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: hexA(T.ink1, 0.04) } },
        formatter: function (ps) { return '<div style="font-weight:600;margin-bottom:4px">' + esc(ps[0].name) + '</div>' + ps.map(function (p) { return tipRow(p.color, p.seriesName, isNum(p.data.raw) ? f(p.data.raw) : '—'); }).join(''); } }),
      series: [side(s.left, lc, true), side(s.right, rc, false)].map(function (x, i) {
        if (i === 0) x.markLine = { silent: true, symbol: 'none', lineStyle: { color: T.axis, width: 1 }, label: { show: false }, data: [{ xAxis: 0 }] };
        return x;
      })
    };
  }, { label: s.label });
};

/* ─────────────────────────────────────── Plotly migration shim */
/* Old views written against Plotly: load the kit's optional module assets/qk/plotly-ec.js (after this file).
 * It defines window.Plotly (newPlot, react, purge, relayout, Plots.resize, on('plotly_click')) on ECharts and
 * these tokens, so the Plotly CDN bundle is never needed. plotlyLayout() keeps the token layout for code that
 * still builds Plotly layouts by hand. */
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

/* ═══════════════════════════════════════ v2 "Signal" charts ═══ */

/* ─────────────────────────────────────── forecast over time (538 style) */
/* QKC.forecast(el, { x: [...], xType: 'time' (ISO dates or ms) | 'category' | 'value',
 *   series: [{ name, data: [..] (0-1 for chances), color, label (end label; default the name), band: { lo, hi },
 *              ours: true (the signal colour, a heavier line), dash }],
 *   annotations: [{ x, label }]   dashed verticals labelled at the top (trades, injuries, a goal, the deadline ...)
 *   today: x (a solid "Today" rule) · split: { x, label } (shade what follows as a projection)
 *   yFmt (default a percentage), yMin, yMax (default 0 and 1 for chances; 'auto' to fit), yName, xName, label })
 * Lines carry their own end labels with the last value ("BOS 34%"), so there is no legend. */
QKC.forecast = function (el, s) {
  return QKC.mount(el, function (T, ent) {
    var numX = s.xType === 'time' || s.xType === 'value';
    var xs = (s.x || []).map(function (v) { return s.xType === 'time' && !isNum(v) ? new Date(v).getTime() : v; });
    var yF = s.yFmt || function (v) { return fmt.pct(v, 0); };
    function pts(arr) { return numX ? (arr || []).map(function (v, j) { return [xs[j], v]; }) : arr; }
    function xv(v) { return s.xType === 'time' && !isNum(v) ? new Date(v).getTime() : v; }
    var narrow = ent.el.clientWidth && ent.el.clientWidth < 520;
    var bands = [], lines = [];
    (s.series || []).forEach(function (x, i) {
      var c = x.ours ? T.model : (x.color ? QK.color.ensure(x.color, T.s1, 3) : T.cat[i % 8]);
      if (x.band && x.band.lo && x.band.hi) bands.push(bandSeries(T, x.band.lo, x.band.hi, xs, numX, c, x.name));
      var last = null;
      for (var j = (x.data || []).length - 1; j >= 0; j--) if (isNum(x.data[j])) { last = x.data[j]; break; }
      lines.push({
        type: 'line', name: x.name, data: pts(x.data), showSymbol: false, symbol: 'circle', symbolSize: 7, z: x.ours ? 6 : 4, connectNulls: false,
        lineStyle: { width: x.ours ? 3 : 2, color: c, type: x.dash ? [5, 4] : 'solid', cap: 'round', join: 'round' }, itemStyle: { color: c, borderColor: T.s1, borderWidth: 2 },
        emphasis: { focus: 'series', lineStyle: { width: (x.ours ? 3 : 2) + 1 } },
        endLabel: s.endLabels === false ? undefined : { show: true, color: c, fontFamily: T.fontUI, fontSize: 11, fontWeight: 700, distance: 6,
          formatter: function () { return (x.label || x.name) + (isNum(last) && !narrow ? ' ' + yF(last) : ''); } },
        labelLayout: { moveOverlap: 'shiftY' }
      });
    });
    /* annotations, today and the projection split ride on the first line as markLine / markArea */
    var ml = [];
    (s.annotations || []).forEach(function (a, k) {
      ml.push({ xAxis: numX ? xv(a.x) : a.x, lineStyle: { color: T.ink3, type: [3, 4], width: 1 },
        label: { show: true, formatter: a.label, position: 'end', rotate: 0, color: T.ink2, fontSize: 10, fontWeight: 600, fontFamily: T.fontUI, distance: k % 2 ? 16 : 4 } });
    });
    if (s.today !== undefined && s.today !== null) ml.push({ xAxis: numX ? xv(s.today) : s.today, lineStyle: { color: T.ink2, type: 'solid', width: 1 }, label: { show: true, formatter: 'Today', position: 'end', rotate: 0, color: T.ink1, fontSize: 10, fontWeight: 700, distance: 4 } });
    if (lines.length) {
      if (ml.length) lines[0].markLine = { silent: true, symbol: 'none', animation: false, data: ml };
      if (s.split && s.split.x !== undefined) lines[0].markArea = { silent: true, itemStyle: { color: hexA(T.ink1, T.dark ? 0.035 : 0.04) }, label: { show: !!s.split.label, position: 'insideTopRight', color: T.ink3, fontSize: 10, fontWeight: 600, formatter: s.split.label || '' },
        data: [[{ xAxis: numX ? xv(s.split.x) : s.split.x }, { xAxis: numX ? (isNum(xs[xs.length - 1]) ? xs[xs.length - 1] : 'max') : s.x[s.x.length - 1] }]] };
    }
    var chance = !s.yFmt;
    var xa = axis(T, { type: s.xType === 'time' ? 'time' : (numX ? 'value' : 'category'), data: numX ? undefined : s.x, split: false, line: true, fmt: s.xFmt, boundaryGap: numX ? undefined : false,
      min: s.xMin !== undefined ? s.xMin : (numX ? 'dataMin' : undefined), max: s.xMax !== undefined ? s.xMax : (numX ? 'dataMax' : undefined), ticks: s.xTicks });
    var ya = axis(T, { fmt: yF, min: s.yMin !== undefined ? s.yMin : (chance ? 0 : undefined), max: s.yMax === 'auto' ? undefined : (s.yMax !== undefined ? s.yMax : (chance ? 1 : undefined)), scale: s.yMax === 'auto' || !chance, interval: s.yInterval });
    var gB = 8 + nameAxis(xa, s.xName || (s.xType === 'time' ? 'Date' : ''), 'bottom');
    var gT = 14 + nameAxis(ya, s.yName || (chance ? 'Chance' : ''), 'side');
    return {
      grid: { left: 10, right: s.endLabels === false ? 10 : (narrow ? 64 : 104), top: gT + (ml.length ? 14 : 0), bottom: gB, containLabel: true },
      xAxis: xa, yAxis: ya,
      tooltip: tooltip(T, { trigger: 'axis', formatter: function (ps) {
        ps = ps.filter(function (p) { return p.seriesType === 'line'; });
        if (!ps.length) return '';
        var xl = s.xLabel ? s.xLabel(ps[0].axisValue) : (s.xType === 'time' ? fmt.date(new Date(ps[0].axisValue).toISOString(), { day: 'numeric', month: 'short', year: 'numeric' }) : ps[0].axisValueLabel);
        return '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(xl) + '</div>' + ps.slice().sort(function (a, b) { return (val(b) || 0) - (val(a) || 0); }).map(function (p) {
          var x = (s.series || [])[p.seriesIndex - bands.length] || {}, j = p.dataIndex, txt = yF(val(p));
          if (x.band && x.band.lo && isNum(x.band.lo[j]) && isNum(x.band.hi[j])) txt += ' (' + yF(x.band.lo[j]) + '–' + yF(x.band.hi[j]) + ')';
          return tipRow(p.color, p.seriesName, txt);
        }).join('');
      } }),
      series: bands.concat(lines)
    };
  }, { label: s.label || 'Forecast over time' });
};

/* ─────────────────────────────────────── distribution / histogram */
/* QKC.distribution(el, { values: [..] (raw values; binned here) | bins: [{ x0, x1, n }], binCount: 20, binWidth,
 *   marks: [{ x, label, color }] (a player, the league average ...), fmt (x labels), xName, yName ('Players'),
 *   colorBy: 'pctl' (bars on the percentile scale by where they sit; default) | 'flat', lowerBetter, label })
 * Bars show how many fall in each bin; marks are labelled verticals, the first in the signal colour. */
QKC.distribution = function (el, s) {
  var bins = s.bins;
  if (!bins) {
    var v = (s.values || []).filter(isNum).sort(function (a, b) { return a - b; });
    var lo = isNum(s.min) ? s.min : (v.length ? v[0] : 0), hi = isNum(s.max) ? s.max : (v.length ? v[v.length - 1] : 1);
    if (hi === lo) { hi = lo + 1; }
    var w = s.binWidth || (hi - lo) / (s.binCount || 20);
    var n = Math.max(1, Math.ceil((hi - lo) / w - 1e-9));
    bins = [];
    for (var i = 0; i < n; i++) bins.push({ x0: lo + i * w, x1: lo + (i + 1) * w, n: 0 });
    v.forEach(function (x) { var k = Math.min(n - 1, Math.max(0, Math.floor((x - lo) / w))); bins[k].n++; });
  }
  var total = bins.reduce(function (a, b) { return a + b.n; }, 0) || 1;
  return QKC.mount(el, function (T) {
    var f = s.fmt || function (x) { return fmt.num(x, 1); };
    var cum = 0;
    var data = bins.map(function (b) {
      var mid = cum + b.n / 2; cum += b.n;
      var pctl = 100 * mid / total; if (s.lowerBetter) pctl = 100 - pctl;
      var c = s.colorBy === 'flat' ? hexA(T.ink3, 0.5) : hexA(QK.pctHex(pctl), 0.85);
      return { value: [b.x0, b.x1, b.n], itemStyle: { color: c } };
    });
    var x0 = bins[0].x0, x1 = bins[bins.length - 1].x1;
    var ml = (s.marks || []).filter(function (m) { return isNum(m.x); }).map(function (m, k) {
      var c = m.color && typeof T[m.color] === 'string' ? T[m.color] : (m.color || (k === 0 ? T.model : T.ink2));
      var at = x1 > x0 ? (m.x - x0) / (x1 - x0) : 0.5;
      return { xAxis: m.x, lineStyle: { color: c, type: k === 0 ? 'solid' : [4, 3], width: k === 0 ? 2 : 1.2 },
        label: { show: true, formatter: m.label + (m.noValue ? '' : ' ' + f(m.x)), position: 'end', rotate: 0, align: at > 0.82 ? 'right' : at < 0.18 ? 'left' : 'center', color: c, fontSize: 10.5, fontWeight: 700, fontFamily: T.fontUI, distance: k % 2 ? 16 : 3 } };
    });
    var xa = axis(T, { type: 'value', min: bins[0].x0, max: bins[bins.length - 1].x1, fmt: f, split: false, line: true });
    var ya = axis(T, { fmt: function (x) { return fmt.num(x, 0); }, minInterval: 1 });
    ya.minInterval = 1;
    /* keep the count axis at the left edge when the values run negative (ECharts puts it on x = 0 by default) */
    ya.axisLine = Object.assign({}, ya.axisLine || {}, { onZero: false });
    var gB = 8 + nameAxis(xa, s.xName || 'Value', 'bottom');
    var gT = 14 + nameAxis(ya, s.yName || 'Players', 'side') + (ml.length ? 16 : 0);
    return {
      grid: { left: 8, right: 16, top: gT, bottom: gB, containLabel: true },
      xAxis: xa, yAxis: ya,
      tooltip: tooltip(T, { formatter: function (p) { var d = p.value; return '<div style="font-weight:600">' + esc(f(d[0])) + ' to ' + esc(f(d[1])) + '</div>' + tipRow(p.color, s.yName || 'Players', fmt.num(d[2], 0)); } }),
      series: [{
        type: 'custom', name: s.yName || 'Players', data: data, encode: { x: [0, 1], y: 2 }, z: 2,
        renderItem: function (params, api) {
          var a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), 0]);
          var d = data[params.dataIndex] || {};
          return { type: 'rect', shape: { x: a[0] + 0.5, y: a[1], width: Math.max(1, b[0] - a[0] - 1), height: b[1] - a[1], r: [2, 2, 0, 0] }, style: { fill: (d.itemStyle || {}).color || T.ink3 } };
        },
        markLine: ml.length ? { silent: true, symbol: 'none', animation: false, data: ml } : undefined
      }]
    };
  }, { label: s.label || 'Distribution' });
};

/* ─────────────────────────────────────── chances (horizontal probability bars, ours first) */
/* QKC.chances(el, { rows: [{ label, p, market, color, href, sub }], valName: 'Chance', marketName: 'Market', max, limit })
 * The bars are our chance (team colour or the signal); the market, where there is one, is a quiet grey tick. */
QKC.chances = function (el, s) {
  var rows = (s.rows || []).filter(function (r) { return r && isNum(r.p); }).slice().sort(function (a, b) { return b.p - a.p; });
  if (s.limit) rows = rows.slice(0, s.limit);
  var anyM = rows.some(function (r) { return isNum(r.market); });
  var mx = s.max;
  if (!isNum(mx)) { var m = Math.max.apply(null, rows.map(function (r) { return Math.max(r.p, isNum(r.market) ? r.market : 0); }).concat([0.01])); mx = m > 0.6 ? 1 : Math.min(1, Math.ceil(m * 20 + 0.5) / 20); }
  return QKC.bar(el, {
    horizontal: true, cats: rows.map(function (r) { return r.label; }), labels: true, max: mx, min: 0, fmt: function (v) { return fmt.pct(v); },
    series: [{ name: s.oursName || 'Our chance', color: 'model', data: rows.map(function (r) { return r.p; }), market: anyM ? rows.map(function (r) { return isNum(r.market) ? r.market : null; }) : undefined }],
    colors: rows.map(function (r) { return r.color || null; }), hrefs: rows.map(function (r) { return r.href; }), labelWidth: s.labelWidth || 150,
    marketName: s.marketName || 'Market (reference)', legendItems: anyM ? [{ name: s.oursName || 'Our chance', color: rows.some(function (r) { return !!r.color; }) ? 'ink' : 'model' }] : [],
    valName: s.valName || 'Chance', label: s.label || 'Chances'
  });
};

root.QKC = QKC;
})(window);
