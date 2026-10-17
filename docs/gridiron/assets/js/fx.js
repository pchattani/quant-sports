/* The Quant Gridiron — shared helpers for the catalogue pages (players, player, teams, team,
 * fourth downs, coaches, leaders, history, lab, compare, calibration, docs): GI.fx.
 * Adapted from the Bullpen's BP.fx (the baseball helpers dropped, football ones added).
 *
 * Read lazily at render time by each module (const FX = () => GI.fx), so script order does
 * not matter. Everything degrades to a local implementation when the core helper is missing.
 *
 * Data contract: oddsmarkets/nfl/PAYLOADS.md. */
(function (GI) {
'use strict';

const FX = GI.fx = GI.fx || {};

// ── basics ─────────────────────────────────────────────────────────────────

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const esc = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
FX.isNum = isNum;
FX.esc = GI.esc || esc;
FX.alive = el => !!el && el.isConnected;
FX.has = v => v !== undefined && v !== null && !(typeof v === 'number' && !isFinite(v));
FX.ok = d => !!d && d.ok !== false;
FX.muted = t => (GI.muted ? GI.muted(t) : '<div class="muted">' + t + '</div>');
FX.num = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
FX.signed = (v, d) => {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
};
FX.pct = (p, d) => (GI.pct ? GI.pct(p, d) : (isNum(p) ? (p * 100).toFixed(d === undefined ? 1 : d) + '%' : '—'));
FX.epa = v => FX.signed(v, 3);
FX.ordinal = n => (GI.ordinal ? GI.ordinal(n) : String(n));
FX.fmtDate = (s, o) => (GI.fmtDate ? GI.fmtDate(s, o) : (s ? String(s).slice(0, 10) : '—'));
FX.fmtStamp = s => (GI.fmtStamp ? GI.fmtStamp(s) : (s ? String(s).replace('T', ' ').replace(/:\d\dZ?$/, '') : ''));

/* Format a catalogue value by its declared fmt (PAYLOADS.md; GI.fmtVal lists them). */
FX.fmtV = (v, fmt) => {
  if (GI.fmtVal && fmt) return GI.fmtVal(v, fmt);
  if (!isNum(v)) return '—';
  const x = Number(v);
  return Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2);
};
FX.fmt = (m, v) => FX.fmtV(v, (m || {}).fmt);
FX.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
FX.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
FX.sd = a => { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = FX.mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); };
FX.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return 'rgba(200,131,74,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
FX.C = GI.C;
FX.PALETTE = GI.PALETTE;
FX.CA = GI.C.p1; FX.CB = GI.C.p2;     // side A (leather) / side B (blue)

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
    const firstK = x[keys[0]];
    const inner = Object.keys(firstK);
    if (inner.length && inner.every(k => /^\d+$/.test(k)) && keys.every(k => typeof x[k][inner[0]] !== 'object')) {
      return inner.map(i => { const o = {}; keys.forEach(c => { o[c] = x[c][i]; }); return o; });
    }
    return keys.map(k => Object.assign({ _key: k }, x[k]));
  }
  return [];
};

// ── season, week, names ────────────────────────────────────────────────────

/* The season of a page: params.season, else ?s=, else the state's, else the current one. */
FX.S = (params, state) => {
  const raw = params && (params.season || (params.query || {}).s);
  if (isNum(raw)) return Number(raw);
  const st = state || GI.state || {};
  if (isNum(st.season)) return Number(st.season);
  return GI.currentSeason();
};
FX.Y = FX.S;
FX.W = (params, state) => {
  const raw = params && params.week;
  if (isNum(raw)) return Number(raw);
  const st = state || GI.state || {};
  return isNum(st.week) ? Number(st.week) : GI.currentWeek();
};
FX.ready = () => Promise.resolve(GI.index() || {});
FX.playerName = pid => GI.playerName(pid);
FX.playerShort = pid => GI.playerShort(pid);
FX.surname = n => GI.surnameOf(n);
FX.playerHref = pid => GI.playerHref(pid);
FX.href = (sub, S) => GI.ghref(sub, S);
/* Player link; name optional; opts as GI.playerLink ({team, pos, surname, short}). */
FX.playerLink = (pid, name, opts) => GI.playerLink(pid, Object.assign({}, opts || {}, name ? { name: name } : {}));
FX.teamLink = (t, opts) => GI.teamLink(t, opts);
FX.gameLink = (id, label) => GI.gameLink(id, label);
FX.coachLink = name => GI.coachLink(name);
FX.ageOf = dob => {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};
/* data/<S>/<file>. */
FX.path = (S, f) => S + '/' + f;
/* First payload that loads and is ok, from a list of paths. */
FX.first = paths => {
  const tryI = i => (i >= paths.length ? Promise.resolve(null) : GI.load(paths[i]).then(d => (d && d.ok !== false ? d : (i + 1 < paths.length ? tryI(i + 1) : d))));
  return tryI(0);
};
FX.notBuilt = (what, d) => FX.muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.');

// ── catalogue helpers ──────────────────────────────────────────────────────

/* Position groups as players.json writes them, and their labels. */
FX.GROUPS = ['QB', 'RB', 'WR', 'TE', 'K', 'P', 'DEF'];
FX.GROUP_LABEL = { QB: 'Quarterbacks', RB: 'Running backs', WR: 'Wide receivers', TE: 'Tight ends', K: 'Kickers', P: 'Punters', DEF: 'Defence' };
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
/* Scope note for a METRIC: play-by-play (nflverse), our model, Next Gen Stats, FTN charting, participation. */
FX.scopeTag = m => {
  const s = String((m || {}).scope || '').toLowerCase();
  if (s === 'ngs') return '<span class="scope-tag real" title="NFL Next Gen Stats (via nflverse), 2016 on">NGS</span>';
  if (s === 'ftn') return '<span class="scope-tag ftn" title="FTN Data via nflverse (CC BY-SA 4.0), 2022 on">FTN</span>';
  if (s === 'model') return '<span class="scope-tag model" title="Our model">model</span>';
  if (s === 'participation' || s === 'part') return '<span class="scope-tag inferred" title="nflverse participation data, 2016-2025">part.</span>';
  if (s === 'pbp') return '<span class="scope-tag pbp" title="nflverse play-by-play">pbp</span>';
  return '';
};

FX.pctColor = p => (GI.pctColor ? GI.pctColor(p) : '#30363d');
FX.pill = p => GI.pctPill(p);
FX.pctRow = (label, p, valueText, title) => GI.pctRow(label, p, valueText, title);
/* A percentile panel of Savant-style sliders grouped by METRIC.group. vals {key: v}, pctSrc {key: 0-100}. opts {note, keys}. */
FX.pctPanel = (metrics, vals, pctSrc, opts) => GI.charts.percentileSliders(metrics, vals, pctSrc, opts);
FX.tile = (label, value, sub, cls) => GI.statTile(label, value, sub, cls);
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
/* Position-group toggle (QB · RB · WR · TE · K · P · DEF), limited to the groups given. */
FX.groupToggle = (id, cur, groups) => FX.toggle(id, (groups || FX.GROUPS).map(g => [g, g]), cur || 'QB');
FX.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' + (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl || '') + '</div>' : '') + (body || '') + '</div>';
FX.table = (cols, rows, opts) => GI.tableHTML(cols, rows, opts);
FX.pairColours = (ca, cb) => (!ca || !cb || String(ca).toLowerCase() !== String(cb).toLowerCase() ? [ca || FX.CA, cb || FX.CB] : [ca, '#e6edf3']);

// ── charts ─────────────────────────────────────────────────────────────────

FX.layout = extra => GI.layout(extra);
FX.plot = (el, traces, lay, conf) => GI.plot(el, traces, lay, conf);
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
/* p from {id: p} or {id: {p, ...}} */
FX.pOf = v => (isNum(v) ? Number(v) : v && isNum(v.p) ? Number(v.p) : null);

})(window.GI);
