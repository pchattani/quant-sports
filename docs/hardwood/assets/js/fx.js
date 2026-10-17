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
  return '<div class="pg-pct-cols">' + groups.map(g => '<div class="pct-group"><div class="pct-group-head">' + esc(g.name) + '</div>' +
    g.items.map(m => FX.pctRow(m.label + (m.lower ? ' ↓' : ''), (pctSrc || {})[m.key], FX.fmt(m, (vals || {})[m.key]),
      (m.desc || '') + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (m.scope === 'pbp' ? ' · play-by-play' : ''))).join('') + '</div>').join('') + '</div>' +
    (o.note ? '<div class="pg-note">' + o.note + '</div>' : '');
};
FX.tile = (label, value, sub, cls) => (HW.statTile ? HW.statTile(label, value, sub, cls) :
  '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>');
FX.toggle = (id, opts, cur) => '<span class="pg-toggle" id="' + esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>').join('') + '</span>';
FX.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
FX.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' + (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl || '') + '</div>' : '') + (body || '') + '</div>';
FX.table = (cols, rows, opts) => HW.tableHTML(cols, rows, opts);
FX.pairColours = (ca, cb) => (!ca || !cb || String(ca).toLowerCase() !== String(cb).toLowerCase() ? [ca || FX.CA, cb || FX.CB] : [ca, '#e6edf3']);

// ── charts ─────────────────────────────────────────────────────────────────

FX.layout = extra => (HW.layout ? HW.layout(extra) : extra);
FX.plot = (el, traces, lay, conf) => HW.plot(el, traces, lay, conf);

FX.radar = (el, axes, rows) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  axes = axes.filter(a => rows.some(r => r && r.pct && isNum(r.pct[a.key])));
  const usable = rows.filter(r => r && r.pct && axes.some(a => isNum(r.pct[a.key])));
  if (!usable.length || axes.length < 3) { node.innerHTML = FX.muted('No percentiles to draw yet.'); return; }
  const narrow = (node.clientWidth || 600) < 520;
  const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
  const ax = axes.map(a => Object.assign({}, a, { label: wrap(a.label) }));
  FX.plot(node, usable.map((r, i) => ({
    type: 'scatterpolar', fill: 'toself', name: r.name,
    r: ax.map(a => (isNum(r.pct[a.key]) ? r.pct[a.key] : 0)).concat([isNum(r.pct[ax[0].key]) ? r.pct[ax[0].key] : 0]),
    theta: ax.map(a => a.label).concat([ax[0].label]),
    line: { color: r.colour || (i ? FX.CB : FX.CA), width: 2 }, fillcolor: FX.alpha(r.colour || (i ? FX.CB : FX.CA), 0.18),
    hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + esc(r.name) + '</extra>'
  })), FX.layout({
    showlegend: usable.length > 1, legend: { orientation: 'h', y: -0.1, font: { color: FX.C.text2 } },
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
    margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 64, r: 64, t: 20, b: 40 }
  }));
};

/* Line with a ±se band: rows [{x, y, se}] */
FX.band = (rows, colour, name, opts) => {
  const o = opts || {};
  const x = rows.map(r => r.x), out = [];
  if (o.band !== false && rows.some(r => isNum(r.se))) {
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.y + (r.se || 0)), line: { width: 0 }, hoverinfo: 'skip', showlegend: false });
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.y - (r.se || 0)), line: { width: 0 }, fill: 'tonexty', fillcolor: FX.alpha(colour, 0.16), hoverinfo: 'skip', showlegend: false });
  }
  out.push({ type: 'scatter', mode: o.mode || 'lines', name: name, x: x, y: rows.map(r => r.y), text: rows.map(r => r.text || ''), customdata: rows.map(r => (isNum(r.se) ? r.se : 0)),
    line: { color: colour, width: o.width || 2, dash: o.dash || 'solid' }, hovertemplate: o.hover || ('%{text} ' + esc(name) + ': %{y:+.2f} ± %{customdata:.2f}<extra></extra>') });
  return out;
};

// ── the court and shot charts (feet, rim at 0,0; PAYLOADS.md front-end contract) ─

FX.COURT = {
  nba: { arc: 23.75, corner: 22, lane: 8, ft: 19, rim: 0.75, ra: 4, base: -5.25 },
  wnba: { arc: 22.15, corner: 22, lane: 8, ft: 19, rim: 0.75, ra: 4, base: -5.25 }
};
FX.YMAX = 35;
FX.arcY = L => { const c = FX.COURT[L] || FX.COURT.nba; return Math.sqrt(Math.max(0, c.arc * c.arc - c.corner * c.corner)); };
const arcPts = (r, a0, a1, n, cx, cy) => { const out = []; for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; out.push([(cx || 0) + r * Math.cos(a), (cy || 0) + r * Math.sin(a)]); } return out; };
const pathOf = (pts, close) => pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' ') + (close ? ' Z' : '');
/* Court lines as Plotly shapes; the charts module's version when it has one. */
FX.courtShapes = L => {
  if (HW.charts && typeof HW.charts.court === 'function') {
    try { const s = HW.charts.court(L); if (Array.isArray(s)) return s; if (s && Array.isArray(s.shapes)) return s.shapes; } catch (e) { /* local */ }
  }
  const c = FX.COURT[L] || FX.COURT.nba, yb = FX.arcY(L), b = c.base, ln = { color: '#3d444d', width: 1.2 };
  const a0 = Math.atan2(yb, c.corner), a1 = Math.PI - a0;
  const ftY = b + c.ft;
  return [
    { type: 'path', path: pathOf([[-25, b], [25, b], [25, FX.YMAX], [-25, FX.YMAX]], true), line: ln, layer: 'below' },
    { type: 'path', path: pathOf([[-c.lane, b], [-c.lane, ftY], [c.lane, ftY], [c.lane, b]], false), line: ln, layer: 'below' },
    { type: 'path', path: pathOf(arcPts(6, 0, Math.PI, 30, 0, ftY), false), line: ln, layer: 'below' },
    { type: 'path', path: pathOf(arcPts(c.ra, 0, Math.PI, 24, 0, 0), false), line: ln, layer: 'below' },
    { type: 'circle', x0: -c.rim, x1: c.rim, y0: -c.rim, y1: c.rim, line: { color: '#f97316', width: 1.5 }, layer: 'below' },
    { type: 'line', x0: -3, x1: 3, y0: -1.25, y1: -1.25, line: { color: '#6e7681', width: 2 }, layer: 'below' },
    { type: 'path', path: pathOf([[-c.corner, b], [-c.corner, yb]].concat(arcPts(c.arc, a1, a0, 50)).concat([[c.corner, yb], [c.corner, b]]), false), line: ln, layer: 'below' }
  ];
};
FX.courtAxes = () => ({
  xaxis: { range: [-25.5, 25.5], visible: false, fixedrange: true },
  yaxis: { range: [-6, FX.YMAX + 0.5], visible: false, fixedrange: true, scaleanchor: 'x', scaleratio: 1 }
});
/* Zone polygons for the shot-profile map: rim, paint, mid, corner3 (left and right), ab3. */
FX.zonePaths = L => {
  const c = FX.COURT[L] || FX.COURT.nba, yb = FX.arcY(L), b = c.base, ftY = b + c.ft;
  const a0 = Math.atan2(yb, c.corner), a1 = Math.PI - a0;
  const arc = arcPts(c.arc, a0, a1, 60);              // right to left over the top
  // the restricted circle, traversed the other way to cut a hole into the paint
  const rimHole = arcPts(c.ra, -Math.PI / 2, 1.5 * Math.PI, 40);
  return {
    paint: { path: pathOf([[0, b], [-c.lane, b], [-c.lane, ftY], [c.lane, ftY], [c.lane, b], [0, b], [0, -c.ra]].concat(rimHole).concat([[0, b]]), true), at: [0, 9.2] },
    rim: { path: pathOf(arcPts(c.ra, 0, 2 * Math.PI, 40), true), at: [0, 0.6] },
    mid: { path: pathOf([[c.corner, b], [c.corner, yb]].concat(arc).concat([[-c.corner, b], [-c.lane, b], [-c.lane, ftY], [c.lane, ftY], [c.lane, b]]), true), at: [-14.5, 10] },
    corner3: { path: pathOf([[-25, b], [-c.corner, b], [-c.corner, yb], [-25, yb]], true) + ' ' + pathOf([[25, b], [c.corner, b], [c.corner, yb], [25, yb]], true), at: [-23.5, 0.5] },
    ab3: { path: pathOf([[-25, yb], [-c.corner, yb]].concat(arc.slice().reverse()).concat([[c.corner, yb], [25, yb], [25, FX.YMAX], [-25, FX.YMAX]]), true), at: [0, 28.5] }
  };
};
FX.ZONE_LABEL = { rim: 'At the rim (<4 ft)', paint: 'Paint (non-rim)', mid: 'Mid-range', corner3: 'Corner 3', ab3: 'Above-the-break 3', heave: 'Heave (>40 ft)' };
FX.ZONE_ORDER = ['rim', 'paint', 'mid', 'corner3', 'ab3', 'heave'];
const DIV_SCALE = [[0, '#2563eb'], [0.25, '#60a5fa'], [0.5, '#6b7280'], [0.75, '#f87171'], [1, '#dc2626']];
FX.divRGB = (v, max) => {
  if (!isNum(v)) return 'rgba(110,118,129,0.35)';
  const t = Math.max(-1, Math.min(1, v / (max || 0.3)));
  const lo = [37, 99, 235], mid = [107, 114, 128], hi = [220, 38, 38];
  const a = mid, b = t < 0 ? lo : hi, u = Math.abs(t);
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
/* Zone map: ZONES {zone: {freq, fg, pps, league_pps}} coloured by pps against the league. */
FX.zoneMap = (el, L, zones, opts) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const Z = zones || {};
  if (!Object.keys(Z).length) { node.innerHTML = FX.muted('No shot profile.'); return; }
  const P = FX.zonePaths(L), o = opts || {};
  const shapes = [];
  const ann = [];
  Object.keys(P).forEach(k => {
    const z = Z[k] || {};
    const diff = isNum(z.pps) && isNum(z.league_pps) ? z.pps - z.league_pps : null;
    const fill = diff === null ? 'rgba(110,118,129,0.25)' : FX.divRGB(diff, 0.25).replace('rgb', 'rgba').replace(')', ',0.62)');
    shapes.push({ type: 'path', path: P[k].path, fillcolor: fill, line: { color: '#0d1117', width: 1.5 }, layer: 'below' });
    if (z.freq !== undefined || z.pps !== undefined) {
      ann.push({ x: P[k].at[0], y: P[k].at[1], showarrow: false, font: { size: o.small ? 9 : 10, color: '#e6edf3' }, align: 'center',
        text: '<b>' + FX.fmtV(z.freq, 'pct') + '</b><br>' + (isNum(z.fg) ? FX.fmtV(z.fg, 'pct') + ' FG' : '') + (diff !== null ? '<br>' + FX.signed(diff, 2) + ' pps' : '') });
      if (k === 'corner3') ann.push(Object.assign({}, ann[ann.length - 1], { x: -P[k].at[0] }));
    }
  });
  // invisible hover points
  const hx = [], hy = [], ht = [];
  Object.keys(P).forEach(k => { const z = Z[k]; if (!z) return; hx.push(P[k].at[0]); hy.push(P[k].at[1]);
    ht.push('<b>' + esc(FX.ZONE_LABEL[k] || k) + '</b><br>share ' + FX.fmtV(z.freq, 'pct') + ' · FG ' + FX.fmtV(z.fg, 'pct') + '<br>' + FX.num(z.pps, 2) + ' pts/shot v league ' + FX.num(z.league_pps, 2)); });
  FX.plot(node, [{ type: 'scatter', mode: 'markers', x: hx, y: hy, text: ht, hovertemplate: '%{text}<extra></extra>', marker: { size: 26, color: 'rgba(0,0,0,0)' } }],
    FX.layout(Object.assign({ margin: { l: 4, r: 4, t: o.title ? 24 : 4, b: 4 }, shapes: shapes.concat(FX.courtShapes(L)), annotations: ann,
      title: o.title ? { text: o.title, font: { size: 12, color: FX.C.text2 }, y: 0.99 } : undefined }, FX.courtAxes())));
};
/* Hex/square cell chart: cells [{x, y, n, fg, pps, pps_diff|lg_pps}] sized by volume, coloured by pps v league. */
FX.cellChart = (el, L, cells, opts) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  const o = opts || {};
  const rows = FX.rowsOf(cells).filter(c => isNum(c.x) && isNum(c.y) && c.y <= FX.YMAX);
  if (!rows.length) { node.innerHTML = FX.muted('No located shots.'); return; }
  const diffOf = c => (isNum(c.pps_diff) ? c.pps_diff : isNum(c.pps) && isNum(c.lg_pps) ? c.pps - c.lg_pps : isNum(c.pps) && isNum(c.league_pps) ? c.pps - c.league_pps : null);
  const maxN = Math.max.apply(null, rows.map(c => c.n || 1));
  const narrow = (node.clientWidth || 600) < 420;
  const size = c => Math.max(5, (narrow ? 15 : 24) * Math.sqrt((c.n || 1) / maxN));
  const diffs = rows.map(diffOf);
  FX.plot(node, [{
    type: 'scatter', mode: 'markers', x: rows.map(c => c.x), y: rows.map(c => c.y),
    text: rows.map((c, i) => (c.n || 0) + ' shots · FG ' + FX.fmtV(c.fg, 'pct') + '<br>' + FX.num(c.pps, 2) + ' pts/shot' + (isNum(diffs[i]) ? ' (' + FX.signed(diffs[i], 2) + ' v league)' : '')),
    hovertemplate: '%{text}<extra></extra>',
    marker: { symbol: o.square ? 'square' : 'hexagon', size: rows.map(size), color: diffs.map(d => (isNum(d) ? d : 0)), cmin: -0.4, cmax: 0.4, colorscale: DIV_SCALE,
      line: { width: 0 }, colorbar: o.colorbar === false ? undefined : { title: { text: 'pts/shot<br>v league', side: 'right', font: { size: 10 } }, thickness: 8, len: 0.6, tickfont: { size: 9, color: FX.C.text2 } } }
  }], FX.layout(Object.assign({ margin: { l: 4, r: o.colorbar === false ? 4 : 10, t: o.title ? 24 : 4, b: 4 }, shapes: FX.courtShapes(L),
    title: o.title ? { text: o.title, font: { size: 12, color: FX.C.text2 }, y: 0.99 } : undefined }, FX.courtAxes())));
};
/* Raw made/missed dots: shots [{x, y, made}] */
FX.dotChart = (el, L, shots, opts) => {
  const o = opts || {};
  const rows = (shots || []).filter(s => isNum(s.x) && isNum(s.y) && s.y <= FX.YMAX);
  if (!rows.length) { (typeof el === 'string' ? document.getElementById(el) : el).innerHTML = FX.muted('No located shots.'); return; }
  const tr = (made, colour, sym) => ({ type: 'scatter', mode: 'markers', name: made ? 'Made' : 'Missed', x: rows.filter(s => !!s.made === made).map(s => s.x), y: rows.filter(s => !!s.made === made).map(s => s.y),
    marker: { size: 5, color: colour, symbol: sym, opacity: 0.75, line: { width: made ? 0 : 1, color: colour } }, hoverinfo: 'skip' });
  FX.plot(el, [tr(false, '#f85149', 'x-thin-open'), tr(true, '#3fb950', 'circle')], FX.layout(Object.assign({ margin: { l: 4, r: 4, t: o.title ? 24 : 4, b: 4 }, shapes: FX.courtShapes(L), showlegend: false,
    title: o.title ? { text: o.title, font: { size: 12, color: FX.C.text2 } } : undefined }, FX.courtAxes())));
};
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
