/* The Quant Gridiron — core: namespace, state, routing, cached loading, helpers, search.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/nfl/PAYLOADS.md). Every page
 * module registers itself with GI.route(name, renderFn) and never edits this file. Routes (hash):
 *
 *   #/                                  hub
 *   #/week  #/week/<S>/<w>              a week of games (w = 1..18; playoffs 19..22, or WC|DIV|CON|SB)
 *   #/game/<game_id>                    game centre (game_id "2026_04_PIT_CLE"; the season is its prefix)
 *   #/standings[/<S>]  #/playoffs[/<S>] standings, playoff picture and bracket
 *   #/teams  #/team/<abbr>              teams
 *   #/players  #/player/<pid>           players (pid = gsis_id "00-0036355")
 *   #/fourth-downs  #/coaches  #/coach/<name>  #/leaders  #/history  #/lab  #/compare[/<a>[/<b>]]
 *   #/markets  #/calibration  #/glossary[/<key>]  #/methodology  #/disclaimer
 *   #/value (player value, best at each position)  #/trade (the trade simulator; state in ?t=&m=)
 *
 * Season and week: every page reads GI.state.season and GI.state.week. The season comes from the
 * route (#/week/<S>/..., #/standings/<S>, #/playoffs/<S>), else a "?s=<YYYY>" query (any page),
 * else index.json "season". The week comes from the route, else "?w=", else index.json "week"
 * (current season) or 1. Links built with the helpers below carry ?s= when the season shown is not
 * the current one.
 *
 * Before a page renders, core loads players_index.json ({pid: [name, team, pos, first, last]}), so
 * GI.playerName / GI.playerLink work synchronously. Team names and colours come from index.json
 * "teams" (and any payload carrying a "teams" dict keyed by abbreviation), with a built-in table of
 * the 32 clubs (plus OAK, SD, STL) as the fallback.
 *
 * A render function is called as fn(el, params, state): `el` is a fresh <div> inside <main id="app">
 * (detached when the viewer navigates away, so async code can test el.isConnected); `params` holds
 * {season, week, id, a, b, S, w, rest, query}. It may return a Promise.
 *
 * Spread convention (assumed; see the report to builder D): every spread is the HOME team's betting
 * line, negative when home is favoured (spread_home -3.5 = home favoured by 3.5). A payload that
 * writes the expected home margin instead can set {"spread_convention": "margin"} on the object
 * (or write "margin"), and GI.homeLine() converts it.
 */
window.GI = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

const C = {
  bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d',
  text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316',
  purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8',
  turf: '#3a9a5f', turf2: '#2a7449', turfDeep: '#173d27', leather: '#c8834a', leather2: '#a5652f', lace: '#f4efe6',
  gi: '#c8834a', accent: '#c8834a', p1: '#c8834a', p2: '#58a6ff', home: '#c8834a', away: '#58a6ff',
  espn: '#8b949e', market: '#e6edf3',
  good: '#3fb950', close: '#d29922', bad: '#f85149',
  pctLow: [50, 105, 220], pctMid: [128, 128, 128], pctHigh: [214, 40, 40]
};
const PALETTE = ['#c8834a', '#58a6ff', '#3fb950', '#bc8cff', '#f85149', '#39d0d8', '#d29922', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
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
const PADDOCK_URL = 'https://pchattani.github.io/the-quant-paddock/';
const HARDWOOD_URL = 'https://pchattani.github.io/the-quant-hardwood/';
const ACE_URL = 'https://pchattani.github.io/the-quant-ace/';
const BULLPEN_URL = 'https://pchattani.github.io/the-quant-bullpen/';
const RINK_URL = 'https://pchattani.github.io/the-quant-rink/';
const SITE = 'The Quant Gridiron';
const FIRST_SEASON = 1999;

/* nflverse abbreviations -> [name, nickname, conference, division, colour, alt]. Colours: club primary and
 * secondary as nflverse's teams table lists them. Relocated franchises keep their old codes for old seasons. */
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
/* Drive results -> [label, colour]. Keys are lower-cased, spaces to underscores. */
const DRIVE_RESULTS = {
  touchdown: ['Touchdown', '#3fb950'], td: ['Touchdown', '#3fb950'],
  field_goal: ['Field goal', '#e3b341'], fg: ['Field goal', '#e3b341'],
  missed_field_goal: ['Missed FG', '#8a5a2e'], missed_fg: ['Missed FG', '#8a5a2e'], blocked_fg: ['Blocked FG', '#8a5a2e'],
  punt: ['Punt', '#6e7681'], blocked_punt: ['Blocked punt', '#f85149'],
  turnover: ['Turnover', '#f85149'], interception: ['Interception', '#f85149'], int: ['Interception', '#f85149'], fumble: ['Fumble', '#f85149'],
  fumble_lost: ['Fumble', '#f85149'], fumble_return_td: ['Fumble (TD)', '#f85149'], int_td: ['Pick-six', '#f85149'],
  turnover_on_downs: ['Downs', '#f97316'], downs: ['Downs', '#f97316'],
  safety: ['Safety', '#bc8cff'],
  end_of_half: ['End of half', '#484f58'], end_of_game: ['End of game', '#484f58'], end_of_period: ['End of half', '#484f58'],
  opp_touchdown: ['Opp. touchdown', '#f85149'], kneel: ['Kneel', '#484f58']
};

// ── state and registries ───────────────────────────────────────────────────

const state = { season: null, week: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = {};      // pid -> {name, team, pos, first, last}
const TEAMS = {};      // abbr -> {abbr, name, short, conference, division, colour, alt}
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];

Object.keys(NFL_TEAMS).forEach(t => {
  const r = NFL_TEAMS[t];
  TEAMS[t] = { abbr: t, name: r[0], short: r[1], conference: r[2], division: r[3], colour: r[4], alt: r[5] };
});

const ROUTES = [];
function addRoute(pattern, name, opts) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, seasonal: !!(opts && opts.seasonal) });
}
addRoute('', 'hub');
addRoute('week', 'week');
addRoute('week/:S', 'week', { seasonal: true });
addRoute('week/:S/:w', 'week', { seasonal: true });
addRoute('game/:id', 'game');
addRoute('standings', 'standings');
addRoute('standings/:S', 'standings', { seasonal: true });
addRoute('playoffs', 'playoffs');
addRoute('playoffs/:S', 'playoffs', { seasonal: true });
addRoute('teams', 'teams');
addRoute('team/:id', 'team');
addRoute('players', 'players');
addRoute('player/:id', 'player');
addRoute('fourth-downs', 'fourth');
addRoute('coaches', 'coaches');
addRoute('coach/:id', 'coach');
addRoute('leaders', 'leaders');
addRoute('history', 'history');
addRoute('lab', 'lab');
addRoute('compare', 'compare');
addRoute('compare/:a', 'compare');
addRoute('compare/:a/:b', 'compare');
addRoute('markets', 'markets');
addRoute('value', 'value');
addRoute('trade', 'trade');
addRoute('transactions', 'transactions');
addRoute('fantasy', 'fantasy');
addRoute('calibration', 'calibration');
addRoute('glossary', 'glossary');
addRoute('glossary/:id', 'glossary');
addRoute('methodology', 'methodology');
addRoute('disclaimer', 'disclaimer');

const ALIASES = { home: 'hub', index: 'hub', '': 'hub', games: 'week', schedule: 'week', scores: 'week', postseason: 'playoffs',
  bracket: 'playoffs', docs: 'methodology', leaderboards: 'leaders', 'fourth-downs': 'fourth', fourth_downs: 'fourth', fourthdowns: 'fourth',
  fourth: 'fourth', referees: 'coaches' };
const ALIAS_SEGS = { games: 'week', schedule: 'week', scores: 'week', postseason: 'playoffs', bracket: 'playoffs', docs: 'methodology',
  leaderboards: 'leaders', fourth: 'fourth-downs', fourth_downs: 'fourth-downs', fourthdowns: 'fourth-downs' };
const TITLES = {
  hub: 'Hub', week: 'Week', game: 'Game centre', standings: 'Standings', playoffs: 'Playoffs', teams: 'Teams', team: 'Team',
  players: 'Players', player: 'Player', fourth: 'Fourth downs', coaches: 'Coaches', coach: 'Coach', leaders: 'Leaders',
  history: 'History', lab: 'Lab', compare: 'Compare', markets: 'Markets', calibration: 'Calibration', glossary: 'Glossary',
  methodology: 'Methodology', disclaimer: 'Disclaimer & terms', value: 'Player value', trade: 'Trade simulator', transactions: 'Transactions', fantasy: 'Fantasy'
};
const NAV_OF = { hub: 'hub', week: 'week', game: 'week', standings: 'standings', playoffs: 'playoffs', teams: 'teams', team: 'teams',
  players: 'players', player: 'players', fourth: 'fourth', coaches: 'coaches', coach: 'coaches', leaders: 'leaders', history: 'history',
  lab: 'lab', compare: 'compare', markets: 'markets', calibration: 'calibration', glossary: 'glossary', methodology: 'methodology',
  value: 'value', trade: 'trade', transactions: 'transactions', fantasy: 'fantasy' };

function normPattern(s) {
  return String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
}
function shape(p) { return p.split('/').map(s => (s.charAt(0) === ':' ? ':' : s)).join('/'); }

/* Register a page renderer: a route name ('game'), an alias ('fourth-downs'), or a pattern ('#/game/<id>'). */
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
  if (state.route === key && booted) render();
}
function routeEntry(name) { return ROUTES.find(r => r.name === name) || null; }

function parseQuery(s) {
  const query = {};
  String(s || '').split('&').forEach(kv => {
    if (!kv) return;
    const i = kv.indexOf('=');
    try { query[decodeURIComponent(i >= 0 ? kv.slice(0, i) : kv)] = i >= 0 ? decodeURIComponent(kv.slice(i + 1)) : ''; } catch (e) { /* malformed */ }
  });
  return query;
}

function parseHash(hash) {
  let h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  let query = {};
  const qi = h.indexOf('?');
  if (qi >= 0) { query = parseQuery(h.slice(qi + 1)); h = h.slice(0, qi); }
  const parts = h.split('/').filter(s => s !== '').map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } });
  if (parts.length && ALIAS_SEGS[parts[0]]) parts[0] = ALIAS_SEGS[parts[0]];
  let best = null, bestLen = -1;
  ROUTES.forEach(r => {
    if (r.segs.length > parts.length) return;
    if (r.segs.length === 0 && parts.length > 0) return;
    for (let i = 0; i < r.segs.length; i++) if (r.segs[i].charAt(0) !== ':' && r.segs[i] !== parts[i]) return;
    // a seasonal segment must look like a season
    for (let i = 0; i < r.segs.length; i++) if (r.segs[i] === ':S' && !/^\d{4}$/.test(parts[i])) return;
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts };
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  let S = params.S ? parseInt(params.S, 10) : NaN;
  if (isNaN(S)) { const q = query.s || query.season || query.y; S = q ? parseInt(q, 10) : NaN; }
  if (isNaN(S) && best.name === 'game' && params.id) S = gameSeason(params.id) || NaN;
  params.season = isNaN(S) ? undefined : S;
  let w = params.w !== undefined ? weekNum(params.w, params.season) : null;
  if (w === null && query.w) w = weekNum(query.w, params.season);
  if (w === null && best.name === 'game' && params.id) w = gameWeek(params.id);
  params.week = w === null ? undefined : w;
  return { name: best.name, params: params, parts: parts };
}

function handlerFor(name) { return HANDLERS[name] || null; }

/* Register cleanup work (timers, listeners) run when the viewer leaves the page. */
function onLeave(fn) { if (typeof fn === 'function') CLEANUPS.push(fn); }
/* setInterval that is cleared on navigation. */
function interval(fn, ms) { const id = setInterval(fn, ms); onLeave(() => clearInterval(id)); return id; }
function runCleanups() {
  const list = CLEANUPS; CLEANUPS = [];
  list.forEach(fn => { try { fn(); } catch (e) { console.warn('cleanup failed', e); } });
}

let booted = false, renderSeq = 0;
function render(opts) {
  const keep = !!(opts && opts.keep === true);
  const y0 = window.scrollY;
  runCleanups();
  closeSearch();
  const r = parseHash();
  const S = r.params.season || currentSeason();
  r.params.season = S;
  const w = isNum(r.params.week) ? r.params.week : (S === currentSeason() ? currentWeek() : 1);
  r.params.week = w;
  state.season = S;
  state.week = w;
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  fillPickers();
  updateHeader();
  markNav(NAV_OF[r.name] || '');
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'page page-' + r.name.replace(/[^a-z0-9-]/gi, '-');
  app.appendChild(el);
  document.title = (r.name === 'hub' ? '' : (TITLES[r.name] || 'Page') + ' · ') + SITE;
  setMeta('');
  if (!keep) window.scrollTo(0, 0);
  const fn = handlerFor(r.name);
  if (!fn) {
    el.innerHTML = r.name === 'notfound'
      ? comingHTML('Page not found', 'There is no page at <code>' + esc(location.hash) + '</code>. Try the hub or the search box.')
      : comingHTML((TITLES[r.name] || 'This page') + ' is coming', 'This part of ' + SITE + ' is still being built.');
    return;
  }
  const seq = ++renderSeq;
  el.innerHTML = '<div class="muted">Loading…</div>';
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

/* Cached fetch of data/<path>. Resolves to the parsed JSON, or null when the file is missing or
 * broken. A payload written with "ok": false resolves as written: test with GI.ok(d). */
function load(p0) {
  const p = String(p0).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(d => { learn(p, d); return d; })
    .catch(err => { console.warn('payload missing:', p, err.message); return null; })
    .then(d => { if (d !== null) CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
function loadAll(paths) { return Promise.all(paths.map(load)); }
/* Forget cached payloads so the next load fetches them again (live refresh). */
function uncache(paths) { (Array.isArray(paths) ? paths : [paths]).forEach(p0 => { const p = String(p0).replace(/^\/+/, '').replace(/^data\//, ''); delete CACHE[p]; }); }
/* Re-fetch index.json (fresh live cards), then resolve with it. */
function refreshIndex() { uncache('index.json'); return load('index.json').then(d => { if (d) INDEX.data = d; return INDEX.data; }); }
/* Every ms while the page is shown and visible: forget `paths`, refresh index.json, re-render the page. */
function liveRefresh(paths, ms) {
  interval(() => {
    if (document.visibilityState !== 'visible') return;
    uncache(paths || []);
    refreshIndex().then(() => render({ keep: true }));
  }, ms || 60000);
}
function ok(d) { return !!d && d.ok !== false; }
function reason(d) { return d && d.reason ? String(d.reason) : 'not built yet'; }
function cached(p0) { const p = String(p0).replace(/^data\//, ''); return Object.prototype.hasOwnProperty.call(CACHE, p) ? CACHE[p] : undefined; }
/* Per-season payload path: ypath('season.json') -> '2026/season.json'. */
function ypath(file, S) { return (S || state.season || currentSeason()) + '/' + file; }
function loadYear(file, S) { return load(ypath(file, S)); }
function weekPath(w, S) { return ypath('weeks/' + w + '.json', S); }
function loadWeek(w, S) { return load(weekPath(w, S)); }
function gamePath(id) { return ypath('games/' + id + '.json', gameSeason(id)); }
/* A game payload (its season is the game_id prefix). */
function loadGame(id) { return load(gamePath(id)); }
function playerPath(pid) { return 'players/' + pid + '.json'; }
function loadPlayer(pid) { return load(playerPath(pid)); }

/* players_index.json: resolves when it has loaded (or failed). */
let namesP = null;
function ensureNames() {
  if (!namesP) namesP = load('players_index.json');
  return namesP;
}
/* players_index.json comes flat ({pid: [...]}) per PAYLOADS.md, or wrapped ({"ok", ..., "players": {...}}): accept both. */
function playersOf(d) { return d && d.players && typeof d.players === 'object' && !Array.isArray(d.players) ? d.players : (d || {}); }

function canonTeam(t) { const s = String(t || '').toUpperCase(); return TEAM_ALIASES[s] || s; }
function putTeam(abbr0, x) {
  const abbr = canonTeam(abbr0);
  if (!abbr || !x || typeof x !== 'object' || !/^[A-Z]{2,3}$/.test(abbr)) return;
  const cur = TEAMS[abbr] || { abbr: abbr };
  const o = {};
  ['name', 'short', 'nickname', 'conference', 'division', 'colour', 'alt', 'city', 'stadium'].forEach(k => { if (x[k] !== undefined && x[k] !== null && x[k] !== '') o[k] = x[k]; });
  if (x.color && !o.colour) o.colour = x.color;
  if (x.colour2 && !o.alt) o.alt = x.colour2;
  if (x.nickname && !o.short) o.short = x.nickname;
  if (x.conf && !o.conference) o.conference = x.conf;
  if (o.colour && !/^#/.test(o.colour)) o.colour = '#' + o.colour;
  if (o.alt && !/^#/.test(o.alt)) o.alt = '#' + o.alt;
  TEAMS[abbr] = Object.assign({}, cur, o);
}
function putPlayer(pid, info) { if (!pid || !info) return; NAMES[pid] = Object.assign({}, NAMES[pid] || {}, info); }
/* Harvest names and teams from any payload that carries them. */
function learn(p, d) {
  if (!d || typeof d !== 'object') return;
  try {
    if (p === 'players_index.json') {
      const P = playersOf(d);
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
  } catch (e) { console.warn('learn failed for', p, e); }
}

// ── formatting ─────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
/* A whole number with thousands separators: 20000 -> "20,000". */
function int(v) { return isNum(v) ? Math.round(Number(v)).toLocaleString('en-US') : '—'; }
function num(v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; }
/* pct(0.1234) -> "12.3%" (input is a probability 0-1). */
function pct(p, d) {
  if (!isNum(p)) return '—';
  const dd = d === undefined ? 1 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd)) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd)) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
}
function signed(v, d) {
  if (!isNum(v)) return '—';
  const s = Number(v).toFixed(d === undefined ? 1 : d);
  return (Number(s) > 0 ? '+' : '') + s.replace(/^-(0\.?0*)$/, '$1');
}
/* Percentage-point difference of two probabilities: pp(0.55, 0.50) -> "+5.0 pp". */
function pp(a, b, d) { return isNum(a) && isNum(b) ? signed((a - b) * 100, d === undefined ? 1 : d) + ' pp' : '—'; }
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
/* fmtDate("2026-10-04") -> "Sun 4 Oct 2026". opts {year:false, time:true, weekday:false}. A plain date is shown as written. */
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
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function fmtStamp(s) {
  const d = parseDate(s);
  if (!d) return s ? String(s) : '';
  return fmtDate(d, { year: false }) + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function localDay(s) {
  const d = parseDate(s);
  if (!d) return '';
  if (String(s).length === 10) return String(s);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function todayISO() { return localDay(new Date().toISOString()); }
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
/* Format a catalogue value by its METRIC fmt: int|0|1|2|3|pct|prob|signed|signed1|pm|epa|yds|sec|plus.
 * pct and prob are fractions 0-1; epa is 3 dp signed. */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt)) {
    case 'pct': return (x * 100).toFixed(1) + '%';
    case 'prob': return pct(x);
    case 'int': case 'plus': return int(x);
    case 'pm': case 'signed1': return signed(x, 1);
    case 'signed': return signed(x, 2);
    case 'epa': return signed(x, 3);
    case '0': return x.toFixed(0);
    case '1': case 'yds': return x.toFixed(1);
    case '3': return x.toFixed(3);
    case 'sec': return x.toFixed(2) + 's';
    case 'deg': return x.toFixed(0) + '°';
    default: return x.toFixed(2);
  }
}
function metric(list, key) { return (list || []).find(m => m && m.key === key) || null; }
/* W-L or W-L-T (the tie only when there is one). */
function record(w, l, t) {
  if (!isNum(w) || !isNum(l)) return '—';
  return Math.round(w) + '-' + Math.round(l) + (isNum(t) && Number(t) > 0 ? '-' + Math.round(t) : '');
}
/* Fair American odds of a probability: 0.6 -> "-150". */
function american(p) {
  if (!isNum(p) || p <= 0 || p >= 1) return '—';
  return p >= 0.5 ? '-' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p);
}
/* Fair decimal odds: 0.4 -> "2.50". */
function decimal(p) { return isNum(p) && p > 0 ? (1 / p).toFixed(p > 0.1 ? 2 : 1) : '—'; }
/* An American price as text: 104 -> "+104", -126 -> "-126". */
function fmtOdds(a) { return isNum(a) ? (Number(a) > 0 ? '+' : '') + Math.round(Number(a)) : '—'; }
/* American price -> implied probability (with the vig). */
function amToProb(a) {
  if (!isNum(a) || Number(a) === 0) return null;
  const x = Number(a);
  return x < 0 ? -x / (-x + 100) : 100 / (x + 100);
}
/* Two American prices [a, b] -> de-vigged probability of a (null when missing). */
function devigAm(pair) {
  if (!pair) return null;
  const a = amToProb(pair[0]), b = amToProb(pair[1]);
  return a === null || b === null ? null : a / (a + b);
}
/* Two-way decimal odds [o1, o2] -> de-vigged p1 (null when missing). */
function devig2(o) {
  if (!o || !isNum(o[0]) || !isNum(o[1]) || o[0] <= 1 || o[1] <= 1) return null;
  const a = 1 / o[0], b = 1 / o[1];
  return a / (a + b);
}
/* A spread number: -3.5 -> "-3.5", 3 -> "+3", 0 -> "PK". */
function fmtLine(v) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  if (x === 0) return 'PK';
  return (x > 0 ? '+' : '') + (Number.isInteger(x) ? String(x) : x.toFixed(1));
}
function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// ── football vocabulary ────────────────────────────────────────────────────

/* Regular-season weeks in a season: 17 to 2020, 18 from 2021. */
function regWeeks(S) { return Number(S || state.season || currentSeason()) >= 2021 ? 18 : 17; }
/* A week as a number: 4 -> 4, 'WC' -> 19 (2021+), 'SB' -> 22. */
function weekNum(w, S) {
  if (isNum(w)) return Number(w);
  const k = String(w || '').toUpperCase();
  const i = POST_KEYS.indexOf(k === 'CONF' ? 'CON' : k);
  return i >= 0 ? regWeeks(S) + 1 + i : null;
}
/* 'REG' | 'WC' | 'DIV' | 'CON' | 'SB' for a week number. */
function weekType(w, S) {
  const n = weekNum(w, S);
  if (!isNum(n)) return '';
  const R = regWeeks(S);
  return n <= R ? 'REG' : POST_KEYS[Math.min(3, n - R - 1)];
}
/* weekLabel(4) -> "Week 4"; weekLabel(19, 2026) -> "Wild Card"; short -> "W4" / "WC". */
function weekLabel(w, S, short) {
  const n = weekNum(w, S);
  if (!isNum(n)) return '—';
  const t = weekType(n, S);
  if (t === 'REG') return short ? 'W' + n : 'Week ' + n;
  return short ? GTYPE_SHORT[t] : ({ WC: 'Wild Card', DIV: 'Divisional', CON: 'Conference', SB: 'Super Bowl' })[t];
}
/* Every week of a season: [{w, label, type}] (18 + 4 from 2021). */
function weeksOf(S) {
  const R = regWeeks(S), out = [];
  for (let w = 1; w <= R + 4; w++) out.push({ w: w, label: weekLabel(w, S), short: weekLabel(w, S, true), type: weekType(w, S) });
  return out;
}
function gtypeLabel(t, short) { const k = String(t || '').toUpperCase(); return (short ? GTYPE_SHORT : GTYPE_LONG)[k] || String(t || ''); }
/* nflverse game_id "2026_04_PIT_CLE" -> {season, week, away, home}. */
function parseGameId(id) {
  const m = /^(\d{4})_(\d{1,2})_([A-Z]{2,3})_([A-Z]{2,3})$/.exec(String(id || ''));
  return m ? { season: Number(m[1]), week: Number(m[2]), away: m[3], home: m[4] } : null;
}
function gameSeason(id) { const g = parseGameId(id); return g ? g.season : null; }
function gameWeek(id) { const g = parseGameId(id); return g ? g.week : null; }
/* 1 -> "1st", 4 -> "4th". */
function downText(d) { return isNum(d) && d >= 1 && d <= 4 ? ordinal(d) : ''; }
/* downDist(3, 7) -> "3rd & 7"; goal to go (dist >= yl100) -> "1st & Goal". */
function downDist(down, dist, yl100) {
  if (!isNum(down) || Number(down) < 1) return '';
  const goal = isNum(yl100) && isNum(dist) && Number(dist) >= Number(yl100);
  return downText(down) + ' & ' + (goal ? 'Goal' : (isNum(dist) ? Math.round(dist) : '?'));
}
/* Field position from yards to the opponent's goal line: fieldPos(65, 'PIT', 'CLE') -> "PIT 35"; 30 -> "CLE 30". */
function fieldPos(yl100, pos, opp) {
  if (!isNum(yl100)) return '';
  const y = Math.round(Number(yl100));
  if (y === 50) return 'Midfield';
  if (y > 50) return (pos ? teamAbbr(pos) : 'Own') + ' ' + (100 - y);
  return (opp ? teamAbbr(opp) : 'Opp') + ' ' + y;
}
/* Clock in a quarter: 754 (seconds) -> "12:34"; "12:34" stays. */
function fmtClock(c) {
  if (c === null || c === undefined || c === '') return '';
  if (isNum(c)) { const s = Math.max(0, Math.round(Number(c))); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  return String(c);
}
/* qtrLabel(3) -> "Q3"; 5 -> "OT"; 6 -> "2OT"; long -> "3rd quarter" / "Overtime". */
function qtrLabel(q, long) {
  if (!isNum(q)) return '';
  const n = Number(q);
  if (n <= 4) return long ? ordinal(n) + ' quarter' : 'Q' + n;
  return long ? (n === 5 ? 'Overtime' : (n - 4) + 'nd overtime') : (n === 5 ? 'OT' : (n - 4) + 'OT');
}
/* "Q3 12:34". */
function clockText(q, c) { return [qtrLabel(q), fmtClock(c)].filter(Boolean).join(' '); }
/* The other team of a game for a team. */
function otherTeam(g, t) { if (!g) return null; return String(t) === String(g.home) ? g.away : g.home; }
/* A drive result: {label, colour}. */
function driveResult(r) {
  const k = String(r || '').toLowerCase().replace(/[\s-]+/g, '_');
  const x = DRIVE_RESULTS[k];
  if (x) return { label: x[0], colour: x[1] };
  if (/touchdown|_td$/.test(k)) return { label: 'Touchdown', colour: DRIVE_RESULTS.touchdown[1] };
  if (/missed|blocked_f/.test(k)) return { label: titleCase(k), colour: DRIVE_RESULTS.missed_fg[1] };
  if (/field_goal|^fg/.test(k)) return { label: 'Field goal', colour: DRIVE_RESULTS.field_goal[1] };
  if (/fumble|intercept|turnover/.test(k)) return { label: titleCase(k), colour: C.red };
  if (/downs/.test(k)) return { label: 'Downs', colour: C.orange };
  if (/half|game|period/.test(k)) return { label: titleCase(k), colour: '#484f58' };
  return { label: titleCase(k) || '—', colour: C.text3 };
}
/* A fourth-down decision grade -> {label, colour, key}: from the payload's letter (analytics/games.GRADE_CUTS:
 * A <= 0.5 pp, B <= 1.5, C <= 3, D <= 6, F beyond; A/B right call, C close call, D/F mistake), a word ('correct'/'good',
 * 'close'/'toss-up', 'mistake'/'bad'/'wrong') or, given a number, the win probability lost (0-1) on the same cut-offs:
 * <= 1.5 pp right call, <= 3 pp close call, else mistake. */
function gradeOf(g, wpLost) {
  const s = String(g === null || g === undefined ? '' : g).toLowerCase();
  if (/^(correct|good|right|right_call|agree|optimal|ok|a|b)$/.test(s)) return { key: 'good', label: 'Right call', colour: C.good };
  if (/^(close|close_call|toss.?up|marginal|neutral|c)$/.test(s)) return { key: 'close', label: 'Close call', colour: C.close };
  if (/^(mistake|bad|wrong|error|blunder|poor|d|f)$/.test(s)) return { key: 'bad', label: 'Mistake', colour: C.bad };
  const x = isNum(wpLost) ? Number(wpLost) : (isNum(g) ? Number(g) : null);
  if (x === null) return { key: '', label: '—', colour: C.text3 };
  const a = Math.abs(x) > 1 ? Math.abs(x) / 100 : Math.abs(x);
  if (a <= 0.015) return { key: 'good', label: 'Right call', colour: C.good };
  if (a <= 0.03) return { key: 'close', label: 'Close call', colour: C.close };
  return { key: 'bad', label: 'Mistake', colour: C.bad };
}
function choiceLabel(c) {
  const k = String(c || '').toLowerCase();
  if (/^go|run|pass|go_for_it/.test(k)) return 'Go for it';
  if (/punt/.test(k)) return 'Punt';
  if (/fg|field/.test(k)) return 'Field goal';
  return titleCase(k) || '—';
}

/* Status of a GAME_CARD / game: 'pre' | 'live' | 'half' | 'final' | 'postponed' | 'cancelled' | 'delayed'. */
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
function isOT(g) { return !!(g && (g.overtime || (isNum(g.qtr) && Number(g.qtr) >= 5) || (Array.isArray(g.quarters) && g.quarters.length > 4))); }
/* A status chip: kickoff time, live quarter and clock, Half, Final (Final/OT). */
function statusChip(g) {
  const st = gameState(g);
  if (st === 'live') return '<span class="chip st-live"><span class="live-dot"></span> ' + esc(clockText(g.qtr, g.clock) || 'Live') + '</span>';
  if (st === 'half') return '<span class="chip st-live"><span class="live-dot"></span> Half</span>';
  if (st === 'final') return '<span class="chip st-ft">Final' + (isOT(g) ? '/OT' : '') + '</span>';
  if (st === 'pre') {
    const k = g.kickoff || g.date;
    const t = fmtTime(k);
    return '<span class="chip st-time">' + esc((parseDate(k) ? DAYS[parseDate(k).getDay()] + ' ' : '') + (t || 'TBD')) + '</span>';
  }
  return '<span class="chip warn">' + esc(titleCase(st)) + '</span>';
}

/* The home betting line from an object carrying a spread: {spread_home} | {spread} | {margin} (expected home
 * margin, sign flipped) | {spread, spread_convention: 'margin'}. Negative = home favoured. */
function homeLine(o) {
  if (!o) return null;
  if (isNum(o.spread_home)) return o.spread_convention === 'margin' ? -Number(o.spread_home) : Number(o.spread_home);
  if (isNum(o.spread)) return o.spread_convention === 'margin' ? -Number(o.spread) : Number(o.spread);
  if (isNum(o.margin)) return -Number(o.margin);
  if (isNum(o.home_margin)) return -Number(o.home_margin);
  return null;
}
/* "PIT -3.5" (the favourite and its line), "Pick'em" at 0; from the home line. */
function spreadText(home, away, line) {
  if (!isNum(line)) return '—';
  const x = Number(line);
  if (Math.abs(x) < 0.05) return "Pick'em";
  return (x < 0 ? teamAbbr(home) : teamAbbr(away)) + ' ' + fmtLine(-Math.abs(x));
}
/* A QB field: a gsis id (linked surname), a name, or {pid, name, status}. */
function qbText(q, link) {
  if (!q) return '';
  if (typeof q === 'object') {
    const pid = q.pid || q.id || q.gsis_id;
    const nm = q.name || (pid ? playerName(pid) : '');
    const st = q.status && !/^(active|start|starter|ok|healthy)$/i.test(q.status) ? ' <span class="qb-st">' + esc(q.status) + '</span>' : '';
    return (pid && link !== false ? playerLink(pid, { name: surnameOf(nm) }) : esc(surnameOf(nm))) + st;
  }
  const s = String(q);
  if (/^\d\d-\d{5,}$/.test(s)) return link === false ? esc(playerSurname(s)) : playerLink(s, { surname: true });
  return esc(surnameOf(s));
}
function surnameOf(n) {
  const p = String(n || '').split(' ');
  if (p.length < 2) return p[0];
  const sfx = /^(Jr\.?|Sr\.?|II|III|IV|V)$/i.test(p[p.length - 1]);
  return sfx && p.length > 2 ? p[p.length - 2] + ' ' + p[p.length - 1] : p.slice(1).join(' ');
}
/* Weather {temp (F), wind (mph), desc|conditions, roof} -> "Dome" | "54°F · wind 12 mph · Rain". */
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

// ── names, teams, links ────────────────────────────────────────────────────

function player(pid) { return NAMES[String(pid)] || {}; }
function playerInfo(pid) { return player(pid); }
function playerName(pid) { const x = NAMES[String(pid)]; return x && x.name ? x.name : (pid ? 'Player ' + pid : '—'); }
function playerShort(pid) {
  const x = NAMES[String(pid)] || {};
  if (x.short) return x.short;
  const n = playerName(pid).split(' ');
  return n.length > 1 ? n[0].charAt(0) + '. ' + n.slice(1).join(' ') : n[0];
}
function playerSurname(pid) { return surnameOf(playerName(pid)); }
/* '?s=S' when S is not the current season, else ''. */
function sq(S) { const s = S || state.season; return s && Number(s) !== currentSeason() ? '?s=' + s : ''; }
/* A route with the season query: ghref('teams') -> '#/teams' (or '#/teams?s=2024'). */
function ghref(sub, S) { return '#/' + String(sub || '').replace(/^\/+/, '') + sq(S); }
function href(sub, S) { return ghref(sub, S); }
function playerHref(pid) { return '#/player/' + encodeURIComponent(pid); }
/* <a> to the player page. opts {name, short: true, surname: true, team: true (abbr after), pos: true} or a name string. */
function playerLink(pid, opts) {
  if (!pid) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.surname ? playerSurname(pid) : o.short ? playerShort(pid) : playerName(pid));
  const x = player(pid);
  const tail = (o.pos && x.pos ? '<span class="pl-pos">' + esc(x.pos) + '</span>' : '') + (o.team && x.team ? '<span class="pl-team">' + esc(teamAbbr(x.team)) + '</span>' : '');
  return '<a class="ply-link" href="' + playerHref(pid) + '">' + esc(label) + tail + '</a>';
}
function teamInfo(t) { return TEAMS[canonTeam(t)] || {}; }
function teamName(t) { const x = teamInfo(t); return x.name || (t ? String(t) : '—'); }
function teamShort(t) { const x = teamInfo(t); return x.short || x.name || (t ? String(t) : '—'); }
function teamAbbr(t) { return t ? (teamInfo(t).abbr || String(t)) : '—'; }
function hexRGB(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return null;
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function lum(rgb) { return (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255; }
/* A team's colour that reads on the dark theme: the alternate when the primary is near black and the alternate
 * is lighter, then lifted toward white until it reads (most club navies do not). */
function teamColour(t) {
  const x = teamInfo(t);
  let rgb = hexRGB(x.colour);
  if (!rgb) return PALETTE[hashIndex(t || '?', PALETTE.length)];
  const alt = hexRGB(x.alt);
  if (lum(rgb) < 0.08 && alt && lum(alt) > 0.25) rgb = alt;
  let c = rgb.slice(), k = 0;
  while (lum(c) < 0.32 && k < 12) { c = c.map(v => Math.round(v + (255 - v) * 0.14)); k++; }
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
}
/* The raw club colour (for fills behind white text). */
function teamColourRaw(t) { return teamInfo(t).colour || C.bg3; }
function teamAlt(t) { return teamInfo(t).alt || C.text3; }
function teamBar(t) { return '<span class="team-bar" style="background:' + teamColour(t) + '"></span>'; }
function teamHref(t, S) { return ghref('team/' + encodeURIComponent(teamAbbr(t)), S); }
/* <a> to the team page. opts {abbr: true, short: true, bar: true (default), name, season}. */
function teamLink(t, opts) {
  if (!t) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.abbr ? teamAbbr(t) : o.short ? teamShort(t) : teamName(t));
  const bar = o.bar === false ? '' : teamBar(t);
  return '<a class="team-link" href="' + teamHref(t, o.season) + '" title="' + esc(teamName(t)) + '">' + bar + esc(label) + '</a>';
}
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
function playerColour(pid) { return pid ? PALETTE[hashIndex(pid, PALETTE.length)] : C.text3; }
function gameHref(id) { return '#/game/' + encodeURIComponent(id); }
/* <a> to the game centre (label default "Game centre"). */
function gameLink(id, label) {
  if (!id) return '<span class="muted-inline">—</span>';
  return '<a class="game-link" href="' + gameHref(id) + '">' + esc(label || 'Game centre') + '</a>';
}
/* "PIT @ CLE" linked to the game centre. */
function matchupLink(id, away, home) {
  const g = parseGameId(id) || {};
  const a = away || g.away, h = home || g.home;
  return '<a class="game-link" href="' + gameHref(id) + '">' + esc(teamAbbr(a)) + ' @ ' + esc(teamAbbr(h)) + '</a>';
}
function coachHref(name) { return '#/coach/' + encodeURIComponent(String(name || '')); }
function coachLink(name) {
  if (!name) return '<span class="muted-inline">—</span>';
  return '<a class="coach-link" href="' + coachHref(name) + '">' + esc(name) + '</a>';
}
function weekHref(S, w) { const s = S || state.season || currentSeason(); return '#/week/' + s + '/' + (isNum(w) ? w : (s === currentSeason() ? currentWeek() : 1)); }
function weekLink(S, w, label) { return '<a href="' + weekHref(S, w) + '">' + esc(label || weekLabel(w, S)) + '</a>'; }
function standingsHref(S) { const s = S || state.season; return '#/standings' + (s && Number(s) !== currentSeason() ? '/' + s : ''); }
function playoffsHref(S) { const s = S || state.season; return '#/playoffs' + (s && Number(s) !== currentSeason() ? '/' + s : ''); }
function compareHref(a, b) { return '#/compare' + (a ? '/' + encodeURIComponent(a) : '') + (b ? '/' + encodeURIComponent(b) : ''); }
function glossHref(key) { return '#/glossary' + (key ? '/' + encodeURIComponent(key) : ''); }

/* A GAME_CARD tile (index.json games/live/recent, schedule.json, weeks/<w>.json). Links to the game centre.
 * Lines: model (home win %, line, total), market (de-vigged home win %, sources), the closing/current line,
 * live WP with down, distance and field position. opts {date: true (day before the time), compact, week: true (week tag)}. */
function gameCard(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const st = gameState(g);
  const m = g.model || {}, mk = g.market || null, ln = g.line || null;
  const pH = isNum(m.p_home) ? Number(m.p_home) : null;
  const live = st === 'live' || st === 'half', fin = st === 'final';
  const hs = isNum(g.hs) ? g.hs : null, as = isNum(g.as) ? g.as : null;
  const pShow = live && isNum(g.wp_home) ? Number(g.wp_home) : (fin ? null : pH);
  const winH = fin && hs !== null && as !== null && hs > as, winA = fin && hs !== null && as !== null && as > hs;
  const qbs = g.qbs || {};
  const row = (t, score, p, win, lose, side) =>
    '<div class="gc-team' + (win ? ' gc-win' : '') + (lose ? ' gc-lose' : '') + '">' + teamBar(t) +
    '<span class="gc-name"><span class="gc-abbr">' + esc(teamAbbr(t)) + '</span> <span class="gc-full">' + esc(teamShort(t)) + '</span>' +
    (live && g.possession && String(g.possession) === String(t) ? '<span class="gc-pos" title="Possession">●</span>' : '') +
    (st === 'pre' && qbs[side] ? '<span class="gc-sp" title="Starting quarterback">' + qbText(qbs[side], false) + '</span>' : '') + '</span>' +
    (st === 'pre' || score === null ? '' : '<span class="gc-score">' + esc(score) + '</span>') +
    '<span class="gc-p" title="' + (live && isNum(g.wp_home) ? 'Live' : 'Model pre-game') + ' ' + side + ' win probability">' + (p === null ? '' : pct(p, 0)) + '</span></div>';
  let top = statusChip(g);
  if (o.date) top = '<span class="gc-date">' + esc(fmtDate(g.kickoff || g.date, { year: false, weekday: st !== 'pre' })) + '</span> ' + top;
  const gt = String(g.gtype || '').toUpperCase();
  const tag = (gt && gt !== 'REG' ? gtypeLabel(gt) : (o.week && isNum(g.week) ? weekLabel(g.week, gameSeason(g.game_id)) : '')) +
    (st === 'pre' && g.weather ? (gt && gt !== 'REG' || o.week ? ' · ' : '') + weatherText(g.weather, g.roof) : '');
  const lines = [];
  const mLine = homeLine(m);
  if (pH !== null || isNum(m.total) || isNum(mLine)) {
    lines.push('<span class="gc-l"><b>Model</b> ' + (pH !== null ? esc(teamAbbr(pH >= 0.5 ? g.home : g.away)) + ' ' + pct(Math.max(pH, 1 - pH), 0) : '') +
      (isNum(mLine) ? ' · ' + esc(spreadText(g.home, g.away, mLine)) : '') + (isNum(m.total) ? ' · ' + num(m.total, 1) : '') + '</span>');
  }
  if (mk && isNum(mk.p_home)) {
    const fav = (pH !== null ? pH : mk.p_home) >= 0.5 ? 'home' : 'away';
    const mp = fav === 'home' ? mk.p_home : 1 - mk.p_home, mm = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    lines.push('<span class="gc-l"><b>Market</b> ' + esc(teamAbbr(g[fav])) + ' ' + pct(mp, 0) + (mm !== null && !fin ? ' (' + edgeHTML(mm, mp, 0) + ')' : '') +
      (mk.sources && mk.sources.length ? ' <span class="src-chip">' + esc(mk.sources.join(' · ')) + '</span>' : '') + '</span>');
  }
  if (ln) {
    const l = homeLine(ln);
    const bits = [];
    if (isNum(l)) bits.push(esc(spreadText(g.home, g.away, l)));
    if (isNum(ln.total)) bits.push('O/U ' + num(ln.total, 1));
    if (isNum(ln.ml_home) && isNum(ln.ml_away)) bits.push(esc(teamAbbr(g.home)) + ' ' + fmtOdds(ln.ml_home));
    if (bits.length) lines.push('<span class="gc-l"><b>' + esc(ln.src || (fin ? 'Close' : 'Line')) + '</b> ' + bits.join(' · ') + '</span>');
  }
  if (live) {
    const sit = g.down ? downDist(g.down, g.dist, g.yl100) + (isNum(g.yl100) ? ' at ' + fieldPos(g.yl100, g.possession, otherTeam(g, g.possession)) : '') : '';
    const fav = isNum(g.wp_home) ? (g.wp_home >= 0.5 ? g.home : g.away) : null;
    lines.push('<span class="gc-l gc-wp"><b>Live</b> ' + (fav ? esc(teamAbbr(fav)) + ' ' + pct(Math.max(g.wp_home, 1 - g.wp_home), 0) + ' to win' : '') +
      (sit ? (fav ? ' · ' : '') + esc((g.possession ? teamAbbr(g.possession) + ' ' : '') + sit) : '') + '</span>');
  }
  return '<a class="gc' + (live ? ' gc-live' : '') + (o.compact ? ' gc-compact' : '') + '" href="' + gameHref(g.game_id || g.id) + '">' +
    '<div class="gc-top">' + top + (tag ? '<span class="gc-tag">' + esc(tag) + '</span>' : '') + '</div>' +
    row(g.away, as, pShow === null ? null : 1 - pShow, winA, winH, 'away') + row(g.home, hs, pShow, winH, winA, 'home') +
    (lines.length ? '<div class="gc-lines">' + lines.join('') + '</div>' : '') + '</a>';
}
/* A market TITLE dict -> {id: p} (de-vigged "probs", else "prices", else the raw "mid"); {} when unavailable. */
function titleProbs(t) {
  if (!t || t.available === false) return {};
  return t.probs || t.prices || t.mid || {};
}

// ── seasons and weeks ──────────────────────────────────────────────────────

function currentSeason() {
  const d = INDEX.data;
  if (d && isNum(d.season)) return Number(d.season);
  const now = new Date();
  return now.getMonth() < 2 ? now.getFullYear() - 1 : now.getFullYear();
}
function currentWeek() {
  const d = INDEX.data;
  return d && isNum(d.week) ? Number(d.week) : 1;
}
function seasons() {
  const d = INDEX.data || {};
  const cur = currentSeason();
  let list = Array.isArray(d.seasons) && d.seasons.length ? d.seasons.map(Number) : [];
  if (!list.length) for (let y = cur; y >= FIRST_SEASON; y--) list.push(y);
  if (list.indexOf(cur) < 0) list.push(cur);
  return list.sort((a, b) => b - a);
}
function phase() { const d = INDEX.data || {}; return String(d.phase || ''); }

// ── HTML builders ──────────────────────────────────────────────────────────

function card(title, sub, bodyHtml, id) {
  return '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' +
    (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + '</div>' : '') +
    (bodyHtml || '') + '</div>';
}
function muted(text) { return '<div class="muted">' + text + '</div>'; }
function chip(text, cls) { return '<span class="chip' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</span>'; }
function notBuilt(what, d) { return muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.'); }
/* A coloured pill (team colour by default): pill('TD', '#3fb950'). */
function pill(text, colour, title) {
  return '<span class="gi-pill"' + (title ? ' title="' + esc(title) + '"' : '') + ' style="border-color:' + (colour || C.border) + ';color:' + (colour || C.text2) + '">' + esc(text) + '</span>';
}
function gradePill(grade, wpLost) { const g = gradeOf(grade, wpLost); return g.key ? pill(g.label, g.colour) : ''; }

/* Table. cols: [{label, align, title, sortable:false, cls}]. rows: [{cells, _class, _href}] or arrays of cells;
 * a cell is {v, html, cls, align, title, style} or a primitive. opts {compact, sticky, cls, id}. */
function tableHTML(cols, rows, opts) {
  const o = opts || {};
  let h = '<div class="table-wrap' + (o.compact ? ' compact' : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '><table class="wc-table' + (o.sticky ? ' sticky-head' : '') + (o.cls ? ' ' + o.cls : '') + '"><thead><tr>';
  cols.forEach(c => {
    const cc = typeof c === 'string' ? { label: c } : c;
    h += '<th class="' + (cc.sortable === false ? '' : 'sortable-th') + (cc.cls ? ' ' + cc.cls : '') + '"' +
         (cc.align ? ' style="text-align:' + cc.align + '"' : '') + (cc.title ? ' title="' + esc(cc.title) + '"' : '') + '>' + esc(cc.label) + '</th>';
  });
  h += '</tr></thead><tbody>';
  (rows || []).forEach(r => {
    const row = Array.isArray(r) ? { cells: r } : r;
    h += '<tr' + (row._class ? ' class="' + row._class + '"' : '') + (row._href ? ' data-href="' + esc(row._href) + '"' : '') + (row._style ? ' style="' + esc(row._style) + '"' : '') + (row._attrs || '') + '>';
    row.cells.forEach((c0, i) => {
      const c = (c0 !== null && typeof c0 === 'object') ? c0 : { v: c0 };
      const col = typeof cols[i] === 'object' ? cols[i] : {};
      const align = c.align || col.align;
      const cls = [c.cls, col.cls].filter(Boolean).join(' ');
      const sortV = c.v !== undefined && c.v !== null ? c.v : (c.html !== undefined ? String(c.html).replace(/<[^>]*>/g, '') : '');
      h += '<td data-v="' + esc(sortV) + '"' + (cls ? ' class="' + cls + '"' : '') + (c.title ? ' title="' + esc(c.title) + '"' : '') +
           (align || c.style ? ' style="' + (align ? 'text-align:' + align + ';' : '') + (c.style || '') + '"' : '') + '>' +
           (c.html !== undefined ? c.html : esc(c.v === null || c.v === undefined ? '—' : c.v)) + '</td>';
    });
    h += '</tr>';
  });
  return h + '</tbody></table></div>';
}
/* Sortable headers and data-href rows for every table under el (element, id or table). */
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
          if (aN && bN) cmp = an - bn; else if (aN) cmp = -1; else if (bN) cmp = 1; else cmp = String(av).localeCompare(String(bv));
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
function lerp(a, b, t) { return a + (b - a) * t; }
/* Savant-style: blue at the bottom, grey in the middle, red at the top (p is 0-100). */
function pctColor(p) {
  if (!isNum(p)) return '#30363d';
  const t = Math.max(0, Math.min(100, p)) / 100;
  const from = t < 0.5 ? C.pctLow : C.pctMid, to = t < 0.5 ? C.pctMid : C.pctHigh;
  const u = t < 0.5 ? t * 2 : (t - 0.5) * 2;
  return 'rgb(' + Math.round(lerp(from[0], to[0], u)) + ',' + Math.round(lerp(from[1], to[1], u)) + ',' + Math.round(lerp(from[2], to[2], u)) + ')';
}
function pctPill(p) {
  if (!isNum(p)) return '<span class="pct-pill empty">—</span>';
  return '<span class="pct-pill" style="background:' + pctColor(p) + '">' + Math.round(p) + '</span>';
}
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
function statTile(label, value, sub, cls) {
  return '<div class="kpi' + (cls ? ' ' + cls : '') + '"><div class="kpi-label">' + esc(label) + '</div>' +
    '<div class="kpi-value">' + (value === undefined || value === null ? '—' : value) + '</div>' + (sub ? '<div class="kpi-sub">' + sub + '</div>' : '') + '</div>';
}
/* A probability with an inline bar (0-1); colour optional; max scales the bar. */
function probCell(p, colour, max) {
  if (!isNum(p)) return '<span class="muted-inline">—</span>';
  const w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="pcell"><span class="pcell-bar"><span style="width:' + w.toFixed(1) + '%;background:' + (colour || C.accent) + '"></span></span><span class="pcell-v">' + pct(p) + '</span></span>';
}
/* Model minus market in percentage points: a signed number in a neutral colour. A gap is a disagreement,
 * not value (the model trails the closing line in the backtest), so it is never coloured good or bad. */
function edgeHTML(model, market, d) {
  if (!isNum(model) || !isNum(market)) return '<span class="muted-inline">—</span>';
  const e = (model - market) * 100;
  return '<span class="gap-v">' + signed(e, d === undefined ? 1 : d) + '</span>';
}
const gapHTML = edgeHTML;
/* A model-minus-line difference in points (spreads, totals): signed, neutral colour. */
function gapPts(v, d) {
  if (!isNum(v)) return '<span class="muted-inline">—</span>';
  return '<span class="gap-v">' + signed(v, d === undefined ? 1 : d) + '</span>';
}
/* A difference in points (lines, totals), coloured: green when positive. */
function ptsEdge(v, d) {
  if (!isNum(v)) return '<span class="muted-inline">—</span>';
  return '<span class="' + (v > 0.05 ? 'edge-pos' : v < -0.05 ? 'edge-neg' : 'muted-inline') + '">' + signed(v, d === undefined ? 1 : d) + '</span>';
}
/* A two-sided probability bar: share a in colour a, the rest in colour b; opts {market, colours:[a,b]}. */
function splitBar(p, opts) {
  const o = opts || {};
  if (!isNum(p)) return '<div class="split-bar empty"></div>';
  const w = Math.max(0, Math.min(1, p)) * 100;
  const ca = o.colours ? o.colours[0] : null, cb = o.colours ? o.colours[1] : null;
  return '<div class="split-bar"><span class="sb-a" style="width:' + w.toFixed(1) + '%' + (ca ? ';background:' + ca : '') + '"></span><span class="sb-b" style="width:' + (100 - w).toFixed(1) + '%' + (cb ? ';background:' + cb : '') + '"></span>' +
    (isNum(o.market) ? '<i class="sb-mk" style="left:' + (Math.max(0, Math.min(1, o.market)) * 100).toFixed(1) + '%" title="Market ' + pct(o.market) + '"></i>' : '') + '</div>';
}
function divColour(v, max, invert) {
  if (!isNum(v) || !max) return 'transparent';
  let t = Math.max(-1, Math.min(1, v / max));
  if (invert) t = -t;
  const a = Math.abs(t);
  return t < 0 ? 'rgba(88,166,255,' + (0.12 + 0.6 * a).toFixed(3) + ')' : 'rgba(248,81,73,' + (0.12 + 0.6 * a).toFixed(3) + ')';
}
/* Sequential colour for t in [0,1] (the leather accent). */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'rgba(200,131,74,' + (0.05 + 0.75 * u).toFixed(3) + ')';
}
function toggles(items, active, attr) {
  const a = attr || 'data-k';
  return items.map(it => '<button type="button" class="tbtn' + (String(it.key) === String(active) ? ' active' : '') + '" ' + a + '="' + esc(it.key) + '">' + esc(it.label) + '</button>').join('');
}
function wireToggles(root, attr, fn) {
  if (!root) return;
  const a = attr || 'data-k';
  root.querySelectorAll('[' + a + ']').forEach(b => b.addEventListener('click', () => {
    root.querySelectorAll('[' + a + ']').forEach(x => x.classList.toggle('active', x === b));
    fn(b.getAttribute(a));
  }));
}
function pageHead(title, sub, right) {
  return '<div class="page-head"><div><h2>' + esc(title) + '</h2>' + (sub ? '<div class="ph-sub muted-inline">' + sub + '</div>' : '') + '</div>' +
    (right ? '<div class="ph-nav">' + right + '</div>' : '') + '</div>';
}
/* Previous / next week links for a season: [prevHtml, nextHtml]. */
function weekNav(S, w, hrefFn) {
  const f = hrefFn || weekHref;
  const max = regWeeks(S) + 4;
  const prev = w > 1 ? '<a href="' + f(S, w - 1) + '">← ' + esc(weekLabel(w - 1, S)) + '</a>' : '<span class="disabled">←</span>';
  const next = w < max ? '<a href="' + f(S, w + 1) + '">' + esc(weekLabel(w + 1, S)) + ' →</a>' : '<span class="disabled">→</span>';
  return prev + next;
}

// ── charts ─────────────────────────────────────────────────────────────────

function deepCopy(o) { return JSON.parse(JSON.stringify(o)); }
function layout(extra) {
  const base = deepCopy(DARK_LAYOUT);
  const out = Object.assign(base, extra || {});
  Object.keys(extra || {}).forEach(k => {
    if (/^[xy]axis\d*$/.test(k) && extra[k] && typeof extra[k] === 'object') out[k] = Object.assign({}, DARK_LAYOUT.xaxis, extra[k]);
  });
  if (extra && extra.font) out.font = Object.assign({}, DARK_LAYOUT.font, extra.font);
  return out;
}
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

// ── header: season and week pickers, nav, meta, search ─────────────────────

/* Change the season shown, keeping the page where it makes sense. */
function setSeason(S0) {
  const S = parseInt(S0, 10);
  if (isNaN(S)) return;
  const r = state.route || 'hub';
  const cur = currentSeason();
  if (r === 'week' || r === 'game') { go(weekHref(S, S === cur ? currentWeek() : Math.min(state.week || 1, regWeeks(S) + 4))); return; }
  if (r === 'standings') { go(standingsHref(S)); return; }
  if (r === 'playoffs') { go(playoffsHref(S)); return; }
  if (r === 'hub' && S !== cur) { go(weekHref(S, 1)); return; }
  const h = String(location.hash || '#/').replace(/\?.*$/, '');
  const q = Object.assign({}, state.params.query || {});
  delete q.y; delete q.season;
  if (S === cur) delete q.s; else q.s = String(S);
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  go((h === '#' ? '#/' : h) + (qs ? '?' + qs : ''));
}
/* Show a week: always the week page. */
function setWeek(w) {
  const n = parseInt(w, 10);
  if (isNaN(n)) return;
  go(weekHref(state.season || currentSeason(), n));
}
function fillPickers() {
  const sel = document.getElementById('season-select');
  if (sel) {
    const list = seasons();
    if (state.season && list.indexOf(state.season) < 0) list.unshift(state.season);
    const html = list.map(y => '<option value="' + y + '">' + y + '</option>').join('');
    if (sel.dataset.filled !== html.length + ':' + list[0]) { sel.innerHTML = html; sel.dataset.filled = html.length + ':' + list[0]; }
    sel.value = String(state.season || currentSeason());
  }
  const ws = document.getElementById('week-select');
  if (ws) {
    const S = state.season || currentSeason();
    const key = String(S);
    if (ws.dataset.season !== key) {
      ws.innerHTML = weeksOf(S).map(x => '<option value="' + x.w + '">' + esc(x.label) + '</option>').join('');
      ws.dataset.season = key;
    }
    ws.value = String(state.week || 1);
    const wp = ws.closest('.week-picker');
    if (wp) wp.classList.toggle('on', state.route === 'week' || state.route === 'game');
  }
}
function updateHeader() {
  const S = state.season;
  const links = { hub: '#/', week: weekHref(S, S === currentSeason() ? currentWeek() : state.week), standings: standingsHref(S), playoffs: playoffsHref(S),
    teams: ghref('teams', S), players: ghref('players', S), fourth: ghref('fourth-downs', S), coaches: ghref('coaches', S), leaders: ghref('leaders', S),
    history: '#/history', lab: ghref('lab', S), compare: '#/compare', markets: '#/markets', calibration: '#/calibration', glossary: '#/glossary',
    methodology: '#/methodology', value: ghref('value', S), trade: '#/trade' };
  document.querySelectorAll('.global-nav a[data-nav]').forEach(a => { if (links[a.dataset.nav]) a.setAttribute('href', links[a.dataset.nav]); });
}
function markNav(key) {
  document.querySelectorAll('.global-nav a[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === key));
}
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const S = state.season || currentSeason();
  const base = ['NFL ' + S + (S === currentSeason() && d && isNum(d.week) ? ' · ' + weekLabel(d.week, S) : ''),
    d && d.updated_at ? 'Updated ' + esc(fmtStamp(d.updated_at)) : ''].filter(Boolean).join(' · ');
  el.innerHTML = [html, base].filter(Boolean).join(' · ');
}

function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
let SEARCH = null;
function loadSearch() {
  if (SEARCH) return SEARCH;
  SEARCH = ensureNames().then(() => {
    const items = [];
    const cur = currentSeason();
    Object.keys(TEAMS).forEach(t => {
      const x = TEAMS[t];
      if (!x.name || t === 'OAK' || t === 'SD' || t === 'STL') return;
      items.push({ kind: 'Teams', id: t, label: x.name, sub: [t, x.division].filter(Boolean).join(' · '), href: teamHref(t, cur), colour: teamColour(t),
        order: 0, norm: norm(x.name + ' ' + t + ' ' + (x.short || '') + ' ' + (x.city || '')) });
    });
    Object.keys(NAMES).forEach(pid => {
      const x = NAMES[pid] || {};
      if (!x.name) return;
      const last = isNum(x.last) ? Number(x.last) : 0;
      items.push({ kind: 'Players', id: pid, label: x.name,
        sub: [x.pos, x.team ? teamAbbr(x.team) : '', isNum(x.first) ? (Number(x.first) === last ? String(last) : x.first + '–' + (last >= cur ? '' : last)) : ''].filter(Boolean).join(' · '),
        href: playerHref(pid), order: cur - last, norm: norm(x.name + ' ' + (x.short || '')) });
    });
    items.sort((a, b) => a.order - b.order);
    return items;
  });
  return SEARCH;
}
function closeSearch() {
  const box = document.getElementById('search-results');
  if (box) { box.innerHTML = ''; box.style.display = 'none'; }
}
function runSearch(q) {
  const box = document.getElementById('search-results');
  const n = norm(q.trim());
  if (n.length < 2 || !box) { closeSearch(); return; }
  loadSearch().then(items => {
    const words = n.split(/\s+/).filter(Boolean);
    const hits = items.filter(it => words.every(w => it.norm.indexOf(w) >= 0));
    // names with a word starting with the query first, then the most recent
    hits.sort((a, b) => {
      const sa = a.norm.split(' ').some(w => w.indexOf(words[0]) === 0) ? 0 : 1, sb = b.norm.split(' ').some(w => w.indexOf(words[0]) === 0) ? 0 : 1;
      return sa - sb || a.order - b.order;
    });
    let html = '';
    ['Teams', 'Players'].forEach(g => {
      const list = hits.filter(h => h.kind === g).slice(0, g === 'Players' ? 10 : 4);
      if (!list.length) return;
      html += '<div class="sr-head">' + g + '</div>' + list.map(h =>
        '<a class="sr-item" href="' + esc(h.href) + '">' + (h.colour ? '<span class="team-bar" style="background:' + h.colour + '"></span>' : '') + '<span>' + esc(h.label) + '</span><span class="sr-sub">' + esc(h.sub || '') + '</span></a>').join('');
    });
    box.innerHTML = html || '<div class="sr-empty">No player or team matches.</div>';
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
function initHeader() {
  const sel = document.getElementById('season-select');
  if (sel) sel.addEventListener('change', () => setSeason(sel.value));
  const ws = document.getElementById('week-select');
  if (ws) ws.addEventListener('change', () => setWeek(ws.value));
}
function init() {
  load('index.json').then(idx => {
    INDEX.data = idx;
    initHeader();
    initSearch();
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
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES, SITE: SITE, FIRST_SEASON: FIRST_SEASON,
  setSeason: setSeason, setWeek: setWeek, setMeta: setMeta,
  // data
  load: load, loadAll: loadAll, uncache: uncache, refreshIndex: refreshIndex, liveRefresh: liveRefresh, ok: ok, reason: reason, cached: cached,
  ypath: ypath, loadYear: loadYear, weekPath: weekPath, loadWeek: loadWeek, gamePath: gamePath, loadGame: loadGame, playerPath: playerPath, loadPlayer: loadPlayer,
  ensureNames: ensureNames, playersOf: playersOf, putTeam: putTeam,
  index: () => INDEX.data, currentSeason: currentSeason, currentWeek: currentWeek, seasons: seasons, phase: phase,
  NAMES: NAMES, TEAMS: TEAMS, NFL_TEAMS: NFL_TEAMS, DIVISIONS: DIVISIONS, CONFERENCES: CONFERENCES, DRIVE_RESULTS: DRIVE_RESULTS,
  // formatting
  esc: esc, num: num, int: int, pct: pct, signed: signed, pp: pp, fmtDate: fmtDate, fmtTime: fmtTime, fmtStamp: fmtStamp, localDay: localDay,
  todayISO: todayISO, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal, metric: metric, record: record, american: american, decimal: decimal,
  fmtOdds: fmtOdds, amToProb: amToProb, devigAm: devigAm, devig2: devig2, fmtLine: fmtLine, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  // football
  regWeeks: regWeeks, weekNum: weekNum, weekType: weekType, weekLabel: weekLabel, weeksOf: weeksOf, gtypeLabel: gtypeLabel,
  parseGameId: parseGameId, gameSeason: gameSeason, gameWeek: gameWeek, downText: downText, downDist: downDist, fieldPos: fieldPos,
  fmtClock: fmtClock, qtrLabel: qtrLabel, clockText: clockText, otherTeam: otherTeam, driveResult: driveResult, gradeOf: gradeOf, choiceLabel: choiceLabel,
  gameState: gameState, isFinal: isFinal, isLive: isLive, isPre: isPre, isOT: isOT, statusChip: statusChip, homeLine: homeLine, spreadText: spreadText,
  qbText: qbText, surnameOf: surnameOf, weatherText: weatherText, gameCard: gameCard, titleProbs: titleProbs,
  // names and links
  player: player, playerInfo: playerInfo, playerName: playerName, playerShort: playerShort, playerSurname: playerSurname, playerColour: playerColour,
  playerLink: playerLink, playerHref: playerHref, canonTeam: canonTeam,
  teamInfo: teamInfo, teamName: teamName, teamShort: teamShort, teamAbbr: teamAbbr, teamColour: teamColour, teamColourRaw: teamColourRaw, teamAlt: teamAlt,
  teamBar: teamBar, teamHref: teamHref, teamLink: teamLink, gameHref: gameHref, gameLink: gameLink, matchupLink: matchupLink,
  coachHref: coachHref, coachLink: coachLink, weekHref: weekHref, weekLink: weekLink, standingsHref: standingsHref, playoffsHref: playoffsHref,
  compareHref: compareHref, glossHref: glossHref, href: href, ghref: ghref, sq: sq,
  // HTML
  card: card, muted: muted, chip: chip, pill: pill, gradePill: gradePill, notBuilt: notBuilt, tableHTML: tableHTML, sortable: sortable,
  pctPill: pctPill, pctColor: pctColor, pctRow: pctRow, statTile: statTile, tile: statTile, probCell: probCell, edgeHTML: edgeHTML, gapHTML: gapHTML, gapPts: gapPts, ptsEdge: ptsEdge,
  splitBar: splitBar, divColour: divColour, seqColour: seqColour, toggles: toggles, wireToggles: wireToggles, pageHead: pageHead, weekNav: weekNav,
  // charts
  plot: plot, layout: layout, PALETTE: PALETTE, C: C, DARK_LAYOUT: DARK_LAYOUT, PLOTLY_CONF: PLOTLY_CONF,
  FOOTBALL_URL: FOOTBALL_URL, PADDOCK_URL: PADDOCK_URL, HARDWOOD_URL: HARDWOOD_URL, ACE_URL: ACE_URL, BULLPEN_URL: BULLPEN_URL, RINK_URL: RINK_URL,
  charts: {}
};
})();
