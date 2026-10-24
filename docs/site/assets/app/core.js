/* The Quant Footballer — core: state, routing (with the old-route redirects), cached loading, competitions,
 * clubs and people indexes, links and marks, formatting, and the HTML builders every page uses.
 * Built on the shared kit v4 "Broadcast" (assets/qk: window.QK, window.QKC; dark only). Older-browser rule: no optional chaining, no
 * nullish coalescing (checked with esprima before shipping).
 *
 * Routes (hash). The section lit in the nav is in brackets.
 *   #/                                          overview: today, live, our forecasts, title races    [overview]
 *   #/matches[?d=YYYY-MM-DD&c=<slug>&f=…]        every competition's matches by day                    [fixtures]
 *   #/match/<slug>/<id>                          the match centre                                      [fixtures]
 *   #/competitions[?f=<family>]                  every competition, by family                          [standings]
 *   #/competition/<slug>[/<tab>][?s=<sid>&view=…] one competition: overview, table, fixtures, bracket,
 *                                                odds, power, players, analytics, clubs, seasons       [standings]
 *   #/clubs[/<tab>]                              clubs on one scale, national teams, "If they met"     [teams]
 *   #/club/<tid>[?c=<slug>&e=<era>&tab=…]        ONE club page across every competition                [teams]
 *   #/players[/<tab>]                            search, leaders across competitions                   [players]
 *   #/player/<pid>[?c=<slug>&scope=club|intl&e=<era>&tab=…]  ONE player page across every competition [players]
 *   #/value[/<tab>][?…]                          value, best by position, transfers, simulator, budgets [value]
 *   #/fantasy[?…]                                fantasy projections, picks, squad                      [fantasy]
 *   #/lab[/<comp>/<pos>]  #/compare[/<kind>[/<a>[/<b>]]]                                              [lab]
 *   #/model[/<tab>[/<key>]]                      methodology, glossary, disclaimer                      [model]
 * Every older route (#/<slug>/<tab>, #/<slug>/match/<id>, #/<slug>/team/<club>, #/<slug>/player/<id>,
 * #/nations, #/leaders, #/transfer, #/glossary, #/methodology, #/disclaimer, #/hub …) is redirected by
 * legacyRedirect() so every link ever shared still lands.
 *
 * A page registers with FB.route(name, fn); fn(el, params, state) renders into el (a fresh div, detached
 * when the viewer navigates away: test FB.alive(el) after every await) and may return a Promise.
 * params holds the named segments plus params.query (the ?a=b part of the hash). */
window.FB = (function () {
'use strict';

var QK = window.QK;

// ── state and registries ──────────────────────────────────────────────────

var state = { route: null, section: null, params: {}, hash: '', comp: null };
var INDEX = { comps: [], bySlug: {}, updated_at: null };
var CACHE = {}, PENDING = {};
var HANDLERS = {};
var CLEANUPS = [];
var SHELL = null;
var booted = false;

var ROUTES = [];
function addRoute(pattern, name, section) {
  ROUTES.push({ segs: pattern ? pattern.split('/') : [], name: name, section: section });
}
addRoute('', 'overview', 'overview');
addRoute('matches', 'matches', 'fixtures');
addRoute('match/:slug/:id', 'match', 'fixtures');
addRoute('competitions', 'competitions', 'standings');
addRoute('competition/:slug', 'competition', 'standings');
addRoute('competition/:slug/:tab', 'competition', 'standings');
addRoute('clubs', 'clubs', 'teams');
addRoute('clubs/:tab', 'clubs', 'teams');
addRoute('club/:tid', 'club', 'teams');
addRoute('players', 'players', 'players');
addRoute('players/:tab', 'players', 'players');
addRoute('player/:pid', 'player', 'players');
addRoute('value', 'value', 'value');
addRoute('value/:tab', 'value', 'value');
addRoute('fantasy', 'fantasy', 'fantasy');
addRoute('lab', 'lab', 'lab');
addRoute('lab/:comp', 'lab', 'lab');
addRoute('lab/:comp/:pos', 'lab', 'lab');
addRoute('compare', 'compare', 'lab');
addRoute('compare/:kind', 'compare', 'lab');
addRoute('compare/:kind/:a', 'compare', 'lab');
addRoute('compare/:kind/:a/:b', 'compare', 'lab');
addRoute('model', 'model', 'model');
addRoute('model/:tab', 'model', 'model');
addRoute('model/:tab/:key', 'model', 'model');
addRoute('team-legacy/:slug/:team', 'teamLegacy', 'teams');

var TITLES = {
  overview: '', matches: 'Matches', match: 'Match centre', competitions: 'Competitions', competition: 'Competition',
  clubs: 'Clubs', club: 'Club', players: 'Players', player: 'Player', value: 'Value & Transfers', fantasy: 'Fantasy',
  lab: 'Lab', compare: 'Compare', model: 'Model', teamLegacy: 'Club'
};

/* The old competition tabs -> [new tab, extra query]. Past-season tabs (p-*) keep their ?s=. */
var COMP_TAB_MAP = {
  overview: ['overview'], table: ['table'], zones: ['table', { view: 'zones' }], anual: ['table', { view: 'anual' }],
  relegation: ['table', { view: 'relegation' }], fixtures: ['fixtures'], matches: ['fixtures', { view: 'played' }],
  bracket: ['bracket'], probs: ['odds'], market: ['odds'], history: ['odds', { view: 'history' }],
  power: ['power'], team: ['clubs'], players: ['players'], analytics: ['analytics'],
  'p-table': ['table'], 'p-results': ['fixtures'], 'p-bracket': ['bracket'], 'p-players': ['players'], 'p-leaders': ['players', { view: 'leaders' }]
};
/* Competition tabs the new page knows (the competition module may hide some per competition). */
var COMP_TABS = ['overview', 'race', 'table', 'fixtures', 'bracket', 'odds', 'power', 'players', 'analytics', 'clubs', 'seasons'];

function splitHash(hash) {
  var h = String(hash === undefined ? location.hash : hash).replace(/^#\/?/, '');
  var query = {};
  var qi = h.indexOf('?');
  if (qi >= 0) {
    h.slice(qi + 1).split('&').forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf('=');
      var k = dec(i >= 0 ? kv.slice(0, i) : kv), v = i >= 0 ? dec(kv.slice(i + 1).replace(/\+/g, ' ')) : '';
      query[k] = v;
    });
    h = h.slice(0, qi);
  }
  var parts = h.split('/').filter(function (s) { return s !== ''; }).map(dec);
  return { parts: parts, query: query };
}
function dec(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }
function enc(s) { return encodeURIComponent(s); }
function qs(query) {
  var ks = Object.keys(query || {}).filter(function (k) { return query[k] !== undefined && query[k] !== null && query[k] !== ''; });
  return ks.length ? '?' + ks.map(function (k) { return enc(k) + '=' + enc(query[k]); }).join('&') : '';
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
function merge(a, b) { var o = {}; Object.keys(a || {}).forEach(function (k) { o[k] = a[k]; }); Object.keys(b || {}).forEach(function (k) { o[k] = b[k]; }); return o; }

/* The new hash for an old route, or null when the route is current. */
function legacyRedirect(hash) {
  var s = splitHash(hash);
  var p = s.parts, q = s.query;
  if (!p.length) return null;
  for (var i = 0; i < ROUTES.length; i++) if (matchSegs(ROUTES[i].segs, p)) return null;   // a current route
  var p0 = p[0];
  if (p0 === 'hub' || p0 === 'home' || p0 === 'index' || p0 === 'ballon-dor') return '#/';
  if (p0 === 'nations') return '#/clubs/nations' + qs(q);
  if (p0 === 'leaders') return '#/players/leaders' + qs(q);
  if (p0 === 'transfer') {
    var v = q.view;
    var rest = merge(q, {}); delete rest.view;
    if (v === 'feed') return '#/value/transfers' + qs(rest);
    if (v === 'deals' || v === 'windows') return '#/value/transfers' + qs(merge(rest, { view: v }));
    return '#/value/simulator' + qs(rest);
  }
  if (p0 === 'glossary') return '#/model/glossary' + (p[1] ? '/' + enc(p[1]) : '') + qs(q);
  if (p0 === 'methodology' || p0 === 'methodologysite') return '#/model/methodology' + (p[1] ? '/' + enc(p[1]) : '') + qs(q);
  if (p0 === 'disclaimer') return '#/model/disclaimer';
  if (p0 === 'calibration') return '#/model/calibration';
  if (p0 === 'lab' && p.length === 4) return '#/lab/' + enc(p[1]) + '/' + enc(p[2]) + qs(merge(q, { w: p[3] }));
  if (INDEX.bySlug[p0]) {
    if (p.length === 1) return '#/competition/' + enc(p0) + qs(q);
    var tab = p[1];
    if (tab === 'match' && p[2]) return '#/match/' + enc(p0) + '/' + enc(p.slice(2).join('/'));
    if (tab === 'player' && p[2]) return '#/player/' + enc(p.slice(2).join('/')) + qs(merge({ c: p0 }, q));
    if (tab === 'team' && p[2]) return '#/team-legacy/' + enc(p0) + '/' + enc(p.slice(2).join('/')) + qs(q);
    if (tab === 'methodology') return '#/model/methodology' + qs({ c: p0 });
    var m = COMP_TAB_MAP[tab];
    if (m) return '#/competition/' + enc(p0) + (m[0] === 'overview' ? '' : '/' + m[0]) + qs(merge(m[1] || {}, q));
    return '#/competition/' + enc(p0) + qs(q);
  }
  // A bare old tab name (#/table) belonged to "the open competition", which no longer exists.
  if (p.length === 1 && (COMP_TAB_MAP[p0] || p0 === 'methodology')) return '#/competitions';
  return null;
}
/* Rewrite href="#/old" links inside a block of static HTML to their new homes. */
function fixLinks(html) {
  return String(html || '').replace(/href="(#\/[^"]*)"/g, function (all, h) {
    var r = legacyRedirect(h.replace(/&amp;/g, '&'));
    return r ? 'href="' + esc(r) + '"' : all;
  });
}

function parseHash(hash) {
  var s = splitHash(hash);
  for (var i = 0; i < ROUTES.length; i++) {
    var p = matchSegs(ROUTES[i].segs, s.parts);
    if (p) { p.query = s.query; return { name: ROUTES[i].name, section: ROUTES[i].section, params: p }; }
  }
  return { name: 'notfound', section: null, params: { query: s.query, rest: s.parts } };
}

function route(name, fn) { HANDLERS[name] = fn; if (booted && state.route === name) render(); }
function onLeave(fn) { if (typeof fn === 'function') CLEANUPS.push(fn); }
function interval(fn, ms) { var id = setInterval(fn, ms); onLeave(function () { clearInterval(id); }); return id; }
function runCleanups() {
  var list = CLEANUPS; CLEANUPS = [];
  list.forEach(function (fn) { try { fn(); } catch (e) { if (window.console) console.warn('cleanup failed', e); } });
}

function render() {
  var red = legacyRedirect(location.hash);
  if (red) { try { history.replaceState(null, '', red); } catch (e) { location.hash = red; return; } }
  runCleanups();
  var r = parseHash();
  state.route = r.name;
  state.section = r.section;
  state.params = r.params;
  state.hash = location.hash || '#/';
  if (r.name !== 'competition') setCompPicker(null);
  if (SHELL) SHELL.setSection(r.section || '');
  var app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '';
  var el = document.createElement('div');
  el.className = 'fb-page fb-page-' + r.name;
  app.appendChild(el);
  document.title = (TITLES[r.name] ? TITLES[r.name] + ' · ' : '') + 'The Quant Footballer';
  if (!state.keepScroll) window.scrollTo(0, 0);
  state.keepScroll = false;
  var fn = HANDLERS[r.name];
  if (!fn) {
    el.innerHTML = pageHead('Not found', 'Page not found', 'There is no page at ' + esc(location.hash) + '. Try the overview, or search (press /).') +
      '<p><a class="qk-btn" href="#/">Back to the overview</a></p>';
    return;
  }
  try {
    var out = fn(el, r.params, state);
    if (out && typeof out.then === 'function') out.then(null, function (err) { showError(el, err); });
  } catch (err) { showError(el, err); }
}
function showError(el, err) {
  if (window.console) console.warn(err);
  if (el && el.isConnected) el.insertAdjacentHTML('afterbegin', '<div class="fb-error" data-route-error role="alert">This page could not be shown: ' + esc(err && err.message ? err.message : err) + '</div>');
}
function go(hash) {
  var h = hash.charAt(0) === '#' ? hash : '#/' + hash.replace(/^\/+/, '');
  if (location.hash === h) render(); else location.hash = h;
}
/* Replace the hash without a new history entry or a re-render (shareable page state). */
function setHashQuiet(h) { try { history.replaceState(null, '', h); state.hash = h; } catch (e) { /* old browsers: state is not shareable */ } }
/* The current route with its query changed: patch = {k: v|null}. render=true re-renders (keeping the scroll). */
function setQuery(patch, rerender) {
  var s = splitHash(location.hash);
  var q = merge(s.query, {});
  Object.keys(patch || {}).forEach(function (k) { if (patch[k] === null || patch[k] === undefined || patch[k] === '') delete q[k]; else q[k] = patch[k]; });
  var h = '#/' + s.parts.map(enc).join('/') + qs(q);
  state.params.query = q;
  if (rerender) { state.keepScroll = true; go(h); } else setHashQuiet(h);
  return q;
}
function alive(el) { return !!el && el.isConnected; }

// ── loading ───────────────────────────────────────────────────────────────

/* data/<path> as JSON, cached for the session; null when missing or broken (never throws). */
function load(path) {
  var p = String(path).replace(/^\/+/, '').replace(/^data\//, '');
  if (Object.prototype.hasOwnProperty.call(CACHE, p)) return Promise.resolve(CACHE[p]);
  if (PENDING[p]) return PENDING[p];
  PENDING[p] = fetch('data/' + p, { cache: 'no-cache' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .catch(function (e) { if (window.console) console.warn('payload missing:', p, e && e.message); return null; })
    .then(function (d) { CACHE[p] = d; delete PENDING[p]; return d; });
  return PENDING[p];
}
/* Re-read a payload (live scores). */
function reload(path) { var p = String(path).replace(/^data\//, ''); delete CACHE[p]; return load(p); }
function loadAll(paths) { return Promise.all(paths.map(load)); }
/* Column-oriented {fields, rows} -> array of objects. */
function rows(doc) {
  var f = (doc || {}).fields || [];
  return ((doc || {}).rows || []).map(function (r) { var o = {}; for (var i = 0; i < f.length; i++) o[f[i]] = r[i]; return o; });
}

// ── competitions ──────────────────────────────────────────────────────────

/* Per-competition payload files (data/<slug>/<file>). */
var FILES = {
  meta: 'meta.json', teams: 'teams.json', table: 'table.json', zones: 'zones.json', probs: 'probs.json',
  bracket: 'bracket.json', anual: 'anual.json', relegation: 'relegation.json', strength: 'strength.json',
  players_live: 'players_live.json', player_leaders: 'player_leaders.json', shots: 'shots.json',
  matches: 'matches.json', market_odds: 'market_odds.json', history: 'history.json', fixtures: 'fixtures.json',
  team_stats: 'team_stats.json', analytics: 'analytics.json', seasons: 'seasons.json', sensitivity: 'sensitivity.json'
};
/* Which files each competition kind writes (others are never requested, so no 404s). */
var KIND_FILES = {
  league: ['meta', 'teams', 'table', 'probs', 'strength', 'players_live', 'player_leaders', 'shots', 'matches', 'market_odds', 'history', 'fixtures', 'team_stats', 'analytics', 'seasons'],
  liga: ['meta', 'teams', 'zones', 'probs', 'bracket', 'anual', 'relegation', 'strength', 'players_live', 'player_leaders', 'shots', 'matches', 'market_odds', 'history', 'fixtures', 'team_stats', 'analytics', 'seasons']
};
var FAMILIES = [
  { key: 'league', label: 'Leagues' }, { key: 'cup', label: 'Continental & world' }, { key: 'domestic', label: 'National cups' },
  { key: 'super', label: 'Super cups' }, { key: 'international', label: 'National teams' }
];
function comps() { return INDEX.comps; }
function comp(slug) { return INDEX.bySlug[slug] || null; }
function familyOf(c) { if (!c) return 'league'; return c.kind !== 'cup' ? 'league' : (c.family || 'cup'); }
function compName(slug, short) { var c = comp(slug); return c ? (short ? (c.short_name || c.name) : c.name) : String(slug || '—'); }
/* Whether a competition writes a payload, from its tabs (the build lists only the tabs it has data for). */
function hasFile(slug, name) {
  var c = comp(slug);
  if (!c || !c.ok) return false;
  var tabs = c.tabs || [];
  var need = {
    table: ['table'], zones: ['zones'], probs: ['probs'], bracket: ['bracket'], anual: ['anual'], relegation: ['relegation'],
    strength: ['power'], players_live: ['players'], player_leaders: ['players'], shots: ['players'], market_odds: ['market'],
    history: ['history'], analytics: ['analytics'], team_stats: ['analytics', 'team'], matches: ['matches']
  }[name];
  if (name === 'seasons') return (c.seasons || []).length > 0;
  if (name === 'sensitivity') return c.kind !== 'cup' && !!c.ok && c.scope === 'club' && (c.kind_u === 'league');
  if (!need) return true;     // meta, teams, fixtures: every built competition
  return need.some(function (t) { return tabs.indexOf(t) >= 0; });
}
/* One payload of one competition: Promise<json|null>. Files the competition does not write resolve to null without a request. */
function compFile(slug, name) {
  if (!FILES[name] || !hasFile(slug, name)) return Promise.resolve(null);
  return load(slug + '/' + FILES[name]);
}
function compFiles(slug, names) {
  return Promise.all(names.map(function (n) { return compFile(slug, n); })).then(function (list) {
    var o = {}; names.forEach(function (n, i) { o[n] = list[i]; }); return o;
  });
}

/* The live edition of a competition: { sid, season, era, status }. */
function currentSeason(c) {
  var cs = (c || {}).current_season || {};
  return { sid: cs.sid !== undefined && cs.sid !== null ? String(cs.sid) : 'live', season: cs.season || shortSeason(c && c.season), era: cs.era || '', status: cs.status || 'current' };
}
function isLastEdition(c) { return currentSeason(c).status === 'last_edition'; }
/* "Premier League 26/27" -> "26/27"; "Liga MX, Apertura 2026" -> "Apertura 2026". */
function shortSeason(name) {
  var s = String(name || '');
  var m = s.match(/\d\d\/\d\d/);
  if (m) return m[0];
  m = s.match(/(Apertura|Clausura) (19|20)\d\d/);
  if (m) return m[0];
  m = s.match(/(19|20)\d\d/);
  return m ? m[0] : s;
}
/* Every edition of a competition, newest first: data/<slug>/seasons.json when written, else competitions.json's list. */
function seasonsOf(c) {
  if (!c) return Promise.resolve([]);
  var cur = currentSeason(c);
  var base = (c.seasons || []).map(function (s) { return merge(s, { sid: String(s.sid) }); });
  var p = hasFile(c.slug, 'seasons') ? load(c.slug + '/seasons.json') : Promise.resolve(null);
  return p.then(function (doc) {
    var list = ((doc || {}).seasons || []).map(function (s) { return merge(s, { sid: String(s.sid) }); });
    if (!list.length) list = base;
    if (c.ok && !list.some(function (s) { return s.source === 'live'; })) list = [{ sid: cur.sid, season: cur.season, era: cur.era, source: 'live', name: c.season }].concat(list);
    list.forEach(function (s) { if (s.source === 'live') s.status = cur.status; });
    return list;
  });
}
/* A past season's payload: data/<slug>/<path>season.json (path from seasons.json), or null. */
function loadPastSeason(c, sid) {
  return seasonsOf(c).then(function (list) {
    var meta = null;
    for (var i = 0; i < list.length; i++) if (list[i].sid === String(sid)) meta = list[i];
    if (!meta || meta.source === 'live') return null;
    var path = meta.path || ('s/' + sid + '/');
    return load(c.slug + '/' + path + 'season.json').then(function (doc) { return doc ? merge(doc, { meta: meta }) : null; });
  });
}

// ── clubs and people ──────────────────────────────────────────────────────

var CLUBS = null, PEOPLE = null;
/* clubs_index.json as { list, byId } (one row per club or national team). */
function clubsIndex() {
  if (CLUBS) return Promise.resolve(CLUBS);
  return load('clubs_index.json').then(function (d) {
    var list = rows(d);
    var byId = {};
    list.forEach(function (r) { byId[String(r.id)] = r; });
    CLUBS = { list: list, byId: byId };
    return CLUBS;
  });
}
function clubRow(tid) { return CLUBS ? CLUBS.byId[String(tid)] || null : null; }
function clubName(tid, fallback) { var r = clubRow(tid); return r ? r.name : (fallback || ''); }
/* v4 team colours (STYLE_GUIDE 3, rule 4): a club's kit colour and its alternate from clubs_index.json (`colour`,
   `alt`) once the football data agent writes them (MIGRATION_V4 payload follow-up). null until then, and the kit's
   fallback takes over: cobalt for the side we favour, slate for the other. Never invented in the front end. */
function hexOk(v) { return typeof v === 'string' && /^#?[0-9a-f]{6}$/i.test(v.trim()) ? (v.charAt(0) === '#' ? v.trim() : '#' + v.trim()) : null; }
function clubColour(tid) { var r = clubRow(tid); return r ? hexOk(r.colour || r.color) : null; }
function clubAlt(tid) { var r = clubRow(tid); return r ? hexOk(r.alt || r.colour2) : null; }
/* A short code for tight spots on the v4 heroes (the watermark, the scoreboard bug, the bar keys): the payloads carry
   no club codes, so it is made from the name: one word -> its first three letters ("ARS"), several -> the initials
   of the words that count ("Manchester City" -> "MC", "Paris Saint-Germain" -> "PSG"). `other` is the opponent's
   name: when the two codes would match ("Real Madrid" v "Real Betis"), each takes its last word's first three. */
var CODE_SKIP = { fc: 1, cf: 1, afc: 1, sc: 1, ac: 1, ca: 1, cd: 1, club: 1, de: 1, del: 1, da: 1, do: 1, of: 1, the: 1, and: 1 };
function codeWords(name) {
  return String(name || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9\s-]/g, '').split(/[\s-]+/).filter(function (w) { return w && !CODE_SKIP[w.toLowerCase()]; });
}
function clubCode(name, other) {
  var w = codeWords(name);
  if (!w.length) return String(name || '').slice(0, 3).toUpperCase();
  var c = w.length === 1 ? w[0].slice(0, 3) : w.slice(0, 3).map(function (x) { return x.charAt(0); }).join('');
  c = c.toUpperCase();
  if (other !== undefined && other !== null) {
    var o = codeWords(other), oc = o.length === 1 ? o[0].slice(0, 3).toUpperCase() : o.slice(0, 3).map(function (x) { return x.charAt(0); }).join('').toUpperCase();
    if (oc === c && w.length > 1) c = w[w.length - 1].slice(0, 3).toUpperCase();
  }
  return c;
}
/* A game (FB.toGame) ready for a v4 hero or bug: both clubs' codes (told apart), and each side's full name kept. */
function heroGame(g) {
  if (!g || !g.home || !g.away) return g;
  g.home.abbr = g.home.abbr || clubCode(g.home.name, g.away.name);
  g.away.abbr = g.away.abbr || clubCode(g.away.name, g.home.name);
  if (g.away.abbr === g.home.abbr) g.away.abbr = g.away.abbr + '2';
  return g;
}
/* people_index.json as { list, byId, aliases } (3.6 MB: search and a few lookups only). A duplicate Sofascore id of
   one person (`aliases`, UNIFIED_PAYLOADS 14.4) looks up the person's row, so an old link still finds him. */
function peopleIndex() {
  if (PEOPLE) return Promise.resolve(PEOPLE);
  return load('people_index.json').then(function (d) {
    var list = rows(d);
    var byId = {}, aliases = (d || {}).aliases || {};
    list.forEach(function (r) { byId[String(r.id)] = r; });
    Object.keys(aliases).forEach(function (a) { if (byId[String(aliases[a])] && !byId[a]) byId[a] = byId[String(aliases[a])]; });
    PEOPLE = { list: list, byId: byId, aliases: aliases };
    return PEOPLE;
  });
}
/* The search box's names-only index (people_names.json: id, name, pos, club; about a seventh of people_index.json,
   b8691423), rows already ordered by minutes; people_index.json when a build has not written it yet. */
function namesIndex() {
  return load('people_names.json').then(function (d) {
    var list = rows(d);
    if (!list.length) return peopleIndex();
    var n = list.length;
    list.forEach(function (r, i) { r._rank = 1 - i / n; });
    return { list: list, names: true };
  });
}
/* The person id of a player id (a merged duplicate id -> the person's). */
function personId(pid) { var a = PEOPLE ? PEOPLE.aliases[String(pid)] : null; return a ? String(a) : String(pid); }

// ── comparison metric sets and peer groups (METRICS_SPEC; STYLE_GUIDE 9) ───────────────────────

/* generated from docs/_design/metrics/football.json (schema 1, 2026-10-22; committed with docs/METRICS_SPEC.md in 5fdf8870,
   and shipped as assets/qk/metrics/football.json) by the phase-2 front-end pass. groups[]: peer group (formation role), minimum minutes, the minutes under
   which the sample is flagged small, and its metrics as [id, m50] (m50: minutes where the metric is half signal;
   null: not measured, see `early` below). metrics{}: display name, unit, lower-is-better, the spec's explanation. */
var MSET = {
  groups: [
    {"id": "cb", "name": "centre-backs", "short": "CBs", "codes": ["CB"], "min": 450, "small": 900, "headline": [["gar90", 660], ["rating", 1190], ["aerials_won_90", 650], ["aerial_pct", 2130], ["padj_tkl_int_90", 710], ["opp_half_passes_90", 310], ["pass_pct", 240], ["long_ball_pct", 1130]], "more": [["duels_won_90", 670], ["duel_pct", 2320], ["recoveries_90", 810], ["interceptions_90", 1310], ["clearances_90", 650], ["blocks_90", 2000], ["long_balls_90", 360], ["prog_carries_90", 1000], ["loss_per_100", 220], ["shot_creation_90", 1030], ["npxg_xa_90", 2510]]},
    {"id": "fb", "name": "full-backs and wing-backs", "short": "full-backs", "codes": ["FB"], "min": 450, "small": 900, "headline": [["gar90", 520], ["rating", 1480], ["npxg_xa_90", 610], ["key_passes_90", 620], ["crosses_90", 410], ["prog_actions_90", 290], ["opp_half_passes_90", 250], ["padj_tkl_int_90", 710], ["recoveries_90", 820]], "more": [["xa_90", 750], ["shot_creation_90", 440], ["dribbles_90", 480], ["prog_carries_90", 560], ["pass_pct", 310], ["duels_won_90", 450], ["duel_pct", 2210], ["aerials_won_90", 430], ["interceptions_90", 1520], ["loss_per_100", 180], ["hsr_km_90", 400]]},
    {"id": "dm_cm", "name": "defensive and central midfielders", "short": "DMs and CMs", "codes": ["DM", "CM"], "min": 450, "small": 900, "headline": [["gar90", 460], ["rating", 650], ["opp_half_passes_90", 240], ["long_balls_90", 270], ["npxg_xa_90", 450], ["key_passes_90", 430], ["prog_actions_90", 380], ["padj_tkl_int_90", 520], ["recoveries_90", 750]], "more": [["xa_90", 490], ["shot_creation_90", 320], ["passes_90", 140], ["pass_pct", 270], ["loss_per_100", 180], ["carries_90", 320], ["ball_wins_90", 620], ["interceptions_90", 970], ["duels_won_90", 480], ["duel_pct", 1440], ["aerials_won_90", 380], ["dribbles_90", 630]]},
    {"id": "am_w", "name": "attacking midfielders and wingers", "short": "AMs and wingers", "codes": ["AM", "W"], "min": 450, "small": 900, "headline": [["npxg_xa_90", 850], ["gar90", 520], ["rating", 800], ["npxg_90", 1080], ["xa_90", 700], ["shot_creation_90", 530], ["dribbles_90", 400], ["opp_half_passes_90", 130]], "more": [["key_passes_90", 550], ["big_chances_90", 2110], ["shots_90", 580], ["ga_90", 2200], ["prog_actions_90", 240], ["crosses_90", 320], ["dribble_pct", 5500], ["touches_90", 120], ["recoveries_90", 910], ["padj_tkl_int_90", 540], ["loss_per_100", 230], ["finishing", 17630]]},
    {"id": "st", "name": "strikers", "short": "strikers", "codes": ["ST"], "min": 450, "small": 900, "headline": [["npxg_xa_90", 1110], ["ga_90", 1570], ["sot_90", 1160], ["shot_creation_90", 650], ["xa_90", 830], ["xg_per_shot", 1620], ["gar90", 690], ["rating", 960]], "more": [["npxg_90", 1150], ["xgot_90", 1270], ["goals_90", 1810], ["shots_90", 790], ["big_chances_90", 2320], ["key_passes_90", 730], ["aerials_won_90", 170], ["aerial_pct", 1570], ["duels_won_90", 260], ["fouled_90", 510], ["touches_90", 120], ["finishing", null], ["g_minus_xg", 10670]]},
    {"id": "gk", "name": "goalkeepers", "short": "goalkeepers", "codes": ["GK"], "min": 900, "small": 1800, "headline": [["goals_prevented_90", null], ["save_pct", null], ["high_claims_90", 1570], ["sweeper_90", 1330], ["pass_pct", 320], ["long_ball_pct", 940], ["passes_90", 260], ["gar90", 8690]], "more": [["saves_90", 2380], ["conceded_90", 2720], ["long_balls_90", 430], ["rating", 14820]]}
  ],
  metrics: {
    "gar90": {"label": "Value added (GAR/90)", "unit": "goals per 90", "lower": false, "tip": "Goals of expected goal difference a player adds per 90 minutes over a replacement-level player in the same role, from the site's player value model (box score plus match rating)."},
    "rating": {"label": "Match rating", "unit": "rating", "lower": false, "tip": "Sofascore's 1-10 match rating, averaged over the player's matches and weighted by minutes."},
    "aerials_won_90": {"label": "Aerial duels won", "unit": "per 90", "lower": false, "tip": "Headers won against an opponent per 90."},
    "aerial_pct": {"label": "Aerial duel success", "unit": "%", "lower": false, "tip": "Share of aerial duels won."},
    "padj_tkl_int_90": {"label": "Tackles + interceptions (possession-adjusted)", "unit": "per 90", "lower": false, "tip": "Tackles plus interceptions per 90, scaled up for players whose team has the ball a lot (fewer chances to defend) and down for those who defend all game."},
    "opp_half_passes_90": {"label": "Passes in the opposition half", "unit": "per 90", "lower": false, "tip": "Completed passes in the opponent's half per 90: how much of the team's play in the attacking half goes through the player."},
    "pass_pct": {"label": "Pass completion", "unit": "%", "lower": false, "tip": "Share of passes that find a team-mate. It also reflects how risky the passing is."},
    "long_ball_pct": {"label": "Long-ball accuracy", "unit": "%", "lower": false, "tip": "Share of long passes that find a team-mate."},
    "duels_won_90": {"label": "Duels won", "unit": "per 90", "lower": false, "tip": "Ground and aerial duels won per 90."},
    "duel_pct": {"label": "Duel success", "unit": "%", "lower": false, "tip": "Share of ground and aerial duels won."},
    "recoveries_90": {"label": "Ball recoveries", "unit": "per 90", "lower": false, "tip": "Loose balls won back for the team, per 90."},
    "interceptions_90": {"label": "Interceptions", "unit": "per 90", "lower": false, "tip": "Opponent passes cut out per 90."},
    "clearances_90": {"label": "Clearances", "unit": "per 90", "lower": false, "tip": "Clearances per 90. Mostly says how much the team is under pressure, not how good the player is."},
    "blocks_90": {"label": "Blocks", "unit": "per 90", "lower": false, "tip": "Shots and passes blocked per 90. Mostly a sign of how much the team defends."},
    "long_balls_90": {"label": "Accurate long balls", "unit": "per 90", "lower": false, "tip": "Long passes that find a team-mate, per 90."},
    "prog_carries_90": {"label": "Progressive carries", "unit": "per 90", "lower": false, "tip": "Carries that move the ball well upfield, per 90."},
    "loss_per_100": {"label": "Possession lost per 100 touches", "unit": "per 100 touches", "lower": true, "tip": "How often the ball is given away for every 100 touches: ball security, whatever the volume."},
    "shot_creation_90": {"label": "Shots + key passes", "unit": "per 90", "lower": false, "tip": "Shots taken plus passes that led to a team-mate's shot, per 90: how often the player ends or sets up an attack."},
    "npxg_xa_90": {"label": "npxG + xA", "unit": "per 90", "lower": false, "tip": "Non-penalty expected goals plus expected assists per 90: the quality of the chances taken and set up."},
    "key_passes_90": {"label": "Key passes", "unit": "per 90", "lower": false, "tip": "Passes that lead directly to a team-mate's shot, per 90."},
    "crosses_90": {"label": "Accurate crosses", "unit": "per 90", "lower": false, "tip": "Crosses that reach a team-mate, per 90."},
    "prog_actions_90": {"label": "Progressive carries + dribbles", "unit": "per 90", "lower": false, "tip": "Carries that move the ball well upfield plus successful take-ons, per 90: how much the player moves the team forward with the ball at their feet."},
    "xa_90": {"label": "Expected assists (xA)", "unit": "per 90", "lower": false, "tip": "The chance that each pass is turned into a goal, added up per 90: chances created, whatever the finish."},
    "dribbles_90": {"label": "Dribbles completed", "unit": "per 90", "lower": false, "tip": "Successful take-ons per 90: beating a defender with the ball."},
    "hsr_km_90": {"label": "High-speed running", "unit": "km per 90", "lower": false, "tip": "Distance covered at high speed and sprinting per 90 (not every league has tracking data)."},
    "passes_90": {"label": "Passes", "unit": "per 90", "lower": false, "tip": "Passes attempted per 90."},
    "carries_90": {"label": "Carries", "unit": "per 90", "lower": false, "tip": "Times the player moves with the ball per 90."},
    "ball_wins_90": {"label": "Ball wins", "unit": "per 90", "lower": false, "tip": "Tackles won, interceptions and recoveries per 90."},
    "npxg_90": {"label": "Non-penalty xG", "unit": "per 90", "lower": false, "tip": "Expected goals from the player's own shots per 90, penalties left out: how good the chances are, and how many there are."},
    "big_chances_90": {"label": "Big chances created", "unit": "per 90", "lower": false, "tip": "Passes that set up a chance a player would be expected to score, per 90."},
    "shots_90": {"label": "Shots", "unit": "per 90", "lower": false, "tip": "Shots of any kind per 90."},
    "ga_90": {"label": "Goals + assists", "unit": "per 90", "lower": false, "tip": "Goals plus assists per 90 minutes, penalties included."},
    "dribble_pct": {"label": "Dribble success", "unit": "%", "lower": false, "tip": "Share of take-ons that succeed. Too noisy in one season to rank on."},
    "touches_90": {"label": "Touches", "unit": "per 90", "lower": false, "tip": "Touches of the ball per 90: how involved the player is."},
    "finishing": {"label": "Finishing (npG - npxG per shot)", "unit": "goals per shot", "lower": false, "tip": "Non-penalty goals minus non-penalty xG, per shot. Fun to look at, but in one season it is almost all luck: it does not carry over to the next."},
    "sot_90": {"label": "Shots on target", "unit": "per 90", "lower": false, "tip": "Shots that would have gone in without the goalkeeper, per 90."},
    "xg_per_shot": {"label": "xG per shot", "unit": "xG", "lower": false, "tip": "The average quality of the player's shots: high means shooting from good positions."},
    "xgot_90": {"label": "xG on target (xGOT)", "unit": "per 90", "lower": false, "tip": "Expected goals of shots on target, judged after the shot from where it was placed, per 90."},
    "goals_90": {"label": "Goals", "unit": "per 90", "lower": false, "tip": "Goals per 90, penalties included."},
    "fouled_90": {"label": "Fouls won", "unit": "per 90", "lower": false, "tip": "Times the player is fouled per 90."},
    "g_minus_xg": {"label": "Goals - xG", "unit": "goals", "lower": false, "tip": "Goals minus expected goals. Mostly luck in one season."},
    "goals_prevented_90": {"label": "Goals prevented", "unit": "per 90", "lower": false, "tip": "Expected goals on target faced minus goals conceded, per 90: shot-stopping above or below an average keeper. Takes several seasons to separate skill from luck."},
    "save_pct": {"label": "Save percentage", "unit": "%", "lower": false, "tip": "Share of shots on target saved. Depends on the shots faced; noisy within a season."},
    "high_claims_90": {"label": "High claims", "unit": "per 90", "lower": false, "tip": "Crosses and high balls caught or punched clear per 90: commanding the box."},
    "sweeper_90": {"label": "Sweeper actions", "unit": "per 90", "lower": false, "tip": "Times the keeper comes off the line to deal with a ball behind the defence, per 90."},
    "saves_90": {"label": "Saves", "unit": "per 90", "lower": false, "tip": "Saves per 90. Mostly says how busy the defence leaves the keeper."},
    "conceded_90": {"label": "Goals conceded", "unit": "per 90", "lower": true, "tip": "Goals conceded per 90. Mostly about the team in front of the keeper."}
  },
  generated: "2026-10-22"
};
var MSET_GROUP = {}, MSET_ROLE = {};
MSET.groups.forEach(function (g) { MSET_GROUP[g.id] = g; g.codes.forEach(function (c) { MSET_ROLE[c] = g.id; }); });
/* Composite attacking rates built from league-adjusted parts are adjusted too (the spec's evidence adjusts them). */
var ADJ_EXTRA = ['npxg_xa_90', 'ga_90', 'shot_creation_90'];
/* The peer group of a formation role (CB, FB, DM, CM, AM, W, ST, GK), or null: a coarse role (DF, MF, FW: substitute
   appearances only) has no peer group and no percentile card (the spec). */
function peerGroup(role) { var id = MSET_ROLE[String(role || '')]; return id ? MSET_GROUP[id] : null; }
/* A group's metric ids: which 'headline' | 'more' | 'all'. */
function groupKeys(g, which) {
  if (!g) return [];
  var a = which === 'more' ? g.more : which === 'all' ? g.headline.concat(g.more) : g.headline;
  return a.map(function (x) { return x[0]; });
}
function metricInfo(key) { return MSET.metrics[key] || null; }
/* Early (drawn dashed): his minutes are short of where the metric is half signal (m50); goalkeeper shot stopping,
   which the spec could not measure, needs 1,800 minutes. */
function isEarly(g, key, minutes) {
  if (!g || !isNum(minutes)) return false;
  var e = g.headline.concat(g.more).filter(function (x) { return x[0] === key; })[0];
  var m50 = e ? e[1] : null;
  if (!isNum(m50)) return g.id === 'gk' && minutes < 1800;
  return minutes < m50;
}
/* "v CBs in the Premier League 26/27, 450+ min" */
function peerLine(g, where, min) { return g ? 'v ' + g.short + (where ? ' in ' + where : '') + (isNum(min) ? ', ' + int(min) + '+ min' : '') : ''; }
/* The minutes a percentile needs in a view: the group's minimum and the view's own floor. */
function peerMin(g, floor) { return Math.max(g ? g.min : 450, isNum(floor) ? floor : 0); }
/* Formation roles this season, by competition: value/lines.json (one row per player and competition, 90+ minutes),
   read only when a percentile card needs it (about 0.66 MB compressed) until the role field reaches the lab and
   players_live rows (payload change listed in docs/_design/metrics/football.json). { ok, line: {"id|comp": role},
   best: {id: the role he played most minutes in}, gar: {"id|comp": gar90}, lines: {id: [[comp, min, gar]]} } */
var ROLES = null, ROLES_P = null;
function roles() {
  if (ROLES) return Promise.resolve(ROLES);
  if (ROLES_P) return ROLES_P;
  ROLES_P = load('value/lines.json').then(function (d) {
    var R = { ok: false, line: {}, best: {}, gar: {}, lines: {} };
    if (d && d.fields) {
      var I = {};
      d.fields.forEach(function (f, i) { I[f] = i; });
      var mins = {};
      (d.rows || []).forEach(function (r) {
        var id = String(r[I.id]), comp = r[I.comp], role = r[I.role], m = r[I.min] || 0, k = id + '|' + comp;
        if (role) R.line[k] = role;
        if (isNum(r[I.gar90])) R.gar[k] = r[I.gar90];
        (R.lines[id] = R.lines[id] || []).push([comp, m, r[I.gar]]);
        if (MSET_ROLE[role]) { var mm = mins[id] = mins[id] || {}; mm[role] = (mm[role] || 0) + m; }
      });
      Object.keys(mins).forEach(function (id) { var mm = mins[id]; R.best[id] = Object.keys(mm).sort(function (a, b) { return mm[b] - mm[a]; })[0]; });
      R.ok = true;
    }
    ROLES = R;
    return R;
  });
  return ROLES_P;
}
/* The roles source for a set of rows: when the rows carry `role` (players_live / lab rows, payload change in the
   spec), no file is read; otherwise value/lines.json (roles()). */
var ROWS_R = { ok: true, fromRows: true, line: {}, best: {}, gar: {}, lines: {} };
function rolesFor(hasRoleField) { return hasRoleField ? Promise.resolve(ROWS_R) : roles(); }
/* A row's role and value added per 90: its own fields when the payload has them, else the value/lines.json join. */
function rowRole(R, rowRoleValue, id, comp) { return rowRoleValue !== undefined && rowRoleValue !== null && rowRoleValue !== '' ? rowRoleValue : roleOf(R, id, comp); }
function rowGar(R, rowGarValue, id, comp) { return isNum(rowGarValue) ? rowGarValue : (R && R.gar ? R.gar[String(id) + '|' + comp] : null); }
/* His role in one competition this season (else the role he played most this season). */
function roleOf(R, id, comp) { if (!R) return null; var k = String(id); return (comp && R.line[k + '|' + comp]) || R.best[k] || null; }
/* Value added per 90 this season over the competitions a test accepts (comp -> bool): summed GAR over summed minutes. */
function garOver(R, id, test) {
  var ls = (R && R.lines[String(id)]) || [], g = 0, m = 0;
  ls.forEach(function (l) { if (isNum(l[2]) && (!test || test(l[0]))) { g += l[2]; m += l[1] || 0; } });
  return m > 0 ? 90 * g / m : null;
}
/* Percentiles against the peer group. o: { rows, minutes(row), role(row) -> role code, val(row, key) -> number,
   floor (the view's own floor) }. Returns { group(row), min(group), peers(group), pct(row) -> {key: 0-100} | null }:
   null when he has no peer group or is under the minimum. Mid-rank percentiles, turned round where less is better. */
function peerPct(o) {
  var cache = {}, peerCache = {};
  var grp = function (r) { return peerGroup(o.role(r)); };
  var minOf = function (g) { return peerMin(g, o.floor); };
  var peersOf = function (g) {
    if (!peerCache[g.id]) peerCache[g.id] = o.rows.filter(function (r) { return grp(r) === g && (o.minutes(r) || 0) >= minOf(g); });
    return peerCache[g.id];
  };
  var sorted = function (g, key) {
    var k = g.id + '|' + key;
    if (!cache[k]) cache[k] = peersOf(g).map(function (r) { return o.val(r, key); }).filter(isNum).sort(function (a, b) { return a - b; });
    return cache[k];
  };
  return {
    group: grp, min: minOf, peers: peersOf, values: sorted,
    pct: function (r) {
      var g = grp(r);
      if (!g || (o.minutes(r) || 0) < minOf(g)) return null;
      var out = {};
      groupKeys(g, 'all').forEach(function (key) {
        var v = o.val(r, key), vals = sorted(g, key);
        if (!isNum(v) || vals.length < 5) return;
        var lo = 0, hi = vals.length;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (vals[mid] < v) lo = mid + 1; else hi = mid; }
        var up = lo; while (up < vals.length && vals[up] === v) up++;
        var rank = (lo + 0.5 * (up - lo)) / vals.length;
        out[key] = Math.round(100 * (((MSET.metrics[key] || {}).lower) ? 1 - rank : rank));
      });
      return out;
    }
  };
}
/* Format a metric for the comparison views: the competition catalogue's fmt when known, else by its unit. */
function fmtSet(key, v, fmt) {
  if (!isNum(v)) return '—';
  if (key === 'gar90') return signed(v, 2);
  if (fmt) return fmtMetric(v, fmt);
  var u = (MSET.metrics[key] || {}).unit || '';
  if (u === '%') return Number(v).toFixed(1) + '%';
  if (u === 'rating') return Number(v).toFixed(2);
  return Number(v).toFixed(2);
}

// ── one row per person: data/lab/ (UNIFIED_PAYLOADS 14) ─────────────────────

var LABV = {};
/* data/lab/index.json: the windows, the scopes each has, the competitions, the metric catalogue. */
function labIndex() { return load('lab/index.json'); }
/* One view, data/lab/<window>/<scope>.json, as { idx, rows, floor, window, scope }: one row per person. */
function labView(win, scope) {
  var key = win + '/' + scope;
  if (LABV[key]) return Promise.resolve(LABV[key]);
  return load('lab/' + key + '.json').then(function (d) {
    if (!d || !d.fields) return null;
    var idx = {};
    d.fields.forEach(function (f, i) { idx[f] = i; });
    LABV[key] = { idx: idx, fields: d.fields, rows: d.rows || [], floor: d.floor || 90, window: win, scope: scope, pct: {} };
    return LABV[key];
  });
}
var LAB_SCOPES = { all: 'All competitions', club: 'Club competitions', intl: 'National team' };
function labScopeName(scope, ix) {
  if (LAB_SCOPES[scope]) return LAB_SCOPES[scope];
  var c = ((ix || {}).comps || {})[scope];
  return comp(scope) ? compName(scope) : (c ? c.name : String(scope || ''));
}
/* The scope picker's options for one window: the three groupings, then every competition with a view. */
function labScopeOptions(ix, win) {
  var have = (((ix || {}).scopes || {})[win]) || {};
  var out = ['all', 'club', 'intl'].filter(function (k) { return have[k]; }).map(function (k) { return [k, LAB_SCOPES[k]]; });
  var comps = Object.keys(have).filter(function (k) { return !LAB_SCOPES[k]; });
  var byKind = {};
  comps.forEach(function (k) { var c = ((ix || {}).comps || {})[k] || {}; var g = c.scope === 'international' ? 'National-team competitions' : c.kind === 'league' ? 'Leagues' : 'Cups'; (byKind[g] = byKind[g] || []).push(k); });
  ['Leagues', 'Cups', 'National-team competitions'].forEach(function (g) {
    if (!byKind[g]) return;
    out.push({ group: g, items: byKind[g].sort(function (a, b) { return labScopeName(a, ix).localeCompare(labScopeName(b, ix)); }).map(function (k) { return [k, labScopeName(k, ix)]; }) });
  });
  return out;
}
/* The window's label with its seasons or dates. */
function labWindowText(w) {
  if (!w) return '';
  if (w.eras) return w.label.replace(/ \(.*\)$/, '') + ' (' + w.eras.split + ' in split-season football, ' + w.eras.calendar + ' in calendar-year football)';
  return w.label + ' (' + w.start + ' to ' + w.end + ')';
}
/* Percentiles of one row in its view: against the same position (G, D, M, F) among rows over `floor` minutes,
   inverted where less is better (players.add_percentiles). metrics: catalogue entries with pct. */
function labPct(view, row, metrics, floor) {
  var I = view.idx, pos = row[I.position] || 'O', key = pos + '|' + floor, cache = view.pct[key];
  if (!cache) {
    var peers = view.rows.filter(function (r) { return (r[I.position] || 'O') === pos && (r[I.minutes] || 0) >= floor; });
    cache = view.pct[key] = { n: peers.length, vals: {} };
    metrics.forEach(function (m) {
      if (I[m.key] === undefined) return;
      cache.vals[m.key] = peers.map(function (r) { return r[I[m.key]]; }).filter(isNum).sort(function (a, b) { return a - b; });
    });
  }
  var out = {};
  metrics.forEach(function (m) {
    if ((m.scope === 'gk' && pos !== 'G') || (m.scope === 'out' && pos === 'G')) return;
    var vals = cache.vals[m.key], v = I[m.key] === undefined ? null : row[I[m.key]];
    if (!vals || vals.length < 3 || !isNum(v)) return;
    var lo = 0, hi = vals.length;
    while (lo < hi) { var mid = (lo + hi) >> 1; if (vals[mid] < v) lo = mid + 1; else hi = mid; }
    var up = lo; while (up < vals.length && vals[up] === v) up++;
    var rank = (lo + 0.5 * (up - lo)) / vals.length;
    out[m.key] = Math.round(100 * (m.lower ? 1 - rank : rank));
  });
  return out;
}
/* Only 1 in 8 clubs has a crest file: data/crests.json (written by the build) lists the ids that do, and any
   other id gets the monogram without a request. Until the list loads, no crest is requested. */
var CRESTS = null;
function crestUrl(tid) { return CRESTS && tid !== null && tid !== undefined && CRESTS[String(tid)] ? 'assets/crests/' + tid + '.png' : null; }
function hasCrest(tid) { return !!(CRESTS && CRESTS[String(tid)]); }
/* Crest files are named by team id: the club id from a crest path. */
function tidFromCrest(src) { var m = /crests\/(\d+)\.png$/.exec(String(src || '')); return m ? m[1] : null; }

// ── formatting ────────────────────────────────────────────────────────────

function isNum(v) { return v !== null && v !== undefined && v !== '' && typeof v !== 'boolean' && !isNaN(v) && isFinite(v); }
function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function num(v, d) { return isNum(v) ? Number(v).toFixed(d === undefined ? 1 : d) : '—'; }
function int(v) { return isNum(v) ? Math.round(v).toLocaleString('en-GB') : '—'; }
function pct(p, d) {
  if (!isNum(p)) return '—';
  var dd = d === undefined ? 0 : d;
  if (p > 0 && p * 100 < Math.pow(10, -dd) / 2) return '<' + Math.pow(10, -dd).toFixed(dd) + '%';
  if (p < 1 && p * 100 > 100 - Math.pow(10, -dd) / 2) return '>' + (100 - Math.pow(10, -dd)).toFixed(dd) + '%';
  return (p * 100).toFixed(dd) + '%';
}
function signed(v, d) {
  if (!isNum(v)) return '—';
  var s = Number(v).toFixed(d === undefined ? 1 : d);
  if (/^-0\.?0*$/.test(s)) s = s.slice(1);
  return (Number(s) > 0 ? '+' : Number(s) < 0 ? '−' : '') + s.replace(/^-/, '');
}
/* Euros the way the transfer pages write them: €212m, €4.5m, €750k. */
function money(v, cur) {
  if (!isNum(v)) return '—';
  var sym = !cur || cur === 'EUR' ? '€' : cur === 'GBP' ? '£' : cur === 'USD' ? '$' : cur + ' ';
  var a = Math.abs(v), sign = v < 0 ? '−' : '';
  if (a >= 1e9) return sign + sym + (a / 1e9).toFixed(2) + 'bn';
  if (a >= 1e6) return sign + sym + (a / 1e6).toFixed(a >= 1e8 ? 0 : 1).replace(/\.0$/, '') + 'm';
  if (a >= 1e3) return sign + sym + Math.round(a / 1e3) + 'k';
  return sign + sym + Math.round(a);
}
/* Catalogue metric formats (players_live metrics[].fmt). */
function fmtMetric(v, f) {
  if (!isNum(v)) return '—';
  if (f === 'pct') return Number(v).toFixed(1) + '%';
  if (f === 'int') return String(Math.round(v));
  if (f === '1') return Number(v).toFixed(1);
  if (f === '3') return Number(v).toFixed(3);
  if (f === '0') return Number(v).toFixed(0);
  return Number(v).toFixed(2);
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
/* "Sat 18 Oct" (viewer's time zone); opts {year: true, weekday: false, time: true}. */
function fmtDate(s, opts) {
  var o = typeof opts === 'boolean' ? { year: opts } : (opts || {});
  var d = parseDate(s);
  if (!d) return '—';
  var out = (o.weekday === false ? '' : DAYS[d.getDay()] + ' ') + d.getDate() + ' ' + MONTHS[d.getMonth()] + (o.year ? ' ' + d.getFullYear() : '');
  if (o.time && String(s).length > 10) out += ' ' + fmtTime(s);
  return out;
}
function fmtTime(s) {
  var d = parseDate(s);
  if (!d || String(s).length === 10) return '';
  return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
}
function fmtStamp(s) { var d = parseDate(s); if (!d) return s ? String(s) : ''; return fmtDate(d) + ' ' + ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); }
/* The viewer's calendar day of a kickoff: YYYY-MM-DD. */
function localDay(s) {
  var d = parseDate(s);
  if (!d) return '';
  return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
}
function today() { return localDay(new Date()); }
function relDay(s) {
  var k = localDay(s), t = today();
  if (!k) return '';
  if (k === t) return 'Today';
  var d0 = parseDate(t + 'T12:00:00'), d1 = parseDate(k + 'T12:00:00');
  var n = Math.round((d1 - d0) / 864e5);
  return n === 1 ? 'Tomorrow' : n === -1 ? 'Yesterday' : fmtDate(s);
}
function ordinal(n) {
  if (!isNum(n)) return '—';
  var v = Math.round(n), t = v % 100;
  return v + (t >= 11 && t <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][v % 10] || 'th');
}
function ageOf(dob) {
  var d = parseDate(dob);
  if (!d) return null;
  var now = new Date(), a = now.getFullYear() - d.getFullYear();
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) a--;
  return a;
}
function median(a) { var s = a.filter(isNum).map(Number).sort(function (x, y) { return x - y; }); if (!s.length) return null; var k = s.length >> 1; return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2; }
function sum(list, k) { return list.reduce(function (s, r) { return s + (isNum(r[k]) ? Number(r[k]) : 0); }, 0); }
/* Minutes-weighted mean of k over rows (w = 'min'). */
function wavg(list, k, w) { var a = 0, b = 0; list.forEach(function (r) { if (isNum(r[k]) && r[k] > 0 && (r[w || 'min'] || 0) > 0) { a += r[k] * r[w || 'min']; b += r[w || 'min']; } }); return b ? a / b : null; }
function initials(name) { return QK.fmt.initials(name); }
function surname(name) {
  var parts = String(name || '').trim().split(' ');
  return parts.length > 2 && parts[parts.length - 1].length <= 3 ? parts.slice(-2).join(' ') : parts[parts.length - 1];
}
/* A season key ("2026/27" or "2026") in a stable sort order. */
function eraKey(e) { var m = /(\d{4})(?:\/(\d{2,4}))?/.exec(String(e || '')); return m ? Number(m[1]) + (m[2] ? 0.5 : 0) : -1; }
/* "2026/27" -> "2026/27"; a calendar year stays a year. */
function eraLabel(e) { return String(e || '—'); }

// ── football vocabulary ───────────────────────────────────────────────────

var KIND_LABEL = { league: 'League', domestic_cup: 'National cup', super_cup: 'Super cup', continental_club: 'Continental', international: 'International' };
var KIND_ORDER = { league: 0, continental_club: 1, domestic_cup: 2, super_cup: 3, international: 4 };
/* Chart slots per competition kind (categorical order is fixed by the kit: 1 model blue, 2 orange …). */
var KIND_SLOT = { league: 1, continental_club: 5, domestic_cup: 3, super_cup: 4, international: 2 };
function kindColor(kind) { return 'var(--c-' + (KIND_SLOT[kind] || 8) + ')'; }
function kindColorHex(kind) { return QK.cssVar('--c-' + (KIND_SLOT[kind] || 8)); }
function kindOf(slug) {
  var c = comp(slug);
  if (c && c.kind_u) return c.kind_u;
  if (!c) return 'league';
  if (c.kind !== 'cup') return 'league';
  return { domestic: 'domestic_cup', super: 'super_cup', international: 'international' }[c.family] || 'continental_club';
}
function kindChip(kind) { return '<span class="fb-kind" style="--k:' + kindColor(kind) + '">' + esc(KIND_LABEL[kind] || kind || '') + '</span>'; }
var POS_LABEL = { G: 'Goalkeeper', D: 'Defender', M: 'Midfielder', F: 'Forward' };
var POS_GROUP = { G: 'Goalkeepers', D: 'Defenders', M: 'Midfielders', F: 'Forwards' };
function posBadge(p) { return p ? '<span class="fb-pos fb-pos-' + esc(p) + '" title="' + esc(POS_LABEL[p] || p) + '">' + esc(p) + '</span>' : ''; }
var ROUND_LABELS = {
  r1: 'Round One', r16: 'Round of 16', qf: 'Quarter-final', sf: 'Semi-final', final: 'Final',
  wc: 'Wild Card', csf: 'Conf. Semi', cf: 'Conf. Final', po: 'Play-off', play_in: 'Play-in',
  r2: 'Second round', r3: 'Third round', r4: 'Fourth round', r5: 'Fifth round', r6: 'Sixth round', r7: 'Seventh round', r8: 'Eighth round',
  r32: 'Round of 32', r64: 'Round of 64', '3rd': 'Third place', prelim: 'Preliminary round', q1: 'First qualifying round',
  q2: 'Second qualifying round', q3: 'Third qualifying round', q4: 'Fourth qualifying round', qualifying: 'Qualifying',
  'runner-up': 'Runner-up', winner: 'Winner', group: 'Group stage', league: 'League phase', qualified: 'Qualified', 'po-final': 'Play-off final'
};
var ORDINAL_WORDS = ['', 'First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth', 'Seventh', 'Eighth', 'Ninth'];
var STAGE_LABELS = { league: 'League', playoff: 'Knockout', qualifying: 'Qualifying', split: 'Split', other: 'Other' };
function isDomestic(slug) { var c = comp(slug) || {}; return c.family === 'domestic' || c.kind_u === 'domestic_cup'; }
function stageLabel(s, slug) { if (s === 'qualifying' && isDomestic(slug)) return 'Early rounds'; return STAGE_LABELS[s] || s; }
/* A fixture's round as a fan reads it ("Round 5", "Quarter-final", "Second qualifying round"). */
function roundText(f, slug, short) {
  var r = f ? f.round : null;
  if (r === null || r === undefined || r === '') return '';
  if (r === 'r1' && isDomestic(slug)) return 'First round';
  if (ROUND_LABELS[r]) return ROUND_LABELS[r];
  var n = /^\d+$/.test(String(r)) ? parseInt(r, 10) : NaN;
  if (isNaN(n)) return String(r);
  if (!f.stage || f.stage === 'league' || f.stage === 'split') return (short ? 'R' : 'Round ') + n;
  if (n === 300) return ROUND_LABELS.prelim;
  if (isDomestic(slug) && n < 10) return n === 1 ? 'First round' : (ROUND_LABELS['r' + n] || 'Round ' + n);
  if (f.stage === 'qualifying' && n < 10) return ROUND_LABELS['q' + n] || (ORDINAL_WORDS[n] || n) + ' qualifying round';
  return 'Round ' + n;
}
/* How far a club went in a cup (club seasons[].stage). */
function stageText(stage) { return ROUND_LABELS[stage] || (stage ? String(stage) : ''); }

/* Coverage of a season row (UNIFIED_PAYLOADS 13.2): "full" says nothing; the rest say what is missing. */
function coverageChip(r, opts) {
  var o = opts || {};
  if (!r || !r.coverage || r.coverage === 'full') return o.full ? '<span class="fb-cov full" data-tip="Every finished match of this team in this edition has line-ups.">Full</span>' : '';
  var cov = r.cov && r.cov.length === 2 ? r.cov[0] + ' of ' + r.cov[1] + ' matches' : '';
  var gap = r.gap === 'backfill' ? ' The missing matches are queued in the hourly fetch and fill in over the coming days.'
    : r.gap === 'unavailable' ? ' Sofascore publishes no line-ups for the rest.'
    : r.gap === 'outside' ? ' The rest are ties the fetch does not follow (no followed club).' : '';
  if (r.coverage === 'totals') {
    return '<span class="fb-cov totals" data-tip="Sofascore\'s season totals: our line-ups covered ' + esc(cov || 'only part of the season') +
      (r.lineups ? ' (' + r.lineups.apps + ' apps, ' + r.lineups.min + ' min)' : '') + '; the totals are complete.">Season totals</span>';
  }
  if (r.coverage === 'partial') return '<span class="fb-cov partial" data-tip="A lower bound: line-ups for ' + esc(cov || 'part of the season') + '.' + esc(gap) + '">Partial' + (r.cov ? ' · ' + r.cov[0] + '/' + r.cov[1] : '') + '</span>';
  if (r.coverage === 'none') return '<span class="fb-cov none" data-tip="No line-ups for this team in this edition.' + esc(gap) + '">No line-ups</span>';
  return '';
}
function formChips(list) {
  return '<span class="fb-form">' + (list || []).map(function (r) { var x = String(r).charAt(0).toUpperCase(); return '<i class="fb-form-' + esc(x) + '" title="' + (x === 'W' ? 'Win' : x === 'D' ? 'Draw' : x === 'L' ? 'Loss' : '') + '">' + esc(x) + '</i>'; }).join('') + '</span>';
}

// ── links and marks ───────────────────────────────────────────────────────

var href = {
  club: function (tid, q) { return '#/club/' + enc(tid) + qs(q); },
  player: function (pid, q) { return '#/player/' + enc(pid) + qs(q); },
  match: function (slug, id) { return '#/match/' + enc(slug) + '/' + enc(id); },
  comp: function (slug, tab, q) { return '#/competition/' + enc(slug) + (tab && tab !== 'overview' ? '/' + tab : '') + qs(q); },
  matches: function (q) { return '#/matches' + qs(q); }
};
/* A crest (or a monogram when the file is missing). size: undefined | 'sm' | 'lg'. */
function crest(tid, name, size) { return QK.teamMark({ logo: tid ? crestUrl(tid) : null, name: name || clubName(tid) || '?' }, size); }
/* A club link with its crest. opts {q, size, nocrest, short}. Without an id: the name only. */
function clubLink(tid, name, opts) {
  var o = opts || {};
  var nm = name || clubName(tid) || '—';
  if (!tid) return '<span class="fb-ent">' + (o.nocrest ? '' : crest(null, nm, o.size || 'sm')) + '<span class="fb-ent-n">' + esc(nm) + '</span></span>';
  return '<a class="fb-ent" href="' + esc(href.club(tid, o.q)) + '">' + (o.nocrest ? '' : crest(tid, nm, o.size || 'sm')) + '<span class="fb-ent-n">' + esc(nm) + '</span></a>';
}
function playerLink(pid, name, opts) {
  var o = opts || {};
  if (!pid) return esc(name || '—');
  return '<a class="fb-link" href="' + esc(href.player(pid, o.q)) + '">' + esc(name || '#' + pid) + '</a>';
}
function compLink(slug, opts) {
  var o = opts || {};
  var c = comp(slug);
  if (!c) return esc(o.name || slug || '—');
  return '<a class="fb-link fb-comp" href="' + esc(href.comp(slug, o.tab, o.q)) + '"><i style="--k:' + kindColor(kindOf(slug)) + '"></i>' + esc(o.short ? (c.short_name || c.name) : c.name) + '</a>';
}

// ── games ─────────────────────────────────────────────────────────────────

/* A fixture (fixtures.json / hub.json / clubs matches) -> the kit's game shape for QK.matchCard and QK.tick.
 * f: {id, date, home, away, home_id, away_id, crests:[h, a], hs, as, status, model:{h,d,a}, xg, round, stage, detail}. */
/* A cached snapshot can keep a match "live" long after it ended (MIGRATION_V2: the home page drops games still live
   12 hours after kick-off): such a match is never shown as live. */
function staleLive(f) {
  var t = parseDate(f && f.date);
  return !!t && (f.status === 'live' || f.status === 'inprogress') && Date.now() - t.getTime() > 12 * 3600e3;
}
function toGame(f, slug, extra) {
  var s = slug || f.comp;
  var hid = f.home_id || tidFromCrest(f.crests && f.crests[0]);
  var aid = f.away_id || tidFromCrest(f.crests && f.crests[1]);
  var stale = staleLive(f);
  var st = f.status === 'finished' || stale ? 'final' : f.status === 'live' || f.status === 'inprogress' ? 'live' : 'pre';
  var g = {
    sport: 'football', league: (extra && extra.league) || compName(s, true), id: f.id, start: f.date, status: st,
    /* v4: the club's kit and alternate colours when clubs_index.json has them (else the kit's cobalt v slate rule) */
    home: { name: f.home, logo: hid ? crestUrl(hid) : null, colour: hid ? clubColour(hid) : null, alt: hid ? clubAlt(hid) : null, full: f.home },
    away: { name: f.away, logo: aid ? crestUrl(aid) : null, colour: aid ? clubColour(aid) : null, alt: aid ? clubAlt(aid) : null, full: f.away },
    hs: f.hs, as: f.as, note: roundText(f, s, true) + (f.result_missing || (stale && !isNum(f.hs)) ? ' · result not reported' : f.status === 'postponed' ? ' · postponed' : f.status === 'cancelled' ? ' · cancelled' : ''),
    href: f.detail ? href.match(s, f.id) : (extra && extra.href) || href.match(s, f.id)
  };
  /* our pre-match chance before kick-off and, after the whistle, as the card's "pre-game" line. Football has no live
     model: while a match is in play the card keeps the pre-match chance and says so (pre_only: "our pre-game chance"),
     as the Home page and the ticker do. */
  if (f.model && isNum(f.model.h)) { g.p_home = f.model.h; g.p_draw = f.model.d; g.p_away = f.model.a; if (st === 'live') g.pre_only = true; }
  if (extra && extra.home_form) g.home.form = extra.home_form;
  if (extra && extra.away_form) g.away.form = extra.away_form;
  if (extra && extra.home_record) g.home.record = extra.home_record;
  if (extra && extra.away_record) g.away.record = extra.away_record;
  if (f.xg && st !== 'pre') g.xg = f.xg;
  return g;
}
/* A game card (kit QK.gameCard, v4: the team-colour stripe): our chance per side before kick-off (the favourite in blue), the home / draw /
   away stripe (home first, as football reads), the score and xG after it, and with why the italic one-line reason (QK.whyLine). The market is never on
   a card: it is a quiet reference on the match page only. extra: {league, href, home_form, away_form ('WDLWW', oldest
   first), home_record, away_record, why: true}. */
function matchCard(f, slug, extra) {
  var g = toGame(f, slug, extra);
  var html = QK.gameCard(g, { sport: false, market: false, homeFirst: true, why: !!(extra && extra.why) });
  if (f.status === 'postponed' || f.status === 'cancelled') html = html.replace('class="qk-gc', 'class="qk-gc fb-void');
  return html;
}
/* The match page's win-chance bar: our home / draw / away chance, home on the left as on the cards. m: {h, d, a}. */
function wpBar(m, home, away, opts) {
  if (!m || !isNum(m.h)) return '';
  var o = opts || {};
  return QK.wpBar(m.h, m.d, m.a, { name: home || 'Home' }, { name: away || 'Away' }, { size: o.size || 'lg', label: o.label || 'Our win chance' });
}
/* Home/draw/away bar with labels: model {h, d, a}. */
function probBar3(m, opts) {
  if (!m || !isNum(m.h)) return '<span class="qk-muted">—</span>';
  var o = opts || {};
  var seg = function (k, cls, lab) { return '<span class="' + cls + '" style="flex:' + Math.max(0.0001, m[k]) + '" title="' + lab + ' ' + pct(m[k]) + '">' + (m[k] >= 0.14 && !o.bare && !o.small ? pct(m[k]) : '') + '</span>'; };
  var bar = '<span class="fb-p3' + (o.small ? ' sm' : '') + '" role="img" aria-label="Our chance: home ' + pct(m.h) + ', draw ' + pct(m.d) + ', away ' + pct(m.a) + '">' + seg('h', 'h', 'Home') + seg('d', 'd', 'Draw') + seg('a', 'a', 'Away') + '</span>';
  if (!o.small || o.bare) return bar;
  /* the small bar is too thin to carry its numbers: they sit underneath, home / draw / away, the favourite in the signal colour */
  var fav = m.h >= m.a && m.h >= m.d ? 'h' : m.a >= m.d ? 'a' : 'd';
  var n = function (k) { return '<span' + (k === fav ? ' class="fav"' : '') + '>' + pct(m[k]) + '</span>'; };
  return '<span class="fb-p3-w">' + bar + '<span class="fb-p3-n" aria-hidden="true">' + n('h') + n('d') + n('a') + '</span></span>';
}
function scoreText(f) {
  var done = f.status === 'finished' || f.status === 'live';
  if (done && (!isNum(f.hs) || !isNum(f.as))) return '–';
  return done ? f.hs + '–' + f.as : 'v';
}
/* One compact fixture row for lists: time · home · score · away · model or xG. opts {date, slug, comp: true}. */
function fixtureRow(f, opts) {
  var o = opts || {};
  var s = o.slug || f.comp;
  var hid = f.home_id || tidFromCrest(f.crests && f.crests[0]), aid = f.away_id || tidFromCrest(f.crests && f.crests[1]);
  var done = f.status === 'finished' || f.status === 'live';
  var when = f.status === 'live' ? '<span class="qk-badge live">Live</span>'
    : f.status === 'finished' ? '<span class="fb-fx-ft">FT</span>'
    : f.result_missing ? '<span class="fb-fx-ft" title="Past its kick-off with no result from the source">N/R</span>' : f.status === 'postponed' ? '<span class="fb-fx-ft">PPD</span>' : f.status === 'cancelled' ? '<span class="fb-fx-ft">CANC</span>'
    : '<span class="fb-fx-t">' + esc(fmtTime(f.date) || 'TBD') + '</span>';
  var link = f.detail || !done ? href.match(s, f.id) : null;
  var extra = done ? (f.xg && isNum(f.xg[0]) ? '<span class="fb-fx-xg">xG ' + num(f.xg[0], 1) + '–' + num(f.xg[1], 1) + '</span>' : '') : (f.model ? probBar3(f.model, { small: true }) : '');
  if (!done && f.model && f.model.lineups) extra = '<span class="qk-badge accent fb-fx-xi" data-tip="Confirmed line-ups are in; the line includes them">XI</span>' + extra;
  return '<div class="fb-fx' + (f.status === 'live' ? ' live' : '') + (f.status === 'postponed' || f.status === 'cancelled' ? ' void' : '') + '">' +
    '<div class="fb-fx-when">' + (o.date ? '<span class="fb-fx-d">' + esc(fmtDate(f.date)) + '</span>' : '') + when +
    (o.comp ? '<span class="fb-fx-c">' + compLink(s, { short: true }) + '</span>' : '') + (o.round && f.round ? '<span class="fb-fx-r">' + esc(roundText(f, s, true)) + '</span>' : '') + '</div>' +
    '<div class="fb-fx-h">' + clubLink(hid, f.home, { size: 'sm' }) + '</div>' +
    (link ? '<a class="fb-fx-s" href="' + esc(link) + '" title="Match centre">' : '<span class="fb-fx-s">') + (done ? '<b>' + esc(scoreText(f)) + '</b>' : '<span class="v">v</span>') + (link ? '</a>' : '</span>') +
    '<div class="fb-fx-a">' + clubLink(aid, f.away, { size: 'sm' }) + '</div>' +
    '<div class="fb-fx-x">' + extra + '</div></div>';
}

// ── HTML builders (kit markup) ────────────────────────────────────────────

/* A card. opts: {id, cls, span (3..12), flush, right (HTML in the head), foot, bodyId, kicker} */
function card(title, sub, body, opts) {
  var o = opts || {};
  return '<section class="qk-card' + (o.span ? ' qk-span-' + o.span : '') + (o.cls ? ' ' + o.cls : '') + '"' + (o.id ? ' id="' + esc(o.id) + '"' : '') + '>' +
    (title || o.right ? '<div class="qk-card-head"><div class="fb-card-titles">' + (title ? '<h3 class="qk-card-title">' + title + '</h3>' : '') + (sub ? '<div class="qk-card-sub">' + sub + '</div>' : '') + '</div>' + (o.right || '') + '</div>' : '') +
    '<div class="qk-card-body' + (o.flush ? ' flush' : '') + '"' + (o.bodyId ? ' id="' + esc(o.bodyId) + '"' : '') + '>' + (body || '') + '</div>' +
    (o.foot ? '<div class="qk-card-foot">' + o.foot + '</div>' : '') + '</section>';
}
function grid(html, cls) { return '<div class="qk-grid' + (cls ? ' ' + cls : '') + '">' + html + '</div>'; }
function chartBox(id, h, label) { return '<div id="' + esc(id) + '" class="fb-chart" style="--h:' + (h || 300) + 'px"' + (label ? ' role="img" aria-label="' + esc(label) + '"' : '') + '></div>'; }
/* A v2 stat tile (kit QK.statTile); value and sub are HTML. o: {sub (HTML), tip, text (a word, not a number: set
   automatically for long text), signal (ours: the number in the signal colour), pctl, href, unit, trend: [..],
   delta, cls, spark (HTML, drawn under the sub-line)}. */
function kpi(label, value, o) {
  o = o || {};
  var plain = String(value === null || value === undefined ? '' : value).replace(/<[^>]*>/g, '').replace(/&[a-z#0-9]+;/gi, 'x');
  var text = o.text !== undefined ? !!o.text : (plain.length > 9 && /[A-Za-z]{3}/.test(plain));
  var sub = o.sub === undefined || o.sub === null ? '' : String(o.sub);
  return QK.statTile({ label: label, value: value, sub: sub + (o.spark ? '<span class="fb-stat-spark">' + o.spark + '</span>' : ''), html: true, cls: o.cls, tip: o.tip, text: text,
    signal: !!o.signal, pctl: isNum(o.pctl) ? o.pctl : null, href: o.href || null, unit: o.unit, trend: o.trend, delta: o.delta, deltaFmt: o.deltaFmt });
}
function kpis(list, cls) { return '<div class="qk-stats fb-kpis' + (cls ? ' ' + cls : '') + '">' + list.join('') + '</div>'; }
function badge(text, kind, tip) { return '<span class="qk-badge' + (kind ? ' ' + kind : '') + '"' + (tip ? ' data-tip="' + esc(tip) + '"' : '') + '>' + esc(text) + '</span>'; }
function muted(text) { return '<p class="fb-muted">' + text + '</p>'; }
function empty(title, text) { return QK.empty(title, text); }
/* The kit's "i" explainer note (QK.note): one or two friendly sentences on what a number means. HTML in. */
function note(html) { return QK.note(html, { cls: 'fb-note' }); }
/* An italic aside (QK.aside): a one-line reason beside a number. Text in. */
function aside(text) { return QK.aside(text); }
/* The page crumb: [[href, label], ..., last label]. */
function crumb(items) {
  return '<nav class="fb-crumb" aria-label="Breadcrumb">' + items.map(function (x, i) {
    var last = i === items.length - 1;
    var t = Array.isArray(x) ? (x[0] ? '<a href="' + esc(x[0]) + '">' + esc(x[1]) + '</a>' : esc(x[1])) : esc(x);
    return t + (last ? '' : '<span aria-hidden="true">›</span>');
  }).join('') + '</nav>';
}
function loading(kind, n) { return QK.skeleton(kind || 'lines', n || 4); }
/* Page head (Design System 2.0 large section head, the page's h1): kicker (HTML), title, sub line (HTML),
   right-hand actions (HTML). */
function pageHead(kicker, title, sub, right) {
  return '<header class="qk-sh lg fb-head"><div class="qk-sh-main">' + (kicker ? '<div class="qk-sh-kicker">' + kicker + '</div>' : '') +
    '<h1 class="qk-sh-title">' + esc(title) + '</h1>' + (sub ? '<p class="qk-sh-sub">' + sub + '</p>' : '') + '</div>' +
    (right ? '<div class="qk-sh-actions">' + right + '</div>' : '') + '</header>';
}
/* A section head inside a page (v2): title, sub (HTML), actions (HTML), kicker (text). */
function secHead(title, sub, actions, kicker, id) {
  return QK.sectionHead({ kicker: kicker || '', title: title, sub: sub || '', actions: actions || '', html: true, id: id });
}
/* Our chances as 538-style bars (kit QK.chances): rows [{label, p, href, sub, mark, color}], opts {limit, max, oursName}.
   Football has no club colours in its payloads, so the bars are the signal colour. */
function chances(rows, opts) { return QK.chances(rows, opts || {}); }
/* Link tabs inside a page: items [[href, label, key, count?]], the active key. */
function subnav(items, active, label) {
  return '<nav class="fb-subnav" aria-label="' + esc(label || 'Views') + '"><div class="qk-tabs" role="tablist">' + items.map(function (i) {
    var on = i[2] === active;
    return '<a class="qk-tab" role="tab" href="' + esc(i[0]) + '" aria-selected="' + (on ? 'true' : 'false') + '"' + (on ? ' aria-current="page"' : '') + '>' + esc(i[1]) + (isNum(i[3]) ? ' <span class="fb-tabn">' + i[3] + '</span>' : '') + '</a>';
  }).join('') + '</div></nav>';
}
/* Segmented control: opts [[value, label]]. Wire with wireSeg(root, id, cb). */
function seg(id, opts, cur, label) {
  return '<div class="qk-seg" id="' + esc(id) + '" role="group" aria-label="' + esc(label || 'View') + '">' + opts.map(function (o) {
    return '<button type="button" data-value="' + esc(o[0]) + '" aria-pressed="' + (String(o[0]) === String(cur) ? 'true' : 'false') + '">' + esc(o[1]) + '</button>';
  }).join('') + '</div>';
}
function wireSeg(root, id, cb) { var n = (root || document).querySelector('#' + id); if (n) QK.seg(n, cb); }
/* A <select>: opts [[value, label]] or [{group, items: [[v, l]]}]. */
function select(id, opts, cur, label, cls) {
  var o1 = function (o) { return '<option value="' + esc(o[0]) + '"' + (String(o[0]) === String(cur) ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; };
  return '<select class="qk-select' + (cls ? ' ' + cls : '') + '" id="' + esc(id) + '" aria-label="' + esc(label || id) + '">' + opts.map(function (o) {
    return o && o.group ? '<optgroup label="' + esc(o.group) + '">' + o.items.map(o1).join('') + '</optgroup>' : o1(o);
  }).join('') + '</select>';
}
/* A filter toolbar: items are HTML (wrap each control in <label><span>Name</span>…</label> via field()). */
function toolbar(items, cls) { return '<div class="fb-toolbar' + (cls ? ' ' + cls : '') + '">' + items.filter(Boolean).join('') + '</div>'; }
function field(label, control) { return '<label class="fb-field"><span>' + esc(label) + '</span>' + control + '</label>'; }
/* A kit table. cols: [{key, label, num, fmt(v, row) -> html, sort: false, tip, sticky, cls, pctl, d}], rows: objects.
 * opts: {sort: {key, dir}, rank, dense (default true), maxHeight, caption}. Returns the QK.table handle. */
function table(el, cols, list, opts) {
  var node = typeof el === 'string' ? document.getElementById(el) : el;
  if (!node) return null;
  var o = opts || {};
  return QK.table(node, { columns: cols, rows: list, sort: o.sort || null, rank: !!o.rank, dense: o.dense !== false, maxHeight: o.maxHeight, caption: o.caption });
}
function set(id, html) { var n = document.getElementById(id); if (n) n.innerHTML = html; return n; }
function pctl(p) { return QK.pctlChip(p); }
/* A single-probability bar with its value: p in 0..1. */
function probBar(p, colour, max) {
  if (!isNum(p)) return '<span class="qk-muted">—</span>';
  var w = Math.max(0, Math.min(1, p / (max || 1))) * 100;
  return '<span class="fb-pbar"><span class="fb-pbar-t"><span style="width:' + w.toFixed(1) + '%;background:' + esc(colour || 'var(--c-1)') + '"></span></span><span class="fb-pbar-v">' + pct(p, p < 0.1 && p > 0 ? 1 : 0) + '</span></span>';
}
function deltaHTML(v, d) { return !isNum(v) ? '<span class="qk-muted">—</span>' : '<span class="' + (v > 0 ? 'fb-up' : v < 0 ? 'fb-down' : '') + '">' + signed(v, d === undefined ? 0 : d) + '</span>'; }
/* "Show more" for long lists: returns html + wires later with wireMore(root). */
function heatColour(t) {
  var a = Math.round(Math.min(1, Math.abs(t)) * 70);
  return 'color-mix(in srgb, ' + (t < 0 ? 'var(--div-neg)' : 'var(--div-pos)') + ' ' + a + '%, transparent)';
}

// ── shell, search, competition picker ─────────────────────────────────────

var SECTION_HREF = { overview: '#/', fixtures: '#/matches', standings: '#/competitions', teams: '#/clubs', players: '#/players', value: '#/value', fantasy: '#/fantasy', lab: '#/lab', model: '#/model' };
function compPickerHTML() {
  var groups = FAMILIES.map(function (f) {
    return { group: f.label, items: INDEX.comps.filter(function (c) { return c.ok && familyOf(c) === f.key; }).map(function (c) { return [c.slug, c.name]; }) };
  }).filter(function (g) { return g.items.length; });
  return '<label class="fb-picker">' + select('fb-comp-pick', [['', 'Competition…']].concat(groups), '', 'Go to a competition') + '</label>';
}
/* The nav's competition picker shows the open competition (or the prompt). */
function setCompPicker(slug) {
  state.comp = slug || null;
  var sel = document.getElementById('fb-comp-pick');
  if (sel) sel.value = slug && comp(slug) ? slug : '';
}
/* Search rows; w ranks matches that start equally well (kit QK.search): competitions, then clubs by reach, then
   players by market value and minutes, so a star comes before a namesake in the reserves. */
function searchRows() {
  return Promise.all([clubsIndex(), namesIndex()]).then(function (arr) {
    var out = [];
    INDEX.comps.filter(function (c) { return c.ok; }).forEach(function (c) {
      out.push({ sport: 'football', t: c.name, s: 'Competition · ' + (c.country || (FAMILIES.filter(function (f) { return f.key === familyOf(c); })[0] || {}).label || ''), href: href.comp(c.slug), w: 6 });
    });
    var clubs = arr[0].list.slice().sort(function (a, b) { return (b.home ? 1 : 0) - (a.home ? 1 : 0) || (b.comps || []).length - (a.comps || []).length; });
    clubs.forEach(function (t) {
      out.push({ sport: 'football', t: t.name, s: (t.national ? 'National team' : 'Club') + (t.home ? ' · ' + compName(t.home, true) : t.country ? ' · ' + t.country : ''), href: href.club(t.id),
        w: 3 + (t.home ? 1 : 0) + Math.min(3, (t.comps || []).length) * 0.3 });
    });
    arr[1].list.forEach(function (p) {
      out.push({ sport: 'football', t: p.name, s: (POS_LABEL[p.pos] || 'Player') + (p.club ? ' · ' + p.club : '') + (p.nt ? ' · ' + p.nt : ''), href: href.player(p.id),
        w: arr[1].names ? 2.5 * p._rank : (isNum(p.mv) && p.mv > 0 ? Math.max(0, Math.log10(p.mv) - 4) : 0) + Math.min(1, (isNum(p.min) ? p.min : 0) / 3000) });
    });
    [['Matches today', '#/matches'], ['Value leaderboard', '#/value'], ['Transfers', '#/value/transfers'], ['Transfer simulator', '#/value/simulator'],
      ['Fantasy', '#/fantasy'], ['Player lab', '#/lab'], ['Compare players', '#/compare/players'], ['Compare clubs', '#/compare/clubs'], ['Clubs on one scale', '#/clubs'],
      ['National teams', '#/clubs/nations'], ['Leaders across competitions', '#/players/leaders'], ['Methodology', '#/model/methodology'], ['Glossary', '#/model/glossary']]
      .forEach(function (p) { out.push({ sport: 'football', t: p[0], s: 'Page', href: p[1] }); });
    return out;
  });
}
function bootShell() {
  var secs = QK.sections('football', { fixtures: 'Matches', standings: 'Competitions', teams: 'Clubs', value: 'Value & Transfers' }).map(function (s) {
    s.href = SECTION_HREF[s.key] || s.href;
    return s;
  });
  SHELL = QK.shell({ sport: 'football', section: 'overview', sections: secs, ctx: compPickerHTML(), search: { load: searchRows } });
  var sel = document.getElementById('fb-comp-pick');
  if (sel) sel.addEventListener('change', function () { if (sel.value) go(href.comp(sel.value)); });
  var foot = document.getElementById('qk-footer');
  if (foot) foot.insertAdjacentHTML('beforeend', '<div class="fb-footnote">The Quant Footballer · data from Sofascore · Dixon-Coles and Elo models, Monte Carlo seasons · ' +
    (INDEX.updated_at ? 'updated ' + esc(fmtStamp(INDEX.updated_at)) + ' · ' : '') + '<a href="#/model/disclaimer">Disclaimer and terms</a> · <a href="#/model/methodology">Methodology</a> · ' +
    'For information and entertainment only; not betting advice. 18+.</div>');
  var fv = document.getElementById('first-visit-notice');
  var seen = false;
  try { seen = window.localStorage.getItem('qf-notice-v1') === '1'; } catch (e) { seen = false; }
  if (fv && !seen) fv.hidden = false;
  var btn = document.getElementById('fv-dismiss');
  if (btn) btn.addEventListener('click', function () { fv.hidden = true; try { window.localStorage.setItem('qf-notice-v1', '1'); } catch (e) { /* private mode */ } });
}
/* Live dot on the sport switcher while any match is in play (hub.json, re-read every minute while live). */
function hubLive(h) {
  var live = false;
  var days = (h || {}).days || {};
  Object.keys(days).forEach(function (k) { (days[k] || []).forEach(function (m) { if (m.status === 'live' && !staleLive(m)) live = true; }); });
  if (SHELL) SHELL.setLive({ football: live });
  return live;
}

/* #/<slug>/team/<club-slug> (old club pages): find the club's id in the competition's teams.json. */
HANDLERS.teamLegacy = function (el, p) {
  el.innerHTML = loading('lines', 3);
  return compFile(p.slug, 'teams').then(function (d) {
    if (!alive(el)) return;
    var teams = (d || {}).teams || {};
    var slugOf = function (n) { return String(teams[n].slug || n).toLowerCase(); };
    var name = Object.keys(teams).filter(function (n) { return slugOf(n) === String(p.team).toLowerCase(); })[0];
    var tid = name && teams[name].team_id;
    var to = tid ? href.club(tid, { c: p.slug }) : href.comp(p.slug, 'clubs');
    try { history.replaceState(null, '', to); } catch (e) { location.hash = to; return; }
    render();
  });
};

function init() {
  /* clubs_index.json up front too: names for links and, once written, the club colours the v4 heroes and stripes use */
  Promise.all([load('competitions.json'), load('crests.json'), clubsIndex()]).then(function (arr) {
    var idx = arr[0];
    CRESTS = {};
    ((arr[1] || {}).ids || []).forEach(function (id) { CRESTS[String(id)] = 1; });
    INDEX.comps = (idx || {}).competitions || [];
    INDEX.updated_at = (idx || {}).updated_at || null;
    INDEX.bySlug = {};
    INDEX.comps.forEach(function (c) { INDEX.bySlug[c.slug] = c; });
    bootShell();
    load('hub.json').then(hubLive);
    booted = true;
    window.addEventListener('hashchange', render);
    render();
  });
}

return {
  state: state, INDEX: INDEX, route: route, go: go, render: render, parseHash: parseHash, legacyRedirect: legacyRedirect, fixLinks: fixLinks,
  ROUTES: ROUTES, COMP_TABS: COMP_TABS, COMP_TAB_MAP: COMP_TAB_MAP, onLeave: onLeave, interval: interval, setHashQuiet: setHashQuiet, setQuery: setQuery,
  alive: alive, init: init, qs: qs, enc: enc, merge: merge,
  load: load, reload: reload, loadAll: loadAll, rows: rows, FILES: FILES, KIND_FILES: KIND_FILES, FAMILIES: FAMILIES,
  comps: comps, comp: comp, familyOf: familyOf, compName: compName, hasFile: hasFile, compFile: compFile, compFiles: compFiles,
  currentSeason: currentSeason, isLastEdition: isLastEdition, shortSeason: shortSeason, seasonsOf: seasonsOf, loadPastSeason: loadPastSeason,
  clubsIndex: clubsIndex, hasCrest: hasCrest, clubRow: clubRow, clubName: clubName, clubColour: clubColour, clubAlt: clubAlt, clubCode: clubCode, heroGame: heroGame, peopleIndex: peopleIndex, crestUrl: crestUrl, tidFromCrest: tidFromCrest,
  MSET: MSET, ADJ_EXTRA: ADJ_EXTRA, peerGroup: peerGroup, groupKeys: groupKeys, metricInfo: metricInfo, isEarly: isEarly, peerLine: peerLine, peerMin: peerMin,
  roles: roles, rolesFor: rolesFor, rowRole: rowRole, rowGar: rowGar, roleOf: roleOf, garOver: garOver, peerPct: peerPct, fmtSet: fmtSet,
  personId: personId, labIndex: labIndex, labView: labView, labScopeName: labScopeName, labScopeOptions: labScopeOptions, labWindowText: labWindowText, labPct: labPct, LAB_SCOPES: LAB_SCOPES,
  isNum: isNum, esc: esc, num: num, int: int, pct: pct, signed: signed, money: money, fmtMetric: fmtMetric, parseDate: parseDate,
  fmtDate: fmtDate, fmtTime: fmtTime, fmtStamp: fmtStamp, localDay: localDay, today: today, relDay: relDay, ordinal: ordinal, ageOf: ageOf,
  median: median, sum: sum, wavg: wavg, initials: initials, surname: surname, eraKey: eraKey, eraLabel: eraLabel, MONTHS: MONTHS, DAYS: DAYS,
  KIND_LABEL: KIND_LABEL, KIND_ORDER: KIND_ORDER, kindOf: kindOf, kindChip: kindChip, kindColor: kindColor, kindColorHex: kindColorHex,
  POS_LABEL: POS_LABEL, POS_GROUP: POS_GROUP, posBadge: posBadge, ROUND_LABELS: ROUND_LABELS, STAGE_LABELS: STAGE_LABELS,
  stageLabel: stageLabel, roundText: roundText, stageText: stageText, coverageChip: coverageChip, formChips: formChips,
  href: href, crest: crest, clubLink: clubLink, playerLink: playerLink, compLink: compLink,
  toGame: toGame, matchCard: matchCard, gameCard: matchCard, wpBar: wpBar, staleLive: staleLive, probBar3: probBar3, scoreText: scoreText, fixtureRow: fixtureRow,
  card: card, grid: grid, chartBox: chartBox, kpi: kpi, kpis: kpis, badge: badge, muted: muted, empty: empty, note: note, aside: aside, crumb: crumb, loading: loading,
  pageHead: pageHead, secHead: secHead, chances: chances, subnav: subnav, seg: seg, wireSeg: wireSeg, select: select, toolbar: toolbar, field: field, table: table, set: set,
  pctl: pctl, probBar: probBar, deltaHTML: deltaHTML, heatColour: heatColour, setCompPicker: setCompPicker, hubLive: hubLive
};
})();
