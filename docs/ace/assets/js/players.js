/* The Quant Ace — players: the shared kit for builder F's pages (TA.fk), the catalogue
 * (#/<T>/players) and the player page (#/<T>/player/<pid>).
 *
 * TA.fk is defined here and read lazily at render time by elo.js, h2h.js, lab.js, compare.js,
 * calibration.js and docs.js (const K = () => TA.fk), so script order does not matter as long
 * as this file is loaded. It leans on the core (core.js: TA.tableHTML, TA.sortable, TA.pctColor,
 * TA.statTile, TA.load) and draws its charts with the kit (QKC, through TA.v2) where those exist and falls back to local
 * versions where they do not.
 *
 * Data (oddsmarkets/tennis/PAYLOADS.md): data/<T>/players.json (catalogue: values, tour and
 * surface-pool percentiles), data/<T>/players/<pid>.json (career), data/<T>/players_index.json
 * (names for search and links), data/<T>/elo.json (current surface Elos), data/<T>/rankings.json
 * (official, race, points to defend), data/<T>/race.json (Finals and year-end No. 1 odds),
 * data/<T>/<year>/events.json (event names in the results log), data/<T>/style.json (tour
 * medians for the charting profile). */
(function (TA) {
'use strict';

// ════════════════════════════════════════════════════════════════════════════
// The kit: TA.fk
// ════════════════════════════════════════════════════════════════════════════

const K = TA.fk = TA.fk || {};

const isNum = v => v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v);
const escL = s => String(s === null || s === undefined ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
K.isNum = isNum;
K.esc = s => (typeof TA.esc === 'function' ? TA.esc(s) : escL(s));
K.has = v => v !== undefined && v !== null && !(typeof v === 'number' && !isFinite(v));
K.alive = el => !!el && el.isConnected;
K.ok = d => !!d && d.ok !== false;
K.muted = t => '<div class="muted">' + t + '</div>';
K.notBuilt = (what, d) => K.muted(K.esc(what) + ' is not available yet' + (d && d.reason ? ' (' + K.esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.');
K.num = (v, d) => (isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—');
K.int = v => (isNum(v) ? Math.round(Number(v)).toLocaleString('en-GB') : '—');
K.signed = (v, d) => {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
};
K.pct = (p, d) => {
  if (!isNum(p)) return '—';
  const dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
};
/* Catalogue values by METRIC fmt (PAYLOADS: int|1|2|3|pct|prob|signed); fractions are 0-1. */
K.fmtV = (v, fmt) => {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt)) {
    case 'int': return Math.round(x).toLocaleString('en-GB');
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'prob': return K.pct(x);
    case 'signed': return K.signed(x, Math.abs(x) >= 10 ? 1 : 2);
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : x.toFixed(2);
  }
};
K.fmt = (m, v) => K.fmtV(v, (m || {}).fmt);
K.median = a => { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; };
K.mean = a => { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; };
K.sd = a => { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = K.mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); };
K.alpha = (hex, a) => {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return TA.alpha ? TA.alpha(hex || 'var(--c-1)', a) : 'rgba(88,166,255,' + a + ')';
  return 'rgba(' + parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16) + ',' + a + ')';
};
K.logit = p => { const q = Math.min(1 - 1e-9, Math.max(1e-9, p)); return Math.log(q / (1 - q)); };
K.sigmoid = x => 1 / (1 + Math.exp(-x));
K.C = Object.assign({ bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d', text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316', purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8' }, TA.C || {});
K.PALETTE = TA.PALETTE || ['#58a6ff', '#f97316', '#3fb950', '#bc8cff', '#f85149', '#d29922', '#39d0d8', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
K.CA = (TA.C && TA.C.p1) || '#d9f24f'; K.CB = (TA.C && TA.C.p2) || '#58a6ff';   // player A / player B, as the core's match pages

// ── surfaces ───────────────────────────────────────────────────────────────

K.SURFACES = ['hard', 'clay', 'grass'];
K.SURF_LABEL = { all: 'All surfaces', hard: 'Hard', clay: 'Clay', grass: 'Grass', carpet: 'Carpet' };
const SURF_C = { all: '#e6edf3', hard: '#3b82f6', clay: '#d2693c', grass: '#3fb950', carpet: '#8b949e' };
K.surfColour = s => {
  const k = String(s || 'all').toLowerCase();
  if (k !== 'all' && TA.C && TA.C[k]) return TA.C[k];
  return SURF_C[k] || SURF_C.all;
};
K.surfChip = s => (s ? '<span class="af-surf" style="--sc:' + K.surfColour(s) + '">' + K.esc(K.SURF_LABEL[s] || s) + '</span>' : '');
K.LEVEL_LABEL = { slam: 'Grand Slam', finals: 'Finals', m1000: '1000', '500': '500', '250': '250', other: 'Other', ch: 'Challenger / 125', q: 'Qualifying' };
K.ROUND_ORDER = ['Q1', 'Q2', 'Q3', 'R128', 'R64', 'R32', 'R16', 'RR', 'QF', 'SF', 'BR', 'F'];
K.ROUND_LABEL = { R128: 'Round of 128', R64: 'Round of 64', R32: 'Round of 32', R16: 'Round of 16', QF: 'Quarter-final', SF: 'Semi-final', F: 'Final', RR: 'Round robin', BR: 'Bronze', Q1: 'Qualifying 1', Q2: 'Qualifying 2', Q3: 'Qualifying 3' };

// ── tour, year, index ──────────────────────────────────────────────────────

K.T = (params, state) => {
  const t = (params && (params.tour || params.T)) || (state && state.tour) || (TA.state && TA.state.tour) || 'atp';
  return String(t).toLowerCase() === 'wta' ? 'wta' : 'atp';
};
K.TN = T => (T === 'wta' ? 'WTA' : 'ATP');
K.FIRST_YEAR = { atp: 2000, wta: 2007 };
K.ready = () => (K.INDEX ? Promise.resolve(K.INDEX) : TA.load('index.json').then(d => { K.INDEX = d || {}; return K.INDEX; }));
K.tourInfo = T => (((K.INDEX || {}).tours) || {})[T] || {};
K.Y = (params, state, T) => {
  const raw = params && (params.year || (params.query || {}).y || (params.query || {}).year);
  if (isNum(raw)) return Number(raw);
  const st = state || TA.state || {};
  if (isNum(st.year)) return Number(st.year);
  const ti = K.tourInfo(T || K.T(params, state));
  return isNum(ti.year) ? Number(ti.year) : new Date().getFullYear();
};

// ── names, links ───────────────────────────────────────────────────────────

K.NAMES = K.NAMES || { atp: {}, wta: {} };          // pid -> {name, short, country, rank}
K.learn = (T, pid, info) => { if (!pid || !info) return; const N = K.NAMES[T] || (K.NAMES[T] = {}); N[pid] = Object.assign({}, N[pid] || {}, info); };
K.loadNames = T => TA.load(T + '/players_index.json').then(d => {
  // PAYLOADS: {pid: [name, short, country, rank]}; the builder wraps it as {"ok", "players": {...}}.
  const m = d && typeof d === 'object' && d.ok !== false ? (d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : d) : null;
  if (m) Object.keys(m).forEach(pid => { const r = m[pid]; if (Array.isArray(r)) K.learn(T, pid, { name: r[0], short: r[1], country: r[2], rank: r[3] }); });
  return d;
});
K.learnCat = (T, cat) => { const P = ((cat || {}).players) || {}; Object.keys(P).forEach(id => { const p = P[id] || {}; if (p.name) K.learn(T, id, { name: p.name, country: p.country, rank: p.rank }); }); };
K.name = (T, pid) => {
  const x = (K.NAMES[T] || {})[pid];
  if (x && x.name) return x.name;
  if (typeof TA.playerName === 'function') { try { const n = TA.playerName(T, pid); if (n && !/^Player /.test(n)) return n; } catch (e) { /* local */ } }
  if (/^x:/.test(String(pid))) return String(pid).slice(2).split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  return pid ? '#' + pid : '—';
};
K.surname = n => { const p = String(n || '').split(' '); return p.length > 1 ? p.slice(1).join(' ') : p[0]; };
K.short = (T, pid) => { const x = (K.NAMES[T] || {})[pid]; return (x && x.short) || K.surname(K.name(T, pid)); };
K.country = (T, pid) => ((K.NAMES[T] || {})[pid] || {}).country || (typeof TA.playerCountry === 'function' ? TA.playerCountry(T, pid) : '') || '';
const enc = encodeURIComponent;
K.href = (T, sub) => '#/' + T + (sub ? '/' + String(sub).replace(/^\/+/, '') : '');
K.playerHref = (T, pid) => K.href(T, 'player/' + enc(pid));
K.eventHref = (T, eid) => K.href(T, 'event/' + enc(eid));
K.matchHref = (T, mid) => K.href(T, 'match/' + enc(mid));
K.h2hHref = (T, a, b) => K.href(T, 'h2h/' + enc(a) + (b ? '/' + enc(b) : ''));
K.compareHref = (T, a, b) => K.href(T, 'compare/' + enc(a) + (b ? '/' + enc(b) : ''));
K.playerLink = (T, pid, label) => (pid ? '<a class="ply-link" href="' + K.playerHref(T, pid) + '">' + K.esc(label || K.name(T, pid)) + '</a>' : '<span class="muted-inline">—</span>');
K.ctry = c => (c ? '<span class="af-ctry">' + K.esc(c) + '</span>' : '');
/* Event names come from data/<T>/<year>/events.json; the slug is the fallback. */
K.EVENTS = K.EVENTS || {};
K.loadEvents = (T, years) => Promise.all((years || []).map(y => TA.load(T + '/' + y + '/events.json').then(d => {
  if (d && d.ok !== false && typeof d === 'object') Object.keys(d).forEach(k => { if (d[k] && typeof d[k] === 'object') K.EVENTS[T + ':' + k] = d[k]; });
})));
K.event = (T, eid) => {
  if (K.EVENTS[T + ':' + eid]) return K.EVENTS[T + ':' + eid];
  if (typeof TA.eventInfo === 'function') { const e = TA.eventInfo(T, eid); if (e && e.name) return e; }
  return null;
};
K.eventName = (T, eid) => {
  const e = K.event(T, eid);
  if (e && e.name) return e.name;
  const s = String(eid || '').replace(/-\d{4}$/, '');
  return s.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') || '—';
};
K.eventLink = (T, eid, label) => (eid ? '<a href="' + K.eventHref(T, eid) + '">' + K.esc(label || K.eventName(T, eid)) + '</a>' : '—');
K.ageOf = dob => {
  if (!dob) return null;
  const d = new Date(String(dob).slice(0, 10) + 'T12:00:00Z');
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  let a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
K.fmtDate = (s, o) => {
  if (typeof TA.fmtDate === 'function') { try { return TA.fmtDate(s, o); } catch (e) { /* local */ } }
  if (!s) return '—';
  const d = new Date(String(s).length === 10 ? s + 'T12:00:00Z' : s);
  if (isNaN(d.getTime())) return String(s);
  const opt = o || {};
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + (opt.year === false ? '' : ' ' + d.getFullYear());
};
K.shortDate = s => K.fmtDate(s, { year: true, weekday: false });

// ── HTML furniture ─────────────────────────────────────────────────────────

K.card = (title, sub, body, id, ctl) => '<div class="card"' + (id ? ' id="' + K.esc(id) + '"' : '') + '>' +
  (title ? '<div class="card-header">' + K.esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl || '') + '</div>' : '') + (body || '') + '</div>';
K.tile = (label, value, sub, cls) => (typeof TA.statTile === 'function' ? TA.statTile(label, value, sub, cls) :
  '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + K.esc(label) + '</div><div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>');
K.toggle = (id, opts, cur) => '<span class="pg-toggle" id="' + K.esc(id) + '">' + opts.map(o => '<button type="button" data-v="' + K.esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' class="on"' : '') + '>' + K.esc(o[1]) + '</button>').join('') + '</span>';
K.wireToggle = (root, id, fn) => {
  const t = (root || document).querySelector('#' + id);
  if (!t) return;
  t.querySelectorAll('button').forEach(b => b.addEventListener('click', () => {
    t.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    fn(b.dataset.v);
  }));
};
K.pctColor = p => {
  if (typeof TA.pctColor === 'function') return TA.pctColor(p);
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100, lo = [59, 130, 246], mid = [107, 114, 128], hi = [239, 68, 68];
  const a = t < 0.5 ? lo : mid, b = t < 0.5 ? mid : hi, u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + [0, 1, 2].map(i => Math.round(a[i] + (b[i] - a[i]) * u)).join(',') + ')';
};
K.ink = p => (typeof TA.pctInk === 'function' ? TA.pctInk(p) : '#fff');
K.pill = p => (isNum(p) ? '<span class="pct-pill" style="background:' + K.pctColor(p) + ';color:' + K.ink(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-pill empty">—</span>');
K.pctRow = (label, p, valueText, title) => {
  const known = isNum(p), x = known ? Math.max(0, Math.min(100, p)) : 0;
  return '<div class="pct-row"' + (title ? ' title="' + K.esc(title) + '"' : '') + '><span class="pct-label">' + K.esc(label) + '</span><div class="pct-bar">' +
    (known ? '<div class="pct-fill" style="width:' + x + '%;background:' + K.pctColor(p) + '"></div><span class="pct-dot" style="left:' + x + '%;background:' + K.pctColor(p) + ';color:' + K.ink(p) + '">' + Math.round(p) + '</span>' : '<span class="pct-none">not enough data</span>') +
    '</div><span class="pct-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
};
K.SCOPE_NOTE = { wta_stats: 'WTA match stats (WTA API, tour level, 2016 on)', charted: 'Match Charting Project matches only' };
K.pctPanel = (metrics, vals, pctSrc, opts) => {
  const o = opts || {};
  const groups = K.groups(metrics).map(g => ({ name: g.name, items: g.items.filter(m => !o.onlyKnown || isNum((vals || {})[m.key])) })).filter(g => g.items.length);
  if (!groups.length) return K.muted('No metrics in the catalogue yet.');
  return '<div class="pg-pct-cols">' + groups.map(g => '<div class="pct-group"><div class="pct-group-head">' + K.esc(g.name) + '</div>' +
    g.items.map(m => K.pctRow(m.label + (m.lower ? ' ↓' : ''), (pctSrc || {})[m.key], K.fmt(m, (vals || {})[m.key]),
      (m.desc || '') + (m.lower ? ' (lower is better; the percentile already accounts for it)' : '') + (K.SCOPE_NOTE[m.scope] ? ' · ' + K.SCOPE_NOTE[m.scope] : ''))).join('') + '</div>').join('') + '</div>' +
    (o.note ? '<div class="pg-note">' + o.note + '</div>' : '');
};

/* Tables: the core's when present (same signature as Hardwood's HW.tableHTML), else this copy. */
K.table = (cols, rows, opts) => {
  if (typeof TA.tableHTML === 'function') return TA.tableHTML(cols, rows, opts);
  const o = opts || {};
  let h = '<div class="table-wrap' + (o.compact ? ' compact' : '') + '"' + (o.id ? ' id="' + K.esc(o.id) + '"' : '') + '><table class="wc-table' + (o.sticky ? ' sticky-head' : '') + (o.cls ? ' ' + o.cls : '') + '"><thead><tr>';
  cols.forEach(c => {
    const cc = typeof c === 'string' ? { label: c } : c;
    h += '<th class="' + (cc.sortable === false ? '' : 'sortable-th') + (cc.cls ? ' ' + cc.cls : '') + '"' + (cc.align ? ' style="text-align:' + cc.align + '"' : '') + (cc.title ? ' title="' + K.esc(cc.title) + '"' : '') + '>' + K.esc(cc.label) + '</th>';
  });
  h += '</tr></thead><tbody>';
  (rows || []).forEach(r => {
    const row = Array.isArray(r) ? { cells: r } : r;
    h += '<tr' + (row._class ? ' class="' + row._class + '"' : '') + (row._href ? ' data-href="' + K.esc(row._href) + '"' : '') + '>';
    row.cells.forEach((c0, i) => {
      const c = (c0 !== null && typeof c0 === 'object') ? c0 : { v: c0 };
      const col = typeof cols[i] === 'object' ? cols[i] : {};
      const align = c.align || col.align;
      const sortV = c.v !== undefined && c.v !== null ? c.v : (c.html !== undefined ? String(c.html).replace(/<[^>]*>/g, '') : '');
      h += '<td data-v="' + K.esc(sortV) + '"' + (c.cls || col.cls ? ' class="' + [c.cls, col.cls].filter(Boolean).join(' ') + '"' : '') + (c.title ? ' title="' + K.esc(c.title) + '"' : '') +
        (align ? ' style="text-align:' + align + '"' : '') + '>' + (c.html !== undefined ? c.html : K.esc(c.v === null || c.v === undefined ? '—' : c.v)) + '</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
};
K.sortable = el => {
  if (typeof TA.sortable === 'function') return TA.sortable(el);
  const root = typeof el === 'string' ? document.getElementById(el) : el;
  if (!root) return;
  const tables = root.tagName === 'TABLE' ? [root] : Array.prototype.slice.call(root.querySelectorAll('table'));
  tables.forEach(table => {
    if (table.dataset.sortWired) return;
    table.dataset.sortWired = '1';
    const ths = Array.prototype.slice.call(table.querySelectorAll('thead th'));
    ths.forEach((th, idx) => {
      if (!th.classList.contains('sortable-th')) return;
      th.addEventListener('click', () => {
        const tbody = table.querySelector('tbody');
        const rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        const asc = th.dataset.sortDir !== 'asc';
        ths.forEach(x => { delete x.dataset.sortDir; });
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        rows.sort((a, b) => {
          const av = a.children[idx] ? a.children[idx].dataset.v : '', bv = b.children[idx] ? b.children[idx].dataset.v : '';
          const an = parseFloat(av), bn = parseFloat(bv), aN = !isNaN(an) && isFinite(av), bN = !isNaN(bn) && isFinite(bv);
          const cmp = aN && bN ? an - bn : aN ? -1 : bN ? 1 : String(av).localeCompare(String(bv));
          return asc ? cmp : -cmp;
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
    table.querySelectorAll('tr[data-href]').forEach(tr => {
      tr.classList.add('row-link');
      tr.addEventListener('click', ev => { if (ev.target.closest('a')) return; location.hash = tr.dataset.href; });
    });
  });
};

// ── charts: the kit's (QKC on ECharts) through TA.v2 (v2.js); no Plotly.

// ── catalogue helpers ──────────────────────────────────────────────────────

K.metaOf = metrics => { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; };
K.groups = metrics => {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === (m.group || 'Other')); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
};
/* First key of an object (or metric list) matching a candidate: exact strings first, then regexes. */
K.pick = (obj, cands) => {
  const keys = Array.isArray(obj) ? obj.map(m => m.key) : Object.keys(obj || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (typeof c === 'string' && keys.indexOf(c) >= 0) return c; }
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (c instanceof RegExp) { const k = keys.find(x => c.test(x)); if (k) return k; } }
  return null;
};
/* Up to n metrics: the preferred candidates in order, then one per group, then the rest. pctAny: only metrics with a percentile there. */
K.headline = (metrics, prefs, n, pctAny) => {
  const out = [];
  const usable = (metrics || []).filter(m => !pctAny || pctAny === true || isNum(pctAny[m.key]));
  (prefs || []).forEach(p => {
    if (out.length >= n) return;
    const re = p instanceof RegExp ? p : new RegExp('^' + p + '$');
    const m = usable.find(x => re.test(x.key) && out.indexOf(x) < 0);
    if (m) out.push(m);
  });
  const seen = {}; out.forEach(m => { seen[m.group] = 1; });
  usable.forEach(m => { if (out.length < n && !seen[m.group] && out.indexOf(m) < 0) { out.push(m); seen[m.group] = 1; } });
  usable.forEach(m => { if (out.length < n && out.indexOf(m) < 0) out.push(m); });
  return out.slice(0, n);
};
K.shortLabel = s => String(s || '').replace(/percentage/i, '%').replace(/ over expected/i, ' v exp').replace(/^Expected /, 'x').slice(0, 26);
K.glossLink = (key, text) => '<a class="gl-link" href="#/glossary/' + enc(key) + '" title="Glossary: ' + K.esc(key) + '">' + text + '</a>';
K.recPct = (w, l) => (isNum(w) && isNum(l) && w + l > 0 ? w / (w + l) : null);
K.rec = (w, l) => (isNum(w) && isNum(l) ? Math.round(w) + '–' + Math.round(l) : '—');

// ── player picker (typeahead over players_index.json) ─────────────────────

const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
/* A search box that resolves to a player id. host: element; opts {T, value (pid), placeholder, onPick(pid)}. */
K.picker = (host, opts) => {
  const o = opts || {};
  const T = o.T;
  host.classList.add('af-picker');
  host.innerHTML = '<input type="search" class="pg-search af-pick-in" autocomplete="off" spellcheck="false" placeholder="' + K.esc(o.placeholder || 'Type a player…') + '"><div class="af-pick-list"></div>';
  const input = host.querySelector('input'), list = host.querySelector('.af-pick-list');
  if (o.value) input.value = K.name(T, o.value);
  let items = null;
  const build = () => {
    const N = K.NAMES[T] || {};
    items = Object.keys(N).map(id => ({ id: id, n: N[id].name || id, c: N[id].country || '', r: isNum(N[id].rank) ? Number(N[id].rank) : 9999, f: fold(N[id].name || id) }));
    items.sort((a, b) => a.r - b.r || a.n.localeCompare(b.n));
  };
  const close = () => { list.innerHTML = ''; list.style.display = 'none'; };
  const show = () => {
    if (!items) build();
    const q = fold(input.value.trim());
    if (q.length < 2) { close(); return; }
    const words = q.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.f.indexOf(w) >= 0)).slice(0, 12);
    list.innerHTML = hits.length ? hits.map(h => '<button type="button" data-id="' + K.esc(h.id) + '"><span>' + K.esc(h.n) + '</span><span class="af-pick-sub">' + K.esc(h.c) + (h.r < 9999 ? ' · #' + h.r : '') + '</span></button>').join('') : '<div class="af-pick-none">No player matches.</div>';
    list.style.display = 'block';
  };
  input.addEventListener('input', show);
  input.addEventListener('focus', () => { input.select(); });
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') close();
    if (ev.key === 'Enter') { const b = list.querySelector('button[data-id]'); if (b) { ev.preventDefault(); b.click(); } }
  });
  list.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-id]');
    if (!b) return;
    input.value = K.name(T, b.dataset.id);
    close();
    if (o.onPick) o.onPick(b.dataset.id);
  });
  const outside = ev => { if (!host.contains(ev.target)) close(); };
  document.addEventListener('click', outside);
  if (typeof TA.onLeave === 'function') TA.onLeave(() => document.removeEventListener('click', outside));
  return { input: input, refresh: () => { items = null; } };
};

// ── the match chain in the browser (h2h and the player page) ───────────────
// The same point → game → tiebreak → set → match recursions as models/match_chain.py, used only
// to price hypothetical matchups from the published ratings.

const CH = K.chain = {};
/* P(server holds) from the serve-point probability p (models/serve_return.py game_hold). */
CH.game = p => { const q = 1 - p; return Math.pow(p, 4) * (1 + 4 * q + 10 * q * q) + 20 * Math.pow(p * q, 3) * p * p / (1 - 2 * p * q); };
/* Inverse: the serve-point probability that holds with probability h (bisection). */
CH.inv = h => { let lo = 0.0001, hi = 0.9999; const t = Math.min(0.99999, Math.max(0.00001, h)); for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (CH.game(m) < t) lo = m; else hi = m; } return (lo + hi) / 2; };
/* P(A wins a tiebreak to N) when A serves first; pa, pb are serve-point win probabilities. */
CH.tiebreak = (pa, pb, N) => {
  const n = N || 7, memo = {};
  const tie = pa * (1 - pb) / (pa * (1 - pb) + (1 - pa) * pb);
  const f = (a, b) => {
    if (a >= n && a - b >= 2) return 1;
    if (b >= n && b - a >= 2) return 0;
    if (a >= n - 1 && b >= n - 1 && a === b) return tie;
    const k = a + b, key = a + ':' + b;
    if (memo[key] !== undefined) return memo[key];
    const aServes = Math.floor((k + 1) / 2) % 2 === 0;
    const pw = aServes ? pa : 1 - pb;
    return (memo[key] = pw * f(a + 1, b) + (1 - pw) * f(a, b + 1));
  };
  return f(0, 0);
};
/* Set outcomes when `first` (0 = A, 1 = B) serves first: [{a, b, p, win (A), odd (games odd)}]. rule: tb7 | tb10 | tb12 | adv. */
CH.set = (pa, pb, first, rule) => {
  const hA = CH.game(pa), hB = CH.game(pb);
  const tbAt = rule === 'tb12' ? 12 : rule === 'adv' ? 99 : 6, tbTo = rule === 'tb10' ? 10 : 7;
  const out = {}, add = (a, b, p) => { const k = a + '-' + b; out[k] = (out[k] || 0) + p; };
  const P = {};   // probability of reaching each game score, swept in order of games played
  P['0:0'] = 1;
  const order = [];
  for (let s = 0; s <= 2 * Math.min(tbAt, 30); s++) for (let a = 0; a <= s; a++) order.push([a, s - a]);
  order.forEach(ab => {
    const a = ab[0], b = ab[1], pr = P[a + ':' + b];
    if (!pr) return;
    const done = (a >= 6 && a - b >= 2) || (b >= 6 && b - a >= 2);
    if (done) { add(a, b, pr); return; }
    if (a === tbAt && b === tbAt) {
      const aFirst = ((a + b) % 2 === 0) === (first === 0);
      const w = aFirst ? CH.tiebreak(pa, pb, tbTo) : 1 - CH.tiebreak(pb, pa, tbTo);
      add(a + 1, b, pr * w); add(a, b + 1, pr * (1 - w));
      return;
    }
    if (a >= 30 || b >= 30) { add(a > b ? a : a + 2, b > a ? b : b + 2, pr); return; }
    const aServing = ((a + b) % 2 === 0) === (first === 0);
    const pw = aServing ? hA : 1 - hB;
    P[(a + 1) + ':' + b] = (P[(a + 1) + ':' + b] || 0) + pr * pw;
    P[a + ':' + (b + 1)] = (P[a + ':' + (b + 1)] || 0) + pr * (1 - pw);
  });
  return Object.keys(out).map(k => { const g = k.split('-').map(Number); return { a: g[0], b: g[1], p: out[k], win: g[0] > g[1], odd: (g[0] + g[1]) % 2 === 1 }; });
};
/* Match: {p (A wins), sets: {"2-0": p, ...}, straight, games (mean)} with the first server averaged 50/50. */
CH.match = (pa, pb, bestOf, finalRule) => {
  const need = bestOf === 5 ? 3 : 2;
  const cache = {};
  const setOf = (first, deciding) => { const k = first + (deciding ? 'd' : 'n'); return cache[k] || (cache[k] = CH.set(pa, pb, first, deciding ? (finalRule || 'tb7') : 'tb7')); };
  const sets = {};
  let pWin = 0, games = 0;
  const go = (sa, sb, first, pr, g) => {
    if (sa === need || sb === need) { const k = sa + '-' + sb; sets[k] = (sets[k] || 0) + pr; if (sa === need) pWin += pr; games += pr * g; return; }
    const deciding = sa === need - 1 && sb === need - 1;
    setOf(first, deciding).forEach(o => { go(sa + (o.win ? 1 : 0), sb + (o.win ? 0 : 1), o.odd ? 1 - first : first, pr * o.p, g + o.a + o.b); });
  };
  go(0, 0, 0, 0.5, 0); go(0, 0, 1, 0.5, 0);
  const straight = (sets[need + '-0'] || 0) + (sets['0-' + need] || 0);
  return { p: pWin, sets: sets, straight: straight, games: games };
};
/* δ such that match(pa+δ, pb−δ) has win probability target (models/match_chain.solve_shift). */
CH.shift = (pa, pb, bestOf, rule, target) => {
  let lo = Math.max(0.02 - pa, pb - 0.98), hi = Math.min(0.98 - pa, pb - 0.02);
  for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (CH.match(pa + m, pb - m, bestOf, rule).p < target) lo = m; else hi = m; }
  return (lo + hi) / 2;
};

// ════════════════════════════════════════════════════════════════════════════
// Catalogue: #/<T>/players
// ════════════════════════════════════════════════════════════════════════════

/* Players (#/<T>/players), Design System 2.0: a leaderboard on the tour's headline metric set (METRICS_SPEC.md, via
 * TA.v2), heat cells on the percentile scale against the peer group (the tour, or the players with enough matches on
 * a surface), sorted by serve + return (the best single predictor beyond Elo). Players below the group's minimum are
 * left out of the ranked board (they have no percentile) and listed underneath. */
let IDXS = { q: '', country: '', surface: '' };
const SHORT = { elo: 'Elo', elo_hard: 'Hard Elo', elo_clay: 'Clay Elo', elo_grass: 'Grass Elo', games_won_pct: 'Games won', hold: 'Hold', brk: 'Break', win_v_top50: 'v top 50',
  win_pct: 'Win %', dominance: 'Dominance', ace_pct: 'Aces', hold_plus_break: 'Serve + return' };

function renderPlayers(el, params, state) {
  const T = K.T(params, state);
  const V = TA.v2;
  el.innerHTML = QK.skeleton('lines', 8);
  return K.ready().then(() => Promise.all([TA.load(T + '/players.json'), K.loadNames(T)])).then(res => {
    if (!K.alive(el)) return;
    const cat = res[0];
    if (!K.ok(cat) || !cat.players) { el.innerHTML = V.card('Players', '', K.notBuilt('The ' + K.TN(T) + ' player catalogue', cat)); return; }
    K.learnCat(T, cat);
    const P = cat.players;
    const ctry = {};
    Object.keys(P).forEach(id => { const c = P[id].country; if (c) ctry[c] = (ctry[c] || 0) + 1; });
    el.innerHTML = '<div class="ta-pl-ctl">' + V.seg('pl-surf', [['', 'All surfaces'], ['hard', 'Hard'], ['clay', 'Clay'], ['grass', 'Grass']], IDXS.surface, 'Peer group') +
      '<input id="pl-q" class="qk-input" type="search" placeholder="Player or country" aria-label="Search players" value="' + K.esc(IDXS.q) + '">' +
      '<select id="pl-country" class="qk-select" aria-label="Country"><option value="">All countries</option>' + Object.keys(ctry).sort().map(c => '<option value="' + K.esc(c) + '"' + (c === IDXS.country ? ' selected' : '') + '>' + K.esc(c) + ' (' + ctry[c] + ')</option>').join('') + '</select></div>' +
      V.card('<span id="pl-title"></span>', '<span id="pl-sub"></span>', '<div id="pl-table"></div>', { flush: true, html: true, foot: '<span id="pl-foot"></span><a href="' + K.href(T, 'lab') + '">Every metric in the lab →</a>' }) +
      '<section class="qk-section">' + V.card('Below the floor', 'Listed with their raw numbers only: too few matches for a percentile', '<div id="pl-below"></div>', { flush: true }) + '</section>';
    const draw = () => drawIndex(el, T, cat);
    let t = null;
    el.querySelector('#pl-q').oninput = e => { IDXS.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    el.querySelector('#pl-country').onchange = e => { IDXS.country = e.target.value; draw(); };
    QK.seg(el.querySelector('#pl-surf'), v => { IDXS.surface = v; draw(); });
    draw();
  });
}

function drawIndex(el, T, cat) {
  const V = TA.v2, P = cat.players, sf = IDXS.surface;
  const q = fold(IDXS.q.trim());
  const keys = ['hold_plus_break'].concat(V.set(T, sf));
  const match = id => {
    const p = P[id];
    if (IDXS.country && p.country !== IDXS.country) return false;
    if (q && fold(String(p.name || '') + ' ' + (p.country || '')).indexOf(q) < 0) return false;
    return true;
  };
  const ids = Object.keys(P).filter(match);
  const pool = ids.filter(id => V.inPool(P[id], sf, cat));
  const below = ids.filter(id => !V.inPool(P[id], sf, cat) && (sf ? ((P[id].values_surface || {})[sf] || {}).matches : P[id].matches));
  const rows = pool.map(id => {
    const p = P[id], r = { id: id, name: p.name || K.name(T, id), sub: [p.country, isNum(p.rank) ? 'No. ' + p.rank : ''].filter(Boolean).join(' · '),
      m: sf ? ((p.values_surface || {})[sf] || {}).matches : p.matches };
    keys.forEach(k => { r[k] = V.value(p, k, sf); r['p_' + k] = V.pctl(p, k, sf, cat); });
    return r;
  });
  QK.leaderboard(el.querySelector('#pl-table'), {
    dense: true, rank: true, sort: { key: 'hold_plus_break', dir: 'desc' }, rowHref: r => K.playerHref(T, r.id),
    columns: [{ key: 'name', label: 'Player', type: 'entity', sub: 'sub', href: r => K.playerHref(T, r.id) }, { key: 'm', label: sf ? 'Matches (' + sf + ')' : 'Matches', num: true }]
      .concat(keys.map(k => ({ key: k, label: SHORT[k] || V.label(k), type: 'pctl', pctl: 'p_' + k, fmt: v => V.fmt(k, v) }))),
    rows: rows
  });
  el.querySelector('#pl-title').textContent = K.TN(T) + (sf ? ' on ' + sf : ' players') + ', ' + (cat.year || '');
  el.querySelector('#pl-sub').innerHTML = 'Peers: ' + K.esc(V.peer(T, sf, cat)) + '. Cells are coloured by percentile against them (blue low, red high); sorted by serve + return. Hold and break are inferred from set scores' + (T === 'wta' ? '; dominance and aces come from WTA match statistics (2016 on, not the Slams)' : '') + '.';
  el.querySelector('#pl-foot').textContent = pool.length + ' qualified of ' + ids.length + (q || IDXS.country ? ' matching' : '') + ' players';
  const host = el.querySelector('#pl-below');
  host.innerHTML = below.length ? K.table([{ label: 'Player' }, { label: 'Ctry' }, { label: 'Rank', align: 'right' }, { label: sf ? 'Matches on ' + sf : 'Matches', align: 'right' }, { label: 'Win %', align: 'right' }],
    below.sort((a, b) => (P[a].rank || 9999) - (P[b].rank || 9999)).map(id => {
      const p = P[id], v = sf ? ((p.values_surface || {})[sf] || {}) : (p.values || {});
      return { _href: K.playerHref(T, id), cells: [{ v: p.name, html: K.playerLink(T, id, p.name) }, p.country || '', { v: isNum(p.rank) ? p.rank : 9999, html: isNum(p.rank) ? String(p.rank) : '—' }, v.matches || 0, { v: v.win_pct, html: K.fmtV(v.win_pct, 'pct') }] };
    }), { compact: true }) : K.muted('Everyone listed meets the floor.');
  K.sortable(host);
}

// ════════════════════════════════════════════════════════════════════════════
// Player page: #/<T>/player/<pid>
// ════════════════════════════════════════════════════════════════════════════

const K_ = {
  elo: ['elo', /^elo$/], hold: ['hold', /^hold$/, /hold/], brk: ['brk', 'break', /^br(ea)?k$/], sr: ['serve_rating', /serve_?r/], rr: ['return_rating', /return_?r/],
  spw: ['spw', /^spw/], xspw: ['xspw', /x_?spw|exp.*spw/], race: ['race_points', /race/], pts: ['points', /^points$/]
};

function renderPlayer(el, params, state) {
  const T = K.T(params, state);
  const pid = String(params.id || params.pid || (params.rest || [])[0] || '');
  el.innerHTML = K.muted('Loading…');
  /* A career file with its own peer block (PAYLOADS.md "peer") draws without the 1.5 MB season catalogue, which then
     loads only for the distribution, the luck tiles and every-metric table; without one, the catalogue loads first. */
  return K.ready().then(() => TA.load(T + '/players/' + pid + '.json')).then(c0 => {
    const career0 = K.ok(c0) ? c0 : null;
    const pc = career0 && career0.peer && Number(career0.peer.year) === Number(K.Y(params, state, T)) ? TA.v2.peerCat(career0.peer, career0, pid) : null;
    return Promise.all([pc ? Promise.resolve(pc) : TA.load(T + '/players.json'), TA.load(T + '/elo.json'), TA.load(T + '/rankings.json'), TA.load(T + '/race.json'), K.loadNames(T)]).then(res => {
      if (!K.alive(el)) return null;
      if (!pc) K.learnCat(T, res[0]);
      const years = Array.from(new Set(((career0 || {}).results || []).map(r => String(r.date || '').slice(0, 4)).filter(y => /^\d{4}$/.test(y))));
      return K.loadEvents(T, years).then(() => { if (K.alive(el)) drawPlayer(el, T, pid, career0, c0, res[0], res[1], res[2], res[3]); });
    });
  });
}

function drawPlayer(el, T, pid, career, careerRaw, cat, elo, ranks, race) {
  const C = K.C;
  /* the full season catalogue: already here, or loaded on demand when the page drew from the career file's peer block */
  let fullP = null;
  const full = () => (cat && cat._peerCat ? (fullP || (fullP = TA.load(T + '/players.json').then(d => (K.ok(d) && d.players ? d : cat)))) : Promise.resolve(cat));
  const P = (K.ok(cat) && cat.players) || {};
  const p = P[pid] || null;
  const metrics = (cat || {}).metrics || [];
  const vals = (p && p.values) || {};
  const val = cands => { const k = K.pick(vals, cands); return k ? vals[k] : null; };
  const c = career || {};
  const name = (p && p.name) || c.name || K.name(T, pid);
  if (name) K.learn(T, pid, { name: name, country: (p && p.country) || c.country });
  const country = (p && p.country) || c.country || K.country(T, pid);
  const age = p && isNum(p.age) ? Math.floor(p.age) : K.ageOf(c.dob);
  const eloCur = ((elo || {}).current || {})[pid] || null;
  const off = ((ranks || {}).official || []).find(r => r[1] === pid) || null;
  const raceList = ((ranks || {}).race || []);
  const raceIdx = raceList.findIndex(r => r[0] === pid);
  const rank = off ? off[0] : (p && p.rank) || null;
  const rival = pickRival(T, pid, ranks, P, elo);
  const h2hTop = ((c.h2h || [])[0] || [])[0];

  if (!career && !p) {
    el.innerHTML = K.card('Player', '', K.notBuilt('The page for ' + K.name(T, pid), careerRaw) + '<div class="pg-note"><a href="' + K.href(T, 'players') + '">All ' + K.TN(T) + ' players →</a></div>');
    return;
  }

  const V = TA.v2;
  const odds = c.odds || {};
  const fq = isNum(odds.finals_qual) ? odds.finals_qual : ((race || {}).finals_qual || {})[pid];
  const no1 = isNum(odds.year_end_no1) ? odds.year_end_no1 : ((race || {}).year_end_no1 || {})[pid];
  const finalsName = T === 'wta' ? 'WTA Finals' : 'ATP Finals';
  const hand = c.hand === 'L' ? 'Left-handed' : c.hand === 'R' ? 'Right-handed' : '';
  const pc = (p && p.pct) || {};
  const hero = QK.playerHeader({ name: name, pos: country || K.TN(T), kicker: K.TN(T) + ' · ' + ((cat || {}).year || ''),
    meta: [age !== null ? ['Age', String(age)] : null, hand ? ['Plays', hand] : null, isNum(c.height) ? ['Height', K.num(c.height, 0) + ' cm'] : null],
    stats: [{ label: 'Ranking', value: isNum(rank) ? '#' + rank : '—' }, { label: 'Elo', value: K.num(eloCur ? eloCur.all : vals.elo, 0) }, { label: 'Titles ' + ((cat || {}).year || ''), value: isNum(vals.titles) ? vals.titles : '—' }, { label: 'W–L', value: isNum(vals.wins) ? vals.wins + '–' + (vals.losses || 0) : '—' }],
    tags: [p && p.qualified ? QK.tag('Qualified for percentiles', 'signal') : QK.tag('Below the match floor: no percentiles')] });
  const links = '<div class="ta-pl-links">' + (rival ? '<a class="qk-btn" href="' + K.compareHref(T, pid, rival) + '">Compare with ' + K.esc(K.surname(K.name(T, rival))) + '</a>' : '') +
    (h2hTop ? '<a class="qk-btn" href="' + K.h2hHref(T, pid, h2hTop) + '">Head to head v ' + K.esc(K.surname(K.name(T, h2hTop))) + '</a>' : '') +
    '<a class="qk-btn" href="' + K.href(T, 'players') + '">All players</a></div>';
  const tiles = [];
  if (isNum(fq) && fq >= 0.005) tiles.push({ label: finalsName, value: K.pct(fq, fq > 0.995 || fq < 0.01 ? 1 : 0), signal: true, sub: 'our chance of qualifying', href: K.href(T, 'race'), tip: 'From simulating the rest of the season' });
  if (isNum(no1) && no1 >= 0.005) tiles.push({ label: 'Year-end No. 1', value: K.pct(no1, 0), signal: !(isNum(fq) && fq >= 0.005), sub: 'our chance, season simulation' });
  tiles.push({ label: 'Elo', value: K.num(eloCur ? eloCur.all : vals.elo, 0), pctl: pc.elo, sub: eloCur && isNum(eloCur.rank) ? 'No. ' + eloCur.rank + ' by Elo' : 'our strength rating', tip: 'Overall strength rating from every result, adjusted for the opponent' });
  if (isNum(vals.hold_plus_break)) tiles.push({ label: 'Serve + return', value: K.fmtV(vals.hold_plus_break, 'pct'), pctl: pc.hold_plus_break, sub: 'hold ' + K.fmtV(vals.hold, 'pct') + ' · break ' + K.fmtV(vals.brk, 'pct') + ', inferred', tip: 'Hold % plus break %, inferred from set scores: the best single predictor beyond Elo' });
  tiles.push({ label: 'Ranking', value: isNum(rank) ? '#' + rank : '—', sub: off ? K.int(off[2]) + ' points' + (isNum(off[3]) && off[3] ? ' · ' + (off[3] > 0 ? '▲' : '▼') + Math.abs(off[3]) : '') : '' });
  tiles.push({ label: 'Race position', value: raceIdx >= 0 ? '#' + (raceIdx + 1) : '—', sub: raceIdx >= 0 ? K.int(raceList[raceIdx][1]) + ' points this year, this week included' : 'outside the race top 100' });

  const surfOpts = V.SURF.filter(s => V.inPool(p, s, cat));
  let h = hero + links +
    '<div class="ta-kpis">' + QK.stats(tiles) + '</div><div id="pp-value"></div>' +
    '<div class="qk-grid"><div class="qk-span-5" id="pp-pcard"></div><div class="qk-span-7"><div class="ta-stack">' +
    (p && p.qualified ? V.card('Where ' + K.esc(K.surname(name)) + ' sits', 'Every qualified player in the peer group; bars coloured by percentile, the player and the median marked',
      '<div class="qk-seg" id="pp-dist-m" role="group" aria-label="Metric" style="margin-bottom:10px;flex-wrap:wrap"></div>' + V.chart('pp-dist', 240, 'Distribution of the peer group')) : '') +
    '<div id="pp-sim"></div></div></div></div>';
  h += '<section class="qk-section"><div class="qk-grid"><div class="qk-span-6">' + V.card('Luck: tiebreaks, deciding sets and close calls', 'Won against what our chances expected. Season to season these barely repeat (tiebreaks r = 0.03, wins over expected r = −0.10), so read them as luck, not skill', '<div id="pp-clutch"></div>', { flush: true }) + '</div>' +
    '<div class="qk-span-6">' + V.card('Ranking', 'Official ranking over time (log scale); gaps are spells without a ranking', V.chart('pp-rank', 280, 'Ranking history'), {}) + '</div></div></section>';
  h += '<div class="card"><div class="card-header">Elo history <span class="card-sub">Overall and surface Elo after every match.</span>' + K.toggle('pp-elo-win', [['all', 'Career'], ['3', 'Last 3 years'], ['1', 'Last year']], 'all') + '</div><div id="pp-elo" style="height:340px"></div></div>';
  h += '<div class="card"><div class="card-header">Serve and return <span class="card-sub">The serve and return ratings from the score-based model by surface, ±1 standard error shaded. Higher is better for both.</span>' +
    K.toggle('pp-sr-kind', [['serve', 'Serve'], ['return', 'Return'], ['hold', 'Hold %'], ['brk', 'Break %']], 'serve') + '</div><div id="pp-sr" style="height:340px"></div><div class="pg-note" id="pp-sr-note"></div></div>';
  h += '<div class="card"><div class="card-header">Points to defend <span class="card-sub">What drops off the 52-week ranking, by week.</span></div><div id="pp-defend"></div></div>';
  h += '<div class="card"><div class="card-header">Seasons <span class="card-sub">Tour-level record, titles, inferred hold and break, and Elo at the end of each year.</span></div><div id="pp-seasons"></div></div>';
  h += '<div class="card"><div class="card-header">Results <span class="card-sub" id="pp-res-sub">Our pre-match chance against what happened.</span>' +
    K.toggle('pp-res-lv', [['tour', 'Tour level'], ['all', T === 'atp' ? 'Every level, with Challengers' : 'Every level']], 'tour') +
    '<span class="pg-ctl"><select id="pp-res-surf" aria-label="Surface"><option value="">all surfaces</option><option value="hard">hard</option><option value="clay">clay</option><option value="grass">grass</option></select></span></div><div id="pp-res-chart" style="height:220px"></div><div id="pp-results"></div></div>';
  h += '<div class="card"><div class="card-header">Splits <span class="card-sub">Record, expected wins (the sum of our pre-match chances) and the difference.</span>' +
    K.toggle('pp-split', [['surface', 'Surface'], ['level', 'Level'], ['round', 'Round'], ['opp_band', 'Opponent rank']], 'surface') + '</div><div id="pp-splits"></div></div>';
  h += '<div class="card" id="pp-style-card"><div class="card-header">Style <span class="card-sub">Shot-by-shot profile from the Match Charting Project, against the median charted ' + K.TN(T) + ' player.</span></div><div id="pp-style"></div></div>';
  h += '<div class="card"><div class="card-header">Head to head <span class="card-sub">Most frequent opponents (top 30 by matches). Click for the full head-to-head page.</span></div><div id="pp-h2h"></div></div>';
  h += '<div class="card"><div class="card-header">Every metric <span class="card-sub">The whole catalogue' + (metrics.length ? ', ' + metrics.length + ' metrics,' : '') + ' as percentiles against the tour or a surface pool (100 = best; ↓ marks metrics where lower is better).</span>' +
    K.toggle('pp-src', [['tour', 'Tour']].concat(surfOpts.map(s => [s, K.SURF_LABEL[s]])), 'tour') + '</div><div id="pp-pct"></div></div>';
  el.innerHTML = h;

  // percentile card on the spec's metric set, by tour or surface
  const drawCard = sf => {
    const host = document.getElementById('pp-pcard');
    if (!host) return;
    const segH = V.seg('pp-pc-sf', [['', 'Tour']].concat(surfOpts.map(s => [s, K.SURF_LABEL[s]])), sf, 'Peer group');
    host.innerHTML = QK.pctCard({ title: 'Percentile rankings', peer: V.peer(T, sf, cat), sample: p ? V.sampleLine(p, T, sf, cat) : '',
      groups: p && V.inPool(p, sf, cat) ? V.pctGroups(p, cat, T, sf) : [], right: surfOpts.length ? segH : '',
      note: 'Hold and break are inferred from set scores, not measured point by point.',
      emptyText: p ? K.esc(name) + ' is short of the ' + (sf || 'tour') + ' match floor this season.' : 'Not in this season’s catalogue (no tour-level match this year).' });
    const sg = host.querySelector('#pp-pc-sf');
    if (sg) QK.seg(sg, v => { drawCard(v); drawDist(v); });
  };
  let distKey = null;
  const drawDist = sf => {
    const segEl = document.getElementById('pp-dist-m');
    if (!segEl || !p) return;
    const keys = V.set(T, sf);
    if (keys.indexOf(distKey) < 0) distKey = keys[0];
    segEl.innerHTML = keys.map(k => '<button type="button" aria-pressed="' + (k === distKey) + '" data-value="' + k + '">' + K.esc(SHORT[k] || V.label(k)) + '</button>').join('');
    const one = k => full().then(fc => {
      if (!document.getElementById('pp-dist')) return;
      distKey = k;
      const FP = fc.players || {};
      const peers = Object.keys(FP).filter(id => V.inPool(FP[id], sf, fc));
      const xs = peers.map(id => V.value(FP[id], k, sf)).filter(isNum).sort((a, b) => a - b);
      const mine = V.value(p, k, sf);
      if (xs.length < 5) { document.getElementById('pp-dist').innerHTML = QK.empty('Too few qualified peers yet'); return; }
      const pctFmt = (V.META[k] || [])[2] === 'pct';
      const f = pctFmt ? (v => (v * 100).toFixed(1) + '%') : (v => V.fmt(k, v));
      QKC.distribution('#pp-dist', { values: xs, binCount: 20, fmt: f, xName: V.label(k, sf) + ' · ' + xs.length + ' ' + V.peer(T, sf, cat).replace(/,.*$/, ''), yName: 'Players',
        marks: (isNum(mine) && V.inPool(p, sf, cat) ? [{ x: mine, label: K.surname(name) }] : []).concat([{ x: xs[Math.floor(xs.length / 2)], label: 'Median' }]), label: 'Distribution of ' + V.label(k) });
    });
    one(distKey);
    QK.seg(segEl, one);
  };
  drawCard('');
  drawDist('');
  // most similar (the spec's weighted distance on the tour profile)
  const sim = cat && cat._peerCat ? (cat.similar || []).slice(0, 5) : V.similar(T, pid, cat, 5);
  const simHost = document.getElementById('pp-sim');
  if (simHost && sim.length) simHost.innerHTML = V.card('Most similar', 'Nearest on this season’s profile: Elo, surface Elos, hold, break and games won' + (T === 'wta' ? ', aces and first serves in' : ', tiebreaks per set'),
    '<ul class="ta-list">' + sim.map((x, i) => '<li><span class="n">' + (i + 1) + '</span><a class="nm" href="' + K.playerHref(T, x.id) + '">' + K.esc(K.name(T, x.id)) + '</a><span class="s">' + K.esc(K.country(T, x.id)) + '</span><a class="v ta-cmp-link" href="' + K.compareHref(T, pid, x.id) + '">Compare</a></li>').join('') + '</ul>',
    { flush: true, foot: '<span></span><a href="' + K.compareHref(T, pid, sim[0].id) + (sim[1] ? '/' + encodeURIComponent(sim[1].id) : '') + '">Compare the top two →</a>' });

  // every metric
  const drawPct = src => full().then(fc => {
    const box = document.getElementById('pp-pct');
    if (!box) return;
    const p = (fc.players || {})[pid] || null, metrics = fc.metrics || [], vals = (p && p.values) || {};
    if (!p) { box.innerHTML = K.muted(K.esc(name) + ' is not in the ' + K.esc((cat || {}).year || '') + ' catalogue (no tour-level match this year).'); return; }
    const pcs = src === 'tour' ? p.pct : ((p.pct_surface || {})[src] || {});
    const vs = src !== 'tour' && (p.values_surface || {})[src] ? p.values_surface[src] : vals;
    box.innerHTML = K.pctPanel(metrics, vs, pcs, { note: (src === 'tour' ? 'Tour percentile' : K.SURF_LABEL[src] + ' percentile') + ', 100 = best. Real serve and return statistics exist for WTA matches from 2016 (not the Slams); style metrics only for charted matches. Tiebreak, deciding-set and over-expected rows are mostly luck. Hover a row for the definition.' });
  });
  drawPct('tour');
  K.wireToggle(el, 'pp-src', drawPct);

  if (TA.value && typeof TA.value.card === 'function') TA.value.card(T, pid, document.getElementById('pp-value'));
  full().then(fc => { if (K.alive(el)) drawClutch(c, (fc.players || {})[pid] || p, fc.metrics || metrics); });
  drawEloHistory(T, c, el);
  drawServeReturn(c, el);
  drawRanks(c);
  drawDefend(T, c, ranks, pid);
  drawSeasons(c);
  drawResults(T, c, el);
  drawSplits(T, c, el);
  drawStyle(T, pid, c);
  drawH2H(T, pid, c);
}

function lastSeason(c, k) { const s = (c.seasons || []).slice().sort((a, b) => b.year - a.year).find(x => isNum(x[k])); return s ? s[k] : null; }

/* The nearest player by official rank (else by Elo) with a catalogue row: the default comparison. */
function pickRival(T, pid, ranks, P, elo) {
  const off = ((ranks || {}).official || []);
  const i = off.findIndex(r => r[1] === pid);
  if (i >= 0) {
    const cands = [off[i - 1], off[i + 1], off[i - 2], off[i + 2]].filter(Boolean).map(r => r[1]).filter(x => P[x]);
    if (cands.length) return cands[0];
  }
  const cur = ((elo || {}).current) || {};
  if (cur[pid]) {
    const me = cur[pid].all;
    const near = Object.keys(cur).filter(x => x !== pid && P[x]).sort((a, b) => Math.abs(cur[a].all - me) - Math.abs(cur[b].all - me))[0];
    if (near) return near;
  }
  return null;
}

function clutchRows(cl) {
  const L = { tb: 'Tiebreaks', deciding: 'Deciding sets', from_set_down: 'From a set down', serving_for_set: 'Serving for the set', serving_for_match: 'Serving for the match', bagels: 'Bagel sets' };
  return Object.keys(cl || {}).filter(k => cl[k] && typeof cl[k] === 'object').map(k => {
    const x = cl[k], n = (x.w || 0) + (x.l || 0);
    const diff = isNum(x.exp) ? (x.w || 0) - x.exp : null;
    return { k: k, label: L[k] || k.replace(/_/g, ' '), w: x.w, l: x.l, n: n, exp: x.exp, diff: diff, rate: n ? (x.w || 0) / n : null, xrate: n && isNum(x.exp) ? x.exp / n : null };
  });
}
function drawClutch(c, p, metrics) {
  const host = document.getElementById('pp-clutch');
  if (!host) return;
  const rows = clutchRows(c.clutch);
  const meta = K.metaOf(metrics);
  const extra = ['tb_pct', 'tb_over', 'dec_pct', 'dec_over', 'fsd_pct', 'fsd_over', 'close_sets_pct', 'bagels_for', 'tb_win', 'deciding_win', 'from_set_down', 'bagels'].filter(k => meta[k] && p && isNum((p.values || {})[k]));
  if (!rows.length && !extra.length) { host.innerHTML = K.muted('No clutch record in the career file.'); return; }
  const max = Math.max.apply(null, rows.map(r => Math.abs(r.diff || 0)).concat([1]));
  host.innerHTML = (rows.length ? '<div class="af-clutch">' + rows.map(r => {
    const w = Math.min(50, 50 * Math.abs(r.diff || 0) / max);
    return '<div class="af-cl-row"><div class="af-cl-lab"><strong>' + K.esc(r.label) + '</strong><span>' + K.rec(r.w, r.l) + (r.n ? ' · ' + K.pct(r.rate, 0) : '') + (isNum(r.xrate) ? ' v ' + K.pct(r.xrate, 0) + ' expected' : '') + '</span></div>' +
      '<div class="af-cl-bar" title="Wins minus expected wins"><span class="' + ((r.diff || 0) >= 0 ? 'pos' : 'neg') + '" style="width:' + w + '%"></span></div>' +
      '<div class="af-cl-v ' + ((r.diff || 0) > 0.05 ? 'pg-up' : (r.diff || 0) < -0.05 ? 'pg-down' : '') + '">' + K.signed(r.diff, 1) + '</div></div>';
  }).join('') + '</div>' : '') +
    (extra.length ? '<div class="af-kv">' + extra.map(k => '<div class="af-kv-i"><span>' + K.esc(meta[k].label) + '</span><strong>' + K.fmt(meta[k], p.values[k]) + ' ' + K.pill((p.pct || {})[k]) + '</strong></div>').join('') + '</div>' : '') +
    '<div class="pg-note">Expected wins are the sum of our chances for those sets or matches, so a positive figure is more won than the ratings predicted. Small samples swing: a tiebreak record of 10 has a standard deviation of about 1.6 wins.</div>';
}

function cutoff(win) { if (win === 'all') return ''; const d = new Date(); d.setFullYear(d.getFullYear() - Number(win)); return d.toISOString().slice(0, 10); }

function drawEloHistory(T, c, root) {
  const rows = (c.elo || []).filter(r => Array.isArray(r) && r[0]);
  const V = TA.v2;
  const draw = win => {
    const node = document.getElementById('pp-elo');
    if (!node) return;
    const cut = cutoff(win);
    const rs = rows.filter(r => String(r[0]) >= cut);
    if (!rs.length) { node.innerHTML = K.muted('No Elo history in the career file.'); return; }
    V.lines(node, { series: [['Overall', 1, 'all', 3], ['Hard', 2, 'hard', 1.6], ['Clay', 3, 'clay', 1.6], ['Grass', 4, 'grass', 1.6]].map(x => ({
      name: x[0], rows: rs.map(r => [r[0], r[x[1]]]), color: x[2] === 'all' ? V.signal() : V.SURF_HEX[x[2]], width: x[3] })),
      yName: 'Elo rating', step: 'end', yFmt: v => String(Math.round(v)), label: 'Elo history, overall and by surface' });
  };
  draw('all');
  K.wireToggle(root, 'pp-elo-win', draw);
}

/* career serve_return rows: [date, surface, serve, return, hold, break, serve_se, return_se] */
function drawServeReturn(c, root) {
  const rows = (c.serve_return || []).filter(r => Array.isArray(r) && r[0]);
  const note = document.getElementById('pp-sr-note');
  const V = TA.v2;
  const KIND = { serve: [2, 6, 'Serve rating (log-odds of holding)'], 'return': [3, 7, 'Return rating (log-odds of breaking)'], hold: [4, null, 'Hold % against an average returner'], brk: [5, null, 'Break % against an average server'] };
  const draw = kind => {
    const node = document.getElementById('pp-sr');
    if (!node) return;
    if (!rows.length) { node.innerHTML = K.muted('No serve/return path in the career file.'); return; }
    const k = KIND[kind] || KIND.serve;
    const surfs = Array.from(new Set(rows.map(r => r[1]))).sort((a, b) => (a === 'all' ? -1 : b === 'all' ? 1 : K.SURFACES.indexOf(a) - K.SURFACES.indexOf(b)));
    const pct = kind === 'hold' || kind === 'brk';
    V.lines(node, { series: surfs.map(sf => {
      const rs = rows.filter(r => r[1] === sf);
      return { name: K.SURF_LABEL[sf] || sf, rows: rs.map(r => [r[0], r[k[0]]]), color: sf === 'all' ? V.signal() : V.SURF_HEX[sf], width: sf === 'all' ? 3 : 1.8,
        band: k[1] !== null ? rs.map(r => [r[0], isNum(r[k[1]]) ? r[k[0]] - r[k[1]] : null, isNum(r[k[1]]) ? r[k[0]] + r[k[1]] : null]) : null };
    }), yName: k[2], yFmt: pct ? (v => Math.round(v * 100) + '%') : (v => Number(v).toFixed(2)), label: k[2] + ' over time' });
    if (note) note.innerHTML = pct ? 'Hold and break against the average tour-level opponent on that surface, from the same fits.' :
      'Ratings are on the log-odds scale of holding serve: a serve rating 0.3 higher raises the log-odds of holding by 0.3 against any returner. Fitted by penalised maximum likelihood over every set score, matches weighted by a half-life (see the <a href="#/methodology/serve-return">methodology</a>). The shaded band is ±1 standard error from the curvature of the fit.';
  };
  draw('serve');
  K.wireToggle(root, 'pp-sr-kind', draw);
}

function drawRanks(c) {
  const node = document.getElementById('pp-rank');
  if (!node) return;
  const rs = (c.ranks || []).filter(r => Array.isArray(r) && isNum(r[1]) && TA.parseDate(r[0]));
  if (!rs.length) { node.innerHTML = K.muted('No ranking history.'); return; }
  /* a spell of more than nine weeks between ranking dates is drawn as a gap, not a line across it; the line holds
     each ranking until the next one (steps) */
  const pts = [];
  rs.forEach((r, i) => {
    const t = TA.parseDate(r[0]).getTime();
    if (i && t - TA.parseDate(rs[i - 1][0]).getTime() > 63 * 864e5) pts.push([t - 864e5, null]);
    pts.push([t, Number(r[1])]);
  });
  const worst = Math.max.apply(null, rs.map(r => Number(r[1])));
  QKC.mount(node, T2 => {
    const ya = QKC.axis(T2, { name: 'Ranking (log scale)', nameAlign: 'left', fmt: v => String(Math.round(v)) });
    ya.type = 'log'; ya.logBase = 10; ya.inverse = true; ya.nameLocation = 'start'; ya.nameGap = 14; ya.min = 1; ya.max = Math.pow(10, Math.ceil(Math.log(Math.max(10, worst)) / Math.LN10));
    return {
      grid: { left: 8, right: 16, top: 30, bottom: 30, containLabel: true },
      xAxis: QKC.axis(T2, { type: 'time', split: false, line: true, name: 'Date', nameLocation: 'middle', nameGap: 26 }),
      yAxis: ya,
      tooltip: QKC.tooltip(T2, { trigger: 'axis', formatter: ps => { const q = (ps || [])[0]; return q && isNum(q.value[1]) ? K.esc(K.fmtDate(new Date(q.value[0]).toISOString().slice(0, 10), { weekday: false })) + ': No. ' + q.value[1] : ''; } }),
      series: [{ type: 'line', step: 'end', showSymbol: false, connectNulls: false, data: pts, lineStyle: { color: T2.model, width: 2 }, itemStyle: { color: T2.model } }]
    };
  }, { label: 'Ranking history' });
}

function drawDefend(T, c, ranks, pid) {
  const host = document.getElementById('pp-defend');
  if (!host) return;
  const list = (Array.isArray(c.to_defend) && c.to_defend.length ? c.to_defend : (((ranks || {}).to_defend || {})[pid] || [])).filter(r => Array.isArray(r));
  if (!list.length) { host.innerHTML = K.muted('Nothing to defend in the coming weeks, or no ranking file.'); return; }
  const tot = list.reduce((s, r) => s + (Number(r[2]) || 0), 0);
  const max = Math.max.apply(null, list.map(r => Number(r[2]) || 0).concat([1]));
  host.innerHTML = '<div class="af-kv"><div class="af-kv-i"><span>Total to defend</span><strong>' + K.int(tot) + '</strong></div><div class="af-kv-i"><span>Events</span><strong>' + list.length + '</strong></div></div>' +
    K.table([{ label: 'Week' }, { label: 'Event' }, { label: 'Points', align: 'right' }, { label: '', sortable: false }],
      list.slice().sort((a, b) => String(a[1]).localeCompare(String(b[1]))).map(r => [{ v: r[1], html: K.esc(K.fmtDate(r[1], { year: false, weekday: false })) }, { v: K.eventName(T, r[0]), html: K.eventLink(T, r[0]) },
        { v: r[2], html: K.int(r[2]) }, { v: r[2], html: '<span class="af-hbar"><span style="width:' + (100 * (Number(r[2]) || 0) / max).toFixed(1) + '%"></span></span>' }]), { compact: true });
}

function drawSeasons(c) {
  const host = document.getElementById('pp-seasons');
  if (!host) return;
  const ss = (c.seasons || []).slice().sort((a, b) => b.year - a.year);
  if (!ss.length) { host.innerHTML = K.muted('No season rows in the career file.'); return; }
  const bs = (s, k) => { let x = (s.by_surface || {})[k]; if (Array.isArray(x)) x = { w: x[0], l: x[1] }; return x ? { v: K.recPct(x.w, x.l), html: K.rec(x.w, x.l) } : { v: -1, html: '<span class="muted-inline">—</span>' }; };
  host.innerHTML = K.table([{ label: 'Year' }, { label: 'W–L', align: 'right' }, { label: 'Win %', align: 'right' }, { label: 'Titles', align: 'right' }, { label: 'Finals', align: 'right' },
    { label: 'Hard', align: 'right' }, { label: 'Clay', align: 'right' }, { label: 'Grass', align: 'right' }, { label: 'Hold %', align: 'right' }, { label: 'Break %', align: 'right' }, { label: 'Elo (end)', align: 'right' }],
    ss.map(s => [s.year, { v: s.w, html: K.rec(s.w, s.l) }, { v: K.recPct(s.w, s.l), html: K.pct(K.recPct(s.w, s.l), 0) }, s.titles || 0, s.finals || 0, bs(s, 'hard'), bs(s, 'clay'), bs(s, 'grass'),
      { v: s.hold, html: K.fmtV(s.hold, 'pct') }, { v: s.brk, html: K.fmtV(s.brk, 'pct') }, { v: s.elo_end, html: K.num(s.elo_end, 0) }]), { compact: true });
  K.sortable(host);
}

function drawResults(T, c, root) {
  const host = document.getElementById('pp-results'), chart = document.getElementById('pp-res-chart'), sel = document.getElementById('pp-res-surf');
  const all = (c.results || []).filter(r => r && r.date).slice().sort((a, b) => String(b.date).localeCompare(String(a.date)));
  /* every level (qualifying, Challengers / WTA 125s): [date, event, round, surface, opp, won, score]; not forecast */
  const every = (c.results_all || []).filter(r => Array.isArray(r) && r[0]).map(r => ({ date: r[0], event: r[1], round: r[2], surface: r[3], opp: r[4], won: !!r[5], score: r[6] }))
    .sort((a, b) => String(b.date).localeCompare(String(a.date)));
  let level = 'tour', showAll = false;
  const lvl = e => { const x = K.event(T, e); return x && x.level ? (K.LEVEL_LABEL[x.level] || x.level) : (T === 'atp' ? 'Challenger or other' : 'Other'); };
  const draw = () => {
    const sf = sel ? sel.value : '';
    const sub = document.getElementById('pp-res-sub');
    if (level === 'all') {
      const rs = every.filter(r => !sf || r.surface === sf);
      chart.style.display = 'none';
      if (sub) sub.innerHTML = rs.length + ' matches at every level this season and last, qualifying and ' + (T === 'atp' ? 'Challengers' : 'WTA 125s') + ' included. They feed the ratings; only tour-level matches get our forecast.';
      host.innerHTML = rs.length ? K.table([{ label: 'Date' }, { label: 'Event' }, { label: 'Level' }, { label: 'Rd' }, { label: 'Opponent' }, { label: 'Result' }, { label: 'Score' }],
        rs.slice(0, showAll ? rs.length : 40).map(r => [{ v: r.date, html: K.esc(K.fmtDate(r.date, { weekday: false })) }, { v: K.eventName(T, r.event), html: K.surfChip(r.surface) + ' ' + K.eventLink(T, r.event) },
          K.esc(lvl(r.event)), { v: K.ROUND_ORDER.indexOf(r.round), html: K.esc(r.round || '') }, { v: K.name(T, r.opp), html: K.playerLink(T, r.opp) },
          { v: r.won ? 1 : 0, html: r.won ? '<span class="af-w">W</span>' : '<span class="af-l">L</span>' }, { v: r.score || '', html: '<span class="pg-mono">' + K.esc(r.score || '') + '</span>' }]), { compact: true, sticky: true }) +
        (rs.length > 40 && !showAll ? '<div class="pg-note"><button type="button" class="af-more" id="pp-res-more">Show all ' + rs.length + ' matches</button></div>' : '')
        : K.muted('No results at any level in the career file' + (sf ? ' on ' + sf : '') + '.');
      K.sortable(host);
      const more = document.getElementById('pp-res-more');
      if (more) more.onclick = () => { showAll = true; draw(); };
      return;
    }
    const rs = all.filter(r => !sf || r.surface === sf);
    if (!rs.length) { host.innerHTML = K.muted('No results in the career file' + (sf ? ' on ' + sf : '') + '.'); chart.style.display = 'none'; return; }
    chart.style.display = '';
    const withP = rs.filter(r => isNum(r.p_pre));
    const wins = withP.filter(r => r.won).length, exp = withP.reduce((s, r) => s + r.p_pre, 0);
    if (sub) sub.innerHTML = rs.length + ' tour-level matches (' + K.esc(String(rs[rs.length - 1].date).slice(0, 4)) + '–' + K.esc(String(rs[0].date).slice(0, 4)) + ')' +
      (withP.length ? ' · won ' + wins + ' against ' + K.num(exp, 1) + ' expected from our pre-match chances (<span class="' + (wins - exp >= 0 ? 'pg-up' : 'pg-down') + '">' + K.signed(wins - exp, 1) + '</span>)' : '');
    // wins minus expected, cumulative (oldest first)
    const asc = withP.slice().reverse();
    let cum = 0;
    const ys = asc.map(r => (cum += (r.won ? 1 : 0) - r.p_pre));
    TA.v2.lines(chart, { series: [{ name: 'Wins minus expected', rows: asc.map((r, k) => [r.date, ys[k]]), color: TA.v2.signal(), area: true }], yName: 'Wins minus expected, running total',
      yFmt: v => K.signed(v, 1), ref: { y: 0 }, yScale: true, label: 'Wins against our pre-match chances, running total' });
    host.innerHTML = K.table([{ label: 'Date' }, { label: 'Event' }, { label: 'Rd' }, { label: 'Opponent' }, { label: 'Result' }, { label: 'Score' }, { label: 'Our chance', align: 'right', title: 'Our pre-match chance for this player' },
      { label: 'Surprise', align: 'right', title: 'Outcome minus our chance: +0.8 is a win we gave 20%' }],
      rs.slice(0, showAll ? rs.length : 40).map(r => ({ _href: r.match ? K.matchHref(T, r.match) : undefined, cells: [
        { v: r.date, html: K.esc(K.fmtDate(r.date, { weekday: false })) },
        { v: K.eventName(T, r.event), html: K.surfChip(r.surface) + ' ' + K.eventLink(T, r.event) },
        { v: K.ROUND_ORDER.indexOf(r.round), html: K.esc(r.round || '') },
        { v: K.name(T, r.opp), html: K.playerLink(T, r.opp) },
        { v: r.won ? 1 : 0, html: r.won ? '<span class="af-w">W</span>' : '<span class="af-l">L</span>' },
        { v: r.score || '', html: '<span class="pg-mono">' + K.esc(r.score || '') + '</span>' },
        { v: r.p_pre, html: K.pct(r.p_pre, 0) },
        { v: isNum(r.p_pre) ? (r.won ? 1 : 0) - r.p_pre : null, html: isNum(r.p_pre) ? '<span class="' + (r.won ? 'pg-up' : 'pg-down') + '">' + K.signed((r.won ? 1 : 0) - r.p_pre, 2) + '</span>' : '—' }
      ] })), { compact: true, sticky: true }) +
      (rs.length > 40 && !showAll ? '<div class="pg-note"><button type="button" class="af-more" id="pp-res-more">Show all ' + rs.length + ' matches</button></div>' : '');
    K.sortable(host);
    const more = document.getElementById('pp-res-more');
    if (more) more.onclick = () => { showAll = true; draw(); };
  };
  if (sel) sel.onchange = draw;
  K.wireToggle(root, 'pp-res-lv', v => { level = v; showAll = false; draw(); });
  draw();
}

function drawSplits(T, c, root) {
  const S = c.splits || {};
  const order = { surface: ['hard', 'clay', 'grass', 'carpet'], level: ['slam', 'finals', 'm1000', '500', '250', 'other'], round: K.ROUND_ORDER, opp_band: ['top10', '11-20', '21-50', '51-100', '100+'] };
  const lab = (kind, k) => (kind === 'surface' ? K.SURF_LABEL[k] || k : kind === 'level' ? K.LEVEL_LABEL[k] || k : kind === 'round' ? (K.ROUND_LABEL[k] || k) : kind === 'opp_band' ? (k === 'top10' ? 'Top 10' : k === '100+' ? 'Outside the top 100' : 'Ranked ' + k) : k);
  const draw = kind => {
    const host = document.getElementById('pp-splits');
    if (!host) return;
    const d = S[kind] || {};
    const keys = Object.keys(d);
    if (!keys.length) { host.innerHTML = K.muted('No ' + kind.replace('_', ' ') + ' split in the career file.'); return; }
    const ord = order[kind] || [];
    keys.sort((a, b) => { const ia = ord.indexOf(a), ib = ord.indexOf(b); return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b); });
    const norm = x => (Array.isArray(x) ? { w: x[0], l: x[1], exp: x[2] } : (x || {}));
    const rows = keys.map(k => {
      const x = norm(d[k]), n = (x.w || 0) + (x.l || 0), diff = isNum(x.exp) ? (x.w || 0) - x.exp : null;
      return [{ v: ord.indexOf(k), html: kind === 'surface' ? K.surfChip(k) : K.esc(lab(kind, k)) }, n, { v: x.w, html: K.rec(x.w, x.l) }, { v: K.recPct(x.w, x.l), html: K.pct(K.recPct(x.w, x.l), 1) },
        { v: x.exp, html: K.num(x.exp, 1) }, { v: diff, html: diff === null ? '—' : '<span class="' + (diff > 0.05 ? 'pg-up' : diff < -0.05 ? 'pg-down' : '') + '">' + K.signed(diff, 1) + '</span>' },
        { v: isNum(x.hold) ? x.hold : null, html: K.fmtV(x.hold, 'pct') }, { v: isNum(x.brk) ? x.brk : null, html: K.fmtV(x.brk, 'pct') }];
    });
    const hasHB = keys.some(k => isNum(norm(d[k]).hold));
    const cols = [{ label: kind === 'opp_band' ? 'Opponent' : K.SURF_LABEL[kind] ? 'Surface' : kind.charAt(0).toUpperCase() + kind.slice(1).replace('_', ' ') }, { label: 'Matches', align: 'right' }, { label: 'W–L', align: 'right' }, { label: 'Win %', align: 'right' },
      { label: 'Expected W', align: 'right' }, { label: 'Over expected', align: 'right' }].concat(hasHB ? [{ label: 'Hold %', align: 'right' }, { label: 'Break %', align: 'right' }] : []);
    host.innerHTML = K.table(cols, rows.map(r => (hasHB ? r : r.slice(0, 6))), { compact: true });
    K.sortable(host);
  };
  draw('surface');
  K.wireToggle(root, 'pp-split', draw);
}

// ── style (Match Charting Project) ─────────────────────────────────────────

let STYLE_MED = {};
function styleMedians(T) {
  if (STYLE_MED[T]) return Promise.resolve(STYLE_MED[T]);
  return TA.load(T + '/style.json').then(d => {
    const rows = Object.keys(d || {}).filter(k => k.charAt(0) !== '_' && d[k] && (d[k].matches || 0) >= 10).map(k => d[k]);
    const get = (o, path) => path.split('.').reduce((x, k) => (x && x[k] !== undefined ? x[k] : null), o);
    const med = path => K.median(rows.map(r => get(r, path)));
    STYLE_MED[T] = { n: rows.length, med: med, meta: (d || {})._meta || null };
    return STYLE_MED[T];
  });
}
K.styleMedians = styleMedians;
const STYLE_ROWS = [
  ['Serve', 'serve.first_in', '1st serve in', 'pct'], ['Serve', 'serve.first_won', '1st serve won', 'pct'], ['Serve', 'serve.second_won', '2nd serve won', 'pct'],
  ['Serve', 'serve.ace_rate', 'Aces per serve point', 'pct'], ['Serve', 'serve.df_rate', 'Double faults per serve point', 'pct', true], ['Serve', 'serve.unret_rate', 'Serves unreturned', 'pct'],
  ['Serve', 'serve.snv_rate', 'Serve and volley', 'pct'], ['Return', 'return.won', 'Return points won', 'pct'], ['Return', 'return.depth.deep', 'Deep returns', 'pct'], ['Return', 'return.fh_share', 'Forehand returns', 'pct'],
  ['Rally', 'rally.mean_len', 'Mean rally length (shots)', '2'], ['Shots', 'shots.winners_per_pt', 'Winners per point', '3'], ['Shots', 'shots.ue_per_pt', 'Unforced errors per point', '3', true],
  ['Shots', 'shots.fh_winners_per_pt', 'Forehand winners per point', '3'], ['Shots', 'shots.bh_winners_per_pt', 'Backhand winners per point', '3'], ['Shots', 'shots.induced_fe_per_pt', 'Forced errors induced per point', '3'],
  ['Shots', 'shots.winner_ue_ratio', 'Winners per unforced error', '2'], ['Shots', 'shots.fh_share', 'Forehand share of groundstrokes', 'pct'], ['Net', 'net.rate', 'Points at the net', 'pct'], ['Net', 'net.won', 'Net points won', 'pct'],
  ['Shots', 'aggression', 'Aggression ((winners + UE) / shots)', '3']
];
K.STYLE_ROWS = STYLE_ROWS;
/* The style block for one profile: serve direction by side, rally lengths, a table v the tour median. host is an element. */
K.styleBlock = (host, T, st, opts) => {
  const o = opts || {};
  if (!st) { host.innerHTML = K.muted(o.empty || 'No charted matches for this player in the Match Charting Project.'); return Promise.resolve(); }
  const id = 'st' + Math.random().toString(36).slice(2, 8);
  host.innerHTML = '<div class="af-kv">' + [['Charted matches', K.int(st.matches)], ['Points', K.int(st.points)], ['Points won', K.fmtV(st.points_won, 'pct')], ['Hand', st.hand === 'L' ? 'Left' : st.hand === 'R' ? 'Right' : '—']]
    .map(x => '<div class="af-kv-i"><span>' + x[0] + '</span><strong>' + x[1] + '</strong></div>').join('') + '</div>' +
    '<div class="' + (o.stack ? '' : 'grid-2 af-style-grid') + '"><div><div class="cmp-group-head">Serve direction by court and serve</div><div id="' + id + '-dir" style="height:' + (o.stack ? 230 : 260) + 'px"></div></div>' +
    '<div><div class="cmp-group-head">Rally length: share of points and points won</div><div id="' + id + '-rally" style="height:' + (o.stack ? 230 : 260) + 'px"></div></div></div>' +
    '<div class="cmp-group-head">Profile against the median charted player</div><div id="' + id + '-tab"></div>' +
    '<div class="pg-note af-licence">Shot-by-shot data: <a href="https://github.com/JeffSackmann/tennis_MatchChartingProject" target="_blank" rel="noopener">the Match Charting Project</a> (Jeff Sackmann and contributors, Tennis Abstract), licensed <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" target="_blank" rel="noopener">CC BY-NC-SA 4.0</a>. These derived tables are shared under the same licence, non-commercially. Charted matches are volunteers\' picks, weighted to big matches and well-known players, so a profile is not a random sample of a career.</div>';
  const dir = ((st.serve || {}).direction) || {};
  const sides = [['first_deuce', '1st, deuce'], ['first_ad', '1st, ad'], ['second_deuce', '2nd, deuce'], ['second_ad', '2nd, ad']].filter(s => dir[s[0]]);
  if (sides.length) {
    const dn = document.getElementById(id + '-dir');
    dn.classList.add('qk-chart');
    QKC.bar(dn, { cats: sides.map(x => x[1] + ' (' + K.int(dir[x[0]].n) + ')'), horizontal: true, stack: true, max: 1, min: 0, fmt: v => Math.round(v * 100) + '%', legend: true, labelWidth: 120,
      series: [['wide', 'Wide', '#5b8def'], ['body', 'Body', '#8b929f'], ['t', 'T', '#f08a3c']].map(z => ({ name: z[1], color: z[2], data: sides.map(x => dir[x[0]][z[0]] || 0) })),
      valName: 'Share of serves', catName: 'Serve and court', label: 'Serve direction' });
  } else document.getElementById(id + '-dir').innerHTML = K.muted('No serve direction.');
  const ra = st.rally || {};
  const bk = Object.keys(ra.dist || {});
  if (bk.length) {
    const rn = document.getElementById(id + '-rally');
    rn.classList.add('qk-chart');
    QKC.mount(rn, Tk => {
      const xa = QKC.axis(Tk, { type: 'category', data: bk, split: false, line: true });
      QKC.nameAxis(xa, 'Shots in the rally', 'bottom');
      const y1 = QKC.axis(Tk, { fmt: v => Math.round(v * 100) + '%', min: 0 });
      QKC.nameAxis(y1, 'Share of points', 'side');
      const y2 = QKC.axis(Tk, { fmt: v => Math.round(v * 100) + '%', min: 0.3, max: 0.7, split: false, position: 'right' });
      y2.name = 'Points won'; y2.nameLocation = 'end'; y2.nameGap = 8;
      return { grid: { left: 8, right: 8, top: 52, bottom: 34, containLabel: true }, xAxis: xa, yAxis: [y1, y2],
        legend: { top: 0, left: 0, textStyle: { color: Tk.ink2 }, itemWidth: 12, itemHeight: 8 },
        tooltip: QKC.tooltip(Tk, { trigger: 'axis', formatter: ps => '<b>' + esc(ps[0].axisValue) + ' shots</b>' + ps.map(q => QKC.tipRow(q.color, q.seriesName, Math.round(q.value * 100) + '%')).join('') }),
        series: [{ type: 'bar', name: 'Share of points', data: bk.map(k => ra.dist[k]), barMaxWidth: 34, itemStyle: { color: QKC.hexA('#5b8def', 0.8), borderRadius: [3, 3, 0, 0] } },
          { type: 'line', name: 'Points won', yAxisIndex: 1, data: bk.map(k => (ra.won || {})[k]), lineStyle: { color: Tk.model, width: 2 }, itemStyle: { color: Tk.model }, symbolSize: 6 }] };
    }, { label: 'Rally length' });
  } else document.getElementById(id + '-rally').innerHTML = K.muted('No rally lengths.');
  return styleMedians(T).then(M => {
    const tab = document.getElementById(id + '-tab');
    if (!tab) return;
    const get = path => path.split('.').reduce((x, k) => (x && x[k] !== undefined ? x[k] : null), st);
    tab.innerHTML = K.table([{ label: 'Group' }, { label: 'Metric' }, { label: 'Player', align: 'right' }, { label: 'Median', align: 'right' }, { label: 'Difference', align: 'right' }],
      STYLE_ROWS.filter(r => isNum(get(r[1]))).map(r => {
        const v = get(r[1]), m = M.med(r[1]), d = isNum(m) ? v - m : null;
        const good = d === null ? '' : ((r[4] ? -d : d) > 0 ? 'pg-up' : (r[4] ? -d : d) < 0 ? 'pg-down' : '');
        return [{ v: r[0], html: '<span class="muted-inline">' + r[0] + '</span>' }, r[2] + (r[4] ? ' ↓' : ''), { v: v, html: K.fmtV(v, r[3]) }, { v: m, html: K.fmtV(m, r[3]) },
          { v: d, html: d === null ? '—' : '<span class="' + (/^(Rally|Shots)$/.test(r[0]) && !r[4] && r[1] !== 'shots.winners_per_pt' ? '' : good) + '">' + (r[3] === 'pct' ? K.signed(100 * d, 1) + ' pts' : K.signed(d, r[3] === '2' ? 2 : 3)) + '</span>' }];
      }), { compact: true }) + '<div class="pg-note">Median over the ' + M.n + ' charted ' + K.TN(T) + ' players with at least 10 charted matches. Green and red mark better and worse where better is clear (serve, return, errors, net success); style choices such as rally length are left uncoloured.</div>';
  });
};
function drawStyle(T, pid, c) {
  const host = document.getElementById('pp-style');
  if (!host) return;
  K.styleBlock(host, T, c.style || null);
}

function drawH2H(T, pid, c) {
  const host = document.getElementById('pp-h2h');
  if (!host) return;
  const list = (c.h2h || []).filter(r => Array.isArray(r) && r[0]);
  if (!list.length) { host.innerHTML = K.muted('No head-to-head records in the career file.'); return; }
  host.innerHTML = K.table([{ label: 'Opponent' }, { label: 'Matches', align: 'right' }, { label: 'W–L', align: 'right' }, { label: 'Win %', align: 'right' }, { label: '', sortable: false }, { label: 'Last met', align: 'right' }, { label: '', sortable: false }],
    list.map(r => {
      const n = (r[1] || 0) + (r[2] || 0), w = n ? r[1] / n : null;
      return { _href: K.h2hHref(T, pid, r[0]), cells: [{ v: K.name(T, r[0]), html: K.playerLink(T, r[0]) + ' ' + K.ctry(K.country(T, r[0])) }, n, { v: r[1], html: K.rec(r[1], r[2]) }, { v: w, html: K.pct(w, 0) },
        { v: w, html: '<span class="af-wl"><span class="w" style="width:' + (100 * (w || 0)).toFixed(0) + '%"></span></span>' }, { v: r[3], html: K.esc(K.fmtDate(r[3], { weekday: false })) },
        { v: '', html: '<a href="' + K.h2hHref(T, pid, r[0]) + '">H2H →</a>' }] };
    }), { compact: true });
  K.sortable(host);
}

if (typeof TA.route === 'function') {
  TA.route('players', renderPlayers);
  TA.route('player', renderPlayer);
}
})(window.TA || (window.TA = {}));
