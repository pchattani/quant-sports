/* The Quant Ace — shared helpers for the catalogue pages (players, elo, h2h, lab, compare,
 * calibration, docs): TA.fx. Adapted from the Hardwood's HW.fx (the court and shot helpers dropped).
 *
 * Read lazily at render time by each module (const FX = () => TA.fx), so script order does
 * not matter. Everything degrades to a local implementation when the core helper is missing.
 *
 * Data contract: oddsmarkets/tennis/PAYLOADS.md. */
(function (TA) {
'use strict';

const FX = TA.fx = TA.fx || {};

// ── basics ─────────────────────────────────────────────────────────────────

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const esc = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
FX.isNum = isNum;
FX.esc = TA.esc || esc;
FX.alive = el => !!el && el.isConnected;
FX.has = v => v !== undefined && v !== null && !(typeof v === 'number' && !isFinite(v));
FX.ok = d => !!d && d.ok !== false;
FX.muted = t => (TA.muted ? TA.muted(t) : '<div class="muted">' + t + '</div>');
FX.num = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
FX.signed = (v, d) => {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
};
FX.pct = (p, d) => (TA.pct ? TA.pct(p, d) : (isNum(p) ? (p * 100).toFixed(d === undefined ? 1 : d) + '%' : '—'));
FX.ordinal = n => (TA.ordinal ? TA.ordinal(n) : String(n));
FX.fmtDate = (s, o) => (TA.fmtDate ? TA.fmtDate(s, o) : (s ? String(s).slice(0, 10) : '—'));
FX.fmtStamp = s => (TA.fmtStamp ? TA.fmtStamp(s) : (s ? String(s).replace('T', ' ').replace(/:\d\dZ?$/, '') : ''));

/* Format a catalogue value by its declared fmt: int|1|2|3|pct|prob|signed (PAYLOADS.md). */
FX.fmtV = (v, fmt) => {
  if (TA.fmtVal && fmt) return TA.fmtVal(v, fmt);
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (fmt) {
    case 'int': return String(Math.round(x));
    case '1': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'prob': return FX.pct(x);
    case 'signed': return FX.signed(x, 2);
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2);
  }
};
FX.fmt = (m, v) => FX.fmtV(v, (m || {}).fmt);
FX.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
FX.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
FX.sd = a => { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = FX.mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); };
FX.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return TA.alpha ? TA.alpha(hex || 'var(--c-1)', a) : 'rgba(217,242,79,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
FX.C = TA.C;
FX.PALETTE = TA.PALETTE;
FX.CA = TA.C.p1; FX.CB = TA.C.p2;     // player A / player B

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
    if (inner.length && inner.every(k => /^\d+$/.test(k)) && keys.every(k => typeof x[k][inner[0]] !== 'object')) {
      return inner.map(i => { const o = {}; keys.forEach(c => { o[c] = x[c][i]; }); return o; });
    }
    return keys.map(k => Object.assign({ _key: k }, x[k]));
  }
  return [];
};

// ── tour, year, names ──────────────────────────────────────────────────────

/* The tour of a page: params.tour, else the state's. FX.L is the Hardwood name, kept as an alias. */
FX.T = (params, state) => {
  const t = (params && (params.tour || params.T)) || (state && state.tour) || (TA.state && TA.state.tour) || 'atp';
  return String(t).toLowerCase() === 'wta' ? 'wta' : 'atp';
};
FX.L = FX.T;
FX.Y = (params, state, T) => {
  const raw = params && (params.year || (params.query || {}).y);
  if (isNum(raw)) return Number(raw);
  const st = state || TA.state || {};
  if (isNum(st.year) && (!st.tour || st.tour === T)) return Number(st.year);
  return TA.currentYear(T);
};
FX.S = FX.Y;
FX.ready = () => Promise.resolve(TA.index() || {});
FX.playerName = (T, pid) => TA.playerName(T, pid);
FX.playerShort = (T, pid) => TA.playerShort(T, pid);
FX.surname = n => { const p = String(n || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : p[0]; };
FX.YEAR = null;
FX.playerHref = (T, pid, Y) => TA.playerHref(T, pid, Y || FX.YEAR);
FX.href = (T, sub, Y) => TA.href(T, sub, Y || FX.YEAR);
/* Player link; name optional. (T, pid, name, _unused, Y) mirrors the Hardwood signature. */
FX.playerLink = (T, pid, name, _team, Y) => {
  if (!pid) return '<span class="muted-inline">—</span>';
  return '<a class="ply-link" href="' + FX.playerHref(T, pid, Y) + '">' + esc(name || TA.playerName(T, pid)) + '</a>';
};
FX.matchLink = (T, mid, label) => TA.matchLink(T, mid, label);
FX.eventLink = (T, eid, label) => TA.eventLink(T, eid, label);
FX.ageOf = dob => {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};
/* data/<T>/<Y>/<file> and data/<T>/<file>. */
FX.path = (T, Y, f) => T + '/' + Y + '/' + f;
FX.tpath = (T, f) => T + '/' + f;
/* First payload that loads and is ok, from a list of paths. */
FX.first = paths => {
  const tryI = i => (i >= paths.length ? Promise.resolve(null) : TA.load(paths[i]).then(d => (d && d.ok !== false ? d : (i + 1 < paths.length ? tryI(i + 1) : d))));
  return tryI(0);
};
FX.notBuilt = (what, d) => FX.muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.');

// ── catalogue helpers ──────────────────────────────────────────────────────

FX.metaOf = metrics => { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; };
FX.groups = metrics => {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === (m.group || 'Other')); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
};
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
FX.shortLabel = s => String(s || '').replace(/percentage/i, '%').slice(0, 24);
FX.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + encodeURIComponent(key) + '" title="Glossary: ' + esc(key) + '">' + text + '</a>';
/* Scope note for a METRIC: real WTA stats, charted matches, or inferred from scores. */
FX.scopeTag = m => {
  const s = (m || {}).scope;
  if (s === 'wta_stats') return '<span class="scope-tag real" title="Measured point by point (WTA match statistics)">real</span>';
  if (s === 'charted') return '<span class="scope-tag charted" title="From charted matches only (Match Charting Project, CC BY-NC-SA 4.0)">charted</span>';
  return '';
};

FX.pctColor = p => (TA.pctColor ? TA.pctColor(p) : '#30363d');
FX.pill = p => TA.pctPill(p);
FX.pctRow = (label, p, valueText, title) => TA.pctRow(label, p, valueText, title);
/* A percentile panel: metric groups of slider rows. vals {key: v}, pctSrc {key: 0-100}. opts {note}. */
FX.pctPanel = (metrics, vals, pctSrc, opts) => {
  const o = opts || {};
  const groups = FX.groups(metrics);
  if (!groups.length) return FX.muted('No metrics in the catalogue yet.');
  return '<div class="pg-pct-cols">' + groups.map(g => '<div class="pct-group"><div class="pct-group-head">' + esc(g.name) + '</div>' +
    g.items.map(m => FX.pctRow(m.label + (m.lower ? ' ↓' : ''), (pctSrc || {})[m.key], FX.fmt(m, (vals || {})[m.key]),
      (m.desc || '') + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') +
      (m.scope === 'wta_stats' ? ' · real WTA match statistics' : m.scope === 'charted' ? ' · charted matches only' : ''))).join('') + '</div>').join('') + '</div>' +
    (o.note ? '<div class="pg-note">' + o.note + '</div>' : '');
};
FX.tile = (label, value, sub, cls) => TA.statTile(label, value, sub, cls);
/* A pill toggle: opts [[value, label]...]; FX.wireToggle(root, id, fn) wires it. */
FX.toggle = (id, opts, cur) => '<span class="pg-toggle" id="' + esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + '>' + esc(o[1]) + '</button>').join('') + '</span>';
FX.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
/* Surface toggle: All · Hard · Clay · Grass. */
FX.surfaceToggle = (id, cur, withAll) => FX.toggle(id, (withAll === false ? [] : [['all', 'All']]).concat([['hard', 'Hard'], ['clay', 'Clay'], ['grass', 'Grass']]), cur || 'all');
FX.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' + (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl || '') + '</div>' : '') + (body || '') + '</div>';
FX.table = (cols, rows, opts) => TA.tableHTML(cols, rows, opts);
FX.pairColours = (ca, cb) => (!ca || !cb || String(ca).toLowerCase() !== String(cb).toLowerCase() ? [ca || FX.CA, cb || FX.CB] : [ca, 'var(--ink-1)']);

// ── charts ─────────────────────────────────────────────────────────────────

FX.layout = extra => TA.layout(extra);
FX.plot = (el, traces, lay, conf) => TA.plot(el, traces, lay, conf);
/* Percentile radar: axes [{key, label}], rows [{name, pct: {key: 0-100}, colour}]. */
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
/* Line with a ±se band: rows [{x, y, se, text}] -> traces. */
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
/* A generic key-value grid for an object of numbers. */
FX.kvTiles = (obj, labels, skip) => {
  const o = obj || {};
  const ks = Object.keys(o).filter(k => (skip || []).indexOf(k) < 0 && (isNum(o[k]) || typeof o[k] === 'string'));
  if (!ks.length) return '';
  return '<div class="hf-kv">' + ks.map(k => '<div class="hf-kv-i"><span>' + esc((labels || {})[k] || k.replace(/_/g, ' ')) + '</span><strong>' + (isNum(o[k]) ? (Math.abs(o[k]) < 1 && !Number.isInteger(o[k]) ? FX.num(o[k], 3) : FX.num(o[k], Number.isInteger(Number(o[k])) ? 0 : 1)) : esc(o[k])) + '</strong></div>').join('') + '</div>';
};
/* p from {pid: p} or {pid: {p, ...}} */
FX.pOf = v => (isNum(v) ? Number(v) : v && isNum(v.p) ? Number(v.p) : null);

})(window.TA);
