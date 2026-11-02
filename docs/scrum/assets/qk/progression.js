/* The Quant — progression module, kit v4 "Broadcast", dark only (round 6, 28 Oct 2026). Load after quant.js and
 * quant-charts.js. A player's career season by season (or by age) on the position group's deep metric set, against the
 * peers of each season, and two to four players on the same chart.
 *
 *   QKC.progression(el, o)        the career progression chart: one metric's value with the peer median and the middle
 *                                 half (25th-75th) of each season's qualified peers, the player's percentile as an
 *                                 optional second line; or several metrics as percentiles. Marker size = sample, hollow =
 *                                 under the floor, team changes marked, short (injury) seasons labelled
 *   QK.progressionGrid(o)         the season-by-season percentile heatmap (rows = metrics, columns = seasons), the value
 *                                 and sample in each cell's tooltip; our-model rows carry the "Ours" tag
 *   QK.progressionDeltas(o)       the biggest jumps and drops between consecutive seasons (percentile points)
 *   QK.careerArc(o)               { html, text, peak, agePeak, trend }: peak season, age at peak, the trend over the
 *                                 last three seasons and "the short version" of the arc in plain words
 *   QK.compareProgression(el, o)  2-4 players on one chart by season, by age or by career year, on any metric of the
 *                                 deep set (value or percentile), with the season-by-season table (each player's best
 *                                 highlighted) and optional "add a player" suggestions
 *   QK.prog.ref(json)             a lookup on a site's progression_ref.json: ref(group, season, id) -> { q, n }
 *   QK.prog.fmt(unit, v)          a default number format from the spec unit
 *
 * Shapes (the site adapter builds them from its player files; docs/_design/MIGRATION_V4.md "Progression"):
 *   player  P = { id, name, short (surname), href, seasons: [S] }
 *   season  S = { key ('20152016'), x (a number on the season axis: 2015), label ('2015-16'), age (19.4),
 *                 cy (career year, optional: else the order in the data), team: { abbr, name, colour } | null,
 *                 teams: ['EDM', ...] (several in a traded season), group ('forwards': the peer group of the row),
 *                 n (sample: games, minutes, PA ...), nMax (the season's length in that unit, optional), nUnit ('games'),
 *                 small (true: under the qualification floor; no percentiles), partial (true: the season in progress;
 *                 left out of the jumps, the peak and the trend), short: { tag ('INJURY'), text
 *                 ('Missed 37 games, injured') } | null (only where the data shows it),
 *                 values: { id: v }, pct: { id: 0-100 } }
 *   metric  M = { id, label, unit, dir ('higher' | 'lower' | 'neutral'), fmt (v -> text, optional), ours: { name } |
 *                 null, tip, head (true: a headline metric of the position) }
 *   ref     o.ref(S, id) -> { q: [p10, p25, p50, p75, p90], n } | null   (the season's qualified peers)
 * Copy is neutral (no pronouns, no betting words); every chart axis is titled. ES5 only (no ?. or ??). */
(function (root) {
'use strict';

var QK = root.QK, QKC = root.QKC;
if (!QK || !QKC) return;
var esc = QK.esc, isNum = QK.isNum;

/* ─────────────────────────────────────── styles (once) */
var CSS = [
  '.qkp-sec{margin-top:var(--sp-7,40px)}',
  '.qkp-ctl{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin:0 0 12px}',
  '.qkp-ctl label{display:inline-flex;gap:8px;align-items:center;font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);min-width:0;max-width:100%}',
  '.qkp-ctl select{max-width:min(320px,100%);min-width:0}',
  '.qkp-ctl .qk-seg{flex-wrap:nowrap}',
  '.qkp-keys{display:flex;flex-wrap:wrap;gap:6px 16px;margin:8px 0 0;font:600 var(--fs-xs)/1.3 var(--font-cond);color:var(--ink-3);text-transform:uppercase;letter-spacing:.04em}',
  '.qkp-keys i{display:inline-block;width:12px;height:12px;margin-right:6px;vertical-align:-1px;background:var(--k)}',
  '.qkp-keys i.band{background:color-mix(in srgb,var(--ink-3) 30%,transparent)}',
  '.qkp-keys i.med{height:0;border-top:2px dashed var(--ink-3);width:14px;vertical-align:3px}',
  '.qkp-keys i.hollow{background:transparent;border:2px solid var(--ink-2);border-radius:50%;width:9px;height:9px}',
  '.qkp-keys i.dot{border-radius:50%}',
  '.qkp-note{font:500 var(--fs-xs)/1.45 var(--font-ui);color:var(--ink-3);margin:8px 0 0}',
  '.qkp-note b{color:var(--ink-2)}',
  /* the heatmap */
  '.qkp-grid{border-collapse:separate;border-spacing:2px;width:auto}',
  '.qkp-grid th,.qkp-grid td{border:0;padding:0;white-space:nowrap}',
  '.qkp-grid thead th{padding:6px 4px 8px;text-align:center;vertical-align:bottom;background:var(--s-1);position:sticky;top:0;z-index:1}',
  '.qkp-grid thead th .s{display:block;font:400 1.1rem/1 var(--font-display);color:var(--ink-1);letter-spacing:.02em}',
  '.qkp-grid thead th .t{display:block;font:700 10px/1.2 var(--font-cond);color:var(--ink-3);letter-spacing:.06em;margin-top:3px}',
  '.qkp-grid thead th.is-small .s{color:var(--ink-3)}',
  '.qkp-grid thead th.is-short .t{color:var(--coral,#ff6a4d)}',
  '.qkp-grid th.qkp-m{position:sticky;left:0;z-index:2;background:var(--s-1);text-align:left;padding:4px 10px 4px 0;font:700 var(--fs-xs)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.04em;color:var(--ink-2);min-width:150px;max-width:220px;white-space:normal}',
  '.qkp-grid thead th.qkp-m{z-index:3;vertical-align:bottom;color:var(--ink-3)}',
  '@media (max-width:640px){.qkp-grid th.qkp-m{min-width:112px;max-width:150px;font-size:11px}}',
  '.qkp-grid tr.qkp-gh th{position:sticky;left:0;background:var(--s-1);padding:12px 0 4px;font:700 var(--fs-2xs)/1 var(--font-cond);color:var(--volt,#d4ff3a);text-transform:uppercase;letter-spacing:.1em;text-align:left}',
  '.qkp-grid .qk-ours{margin-left:6px;vertical-align:1px}',
  '.qkp-c{display:flex;align-items:center;justify-content:center;width:46px;height:30px;font:700 13px/1 var(--font-cond);font-variant-numeric:tabular-nums;cursor:default}',
  '.qkp-c.na{background:var(--s-2);color:var(--ink-3)}',
  '.qkp-c.sm{background:transparent;border:1px dashed var(--line-3,#3a4150);color:var(--ink-3);font-weight:600}',
  '.qkp-c:focus-visible{outline:2px solid var(--focus);outline-offset:1px}',
  '.qkp-scale{display:flex;align-items:center;gap:8px;margin:10px 0 0;font:700 10px/1 var(--font-cond);color:var(--ink-3);text-transform:uppercase;letter-spacing:.08em;flex-wrap:wrap}',
  '.qkp-scale b{display:inline-block;width:120px;height:10px;background:linear-gradient(90deg,var(--pc-0),var(--pc-25),var(--pc-50),var(--pc-75),var(--pc-100))}',
  '.qkp-scale .sm{display:inline-block;width:18px;height:12px;border:1px dashed var(--line-3,#3a4150)}',
  /* deltas */
  '.qkp-dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--sp-4,16px)}',
  '@media (max-width:720px){.qkp-dl{grid-template-columns:minmax(0,1fr)}}',
  '.qkp-dl h4{margin:0 0 6px;font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.1em;color:var(--ink-3)}',
  '.qkp-dl ul{list-style:none;margin:0;padding:0}',
  '.qkp-dl li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:10px 0;border-top:1px solid var(--line-2)}',
  '.qkp-dl li:first-child{border-top:0}',
  '.qkp-dl .m{font:700 var(--fs-sm)/1.2 var(--font-cond);text-transform:uppercase;letter-spacing:.03em;color:var(--ink-1);min-width:0}',
  '.qkp-dl .m .qk-ours{margin-left:6px}',
  '.qkp-dl .d{font:400 1.6rem/1 var(--font-display);white-space:nowrap;text-align:right}',
  '.qkp-dl .d small{font:700 10px/1 var(--font-cond);color:var(--ink-3);margin-left:3px;letter-spacing:.06em}',
  '.qkp-dl .w{grid-column:1 / 3;font:500 var(--fs-xs)/1.4 var(--font-ui);color:var(--ink-3)}',
  '.qkp-dl .w b{color:var(--ink-2);font-weight:600}',
  '.qkp-up{color:var(--up)}.qkp-down{color:var(--down)}',
  /* compare table */
  '.qkp-ct td.num,.qkp-ct th.num{text-align:right}',
  '.qkp-ct td.best{background:color-mix(in srgb,var(--volt,#d4ff3a) 14%,transparent);color:var(--ink-1);font-weight:700}','.qkp-ct td.best::before{content:"BEST ";font:700 10px/1 var(--font-cond);letter-spacing:.06em;color:var(--volt,#d4ff3a)}',
  '.qkp-ct .pc{display:inline-block;min-width:26px;margin-left:6px;padding:2px 4px;font:700 11px/1 var(--font-cond);text-align:center}',
  '.qkp-ct th .k{display:inline-block;width:10px;height:10px;margin-right:6px;background:var(--k)}',
  '.qkp-ct td.sm{color:var(--ink-3)}',
  '.qkp-sugg{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:12px 0 0}',
  '.qkp-sugg > span{font:700 var(--fs-2xs)/1 var(--font-cond);text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);margin-right:4px}'
].join('\n');
function injectCSS() {
  if (typeof document === 'undefined' || document.getElementById('qkp-css')) return;
  var s = document.createElement('style');
  s.id = 'qkp-css';
  s.textContent = CSS;
  (document.head || document.documentElement).appendChild(s);
}
injectCSS();

/* ─────────────────────────────────────── helpers */
var PROG = {};
/* a default format from the spec unit and the size of the number */
PROG.fmt = function (unit, v) {
  if (!isNum(v)) return '—';
  var u = String(unit || '').toLowerCase();
  if (/(^|[^a-z])(%|pct|percent|share|rate)([^a-z]|$)/.test(u) && Math.abs(v) <= 1.0001) return (v * 100).toFixed(1) + '%';
  var a = Math.abs(v);
  var d = a >= 100 ? 0 : a >= 10 ? 1 : a >= 0.1 ? 2 : 3;
  return (v < 0 ? '−' : '') + Math.abs(v).toFixed(d);
};
function mfmt(M, v) { return M && typeof M.fmt === 'function' ? M.fmt(v) : PROG.fmt(M && M.unit, v); }
function lowerOf(M) { return !!(M && M.dir === 'lower'); }
function styleOf(M) { return !!(M && (M.dir === 'neutral' || M.style)); }
/* QK.prog.ref(json) -> function (group, seasonKey, id) -> { q: [..5], n } | null, on a progression_ref.json
 * ({ q: [10, 25, 50, 75, 90], seasons: { '<season>': { '<group>': { n, m: { id: [q...] } } } } }) */
PROG.ref = function (json) {
  var S = (json && json.seasons) || {};
  return function (group, season, id) {
    var g = (S[String(season)] || {})[group];
    var q = g && g.m ? g.m[id] : null;
    return q && q.length >= 5 ? { q: q, n: g.n } : null;
  };
};
/* the x value of a season row on each axis */
function xOf(S, mode, i) {
  if (mode === 'age') return isNum(S.age) ? Math.floor(S.age) : null;
  if (mode === 'year') return isNum(S.cy) ? S.cy : i + 1;
  return isNum(S.x) ? S.x : (isNum(Number(S.key)) ? Number(String(S.key).slice(0, 4)) : null);
}
/* one row per x (two seasons at one age: the later one stands) */
function dedupe(rows) {
  var at = {};
  rows.forEach(function (r, i) { at[r.x] = i; });
  return rows.filter(function (r, i) { return at[r.x] === i; });
}
function shortLabel(S) {
  var m = /^(\d{4})[-–](\d{2,4})$/.exec(String(S.label || ''));
  return m ? m[1].slice(2) + '-' + m[2].slice(-2) : String(S.label || S.key || '');
}
function sorted(P) {
  return (P.seasons || []).slice().sort(function (a, b) { return (xOf(a, 'season', 0) || 0) - (xOf(b, 'season', 0) || 0); });
}
function sampleText(S) {
  if (!isNum(S.n)) return '';
  return Math.round(S.n).toLocaleString('en-GB') + ' ' + (S.nUnit || 'games') + (isNum(S.nMax) ? ' of ' + Math.round(S.nMax).toLocaleString('en-GB') : '');
}
function teamText(S) {
  if (S.teams && S.teams.length > 1) return S.teams.join(', ');
  return S.team ? (S.team.abbr || S.team.name || '') : '';
}
/* marker size by sample: 7 px at nothing, 16 px at a full season (no season length: by the player's own largest sample) */
function sizeOf(S, nMaxP) {
  var full = isNum(S.nMax) && S.nMax > 0 ? S.nMax : nMaxP;
  if (!isNum(S.n) || !isNum(full) || full <= 0) return 11;
  return 7 + 9 * Math.max(0, Math.min(1, S.n / full));
}
function teamColour(S, T) {
  var c = S.team && S.team.colour;
  return c && QK.color.parse(c) ? QK.color.ensure(c, T.s1, 3) : T.ink3;
}
function hexA(c, a) { return QKC.hexA ? QKC.hexA(c, a) : c; }
function lc(x) { x = String(x || ''); return /^[A-Z][a-z]/.test(x) ? x.charAt(0).toLowerCase() + x.slice(1) : x; }
function pctWord(p) { return QK.ordinal(Math.round(p)); }
/* the axis on seasons or ages: numeric, a tick per season, labels from the rows (season labels or ages) */
function xAxisFor(T, el, xs, labels, mode) {
  var w = el && el.clientWidth ? el.clientWidth : 800, narrow = w < 480;
  var lo = Math.min.apply(null, xs), hi = Math.max.apply(null, xs);
  /* custom ticks at the seasons themselves (a value axis from lo - 0.5 would tick at the half-years); thinned so the
     labels never collide: about 44 px a season label (30 on a phone), 26 px an age */
  var all = []; for (var v = lo; v <= hi; v++) all.push(v);
  var per = mode === 'season' ? (narrow ? 34 : 50) : 26;
  var room = Math.max(1, Math.floor((w - 90) / per)), step = Math.max(1, Math.ceil(all.length / room));
  var vals = all.filter(function (x, i) { return i % step === 0 || x === hi; });
  if (vals.length > 1 && vals[vals.length - 1] - vals[vals.length - 2] < step) vals.splice(vals.length - 2, 1);
  var lab = vals.map(function (x) { var l = labels[x]; return l === undefined ? String(x) : (narrow && mode === 'season' ? l.s : l.l); });
  return QKC.axis(T, { type: 'value', min: lo - 0.5, max: hi + 0.5, split: false, line: true, ticks: { values: vals, labels: lab } });
}

/* a shaded band [lo, hi] at numeric x, as polygons (gaps split it) */
function bandSeries(pts, colour, name) {
  return {
    type: 'custom', name: '_band', silent: true, tooltip: { show: false }, z: 1, data: pts.map(function (p) { return [p[0], p[1], p[2]]; }),
    encode: { x: 0, y: [1, 2] },
    renderItem: function (params, api) {
      if (params.dataIndex !== 0) return null;
      var runs = [], cur = [], last = null;
      pts.forEach(function (p) {
        if (last !== null && p[0] - last > 1.01 && cur.length) { runs.push(cur); cur = []; }
        cur.push(p); last = p[0];
      });
      if (cur.length) runs.push(cur);
      return { type: 'group', children: runs.map(function (r) {
        if (r.length === 1) { var a = api.coord([r[0][0] - 0.18, r[0][2]]), b = api.coord([r[0][0] + 0.18, r[0][1]]); return { type: 'rect', shape: { x: a[0], y: a[1], width: b[0] - a[0], height: b[1] - a[1] }, style: { fill: colour } }; }
        var top = r.map(function (q) { return api.coord([q[0], q[2]]); }), bot = r.slice().reverse().map(function (q) { return api.coord([q[0], q[1]]); });
        return { type: 'polygon', shape: { points: top.concat(bot) }, style: { fill: colour } };
      }) };
    },
    _qkpName: name
  };
}

/* ─────────────────────────────────────── 1. the career progression chart */
/* QKC.progression(el, { player: P, metrics: [M] (1-4), mode: 'value' | 'pct' (default: value for one metric, pct for
 *   several), x: 'season' | 'age', ref: (S, id) -> { q, n } (value mode: the peer median and the middle half),
 *   pctLine: true (value mode: the season percentile as a dashed line on a right axis), peerName: 'forwards',
 *   colour (the player's line; default cobalt), label }) -> the ECharts instance. Team changes are dashed verticals
 *   named with the new team (in its colour); a short or injury-shortened season carries its tag under the point. */
QKC.progression = function (el, o) {
  o = o || {};
  var P = o.player || { seasons: [] }, ms = (o.metrics || []).filter(Boolean).slice(0, 4);
  var mode = o.mode || (ms.length > 1 ? 'pct' : 'value'), xm = o.x === 'age' ? 'age' : 'season';
  var rows = dedupe(sorted(P).map(function (S, i) { return { S: S, x: xOf(S, xm, i) }; }).filter(function (r) { return isNum(r.x); }));
  var peer = o.peerName || 'peers';
  return QKC.mount(el, function (T) {
    if (!rows.length || !ms.length) return { title: { text: 'No seasons to show', left: 'center', top: 'middle', textStyle: { color: T.ink3, fontFamily: T.fontCond } } };
    var xs = rows.map(function (r) { return r.x; });
    var labels = {};
    rows.forEach(function (r) { labels[r.x] = xm === 'age' ? { l: String(r.x), s: String(r.x) } : { l: String(r.S.label || r.x), s: shortLabel(r.S) }; });
    var nMaxP = Math.max.apply(null, rows.map(function (r) { return isNum(r.S.n) ? r.S.n : 0; }).concat([1]));
    var xa = xAxisFor(T, typeof el === 'string' ? document.querySelector(el) : el, xs, labels, xm);
    var gB = 10 + QKC.nameAxis(xa, xm === 'age' ? 'Age (at the season)' : 'Season', 'bottom');
    var series = [], yAxes = [];
    var main = o.colour && QK.color.parse(o.colour) ? QK.color.ensure(o.colour, T.s1, 3) : T.model;
    var cols = [main, T.cat[1], T.cat[2], T.cat[3]];
    /* team changes (season axis only: by age the same) and short seasons */
    var changes = [];
    rows.forEach(function (r, i) {
      if (!i) return;
      var a = rows[i - 1].S.team, b = r.S.team;
      if (a && b && a.abbr && b.abbr && a.abbr !== b.abbr) changes.push({ x: r.x - 0.5, team: b, S: r.S });
    });
    var markTeams = changes.length ? { silent: true, symbol: 'none', animation: false,
      data: changes.map(function (c) { return { xAxis: c.x, lineStyle: { color: teamColour(c.S, T), type: [4, 4], width: 1.5 }, label: Object.assign(QKC.annot(T, { color: teamColour(c.S, T), fontSize: 12 }), { formatter: '→ ' + (c.team.abbr || ''), position: 'end', distance: 4 }) }; }) } : undefined;
    function pointItem(r, y, c, extra) {
      var S = r.S, small = !!S.small;
      var it = { value: [r.x, y], symbolSize: sizeOf(S, nMaxP), itemStyle: small ? { color: T.s1, borderColor: c, borderWidth: 2, opacity: 0.9 } : { color: c, borderColor: T.s1, borderWidth: 1.5 } };
      if (S.partial && !S.short && extra) it.label = Object.assign(QKC.annot(T, { color: T.ink3, fontSize: 11 }), { show: true, position: 'bottom', distance: 8, formatter: 'SO FAR' });
      if (S.short && extra) it.label = Object.assign(QKC.annot(T, { color: T.coral || '#ff6a4d', fontSize: 11 }), { show: true, position: 'bottom', distance: 8, formatter: String(S.short.tag || 'Short season').toUpperCase() });
      return it;
    }
    var tipRows = function (x) { return rows.filter(function (r) { return r.x === x; })[0]; };
    var ya;
    if (mode === 'pct') {
      ya = QKC.axis(T, { min: 0, max: 100, interval: 25, fmt: function (v) { return String(v); } });
      var gT = 12 + QKC.nameAxis(ya, 'Percentile v ' + peer + ' (100 = best)', 'side');
      ms.forEach(function (M, k) {
        var c = cols[k % 4];
        series.push({ type: 'line', name: M.label, z: 3, connectNulls: false, showSymbol: true, symbol: 'circle',
          lineStyle: { width: k ? 2 : 3, color: c }, itemStyle: { color: c },
          endLabel: ms.length > 1 ? { show: true, formatter: M.label, color: c, fontFamily: T.fontCond, fontWeight: 700, fontSize: 12, distance: 6 } : undefined,
          labelLayout: { moveOverlap: 'shiftY' },
          data: rows.map(function (r) { var p = (r.S.pct || {})[M.id]; return isNum(p) ? pointItem(r, p, c, k === 0) : { value: [r.x, null] }; }),
          markLine: k === 0 ? { silent: true, symbol: 'none', animation: false, lineStyle: { color: T.axis, type: [3, 3], width: 1 }, label: Object.assign(QKC.annot(T, { fontSize: 11 }), { formatter: 'peer median', position: 'insideStartTop' }), data: [{ yAxis: 50 }].concat(markTeams ? markTeams.data : []) } : undefined,
          markArea: k === 0 ? { silent: true, itemStyle: { color: hexA(T.ink3, 0.10) }, data: [[{ yAxis: 25 }, { yAxis: 75 }]] } : undefined });
      });
      yAxes = [ya];
      return finish(gT, ms.length > 1 ? 120 : 24);
    }
    /* value mode: one metric, the band and the median from each season's peers */
    var M = ms[0], low = lowerOf(M);
    var ref = typeof o.ref === 'function' ? o.ref : null;
    var band = [], med = [];
    rows.forEach(function (r) {
      var q = ref ? ref(r.S, M.id) : null;
      if (q && q.q) { band.push([r.x, q.q[1], q.q[3]]); med.push([r.x, q.q[2]]); }
    });
    ya = QKC.axis(T, { scale: true, inverse: low, fmt: function (v) { return mfmt(M, v); } });
    var elN = typeof el === 'string' ? document.querySelector(el) : el, narrowY = (elN && elN.clientWidth ? elN.clientWidth : 800) < 560;
    var yName = narrowY ? M.label + (low ? ' (lower is better)' : '') : M.label + (M.unit ? ' (' + M.unit + ')' : '') + (low ? ' · lower is better, plotted up' : '');
    if (narrowY && yName.length > 30) yName = yName.slice(0, 29) + '…';
    var gT2 = 12 + QKC.nameAxis(ya, yName, 'side');
    yAxes = [ya];
    if (band.length) series.push(bandSeries(band, hexA(T.ink3, 0.18), 'Middle half of ' + peer));
    if (med.length) series.push({ type: 'line', name: 'Peer median', z: 2, showSymbol: false, data: med, lineStyle: { color: T.ink3, type: [5, 4], width: 1.5 }, itemStyle: { color: T.ink3 }, connectNulls: false });
    series.push({ type: 'line', name: QK.surname(P.name || '') || 'Player', z: 4, showSymbol: true, symbol: 'circle', lineStyle: { width: 3, color: main }, itemStyle: { color: main },
      data: rows.map(function (r) { var v = (r.S.values || {})[M.id]; return isNum(v) ? pointItem(r, v, main, true) : { value: [r.x, null] }; }),
      markLine: markTeams });
    var pl = o.pctLine !== false && rows.some(function (r) { return isNum((r.S.pct || {})[M.id]); });
    if (pl) {
      var yb = QKC.axis(T, { min: 0, max: 100, interval: 25, split: false, position: 'right', fmt: function (v) { return String(v); } });
      yb.name = narrowY ? 'Pctl' : 'Percentile'; yb.nameLocation = 'end'; yb.nameGap = 8; yb.nameTextStyle.align = 'right';
      yAxes.push(yb);
      series.push({ type: 'line', name: 'Percentile v ' + peer, yAxisIndex: 1, z: 3, showSymbol: true, symbol: 'diamond', symbolSize: 7,
        lineStyle: { width: 1.5, color: T.cat[2], type: [2, 3] }, itemStyle: { color: T.cat[2] },
        data: rows.map(function (r) { var p = (r.S.pct || {})[M.id]; return [r.x, isNum(p) ? p : null]; }) });
    }
    return finish(gT2, pl ? 44 : 24);

    function finish(top, right) {
      return {
        grid: { left: 8, right: right, top: top + 6, bottom: gB + 12, containLabel: true },
        xAxis: xa, yAxis: yAxes.length === 1 ? yAxes[0] : yAxes,
        tooltip: QKC.tooltip(T, { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: T.axis } }, formatter: function (ps) {
          var x = ps && ps.length ? (Array.isArray(ps[0].value) ? ps[0].value[0] : ps[0].axisValue) : null;
          var r = tipRows(Math.round(Number(x)));
          if (!r) return '';
          var S = r.S;
          var head = '<b>' + esc((S.label || '') + (isNum(S.age) ? ' · age ' + Math.floor(S.age) : '')) + '</b><div style="color:#c3c9d4;font-size:12px;margin:2px 0 6px">' + esc([teamText(S), sampleText(S), S.small ? 'under the sample floor' : ''].filter(Boolean).join(' · ')) + '</div>';
          var body = ms.map(function (M2, k) {
            var v = (S.values || {})[M2.id], p = (S.pct || {})[M2.id];
            var txt = mfmt(M2, v) + (isNum(p) ? ' · ' + pctWord(p) + ' pctl' : '');
            return QKC.tipRow(mode === 'pct' ? cols[k % 4] : main, M2.label, txt);
          }).join('');
          if (mode === 'value' && ref) { var q = ref(S, ms[0].id); if (q && q.q) body += QKC.tipRow(T.ink3, 'Peers: median', mfmt(ms[0], q.q[2])) + QKC.tipRow(T.ink3, 'Middle half', mfmt(ms[0], q.q[1]) + ' to ' + mfmt(ms[0], q.q[3])) + (isNum(q.n) ? '<div style="color:#9aa3b2;font-size:11px;margin-top:4px">' + q.n + ' qualified ' + esc(peer) + '</div>' : ''); }
          if (S.short && S.short.text) body += '<div style="color:#ff6a4d;font-size:12px;margin-top:6px">' + esc(S.short.text) + '</div>';
          return head + body;
        } }),
        series: series
      };
    }
  }, { label: o.label || ((P.name || 'Player') + ': ' + ms.map(function (m) { return m.label; }).join(', ') + ' by ' + (xm === 'age' ? 'age' : 'season')) });
};

/* the chart's key (HTML), for the line below a progression chart */
QK.progressionKey = function (o) {
  o = o || {};
  var it = [];
  if (o.mode !== 'pct') {
    it.push('<span><i style="--k:var(--signal)" class="dot"></i>' + esc(o.name || 'Player') + '</span>');
    if (o.band !== false) it.push('<span><i class="band"></i>Middle half of ' + esc(o.peerName || 'peers') + '</span><span><i class="med"></i>Peer median</span>');
    if (o.pctLine) it.push('<span><i style="--k:var(--c-3)"></i>Percentile (right axis)</span>');
  } else it.push('<span><i class="band"></i>Middle half (25th to 75th)</span>');
  it.push('<span><i class="hollow"></i>Under the sample floor</span><span>Bigger dot = more ' + esc(o.nUnit || 'games') + '</span>');
  return '<div class="qkp-keys">' + it.join('') + '</div>';
};

/* ─────────────────────────────────────── 2. the season-by-season percentile heatmap */
/* QK.progressionGrid({ player: P, metrics: [M], groups: [{ label, ids }] (optional sections), peerName, newestFirst })
 * -> HTML: a table, metrics down the side, seasons across (team and age under each), each cell the percentile on the
 * kit's scale with the value, the sample and the peers in its tooltip. Seasons under the floor are dashed (value only).
 * Wide careers scroll inside the card; the metric column stays put. */
QK.progressionGrid = function (o) {
  o = o || {};
  var P = o.player || { seasons: [] }, ms = (o.metrics || []).filter(Boolean);
  var ss = sorted(P);
  if (o.newestFirst) ss.reverse();
  if (!ss.length || !ms.length) return QK.empty('No seasons yet', 'The heatmap appears once a season is in the data.');
  /* rows the player has no value for in any season (a catcher's framing on an outfielder) are left out (dropEmpty: false keeps them) */
  if (o.dropEmpty !== false) ms = ms.filter(function (m) { return ss.some(function (S) { return isNum((S.values || {})[m.id]); }); });
  var byId = {}; ms.forEach(function (m) { byId[m.id] = m; });
  var groups = o.groups && o.groups.length ? o.groups.map(function (g) { return { label: g.label, ms: (g.ids || []).map(function (id) { return byId[id]; }).filter(Boolean) }; }).filter(function (g) { return g.ms.length; }) : [{ label: '', ms: ms }];
  var peer = o.peerName || 'peers';
  var head = '<tr><th class="qkp-m" scope="col">Metric · percentile</th>' + ss.map(function (S) {
    var t = [teamText(S), isNum(S.age) ? Math.floor(S.age) : ''].filter(function (x) { return x !== ''; }).join(' · ');
    var tip = (S.label || '') + ': ' + [teamText(S), sampleText(S), S.small ? 'under the sample floor, so no percentiles' : '', S.short ? S.short.text : ''].filter(Boolean).join(' · ');
    return '<th scope="col" class="' + (S.small ? 'is-small' : '') + (S.short ? ' is-short' : '') + '" data-tip="' + esc(tip) + '"><span class="s">' + esc(shortLabel(S)) + '</span><span class="t">' + esc(t) + (S.short ? ' · ' + esc(String(S.short.tag || 'short').toUpperCase()) : '') + '</span></th>';
  }).join('') + '</tr>';
  var body = groups.map(function (g) {
    return (g.label ? '<tr class="qkp-gh"><th colspan="' + (ss.length + 1) + '">' + esc(g.label) + '</th></tr>' : '') + g.ms.map(function (M) {
      return '<tr><th class="qkp-m" scope="row"' + (M.tip ? ' data-tip="' + esc(M.tip) + '"' : '') + '>' + esc(M.label) + (M.ours ? QK.ours({ short: true, model: M.ours.name, about: M.ours.about }) : '') + '</th>' + ss.map(function (S) {
        var v = (S.values || {})[M.id], p = (S.pct || {})[M.id];
        var tip = M.label + ', ' + (S.label || '') + ': ' + mfmt(M, v) + (M.unit ? ' ' + M.unit : '') + (isNum(p) ? ' · ' + pctWord(p) + ' percentile v ' + peer : (isNum(v) ? (S.small ? ' · under the sample floor' : ' · no percentile') : ' · not in the data')) + (sampleText(S) ? ' · ' + sampleText(S) : '');
        if (isNum(p)) {
          var st = styleOf(M);
          return '<td><span class="qkp-c" tabindex="0" data-tip="' + esc(tip) + '" style="background:' + (st ? 'var(--s-3)' : QK.pctColor(p)) + ';color:' + (st ? 'var(--ink-1)' : QK.pctInk(p)) + '">' + Math.round(p) + '</span></td>';
        }
        return '<td><span class="qkp-c ' + (isNum(v) ? 'sm' : 'na') + '" tabindex="0" data-tip="' + esc(tip) + '">' + (isNum(v) ? '·' : '–') + '</span></td>';
      }).join('') + '</tr>';
    }).join('');
  }).join('');
  return '<div class="qk-table-wrap qkp-gridw"><table class="qkp-grid" aria-label="' + esc((P.name || 'Player') + ': percentiles by season') + '"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div>' +
    '<div class="qkp-scale"><span>0</span><b></b><span>100 · percentile v ' + esc(peer) + ' that season</span><span class="sm"></span><span>under the floor (value in the tooltip)</span>' + '</div>';
};

/* ─────────────────────────────────────── 3. year-over-year deltas and the career arc */
function pairsOf(P, ms) {
  var ss = sorted(P), out = [];
  for (var i = 1; i < ss.length; i++) {
    var a = ss[i - 1], b = ss[i];
    if (a.small || b.small || a.partial || b.partial) continue;
    ms.forEach(function (M) {
      if (styleOf(M)) return;
      var pa = (a.pct || {})[M.id], pb = (b.pct || {})[M.id];
      if (isNum(pa) && isNum(pb)) out.push({ M: M, a: a, b: b, pa: pa, pb: pb, d: pb - pa, va: (a.values || {})[M.id], vb: (b.values || {})[M.id] });
    });
  }
  return out;
}
/* QK.progressionDeltas({ player: P, metrics: [M] (the deep set), limit: 4, peerName }) -> HTML: the biggest jumps and
 * drops between consecutive seasons (both above the floor), in percentile points against the position's peers. */
QK.progressionDeltas = function (o) {
  o = o || {};
  var all = pairsOf(o.player || {}, (o.metrics || []).filter(Boolean)), lim = o.limit || 4;
  if (!all.length) return QK.empty('No season-to-season changes yet', 'They appear once two seasons in a row are above the sample floor.');
  var pick = function (list) { var seen = {}, out = []; list.forEach(function (x) { var k = x.M.id; if (!seen[k] && out.length < lim) { seen[k] = 1; out.push(x); } }); return out; };
  var ups = pick(all.filter(function (x) { return x.d >= 5; }).sort(function (x, y) { return y.d - x.d; }));
  var dns = pick(all.filter(function (x) { return x.d <= -5; }).sort(function (x, y) { return x.d - y.d; }));
  var li = function (x) {
    var up = x.d > 0;
    return '<li><span class="m">' + esc(x.M.label) + (x.M.ours ? QK.ours({ short: true, model: x.M.ours.name }) : '') + '</span><span class="d ' + (up ? 'qkp-up' : 'qkp-down') + '">' + (up ? '+' : '−') + Math.abs(Math.round(x.d)) + '<small>PCTL PTS</small></span>' +
      '<span class="w"><b>' + esc(shortLabel(x.a)) + ' → ' + esc(shortLabel(x.b)) + '</b>: from the ' + pctWord(x.pa) + ' to the ' + pctWord(x.pb) + ' percentile (' + esc(mfmt(x.M, x.va)) + ' → ' + esc(mfmt(x.M, x.vb)) + (x.M.unit && !/%$/.test(mfmt(x.M, x.vb)) && !/^(rate|share|%.*|.*scale)$/i.test(x.M.unit) ? ' ' + esc(x.M.unit) : '') + ')' +
      (x.b.team && x.a.team && x.a.team.abbr !== x.b.team.abbr ? ', the season of the move to ' + esc(x.b.team.abbr || x.b.team.name || '') : '') + '.</span></li>';
  };
  return '<div class="qkp-dl"><div><h4>Biggest jumps</h4>' + (ups.length ? '<ul>' + ups.map(li).join('') + '</ul>' : '<p class="qkp-note">No jump of 5 percentile points or more.</p>') + '</div>' +
    '<div><h4>Biggest drops</h4>' + (dns.length ? '<ul>' + dns.map(li).join('') + '</ul>' : '<p class="qkp-note">No drop of 5 percentile points or more.</p>') + '</div></div>';
};
/* QK.careerArc({ player: P, metrics: [M] (the headline set: the season score is their mean percentile), all: [M] (the
 *   deep set, for the biggest jump in the text), key: M (an anchor metric shown beside the peak, e.g. WAR), peerName,
 *   noun: 'season' }) -> { html (the black tiles), text (the short version), peak: S, score, agePeak, trend: { slope,
 *   word, n } }. A season scores when it is above the floor and has at least half the headline percentiles. */
QK.careerArc = function (o) {
  o = o || {};
  var P = o.player || { seasons: [] }, hs = (o.metrics || []).filter(function (m) { return m && !styleOf(m); });
  var ss = sorted(P), peer = o.peerName || 'peers', sur = P.short || QK.surname(P.name || '') || 'The player';
  var scored = ss.map(function (S) {
    if (S.small || S.partial) return null;
    var ps = hs.map(function (M) { return (S.pct || {})[M.id]; }).filter(isNum);
    return ps.length && ps.length >= Math.max(1, Math.ceil(hs.length / 2)) ? { S: S, score: ps.reduce(function (a, b) { return a + b; }, 0) / ps.length } : null;
  }).filter(Boolean);
  var res = { html: '', text: '', peak: null, score: null, agePeak: null, trend: null };
  if (!ss.length) return res;
  var first = ss[0], last = ss[ss.length - 1];
  var span = ss.length + ' season' + (ss.length === 1 ? '' : 's') + ' in the data' + (ss.length > 1 ? ' (' + (first.label || '') + ' to ' + (last.label || '') + ')' : '');
  var best = null;
  scored.forEach(function (x) { if (!best || x.score > best.score) best = x; });
  if (best) { res.peak = best.S; res.score = best.score; res.agePeak = isNum(best.S.age) ? Math.floor(best.S.age) : null; }
  var l3 = scored.slice(-3);
  if (l3.length >= 2) {
    var n = l3.length, mx = (n - 1) / 2, my = l3.reduce(function (a, x) { return a + x.score; }, 0) / n, num = 0, den = 0;
    l3.forEach(function (x, i) { num += (i - mx) * (x.score - my); den += (i - mx) * (i - mx); });
    var sl = den ? num / den : 0;
    res.trend = { slope: sl, n: n, word: sl >= 6 ? 'rising' : sl >= 2 ? 'edging up' : sl <= -6 ? 'falling' : sl <= -2 ? 'slipping' : 'steady' };
  }
  var K = o.key || null, kBest = null;
  if (K) ss.forEach(function (S) { var v = (S.values || {})[K.id]; if (isNum(v) && !S.small && (!kBest || (lowerOf(K) ? v < kBest.v : v > kBest.v))) kBest = { S: S, v: v }; });
  var tiles = [];
  tiles.push({ label: 'Peak season', value: best ? (best.S.label || '') : '—', text: true, sub: best ? 'headline numbers averaged the ' + pctWord(best.score) + ' percentile' : 'no season above the floor yet', signal: !!best });
  tiles.push({ label: 'Age at peak', value: isNum(res.agePeak) ? String(res.agePeak) : '—', sub: best && best.S.team ? (best.S.team.name || best.S.team.abbr || '') : '' });
  tiles.push({ label: 'Last ' + (res.trend ? res.trend.n : 3) + ' seasons', value: res.trend ? (res.trend.slope >= 0 ? '+' : '−') + Math.abs(res.trend.slope).toFixed(0) : '—', unit: res.trend ? 'a season' : '', sub: res.trend ? res.trend.word + ' (percentile points on the headline set)' : 'needs two seasons above the floor' });
  if (K && kBest) tiles.push({ label: 'Best ' + K.label, value: mfmt(K, kBest.v), sub: (kBest.S.label || '') + (K.unit ? ' · ' + K.unit : ''), signal: !!K.ours });
  res.html = QK.stats(tiles);
  /* the short version */
  var t = sur + ' has ' + span + '.';
  if (best) {
    var cur = scored[scored.length - 1];
    t += best.S === last ? ' This season is the peak so far: the headline numbers average the ' + pctWord(best.score) + ' percentile of ' + peer + '.'
      : ' The peak so far: ' + (best.S.label || '') + (isNum(res.agePeak) ? ', at ' + res.agePeak : '') + ', when the headline numbers averaged the ' + pctWord(best.score) + ' percentile of ' + peer + '.';
    if (cur && cur.S !== best.S) t += ' The latest full season (' + (cur.S.label || '') + ') reads the ' + pctWord(cur.score) + '.';
    var part = ss.filter(function (S) { return S.partial && !S.small; })[0];
    if (part) { var pp2 = hs.map(function (M) { return (part.pct || {})[M.id]; }).filter(isNum); if (pp2.length) t += ' So far in ' + (part.label || 'this season') + ' (' + sampleText(part) + '): the ' + pctWord(pp2.reduce(function (a, b) { return a + b; }, 0) / pp2.length) + ', a small sample.'; }
  } else t += ' No season clears the sample floor yet, so there is no percentile arc to read.';
  if (res.trend) t += ' Over the last ' + res.trend.n + ' seasons the profile is ' + res.trend.word + (res.trend.word === 'steady' ? '' : ' (' + (res.trend.slope >= 0 ? '+' : '−') + Math.abs(res.trend.slope).toFixed(0) + ' a season)') + '.';
  var pr = pairsOf(P, (o.all || hs).filter(Boolean));
  if (pr.length) {
    var up = pr.slice().sort(function (a, b) { return b.d - a.d; })[0], dn = pr.slice().sort(function (a, b) { return a.d - b.d; })[0];
    if (up && up.d >= 10) t += ' Biggest jump: ' + lc(up.M.label) + ', from the ' + pctWord(up.pa) + ' to the ' + pctWord(up.pb) + ' percentile (' + shortLabel(up.a) + ' to ' + shortLabel(up.b) + ').';
    if (dn && dn.d <= -10) t += ' Biggest drop: ' + lc(dn.M.label) + ', from the ' + pctWord(dn.pa) + ' to the ' + pctWord(dn.pb) + ' (' + shortLabel(dn.a) + ' to ' + shortLabel(dn.b) + ').';
  }
  var shorts = ss.filter(function (S) { return S.short && S.short.kind === 'injury'; });
  if (shorts.length) t += ' Injury cut short ' + shorts.map(function (S) { return S.label; }).join(', ') + '.';
  res.text = t;
  return res;
};

/* ─────────────────────────────────────── 4. compare progression */
/* QK.compareProgression(el, { players: [P] (2-4), metrics: [M] (the deep set; ours first through cat), cat (QK.spec
 *   catalogue: optgroups "Our models" / "Box score"), metric: id, x: 'season' | 'age' | 'year', y: 'value' | 'pct',
 *   ref: (P, S, id) -> { q, n } (the band, by season when every player shares the peer group), peerName: (P) -> 'forwards',
 *   onState: ({ metric, x, y }) -> void (keep the URL in step), suggest: [{ id, name, sub, href }] (players to add),
 *   cyNote: 'career year counts seasons in our data (from 2009-10)', height: 380 })
 * Renders the controls, the chart, a key and the season-by-season table (each player's best season highlighted). */
QK.compareProgression = function (el, o) {
  el = typeof el === 'string' ? document.querySelector(el) : el;
  if (!el) return null;
  o = o || {};
  var Ps = (o.players || []).filter(Boolean).slice(0, 4), ms = (o.metrics || []).filter(Boolean);
  if (!Ps.length || !ms.length) { el.innerHTML = QK.empty('Pick two players', 'Add players to compare their careers season by season.'); return null; }
  var byId = {}; ms.forEach(function (m) { byId[m.id] = m; });
  var st = { metric: byId[o.metric] ? o.metric : ms[0].id, x: o.x === 'age' || o.x === 'year' ? o.x : 'season', y: o.y === 'pct' ? 'pct' : 'value' };
  /* only metrics some player has a value for */
  var has = function (id) { return Ps.some(function (P) { return (P.seasons || []).some(function (S) { return isNum((S.values || {})[id]); }); }); };
  var opts = ms.filter(function (m) { return has(m.id); }).map(function (m) { return { value: m.id, key: m.id, label: m.label }; });
  if (!opts.length) opts = ms.map(function (m) { return { value: m.id, key: m.id, label: m.label }; });
  if (!opts.some(function (x) { return x.value === st.metric; })) st.metric = opts[0].value;
  var uid = 'qkp' + Math.random().toString(36).slice(2, 8);
  var seg = function (k, items) { return '<div class="qk-seg" role="group" data-k="' + k + '" aria-label="' + (k === 'x' ? 'Line up by' : 'Show') + '">' + items.map(function (it) { return '<button type="button" data-value="' + it[0] + '" aria-pressed="' + (st[k] === it[0]) + '">' + esc(it[1]) + '</button>'; }).join('') + '</div>'; };
  el.innerHTML = '<div class="qkp-ctl"><label for="' + uid + '-m">Metric <select class="qk-select" id="' + uid + '-m">' + QK.optgroups(opts, o.cat || null, { selected: st.metric }) + '</select></label>' +
    seg('x', [['season', 'By season'], ['age', 'By age'], ['year', 'Career year']]) + seg('y', [['value', 'Value'], ['pct', 'Percentile']]) + '</div>' +
    '<div class="qkp-cc" id="' + uid + '-c" style="height:' + (o.height || 380) + 'px"></div><div id="' + uid + '-k"></div><p class="qkp-note" id="' + uid + '-n"></p>' +
    '<div id="' + uid + '-t" style="margin-top:14px"></div>' +
    (o.suggest && o.suggest.length ? '<div class="qkp-sugg"><span>Add a player</span>' + o.suggest.slice(0, 6).map(function (s) { return '<a class="qk-chip" href="' + esc(s.href) + '"' + (s.sub ? ' data-tip="' + esc(s.sub) + '"' : '') + '>+ ' + esc(s.name) + '</a>'; }).join('') + '</div>' : '');
  var sel = el.querySelector('#' + uid + '-m');
  sel.addEventListener('change', function () { st.metric = sel.value; draw(); });
  Array.prototype.forEach.call(el.querySelectorAll('.qk-seg'), function (sg) { QK.seg(sg, function (v) { st[sg.getAttribute('data-k')] = v; draw(); }); });
  function rowsOf(P) { return dedupe(sorted(P).map(function (S, i) { return { S: S, x: xOf(S, st.x, i) }; }).filter(function (r) { return isNum(r.x); })); }
  function draw() {
    if (o.onState) { try { o.onState({ metric: st.metric, x: st.x, y: st.y }); } catch (e) { /* the page's own */ } }
    var M = byId[st.metric] || ms[0], y = st.y, low = lowerOf(M);
    var R = Ps.map(rowsOf);
    var groups = {}; Ps.forEach(function (P) { (P.seasons || []).forEach(function (S) { if (S.group) groups[S.group] = 1; }); });
    var oneGroup = Object.keys(groups).length <= 1;
    var useBand = y === 'value' && st.x === 'season' && oneGroup && typeof o.ref === 'function';
    var xsAll = []; R.forEach(function (rs) { rs.forEach(function (r) { if (xsAll.indexOf(r.x) < 0) xsAll.push(r.x); }); });
    xsAll.sort(function (a, b) { return a - b; });
    var labels = {};
    R.forEach(function (rs) { rs.forEach(function (r) { if (!labels[r.x]) labels[r.x] = st.x === 'season' ? { l: String(r.S.label || r.x), s: shortLabel(r.S) } : { l: String(r.x), s: String(r.x) }; }); });
    var nMaxAll = 1; R.forEach(function (rs) { rs.forEach(function (r) { if (isNum(r.S.n) && r.S.n > nMaxAll) nMaxAll = r.S.n; }); });
    var cEl = el.querySelector('#' + uid + '-c');
    var peerOf = function (P) { return o.peerName ? o.peerName(P) : 'peers'; };
    QKC.mount(cEl, function (T) {
      if (!xsAll.length) return { title: { text: 'No seasons to show', left: 'center', top: 'middle', textStyle: { color: T.ink3, fontFamily: T.fontCond } } };
      var cols = [T.cat[0], T.cat[1], T.cat[2], T.cat[3]];
      var xa = xAxisFor(T, cEl, xsAll, labels, st.x);
      var gB = 10 + QKC.nameAxis(xa, st.x === 'age' ? 'Age (at the season)' : st.x === 'year' ? 'Career year (1 = first season in the data)' : 'Season', 'bottom');
      var ya = y === 'pct' ? QKC.axis(T, { min: 0, max: 100, interval: 25, fmt: function (v) { return String(v); } }) : QKC.axis(T, { scale: true, inverse: low, fmt: function (v) { return mfmt(M, v); } });
      var nY = (cEl.clientWidth || 800) < 560;
      var yN = y === 'pct' ? M.label + (nY ? ' (pctl)' : ': percentile v peers (100 = best)') : M.label + (M.unit && !nY ? ' (' + M.unit + ')' : '') + (low ? (nY ? ' (lower is better)' : ' · lower is better, plotted up') : '');
      if (nY && yN.length > 34) yN = yN.slice(0, 33) + '…';
      var gT = 12 + QKC.nameAxis(ya, yN, 'side');
      var series = [];
      if (useBand) {
        var band = [], med = [];
        xsAll.forEach(function (x) {
          var hit = null;
          R.forEach(function (rs, i) { rs.forEach(function (r) { if (!hit && r.x === x) hit = o.ref(Ps[i], r.S, M.id); }); });
          if (hit && hit.q) { band.push([x, hit.q[1], hit.q[3]]); med.push([x, hit.q[2]]); }
        });
        if (band.length) series.push(bandSeries(band, hexA(T.ink3, 0.16), 'band'));
        if (med.length) series.push({ type: 'line', name: 'Peer median', z: 2, showSymbol: false, data: med, lineStyle: { color: T.ink3, type: [5, 4], width: 1.5 }, itemStyle: { color: T.ink3 } });
      }
      Ps.forEach(function (P, i) {
        var c = cols[i % 4];
        series.push({ type: 'line', name: P.short || QK.surname(P.name || '') || ('Player ' + (i + 1)), z: 4, showSymbol: true, symbol: 'circle', connectNulls: false,
          lineStyle: { width: 3, color: c }, itemStyle: { color: c },
          endLabel: { show: true, formatter: P.short || QK.surname(P.name || ''), color: c, fontFamily: T.fontCond, fontWeight: 700, fontSize: 13, distance: 6 },
          labelLayout: { moveOverlap: 'shiftY' },
          data: xsAll.map(function (x) {
            var r = R[i].filter(function (q) { return q.x === x; })[0];
            var v = r ? (y === 'pct' ? (r.S.pct || {})[M.id] : (r.S.values || {})[M.id]) : null;
            if (!isNum(v)) return { value: [x, null] };
            var small = !!r.S.small, full = isNum(r.S.nMax) && r.S.nMax > 0 ? r.S.nMax : nMaxAll;
            return { value: [x, v], symbolSize: isNum(r.S.n) ? 6 + 8 * Math.max(0, Math.min(1, r.S.n / full)) : 9, itemStyle: small ? { color: T.s1, borderColor: c, borderWidth: 2 } : { color: c, borderColor: T.s1, borderWidth: 1.5 } };
          }),
          markLine: i === 0 && y === 'pct' ? { silent: true, symbol: 'none', animation: false, lineStyle: { color: T.axis, type: [3, 3], width: 1 }, label: Object.assign(QKC.annot(T, { fontSize: 11 }), { formatter: 'peer median', position: 'insideStartTop' }), data: [{ yAxis: 50 }] } : undefined });
      });
      return {
        grid: { left: 8, right: 96, top: gT + 6, bottom: gB + 12, containLabel: true }, xAxis: xa, yAxis: ya,
        tooltip: QKC.tooltip(T, { trigger: 'axis', formatter: function (ps) {
          var x = ps && ps.length ? (Array.isArray(ps[0].value) ? ps[0].value[0] : ps[0].axisValue) : null;
          x = Math.round(Number(x));
          var head = '<b>' + esc(st.x === 'age' ? 'Age ' + x : st.x === 'year' ? 'Career year ' + x : (labels[x] ? labels[x].l : x)) + '</b>';
          return head + Ps.map(function (P, i) {
            var r = R[i].filter(function (q) { return q.x === x; })[0];
            if (!r) return '';
            var v = (r.S.values || {})[M.id], p = (r.S.pct || {})[M.id];
            return QKC.tipRow(cols[i % 4], (P.short || QK.surname(P.name || '')) + (st.x !== 'season' ? ' (' + shortLabel(r.S) + ')' : ''), mfmt(M, v) + (isNum(p) ? ' · ' + pctWord(p) : '') + (r.S.small ? ' · small sample' : ''));
          }).join('');
        } }),
        series: series
      };
    }, { label: Ps.map(function (P) { return P.name; }).join(', ') + ': ' + M.label + ' by ' + (st.x === 'age' ? 'age' : st.x === 'year' ? 'career year' : 'season') });
    /* key and note */
    el.querySelector('#' + uid + '-k').innerHTML = '<div class="qkp-keys">' + Ps.map(function (P, i) { return '<span><i style="--k:var(--c-' + (i + 1) + ')"></i>' + esc(P.name || '') + '</span>'; }).join('') +
      (useBand ? '<span><i class="band"></i>Middle half of ' + esc(peerOf(Ps[0])) + '</span><span><i class="med"></i>Peer median</span>' : '') + '<span><i class="hollow"></i>Under the sample floor</span></div>';
    var notes = [];
    if (M.tip) notes.push('<b>' + esc(M.label) + ':</b> ' + esc(M.tip));
    if (y === 'pct') notes.push('Percentiles are against each player’s own position group in that season, so they compare across eras.');
    else if (!oneGroup) notes.push('The players sit in different peer groups, so the peer band is off; switch to percentiles to compare like with like.');
    if (st.x === 'year' && o.cyNote) notes.push(esc(o.cyNote));
    el.querySelector('#' + uid + '-n').innerHTML = notes.join(' ');
    /* the table: each x down the side, a column per player; each player's best season under the volt stroke */
    var bestOf = R.map(function (rs) {
      var b = null;
      rs.forEach(function (r) { var v = y === 'pct' ? (r.S.pct || {})[M.id] : (r.S.values || {})[M.id]; if (!isNum(v) || r.S.small || r.S.partial) return; var better = y === 'pct' ? true : !lowerOf(M); if (!b || (better ? v > b.v : v < b.v)) b = { x: r.x, v: v }; });
      return b;
    });
    var th = '<tr><th scope="col">' + esc(st.x === 'age' ? 'Age' : st.x === 'year' ? 'Year' : 'Season') + '</th>' + Ps.map(function (P, i) { return '<th scope="col" class="num"><span class="k" style="--k:var(--c-' + (i + 1) + ')"></span>' + esc(P.short || QK.surname(P.name || '')) + '</th>'; }).join('') + '</tr>';
    var tb = xsAll.map(function (x) {
      return '<tr><th scope="row">' + esc(labels[x] ? labels[x].l : x) + '</th>' + Ps.map(function (P, i) {
        var r = R[i].filter(function (q) { return q.x === x; })[0];
        if (!r) return '<td class="num sm">–</td>';
        var v = (r.S.values || {})[M.id], p = (r.S.pct || {})[M.id];
        var best = bestOf[i] && bestOf[i].x === x;
        var cell = (y === 'pct' ? (isNum(p) ? pctWord(p) : '–') : mfmt(M, v)) + (y === 'value' && isNum(p) && !styleOf(M) ? '<span class="pc" style="background:' + QK.pctColor(p) + ';color:' + QK.pctInk(p) + '">' + Math.round(p) + '</span>' : '');
        var tip = (P.name || '') + ', ' + (r.S.label || '') + ': ' + [teamText(r.S), isNum(r.S.age) ? 'age ' + Math.floor(r.S.age) : '', sampleText(r.S), r.S.small ? 'under the sample floor' : '', r.S.partial ? 'season in progress' : '', r.S.short ? r.S.short.text : ''].filter(Boolean).join(' · ');
        return '<td class="num' + (best ? ' best' : '') + (r.S.small ? ' sm' : '') + '" data-tip="' + esc(tip) + '">' + cell + '</td>';
      }).join('') + '</tr>';
    }).join('');
    el.querySelector('#' + uid + '-t').innerHTML = '<div class="qk-table-wrap"><table class="qk-table dense qkp-ct"><caption class="qk-sr">' + esc(M.label) + ' by ' + esc(st.x) + '</caption><thead>' + th + '</thead><tbody>' + tb + '</tbody></table></div>' +
      '<p class="qkp-note">Each player’s best season above the sample floor is marked BEST' + (y === 'value' ? '; the small box is the percentile against the position that season' : '') + '.</p>';
  }
  draw();
  return { state: st, redraw: draw };
};

QK.prog = PROG;
root.QKP = { prog: PROG };
})(window);
