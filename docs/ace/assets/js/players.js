/* The Quant Ace — players: the shared kit for builder F's pages (TA.fk), the catalogue
 * (#/<T>/players) and the player page (#/<T>/player/<pid>).
 *
 * TA.fk is defined here and read lazily at render time by elo.js, h2h.js, lab.js, compare.js,
 * calibration.js and docs.js (const K = () => TA.fk), so script order does not matter as long
 * as this file is loaded. It leans on the core (core.js: TA.tableHTML, TA.sortable, TA.plot,
 * TA.layout, TA.pctColor, TA.statTile, TA.load) where those exist and falls back to local
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

// ── charts ─────────────────────────────────────────────────────────────────

const DARK = {
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: '#8b949e', family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', size: 11 },
  xaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  yaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  margin: { l: 60, r: 20, t: 30, b: 50 }, hovermode: 'closest',
  hoverlabel: { bgcolor: '#161b22', bordercolor: '#30363d', font: { color: '#e6edf3', size: 12 } }, showlegend: false
};
K.layout = extra => {
  if (typeof TA.layout === 'function') return TA.layout(extra);
  const out = Object.assign(JSON.parse(JSON.stringify(DARK)), extra || {});
  Object.keys(extra || {}).forEach(k => { if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK.xaxis, extra[k]); });
  if (extra && extra.font) out.font = Object.assign({}, DARK.font, extra.font);
  return out;
};
K.plot = (el, traces, lay, conf) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (typeof TA.plot === 'function') return TA.plot(node, traces, lay, conf);
  if (typeof Plotly === 'undefined') { node.innerHTML = K.muted('The chart library did not load. The tables carry the same data.'); return null; }
  try {
    const p = Plotly.newPlot(node, traces, lay, Object.assign({ displayModeBar: false, responsive: true }, conf || {}));
    if (typeof TA.onLeave === 'function') TA.onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    return p;
  } catch (err) { node.innerHTML = K.muted('The chart could not be drawn.'); return null; }
};
K.legendTop = () => ({ showlegend: true, legend: { orientation: 'h', y: 1.14, x: 0, font: { color: K.C.text2, size: 10 } } });
K.radar = (el, axes, rows) => {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return;
  axes = axes.filter(a => rows.some(r => r && r.pct && isNum(r.pct[a.key])));
  const usable = rows.filter(r => r && r.pct && axes.some(a => isNum(r.pct[a.key])));
  if (!usable.length || axes.length < 3) { node.innerHTML = K.muted('No percentiles to draw yet.'); return; }
  const narrow = (node.clientWidth || 600) < 520;
  const wrap = s => (narrow && s.length > 12 ? s.replace(/^(.{6,14}?)\s+/, '$1<br>') : s);
  const ax = axes.map(a => Object.assign({}, a, { label: wrap(a.label) }));
  K.plot(node, usable.map((r, i) => ({
    type: 'scatterpolar', fill: 'toself', name: r.name,
    r: ax.map(a => (isNum(r.pct[a.key]) ? r.pct[a.key] : 0)).concat([isNum(r.pct[ax[0].key]) ? r.pct[ax[0].key] : 0]),
    theta: ax.map(a => a.label).concat([ax[0].label]),
    line: { color: r.colour || (i ? K.CB : K.CA), width: 2 }, fillcolor: K.alpha(r.colour || (i ? K.CB : K.CA), 0.18),
    hovertemplate: '%{theta}: %{r:.0f}th percentile<extra>' + K.esc(r.name) + '</extra>'
  })), K.layout({
    showlegend: usable.length > 1, legend: { orientation: 'h', y: -0.1, font: { color: K.C.text2 } },
    polar: { bgcolor: 'rgba(0,0,0,0)', radialaxis: { visible: true, range: [0, 100], gridcolor: '#21262d', tickfont: { size: 9 }, tickvals: [25, 50, 75, 100] }, angularaxis: { gridcolor: '#21262d', tickfont: { size: narrow ? 8 : 10 } } },
    margin: narrow ? { l: 46, r: 46, t: 24, b: 40 } : { l: 70, r: 70, t: 24, b: 40 }
  }));
};
/* Line with a ±se band: rows [{x, y, se, text}] -> traces. */
K.band = (rows, colour, name, opts) => {
  const o = opts || {};
  const x = rows.map(r => r.x), out = [];
  if (o.band !== false && rows.some(r => isNum(r.se))) {
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.y + (r.se || 0)), line: { width: 0, shape: o.shape || 'linear' }, hoverinfo: 'skip', showlegend: false, xaxis: o.xaxis, yaxis: o.yaxis });
    out.push({ type: 'scatter', mode: 'lines', x: x, y: rows.map(r => r.y - (r.se || 0)), line: { width: 0, shape: o.shape || 'linear' }, fill: 'tonexty', fillcolor: K.alpha(colour, 0.16), hoverinfo: 'skip', showlegend: false, xaxis: o.xaxis, yaxis: o.yaxis });
  }
  out.push({ type: 'scatter', mode: o.mode || 'lines', name: name, x: x, y: rows.map(r => r.y), text: rows.map(r => r.text || ''), customdata: rows.map(r => (isNum(r.se) ? r.se : 0)),
    line: { color: colour, width: o.width || 2, dash: o.dash || 'solid', shape: o.shape || 'linear' }, xaxis: o.xaxis, yaxis: o.yaxis,
    hovertemplate: o.hover || ('%{text} ' + K.esc(name) + ': %{y:+.2f} ± %{customdata:.2f}<extra></extra>') });
  return out;
};

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

const IDX_PREFS = ['elo', /^elo$/, 'win_pct', /win_?pct|^win$/, 'hold', /^hold/, 'brk', 'break', /^br(ea)?k/, 'serve_rating', /serve_?r/, 'return_rating', /return_?r/, 'tb_over', /tb.*(over|exp)/];
const RADAR_PREFS = ['hold', /^hold$/, 'brk', /^br(ea)?k$/, 'serve_rating', 'return_rating', 'win_pct', 'win_v_top20', 'win_top20', /top_?(10|20)/, 'tb_over', 'dec_over', 'dec_pct', 'deciding_win', /decid/, 'wins_over_exp', 'over_exp', /over_?exp/, 'elo_d90', /elo_d/, 'spw_real', 'rpw_real', 'first_won', 'second_won'];
let IDXS = { q: '', country: '', floor: null, surface: '', extra: '' };

function renderPlayers(el, params, state) {
  const T = K.T(params, state);
  el.innerHTML = '<div class="card"><div class="card-header">' + K.TN(T) + ' players <span class="card-sub" id="pl-sub">Loading…</span></div>' +
    '<div class="lab-controls af-controls">' +
    '<label>Search<input id="pl-q" class="pg-search" type="search" placeholder="player or country…"></label>' +
    '<label>Country<select id="pl-country"><option value="">All countries</option></select></label>' +
    '<label>Min matches <span id="pl-floor-v"></span><input id="pl-floor" type="range" min="0" max="60" step="1"></label>' +
    '<label>Surface<select id="pl-surf"><option value="">All surfaces (tour percentiles)</option><option value="hard">Hard</option><option value="clay">Clay</option><option value="grass">Grass</option></select></label>' +
    '<label>Add a column<select id="pl-extra"><option value="">—</option></select></label>' +
    '</div><div id="pl-table">' + K.muted('Loading…') + '</div><div class="pg-note" id="pl-note"></div></div>';
  return K.ready().then(() => Promise.all([TA.load(T + '/players.json'), K.loadNames(T)])).then(res => {
    if (!K.alive(el)) return;
    const cat = res[0];
    const $ = id => document.getElementById(id);
    if (!K.ok(cat) || !cat.players) { $('pl-table').innerHTML = K.notBuilt('The ' + K.TN(T) + ' player catalogue', cat); $('pl-sub').textContent = ''; return; }
    K.learnCat(T, cat);
    const P = cat.players, metrics = cat.metrics || [];
    const ids = Object.keys(P);
    const maxN = Math.max.apply(null, ids.map(id => P[id].matches || 0).concat([10]));
    $('pl-floor').max = String(maxN);
    const floor0 = isNum(cat.floor) ? cat.floor : cat.min_matches;
    if (IDXS.floor === null || IDXS.floor > maxN) IDXS.floor = isNum(floor0) ? Math.min(floor0, maxN) : Math.min(10, maxN);
    $('pl-floor').value = IDXS.floor; $('pl-floor-v').textContent = IDXS.floor;
    const ctry = {};
    ids.forEach(id => { const c = P[id].country; if (c) ctry[c] = (ctry[c] || 0) + 1; });
    $('pl-country').innerHTML = '<option value="">All countries</option>' + Object.keys(ctry).sort().map(c => '<option value="' + K.esc(c) + '"' + (c === IDXS.country ? ' selected' : '') + '>' + K.esc(c) + ' (' + ctry[c] + ')</option>').join('');
    $('pl-q').value = IDXS.q; $('pl-surf').value = IDXS.surface;
    $('pl-extra').innerHTML = '<option value="">—</option>' + K.groups(metrics).map(g => '<optgroup label="' + K.esc(g.name) + '">' + g.items.map(m => '<option value="' + K.esc(m.key) + '"' + (m.key === IDXS.extra ? ' selected' : '') + '>' + K.esc(m.label) + '</option>').join('') + '</optgroup>').join('');
    const heads = K.headline(metrics, IDX_PREFS, 7, true);
    const draw = () => drawIndex(T, cat, heads);
    let t = null;
    $('pl-q').oninput = e => { IDXS.q = e.target.value; clearTimeout(t); t = setTimeout(draw, 150); };
    $('pl-country').onchange = e => { IDXS.country = e.target.value; draw(); };
    $('pl-surf').onchange = e => { IDXS.surface = e.target.value; draw(); };
    $('pl-floor').oninput = e => { IDXS.floor = Number(e.target.value); $('pl-floor-v').textContent = IDXS.floor; };
    $('pl-floor').onchange = draw;
    $('pl-extra').onchange = e => { IDXS.extra = e.target.value; draw(); };
    draw();
    $('pl-note').innerHTML = 'Catalogue for ' + K.esc(cat.year || '') + ', tour-level singles. Pills are percentiles (100 = best; ↓ metrics are already flipped) against every qualified ' + K.TN(T) + ' player, or with a surface picked, against the players with enough matches on that surface (and only they are listed). ' +
      'Percentiles need ' + K.num(isNum(cat.floor) ? cat.floor : cat.min_matches, 0) + '+ matches' + (isNum(cat.surface_floor) ? ' (' + cat.surface_floor + '+ on a surface)' : '') + '; players below show raw values only. Serve and return figures marked inferred come from game and set scores; ' + (T === 'wta' ? 'the WTA rows also carry real point-level stats from the WTA API. ' : 'the ATP has no public point-level stats, so its serve and return figures are all inferred from scores. ') +
      'Headline columns: ' + heads.map(m => K.glossLink(m.key, K.esc(m.label))).join(' · ') + '. All ' + metrics.length + ' metrics are on every player page and in the <a href="' + K.href(T, 'lab') + '">lab</a>.';
  });
}

function drawIndex(T, cat, heads) {
  const P = cat.players, meta = K.metaOf(cat.metrics);
  const q = fold(IDXS.q.trim());
  const extra = IDXS.extra && meta[IDXS.extra] ? meta[IDXS.extra] : null;
  const cols = heads.concat(extra && heads.indexOf(extra) < 0 ? [extra] : []);
  const sf = IDXS.surface;
  const ids = Object.keys(P).filter(id => {
    const p = P[id];
    if ((p.matches || 0) < IDXS.floor) return false;
    if (IDXS.country && p.country !== IDXS.country) return false;
    if (sf && !((p.pct_surface || {})[sf])) return false;
    if (q && fold(String(p.name || '') + ' ' + (p.country || '')).indexOf(q) < 0) return false;
    return true;
  });
  const sortKey = (heads[0] || {}).key;
  ids.sort((a, b) => {
    const va = (P[a].values || {})[sortKey], vb = (P[b].values || {})[sortKey];
    return (isNum(vb) ? vb : -1e9) - (isNum(va) ? va : -1e9) || (P[b].matches || 0) - (P[a].matches || 0);
  });
  const src = p => (sf ? ((p.pct_surface || {})[sf] || {}) : (p.pct || {}));
  const rows = ids.map((id, i) => {
    const p = P[id];
    return { _href: K.playerHref(T, id), cells: [
      { v: i + 1, cls: 'pos-cell' },
      { v: p.name || id, html: K.playerLink(T, id, p.name) + (p.qualified === false ? ' <span class="pg-tag" title="Below the match floor: no percentiles">few matches</span>' : '') },
      { v: p.country || '', html: K.ctry(p.country) },
      { v: p.age, html: isNum(p.age) ? K.num(p.age, 0) : '—', align: 'right' },
      { v: isNum(p.rank) ? p.rank : 9999, html: isNum(p.rank) ? String(p.rank) : '—', align: 'right' },
      { v: p.matches || 0, html: String(p.matches || 0), align: 'right' }
    ].concat(cols.map(m => {
      const v = (sf && (p.values_surface || {})[sf] ? p.values_surface[sf] : (p.values || {}))[m.key], pc = src(p)[m.key];
      return { v: isNum(v) ? v : -1e9, html: '<span class="af-val">' + K.fmt(m, v) + '</span> ' + K.pill(pc), align: 'right' };
    })) };
  });
  const host = document.getElementById('pl-table');
  if (!host) return;
  host.innerHTML = rows.length ? K.table([{ label: '#', sortable: false }, { label: 'Player' }, { label: 'Ctry' }, { label: 'Age', align: 'right' }, { label: 'Rank', align: 'right' }, { label: 'Matches', align: 'right' }]
    .concat(cols.map(m => ({ label: K.shortLabel(m.label) + (m.lower ? ' ↓' : ''), align: 'right', title: (m.desc || m.label) + (m.lower ? ' (lower is better)' : '') }))), rows, { sticky: true, compact: true })
    : K.muted('No player matches these filters.');
  K.sortable(host);
  const sub = document.getElementById('pl-sub');
  if (sub) sub.textContent = ids.length + ' of ' + Object.keys(P).length + ' players · sorted by ' + ((heads[0] || {}).label || 'matches') + (sf ? ' · ' + K.SURF_LABEL[sf] + ' percentiles' : '') + '; click a header to sort, a row to open the player';
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
  return K.ready().then(() => Promise.all([
    TA.load(T + '/players/' + pid + '.json'), TA.load(T + '/players.json'), TA.load(T + '/elo.json'), TA.load(T + '/rankings.json'), TA.load(T + '/race.json'), K.loadNames(T)
  ])).then(res => {
    if (!K.alive(el)) return null;
    const career = K.ok(res[0]) ? res[0] : null;
    K.learnCat(T, res[1]);
    const years = Array.from(new Set(((career || {}).results || []).map(r => String(r.date || '').slice(0, 4)).filter(y => /^\d{4}$/.test(y))));
    return K.loadEvents(T, years).then(() => { if (K.alive(el)) drawPlayer(el, T, pid, career, res[0], res[1], res[2], res[3], res[4]); });
  });
}

function drawPlayer(el, T, pid, career, careerRaw, cat, elo, ranks, race) {
  const C = K.C;
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

  let h = '<div class="pg-head af-head"><div class="pg-num af-badge">' + K.esc(isNum(rank) ? '#' + rank : K.TN(T)) + '</div><div class="pg-body"><h2>' + K.esc(name) + '</h2>' +
    '<div class="pg-sub">' + K.ctry(country) + (c.hand ? '<span>' + (c.hand === 'L' ? 'Left-handed' : c.hand === 'R' ? 'Right-handed' : K.esc(c.hand)) + '</span>' : '') +
    (age !== null ? '<span>age ' + age + '</span>' : '') + (isNum(c.height) ? '<span>' + K.num(c.height, 0) + ' cm</span>' : '') +
    '<span class="chip">' + K.TN(T) + '</span>' + (p && p.qualified === false ? '<span class="chip warn">below the match floor: no percentiles</span>' : '') + '</div></div>' +
    '<div class="pg-links">' + (rival ? '<a href="' + K.compareHref(T, pid, rival) + '">Compare with ' + K.esc(K.surname(K.name(T, rival))) + ' →</a>' : '') +
    (h2hTop ? '<a href="' + K.h2hHref(T, pid, h2hTop) + '">H2H v ' + K.esc(K.surname(K.name(T, h2hTop))) + ' →</a>' : '') +
    '<a href="' + K.href(T, 'elo') + '">Elo →</a><a href="' + K.href(T, 'lab') + '">Lab →</a><a href="' + K.href(T, 'players') + '">All players →</a></div></div>';

  // Tiles.
  const surfE = eloCur ? K.SURFACES.map(s => '<span class="af-se" style="color:' + K.surfColour(s) + '">' + s.charAt(0).toUpperCase() + ' ' + K.num(eloCur[s], 0) + '</span>').join(' ') : '';
  const hold = isNum(val(K_.hold)) ? val(K_.hold) : lastSeason(c, 'hold'), brk = isNum(val(K_.brk)) ? val(K_.brk) : lastSeason(c, 'brk');
  const odds = c.odds || {};
  const fq = isNum(odds.finals_qual) ? odds.finals_qual : ((race || {}).finals_qual || {})[pid];
  const no1 = isNum(odds.year_end_no1) ? odds.year_end_no1 : ((race || {}).year_end_no1 || {})[pid];
  const finalsName = T === 'wta' ? 'WTA Finals' : 'ATP Finals';
  h += '<div class="kpi-grid af-tiles">' + [
    K.tile('Elo', K.num(eloCur ? eloCur.all : val(K_.elo), 0), eloCur && isNum(eloCur.rank) ? 'No. ' + eloCur.rank + ' by Elo · ' + K.int(eloCur.n) + ' matches rated' : ''),
    K.tile('Surface Elo', eloCur ? '<span class="af-tile-surf">' + surfE + '</span>' : '—', 'hard · clay · grass'),
    K.tile('Ranking', isNum(rank) ? '#' + rank : '—', off ? K.int(off[2]) + ' points' + (isNum(off[3]) && off[3] ? ' · <span class="' + (off[3] > 0 ? 'pg-up' : 'pg-down') + '">' + (off[3] > 0 ? '▲' : '▼') + Math.abs(off[3]) + '</span>' : '') : ''),
    K.tile('Race', raceIdx >= 0 ? '#' + (raceIdx + 1) : '—', raceIdx >= 0 ? K.int(raceList[raceIdx][1]) + ' points this year' : 'not in the race top 100'),
    K.tile('Hold %', K.fmtV(hold, 'pct'), 'service games held, inferred' + (p && isNum((p.pct || {}).hold) ? ' · ' + Math.round(p.pct.hold) + 'th pct' : '')),
    K.tile('Break %', K.fmtV(brk, 'pct'), 'return games won, inferred' + (p && isNum((p.pct || {}).brk) ? ' · ' + Math.round(p.pct.brk) + 'th pct' : '')),
    K.tile(finalsName, isNum(fq) ? K.pct(fq) : '—', isNum(fq) ? 'qualification odds · <a href="' + K.href(T, 'race') + '">race →</a>' : 'not simulated'),
    K.tile('Year-end No. 1', isNum(no1) ? K.pct(no1) : '—', isNum(no1) ? 'season simulation' : 'not in contention')
  ].join('') + '</div>';
  h += '<div id="pp-value"></div>';

  // Percentiles + radar.
  const surfOpts = K.SURFACES.filter(s => p && (p.pct_surface || {})[s]);
  h += '<div class="card"><div class="card-header">Percentiles <span class="card-sub">The whole catalogue, ' + metrics.length + ' metrics' + (cat && cat.year ? ', ' + K.esc(cat.year) : '') + '. Tour: against every qualified ' + K.TN(T) + ' player. Surface: against the players with enough matches on it.</span>' +
    K.toggle('pp-src', [['tour', 'Tour']].concat(surfOpts.map(s => [s, K.SURF_LABEL[s]])), 'tour') + '</div><div id="pp-pct"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Profile <span class="card-sub">Ten headline metrics as tour percentiles' + (rival ? ', against ' + K.esc(K.name(T, rival)) : '') + '.</span></div><div id="pp-radar" style="height:400px"></div></div>' +
    '<div class="card"><div class="card-header">Clutch <span class="card-sub">Actual against the chain\'s expectation from the pre-match prices.</span></div><div id="pp-clutch"></div></div></div>';
  // Elo history and serve/return paths.
  h += '<div class="card"><div class="card-header">Elo history <span class="card-sub">Overall and surface Elo after every match.</span>' + K.toggle('pp-elo-win', [['all', 'Career'], ['3', 'Last 3 years'], ['1', 'Last year']], 'all') + '</div><div id="pp-elo" style="height:340px"></div></div>';
  h += '<div class="card"><div class="card-header">Serve and return <span class="card-sub">The serve (s) and return (r) ratings from the score-based model, ±1 standard error shaded, by surface. Higher is better for both.</span>' +
    K.toggle('pp-sr-kind', [['rating', 'Ratings'], ['rates', 'Hold / break %']], 'rating') + '</div><div id="pp-sr" style="height:360px"></div><div class="pg-note" id="pp-sr-note"></div></div>';
  h += '<div class="grid-2"><div class="card"><div class="card-header">Ranking <span class="card-sub">Official ranking over time (log scale).</span></div><div id="pp-rank" style="height:280px"></div></div>' +
    '<div class="card"><div class="card-header">Points to defend <span class="card-sub">What drops off the 52-week ranking, by week.</span></div><div id="pp-defend"></div></div></div>';
  h += '<div class="card"><div class="card-header">Seasons <span class="card-sub">Tour-level record, titles, inferred hold and break, and Elo at the end of each year.</span></div><div id="pp-seasons"></div></div>';
  h += '<div class="card"><div class="card-header">Results <span class="card-sub" id="pp-res-sub">The model\'s pre-match probability and the closing market against what happened.</span>' +
    '<span class="pg-ctl"><select id="pp-res-surf"><option value="">all surfaces</option><option value="hard">hard</option><option value="clay">clay</option><option value="grass">grass</option></select></span></div><div id="pp-res-chart" style="height:220px"></div><div id="pp-results"></div></div>';
  h += '<div class="card"><div class="card-header">Splits <span class="card-sub">Record, expected wins (sum of pre-match model probabilities) and the difference.</span>' +
    K.toggle('pp-split', [['surface', 'Surface'], ['level', 'Level'], ['round', 'Round'], ['opp_band', 'Opponent rank']], 'surface') + '</div><div id="pp-splits"></div></div>';
  h += '<div class="card" id="pp-style-card"><div class="card-header">Style <span class="card-sub">Shot-by-shot profile from the Match Charting Project, against the median charted ' + K.TN(T) + ' player.</span></div><div id="pp-style"></div></div>';
  h += '<div class="card"><div class="card-header">Head to head <span class="card-sub">Most frequent opponents (top 30 by matches). Click for the full head-to-head page.</span></div><div id="pp-h2h"></div></div>';
  el.innerHTML = h;

  // Percentile panel.
  const drawPct = src => {
    const box = document.getElementById('pp-pct');
    if (!box) return;
    if (!p) { box.innerHTML = K.muted(K.esc(name) + ' is not in the ' + K.esc((cat || {}).year || '') + ' catalogue (no tour-level match this year).'); return; }
    const pc = src === 'tour' ? p.pct : ((p.pct_surface || {})[src] || {});
    const vs = src !== 'tour' && (p.values_surface || {})[src] ? p.values_surface[src] : vals;
    box.innerHTML = K.pctPanel(metrics, vs, pc, { note: (src === 'tour' ? 'Tour percentile' : K.SURF_LABEL[src] + ' percentile') + ', 100 = best. ↓ marks metrics where lower is better. Real serve/return stats exist for WTA matches from 2016 (not Slams); style metrics only for charted matches. With a surface picked, values are the figures on that surface where the catalogue carries them, ranked against that surface pool. Hover a row for the definition.' });
  };
  drawPct('tour');
  K.wireToggle(el, 'pp-src', drawPct);
  const pctP = (p && p.pct) || {};
  const axes = K.headline(metrics, RADAR_PREFS, 10, pctP).map(m => ({ key: m.key, label: K.shortLabel(m.label) }));
  const rv = rival && P[rival] ? P[rival] : null;
  K.radar('pp-radar', axes, [{ name: name, pct: pctP, colour: K.CA }].concat(rv ? [{ name: rv.name, pct: rv.pct || {}, colour: K.CB }] : []));

  if (TA.value && typeof TA.value.card === 'function') TA.value.card(T, pid, document.getElementById('pp-value'));
  drawClutch(c, p, metrics);
  drawEloHistory(T, c, el);
  drawServeReturn(c, el);
  drawRanks(c);
  drawDefend(T, c, ranks, pid);
  drawSeasons(c);
  drawResults(T, c);
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
    '<div class="pg-note">Expected wins are the sum of the model\'s probabilities for those sets or matches, so a positive figure is more won than the ratings predicted. Small samples swing: a tiebreak record of 10 has a standard deviation of about 1.6 wins.</div>';
}

function cutoff(win) { if (win === 'all') return ''; const d = new Date(); d.setFullYear(d.getFullYear() - Number(win)); return d.toISOString().slice(0, 10); }

function drawEloHistory(T, c, root) {
  const rows = (c.elo || []).filter(r => Array.isArray(r) && r[0]);
  const draw = win => {
    const node = document.getElementById('pp-elo');
    if (!node) return;
    const cut = cutoff(win);
    const rs = rows.filter(r => String(r[0]) >= cut);
    if (!rs.length) { node.innerHTML = K.muted('No Elo history in the career file.'); return; }
    const x = rs.map(r => r[0]);
    const tr = [['All', 1, 'all', 2.6], ['Hard', 2, 'hard', 1.4], ['Clay', 3, 'clay', 1.4], ['Grass', 4, 'grass', 1.4]].filter(s => rs.some(r => isNum(r[s[1]]))).map(s => ({
      type: 'scatter', mode: 'lines', name: s[0], x: x, y: rs.map(r => r[s[1]]), line: { color: K.surfColour(s[2]), width: s[3], shape: 'hv' },
      hovertemplate: '%{x}: ' + s[0] + ' %{y:.0f}<extra></extra>'
    }));
    K.plot(node, tr, K.layout(Object.assign(K.legendTop(), { margin: { l: 50, r: 10, t: 30, b: 36 }, yaxis: { title: 'Elo' }, xaxis: { type: 'date', title: 'Date' } })));
  };
  draw('all');
  K.wireToggle(root, 'pp-elo-win', draw);
}

function drawServeReturn(c, root) {
  const rows = (c.serve_return || []).filter(r => Array.isArray(r) && r[0]);
  const note = document.getElementById('pp-sr-note');
  const draw = kind => {
    const node = document.getElementById('pp-sr');
    if (!node) return;
    if (!rows.length) { node.innerHTML = K.muted('No serve/return path in the career file.'); return; }
    const surfs = Array.from(new Set(rows.map(r => r[1]))).sort((a, b) => (a === 'all' ? -1 : b === 'all' ? 1 : K.SURFACES.indexOf(a) - K.SURFACES.indexOf(b)));
    const tr = [];
    surfs.forEach(s => {
      const rs = rows.filter(r => r[1] === s);
      const col = K.surfColour(s), lab = K.SURF_LABEL[s] || s;
      if (kind === 'rates') {
        tr.push({ type: 'scatter', mode: 'lines', name: lab + ' hold', x: rs.map(r => r[0]), y: rs.map(r => r[4]), line: { color: col, width: 2 }, hovertemplate: '%{x}: ' + lab + ' hold %{y:.1%}<extra></extra>' });
        tr.push({ type: 'scatter', mode: 'lines', name: lab + ' break', x: rs.map(r => r[0]), y: rs.map(r => r[5]), line: { color: col, width: 1.5, dash: 'dot' }, yaxis: 'y2', hovertemplate: '%{x}: ' + lab + ' break %{y:.1%}<extra></extra>' });
      } else {
        K.band(rs.map(r => ({ x: r[0], y: r[2], se: r[6], text: r[0] })), col, lab + ' serve').forEach(t => tr.push(t));
        K.band(rs.map(r => ({ x: r[0], y: r[3], se: r[7], text: r[0] })), col, lab + ' return', { dash: 'dot', yaxis: 'y2' }).forEach(t => tr.push(t));
      }
    });
    const lay = K.layout(Object.assign(K.legendTop(), { margin: { l: 50, r: 10, t: 34, b: 36 }, xaxis: { type: 'date', title: 'Date' },
      grid: { rows: 2, columns: 1, pattern: 'independent', roworder: 'top to bottom' },
      yaxis: { title: kind === 'rates' ? 'Hold %' : 'Serve rating', domain: [0.54, 1], tickformat: kind === 'rates' ? '.0%' : '' },
      yaxis2: { title: kind === 'rates' ? 'Break %' : 'Return rating', domain: [0, 0.44], tickformat: kind === 'rates' ? '.0%' : '', gridcolor: '#21262d', zerolinecolor: '#30363d' },
      xaxis2: { type: 'date', anchor: 'y2', gridcolor: '#21262d', title: 'Date' } }));
    tr.forEach(t => { if (t.yaxis === 'y2') t.xaxis = 'x2'; });
    K.plot(node, tr, lay);
    if (note) note.innerHTML = kind === 'rates' ? 'Hold and break against the average tour-level opponent on that surface, from the same fits. Solid: hold (top). Dotted: break (bottom).' :
      'Ratings are on the log-odds scale of holding serve: a serve rating 0.3 higher raises the log-odds of holding by 0.3 against any returner. Fitted by penalised maximum likelihood over every set score, matches weighted by a half-life (see the <a href="#/methodology/serve-return">methodology</a>). The band is ±1 standard error from the curvature of the fit.';
  };
  draw('rating');
  K.wireToggle(root, 'pp-sr-kind', draw);
}

function drawRanks(c) {
  const node = document.getElementById('pp-rank');
  if (!node) return;
  const rs = (c.ranks || []).filter(r => Array.isArray(r) && isNum(r[1]));
  if (!rs.length) { node.innerHTML = K.muted('No ranking history.'); return; }
  K.plot(node, [{ type: 'scatter', mode: 'lines', x: rs.map(r => r[0]), y: rs.map(r => r[1]), line: { color: K.C.yellow, width: 2, shape: 'hv' }, hovertemplate: '%{x}: No. %{y}<extra></extra>' }],
    K.layout({ margin: { l: 44, r: 10, t: 10, b: 36 }, xaxis: { type: 'date', title: 'Date' }, yaxis: { type: 'log', autorange: 'reversed', title: 'Rank', tickvals: [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000] } }));
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

function drawResults(T, c) {
  const host = document.getElementById('pp-results'), chart = document.getElementById('pp-res-chart'), sel = document.getElementById('pp-res-surf');
  const all = (c.results || []).filter(r => r && r.date).slice().sort((a, b) => String(b.date).localeCompare(String(a.date)));
  const draw = () => {
    const sf = sel ? sel.value : '';
    const rs = all.filter(r => !sf || r.surface === sf);
    if (!rs.length) { host.innerHTML = K.muted('No results in the career file' + (sf ? ' on ' + sf : '') + '.'); chart.style.display = 'none'; return; }
    chart.style.display = '';
    const withP = rs.filter(r => isNum(r.p_pre));
    const wins = withP.filter(r => r.won).length, exp = withP.reduce((s, r) => s + r.p_pre, 0);
    const withM = rs.filter(r => isNum(r.market_pre) && isNum(r.p_pre));
    const ll = (list, k) => list.reduce((s, r) => { const q = Math.min(0.9999, Math.max(0.0001, r[k])); return s - Math.log(r.won ? q : 1 - q); }, 0) / (list.length || 1);
    const sub = document.getElementById('pp-res-sub');
    if (sub) sub.innerHTML = rs.length + ' matches (' + K.esc(String(rs[rs.length - 1].date).slice(0, 4)) + '–' + K.esc(String(rs[0].date).slice(0, 4)) + ')' +
      (withP.length ? ' · won ' + wins + ' against ' + K.num(exp, 1) + ' expected (<span class="' + (wins - exp >= 0 ? 'pg-up' : 'pg-down') + '">' + K.signed(wins - exp, 1) + '</span>)' : '') +
      (withM.length >= 5 ? ' · log-loss on the ' + withM.length + ' matches with a closing price: model ' + K.num(ll(withM, 'p_pre'), 3) + ', market ' + K.num(ll(withM, 'market_pre'), 3) : '');
    // Wins minus expected, cumulative (oldest first).
    const asc = withP.slice().reverse();
    let cum = 0;
    const ys = asc.map(r => (cum += (r.won ? 1 : 0) - r.p_pre));
    K.plot(chart, [{ type: 'scatter', mode: 'lines', x: asc.map(r => r.date), y: ys, line: { color: K.C.blue, width: 2 }, fill: 'tozeroy', fillcolor: K.alpha(K.C.blue, 0.12),
      text: asc.map(r => (r.won ? 'W ' : 'L ') + K.name(T, r.opp) + ' · ' + K.eventName(T, r.event) + ' ' + (r.round || '') + ' · model ' + K.pct(r.p_pre, 0)), hovertemplate: '%{x}<br>%{text}<br>running total %{y:+.1f}<extra></extra>' }],
      K.layout({ margin: { l: 46, r: 10, t: 8, b: 30 }, xaxis: { type: 'date', title: 'Date' }, yaxis: { title: 'Wins − expected', zeroline: true, zerolinecolor: '#6e7681' } }));
    host.innerHTML = K.table([{ label: 'Date' }, { label: 'Event' }, { label: 'Rd' }, { label: 'Opponent' }, { label: 'Result' }, { label: 'Score' }, { label: 'Model', align: 'right', title: 'The model\'s pre-match probability for this player' },
      { label: 'Market', align: 'right', title: 'Closing market probability (de-vigged) for this player' }, { label: 'Surprise', align: 'right', title: 'Outcome minus the model probability: +0.8 is a win the model gave 20%' }],
      rs.slice(0, showAll ? rs.length : 40).map(r => ({ _href: r.match ? K.matchHref(T, r.match) : undefined, cells: [
        { v: r.date, html: K.esc(K.fmtDate(r.date, { weekday: false })) },
        { v: K.eventName(T, r.event), html: K.surfChip(r.surface) + ' ' + K.eventLink(T, r.event) },
        { v: K.ROUND_ORDER.indexOf(r.round), html: K.esc(r.round || '') },
        { v: K.name(T, r.opp), html: K.playerLink(T, r.opp) },
        { v: r.won ? 1 : 0, html: r.won ? '<span class="af-w">W</span>' : '<span class="af-l">L</span>' },
        { v: r.score || '', html: '<span class="pg-mono">' + K.esc(r.score || '') + '</span>' },
        { v: r.p_pre, html: K.pct(r.p_pre, 0) },
        { v: r.market_pre, html: isNum(r.market_pre) ? K.pct(r.market_pre, 0) + (isNum(r.p_pre) ? ' <span class="muted-inline">(' + K.signed(100 * (r.p_pre - r.market_pre), 0) + ')</span>' : '') : '<span class="muted-inline">—</span>' },
        { v: isNum(r.p_pre) ? (r.won ? 1 : 0) - r.p_pre : null, html: isNum(r.p_pre) ? '<span class="' + (r.won ? 'pg-up' : 'pg-down') + '">' + K.signed((r.won ? 1 : 0) - r.p_pre, 2) + '</span>' : '—' }
      ] })), { compact: true, sticky: true }) +
      (rs.length > 40 && !showAll ? '<div class="pg-note"><button type="button" class="af-more" id="pp-res-more">Show all ' + rs.length + ' matches</button></div>' : '');
    K.sortable(host);
    const more = document.getElementById('pp-res-more');
    if (more) more.onclick = () => { showAll = true; draw(); };
  };
  let showAll = false;
  if (sel) sel.onchange = draw;
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
    K.plot(id + '-dir', [['wide', 'Wide', '#58a6ff'], ['body', 'Body', '#8b949e'], ['t', 'T', '#f97316']].map(z => ({
      type: 'bar', orientation: 'h', name: z[1], y: sides.map(s => s[1] + ' (' + K.int(dir[s[0]].n) + ')'), x: sides.map(s => dir[s[0]][z[0]]), marker: { color: z[2] },
      hovertemplate: '%{y}: ' + z[1] + ' %{x:.0%}<extra></extra>', text: sides.map(s => Math.round(100 * (dir[s[0]][z[0]] || 0)) + '%'), textposition: 'inside', insidetextanchor: 'middle'
    })), K.layout(Object.assign(K.legendTop(), { barmode: 'stack', margin: { l: 110, r: 10, t: 28, b: 24 }, xaxis: { title: 'Share of serves', tickformat: '.0%', range: [0, 1] }, yaxis: { autorange: 'reversed' } })));
  } else document.getElementById(id + '-dir').innerHTML = K.muted('No serve direction.');
  const ra = st.rally || {};
  const bk = Object.keys(ra.dist || {});
  if (bk.length) {
    K.plot(id + '-rally', [
      { type: 'bar', name: 'Share of points', x: bk, y: bk.map(k => ra.dist[k]), marker: { color: K.alpha('#58a6ff', 0.75) }, hovertemplate: '%{x} shots: %{y:.0%} of points<extra></extra>' },
      { type: 'scatter', mode: 'lines+markers', name: 'Points won', x: bk, y: bk.map(k => (ra.won || {})[k]), yaxis: 'y2', line: { color: '#f97316', width: 2 }, hovertemplate: '%{x} shots: won %{y:.0%}<extra></extra>' }
    ], K.layout(Object.assign(K.legendTop(), { margin: { l: 44, r: 44, t: 28, b: 30 }, xaxis: { title: 'Shots in the rally', type: 'category' }, yaxis: { title: 'Share of points', tickformat: '.0%' },
      yaxis2: { title: 'Points won', overlaying: 'y', side: 'right', tickformat: '.0%', range: [0.3, 0.7], gridcolor: 'rgba(0,0,0,0)' } })));
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
