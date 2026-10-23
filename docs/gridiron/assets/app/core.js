/* The Quant Gridiron — core: state, routing (with the old-route redirect map), cached loading, names
 * and colours, formatting, football vocabulary, the catalogue helpers and the HTML builders every page
 * uses. Built on the shared kit (assets/qk: window.QK, window.QKC).
 * Older-browser rule shared with the kit: no optional chaining, no nullish coalescing.
 *
 * Routes (hash). The section lit in the nav is in brackets.
 *   #/                                              overview                        [overview]
 *   #/games[/<S>[/<w>]]  #/game/<game_id>           a week of games, game centre    [fixtures]
 *   #/standings[/<S>][?v=table|conf|ratings|wins|draft]  #/playoffs[/<S>]  #/futures   [standings]
 *   #/teams  #/team/<abbr>                                                          [teams]
 *   #/players[?g=]  #/player/<pid>  #/leaders  #/history                            [players]
 *   #/value  #/trade  #/transactions                                                [value]
 *   #/fantasy                                                                       [fantasy]
 *   #/lab  #/compare[/<a>[/<b>]]  #/fourth-downs  #/coaches  #/coach/<name>         [lab]
 *   #/model  #/calibration  #/methodology[/<sec>]  #/glossary[/<key>]  #/disclaimer  [model]
 * Any page takes ?s=<season>. Old routes are redirected through ROUTE_MAP so every shared link lands.
 *
 * A page registers with GI.route(name, fn); fn(el, params, state) renders into el (a fresh div,
 * detached when the viewer navigates away: test el.isConnected after any await) and may return a
 * Promise. params: named segments, season, week, query. */
window.GI = (function () {
'use strict';

const QK = window.QK;
const SITE = 'The Quant Gridiron';
const FIRST_SEASON = 1999;

// ── teams ─────────────────────────────────────────────────────────────────

/* nflverse abbreviations -> [name, nickname, conference, division, colour, alt]. */
const NFL_TEAMS = {
  ARI: ['Arizona Cardinals', 'Cardinals', 'NFC', 'NFC West', '#97233f', '#000000'],
  ATL: ['Atlanta Falcons', 'Falcons', 'NFC', 'NFC South', '#a71930', '#000000'],
  BAL: ['Baltimore Ravens', 'Ravens', 'AFC', 'AFC North', '#241773', '#9e7c0c'],
  BUF: ['Buffalo Bills', 'Bills', 'AFC', 'AFC East', '#00338d', '#c60c30'],
  CAR: ['Carolina Panthers', 'Panthers', 'NFC', 'NFC South', '#0085ca', '#101820'],
  CHI: ['Chicago Bears', 'Bears', 'NFC', 'NFC North', '#0b162a', '#c83803'],
  CIN: ['Cincinnati Bengals', 'Bengals', 'AFC', 'AFC North', '#fb4f14', '#000000'],
  CLE: ['Cleveland Browns', 'Browns', 'AFC', 'AFC North', '#311d00', '#ff3c00'],
  DAL: ['Dallas Cowboys', 'Cowboys', 'NFC', 'NFC East', '#003594', '#869397'],
  DEN: ['Denver Broncos', 'Broncos', 'AFC', 'AFC West', '#fb4f14', '#002244'],
  DET: ['Detroit Lions', 'Lions', 'NFC', 'NFC North', '#0076b6', '#b0b7bc'],
  GB: ['Green Bay Packers', 'Packers', 'NFC', 'NFC North', '#203731', '#ffb612'],
  HOU: ['Houston Texans', 'Texans', 'AFC', 'AFC South', '#03202f', '#a71930'],
  IND: ['Indianapolis Colts', 'Colts', 'AFC', 'AFC South', '#002c5f', '#a2aaad'],
  JAX: ['Jacksonville Jaguars', 'Jaguars', 'AFC', 'AFC South', '#101820', '#d7a22a'],
  KC: ['Kansas City Chiefs', 'Chiefs', 'AFC', 'AFC West', '#e31837', '#ffb81c'],
  LA: ['Los Angeles Rams', 'Rams', 'NFC', 'NFC West', '#003594', '#ffa300'],
  LAC: ['Los Angeles Chargers', 'Chargers', 'AFC', 'AFC West', '#0080c6', '#ffc20e'],
  LV: ['Las Vegas Raiders', 'Raiders', 'AFC', 'AFC West', '#000000', '#a5acaf'],
  MIA: ['Miami Dolphins', 'Dolphins', 'AFC', 'AFC East', '#008e97', '#fc4c02'],
  MIN: ['Minnesota Vikings', 'Vikings', 'NFC', 'NFC North', '#4f2683', '#ffc62f'],
  NE: ['New England Patriots', 'Patriots', 'AFC', 'AFC East', '#002244', '#c60c30'],
  NO: ['New Orleans Saints', 'Saints', 'NFC', 'NFC South', '#d3bc8d', '#101820'],
  NYG: ['New York Giants', 'Giants', 'NFC', 'NFC East', '#0b2265', '#a71930'],
  NYJ: ['New York Jets', 'Jets', 'AFC', 'AFC East', '#125740', '#000000'],
  PHI: ['Philadelphia Eagles', 'Eagles', 'NFC', 'NFC East', '#004c54', '#a5acaf'],
  PIT: ['Pittsburgh Steelers', 'Steelers', 'AFC', 'AFC North', '#ffb612', '#101820'],
  SEA: ['Seattle Seahawks', 'Seahawks', 'NFC', 'NFC West', '#002244', '#69be28'],
  SF: ['San Francisco 49ers', '49ers', 'NFC', 'NFC West', '#aa0000', '#b3995d'],
  TB: ['Tampa Bay Buccaneers', 'Buccaneers', 'NFC', 'NFC South', '#d50a0a', '#ff7900'],
  TEN: ['Tennessee Titans', 'Titans', 'AFC', 'AFC South', '#0c2340', '#4b92db'],
  WAS: ['Washington Commanders', 'Commanders', 'NFC', 'NFC East', '#5a1414', '#ffb612'],
  OAK: ['Oakland Raiders', 'Raiders', 'AFC', 'AFC West', '#000000', '#a5acaf'],
  SD: ['San Diego Chargers', 'Chargers', 'AFC', 'AFC West', '#0080c6', '#ffc20e'],
  STL: ['St. Louis Rams', 'Rams', 'NFC', 'NFC West', '#002244', '#b3995d']
};
const TEAM_ALIASES = { LAR: 'LA', WSH: 'WAS', JAC: 'JAX', LVR: 'LV', ARZ: 'ARI', BLT: 'BAL', CLV: 'CLE', HST: 'HOU' };
const DIVISIONS = ['AFC East', 'AFC North', 'AFC South', 'AFC West', 'NFC East', 'NFC North', 'NFC South', 'NFC West'];
const CONFERENCES = ['AFC', 'NFC'];
const GTYPE_LONG = { REG: 'Regular season', WC: 'Wild Card', DIV: 'Divisional round', CON: 'Conference championship', SB: 'Super Bowl', PRE: 'Preseason' };
const GTYPE_SHORT = { REG: 'Reg', WC: 'WC', DIV: 'DIV', CON: 'CONF', SB: 'SB', PRE: 'Pre' };
const POST_KEYS = ['WC', 'DIV', 'CON', 'SB'];
/* Drive results -> [label, colour] (kit v3 status colours: up green, sun, down coral-red, warm grey). */
const DRIVE_RESULTS = {
  touchdown: ['Touchdown', '#5fd38a'], td: ['Touchdown', '#5fd38a'],
  field_goal: ['Field goal', '#ffc94d'], fg: ['Field goal', '#ffc94d'],
  missed_field_goal: ['Missed FG', '#d9b38c'], missed_fg: ['Missed FG', '#d9b38c'], blocked_fg: ['Blocked FG', '#d9b38c'],
  punt: ['Punt', '#8a93a3'], blocked_punt: ['Blocked punt', '#ff6a4d'],
  turnover: ['Turnover', '#ff6a4d'], interception: ['Interception', '#ff6a4d'], int: ['Interception', '#ff6a4d'], fumble: ['Fumble', '#ff6a4d'],
  fumble_lost: ['Fumble', '#ff6a4d'], fumble_return_td: ['Fumble (TD)', '#ff6a4d'], int_td: ['Pick-six', '#ff6a4d'],
  turnover_on_downs: ['Downs', '#ff9a6b'], downs: ['Downs', '#ff9a6b'],
  safety: ['Safety', '#c39be8'],
  end_of_half: ['End of half', '#6b7383'], end_of_game: ['End of game', '#6b7383'], end_of_period: ['End of half', '#6b7383'],
  opp_touchdown: ['Opp. touchdown', '#ff6a4d'], kneel: ['Kneel', '#6b7383']
};
const GOOD = '#5fd38a', CLOSE = '#ffc94d', BAD = '#ff6a4d';
const PALETTE = ['#3987e5', '#ff9a6b', '#5fd38a', '#c39be8', '#ffc94d', '#46b9c9', '#ff6a4d', '#8e8cf0', '#7ee787', '#ff9bce'];

// ── state and registries ──────────────────────────────────────────────────

const state = { season: null, week: null, route: null, section: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = {};      // pid -> {name, team, pos, first, last}
const TEAMS = {};      // abbr -> {abbr, name, short, conference, division, colour, alt}
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];
let SHELL = null;

Object.keys(NFL_TEAMS).forEach(t => {
  const r = NFL_TEAMS[t];
  TEAMS[t] = { abbr: t, name: r[0], short: r[1], conference: r[2], division: r[3], colour: r[4], alt: r[5] };
});

const ROUTES = [];
function addRoute(pattern, name, section) { ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, section: section }); }
addRoute('', 'overview', 'overview');
addRoute('games', 'games', 'fixtures');
addRoute('games/:S', 'games', 'fixtures');
addRoute('games/:S/:w', 'games', 'fixtures');
addRoute('game/:id', 'game', 'fixtures');
addRoute('standings', 'standings', 'standings');
addRoute('standings/:S', 'standings', 'standings');
addRoute('playoffs', 'playoffs', 'standings');
addRoute('playoffs/:S', 'playoffs', 'standings');
addRoute('futures', 'futures', 'standings');
addRoute('teams', 'teams', 'teams');
addRoute('team/:id', 'team', 'teams');
addRoute('players', 'players', 'players');
addRoute('player/:id', 'player', 'players');
addRoute('leaders', 'leaders', 'players');
addRoute('history', 'history', 'players');
addRoute('value', 'value', 'value');
addRoute('trade', 'trade', 'value');
addRoute('transactions', 'transactions', 'value');
addRoute('fantasy', 'fantasy', 'fantasy');
addRoute('lab', 'lab', 'lab');
addRoute('compare', 'compare', 'lab');
addRoute('compare/:a', 'compare', 'lab');
addRoute('compare/:a/:b', 'compare', 'lab');
addRoute('compare/:a/:b/:c', 'compare', 'lab');
addRoute('fourth-downs', 'fourth', 'lab');
addRoute('coaches', 'coaches', 'lab');
addRoute('coach/:id', 'coach', 'lab');
addRoute('model', 'calibration', 'model');
addRoute('calibration', 'calibration', 'model');
addRoute('methodology', 'methodology', 'model');
addRoute('methodology/:sec', 'methodology', 'model');
addRoute('glossary', 'glossary', 'model');
addRoute('glossary/:id', 'glossary', 'model');
addRoute('disclaimer', 'disclaimer', 'model');

/* Old hash routes -> their new home: [from pattern, to template, extra query]. ':x' captures carry
 * over and the old query string is kept (#/trade?t=&m=, #/fantasy?f=&tab=, #/lab?g=&x=&y=). */
const ROUTE_MAP = [
  ['hub', ''], ['home', ''], ['index', ''],
  ['week', 'games'], ['week/:S', 'games/:S'], ['week/:S/:w', 'games/:S/:w'],
  ['schedule', 'games'], ['scores', 'games'],
  ['markets', 'futures'],
  ['bracket', 'playoffs'], ['postseason', 'playoffs'], ['bracket/:S', 'playoffs/:S'], ['postseason/:S', 'playoffs/:S'],
  ['docs', 'methodology'], ['leaderboards', 'leaders'],
  ['fourth', 'fourth-downs'], ['fourth_downs', 'fourth-downs'], ['fourthdowns', 'fourth-downs'],
  ['referees', 'coaches']
];

const TITLES = {
  overview: '', games: 'Games', game: 'Game centre', standings: 'Standings', playoffs: 'Playoff picture', futures: 'Season forecasts',
  teams: 'Teams', team: 'Team', players: 'Players', player: 'Player', leaders: 'Leaders', history: 'All-time',
  value: 'Player value', trade: 'Trade simulator', transactions: 'Transactions', fantasy: 'Fantasy',
  lab: 'Lab', compare: 'Compare', fourth: 'Fourth downs', coaches: 'Coaches', coach: 'Coach',
  calibration: 'Calibration', methodology: 'Methodology', glossary: 'Glossary', disclaimer: 'Disclaimer and terms'
};

function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
function splitHash(hash) {
  let h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  const query = {};
  const qi = h.indexOf('?');
  if (qi >= 0) {
    h.slice(qi + 1).split('&').forEach(kv => {
      if (!kv) return;
      const i = kv.indexOf('=');
      query[dec(i >= 0 ? kv.slice(0, i) : kv)] = i >= 0 ? dec(kv.slice(i + 1)) : '';
    });
    h = h.slice(0, qi);
  }
  return { parts: h.split('/').filter(s => s !== '').map(dec), query: query };
}
function qs(query) {
  const ks = Object.keys(query || {}).filter(k => query[k] !== undefined && query[k] !== null && query[k] !== '');
  return ks.length ? '?' + ks.map(k => encodeURIComponent(k) + '=' + encodeURIComponent(query[k])).join('&') : '';
}
function matchSegs(segs, parts) {
  if (segs.length !== parts.length) return null;
  const p = {};
  for (let i = 0; i < segs.length; i++) {
    if (segs[i].charAt(0) === ':') p[segs[i].slice(1)] = parts[i];
    else if (segs[i] !== parts[i]) return null;
  }
  return p;
}
/* The new hash for an old route, or null when the route is current. */
function redirectFor(hash) {
  const s = splitHash(hash);
  for (let i = 0; i < ROUTE_MAP.length; i++) {
    const m = ROUTE_MAP[i];
    const p = matchSegs(m[0] ? m[0].split('/') : [], s.parts);
    if (!p) continue;
    const to = m[1].split('/').filter(Boolean).map(seg => (seg.charAt(0) === ':' ? encodeURIComponent(p[seg.slice(1)]) : seg)).join('/');
    return '#/' + to + qs(Object.assign({}, m[2] || {}, s.query));
  }
  return null;
}
/* Rewrite href="#/old" links inside a block of static HTML to their new homes. */
function fixLinks(html) {
  return String(html || '').replace(/href="(#\/[^"]*)"/g, (all, h) => { const r = redirectFor(h.replace(/&amp;/g, '&')); return r ? 'href="' + r + '"' : all; });
}
function parseHash(hash) {
  const s = splitHash(hash);
  let best = null, params = null;
  for (let i = 0; i < ROUTES.length; i++) {
    const p = matchSegs(ROUTES[i].segs, s.parts);
    if (p && (p.S === undefined || /^\d{4}$/.test(p.S))) { best = ROUTES[i]; params = p; break; }
  }
  if (!best) return { name: 'notfound', section: null, params: { query: s.query, rest: s.parts } };
  params.query = s.query;
  let S = params.S ? parseInt(params.S, 10) : NaN;
  if (isNaN(S)) { const q = s.query.s || s.query.season || s.query.y; S = q ? parseInt(q, 10) : NaN; }
  if (isNaN(S) && best.name === 'game' && params.id) S = gameSeason(params.id) || NaN;
  params.season = isNaN(S) ? undefined : S;
  let w = params.w !== undefined ? weekNum(params.w, params.season) : null;
  if (w === null && s.query.w) w = weekNum(s.query.w, params.season);
  if (w === null && best.name === 'game' && params.id) w = gameWeek(params.id);
  params.week = w === null ? undefined : w;
  return { name: best.name, section: best.section, params: params };
}

function route(name, fn) { HANDLERS[name] = fn; if (booted && state.route === name) render(); }
function onLeave(fn) { if (typeof fn === 'function') CLEANUPS.push(fn); }
function interval(fn, ms) { const id = setInterval(fn, ms); onLeave(() => clearInterval(id)); return id; }
function runCleanups() {
  const list = CLEANUPS; CLEANUPS = [];
  list.forEach(fn => { try { fn(); } catch (e) { if (window.console) console.warn('cleanup failed', e); } });
}

let booted = false, renderSeq = 0;
function render(opts) {
  const keep = !!(opts && opts.keep === true);
  const y0 = window.scrollY;
  const red = redirectFor(location.hash);
  if (red) { try { history.replaceState(null, '', red); } catch (e) { location.hash = red; return; } }
  runCleanups();
  const r = parseHash();
  const S = r.params.season || currentSeason();
  r.params.season = S;
  r.params.week = isNum(r.params.week) ? r.params.week : (S === currentSeason() ? currentWeek() : 1);
  state.season = S;
  state.week = r.params.week;
  state.route = r.name;
  state.section = r.section;
  state.params = r.params;
  state.hash = location.hash || '#/';
  syncShell();
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'gi-page gi-page-' + r.name;
  app.appendChild(el);
  document.title = (TITLES[r.name] ? TITLES[r.name] + ' · ' : '') + SITE;
  if (!keep) window.scrollTo(0, 0);
  const fn = HANDLERS[r.name];
  if (!fn) {
    el.innerHTML = pageHead('Not found', 'Page not found', 'There is no page at ' + esc(location.hash) + '. Try the overview or search (press /).') +
      '<p><a class="qk-btn" href="#/">Back to the overview</a></p>';
    return;
  }
  const seq = ++renderSeq;
  el.innerHTML = QK.skeleton('lines', 6);
  ensureNames().then(() => {
    if (seq !== renderSeq || !el.isConnected) return;
    el.innerHTML = '';
    try {
      const out = fn(el, r.params, state);
      if (out && typeof out.then === 'function') out.then(() => { if (keep) window.scrollTo(0, y0); }, err => showError(el, err));
      else if (keep) window.scrollTo(0, y0);
    } catch (err) { showError(el, err); }
  });
}
function showError(el, err) {
  if (window.console) console.error(err);
  if (el) el.insertAdjacentHTML('afterbegin', '<div class="gi-error" data-route-error role="alert">This page could not be shown: ' + esc(err && err.message ? err.message : err) + '</div>');
}
function go(hash) {
  const h = hash.charAt(0) === '#' ? hash : '#/' + hash.replace(/^\/+/, '');
  if (location.hash === h) render(); else location.hash = h;
}
/* Replace the hash without a new history entry or a re-render (shareable page state). */
function setHashQuiet(h) { try { history.replaceState(null, '', h); state.hash = h; } catch (e) { /* old browsers */ } }

// ── loading ───────────────────────────────────────────────────────────────

/* Cached fetch of data/<path>: the parsed JSON, or null when missing or broken. */
function load(p0) {
  const p = String(p0).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(d => { learn(p, d); return d; })
    .catch(() => null)
    .then(d => { if (d !== null) CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
function loadAll(paths) { return Promise.all(paths.map(load)); }
function uncache(paths) { (Array.isArray(paths) ? paths : [paths]).forEach(p0 => { delete CACHE[String(p0).replace(/^\/+/, '').replace(/^data\//, '')]; }); }
function refreshIndex() { uncache('index.json'); return load('index.json').then(d => { if (d) INDEX.data = d; return INDEX.data; }); }
/* Every ms while visible: forget `paths`, refresh index.json and re-render the page in place. */
function liveRefresh(paths, ms) {
  interval(() => {
    if (document.visibilityState !== 'visible') return;
    uncache(paths || []);
    refreshIndex().then(() => render({ keep: true }));
  }, ms || 60000);
}
function ok(d) { return !!d && d.ok !== false; }
function reason(d) { return d && d.reason ? String(d.reason) : 'not built yet'; }
function ypath(file, S) { return (S || state.season || currentSeason()) + '/' + file; }
function loadYear(file, S) { return load(ypath(file, S)); }
function weekPath(w, S) { return ypath('weeks/' + w + '.json', S); }
function loadWeek(w, S) { return load(weekPath(w, S)); }
function gamePath(id) { return ypath('games/' + id + '.json', gameSeason(id)); }
function loadGame(id) { return load(gamePath(id)); }
function loadPlayer(pid) { return load('players/' + pid + '.json'); }
let namesP = null;
function ensureNames() { if (!namesP) namesP = load('players_index.json'); return namesP; }

function canonTeam(t) { const s = String(t || '').toUpperCase(); return TEAM_ALIASES[s] || s; }
function putTeam(abbr0, x) {
  const abbr = canonTeam(abbr0);
  if (!abbr || !x || typeof x !== 'object' || !/^[A-Z]{2,3}$/.test(abbr)) return;
  const o = {};
  ['name', 'short', 'nickname', 'conference', 'division', 'colour', 'alt', 'city', 'stadium'].forEach(k => { if (x[k] !== undefined && x[k] !== null && x[k] !== '') o[k] = x[k]; });
  if (x.color && !o.colour) o.colour = x.color;
  if (x.nickname && !o.short) o.short = x.nickname;
  if (x.conf && !o.conference) o.conference = x.conf;
  if (o.colour && !/^#/.test(o.colour)) o.colour = '#' + o.colour;
  if (o.alt && !/^#/.test(o.alt)) o.alt = '#' + o.alt;
  TEAMS[abbr] = Object.assign({}, TEAMS[abbr] || { abbr: abbr }, o);
}
function putPlayer(pid, info) {
  if (!pid || !info) return;
  const o = {};
  Object.keys(info).forEach(k => { if (info[k] !== undefined && info[k] !== null && info[k] !== '') o[k] = info[k]; });
  NAMES[pid] = Object.assign({}, NAMES[pid] || {}, o);
}
function learn(p, d) {
  if (!d || typeof d !== 'object') return;
  try {
    if (p === 'players_index.json') {
      const P = d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : d;
      Object.keys(P).forEach(id => {
        const r = P[id];
        if (Array.isArray(r)) putPlayer(id, { name: r[0], team: r[1], pos: r[2], first: r[3], last: r[4] });
        else if (r && typeof r === 'object' && r.name) putPlayer(id, r);
      });
      return;
    }
    if (d.teams && typeof d.teams === 'object' && !Array.isArray(d.teams)) {
      Object.keys(d.teams).forEach(t => { const x = d.teams[t]; if (x && typeof x === 'object' && (x.name || x.colour || x.color || x.division)) putTeam(t, x); });
    }
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(id => { const n = d.names[id]; if (typeof n === 'string' && !(NAMES[id] || {}).name) putPlayer(id, { name: n }); });
    }
    if (/^players\/[^/]+\.json$/.test(p) && d.name) putPlayer(String(d.id || p.split('/').pop().replace('.json', '')), { name: d.name, pos: d.pos });
    if (d.players && typeof d.players === 'object' && !Array.isArray(d.players)) {
      Object.keys(d.players).forEach(id => { const x = d.players[id] || {}; if (x.name && !(NAMES[id] || {}).name) putPlayer(id, { name: x.name, team: x.team, pos: x.pos }); });
    }
  } catch (e) { if (window.console) console.warn('learn failed for', p, e); }
}

// ── formatting ────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function int(v) { return isNum(v) ? Math.round(Number(v)).toLocaleString('en-US') : '—'; }
function num(v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; }
function pct(p, d) {
  if (!isNum(p)) return '—';
  const dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
}
function signed(v, d) {
  if (!isNum(v)) return '—';
  let s = Number(v).toFixed(d === undefined ? 1 : d);
  if (/^-0\.?0*$/.test(s)) s = s.slice(1);
  return (Number(s) > 0 ? '+' : Number(s) < 0 ? '−' : '') + s.replace(/^-/, '');
}
function pp(a, b, d) { return isNum(a) && isNum(b) ? signed((a - b) * 100, d === undefined ? 1 : d) + ' pts' : '—'; }
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  let str = String(s);
  if (/^\d{8}$/.test(str)) str = str.slice(0, 4) + '-' + str.slice(4, 6) + '-' + str.slice(6);
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?$/.test(str)) str += 'Z';
  const d = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
  return isNaN(d.getTime()) ? null : d;
}
function fmtDate(s, opts) {
  const o = typeof opts === 'boolean' ? { year: opts } : (opts || {});
  const d = parseDate(s);
  if (!d) return '—';
  const plain = String(s).length === 10;
  const day = plain ? d.getUTCDay() : d.getDay(), dd = plain ? d.getUTCDate() : d.getDate(), mm = plain ? d.getUTCMonth() : d.getMonth(), yy = plain ? d.getUTCFullYear() : d.getFullYear();
  let out = (o.weekday === false ? '' : DAYS[day] + ' ') + dd + ' ' + MONTHS[mm] + (o.year === false ? '' : ' ' + yy);
  if (o.time && !plain) out += ' ' + fmtTime(s);
  return out;
}
function fmtTime(s) {
  const d = parseDate(s);
  if (!d || String(s).length <= 10) return '';
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
}
function fmtStamp(s) { const d = parseDate(s); if (!d) return s ? String(s) : ''; return fmtDate(d, { year: false }) + ' ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
function localDay(s) {
  const d = parseDate(s);
  if (!d) return '';
  if (String(s).length === 10) return String(s);
  return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}
function countdown(iso, now) {
  const d = parseDate(iso);
  if (!d) return '';
  let s = Math.floor((d.getTime() - (now || Date.now())) / 1000);
  if (s <= 0) return '';
  const days = Math.floor(s / 86400); s -= days * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60); s -= m * 60;
  const p = n => ('0' + n).slice(-2);
  return days ? days + 'd ' + p(h) + 'h ' + p(m) + 'm' : p(h) + 'h ' + p(m) + 'm ' + p(s) + 's';
}
function ordinal(n) {
  if (!isNum(n)) return '—';
  const v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
}
/* Catalogue values by METRIC fmt: int|count|plus|0|1|2|3|pct|pct0|prob|wp|pp|signed|signed1..3|pm|epa|yds|sec|deg. */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt || '')) {
    case 'int': case 'count': return Math.round(x).toLocaleString('en-US');
    case 'plus': return Math.round(x).toString();
    case '0': return x.toFixed(0);
    case '1': case 'yds': case 'mph': case 'ft': case 'in': return x.toFixed(1);
    case '2': return x.toFixed(2);
    case '3': return x.toFixed(3);
    case 'sec': case 's': return x.toFixed(2) + 's';
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'pct0': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(0) + '%';
    case 'prob': case 'wp': return pct(x);
    case 'pp': return signed(x * 100, 1) + ' pts';
    case 'signed1': case 'pm': return signed(x, 1);
    case 'signed': case 'signed2': return signed(x, 2);
    case 'signed3': case 'epa': return signed(x, 3);
    case 'deg': return x.toFixed(0) + '°';
    default: return Math.abs(x) >= 100 ? x.toFixed(0) : Math.abs(x) < 1 && x !== 0 ? x.toFixed(3) : x.toFixed(2);
  }
}
function record(w, l, t) {
  if (!isNum(w) || !isNum(l)) return '—';
  return Math.round(w) + '-' + Math.round(l) + (isNum(t) && Number(t) > 0 ? '-' + Math.round(t) : '');
}
function american(p) {
  if (!isNum(p) || p <= 0 || p >= 1) return '—';
  return p >= 0.5 ? '−' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p);
}
function fmtOdds(a) { return isNum(a) ? (Number(a) > 0 ? '+' : '−') + Math.abs(Math.round(Number(a))) : '—'; }
function amToProb(a) {
  if (!isNum(a) || Number(a) === 0) return null;
  const x = Number(a);
  return x < 0 ? -x / (-x + 100) : 100 / (x + 100);
}
function fmtLine(v) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  if (x === 0) return 'PK';
  return (x > 0 ? '+' : '−') + (Number.isInteger(Math.abs(x)) ? String(Math.abs(x)) : Math.abs(x).toFixed(1));
}
function titleCase(id) { return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' '); }
function fold(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
function median(a) { const s = a.filter(isNum).map(Number).sort((x, y) => x - y); if (!s.length) return null; const k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function mean(a) { const s = a.filter(isNum).map(Number); return s.length ? s.reduce((x, y) => x + y, 0) / s.length : null; }
function sum(a) { return a.filter(isNum).map(Number).reduce((x, y) => x + y, 0); }
function sd(a) { const s = a.filter(isNum).map(Number); if (s.length < 2) return null; const m = mean(s); return Math.sqrt(s.reduce((x, y) => x + (y - m) * (y - m), 0) / (s.length - 1)); }
function corr(xs, ys) {
  const pairs = xs.map((x, i) => [x, ys[i]]).filter(p => isNum(p[0]) && isNum(p[1]));
  if (pairs.length < 3) return null;
  const mx = mean(pairs.map(p => p[0])), my = mean(pairs.map(p => p[1]));
  let a = 0, b = 0, c = 0;
  pairs.forEach(p => { a += (p[0] - mx) * (p[1] - my); b += (p[0] - mx) * (p[0] - mx); c += (p[1] - my) * (p[1] - my); });
  return b && c ? a / Math.sqrt(b * c) : null;
}
function first() { for (let i = 0; i < arguments.length; i++) if (isNum(arguments[i])) return Number(arguments[i]); return null; }

// ── football vocabulary ───────────────────────────────────────────────────

function regWeeks(S) { return Number(S || state.season || currentSeason()) >= 2021 ? 18 : 17; }
function weekNum(w, S) {
  if (isNum(w)) return Number(w);
  const k = String(w || '').toUpperCase();
  const i = POST_KEYS.indexOf(k === 'CONF' ? 'CON' : k);
  return i >= 0 ? regWeeks(S) + 1 + i : null;
}
function weekType(w, S) {
  const n = weekNum(w, S);
  if (!isNum(n)) return '';
  const R = regWeeks(S);
  return n <= R ? 'REG' : POST_KEYS[Math.min(3, n - R - 1)];
}
function weekLabel(w, S, short) {
  const n = weekNum(w, S);
  if (!isNum(n)) return '—';
  const t = weekType(n, S);
  if (t === 'REG') return short ? 'W' + n : 'Week ' + n;
  return short ? GTYPE_SHORT[t] : ({ WC: 'Wild Card', DIV: 'Divisional', CON: 'Conference', SB: 'Super Bowl' })[t];
}
function weeksOf(S) {
  const R = regWeeks(S), out = [];
  for (let w = 1; w <= R + 4; w++) out.push({ w: w, label: weekLabel(w, S), short: weekLabel(w, S, true), type: weekType(w, S) });
  return out;
}
function gtypeLabel(t, short) { const k = String(t || '').toUpperCase(); return (short ? GTYPE_SHORT : GTYPE_LONG)[k] || String(t || ''); }
function parseGameId(id) {
  const m = /^(\d{4})_(\d{1,2})_([A-Z]{2,3})_([A-Z]{2,3})$/.exec(String(id || ''));
  return m ? { season: Number(m[1]), week: Number(m[2]), away: m[3], home: m[4] } : null;
}
function gameSeason(id) { const g = parseGameId(id); return g ? g.season : null; }
function gameWeek(id) { const g = parseGameId(id); return g ? g.week : null; }
function downText(d) { return isNum(d) && d >= 1 && d <= 4 ? ordinal(d) : ''; }
function downDist(down, dist, yl100) {
  if (!isNum(down) || Number(down) < 1) return '';
  const goal = isNum(yl100) && isNum(dist) && Number(dist) >= Number(yl100);
  return downText(down) + ' & ' + (goal ? 'Goal' : (isNum(dist) ? Math.round(dist) : '?'));
}
function fieldPos(yl100, pos, opp) {
  if (!isNum(yl100)) return '';
  const y = Math.round(Number(yl100));
  if (y === 50) return 'Midfield';
  if (y > 50) return (pos ? teamAbbr(pos) : 'Own') + ' ' + (100 - y);
  return (opp ? teamAbbr(opp) : 'Opp') + ' ' + y;
}
function fmtClock(c) {
  if (c === null || c === undefined || c === '') return '';
  if (isNum(c)) { const s = Math.max(0, Math.round(Number(c))); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  return String(c);
}
function qtrLabel(q, long) {
  if (!isNum(q)) return '';
  const n = Number(q);
  if (n <= 4) return long ? ordinal(n) + ' quarter' : 'Q' + n;
  return long ? (n === 5 ? 'Overtime' : (n - 4) + 'nd overtime') : (n === 5 ? 'OT' : (n - 4) + 'OT');
}
function clockText(q, c) { return [qtrLabel(q), fmtClock(c)].filter(Boolean).join(' '); }
function otherTeam(g, t) { if (!g) return null; return String(t) === String(g.home) ? g.away : g.home; }
function driveResult(r) {
  const k = String(r || '').toLowerCase().replace(/[\s-]+/g, '_');
  const x = DRIVE_RESULTS[k];
  if (x) return { label: x[0], colour: x[1] };
  if (/touchdown|_td$/.test(k)) return { label: 'Touchdown', colour: DRIVE_RESULTS.touchdown[1] };
  if (/missed|blocked_f/.test(k)) return { label: titleCase(k), colour: DRIVE_RESULTS.missed_fg[1] };
  if (/field_goal|^fg/.test(k)) return { label: 'Field goal', colour: DRIVE_RESULTS.field_goal[1] };
  if (/fumble|intercept|turnover/.test(k)) return { label: titleCase(k), colour: BAD };
  if (/downs/.test(k)) return { label: 'Downs', colour: '#e8833a' };
  if (/half|game|period/.test(k)) return { label: titleCase(k), colour: '#5a6270' };
  return { label: titleCase(k) || '—', colour: '#7d8590' };
}
/* A fourth-down grade -> {key, label, colour}: letters A/B right call, C close, D/F mistake; or WP lost (0-1). */
function gradeOf(g, wpLost) {
  const s = String(g === null || g === undefined ? '' : g).toLowerCase();
  if (/^(correct|good|right|right_call|agree|optimal|ok|a|b)$/.test(s)) return { key: 'good', label: 'Right call', colour: GOOD };
  if (/^(close|close_call|toss.?up|marginal|neutral|c)$/.test(s)) return { key: 'close', label: 'Close call', colour: CLOSE };
  if (/^(mistake|bad|wrong|error|blunder|poor|d|f)$/.test(s)) return { key: 'bad', label: 'Mistake', colour: BAD };
  const x = isNum(wpLost) ? Number(wpLost) : (isNum(g) ? Number(g) : null);
  if (x === null) return { key: '', label: '—', colour: '#7d8590' };
  const a = Math.abs(x) > 1 ? Math.abs(x) / 100 : Math.abs(x);
  if (a <= 0.015) return { key: 'good', label: 'Right call', colour: GOOD };
  if (a <= 0.03) return { key: 'close', label: 'Close call', colour: CLOSE };
  return { key: 'bad', label: 'Mistake', colour: BAD };
}
function choiceLabel(c) {
  const k = String(c || '').toLowerCase();
  if (/^go|run|pass|go_for_it/.test(k)) return 'Go for it';
  if (/punt/.test(k)) return 'Punt';
  if (/fg|field/.test(k)) return 'Field goal';
  return titleCase(k) || '—';
}
function gameState(g) {
  const s = String((g && g.status) || '').toLowerCase().replace(/^status_/, '');
  if (/half/.test(s)) return 'half';
  if (s === 'live' || s === 'in' || /progress|end_period|end of|end_of_period|^q\d/.test(s)) return 'live';
  if (/final|^post$|^done$|complete|game over|^closed$/.test(s)) return 'final';
  if (s === 'pre' || /sched|upcoming|preview|^$/.test(s)) return 'pre';
  if (/postpon/.test(s)) return 'postponed';
  if (/cancel/.test(s)) return 'cancelled';
  if (/delay|suspend/.test(s)) return 'delayed';
  return s;
}
function isFinal(g) { return gameState(g) === 'final'; }
function isLive(g) { const s = gameState(g); return s === 'live' || s === 'half'; }
function isPre(g) { return gameState(g) === 'pre'; }
/* A game still marked upcoming (or live) 12 hours after kickoff is a stale snapshot (the hourly build has not caught up):
 * lists of what is on now leave it out (the Home page applies the same guard). */
function isStale(g) {
  const d = parseDate(g && g.kickoff);
  return !!d && !isFinal(g) && Date.now() - d.getTime() > 12 * 3600 * 1000;
}
function isOT(g) { return !!(g && (g.overtime || (isNum(g.qtr) && Number(g.qtr) >= 5) || (Array.isArray(g.quarters) && g.quarters.length > 4))); }
/* The home betting line: negative = home favoured. */
function homeLine(o) {
  if (!o) return null;
  if (isNum(o.spread_home)) return o.spread_convention === 'margin' ? -Number(o.spread_home) : Number(o.spread_home);
  if (isNum(o.spread)) return o.spread_convention === 'margin' ? -Number(o.spread) : Number(o.spread);
  if (isNum(o.margin)) return -Number(o.margin);
  if (isNum(o.home_margin)) return -Number(o.home_margin);
  return null;
}
/* "PIT −3.5" (the favourite and its line), "Pick'em" at 0. */
function spreadText(home, away, line) {
  if (!isNum(line)) return '—';
  const x = Number(line);
  if (Math.abs(x) < 0.05) return "Pick'em";
  return (x < 0 ? teamAbbr(home) : teamAbbr(away)) + ' ' + fmtLine(-Math.abs(x));
}
function surnameOf(n) {
  const p = String(n || '').split(' ');
  if (p.length < 2) return p[0];
  const sfx = /^(Jr\.?|Sr\.?|II|III|IV|V)$/i.test(p[p.length - 1]);
  return sfx && p.length > 2 ? p[p.length - 2] + ' ' + p[p.length - 1] : p.slice(1).join(' ');
}
function qbText(q, link) {
  if (!q) return '';
  if (typeof q === 'object') {
    const pid = q.pid || q.id || q.gsis_id;
    const nm = q.name || (pid ? playerName(pid) : '');
    const st = q.status && !/^(active|start|starter|ok|healthy)$/i.test(q.status) ? ' <span class="qk-badge">' + esc(q.status) + '</span>' : '';
    return (pid && link !== false ? playerLink(pid, { name: surnameOf(nm) }) : esc(surnameOf(nm))) + st;
  }
  const s = String(q);
  if (/^\d\d-\d{5,}$/.test(s)) return link === false ? esc(surnameOf(playerName(s))) : playerLink(s, { name: surnameOf(playerName(s)) });
  return esc(surnameOf(s));
}
function weatherText(w, roof) {
  const r = String(roof || (w && w.roof) || '').toLowerCase();
  if (r === 'dome' || r === 'closed' || r === 'indoors') return r === 'closed' ? 'Roof closed' : 'Dome';
  if (!w) return r === 'open' ? 'Roof open' : '';
  const bits = [];
  if (isNum(w.temp)) bits.push(Math.round(w.temp) + '°F');
  if (isNum(w.wind)) bits.push('wind ' + Math.round(w.wind) + ' mph');
  const d = w.desc || w.conditions || w.summary;
  if (d) bits.push(String(d));
  return (r === 'open' ? 'Roof open · ' : '') + bits.join(' · ');
}

// ── names, teams, links ───────────────────────────────────────────────────

function player(pid) { return NAMES[String(pid)] || {}; }
function playerName(pid) { const x = NAMES[String(pid)]; return x && x.name ? x.name : (pid ? String(pid) : '—'); }
function playerShort(pid) { const n = playerName(pid).split(' '); return n.length > 1 ? n[0].charAt(0) + '. ' + n.slice(1).join(' ') : n[0]; }
function playerSurname(pid) { return surnameOf(playerName(pid)); }
function sq(S) { const s = S || state.season; return s && Number(s) !== currentSeason() ? '?s=' + s : ''; }
function ghref(sub, S, extra) {
  const q = Object.assign({}, extra || {});
  const s = S || state.season;
  if (s && Number(s) !== currentSeason()) q.s = s;
  return '#/' + String(sub || '').replace(/^\/+/, '') + qs(q);
}
function playerHref(pid, S) { return '#/player/' + encodeURIComponent(pid) + (S && Number(S) !== currentSeason() ? '?s=' + S : ''); }
/* <a> to the player page. opts {name, short, surname, team (abbr after), pos} or a name string. */
function playerLink(pid, opts) {
  if (!pid) return '<span class="qk-muted">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.surname ? playerSurname(pid) : o.short ? playerShort(pid) : playerName(pid));
  const x = player(pid);
  const tail = (o.pos && x.pos ? ' <span class="gi-tag">' + esc(posLabel(x.pos)) + '</span>' : '') + (o.team && x.team ? ' <span class="gi-tag">' + esc(teamAbbr(x.team)) + '</span>' : '');
  return '<a class="gi-link" href="' + playerHref(pid, o.season) + '">' + esc(label) + '</a>' + tail;
}
function teamInfo(t) { return TEAMS[canonTeam(t)] || {}; }
function teamName(t) { const x = teamInfo(t); return x.name || (t ? String(t) : '—'); }
function teamShort(t) { const x = teamInfo(t); return x.short || x.name || (t ? String(t) : '—'); }
function teamAbbr(t) { return t ? (teamInfo(t).abbr || String(t)) : '—'; }
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
/* The raw club colour. A near-black primary falls back to the alternate when that is lighter. */
function teamColour(t) {
  const x = teamInfo(t);
  if (!QK.color.parse(x.colour)) return PALETTE[hashIndex(t || '?', PALETTE.length)];
  if (QK.color.lum(x.colour) < 0.012 && QK.color.parse(x.alt) && QK.color.lum(x.alt) > 0.08) return x.alt;
  return x.colour;
}
/* The club colour lifted to 3:1 on the card (marks, bars, chart series). */
function tc(t) { return QK.color.team(teamColour(t)); }
function teamHref(t, S) { return '#/team/' + encodeURIComponent(teamAbbr(t)) + (S && Number(S) !== currentSeason() ? '?s=' + S : ''); }
function mark(t, size) { const x = teamInfo(t); return QK.teamMark({ name: x.name || t, abbr: teamAbbr(t), colour: x.colour }, size || 'sm'); }
/* Two clubs' colours that can sit side by side (kit rule QK.color.distinct): the second falls back to its alternate
 * colour, then the win-probability orange, then blue. Pass the pair to QK.wpBar / QK.matchupBar so bars and charts agree. */
function pair(a, b) {
  const ca = tc(a);
  let cb = tc(b);
  const ok = (x, y) => (QK.color.distinct ? QK.color.distinct(x, y) : QK.color.contrast(x, y) >= 1.6);
  if (!ok(ca, cb)) {
    const alt = teamInfo(b).alt;
    const alt2 = QK.color.parse(alt) ? QK.color.team(alt) : null;
    cb = alt2 && ok(ca, alt2) ? alt2 : QK.cssVar('--wp-b');
    if (!ok(ca, cb)) cb = QK.cssVar('--wp-a');
  }
  return [ca, cb];
}
/* <a> to the team page. opts {abbr, short, name, season, mark: true (default) | false, dot}. */
function teamLink(t, opts) {
  if (!t) return '<span class="qk-muted">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.abbr ? teamAbbr(t) : o.short ? teamShort(t) : teamName(t));
  const lead = o.mark === false ? '' : o.dot ? '<i class="gi-dot" style="--tc:' + esc(teamColour(t)) + '" aria-hidden="true"></i>' : mark(t, 'sm');
  return '<a class="gi-link gi-team" href="' + teamHref(t, o.season) + '" title="' + esc(teamName(t)) + '">' + lead + '<span>' + esc(label) + '</span></a>';
}
function teamChip(t, S) {
  if (!t) return '<span class="qk-muted">—</span>';
  return '<a class="gi-tchip" href="' + teamHref(t, S) + '" style="--tc:' + esc(tc(t)) + '" title="' + esc(teamName(t)) + '">' + esc(teamAbbr(t)) + '</a>';
}
function playerColour(pid) { return pid ? PALETTE[hashIndex(pid, PALETTE.length)] : '#8a93a3'; }
function gameHref(id) { return '#/game/' + encodeURIComponent(id); }
function matchupLink(id, away, home) {
  const g = parseGameId(id) || {};
  return '<a class="gi-link" href="' + gameHref(id) + '">' + esc(teamAbbr(away || g.away)) + ' @ ' + esc(teamAbbr(home || g.home)) + '</a>';
}
function coachHref(name, S) { return '#/coach/' + encodeURIComponent(String(name || '')) + (S && Number(S) !== currentSeason() ? '?s=' + S : ''); }
function coachLink(name, S) { return name ? '<a class="gi-link" href="' + coachHref(name, S) + '">' + esc(name) + '</a>' : '<span class="qk-muted">—</span>'; }
function weekHref(S, w) { const s = S || state.season || currentSeason(); return '#/games/' + s + '/' + (isNum(w) ? w : (s === currentSeason() ? currentWeek() : 1)); }
function standingsHref(S, v) { const s = S || state.season; return '#/standings' + (s && Number(s) !== currentSeason() ? '/' + s : '') + (v ? '?v=' + v : ''); }
function playoffsHref(S) { const s = S || state.season; return '#/playoffs' + (s && Number(s) !== currentSeason() ? '/' + s : ''); }
function compareHref(a, b, c) { return '#/compare' + (a ? '/' + encodeURIComponent(a) : '') + (b ? '/' + encodeURIComponent(b) : '') + (b && c ? '/' + encodeURIComponent(c) : ''); }
function glossHref(key) { return '#/glossary' + (key ? '/' + encodeURIComponent(key) : ''); }

// ── catalogue helpers (players.json, teams.json, lab.json) ────────────────

const GROUPS = ['QB', 'RB', 'WR', 'TE', 'K', 'P', 'DEF'];
const GROUP_NAME = { QB: 'Quarterbacks', RB: 'Running backs', WR: 'Wide receivers', TE: 'Tight ends', K: 'Kickers', P: 'Punters', DEF: 'Defence' };
const GROUP_ONE = { QB: 'quarterback', RB: 'running back', WR: 'wide receiver', TE: 'tight end', K: 'kicker', P: 'punter', DEF: 'defender' };
function groupOf(pos, group) {
  if (group && GROUPS.indexOf(String(group).toUpperCase()) >= 0) return String(group).toUpperCase();
  const p = String(pos || '').toUpperCase();
  if (p === 'QB') return 'QB';
  if (/^(RB|HB|FB)$/.test(p)) return 'RB';
  if (p === 'WR') return 'WR';
  if (p === 'TE') return 'TE';
  if (/^(K|PK)$/.test(p)) return 'K';
  if (p === 'P') return 'P';
  if (/^(OL|OT|OG|C|G|T|LS)$/.test(p)) return 'OL';
  return p ? 'DEF' : '';
}
const SAMPLE = {
  QB: [['dropbacks', 'Dropbacks'], ['plays', 'Plays'], ['att', 'Attempts'], ['pass_att', 'Attempts'], ['attempts', 'Attempts']],
  RB: [['carries', 'Carries'], ['rush_att', 'Carries'], ['att', 'Carries'], ['touches', 'Touches'], ['plays', 'Plays']],
  WR: [['targets', 'Targets'], ['routes', 'Routes'], ['tgt', 'Targets'], ['plays', 'Plays']],
  TE: [['targets', 'Targets'], ['routes', 'Routes'], ['tgt', 'Targets'], ['plays', 'Plays']],
  K: [['fga', 'FG attempts'], ['fg_att', 'FG attempts'], ['kicks', 'Kicks']],
  P: [['punts', 'Punts']],
  DEF: [['snaps', 'Snaps'], ['def_snaps', 'Snaps'], ['pass_rush_snaps', 'Rush snaps'], ['tackles', 'Tackles'], ['plays', 'Plays']]
};
function sampleKey(P, group) {
  const cands = SAMPLE[group] || [];
  const ids = Object.keys(P || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i][0]; if (ids.some(id => isNum(((P[id] || {}).values || {})[c]) || isNum(((P[id] || {}).n || {})[c]) || isNum((P[id] || {})[c]))) return cands[i]; }
  return ['games', 'Games'];
}
function sampleOf(p, key) { const v = isNum((p.n || {})[key]) ? p.n[key] : (p.values || {})[key]; return isNum(v) ? Number(v) : (isNum(p[key]) ? Number(p[key]) : (key === 'games' && isNum(p.g) ? Number(p.g) : 0)); }
function scopeOk(m, group) {
  const s = m && (m.scope !== undefined ? m.scope : m.groups);
  if (!s || s === 'all' || s === '*') return true;
  const list = Array.isArray(s) ? s : String(s).split(/[,|/ ]+/);
  return list.some(x => String(x).toUpperCase() === group || (String(x).toUpperCase() === 'REC' && /^(WR|TE|RB)$/.test(group)) || (String(x).toUpperCase() === 'SKILL' && /^(RB|WR|TE)$/.test(group)));
}
function metaOf(metrics) { const m = {}; (metrics || []).forEach(x => { m[x.key] = x; }); return m; }
function metricsFor(cat, group) {
  const M = (cat || {}).metrics;
  if (M && !Array.isArray(M) && typeof M === 'object') return (M[group] || []).slice();
  const G = (cat || {}).groups;
  if (G && Array.isArray(G[group])) { const meta = metaOf(M || []); return G[group].map(x => meta[x]).filter(Boolean); }
  const P = (cat || {}).players || {};
  const ids = Object.keys(P).filter(id => groupOf(P[id].pos, P[id].group) === group);
  return (M || []).filter(m => scopeOk(m, group) && ids.some(id => isNum(((P[id] || {}).values || {})[m.key])));
}
function allMetrics(cat) {
  const M = (cat || {}).metrics;
  if (M && !Array.isArray(M) && typeof M === 'object') { const out = [], seen = {}; Object.keys(M).forEach(g => (M[g] || []).forEach(m => { if (!seen[m.key]) { seen[m.key] = 1; out.push(m); } })); return out; }
  return (M || []).slice();
}
function metricGroups(metrics) {
  const out = [];
  (metrics || []).forEach(m => { let g = out.find(x => x.name === (m.group || 'Other')); if (!g) { g = { name: m.group || 'Other', items: [] }; out.push(g); } g.items.push(m); });
  return out;
}
function colRows(x) {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object' && !Array.isArray(r));
  const cols = x.cols || x.fields || x.columns, rows = x.rows || x.data;
  if (!Array.isArray(cols) || !Array.isArray(rows)) return [];
  return rows.map(r => { if (!Array.isArray(r)) return r; const o = {}; cols.forEach((c, i) => { o[c] = r[i]; }); return o; });
}
function listOf(x, idKey) {
  if (!x) return [];
  if (Array.isArray(x)) return x.filter(r => r && typeof r === 'object');
  if ((x.cols || x.fields || x.columns) && (x.rows || x.data)) return colRows(x);
  if (typeof x === 'object') return Object.keys(x).filter(k => x[k] && typeof x[k] === 'object' && !Array.isArray(x[k])).map(k => { const o = {}; o[idKey || 'id'] = k; return Object.assign(o, x[k]); });
  return [];
}
function pickKey(obj, cands) {
  const keys = Array.isArray(obj) ? obj.map(m => (m && m.key !== undefined ? m.key : m)) : Object.keys(obj || {});
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (typeof c === 'string' && keys.indexOf(c) >= 0) return c; }
  for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (c instanceof RegExp) { const k = keys.find(x => c.test(x)); if (k) return k; } }
  return null;
}
function val(obj, cands) { const k = pickKey(obj || {}, cands); return k ? obj[k] : null; }
function headline(metrics, prefs, n) {
  const out = [];
  const usable = (metrics || []).slice();
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
}
const PREFS = {
  QB: ['composite', 'epa_db', 'epa_per_db', 'epa_per_play', /^epa_?(per_?)?(play|db|dropback)/, 'value', 'cpoe', /cpoe/, 'success', 'success_rate', 'adot', 'ttt', 'time_to_throw', 'sack_rate', 'twp_rate', /twp|turnover_worthy/],
  RB: ['value', 'ryoe', 'ryoe_per_att', /ryoe/, 'rush_epa', 'rush_success', 'success_rate', 'explosive', 'explosive_rate', 'target_share', 'rec_epa_tgt'],
  WR: ['value', 'target_share', 'rec_epa_tgt', 'adot', 'separation', 'yacoe', 'yac_oe', /yac_?oe|yacoe/, 'croe', /croe|catch_rate_oe/, 'drop_rate', 'wopr'],
  K: ['fg_oe', 'pts_oe', /fg_?oe|over_exp/, 'fg_pct', 'fg_50_pct', 'xp_pct', 'avg_dist', 'fga'],
  P: ['epa_punt', 'epa_per_punt', 'net', 'net_avg', 'gross', 'inside20', 'touchback_rate', 'punts'],
  DEF: ['def_value', 'splash_pg', 'sacks', 'pressures_pg', 'qb_hits', 'tfl', 'ints', 'pd', 'tackles']
};
PREFS.TE = PREFS.WR;
function shortLabel(s) { return String(s || '').replace(/percentage/i, '%').replace(/ over expected/i, ' OE').replace(/ per play/i, '/play').replace(/^Expected /, 'x').slice(0, 24); }
/* Model ids in payload prose read as words (glossary.json, players.json and lab.json still carry player_value and
 * team_strength, 23 Oct 2026). The "builder X's" rewrite went with the builder copy pass (b463b937..a7f39783). */
function cleanDesc(t) { return String(t || '').replace(/player_value/g, 'player-value model').replace(/team_strength/g, 'team-strength model'); }
function cleanMetrics(list) { (Array.isArray(list) ? list : []).forEach(m => { if (m && m.desc && !m._c) { m.desc = cleanDesc(m.desc); m._c = 1; } }); return list; }
function catOf(d) {
  if (!d || d.ok === false) return null;
  if (Array.isArray(d.metrics)) cleanMetrics(d.metrics);
  else if (d.metrics && typeof d.metrics === 'object') Object.keys(d.metrics).forEach(k => cleanMetrics(d.metrics[k]));
  if (d.players && d.metrics) return d;
  const inner = d.catalogue || d.data;
  if (inner && inner.players) return Object.assign({}, d, inner);
  return d.players ? Object.assign({ metrics: [] }, d) : null;
}
function glossLink(key, text) { return '<a class="gi-gl" href="' + glossHref(key) + '" title="Glossary">' + text + '</a>'; }

// ── HTML builders (kit markup) ────────────────────────────────────────────

/* A card. opts: {id, cls, span (3..12), flush, right (HTML in the head), foot, bodyId, style} */
function card(title, sub, body, opts) {
  const o = opts || {};
  return '<section class="qk-card' + (o.span ? ' qk-span-' + o.span : '') + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + (o.style ? ' style="' + esc(o.style) + '"' : '') + '>' +
    (title || o.right ? '<div class="qk-card-head"><div class="gi-card-titles">' + (title ? '<h3 class="qk-card-title">' + title + '</h3>' : '') + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '') +
    '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '"' + (o.bodyId ? ' id="' + esc(o.bodyId) + '"' : '') + '>' + (body || '') + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
}
function grid(html, cls) { return '<div class="qk-grid' + (cls ? ' ' + cls : '') + '">' + html + '</div>'; }
function chartBox(id, h, label) { return '<div id="' + esc(id) + '" class="gi-chart" style="--h:' + (h || 300) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; }
/* A stat tile (Design System 2.0); value and sub are HTML (links allowed).
 * o: {cls, tip, text, spark|trend: [..], signal (ours: the number in the signal colour), pctl, unit, href, delta} */
function kpi(label, value, sub, o) {
  o = o || {};
  const tr = Array.isArray(o.trend) ? o.trend : (Array.isArray(o.spark) ? o.spark : null);
  return QK.statTile({ label: label, value: value, sub: sub, html: true, cls: o.cls, tip: o.tip, text: o.text, trend: tr || undefined, signal: !!o.signal, pctl: o.pctl, unit: o.unit, href: o.href, delta: o.delta });
}
function kpis(list, cls) { return '<div class="gi-stats' + (cls ? ' ' + cls : '') + '">' + QK.stats(list.filter(Boolean)) + '</div>'; }
function chip(text, kind) { return '<span class="qk-badge' + (kind ? ' ' + kind : '') + '">' + esc(text) + '</span>'; }
function muted(text) { return '<p class="gi-muted">' + text + '</p>'; }
function empty(title, text) { return QK.empty(title, text); }
function note(html) { return '<div class="qk-note gi-note">' + html + '</div>'; }
function notBuilt(what, d) { return empty(what + ' is not available yet', d && d.reason ? String(d.reason) : 'The payloads are rebuilt every hour.'); }
/* The page head (Design System 2.0 section head, h1): kicker as text, title as text, sub and actions as HTML. */
function pageHead(kicker, title, sub, right) {
  const k = String(kicker || '').replace(/<[^>]*>/g, '').replace(/&amp;/g, '&');
  return QK.sectionHead({ kicker: k ? 'NFL · ' + k.replace(/^NFL( · )?/, '') : 'NFL', title: esc(title), sub: sub || '', actions: right || '', size: 'lg', tag: 'h1', html: true, cls: 'gi-head' });
}
/* A section head inside a page (v2): opts {kicker, title, sub (HTML), actions (HTML), id} */
function secHead(o) { return QK.sectionHead({ kicker: o.kicker, title: o.html ? o.title : esc(o.title), sub: o.sub || '', actions: o.actions || '', id: o.id, html: true }); }
/* Sub-navigation inside a section: [[href, label, key]], active key. */
function subnav(items, active, label) {
  return '<nav class="gi-subnav" aria-label="' + esc(label || 'Views') + '"><div class="qk-tabs" role="tablist">' + items.map(i =>
    '<a class="qk-tab" role="tab" href="' + esc(i[0]) + '" aria-selected="' + (i[2] === active ? 'true' : 'false') + '"' + (i[2] === active ? ' aria-current="page"' : '') + '>' + esc(i[1]) + '</a>').join('') + '</div></nav>';
}
/* The sub-navigation of each section, so every page of a section shows the same views. */
function sectionNav(key, active) {
  const S = state.season;
  const L = {
    standings: [[standingsHref(S), 'Standings', 'table'], [standingsHref(S, 'ratings'), 'Power ratings', 'ratings'], [playoffsHref(S), 'Playoff picture', 'playoffs'],
      [standingsHref(S, 'wins'), 'Win totals', 'wins'], [standingsHref(S, 'draft'), 'Draft order', 'draft'], ['#/futures', 'Season forecasts', 'futures']],
    players: [[ghref('players', S), 'Players', 'players'], [ghref('leaders', S), 'Leaders', 'leaders'], ['#/history', 'All-time', 'history']],
    value: [[ghref('value', S), 'Player value', 'value'], ['#/trade', 'Trade simulator', 'trade'], ['#/transactions', 'Transactions', 'transactions']],
    lab: [[ghref('lab', S), 'Scatter lab', 'lab'], ['#/compare', 'Compare', 'compare'], [ghref('fourth-downs', S), 'Fourth downs', 'fourth'], [ghref('coaches', S), 'Coaches', 'coaches']],
    model: [['#/calibration', 'Calibration', 'calibration'], ['#/methodology', 'Methodology', 'methodology'], ['#/glossary', 'Glossary', 'glossary'], ['#/disclaimer', 'Terms', 'disclaimer']]
  };
  return L[key] ? subnav(L[key], active, 'Views in this section') : '';
}
/* Segmented control. opts: [[value, label]]. Wire with wireSeg(root, id, cb). */
function seg(id, opts, cur, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label || 'View') + '">' + opts.map(o =>
    '<button type="button" data-value="' + esc(o[0]) + '" aria-pressed="' + (String(o[0]) === String(cur) ? 'true' : 'false') + '"' + (o[2] ? ' disabled' : '') + '>' + esc(o[1]) + '</button>').join('') + '</div>';
}
function wireSeg(root, id, cb) { const n = (root || document).querySelector('#' + id); if (n) QK.seg(n, cb); }
function select(id, opts, cur, label, cls) {
  return '<select class="qk-select' + (cls ? ' ' + cls : '') + '" id="' + esc(id) + '" aria-label="' + esc(label || '') + '">' + opts.map(o =>
    (o.group ? '<optgroup label="' + esc(o.group) + '">' + o.items.map(x => '<option value="' + esc(x[0]) + '"' + (String(x[0]) === String(cur) ? ' selected' : '') + '>' + esc(x[1]) + '</option>').join('') + '</optgroup>'
      : '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' selected' : '') + '>' + esc(o[1]) + '</option>')).join('') + '</select>';
}
function field(label, html) { return '<label class="gi-field"><span>' + esc(label) + '</span>' + html + '</label>'; }
/* A kit table. cols: [{key, label, num, fmt(v,row) -> html, sort:false, tip, sticky, cls, pctl}], rows: objects.
 * opts: {sort: {key, dir}, rank, dense (default true), maxHeight, caption}. */
function table(el, cols, rows, opts) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  const o = opts || {};
  const t = QK.table(node, { columns: cols, rows: rows, sort: o.sort || null, rank: !!o.rank, dense: o.dense !== false, maxHeight: o.maxHeight, caption: o.caption });
  if (o.rowHref) wireRows(node, o.rowHref);
  return t;
}
/* Whole-row links for a QK.table: rowHref(row) -> hash; re-wired after every sort through a MutationObserver-free delegate. */
function wireRows(node, fn) {
  if (node.__giRows) return;
  node.__giRows = true;
  node.addEventListener('click', ev => {
    if (ev.target.closest('a, button, input, select')) return;
    const tr = ev.target.closest('tbody tr');
    if (!tr) return;
    const a = tr.querySelector('a[href^="#/"]');
    if (a) location.hash = a.getAttribute('href');
  });
  node.classList.add('gi-rowlinks');
}
/* Static HTML table on kit markup and its sortable headers / data-href rows: the kit's QK.tableHTML and
 * QK.sortable (ported from here). cols: [{label, align, title, sortable:false, cls}]; rows: [{cells, _class, _href}]
 * or arrays of cells; a cell is {v, html, cls, align, title, style} or a primitive. opts {cls, id, maxHeight, sticky}. */
function tableHTML(cols, rows, opts) { return QK.tableHTML(cols, rows, opts); }
function sortable(el) { return QK.sortable(el); }
function pill(text, colour, title) { return '<span class="gi-grade" style="--g:' + esc(colour || 'var(--ink-3)') + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + esc(text) + '</span>'; }
function teamBar(t) { return '<i class="gi-dot" style="--tc:' + esc(teamColour(t)) + '" aria-hidden="true"></i>'; }
function weekNav(S, w) {
  const max = regWeeks(S) + 4;
  return (w > 1 ? '<a class="qk-btn" href="' + weekHref(S, w - 1) + '">← ' + esc(weekLabel(w - 1, S)) + '</a>' : '') +
    (w < max ? '<a class="qk-btn" href="' + weekHref(S, w + 1) + '">' + esc(weekLabel(w + 1, S)) + ' →</a>' : '');
}
function weekLink(S, w, label) { return '<a class="gi-link" href="' + weekHref(S, w) + '">' + esc(label || weekLabel(w, S)) + '</a>'; }
function devigAm(pair) { if (!pair) return null; const a = amToProb(pair[0]), b = amToProb(pair[1]); return a === null || b === null ? null : a / (a + b); }
/* The side the model prefers against the line, in points: {team, pts}. */
function lineLean(g, mLine, lLine) {
  if (!isNum(mLine) || !isNum(lLine)) return null;
  const d = Number(lLine) - Number(mLine);
  if (Math.abs(d) < 0.05) return { team: null, pts: 0 };
  return { team: d > 0 ? g.home : g.away, pts: Math.abs(d) };
}
function gapPts(v, d) { return isNum(v) ? '<span class="gi-gap">' + signed(v, d === undefined ? 1 : d) + '</span>' : '<span class="qk-muted">—</span>'; }
function ptsEdge(v, d) { return isNum(v) ? '<span class="' + (v > 0.05 ? 'gi-up' : v < -0.05 ? 'gi-down' : '') + '">' + signed(v, d === undefined ? 1 : d) + '</span>' : '<span class="qk-muted">—</span>'; }
function set(id, html) { const n = document.getElementById(id); if (n) n.innerHTML = html; return n; }
function alive(el) { return !!el && el.isConnected; }
function pctl(p) { return QK.pctlChip(p); }
/* Probability with an inline bar. */
function probBar(p, colour, max) {
  if (!isNum(p)) return '<span class="qk-muted">—</span>';
  const w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="gi-pbar"><span class="gi-pbar-t"><span style="width:' + w.toFixed(1) + '%;background:' + esc(colour || 'var(--signal)') + '"></span></span><span class="gi-pbar-v">' + pct(p, p < 0.1 ? 1 : 0) + '</span></span>';
}
/* Model minus market, percentage points: neutral (a disagreement, not a recommendation). */
function gapHTML(model, market, d) {
  if (!isNum(model) || !isNum(market)) return '<span class="qk-muted">—</span>';
  return '<span class="gi-gap">' + signed((model - market) * 100, d === undefined ? 1 : d) + '</span>';
}
/* The NFL roles for display: the edge-rusher code shows as ED (the common charting abbreviation), so the page copy keeps
 * clear of betting vocabulary; the tooltip says what it is. */
const POS_SHOW = { EDGE: 'ED' };
const POS_LONG = { QB: 'Quarterback', RB: 'Running back', WR: 'Wide receiver', TE: 'Tight end', EDGE: 'Edge rusher', ED: 'Edge rusher', DL: 'Interior lineman', IDL: 'Interior lineman', LB: 'Linebacker', CB: 'Cornerback', S: 'Safety', DB: 'Defensive back', K: 'Kicker', P: 'Punter', OL: 'Offensive lineman', FB: 'Fullback' };
function posLabel(p) { const k = String(p || '').toUpperCase(); return POS_SHOW[k] || String(p || ''); }
function posLong(p) { const k = String(p || '').toUpperCase(); return POS_LONG[k] || String(p || ''); }
/* Payload prose (glossary, value, trade and movement notes): the edge-rusher code as ED and "edge rushers" as outside
 * rushers. Kept: EDGE is the payloads' position code (a data key the builders keep), so value.json, trade.json,
 * movement.json and transactions.json carry it in the deployed build too (checked 23 Oct 2026), and ESPN's own
 * transaction notes use it. The betting-word rewrite went with the builder copy pass (b463b937..a7f39783). */
function copyText(t) {
  return String(t === null || t === undefined ? '' : t).replace(/\bEDGE\b/g, 'ED')
    .replace(/\b([Ee])dge(s?)\b(?=[ -](rush|and interior|or interior|role|defender|player))/g, (m, e, pl) => (e === 'E' ? 'Outside' : 'outside') + (pl ? 's' : ''));
}
function deltaHTML(v, d) { return !isNum(v) ? '<span class="qk-muted">—</span>' : '<span class="' + (v > 0 ? 'gi-up' : v < 0 ? 'gi-down' : '') + '">' + signed(v, d === undefined ? 1 : d) + '</span>'; }
/* Percentile bars (kit): items [{label, p, value, href, tip}]; grouped when items carry .group. */
function pctBars(items) {
  const rows = items.filter(x => isNum(x.p));
  if (!rows.length) return muted('Below the sample floor: no percentiles yet.');
  return QK.pctlBars(rows.map(x => ({ label: x.label, pctl: x.p, value: x.value })));
}
function gradePill(grade, wpLost) { const g = gradeOf(grade, wpLost); return g.key ? '<span class="gi-grade" style="--g:' + g.colour + '">' + esc(g.label) + '</span>' : ''; }
/* HTML heat table with kit diverging colours (see Paddock's heatTable). */
function heatTable(spec) {
  const s = spec || {};
  const rows = s.rows || [];
  if (!rows.length) return muted('No data.');
  const nCols = Math.max.apply(null, rows.map(r => (r.values || []).length));
  const centers = [];
  for (let i = 0; i < nCols; i++) {
    if (s.center !== 'col') { centers.push(isNum(s.center) ? s.center : 0); continue; }
    centers.push(median(rows.map(r => (r.values || [])[i])) || 0);
  }
  const dev = [];
  rows.forEach(r => (r.values || []).forEach((v, k) => { if (isNum(v)) dev.push(Math.abs(v - centers[k])); }));
  dev.sort((a, b) => a - b);
  const max = s.max || dev[Math.floor(dev.length * 0.95)] || dev[dev.length - 1] || 1;
  const f = s.fmt || (v => num(v, 2));
  const colour = (v, k) => {
    let t = Math.max(-1, Math.min(1, (v - centers[k]) / max));
    if (s.invert || (s.invertCols && s.invertCols[k])) t = -t;
    const a = Math.round(Math.abs(t) * 70);
    return 'color-mix(in srgb, ' + (t < 0 ? 'var(--div-neg)' : 'var(--div-pos)') + ' ' + a + '%, transparent)';
  };
  let h = '<div class="qk-table-wrap gi-heat-wrap"><table class="qk-table dense gi-heat"><thead><tr><th class="sticky-col">' + esc(s.corner || '') + '</th>';
  (s.cols || []).forEach(c => { const cc = typeof c === 'object' ? c : { label: c }; h += '<th class="num"' + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(r => {
    h += '<tr><td class="sticky-col">' + (r.label || '') + '</td>';
    (r.values || []).forEach((v, k) => {
      const t = r.titles && r.titles[k] ? ' title="' + esc(r.titles[k]) + '"' : '';
      const ff = (r.fmts && r.fmts[k]) || f;
      h += isNum(v) ? '<td class="num gi-heat-c" style="background:' + colour(v, k) + '"' + t + '>' + ff(v) + '</td>' : '<td class="num gi-heat-c qk-muted"' + t + '>·</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}

/* A game card (kit v3: QK.gameCard): our chance per team (the favourite in blue), the win-probability bar in team
 * colours with a key, records and form when the page has the standings, the score bug when live. No market on cards
 * (the kit's default). Below it the NFL facts: before kickoff the starting QBs and our projected score; live the clock
 * and the down and distance.
 * opts: {date: true (date in the top line), week: true (week label in the top line), rows: {team: standings row}, compact,
 *        why: true (the italic one-line reason, QK.whyLine)} */
function gameCard(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const st = gameState(g);
  const live = st === 'live' || st === 'half', fin = st === 'final';
  const m = g.model || {};
  const x = qkGame(g, o.rows);
  const gt = String(g.gtype || '').toUpperCase();
  x.league = gt && gt !== 'REG' ? gtypeLabel(gt) : (o.week && isNum(g.week) ? weekLabel(g.week, gameSeason(g.game_id)) : (fin && o.date ? fmtDate(g.kickoff, { year: false }) : (g.div_game ? 'Division game' : 'Regular season')));
  const extra = [];
  if (st === 'pre') {
    const qbs = g.qbs || {};
    if (qbs.away || qbs.home) extra.push('<span><i>QBs</i> ' + (qbs.away ? qbText(qbs.away, false) : '?') + ' v ' + (qbs.home ? qbText(qbs.home, false) : '?') + '</span>');
    if (isNum(m.home_pts) && isNum(m.away_pts)) extra.push('<span><i>Projected</i> ' + esc(teamAbbr(g.away)) + ' ' + num(m.away_pts, 0) + '–' + num(m.home_pts, 0) + ' ' + esc(teamAbbr(g.home)) + '</span>');
  } else if (live) {
    extra.push('<span><i>' + esc(st === 'half' ? 'Halftime' : (clockText(g.qtr, g.clock) || 'Live')) + '</i>' + (g.down && g.possession ? ' ' + esc(teamAbbr(g.possession)) + ' ' + esc(downDist(g.down, g.dist, g.yl100)) + (isNum(g.yl100) ? ' at ' + esc(fieldPos(g.yl100, g.possession, otherTeam(g, g.possession))) : '') : '') + '</span>');
  }
  let h = QK.gameCard(x, { sport: false, why: !!o.why });
  if (extra.length && !o.compact) h = h.indexOf('<div class="qk-aside">') > 0 ? h.replace('<div class="qk-aside">', '<div class="gi-gc-x">' + extra.join('') + '</div><div class="qk-aside">') : h.replace(/<\/(a|div)>$/, '<div class="gi-gc-x">' + extra.join('') + '</div></$1>');
  return h;
}
/* The same game in the kit's shared shape (QK.gameCard, QK.ticker, QKC.winProb); rows {team: standings row} adds records. */
function qkGame(g, rows) {
  const st = gameState(g);
  const rec = t => { const r = rows && rows[canonTeam(t)]; return r && isNum(r.w) ? record(r.w, r.l, r.t) : ''; };
  const form = t => { const r = rows && rows[canonTeam(t)]; return r && Array.isArray(r.last5) ? r.last5.join('') : ''; };
  const T = t => ({ name: teamShort(t), abbr: teamAbbr(t), colour: teamInfo(t).colour, href: teamHref(t), record: rec(t), form: form(t) });
  const live = st === 'live' || st === 'half';
  const p0 = (g.model || {}).p_home;
  /* v3: live, the kit reads wp_home as the live chance and p_home as our pre-game call ("before the start we had ...") */
  return { sport: 'nfl', league: 'NFL', id: g.game_id, start: g.kickoff, status: live ? 'live' : (st === 'final' ? 'final' : 'pre'),
    home: T(g.home), away: T(g.away), hs: g.hs, as: g.as, p_home: isNum(p0) ? Number(p0) : null,
    wp_home: live && isNum(g.wp_home) ? Number(g.wp_home) : null, pre_only: live && !isNum(g.wp_home) ? true : undefined,
    market_home: (g.market || {}).p_home, period: g.qtr, clock: fmtClock(g.clock), note: isOT(g) ? 'OT' : '', href: gameHref(g.game_id) };
}
/* Team -> standings row, from season.json rows (for records on game cards). */
function rowsByTeam(rows) { const o = {}; (rows || []).forEach(r => { if (r && r.team) o[canonTeam(r.team)] = r; }); return o; }
function titleProbs(t) { if (!t || t.available === false) return {}; return t.probs || t.prices || t.mid || {}; }

// ── seasons and the shell ─────────────────────────────────────────────────

function currentSeason() {
  const d = INDEX.data;
  if (d && isNum(d.season)) return Number(d.season);
  const now = new Date();
  return now.getMonth() < 2 ? now.getFullYear() - 1 : now.getFullYear();
}
function currentWeek() { const d = INDEX.data; return d && isNum(d.week) ? Number(d.week) : 1; }
function seasons() {
  const d = INDEX.data || {};
  const cur = currentSeason();
  const list = Array.isArray(d.seasons) && d.seasons.length ? d.seasons.map(Number) : [];
  if (!list.length) for (let y = cur; y >= FIRST_SEASON; y--) list.push(y);
  if (list.indexOf(cur) < 0) list.push(cur);
  return list.sort((a, b) => b - a);
}
function phase() { return String((INDEX.data || {}).phase || ''); }
function index() { return INDEX.data; }

/* Season select: keep the page where it makes sense. */
function setSeason(S0) {
  const S = parseInt(S0, 10);
  if (isNaN(S)) return;
  const r = state.route || 'overview';
  const cur = currentSeason();
  if (r === 'games' || r === 'game') { go(weekHref(S, S === cur ? currentWeek() : 1)); return; }
  if (r === 'standings') { go(standingsHref(S, (state.params.query || {}).v)); return; }
  if (r === 'playoffs') { go(playoffsHref(S)); return; }
  if (r === 'overview' || r === 'futures' || r === 'trade' || r === 'transactions' || r === 'history' || r === 'fantasy' || r === 'calibration' || r === 'methodology' || r === 'glossary' || r === 'disclaimer') {
    go(S === cur ? '#/' : standingsHref(S)); return;
  }
  const h = String(location.hash || '#/').replace(/[?].*$/, '');
  const q = Object.assign({}, state.params.query || {});
  delete q.y; delete q.season;
  if (S === cur) delete q.s; else q.s = String(S);
  go((h === '#' ? '#/' : h) + qs(q));
}
function syncShell() {
  if (!SHELL) return;
  SHELL.setSection(state.section || '');
  const sel = document.getElementById('gi-season');
  if (sel && String(sel.value) !== String(state.season)) {
    if (!Array.prototype.some.call(sel.options, o => o.value === String(state.season))) sel.insertAdjacentHTML('beforeend', '<option value="' + state.season + '">' + state.season + '</option>');
    sel.value = String(state.season);
  }
  const S = state.season, cur = currentSeason();
  const map = { fixtures: weekHref(S, S === cur ? currentWeek() : 1), standings: standingsHref(S), teams: ghref('teams', S), players: ghref('players', S), value: ghref('value', S), lab: ghref('lab', S) };
  Array.prototype.forEach.call(document.querySelectorAll('.qk-secnav a[data-sec]'), a => { const k = a.getAttribute('data-sec'); if (map[k]) a.setAttribute('href', map[k]); });
  const live = (INDEX.data && ((INDEX.data.live || []).length || (INDEX.data.games || []).some(isLive))) ? true : false;
  SHELL.setLive({ nfl: live });
}
function searchRows() {
  return ensureNames().then(() => {
    const rows = [];
    const cur = currentSeason();
    Object.keys(NFL_TEAMS).forEach(t => {
      if (t === 'OAK' || t === 'SD' || t === 'STL') return;
      rows.push({ sport: 'nfl', t: teamName(t), s: 'Team · ' + t + ' · ' + (teamInfo(t).division || ''), href: teamHref(t), _o: -1 });
    });
    Object.keys(NAMES).forEach(pid => {
      const x = NAMES[pid] || {};
      if (!x.name) return;
      const last = isNum(x.last) ? Number(x.last) : 0;
      rows.push({ sport: 'nfl', t: x.name, s: [x.pos, x.team ? teamAbbr(x.team) : '', isNum(x.first) ? (Number(x.first) === last ? String(last) : x.first + '–' + (last >= cur ? '' : last)) : ''].filter(Boolean).join(' · '), href: playerHref(pid), _o: cur - last });
    });
    rows.sort((a, b) => a._o - b._o);
    [['Games this week', weekHref(cur, currentWeek())], ['Standings', '#/standings'], ['Power ratings', '#/standings?v=ratings'], ['Playoff picture', '#/playoffs'], ['Season forecasts', '#/futures'],
      ['Player value', '#/value'], ['Trade simulator', '#/trade'], ['Transactions', '#/transactions'], ['Fantasy', '#/fantasy'], ['Leaders', '#/leaders'], ['All-time leaders', '#/history'],
      ['Scatter lab', '#/lab'], ['Compare players', '#/compare'], ['Fourth downs', '#/fourth-downs'], ['Coaches', '#/coaches'], ['Calibration', '#/calibration'], ['Methodology', '#/methodology'], ['Glossary', '#/glossary']]
      .forEach(p => rows.unshift({ sport: 'nfl', t: p[0], s: 'Page', href: p[1] }));
    return rows;
  });
}
function bootShell() {
  const idx = INDEX.data || {};
  const ctx = '<select class="qk-select" id="gi-season" aria-label="Season">' + seasons().map(y => '<option value="' + y + '">' + y + '</option>').join('') + '</select>';
  const secs = QK.sections('nfl').map(s => {
    s.href = { overview: '#/', fixtures: '#/games', standings: '#/standings', teams: '#/teams', players: '#/players', value: '#/value', fantasy: '#/fantasy', lab: '#/lab', model: '#/calibration' }[s.key] || s.href;
    return s;
  });
  SHELL = QK.shell({ sport: 'nfl', section: 'overview', sections: secs, ctx: ctx, search: { load: searchRows } });
  const sel = document.getElementById('gi-season');
  if (sel) { sel.value = String(state.season || currentSeason()); sel.addEventListener('change', () => setSeason(sel.value)); }
  const foot = document.getElementById('qk-footer');
  if (foot) foot.insertAdjacentHTML('beforeend', '<div class="gi-footnote">Data from nflverse (CC BY 4.0), ESPN, Kalshi and Polymarket · our own expected points, win probability and season simulation · ' +
    (idx.updated_at ? 'updated ' + esc(fmtStamp(idx.updated_at)) + ' · ' : '') + '<a href="#/disclaimer">Disclaimer and terms</a> · <a href="#/methodology">Methodology</a></div>');
  const fv = document.getElementById('first-visit-notice');
  let seen = false;
  try { seen = window.localStorage.getItem('qg-notice-v1') === '1'; } catch (e) { seen = false; }
  if (fv && !seen) fv.hidden = false;
  const btn = document.getElementById('fv-dismiss');
  if (btn) btn.addEventListener('click', () => { fv.hidden = true; try { window.localStorage.setItem('qg-notice-v1', '1'); } catch (e) { /* private mode */ } });
}
function init() {
  load('index.json').then(idx => {
    INDEX.data = idx || {};
    state.season = currentSeason();
    bootShell();
    booted = true;
    window.addEventListener('hashchange', () => render());
    render();
  });
}

return {
  state: state, route: route, go: go, render: render, parseHash: parseHash, redirectFor: redirectFor, fixLinks: fixLinks, qs: qs,
  ROUTES: ROUTES, ROUTE_MAP: ROUTE_MAP, TITLES: TITLES, SITE: SITE, FIRST_SEASON: FIRST_SEASON, onLeave: onLeave, interval: interval, setHashQuiet: setHashQuiet, init: init,
  load: load, loadAll: loadAll, uncache: uncache, refreshIndex: refreshIndex, liveRefresh: liveRefresh, ok: ok, reason: reason,
  ypath: ypath, loadYear: loadYear, weekPath: weekPath, loadWeek: loadWeek, gamePath: gamePath, loadGame: loadGame, loadPlayer: loadPlayer, ensureNames: ensureNames, putTeam: putTeam, putPlayer: putPlayer,
  index: index, currentSeason: currentSeason, currentWeek: currentWeek, seasons: seasons, phase: phase, setSeason: setSeason,
  NAMES: NAMES, TEAMS: TEAMS, NFL_TEAMS: NFL_TEAMS, DIVISIONS: DIVISIONS, CONFERENCES: CONFERENCES, DRIVE_RESULTS: DRIVE_RESULTS, PALETTE: PALETTE, GOOD: GOOD, CLOSE: CLOSE, BAD: BAD,
  esc: esc, num: num, int: int, pct: pct, signed: signed, pp: pp, fmtDate: fmtDate, fmtTime: fmtTime, fmtStamp: fmtStamp, localDay: localDay, countdown: countdown,
  ordinal: ordinal, fmtVal: fmtVal, record: record, american: american, fmtOdds: fmtOdds, amToProb: amToProb, fmtLine: fmtLine, parseDate: parseDate, isNum: isNum,
  titleCase: titleCase, fold: fold, median: median, mean: mean, sum: sum, sd: sd, corr: corr, first: first,
  regWeeks: regWeeks, weekNum: weekNum, weekType: weekType, weekLabel: weekLabel, weeksOf: weeksOf, gtypeLabel: gtypeLabel, parseGameId: parseGameId,
  gameSeason: gameSeason, gameWeek: gameWeek, downText: downText, downDist: downDist, fieldPos: fieldPos, fmtClock: fmtClock, qtrLabel: qtrLabel, clockText: clockText,
  otherTeam: otherTeam, driveResult: driveResult, gradeOf: gradeOf, choiceLabel: choiceLabel, gameState: gameState, isFinal: isFinal, isLive: isLive, isPre: isPre, isOT: isOT, isStale: isStale,
  homeLine: homeLine, spreadText: spreadText, surnameOf: surnameOf, qbText: qbText, weatherText: weatherText, titleProbs: titleProbs,
  player: player, playerName: playerName, playerShort: playerShort, playerSurname: playerSurname, playerHref: playerHref, playerLink: playerLink, playerColour: playerColour, canonTeam: canonTeam,
  teamInfo: teamInfo, pair: pair, teamName: teamName, teamShort: teamShort, teamAbbr: teamAbbr, teamColour: teamColour, tc: tc, teamHref: teamHref, teamLink: teamLink, teamChip: teamChip, mark: mark,
  gameHref: gameHref, matchupLink: matchupLink, coachHref: coachHref, coachLink: coachLink, weekHref: weekHref, standingsHref: standingsHref, playoffsHref: playoffsHref,
  compareHref: compareHref, glossHref: glossHref, ghref: ghref, sq: sq,
  GROUPS: GROUPS, GROUP_NAME: GROUP_NAME, GROUP_ONE: GROUP_ONE, groupOf: groupOf, SAMPLE: SAMPLE, sampleKey: sampleKey, sampleOf: sampleOf, scopeOk: scopeOk, metaOf: metaOf,
  metricsFor: metricsFor, allMetrics: allMetrics, metricGroups: metricGroups, colRows: colRows, listOf: listOf, pickKey: pickKey, val: val, headline: headline, PREFS: PREFS,
  shortLabel: shortLabel, cleanDesc: cleanDesc, cleanMetrics: cleanMetrics, catOf: catOf, glossLink: glossLink,
  card: card, grid: grid, chartBox: chartBox, kpi: kpi, kpis: kpis, secHead: secHead, posLabel: posLabel, posLong: posLong, copyText: copyText, rowsByTeam: rowsByTeam, chip: chip, muted: muted, empty: empty, note: note, notBuilt: notBuilt, pageHead: pageHead,
  subnav: subnav, sectionNav: sectionNav, seg: seg, wireSeg: wireSeg, select: select, field: field, table: table, wireRows: wireRows, set: set, alive: alive, pctl: pctl, probBar: probBar,
  gapHTML: gapHTML, edgeHTML: gapHTML, deltaHTML: deltaHTML, tableHTML: tableHTML, sortable: sortable, pill: pill, teamBar: teamBar, weekNav: weekNav, weekLink: weekLink,
  devigAm: devigAm, lineLean: lineLean, gapPts: gapPts, ptsEdge: ptsEdge, pctBars: pctBars, gradePill: gradePill, heatTable: heatTable, gameCard: gameCard, qkGame: qkGame
};
})();
