/* The Quant Hardwood — core: namespace, state, routing, cached loading, helpers, search.
 *
 * A static shell over JSON payloads under data/ (see oddsmarkets/basketball/PAYLOADS.md).
 * Every page module registers itself with HW.route(name, renderFn) and never edits
 * this file. Routes (hash) carry the league first; L is 'nba' or 'wnba':
 *
 *   #/                                  hub (league = last viewed, default nba)
 *   #/<L>                               hub
 *   #/<L>/season/<S>                    season          (#/<L>/season -> current season)
 *   #/<L>/games[/<YYYY-MM-DD>]          games           (a date list; ?s=S for another season)
 *   #/<L>/game/<gid>                    game
 *   #/<L>/team/<tid>                    team
 *   #/<L>/player/<pid>                  player
 *   #/<L>/players  teams  leaders  awards  playoffs  lab  markets  calibration
 *   #/<L>/value  #/<L>/trade        player value (WAR) and the trade simulator (state in ?t=&m=)
 *   #/<L>/compare                       compare
 *   #/<L>/compare/players/<a>/<b>       compare-players (falls back to a 'compare' handler)
 *   #/<L>/compare/teams/<a>/<b>         compare-teams   (falls back to a 'compare' handler)
 *   #/glossary  #/methodology  #/disclaimer   (global; a league prefix is accepted and kept)
 *
 * Season: every page reads the season from HW.state.season. It comes from the route
 * (#/<L>/season/<S>), else a "?s=<S>" query (any page), else the league's current
 * season. Links built with the helpers below carry ?s= when the season shown is not the
 * current one, so a viewer browsing 2024 stays in 2024.
 *
 * A render function is called as fn(el, params, state): `el` is a fresh <div> inside
 * <main id="app"> (detached when the viewer navigates away, so async code can test
 * el.isConnected), `params` holds {league, season, id, a, b, kind, date, rest, query}.
 * It may return a Promise.
 *
 * HW.route accepts a route name ('game'), an alias ('compare/players') or a pattern
 * ('#/<L>/game/<gid>', 'game/:id'); the league prefix in a pattern is ignored.
 *
 * Most helpers take the league first: teamLink(L, tid). When the first argument is not
 * 'nba'/'wnba' it is treated as the id and the current league is used: teamLink(tid).
 */
window.HW = (function () {
'use strict';

// ── constants ──────────────────────────────────────────────────────────────

const C = {
  bg: '#0d1117', bg2: '#161b22', bg3: '#21262d', border: '#30363d',
  text: '#e6edf3', text2: '#8b949e', text3: '#6e7681',
  blue: '#58a6ff', green: '#3fb950', red: '#f85149', orange: '#f97316',
  purple: '#bc8cff', yellow: '#d29922', teal: '#39d0d8', wood: '#f0883e', wood2: '#c9773a',
  make: '#3fb950', miss: '#f85149',
  pctLow: [59, 130, 246], pctMid: [107, 114, 128], pctHigh: [239, 68, 68]
};
const PALETTE = ['#58a6ff', '#f0883e', '#3fb950', '#bc8cff', '#f85149', '#d29922', '#39d0d8', '#79c0ff', '#d2a8ff', '#ff7b72', '#7ee787', '#e3b341'];
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
const ACE_URL = 'https://pchattani.github.io/the-quant-ace/';
const BULLPEN_URL = 'https://pchattani.github.io/the-quant-bullpen/';
const GRIDIRON_URL = 'https://pchattani.github.io/the-quant-gridiron/';
const RINK_URL = 'https://pchattani.github.io/the-quant-rink/';
const LEAGUES = ['nba', 'wnba'];
const LEAGUE_NAME = { nba: 'NBA', wnba: 'WNBA' };
const LS_LEAGUE = 'qh-league';

// ── state and registries ───────────────────────────────────────────────────

const state = { league: 'nba', season: null, route: null, params: {}, hash: '' };
const INDEX = { data: null };
const NAMES = { nba: { teams: {}, players: {} }, wnba: { teams: {}, players: {} } };
const CACHE = {}, PENDING = {};
const HANDLERS = {};
let CLEANUPS = [];

try { const l = window.localStorage.getItem(LS_LEAGUE); if (LEAGUES.indexOf(l) >= 0) state.league = l; } catch (e) { /* private mode */ }

function isLeague(x) { return LEAGUES.indexOf(String(x)) >= 0; }

// Route table: league-relative pattern segments, ':x' captures.
const ROUTES = [];
function addRoute(pattern, name, fallbacks, defaults, global) {
  ROUTES.push({ pattern: pattern, segs: pattern ? pattern.split('/') : [], name: name, fallbacks: fallbacks || [], defaults: defaults || {}, global: !!global });
}
addRoute('', 'hub');
addRoute('season', 'season');
addRoute('season/:season', 'season');
addRoute('games', 'games');
addRoute('games/:date', 'games');
addRoute('game/:id', 'game');
addRoute('team/:id', 'team');
addRoute('player/:id', 'player');
addRoute('players', 'players');
addRoute('value', 'value');
addRoute('trade', 'trade');
addRoute('moves', 'moves');
addRoute('fantasy', 'fantasy');
addRoute('teams', 'teams');
addRoute('leaders', 'leaders');
addRoute('awards', 'awards');
addRoute('playoffs', 'playoffs');
addRoute('lab', 'lab');
addRoute('compare', 'compare');
addRoute('compare/players', 'compare-players', ['compare'], { kind: 'players' });
addRoute('compare/players/:a', 'compare-players', ['compare'], { kind: 'players' });
addRoute('compare/players/:a/:b', 'compare-players', ['compare'], { kind: 'players' });
addRoute('compare/teams', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('compare/teams/:a', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('compare/teams/:a/:b', 'compare-teams', ['compare'], { kind: 'teams' });
addRoute('markets', 'markets');
addRoute('calibration', 'calibration');
addRoute('standings', 'standings');
addRoute('model', 'model');
addRoute('glossary', 'glossary', [], {}, true);
addRoute('methodology', 'methodology', [], {}, true);
addRoute('disclaimer', 'disclaimer', [], {}, true);

const ALIASES = {
  home: 'hub', index: 'hub', '': 'hub', league: 'hub', overview: 'hub',
  'compare/players': 'compare-players', 'compare_players': 'compare-players',
  'compare/teams': 'compare-teams', 'compare_teams': 'compare-teams',
  schedule: 'games', scores: 'games', bracket: 'playoffs', docs: 'methodology'
};

/* Old routes (before the October 2026 redesign) -> [section route, tab]. The league prefix and the other
 * query keys are kept; '#/<L>/season/<S>' keeps its season as ?s=. Deep links with an id (#/glossary/<key>,
 * #/methodology/<part>, #/<L>/compare/players/<a>/<b>) still render where they are, inside their section. */
const REDIRECTS = {
  season: ['standings', null], leaders: ['players', 'leaders'], awards: ['players', 'awards'],
  playoffs: ['standings', 'bracket'], bracket: ['standings', 'bracket'], markets: ['standings', 'markets'],
  trade: ['value', 'trade'], moves: ['value', 'moves'], calibration: ['model', 'calibration'],
  glossary: ['model', 'glossary'], methodology: ['model', 'methodology'], docs: ['model', 'methodology'],
  hub: ['', null], overview: ['', null], schedule: ['games', null], scores: ['games', null]
};
/* The moves view kept its own ?tab= before it moved under Value & Moves; it is ?mt= now. */
const RENAME_Q = { moves: { tab: 'mt' } };
function redirectFor(hash) {
  let h = String(hash || '').replace(/^#\/?/, '');
  let q = '';
  const qi = h.indexOf('?');
  if (qi >= 0) { q = h.slice(qi + 1); h = h.slice(0, qi); }
  let parts = h.split('/').filter(x => x !== '');
  let L = null;
  if (parts.length && isLeague(parts[0].toLowerCase())) { L = parts[0].toLowerCase(); parts = parts.slice(1); }
  if (!parts.length) return null;
  const head = parts[0];
  const to = REDIRECTS[head];
  if (!to) return null;
  const extra = [];
  if (parts.length > 1) {
    if (head === 'season' && parts.length === 2 && /^\d{4}$/.test(parts[1])) extra.push('s=' + parts[1]);
    else return null;                      // glossary/<key>, methodology/<part>: rendered in place
  }
  const ren = RENAME_Q[head] || {};
  let query = q.split('&').filter(Boolean).map(kv => { const k = kv.split('=')[0]; return ren[k] ? ren[k] + kv.slice(k.length) : kv; });
  if (to[1]) query = ['tab=' + to[1]].concat(query.filter(kv => !/^tab=/.test(kv)));
  if (head === 'season' && extra.length) query = query.filter(kv => !/^s=/.test(kv));
  const all = query.concat(extra);
  return '#/' + (L || state.league) + (to[0] ? '/' + to[0] : '') + (all.length ? '?' + all.join('&') : '');
}

const TITLES = {
  hub: 'Overview', season: 'Standings', standings: 'Standings', games: 'Games', game: 'Game centre', team: 'Team', player: 'Player',
  players: 'Players', teams: 'Teams', value: 'Value & Moves', trade: 'Trade simulator', moves: 'Moves', fantasy: 'Fantasy', leaders: 'Leaders', awards: 'Awards', playoffs: 'Playoffs', lab: 'Lab',
  compare: 'Compare', 'compare-players': 'Compare players', 'compare-teams': 'Compare teams', model: 'Model',
  markets: 'Markets', calibration: 'Calibration', glossary: 'Glossary', methodology: 'Methodology', disclaimer: 'Disclaimer & terms'
};
/* Which kit section (QK.SECTIONS key) each route belongs to. */
const SECTION_OF = { hub: 'overview', season: 'standings', standings: 'standings', playoffs: 'standings', markets: 'standings',
  games: 'fixtures', game: 'fixtures', team: 'teams', teams: 'teams',
  player: 'players', players: 'players', leaders: 'players', awards: 'players',
  value: 'value', trade: 'value', moves: 'value', fantasy: 'fantasy',
  lab: 'lab', compare: 'lab', 'compare-players': 'lab', 'compare-teams': 'lab',
  model: 'model', calibration: 'model', glossary: 'model', methodology: 'model', disclaimer: 'model' };
const NAV_OF = SECTION_OF;
/* Route names the redesigned pages own: a legacy module's HW.route(name) registers a view (HW.view(name))
 * that a section page renders inside its tabs, not the route itself. */
const OWNED = { hub: 1, games: 1, game: 1, standings: 1, teams: 1, team: 1, players: 1, player: 1, value: 1, fantasy: 1,
  lab: 1, compare: 1, 'compare-players': 1, 'compare-teams': 1, model: 1, glossary: 1, methodology: 1, disclaimer: 1 };
const VIEWS = {};
// Where a page lands when the league is switched (id pages fall back to their list).
const SWITCH_TO = { game: 'games', team: 'teams', player: 'players', 'compare-players': 'compare', 'compare-teams': 'compare' };

function normPattern(s) {
  let p = String(s || '').trim().replace(/^#/, '').replace(/^\/+|\/+$/g, '').replace(/<(\w+)>/g, ':$1');
  p = p.replace(/^(:L|:league|nba|wnba)(\/|$)/, '');
  return p;
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
  VIEWS[key] = fn;
  if (OWNED[key]) return;
  HANDLERS[key] = fn;
  // A late registration for the page on screen renders it now.
  if (state.route === key || (state.route && !HANDLERS[state.route] && (routeEntry(state.route) || {}).fallbacks && routeEntry(state.route).fallbacks.indexOf(key) >= 0)) {
    if (booted) render();
  }
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
    try {
      query[decodeURIComponent(i >= 0 ? kv.slice(0, i) : kv)] = i >= 0 ? decodeURIComponent(kv.slice(i + 1)) : '';
    } catch (e) { /* malformed */ }
  });
  return query;
}

function parseHash(hash) {
  let h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  let query = {};
  const qi = h.indexOf('?');
  if (qi >= 0) { query = parseQuery(h.slice(qi + 1)); h = h.slice(0, qi); }
  let parts = h.split('/').filter(s => s !== '').map(s => { try { return decodeURIComponent(s); } catch (e) { return s; } });
  let league = null;
  if (parts.length && isLeague(parts[0].toLowerCase())) { league = parts[0].toLowerCase(); parts = parts.slice(1); }
  let best = null, bestLen = -1;
  ROUTES.forEach(r => {
    if (r.segs.length > parts.length) return;
    if (r.segs.length === 0 && parts.length > 0) return;
    for (let i = 0; i < r.segs.length; i++) {
      if (r.segs[i].charAt(0) !== ':' && r.segs[i] !== parts[i]) return;
    }
    const score = r.segs.length * 2 + (r.segs.length === parts.length ? 1 : 0);
    if (score > bestLen) { best = r; bestLen = score; }
  });
  const params = { league: league, rest: [], query: query };
  if (!best) return { name: 'notfound', params: Object.assign(params, { rest: parts }), parts: parts, league: league };
  Object.keys(best.defaults).forEach(k => { params[k] = best.defaults[k]; });
  best.segs.forEach((s, i) => { if (s.charAt(0) === ':') params[s.slice(1)] = parts[i]; });
  params.rest = parts.slice(best.segs.length);
  if (params.season !== undefined) { const y = parseInt(params.season, 10); params.season = isNaN(y) ? undefined : y; }
  if (params.season === undefined && query.s) { const y = parseInt(query.s, 10); if (!isNaN(y)) params.season = y; }
  return { name: best.name, params: params, parts: parts, league: league, global: best.global };
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

let booted = false, renderSeq = 0;
function render(opts) {
  const keep = !!(opts && opts.keep === true);
  const y0 = window.scrollY;
  const rd = redirectFor(location.hash);
  if (rd) { try { location.replace(rd); } catch (e) { location.hash = rd; } return; }
  runCleanups();
  const r = parseHash();
  const prevLeague = state.league, prevSeason = state.season;
  if (r.league) setLeagueState(r.league);
  r.params.league = state.league;
  const S = r.params.season && seasons(state.league).indexOf(r.params.season) >= 0 ? r.params.season
    : (r.params.season || currentSeason(state.league));
  r.params.season = S;
  state.season = S;
  state.route = r.name;
  state.params = r.params;
  state.hash = location.hash || '#/';
  if (prevLeague !== state.league || prevSeason !== state.season || !pickerFilled) fillSeasonPicker();
  updateHeader();
  markNav(NAV_OF[r.name] || '');
  const app = document.getElementById('app');
  if (!app) return;
  disposeCharts(app);
  app.innerHTML = '';
  const el = document.createElement('div');
  el.className = 'page page-' + r.name.replace(/[^a-z0-9-]/gi, '-') + ' league-' + state.league;
  app.appendChild(el);
  document.title = (r.name === 'hub' ? LEAGUE_NAME[state.league] + ' odds, models and analytics · ' : (TITLES[r.name] || 'Page') + (r.global ? '' : ' · ' + LEAGUE_NAME[state.league]) + ' · ') + 'The Quant Hardwood';
  setMeta('');
  if (!keep) window.scrollTo(0, 0);
  const fn = handlerFor(r.name);
  if (!fn) {
    el.innerHTML = r.name === 'notfound'
      ? comingHTML('Page not found', 'There is no page at <code>' + esc(location.hash) + '</code>. Try the overview or the search (press /).')
      : comingHTML((TITLES[r.name] || 'This page') + ' is coming', 'This part of The Quant Hardwood is still being built.');
    return;
  }
  const seq = ++renderSeq;
  try {
    const out = fn(el, r.params, state);
    if (out && typeof out.then === 'function') out.then(() => { if (keep && seq === renderSeq) window.scrollTo(0, y0); }, err => showError(el, err));
    else if (keep) window.scrollTo(0, y0);
  } catch (err) {
    showError(el, err);
  }
}

/* ECharts instances outlive their nodes (resize observers, progressive rendering): free them before a page goes. */
function disposeCharts(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll('.qk-chart').forEach(n => {
    const e = n.__qkc;
    if (!e) return;
    try { if (e.ro) e.ro.disconnect(); e.chart.dispose(); } catch (err) { /* gone */ }
    n.__qkc = null;
  });
}

function comingHTML(title, body) {
  return '<div class="card coming"><div class="pad"><div class="coming-title">' + esc(title) + '</div>' +
    '<p class="muted-inline">' + body + '</p><p><a href="' + href(state.league, '') + '">Back to the overview →</a></p></div></div>';
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
 * test it with HW.ok(d). */
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
/* Path of a per-league-season payload: path('season.json') -> 'nba/2027/season.json'. */
function path(file, L, S) {
  const l = isLeague(L) ? L : state.league;
  const s = S || (l === state.league ? state.season : null) || currentSeason(l);
  return l + '/' + s + '/' + file;
}
/* load(path(file, L, S)). */
function loadSeason(file, L, S) { return load(path(file, L, S)); }
/* Path of a per-league payload: lpath('history.json') -> 'nba/history.json'. */
function lpath(file, L) { return (isLeague(L) ? L : state.league) + '/' + file; }

/* Harvest names and colours from any payload that carries them. */
function learn(p, d) {
  if (!d || typeof d !== 'object') return;
  const m = /^(nba|wnba)\//.exec(p);
  const L = m ? m[1] : null;
  const putT = (l, id, info) => { if (!l || !id || !info) return; NAMES[l].teams[id] = Object.assign({}, NAMES[l].teams[id] || {}, info); };
  const putP = (l, id, info) => { if (!l || !id || !info) return; NAMES[l].players[id] = Object.assign({}, NAMES[l].players[id] || {}, info); };
  try {
    if (p === 'index.json' && d.leagues) {
      Object.keys(d.leagues).forEach(l => {
        if (!isLeague(l)) return;
        const t = d.leagues[l].teams || {};
        Object.keys(t).forEach(id => putT(l, id, pick(t[id], ['name', 'abbr', 'short', 'colour', 'alt_colour', 'conference', 'division', 'location'])));
      });
    }
    if (!L) return;
    if (/\/teams\.json$/.test(p) && d.teams && !Array.isArray(d.teams)) {
      Object.keys(d.teams).forEach(id => { const t = d.teams[id] || {}; if (t.name) putT(L, id, pick(t, ['name', 'abbr', 'colour'])); });
    }
    if (/\/players\.json$/.test(p) && d.players && !Array.isArray(d.players)) {
      Object.keys(d.players).forEach(id => { const x = d.players[id] || {}; if (x.name) putP(L, id, pick(x, ['name', 'short', 'team', 'pos'])); });
    }
    if (/\/players\/[^/]+\.json$/.test(p) && d.name) putP(L, String(d.id || p.split('/').pop().replace('.json', '')), pick(d, ['name', 'pos']));
    if (/\/games\/[^/]+\.json$/.test(p) && d.box) {
      Object.keys(d.box).forEach(tid => ((d.box[tid] || {}).players || []).forEach(x => {
        if (x.id && x.name && !(NAMES[L].players[x.id] || {}).name) putP(L, String(x.id), { name: x.name, team: tid, pos: x.pos });
      }));
    }
    if (/\/lab\.json$/.test(p) && Array.isArray(d.fields) && Array.isArray(d.rows)) {
      const ii = d.fields.indexOf('id'), ni = d.fields.indexOf('name'), ti = d.fields.indexOf('team');
      if (ii >= 0 && ni >= 0) d.rows.forEach(r => { if (r[ii] && r[ni] && !(NAMES[L].players[r[ii]] || {}).name) putP(L, String(r[ii]), { name: r[ni], team: ti >= 0 ? r[ti] : undefined }); });
    }
    if (/\/awards\.json$/.test(p) && Array.isArray(d.keys)) {
      d.keys.forEach(k => { const f = (d[k] || {}).features || {}; Object.keys(f).forEach(id => { const x = f[id] || {}; if (x.name && !(NAMES[L].players[id] || {}).name) putP(L, id, pick(x, ['name', 'team'])); }); });
    }
    // {cols, rows} payloads with ids and names (valuation, value, trade, fantasy): current rosters
    const tab = Array.isArray(d.cols) ? d : (d.players && Array.isArray(d.players.cols) ? d.players : null);
    if (tab && Array.isArray(tab.rows)) {
      const ii = tab.cols.indexOf('id'), ni = tab.cols.indexOf('name'), ti = tab.cols.indexOf('team'), pi = tab.cols.indexOf('pos');
      if (ii >= 0 && ni >= 0) tab.rows.forEach(r => {
        const id = String(r[ii]); const cur = NAMES[L].players[id] || {};
        if (!r[ni]) return;
        const info = { name: cur.name || r[ni] };
        if (!cur.team && ti >= 0 && r[ti]) info.team = String(r[ti]);
        if (!cur.pos && pi >= 0 && r[pi]) info.pos = r[pi];
        putP(L, id, info);
      });
    }
    if (d.names && typeof d.names === 'object' && !Array.isArray(d.names)) {
      Object.keys(d.names).forEach(id => { const n = d.names[id]; if (typeof n === 'string' && !(NAMES[L].players[id] || {}).name) putP(L, id, { name: n }); });
    }
  } catch (e) { console.warn('learn failed for', p, e); }
}
function pick(o, keys) { const out = {}; keys.forEach(k => { if (o && o[k] !== undefined && o[k] !== null) out[k] = o[k]; }); return out; }

// ── formatting ─────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v); }
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
/* Percentage-point difference of two probabilities: pp(0.55, 0.50) -> "+5.0 pp". */
function pp(a, b, d) { return isNum(a) && isNum(b) ? signed((a - b) * 100, d === undefined ? 1 : d) + ' pp' : '—'; }
/* fmtSec(754) -> "12:34"; over an hour "1:02:03". */
function fmtSec(s) {
  if (!isNum(s)) return '—';
  let t = Math.round(Math.abs(Number(s)));
  const h = Math.floor(t / 3600); t -= h * 3600;
  const m = Math.floor(t / 60); t -= m * 60;
  const p2 = n => (n < 10 ? '0' : '') + n;
  return (s < 0 ? '-' : '') + (h ? h + ':' + p2(m) : m) + ':' + p2(t);
}
/* Minutes as m:ss: fmtMin(31.5) -> "31:30". */
function fmtMin(m) { return isNum(m) ? fmtSec(Number(m) * 60) : '—'; }
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  let str = String(s);
  if (/^\d{8}$/.test(str)) str = str.slice(0, 4) + '-' + str.slice(4, 6) + '-' + str.slice(6);
  const d = new Date(str.length === 10 ? str + 'T12:00:00Z' : str);
  return isNaN(d.getTime()) ? null : d;
}
/* fmtDate("2026-10-20") -> "Tue 20 Oct 2026" in the viewer's timezone.
 * opts: {year: false} drops the year, {year: 'auto'} keeps it only outside the current year, {time: true} adds
 * HH:MM, {weekday: false}. */
function fmtDate(s, opts) {
  const o = typeof opts === 'boolean' ? { year: opts } : (opts || {});
  const d = parseDate(s);
  if (!d) return '—';
  const showYear = o.year === 'auto' ? d.getFullYear() !== new Date().getFullYear() : o.year !== false;
  let out = (o.weekday === false ? '' : DAYS[d.getDay()] + ' ') + d.getDate() + ' ' + MONTHS[d.getMonth()] + (showYear ? ' ' + d.getFullYear() : '');
  if (o.time && String(s).length > 10) out += ' ' + fmtTime(s);
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
/* The viewer's local calendar day of an ISO time, as YYYY-MM-DD. */
function localDay(s) {
  const d = parseDate(s);
  if (!d) return '';
  if (String(s).length === 10) return String(s);
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
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
/* Format a catalogue value by its METRIC fmt: 'int', '0', '1', '2', '3', 'pct' (a 0-1 rate shown as 54.3%;
 * a value above 1.5 is taken as already in percent), 'pm' (signed, 1 dp), 'sec' (m:ss), 'prob', 'signed'. */
function fmtVal(v, fmt) {
  if (!isNum(v)) return '—';
  const x = Number(v);
  switch (String(fmt)) {
    case 'pct': return (Math.abs(x) <= 1.5 ? x * 100 : x).toFixed(1) + '%';
    case 'prob': return pct(x);
    case 'int': return String(Math.round(x));
    case 'pm': return signed(x, 1);
    case 'signed': return signed(x, 2);
    case 'sec': return fmtSec(x);
    case 'min': return fmtMin(x);
    case '0': return x.toFixed(0);
    case '1': return x.toFixed(1);
    case '3': return x.toFixed(3).replace(/^0\./, '.').replace(/^-0\./, '-.');
    default: return x.toFixed(2);
  }
}
/* Find a METRIC {key,label,fmt,...} in a list by key. */
function metric(list, key) { return (list || []).find(m => m && m.key === key) || null; }
/* Record "w-l". */
function record(w, l) { return isNum(w) && isNum(l) ? Math.round(w) + '-' + Math.round(l) : '—'; }
/* A spread from the home side: fmtSpread(-3.5) -> "-3.5", 0 -> "PK". */
function fmtSpread(v) { if (!isNum(v)) return '—'; const x = Math.round(Number(v) * 2) / 2; return x === 0 ? 'PK' : signed(x, 1).replace(/\.0$/, ''); }
/* Fair American odds of a probability: 0.6 -> "-150", 0.4 -> "+150". */
function american(p) {
  if (!isNum(p) || p <= 0 || p >= 1) return '—';
  return p >= 0.5 ? '-' + Math.round(100 * p / (1 - p)) : '+' + Math.round(100 * (1 - p) / p);
}
/* Fair decimal odds: 0.4 -> "2.50". */
function decimal(p) { return isNum(p) && p > 0 ? (1 / p).toFixed(p > 0.1 ? 2 : 1) : '—'; }

// ── leagues and seasons ────────────────────────────────────────────────────

function leagueInfo(L) {
  const l = isLeague(L) ? L : state.league;
  const d = INDEX.data;
  return (d && d.leagues && d.leagues[l]) || {};
}
function defaultSeason(L) {
  const now = new Date();
  const y = now.getFullYear();
  return L === 'nba' ? (now.getMonth() >= 7 ? y + 1 : y) : (now.getMonth() >= 2 ? y : y - 1);
}
function currentSeason(L) {
  const l = isLeague(L) ? L : state.league;
  const i = leagueInfo(l);
  return i.current_season ? Number(i.current_season) : defaultSeason(l);
}
function seasons(L) {
  const l = isLeague(L) ? L : state.league;
  const i = leagueInfo(l);
  const list = (i.seasons && i.seasons.length ? i.seasons.map(Number) : [currentSeason(l)]).slice();
  if (list.indexOf(currentSeason(l)) < 0) list.push(currentSeason(l));
  return list.sort((a, b) => b - a);
}
/* "2026-27" for the NBA (S = 2027), "2026" for the WNBA. */
function seasonLabel(L, S) {
  const l = isLeague(L) ? L : state.league;
  const s = Number(S === undefined ? (isLeague(L) ? state.season : L) : S);
  if (!isNum(s)) return '—';
  return l === 'nba' ? (s - 1) + '-' + String(s).slice(2) : String(s);
}
function leagueName(L) { return LEAGUE_NAME[isLeague(L) ? L : state.league]; }
function phase(L) { return leagueInfo(L).phase || null; }

// ── names, colours, links ──────────────────────────────────────────────────

/* Normalise (L, id, ...rest) when the league was left out: (id, ...rest). */
function args(a) {
  const list = Array.prototype.slice.call(a);
  if (isLeague(list[0])) return list;
  return [state.league].concat(list);
}
function titleCase(id) {
  return String(id || '').split(/[_\s-]+/).filter(Boolean).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}
function team(L, id) { const a = args(arguments); return NAMES[a[0]].teams[String(a[1])] || {}; }
function teamName(L, id) { const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])]; return x && x.name ? x.name : (a[1] ? 'Team ' + a[1] : '—'); }
function teamAbbr(L, id) {
  const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])];
  if (x && x.abbr) return x.abbr;
  const n = teamName(a[0], a[1]); return n.replace(/[^A-Za-z]/g, '').slice(0, 3).toUpperCase();
}
/* Short team name: "Celtics" from "Boston Celtics" unless the payload gives one. */
function teamShort(L, id) {
  const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])] || {};
  if (x.short) return x.short;
  if (x.name && x.location && x.name.indexOf(x.location) === 0) return x.name.slice(x.location.length).trim() || x.name;
  return x.name ? x.name.split(' ').slice(-1)[0] : teamAbbr(a[0], a[1]);
}
function playerName(L, id) { const a = args(arguments); const x = NAMES[a[0]].players[String(a[1])]; return x && x.name ? x.name : (a[1] ? 'Player ' + a[1] : '—'); }
function playerShort(L, id) {
  const a = args(arguments); const x = NAMES[a[0]].players[String(a[1])] || {};
  if (x.short) return x.short;
  const n = playerName(a[0], a[1]).split(' ');
  return n.length > 1 ? n[0].charAt(0) + '. ' + n.slice(1).join(' ') : n[0];
}
function hashIndex(s, n) { let h = 0; String(s).split('').forEach(ch => { h = (h * 31 + ch.charCodeAt(0)) >>> 0; }); return h % n; }
function hexOf(c) { const s = String(c || ''); return s ? (s.charAt(0) === '#' ? s : '#' + s) : ''; }
function luminance(hex) {
  const h = hexOf(hex).slice(1);
  if (h.length !== 6) return 0.5;
  const v = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
/* The team's colour (ESPN primary via the payloads); swaps to the alternate when the
 * primary is too dark to read on the dark theme; else a stable palette pick. */
function teamColour(L, id) {
  const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])];
  if (x && x.colour) {
    const c = hexOf(x.colour);
    // The kit raises a dark kit colour in HSL until it clears 3:1 on the card (both themes).
    if (window.QK && QK.color && QK.color.parse(c)) {
      const alt = hexOf(x.alt_colour);
      const dark = QK.theme.get() === 'dark';
      if (dark && luminance(c) < 0.06 && QK.color.parse(alt) && luminance(alt) > 0.12 && luminance(alt) < 0.8) return QK.color.team(alt);
      return QK.color.team(c);
    }
    if (luminance(c) < 0.18 && x.alt_colour && luminance(hexOf(x.alt_colour)) > luminance(c)) return hexOf(x.alt_colour);
    return luminance(c) < 0.08 ? '#9aa4b2' : c;
  }
  return a[1] ? PALETTE[hashIndex(a[1], PALETTE.length)] : C.text3;
}
/* The team's own primary colour, unadjusted (for kit marks, which adjust it themselves). */
function teamColourRaw(L, id) { const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])]; return x && x.colour ? hexOf(x.colour) : ''; }
function teamAlt(L, id) { const a = args(arguments); const x = NAMES[a[0]].teams[String(a[1])]; return x && x.alt_colour ? hexOf(x.alt_colour) : ''; }
function teamBar(L, id) { const a = args(arguments); return '<span class="team-bar" style="background:' + esc(teamColour(a[0], a[1])) + '"></span>'; }
/* '?s=S' when S is not the league's current season, else ''. */
function sq(L, S) {
  const l = isLeague(L) ? L : state.league;
  const s = S || (l === state.league ? state.season : null);
  return s && Number(s) !== currentSeason(l) ? '?s=' + s : '';
}
/* '#/<L>/<sub>' plus the season query: href('nba', 'players') -> '#/nba/players'. */
function href(L, sub, S) {
  const l = isLeague(L) ? L : state.league;
  const s = String(sub || '').replace(/^\/+/, '');
  return '#/' + l + (s ? '/' + s : '') + (s ? sq(l, S) : '');
}
function seasonHref(L, S) { const l = isLeague(L) ? L : state.league; const s = S || (l === state.league ? state.season : currentSeason(l)); return '#/' + l + '/standings' + (s && Number(s) !== currentSeason(l) ? '?s=' + s : ''); }
function teamHref(L, id, S) { const a = args(arguments); return href(a[0], 'team/' + encodeURIComponent(a[1]), a[2]); }
function playerHref(L, id, S) { const a = args(arguments); return href(a[0], 'player/' + encodeURIComponent(a[1]), a[2]); }
function gameHref(L, id, S) { const a = args(arguments); return href(a[0], 'game/' + encodeURIComponent(a[1]), a[2]); }
/* <a> to the team page. opts {name, abbr: true, short: true, bar: false, season} or a name string. */
function teamLink(L, id, opts) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  const o = typeof a[2] === 'string' ? { name: a[2] } : (a[2] || {});
  const label = o.name || (o.abbr ? teamAbbr(a[0], a[1]) : o.short ? teamShort(a[0], a[1]) : teamName(a[0], a[1]));
  return '<a class="team-link" href="' + teamHref(a[0], a[1], o.season) + '">' + (o.bar === false ? '' : teamBar(a[0], a[1])) + esc(label) + '</a>';
}
/* <a> to the player page. opts {name, short: true, team (colour bar), season} or a name string. */
function playerLink(L, id, opts) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  const o = typeof a[2] === 'string' ? { name: a[2] } : (a[2] || {});
  const label = o.name || (o.short ? playerShort(a[0], a[1]) : playerName(a[0], a[1]));
  return '<a class="ply-link" href="' + playerHref(a[0], a[1], o.season) + '">' + (o.team ? teamBar(a[0], o.team) : '') + esc(label) + '</a>';
}
/* <a> to the game centre; label defaults to "AWY @ HOM" when names are known. */
function gameLink(L, id, label, S) {
  const a = args(arguments);
  if (!a[1]) return '<span class="muted-inline">—</span>';
  return '<a class="game-link" href="' + gameHref(a[0], a[1], a[3]) + '">' + esc(a[2] || 'Game centre') + '</a>';
}

// ── games ──────────────────────────────────────────────────────────────────

/* Status of a GAME_CARD / game payload: 'pre' | 'in' | 'post' | other (postponed, canceled). */
function gameState(g) {
  const s = String((g && g.status) || '').toLowerCase();
  if (s === 'in' || s === 'live' || s === 'halftime' || s === 'end_period') return 'in';
  if (s === 'post' || s === 'final') return 'post';
  if (s === 'pre' || s === 'scheduled' || !s) return 'pre';
  return s;
}
function periodLabel(L, p) {
  const n = Number(p);
  if (!isNum(n) || n <= 0) return '';
  return n <= 4 ? 'Q' + n : (n === 5 ? 'OT' : (n - 4) + 'OT');
}
/* A status chip: tip-off time, live period and clock, Final (OT). */
function statusChip(g, L) {
  const st = gameState(g);
  if (st === 'in') return '<span class="chip st-live"><span class="live-dot"></span> ' + esc(periodLabel(L, g.period)) + (g.clock ? ' ' + esc(g.clock) : '') + '</span>';
  if (st === 'post') return '<span class="chip st-ft">Final' + (Number(g.period) > 4 ? ' (' + esc(periodLabel(L, g.period)) + ')' : '') + '</span>';
  if (st === 'pre') return '<span class="chip st-time">' + esc(fmtTime(g.date) || 'TBD') + '</span>';
  return '<span class="chip warn">' + esc(titleCase(st)) + '</span>';
}
/* A GAME_CARD tile (index.json today/next_games/last_games, or any object with the same fields).
 * opts {league, season, compact, date: true (show the date instead of the time)}. The whole tile links to the game. */
function gameCard(g, opts) {
  const o = opts || {};
  const L = o.league || state.league;
  if (!g) return '';
  const st = gameState(g);
  const m = g.model || {}, mk = g.market || null;
  const pH = isNum(m.p_home) ? Number(m.p_home) : null;
  const live = st === 'in', done = st === 'post';
  const hs = isNum(g.hs) ? g.hs : null, as = isNum(g.as) ? g.as : null;
  const winH = done && hs !== null && as !== null && hs > as, winA = done && hs !== null && as !== null && as > hs;
  const row = (tid, score, p, win, isHome) =>
    '<div class="gc-team' + (win ? ' gc-win' : '') + '">' + teamBar(L, tid) +
    '<span class="gc-name"><span class="gc-abbr">' + esc(teamAbbr(L, tid)) + '</span> <span class="gc-full">' + esc(teamShort(L, tid)) + '</span></span>' +
    (st === 'pre' || !isNum(score) ? '' : '<span class="gc-score">' + esc(score) + '</span>') +
    '<span class="gc-p" title="' + (isHome ? 'Model home win probability' : 'Model away win probability') + '">' + (p === null ? '' : pct(p, 0)) + '</span></div>';
  let top = statusChip(g, L);
  if (o.date) top = '<span class="gc-date">' + esc(fmtDate(g.date, { year: false })) + '</span> ' + top;
  const tag = g.series && (g.series.summary || g.series.round) ? esc(g.series.summary || g.series.round) : (g.stype && g.stype !== 'reg' ? esc(stypeLabel(g.stype)) : '');
  const modelSpread = isNum(m.margin) ? -Number(m.margin) : null;
  const lines = [];
  if (isNum(pH) || isNum(modelSpread) || isNum(m.total)) {
    lines.push('<span class="gc-l"><b>Model</b> ' + esc(teamAbbr(L, g.home)) + ' ' + fmtSpread(modelSpread) + (isNum(m.total) ? ' · O/U ' + num(m.total, 1) : '') + '</span>');
  }
  if (mk && (isNum(mk.p_home) || isNum(mk.spread_home) || isNum(mk.total))) {
    lines.push('<span class="gc-l"><b>Market</b> ' + (isNum(mk.spread_home) ? esc(teamAbbr(L, g.home)) + ' ' + fmtSpread(mk.spread_home) : '') +
      (isNum(mk.total) ? ' · O/U ' + num(mk.total, 1) : '') + (isNum(mk.p_home) ? ' · ' + pct(mk.p_home, 0) : '') +
      (isNum(mk.p_home) && isNum(pH) ? ' (' + edgeHTML(pH, mk.p_home, 0) + ')' : '') + '</span>');
  }
  if (live && (isNum(g.wp_home) || isNum(g.espn_wp))) {
    lines.push('<span class="gc-l gc-wp"><b>Live WP</b> ' + esc(teamAbbr(L, g.home)) + ' ' + pct(g.wp_home, 0) + (isNum(g.espn_wp) ? ' · ESPN ' + pct(g.espn_wp, 0) : '') + '</span>');
  }
  return '<a class="gc' + (live ? ' gc-live' : '') + (o.compact ? ' gc-compact' : '') + '" href="' + gameHref(L, g.id, o.season) + '">' +
    '<div class="gc-top">' + top + (tag ? '<span class="gc-tag">' + tag + '</span>' : '') + '</div>' +
    row(g.away, as, pH === null ? null : 1 - pH, winA, false) + row(g.home, hs, pH, winH, true) +
    (lines.length ? '<div class="gc-lines">' + lines.join('') + '</div>' : '') + '</a>';
}
/* season.json "sim" per team: {tid: {exp_w, seed_dist, p_playoffs, ...}} whether the builder nests it under
 * "teams" or writes the teams at the top level next to "n_sims". */
function simTeams(season) {
  const s = season && season.sim;
  if (!s || typeof s !== 'object') return {};
  if (s.teams && typeof s.teams === 'object' && !Array.isArray(s.teams)) return s.teams;
  const out = {};
  Object.keys(s).forEach(k => { const v = s[k]; if (v && typeof v === 'object' && !Array.isArray(v) && (isNum(v.exp_w) || isNum(v.p_title) || v.seed_dist)) out[k] = v; });
  return out;
}
/* A market TITLE dict -> {id: p} (de-vigged "probs", else the raw "mid"); {} when unavailable. */
function titleProbs(t) {
  if (!t || t.available === false) return {};
  return t.probs || t.mid || {};
}
const STYPE = { pre: 'Preseason', reg: 'Regular season', post: 'Playoffs', playin: 'Play-in', cup: 'NBA Cup', allstar: 'All-Star' };
function stypeLabel(s) { return STYPE[s] || titleCase(s || ''); }

// ── HTML builders ──────────────────────────────────────────────────────────

/* A card: header with a title and a muted sub-line, then the body. */
function card(title, sub, bodyHtml, id) {
  return '<div class="card"' + (id ? ' id="' + esc(id) + '"' : '') + '>' +
    (title ? '<div class="card-header">' + esc(title) + (sub ? ' <span class="card-sub">' + sub + '</span>' : '') + '</div>' : '') +
    (bodyHtml || '') + '</div>';
}
function muted(text) { return '<div class="muted">' + text + '</div>'; }
function chip(text, cls) { return '<span class="chip' + (cls ? ' ' + cls : '') + '">' + esc(text) + '</span>'; }
/* A muted note for a payload that is missing or written with ok: false. */
function notBuilt(what, d) { return muted(esc(what) + ' is not available yet' + (d && d.reason ? ' (' + esc(d.reason) + ')' : '') + '.'); }

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
/* Model minus market in percentage points, coloured (green = model higher). '' when either is missing. */
function edgeHTML(model, market, d) {
  if (!isNum(model) || !isNum(market)) return '<span class="muted-inline">—</span>';
  const e = (model - market) * 100;
  return '<span class="' + (e > 0.05 ? 'edge-pos' : e < -0.05 ? 'edge-neg' : 'muted-inline') + '">' + signed(e, d === undefined ? 1 : d) + '</span>';
}
/* Diverging colour for v in [-max, max]: negative green (good when lower = better), positive red. */
function divColour(v, max, invert) {
  if (!isNum(v) || !max) return 'transparent';
  let t = Math.max(-1, Math.min(1, v / max));
  if (invert) t = -t;
  const a = Math.abs(t);
  return t < 0 ? 'rgba(63,185,80,' + (0.12 + 0.6 * a).toFixed(3) + ')' : 'rgba(248,81,73,' + (0.12 + 0.6 * a).toFixed(3) + ')';
}
/* Sequential colour for t in [0,1] (the hardwood orange). */
function seqColour(t) {
  if (!isNum(t)) return 'transparent';
  const u = Math.max(0, Math.min(1, t));
  return 'rgba(240,136,62,' + (0.06 + 0.8 * u).toFixed(3) + ')';
}
/* A row of segment buttons; returns HTML. items [{key,label}], active key, data attribute name. */
function toggles(items, active, attr) {
  const a = attr || 'data-k';
  return items.map(it => '<button type="button" class="tbtn' + (String(it.key) === String(active) ? ' active' : '') + '" ' + a + '="' + esc(it.key) + '">' + esc(it.label) + '</button>').join('');
}
/* Wire toggle buttons under root (by attr) to fn(key); marks the active one. */
function wireToggles(root, attr, fn) {
  if (!root) return;
  const a = attr || 'data-k';
  root.querySelectorAll('[' + a + ']').forEach(b => b.addEventListener('click', () => {
    root.querySelectorAll('[' + a + ']').forEach(x => x.classList.toggle('active', x === b));
    fn(b.getAttribute(a));
  }));
}
/* The page head: a title, a sub-line (HTML) and optional right-side links (HTML). */
function pageHead(title, sub, right) {
  return '<div class="page-head"><div><h2>' + esc(title) + '</h2>' + (sub ? '<div class="ph-sub muted-inline">' + sub + '</div>' : '') + '</div>' +
    (right ? '<div class="ph-nav">' + right + '</div>' : '') + '</div>';
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
/* A pre-redesign chart written against Plotly loads the kit's Plotly-on-ECharts module on first use (the
 * Plotly CDN bundle is no longer used; the redesigned pages draw with QKC directly). */
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
/* Plotly.on() exists only once the chart is drawn; legacy code wires clicks right after plot(). */
function drawPlot(node, traces, lay, conf) {
  try {
    const p = Plotly.newPlot(node, traces, lay && lay.paper_bgcolor !== undefined ? lay : layout(lay), Object.assign({}, PLOTLY_CONF, conf || {}));
    onLeave(() => { try { Plotly.purge(node); } catch (e) { /* gone */ } });
    if (p && p.then) p.then(() => { (node.__hwOn || []).forEach(x => node.on(x[0], x[1])); node.__hwOn = null; });
    return p;
  } catch (err) {
    console.warn('chart failed', err);
    node.innerHTML = '<div class="muted">The chart could not be drawn.</div>';
    return null;
  }
}
/* Draw a Plotly chart into el (element or id); the library loads on first use. */
function plot(el, traces, lay, conf) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  if (typeof Plotly !== 'undefined') return drawPlot(node, traces, lay, conf);
  // Until Plotly is here, node.on(ev, fn) is queued and bound once the chart exists.
  if (!node.on) node.on = (ev, fn) => { (node.__hwOn || (node.__hwOn = [])).push([ev, fn]); };
  node.classList.add('hw-plot-wait');
  const route0 = state.hash;
  return loadPlotly().then(ok => {
    node.classList.remove('hw-plot-wait');
    if (!node.isConnected || state.hash !== route0) return null;
    if (!ok) { node.innerHTML = '<div class="muted">The chart library did not load. The tables carry the same data.</div>'; return null; }
    const queued = node.__hwOn || [];
    try { delete node.on; } catch (e) { node.on = undefined; }
    node.__hwOn = queued;
    return drawPlot(node, traces, lay, conf);
  });
}
/* The legacy colour constants and the Plotly layout follow the kit's tokens (dark or light). */
function retheme() {
  if (!window.QKC) return;
  const T = QKC.tokens();
  C.bg = T.bg; C.bg2 = T.s1; C.bg3 = T.s2; C.border = T.s4;
  C.text = T.ink1; C.text2 = T.ink2; C.text3 = T.ink3;
  C.blue = T.model; C.orange = T.market; C.green = T.up; C.red = T.down;
  DARK_LAYOUT.font = { color: T.ink2, family: T.fontUI, size: 11 };
  DARK_LAYOUT.xaxis = { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } };
  DARK_LAYOUT.yaxis = { gridcolor: T.grid, zerolinecolor: T.axis, linecolor: T.axis, tickfont: { family: T.fontNum, color: T.ink3 } };
  DARK_LAYOUT.hoverlabel = { bgcolor: T.s4, bordercolor: T.line2, font: { color: T.ink1, size: 12, family: T.fontUI } };
}

// ── header: the kit shell, league switch, season picker, section nav, meta, search ─────────

let SHELL = null;
function setLeagueState(L) {
  if (!isLeague(L)) return;
  state.league = L;
  try { window.localStorage.setItem(LS_LEAGUE, L); } catch (e) { /* private mode */ }
}
/* Switch league, keeping the page type (and the section tab) where the other league has it. */
function switchLeague(L) {
  if (!isLeague(L)) return;
  const r = state.route || 'hub';
  let to = SWITCH_TO[r] || r;
  const e = routeEntry(to);
  if (to === 'notfound' || !e) to = 'hub';
  if ((routeEntry(to) || {}).global) {
    setLeagueState(L);
    const h = String(location.hash || '#/').replace(/^#\/(nba|wnba)\//, '#/');
    if (h !== location.hash) go(h); else render();
    return;
  }
  const tab = ((state.params || {}).query || {}).tab;
  const keepTab = tab && ['standings', 'players', 'value', 'fantasy', 'lab', 'model', 'teams', 'games'].indexOf(to) >= 0 ? '?tab=' + encodeURIComponent(tab) : '';
  if (to === 'hub') go('#/' + L);
  else go('#/' + L + '/' + routeEntry(to).pattern.replace(/\/:.*$/, '') + keepTab);
}
/* Change the season shown, keeping the page where it makes sense. */
function setSeason(S) {
  const s = parseInt(S, 10);
  if (isNaN(s)) return;
  const L = state.league, r = state.route || 'hub';
  if (r === 'game') { go(href(L, 'games', s)); return; }
  if ((routeEntry(r) || {}).global) { state.season = s; return; }
  const h = String(location.hash || '').replace(/\?.*$/, '') || '#/' + L;
  const q = Object.assign({}, state.params.query || {});
  if (s === currentSeason(L)) delete q.s; else q.s = String(s);
  const qs = Object.keys(q).map(k => encodeURIComponent(k) + '=' + encodeURIComponent(q[k])).join('&');
  go(h + (qs ? '?' + qs : ''));
}
let pickerFilled = false;
function fillSeasonPicker() {
  const sel = document.getElementById('season-select');
  if (!sel) return;
  const L = state.league;
  const list = seasons(L);
  if (state.season && list.indexOf(state.season) < 0) list.unshift(state.season);
  sel.innerHTML = list.map(y => '<option value="' + y + '">' + esc(seasonLabel(L, y)) + '</option>').join('');
  sel.value = String(state.season || currentSeason(L));
  pickerFilled = true;
}
/* Section hrefs carry the league (and the season when it is not the current one). */
function sectionHref(key, L, S) {
  const sub = { overview: '', fixtures: 'games', standings: 'standings', teams: 'teams', players: 'players', value: 'value', fantasy: 'fantasy', lab: 'lab', model: 'model' }[key];
  if (key === 'overview') return '#/' + L + (S && Number(S) !== currentSeason(L) ? '?s=' + S : '');
  if (key === 'fantasy' || key === 'model') return '#/' + L + '/' + sub;
  return href(L, sub, S);
}
function updateHeader() {
  const L = state.league, S = state.season;
  document.querySelectorAll('.qk-secnav a[data-sec]').forEach(a => a.setAttribute('href', sectionHref(a.getAttribute('data-sec'), L, S)));
  document.querySelectorAll('[data-league-btn]').forEach(b => b.setAttribute('aria-pressed', b.getAttribute('data-league-btn') === L ? 'true' : 'false'));
  const brand = document.querySelector('.qk-brand-name b');
  if (brand) brand.textContent = 'Hardwood';
}
function markNav(key) {
  if (SHELL) SHELL.setSection(key);
}
function setMeta(html) {
  const el = document.getElementById('meta-line');
  if (!el) return;
  const d = INDEX.data;
  const ph = (state.season || currentSeason(state.league)) === currentSeason(state.league) ? phase(state.league) : null;
  const base = [LEAGUE_NAME[state.league] + ' ' + seasonLabel(state.league, state.season || currentSeason(state.league)) + (ph ? ' · ' + titleCase(ph) : ''),
    d && d.updated_at ? 'Data updated ' + esc(fmtStamp(d.updated_at)) : ''].filter(Boolean).join(' · ');
  el.innerHTML = [html, base].filter(Boolean).join(' · ');
}

/* Search rows for the kit's command palette: both leagues' teams and current players (by minutes). */
const SEARCH = {};
function loadSearch(L0, S0) {
  const L = L0 || state.league, S = S0 || currentSeason(L);
  const key = L + '/' + S;
  if (SEARCH[key]) return SEARCH[key];
  SEARCH[key] = loadAll([path('players.json', L, S), L + '/' + S + '/valuation.json']).then(arr => {
    const items = [], seen = {};
    const add = (kind, id, label, sub, h, tid, w) => {
      const k = kind + ':' + id;
      if (seen[k]) return; seen[k] = 1;
      items.push({ kind: kind, id: id, label: label, sub: sub, href: h, team: tid, w: w || 0 });
    };
    const teams = NAMES[L].teams;
    Object.keys(teams).forEach(id => { const t = teams[id]; add('Teams', id, t.name || teamName(L, id), [t.abbr, t.conference].filter(Boolean).join(' · '), teamHref(L, id, S), id, 1e6); });
    // current rosters first (valuation.json is built from the latest rosters), then everyone in the catalogue
    const v = arr[1];
    if (v && v.ok !== false && Array.isArray(v.cols)) {
      const c = v.cols, ix = n => c.indexOf(n);
      (v.rows || []).forEach(r => add('Players', String(r[ix('id')]), r[ix('name')], [r[ix('pos')], r[ix('team')] ? teamAbbr(L, r[ix('team')]) : 'free agent'].filter(Boolean).join(' · '), playerHref(L, r[ix('id')], S), r[ix('team')], 1000 + (Number(r[ix('mpg')]) || 0)));
    }
    const pl = (arr[0] && arr[0].players) || {};
    Object.keys(pl).forEach(id => {
      const x = pl[id] || {};
      add('Players', id, x.name || playerName(L, id), [x.pos, x.team ? teamAbbr(L, x.team) : ''].filter(Boolean).join(' · '), playerHref(L, id, S), x.team, (x.min || 0) / 100);
    });
    items.sort((a, b) => b.w - a.w);
    return items;
  });
  return SEARCH[key];
}
function closeSearch() { /* the kit's palette closes itself on navigation */ }

function leagueSeg() {
  return '<div class="qk-seg hw-league" role="group" aria-label="League">' + LEAGUES.map(l =>
    '<button type="button" data-league-btn="' + l + '" aria-pressed="' + (l === state.league ? 'true' : 'false') + '">' + LEAGUE_NAME[l] + '</button>').join('') + '</div>';
}
function initHeader() {
  if (window.QK) {
    SHELL = QK.shell({
      sport: 'basketball', section: 'overview',
      sections: QK.sections('basketball').map(s => { s.href = sectionHref(s.key, state.league, null); return s; }),
      ctx: leagueSeg() + '<label class="qk-sr" for="season-select">Season</label><select id="season-select" class="qk-select hw-season" aria-label="Season"></select>',
      search: {
        load: () => Promise.all(LEAGUES.map(l => loadSearch(l, currentSeason(l)))).then(lists => {
          // the league on screen first
          const order = lists.map((x, i) => ({ l: LEAGUES[i], x: x })).sort((a, b) => (a.l === state.league ? -1 : 0) - (b.l === state.league ? -1 : 0));
          const out = [];
          order.forEach(o => o.x.forEach(it => out.push({ sport: 'basketball', t: it.label, s: LEAGUE_NAME[o.l] + ' · ' + (it.kind === 'Teams' ? 'Team' : '') + (it.kind === 'Teams' && it.sub ? ' · ' : '') + (it.sub || ''), href: it.href })));
          return out;
        })
      }
    });
    retheme();
    QK.theme.onChange(() => {
      setTimeout(() => {
        retheme();
        const app = document.getElementById('app');
        // legacy Plotly charts and team-coloured legacy HTML are painted once: draw the page again
        if (app && app.querySelector('.js-plotly-plot, .team-bar, .hw-legacy')) render({ keep: true });
      }, 40);
    });
    document.querySelectorAll('[data-league-btn]').forEach(b => b.addEventListener('click', () => switchLeague(b.getAttribute('data-league-btn'))));
  }
  const sel = document.getElementById('season-select');
  if (sel) sel.addEventListener('change', () => setSeason(sel.value));
}
function initSearch() { /* the kit shell owns search */ }

function init() {
  load('index.json').then(idx => {
    INDEX.data = idx;
    initHeader();
    initSearch();
    const ov = document.getElementById('loading-overlay');
    if (ov) ov.style.display = 'none';
    booted = true;
    window.addEventListener('hashchange', () => render());
    render();
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else setTimeout(init, 0);

return {
  // state and routing
  state: state, route: route, page: page, view: view, VIEWS: VIEWS, SECTION_OF: SECTION_OF, redirectFor: redirectFor, go: go,
  loadPlotly: loadPlotly, retheme: retheme, loadSearch: loadSearch, teamColourRaw: teamColourRaw, teamAlt: teamAlt, routeEntry: routeEntry, parseHash: parseHash, onLeave: onLeave, interval: interval, render: render,
  ROUTES: ROUTES, HANDLERS: HANDLERS, TITLES: TITLES, LEAGUES: LEAGUES, LEAGUE_NAME: LEAGUE_NAME,
  switchLeague: switchLeague, setSeason: setSeason, setMeta: setMeta,
  // data
  load: load, loadAll: loadAll, ok: ok, reason: reason, cached: cached, path: path, lpath: lpath, loadSeason: loadSeason,
  index: () => INDEX.data, leagueInfo: leagueInfo, currentSeason: currentSeason, seasons: seasons, seasonLabel: seasonLabel,
  leagueName: leagueName, phase: phase, isLeague: isLeague, NAMES: NAMES,
  // formatting
  esc: esc, num: num, pct: pct, signed: signed, pp: pp, fmtSec: fmtSec, fmtMin: fmtMin, fmtDate: fmtDate, fmtTime: fmtTime,
  fmtStamp: fmtStamp, localDay: localDay, countdown: countdown, ordinal: ordinal, fmtVal: fmtVal, metric: metric, record: record,
  fmtSpread: fmtSpread, american: american, decimal: decimal, parseDate: parseDate, isNum: isNum, titleCase: titleCase,
  // names, colours, links
  team: team, teamName: teamName, teamAbbr: teamAbbr, teamShort: teamShort, playerName: playerName, playerShort: playerShort,
  teamColour: teamColour, teamBar: teamBar, teamLink: teamLink, playerLink: playerLink, gameLink: gameLink,
  href: href, sq: sq, seasonHref: seasonHref, teamHref: teamHref, playerHref: playerHref, gameHref: gameHref,
  // games
  gameState: gameState, periodLabel: periodLabel, statusChip: statusChip, stypeLabel: stypeLabel, gameCard: gameCard, simTeams: simTeams, titleProbs: titleProbs,
  // HTML
  card: card, muted: muted, chip: chip, notBuilt: notBuilt, tableHTML: tableHTML, sortable: sortable, pctPill: pctPill, pctColor: pctColor,
  pctRow: pctRow, statTile: statTile, probCell: probCell, edgeHTML: edgeHTML, divColour: divColour, seqColour: seqColour,
  toggles: toggles, wireToggles: wireToggles, pageHead: pageHead,
  // charts
  plot: plot, layout: layout, PALETTE: PALETTE, C: C, DARK_LAYOUT: DARK_LAYOUT, PLOTLY_CONF: PLOTLY_CONF,
  FOOTBALL_URL: FOOTBALL_URL, PADDOCK_URL: PADDOCK_URL, ACE_URL: ACE_URL, BULLPEN_URL: BULLPEN_URL, GRIDIRON_URL: GRIDIRON_URL, RINK_URL: RINK_URL,
  charts: {}
};
})();
