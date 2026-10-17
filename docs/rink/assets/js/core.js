/* The Quant Rink — core: namespace, state, routing, cached loading, helpers, search.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/nhl/PAYLOADS.md). Every page module
 * registers itself with RK.route(name, renderFn) and never edits this file. Routes (hash):
 *
 *   #/                                  hub
 *   #/games  #/games/<YYYY-MM-DD>       a day of games (default: today, else the nearest day with games)
 *   #/game/<game_id>                    game centre (NHL gameId 2026020009; the season is its first four digits)
 *   #/standings[/<S>]  #/playoffs[/<S>] standings and playoff race, the bracket (S = 20262027)
 *   #/teams  #/team/<abbr>              teams
 *   #/skaters  #/goalies  #/player/<pid>  #/lines  #/leaders  #/history  #/lab  #/compare[/<a>[/<b>]]
 *   #/markets  #/calibration  #/glossary[/<key>]  #/methodology  #/disclaimer
 *   #/value  #/trade                    player value (GAR, WAR) and the trade simulator (state in ?t=&m=)
 *   #/value?tab=val  #/moves  #/fantasy  multi-season valuation, transactions and trade grades, fantasy
 *
 * Season: every page reads RK.state.season (an 8-digit NHL season id, a Number: 20262027). It comes
 * from the route (#/standings/<S>, #/playoffs/<S>), the game id (#/game/<id>), else a "?s=<S>" query
 * (any page; "?s=2026" and "?s=2026-27" are accepted too), else index.json "season". Links built with
 * the helpers below carry ?s= when the season shown is not the current one. RK.state.date is the day of
 * the games page (route, else "?d=", else null).
 *
 * Before a page renders, core loads players_index.json ({pid: [name, team, pos, first_season, last_season]}),
 * so RK.playerName / RK.playerLink work synchronously. Team names and colours come from index.json "teams"
 * (and any payload carrying a "teams" dict keyed by tri-code), with a built-in table of the 32 clubs (plus
 * ARI, PHX, ATL) as the fallback.
 *
 * A render function is called as fn(el, params, state): `el` is a fresh <div> inside <main id="app">
 * (detached when the viewer navigates away, so async code can test el.isConnected); `params` holds
 * {season, date, id, a, b, S, rest, query}. It may return a Promise.
 *
 * Puck line convention (PAYLOADS.md): every puck line is the HOME team's line, negative when home is
 * favoured (-1.5 = home favoured). Times: `sec` is elapsed game seconds (0 at the opening face-off,
 * 1200 per regulation period); `clock` is the time remaining in the period ("12:34" or seconds).
 */
window.RK = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

const C = {
  bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d',
  text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316',
  purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8',
  ice: '#5cc6f2', ice2: '#2f8fc4', iceDeep: '#0e2638', iceSheet: '#dcecf5', goal: '#e5484d', goal2: '#b8262c', crease: '#4a90d9',
  rk: '#5cc6f2', accent: '#5cc6f2', p1: '#5cc6f2', p2: '#ef6a6e', home: '#5cc6f2', away: '#ef6a6e',
  espn: '#8b949e', market: '#e6edf3',
  good: '#3fb950', close: '#d29922', bad: '#f85149',
  pctLow: [50, 105, 220], pctMid: [128, 128, 128], pctHigh: [214, 40, 40]
};
const PALETTE = ['#5cc6f2', '#ef6a6e', '#3fb950', '#bc8cff', '#d29922', '#39d0d8', '#f97316', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
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
const GRIDIRON_URL = 'https://pchattani.github.io/the-quant-gridiron/';
const SITE = 'The Quant Rink';
const FIRST_SEASON = 20092010;          // the first season with per-season payloads (career data 2009-10 on)
const MONEYPUCK_CREDIT = 'xG benchmark data from MoneyPuck.com';

/* NHL tri-codes -> [name, short (nickname), conference, division, colour, alt]. Colours: club primary and
 * secondary. Relocated franchises keep their old codes for old seasons. */
const NHL_TEAMS = {
  ANA: ['Anaheim Ducks', 'Ducks', 'Western', 'Pacific', '#fc4c02', '#b9975b'],
  BOS: ['Boston Bruins', 'Bruins', 'Eastern', 'Atlantic', '#000000', '#ffb81c'],
  BUF: ['Buffalo Sabres', 'Sabres', 'Eastern', 'Atlantic', '#003087', '#ffb81c'],
  CGY: ['Calgary Flames', 'Flames', 'Western', 'Pacific', '#c8102e', '#f1be48'],
  CAR: ['Carolina Hurricanes', 'Hurricanes', 'Eastern', 'Metropolitan', '#ce1126', '#a2aaad'],
  CHI: ['Chicago Blackhawks', 'Blackhawks', 'Western', 'Central', '#cf0a2c', '#ff671b'],
  COL: ['Colorado Avalanche', 'Avalanche', 'Western', 'Central', '#6f263d', '#236192'],
  CBJ: ['Columbus Blue Jackets', 'Blue Jackets', 'Eastern', 'Metropolitan', '#002654', '#ce1126'],
  DAL: ['Dallas Stars', 'Stars', 'Western', 'Central', '#006847', '#8f8f8c'],
  DET: ['Detroit Red Wings', 'Red Wings', 'Eastern', 'Atlantic', '#ce1126', '#ffffff'],
  EDM: ['Edmonton Oilers', 'Oilers', 'Western', 'Pacific', '#041e42', '#ff4c00'],
  FLA: ['Florida Panthers', 'Panthers', 'Eastern', 'Atlantic', '#c8102e', '#b9975b'],
  LAK: ['Los Angeles Kings', 'Kings', 'Western', 'Pacific', '#111111', '#a2aaad'],
  MIN: ['Minnesota Wild', 'Wild', 'Western', 'Central', '#154734', '#a6192e'],
  MTL: ['Montréal Canadiens', 'Canadiens', 'Eastern', 'Atlantic', '#af1e2d', '#192168'],
  NSH: ['Nashville Predators', 'Predators', 'Western', 'Central', '#ffb81c', '#041e42'],
  NJD: ['New Jersey Devils', 'Devils', 'Eastern', 'Metropolitan', '#ce1126', '#000000'],
  NYI: ['New York Islanders', 'Islanders', 'Eastern', 'Metropolitan', '#00539b', '#f47d30'],
  NYR: ['New York Rangers', 'Rangers', 'Eastern', 'Metropolitan', '#0038a8', '#ce1126'],
  OTT: ['Ottawa Senators', 'Senators', 'Eastern', 'Atlantic', '#da1a32', '#b79257'],
  PHI: ['Philadelphia Flyers', 'Flyers', 'Eastern', 'Metropolitan', '#f74902', '#000000'],
  PIT: ['Pittsburgh Penguins', 'Penguins', 'Eastern', 'Metropolitan', '#000000', '#fcb514'],
  SJS: ['San Jose Sharks', 'Sharks', 'Western', 'Pacific', '#006d75', '#ea7200'],
  SEA: ['Seattle Kraken', 'Kraken', 'Western', 'Pacific', '#001628', '#99d9d9'],
  STL: ['St. Louis Blues', 'Blues', 'Western', 'Central', '#002f87', '#fcb514'],
  TBL: ['Tampa Bay Lightning', 'Lightning', 'Eastern', 'Atlantic', '#002868', '#ffffff'],
  TOR: ['Toronto Maple Leafs', 'Maple Leafs', 'Eastern', 'Atlantic', '#00205b', '#ffffff'],
  UTA: ['Utah Mammoth', 'Mammoth', 'Western', 'Central', '#6cace4', '#010101'],
  VAN: ['Vancouver Canucks', 'Canucks', 'Western', 'Pacific', '#00205b', '#00843d'],
  VGK: ['Vegas Golden Knights', 'Golden Knights', 'Western', 'Pacific', '#b4975a', '#333f42'],
  WSH: ['Washington Capitals', 'Capitals', 'Eastern', 'Metropolitan', '#041e42', '#c8102e'],
  WPG: ['Winnipeg Jets', 'Jets', 'Western', 'Central', '#041e42', '#ac162c'],
  ARI: ['Arizona Coyotes', 'Coyotes', 'Western', 'Central', '#8c2633', '#e2d6b5'],
  PHX: ['Phoenix Coyotes', 'Coyotes', 'Western', 'Pacific', '#8c2633', '#e2d6b5'],
  ATL: ['Atlanta Thrashers', 'Thrashers', 'Eastern', 'Southeast', '#041e42', '#5c88da']
};
const HISTORIC = ['ARI', 'PHX', 'ATL'];
const TEAM_ALIASES = { 'L.A': 'LAK', LA: 'LAK', 'N.J': 'NJD', NJ: 'NJD', 'S.J': 'SJS', SJ: 'SJS', 'T.B': 'TBL', TB: 'TBL', WAS: 'WSH', MON: 'MTL',
  UTAH: 'UTA', CLB: 'CBJ', NAS: 'NSH', VEG: 'VGK', LV: 'VGK', CAL: 'CGY', WIN: 'WPG', ANH: 'ANA', 'NY RANGERS': 'NYR', 'NY ISLANDERS': 'NYI' };
const DIVISIONS = ['Atlantic', 'Metropolitan', 'Central', 'Pacific'];
const CONFERENCES = ['Eastern', 'Western'];
const DIV_CONF = { Atlantic: 'Eastern', Metropolitan: 'Eastern', Central: 'Western', Pacific: 'Western', Southeast: 'Eastern', Northeast: 'Eastern', Northwest: 'Western' };
const GTYPE_LONG = { '01': 'Preseason', '02': 'Regular season', '03': 'Playoffs', '04': 'All-Star' };
const GTYPE_SHORT = { '01': 'Pre', '02': 'Reg', '03': 'PO', '04': 'ASG' };
const ROUND_NAMES = { 1: 'First round', 2: 'Second round', 3: 'Conference final', 4: 'Stanley Cup Final' };
/* Strength groups for filters: [key, label]. */
const STRENGTHS = [['all', 'All'], ['5v5', '5v5'], ['PP', 'Power play'], ['PK', 'Shorthanded'], ['EN', 'Empty net'], ['other', 'Other']];
const SHOT_TYPES = { goal: 'Goal', 'shot-on-goal': 'Shot on goal', sog: 'Shot on goal', shot: 'Shot on goal', 'missed-shot': 'Missed', miss: 'Missed', 'blocked-shot': 'Blocked', block: 'Blocked' };

// ── state and registries ───────────────────────────────────────────────────

const state = { season: null, date: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = {};      // pid -> {name, team, pos, first, last}
const TEAMS = {};      // abbr -> {abbr, name, short, conference, division, colour, alt}
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];

Object.keys(NHL_TEAMS).forEach(t => {
  const r = NHL_TEAMS[t];
  TEAMS[t] = { abbr: t, name: r[0], short: r[1], conference: r[2], division: r[3], colour: r[4], alt: r[5] };
});

const ROUTES = [];
function addRoute(pattern, name, opts) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, seasonal: !!(opts && opts.seasonal) });
}
addRoute('', 'hub');
addRoute('games', 'games');
addRoute('games/:date', 'games');
addRoute('game/:id', 'game');
addRoute('standings', 'standings');
addRoute('standings/:S', 'standings', { seasonal: true });
addRoute('teams', 'teams');
addRoute('team/:id', 'team');
addRoute('players', 'players');
addRoute('player/:id', 'player');
addRoute('value', 'value');
addRoute('fantasy', 'fantasy');
addRoute('lab', 'lab');
addRoute('compare', 'compare');
addRoute('compare/:a', 'compare');
addRoute('compare/:a/:b', 'compare');
addRoute('model', 'model');
addRoute('glossary', 'glossary');
addRoute('glossary/:id', 'glossary');
addRoute('methodology', 'methodology');
addRoute('disclaimer', 'disclaimer');

const ALIASES = { home: 'hub', index: 'hub', '': 'hub' };
const ALIAS_SEGS = { schedule: 'games', scores: 'games', scoreboard: 'games' };
/* Old routes (before the October 2026 redesign) -> [section route, tab]. A one-segment hash (plus its query) is
 * replaced; '#/playoffs/<S>' keeps its season. Deep links with an id (#/glossary/<key>, #/methodology/<part>,
 * #/compare/<a>/<b>) still render where they are, inside their section. */
const REDIRECTS = {
  skaters: ['players', 'skaters'], goalies: ['players', 'goalies'], leaders: ['players', 'leaders'], leaderboards: ['players', 'leaders'],
  lines: ['players', 'lines'], awards: ['players', 'awards'],
  playoffs: ['standings', 'bracket'], bracket: ['standings', 'bracket'], postseason: ['standings', 'bracket'],
  markets: ['standings', 'markets'], history: ['standings', 'history'],
  trade: ['value', 'trade'], moves: ['value', 'moves'], valuation: ['value', 'val'],
  calibration: ['model', 'calibration'], docs: ['model', 'methodology'], hub: ['', null]
};
function redirectFor(hash) {
  let h = String(hash || '').replace(/^#\/?/, '');
  let q = '';
  const qi = h.indexOf('?');
  if (qi >= 0) { q = h.slice(qi + 1); h = h.slice(0, qi); }
  const parts = h.split('/').filter(x => x !== '');
  if (!parts.length) return null;
  let to = REDIRECTS[parts[0]];
  if (!to && (parts[0] === 'glossary' || parts[0] === 'methodology') && parts.length === 1) to = ['model', parts[0]];
  if (!to) return null;
  const extra = [];
  if (parts.length > 1) {
    if ((parts[0] === 'playoffs' || parts[0] === 'bracket' || parts[0] === 'postseason') && parts.length === 2 && toSeason(parts[1])) extra.push('s=' + toSeason(parts[1]));
    else return null;
  }
  const query = q.split('&').filter(Boolean).filter(kv => !(to[1] && /^tab=/.test(kv) && to[0] !== 'value'));
  if (to[1] && !(to[0] === 'value' && query.some(kv => /^tab=/.test(kv)))) query.unshift('tab=' + to[1]);
  const all = query.concat(extra);
  return '#/' + to[0] + (all.length ? '?' + all.join('&') : '');
}
const TITLES = {
  hub: 'Overview', games: 'Games', game: 'Game centre', standings: 'Standings', teams: 'Teams', team: 'Team', players: 'Players', player: 'Player',
  value: 'Value & Moves', fantasy: 'Fantasy', lab: 'Lab', compare: 'Compare', model: 'Model', glossary: 'Glossary', methodology: 'Methodology', disclaimer: 'Disclaimer & terms'
};
/* Which kit section each route belongs to (QK.SECTIONS keys). */
const SECTION_OF = { hub: 'overview', games: 'fixtures', game: 'fixtures', standings: 'standings', teams: 'teams', team: 'teams',
  players: 'players', player: 'players', value: 'value', fantasy: 'fantasy', lab: 'lab', compare: 'lab',
  model: 'model', glossary: 'model', methodology: 'model', disclaimer: 'model' };
const NAV_OF = SECTION_OF;
/* Names the redesigned pages own: a legacy module's RK.route(name) registers a view (RK.view(name)) that a section
 * page renders inside its tabs, not the route itself. */
const OWNED = { hub: 1, games: 1, game: 1, standings: 1, teams: 1, team: 1, players: 1, player: 1, value: 1, fantasy: 1, lab: 1, compare: 1,
  model: 1, glossary: 1, methodology: 1 };
const VIEWS = {};

function normPattern(s) {
  return String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
}
function shape(p) { return p.split('/').map(s => (s.charAt(0) === ':' ? ':' : s)).join('/'); }

/* Register a page renderer: a route name ('game'), an alias ('schedule'), or a pattern ('#/game/<id>'). */
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
  VIEWS[key] = fn;
  if (OWNED[key]) return;
  HANDLERS[key] = fn;
  if (state.route === key && booted) render();
}
/* Register a redesigned page (owns its route). */
function page(name, fn) {
  if (typeof fn !== 'function') return;
  HANDLERS[name] = fn;
  if (state.route === name && booted) render();
}
function view(name) { return VIEWS[name] || null; }
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

const DATE_RE = /^\d{4}-\d\d-\d\d$/;
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
    // a seasonal segment must look like a season, a date segment like a date
    for (let i = 0; i < r.segs.length; i++) {
      if (r.segs[i] === ':S' && toSeason(parts[i]) === null) return;
      if (r.segs[i] === ':date' && !DATE_RE.test(parts[i])) return;
    }
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts };
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  let S = params.S ? toSeason(params.S) : null;
  if (S === null) { const q = query.s || query.season || query.y; S = q ? toSeason(q) : null; }
  if (S === null && best.name === 'game' && params.id) S = gameSeason(params.id);
  if (S === null && params.date) S = seasonOfDate(params.date);
  params.season = S === null ? undefined : S;
  if (!params.date && query.d && DATE_RE.test(query.d)) params.date = query.d;
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
  const rd = redirectFor(location.hash);
  if (rd) { try { location.replace(rd); } catch (e) { location.hash = rd; } return; }
  runCleanups();
  closeSearch();
  const r = parseHash();
  const S = r.params.season || currentSeason();
  r.params.season = S;
  state.season = S;
  state.date = r.params.date || null;
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
  document.title = (r.name === 'hub' ? 'NHL odds, models and analytics · ' : (TITLES[r.name] || 'Page') + ' · ') + SITE;
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
  el.innerHTML = window.QK ? QK.skeleton('lines', 6) : '<div class="muted">Loading…</div>';
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
 * broken. A payload written with "ok": false resolves as written: test with RK.ok(d). */
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
/* Per-season payload path: ypath('season.json') -> '20262027/season.json'. */
function ypath(file, S) { return (toSeason(S) || state.season || currentSeason()) + '/' + file; }
function loadYear(file, S) { return load(ypath(file, S)); }
function gamePath(id) { return ypath('games/' + id + '.json', gameSeason(id)); }
/* A game payload (its season is the first four digits of the gameId). */
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

function canonTeam(t) { const s = String(t || '').toUpperCase().trim(); return TEAM_ALIASES[s] || s; }
function putTeam(abbr0, x) {
  const abbr = canonTeam(abbr0);
  if (!abbr || !x || typeof x !== 'object' || !/^[A-Z]{2,3}$/.test(abbr)) return;
  const cur = TEAMS[abbr] || { abbr: abbr };
  const o = {};
  ['name', 'short', 'nickname', 'conference', 'division', 'colour', 'alt', 'city', 'arena'].forEach(k => { if (x[k] !== undefined && x[k] !== null && x[k] !== '') o[k] = x[k]; });
  if (x.color && !o.colour) o.colour = x.color;
  if (x.colour2 && !o.alt) o.alt = x.colour2;
  if (x.nickname && !o.short) o.short = x.nickname;
  if (x.conf && !o.conference) o.conference = x.conf;
  if (o.conference) o.conference = confName(o.conference);
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
/* addDays('2026-10-07', -1) -> '2026-10-06'. */
function addDays(iso, n) {
  const d = parseDate(iso);
  if (!d) return iso;
  const x = new Date(d.getTime() + n * 86400000);
  return x.getUTCFullYear() + '-' + String(x.getUTCMonth() + 1).padStart(2, '0') + '-' + String(x.getUTCDate()).padStart(2, '0');
}
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
/* Format a catalogue value by its METRIC fmt: int|0|1|2|3|pct|prob|signed|signed1|pm|rate|toi|toi_min|sec|plus|svpct.
 * pct and prob are fractions 0-1; rate is per 60 (2 dp); toi is seconds ("18:42"); toi_min minutes; svpct ".915". */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt)) {
    case 'pct': return (x * 100).toFixed(1) + '%';
    case 'prob': return pct(x);
    case 'int': case 'plus': return int(x);
    case 'pm': case 'signed1': return signed(x, 1);
    case 'signed': return signed(x, 2);
    case 'signed3': return signed(x, 3);
    case 'rate': case '2': return x.toFixed(2);
    case 'toi': return fmtTOI(x);
    case 'toi_min': return fmtTOI(x * 60);
    case 'svpct': return x >= 1 ? x.toFixed(3) : x.toFixed(3).replace(/^0/, '');
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '3': return x.toFixed(3);
    case 'sec': return x.toFixed(2) + 's';
    case 'mph': return x.toFixed(1) + ' mph';
    case 'ft': return x.toFixed(1) + ' ft';
    default: return x.toFixed(2);
  }
}
function metric(list, key) { return (list || []).find(m => m && m.key === key) || null; }
/* W-L-OTL: record(10, 4, 2) -> "10-4-2" (OTL shown when given, even 0). */
function record(w, l, otl) {
  if (!isNum(w) || !isNum(l)) return '—';
  return Math.round(w) + '-' + Math.round(l) + (isNum(otl) ? '-' + Math.round(otl) : '');
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
/* A line number: -1.5 -> "-1.5", 1.5 -> "+1.5", 0 -> "PK". */
function fmtLine(v) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  if (x === 0) return 'PK';
  return (x > 0 ? '+' : '') + (Number.isInteger(x) ? String(x) : x.toFixed(1));
}
function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

// ── seasons ────────────────────────────────────────────────────────────────

/* Any season spelling -> the 8-digit id (Number) or null: 20262027, '20262027', 2026, '2026-27', '2026/27'. */
function toSeason(x) {
  if (x === null || x === undefined || x === '') return null;
  const s = String(x).trim();
  let m = /^(\d{4})(\d{4})$/.exec(s);
  if (m && Number(m[2]) === Number(m[1]) + 1) return Number(s);
  m = /^(\d{4})[-/](\d{2}|\d{4})$/.exec(s);
  if (m) return Number(m[1]) * 10000 + Number(m[1]) + 1;
  m = /^(\d{4})$/.exec(s);
  if (m && Number(m[1]) >= 1917 && Number(m[1]) <= 2100) return Number(m[1]) * 10000 + Number(m[1]) + 1;
  return null;
}
/* 20262027 -> "2026-27"; short -> "26-27". */
function seasonLabel(S, short) {
  const s = toSeason(S);
  if (!s) return S ? String(S) : '—';
  const a = Math.floor(s / 10000), b = s % 10000;
  return short ? String(a).slice(2) + '-' + String(b).slice(2) : a + '-' + String(b).slice(2);
}
function seasonStart(S) { const s = toSeason(S); return s ? Math.floor(s / 10000) : null; }
function seasonEnd(S) { const s = toSeason(S); return s ? s % 10000 : null; }
/* The season a calendar date falls in (September on = the new season). */
function seasonOfDate(iso) {
  const d = parseDate(iso);
  if (!d) return null;
  const y = d.getUTCFullYear(), m = d.getUTCMonth();
  const a = m >= 8 ? y : y - 1;
  return a * 10000 + a + 1;
}
/* Regular-season games per team: 84 from 2026-27, 82 before; 48 in 2012-13, 56 in 2020-21. */
function regGames(S) {
  const s = toSeason(S) || currentSeason();
  if (s === 20122013) return 48;
  if (s === 20202021) return 56;
  return s >= 20262027 ? 84 : 82;
}
function currentSeason() {
  const d = INDEX.data;
  const s = d ? toSeason(d.season) : null;
  if (s) return s;
  return seasonOfDate(new Date().toISOString()) || 20262027;
}
function seasons() {
  const d = INDEX.data || {};
  const cur = currentSeason();
  let list = Array.isArray(d.seasons) && d.seasons.length ? d.seasons.map(toSeason).filter(Boolean) : [];
  if (!list.length) for (let a = Math.floor(cur / 10000); a >= Math.floor(FIRST_SEASON / 10000); a--) list.push(a * 10000 + a + 1);
  if (list.indexOf(cur) < 0) list.push(cur);
  return list.sort((a, b) => b - a);
}
/* index.json "phase": 'preseason' | 'regular' | 'playoffs' | 'offseason' (as written). */
function phase() { const d = INDEX.data || {}; return String(d.phase || ''); }
function phaseLabel(p) {
  const s = String(p === undefined ? phase() : p).toLowerCase();
  if (/play/.test(s)) return 'Playoffs';
  if (/off/.test(s)) return 'Offseason';
  if (/pre/.test(s)) return 'Preseason';
  if (/reg|season/.test(s)) return 'Regular season';
  return s ? titleCase(s) : '';
}

// ── hockey vocabulary ──────────────────────────────────────────────────────

/* NHL gameId "2026020009" -> {season: 20262027, type: '02', number: 9, playoff, round, series, game}. */
function parseGameId(id) {
  const s = String(id || '');
  const m = /^(\d{4})(\d{2})(\d{4})$/.exec(s);
  if (!m) return null;
  const a = Number(m[1]);
  const out = { season: a * 10000 + a + 1, type: m[2], number: Number(m[3]), playoff: m[2] === '03' };
  if (out.playoff) { out.round = Number(m[3].charAt(1)); out.series = Number(m[3].charAt(2)); out.game = Number(m[3].charAt(3)); }
  return out;
}
function gameSeason(id) { const g = parseGameId(id); return g ? g.season : null; }
function gameType(id) { const g = parseGameId(id); return g ? g.type : ''; }
function isPlayoffGame(g) {
  if (!g) return false;
  if (typeof g !== 'object') return gameType(g) === '03';
  if (g.playoff === true || String(g.type || g.game_type || '') === '03' || /^(p|po|playoff)/i.test(String(g.type || g.game_type || ''))) return true;
  return gameType(g.game_id || g.id) === '03';
}
function gtypeLabel(t, short) {
  let k = String(t || '');
  if (/^\d{10}$/.test(k)) k = gameType(k);
  if (/^\d$/.test(k)) k = '0' + k;
  if (/^(p|po|playoff)/i.test(k)) k = '03';
  if (/^(r|reg)/i.test(k)) k = '02';
  return (short ? GTYPE_SHORT : GTYPE_LONG)[k] || String(t || '');
}
function roundName(r) { return ROUND_NAMES[r] || (isNum(r) ? 'Round ' + r : ''); }
/* periodLabel(2) -> "2nd"; 4 -> "OT"; 5 -> "SO" (regular season) or "2OT" (playoffs); long -> "2nd period" / "Overtime" / "Shootout".
 * opts: {playoff: bool, long: bool} or a game (card) to read the type from. */
function periodLabel(p, opts) {
  if (!isNum(p)) return p ? String(p) : '';
  const o = opts && typeof opts === 'object' && (opts.game_id || opts.home) ? { playoff: isPlayoffGame(opts) } : (typeof opts === 'boolean' ? { long: opts } : (opts || {}));
  const n = Number(p);
  if (n <= 3) return o.long ? ordinal(n) + ' period' : ordinal(n);
  if (!o.playoff && n === 5) return o.long ? 'Shootout' : 'SO';
  if (n === 4) return o.long ? 'Overtime' : 'OT';
  return o.long ? ordinal(n - 3) + ' overtime' : (n - 3) + 'OT';
}
/* Clock in a period: 754 (seconds remaining) -> "12:34"; "12:34" stays. */
function fmtClock(c) {
  if (c === null || c === undefined || c === '') return '';
  if (isNum(c)) { const s = Math.max(0, Math.round(Number(c))); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
  return String(c);
}
/* "2nd 12:34" (opts as periodLabel). */
function clockText(p, c, opts) { return [periodLabel(p, opts), fmtClock(c)].filter(Boolean).join(' '); }
/* Elapsed game seconds -> {period, clock ("mm:ss" remaining)}; overtime is 5:00 in the regular season, 20:00 in the playoffs. */
function secToClock(sec, playoff) {
  if (!isNum(sec)) return { period: null, clock: '' };
  const s = Math.max(0, Number(sec));
  if (s < 3600) { const p = Math.floor(s / 1200) + 1; return { period: Math.min(3, p), clock: fmtClock(1200 * Math.min(3, p) - s) }; }
  const len = playoff ? 1200 : 300;
  const k = Math.floor((s - 3600) / len);
  return { period: 4 + k, clock: fmtClock(len - (s - 3600 - k * len)) };
}
/* "2nd 12:34" from elapsed seconds. */
function secText(sec, playoff) { const x = secToClock(sec, playoff); return clockText(x.period, x.clock, { playoff: playoff }); }
/* Time on ice: seconds -> "18:42"; "18:42" stays; opts.minutes = the input is minutes. */
function fmtTOI(v, opts) {
  if (v === null || v === undefined || v === '') return '—';
  if (!isNum(v)) return String(v);
  const s = Math.max(0, Math.round(Number(v) * (opts && opts.minutes ? 60 : 1)));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
/* Time on ice in a game payload, to seconds: "18:42" stays exact; a number up to 90 is minutes (25.25), above it seconds. */
function toiGame(v) {
  if (isNum(v)) return Number(v) <= 90 ? Number(v) * 60 : Number(v);
  return toiSec(v);
}
/* "18:42" | 1122 -> seconds (Number) or null. */
function toiSec(v) {
  if (isNum(v)) return Number(v);
  const m = /^(\d+):(\d\d)$/.exec(String(v || '').trim());
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}
/* Strength of an event from the shooting (or acting) team's side. Accepts '5v5', '5v4', '4v5', '6v5', 'EV', 'PP', 'SH', 'PK', 'EN',
 * or the NHL situationCode '1551' (away goalie, away skaters, home skaters, home goalie) with side 'home'|'away'.
 * -> {key: '5v5'|'4v4'|'3v3'|'PP'|'PK'|'EN'|'EA'|'EV'|'', label, short, own, opp, emptyNet}. key EN: the opposing net is empty;
 * EA: the team has an extra attacker (own goalie pulled). */
function strength(s, side) {
  const raw = String(s === null || s === undefined ? '' : s).trim();
  let own = null, opp = null, ownG = 1, oppG = 1;
  let m = /^([01])(\d)(\d)([01])$/.exec(raw);
  if (m && side) {
    const ag = Number(m[1]), as = Number(m[2]), hs = Number(m[3]), hg = Number(m[4]);
    if (side === 'home') { own = hs; opp = as; ownG = hg; oppG = ag; } else { own = as; opp = hs; ownG = ag; oppG = hg; }
  } else if ((m = /^(\d)\s*v\s*(\d)$/i.exec(raw))) { own = Number(m[1]); opp = Number(m[2]); }
  if (own !== null) {
    const nm = own + 'v' + opp;
    if (oppG === 0) return { key: 'EN', label: 'Empty net', short: 'EN', own: own, opp: opp, emptyNet: true };
    if (ownG === 0 || (own === 6 && opp === 5)) return { key: 'EA', label: 'Extra attacker (' + nm + ')', short: nm, own: own, opp: opp };
    if (own > opp) return { key: 'PP', label: 'Power play (' + nm + ')', short: 'PP', own: own, opp: opp };
    if (own < opp) return { key: 'PK', label: 'Shorthanded (' + nm + ')', short: 'SH', own: own, opp: opp };
    if (own === 5) return { key: '5v5', label: '5v5', short: '5v5', own: own, opp: opp };
    return { key: nm, label: nm, short: nm, own: own, opp: opp };
  }
  const k = raw.toUpperCase();
  if (k === 'EV' || k === 'ES' || k === 'EVEN') return { key: 'EV', label: 'Even strength', short: 'EV' };
  if (k === 'PP' || k === 'PPG') return { key: 'PP', label: 'Power play', short: 'PP' };
  if (k === 'SH' || k === 'PK' || k === 'SHG') return { key: 'PK', label: 'Shorthanded', short: 'SH' };
  if (k === 'EN' || k === 'ENG') return { key: 'EN', label: 'Empty net', short: 'EN' };
  if (k === 'ALL') return { key: 'all', label: 'All situations', short: 'All' };
  return { key: raw, label: raw, short: raw };
}
/* The filter group of a strength ('5v5' | 'PP' | 'PK' | 'EN' | 'other'). */
function strengthGroup(s, side) {
  const k = strength(s, side).key;
  if (k === '5v5' || k === 'EV') return '5v5';
  if (k === 'PP' || k === 'PK' || k === 'EN') return k;
  return 'other';
}
function strengthLabel(s, side) { return strength(s, side).label; }
/* A small coloured strength tag (PP, SH, EN, 4v4 ...); '' at 5v5. */
function strengthTag(s, side) {
  const x = strength(s, side);
  if (!x.key || x.key === '5v5' || x.key === 'EV' || x.key === 'all') return '';
  const col = x.key === 'PP' ? C.ice : x.key === 'PK' ? C.goal : x.key === 'EN' ? C.yellow : C.text2;
  return '<span class="rk-pill" style="border-color:' + col + ';color:' + col + '" title="' + esc(x.label) + '">' + esc(x.short) + '</span>';
}
/* An event or shot type -> its label: 'shot-on-goal' -> 'Shot on goal'. */
function shotTypeLabel(t) { const k = String(t || '').toLowerCase(); return SHOT_TYPES[k] || titleCase(k); }
/* Positions: 'C' | 'L' | 'LW' | 'R' | 'RW' | 'D' | 'G' -> {key: 'C'|'LW'|'RW'|'D'|'G', group: 'F'|'D'|'G', label}. */
function posInfo(p) {
  const k = String(p || '').toUpperCase();
  if (k === 'C') return { key: 'C', group: 'F', label: 'Centre' };
  if (k === 'L' || k === 'LW') return { key: 'LW', group: 'F', label: 'Left wing' };
  if (k === 'R' || k === 'RW') return { key: 'RW', group: 'F', label: 'Right wing' };
  if (k === 'F' || k === 'W') return { key: k, group: 'F', label: k === 'F' ? 'Forward' : 'Wing' };
  if (k === 'D') return { key: 'D', group: 'D', label: 'Defence' };
  if (k === 'G') return { key: 'G', group: 'G', label: 'Goalie' };
  return { key: k, group: '', label: k };
}
/* The other team of a game for a team. */
function otherTeam(g, t) { if (!g) return null; return String(t) === String(g.home) ? g.away : g.home; }

/* Status of a GAME_CARD / game: 'pre' | 'live' | 'int' (intermission) | 'final' | 'postponed' | 'cancelled' | 'delayed'.
 * NHL gameState FUT/PRE -> pre, LIVE/CRIT -> live, OFF/FINAL -> final. */
function gameState(g) {
  const s = String((g && (g.status || g.state || g.game_state)) || '').toLowerCase().replace(/^status_/, '');
  if (g && g.intermission === true && !/final|off/.test(s)) return 'int';
  if (/^int|intermission/.test(s)) return 'int';
  if (s === 'live' || s === 'crit' || s === 'in' || /progress|^p\d|end_period|end of/.test(s)) return 'live';
  if (/final|^off$|^post$|^done$|complete|game over|^closed$/.test(s)) return 'final';
  if (s === 'pre' || s === 'fut' || /sched|upcoming|preview|^$/.test(s)) return 'pre';
  if (/ppd|postpon/.test(s)) return 'postponed';
  if (/cancel/.test(s)) return 'cancelled';
  if (/delay|susp/.test(s)) return 'delayed';
  return s;
}
function isFinal(g) { return gameState(g) === 'final'; }
function isLive(g) { const s = gameState(g); return s === 'live' || s === 'int'; }
function isPre(g) { return gameState(g) === 'pre'; }
/* How a game ended: '' (regulation), 'OT', '2OT' ..., 'SO'. */
function endedIn(g) {
  if (!g) return '';
  if (g.so === true || String(g.ended || g.last_period_type || '').toUpperCase() === 'SO') return 'SO';
  const playoff = isPlayoffGame(g);
  const p = isNum(g.period) ? Number(g.period) : (Array.isArray(periodsOf(g)) ? periodsOf(g).length : 0);
  if (p >= 4) return periodLabel(p, { playoff: playoff });
  if (g.ot === true || String(g.ended || g.last_period_type || '').toUpperCase() === 'OT') return 'OT';
  return '';
}
function isOT(g) { return endedIn(g) !== ''; }
/* A status chip: puck-drop time, live period and clock, intermission, Final (Final/OT, Final/SO). */
function statusChip(g) {
  const st = gameState(g);
  if (st === 'live') return '<span class="chip st-live"><span class="live-dot"></span> ' + esc(clockText(g.period, g.clock, g) || 'Live') + '</span>';
  if (st === 'int') return '<span class="chip st-live"><span class="live-dot"></span> ' + esc(isNum(g.period) ? periodLabel(g.period, g) + ' int.' : 'Intermission') + '</span>';
  if (st === 'final') { const e = endedIn(g); return '<span class="chip st-ft">Final' + (e ? '/' + esc(e) : '') + '</span>'; }
  if (st === 'pre') {
    const k = g.start || g.date;
    const t = fmtTime(k);
    return '<span class="chip st-time">' + esc((parseDate(k) && String(k).length > 10 ? DAYS[parseDate(k).getDay()] + ' ' : '') + (t || 'TBD')) + '</span>';
  }
  return '<span class="chip warn">' + esc(titleCase(st)) + '</span>';
}
function pick2(o, keys) { for (let i = 0; i < keys.length; i++) if (o[keys[i]] !== undefined && o[keys[i]] !== null) return o[keys[i]]; return null; }
/* Periods of a game as [{label, away, home, sog_home, sog_away, xg_home, xg_away}] from g.linescore | g.periods | g.by_period: [[away, home]], [{period, home, away}],
 * or {home: [...], away: [...]}. */
function periodsOf(g) {
  if (!g) return [];
  const q = g.linescore || g.periods || g.by_period || g.score_by_period;
  if (!q) return [];
  const playoff = isPlayoffGame(g);
  const lab = (p, i) => (p && (p.label || p.period_label)) || periodLabel(isNum(p && p.period) ? p.period : i + 1, { playoff: playoff });
  if (Array.isArray(q)) return q.map((r, i) => (Array.isArray(r) ? { label: periodLabel(i + 1, { playoff: playoff }), away: r[0], home: r[1] } :
    { label: lab(r, i), away: pick2(r, ['away', 'g_away']), home: pick2(r, ['home', 'g_home']), sog_home: pick2(r, ['sog_home', 's_home']), sog_away: pick2(r, ['sog_away', 's_away']),
      xg_home: r.xg_home, xg_away: r.xg_away }));
  if (Array.isArray(q.home) && Array.isArray(q.away)) return q.home.map((h, i) => ({ label: periodLabel(i + 1, { playoff: playoff }), away: q.away[i], home: h }));
  return [];
}

/* The home puck line from an object: {puck_line} (number, or {line|home_line}) | {puck_line_home} when it is a line (|x| >= 1). */
function homeLine(o) {
  if (!o) return null;
  const pl = o.puck_line;
  if (isNum(pl)) return Number(pl);
  if (pl && typeof pl === 'object') { const v = isNum(pl.line) ? pl.line : (isNum(pl.home_line) ? pl.home_line : pl.home); if (isNum(v) && Math.abs(v) >= 0.5 && Math.abs(v) < 10) return Number(v); }
  if (isNum(o.puck_line_home) && Math.abs(o.puck_line_home) >= 1) return Number(o.puck_line_home);
  if (isNum(o.spread_home)) return Number(o.spread_home);
  return null;
}
/* "TOR -1.5" (the favourite and its line) from the home line. */
function lineText(home, away, line) {
  if (!isNum(line)) return '—';
  const x = Number(line);
  if (Math.abs(x) < 0.05) return 'PK';
  return (x < 0 ? teamAbbr(home) : teamAbbr(away)) + ' ' + fmtLine(-Math.abs(x));
}
/* A goalie field: a pid (linked surname), a name, or {pid|id, name, status ('confirmed'|'projected'|'likely'), gsax}. */
function goalieText(q, link) {
  if (!q) return '';
  if (typeof q === 'object') {
    const pid = q.pid || q.id || q.player_id;
    const nm = q.name || (pid ? playerName(pid) : '');
    const st = q.status && !/^(confirmed|starter|start|ok)$/i.test(q.status) ? ' <span class="g-st" title="Starter ' + esc(q.status) + '">' + esc(String(q.status).charAt(0).toUpperCase()) + '</span>' : '';
    return (pid && link !== false ? playerLink(pid, { name: surnameOf(nm) }) : esc(surnameOf(nm))) + st;
  }
  const s = String(q);
  if (/^\d{7}$/.test(s)) return link === false ? esc(playerSurname(s)) : playerLink(s, { surname: true });
  return esc(surnameOf(s));
}
function surnameOf(n) {
  const p = String(n || '').split(' ');
  if (p.length < 2) return p[0];
  const sfx = /^(Jr\.?|Sr\.?|II|III|IV|V)$/i.test(p[p.length - 1]);
  return sfx && p.length > 2 ? p[p.length - 2] + ' ' + p[p.length - 1] : p.slice(1).join(' ');
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
function sq(S) { const s = toSeason(S || state.season); return s && s !== currentSeason() ? '?s=' + s : ''; }
/* A route with the season query: href('teams') -> '#/teams' (or '#/teams?s=20252026'). */
function href(sub, S) { return '#/' + String(sub || '').replace(/^\/+/, '') + sq(S); }
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
function confName(c) {
  const s = String(c || '');
  if (/^e/i.test(s)) return 'Eastern';
  if (/^w/i.test(s)) return 'Western';
  return s;
}
function teamInfo(t) { return TEAMS[canonTeam(t)] || {}; }
function teamName(t) { const x = teamInfo(t); return x.name || (t ? String(t) : '—'); }
function teamShort(t) { const x = teamInfo(t); return x.short || x.name || (t ? String(t) : '—'); }
function teamAbbr(t) { return t ? (teamInfo(t).abbr || String(t)) : '—'; }
function teamConf(t) { const x = teamInfo(t); return confName(x.conference || DIV_CONF[x.division] || ''); }
function teamDiv(t) { return teamInfo(t).division || ''; }
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
  if (lum(rgb) < 0.13 && alt && lum(alt) > 0.18 && lum(alt) < 0.85) rgb = alt;
  else if (lum(rgb) < 0.06 && alt && lum(alt) >= 0.85) rgb = alt;
  let c = rgb.slice(), k = 0;
  while (lum(c) < 0.32 && k < 12) { c = c.map(v => Math.round(v + (255 - v) * 0.14)); k++; }
  return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
}
/* A colour distance that tracks perception better than plain RGB ("redmean"): about 0 for the same colour, ~150 for
 * two shades that read as different hues on the dark theme, 765 for black v white. */
function colourDist(A, B) {
  const r = (A[0] + B[0]) / 2, dr = A[0] - B[0], dg = A[1] - B[1], db = A[2] - B[2];
  return Math.sqrt((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db);
}
/* Two team colours that can be told apart (CAR and FLA are both red; TBL and WPG both blue): the first keeps its
 * colour; the second falls back to its alternate (when it reads on the dark theme), then to white or amber,
 * whichever stands furthest from the first. */
const PAIR_MIN = 150;
function pairColours(a, b) {
  const ca = teamColour(a);
  const cb = teamColour(b);
  const A = hexRGB(ca), B = hexRGB(cb);
  if (!A || !B || colourDist(A, B) >= PAIR_MIN) return [ca, cb];
  // the alternate only when it reads on its own (a black alternate lifted to grey looks disabled)
  const altR = hexRGB(teamInfo(b).alt);
  const cands = [altR && lum(altR) > 0.25 ? teamInfo(b).alt : null, '#e6edf3', '#f0b429'].filter(Boolean);
  const ok = cands.find(c => colourDist(A, hexRGB(c)) >= PAIR_MIN);
  return [ca, ok || cands.slice().sort((x, y) => colourDist(A, hexRGB(y)) - colourDist(A, hexRGB(x)))[0]];
}
/* The raw club colour (for fills behind white text). */
function teamColourRaw(t) { return teamInfo(t).colour || C.bg3; }
function teamAlt(t) { return teamInfo(t).alt || C.text3; }
function teamBar(t, colour) { return '<span class="team-bar" style="background:' + (colour || teamColour(t)) + '"></span>'; }
function teamHref(t, S) { return href('team/' + encodeURIComponent(teamAbbr(t)), S); }
/* <a> to the team page. opts {abbr: true, short: true, bar: true (default), colour (the bar's, e.g. from pairColours), name, season}. */
function teamLink(t, opts) {
  if (!t) return '<span class="muted-inline">—</span>';
  const o = typeof opts === 'string' ? { name: opts } : (opts || {});
  const label = o.name || (o.abbr ? teamAbbr(t) : o.short ? teamShort(t) : teamName(t));
  const bar = o.bar === false ? '' : teamBar(t, o.colour);
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
/* "BOS @ TOR" linked to the game centre. */
function matchupLink(id, away, home) {
  return '<a class="game-link" href="' + gameHref(id) + '">' + esc(teamAbbr(away)) + ' @ ' + esc(teamAbbr(home)) + '</a>';
}
/* The games page: a date ('2026-10-07'), else the season's default day. */
function gamesHref(date, S) {
  if (date) return '#/games/' + date;
  return '#/games' + sq(S);
}
function standingsHref(S) { const s = toSeason(S || state.season); return '#/standings' + (s && s !== currentSeason() ? '/' + s : ''); }
function playoffsHref(S) { const s = toSeason(S || state.season); return '#/playoffs' + (s && s !== currentSeason() ? '/' + s : ''); }
function compareHref(a, b) { return '#/compare' + (a ? '/' + encodeURIComponent(a) : '') + (b ? '/' + encodeURIComponent(b) : ''); }
function glossHref(key) { return '#/glossary' + (key ? '/' + encodeURIComponent(key) : ''); }

/* A market TITLE dict -> {id: p} (de-vigged "probs", else "prices", else the raw "mid"); {} when unavailable. */
/* A market's sources as a short label: ["kalshi", "polymarket"] -> "Kalshi + Polymarket"; [{source: "polymarket", ...}]
 * -> "Polymarket"; ["line"] -> "No-vig line"; a {name: fetched_at} map -> its names. '' when there are none. */
const SRC_NAME = { kalshi: 'Kalshi', polymarket: 'Polymarket', line: 'No-vig line', book: 'No-vig line', draftkings: 'DraftKings', espn: 'ESPN' };
function srcLabel(src) {
  if (src === null || src === undefined || src === '') return '';
  let list = Array.isArray(src) ? src : (typeof src === 'object' ? (src.source || src.name ? [src] : Object.keys(src)) : [src]);
  const out = [];
  list.forEach(x => {
    const n = x && typeof x === 'object' ? (x.source || x.name || x.provider || '') : x;
    if (n === null || n === undefined || n === '') return;
    const k = String(n).toLowerCase();
    const lab = SRC_NAME[k] || titleCase(String(n));
    if (out.indexOf(lab) < 0) out.push(lab);
  });
  return out.join(' + ');
}
/* True when a market price is only the de-vigged sportsbook line. */
function srcLineOnly(src) { return srcLabel(src) === 'No-vig line'; }

function titleProbs(t) {
  if (!t || t.available === false) return {};
  return t.probs || t.prices || t.mid || {};
}

/* A GAME_CARD tile (index.json today/live/recent/upcoming, schedule.json). Links to the game centre.
 * Lines: model (home win %, P(OT), total), market (de-vigged home win %, sources), the current/closing line,
 * live WP and xG. opts {date: true (day before the time), compact}. */
function gameCard(g, opts) {
  const o = opts || {};
  if (!g) return '';
  const st = gameState(g);
  const m = g.model || {}, mk = g.market || null, ln = g.line || null;
  const pH = isNum(m.p_home) ? Number(m.p_home) : null;
  const live = st === 'live' || st === 'int', fin = st === 'final';
  const hs = isNum(g.hs) ? g.hs : null, as = isNum(g.as) ? g.as : null;
  const pShow = live && isNum(g.wp_home) ? Number(g.wp_home) : (fin ? null : pH);
  const winH = fin && hs !== null && as !== null && hs > as, winA = fin && hs !== null && as !== null && as > hs;
  const gl = g.goalies || {};
  const xg = g.xg || null;
  const row = (t, score, p, win, lose, side) =>
    '<div class="gc-team' + (win ? ' gc-win' : '') + (lose ? ' gc-lose' : '') + '">' + teamBar(t) +
    '<span class="gc-name"><span class="gc-abbr">' + esc(teamAbbr(t)) + '</span> <span class="gc-full">' + esc(teamShort(t)) + '</span>' +
    (gl[side] && (st === 'pre' || o.goalies) ? '<span class="gc-sp" title="Starting goalie">' + goalieText(gl[side], false) + '</span>' : '') + '</span>' +
    ((live || fin) && xg && isNum(xg[side]) ? '<span class="gc-xg" title="Expected goals">' + num(xg[side], 1) + '</span>' : '<span class="gc-xg"></span>') +
    (st === 'pre' || score === null ? '<span></span>' : '<span class="gc-score">' + esc(score) + '</span>') +
    '<span class="gc-p" title="' + (live && isNum(g.wp_home) ? 'Live' : 'Model pre-game') + ' ' + side + ' win probability">' + (p === null ? '' : pct(p, 0)) + '</span></div>';
  let top = statusChip(g);
  if (o.date) top = '<span class="gc-date">' + esc(fmtDate(g.date || g.start, { year: false })) + '</span> ' + top;
  const pg = parseGameId(g.game_id);
  const tag = pg && pg.playoff ? roundName(pg.round) + (pg.game ? ' · G' + pg.game : '') : (g.label || '');
  const lines = [];
  if (pH !== null || isNum(m.total)) {
    lines.push('<span class="gc-l"><b>Model</b> ' + (pH !== null ? esc(teamAbbr(pH >= 0.5 ? g.home : g.away)) + ' ' + pct(Math.max(pH, 1 - pH), 0) : '') +
      (isNum(m.p_ot) ? ' · OT ' + pct(m.p_ot, 0) : '') + (isNum(m.total) ? ' · ' + num(m.total, 1) + ' goals' : '') + '</span>');
  }
  if (mk && isNum(mk.p_home)) {
    const fav = (pH !== null ? pH : mk.p_home) >= 0.5 ? 'home' : 'away';
    const mp = fav === 'home' ? mk.p_home : 1 - mk.p_home, mm = pH === null ? null : (fav === 'home' ? pH : 1 - pH);
    const lineOnly = srcLineOnly(mk.sources);
    lines.push('<span class="gc-l"><b>' + (lineOnly ? 'No-vig' : 'Market') + '</b> ' + esc(teamAbbr(g[fav])) + ' ' + pct(mp, 0) + (mm !== null && !fin ? ' (' + edgeHTML(mm, mp, 0) + ')' : '') +
      (srcLabel(mk.sources) && !lineOnly ? ' <span class="src-chip">' + esc(srcLabel(mk.sources)) + '</span>' : '') + '</span>');
  }
  if (ln) {
    const L = fin && ln.close && typeof ln.close === 'object' ? Object.assign({}, ln, ln.close) : ln;
    const l = homeLine(L);
    const bits = [];
    if (isNum(L.ml_home) && isNum(L.ml_away)) bits.push(esc(teamAbbr(g.home)) + ' ' + fmtOdds(L.ml_home));
    if (isNum(l)) bits.push(esc(lineText(g.home, g.away, l)));
    if (isNum(L.total)) bits.push('O/U ' + num(L.total, 1));
    if (bits.length) lines.push('<span class="gc-l"><b>' + esc(ln.src || (fin ? 'Close' : 'Line')) + '</b> ' + bits.join(' · ') + '</span>');
  }
  if (live && isNum(g.wp_home)) {
    const fav = g.wp_home >= 0.5 ? g.home : g.away;
    lines.push('<span class="gc-l gc-wp"><b>Live</b> ' + esc(teamAbbr(fav)) + ' ' + pct(Math.max(g.wp_home, 1 - g.wp_home), 0) + ' to win' +
      (xg && isNum(xg.home) && isNum(xg.away) ? ' · xG ' + num(xg.away, 1) + '–' + num(xg.home, 1) : '') + '</span>');
  }
  return '<a class="gc' + (live ? ' gc-live' : '') + (o.compact ? ' gc-compact' : '') + '" href="' + gameHref(g.game_id || g.id) + '">' +
    '<div class="gc-top">' + top + (tag ? '<span class="gc-tag">' + esc(tag) + '</span>' : '') + '</div>' +
    row(g.away, as, pShow === null ? null : 1 - pShow, winA, winH, 'away') + row(g.home, hs, pShow, winH, winA, 'home') +
    (lines.length ? '<div class="gc-lines">' + lines.join('') + '</div>' : '') + '</a>';
}

// ── HTML builders ──────────────────────────────────────────────────────────

function card(title, sub, bodyHtml, id, ctl) {
  return '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' +
    (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + (ctl || '') + '</div>' : '') +
    (bodyHtml || '') + '</div>';
}
function muted(text) { return '<div class="muted">' + text + '</div>'; }
function chip(text, cls) { return '<span class="chip' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</span>'; }
function notBuilt(what, d) { return muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '. The payloads are rebuilt every hour.'); }
/* A coloured pill: pill('PP', '#5cc6f2'). */
function pill(text, colour, title) {
  return '<span class="rk-pill"' + (title ? ' title="' + esc(title) + '"' : '') + ' style="border-color:' + (colour || C.border) + ';color:' + (colour || C.text2) + '">' + esc(text) + '</span>';
}

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
/* Model minus market in percentage points, coloured (green = model higher). */
function edgeHTML(model, market, d) {
  if (!isNum(model) || !isNum(market)) return '<span class="muted-inline">—</span>';
  const e = (model - market) * 100;
  return '<span class="' + (e > 0.05 ? 'edge-pos' : e < -0.05 ? 'edge-neg' : 'muted-inline') + '">' + signed(e, d === undefined ? 1 : d) + '</span>';
}
/* A difference in goals (lines, totals), coloured: green when positive. */
function ptsEdge(v, d) {
  if (!isNum(v)) return '<span class="muted-inline">—</span>';
  return '<span class="' + (v > 0.005 ? 'edge-pos' : v < -0.005 ? 'edge-neg' : 'muted-inline') + '">' + signed(v, d === undefined ? 2 : d) + '</span>';
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
/* Sequential colour for t in [0,1] (the ice accent). */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'rgba(92,198,242,' + (0.05 + 0.7 * u).toFixed(3) + ')';
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

// ── charts plumbing ────────────────────────────────────────────────────────

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
/* A legacy chart written against Plotly loads the kit's Plotly-on-ECharts module on first use (the Plotly
 * CDN bundle is no longer used; the redesigned pages draw with QKC directly). */
const PLOTLY_SRC = 'assets/qk/plotly-ec.js';
let plotlyP = null;
function loadPlotly() {
  if (typeof Plotly !== 'undefined') return Promise.resolve(true);
  if (!plotlyP) {
    plotlyP = new Promise(res => {
      const sc = document.createElement('script');
      sc.src = PLOTLY_SRC; sc.charset = 'utf-8'; sc.async = true;
      sc.onload = () => res(true);
      sc.onerror = () => { plotlyP = null; res(false); };
      document.head.appendChild(sc);
    });
  }
  return plotlyP;
}
function drawPlot(node, traces, lay, conf) {
  try {
    const p = Plotly.newPlot(node, traces, lay && lay.paper_bgcolor !== undefined ? lay : layout(lay), Object.assign({}, PLOTLY_CONF, conf || {}));
    onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    if (node.__rkClick && p && p.then) p.then(() => clickThrough(node));
    return p;
  } catch (err) {
    console.warn('chart failed', err);
    node.innerHTML = '<div class="muted">The chart could not be drawn.</div>';
    return null;
  }
}
/* Click a Plotly point -> its customdata hash (attached once the chart exists). */
function clickThrough(node) {
  if (!node) return;
  if (!node.on) { node.__rkClick = true; return; }
  if (node.__rkClickBound) return;
  node.__rkClickBound = true;
  node.on('plotly_click', ev => { const h = ev.points && ev.points[0] && ev.points[0].customdata; if (h && typeof h === 'string' && h.charAt(0) === '#') location.hash = h; });
}
function plot(el, traces, lay, conf) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (typeof Plotly !== 'undefined') return drawPlot(node, traces, lay, conf);
  node.classList.add('rk-plot-wait');
  const route0 = state.hash;
  return loadPlotly().then(ok => {
    node.classList.remove('rk-plot-wait');
    if (!node.isConnected || state.hash !== route0) return null;
    if (!ok) { node.innerHTML = '<div class="muted">The chart library did not load. The tables carry the same data.</div>'; return null; }
    return drawPlot(node, traces, lay, conf);
  });
}
/* Purge every Plotly chart under a node (before replacing its HTML). */
function purge(root) {
  if (!root || typeof Plotly === 'undefined') return;
  root.querySelectorAll('.js-plotly-plot').forEach(n => { try { Plotly.purge(n); } catch (e) { /* gone */ } });
}

// ── header: season picker, nav, meta, search ───────────────────────────────

/* Change the season shown, keeping the page where it makes sense. */
function setSeason(S0) {
  const S = toSeason(S0);
  if (!S) return;
  const r = state.route || 'hub';
  const cur = currentSeason();
  if (r === 'standings') { go(standingsHref(S)); return; }
  if (r === 'playoffs') { go(playoffsHref(S)); return; }
  if (r === 'games' || r === 'game') { go(gamesHref(null, S)); return; }
  if (r === 'hub' && S !== cur) { go(standingsHref(S)); return; }
  const h = String(location.hash || '#/').replace(/\?.*$/, '');
  const q = Object.assign({}, state.params.query || {});
  delete q.y; delete q.season; delete q.d;
  if (S === cur) delete q.s; else q.s = String(S);
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  go((h === '#' ? '#/' : h) + (qs ? '?' + qs : ''));
}
function fillPickers() {
  const sel = document.getElementById('season-select');
  if (!sel) return;
  const list = seasons();
  if (state.season && list.indexOf(state.season) < 0) list.unshift(state.season);
  const html = list.map(y => '<option value="' + y + '">' + seasonLabel(y) + '</option>').join('');
  if (sel.dataset.filled !== html.length + ':' + list[0]) { sel.innerHTML = html; sel.dataset.filled = html.length + ':' + list[0]; }
  sel.value = String(state.season || currentSeason());
}
function updateHeader() {
  const S = state.season;
  if (SHELL) {
    const map = { overview: '#/', fixtures: gamesHref(null, S), standings: standingsHref(S), teams: href('teams', S), players: href('players', S),
      value: href('value', S), fantasy: '#/fantasy', lab: href('lab', S), model: '#/model' };
    document.querySelectorAll('.qk-secnav a[data-sec]').forEach(a => { const h = map[a.getAttribute('data-sec')]; if (h) a.setAttribute('href', h); });
  }
  const links = { hub: '#/', games: gamesHref(null, S), standings: standingsHref(S), playoffs: playoffsHref(S),
    teams: href('teams', S), skaters: href('skaters', S), goalies: href('goalies', S), lines: href('lines', S), value: href('value', S), trade: '#/trade', leaders: href('leaders', S),
    history: '#/history', lab: href('lab', S), compare: '#/compare', markets: '#/markets', calibration: '#/calibration', glossary: '#/glossary',
    methodology: '#/methodology' };
  document.querySelectorAll('.global-nav a[data-nav]').forEach(a => { if (links[a.dataset.nav]) a.setAttribute('href', links[a.dataset.nav]); });
}
let SHELL = null;
function markNav(key) {
  if (SHELL) SHELL.setSection(key);
}
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const S = state.season || currentSeason();
  const base = ['NHL ' + seasonLabel(S) + (S === currentSeason() && phaseLabel() ? ' · ' + phaseLabel() : ''),
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
      if (!x.name || HISTORIC.indexOf(t) >= 0) return;
      items.push({ kind: 'Teams', id: t, label: x.name, sub: [t, x.division].filter(Boolean).join(' · '), href: teamHref(t, cur), colour: teamColour(t),
        order: 0, norm: norm(x.name + ' ' + t + ' ' + (x.short || '') + ' ' + (x.city || '')) });
    });
    Object.keys(NAMES).forEach(pid => {
      const x = NAMES[pid] || {};
      if (!x.name) return;
      const last = toSeason(x.last) || 0, first = toSeason(x.first);
      const yrs = first ? (first === last ? seasonLabel(last) : seasonStart(first) + '–' + (last >= cur ? '' : seasonEnd(last))) : '';
      items.push({ kind: 'Players', id: pid, label: x.name,
        sub: [x.pos, x.team ? teamAbbr(x.team) : '', yrs].filter(Boolean).join(' · '),
        href: playerHref(pid), order: last ? Math.floor((cur - last) / 10001) : 99, norm: norm(x.name + ' ' + (x.short || '')) });
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
/* Legacy colour constants and the Plotly layout follow the kit's tokens (dark or light). */
function retheme() {
  if (!window.QKC) return;
  const T = QKC.tokens();
  C.bg = T.bg; C.bg2 = T.s1; C.bg3 = T.s2; C.border = T.s4;
  C.text = T.ink1; C.text2 = T.ink2; C.text3 = T.ink3; C.market = T.ink1; C.espn = T.ink3;
  DARK_LAYOUT.font = { color: T.ink2, family: T.fontUI, size: 11 };
  DARK_LAYOUT.xaxis = { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } };
  DARK_LAYOUT.yaxis = { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } };
  DARK_LAYOUT.hoverlabel = { bgcolor: T.s4, bordercolor: T.line2, font: { color: T.ink1, size: 12, family: T.fontUI } };
}
function initHeader() {
  if (window.QK) {
    SHELL = QK.shell({
      sport: 'hockey', section: 'overview',
      sections: QK.sections('hockey'),
      ctx: '<label class="qk-sr" for="season-select">Season</label><select id="season-select" class="qk-select rk-season" aria-label="Season"></select>',
      search: { load: () => loadSearch().then(items => items.map(it => ({ sport: 'hockey', t: it.label, s: (it.kind === 'Teams' ? 'Team · ' : '') + (it.sub || ''), href: it.href }))) }
    });
    retheme();
    QK.theme.onChange(() => {
      setTimeout(() => {
        retheme();
        const app = document.getElementById('app');
        if (app && app.querySelector('.js-plotly-plot, .rk-legacy-colour')) render({ keep: true });
      }, 40);
    });
  }
  const sel = document.getElementById('season-select');
  if (sel) sel.addEventListener('change', () => setSeason(sel.value));
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
  state: state, route: route, page: page, view: view, VIEWS: VIEWS, SECTION_OF: SECTION_OF, redirectFor: redirectFor, go: go,
  loadPlotly: loadPlotly, clickThrough: clickThrough, retheme: retheme, parseHash: parseHash, onLeave: onLeave, interval: interval, render: render, routeEntry: routeEntry,
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES, SITE: SITE, FIRST_SEASON: FIRST_SEASON, MONEYPUCK_CREDIT: MONEYPUCK_CREDIT,
  setSeason: setSeason, setMeta: setMeta, markNav: markNav,
  // data
  load: load, loadAll: loadAll, uncache: uncache, refreshIndex: refreshIndex, liveRefresh: liveRefresh, ok: ok, reason: reason, cached: cached,
  ypath: ypath, loadYear: loadYear, gamePath: gamePath, loadGame: loadGame, playerPath: playerPath, loadPlayer: loadPlayer,
  ensureNames: ensureNames, playersOf: playersOf, putTeam: putTeam, putPlayer: putPlayer,
  index: () => INDEX.data, currentSeason: currentSeason, seasons: seasons, phase: phase, phaseLabel: phaseLabel,
  NAMES: NAMES, TEAMS: TEAMS, NHL_TEAMS: NHL_TEAMS, HISTORIC: HISTORIC, DIVISIONS: DIVISIONS, CONFERENCES: CONFERENCES, DIV_CONF: DIV_CONF,
  STRENGTHS: STRENGTHS, ROUND_NAMES: ROUND_NAMES,
  // seasons
  toSeason: toSeason, seasonLabel: seasonLabel, seasonStart: seasonStart, seasonEnd: seasonEnd, seasonOfDate: seasonOfDate, regGames: regGames,
  // formatting
  esc: esc, num: num, int: int, pct: pct, signed: signed, pp: pp, fmtDate: fmtDate, fmtTime: fmtTime, fmtStamp: fmtStamp, localDay: localDay,
  todayISO: todayISO, addDays: addDays, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal, metric: metric, record: record, american: american,
  decimal: decimal, fmtOdds: fmtOdds, amToProb: amToProb, devigAm: devigAm, devig2: devig2, fmtLine: fmtLine, parseDate: parseDate, isNum: isNum,
  titleCase: titleCase,
  // hockey
  parseGameId: parseGameId, gameSeason: gameSeason, gameType: gameType, isPlayoffGame: isPlayoffGame, gtypeLabel: gtypeLabel, roundName: roundName,
  periodLabel: periodLabel, fmtClock: fmtClock, clockText: clockText, secToClock: secToClock, secText: secText, fmtTOI: fmtTOI, toiSec: toiSec, toiGame: toiGame,
  strength: strength, strengthGroup: strengthGroup, strengthLabel: strengthLabel, strengthTag: strengthTag, shotTypeLabel: shotTypeLabel, posInfo: posInfo,
  otherTeam: otherTeam, gameState: gameState, isFinal: isFinal, isLive: isLive, isPre: isPre, isOT: isOT, endedIn: endedIn, statusChip: statusChip,
  periodsOf: periodsOf, homeLine: homeLine, lineText: lineText, goalieText: goalieText, surnameOf: surnameOf, gameCard: gameCard, titleProbs: titleProbs, srcLabel: srcLabel, srcLineOnly: srcLineOnly,
  // names and links
  player: player, playerInfo: playerInfo, playerName: playerName, playerShort: playerShort, playerSurname: playerSurname, playerColour: playerColour,
  playerLink: playerLink, playerHref: playerHref, canonTeam: canonTeam, confName: confName,
  teamInfo: teamInfo, teamName: teamName, teamShort: teamShort, teamAbbr: teamAbbr, teamConf: teamConf, teamDiv: teamDiv, teamColour: teamColour,
  teamColourRaw: teamColourRaw, teamAlt: teamAlt, pairColours: pairColours, teamBar: teamBar, teamHref: teamHref, teamLink: teamLink,
  gameHref: gameHref, gameLink: gameLink, matchupLink: matchupLink, gamesHref: gamesHref, standingsHref: standingsHref, playoffsHref: playoffsHref,
  compareHref: compareHref, glossHref: glossHref, href: href, ghref: href, sq: sq,
  // HTML
  card: card, muted: muted, chip: chip, pill: pill, notBuilt: notBuilt, tableHTML: tableHTML, sortable: sortable,
  pctPill: pctPill, pctColor: pctColor, pctRow: pctRow, statTile: statTile, tile: statTile, probCell: probCell, edgeHTML: edgeHTML, ptsEdge: ptsEdge,
  splitBar: splitBar, divColour: divColour, seqColour: seqColour, toggles: toggles, wireToggles: wireToggles, pageHead: pageHead,
  // charts
  plot: plot, layout: layout, purge: purge, PALETTE: PALETTE, C: C, DARK_LAYOUT: DARK_LAYOUT, PLOTLY_CONF: PLOTLY_CONF,
  FOOTBALL_URL: FOOTBALL_URL, PADDOCK_URL: PADDOCK_URL, HARDWOOD_URL: HARDWOOD_URL, ACE_URL: ACE_URL, BULLPEN_URL: BULLPEN_URL, GRIDIRON_URL: GRIDIRON_URL,
  charts: {}
};
})();
