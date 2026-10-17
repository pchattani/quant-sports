/* The Quant Footballer — charts: Plotly wrappers, the pitch, shot maps, xG race,
 * momentum, radar. Charts come from a CDN; tables do not, so a missing chart never
 * takes a section down. */
(function (FH) {
'use strict';

const { DARK_LAYOUT, PLOTLY_CONF, C, esc, num, pct, setHTML } = FH;

function plot(elId, traces, layout) {
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  if (typeof Plotly === 'undefined') {
    el.innerHTML = '<div class="muted">The chart library did not load. The tables carry the same data.</div>';
    return;
  }
  try {
    Plotly.newPlot(el, traces, layout, PLOTLY_CONF);
  } catch (err) {
    console.warn('chart failed', err);
    el.innerHTML = '<div class="muted">The chart could not be drawn.</div>';
  }
}

function layout(extra) {
  const base = JSON.parse(JSON.stringify(DARK_LAYOUT));
  const out = Object.assign(base, extra || {});
  if (extra && extra.xaxis) out.xaxis = Object.assign({}, DARK_LAYOUT.xaxis, extra.xaxis);
  if (extra && extra.yaxis) out.yaxis = Object.assign({}, DARK_LAYOUT.yaxis, extra.yaxis);
  return out;
}

/* A vertical half-pitch: the goal at the top, `y` (0-100 across the width) on the
 * x-axis and `x` (distance from the goal line, Sofascore's convention) on the
 * y-axis, so a shot map reads like a broadcast overlay. */
function pitchShapes() {
  const line = { color: '#3d444d', width: 1 };
  return [
    { type: 'rect', x0: 0, x1: 100, y0: 0, y1: 55, line: line },
    { type: 'rect', x0: 21, x1: 79, y0: 0, y1: 17, line: line },        // penalty area (16.5m ≈ 17% of 105m... scaled to Sofascore units)
    { type: 'rect', x0: 36.8, x1: 63.2, y0: 0, y1: 5.8, line: line },   // six-yard box
    { type: 'rect', x0: 44.5, x1: 55.5, y0: -2.5, y1: 0, line: { color: '#8b949e', width: 2 } },   // goal
    { type: 'circle', x0: 49.2, x1: 50.8, y0: 10.6, y1: 12.2, line: line, fillcolor: '#3d444d' },  // penalty spot
    { type: 'path', path: 'M 38.5 17 Q 50 25.5 61.5 17', line: line },   // D
    { type: 'line', x0: 0, x1: 100, y0: 52.5, y1: 52.5, line: { color: '#3d444d', width: 1, dash: 'dot' } }
  ];
}

function shotLabel(s) {
  const parts = [];
  if (s.player) parts.push(s.player);
  if (s.match) parts.push(s.match);
  parts.push((s.type || 'shot') + (s.body ? ' · ' + s.body.replace('-', ' ') : '') + (s.situation ? ' · ' + s.situation.replace('-', ' ') : ''));
  parts.push('xG ' + num(s.xg, 2) + (s.xgot ? ' · xGOT ' + num(s.xgot, 2) : '') + (s.time ? ' · ' + s.time + "'" : ''));
  return parts.join('<br>');
}

/* Shots on the half pitch; goals in green, saves in blue, the rest grey; size by xG. */
function renderShotMap(elId, shots, opts) {
  const o = opts || {};
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  const valid = (shots || []).filter(s => s.x !== null && s.x !== undefined && s.y !== null && s.y !== undefined);
  if (!valid.length) { el.innerHTML = '<div class="muted">No shots.</div>'; return; }
  const kindOf = s => { const t = String(s.type || '').toLowerCase(); return t === 'goal' ? 'goal' : t === 'save' ? 'save' : t === 'post' ? 'post' : t.indexOf('block') >= 0 ? 'block' : 'miss'; };
  const colors = { goal: C.green, save: C.blue, post: C.yellow, block: C.text3, miss: '#c9d1d9' };
  const groups = { goal: 'Goal', save: 'Saved', post: 'Woodwork', block: 'Blocked', miss: 'Off target' };
  const traces = Object.keys(groups).map(k => {
    const pts = valid.filter(s => kindOf(s) === k);
    return {
      type: 'scatter', mode: 'markers', name: groups[k], x: pts.map(s => s.y), y: pts.map(s => s.x),
      text: pts.map(shotLabel), hovertemplate: '%{text}<extra></extra>',
      marker: { size: pts.map(s => 7 + Math.sqrt(s.xg || 0.02) * 26), color: colors[k], opacity: k === 'goal' ? 0.95 : 0.75,
                line: { color: '#0d1117', width: 1 }, symbol: k === 'block' ? 'x' : 'circle' }
    };
  }).filter(t => t.x.length);
  plot(el, traces, layout({
    shapes: pitchShapes(), showlegend: o.legend !== false, legend: { orientation: 'h', y: -0.02, font: { color: C.text2 } },
    xaxis: { range: [-2, 102], visible: false, fixedrange: true },
    yaxis: { range: [56, -4], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 0.68 },
    margin: { l: 10, r: 10, t: 10, b: 30 }
  }));
}

/* Cumulative xG by minute for both sides, goals marked. */
function renderXgRace(elId, shots, home, away) {
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  const list = (shots || []).filter(s => s.time !== null && s.time !== undefined);
  if (!list.length) { el.innerHTML = '<div class="muted">No shot data.</div>'; return; }
  const maxT = Math.max(90, ...list.map(s => s.time || 0));
  const build = side => {
    const own = list.filter(s => (s.is_home === undefined ? s.team === side : (s.is_home ? home : away) === side))
      .sort((a, b) => (a.time || 0) - (b.time || 0));
    const xs = [0], ys = [0]; let cum = 0; const goals = [];
    own.forEach(s => { cum += s.xg || 0; xs.push(s.time); ys.push(cum); if (String(s.type).toLowerCase() === 'goal') goals.push({ t: s.time, v: cum, who: s.player_name || s.player }); });
    xs.push(maxT); ys.push(cum);
    return { xs, ys, goals };
  };
  const h = build(home), a = build(away);
  const traces = [
    { type: 'scatter', mode: 'lines', name: home, x: h.xs, y: h.ys, line: { shape: 'hv', color: C.blue, width: 2.5 }, hovertemplate: home + ': %{y:.2f} xG at %{x}\'<extra></extra>' },
    { type: 'scatter', mode: 'lines', name: away, x: a.xs, y: a.ys, line: { shape: 'hv', color: C.orange, width: 2.5 }, hovertemplate: away + ': %{y:.2f} xG at %{x}\'<extra></extra>' },
    { type: 'scatter', mode: 'markers', name: 'Goals', x: h.goals.map(g => g.t).concat(a.goals.map(g => g.t)), y: h.goals.map(g => g.v).concat(a.goals.map(g => g.v)),
      text: h.goals.map(g => g.who).concat(a.goals.map(g => g.who)), marker: { size: 11, color: C.green, symbol: 'circle', line: { color: '#0d1117', width: 1 } },
      hovertemplate: '⚽ %{text} (%{x}\')<extra></extra>' }
  ];
  plot(el, traces, layout({
    showlegend: true, legend: { orientation: 'h', y: 1.12, font: { color: C.text2 } },
    xaxis: { title: 'Minute', range: [0, maxT + 1] }, yaxis: { title: 'Cumulative xG', rangemode: 'tozero' },
    margin: { l: 55, r: 20, t: 30, b: 45 }
  }));
}

function renderMomentum(elId, mom, home, away) {
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  if (!(mom || []).length) { el.innerHTML = '<div class="muted">No momentum data.</div>'; return; }
  plot(el, [{
    type: 'bar', x: mom.map(p => p.minute), y: mom.map(p => p.value),
    marker: { color: mom.map(p => (p.value >= 0 ? C.blue : C.orange)) }, hovertemplate: 'min %{x}: %{y:.0f}<extra></extra>'
  }], layout({ xaxis: { title: 'Minute' }, yaxis: { title: esc(away) + ' ← → ' + esc(home) }, margin: { l: 70, r: 20, t: 10, b: 45 }, bargap: 0.15 }));
}

/* Percentile radar for one or two players. axes: [{key,label}], rows: [{name, pct}] */
function renderRadar(elId, axes, rows) {
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  const usable = rows.filter(r => r && r.pct);
  if (!usable.length) { el.innerHTML = '<div class="muted">Percentiles need more minutes.</div>'; return; }
  plot(el, usable.map((r, i) => ({
    type: 'scatterpolar', fill: 'toself', name: r.name,
    r: axes.map(ax => (r.pct[ax.key] === undefined ? 0 : r.pct[ax.key]) / 100).concat([(r.pct[axes[0].key] || 0) / 100]),
    theta: axes.map(ax => ax.label).concat([axes[0].label]),
    line: { color: i === 0 ? C.blue : C.orange }, opacity: 0.85,
    hovertemplate: '%{theta}: %{r:.0%} percentile<extra>' + esc(r.name) + '</extra>'
  })), layout({
    showlegend: usable.length > 1, legend: { orientation: 'h', y: -0.08, font: { color: C.text2 } },
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 1], tickformat: '.0%', gridcolor: '#21262d', tickfont: { size: 9 } }, angularaxis: { gridcolor: '#21262d' } },
    margin: { l: 50, r: 50, t: 20, b: 40 }
  }));
}

/* Horizontal probability bars, sorted ascending so the favourite sits on top. */
function renderProbBars(elId, items, title, color) {
  const el = typeof elId === 'string' ? document.getElementById(elId) : elId;
  if (!el) return;
  const sorted = items.filter(i => i.p > 0).slice().sort((a, b) => a.p - b.p);
  if (!sorted.length) { el.innerHTML = '<div class="muted">Nothing to show.</div>'; return; }
  plot(el, [{
    type: 'bar', orientation: 'h', y: sorted.map(i => i.label), x: sorted.map(i => i.p),
    text: sorted.map(i => pct(i.p)), textposition: 'outside', cliponaxis: false,
    marker: { color: color || C.blue }, hovertemplate: '%{y}: %{x:.1%}<extra></extra>'
  }], layout({
    margin: { l: 150, r: 60, t: 10, b: 40 },
    xaxis: { tickformat: '.0%', title: title || '', range: [0, Math.min(1, Math.max(...sorted.map(i => i.p)) * 1.25)] },
    yaxis: { automargin: true }
  }));
}

FH.plot = plot;
FH.layout = layout;
FH.pitchShapes = pitchShapes;
FH.renderShotMap = renderShotMap;
FH.renderXgRace = renderXgRace;
FH.renderMomentum = renderMomentum;
FH.renderRadar = renderRadar;
FH.renderProbBars = renderProbBars;
})(window.FH);
