/* The Quant — Plotly-compatible charts on Apache ECharts (the kit's chart library). Optional kit module.
 *
 * Load it after quant.js and quant-charts.js on any page that still has Plotly-era views:
 *   <script src="assets/qk/plotly-ec.js" defer></script>
 * or on demand (inject the script the first time an old view draws). Then the Plotly CDN bundle is not needed.
 *
 * The sport sites were written against Plotly (Plotly.newPlot(el, traces, layout)). This file defines a
 * small window.Plotly with the same entry points, so every existing chart renders through ECharts and the
 * design kit: colours come from the tokens at paint time (dark and light), charts repaint when the theme
 * changes, resize with their container and degrade to a message when the CDN fails (QKC.mount).
 *
 * Supported (the subset the sites use): scatter (lines, markers, text, fills tozeroy / tonexty / toself,
 * line shapes hv / vh / spline, dashes, error bars), bar (vertical, horizontal, group / stack / overlay,
 * text labels), heatmap (drawn as cells, so it works on value axes under shapes), scatterpolar (radar),
 * marker colour scales with a colour bar, layout shapes (line, rect, circle, path) and annotations in data
 * or paper coordinates, axis types (linear, log, date, category), ranges, reversed axes, tick values and
 * formats, equal-aspect axes (scaleanchor), a second y axis (overlaying or stacked by domain), legends,
 * titles, hover templates (%{x:.1%}, %{customdata[0]}, <extra>) and plotly_click with customdata.
 *
 * Old dark-palette neutrals written into chart code (#0d1117, #30363d, #8b949e ...) and CSS colours
 * ('var(--ink-2)', color-mix(...)) resolve to the current theme's tokens.
 * No optional chaining or nullish coalescing (older browsers). */
(function (root) {
'use strict';

var QK = root.QK, QKC = root.QKC;
if (!QK || !QKC) return;
var isNum = function (x) { return typeof x === 'number' && isFinite(x); };
var esc = QK.esc;

/* ───────────────────────────── colours */
var OLD = {
  '#0d1117': 's1', '#161b22': 's1', '#1c2128': 's2', '#21262d': 'grid', '#2b323b': 'grid', '#30363d': 'axis', '#3d444d': 'axis',
  '#3a4048': 'axis', '#c9d1d9': 'ink2', '#8b949e': 'ink3', '#6e7681': 'ink3', '#e6edf3': 'ink1', '#ffffff': 'ink1', '#fff': 'ink1'
};
var cssCache = {}, probe = null;
function themeKey() { return QK.theme.get(); }
function parseCssColor(s) {
  var m = /^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(s);
  if (m) { var a = m[4] === undefined ? 1 : (m[4].indexOf('%') > 0 ? parseFloat(m[4]) / 100 : parseFloat(m[4])); return 'rgba(' + Math.round(+m[1]) + ',' + Math.round(+m[2]) + ',' + Math.round(+m[3]) + ',' + a + ')'; }
  m = /^color\(srgb\s+([\d.e-]+)\s+([\d.e-]+)\s+([\d.e-]+)(?:\s*\/\s*([\d.]+%?))?\s*\)$/.exec(s);
  if (m) { var al = m[4] === undefined ? 1 : (m[4].indexOf('%') > 0 ? parseFloat(m[4]) / 100 : parseFloat(m[4])); return 'rgba(' + Math.round(255 * Math.max(0, Math.min(1, +m[1]))) + ',' + Math.round(255 * Math.max(0, Math.min(1, +m[2]))) + ',' + Math.round(255 * Math.max(0, Math.min(1, +m[3]))) + ',' + al + ')'; }
  return null;
}
function cssColor(s) {
  var key = themeKey() + '|' + s;
  if (cssCache[key]) return cssCache[key];
  if (!probe) { probe = document.createElement('span'); probe.style.display = 'none'; document.documentElement.appendChild(probe); }
  probe.style.color = '';
  probe.style.color = s;
  var out = parseCssColor(getComputedStyle(probe).color) || s;
  cssCache[key] = out;
  return out;
}
function toHex(r, g, b) { return '#' + [r, g, b].map(function (v) { return ('0' + Math.max(0, Math.min(255, Math.round(v))).toString(16)).slice(-2); }).join(''); }
function withAlpha(c, a) {
  if (!c) return c;
  var p = QK.color.parse(c);
  if (p) return 'rgba(' + p[0] + ',' + p[1] + ',' + p[2] + ',' + a + ')';
  var r = parseCssColor(c);
  if (r) { var m = /rgba\((\d+),(\d+),(\d+),([\d.]+)\)/.exec(r); if (m) return 'rgba(' + m[1] + ',' + m[2] + ',' + m[3] + ',' + (+m[4] * a) + ')'; }
  return c;
}
/* ctx 'text': a dark ink on a bright marker stays dark in both themes. */
function makeCol(T) {
  return function col(c, ctx) {
    if (c === undefined || c === null || c === '') return c;
    if (Array.isArray(c)) return c.map(function (x) { return col(x, ctx); });
    if (typeof c !== 'string') return c;
    var s = c.trim(), k = s.toLowerCase();
    if (k.indexOf('var(') >= 0 || k.indexOf('color-mix') >= 0) return cssColor(s);
    if (ctx !== 'text' && OLD[k]) return T[OLD[k]];
    var m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)$/.exec(k);
    if (m && ctx !== 'text') {
      var hx = toHex(+m[1], +m[2], +m[3]);
      if (OLD[hx]) return withAlpha(T[OLD[hx]], m[4] === undefined ? 1 : +m[4]);
    }
    return s;
  };
}
/* Plotly colour scales: [[0, c], ..., [1, c]] or a name. */
var NAMED = {
  Viridis: [[0, '#440154'], [0.25, '#3b528b'], [0.5, '#21918c'], [0.75, '#5ec962'], [1, '#fde725']],
  RdBu: [[0, '#b2182b'], [0.5, '#f7f7f7'], [1, '#2166ac']], Blues: [[0, '#deebf7'], [1, '#08519c']],
  Reds: [[0, '#fee0d2'], [1, '#a50f15']], Greens: [[0, '#e5f5e0'], [1, '#006d2c']]
};
function scaleOf(cs, col) {
  var s = typeof cs === 'string' ? (NAMED[cs] || NAMED.Viridis) : (Array.isArray(cs) && cs.length ? cs : NAMED.Viridis);
  return s.map(function (x) { return [Number(x[0]), rgbOf(col(x[1]))]; });
}
function rgbOf(c) {
  var p = QK.color.parse(c);
  if (p) return [p[0], p[1], p[2], 1];
  var r = parseCssColor(String(c || ''));
  if (r) { var m = /rgba\((\d+),(\d+),(\d+),([\d.]+)\)/.exec(r); if (m) return [+m[1], +m[2], +m[3], +m[4]]; }
  return [128, 128, 128, 1];
}
function interp(scale, t) {
  t = Math.max(0, Math.min(1, isNum(t) ? t : 0));
  for (var i = 1; i < scale.length; i++) {
    if (t <= scale[i][0] || i === scale.length - 1) {
      var a = scale[i - 1], b = scale[i], u = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
      u = Math.max(0, Math.min(1, u));
      return 'rgba(' + [0, 1, 2].map(function (k) { return Math.round(a[1][k] + (b[1][k] - a[1][k]) * u); }).join(',') + ',' + (a[1][3] + (b[1][3] - a[1][3]) * u) + ')';
    }
  }
  return 'rgba(128,128,128,1)';
}

/* ───────────────────────────── numbers and templates */
function fmtSpec(v, spec) {
  if (spec === undefined || spec === null || spec === '') return dflt(v);
  if (/%[a-zA-Z]/.test(spec) && !/^[+,]?\.?\d*%$/.test(spec)) return fmtDate(v, spec);
  var n = typeof v === 'number' ? v : parseFloat(v);
  if (!isFinite(n)) return v === undefined || v === null ? '' : String(v);
  var m = /^([+ ])?(,)?(?:\.(\d+))?([fd%e]|s|r|g)?$/.exec(spec);
  if (!m) return dflt(v);
  var sign = m[1] === '+', comma = !!m[2], prec = m[3] === undefined ? null : +m[3], type = m[4] || 'g';
  var out;
  if (type === '%') { out = (n * 100).toFixed(prec === null ? 0 : prec); out = group(out, comma) + '%'; }
  else if (type === 'f') out = group(n.toFixed(prec === null ? 6 : prec), comma);
  else if (type === 'd') out = group(Math.round(n).toString(), comma);
  else if (type === 'e') out = n.toExponential(prec === null ? 2 : prec);
  else out = group(prec === null ? String(+n.toPrecision(6)) : String(+n.toPrecision(Math.max(1, prec))), comma);
  if (sign && n > 0) out = '+' + out;
  if (n < 0) out = out.replace('-', '−');
  return out;
}
function group(s, comma) {
  if (!comma) return s;
  var p = s.split('.');
  p[0] = p[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return p.join('.');
}
function dflt(v) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'number') return Math.abs(v) >= 1000 ? group(String(Math.round(v)), true) : String(+v.toPrecision(4));
  return String(v);
}
var MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
var MONL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
function toDate(v) { if (v instanceof Date) return v; if (isNum(v)) return new Date(v); var t = parseTime(v); return t === null ? null : new Date(t); }
function fmtDate(v, spec) {
  var d = toDate(v);
  if (!d || isNaN(d)) return String(v);
  if (!spec) return d.getDate() + ' ' + MON[d.getMonth()] + ' ' + d.getFullYear();
  return spec.replace(/%([a-zA-Z])/g, function (m, k) {
    switch (k) {
      case 'b': return MON[d.getMonth()]; case 'B': return MONL[d.getMonth()]; case 'd': return ('0' + d.getDate()).slice(-2);
      case 'e': return String(d.getDate()); case 'Y': return String(d.getFullYear()); case 'y': return String(d.getFullYear()).slice(-2);
      case 'm': return ('0' + (d.getMonth() + 1)).slice(-2); case 'H': return ('0' + d.getHours()).slice(-2); case 'M': return ('0' + d.getMinutes()).slice(-2);
      default: return m;
    }
  });
}
function parseTime(v) {
  if (v instanceof Date) return v.getTime();
  if (isNum(v)) return v;
  var s = String(v || '');
  if (/^\d{4}-\d\d-\d\d$/.test(s)) s += 'T00:00:00';
  else if (/^\d{4}-\d\d$/.test(s)) s += '-01T00:00:00';
  else if (/^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)) s = s.replace(' ', 'T');
  var t = Date.parse(s);
  return isNaN(t) ? null : t;
}
function isDateStr(v) { return typeof v === 'string' && /^\d{4}-\d\d(-\d\d)?([ T]\d\d:\d\d(:\d\d)?(\.\d+)?Z?)?$/.test(v); }
function isNumStr(v) { return typeof v === 'string' && v.trim() !== '' && isFinite(Number(v)); }
function fill(t, ctx) {
  if (!t) return '';
  var extra = '';
  t = String(t).replace(/<extra>([\s\S]*?)<\/extra>/, function (m, x) { extra = x; return ''; });
  t = t.replace(/%\{([^}:]+)(?::([^}]*))?\}/g, function (m, key, spec) {
    var v = lookup(ctx, key.trim());
    if (spec === undefined && (key === 'x' || key === 'y') && ctx.axisTime && ctx.axisTime[key]) return fmtDate(v);
    return spec === undefined ? dflt(v) : fmtSpec(v, spec);
  });
  extra = extra.replace(/%\{([^}:]+)(?::([^}]*))?\}/g, function (m, key, spec) { var v = lookup(ctx, key.trim()); return spec === undefined ? dflt(v) : fmtSpec(v, spec); });
  return t + (extra ? '<div style="opacity:.65;font-size:11px;margin-top:3px">' + extra + '</div>' : '');
}
function pick(a, i) { return Array.isArray(a) ? a[i] : a; }
function lookup(ctx, key) {
  var tr = ctx.tr, i = ctx.i;
  if (key === 'x') return ctx.x; if (key === 'y') return ctx.y; if (key === 'z') return ctx.z;
  if (key === 'r') return ctx.r; if (key === 'theta') return ctx.theta;
  if (key === 'text') return pick(tr.text, i); if (key === 'hovertext') return pick(tr.hovertext, i);
  if (key === 'fullData.name' || key === 'data.name') return tr.name;
  if (key === 'pointNumber' || key === 'pointIndex') return i;
  if (key === 'meta') return tr.meta;
  var m = /^customdata(?:\[(\d+)\])?$/.exec(key);
  if (m) { var cd = pick(tr.customdata, i); return m[1] === undefined ? cd : (Array.isArray(cd) ? cd[+m[1]] : undefined); }
  m = /^marker\.(color|size)$/.exec(key);
  if (m) return pick((tr.marker || {})[m[1]], i);
  return '';
}

/* ───────────────────────────── helpers */
function arr(a) { return Array.isArray(a) ? a : (a && typeof a.length === 'number' ? Array.prototype.slice.call(a) : []); }
function titleText(t) { return !t ? '' : (typeof t === 'string' ? t : (t.text || '')); }
function axisKey(id, d) { return id ? String(id).replace(/^([xy])(\d*)$/, function (m, a, n) { return a + 'axis' + (n === '1' ? '' : n); }) : d; }
function strip(html) { return String(html === undefined || html === null ? '' : html).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&quot;/g, '"'); }
var DASH = { dot: [2, 3], dash: [6, 4], dashdot: [6, 3, 2, 3], longdash: [10, 4], solid: null };
function dashOf(d) { return d && DASH[d] !== undefined ? DASH[d] : (Array.isArray(d) ? d : null); }
var SYMBOL = {
  circle: 'circle', 'circle-open': 'circle', square: 'rect', 'square-open': 'rect', diamond: 'diamond', 'diamond-open': 'diamond',
  'triangle-up': 'triangle', 'triangle-up-open': 'triangle',
  'triangle-down': 'path://M0,0L10,0L5,9Z',
  x: 'path://M1,0L5,4L9,0L10,1L6,5L10,9L9,10L5,6L1,10L0,9L4,5L0,1Z',
  'x-open': 'path://M1,0L5,4L9,0L10,1L6,5L10,9L9,10L5,6L1,10L0,9L4,5L0,1Z',
  star: 'path://M5,0L6.2,3.6L10,3.8L7,6.1L8.1,9.8L5,7.6L1.9,9.8L3,6.1L0,3.8L3.8,3.6Z',
  'star-open': 'path://M5,0L6.2,3.6L10,3.8L7,6.1L8.1,9.8L5,7.6L1.9,9.8L3,6.1L0,3.8L3.8,3.6Z',
  'line-ns-open': 'path://M4.4,0L5.6,0L5.6,10L4.4,10Z', 'line-ns': 'path://M4.4,0L5.6,0L5.6,10L4.4,10Z',
  'line-ew-open': 'path://M0,4.4L10,4.4L10,5.6L0,5.6Z'
};
function symOf(s) { return SYMBOL[s] || 'circle'; }
function isOpen(s) { return /-open$/.test(String(s || '')); }
function textPos(p, horizontal) {
  p = String(p || 'top center');
  if (p === 'outside' || p === 'auto') return horizontal ? 'right' : 'top';
  if (p === 'inside') return 'inside';
  if (p.indexOf('middle center') === 0) return 'inside';
  if (p.indexOf('top') === 0) return 'top';
  if (p.indexOf('bottom') === 0) return 'bottom';
  if (/right$/.test(p)) return 'right';
  if (/left$/.test(p)) return 'left';
  return 'top';
}

/* ───────────────────────────── build an ECharts option from traces + layout */
function build(T, el, traces, layout) {
  var col = makeCol(T);
  var L = layout || {};
  traces = (traces || []).filter(function (t) { return t && t.visible !== false; });
  var W = el.clientWidth || 600, H = el.clientHeight || 360;
  var font = { fontFamily: T.fontUI, color: T.ink2 };

  /* polar → radar */
  var polar = traces.filter(function (t) { return t.type === 'scatterpolar' || t.type === 'barpolar'; });
  if (polar.length) return buildRadar(T, col, polar, L, W, H);

  /* axes: ids in use */
  function xId(t) { return t.xaxis || 'x'; }
  function yId(t) { return t.yaxis || 'y'; }
  var xIds = [], yIds = [];
  traces.forEach(function (t) { if (xIds.indexOf(xId(t)) < 0) xIds.push(xId(t)); if (yIds.indexOf(yId(t)) < 0) yIds.push(yId(t)); });
  if (!xIds.length) xIds = ['x']; if (!yIds.length) yIds = ['y'];
  ['x', 'y'].forEach(function (a) {
    var list = a === 'x' ? xIds : yIds;
    if (list.indexOf(a) < 0 && L[a + 'axis']) list.unshift(a);
    list.sort();
  });
  function laxis(id) { return L[axisKey(id)] || {}; }
  /* grids: a y axis with its own domain (not overlaying) opens a grid; x axes follow their anchor */
  var grids = [], gridOfY = {};
  yIds.forEach(function (id) {
    var a = laxis(id);
    if (a.overlaying) { gridOfY[id] = null; return; }
    var dom = a.domain && a.domain.length === 2 ? a.domain : [0, 1];
    var gi = -1;
    grids.forEach(function (g, i) { if (g.dom[0] === dom[0] && g.dom[1] === dom[1]) gi = i; });
    if (gi < 0) { grids.push({ dom: dom }); gi = grids.length - 1; }
    gridOfY[id] = gi;
  });
  yIds.forEach(function (id) { if (gridOfY[id] === null) { var o = String(laxis(id).overlaying); gridOfY[id] = gridOfY[o] !== undefined && gridOfY[o] !== null ? gridOfY[o] : 0; } });
  if (!grids.length) grids.push({ dom: [0, 1] });
  var gridOfX = {};
  xIds.forEach(function (id) {
    var a = laxis(id), anc = a.anchor && a.anchor !== 'free' ? a.anchor : null;
    if (!anc) { var tr = traces.filter(function (t) { return xId(t) === id; })[0]; anc = tr ? yId(tr) : 'y'; }
    gridOfX[id] = gridOfY[anc] !== undefined ? gridOfY[anc] : 0;
  });

  /* axis kinds from the layout or the data */
  function axisValues(id, letter) {
    var out = [];
    traces.forEach(function (t) {
      if ((letter === 'x' ? xId(t) : yId(t)) !== id) return;
      var v = arr(t[letter]);
      if (!v.length && t.type === 'heatmap') return;
      if (!v.length) { var other = arr(t[letter === 'x' ? 'y' : 'x']); v = other.map(function (_, i) { return i; }); }
      out = out.concat(v);
    });
    return out;
  }
  var AX = {};
  function kindOf(id, letter) {
    var a = laxis(id), vals = axisValues(id, letter);
    if (a.type === 'date') return 'time';
    if (a.type === 'log') return 'log';
    if (a.type === 'category' || a.type === 'multicategory') return 'category';
    if (a.type === 'linear') return 'value';
    var anyStr = false, allDate = true, allNum = true, seen = 0;
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      if (v === null || v === undefined || v === '') continue;
      seen++;
      if (typeof v === 'string') { anyStr = true; if (!isDateStr(v)) allDate = false; if (!isNumStr(v)) allNum = false; }
      else if (v instanceof Date) { anyStr = true; allNum = false; }
      else { allDate = false; }
    }
    if (!seen || !anyStr) return 'value';
    if (allNum) return 'value';
    if (allDate) return 'time';
    return 'category';
  }
  xIds.forEach(function (id) { AX[id] = { letter: 'x', kind: kindOf(id, 'x') }; });
  yIds.forEach(function (id) { AX[id] = { letter: 'y', kind: kindOf(id, 'y') }; });
  /* category lists */
  Object.keys(AX).forEach(function (id) {
    var ax = AX[id];
    if (ax.kind !== 'category') return;
    var a = laxis(id);
    var cats = [];
    if (Array.isArray(a.categoryarray)) cats = a.categoryarray.map(String);
    axisValues(id, ax.letter).forEach(function (v) { if (v !== null && v !== undefined && cats.indexOf(String(v)) < 0) cats.push(String(v)); });
    traces.forEach(function (t) { if (t.type === 'heatmap' && (ax.letter === 'x' ? xId(t) : yId(t)) === id) arr(t[ax.letter]).forEach(function (v) { if (cats.indexOf(String(v)) < 0) cats.push(String(v)); }); });
    ax.cats = cats;
  });
  function conv(id, v) {
    var ax = AX[id];
    if (v === null || v === undefined || v === '') return null;
    if (!ax) return v;
    if (ax.kind === 'time') return parseTime(v);
    if (ax.kind === 'category') return String(v);
    var n = typeof v === 'number' ? v : Number(v);
    return isFinite(n) ? n : null;
  }

  /* hover: axis trigger for line/bar-only charts, item trigger once markers are in play */
  var hoverMode = L.hovermode;
  var hoverable = traces.filter(function (t) { return t.hoverinfo !== 'skip' && t.hoverinfo !== 'none'; });
  var anyMarkers = hoverable.some(function (t) { return (t.type === 'scatter' || t.type === 'scattergl' || !t.type) && /markers|text/.test(t.mode || 'markers') && !/lines/.test(t.mode || ''); });
  var axisTrigger = hoverMode === 'x' || hoverMode === 'x unified' || hoverMode === 'y' || (!anyMarkers && hoverable.length && hoverable.every(function (t) { return t.type === 'bar' || (t.type === 'scatter' || !t.type) && /lines/.test(t.mode || ''); }));
  if (hoverMode === false) axisTrigger = false;

  var series = [], legendNames = [], shapesBelow = [], shapesAbove = [], visualMaps = [];
  var axisTime = {};
  Object.keys(AX).forEach(function (id) { if (AX[id].kind === 'time') axisTime[AX[id].letter] = true; });
  var barMode = L.barmode || 'group';
  var anchor = null;

  traces.forEach(function (tr, ti) {
    var type = tr.type || 'scatter';
    var xa = xId(tr), ya = yId(tr);
    var xi = xIds.indexOf(xa), yi = yIds.indexOf(ya);
    var color0 = col(tr.marker && typeof tr.marker.color === 'string' ? tr.marker.color : (tr.line && tr.line.color) || (tr.marker && tr.marker.color && !Array.isArray(tr.marker.color) ? tr.marker.color : null)) || T.cat[ti % 8];
    var silent = tr.hoverinfo === 'skip' || tr.hoverinfo === 'none';
    var inLegend = tr.showlegend !== false && !!tr.name && !silent;
    var base = { name: tr.name || ('trace ' + ti), xAxisIndex: xi, yAxisIndex: yi, silent: silent && !tr.customdata, z: 3 + ti * 0.01, _ti: ti };
    if (silent) base.tooltip = { show: false };
    if (inLegend && legendNames.indexOf(base.name) < 0) legendNames.push(base.name);

    if (type === 'heatmap') {
      series.push(heatmapSeries(T, col, tr, base, xa, ya, conv, AX, visualMaps, axisTime));
      return;
    }
    var xs = arr(tr.x), ys = arr(tr.y);
    var horizontal = type === 'bar' && tr.orientation === 'h';
    if (!xs.length && ys.length) xs = ys.map(function (_, i) { return i; });
    if (!ys.length && xs.length) ys = xs.map(function (_, i) { return i; });
    var n = Math.max(xs.length, ys.length);
    var pts = [];
    for (var i = 0; i < n; i++) pts.push([conv(xa, xs[i]), conv(ya, ys[i])]);
    if (!anchor) for (var a0 = 0; a0 < pts.length; a0++) if (pts[a0][0] !== null && pts[a0][1] !== null) { anchor = { x: pts[a0][0], y: pts[a0][1], xi: xi, yi: yi }; break; }

    /* per-point marker styling */
    var mk = tr.marker || {}, ml = mk.line || {};
    var cArr = Array.isArray(mk.color) ? mk.color : null;
    var numericC = cArr && cArr.some(isNum);
    var scale = null, cmin = mk.cmin, cmax = mk.cmax;
    if (numericC) {
      scale = scaleOf(mk.colorscale, col);
      if (mk.reversescale) scale = scale.map(function (s) { return [1 - s[0], s[1]]; }).reverse();
      var cv = cArr.filter(isNum);
      if (!isNum(cmin)) cmin = Math.min.apply(null, cv); if (!isNum(cmax)) cmax = Math.max.apply(null, cv);
      if (mk.showscale !== false && (mk.colorbar || mk.showscale)) visualMaps.push({ min: cmin, max: cmax, scale: scale, title: titleText((mk.colorbar || {}).title), grid: gridOfY[ya] || 0 });
    }
    function pointColor(i) {
      if (cArr) { var c = cArr[i]; if (numericC) return isNum(c) ? interp(scale, (c - cmin) / ((cmax - cmin) || 1)) : T.other; return col(c) || color0; }
      return color0;
    }
    var sizes = Array.isArray(mk.size) ? mk.size : null;
    var syms = Array.isArray(mk.symbol) ? mk.symbol : null;
    var lws = Array.isArray(ml.width) ? ml.width : null, lcs = Array.isArray(ml.color) ? ml.color : null;
    var opac = Array.isArray(mk.opacity) ? mk.opacity : null;
    var perPoint = !!(cArr || sizes || syms || lws || lcs || opac);
    var texts = Array.isArray(tr.text) ? tr.text : null;
    var mode = tr.mode || (type === 'scatter' ? (n > 20 ? 'lines' : 'lines+markers') : '');
    var showText = (/text/.test(mode) || (type === 'bar' && tr.text !== undefined && tr.textposition !== 'none')) && (texts || typeof tr.text === 'string');
    var tf = tr.textfont || {};

    if (type === 'bar') {
      var data = pts.map(function (p, i) {
        var v = horizontal ? [p[0], p[1]] : [p[0], p[1]];
        var o = { value: v, _i: i };
        if (cArr) o.itemStyle = { color: pointColor(i) };
        return o;
      });
      var s = Object.assign(base, {
        type: 'bar', data: data, barMaxWidth: horizontal ? 18 : 34,
        itemStyle: { color: color0, borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0], opacity: isNum(mk.opacity) ? mk.opacity : 1 },
        emphasis: { focus: 'none', itemStyle: { opacity: 1 } }
      });
      if (barMode === 'stack' || barMode === 'relative') s.stack = 'bars' + (horizontal ? 'h' : 'v') + xi + yi;
      if (barMode === 'overlay') s.barGap = '-100%';
      if (isNum(L.bargap)) s.barCategoryGap = Math.round(L.bargap * 100) + '%';
      if (showText) s.label = { show: true, position: textPos(tr.textposition, horizontal), color: col(tf.color, 'text') || T.ink2, fontFamily: T.fontNum, fontSize: tf.size || 10.5,
        formatter: function (p) { var t = texts ? texts[p.data._i] : tr.text; return strip(tr.texttemplate && tr.texttemplate !== '%{text}' ? fill(tr.texttemplate, { tr: tr, i: p.data._i, x: xs[p.data._i], y: ys[p.data._i] }) : t); } };
      s._tip = tipFn(tr, xs, ys, axisTime);
      series.push(s);
      if (tr.error_y || tr.error_x) series.push(errorBars(T, col, tr, pts, base, color0));
      return;
    }

    /* scatter */
    var lines = /lines/.test(mode), markers = /markers/.test(mode);
    var ln = tr.line || {};
    var lineW = isNum(ln.width) ? ln.width : 2;
    var symbolSize = isNum(mk.size) ? mk.size : (markers ? 7 : 4);
    var openSym = isOpen(mk.symbol);
    var dataS = pts.map(function (p, i) {
      var o = { value: [p[0], p[1]], _i: i };
      if (perPoint || showText) {
        var c = pointColor(i), sym = syms ? syms[i] : mk.symbol, open = isOpen(sym);
        var lc = lcs ? col(lcs[i]) : col(ml.color), lw = lws ? lws[i] : (isNum(ml.width) ? ml.width : 0);
        o.itemStyle = open ? { color: 'transparent', borderColor: c, borderWidth: Math.max(1.5, lw || 1.5) } : { color: c, borderColor: lc || T.s1, borderWidth: lw, opacity: opac ? opac[i] : (isNum(mk.opacity) ? mk.opacity : 1) };
        if (syms) o.symbol = symOf(sym);
        if (sizes) o.symbolSize = isNum(sizes[i]) ? sizes[i] : symbolSize;
        if (showText && texts) o.label = { show: texts[i] !== '' && texts[i] !== null && texts[i] !== undefined, formatter: strip(texts[i]) };
      }
      return o;
    });
    var ss = Object.assign(base, {
      type: lines ? 'line' : 'scatter', data: dataS,
      symbol: symOf(mk.symbol), symbolSize: symbolSize, showSymbol: markers || (lines && !silent && axisTrigger === false && n < 120),
      connectNulls: !!tr.connectgaps,
      itemStyle: openSym ? { color: 'transparent', borderColor: color0, borderWidth: Math.max(1.5, isNum(ml.width) ? ml.width : 1.5) }
        : { color: color0, borderColor: col(ml.color) || T.s1, borderWidth: isNum(ml.width) ? ml.width : (markers ? 1 : 0), opacity: isNum(mk.opacity) ? mk.opacity : 1 },
      emphasis: { focus: 'none', scale: 1.25 }
    });
    if (lines) {
      var lc0 = col(ln.color) || color0;
      ss.lineStyle = { color: lc0, width: lineW, type: dashOf(ln.dash) || 'solid', opacity: lineW === 0 ? 0 : 1, cap: 'round', join: 'round' };
      if (!markers && !perPoint) ss.itemStyle = { color: lc0 };
      if (ln.shape === 'hv') ss.step = 'end'; else if (ln.shape === 'vh') ss.step = 'start'; else if (ln.shape === 'hvh') ss.step = 'middle';
      else if (ln.shape === 'spline') ss.smooth = 0.3;
      ss.emphasis = { focus: 'none', lineStyle: { width: lineW === 0 ? 0 : lineW + 0.5 } };
      if (lineW === 0 && !markers) ss.showSymbol = false;
    } else {
      ss.large = n > 2500 && !perPoint;
    }
    if (showText) {
      ss.label = { show: true, position: textPos(tr.textposition), color: col(tf.color, 'text') || T.ink2, fontSize: tf.size || 10, fontFamily: T.fontUI, fontWeight: 600,
        formatter: function (p) { return strip(texts ? texts[p.data._i] : tr.text); } };
      ss.labelLayout = { hideOverlap: true };
    }
    if (tr.fill === 'tozeroy' || tr.fill === 'tozerox') {
      ss.areaStyle = { color: col(tr.fillcolor) || withAlpha(ss.lineStyle ? ss.lineStyle.color : color0, 0.18), origin: 'auto' };
      if (ss.type !== 'line') { ss.type = 'line'; ss.lineStyle = { width: 0, opacity: 0 }; ss.showSymbol = false; }
    }
    if (tr.fill === 'toself') {
      var poly = pts.filter(function (p) { return p[0] !== null && p[1] !== null; });
      (tr._above ? shapesAbove : shapesBelow).push({ kind: 'poly', pts: poly, fill: col(tr.fillcolor) || withAlpha(color0, 0.2), stroke: lineW > 0 && lines ? (col(ln.color) || color0) : null, width: lineW, xi: xi, yi: yi });
      if (lineW === 0 || !lines) { ss.lineStyle = { width: 0, opacity: 0 }; ss.showSymbol = markers; }
    }
    if (tr.fill === 'tonexty' && ti > 0) {
      /* the band between this trace and the one before, drawn as polygons (gaps split it), stepped like the line */
      var prev = traces[ti - 1], pxs = arr(prev.x), pys = arr(prev.y);
      var stepMode = ln.shape === 'hv' ? 'hv' : ln.shape === 'vh' ? 'vh' : null;
      var runs = [], cur = [];
      for (var k = 0; k < n; k++) {
        var xv = pts[k][0], yv = pts[k][1], pv = pys[k] !== null && pys[k] !== undefined && isFinite(+pys[k]) ? +pys[k] : null;
        if (pxs.length && conv(xa, pxs[k]) !== xv) pv = null;
        if (xv === null || yv === null || pv === null) { if (cur.length) runs.push(cur); cur = []; continue; }
        cur.push([xv, yv, pv]);
      }
      if (cur.length) runs.push(cur);
      var fc = col(tr.fillcolor) || withAlpha(color0, 0.2);
      runs.forEach(function (r) {
        if (r.length < 2) return;
        var top = [], bot = [];
        for (var q = 0; q < r.length; q++) {
          if (q > 0 && stepMode) {
            if (stepMode === 'hv') { top.push([r[q][0], r[q - 1][1]]); bot.push([r[q][0], r[q - 1][2]]); }
            else { top.push([r[q - 1][0], r[q][1]]); bot.push([r[q - 1][0], r[q][2]]); }
          }
          top.push([r[q][0], r[q][1]]); bot.push([r[q][0], r[q][2]]);
        }
        shapesBelow.push({ kind: 'poly', pts: top.concat(bot.reverse()), fill: fc, stroke: null, width: 0, xi: xi, yi: yi });
      });
    }
    ss._tip = tipFn(tr, xs, ys, axisTime);
    series.push(ss);
    if (tr.error_y || tr.error_x) series.push(errorBars(T, col, tr, pts, base, color0));
  });

  /* shapes and annotations */
  (L.shapes || []).forEach(function (sh) {
    if (!sh) return;
    (sh.layer === 'below' ? shapesBelow : shapesAbove).push(Object.assign({ kind: 'shape' }, sh));
  });
  (L.annotations || []).forEach(function (an) { if (an && an.text !== undefined && an.visible !== false) shapesAbove.push(Object.assign({ kind: 'text' }, an)); });

  /* axes */
  var xAxes = xIds.map(function (id) { return makeAxis(T, col, id, laxis(id), AX[id], gridOfX[id], 'x'); });
  xAxes.forEach(function (ax, i) {
    var id = xIds[i], on = traces.filter(function (t) { return xId(t) === id; });
    if ((ax.type === 'value' || ax.type === 'time') && ax.min === undefined && ax.max === undefined && on.length && on.every(function (t) { return (t.type || 'scatter') === 'scatter' && /lines/.test(t.mode || 'lines') && !/markers/.test(t.mode || ''); })) { ax.min = 'dataMin'; ax.max = 'dataMax'; ax.scale = true; }
  });
  var yAxes = yIds.map(function (id) { return makeAxis(T, col, id, laxis(id), AX[id], gridOfY[id], 'y'); });

  /* explicit ranges, for the anchor of the overlay series */
  if (!anchor) {
    var xr = (laxis(xIds[0]).range || [0, 1]), yr = (laxis(yIds[0]).range || [0, 1]);
    anchor = { x: conv(xIds[0], xr[0]), y: conv(yIds[0], yr[0]), xi: 0, yi: 0 };
    if (AX[xIds[0]].kind === 'category') anchor.x = (AX[xIds[0]].cats || [])[0];
    if (AX[yIds[0]].kind === 'category') anchor.y = (AX[yIds[0]].cats || [])[0];
  }

  /* layout: legend, title, padding */
  var showLegend = L.showlegend === true || (L.showlegend === undefined && legendNames.length > 1);
  var lg = L.legend || {};
  var legendPos = lg.orientation === 'h' ? (isNum(lg.y) && lg.y > 0.5 ? 'top' : 'bottom') : (lg.orientation === 'v' || isNum(lg.x) ? 'right' : (isNum(lg.y) && lg.y > 0.5 ? 'top' : 'bottom'));
  if (W < 560 && legendPos === 'right') legendPos = 'bottom';
  var title = titleText(L.title);
  var marg = L.margin || {};
  var hasXTitle = xAxes.some(function (a) { return !!a.name; }), hasYTitle = yAxes.some(function (a, i) { return !!a.name && a.position !== 'right'; });
  var hasY2Title = yAxes.some(function (a) { return !!a.name && a.position === 'right'; });
  var annTop = (L.annotations || []).some(function (a) { return a && a.yref === 'paper' && a.y > 1; });
  var pad = {
    top: 10 + (title ? 22 : 0) + (showLegend && legendPos === 'top' ? 26 : 0) + (annTop ? 14 : 0) + (xAxes.some(function (a) { return a.position === 'top' && a.axisLabel.show !== false; }) ? 16 : 0),
    bottom: 6 + (hasXTitle ? 20 : 0) + (showLegend && legendPos === 'bottom' ? 32 : 0),
    left: 6 + (hasYTitle ? 18 : 0),
    right: 12 + (hasY2Title ? 18 : 0) + (showLegend && legendPos === 'right' ? 130 : 0) + (visualMaps.length ? 52 : 0)
  };
  var equal = yIds.concat(xIds).some(function (id) { return !!laxis(id).scaleanchor; });
  var gridOpts = grids.map(function (g, gi) {
    var top = pad.top, bottom = pad.bottom;
    var avail = H - top - bottom;
    var gTop = top + (1 - g.dom[1]) * avail, gH = (g.dom[1] - g.dom[0]) * avail;
    if (grids.length > 1) { gTop += 4; gH -= 18; }
    return { left: pad.left, right: pad.right, top: Math.round(gTop), height: Math.max(40, Math.round(gH)), containLabel: true };
  });
  /* containLabel measures the default ticks, not custom tick text: make room for long tick text by hand */
  yAxes.forEach(function (a) {
    if (!a._ttMax || a.axisLabel.show === false) return;
    var extra = Math.max(0, a._ttMax * 6.4 - 30);
    gridOpts.forEach(function (g, gi) { if ((a.gridIndex || 0) !== gi) return; if (a.position === 'right') g.right += extra; else g.left += extra; });
  });
  if (equal) applyEqual(gridOpts, xAxes, yAxes, xIds, yIds, laxis, W, H, marg, pad);

  /* name gaps that clear the tick labels */
  yAxes.forEach(function (a) { if (a.name) a.nameGap = a._gap || 34; });
  xAxes.forEach(function (a) { if (a.name) a.nameGap = a.axisLabel && a.axisLabel.show === false ? 8 : (a.axisLabel && a.axisLabel.rotate ? 44 : 26); });

  /* overlay (shapes, annotations, fill polygons) — one custom series per layer */
  if (shapesBelow.length) series.unshift(overlaySeries(T, col, shapesBelow, anchor, 0, conv, xIds, yIds));
  if (shapesAbove.length) series.push(overlaySeries(T, col, shapesAbove, anchor, 40, conv, xIds, yIds));

  /* colour bars */
  var vm = visualMaps.slice(0, 1).map(function (v) {
    series.push({ type: 'scatter', name: '_scale', data: [], xAxisIndex: 0, yAxisIndex: 0, silent: true, tooltip: { show: false } });
    return { type: 'continuous', min: v.min, max: v.max, seriesIndex: series.length - 1, calculable: false, orient: 'vertical', right: 4, top: 'middle', itemWidth: 8, itemHeight: Math.min(150, H * 0.45),
      text: [dflt(+v.max.toPrecision(3)), dflt(+v.min.toPrecision(3))], textGap: 4, textStyle: { color: T.ink3, fontFamily: T.fontNum, fontSize: 9.5 },
      inRange: { color: v.scale.map(function (s) { return 'rgba(' + s[1].slice(0, 3).join(',') + ',' + s[1][3] + ')'; }) } };
  });

  var opt = {
    grid: gridOpts, xAxis: xAxes, yAxis: yAxes, series: series,
    legend: showLegend ? legendOf(T, legendNames, legendPos, traces) : { show: false },
    tooltip: tooltipOf(T, series, traces, axisTrigger, hoverMode)
  };
  if (vm.length) opt.visualMap = vm;
  if (title) opt.title = { text: strip(title), left: 4, top: 2, textStyle: { color: T.ink2, fontSize: 12, fontWeight: 600, fontFamily: T.fontUI } };
  /* bars in a group need the gap set on the last series of a stack-free group */
  if (barMode === 'group') series.filter(function (s) { return s.type === 'bar'; }).forEach(function (s) { s.barGap = '12%'; });
  return opt;
}

function tipFn(tr, xs, ys, axisTime) {
  return function (i) {
    var ctx = { tr: tr, i: i, x: xs[i], y: ys[i], axisTime: axisTime };
    var ht = Array.isArray(tr.hovertemplate) ? tr.hovertemplate[i] : tr.hovertemplate;
    if (ht) return fill(ht, ctx);
    if (tr.hoverinfo === 'text' || (tr.hovertext && !tr.hoverinfo)) { var h = pick(tr.hovertext, i); if (h === undefined || h === null) h = pick(tr.text, i); return h === undefined || h === null ? '' : String(h); }
    var xv = axisTime.x ? fmtDate(xs[i]) : dflt(xs[i]), yv = axisTime.y ? fmtDate(ys[i]) : dflt(ys[i]);
    var t = pick(tr.text, i);
    return (tr.name ? '<b>' + esc(tr.name) + '</b><br>' : '') + (tr.orientation === 'h' ? esc(yv) + ': ' + esc(xv) : esc(xv) + ': ' + esc(yv)) + (t !== undefined && t !== null && t !== '' ? '<br>' + t : '');
  };
}

function legendOf(T, names, pos, traces) {
  var o = { show: true, data: names, type: 'scroll', icon: 'roundRect', itemWidth: 12, itemHeight: 8, itemGap: 12,
    textStyle: { color: T.ink2, fontFamily: T.fontUI, fontSize: 11 }, pageTextStyle: { color: T.ink3 }, pageIconColor: T.ink2, pageIconInactiveColor: T.ink4 };
  if (pos === 'top') { o.top = 2; o.left = 0; }
  else if (pos === 'right') { o.orient = 'vertical'; o.right = 0; o.top = 'middle'; }
  else { o.bottom = 0; o.left = 'center'; }
  return o;
}

function tooltipOf(T, series, traces, axisTrigger, hoverMode) {
  if (hoverMode === false) return { show: false };
  var t = QKC.tooltip(T, {
    trigger: axisTrigger ? 'axis' : 'item',
    formatter: function (ps) {
      var list = Array.isArray(ps) ? ps : [ps];
      var out = [];
      list.forEach(function (p) {
        var s = series[p.seriesIndex];
        if (!s || !s._tip || s.silent) return;
        var i = p.data && p.data._i !== undefined ? p.data._i : p.dataIndex;
        var body = s._tip(i);
        if (!body) return;
        out.push(axisTrigger && list.length > 1 ? '<div style="display:flex;gap:8px;align-items:flex-start"><i style="width:8px;height:8px;border-radius:2px;margin-top:5px;flex:none;background:' + p.color + '"></i><div>' + body + '</div></div>' : body);
      });
      return out.length ? '<div style="max-width:300px;white-space:normal;line-height:1.45">' + out.join('<div style="height:6px"></div>') + '</div>' : '';
    }
  });
  if (axisTrigger) t.axisPointer = { type: series.some(function (s) { return s.type === 'bar'; }) ? 'shadow' : 'line', lineStyle: { color: T.axis }, shadowStyle: { color: QKC.hexA(T.ink1, T.dark ? 0.05 : 0.04) } };
  return t;
}

function tickFmt(spec, kind) {
  if (!spec) return null;
  if (kind === 'time') return function (v) { return fmtDate(v, spec); };
  return function (v) { return fmtSpec(v, spec); };
}
function makeAxis(T, col, id, a, ax, gridIndex, letter) {
  var kind = ax ? ax.kind : 'value';
  var o = QKC.axis(T, { type: kind, data: kind === 'category' ? ax.cats : undefined, split: kind !== 'category' && a.showgrid !== false, line: kind === 'category' || a.showline === true });
  o.gridIndex = gridIndex || 0;
  o.axisLabel.hideOverlap = true;
  if (kind === 'category') { o.axisLabel.fontFamily = T.fontUI; o.axisLabel.color = T.ink2; o.axisLabel.width = letter === 'y' ? 150 : 90; o.axisLabel.overflow = 'truncate'; o.axisLabel.interval = letter === 'y' ? 0 : 'auto'; }
  if (kind === 'time') { o.axisLabel.formatter = a.tickformat ? tickFmt(a.tickformat, 'time') : { year: '{yyyy}', month: '{MMM}', day: '{d} {MMM}', hour: '{HH}:{mm}', minute: '{HH}:{mm}' }; o.splitLine.show = a.showgrid !== false; }
  else if (a.tickformat) o.axisLabel.formatter = tickFmt(a.tickformat, kind);
  else if (kind === 'value' || kind === 'log') o.axisLabel.formatter = function (v) { return dflt(+(+v).toPrecision(6)); };
  if (a.gridcolor) o.splitLine.lineStyle.color = col(a.gridcolor);
  if (a.showticklabels === false || a.visible === false) o.axisLabel.show = false;
  if (a.visible === false) { o.axisLine.show = false; o.splitLine.show = false; }
  if (a.side === 'right' || (letter === 'y' && a.overlaying)) { o.position = a.side === 'left' ? 'left' : 'right'; if (a.overlaying) o.splitLine.show = a.showgrid === true; }
  if (a.side === 'top') o.position = 'top';
  if (a.autorange === 'reversed') o.inverse = true;
  if (isNum(a.tickangle) && a.tickangle) o.axisLabel.rotate = -a.tickangle;
  var r = a.range;
  if (Array.isArray(r) && r.length === 2 && r[0] !== null && r[1] !== null && r[0] !== undefined) {
    var lo = r[0], hi = r[1];
    if (kind === 'log') { lo = Math.pow(10, lo); hi = Math.pow(10, hi); }
    if (kind === 'time') { lo = parseTime(lo); hi = parseTime(hi); }
    if (kind === 'category') { o.min = Math.max(0, Math.round(lo)); o.max = Math.round(hi); }
    else if (isNum(+lo) && isNum(+hi)) { if (+lo > +hi) { o.inverse = !o.inverse; o.min = +hi; o.max = +lo; } else { o.min = +lo; o.max = +hi; } }
  } else if (a.rangemode === 'tozero' && kind === 'value') { o.min = function (v) { return Math.min(0, v.min); }; o.max = function (v) { return Math.max(0, v.max); }; o.scale = false; }
  else if (kind === 'value') o.scale = true;
  if (kind === 'log') { o.logBase = 10; o.scale = true; }
  if (isNum(a.dtick) && (kind === 'value')) o.interval = a.dtick;
  if (Array.isArray(a.tickvals) && a.tickvals.length) {
    var tv = a.tickvals.map(function (v) { return kind === 'time' ? parseTime(v) : v; }), tt = Array.isArray(a.ticktext) ? a.ticktext : null;
    o.axisLabel.customValues = tv; o.axisTick = { show: false, customValues: tv };
    if (tt) o._ttMax = Math.max.apply(null, tt.map(function (x) { return strip(x).length; }));
    if (kind === 'value' || kind === 'log') o.splitLine.show = a.showgrid !== false;
    var f0 = o.axisLabel.formatter;
    o.axisLabel.formatter = function (v) {
      for (var i = 0; i < tv.length; i++) if (Math.abs(tv[i] - v) < 1e-9 * Math.max(1, Math.abs(v))) return tt ? strip(tt[i]) : (typeof f0 === 'function' ? f0(v) : dflt(v));
      return tt ? '' : (typeof f0 === 'function' ? f0(v) : dflt(v));
    };
    if (kind === 'value' && tv.length >= 2 && !isNum(o.min)) { o.min = Math.min.apply(null, tv.concat(isNum(o.min) ? [o.min] : [])); }
  }
  var t = titleText(a.title);
  if (t) {
    o.name = strip(t); o.nameLocation = 'middle';
    o.nameTextStyle = { color: T.ink3, fontFamily: T.fontUI, fontSize: 11, fontWeight: 600 };
    if (letter === 'y') {
      o.nameRotate = o.position === 'right' ? -90 : 90;
      o._gap = 40;
    }
  }
  if (a.zeroline === true && kind === 'value') o._zero = col(a.zerolinecolor) || T.axis;
  return o;
}

/* equal aspect: shrink the plot area (Plotly's constrain: 'domain'), centred, keeping the ranges */
function applyEqual(grids, xAxes, yAxes, xIds, yIds, laxis, W, H, marg, pad) {
  var xa = xAxes[0], ya = yAxes[0];
  if (!isNum(xa.min) || !isNum(xa.max) || !isNum(ya.min) || !isNum(ya.max)) return;
  var yl = laxis(yIds[0]), xl = laxis(xIds[0]);
  var ratio = isNum(yl.scaleratio) && yl.scaleanchor ? yl.scaleratio : (isNum(xl.scaleratio) && xl.scaleanchor ? 1 / xl.scaleratio : 1);
  var labelsX = xa.axisLabel.show !== false, labelsY = ya.axisLabel.show !== false;
  var l = labelsY || ya.name ? Math.max(isNum(marg.l) ? marg.l : 44, 36) : 4, r = 6 + pad.right - 12, t = pad.top, b = (labelsX || xa.name ? Math.max(isNum(marg.b) ? marg.b : 40, 30) : 4) + (pad.bottom - 6 - (xa.name ? 20 : 0));
  var w = W - l - r, h = H - t - b;
  if (w <= 20 || h <= 20) return;
  var dx = xa.max - xa.min, dy = ya.max - ya.min;
  var p = Math.min(w / dx, h / (dy * ratio));
  var gw = p * dx, gh = p * dy * ratio;
  grids[0] = { left: Math.round(l + (w - gw) / 2), top: Math.round(t + (h - gh) / 2), width: Math.round(gw), height: Math.round(gh), containLabel: false };
  if (ya.name) ya._gap = 30;
}

/* ───────────────────────────── heatmap as cells (works on value axes, under shapes) */
function centresToEdges(c) {
  var e = [];
  for (var i = 0; i < c.length; i++) {
    var lo = i > 0 ? (c[i] + c[i - 1]) / 2 : c[i] - ((c.length > 1 ? c[1] - c[0] : 1) / 2);
    var hi = i < c.length - 1 ? (c[i] + c[i + 1]) / 2 : c[i] + ((c.length > 1 ? c[i] - c[i - 1] : 1) / 2);
    e.push([lo, hi]);
  }
  return e;
}
function heatmapSeries(T, col, tr, base, xa, ya, conv, AX, visualMaps, axisTime) {
  var z = arr(tr.z).map(arr);
  var xs = arr(tr.x), ys = arr(tr.y);
  if (!xs.length) xs = (z[0] || []).map(function (_, i) { return i; });
  if (!ys.length) ys = z.map(function (_, i) { return i; });
  var xCat = AX[xa] && AX[xa].kind === 'category', yCat = AX[ya] && AX[ya].kind === 'category';
  var xc = xCat ? xs.map(function (v) { return AX[xa].cats.indexOf(String(v)); }) : xs.map(Number);
  var yc = yCat ? ys.map(function (v) { return AX[ya].cats.indexOf(String(v)); }) : ys.map(Number);
  var xe = xCat ? xc.map(function (i) { return [i - 0.5, i + 0.5]; }) : centresToEdges(xc);
  var ye = yCat ? yc.map(function (i) { return [i - 0.5, i + 0.5]; }) : centresToEdges(yc);
  var flat = []; z.forEach(function (r) { r.forEach(function (v) { if (isNum(v)) flat.push(v); }); });
  var zmin = isNum(tr.zmin) ? tr.zmin : Math.min.apply(null, flat.length ? flat : [0]), zmax = isNum(tr.zmax) ? tr.zmax : Math.max.apply(null, flat.length ? flat : [1]);
  if (tr.zmid !== undefined && isNum(tr.zmid)) { var m = Math.max(Math.abs(zmax - tr.zmid), Math.abs(zmin - tr.zmid)); zmin = tr.zmid - m; zmax = tr.zmid + m; }
  var scale = scaleOf(tr.colorscale, col);
  if (tr.reversescale) scale = scale.map(function (s) { return [1 - s[0], s[1]]; }).reverse();
  if (tr.showscale !== false) visualMaps.push({ min: zmin, max: zmax, scale: scale, title: titleText((tr.colorbar || {}).title) });
  var data = [];
  z.forEach(function (row, iy) {
    row.forEach(function (v, ix) {
      if (!isNum(v) || !xe[ix] || !ye[iy]) return;
      data.push({ value: [xe[ix][0], xe[ix][1], ye[iy][0], ye[iy][1], v], _i: data.length, _cell: [iy, ix], itemStyle: { color: interp(scale, (v - zmin) / ((zmax - zmin) || 1)) } });
    });
  });
  var gx = isNum(tr.xgap) ? tr.xgap / 2 : 0.5, gy = isNum(tr.ygap) ? tr.ygap / 2 : 0.5;
  var texts = arr(tr.text);
  var s = Object.assign(base, {
    type: 'custom', data: data, encode: { x: [0, 1], y: [2, 3] }, z: 2,
    renderItem: function (params, api) {
      var p0 = api.coord([api.value(0), api.value(3)]), p1 = api.coord([api.value(1), api.value(2)]);
      var x = Math.min(p0[0], p1[0]) + gx, y = Math.min(p0[1], p1[1]) + gy;
      var w = Math.abs(p1[0] - p0[0]) - 2 * gx, h = Math.abs(p1[1] - p0[1]) - 2 * gy;
      return { type: 'rect', shape: { x: x, y: y, width: Math.max(0, w), height: Math.max(0, h), r: 2 }, style: api.style({ stroke: null }) };
    }
  });
  /* the tooltip receives the index into data; _cell is [row, column] of z */
  s._tip = function (k) {
    var d = data[k] || {}, ij = d._cell || [0, 0];
    var ctx = { tr: tr, i: ij[0], x: xs[ij[1]], y: ys[ij[0]], z: (z[ij[0]] || [])[ij[1]], axisTime: axisTime };
    if (tr.hovertemplate) return fill(tr.hovertemplate, ctx);
    var t = texts[ij[0]] && Array.isArray(texts[ij[0]]) ? texts[ij[0]][ij[1]] : null;
    if (t !== null && t !== undefined && t !== '') return String(t);
    return esc(dflt(ctx.y)) + ' · ' + esc(dflt(ctx.x)) + ': <b>' + dflt(ctx.z) + '</b>';
  };
  return s;
}

/* ───────────────────────────── error bars */
function errorBars(T, col, tr, pts, base, color0) {
  var ey = tr.error_y || null, ex = tr.error_x || null;
  function amt(e, i, minus) {
    if (!e || e.visible === false) return 0;
    var a = minus && e.symmetric === false ? arr(e.arrayminus) : arr(e.array);
    var v = a.length ? a[i] : e.value;
    return isNum(+v) ? +v : 0;
  }
  var data = pts.map(function (p, i) { return { value: [p[0], p[1], amt(ey, i, false), amt(ey, i, true), amt(ex, i, false), amt(ex, i, true)], _i: i }; }).filter(function (d) { return d.value[0] !== null && d.value[1] !== null; });
  var c = col((ey || ex).color) || color0, w = isNum((ey || ex).thickness) ? (ey || ex).thickness : 1.2, cap = isNum((ey || ex).width) ? (ey || ex).width : 0;
  return { type: 'custom', name: '_err' + base._ti, xAxisIndex: base.xAxisIndex, yAxisIndex: base.yAxisIndex, silent: true, tooltip: { show: false }, z: 2, data: data, encode: { x: 0, y: 1 },
    renderItem: function (params, api) {
      var x = api.value(0), y = api.value(1), kids = [];
      var st = { stroke: c, lineWidth: w };
      if (ey) {
        var a = api.coord([x, y + api.value(2)]), b = api.coord([x, y - api.value(3)]);
        kids.push({ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: st });
        if (cap) { kids.push({ type: 'line', shape: { x1: a[0] - cap, y1: a[1], x2: a[0] + cap, y2: a[1] }, style: st }); kids.push({ type: 'line', shape: { x1: b[0] - cap, y1: b[1], x2: b[0] + cap, y2: b[1] }, style: st }); }
      }
      if (ex) {
        var e = api.coord([x + api.value(4), y]), f = api.coord([x - api.value(5), y]);
        kids.push({ type: 'line', shape: { x1: e[0], y1: e[1], x2: f[0], y2: f[1] }, style: st });
      }
      return { type: 'group', children: kids };
    } };
}

/* ───────────────────────────── shapes, annotations and filled polygons */
function parsePath(d) {
  var toks = String(d || '').replace(/([MLZHVmlzhv])/g, ' $1 ').replace(/,/g, ' ').trim().split(/\s+/);
  var pts = [], closed = false, i = 0, cmd = 'M', cur = [0, 0];
  while (i < toks.length) {
    var t = toks[i];
    if (/^[MLZHVmlzhv]$/.test(t)) { cmd = t; i++; if (cmd === 'Z' || cmd === 'z') closed = true; continue; }
    if (cmd === 'M' || cmd === 'L') { cur = [parseFloat(toks[i]), parseFloat(toks[i + 1])]; pts.push(cur); i += 2; }
    else if (cmd === 'H') { cur = [parseFloat(toks[i]), cur[1]]; pts.push(cur); i += 1; }
    else if (cmd === 'V') { cur = [cur[0], parseFloat(toks[i])]; pts.push(cur); i += 1; }
    else i++;
  }
  return { pts: pts.filter(function (p) { return isNum(p[0]) && isNum(p[1]); }), closed: closed };
}
function overlaySeries(T, col, items, anchor, z, conv, xIds, yIds) {
  return {
    type: 'custom', name: '_overlay' + z, silent: true, tooltip: { show: false }, z: z, clip: false,
    xAxisIndex: anchor.xi || 0, yAxisIndex: anchor.yi || 0,
    data: [[anchor.x, anchor.y]], encode: { x: 0, y: 1 },
    renderItem: function (params, api) {
      var cs = params.coordSys;
      function px(x, ref) { return ref === 'paper' ? cs.x + Number(x) * cs.width : api.coord([conv(xIds[0], x), anchor.y])[0]; }
      function py(y, ref) { return ref === 'paper' ? cs.y + (1 - Number(y)) * cs.height : api.coord([anchor.x, conv(yIds[0], y)])[1]; }
      function pt(x, y, xr, yr) { if (xr !== 'paper' && yr !== 'paper') { var c = api.coord([conv(xIds[0], x), conv(yIds[0], y)]); return c; } return [px(x, xr), py(y, yr)]; }
      var kids = [];
      items.forEach(function (it) {
        if (it.kind === 'poly') {
          if (it.pts.length < 3) return;
          kids.push({ type: 'polygon', shape: { points: it.pts.map(function (p) { return api.coord(p); }) }, style: { fill: it.fill, stroke: it.stroke || null, lineWidth: it.width || 0 }, silent: true });
          return;
        }
        if (it.kind === 'text') {
          var xr = it.xref === 'paper' ? 'paper' : 'data', yr = it.yref === 'paper' ? 'paper' : 'data';
          var p = pt(it.x, it.y, xr, yr);
          var f = it.font || {};
          var align = it.xanchor === 'left' ? 'left' : it.xanchor === 'right' ? 'right' : 'center';
          var va = it.yanchor === 'top' ? 'top' : it.yanchor === 'bottom' ? 'bottom' : 'middle';
          kids.push({ type: 'text', x: p[0] + (isNum(it.xshift) ? it.xshift : 0), y: p[1] - (isNum(it.yshift) ? it.yshift : 0), silent: true,
            style: { text: strip(it.text), fill: col(f.color) || T.ink3, font: (/<b>/.test(it.text) ? '600 ' : '500 ') + (f.size || 10) + 'px ' + T.fontUI, align: align, verticalAlign: va,
              backgroundColor: it.bgcolor ? col(it.bgcolor) : null, padding: it.bgcolor ? [2, 4] : 0 } });
          return;
        }
        var xref = it.xref === 'paper' ? 'paper' : 'data', yref = it.yref === 'paper' ? 'paper' : 'data';
        var ln = it.line || {};
        var stroke = ln.width === 0 ? null : (col(ln.color) || T.axis);
        var st = { fill: col(it.fillcolor) || null, stroke: stroke, lineWidth: isNum(ln.width) ? ln.width : 1, lineDash: dashOf(ln.dash), opacity: isNum(it.opacity) ? it.opacity : 1 };
        if (it.type === 'line') {
          var a = pt(it.x0, it.y0, xref, yref), b = pt(it.x1, it.y1, xref, yref);
          kids.push({ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: { stroke: stroke, lineWidth: st.lineWidth, lineDash: st.lineDash, opacity: st.opacity }, silent: true });
        } else if (it.type === 'rect') {
          var c = pt(it.x0, it.y0, xref, yref), d = pt(it.x1, it.y1, xref, yref);
          kids.push({ type: 'rect', shape: { x: Math.min(c[0], d[0]), y: Math.min(c[1], d[1]), width: Math.abs(d[0] - c[0]), height: Math.abs(d[1] - c[1]) }, style: st, silent: true });
        } else if (it.type === 'circle') {
          var e = pt(it.x0, it.y0, xref, yref), g = pt(it.x1, it.y1, xref, yref);
          kids.push({ type: 'ellipse', shape: { cx: (e[0] + g[0]) / 2, cy: (e[1] + g[1]) / 2, rx: Math.abs(g[0] - e[0]) / 2, ry: Math.abs(g[1] - e[1]) / 2 }, style: st, silent: true });
        } else if (it.type === 'path') {
          var pp = parsePath(it.path);
          if (pp.pts.length < 2) return;
          var P = pp.pts.map(function (q) { return pt(q[0], q[1], xref, yref); });
          kids.push(pp.closed ? { type: 'polygon', shape: { points: P }, style: st, silent: true } : { type: 'polyline', shape: { points: P }, style: { stroke: stroke, lineWidth: st.lineWidth, lineDash: st.lineDash, fill: null }, silent: true });
        }
      });
      return { type: 'group', children: kids };
    }
  };
}

/* ───────────────────────────── radar */
function buildRadar(T, col, traces, L, W, H) {
  var pl = L.polar || {}, ra = pl.radialaxis || {}, aa = pl.angularaxis || {};
  var labels = [];
  traces.forEach(function (t) { arr(t.theta).forEach(function (th) { if (labels.indexOf(String(th)) < 0) labels.push(String(th)); }); });
  var range = Array.isArray(ra.range) ? ra.range : [0, 100];
  var lg = L.legend || {};
  var names = traces.filter(function (t) { return t.showlegend !== false && t.name; }).map(function (t) { return t.name; });
  var showLegend = L.showlegend === true || (L.showlegend === undefined && names.length > 1);
  var series = traces.map(function (t, i) {
    var r = arr(t.r), th = arr(t.theta).map(String);
    var vals = labels.map(function (lab) { var k = th.indexOf(lab); return k >= 0 && isNum(+r[k]) ? +r[k] : 0; });
    var c = col((t.line || {}).color || (t.marker || {}).color) || T.cat[i % 8];
    return { name: t.name || ('trace ' + i), value: vals, symbol: 'circle', symbolSize: 4,
      lineStyle: { color: c, width: isNum((t.line || {}).width) ? t.line.width : 2 }, itemStyle: { color: c },
      areaStyle: t.fill === 'toself' || t.fill === 'tonext' ? { color: col(t.fillcolor) || withAlpha(c, 0.18) } : undefined, _t: t };
  });
  var small = W < 420;
  return {
    legend: showLegend ? legendOf(T, names, (isNum(lg.y) && lg.y > 0.5) ? 'top' : 'bottom', traces) : { show: false },
    tooltip: QKC.tooltip(T, { trigger: 'item', formatter: function (p) {
      var s = series[p.dataIndex] || {}, t = s._t || {};
      return '<b>' + esc(p.name) + '</b>' + labels.map(function (lab, k) {
        var v = p.value[k];
        if (t.hovertemplate) { var f = fill(t.hovertemplate, { tr: t, i: k, r: v, theta: lab }); return '<br>' + f.replace(/<div[\s\S]*<\/div>$/, ''); }
        return '<br>' + esc(lab) + ': ' + dflt(v);
      }).join('');
    } }),
    radar: { indicator: labels.map(function (l) { return { name: l, min: range[0], max: range[1] }; }), radius: small ? '58%' : '66%', center: ['50%', showLegend ? '48%' : '52%'],
      splitNumber: 4, axisName: { color: T.ink2, fontFamily: T.fontUI, fontSize: small ? 9 : (((aa.tickfont || {}).size) || 10.5) },
      splitLine: { lineStyle: { color: T.grid } }, axisLine: { lineStyle: { color: T.grid } }, splitArea: { show: false } },
    series: [{ type: 'radar', data: series, emphasis: { lineStyle: { width: 3 } } }]
  };
}

/* ───────────────────────────── the Plotly API */
function newPlot(node, traces, layout, config) {
  var el = typeof node === 'string' ? document.getElementById(node) : node;
  if (!el) return Promise.resolve(null);
  var L = layout || {};
  el.__pl = { traces: traces || [], layout: L };
  /* height: the layout's, else the element's own CSS height, else a default */
  if (isNum(L.height)) el.style.height = L.height + 'px';
  else if (!el.style.height) {
    var hgt = el.getBoundingClientRect().height;
    el.style.height = (hgt > 60 ? Math.round(hgt) : 360) + 'px';
  }
  if (!el.__plh) el.__plh = {};
  if (!el.on) {
    el.on = function (evt, fn) { (el.__plh[evt] = el.__plh[evt] || []).push(fn); return el; };
    el.removeAllListeners = function (evt) { if (evt) delete el.__plh[evt]; else el.__plh = {}; };
  }
  var chart = QKC.mount(el, function (T) {
    var pl = el.__pl;
    var opt = build(T, el, pl.traces, pl.layout);
    el.__plSeries = opt.series || [];
    /* zero lines */
    (opt.yAxis || []).forEach(function (a, i) {
      if (!a._zero) return;
      opt.series.push({ type: 'line', name: '_zero' + i, data: [], yAxisIndex: i, xAxisIndex: 0, silent: true, tooltip: { show: false },
        markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: a._zero, type: 'solid', width: 1 }, data: [{ yAxis: 0 }] } });
    });
    return opt;
  }, {
    label: (L.title && titleText(L.title)) || el.getAttribute('aria-label') || 'Chart',
    onClick: function (p) {
      var pl = el.__pl;
      var s = (el.__plSeries || [])[p.seriesIndex] || null;
      var ti = s && s._ti !== undefined ? s._ti : null;
      var trs = (pl.traces || []).filter(function (t) { return t && t.visible !== false; });
      var tr = ti !== null ? trs[ti] : null;
      var i = p.data && p.data._i !== undefined ? p.data._i : p.dataIndex;
      var cd = tr ? pick(tr.customdata, i) : undefined;
      var hs = el.__plh.plotly_click || [];
      if (hs.length) hs.forEach(function (fn) { try { fn({ points: [{ customdata: cd, pointIndex: i, pointNumber: i, curveNumber: ti, x: tr ? pick(tr.x, i) : undefined, y: tr ? pick(tr.y, i) : undefined, data: tr }] }); } catch (e) { if (root.console) console.error(e); } });
    }
  });
  if (chart) {
    /* equal-aspect plots and stacked grids depend on the size: rebuild on a width change */
    var lastW = el.clientWidth;
    if (root.ResizeObserver && !el.__plro) {
      el.__plro = new ResizeObserver(function () {
        var w = el.clientWidth;
        if (Math.abs(w - lastW) < 4 || !el.__qkc) return;
        lastW = w;
        clearTimeout(el.__plt);
        el.__plt = setTimeout(function () { if (el.__qkc && el.isConnected) el.__qkc.paint(); }, 120);
      });
      el.__plro.observe(el);
    }
    chart.on('mouseover', function () { el.style.cursor = (el.__plh.plotly_click || []).length ? 'pointer' : ''; });
  }
  return Promise.resolve(el);
}
function purge(node) {
  var el = typeof node === 'string' ? document.getElementById(node) : node;
  if (!el) return;
  if (el.__plro) { try { el.__plro.disconnect(); } catch (e) { /* gone */ } el.__plro = null; }
  if (el.__qkc) { try { el.__qkc.chart.dispose(); } catch (e) { /* gone */ } if (el.__qkc.ro) { try { el.__qkc.ro.disconnect(); } catch (e) { /* gone */ } } el.__qkc = null; }
}

root.Plotly = { newPlot: newPlot, react: newPlot, purge: purge, version: 'qk-echarts-shim',
  relayout: function (node, upd) { var el = typeof node === 'string' ? document.getElementById(node) : node; if (el && el.__pl) { Object.assign(el.__pl.layout, upd || {}); if (el.__qkc) el.__qkc.paint(); } return Promise.resolve(el); },
  Plots: { resize: function (node) { var el = typeof node === 'string' ? document.getElementById(node) : node; if (el && el.__qkc) el.__qkc.chart.resize(); } } };
root.PlotlyEC = { build: build, fmtSpec: fmtSpec, fill: fill, cssColor: cssColor };
})(window);
