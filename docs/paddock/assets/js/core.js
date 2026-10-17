/* The Quant Paddock — core: namespace, state, routing, cached loading, helpers, search.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/f1/PAYLOADS.md).
 * Every page module registers itself with PD.route(name, renderFn) and never edits
 * this file. Routes (hash):
 *
 *   #/                              hub
 *   #/season/<y>                    season          (#/season -> current season)
 *   #/races/<y>                     races           (#/races  -> current season)
 *   #/race/<y>/<r>                  race
 *   #/race/<y>/<r>/quali            quali
 *   #/race/<y>/<r>/telemetry        telemetry
 *   #/driver/<id>                   driver
 *   #/team/<id>                     team
 *   #/circuit/<id>                  circuit
 *   #/drivers  #/teams  #/circuits  drivers / teams / circuits
 *   #/lab                           lab
 *   #/compare/drivers/<a>/<b>       compare-drivers (falls back to a 'compare' handler)
 *   #/compare/teams/<a>/<b>         compare-teams   (falls back to a 'compare' handler)
 *   #/compare                       compare
 *   #/markets #/calibration #/glossary #/methodology #/disclaimer
 *   #/value[/<y>] #/swap #/fantasy
 *
 * Extra trailing segments land in params.rest; a "?a=1&b=2" suffix lands in
 * params.query. A render function is called as fn(el, params, state): `el` is a
 * fresh <div> inside <main id="app"> (it is detached when the viewer navigates
 * away, so async code can test el.isConnected), `params` holds the named
 * segments ({year, round, id, a, b, kind, rest, query}). It may return a Promise.
 *
 * PD.route accepts a route name ('race'), an alias ('race-quali', 'race/quali',
 * 'compare/drivers') or the pattern itself ('#/race/<y>/<r>/quali',
 * 'race/:year/:round/quali'); an unknown pattern is added as a new route.
 */
window.PD = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

const C = {
  bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d',
  text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316',
  purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8',
  pctLow: [59, 130, 246], pctMid: [107, 114, 128], pctHigh: [239, 68, 68]
};
const PALETTE = ['#58a6ff', '#3fb950', '#f97316', '#bc8cff', '#f85149', '#d29922', '#39d0d8', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
const COMPOUNDS = { SOFT: '#e8002d', MEDIUM: '#ffd12e', HARD: '#f0f0ec', INTERMEDIATE: '#43b02a', WET: '#0067ad', UNKNOWN: '#6e7681', TEST_UNKNOWN: '#6e7681' };
const DARK_LAYOUT = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: '#8b949e', family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', size: 11 },
  xaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  yaxis: { gridcolor: '#21262d', zerolinecolor: '#30363d', linecolor: '#30363d' },
  margin: { l: 60, r: 20, t: 30, b: 50 },
  hovermode: 'closest',
  hoverlabel: { bgcolor: '#161b22', bordercolor: '#30363d', font: { color: '#e6edf3', size: 12 } },
  showlegend: false
};
const PLOTLY_CONF = { displayModeBar: false, responsive: true };
const FOOTBALL_URL = 'https://pchattani.github.io/the-quant-footballer/';

// ── state and registries ───────────────────────────────────────────────────

const state = { year: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = { drivers: {}, teams: {}, circuits: {} };   // id -> {name, code, colour, ...}
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];

// Route table: pattern segments, ':x' captures. Order matters only for display.
const ROUTES = [];
function addRoute(pattern, name, fallbacks, defaults) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, fallbacks: fallbacks || [], defaults: defaults || {} });
}
addRoute('', 'hub');
addRoute('season', 'season');
addRoute('season/:year', 'season');
addRoute('races', 'races');
addRoute('races/:year', 'races');
addRoute('race/:year/:round', 'race');
addRoute('race/:year/:round/quali', 'quali');
addRoute('race/:year/:round/telemetry', 'telemetry');
addRoute('driver/:id', 'driver');
addRoute('team/:id', 'team');
addRoute('circuit/:id', 'circuit');
addRoute('drivers', 'drivers');
addRoute('teams', 'teams');
addRoute('circuits', 'circuits');
addRoute('lab', 'lab');
addRoute('compare', 'compare');
addRoute('compare/drivers', 'compare-drivers', ['compare'], { kind: 'drivers' });
addRoute('compare/drivers/:a', 'compare-drivers', ['compare'], { kind: 'drivers' });
addRoute('compare/drivers/:a/:b', 'compare-drivers', ['compare'], { kind: 'drivers' });
addRoute('compare/teams', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('compare/teams/:a', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('compare/teams/:a/:b', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('markets', 'markets');
addRoute('value', 'value');
addRoute('value/:year', 'value');
addRoute('swap', 'swap');
addRoute('fantasy', 'fantasy');
addRoute('calibration', 'calibration');
addRoute('glossary', 'glossary');
addRoute('methodology', 'methodology');
addRoute('disclaimer', 'disclaimer');

const ALIASES = {
  home: 'hub', index: 'hub', '': 'hub',
  'race-quali': 'quali', 'race/quali': 'quali', qualifying: 'quali',
  'race-telemetry': 'telemetry', 'race/telemetry': 'telemetry', 'telemetry-lab': 'telemetry',
  'compare/drivers': 'compare-drivers', 'compare_drivers': 'compare-drivers',
  'compare/teams': 'compare-teams', 'compare_teams': 'compare-teams',
  calendar: 'races', 'season-races': 'races'
};

const TITLES = {
  hub: 'Hub', season: 'Season', races: 'Races', race: 'Race centre', quali: 'Qualifying', telemetry: 'Telemetry lab',
  driver: 'Driver', team: 'Team', circuit: 'Circuit', drivers: 'Drivers', teams: 'Teams', circuits: 'Circuits',
  lab: 'Lab', compare: 'Compare', 'compare-drivers': 'Compare drivers', 'compare-teams': 'Compare teams',
  markets: 'Markets', calibration: 'Calibration', glossary: 'Glossary', methodology: 'Methodology', disclaimer: 'Disclaimer & terms',
  value: 'Driver value', swap: 'Driver-swap simulator', fantasy: 'Fantasy'
};
// Which top-nav link lights up for each route.
const NAV_OF = { hub: 'hub', season: 'season', races: 'races', race: 'races', quali: 'races', telemetry: 'races',
  driver: 'drivers', drivers: 'drivers', team: 'teams', teams: 'teams', circuit: 'circuits', circuits: 'circuits',
  lab: 'lab', compare: 'compare', 'compare-drivers': 'compare', 'compare-teams': 'compare', markets: 'markets',
  calibration: 'calibration', glossary: 'glossary', methodology: 'methodology', value: 'value', swap: 'swap', fantasy: 'fantasy' };

function normPattern(s) {
  return String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
}
function shape(p) { return p.split('/').map(s => (s.charAt(0) === ':' ? ':' : s)).join('/'); }

/* Register a page renderer. See the header for the accepted names. */
function route(name, fn) {
  if (typeof fn !== 'function') return;
  const raw = normPattern(name);
  let key = ALIASES[raw] || ALIASES[String(name)] || raw;
  if (raw.indexOf('/') >= 0 || raw.indexOf(':') >= 0) {
    const sh = shape(raw);
    const hit = ROUTES.find(r => shape(r.pattern) === sh);
    if (hit) key = hit.name;
    else if (!ALIASES[raw]) { addRoute(raw, raw); key = raw; }
  }
  HANDLERS[key] = fn;
  // A late registration for the page on screen renders it now.
  if (state.route === key || (state.route && !HANDLERS[state.route] && (routeEntry(state.route) || {}).fallbacks && routeEntry(state.route).fallbacks.indexOf(key) >= 0)) {
    if (booted) render();
  }
}
function routeEntry(name) { return ROUTES.find(r => r.name === name) || null; }

function parseHash(hash) {
  let h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  const query = {};
  const qi = h.indexOf('?');
  if (qi >= 0) {
    h.slice(qi + 1).split('&').forEach(kv => {
      if (!kv) return;
      const i = kv.indexOf('=');
      const k = decodeURIComponent(i >= 0 ? kv.slice(0, i) : kv), v = i >= 0 ? decodeURIComponent(kv.slice(i + 1)) : '';
      query[k] = v;
    });
    h = h.slice(0, qi);
  }
  const parts = h.split('/').filter(s => s !== '').map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } });
  let best = null, bestLen = -1;
  ROUTES.forEach(r => {
    if (r.segs.length > parts.length) return;
    if (r.segs.length === 0 && parts.length > 0) return;
    for (let i = 0; i < r.segs.length; i++) {
      if (r.segs[i].charAt(0) !== ':' && r.segs[i] !== parts[i]) return;
    }
    // Prefer the longest match; among equals, the exact-length one.
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts };
  Object.keys(best.defaults).forEach(k => { params[k] = best.defaults[k]; });
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  if (params.year !== undefined) { const y = parseInt(params.year, 10); params.year = isNaN(y) ? params.year : y; }
  if (params.round !== undefined) { const r = parseInt(params.round, 10); params.round = isNaN(r) ? params.round : r; }
  return { name: best.name, params: params, parts: parts };
}

function handlerFor(name) {
  if (HANDLERS[name]) return HANDLERS[name];
  const e = routeEntry(name);
  if (e) for (let i = 0; i < e.fallbacks.length; i++) if (HANDLERS[e.fallbacks[i]]) return HANDLERS[e.fallbacks[i]];
  return null;
}

/* Register cleanup work (timers, listeners) run when the viewer leaves the page. */
function onLeave(fn) { if (typeof fn === 'function') CLEANUPS.push(fn); }
/* setInterval that is cleared on navigation. */
function interval(fn, ms) { const id = setInterval(fn, ms); onLeave(() => clearInterval(id)); return id; }

function runCleanups() {
  const list = CLEANUPS; CLEANUPS = [];
  list.forEach(fn => { try { fn(); } catch (e) { console.warn('cleanup failed', e); } });
}

let booted = false;
function render() {
  runCleanups();
  closeSearch();
  const r = parseHash();
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  if (r.params.year && typeof r.params.year === 'number') setYear(r.params.year, true);
  else if (!state.year) setYear(currentSeason(), true);
  markNav(NAV_OF[r.name] || '');
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'page page-' + r.name.replace(/[^a-z0-9-]/gi, '-');
  app.appendChild(el);
  document.title = (r.name === 'hub' ? '' : (TITLES[r.name] || 'Page') + ' · ') + 'The Quant Paddock';
  setMeta('');
  window.scrollTo(0, 0);
  const fn = handlerFor(r.name);
  if (!fn) {
    el.innerHTML = r.name === 'notfound'
      ? comingHTML('Page not found', 'There is no page at <code>' + esc(location.hash) + '</code>. Try the hub or the search box.')
      : comingHTML((TITLES[r.name] || 'This page') + ' is coming', 'This part of The Quant Paddock is still being built. The hub, season and race centre pages are live.');
    return;
  }
  try {
    const out = fn(el, r.params, state);
    if (out && typeof out.then === 'function') {
      out.then(null, err => showError(el, err));
    }
  } catch (err) {
    showError(el, err);
  }
}

function comingHTML(title, body) {
  return '<div class="card coming"><div class="pad"><div class="coming-title">' + esc(title) + '</div>' +
    '<p class="muted-inline">' + body + '</p><p><a href="#/">Back to the hub →</a></p></div></div>';
}
function showError(el, err) {
  console.error(err);
  if (el) el.insertAdjacentHTML('afterbegin', '<div class="error-banner">This page could not be shown: ' + esc(err && err.message ? err.message : err) + '</div>');
}

function go(hash) {
  const h = hash.charAt(0) === '#' ? hash : '#/' + hash.replace(/^\/+/, '');
  if (location.hash === h) render(); else location.hash = h;
}

// ── loading ────────────────────────────────────────────────────────────────

/* Cached fetch of data/<path>. Resolves to the parsed JSON, or null when the file
 * is missing or broken. A payload written with "ok": false resolves as written:
 * test it with PD.ok(d). */
function load(path) {
  const p = String(path).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(d => { learn(p, d); return d; })
    .catch(err => { console.warn('payload missing:', p, err.message); return null; })
    .then(d => { if (d !== null) CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
/* Several payloads at once: resolves to an array in the same order. */
function loadAll(paths) { return Promise.all(paths.map(load)); }
function ok(d) { return !!d && d.ok !== false; }
function reason(d) { return d && d.reason ? String(d.reason) : 'not built yet'; }
function cached(path) { const p = String(path).replace(/^data\//, ''); return Object.prototype.hasOwnProperty.call(CACHE, p) ? CACHE[p] : undefined; }

/* Harvest names and colours from any payload that carries them. */
function learn(path, d) {
  if (!d || typeof d !== 'object') return;
  const putD = (id, info) => { if (!id || !info) return; NAMES.drivers[id] = Object.assign({}, NAMES.drivers[id] || {}, info); };
  const putT = (id, info) => { if (!id || !info) return; NAMES.teams[id] = Object.assign({}, NAMES.teams[id] || {}, info); };
  const putC = (id, info) => { if (!id || !info) return; NAMES.circuits[id] = Object.assign({}, NAMES.circuits[id] || {}, info); };
  try {
    if (/(^|\/)index\.json$/.test(path)) {
      Object.keys(d.drivers || {}).forEach(id => putD(id, pick(d.drivers[id], ['name', 'code', 'number', 'nationality', 'team'])));
      Object.keys(d.teams || {}).forEach(id => putT(id, pick(d.teams[id], ['name', 'colour'])));
      if (d.next && d.next.circuit) putC(d.next.circuit.id, pick(d.next.circuit, ['name', 'country']));
    }
    if (d.teams && !Array.isArray(d.teams) && /season\.json$|teams\.json$/.test(path)) {
      Object.keys(d.teams).forEach(id => { const t = d.teams[id] || {}; if (t.name || t.colour) putT(id, pick(t, ['name', 'colour'])); });
    }
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(id => { const n = d.names[id]; if (typeof n === 'string' && !(NAMES.drivers[id] || {}).name) putD(id, { name: n }); });
    }
    if (d.drivers && !Array.isArray(d.drivers) && /drivers\.json$/.test(path)) {
      Object.keys(d.drivers).forEach(id => { const x = d.drivers[id] || {}; if (x.name) putD(id, pick(x, ['name', 'code', 'team'])); });
    }
    if (/(^|\/)drivers\/[^/]+\.json$/.test(path) && d.name) putD(path.split('/').pop().replace('.json', ''), pick(d, ['name', 'nationality']));
    if (Array.isArray(d.calendar)) d.calendar.forEach(c => { if (c.circuit && c.circuit.id) putC(c.circuit.id, pick(c.circuit, ['name', 'country', 'locality'])); });
    if (d.circuit && d.circuit.id) putC(d.circuit.id, pick(d.circuit, ['name', 'country', 'locality']));
    if (/circuits\.json$/.test(path)) Object.keys(d).forEach(id => { const x = d[id]; if (x && typeof x === 'object' && x.name) putC(id, pick(x, ['name', 'country'])); });
    if (/elo\.json$/.test(path) && Array.isArray(d.all_time)) d.all_time.forEach(x => { if (x.driver && x.name && !(NAMES.drivers[x.driver] || {}).name) putD(x.driver, { name: x.name }); });
  } catch (e) { console.warn('learn failed for', path, e); }
}
function pick(o, keys) { const out = {}; keys.forEach(k => { if (o && o[k] !== undefined && o[k] !== null) out[k] = o[k]; }); return out; }

// ── formatting ─────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && !isNaN(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
/* num(3.14159, 2) -> "3.14"; '—' for missing. */
function num(v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; }
/* pct(0.1234) -> "12.3%" (input is a probability 0-1). */
function pct(p, d) {
  if (!isNum(p)) return '—';
  const dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
}
/* signed(1.5) -> "+1.5", signed(-2) -> "-2.0". */
function signed(v, d) {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
}
/* fmtMs(83456) -> "1:23.456"; under a minute "23.456"; over an hour "1:32:10.123". */
function fmtMs(ms, digits) {
  if (!isNum(ms)) return '—';
  const d = digits === undefined ? 3 : digits;
  const neg = ms < 0;
  const unit = Math.pow(10, 3 - d);
  let t = Math.round(Math.abs(Number(ms)) / unit) * unit / 1000;
  const h = Math.floor(t / 3600); t -= h * 3600;
  const m = Math.floor(t / 60); t -= m * 60;
  const s = Math.max(0, t).toFixed(d);
  const pad = n => (n < 10 ? '0' : '') + n;
  const sec = (Number(s) < 10 && (m || h) ? '0' : '') + s;
  const out = h ? h + ':' + pad(m) + ':' + sec : m ? m + ':' + sec : s;
  return (neg ? '-' : '') + out;
}
/* fmtGap(123) -> "+0.123" (input in ms); over a minute "+1:02.345". */
function fmtGap(ms, digits) {
  if (!isNum(ms)) return '—';
  if (Number(ms) === 0) return '—';
  return (ms > 0 ? '+' : '-') + fmtMs(Math.abs(ms), digits === undefined ? 3 : digits);
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  const str = String(s);
  const d = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
  return isNaN(d.getTime()) ? null : d;
}
/* fmtDate("2026-09-26") -> "Sat 26 Sep 2026" in the viewer's timezone.
 * opts: {year: false} drops the year, {time: true} adds HH:MM, {weekday: false}. */
function fmtDate(s, opts) {
  const o = typeof opts === 'boolean' ? { year: opts } : (opts || {});
  const d = parseDate(s);
  if (!d) return '—';
  let out = (o.weekday === false ? '' : DAYS[d.getDay()] + ' ') + d.getDate() + ' ' + MONTHS[d.getMonth()] + (o.year === false ? '' : ' ' + d.getFullYear());
  if (o.time && String(s).length > 10) out += ' ' + fmtTime(s);
  return out;
}
function fmtTime(s) {
  const d = parseDate(s);
  if (!d || String(s).length === 10) return '';
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function fmtStamp(s) {
  const d = parseDate(s);
  if (!d) return s ? String(s) : '';
  return fmtDate(d, { year: false }) + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
/* "3d 04h 12m" / "4h 12m 09s" until an ISO time; '' if past. */
function countdown(iso, now) {
  const d = parseDate(iso);
  if (!d) return '';
  let s = Math.floor((d.getTime() - (now || Date.now())) / 1000);
  if (s <= 0) return '';
  const days = Math.floor(s / 86400); s -= days * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  const p = n => String(n).padStart(2, '0');
  return days ? days + 'd ' + p(h) + 'h ' + p(m) + 'm' : p(h) + 'h ' + p(m) + 'm ' + p(s) + 's';
}
function ordinal(n) {
  if (!isNum(n)) return '—';
  const v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
}
/* Format a catalogue value by its declared fmt ('pct', 'prob', 'int', 'ms', 'gap', '1', '2', '3', 'signed'). */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  switch (fmt) {
    case 'pct': return Number(v).toFixed(1) + '%';
    case 'prob': return pct(v);
    case 'int': return String(Math.round(v));
    case 'ms': return fmtMs(v);
    case 'gap': return fmtGap(v);
    case 's': return Number(v).toFixed(3) + 's';
    case 'signed': return signed(v, 2);
    case '0': return Number(v).toFixed(0);
    case '1': return Number(v).toFixed(1);
    case '3': return Number(v).toFixed(3);
    default: return Number(v).toFixed(2);
  }
}

// ── names, colours, links ──────────────────────────────────────────────────

function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}
function driverName(id) { const x = NAMES.drivers[id]; return x && x.name ? x.name : titleCase(id); }
function driverCode(id) {
  const x = NAMES.drivers[id];
  if (x && x.code) return x.code;
  const parts = String(id || '').split('_');
  return parts[parts.length - 1].slice(0, 3).toUpperCase();
}
function driverSurname(id) { const n = driverName(id).split(' '); return n[n.length - 1]; }
function teamName(id) { const x = NAMES.teams[id]; return x && x.name ? x.name : titleCase(id); }
function circuitName(id) { const x = NAMES.circuits[id]; return x && x.name ? x.name : titleCase(id); }
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
/* The team's colour (OpenF1 team_colour via the payloads), else a stable palette pick. */
function teamColour(id) {
  const x = NAMES.teams[id];
  if (x && x.colour) { const c = String(x.colour); return c.charAt(0) === '#' ? c : '#' + c; }
  return id ? PALETTE[hashIndex(id, PALETTE.length)] : C.text3;
}
/* A driver's colour: their team's (current season unless a team is given). */
function driverColour(id, team) {
  const t = team || (NAMES.drivers[id] || {}).team;
  return t ? teamColour(t) : PALETTE[hashIndex(id || '', PALETTE.length)];
}
function compoundColour(c) { return COMPOUNDS[String(c || 'UNKNOWN').toUpperCase()] || COMPOUNDS.UNKNOWN; }
function teamBar(id) { return '<span class="team-bar" style="background:' + esc(teamColour(id)) + '"></span>'; }
/* <a> to the driver page. opts {name, code: true (show the code), team (colour bar)} or a name string. */
function driverLink(id, opts) {
  if (!id) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.code ? driverCode(id) : driverName(id));
  return '<a class="drv-link" href="#/driver/' + encodeURIComponent(id) + '">' + (o.team ? teamBar(o.team) : '') + esc(label) + '</a>';
}
function teamLink(id, opts) {
  if (!id) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  return '<a class="team-link" href="#/team/' + encodeURIComponent(id) + '">' + (o.bar === false ? '' : teamBar(id)) + esc(o.name || teamName(id)) + '</a>';
}
function circuitLink(id, name) {
  if (!id) return '<span class="muted-inline">—</span>';
  return '<a class="circ-link" href="#/circuit/' + encodeURIComponent(id) + '">' + esc(name || circuitName(id)) + '</a>';
}
function raceHref(y, r, sub) { return '#/race/' + y + '/' + r + (sub ? '/' + sub : ''); }
function raceLink(y, r, label) { return '<a class="race-link" href="' + raceHref(y, r) + '">' + esc(label || (y + ' R' + r)) + '</a>'; }

// ── HTML builders ──────────────────────────────────────────────────────────

/* A card: header with a title and a muted sub-line, then the body. */
function card(title, sub, bodyHtml, id) {
  return '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' +
    (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + '</div>' : '') +
    (bodyHtml || '') + '</div>';
}
function muted(text) { return '<div class="muted">' + text + '</div>'; }
function chip(text, cls) { return '<span class="chip' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</span>'; }

/* Table. cols: [{label, align, title, sortable:false, cls}]. rows: [{cells: [cell...], _class, _href}]
 * or plain arrays of cells; a cell is {v, html, cls, align, title} or a primitive.
 * opts: {compact, sticky, cls, id}. Sort keys come from cell.v (numeric when it parses). */
function tableHTML(cols, rows, opts) {
  const o = opts || {};
  let h = '<div class="table-wrap' + (o.compact ? ' compact' : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><table class="wc-table' + (o.sticky ? ' sticky-head' : '') + (o.cls ? ' ' + o.cls : '') + '"><thead><tr>';
  cols.forEach(c => {
    const cc = typeof c === 'string' ? { label: c } : c;
    h += '<th class="' + (cc.sortable === false ? '' : 'sortable-th') + (cc.cls ? ' ' + cc.cls : '') + '"' +
         (cc.align ? ' style="text-align:' + cc.align + '"' : '') +
         (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>';
  });
  h += '</tr></thead><tbody>';
  (rows || []).forEach(r => {
    const row = Array.isArray(r) ? { cells: r } : r;
    h += '<tr' + (row._class ? ' class="' + row._class + '"' : '') + (row._href ? ' data-href="' + esc(row._href) + '"' : '') + (row._style ? ' style="' + esc(row._style) + '"' : '') + '>';
    row.cells.forEach((c0, i) => {
      const c = (c0 !== null && typeof c0 === 'object') ? c0 : { v: c0 };
      const col = typeof cols[i] === 'object' ? cols[i] : {};
      const align = c.align || col.align;
      const sortV = c.v !== undefined && c.v !== null ? c.v : (c.html !== undefined ? String(c.html).replace(/<[^>]*>/g, '') : '');
      h += '<td data-v="' + esc(sortV) + '"' + (c.cls ? ' class="' + c.cls + '"' : '') + (c.title ? ' title="' + esc(c.title) + '"' : '') +
           (align || c.style ? ' style="' + (align ? 'text-align:' + align + ';' : '') + (c.style || '') + '"' : '') + '>' +
           (c.html !== undefined ? c.html : esc(c.v === null || c.v === undefined ? '—' : c.v)) + '</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}

/* Make the tables in el (an element, an id, or a table) sortable by header click,
 * and wire rows carrying data-href as links. */
function sortable(el) {
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
          const av = a.children[idx] ? a.children[idx].dataset.v : '';
          const bv = b.children[idx] ? b.children[idx].dataset.v : '';
          const an = parseFloat(av), bn = parseFloat(bv);
          const aN = !isNaN(an) && isFinite(av), bN = !isNaN(bn) && isFinite(bv);
          let cmp;
          if (aN && bN) cmp = an - bn;
          else if (aN) cmp = -1;
          else if (bN) cmp = 1;
          else cmp = String(av).localeCompare(String(bv));
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
}

/* Blue at the bottom, grey in the middle, red at the top (p is 0-100). */
function lerp(a, b, t) { return a + (b - a) * t; }
function pctColor(p) {
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100;
  const from = t < 0.5 ? C.pctLow : C.pctMid, to = t < 0.5 ? C.pctMid : C.pctHigh;
  const u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + Math.round(lerp(from[0], to[0], u)) + ',' + Math.round(lerp(from[1], to[1], u)) + ',' + Math.round(lerp(from[2], to[2], u)) + ')';
}
/* A Savant-style percentile pill; p is a 0-100 percentile (100 = best). */
function pctPill(p) {
  if (!isNum(p)) return '<span class="pct-pill empty">—</span>';
  return '<span class="pct-pill" style="background:' + pctColor(p) + '">' + Math.round(p) + '</span>';
}
/* One slider row: label, a bar with the percentile dot, and the raw value text. */
function pctRow(label, p, valueText, title) {
  const known = isNum(p);
  const x = known ? Math.max(0, Math.min(100, p)) : 0;
  return '<div class="pct-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>' +
    '<span class="pct-label">' + esc(label) + '</span>' +
    '<div class="pct-bar">' + (known
      ? '<div class="pct-fill" style="width:' + x + '%;background:' + pctColor(p) + '"></div>' +
        '<span class="pct-dot" style="left:' + x + '%;background:' + pctColor(p) + '">' + Math.round(p) + '</span>'
      : '<span class="pct-none">not enough data</span>') +
    '</div><span class="pct-val">' + (valueText === undefined ? '' : valueText) + '</span></div>';
}
/* A KPI tile; value is HTML. */
function statTile(label, value, sub, cls) {
  return '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + esc(label) + '</div>' +
    '<div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>';
}
/* A probability with an inline bar (0-1); colour optional. */
function probCell(p, colour, max) {
  if (!isNum(p)) return '<span class="muted-inline">—</span>';
  const w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="pcell"><span class="pcell-bar"><span style="width:' + w.toFixed(1) + '%;background:' + (colour || C.blue) + '"></span></span><span class="pcell-v">' + pct(p) + '</span></span>';
}
/* Diverging colour for v in [-max, max]: negative green (good when lower = better), positive red. */
function divColour(v, max, invert) {
  if (!isNum(v) || !max) return 'transparent';
  let t = Math.max(-1, Math.min(1, v / max));
  if (invert) t = -t;
  const a = Math.abs(t);
  return t < 0 ? 'rgba(63,185,80,' + (0.12 + 0.6 * a).toFixed(3) + ')' : 'rgba(248,81,73,' + (0.12 + 0.6 * a).toFixed(3) + ')';
}
/* Sequential blue for t in [0,1]. */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'rgba(88,166,255,' + (0.06 + 0.8 * u).toFixed(3) + ')';
}

// ── charts ─────────────────────────────────────────────────────────────────

function deepCopy(o) { return JSON.parse(JSON.stringify(o)); }
/* The dark layout merged with extra (axes merged one level deep). */
function layout(extra) {
  const base = deepCopy(DARK_LAYOUT);
  const out = Object.assign(base, extra || {});
  Object.keys(extra || {}).forEach(k => {
    if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK_LAYOUT.xaxis, extra[k]);
  });
  if (extra && extra.font) out.font = Object.assign({}, DARK_LAYOUT.font, extra.font);
  return out;
}
/* Draw a Plotly chart into el (element or id); degrades to a muted line. */
function plot(el, traces, lay, conf) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (typeof Plotly === 'undefined') {
    node.innerHTML = '<div class="muted">The chart library did not load. The tables carry the same data.</div>';
    return null;
  }
  try {
    const p = Plotly.newPlot(node, traces, lay && lay.paper_bgcolor !== undefined ? lay : layout(lay), Object.assign({}, PLOTLY_CONF, conf || {}));
    onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    return p;
  } catch (err) {
    console.warn('chart failed', err);
    node.innerHTML = '<div class="muted">The chart could not be drawn.</div>';
    return null;
  }
}

// ── header: season picker, nav, meta, search ───────────────────────────────

function currentSeason() {
  const d = INDEX.data;
  return d && d.current_season ? d.current_season : new Date().getFullYear();
}
function setYear(y, silent) {
  const yy = parseInt(y, 10);
  if (isNaN(yy)) return;
  state.year = yy;
  const sel = document.getElementById('season-select');
  if (sel && String(sel.value) !== String(yy)) {
    if (!Array.prototype.some.call(sel.options, o => o.value === String(yy))) sel.insertAdjacentHTML('beforeend', '<option value="' + yy + '">' + yy + '</option>');
    sel.value = String(yy);
  }
  document.querySelectorAll('[data-nav="season"]').forEach(a => { a.setAttribute('href', '#/season/' + yy); });
  document.querySelectorAll('[data-nav="races"]').forEach(a => { a.setAttribute('href', '#/races/' + yy); });
  if (!silent) {
    if (state.route === 'races') go('#/races/' + yy);
    else go('#/season/' + yy);
  }
}
function markNav(key) {
  document.querySelectorAll('.global-nav a[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === key));
}
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const base = d && d.updated_at ? 'Updated ' + esc(fmtStamp(d.updated_at)) : '';
  el.innerHTML = [html, base].filter(Boolean).join(' · ');
}

let SEARCH = null, searchPending = null;
function loadSearch() {
  if (SEARCH) return Promise.resolve(SEARCH);
  if (searchPending) return searchPending;
  const y = state.year || currentSeason();
  searchPending = loadAll(['elo.json', 'circuits.json', y + '/season.json', currentSeason() + '/season.json']).then(arr => {
    const items = [];
    const seen = {};
    const add = (kind, id, label, sub, href) => {
      const k = kind + ':' + id;
      if (seen[k]) return; seen[k] = 1;
      items.push({ kind: kind, id: id, label: label, sub: sub, href: href, norm: norm(label + ' ' + (sub || '') + ' ' + id) });
    };
    Object.keys(NAMES.drivers).forEach(id => { const x = NAMES.drivers[id]; add('Drivers', id, x.name || titleCase(id), [x.code, x.team ? teamName(x.team) : ''].filter(Boolean).join(' · '), '#/driver/' + id); });
    ((arr[0] || {}).all_time || []).forEach(x => add('Drivers', x.driver, x.name || titleCase(x.driver), (x.years || []).join('–'), '#/driver/' + x.driver));
    Object.keys(NAMES.teams).forEach(id => add('Teams', id, teamName(id), '', '#/team/' + id));
    Object.keys(NAMES.circuits).forEach(id => { const x = NAMES.circuits[id]; add('Circuits', id, x.name || titleCase(id), x.country || '', '#/circuit/' + id); });
    [arr[2], arr[3]].forEach(s => {
      if (!ok(s)) return;
      (s.calendar || []).forEach(c => add('Races', s.year + '-' + c.round, s.year + ' ' + c.name, 'Round ' + c.round + ' · ' + fmtDate(c.date, { weekday: false }) + (c.circuit && c.circuit.locality ? ' · ' + c.circuit.locality : ''), raceHref(s.year, c.round)));
    });
    SEARCH = items;
    return items;
  });
  return searchPending;
}
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function closeSearch() {
  const box = document.getElementById('search-results');
  if (box) { box.innerHTML = ''; box.style.display = 'none'; }
}
function runSearch(q) {
  const box = document.getElementById('search-results');
  const n = norm(q.trim());
  if (n.length < 2 || !box) { closeSearch(); return; }
  loadSearch().then(items => {
    const groups = ['Drivers', 'Teams', 'Circuits', 'Races'];
    const words = n.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.norm.indexOf(w) >= 0));
    let html = '';
    groups.forEach(g => {
      const list = hits.filter(h => h.kind === g).slice(0, g === 'Races' ? 6 : 7);
      if (!list.length) return;
      html += '<div class="sr-head">' + g + '</div>' + list.map(h =>
        '<a class="sr-item" href="' + esc(h.href) + '">' + (g === 'Teams' ? teamBar(h.id) : '') + '<span>' + esc(h.label) + '</span><span class="sr-sub">' + esc(h.sub || '') + '</span></a>').join('');
    });
    box.innerHTML = html || '<div class="sr-empty">No driver, team, circuit or race matches.</div>';
    box.style.display = 'block';
  });
}
function initSearch() {
  const input = document.getElementById('search-input');
  if (!input) return;
  let timer = null;
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => runSearch(input.value), 120); });
  input.addEventListener('focus', () => { loadSearch(); if (input.value.trim().length >= 2) runSearch(input.value); });
  input.addEventListener('keydown', ev => {
    if (ev.key === 'Escape') { input.value = ''; closeSearch(); input.blur(); }
    if (ev.key === 'Enter') { const a = document.querySelector('#search-results a.sr-item'); if (a) { location.hash = a.getAttribute('href'); input.value = ''; closeSearch(); } }
  });
  document.addEventListener('click', ev => { if (!ev.target.closest('.search-box')) closeSearch(); });
  const box = document.getElementById('search-results');
  if (box) box.addEventListener('click', ev => { if (ev.target.closest('a')) { input.value = ''; closeSearch(); } });
}

function initSeasonPicker() {
  const sel = document.getElementById('season-select');
  if (!sel) return;
  const d = INDEX.data || {};
  const years = (d.seasons && d.seasons.length) ? d.seasons.slice() : [currentSeason()];
  years.sort((a, b) => b - a);
  sel.innerHTML = years.map(y => '<option value="' + y + '">' + y + '</option>').join('');
  sel.value = String(state.year || currentSeason());
  sel.addEventListener('change', () => setYear(sel.value));
}

function init() {
  load('index.json').then(idx => {
    INDEX.data = idx;
    state.year = state.year || currentSeason();
    initSeasonPicker();
    initSearch();
    setYear(state.year, true);
    const ov = document.getElementById('loading-overlay');
    if (ov) ov.style.display = 'none';
    booted = true;
    window.addEventListener('hashchange', render);
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else setTimeout(init, 0);

return {
  // state and routing
  state: state, route: route, go: go, parseHash: parseHash, onLeave: onLeave, interval: interval, render: render,
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES,
  // data
  load: load, loadAll: loadAll, ok: ok, reason: reason, cached: cached, index: () => INDEX.data, currentSeason: currentSeason,
  NAMES: NAMES, setYear: setYear, setMeta: setMeta,
  // formatting
  esc: esc, num: num, pct: pct, signed: signed, fmtMs: fmtMs, fmtGap: fmtGap, fmtDate: fmtDate, fmtTime: fmtTime,
  fmtStamp: fmtStamp, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  // names, colours, links
  driverName: driverName, driverCode: driverCode, driverSurname: driverSurname, teamName: teamName, circuitName: circuitName,
  teamColour: teamColour, driverColour: driverColour, compoundColour: compoundColour, teamBar: teamBar,
  driverLink: driverLink, teamLink: teamLink, circuitLink: circuitLink, raceLink: raceLink, raceHref: raceHref,
  // HTML
  card: card, muted: muted, chip: chip, tableHTML: tableHTML, sortable: sortable, pctPill: pctPill, pctColor: pctColor,
  pctRow: pctRow, statTile: statTile, probCell: probCell, divColour: divColour, seqColour: seqColour,
  // charts
  plot: plot, layout: layout, PALETTE: PALETTE, COMPOUNDS: COMPOUNDS, C: C, DARK_LAYOUT: DARK_LAYOUT, PLOTLY_CONF: PLOTLY_CONF,
  FOOTBALL_URL: FOOTBALL_URL,
  charts: {}
};
})();
