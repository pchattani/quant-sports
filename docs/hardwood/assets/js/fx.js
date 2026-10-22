/* The Quant Hardwood — shared helpers for the catalogue pages (players, teams, leaders,
 * awards, lab, compare, calibration, docs): HW.fx.
 *
 * Read lazily at render time by each module (const FX = () => HW.fx), so script order
 * does not matter. Everything here degrades to a local implementation when the core
 * (core.js) or charts (charts.js) helper of the same job is missing.
 *
 * Data contract: oddsmarkets/basketball/PAYLOADS.md. */
(function (HW) {
'use strict';

const FX = HW.fx = HW.fx || {};

// ── basics ─────────────────────────────────────────────────────────────────

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const esc = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
FX.isNum = isNum;
FX.esc = HW.esc || esc;
FX.alive = el => !!el && el.isConnected;
FX.has = v => v !== undefined && v !== null && !(typeof v === 'number' && !isFinite(v));
FX.ok = d => !!d && d.ok !== false;
FX.muted = t => (HW.muted ? HW.muted(t) : '<div class="muted">' + t + '</div>');
FX.num = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
FX.signed = (v, d) => {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
};
FX.pct = (p, d) => {
  if (HW.pct) return HW.pct(p, d);
  if (!isNum(p)) return '—';
  return (p * 100).toFixed(d === undefined ? 1 : d) + '%';
};
FX.ordinal = n => {
  if (HW.ordinal) return HW.ordinal(n);
  if (!isNum(n)) return '—';
  const v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
};
FX.fmtDate = (s, o) => {
  if (HW.fmtDate) return HW.fmtDate(s, o);
  if (!s) return '—';
  const d = new Date(String(s).length === 10 ? s + 'T12:00:00Z' : s);
  return isNaN(d.getTime()) ? String(s) : d.toDateString().slice(4);
};
FX.fmtStamp = s => (HW.fmtStamp ? HW.fmtStamp(s) : (s ? String(s).replace('T', ' ').replace(/:\d\dZ?$/, '') : ''));
FX.mmss = sec => { if (!isNum(sec)) return '—'; const m = Math.floor(sec / 60), s = Math.round(sec - m * 60); return m + ':' + (s < 10 ? '0' : '') + s; };

/* Format a catalogue value by its declared fmt: int|1|2|3|pct|pm|sec (PAYLOADS.md).
 * pct values are fractions (rates are 3 dp); a value above 1.5 is taken as already in %. */
FX.fmtV = (v, fmt) => {
  if (HW.fmtVal && fmt) return HW.fmtVal(v, fmt);
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (fmt) {
    case 'int': return String(Math.round(x));
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'prob': return FX.pct(x);
    case 'pm': case 'signed': return FX.signed(x, 1);
    case 'sec': return FX.mmss(x);
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2);
  }
};
FX.fmt = (m, v) => FX.fmtV(v, (m || {}).fmt);
FX.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
FX.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
FX.sd = a => { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = FX.mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); };
FX.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
FX.C = HW.C || { bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d', text: '#e6edf3', text2: '#8b949e', text3: '#6e7681', blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316', purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8' };
FX.PALETTE = HW.PALETTE || ['#58a6ff', '#3fb950', '#f97316', '#bc8cff', '#f85149', '#d29922', '#39d0d8', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
FX.CA = '#58a6ff'; FX.CB = '#f97316';

/* Normalise a table-ish payload to an array of row objects:
 * [{...}], {cols, rows}, {fields, rows}, {key: {...}} (key kept as _key), or pandas-style {col: {i: v}}. */
FX.rowsOf = x => {
  if (!x) return [];
  if (Array.isArray(x)) {
    if (x.length && Array.isArray(x[0])) return [];
    return x.filter(r => r && typeof r === 'object');
  }
  if (typeof x !== 'object') return [];
  const cols = x.cols || x.columns || x.fields;
  if (Array.isArray(cols) && Array.isArray(x.rows)) return x.rows.map(r => { const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
  if (Array.isArray(x.cells)) return FX.rowsOf(x.cells);
  const keys = Object.keys(x);
  if (keys.length && keys.every(k => x[k] && typeof x[k] === 'object' && !Array.isArray(x[k]))) {
    const first = x[keys[0]];
    const inner = Object.keys(first);
    // pandas orient="dict" ({col: {idx: v}}) has numeric inner keys
    if (inner.length && inner.every(k => /^\d+$/.test(k)) && keys.every(k => typeof x[k][inner[0]] !== 'object')) {
      return inner.map(i => { const o = {}; keys.forEach(c => { o[c] = x[c][i]; }); return o; });
    }
    return keys.map(k => Object.assign({ _key: k }, x[k]));
  }
  return [];
};

// ── league, season, names ──────────────────────────────────────────────────

FX.L = (params, state) => {
  const l = (params && (params.league || params.L)) || (state && state.league) || (HW.state && HW.state.league) || 'nba';
  return String(l).toLowerCase() === 'wnba' ? 'wnba' : 'nba';
};
FX.indexL = L => { const idx = FX.INDEX || (HW.index ? HW.index() : null) || {}; return ((idx.leagues || {})[L]) || {}; };
FX.current = L => FX.indexL(L).current_season || null;
FX.S = (params, state, L) => {
  const raw = params && (params.season || params.year || (params.query || {}).season);
  if (isNum(raw)) return Number(raw);
  const st = state || HW.state || {};
  if (isNum(st.season) && (!st.league || st.league === L)) return Number(st.season);
  return FX.current(L) || new Date().getFullYear();
};
/* Load index.json once (names, colours, seasons) and remember it. */
FX.ready = () => (FX.INDEX ? Promise.resolve(FX.INDEX) : HW.load('index.json').then(d => { FX.INDEX = d || {}; return FX.INDEX; }));
FX.NAMES = FX.NAMES || { nba: {}, wnba: {} };     // pid -> {name, team}
FX.learnPlayers = (L, cat) => {
  const P = ((cat || {}).players) || {};
  Object.keys(P).forEach(id => { const p = P[id] || {}; if (p.name) FX.NAMES[L][id] = { name: p.name, team: p.team, pos: p.pos }; });
};
FX.team = (L, tid) => (FX.indexL(L).teams || {})[tid] || null;
FX.teamName = (L, tid) => {
  const t = FX.team(L, tid);
  if (t && t.name) return t.name;
  if (HW.teamName) return HW.teamName(L, tid);
  return tid ? String(tid) : '—';
};
FX.teamAbbr = (L, tid) => (HW.teamAbbr ? HW.teamAbbr(L, tid) : ((FX.team(L, tid) || {}).abbr || String(FX.teamName(L, tid)).slice(0, 3).toUpperCase()));
FX.teamColour = (L, tid) => {
  if (HW.teamColour) return HW.teamColour(L, tid);
  const t = FX.team(L, tid);
  if (t && t.colour) return String(t.colour).charAt(0) === '#' ? t.colour : '#' + t.colour;
  let h = 0; String(tid || '').split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; });
  return FX.PALETTE[h % FX.PALETTE.length];
};
FX.playerName = (L, pid) => ((FX.NAMES[L] || {})[pid] || {}).name || (HW.playerName ? HW.playerName(L, pid) : '#' + pid);
FX.surname = n => { const p = String(n || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : p[0]; };
FX.bar = (L, tid) => '<span class="team-bar" style="background:' + esc(FX.teamColour(L, tid)) + '"></span>';
/* Links keep the season shown (core adds ?s= when it is not the current one). */
FX.SEASON = null;
FX.teamHref = (L, tid, S) => (HW.teamHref ? HW.teamHref(L, tid, S || FX.SEASON) : '#/' + L + '/team/' + encodeURIComponent(tid));
FX.playerHref = (L, pid, S) => (HW.playerHref ? HW.playerHref(L, pid, S || FX.SEASON) : '#/' + L + '/player/' + encodeURIComponent(pid));
FX.gameHref = (L, gid) => (HW.gameHref ? HW.gameHref(L, gid, FX.SEASON) : '#/' + L + '/game/' + encodeURIComponent(gid));
FX.href = (L, sub, S) => (HW.href ? HW.href(L, sub, S || FX.SEASON) : '#/' + L + '/' + sub);
FX.teamLink = (L, tid, opts) => {
  if (!tid) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.abbr ? FX.teamAbbr(L, tid) : (o.name || FX.teamName(L, tid));
  return '<a class="team-link" href="' + FX.teamHref(L, tid, o.season) + '">' + (o.bar === false ? '' : FX.bar(L, tid)) + esc(label) + '</a>';
};
FX.playerLink = (L, pid, name, team, S) => {
  if (!pid) return '<span class="muted-inline">—</span>';
  return '<a class="ply-link" href="' + FX.playerHref(L, pid, S) + '">' + (team ? FX.bar(L, team) : '') + esc(name || FX.playerName(L, pid)) + '</a>';
};
FX.gameLink = (L, gid, label) => '<a class="game-link" href="' + FX.gameHref(L, gid) + '">' + esc(label || 'game') + '</a>';
FX.ageOf = dob => {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};

/* data/<L>/<S>/<file> */
FX.path = (L, S, f) => L + '/' + S + '/' + f;
FX.season = (L, S) => HW.loadAll([FX.path(L, S, 'players.json'), FX.path(L, S, 'teams.json'), FX.path(L, S, 'season.json')])
  .then(r => { FX.learnPlayers(L, r[0]); return r; });
/* First payload that loads and is ok, from a list of paths. */
FX.first = paths => {
  const tryI = i => (i >= paths.length ? Promise.resolve(null) : HW.load(paths[i]).then(d => (d && d.ok !== false ? d : (i + 1 < paths.length ? tryI(i + 1) : d))));
  return tryI(0);
};
FX.notBuilt = (what, d) => FX.muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.');
FX.seasonLabel = (L, S) => (HW.seasonLabel ? HW.seasonLabel(L, S) : L === 'nba' && isNum(S) ? (S - 1) + '-' + String(S).slice(2) : String(S));

// ── catalogue helpers ──────────────────────────────────────────────────────

FX.metaOf = metrics => { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; };
FX.groups = metrics => {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === (m.group || 'Other')); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
};
/* First key in `values` (or metric list) matching a candidate: exact strings first, then regexes. */
FX.pick = (obj, cands) => {
  const keys = Array.isArray(obj) ? obj.map(m => m.key) : Object.keys(obj || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (typeof c === 'string' && keys.indexOf(c) >= 0) return c; }
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (c instanceof RegExp) { const k = keys.find(x => c.test(x)); if (k) return k; } }
  return null;
};
FX.headline = (metrics, prefs, n, pctAny) => {
  const out = [];
  const usable = (metrics || []).filter(m => !pctAny || pctAny === true || isNum(pctAny[m.key]));
  (prefs || []).forEach(p => {
    if (out.length >= n) return;
    const re = p instanceof RegExp ? p : new RegExp('^' + p + '$');
    const m = usable.find(x => re.test(x.key) && out.indexOf(x) < 0);
    if (m) out.push(m);
  });
  const seen = new Set(out.map(m => m.group));
  usable.forEach(m => { if (out.length < n && !seen.has(m.group) && out.indexOf(m) < 0) { out.push(m); seen.add(m.group); } });
  usable.forEach(m => { if (out.length < n && out.indexOf(m) < 0) out.push(m); });
  return out.slice(0, n);
};
FX.shortLabel = s => String(s || '').replace(/ per 100( possessions)?/i, '/100').replace(/ per 36( minutes)?/i, '/36').replace(/ per game/i, '/g').replace(/percentage/i, '%').slice(0, 24);
FX.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + encodeURIComponent(key) + '" title="Glossary: ' + esc(key) + '">' + text + '</a>';

/* Percentile colours and pills: blue (low) - grey - red (high), as core. */
FX.pctColor = p => {
  if (HW.pctColor) return HW.pctColor(p);
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100, lo = [59, 130, 246], mid = [107, 114, 128], hi = [239, 68, 68];
  const a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi, u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
FX.pill = p => (HW.pctPill ? HW.pctPill(p) : (isNum(p) ? '<span class="pct-pill" style="background:' + FX.pctColor(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-pill empty">—</span>'));
FX.pctRow = (label, p, valueText, title) => {
  if (HW.pctRow) return HW.pctRow(label, p, valueText, title);
  const known = isNum(p), x = known ? Math.max(0, Math.min(100, p)) : 0;
  return '<div class="pct-row"' + (title ? ' title="' + esc(title) + '"' : '') + '><span class="pct-label">' + esc(label) + '</span><div class="pct-bar">' +
    (known ? '<div class="pct-fill" style="width:' + x + '%;background:' + FX.pctColor(p) + '"></div><span class="pct-dot" style="left:' + x + '%;background:' + FX.pctColor(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-none">not enough data</span>') +
    '</div><span class="pct-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
};
FX.pctPanel = (metrics, vals, pctSrc, opts) => {
  const o = opts || {};
  const groups = FX.groups(metrics);
  if (!groups.length) return FX.muted('No metrics in the catalogue yet.');
  return '<div class="pg-pct-cols hw-pcols">' + groups.map(g => {
    const style = /shot diet|style/i.test(g.name);
    if (style) return '<div class="qk-pgrp"><div class="qk-pgrp-h">' + esc(g.name) + ' <span class="qk-muted">(style: values, not ranked)</span></div><ul class="hw-style">' + g.items.filter(m => isNum((vals || {})[m.key])).map(m => '<li><span>' + esc(m.label) + '</span><b>' + String(FX.fmt(m, vals[m.key])).replace(/<[^>]*>/g, '') + '</b></li>').join('') + '</ul></div>';
    const rows = g.items.map(m => ({ label: m.label, pctl: (pctSrc || {})[m.key], value: String(FX.fmt(m, (vals || {})[m.key])).replace(/<[^>]*>/g, ''),
      tip: (m.desc || '') + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (m.scope === 'pbp' ? ' · play-by-play' : '') })).filter(r => isNum(r.pctl));
    return rows.length ? '<div class="qk-pgrp"><div class="qk-pgrp-h">' + esc(g.name) + '</div>' + QK.pctlBars(rows) + '</div>' : '';
  }).join('') + '</div>' + (o.note ? '<div class="pg-note">' + o.note + '</div>' : '');
};
FX.tile = (label, value, sub, cls) => (HW.statTile ? HW.statTile(label, value, sub, cls) :
  '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>');
FX.toggle = (id, opts, cur) => '<span class="pg-toggle qk-seg" id="' + esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + esc(o[0]) + '" aria-pressed="' + (String(o[0]) === String(cur)) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>').join('') + '</span>';
FX.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); });
    fn(b.dataset.v);
  }));
};
FX.card = (title, sub, body, id, ctl) => '<section class="qk-card hw-lcard"' + (id ? ' id="' + esc(id) + '"' : '') + '>' + (title ? '<div class="qk-card-head"><div style="min-width:0"><div class="qk-card-title">' + esc(title) + '</div>' + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (ctl ? '<div class="hw-lctl">' + ctl + '</div>' : '') + '</div>' : '') + '<div class="qk-card-body flush">' + (body || '') + '</div></section>';
FX.table = (cols, rows, opts) => HW.tableHTML(cols, rows, opts);
FX.pairColours = (ca, cb) => (!ca || !cb || String(ca).toLowerCase() !== String(cb).toLowerCase() ? [ca || FX.CA, cb || FX.CB] : [ca, '#e6edf3']);

// ── charts ─────────────────────────────────────────────────────────────────

/* Charts draw with the kit's ECharts layer (QKC) through HW.charts; the Plotly helpers are gone. */
FX.radar = (el, axes, rows) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  axes = axes.filter(a => rows.some(r => r && r.pct && isNum(r.pct[a.key])));
  const usable = rows.filter(r => r && r.pct && axes.some(a => isNum(r.pct[a.key])));
  if (!usable.length || axes.length < 3) { node.innerHTML = FX.muted('No percentiles to draw yet.'); return; }
  HW.charts.radar(node, usable.map((r, i) => ({ name: r.name, colour: r.colour || (i ? FX.CB : FX.CA), values: axes.map(a => (isNum(r.pct[a.key]) ? r.pct[a.key] : null)) })), { labels: axes.map(a => a.label), height: node.clientHeight || 400 });
};
/* A net-rating path with its ±1 standard error band, for QKC.line: rows [{x: date, y, se}] -> a series. */
FX.bandSeries = (rows, colour, name) => {
  const ok = rows.filter(r => isNum(r.y));
  return { name: name, color: colour, data: ok.map(r => [Date.parse(r.x), r.y]),
    band: ok.some(r => isNum(r.se)) ? { lo: ok.map(r => r.y - (r.se || 0)), hi: ok.map(r => r.y + (r.se || 0)), x: ok.map(r => Date.parse(r.x)) } : undefined };
};
FX.dateFmt = v => FX.fmtDate(new Date(v).toISOString().slice(0, 10), { year: false });
/* Net rating over the season (±1 standard error shaded) for one or more teams: list [{name, colour, rows}]. */
FX.pathChart = (el, list, opts) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const o = opts || {};
  QKC.line(node, { xType: 'time', series: list.map(x => FX.bandSeries(x.rows, x.colour, x.name)), xName: 'Date', yName: o.yName || 'Net rating (points per 100 possessions)',
    xFmt: FX.dateFmt, xLabel: FX.dateFmt, yFmt: v => FX.signed(v, 1), ref: { y: 0 }, label: o.label || 'Net rating through the season' });
};

// ── the court and shot charts (feet, rim at 0,0; PAYLOADS.md front-end contract) ─

FX.COURT = {
  nba: { arc: 23.75, corner: 22, lane: 8, ft: 19, rim: 0.75, ra: 4, base: -5.25 },
  wnba: { arc: 22.15, corner: 22, lane: 8, ft: 19, rim: 0.75, ra: 4, base: -5.25 }
};
FX.YMAX = 35;
FX.arcY = L => { const c = FX.COURT[L] || FX.COURT.nba; return Math.sqrt(Math.max(0, c.arc * c.arc - c.corner * c.corner)); };
const arcPts = (r, a0, a1, n, cx, cy) => { const out = []; for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; out.push([(cx || 0) + r * Math.cos(a), (cy || 0) + r * Math.sin(a)]); } return out; };
/* Zone polygons for the shot-profile map: rim, paint, mid, corner3 (left and right), ab3. */
FX.zonePolys = L => {
  const c = FX.COURT[L] || FX.COURT.nba, yb = FX.arcY(L), b = c.base, ftY = b + c.ft;
  const a0 = Math.atan2(yb, c.corner), a1 = Math.PI - a0;
  const arc = arcPts(c.arc, a0, a1, 60);              // right to left over the top
  return {
    ab3: { polys: [[[-25, yb], [-c.corner, yb]].concat(arc.slice().reverse()).concat([[c.corner, yb], [25, yb], [25, FX.YMAX], [-25, FX.YMAX]])], at: [0, 28.5] },
    corner3: { polys: [[[-25, b], [-c.corner, b], [-c.corner, yb], [-25, yb]], [[25, b], [c.corner, b], [c.corner, yb], [25, yb]]], at: [-23.5, 1.5], at2: [23.5, 1.5] },
    mid: { polys: [[[c.corner, b], [c.corner, yb]].concat(arc).concat([[-c.corner, b], [-c.lane, b], [-c.lane, ftY], [c.lane, ftY], [c.lane, b]])], at: [-14.5, 10] },
    paint: { polys: [[[-c.lane, b], [-c.lane, ftY], [c.lane, ftY], [c.lane, b]]], at: [0, 9.2] },
    rim: { polys: [arcPts(c.ra, 0, 2 * Math.PI, 40)], at: [0, 0.6] }
  };
};
FX.ZONE_LABEL = { rim: 'At the rim (<4 ft)', paint: 'Paint (non-rim)', mid: 'Mid-range', corner3: 'Corner 3', ab3: 'Above-the-break 3', heave: 'Heave (>40 ft)' };
FX.ZONE_ORDER = ['rim', 'paint', 'mid', 'corner3', 'ab3', 'heave'];
FX.divRGB = (v, max) => {
  if (!isNum(v)) return 'rgba(110,118,129,0.35)';
  const t = Math.max(-1, Math.min(1, v / (max || 0.3)));
  const lo = [37, 99, 235], mid = [107, 114, 128], hi = [220, 38, 38];
  const a = mid, b = t < 0 ? lo : hi, u = Math.abs(t);
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
/* Zone map: ZONES {zone: {freq, fg, pps, league_pps}}, each zone filled by points per shot against the league
 * (cold to hot) and labelled with its share of shots, FG% and the difference. */
FX.zoneMap = (el, L, zones, opts) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const Z = zones || {};
  if (!Object.keys(Z).length) { node.innerHTML = FX.muted('No shot profile.'); return; }
  const P = FX.zonePolys(L), o = opts || {};
  const keys = Object.keys(P);
  const diffOf = k => { const z = Z[k] || {}; return isNum(z.pps) && isNum(z.league_pps) ? z.pps - z.league_pps : null; };
  const col = d => QK.pctHex(isNum(d) ? Math.max(0, Math.min(100, 50 + 50 * d / 0.25)) : 50);
  const shapes = [];
  keys.forEach(k => P[k].polys.forEach(poly => shapes.push({ k: k, poly: poly })));
  const labs = [];
  keys.forEach(k => { const z = Z[k]; if (!z || (z.freq === undefined && z.pps === undefined)) return; labs.push({ k: k, at: P[k].at }); if (P[k].at2) labs.push({ k: k, at: P[k].at2 }); });
  HW.charts.courtMount(node, T => ({
    tooltip: QKC.tooltip(T, { formatter: p => { const k = p.data.k, z = Z[k] || {}, d = diffOf(k);
      return '<div style="font-weight:600">' + esc(FX.ZONE_LABEL[k] || k) + '</div>' + QKC.tipRow(col(d), 'Share of shots', FX.fmtV(z.freq, 'pct')) + QKC.tipRow(col(d), 'FG%', FX.fmtV(z.fg, 'pct')) +
        QKC.tipRow(col(d), 'Points per shot', FX.num(z.pps, 2) + (isNum(z.league_pps) ? ' (league ' + FX.num(z.league_pps, 2) + ')' : '')); } }),
    series: [{ type: 'custom', data: shapes.map(x => ({ value: x.poly[0], k: x.k })), encode: { x: 0, y: 1 }, z: 1,
      renderItem: (params, api) => { const x = shapes[params.dataIndex]; const d = diffOf(x.k);
        return { type: 'polygon', shape: { points: x.poly.map(q => api.coord(q)) }, style: { fill: isNum(d) ? QKC.hexA(col(d), 0.38) : QKC.hexA(T.ink3, 0.14), stroke: T.s1, lineWidth: 1.5 } }; } },
    { type: 'scatter', z: 3, symbolSize: 1, itemStyle: { color: 'transparent' }, data: labs.map(x => { const z = Z[x.k] || {}, d = diffOf(x.k);
      return { value: x.at, k: x.k, label: { show: true, color: T.ink1, fontFamily: T.fontNum, fontSize: o.small ? 9.5 : 10.5, lineHeight: o.small ? 12 : 13, textBorderColor: T.s1, textBorderWidth: 2,
        formatter: '{b|' + FX.fmtV(z.freq, 'pct') + '}' + (isNum(z.fg) ? '\n' + FX.fmtV(z.fg, 'pct') + ' FG' : '') + (d !== null ? '\n' + FX.signed(d, 2) + ' pps' : ''), rich: { b: { fontWeight: 700, color: T.ink1, fontFamily: T.fontNum } } } }; }) }]
  }), o.title || 'Shot profile by zone');
  HW.charts.chartKey(node, (o.title ? '<b>' + esc(o.title) + '</b> · ' : '') + 'Each zone: share of shots, FG% and points per shot against the league (blue below, red above).');
};
/* League-relative cells: cells [{x, y, n, fg, pps, pps_diff|lg_pps}] as hexagons sized by volume. */
FX.cellChart = (el, L, cells, opts) => HW.charts.cellChart(el, L, FX.rowsOf(cells), opts);
/* Raw made/missed dots: shots [{x, y, made}] */
FX.dotChart = (el, L, shots, opts) => HW.charts.shotChart(el, shots, Object.assign({ league: L, mode: 'dots' }, opts || {}));
/* Zone table HTML from ZONES. */
FX.zoneTable = zones => {
  const Z = zones || {};
  const keys = FX.ZONE_ORDER.filter(k => Z[k]).concat(Object.keys(Z).filter(k => FX.ZONE_ORDER.indexOf(k) < 0));
  if (!keys.length) return FX.muted('No zone table.');
  return HW.tableHTML([{ label: 'Zone' }, { label: 'Share', align: 'right' }, { label: 'FG%', align: 'right' }, { label: 'Pts/shot', align: 'right' }, { label: 'League', align: 'right' }, { label: 'v league', align: 'right' }],
    keys.map(k => { const z = Z[k] || {}; const d = isNum(z.pps) && isNum(z.league_pps) ? z.pps - z.league_pps : null;
      return [{ v: k, html: esc(FX.ZONE_LABEL[k] || k) }, { v: z.freq, html: FX.fmtV(z.freq, 'pct') }, { v: z.fg, html: FX.fmtV(z.fg, 'pct') }, { v: z.pps, html: FX.num(z.pps, 2) }, { v: z.league_pps, html: FX.num(z.league_pps, 2) },
        { v: d, html: d === null ? '—' : '<span class="' + (d > 0 ? 'pg-up' : d < 0 ? 'pg-down' : '') + '">' + FX.signed(d, 2) + '</span>' }]; }), { compact: true });
};
/* Shot-type table from {type: {n, fg, pps}}. */
FX.typeTable = types => {
  const T = types || {};
  const keys = Object.keys(T).sort((a, b) => ((T[b] || {}).n || 0) - ((T[a] || {}).n || 0));
  if (!keys.length) return FX.muted('No shot types.');
  const tot = keys.reduce((s, k) => s + ((T[k] || {}).n || 0), 0) || 1;
  return HW.tableHTML([{ label: 'Type' }, { label: 'Shots', align: 'right' }, { label: 'Share', align: 'right' }, { label: 'FG%', align: 'right' }, { label: 'Pts/shot', align: 'right' }],
    keys.map(k => { const t = T[k] || {}; return [{ v: k, html: esc(k.charAt(0).toUpperCase() + k.slice(1)) }, t.n, { v: (t.n || 0) / tot, html: FX.fmtV((t.n || 0) / tot, 'pct') }, { v: t.fg, html: FX.fmtV(t.fg, 'pct') }, { v: t.pps, html: FX.num(t.pps, 2) }]; }), { compact: true });
};

/* A generic key-value grid for an object of numbers (projection rows and the like). */
FX.kvTiles = (obj, labels, skip) => {
  const o = obj || {};
  const ks = Object.keys(o).filter(k => (skip || []).indexOf(k) < 0 && (isNum(o[k]) || typeof o[k] === 'string'));
  if (!ks.length) return '';
  return '<div class="hf-kv">' + ks.map(k => '<div class="hf-kv-i"><span>' + esc((labels || {})[k] || k.replace(/_/g, ' ')) + '</span><strong>' + (isNum(o[k]) ? (Math.abs(o[k]) < 1 && !Number.isInteger(o[k]) ? FX.num(o[k], 3) : FX.num(o[k], Number.isInteger(Number(o[k])) ? 0 : 1)) : esc(o[k])) + '</strong></div>').join('') + '</div>';
};

FX.AWARDS = { mvp: 'MVP', roy: 'Rookie of the Year', dpoy: 'Defensive Player', sixth: 'Sixth ' + 'Player', '6moy': 'Sixth Player', mip: 'Most Improved', clutch: 'Clutch Player' };
FX.awardName = (k, L) => (k === 'sixth' || k === '6moy' ? (L === 'wnba' ? 'Sixth Player' : 'Sixth Man') : FX.AWARDS[k] || String(k).toUpperCase());
/* award p from {pid: p} or {pid: {p, ...}} */
FX.pOf = v => (isNum(v) ? Number(v) : v && isNum(v.p) ? Number(v.p) : null);

})(window.HW);
