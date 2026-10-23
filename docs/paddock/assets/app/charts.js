/* The Quant Paddock — chart helpers (PD.ch) on the kit's ECharts layer (QKC.mount, tokens, axis,
 * tooltip). Every helper takes a target (element or id) first, builds from the design tokens at paint
 * time (so the theme toggle repaints it) and writes a short note instead of a blank box when its data
 * is missing. Team colours are lifted to 3:1 on the card; a team's second driver is dashed. */
(function (PD) {
'use strict';

var QK = window.QK, QKC = window.QKC;
var esc = PD.esc, isNum = PD.isNum;

function node(x) { return typeof x === 'string' ? document.getElementById(x) : x; }
function none(x, text) { var n = node(x); if (n) { n.classList.add('pd-chart-empty'); n.innerHTML = '<div class="pd-chart-msg">' + esc(text) + '</div>'; } return null; }
function lift(hex, T) { return QK.color.parse(hex) ? QK.color.ensure(hex, T.s1, 3) : hex; }
function tip(T, extra) { return QKC.tooltip(T, extra); }
function ax(T, o) { return QKC.axis(T, o); }
function row(c, name, v) { return QKC.tipRow(c, name, v); }
function head(t, T) { return '<div style="font-weight:600;margin-bottom:4px">' + esc(t) + '</div>'; }
function mount(x, build, label, o) {
  var n = node(x);
  if (!n) return null;
  n.classList.remove('pd-chart-empty');
  n.innerHTML = '';
  var opts = Object.assign({ label: label }, o || {});
  return QKC.mount(n, build, opts);
}
function legend(T, o) { return Object.assign({ top: 0, left: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 4, textStyle: { color: T.ink2, fontSize: 11 }, type: 'scroll', pageTextStyle: { color: T.ink3 } }, o || {}); }
function narrow(x) { var n = node(x); return n ? n.clientWidth < 560 : false; }

/* Colour and dash per driver: the team colour; the team's second-listed driver dashed. */
function styleMap(ids, teams) {
  var seen = {}, out = {};
  ids.forEach(function (id) {
    var t = (teams && teams[id]) || PD.driverTeam(id) || null;
    var key = t || id;
    out[id] = { colour: t ? PD.teamColour(t) : PD.driverColour(id), dash: !!seen[key], team: t };
    seen[key] = true;
  });
  return out;
}
function orderOf(obj, order) {
  var keys = Object.keys(obj || {});
  if (!order || !order.length) return keys;
  var has = {};
  keys.forEach(function (k) { has[k] = 1; });
  var headK = order.filter(function (k) { return has[k]; });
  return headK.concat(keys.filter(function (k) { return headK.indexOf(k) < 0; }));
}

// ── race control bands ────────────────────────────────────────────────────

function controlBands(control, nLaps) {
  var evs = (control || []).filter(function (e) { return e && isNum(e.lap) && (e.kind === 'SC' || e.kind === 'VSC' || e.kind === 'RED') && !/CHEQUERED/i.test(e.message || ''); })
    .slice().sort(function (a, b) { return (a.lap - b.lap) || ((a.t_ms || 0) - (b.t_ms || 0)); });
  var bands = [], open = {};
  evs.forEach(function (e) {
    var m = String(e.message || '').toUpperCase(), k = e.kind;
    var ending = /(IN THIS LAP|ENDING|WITHDRAWN|ENDED|RESUM|TRACK CLEAR|GREEN)/.test(m);
    if (!ending) { if (open[k] === undefined) open[k] = e.lap; }
    else if (open[k] !== undefined) { bands.push({ kind: k, from: open[k], to: Math.max(e.lap, open[k] + 0.5) }); delete open[k]; }
  });
  Object.keys(open).forEach(function (k) { bands.push({ kind: k, from: open[k], to: k === 'RED' ? open[k] + 1 : Math.min(nLaps || open[k] + 3, open[k] + 3) }); });
  return bands;
}
function bandArea(bands, T) {
  if (!bands || !bands.length) return undefined;
  return { silent: true, data: bands.map(function (b) {
    var c = b.kind === 'RED' ? QKC.hexA(T.down || PD.col('down'), 0.16) : QKC.hexA(T.sun || '#ffc94d', b.kind === 'VSC' ? 0.08 : 0.15);
    return [{ xAxis: b.from - 0.5, itemStyle: { color: c }, label: { show: true, position: 'insideTop', formatter: b.kind, color: T.ink3, fontSize: 9 } }, { xAxis: b.to + 0.5 }];
  }) };
}

// ── lap charts: positions and gaps ────────────────────────────────────────

/* series: {id: [value per lap]}; o: {order, teams, control, invert, yMin, yMax, yName, fmt(v), cap, label, endLabels} */
function lapLines(x, series, o) {
  o = o || {};
  var ids = orderOf(series, o.order).filter(function (id) { return (series[id] || []).some(isNum); });
  if (!ids.length) return none(x, o.emptyText || 'No lap data for this race.');
  var st = styleMap(ids, o.teams);
  var n = 0;
  ids.forEach(function (id) { n = Math.max(n, series[id].length); });
  var bands = o.control ? controlBands(o.control, n) : [];
  var f = o.fmt || function (v) { return PD.num(v, 1); };
  return mount(x, function (T) {
    var ser = ids.map(function (id, i) {
      var c = lift(st[id].colour, T);
      return {
        type: 'line', name: PD.driverCode(id), id: id, showSymbol: false, symbol: 'circle', symbolSize: 6, connectNulls: false,
        data: series[id].map(function (v, k) { return [k + 1, isNum(v) ? (o.cap && v > o.cap ? o.cap : v) : null]; }),
        lineStyle: { width: o.width || 1.8, color: c, type: st[id].dash ? [4, 3] : 'solid' }, itemStyle: { color: c },
        emphasis: { focus: 'series', lineStyle: { width: 3 } },
        endLabel: o.endLabels === false ? undefined : { show: true, formatter: PD.driverCode(id), color: c, fontSize: 10, fontWeight: 600, fontFamily: T.fontNum, distance: 4 },
        labelLayout: { moveOverlap: 'shiftY' },
        markArea: i === 0 ? bandArea(bands, T) : undefined
      };
    });
    return {
      grid: { left: 6, right: o.endLabels === false ? 14 : 44, top: o.yName ? 26 : 12, bottom: 24, containLabel: true },
      xAxis: ax(T, { type: 'value', min: 1, max: n, line: true, split: false, name: 'Lap', nameLocation: 'middle', nameGap: 26, fmt: function (v) { return Math.round(v); } }),
      yAxis: ax(T, { inverse: !!o.invert, min: o.yMin, max: o.yMax, name: o.yName, nameAlign: 'left', nameLocation: o.invert ? 'start' : 'end', interval: o.interval, fmt: o.yFmt }),
      tooltip: tip(T, { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: T.axis } },
        formatter: function (ps) {
          var lap = ps[0] ? Math.round(ps[0].value[0]) : '';
          var list = ps.filter(function (p) { return isNum(p.value[1]); }).sort(function (a, b) { return o.invert ? a.value[1] - b.value[1] : b.value[1] - a.value[1]; });
          var cols = list.length > 12 ? 2 : 1;
          return '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">Lap ' + lap + '</div><div style="display:grid;grid-template-columns:repeat(' + cols + ',auto);column-gap:14px">' +
            list.map(function (p) { var v = series[ids[p.seriesIndex]][lap - 1]; return row(p.color, p.seriesName, f(v)); }).join('') + '</div>';
        } }),
      series: ser
    };
  }, o.label);
}

// ── horizontal bars with optional whiskers and market ticks ───────────────

/* rows: [{label, value, colour, href, lo, hi, mark (second value, e.g. market), sub}]; o: {fmt, name, markName, diverging, ref, min, max, labelWidth, label,
 * xName (value-axis title; shows the axis when bar labels would hide it)} */
function hbars(x, rows, o) {
  o = o || {};
  var list = (rows || []).filter(function (r) { return isNum(r.value); });
  if (!list.length) return none(x, o.emptyText || 'Nothing to show.');
  var f = o.fmt || function (v) { return PD.num(v, 2); };
  var hasMark = list.some(function (r) { return isNum(r.mark); });
  var hasErr = list.some(function (r) { return isNum(r.lo) && isNum(r.hi); });
  return mount(x, function (T) {
    var cats = list.map(function (r) { return r.label; });
    var ya = ax(T, { type: 'category', data: cats, split: false, inverse: true });
    ya.axisLabel.color = T.ink2; ya.axisLabel.width = o.labelWidth || (narrow(x) ? 70 : 120); ya.axisLabel.overflow = 'truncate'; ya.axisLabel.fontSize = 11;
    var series = [{
      type: 'bar', name: o.name || 'Value', barMaxWidth: 16, barCategoryGap: '28%', z: 2,
      data: list.map(function (r) {
        var c = o.diverging ? (r.value >= 0 ? T.pos : T.neg) : (r.colour ? lift(r.colour, T) : T.model);
        return { value: r.value, href: r.href, itemStyle: { color: c, borderRadius: r.value < 0 ? [4, 0, 0, 4] : [0, 4, 4, 0] } };
      }),
      label: o.labels === false || hasErr ? undefined : { show: true, position: 'right', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: function (p) { return f(p.value); } },
      markLine: isNum(o.ref) ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ xAxis: o.ref }] } : undefined,
      cursor: list.some(function (r) { return r.href; }) ? 'pointer' : 'default'
    }];
    if (hasErr) series.push({ type: 'custom', name: 'interval', silent: true, z: 3, data: list.map(function (r, i) { return [r.lo, r.hi, i]; }),
      renderItem: function (p, api) {
        if (!isNum(api.value(0))) return null;
        var a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
        var st = { stroke: T.ink2, lineWidth: 1.2 };
        return { type: 'group', children: [{ type: 'line', shape: { x1: a[0], y1: a[1], x2: b[0], y2: b[1] }, style: st },
          { type: 'line', shape: { x1: a[0], y1: a[1] - 4, x2: a[0], y2: a[1] + 4 }, style: st }, { type: 'line', shape: { x1: b[0], y1: b[1] - 4, x2: b[0], y2: b[1] + 4 }, style: st }] };
      }, encode: { x: [0, 1], y: 2 } });
    if (hasMark) series.push({ type: 'scatter', name: o.markName || 'Market', z: 4, symbol: 'rect', symbolSize: [3, 16], itemStyle: { color: T.market },
      data: list.map(function (r, i) { return isNum(r.mark) ? [r.mark, i] : null; }).filter(Boolean) });
    return {
      grid: { left: 6, right: hasErr ? 16 : 48, top: hasMark ? 26 : 8, bottom: o.xName ? 30 : 8, containLabel: true },
      legend: hasMark ? legend(T, { data: [o.name || 'Model', o.markName || 'Market'], icon: 'roundRect', itemWidth: 10, itemHeight: 10 }) : undefined,
      xAxis: (function () { var a = ax(T, { min: o.min, max: o.max, fmt: o.axisFmt || f, name: o.xName, nameLocation: 'middle', nameGap: 24 }); if (o.labels !== false && !hasErr && !o.xName) { a.axisLabel.show = !!o.axisLabels; } return a; })(),
      yAxis: ya,
      tooltip: tip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(T.ink1, 0.04) } },
        formatter: function (ps) {
          var r = list[ps[0].dataIndex];
          return head(r.full || r.label, T) + (r.sub ? '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(r.sub) + '</div>' : '') + row(ps[0].color, o.name || 'Value', f(r.value)) +
            (isNum(r.lo) && isNum(r.hi) ? row(T.ink3, o.errName || 'Interval', f(r.lo) + ' to ' + f(r.hi)) : '') + (isNum(r.mark) ? row(T.market, o.markName || 'Market', f(r.mark)) : '');
        } }),
      series: series
    };
  }, o.label);
}

// ── lines over rounds / years (with optional ±se bands) ───────────────────

/* series: [{name, data: [[x, y]...] or y per x, colour, dash, width, band: [[x, lo, hi]...], faint, area}], o: {xs (category labels), xName, yName, yFmt, xFmt, inverse, legend, ref, endLabels, step, xType} */
function lines(x, series, o) {
  o = o || {};
  var list = (series || []).filter(function (s) { return (s.data || []).some(function (d) { return Array.isArray(d) ? isNum(d[1]) : isNum(d); }); });
  if (!list.length) return none(x, o.emptyText || 'No data yet.');
  var xType = o.xType || (o.xs ? 'category' : 'value');
  return mount(x, function (T) {
    var out = [];
    var main = list.filter(function (s) { return !s.faint; });
    list.forEach(function (s, i) {
      var c = s.colour ? lift(s.colour, T) : T.cat[main.indexOf(s) % 8];
      if (s.faint) c = QKC.hexA(c, 0.28);
      if (s.band && s.band.length > 1) {
        /* the ±se band as one polygon (a custom series: stacking does not work on a value x axis) */
        var band = s.band.filter(function (b) { return isNum(b[0]) && isNum(b[1]) && isNum(b[2]); });
        out.push({ type: 'custom', name: s.name + ' band', silent: true, z: 0, tooltip: { show: false }, data: band.map(function (b) { return [b[0], b[1], b[2]]; }), encode: { x: 0, y: [1, 2] },
          renderItem: function (p, api) {
            if (p.dataIndex !== 0) return null;
            var top = band.map(function (b) { return api.coord([b[0], b[2]]); }), bot = band.map(function (b) { return api.coord([b[0], b[1]]); }).reverse();
            return { type: 'polygon', shape: { points: top.concat(bot) }, style: { fill: QKC.hexA(c, 0.18) } };
          } });
      }
      out.push({
        type: 'line', name: s.name, data: s.data, showSymbol: !!s.symbols, symbolSize: 6, symbol: 'circle', step: o.step || s.step || false, connectNulls: true, z: s.faint ? 1 : 3,
        lineStyle: { width: s.width || (s.faint ? 1 : 2), color: c, type: s.dash ? [5, 4] : 'solid' }, itemStyle: { color: c }, silent: !!s.faint,
        tooltip: s.faint && o.faintTip === false ? { show: false } : undefined,
        areaStyle: s.area ? { color: QKC.hexA(c, 0.16) } : undefined,
        emphasis: s.faint ? { disabled: true } : { focus: 'series' },
        endLabel: o.endLabels && !s.faint ? { show: true, formatter: s.short || s.name, color: c, fontSize: 10.5, fontWeight: 600, distance: 5 } : undefined,
        labelLayout: { moveOverlap: 'shiftY' },
        markLine: i === 0 && isNum(o.ref) ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: o.ref }] } : undefined
      });
    });
    var named = list.filter(function (s) { return !s.faint; }).map(function (s) { return s.name; });
    return {
      grid: { left: 6, right: o.endLabels ? 70 : 16, top: (o.legend !== false && named.length > 1 && !o.endLabels ? 30 : 12) + (o.yName ? 22 : 0), bottom: o.xName ? 30 : 8, containLabel: true },
      legend: o.legend !== false && named.length > 1 && !o.endLabels ? legend(T, { data: named }) : undefined,
      xAxis: ax(T, { type: xType, data: o.xs, line: true, split: false, boundaryGap: xType === 'category' ? false : undefined, fmt: o.xFmt, min: o.xMin, max: o.xMax, name: o.xName, nameLocation: 'middle', nameGap: 26, scale: xType === 'value' }),
      yAxis: ax(T, { name: o.yName, nameAlign: 'left', nameLocation: o.inverse ? 'start' : 'end', fmt: o.yFmt, inverse: !!o.inverse, scale: o.yScale !== false, min: o.yMin, max: o.yMax }),
      tooltip: tip(T, { trigger: 'axis',
        formatter: function (ps) {
          var vis = ps.filter(function (p) { return !/ band$/.test(p.seriesName); });
          var label = vis[0] ? (o.xLabel ? o.xLabel(vis[0].axisValue) : vis[0].axisValueLabel) : '';
          var shown = vis.filter(function (p) { var s = list.filter(function (q) { return q.name === p.seriesName; })[0]; return !(s && s.faint && o.faintTip === false); })
            .sort(function (a, b) { var va = val(a), vb = val(b); return o.inverse ? va - vb : vb - va; }).slice(0, 14);
          return '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(label) + '</div>' + shown.map(function (p) { return row(p.color, p.seriesName, o.yFmt ? o.yFmt(val(p)) : PD.num(val(p), 1)); }).join('');
        } }),
      series: out
    };
  }, o.label);
}
function val(p) { var v = p.value; return Array.isArray(v) ? v[v.length - 1] : v; }

// ── columns (vertical bars, optional line on a second axis) ───────────────

/* o: {cats, series: [{name, data, colour, type: 'bar'|'line'|'scatter', axis: 1, stack}], yName, y2Name, fmt, y2Fmt, hrefs, colours (per bar of series 0), label} */
function columns(x, o) {
  if (!o.cats || !o.cats.length) return none(x, o.emptyText || 'No data yet.');
  return mount(x, function (T) {
    var two = o.series.some(function (s) { return s.axis === 1; });
    var ser = o.series.map(function (s, i) {
      var c = s.colour ? lift(s.colour, T) : T.cat[i % 8];
      var base = { name: s.name, yAxisIndex: s.axis === 1 ? 1 : 0, z: s.type === 'bar' || !s.type ? 2 : 4 };
      if (s.type === 'line') return Object.assign(base, { type: 'line', data: s.data, symbol: 'circle', symbolSize: 6, lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, connectNulls: true });
      if (s.type === 'scatter') return Object.assign(base, { type: 'scatter', data: s.data, symbol: s.symbol || 'circle', symbolSize: s.size || 10, itemStyle: { color: c } });
      return Object.assign(base, { type: 'bar', stack: s.stack, barMaxWidth: 26, data: s.data.map(function (v, j) {
        var cc = o.colours && i === 0 && o.colours[j] ? lift(o.colours[j], T) : (s.colours && s.colours[j] ? lift(s.colours[j], T) : c);
        return { value: v, href: o.hrefs ? o.hrefs[j] : undefined, itemStyle: { color: cc, borderRadius: s.stack ? 0 : [3, 3, 0, 0] } };
      }), label: s.labels ? { show: true, position: 'top', color: T.ink2, fontSize: 10, fontFamily: T.fontNum, formatter: function (p) { return s.fmt ? s.fmt(p.value) : PD.num(p.value, 0); } } : undefined,
        markLine: isNum(s.ref) ? { silent: true, symbol: 'none', lineStyle: { color: T.ink3, type: [4, 3] }, label: { formatter: s.refLabel || '', color: T.ink3, fontSize: 10 }, data: [{ xAxis: s.ref }] } : undefined });
    });
    var ya = [ax(T, { name: o.yName, nameAlign: 'left', fmt: o.fmt, min: o.yMin, max: o.yMax })];
    if (two) { var a2 = ax(T, { name: o.y2Name, nameAlign: 'right', nameLocation: o.y2Inverse ? 'start' : 'end', fmt: o.y2Fmt, min: o.y2Inverse ? 1 : 0, max: o.y2Max, split: false, inverse: !!o.y2Inverse }); a2.position = 'right'; ya.push(a2); }
    var xa = ax(T, { type: 'category', data: o.cats, split: false, line: true, name: o.xName, nameLocation: 'middle', nameGap: 26 });
    if (o.rotate) xa.axisLabel.rotate = o.rotate;
    return {
      grid: { left: 6, right: two ? 10 : 14, top: (o.series.length > 1 ? 30 : 10) + (o.yName || o.y2Name ? 18 : 0), bottom: o.xName ? 30 : 6, containLabel: true },
      legend: o.series.length > 1 ? legend(T) : undefined,
      xAxis: xa, yAxis: ya,
      tooltip: tip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(T.ink1, 0.04) } },
        formatter: function (ps) { return head(o.tipLabel ? o.tipLabel(ps[0].dataIndex) : ps[0].name, T) + ps.map(function (p) { var s = o.series[p.seriesIndex] || {}; var v = Array.isArray(p.value) ? p.value[1] : p.value; return isNum(v) ? row(p.color, p.seriesName, s.fmt ? s.fmt(v) : (o.fmt ? o.fmt(v) : PD.num(v, 1))) : ''; }).join(''); } }),
      series: ser
    };
  }, o.label);
}

// ── heatmaps ──────────────────────────────────────────────────────────────

/* Position distribution: rows [{label, dist: [p per place], href}]. o: {zmax, labels, xName ('Finishing position'), yName} */
function posHeat(x, rows, o) {
  o = o || {};
  var list = (rows || []).filter(function (r) { return (r.dist || []).length; });
  if (!list.length) return none(x, 'No position distribution.');
  var n = Math.max.apply(null, list.map(function (r) { return r.dist.length; }));
  var n2 = node(x);
  if (n2) n2.style.setProperty('--h', Math.max(220, list.length * 24 + 60) + 'px');
  var data = [];
  list.forEach(function (r, yi) { for (var k = 0; k < n; k++) { var p = r.dist[k] || 0; data.push([k, yi, p > 0 ? p : null]); } });
  var xs = []; for (var k = 0; k < n; k++) xs.push(o.labels ? o.labels[k] : 'P' + (k + 1));
  return mount(x, function (T) {
    var xa = ax(T, { type: 'category', data: xs, split: false }); xa.position = 'top'; xa.axisLabel.color = T.ink2; xa.axisLabel.fontFamily = T.fontNum; xa.axisLabel.interval = 0; xa.axisLabel.fontSize = 9.5;
    var ya = ax(T, { type: 'category', data: list.map(function (r) { return r.label; }), split: false, inverse: true }); ya.axisLabel.color = T.ink2; ya.axisLabel.width = narrow(x) ? 70 : 120; ya.axisLabel.overflow = 'truncate';
    var titled = heatTitles(xa, ya, o.xName === undefined ? 'Finishing position' : o.xName, o.yName);
    return {
      grid: { left: 6, right: 8, top: 22 + titled, bottom: 4, containLabel: true },
      xAxis: xa, yAxis: ya,
      visualMap: { show: false, min: 0, max: o.zmax || Math.max.apply(null, data.map(function (d) { return d[2] || 0; })), inRange: { color: [QKC.hexA(T.seq[0], 0.35), T.seq[1], T.seq[2], T.seq[3], T.seq[4]] } },
      tooltip: tip(T, { formatter: function (p) { return head(list[p.value[1]].label, T) + row(p.color, xs[p.value[0]], PD.pct(p.value[2])); } }),
      series: [{ type: 'heatmap', data: data, itemStyle: { borderColor: T.s1, borderWidth: 1.5, borderRadius: 2 },
        label: { show: true, fontFamily: T.fontNum, fontSize: 9, color: T.ink1, formatter: function (p) { var v = p.value[2]; return v >= 0.095 ? Math.round(v * 100) : ''; } } }]
    };
  }, o.label || 'Finishing-position distribution');
}

/* Axis titles for the heatmaps (category axes, x along the top): x centred over the columns, y over the row labels.
 * Returns the extra room above the grid. */
function heatTitles(xa, ya, xName, yName) {
  if (xName) { xa.name = xName; xa.nameLocation = 'middle'; xa.nameGap = 24; }
  if (yName) { ya.name = yName; ya.nameLocation = 'start'; ya.nameGap = 24; ya.nameTextStyle.align = 'right'; }
  return xName || yName ? 20 : 0;
}
/* A grid heatmap with blanks: o: {xs, ys, data: [[xi, yi, v]], diverging, mid, fmt, hrefs (per row), cell (show labels), invert, xName, yName} */
function heat(x, o) {
  if (!o.ys || !o.ys.length) return none(x, o.emptyText || 'No data yet.');
  var n2 = node(x);
  if (n2 && o.autoHeight !== false) n2.style.setProperty('--h', Math.max(200, o.ys.length * (o.rowH || 26) + 70) + 'px');
  var vals = o.data.map(function (d) { return d[2]; }).filter(isNum);
  return mount(x, function (T) {
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (o.diverging) { var m = Math.max(Math.abs(lo - (o.mid || 0)), Math.abs(hi - (o.mid || 0))) || 1; lo = (o.mid || 0) - m; hi = (o.mid || 0) + m; }
    var xa = ax(T, { type: 'category', data: o.xs, split: false }); xa.position = 'top'; xa.axisLabel.color = T.ink2; xa.axisLabel.fontSize = 10;
    var ya = ax(T, { type: 'category', data: o.ys, split: false, inverse: true }); ya.axisLabel.color = T.ink2; ya.axisLabel.width = narrow(x) ? 76 : 130; ya.axisLabel.overflow = 'truncate';
    var range = o.diverging ? (o.invert ? [T.pos, T.mid, T.neg] : [T.neg, T.mid, T.pos]) : [QKC.hexA(T.seq[0], 0.4), T.seq[2], T.seq[4]];
    var titled = heatTitles(xa, ya, o.xName, o.yName);
    return {
      grid: { left: 6, right: 8, top: 24 + titled, bottom: o.legend === false ? 4 : 40, containLabel: true },
      xAxis: xa, yAxis: ya,
      visualMap: { show: o.legend !== false, min: lo, max: hi, orient: 'horizontal', left: 'center', bottom: 0, itemWidth: 10, itemHeight: 140, calculable: false,
        textStyle: { color: T.ink3, fontFamily: T.fontNum, fontSize: 10 }, formatter: function (v) { return o.fmt ? o.fmt(v) : PD.num(v, 1); }, inRange: { color: range } },
      tooltip: tip(T, { formatter: function (p) { return head(o.ys[p.value[1]] + ' · ' + o.xs[p.value[0]], T) + '<div style="font-family:var(--font-num)">' + esc(o.tipFmt ? o.tipFmt(p.value) : (o.fmt ? o.fmt(p.value[2]) : PD.num(p.value[2], 2))) + '</div>'; } }),
      series: [{ type: 'heatmap', data: o.data.filter(function (d) { return isNum(d[2]); }).map(function (d) { return { value: d, href: o.hrefs ? o.hrefs[d[1]] : undefined }; }),
        itemStyle: { borderColor: T.s1, borderWidth: 2, borderRadius: 3 },
        label: { show: o.cell !== false, fontFamily: T.fontNum, fontSize: 9.5, color: T.ink1, formatter: function (p) { return o.fmt ? o.fmt(p.value[2]) : PD.num(p.value[2], 1); } } }]
    };
  }, o.label);
}

// ── distributions ─────────────────────────────────────────────────────────

function quantiles(v) {
  var s = v.slice().sort(function (a, b) { return a - b; });
  var q = function (p) { var i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
  return [s[0], q(0.25), q(0.5), q(0.75), s[s.length - 1]];
}
/* groups: [{label, values, colour, sub}]; o: {yName, fmt} — a box per group. */
function boxes(x, groups, o) {
  o = o || {};
  var list = (groups || []).filter(function (g) { return (g.values || []).length >= 3; });
  if (!list.length) return none(x, o.emptyText || 'Too few laps to draw.');
  return mount(x, function (T) {
    var cats = list.map(function (g) { return g.label; });
    var xa = ax(T, { type: 'category', data: cats, split: false, line: true }); xa.axisLabel.interval = 0; xa.axisLabel.fontFamily = T.fontNum; xa.axisLabel.fontSize = 9.5; xa.axisLabel.color = T.ink2;
    if (list.length > 12) xa.axisLabel.rotate = 90;
    return {
      grid: { left: 6, right: 12, top: o.yName ? 26 : 12, bottom: 6, containLabel: true },
      xAxis: xa, yAxis: ax(T, { name: o.yName, nameAlign: 'left', scale: true, fmt: o.fmt }),
      tooltip: tip(T, { formatter: function (p) {
        var g = list[p.dataIndex]; var q = quantiles(g.values); var f = o.fmt || function (v) { return PD.num(v, 3); };
        return head(g.sub || g.label, T) + row(p.color, 'Median', f(q[2])) + row(p.color, 'Middle half', f(q[1]) + ' to ' + f(q[3])) + row(p.color, 'Range', f(q[0]) + ' to ' + f(q[4])) + row(T.ink3, 'Laps', String(g.values.length));
      } }),
      series: [{ type: 'boxplot', boxWidth: [6, 18], data: list.map(function (g) {
        var c = lift(g.colour || T.model, T);
        return { value: quantiles(g.values), itemStyle: { color: QKC.hexA(c, 0.3), borderColor: c, borderWidth: 1.4 } };
      }) }]
    };
  }, o.label);
}
/* values: [number] or [{name, values, colour}]; o: {bin, xName, ref, refLabel, fmt} */
function hist(x, sets, o) {
  o = o || {};
  var groups = Array.isArray(sets) && sets.length && typeof sets[0] === 'object' ? sets : [{ name: o.name || 'Count', values: sets || [], colour: o.colour }];
  var all = [];
  groups.forEach(function (g) { g.values.forEach(function (v) { if (isNum(v)) all.push(v); }); });
  if (!all.length) return none(x, o.emptyText || 'No data.');
  var bin = o.bin || 1, lo = Math.floor(Math.min.apply(null, all) / bin) * bin, hi = Math.ceil(Math.max.apply(null, all) / bin) * bin + bin;
  var cats = [];
  for (var b = lo; b < hi - 1e-9; b += bin) cats.push(b);
  var series = groups.map(function (g) {
    var counts = cats.map(function () { return 0; });
    g.values.forEach(function (v) { if (!isNum(v)) return; var k = Math.min(cats.length - 1, Math.floor((v - lo) / bin + 1e-9)); counts[k]++; });
    return { name: g.name, data: counts, colour: g.colour };
  });
  var f = o.fmt || function (v) { return PD.num(v, 1); };
  return columns(x, { cats: cats.map(function (c) { return f(c); }), series: series, yName: o.yName || 'Count', xName: o.xName, fmt: function (v) { return PD.num(v, 0); }, label: o.label,
    tipLabel: function (i) { return f(cats[i]) + ' to ' + f(cats[i] + bin) + (o.unit || ''); } });
}

// ── tyre stints ───────────────────────────────────────────────────────────

var COMP_ORDER = ['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET', 'UNKNOWN'];
function stints(x, data, o) {
  o = o || {};
  var ids = orderOf(data, o.order).filter(function (id) { return (data[id] || []).length; });
  if (!ids.length) return none(x, 'No tyre stints for this race.');
  var n = o.nLaps || Math.max.apply(null, ids.map(function (id) { return Math.max.apply(null, data[id].map(function (s) { return s.to || 0; })); }));
  var n2 = node(x);
  if (n2) n2.style.setProperty('--h', Math.max(260, ids.length * 22 + 50) + 'px');
  var rows = [];
  ids.forEach(function (id, yi) { data[id].forEach(function (s, k) {
    var c = s.compound ? String(s.compound).toUpperCase() : 'UNKNOWN';
    if (COMP_ORDER.indexOf(c) < 0) c = 'UNKNOWN';
    rows.push({ value: [(s.from || 1) - 1, s.to || n, yi, k + 1, s.age_start || 0], comp: c, id: id });
  }); });
  return mount(x, function (T) {
    var ya = ax(T, { type: 'category', data: ids.map(PD.driverCode), split: false, inverse: true }); ya.axisLabel.fontFamily = T.fontNum; ya.axisLabel.color = T.ink2; ya.axisLabel.interval = 0;
    return {
      grid: { left: 6, right: 14, top: 8, bottom: 26, containLabel: true },
      xAxis: ax(T, { min: 0, max: n, name: 'Lap', nameLocation: 'middle', nameGap: 24, line: true }),
      yAxis: ya,
      tooltip: tip(T, { formatter: function (p) { var r = rows[p.dataIndex]; var v = r.value;
        return head(PD.driverName(r.id), T) + row(PD.compoundColour(r.comp), 'Stint ' + v[3], (r.comp === 'UNKNOWN' ? 'compound unknown' : r.comp.charAt(0) + r.comp.slice(1).toLowerCase())) + row(T.ink3, 'Laps', (v[0] + 1) + '–' + v[1] + ' (' + (v[1] - v[0]) + ')') + (v[4] ? row(T.ink3, 'Age at fitting', v[4] + ' laps') : ''); } }),
      series: [{ type: 'custom', data: rows.map(function (r) { return r.value; }), encode: { x: [0, 1], y: 2 },
        renderItem: function (p, api) {
          var r = rows[p.dataIndex];
          var a = api.coord([api.value(0), api.value(2)]), b = api.coord([api.value(1), api.value(2)]);
          var hgt = api.size([0, 1])[1] * 0.62;
          var fill = PD.compoundColour(r.comp);
          var w = Math.max(1, b[0] - a[0] - 1.5);
          var laps = api.value(1) - api.value(0);
          var dark = r.comp === 'HARD' || r.comp === 'MEDIUM';
          return { type: 'group', children: [
            { type: 'rect', shape: { x: a[0] + 0.75, y: a[1] - hgt / 2, width: w, height: hgt, r: 3 }, style: { fill: fill, stroke: T.s1, lineWidth: 1 } },
            w > 26 ? { type: 'text', style: { text: (r.comp === 'UNKNOWN' ? '' : r.comp.charAt(0)) + ' ' + laps, x: a[0] + w / 2, y: a[1], align: 'center', verticalAlign: 'middle', fill: dark ? '#0b0d10' : '#ffffff', font: '600 10px ' + T.fontNum } } : null
          ].filter(Boolean) };
        } }]
    };
  }, o.label || 'Tyre strategy');
}

// ── track map and telemetry ───────────────────────────────────────────────

/* Fit x/y ranges to the container aspect so the circuit is not stretched. */
function fitRange(xs, ys, el, pad) {
  var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
  var w = x1 - x0 || 1, h = y1 - y0 || 1, p = pad || 0.06;
  x0 -= w * p; x1 += w * p; y0 -= h * p; y1 += h * p; w = x1 - x0; h = y1 - y0;
  var W = Math.max(200, el.clientWidth || 600), H = Math.max(200, el.clientHeight || 420);
  if (w / h > W / H) { var nh = w * H / W; y0 -= (nh - h) / 2; y1 += (nh - h) / 2; }
  else { var nw = h * W / H; x0 -= (nw - w) / 2; x1 += (nw - w) / 2; }
  return { x: [x0, x1], y: [y0, y1] };
}
/* tr: {x, y, v (values to colour by), vName, corners: [{d, n}], step} */
function trackMap(x, tr, o) {
  o = o || {};
  if (!tr || (tr.x || []).length < 10) return none(x, o.emptyText || 'No position data for a track map.');
  var n2 = node(x);
  return mount(x, function (T) {
    var R = fitRange(tr.x, tr.y, n2);
    var pts = tr.x.map(function (v, i) { return [v, tr.y[i], tr.v ? tr.v[i] : 0, i]; });
    var step = tr.step || 10;
    var cs = (tr.corners || []).map(function (c) { var k = Math.min(tr.x.length - 1, Math.round(c.d / step)); return { value: [tr.x[k], tr.y[k]], name: String(c.n) }; });
    var vs = (tr.v || []).filter(isNum);
    return {
      grid: { left: 0, right: o.legendRight === false ? 0 : 50, top: 6, bottom: 6 },
      xAxis: { type: 'value', min: R.x[0], max: R.x[1], show: false }, yAxis: { type: 'value', min: R.y[0], max: R.y[1], show: false },
      visualMap: tr.v ? { type: 'continuous', dimension: 2, seriesIndex: 1, min: Math.min.apply(null, vs), max: Math.max.apply(null, vs), orient: 'vertical', right: 0, top: 'middle', itemWidth: 10, itemHeight: 140,
        text: [tr.vName || '', ''], textStyle: { color: T.ink3, fontSize: 10 }, inRange: { color: [PD.col('sky'), PD.col('mint'), PD.col('leaf'), PD.col('sun'), PD.col('coral')] }, calculable: false } : undefined,
      tooltip: tip(T, { formatter: function (p) { if (p.seriesIndex !== 1) return p.name ? 'Turn ' + p.name : ''; var i = p.value[3]; return row(p.color, Math.round(i * step) + ' m', (tr.v ? PD.num(p.value[2], 0) + ' ' + (tr.vUnit || '') : '')) + (tr.gear ? row(T.ink3, 'Gear', String(tr.gear[i])) : ''); } }),
      series: [
        { type: 'line', data: pts.map(function (p) { return [p[0], p[1]]; }), showSymbol: false, silent: true, lineStyle: { width: 9, color: T.s3, cap: 'round', join: 'round' }, z: 1 },
        { type: 'scatter', data: pts, symbolSize: 3.6, z: 2, itemStyle: { color: T.sky } },
        { type: 'scatter', data: cs, symbolSize: 15, z: 3, itemStyle: { color: T.s4, borderColor: T.line2, borderWidth: 1 }, label: { show: true, formatter: function (p) { return p.name; }, color: T.ink1, fontSize: 8.5, fontWeight: 700 } },
        { type: 'scatter', data: [[tr.x[0], tr.y[0]]], symbol: 'rect', symbolSize: [10, 10], z: 4, itemStyle: { color: T.ink1 }, tooltip: { formatter: 'Start / finish' } }
      ]
    };
  }, o.label || 'Track map');
}
/* Who is faster where: segs [{from, to, a: true|false}] over geometry geo {x, y}; names [nameA, nameB] */
function segMap(x, geo, segs, names, o) {
  o = o || {};
  if (!geo || (geo.x || []).length < 10) return none(x, 'No position data for this session: the map needs a stored trace or the OpenF1 location feed.');
  var n2 = node(x);
  return mount(x, function (T) {
    var R = fitRange(geo.x, geo.y, n2);
    var A = [], B = [];
    segs.forEach(function (s) { var tgt = s.a ? A : B; for (var i = s.from; i <= s.to && i < geo.x.length; i++) tgt.push([geo.x[i], geo.y[i]]); tgt.push(['-', '-']); });
    var winsA = segs.filter(function (s) { return s.a; }).length, winsB = segs.length - winsA;
    var cs = (o.corners || []).map(function (c) { var k = Math.min(geo.x.length - 1, Math.round(c.d / (o.step || 10))); return { value: [geo.x[k], geo.y[k]], name: String(c.n) }; });
    return {
      grid: { left: 0, right: 0, top: 26, bottom: 4 },
      legend: legend(T, { data: [names[0] + ' faster (' + winsA + ')', names[1] + ' faster (' + winsB + ')'] }),
      xAxis: { type: 'value', min: R.x[0], max: R.x[1], show: false }, yAxis: { type: 'value', min: R.y[0], max: R.y[1], show: false },
      tooltip: { show: false },
      series: [
        { type: 'line', data: geo.x.map(function (v, i) { return [v, geo.y[i]]; }), showSymbol: false, silent: true, lineStyle: { width: 11, color: T.s3 }, z: 1 },
        { type: 'line', name: names[0] + ' faster (' + winsA + ')', data: A, showSymbol: false, connectNulls: false, lineStyle: { width: 5, color: T.sky }, itemStyle: { color: T.sky }, z: 2 },
        { type: 'line', name: names[1] + ' faster (' + winsB + ')', data: B, showSymbol: false, connectNulls: false, lineStyle: { width: 5, color: T.coral }, itemStyle: { color: T.coral }, z: 2 },
        { type: 'scatter', data: cs, symbolSize: 15, z: 3, silent: true, itemStyle: { color: T.s4, borderColor: T.line2 }, label: { show: true, formatter: function (p) { return p.name; }, color: T.ink1, fontSize: 8.5, fontWeight: 700 } }
      ]
    };
  }, o.label || 'Track map: who is faster where');
}
/* Stacked telemetry panels on a shared distance axis. A, B traces {d, speed, throttle, brake, gear, rpm, drs}; delta[]; names; corners */
function telemetry(x, A, B, delta, names, corners) {
  var len = Math.min(A.d.length, B.d.length);
  var d = A.d.slice(0, len);
  var panels = [['delta', 'Delta (s)', 1.1], ['speed', 'Speed', 2.2], ['throttle', 'Throttle %', 1], ['brake', 'Brake', 0.6], ['gear', 'Gear', 0.9], ['rpm', 'RPM', 1], ['drs', 'DRS', 0.6]];
  var host = node(x);
  return mount(x, function (T) {
    var tot = panels.reduce(function (s, p) { return s + p[2]; }, 0);
    var top = 34, avail = ((host && host.clientHeight) || 900) - top - 34, gap = 10, grids = [], xA = [], yA = [], ser = [];
    var unit = (avail - gap * (panels.length - 1)) / tot;
    panels.forEach(function (p, i) {
      var h = unit * p[2];
      grids.push({ left: 58, right: 12, top: top, height: h });
      top += h + gap;
      xA.push(Object.assign(ax(T, { type: 'value', min: 0, max: d[d.length - 1], split: false, line: true, name: i === panels.length - 1 ? 'Distance (m)' : '', nameLocation: 'middle', nameGap: 22 }), { gridIndex: i }));
      xA[i].axisLabel.show = i === panels.length - 1;
      var ya = ax(T, { name: '', min: p[0] === 'throttle' ? 0 : p[0] === 'brake' ? 0 : undefined, max: p[0] === 'throttle' ? 100 : p[0] === 'brake' ? 1 : undefined, scale: p[0] !== 'throttle' && p[0] !== 'brake' });
      ya.gridIndex = i; ya.splitNumber = 2; ya.axisLabel.fontSize = 9;
      ya.name = p[1]; ya.nameLocation = 'middle'; ya.nameGap = 40; ya.nameRotate = 90; ya.nameTextStyle = { color: T.ink3, fontSize: 9.5, fontWeight: 600 };
      yA.push(ya);
      if (p[0] === 'delta') {
        ser.push({ type: 'line', name: 'Delta', xAxisIndex: i, yAxisIndex: i, data: d.map(function (v, k) { return [v, delta[k]]; }), showSymbol: false, lineStyle: { width: 1.5, color: T.ink1 }, areaStyle: { color: QKC.hexA(T.ink2, 0.12) },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [3, 3] }, label: { show: false }, data: [{ yAxis: 0 }].concat((corners || []).map(function (c) { return { xAxis: c.d }; })) } });
        return;
      }
      [[A, T.sky, names[0]], [B, T.coral, names[1]]].forEach(function (z) {
        var arr = z[0][p[0]] || [];
        if (p[0] === 'brake') arr = arr.map(function (v) { return v > 1 ? v / 100 : v; });
        ser.push({ type: 'line', name: z[2], xAxisIndex: i, yAxisIndex: i, data: d.map(function (v, k) { return [v, arr[k]]; }), showSymbol: false, step: p[0] === 'gear' || p[0] === 'drs' || p[0] === 'brake' ? 'end' : false,
          lineStyle: { width: p[0] === 'speed' ? 1.7 : 1.3, color: z[1] }, itemStyle: { color: z[1] },
          markLine: p[0] === 'speed' && z[0] === A ? { silent: true, symbol: 'none', lineStyle: { color: QKC.hexA(T.ink3, 0.4), type: [2, 3] }, label: { show: true, position: 'end', formatter: function (q) { return q.name; }, color: T.ink3, fontSize: 9 },
            data: (corners || []).map(function (c) { return { xAxis: c.d, name: 'T' + c.n }; }) } : undefined });
      });
    });
    return {
      grid: grids, xAxis: xA, yAxis: yA,
      legend: legend(T, { data: [names[0], names[1]], top: 4, left: 'center' }),
      axisPointer: { link: [{ xAxisIndex: 'all' }], lineStyle: { color: T.axis } },
      tooltip: tip(T, { trigger: 'axis', formatter: function (ps) {
        var dist = ps[0] ? Math.round(ps[0].axisValue) : 0, k = Math.min(len - 1, Math.max(0, Math.round(dist / ((A.step) || 10))));
        var f = function (tr, key) { var v = (tr[key] || [])[k]; return isNum(v) ? PD.num(v, key === 'rpm' || key === 'speed' || key === 'throttle' ? 0 : 0) : '—'; };
        return '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + dist + ' m · delta ' + PD.signed(delta[k], 3) + ' s</div>' +
          row(T.sky, names[0], f(A, 'speed') + ' km/h · ' + f(A, 'throttle') + '% · g' + f(A, 'gear')) + row(T.coral, names[1], f(B, 'speed') + ' km/h · ' + f(B, 'throttle') + '% · g' + f(B, 'gear'));
      } }),
      series: ser
    };
  }, 'Telemetry overlay of two laps');
}

// ── radar, scatter, waterfall ─────────────────────────────────────────────

/* axes [{key, label}], rows [{name, pct: {key: 0-100}, colour}] */
function radar(x, axes, rows) {
  var use = axes.filter(function (a) { return rows.some(function (r) { return r && r.pct && isNum(r.pct[a.key]); }); });
  var list = rows.filter(function (r) { return r && r.pct && use.some(function (a) { return isNum(r.pct[a.key]); }); });
  if (use.length < 3 || !list.length) return none(x, 'No percentiles to draw yet.');
  return mount(x, function (T) {
    return {
      legend: list.length > 1 ? legend(T, { data: list.map(function (r) { return r.name; }), icon: 'roundRect', itemWidth: 10, itemHeight: 10 }) : undefined,
      tooltip: tip(T, {}),
      radar: { indicator: use.map(function (a) { return { name: a.label, max: 100, min: 0 }; }), radius: narrow(x) ? '58%' : '66%', center: ['50%', list.length > 1 ? '56%' : '52%'], splitNumber: 4,
        axisName: { color: T.ink2, fontSize: narrow(x) ? 9 : 10.5 }, splitLine: { lineStyle: { color: T.grid } }, axisLine: { lineStyle: { color: T.grid } }, splitArea: { show: false } },
      series: [{ type: 'radar', symbolSize: 5, data: list.map(function (r, i) {
        var c = r.colour ? lift(r.colour, T) : (i ? T.coral : T.sky);
        return { name: r.name, value: use.map(function (a) { return isNum(r.pct[a.key]) ? Math.round(r.pct[a.key]) : 0; }), lineStyle: { color: c, width: 2 }, itemStyle: { color: c }, areaStyle: { color: QKC.hexA(c, 0.16) } };
      }) }]
    };
  }, 'Percentile profile');
}
/* points [{x, y, name, colour, size, href, label (bool), hit}]; o: {xName, yName, xFmt, yFmt, invX, invY, refX, refY, diag, groups (legend)} */
function scatter(x, pts, o) {
  o = o || {};
  if (!pts || pts.length < 2) return none(x, o.emptyText || 'Too few points for this view.');
  return mount(x, function (T) {
    var ml = [];
    if (isNum(o.refX)) ml.push({ xAxis: o.refX });
    if (isNum(o.refY)) ml.push({ yAxis: o.refY });
    var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
    var series = [{
      type: 'scatter', z: 2,
      symbolSize: function (v, p) { return pts[p.dataIndex].size || 11; },
      data: pts.map(function (p) {
        var c = p.colour ? lift(p.colour, T) : T.model;
        return { value: [p.x, p.y], name: p.name, href: p.href,
          itemStyle: { color: c, borderColor: p.hit ? T.ink1 : T.s1, borderWidth: p.hit ? 2.5 : 1, opacity: 0.92 },
          label: { show: !!p.label || !!p.hit, formatter: p.short || p.name, position: 'top', color: p.hit ? T.ink1 : T.ink2, fontSize: 10, fontWeight: 600 } };
      }),
      labelLayout: { hideOverlap: true },
      emphasis: { scale: 1.4, label: { show: true } },
      markLine: ml.length ? { silent: true, symbol: 'none', lineStyle: { color: T.axis, type: [4, 4] }, label: { show: false }, data: ml } : undefined
    }];
    if (o.diag) {
      var lo = Math.min(Math.min.apply(null, xs), Math.min.apply(null, ys)), hi = Math.max(Math.max.apply(null, xs), Math.max.apply(null, ys));
      series.push({ type: 'line', data: [[lo, lo], [hi, hi]], showSymbol: false, silent: true, lineStyle: { color: T.axis, type: [4, 4], width: 1 }, tooltip: { show: false } });
    }
    return {
      grid: { left: 8, right: 20, top: o.yName ? 30 : 14, bottom: 34, containLabel: true },
      xAxis: ax(T, { name: o.xName, nameLocation: 'middle', nameGap: 28, fmt: o.xFmt, scale: true, inverse: !!o.invX, min: o.xMin, max: o.xMax }),
      yAxis: ax(T, { name: o.yName, fmt: o.yFmt, scale: true, inverse: !!o.invY, min: o.yMin, max: o.yMax }),
      tooltip: tip(T, { formatter: function (p) { var d = pts[p.dataIndex]; if (!d) return ''; return head(d.name, T) + (d.sub ? '<div style="color:' + T.ink3 + ';font-size:11px;margin-bottom:4px">' + esc(d.sub) + '</div>' : '') +
        row(p.color, o.xName || 'x', o.xFmt ? o.xFmt(d.x) : PD.num(d.x, 2)) + row(p.color, o.yName || 'y', o.yFmt ? o.yFmt(d.y) : PD.num(d.y, 2)) + (d.extra ? d.extra : ''); } }),
      series: series
    };
  }, o.label);
}
/* steps [{label, value, total: bool}] — a waterfall from an absolute start to a total. */
function waterfall(x, steps, o) {
  o = o || {};
  if (!steps || !steps.length) return none(x, 'No split yet.');
  var base = [], vals = [], run = 0;
  steps.forEach(function (s, i) {
    if (i === 0 || s.total) { base.push(0); vals.push(s.value); run = s.value; return; }
    var nv = run + s.value;
    base.push(Math.min(run, nv)); vals.push(Math.abs(s.value)); run = nv;
  });
  return mount(x, function (T) {
    var xa = ax(T, { type: 'category', data: steps.map(function (s) { return s.label; }), split: false, line: true }); xa.axisLabel.interval = 0; xa.axisLabel.color = T.ink2;
    return {
      grid: { left: 6, right: 10, top: o.yName ? 28 : 22, bottom: 6, containLabel: true },
      xAxis: xa, yAxis: ax(T, { name: o.yName, nameAlign: 'left' }),
      tooltip: tip(T, { trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: QKC.hexA(T.ink1, 0.04) } }, formatter: function (ps) { var s = steps[ps[0].dataIndex]; return head(s.label, T) + row(T.ink2, s.total || ps[0].dataIndex === 0 ? 'Points' : 'Adds', (s.total || ps[0].dataIndex === 0 ? '' : (s.value >= 0 ? '+' : '')) + PD.num(s.value, 1)); } }),
      series: [
        { type: 'bar', stack: 'w', data: base, itemStyle: { color: 'transparent' }, silent: true, tooltip: { show: false } },
        { type: 'bar', stack: 'w', barMaxWidth: 40, data: vals.map(function (v, i) {
          var s = steps[i];
          var c = i === 0 || s.total ? lift(o.colour || T.model, T) : (s.value >= 0 ? T.up : T.down);
          return { value: v, itemStyle: { color: c, borderRadius: 3 } };
        }), label: { show: true, position: 'top', color: T.ink2, fontFamily: T.fontNum, fontSize: 10.5, formatter: function (p) { var s = steps[p.dataIndex]; return (p.dataIndex && !s.total && s.value > 0 ? '+' : '') + PD.num(s.value, 1); } } }
      ]
    };
  }, o.label);
}
/* Reliability diagram: models [{name, bins: [{mean_p, freq, n}]}] */
function reliability(x, models) {
  var list = models.filter(function (m) { return (m.bins || []).length; });
  if (!list.length) return none(x, 'No reliability bins.');
  return mount(x, function (T) {
    var maxN = 1;
    list.forEach(function (m) { m.bins.forEach(function (b) { maxN = Math.max(maxN, b.n); }); });
    var ser = [{ type: 'line', data: [[0, 0], [1, 1]], showSymbol: false, silent: true, lineStyle: { color: T.axis, type: [4, 4], width: 1 }, tooltip: { show: false } }];
    list.forEach(function (m, i) {
      ser.push({ type: 'line', name: m.name, data: m.bins.map(function (b) { return [b.mean_p, b.freq, b.n]; }), symbol: 'circle',
        symbolSize: function (v) { return 5 + 14 * Math.sqrt(v[2] / maxN); }, lineStyle: { width: 1.6, color: T.cat[i % 8] }, itemStyle: { color: T.cat[i % 8] } });
    });
    return {
      grid: { left: 8, right: 16, top: 54, bottom: 34, containLabel: true },
      legend: legend(T, { data: list.map(function (m) { return m.name; }) }),
      xAxis: ax(T, { min: 0, max: 1, name: 'Forecast probability', nameLocation: 'middle', nameGap: 26, fmt: function (v) { return Math.round(v * 100) + '%'; } }),
      yAxis: ax(T, { min: 0, max: 1, name: 'Observed', fmt: function (v) { return Math.round(v * 100) + '%'; } }),
      tooltip: tip(T, { formatter: function (p) { return head(p.seriesName, T) + row(p.color, 'Forecast', PD.pct(p.value[0])) + row(p.color, 'Observed', PD.pct(p.value[1])) + row(T.ink3, 'Forecasts', String(p.value[2])); } }),
      series: ser
    };
  }, 'Reliability diagram');
}

PD.ch = {
  lapLines: lapLines, hbars: hbars, lines: lines, columns: columns, posHeat: posHeat, heat: heat, boxes: boxes, hist: hist,
  stints: stints, trackMap: trackMap, segMap: segMap, telemetry: telemetry, radar: radar, scatter: scatter, waterfall: waterfall,
  reliability: reliability, controlBands: controlBands, styleMap: styleMap, none: none, quantiles: quantiles
};
})(window.PD);
