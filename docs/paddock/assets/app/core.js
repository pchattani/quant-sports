/* The Quant Paddock — core: state, routing (with the old-route redirect map), cached loading,
 * names and colours, formatting and the HTML builders every page uses. Built on the shared kit
 * (assets/qk: window.QK, window.QKC). Older-browser rule: no optional chaining, no nullish coalescing.
 *
 * Routes (hash). Section in brackets is the item lit in the section nav.
 *   #/                                   overview                      [overview]
 *   #/races[/<y>]  #/circuits  #/circuit/<id>                          [races]
 *   #/race/<y>/<r>[/laps|strategy|quali|telemetry]   race centre       [races]
 *   #/standings[/<y>][?tab=championship|odds|pace]                     [standings]
 *   #/constructors[/<y>] (the Teams page, pd-teams.js)  #/team/<id>[/<y>]   [constructors]
 *   #/scout (the Scouting Room, pd-scout.js)  #/driver/<id>[/<y>]  #/compare/drivers/<a>/<b>   [scouting room]
 *   #/value[/<y>][?tab=drivers|swap|needs&x=&w=]                       [value & moves]
 *   #/fantasy                                                          [fantasy]
 * Round 9: the Drivers list and the Lab are the Scouting Room (#/drivers[/<y>] -> #/scout?s=<y>, #/lab?x=&y=&q= ->
 * #/scout?view=chart&x=&y=&q=, bare #/compare[/drivers[/<a>]] -> the room's compare tray), and Compare teams is the
 * Teams page's head to head (#/compare/teams/<a>/<b> -> #/constructors?a=&b=&sec=h2h).
 *   #/model  #/methodology[/<sec>]  #/calibration  #/glossary[/<key>]  #/disclaimer   [model]
 * Old routes are redirected through ROUTE_MAP (see below) so every link ever shared still lands.
 * The season comes from the address only (round 9): a page without a year in its route is the current season, and the
 * links a page draws to a driver or a constructor carry the page's season (#/driver/<id>/<y>), so the year never
 * carries over in session state and the season select always shows the season on screen.
 *
 * A page registers with PD.route(name, fn); fn(el, params, state) renders into el (a fresh div,
 * detached when the viewer navigates away: test el.isConnected after any await) and may return a
 * Promise. params: the named segments plus params.query (the ?a=b part of the hash). */
window.PD = (function () {
'use strict';

var QK = window.QK;

// ── state, registries ─────────────────────────────────────────────────────

var state = { year: null, route: null, params: {}, hash: '' };
var INDEX = { data: null };
var NAMES = { drivers: {}, teams: {}, circuits: {} };
var CACHE = {}, PENDING = {};
var HANDLERS = {};
var CLEANUPS = [];
var SHELL = null;

var ROUTES = [];
function addRoute(pattern, name, section) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, section: section });
}
addRoute('', 'overview', 'overview');
addRoute('races', 'races', 'fixtures');
addRoute('races/:year', 'races', 'fixtures');
addRoute('circuits', 'circuits', 'fixtures');
addRoute('circuit/:id', 'circuit', 'fixtures');
addRoute('race/:year/:round', 'race', 'fixtures');
addRoute('race/:year/:round/:tab', 'race', 'fixtures');
addRoute('standings', 'standings', 'standings');
addRoute('standings/:year', 'standings', 'standings');
addRoute('constructors', 'constructors', 'teams');
addRoute('constructors/:year', 'constructors', 'teams');
addRoute('team/:id', 'team', 'teams');
addRoute('team/:id/:year', 'team', 'teams');
addRoute('scout', 'scout', 'scout');
addRoute('driver/:id', 'driver', 'scout');
addRoute('driver/:id/:year', 'driver', 'scout');
addRoute('value', 'value', 'value');
addRoute('value/:year', 'value', 'value');
addRoute('fantasy', 'fantasy', 'fantasy');
addRoute('compare/:kind/:a/:b', 'compare', 'scout');
addRoute('model', 'model', 'model');
addRoute('methodology', 'methodology', 'model');
addRoute('methodology/:sec', 'methodology', 'model');
addRoute('calibration', 'calibration', 'model');
addRoute('glossary', 'glossary', 'model');
addRoute('glossary/:key', 'glossary', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

/* Old hash routes -> their new home. [from pattern, to template, extra query]. ':x' captures carry
 * over (into the path, and into an extra query value written ':x'); the old query string is kept (swap's ?x=&w=,
 * telemetry's ?s=&a=&la=&b=&lb=, the Lab's ?x=&y=&q=). Exposed as PD.ROUTE_MAP and applied to links inside static
 * text (methodology) as well. */
var ROUTE_MAP = [
  ['hub', ''], ['home', ''], ['index', ''],
  ['season', 'standings'], ['season/:year', 'standings/:year'],
  ['calendar', 'races'], ['season-races', 'races'],
  ['teams', 'constructors'], ['teams/:year', 'constructors/:year'],
  ['markets', 'standings', { tab: 'odds' }],
  ['swap', 'value', { tab: 'swap' }],
  ['race/:year/:round/qualifying', 'race/:year/:round/quali'],
  ['race/:year/:round/results', 'race/:year/:round'],
  ['compare/drivers/:a/:b/:rest', 'compare/drivers/:a/:b'],
  ['drivers', 'scout'], ['drivers/:year', 'scout', { s: ':year' }], ['players', 'scout'], ['leaders', 'scout', { view: 'leaders' }],
  ['lab', 'scout', { view: 'chart' }], ['compare', 'scout'], ['compare/drivers', 'scout'], ['compare/drivers/:a', 'scout', { cmp: ':a' }],
  ['compare/teams', 'constructors', { sec: 'h2h' }], ['compare/teams/:a', 'constructors', { a: ':a', sec: 'h2h' }],
  ['compare/teams/:a/:b', 'constructors', { a: ':a', b: ':b', sec: 'h2h' }],
  ['glossary/g', 'glossary']
];

var TITLES = {
  overview: '', races: 'Races', circuits: 'Circuits', circuit: 'Circuit', race: 'Race centre', standings: 'Standings',
  constructors: 'Constructors', team: 'Constructor', scout: 'Scouting Room', driver: 'Driver', value: 'Value & Moves',
  fantasy: 'Fantasy', compare: 'Compare', model: 'Model', methodology: 'Methodology',
  calibration: 'Calibration', glossary: 'Glossary', disclaimer: 'Disclaimer and terms'
};

function splitHash(hash) {
  var h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  var query = {};
  var qi = h.indexOf('?');
  if (qi >= 0) {
    h.slice(qi + 1).split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      var k = dec(i >= 0 ? kv.slice(0, i) : kv), v = i >= 0 ? dec(kv.slice(i + 1)) : '';
      query[k] = v;
    });
    h = h.slice(0, qi);
  }
  var parts = h.split('/').filter(function (s) { return s !== ''; }).map(dec);
  return { parts: parts, query: query };
}
function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
function qs(query) {
  var ks = Object.keys(query || {}).filter(function (k) { return query[k] !== undefined && query[k] !== null && query[k] !== ''; });
  return ks.length ? '?' + ks.map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(query[k]); }).join('&') : '';
}
function matchSegs(segs, parts) {
  if (segs.length !== parts.length) return null;
  var p = {};
  for (var i = 0; i < segs.length; i++) {
    if (segs[i].charAt(0) === ':') p[segs[i].slice(1)] = parts[i];
    else if (segs[i] !== parts[i]) return null;
  }
  return p;
}
/* The new hash for an old route, or null when the route is current. */
function redirectFor(hash) {
  var s = splitHash(hash);
  for (var i = 0; i < ROUTE_MAP.length; i++) {
    var m = ROUTE_MAP[i];
    var p = matchSegs(m[0] ? m[0].split('/') : [], s.parts);
    if (!p) continue;
    var to = m[1].split('/').filter(Boolean).map(function (seg) { return seg.charAt(0) === ':' ? encodeURIComponent(p[seg.slice(1)]) : seg; }).join('/');
    var ex = {};
    Object.keys(m[2] || {}).forEach(function (k) { var v = m[2][k]; ex[k] = typeof v === 'string' && v.charAt(0) === ':' ? p[v.slice(1)] : v; });
    var q = Object.assign(ex, s.query);
    return '#/' + to + qs(q);
  }
  return null;
}
/* Rewrite href="#/old" links inside a block of static HTML to their new homes. */
function fixLinks(html) {
  return String(html || '').replace(/href="(#\/[^"]*)"/g, function (all, h) { var r = redirectFor(h.replace(/&amp;/g, '&')); return r ? 'href="' + r + '"' : all; });
}

function parseHash(hash) {
  var s = splitHash(hash);
  var best = null, params = null;
  for (var i = 0; i < ROUTES.length; i++) {
    var p = matchSegs(ROUTES[i].segs, s.parts);
    if (p) { best = ROUTES[i]; params = p; break; }
  }
  if (!best) return { name: 'notfound', section: null, params: { query: s.query, rest: s.parts } };
  params.query = s.query;
  if (params.year !== undefined) { var y = parseInt(params.year, 10); params.year = isNaN(y) ? null : y; }
  if (params.round !== undefined) { var r = parseInt(params.round, 10); params.round = isNaN(r) ? null : r; }
  return { name: best.name, section: best.section, params: params };
}

function route(name, fn) { HANDLERS[name] = fn; if (booted && state.route === name) render(); }
function onLeave(fn) { if (typeof fn === 'function') CLEANUPS.push(fn); }
function interval(fn, ms) { var id = setInterval(fn, ms); onLeave(function () { clearInterval(id); }); return id; }
function runCleanups() {
  var list = CLEANUPS; CLEANUPS = [];
  list.forEach(function (fn) { try { fn(); } catch (e) { if (window.console) console.warn('cleanup failed', e); } });
}

var booted = false;
function render() {
  var red = redirectFor(location.hash);
  if (red) { try { history.replaceState(null, '', red); } catch (e) { location.hash = red; return; } }
  runCleanups();
  var r = parseHash();
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  /* the season is the address's, else the current one: never the last page's (round 9, the sticky-year fix) */
  setYear(typeof r.params.year === 'number' ? r.params.year : currentSeason(), true);
  if (SHELL) SHELL.setSection(r.section || '');
  var app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  var el = document.createElement('div');
  el.className = 'pd-page pd-page-' + r.name;
  app.appendChild(el);
  document.title = (TITLES[r.name] ? TITLES[r.name] + ' · ' : '') + 'The Quant Paddock';
  window.scrollTo(0, 0);
  var fn = HANDLERS[r.name];
  if (!fn) {
    el.innerHTML = pageHead('Not found', 'Page not found', 'There is no page at ' + esc(location.hash) + '. Try the overview or search (press /).') +
      '<p><a class="qk-btn" href="#/">Back to the overview</a></p>';
    return;
  }
  try {
    var out = fn(el, r.params, state);
    if (out && typeof out.then === 'function') out.then(null, function (err) { showError(el, err); });
  } catch (err) { showError(el, err); }
}
function showError(el, err) {
  if (window.console) console.error(err);
  if (el) el.insertAdjacentHTML('afterbegin', '<div class="pd-error" data-route-error role="alert">This page could not be shown: ' + esc(err && err.message ? err.message : err) + '</div>');
}
function go(hash) {
  var h = hash.charAt(0) === '#' ? hash : '#/' + hash.replace(/^\/+/, '');
  if (location.hash === h) render(); else location.hash = h;
}
/* Replace the hash without a new history entry or a re-render (shareable page state). */
function setHashQuiet(h) { try { history.replaceState(null, '', h); state.hash = h; } catch (e) { /* old browsers: state is not shareable */ } }

// ── loading ───────────────────────────────────────────────────────────────

function load(path) {
  var p = String(path).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (d) { learn(p, d); return d; })
    .catch(function () { return null; })
    .then(function (d) { if (d !== null) CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
/* Like load() but says first whether the file exists (HEAD), so optional files do not log 404s. */
function loadAll(paths) { return Promise.all(paths.map(load)); }
function ok(d) { return !!d && d.ok !== false; }
function reason(d) { return d && d.reason ? String(d.reason) : 'not built yet'; }

function learn(path, d) {
  if (!d || typeof d !== 'object') return;
  function putD(id, info) { if (!id || !info) return; NAMES.drivers[id] = Object.assign({}, NAMES.drivers[id] || {}, info); }
  function putT(id, info) { if (!id || !info) return; NAMES.teams[id] = Object.assign({}, NAMES.teams[id] || {}, info); }
  function putC(id, info) { if (!id || !info) return; NAMES.circuits[id] = Object.assign({}, NAMES.circuits[id] || {}, info); }
  try {
    if (/^index\.json$/.test(path)) {
      Object.keys(d.drivers || {}).forEach(function (id) { putD(id, pick(d.drivers[id], ['name', 'code', 'number', 'nationality', 'team'])); });
      Object.keys(d.teams || {}).forEach(function (id) { putT(id, pick(d.teams[id], ['name', 'colour', 'alt'])); });
      if (d.next && d.next.circuit) putC(d.next.circuit.id, pick(d.next.circuit, ['name', 'country']));
    }
    if (d.teams && !Array.isArray(d.teams) && /season\.json$|teams\.json$/.test(path)) {
      Object.keys(d.teams).forEach(function (id) { var t = d.teams[id] || {}; if (t.name || t.colour) putT(id, pick(t, ['name', 'colour', 'alt'])); });
    }
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(function (id) { var n = d.names[id]; if (typeof n === 'string' && !(NAMES.drivers[id] || {}).name) putD(id, { name: n }); });
    }
    if (d.drivers && !Array.isArray(d.drivers) && /drivers\.json$/.test(path)) {
      Object.keys(d.drivers).forEach(function (id) { var x = d.drivers[id] || {}; if (x.name && !(NAMES.drivers[id] || {}).name) putD(id, pick(x, ['name', 'code'])); });
    }
    if (/^drivers\/[^/]+\.json$/.test(path) && d.name) putD(path.split('/').pop().replace('.json', ''), pick(d, ['name', 'nationality', 'code']));
    if (Array.isArray(d.calendar)) d.calendar.forEach(function (c) { if (c.circuit && c.circuit.id) putC(c.circuit.id, pick(c.circuit, ['name', 'country', 'locality'])); });
    if (d.circuit && d.circuit.id) putC(d.circuit.id, pick(d.circuit, ['name', 'country', 'locality']));
    if (/^circuits\.json$/.test(path)) Object.keys(d).forEach(function (id) { var x = d[id]; if (x && typeof x === 'object' && x.name) putC(id, pick(x, ['name', 'country'])); });
    if (/^elo\.json$/.test(path) && Array.isArray(d.all_time)) d.all_time.forEach(function (x) { if (x.driver && x.name && !(NAMES.drivers[x.driver] || {}).name) putD(x.driver, { name: x.name }); });
    if (/^elo\.json$/.test(path) && d.current) Object.keys(d.current).forEach(function (id) { var x = d.current[id]; if (x && x.name && !(NAMES.drivers[id] || {}).name) putD(id, { name: x.name }); });
  } catch (e) { if (window.console) console.warn('learn failed for', path, e); }
}
function pick(o, keys) { var out = {}; keys.forEach(function (k) { if (o && o[k] !== undefined && o[k] !== null) out[k] = o[k]; }); return out; }

// ── formatting ────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function num(v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; }
function int(v) { return isNum(v) ? Math.round(v).toLocaleString('en-GB') : '—'; }
function pts(v) { return isNum(v) ? (v % 1 ? Number(v).toFixed(1) : String(Math.round(v))) : '—'; }
/* A championship chance: ">99.9%" until the title is clinched arithmetically (a simulation that never loses is not a
   clinch: the magic number may still be 49), "<0.1%" until the driver or team is out; c is the championship row
   ({ p_title, clinched, eliminated }). */
function chance(p, c, d) {
  if (!isNum(p)) return '—';
  var dd = d === undefined ? 1 : d, lim = Math.pow(10, -dd);
  if (c && c.clinched) return '100%';
  if (c && c.eliminated) return '0%';
  if (p * 100 >= 100 - lim / 2) return '>' + (100 - lim).toFixed(dd) + '%';
  if (p * 100 < lim / 2) return '<' + lim.toFixed(dd) + '%';
  return pct(p, dd);
}
function titlePct(c, d) { return c ? chance(c.p_title, c, d) : '—'; }
function pct(p, d) {
  if (!isNum(p)) return '—';
  var dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
}
function signed(v, d) {
  if (!isNum(v)) return '—';
  var s = Number(v).toFixed(d === undefined ? 1 : d);
  if (/^-0\.?0*$/.test(s)) s = s.slice(1);
  return (Number(s) > 0 ? '+' : Number(s) < 0 ? '−' : '') + s.replace(/^-/, '');
}
function fmtMs(ms, digits) {
  if (!isNum(ms)) return '—';
  var d = digits === undefined ? 3 : digits;
  var neg = ms < 0;
  var unit = Math.pow(10, 3 - d);
  var t = Math.round(Math.abs(Number(ms)) / unit) * unit / 1000;
  var h = Math.floor(t / 3600); t -= h * 3600;
  var m = Math.floor(t / 60); t -= m * 60;
  var s = Math.max(0, t).toFixed(d);
  var pad = function (n) { return (n < 10 ? '0' : '') + n; };
  var sec = (Number(s) < 10 && (m || h) ? '0' : '') + s;
  var out = h ? h + ':' + pad(m) + ':' + sec : m ? m + ':' + sec : s;
  return (neg ? '-' : '') + out;
}
function fmtGap(ms, digits) {
  if (!isNum(ms) || Number(ms) === 0) return '—';
  return (ms > 0 ? '+' : '-') + fmtMs(Math.abs(ms), digits === undefined ? 3 : digits);
}
var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  var str = String(s);
  var d = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
  return isNaN(d.getTime()) ? null : d;
}
function fmtDate(s, opts) {
  var o = typeof opts === 'boolean' ? { year: opts } : (opts || {});
  var d = parseDate(s);
  if (!d) return '—';
  var out = (o.weekday === false ? '' : DAYS[d.getDay()] + ' ') + d.getDate() + ' ' + MONTHS[d.getMonth()] + (o.year === false ? '' : ' ' + d.getFullYear());
  if (o.time && String(s).length > 10) out += ' ' + fmtTime(s);
  return out;
}
function fmtTime(s) {
  var d = parseDate(s);
  if (!d || String(s).length === 10) return '';
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
}
function fmtStamp(s) { var d = parseDate(s); if (!d) return s ? String(s) : ''; return fmtDate(d, { year: false }) + ' ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
function countdown(iso, now) {
  var d = parseDate(iso);
  if (!d) return '';
  var s = Math.floor((d.getTime() - (now || Date.now())) / 1000);
  if (s <= 0) return '';
  var days = Math.floor(s / 86400); s -= days * 86400;
  var h = Math.floor(s / 3600); s -= h * 3600;
  var m = Math.floor(s / 60); s -= m * 60;
  var p = function (n) { return ('0' + n).slice(-2); };
  return days ? days + 'd ' + p(h) + 'h ' + p(m) + 'm' : p(h) + 'h ' + p(m) + 'm ' + p(s) + 's';
}
function ordinal(n) {
  if (!isNum(n)) return '—';
  var v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
}
function fmtVal(v, f) {
  if (!isNum(v)) return '—';
  switch (f) {
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
function titleCase(id) { return String(id || '').split(/[_\s-]+/).filter(Boolean).map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(' '); }
function shortRace(n) { return String(n || '').replace(/ Grand Prix.*$/, '').replace(/^Grand Prix (of )?/, ''); }
function median(a) { var s = a.filter(isNum).slice().sort(function (x, y) { return x - y; }); if (!s.length) return null; var k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function mean(a) { var s = a.filter(isNum); return s.length ? s.reduce(function (x, y) { return x + Number(y); }, 0) / s.length : null; }
function rowsOf(cols, rows) { return (rows || []).map(function (r) { var o = {}; cols.forEach(function (c, i) { o[c] = r[i]; }); return o; }); }
function ageOf(dob) {
  var d = parseDate(dob);
  if (!d) return null;
  var now = new Date(), a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
}
function finished(st) { return !st || st === 'Finished' || /^\+\d+ Laps?$/.test(st) || st === 'Lapped'; }

// ── names, colours, links ─────────────────────────────────────────────────

/* Fallback colours for a team with none in the payloads (historic entrants): the kit's warm chart slots, blue left out
 * because blue means ours. */
var PALETTE = ['#6aa8ec', '#ff7a5c', '#8fd16a', '#c39be8', '#ffc94d', '#8fdcc8', '#f28fb5', '#d9b38c', '#ff9b7a', '#a7c7f2'];
/* Kit colour tokens by name, read from the page (charts need the hex): PD.col('coral'). Blue is ours only. */
var TOK = { teal: '--c-1', coral: '--c-2', sky: '--c-3', sun: '--c-4', plum: '--c-5', leaf: '--c-6', rose: '--c-7', sand: '--c-8', mint: '--mint', grey: '--c-other', muted: '--ink-3', faint: '--ink-4', up: '--up', down: '--down' };
function col(k) { return QK.cssVar(TOK[k] || k) || '#8a93a3'; }
var COMPOUNDS = { SOFT: '#e8002d', MEDIUM: '#ffd12e', HARD: '#f0f0ec', INTERMEDIATE: '#43b02a', WET: '#0067ad', UNKNOWN: '#7d8590', TEST_UNKNOWN: '#7d8590' };
function driverName(id) { var x = NAMES.drivers[id]; return x && x.name ? x.name : titleCase(id); }
function driverCode(id) {
  var x = NAMES.drivers[id];
  if (x && x.code) return x.code;
  var parts = String(id || '').split('_');
  return parts[parts.length - 1].slice(0, 3).toUpperCase();
}
function driverSurname(id) { var n = driverName(id).split(' '); return n[n.length - 1]; }
function teamName(id) { var x = NAMES.teams[id]; return x && x.name ? x.name : titleCase(id); }
function circuitName(id) { var x = NAMES.circuits[id]; return x && x.name ? x.name : titleCase(id); }
function hashIndex(s, n) { var h = 0; String(s).split('').forEach(function (ch) { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
/* The team's raw colour (OpenF1 team_colour via the payloads), else a stable palette pick. */
function teamColour(id) {
  var x = NAMES.teams[id];
  if (x && x.colour) { var c = String(x.colour); return c.charAt(0) === '#' ? c : '#' + c; }
  return id ? PALETTE[hashIndex(id, PALETTE.length)] : '#6b7383';
}
/* The team's colour from the payloads only (index.json / season.json teams[].colour), else null: blocks, heroes and
   title-race bars take it, and the kit's fallbacks (cobalt v slate, QK.color.block) cover a team without one. Never a
   palette pick: the front end does not invent team colours. */
function teamColourRaw(id) {
  var x = NAMES.teams[id];
  if (!x || !x.colour) return null;
  var c = String(x.colour);
  return c.charAt(0) === '#' ? c : '#' + c;
}
/* The team's second livery colour from the payloads (teams[].alt), else null: the kit's blockPair takes it when two
   constructors' colours clash (Red Bull v Mercedes), before falling back to slate. */
function teamAlt(id) {
  var x = NAMES.teams[id];
  if (!x || !x.alt) return null;
  var c = String(x.alt);
  return c.charAt(0) === '#' ? c : '#' + c;
}
/* The team colour lifted to 3:1 on the current card surface (marks, bars, text accents). */
function tc(id) { return QK.color.team(teamColour(id)); }
function driverTeam(id) { return (NAMES.drivers[id] || {}).team || null; }
function driverColour(id, team) { var t = team || driverTeam(id); return t ? teamColour(t) : PALETTE[hashIndex(id || '', PALETTE.length)]; }
function compoundColour(c) { return COMPOUNDS[String(c || 'UNKNOWN').toUpperCase()] || COMPOUNDS.UNKNOWN; }
function teamDot(id) { return '<i class="pd-dot" style="--tc:' + esc(teamColour(id)) + '" aria-hidden="true"></i>'; }
/* Entity links carry the season: y, else the season of the page drawing the link; the current season adds nothing. */
function yTail(y) { var yy = y === undefined || y === null ? state.year : y; yy = parseInt(yy, 10); return !isNaN(yy) && yy !== currentSeason() ? '/' + yy : ''; }
function driverHref(id, y) { return '#/driver/' + encodeURIComponent(id) + yTail(y); }
function teamHref(id, y) { return '#/team/' + encodeURIComponent(id) + yTail(y); }
function raceHref(y, r, tab) { return '#/race/' + y + '/' + r + (tab ? '/' + tab : ''); }
/* opts: {name, code: true, team (dot colour), dot: false} or a name string. */
function driverLink(id, opts) {
  if (!id) return '<span class="qk-muted">—</span>';
  var o = typeof opts === 'string' ? { name: opts } : (opts || {});
  var label = o.name || (o.code ? driverCode(id) : driverName(id));
  var t = o.team || driverTeam(id);
  return '<a class="pd-link" href="' + driverHref(id, o.y) + '">' + (o.dot === false || !t ? '' : teamDot(t)) + esc(label) + '</a>';
}
function teamLink(id, opts) {
  if (!id) return '<span class="qk-muted">—</span>';
  var o = typeof opts === 'string' ? { name: opts } : (opts || {});
  return '<a class="pd-link" href="' + teamHref(id, o.y) + '">' + (o.dot === false ? '' : teamDot(id)) + esc(o.name || teamName(id)) + '</a>';
}
function circuitLink(id, name) { return id ? '<a class="pd-link" href="#/circuit/' + encodeURIComponent(id) + '">' + esc(name || circuitName(id)) + '</a>' : '<span class="qk-muted">—</span>'; }
function raceLink(y, r, label) { return '<a class="pd-link" href="' + raceHref(y, r) + '">' + esc(label || (y + ' R' + r)) + '</a>'; }
function mark(t, size) { return QK.teamMark({ name: teamName(t), abbr: teamAbbr(t), colour: teamColourRaw(t) }, size || 'sm'); }
function teamAbbr(t) {
  var n = teamName(t).replace(/ F1 Team| Racing| Formula One Team| Team/g, '');
  var w = n.split(/\s+/).filter(Boolean);
  return (w.length > 1 ? w.map(function (x) { return x.charAt(0); }).join('') : n.slice(0, 3)).slice(0, 3).toUpperCase();
}

// ── HTML builders (kit markup) ────────────────────────────────────────────

/* A card. opts: {id, cls, span (grid span 3..12), flush (no body padding), right (HTML in the head), foot, bodyId} */
function card(title, sub, body, opts) {
  var o = opts || {};
  return '<section class="qk-card' + (o.span ? ' qk-span-' + o.span : '') + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' +
    (title || o.right ? '<div class="qk-card-head"><div class="pd-card-titles">' + (title ? '<h3 class="qk-card-title">' + title + '</h3>' : '') + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '') +
    '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '"' + (o.bodyId ? ' id="' + esc(o.bodyId) + '"' : '') + '>' + (body || '') + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
}
function grid(html, cls) { return '<div class="qk-grid' + (cls ? ' ' + cls : '') + '">' + html + '</div>'; }
function chartBox(id, h, label) { return '<div id="' + esc(id) + '" class="pd-chart" style="--h:' + (h || 300) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; }
/* A stat tile (Design System 2.0, QK.statTile); value and sub are HTML (links allowed).
 * o: {text (a word or a name, not a number), signal (ours: the forecast or rating), pctl, tip, trend: [..], trendColor, href, unit, cls} */
function kpi(label, value, sub, o) {
  o = o || {};
  return QK.statTile({ label: label, value: value, sub: sub, html: true, cls: o.cls, tip: o.tip, text: o.text, signal: o.signal, pctl: o.pctl, trend: o.trend, trendColor: o.trendColor, trendLabel: o.trendLabel, href: o.href, unit: o.unit });
}
function kpis(list, cls) { return '<div class="qk-stats pd-kpis' + (cls ? ' ' + cls : '') + '">' + list.join('') + '</div>'; }
function chip(text, kind) { return '<span class="qk-badge' + (kind ? ' ' + kind : '') + '">' + esc(text) + '</span>'; }
function muted(text) { return '<p class="pd-muted">' + text + '</p>'; }
function empty(title, text) { return QK.empty(title, text); }
/* The kit's "i" explainer (QK.note): one or two friendly sentences on what a number means. */
function note(html) { return QK.note(html, { cls: 'pd-note' }); }
function aside(text) { return QK.aside(text); }
function notBuilt(what, d) { return empty(what + ' is not available', d && d.reason ? String(d.reason) : 'The payload is rebuilt after each session.'); }
/* Page head (Design System 2.0 section head, large, h1): kicker ("F1 · ..."), title, sub line (HTML; always present so a
 * page can fill it later through .qk-sh-sub), right-hand HTML (links, a pager). */
function pageHead(kicker, title, sub, right) {
  var k = kicker ? (/^F1\b/.test(String(kicker)) ? String(kicker) : 'F1 · ' + kicker) : 'F1';
  return '<header class="qk-sh lg pd-head"><div class="qk-sh-main"><div class="qk-sh-kicker">' + k + '</div><h1 class="qk-sh-title">' + esc(title) + '</h1><p class="qk-sh-sub">' + (sub || '') + '</p></div>' +
    (right ? '<div class="qk-sh-actions">' + right + '</div>' : '') + '</header>';
}
/* A section head inside a page (v2): kicker, title, sub (HTML), actions (HTML). */
function secHead(kicker, title, sub, actions) { return QK.sectionHead({ kicker: kicker, title: title, sub: sub, actions: actions, html: true }); }
/* Sub-navigation inside a section: [[href, label, key]], active key. */
function subnav(items, active, label) {
  return '<nav class="pd-subnav" aria-label="' + esc(label || 'Views') + '"><div class="qk-tabs" role="tablist">' + items.map(function (i) {
    return '<a class="qk-tab" role="tab" href="' + esc(i[0]) + '" aria-selected="' + (i[2] === active ? 'true' : 'false') + '"' + (i[2] === active ? ' aria-current="page"' : '') + '>' + esc(i[1]) + '</a>';
  }).join('') + '</div></nav>';
}
/* Segmented control. opts: [[value, label]]. Wire with wireSeg(root, id, cb). */
function seg(id, opts, cur, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label || 'View') + '">' + opts.map(function (o) {
    return '<button type="button" data-value="' + esc(o[0]) + '" aria-pressed="' + (String(o[0]) === String(cur) ? 'true' : 'false') + '">' + esc(o[1]) + '</button>';
  }).join('') + '</div>';
}
function wireSeg(root, id, cb) { var n = (root || document).querySelector('#' + id); if (n) QK.seg(n, cb); }
/* Year pager for season pages: ← prev · next → around y for route base. */
function yearPager(base, y) {
  var ys = ((INDEX.data || {}).seasons || [y]).slice().sort(function (a, b) { return a - b; });
  var i = ys.indexOf(y);
  var prev = i > 0 ? ys[i - 1] : null, next = i >= 0 && i < ys.length - 1 ? ys[i + 1] : null;
  return '<div class="pd-pager">' + (prev ? '<a class="qk-btn" href="#/' + base + '/' + prev + '">← ' + prev + '</a>' : '') + (next ? '<a class="qk-btn" href="#/' + base + '/' + next + '">' + next + ' →</a>' : '') + '</div>';
}
/* A kit table. cols: [{key, label, num, fmt(v, row) -> html, sort: false, tip, sticky, cls, pctl}], rows: objects.
 * opts: {sort: {key, dir}, rank, dense (default true), maxHeight, caption, rowClass(row) -> 'hl'}. Returns the QK.table handle. */
function table(el, cols, rows, opts) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  var o = opts || {};
  return QK.table(node, { columns: cols, rows: rows, sort: o.sort || null, rank: !!o.rank, dense: o.dense !== false, maxHeight: o.maxHeight, caption: o.caption, rowClass: o.rowClass });
}
function set(id, html) { var n = document.getElementById(id); if (n) n.innerHTML = html; return n; }
function alive(el) { return !!el && el.isConnected; }
function pctl(p) { return QK.pctlChip(p); }
function probBar(p, colour, max, text) {
  if (!isNum(p)) return '<span class="qk-muted">—</span>';
  var w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="pd-pbar"><span class="pd-pbar-t"><span style="width:' + w.toFixed(1) + '%;background:' + esc(colour || 'var(--c-1)') + '"></span></span><span class="pd-pbar-v">' + (text || pct(p)) + '</span></span>';
}
function deltaHTML(v, d) { return !isNum(v) ? '<span class="qk-muted">—</span>' : '<span class="' + (v > 0 ? 'pd-up' : v < 0 ? 'pd-down' : '') + '">' + signed(v, d === undefined ? 0 : d) + '</span>'; }
function posHTML(p, status) {
  if (!isNum(p)) return '<span class="qk-muted">—</span>';
  if (status && !finished(status)) return '<span class="pd-dnf" title="' + esc(status) + '">' + (/disq/i.test(status) ? 'DSQ' : 'DNF') + '</span>';
  return '<span class="pd-pos' + (p <= 3 ? ' p' + p : '') + '">P' + p + '</span>';
}
/* HTML heat table with kit diverging colours. spec: {corner, cols:[label|{label,title}], rows:[{label(html), values, titles}], fmt, center:'col'|number, invert, scale:'seq'} */
function heatTable(spec) {
  var s = spec || {};
  var rows = s.rows || [];
  if (!rows.length) return muted('No data.');
  var nCols = Math.max.apply(null, rows.map(function (r) { return (r.values || []).length; }));
  var centers = [];
  for (var i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(isNum(s.center) ? s.center : 0); continue; }
    centers.push(median(rows.map(function (r) { return (r.values || [])[i]; })) || 0);
  }
  var dev = [];
  rows.forEach(function (r) { (r.values || []).forEach(function (v, k) { if (isNum(v)) dev.push(Math.abs(v - centers[k])); }); });
  dev.sort(function (a, b) { return a - b; });
  var max = s.max || dev[Math.floor(dev.length * 0.95)] || dev[dev.length - 1] || 1;
  var f = s.fmt || function (v) { return num(v, 2); };
  var colour = function (v, k) {
    var t = Math.max(-1, Math.min(1, (v - centers[k]) / max));
    if (s.invert) t = -t;
    var a = Math.round(Math.abs(t) * 60);   /* 60% at most: white figures stay above 4.5:1 on the strongest cell */
    return 'color-mix(in srgb, ' + (t < 0 ? 'var(--div-neg)' : 'var(--div-pos)') + ' ' + a + '%, transparent)';
  };
  var h = '<div class="qk-table-wrap pd-heat-wrap"><table class="qk-table dense pd-heat"><thead><tr><th class="sticky-col">' + esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(function (c) { var cc = typeof c === 'object' ? c : { label: c }; h += '<th class="num"' + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(function (r) {
    h += '<tr><td class="sticky-col">' + (r.label || '') + '</td>';
    (r.values || []).forEach(function (v, k) {
      var t = r.titles && r.titles[k] ? ' title="' + esc(r.titles[k]) + '"' : '';
      h += isNum(v) ? '<td class="num pd-heat-c" style="background:' + colour(v, k) + '"' + t + '>' + f(v) + '</td>' : '<td class="num pd-heat-c qk-muted"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}

// ── season and shell ──────────────────────────────────────────────────────

function currentSeason() { var d = INDEX.data; return d && d.current_season ? d.current_season : new Date().getFullYear(); }
/* Year-scoped sections: the season select keeps them on the picked season. */
var YEAR_BASES = { races: 'races', standings: 'standings', constructors: 'constructors', value: 'value' };
function setYear(y, silent) {
  var yy = parseInt(y, 10);
  if (isNaN(yy)) return;
  state.year = yy;
  var sel = document.getElementById('pd-season');
  if (sel && String(sel.value) !== String(yy)) {
    if (!Array.prototype.some.call(sel.options, function (o) { return o.value === String(yy); })) sel.insertAdjacentHTML('beforeend', '<option value="' + yy + '">' + yy + '</option>');
    sel.value = String(yy);
  }
  updateSectionHrefs();
  if (!silent) {
    var base = YEAR_BASES[state.route];
    var ent = { driver: 'driver', team: 'team' }[state.route];
    if (state.route === 'scout') { var q0 = Object.assign({}, state.params.query || {}); q0.s = yy !== currentSeason() ? yy : null; q0.p = null; go('#/scout' + qs(q0)); return; }
    if (ent && state.params && state.params.id) { go('#/' + ent + '/' + encodeURIComponent(state.params.id) + (yy !== currentSeason() ? '/' + yy : '') + qs(state.params.query)); return; }
    go('#/' + (base || 'standings') + '/' + yy);
  }
}
function updateSectionHrefs() {
  var y = state.year, cur = currentSeason();
  var tail = y && y !== cur ? '/' + y : '';
  var map = { fixtures: '#/races' + tail, standings: '#/standings' + tail, teams: '#/constructors' + tail, scout: '#/scout' + (tail ? '?s=' + y : ''), value: '#/value' + (y && y !== cur && y >= 1994 ? '/' + y : '') };
  Array.prototype.forEach.call(document.querySelectorAll('.qk-secnav a[data-sec]'), function (a) { var k = a.getAttribute('data-sec'); if (map[k]) a.setAttribute('href', map[k]); });
}
function index() { return INDEX.data; }

function searchRows() {
  var y = currentSeason();
  return loadAll(['elo.json', 'circuits.json', y + '/season.json']).then(function (arr) {
    var rows = [], seen = {};
    function add(key, t, s, href) { if (seen[key]) return; seen[key] = 1; rows.push({ sport: 'f1', t: t, s: s, href: href }); }
    var idx = INDEX.data || {};
    Object.keys(idx.drivers || {}).forEach(function (id) { var x = idx.drivers[id]; add('d:' + id, x.name || titleCase(id), 'Driver · ' + teamName(x.team) + (x.number ? ' · #' + x.number : ''), driverHref(id, y)); });
    Object.keys(idx.teams || {}).forEach(function (id) { add('t:' + id, teamName(id), 'Constructor · ' + y, teamHref(id, y)); });
    ((arr[0] || {}).all_time || []).forEach(function (x) { add('d:' + x.driver, x.name || titleCase(x.driver), 'Driver · ' + (x.years || []).join('–'), driverHref(x.driver, y)); });
    Object.keys(NAMES.drivers).forEach(function (id) { add('d:' + id, driverName(id), 'Driver', driverHref(id, y)); });
    Object.keys(NAMES.teams).forEach(function (id) { add('t:' + id, teamName(id), 'Constructor', teamHref(id, y)); });
    var circ = arr[1] || {};
    Object.keys(circ).forEach(function (id) { var c = circ[id]; if (c && c.name) add('c:' + id, c.name, 'Circuit · ' + (c.country || '') + ((c.history || []).length ? ' · ' + c.history.length + ' races' : ''), '#/circuit/' + id); });
    var s = arr[2];
    if (ok(s)) (s.calendar || []).forEach(function (c) { add('r:' + c.round, s.year + ' ' + c.name, 'Race · round ' + c.round + ' · ' + fmtDate(c.date, { weekday: false }), raceHref(s.year, c.round)); });
    [['Standings', '#/standings'], ['Title chances', '#/standings?tab=odds'], ['Driver value', '#/value'], ['Driver-swap simulator', '#/value?tab=swap'], ['Fantasy', '#/fantasy'], ['Scouting Room', '#/scout'], ['Build your own chart', '#/scout?view=chart'], ['Compare drivers', '#/scout'], ['Teams: head to head', '#/constructors?sec=h2h'], ['How it works', '#/methodology'], ['How we’re doing', '#/model'], ['Glossary', '#/glossary']]
      .forEach(function (p) { add('p:' + p[0], p[0], 'Page', p[1]); });
    return rows;
  });
}

function bootShell() {
  var idx = INDEX.data || {};
  var years = (idx.seasons && idx.seasons.length ? idx.seasons.slice() : [currentSeason()]).sort(function (a, b) { return b - a; });
  var ctx = '<label class="pd-season"><select class="qk-select" id="pd-season" aria-label="Season">' +
    years.map(function (y) { return '<option value="' + y + '">' + y + '</option>'; }).join('') + '</select></label>';
  /* round 9: the Scouting Room in the Drivers slot (QK.sections scout: Drivers and the Lab become #/scout) */
  var secs = QK.sections('f1', { scout: true }).map(function (s) {
    s.href = { overview: '#/', fixtures: '#/races', standings: '#/standings', teams: '#/constructors', scout: '#/scout', value: '#/value', fantasy: '#/fantasy', model: '#/model' }[s.key] || s.href;
    return s;
  });
  SHELL = QK.shell({ sport: 'f1', section: 'overview', sections: secs, ctx: ctx, search: { load: searchRows } });
  var sel = document.getElementById('pd-season');
  if (sel) { sel.value = String(state.year || currentSeason()); sel.addEventListener('change', function () { setYear(sel.value); }); }
  var foot = document.getElementById('qk-footer');
  if (foot) foot.insertAdjacentHTML('beforeend', '<div class="pd-footnote">Data from Jolpica-F1 and OpenF1 · Monte Carlo race and championship model · ' +
    (idx.updated_at ? 'updated ' + esc(fmtStamp(idx.updated_at)) + ' · ' : '') + '<a href="#/disclaimer">Disclaimer and terms</a> · <a href="#/methodology">Methodology</a></div>');
  // first-visit notice
  var fv = document.getElementById('first-visit-notice');
  var seen = false;
  try { seen = window.localStorage.getItem('qp-notice-v1') === '1'; } catch (e) { seen = false; }
  if (fv && !seen) fv.hidden = false;
  var btn = document.getElementById('fv-dismiss');
  if (btn) btn.addEventListener('click', function () { fv.hidden = true; try { window.localStorage.setItem('qp-notice-v1', '1'); } catch (e) { /* private mode */ } });
}

function init() {
  load('index.json').then(function (idx) {
    INDEX.data = idx || {};
    state.year = state.year || currentSeason();
    bootShell();
    setYear(state.year, true);
    booted = true;
    window.addEventListener('hashchange', render);
    render();
  });
}

return {
  state: state, route: route, go: go, render: render, parseHash: parseHash, redirectFor: redirectFor, fixLinks: fixLinks,
  ROUTES: ROUTES, ROUTE_MAP: ROUTE_MAP, onLeave: onLeave, interval: interval, setHashQuiet: setHashQuiet, init: init, qs: qs,
  load: load, loadAll: loadAll, ok: ok, reason: reason, index: index, currentSeason: currentSeason, setYear: setYear, NAMES: NAMES,
  esc: esc, num: num, int: int, pts: pts, pct: pct, chance: chance, titlePct: titlePct, signed: signed, fmtMs: fmtMs, fmtGap: fmtGap, fmtDate: fmtDate, fmtTime: fmtTime,
  fmtStamp: fmtStamp, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  shortRace: shortRace, median: median, mean: mean, rowsOf: rowsOf, ageOf: ageOf, finished: finished,
  driverName: driverName, driverCode: driverCode, driverSurname: driverSurname, teamName: teamName, circuitName: circuitName, teamAbbr: teamAbbr,
  teamColour: teamColour, teamColourRaw: teamColourRaw, teamAlt: teamAlt, tc: tc, driverTeam: driverTeam, driverColour: driverColour, compoundColour: compoundColour, COMPOUNDS: COMPOUNDS, PALETTE: PALETTE,
  teamDot: teamDot, driverLink: driverLink, teamLink: teamLink, circuitLink: circuitLink, raceLink: raceLink, raceHref: raceHref, driverHref: driverHref, teamHref: teamHref, mark: mark,
  card: card, grid: grid, chartBox: chartBox, kpi: kpi, kpis: kpis, chip: chip, muted: muted, empty: empty, note: note, aside: aside, notBuilt: notBuilt, col: col,
  pageHead: pageHead, secHead: secHead, subnav: subnav, seg: seg, wireSeg: wireSeg, yearPager: yearPager, table: table, set: set, alive: alive, pctl: pctl,
  probBar: probBar, deltaHTML: deltaHTML, posHTML: posHTML, heatTable: heatTable
};
})();
